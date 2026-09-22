"""Small deterministic rule set for Day20.2."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from .contracts import GuardrailDecision, GuardrailOutcome, ToolGuardrailPolicy


_ALLOW_ACTIONS = frozenset(
    {"read_data", "analysis", "chart", "mcp_read", "subagent_read"}
)
_PYTHON_SHELL = re.compile(
    r"(?:^|[_-])(?:python|python3|shell|bash|sh|powershell|cmd|exec_code|run_code)(?:$|[_-])",
    re.I,
)
_ORIGINAL_MUTATION = re.compile(
    r"(?:modify|overwrite|delete|truncate|replace)[_-]?(?:original|source|input|dataset)",
    re.I,
)


class DeterministicGuardrail:
    """Classify an action without consulting an LLM or executing the handler."""

    def evaluate(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        policy: ToolGuardrailPolicy,
    ) -> GuardrailDecision:
        action = policy.action_type.strip().lower()
        if action in {"python", "shell"} or _PYTHON_SHELL.search(tool_name):
            return self._decision(
                "block", "deny_arbitrary_code", "Arbitrary Python or shell execution is denied", tool_name, policy
            )
        if action == "modify_original_data" or _ORIGINAL_MUTATION.search(tool_name):
            return self._decision(
                "block", "deny_original_data_mutation", "Original data cannot be modified", tool_name, policy
            )
        if action == "mcp_write":
            action_hash = self._action_hash(tool_name, arguments)
            return self._decision(
                "needs_approval",
                "approve_mcp_external_write",
                "External MCP write requires approval",
                tool_name,
                policy,
                approval_id=f"approval_{uuid.uuid4().hex}",
                action_hash=action_hash,
            )
        if action in _ALLOW_ACTIONS:
            return self._decision(
                "allow", "allow_read_or_analysis", "Read-only or bounded analysis action", tool_name, policy
            )
        return self._decision(
            "block",
            "deny_unknown_high_risk",
            "Unknown high-risk action is denied by default",
            tool_name,
            policy,
        )

    @staticmethod
    def _decision(
        decision: GuardrailOutcome,
        rule_id: str,
        reason: str,
        tool_name: str,
        policy: ToolGuardrailPolicy,
        *,
        approval_id: str | None = None,
        action_hash: str | None = None,
    ) -> GuardrailDecision:
        return GuardrailDecision(
            decision=decision,
            rule_id=rule_id,
            reason=reason,
            tool_name=tool_name,
            action_type=policy.action_type,
            risk_level=policy.risk_level,
            tool_kind=policy.tool_kind,
            approval_id=approval_id,
            action_hash=action_hash,
        )

    @staticmethod
    def _action_hash(tool_name: str, arguments: dict[str, Any]) -> str:
        payload = json.dumps(
            {"tool": tool_name, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
