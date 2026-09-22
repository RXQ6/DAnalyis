from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent import AgentLoop, ConversationRunner
from datasets import DatasetRegistry
from eval_harness import EvalCase
from eval_harness.evaluators import ObservabilityEvaluator
from mcp_adapter import MCPToolAdapter, MockMCPClient, MockMCPServer
from observability import TraceCollector, TraceEvent
from skill_runtime import SkillRegistry, SkillRuntime
from subagents import data_check_delegate_definition
from tools import build_default_registry
from workflow import AnalysisNode, CalcNode, ChatNode, MemoryRecallNode, RuleRouter, Workflow


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


def workflow_for(runner: ConversationRunner, *, skill_runtime: Any = None) -> Workflow:
    return Workflow(
        router=RuleRouter(),
        nodes={
            "chat": ChatNode(),
            "analysis": AnalysisNode(runner, skill_runtime=skill_runtime),
            "calc": CalcNode(),
            "memory_recall": MemoryRecallNode(None),
        },
    )


class TraceContractTests(unittest.TestCase):
    def test_trace_event_contract_and_sanitized_bounded_metadata(self) -> None:
        collector = TraceCollector("trace_test", max_events=2)
        collector.emit(
            "request_started",
            component="agent",
            name="agent_loop",
            status="started",
            metadata={
                "prompt": "PRIVATE QUESTION",
                "data": [{"secret": "ROW"}],
                "api_token": "TOKEN-VALUE",
                "safe": "x" * 500,
            },
        )
        collector.emit(
            "request_completed",
            component="agent",
            name="agent_loop",
            status="ok",
            latency_ms=1.25,
        )
        collector.emit("error", component="test", name="overflow", status="error")

        events = collector.snapshot()
        self.assertEqual(events[0]["metadata"]["prompt"], "<redacted>")
        self.assertEqual(events[0]["metadata"]["data"], "<redacted>")
        self.assertEqual(events[0]["metadata"]["api_token"], "<redacted>")
        self.assertNotIn("PRIVATE QUESTION", json.dumps(events, ensure_ascii=False))
        self.assertNotIn("ROW", json.dumps(events, ensure_ascii=False))
        self.assertEqual(events[-1]["error_code"], "trace_event_limit_reached")
        self.assertEqual(TraceEvent(**{key: events[0][key] for key in TraceEvent.__dataclass_fields__}).trace_id, "trace_test")


class RuntimeTraceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_full_workflow_request_emits_route_tool_and_mcp_events(self) -> None:
        registry = build_default_registry()
        MCPToolAdapter(
            MockMCPClient(MockMCPServer()),
            server_id="mock",
            allowed_tools={"echo"},
        ).register_into(registry)
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "mcp-1",
                    "name": "mcp_mock__echo",
                    "arguments": {"text": "sensitive payload"},
                },
                {"type": "final_answer", "content": "完成"},
            ]
        )
        runner = ConversationRunner(
            AgentLoop(model, registry),
            dataset_registry=DatasetRegistry(self.root / "derived"),
        )

        result = workflow_for(runner).invoke({"query": "分析数据并调用已配置工具"})
        observability = result["data"]["observability"]
        events = observability["events"]
        event_types = [event["event_type"] for event in events]

        self.assertEqual(event_types[0], "request_started")
        self.assertIn("route_selected", event_types)
        self.assertIn("tool_called", event_types)
        self.assertIn("mcp_called", event_types)
        self.assertIn("tool_completed", event_types)
        self.assertEqual(event_types[-1], "request_completed")
        self.assertEqual({event["trace_id"] for event in events}, {observability["trace_id"]})
        self.assertNotIn("sensitive payload", json.dumps(events, ensure_ascii=False))
        self.assertEqual(
            result["data"]["agent_state"]["execution_trace"][0]["data"]
            ["structuredContent"]["echo"],
            "sensitive payload",
        )

    def test_failed_mcp_emits_structured_error_without_raw_payload(self) -> None:
        registry = build_default_registry()
        MCPToolAdapter(
            MockMCPClient(MockMCPServer(fail_calls=True)),
            server_id="mock",
            allowed_tools={"echo"},
        ).register_into(registry)
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "mcp-error",
                    "name": "mcp_mock__echo",
                    "arguments": {"text": "must-not-enter-trace"},
                },
                {"type": "final_answer", "content": "已安全恢复"},
            ]
        )
        state = AgentLoop(model, registry).run("触发受控 MCP 错误")
        error_events = [
            event for event in state.trace_events if event["event_type"] == "error"
        ]
        self.assertTrue(error_events)
        self.assertIn(
            "mcp_server_unavailable",
            {event["error_code"] for event in error_events},
        )
        self.assertNotIn(
            "must-not-enter-trace", json.dumps(state.trace_events, ensure_ascii=False)
        )

    def test_skill_emits_trigger_and_contract_events(self) -> None:
        dataset = self.root / "sales.csv"
        dataset.write_text("地区,销售额\n华东,10\n", encoding="utf-8")
        datasets = DatasetRegistry(self.root / "skill-derived")
        dataset_id = datasets.register(dataset)["datasetId"]
        contracted = json.dumps(
            {
                "status": "completed",
                "summary": "诊断完成",
                "findings": [
                    {
                        "title": "结构正常",
                        "severity": "low",
                        "detail": "字段可用",
                        "evidenceCallIds": ["inspect-1"],
                    }
                ],
                "recommendations": [],
                "limitations": [],
            },
            ensure_ascii=False,
        )
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "inspect-1",
                    "name": "inspect_data",
                    "arguments": {"datasetId": dataset_id},
                },
                {"type": "final_answer", "content": contracted},
            ]
        )
        runner = ConversationRunner(
            AgentLoop(model, build_default_registry()), dataset_registry=datasets
        )
        runner.set_active_datasets([dataset_id])
        runtime = SkillRuntime(runner, SkillRegistry())

        result = workflow_for(runner, skill_runtime=runtime).invoke(
            {"query": "为什么最近销量下降"}
        )
        events = result["data"]["observability"]["events"]
        self.assertIn("skill_triggered", [event["event_type"] for event in events])
        contracts = [event for event in events if event["event_type"] == "contract_checked"]
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0]["status"], "ok")

    def test_subagent_emits_start_and_completion_without_raw_evidence(self) -> None:
        dataset = self.root / "sub.csv"
        dataset.write_text("地区,销售额\n华东,10\n", encoding="utf-8")
        datasets = DatasetRegistry(self.root / "sub-derived")
        dataset_id = datasets.register(dataset)["datasetId"]
        sub_model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "sub-inspect",
                    "name": "inspect_data",
                    "arguments": {"datasetId": dataset_id},
                },
                {"type": "final_answer", "content": "检查完成"},
            ]
        )
        registry = build_default_registry()
        registry.register(data_check_delegate_definition(sub_model, registry))
        main_model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "delegate-1",
                    "name": "delegate_data_check",
                    "arguments": {"task": "检查字段", "datasetId": dataset_id},
                },
                {"type": "final_answer", "content": "完成"},
            ]
        )
        state = AgentLoop(main_model, registry).run(
            "委派检查",
            dataset_registry=datasets,
            active_dataset_ids=[dataset_id],
        )
        event_types = [event["event_type"] for event in state.trace_events]
        self.assertIn("subagent_started", event_types)
        self.assertIn("subagent_completed", event_types)
        encoded = json.dumps(state.trace_events, ensure_ascii=False)
        self.assertNotIn("columns", encoded)
        self.assertNotIn("检查完成", encoded)


class EvalHarnessCompatibilityTests(unittest.TestCase):
    def test_day19_runner_can_select_observability_evaluator(self) -> None:
        collector = TraceCollector("trace_eval")
        collector.emit("request_started", component="agent", name="agent_loop", status="started")
        collector.emit(
            "request_completed",
            component="agent",
            name="agent_loop",
            status="ok",
            latency_ms=1,
        )
        case = EvalCase(
            "DAY20-TRACE-01",
            "observability",
            "trace contract",
            lambda: {},
            expectations={
                "observability": {
                    "required_events": ["request_started", "request_completed"]
                }
            },
        )
        result = ObservabilityEvaluator().evaluate(
            case, {"trace_events": collector.snapshot()}
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.values["trace_event_count"], 2)


if __name__ == "__main__":
    unittest.main()
