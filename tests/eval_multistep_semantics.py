from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from day8_semantic_cases import CASES, evaluate_case, run_case


RESULT = Path(__file__).resolve().parent / "results" / "day8-multistep-semantics.json"


def main() -> int:
    records = []
    for case in CASES:
        state, model = run_case(case)
        failures = evaluate_case(case, state, model)
        record = {
            "caseId": case.case_id,
            "question": case.question,
            "passed": not failures,
            "expectedToolChain": case.expected_chain,
            "expectedArguments": case.expected_arguments,
            "standardAnswer": case.expected_answer,
            "actualTrace": state.execution_trace,
            "actualFinalAnswer": state.final_answer,
            "stopReason": state.stop_reason,
            "iteration": state.iteration,
            "secondRoundSawObservation": bool(model.calls[1]["messages"] and model.calls[1]["messages"][-1].get("role") == "tool"),
            "failures": failures,
        }
        records.append(record)
        print(f"{'PASS' if record['passed'] else 'FAIL'} {case.case_id}: {' -> '.join(record['expectedToolChain'])} -> Final Answer")
        for failure in failures:
            print(f"  - {failure}")
    report = {"passed": all(record["passed"] for record in records), "passedCases": sum(record["passed"] for record in records), "totalCases": len(records), "cases": records}
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Result: {report['passedCases']}/{report['totalCases']}; report: {RESULT}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
