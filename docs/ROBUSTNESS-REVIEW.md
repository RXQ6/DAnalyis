# P0 robustness review

## Scope

- 10 abnormal-input cases, separate from the original five Bad Cases.
- 15 new holdout questions over new CSV/XLSX fixtures.
- Black-box execution through `src/cli.js`.
- Intermediate checks cover selected tool, exact arguments, repeated calls,
  round limits, error-stop behavior, and deterministic conclusion grounding.
- P1 charting, multi-file analysis, and history are excluded.

## Acceptance gates

- Abnormal-input recognition rate: at least 90%.
- Holdout accuracy: at least 85%.
- Average response time: at most 30 seconds.
- Maximum reported cost per case: at most CNY 0.5.
- Intermediate-process checks: 100%.

## Initial run and fixes

The first run passed 7/10 abnormal cases and 15/15 holdout cases. It exposed:

1. One product defect: a request for nonexistent customer satisfaction could be
   routed using the existing customer text column and fail as a type error. The
   router now refuses ranking when no referenced numeric metric exists.
2. Two evaluator classification defects: mixed dates and dirty numerics correctly
   entered the selected analysis tool, which rejected them before calculating.
   The evaluator now requires the correct tool and arguments plus an `error` tool
   status for these field-level validation cases. This preserves the user-facing
   rejection standard while testing the intermediate process accurately.
3. Date profiling now distinguishes mixed date formats and reports
   `dirty_date_data` rather than silently dropping invalid dates.

Initial recorded failure-reason counts were three process-classification failures
and one error-code mismatch. The verified final run has no remaining failures.

## Final result

- Abnormal cases: 10/10 (100%).
- New holdout cases: 15/15 (100%).
- Overall: 25/25 (100%).
- Intermediate-process checks: 100%.
- Average response time: 0.254 seconds.
- Maximum response time: 0.343 seconds.
- Average tool calls: 4.20; observed range: 1–5.
- Observed rounds: 1; configured maximum: 3.
- Average and maximum reported cost: CNY 0.
- Final failure-reason distribution: empty.

## Limitations

The holdout set was authored locally from the PRD after the original P0 suite and
was not used to build the initial MVP. It is stronger evidence than rerunning the
original cases, but it is not an externally administered or statistically sampled
benchmark. P1 readiness is not evaluated by this review.
