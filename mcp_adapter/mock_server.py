"""In-memory MCP server and client used by the first integration version."""

from __future__ import annotations

import copy
import time
from typing import Any

from .contracts import MCPCallResult, MCPRemoteError, MCPToolSpec, MCPUnknownToolError


class MockMCPServer:
    """A single deterministic echo tool; no network or external service."""

    def __init__(
        self,
        *,
        delay_seconds: float = 0.0,
        fail_calls: bool = False,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.fail_calls = fail_calls
        self.calls: list[dict[str, Any]] = []

    def list_tools(self) -> list[MCPToolSpec]:
        return [
            {
                "name": "echo",
                "description": "Return the supplied text from the simulated MCP server.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 2_000}
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            }
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.fail_calls:
            raise MCPRemoteError("simulated MCP server failure")
        if name != "echo":
            raise MCPUnknownToolError(f"unknown MCP tool: {name}")
        self.calls.append({"name": name, "arguments": copy.deepcopy(arguments)})
        text = arguments["text"]
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": {"echo": text},
            "isError": False,
        }


class MockMCPClient:
    """Minimal client facade that matches list_tools/call_tool."""

    def __init__(self, server: MockMCPServer) -> None:
        self.server = server

    def list_tools(self, *, timeout_seconds: float) -> list[MCPToolSpec]:
        del timeout_seconds
        return self.server.list_tools()

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> MCPCallResult:
        del timeout_seconds
        return self.server.call_tool(name, arguments)

