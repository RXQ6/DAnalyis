"""Deterministic validation for Day20 TraceEvent streams."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..models import EvalCase, ProcessEvaluation
from ..taxonomy import FailureType


_REQUIRED_FIELDS = frozenset(
    {
        "trace_id",
        "event_type",
        "component",
        "name",
        "status",
        "latency_ms",
        "error_code",
        "metadata",
    }
)


class ObservabilityEvaluator:
    name = "observability"

    def evaluate(
        self, case: EvalCase, observation: Mapping[str, Any]
    ) -> ProcessEvaluation:
        config = case.expectations.get("observability")
        if config is None:
            return ProcessEvaluation(self.name, False, True)
        events = observation.get("trace_events")
        failures: list[str] = []
        if not isinstance(events, list) or not events:
            failures.append("trace_events must be a non-empty list")
            events = []
        valid_events = [event for event in events if isinstance(event, Mapping)]
        if len(valid_events) != len(events):
            failures.append("every trace event must be an object")
        trace_ids = {event.get("trace_id") for event in valid_events}
        if len(trace_ids) != 1 or None in trace_ids:
            failures.append("trace events must share one trace_id")
        sequences = [event.get("sequence") for event in valid_events]
        if sequences and sequences != sorted(sequences):
            failures.append("trace event sequence must be monotonic")
        for index, event in enumerate(valid_events):
            missing = sorted(_REQUIRED_FIELDS.difference(event))
            if missing:
                failures.append(f"event {index} missing fields: {missing}")
        actual_types = {str(event.get("event_type")) for event in valid_events}
        expected_types = set(config.get("required_events", []))
        missing_types = sorted(expected_types - actual_types)
        if missing_types:
            failures.append(f"missing required events: {missing_types}")
        values = {
            "observability_available": bool(valid_events),
            "trace_event_count": len(valid_events),
            "event_types": sorted(actual_types),
        }
        if failures:
            return ProcessEvaluation(
                self.name,
                bool(valid_events),
                False,
                str(FailureType.TRACE_ERROR),
                "; ".join(failures),
                values,
            )
        return ProcessEvaluation(self.name, True, True, values=values)
