"""Main-agent ToolDefinition for the single data-check delegation scenario."""

from __future__ import annotations

import re
from typing import Any

from guardrails import ToolGuardrailPolicy
from tools.registry import ToolDefinition, ToolExecutionError

from .contracts import SubAgentLimits
from .registry import DELEGATE_TOOL_NAME
from .runner import DataCheckSubAgentRunner


def data_check_delegate_definition(
    model: Any,
    source_registry: Any,
    *,
    limits: SubAgentLimits | None = None,
    context_compressor: Any | None = None,
) -> ToolDefinition:
    active_limits = limits or SubAgentLimits()
    runner = DataCheckSubAgentRunner(
        model,
        source_registry,
        limits=active_limits,
        context_compressor=context_compressor,
    )

    def handler(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
        current_calls = context.get("current_tool_calls", [])
        if current_calls.count(DELEGATE_TOOL_NAME) >= 1:
            raise ToolExecutionError(
                "delegation_budget_exceeded",
                "Only one Sub-agent delegation is allowed per main Agent run",
                {"maxDelegations": 1},
                recoverable=False,
            )
        dataset_registry = context.get("dataset_registry")
        if dataset_registry is None:
            raise ToolExecutionError(
                "dataset_registry_required",
                "Sub-agent delegation requires DatasetRegistry",
                recoverable=False,
            )
        dataset_id = arguments["datasetId"]
        active_ids = context.get("active_dataset_ids")
        if not isinstance(active_ids, list) or dataset_id not in active_ids:
            raise ToolExecutionError(
                "inactive_dataset",
                f"dataset is not active in the current conversation: {dataset_id}",
            )
        if not dataset_registry.contains(dataset_id):
            raise ToolExecutionError("dataset_not_found", f"unknown dataset: {dataset_id}")
        call_id = str(context.get("call_id") or "delegate")
        safe_call_id = re.sub(r"[^a-zA-Z0-9_-]", "_", call_id)[:64]
        return runner.run(
            subtask_id=f"sub_{safe_call_id}",
            task=arguments["task"],
            dataset_id=dataset_id,
            dataset_registry=dataset_registry,
            metric=arguments.get("metric"),
            trace_collector=context.get("_trace_collector"),
        )

    return ToolDefinition(
        name=DELEGATE_TOOL_NAME,
        description=(
            "Delegate one bounded, read-only data inspection or quality-check subtask. "
            "The Sub-agent has isolated context and only inspect_data, basic_stats, "
            "and detect_anomaly. Use at most once, then integrate its structured evidence."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": active_limits.max_task_chars,
                },
                "datasetId": {"type": "string", "minLength": 1, "maxLength": 128},
                "metric": {"type": "string", "minLength": 1, "maxLength": 128},
            },
            "required": ["task", "datasetId"],
            "additionalProperties": False,
        },
        handler=handler,
        timeout_seconds=active_limits.timeout_seconds,
        max_result_bytes=active_limits.max_result_bytes,
        guardrail_policy=ToolGuardrailPolicy(
            action_type="subagent_read",
            risk_level="low",
            tool_kind="subagent",
        ),
    )
