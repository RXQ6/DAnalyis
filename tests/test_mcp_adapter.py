from __future__ import annotations

import time
import unittest
from typing import Any

from mcp_adapter import (
    MCPRemoteError,
    MCPToolAdapter,
    MCPUnknownToolError,
    MockMCPClient,
    MockMCPServer,
)
from tools.registry import ToolDefinition, ToolRegistry


def local_handler(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    return arguments


class StaticClient:
    def __init__(self, tools: Any, result: Any = None, error: Exception | None = None) -> None:
        self.tools = tools
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self, *, timeout_seconds: float) -> Any:
        del timeout_seconds
        return self.tools

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> Any:
        del timeout_seconds
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        return self.result


def echo_spec() -> dict[str, Any]:
    return {
        "name": "echo",
        "description": "echo text",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    }


class MCPAdapterTests(unittest.TestCase):
    def test_discovers_and_registers_namespaced_tool(self) -> None:
        registry = ToolRegistry()
        server = MockMCPServer()
        report = MCPToolAdapter(
            MockMCPClient(server), server_id="mock"
        ).register_into(registry)

        self.assertTrue(report.ok)
        self.assertEqual(report.registered_tools, ("mcp_mock__echo",))
        schema = registry.tool_schemas()[0]["function"]
        self.assertEqual(schema["name"], "mcp_mock__echo")
        self.assertEqual(schema["parameters"], server.list_tools()[0]["inputSchema"])
        self.assertIn("[MCP:mock]", schema["description"])

    def test_success_is_wrapped_by_existing_tool_result(self) -> None:
        server = MockMCPServer()
        registry = ToolRegistry()
        MCPToolAdapter(MockMCPClient(server), server_id="mock").register_into(registry)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["structuredContent"], {"echo": "hello"})
        self.assertEqual(result["data"]["server"], "mock")
        self.assertEqual(server.calls, [{"name": "echo", "arguments": {"text": "hello"}}])
        self.assertIsInstance(result["duration"], float)
        self.assertFalse(result["truncated"])

    def test_registry_validates_arguments_before_remote_call(self) -> None:
        server = MockMCPServer()
        registry = ToolRegistry()
        MCPToolAdapter(MockMCPClient(server), server_id="mock").register_into(registry)

        result = registry.execute("mcp_mock__echo", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_arguments")
        self.assertEqual(server.calls, [])

    def test_unknown_registry_tool_never_calls_mcp(self) -> None:
        client = StaticClient([echo_spec()], {"content": []})
        registry = ToolRegistry()
        MCPToolAdapter(client, server_id="mock").register_into(registry)

        result = registry.execute("mcp_mock__missing", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "TOOL_NOT_FOUND")
        self.assertEqual(client.calls, [])

    def test_remote_unknown_tool_is_normalized(self) -> None:
        client = StaticClient(
            [echo_spec()], error=MCPUnknownToolError("removed after discovery")
        )
        registry = ToolRegistry()
        MCPToolAdapter(client, server_id="mock").register_into(registry)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_tool_not_found")
        self.assertTrue(result["error"]["recoverable"])

    def test_remote_exception_is_normalized(self) -> None:
        client = StaticClient([echo_spec()], error=MCPRemoteError("offline"))
        registry = ToolRegistry()
        MCPToolAdapter(client, server_id="mock").register_into(registry)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_server_unavailable")

    def test_malformed_call_response_is_protocol_error(self) -> None:
        client = StaticClient([echo_spec()], {"content": "not-a-list"})
        registry = ToolRegistry()
        MCPToolAdapter(client, server_id="mock").register_into(registry)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_protocol_error")

    def test_remote_is_error_becomes_failed_tool_result(self) -> None:
        client = StaticClient(
            [echo_spec()],
            {
                "content": [{"type": "text", "text": "remote rejected request"}],
                "isError": True,
            },
        )
        registry = ToolRegistry()
        MCPToolAdapter(client, server_id="mock").register_into(registry)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_tool_error")
        self.assertEqual(result["error"]["message"], "remote rejected request")

    def test_call_timeout_is_bounded_and_recoverable(self) -> None:
        registry = ToolRegistry()
        adapter = MCPToolAdapter(
            MockMCPClient(MockMCPServer(delay_seconds=0.1)),
            server_id="mock",
            call_timeout_seconds=0.01,
        )
        adapter.register_into(registry)

        started = time.perf_counter()
        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertLess(time.perf_counter() - started, 0.08)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_timeout")
        self.assertTrue(result["error"]["recoverable"])

    def test_discovery_failure_keeps_existing_registry_unchanged(self) -> None:
        class SlowClient(StaticClient):
            def list_tools(self, *, timeout_seconds: float) -> Any:
                del timeout_seconds
                time.sleep(0.1)
                return [echo_spec()]

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "local_echo",
                "local echo",
                {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                local_handler,
            )
        )
        report = MCPToolAdapter(
            SlowClient([]), server_id="mock", discovery_timeout_seconds=0.01
        ).register_into(registry)

        self.assertFalse(report.ok)
        self.assertEqual(report.error["code"], "mcp_discovery_timeout")
        self.assertEqual(
            [item["function"]["name"] for item in registry.tool_schemas()],
            ["local_echo"],
        )
        self.assertTrue(registry.execute("local_echo", {})["ok"])

    def test_invalid_discovery_is_atomic(self) -> None:
        invalid = echo_spec()
        invalid["inputSchema"] = {"type": "object", "properties": {"x": {}}}
        registry = ToolRegistry()
        report = MCPToolAdapter(
            StaticClient([echo_spec(), invalid]), server_id="mock"
        ).register_into(registry)

        self.assertFalse(report.ok)
        self.assertEqual(report.error["code"], "mcp_protocol_error")
        self.assertEqual(report.registered_tools, ())
        self.assertEqual(registry.tool_schemas(), [])

    def test_allowlist_and_result_limit_are_enforced(self) -> None:
        large_client = StaticClient(
            [echo_spec()],
            {"content": [{"type": "text", "text": "x" * 2_000}]},
        )
        registry = ToolRegistry()
        report = MCPToolAdapter(
            large_client,
            server_id="mock",
            allowed_tools={"echo"},
            max_result_bytes=256,
        ).register_into(registry)
        self.assertTrue(report.ok)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
