"""Tool metadata, validation, and dispatch for the Day8 Agent Loop."""

from __future__ import annotations

import inspect
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
