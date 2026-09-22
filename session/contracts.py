"""Public contracts for durable, thread-scoped sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SessionRecord:
    """Metadata for one long-lived task identified by ``thread_id``."""

    thread_id: str
    status: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SessionStoreError(RuntimeError):
    """Base error for stable SessionStore failures."""

    code = "session_store_error"


class SessionAlreadyExistsError(SessionStoreError):
    code = "session_already_exists"


class SessionNotFoundError(SessionStoreError):
    code = "session_not_found"


class SessionSerializationError(SessionStoreError):
    code = "session_serialization_error"
