"""Deterministic Workflow route evaluation."""

from __future__ import annotations

from typing import Any, Mapping

from ..models import EvalCase, ProcessEvaluation
from ..taxonomy import FailureType


class RouteEvaluator:
    name = "route"
    allowed_routes = frozenset({"analysis", "chat", "calc", "memory", "memory_recall"})

    def evaluate(
        self, case: EvalCase, observation: Mapping[str, Any]
    ) -> ProcessEvaluation:
        expected = case.expectations.get("route")
        if expected is None:
            return ProcessEvaluation(self.name, False, True, values={"route_correct": None})
        actual = observation.get("route")
        valid = actual in self.allowed_routes
        correct = valid and actual == expected
        if correct:
            return ProcessEvaluation(
                self.name,
                True,
                True,
                values={"route_correct": True, "expected": expected, "actual": actual},
            )
        reason = (
            f"invalid route {actual!r}"
            if not valid
            else f"expected route {expected!r}, got {actual!r}"
        )
        return ProcessEvaluation(
            self.name,
            True,
            False,
            str(FailureType.ROUTING_ERROR),
            reason,
            {"route_correct": False, "expected": expected, "actual": actual},
        )
