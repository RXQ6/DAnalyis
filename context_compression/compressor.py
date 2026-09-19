"""Build a bounded LLM context view without mutating Agent runtime state."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CompressionPolicy:
    trigger_total_chars: int = 28_000
    target_total_chars: int = 20_000
    single_tool_result_chars: int = 8_000
    message_count_trigger: int = 36
    dataset_column_trigger: int = 80
    dataset_profile_column_limit: int = 40
    keep_recent_turns: int = 4
    keep_recent_tool_results: int = 4
    memory_view_chars: int = 2_000
    keep_completed_todos: int = 3


@dataclass
class CompressionResult:
    messages: list[dict[str, Any]]
    report: dict[str, Any] = field(default_factory=dict)


class ContextCompressor:
    """Applies deterministic reductions only to a deep-copied message view."""

    def __init__(self, policy: CompressionPolicy | None = None) -> None:
        self.policy = policy or CompressionPolicy()

    def compress(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        state: Any | None = None,
    ) -> CompressionResult:
        del state
        original = copy.deepcopy(messages)
        original_chars = _serialized_chars(original, tools)
        reasons = self._trigger_reasons(original, original_chars)
        if not reasons:
            return CompressionResult(
                original,
                {
                    "triggered": False,
                    "originalChars": original_chars,
                    "viewChars": original_chars,
                    "strategies": [],
                    "triggerReasons": [],
                    "policy": asdict(self.policy),
                },
            )

        view = copy.deepcopy(original)
        strategies: list[str] = []
        current_user_index = _last_role_index(view, "user")
        latest_tool_index = _last_role_index(view, "tool")

        strategies.extend(self._compact_named_system_messages(view))
        if self._compact_dataset_profiles(view, current_user_index):
            strategies.append("dataset_profile")
        if self._compact_tool_messages(view, latest_tool_index):
            strategies.append("tool_result_metadata")

        view, removed_turns = self._truncate_history(view)
        if removed_turns:
            strategies.append("history_turn_truncation")

        if _serialized_chars(view, tools) > self.policy.target_total_chars:
            if self._reduce_conversation_results_to_latest(view):
                strategies.append("conversation_result_refs")
            view, additionally_removed = self._truncate_history(view, keep_turns=1)
            removed_turns += additionally_removed

        return CompressionResult(
            view,
            {
                "triggered": True,
                "originalChars": original_chars,
                "viewChars": _serialized_chars(view, tools),
                "strategies": list(dict.fromkeys(strategies)),
                "triggerReasons": reasons,
                "removedHistoryTurns": removed_turns,
                "latestToolResultPreserved": latest_tool_index is not None,
                "policy": asdict(self.policy),
            },
        )

    def _trigger_reasons(
        self, messages: list[dict[str, Any]], total_chars: int
    ) -> list[str]:
        reasons = []
        if total_chars >= self.policy.trigger_total_chars:
            reasons.append("total_chars")
        if len(messages) >= self.policy.message_count_trigger:
            reasons.append("message_count")
        if any(
            message.get("role") == "tool"
            and len(str(message.get("content", ""))) >= self.policy.single_tool_result_chars
            for message in messages
        ):
            reasons.append("large_tool_result")
        if _maximum_dataset_columns(messages) >= self.policy.dataset_column_trigger:
            reasons.append("wide_dataset")
        return reasons

    def _compact_named_system_messages(self, messages: list[dict[str, Any]]) -> list[str]:
        strategies: list[str] = []
        for message in messages:
            if message.get("name") == "memory_context":
                limited = _limit_memory(
                    str(message.get("content", "")), self.policy.memory_view_chars
                )
                if limited != message.get("content"):
                    message["content"] = limited
                    strategies.append("memory_limit")
            elif message.get("name") == "conversation_context":
                if self._compact_conversation_context(message):
                    strategies.append("conversation_tool_results")
            elif str(message.get("content", "")).startswith("当前 Todo 概览"):
                if self._compact_todo_message(message):
                    strategies.append("todo_summary")
        return strategies

    def _compact_conversation_context(self, message: dict[str, Any]) -> bool:
        prefix, payload = _split_json_content(str(message.get("content", "")))
        if not isinstance(payload, dict):
            return False
        results = payload.get("priorToolResults")
        if not isinstance(results, list) or not results:
            return False
        recent_count = max(1, self.policy.keep_recent_tool_results)
        older = results[:-recent_count]
        recent = results[-recent_count:]
        payload["priorToolResultRefs"] = [_tool_result_reference(item) for item in older]
        payload["priorToolResults"] = [
            _compact_prior_tool_result(item, preserve_data=True) for item in recent
        ]
        message["content"] = prefix + json.dumps(payload, ensure_ascii=False)
        return True

    def _compact_todo_message(self, message: dict[str, Any]) -> bool:
        prefix, payload = _split_json_content(str(message.get("content", "")))
        if not isinstance(payload, dict):
            return False
        completed = payload.get("completed")
        if not isinstance(completed, list):
            return False
        payload["completedCount"] = len(completed)
        payload["completed"] = completed[-self.policy.keep_completed_todos :]
        message["content"] = prefix + json.dumps(payload, ensure_ascii=False)
        return True

    def _compact_dataset_profiles(
        self, messages: list[dict[str, Any]], current_user_index: int | None
    ) -> bool:
        changed = False
        current_user_text = (
            _message_text(messages[current_user_index])
            if current_user_index is not None
            else ""
        )
        for index, message in enumerate(messages):
            context = message.get("dataset_context")
            if not isinstance(context, dict):
                continue
            if index != current_user_index:
                datasets = context.get("datasets", [])
                message["dataset_context"] = {
                    "datasetCount": context.get("datasetCount", len(datasets)),
                    "datasetIds": [
                        item.get("datasetId")
                        for item in datasets
                        if isinstance(item, dict) and item.get("datasetId")
                    ],
                    "profileOmitted": True,
                }
                changed = True
                continue
            compact = _compact_dataset_context(
                context,
                current_user_text,
                self.policy.dataset_profile_column_limit,
            )
            if compact != context:
                message["dataset_context"] = compact
                changed = True
        return changed

    @staticmethod
    def _compact_tool_messages(
        messages: list[dict[str, Any]], latest_tool_index: int | None
    ) -> bool:
        changed = False
        for index, message in enumerate(messages):
            if message.get("role") != "tool" or index == latest_tool_index:
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            try:
                observation = json.loads(content)
            except json.JSONDecodeError:
                continue
            if not isinstance(observation, dict):
                continue
            compact = {
                key: copy.deepcopy(observation[key])
                for key in ("tool", "ok", "data", "error", "truncated")
                if key in observation
                and observation[key] is not None
                and not (key == "truncated" and observation[key] is False)
            }
            message["content"] = json.dumps(compact, ensure_ascii=False)
            changed = True
        return changed

    def _truncate_history(
        self, messages: list[dict[str, Any]], *, keep_turns: int | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        current_user_index = _last_role_index(messages, "user")
        if current_user_index is None:
            return messages, 0
        keep_turns = self.policy.keep_recent_turns if keep_turns is None else keep_turns
        prefix = [
            copy.deepcopy(message)
            for message in messages[:current_user_index]
            if message.get("role") == "system"
        ]
        history_non_system = [
            copy.deepcopy(message)
            for message in messages[:current_user_index]
            if message.get("role") != "system"
        ]
        turns = _message_turns(history_non_system)
        kept = turns[-keep_turns:] if keep_turns > 0 else []
        flattened = [message for turn in kept for message in turn]
        tail = copy.deepcopy(messages[current_user_index:])
        return [*prefix, *flattened, *tail], max(0, len(turns) - len(kept))

    @staticmethod
    def _reduce_conversation_results_to_latest(messages: list[dict[str, Any]]) -> bool:
        for message in messages:
            if message.get("name") != "conversation_context":
                continue
            prefix, payload = _split_json_content(str(message.get("content", "")))
            if not isinstance(payload, dict):
                return False
            results = payload.get("priorToolResults")
            if not isinstance(results, list) or len(results) <= 1:
                return False
            refs = payload.setdefault("priorToolResultRefs", [])
            refs.extend(_tool_result_reference(item) for item in results[:-1])
            payload["priorToolResults"] = [results[-1]]
            message["content"] = prefix + json.dumps(payload, ensure_ascii=False)
            return True
        return False


def _serialized_chars(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    return len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False))


def _last_role_index(messages: list[dict[str, Any]], role: str) -> int | None:
    return next(
        (index for index in range(len(messages) - 1, -1, -1) if messages[index].get("role") == role),
        None,
    )


def _split_json_content(content: str) -> tuple[str, Any]:
    for separator in ("：", ":"):
        if separator in content:
            head, raw = content.split(separator, 1)
            try:
                return head + separator, json.loads(raw)
            except json.JSONDecodeError:
                continue
    return content, None


def _limit_memory(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    lines = content.splitlines()
    kept: list[str] = []
    kv_lines = [line for line in lines if line.startswith("KV ")]
    semantic_lines = [line for line in lines if not line.startswith("KV ")]
    for line in [*semantic_lines[:1], *kv_lines, *semantic_lines[1:]]:
        candidate = "\n".join([*kept, line])
        if len(candidate) > max(0, limit - 24):
            continue
        kept.append(line)
    return "\n".join([*kept, "[较低优先级 Memory 已省略]"])


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _maximum_dataset_columns(messages: list[dict[str, Any]]) -> int:
    maximum = 0
    for message in messages:
        context = message.get("dataset_context")
        if not isinstance(context, dict):
            continue
        for dataset in context.get("datasets", []):
            if isinstance(dataset, dict):
                maximum = max(maximum, len(dataset.get("columns", [])))
    return maximum


def _compact_dataset_context(
    context: dict[str, Any], relevant_text: str, column_limit: int
) -> dict[str, Any]:
    datasets = []
    for dataset in context.get("datasets", []):
        if not isinstance(dataset, dict):
            continue
        columns = [
            column
            for column in dataset.get("columns", [])
            if isinstance(column, dict) and isinstance(column.get("name"), str)
        ]
        relevant_indexes = [
            index
            for index, column in enumerate(columns)
            if column["name"] and column["name"] in relevant_text
        ]
        relevant_set = set(relevant_indexes)
        max_columns = max(1, column_limit)
        selected_indexes = list(relevant_indexes[:max_columns])
        selected_set = set(selected_indexes)
        representative_budget = max_columns - len(selected_indexes)

        # Give every available type one representative before filling the
        # remaining budget in stable source order.
        for column_type in dict.fromkeys(
            str(column.get("type", "unknown")) for column in columns
        ):
            if representative_budget <= 0:
                break
            representative = next(
                (
                    index
                    for index, column in enumerate(columns)
                    if index not in selected_set
                    and str(column.get("type", "unknown")) == column_type
                ),
                None,
            )
            if representative is not None:
                selected_indexes.append(representative)
                selected_set.add(representative)
                representative_budget -= 1
        for index in range(len(columns)):
            if representative_budget <= 0:
                break
            if index in selected_set:
                continue
            selected_indexes.append(index)
            selected_set.add(index)
            representative_budget -= 1

        selected_indexes.sort()
        columns_by_type: dict[str, list[str]] = {}
        for index in selected_indexes:
            column = columns[index]
            name = column["name"]
            column_type = column.get("type", "unknown")
            columns_by_type.setdefault(str(column_type), []).append(name)
        relevant_columns = [
            copy.deepcopy(columns[index])
            for index in selected_indexes
            if index in relevant_set
        ]
        compact = {
            key: copy.deepcopy(dataset[key])
            for key in (
                "datasetId",
                "filename",
                "format",
                "sizeBytes",
                "rowCount",
                "columnCount",
                "dateRanges",
                "derived",
                "lineage",
            )
            if key in dataset
        }
        compact["columnsByType"] = columns_by_type
        compact["omittedColumnCount"] = max(0, len(columns) - len(selected_indexes))
        if relevant_columns:
            compact["relevantColumns"] = relevant_columns
        datasets.append(compact)
    return {"datasetCount": context.get("datasetCount", len(datasets)), "datasets": datasets}


def _compact_prior_tool_result(value: Any, *, preserve_data: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"invalidResult": True}
    result = value.get("toolResult")
    compact_result = {}
    if isinstance(result, dict):
        for key in ("ok", "data", "error", "truncated"):
            if key not in result or result[key] is None:
                continue
            if key == "truncated" and result[key] is False:
                continue
            if key == "data" and not preserve_data:
                continue
            compact_result[key] = copy.deepcopy(result[key])
    return {
        "callId": value.get("callId"),
        "toolName": value.get("toolName"),
        "arguments": copy.deepcopy(value.get("arguments", {})),
        "toolResult": compact_result,
    }


def _tool_result_reference(value: Any) -> dict[str, Any]:
    compact = _compact_prior_tool_result(value, preserve_data=False)
    result = value.get("toolResult") if isinstance(value, dict) else None
    compact["ok"] = result.get("ok") if isinstance(result, dict) else None
    compact["dataOmitted"] = True
    compact.pop("toolResult", None)
    return compact


def _message_turns(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    turns: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "user" and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)
    return turns
