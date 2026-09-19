"""Conversation-scoped orchestration around the existing single-run AgentLoop."""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datasets import DatasetRegistry

from .loop import AgentLoop
from .state import AgentState


MAX_HISTORY_TURNS = 12
MAX_PRIOR_TOOL_RESULTS = 24
ANALYSIS_TOOLS = frozenset(
    {
        "basic_stats",
        "group_compare",
        "trend_analysis",
        "detect_anomaly",
        "top_n",
        "compare_datasets",
    }
)


@dataclass
class ConversationTurn:
    turn_id: str
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    dataset_ids: list[str]
    stop_reason: str | None


@dataclass
class ConversationState:
    """Temporary state owned by one active conversation, never by long-term Memory."""

    conversation_id: str
    dataset_registry: DatasetRegistry
    turns: list[ConversationTurn] = field(default_factory=list)
    active_dataset_ids: list[str] = field(default_factory=list)
    current_dataset_id: str | None = None
    last_dataset_ids: list[str] = field(default_factory=list)
    last_metric: str | None = None
    last_group: str | None = None
    last_time_range: dict[str, str] | None = None
    last_filters: dict[str, Any] = field(default_factory=dict)
    open_todos: list[dict[str, str]] = field(default_factory=list)

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def history_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        active = set(self.active_dataset_ids)
        for turn in self.turns[-MAX_HISTORY_TURNS:]:
            if turn.dataset_ids and not set(turn.dataset_ids).issubset(active):
                continue
            messages.extend(copy.deepcopy(turn.messages))
        return messages

    def prior_tool_results(self) -> list[dict[str, Any]]:
        active = set(self.active_dataset_ids)
        results: list[dict[str, Any]] = []
        for turn in self.turns:
            for result in turn.tool_results:
                result_ids = set(_dataset_ids(result))
                if result_ids and not result_ids.issubset(active):
                    continue
                results.append(copy.deepcopy(result))
        return results[-MAX_PRIOR_TOOL_RESULTS:]


