# 项目进度

更新时间：2026-09-15

## 已完成

### P0 数据分析能力

- 已支持单个 CSV / XLSX 文件的数据读取、字段检查、基础统计、分组比较、趋势分析、异常检测和 Top N 分析。
- 数据读取与计算继续由确定性工具完成，Agent 只负责选择工具、判断下一步和解释结果。
- 未引入任意 Python 代码执行、HTTP、Shell、RAG、Memory、Multi-Agent 或数据库能力。

### 工具系统工程化

- 工具统一通过 `ToolRegistry` 注册和调用，Agent Loop 不硬编码具体分析工具。
- 已支持多工具注册、重复注册检查、未知工具检查、schema 校验和 handler 参数签名检查。
- 已处理循环创建 handler 时的 closure late-binding，通过工厂函数绑定工具配置。
- 工具执行已具备参数校验、异常统一捕获、timeout 和结果截断。
- 工具失败会以 Observation 返回 Agent，不会因可恢复工具错误导致整个 Agent 崩溃。
- 未注册工具统一返回错误码 `TOOL_NOT_FOUND`。
- 工具返回统一为 `ToolResult`：`ok`、`data`、`error`、`duration`、`truncated`。
- 工具调用 trace 已记录工具名、参数、成功状态、结果、错误、耗时和截断状态。

### Todo 任务状态机制

- `AgentState` 已加入 `todos`，每项包含 `id`、`content`、`status`。
- Todo 状态支持 `pending`、`in_progress`、`completed`。
- 已新增并通过 Registry 注册 `todo_write`，用于创建、更新、增删、调整和重排 Todo，并返回当前状态汇总。
- TodoWrite 只管理计划状态，不执行数据读取或分析工具。
- Todo 状态会在后续 Agent 轮次中以按状态分组的概览持续提供给模型。
- 简单一步任务可以直接完成，不强制创建 Todo。
- Prompt 已加入软约束：复杂任务优先规划、一次尽量只有一个 `in_progress`、完成后及时更新、允许根据分析结果调整计划且不强制固定顺序。
- 代码没有设置步骤顺序硬锁；存在未完成 Todo 时，其他合理分析工具仍可正常执行。

## 当前状态

- Todo 单元测试：9/9 通过。
- Python 全量单元测试：38/38 通过。
- Node 基础测试：13/13 通过。
- 多步语义评测：3/3 通过。
- P0 正式用例：10/10，通过率 100%。
- P0 总体评测：15/15，通过率 100%。
- Bad-case recognition：5/5，通过率 100%。
- Robustness：25/25，通过率 100%，其中 bad cases 10/10、holdout cases 15/15。
- 当前未发现 P0、robustness、ToolRegistry、ToolResult 或 Agent Loop 功能回归。
- 当前 Todo 机制回归验收通过，评测标准未修改。

## 最近改动

- 增加轻量级 Todo 状态及按 `completed`、`in_progress`、`pending` 分组的 summary。
- 增加 TodoWrite 受控工具，并接入现有 Registry、ToolResult、Observation 和 trace 链路。
- Agent Loop 会在 Todo 非空时将最新概览加入下一轮模型上下文。
- 补充 Todo 创建、状态流转、持续可见、计划调整、软约束、职责隔离和多步工具交替调用测试。
- 补充未完成 Todo 不阻塞其他合理分析步骤的回归测试。
- 完成 P0、robustness、多步语义、Agent Loop、Registry 和基础功能回归验证。

## 待处理

- 当前没有阻塞验收的问题。
- Todo 属于模型遵循的软约束，模型仍可能跳过规划、忘记更新状态或同时设置多个 `in_progress`。
- TodoWrite 使用完整快照更新，模型遗漏某项时该项会从当前计划中移除。
- Todo 仅保存在单次 Agent 运行的内存状态中，不支持跨运行持久化。
- TodoWrite 会占用 Agent Loop 迭代次数，较长任务可能更容易达到 `max_iter`。
- 当前未限制 Todo 数量，过长计划可能增加模型上下文长度。

## 下一步

- 在不改变当前 P0 / P1 边界的前提下，继续观察真实复杂任务中 Todo 的创建与更新质量。
- 如实际使用出现遗漏更新或上下文过长，再基于真实失败案例补充最小测试和约束。
- 后续任何主要修改继续运行 Node 基础测试、Python 单元测试、P0、robustness 和多步语义回归。
