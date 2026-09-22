"""Deterministic process evaluators used by EvalRunner."""

from .contract import ContractEvaluator
from .guardrail import GuardrailEvaluator
from .hitl import HITLEvaluator
from .observability import ObservabilityEvaluator
from .session import SessionEvaluator
from .route import RouteEvaluator
from .tool import ToolEvaluator
from .trace import TraceEvaluator


def default_evaluators() -> dict[str, object]:
    return {
        "route": RouteEvaluator(),
        "tool": ToolEvaluator(),
        "trace": TraceEvaluator(),
        "contract": ContractEvaluator(),
        "observability": ObservabilityEvaluator(),
        "guardrail": GuardrailEvaluator(),
        "hitl": HITLEvaluator(),
        "session": SessionEvaluator(),
    }


__all__ = [
    "ContractEvaluator",
    "GuardrailEvaluator",
    "HITLEvaluator",
    "ObservabilityEvaluator",
    "SessionEvaluator",
    "RouteEvaluator",
    "ToolEvaluator",
    "TraceEvaluator",
    "default_evaluators",
]
