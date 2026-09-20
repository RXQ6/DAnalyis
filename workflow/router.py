"""Rule-first request router for the outer Workflow layer."""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from typing import Any, Protocol

from .calculator import can_calculate
from .state import Route


class RouterModel(Protocol):
    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


_ANALYSIS_ACTION = re.compile(
    r"分析|统计|趋势|异常|离群|分组|对比|比较|排名|排序|占比|同比|环比|"
    r"求和|总和|平均|最大|最小|中位数|画图|图表|可视化|"
    r"analy[sz]e|statistics?|trend|anomal|outlier|group|compare|rank|chart|plot",
    re.I,
)
_DATA_REFERENCE = re.compile(
    r"数据|文件|表格|字段|列|行|销售|利润|金额|收入|成本|指标|地区|日期|"
    r"dataset|file|table|column|row|metric|sales|revenue|profit|cost|date",
    re.I,
)
_MEMORY_RECALL = re.compile(
    r"(?:还)?记得|记忆|我.*偏好|之前.*(?:说|设置|记住)|"
    r"remember|memory|my preference|what did i",
    re.I,
)
_CHAT = re.compile(
    r"^\s*(?:你好|您好|嗨|hello|hi|hey|谢谢|感谢|再见|你是谁|你能做什么)\s*[！!。.?？]*\s*$",
    re.I,
)
_FOLLOW_UP = re.compile(
    r"^(?:那|那么|改为|改看|继续|再|还是|只看|不要|刚才|上一个|前面)|"
    r"^(?:then|instead|continue|what about|how about|previous)",
    re.I,
)


class RuleRouter:
    """Selects a registered route; an optional model is used only for ambiguity."""

    def __init__(self, fallback_model: RouterModel | None = None) -> None:
        self.fallback_model = fallback_model

    def route(
        self, state: Mapping[str, Any], *, allowed_routes: Collection[str]
    ) -> dict[str, Any]:
        allowed = frozenset(allowed_routes)
        query = str(state.get("query", "")).strip()
        has_datasets = bool(state.get("dataset_paths") or state.get("active_dataset_ids"))

        decision = self._rule_decision(query, has_datasets=has_datasets)
        if decision is not None:
            route, rule = decision
            return self._validated(route, allowed, source="rule", rule=rule)

        if self.fallback_model is not None:
            raw: Any = None
            try:
                raw = self.fallback_model.complete(
                    messages=self._fallback_messages(query, has_datasets, allowed),
                    tools=[],
                )
                candidate = self._extract_route(raw)
                if candidate in allowed:
                    return {
                        "route": candidate,
                        "source": "llm_fallback",
                        "rule": None,
                    }
            except Exception as error:
                raw = {"errorType": type(error).__name__}
            return self._safe_fallback(
                allowed,
                has_datasets=has_datasets,
                reason="invalid_llm_route",
                raw=raw,
            )

        return self._safe_fallback(
            allowed,
            has_datasets=has_datasets,
            reason="no_fallback_model",
        )

    @staticmethod
    def _rule_decision(query: str, *, has_datasets: bool) -> tuple[str, str] | None:
        analysis_action = bool(_ANALYSIS_ACTION.search(query))
        data_reference = bool(_DATA_REFERENCE.search(query))
        if analysis_action and (has_datasets or data_reference):
            return Route.ANALYSIS.value, "dataset_analysis_intent"
        if _MEMORY_RECALL.search(query) and not analysis_action:
            return Route.MEMORY_RECALL.value, "explicit_memory_recall"
        if can_calculate(query):
            return Route.CALC.value, "deterministic_arithmetic"
        if _CHAT.fullmatch(query):
            return Route.CHAT.value, "explicit_chat"
        if has_datasets and (_FOLLOW_UP.search(query) or query):
            return Route.ANALYSIS.value, "active_dataset_follow_up"
        return None

    @staticmethod
    def _fallback_messages(
        query: str, has_datasets: bool, allowed: Collection[str]
    ) -> list[dict[str, Any]]:
        routes = sorted(allowed)
        return [
            {
                "role": "system",
                "content": (
                    "你是请求分类器，只决定处理路径，不回答问题。"
                    f"只能返回 JSON：{{\"route\": <{routes}>}}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"query": query, "hasActiveDataset": has_datasets},
                    ensure_ascii=False,
                ),
            },
        ]

    @staticmethod
    def _extract_route(raw: Any) -> str | None:
        if not isinstance(raw, Mapping):
            return None
        candidate = raw.get("route")
        if candidate is None and isinstance(raw.get("content"), str):
            content = raw["content"].strip()
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = {"route": content}
            candidate = parsed.get("route") if isinstance(parsed, Mapping) else None
        return candidate.strip().lower() if isinstance(candidate, str) else None

    @staticmethod
    def _validated(
        route: str, allowed: Collection[str], *, source: str, rule: str
    ) -> dict[str, Any]:
        if route not in allowed:
            raise ValueError(f"router selected an unregistered route: {route}")
        return {"route": route, "source": source, "rule": rule}

    @staticmethod
    def _safe_fallback(
        allowed: Collection[str],
        *,
        has_datasets: bool,
        reason: str,
        raw: Any = None,
    ) -> dict[str, Any]:
        preferred = Route.ANALYSIS.value if has_datasets else Route.CHAT.value
        if preferred not in allowed:
            raise ValueError("safe fallback route is not registered")
        result = {"route": preferred, "source": "safe_fallback", "rule": reason}
        if raw is not None:
            result["invalidOutputType"] = type(raw).__name__
        return result
