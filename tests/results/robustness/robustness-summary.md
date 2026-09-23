# P0 Robustness and Holdout Evaluation

- Result: PASS
- Bad cases: 10/10 (100.0%)
- New holdout cases: 15/15 (100.0%)
- Overall: 25/25 (100.0%)
- Average response: 0.160s
- Maximum response: 0.209s
- Average tool calls: 4.20
- Cost per case: average CNY 0.000, maximum CNY 0.000
- Intermediate-process checks: 100.0%
- Failure reason distribution: {}

## Cases

- PASS BAD-01: missing metric field (0.146s)
- PASS BAD-02: empty file (0.159s)
- PASS BAD-03: mixed date formats (0.175s)
- PASS BAD-04: string in numeric column (0.137s)
- PASS BAD-05: question asks unavailable information (0.138s)
- PASS BAD-06: vague request (0.146s)
- PASS BAD-07: inconsistent CSV width (0.152s)
- PASS BAD-08: corrupted XLSX (0.146s)
- PASS BAD-09: invalid UTF-8 CSV (0.144s)
- PASS BAD-10: file exceeds 20MB (0.145s)
- PASS NEW-01: semicolon-delimited decimal sum (0.163s)
- PASS NEW-02: average with a missing numeric cell (0.155s)
- PASS NEW-03: group average ignores missing metric (0.168s)
- PASS NEW-04: negative minimum (0.154s)
- PASS NEW-05: maximum (0.157s)
- PASS NEW-06: count nonempty text (0.174s)
- PASS NEW-07: top 3 with deterministic tie ordering (0.158s)
- PASS NEW-08: Chinese date trend (0.176s)
- PASS NEW-09: English-header group sum (0.209s)
- PASS NEW-10: English trend phrasing (0.188s)
- PASS NEW-11: no anomaly (0.160s)
- PASS NEW-12: quoted comma in label (0.190s)
- PASS NEW-13: thousands separators (0.157s)
- PASS NEW-14: new XLSX sum (0.159s)
- PASS NEW-15: tab-delimited CSV average (0.147s)
