# MVP assumptions

PRD v1.0 leaves the following implementation details open. The MVP uses these
conservative assumptions without expanding into P1:

1. The public interface is a local, single-request CLI. It accepts exactly one
   CSV/XLSX file and one natural-language question, and returns JSON.
2. Natural-language routing is deterministic and rule-based. No model performs
   arithmetic, data parsing, or result synthesis; all reported values come from
   named program tools.
3. Column references are matched exactly (case-insensitively) against the uploaded
   headers. The agent does not invent aliases for missing business fields.
4. Supported statistics are sum, average, count, minimum and maximum. Top-N is
   part of basic statistics and defaults to 5 only when the user says “Top” but
   supplies no number.
5. Group comparison requires a grouping field, a numeric metric and an aggregation.
   “按…统计…” defaults to sum; a bare/ambiguous request asks for clarification.
6. Trend analysis groups a numeric metric by a parseable date column and returns
   ascending daily totals. It does not forecast, interpolate, or draw a chart.
7. Anomalies use Tukey's 1.5×IQR rule on a numeric column. Fewer than four valid
   values are insufficient for anomaly detection.
8. Empty numeric cells are reported as missing and excluded. Non-empty text mixed
   into an otherwise numeric field makes that field `mixed`; numeric analyses stop
   with a cleaning prompt instead of silently coercing it.
9. CSV delimiter detection covers comma, tab and semicolon. XLSX reads the first
   worksheet only, uses cached formula values, and does not evaluate formulas.
10. Dates accepted from text are ISO-like year-month-day forms (including Chinese
    年/月/日 notation). Ambiguous locale-only dates are not guessed.
11. Logging is returned in the response as an audit object and can additionally be
    appended to a JSONL file with `--log`. Model call count and cost are zero.
12. P1 charting, multi-file analysis and conversation history are intentionally absent.
