"""Execute a matched Skill through the existing AgentLoop implementation."""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from agent import AgentLoop, ConversationRunner

from .contracts import SkillDefinition, SkillInvocation, SkillMatch
from .output import OutputContractValidator
from .registry import SkillRegistry
from .tool_view import build_skill_tool_view


class SkillRuntime:
    def __init__(
        self,
        runner: ConversationRunner,
        registry: SkillRegistry,
        *,
        validator: OutputContractValidator | None = None,
    ) -> None:
        self.runner = runner
        self.registry = registry
        self.validator = validator or OutputContractValidator()
        self.invocations: list[dict[str, Any]] = []

    def try_invoke(self, state: dict[str, Any]) -> dict[str, Any] | None:
        match = self.registry.discover(state)
        if match is None:
            return None
        started_wall = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        invocation_id = f"skill_{uuid.uuid4().hex[:12]}"
        try:
            definition = self.registry.load(match.name)
            tool_view = build_skill_tool_view(
                self.runner.loop.registry, definition.allowed_tools
            )
            skill_loop = self._build_loop(definition, tool_view)
            skill_runner = self.runner.with_loop(skill_loop)
            agent_state = skill_runner.run(state["query"], **self._runner_kwargs(state))
            validation = self.validator.validate(
                agent_state.final_answer,
                definition.output_contract,
                agent_state.execution_trace,
            )
            status = self._invocation_status(agent_state.stop_reason, validation.ok)
            invocation = self._invocation(
                invocation_id,
                definition,
                match,
                status=status,
                started_at=started_wall,
                duration_ms=(time.perf_counter() - started) * 1000,
                agent_state=agent_state,
                contract_valid=validation.ok,
                output_errors=validation.errors,
            )
            invocation_data = invocation.to_dict()
            agent_state.record_skill_invocation(invocation_data)
            self.invocations.append(copy.deepcopy(invocation_data))
            serialized = asdict(agent_state) if is_dataclass(agent_state) else dict(agent_state)
            if validation.ok and validation.value is not None:
                return {
                    "status": "ok",
                    "response": validation.value["summary"],
                    "data": {
                        "skill_output": validation.value,
                        "skill_invocation": invocation_data,
                        "agent_state": serialized,
                    },
                    "error": None,
                }
            error_code = (
                "skill_output_contract_violation"
                if agent_state.stop_reason == "final_answer"
                else "skill_execution_incomplete"
            )
            return {
                "status": "incomplete" if agent_state.stop_reason == "max_iter" else "error",
                "response": None,
                "data": {
                    "skill_invocation": invocation_data,
                    "agent_state": serialized,
                },
                "error": {
                    "code": error_code,
                    "message": "Skill execution did not produce a valid contracted output",
                    "details": {"violations": list(validation.errors)},
                },
            }
        except Exception as error:
            return self._startup_failure(
                invocation_id,
                match,
                started_wall,
                (time.perf_counter() - started) * 1000,
                error,
            )

    def _build_loop(self, definition: SkillDefinition, tool_view: Any) -> AgentLoop:
        base = self.runner.loop
        return AgentLoop(
            base.model,
            tool_view,
            max_iter=base.max_iter,
            system_prompt=base.system_prompt + "\n\n" + definition.instructions,
            memory=base.memory,
            context_compressor=base.context_compressor,
        )

    @staticmethod
    def _runner_kwargs(state: dict[str, Any]) -> dict[str, Any]:
        return {
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

    @staticmethod
    def _invocation_status(stop_reason: str | None, contract_valid: bool) -> str:
        if stop_reason == "final_answer" and contract_valid:
            return "completed"
        if stop_reason == "max_iter":
            return "max_iter"
        if stop_reason == "needs_user_input":
            return "needs_input"
        if stop_reason == "final_answer":
            return "output_invalid"
        return "failed"

    @staticmethod
    def _invocation(
        invocation_id: str,
        definition: SkillDefinition,
        match: SkillMatch,
        *,
        status: str,
        started_at: str,
        duration_ms: float,
        agent_state: Any,
        contract_valid: bool,
        output_errors: tuple[dict[str, Any], ...],
    ) -> SkillInvocation:
        trace = tuple(
            {
                "callId": str(item.get("call_id", "")),
                "toolName": str(item.get("tool_name", "")),
                "success": bool(item.get("success")),
                "errorCode": (
                    item.get("error", {}).get("code")
                    if isinstance(item.get("error"), dict)
                    else None
                ),
                "duration": item.get("duration"),
                "truncated": bool(item.get("truncated")),
            }
            for item in agent_state.execution_trace
        )
        tools_used = tuple(
            dict.fromkeys(
                item["toolName"] for item in trace if item["toolName"]
            )
        )
        return SkillInvocation(
            invocation_id=invocation_id,
            skill_name=definition.name,
            skill_version=definition.version,
            trigger={
                "source": match.source,
                "rule": match.rule,
                "matchedText": match.matched_text,
            },
            status=status,
            allowed_tools=definition.allowed_tools,
            started_at=started_at,
            duration_ms=round(duration_ms, 3),
            agent_stop_reason=agent_state.stop_reason,
            iterations=agent_state.iteration,
            contract_valid=contract_valid,
            tools_used=tools_used,
            output_errors=tuple(copy.deepcopy(output_errors)),
            trace=trace,
        )

    def _startup_failure(
        self,
        invocation_id: str,
        match: SkillMatch,
        started_at: str,
        duration_ms: float,
        error: Exception,
    ) -> dict[str, Any]:
        invocation = {
            "invocation_id": invocation_id,
            "skill_name": match.name,
            "skill_version": "unknown",
            "trigger": {
                "source": match.source,
                "rule": match.rule,
                "matchedText": match.matched_text,
            },
            "status": "failed",
            "allowed_tools": (),
            "started_at": started_at,
            "duration_ms": round(duration_ms, 3),
            "agent_stop_reason": None,
            "iterations": 0,
            "contract_valid": False,
            "tools_used": (),
            "output_errors": (),
            "trace": (),
        }
        self.invocations.append(copy.deepcopy(invocation))
        return {
            "status": "error",
            "response": None,
            "data": {"skill_invocation": invocation},
            "error": {
                "code": "skill_runtime_error",
                "message": "Skill could not be loaded or started",
                "details": {"errorType": type(error).__name__},
            },
        }
