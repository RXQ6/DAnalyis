"""Outer Workflow engine with one dictionary-based invoke entry point."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .nodes import AnalysisNode, WorkflowNode
from .router import RuleRouter
from .state import ROUTES, Route


class Workflow:
    def __init__(
        self,
        *,
        router: RuleRouter,
        nodes: Mapping[str | Route, WorkflowNode],
    ) -> None:
        normalized = {
            key.value if isinstance(key, Route) else str(key): value
            for key, value in nodes.items()
        }
        if set(normalized) != set(ROUTES):
            missing = sorted(ROUTES.difference(normalized))
            extra = sorted(set(normalized).difference(ROUTES))
            raise ValueError(f"workflow routes mismatch; missing={missing}, extra={extra}")
        self.router = router
        self.nodes = normalized

    def invoke(self, state: Mapping[str, Any]) -> dict[str, Any]:
        work_state = self._normalize_state(state)
        self._add_runtime_context(work_state)
        routing = self.router.route(work_state, allowed_routes=self.nodes.keys())
        route = routing["route"]
        if route not in self.nodes:
            raise ValueError(f"router selected an unregistered route: {route}")
        work_state["route"] = route
        work_state["routing"] = copy.deepcopy(routing)

        try:
            node_result = self.nodes[route].invoke(work_state)
            normalized_result = self._normalize_result(node_result)
        except Exception as error:
            normalized_result = {
                "status": "error",
                "response": None,
                "data": {},
                "error": {
                    "code": "node_execution_error",
                    "message": str(error),
                    "errorType": type(error).__name__,
                },
            }
        work_state["node_result"] = copy.deepcopy(normalized_result)
        work_state["response"] = normalized_result["response"]
        work_state["error"] = copy.deepcopy(normalized_result["error"])
        return {
            "status": normalized_result["status"],
            "route": route,
            "response": normalized_result["response"],
            "data": normalized_result["data"],
            "error": normalized_result["error"],
            "routing": copy.deepcopy(routing),
        }

    def _add_runtime_context(self, state: dict[str, Any]) -> None:
        node = self.nodes[Route.ANALYSIS.value]
        if isinstance(node, AnalysisNode):
            for key, value in node.routing_context().items():
                state.setdefault(key, value)

    @staticmethod
    def _normalize_state(state: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(state, Mapping):
            raise TypeError("workflow state must be a mapping")
        normalized = copy.deepcopy(dict(state))
        query = normalized.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("workflow state requires a non-empty query")
        normalized["query"] = query.strip()
        if "dataset_paths" in normalized:
            paths = normalized["dataset_paths"]
            if isinstance(paths, (str, bytes)) or not isinstance(paths, (list, tuple)):
                raise ValueError("dataset_paths must be a list or tuple")
            normalized["dataset_paths"] = list(paths)
        return normalized

    @staticmethod
    def _normalize_result(result: Any) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            raise TypeError("workflow node result must be a mapping")
        status = result.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError("workflow node result requires status")
        data = result.get("data", {})
        if not isinstance(data, Mapping):
            raise ValueError("workflow node result data must be a mapping")
        error = result.get("error")
        if error is not None and not isinstance(error, Mapping):
            raise ValueError("workflow node result error must be a mapping or null")
        return {
            "status": status,
            "response": result.get("response"),
            "data": dict(data),
            "error": None if error is None else dict(error),
        }
