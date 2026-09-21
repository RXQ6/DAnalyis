"""Day19.3 deterministic regression gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .baseline import EvalBaseline, current_core_metrics
from .metrics import EvalMetrics


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str
    reason: str
    actual: Any = None
    baseline: Any = None
    limit: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "actual": self.actual,
            "baseline": self.baseline,
            "limit": self.limit,
        }


class RegressionGate:
    def evaluate(
        self,
        metrics: EvalMetrics,
        baseline: EvalBaseline,
        harness_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        core = current_core_metrics(metrics)
        results: list[GateResult] = []

        def required_min(name: str, actual: float | None, required: float) -> None:
            if actual is None:
                results.append(GateResult(name, "FAIL", "required metric unavailable", None, required, required))
            elif actual < required:
                results.append(GateResult(name, "FAIL", f"{actual:.6f} is below {required:.6f}", actual, required, required))
            else:
                results.append(GateResult(name, "PASS", f"{actual:.6f} meets minimum {required:.6f}", actual, required, required))

        required_min("p0_100_percent", core["p0_pass_rate"], 1.0)
        required_min("p1_not_below_baseline", core["p1_pass_rate"], float(baseline.metrics["p1_pass_rate"]))
        required_min("robustness_not_below_baseline", core["robustness_rate"], float(baseline.metrics["robustness_rate"]))

        self._zero_gate(results, "security_violation_zero", metrics.get("security_violation_count"))
        self._zero_gate(results, "contract_failure_zero", metrics.get("contract_failure_count"))

        latency_tolerance = baseline.tolerances.get("latency", {})
        for metric_name in ("avg_latency", "p95_latency", "max_latency"):
            self._tolerance_gate(
                results,
                metric_name,
                core.get(metric_name),
                float(baseline.metrics[metric_name]),
                latency_tolerance,
            )
        cost_tolerance = baseline.tolerances.get("cost", {})
        for metric_name in ("average_cost", "maximum_cost"):
            self._tolerance_gate(
                results,
                metric_name,
                core.get(metric_name),
                float(baseline.metrics[metric_name]),
                cost_tolerance,
            )

        legacy_failures = [
            f"{suite_name}:{gate_name}"
            for suite_name, suite in harness_report.get("suites", {}).items()
            for gate_name, passed in suite.get("gates", {}).items()
            if not passed
        ]
        if legacy_failures:
            results.append(GateResult("existing_thresholds", "FAIL", f"existing gates failed: {legacy_failures}"))
        else:
            results.append(GateResult("existing_thresholds", "PASS", "all existing P0/P1/Robustness gates passed"))
        return {
            "passed": all(result.status == "PASS" for result in results),
            "results": [result.to_dict() for result in results],
        }

    @staticmethod
    def _zero_gate(results: list[GateResult], name: str, metric: Any) -> None:
        if not metric.available:
            results.append(GateResult(name, "FAIL", f"required metric unavailable: {metric.reason}"))
        elif metric.value != 0:
            results.append(GateResult(name, "FAIL", f"expected 0, got {metric.value}", metric.value, 0, 0))
        else:
            results.append(GateResult(name, "PASS", "value is 0", metric.value, 0, 0))

    @staticmethod
    def _tolerance_gate(
        results: list[GateResult],
        name: str,
        actual: float | None,
        baseline: float,
        tolerance: Mapping[str, float],
    ) -> None:
        relative = float(tolerance.get("relative", 0))
        absolute = float(tolerance.get("absolute", 0))
        limit = max(baseline * (1 + relative), baseline + absolute)
        if actual is None:
            results.append(GateResult(name, "FAIL", "required metric unavailable", None, baseline, limit))
        elif actual > limit:
            results.append(GateResult(name, "FAIL", f"{actual:.6f} exceeds tolerance limit {limit:.6f}", actual, baseline, limit))
        else:
            results.append(GateResult(name, "PASS", f"{actual:.6f} is within tolerance limit {limit:.6f}", actual, baseline, limit))
