# Day8 Agent Loop 架构

## 1. 范围

Day8 在现有 P0 数据读取、统计、分组、趋势和异常分析工具之上增加受控的多步执行机制。该变化不推倒重构现有项目结构，不改变 P0 / P1 功能范围，也不提前设计 Day9 安全层、RAG、Memory 或 Multi-Agent。

## 2. 执行链路

```text
User
  → Agent Loop
  → LLM
  → Tool Call
  → Tool Registry
  → Tool Handler
  → Observation
  → 回填 LLM
  → 继续调用工具或 Final Answer
```

每一轮由 Agent Loop 组织。LLM 只产生受控决策；真实数据读取与计算由已注册的 Tool Handler 确定性执行。

## 3. 核心组件

### AgentLoop

AgentLoop 是单次分析任务的执行协调器，负责：

- 初始化并维护 AgentState。
- 在每轮调用 LLM 获取下一步决策。
- 校验 LLM 返回的是 Final Answer 还是已注册工具的 Tool Call。
- 通过 Tool Registry 定位并调用 Tool Handler。
- 将 Tool Handler 返回的 Observation 写入状态并回填 LLM。
- 更新 `iteration`，检查 `max_iter`，并在满足停止条件时设置 `stop_reason`。
- 形成完整 execution trace。

AgentLoop 不负责 CSV / XLSX 解析、统计计算或业务结果推测，这些能力继续由现有确定性模块承担。

### AgentState

AgentState 保存一次任务执行期间的最小状态，包括：

- 原始用户问题和当前数据上下文。
- 当前 `iteration` 与配置的 `max_iter`。
- 已发生的 Tool Call 与对应 Observation。
- 可供下一轮 LLM 决策使用的消息上下文。
- 当前执行状态与最终 `stop_reason`。

AgentState 仅在当前任务内使用。本阶段不提供跨任务 Memory，也不承担历史对话产品能力。

### ToolRegistry

ToolRegistry 是工具名称到 Tool Handler 和工具描述的唯一注册入口，负责：

- 注册工具名称、参数约束、说明和对应 Handler。
- 根据 Tool Call 查找已注册工具。
- 拒绝未知工具名称。
- 为 LLM 提供当前允许调用的工具清单。

新增工具必须通过 Tool Registry 注册。现有数据处理模块可作为 Handler 被复用，不要求重写其计算逻辑。

## 4. Observation 回填

Tool Handler 执行完成后返回结构化结果。Agent Loop 将其标准化为 Observation，至少包含：

- 工具名称。
- 执行状态。
- 结构化 `tool_result` 或错误信息。
- 当前 `iteration`。

Observation 会追加到当前任务上下文并回填给 LLM。LLM 只能基于用户问题、AgentState 和已记录 Observation 决定下一步；不得绕过工具结果自行生成数据结论。

## 5. 执行边界

### max_iter

`max_iter` 是单次任务允许的最大 Agent Loop 轮数。每次 LLM 决策计为一轮。Agent Loop 在进入下一轮前检查上限；达到上限后立即停止，并记录对应 `stop_reason`，防止无效循环和成本失控。

### stop_reason

任务结束时必须记录 `stop_reason`。当前需要支持：

- `final_answer`：已有充分工具证据并生成最终答案。
- `max_iter`：达到最大轮数。
- `needs_user_input`：缺少字段、目标或其他必要信息。
- `unrecoverable_tool_error`：工具执行失败且当前任务不能继续。

### execution trace

每轮执行记录形成有序 trace。每条 trace 至少包含：

```text
iteration
tool_call
tool_result / observation
```

任务级 trace 还应记录最终 `stop_reason`。trace 用于复现决策路径、检查工具和参数、识别重复调用并验证是否遵守 `max_iter`；它不作为 Memory，也不跨任务自动复用。

## 6. 与现有项目的关系

- 现有输入校验、数据画像、统计、分组、趋势和异常工具继续保留。
- Day8 只在现有工具调用链外增加 AgentLoop、AgentState 和 ToolRegistry。
- P0 评测指标及 `tests/eval_cases.md` 保持不变。
- P1 的图表、多文件和历史对话仍按原计划执行，不在 Day8 架构中提前实现。
