from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent import AgentLoop
from context_compression import CompressionPolicy, ContextCompressor
from tools.handlers import build_default_registry


ROOT = Path(__file__).resolve().parents[1]
SALES = ROOT / "tests" / "fixtures" / "sales.csv"


class ScriptedModel:
    def __init__(self, decisions: list[Any]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        decision = self.decisions[len(self.calls) - 1]
        return decision(messages) if callable(decision) else decision


class FailingCompressor:
    def compress(self, **kwargs: Any) -> Any:
        del kwargs
        raise RuntimeError("compression failed")


def low_policy(**overrides: Any) -> CompressionPolicy:
    values = {
        "trigger_total_chars": 1,
        "target_total_chars": 2_000,
        "single_tool_result_chars": 100,
        "message_count_trigger": 5,
        "dataset_column_trigger": 5,
        "dataset_profile_column_limit": 6,
        "keep_recent_turns": 2,
        "keep_recent_tool_results": 2,
        "memory_view_chars": 300,
        "keep_completed_todos": 1,
    }
    values.update(overrides)
    return CompressionPolicy(**values)


def observation(call_id: str, value: int, *, payload: str = "") -> list[dict[str, Any]]:
    return [
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
            "content": json.dumps(
                {
                    "tool": "basic_stats",
                    "iteration": 1,
                    "ok": True,
                    "data": {"value": value, "payload": payload},
                    "error": None,
                    "duration": 1.25,
                    "truncated": False,
                },
                ensure_ascii=False,
            ),
        },
    ]


