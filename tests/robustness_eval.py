"""Independent robustness and holdout evaluation for the P0 agent."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "robustness_fixtures"
RESULTS = Path(__file__).resolve().parent / "results" / "robustness"
CLI = ROOT / "src" / "cli.js"
ANALYSIS_TOOLS = {"statistics", "group_compare", "top_n", "trend", "anomaly"}


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    description: str
    file_name: str
    question: str
    status: str
    analysis: str | None = None
    args: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    error_code: str | None = None


CASES = [
    Case("BAD-01", "bad", "missing metric field", "metrics.csv", "计算退款金额总和", "error", error_code="missing_field"),
    Case("BAD-02", "bad", "empty file", "empty.csv", "计算金额总和", "error", error_code="empty_file"),
    Case("BAD-03", "bad", "mixed date formats", "mixed_dates.csv", "分析销售额随日期的趋势", "error", "trend", {"dateField": "日期", "metric": "销售额", "operation": "sum"}, error_code="dirty_date_data"),
    Case("BAD-04", "bad", "string in numeric column", "dirty_numeric.csv", "计算销售额平均值", "error", "statistics", {"metric": "销售额", "operation": "average"}, error_code="dirty_numeric_data"),
    Case("BAD-05", "bad", "question asks unavailable information", "metrics.csv", "找出客户满意度最高的客户", "error", error_code="missing_field"),
    Case("BAD-06", "bad", "vague request", "metrics.csv", "分析一下", "needs_input"),
    Case("BAD-07", "bad", "inconsistent CSV width", "malformed.csv", "计算销售额总和", "error", error_code="inconsistent_columns"),
    Case("BAD-08", "bad", "corrupted XLSX", "corrupt.xlsx", "计算销售额平均值", "error", error_code="unreadable_file"),
    Case("BAD-09", "bad", "invalid UTF-8 CSV", "invalid_utf8.csv", "计算金额总和", "error", error_code="encoding_error"),
    Case("BAD-10", "bad", "file exceeds 20MB", "oversized.csv", "计算金额总和", "error", error_code="file_too_large"),
    Case("NEW-01", "holdout", "semicolon-delimited decimal sum", "semicolon.csv", "计算金额总和", "ok", "statistics", {"metric": "金额", "operation": "sum"}, {"value": 6.75}),
    Case("NEW-02", "holdout", "average with a missing numeric cell", "metrics.csv", "计算收入平均值", "ok", "statistics", {"metric": "收入", "operation": "average"}, {"value": 20, "validCount": 3}),
    Case("NEW-03", "holdout", "group average ignores missing metric", "metrics.csv", "按地区分组统计收入平均值", "ok", "group_compare", {"groupBy": "地区", "metric": "收入", "operation": "average"}, {"groups": {"北区": 15, "南区": 30}}),
    Case("NEW-04", "holdout", "negative minimum", "metrics.csv", "计算利润最小值", "ok", "statistics", {"metric": "利润", "operation": "minimum"}, {"value": -5}),
    Case("NEW-05", "holdout", "maximum", "metrics.csv", "计算利润最大值", "ok", "statistics", {"metric": "利润", "operation": "maximum"}, {"value": 40}),
    Case("NEW-06", "holdout", "count nonempty text", "metrics.csv", "统计客户数量", "ok", "statistics", {"metric": "客户", "operation": "count"}, {"value": 3}),
    Case("NEW-07", "holdout", "top 3 with deterministic tie ordering", "ranking.csv", "找出金额 Top 3 客户", "ok", "top_n", {"metric": "金额", "label": "客户", "count": 3}, {"items": [("乙", 500), ("丁", 500), ("丙", 300)]}),
    Case("NEW-08", "holdout", "Chinese date trend", "chinese_dates.csv", "按日期分析访问量趋势", "ok", "trend", {"dateField": "日期", "metric": "访问量", "operation": "sum"}, {"points": [("2026-03-01", 15), ("2026-03-02", 20)]}),
    Case("NEW-09", "holdout", "English-header group sum", "english.csv", "按region分组统计revenue总和", "ok", "group_compare", {"groupBy": "region", "metric": "revenue", "operation": "sum"}, {"groups": {"east": 50, "west": 10}}),
    Case("NEW-10", "holdout", "English trend phrasing", "english.csv", "revenue trend over date", "ok", "trend", {"dateField": "date", "metric": "revenue", "operation": "sum"}, {"points": [("2026-04-01", 40), ("2026-04-02", 20)]}),
    Case("NEW-11", "holdout", "no anomaly", "no_outlier.csv", "识别温度异常值", "ok", "anomaly", {"metric": "温度"}, {"anomalyCount": 0}),
    Case("NEW-12", "holdout", "quoted comma in label", "quoted.csv", "按客户分组统计金额总和", "ok", "group_compare", {"groupBy": "客户", "metric": "金额", "operation": "sum"}, {"groups": {"甲,一部": 100, "乙,二部": 200}}),
    Case("NEW-13", "holdout", "thousands separators", "formatted_numbers.csv", "计算金额总和", "ok", "statistics", {"metric": "金额", "operation": "sum"}, {"value": 3200.5}),
    Case("NEW-14", "holdout", "new XLSX sum", "holdout.xlsx", "计算库存总和", "ok", "statistics", {"metric": "库存", "operation": "sum"}, {"value": 24}),
    Case("NEW-15", "holdout", "tab-delimited CSV average", "tabbed.csv", "计算评分平均值", "ok", "statistics", {"metric": "评分", "operation": "average"}, {"value": 2.5}),
]


def create_xlsx(path: Path) -> None:
    rows = [
        '<row r="1"><c r="A1" t="inlineStr"><is><t>仓库</t></is></c><c r="B1" t="inlineStr"><is><t>库存</t></is></c></row>',
        '<row r="2"><c r="A2" t="inlineStr"><is><t>东</t></is></c><c r="B2"><v>7</v></c></row>',
        '<row r="3"><c r="A3" t="inlineStr"><is><t>西</t></is></c><c r="B3"><v>17</v></c></row>',
    ]
    files = {
        "[Content_Types].xml": "<Types/>",
        "xl/workbook.xml": '<workbook xmlns:r="r"><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<worksheet><sheetData>{"".join(rows)}</sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))


def get_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def validate_expected(case: Case, output: dict[str, Any]) -> list[str]:
    failures = []
    if output.get("status") != case.status:
        failures.append(f"status:{output.get('status')}!=expected:{case.status}")
    if case.error_code and output.get("error", {}).get("code") != case.error_code:
        failures.append(f"error_code:{output.get('error', {}).get('code')}!=expected:{case.error_code}")
    if case.status != "ok":
        if "result" in output or "conclusion" in output:
            failures.append("fabricated_result_or_conclusion")
        return failures
    if output.get("analysis") != case.analysis:
        failures.append(f"wrong_tool:{output.get('analysis')}!=expected:{case.analysis}")
    result = output.get("result", {})
    for key, expected in (case.expected or {}).items():
        if key == "groups":
            actual = {item.get("group"): item.get("value") for item in result.get("groups", [])}
        elif key == "points":
            actual = [(item.get("date"), item.get("value")) for item in result.get("points", [])]
        elif key == "items":
            actual = [(item.get("label"), item.get("value")) for item in result.get("items", [])]
        else:
            actual = result.get(key)
        if actual != expected:
            failures.append(f"wrong_result.{key}:{actual!r}!=expected:{expected!r}")
    return failures


def validate_process(case: Case, output: dict[str, Any]) -> tuple[list[str], dict[str, bool]]:
    failures = []
    audit = output.get("audit", {})
    calls = audit.get("toolCalls", [])
    names = [call.get("tool") for call in calls if isinstance(call, dict)]
    repeated = len(names) != len(set(names))
    rounds_ok = isinstance(audit.get("rounds"), int) and audit["rounds"] <= audit.get("maxRounds", 0) <= 3
    if repeated:
        failures.append("repeated_tool_call")
    if not rounds_ok:
        failures.append("round_limit_violation")
    params_ok = True
    tool_ok = True
    conclusion_ok = True
    if case.status == "ok":
        analysis_calls = [call for call in calls if call.get("tool") in ANALYSIS_TOOLS]
        tool_ok = len(analysis_calls) == 1 and analysis_calls[0].get("tool") == case.analysis
        params_ok = tool_ok and analysis_calls[0].get("args") == case.args
        if not tool_ok:
            failures.append("analysis_tool_trace_mismatch")
        if not params_ok:
            failures.append(f"wrong_parameters:{analysis_calls[0].get('args') if analysis_calls else None!r}")
        conclusion = output.get("conclusion", "")
        result = output.get("result", {})
        metric = result.get("metric", "")
        conclusion_ok = bool(conclusion and metric in conclusion)
        if case.analysis == "statistics":
            conclusion_ok &= str(result.get("value")) in conclusion.replace(",", "")
        elif case.analysis == "group_compare" and result.get("groups"):
            conclusion_ok &= str(result["groups"][0].get("group")) in conclusion
        elif case.analysis == "trend" and result.get("points"):
            conclusion_ok &= result["points"][0].get("date", "") in conclusion and result["points"][-1].get("date", "") in conclusion
        elif case.analysis == "anomaly":
            conclusion_ok &= str(result.get("anomalyCount")) in conclusion
        elif case.analysis == "top_n":
            conclusion_ok &= str(result.get("count")) in conclusion
        if re.search(r"因为|导致|原因是|caused by|because", conclusion, re.I):
            conclusion_ok = False
        if not conclusion_ok:
            failures.append("conclusion_not_strictly_grounded")
    else:
        analysis_calls = [call for call in calls if call.get("tool") in ANALYSIS_TOOLS]
        if case.analysis:
            tool_ok = len(analysis_calls) == 1 and analysis_calls[0].get("tool") == case.analysis and analysis_calls[0].get("status") == "error"
            params_ok = tool_ok and analysis_calls[0].get("args") == case.args
        else:
            tool_ok = not analysis_calls
            params_ok = tool_ok
        conclusion_ok = "result" not in output and "conclusion" not in output
        if not tool_ok:
            failures.append("invalid_input_tool_trace_mismatch")
        if not params_ok:
            failures.append("invalid_input_parameter_mismatch")
    return failures, {"toolSelection": tool_ok, "parameters": params_ok, "rounds": rounds_ok, "noRepeats": not repeated, "conclusion": conclusion_ok}


def prepare(directory: Path) -> None:
    for source in FIXTURES.iterdir():
        if source.is_file():
            shutil.copyfile(source, directory / source.name)
    shutil.copyfile(ROOT / "tests" / "fixtures" / "dirty_numeric.csv", directory / "dirty_numeric.csv")
    (directory / "invalid_utf8.csv").write_bytes(b"amount\n\xff\n")
    with (directory / "oversized.csv").open("wb") as handle:
        handle.write(b"amount\n")
        handle.truncate(20 * 1024 * 1024 + 1)
    create_xlsx(directory / "holdout.xlsx")


def run_case(node: str, case: Case, directory: Path) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        process = subprocess.run([node, str(CLI), "--file", str(directory / case.file_name), "--question", case.question], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        duration = time.perf_counter() - started
        output = json.loads(process.stdout)
        failures = validate_expected(case, output)
        process_failures, checks = validate_process(case, output)
        failures.extend(process_failures)
        expected_exit = 1 if case.status == "error" else 0
        if process.returncode != expected_exit:
            failures.append(f"exit_code:{process.returncode}!=expected:{expected_exit}")
    except Exception as error:
        duration = time.perf_counter() - started
        output, checks, failures = None, {}, [f"harness_or_process_error:{type(error).__name__}:{error}"]
        process = None
    return {"caseId": case.case_id, "category": case.category, "description": case.description, "question": case.question, "passed": not failures, "durationSeconds": round(duration, 6), "failures": failures, "processChecks": checks, "output": output, "stderr": process.stderr if process else ""}


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("Node.js is required", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="p0-robustness-") as temp:
        directory = Path(temp)
        prepare(directory)
        results = [run_case(node, case, directory) for case in CASES]
    bad = [item for item in results if item["category"] == "bad"]
    holdout = [item for item in results if item["category"] == "holdout"]
    all_checks = [value for item in results for value in item["processChecks"].values()]
    calls = [len((item.get("output") or {}).get("audit", {}).get("toolCalls", [])) for item in results]
    costs = [float((item.get("output") or {}).get("audit", {}).get("estimatedCostCny", 0)) for item in results]
    failure_reasons = Counter(reason.split(":", 1)[0] for item in results for reason in item["failures"])
    metrics = {
        "badCaseRecognitionRate": sum(item["passed"] for item in bad) / len(bad),
        "holdoutAccuracy": sum(item["passed"] for item in holdout) / len(holdout),
        "overallAccuracy": sum(item["passed"] for item in results) / len(results),
        "averageResponseSeconds": sum(item["durationSeconds"] for item in results) / len(results),
        "maximumResponseSeconds": max(item["durationSeconds"] for item in results),
        "averageCostCny": sum(costs) / len(costs),
        "maximumCostCny": max(costs),
        "averageToolCalls": sum(calls) / len(calls),
        "processCheckPassRate": sum(all_checks) / len(all_checks),
        "failureReasonDistribution": dict(failure_reasons),
    }
    gates = {
        "badCaseRecognitionRate>=90%": metrics["badCaseRecognitionRate"] >= 0.9,
        "holdoutAccuracy>=85%": metrics["holdoutAccuracy"] >= 0.85,
        "averageResponse<=30s": metrics["averageResponseSeconds"] <= 30,
        "maximumCost<=0.5CNY": metrics["maximumCostCny"] <= 0.5,
        "processChecks=100%": metrics["processCheckPassRate"] == 1,
    }
    report = {"schemaVersion": 1, "scope": {"badCases": len(bad), "holdoutCases": len(holdout), "p1Included": False}, "metrics": metrics, "gates": gates, "passed": all(gates.values()), "cases": results}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "robustness-evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "failures.json").write_text(json.dumps([item for item in results if not item["passed"]], ensure_ascii=False, indent=2), encoding="utf-8")
    with (RESULTS / "traces.jsonl").open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(json.dumps({"caseId": item["caseId"], "audit": (item.get("output") or {}).get("audit", {})}, ensure_ascii=False) + "\n")
    lines = ["# P0 Robustness and Holdout Evaluation", "", f"- Result: {'PASS' if report['passed'] else 'FAIL'}", f"- Bad cases: {sum(i['passed'] for i in bad)}/{len(bad)} ({metrics['badCaseRecognitionRate']:.1%})", f"- New holdout cases: {sum(i['passed'] for i in holdout)}/{len(holdout)} ({metrics['holdoutAccuracy']:.1%})", f"- Overall: {sum(i['passed'] for i in results)}/{len(results)} ({metrics['overallAccuracy']:.1%})", f"- Average response: {metrics['averageResponseSeconds']:.3f}s", f"- Maximum response: {metrics['maximumResponseSeconds']:.3f}s", f"- Average tool calls: {metrics['averageToolCalls']:.2f}", f"- Cost per case: average CNY {metrics['averageCostCny']:.3f}, maximum CNY {metrics['maximumCostCny']:.3f}", f"- Intermediate-process checks: {metrics['processCheckPassRate']:.1%}", f"- Failure reason distribution: {metrics['failureReasonDistribution'] or '{}'}", "", "## Cases", ""]
    lines.extend(f"- {'PASS' if item['passed'] else 'FAIL'} {item['caseId']}: {item['description']} ({item['durationSeconds']:.3f}s){' — ' + '; '.join(item['failures']) if item['failures'] else ''}" for item in results)
    (RESULTS / "robustness-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for item in results:
        print(f"{'PASS' if item['passed'] else 'FAIL'} {item['caseId']} {item['durationSeconds']:.3f}s")
        for failure in item["failures"]:
            print(f"  - {failure}")
    print(f"Bad cases: {sum(i['passed'] for i in bad)}/{len(bad)}; holdout: {sum(i['passed'] for i in holdout)}/{len(holdout)}; overall: {sum(i['passed'] for i in results)}/{len(results)}")
    print(f"Average response: {metrics['averageResponseSeconds']:.3f}s; average tool calls: {metrics['averageToolCalls']:.2f}; process checks: {metrics['processCheckPassRate']:.1%}")
    print(f"Failure reasons: {dict(failure_reasons)}")
    print(f"Report: {RESULTS / 'robustness-summary.md'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
