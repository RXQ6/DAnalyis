"""Registered chart tool backed only by prior successful ToolResults."""

from __future__ import annotations

from typing import Any

from guardrails import ToolGuardrailPolicy

from charts import ChartSpecError, build_chart_spec, render_svg

from .registry import ToolDefinition, ToolExecutionError


CHART_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sourceCallId": {"type": "string", "minLength": 1, "maxLength": 128},
        "chartType": {"type": "string", "enum": ["bar", "line", "scatter"]},
        "title": {"type": "string", "minLength": 1, "maxLength": 120},
    },
    "required": ["sourceCallId", "chartType"],
    "additionalProperties": False,
}


def _find_source(previous: list[Any], call_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in reversed(previous)
            if isinstance(item, dict) and item.get("callId") == call_id
        ),
        None,
    )


def _ensure_active_source(
    source: dict[str, Any],
    previous: list[Any],
    context: dict[str, Any],
    *,
    visited: set[str] | None = None,
) -> None:
    """Reject stale dataset lineage when conversation activity is enforced."""
    active = context.get("active_dataset_ids")
    if active is None:
        return
    active_ids = set(active)
    seen = visited or set()
    call_id = source.get("callId")
    if isinstance(call_id, str):
        if call_id in seen:
            raise ToolExecutionError("cyclic_tool_source", "tool source lineage contains a cycle")
        seen.add(call_id)
    arguments = source.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    dataset_id = arguments.get("datasetId")
    if isinstance(dataset_id, str) and dataset_id not in active_ids:
        raise ToolExecutionError(
            "inactive_tool_source",
            f"tool source uses an inactive dataset: {dataset_id}",
            {"datasetId": dataset_id, "sourceCallId": call_id},
        )
    referenced = []
    if isinstance(arguments.get("sourceCallId"), str):
        referenced.append(arguments["sourceCallId"])
    if isinstance(arguments.get("sourceCallIds"), list):
        referenced.extend(item for item in arguments["sourceCallIds"] if isinstance(item, str))
    for referenced_id in referenced:
        parent = _find_source(previous, referenced_id)
        if parent is None:
            raise ToolExecutionError(
                "tool_source_lineage_unavailable",
                f"source lineage call is unavailable: {referenced_id}",
                {"sourceCallId": referenced_id},
            )
        _ensure_active_source(parent, previous, context, visited=set(seen))


