"""Shared dictionary contracts for the outer Workflow layer."""

from __future__ import annotations

from enum import Enum
from typing import Any, NotRequired, TypedDict


class Route(str, Enum):
    CHAT = "chat"
    ANALYSIS = "analysis"
    CALC = "calc"
    MEMORY_RECALL = "memory_recall"


class WorkflowState(TypedDict):
    query: str
    dataset_paths: NotRequired[list[str]]
    active_dataset_ids: NotRequired[list[str]]
    memory_scope: NotRequired[str]
    route: NotRequired[str]
    routing: NotRequired[dict[str, Any]]
    node_result: NotRequired[dict[str, Any]]
    response: NotRequired[str | None]
    error: NotRequired[dict[str, Any] | None]


ROUTES = frozenset(route.value for route in Route)
