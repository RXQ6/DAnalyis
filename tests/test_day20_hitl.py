from __future__ import annotations

import json
import unittest
from typing import Any

from agent import AgentLoop
from eval_harness import EvalCase, EvalRunner
from hitl import ApprovalManager
from mcp_adapter import MCPToolAdapter, MockMCPClient, MockMCPServer
from tools import ToolRegistry


class ScriptedModel:
    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del messages, tools
        return {
            "type": "tool_call",
            "id": "write-1",
            "name": "mcp_mock__echo",
            "arguments": {"text": "private-payload"},
        }


class HITLApprovalTests(unittest.TestCase):
    def _pending(
        self, *, manager: ApprovalManager | None = None
    ) -> tuple[AgentLoop, Any, MockMCPServer]:
        registry = ToolRegistry(approval_manager=manager)
        server = MockMCPServer()
        report = MCPToolAdapter(
            MockMCPClient(server),
            server_id="mock",
            allowed_tools={"echo"},
            tool_policies={"echo": "mcp_write"},
        ).register_into(registry)
        self.assertTrue(report.ok)
        loop = AgentLoop(ScriptedModel(), registry)
        state = loop.run("执行外部写操作")
        return loop, state, server

    def test_pending_created_without_sensitive_arguments(self) -> None:
        _loop, state, server = self._pending()
        self.assertEqual(state.stop_reason, "needs_approval")
        self.assertEqual(state.pending_approval["status"], "pending")
        self.assertEqual(state.pending_approval["call_id"], "write-1")
        public = json.dumps(state.pending_approval, ensure_ascii=False)
        self.assertNotIn("private-payload", public)
        self.assertNotIn("arguments", state.pending_approval)
        self.assertEqual(server.calls, [])

    def test_approve_resumes_exact_action_once(self) -> None:
        loop, state, server = self._pending()
        pending = dict(state.pending_approval)
        result = loop.resume_approval(
            state,
            approval_id=pending["approval_id"],
            action_hash=pending["action_hash"],
            decision="approve",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.decision.status, "approved")
        self.assertEqual(
            server.calls,
            [{"name": "echo", "arguments": {"text": "private-payload"}}],
        )
        self.assertEqual(state.stop_reason, "approval_executed")
        self.assertTrue(state.execution_trace[-1]["success"])

    def test_reject_never_executes_action(self) -> None:
        loop, state, server = self._pending()
        pending = dict(state.pending_approval)
        result = loop.resume_approval(
            state,
            approval_id=pending["approval_id"],
            action_hash=pending["action_hash"],
            decision="reject",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.decision.status, "rejected")
        self.assertEqual(server.calls, [])
        self.assertEqual(state.stop_reason, "approval_rejected")

    def test_expired_never_executes_action(self) -> None:
        now = [1000.0]
        manager = ApprovalManager(ttl_seconds=5, clock=lambda: now[0])
        loop, state, server = self._pending(manager=manager)
        pending = dict(state.pending_approval)
        now[0] = 1006.0
        result = loop.resume_approval(
            state,
            approval_id=pending["approval_id"],
            action_hash=pending["action_hash"],
            decision="approve",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.decision.status, "expired")
        self.assertEqual(server.calls, [])
        self.assertEqual(state.stop_reason, "approval_expired")

    def test_action_hash_mismatch_invalidates_approval(self) -> None:
        loop, state, server = self._pending()
        pending = dict(state.pending_approval)
        mismatch = loop.resume_approval(
            state,
            approval_id=pending["approval_id"],
            action_hash="changed-action-hash",
            decision="approve",
        )
        self.assertFalse(mismatch.ok)
        self.assertEqual(mismatch.error["code"], "approval_action_mismatch")
        retry = loop.registry.resolve_approval(
            approval_id=pending["approval_id"],
            action_hash=pending["action_hash"],
            decision="approve",
        )
        self.assertFalse(retry.ok)
        self.assertEqual(retry.error["code"], "approval_rejected")
        self.assertEqual(server.calls, [])

    def test_approval_replay_is_rejected(self) -> None:
        loop, state, server = self._pending()
        pending = dict(state.pending_approval)
        first = loop.resume_approval(
            state,
            approval_id=pending["approval_id"],
            action_hash=pending["action_hash"],
            decision="approve",
        )
        replay = loop.registry.resolve_approval(
            approval_id=pending["approval_id"],
            action_hash=pending["action_hash"],
            decision="approve",
        )
        self.assertTrue(first.ok)
        self.assertFalse(replay.ok)
        self.assertEqual(replay.error["code"], "approval_already_consumed")
        self.assertEqual(len(server.calls), 1)

    def test_approval_trace_preserves_identity(self) -> None:
        loop, state, _server = self._pending()
        pending = dict(state.pending_approval)
        loop.resume_approval(
            state,
            approval_id=pending["approval_id"],
            action_hash=pending["action_hash"],
            decision="approve",
        )
        lifecycle = [
            event
            for event in state.trace_events
            if event["event_type"]
            in {"approval_requested", "approval_decided", "approval_resumed"}
        ]
        self.assertEqual(
            [event["event_type"] for event in lifecycle],
            ["approval_requested", "approval_decided", "approval_resumed"],
        )
        identities = {
            (
                event["metadata"]["approval_id"],
                event["metadata"]["action_hash"],
            )
            for event in lifecycle
        }
        self.assertEqual(len(identities), 1)
        self.assertEqual({event["trace_id"] for event in lifecycle}, {state.trace_id})

    def test_day19_hitl_evaluator_accepts_approved_trace(self) -> None:
        loop, state, _server = self._pending()
        pending = dict(state.pending_approval)
        loop.resume_approval(
            state,
            approval_id=pending["approval_id"],
            action_hash=pending["action_hash"],
            decision="approve",
        )
        case = EvalCase(
            "DAY20-HITL-01",
            "security",
            "approved exact action",
            lambda: {"passed": True, "trace_events": state.trace_events},
            expectations={
                "hitl": {"tool": "mcp_mock__echo", "status": "approved"}
            },
            evaluators=("hitl",),
        )
        result = EvalRunner().run_case(case)
        self.assertTrue(result.passed, result.failure_reason)


if __name__ == "__main__":
    unittest.main()
