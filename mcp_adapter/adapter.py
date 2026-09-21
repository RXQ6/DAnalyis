"""Map MCP tools into the existing ToolRegistry without changing AgentLoop."""

from __future__ import annotations

import copy
import json
import math
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from tools.registry import ToolDefinition, ToolExecutionError, ToolRegistry

from .contracts import (
    MCPCallResult,
    MCPClient,
    MCPProtocolError,
    MCPRemoteError,
    MCPToolSpec,
    MCPUnknownToolError,
)


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_T = TypeVar("_T")


@dataclass(frozen=True)
class MCPRegistrationReport:
    ok: bool
    server_id: str
    registered_tools: tuple[str, ...]
    error: dict[str, Any] | None = None


@dataclass
class _ThreadOutcome:
    value: Any = None
    error: BaseException | None = None


class MCPToolAdapter:
    """Discovers one configured MCP server and registers namespaced handlers."""

    def __init__(
        self,
        client: MCPClient,
        *,
        server_id: str,
        allowed_tools: set[str] | frozenset[str] | None = None,
        discovery_timeout_seconds: float = 5.0,
        call_timeout_seconds: float = 5.0,
        max_result_bytes: int = 64 * 1024,
        max_tools: int = 32,
        max_description_chars: int = 2_000,
        max_schema_bytes: int = 32 * 1024,
    ) -> None:
        if not isinstance(server_id, str) or not _NAME_PATTERN.fullmatch(server_id):
            raise ValueError("MCP server_id must contain only letters, numbers, '_' or '-'")
        if (
            isinstance(discovery_timeout_seconds, bool)
            or isinstance(call_timeout_seconds, bool)
            or not isinstance(discovery_timeout_seconds, (int, float))
            or not isinstance(call_timeout_seconds, (int, float))
            or not math.isfinite(discovery_timeout_seconds)
            or not math.isfinite(call_timeout_seconds)
            or discovery_timeout_seconds <= 0
            or call_timeout_seconds <= 0
        ):
            raise ValueError("MCP timeouts must be positive")
        if max_result_bytes < 256:
            raise ValueError("MCP max_result_bytes must be at least 256")
        if max_tools < 1:
            raise ValueError("MCP max_tools must be at least 1")
        self.client = client
        self.server_id = server_id.replace("-", "_")
        self.allowed_tools = None if allowed_tools is None else frozenset(allowed_tools)
        self.discovery_timeout_seconds = float(discovery_timeout_seconds)
        self.call_timeout_seconds = float(call_timeout_seconds)
        self.max_result_bytes = max_result_bytes
        self.max_tools = max_tools
        self.max_description_chars = max_description_chars
        self.max_schema_bytes = max_schema_bytes

    def register_into(self, registry: ToolRegistry) -> MCPRegistrationReport:
        """Fail open: a discovery failure leaves the existing registry untouched."""

        try:
            remote_tools = self._run_with_timeout(
                lambda: self.client.list_tools(
                    timeout_seconds=self.discovery_timeout_seconds
                ),
                self.discovery_timeout_seconds,
            )
            definitions = self._definitions(remote_tools)
            registry.register_many(definitions)
        except TimeoutError:
            return self._registration_error(
                "mcp_discovery_timeout", "MCP tool discovery timed out"
            )
        except MCPProtocolError:
            return self._registration_error(
                "mcp_protocol_error", "MCP tool discovery returned an invalid response"
            )
        except MCPRemoteError:
            return self._registration_error(
                "mcp_server_unavailable", "MCP server is unavailable"
            )
        except Exception as error:
            return self._registration_error(
                "mcp_registration_error",
                "MCP tools could not be registered",
                exception_type=type(error).__name__,
            )
        return MCPRegistrationReport(
            ok=True,
            server_id=self.server_id,
            registered_tools=tuple(definition.name for definition in definitions),
        )

    def _definitions(self, response: Any) -> list[ToolDefinition]:
        if not isinstance(response, list):
            raise MCPProtocolError("list_tools response must be a list")
        if len(response) > self.max_tools:
            raise MCPProtocolError("list_tools response exceeds the configured tool limit")

        definitions: list[ToolDefinition] = []
        local_names: set[str] = set()
        for raw in response:
            spec = self._validate_tool_spec(raw)
            if self.allowed_tools is not None and spec["name"] not in self.allowed_tools:
                continue
            local_name = self._local_name(spec["name"])
            if local_name in local_names:
                raise MCPProtocolError("MCP tool names collide after normalization")
            local_names.add(local_name)
            definitions.append(
                ToolDefinition(
                    name=local_name,
                    description=f"[MCP:{self.server_id}] {spec['description']}",
                    parameter_schema=copy.deepcopy(spec["inputSchema"]),
                    handler=self._handler(spec["name"]),
                    timeout_seconds=self.call_timeout_seconds,
                    max_result_bytes=self.max_result_bytes,
                )
            )
        try:
            ToolRegistry().register_many(definitions)
        except (TypeError, ValueError) as error:
            raise MCPProtocolError("MCP tool definition is incompatible") from error
        return definitions

    def _validate_tool_spec(self, raw: Any) -> MCPToolSpec:
        if not isinstance(raw, dict):
            raise MCPProtocolError("MCP tool definition must be an object")
        name = raw.get("name")
        description = raw.get("description")
        schema = raw.get("inputSchema")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 64
            or not _NAME_PATTERN.fullmatch(name)
        ):
            raise MCPProtocolError("MCP tool name is invalid")
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > self.max_description_chars
        ):
            raise MCPProtocolError("MCP tool description is invalid")
        if not isinstance(schema, dict):
            raise MCPProtocolError("MCP tool inputSchema must be an object")
        try:
            schema_size = len(
                json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        except (TypeError, ValueError) as error:
            raise MCPProtocolError("MCP tool inputSchema must be JSON serializable") from error
        if schema_size > self.max_schema_bytes:
            raise MCPProtocolError("MCP tool inputSchema is too large")
        return {
            "name": name,
            "description": description.strip(),
            "inputSchema": copy.deepcopy(schema),
        }

    def _handler(self, remote_name: str):
        def handler(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
            del context
            try:
                response = self._run_with_timeout(
                    lambda: self.client.call_tool(
                        remote_name,
                        copy.deepcopy(arguments),
                        timeout_seconds=self.call_timeout_seconds,
                    ),
                    self.call_timeout_seconds,
                )
                return self._normalize_call_result(remote_name, response)
            except ToolExecutionError:
                raise
            except TimeoutError as error:
                raise ToolExecutionError(
                    "mcp_timeout",
                    "MCP tool call timed out",
                    {"server": self.server_id, "tool": remote_name},
                ) from error
            except MCPUnknownToolError as error:
                raise ToolExecutionError(
                    "mcp_tool_not_found",
                    "MCP server does not expose the requested tool",
                    {"server": self.server_id, "tool": remote_name},
                ) from error
            except MCPProtocolError as error:
                raise ToolExecutionError(
                    "mcp_protocol_error",
                    "MCP tool returned an invalid response",
                    {"server": self.server_id, "tool": remote_name},
                ) from error
            except MCPRemoteError as error:
                raise ToolExecutionError(
                    "mcp_server_unavailable",
                    "MCP server call failed",
                    {"server": self.server_id, "tool": remote_name},
                ) from error
            except Exception as error:
                raise ToolExecutionError(
                    "mcp_server_unavailable",
                    "MCP server call failed unexpectedly",
                    {
                        "server": self.server_id,
                        "tool": remote_name,
                        "exceptionType": type(error).__name__,
                    },
                ) from error

        return handler

    def _normalize_call_result(self, remote_name: str, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise MCPProtocolError("call_tool response must be an object")
        content = raw.get("content", [])
        if not isinstance(content, list) or any(not isinstance(item, dict) for item in content):
            raise MCPProtocolError("call_tool content must be a list of objects")
        is_error = raw.get("isError", False)
        if not isinstance(is_error, bool):
            raise MCPProtocolError("call_tool isError must be a boolean")
        if is_error:
            raise ToolExecutionError(
                "mcp_tool_error",
                self._remote_error_message(content),
                {"server": self.server_id, "tool": remote_name},
            )
        result: dict[str, Any] = {
            "server": self.server_id,
            "tool": remote_name,
            "content": copy.deepcopy(content),
        }
        if "structuredContent" in raw:
            result["structuredContent"] = copy.deepcopy(raw["structuredContent"])
        return result

    def _local_name(self, remote_name: str) -> str:
        return f"mcp_{self.server_id}__{remote_name.replace('-', '_')}"

    def _registration_error(
        self, code: str, message: str, *, exception_type: str | None = None
    ) -> MCPRegistrationReport:
        details = {"server": self.server_id}
        if exception_type:
            details["exceptionType"] = exception_type
        return MCPRegistrationReport(
            ok=False,
            server_id=self.server_id,
            registered_tools=(),
            error={
                "code": code,
                "message": message,
                "details": details,
                "recoverable": True,
            },
        )

    @staticmethod
    def _remote_error_message(content: list[dict[str, Any]]) -> str:
        for item in content:
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()[:500]
        return "MCP tool reported an error"

    @staticmethod
    def _run_with_timeout(operation: Callable[[], _T], timeout_seconds: float) -> _T:
        outcome = _ThreadOutcome()

        def run() -> None:
            try:
                outcome.value = operation()
            except BaseException as error:  # transported back to the calling thread
                outcome.error = error

        worker = threading.Thread(target=run, daemon=True, name="mcp-adapter-call")
        worker.start()
        worker.join(timeout_seconds)
        if worker.is_alive():
            raise TimeoutError("MCP operation timed out")
        if outcome.error is not None:
            raise outcome.error
        return outcome.value
