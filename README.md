# Data Analysis Agent v1.1

一个支持上传 CSV/XLSX、使用自然语言完成单文件或受控多文件分析的数据分析 Agent。
项目已完成 PRD v1.1 的 M1–M3：P0 确定性分析、受控多步 Agent、图表、多文件、
历史对话、Todo、三层 Memory、Context Compression、Historical Summary 和 Bad Case 优化。

LLM 只负责理解问题、选择受控工具、决定是否继续分析和解释结果。数据读取、统计、
分组、趋势、异常、占比、同比等真实计算由确定性工具执行。项目不运行用户提供的代码，
不让模型动态生成并执行任意 Python，也不修改原始数据。

Requirements: Node.js 20 or newer. No third-party packages are required.

```powershell
node src/cli.js --file .\sales.csv --question "按地区分组统计销售额总和"
node src/cli.js --file .\sales.xlsx --question "销售额平均值" --log .\audit.jsonl
npm test
python tests/eval_agent.py
python tests/eval_p1.py
python tests/robustness_eval.py
python tests/eval_context_compression.py
python tests/eval_historical_summary.py
python tests/eval_multistep_semantics.py
python -m unittest discover -s tests -p "test_*.py"
```

Exit code is non-zero for invalid input or unsafe/invalid calculations. A valid but
underspecified question returns `status: "needs_input"`. See
[`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) for the deliberately narrow MVP choices.

## 稳定版本评测

| 评测 | 结果 |
| --- | ---: |
| P0 | 10/10 |
| P0 整体（含原 Bad Cases） | 15/15 |
| P1 | 20/20 |
| Robustness | 25/25 |
| Python 全量 | 113/113 |
| Node 全量 | 13/13 |
| Memory / Todo | 16/16、12/12 |
| Context Compression / Historical Summary | 9/9、8/8 |
| 多步语义 | 3/3 |

完整演进、限制和剩余风险见
[`docs/project-retrospective.md`](docs/project-retrospective.md) 与
[`processed.md`](processed.md)。可审计评测输出保存在 `tests/results/`。

## 项目结构与各部分作用

| 部分 | 作用 |
| --- | --- |
| `src/` | P0 数据分析主程序：负责文件读取与校验、问题路由、确定性统计工具调用及结果呈现。 |
| `agent/` | Day8 Agent Loop 与 P1 ConversationRunner：负责单轮决策、会话历史、活动数据集和临时分析状态。 |
| `context_compression/` | 只读的 LLM 上下文视图压缩：按阈值生成较老历史摘要，并用规则精简 messages、ToolResult、Todo、Memory 和 Dataset profile；失败时回退稳定的规则型压缩。 |
| `charts/` | P1 图表规格与确定性 SVG 渲染：只消费已有分析 ToolResult，不重新计算业务数字。 |
| `datasets/` | P1 任务/会话级 DatasetRegistry：管理多个数据集 ID、安全摘要、可信路径、活动数据集和派生 lineage。 |
| `tools/` | 受控工具注册表与处理器：提供 Agent 可调用的确定性计算能力，禁止执行任意 Python 代码。 |
| `docs/` | 产品需求、架构设计、实现假设与鲁棒性复盘文档。 |
| `tests/` | 自动化测试、P0/P1 语义评测、鲁棒性评测、测试数据与可审计评测结果。 |
| `package.json` | Node.js 项目信息及 `npm test` 测试入口。 |
| `AGENTS.md` | 项目开发边界、修改原则与交付验证要求。 |
| `.gitignore` | 排除缓存等不应上传的本地生成文件。 |
