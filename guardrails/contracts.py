"""Stable Guardrail contracts shared by local, MCP, and Sub-agent tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


GuardrailOutcome = Literal["allow", "block", "needs_approval"]


@dataclass(frozen=True)
class ToolGuardrailPolicy:
    """Static, host-owned classification attached to one ToolDefinition."""

    action_type: str = "analysis"
    risk_level: str = "low"
    tool_kind: str = "local"


@dataclass(frozen=True)
class GuardrailDecision:
    """One deterministic decision made before a tool handler is entered."""

    decision: GuardrailOutcome
    rule_id: str
    reason: str
    tool_name: str
    action_type: str
    risk_level: str
    tool_kind: str
    approval_id: str | None = None
    action_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def pending_state(self) -> dict[str, Any] | None:
        if self.decision != "needs_approval":
            return None
        return {
            "status": "pending",
            "approval_id": self.approval_id,
            "action_hash": self.action_hash,
            "tool_name": self.tool_name,
            "action_type": self.action_type,
            "risk_level": self.risk_level,
            "rule_id": self.rule_id,
        }
