"""Outer Workflow engine with one dictionary-based invoke entry point."""

from __future__ import annotations

import copy
import time
from collections.abc import Mapping
from typing import Any

from observability import TraceCollector

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
        request_started = time.perf_counter()
        work_state = self._normalize_state(state)
        supplied_collector = work_state.get("_trace_collector")
        collector = (
            supplied_collector
            if isinstance(supplied_collector, TraceCollector)
            else TraceCollector()
        )
        work_state["_trace_collector"] = collector
        collector.emit(
            "request_started",
            component="workflow",
            name="workflow",
            status="started",
            metadata={"has_dataset": bool(work_state.get("dataset_paths"))},
        )
        self._add_runtime_context(work_state)
        route_started = time.perf_counter()
        try:
            routing = self.router.route(work_state, allowed_routes=self.nodes.keys())
        except Exception as error:
            elapsed = (time.perf_counter() - route_started) * 1000
            collector.emit(
                "error",
                component="route",
                name="select",
                status="error",
                latency_ms=elapsed,
                error_code=type(error).__name__,
                metadata={"source": "workflow_router"},
            )
            collector.emit(
                "request_completed",
                component="workflow",
                name="workflow",
                status="error",
                latency_ms=(time.perf_counter() - request_started) * 1000,
                error_code=type(error).__name__,
            )
            raise
        route = routing["route"]
        collector.emit(
            "route_selected",
            component="route",
            name=route,
            status="ok",
            latency_ms=(time.perf_counter() - route_started) * 1000,
            metadata={"source": routing.get("source"), "rule": routing.get("rule")},
        )
        if route not in self.nodes:
            raise ValueError(f"router selected an unregistered route: {route}")
        work_state["route"] = route
        work_state["routing"] = copy.deepcopy(routing)

        try:
            node_result = self.nodes[route].invoke(work_state)
            normalized_result = self._normalize_result(node_result)
        except Exception as error:
            collector.emit(
                "error",
                component="workflow",
                name=route,
                status="error",
                error_code=type(error).__name__,
                metadata={"phase": "node_execution"},
            )
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
        request_status = "ok" if normalized_result["status"] == "ok" else normalized_result["status"]
        error_code = None
        if isinstance(normalized_result["error"], Mapping):
            error_code = str(normalized_result["error"].get("code") or "workflow_error")
            collector.emit(
                "error",
                component="workflow",
                name=route,
                status="error",
                error_code=error_code,
                metadata={"phase": "node_result"},
            )
        collector.emit(
            "request_completed",
            component="workflow",
            name="workflow",
            status=request_status,
            latency_ms=(time.perf_counter() - request_started) * 1000,
            error_code=error_code,
            metadata={"route": route},
        )
        trace_events = collector.snapshot()
        normalized_result["data"]["observability"] = {
            "trace_id": collector.trace_id,
            "events": trace_events,
        }
        agent_state = normalized_result["data"].get("agent_state")
        if isinstance(agent_state, dict):
            agent_state["trace_id"] = collector.trace_id
            agent_state["trace_events"] = copy.deepcopy(trace_events)
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
