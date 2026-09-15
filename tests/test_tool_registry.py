from __future__ import annotations

import unittest
from typing import Any

from tools.handlers import build_default_registry
from tools.registry import ToolDefinition, ToolExecutionError, ToolRegistry


def schema(*required: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": "string"} for name in required},
        "required": list(required),
        "additionalProperties": False,
    }


def handler(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {"arguments": arguments, "context": context}


class RecordingBridge:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(
        self, name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(name)
        return {"name": name}


class ToolRegistryTests(unittest.TestCase):
    def test_register_many_registers_multiple_tools(self) -> None:
        registry = ToolRegistry()
        registry.register_many(
            [
                ToolDefinition("first", "first tool", schema(), handler),
                ToolDefinition("second", "second tool", schema(), handler),
            ]
        )

        self.assertEqual(
            [item["function"]["name"] for item in registry.tool_schemas()],
            ["first", "second"],
        )

    def test_register_many_rejects_duplicates_without_partial_registration(self) -> None:
        registry = ToolRegistry()
        registry.register(ToolDefinition("existing", "existing tool", schema(), handler))

        with self.assertRaisesRegex(ValueError, "tool already registered: existing"):
            registry.register_many(
                [
                    ToolDefinition("new_tool", "new tool", schema(), handler),
                    ToolDefinition("existing", "duplicate tool", schema(), handler),
                ]
            )

        with self.assertRaises(ToolExecutionError) as raised:
            registry.get("new_tool")
        self.assertEqual(raised.exception.code, "unknown_tool")

    def test_register_many_rejects_duplicate_names_inside_batch(self) -> None:
        registry = ToolRegistry()
        duplicate = ToolDefinition("same", "same tool", schema(), handler)

        with self.assertRaisesRegex(ValueError, "tool already registered: same"):
            registry.register_many([duplicate, duplicate])

        self.assertEqual(registry.tool_schemas(), [])

    def test_unknown_tool_has_stable_error_code(self) -> None:
        with self.assertRaises(ToolExecutionError) as raised:
            ToolRegistry().execute("missing", {})

        self.assertEqual(raised.exception.code, "unknown_tool")

    def test_registration_rejects_schema_requiring_undefined_property(self) -> None:
        invalid_schema = {
            "type": "object",
            "properties": {},
            "required": ["metric"],
            "additionalProperties": False,
        }

        with self.assertRaisesRegex(ValueError, "requires undefined properties"):
            ToolRegistry().register(
                ToolDefinition("invalid", "invalid schema", invalid_schema, handler)
            )

    def test_registration_rejects_handler_signature_mismatch(self) -> None:
        def invalid_handler(arguments: dict[str, Any]) -> None:
            del arguments

        with self.assertRaisesRegex(ValueError, r"exactly \(arguments, context\)"):
            ToolRegistry().register(
                ToolDefinition("invalid", "invalid handler", schema(), invalid_handler)
            )

    def test_factory_binds_each_tool_name_without_late_binding(self) -> None:
        bridge = RecordingBridge()
        registry = build_default_registry(bridge=bridge)
        names = [item["function"]["name"] for item in registry.tool_schemas()]

        for name in names:
            definition = registry.get(name)
            self.assertEqual(definition.handler({}, {}), {"name": name})

        self.assertEqual(bridge.calls, names)

    def test_default_catalog_is_the_single_registry_source(self) -> None:
        names = [
            item["function"]["name"]
            for item in build_default_registry(bridge=RecordingBridge()).tool_schemas()
        ]

        self.assertEqual(
            names,
            [
                "inspect_data",
                "basic_stats",
                "group_compare",
                "trend_analysis",
                "detect_anomaly",
                "top_n",
            ],
        )


if __name__ == "__main__":
    unittest.main()
