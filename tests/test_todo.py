from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from agent.loop import AgentLoop
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


class RecordingBridge:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        del arguments, context, timeout_seconds
        self.calls.append(name)
        return {"tool": name}


def run_todo_multistep_case() -> tuple[Any, ScriptedModel]:
    initial = [
        {"id": "compare", "content": "比较各地区销售额", "status": "in_progress"},
        {"id": "trend", "content": "分析华东销售趋势", "status": "pending"},
    ]
    second_step = [
        {"id": "compare", "content": "比较各地区销售额", "status": "completed"},
        {"id": "trend", "content": "分析华东销售趋势", "status": "in_progress"},
    ]
    completed = [
        {"id": "compare", "content": "比较各地区销售额", "status": "completed"},
        {"id": "trend", "content": "分析华东销售趋势", "status": "completed"},
    ]
    model = ScriptedModel(
        [
            {
                "type": "tool_call",
                "id": "todo-create",
                "name": "todo_write",
                "arguments": {"todos": initial},
            },
            {
                "type": "tool_call",
                "id": "compare-regions",
                "name": "group_compare",
                "arguments": {
                    "groupBy": "地区",
                    "metric": "销售额",
                    "operation": "sum",
                },
            },
            {
                "type": "tool_call",
                "id": "todo-progress",
                "name": "todo_write",
                "arguments": {"todos": second_step},
            },
            {
                "type": "tool_call",
                "id": "analyze-trend",
                "name": "trend_analysis",
                "arguments": {
                    "dateField": "日期",
                    "metric": "销售额",
                    "operation": "sum",
                    "filters": {"地区": "华东"},
                },
            },
            {
                "type": "tool_call",
                "id": "todo-complete",
                "name": "todo_write",
                "arguments": {"todos": completed},
            },
            {"type": "final_answer", "content": "地区比较与华东趋势分析均已完成。"},
        ]
    )
    state = AgentLoop(model, build_default_registry()).run(
        "比较各地区销售额，并分析华东销售趋势",
        dataset=str(SALES),
    )
    return state, model


