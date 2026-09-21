"""Unified Day19.1 entry point for P0, P1, and Robustness."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval_harness import (  # noqa: E402
    EvalBaseline,
    EvalRunner,
    MetricsCollector,
    RegressionGate,
    UnifiedReportBuilder,
)
from eval_harness.legacy_suites import legacy_suites  # noqa: E402


RESULT = ROOT / "tests" / "results" / "day19-eval-harness.json"
UNIFIED_JSON = ROOT / "tests" / "results" / "day19-unified-report.json"
UNIFIED_MARKDOWN = ROOT / "tests" / "results" / "day19-unified-report.md"
BASELINE = ROOT / "eval_harness" / "baselines" / "day19-stable.json"


def main() -> int:
    runner = EvalRunner()
    with legacy_suites() as suites:
        report = runner.run(suites)
    runner.write_report(report, RESULT)
    metrics = MetricsCollector().collect(report)
    baseline = EvalBaseline.load(BASELINE)
    gate_report = RegressionGate().evaluate(metrics, baseline, report)
    builder = UnifiedReportBuilder()
    unified_report = builder.build(report, metrics, baseline, gate_report)
    builder.write_json(unified_report, UNIFIED_JSON)
    builder.write_markdown(unified_report, UNIFIED_MARKDOWN)
    for name, suite in report["suites"].items():
        status = "PASS" if suite["passed"] else "FAIL"
        print(f"{status} {name}: {suite['passed_cases']}/{suite['total_cases']}")
        for gate, passed in suite["gates"].items():
            print(f"  {'PASS' if passed else 'FAIL'} {gate}")
    for gate in gate_report["results"]:
        print(f"  {gate['status']} regression:{gate['name']}: {gate['reason']}")
    print(
        f"Day19.3: {unified_report['overall_status']} "
        f"{report['passed_cases']}/{report['total_cases']}"
    )
    print(f"Raw report: {RESULT}")
    print(f"Unified reports: {UNIFIED_JSON}; {UNIFIED_MARKDOWN}")
    return 0 if unified_report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
