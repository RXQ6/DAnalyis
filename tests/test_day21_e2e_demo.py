from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from cryptography.fernet import Fernet
from demo import Day21Demo
from eval_harness import EvalCase, EvalRunner

class Day21E2EDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.data=self.root/"sales.csv"; self.data.write_text("地区,销售额\n华东,10\n华南,20\n",encoding="utf-8"); self.demo=Day21Demo(self.root,approval_key=Fernet.generate_key())
    def tearDown(self): self.tmp.cleanup()
    def test_happy_path_links_workflow_skill_subagent_memory_context_and_session(self):
        out=self.demo.happy_path(self.data,thread_id="thread_happy")
        self.assertEqual(out["route"],"analysis"); self.assertEqual(out["skill"],"data-diagnosis"); self.assertEqual(out["first_answer"],"数据诊断完成。"); self.assertEqual(out["final_answer"],"主 Agent 已整合子任务结果。"); self.assertTrue(out["subagent_completed"]); self.assertNotEqual(out["trace_id"],out["first_trace_id"]); self.assertTrue(out["messages"]); self.assertTrue(out["context_reports"])
        kinds={e["event_type"] for e in out["events"]}; self.assertIn("route_selected",kinds); self.assertIn("skill_triggered",kinds); self.assertIn("tool_completed",kinds)
    def test_hitl_restart_approve_new_trace_same_thread_and_no_plaintext(self):
        pending=self.demo.start_hitl(thread_id="thread_hitl",text="TOP-SECRET"); p=pending["pending"]; resumed=self.demo.resume_hitl(thread_id="thread_hitl",approval_id=p["approval_id"],action_hash=p["action_hash"],decision="approve")
        self.assertEqual(resumed["thread_id"],pending["thread_id"]); self.assertNotEqual(resumed["trace_id"],pending["trace_id"]); self.assertEqual(len(resumed["remote_calls"]),1); self.assertNotIn("TOP-SECRET",json.dumps(resumed["events"],ensure_ascii=False)); self.assertNotIn(b"TOP-SECRET",(self.root/"sessions.sqlite3").read_bytes())
    def test_replay_reject_expire_and_hash_swap_never_execute(self):
        cases=[("reject",None),("approve","wrong"),("expire",None)]
        for index,(decision,override) in enumerate(cases):
            pending=self.demo.start_hitl(thread_id=f"thread_stop_{index}"); p=pending["pending"]; out=self.demo.resume_hitl(thread_id=pending["thread_id"],approval_id=p["approval_id"],action_hash=override or p["action_hash"],decision=decision); self.assertEqual(out["remote_calls"],[])
        pending=self.demo.start_hitl(thread_id="thread_replay"); p=pending["pending"]; first=self.demo.resume_hitl(thread_id="thread_replay",approval_id=p["approval_id"],action_hash=p["action_hash"],decision="approve"); second=self.demo.resume_hitl(thread_id="thread_replay",approval_id=p["approval_id"],action_hash=p["action_hash"],decision="approve"); self.assertEqual(len(first["remote_calls"]),1); self.assertEqual(second["remote_calls"],[]); self.assertFalse(second["result"]["ok"])
    def test_day19_evaluates_end_to_end_session_trace(self):
        pending=self.demo.start_hitl(thread_id="thread_eval"); p=pending["pending"]; out=self.demo.resume_hitl(thread_id="thread_eval",approval_id=p["approval_id"],action_hash=p["action_hash"],decision="approve")
        case=EvalCase("D21-E2E","session","e2e",lambda:{"passed":True,"thread_id":"thread_eval","session_events":out["events"]},expectations={"session":{"thread_id":"thread_eval","approval_status":"approved","min_trace_count":1}},evaluators=("session",)); self.assertTrue(EvalRunner().run_case(case).passed)
if __name__=="__main__": unittest.main()
