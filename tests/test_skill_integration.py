from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent import AgentLoop, ConversationRunner
from datasets import DatasetRegistry
from skill_runtime import SkillRegistry, SkillRuntime
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
    def __init__(self, decisions: list[Any]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        decision = self.decisions[len(self.calls) - 1]
        return decision(messages) if callable(decision) else decision


def contracted_output(call_id: str = "diag-inspect") -> str:
    return json.dumps(
        {
            "status": "completed",
            "summary": "数据结构已完成诊断。",
            "findings": [
                {
                    "title": "字段结构可用",
                    "severity": "low",
                    "detail": "数据检查工具成功返回字段与缺失情况。",
                    "evidenceCallIds": [call_id],
                }
            ],
            "recommendations": ["继续核对业务口径"],
            "limitations": [],
        },
        ensure_ascii=False,
    )


class SkillIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.dataset = self.root / "sales.csv"
        self.dataset.write_text("地区,销售额\n华东,10\n华南,20\n", encoding="utf-8")
        self.datasets = DatasetRegistry(self.root / "derived")
        self.dataset_id = self.datasets.register(self.dataset)["datasetId"]

    def tearDown(self) -> None:
        self.directory.cleanup()

    def build_node(self, model: ScriptedModel):
        runner = ConversationRunner(
            AgentLoop(model, build_default_registry()),
            dataset_registry=self.datasets,
            conversation_id="skill-test",
        )
        runner.set_active_datasets([self.dataset_id])
        registry = SkillRegistry()
        runtime = SkillRuntime(runner, registry)
        return AnalysisNode(runner, skill_runtime=runtime), runner, registry, runtime

    def test_matched_skill_reuses_agent_loop_and_records_invocation_trace(self) -> None:
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "diag-inspect",
                    "name": "inspect_data",
                    "arguments": {"datasetId": self.dataset_id},
                },
                {"type": "final_answer", "content": contracted_output()},
            ]
        )
        node, runner, registry, runtime = self.build_node(model)

        result = node.invoke(
            {
                "query": "请对这份数据做数据诊断，看看问题出在哪",
                "active_dataset_ids": [self.dataset_id],
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["response"], "数据结构已完成诊断。")
        self.assertEqual(registry.loaded_skill_names, ("data-diagnosis",))
        self.assertEqual(runner.state.turn_count, 1)
        self.assertEqual(len(runtime.invocations), 1)
        invocation = result["data"]["skill_invocation"]
        self.assertEqual(invocation["skill_name"], "data-diagnosis")
        self.assertTrue(invocation["contract_valid"])
        self.assertEqual(invocation["tools_used"], ("inspect_data",))
        self.assertNotIn("output_valid", invocation)
        self.assertEqual(invocation["trace"][0]["toolName"], "inspect_data")
        agent_state = result["data"]["agent_state"]
        self.assertEqual(agent_state["execution_trace"][-1]["trace_type"], "skill_invocation")
        self.assertEqual(agent_state["execution_trace"][-1]["tool_name"], "skill:data-diagnosis")
        first_call_tools = {
            item["function"]["name"] for item in model.calls[0]["tools"]
        }
        self.assertEqual(first_call_tools, set(invocation["allowed_tools"]))
        self.assertIn("# data-diagnosis", model.calls[0]["messages"][0]["content"])
        self.assertNotIn("# data-diagnosis", json.dumps(runner.state.history_messages()))

    def test_workflow_routes_to_analysis_then_discovers_skill(self) -> None:
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "diag-inspect",
                    "name": "inspect_data",
                    "arguments": {"datasetId": self.dataset_id},
                },
                {"type": "final_answer", "content": contracted_output()},
            ]
        )
        node, _, _, _ = self.build_node(model)
        workflow = Workflow(
            router=RuleRouter(),
            nodes={
                "chat": ChatNode(),
                "analysis": node,
                "calc": CalcNode(),
                "memory_recall": MemoryRecallNode(None),
            },
        )

        result = workflow.invoke({"query": "为什么最近销量下降"})

        self.assertEqual(result["route"], "analysis")
        self.assertEqual(result["routing"]["source"], "rule")
        self.assertEqual(
            result["data"]["skill_invocation"]["skill_name"], "data-diagnosis"
        )
        self.assertEqual(result["status"], "ok")

    def test_unmatched_analysis_does_not_load_or_inject_skill(self) -> None:
        model = ScriptedModel([{"type": "final_answer", "content": "普通分析完成"}])
        node, runner, registry, runtime = self.build_node(model)

        result = node.invoke(
            {
                "query": "统计销售额总和",
                "active_dataset_ids": [self.dataset_id],
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["response"], "普通分析完成")
        self.assertEqual(registry.loaded_skill_names, ())
        self.assertEqual(runtime.invocations, [])
        self.assertNotIn("# data-diagnosis", model.calls[0]["messages"][0]["content"])
        self.assertEqual(runner.state.turn_count, 1)

    def test_unauthorized_tool_is_rejected_without_crashing_skill(self) -> None:
        insufficient = json.dumps(
            {
                "status": "insufficient_evidence",
                "summary": "未获得足够证据。",
                "findings": [],
                "recommendations": ["使用允许的数据检查工具重试"],
                "limitations": ["尝试的工具不在 Skill 权限范围内"],
            },
            ensure_ascii=False,
        )
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "unauthorized",
                    "name": "generate_chart",
                    "arguments": {},
                },
                {"type": "final_answer", "content": insufficient},
            ]
        )
        node, _, _, _ = self.build_node(model)

        result = node.invoke(
            {
                "query": "做一次异常原因诊断",
                "active_dataset_ids": [self.dataset_id],
            }
        )

        self.assertEqual(result["status"], "ok")
        trace = result["data"]["agent_state"]["execution_trace"]
        self.assertFalse(trace[0]["success"])
        self.assertEqual(trace[0]["error"]["code"], "TOOL_NOT_FOUND")
        self.assertEqual(trace[-1]["trace_type"], "skill_invocation")

    def test_invalid_output_contract_is_structured_error(self) -> None:
        model = ScriptedModel(
            [{"type": "final_answer", "content": "这是不符合契约的自然语言"}]
        )
        node, _, _, _ = self.build_node(model)

        result = node.invoke(
            {
                "query": "请做根因分析",
                "active_dataset_ids": [self.dataset_id],
            }
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "skill_output_contract_violation")
        self.assertFalse(result["data"]["skill_invocation"]["contract_valid"])
        self.assertFalse(
            result["data"]["agent_state"]["execution_trace"][-1]["success"]
        )


if __name__ == "__main__":
    unittest.main()
