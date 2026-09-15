"""Deterministic PRD v1.0 P0 evaluation runner.

This file invokes the Node CLI as a black box and checks exact structured output.
It does not execute model-generated code or alter tests/eval_cases.md.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RESULTS = Path(__file__).resolve().parent / "results"
CLI = ROOT / "src" / "cli.js"
TIMEOUT_SECONDS = 30


Check = Callable[[dict[str, Any]], list[str]]


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    description: str
    file_name: str
    question: str
    check: Check


def require(output: dict[str, Any], path: str, expected: Any) -> list[str]:
    actual: Any = output
    for part in path.split("."):
        if not isinstance(actual, dict) or part not in actual:
            return [f"missing {path}; expected {expected!r}"]
        actual = actual[part]
    return [] if actual == expected else [f"{path}: expected {expected!r}, got {actual!r}"]


def require_no_result(output: dict[str, Any]) -> list[str]:
    failures = []
    if "result" in output:
        failures.append("unsafe fabricated result was returned")
    if output.get("status") == "ok":
        failures.append("status must not be ok")
    return failures


def check_sum(output: dict[str, Any]) -> list[str]:
    return require(output, "status", "ok") + require(output, "analysis", "statistics") + require(output, "result.operation", "sum") + require(output, "result.value", 1580)


def check_average(output: dict[str, Any]) -> list[str]:
    return require(output, "status", "ok") + require(output, "analysis", "statistics") + require(output, "result.operation", "average") + require(output, "result.value", 20)


def check_group(output: dict[str, Any]) -> list[str]:
    failures = require(output, "status", "ok") + require(output, "analysis", "group_compare")
    groups = output.get("result", {}).get("groups", [])
    actual = {item.get("group"): item.get("value") for item in groups}
    expected = {"华南": 1200, "华东": 380}
    if actual != expected:
        failures.append(f"group totals: expected {expected!r}, got {actual!r}")
    return failures


def check_top5(output: dict[str, Any]) -> list[str]:
    failures = require(output, "status", "ok") + require(output, "analysis", "top_n") + require(output, "result.count", 5)
    items = output.get("result", {}).get("items", [])
    actual = [(item.get("label"), item.get("value")) for item in items]
    expected = [("B", 700), ("F", 600), ("D", 500), ("G", 400), ("C", 300)]
    if actual != expected:
        failures.append(f"top 5: expected {expected!r}, got {actual!r}")
    return failures


def check_trend(output: dict[str, Any]) -> list[str]:
    failures = require(output, "status", "ok") + require(output, "analysis", "trend")
    points = output.get("result", {}).get("points", [])
    actual = [(point.get("date"), point.get("value")) for point in points]
    expected = [("2026-01-01", 300), ("2026-01-02", 1150), ("2026-01-03", 130)]
    if actual != expected:
        failures.append(f"trend points: expected {expected!r}, got {actual!r}")
    return failures


def check_anomaly(output: dict[str, Any]) -> list[str]:
    failures = require(output, "status", "ok") + require(output, "analysis", "anomaly") + require(output, "result.method", "iqr_1.5") + require(output, "result.anomalyCount", 1)
    anomalies = output.get("result", {}).get("anomalies", [])
    actual = [(item.get("rowNumber"), item.get("value")) for item in anomalies]
    if actual != [(7, 100)]:
        failures.append(f"anomalies: expected [(7, 100)], got {actual!r}")
    return failures


def check_error(code: str) -> Check:
    def checker(output: dict[str, Any]) -> list[str]:
        return require(output, "status", "error") + require(output, "error.code", code) + require_no_result(output)
    return checker


def check_needs_input(output: dict[str, Any]) -> list[str]:
    failures = require(output, "status", "needs_input") + require_no_result(output)
    if not output.get("message"):
        failures.append("clarification message is empty")
    return failures


def check_empty_stops(output: dict[str, Any]) -> list[str]:
    failures = check_error("empty_file")(output)
    analysis_tools = {"statistics", "group_compare", "top_n", "trend", "anomaly"}
    calls = output.get("audit", {}).get("toolCalls", [])
    if any(call.get("tool") in analysis_tools for call in calls if isinstance(call, dict)):
        failures.append("analysis tool was called after empty-file validation failed")
    return failures


def cases() -> list[Case]:
    return [
        Case("P0-01", "p0", "CSV column sum", "sales.csv", "计算销售额总和", check_sum),
        Case("P0-02", "p0", "XLSX column average", "average.xlsx", "计算销售额平均值", check_average),
        Case("P0-03", "p0", "group sales by region", "sales.csv", "按地区分组统计销售额总和", check_group),
        Case("P0-04", "p0", "top 5 products", "top_products.csv", "找出销售额 Top 5 产品", check_top5),
        Case("P0-05", "p0", "daily sales trend", "sales.csv", "按日期分析销售额趋势", check_trend),
        Case("P0-06", "p0", "obvious anomaly", "anomaly.csv", "识别销售额异常值", check_anomaly),
        Case("P0-07", "p0", "missing field", "sales.csv", "计算利润总和", check_error("missing_field")),
        Case("P0-08", "p0", "empty input", "empty.csv", "计算销售额总和", check_empty_stops),
        Case("P0-09", "p0", "dirty numeric input", "dirty_numeric.csv", "计算销售额总和", check_error("dirty_numeric_data")),
        Case("P0-10", "p0", "insufficient question", "sales.csv", "帮我看看这个数据", check_needs_input),
        Case("BC-01", "bad", "missing profit margin", "sales.csv", "按利润率排序", check_error("missing_field")),
        Case("BC-02", "bad", "empty CSV stops analysis", "empty.csv", "计算销售额总和", check_empty_stops),
        Case("BC-03", "bad", "text in numeric field", "dirty_numeric.csv", "计算销售额总和", check_error("dirty_numeric_data")),
        Case("BC-04", "bad", "vague question", "sales.csv", "帮我看看这个数据有什么问题", check_needs_input),
        Case("BC-05", "bad", "trend tool selection", "sales.csv", "销售额趋势如何", lambda output: require(output, "status", "ok") + require(output, "analysis", "trend")),
    ]


def create_average_xlsx(destination: Path) -> None:
    rows = "".join([
        '<row r="1"><c r="A1" t="inlineStr"><is><t>产品</t></is></c><c r="B1" t="inlineStr"><is><t>销售额</t></is></c></row>',
        '<row r="2"><c r="A2" t="inlineStr"><is><t>A</t></is></c><c r="B2"><v>10</v></c></row>',
        '<row r="3"><c r="A3" t="inlineStr"><is><t>B</t></is></c><c r="B3"><v>20</v></c></row>',
        '<row r="4"><c r="A4" t="inlineStr"><is><t>C</t></is></c><c r="B4"><v>30</v></c></row>',
    ])
    files = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": '<?xml version="1.0"?><workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0"?><Relationships><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0"?><worksheet><sheetData>{rows}</sheetData></worksheet>',
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))


def invoke(node: str, case: Case, fixture_directory: Path) -> dict[str, Any]:
    file_path = fixture_directory / case.file_name
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [node, str(CLI), "--file", str(file_path), "--question", case.question],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        elapsed = time.perf_counter() - started
    except subprocess.TimeoutExpired:
        return {"caseId": case.case_id, "passed": False, "durationSeconds": TIMEOUT_SECONDS, "failures": ["process timed out"], "output": None}
    try:
        output = json.loads(completed.stdout)
        failures = case.check(output)
    except json.JSONDecodeError as error:
        output = None
        failures = [f"stdout is not valid JSON: {error}"]
    expected_exit = 0 if output and output.get("status") in {"ok", "needs_input"} else 1
    if completed.returncode != expected_exit:
        failures.append(f"exit code: expected {expected_exit}, got {completed.returncode}")
    return {
        "caseId": case.case_id,
        "category": case.category,
        "description": case.description,
        "passed": not failures,
        "durationSeconds": round(elapsed, 6),
        "exitCode": completed.returncode,
        "failures": failures,
        "stderr": completed.stderr,
        "output": output,
    }


def write_reports(results: list[dict[str, Any]], environment: dict[str, Any]) -> dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p0 = [result for result in results if result["category"] == "p0"]
    bad = [result for result in results if result["category"] == "bad"]
    passed = sum(result["passed"] for result in results)
    p0_passed = sum(result["passed"] for result in p0)
    bad_passed = sum(result["passed"] for result in bad)
    durations = [result["durationSeconds"] for result in results]
    costs = [float((result.get("output") or {}).get("audit", {}).get("estimatedCostCny", 0)) for result in results]
    metrics = {
        "p0Passed": p0_passed,
        "p0Total": len(p0),
        "p0PassRate": p0_passed / len(p0),
        "overallPassed": passed,
        "overallTotal": len(results),
        "overallAccuracy": passed / len(results),
        "badCasePassed": bad_passed,
        "badCaseTotal": len(bad),
        "badCaseRecognitionRate": bad_passed / len(bad),
        "averageResponseSeconds": sum(durations) / len(durations),
        "maximumResponseSeconds": max(durations),
        "maximumCostCny": max(costs),
    }
    thresholds = {
        "p0PassRate": {"required": 1.0, "passed": metrics["p0PassRate"] >= 1.0},
        "overallAccuracy": {"required": 0.85, "passed": metrics["overallAccuracy"] >= 0.85},
        "badCaseRecognitionRate": {"required": 0.90, "passed": metrics["badCaseRecognitionRate"] >= 0.90},
        "averageResponseSeconds": {"requiredMaximum": 30, "passed": metrics["averageResponseSeconds"] <= 30},
        "maximumCostCny": {"requiredMaximum": 0.5, "passed": metrics["maximumCostCny"] <= 0.5},
    }
    report = {"schemaVersion": 1, "environment": environment, "metrics": metrics, "thresholds": thresholds, "passed": all(item["passed"] for item in thresholds.values()), "cases": results}
    (RESULTS / "evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [{"caseId": result["caseId"], "failures": result["failures"], "output": result["output"]} for result in results if not result["passed"]]
    (RESULTS / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    with (RESULTS / "tool-calls.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps({"caseId": result["caseId"], "toolCalls": (result.get("output") or {}).get("audit", {}).get("toolCalls", [])}, ensure_ascii=False) + "\n")
    lines = [
        "# PRD v1.0 P0 Evaluation Summary", "",
        f"- Result: {'PASS' if report['passed'] else 'FAIL'}",
        f"- P0 pass rate: {metrics['p0Passed']}/{metrics['p0Total']} ({metrics['p0PassRate']:.1%})",
        f"- Overall accuracy: {metrics['overallPassed']}/{metrics['overallTotal']} ({metrics['overallAccuracy']:.1%})",
        f"- Bad-case recognition: {metrics['badCasePassed']}/{metrics['badCaseTotal']} ({metrics['badCaseRecognitionRate']:.1%})",
        f"- Average response: {metrics['averageResponseSeconds']:.3f}s",
        f"- Maximum response: {metrics['maximumResponseSeconds']:.3f}s",
        f"- Maximum reported cost: CNY {metrics['maximumCostCny']:.3f}", "", "## Cases", "",
    ]
    lines.extend(f"- {'PASS' if result['passed'] else 'FAIL'} {result['caseId']}: {result['description']} ({result['durationSeconds']:.3f}s)" for result in results)
    (RESULTS / "evaluation-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("ERROR: node executable was not found", file=sys.stderr)
        return 2
    if not CLI.is_file():
        print(f"ERROR: CLI was not found: {CLI}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="data-agent-eval-") as temp:
        fixture_directory = Path(temp)
        for source in FIXTURES.glob("*.csv"):
            shutil.copyfile(source, fixture_directory / source.name)
        create_average_xlsx(fixture_directory / "average.xlsx")
        results = [invoke(node, case, fixture_directory) for case in cases()]
    node_version = subprocess.run([node, "--version"], capture_output=True, text=True, encoding="utf-8", check=False).stdout.strip()
    environment = {"node": node_version, "python": sys.version.split()[0], "platform": sys.platform, "timeoutSeconds": TIMEOUT_SECONDS, "caseSource": "tests/eval_cases.md"}
    report = write_reports(results, environment)
    for result in results:
        print(f"{'PASS' if result['passed'] else 'FAIL'} {result['caseId']} {result['durationSeconds']:.3f}s")
        for failure in result["failures"]:
            print(f"  - {failure}")
    metrics = report["metrics"]
    print(f"P0: {metrics['p0Passed']}/{metrics['p0Total']} ({metrics['p0PassRate']:.1%})")
    print(f"Overall: {metrics['overallPassed']}/{metrics['overallTotal']} ({metrics['overallAccuracy']:.1%})")
    print(f"Bad cases: {metrics['badCasePassed']}/{metrics['badCaseTotal']} ({metrics['badCaseRecognitionRate']:.1%})")
    print(f"Average response: {metrics['averageResponseSeconds']:.3f}s; maximum cost: CNY {metrics['maximumCostCny']:.3f}")
    print(f"Report: {RESULTS / 'evaluation-summary.md'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
