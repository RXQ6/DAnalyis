"""Data contracts for the Day19 evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


EvalExecutor = Callable[[], Mapping[str, Any]]
EvalGate = Callable[[list["EvalResult"]], Mapping[str, Any]]


@dataclass(frozen=True)
class EvalCase:
    """One executable evaluation case.

    The executor remains outside the Agent implementation.  It returns a small
    normalized mapping and may reuse an existing legacy evaluation function.
    """

    case_id: str
    category: str
    description: str
    executor: EvalExecutor = field(repr=False, compare=False)
    suite: str = "default"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    expectations: Mapping[str, Any] = field(default_factory=dict)
    evaluators: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcessEvaluation:
    """One deterministic process evaluator result."""

    evaluator: str
    available: bool
    passed: bool
    failure_type: str | None = None
    failure_reason: str | None = None
    values: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluator": self.evaluator,
            "available": self.available,
            "passed": self.passed,
            "failure_type": self.failure_type,
            "failure_reason": self.failure_reason,
            "values": dict(self.values),
        }


@dataclass(frozen=True)
class EvalResult:
    """Normalized result emitted for every EvalCase."""

    case_id: str
    category: str
    passed: bool
    failure_reason: str | None
    latency: float
    answer: Any
    trace_summary: Mapping[str, Any]
    route_correct: bool | None
    tool_correct: bool | None
    contract_valid: bool | None
    trace_available: bool
    tool_calls: int | None
    loop_iterations: int | None
    retry_count: int | None
    failure_type: str | None
    process_evaluations: tuple[Mapping[str, Any], ...] = ()
    suite: str = "default"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "passed": self.passed,
            "failure_reason": self.failure_reason,
            "latency": self.latency,
            "answer": self.answer,
            "trace_summary": dict(self.trace_summary),
            "route_correct": self.route_correct,
            "tool_correct": self.tool_correct,
            "contract_valid": self.contract_valid,
            "trace_available": self.trace_available,
            "tool_calls": self.tool_calls,
            "loop_iterations": self.loop_iterations,
            "retry_count": self.retry_count,
            "failure_type": self.failure_type,
            "process_evaluations": [dict(item) for item in self.process_evaluations],
            "suite": self.suite,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvalSuite:
    """A group of cases and its unchanged regression gate."""

    name: str
    cases: tuple[EvalCase, ...]
    gate: EvalGate = field(repr=False, compare=False)
