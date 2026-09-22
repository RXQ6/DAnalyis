"""State owned by one Day8 Agent Loop run."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    conversation_id: str | None = None
    turn_id: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    dataset: str | None = None
    dataset_context: dict[str, Any] = field(default_factory=dict)
    schema: dict[str, Any] | list[Any] | None = None
    iteration: int = 0
    max_iter: int = 6
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    execution_trace: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str | None = None
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    approval_history: list[dict[str, Any]] = field(default_factory=list)
    skill_invocations: list[dict[str, Any]] = field(default_factory=list)
    prior_tool_results: list[dict[str, Any]] = field(default_factory=list)
    todos: list[dict[str, str]] = field(default_factory=list)
    memory_context: str = ""
    recalled_memories: list[dict[str, Any]] = field(default_factory=list)
    remembered_memories: list[dict[str, Any]] = field(default_factory=list)
    memory_errors: list[dict[str, str]] = field(default_factory=list)
    context_reports: list[dict[str, Any]] = field(default_factory=list)
    context_errors: list[dict[str, str]] = field(default_factory=list)
    stop_reason: str | None = None
    final_answer: str | None = None

    def add_message(self, role: str, content: Any, **extra: Any) -> None:
        self.messages.append({"role": role, "content": content, **extra})

    def todo_summary(self) -> dict[str, list[dict[str, str]]]:
        """Return the current plan grouped by status for model context."""
        return {
            status: [dict(todo) for todo in self.todos if todo["status"] == status]
            for status in ("completed", "in_progress", "pending")
        }

    def record_tool_execution(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        observation: dict[str, Any],
    ) -> None:
        call = {
            "id": call_id,
            "name": name,
            "arguments": arguments,
            "iteration": self.iteration,
        }
        self.tool_calls.append(call)
        self.execution_trace.append(
            {
                "iteration": self.iteration,
                "call_id": call_id,
                "tool_name": name,
                "arguments": arguments,
                "success": observation["ok"],
                "data": observation["data"],
                "error": observation["error"],
                "duration": observation["duration"],
                "truncated": observation["truncated"],
            }
        )

    def record_skill_invocation(self, invocation: dict[str, Any]) -> None:
        """Add a compact Skill audit event without pretending it is a tool call."""
        item = copy.deepcopy(invocation)
        self.skill_invocations.append(item)
        self.execution_trace.append(
            {
                "trace_type": "skill_invocation",
                "iteration": self.iteration,
                "call_id": item["invocation_id"],
                "tool_name": f"skill:{item['skill_name']}",
                "arguments": {
                    "skill": item["skill_name"],
                    "triggerRule": item["trigger"]["rule"],
                },
                "success": item["status"] == "completed" and item["contract_valid"],
                "data": {"skillInvocation": item},
                "error": (
                    None
                    if item["contract_valid"]
                    else {
                        "code": "skill_output_contract_violation",
                        "message": "Skill output did not satisfy its contract",
                    }
                ),
                "duration": item["duration_ms"],
                "truncated": False,
            }
        )
