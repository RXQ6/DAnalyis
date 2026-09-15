from __future__ import annotations

import json
import unittest
from typing import Any

from agent.loop import AgentLoop
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


if __name__ == "__main__":
    unittest.main()
