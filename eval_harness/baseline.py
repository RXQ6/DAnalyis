"""Versioned baseline loading and delta calculation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .metrics import EvalMetrics


@dataclass(frozen=True)
class EvalBaseline:
    baseline_id: str
    metrics: Mapping[str, float]
    tolerances: Mapping[str, Mapping[str, float]]
    metadata: Mapping[str, Any]

    @classmethod
    def load(cls, path: Path) -> "EvalBaseline":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            str(payload["baseline_id"]),
            payload["metrics"],
            payload.get("tolerances", {}),
            {
                "schema_version": payload.get("schema_version"),
                "created_at": payload.get("created_at"),
                "source_report": payload.get("source_report"),
            },
        )


def current_core_metrics(metrics: EvalMetrics) -> dict[str, float | None]:
    cost = metrics.get("cost")
    cost_value = cost.value if cost.available and isinstance(cost.value, Mapping) else {}
    return {
        "p0_pass_rate": metrics.get("p0_pass_rate").value if metrics.get("p0_pass_rate").available else None,
        "p1_pass_rate": metrics.get("p1_pass_rate").value if metrics.get("p1_pass_rate").available else None,
        "robustness_rate": metrics.get("robustness_rate").value if metrics.get("robustness_rate").available else None,
        "avg_latency": metrics.get("avg_latency").value if metrics.get("avg_latency").available else None,
        "p95_latency": metrics.get("p95_latency").value if metrics.get("p95_latency").available else None,
        "max_latency": metrics.get("max_latency").value if metrics.get("max_latency").available else None,
        "average_cost": cost_value.get("average"),
        "maximum_cost": cost_value.get("maximum"),
    }


def compare_to_baseline(
    metrics: EvalMetrics, baseline: EvalBaseline
) -> dict[str, dict[str, Any]]:
    current = current_core_metrics(metrics)
    comparisons: dict[str, dict[str, Any]] = {}
    for name, baseline_value in baseline.metrics.items():
        current_value = current.get(name)
        available = current_value is not None
        comparisons[name] = {
            "available": available,
            "current": current_value,
            "baseline": baseline_value,
            "delta": current_value - baseline_value if available else None,
            "reason": None if available else "current metric unavailable",
        }
    return comparisons
