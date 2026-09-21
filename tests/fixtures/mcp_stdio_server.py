"""Official MCP SDK stdio server used only by Day18.1 integration tests."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer


server = MCPServer("day18-stdio", version="1.0.0")


@server.tool(structured_output=True)
async def echo(text: str) -> dict[str, str]:
    """Return text through a real MCP stdio round trip."""
    return {"echo": text}


@server.tool()
async def slow_echo(text: str, delay_seconds: float = 5.0) -> str:
    """Wait before returning, and record cancellation for integration tests."""
    try:
        await asyncio.sleep(delay_seconds)
        return text
    except BaseException as error:
        marker = os.environ.get("MCP_CANCEL_MARKER")
        if marker:
            Path(marker).write_text(type(error).__name__, encoding="utf-8")
        raise


if __name__ == "__main__":
    server.run("stdio")
