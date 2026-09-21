from __future__ import annotations

import unittest

from eval_harness import EvalCase, EvalRunner, FailureType
from eval_harness.evaluators import (
    ContractEvaluator,
    RouteEvaluator,
    ToolEvaluator,
    TraceEvaluator,
)


def case_with(
    *, expectations: dict, evaluators: tuple[str, ...], observation: dict | None = None
) -> EvalCase:
    return EvalCase(
        "PROCESS-01",
        "process",
        "process evaluator case",
        lambda: {"passed": True, **(observation or {})},
        "process",
        expectations=expectations,
        evaluators=evaluators,
    )


class RouteEvaluatorTest(unittest.TestCase):
    def test_accepts_supported_matching_route(self) -> None:
        result = RouteEvaluator().evaluate(
            case_with(expectations={"route": "analysis"}, evaluators=()),
            {"route": "analysis"},
        )
        self.assertTrue(result.passed)
        self.assertTrue(result.values["route_correct"])

    def test_route_mismatch_is_routing_error(self) -> None:
        result = RouteEvaluator().evaluate(
            case_with(expectations={"route": "calc"}, evaluators=()),
            {"route": "chat"},
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "ROUTING_ERROR")

    def test_invalid_route_is_routing_error(self) -> None:
        result = RouteEvaluator().evaluate(
            case_with(expectations={"route": "memory_recall"}, evaluators=()),
            {"route": "invented"},
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "ROUTING_ERROR")


class ToolEvaluatorTest(unittest.TestCase):
    def test_expected_tool_passes(self) -> None:
        result = ToolEvaluator().evaluate(
            case_with(
                expectations={"tools": {"expected": ["statistics"], "allowed": ["statistics"]}},
                evaluators=(),
            ),
            {"trace": {"available": True, "tool_calls": [{"tool": "statistics", "status": "ok"}]}},
        )
        self.assertTrue(result.passed)
        self.assertTrue(result.values["tool_correct"])

    def test_missing_tool_is_selection_error(self) -> None:
        result = ToolEvaluator().evaluate(
            case_with(
                expectations={"tools": {"expected": ["statistics"], "allowed": ["statistics"]}},
                evaluators=(),
            ),
            {"trace": {"available": True, "tool_calls": []}},
        )
        self.assertEqual(result.failure_type, "TOOL_SELECTION_ERROR")

    def test_unauthorized_tool_is_security_violation(self) -> None:
        result = ToolEvaluator().evaluate(
            case_with(
                expectations={"tools": {"expected": [], "allowed": ["statistics"]}},
                evaluators=(),
            ),
            {"trace": {"available": True, "tool_calls": [{"tool": "delete_file", "status": "ok"}]}},
        )
        self.assertEqual(result.failure_type, "SECURITY_VIOLATION")

    def test_failed_tool_is_execution_error(self) -> None:
        result = ToolEvaluator().evaluate(
            case_with(
                expectations={"tools": {"expected": ["statistics"], "allowed": ["statistics"]}},
                evaluators=(),
            ),
            {"trace": {"available": True, "tool_calls": [{"tool": "statistics", "status": "error"}]}},
        )
        self.assertEqual(result.failure_type, "TOOL_EXECUTION_ERROR")

    def test_duplicate_call_is_selection_error(self) -> None:
        call = {"tool": "statistics", "status": "ok", "args": {"metric": "销售额"}}
        result = ToolEvaluator().evaluate(
            case_with(
                expectations={"tools": {"expected": ["statistics"], "allowed": ["statistics"]}},
                evaluators=(),
            ),
            {"trace": {"available": True, "tool_calls": [call, dict(call)]}},
        )
        self.assertEqual(result.failure_type, "TOOL_SELECTION_ERROR")


