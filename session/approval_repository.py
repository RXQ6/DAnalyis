"""Encrypted HITL action persistence backed by the session event table."""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from typing import Any
from cryptography.fernet import Fernet, InvalidToken

class SQLiteApprovalRepository:
    def __init__(self, store: Any, key: bytes) -> None:
        self.store, self.cipher = store, Fernet(key)

    def create(self, thread_id: str, request: dict[str, Any], payload: dict[str, Any]) -> None:
        event = {"event_type":"approval_requested","component":"hitl","name":request["tool_name"],"status":"pending","trace_id":request.get("trace_id"),"metadata":{k:request.get(k) for k in ("approval_id","action_hash","action_type","rule_id","call_id")}}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        token = self.cipher.encrypt(raw)
        with self.store._lock:
            c=self.store._connection.cursor(); c.execute("BEGIN IMMEDIATE")
            seq=c.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM session_events WHERE thread_id=?",(thread_id,)).fetchone()[0]
            c.execute("INSERT INTO session_events(event_id,thread_id,sequence,trace_id,event_type,event_json,created_at,schema_version,approval_id,action_hash,approval_status,expires_at,private_payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(f"event_{request['approval_id']}",thread_id,seq,request.get("trace_id"),"approval_requested",json.dumps(event,ensure_ascii=False),request["created_at"],1,request["approval_id"],request["action_hash"],"pending",request["expires_at"],token)); self.store._connection.commit()

    def decide(self, thread_id: str, approval_id: str, action_hash: str, decision: str, now: float) -> tuple[dict[str,Any],dict[str,Any]|None]:
        stamp=datetime.fromtimestamp(now,timezone.utc).isoformat()
        with self.store._lock:
            c=self.store._connection.cursor(); c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM session_events WHERE thread_id=? AND approval_id=? ORDER BY id DESC LIMIT 1",(thread_id,approval_id)).fetchone()
            if row is None: self.store._connection.rollback(); return {"code":"approval_not_found"},None
            status=row["approval_status"]
            if status!="pending": self.store._connection.rollback(); return {"code":"approval_already_consumed" if status=="approved" else f"approval_{status}"},None
            expired=stamp>=row["expires_at"] or decision=="expire"
            mismatch=action_hash!=row["action_hash"]
            final="expired" if expired else "rejected" if mismatch or decision=="reject" else "approved" if decision=="approve" else "pending"
            if final=="pending": self.store._connection.rollback(); return {"code":"invalid_approval_decision"},None
            payload=None
            if final=="approved":
                try: payload=json.loads(self.cipher.decrypt(row["private_payload"]).decode())
                except InvalidToken: self.store._connection.rollback(); return {"code":"approval_payload_unreadable"},None
            c.execute("UPDATE session_events SET approval_status=?,consumed_at=?,private_payload=NULL WHERE id=?",(final,stamp,row["id"]))
            seq=c.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM session_events WHERE thread_id=?",(thread_id,)).fetchone()[0]
            public={"event_type":"approval_decided","component":"hitl","name":json.loads(row["event_json"])["name"],"status":final,"trace_id":None,"metadata":{"approval_id":approval_id,"action_hash":row["action_hash"]}}
            c.execute("INSERT INTO session_events(event_id,thread_id,sequence,event_type,event_json,created_at,schema_version) VALUES(?,?,?,?,?,?,1)",(f"event_{approval_id}_{final}",thread_id,seq,"approval_decided",json.dumps(public,ensure_ascii=False),stamp)); self.store._connection.commit()
            return {"status":final,"action_hash":row["action_hash"],"decided_at":stamp,"mismatch":mismatch},payload
