"""Serializable models shared by the long-term memory stores."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KVMemoryEntry:
    scope_id: str
    key: str
    value: Any
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "kv",
            "scope_id": self.scope_id,
            "key": self.key,
            "value": self.value,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SemanticMemoryEntry:
    id: str
    scope_id: str
    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "semantic",
            "id": self.id,
            "scope_id": self.scope_id,
            "kind": self.kind,
            "content": self.content,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SemanticMemoryMatch:
    entry: SemanticMemoryEntry
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {**self.entry.to_dict(), "score": self.score}


@dataclass(frozen=True)
class MemoryRecall:
    context: str = ""
    memories: list[dict[str, Any]] = field(default_factory=list)
