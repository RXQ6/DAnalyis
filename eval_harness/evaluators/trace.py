"""Trace availability and loop-behaviour evaluation."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Mapping

from ..models import EvalCase, ProcessEvaluation
from ..taxonomy import FailureType


def _call_signature(call: Mapping[str, Any]) -> str:
    arguments = call.get("args", call.get("arguments", {}))
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    except TypeError:
        encoded = repr(arguments)
    return f"{call.get('tool', call.get('name'))}:{encoded}"


class TraceEvaluator:
    name = "trace"

    def evaluate(
        self, case: EvalCase, observation: Mapping[str, Any]
    ) -> ProcessEvaluation:
        del case
        trace = observation.get("trace") or {}
        if not trace.get("available"):
            return ProcessEvaluation(
                self.name,
                False,
                True,
                values={
                    "trace_available": False,
                    "tool_calls": None,
                    "loop_iterations": None,
                    "retry_count": None,
                },
            )
        calls = [call for call in trace.get("tool_calls", []) if isinstance(call, Mapping)]
        signatures = [_call_signature(call) for call in calls]
        duplicate_count = sum(count - 1 for count in Counter(signatures).values() if count > 1)
        explicit_retries = sum(1 for call in calls if call.get("retry") is True)
        retry_count = max(duplicate_count, explicit_retries)
        iterations = trace.get("loop_iterations")
        max_iter = trace.get("max_iter")
        stop_reason = trace.get("stop_reason")
        abnormal = (
            isinstance(iterations, int)
            and isinstance(max_iter, int)
            and iterations > max_iter
        ) or stop_reason == "max_iter"
        repeated = retry_count > int(trace.get("allowed_retries", 0))
        values = {
            "trace_available": True,
            "tool_calls": len(calls),
            "loop_iterations": iterations if isinstance(iterations, int) else None,
            "retry_count": retry_count,
            "max_iter": max_iter,
            "stop_reason": stop_reason,
        }
        if abnormal or repeated:
            reasons = []
            if abnormal:
                reasons.append("abnormal loop or max_iter termination")
            if repeated:
                reasons.append(f"unexpected repeated calls: {retry_count}")
            return ProcessEvaluation(
                self.name,
                True,
                False,
                str(FailureType.TRACE_ERROR),
                "; ".join(reasons),
                values,
            )
        return ProcessEvaluation(self.name, True, True, values=values)
