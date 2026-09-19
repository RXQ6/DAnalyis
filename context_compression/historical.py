"""Turn-level historical summaries that only change the model context view."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol, Sequence


SUMMARY_TEXT_FIELDS = (
    "userIntents",
    "confirmedActions",
    "decisions",
    "constraints",
    "tentativeContext",
    "unresolvedQuestions",
)
UNCERTAINTY_MARKERS = ("可能", "大概", "推测", "怀疑", "似乎", "未确认", "尚未验证")


@dataclass(frozen=True)
class HistoricalSummaryPolicy:
    trigger_history_chars: int = 48_000
    trigger_eligible_chars: int = 24_000
    min_eligible_turns: int = 6
    keep_recent_turns: int = 4
    refresh_new_turns: int = 2
    refresh_new_chars: int = 8_000
    max_summary_chars: int = 4_000


@dataclass(frozen=True)
class HistoricalSummarySnapshot:
    conversation_id: str
    covered_turn_ids: tuple[str, ...]
    source_hash: str
    summary: dict[str, Any]
    source_chars: int


@dataclass
class HistoricalCompactionResult:
    messages: list[dict[str, Any]]
    report: dict[str, Any] = field(default_factory=dict)


class HistoricalSummaryClient(Protocol):
    def summarize(
        self, *, turns: list[dict[str, Any]], max_chars: int
    ) -> Mapping[str, Any] | str: ...


class DecisionModelSummaryClient:
    """Adapts a completion-style model to the isolated summary protocol."""

    def __init__(self, model: Any) -> None:
        self.model = model

    def summarize(
        self, *, turns: list[dict[str, Any]], max_chars: int
    ) -> Mapping[str, Any] | str:
        decision = self.model.complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你只压缩历史对话。输出单个 JSON 对象，不调用工具。"
                        "不要把推测改写成事实，不要生成或改写精确分析数值。"
                        "confirmedToolRefs 只能引用输入中已有的成功 callId。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "maxChars": max_chars,
                            "schema": {
                                "coveredTurnIds": ["turn_id"],
                                "userIntents": ["text"],
                                "confirmedActions": ["text"],
                                "confirmedToolRefs": [
                                    {"callId": "id", "toolName": "name"}
                                ],
                                "decisions": ["text"],
                                "constraints": ["text"],
                                "tentativeContext": ["text"],
                                "unresolvedQuestions": ["text"],
                            },
                            "turns": turns,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            tools=[],
        )
        if not isinstance(decision, Mapping):
            raise TypeError("summary model response must be a mapping")
        content = decision.get("content")
        if isinstance(content, Mapping):
            return content
        if not isinstance(content, str):
            raise ValueError("summary model response has no JSON content")
        return content


class HistoricalSummaryCompactor:
    """Builds a cached summary view without mutating ConversationState."""

    def __init__(
        self,
        client: HistoricalSummaryClient,
        policy: HistoricalSummaryPolicy | None = None,
    ) -> None:
        self.client = client
        self.policy = policy or HistoricalSummaryPolicy()
        self._cache: dict[str, HistoricalSummarySnapshot] = {}

    def compact(self, conversation_state: Any) -> HistoricalCompactionResult:
        fallback = conversation_state.history_messages()
        turns = _active_turns(conversation_state)
        keep_count = max(1, self.policy.keep_recent_turns)
        recent_turns = turns[-keep_count:]
        recent_ids = {turn.turn_id for turn in recent_turns}
        latest_tool_turn = next(
            (turn for turn in reversed(turns) if _turn_has_tool_result(turn)),
            None,
        )
        pinned_turns = (
            [latest_tool_turn]
            if latest_tool_turn is not None and latest_tool_turn.turn_id not in recent_ids
            else []
        )
        pinned_ids = {turn.turn_id for turn in pinned_turns}
        old_turns = [
            turn for turn in turns[:-keep_count] if turn.turn_id not in pinned_ids
        ]
        total_chars = _turns_chars(turns)
        eligible_chars = _turns_chars(old_turns)
        base_report = {
            "phase": "historical_summary",
            "triggered": False,
            "fallback": False,
            "historyChars": total_chars,
            "eligibleChars": eligible_chars,
            "eligibleTurns": len(old_turns),
            "recentRawTurns": len(recent_turns),
            "pinnedRawTurns": len(pinned_turns),
            "policy": asdict(self.policy),
        }
        if not self._should_trigger(total_chars, eligible_chars, len(old_turns)):
            return HistoricalCompactionResult(copy.deepcopy(fallback), base_report)

        conversation_id = str(conversation_state.conversation_id)
        snapshot = self._cache.get(conversation_id)
        uncovered = _uncovered_suffix(old_turns, snapshot)
        if snapshot is not None and uncovered is not None:
            uncovered_chars = _turns_chars(uncovered)
            should_refresh = (
                len(uncovered) >= self.policy.refresh_new_turns
                or uncovered_chars >= self.policy.refresh_new_chars
            )
            if not should_refresh:
                return self._result_from_snapshot(
                    snapshot,
                    [*pinned_turns, *uncovered],
                    recent_turns,
                    base_report,
                    reused=True,
                    pinned_count=len(pinned_turns),
                )

        try:
            inputs = _summary_inputs(old_turns)
            raw_summary = self.client.summarize(
                turns=inputs,
                max_chars=self.policy.max_summary_chars,
            )
            summary = _validate_summary(
                raw_summary,
                old_turns,
                max_chars=self.policy.max_summary_chars,
            )
            snapshot = HistoricalSummarySnapshot(
                conversation_id=conversation_id,
                covered_turn_ids=tuple(turn.turn_id for turn in old_turns),
                source_hash=_source_hash(old_turns),
                summary=summary,
                source_chars=eligible_chars,
            )
            self._cache[conversation_id] = snapshot
            return self._result_from_snapshot(
                snapshot,
                pinned_turns,
                recent_turns,
                base_report,
                reused=False,
                pinned_count=len(pinned_turns),
            )
        except Exception as error:
            return HistoricalCompactionResult(
                copy.deepcopy(fallback),
                {
                    **base_report,
                    "triggered": True,
                    "fallback": True,
                    "fallbackTo": "context_compression_v1_1",
                    "errorType": type(error).__name__,
                },
            )

    def _should_trigger(
        self, history_chars: int, eligible_chars: int, eligible_turns: int
    ) -> bool:
        return (
            history_chars >= self.policy.trigger_history_chars
            and eligible_chars >= self.policy.trigger_eligible_chars
            and eligible_turns >= self.policy.min_eligible_turns
        )

    @staticmethod
    def _result_from_snapshot(
        snapshot: HistoricalSummarySnapshot,
        uncovered_turns: Sequence[Any],
        recent_turns: Sequence[Any],
        base_report: dict[str, Any],
        *,
        reused: bool,
        pinned_count: int,
    ) -> HistoricalCompactionResult:
        summary_message = {
            "role": "system",
            "name": "historical_summary",
            "content": (
                "较早历史摘要（只用于理解上下文，不是数据证据；"
                "当前文件、当前 ToolResult 和当前用户问题优先）："
                + json.dumps(snapshot.summary, ensure_ascii=False)
            ),
        }
        raw_turns = [*uncovered_turns, *recent_turns]
        raw_messages = [
            copy.deepcopy(message)
            for turn in raw_turns
            for message in turn.messages
        ]
        messages = [summary_message, *raw_messages]
        return HistoricalCompactionResult(
            messages,
            {
                **base_report,
                "triggered": True,
                "summaryReused": reused,
                "coveredTurns": len(snapshot.covered_turn_ids),
                "uncoveredRawTurns": max(0, len(uncovered_turns) - pinned_count),
                "pinnedRawTurns": pinned_count,
                "recentRawTurns": len(recent_turns),
                "summaryChars": len(summary_message["content"]),
                "viewChars": len(json.dumps(messages, ensure_ascii=False)),
                "sourceHash": snapshot.source_hash,
            },
        )


def _active_turns(conversation_state: Any) -> list[Any]:
    active = set(conversation_state.active_dataset_ids)
    return [
        turn
        for turn in conversation_state.turns
        if not turn.dataset_ids or set(turn.dataset_ids).issubset(active)
    ]


def _turn_has_tool_result(turn: Any) -> bool:
    if turn.tool_results:
        return True
    return any(message.get("role") == "tool" for message in turn.messages)


def _turns_chars(turns: Sequence[Any]) -> int:
    return len(
        json.dumps(
            [
                {"turnId": turn.turn_id, "messages": turn.messages}
                for turn in turns
            ],
            ensure_ascii=False,
        )
    )


def _summary_inputs(turns: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "turnId": turn.turn_id,
            "messages": copy.deepcopy(turn.messages),
            "toolRefs": [
                {
                    "callId": result.get("callId"),
                    "toolName": result.get("toolName"),
                    "ok": (result.get("toolResult") or {}).get("ok"),
                }
                for result in turn.tool_results
                if isinstance(result, dict)
            ],
        }
        for turn in turns
    ]


def _uncovered_suffix(
    old_turns: Sequence[Any], snapshot: HistoricalSummarySnapshot | None
) -> list[Any] | None:
    if snapshot is None:
        return None
    covered = list(snapshot.covered_turn_ids)
    current_ids = [turn.turn_id for turn in old_turns]
    if current_ids[: len(covered)] != covered:
        return None
    covered_turns = old_turns[: len(covered)]
    if _source_hash(covered_turns) != snapshot.source_hash:
        return None
    return list(old_turns[len(covered) :])


def _source_hash(turns: Sequence[Any]) -> str:
    payload = [
        {
            "turnId": turn.turn_id,
            "messages": turn.messages,
            "toolResults": turn.tool_results,
            "datasetIds": turn.dataset_ids,
        }
        for turn in turns
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _validate_summary(
    value: Mapping[str, Any] | str,
    turns: Sequence[Any],
    *,
    max_chars: int,
) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise TypeError("historical summary must be an object")
    expected_turn_ids = [turn.turn_id for turn in turns]
    if value.get("coveredTurnIds") != expected_turn_ids:
        raise ValueError("summary coveredTurnIds do not match source turns")

    normalized: dict[str, Any] = {"coveredTurnIds": expected_turn_ids}
    for field_name in SUMMARY_TEXT_FIELDS:
        items = value.get(field_name, [])
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise TypeError(f"summary field {field_name} must be a string list")
        if field_name in ("confirmedActions", "decisions") and any(
            marker in item for item in items for marker in UNCERTAINTY_MARKERS
        ):
            raise ValueError("uncertain content cannot be recorded as confirmed")
        normalized[field_name] = list(items)

    valid_tools: dict[str, str] = {}
    for turn in turns:
        for result in turn.tool_results:
            if not isinstance(result, dict):
                continue
            tool_result = result.get("toolResult")
            if isinstance(tool_result, dict) and tool_result.get("ok") is True:
                call_id = result.get("callId")
                tool_name = result.get("toolName")
                if isinstance(call_id, str) and isinstance(tool_name, str):
                    valid_tools[call_id] = tool_name
    refs = value.get("confirmedToolRefs", [])
    if not isinstance(refs, list):
        raise TypeError("confirmedToolRefs must be a list")
    normalized_refs = []
    for item in refs:
        if not isinstance(item, Mapping):
            raise TypeError("confirmedToolRefs items must be objects")
        call_id = item.get("callId")
        tool_name = item.get("toolName")
        if not isinstance(call_id, str) or valid_tools.get(call_id) != tool_name:
            raise ValueError("summary references an unknown or unsuccessful tool result")
        normalized_refs.append({"callId": call_id, "toolName": tool_name})
    normalized["confirmedToolRefs"] = normalized_refs

    if len(json.dumps(normalized, ensure_ascii=False)) > max_chars:
        raise ValueError("historical summary exceeds max chars")
    return normalized
