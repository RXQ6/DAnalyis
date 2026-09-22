from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from ..models import EvalCase, ProcessEvaluation
from ..taxonomy import FailureType
class SessionEvaluator:
    name="session"
    def evaluate(self, case: EvalCase, observation: Mapping[str,Any])->ProcessEvaluation:
        config=case.expectations.get("session")
        if config is None: return ProcessEvaluation(self.name,False,True)
        events=observation.get("session_events",[]); failures=[]
        if observation.get("thread_id")!=config.get("thread_id"): failures.append("thread_id mismatch")
        statuses=[e.get("status") for e in events if e.get("event_type")=="approval_decided"]
        if config.get("approval_status") and config["approval_status"] not in statuses: failures.append("approval status missing")
        traces={e.get("trace_id") for e in events if e.get("trace_id")}
        if config.get("min_trace_count",1)>len(traces): failures.append("trace continuity missing")
        return ProcessEvaluation(self.name,bool(events),not failures,str(FailureType.TRACE_ERROR) if failures else None,"; ".join(failures) or None,{"session_trace_count":len(traces)})
