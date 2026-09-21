from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from agent import AgentLoop
from mcp_adapter import MCPHost, MCPStdioClient
from tools import build_default_registry


SERVER_PATH = Path(__file__).resolve().parent / "fixtures" / "mcp_stdio_server.py"


class ScriptedModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del tools
        self.calls += 1
        if self.calls == 1:
            return {
                "type": "tool_call",
                "id": "stdio-echo-1",
                "name": "mcp_stdio__echo",
                "arguments": {"text": "from-agent"},
            }
        observation = json.loads(messages[-1]["content"])
        if not observation["ok"]:
            raise AssertionError(observation)
        return {"type": "final_answer", "content": "stdio MCP complete"}


class MCPStdioSDKTests(unittest.TestCase):
    def build_client(self, marker: Path | None = None) -> MCPStdioClient:
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        if marker is not None:
            environment["MCP_CANCEL_MARKER"] = str(marker)
        return MCPStdioClient(
            sys.executable,
            args=[str(SERVER_PATH)],
            env=environment,
            cwd=SERVER_PATH.parent.parent.parent,
        )

    def test_real_stdio_server_reuses_adapter_and_agent_loop(self) -> None:
        registry = build_default_registry()
        client = self.build_client()
        host = MCPHost(registry)
        try:
            report = host.attach_server(
                client,
                server_id="stdio",
                allowed_tools={"echo", "slow_echo"},
            )
            self.assertTrue(report.ok, report.error)
            self.assertEqual(
                report.registered_tools,
                ("mcp_stdio__echo", "mcp_stdio__slow_echo"),
            )

            direct = registry.execute("mcp_stdio__echo", {"text": "direct"})
            self.assertTrue(direct["ok"], direct)
            self.assertEqual(direct["data"]["structuredContent"], {"echo": "direct"})

            state = AgentLoop(ScriptedModel(), registry).run("call real stdio MCP")
            self.assertEqual(state.stop_reason, "final_answer")
            self.assertEqual(state.final_answer, "stdio MCP complete")
            self.assertEqual(state.execution_trace[0]["tool_name"], "mcp_stdio__echo")
            self.assertTrue(state.execution_trace[0]["success"])
        finally:
            host.close()

    def test_adapter_timeout_cancels_underlying_sdk_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "cancelled.txt"
            registry = build_default_registry()
            client = self.build_client(marker)
            host = MCPHost(registry)
            try:
                report = host.attach_server(
                    client,
                    server_id="stdio",
                    allowed_tools={"echo", "slow_echo"},
                    call_timeout_seconds=0.5,
                )
                self.assertTrue(report.ok, report.error)

                started = time.perf_counter()
                result = registry.execute(
                    "mcp_stdio__slow_echo",
                    {"text": "late", "delay_seconds": 5.0},
                )
                self.assertLess(time.perf_counter() - started, 1.5)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "mcp_timeout")

                deadline = time.monotonic() + 3.0
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(marker.exists(), "stdio Server did not observe cancellation")
                self.assertIn("Cancel", marker.read_text(encoding="utf-8"))

                follow_up = registry.execute("mcp_stdio__echo", {"text": "still-alive"})
                self.assertTrue(follow_up["ok"], follow_up)
            finally:
                host.close()


if __name__ == "__main__":
    unittest.main()
