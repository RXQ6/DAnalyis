"""Lazy Skill discovery and full-definition loading."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts import SkillDefinition, SkillDescriptor, SkillMatch


DEFAULT_DEFINITIONS = Path(__file__).resolve().parent / "definitions"
DEFAULT_CATALOG = DEFAULT_DEFINITIONS / "catalog.json"

_NON_ACTIONABLE_TRIGGER_PATTERNS = (
    r"(?:什么是|解释|介绍|定义).{0,12}(?:数据诊断|异常原因|波动原因|根因分析)",
    r"(?:数据诊断|异常原因|波动原因|根因分析).{0,12}(?:是什么意思|的定义|的概念)",
    r"(?:异常原因|波动原因|根因分析).{0,8}(?:字段|列名).{0,8}(?:改名|重命名)",
)


class SkillRegistry:
    """Loads discovery metadata eagerly and full instructions only after a match."""

    def __init__(
        self,
        *,
        catalog_path: str | Path | None = None,
        definitions_root: str | Path | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path or DEFAULT_CATALOG).resolve()
        self.definitions_root = Path(definitions_root or DEFAULT_DEFINITIONS).resolve()
        self._descriptors: tuple[SkillDescriptor, ...] | None = None
        self._loaded: dict[str, SkillDefinition] = {}

    @property
    def loaded_skill_names(self) -> tuple[str, ...]:
        return tuple(self._loaded)

    def discover(self, state: Mapping[str, Any]) -> SkillMatch | None:
        query = str(state.get("query", "")).strip()
        has_dataset = bool(state.get("dataset_paths") or state.get("active_dataset_ids"))
        if any(re.search(pattern, query, re.I) for pattern in _NON_ACTIONABLE_TRIGGER_PATTERNS):
            return None
        for descriptor in self._catalog():
            if descriptor.requires_dataset and not has_dataset:
                continue
            for pattern in descriptor.trigger_patterns:
                match = re.search(pattern, query, re.I)
                if match:
                    return SkillMatch(
                        name=descriptor.name,
                        source="rule",
                        rule="explicit_data_diagnosis",
                        matched_text=match.group(0),
                    )
        return None

    def load(self, name: str) -> SkillDefinition:
        if name in self._loaded:
            return self._loaded[name]
        descriptor = next(
            (item for item in self._catalog() if item.name == name),
            None,
        )
        if descriptor is None:
            raise ValueError(f"skill is not registered: {name}")
        definition_path = self._safe_path(descriptor.definition_path)
        instruction_path = self._safe_path(descriptor.instruction_path)
        raw = self._read_json(definition_path, "skill definition")
        instructions = instruction_path.read_text(encoding="utf-8")
        definition = self._parse_definition(raw, descriptor, instructions)
        self._loaded[name] = definition
        return definition

    def _catalog(self) -> tuple[SkillDescriptor, ...]:
        if self._descriptors is not None:
            return self._descriptors
        raw = self._read_json(self.catalog_path, "skill catalog")
        entries = raw.get("skills") if isinstance(raw, dict) else None
        if not isinstance(entries, list) or not entries:
            raise ValueError("skill catalog must contain a non-empty skills array")
        descriptors = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("skill catalog entries must be objects")
            patterns = entry.get("triggerPatterns")
            if not isinstance(patterns, list) or not patterns or any(
                not isinstance(pattern, str) or not pattern for pattern in patterns
            ):
                raise ValueError("skill triggerPatterns must be non-empty strings")
            descriptor = SkillDescriptor(
                name=self._required_string(entry, "name"),
                description=self._required_string(entry, "description"),
                trigger_patterns=tuple(patterns),
                requires_dataset=bool(entry.get("requiresDataset", False)),
                definition_path=self._required_string(entry, "definitionPath"),
                instruction_path=self._required_string(entry, "instructionPath"),
            )
            descriptors.append(descriptor)
        names = [item.name for item in descriptors]
        if len(names) != len(set(names)):
            raise ValueError("skill catalog contains duplicate names")
        self._descriptors = tuple(descriptors)
        return self._descriptors

    def _parse_definition(
        self,
        raw: Any,
        descriptor: SkillDescriptor,
        instructions: str,
    ) -> SkillDefinition:
        if not isinstance(raw, dict):
            raise ValueError("skill definition must be an object")
        name = self._required_string(raw, "name")
        description = self._required_string(raw, "description")
        version = self._required_string(raw, "version")
        if name != descriptor.name or description != descriptor.description:
            raise ValueError("skill catalog and definition metadata do not match")
        allowed = self._string_list(raw, "allowedTools")
        workflow = self._string_list(raw, "workflow")
        boundaries = self._string_list(raw, "boundaries")
        trigger = raw.get("trigger")
        contract = raw.get("outputContract")
        if not isinstance(trigger, dict) or not isinstance(contract, dict):
            raise ValueError("skill trigger and outputContract must be objects")
        if not instructions.strip():
            raise ValueError("SKILL.md cannot be empty")
        return SkillDefinition(
            name=name,
            version=version,
            description=description,
            allowed_tools=tuple(allowed),
            trigger=copy.deepcopy(trigger),
            workflow=tuple(workflow),
            boundaries=tuple(boundaries),
            output_contract=copy.deepcopy(contract),
            instructions=instructions,
        )

    def _safe_path(self, relative: str) -> Path:
        candidate = (self.definitions_root / relative).resolve()
        if self.definitions_root not in candidate.parents:
            raise ValueError("skill path escapes definitions root")
        if not candidate.is_file():
            raise ValueError(f"skill file does not exist: {relative}")
        return candidate

    @staticmethod
    def _read_json(path: Path, label: str) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"unable to load {label}: {path}") from error

    @staticmethod
    def _required_string(value: Mapping[str, Any], key: str) -> str:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"skill {key} must be a non-empty string")
        return item.strip()

    @staticmethod
    def _string_list(value: Mapping[str, Any], key: str) -> list[str]:
        items = value.get(key)
        if not isinstance(items, list) or not items or any(
            not isinstance(item, str) or not item.strip() for item in items
        ):
            raise ValueError(f"skill {key} must contain non-empty strings")
        normalized = [item.strip() for item in items]
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"skill {key} cannot contain duplicates")
        return normalized
