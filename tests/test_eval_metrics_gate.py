from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval_harness import (
    EvalBaseline,
    MetricsCollector,
    RegressionGate,
    UnifiedReportBuilder,
)
from eval_harness.baseline import compare_to_baseline


def result(
    case_id: str,
    suite: str,
    category: str,
    *,
    passed: bool = True,
    latency: float = 0.1,
    tool_calls: int | None = 2,
    loops: int | None = 1,
    retries: int | None = 0,
    failure_type: str | None = None,
    contract_valid: bool | None = True,
    cost: float | None = 0.0,
) -> dict:
    metadata = {} if cost is None else {"cost_cny": cost}
    return {
        "case_id": case_id,
        "suite": suite,
        "category": category,
        "passed": passed,
        "latency": latency,
        "route_correct": None,
        "tool_correct": True if tool_calls is not None else None,
        "contract_valid": contract_valid,
        "trace_available": tool_calls is not None,
        "tool_calls": tool_calls,
        "loop_iterations": loops,
        "retry_count": retries,
        "failure_type": failure_type,
        "metadata": metadata,
    }


def harness_report(results: list[dict] | None = None) -> dict:
    items = results or [
        result("P0-01", "p0", "p0", latency=0.1),
        result("P1-01", "p1", "chart", latency=0.2, tool_calls=None, loops=None, retries=None, contract_valid=None),
        result("BAD-01", "robustness", "bad", latency=0.3),
    ]
    suites = {}
    for name in ("p0", "p1", "robustness"):
        suite_items = [item for item in items if item["suite"] == name]
        suites[name] = {
            "passed": all(item["passed"] for item in suite_items),
            "passed_cases": sum(item["passed"] for item in suite_items),
            "total_cases": len(suite_items),
            "gates": {"legacy": all(item["passed"] for item in suite_items)},
        }
    return {
        "passed": all(item["passed"] for item in items),
        "passed_cases": sum(item["passed"] for item in items),
        "total_cases": len(items),
        "results": items,
        "suites": suites,
        "process_metrics": {
            "route_evaluated": 0,
            "route_correct": 0,
            "tool_evaluated": 2,
            "tool_correct": 2,
            "contract_evaluated": 2,
            "contract_valid": 2,
            "trace_available": 2,
            "trace_unavailable": 1,
        },
    }


def baseline() -> EvalBaseline:
    return EvalBaseline(
        "test-baseline",
        {
            "p0_pass_rate": 1.0,
            "p1_pass_rate": 1.0,
            "robustness_rate": 1.0,
            "avg_latency": 0.2,
            "p95_latency": 0.3,
            "max_latency": 0.3,
            "average_cost": 0.0,
            "maximum_cost": 0.0,
        },
        {"latency": {"relative": 0.5, "absolute": 0.2}, "cost": {"absolute": 0.5}},
        {"schema_version": 1},
    )


class MetricsCollectorTest(unittest.TestCase):
    def test_collects_required_metrics_and_nearest_rank_p95(self) -> None:
        metrics = MetricsCollector().collect(harness_report())
        self.assertEqual(metrics.get("pass_rate").value, 1.0)
        self.assertEqual(metrics.get("bad_case_recognition").value, 1.0)
        self.assertAlmostEqual(metrics.get("avg_latency").value, 0.2)
        self.assertEqual(metrics.get("p95_latency").value, 0.3)
        self.assertEqual(metrics.get("avg_tool_calls").sample_count, 2)
        self.assertEqual(metrics.get("retry_count").value, 0)

    def test_missing_process_metrics_are_unavailable_not_zero(self) -> None:
        items = [result("P1-01", "p1", "chart", tool_calls=None, loops=None, retries=None, contract_valid=None)]
        report = harness_report(items)
        metrics = MetricsCollector().collect(report)
        self.assertFalse(metrics.get("avg_tool_calls").available)
        self.assertIsNone(metrics.get("avg_tool_calls").value)
        self.assertFalse(metrics.get("contract_failure_count").available)

    def test_token_is_explicitly_unavailable(self) -> None:
        metric = MetricsCollector().collect(harness_report()).get("token")
        self.assertFalse(metric.available)
        self.assertIsNone(metric.value)
        self.assertEqual(metric.reason, "token usage not exposed")

    def test_cost_is_available_when_zero_is_observed(self) -> None:
        metric = MetricsCollector().collect(harness_report()).get("cost")
        self.assertTrue(metric.available)
        self.assertEqual(metric.value["total"], 0.0)


