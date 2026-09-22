"""Thread-safe, fail-safe TraceEvent collection with bounded metadata."""

from __future__ import annotations

import copy
import math
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import TraceEvent


_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "csv",
        "data",
        "file_content",
        "messages",
        "password",
        "prompt",
        "raw",
        "result",
        "secret",
        "token",
        "tool_result",
    }
)


class TraceCollector:
    """Collect a bounded event stream without participating in control flow."""

    def __init__(self, trace_id: str | None = None, *, max_events: int = 500) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self.trace_id = trace_id or f"trace_{uuid.uuid4().hex}"
        self.max_events = max_events
        self._events: list[TraceEvent] = []
        self._sequence = 0
        self._dropped = 0
        self._lock = threading.Lock()

    def __deepcopy__(self, memo: dict[int, Any]) -> "TraceCollector":
        """Runtime state may be copied by Workflow; one request keeps one collector."""

        del memo
        return self

    def emit(
        self,
        event_type: str,
        *,
        component: str,
        name: str,
        status: str,
        latency_ms: float | int | None = None,
        error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TraceEvent | None:
        """Append one event. Observability failures are intentionally swallowed."""

        try:
            normalized_latency = self._latency(latency_ms)
            safe_metadata = self._sanitize(dict(metadata or {}))
            with self._lock:
                if len(self._events) >= self.max_events:
                    self._dropped += 1
                    return None
                self._sequence += 1
                event = TraceEvent(
                    trace_id=self.trace_id,
                    event_type=str(event_type)[:80],
                    component=str(component)[:80],
                    name=str(name)[:160],
                    status=str(status)[:40],
                    latency_ms=normalized_latency,
                    error_code=None if error_code is None else str(error_code)[:120],
                    metadata=safe_metadata,
                    event_id=f"evt_{uuid.uuid4().hex}",
                    sequence=self._sequence,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                self._events.append(event)
                return event
        except Exception:
            return None

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            events = [event.to_dict() for event in self._events]
            dropped = self._dropped
        if dropped:
            events.append(
                {
                    "schema_version": 1,
                    "trace_id": self.trace_id,
                    "event_id": "",
                    "sequence": len(events) + 1,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event_type": "error",
                    "component": "observability",
                    "name": "trace_buffer",
                    "status": "truncated",
                    "latency_ms": None,
                    "error_code": "trace_event_limit_reached",
                    "metadata": {"dropped_count": dropped},
                }
            )
        return copy.deepcopy(events)

    @staticmethod
    def _latency(value: float | int | None) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        if not math.isfinite(number) or number < 0:
            return None
        return round(number, 3)

    @classmethod
    def _sanitize(cls, value: Any, *, depth: int = 0) -> Any:
        if depth >= 4:
            return "<max-depth>"
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, str):
            return value if len(value) <= 240 else value[:239] + "…"
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for key, item in list(value.items())[:30]:
                normalized_key = str(key)[:80]
                lower_key = normalized_key.lower()
                is_sensitive = (
                    lower_key in _SENSITIVE_KEYS
                    or any(
                        marker in lower_key
                        for marker in ("authorization", "cookie", "password", "secret", "token")
                    )
                    or lower_key.startswith("raw_")
                    or lower_key.endswith("_content")
                )
                if is_sensitive:
                    result[normalized_key] = "<redacted>"
                else:
                    result[normalized_key] = cls._sanitize(item, depth=depth + 1)
            if len(value) > 30:
                result["_truncated_keys"] = len(value) - 30
            return result
        if isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)
            result = [cls._sanitize(item, depth=depth + 1) for item in items[:20]]
            if len(items) > 20:
                result.append(f"<truncated:{len(items) - 20}>")
            return result
        return f"<{type(value).__name__}>"