class ConversationRunner:
    """Adds multi-turn continuity without moving conversation policy into AgentLoop."""

    def __init__(
        self,
        loop: AgentLoop,
        *,
        work_dir: str | Path | None = None,
        dataset_registry: DatasetRegistry | None = None,
        conversation_id: str | None = None,
        historical_compactor: Any | None = None,
    ) -> None:
        if dataset_registry is None:
            if work_dir is None:
                raise ValueError("work_dir or dataset_registry is required")
            dataset_registry = DatasetRegistry(work_dir)
        self.loop = loop
        self.historical_compactor = historical_compactor
        self.state = ConversationState(
            conversation_id=conversation_id or f"conv_{uuid.uuid4().hex[:12]}",
            dataset_registry=dataset_registry,
        )

    def add_datasets(
        self, file_paths: Sequence[str | Path], *, replace: bool = True
    ) -> list[dict[str, Any]]:
        summaries = [self.state.dataset_registry.register(path) for path in file_paths]
        dataset_ids = [summary["datasetId"] for summary in summaries]
        if replace:
            self.state.active_dataset_ids = dataset_ids
            self.state.last_dataset_ids = list(dataset_ids)
        else:
            for dataset_id in dataset_ids:
                if dataset_id not in self.state.active_dataset_ids:
                    self.state.active_dataset_ids.append(dataset_id)
        self.state.current_dataset_id = dataset_ids[-1] if dataset_ids else None
        return summaries

    def set_active_datasets(self, dataset_ids: Sequence[str]) -> None:
        normalized = list(dict.fromkeys(dataset_ids))
        for dataset_id in normalized:
            if not self.state.dataset_registry.contains(dataset_id):
                raise ValueError(f"dataset is not registered: {dataset_id}")
        self.state.active_dataset_ids = normalized
        self.state.current_dataset_id = normalized[-1] if normalized else None

    def run(
        self,
        user_question: str,
        *,
        dataset_paths: Sequence[str | Path] | None = None,
        replace_datasets: bool = True,
        memory_scope: str | None = None,
        memory_keys: Sequence[str] | None = None,
        memory_top_k: int = 3,
        remember: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        artifact_dir: str | None = None,
    ) -> AgentState:
        if dataset_paths:
            self.add_datasets(dataset_paths, replace=replace_datasets)

        turn_id = f"turn_{self.state.turn_count + 1}"
        history_messages = self.state.history_messages()
        summary_report: dict[str, Any] | None = None
        if self.historical_compactor is not None:
            try:
                compacted = self.historical_compactor.compact(self.state)
                history_messages = compacted.messages
                summary_report = compacted.report
            except Exception as error:
                summary_report = {
                    "phase": "historical_summary",
                    "triggered": True,
                    "fallback": True,
                    "fallbackTo": "context_compression_v1_1",
                    "errorType": type(error).__name__,
                }
        history = [self._context_message(), *history_messages]
        state = self.loop.run(
            user_question,
            dataset_registry=self.state.dataset_registry,
            history_messages=history,
            prior_tool_results=self.state.prior_tool_results(),
            initial_todos=self.state.open_todos,
            active_dataset_ids=self.state.active_dataset_ids,
            conversation_id=self.state.conversation_id,
            turn_id=turn_id,
            memory_scope=memory_scope,
            memory_keys=memory_keys,
            memory_top_k=memory_top_k,
            remember=remember,
            artifact_dir=artifact_dir,
        )
        if summary_report is not None:
            state.context_reports.append(copy.deepcopy(summary_report))
            if summary_report.get("fallback"):
                state.context_errors.append(
                    {
                        "phase": "historical_summary",
                        "error_type": str(summary_report.get("errorType", "UnknownError")),
                    }
                )
        self._record_turn(state, turn_id)
        return state

    def _context_message(self) -> dict[str, Any]:
        context = {
            "conversationId": self.state.conversation_id,
            "currentDatasetId": self.state.current_dataset_id,
            "activeDatasetIds": list(self.state.active_dataset_ids),
            "lastDatasetIds": list(self.state.last_dataset_ids),
            "lastMetric": self.state.last_metric,
            "lastGroup": self.state.last_group,
            "lastTimeRange": copy.deepcopy(self.state.last_time_range),
            "lastFilters": copy.deepcopy(self.state.last_filters),
            "priorToolResults": self.state.prior_tool_results(),
        }
        return {
            "role": "system",
            "name": "conversation_context",
            "content": (
                "当前会话临时状态（只用于理解追问，不属于长期 Memory；"
                "当前活动文件和当前轮 ToolResult 优先）："
                + json.dumps(context, ensure_ascii=False)
            ),
        }

    def _record_turn(self, state: AgentState, turn_id: str) -> None:
        current_messages = _current_turn_messages(state.messages)
        tool_results = _tool_results(state)
        used_ids = _used_dataset_ids(tool_results)
        if not used_ids:
            used_ids = list(self.state.active_dataset_ids)

        self._activate_derived_datasets(tool_results)
        self._update_focus(state)
        self.state.last_dataset_ids = used_ids
        if len(used_ids) == 1:
            self.state.current_dataset_id = used_ids[0]
        self.state.open_todos = [
            dict(todo) for todo in state.todos if todo.get("status") != "completed"
        ]
        self.state.turns.append(
            ConversationTurn(
                turn_id=turn_id,
                messages=current_messages,
                tool_results=tool_results,
                dataset_ids=used_ids,
                stop_reason=state.stop_reason,
            )
        )

    def _activate_derived_datasets(self, results: list[dict[str, Any]]) -> None:
        for result in results:
            data = result.get("toolResult", {}).get("data")
            dataset = data.get("dataset") if isinstance(data, dict) else None
            dataset_id = dataset.get("datasetId") if isinstance(dataset, dict) else None
            if dataset_id and dataset_id not in self.state.active_dataset_ids:
                self.state.active_dataset_ids.append(dataset_id)

    def _update_focus(self, state: AgentState) -> None:
        for entry in reversed(state.execution_trace):
            if not entry["success"] or entry["tool_name"] not in ANALYSIS_TOOLS:
                continue
            arguments = entry["arguments"]
            data = entry["data"] if isinstance(entry["data"], dict) else {}
            if isinstance(arguments.get("datasetId"), str):
                self.state.current_dataset_id = arguments["datasetId"]
            if isinstance(arguments.get("metric"), str):
                self.state.last_metric = arguments["metric"]
            if isinstance(arguments.get("groupBy"), str):
                self.state.last_group = arguments["groupBy"]
            if isinstance(arguments.get("filters"), dict):
                self.state.last_filters = copy.deepcopy(arguments["filters"])
            time_range = _time_range(arguments, data)
            if time_range is not None:
                self.state.last_time_range = time_range
            break


def _current_turn_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start = next(
        (index for index in range(len(messages) - 1, -1, -1) if messages[index].get("role") == "user"),
        len(messages),
    )
    return copy.deepcopy(messages[start:])


def _tool_results(state: AgentState) -> list[dict[str, Any]]:
    return [
        {
            "callId": entry["call_id"],
            "toolName": entry["tool_name"],
            "arguments": copy.deepcopy(entry["arguments"]),
            "toolResult": {
                "ok": entry["success"],
                "data": copy.deepcopy(entry["data"]),
                "error": copy.deepcopy(entry["error"]),
                "duration": entry["duration"],
                "truncated": entry["truncated"],
            },
        }
        for entry in state.execution_trace
    ]


def _used_dataset_ids(results: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for result in results:
        for dataset_id in _dataset_ids(result):
            if dataset_id not in found:
                found.append(dataset_id)
    return found


def _dataset_ids(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower().endswith("datasetid") and isinstance(item, str):
                if item not in found:
                    found.append(item)
            else:
                for dataset_id in _dataset_ids(item):
                    if dataset_id not in found:
                        found.append(dataset_id)
    elif isinstance(value, list):
        for item in value:
            for dataset_id in _dataset_ids(item):
                if dataset_id not in found:
                    found.append(dataset_id)
    return found


def _time_range(arguments: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    explicit = arguments.get("timeRange")
    if isinstance(explicit, dict) and explicit:
        return {str(key): str(value) for key, value in explicit.items()}
    points = data.get("points")
    if not isinstance(points, list) or not points:
        return None
    dates = [point.get("date") for point in points if isinstance(point, dict)]
    dates = [date for date in dates if isinstance(date, str)]
    if not dates:
        return None
    result = {"start": min(dates), "end": max(dates)}
    if isinstance(arguments.get("dateField"), str):
        result["dateField"] = arguments["dateField"]
    return result
