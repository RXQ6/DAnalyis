"""Unified policy and lifecycle facade for three-layer Agent memory."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .kv import SQLiteKVMemory
from .models import MemoryRecall
from .vector import Embedder, SQLiteVectorMemory


ALLOWED_KV_KEYS = frozenset(
    {
        "preferred_metric",
        "preferred_chart_type",
        "default_time_column",
        "default_aggregation",
    }
)
ALLOWED_SEMANTIC_KINDS = frozenset({"analysis_summary", "analysis_experience", "sop"})
BLOCKED_PAYLOAD_KEYS = frozenset(
    {
        "rows",
        "todos",
        "tool_calls",
        "execution_trace",
        "observation",
        "observations",
        "datasetid",
        "dataset_id",
        "datasetids",
        "dataset_ids",
    }
)
RUNTIME_DATASET_ID = re.compile(r"\bds_[0-9a-f]{12,64}\b", re.IGNORECASE)


class ThreeLayerMemory:
    """Keeps short-term state in AgentState and owns only scoped long-term stores."""

    def __init__(
        self,
        kv: SQLiteKVMemory,
        semantic: SQLiteVectorMemory,
        *,
        max_context_chars: int = 4000,
        max_semantic_top_k: int = 5,
        semantic_min_score: float = 0.08,
    ) -> None:
        if max_context_chars < 256:
            raise ValueError("max_context_chars must be at least 256")
        self.kv = kv
        self.semantic = semantic
        self.max_context_chars = max_context_chars
        if max_semantic_top_k < 1:
            raise ValueError("max_semantic_top_k must be positive")
        if not 0 <= semantic_min_score <= 1:
            raise ValueError("semantic_min_score must be between 0 and 1")
        self.max_semantic_top_k = max_semantic_top_k
        self.semantic_min_score = semantic_min_score

    @classmethod
    def from_sqlite(
        cls,
        database: str | Path,
        *,
        embedder: Embedder | None = None,
        max_context_chars: int = 4000,
        max_semantic_top_k: int = 5,
        semantic_min_score: float = 0.08,
    ) -> "ThreeLayerMemory":
        return cls(
            SQLiteKVMemory(database),
            SQLiteVectorMemory(database, embedder=embedder),
            max_context_chars=max_context_chars,
            max_semantic_top_k=max_semantic_top_k,
            semantic_min_score=semantic_min_score,
        )

    def recall(
        self,
        *,
        scope_id: str,
        query: str,
        relevant_kv_keys: Sequence[str] = (),
        top_k: int = 3,
    ) -> MemoryRecall:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        memories: list[dict[str, Any]] = []
        lines = [
            "长期 Memory（仅作历史辅助；当前文件、当前 schema 和 ToolResult 冲突时优先当前事实）："
        ]
        for key in dict.fromkeys(relevant_kv_keys):
            if key not in ALLOWED_KV_KEYS:
                continue
            entry = self.kv.get(scope_id, key)
            if entry is not None:
                item = entry.to_dict()
                line = f"KV {key}={json.dumps(entry.value, ensure_ascii=False)}"
                if _append_within_limit(lines, line, self.max_context_chars):
                    memories.append(item)

        for match in self.semantic.search(
            scope_id,
            query,
            top_k=min(top_k, self.max_semantic_top_k),
            min_score=self.semantic_min_score,
        ):
            item = match.to_dict()
            line = (
                f"Semantic[{match.entry.kind}, score={match.score:.3f}] "
                f"{match.entry.content}"
            )
            if _append_within_limit(lines, line, self.max_context_chars):
                memories.append(item)

        if len(lines) == 1:
            return MemoryRecall()
        return MemoryRecall(context="\n".join(lines), memories=memories)

    def remember(
        self,
        *,
        scope_id: str,
        requests: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        incoming = [requests] if isinstance(requests, Mapping) else list(requests)
        saved = []
        for request in incoming:
            if not isinstance(request, Mapping):
                raise ValueError("remember requests must be objects")
            memory_type = request.get("type")
            if memory_type == "kv":
                key = request.get("key")
                if key not in ALLOWED_KV_KEYS:
                    raise ValueError(f"KV memory key is not allowed: {key}")
                value = request.get("value")
                _validate_payload(value)
                serialized = json.dumps(value, ensure_ascii=False)
                if len(serialized) > 2000:
                    raise ValueError("KV memory value is too large")
                saved.append(self.kv.set(scope_id, key, value).to_dict())
                continue
            if memory_type == "semantic":
                kind = request.get("kind")
                if kind not in ALLOWED_SEMANTIC_KINDS:
                    raise ValueError(f"semantic memory kind is not allowed: {kind}")
                content = request.get("content")
                metadata = request.get("metadata", {})
                _validate_semantic_content(content)
                _validate_payload(metadata)
                memory_id = request.get("id")
                if memory_id and self.semantic.get(scope_id, memory_id) is not None:
                    entry = self.semantic.update(
                        scope_id,
                        memory_id,
                        content=content,
                        kind=kind,
                        metadata=metadata,
                    )
                else:
                    entry = self.semantic.add(
                        scope_id,
                        content,
                        kind=kind,
                        metadata=metadata,
                        memory_id=memory_id,
                    )
                saved.append(entry.to_dict())
                continue
            raise ValueError("remember request type must be 'kv' or 'semantic'")
        return saved

    def close(self) -> None:
        self.kv.close()
        self.semantic.close()


def _append_within_limit(lines: list[str], line: str, limit: int) -> bool:
    current_length = len("\n".join(lines))
    available = limit - current_length - 1
    if available <= 16:
        return False
    if len(line) > available:
        line = line[: available - 1] + "…"
    lines.append(line)
    return True


def _validate_payload(value: Any, path: str = "value") -> None:
    if isinstance(value, Mapping):
        blocked = BLOCKED_PAYLOAD_KEYS.intersection(str(key).lower() for key in value)
        if blocked:
            raise ValueError(f"{path} contains non-memory runtime data: {sorted(blocked)[0]}")
        for key, item in value.items():
            _validate_payload(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_payload(item, f"{path}[{index}]")
    elif isinstance(value, str) and RUNTIME_DATASET_ID.search(value):
        raise ValueError(f"{path} contains a temporary dataset identifier")
    else:
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{path} must be JSON serializable") from error


def _validate_semantic_content(content: Any) -> None:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("semantic memory content must be a non-empty string")
    content = content.strip()
    if len(content) > 4000:
        raise ValueError("semantic memory content is too large")
    lowered = content.lower()
    if RUNTIME_DATASET_ID.search(content):
        raise ValueError("temporary dataset identifiers cannot be stored in semantic memory")
    if any(marker in lowered for marker in ('"tool_call_id"', '"execution_trace"', '"todos"')):
        raise ValueError("runtime Todo or Observation data cannot be stored in semantic memory")
    if re.search(r'"status"\s*:\s*"(?:pending|in_progress|completed)"', lowered):
        raise ValueError("Todo snapshots cannot be stored in semantic memory")
    if content.startswith("PK\x03\x04") or _looks_like_delimited_table(content):
        raise ValueError("raw CSV/XLSX data cannot be stored in semantic memory")


def _looks_like_delimited_table(content: str) -> bool:
    lines = [line for line in content.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    for delimiter in (",", "\t", ";"):
        counts = [line.count(delimiter) for line in lines[:20]]
        if counts and counts[0] >= 1 and sum(count == counts[0] for count in counts) >= len(counts) - 1:
            return True
    return False
