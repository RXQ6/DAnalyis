from __future__ import annotations

import json
import time
import unittest
from typing import Any

from agent import AgentLoop
from mcp_adapter import MCPToolAdapter, MockMCPClient, MockMCPServer
from subagents.registry import DATA_CHECK_TOOLS, ToolBudget, build_restricted_registry
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


class MCPIntegrationTests(unittest.TestCase):
    def test_agent_loop_uses_mcp_through_existing_registry(self) -> None:
        server = MockMCPServer()
        registry = build_default_registry()
        report = MCPToolAdapter(
            MockMCPClient(server), server_id="mock", allowed_tools={"echo"}
        ).register_into(registry)
        self.assertTrue(report.ok)

        def finish(messages: list[dict[str, Any]]) -> dict[str, Any]:
            observation = json.loads(messages[-1]["content"])
            self.assertEqual(observation["tool"], "mcp_mock__echo")
            self.assertTrue(observation["ok"])
            self.assertEqual(
                observation["data"]["structuredContent"], {"echo": "from-agent"}
            )
            return {"type": "final_answer", "content": "MCP result integrated"}

        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "mcp-call-1",
                    "name": "mcp_mock__echo",
                    "arguments": {"text": "from-agent"},
                },
                finish,
            ]
        )

        state = AgentLoop(model, registry).run("use the mock MCP echo tool")

        self.assertEqual(state.stop_reason, "final_answer")
        self.assertEqual(state.final_answer, "MCP result integrated")
        self.assertEqual(state.execution_trace[0]["tool_name"], "mcp_mock__echo")
        self.assertTrue(state.execution_trace[0]["success"])

    def test_mcp_failure_does_not_stop_main_agent(self) -> None:
        registry = build_default_registry()
        MCPToolAdapter(
            MockMCPClient(MockMCPServer(fail_calls=True)), server_id="mock"
        ).register_into(registry)

        def recover(messages: list[dict[str, Any]]) -> dict[str, Any]:
            observation = json.loads(messages[-1]["content"])
            self.assertFalse(observation["ok"])
            self.assertEqual(
                observation["error"]["code"], "mcp_server_unavailable"
            )
            return {"type": "final_answer", "content": "Recovered safely"}

        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "mcp-failure",
                    "name": "mcp_mock__echo",
                    "arguments": {"text": "hello"},
                },
                recover,
            ]
        )

        state = AgentLoop(model, registry).run("handle an MCP failure")

        self.assertEqual(state.stop_reason, "final_answer")
        self.assertEqual(state.final_answer, "Recovered safely")
        self.assertFalse(state.execution_trace[0]["success"])

    def test_default_registry_and_subagent_allowlist_do_not_gain_mcp(self) -> None:
        source = build_default_registry()
        default_names = {
            item["function"]["name"] for item in source.tool_schemas()
        }
        self.assertFalse(any(name.startswith("mcp_") for name in default_names))

        MCPToolAdapter(
            MockMCPClient(MockMCPServer()), server_id="mock"
        ).register_into(source)
        restricted = build_restricted_registry(
            source,
            budget=ToolBudget(max_calls=4, deadline=time.monotonic() + 5),
        )
        restricted_names = tuple(
            item["function"]["name"] for item in restricted.tool_schemas()
        )

        self.assertEqual(restricted_names, DATA_CHECK_TOOLS)
        self.assertNotIn("mcp_mock__echo", restricted_names)


if __name__ == "__main__":
    unittest.main()
