"""Generic controlled multi-step Agent Loop for Day8."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from context_compression import ContextCompressor

from .prompt import SYSTEM_PROMPT
from .state import AgentState
from tools.registry import ToolRegistry


class ModelClient(Protocol):
    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class MemoryClient(Protocol):
    def recall(
        self,
        *,
        scope_id: str,
        query: str,
        relevant_kv_keys: Sequence[str],
        top_k: int,
    ) -> Any: ...

    def remember(
        self,
        *,
        scope_id: str,
        requests: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]: ...


class ContextCompressorClient(Protocol):
    def compress(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        state: AgentState,
    ) -> Any: ...


class AgentLoop:
    """Coordinates model decisions and registry tools without tool-specific logic."""

    def __init__(
        self,
        model: ModelClient,
        registry: ToolRegistry,
        *,
        max_iter: int = 6,
        system_prompt: str = SYSTEM_PROMPT,
        memory: MemoryClient | None = None,
        context_compressor: ContextCompressorClient | None = None,
    ) -> None:
        if max_iter < 1:
            raise ValueError("max_iter must be at least 1")
        self.model = model
        self.registry = registry
        self.max_iter = max_iter
        self.system_prompt = system_prompt
        self.memory = memory
        self.context_compressor = context_compressor or ContextCompressor()

    def run(
        self,
        user_question: str,
        *,
        dataset: str | None = None,
        dataset_context: dict[str, Any] | None = None,
        schema: dict[str, Any] | list[Any] | None = None,
        memory_scope: str | None = None,
        memory_keys: Sequence[str] | None = None,
        memory_top_k: int = 3,
        remember: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        artifact_dir: str | None = None,
        dataset_registry: Any | None = None,
        history_messages: Sequence[Mapping[str, Any]] | None = None,
        prior_tool_results: Sequence[Mapping[str, Any]] | None = None,
        initial_todos: Sequence[Mapping[str, str]] | None = None,
        active_dataset_ids: Sequence[str] | None = None,
        conversation_id: str | None = None,
        turn_id: str | None = None,
    ) -> AgentState:
        if dataset_registry is not None and any(
            value is not None for value in (dataset, dataset_context, schema)
        ):
            raise ValueError(
                "dataset, dataset_context and schema are derived from DatasetRegistry"
            )
        if remember is not None and (self.memory is None or not memory_scope):
            raise ValueError("explicit remember requires memory and memory_scope")
        recall = None
        memory_errors: list[dict[str, str]] = []
        if self.memory is not None and memory_scope:
            try:
                recall = self.memory.recall(
                    scope_id=memory_scope,
                    query=user_question,
                    relevant_kv_keys=(
                        tuple(memory_keys)
                        if memory_keys is not None
                        else self._relevant_memory_keys(user_question)
                    ),
                    top_k=memory_top_k,
                )
            except Exception as error:
                memory_errors.append(
                    {"phase": "recall", "error_type": type(error).__name__}
                )
        safe_dataset_context = (
            dataset_registry.public_context(active_dataset_ids)
            if dataset_registry is not None
            else (dataset_context or {})
        )
        state = AgentState(
            conversation_id=conversation_id,
            turn_id=turn_id,
            dataset=dataset,
            dataset_context=safe_dataset_context,
            schema=schema,
            max_iter=self.max_iter,
            memory_context=recall.context if recall is not None else "",
            recalled_memories=list(recall.memories) if recall is not None else [],
            memory_errors=memory_errors,
            prior_tool_results=[copy.deepcopy(dict(item)) for item in (prior_tool_results or ())],
            todos=[dict(todo) for todo in (initial_todos or ())],
        )
        state.add_message("system", self.system_prompt)
        if state.memory_context:
            state.add_message("system", state.memory_context, name="memory_context")
        for message in history_messages or ():
            state.messages.append(copy.deepcopy(dict(message)))
        state.add_message(
            "user",
            user_question,
            dataset_context=state.dataset_context,
            schema=state.schema,
        )

        for iteration in range(1, self.max_iter + 1):
            state.iteration = iteration
            model_messages = self._messages_for_model(state)
            tool_schemas = self.registry.tool_schemas()
            try:
                compressed = self.context_compressor.compress(
                    messages=model_messages,
                    tools=tool_schemas,
                    state=state,
                )
                model_messages = compressed.messages
                state.context_reports.append(copy.deepcopy(compressed.report))
            except Exception as error:
                state.context_errors.append(
                    {"phase": "compression", "error_type": type(error).__name__}
                )
            raw_decision = self.model.complete(
                messages=model_messages,
                tools=tool_schemas,
            )
            decision = self._normalize_decision(raw_decision, iteration, turn_id=turn_id)

            if decision["type"] == "needs_user_input":
                answer = str(decision.get("content", "")).strip()
                state.add_message("assistant", answer)
                state.final_answer = answer
                state.stop_reason = "needs_user_input"
                return state

            if decision["type"] == "final_answer":
                answer = str(decision.get("content", "")).strip()
                state.add_message("assistant", answer)
                state.final_answer = answer
                state.stop_reason = "final_answer"
                if remember is not None:
                    try:
                        state.remembered_memories = self.memory.remember(
                            scope_id=memory_scope,
                            requests=remember,
                        )
                    except Exception as error:
                        state.memory_errors.append(
                            {"phase": "remember", "error_type": type(error).__name__}
                        )
                return state

            calls = decision["tool_calls"]
            state.messages.append(
                {
                    "role": "assistant",
                    "content": decision.get("content"),
                    "tool_calls": [self._assistant_call(call) for call in calls],
                }
            )
            for call in calls:
                tool_result = self.registry.execute(
                    call["name"],
                    call["arguments"],
                    context={
                        "dataset": state.dataset,
                        "dataset_context": state.dataset_context,
                        "schema": state.schema,
                        "iteration": state.iteration,
                        "todos": state.todos,
                        "call_id": call["id"],
                        "artifact_dir": artifact_dir,
                        "dataset_registry": dataset_registry,
                        "active_dataset_ids": (
                            None
                            if active_dataset_ids is None
                            else list(active_dataset_ids)
                        ),
                        "previous_tool_results": self._tool_results_for_context(state),
                    },
                )
                observation = {
                    "tool": call["name"],
                    "iteration": state.iteration,
                    **tool_result,
                }
                self._record_observation(state, call, observation)
                if not tool_result["ok"]:
                    error = tool_result["error"] or {}
                    if not error.get("recoverable", True):
                        state.stop_reason = "unrecoverable_tool_error"
                        return state

        state.stop_reason = "max_iter"
        return state

    @staticmethod
    def _tool_results_for_context(state: AgentState) -> list[dict[str, Any]]:
        """Expose prior normalized ToolResults to dependent registered tools."""
        current = [
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
        return copy.deepcopy(state.prior_tool_results) + current

    @staticmethod
    def _relevant_memory_keys(question: str) -> tuple[str, ...]:
        lowered = question.lower()
        keys = []
        if any(term in lowered for term in ("指标", "metric", "统计", "分析")):
            keys.append("preferred_metric")
        if any(term in lowered for term in ("图", "可视化", "chart")):
            keys.append("preferred_chart_type")
        if any(term in lowered for term in ("日期", "时间", "趋势", "date", "time", "trend")):
            keys.append("default_time_column")
        if any(
            term in lowered
            for term in ("统计", "聚合", "总和", "平均", "分组", "趋势", "sum", "average")
        ):
            keys.append("default_aggregation")
        return tuple(keys or ("preferred_metric", "default_aggregation"))

    @staticmethod
    def _messages_for_model(state: AgentState) -> list[dict[str, Any]]:
        messages = copy.deepcopy(state.messages)
        if not state.todos:
            return messages
        messages.insert(
            1,
            {
                "role": "system",
                "content": (
                    "当前 Todo 概览（计划状态，不代表工具已执行）："
                    + json.dumps(state.todo_summary(), ensure_ascii=False)
                ),
            },
        )
        return messages

    @staticmethod
    def _record_observation(
        state: AgentState, call: dict[str, Any], observation: dict[str, Any]
    ) -> None:
        state.record_tool_execution(
            call_id=call["id"],
            name=call["name"],
            arguments=call["arguments"],
            observation=observation,
        )
        state.messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call["name"],
                "content": json.dumps(observation, ensure_ascii=False),
            }
        )

    @staticmethod
    def _assistant_call(call: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": call["id"],
            "type": "function",
            "function": {
                "name": call["name"],
                "arguments": json.dumps(call["arguments"], ensure_ascii=False),
            },
        }

    @staticmethod
    def _normalize_decision(
        raw: dict[str, Any], iteration: int, *, turn_id: str | None = None
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise TypeError("model decision must be a dictionary")
        if raw.get("type") == "final_answer":
            return {"type": "final_answer", "content": raw.get("content", "")}
        if raw.get("type") == "needs_user_input":
            return {"type": "needs_user_input", "content": raw.get("content", "")}

        raw_calls: list[dict[str, Any]]
        if raw.get("type") == "tool_call":
            raw_calls = [raw]
        elif isinstance(raw.get("tool_calls"), list) and raw["tool_calls"]:
            raw_calls = raw["tool_calls"]
        else:
            if isinstance(raw.get("content"), str):
                return {"type": "final_answer", "content": raw["content"]}
            raise ValueError("model decision contains neither a tool call nor final answer")

        calls = []
        for index, raw_call in enumerate(raw_calls, start=1):
            function = raw_call.get("function", raw_call)
            name = function.get("name")
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError("invalid tool call name or arguments")
            calls.append(
                {
                    "id": raw_call.get("id")
                    or f"{turn_id + '_' if turn_id else ''}call_{iteration}_{index}",
                    "name": name,
                    "arguments": arguments,
                }
            )
        return {"type": "tool_calls", "content": raw.get("content"), "tool_calls": calls}
