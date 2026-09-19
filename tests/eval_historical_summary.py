"""Deterministic evaluation for turn-level Historical Summary compaction."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent import AgentLoop, ConversationRunner, ConversationState
from context_compression import HistoricalSummaryCompactor
from datasets import DatasetRegistry
from test_historical_summary import (
    InspectingModel,
    SummaryClient,
    UnsafeCertaintyClient,
    make_plain_turn,
    make_turn,
    policy,
)
from tools.handlers import build_default_registry


RESULT = ROOT / "tests" / "results" / "historical-summary-evaluation.json"


class LatestToolAnswerModel:
    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del tools
        latest = next(
            (
                json.loads(message["content"])
                for message in reversed(messages)
                if message.get("role") == "tool"
            ),
            None,
        )
        if latest is None:
            context_message = next(
                message
                for message in messages
                if message.get("name") == "conversation_context"
            )
            context = json.loads(context_message["content"].split("：", 1)[1])
            prior = context.get("priorToolResults", [])
            latest = prior[-1]["toolResult"] if prior else None
        value = latest["data"]["value"] if latest is not None else None
        return {"type": "final_answer", "content": f"最新结果为 {value}。"}


def main() -> int:
    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="historical-summary-eval-") as directory:
        temp_root = Path(directory)

        small = ConversationState(
            conversation_id="small",
            dataset_registry=DatasetRegistry(temp_root / "small"),
            turns=[make_turn(index) for index in range(1, 5)],
        )
        small_client = SummaryClient()
        small_result = HistoricalSummaryCompactor(
            small_client,
            policy(trigger_history_chars=100_000, trigger_eligible_chars=100_000),
        ).compact(small)
        record(
            records,
            "HS-01",
            not small_result.report["triggered"] and not small_client.calls,
            small_result.report,
        )

        state = ConversationState(
            conversation_id="long",
            dataset_registry=DatasetRegistry(temp_root / "long"),
            turns=[make_turn(index, payload=1_000) for index in range(1, 21)],
        )
        original_turns = copy.deepcopy(state.turns)
        raw_chars = len(
            json.dumps(
                [message for turn in state.turns for message in turn.messages],
                ensure_ascii=False,
            )
        )
        client = SummaryClient()
        compactor = HistoricalSummaryCompactor(client, policy(keep_recent_turns=4))
        compacted = compactor.compact(state)
        view_chars = len(json.dumps(compacted.messages, ensure_ascii=False))
        reduction = 1 - view_chars / raw_chars
        raw_view = json.dumps(compacted.messages, ensure_ascii=False)
        summary_payload = json.loads(compacted.messages[0]["content"].split("：", 1)[1])
        source_tool_map = {
            result["callId"]: result["toolName"]
            for turn in original_turns[:16]
            for result in turn.tool_results
            if result["toolResult"]["ok"]
        }
        fact_refs_consistent = all(
            source_tool_map.get(ref["callId"]) == ref["toolName"]
            for ref in summary_payload["confirmedToolRefs"]
        )
        record(
            records,
            "HS-02",
            compacted.report["triggered"]
            and reduction >= 0.50
            and compacted.report["coveredTurns"] == 16
            and compacted.report["recentRawTurns"] == 4
            and "历史问题 17" in raw_view
            and "历史问题 20" in raw_view
            and fact_refs_consistent,
            {
                **compacted.report,
                "originalChars": raw_chars,
                "viewChars": view_chars,
                "reductionRatio": round(reduction, 4),
                "factRefsConsistent": fact_refs_consistent,
                "confirmedToolRefs": summary_payload["confirmedToolRefs"],
            },
        )
        record(
            records,
            "HS-03",
            state.turns == original_turns,
            {"conversationStateUnchanged": state.turns == original_turns},
        )

        reused = compactor.compact(state)
        state.turns.append(make_turn(21, payload=1_000))
        incremental = compactor.compact(state)
        record(
            records,
            "HS-04",
            reused.report["summaryReused"]
            and incremental.report["summaryReused"]
            and incremental.report["uncoveredRawTurns"] == 1
            and len(client.calls) == 1,
            {
                "summaryCalls": len(client.calls),
                "sameSourceReused": reused.report["summaryReused"],
                "uncoveredRawTurns": incremental.report["uncoveredRawTurns"],
            },
        )

        failed_state = ConversationState(
            conversation_id="failed",
            dataset_registry=DatasetRegistry(temp_root / "failed"),
            turns=[make_turn(index) for index in range(1, 15)],
        )
        failure = HistoricalSummaryCompactor(
            SummaryClient(fail=True), policy()
        ).compact(failed_state)
        unsafe = HistoricalSummaryCompactor(
            UnsafeCertaintyClient(), policy()
        ).compact(failed_state)
        record(
            records,
            "HS-05",
            failure.report["fallback"]
            and unsafe.report["fallback"]
            and failure.messages == failed_state.history_messages()
            and unsafe.messages == failed_state.history_messages(),
            {
                "modelFailureFallback": failure.report["fallback"],
                "unsafeSummaryFallback": unsafe.report["fallback"],
                "fallbackTo": failure.report.get("fallbackTo"),
            },
        )

        model = InspectingModel()
        runner = ConversationRunner(
            AgentLoop(model, build_default_registry()),
            dataset_registry=DatasetRegistry(temp_root / "runner"),
            conversation_id="runner",
            historical_compactor=HistoricalSummaryCompactor(SummaryClient(), policy()),
        )
        runner.state.turns = [make_turn(index) for index in range(1, 7)]
        runner.state.open_todos = [
            {"id": "goal", "content": "完成当前任务", "status": "in_progress"}
        ]
        run_state = runner.run("当前用户问题")
        model_messages = model.calls[0]
        protected = {
            "system": model_messages[0]["role"] == "system",
            "currentUser": any(
                item.get("content") == "当前用户问题" for item in model_messages
            ),
            "taskGoal": any(
                "完成当前任务" in str(item.get("content", ""))
                for item in model_messages
            ),
            "latestToolResult": any(
                item.get("tool_call_id") == "call-6" for item in model_messages
            ),
        }
        record(
            records,
            "HS-06",
            all(protected.values())
            and run_state.final_answer == "上下文完整。"
            and not run_state.context_errors,
            {"protected": protected, "answer": run_state.final_answer},
        )

        parity_turns = [make_turn(index) for index in range(1, 7)]
        parity_turns.extend(make_plain_turn(index) for index in range(7, 13))

        def answer_runner(name: str, *, with_summary: bool) -> ConversationRunner:
            active_compactor = (
                HistoricalSummaryCompactor(SummaryClient(), policy(keep_recent_turns=4))
                if with_summary
                else None
            )
            active_runner = ConversationRunner(
                AgentLoop(LatestToolAnswerModel(), build_default_registry()),
                dataset_registry=DatasetRegistry(temp_root / name),
                conversation_id=name,
                historical_compactor=active_compactor,
            )
            active_runner.state.turns = copy.deepcopy(parity_turns)
            return active_runner

        baseline_answer = answer_runner("parity-baseline", with_summary=False).run(
            "继续刚才结果"
        )
        compacted_answer = answer_runner("parity-summary", with_summary=True).run(
            "继续刚才结果"
        )
        record(
            records,
            "HS-07",
            baseline_answer.final_answer
            == compacted_answer.final_answer
            == "最新结果为 6。",
            {
                "baselineAnswer": baseline_answer.final_answer,
                "summaryAnswer": compacted_answer.final_answer,
                "semanticEqual": baseline_answer.final_answer
                == compacted_answer.final_answer,
            },
        )

        fallback_model = InspectingModel()
        fallback_runner = ConversationRunner(
            AgentLoop(fallback_model, build_default_registry()),
            dataset_registry=DatasetRegistry(temp_root / "fallback-runner"),
            conversation_id="fallback-runner",
            historical_compactor=HistoricalSummaryCompactor(
                SummaryClient(fail=True), policy()
            ),
        )
        fallback_runner.state.turns = [make_turn(index) for index in range(1, 15)]
        fallback_state = fallback_runner.run("fallback 后继续")
        summary_fallback_report = next(
            item
            for item in fallback_state.context_reports
            if item.get("phase") == "historical_summary"
        )
        v11_report = next(
            item
            for item in fallback_state.context_reports
            if item.get("phase") != "historical_summary"
        )
        record(
            records,
            "HS-08",
            summary_fallback_report["fallback"]
            and summary_fallback_report["fallbackTo"] == "context_compression_v1_1"
            and v11_report["triggered"]
            and fallback_state.final_answer == "上下文完整。",
            {
                "summaryFallback": summary_fallback_report["fallback"],
                "fallbackTo": summary_fallback_report["fallbackTo"],
                "v11Triggered": v11_report["triggered"],
                "answer": fallback_state.final_answer,
            },
        )

    report = {
        "passed": all(item["passed"] for item in records),
        "passedCases": sum(item["passed"] for item in records),
        "totalCases": len(records),
        "cases": records,
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Historical summary evaluation: {report['passedCases']}/{report['totalCases']}")
    print(f"Report: {RESULT}")
    return 0 if report["passed"] else 1


def record(
    records: list[dict[str, Any]], case_id: str, passed: bool, details: dict[str, Any]
) -> None:
    records.append({"caseId": case_id, "passed": passed, "details": details})
    print(f"{'PASS' if passed else 'FAIL'} {case_id}")


if __name__ == "__main__":
    raise SystemExit(main())
