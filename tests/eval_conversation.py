"""Deterministic P1 conversation-history evaluation and auditable trace."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import AgentLoop, ConversationRunner
from datasets import DatasetRegistry
from memory import ThreeLayerMemory
from tools.handlers import build_default_registry


RESULT = ROOT / "tests" / "results" / "conversation-evaluation.json"


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


def context(messages: list[dict[str, Any]]) -> dict[str, Any]:
    message = next(item for item in messages if item.get("name") == "conversation_context")
    return json.loads(message["content"].split("：", 1)[1])


def runner(root: Path, model: ScriptedModel, *, memory: Any = None) -> ConversationRunner:
    return ConversationRunner(
        AgentLoop(model, build_default_registry(), memory=memory),
        dataset_registry=DatasetRegistry(root / f"derived-{id(model)}"),
    )


def trace_turn(question: str, state: Any, session: ConversationRunner) -> dict[str, Any]:
    return {
        "turn": session.state.turn_count,
        "question": question,
        "toolCalls": [
            {"name": entry["tool_name"], "arguments": entry["arguments"]}
            for entry in state.execution_trace
        ],
        "answer": state.final_answer,
        "stopReason": state.stop_reason,
        "conversationState": {
            "currentDatasetId": session.state.current_dataset_id,
            "lastDatasetIds": list(session.state.last_dataset_ids),
            "lastMetric": session.state.last_metric,
            "lastGroup": session.state.last_group,
            "lastTimeRange": session.state.last_time_range,
            "openTodos": list(session.state.open_todos),
        },
    }


def main() -> int:
    records: list[dict[str, Any]] = []
    continuous_trace: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="conversation-eval-") as directory:
        root = Path(directory)
        sales = root / "sales.csv"
        sales.write_text(
            "日期,地区,销售额,利润\n"
            "2026-01-01,华东,10,2\n"
            "2026-01-02,华东,20,3\n"
            "2026-01-01,华南,40,4\n",
            encoding="utf-8",
        )

        # One continuous four-turn conversation for inheritance and traceability.
        model = ScriptedModel(
            [
                lambda messages: {
                    "type": "tool_call",
                    "id": "regions-sales",
                    "name": "group_compare",
                    "arguments": {
                        "datasetId": context(messages)["currentDatasetId"],
                        "groupBy": "地区",
                        "metric": "销售额",
                        "operation": "sum",
                    },
                },
                {"type": "final_answer", "content": "华南销售额最高。"},
                lambda messages: {
                    "type": "tool_call",
                    "id": "regions-sales-again",
                    "name": "group_compare",
                    "arguments": {
                        "datasetId": context(messages)["currentDatasetId"],
                        "groupBy": context(messages)["lastGroup"],
                        "metric": context(messages)["lastMetric"],
                        "operation": "sum",
                    },
                },
                {"type": "final_answer", "content": "仍按地区查看销售额。"},
                lambda messages: {
                    "type": "tool_call",
                    "id": "east-trend",
                    "name": "trend_analysis",
                    "arguments": {
                        "datasetId": context(messages)["currentDatasetId"],
                        "dateField": "日期",
                        "metric": context(messages)["lastMetric"],
                        "operation": "sum",
                        "filters": {"地区": "华东"},
                    },
                },
                {"type": "final_answer", "content": "华东销售额从 10 上升到 20。"},
                {
                    "type": "tool_call",
                    "id": "east-chart",
                    "name": "generate_chart",
                    "arguments": {"sourceCallId": "east-trend", "chartType": "line"},
                },
                {"type": "final_answer", "content": "已生成华东销售额趋势图。"},
            ]
        )
        session = runner(root, model)
        turns = [
            ("按地区看销售额", {"dataset_paths": [sales]}),
            ("还是看销售额", {}),
            ("那华东呢", {}),
            ("把刚才结果画成图", {"artifact_dir": str(root / "charts")}),
        ]
        states = []
        for question, kwargs in turns:
            state = session.run(question, **kwargs)
            states.append(state)
            continuous_trace.append(trace_turn(question, state, session))

        east_args = states[2].execution_trace[0]["arguments"]
        record(
            records,
            "CONV-01",
            east_args.get("filters") == {"地区": "华东"}
            and east_args.get("datasetId") == session.state.current_dataset_id
            and east_args.get("metric") == "销售额",
            "那华东呢继承分析对象",
        )
        again_args = states[1].execution_trace[0]["arguments"]
        record(
            records,
            "CONV-02",
            again_args.get("metric") == "销售额" and again_args.get("groupBy") == "地区",
            "还是看销售额继承 metric/group",
        )

        # Two-file continuation reuses session datasets and prior ToolResults.
        first = root / "first.csv"
        second = root / "second.csv"
        first.write_text("产品,销售额\nA,10\nB,20\n", encoding="utf-8")
        second.write_text("产品,销售额\nA,40\nB,60\n", encoding="utf-8")
        two_model = ScriptedModel(
            [
                lambda messages: {
                    "tool_calls": [
                        {
                            "id": "file-1",
                            "name": "basic_stats",
                            "arguments": {
                                "datasetId": context(messages)["activeDatasetIds"][0],
                                "metric": "销售额",
                                "operation": "sum",
                            },
                        },
                        {
                            "id": "file-2",
                            "name": "basic_stats",
                            "arguments": {
                                "datasetId": context(messages)["activeDatasetIds"][1],
                                "metric": "销售额",
                                "operation": "sum",
                            },
                        },
                    ]
                },
                {"type": "final_answer", "content": "两个文件统计完成。"},
                {
                    "type": "tool_call",
                    "id": "two-compare",
                    "name": "compare_datasets",
                    "arguments": {"sourceCallIds": ["file-1", "file-2"]},
                },
                {"type": "final_answer", "content": "第二个文件销售额更高。"},
            ]
        )
        two_session = runner(root, two_model)
        two_session.run("分别统计两个文件", dataset_paths=[first, second])
        two_result = two_session.run("继续刚才两个文件")
        values = [
            item["value"] for item in two_result.execution_trace[0]["data"]["groups"]
        ]
        record(
            records,
            "CONV-03",
            values == [30, 100] and len(two_session.state.last_dataset_ids) == 2,
            "继续刚才两个文件恢复 dataset 与 ToolResult",
        )

        # Explicit new field overrides the previous metric.
        override_model = ScriptedModel(
            [
                lambda messages: stats_call(messages, "old-field", "销售额"),
                {"type": "final_answer", "content": "销售额总和完成。"},
                lambda messages: stats_call(messages, "new-field", "利润"),
                {"type": "final_answer", "content": "利润总和完成。"},
            ]
        )
        override_session = runner(root, override_model)
        override_session.run("计算销售额", dataset_paths=[sales])
        override_result = override_session.run("改为计算利润")
        record(
            records,
            "CONV-04",
            override_result.execution_trace[0]["arguments"]["metric"] == "利润"
            and override_session.state.last_metric == "利润",
            "显式新字段覆盖旧会话状态",
        )

        database = root / "memory.sqlite3"
        memory = ThreeLayerMemory.from_sqlite(database)
        try:
            # Runtime dataset/Todo state is not automatically persisted.
            todo_model = ScriptedModel(
                [
                    {
                        "type": "tool_call",
                        "id": "temp-todo",
                        "name": "todo_write",
                        "arguments": {
                            "updates": [
                                {
                                    "id": "temporary",
                                    "content": "临时任务",
                                    "status": "in_progress",
                                }
                            ]
                        },
                    },
                    {"type": "final_answer", "content": "临时任务已记录。"},
                ]
            )
            todo_session = runner(root, todo_model, memory=memory)
            todo_session.run("建立临时任务", dataset_paths=[sales], memory_scope="user-a")
            no_runtime_memory = (
                memory.kv.list("user-a") == [] and memory.semantic.list("user-a") == []
            )
            record(records, "CONV-05", no_runtime_memory, "临时 dataset/Todo 不进入长期 Memory")

            # Explicit long-term preference is recalled in a later conversation.
            memory.remember(
                scope_id="user-a",
                requests={"type": "kv", "key": "preferred_metric", "value": "销售额"},
            )

            def recalled(messages: list[dict[str, Any]]) -> dict[str, Any]:
                memory_text = next(
                    item["content"] for item in messages if item.get("name") == "memory_context"
                )
                return {
                    "type": "final_answer",
                    "content": "RECALLED" if "preferred_metric" in memory_text else "MISSING",
                }

            recall_session = runner(root, ScriptedModel([recalled]), memory=memory)
            recall_state = recall_session.run("按偏好指标分析", memory_scope="user-a")
            record(
                records,
                "CONV-06",
                recall_state.final_answer == "RECALLED" and bool(recall_state.recalled_memories),
                "长期偏好 recall",
            )

            memory.remember(
                scope_id="user-a",
                requests={
                    "type": "semantic",
                    "kind": "analysis_summary",
                    "content": "历史销售额总和是 999。",
                },
            )

            def current_answer(messages: list[dict[str, Any]]) -> dict[str, Any]:
                observation = json.loads(messages[-1]["content"])
                memory_text = next(
                    item["content"] for item in messages if item.get("name") == "memory_context"
                )
                passed = observation["data"]["value"] == 70 and "999" in memory_text
                return {
                    "type": "final_answer",
                    "content": "CURRENT" if passed else "CONFLICT_FAILED",
                }

            priority_model = ScriptedModel(
                [
                    lambda messages: stats_call(messages, "current-result", "销售额"),
                    current_answer,
                ]
            )
            priority_session = runner(root, priority_model, memory=memory)
            priority_state = priority_session.run(
                "计算当前销售额", dataset_paths=[sales], memory_scope="user-a"
            )
            record(
                records,
                "CONV-07",
                priority_state.final_answer == "CURRENT",
                "当前 ToolResult 覆盖冲突 Memory",
            )
        finally:
            memory.close()

        # A separate runner receives no temporary state from the previous session.
        def isolated(messages: list[dict[str, Any]]) -> dict[str, Any]:
            current = context(messages)
            clean = (
                current["currentDatasetId"] is None
                and current["lastDatasetIds"] == []
                and current["lastMetric"] is None
                and current["priorToolResults"] == []
            )
            return {
                "type": "needs_user_input",
                "content": "ISOLATED" if clean else "LEAKED",
            }

        isolated_session = runner(root, ScriptedModel([isolated]))
        isolated_state = isolated_session.run("那华东呢")
        record(
            records,
            "CONV-08",
            isolated_state.final_answer == "ISOLATED"
            and isolated_state.stop_reason == "needs_user_input",
            "新会话不继承旧临时状态",
        )

    report = {
        "passed": all(item["passed"] for item in records),
        "passedCases": sum(item["passed"] for item in records),
        "totalCases": len(records),
        "cases": records,
        "continuousTrace": continuous_trace,
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Conversation evaluation: {report['passedCases']}/{report['totalCases']}")
    print(f"Report: {RESULT}")
    return 0 if report["passed"] else 1


def stats_call(messages: list[dict[str, Any]], call_id: str, metric: str) -> dict[str, Any]:
    return {
        "type": "tool_call",
        "id": call_id,
        "name": "basic_stats",
        "arguments": {
            "datasetId": context(messages)["currentDatasetId"],
            "metric": metric,
            "operation": "sum",
        },
    }


def record(
    records: list[dict[str, Any]], case_id: str, passed: bool, description: str
) -> None:
    records.append({"caseId": case_id, "description": description, "passed": passed})
    print(f"{'PASS' if passed else 'FAIL'} {case_id}: {description}")


if __name__ == "__main__":
    raise SystemExit(main())
