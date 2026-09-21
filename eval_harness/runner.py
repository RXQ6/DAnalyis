"""Deterministic runner for normalized evaluation suites."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from .evaluators import default_evaluators
from .models import EvalCase, EvalResult, EvalSuite
from .taxonomy import FailureType, classify_legacy_failure, primary_failure


class EvalRunner:
    """Execute EvalCases, normalize failures, and apply suite-specific gates."""

    def __init__(self, evaluators: Mapping[str, Any] | None = None) -> None:
        self.evaluators = dict(evaluators or default_evaluators())

    def run_case(self, case: EvalCase) -> EvalResult:
        started = time.perf_counter()
        try:
            observation = dict(case.executor())
            measured_latency = time.perf_counter() - started
            failures = observation.get("failures") or []
            if isinstance(failures, str):
                failures = [failures]
            legacy_passed = bool(observation.get("passed", not failures))
            process_results = []
            for evaluator_name in case.evaluators:
                if evaluator_name not in self.evaluators:
                    raise ValueError(f"unknown evaluator: {evaluator_name}")
                process_results.append(
                    self.evaluators[evaluator_name].evaluate(case, observation)
                )
            process_failures = [
                result.failure_reason
                for result in process_results
                if not result.passed and result.failure_reason
            ]
            passed = legacy_passed and all(result.passed for result in process_results)
            failure_reason = observation.get("failure_reason")
            if failure_reason is None and failures:
                failure_reason = "; ".join(str(item) for item in failures)
            if process_failures:
                process_reason = "; ".join(process_failures)
                failure_reason = (
                    f"{failure_reason}; {process_reason}" if failure_reason else process_reason
                )
            latency = observation.get("latency", measured_latency)
            metadata = dict(observation.get("metadata") or {})
            metadata.setdefault("failures", list(failures))
            values: dict[str, Any] = {}
            for result in process_results:
                values.update(result.values)
            trace_summary = dict(observation.get("trace_summary") or {})
            trace_available = bool(values.get("trace_available", trace_summary.get("available", False)))
            failure_type = primary_failure(
                [result.failure_type for result in process_results]
                + [classify_legacy_failure(failures) if not legacy_passed else None]
            )
            return EvalResult(
                case_id=case.case_id,
                category=case.category,
                passed=passed,
                failure_reason=None if passed else str(failure_reason or "evaluation_failed"),
                latency=round(float(latency), 6),
                answer=observation.get("answer"),
                trace_summary=trace_summary,
                route_correct=values.get("route_correct"),
                tool_correct=values.get("tool_correct"),
                contract_valid=values.get("contract_valid"),
                trace_available=trace_available,
                tool_calls=values.get("tool_calls"),
                loop_iterations=values.get("loop_iterations"),
                retry_count=values.get("retry_count"),
                failure_type=failure_type,
                process_evaluations=tuple(result.to_dict() for result in process_results),
                suite=case.suite,
                metadata=metadata,
            )
        except Exception as error:  # A broken case must not abort the remaining suite.
            return EvalResult(
                case_id=case.case_id,
                category=case.category,
                passed=False,
                failure_reason=f"harness_or_process_error:{type(error).__name__}:{error}",
                latency=round(time.perf_counter() - started, 6),
                answer=None,
                trace_summary={"available": False, "reason": "executor_error"},
                route_correct=None,
                tool_correct=None,
                contract_valid=None,
                trace_available=False,
                tool_calls=None,
                loop_iterations=None,
                retry_count=None,
                failure_type=str(FailureType.HARNESS_ERROR),
                suite=case.suite,
                metadata={"failures": [f"{type(error).__name__}:{error}"]},
            )

    def run_cases(self, cases: Iterable[EvalCase]) -> list[EvalResult]:
        return [self.run_case(case) for case in cases]

    def run(self, suites: Iterable[EvalSuite]) -> dict[str, Any]:
        results: list[EvalResult] = []
        suite_reports: dict[str, Any] = {}
        for suite in suites:
            suite_results = self.run_cases(suite.cases)
            results.extend(suite_results)
            gate_report = dict(suite.gate(suite_results))
            suite_reports[suite.name] = {
                "passed": bool(gate_report.get("passed", False)),
                "passed_cases": sum(result.passed for result in suite_results),
                "total_cases": len(suite_results),
                "metrics": gate_report.get("metrics", {}),
                "gates": gate_report.get("gates", {}),
            }
        process_metrics = {
            "route_evaluated": sum(result.route_correct is not None for result in results),
            "route_correct": sum(result.route_correct is True for result in results),
            "tool_evaluated": sum(result.tool_correct is not None for result in results),
            "tool_correct": sum(result.tool_correct is True for result in results),
            "contract_evaluated": sum(result.contract_valid is not None for result in results),
            "contract_valid": sum(result.contract_valid is True for result in results),
            "trace_available": sum(result.trace_available for result in results),
            "trace_unavailable": sum(not result.trace_available for result in results),
            "failure_types": dict(
                Counter(result.failure_type for result in results if result.failure_type)
            ),
        }
        return {
            "schema_version": 1,
            "harness": "day19.2",
            "passed": all(report["passed"] for report in suite_reports.values()),
            "passed_cases": sum(result.passed for result in results),
            "total_cases": len(results),
            "process_metrics": process_metrics,
            "suites": suite_reports,
            "results": [result.to_dict() for result in results],
        }

    @staticmethod
    def write_report(report: Mapping[str, Any], destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
