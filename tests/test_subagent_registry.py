from __future__ import annotations

import time
import unittest
from typing import Any

from subagents.registry import (
    DATA_CHECK_TOOLS,
    DELEGATE_TOOL_NAME,
    ToolBudget,
    build_restricted_registry,
)
from tools.registry import ToolDefinition, ToolRegistry


SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def source_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name in (*DATA_CHECK_TOOLS, DELEGATE_TOOL_NAME, "todo_write"):
        def handler(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        registry.register(
            ToolDefinition(
                name=name,
                description=f"test {name}",
                parameter_schema=SCHEMA,
                handler=handler,
            )
        )
    return registry


class SubAgentRegistryTests(unittest.TestCase):
    def budget(self, calls: int = 4) -> ToolBudget:
        return ToolBudget(calls, time.monotonic() + 10)

    def test_registry_exposes_exact_read_only_allowlist(self) -> None:
        restricted = build_restricted_registry(source_registry(), budget=self.budget())
        names = {
            schema["function"]["name"] for schema in restricted.tool_schemas()
        }
        self.assertEqual(names, set(DATA_CHECK_TOOLS))
        for forbidden in (DELEGATE_TOOL_NAME, "todo_write"):
            result = restricted.execute(forbidden, {})
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "TOOL_NOT_FOUND")

    def test_registry_rejects_recursive_or_invalid_allowlist(self) -> None:
        with self.assertRaises(ValueError):
            build_restricted_registry(
                source_registry(),
                budget=self.budget(),
                allowed_tools=(DELEGATE_TOOL_NAME,),
            )
        with self.assertRaises(Exception):
            build_restricted_registry(
                source_registry(),
                budget=self.budget(),
                allowed_tools=("missing_tool",),
            )

    def test_tool_budget_stops_the_fifth_call(self) -> None:
        restricted = build_restricted_registry(
            source_registry(), budget=self.budget(calls=4)
        )
        for _ in range(4):
            self.assertTrue(restricted.execute("inspect_data", {})["ok"])
        rejected = restricted.execute("inspect_data", {})
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "subagent_tool_budget_exceeded")
        self.assertFalse(rejected["error"]["recoverable"])


if __name__ == "__main__":
    unittest.main()
