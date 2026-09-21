"""Deterministic tool selection, execution, and permission evaluation."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Mapping

from ..models import EvalCase, ProcessEvaluation
from ..taxonomy import FailureType


def _signature(call: Mapping[str, Any]) -> str:
    arguments = call.get("args", call.get("arguments", {}))
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    except TypeError:
        encoded = repr(arguments)
    return f"{call.get('tool', call.get('name'))}:{encoded}"


class ToolEvaluator:
    name = "tool"

    def evaluate(
        self, case: EvalCase, observation: Mapping[str, Any]
    ) -> ProcessEvaluation:
        config = case.expectations.get("tools")
        if config is None:
            return ProcessEvaluation(self.name, False, True, values={"tool_correct": None})
        trace = observation.get("trace") or {}
        if not trace.get("available"):
            return ProcessEvaluation(
                self.name,
                False,
                True,
                values={"tool_correct": None, "reason": "trace_unavailable"},
            )
        calls = [call for call in trace.get("tool_calls", []) if isinstance(call, Mapping)]
        names = [str(call.get("tool", call.get("name"))) for call in calls]
        expected = list(config.get("expected", []))
        allowed = config.get("allowed")
        unauthorized = [] if allowed is None else sorted(set(names) - set(allowed))
        if unauthorized:
            return ProcessEvaluation(
                self.name,
                True,
                False,
                str(FailureType.SECURITY_VIOLATION),
                f"unauthorized tools called: {unauthorized}",
                {"tool_correct": False, "actual": names, "unauthorized": unauthorized},
            )
        missing = [tool for tool in expected if tool not in names]
        signatures = [_signature(call) for call in calls]
        repeated = sorted(signature for signature, count in Counter(signatures).items() if count > 1)
        if missing or (repeated and config.get("forbid_repeats", True)):
            parts = []
            if missing:
                parts.append(f"missing expected tools: {missing}")
            if repeated:
                parts.append(f"repeated tool calls: {repeated}")
            return ProcessEvaluation(
                self.name,
                True,
                False,
                str(FailureType.TOOL_SELECTION_ERROR),
                "; ".join(parts),
                {
                    "tool_correct": False,
                    "expected": expected,
                    "actual": names,
                    "repeated": repeated,
                },
            )
        failed = [name for name, call in zip(names, calls) if call.get("status") == "error"]
        if failed and not config.get("allow_execution_errors", False):
            return ProcessEvaluation(
                self.name,
                True,
                False,
                str(FailureType.TOOL_EXECUTION_ERROR),
                f"tool execution failed: {failed}",
                {"tool_correct": False, "actual": names, "failed": failed},
            )
        return ProcessEvaluation(
            self.name,
            True,
            True,
            values={
                "tool_correct": True,
                "expected": expected,
                "actual": names,
                "repeated": [],
            },
        )
