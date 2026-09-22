"""Isolated execution and result sanitization for the data-check Sub-agent."""

from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from agent import AgentLoop, AgentState
from context_compression import ContextCompressor
from tools.registry import ToolRegistry

from .contracts import SubAgentLimits, SubAgentResult
from .prompt import DATA_CHECK_SYSTEM_PROMPT
from .registry import DATA_CHECK_TOOLS, ToolBudget, build_restricted_registry


@dataclass
class _RunOutcome:
    state: AgentState | None = None
    error: Exception | None = None


class DataCheckSubAgentRunner:
    """Runs one bounded task without parent messages, history, Todo, or Memory."""

    def __init__(
        self,
        model: Any,
        source_registry: ToolRegistry,
        *,
        limits: SubAgentLimits | None = None,
        context_compressor: Any | None = None,
    ) -> None:
        self.model = model
        self.source_registry = source_registry
        self.limits = limits or SubAgentLimits()
        self.context_compressor = context_compressor or ContextCompressor()

    def run(
        self,
        *,
        subtask_id: str,
        task: str,
        dataset_id: str,
        dataset_registry: Any,
        metric: str | None = None,
        trace_collector: Any | None = None,
    ) -> SubAgentResult:
        normalized_task = self._validate_task(task)
        started = time.perf_counter()
        self._emit(
            trace_collector,
            "subagent_started",
            subtask_id,
            status="started",
            metadata={"dataset_id": dataset_id},
        )
        deadline = time.monotonic() + self.limits.timeout_seconds
        budget = ToolBudget(self.limits.max_tool_calls, deadline)
        registry = build_restricted_registry(
            self.source_registry,
            budget=budget,
            allowed_tools=DATA_CHECK_TOOLS,
        )
        loop = AgentLoop(
            self.model,
            registry,
            max_iter=self.limits.max_iterations,
            system_prompt=DATA_CHECK_SYSTEM_PROMPT,
            memory=None,
            context_compressor=self.context_compressor,
        )
        outcome = _RunOutcome()

        def execute() -> None:
            try:
                outcome.state = loop.run(
                    self._task_message(normalized_task, dataset_id, metric),
                    dataset_registry=dataset_registry,
                    active_dataset_ids=[dataset_id],
                    turn_id=subtask_id,
                    trace_collector=trace_collector,
                )
            except Exception as error:  # normalized before crossing the boundary
                outcome.error = error

        worker = threading.Thread(target=execute, daemon=True, name=f"subagent-{subtask_id[:32]}")
        worker.start()
        worker.join(self.limits.timeout_seconds)
        if worker.is_alive():
            result = self._empty_result(
                subtask_id,
                dataset_id,
                status="timeout",
                stop_reason="timeout",
                summary="Sub-agent execution timed out.",
                error={"code": "subagent_timeout", "message": "Sub-agent execution timed out"},
                tool_calls=budget.calls,
            )
            self._emit_completed(trace_collector, subtask_id, result, started)
            return result
        if outcome.error is not None:
            result = self._empty_result(
                subtask_id,
                dataset_id,
                status="failed",
                stop_reason="error",
                summary="Sub-agent execution failed.",
                error={
                    "code": "subagent_execution_error",
                    "message": "Sub-agent execution failed",
                    "errorType": type(outcome.error).__name__,
                },
                tool_calls=budget.calls,
            )
            self._emit_completed(trace_collector, subtask_id, result, started)
            return result
        assert outcome.state is not None
        result = self._sanitize(subtask_id, dataset_id, outcome.state, budget.calls)
        self._emit_completed(trace_collector, subtask_id, result, started)
        return result

    @staticmethod
    def _emit(
        collector: Any,
        event_type: str,
        name: str,
        *,
        status: str,
        latency_ms: float | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        emit = getattr(collector, "emit", None)
        if callable(emit):
            emit(
                event_type,
                component="subagent",
                name=name,
                status=status,
                latency_ms=latency_ms,
                error_code=error_code,
                metadata=metadata,
            )

    @classmethod
    def _emit_completed(
        cls,
        collector: Any,
        subtask_id: str,
        result: SubAgentResult,
        started: float,
    ) -> None:
        error = result.get("error")
        error_code = error.get("code") if isinstance(error, dict) else None
        cls._emit(
            collector,
            "subagent_completed",
            subtask_id,
            status=str(result["status"]),
            latency_ms=(time.perf_counter() - started) * 1000,
            error_code=error_code,
            metadata={
                "stop_reason": result["stopReason"],
                "iterations": result["usage"]["iterations"],
                "tool_calls": result["usage"]["toolCalls"],
                "evidence_count": len(result["evidence"]),
            },
        )
        if error_code:
            cls._emit(
                collector,
                "error",
                subtask_id,
                status="error",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_code=str(error_code),
                metadata={"source": "subagent"},
            )

    def _sanitize(
        self,
        subtask_id: str,
        dataset_id: str,
        state: AgentState,
        tool_calls: int,
    ) -> SubAgentResult:
        evidence = []
        warnings = []
        for entry in state.execution_trace:
            if not entry.get("success") or entry.get("tool_name") not in DATA_CHECK_TOOLS:
                continue
            data, truncated = self._bounded_evidence(entry.get("data"))
            if truncated:
                warnings.append(f"evidence_truncated:{entry['call_id']}")
            evidence.append(
                {
                    "callId": str(entry["call_id"]),
                    "toolName": str(entry["tool_name"]),
                    "data": data,
                }
            )
            if len(evidence) >= self.limits.max_evidence_items:
                break

        summary = str(state.final_answer or "").strip()
        if len(summary) > self.limits.max_summary_chars:
            summary = summary[: self.limits.max_summary_chars - 1] + "…"
            warnings.append("summary_truncated")

        if state.stop_reason == "needs_user_input":
            status = "needs_input"
        elif state.stop_reason == "max_iter":
            status = "max_iter"
        elif state.stop_reason == "final_answer" and evidence:
            status = "completed"
        else:
            status = "failed"
        error = None
        if status == "failed":
            error = {
                "code": "subagent_no_supported_evidence",
                "message": "Sub-agent did not produce supported evidence",
            }
        result: SubAgentResult = {
            "subtaskId": subtask_id,
            "status": status,
            "summary": summary,
            "evidence": evidence,
            "usedDatasetIds": [dataset_id],
            "warnings": list(dict.fromkeys(warnings)),
            "stopReason": str(state.stop_reason or "unknown"),
            "usage": {"iterations": state.iteration, "toolCalls": tool_calls},
            "error": error,
        }
        return self._bound_result(result)

    def _bounded_evidence(self, data: Any) -> tuple[Any, bool]:
        try:
            serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return {"preview": "<non-serializable result>", "truncated": True}, True
        encoded = serialized.encode("utf-8")
        if len(encoded) <= self.limits.max_evidence_bytes:
            return copy.deepcopy(data), False
        preview = encoded[: self.limits.max_evidence_bytes].decode("utf-8", errors="ignore")
        return {"preview": preview, "truncated": True}, True

    def _bound_result(self, result: SubAgentResult) -> SubAgentResult:
        serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) <= self.limits.max_result_bytes:
            return result
        bounded = copy.deepcopy(result)
        bounded["evidence"] = bounded["evidence"][:1]
        bounded["warnings"].append("result_truncated")
        return bounded

    def _validate_task(self, task: str) -> str:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("Sub-agent task must be a non-empty string")
        normalized = task.strip()
        if len(normalized) > self.limits.max_task_chars:
            raise ValueError("Sub-agent task is too long")
        return normalized

    @staticmethod
    def _task_message(task: str, dataset_id: str, metric: str | None) -> str:
        payload = {"task": task, "datasetId": dataset_id}
        if metric:
            payload["metric"] = metric
        return "受控数据检查子任务：" + json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _empty_result(
        subtask_id: str,
        dataset_id: str,
        *,
        status: str,
        stop_reason: str,
        summary: str,
        error: dict[str, Any],
        tool_calls: int,
    ) -> SubAgentResult:
        return {
            "subtaskId": subtask_id,
            "status": status,  # type: ignore[typeddict-item]
            "summary": summary,
            "evidence": [],
            "usedDatasetIds": [dataset_id],
            "warnings": [],
            "stopReason": stop_reason,
            "usage": {"iterations": 0, "toolCalls": tool_calls},
            "error": error,
        }
