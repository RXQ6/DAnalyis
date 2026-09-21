"""Adapters for the existing P0, P1, and Robustness evaluations.

The original files remain authoritative for case definitions and assertions.
This module only normalizes their results for EvalRunner.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import EvalCase, EvalResult, EvalSuite


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import eval_agent  # noqa: E402
import eval_p1  # noqa: E402
import robustness_eval  # noqa: E402


_P0_ALLOWED_TOOLS = [
    "validate_input",
    "load_table",
    "profile_table",
    "route_question",
    "statistics",
    "group_compare",
    "top_n",
    "trend",
    "anomaly",
]
_P0_EXPECTED_ANALYSIS = {
    "P0-01": "statistics",
    "P0-02": "statistics",
    "P0-03": "group_compare",
    "P0-04": "top_n",
    "P0-05": "trend",
    "P0-06": "anomaly",
    "BC-05": "trend",
}
_P0_EXPECTED_FAILURES = {
    "P0-07",
    "P0-08",
    "P0-09",
    "BC-01",
    "BC-02",
    "BC-03",
}


def _answer(output: dict[str, Any] | None) -> Any:
    if not output:
        return None
    for key in ("conclusion", "message", "result", "error"):
        if key in output:
            return output[key]
    return output


def _trace_summary(output: dict[str, Any] | None) -> dict[str, Any]:
    audit = (output or {}).get("audit", {})
    calls = audit.get("toolCalls", [])
    return {
        "available": bool(audit),
        "rounds": audit.get("rounds"),
        "max_rounds": audit.get("maxRounds"),
        "tool_calls": [
            {
                "tool": call.get("tool"),
                "status": call.get("status"),
            }
            for call in calls
            if isinstance(call, dict)
        ],
    }


def _trace(output: dict[str, Any] | None) -> dict[str, Any]:
    audit = (output or {}).get("audit", {})
    calls = audit.get("toolCalls", [])
    return {
        "available": bool(audit),
        "tool_calls": [dict(call) for call in calls if isinstance(call, dict)],
        "loop_iterations": audit.get("rounds"),
        "max_iter": audit.get("maxRounds"),
        "stop_reason": audit.get("stopReason"),
        "allowed_retries": 0,
    }


def _p0_case(case: Any, node: str, fixture_directory: Path) -> EvalCase:
    def execute() -> dict[str, Any]:
        record = eval_agent.invoke(node, case, fixture_directory)
        output = record.get("output")
        return {
            "passed": record["passed"],
            "failures": record.get("failures", []),
            "latency": record["durationSeconds"],
            "answer": _answer(output),
            "trace_summary": _trace_summary(output),
            "trace": _trace(output),
            "contract_value": output,
            "metadata": {
                "cost_cny": float((output or {}).get("audit", {}).get("estimatedCostCny", 0)),
                "legacy_exit_code": record.get("exitCode"),
            },
        }

    expected_tool = _P0_EXPECTED_ANALYSIS.get(case.case_id)
    return EvalCase(
        case.case_id,
        case.category,
        case.description,
        execute,
        "p0",
        expectations={
            "tools": {
                "expected": [expected_tool] if expected_tool else [],
                "allowed": _P0_ALLOWED_TOOLS,
                "allow_execution_errors": case.case_id in _P0_EXPECTED_FAILURES,
                "forbid_repeats": True,
            },
            "contract": {
                "kind": "structured_output",
                "required": ["status", "audit"],
                "types": {"status": "string", "audit": "object"},
            },
        },
        evaluators=("tool", "trace", "contract"),
    )


def _p1_case(case: Any, directory: Path) -> EvalCase:
    def execute() -> dict[str, Any]:
        actual, failures = case.execute(directory)
        trace_fields = {
            key: actual[key]
            for key in ("toolChain", "stopReason", "iteration", "trace")
            if isinstance(actual, dict) and key in actual
        }
        return {
            "passed": not failures,
            "failures": failures,
            "answer": actual,
            "trace_summary": {
                "available": bool(trace_fields),
                "details": trace_fields,
                "source": "legacy_p1_actual",
                "observed_keys": sorted(actual) if isinstance(actual, dict) else [],
                "capability": case.capability,
            },
            "trace": {"available": False},
            "metadata": {
                "cost_cny": 0.0,
                "cost_basis": "deterministic scripted model; no external LLM call",
                "input_fixture": case.input_fixture,
                "capability": case.capability,
                "mapped_test": case.mapped_test,
                "expected": case.expected,
            },
        }

    return EvalCase(
        case.case_id,
        case.category,
        case.description,
        execute,
        "p1",
        evaluators=("trace",),
    )


def _robustness_case(case: Any, node: str, directory: Path) -> EvalCase:
    def execute() -> dict[str, Any]:
        record = robustness_eval.run_case(node, case, directory)
        output = record.get("output")
        return {
            "passed": record["passed"],
            "failures": record.get("failures", []),
            "latency": record["durationSeconds"],
            "answer": _answer(output),
            "trace_summary": _trace_summary(output),
            "trace": _trace(output),
            "contract_value": output,
            "metadata": {
                "cost_cny": float((output or {}).get("audit", {}).get("estimatedCostCny", 0)),
                "process_checks": record.get("processChecks", {}),
            },
        }

    return EvalCase(
        case.case_id,
        case.category,
        case.description,
        execute,
        "robustness",
        expectations={
            "tools": {
                "expected": [case.analysis] if case.analysis else [],
                "allowed": _P0_ALLOWED_TOOLS,
                "allow_execution_errors": case.status != "ok",
                "forbid_repeats": True,
            },
            "contract": {
                "kind": "structured_output",
                "required": ["status", "audit"],
                "types": {"status": "string", "audit": "object"},
            },
        },
        evaluators=("tool", "trace", "contract"),
    )


def _p0_gate(results: list[EvalResult]) -> dict[str, Any]:
    p0 = [result for result in results if result.category == "p0"]
    bad = [result for result in results if result.category == "bad"]
    durations = [result.latency for result in results]
    costs = [float(result.metadata.get("cost_cny", 0)) for result in results]
    metrics = {
        "p0PassRate": sum(result.passed for result in p0) / len(p0),
        "overallAccuracy": sum(result.passed for result in results) / len(results),
        "badCaseRecognitionRate": sum(result.passed for result in bad) / len(bad),
        "averageResponseSeconds": sum(durations) / len(durations),
        "maximumResponseSeconds": max(durations),
        "maximumCostCny": max(costs),
    }
    gates = {
        "p0PassRate>=100%": metrics["p0PassRate"] >= 1.0,
        "overallAccuracy>=85%": metrics["overallAccuracy"] >= 0.85,
        "badCaseRecognitionRate>=90%": metrics["badCaseRecognitionRate"] >= 0.90,
        "averageResponse<=30s": metrics["averageResponseSeconds"] <= 30,
        "maximumCost<=0.5CNY": metrics["maximumCostCny"] <= 0.5,
    }
    return {"passed": all(gates.values()), "metrics": metrics, "gates": gates}


def _p1_gate(results: list[EvalResult]) -> dict[str, Any]:
    metrics = {
        "passRate": sum(result.passed for result in results) / len(results),
        "averageResponseSeconds": sum(result.latency for result in results) / len(results),
        "maximumResponseSeconds": max(result.latency for result in results),
        "averageCostCny": 0.0,
        "maximumCostCny": 0.0,
    }
    gates = {"allCasesPassed": all(result.passed for result in results)}
    return {"passed": all(gates.values()), "metrics": metrics, "gates": gates}


def _robustness_gate(results: list[EvalResult]) -> dict[str, Any]:
    bad = [result for result in results if result.category == "bad"]
    holdout = [result for result in results if result.category == "holdout"]
    costs = [float(result.metadata.get("cost_cny", 0)) for result in results]
    checks = [
        bool(value)
        for result in results
        for value in (result.metadata.get("process_checks") or {}).values()
    ]
    metrics = {
        "badCaseRecognitionRate": sum(result.passed for result in bad) / len(bad),
        "holdoutAccuracy": sum(result.passed for result in holdout) / len(holdout),
        "overallAccuracy": sum(result.passed for result in results) / len(results),
        "averageResponseSeconds": sum(result.latency for result in results) / len(results),
        "maximumResponseSeconds": max(result.latency for result in results),
        "maximumCostCny": max(costs),
        "processCheckPassRate": sum(checks) / len(checks) if checks else 0.0,
    }
    gates = {
        "badCaseRecognitionRate>=90%": metrics["badCaseRecognitionRate"] >= 0.9,
        "holdoutAccuracy>=85%": metrics["holdoutAccuracy"] >= 0.85,
        "averageResponse<=30s": metrics["averageResponseSeconds"] <= 30,
        "maximumCost<=0.5CNY": metrics["maximumCostCny"] <= 0.5,
        "processChecks=100%": metrics["processCheckPassRate"] == 1,
    }
    return {"passed": all(gates.values()), "metrics": metrics, "gates": gates}


@contextmanager
def legacy_suites() -> Iterator[tuple[EvalSuite, ...]]:
    """Build all Day19.1 suites while keeping their temporary fixtures alive."""

    node = shutil.which("node")
    if not node:
        raise RuntimeError("node executable was not found")
    with tempfile.TemporaryDirectory(prefix="day19-p0-") as p0_temp, tempfile.TemporaryDirectory(
        prefix="day19-p1-"
    ) as p1_temp, tempfile.TemporaryDirectory(prefix="day19-robustness-") as robustness_temp:
        p0_directory = Path(p0_temp)
        for source in eval_agent.FIXTURES.glob("*.csv"):
            shutil.copyfile(source, p0_directory / source.name)
        eval_agent.create_average_xlsx(p0_directory / "average.xlsx")

        robustness_directory = Path(robustness_temp)
        robustness_eval.prepare(robustness_directory)

        yield (
            EvalSuite(
                "p0",
                tuple(_p0_case(case, node, p0_directory) for case in eval_agent.cases()),
                _p0_gate,
            ),
            EvalSuite(
                "p1",
                tuple(_p1_case(case, Path(p1_temp)) for case in eval_p1.cases()),
                _p1_gate,
            ),
            EvalSuite(
                "robustness",
                tuple(
                    _robustness_case(case, node, robustness_directory)
                    for case in robustness_eval.CASES
                ),
                _robustness_gate,
            ),
        )
