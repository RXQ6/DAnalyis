"""State owned by one Day8 Agent Loop run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    dataset: str | None = None
    dataset_context: dict[str, Any] = field(default_factory=dict)
    schema: dict[str, Any] | list[Any] | None = None
    iteration: int = 0
    max_iter: int = 6
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    execution_trace: list[dict[str, Any]] = field(default_factory=list)
    todos: list[dict[str, str]] = field(default_factory=list)
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
