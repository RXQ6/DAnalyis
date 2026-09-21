"""Deterministic process evaluators used by EvalRunner."""

from .contract import ContractEvaluator
from .route import RouteEvaluator
from .tool import ToolEvaluator
from .trace import TraceEvaluator


def default_evaluators() -> dict[str, object]:
    return {
        "route": RouteEvaluator(),
        "tool": ToolEvaluator(),
        "trace": TraceEvaluator(),
        "contract": ContractEvaluator(),
    }


__all__ = [
    "ContractEvaluator",
    "RouteEvaluator",
    "ToolEvaluator",
    "TraceEvaluator",
    "default_evaluators",
]
