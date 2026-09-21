from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval_harness import EvalCase, EvalResult, EvalRunner, EvalSuite


def all_pass_gate(results: list[EvalResult]) -> dict:
    passed = all(result.passed for result in results)
    return {
        "passed": passed,
        "metrics": {"passRate": sum(result.passed for result in results) / len(results)},
        "gates": {"allCasesPassed": passed},
    }


class EvalHarnessTest(unittest.TestCase):
    def test_eval_case_keeps_identity_and_metadata(self) -> None:
        case = EvalCase("E-01", "answer", "demo", lambda: {}, "sample", {"tag": "fast"})
        self.assertEqual(case.case_id, "E-01")
        self.assertEqual(case.suite, "sample")
        self.assertEqual(case.metadata["tag"], "fast")

    def test_runner_normalizes_success(self) -> None:
        case = EvalCase(
            "E-02",
            "answer",
            "success",
            lambda: {
                "passed": True,
                "answer": {"value": 3},
                "trace_summary": {"tool_calls": ["statistics"]},
                "latency": 0.25,
            },
            "sample",
        )
        result = EvalRunner().run_case(case)
        self.assertTrue(result.passed)
        self.assertIsNone(result.failure_reason)
        self.assertEqual(result.answer, {"value": 3})
        self.assertEqual(result.latency, 0.25)

    def test_runner_joins_failure_reasons(self) -> None:
        case = EvalCase(
            "E-03",
            "tool",
            "failure",
            lambda: {"passed": False, "failures": ["wrong_tool", "wrong_args"]},
            "sample",
        )
        result = EvalRunner().run_case(case)
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_reason, "wrong_tool; wrong_args")

    def test_runner_contains_executor_exception(self) -> None:
        def broken() -> dict:
            raise ValueError("bad fixture")

        result = EvalRunner().run_case(EvalCase("E-04", "harness", "broken", broken))
        self.assertFalse(result.passed)
        self.assertIn("harness_or_process_error:ValueError", result.failure_reason or "")

    def test_runner_applies_suite_gate(self) -> None:
        suite = EvalSuite(
            "sample",
            (
                EvalCase("E-05", "answer", "ok", lambda: {"passed": True}, "sample"),
                EvalCase("E-06", "answer", "bad", lambda: {"passed": False}, "sample"),
            ),
            all_pass_gate,
        )
        report = EvalRunner().run([suite])
        self.assertFalse(report["passed"])
        self.assertEqual(report["passed_cases"], 1)
        self.assertEqual(report["total_cases"], 2)

    def test_report_is_json_serializable(self) -> None:
        suite = EvalSuite(
            "sample",
            (EvalCase("E-07", "answer", "ok", lambda: {"passed": True}, "sample"),),
            all_pass_gate,
        )
        report = EvalRunner().run([suite])
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "report.json"
            EvalRunner.write_report(report, destination)
            loaded = json.loads(destination.read_text(encoding="utf-8"))
        self.assertTrue(loaded["passed"])
        self.assertIn("trace_summary", loaded["results"][0])


if __name__ == "__main__":
    unittest.main()
