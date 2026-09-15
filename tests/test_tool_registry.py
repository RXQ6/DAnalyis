from __future__ import annotations

import json
import subprocess
import unittest
from typing import Any
from unittest.mock import patch

from tools.handlers import NodeToolBridge, build_default_registry
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
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
        *,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        del arguments, context, timeout_seconds
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
        result = ToolRegistry().execute("missing", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "unknown_tool")
        self.assertIsNone(result["data"])
        self.assertFalse(result["truncated"])

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

    def test_nested_arguments_and_numeric_bounds_are_validated(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "bounded",
                "bounded test tool",
                {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "minimum": 1, "maximum": 3},
                        "options": {
                            "type": "object",
                            "properties": {"label": {"type": "string", "minLength": 1}},
                            "required": ["label"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["count", "options"],
                    "additionalProperties": False,
                },
                handler,
            )
        )

        for arguments in (
            {"count": 0, "options": {"label": "ok"}},
            {"count": 1, "options": {"label": ""}},
            {"count": 1, "options": {"label": "ok", "extra": True}},
        ):
            with self.subTest(arguments=arguments):
                result = registry.execute("bounded", arguments)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "invalid_arguments")

    def test_unexpected_handler_exception_is_sanitized(self) -> None:
        def failing_handler(arguments: dict[str, Any], context: dict[str, Any]) -> None:
            del arguments, context
            raise RuntimeError("sensitive implementation detail")

        registry = ToolRegistry()
        registry.register(
            ToolDefinition("failing", "failing tool", schema(), failing_handler)
        )

        result = registry.execute("failing", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "handler_error")
        self.assertNotIn("sensitive", result["error"]["message"])
        self.assertEqual(result["error"]["details"], {"exceptionType": "RuntimeError"})

    def test_large_result_is_truncated_to_a_json_safe_preview(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                "large",
                "large result tool",
                schema(),
                lambda arguments, context: {"rows": ["数据" * 1000]},
                max_result_bytes=512,
            )
        )

        result = registry.execute("large", {})

        self.assertTrue(result["ok"])
        self.assertTrue(result["truncated"])
        self.assertGreater(result["data"]["meta"]["originalSizeBytes"], 512)
        self.assertLessEqual(
            len(json.dumps(result["data"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            512,
        )

    def test_default_catalog_rejects_out_of_range_top_n_before_handler(self) -> None:
        bridge = RecordingBridge()
        registry = build_default_registry(bridge=bridge)

        result = registry.execute("top_n", {"metric": "销售额", "count": 1001})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_arguments")
        self.assertEqual(bridge.calls, [])

    def test_successful_execution_returns_the_uniform_tool_result(self) -> None:
        registry = ToolRegistry()
        registry.register(ToolDefinition("echo", "echo tool", schema("value"), handler))

        result = registry.execute("echo", {"value": "ok"}, context={"iteration": 1})

        self.assertEqual(
            set(result), {"ok", "data", "error", "duration", "truncated"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["data"],
            {"arguments": {"value": "ok"}, "context": {"iteration": 1}},
        )
        self.assertIsNone(result["error"])
        self.assertGreaterEqual(result["duration"], 0)
        self.assertFalse(result["truncated"])

    def test_node_bridge_timeout_has_a_stable_error(self) -> None:
        timeout = subprocess.TimeoutExpired(cmd=["node"], timeout=0.25)
        with patch("tools.handlers.subprocess.run", side_effect=timeout) as run:
            with self.assertRaises(ToolExecutionError) as raised:
                NodeToolBridge().execute(
                    "inspect_data", {}, {"dataset": "data.csv"}, timeout_seconds=0.25
                )

        self.assertEqual(raised.exception.code, "tool_timeout")
        self.assertEqual(raised.exception.details, {"timeoutSeconds": 0.25})
        self.assertEqual(run.call_args.kwargs["timeout"], 0.25)

    def test_node_bridge_preserves_structured_error_details(self) -> None:
        response = subprocess.CompletedProcess(
            args=["node"],
            returncode=1,
            stdout=json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": "dirty_numeric_data",
                        "message": "数据不干净",
                        "invalidCount": 3,
                    },
                }
            ),
            stderr="",
        )
        with patch("tools.handlers.subprocess.run", return_value=response):
            with self.assertRaises(ToolExecutionError) as raised:
                NodeToolBridge().execute("basic_stats", {}, {"dataset": "data.csv"})

        self.assertEqual(raised.exception.code, "dirty_numeric_data")
        self.assertEqual(raised.exception.details, {"invalidCount": 3})


if __name__ == "__main__":
    unittest.main()
