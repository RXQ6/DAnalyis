"""Deterministic Todo state management for multi-step Agent runs."""

from __future__ import annotations

from typing import Any

from .registry import ToolDefinition, ToolExecutionError


TODO_STATUSES = ("pending", "in_progress", "completed")

TODO_WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "content": {"type": "string", "minLength": 1},
                    "status": {"type": "string", "enum": list(TODO_STATUSES)},
                },
                "required": ["id", "content", "status"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["todos"],
    "additionalProperties": False,
}


def todo_summary(todos: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    return {
        status: [dict(todo) for todo in todos if todo["status"] == status]
        for status in ("completed", "in_progress", "pending")
    }


def todo_write(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Replace the current Todo snapshot; this never executes analysis work."""
    current = context.get("todos")
    if not isinstance(current, list):
        raise ToolExecutionError(
            "todo_state_unavailable",
            "Todo state is unavailable in the current Agent run",
            recoverable=False,
        )

    incoming = arguments["todos"]
    ids = [todo["id"].strip() for todo in incoming]
    if len(ids) != len(set(ids)):
        raise ToolExecutionError(
            "invalid_arguments",
            "Todo ids must be unique",
        )

    normalized = [
        {
            "id": todo["id"].strip(),
            "content": todo["content"].strip(),
            "status": todo["status"],
        }
        for todo in incoming
    ]
    if any(not todo["id"] or not todo["content"] for todo in normalized):
        raise ToolExecutionError(
            "invalid_arguments",
            "Todo id and content cannot be blank",
        )

    current[:] = normalized
    return {"todos": [dict(todo) for todo in current], "summary": todo_summary(current)}


def todo_definition() -> ToolDefinition:
    return ToolDefinition(
        name="todo_write",
        description=(
            "Create or revise the Todo snapshot for a complex multi-step task and return "
            "its current summary. This manages plan state only and performs no data analysis."
        ),
        parameter_schema=TODO_WRITE_SCHEMA,
        handler=todo_write,
    )
