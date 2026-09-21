"""Restricted and budgeted ToolRegistry construction for the v1 Sub-agent."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from tools.registry import ToolDefinition, ToolExecutionError, ToolRegistry


DATA_CHECK_TOOLS = ("inspect_data", "basic_stats", "detect_anomaly")
DELEGATE_TOOL_NAME = "delegate_data_check"


@dataclass
class ToolBudget:
    max_calls: int
    deadline: float
    calls: int = 0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def consume(self) -> None:
        with self._lock:
            if time.monotonic() >= self.deadline:
                raise ToolExecutionError(
                    "subagent_timeout",
                    "Sub-agent execution deadline was exceeded",
                    recoverable=False,
                )
            if self.calls >= self.max_calls:
                raise ToolExecutionError(
                    "subagent_tool_budget_exceeded",
                    "Sub-agent tool-call budget was exceeded",
                    {"maxToolCalls": self.max_calls},
                    recoverable=False,
                )
            self.calls += 1


def build_restricted_registry(
    source: ToolRegistry,
    *,
    budget: ToolBudget,
    allowed_tools: tuple[str, ...] = DATA_CHECK_TOOLS,
) -> ToolRegistry:
    if not allowed_tools or len(allowed_tools) != len(set(allowed_tools)):
        raise ValueError("Sub-agent tool allowlist must be non-empty and unique")
    if DELEGATE_TOOL_NAME in allowed_tools:
        raise ValueError("Sub-agent cannot receive the delegation tool")

    restricted = ToolRegistry()
    definitions = []
    for name in allowed_tools:
        source_definition = source.get(name)
        definitions.append(_budgeted_definition(source_definition, budget))
    restricted.register_many(definitions)
    return restricted


def _budgeted_definition(
    definition: ToolDefinition, budget: ToolBudget
) -> ToolDefinition:
    def handler(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
        budget.consume()
        return definition.handler(arguments, context)

    return ToolDefinition(
        name=definition.name,
        description=definition.description,
        parameter_schema=definition.parameter_schema,
        handler=handler,
        timeout_seconds=definition.timeout_seconds,
        max_result_bytes=definition.max_result_bytes,
    )

