"""Contracts for lazily discovered project-level Skills."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SkillDescriptor:
    name: str
    description: str
    trigger_patterns: tuple[str, ...]
    requires_dataset: bool
    definition_path: str
    instruction_path: str


@dataclass(frozen=True)
class SkillMatch:
    name: str
    source: Literal["rule"]
    rule: str
    matched_text: str


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    version: str
    description: str
    allowed_tools: tuple[str, ...]
    trigger: dict[str, Any]
    workflow: tuple[str, ...]
    boundaries: tuple[str, ...]
    output_contract: dict[str, Any]
    instructions: str


@dataclass(frozen=True)
class SkillInvocation:
    invocation_id: str
    skill_name: str
    skill_version: str
    trigger: dict[str, Any]
    status: str
    allowed_tools: tuple[str, ...]
    started_at: str
    duration_ms: float
    agent_stop_reason: str | None
    iterations: int
    contract_valid: bool
    tools_used: tuple[str, ...]
    output_errors: tuple[dict[str, Any], ...]
    trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
