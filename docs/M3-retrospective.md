# M3 Bad Case 优化与项目复盘

更新时间：2026-09-19

## 阶段结论

- M2 已完成：P1 正式评测 20/20，通过率 100%。
- M3 已完成：高风险 bad case 已完成复现、最小修复、风险台账、项目复盘和全量回归。
- 本阶段不扩展功能范围，不修改 PRD、标准答案或通过阈值。

## 历史失败与处理

| 分类 | 历史问题 | 根因 | 当前处理 |
| --- | --- | --- | --- |
| 数据层 | 缺失字段、空文件、数值脏数据、不规则 CSV、混合日期 | 输入质量不足时若继续计算会产生错误结论 | 输入/profile 层确定性拒绝，P0 与 robustness 持续覆盖 |
| 工具层 | P1-02 输出分组总额而非占比 | 缺少工具层归一化，不能让模型计算比例 | `normalize_share` 确定性计算 |
| 工具层 | P1-03 无散点图 | Chart Schema 仅支持 bar/line，且没有成对数值来源 | `scatter_data` + 受控 scatter spec/SVG |
| 工具层 | P1-09 无同比率 | `compare_datasets` 只返回原值 | 工具层计算绝对变化、同比率和百分比 |
| 工具层 | P1-10 不接受分组结果 | 比较工具仅支持 `basic_stats` | 支持同口径 `group_compare` 分类对齐 |
| 状态隔离 | 派生图表工具可直接消费调用方传入的旧 ToolResult | 图表层信任 `previous_tool_results`，未独立验证活动 dataset lineage | 图表与占比工具递归校验来源 call 和活动 dataset |
| 工具语义 | 分组比较误带同比模式会被静默忽略 | `comparisonMode` 只在 basic stats 分支读取 | 对不兼容来源/模式返回明确错误 |
| Memory | 显式 remember 可夹带临时 dataset ID | 写入防护覆盖表格、Todo、Observation，但未覆盖运行时数据集标识 | 阻止 dataset key 和 `ds_<id>` 进入 KV、semantic content/metadata |

## 分层风险台账

### 数据层

- 已覆盖：空文件、缺失字段、混合类型、异常 CSV 行、混合日期格式、格式限制、文件大小限制。
- 当前边界：字符编码长尾、极端稀疏数据、同名但业务语义不同的跨文件字段仍需由用户确认。

### 工具层

- 已覆盖：Registry schema、统一 ToolResult、timeout、截断、失败来源拒绝、活动数据集校验、占比/同比边界、分组维度校验。
- 当前边界：散点图超过 100 点明确拒绝而不采样；同比基准由 `sourceCallIds` 顺序确定；分类缺失值显式为 `null + missing=true`。

### Agent Loop / Todo

- 已覆盖：最大轮数、可恢复/不可恢复错误、连续工具调用、Todo 增量状态、工具失败 Observation。
- 当前边界：Todo 是模型软约束；真实模型仍可能重复调用失败工具或生成与 ToolResult 不完全一致的文字。

### Memory

- 已覆盖：scope 隔离、显式写入、当前结果优先、相关度/top-k/长度限制、原始数据、Todo、Observation 和临时 dataset ID 防护。
- 当前边界：本地 hashing embedding 对长尾同义表达的召回质量有限；事实优先级仍需最终生成模型遵循 prompt。

### Context / Historical Summary

- 已覆盖：阈值触发、历史截断、ToolResult/Todo/Memory/profile 精简、宽表字段上限、状态不变、fail-open、摘要不确定性校验。
- 当前边界：字符数是 token 的近似；单条受保护结果可能超过目标长度；摘要缓存只在进程内有效。

### 最终生成

- 已覆盖：计算结果必须来自工具、当前 ToolResult 优先、不适合分析时明确停止或追问。
- 当前边界：现有正式评测以确定性/scripted model 为主，真实模型在工具选择和结果表述上的随机波动仍需持续观测。

## 本批新增回归边界

- 图表和占比拒绝引用非活动 dataset 的历史 ToolResult。
- 派生 ToolResult 的来源链不可用或形成循环时拒绝执行。
- 重复 call ID 使用最近 ToolResult。
- `group_compare + year_over_year` 不再静默降级。
- 跨文件缺失类别保持 missing/null，不当作 0。
- 截断的比较来源不读取 preview 数值。
- 临时 dataset ID 不能写入长期 Memory。
- Context 总字符阈值采用包含边界：达到阈值即触发。
- scatter 缺失数值对被计数并省略，超过图表点数上限明确拒绝。

## 架构演进复盘

1. P0 先将真实数据读取与计算放入确定性工具，限制 LLM 只做理解、选择和解释。
2. 多步需求出现后引入 Agent Loop，用 Observation、`max_iter` 和 stop reason 控制执行，而没有开放任意代码执行。
3. 工具数量增长后引入 ToolRegistry/ToolResult，统一注册、schema、异常、超时、截断和 trace，避免主循环硬编码工具。
4. Todo 用于复杂任务的短期计划连续性，但保持软约束，不替代工具状态或长期 Memory。
5. Memory 用于跨任务稳定偏好，并通过 scope、显式 remember 和当前数据优先原则与临时会话状态隔离。
6. P1 图表消费 ToolResult，多文件由 DatasetRegistry 管理，历史对话由 Agent Loop 外层 ConversationState 管理，因此没有重写核心循环。
7. 能力增多导致上下文增长后，先增加只读视图型 Context Compression，再增加可回退到规则压缩的 Historical Summary。
8. M3 冻结功能边界，集中处理跨层来源校验、状态隔离、错误传播和证据一致性。

## 当前验证基线

- P0：10/10；整体 15/15；原 Bad Cases 5/5。
- P1：20/20。
- Robustness：25/25。
- Python：113/113；Node：13/13。
- Memory：16/16；Todo：12/12。
- Context Compression：9/9；Historical Summary：8/8。
- 历史对话：8/8；图表：5/5；多文件：5/5；多步语义：3/3。

## M3 完成后的维护原则

- 只从真实失败或高置信复现出发，不为假设风险重构稳定模块。
- 优先修复错误结论、跨会话状态污染、错误来源引用和失败后伪造答案。
- 每个修复必须先有回归测试，完成后重新运行 P0、P1、robustness 和全量测试。
