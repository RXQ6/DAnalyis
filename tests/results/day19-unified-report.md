# Day19.3 Unified Evaluation Report

- Overall: **PASS**
- Cases: 60/60
- Harness: PASS
- Regression gate: PASS
- Baseline: `day19-stable-2026-09-21`

## Category Pass Rates

| Category | Rate | Coverage |
| --- | ---: | ---: |
| bad | 100.0% | 15/15 |
| chart | 100.0% | 5/5 |
| conversation | 100.0% | 8/8 |
| holdout | 100.0% | 15/15 |
| multifile | 100.0% | 7/7 |
| p0 | 100.0% | 10/10 |

## Core Metrics

| Metric | Value | Coverage |
| --- | ---: | ---: |
| pass_rate | 100.0% | 60/60 |
| accuracy | 100.0% | 60/60 |
| p0_pass_rate | 100.0% | 15/15 |
| p1_pass_rate | 100.0% | 20/20 |
| bad_case_recognition | 100.0% | 15/15 |
| robustness_rate | 100.0% | 25/25 |
| avg_latency | 0.264508 | 60/60 |
| p95_latency | 0.691525 | 60/60 |
| max_latency | 0.916669 | 60/60 |
| avg_tool_calls | 4.200000 | 40/60 |
| avg_loop_iterations | 1.000000 | 40/60 |
| retry_count | 0 | 40/60 |
| timeout_count | 0 | 60/60 |
| security_violation_count | 0 | 60/60 |
| contract_failure_count | 0 | 40/60 |
| cost | total=0.0, average=0.0, maximum=0.0, currency=CNY | 60/60 |
| token | unavailable (token usage not exposed) | 0/60 |

## Route / Tool / Trace / Contract

- Route evaluated/correct: 0/0
- Tool evaluated/correct: 40/40
- Contract evaluated/valid: 40/40
- Trace available/unavailable: 40/20

## Baseline Delta

| Metric | Current | Baseline | Delta |
| --- | ---: | ---: | ---: |
| p0_pass_rate | 1.000000 | 1.000000 | +0.000000 |
| p1_pass_rate | 1.000000 | 1.000000 | +0.000000 |
| robustness_rate | 1.000000 | 1.000000 | +0.000000 |
| avg_latency | 0.264508 | 0.249866 | +0.014642 |
| p95_latency | 0.691525 | 0.695978 | -0.004453 |
| max_latency | 0.916669 | 0.877718 | +0.038951 |
| average_cost | 0.000000 | 0.000000 | +0.000000 |
| maximum_cost | 0.000000 | 0.000000 | +0.000000 |

## Failure Taxonomy

- No failures

## Regression Gate

| Gate | Status | Reason |
| --- | --- | --- |
| p0_100_percent | PASS | 1.000000 meets minimum 1.000000 |
| p1_not_below_baseline | PASS | 1.000000 meets minimum 1.000000 |
| robustness_not_below_baseline | PASS | 1.000000 meets minimum 1.000000 |
| security_violation_zero | PASS | value is 0 |
| contract_failure_zero | PASS | value is 0 |
| avg_latency | PASS | 0.264508 is within tolerance limit 1.249866 |
| p95_latency | PASS | 0.691525 is within tolerance limit 1.695978 |
| max_latency | PASS | 0.916669 is within tolerance limit 1.877718 |
| average_cost | PASS | 0.000000 is within tolerance limit 0.500000 |
| maximum_cost | PASS | 0.000000 is within tolerance limit 0.500000 |
| existing_thresholds | PASS | all existing P0/P1/Robustness gates passed |

## Current Risks

- P1 legacy cases do not expose complete traces; process metrics remain unavailable for those cases.
- Workflow routes are covered by evaluator tests but are not yet a formal suite in the unified run.
- Token usage is unavailable until the underlying model clients expose it.
- Latency is environment-sensitive; the gate uses a versioned baseline plus explicit tolerance while retaining legacy hard limits.
