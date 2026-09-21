# Day8 Agent Loop 架构

## 1. 范围

Day8 在现有 P0 数据读取、统计、分组、趋势和异常分析工具之上增加受控的多步执行机制。P1 图表能力继续复用该执行机制和现有分析结果，不推倒重构现有项目结构。

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

AgentState 仅在当前一次 `AgentLoop.run()` 内使用。P1 历史对话由外层
`ConversationRunner` 管理，不把跨轮生命周期塞入 Agent Loop。

### ToolRegistry

ToolRegistry 是工具名称到 Tool Handler 和工具描述的唯一注册入口，负责：

- 注册工具名称、参数约束、说明和对应 Handler。
- 根据 Tool Call 查找已注册工具。
- 拒绝未知工具名称。
- 为 LLM 提供当前允许调用的工具清单。

新增工具必须通过 Tool Registry 注册。现有数据处理模块可作为 Handler 被复用，不要求重写其计算逻辑。

## 4. Observation 回填

Tool Registry 将 Handler 的成功或失败统一为 ToolResult，Agent Loop 将同一结构作为
Observation 回填模型。ToolResult 固定包含：

- `ok`：是否执行成功。
- `data`：成功数据；失败时为 `null`。
- `error`：结构化错误；成功时为 `null`。
- `duration`：Registry 记录的执行毫秒数。
- `truncated`：结果是否因大小限制被截断。

Observation 在此基础上增加工具名称和当前 `iteration`，不再维护另一套结果协议。

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

每轮执行记录直接追加到现有 `AgentState.execution_trace`。每条 trace 包含：

```text
iteration
call_id
tool_name
arguments
success
data
error
duration
truncated
```

任务级 trace 还应记录最终 `stop_reason`。trace 用于复现决策路径、检查工具和参数、识别重复调用并验证是否遵守 `max_iter`；它不作为 Memory，也不跨任务自动复用。

## 6. 与现有项目的关系

- 现有输入校验、数据画像、统计、分组、趋势和异常工具继续保留。
- Day8 只在现有工具调用链外增加 AgentLoop、AgentState 和 ToolRegistry。
- P0 评测指标及 `tests/eval_cases.md` 保持不变。
- P1 第一版图表已按下述最小链路接入；多文件和历史对话仍按原计划执行。

## 7. P1 第一版图表链路

图表生成遵循 `分析 ToolResult → Chart Spec → SVG`：

```text
group_compare / top_n / trend_analysis
  → 标准 ToolResult
  → generate_chart(sourceCallId, chartType)
  → 从当前运行的 prior ToolResult 读取真实数据
  → 结构化 Chart Spec
  → 确定性 SVG renderer
  → spec + artifact ToolResult
```

- `generate_chart` 通过 Tool Registry 注册，Agent Loop 不包含图表工具名称或数据映射逻辑。
- 模型只能提交来源调用 ID、图表类型和可选标题，不能提交或覆盖图表数据点。
- `group_compare`、`top_n` 支持柱状图，`trend_analysis` 支持折线图。
- 失败、截断、来源不兼容或超过 100 个点的 ToolResult 不生成图表。
- artifact 只能写入调用方提供的受控目录；第一版输出 SVG，不引入第三方渲染依赖。

## 8. P1 第一版多文件链路

多文件由任务级 `DatasetRegistry` 管理。Registry 保存 `dataset_id → 可信文件路径`、文件指纹、安全摘要和派生 lineage；模型只看到文件名、字段、类型、行数和日期范围等摘要。

```text
多个 CSV/XLSX
  → DatasetRegistry 注册并生成唯一 dataset_id
  → 安全摘要进入 Agent 上下文
  → 现有分析工具(datasetId)
  → compare_datasets 引用真实 ToolResult
  → 可选 generate_chart
```

受控 merge 使用独立的两阶段链路：

```text
inspect_merge
  → 检查字段、类型、空 key、重复 key、join 基数和输出行数
  → 成功且无风险的 preflight ToolResult
  → merge_datasets(preflightCallId)
  → 重新核对文件指纹和计划
  → 生成并注册派生 dataset_id
```

- 第一版 merge 只支持一对一的 `inner` 和 `left join`。
- 一对多、多对一、多对多、类型不兼容、空 key 和过大输出均阻止执行。
- merge 结果写入 Registry 受控目录，ToolResult 只返回摘要和 lineage，不返回完整数据行。
- 未启用 DatasetRegistry 时，原单文件路径和 P0 行为保持不变。

## 9. P1 第一版历史对话链路

历史对话在 Agent Loop 外增加会话编排层，不改变现有工具决策主循环：

