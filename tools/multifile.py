"""Registered deterministic tools for task-scoped multi-file analysis."""

from __future__ import annotations

import math
from typing import Any

from datasets import DatasetRegistryError, MultiFileBridge
from datasets.bridge import MultiFileBridgeError

from .registry import ToolDefinition, ToolExecutionError


DATASET_ID = {"type": "string", "minLength": 4, "maxLength": 67}


def _registry(context: dict[str, Any]) -> Any:
    registry = context.get("dataset_registry")
    if registry is None:
        raise ToolExecutionError(
            "dataset_registry_unavailable",
            "a DatasetRegistry is required for multi-file tools",
            recoverable=False,
        )
    return registry


def _tool_error(error: Exception) -> ToolExecutionError:
    return ToolExecutionError(
        getattr(error, "code", "multifile_error"),
        str(error),
        getattr(error, "details", {}),
    )


def _active_ids(context: dict[str, Any]) -> list[str] | None:
    active = context.get("active_dataset_ids")
    return None if active is None else list(active)


def _require_active(dataset_id: str, context: dict[str, Any]) -> None:
    active = _active_ids(context)
    if active is not None and dataset_id not in active:
        raise ToolExecutionError(
            "inactive_dataset",
            f"dataset is not active in the current conversation: {dataset_id}",
        )