def generate_chart(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Create and render a chart without accepting model-supplied data values."""
    source_call_id = arguments["sourceCallId"]
    previous = context.get("previous_tool_results")
    if not isinstance(previous, list):
        raise ToolExecutionError(
            "chart_source_unavailable",
            "previous ToolResults are unavailable in the current Agent run",
        )
    source = _find_source(previous, source_call_id)
    if source is None:
        raise ToolExecutionError(
            "chart_source_not_found",
            f"no prior tool result exists for call id: {source_call_id}",
            {"sourceCallId": source_call_id},
        )
    _ensure_active_source(source, previous, context)
    tool_result = source.get("toolResult")
    if not isinstance(tool_result, dict):
        raise ToolExecutionError(
            "invalid_chart_source", "the referenced ToolResult is invalid"
        )
    if not tool_result.get("ok"):
        raise ToolExecutionError(
            "chart_source_failed",
            "a failed ToolResult cannot be charted",
            {"sourceCallId": source_call_id},
        )
    if tool_result.get("truncated"):
        raise ToolExecutionError(
            "chart_source_truncated",
            "a truncated ToolResult cannot be charted safely",
            {"sourceCallId": source_call_id},
        )
    source_data = tool_result.get("data")
    if not isinstance(source_data, dict):
        raise ToolExecutionError(
            "invalid_chart_source", "the referenced ToolResult data must be an object"
        )

    try:
        spec = build_chart_spec(
            source_call_id=source_call_id,
            source_tool=source.get("toolName", ""),
            source_data=source_data,
            chart_type=arguments["chartType"],
            title=arguments.get("title"),
        )
    except ChartSpecError as error:
        raise ToolExecutionError(error.code, str(error), error.details) from error

    artifact_dir = context.get("artifact_dir")
    if not artifact_dir:
        raise ToolExecutionError(
            "chart_output_unavailable",
            "a controlled artifact directory is required to render a chart",
        )
    try:
        artifact = render_svg(
            spec,
            artifact_dir=artifact_dir,
            artifact_name=str(context.get("call_id") or "chart"),
        )
    except (OSError, ValueError) as error:
        raise ToolExecutionError(
            "chart_render_failed",
            "chart rendering failed",
            {"exceptionType": type(error).__name__},
        ) from error
    return {"spec": spec, "artifact": artifact}


def normalize_share(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Normalize prior group totals into ratios without model-supplied values."""
    source_call_id = arguments["sourceCallId"]
    previous = context.get("previous_tool_results")
    if not isinstance(previous, list):
        raise ToolExecutionError("share_source_unavailable", "prior ToolResults are unavailable")
    source = _find_source(previous, source_call_id)
    if source is None:
        raise ToolExecutionError("share_source_not_found", f"source call does not exist: {source_call_id}")
    _ensure_active_source(source, previous, context)
    result = source.get("toolResult")
    if not isinstance(result, dict) or not result.get("ok"):
        raise ToolExecutionError("share_source_failed", "share source must be successful")
    if result.get("truncated"):
        raise ToolExecutionError("share_source_truncated", "a truncated source cannot be normalized")
    if source.get("toolName") != "group_compare":
        raise ToolExecutionError("unsupported_share_source", "share normalization requires group_compare")
    data = result.get("data")
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list) or not groups:
        raise ToolExecutionError("invalid_share_source", "share source has no groups")
    numeric_values: list[float] = []
    for index, item in enumerate(groups):
        value = item.get("value") if isinstance(item, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolExecutionError("invalid_share_source", f"group {index} has no numeric value")
        if value < 0:
            raise ToolExecutionError("negative_share_value", "share normalization does not accept negative values")
        numeric_values.append(float(value))
    total = sum(numeric_values)
    if total <= 0:
        raise ToolExecutionError("zero_share_total", "share normalization requires a positive total")
    metric = data.get("metric")
    group_by = data.get("groupBy")
    if not isinstance(metric, str) or not metric or not isinstance(group_by, str) or not group_by:
        raise ToolExecutionError("invalid_share_source", "share source is missing metric or groupBy")
    return {
        "groupBy": group_by,
        "metric": f"{metric}占比",
        "sourceMetric": metric,
        "operation": "share",
        "total": total,
        "groups": [
            {
                "group": item.get("group"),
                "value": value / total,
                "sourceValue": value,
                "validCount": item.get("validCount"),
            }
            for item, value in zip(groups, numeric_values, strict=True)
        ],
        "sourceCallId": source_call_id,
    }


def chart_definition() -> ToolDefinition:
    return ToolDefinition(
        name="generate_chart",
        description=(
            "Generate a bar, line, or scatter chart from a prior successful analysis ToolResult. "
            "Pass only its sourceCallId; never copy or recalculate data values. "
            "group_compare, normalize_share, top_n and compare_datasets support bar; "
            "trend_analysis supports line; scatter_data supports scatter."
        ),
        parameter_schema=CHART_SCHEMA,
        handler=generate_chart,
        timeout_seconds=10.0,
        guardrail_policy=ToolGuardrailPolicy(action_type="chart"),
    )


def share_definition() -> ToolDefinition:
    return ToolDefinition(
        name="normalize_share",
        description=(
            "Convert a prior group_compare ToolResult into deterministic category ratios. "
            "Pass only sourceCallId; never supply or calculate percentages in the model."
        ),
        parameter_schema={
            "type": "object",
            "properties": {"sourceCallId": {"type": "string", "minLength": 1, "maxLength": 128}},
            "required": ["sourceCallId"],
            "additionalProperties": False,
        },
        handler=normalize_share,
        timeout_seconds=5.0,
    )
