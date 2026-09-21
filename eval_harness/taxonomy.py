"""Stable failure categories emitted by the evaluation harness."""

from __future__ import annotations

from enum import StrEnum
from typing import Iterable


class FailureType(StrEnum):
    ROUTING_ERROR = "ROUTING_ERROR"
    TOOL_SELECTION_ERROR = "TOOL_SELECTION_ERROR"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    MEMORY_ERROR = "MEMORY_ERROR"
    CONTEXT_ERROR = "CONTEXT_ERROR"
    CONTRACT_ERROR = "CONTRACT_ERROR"
    ANSWER_ERROR = "ANSWER_ERROR"
    TIMEOUT = "TIMEOUT"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    TRACE_ERROR = "TRACE_ERROR"
    HARNESS_ERROR = "HARNESS_ERROR"


_PRIORITY = {
    FailureType.SECURITY_VIOLATION: 0,
    FailureType.TIMEOUT: 1,
    FailureType.HARNESS_ERROR: 2,
    FailureType.CONTRACT_ERROR: 3,
    FailureType.ROUTING_ERROR: 4,
    FailureType.TOOL_EXECUTION_ERROR: 5,
    FailureType.TOOL_SELECTION_ERROR: 6,
    FailureType.MEMORY_ERROR: 7,
    FailureType.CONTEXT_ERROR: 8,
    FailureType.TRACE_ERROR: 9,
    FailureType.ANSWER_ERROR: 10,
}


def primary_failure(types: Iterable[str | FailureType | None]) -> str | None:
    values = [FailureType(value) for value in types if value]
    if not values:
        return None
    return str(min(values, key=lambda value: _PRIORITY[value]))


def classify_legacy_failure(reasons: Iterable[str]) -> str | None:
    text = " ".join(str(reason) for reason in reasons).lower()
    if not text:
        return None
    if "timeout" in text or "timed out" in text:
        return str(FailureType.TIMEOUT)
    if "unauthorized" in text or "permission" in text or "security" in text:
        return str(FailureType.SECURITY_VIOLATION)
    if "contract" in text or "schema" in text:
        return str(FailureType.CONTRACT_ERROR)
    if "route" in text:
        return str(FailureType.ROUTING_ERROR)
    if "memory" in text:
        return str(FailureType.MEMORY_ERROR)
    if "context" in text:
        return str(FailureType.CONTEXT_ERROR)
    if "wrong_tool" in text or "tool_selection" in text or "wrong_parameter" in text:
        return str(FailureType.TOOL_SELECTION_ERROR)
    if "tool" in text and ("error" in text or "failed" in text):
        return str(FailureType.TOOL_EXECUTION_ERROR)
    return str(FailureType.ANSWER_ERROR)
