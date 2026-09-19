"""Deterministic evaluation for the first P1 multi-file slice."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datasets import DatasetRegistry
from tools.handlers import build_default_registry


RESULT = ROOT / "tests" / "results" / "multifile-evaluation.json"


def prior(call_id: str, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {"callId": call_id, "toolName": tool_name, "arguments": arguments, "toolResult": result}


def main() -> int:
    records = []
    with tempfile.TemporaryDirectory(prefix="multifile-eval-") as directory:
        root = Path(directory)
        registry = DatasetRegistry(root / "derived")
        tools = build_default_registry()

        sales_2025 = root / "sales_2025.csv"
        sales_2025.write_text("订单,客户,销售额\nA1,C1,10\nA2,C2,20\n", encoding="utf-8")
        sales_2026 = root / "sales_2026.csv"
        sales_2026.write_text("订单,客户,销售额\nB1,C1,40\nB2,C2,60\n", encoding="utf-8")
        customers = root / "customers.csv"
        customers.write_text("客户ID,地区\nC1,华东\nC2,华南\n", encoding="utf-8")
        duplicate_customers = root / "duplicate_customers.csv"
        duplicate_customers.write_text("客户ID,标签\nC1,A\nC1,B\nC2,C\n", encoding="utf-8")

        first = registry.register(sales_2025)
        second = registry.register(sales_2026)
        customer = registry.register(customers)
        duplicate = registry.register(duplicate_customers)

        def context(previous_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            return {"dataset_registry": registry, "previous_tool_results": previous_results or [], "call_id": "eval"}

        listed = tools.execute("list_datasets", {}, context=context())
        record(records, "MF-01", listed["ok"] and listed["data"]["datasetCount"] == 4, listed)

        args1 = {"datasetId": first["datasetId"], "metric": "销售额", "operation": "sum"}
        args2 = {"datasetId": second["datasetId"], "metric": "销售额", "operation": "sum"}
        stats1 = tools.execute("basic_stats", args1, context=context())
        stats2 = tools.execute("basic_stats", args2, context=context())
        compared = tools.execute(
            "compare_datasets",
            {"sourceCallIds": ["stats-1", "stats-2"]},
            context=context([prior("stats-1", "basic_stats", args1, stats1), prior("stats-2", "basic_stats", args2, stats2)]),
        )
        values = [item["value"] for item in (compared.get("data") or {}).get("groups", [])]
        record(records, "MF-02", compared["ok"] and values == [30, 100], compared)

        inspect_args = {
            "leftDatasetId": second["datasetId"], "rightDatasetId": customer["datasetId"],
            "leftKey": "客户", "rightKey": "客户ID", "joinType": "left",
        }
        inspected = tools.execute("inspect_merge", inspect_args, context=context())
        merged = tools.execute(
            "merge_datasets",
            {"preflightCallId": "safe-plan"},
            context=context([prior("safe-plan", "inspect_merge", inspect_args, inspected)]),
        )
        derived = (merged.get("data") or {}).get("dataset", {})
        record(records, "MF-03", inspected["ok"] and inspected["data"]["safeToExecute"] and merged["ok"] and derived.get("rowCount") == 2, merged)

        risk_args = {
            "leftDatasetId": second["datasetId"], "rightDatasetId": duplicate["datasetId"],
            "leftKey": "客户", "rightKey": "客户ID", "joinType": "left",
        }
        risk = tools.execute("inspect_merge", risk_args, context=context())
        blocked = tools.execute(
            "merge_datasets",
            {"preflightCallId": "risk-plan"},
            context=context([prior("risk-plan", "inspect_merge", risk_args, risk)]),
        )
        record(records, "MF-04", risk["ok"] and risk["data"]["cardinality"] == "one_to_many" and not blocked["ok"] and blocked["error"]["code"] == "unsafe_merge_plan", blocked)

        missing = tools.execute(
            "inspect_merge",
            {"leftDatasetId": first["datasetId"], "rightDatasetId": customer["datasetId"], "leftKey": "不存在", "rightKey": "客户ID", "joinType": "inner"},
            context=context(),
        )
        record(records, "MF-05", not missing["ok"] and missing["error"]["code"] == "missing_join_field", missing)

    report = {
        "passed": all(item["passed"] for item in records),
        "passedCases": sum(item["passed"] for item in records),
        "totalCases": len(records),
        "cases": records,
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Multi-file evaluation: {report['passedCases']}/{report['totalCases']}")
    return 0 if report["passed"] else 1


def record(records: list[dict[str, Any]], case_id: str, passed: bool, result: dict[str, Any]) -> None:
    records.append(
        {
            "caseId": case_id,
            "passed": passed,
            "ok": result.get("ok"),
            "errorCode": (result.get("error") or {}).get("code"),
        }
    )
    print(f"{'PASS' if passed else 'FAIL'} {case_id}")


if __name__ == "__main__":
    raise SystemExit(main())
