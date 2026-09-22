from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent import AgentLoop
from datasets import DatasetRegistry
from eval_harness import EvalCase, EvalRunner
from guardrails import DeterministicGuardrail, ToolGuardrailPolicy
from mcp_adapter import MCPToolAdapter, MockMCPClient, MockMCPServer
from observability import TraceCollector
from subagents import data_check_delegate_definition
from tools import ToolDefinition, ToolRegistry, build_default_registry


EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


class ScriptedModel:
    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = decisions
        self.calls = 0

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del messages, tools
        decision = self.decisions[self.calls]
        self.calls += 1
        return decision


class GuardrailDecisionTests(unittest.TestCase):
    def test_deterministic_rule_matrix(self) -> None:
        engine = DeterministicGuardrail()
        cases = [
            ("read_data", "allow"),
            ("analysis", "allow"),
            ("chart", "allow"),
            ("subagent_read", "allow"),
            ("mcp_read", "allow"),
            ("modify_original_data", "block"),
            ("python", "block"),
            ("shell", "block"),
            ("mcp_write", "needs_approval"),
            ("unknown_high_risk", "block"),
        ]
        for action_type, expected in cases:
            with self.subTest(action_type=action_type):
                decision = engine.evaluate(
                    tool_name="demo_tool",
                    arguments={},
                    policy=ToolGuardrailPolicy(
                        action_type=action_type,
                        risk_level="high" if expected != "allow" else "low",
                    ),
                )
                self.assertEqual(decision.decision, expected)

    def test_read_only_local_tool_is_allowed_and_executes(self) -> None:
        calls: list[str] = []

        def handler(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
            del arguments, context
            calls.append("called")
            return {"count": 1}

        collector = TraceCollector("trace_allow")
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "read_rows",
                "read rows",
                EMPTY_SCHEMA,
                handler,
                guardrail_policy=ToolGuardrailPolicy(action_type="read_data"),
            )
        )
        result = registry.execute(
            "read_rows", {}, context={"_trace_collector": collector}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["called"])
        decisions = [
            event
            for event in collector.snapshot()
            if event["event_type"] == "guardrail_decision"
        ]
        self.assertEqual(decisions[0]["status"], "allow")

    def test_original_data_mutation_is_blocked_before_handler(self) -> None:
        calls: list[str] = []

        def handler(arguments: dict[str, Any], context: dict[str, Any]) -> None:
            del arguments, context
            calls.append("called")

        collector = TraceCollector("trace_block")
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "overwrite_original_dataset",
                "unsafe mutation",
                EMPTY_SCHEMA,
                handler,
                guardrail_policy=ToolGuardrailPolicy(
                    action_type="modify_original_data", risk_level="high"
                ),
            )
        )
        result = registry.execute(
            "overwrite_original_dataset",
            {},
            context={"_trace_collector": collector},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "guardrail_blocked")
        self.assertEqual(calls, [])
        events = collector.snapshot()
        decision = next(
            event for event in events if event["event_type"] == "guardrail_decision"
        )
        self.assertEqual(decision["status"], "block")
        self.assertFalse(
            any(
                event["event_type"] == "tool_completed" and event["status"] == "ok"
                for event in events
            )
        )

    def test_python_or_shell_name_is_blocked_even_with_default_policy(self) -> None:
        calls: list[str] = []

        def handler(arguments: dict[str, Any], context: dict[str, Any]) -> None:
            del arguments, context
            calls.append("called")

        registry = ToolRegistry()
        registry.register(ToolDefinition("run_python", "unsafe", EMPTY_SCHEMA, handler))
        result = registry.execute("run_python", {})
        self.assertEqual(result["error"]["code"], "guardrail_blocked")
        self.assertEqual(calls, [])


class GuardrailIntegrationTests(unittest.TestCase):
    def test_mcp_write_returns_pending_without_remote_call(self) -> None:
        server = MockMCPServer()
        registry = build_default_registry()
        report = MCPToolAdapter(
            MockMCPClient(server),
            server_id="mock",
            allowed_tools={"echo"},
            tool_policies={"echo": "mcp_write"},
        ).register_into(registry)
        self.assertTrue(report.ok)
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "write-1",
                    "name": "mcp_mock__echo",
                    "arguments": {"text": "do-not-send"},
                }
            ]
        )

        state = AgentLoop(model, registry).run("执行外部写操作")

        self.assertEqual(state.stop_reason, "needs_approval")
        self.assertEqual(state.pending_approval["status"], "pending")
        self.assertEqual(state.pending_approval["tool_name"], "mcp_mock__echo")
        self.assertEqual(server.calls, [])
        self.assertNotIn("do-not-send", json.dumps(state.trace_events, ensure_ascii=False))
        decision = next(
            event
            for event in state.trace_events
            if event["event_type"] == "guardrail_decision"
        )
        self.assertEqual(decision["status"], "needs_approval")
        self.assertNotIn(
            "mcp_called", {event["event_type"] for event in state.trace_events}
        )

    def test_read_only_subagent_delegation_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "sales.csv"
            dataset.write_text("地区,销售额\n华东,10\n", encoding="utf-8")
            datasets = DatasetRegistry(root / "derived")
            dataset_id = datasets.register(dataset)["datasetId"]
            sub_model = ScriptedModel(
                [
                    {
                        "type": "tool_call",
                        "id": "inspect-1",
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
                "委派只读检查",
                dataset_registry=datasets,
                active_dataset_ids=[dataset_id],
            )
        delegate_decision = next(
            event
            for event in state.trace_events
            if event["event_type"] == "guardrail_decision"
            and event["name"] == "delegate_data_check"
        )
        self.assertEqual(delegate_decision["status"], "allow")
        self.assertIn(
            "subagent_completed", {event["event_type"] for event in state.trace_events}
        )

    def test_day19_guardrail_evaluator_accepts_blocked_trace(self) -> None:
        collector = TraceCollector("trace_eval_guardrail")
        collector.emit(
            "guardrail_decision",
            component="guardrail",
            name="unsafe_tool",
            status="block",
            error_code="guardrail_blocked",
            metadata={"rule_id": "deny_unknown_high_risk"},
        )
        collector.emit(
            "tool_completed",
            component="tool",
            name="unsafe_tool",
            status="blocked",
            error_code="guardrail_blocked",
        )
        case = EvalCase(
            "DAY20-GUARD-01",
            "security",
            "blocked action",
            lambda: {
                "passed": True,
                "trace_events": collector.snapshot(),
            },
            expectations={
                "guardrail": {"tool": "unsafe_tool", "decision": "block"}
            },
            evaluators=("guardrail",),
        )
        result = EvalRunner().run_case(case)
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
