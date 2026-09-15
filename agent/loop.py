"""Generic controlled multi-step Agent Loop for Day8."""

from __future__ import annotations

import copy
import json
from typing import Any, Protocol

from .prompt import SYSTEM_PROMPT
from .state import AgentState
from tools.registry import ToolRegistry


class ModelClient(Protocol):
    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class AgentLoop:
    """Coordinates model decisions and registry tools without tool-specific logic."""

    def __init__(
        self,
        model: ModelClient,
        registry: ToolRegistry,
        *,
        max_iter: int = 6,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        if max_iter < 1:
            raise ValueError("max_iter must be at least 1")
        self.model = model
        self.registry = registry
        self.max_iter = max_iter
        self.system_prompt = system_prompt

    def run(
        self,
        user_question: str,
        *,
        dataset: str | None = None,
        dataset_context: dict[str, Any] | None = None,
        schema: dict[str, Any] | list[Any] | None = None,
    ) -> AgentState:
        state = AgentState(
            dataset=dataset,
            dataset_context=dataset_context or {},
            schema=schema,
            max_iter=self.max_iter,
        )
        state.add_message("system", self.system_prompt)
        state.add_message(
            "user",
            user_question,
            dataset_context=state.dataset_context,
            schema=state.schema,
        )

        for iteration in range(1, self.max_iter + 1):
            state.iteration = iteration
            raw_decision = self.model.complete(
                messages=copy.deepcopy(state.messages),
                tools=self.registry.tool_schemas(),
            )
            decision = self._normalize_decision(raw_decision, iteration)

            if decision["type"] == "final_answer":
                answer = str(decision.get("content", "")).strip()
                state.add_message("assistant", answer)
                state.final_answer = answer
                state.stop_reason = "final_answer"
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
    def _normalize_decision(raw: dict[str, Any], iteration: int) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise TypeError("model decision must be a dictionary")
        if raw.get("type") == "final_answer":
            return {"type": "final_answer", "content": raw.get("content", "")}

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
                    "id": raw_call.get("id") or f"call_{iteration}_{index}",
                    "name": name,
                    "arguments": arguments,
                }
            )
        return {"type": "tool_calls", "content": raw.get("content"), "tool_calls": calls}
