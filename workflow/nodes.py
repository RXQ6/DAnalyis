"""Route nodes that adapt existing services to the Workflow state contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any, Protocol

from .calculator import CalculationError, evaluate_expression, extract_expression


class WorkflowNode(Protocol):
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]: ...


class AnalysisRunner(Protocol):
    def run(self, user_question: str, **kwargs: Any) -> Any: ...


class OptionalSkillRuntime(Protocol):
    def try_invoke(self, state: dict[str, Any]) -> dict[str, Any] | None: ...


class RecallMemory(Protocol):
    def recall(
        self,
        *,
        scope_id: str,
        query: str,
        relevant_kv_keys: Sequence[str],
        top_k: int,
    ) -> Any: ...


class AnalysisNode:
    """Delegates analysis unchanged to the existing ConversationRunner."""

    def __init__(
        self,
        runner: AnalysisRunner,
        *,
        skill_runtime: OptionalSkillRuntime | None = None,
    ) -> None:
        self.runner = runner
        self.skill_runtime = skill_runtime

    def routing_context(self) -> dict[str, Any]:
        conversation = getattr(self.runner, "state", None)
        return {
            "active_dataset_ids": list(
                getattr(conversation, "active_dataset_ids", ()) or ()
            )
        }

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.skill_runtime is not None:
            skill_result = self.skill_runtime.try_invoke(state)
            if skill_result is not None:
                return skill_result
        kwargs = {
            key: state[key]
            for key in (
                "dataset_paths",
                "replace_datasets",
                "memory_scope",
                "memory_keys",
                "memory_top_k",
                "remember",
                "artifact_dir",
            )
            if key in state
        }
        agent_state = self.runner.run(state["query"], **kwargs)
        stop_reason = getattr(agent_state, "stop_reason", None)
        answer = getattr(agent_state, "final_answer", None)
        if stop_reason == "needs_user_input":
            status = "needs_input"
        elif stop_reason == "final_answer":
            status = "ok"
        elif stop_reason == "max_iter":
            status = "incomplete"
        else:
            status = "error"
        serialized = asdict(agent_state) if is_dataclass(agent_state) else dict(agent_state)
        error = None
        if status == "error":
            error = {
                "code": stop_reason or "analysis_failed",
                "message": "analysis route did not complete successfully",
            }
        return {
            "status": status,
            "response": answer,
            "data": {"agent_state": serialized},
            "error": error,
        }


class CalcNode:
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        expression = extract_expression(state["query"])
        if expression is None:
            return _error("invalid_expression", "请求不是受支持的纯算术表达式")
        try:
            value = evaluate_expression(expression)
        except (CalculationError, ArithmeticError, ValueError) as error:
            return _error("calculation_error", str(error))
        return {
            "status": "ok",
            "response": str(value),
            "data": {"expression": expression, "value": value},
            "error": None,
        }


class MemoryRecallNode:
    DEFAULT_KEYS = (
        "preferred_metric",
        "preferred_chart_type",
        "default_time_column",
        "default_aggregation",
    )

    def __init__(self, memory: RecallMemory | None) -> None:
        self.memory = memory

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        scope = state.get("memory_scope")
        if not isinstance(scope, str) or not scope.strip():
            return {
                "status": "needs_input",
                "response": "需要 memory_scope 才能查询长期记忆。",
                "data": {},
                "error": None,
            }
        if self.memory is None:
            return _error("memory_unavailable", "长期记忆服务未配置")
        recall = self.memory.recall(
            scope_id=scope,
            query=state["query"],
            relevant_kv_keys=tuple(state.get("memory_keys", self.DEFAULT_KEYS)),
            top_k=int(state.get("memory_top_k", 3)),
        )
        memories = list(getattr(recall, "memories", ()) or ())
        context = str(getattr(recall, "context", "") or "")
        response = context or "没有找到相关的长期记忆。"
        return {
            "status": "ok",
            "response": response,
            "data": {"context": context, "memories": memories},
            "error": None,
        }


class ChatNode:
    def __init__(
        self,
        responder: Callable[[str, Mapping[str, Any]], str | Mapping[str, Any]] | None = None,
    ) -> None:
        self.responder = responder

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.responder is None:
            response: str | Mapping[str, Any] = (
                "你好，我可以帮助你分析 CSV/XLSX 数据、进行受控计算或查询已保存的偏好。"
            )
        else:
            response = self.responder(state["query"], state)
        if isinstance(response, Mapping):
            return {
                "status": str(response.get("status", "ok")),
                "response": response.get("response"),
                "data": dict(response.get("data", {})),
                "error": response.get("error"),
            }
        return {"status": "ok", "response": str(response), "data": {}, "error": None}


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "response": None,
        "data": {},
        "error": {"code": code, "message": message},
    }
