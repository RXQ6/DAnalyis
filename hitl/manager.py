"""Thread-safe, single-use approval storage and state transitions."""

from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from guardrails import GuardrailDecision, ToolGuardrailPolicy

from .contracts import ApprovalDecision, ApprovalRequest, ApprovalResolution


@dataclass
class _ApprovalRecord:
    request: ApprovalRequest
    arguments: dict[str, Any]
    context: dict[str, Any]
    policy: ToolGuardrailPolicy
    collector: Any
    expires_epoch: float
    status: str = "pending"
    consumed: bool = False


@dataclass(frozen=True)
class _ApprovedAction:
    request: ApprovalRequest
    arguments: dict[str, Any]
    context: dict[str, Any]
    policy: ToolGuardrailPolicy
    collector: Any


class ApprovalManager:
    """Own private action payloads; public requests never expose arguments."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("approval ttl_seconds must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self.clock = clock
        self._records: dict[str, _ApprovalRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        decision: GuardrailDecision,
        *,
        arguments: dict[str, Any],
        context: dict[str, Any],
        policy: ToolGuardrailPolicy,
        collector: Any,
    ) -> ApprovalRequest:
        if decision.decision != "needs_approval":
            raise ValueError("approval requests require a needs_approval decision")
        if not decision.approval_id or not decision.action_hash:
            raise ValueError("guardrail decision is missing approval identity")
        now = self.clock()
        request = ApprovalRequest(
            approval_id=decision.approval_id,
            action_hash=decision.action_hash,
            tool_name=decision.tool_name,
            action_type=decision.action_type,
            risk_level=decision.risk_level,
            rule_id=decision.rule_id,
            trace_id=getattr(collector, "trace_id", None),
            call_id=(
                str(context.get("call_id"))
                if context.get("call_id") is not None
                else None
            ),
            status="pending",
            created_at=self._iso(now),
            expires_at=self._iso(now + self.ttl_seconds),
        )
        private_context = dict(context)
        private_context.pop("_trace_collector", None)
        record = _ApprovalRecord(
            request=request,
            arguments=copy.deepcopy(arguments),
            context=private_context,
            policy=policy,
            collector=collector,
            expires_epoch=now + self.ttl_seconds,
        )
        with self._lock:
            self._records[request.approval_id] = record
        self._emit(
            collector,
            "approval_requested",
            request,
            status="pending",
        )
        return request

    def resolve(
        self,
        *,
        approval_id: str,
        action_hash: str,
        decision: Literal["approve", "reject", "expire"],
    ) -> tuple[ApprovalResolution, _ApprovedAction | None]:
        now = self.clock()
        with self._lock:
            record = self._records.get(approval_id)
            if record is None:
                return self._error(
                    None,
                    "approval_not_found",
                    "Approval request does not exist",
                ), None
            if record.consumed:
                return self._error(
                    record,
                    "approval_already_consumed",
                    "Approval has already been consumed",
                ), None
            if record.status != "pending":
                return self._error(
                    record,
                    f"approval_{record.status}",
                    f"Approval is already {record.status}",
                ), None
            if now >= record.expires_epoch or decision == "expire":
                resolution = self._finish_locked(
                    record,
                    status="expired",
                    reason="approval_expired",
                    now=now,
                    consume=False,
                )
                return resolution, None
            if action_hash != record.request.action_hash:
                resolution = self._finish_locked(
                    record,
                    status="rejected",
                    reason="action_hash_mismatch",
                    now=now,
                    consume=False,
                )
                return ApprovalResolution(
                    ok=False,
                    decision=resolution.decision,
                    error={
                        "code": "approval_action_mismatch",
                        "message": "Approval action hash does not match",
                    },
                    trace_events=resolution.trace_events,
                ), None
            if decision == "reject":
                resolution = self._finish_locked(
                    record,
                    status="rejected",
                    reason="user_rejected",
                    now=now,
                    consume=False,
                )
                return resolution, None
            if decision != "approve":
                return self._error(
                    record,
                    "invalid_approval_decision",
                    "Approval decision is invalid",
                ), None

            record.status = "approved"
            record.consumed = True
            public_decision = ApprovalDecision(
                approval_id=record.request.approval_id,
                action_hash=record.request.action_hash,
                status="approved",
                reason="user_approved",
                decided_at=self._iso(now),
                consumed=True,
            )
            action = _ApprovedAction(
                request=record.request,
                arguments=record.arguments,
                context=record.context,
                policy=record.policy,
                collector=record.collector,
            )
            record.arguments = {}
            record.context = {}
            self._emit(
                record.collector,
                "approval_decided",
                record.request,
                status="approved",
            )
            return (
                ApprovalResolution(
                    ok=True,
                    decision=public_decision,
                    trace_events=self._events(record.collector),
                ),
                action,
            )

    def _finish_locked(
        self,
        record: _ApprovalRecord,
        *,
        status: Literal["rejected", "expired"],
        reason: str,
        now: float,
        consume: bool,
    ) -> ApprovalResolution:
        record.status = status
        record.consumed = consume
        record.arguments = {}
        record.context = {}
        decision = ApprovalDecision(
            approval_id=record.request.approval_id,
            action_hash=record.request.action_hash,
            status=status,
            reason=reason,
            decided_at=self._iso(now),
            consumed=consume,
        )
        self._emit(
            record.collector,
            "approval_decided",
            record.request,
            status=status,
            error_code=reason,
        )
        return ApprovalResolution(
            ok=True,
            decision=decision,
            trace_events=self._events(record.collector),
        )

    def _error(
        self,
        record: _ApprovalRecord | None,
        code: str,
        message: str,
    ) -> ApprovalResolution:
        collector = None if record is None else record.collector
        request = None if record is None else record.request
        if request is not None:
            self._emit(
                collector,
                "error",
                request,
                status="rejected",
                error_code=code,
            )
        return ApprovalResolution(
            ok=False,
            decision=None,
            error={"code": code, "message": message},
            trace_events=self._events(collector),
        )

    @staticmethod
    def _emit(
        collector: Any,
        event_type: str,
        request: ApprovalRequest,
        *,
        status: str,
        error_code: str | None = None,
    ) -> None:
        emit = getattr(collector, "emit", None)
        if callable(emit):
            emit(
                event_type,
                component="hitl",
                name=request.tool_name,
                status=status,
                error_code=error_code,
                metadata={
                    "approval_id": request.approval_id,
                    "action_hash": request.action_hash,
                    "action_type": request.action_type,
                    "rule_id": request.rule_id,
                    "call_id": request.call_id,
                },
            )

    @staticmethod
    def _events(collector: Any) -> tuple[dict[str, Any], ...]:
        snapshot = getattr(collector, "snapshot", None)
        return tuple(snapshot()) if callable(snapshot) else ()

    @staticmethod
    def _iso(epoch: float) -> str:
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat()
