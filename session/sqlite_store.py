"""SQLite implementation of the minimal Day21.1 SessionStore primitives."""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    SessionAlreadyExistsError,
    SessionNotFoundError,
    SessionRecord,
    SessionSerializationError,
)


_THREAD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    thread_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    turn_id TEXT,
    trace_id TEXT,
    role TEXT NOT NULL,
    message_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(thread_id) REFERENCES sessions(thread_id) ON DELETE CASCADE,
    UNIQUE(thread_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_session_messages_thread_sequence
ON session_messages(thread_id, sequence);

CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    turn_id TEXT,
    trace_id TEXT,
    event_type TEXT NOT NULL,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    approval_id TEXT,
    action_hash TEXT,
    approval_status TEXT,
    expires_at TEXT,
    consumed_at TEXT,
    private_payload BLOB,
    FOREIGN KEY(thread_id) REFERENCES sessions(thread_id) ON DELETE CASCADE,
    UNIQUE(thread_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_session_events_thread_sequence
ON session_events(thread_id, sequence);

CREATE INDEX IF NOT EXISTS idx_session_events_trace
ON session_events(trace_id);

CREATE INDEX IF NOT EXISTS idx_session_events_approval
ON session_events(approval_id);
"""


class SQLiteSessionStore:
    """Persist canonical messages and generic structured events per thread.

    The store intentionally has no workflow, memory, trace-collection, context,
    or business resume behavior. Callers compose the read primitives themselves.
    """

    def __init__(self, database: str | Path = ":memory:", *, timeout: float = 5.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        supplied_database = str(database)
        self.database = (
            ":memory:"
            if supplied_database == ":memory:"
            else str(Path(supplied_database).expanduser().resolve())
        )
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.database,
            timeout=timeout,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._closed = False
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
            if self.database != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.executescript(_SCHEMA)
            self._migrate_event_columns()
            self._connection.commit()

    def create_session(
        self,
        thread_id: str | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> SessionRecord:
        active_thread_id = thread_id or f"thread_{uuid.uuid4().hex}"
        self._validate_thread_id(active_thread_id)
        if metadata is not None and not isinstance(metadata, Mapping):
            raise TypeError("session metadata must be a mapping")
        metadata_json = self._encode(dict(metadata or {}), "session metadata")
        now = self._utc_now()
        with self._lock:
            self._ensure_open()
            try:
                self._connection.execute(
                    """
                    INSERT INTO sessions (
                        thread_id, status, metadata_json, created_at, updated_at,
                        schema_version
                    ) VALUES (?, 'active', ?, ?, ?, 1)
                    """,
                    (active_thread_id, metadata_json, now, now),
                )
                self._connection.commit()
            except sqlite3.IntegrityError as error:
                self._connection.rollback()
                raise SessionAlreadyExistsError(
                    f"session already exists: {active_thread_id}"
                ) from error
        record = self.get_session(active_thread_id)
        assert record is not None
        return record

    def get_session(self, thread_id: str) -> SessionRecord | None:
        self._validate_thread_id(thread_id)
        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                "SELECT * FROM sessions WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return None if row is None else self._session_record(row)

    def list_sessions(self, *, limit: int = 20) -> list[SessionRecord]:
        """Return the most recently updated sessions without adding a second index."""
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("limit must be an integer between 1 and 100")
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC, thread_id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._session_record(row) for row in rows]

    def append_message(
        self,
        thread_id: str,
        message: Mapping[str, Any],
        *,
        message_id: str | None = None,
        turn_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_thread_id(thread_id)
        payload = self._mapping_payload(message, "message")
        role = payload.get("role")
        if not isinstance(role, str) or not role.strip():
            raise ValueError("message role must be a non-empty string")
        if "content" not in payload:
            raise ValueError("message must contain content")
        record_id = self._record_id(message_id, "message")
        encoded = self._encode(payload, "message")
        self._append(
            table="session_messages",
            id_column="message_id",
            record_id=record_id,
            thread_id=thread_id,
            turn_id=turn_id or self._optional_text(payload.get("turn_id")),
            trace_id=trace_id or self._optional_text(payload.get("trace_id")),
            kind_column="role",
            kind=role,
            json_column="message_json",
            encoded=encoded,
        )
        return copy.deepcopy(payload)

    def get_messages(
        self,
        thread_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._get_payloads(
            table="session_messages",
            json_column="message_json",
            thread_id=thread_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def append_event(
        self,
        thread_id: str,
        event: Mapping[str, Any],
        *,
        event_id: str | None = None,
        turn_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_thread_id(thread_id)
        payload = self._mapping_payload(event, "event")
        event_type = payload.get("event_type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be a non-empty string")
        record_id = self._record_id(
            event_id or self._optional_text(payload.get("event_id")), "event"
        )
        encoded = self._encode(payload, "event")
        self._append(
            table="session_events",
            id_column="event_id",
            record_id=record_id,
            thread_id=thread_id,
            turn_id=turn_id or self._optional_text(payload.get("turn_id")),
            trace_id=trace_id or self._optional_text(payload.get("trace_id")),
            kind_column="event_type",
            kind=event_type,
            json_column="event_json",
            encoded=encoded,
        )
        return copy.deepcopy(payload)

    def get_events(
        self,
        thread_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._get_payloads(
            table="session_events",
            json_column="event_json",
            thread_id=thread_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "SQLiteSessionStore":
        self._ensure_open()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _append(
        self,
        *,
        table: str,
        id_column: str,
        record_id: str,
        thread_id: str,
        turn_id: str | None,
        trace_id: str | None,
        kind_column: str,
        kind: str,
        json_column: str,
        encoded: str,
    ) -> None:
        now = self._utc_now()
        with self._lock:
            self._ensure_open()
            cursor = self._connection.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                if cursor.execute(
                    "SELECT 1 FROM sessions WHERE thread_id = ?", (thread_id,)
                ).fetchone() is None:
                    raise SessionNotFoundError(f"session not found: {thread_id}")
                sequence = cursor.execute(
                    f"SELECT COALESCE(MAX(sequence), 0) + 1 FROM {table} "
                    "WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()[0]
                cursor.execute(
                    f"""
                    INSERT INTO {table} (
                        {id_column}, thread_id, sequence, turn_id, trace_id,
                        {kind_column}, {json_column}, created_at, schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        record_id,
                        thread_id,
                        sequence,
                        turn_id,
                        trace_id,
                        kind,
                        encoded,
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE sessions SET updated_at = ? WHERE thread_id = ?",
                    (now, thread_id),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def _get_payloads(
        self,
        *,
        table: str,
        json_column: str,
        thread_id: str,
        after_sequence: int,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        self._validate_thread_id(thread_id)
        if (
            not isinstance(after_sequence, int)
            or isinstance(after_sequence, bool)
            or after_sequence < 0
        ):
            raise ValueError("after_sequence must be a non-negative integer")
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
        ):
            raise ValueError("limit must be a positive integer")
        sql = (
            f"SELECT {json_column} FROM {table} "
            "WHERE thread_id = ? AND sequence > ? ORDER BY sequence ASC"
        )
        parameters: list[Any] = [thread_id, after_sequence]
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)
        with self._lock:
            self._ensure_open()
            if self._connection.execute(
                "SELECT 1 FROM sessions WHERE thread_id = ?", (thread_id,)
            ).fetchone() is None:
                raise SessionNotFoundError(f"session not found: {thread_id}")
            rows = self._connection.execute(sql, parameters).fetchall()
        return [json.loads(row[json_column]) for row in rows]

    @staticmethod
    def _mapping_payload(value: Mapping[str, Any], label: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError(f"{label} must be a mapping")
        return copy.deepcopy(dict(value))

    @staticmethod
    def _encode(value: Any, label: str) -> str:
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            raise SessionSerializationError(
                f"{label} is not JSON serializable"
            ) from error

    @staticmethod
    def _record_id(value: str | None, prefix: str) -> str:
        if value is None:
            return f"{prefix}_{uuid.uuid4().hex}"
        if not isinstance(value, str) or not value.strip() or len(value) > 160:
            raise ValueError(f"{prefix}_id must be a non-empty string")
        return value

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _validate_thread_id(thread_id: str) -> None:
        if not isinstance(thread_id, str) or _THREAD_ID.fullmatch(thread_id) is None:
            raise ValueError("thread_id is invalid")

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _session_record(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            thread_id=row["thread_id"],
            status=row["status"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            schema_version=row["schema_version"],
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("session store is closed")

    def _migrate_event_columns(self) -> None:
        existing = {
            row[1]
            for row in self._connection.execute(
                "PRAGMA table_info(session_events)"
            ).fetchall()
        }
        additions = {
            "approval_id": "TEXT",
            "action_hash": "TEXT",
            "approval_status": "TEXT",
            "expires_at": "TEXT",
            "consumed_at": "TEXT",
            "private_payload": "BLOB",
        }
        for name, kind in additions.items():
            if name not in existing:
                self._connection.execute(
                    f"ALTER TABLE session_events ADD COLUMN {name} {kind}"
                )
