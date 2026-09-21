"""Contracts and hard limits for the single v1 data-check Sub-agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict


class SubAgentEvidence(TypedDict):
    callId: str
    toolName: str
    data: Any


class SubAgentUsage(TypedDict):
    iterations: int
    toolCalls: int


class SubAgentResult(TypedDict):
    subtaskId: str
    status: Literal["completed", "needs_input", "max_iter", "failed", "timeout"]
    summary: str
    evidence: list[SubAgentEvidence]
    usedDatasetIds: list[str]
    warnings: list[str]
    stopReason: str
    usage: SubAgentUsage
    error: dict[str, Any] | None


@dataclass(frozen=True)
class SubAgentLimits:
    max_iterations: int = 3
    max_tool_calls: int = 4
    timeout_seconds: float = 15.0
    max_task_chars: int = 800
    max_summary_chars: int = 2000
    max_evidence_items: int = 4
    max_evidence_bytes: int = 3000
    max_result_bytes: int = 12 * 1024

    def __post_init__(self) -> None:
        integer_limits = (
            self.max_iterations,
            self.max_tool_calls,
            self.max_task_chars,
            self.max_summary_chars,
            self.max_evidence_items,
            self.max_evidence_bytes,
            self.max_result_bytes,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in integer_limits
        ):
            raise ValueError("Sub-agent integer limits must be positive integers")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Sub-agent timeout must be positive")
