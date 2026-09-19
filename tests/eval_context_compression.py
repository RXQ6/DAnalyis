"""Deterministic evaluation for view-only context compression."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import AgentLoop
from context_compression import CompressionPolicy, ContextCompressor
from datasets import DatasetRegistry
from tools.handlers import build_default_registry


RESULT = ROOT / "tests" / "results" / "context-compression-evaluation.json"


class FinalModel:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del tools
        self.messages = messages
        return {"type": "final_answer", "content": "正常完成。"}


class FailingCompressor:
    def compress(self, **kwargs: Any) -> Any:
        del kwargs
        raise RuntimeError("expected failure")


class StatsAnswerModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del tools
        self.calls += 1
        if self.calls == 1:
            return {
                "type": "tool_call",
                "id": "answer-source",
                "name": "basic_stats",
                "arguments": {"metric": "销售额", "operation": "sum"},
            }
        observation = json.loads(messages[-1]["content"])
        return {
            "type": "final_answer",
            "content": f"销售额总和为 {observation['data']['value']}。",
        }


class MultiFileAnswerModel:
    def __init__(self, first_id: str, second_id: str) -> None:
        self.first_id = first_id
        self.second_id = second_id
        self.calls = 0

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del tools
        self.calls += 1
        if self.calls == 1:
            return {
                "type": "tool_call",
                "id": "stats-a",
                "name": "basic_stats",
                "arguments": {
                    "datasetId": self.first_id,
                    "metric": "销售额",
                    "operation": "sum",
                },
            }
        if self.calls == 2:
            return {
                "type": "tool_call",
                "id": "stats-b",
                "name": "basic_stats",
                "arguments": {
                    "datasetId": self.second_id,
                    "metric": "销售额",
                    "operation": "sum",
                },
            }
        if self.calls == 3:
            return {
                "type": "tool_call",
                "id": "compare-ab",
                "name": "compare_datasets",
                "arguments": {"sourceCallIds": ["stats-a", "stats-b"]},
            }
        observation = json.loads(messages[-1]["content"])
        values = [item["value"] for item in observation["data"]["groups"]]
        return {"type": "final_answer", "content": f"两个文件结果为 {values}。"}


def tool_pair(index: int, *, latest: bool = False) -> list[dict[str, Any]]:
    call_id = "latest-critical" if latest else f"history-{index}"
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "group_compare", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "name": "group_compare",
            "content": json.dumps(
                {
                    "tool": "group_compare",
                    "iteration": index + 1,
                    "ok": True,
                    "data": {
                        "metric": "销售额",
                        "groups": [
                            {"group": f"地区{item}", "value": item}
                            for item in range(180)
                        ],
                    },
                    "error": None,
                    "duration": 1.2,
                    "truncated": False,
                },
                ensure_ascii=False,
            ),
        },
    ]


def main() -> int:
    compressor = ContextCompressor()
    tools = build_default_registry().tool_schemas()
    records: list[dict[str, Any]] = []

    small = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "简单问题"},
    ]
    small_result = compressor.compress(messages=small, tools=tools)
    record(
        records,
        "CTX-01",
        not small_result.report["triggered"] and small_result.messages == small,
        small_result.report,
    )

    large: list[dict[str, Any]] = [{"role": "system", "content": "PROTECTED SYSTEM"}]
    for index in range(10):
        large.append({"role": "user", "content": f"历史问题 {index}"})
        large.extend(tool_pair(index))
        large.append({"role": "assistant", "content": f"历史回答 {index}"})
    large.append({"role": "user", "content": "CURRENT QUESTION"})
    large.extend(tool_pair(99, latest=True))
    original = copy.deepcopy(large)
    latest_content = large[-1]["content"]
    large_result = compressor.compress(messages=large, tools=tools)
    reduction = 1 - large_result.report["viewChars"] / large_result.report["originalChars"]
    preserved = (
        large_result.messages[0]["content"] == "PROTECTED SYSTEM"
        and any(item.get("content") == "CURRENT QUESTION" for item in large_result.messages)
        and large_result.messages[-1]["content"] == latest_content
    )
    record(
        records,
        "CTX-02",
        large_result.report["triggered"] and reduction >= 0.30 and preserved,
        {
            **large_result.report,
            "reductionRatio": round(reduction, 4),
            "systemPreserved": large_result.messages[0]["content"] == "PROTECTED SYSTEM",
            "currentUserPreserved": any(
                item.get("content") == "CURRENT QUESTION" for item in large_result.messages
            ),
            "latestToolResultPreserved": large_result.messages[-1]["content"] == latest_content,
            "oldMessagesReduced": large_result.report.get("removedHistoryTurns", 0) > 0,
        },
    )
    record(records, "CTX-03", large == original, {"stateUnchanged": large == original})

    model = FinalModel()
    state = AgentLoop(
        model,
        build_default_registry(),
        context_compressor=FailingCompressor(),
    ).run("fallback 测试")
    record(
        records,
        "CTX-04",
        state.final_answer == "正常完成。"
        and state.stop_reason == "final_answer"
        and state.context_errors[0]["error_type"] == "RuntimeError",
        {"stopReason": state.stop_reason, "contextErrors": state.context_errors},
    )

    todo_message = {
        "role": "system",
        "content": "当前 Todo 概览（计划状态，不代表工具已执行）："
        + json.dumps(
            {
                "completed": [
                    {"id": str(index), "content": "已完成", "status": "completed"}
                    for index in range(5)
                ],
                "in_progress": [
                    {"id": "goal", "content": "比较华东销售额", "status": "in_progress"}
                ],
                "pending": [
                    {"id": "chart", "content": "生成趋势图", "status": "pending"}
                ],
            },
            ensure_ascii=False,
        ),
    }
    todo_result = ContextCompressor(
        CompressionPolicy(trigger_total_chars=1, target_total_chars=20_000)
    ).compress(
        messages=[
            {"role": "system", "content": "system"},
            todo_message,
            {"role": "user", "content": "继续当前任务"},
        ],
        tools=tools,
    )
    compact_todo = next(
        item for item in todo_result.messages if str(item.get("content", "")).startswith("当前 Todo")
    )
    todo_data = json.loads(compact_todo["content"].split("：", 1)[1])
    record(
        records,
        "CTX-05",
        todo_data["in_progress"][0]["content"] == "比较华东销售额"
        and todo_data["pending"][0]["id"] == "chart"
        and todo_data["completedCount"] == 5
        and len(todo_data["completed"]) == 3,
        {
            "taskGoal": todo_data["in_progress"],
            "pending": todo_data["pending"],
            "completedCount": todo_data["completedCount"],
            "visibleCompleted": len(todo_data["completed"]),
        },
    )

    memory_result = ContextCompressor(
        CompressionPolicy(
            trigger_total_chars=1,
            target_total_chars=20_000,
            memory_view_chars=300,
        )
    ).compress(
        messages=[
            {"role": "system", "content": "system"},
            {
                "role": "system",
                "name": "memory_context",
                "content": "长期 Memory：\nKV preferred_metric=销售额\n" + "Semantic 经验信息\n" * 100,
            },
            {"role": "user", "content": "当前问题"},
        ],
        tools=tools,
    )
    memory_message = next(
        item for item in memory_result.messages if item.get("name") == "memory_context"
    )
    record(
        records,
        "CTX-06",
        len(memory_message["content"]) <= 330
        and "preferred_metric" in memory_message["content"],
        {
            "memoryViewChars": len(memory_message["content"]),
            "kvPreserved": "preferred_metric" in memory_message["content"],
        },
    )

    wide_column_count = 1_200
    columns = [
        {
            "name": "销售额" if index == 0 else f"字段{index}",
            "type": "number" if index < 10 else "text",
            "missing": index,
            "nonEmpty": 100 - min(index, 100),
            "distinct": 20,
        }
        for index in range(wide_column_count)
    ]
    dataset_messages = [
            {"role": "system", "content": "system"},
            {
                "role": "user",
                "content": "分析销售额",
                "dataset_context": {
                    "datasetCount": 1,
                    "datasets": [
                        {
                            "datasetId": "ds_wide",
                            "filename": "wide.csv",
                            "rowCount": 100,
                            "columnCount": wide_column_count,
                            "columns": columns,
                            "dateRanges": [],
                        }
                    ],
                },
            },
        ]
    original_dataset_messages = copy.deepcopy(dataset_messages)
    original_profile_chars = len(
        json.dumps(
            dataset_messages[-1]["dataset_context"]["datasets"][0],
            ensure_ascii=False,
        )
    )
    dataset_result = compressor.compress(
        messages=dataset_messages,
        tools=tools,
    )
    compact_dataset = dataset_result.messages[-1]["dataset_context"]["datasets"][0]
    visible_names = sum(len(items) for items in compact_dataset["columnsByType"].values())
    compact_profile_chars = len(json.dumps(compact_dataset, ensure_ascii=False))
    has_bounded_column_view = (
        visible_names < wide_column_count
        and compact_dataset.get("omittedColumnCount", 0) > 0
    )
    record(
        records,
        "CTX-07",
        dataset_result.report["triggered"]
        and has_bounded_column_view
        and compact_profile_chars < original_profile_chars * 0.25
        and dataset_messages == original_dataset_messages
        and "columns" not in compact_dataset
        and compact_dataset["relevantColumns"][0]["name"] == "销售额",
        {
            "originalColumns": wide_column_count,
            "visibleColumnNames": visible_names,
            "compactProfileChars": compact_profile_chars,
            "originalProfileChars": original_profile_chars,
            "profileReductionRatio": round(
                1 - compact_profile_chars / original_profile_chars, 4
            ),
            "hasBoundedColumnView": has_bounded_column_view,
            "sourceMetadataUnchanged": dataset_messages == original_dataset_messages,
            "omittedColumnCount": compact_dataset.get("omittedColumnCount", 0),
            "profileUsesTypeGroups": "columnsByType" in compact_dataset,
            "relevantColumn": compact_dataset.get("relevantColumns", []),
        },
    )

    sales = ROOT / "tests" / "fixtures" / "sales.csv"
    uncompressed = AgentLoop(
        StatsAnswerModel(),
        build_default_registry(),
        context_compressor=ContextCompressor(
            CompressionPolicy(
                trigger_total_chars=10**9,
                single_tool_result_chars=10**9,
                message_count_trigger=10**9,
                dataset_column_trigger=10**9,
            )
        ),
    ).run("计算销售额总和", dataset=str(sales))
    compressed = AgentLoop(
        StatsAnswerModel(),
        build_default_registry(),
        context_compressor=ContextCompressor(
            CompressionPolicy(
                trigger_total_chars=1,
                target_total_chars=20_000,
                single_tool_result_chars=1,
                message_count_trigger=1,
                dataset_column_trigger=1,
            )
        ),
    ).run("计算销售额总和", dataset=str(sales))
    record(
        records,
        "CTX-08",
        uncompressed.final_answer == compressed.final_answer == "销售额总和为 1580。"
        and uncompressed.execution_trace[0]["data"] == compressed.execution_trace[0]["data"],
        {
            "uncompressedAnswer": uncompressed.final_answer,
            "compressedAnswer": compressed.final_answer,
            "toolResultEqual": uncompressed.execution_trace[0]["data"]
            == compressed.execution_trace[0]["data"],
        },
    )

    with tempfile.TemporaryDirectory(prefix="compression-multifile-") as directory:
        temp_root = Path(directory)
        registry = DatasetRegistry(temp_root / "derived")
        first_file = temp_root / "first.csv"
        second_file = temp_root / "second.csv"
        first_file.write_text("订单,销售额\nA1,10\nA2,20\n", encoding="utf-8")
        second_file.write_text("订单,销售额\nB1,40\nB2,60\n", encoding="utf-8")
        first = registry.register(first_file)
        second = registry.register(second_file)
        active_ids = [first["datasetId"], second["datasetId"]]

        def run_multifile(policy: CompressionPolicy) -> Any:
            return AgentLoop(
                MultiFileAnswerModel(*active_ids),
                build_default_registry(),
                context_compressor=ContextCompressor(policy),
            ).run(
                "比较两个文件的销售额",
                dataset_registry=registry,
                active_dataset_ids=active_ids,
            )

        multifile_uncompressed = run_multifile(
            CompressionPolicy(
                trigger_total_chars=10**9,
                single_tool_result_chars=10**9,
                message_count_trigger=10**9,
                dataset_column_trigger=10**9,
            )
        )
        multifile_compressed = run_multifile(
            CompressionPolicy(
                trigger_total_chars=1,
                target_total_chars=20_000,
                single_tool_result_chars=1,
                message_count_trigger=1,
                dataset_column_trigger=1,
            )
        )
        uncompressed_values = multifile_uncompressed.execution_trace[-1]["data"]
        compressed_values = multifile_compressed.execution_trace[-1]["data"]
        record(
            records,
            "CTX-09",
            multifile_uncompressed.final_answer
            == multifile_compressed.final_answer
            == "两个文件结果为 [30, 100]。"
            and uncompressed_values == compressed_values,
            {
                "uncompressedAnswer": multifile_uncompressed.final_answer,
                "compressedAnswer": multifile_compressed.final_answer,
                "toolResultEqual": uncompressed_values == compressed_values,
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
    print(f"Context compression evaluation: {report['passedCases']}/{report['totalCases']}")
    print(f"Report: {RESULT}")
    return 0 if report["passed"] else 1


def record(
    records: list[dict[str, Any]], case_id: str, passed: bool, details: dict[str, Any]
) -> None:
    records.append({"caseId": case_id, "passed": passed, "details": details})
    print(f"{'PASS' if passed else 'FAIL'} {case_id}")


if __name__ == "__main__":
    raise SystemExit(main())
