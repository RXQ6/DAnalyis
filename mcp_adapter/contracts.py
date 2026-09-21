"""Minimal synchronous contracts for MCP tool discovery and invocation."""

from __future__ import annotations

from typing import Any, NotRequired, Protocol, TypedDict


class MCPToolSpec(TypedDict):
    name: str
    inputSchema: dict[str, Any]
    description: NotRequired[str]
    title: NotRequired[str]
    outputSchema: NotRequired[dict[str, Any]]
    annotations: NotRequired[dict[str, Any]]


class MCPListToolsResult(TypedDict):
    tools: list[MCPToolSpec]
    nextCursor: NotRequired[str]


class MCPCallResult(TypedDict, total=False):
    resultType: str
    content: list[dict[str, Any]]
    structuredContent: Any
    isError: bool


class MCPClient(Protocol):
    """Transport-neutral Tools client implemented by mocks or a real SDK facade."""

    def list_tools(
        self,
        *,
        cursor: str | None = None,
        timeout_seconds: float,
    ) -> MCPListToolsResult: ...

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> MCPCallResult: ...


class MCPResourcesClient(Protocol):
    """Reserved extension point; Resources are not wired into the Harness yet."""

    def list_resources(self, *, cursor: str | None = None, timeout_seconds: float) -> Any: ...

    def read_resource(self, uri: str, *, timeout_seconds: float) -> Any: ...


class MCPPromptsClient(Protocol):
    """Reserved extension point; Prompts are not wired into the Harness yet."""

    def list_prompts(self, *, cursor: str | None = None, timeout_seconds: float) -> Any: ...

    def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> Any: ...


class MCPClientError(RuntimeError):
    """Base error raised by an MCP client before Registry normalization."""


class MCPProtocolError(MCPClientError):
    """The server response does not satisfy the minimal MCP contract."""


class MCPSchemaCompatibilityError(MCPClientError):
    """A valid MCP schema cannot be represented by the current ToolRegistry."""


class MCPRemoteError(MCPClientError):
    """The remote server or transport failed."""


class MCPUnknownToolError(MCPClientError):
    """The remote server does not expose the requested tool."""
