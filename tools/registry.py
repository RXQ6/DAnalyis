"""Tool metadata, validation, and dispatch for the Day8 Agent Loop."""

from __future__ import annotations

import inspect
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, TypedDict

from guardrails import DeterministicGuardrail, GuardrailDecision, ToolGuardrailPolicy
from hitl import ApprovalManager, ApprovalResolution


ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Any]


class ToolResult(TypedDict):
    """Normalized result returned by every registry execution; duration is milliseconds."""

    ok: bool
    data: Any
    error: dict[str, Any] | None
    duration: float
    truncated: bool


class ToolExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}
        self.recoverable = recoverable


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameter_schema: dict[str, Any]
    handler: ToolHandler
    timeout_seconds: float = 30.0
    max_result_bytes: int = 64 * 1024
    guardrail_policy: ToolGuardrailPolicy = ToolGuardrailPolicy()


class ToolRegistry:
    def __init__(
        self,
        *,
        guardrail: DeterministicGuardrail | None = None,
        approval_manager: ApprovalManager | None = None,
    ) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self.guardrail = guardrail or DeterministicGuardrail()
        self.approval_manager = approval_manager or ApprovalManager()

    def register(self, definition: ToolDefinition) -> None:
        self.register_many([definition])

    def register_many(self, definitions: list[ToolDefinition]) -> None:
        """Validate a batch before mutating the registry."""
        pending = list(definitions)
        for definition in pending:
            self._validate_definition(definition)
        names = [definition.name for definition in pending]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        conflicts = sorted(name for name in names if name in self._tools)
        if duplicates or conflicts:
            names_text = ", ".join(sorted(set(duplicates + conflicts)))
            raise ValueError(f"tool already registered: {names_text}")
        self._tools.update({definition.name: definition for definition in pending})

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolExecutionError("TOOL_NOT_FOUND", f"tool is not registered: {name}") from error

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        started = time.perf_counter()
        runtime_context = context or {}
        collector = runtime_context.get("_trace_collector")
        self._emit_trace(
            collector,
            "tool_called",
            name=name,
            status="started",
            metadata={
                "argument_names": sorted(arguments) if isinstance(arguments, dict) else [],
                "iteration": runtime_context.get("iteration"),
                "call_id": runtime_context.get("call_id"),
            },
        )
        try:
            definition = self.get(name)
            self._validate_arguments(definition.parameter_schema, arguments)
            guardrail_started = time.perf_counter()
            decision = self.guardrail.evaluate(
                tool_name=name,
                arguments=arguments,
                policy=definition.guardrail_policy,
            )
            self._emit_guardrail(
                collector,
                decision,
                latency_ms=(time.perf_counter() - guardrail_started) * 1000,
            )
            if decision.decision == "block":
                normalized = self._result(
                    ok=False,
                    data=None,
                    error={
                        "code": "guardrail_blocked",
                        "message": decision.reason,
                        "details": {
                            "ruleId": decision.rule_id,
                            "actionType": decision.action_type,
                        },
                        "recoverable": False,
                    },
                    started=started,
                    truncated=False,
                )
                self._emit_trace(
                    collector,
                    "tool_completed",
                    name=name,
                    status="blocked",
                    latency_ms=normalized["duration"],
                    error_code="guardrail_blocked",
                    metadata={"rule_id": decision.rule_id},
                )
                self._emit_trace(
                    collector,
                    "error",
                    name=name,
                    status="blocked",
                    latency_ms=normalized["duration"],
                    error_code="guardrail_blocked",
                    metadata={"source": "guardrail", "rule_id": decision.rule_id},
                )
                return normalized
            if decision.decision == "needs_approval":
                pending = self.approval_manager.create(
                    decision,
                    arguments=arguments,
                    context=runtime_context,
                    policy=definition.guardrail_policy,
                    collector=collector,
                ).to_dict()
                normalized = self._result(
                    ok=False,
                    data={"pending": pending},
                    error={
                        "code": "approval_required",
                        "message": decision.reason,
                        "details": pending or {},
                        "recoverable": False,
                    },
                    started=started,
                    truncated=False,
                )
                self._emit_trace(
                    collector,
                    "tool_completed",
                    name=name,
                    status="needs_approval",
                    latency_ms=normalized["duration"],
                    error_code="approval_required",
                    metadata={"rule_id": decision.rule_id},
                )
                return normalized
            return self._invoke_handler(
                definition,
                arguments,
                runtime_context,
                collector=collector,
                started=started,
            )
        except ToolExecutionError as error:
            return self._execution_error(name, error, collector=collector, started=started)
        except Exception as error:
            return self._unexpected_error(name, error, collector=collector, started=started)

    def resolve_approval(
        self,
        *,
        approval_id: str,
        action_hash: str,
        decision: str,
    ) -> ApprovalResolution:
        """Resolve one approval and execute only its immutable stored action."""
        resolution, action = self.approval_manager.resolve(
            approval_id=approval_id,
            action_hash=action_hash,
            decision=decision,
        )
        if action is None:
            return resolution

        collector = action.collector
        started = time.perf_counter()
        try:
            definition = self.get(action.request.tool_name)
            if definition.guardrail_policy != action.policy:
                raise ToolExecutionError(
                    "approval_action_changed",
                    "approved tool policy no longer matches the pending action",
                    recoverable=False,
                )
            self._emit_trace(
                collector,
                "tool_called",
                name=action.request.tool_name,
                status="resumed",
                metadata={
                    "approval_id": approval_id,
                    "action_hash": action_hash,
                    "call_id": action.request.call_id,
                    "argument_names": sorted(action.arguments),
                },
            )
            resume_context = dict(action.context)
            resume_context["_trace_collector"] = collector
            tool_result = self._invoke_handler(
                definition,
                action.arguments,
                resume_context,
                collector=collector,
                started=started,
            )
        except ToolExecutionError as error:
            tool_result = self._execution_error(
                action.request.tool_name,
                error,
                collector=collector,
                started=started,
            )
        except Exception as error:
            tool_result = self._unexpected_error(
                action.request.tool_name,
                error,
                collector=collector,
                started=started,
            )

        self._emit_hitl_resume(
            collector,
            name=action.request.tool_name,
            approval_id=approval_id,
            action_hash=action_hash,
            call_id=action.request.call_id,
            tool_result=tool_result,
        )
        return ApprovalResolution(
            ok=tool_result["ok"],
            decision=resolution.decision,
            tool_result=tool_result,
            error=None if tool_result["ok"] else tool_result["error"],
            trace_events=tuple(collector.snapshot()) if collector is not None else (),
        )

    def _invoke_handler(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any],
        *,
        collector: Any,
        started: float,
    ) -> ToolResult:
        name = definition.name
        try:
            result = definition.handler(arguments, context)
            data, truncated = self._bounded_result(result, definition.max_result_bytes)
            normalized = self._result(
                ok=True,
                data=data,
                error=None,
                started=started,
                truncated=truncated,
            )
            self._emit_trace(
                collector,
                "tool_completed",
                name=name,
                status="ok",
                latency_ms=normalized["duration"],
                metadata={"truncated": truncated},
            )
            return normalized
        except ToolExecutionError as error:
            return self._execution_error(name, error, collector=collector, started=started)
        except Exception as error:
            return self._unexpected_error(name, error, collector=collector, started=started)

    def _execution_error(
        self,
        name: str,
        error: ToolExecutionError,
        *,
        collector: Any,
        started: float,
    ) -> ToolResult:
        normalized = self._result(
            ok=False,
            data=None,
            error={
                "code": error.code,
                "message": str(error),
                "details": error.details,
                "recoverable": error.recoverable,
            },
            started=started,
            truncated=False,
        )
        self._emit_trace(
            collector,
            "tool_completed",
            name=name,
            status="error",
            latency_ms=normalized["duration"],
            error_code=error.code,
            metadata={"recoverable": error.recoverable},
        )
        self._emit_trace(
            collector,
            "error",
            name=name,
            status="error",
            latency_ms=normalized["duration"],
            error_code=error.code,
            metadata={"source": "tool_registry"},
        )
        return normalized

    def _unexpected_error(
        self,
        name: str,
        error: Exception,
        *,
        collector: Any,
        started: float,
    ) -> ToolResult:
        normalized = self._result(
            ok=False,
            data=None,
            error={
                "code": "handler_error",
                "message": "tool execution failed unexpectedly",
                "details": {"exceptionType": type(error).__name__},
                "recoverable": True,
            },
            started=started,
            truncated=False,
        )
        self._emit_trace(
            collector,
            "tool_completed",
            name=name,
            status="error",
            latency_ms=normalized["duration"],
            error_code="handler_error",
            metadata={"exception_type": type(error).__name__},
        )
        self._emit_trace(
            collector,
            "error",
            name=name,
            status="error",
            latency_ms=normalized["duration"],
            error_code="handler_error",
            metadata={"source": "tool_handler"},
        )
        return normalized

    @staticmethod
    def _emit_hitl_resume(
        collector: Any,
        *,
        name: str,
        approval_id: str,
        action_hash: str,
        call_id: str | None,
        tool_result: ToolResult,
    ) -> None:
        emit = getattr(collector, "emit", None)
        if callable(emit):
            error = tool_result.get("error") or {}
            emit(
                "approval_resumed",
                component="hitl",
                name=name,
                status="ok" if tool_result["ok"] else "error",
                latency_ms=tool_result["duration"],
                error_code=error.get("code"),
                metadata={
                    "approval_id": approval_id,
                    "action_hash": action_hash,
                    "call_id": call_id,
                },
            )

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameter_schema,
                },
            }
            for tool in self._tools.values()
        ]

    @staticmethod
    def _emit_trace(
        collector: Any,
        event_type: str,
        *,
        name: str,
        status: str,
        latency_ms: float | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        emit = getattr(collector, "emit", None)
        if callable(emit):
            emit(
                event_type,
                component="tool",
                name=name,
                status=status,
                latency_ms=latency_ms,
                error_code=error_code,
                metadata=metadata,
            )

    @staticmethod
    def _emit_guardrail(
        collector: Any,
        decision: GuardrailDecision,
        *,
        latency_ms: float,
    ) -> None:
        emit = getattr(collector, "emit", None)
        if callable(emit):
            emit(
                "guardrail_decision",
                component="guardrail",
                name=decision.tool_name,
                status=decision.decision,
                latency_ms=latency_ms,
                error_code=(
                    "guardrail_blocked"
                    if decision.decision == "block"
                    else "approval_required"
                    if decision.decision == "needs_approval"
                    else None
                ),
                metadata={
                    "rule_id": decision.rule_id,
                    "action_type": decision.action_type,
                    "risk_level": decision.risk_level,
                    "tool_kind": decision.tool_kind,
                },
            )

    @staticmethod
    def _validate_definition(definition: ToolDefinition) -> None:
        if not isinstance(definition, ToolDefinition):
            raise TypeError("tool definition must be a ToolDefinition")
        if not isinstance(definition.name, str) or not definition.name.strip():
            raise ValueError("tool name cannot be empty")
        if not isinstance(definition.description, str) or not definition.description.strip():
            raise ValueError(f"tool description cannot be empty: {definition.name}")
        ToolRegistry._validate_parameter_schema(definition.name, definition.parameter_schema)
        if not callable(definition.handler):
            raise ValueError(f"tool handler must be callable: {definition.name}")
        if not isinstance(definition.guardrail_policy, ToolGuardrailPolicy):
            raise ValueError(f"tool guardrail policy is invalid: {definition.name}")
        try:
            signature = inspect.signature(definition.handler)
        except (TypeError, ValueError) as error:
            raise ValueError(f"tool handler signature cannot be inspected: {definition.name}") from error
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        has_varargs = any(
            parameter.kind == inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        )
        required_keyword_only = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind == inspect.Parameter.KEYWORD_ONLY
            and parameter.default is inspect.Parameter.empty
        ]
        if len(positional) != 2 or has_varargs or required_keyword_only:
            raise ValueError(
                f"tool handler must accept exactly (arguments, context): {definition.name}"
            )
        if (
            isinstance(definition.timeout_seconds, bool)
            or not isinstance(definition.timeout_seconds, (int, float))
            or not math.isfinite(definition.timeout_seconds)
            or definition.timeout_seconds <= 0
        ):
            raise ValueError(f"tool timeout must be a positive number: {definition.name}")
        if (
            isinstance(definition.max_result_bytes, bool)
            or not isinstance(definition.max_result_bytes, int)
            or definition.max_result_bytes < 256
        ):
            raise ValueError(f"tool max result bytes must be at least 256: {definition.name}")

    @staticmethod
    def _validate_parameter_schema(name: str, schema: dict[str, Any]) -> None:
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError(f"tool parameter schema must describe an object: {name}")
        properties = schema.get("properties")
        required = schema.get("required", [])
        if not isinstance(properties, dict):
            raise ValueError(f"tool parameter schema properties must be an object: {name}")
        if (
            not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or len(required) != len(set(required))
        ):
            raise ValueError(f"tool parameter schema required must contain unique names: {name}")
        missing_properties = [item for item in required if item not in properties]
        if missing_properties:
            raise ValueError(
                f"tool parameter schema requires undefined properties for {name}: "
                f"{', '.join(missing_properties)}"
            )
        invalid_properties = [
            property_name
            for property_name, rule in properties.items()
            if not isinstance(property_name, str) or not isinstance(rule, dict) or "type" not in rule
        ]
        if invalid_properties:
            raise ValueError(f"tool parameter schema contains invalid properties: {name}")

    @staticmethod
    def _result(
        *,
        ok: bool,
        data: Any,
        error: dict[str, Any] | None,
        started: float,
        truncated: bool,
    ) -> ToolResult:
        return {
            "ok": ok,
            "data": data,
            "error": error,
            "duration": round((time.perf_counter() - started) * 1000, 3),
            "truncated": truncated,
        }

    @staticmethod
    def _bounded_result(result: Any, max_result_bytes: int) -> tuple[Any, bool]:
        try:
            serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            raise ToolExecutionError(
                "invalid_tool_result",
                "tool result must be JSON serializable",
                {"exceptionType": type(error).__name__},
            ) from error
        original_size = len(serialized.encode("utf-8"))
        if original_size <= max_result_bytes:
            return result, False

        metadata = {
            "truncated": True,
            "originalSizeBytes": original_size,
            "maxResultBytes": max_result_bytes,
        }
        low = 0
        high = len(serialized)
        while low < high:
            middle = (low + high + 1) // 2
            candidate = {"preview": serialized[:middle], "_meta": metadata}
            candidate_size = len(
                json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            if candidate_size <= max_result_bytes:
                low = middle
            else:
                high = middle - 1
        return {"preview": serialized[:low], "meta": metadata}, True

    @staticmethod
    def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ToolExecutionError("invalid_arguments", "tool arguments must be an object")
        ToolRegistry._validate_value(schema, arguments, "arguments")

    @staticmethod
    def _validate_value(rule: dict[str, Any], value: Any, path: str) -> None:
        expected_types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "object": dict,
            "array": list,
            "boolean": bool,
        }
        rule_type = rule.get("type")
        expected = expected_types.get(rule_type)
        if expected and (
            not isinstance(value, expected)
            or (rule_type in {"integer", "number"} and isinstance(value, bool))
        ):
            raise ToolExecutionError("invalid_arguments", f"{path} has invalid type")
        if rule_type == "number" and not math.isfinite(value):
            raise ToolExecutionError("invalid_arguments", f"{path} must be finite")
        if "enum" in rule and value not in rule["enum"]:
            raise ToolExecutionError("invalid_arguments", f"{path} is not an allowed value")

        if rule_type == "string":
            if "minLength" in rule and len(value) < rule["minLength"]:
                raise ToolExecutionError("invalid_arguments", f"{path} is too short")
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                raise ToolExecutionError("invalid_arguments", f"{path} is too long")
        if rule_type in {"integer", "number"}:
            if "minimum" in rule and value < rule["minimum"]:
                raise ToolExecutionError("invalid_arguments", f"{path} is below minimum")
            if "maximum" in rule and value > rule["maximum"]:
                raise ToolExecutionError("invalid_arguments", f"{path} exceeds maximum")
        if rule_type == "array" and isinstance(rule.get("items"), dict):
            for index, item in enumerate(value):
                ToolRegistry._validate_value(rule["items"], item, f"{path}[{index}]")
        if rule_type == "object":
            properties = rule.get("properties", {})
            missing = [name for name in rule.get("required", []) if name not in value]
            if missing:
                raise ToolExecutionError(
                    "invalid_arguments", f"missing required arguments: {', '.join(missing)}"
                )
            if rule.get("additionalProperties") is False:
                unknown = [name for name in value if name not in properties]
                if unknown:
                    raise ToolExecutionError(
                        "invalid_arguments", f"unknown arguments: {', '.join(unknown)}"
                    )
            for name, item in value.items():
                nested_rule = properties.get(name)
                if isinstance(nested_rule, dict):
                    ToolRegistry._validate_value(nested_rule, item, f"{path}.{name}")
