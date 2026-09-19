"""Controlled subprocess bridge for deterministic multi-file operations."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BRIDGE = ROOT / "src" / "multifile_bridge.js"


class MultiFileBridgeError(RuntimeError):
    def __init__(
        self, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class MultiFileBridge:
    def __init__(
        self, node_binary: str | None = None, bridge_path: Path | None = None
    ) -> None:
        self.node_binary = node_binary or shutil.which("node") or "node"
        self.bridge_path = bridge_path or DEFAULT_BRIDGE

    def summarize(self, dataset: str) -> dict[str, Any]:
        return self._execute({"action": "summarize", "dataset": dataset})

    def inspect_merge(
        self,
        *,
        left_path: str,
        right_path: str,
        left_key: str,
        right_key: str,
        join_type: str,
    ) -> dict[str, Any]:
        return self._execute(
            {
                "action": "inspect_merge",
                "leftPath": left_path,
                "rightPath": right_path,
                "leftKey": left_key,
                "rightKey": right_key,
                "joinType": join_type,
            }
        )

    def merge(
        self,
        *,
        left_path: str,
        right_path: str,
        left_key: str,
        right_key: str,
        join_type: str,
        expected_plan_fingerprint: str,
        output_path: str,
    ) -> dict[str, Any]:
        return self._execute(
            {
                "action": "merge",
                "leftPath": left_path,
                "rightPath": right_path,
                "leftKey": left_key,
                "rightKey": right_key,
                "joinType": join_type,
                "expectedPlanFingerprint": expected_plan_fingerprint,
                "outputPath": output_path,
            }
        )

    def _execute(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            process = subprocess.run(
                [self.node_binary, str(self.bridge_path)],
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30.0,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise MultiFileBridgeError("tool_timeout", "multi-file operation timed out") from error
        except OSError as error:
            raise MultiFileBridgeError(
                "bridge_unavailable", "multi-file bridge is unavailable"
            ) from error
        try:
            response = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise MultiFileBridgeError(
                "invalid_bridge_response", "multi-file bridge did not return JSON"
            ) from error
        if not isinstance(response, dict):
            raise MultiFileBridgeError(
                "invalid_bridge_response", "multi-file bridge response must be an object"
            )
        if process.returncode != 0 or response.get("status") != "ok":
            details = response.get("error")
            if not isinstance(details, dict):
                details = {}
            raise MultiFileBridgeError(
                str(details.get("code", "multifile_error")),
                str(details.get("message", "multi-file operation failed")),
                {key: value for key, value in details.items() if key not in {"code", "message"}},
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise MultiFileBridgeError(
                "invalid_bridge_response", "multi-file bridge result must be an object"
            )
        return result
