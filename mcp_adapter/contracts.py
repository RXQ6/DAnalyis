"""Minimal synchronous contracts for MCP tool discovery and invocation."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class MCPToolSpec(TypedDict):
    name: str
    description: str
    inputSchema: dict[str, Any]


class MCPCallResult(TypedDict, total=False):
    content: list[dict[str, Any]]
    structuredContent: Any
    isError: bool


class MCPClient(Protocol):
    def list_tools(self, *, timeout_seconds: float) -> list[MCPToolSpec]: ...

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> MCPCallResult: ...


class MCPClientError(RuntimeError):
    """Base error raised by an MCP client before Registry normalization."""


class MCPProtocolError(MCPClientError):
    """The server response does not satisfy the minimal MCP contract."""


class MCPRemoteError(MCPClientError):
    """The remote server or transport failed."""


class MCPUnknownToolError(MCPClientError):
    """The remote server does not expose the requested tool."""