class ContextCompressionTests(unittest.TestCase):
    def test_below_threshold_returns_an_equal_view_without_triggering(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "计算销售额"},
        ]
        tools = [{"type": "function", "function": {"name": "basic_stats"}}]

        result = ContextCompressor().compress(messages=messages, tools=tools)

        self.assertFalse(result.report["triggered"])
        self.assertEqual(result.messages, messages)
        self.assertIsNot(result.messages, messages)

    def test_total_character_trigger_is_inclusive_at_the_exact_boundary(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "计算销售额"},
        ]
        tools = [{"type": "function", "function": {"name": "basic_stats"}}]
        probe = ContextCompressor(
            CompressionPolicy(trigger_total_chars=100_000, message_count_trigger=100)
        ).compress(messages=messages, tools=tools)
        exact = probe.report["originalChars"]
        below = ContextCompressor(
            CompressionPolicy(trigger_total_chars=exact + 1, message_count_trigger=100)
        ).compress(messages=messages, tools=tools)
        boundary = ContextCompressor(
            CompressionPolicy(trigger_total_chars=exact, message_count_trigger=100)
        ).compress(messages=messages, tools=tools)

        self.assertFalse(below.report["triggered"])
        self.assertTrue(boundary.report["triggered"])
        self.assertIn("total_chars", boundary.report["triggerReasons"])

    def test_compression_preserves_real_input_system_current_user_and_latest_tool(self) -> None:
        columns = [
            {
                "name": "销售额" if index == 0 else f"字段{index}",
                "type": "number" if index < 3 else "text",
                "missing": index,
                "nonEmpty": 100 - index,
                "distinct": 10,
                "invalidNumeric": 0,
                "invalidDate": 0,
            }
            for index in range(100)
        ]
        prior = [
            {
                "callId": f"prior-{index}",
                "toolName": "basic_stats",
                "arguments": {"metric": "销售额", "operation": "sum"},
                "toolResult": {
                    "ok": True,
                    "data": {"value": index, "payload": "x" * 600},
                    "error": None,
                    "duration": 2.0,
                    "truncated": False,
                },
            }
            for index in range(6)
        ]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "PROTECTED SYSTEM"},
            {
                "role": "system",
                "name": "memory_context",
                "content": "长期 Memory：\nKV preferred_metric=销售额\n" + "经验信息\n" * 200,
            },
            {
                "role": "system",
                "name": "conversation_context",
                "content": "当前会话临时状态："
                + json.dumps({"lastMetric": "销售额", "priorToolResults": prior}, ensure_ascii=False),
            },
            {
                "role": "system",
                "content": "当前 Todo 概览（计划状态，不代表工具已执行）："
                + json.dumps(
                    {
                        "completed": [
                            {"id": f"done-{index}", "content": "完成", "status": "completed"}
                            for index in range(5)
                        ],
                        "in_progress": [
                            {"id": "active", "content": "当前目标", "status": "in_progress"}
                        ],
                        "pending": [],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        for index in range(6):
            messages.append({"role": "user", "content": f"历史问题 {index}"})
            messages.extend(observation(f"history-{index}", index, payload="y" * 500))
            messages.append({"role": "assistant", "content": f"历史回答 {index}"})
        messages.append(
            {
                "role": "user",
                "content": "当前计算销售额",
                "dataset_context": {
                    "datasetCount": 1,
                    "datasets": [
                        {
                            "datasetId": "ds_current",
                            "filename": "wide.csv",
                            "rowCount": 100,
                            "columnCount": 100,
                            "columns": columns,
                            "dateRanges": [],
                            "derived": False,
                            "lineage": None,
                        }
                    ],
                },
            }
        )
        messages.extend(observation("latest-critical", 999, payload="LATEST" * 200))
        original = copy.deepcopy(messages)
        latest_content = messages[-1]["content"]

        result = ContextCompressor(low_policy()).compress(messages=messages, tools=[])

        self.assertTrue(result.report["triggered"])
        self.assertLess(result.report["viewChars"], result.report["originalChars"])
        self.assertEqual(messages, original)
        self.assertEqual(result.messages[0]["content"], "PROTECTED SYSTEM")
        current = next(item for item in result.messages if item.get("content") == "当前计算销售额")
        self.assertIn("columnsByType", current["dataset_context"]["datasets"][0])
        compact_dataset = current["dataset_context"]["datasets"][0]
        visible_names = sum(len(names) for names in compact_dataset["columnsByType"].values())
        self.assertEqual(visible_names, 6)
        self.assertEqual(compact_dataset["omittedColumnCount"], 94)
        self.assertEqual(compact_dataset["relevantColumns"][0]["name"], "销售额")
        self.assertEqual(result.messages[-1]["content"], latest_content)
        self.assertLessEqual(
            len([item for item in result.messages if item.get("role") == "user"]), 3
        )

    def test_tool_todo_memory_and_dataset_views_are_compacted_deterministically(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "system",
                "name": "memory_context",
                "content": "长期 Memory：\nKV preferred_metric=销售额\n" + "semantic\n" * 100,
            },
            {
                "role": "system",
                "content": "当前 Todo 概览（计划状态，不代表工具已执行）："
                + json.dumps(
                    {
                        "completed": [
                            {"id": "a", "content": "A", "status": "completed"},
                            {"id": "b", "content": "B", "status": "completed"},
                        ],
                        "in_progress": [
                            {"id": "c", "content": "C", "status": "in_progress"}
                        ],
                        "pending": [],
                    },
                    ensure_ascii=False,
                ),
            },
            {"role": "user", "content": "旧问题"},
            *observation("old-result", 10),
            {"role": "assistant", "content": "旧回答"},
            {"role": "user", "content": "当前问题"},
            *observation("latest-result", 20),
        ]
        result = ContextCompressor(low_policy(keep_recent_turns=3)).compress(
            messages=messages, tools=[]
        )

        memory = next(item for item in result.messages if item.get("name") == "memory_context")
        self.assertLessEqual(len(memory["content"]), 330)
        todo = next(
            item
            for item in result.messages
            if str(item.get("content", "")).startswith("当前 Todo 概览")
        )
        todo_data = json.loads(todo["content"].split("：", 1)[1])
        self.assertEqual(todo_data["completedCount"], 2)
        self.assertEqual(len(todo_data["completed"]), 1)
        self.assertEqual(todo_data["in_progress"][0]["id"], "c")
        old_tool = next(item for item in result.messages if item.get("tool_call_id") == "old-result")
        old_data = json.loads(old_tool["content"])
        self.assertNotIn("duration", old_data)
        self.assertEqual(old_data["data"]["value"], 10)

    def test_compression_failure_falls_back_to_original_context(self) -> None:
        model = ScriptedModel([{"type": "final_answer", "content": "正常完成。"}])
        state = AgentLoop(
            model,
            build_default_registry(),
            context_compressor=FailingCompressor(),
        ).run("简单问题")

        self.assertEqual(state.final_answer, "正常完成。")
        self.assertEqual(state.stop_reason, "final_answer")
        self.assertEqual(state.context_errors[0]["error_type"], "RuntimeError")
        self.assertEqual(len(model.calls[0]["messages"]), 2)

    def test_wide_dataset_profile_is_bounded_and_keeps_question_columns(self) -> None:
        columns = [
            {
                "name": "目标销售额" if index == 1_199 else f"字段{index}",
                "type": "number" if index % 3 == 0 else "text",
                "missing": index % 5,
                "nonEmpty": 100 - (index % 5),
                "distinct": 20,
            }
            for index in range(1_200)
        ]
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "user",
                "content": "分析目标销售额",
                "dataset_context": {
                    "datasetCount": 1,
                    "datasets": [
                        {
                            "datasetId": "ds_wide",
                            "filename": "wide.csv",
                            "columnCount": len(columns),
                            "columns": columns,
                        }
                    ],
                },
            },
        ]
        original = copy.deepcopy(messages)

        result = ContextCompressor(
            low_policy(dataset_profile_column_limit=12)
        ).compress(messages=messages, tools=[])

        compact = result.messages[-1]["dataset_context"]["datasets"][0]
        visible_names = [
            name for names in compact["columnsByType"].values() for name in names
        ]
        self.assertEqual(len(visible_names), 12)
        self.assertIn("目标销售额", visible_names)
        self.assertEqual(compact["relevantColumns"][0]["name"], "目标销售额")
        self.assertEqual(compact["omittedColumnCount"], 1_188)
        self.assertIn("number", compact["columnsByType"])
        self.assertIn("text", compact["columnsByType"])
        self.assertEqual(messages, original)

    def test_chart_uses_full_state_after_the_model_view_is_compressed(self) -> None:
        def request_chart(messages: list[dict[str, Any]]) -> dict[str, Any]:
            latest = json.loads(messages[-1]["content"])
            self.assertEqual(latest["data"]["groups"][0]["group"], "华南")
            return {
                "type": "tool_call",
                "id": "compressed-chart",
                "name": "generate_chart",
                "arguments": {"sourceCallId": "compressed-source", "chartType": "bar"},
            }

        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "compressed-source",
                    "name": "group_compare",
                    "arguments": {"groupBy": "地区", "metric": "销售额", "operation": "sum"},
                },
                request_chart,
                {"type": "final_answer", "content": "完成。"},
            ]
        )
        with tempfile.TemporaryDirectory() as artifacts:
            state = AgentLoop(
                model,
                build_default_registry(),
                context_compressor=ContextCompressor(low_policy()),
            ).run("按地区画图", dataset=str(SALES), artifact_dir=artifacts)

            self.assertTrue(state.execution_trace[1]["success"])
            self.assertTrue(Path(state.execution_trace[1]["data"]["artifact"]["path"]).is_file())
            self.assertTrue(any(report["triggered"] for report in state.context_reports))
            self.assertEqual(state.execution_trace[0]["data"]["groups"][0]["group"], "华南")


if __name__ == "__main__":
    unittest.main()
