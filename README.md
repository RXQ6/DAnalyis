# Data Analysis Agent MVP

PRD v1.0 P0 implementation. The agent reads one CSV/XLSX file, deterministically
routes a natural-language question to a statistics, group comparison, trend,
Top-N or IQR anomaly tool, and prints structured JSON. It runs no user-supplied code
and never changes the source data.

Requirements: Node.js 20 or newer. No third-party packages are required.

```powershell
node src/cli.js --file .\sales.csv --question "按地区分组统计销售额总和"
node src/cli.js --file .\sales.xlsx --question "销售额平均值" --log .\audit.jsonl
npm test
```

Exit code is non-zero for invalid input or unsafe/invalid calculations. A valid but
underspecified question returns `status: "needs_input"`. See
[`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) for the deliberately narrow MVP choices.
