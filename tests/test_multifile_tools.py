from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.loop import AgentLoop
from datasets import DatasetRegistry
from tools.handlers import build_default_registry


def previous(call_id: str, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "callId": call_id,
        "toolName": tool_name,
        "arguments": arguments,
        "toolResult": result,
    }


class ScriptedModel:
    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        return self.decisions[len(self.calls) - 1]


class MultiFileToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.registry = DatasetRegistry(self.root / "derived")
        self.tools = build_default_registry()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def add(self, name: str, content: str) -> dict[str, Any]:
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return self.registry.register(path)

    def context(self, previous_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "dataset_registry": self.registry,
            "previous_tool_results": previous_results or [],
            "call_id": "test-call",
        }

    def test_list_and_inspect_return_summaries_without_paths_or_rows(self) -> None:
        summary = self.add("sales.csv", "id,销售额\nA,10\nB,20\n")

        listed = self.tools.execute("list_datasets", {}, context=self.context())
        inspected = self.tools.execute(
            "inspect_dataset", {"datasetId": summary["datasetId"]}, context=self.context()
        )

        self.assertTrue(listed["ok"] and inspected["ok"])
        encoded = json.dumps([listed["data"], inspected["data"]], ensure_ascii=False)
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn('"rows"', encoded)

    def test_existing_analysis_tools_select_datasets_by_id(self) -> None:
        first = self.add("first.csv", "id,销售额\nA,10\nB,20\n")
        second = self.add("second.csv", "id,销售额\nC,100\n")

        first_result = self.tools.execute(
            "basic_stats",
            {"datasetId": first["datasetId"], "metric": "销售额", "operation": "sum"},
            context=self.context(),
        )
        second_result = self.tools.execute(
            "basic_stats",
            {"datasetId": second["datasetId"], "metric": "销售额", "operation": "sum"},
            context=self.context(),
        )

        self.assertEqual(first_result["data"]["value"], 30)
        self.assertEqual(second_result["data"]["value"], 100)

    def test_dataset_id_is_required_in_registry_mode(self) -> None:
        self.add("sales.csv", "id,销售额\nA,10\n")
        result = self.tools.execute(
            "basic_stats",
            {"metric": "销售额", "operation": "sum"},
            context=self.context(),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "dataset_id_required")

    def test_compare_uses_prior_tool_results_without_model_values(self) -> None:
        first = self.add("first.csv", "id,销售额\nA,10\nB,20\n")
        second = self.add("second.csv", "id,销售额\nC,100\n")
        args1 = {"datasetId": first["datasetId"], "metric": "销售额", "operation": "sum"}
        args2 = {"datasetId": second["datasetId"], "metric": "销售额", "operation": "sum"}
        result1 = self.tools.execute("basic_stats", args1, context=self.context())
        result2 = self.tools.execute("basic_stats", args2, context=self.context())

        compared = self.tools.execute(
            "compare_datasets",
            {"sourceCallIds": ["stats-1", "stats-2"]},
            context=self.context(
                [
                    previous("stats-1", "basic_stats", args1, result1),
                    previous("stats-2", "basic_stats", args2, result2),
                ]
            ),
        )

        self.assertTrue(compared["ok"])
        self.assertEqual(
            [item["value"] for item in compared["data"]["groups"]], [30, 100]
        )
        chart = self.tools.execute(
            "generate_chart",
            {"sourceCallId": "compare-1", "chartType": "bar"},
            context={
                **self.context(
                    [
                        previous(
                            "compare-1",
                            "compare_datasets",
                            {"sourceCallIds": ["stats-1", "stats-2"]},
                            compared,
                        )
                    ]
                ),
                "artifact_dir": str(self.root / "charts"),
                "call_id": "compare-chart",
            },
        )
        self.assertTrue(chart["ok"])
        self.assertEqual(
            [item["y"] for item in chart["data"]["spec"]["data"]["values"]],
            [30, 100],
        )
        injected = self.tools.execute(
            "compare_datasets",
            {"sourceCallIds": ["stats-1", "stats-2"], "values": [999, 999]},
            context=self.context(),
        )
        self.assertEqual(injected["error"]["code"], "invalid_arguments")

    def test_safe_one_to_one_merge_creates_a_derived_dataset(self) -> None:
        left = self.add("orders.csv", "订单,客户,销售额\nO1,C1,10\nO2,C2,20\n")
        right = self.add("customers.csv", "客户ID,地区\nC1,华东\nC2,华南\n")
        inspect_args = {
            "leftDatasetId": left["datasetId"],
            "rightDatasetId": right["datasetId"],
            "leftKey": "客户",
            "rightKey": "客户ID",
            "joinType": "left",
        }
        inspected = self.tools.execute("inspect_merge", inspect_args, context=self.context())
        self.assertTrue(inspected["ok"])
        self.assertEqual(inspected["data"]["cardinality"], "one_to_one")
        self.assertTrue(inspected["data"]["safeToExecute"])

        merged = self.tools.execute(
            "merge_datasets",
            {"preflightCallId": "preflight-1"},
            context=self.context(
                [previous("preflight-1", "inspect_merge", inspect_args, inspected)]
            ),
        )

        self.assertTrue(merged["ok"])
        derived = merged["data"]["dataset"]
        self.assertTrue(derived["derived"])
        self.assertEqual(derived["rowCount"], 2)
        self.assertIn("地区", [column["name"] for column in derived["columns"]])
        stats = self.tools.execute(
            "basic_stats",
            {"datasetId": derived["datasetId"], "metric": "销售额", "operation": "sum"},
            context=self.context(),
        )
        self.assertEqual(stats["data"]["value"], 30)

    def test_merge_preflight_detects_and_blocks_cardinality_risk(self) -> None:
        left = self.add("orders.csv", "订单,客户\nO1,C1\nO2,C2\n")
        right = self.add("tags.csv", "客户ID,标签\nC1,A\nC1,B\nC2,C\n")
        inspect_args = {
            "leftDatasetId": left["datasetId"],
            "rightDatasetId": right["datasetId"],
            "leftKey": "客户",
            "rightKey": "客户ID",
            "joinType": "left",
        }
        inspected = self.tools.execute("inspect_merge", inspect_args, context=self.context())
        self.assertEqual(inspected["data"]["cardinality"], "one_to_many")
        self.assertEqual(inspected["data"]["rightKeyStats"]["duplicateKeyCount"], 1)
        self.assertFalse(inspected["data"]["safeToExecute"])

        merged = self.tools.execute(
            "merge_datasets",
            {"preflightCallId": "preflight-risk"},
            context=self.context(
                [previous("preflight-risk", "inspect_merge", inspect_args, inspected)]
            ),
        )
        self.assertFalse(merged["ok"])
        self.assertEqual(merged["error"]["code"], "unsafe_merge_plan")

    def test_merge_preflight_classifies_many_to_one_and_many_to_many(self) -> None:
        left_many = self.add("left_many.csv", "客户,订单\nC1,O1\nC1,O2\n")
        right_one = self.add("right_one.csv", "客户ID,地区\nC1,华东\n")
        many_to_one = self.tools.execute(
            "inspect_merge",
            {"leftDatasetId": left_many["datasetId"], "rightDatasetId": right_one["datasetId"], "leftKey": "客户", "rightKey": "客户ID", "joinType": "inner"},
            context=self.context(),
        )
        self.assertEqual(many_to_one["data"]["cardinality"], "many_to_one")
        self.assertFalse(many_to_one["data"]["safeToExecute"])

        right_many = self.add("right_many.csv", "客户ID,标签\nC1,A\nC1,B\n")
        many_to_many = self.tools.execute(
            "inspect_merge",
            {"leftDatasetId": left_many["datasetId"], "rightDatasetId": right_many["datasetId"], "leftKey": "客户", "rightKey": "客户ID", "joinType": "inner"},
            context=self.context(),
        )
        self.assertEqual(many_to_many["data"]["cardinality"], "many_to_many")
        self.assertFalse(many_to_many["data"]["safeToExecute"])

    def test_merge_rechecks_fingerprint_and_rejects_stale_plan(self) -> None:
        left = self.add("left_stale.csv", "客户,销售额\nC1,10\n")
        right_path = self.root / "right_stale.csv"
        right_path.write_text("客户ID,地区\nC1,华东\n", encoding="utf-8")
        right = self.registry.register(right_path)
        inspect_args = {
            "leftDatasetId": left["datasetId"], "rightDatasetId": right["datasetId"],
            "leftKey": "客户", "rightKey": "客户ID", "joinType": "left",
        }
        inspected = self.tools.execute("inspect_merge", inspect_args, context=self.context())
        right_path.write_text("客户ID,地区\nC1,华南\n", encoding="utf-8")

        merged = self.tools.execute(
            "merge_datasets",
            {"preflightCallId": "stale-plan"},
            context=self.context([previous("stale-plan", "inspect_merge", inspect_args, inspected)]),
        )
        self.assertFalse(merged["ok"])
        self.assertEqual(merged["error"]["code"], "stale_merge_plan")

    def test_merge_preflight_rejects_missing_and_incompatible_keys(self) -> None:
        left = self.add("left.csv", "id,value\n1,10\n")
        right = self.add("right.csv", "id,name\nA,甲\n")
        incompatible = self.tools.execute(
            "inspect_merge",
            {"leftDatasetId": left["datasetId"], "rightDatasetId": right["datasetId"], "leftKey": "id", "rightKey": "id", "joinType": "inner"},
            context=self.context(),
        )
        self.assertTrue(incompatible["ok"])
        self.assertFalse(incompatible["data"]["typesCompatible"])
        self.assertIn("incompatible_key_types", incompatible["data"]["risks"])

        missing = self.tools.execute(
            "inspect_merge",
            {"leftDatasetId": left["datasetId"], "rightDatasetId": right["datasetId"], "leftKey": "missing", "rightKey": "id", "joinType": "inner"},
            context=self.context(),
        )
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "missing_join_field")

    def test_agent_receives_only_registry_summary(self) -> None:
        summary = self.add("secret.csv", "id,销售额\n客户甲,10\n")
        model = ScriptedModel([{"type": "final_answer", "content": "已看到摘要。"}])
        state = AgentLoop(model, self.tools).run(
            "列出数据集", dataset_registry=self.registry
        )

        user_message = next(item for item in model.calls[0]["messages"] if item["role"] == "user")
        encoded = json.dumps(user_message, ensure_ascii=False)
        self.assertIn(summary["datasetId"], encoded)
        self.assertNotIn("客户甲", encoded)
        self.assertNotIn(str(self.root), encoded)
        self.assertEqual(state.stop_reason, "final_answer")

        with self.assertRaisesRegex(ValueError, "derived from DatasetRegistry"):
            AgentLoop(ScriptedModel([]), self.tools).run(
                "不允许旁路摘要",
                dataset_registry=self.registry,
                dataset_context={"rows": [{"id": "raw"}]},
            )

    def test_year_over_year_rate_is_deterministic_and_handles_zero_baseline(self) -> None:
        first = self.add("2025.csv", "销售额\n50\n")
        second = self.add("2026.csv", "销售额\n100\n")
        args1 = {"datasetId": first["datasetId"], "metric": "销售额", "operation": "sum"}
        args2 = {"datasetId": second["datasetId"], "metric": "销售额", "operation": "sum"}
        one = self.tools.execute("basic_stats", args1, context=self.context())
        two = self.tools.execute("basic_stats", args2, context=self.context())
        compared = self.tools.execute(
            "compare_datasets", {"sourceCallIds": ["one", "two"], "comparisonMode": "year_over_year"},
            context=self.context([previous("one", "basic_stats", args1, one), previous("two", "basic_stats", args2, two)]),
        )
        self.assertTrue(compared["ok"])
        self.assertEqual(compared["data"]["yearOverYearRate"], 1)
        self.assertEqual(compared["data"]["yearOverYearPercent"], 100)

        zero_data = dict(one["data"])
        zero_data["value"] = 0
        zero = {**one, "data": zero_data}
        zero_compared = self.tools.execute(
            "compare_datasets", {"sourceCallIds": ["zero", "two"], "comparisonMode": "year_over_year"},
            context=self.context([previous("zero", "basic_stats", args1, zero), previous("two", "basic_stats", args2, two)]),
        )
        self.assertTrue(zero_compared["ok"])
        self.assertIsNone(zero_compared["data"]["yearOverYearRate"])
        self.assertEqual(zero_compared["data"]["yearOverYearStatus"], "undefined_zero_baseline")

        missing_data = dict(one["data"])
        missing_data["value"] = None
        missing = {**one, "data": missing_data}
        missing_compared = self.tools.execute(
            "compare_datasets", {"sourceCallIds": ["missing", "two"], "comparisonMode": "year_over_year"},
            context=self.context([previous("missing", "basic_stats", args1, missing), previous("two", "basic_stats", args2, two)]),
        )
        self.assertFalse(missing_compared["ok"])
        self.assertEqual(missing_compared["error"]["code"], "missing_comparison_value")

    def test_group_compare_sources_are_aligned_and_dimensions_validated(self) -> None:
        first = self.add("first-groups.csv", "类别,销售额\nA,10\nB,40\n")
        second = self.add("second-groups.csv", "类别,销售额\nA,30\nB,70\n")
        args1 = {"datasetId": first["datasetId"], "groupBy": "类别", "metric": "销售额", "operation": "sum"}
        args2 = {"datasetId": second["datasetId"], "groupBy": "类别", "metric": "销售额", "operation": "sum"}
        one = self.tools.execute("group_compare", args1, context=self.context())
        two = self.tools.execute("group_compare", args2, context=self.context())
        compared = self.tools.execute(
            "compare_datasets", {"sourceCallIds": ["one", "two"]},
            context=self.context([previous("one", "group_compare", args1, one), previous("two", "group_compare", args2, two)]),
        )
        self.assertTrue(compared["ok"])
        categories = {item["group"]: item for item in compared["data"]["categories"]}
        self.assertEqual(set(categories), {"A", "B"})
        self.assertEqual([item["value"] for item in categories["A"]["values"]], [10, 30])

        bad_data = dict(two["data"])
        bad_data["groupBy"] = "地区"
        bad = {**two, "data": bad_data}
        mismatch = self.tools.execute(
            "compare_datasets", {"sourceCallIds": ["one", "bad"]},
            context=self.context([previous("one", "group_compare", args1, one), previous("bad", "group_compare", args2, bad)]),
        )
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["error"]["code"], "incompatible_comparison_sources")

        wrong_mode = self.tools.execute(
            "compare_datasets", {"sourceCallIds": ["one", "two"], "comparisonMode": "year_over_year"},
            context=self.context([previous("one", "group_compare", args1, one), previous("two", "group_compare", args2, two)]),
        )
        self.assertFalse(wrong_mode["ok"])
        self.assertEqual(wrong_mode["error"]["code"], "incompatible_comparison_mode")

    def test_group_compare_marks_missing_category_instead_of_treating_it_as_zero(self) -> None:
        first = self.add("all-categories.csv", "类别,销售额\nA,10\nB,40\n")
        second = self.add("missing-category.csv", "类别,销售额\nA,30\n")
        args1 = {"datasetId": first["datasetId"], "groupBy": "类别", "metric": "销售额", "operation": "sum"}
        args2 = {"datasetId": second["datasetId"], "groupBy": "类别", "metric": "销售额", "operation": "sum"}
        one = self.tools.execute("group_compare", args1, context=self.context())
        two = self.tools.execute("group_compare", args2, context=self.context())
        compared = self.tools.execute(
            "compare_datasets", {"sourceCallIds": ["one", "two"]},
            context=self.context([previous("one", "group_compare", args1, one), previous("two", "group_compare", args2, two)]),
        )
        categories = {item["group"]: item for item in compared["data"]["categories"]}
        missing = categories["B"]["values"][1]
        self.assertTrue(missing["missing"])
        self.assertIsNone(missing["value"])

    def test_compare_rejects_truncated_sources_without_using_preview_values(self) -> None:
        first = self.add("first-truncated.csv", "销售额\n10\n")
        second = self.add("second-truncated.csv", "销售额\n20\n")
        args1 = {"datasetId": first["datasetId"], "metric": "销售额", "operation": "sum"}
        args2 = {"datasetId": second["datasetId"], "metric": "销售额", "operation": "sum"}
        one = self.tools.execute("basic_stats", args1, context=self.context())
        two = self.tools.execute("basic_stats", args2, context=self.context())
        truncated = {**one, "data": {"preview": "{\"value\":10}"}, "truncated": True}
        compared = self.tools.execute(
            "compare_datasets", {"sourceCallIds": ["one", "two"]},
            context=self.context([previous("one", "basic_stats", args1, truncated), previous("two", "basic_stats", args2, two)]),
        )
        self.assertFalse(compared["ok"])
        self.assertEqual(compared["error"]["code"], "comparison_source_truncated")


if __name__ == "__main__":
    unittest.main()
