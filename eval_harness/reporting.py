"""Unified JSON and Markdown reporting for Day19.3."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .baseline import EvalBaseline, compare_to_baseline
from .metrics import EvalMetrics


DEFAULT_RISKS = [
    "P1 legacy cases do not expose complete traces; process metrics remain unavailable for those cases.",
    "Workflow routes are covered by evaluator tests but are not yet a formal suite in the unified run.",
    "Token usage is unavailable until the underlying model clients expose it.",
    "Latency is environment-sensitive; the gate uses a versioned baseline plus explicit tolerance while retaining legacy hard limits.",
]


class UnifiedReportBuilder:
    def build(
        self,
        harness_report: Mapping[str, Any],
        metrics: EvalMetrics,
        baseline: EvalBaseline,
        gate_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "report": "day19.3-unified-evaluation",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall_status": "PASS"
            if harness_report.get("passed") and gate_report.get("passed")
            else "FAIL",
            "summary": {
                "passed_cases": harness_report.get("passed_cases"),
                "total_cases": harness_report.get("total_cases"),
                "harness_passed": bool(harness_report.get("passed")),
                "regression_gate_passed": bool(gate_report.get("passed")),
            },
            "metrics": metrics.to_dict(),
            "process_metrics": dict(harness_report.get("process_metrics", {})),
            "baseline": {
                "baseline_id": baseline.baseline_id,
                "metadata": dict(baseline.metadata),
                "delta": compare_to_baseline(metrics, baseline),
            },
            "regression_gate": dict(gate_report),
            "risks": list(DEFAULT_RISKS),
        }

    @staticmethod
    def write_json(report: Mapping[str, Any], destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_markdown(self, report: Mapping[str, Any], destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.to_markdown(report), encoding="utf-8")

    def to_markdown(self, report: Mapping[str, Any]) -> str:
        summary = report["summary"]
        metrics = report["metrics"]
        lines = [
            "# Day19.3 Unified Evaluation Report",
            "",
            f"- Overall: **{report['overall_status']}**",
            f"- Cases: {summary['passed_cases']}/{summary['total_cases']}",
            f"- Harness: {'PASS' if summary['harness_passed'] else 'FAIL'}",
            f"- Regression gate: {'PASS' if summary['regression_gate_passed'] else 'FAIL'}",
            f"- Baseline: `{report['baseline']['baseline_id']}`",
            "",
            "## Category Pass Rates",
            "",
            "| Category | Rate | Coverage |",
            "| --- | ---: | ---: |",
        ]
        for name, metric in metrics["category_pass_rates"].items():
            value = self._format_metric(metric, percent=True)
            lines.append(f"| {name} | {value} | {metric['sample_count']}/{metric['total_count']} |")
        lines.extend(["", "## Core Metrics", "", "| Metric | Value | Coverage |", "| --- | ---: | ---: |"])
        for name, metric in metrics["values"].items():
            value = self._format_metric(metric, percent=name.endswith("rate") or name in {"accuracy", "bad_case_recognition"})
            lines.append(f"| {name} | {value} | {metric['sample_count']}/{metric['total_count']} |")
        process = report["process_metrics"]
        lines.extend([
            "",
            "## Route / Tool / Trace / Contract",
            "",
            f"- Route evaluated/correct: {process.get('route_evaluated', 0)}/{process.get('route_correct', 0)}",
            f"- Tool evaluated/correct: {process.get('tool_evaluated', 0)}/{process.get('tool_correct', 0)}",
            f"- Contract evaluated/valid: {process.get('contract_evaluated', 0)}/{process.get('contract_valid', 0)}",
            f"- Trace available/unavailable: {process.get('trace_available', 0)}/{process.get('trace_unavailable', 0)}",
            "",
            "## Baseline Delta",
            "",
            "| Metric | Current | Baseline | Delta |",
            "| --- | ---: | ---: | ---: |",
        ])
        for name, comparison in report["baseline"]["delta"].items():
            if comparison["available"]:
                lines.append(f"| {name} | {comparison['current']:.6f} | {comparison['baseline']:.6f} | {comparison['delta']:+.6f} |")
            else:
                lines.append(f"| {name} | unavailable | {comparison['baseline']} | unavailable |")
        lines.extend(["", "## Failure Taxonomy", ""])
        distribution = metrics["failure_taxonomy"]
        if distribution:
            lines.extend(f"- {name}: {count}" for name, count in sorted(distribution.items()))
        else:
            lines.append("- No failures")
        lines.extend(["", "## Regression Gate", "", "| Gate | Status | Reason |", "| --- | --- | --- |"])
        for gate in report["regression_gate"]["results"]:
            reason = str(gate["reason"]).replace("|", "\\|")
            lines.append(f"| {gate['name']} | {gate['status']} | {reason} |")
        lines.extend(["", "## Current Risks", ""])
        lines.extend(f"- {risk}" for risk in report["risks"])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _format_metric(metric: Mapping[str, Any], *, percent: bool = False) -> str:
        if not metric["available"]:
            return f"unavailable ({metric['reason']})"
        value = metric["value"]
        if isinstance(value, Mapping):
            return ", ".join(f"{key}={item}" for key, item in value.items())
        if percent and isinstance(value, (int, float)):
            return f"{value:.1%}"
        if isinstance(value, float):
            return f"{value:.6f}"
        return str(value)
