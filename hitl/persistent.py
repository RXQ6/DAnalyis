"""SQLite-backed approval manager for cross-process HITL continuation."""
from __future__ import annotations
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from guardrails import DeterministicGuardrail, GuardrailDecision, ToolGuardrailPolicy
from observability import TraceCollector
from session import SQLiteApprovalRepository
from .contracts import ApprovalDecision, ApprovalRequest, ApprovalResolution
from .manager import _ApprovedAction, ApprovalManager

class PersistentApprovalManager:
    def __init__(self, repository: SQLiteApprovalRepository, *, thread_id: str, ttl_seconds: float=300, clock=time.time) -> None:
        self.repository,self.thread_id,self.ttl_seconds,self.clock=repository,thread_id,ttl_seconds,clock

    def create(self, decision: GuardrailDecision, *, arguments: dict[str,Any], context: dict[str,Any], policy: ToolGuardrailPolicy, collector: Any) -> ApprovalRequest:
        now=self.clock(); request=ApprovalRequest(decision.approval_id or "",decision.action_hash or "",decision.tool_name,decision.action_type,decision.risk_level,decision.rule_id,getattr(collector,"trace_id",None),str(context.get("call_id")) if context.get("call_id") else None,"pending",self._iso(now),self._iso(now+self.ttl_seconds))
        safe_context={k:context.get(k) for k in ("call_id","iteration","thread_id","turn_id") if context.get(k) is not None}
        self.repository.create(self.thread_id,request.to_dict(),{"tool_name":decision.tool_name,"arguments":arguments,"context":safe_context,"policy":asdict(policy)})
        ApprovalManager._emit(collector,"approval_requested",request,status="pending")
        return request

    def resolve(self, *, approval_id: str, action_hash: str, decision: str):
        collector=TraceCollector(); info,payload=self.repository.decide(self.thread_id,approval_id,action_hash,decision,self.clock())
        if "code" in info:
            return ApprovalResolution(False,None,error={"code":info["code"],"message":info["code"]},trace_events=tuple(collector.snapshot())),None
        status=info["status"]; public=ApprovalDecision(approval_id,info["action_hash"],status,"action_hash_mismatch" if info.get("mismatch") else f"user_{status}",info["decided_at"],status=="approved")
        tool_name=payload["tool_name"] if payload else "approval"; policy_data=payload["policy"] if payload else {"action_type":"mcp_write","risk_level":"high","tool_kind":"mcp"}
        if payload and DeterministicGuardrail._action_hash(tool_name, payload["arguments"]) != info["action_hash"]:
            return ApprovalResolution(False,public,error={"code":"approval_payload_mismatch","message":"stored action no longer matches action_hash"},trace_events=tuple(collector.snapshot())),None
        request=ApprovalRequest(approval_id,info["action_hash"],tool_name,policy_data["action_type"],policy_data["risk_level"],"persistent_approval",None,payload.get("context",{}).get("call_id") if payload else None,"pending","","")
        ApprovalManager._emit(collector,"approval_decided",request,status=status,error_code=None if status=="approved" else public.reason)
        if status!="approved": return ApprovalResolution(True,public,trace_events=tuple(collector.snapshot())),None
        policy=ToolGuardrailPolicy(**policy_data)
        return ApprovalResolution(True,public,trace_events=tuple(collector.snapshot())),_ApprovedAction(request,payload["arguments"],payload["context"],policy,collector)

    def record_completed(self, action: Any, result: dict[str,Any]) -> None:
        del result
        for event in action.collector.snapshot():
            if event["event_type"] in {"tool_called","tool_completed","mcp_called","approval_resumed","error"}:
                self.repository.store.append_event(self.thread_id,event,trace_id=event.get("trace_id"))

    @staticmethod
    def _iso(epoch: float)->str: return datetime.fromtimestamp(epoch,timezone.utc).isoformat()
