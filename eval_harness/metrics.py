"""Unified deterministic metrics for Day19.3 reports."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import fmean
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class MetricValue:
    value: Any
    available: bool = True
    unit: str | None = None
    sample_count: int | None = None
    total_count: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "value": self.value if self.available else None,
            "unit": self.unit,
            "sample_count": self.sample_count,
            "total_count": self.total_count,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EvalMetrics:
    values: Mapping[str, MetricValue]
    category_pass_rates: Mapping[str, MetricValue] = field(default_factory=dict)
    failure_taxonomy: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": {name: value.to_dict() for name, value in self.values.items()},
            "category_pass_rates": {
                name: value.to_dict() for name, value in self.category_pass_rates.items()
            },
            "failure_taxonomy": dict(self.failure_taxonomy),
        }

    def get(self, name: str) -> MetricValue:
        return self.values[name]


def _rate(passed: int, total: int) -> MetricValue:
    if total == 0:
        return MetricValue(None, False, "ratio", 0, 0, "no matching cases")
    return MetricValue(passed / total, True, "ratio", total, total)


def _average(values: Iterable[float], total: int, unit: str) -> MetricValue:
    samples = list(values)
    if not samples:
        return MetricValue(None, False, unit, 0, total, "metric not exposed")
    return MetricValue(fmean(samples), True, unit, len(samples), total)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


class MetricsCollector:
    """Collect metrics without replacing unavailable observations with zero."""

    def collect(self, harness_report: Mapping[str, Any]) -> EvalMetrics:
        results = list(harness_report.get("results", []))
        total = len(results)
        passed = sum(bool(item.get("passed")) for item in results)
        latencies = [float(item["latency"]) for item in results if item.get("latency") is not None]
        tool_calls = [float(item["tool_calls"]) for item in results if item.get("tool_calls") is not None]
        iterations = [float(item["loop_iterations"]) for item in results if item.get("loop_iterations") is not None]
        retries = [int(item["retry_count"]) for item in results if item.get("retry_count") is not None]
        costs = [
            float(item.get("metadata", {}).get("cost_cny"))
            for item in results
            if item.get("metadata", {}).get("cost_cny") is not None
        ]
        tokens = [
            int(item.get("metadata", {}).get("token_count"))
            for item in results
            if item.get("metadata", {}).get("token_count") is not None
        ]
        suites = harness_report.get("suites", {})
        p0 = suites.get("p0", {})
        p1 = suites.get("p1", {})
        robustness = suites.get("robustness", {})
        bad_cases = [item for item in results if item.get("category") == "bad"]
        taxonomy: dict[str, int] = {}
        for item in results:
            failure_type = item.get("failure_type")
            if failure_type:
                taxonomy[failure_type] = taxonomy.get(failure_type, 0) + 1
        contract_evaluated = [item for item in results if item.get("contract_valid") is not None]
        values = {
            "pass_rate": _rate(passed, total),
            "accuracy": _rate(passed, total),
            "p0_pass_rate": _rate(int(p0.get("passed_cases", 0)), int(p0.get("total_cases", 0))),
            "p1_pass_rate": _rate(int(p1.get("passed_cases", 0)), int(p1.get("total_cases", 0))),
            "bad_case_recognition": _rate(sum(bool(item.get("passed")) for item in bad_cases), len(bad_cases)),
            "robustness_rate": _rate(int(robustness.get("passed_cases", 0)), int(robustness.get("total_cases", 0))),
            "avg_latency": _average(latencies, total, "seconds"),
            "p95_latency": MetricValue(
                _percentile(latencies, 0.95) if latencies else None,
                bool(latencies),
                "seconds",
                len(latencies),
                total,
                None if latencies else "latency not exposed",
            ),
            "max_latency": MetricValue(
                max(latencies) if latencies else None,
                bool(latencies),
                "seconds",
                len(latencies),
                total,
                None if latencies else "latency not exposed",
            ),
            "avg_tool_calls": _average(tool_calls, total, "calls"),
            "avg_loop_iterations": _average(iterations, total, "iterations"),
            "retry_count": MetricValue(sum(retries), bool(retries), "count", len(retries), total, None if retries else "trace retry count not exposed"),
            "timeout_count": MetricValue(taxonomy.get("TIMEOUT", 0), True, "count", total, total),
            "security_violation_count": MetricValue(taxonomy.get("SECURITY_VIOLATION", 0), True, "count", total, total),
            "contract_failure_count": MetricValue(
                sum(item.get("contract_valid") is False for item in contract_evaluated),
                bool(contract_evaluated),
                "count",
                len(contract_evaluated),
                total,
                None if contract_evaluated else "contract evaluator not run",
            ),
            "cost": MetricValue(
                {"total": sum(costs), "average": fmean(costs), "maximum": max(costs), "currency": "CNY"} if costs else None,
                bool(costs),
                "CNY",
                len(costs),
                total,
                None if costs else "cost not exposed",
            ),
            "token": MetricValue(
                {"total": sum(tokens), "average": fmean(tokens), "maximum": max(tokens)} if tokens else None,
                bool(tokens),
                "tokens",
                len(tokens),
                total,
                None if tokens else "token usage not exposed",
            ),
        }
        categories: dict[str, list[Mapping[str, Any]]] = {}
        for item in results:
            categories.setdefault(str(item.get("category", "unknown")), []).append(item)
        category_rates = {
            category: _rate(sum(bool(item.get("passed")) for item in items), len(items))
            for category, items in sorted(categories.items())
        }
        return EvalMetrics(values, category_rates, taxonomy)