def list_datasets(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del arguments
    summaries = _registry(context).list_summaries(_active_ids(context))
    return {"datasetCount": len(summaries), "datasets": summaries}


def inspect_dataset(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        _require_active(arguments["datasetId"], context)
        return _registry(context).summary(arguments["datasetId"])
    except DatasetRegistryError as error:
        raise _tool_error(error) from error


def compare_datasets(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    call_ids = arguments["sourceCallIds"]
    if len(call_ids) < 2 or len(call_ids) > 10 or len(call_ids) != len(set(call_ids)):
        raise ToolExecutionError(
            "invalid_arguments", "sourceCallIds must contain 2-10 unique call ids"
        )
    previous = context.get("previous_tool_results")
    if not isinstance(previous, list):
        raise ToolExecutionError(
            "comparison_source_unavailable", "prior ToolResults are unavailable"
        )
    registry = _registry(context)
    sources = []
    for call_id in call_ids:
        source = next(
            (
                item
                for item in reversed(previous)
                if isinstance(item, dict) and item.get("callId") == call_id
            ),
            None,
        )
        if source is None:
            raise ToolExecutionError(
                "comparison_source_not_found", f"source call does not exist: {call_id}"
            )
        result = source.get("toolResult")
        if not isinstance(result, dict) or not result.get("ok"):
            raise ToolExecutionError(
                "comparison_source_failed", f"source call did not succeed: {call_id}"
            )
        if result.get("truncated"):
            raise ToolExecutionError(
                "comparison_source_truncated", f"source call is truncated: {call_id}"
            )
        source_tool = source.get("toolName")
        if source_tool not in {"basic_stats", "group_compare"}:
            raise ToolExecutionError(
                "unsupported_comparison_source",
                "comparison accepts basic_stats or group_compare ToolResults",
            )
        data = result.get("data")
        call_arguments = source.get("arguments")
        if not isinstance(data, dict) or not isinstance(call_arguments, dict):
            raise ToolExecutionError("invalid_comparison_source", "source is invalid")
        dataset_id = call_arguments.get("datasetId")
        if not isinstance(dataset_id, str):
            raise ToolExecutionError(
                "comparison_dataset_missing", "source call has no datasetId"
            )
        try:
            _require_active(dataset_id, context)
            summary = registry.summary(dataset_id)
        except DatasetRegistryError as error:
            raise _tool_error(error) from error
        sources.append(
            {
                "callId": call_id,
                "sourceTool": source_tool,
                "datasetId": dataset_id,
                "filename": summary["filename"],
                "metric": data.get("metric"),
                "operation": data.get("operation"),
                "value": data.get("value"),
                "validCount": data.get("validCount"),
                "groupBy": data.get("groupBy"),
                "groups": data.get("groups"),
            }
        )
    if len({item["datasetId"] for item in sources}) != len(sources):
        raise ToolExecutionError(
            "duplicate_comparison_dataset", "each source must use a different dataset"
        )
    source_tools = {item["sourceTool"] for item in sources}
    if len(source_tools) != 1:
        raise ToolExecutionError(
            "incompatible_comparison_sources",
            "all sources must use the same analysis tool",
        )
    source_tool = source_tools.pop()
    signatures = {(item["metric"], item["operation"]) for item in sources}
    if len(signatures) != 1:
        raise ToolExecutionError(
            "incompatible_comparison_sources",
            "all sources must use the same metric and operation",
        )
    metric, operation = signatures.pop()
    if source_tool == "group_compare":
        if arguments.get("comparisonMode", "values") != "values":
            raise ToolExecutionError(
                "incompatible_comparison_mode",
                "year_over_year mode only accepts basic_stats sources",
            )
        group_dimensions = {item["groupBy"] for item in sources}
        if len(group_dimensions) != 1 or not next(iter(group_dimensions), None):
            raise ToolExecutionError(
                "incompatible_comparison_sources",
                "all grouped sources must use the same groupBy dimension",
            )
        group_by = group_dimensions.pop()
        dataset_groups = []
        category_order: list[str] = []
        for source in sources:
            raw_groups = source["groups"]
            if not isinstance(raw_groups, list):
                raise ToolExecutionError("invalid_comparison_source", "group source has no groups")
            mapped: dict[str, dict[str, Any]] = {}
            for item in raw_groups:
                group = item.get("group") if isinstance(item, dict) else None
                value = item.get("value") if isinstance(item, dict) else None
                if group is None or isinstance(group, (dict, list)):
                    raise ToolExecutionError("invalid_comparison_source", "group label is invalid")
                key = str(group)
                if key in mapped:
                    raise ToolExecutionError("duplicate_comparison_group", f"duplicate group: {key}")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ToolExecutionError("invalid_comparison_source", f"group {key} has invalid value")
                mapped[key] = {"value": value, "validCount": item.get("validCount")}
                if key not in category_order:
                    category_order.append(key)
            dataset_groups.append(mapped)
        categories = []
        for group in category_order:
            values = []
            for source, mapped in zip(sources, dataset_groups, strict=True):
                point = mapped.get(group)
                values.append(
                    {
                        "datasetId": source["datasetId"],
                        "filename": source["filename"],
                        "value": None if point is None else point["value"],
                        "validCount": None if point is None else point["validCount"],
                        "missing": point is None,
                    }
                )
            categories.append({"group": group, "values": values})
        return {
            "groupBy": group_by,
            "metric": metric,
            "operation": operation,
            "comparisonMode": "group_compare",
            "datasets": [
                {"datasetId": item["datasetId"], "filename": item["filename"]}
                for item in sources
            ],
            "categories": categories,
            "sourceCallIds": list(call_ids),
        }

    output = {
        "groupBy": "dataset",
        "metric": metric,
        "operation": operation,
        "groups": [
            {
                "group": item["filename"],
                "datasetId": item["datasetId"],
                "value": item["value"],
                "validCount": item["validCount"],
            }
            for item in sources
        ],
        "sourceCallIds": list(call_ids),
    }
    if arguments.get("comparisonMode", "values") == "year_over_year":
        if len(sources) != 2:
            raise ToolExecutionError("invalid_year_over_year_sources", "year-over-year comparison requires exactly two sources")
        baseline, current = sources
        for item in (baseline, current):
            value = item["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ToolExecutionError("missing_comparison_value", "year-over-year source value is missing or invalid")
        absolute_change = current["value"] - baseline["value"]
        output.update(
            {
                "comparisonMode": "year_over_year",
                "baselineDatasetId": baseline["datasetId"],
                "currentDatasetId": current["datasetId"],
                "absoluteChange": absolute_change,
                "yearOverYearRate": None if baseline["value"] == 0 else absolute_change / baseline["value"],
                "yearOverYearPercent": None if baseline["value"] == 0 else absolute_change / baseline["value"] * 100,
                "yearOverYearStatus": "undefined_zero_baseline" if baseline["value"] == 0 else "ok",
            }
        )
    return output


def inspect_merge(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    registry = _registry(context)
    _require_active(arguments["leftDatasetId"], context)
    _require_active(arguments["rightDatasetId"], context)
    if arguments["leftDatasetId"] == arguments["rightDatasetId"]:
        raise ToolExecutionError(
            "same_merge_dataset", "left and right datasets must be different"
        )
    try:
        left_path = registry.resolve(arguments["leftDatasetId"])
        right_path = registry.resolve(arguments["rightDatasetId"])
        plan = registry.bridge.inspect_merge(
            left_path=left_path,
            right_path=right_path,
            left_key=arguments["leftKey"],
            right_key=arguments["rightKey"],
            join_type=arguments["joinType"],
        )
    except (DatasetRegistryError, MultiFileBridgeError) as error:
        raise _tool_error(error) from error
    return {
        "leftDatasetId": arguments["leftDatasetId"],
        "rightDatasetId": arguments["rightDatasetId"],
        **plan,
    }


def merge_datasets(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    previous = context.get("previous_tool_results")
    preflight_call_id = arguments["preflightCallId"]
    if not isinstance(previous, list):
        raise ToolExecutionError("merge_preflight_unavailable", "prior ToolResults are unavailable")
    source = next(
        (
            item
            for item in reversed(previous)
            if isinstance(item, dict) and item.get("callId") == preflight_call_id
        ),
        None,
    )
    if source is None or source.get("toolName") != "inspect_merge":
        raise ToolExecutionError(
            "merge_preflight_not_found", "merge requires an inspect_merge ToolResult"
        )
    result = source.get("toolResult")
    if not isinstance(result, dict) or not result.get("ok") or result.get("truncated"):
        raise ToolExecutionError(
            "invalid_merge_preflight", "merge preflight must be successful and complete"
        )
    plan = result.get("data")
    if not isinstance(plan, dict):
        raise ToolExecutionError("invalid_merge_preflight", "merge preflight data is invalid")
    if not plan.get("safeToExecute"):
        raise ToolExecutionError(
            "unsafe_merge_plan",
            "merge is blocked because the preflight found type or cardinality risks",
            {"risks": plan.get("risks", []), "cardinality": plan.get("cardinality")},
        )

    registry = _registry(context)
    output_path = registry.output_path("merged")
    try:
        left_path = registry.resolve(plan["leftDatasetId"])
        right_path = registry.resolve(plan["rightDatasetId"])
        merged = registry.bridge.merge(
            left_path=left_path,
            right_path=right_path,
            left_key=plan["leftKey"],
            right_key=plan["rightKey"],
            join_type=plan["joinType"],
            expected_plan_fingerprint=plan["planFingerprint"],
            output_path=str(output_path),
        )
        summary = registry.register_derived(
            output_path,
            filename=output_path.name,
            lineage={
                "operation": "merge",
                "leftDatasetId": plan["leftDatasetId"],
                "rightDatasetId": plan["rightDatasetId"],
                "leftKey": plan["leftKey"],
                "rightKey": plan["rightKey"],
                "joinType": plan["joinType"],
                "preflightCallId": preflight_call_id,
            },
        )
    except (DatasetRegistryError, MultiFileBridgeError) as error:
        raise _tool_error(error) from error
    return {"dataset": summary, "rowCount": merged["rowCount"], "preflightCallId": preflight_call_id}


def multifile_definitions(*, bridge: MultiFileBridge | None = None) -> list[ToolDefinition]:
    del bridge
    empty_schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    return [
        ToolDefinition("list_datasets", "List safe summaries for all task datasets; returns no raw rows or paths.", empty_schema, list_datasets),
        ToolDefinition(
            "inspect_dataset",
            "Inspect one registered dataset summary by datasetId without returning raw rows.",
            {"type": "object", "properties": {"datasetId": DATASET_ID}, "required": ["datasetId"], "additionalProperties": False},
            inspect_dataset,
        ),
        ToolDefinition(
            "compare_datasets",
            "Compare 2-10 prior basic_stats or group_compare ToolResults; optionally calculate a deterministic two-source year-over-year rate.",
            {"type": "object", "properties": {"sourceCallIds": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 128}}, "comparisonMode": {"type": "string", "enum": ["values", "year_over_year"]}}, "required": ["sourceCallIds"], "additionalProperties": False},
            compare_datasets,
        ),
        ToolDefinition(
            "inspect_merge",
            "Preflight a controlled two-dataset join: validate keys, types, duplicates, cardinality and estimated rows.",
            {
                "type": "object",
                "properties": {
                    "leftDatasetId": DATASET_ID,
                    "rightDatasetId": DATASET_ID,
                    "leftKey": {"type": "string", "minLength": 1, "maxLength": 200},
                    "rightKey": {"type": "string", "minLength": 1, "maxLength": 200},
                    "joinType": {"type": "string", "enum": ["inner", "left"]},
                },
                "required": ["leftDatasetId", "rightDatasetId", "leftKey", "rightKey", "joinType"],
                "additionalProperties": False,
            },
            inspect_merge,
        ),
        ToolDefinition(
            "merge_datasets",
            "Execute a safe one-to-one merge from a successful inspect_merge ToolResult and register the derived dataset.",
            {"type": "object", "properties": {"preflightCallId": {"type": "string", "minLength": 1, "maxLength": 128}}, "required": ["preflightCallId"], "additionalProperties": False},
            merge_datasets,
        ),
    ]
