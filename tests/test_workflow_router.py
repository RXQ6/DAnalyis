from __future__ import annotations

import unittest
from typing import Any

from workflow import ROUTES, RuleRouter


class FallbackModel:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        return self.response


class WorkflowRouterTests(unittest.TestCase):
    def route(self, query: str, **state: Any) -> dict[str, Any]:
        return RuleRouter().route(
            {"query": query, **state}, allowed_routes=ROUTES
        )

    def test_clear_rules_cover_the_four_routes(self) -> None:
        cases = [
            ("你好", {}, "chat"),
            ("请计算 1 + 2 * 3", {}, "calc"),
            ("按地区统计销售额", {"dataset_paths": ["sales.csv"]}, "analysis"),
            ("你还记得我偏好的指标吗", {"memory_scope": "user-a"}, "memory_recall"),
        ]
        for query, state, expected in cases:
            with self.subTest(query=query):
                decision = self.route(query, **state)
                self.assertEqual(decision["route"], expected)
                self.assertEqual(decision["source"], "rule")

    def test_analysis_wins_when_memory_preference_is_used_for_current_data(self) -> None:
        decision = self.route(
            "按我的偏好指标分析当前文件",
            dataset_paths=["sales.csv"],
            memory_scope="user-a",
        )
        self.assertEqual(decision["route"], "analysis")

    def test_dataset_calculation_is_not_misrouted_to_pure_calc(self) -> None:
        decision = self.route("计算销售额总和", dataset_paths=["sales.csv"])
        self.assertEqual(decision["route"], "analysis")

    def test_active_dataset_follow_up_routes_to_analysis(self) -> None:
        decision = self.route("那华东呢", active_dataset_ids=["ds_123"])
        self.assertEqual(decision["route"], "analysis")

    def test_rule_hit_never_calls_fallback_model(self) -> None:
        model = FallbackModel({"route": "analysis"})
        decision = RuleRouter(model).route(
            {"query": "1 + 1"}, allowed_routes=ROUTES
        )
        self.assertEqual(decision["route"], "calc")
        self.assertEqual(model.calls, [])

    def test_ambiguous_request_uses_valid_llm_fallback(self) -> None:
        model = FallbackModel({"content": '{"route": "chat"}'})
        decision = RuleRouter(model).route(
            {"query": "给我一些建议"}, allowed_routes=ROUTES
        )
        self.assertEqual(decision["route"], "chat")
        self.assertEqual(decision["source"], "llm_fallback")
        self.assertEqual(model.calls[0]["tools"], [])

    def test_invalid_llm_route_can_never_escape_registered_routes(self) -> None:
        model = FallbackModel({"route": "sql_admin"})
        decision = RuleRouter(model).route(
            {"query": "做点什么"}, allowed_routes=ROUTES
        )
        self.assertEqual(decision["route"], "chat")
        self.assertIn(decision["route"], ROUTES)
        self.assertEqual(decision["source"], "safe_fallback")


if __name__ == "__main__":
    unittest.main()
