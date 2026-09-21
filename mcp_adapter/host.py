"""Host-side lifecycle and policy boundary for optional MCP servers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.registry import ToolRegistry

from .adapter import MCPRegistrationReport, MCPToolAdapter
from .contracts import MCPClient


@dataclass(frozen=True)
class MCPServerBinding:
    """One Host-owned Client connection and its explicit tool permission set."""

    server_id: str
    client: MCPClient
    allowed_tools: frozenset[str]


class MCPHost:
    """Own MCP Clients while keeping protocol concerns outside AgentLoop."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._bindings: dict[str, MCPServerBinding] = {}

    @property
    def server_ids(self) -> tuple[str, ...]:
        return tuple(self._bindings)

    def attach_server(
        self,
        client: MCPClient,
        *,
        server_id: str,
        allowed_tools: set[str] | frozenset[str],
        **adapter_options: Any,
    ) -> MCPRegistrationReport:
        """Register one server with an explicit allowlist; fail without retaining it."""

        if server_id in self._bindings:
            raise ValueError(f"MCP server is already attached: {server_id}")
        if not isinstance(allowed_tools, (set, frozenset)):
            raise TypeError("MCP Host requires an explicit allowed_tools set")
        binding = MCPServerBinding(server_id, client, frozenset(allowed_tools))
        report = MCPToolAdapter(
            client,
            server_id=server_id,
            allowed_tools=binding.allowed_tools,
            **adapter_options,
        ).register_into(self.registry)
        if report.ok:
            self._bindings[server_id] = binding
        return report

    def close(self) -> None:
        """Best-effort close of SDK transports without affecting the Agent registry."""

        for binding in tuple(self._bindings.values()):
            close = getattr(binding.client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._bindings.clear()
