from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from workflow import AnalysisNode, CalcNode, ChatNode, MemoryRecallNode


@dataclass
class FakeAgentState:
    stop_reason: str = "final_answer"
    final_answer: str = "完成"
    execution_trace: list[dict[str, Any]] = field(default_factory=list)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, question: str, **kwargs: Any) -> FakeAgentState:
        self.calls.append((question, kwargs))
        return FakeAgentState()


class FakeRecall:
    context = "长期偏好：销售额"
    memories = [{"key": "preferred_metric", "value": "销售额"}]


class FakeMemory:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def recall(self, **kwargs: Any) -> FakeRecall:
        self.calls.append(kwargs)
        return FakeRecall()


class WorkflowNodeTests(unittest.TestCase):
    def test_analysis_node_only_adapts_conversation_runner(self) -> None:
        runner = FakeRunner()
        result = AnalysisNode(runner).invoke(
            {
                "query": "分析销售额",
                "dataset_paths": ["sales.csv"],
                "memory_scope": "user-a",
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["response"], "完成")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0], "分析销售额")
        self.assertEqual(runner.calls[0][1]["dataset_paths"], ["sales.csv"])

    def test_calc_node_is_deterministic_and_rejects_code(self) -> None:
        result = CalcNode().invoke({"query": "请计算 (1 + 2) * 3"})
        self.assertEqual(result["data"]["value"], 9)
        rejected = CalcNode().invoke({"query": "__import__('os').system('whoami')"})
        self.assertEqual(rejected["status"], "error")

    def test_memory_recall_is_read_only_and_requires_scope(self) -> None:
        memory = FakeMemory()
        missing = MemoryRecallNode(memory).invoke({"query": "记得什么"})
        self.assertEqual(missing["status"], "needs_input")
        result = MemoryRecallNode(memory).invoke(
            {"query": "记得我的指标吗", "memory_scope": "user-a"}
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(memory.calls), 1)
        self.assertEqual(memory.calls[0]["scope_id"], "user-a")

    def test_chat_node_does_not_need_analysis_services(self) -> None:
        result = ChatNode(lambda query, state: f"chat:{query}").invoke({"query": "你好"})
        self.assertEqual(result["response"], "chat:你好")


if __name__ == "__main__":
    unittest.main()
