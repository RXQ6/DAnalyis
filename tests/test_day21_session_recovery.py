from __future__ import annotations
import tempfile, unittest
from pathlib import Path
from typing import Any
from cryptography.fernet import Fernet
from agent import AgentLoop
from datasets import DatasetRegistry
from eval_harness import EvalCase, EvalRunner
from hitl import PersistentApprovalManager
from mcp_adapter import MCPToolAdapter, MockMCPClient, MockMCPServer
from session import SQLiteApprovalRepository, SQLiteSessionStore
from session.recovery import SessionStateProjector
from tools import ToolRegistry

class Model:
    def complete(self, **_:Any): return {"type":"tool_call","id":"write-1","name":"mcp_mock__echo","arguments":{"text":"secret-value"}}

class SessionRecoveryTests(unittest.TestCase):
    def pending(self, db:Path, key:bytes, now:list[float]|None=None):
        store=SQLiteSessionStore(db); store.create_session("thread_old") if store.get_session("thread_old") is None else None
        clock=(lambda:now[0]) if now else __import__('time').time
        manager=PersistentApprovalManager(SQLiteApprovalRepository(store,key),thread_id="thread_old",ttl_seconds=5 if now else 300,clock=clock)
        registry=ToolRegistry(approval_manager=manager); server=MockMCPServer(); MCPToolAdapter(MockMCPClient(server),server_id="mock",allowed_tools={"echo"},tool_policies={"echo":"mcp_write"}).register_into(registry)
        state=AgentLoop(Model(),registry).run("write",conversation_id="thread_old",turn_id="turn_1")
        return store,state,server
    def restored(self,db,key):
        store=SQLiteSessionStore(db); manager=PersistentApprovalManager(SQLiteApprovalRepository(store,key),thread_id="thread_old")
        registry=ToolRegistry(approval_manager=manager); server=MockMCPServer(); MCPToolAdapter(MockMCPClient(server),server_id="mock",allowed_tools={"echo"},tool_policies={"echo":"mcp_write"}).register_into(registry); return store,registry,server
    def test_cross_restart_approve_executes_exact_action_new_trace(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"s.db"; key=Fernet.generate_key(); s,state,_=self.pending(db,key); p=state.pending_approval; origin=state.trace_id; s.close(); s2,r,server=self.restored(db,key); out=r.resolve_approval(approval_id=p["approval_id"],action_hash=p["action_hash"],decision="approve")
            self.assertTrue(out.ok); self.assertEqual(server.calls[0]["arguments"],{"text":"secret-value"}); self.assertNotEqual(out.trace_events[-1]["trace_id"],origin); self.assertGreaterEqual(len(s2.get_events("thread_old")),3); s2.close()
    def test_reject_and_replay_do_not_execute(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"s.db"; key=Fernet.generate_key(); s,state,_=self.pending(db,key); p=state.pending_approval; s.close(); s2,r,server=self.restored(db,key); one=r.resolve_approval(approval_id=p["approval_id"],action_hash=p["action_hash"],decision="reject"); two=r.resolve_approval(approval_id=p["approval_id"],action_hash=p["action_hash"],decision="approve"); self.assertEqual(one.decision.status,"rejected"); self.assertFalse(two.ok); self.assertEqual(server.calls,[]); s2.close()
    def test_hash_mismatch_invalidates(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"s.db"; key=Fernet.generate_key(); s,state,_=self.pending(db,key); p=state.pending_approval; s.close(); s2,r,server=self.restored(db,key); out=r.resolve_approval(approval_id=p["approval_id"],action_hash="bad",decision="approve"); self.assertEqual(out.decision.status,"rejected"); self.assertEqual(server.calls,[]); s2.close()
    def test_expired_does_not_execute(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"s.db"; key=Fernet.generate_key(); now=[1000.0]; s,state,_=self.pending(db,key,now); p=state.pending_approval; s.close(); now[0]=1006; s2=SQLiteSessionStore(db); m=PersistentApprovalManager(SQLiteApprovalRepository(s2,key),thread_id="thread_old",clock=lambda:now[0]); r=ToolRegistry(approval_manager=m); out=r.resolve_approval(approval_id=p["approval_id"],action_hash=p["action_hash"],decision="approve"); self.assertEqual(out.decision.status,"expired"); s2.close()
    def test_plaintext_payload_not_in_database(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"s.db"; key=Fernet.generate_key(); s,_,_=self.pending(db,key); s.close(); self.assertNotIn(b"secret-value",db.read_bytes())
    def test_messages_and_structured_events_project(self):
        with tempfile.TemporaryDirectory() as d:
            store=SQLiteSessionStore(Path(d)/"s.db"); store.create_session("thread_old"); store.append_message("thread_old",{"role":"user","content":"hello","turn_id":"turn_1"}); store.append_event("thread_old",{"event_type":"guardrail_decision","status":"allow","trace_id":"trace_a"}); store.append_event("thread_old",{"event_type":"validated_result","status":"valid","trace_id":"trace_b"}); snap=SessionStateProjector.project(thread_id="thread_old",messages=store.get_messages("thread_old"),events=store.get_events("thread_old"),dataset_registry=DatasetRegistry(Path(d)/"data")); self.assertEqual(snap.conversation_state.conversation_id,"thread_old"); self.assertEqual(snap.conversation_state.history_messages()[0]["content"],"hello"); self.assertEqual(len(snap.guardrail_decisions),1); self.assertEqual(len(snap.validated_results),1); self.assertEqual(snap.trace_ids,["trace_a","trace_b"]); store.close()
    def test_day19_session_evaluator(self):
        case=EvalCase("D21","session","restore",lambda:{"passed":True,"thread_id":"t","session_events":[{"event_type":"approval_decided","status":"approved","trace_id":"new"}]},expectations={"session":{"thread_id":"t","approval_status":"approved"}},evaluators=("session",)); self.assertTrue(EvalRunner().run_case(case).passed)
if __name__=="__main__": unittest.main()
