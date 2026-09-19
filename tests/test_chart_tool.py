from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from charts.spec import MAX_CHART_POINTS, ChartSpecError, build_chart_spec
from tools.handlers import build_default_registry


def prior_result(
    *,
    call_id: str,
    tool_name: str,
    data: object,
    ok: bool = True,
    truncated: bool = False,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "callId": call_id,
        "toolName": tool_name,
        "arguments": arguments or {},
        "toolResult": {
            "ok": ok,
            "data": data,
            "error": None if ok else {"code": "source_failed"},
            "duration": 1.0,
            "truncated": truncated,
        },
    }


class ChartToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_group_result_becomes_bar_spec_and_svg_without_recalculation(self) -> None:
        source_data = {
            "groupBy": "地区",
            "metric": "销售额",
            "operation": "sum",
            "groups": [
                {"group": "华南", "value": 1200, "validCount": 2},
                {"group": "华东", "value": 380, "validCount": 3},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self.registry.execute(
                "generate_chart",
                {"sourceCallId": "group-1", "chartType": "bar"},
                context={
                    "call_id": "chart-1",
                    "artifact_dir": directory,
                    "previous_tool_results": [
                        prior_result(
                            call_id="group-1",
                            tool_name="group_compare",
                            data=source_data,
                        )
                    ],
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(
                result["data"]["spec"]["data"]["values"],
                [{"x": "华南", "y": 1200}, {"x": "华东", "y": 380}],
            )
            artifact = Path(result["data"]["artifact"]["path"])
            self.assertEqual(artifact.parent, Path(directory).resolve())
            self.assertIn("<rect", artifact.read_text(encoding="utf-8"))

    def test_trend_result_becomes_line_spec_and_svg(self) -> None:
        source_data = {
            "dateField": "日期",
            "metric": "销售额",
            "operation": "sum",
            "invalidDateCount": 0,
            "points": [
                {"date": "2026-01-01", "value": 300, "validCount": 2},
                {"date": "2026-01-02", "value": 1150, "validCount": 2},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self.registry.execute(
                "generate_chart",
                {
                    "sourceCallId": "trend-1",
                    "chartType": "line",
                    "title": "销售额 <趋势>",
                },
                context={
                    "call_id": "chart-2",
                    "artifact_dir": directory,
                    "previous_tool_results": [
                        prior_result(
                            call_id="trend-1",
                            tool_name="trend_analysis",
                            data=source_data,
                        )
                    ],
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(
                result["data"]["spec"]["data"]["values"],
                [
                    {"x": "2026-01-01", "y": 300},
                    {"x": "2026-01-02", "y": 1150},
                ],
            )
            svg = Path(result["data"]["artifact"]["path"]).read_text(encoding="utf-8")
            self.assertIn("<polyline", svg)
            self.assertIn("销售额 &lt;趋势&gt;", svg)
            self.assertNotIn("销售额 <趋势>", svg)

    def test_top_n_result_supports_bar_chart(self) -> None:
        spec = build_chart_spec(
            source_call_id="top-1",
            source_tool="top_n",
            source_data={
                "metric": "销售额",
                "count": 2,
                "items": [
                    {"rank": 1, "label": "A", "value": 9},
                    {"rank": 2, "label": "B", "value": 7},
                ],
            },
            chart_type="bar",
        )

        self.assertEqual(spec["data"]["values"], [{"x": "A", "y": 9}, {"x": "B", "y": 7}])
        self.assertEqual(spec["meta"]["sourceCallId"], "top-1")

    def test_model_cannot_supply_or_override_chart_values(self) -> None:
        result = self.registry.execute(
            "generate_chart",
            {
                "sourceCallId": "group-1",
                "chartType": "bar",
                "values": [{"x": "伪造", "y": 999999}],
            },
            context={},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_arguments")

    def test_rejects_incompatible_failed_truncated_and_missing_sources(self) -> None:
        cases = [
            (
                [
                    prior_result(
                        call_id="group-1",
                        tool_name="group_compare",
                        data={
                            "groupBy": "地区",
                            "metric": "销售额",
                            "operation": "sum",
                            "groups": [{"group": "华东", "value": 1}],
                        },
                    )
                ],
                "group-1",
                "line",
                "incompatible_chart_type",
            ),
            (
                [
                    prior_result(
                        call_id="failed-1",
                        tool_name="group_compare",
                        data=None,
                        ok=False,
                    )
                ],
                "failed-1",
                "bar",
                "chart_source_failed",
            ),
            (
                [
                    prior_result(
                        call_id="truncated-1",
                        tool_name="group_compare",
                        data={"preview": "..."},
                        truncated=True,
                    )
                ],
                "truncated-1",
                "bar",
                "chart_source_truncated",
            ),
            ([], "missing-1", "bar", "chart_source_not_found"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for previous, source_call_id, chart_type, expected_code in cases:
                with self.subTest(expected_code=expected_code):
                    result = self.registry.execute(
                        "generate_chart",
                        {"sourceCallId": source_call_id, "chartType": chart_type},
                        context={
                            "call_id": "chart-error",
                            "artifact_dir": directory,
                            "previous_tool_results": previous,
                        },
                    )
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["error"]["code"], expected_code)

    def test_rejects_unsupported_sources_and_excessive_point_counts(self) -> None:
        with self.assertRaises(ChartSpecError) as unsupported:
            build_chart_spec(
                source_call_id="stats-1",
                source_tool="basic_stats",
                source_data={
                    "metric": "销售额",
                    "operation": "sum",
                    "value": 1580,
                },
                chart_type="bar",
            )
        self.assertEqual(unsupported.exception.code, "unsupported_chart_source")

        with self.assertRaises(ChartSpecError) as excessive:
            build_chart_spec(
                source_call_id="trend-many",
                source_tool="trend_analysis",
                source_data={
                    "dateField": "日期",
                    "metric": "销售额",
                    "operation": "sum",
                    "points": [
                        {"date": f"day-{index}", "value": index}
                        for index in range(MAX_CHART_POINTS + 1)
                    ],
                },
                chart_type="line",
            )
        self.assertEqual(excessive.exception.code, "too_many_chart_points")

    def test_requires_controlled_artifact_directory(self) -> None:
        result = self.registry.execute(
            "generate_chart",
            {"sourceCallId": "group-1", "chartType": "bar"},
            context={
                "call_id": "chart-1",
                "previous_tool_results": [
                    prior_result(
                        call_id="group-1",
                        tool_name="group_compare",
                        data={
                            "groupBy": "地区",
                            "metric": "销售额",
                            "operation": "sum",
                            "groups": [{"group": "华东", "value": 1}],
                        },
                    )
                ],
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "chart_output_unavailable")
        self.assertTrue(result["error"]["recoverable"])

    def test_category_share_is_computed_by_tool_and_charts_as_ratios(self) -> None:
        grouped = prior_result(
            call_id="groups",
            tool_name="group_compare",
            data={"groupBy": "地区", "metric": "销售额", "operation": "sum", "groups": [
                {"group": "华东", "value": 25, "validCount": 1},
                {"group": "华南", "value": 75, "validCount": 1},
            ]},
        )
        shares = self.registry.execute(
            "normalize_share", {"sourceCallId": "groups"},
            context={"previous_tool_results": [grouped]},
        )
        self.assertTrue(shares["ok"])
        self.assertEqual([item["value"] for item in shares["data"]["groups"]], [0.25, 0.75])
        with tempfile.TemporaryDirectory() as directory:
            chart = self.registry.execute(
                "generate_chart", {"sourceCallId": "shares", "chartType": "bar"},
                context={"call_id": "share-chart", "artifact_dir": directory, "previous_tool_results": [
                    prior_result(call_id="shares", tool_name="normalize_share", data=shares["data"])
                ]},
            )
        self.assertTrue(chart["ok"])
        self.assertEqual(sum(item["y"] for item in chart["data"]["spec"]["data"]["values"]), 1)

    def test_share_rejects_zero_total(self) -> None:
        result = self.registry.execute(
            "normalize_share", {"sourceCallId": "groups"},
            context={"previous_tool_results": [prior_result(
                call_id="groups", tool_name="group_compare",
                data={"groupBy": "地区", "metric": "销售额", "operation": "sum", "groups": [{"group": "华东", "value": 0}]},
            )]},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "zero_share_total")

    def test_two_numeric_fields_generate_controlled_scatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "scatter.csv"
            dataset.write_text("销量,利润\n10,2\n20,5\n30,9\n", encoding="utf-8")
            points = self.registry.execute(
                "scatter_data", {"xField": "销量", "yField": "利润"}, context={"dataset": str(dataset)}
            )
            self.assertTrue(points["ok"])
            chart = self.registry.execute(
                "generate_chart", {"sourceCallId": "points", "chartType": "scatter"},
                context={"call_id": "scatter", "artifact_dir": directory, "previous_tool_results": [
                    prior_result(call_id="points", tool_name="scatter_data", data=points["data"])
                ]},
            )
            self.assertTrue(chart["ok"])
            self.assertEqual(chart["data"]["spec"]["data"]["values"], [{"x": 10, "y": 2}, {"x": 20, "y": 5}, {"x": 30, "y": 9}])
            self.assertIn("<circle", Path(chart["data"]["artifact"]["path"]).read_text(encoding="utf-8"))

    def test_chart_and_share_reject_inactive_dataset_sources(self) -> None:
        source = prior_result(
            call_id="old-groups",
            tool_name="group_compare",
            arguments={"datasetId": "ds_aaaaaaaaaaaa", "groupBy": "地区", "metric": "销售额", "operation": "sum"},
            data={"groupBy": "地区", "metric": "销售额", "operation": "sum", "groups": [{"group": "华东", "value": 10}]},
        )
        share = self.registry.execute(
            "normalize_share", {"sourceCallId": "old-groups"},
            context={"active_dataset_ids": ["ds_bbbbbbbbbbbb"], "previous_tool_results": [source]},
        )
        self.assertFalse(share["ok"])
        self.assertEqual(share["error"]["code"], "inactive_tool_source")
        with tempfile.TemporaryDirectory() as directory:
            chart = self.registry.execute(
                "generate_chart", {"sourceCallId": "old-groups", "chartType": "bar"},
                context={"active_dataset_ids": ["ds_bbbbbbbbbbbb"], "artifact_dir": directory, "previous_tool_results": [source]},
            )
        self.assertFalse(chart["ok"])
        self.assertEqual(chart["error"]["code"], "inactive_tool_source")

    def test_chart_validates_active_derived_source_lineage(self) -> None:
        grouped = prior_result(
            call_id="groups",
            tool_name="group_compare",
            arguments={"datasetId": "ds_aaaaaaaaaaaa", "groupBy": "地区", "metric": "销售额", "operation": "sum"},
            data={"groupBy": "地区", "metric": "销售额", "operation": "sum", "groups": [{"group": "华东", "value": 10}]},
        )
        shares = prior_result(
            call_id="shares",
            tool_name="normalize_share",
            arguments={"sourceCallId": "groups"},
            data={"groupBy": "地区", "metric": "销售额占比", "operation": "share", "groups": [{"group": "华东", "value": 1.0}]},
        )
        with tempfile.TemporaryDirectory() as directory:
            allowed = self.registry.execute(
                "generate_chart", {"sourceCallId": "shares", "chartType": "bar"},
                context={"active_dataset_ids": ["ds_aaaaaaaaaaaa"], "artifact_dir": directory, "previous_tool_results": [grouped, shares]},
            )
            missing = self.registry.execute(
                "generate_chart", {"sourceCallId": "shares", "chartType": "bar"},
                context={"active_dataset_ids": ["ds_aaaaaaaaaaaa"], "artifact_dir": directory, "previous_tool_results": [shares]},
            )
        self.assertTrue(allowed["ok"])
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "tool_source_lineage_unavailable")

    def test_duplicate_call_id_uses_latest_tool_result(self) -> None:
        old = prior_result(
            call_id="same", tool_name="group_compare",
            data={"groupBy": "地区", "metric": "销售额", "operation": "sum", "groups": [{"group": "旧", "value": 999}]},
        )
        current = prior_result(
            call_id="same", tool_name="group_compare",
            data={"groupBy": "地区", "metric": "销售额", "operation": "sum", "groups": [{"group": "新", "value": 10}]},
        )
        with tempfile.TemporaryDirectory() as directory:
            chart = self.registry.execute(
                "generate_chart", {"sourceCallId": "same", "chartType": "bar"},
                context={"artifact_dir": directory, "previous_tool_results": [old, current]},
            )
        self.assertTrue(chart["ok"])
        self.assertEqual(chart["data"]["spec"]["data"]["values"], [{"x": "新", "y": 10}])

    def test_scatter_omits_incomplete_pairs_and_rejects_more_than_point_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial = root / "partial.csv"
            partial.write_text("销量,利润\n10,2\n20,\n30,9\n", encoding="utf-8")
            points = self.registry.execute(
                "scatter_data", {"xField": "销量", "yField": "利润"}, context={"dataset": str(partial)}
            )
            self.assertTrue(points["ok"])
            self.assertEqual(points["data"]["omittedPairCount"], 1)
            self.assertEqual(points["data"]["pointCount"], 2)

            excessive = root / "excessive.csv"
            excessive.write_text(
                "销量,利润\n" + "\n".join(f"{index},{index * 2}" for index in range(MAX_CHART_POINTS + 1)) + "\n",
                encoding="utf-8",
            )
            many = self.registry.execute(
                "scatter_data", {"xField": "销量", "yField": "利润"}, context={"dataset": str(excessive)}
            )
            chart = self.registry.execute(
                "generate_chart", {"sourceCallId": "many", "chartType": "scatter"},
                context={"artifact_dir": directory, "previous_tool_results": [prior_result(call_id="many", tool_name="scatter_data", data=many["data"])]},
            )
        self.assertFalse(chart["ok"])
        self.assertEqual(chart["error"]["code"], "too_many_chart_points")


if __name__ == "__main__":
    unittest.main()
