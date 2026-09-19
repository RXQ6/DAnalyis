"""Formal executable mapping for the 20 P1 cases in tests/eval_cases.md."""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import AgentLoop, ConversationRunner
from datasets import DatasetRegistry, DatasetRegistryError
from eval_agent import create_average_xlsx
from tools.handlers import build_default_registry


RESULT = ROOT / "tests" / "results" / "p1-evaluation.json"
SUMMARY = ROOT / "tests" / "results" / "p1-evaluation-summary.md"


class ScriptedModel:
    def __init__(self, decisions: list[Any]) -> None:
        self.decisions = decisions
        self.calls = 0

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del tools
        decision = self.decisions[self.calls]
        self.calls += 1
        return decision(messages) if callable(decision) else decision


@dataclass(frozen=True)
class FormalCase:
    case_id: str
    category: str
    description: str
    input_fixture: str
    capability: str
    mapped_test: str
    expected: str
    execute: Callable[[Path], tuple[dict[str, Any], list[str]]]


def conversation_context(messages: list[dict[str, Any]]) -> dict[str, Any]:
    item = next(message for message in messages if message.get("name") == "conversation_context")
    return json.loads(item["content"].split("：", 1)[1])


def make_runner(root: Path, model: ScriptedModel, name: str) -> ConversationRunner:
    return ConversationRunner(
        AgentLoop(model, build_default_registry()),
        dataset_registry=DatasetRegistry(root / f"derived-{name}"),
        conversation_id=f"p1-{name}",
    )


def tool_context(
    registry: DatasetRegistry, previous: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "dataset_registry": registry,
        "active_dataset_ids": [item["datasetId"] for item in registry.list_summaries()],
        "previous_tool_results": previous or [],
        "call_id": "p1-eval",
    }


