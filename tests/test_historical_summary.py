from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent import AgentLoop, ConversationRunner, ConversationState, ConversationTurn
from context_compression import HistoricalSummaryCompactor, HistoricalSummaryPolicy
from datasets import DatasetRegistry
from tools.handlers import build_default_registry


class SummaryClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[dict[str, Any]]] = []

    def summarize(
        self, *, turns: list[dict[str, Any]], max_chars: int
    ) -> dict[str, Any]:
        del max_chars
        self.calls.append(copy.deepcopy(turns))
        if self.fail:
            raise RuntimeError("summary unavailable")
        refs = [
            ref
            for turn in turns
            for ref in turn["toolRefs"]
            if ref["ok"] is True
        ]
        return {
            "coveredTurnIds": [turn["turnId"] for turn in turns],
            "userIntents": ["延续历史分析"],
            "confirmedActions": ["已调用确定性分析工具"],
            "confirmedToolRefs": [
                {"callId": ref["callId"], "toolName": ref["toolName"]}
                for ref in refs[:1]
            ],
            "decisions": [],
            "constraints": [],
            "tentativeContext": ["用户曾推测原因，尚未验证"],
            "unresolvedQuestions": [],
        }


class InspectingModel:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del tools
        self.calls.append(copy.deepcopy(messages))
        return {"type": "final_answer", "content": "上下文完整。"}


class UnsafeCertaintyClient(SummaryClient):
    def summarize(
        self, *, turns: list[dict[str, Any]], max_chars: int
    ) -> dict[str, Any]:
        result = super().summarize(turns=turns, max_chars=max_chars)
        result["confirmedActions"] = ["可能是促销导致"]
        result["tentativeContext"] = []
        return result


def policy(**overrides: Any) -> HistoricalSummaryPolicy:
    values = {
        "trigger_history_chars": 1,
        "trigger_eligible_chars": 1,
        "min_eligible_turns": 2,
        "keep_recent_turns": 2,
        "refresh_new_turns": 2,
        "refresh_new_chars": 100_000,
        "max_summary_chars": 4_000,
    }
    values.update(overrides)
    return HistoricalSummaryPolicy(**values)


def make_turn(index: int, *, payload: int = 80) -> ConversationTurn:
    call_id = f"call-{index}"
    observation = {
        "tool": "basic_stats",
        "iteration": 1,
        "ok": True,
        "data": {"value": index, "payload": "x" * payload},
        "error": None,
        "duration": 0.1,
        "truncated": False,
    }
    return ConversationTurn(
        turn_id=f"turn_{index}",
        messages=[
            {"role": "user", "content": f"历史问题 {index}"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "basic_stats", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": "basic_stats",
                "content": json.dumps(observation, ensure_ascii=False),
            },
            {"role": "assistant", "content": f"历史回答 {index}"},
        ],
        tool_results=[
            {
                "callId": call_id,
                "toolName": "basic_stats",
                "arguments": {"metric": "销售额", "operation": "sum"},
                "toolResult": {
                    "ok": True,
                    "data": {"value": index},
                    "error": None,
                    "duration": 0.1,
                    "truncated": False,
                },
            }
        ],
        dataset_ids=[],
        stop_reason="final_answer",
    )


def make_plain_turn(index: int) -> ConversationTurn:
    return ConversationTurn(
        turn_id=f"turn_{index}",
        messages=[
            {"role": "user", "content": f"纯对话问题 {index}"},
            {"role": "assistant", "content": f"纯对话回答 {index}"},
        ],
        tool_results=[],
        dataset_ids=[],
        stop_reason="final_answer",
    )


class HistoricalSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def state(self, count: int) -> ConversationState:
        return ConversationState(
            conversation_id="conv-summary",
            dataset_registry=DatasetRegistry(self.root / "derived"),
            turns=[make_turn(index) for index in range(1, count + 1)],
        )

    def test_below_threshold_keeps_existing_history_view_without_summary(self) -> None:
        state = self.state(4)
        client = SummaryClient()
        compactor = HistoricalSummaryCompactor(
            client,
            policy(trigger_history_chars=100_000, trigger_eligible_chars=100_000),
        )

        result = compactor.compact(state)

        self.assertFalse(result.report["triggered"])
        self.assertEqual(result.messages, state.history_messages())
        self.assertEqual(client.calls, [])

    def test_only_old_turns_are_summarized_and_real_state_is_unchanged(self) -> None:
        state = self.state(6)
        original = copy.deepcopy(state.turns)
        client = SummaryClient()
        result = HistoricalSummaryCompactor(client, policy()).compact(state)

        self.assertTrue(result.report["triggered"])
        self.assertFalse(result.report["fallback"])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            [turn["turnId"] for turn in client.calls[0]],
            ["turn_1", "turn_2", "turn_3", "turn_4"],
        )
        self.assertEqual(result.messages[0]["name"], "historical_summary")
        raw_text = json.dumps(result.messages[1:], ensure_ascii=False)
        self.assertIn("历史问题 5", raw_text)
        self.assertIn("历史问题 6", raw_text)
        self.assertNotIn("历史问题 1", raw_text)
        self.assertIn("尚未验证", result.messages[0]["content"])
        self.assertEqual(state.turns, original)

    def test_cache_reuses_summary_and_refreshes_only_after_enough_new_turns(self) -> None:
        state = self.state(6)
        client = SummaryClient()
        compactor = HistoricalSummaryCompactor(client, policy())

        first = compactor.compact(state)
        second = compactor.compact(state)
        state.turns.append(make_turn(7))
        third = compactor.compact(state)
        state.turns.append(make_turn(8))
        fourth = compactor.compact(state)

        self.assertFalse(first.report["summaryReused"])
        self.assertTrue(second.report["summaryReused"])
        self.assertTrue(third.report["summaryReused"])
        self.assertEqual(third.report["uncoveredRawTurns"], 1)
        self.assertIn("历史问题 5", json.dumps(third.messages, ensure_ascii=False))
        self.assertFalse(fourth.report["summaryReused"])
        self.assertEqual(len(client.calls), 2)

    def test_summary_failure_returns_v11_fallback_view(self) -> None:
        state = self.state(14)
        client = SummaryClient(fail=True)
        result = HistoricalSummaryCompactor(client, policy()).compact(state)

        self.assertTrue(result.report["triggered"])
        self.assertTrue(result.report["fallback"])
        self.assertEqual(result.report["fallbackTo"], "context_compression_v1_1")
        self.assertEqual(result.messages, state.history_messages())
        self.assertEqual(len(result.messages), len(state.history_messages()))

    def test_uncertain_content_cannot_be_promoted_to_confirmed_fact(self) -> None:
        state = self.state(6)
        result = HistoricalSummaryCompactor(
            UnsafeCertaintyClient(), policy()
        ).compact(state)

        self.assertTrue(result.report["fallback"])
        self.assertEqual(result.report["errorType"], "ValueError")
        self.assertEqual(result.messages, state.history_messages())

    def test_latest_tool_result_turn_is_pinned_even_when_older_than_recent_window(self) -> None:
        state = self.state(4)
        state.turns.extend(make_plain_turn(index) for index in range(5, 9))
        client = SummaryClient()
        result = HistoricalSummaryCompactor(client, policy()).compact(state)

        summarized_ids = [turn["turnId"] for turn in client.calls[0]]
        self.assertNotIn("turn_4", summarized_ids)
        self.assertEqual(result.report["pinnedRawTurns"], 1)
        pinned = next(
            item for item in result.messages if item.get("tool_call_id") == "call-4"
        )
        self.assertEqual(json.loads(pinned["content"])["data"]["value"], 4)

    def test_runner_preserves_protected_context_and_records_summary_audit(self) -> None:
        model = InspectingModel()
        client = SummaryClient()
        compactor = HistoricalSummaryCompactor(client, policy())
        runner = ConversationRunner(
            AgentLoop(model, build_default_registry()),
            dataset_registry=DatasetRegistry(self.root / "runner-derived"),
            conversation_id="conv-summary",
            historical_compactor=compactor,
        )
        runner.state.turns = [make_turn(index) for index in range(1, 7)]
        runner.state.open_todos = [
            {"id": "goal", "content": "完成当前销售分析", "status": "in_progress"}
        ]

        result = runner.run("当前用户问题")
        messages = model.calls[0]

        self.assertEqual(messages[0]["role"], "system")
        self.assertTrue(any(item.get("name") == "historical_summary" for item in messages))
        self.assertTrue(
            any(str(item.get("content", "")).startswith("当前 Todo 概览") for item in messages)
        )
        self.assertTrue(any(item.get("content") == "当前用户问题" for item in messages))
        latest_tool = next(
            item for item in messages if item.get("tool_call_id") == "call-6"
        )
        self.assertEqual(json.loads(latest_tool["content"])["data"]["value"], 6)
        audit = next(
            item for item in result.context_reports if item.get("phase") == "historical_summary"
        )
        self.assertTrue(audit["triggered"])
        self.assertEqual(result.final_answer, "上下文完整。")


if __name__ == "__main__":
    unittest.main()
