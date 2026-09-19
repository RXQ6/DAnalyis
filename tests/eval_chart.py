"""Deterministic semantic evaluation for the first bar/line chart slice."""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.loop import AgentLoop
from tools.handlers import build_default_registry


FIXTURES = ROOT / "tests" / "fixtures"
RESULT = ROOT / "tests" / "results" / "chart-evaluation.json"


class ScriptedModel:
    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = decisions
        self.index = 0

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del messages, tools
        decision = self.decisions[self.index]
        self.index += 1
        return decision


@dataclass(frozen=True)
class Case:
    case_id: str
    question: str
    dataset: Path
    analysis_call: dict[str, Any]
    chart_call: dict[str, Any]
    expected_chart_type: str | None = None
    expected_error: str | None = None


CASES = [
    Case(
        "CHART-01",
        "根据时间序列生成销售额折线图",
        FIXTURES / "sales.csv",
        {
            "type": "tool_call",
            "id": "trend-1",
            "name": "trend_analysis",
            "arguments": {"dateField": "日期", "metric": "销售额", "operation": "sum"},
        },
        {
            "type": "tool_call",
            "id": "chart-1",
            "name": "generate_chart",
            "arguments": {"sourceCallId": "trend-1", "chartType": "line"},
        },
        expected_chart_type="line",
    ),
    Case(
        "CHART-02",
        "按地区生成销售额柱状图",
        FIXTURES / "sales.csv",
        {
            "type": "tool_call",
            "id": "group-1",
            "name": "group_compare",
            "arguments": {"groupBy": "地区", "metric": "销售额", "operation": "sum"},
        },
        {
            "type": "tool_call",
            "id": "chart-2",
            "name": "generate_chart",
            "arguments": {"sourceCallId": "group-1", "chartType": "bar"},
        },
        expected_chart_type="bar",
    ),
    Case(
        "CHART-03",
        "生成销售额 Top 5 产品柱状图",
        FIXTURES / "top_products.csv",
        {
            "type": "tool_call",
            "id": "top-1",
            "name": "top_n",
            "arguments": {"metric": "销售额", "label": "产品", "count": 5},
        },
        {
            "type": "tool_call",
            "id": "chart-3",
            "name": "generate_chart",
            "arguments": {"sourceCallId": "top-1", "chartType": "bar"},
        },
        expected_chart_type="bar",
    ),
    Case(
        "CHART-04",
        "分组结果不能错误生成为折线图",
        FIXTURES / "sales.csv",
        {
            "type": "tool_call",
            "id": "group-wrong",
            "name": "group_compare",
            "arguments": {"groupBy": "地区", "metric": "销售额", "operation": "sum"},
        },
        {
            "type": "tool_call",
            "id": "chart-wrong",
            "name": "generate_chart",
            "arguments": {"sourceCallId": "group-wrong", "chartType": "line"},
        },
        expected_error="incompatible_chart_type",
    ),
    Case(
        "CHART-05",
        "单个统计值不应伪造成图表序列",
        FIXTURES / "sales.csv",
        {
            "type": "tool_call",
            "id": "stats-1",
            "name": "basic_stats",
            "arguments": {"metric": "销售额", "operation": "sum"},
        },
        {
            "type": "tool_call",
            "id": "chart-stats",
            "name": "generate_chart",
            "arguments": {"sourceCallId": "stats-1", "chartType": "bar"},
        },
        expected_error="unsupported_chart_source",
    ),
]


def main() -> int:
    records = []
    with tempfile.TemporaryDirectory(prefix="chart-eval-") as artifacts:
        for case in CASES:
            model = ScriptedModel(
                [
                    case.analysis_call,
                    case.chart_call,
                    {"type": "final_answer", "content": "图表处理完成。"},
                ]
            )
            state = AgentLoop(model, build_default_registry()).run(
                case.question,
                dataset=str(case.dataset),
                artifact_dir=artifacts,
            )
            chart_trace = state.execution_trace[1]
            failures = []
            if case.expected_error:
                actual_error = (chart_trace["error"] or {}).get("code")
                if chart_trace["success"] or actual_error != case.expected_error:
                    failures.append(f"chart_error:{actual_error!r}")
            else:
                data = chart_trace["data"] or {}
                spec = data.get("spec", {})
                artifact = data.get("artifact", {})
                if not chart_trace["success"]:
                    failures.append("chart_failed")
                if spec.get("chartType") != case.expected_chart_type:
                    failures.append(f"chart_type:{spec.get('chartType')!r}")
                if spec.get("meta", {}).get("sourceCallId") != case.analysis_call["id"]:
                    failures.append("source_call_id")
                if not Path(artifact.get("path", "missing")).is_file():
                    failures.append("artifact_missing")
            if [call["name"] for call in state.tool_calls] != [
                case.analysis_call["name"],
                "generate_chart",
            ]:
                failures.append("tool_chain")
            records.append(
                {
                    "caseId": case.case_id,
                    "passed": not failures,
                    "toolChain": [call["name"] for call in state.tool_calls],
                    "chartTrace": {
                        "arguments": chart_trace["arguments"],
                        "success": chart_trace["success"],
                        "spec": (chart_trace["data"] or {}).get("spec"),
                        "artifact": {
                            key: value
                            for key, value in (chart_trace["data"] or {})
                            .get("artifact", {})
                            .items()
                            if key != "path"
                        },
                        "error": chart_trace["error"],
                    },
                    "failures": failures,
                }
            )
            print(f"{'PASS' if not failures else 'FAIL'} {case.case_id}")

    report = {
        "passed": all(record["passed"] for record in records),
        "passedCases": sum(record["passed"] for record in records),
        "totalCases": len(records),
        "cases": records,
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Chart evaluation: {report['passedCases']}/{report['totalCases']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
