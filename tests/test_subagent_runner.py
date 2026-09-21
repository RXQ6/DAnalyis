from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from datasets import DatasetRegistry
from subagents import DataCheckSubAgentRunner, SubAgentLimits
from tools import build_default_registry


class ScriptedModel:
    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = decisions
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        return self.decisions[len(self.calls) - 1]


class RepeatingInspectModel:
    def __init__(self, dataset_id: str) -> None:
        self.dataset_id = dataset_id
        self.calls = 0

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.calls += 1
        return {
            "type": "tool_call",
            "id": f"inspect-{self.calls}",
            "name": "inspect_data",
            "arguments": {"datasetId": self.dataset_id},
        }


class SlowModel:
    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        time.sleep(0.2)
        return {"type": "final_answer", "content": "too late"}


class SubAgentRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        dataset = root / "sales.csv"
        dataset.write_text("地区,销售额\n华东,10\n华南,20\n", encoding="utf-8")
        self.datasets = DatasetRegistry(root / "derived")
        self.dataset_id = self.datasets.register(dataset)["datasetId"]
        self.registry = build_default_registry()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_runner_has_isolated_messages_and_returns_sanitized_result(self) -> None:
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "inspect-1",
                    "name": "inspect_data",
                    "arguments": {"datasetId": self.dataset_id},
                },
                {"type": "final_answer", "content": "结构和缺失值检查完成。"},
            ]
        )
        result = DataCheckSubAgentRunner(model, self.registry).run(
            subtask_id="sub-test",
            task="检查字段结构和缺失值",
            dataset_id=self.dataset_id,
            dataset_registry=self.datasets,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"], "结构和缺失值检查完成。")
        self.assertEqual(result["evidence"][0]["toolName"], "inspect_data")
        self.assertEqual(
            set(result),
            {
                "subtaskId", "status", "summary", "evidence", "usedDatasetIds",
                "warnings", "stopReason", "usage", "error",
            },
        )
        serialized = json.dumps(result, ensure_ascii=False)
        for forbidden in ("messages", "execution_trace", "todos", "memory_context"):
            self.assertNotIn(forbidden, serialized)
        model_context = json.dumps(model.calls, ensure_ascii=False)
        self.assertNotIn("PARENT_SECRET_MARKER", model_context)
        tool_names = {
            item["function"]["name"] for item in model.calls[0]["tools"]
        }
        self.assertEqual(tool_names, {"inspect_data", "basic_stats", "detect_anomaly"})

    def test_runner_has_independent_iteration_limit(self) -> None:
        model = RepeatingInspectModel(self.dataset_id)
        result = DataCheckSubAgentRunner(
            model,
            self.registry,
            limits=SubAgentLimits(max_iterations=2),
        ).run(
            subtask_id="sub-max-iter",
            task="反复检查",
            dataset_id=self.dataset_id,
            dataset_registry=self.datasets,
        )
        self.assertEqual(result["status"], "max_iter")
        self.assertEqual(result["usage"]["iterations"], 2)
        self.assertEqual(model.calls, 2)

    def test_runner_returns_timeout_without_internal_context(self) -> None:
        started = time.monotonic()
        result = DataCheckSubAgentRunner(
            SlowModel(),
            self.registry,
            limits=SubAgentLimits(timeout_seconds=0.03),
        ).run(
            subtask_id="sub-timeout",
            task="慢检查",
            dataset_id=self.dataset_id,
            dataset_registry=self.datasets,
        )
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["error"]["code"], "subagent_timeout")
        self.assertLess(time.monotonic() - started, 0.18)

    def test_runner_bounds_the_summary_returned_to_parent(self) -> None:
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "inspect-bounded",
                    "name": "inspect_data",
                    "arguments": {"datasetId": self.dataset_id},
                },
                {"type": "final_answer", "content": "很长摘要" * 20},
            ]
        )
        result = DataCheckSubAgentRunner(
            model,
            self.registry,
            limits=SubAgentLimits(max_summary_chars=20),
        ).run(
            subtask_id="sub-bounded",
            task="检查摘要限制",
            dataset_id=self.dataset_id,
            dataset_registry=self.datasets,
        )
        self.assertLessEqual(len(result["summary"]), 20)
        self.assertIn("summary_truncated", result["warnings"])

    def test_separate_runs_do_not_share_messages_or_state(self) -> None:
        model = ScriptedModel(
            [
                {
                    "type": "tool_call",
                    "id": "inspect-first",
                    "name": "inspect_data",
                    "arguments": {"datasetId": self.dataset_id},
                },
                {"type": "final_answer", "content": "第一次完成"},
                {
                    "type": "tool_call",
                    "id": "inspect-second",
                    "name": "inspect_data",
                    "arguments": {"datasetId": self.dataset_id},
                },
                {"type": "final_answer", "content": "第二次完成"},
            ]
        )
        runner = DataCheckSubAgentRunner(model, self.registry)
        first = runner.run(
            subtask_id="sub-first",
            task="FIRST_SUBTASK_SECRET",
            dataset_id=self.dataset_id,
            dataset_registry=self.datasets,
        )
        second = runner.run(
            subtask_id="sub-second",
            task="SECOND_SUBTASK",
            dataset_id=self.dataset_id,
            dataset_registry=self.datasets,
        )
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        second_first_messages = json.dumps(model.calls[2]["messages"], ensure_ascii=False)
        self.assertNotIn("FIRST_SUBTASK_SECRET", second_first_messages)
        self.assertIn("SECOND_SUBTASK", second_first_messages)
        self.assertIsNot(model.calls[0]["messages"], model.calls[2]["messages"])


if __name__ == "__main__":
    unittest.main()
