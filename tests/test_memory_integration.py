from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.loop import AgentLoop
from memory.service import ThreeLayerMemory
from tools.handlers import build_default_registry


ROOT = Path(__file__).resolve().parents[1]
SALES = ROOT / "tests" / "fixtures" / "sales.csv"


class ScriptedModel:
    def __init__(self, decisions: list[Any]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        decision = self.decisions[len(self.calls) - 1]
        return decision(messages) if callable(decision) else decision


class FailingMemory:
    def recall(self, **kwargs: Any) -> Any:
        del kwargs
        raise RuntimeError("memory unavailable")

    def remember(self, **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        raise RuntimeError("memory unavailable")


class MemoryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.memory = ThreeLayerMemory.from_sqlite(
            Path(self.directory.name) / "memory.sqlite3", max_context_chars=1000
        )

    def tearDown(self) -> None:
        self.memory.close()
        self.directory.cleanup()

    def test_recall_enters_context_and_only_relevant_kv_is_included(self) -> None:
        self.memory.remember(
            scope_id="user-a",
            requests=[
                {"type": "kv", "key": "preferred_chart_type", "value": "line"},
                {"type": "kv", "key": "default_time_column", "value": "日期"},
                {
                    "type": "semantic",
                    "kind": "sop",
                    "content": "趋势分析先确认日期字段，再选择聚合粒度。",
                },
            ],
        )
        model = ScriptedModel([{"type": "final_answer", "content": "收到。"}])

        state = AgentLoop(model, build_default_registry(), memory=self.memory).run(
            "请分析销售趋势",
            dataset=str(SALES),
            memory_scope="user-a",
            memory_top_k=1,
        )

        memory_messages = [
            message
            for message in model.calls[0]["messages"]
            if message.get("name") == "memory_context"
        ]
        self.assertEqual(len(memory_messages), 1)
        self.assertIn("default_time_column", memory_messages[0]["content"])
        self.assertNotIn("preferred_chart_type", memory_messages[0]["content"])
        self.assertIn("趋势分析先确认日期字段", memory_messages[0]["content"])
        self.assertLessEqual(len(state.memory_context), 1000)
        self.assertTrue(state.recalled_memories)

    def test_explicit_remember_is_recalled_by_a_later_request(self) -> None:
        first = AgentLoop(
            ScriptedModel([{"type": "final_answer", "content": "已完成。"}]),
            build_default_registry(),
            memory=self.memory,
        ).run(
            "以后趋势分析怎么做",
            memory_scope="user-a",
            remember={
                "type": "semantic",
                "kind": "analysis_experience",
                "content": "销售趋势分析应先确认日期字段。",
            },
        )
        second_model = ScriptedModel([{"type": "final_answer", "content": "已召回。"}])
        second = AgentLoop(
            second_model, build_default_registry(), memory=self.memory
        ).run("再次分析销售趋势和日期", memory_scope="user-a")

        self.assertEqual(len(first.remembered_memories), 1)
        self.assertTrue(second.recalled_memories)
        self.assertIn("销售趋势分析应先确认日期字段", second.memory_context)

    def test_current_tool_result_has_priority_over_conflicting_memory(self) -> None:
        self.memory.remember(
            scope_id="user-a",
            requests={
                "type": "semantic",
                "kind": "analysis_summary",
                "content": "历史销售额总和是 999。",
            },
        )

        def answer_from_current_observation(messages: list[dict[str, Any]]) -> dict[str, Any]:
            observation = json.loads(messages[-1]["content"])
            self.assertEqual(observation["data"]["value"], 1580)
            memory_text = next(
                message["content"]
                for message in messages
                if message.get("name") == "memory_context"
            )
            self.assertIn("999", memory_text)
            return {"type": "final_answer", "content": "当前销售额总和为 1580。"}

        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "sum-current",
                    "name": "basic_stats",
                    "arguments": {"metric": "销售额", "operation": "sum"},
                },
                answer_from_current_observation,
            ]
        )
        state = AgentLoop(model, build_default_registry(), memory=self.memory).run(
            "计算销售额总和",
            dataset=str(SALES),
            memory_scope="user-a",
        )

        self.assertEqual(state.final_answer, "当前销售额总和为 1580。")
        self.assertEqual(state.execution_trace[0]["data"]["value"], 1580)

    def test_todo_and_dataset_are_not_automatically_persisted(self) -> None:
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "todo",
                    "name": "todo_write",
                    "arguments": {
                        "updates": [
                            {"id": "inspect", "content": "检查数据", "status": "completed"}
                        ]
                    },
                },
                {"type": "final_answer", "content": "完成。"},
            ]
        )

        state = AgentLoop(model, build_default_registry(), memory=self.memory).run(
            "检查文件", dataset=str(SALES), memory_scope="user-a"
        )

        self.assertEqual(len(state.todos), 1)
        self.assertEqual(self.memory.kv.list("user-a"), [])
        self.assertEqual(self.memory.semantic.list("user-a"), [])

    def test_raw_csv_and_todo_snapshots_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "raw CSV/XLSX"):
            self.memory.remember(
                scope_id="user-a",
                requests={
                    "type": "semantic",
                    "kind": "analysis_summary",
                    "content": "日期,地区,销售额\n2026-01-01,华东,100\n2026-01-02,华南,200",
                },
            )
        with self.assertRaisesRegex(ValueError, "Todo"):
            self.memory.remember(
                scope_id="user-a",
                requests={
                    "type": "semantic",
                    "kind": "sop",
                    "content": '{"todos":[{"content":"检查", "status":"pending"}]}',
                },
            )
        self.assertEqual(self.memory.semantic.list("user-a"), [])

    def test_temporary_dataset_ids_cannot_enter_long_term_memory(self) -> None:
        with self.assertRaisesRegex(ValueError, "temporary dataset identifier"):
            self.memory.remember(
                scope_id="user-a",
                requests={"type": "kv", "key": "preferred_metric", "value": "ds_123456789abc"},
            )
        with self.assertRaisesRegex(ValueError, "temporary dataset identifiers"):
            self.memory.remember(
                scope_id="user-a",
                requests={"type": "semantic", "kind": "analysis_summary", "content": "继续分析 ds_123456789abc"},
            )
        with self.assertRaisesRegex(ValueError, "non-memory runtime data"):
            self.memory.remember(
                scope_id="user-a",
                requests={"type": "semantic", "kind": "sop", "content": "分析前检查字段。", "metadata": {"datasetId": "external"}},
            )
        self.assertEqual(self.memory.kv.list("user-a"), [])
        self.assertEqual(self.memory.semantic.list("user-a"), [])

    def test_remember_does_not_run_when_loop_does_not_finish(self) -> None:
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "inspect",
                    "name": "inspect_data",
                    "arguments": {},
                }
            ]
        )

        state = AgentLoop(
            model, build_default_registry(), max_iter=1, memory=self.memory
        ).run(
            "检查数据",
            dataset=str(SALES),
            memory_scope="user-a",
            remember={"type": "kv", "key": "preferred_metric", "value": "销售额"},
        )

        self.assertEqual(state.stop_reason, "max_iter")
        self.assertIsNone(self.memory.kv.get("user-a", "preferred_metric"))

    def test_memory_failures_do_not_control_agent_loop(self) -> None:
        state = AgentLoop(
            ScriptedModel([{"type": "final_answer", "content": "正常完成。"}]),
            build_default_registry(),
            memory=FailingMemory(),
        ).run(
            "完成当前任务",
            memory_scope="user-a",
            remember={"type": "kv", "key": "preferred_metric", "value": "销售额"},
        )

        self.assertEqual(state.stop_reason, "final_answer")
        self.assertEqual(state.final_answer, "正常完成。")
        self.assertEqual(
            [error["phase"] for error in state.memory_errors], ["recall", "remember"]
        )

    def test_recall_filters_irrelevant_memory_caps_top_k_and_context(self) -> None:
        limited = ThreeLayerMemory.from_sqlite(
            Path(self.directory.name) / "limited.sqlite3",
            max_context_chars=300,
            max_semantic_top_k=2,
            semantic_min_score=0.12,
        )
        try:
            for index in range(5):
                limited.remember(
                    scope_id="user-a",
                    requests={
                        "type": "semantic",
                        "kind": "sop",
                        "content": f"销售趋势规则 {index}：先检查日期字段并按月汇总。",
                    },
                )
            limited.remember(
                scope_id="user-a",
                requests={
                    "type": "semantic",
                    "kind": "analysis_experience",
                    "content": "员工排班时优先确认门店营业时间。",
                },
            )

            recall = limited.recall(
                scope_id="user-a",
                query="分析营收走势和时间列",
                top_k=100,
            )

            semantic = [item for item in recall.memories if item["type"] == "semantic"]
            self.assertLessEqual(len(semantic), 2)
            self.assertTrue(semantic)
            self.assertTrue(all("销售趋势规则" in item["content"] for item in semantic))
            self.assertNotIn("员工排班", recall.context)
            self.assertLessEqual(len(recall.context), 300)
        finally:
            limited.close()

    def test_explicit_semantic_id_updates_instead_of_duplicating(self) -> None:
        first = self.memory.remember(
            scope_id="user-a",
            requests={
                "type": "semantic",
                "kind": "sop",
                "content": "趋势分析先检查日期字段。",
            },
        )[0]
        updated = self.memory.remember(
            scope_id="user-a",
            requests={
                "type": "semantic",
                "id": first["id"],
                "kind": "sop",
                "content": "趋势分析先检查日期字段和聚合粒度。",
                "metadata": {"version": 2},
            },
        )[0]

        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(updated["metadata"], {"version": 2})
        self.assertEqual(len(self.memory.semantic.list("user-a")), 1)


if __name__ == "__main__":
    unittest.main()
