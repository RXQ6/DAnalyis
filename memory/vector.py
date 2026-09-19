"""Small persistent vector store for bounded semantic memory collections."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Protocol

from .models import SemanticMemoryEntry, SemanticMemoryMatch


CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "concept:aggregation": ("聚合", "汇总", "合计", "aggregate", "aggregation"),
    "concept:anomaly": ("异常", "离群", "异常值", "离群点", "anomaly", "outlier"),
    "concept:average": ("平均", "均值", "average", "mean"),
    "concept:date": ("日期", "时间字段", "时间列", "date", "timestamp"),
    "concept:missing": ("缺失", "空值", "缺失值", "missing", "null"),
    "concept:sales": ("销售", "销售额", "营收", "收入", "sales", "revenue"),
    "concept:sum": ("求和", "总和", "合计", "sum", "total"),
    "concept:trend": ("趋势", "变化走势", "走势", "trend"),
}


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Dependency-free deterministic text embedding suitable for a small local store."""

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 32:
            raise ValueError("dimensions must be at least 32")
        self.dimensions = dimensions
        self.model_id = f"hashing-domain-v2-{dimensions}"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dimensions
            vector[index] += -1.0 if value & 1 else 1.0
        magnitude = math.sqrt(sum(item * item for item in vector))
        if magnitude:
            return [item / magnitude for item in vector]
        return vector