```text
ConversationRunner / ConversationState
  → 注入历史 messages、活动 dataset 摘要、历史 ToolResult 和未完成 Todo
  → AgentLoop.run()
  → 当前轮 ToolResult / Final Answer
  → 更新临时 ConversationState
```

- `ConversationState` 保存 `current_dataset_id`、`last_dataset_ids`、
  `last_metric`、`last_group`、`last_time_range`、最近消息、可复用 ToolResult
  和未完成 Todo。
- 同一会话复用 DatasetRegistry；模型与工具默认只能访问当前活动 dataset ID。
- 上传新文件默认替换活动数据集。旧 Registry 映射可以保留，但旧 ToolResult
  不再注入当前工具上下文，防止混用旧文件。
- 历史 ToolResult 可继续被 `generate_chart`、`compare_datasets` 等现有注册工具引用；
  当前轮 ToolResult 始终排在历史结果之后并优先匹配。
- 会话状态只存在于当前 `ConversationRunner` 生命周期，不写入长期 Memory。
  长期偏好仍通过现有显式 `remember` 写入 KV / Semantic Memory。
- 未配置 Historical Summary 时最多直接回放最近 12 轮，并保留最多 24 条可复用 ToolResult。
- 信息不足时模型可返回 `needs_user_input`，未完成 Todo 可在同一会话下一轮继续。

## 10. Context Compression 上下文视图

Context Compression 只作用于 `model.complete()` 前的消息深拷贝，不修改
`AgentState.messages`、ToolResult、Todo、Memory 或 DatasetRegistry：

```text
ConversationState 完整 turns
  → HistoricalSummaryCompactor（每个会话轮次最多一次、达到阈值时）
  → 较老历史摘要 + 最近原文 turns
  → AgentState / messages
  → Todo summary
  → ContextCompressor（达到阈值时）
  → 临时 ContextView
  → model.complete()

ToolRegistry / Tool Handler
  ← 始终读取完整 state 和完整 previous_tool_results
```

- 默认总上下文达到 28,000 字符、消息达到 36 条、单条 ToolResult 达到 8,000 字符，
  或 Dataset profile 达到 80 列时触发；目标总视图约 20,000 字符。
- system prompt、当前用户问题、当前任务 Todo 和最新 ToolResult 优先保留。
- 历史消息按完整 turn 截断，不产生孤立 tool call / tool message。
- 旧 ToolResult 去除执行耗时、空错误等传输字段；会话中更旧结果只保留 call ID、
  工具名和参数引用，真实结果仍完整保存在 ConversationState。
- Todo 保留进行中/待处理项，已完成项只展示数量和最近若干项。
- Memory 视图触发后限制为 2,000 字符并优先保留 KV；底层 recall 和 Memory 数据不变。
- Dataset profile 默认最多展示 40 个字段名，当前问题相关字段优先，并输出
  `omittedColumnCount`；真实 Dataset metadata 不变。
- 压缩器异常时 Agent Loop 记录 `context_errors` 并将原始上下文传给模型，任务继续执行。
- Historical Summary 是 `ConversationRunner` 的可选依赖，不改变 Agent Loop。默认历史达到
  48,000 字符、可摘要旧历史达到 24,000 字符且至少 6 个完整 turn 时触发；最近 4 轮保留原文。
- 若全局最新 ToolResult 位于最近 4 轮之外，其所在 turn 会额外固定为原文，不进入摘要。
- 摘要按 conversation/source hash 缓存；少于 2 个新旧 turn 且新增旧历史不足 8,000 字符时
  复用摘要，并把尚未覆盖的 turn 继续作为原文传入，不会每轮重新摘要。
- 摘要只允许结构化意图、动作、约束、不确定上下文和成功 ToolResult 引用；不确定内容进入
  confirmed 区域、引用未知/失败 call ID、超长或非法输出都会触发 fallback。
- Historical Summary 失败时恢复现有最近 12 轮视图，并继续经过规则型 Context Compression
  v1.1；两层都只修改 LLM 视图，不修改 ConversationState、ToolResult 或 DatasetRegistry。

## 11. Workflow / Router 外层编排

Workflow 位于 ConversationRunner 和 Agent Loop 外层，只决定请求进入哪条处理路径，
不替代 Agent Loop 的工具选择和多步执行：

```text
Workflow.invoke(state)
  → RuleRouter
  ├─ chat → ChatNode
  ├─ calc → CalcNode
  ├─ memory_recall → MemoryRecallNode
  └─ analysis → AnalysisNode → ConversationRunner.run() → AgentLoop.run()
```

- 第一版 route 固定为 `chat`、`analysis`、`calc`、`memory_recall`，Workflow 启动时要求
  Node Registry 与该集合完全一致，dispatch 前再次校验 route。
