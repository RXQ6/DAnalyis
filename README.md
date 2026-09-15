# Data Analysis Agent MVP

一个支持上传单个 CSV/XLSX 文件并使用自然语言提问的数据分析 Agent。
Agent 会通过受控工具完成真实的数据读取、统计与分析，并输出有依据、
可复核的结构化结论。

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

## 项目结构与各部分作用

| 部分 | 作用 |
| --- | --- |
| `src/` | P0 数据分析主程序：负责文件读取与校验、问题路由、确定性统计工具调用及结果呈现。 |
| `agent/` | Day8 Agent Loop：负责理解问题、选择已注册工具、维护分析状态并决定是否继续。 |
| `tools/` | 受控工具注册表与处理器：提供 Agent 可调用的确定性计算能力，禁止执行任意 Python 代码。 |
| `docs/` | 产品需求、架构设计、实现假设与鲁棒性复盘文档。 |
| `tests/` | 自动化测试、P0/P1 语义评测、鲁棒性评测、测试数据与可审计评测结果。 |
| `package.json` | Node.js 项目信息及 `npm test` 测试入口。 |
| `AGENTS.md` | 项目开发边界、修改原则与交付验证要求。 |
| `.gitignore` | 排除缓存等不应上传的本地生成文件。 |
