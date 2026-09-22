"""Map MCP tools into the existing ToolRegistry without changing AgentLoop."""

from __future__ import annotations

import copy
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypeVar

from guardrails import ToolGuardrailPolicy
from tools.registry import ToolDefinition, ToolExecutionError, ToolRegistry

from .contracts import (
    MCPCallResult,
    MCPClient,
    MCPProtocolError,
    MCPRemoteError,
    MCPSchemaCompatibilityError,
    MCPToolSpec,
    MCPUnknownToolError,
)


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
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
        allowed_tools: set[str] | frozenset[str],
        discovery_timeout_seconds: float = 5.0,
        call_timeout_seconds: float = 5.0,
        max_result_bytes: int = 64 * 1024,
        max_tools: int = 32,
        max_description_chars: int = 2_000,
        max_schema_bytes: int = 32 * 1024,
        tool_policies: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(server_id, str) or not _NAME_PATTERN.fullmatch(server_id):
            raise ValueError("MCP server_id must contain only letters, numbers, '_' or '-'")
        if not isinstance(allowed_tools, (set, frozenset)):
            raise TypeError("MCP Adapter requires an explicit allowed_tools set")
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
        self.allowed_tools = frozenset(allowed_tools)
        self.discovery_timeout_seconds = float(discovery_timeout_seconds)
        self.call_timeout_seconds = float(call_timeout_seconds)
        self.max_result_bytes = max_result_bytes
        self.max_tools = max_tools
        self.max_description_chars = max_description_chars
        self.max_schema_bytes = max_schema_bytes
        self.tool_policies = dict(tool_policies or {})
        unknown_policy_tools = sorted(set(self.tool_policies) - set(self.allowed_tools))
        if unknown_policy_tools:
            raise ValueError(
                "MCP tool policies must reference allowed tools: "
                + ", ".join(unknown_policy_tools)
            )
        if any(not isinstance(value, str) or not value.strip() for value in self.tool_policies.values()):
            raise ValueError("MCP tool policy actions must be non-empty strings")

    def register_into(self, registry: ToolRegistry) -> MCPRegistrationReport:
        """Fail open: a discovery failure leaves the existing registry untouched."""

        try:
            remote_tools = self._discover_tools()
            definitions = self._definitions(remote_tools)
            registry.register_many(definitions)
        except TimeoutError:
            self._cancel_pending()
            return self._registration_error(
                "mcp_discovery_timeout", "MCP tool discovery timed out"
            )
        except MCPProtocolError:
            return self._registration_error(
                "mcp_protocol_error", "MCP tool discovery returned an invalid response"
            )
        except MCPSchemaCompatibilityError:
            return self._registration_error(
                "mcp_schema_incompatible",
                "MCP tool schema is not supported by the current ToolRegistry",
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

    def _discover_tools(self) -> list[MCPToolSpec]:
        tools: list[MCPToolSpec] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page = self._run_with_timeout(
                lambda current=cursor: self.client.list_tools(
                    cursor=current,
                    timeout_seconds=self.discovery_timeout_seconds,
                ),
                self.discovery_timeout_seconds,
            )
            if not isinstance(page, dict) or not isinstance(page.get("tools"), list):
                raise MCPProtocolError("list_tools response must contain a tools list")
            tools.extend(page["tools"])
            if len(tools) > self.max_tools:
                raise MCPProtocolError(
                    "list_tools response exceeds the configured tool limit"
                )
            next_cursor = page.get("nextCursor")
            if next_cursor is None:
                return tools
            if not isinstance(next_cursor, str) or not next_cursor:
                raise MCPProtocolError("list_tools nextCursor must be a non-empty string")
            if next_cursor in seen_cursors:
                raise MCPProtocolError("list_tools returned a repeated cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def _definitions(self, response: Any) -> list[ToolDefinition]:
        definitions: list[ToolDefinition] = []
        local_names: set[str] = set()
        for raw in response:
            spec = self._validate_tool_spec(raw)
            if spec["name"] not in self.allowed_tools:
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
                    handler=self._handler(spec["name"], spec.get("outputSchema")),
                    timeout_seconds=self.call_timeout_seconds,
                    max_result_bytes=self.max_result_bytes,
                    guardrail_policy=self._guardrail_policy(spec["name"]),
                )
            )
        try:
            ToolRegistry().register_many(definitions)
        except (TypeError, ValueError) as error:
            raise MCPSchemaCompatibilityError(
                "MCP tool definition is incompatible"
            ) from error
        return definitions

    def _guardrail_policy(self, remote_name: str) -> ToolGuardrailPolicy:
        action_type = self.tool_policies.get(remote_name, "mcp_read")
        return ToolGuardrailPolicy(
            action_type=action_type,
            risk_level="high" if action_type == "mcp_write" else "low",
            tool_kind="mcp",
        )

    def _validate_tool_spec(self, raw: Any) -> MCPToolSpec:
        if not isinstance(raw, dict):
            raise MCPProtocolError("MCP tool definition must be an object")
        name = raw.get("name")
        description = raw.get("description")
        schema = raw.get("inputSchema")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 128
            or not _TOOL_NAME_PATTERN.fullmatch(name)
        ):
            raise MCPProtocolError("MCP tool name is invalid")
        title = raw.get("title")
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise MCPProtocolError("MCP tool title is invalid")
        if description is not None and not isinstance(description, str):
            raise MCPProtocolError("MCP tool description is invalid")
        description = (description or title or f"MCP tool {name}").strip()
        if not description or len(description) > self.max_description_chars:
            raise MCPProtocolError("MCP tool description is invalid")
        if not isinstance(schema, dict):
            raise MCPProtocolError("MCP tool inputSchema must be an object")
        schema = self._normalize_input_schema(schema)
        output_schema = raw.get("outputSchema")
        if output_schema is not None and not isinstance(output_schema, dict):
            raise MCPProtocolError("MCP tool outputSchema must be an object")
        try:
            schemas = [schema] + ([output_schema] if output_schema is not None else [])
            schema_size = sum(
                len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                for item in schemas
            )
        except (TypeError, ValueError) as error:
            raise MCPProtocolError("MCP tool schemas must be JSON serializable") from error
        if schema_size > self.max_schema_bytes:
            raise MCPProtocolError("MCP tool schemas are too large")
        spec: MCPToolSpec = {
            "name": name,
            "description": description,
            "inputSchema": copy.deepcopy(schema),
        }
        if isinstance(title, str):
            spec["title"] = title.strip()
        if output_schema is not None:
            spec["outputSchema"] = copy.deepcopy(output_schema)
        annotations = raw.get("annotations")
        if annotations is not None:
            if not isinstance(annotations, dict):
                raise MCPProtocolError("MCP tool annotations must be an object")
            spec["annotations"] = copy.deepcopy(annotations)
        return spec

    def _handler(self, remote_name: str, output_schema: dict[str, Any] | None):
        expected_output = copy.deepcopy(output_schema)

        def handler(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
            collector = context.get("_trace_collector")
            started = time.perf_counter()
            try:
                response = self._run_with_timeout(
                    lambda: self.client.call_tool(
                        remote_name,
                        copy.deepcopy(arguments),
                        timeout_seconds=self.call_timeout_seconds,
                    ),
                    self.call_timeout_seconds,
                )
                result = self._normalize_call_result(
                    remote_name, response, output_schema=expected_output
                )
                self._emit_call(
                    collector,
                    remote_name,
                    status="ok",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
                return result
            except ToolExecutionError as error:
                self._emit_call(
                    collector,
                    remote_name,
                    status="error",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error_code=error.code,
                )
                raise
            except TimeoutError as error:
                self._cancel_pending()
                self._emit_call(
                    collector,
                    remote_name,
                    status="error",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error_code="mcp_timeout",
                )
                raise ToolExecutionError(
                    "mcp_timeout",
                    "MCP tool call timed out",
                    {"server": self.server_id, "tool": remote_name},
                ) from error
            except MCPUnknownToolError as error:
                self._emit_call(
                    collector,
                    remote_name,
                    status="error",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error_code="mcp_tool_not_found",
                )
                raise ToolExecutionError(
                    "mcp_tool_not_found",
                    "MCP server does not expose the requested tool",
                    {"server": self.server_id, "tool": remote_name},
                ) from error
            except MCPProtocolError as error:
                self._emit_call(
                    collector,
                    remote_name,
                    status="error",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error_code="mcp_protocol_error",
                )
                raise ToolExecutionError(
                    "mcp_protocol_error",
                    "MCP tool returned an invalid response",
                    {"server": self.server_id, "tool": remote_name},
                ) from error
            except MCPRemoteError as error:
                self._emit_call(
                    collector,
                    remote_name,
                    status="error",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error_code="mcp_server_unavailable",
                )
                raise ToolExecutionError(
                    "mcp_server_unavailable",
                    "MCP server call failed",
                    {"server": self.server_id, "tool": remote_name},
                ) from error
            except Exception as error:
                self._emit_call(
                    collector,
                    remote_name,
                    status="error",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error_code="mcp_server_unavailable",
                )
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

    def _emit_call(
        self,
        collector: Any,
        remote_name: str,
        *,
        status: str,
        latency_ms: float,
        error_code: str | None = None,
    ) -> None:
        emit = getattr(collector, "emit", None)
        if callable(emit):
            emit(
                "mcp_called",
                component="mcp",
                name=remote_name,
                status=status,
                latency_ms=latency_ms,
                error_code=error_code,
                metadata={"server_id": self.server_id},
            )

    def _normalize_call_result(
        self,
        remote_name: str,
        raw: Any,
        *,
        output_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise MCPProtocolError("call_tool response must be an object")
        result_type = raw.get("resultType", "complete")
        if result_type == "input_required":
            raise ToolExecutionError(
                "mcp_input_required_unsupported",
                "MCP tool requires additional input that this Host does not support",
                {"server": self.server_id, "tool": remote_name},
            )
        if result_type != "complete":
            raise MCPProtocolError("call_tool resultType is invalid")
        content = raw.get("content", [])
        if not isinstance(content, list) or any(not isinstance(item, dict) for item in content):
            raise MCPProtocolError("call_tool content must be a list of objects")
        for item in content:
            self._validate_content_block(item)
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
            if output_schema is not None:
                self._validate_output(raw["structuredContent"], output_schema, "structuredContent")
            result["structuredContent"] = copy.deepcopy(raw["structuredContent"])
        elif output_schema is not None:
            raise MCPProtocolError(
                "call_tool omitted structuredContent required by outputSchema"
            )
        return result

    def _local_name(self, remote_name: str) -> str:
        normalized = remote_name.replace("-", "_").replace(".", "_")
        return f"mcp_{self.server_id}__{normalized}"

    @staticmethod
    def _normalize_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(schema)
        if normalized.get("type") != "object":
            raise MCPProtocolError("MCP tool inputSchema must describe an object")
        normalized.setdefault("properties", {})
        normalized.setdefault("required", [])
        return normalized

    @staticmethod
    def _validate_content_block(item: dict[str, Any]) -> None:
        block_type = item.get("type")
        if block_type == "text":
            valid = isinstance(item.get("text"), str)
        elif block_type in {"image", "audio"}:
            valid = isinstance(item.get("data"), str) and isinstance(
                item.get("mimeType"), str
            )
        elif block_type == "resource_link":
            valid = isinstance(item.get("uri"), str) and isinstance(
                item.get("name"), str
            )
        elif block_type == "resource":
            resource = item.get("resource")
            valid = isinstance(resource, dict) and isinstance(resource.get("uri"), str)
        else:
            valid = False
        if not valid:
            raise MCPProtocolError("call_tool contains an invalid content block")

    @classmethod
    def _validate_output(cls, value: Any, schema: dict[str, Any], path: str) -> None:
        if "enum" in schema and value not in schema["enum"]:
            raise MCPProtocolError(f"{path} does not satisfy outputSchema")
        schema_type = schema.get("type")
        expected = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "null": type(None),
        }.get(schema_type)
        if expected is None:
            raise MCPProtocolError("MCP outputSchema uses an unsupported shape")
        if not isinstance(value, expected) or (
            schema_type in {"integer", "number"} and isinstance(value, bool)
        ):
            raise MCPProtocolError(f"{path} does not satisfy outputSchema")
        if schema_type == "object":
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            if not isinstance(properties, dict) or not isinstance(required, list):
                raise MCPProtocolError("MCP outputSchema is invalid")
            if any(name not in value for name in required):
                raise MCPProtocolError(f"{path} does not satisfy outputSchema")
            if schema.get("additionalProperties") is False and any(
                name not in properties for name in value
            ):
                raise MCPProtocolError(f"{path} does not satisfy outputSchema")
            for name, item in value.items():
                if isinstance(properties.get(name), dict):
                    cls._validate_output(item, properties[name], f"{path}.{name}")
        elif schema_type == "array" and isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                cls._validate_output(item, schema["items"], f"{path}[{index}]")

    def _cancel_pending(self) -> None:
        cancel = getattr(self.client, "cancel_pending", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass

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
