"""Optional MCP tool source for the existing ToolRegistry."""

from .adapter import MCPRegistrationReport, MCPToolAdapter
from .contracts import (
    MCPCallResult,
    MCPClient,
    MCPClientError,
    MCPListToolsResult,
    MCPPromptsClient,
    MCPProtocolError,
    MCPRemoteError,
    MCPResourcesClient,
    MCPSchemaCompatibilityError,
    MCPToolSpec,
    MCPUnknownToolError,
)
from .host import MCPHost, MCPServerBinding
from .mock_server import MockMCPClient, MockMCPServer
from .sdk_stdio_client import MCPStdioClient

__all__ = [
    "MCPCallResult",
    "MCPClient",
    "MCPClientError",
    "MCPHost",
    "MCPListToolsResult",
    "MCPPromptsClient",
    "MCPProtocolError",
    "MCPRegistrationReport",
    "MCPRemoteError",
    "MCPResourcesClient",
    "MCPSchemaCompatibilityError",
    "MCPServerBinding",
    "MCPStdioClient",
    "MCPToolAdapter",
    "MCPToolSpec",
    "MCPUnknownToolError",
    "MockMCPClient",
    "MockMCPServer",
]
