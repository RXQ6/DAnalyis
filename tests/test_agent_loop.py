from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from agent.loop import AgentLoop
from tools.handlers import build_default_registry
from tools.registry import ToolDefinition, ToolRegistry


ROOT = Path(__file__).resolve().parents[1]
SALES = ROOT / "tests" / "fixtures" / "sales.csv"


class ScriptedModel:
    def __init__(self, decisions: list[Any]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        decision = self.decisions[len(self.calls) - 1]
        return decision(messages) if callable(decision) else decision


class RepeatingModel:
    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.call_count += 1
        return {"type": "tool_call", "id": f"repeat-{self.call_count}", "name": "inspect_data", "arguments": {}}


class AgentLoopTests(unittest.TestCase):
    def test_case_a_single_tool_then_final_answer(self) -> None:
        def final_after_observation(messages: list[dict[str, Any]]) -> dict[str, Any]:
            self.assertEqual(messages[-1]["role"], "tool")
            observation = json.loads(messages[-1]["content"])
            self.assertEqual(observation["tool"], "basic_stats")
            self.assertEqual(observation["result"]["value"], 1580)
            return {"type": "final_answer", "content": "销售额总和为 1580。"}

        model = ScriptedModel([
            {"type": "tool_call", "id": "stats-1", "name": "basic_stats", "arguments": {"metric": "销售额", "operation": "sum"}},
            final_after_observation,
        ])
        state = AgentLoop(model, build_default_registry()).run("计算销售额总和", dataset=str(SALES))

        self.assertEqual(state.stop_reason, "final_answer")
        self.assertEqual(state.final_answer, "销售额总和为 1580。")
        self.assertEqual(state.iteration, 2)
        self.assertEqual([call["name"] for call in state.tool_calls], ["basic_stats"])
        self.assertEqual(state.execution_trace[0]["status"], "ok")

    def test_case_b_observation_drives_a_second_different_tool(self) -> None:
        def choose_trend(messages: list[dict[str, Any]]) -> dict[str, Any]:
            first = json.loads(messages[-1]["content"])
            self.assertEqual(first["tool"], "group_compare")
            self.assertEqual(first["result"]["groups"][0]["group"], "华南")
            return {
                "type": "tool_call",
                "id": "trend-1",
                "name": "trend_analysis",
                "arguments": {"dateField": "日期", "metric": "销售额", "operation": "sum", "filters": {"地区": "华东"}},
            }

        def final_after_trend(messages: list[dict[str, Any]]) -> dict[str, Any]:
            second = json.loads(messages[-1]["content"])
            self.assertEqual(second["tool"], "trend_analysis")
            self.assertEqual(
                [(point["date"], point["value"]) for point in second["result"]["points"]],
                [("2026-01-01", 100), ("2026-01-02", 150), ("2026-01-03", 130)],
            )
            return {"type": "final_answer", "content": "已完成地区对比，并基于工具结果分析华东趋势。"}

        model = ScriptedModel([
            {"type": "tool_call", "id": "group-1", "name": "group_compare", "arguments": {"groupBy": "地区", "metric": "销售额", "operation": "sum"}},
            choose_trend,
            final_after_trend,
        ])
        state = AgentLoop(model, build_default_registry()).run(
            "找出销售下降最严重的地区，再分析该地区最近 6 个月趋势",
            dataset=str(SALES),
            schema={"columns": ["日期", "地区", "产品", "销售额"]},
        )

        self.assertEqual(state.stop_reason, "final_answer")
        self.assertEqual(state.iteration, 3)
        self.assertEqual([call["name"] for call in state.tool_calls], ["group_compare", "trend_analysis"])
        self.assertEqual([entry["iteration"] for entry in state.execution_trace], [1, 2])
        self.assertEqual(len([message for message in state.messages if message["role"] == "tool"]), 2)

    def test_case_c_max_iter_stops_repeating_model(self) -> None:
        registry = ToolRegistry()
        executions = []
        registry.register(ToolDefinition("inspect_data", "test inspection", {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, lambda arguments, context: executions.append(context["iteration"]) or {"rows": 1}))
        model = RepeatingModel()

        state = AgentLoop(model, registry, max_iter=3).run("不断检查", dataset="unused.csv")

        self.assertEqual(state.stop_reason, "max_iter")
        self.assertEqual(state.iteration, 3)
        self.assertEqual(model.call_count, 3)
        self.assertEqual(executions, [1, 2, 3])
        self.assertEqual(len(state.tool_calls), 3)
        self.assertIsNone(state.final_answer)

    def test_unrecoverable_tool_error_is_observed_and_stops(self) -> None:
        model = ScriptedModel([
            {"type": "tool_call", "id": "unknown-1", "name": "not_registered", "arguments": {}},
        ])
        state = AgentLoop(model, ToolRegistry()).run("调用未知工具", dataset="unused.csv")

        self.assertEqual(state.stop_reason, "unrecoverable_tool_error")
        self.assertEqual(state.iteration, 1)
        self.assertEqual(state.execution_trace[0]["status"], "error")
        self.assertEqual(state.execution_trace[0]["observation"]["error"]["code"], "unknown_tool")
        self.assertEqual(state.messages[-1]["role"], "tool")

    def test_default_registry_exposes_current_tools(self) -> None:
        names = {item["function"]["name"] for item in build_default_registry().tool_schemas()}
        self.assertTrue({"inspect_data", "basic_stats", "group_compare", "trend_analysis", "detect_anomaly"}.issubset(names))

    def test_default_max_iter_is_six(self) -> None:
        loop = AgentLoop(RepeatingModel(), ToolRegistry())
        self.assertEqual(loop.max_iter, 6)


if __name__ == "__main__":
    unittest.main()

