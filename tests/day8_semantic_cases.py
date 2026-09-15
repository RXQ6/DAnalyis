from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent.loop import AgentLoop
from agent.state import AgentState
from tools.handlers import build_default_registry


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "semantic_fixtures"
Decision = dict[str, Any] | Callable[[list[dict[str, Any]]], dict[str, Any]]


class ObservationDrivenModel:
    def __init__(self, decisions: list[Decision]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        decision = self.decisions[len(self.calls) - 1]
        return decision(messages) if callable(decision) else decision


@dataclass(frozen=True)
class SemanticCase:
    case_id: str
    question: str
    dataset: Path
    expected_chain: list[str]
    expected_arguments: list[dict[str, Any]]
    expected_observations: list[dict[str, Any]]
    expected_answer: str
    date_from: str
    date_to: str
    decisions: Callable[[], list[Decision]]


def observation(messages: list[dict[str, Any]]) -> dict[str, Any]:
    if not messages or messages[-1].get("role") != "tool":
        raise AssertionError("the next decision did not receive a tool Observation")
    return json.loads(messages[-1]["content"])


def region_decisions() -> list[Decision]:
    selected: dict[str, str] = {}

    def continue_from_group(messages: list[dict[str, Any]]) -> dict[str, Any]:
        first = observation(messages)
        groups = first["result"]["groups"]
        selected["region"] = min(groups, key=lambda item: item["value"])["group"]
        return {
            "type": "tool_call",
            "id": "region-trend",
            "name": "trend_analysis",
            "arguments": {
                "dateField": "日期", "metric": "销售额", "operation": "sum",
                "filters": {"地区": selected["region"]},
            },
        }

    def final_from_trend(messages: list[dict[str, Any]]) -> dict[str, Any]:
        second = observation(messages)
        points = second["result"]["points"]
        return {
            "type": "final_answer",
            "content": f"{selected['region']}总销售额最低，为450；2026年1月至6月销售额从{points[0]['value']}降至{points[-1]['value']}。",
        }

    return [
        {"type": "tool_call", "id": "region-group", "name": "group_compare", "arguments": {"groupBy": "地区", "metric": "销售额", "operation": "sum"}},
        continue_from_group,
        final_from_trend,
    ]


def product_decisions() -> list[Decision]:
    selected: dict[str, str] = {}

    def continue_from_top(messages: list[dict[str, Any]]) -> dict[str, Any]:
        first = observation(messages)
        selected["product"] = first["result"]["items"][0]["label"]
        return {
            "type": "tool_call",
            "id": "product-trend",
            "name": "trend_analysis",
            "arguments": {
                "dateField": "日期", "metric": "销售额", "operation": "sum",
                "filters": {"产品": selected["product"]},
            },
        }

    def final_from_trend(messages: list[dict[str, Any]]) -> dict[str, Any]:
        second = observation(messages)
        points = second["result"]["points"]
        values = "、".join(str(point["value"]) for point in points)
        return {"type": "final_answer", "content": f"单月销售额最高的产品是{selected['product']}，最高值100；最近3个月销售额依次为{values}。"}

    return [
        {"type": "tool_call", "id": "product-top", "name": "top_n", "arguments": {"metric": "销售额", "label": "产品", "count": 1}},
        continue_from_top,
        final_from_trend,
    ]


def inspect_decisions() -> list[Decision]:
    def continue_from_schema(messages: list[dict[str, Any]]) -> dict[str, Any]:
        first = observation(messages)
        columns = {column["name"]: column["type"] for column in first["result"]["profile"]["columns"]}
        if columns.get("日期") != "date" or columns.get("利润") != "number":
            raise AssertionError("inspect_data did not establish the required date and numeric fields")
        return {
            "type": "tool_call",
            "id": "profit-trend",
            "name": "trend_analysis",
            "arguments": {
                "dateField": "日期", "metric": "利润", "operation": "sum",
                "filters": {"地区": "华南"},
            },
        }

    def final_from_trend(messages: list[dict[str, Any]]) -> dict[str, Any]:
        second = observation(messages)
        values = "、".join(str(point["value"]) for point in second["result"]["points"])
        return {"type": "final_answer", "content": f"字段检查通过；华南2026年第一季度利润依次为{values}，呈逐月上升。"}

    return [
        {"type": "tool_call", "id": "profit-inspect", "name": "inspect_data", "arguments": {}},
        continue_from_schema,
        final_from_trend,
    ]


CASES = [
    SemanticCase(
        "SEM-01", "找出总销售额最低的地区，再分析该地区2026年1月至6月趋势", FIXTURES / "region_6m.csv",
        ["group_compare", "trend_analysis"],
        [{"groupBy": "地区", "metric": "销售额", "operation": "sum"}, {"dateField": "日期", "metric": "销售额", "operation": "sum", "filters": {"地区": "华东"}}],
        [{"groups": [("华南", 1200), ("华东", 450)]}, {"points": [("2026-01-01", 100), ("2026-02-01", 90), ("2026-03-01", 80), ("2026-04-01", 70), ("2026-05-01", 60), ("2026-06-01", 50)]}],
        "华东总销售额最低，为450；2026年1月至6月销售额从100降至50。", "2026-01-01", "2026-06-01", region_decisions,
    ),
    SemanticCase(
        "SEM-02", "找出单月销售额最高的产品，再分析该产品2026年4月至6月趋势", FIXTURES / "product_3m.csv",
        ["top_n", "trend_analysis"],
        [{"metric": "销售额", "label": "产品", "count": 1}, {"dateField": "日期", "metric": "销售额", "operation": "sum", "filters": {"产品": "B"}}],
        [{"items": [("B", 100)]}, {"points": [("2026-04-01", 10), ("2026-05-01", 15), ("2026-06-01", 100)]}],
        "单月销售额最高的产品是B，最高值100；最近3个月销售额依次为10、15、100。", "2026-04-01", "2026-06-01", product_decisions,
    ),
    SemanticCase(
        "SEM-03", "先检查字段，再分析华南2026年第一季度利润趋势", FIXTURES / "profit_q1.csv",
        ["inspect_data", "trend_analysis"],
        [{}, {"dateField": "日期", "metric": "利润", "operation": "sum", "filters": {"地区": "华南"}}],
        [{"schema": {"日期": "date", "地区": "text", "利润": "number"}}, {"points": [("2026-01-01", 5), ("2026-02-01", 10), ("2026-03-01", 15)]}],
        "字段检查通过；华南2026年第一季度利润依次为5、10、15，呈逐月上升。", "2026-01-01", "2026-03-01", inspect_decisions,
    ),
]


def run_case(case: SemanticCase) -> tuple[AgentState, ObservationDrivenModel]:
    model = ObservationDrivenModel(case.decisions())
    state = AgentLoop(model, build_default_registry()).run(case.question, dataset=str(case.dataset))
    return state, model


def evaluate_case(case: SemanticCase, state: AgentState, model: ObservationDrivenModel) -> list[str]:
    failures: list[str] = []
    chain = [call["name"] for call in state.tool_calls]
    arguments = [call["arguments"] for call in state.tool_calls]
    if chain != case.expected_chain:
        failures.append(f"tool_chain:{chain!r}")
    if arguments != case.expected_arguments:
        failures.append(f"tool_arguments:{arguments!r}")
    if len(state.execution_trace) != 2 or any(item["status"] != "ok" for item in state.execution_trace):
        failures.append("execution_trace_status")
    else:
        first = state.execution_trace[0]["observation"]["result"]
        second = state.execution_trace[1]["observation"]["result"]
        expected_first, expected_second = case.expected_observations
        if "groups" in expected_first:
            actual = [(item["group"], item["value"]) for item in first.get("groups", [])]
            if actual != expected_first["groups"]:
                failures.append(f"first_observation:{actual!r}")
        if "items" in expected_first:
            actual = [(item["label"], item["value"]) for item in first.get("items", [])]
            if actual != expected_first["items"]:
                failures.append(f"first_observation:{actual!r}")
        if "schema" in expected_first:
            actual = {column["name"]: column["type"] for column in first.get("profile", {}).get("columns", [])}
            if actual != expected_first["schema"]:
                failures.append(f"first_observation:{actual!r}")
        actual_points = [(item["date"], item["value"]) for item in second.get("points", [])]
        if actual_points != expected_second["points"]:
            failures.append(f"second_observation:{actual_points!r}")
        dates = [date for date, _ in actual_points]
        if not dates or min(dates) < case.date_from or max(dates) > case.date_to:
            failures.append(f"time_range:{dates!r}")
    second_model_messages = model.calls[1]["messages"] if len(model.calls) > 1 else []
    if not second_model_messages or second_model_messages[-1].get("role") != "tool":
        failures.append("second_round_missing_first_observation")
    if state.final_answer != case.expected_answer:
        failures.append(f"final_answer:{state.final_answer!r}")
    if state.stop_reason != "final_answer" or state.iteration != 3:
        failures.append(f"stop:{state.stop_reason}/iteration:{state.iteration}")
    return failures