def prior(
    call_id: str, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    return {
        "callId": call_id,
        "toolName": tool_name,
        "arguments": arguments,
        "toolResult": result,
    }


def chart_run(
    root: Path,
    *,
    analysis: dict[str, Any],
    chart: dict[str, Any],
    dataset: Path,
) -> Any:
    model = ScriptedModel(
        [analysis, chart, {"type": "final_answer", "content": "图表处理完成。"}]
    )
    return AgentLoop(model, build_default_registry()).run(
        "P1 图表评测",
        dataset=str(dataset),
        artifact_dir=str(root / "charts"),
    )


def chart_actions(root: Path, *, actions: list[dict[str, Any]], dataset: Path) -> Any:
    model = ScriptedModel([*actions, {"type": "final_answer", "content": "图表处理完成。"}])
    return AgentLoop(model, build_default_registry()).run(
        "P1 图表评测", dataset=str(dataset), artifact_dir=str(root / "charts")
    )


def chart_line(root: Path) -> tuple[dict[str, Any], list[str]]:
    state = chart_run(
        root,
        dataset=ROOT / "tests" / "fixtures" / "sales.csv",
        analysis={
            "type": "tool_call",
            "id": "trend",
            "name": "trend_analysis",
            "arguments": {"dateField": "日期", "metric": "销售额", "operation": "sum"},
        },
        chart={
            "type": "tool_call",
            "id": "line-chart",
            "name": "generate_chart",
            "arguments": {"sourceCallId": "trend", "chartType": "line"},
        },
    )
    trace = state.execution_trace[1]
    actual = {"success": trace["success"], "chartType": (trace["data"] or {}).get("spec", {}).get("chartType")}
    failures = [] if actual == {"success": True, "chartType": "line"} else ["line chart was not generated"]
    return actual, failures


def chart_share(root: Path) -> tuple[dict[str, Any], list[str]]:
    state = chart_actions(
        root,
        dataset=ROOT / "tests" / "fixtures" / "sales.csv",
        actions=[{
            "type": "tool_call",
            "id": "groups",
            "name": "group_compare",
            "arguments": {"groupBy": "地区", "metric": "销售额", "operation": "sum"},
        }, {
            "type": "tool_call",
            "id": "shares",
            "name": "normalize_share",
            "arguments": {"sourceCallId": "groups"},
        }, {
            "type": "tool_call",
            "id": "share-chart",
            "name": "generate_chart",
            "arguments": {"sourceCallId": "shares", "chartType": "bar"},
        }],
    )
    trace = state.execution_trace[2]
    values = (trace["data"] or {}).get("spec", {}).get("data", {}).get("values", [])
    total = sum(item.get("y", 0) for item in values)
    actual = {"success": trace["success"], "values": values, "valueTotal": total}
    failures = []
    if not trace["success"]:
        failures.append("bar chart was not generated")
    if round(total, 6) not in (1.0, 100.0):
        failures.append("capability_conflict: chart contains raw totals, not category shares")
    return actual, failures


def chart_scatter(root: Path) -> tuple[dict[str, Any], list[str]]:
    dataset = root / "scatter.csv"
    dataset.write_text("销量,利润\n10,2\n20,5\n30,9\n", encoding="utf-8")
    state = chart_run(
        root,
        dataset=dataset,
        analysis={
            "type": "tool_call",
            "id": "points",
            "name": "scatter_data",
            "arguments": {"xField": "销量", "yField": "利润"},
        },
        chart={
            "type": "tool_call",
            "id": "scatter-chart",
            "name": "generate_chart",
            "arguments": {"sourceCallId": "points", "chartType": "scatter"},
        },
    )
    trace = state.execution_trace[1]
    chart_type = (trace.get("data") or {}).get("spec", {}).get("chartType")
    actual = {"success": trace["success"], "chartType": chart_type}
    return actual, [] if actual == {"success": True, "chartType": "scatter"} else ["scatter chart was not generated"]


def chart_explicit(root: Path) -> tuple[dict[str, Any], list[str]]:
    return chart_line(root)


def chart_unsuitable(root: Path) -> tuple[dict[str, Any], list[str]]:
    state = chart_run(
        root,
        dataset=ROOT / "tests" / "fixtures" / "sales.csv",
        analysis={
            "type": "tool_call",
            "id": "one-value",
            "name": "basic_stats",
            "arguments": {"metric": "销售额", "operation": "sum"},
        },
        chart={
            "type": "tool_call",
            "id": "bad-chart",
            "name": "generate_chart",
            "arguments": {"sourceCallId": "one-value", "chartType": "bar"},
        },
    )
    trace = state.execution_trace[1]
    error_code = (trace["error"] or {}).get("code")
    actual = {"success": trace["success"], "errorCode": error_code}
    failures = [] if not trace["success"] and error_code == "unsupported_chart_source" else ["unsuitable data was not rejected clearly"]
    return actual, failures


def execute_merge(
    root: Path, left: Path, right: Path, left_key: str, right_key: str, name: str
) -> tuple[dict[str, Any], list[str]]:
    registry = DatasetRegistry(root / f"merge-{name}")
    tools = build_default_registry()
    first = registry.register(left)
    second = registry.register(right)
    args = {
        "leftDatasetId": first["datasetId"],
        "rightDatasetId": second["datasetId"],
        "leftKey": left_key,
        "rightKey": right_key,
        "joinType": "inner",
    }
    inspected = tools.execute("inspect_merge", args, context=tool_context(registry))
    merged = tools.execute(
        "merge_datasets",
        {"preflightCallId": "preflight"},
        context=tool_context(registry, [prior("preflight", "inspect_merge", args, inspected)]),
    )
    actual = {
        "preflightOk": inspected["ok"],
        "safeToExecute": (inspected.get("data") or {}).get("safeToExecute"),
        "mergeOk": merged["ok"],
        "rowCount": (merged.get("data") or {}).get("rowCount"),
    }
    failures = [] if actual["preflightOk"] and actual["safeToExecute"] and actual["mergeOk"] else ["safe one-to-one merge did not complete"]
    return actual, failures


def merge_csv(root: Path) -> tuple[dict[str, Any], list[str]]:
    left = root / "same-left.csv"
    right = root / "same-right.csv"
    left.write_text("ID,销售额\nA,10\nB,20\n", encoding="utf-8")
    right.write_text("ID,销售额\nA,40\nB,60\n", encoding="utf-8")
    return execute_merge(root, left, right, "ID", "ID", "csv")


def merge_xlsx(root: Path) -> tuple[dict[str, Any], list[str]]:
    left = root / "left.xlsx"
    right = root / "right.xlsx"
    create_average_xlsx(left)
    create_average_xlsx(right)
    return execute_merge(root, left, right, "产品", "产品", "xlsx")


def mapping_issue(root: Path) -> tuple[dict[str, Any], list[str]]:
    left = root / "mapping-left.csv"
    right = root / "mapping-right.csv"
    left.write_text("客户,销售额\nC1,10\n", encoding="utf-8")
    right.write_text("客户ID,利润\nC1,2\n", encoding="utf-8")
    registry = DatasetRegistry(root / "mapping")
    tools = build_default_registry()
    first = registry.register(left)
    second = registry.register(right)
    result = tools.execute(
        "inspect_merge",
        {
            "leftDatasetId": first["datasetId"],
            "rightDatasetId": second["datasetId"],
            "leftKey": "客户",
            "rightKey": "客户",
            "joinType": "inner",
        },
        context=tool_context(registry),
    )
    code = (result.get("error") or {}).get("code")
    actual = {"ok": result["ok"], "errorCode": code}
    return actual, [] if not result["ok"] and code == "missing_join_field" else ["field mapping mismatch was not reported"]


def compare_files(root: Path, *, categorized: bool) -> tuple[dict[str, Any], list[str]]:
    first_file = root / ("category-a.csv" if categorized else "sales-2025.csv")
    second_file = root / ("category-b.csv" if categorized else "sales-2026.csv")
    first_file.write_text("类别,销售额\nA,10\nB,40\n", encoding="utf-8")
    second_file.write_text("类别,销售额\nA,30\nB,70\n", encoding="utf-8")
    registry = DatasetRegistry(root / ("category-compare" if categorized else "yoy"))
    tools = build_default_registry()
    first = registry.register(first_file)
    second = registry.register(second_file)
    if categorized:
        args1 = {"datasetId": first["datasetId"], "groupBy": "类别", "metric": "销售额", "operation": "sum"}
        args2 = {"datasetId": second["datasetId"], "groupBy": "类别", "metric": "销售额", "operation": "sum"}
        one = tools.execute("group_compare", args1, context=tool_context(registry))
        two = tools.execute("group_compare", args2, context=tool_context(registry))
        compared = tools.execute(
            "compare_datasets",
            {"sourceCallIds": ["one", "two"]},
            context=tool_context(registry, [prior("one", "group_compare", args1, one), prior("two", "group_compare", args2, two)]),
        )
        data = compared.get("data") or {}
        actual = {"ok": compared["ok"], "categories": data.get("categories")}
        return actual, [] if compared["ok"] and len(data.get("categories") or []) == 2 else ["grouped datasets were not compared"]
    args1 = {"datasetId": first["datasetId"], "metric": "销售额", "operation": "sum"}
    args2 = {"datasetId": second["datasetId"], "metric": "销售额", "operation": "sum"}
    one = tools.execute("basic_stats", args1, context=tool_context(registry))
    two = tools.execute("basic_stats", args2, context=tool_context(registry))
    compared = tools.execute(
        "compare_datasets",
        {"sourceCallIds": ["one", "two"], "comparisonMode": "year_over_year"},
        context=tool_context(registry, [prior("one", "basic_stats", args1, one), prior("two", "basic_stats", args2, two)]),
    )
    data = compared.get("data") or {}
    actual = {"ok": compared["ok"], "groups": data.get("groups"), "yearOverYearRate": data.get("yearOverYearRate")}
    return actual, [] if actual["yearOverYearRate"] == 1 else ["deterministic year-over-year rate is incorrect"]


def empty_file(root: Path) -> tuple[dict[str, Any], list[str]]:
    empty = root / "empty-p1.csv"
    empty.write_text("", encoding="utf-8")
    registry = DatasetRegistry(root / "empty-registry")
    try:
        registry.register(empty)
    except DatasetRegistryError as error:
        actual = {"accepted": False, "errorCode": error.code}
        return actual, [] if error.code == "empty_file" else [f"unexpected error: {error.code}"]
    return {"accepted": True}, ["empty file was accepted"]


def structure_mismatch(root: Path) -> tuple[dict[str, Any], list[str]]:
    left = root / "structure-left.csv"
    right = root / "structure-right.csv"
    left.write_text("ID,销售额\nA,10\n", encoding="utf-8")
    right.write_text("编号,说明\n1,x\n", encoding="utf-8")
    registry = DatasetRegistry(root / "structure")
    tools = build_default_registry()
    first = registry.register(left)
    second = registry.register(right)
    result = tools.execute(
        "inspect_merge",
        {"leftDatasetId": first["datasetId"], "rightDatasetId": second["datasetId"], "leftKey": "ID", "rightKey": "ID", "joinType": "inner"},
        context=tool_context(registry),
    )
    code = (result.get("error") or {}).get("code")
    return {"ok": result["ok"], "errorCode": code}, [] if not result["ok"] else ["incompatible structures produced a result"]


def history_fixture(root: Path) -> Path:
    path = root / "history.csv"
    if not path.exists():
        path.write_text("日期,地区,销售额,利润\n2026-01-01,华东,10,2\n2026-01-02,华东,20,3\n2026-01-01,华南,40,4\n", encoding="utf-8")
    return path


def group_call(messages: list[dict[str, Any]], call_id: str, metric: str = "销售额") -> dict[str, Any]:
    return {
        "type": "tool_call",
        "id": call_id,
        "name": "group_compare",
        "arguments": {"datasetId": conversation_context(messages)["currentDatasetId"], "groupBy": "地区", "metric": metric, "operation": "sum"},
    }


def prior_groups(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = conversation_context(messages)["priorToolResults"]
    return next(result["toolResult"]["data"]["groups"] for result in reversed(results) if result["toolName"] == "group_compare")


def history_extreme(root: Path, *, highest: bool) -> tuple[dict[str, Any], list[str]]:
    expected = "华南" if highest else "华东"
    model = ScriptedModel(
        [
            lambda messages: group_call(messages, "groups"),
            {"type": "final_answer", "content": "地区比较完成。"},
            lambda messages: {
                "type": "final_answer",
                "content": (max if highest else min)(prior_groups(messages), key=lambda item: item["value"])["group"],
            },
        ]
    )
    session = make_runner(root, model, f"extreme-{highest}")
    session.run("哪个地区销售额最高", dataset_paths=[history_fixture(root)])
    state = session.run("刚才哪个地区最高" if highest else "那最低的呢")
    actual = {"answer": state.final_answer}
    return actual, [] if state.final_answer == expected else [f"expected {expected}, got {state.final_answer}"]


def history_filter(root: Path) -> tuple[dict[str, Any], list[str]]:
    def trend(messages: list[dict[str, Any]], call_id: str, region: str) -> dict[str, Any]:
        return {"type": "tool_call", "id": call_id, "name": "trend_analysis", "arguments": {"datasetId": conversation_context(messages)["currentDatasetId"], "dateField": "日期", "metric": "销售额", "operation": "sum", "filters": {"地区": region}}}
    model = ScriptedModel([lambda messages: trend(messages, "east", "华东"), {"type": "final_answer", "content": "华东完成"}, lambda messages: trend(messages, "south", "华南"), {"type": "final_answer", "content": "华南完成"}])
    session = make_runner(root, model, "filter")
    session.run("看华东销售趋势", dataset_paths=[history_fixture(root)])
    state = session.run("改看华南")
    filters = state.execution_trace[0]["arguments"].get("filters")
    return {"filters": filters}, [] if filters == {"地区": "华南"} else ["new filter was not applied"]


def history_metric(root: Path) -> tuple[dict[str, Any], list[str]]:
    model = ScriptedModel([lambda messages: group_call(messages, "sales"), {"type": "final_answer", "content": "销售额完成"}, lambda messages: group_call(messages, "profit", "利润"), {"type": "final_answer", "content": "利润完成"}])
    session = make_runner(root, model, "metric")
    session.run("按地区看销售额", dataset_paths=[history_fixture(root)])
    state = session.run("改看利润")
    metric = state.execution_trace[0]["arguments"].get("metric")
    return {"metric": metric}, [] if metric == "利润" else ["new metric did not override old metric"]


def history_new_file(root: Path) -> tuple[dict[str, Any], list[str]]:
    old = root / "old-history.csv"
    new = root / "new-history.csv"
    old.write_text("销售额\n10\n20\n", encoding="utf-8")
    new.write_text("销售额\n100\n", encoding="utf-8")
    def stats(messages: list[dict[str, Any]], call_id: str) -> dict[str, Any]:
        return {"type": "tool_call", "id": call_id, "name": "basic_stats", "arguments": {"datasetId": conversation_context(messages)["currentDatasetId"], "metric": "销售额", "operation": "sum"}}
    model = ScriptedModel([lambda messages: stats(messages, "old"), {"type": "final_answer", "content": "30"}, lambda messages: stats(messages, "new"), {"type": "final_answer", "content": "100"}])
    session = make_runner(root, model, "new-file")
    session.run("计算旧文件", dataset_paths=[old])
    old_id = session.state.current_dataset_id
    state = session.run("改用新文件", dataset_paths=[new])
    actual = {"value": state.execution_trace[0]["data"]["value"], "oldDatasetId": old_id, "currentDatasetId": session.state.current_dataset_id}
    return actual, [] if actual["value"] == 100 and actual["oldDatasetId"] != actual["currentDatasetId"] else ["old and new datasets were mixed"]


def history_long(root: Path) -> tuple[dict[str, Any], list[str]]:
    decisions: list[Any] = [lambda messages: group_call(messages, "long-groups"), {"type": "final_answer", "content": "完成"}]
    decisions.extend({"type": "final_answer", "content": f"中间回答 {index}"} for index in range(13))
    decisions.append(lambda messages: {"type": "final_answer", "content": max(prior_groups(messages), key=lambda item: item["value"])["group"]})
    session = make_runner(root, ScriptedModel(decisions), "long")
    session.run("哪个地区最高", dataset_paths=[history_fixture(root)])
    for index in range(13):
        session.run(f"中间问题 {index}")
    state = session.run("最早分析哪个地区最高")
    return {"answer": state.final_answer, "turns": session.state.turn_count}, [] if state.final_answer == "华南" else ["long conversation lost the analysis result"]


def history_conflict(root: Path) -> tuple[dict[str, Any], list[str]]:
    model = ScriptedModel([lambda messages: group_call(messages, "sales-conflict"), {"type": "final_answer", "content": "销售额完成"}, lambda messages: group_call(messages, "profit-conflict", "利润"), {"type": "final_answer", "content": "已识别冲突并改看利润"}])
    session = make_runner(root, model, "conflict")
    session.run("只看销售额", dataset_paths=[history_fixture(root)])
    state = session.run("不要销售额，改看利润")
    metric = state.execution_trace[0]["arguments"].get("metric")
    return {"metric": metric, "answer": state.final_answer}, [] if metric == "利润" and "利润" in (state.final_answer or "") else ["conflicting instruction was not resolved in favor of the current question"]


def history_insufficient(root: Path) -> tuple[dict[str, Any], list[str]]:
    session = make_runner(root, ScriptedModel([{"type": "needs_user_input", "content": "请重新提供文件和分析目标。"}]), "insufficient")
    state = session.run("那最低的呢")
    actual = {"stopReason": state.stop_reason, "answer": state.final_answer}
    return actual, [] if state.stop_reason == "needs_user_input" else ["missing history did not request more information"]


def cases() -> list[FormalCase]:
    return [
        FormalCase("P1-01", "chart", "根据时间序列生成折线图", "tests/fixtures/sales.csv", "趋势 ToolResult → line chart", "tests/eval_chart.py CHART-01", "生成 line SVG，来源为 trend_analysis", chart_line),
        FormalCase("P1-02", "chart", "根据类别占比生成柱状图", "tests/fixtures/sales.csv", "类别占比 → bar chart", "tests/test_chart_tool.py + tests/eval_p1.py", "柱高表示占比，总计为 1 或 100", chart_share),
        FormalCase("P1-03", "chart", "根据两个数值字段生成散点图", "generated scatter.csv", "scatter chart", "tests/test_chart_tool.py + tests/eval_p1.py", "成功生成 scatter chart", chart_scatter),
        FormalCase("P1-04", "chart", "用户指定图表类型时正确生成", "tests/fixtures/sales.csv", "显式 line chart", "tests/eval_chart.py CHART-01/04", "按用户指定生成 line chart", chart_explicit),
        FormalCase("P1-05", "chart", "数据不适合画图时给出提示", "tests/fixtures/sales.csv", "不支持的单值图表来源", "tests/eval_chart.py CHART-05", "拒绝生成并返回 unsupported_chart_source", chart_unsuitable),
        FormalCase("P1-06", "multifile", "合并两个字段一致的 CSV", "generated same-left.csv + same-right.csv", "CSV 一对一安全合并", "tests/test_multifile_tools.py + tests/eval_p1.py", "preflight 安全且生成派生数据集", merge_csv),
        FormalCase("P1-07", "multifile", "合并两个 Excel 文件", "generated left.xlsx + right.xlsx", "XLSX 一对一安全合并", "tests/eval_p1.py", "preflight 安全且生成派生数据集", merge_xlsx),
        FormalCase("P1-08", "multifile", "字段名称略有差异时提示映射问题", "generated 客户/客户ID CSV", "join 字段映射校验", "tests/eval_p1.py", "明确返回 missing_join_field，不执行合并", mapping_issue),
        FormalCase("P1-09", "multifile", "对两个文件做同比分析", "generated sales-2025.csv + sales-2026.csv", "跨文件同比计算", "tests/test_multifile_tools.py + tests/eval_p1.py", "确定性返回同比变化率", lambda root: compare_files(root, categorized=False)),
        FormalCase("P1-10", "multifile", "对两个文件做分类对比", "generated category-a.csv + category-b.csv", "跨文件分组对比", "tests/test_multifile_tools.py + tests/eval_p1.py", "按类别比较两个文件的分组结果", lambda root: compare_files(root, categorized=True)),
        FormalCase("P1-11", "multifile", "文件之一为空时正确处理", "generated empty-p1.csv", "空文件注册校验", "tests/test_dataset_registry.py + tests/eval_p1.py", "拒绝空文件且不继续分析", empty_file),
        FormalCase("P1-12", "multifile", "文件结构不一致时不给出错误结论", "generated structure-left/right.csv", "结构/关联字段校验", "tests/test_multifile_tools.py + tests/eval_p1.py", "拒绝不兼容合并，不产生结论", structure_mismatch),
        FormalCase("P1-13", "conversation", "追问刚才哪个地区最高", "generated history.csv + 2 turns", "历史 ToolResult recall", "tests/test_conversation.py + tests/eval_p1.py", "回答华南", lambda root: history_extreme(root, highest=True)),
        FormalCase("P1-14", "conversation", "追问那最低的呢", "generated history.csv + 2 turns", "历史对象与结果 recall", "tests/eval_p1.py", "回答华东", lambda root: history_extreme(root, highest=False)),
        FormalCase("P1-15", "conversation", "修改筛选条件后重新分析", "generated history.csv + 2 turns", "filter 覆盖", "tests/eval_conversation.py CONV-01 + tests/eval_p1.py", "第二轮使用华南筛选", history_filter),
        FormalCase("P1-16", "conversation", "更换指标后继续分析", "generated history.csv + 2 turns", "metric 覆盖", "tests/eval_conversation.py CONV-04 + tests/eval_p1.py", "第二轮改用利润", history_metric),
        FormalCase("P1-17", "conversation", "上传新文件后不混用旧数据", "generated old/new-history.csv", "活动数据集隔离", "tests/test_conversation.py + tests/eval_p1.py", "只使用新文件并得到 100", history_new_file),
        FormalCase("P1-18", "conversation", "长对话后仍引用正确分析结果", "generated history.csv + 15 turns", "长历史 ToolResult recall", "tests/test_conversation.py + tests/eval_p1.py", "仍回答华南", history_long),
        FormalCase("P1-19", "conversation", "前后问题冲突时能识别", "generated history.csv + 2 turns", "当前问题覆盖旧 metric", "tests/eval_conversation.py CONV-04 + tests/eval_p1.py", "按当前请求改用利润", history_conflict),
        FormalCase("P1-20", "conversation", "历史上下文不足时要求重新提供信息", "no dataset/history", "needs_user_input", "tests/eval_conversation.py CONV-08 + tests/eval_p1.py", "stop_reason=needs_user_input", history_insufficient),
    ]


def main() -> int:
    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="p1-formal-eval-") as directory:
        root = Path(directory)
        for case in cases():
            started = time.perf_counter()
            try:
                actual, failures = case.execute(root)
            except Exception as error:
                actual = {"exceptionType": type(error).__name__, "message": str(error)}
                failures = [f"evaluation exception: {type(error).__name__}: {error}"]
            duration = time.perf_counter() - started
            record = {
                "caseId": case.case_id,
                "category": case.category,
                "description": case.description,
                "inputFixture": case.input_fixture,
                "capability": case.capability,
                "mappedTest": case.mapped_test,
                "expected": case.expected,
                "actual": actual,
                "passed": not failures,
                "failures": failures,
                "durationSeconds": round(duration, 6),
                "costCny": 0.0,
                "costBasis": "deterministic scripted model; no external LLM call",
            }
            records.append(record)
            print(f"{'PASS' if record['passed'] else 'FAIL'} {case.case_id} {duration:.3f}s")
            for failure in failures:
                print(f"  - {failure}")

    durations = [record["durationSeconds"] for record in records]
    costs = [record["costCny"] for record in records]
    categories = {
        category: {
            "passed": sum(record["passed"] for record in records if record["category"] == category),
            "total": sum(record["category"] == category for record in records),
        }
        for category in ("chart", "multifile", "conversation")
    }
    report = {
        "schemaVersion": 1,
        "source": "tests/eval_cases.md#P1-Evaluation-Cases",
        "passed": all(record["passed"] for record in records),
        "metrics": {
            "passedCases": sum(record["passed"] for record in records),
            "totalCases": len(records),
            "passRate": sum(record["passed"] for record in records) / len(records),
            "averageResponseSeconds": statistics.fmean(durations),
            "maximumResponseSeconds": max(durations),
            "averageCostCny": statistics.fmean(costs),
            "maximumCostCny": max(costs),
        },
        "categories": categories,
        "cases": records,
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# P1 Formal Evaluation",
        "",
        f"- Passed: {report['metrics']['passedCases']}/{report['metrics']['totalCases']} ({report['metrics']['passRate']:.1%})",
        f"- Average response: {report['metrics']['averageResponseSeconds']:.3f}s",
        f"- Maximum response: {report['metrics']['maximumResponseSeconds']:.3f}s",
        f"- Average cost: CNY {report['metrics']['averageCostCny']:.3f}",
        f"- Maximum cost: CNY {report['metrics']['maximumCostCny']:.3f}",
        "",
        "## Case Mapping",
        "",
        "| Case | Category | Input / fixture | Capability | Test mapping | Expected | Actual | Result | Time | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for item in records:
        cells = [
            item["caseId"],
            item["category"],
            item["inputFixture"],
            item["capability"],
            item["mappedTest"],
            item["expected"],
            json.dumps(item["actual"], ensure_ascii=False, separators=(",", ":")),
            "PASS" if item["passed"] else "FAIL: " + "; ".join(item["failures"]),
            f"{item['durationSeconds']:.3f}s",
            f"CNY {item['costCny']:.3f}",
        ]
        escaped = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells]
        lines.append("| " + " | ".join(escaped) + " |")
    SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"P1: {report['metrics']['passedCases']}/{report['metrics']['totalCases']} "
        f"({report['metrics']['passRate']:.1%})"
    )
    print(f"Report: {RESULT}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