class SQLiteVectorMemory:
    """Stores embeddings in SQLite and performs bounded in-process cosine search."""

    def __init__(self, database: str | Path, *, embedder: Embedder | None = None) -> None:
        self.database = str(database)
        self.embedder = embedder or HashingEmbedder()
        self._connection = sqlite3.connect(self.database)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_memory (
                id TEXT PRIMARY KEY,
                scope_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT,
                metadata_json TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                embedding_model TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._migrate_schema()
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS semantic_memory_scope ON semantic_memory(scope_id)"
        )
        self._connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS semantic_memory_dedup
            ON semantic_memory(scope_id, kind, content_hash)
            """
        )
        self._connection.commit()

    def add(
        self,
        scope_id: str,
        content: str,
        *,
        kind: str,
        metadata: dict[str, Any] | None = None,
        memory_id: str | None = None,
    ) -> SemanticMemoryEntry:
        scope_id = _required_text(scope_id, "scope_id")
        content = _required_text(content, "content")
        kind = _required_text(kind, "kind")
        entry_id = memory_id or str(uuid.uuid4())
        metadata = dict(metadata or {})
        embedding = self.embedder.embed(content)
        content_hash = _content_hash(content)
        try:
            self._connection.execute(
                """
                INSERT INTO semantic_memory
                    (id, scope_id, kind, content, content_hash, metadata_json,
                     embedding_json, embedding_model, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(scope_id, kind, content_hash) DO UPDATE SET
                    content = excluded.content,
                    metadata_json = excluded.metadata_json,
                    embedding_json = excluded.embedding_json,
                    embedding_model = excluded.embedding_model,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    entry_id,
                    scope_id,
                    kind,
                    content,
                    content_hash,
                    json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(embedding, separators=(",", ":")),
                    _embedder_id(self.embedder),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"semantic memory id already exists: {entry_id}") from error
        self._connection.commit()
        row = self._connection.execute(
            "SELECT id FROM semantic_memory WHERE scope_id = ? AND kind = ? AND content_hash = ?",
            (scope_id, kind, content_hash),
        ).fetchone()
        return self.get(scope_id, row[0])  # type: ignore[return-value]

    def update(
        self,
        scope_id: str,
        memory_id: str,
        *,
        content: str | None = None,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SemanticMemoryEntry:
        existing = self.get(scope_id, memory_id)
        if existing is None:
            raise KeyError(f"semantic memory does not exist: {memory_id}")
        next_content = _required_text(content, "content") if content is not None else existing.content
        next_kind = _required_text(kind, "kind") if kind is not None else existing.kind
        next_metadata = dict(metadata) if metadata is not None else existing.metadata
        try:
            self._connection.execute(
                """
                UPDATE semantic_memory SET
                    kind = ?, content = ?, content_hash = ?, metadata_json = ?,
                    embedding_json = ?, embedding_model = ?, updated_at = CURRENT_TIMESTAMP
                WHERE scope_id = ? AND id = ?
                """,
                (
                    next_kind,
                    next_content,
                    _content_hash(next_content),
                    json.dumps(next_metadata, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(self.embedder.embed(next_content), separators=(",", ":")),
                    _embedder_id(self.embedder),
                    scope_id,
                    memory_id,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("semantic memory update would create a duplicate") from error
        self._connection.commit()
        return self.get(scope_id, memory_id)  # type: ignore[return-value]

    def get(self, scope_id: str, memory_id: str) -> SemanticMemoryEntry | None:
        scope_id = _required_text(scope_id, "scope_id")
        memory_id = _required_text(memory_id, "memory_id")
        row = self._connection.execute(
            """
            SELECT id, kind, content, metadata_json, created_at, updated_at
            FROM semantic_memory WHERE scope_id = ? AND id = ?
            """,
            (scope_id, memory_id),
        ).fetchone()
        return _entry_from_row(scope_id, row) if row else None

    def search(
        self,
        scope_id: str,
        query: str,
        *,
        top_k: int = 3,
        min_score: float = 0.05,
    ) -> list[SemanticMemoryMatch]:
        scope_id = _required_text(scope_id, "scope_id")
        query = _required_text(query, "query")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        query_vector = self.embedder.embed(query)
        rows = self._connection.execute(
            """
            SELECT id, kind, content, metadata_json, created_at, updated_at, embedding_json
            FROM semantic_memory WHERE scope_id = ?
            """,
            (scope_id,),
        ).fetchall()
        matches = []
        for row in rows:
            score = sum(
                left * right
                for left, right in zip(query_vector, json.loads(row[6]), strict=True)
            )
            if score >= min_score:
                matches.append(
                    SemanticMemoryMatch(_entry_from_row(scope_id, row[:6]), round(score, 6))
                )
        matches.sort(key=lambda item: (-item.score, item.entry.id))
        return matches[:top_k]

    def delete(self, scope_id: str, memory_id: str) -> bool:
        scope_id = _required_text(scope_id, "scope_id")
        memory_id = _required_text(memory_id, "memory_id")
        cursor = self._connection.execute(
            "DELETE FROM semantic_memory WHERE scope_id = ? AND id = ?",
            (scope_id, memory_id),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def list(self, scope_id: str) -> list[SemanticMemoryEntry]:
        scope_id = _required_text(scope_id, "scope_id")
        rows = self._connection.execute(
            """
            SELECT id, kind, content, metadata_json, created_at, updated_at
            FROM semantic_memory WHERE scope_id = ? ORDER BY created_at, id
            """,
            (scope_id,),
        ).fetchall()
        return [_entry_from_row(scope_id, row) for row in rows]

    def close(self) -> None:
        self._connection.close()

    def _migrate_schema(self) -> None:
        columns = {
            row[1]
            for row in self._connection.execute("PRAGMA table_info(semantic_memory)").fetchall()
        }
        if "content_hash" not in columns:
            self._connection.execute("ALTER TABLE semantic_memory ADD COLUMN content_hash TEXT")
        if "updated_at" not in columns:
            self._connection.execute("ALTER TABLE semantic_memory ADD COLUMN updated_at TEXT")
        if "embedding_model" not in columns:
            self._connection.execute("ALTER TABLE semantic_memory ADD COLUMN embedding_model TEXT")
        rows = self._connection.execute(
            "SELECT id, content, created_at, embedding_model FROM semantic_memory"
        ).fetchall()
        active_model = _embedder_id(self.embedder)
        for memory_id, content, created_at, stored_model in rows:
            embedding_update = ""
            parameters: list[Any] = [_content_hash(content), created_at]
            if stored_model != active_model:
                embedding_update = ", embedding_json = ?, embedding_model = ?"
                parameters.extend(
                    [
                        json.dumps(self.embedder.embed(content), separators=(",", ":")),
                        active_model,
                    ]
                )
            parameters.append(memory_id)
            self._connection.execute(
                f"""
                UPDATE semantic_memory
                SET content_hash = ?, updated_at = COALESCE(updated_at, ?)
                {embedding_update}
                WHERE id = ?
                """,
                parameters,
            )
        self._connection.execute(
            """
            DELETE FROM semantic_memory
            WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM semantic_memory
                GROUP BY scope_id, kind, content_hash
            )
            """
        )
        self._connection.commit()


def _entry_from_row(scope_id: str, row: tuple[Any, ...]) -> SemanticMemoryEntry:
    return SemanticMemoryEntry(
        id=row[0],
        scope_id=scope_id,
        kind=row[1],
        content=row[2],
        metadata=json.loads(row[3]),
        created_at=row[4],
        updated_at=row[5],
    )


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_]+", lowered)
    for run in re.findall(r"[\u3400-\u9fff]+", lowered):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
        tokens.extend(run[index : index + 3] for index in range(len(run) - 2))
    for concept, aliases in CONCEPT_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            tokens.extend((concept, concept))
    return tokens


def _content_hash(content: str) -> str:
    normalized = re.sub(r"\s+", " ", content.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _embedder_id(embedder: Embedder) -> str:
    configured = getattr(embedder, "model_id", None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    embedder_type = type(embedder)
    return f"{embedder_type.__module__}.{embedder_type.__qualname__}"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()
