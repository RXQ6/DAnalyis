"""Registry entries backed by the existing deterministic Node analysis modules."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .registry import ToolDefinition, ToolExecutionError, ToolRegistry
from .todo import todo_definition


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BRIDGE = ROOT / "src" / "tool_bridge.js"
DEFAULT_CATALOG = ROOT / "tools" / "catalog.json"


class NodeToolBridge:
    def __init__(self, node_binary: str | None = None, bridge_path: Path | None = None) -> None:
        self.node_binary = node_binary or shutil.which("node") or "node"
        self.bridge_path = bridge_path or DEFAULT_BRIDGE

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
        *,
        timeout_seconds: float = 30.0,
    ) -> Any:
        dataset = context.get("dataset")
        if not dataset:
            raise ToolExecutionError(
                "missing_dataset",
                "a dataset is required for this tool",
                recoverable=False,
            )
        request = {"tool": name, "dataset": dataset, "arguments": arguments}
        try:
            process = subprocess.run(
                [self.node_binary, str(self.bridge_path)],
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ToolExecutionError(
                "tool_timeout",
                f"tool execution exceeded {timeout_seconds:g} seconds",
                {"timeoutSeconds": timeout_seconds},
            ) from error
        except OSError as error:
            raise ToolExecutionError(
                "bridge_unavailable",
                "tool bridge is unavailable",
                {"exceptionType": type(error).__name__},
                recoverable=False,
            ) from error
        try:
            response = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise ToolExecutionError(
                "invalid_bridge_response",
                "tool bridge did not return JSON",
                recoverable=False,
            ) from error
        if not isinstance(response, dict):
            raise ToolExecutionError(
                "invalid_bridge_response",
                "tool bridge response must be an object",
                recoverable=False,
            )
        if process.returncode != 0 or response.get("status") != "ok":
            details = response.get("error", {})
            if not isinstance(details, dict):
                details = {}
            error_details = {
                key: value for key, value in details.items() if key not in {"code", "message"}
            }
            raise ToolExecutionError(
                details.get("code", "tool_error"),
                details.get("message", "tool failed"),
                error_details,
            )
        if "result" not in response:
            raise ToolExecutionError(
                "invalid_bridge_response",
                "tool bridge response is missing result",
                recoverable=False,
            )
        return response["result"]


def _bridge_handler(bridge: NodeToolBridge, tool_name: str, timeout_seconds: float):
    """Bind one tool name without relying on a loop variable closure."""

    def handler(arguments: dict[str, Any], context: dict[str, Any]) -> Any:
        return bridge.execute(
            tool_name, arguments, context, timeout_seconds=timeout_seconds
        )

    return handler


def _load_catalog(catalog_path: Path) -> dict[str, Any]:
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to load tool catalog: {catalog_path}") from error
    tools = catalog.get("tools") if isinstance(catalog, dict) else None
    if not isinstance(tools, list):
        raise ValueError("tool catalog must contain a tools array")
    return catalog


def build_default_registry(
    *,
    node_binary: str | None = None,
    bridge_path: Path | None = None,
    catalog_path: Path | None = None,
    bridge: NodeToolBridge | None = None,
) -> ToolRegistry:
    active_bridge = bridge or NodeToolBridge(node_binary=node_binary, bridge_path=bridge_path)
    registry = ToolRegistry()
    catalog = _load_catalog(catalog_path or DEFAULT_CATALOG)
    defaults = catalog.get("executionDefaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("tool catalog executionDefaults must be an object")
    default_timeout = defaults.get("timeoutSeconds", 30.0)
    default_max_result = defaults.get("maxResultBytes", 64 * 1024)
    definitions = []
    for item in catalog["tools"]:
        if not isinstance(item, dict):
            raise ValueError("tool catalog entries must be objects")
        try:
            name = item["name"]
            description = item["description"]
            parameter_schema = item["parameters"]
        except KeyError as error:
            raise ValueError(f"tool catalog entry is missing {error.args[0]}") from error
        timeout_seconds = item.get("timeoutSeconds", default_timeout)
        max_result_bytes = item.get("maxResultBytes", default_max_result)
        definitions.append(
            ToolDefinition(
                name=name,
                description=description,
                parameter_schema=parameter_schema,
                handler=_bridge_handler(active_bridge, name, timeout_seconds),
                timeout_seconds=timeout_seconds,
                max_result_bytes=max_result_bytes,
            )
        )
    definitions.append(todo_definition())
    registry.register_many(definitions)
    return registry
