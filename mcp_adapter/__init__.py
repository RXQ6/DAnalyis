"""Optional MCP tool source for the existing ToolRegistry."""

from .adapter import MCPRegistrationReport, MCPToolAdapter
from .contracts import (
    MCPCallResult,
    MCPClient,
    MCPClientError,
    MCPProtocolError,
    MCPRemoteError,
    MCPToolSpec,
    MCPUnknownToolError,
)
from .mock_server import MockMCPClient, MockMCPServer

__all__ = [
    "MCPCallResult",
    "MCPClient",
    "MCPClientError",
    "MCPProtocolError",
    "MCPRegistrationReport",
    "MCPRemoteError",
    "MCPToolAdapter",
    "MCPToolSpec",
    "MCPUnknownToolError",
    "MockMCPClient",
    "MockMCPServer",
]
