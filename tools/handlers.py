"""Registry entries backed by the existing deterministic Node analysis modules."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .registry import ToolDefinition, ToolExecutionError, ToolRegistry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BRIDGE = ROOT / "src" / "tool_bridge.js"


class NodeToolBridge:
    def __init__(self, node_binary: str | None = None, bridge_path: Path | None = None) -> None:
        self.node_binary = node_binary or shutil.which("node") or "node"
        self.bridge_path = bridge_path or DEFAULT_BRIDGE

    def execute(self, name: str, arguments: dict[str, Any], context: dict[str, Any]) -> Any:
        dataset = context.get("dataset")
        if not dataset:
            raise ToolExecutionError("missing_dataset", "a dataset is required for this tool")
        request = {"tool": name, "dataset": dataset, "arguments": arguments}
        try:
            process = subprocess.run(
                [self.node_binary, str(self.bridge_path)],
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ToolExecutionError("bridge_unavailable", str(error)) from error
        try:
            response = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise ToolExecutionError("invalid_bridge_response", "tool bridge did not return JSON") from error
        if process.returncode != 0 or response.get("status") != "ok":
            details = response.get("error", {})
            raise ToolExecutionError(details.get("code", "tool_error"), details.get("message", "tool failed"))
        return response["result"]


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def build_default_registry(
    *, node_binary: str | None = None, bridge_path: Path | None = None
) -> ToolRegistry:
    bridge = NodeToolBridge(node_binary=node_binary, bridge_path=bridge_path)
    registry = ToolRegistry()
    definitions = [
        ("inspect_data", "Inspect columns, types, missing values and row count.", _schema({}, [])),
        ("basic_stats", "Calculate sum, average, count, minimum or maximum for one field.", _schema({"metric": {"type": "string"}, "operation": {"type": "string", "enum": ["sum", "average", "count", "minimum", "maximum"]}}, ["metric", "operation"])),
        ("group_compare", "Aggregate a numeric metric by a category.", _schema({"groupBy": {"type": "string"}, "metric": {"type": "string"}, "operation": {"type": "string", "enum": ["sum", "average", "count", "minimum", "maximum"]}}, ["groupBy", "metric", "operation"])),
        ("trend_analysis", "Aggregate a numeric metric over a date field; optional equality filters narrow the rows.", _schema({"dateField": {"type": "string"}, "metric": {"type": "string"}, "operation": {"type": "string", "enum": ["sum", "average", "count", "minimum", "maximum"]}, "filters": {"type": "object"}}, ["dateField", "metric", "operation"])),
        ("detect_anomaly", "Detect numeric outliers using the deterministic 1.5 IQR rule.", _schema({"metric": {"type": "string"}}, ["metric"])),
        ("top_n", "Return the highest N records for a numeric metric.", _schema({"metric": {"type": "string"}, "label": {"type": "string"}, "count": {"type": "integer"}}, ["metric", "count"])),
    ]
    for name, description, parameter_schema in definitions:
        registry.register(
            ToolDefinition(
                name=name,
                description=description,
                parameter_schema=parameter_schema,
                handler=lambda arguments, context, tool_name=name: bridge.execute(tool_name, arguments, context),
            )
        )
    return registry