- Router 优先使用确定性规则识别数据分析、长期记忆查询、纯算术和明确闲聊；只有规则
  无法判断时才调用可选的 LLM 分类器，分类器没有工具且只允许选择已注册 route。
- LLM 返回非法值或调用失败时，有活动数据集回退 `analysis`，否则回退 `chat`；未知
  route 永远不会进入 Node。
- 所有 Node 使用同一个 dict state；`Workflow.invoke()` 深拷贝输入，不修改调用方状态，
  并统一返回 `status`、`route`、`response`、`data`、`error` 和 `routing`。
- AnalysisNode 只做参数和结果适配，继续复用 ConversationRunner，因此现有 DatasetRegistry、
  Todo、Memory、Context Compression、ToolRegistry 与 Agent Loop 执行链保持不变。
- CalcNode 使用受限 AST 解析器，仅接受有长度、复杂度和数值上限的算术表达式，不使用
  `eval()`，也不执行函数、属性、变量或任意 Python 代码。
- MemoryRecallNode 只调用现有 Memory 的只读 `recall()`；显式 remember 仍沿用现有
  analysis 调用参数，不由 Router 自动写入长期 Memory。

## 12. 单场景 Sub-agent 委派

第一版仅提供可选的 `delegate_data_check` 数据检查委派工具，不增加 Workflow route，
也不改变主 Agent Loop 的决策流程：

```text
Workflow analysis
  → ConversationRunner
  → Main AgentLoop
  → delegate_data_check
  → DataCheckSubAgentRunner
  → 独立 AgentLoop / AgentState / messages
  → restricted ToolRegistry
  → sanitized SubAgentResult
  → 主 Agent Observation
  → 主 Agent 继续调用工具或 Final Answer
```

- 调用方显式把 `data_check_delegate_definition()` 注册到主 Registry；默认 Registry 和
  现有 P0/P1 入口不自动获得委派能力。
- Sub-agent 只接收受限 task、一个已验证为 active 的 datasetId 及 DatasetRegistry 的安全
  公开摘要；不接收主 Agent messages、历史 ToolResult、Todo、Memory 或会话历史。
- Sub-agent 复用现有 AgentLoop、ToolRegistry、ToolResult 和 ContextCompressor，但创建新的
  AgentState；固定工具白名单为 `inspect_data`、`basic_stats`、`detect_anomaly`。
- Sub Registry 不包含委派工具，因此不能递归委派；也不包含 Todo、Memory 写入、图表、
  多文件比较或 merge 能力。
- 默认最多 3 个 Sub-agent 迭代、4 次工具调用和 15 秒墙钟等待；每次主 Agent run 最多
  调用一次委派工具，重复委派以不可恢复错误停止。
- 返回主 Agent 的结果只包含 subtaskId、状态、简短 summary、最多 4 条受限 evidence、
  dataset ID、warning、stop reason、usage 和结构化 error；不返回内部 messages、完整 trace、
  prompt、Todo、Memory 或 Context Compression 报告。
- Sub-agent 超时后立即向主 Agent 返回 timeout；执行线程为 daemon，且预算 deadline 会阻止
  超时后的新工具调用。已经进入底层只读工具的调用仍由该工具自身的 timeout 收敛。

## 13. MCP 工具适配层

MCP Adapter 是可选的 Tool Registry 工具来源，不增加 Workflow route，也不改变 Agent Loop。Host、Client、Server 边界如下：

```text
MCPHost（生命周期、显式 allowlist）
  → MCPClient（transport/SDK 的语义接口）
  → MCP Server

Workflow analysis
  → ConversationRunner
  → AgentLoop
  → ToolRegistry
      ├─ 本地 ToolDefinition → 本地 Handler
      └─ MCP ToolDefinition → MCPToolAdapter → MCPClient.call_tool()
  → 统一 ToolResult / Observation
```

- `MCPHost` 持有一组一对一 Server Client，负责显式工具 allowlist、注册和 best-effort close；
  Adapter 本身也要求 allowlist，绕过 Host 时不会默认暴露 Server 全部工具。
- `MCPClient` 的 Tools 接口独立定义分页 `list_tools(cursor)` 和 `call_tool()`；真实 SDK 只需实现该
  transport-neutral facade，上层 Agent、Registry 和 Adapter 无需改写。Resources / Prompts 目前仅有
  独立 Protocol 扩展位，没有接入 Harness。
- Day18.1 新增 `MCPStdioClient`：在专用后台事件循环中持有官方 MCP Python SDK `Client` 与
  `StdioServerParameters`，把异步 SDK 结果转换成现有同步 Client 合约。stdio 子进程的启动、协议协商、
  JSON-RPC 和关闭均由官方 SDK 管理，Agent Loop 与 ToolRegistry 不感知具体 Client 实现。
