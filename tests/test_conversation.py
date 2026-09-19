from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent import AgentLoop, ConversationRunner
from datasets import DatasetRegistry
from memory import ThreeLayerMemory
from tools.handlers import build_default_registry


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


def conversation_context(messages: list[dict[str, Any]]) -> dict[str, Any]:
    message = next(item for item in messages if item.get("name") == "conversation_context")
    return json.loads(message["content"].split("：", 1)[1])


class ConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def write(self, name: str, content: str) -> Path:
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def runner(self, model: ScriptedModel, *, memory: Any = None) -> ConversationRunner:
        registry = DatasetRegistry(self.root / "derived")
        loop = AgentLoop(model, build_default_registry(), memory=memory)
        return ConversationRunner(loop, dataset_registry=registry, conversation_id="conv-test")

    def test_follow_up_reuses_messages_dataset_metric_group_and_time_range(self) -> None:
        sales = self.write(
            "sales.csv",
            "日期,地区,销售额\n2026-01-01,华东,10\n2026-01-02,华东,20\n2026-01-01,华南,40\n",
        )

        def follow_up(messages: list[dict[str, Any]]) -> dict[str, Any]:
            context = conversation_context(messages)
            self.assertEqual(context["lastMetric"], "销售额")
            self.assertEqual(context["lastGroup"], "地区")
            self.assertEqual(context["activeDatasetIds"], context["lastDatasetIds"])
            self.assertTrue(any(item.get("role") == "tool" for item in messages))
            dataset_id = context["currentDatasetId"]
            return {
                "type": "tool_call",
                "id": "east-trend",
                "name": "trend_analysis",
                "arguments": {
                    "datasetId": dataset_id,
                    "dateField": "日期",
                    "metric": "销售额",
                    "operation": "sum",
                    "filters": {"地区": "华东"},
                },
            }

        model = ScriptedModel(
            [
                lambda messages: {
                    "type": "tool_call",
                    "id": "regions",
                    "name": "group_compare",
                    "arguments": {
                        "datasetId": conversation_context(messages)["currentDatasetId"],
                        "groupBy": "地区",
                        "metric": "销售额",
                        "operation": "sum",
                    },
                },
                {"type": "final_answer", "content": "华南最高。"},
                follow_up,
                {"type": "final_answer", "content": "华东销售额趋势已完成。"},
            ]
        )
        runner = self.runner(model)

        runner.run("比较各地区销售额", dataset_paths=[sales])
        second = runner.run("那华东呢")

        self.assertEqual(second.execution_trace[0]["tool_name"], "trend_analysis")
        self.assertEqual(second.execution_trace[0]["arguments"]["filters"], {"地区": "华东"})
        self.assertEqual(runner.state.last_metric, "销售额")
        self.assertEqual(runner.state.last_group, "地区")
        self.assertEqual(
            runner.state.last_time_range,
            {"start": "2026-01-01", "end": "2026-01-02", "dateField": "日期"},
        )

    def test_continue_two_files_can_compare_prior_turn_tool_results(self) -> None:
        first = self.write("first.csv", "产品,销售额\nA,10\nB,20\n")
        second = self.write("second.csv", "产品,销售额\nA,40\nB,60\n")

        def first_stats(messages: list[dict[str, Any]]) -> dict[str, Any]:
            ids = conversation_context(messages)["activeDatasetIds"]
            return {
                "tool_calls": [
                    {
                        "id": "stats-first",
                        "name": "basic_stats",
                        "arguments": {"datasetId": ids[0], "metric": "销售额", "operation": "sum"},
                    },
                    {
                        "id": "stats-second",
                        "name": "basic_stats",
                        "arguments": {"datasetId": ids[1], "metric": "销售额", "operation": "sum"},
                    },
                ]
            }

        model = ScriptedModel(
            [
                first_stats,
                {"type": "final_answer", "content": "两个文件已分别统计。"},
                {
                    "type": "tool_call",
                    "id": "compare-prior",
                    "name": "compare_datasets",
                    "arguments": {"sourceCallIds": ["stats-first", "stats-second"]},
                },
                {"type": "final_answer", "content": "第二个文件销售额更高。"},
            ]
        )
        runner = self.runner(model)

        runner.run("分别统计两个文件", dataset_paths=[first, second])
        compared = runner.run("继续刚才两个文件")

        self.assertTrue(compared.execution_trace[0]["success"])
        self.assertEqual(
            [item["value"] for item in compared.execution_trace[0]["data"]["groups"]],
            [30, 100],
        )
        self.assertEqual(len(runner.state.last_dataset_ids), 2)

    def test_metric_change_updates_conversation_focus(self) -> None:
        data = self.write(
            "metrics.csv", "地区,利润,销售额\n华东,3,10\n华南,4,20\n"
        )

        def switch_metric(messages: list[dict[str, Any]]) -> dict[str, Any]:
            context = conversation_context(messages)
            self.assertEqual(context["lastMetric"], "利润")
            return {
                "type": "tool_call",
                "id": "sales-by-region",
                "name": "group_compare",
                "arguments": {
                    "datasetId": context["currentDatasetId"],
                    "groupBy": context["lastGroup"],
                    "metric": "销售额",
                    "operation": "sum",
                },
            }

        model = ScriptedModel(
            [
                lambda messages: {
                    "type": "tool_call",
                    "id": "profit-by-region",
                    "name": "group_compare",
                    "arguments": {
                        "datasetId": conversation_context(messages)["currentDatasetId"],
                        "groupBy": "地区",
                        "metric": "利润",
                        "operation": "sum",
                    },
                },
                {"type": "final_answer", "content": "利润比较完成。"},
                switch_metric,
                {"type": "final_answer", "content": "销售额比较完成。"},
            ]
        )
        runner = self.runner(model)
        runner.run("按地区看利润", dataset_paths=[data])
        runner.run("还是看销售额")

        self.assertEqual(runner.state.last_metric, "销售额")
        self.assertEqual(runner.state.last_group, "地区")

    def test_new_upload_replaces_active_data_and_old_result_is_not_reused(self) -> None:
        old = self.write("old.csv", "销售额\n10\n20\n")
        new = self.write("new.csv", "销售额\n100\n")

        def stats(messages: list[dict[str, Any]], call_id: str) -> dict[str, Any]:
            return {
                "type": "tool_call",
                "id": call_id,
                "name": "basic_stats",
                "arguments": {
                    "datasetId": conversation_context(messages)["currentDatasetId"],
                    "metric": "销售额",
                    "operation": "sum",
                },
            }

        def new_stats(messages: list[dict[str, Any]]) -> dict[str, Any]:
            context = conversation_context(messages)
            self.assertEqual(context["priorToolResults"], [])
            return stats(messages, "new-stats")

        model = ScriptedModel(
            [
                lambda messages: stats(messages, "old-stats"),
                {"type": "final_answer", "content": "旧文件总和为 30。"},
                new_stats,
                {"type": "final_answer", "content": "新文件总和为 100。"},
            ]
        )
        runner = self.runner(model)
        runner.run("求和", dataset_paths=[old])
        old_id = runner.state.current_dataset_id
        current = runner.run("新文件也求和", dataset_paths=[new])

        self.assertNotEqual(old_id, runner.state.current_dataset_id)
        self.assertEqual(current.execution_trace[0]["data"]["value"], 100)
        blocked = runner.loop.registry.execute(
            "basic_stats",
            {"datasetId": old_id, "metric": "销售额", "operation": "sum"},
            context={
                "dataset_registry": runner.state.dataset_registry,
                "active_dataset_ids": runner.state.active_dataset_ids,
            },
        )
        self.assertEqual(blocked["error"]["code"], "inactive_dataset")

    def test_unfinished_todo_continues_but_never_enters_long_term_memory(self) -> None:
        database = self.root / "memory.sqlite3"
        memory = ThreeLayerMemory.from_sqlite(database)
        try:
            def finish_todo(messages: list[dict[str, Any]]) -> dict[str, Any]:
                todo_context = next(
                    item for item in messages if item.get("content", "").startswith("当前 Todo 概览")
                )
                self.assertIn('"id": "clarify"', todo_context["content"])
                return {
                    "type": "tool_call",
                    "id": "todo-done",
                    "name": "todo_write",
                    "arguments": {"updates": [{"id": "clarify", "status": "completed"}]},
                }

            model = ScriptedModel(
                [
                    {
                        "type": "tool_call",
                        "id": "todo-open",
                        "name": "todo_write",
                        "arguments": {
                            "updates": [
                                {
                                    "id": "clarify",
                                    "content": "确认分析字段",
                                    "status": "in_progress",
                                }
                            ]
                        },
                    },
                    {"type": "needs_user_input", "content": "请提供分析字段。"},
                    finish_todo,
                    {"type": "final_answer", "content": "已继续。"},
                ]
            )
            runner = self.runner(model, memory=memory)
            first = runner.run("继续分析", memory_scope="user-a")
            second = runner.run("使用销售额", memory_scope="user-a")

            self.assertEqual(first.stop_reason, "needs_user_input")
            self.assertEqual(second.stop_reason, "final_answer")
            self.assertEqual(runner.state.open_todos, [])
            self.assertEqual(memory.kv.list("user-a"), [])
            self.assertEqual(memory.semantic.list("user-a"), [])
        finally:
            memory.close()

    def test_current_tool_result_overrides_conflicting_long_term_memory(self) -> None:
        data = self.write("current.csv", "销售额\n10\n20\n")
        memory = ThreeLayerMemory.from_sqlite(self.root / "priority.sqlite3")
        memory.remember(
            scope_id="user-a",
            requests={
                "type": "semantic",
                "kind": "analysis_summary",
                "content": "历史销售额总和是 999。",
            },
        )
        try:
            def answer_current(messages: list[dict[str, Any]]) -> dict[str, Any]:
                memory_message = next(
                    item for item in messages if item.get("name") == "memory_context"
                )
                observation = json.loads(messages[-1]["content"])
                self.assertIn("999", memory_message["content"])
                self.assertEqual(observation["data"]["value"], 30)
                return {"type": "final_answer", "content": "当前文件销售额总和为 30。"}

            model = ScriptedModel(
                [
                    lambda messages: {
                        "type": "tool_call",
                        "id": "current-sum",
                        "name": "basic_stats",
                        "arguments": {
                            "datasetId": conversation_context(messages)["currentDatasetId"],
                            "metric": "销售额",
                            "operation": "sum",
                        },
                    },
                    answer_current,
                ]
            )
            runner = self.runner(model, memory=memory)
            result = runner.run(
                "计算当前销售额总和", dataset_paths=[data], memory_scope="user-a"
            )

            self.assertEqual(result.final_answer, "当前文件销售额总和为 30。")
        finally:
            memory.close()

    def test_chart_can_reference_previous_turn_result(self) -> None:
        data = self.write("chart.csv", "地区,销售额\n华东,10\n华南,20\n")
        artifacts = self.root / "charts"
        model = ScriptedModel(
            [
                lambda messages: {
                    "type": "tool_call",
                    "id": "group-source",
                    "name": "group_compare",
                    "arguments": {
                        "datasetId": conversation_context(messages)["currentDatasetId"],
                        "groupBy": "地区",
                        "metric": "销售额",
                        "operation": "sum",
                    },
                },
                {"type": "final_answer", "content": "地区比较完成。"},
                {
                    "type": "tool_call",
                    "id": "chart-follow-up",
                    "name": "generate_chart",
                    "arguments": {"sourceCallId": "group-source", "chartType": "bar"},
                },
                {"type": "final_answer", "content": "图表已生成。"},
            ]
        )
        runner = self.runner(model)
        runner.run("按地区比较", dataset_paths=[data])
        result = runner.run("把刚才结果画成图", artifact_dir=str(artifacts))

        self.assertTrue(result.execution_trace[0]["success"])
        self.assertTrue(Path(result.execution_trace[0]["data"]["artifact"]["path"]).is_file())

    def test_long_conversation_keeps_recent_analysis_evidence_without_summary(self) -> None:
        data = self.write("long.csv", "地区,销售额\n华东,10\n华南,20\n")

        def final_follow_up(messages: list[dict[str, Any]]) -> dict[str, Any]:
            context = conversation_context(messages)
            sources = context["priorToolResults"]
            source = next(item for item in sources if item["callId"] == "long-source")
            groups = source["toolResult"]["data"]["groups"]
            highest = max(groups, key=lambda item: item["value"])["group"]
            return {"type": "final_answer", "content": f"刚才最高的是{highest}。"}

        decisions: list[Any] = [
            lambda messages: {
                "type": "tool_call",
                "id": "long-source",
                "name": "group_compare",
                "arguments": {
                    "datasetId": conversation_context(messages)["currentDatasetId"],
                    "groupBy": "地区",
                    "metric": "销售额",
                    "operation": "sum",
                },
            },
            {"type": "final_answer", "content": "地区比较完成。"},
            *[
                {"type": "final_answer", "content": f"中间对话 {index}。"}
                for index in range(13)
            ],
            final_follow_up,
        ]
        runner = self.runner(ScriptedModel(decisions))
        runner.run("哪个地区最高", dataset_paths=[data])
        for index in range(13):
            runner.run(f"中间问题 {index}")
        result = runner.run("长对话前刚才哪个地区最高")

        self.assertEqual(result.final_answer, "刚才最高的是华南。")
        self.assertEqual(runner.state.turn_count, 15)

    def test_insufficient_history_returns_needs_user_input(self) -> None:
        model = ScriptedModel(
            [{"type": "needs_user_input", "content": "请先提供文件和指标。"}]
        )
        runner = self.runner(model)

        state = runner.run("那华东呢")

        self.assertEqual(state.stop_reason, "needs_user_input")
        self.assertEqual(state.final_answer, "请先提供文件和指标。")
        self.assertEqual(state.execution_trace, [])


if __name__ == "__main__":
    unittest.main()
