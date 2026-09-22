"""Pure projection of SessionStore read results into recoverable task state."""
from __future__ import annotations
import copy
from dataclasses import dataclass
from typing import Any
from agent.conversation import ConversationState, ConversationTurn

@dataclass
class SessionRecoverySnapshot:
    conversation_state: ConversationState
    guardrail_decisions: list[dict[str,Any]]
    approvals: dict[str,dict[str,Any]]
    tool_events: list[dict[str,Any]]
    mcp_events: list[dict[str,Any]]
    validated_results: list[dict[str,Any]]
    trace_ids: list[str]

class SessionStateProjector:
    @staticmethod
    def project(*, thread_id: str, messages: list[dict[str,Any]], events: list[dict[str,Any]], dataset_registry: Any) -> SessionRecoverySnapshot:
        grouped: dict[str,list[dict[str,Any]]]={}
        for message in messages:
            turn=str(message.get("turn_id") or "turn_1"); clean=copy.deepcopy(message); clean.pop("turn_id",None); clean.pop("trace_id",None); grouped.setdefault(turn,[]).append(clean)
        state=ConversationState(conversation_id=thread_id,dataset_registry=dataset_registry)
        state.turns=[ConversationTurn(turn,items,[],[],None) for turn,items in grouped.items()]
        guards=[]; approvals={}; tools=[]; mcps=[]; validated=[]; traces=[]
        for event in events:
            kind=event.get("event_type"); trace=event.get("trace_id")
            if isinstance(trace,str) and trace not in traces: traces.append(trace)
            if kind=="guardrail_decision": guards.append(copy.deepcopy(event))
            if kind in {"approval_requested","approval_decided"}:
                meta=event.get("metadata") or {}; aid=meta.get("approval_id")
                if aid: approvals[str(aid)]=copy.deepcopy(event)
            if kind in {"tool_called","tool_completed"}: tools.append(copy.deepcopy(event))
            if kind=="mcp_called": mcps.append(copy.deepcopy(event))
            if kind in {"validated_result","contract_checked"}: validated.append(copy.deepcopy(event))
        return SessionRecoverySnapshot(state,guards,approvals,tools,mcps,validated,traces)
