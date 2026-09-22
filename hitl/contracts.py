"""Public, serialization-safe HITL contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    action_hash: str
    tool_name: str
    action_type: str
    risk_level: str
    rule_id: str
    trace_id: str | None
    call_id: str | None
    status: ApprovalStatus
    created_at: str
    expires_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalDecision:
    approval_id: str
    action_hash: str
    status: ApprovalStatus
    reason: str
    decided_at: str
    consumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalResolution:
    ok: bool
    decision: ApprovalDecision | None
    tool_result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    trace_events: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "decision": None if self.decision is None else self.decision.to_dict(),
            "tool_result": self.tool_result,
            "error": self.error,
            "trace_events": [dict(event) for event in self.trace_events],
        }
