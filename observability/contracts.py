"""Stable structured trace-event contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TraceEvent:
    """One sanitized observation emitted during a request."""

    trace_id: str
    event_type: str
    component: str
    name: str
    status: str
    latency_ms: float | None = None
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""
    sequence: int = 0
    timestamp: str = ""
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
