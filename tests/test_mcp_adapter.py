from __future__ import annotations

import time
import unittest
from typing import Any

from mcp_adapter import (
    MCPHost,
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

    def list_tools(
        self, *, cursor: str | None = None, timeout_seconds: float
    ) -> Any:
        del timeout_seconds
        if cursor is not None:
            raise AssertionError(f"unexpected cursor: {cursor}")
        return self.tools if isinstance(self.tools, dict) else {"tools": self.tools}

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
            MockMCPClient(server), server_id="mock", allowed_tools={"echo"}
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
        MCPToolAdapter(
            MockMCPClient(server), server_id="mock", allowed_tools={"echo"}
        ).register_into(registry)

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
        MCPToolAdapter(
            MockMCPClient(server), server_id="mock", allowed_tools={"echo"}
        ).register_into(registry)

        result = registry.execute("mcp_mock__echo", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_arguments")
        self.assertEqual(server.calls, [])

    def test_unknown_registry_tool_never_calls_mcp(self) -> None:
        client = StaticClient([echo_spec()], {"content": []})
        registry = ToolRegistry()
        MCPToolAdapter(client, server_id="mock", allowed_tools={"echo"}).register_into(registry)

        result = registry.execute("mcp_mock__missing", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "TOOL_NOT_FOUND")
        self.assertEqual(client.calls, [])

    def test_remote_unknown_tool_is_normalized(self) -> None:
        client = StaticClient(
            [echo_spec()], error=MCPUnknownToolError("removed after discovery")
        )
        registry = ToolRegistry()
        MCPToolAdapter(client, server_id="mock", allowed_tools={"echo"}).register_into(registry)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_tool_not_found")
        self.assertTrue(result["error"]["recoverable"])

    def test_remote_exception_is_normalized(self) -> None:
        client = StaticClient([echo_spec()], error=MCPRemoteError("offline"))
        registry = ToolRegistry()
        MCPToolAdapter(client, server_id="mock", allowed_tools={"echo"}).register_into(registry)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_server_unavailable")

    def test_malformed_call_response_is_protocol_error(self) -> None:
        client = StaticClient([echo_spec()], {"content": "not-a-list"})
        registry = ToolRegistry()
        MCPToolAdapter(client, server_id="mock", allowed_tools={"echo"}).register_into(registry)

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
        MCPToolAdapter(client, server_id="mock", allowed_tools={"echo"}).register_into(registry)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_tool_error")
        self.assertEqual(result["error"]["message"], "remote rejected request")

    def test_call_timeout_is_bounded_and_recoverable(self) -> None:
        registry = ToolRegistry()
        client = MockMCPClient(MockMCPServer(delay_seconds=0.1))
        adapter = MCPToolAdapter(
            client,
            server_id="mock",
            allowed_tools={"echo"},
            call_timeout_seconds=0.01,
        )
        adapter.register_into(registry)

        started = time.perf_counter()
        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertLess(time.perf_counter() - started, 0.08)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_timeout")
        self.assertTrue(result["error"]["recoverable"])
        self.assertEqual(client.cancel_count, 1)

    def test_discovery_failure_keeps_existing_registry_unchanged(self) -> None:
        class SlowClient(StaticClient):
            def list_tools(
                self, *, cursor: str | None = None, timeout_seconds: float
            ) -> Any:
                del cursor, timeout_seconds
                time.sleep(0.1)
                return {"tools": [echo_spec()]}

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
            SlowClient([]), server_id="mock", allowed_tools={"echo"}, discovery_timeout_seconds=0.01
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
        invalid["name"] = "incompatible"
        invalid["inputSchema"] = {"type": "object", "properties": {"x": {}}}
        registry = ToolRegistry()
        report = MCPToolAdapter(
            StaticClient([echo_spec(), invalid]),
            server_id="mock",
            allowed_tools={"echo", "incompatible"},
        ).register_into(registry)

        self.assertFalse(report.ok)
        self.assertEqual(report.error["code"], "mcp_schema_incompatible")
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

    def test_paginated_discovery_and_bound_handlers_do_not_cross(self) -> None:
        first = echo_spec()
        first["name"] = "alpha.echo"
        second = echo_spec()
        second["name"] = "beta-echo"

        class PagedClient(StaticClient):
            def list_tools(
                self, *, cursor: str | None = None, timeout_seconds: float
            ) -> Any:
                del timeout_seconds
                if cursor is None:
                    return {"tools": [first], "nextCursor": "page-2"}
                if cursor == "page-2":
                    return {"tools": [second]}
                raise AssertionError(cursor)

        client = PagedClient([], {"content": []})
        registry = ToolRegistry()
        report = MCPToolAdapter(
            client,
            server_id="paged",
            allowed_tools={"alpha.echo", "beta-echo"},
        ).register_into(registry)

        self.assertTrue(report.ok)
        self.assertEqual(
            report.registered_tools,
            ("mcp_paged__alpha_echo", "mcp_paged__beta_echo"),
        )
        self.assertTrue(registry.execute("mcp_paged__alpha_echo", {"text": "a"})["ok"])
        self.assertTrue(registry.execute("mcp_paged__beta_echo", {"text": "b"})["ok"])
        self.assertEqual([name for name, _ in client.calls], ["alpha.echo", "beta-echo"])

    def test_standard_no_argument_schema_is_normalized(self) -> None:
        spec = {
            "name": "ping",
            "title": "Ping",
            "inputSchema": {"type": "object", "additionalProperties": False},
        }
        registry = ToolRegistry()

        report = MCPToolAdapter(
            StaticClient([spec], {"content": []}),
            server_id="mock",
            allowed_tools={"ping"},
        ).register_into(registry)

        self.assertTrue(report.ok)
        parameters = registry.tool_schemas()[0]["function"]["parameters"]
        self.assertEqual(parameters["properties"], {})
        self.assertEqual(parameters["required"], [])

    def test_output_schema_mismatch_is_protocol_error(self) -> None:
        spec = echo_spec()
        spec["outputSchema"] = {
            "type": "object",
            "properties": {"echo": {"type": "string"}},
            "required": ["echo"],
            "additionalProperties": False,
        }
        registry = ToolRegistry()
        MCPToolAdapter(
            StaticClient(
                [spec],
                {"content": [], "structuredContent": {"echo": 123}},
            ),
            server_id="mock",
            allowed_tools={"echo"},
        ).register_into(registry)

        result = registry.execute("mcp_mock__echo", {"text": "hello"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "mcp_protocol_error")

    def test_input_required_and_invalid_content_are_safe_errors(self) -> None:
        input_registry = ToolRegistry()
        MCPToolAdapter(
            StaticClient(
                [echo_spec()],
                {"resultType": "input_required", "content": []},
            ),
            server_id="input",
            allowed_tools={"echo"},
        ).register_into(input_registry)
        input_result = input_registry.execute(
            "mcp_input__echo", {"text": "hello"}
        )

        content_registry = ToolRegistry()
        MCPToolAdapter(
            StaticClient(
                [echo_spec()],
                {"content": [{"type": "image", "data": "missing-mime"}]},
            ),
            server_id="content",
            allowed_tools={"echo"},
        ).register_into(content_registry)
        content_result = content_registry.execute(
            "mcp_content__echo", {"text": "hello"}
        )

        self.assertFalse(input_result["ok"])
        self.assertEqual(
            input_result["error"]["code"], "mcp_input_required_unsupported"
        )
        self.assertFalse(content_result["ok"])
        self.assertEqual(content_result["error"]["code"], "mcp_protocol_error")

    def test_host_requires_allowlist_and_closes_client(self) -> None:
        client = MockMCPClient(MockMCPServer())
        host = MCPHost(ToolRegistry())

        with self.assertRaises(TypeError):
            host.attach_server(client, server_id="mock", allowed_tools=None)  # type: ignore[arg-type]
        report = host.attach_server(
            client, server_id="mock", allowed_tools={"echo"}
        )

        self.assertTrue(report.ok)
        self.assertEqual(host.server_ids, ("mock",))
        host.close()
        self.assertTrue(client.closed)
        self.assertEqual(host.server_ids, ())

    def test_host_allowlist_does_not_expose_other_remote_tools(self) -> None:
        allowed = echo_spec()
        allowed["name"] = "allowed"
        blocked = echo_spec()
        blocked["name"] = "blocked"
        registry = ToolRegistry()
        host = MCPHost(registry)

        report = host.attach_server(
            StaticClient([allowed, blocked], {"content": []}),
            server_id="secure",
            allowed_tools={"allowed"},
        )

        self.assertTrue(report.ok)
        self.assertEqual(report.registered_tools, ("mcp_secure__allowed",))
        names = [item["function"]["name"] for item in registry.tool_schemas()]
        self.assertEqual(names, ["mcp_secure__allowed"])

    def test_malformed_list_page_and_unavailable_server_are_structured(self) -> None:
        malformed = MCPToolAdapter(
            StaticClient({"tools": "not-a-list"}),
            server_id="bad",
            allowed_tools=set(),
        ).register_into(ToolRegistry())

        class OfflineClient(StaticClient):
            def list_tools(
                self, *, cursor: str | None = None, timeout_seconds: float
            ) -> Any:
                del cursor, timeout_seconds
                raise MCPRemoteError("offline")

        unavailable = MCPToolAdapter(
            OfflineClient([]), server_id="offline", allowed_tools=set()
        ).register_into(ToolRegistry())

        self.assertFalse(malformed.ok)
        self.assertEqual(malformed.error["code"], "mcp_protocol_error")
        self.assertFalse(unavailable.ok)
        self.assertEqual(unavailable.error["code"], "mcp_server_unavailable")


if __name__ == "__main__":
    unittest.main()