- 工具发现显式发生在 Registry 组装阶段。远端 `echo` 会映射为带来源命名空间的
  `mcp_mock__echo`，参数 schema 成为 `ToolDefinition.parameter_schema`，handler 闭包保存真实
  Server 工具名并调用 `call_tool()`。
- 发现过程遍历 `nextCursor` 并限制工具总数；名称支持 MCP 的点号/连字符并在本地命名空间内检查
  归一化碰撞。标准无参数 object schema 会补齐现有 ToolRegistry 需要的空 properties/required；
  协议错误和本地 schema 不兼容分别返回 `mcp_protocol_error`、`mcp_schema_incompatible`。
- 发现结果通过 `register_many()` 原子注册；失败时返回 `MCPRegistrationReport`，已有本地 Registry 不变。
- 调用成功的数据由现有 Registry 统一包装为 ToolResult，并继续使用既有 JSON 序列化、
  大小限制、duration 和 trace。Adapter 校验 content block、`resultType` 和可选 `outputSchema`；
  远端 `isError`、未知工具、协议错误、远端异常和 timeout
  分别映射为稳定的 `mcp_tool_error`、`mcp_tool_not_found`、`mcp_protocol_error`、
  `mcp_server_unavailable` 和 `mcp_timeout`，不会把异常抛到主 Agent。timeout 会调用 Client 的可选
  `cancel_pending()`，真实 SDK facade 应将其绑定到底层 transport 取消。
- `MCPStdioClient.cancel_pending()` 会在线程安全地取消当前 SDK asyncio task；SDK 负责把 cancellation
  传播到 stdio Server。真实集成测试由 Server 捕获取消并写 marker，且取消后同一 Client 可继续调用。
- 默认回归继续使用内存 `MockMCPServer` / `MockMCPClient`；Day18.1 额外提供官方 SDK 的真实 stdio
  Client/Server 集成。Streamable HTTP、认证、资源读取、prompt 和动态通知仍不在当前范围。
- 默认 `build_default_registry()` 不注册 MCP 工具；调用方必须显式构造 Adapter 并注册。
  Sub-agent 仍从固定白名单构造受限 Registry，因此不会自动继承 MCP 权限。

## 14. Day16 data-diagnosis Skill

Skill 是 analysis route 内的专业能力封装，不增加顶层 route，也不实现另一套 Agent Loop：

```text
Workflow.invoke(state)
  → RuleRouter → analysis
  → AnalysisNode
  → SkillRegistry.discover()（仅 catalog 元数据）
      ├─ 未命中 → 原 ConversationRunner / AgentLoop
      └─ 命中 data-diagnosis
          → 加载 definition.json + SKILL.md
          → 从现有 ToolRegistry 构造 allowed-tools 视图
          → SkillRuntime → 现有 ConversationRunner / AgentLoop
          → OutputContractValidator
          → SkillInvocation / execution_trace
```

- 目录只保存 name、description、Trigger pattern、数据集前置条件和完整定义路径；普通 analysis
  不读取或注入 `SKILL.md`。第一版只有存在活动/上传数据集且请求明确包含数据诊断、异常原因、
  波动原因或根因分析等表达时命中。
- 完整 SkillDefinition 包含 name、version、description、allowed-tools、Trigger、Workflow、
  Boundaries、Output Contract 和 `SKILL.md` instructions。目录与完整定义的 name/description
  必须一致，文件路径必须位于受控 definitions root。
- SkillRuntime 继续实例化现有 `AgentLoop` 类，复用原 model、Memory、ContextCompressor、
  max_iter 和基础 system prompt；`ConversationRunner.with_loop()` 让受限 Loop 共享同一个
  ConversationState、DatasetRegistry、历史 ToolResult 和 Todo 生命周期。
- allowed-tools 视图只把原 Registry 中显式声明的 ToolDefinition 注册进新的 ToolRegistry；
  未授权工具不会出现在模型工具清单中，模型强行调用时仍由现有 Registry 返回
  `TOOL_NOT_FOUND`。第一版不允许 Sub-agent、MCP、merge 或图表工具。
- data-diagnosis 最终答案必须是约定 JSON object。Validator 检查必填字段、类型、枚举、
  长度、额外字段、`insufficient_evidence` 的 limitation，并验证每个 evidenceCallId 引用
  本次运行中成功的工具调用；失败时返回 `skill_output_contract_violation`。
- SkillInvocation 记录 Skill/版本、Trigger、allowed-tools、状态、耗时、Agent stop reason、
  迭代数、输出校验和精简工具 trace，不复制完整 messages、Memory 或原始数据；同时以
  `trace_type=skill_invocation` 事件追加到现有 AgentState.execution_trace。
