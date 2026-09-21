from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent import AgentLoop, ConversationRunner
from datasets import DatasetRegistry
from subagents import data_check_delegate_definition
from tools import build_default_registry


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


class SubAgentIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.dataset = self.root / "sales.csv"
        self.dataset.write_text("地区,销售额\n华东,10\n华南,20\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_main_agent_receives_sanitized_result_and_keeps_final_control(self) -> None:
        datasets = DatasetRegistry(self.root / "derived")
        dataset_id = datasets.register(self.dataset)["datasetId"]
        sub_model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "sub-inspect",
                    "name": "inspect_data",
                    "arguments": {"datasetId": dataset_id},
                },
                {"type": "final_answer", "content": "数据结构检查完成。"},
            ]
        )
        registry = build_default_registry()
        registry.register(data_check_delegate_definition(sub_model, registry))

        def continue_after_delegation(messages: list[dict[str, Any]]) -> dict[str, Any]:
            observation = json.loads(messages[-1]["content"])
            self.assertEqual(observation["tool"], "delegate_data_check")
            delegated = observation["data"]
            self.assertEqual(delegated["status"], "completed")
            self.assertEqual(delegated["evidence"][0]["toolName"], "inspect_data")
            serialized = json.dumps(delegated, ensure_ascii=False)
            self.assertNotIn("messages", serialized)
            self.assertNotIn("execution_trace", serialized)
            return {
                "type": "tool_call",
                "id": "main-stats",
                "name": "basic_stats",
                "arguments": {
                    "datasetId": dataset_id,
                    "metric": "销售额",
                    "operation": "sum",
                },
            }

        def final_after_main_tool(messages: list[dict[str, Any]]) -> dict[str, Any]:
            observation = json.loads(messages[-1]["content"])
            self.assertEqual(observation["tool"], "basic_stats")
            self.assertEqual(observation["data"]["value"], 30)
            return {"type": "final_answer", "content": "主 Agent 已整合检查结果。"}

        main_model = ScriptedModel(
            [
                {"type": "final_answer", "content": "父历史已记录"},
                {
                    "type": "tool_call",
                    "id": "delegate-1",
                    "name": "delegate_data_check",
                    "arguments": {
                        "task": "检查字段和缺失值",
                        "datasetId": dataset_id,
                    },
                },
                continue_after_delegation,
                final_after_main_tool,
            ]
        )
        runner = ConversationRunner(
            AgentLoop(main_model, registry),
            dataset_registry=datasets,
            conversation_id="subagent-integration",
        )
        runner.set_active_datasets([dataset_id])
        runner.run("PARENT_HISTORY_SECRET_MARKER")
        state = runner.run("先委派检查数据，再给出结论")

        self.assertEqual(state.stop_reason, "final_answer")
        self.assertEqual(state.final_answer, "主 Agent 已整合检查结果。")
        self.assertEqual(
            [call["name"] for call in state.tool_calls],
            ["delegate_data_check", "basic_stats"],
        )
        self.assertEqual(len(sub_model.calls), 2)
        self.assertNotIn(
            "先委派检查数据，再给出结论",
            json.dumps(sub_model.calls, ensure_ascii=False),
        )
        self.assertNotIn(
            "PARENT_HISTORY_SECRET_MARKER",
            json.dumps(sub_model.calls, ensure_ascii=False),
        )

    def test_subagent_failure_is_structured_and_main_agent_can_finish(self) -> None:
        datasets = DatasetRegistry(self.root / "derived-failure")
        dataset_id = datasets.register(self.dataset)["datasetId"]
        sub_model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "unauthorized",
                    "name": "todo_write",
                    "arguments": {},
                },
                {"type": "final_answer", "content": "无法完成"},
            ]
        )
        registry = build_default_registry()
        registry.register(data_check_delegate_definition(sub_model, registry))

        def recover_from_subagent_failure(messages: list[dict[str, Any]]) -> dict[str, Any]:
            observation = json.loads(messages[-1]["content"])
            self.assertTrue(observation["ok"])
            self.assertEqual(observation["data"]["status"], "failed")
            self.assertEqual(
                observation["data"]["error"]["code"],
                "subagent_no_supported_evidence",
            )
            return {
                "type": "final_answer",
                "content": "子任务失败，主 Agent 已安全结束。",
            }

        main_model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "delegate-failure",
                    "name": "delegate_data_check",
                    "arguments": {
                        "task": "尝试受控检查",
                        "datasetId": dataset_id,
                    },
                },
                recover_from_subagent_failure,
            ]
        )
        state = AgentLoop(main_model, registry).run(
            "处理可能失败的子任务",
            dataset_registry=datasets,
            active_dataset_ids=[dataset_id],
        )
        self.assertEqual(state.stop_reason, "final_answer")
        self.assertEqual(state.final_answer, "子任务失败，主 Agent 已安全结束。")

    def test_delegation_rejects_inactive_dataset(self) -> None:
        datasets = DatasetRegistry(self.root / "derived-inactive")
        dataset_id = datasets.register(self.dataset)["datasetId"]
        registry = build_default_registry()
        registry.register(data_check_delegate_definition(ScriptedModel([]), registry))
        result = registry.execute(
            "delegate_data_check",
            {"task": "检查数据", "datasetId": dataset_id},
            context={
                "dataset_registry": datasets,
                "active_dataset_ids": [],
                "current_tool_calls": [],
            },
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "inactive_dataset")

    def test_second_delegation_in_one_main_run_is_rejected(self) -> None:
        datasets = DatasetRegistry(self.root / "derived-budget")
        dataset_id = datasets.register(self.dataset)["datasetId"]
        sub_model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "sub-inspect",
                    "name": "inspect_data",
                    "arguments": {"datasetId": dataset_id},
                },
                {"type": "final_answer", "content": "完成"},
            ]
        )
        registry = build_default_registry()
        registry.register(data_check_delegate_definition(sub_model, registry))
        main_model = ScriptedModel(
            [
                {
                    "tool_calls": [
                        {
                            "id": "delegate-a",
                            "name": "delegate_data_check",
                            "arguments": {"task": "第一次", "datasetId": dataset_id},
                        },
                        {
                            "id": "delegate-b",
                            "name": "delegate_data_check",
                            "arguments": {"task": "第二次", "datasetId": dataset_id},
                        },
                    ]
                }
            ]
        )
        state = AgentLoop(main_model, registry).run(
            "重复委派",
            dataset_registry=datasets,
            active_dataset_ids=[dataset_id],
        )
        self.assertEqual(state.stop_reason, "unrecoverable_tool_error")
        self.assertEqual(len(state.execution_trace), 2)
        self.assertTrue(state.execution_trace[0]["success"])
        self.assertEqual(
            state.execution_trace[1]["error"]["code"], "delegation_budget_exceeded"
        )


if __name__ == "__main__":
    unittest.main()
