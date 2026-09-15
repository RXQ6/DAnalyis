"""Tool metadata, validation, and dispatch for the Day8 Agent Loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Any]


class ToolExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameter_schema: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if not definition.name:
            raise ValueError("tool name cannot be empty")
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolExecutionError("unknown_tool", f"tool is not registered: {name}") from error

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        definition = self.get(name)
        self._validate_arguments(definition.parameter_schema, arguments)
        try:
            return definition.handler(arguments, context or {})
        except ToolExecutionError:
            raise
        except Exception as error:
            raise ToolExecutionError("handler_error", str(error)) from error

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
    def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ToolExecutionError("invalid_arguments", "tool arguments must be an object")
        properties = schema.get("properties", {})
        missing = [name for name in schema.get("required", []) if name not in arguments]
        if missing:
            raise ToolExecutionError("invalid_arguments", f"missing required arguments: {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            unknown = [name for name in arguments if name not in properties]
            if unknown:
                raise ToolExecutionError("invalid_arguments", f"unknown arguments: {', '.join(unknown)}")
        expected_types = {"string": str, "integer": int, "number": (int, float), "object": dict, "array": list}
        for name, value in arguments.items():
            rule = properties.get(name, {})
            expected = expected_types.get(rule.get("type"))
            if expected and (not isinstance(value, expected) or isinstance(value, bool)):
                raise ToolExecutionError("invalid_arguments", f"argument {name} has invalid type")
            if "enum" in rule and value not in rule["enum"]:
                raise ToolExecutionError("invalid_arguments", f"argument {name} is not an allowed value")