class TraceEvaluatorTest(unittest.TestCase):
    def test_unavailable_trace_is_explicit_and_not_fabricated(self) -> None:
        result = TraceEvaluator().evaluate(
            case_with(expectations={}, evaluators=()), {"trace": {"available": False}}
        )
        self.assertTrue(result.passed)
        self.assertFalse(result.available)
        self.assertIsNone(result.values["tool_calls"])
        self.assertIsNone(result.values["loop_iterations"])

    def test_trace_metrics_are_counted(self) -> None:
        result = TraceEvaluator().evaluate(
            case_with(expectations={}, evaluators=()),
            {
                "trace": {
                    "available": True,
                    "tool_calls": [{"tool": "statistics", "args": {"metric": "销售额"}}],
                    "loop_iterations": 2,
                    "max_iter": 5,
                }
            },
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.values["tool_calls"], 1)
        self.assertEqual(result.values["loop_iterations"], 2)
        self.assertEqual(result.values["retry_count"], 0)

    def test_max_iter_termination_is_trace_error(self) -> None:
        result = TraceEvaluator().evaluate(
            case_with(expectations={}, evaluators=()),
            {
                "trace": {
                    "available": True,
                    "tool_calls": [],
                    "loop_iterations": 3,
                    "max_iter": 3,
                    "stop_reason": "max_iter",
                }
            },
        )
        self.assertEqual(result.failure_type, "TRACE_ERROR")


class ContractEvaluatorTest(unittest.TestCase):
    def test_structured_output_contract(self) -> None:
        case = case_with(
            expectations={
                "contract": {
                    "required": ["status", "result"],
                    "types": {"status": "string", "result": "object"},
                }
            },
            evaluators=(),
        )
        result = ContractEvaluator().evaluate(
            case, {"contract_value": {"status": "ok", "result": {"value": 3}}}
        )
        self.assertTrue(result.passed)
        self.assertTrue(result.values["contract_valid"])

    def test_tool_result_contract_failure(self) -> None:
        case = case_with(
            expectations={"contract": {"kind": "tool_result"}}, evaluators=()
        )
        result = ContractEvaluator().evaluate(case, {"contract_value": {"ok": True}})
        self.assertEqual(result.failure_type, "CONTRACT_ERROR")

    def test_skill_invocation_contract_failure(self) -> None:
        case = case_with(
            expectations={"contract": {"kind": "skill_invocation"}}, evaluators=()
        )
        result = ContractEvaluator().evaluate(
            case,
            {
                "contract_value": {
                    "skill_name": "data-diagnosis",
                    "status": "completed",
                    "tools_used": [],
                    "contract_valid": False,
                }
            },
        )
        self.assertEqual(result.failure_type, "CONTRACT_ERROR")


class RunnerProcessIntegrationTest(unittest.TestCase):
    def test_runner_invokes_all_process_evaluators(self) -> None:
        trace = {
            "available": True,
            "tool_calls": [{"tool": "statistics", "status": "ok"}],
            "loop_iterations": 1,
            "max_iter": 3,
        }
        case = case_with(
            expectations={
                "route": "analysis",
                "tools": {"expected": ["statistics"], "allowed": ["statistics"]},
                "contract": {"required": ["status"]},
            },
            evaluators=("route", "tool", "trace", "contract"),
            observation={
                "route": "analysis",
                "trace": trace,
                "trace_summary": {"available": True},
                "contract_value": {"status": "ok"},
            },
        )
        result = EvalRunner().run_case(case)
        self.assertTrue(result.passed)
        self.assertTrue(result.route_correct)
        self.assertTrue(result.tool_correct)
        self.assertTrue(result.contract_valid)
        self.assertTrue(result.trace_available)
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(result.loop_iterations, 1)
        self.assertEqual(result.retry_count, 0)
        self.assertIsNone(result.failure_type)

    def test_security_failure_has_priority(self) -> None:
        case = case_with(
            expectations={
                "route": "analysis",
                "tools": {"expected": ["statistics"], "allowed": ["statistics"]},
            },
            evaluators=("route", "tool"),
            observation={
                "route": "chat",
                "trace": {
                    "available": True,
                    "tool_calls": [{"tool": "delete_file", "status": "ok"}],
                },
            },
        )
        result = EvalRunner().run_case(case)
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "SECURITY_VIOLATION")


class FailureTaxonomyTest(unittest.TestCase):
    def test_required_failure_types_are_stable(self) -> None:
        required = {
            "ROUTING_ERROR",
            "TOOL_SELECTION_ERROR",
            "TOOL_EXECUTION_ERROR",
            "MEMORY_ERROR",
            "CONTEXT_ERROR",
            "CONTRACT_ERROR",
            "ANSWER_ERROR",
            "TIMEOUT",
            "SECURITY_VIOLATION",
        }
        self.assertTrue(required.issubset({str(item) for item in FailureType}))


if __name__ == "__main__":
    unittest.main()
