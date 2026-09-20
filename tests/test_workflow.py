from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent import AgentLoop, ConversationRunner
from datasets import DatasetRegistry
from tools import build_default_registry
from workflow import (
    AnalysisNode,
    CalcNode,
    ChatNode,
    MemoryRecallNode,
    RuleRouter,
    Workflow,
)


class ScriptedModel:
    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        return self.decisions[len(self.calls) - 1]


class RecordingNode:
    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self.states.append(copy.deepcopy(state))
        return {
            "status": "ok",
            "response": state["query"],
            "data": {"seenRoute": state["route"]},
            "error": None,
        }


def build_test_workflow(runner: ConversationRunner) -> Workflow:
    return Workflow(
        router=RuleRouter(),
        nodes={
            "chat": ChatNode(),
            "analysis": AnalysisNode(runner),
            "calc": CalcNode(),
            "memory_recall": MemoryRecallNode(None),
        },
    )


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def runner(self, model: ScriptedModel) -> ConversationRunner:
        return ConversationRunner(
            AgentLoop(model, build_default_registry()),
            dataset_registry=DatasetRegistry(self.root / "derived"),
            conversation_id="workflow-test",
        )

    def test_analysis_route_reuses_real_agent_loop(self) -> None:
        dataset = self.root / "sales.csv"
        dataset.write_text("地区,销售额\n华东,10\n华南,20\n", encoding="utf-8")
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "stats-1",
                    "name": "basic_stats",
                    "arguments": {"metric": "销售额", "operation": "sum"},
                },
                {"type": "final_answer", "content": "销售额总和为 30。"},
            ]
        )
        result = build_test_workflow(self.runner(model)).invoke(
            {"query": "计算销售额总和", "dataset_paths": [dataset]}
        )
        self.assertEqual(result["route"], "analysis")
        self.assertEqual(result["response"], "销售额总和为 30。")
        agent_state = result["data"]["agent_state"]
        self.assertEqual(agent_state["stop_reason"], "final_answer")
        self.assertEqual(agent_state["tool_calls"][0]["name"], "basic_stats")

    def test_active_dataset_context_routes_follow_up_back_to_analysis(self) -> None:
        dataset = self.root / "sales.csv"
        dataset.write_text("地区,销售额\n华东,10\n", encoding="utf-8")
        model = ScriptedModel(
            [
                {"type": "final_answer", "content": "第一轮完成"},
                {"type": "final_answer", "content": "追问完成"},
            ]
        )
        workflow = build_test_workflow(self.runner(model))
        workflow.invoke({"query": "分析销售额", "dataset_paths": [dataset]})
        follow_up = workflow.invoke({"query": "那华东呢"})
        self.assertEqual(follow_up["route"], "analysis")
        self.assertEqual(follow_up["response"], "追问完成")

    def test_invoke_does_not_mutate_input_and_executes_one_node(self) -> None:
        runner = self.runner(ScriptedModel([]))
        workflow = build_test_workflow(runner)
        state = {"query": "1 + 2"}
        original = copy.deepcopy(state)
        result = workflow.invoke(state)
        self.assertEqual(state, original)
        self.assertEqual(result["route"], "calc")
        self.assertEqual(result["data"]["value"], 3)
        self.assertEqual(runner.state.turn_count, 0)

    def test_workflow_rejects_missing_or_extra_routes_at_startup(self) -> None:
        with self.assertRaises(ValueError):
            Workflow(router=RuleRouter(), nodes={"chat": ChatNode()})

    def test_every_route_receives_shared_state_and_returns_one_contract(self) -> None:
        nodes = {route: RecordingNode() for route in (
            "chat", "analysis", "calc", "memory_recall"
        )}
        workflow = Workflow(router=RuleRouter(), nodes=nodes)
        cases = [
            ({"query": "你好"}, "chat"),
            ({"query": "分析销售额", "dataset_paths": ["sales.csv"]}, "analysis"),
            ({"query": "1 + 2"}, "calc"),
            ({"query": "你还记得我的偏好吗", "memory_scope": "user-a"}, "memory_recall"),
        ]
        expected_keys = {"status", "route", "response", "data", "error", "routing"}
        for state, expected_route in cases:
            with self.subTest(route=expected_route):
                result = workflow.invoke(state)
                self.assertEqual(set(result), expected_keys)
                self.assertEqual(result["route"], expected_route)
                seen = nodes[expected_route].states[-1]
                self.assertEqual(seen["query"], state["query"])
                self.assertEqual(seen["route"], expected_route)
                self.assertEqual(seen["routing"]["route"], expected_route)


if __name__ == "__main__":
    unittest.main()
