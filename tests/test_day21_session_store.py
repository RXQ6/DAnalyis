from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from session import (
    SessionAlreadyExistsError,
    SessionNotFoundError,
    SessionRecord,
    SessionSerializationError,
    SQLiteSessionStore,
)


class SQLiteSessionStoreTests(unittest.TestCase):
    def test_create_and_get_session_record_with_utc_timestamps(self) -> None:
        with SQLiteSessionStore() as store:
            created = store.create_session(
                "thread_day21", metadata={"source": "test"}
            )
            loaded = store.get_session("thread_day21")

        self.assertIsInstance(created, SessionRecord)
        self.assertEqual(loaded, created)
        self.assertEqual(created.thread_id, "thread_day21")
        self.assertEqual(created.status, "active")
        self.assertEqual(created.metadata, {"source": "test"})
        for value in (created.created_at, created.updated_at):
            timestamp = datetime.fromisoformat(value)
            self.assertEqual(timestamp.utcoffset(), timezone.utc.utcoffset(timestamp))

    def test_create_can_generate_thread_id_and_duplicate_is_rejected(self) -> None:
        with SQLiteSessionStore() as store:
            generated = store.create_session()
            self.assertTrue(generated.thread_id.startswith("thread_"))
            store.create_session("thread_unique")
            with self.assertRaises(SessionAlreadyExistsError):
                store.create_session("thread_unique")

    def test_list_sessions_uses_store_updated_order(self) -> None:
        with SQLiteSessionStore() as store:
            store.create_session("thread_old")
            store.create_session("thread_new")
            time.sleep(0.01)
            store.append_message("thread_old", {"role": "user", "content": "updated"})
            records = store.list_sessions(limit=2)
            self.assertEqual([item.thread_id for item in records], ["thread_old", "thread_new"])
            with self.assertRaises(ValueError):
                store.list_sessions(limit=0)

    def test_messages_round_trip_in_true_append_order(self) -> None:
        with SQLiteSessionStore() as store:
            store.create_session("thread_messages")
            expected = [
                {"role": "user", "content": "第一条"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "call_1", "name": "basic_stats"}],
                },
                {"role": "tool", "content": {"ok": True, "count": 3}},
                {"role": "assistant", "content": "第四条"},
            ]
            for message in expected:
                store.append_message("thread_messages", message)

            self.assertEqual(store.get_messages("thread_messages"), expected)
            self.assertEqual(
                store.get_messages("thread_messages", after_sequence=2, limit=1),
                [expected[2]],
            )

    def test_structured_events_accept_reserved_future_event_types_in_order(self) -> None:
        with SQLiteSessionStore() as store:
            store.create_session("thread_events")
            expected = [
                {"event_type": "guardrail_decision", "status": "allow"},
                {"event_type": "approval_requested", "status": "pending"},
                {"event_type": "tool_completed", "status": "ok"},
                {"event_type": "mcp_called", "status": "ok"},
                {"event_type": "validated_result", "status": "valid"},
            ]
            for event in expected:
                store.append_event("thread_events", event)

            self.assertEqual(store.get_events("thread_events"), expected)

    def test_message_and_event_payloads_are_json_snapshots(self) -> None:
        with SQLiteSessionStore() as store:
            store.create_session("thread_snapshot")
            message = {"role": "user", "content": {"query": "原值"}}
            event = {"event_type": "turn_started", "metadata": {"step": 1}}
            store.append_message("thread_snapshot", message)
            store.append_event("thread_snapshot", event)
            message["content"]["query"] = "已修改"
            event["metadata"]["step"] = 2

            self.assertEqual(
                store.get_messages("thread_snapshot")[0]["content"]["query"],
                "原值",
            )
            self.assertEqual(
                store.get_events("thread_snapshot")[0]["metadata"]["step"], 1
            )
            with self.assertRaises(SessionSerializationError):
                store.append_event(
                    "thread_snapshot",
                    {"event_type": "bad", "value": object()},
                )

    def test_thread_isolation_and_missing_session_errors(self) -> None:
        with SQLiteSessionStore() as store:
            store.create_session("thread_a")
            store.create_session("thread_b")
            store.append_message("thread_a", {"role": "user", "content": "A"})
            store.append_message("thread_b", {"role": "user", "content": "B"})
            self.assertEqual(store.get_messages("thread_a")[0]["content"], "A")
            self.assertEqual(store.get_messages("thread_b")[0]["content"], "B")
            self.assertIsNone(store.get_session("thread_missing"))
            with self.assertRaises(SessionNotFoundError):
                store.append_event(
                    "thread_missing", {"event_type": "turn_started"}
                )
            with self.assertRaises(SessionNotFoundError):
                store.get_events("thread_missing")

    def test_concurrent_appends_have_a_complete_serial_order(self) -> None:
        with SQLiteSessionStore() as store:
            store.create_session("thread_concurrent")

            def append(index: int) -> None:
                store.append_event(
                    "thread_concurrent",
                    {"event_type": "step", "index": index},
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(append, range(40)))

            events = store.get_events("thread_concurrent")
            self.assertEqual(len(events), 40)
            self.assertEqual({event["index"] for event in events}, set(range(40)))

    def test_file_database_survives_store_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            with SQLiteSessionStore(database) as first:
                first.create_session("thread_file")
                first.append_message(
                    "thread_file", {"role": "user", "content": "persisted"}
                )
            with SQLiteSessionStore(database) as second:
                self.assertIsNotNone(second.get_session("thread_file"))
                self.assertEqual(
                    second.get_messages("thread_file"),
                    [{"role": "user", "content": "persisted"}],
                )

    def test_file_database_is_readable_from_another_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "cross-process.sqlite3"
            script = (
                "from session import SQLiteSessionStore; "
                f"s=SQLiteSessionStore({str(database)!r}); "
                "s.create_session('thread_process'); "
                "s.append_event('thread_process', "
                "{'event_type':'turn_completed','status':'ok'}); s.close()"
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with SQLiteSessionStore(database) as store:
                self.assertEqual(
                    store.get_events("thread_process"),
                    [{"event_type": "turn_completed", "status": "ok"}],
                )

    def test_schema_uses_three_tables(self) -> None:
        with SQLiteSessionStore() as store:
            rows = store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        names = {row[0] for row in rows}
        self.assertTrue(
            {"sessions", "session_messages", "session_events"}.issubset(names)
        )
        self.assertNotIn("session_approvals", names)


if __name__ == "__main__":
    unittest.main()
