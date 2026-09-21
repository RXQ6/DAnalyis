from __future__ import annotations

import unittest

from skill_runtime import build_skill_tool_view
from tools import build_default_registry


class SkillToolViewTests(unittest.TestCase):
    def test_view_contains_only_allowed_existing_definitions(self) -> None:
        source = build_default_registry()
        allowed = ("inspect_data", "basic_stats", "detect_anomaly")

        view = build_skill_tool_view(source, allowed)
        names = tuple(item["function"]["name"] for item in view.tool_schemas())

        self.assertEqual(names, allowed)
        self.assertIs(
            view.get("inspect_data").handler,
            source.get("inspect_data").handler,
        )
        self.assertIn("todo_write", [item["function"]["name"] for item in source.tool_schemas()])

    def test_unauthorized_tool_is_rejected_by_restricted_registry(self) -> None:
        view = build_skill_tool_view(build_default_registry(), ("inspect_data",))

        result = view.execute("generate_chart", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "TOOL_NOT_FOUND")

    def test_missing_allowed_tool_fails_before_execution(self) -> None:
        with self.assertRaisesRegex(ValueError, "unavailable tool"):
            build_skill_tool_view(build_default_registry(), ("not_registered",))


if __name__ == "__main__":
    unittest.main()