class TodoTests(unittest.TestCase):
    def test_simple_task_does_not_require_todo(self) -> None:
        model = ScriptedModel([{"type": "final_answer", "content": "直接回答。"}])

        state = AgentLoop(model, build_default_registry()).run("一个简单问题")

        self.assertEqual(state.todos, [])
        self.assertEqual(len(model.calls[0]["messages"]), 2)

    def test_todo_write_creates_updates_and_exposes_summary_next_round(self) -> None:
        initial = [
            {"id": "compare", "content": "比较各地区", "status": "in_progress"},
            {"id": "trend", "content": "分析目标地区趋势", "status": "pending"},
        ]
        updated = [
            {"id": "compare", "content": "比较各地区", "status": "completed"},
            {"id": "trend", "content": "分析目标地区趋势", "status": "in_progress"},
        ]

        def update_after_create(messages: list[dict[str, Any]]) -> dict[str, Any]:
            context = messages[1]
            self.assertEqual(context["role"], "system")
            summary = json.loads(context["content"].split("：", 1)[1])
            self.assertEqual(summary["in_progress"][0]["id"], "compare")
            observation = json.loads(messages[-1]["content"])
            self.assertEqual(observation["tool"], "todo_write")
            self.assertEqual(observation["data"]["summary"]["pending"][0]["id"], "trend")
            return {
                "type": "tool_call",
                "id": "todo-2",
                "name": "todo_write",
                "arguments": {"todos": updated},
            }

        def finish(messages: list[dict[str, Any]]) -> dict[str, Any]:
            summary = json.loads(messages[1]["content"].split("：", 1)[1])
            self.assertEqual(summary["completed"][0]["id"], "compare")
            self.assertEqual(summary["in_progress"][0]["id"], "trend")
            return {"type": "final_answer", "content": "计划状态已更新。"}

        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "todo-1",
                    "name": "todo_write",
                    "arguments": {"todos": initial},
                },
                update_after_create,
                finish,
            ]
        )

        state = AgentLoop(model, build_default_registry()).run("完成一个复杂分析")

        self.assertEqual(state.todos, updated)
        self.assertEqual([item["tool_name"] for item in state.execution_trace], ["todo_write", "todo_write"])
        self.assertEqual(state.stop_reason, "final_answer")

    def test_todo_validation_rejects_invalid_status_and_duplicate_ids(self) -> None:
        registry = build_default_registry()
        context = {"todos": []}

        invalid_status = registry.execute(
            "todo_write",
            {"todos": [{"id": "1", "content": "任务", "status": "started"}]},
            context=context,
        )
        duplicate_ids = registry.execute(
            "todo_write",
            {
                "todos": [
                    {"id": "same", "content": "任务一", "status": "pending"},
                    {"id": "same", "content": "任务二", "status": "in_progress"},
                ]
            },
            context=context,
        )

        self.assertFalse(invalid_status["ok"])
        self.assertEqual(invalid_status["error"]["code"], "invalid_arguments")
        self.assertFalse(duplicate_ids["ok"])
        self.assertEqual(duplicate_ids["error"]["code"], "invalid_arguments")
        self.assertEqual(context["todos"], [])

    def test_multiple_in_progress_is_allowed_as_soft_constraint(self) -> None:
        registry = build_default_registry()
        todos: list[dict[str, str]] = []
        result = registry.execute(
            "todo_write",
            {
                "todos": [
                    {"id": "a", "content": "任务 A", "status": "in_progress"},
                    {"id": "b", "content": "任务 B", "status": "in_progress"},
                ]
            },
            context={"todos": todos},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["data"]["summary"]["in_progress"]), 2)

    def test_todo_can_be_reordered_and_removed(self) -> None:
        registry = build_default_registry()
        todos = [
            {"id": "a", "content": "任务 A", "status": "pending"},
            {"id": "b", "content": "任务 B", "status": "pending"},
        ]
        replacement = [{"id": "b", "content": "调整后的任务 B", "status": "completed"}]

        result = registry.execute(
            "todo_write", {"todos": replacement}, context={"todos": todos}
        )

        self.assertTrue(result["ok"])
        self.assertEqual(todos, replacement)

    def test_pending_in_progress_completed_lifecycle(self) -> None:
        registry = build_default_registry()
        todos: list[dict[str, str]] = []
        snapshots = [
            [{"id": "task", "content": "完成分析", "status": status}]
            for status in ("pending", "in_progress", "completed")
        ]

        for status, snapshot in zip(
            ("pending", "in_progress", "completed"), snapshots, strict=True
        ):
            result = registry.execute(
                "todo_write", {"todos": snapshot}, context={"todos": todos}
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["summary"][status][0]["id"], "task")

        self.assertEqual(todos, snapshots[-1])

    def test_todo_write_does_not_execute_analysis_bridge(self) -> None:
        bridge = RecordingBridge()
        registry = build_default_registry(bridge=bridge)
        todos: list[dict[str, str]] = []

        result = registry.execute(
            "todo_write",
            {
                "todos": [
                    {"id": "plan", "content": "规划分析", "status": "in_progress"}
                ]
            },
            context={"todos": todos},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(bridge.calls, [])

    def test_unfinished_todo_does_not_block_another_analysis_step(self) -> None:
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "todo-open",
                    "name": "todo_write",
                    "arguments": {
                        "todos": [
                            {
                                "id": "open",
                                "content": "仍在进行的检查",
                                "status": "in_progress",
                            },
                            {
                                "id": "sum",
                                "content": "计算销售额总和",
                                "status": "pending",
                            },
                        ]
                    },
                },
                {
                    "type": "tool_call",
                    "id": "sum-sales",
                    "name": "basic_stats",
                    "arguments": {"metric": "销售额", "operation": "sum"},
                },
                {"type": "final_answer", "content": "销售额总和为 1580。"},
            ]
        )

        state = AgentLoop(model, build_default_registry(), max_iter=3).run(
            "在检查继续进行时计算销售额总和", dataset=str(SALES)
        )

        self.assertEqual(
            [entry["tool_name"] for entry in state.execution_trace],
            ["todo_write", "basic_stats"],
        )
        self.assertTrue(state.execution_trace[1]["success"])
        self.assertEqual(state.execution_trace[1]["data"]["value"], 1580)
        self.assertEqual(state.todos[0]["status"], "in_progress")

    def test_todo_and_analysis_tools_form_a_complete_multistep_trace(self) -> None:
        state, model = run_todo_multistep_case()

        self.assertEqual(
            [entry["tool_name"] for entry in state.execution_trace],
            [
                "todo_write",
                "group_compare",
                "todo_write",
                "trend_analysis",
                "todo_write",
            ],
        )
        self.assertTrue(all(entry["success"] for entry in state.execution_trace))
        self.assertEqual(
            [todo["status"] for todo in state.todos], ["completed", "completed"]
        )
        self.assertEqual(state.stop_reason, "final_answer")

        visible_summaries = [
            json.loads(call["messages"][1]["content"].split("：", 1)[1])
            for call in model.calls[1:]
        ]
        self.assertEqual(visible_summaries[0]["in_progress"][0]["id"], "compare")
        self.assertEqual(visible_summaries[2]["in_progress"][0]["id"], "trend")
        self.assertEqual(len(visible_summaries[-1]["completed"]), 2)


if __name__ == "__main__":
    unittest.main()
