"""Deterministic Todo state management for multi-step Agent runs."""

from __future__ import annotations

from typing import Any

from .registry import ToolDefinition, ToolExecutionError


TODO_STATUSES = ("pending", "in_progress", "completed")
MAX_TODOS = 20
MAX_TODO_ID_LENGTH = 64
MAX_TODO_CONTENT_LENGTH = 200

TODO_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": MAX_TODO_ID_LENGTH},
        "content": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_TODO_CONTENT_LENGTH,
        },
        "status": {"type": "string", "enum": list(TODO_STATUSES)},
    },
    "required": ["id", "content", "status"],
    "additionalProperties": False,
}

TODO_WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "maxItems": MAX_TODOS,
            "items": TODO_ITEM_SCHEMA,
        },
        "updates": {
            "type": "array",
            "maxItems": MAX_TODOS,
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_TODO_ID_LENGTH,
                    },
                    "content": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_TODO_CONTENT_LENGTH,
                    },
                    "status": {"type": "string", "enum": list(TODO_STATUSES)},
                    "remove": {"type": "boolean"},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    "required": [],
    "additionalProperties": False,
}


def todo_summary(todos: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    return {
        status: [dict(todo) for todo in todos if todo["status"] == status]
        for status in ("completed", "in_progress", "pending")
    }


def todo_write(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Incrementally update Todo state; legacy full snapshots remain supported."""
    current = context.get("todos")
    if not isinstance(current, list):
        raise ToolExecutionError(
            "todo_state_unavailable",
            "Todo state is unavailable in the current Agent run",
            recoverable=False,
        )

    has_snapshot = "todos" in arguments
    has_updates = "updates" in arguments
    if has_snapshot == has_updates:
        raise ToolExecutionError(
            "invalid_arguments",
            "Provide exactly one of todos or updates",
        )

    if has_snapshot:
        candidate = _normalized_snapshot(arguments["todos"])
    else:
        candidate = _apply_updates(current, arguments["updates"])

    if len(candidate) > MAX_TODOS:
        raise ToolExecutionError(
            "invalid_arguments",
            f"Todo count cannot exceed {MAX_TODOS}",
        )

    current[:] = candidate
    return {"todos": [dict(todo) for todo in current], "summary": todo_summary(current)}


def _normalized_snapshot(incoming: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized = [_normalized_item(todo) for todo in incoming]
    _validate_unique_ids([todo["id"] for todo in normalized])
    return normalized


def _apply_updates(
    current: list[dict[str, str]], updates: list[dict[str, Any]]
) -> list[dict[str, str]]:
    normalized_ids = [update["id"].strip() for update in updates]
    _validate_unique_ids(normalized_ids)
    candidate = [dict(todo) for todo in current]

    for update, todo_id in zip(updates, normalized_ids, strict=True):
        if not todo_id:
            raise ToolExecutionError("invalid_arguments", "Todo id cannot be blank")
        index = next(
            (position for position, todo in enumerate(candidate) if todo["id"] == todo_id),
            None,
        )
        if update.get("remove", False):
            if "content" in update or "status" in update:
                raise ToolExecutionError(
                    "invalid_arguments",
                    "A removed Todo cannot also update content or status",
                )
            if index is not None:
                candidate.pop(index)
            continue

        if index is None:
            if "content" not in update or "status" not in update:
                raise ToolExecutionError(
                    "invalid_arguments",
                    "A new Todo requires content and status",
                )
            candidate.append(_normalized_item({**update, "id": todo_id}))
            continue

        if "content" in update:
            content = update["content"].strip()
            if not content:
                raise ToolExecutionError(
                    "invalid_arguments", "Todo content cannot be blank"
                )
            candidate[index]["content"] = content
        if "status" in update:
            candidate[index]["status"] = update["status"]

    return candidate


def _normalized_item(todo: dict[str, Any]) -> dict[str, str]:
    normalized = {
        "id": todo["id"].strip(),
        "content": todo["content"].strip(),
        "status": todo["status"],
    }
    if not normalized["id"] or not normalized["content"]:
        raise ToolExecutionError(
            "invalid_arguments", "Todo id and content cannot be blank"
        )
    return normalized


def _validate_unique_ids(ids: list[str]) -> None:
    if len(ids) != len(set(ids)):
        raise ToolExecutionError("invalid_arguments", "Todo ids must be unique")


def todo_definition() -> ToolDefinition:
    return ToolDefinition(
        name="todo_write",
        description=(
            "Incrementally create, update or remove Todo items and return the current summary. "
            "Prefer updates; todos is a legacy full-snapshot option. This manages plan state "
            "only and performs no data analysis."
        ),
        parameter_schema=TODO_WRITE_SCHEMA,
        handler=todo_write,
    )
