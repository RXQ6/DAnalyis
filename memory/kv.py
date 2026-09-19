"""SQLite-backed exact key/value long-term memory."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import KVMemoryEntry


class SQLiteKVMemory:
    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        self._connection = sqlite3.connect(self.database)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_memory (
                scope_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (scope_id, key)
            )
            """
        )
        self._connection.commit()

    def set(self, scope_id: str, key: str, value: Any) -> KVMemoryEntry:
        scope_id = _required_text(scope_id, "scope_id")
        key = _required_text(key, "key")
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        existing = self.get(scope_id, key)
        if existing is not None and existing.value == value:
            return existing
        self._connection.execute(
            """
            INSERT INTO kv_memory (scope_id, key, value_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(scope_id, key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (scope_id, key, serialized),
        )
        self._connection.commit()
        entry = self.get(scope_id, key)
        if entry is None:  # pragma: no cover - SQLite contract guard
            raise RuntimeError("KV memory write did not persist")
        return entry

    def update(self, scope_id: str, key: str, value: Any) -> KVMemoryEntry:
        if self.get(scope_id, key) is None:
            raise KeyError(f"KV memory does not exist: {key}")
        return self.set(scope_id, key, value)

    def get(self, scope_id: str, key: str) -> KVMemoryEntry | None:
        scope_id = _required_text(scope_id, "scope_id")
        key = _required_text(key, "key")
        row = self._connection.execute(
            "SELECT value_json, updated_at FROM kv_memory WHERE scope_id = ? AND key = ?",
            (scope_id, key),
        ).fetchone()
        if row is None:
            return None
        return KVMemoryEntry(scope_id, key, json.loads(row[0]), row[1])

    def delete(self, scope_id: str, key: str) -> bool:
        scope_id = _required_text(scope_id, "scope_id")
        key = _required_text(key, "key")
        cursor = self._connection.execute(
            "DELETE FROM kv_memory WHERE scope_id = ? AND key = ?", (scope_id, key)
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def list(self, scope_id: str) -> list[KVMemoryEntry]:
        scope_id = _required_text(scope_id, "scope_id")
        rows = self._connection.execute(
            """
            SELECT key, value_json, updated_at
            FROM kv_memory
            WHERE scope_id = ?
            ORDER BY key
            """,
            (scope_id,),
        ).fetchall()
        return [
            KVMemoryEntry(scope_id, row[0], json.loads(row[1]), row[2])
            for row in rows
        ]

    def close(self) -> None:
        self._connection.close()


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()