class BaselineAndGateTest(unittest.TestCase):
    def test_baseline_delta_is_reported(self) -> None:
        metrics = MetricsCollector().collect(harness_report())
        delta = compare_to_baseline(metrics, baseline())
        self.assertTrue(delta["avg_latency"]["available"])
        self.assertAlmostEqual(delta["avg_latency"]["delta"], 0.0)

    def test_stable_run_passes_all_gates(self) -> None:
        report = harness_report()
        gate = RegressionGate().evaluate(MetricsCollector().collect(report), baseline(), report)
        self.assertTrue(gate["passed"])
        self.assertTrue(all(item["status"] == "PASS" for item in gate["results"]))

    def test_p1_regression_fails(self) -> None:
        report = harness_report([
            result("P0-01", "p0", "p0"),
            result("P1-01", "p1", "chart", passed=False),
            result("BAD-01", "robustness", "bad"),
        ])
        gate = RegressionGate().evaluate(MetricsCollector().collect(report), baseline(), report)
        failed = {item["name"] for item in gate["results"] if item["status"] == "FAIL"}
        self.assertIn("p1_not_below_baseline", failed)

    def test_security_and_contract_failures_block_gate(self) -> None:
        report = harness_report([
            result("P0-01", "p0", "p0"),
            result("P1-01", "p1", "chart"),
            result("BAD-01", "robustness", "bad", failure_type="SECURITY_VIOLATION", contract_valid=False),
        ])
        gate = RegressionGate().evaluate(MetricsCollector().collect(report), baseline(), report)
        failed = {item["name"] for item in gate["results"] if item["status"] == "FAIL"}
        self.assertIn("security_violation_zero", failed)
        self.assertIn("contract_failure_zero", failed)

    def test_latency_over_tolerance_fails(self) -> None:
        report = harness_report([
            result("P0-01", "p0", "p0", latency=2.0),
            result("P1-01", "p1", "chart", latency=2.0),
            result("BAD-01", "robustness", "bad", latency=2.0),
        ])
        gate = RegressionGate().evaluate(MetricsCollector().collect(report), baseline(), report)
        failed = {item["name"] for item in gate["results"] if item["status"] == "FAIL"}
        self.assertIn("avg_latency", failed)

    def test_missing_required_cost_fails_instead_of_using_zero(self) -> None:
        items = [
            result("P0-01", "p0", "p0", cost=None),
            result("P1-01", "p1", "chart", cost=None),
            result("BAD-01", "robustness", "bad", cost=None),
        ]
        report = harness_report(items)
        gate = RegressionGate().evaluate(MetricsCollector().collect(report), baseline(), report)
        failed = {item["name"] for item in gate["results"] if item["status"] == "FAIL"}
        self.assertIn("average_cost", failed)
        self.assertIn("maximum_cost", failed)


class UnifiedReportTest(unittest.TestCase):
    def test_writes_json_and_markdown_sections(self) -> None:
        raw = harness_report()
        metrics = MetricsCollector().collect(raw)
        gate = RegressionGate().evaluate(metrics, baseline(), raw)
        builder = UnifiedReportBuilder()
        report = builder.build(raw, metrics, baseline(), gate)
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "report.json"
            markdown_path = Path(directory) / "report.md"
            builder.write_json(report, json_path)
            builder.write_markdown(report, markdown_path)
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
        self.assertEqual(loaded["overall_status"], "PASS")
        self.assertIn("## Baseline Delta", markdown)
        self.assertIn("## Regression Gate", markdown)
        self.assertIn("## Current Risks", markdown)


if __name__ == "__main__":
    unittest.main()
