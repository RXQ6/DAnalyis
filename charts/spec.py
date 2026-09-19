"""Build small chart specifications from existing analysis tool results."""

from __future__ import annotations

import math
from typing import Any


MAX_CHART_POINTS = 100
SUPPORTED_SOURCES = {
    "group_compare": "bar",
    "normalize_share": "bar",
    "top_n": "bar",
    "compare_datasets": "bar",
    "trend_analysis": "line",
    "scatter_data": "scatter",
}


class ChartSpecError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


def build_chart_spec(
    *,
    source_call_id: str,
    source_tool: str,
    source_data: dict[str, Any],
    chart_type: str,
    title: str | None = None,
) -> dict[str, Any]:
    """Map a successful analysis result to a validated, renderer-neutral spec."""
    expected_type = SUPPORTED_SOURCES.get(source_tool)
    if expected_type is None:
        raise ChartSpecError(
            "unsupported_chart_source",
            f"tool result cannot be charted in the first chart version: {source_tool}",
            {"sourceTool": source_tool},
        )
    if chart_type != expected_type:
        raise ChartSpecError(
            "incompatible_chart_type",
            f"{source_tool} only supports {expected_type} charts",
            {
                "sourceTool": source_tool,
                "requestedChartType": chart_type,
                "supportedChartType": expected_type,
            },
        )

    if source_tool == "scatter_data":
        raw_values = source_data.get("points")
        x_title = _required_text(source_data, "xField")
        y_title = _required_text(source_data, "yField")
        x_type = "quantitative"
        values = _scatter_values(raw_values)
    elif source_tool in {"group_compare", "normalize_share", "compare_datasets"}:
        raw_values = source_data.get("groups")
        x_key = "group"
        x_title = _required_text(source_data, "groupBy")
        x_type = "nominal"
    elif source_tool == "top_n":
        raw_values = source_data.get("items")
        x_key = "label"
        x_title = "项目"
        x_type = "nominal"
    else:
        raw_values = source_data.get("points")
        x_key = "date"
        x_title = _required_text(source_data, "dateField")
        x_type = "temporal"

    metric = _required_text(source_data, "metric")
    operation = source_data.get("operation")
    if operation is not None and not isinstance(operation, str):
        raise ChartSpecError("invalid_chart_source", "source operation must be text")
    if source_tool != "scatter_data":
        values = _chart_values(raw_values, x_key)
        y_title = metric
    if not values:
        raise ChartSpecError("insufficient_chart_data", "chart source contains no points")
    if len(values) > MAX_CHART_POINTS:
        raise ChartSpecError(
            "too_many_chart_points",
            f"chart source exceeds the {MAX_CHART_POINTS}-point limit",
            {"pointCount": len(values), "maximum": MAX_CHART_POINTS},
        )

    chart_title = title.strip() if isinstance(title, str) and title.strip() else _default_title(
        source_tool, metric, operation, x_title
    )
    return {
        "version": "1.0",
        "chartType": chart_type,
        "title": chart_title,
        "data": {"values": values},
        "encoding": {
            "x": {"field": "x", "type": x_type, "title": x_title},
            "y": {"field": "y", "type": "quantitative", "title": y_title},
        },
        "meta": {
            "sourceCallId": source_call_id,
            "sourceTool": source_tool,
            "metric": metric,
            "operation": operation,
            "pointCount": len(values),
        },
    }


def _chart_values(raw_values: Any, x_key: str) -> list[dict[str, Any]]:
    if not isinstance(raw_values, list):
        raise ChartSpecError("invalid_chart_source", "source result has no chartable series")
    values = []
    for index, item in enumerate(raw_values):
        if not isinstance(item, dict):
            raise ChartSpecError(
                "invalid_chart_source", f"source point {index} must be an object"
            )
        x_value = item.get(x_key)
        y_value = item.get("value")
        if x_value is None or isinstance(x_value, (dict, list)):
            raise ChartSpecError(
                "invalid_chart_source", f"source point {index} has an invalid x value"
            )
        if (
            isinstance(y_value, bool)
            or not isinstance(y_value, (int, float))
            or not math.isfinite(y_value)
        ):
            raise ChartSpecError(
                "invalid_chart_source", f"source point {index} has an invalid numeric value"
            )
        values.append({"x": str(x_value), "y": y_value})
    return values


def _scatter_values(raw_values: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_values, list):
        raise ChartSpecError("invalid_chart_source", "scatter source has no points")
    values = []
    for index, item in enumerate(raw_values):
        x_value = item.get("x") if isinstance(item, dict) else None
        y_value = item.get("y") if isinstance(item, dict) else None
        for axis, value in (("x", x_value), ("y", y_value)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ChartSpecError("invalid_chart_source", f"scatter point {index} has invalid {axis}")
        values.append({"x": x_value, "y": y_value})
    return values


def _required_text(source_data: dict[str, Any], key: str) -> str:
    value = source_data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ChartSpecError("invalid_chart_source", f"source result is missing {key}")
    return value


def _default_title(
    source_tool: str, metric: str, operation: str | None, x_title: str
) -> str:
    operation_label = {
        "sum": "总和",
        "average": "平均值",
        "count": "计数",
        "minimum": "最小值",
        "maximum": "最大值",
    }.get(operation or "", operation or "")
    if source_tool == "trend_analysis":
        return f"{metric}{operation_label}趋势"
    if source_tool == "scatter_data":
        return f"{x_title}与{metric}散点图"
    if source_tool == "top_n":
        return f"{metric}排名"
    return f"按{x_title}统计{metric}{operation_label}"
