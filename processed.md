# 项目进度

更新时间：2026-09-21

## 里程碑状态

- M1：完成。
- M2：完成；P1 正式评测 20/20，通过率 100%。
- M3：完成；Bad Case 优化、风险台账、最终项目复盘和全量回归均已完成。

## 已完成

### P0 数据分析能力

- 已支持单个 CSV / XLSX 文件的数据读取、字段检查、基础统计、分组比较、趋势分析、异常检测和 Top N 分析。
- 数据读取与计算继续由确定性工具完成，Agent 只负责选择工具、判断下一步和解释结果。
- 未引入任意 Python 代码执行、HTTP、Shell、RAG 或 Multi-Agent；长期 Memory 仅使用本地 SQLite 持久化，不接触当前文件的原始数据计算链路。

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
- TodoWrite 优先使用 `updates` 按 `id` 增量新增、局部更新或删除 Todo；未包含在本次更新中的旧 Todo 会被保留。
- 为兼容已有调用，TodoWrite 暂时保留 `todos` 完整快照入口。
- Todo 数量上限为 20 项，`id` 最长 64 字符，单项 `content` 最长 200 字符。
- Todo 状态会在后续 Agent 轮次中以按状态分组的概览持续提供给模型。
- 简单一步任务可以直接完成，不强制创建 Todo。
- Prompt 已加入软约束：复杂任务优先规划、一次尽量只有一个 `in_progress`、完成后及时更新、允许根据分析结果调整计划且不强制固定顺序。
- 代码没有设置步骤顺序硬锁；存在未完成 Todo 时，其他合理分析工具仍可正常执行。

### 三层 Memory 机制

- 短期 Memory 继续复用单次运行的 `messages` 与 `AgentState`，没有新增重复的短期存储。
- 新增长期 KV Memory，使用 SQLite 持久化并支持 set、get、update、delete、list；同 scope/key 重复写入会去重并按需更新。
- 新增长期 Semantic Memory，使用 SQLite 持久化向量、本地可替换 embedding 和余弦相似度检索，支持 add、search(top-k)、update、delete；同 scope/kind/规范化内容使用指纹去重。
- `ThreeLayerMemory` 统一提供 recall 与显式 remember；Agent Loop 不直接操作 SQLite 或向量表。
- recall 在首轮模型调用前执行，只拼接与当前问题相关的 KV key，并对语义最低相关度、top-k 和总上下文长度设限。
- remember 仅在用户显式提供写入请求且 Agent 正常生成 Final Answer 后执行；不会自动保存聊天、Todo、工具 Observation 或当前文件数据。
- 长期 Memory 按 `scope_id` 隔离；未提供 scope 时不进行长期召回或写入，避免跨用户共享。
- Prompt 已明确当前文件、当前 schema 和 ToolResult 高于历史 Memory，历史数值不得作为当前统计结果。
- Memory 召回或写入失败会记录到运行时 `memory_errors`，不会改变 Agent Loop 的分析结果或终止原因。
- 已增加对原始 CSV/XLSX 表格内容、Todo 快照和完整运行时载荷的长期写入防护。

### P1 第一版自动生成图表

- P1 第一版自动生成图表能力已完成。
- 新增并通过 Tool Registry 注册 `generate_chart`，没有在 Agent Loop 中硬编码图表工具逻辑。
- 图表工具只接受 `sourceCallId`、受控图表类型和可选标题，不能接受模型提交的数据点。
- 图表数据只从当前 Agent 运行中已有的成功、未截断 ToolResult 读取。
- `group_compare`、`normalize_share` 和 `top_n` 可生成柱状图，`trend_analysis` 可生成折线图，`scatter_data` 可生成散点图。
- 分析结果先转换为结构化 Chart Spec，再由确定性 SVG renderer 写入调用方提供的受控 artifact 目录。
- 图表层不重新聚合、排序、补值或采样；超过 100 个点时明确返回错误。
- 当前不支持饼图、多系列图和交互式图表。

### P1 第一版多文件分析

- P1 第一版多文件分析能力已完成，并于 2026-09-18 完成专项验收与全量回归。
- 新增任务级 `DatasetRegistry`，为每个 CSV/XLSX 生成唯一 `dataset_id`，并管理可信路径、文件指纹、安全摘要和派生数据集 lineage。
- Agent 只接收文件名、格式、行数、字段、字段类型、缺失统计和日期范围等摘要，不接收真实路径或完整数据行。
- 现有 `inspect_data`、`basic_stats`、`group_compare`、`trend_analysis`、`detect_anomaly` 和 `top_n` 在多文件模式下通过可选 `datasetId` 继续复用原确定性 Node 分析逻辑。
- 新增 `list_datasets`、`inspect_dataset`、`compare_datasets`、`inspect_merge` 和 `merge_datasets`，全部通过 Tool Registry 注册并返回标准 ToolResult。
- `compare_datasets` 只引用不同数据集已有的同口径 `basic_stats` 或 `group_compare` ToolResult，模型不能提交或覆盖比较数字；basic stats 比较结果可继续生成柱状图。
- merge 使用 `inspect_merge → merge_datasets(preflightCallId)` 两阶段流程，执行前检查关联字段、类型、空 key、重复 key、join 基数、输出规模和文件指纹。
- 第一版只执行无风险的一对一 `inner` / `left join`；一对多、多对一、多对多、类型不兼容、空 key 和过大输出均阻止执行。
- merge 生成新的派生 `dataset_id`，后续继续使用现有分析和图表工具；完整合并数据不进入 LLM 或长期 Memory。

### P1 第一版历史对话

- 新增 `ConversationRunner` / `ConversationState`，在现有 Agent Loop 外管理多轮会话，没有重写工具决策主循环。
- 会话状态包含当前/最近数据集、最近指标、分组、筛选、时间范围、最近消息、历史 ToolResult 和未完成 Todo。
- 同一会话复用 DatasetRegistry；活动 dataset ID 同时约束模型摘要和真实工具执行，上传新文件后旧数据集默认失活。
- 历史 ToolResult 可继续供现有图表和多文件工具按 call ID 引用；当前轮 ToolResult 和当前活动文件优先于会话历史及长期 Memory。
- `needs_user_input` 已作为明确停止原因接入；信息补齐后未完成 Todo 可在同一会话继续。
- 临时 dataset ID、Todo、ToolResult、筛选条件和完整聊天不会自动写入长期 Memory；长期偏好仍使用现有显式 remember。
- 未配置 Historical Summary 时，会话视图采用最近 12 轮消息与最多 24 条历史 ToolResult 的固定窗口；配置摘要器后只对更老完整 turn 生成派生摘要，最近轮次仍保留原文。

### Context Compression 上下文视图压缩

- 新增独立 `context_compression` 层，只压缩传给模型的消息深拷贝，不修改真实 AgentState、ToolResult、Todo、Memory 或 DatasetRegistry。
- Agent Loop 仅在 `model.complete()` 前增加一个可选压缩步骤；ToolRegistry 和 Tool Handler 继续读取完整真实状态。
- 低于阈值时返回等值上下文；达到总字符数、消息数、大 ToolResult 或宽表阈值时才触发。
- 已支持按完整 turn 截断历史消息、清理旧 ToolResult 传输元数据、精简会话 ToolResult 重复副本、压缩 completed Todo、限制 Memory 视图和按类型归组 Dataset profile。
- system prompt、当前用户问题、当前任务、最新关键 ToolResult 和当前相关字段优先保留。
- 压缩失败采用 fail-open：记录 `context_errors` 并回退原始上下文，不影响 Agent 执行。
- 规则型 Context Compression v1.1 完全确定性；可选 Historical Summary 在会话轮次级运行，失败时回退 v1.1，并记录触发、缓存、覆盖范围和错误审计。

## M3 Bad Case 优化（已完成）

- 修复派生图表/占比工具对调用方历史 ToolResult 的过度信任：当 Conversation 提供活动数据集约束时，递归验证来源 call lineage，拒绝非活动 dataset、缺失 lineage 和循环 lineage。
- 修复 `group_compare` 来源误带 `year_over_year` 时被静默忽略的问题，改为返回 `incompatible_comparison_mode`。
- 修复显式长期 Memory 写入可夹带临时 dataset ID 的问题；KV、Semantic content 和 metadata 均拒绝 runtime dataset key/ID。
- 补充重复 call ID 最近结果优先、截断比较来源拒绝、分类缺失不当作 0、scatter 点数/缺失对、Context 精确阈值等回归测试。
- 新增 `docs/M3-retrospective.md`，记录历史失败、分层风险、架构演进原因和后续原则。
- 新增 `docs/project-retrospective.md`，汇总 PRD、P0/P1、Agent Loop、ToolRegistry、Todo、Memory、Context、Bad Case、最终评测和后续方向。

## 最终验收快照

- P0：10/10；包含原 Bad Cases 的总体评测 15/15。
- P1：20/20；图表 5/5、多文件 7/7、历史对话 8/8。
- Robustness：25/25；bad cases 10/10、holdout 15/15。
- Python：113/113；Node：13/13。
- Memory 16/16、Todo 12/12、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3。
- P1 平均/最大响应时间 0.464/0.796 秒；robustness 平均/最大响应时间 0.156/0.177 秒；确定性评测成本 CNY 0.000。
- PRD、标准答案和通过阈值未为验收结果调整。

## 当前状态

- Todo 单元测试：12/12 通过。
- 历史对话专项测试：9/9 通过；覆盖“那华东呢”“继续刚才两个文件”“还是看销售额”、长对话证据、跨轮图表、换文件隔离、Todo 续接、Memory 冲突优先级和上下文不足。
- 历史对话独立回归评测：8/8 通过；覆盖分析对象/metric/dataset 继承、显式新字段覆盖、临时状态不进 Memory、长期偏好 recall、当前 ToolResult 优先和跨会话隔离，并输出连续 4 轮 trace。
- Context Compression 专项单元测试：6/6 通过；覆盖阈值透传、真实状态不变、五类压缩、最新 ToolResult 保护、fallback、压缩视图下图表链路和超宽表字段上限。
- Context Compression 独立评测：9/9 通过；高压样本由 88,670 字符降至 21,354 字符，减少 75.92%；1,200 列 Dataset profile 由 98,809 字符降至 586 字符，仅保留 40 个字段名和当前问题相关字段，并记录 `omittedColumnCount=1160`；单文件与多文件压缩前后答案和 ToolResult 一致。
- Historical Summary 专项单元测试：7/7 通过；覆盖阈值、旧历史/最近原文边界、状态不变、缓存复用与刷新、摘要失败 fallback、不确定内容校验、受保护上下文，以及最近关键 ToolResult 位于更老 turn 时的原文固定保留。
- Historical Summary 独立评测：8/8 通过；20 轮样本中摘要较老 16 轮、最近 4 轮保留原文，视图由 29,595 字符降至 6,531 字符，减少 77.93%；确认事实引用与原 ToolResult 一致、摘要前后业务答案一致，失败时由规则型 v1.1 实际接管。
- Memory 专项测试：16/16 通过。
- 图表重点验证：8/8 通过，通过率 100%；覆盖分组柱状图、趋势折线图、ToolResult 数值一致性、LLM 数值注入防护、不适合画图提示、图表失败后的文本分析连续性及核心回归。
- 图表专项单元测试：7/7 通过。
- 图表语义评测：5/5 通过。
- DatasetRegistry 专项测试：4/4 通过。
- 多文件工具专项测试：10/10 通过。
- 现有多文件语义评测：5/5 通过，通过率 100%。
- 2026-09-18 多文件补充专项验收：10/10 通过，通过率 100%；覆盖多个 CSV/XLSX 独立注册、`dataset_id` 数据隔离、profile/summary、compare、1:1 inner/left join、缺失/类型不兼容/重复 key 拒绝、1:N/N:1/N:N 风险拦截、merge 后统计/趋势/图表和单文件兼容。
- Todo + Agent Loop + ToolRegistry 专项回归：41/41 通过（Todo 12/12、Agent Loop 11/11、ToolRegistry 18/18）。
- Python 全量单元测试：113/113 通过。
- Node 基础测试：13/13 通过。
- 多步语义评测：3/3 通过。
- P0 正式用例：10/10，通过率 100%。
- P0 总体评测：15/15，通过率 100%。
- P1 正式评测：20/20，通过率 100%；图表 5/5、多文件 7/7、历史对话 8/8。
- Bad-case recognition：5/5，通过率 100%。
- Robustness：25/25，通过率 100%，其中 bad cases 10/10、holdout cases 15/15。
- 当前未发现 P0、robustness、ToolRegistry、ToolResult 或 Agent Loop 功能回归。
- 当前 Todo 机制回归验收通过，评测标准未修改。
- 当前 Memory、Todo、ToolRegistry、ToolResult 和 Agent Loop 边界回归验收通过，评测标准未修改。
- 当前图表、P0、robustness、Memory、Todo、Agent Loop 和 ToolRegistry 回归均通过，未修改 P0 业务逻辑或评测标准。
- 当前多文件、图表、P0、robustness、Memory、Todo、Agent Loop 和 ToolRegistry 回归均通过，现有单文件入口正常，业务代码、测试和评测标准均未为本次评测修改。
- 当前 P1 多文件分析可以验收通过，未发现阻塞验收的问题。
- 当前 P1 历史对话专项、P0、图表、多文件、Memory、Todo、多步语义和 robustness 回归均通过，未修改既有评测标准。

## 最近改动

- 新增 `context_compression/compressor.py`，提供可配置 CompressionPolicy、CompressionResult 和确定性 ContextCompressor。
- AgentState 增加 `context_reports` 与 `context_errors` 审计字段；Agent Loop 在模型调用前生成临时压缩视图并在异常时回退。
- Context Compression 的 Dataset profile 增加默认 40 字段视图上限：当前问题明确涉及的字段优先保留，其余名额先覆盖字段类型再按原始顺序选取，并输出 `omittedColumnCount`；真实 Dataset metadata 不变。
- 新增 6 条 Context Compression 单元测试、9 条独立压缩评测及持久化评测结果；宽表专项同时验证字段上限、相关字段优先、原 metadata 不变，以及单文件/多文件结果一致性。
- 新增 `HistoricalSummaryCompactor`、摘要策略/快照/模型适配器和 ConversationRunner 可选接入点；只构造 LLM 历史视图，不修改 ConversationState，也不改 Agent Loop。
- Historical Summary 默认在历史达到 48,000 字符、旧历史达到 24,000 字符且至少 6 个完整 turn 时触发；保留最近 4 轮，按 source hash 缓存，少量新旧 turn 继续保留原文而不立即重摘要。
- 摘要失败、非法 ToolResult 引用、超长输出或不确定内容进入 confirmed 区域时回退现有最近 12 轮视图，再由 Context Compression v1.1 处理。
- 新增 7 条 Historical Summary 单元测试、8 条独立评测及持久化报告；如果最近原文窗口没有 ToolResult，会把全局最新 ToolResult 所在旧 turn 固定为原文而不纳入摘要；专项对照覆盖事实引用、语义一致性和完整 fallback 调用链。
- 完成 Python 100/100、Node 13/13、P0 15/15、图表 5/5、多文件 5/5、历史对话 8/8、多步语义 3/3、robustness 25/25 回归，未修改既有评测标准。

- 新增 ConversationState、ConversationTurn 和 ConversationRunner，会话级复用 messages、DatasetRegistry、ToolResult 与未完成 Todo。
- Agent Loop 仅增加历史消息、历史 ToolResult、初始 Todo、活动数据集和会话审计字段的可选注入参数；默认值保持旧调用行为。
- DatasetRegistry 增加按活动 ID 输出安全摘要的能力；Node 分析桥和多文件工具拒绝访问当前会话已失活的数据集。
- 增加最近指标、分组、筛选与时间范围提取，以及新文件替换、跨轮图表/比较和 `needs_user_input` 支持。
- 新增 9 条历史对话专项单元测试，并完成 Python 87/87、Node 13/13、P0 15/15、图表 5/5、多文件 5/5、多步语义 3/3、robustness 25/25 回归。
- 新增 `tests/eval_conversation.py` 与可审计结果 `tests/results/conversation-evaluation.json`；独立历史对话评测 8/8 通过，全量回归未发现状态串会话或既有能力退化。

- 增加 DatasetRegistry、安全摘要、唯一 dataset ID、文件指纹和派生数据 lineage。
- 现有分析工具增加可选 datasetId 解析，多文件模式必须指定 ID，旧单文件路径保持兼容。
- 增加 list、inspect、跨 ToolResult compare 和两阶段受控 merge 工具。
- 增加 CSV/XLSX 注册、安全上下文、跨文件比较、图表复用、一对一 merge、缺失字段、类型冲突、重复 key、各种 join 基数和 stale plan 测试。
- 完成现有多文件语义评测 5/5 和覆盖十项验收重点的补充专项验证 10/10，并完成 P0、图表、robustness、Memory、Todo、Agent Loop、ToolRegistry 和多步语义回归。

- 新增 Chart Spec 构造、SVG renderer 和注册工具 `generate_chart`。
- Agent Loop 仅增加通用的 prior ToolResult 与受控 artifact 目录上下文，未加入图表专用分支。
- 增加柱状图、折线图、来源追溯、模型数据注入防护、错误来源、截断来源、类型不兼容、点数上限和 SVG 转义测试。
- 增加 5 条第一版图表语义评测，并完成 P0、robustness、Memory、Todo、Agent Loop、ToolRegistry 和多步语义回归。

- 增加 SQLite KV Memory、SQLite 向量 Memory 和统一 `ThreeLayerMemory` 门面。
- Agent Loop 增加首轮前 recall 与 Final Answer 后显式 remember 两个接入点；无 Memory 配置时保持原行为。
- `AgentState` 增加本次运行的 memory context、召回/写入记录和错误审计字段，不持有数据库对象。
- 增加 Memory 上下文长度限制、相关 KV 选择、semantic top-k、scope 隔离和 fail-open 行为。
- 新增 KV 持久化、向量检索、跨请求召回、事实优先级、Todo 隔离和原始数据防护测试。
- 默认 hashing embedding 增加中英文词项、连续中文 n-gram 和数据分析领域概念别名，改善同义改写召回，同时保持 `Embedder` 接口可替换。
- Semantic 向量记录增加 embedding 版本标识；更换实现或维度后会对已有文本自动重新 embedding，避免新旧向量不兼容。
- KV 增加显式 update 与相同值 no-op；Semantic Memory 增加内容指纹去重、重复 add 更新和按 ID 更新后重新 embedding。
- recall 增加语义最低分数、可配置 top-k 硬上限，并继续严格执行 memory context 字符上限。
- 补充领域同义改写、无关记忆过滤、top-k 上限、KV/Semantic 去重和更新专项测试。

- 增加轻量级 Todo 状态及按 `completed`、`in_progress`、`pending` 分组的 summary。
- 增加 TodoWrite 受控工具，并接入现有 Registry、ToolResult、Observation 和 trace 链路。
- Agent Loop 会在 Todo 非空时将最新概览加入下一轮模型上下文。
- 补充 Todo 创建、状态流转、持续可见、计划调整、软约束、职责隔离和多步工具交替调用测试。
- 补充未完成 Todo 不阻塞其他合理分析步骤的回归测试。
- TodoWrite 从优先完整列表覆盖调整为优先增量更新，降低遗漏旧 Todo 的风险。
- 增加 Todo 数量、id 长度和单项描述长度限制。
- 复用 Agent Loop 已有的同轮多工具调用能力，在不依赖新 Observation 时将 TodoWrite 与分析工具同轮执行；专项场景的 5 次工具调用由 5 个迭代轮次降为 3 个，未修改 Loop 主流程。
- 补充增量保留、局部更新、删除、数量上限、描述长度和同轮调用测试。
- 完成 P0、robustness、多步语义、Agent Loop、Registry 和基础功能回归验证。

## P1 M2 四项能力补齐

- 增加 `normalize_share` 受控工具，将 `group_compare` 结果确定性归一化为占比，图表不接受模型提供的比例值。
- 增加 `scatter_data` 注册工具与 scatter Chart Schema / SVG 渲染，散点数值来自原始数据的确定性成对提取。
- 扩展 `compare_datasets`，支持确定性同比变化率、绝对变化、百分比，以及零基准和缺失值边界。
- 扩展 `compare_datasets` 对同字段、同操作、同分组维度的 `group_compare` 结果进行跨文件分类对齐。
- P1 正式评测 20/20（100%）；P0 10/10、总体 15/15；robustness 25/25；Python 单元测试 105/105；Node 13/13。
- Memory 15/15、DatasetRegistry 4/4、Chart 5/5、Multi-file 5/5、Conversation 8/8、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3 均通过。

## Workflow / Router 最小接入

- 新增 `workflow/` 外层编排包，提供统一的 `Workflow.invoke(state)` dict 入口；输入会被深拷贝，Node 之间统一使用 state / dict 传递结果。
- 第一版 route 固定为 `chat`、`analysis`、`calc`、`memory_recall`；Node Registry 启动时必须与固定集合完全一致，Router 输出和 dispatch 均进行注册校验。
- Router 采用规则优先：数据分析及活动数据集追问进入 analysis，明确长期记忆查询进入 memory_recall，可完整解析的纯算术进入 calc，明确问候进入 chat；只有不明确请求才使用可选 LLM 兜底。
- LLM fallback 不获得工具，只做分类；非法、空白或异常输出会按是否存在活动数据集安全回退到 analysis/chat，不会产生不存在的 intent。
- AnalysisNode 只适配现有 `ConversationRunner.run()`，继续复用 Agent Loop、ToolRegistry、Todo、Memory、DatasetRegistry 和 Context Compression，未修改现有 P0/P1 业务实现及评测标准。
- CalcNode 使用受限 AST 算术解析，禁止变量、函数、属性和任意代码执行；MemoryRecallNode 只调用现有 `recall()`，不自动写长期 Memory。
- 新增 16 条 Workflow / Router 专项测试，覆盖四类规则、规则优先级、LLM 仅兜底、非法 route 防护、Node 职责、输入不变性、四条路径的统一返回契约、活动数据集追问以及真实 Agent Loop 复用。
- 完成 Workflow 16/16、Python 全量 129/129、Node 13/13、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8 回归，未修改既有评测目标。

## 单场景 Sub-agent 最小接入

- 新增可选的 `delegate_data_check` 委派工具，只处理数据结构、基础统计和异常检查这一类只读子任务；Workflow route 和默认 P0/P1 Registry 保持不变。
- Sub-agent 复用现有 AgentLoop、ToolRegistry、ToolResult 和 ContextCompressor，但每次创建独立 AgentState/messages，不注入主历史、Todo、Memory 或 prior ToolResult。
- Sub Registry 固定只允许 `inspect_data`、`basic_stats`、`detect_anomaly`，不包含委派工具自身、Todo、图表、Memory 写入、多文件比较或 merge，并只接受当前 active datasetId。
- 默认限制为 3 次独立迭代、4 次工具调用和 15 秒等待；主 Agent 每次 run 最多委派一次，第二次委派硬性拒绝。
- 返回主 Agent 的 SubAgentResult 只包含状态、短摘要、受限 evidence、使用的数据集、warning、stop reason、usage 和结构化 error，不回灌内部 messages 或完整 execution trace。
- 新增 12 条 Sub-agent 专项测试，覆盖工具白名单、递归/越权拒绝、工具预算、迭代上限、超时、摘要上限、跨 run 状态隔离、父历史隔离、active dataset 校验、重复委派、失败归一化，以及主 Agent 委派后继续执行普通工具或在子任务失败后安全形成最终答案。
- 完成 Sub-agent 12/12、Workflow 16/16、Python 全量 141/141、Node 13/13、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8 回归，未修改既有评测目标。

## MCP 工具最小接入

- 新增可选 `mcp_adapter/`，定义同步 `MCPClient.list_tools()` / `call_tool()`、MCP Tool/CallResult 合约、工具适配器和内存模拟 Server；未引入真实外部服务或第三方依赖。
- MCP Adapter 在现有 Registry 组装阶段执行发现，把远端工具映射为带 Server 命名空间的 `ToolDefinition` 和 handler；默认 Registry 工具集合保持不变，Agent Loop、Workflow 和 P0/P1 调用链未增加 MCP 专用分支。
- 工具发现先校验工具数量、名称、描述、schema 大小及现有 Registry 兼容性，再通过 `register_many()` 原子注册；发现失败时返回可恢复的 `MCPRegistrationReport`，保留全部本地工具。
- MCP 调用成功结果继续由现有 ToolRegistry 统一包装成 ToolResult、执行结果大小限制并写入原 execution trace；`isError`、未知远端工具、协议错误、远端异常和 timeout 均转换为稳定的结构化错误。
- 第一版 `MockMCPServer` 仅暴露确定性 `echo`，`MockMCPClient` 只负责内存转发；Sub-agent 固定工具白名单不会自动继承 MCP 工具。
- 新增 15 条 MCP 专项测试，覆盖发现、命名空间映射、参数校验、标准 ToolResult、Agent Loop 集成、主 Agent 失败恢复、allowlist、原子注册、结果截断、调用/发现 timeout、协议错误、远端异常、Registry/远端未知工具以及 Sub-agent 权限隔离。
- 完成 MCP 专项 15/15、Python 全量 156/156、Node 13/13、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8 回归，未修改既有评测目标。
- 再次完成 MCP 专项与全量回归复测：`list_tools`、Registry 注册、Agent 按名称调用、统一 ToolResult、未知工具、协议错误、远端异常、timeout 和失败后继续执行均通过；额外验证 `mcp_multi__alpha`、`mcp_multi__beta` 与本地 `local_echo` 同时注册和调用时 handler 不串联。复测结果仍为 MCP 15/15、Workflow 16/16、Sub-agent 12/12、Memory 16/16、Todo 12/12、Python 156/156、Node 13/13、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8。

## Day16 data-diagnosis Skill 最小接入

- 新增 `skill_runtime/`，第一版只提供 `data-diagnosis`；Skill 是现有 analysis Harness 内的专业能力封装，不新增 route 或另一套 Agent Loop。
- SkillRegistry 先使用 `catalog.json` 中的 name、description、Trigger 和数据集前置条件完成规则发现；未命中时不读取或注入完整 `SKILL.md`，命中后才加载 definition、Workflow、Boundaries、allowed-tools、Output Contract 和 instructions。
- AnalysisNode 只增加默认关闭的 SkillRuntime 插槽；未配置或未命中时继续原样调用 ConversationRunner。SkillRuntime 使用现有 AgentLoop 类，并通过共享 ConversationState 的 runner view 复用 DatasetRegistry、历史上下文、Memory、Todo、Context Compression 和现有 trace。
- allowed-tools 从当前 ToolRegistry 的既有 ToolDefinition 构造独立受限视图；未授权工具不进入模型 schema，强行调用时返回现有 `TOOL_NOT_FOUND`。第一版不授权 Sub-agent、MCP、merge 或图表工具。
- 新增 SkillDefinition 与 SkillInvocation。Invocation 使用 `contract_valid` 作为输出契约验收字段，并直接提供按调用顺序去重的 `tools_used`；Trigger、权限、状态、耗时、停止原因、迭代数和精简 `trace` 继续用于审计，并以 `skill_invocation` 事件写入现有 AgentState.execution_trace，不复制完整内部上下文。
- data-diagnosis 输出必须满足结构化 JSON contract；确定性 Validator 检查字段、类型、枚举、长度、未知字段、证据不足条件，并确认 evidenceCallId 来自本次成功工具调用。非法输出安全返回 `skill_output_contract_violation`。
- data-diagnosis 触发规则补充“为什么最近销量下降”“最近销售额为什么一直降”“哪个地区导致指标下降”等自然表达；增加 chat、calc、普通聚合、概念解释和字段改名负例，避免仅因出现诊断关键词而误触发。
- Day16 Skill 专项测试扩充为 18 条，覆盖目录发现、四个业务诊断正例、五个负例、数据集前置条件、未命中不加载 SKILL.md、完整定义、受限 Registry、缺失/越权工具、输出契约、证据引用、共享会话、Skill prompt 不进入后续历史、SkillInvocation 核心字段与 trace，以及真实 User → Router → analysis → Skill → Agent Loop 链路。
- 完成 Skill 18/18、Python 全量 174/174、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8 回归，未修改既有评测目标或其他 Harness 逻辑。
- 2026-09-21 再次完成 Day16 冻结前复验：Skill 18/18，确认 Invocation 仅使用 `contract_valid` 并直接提供 `tools_used`，`trace` 只作为审计明细；四个自然语言诊断正例全部命中，五个 chat/calc/普通分析/概念类负例均未误触发。全量结果为 Python 174/174、Node 13/13、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8，Workflow、Sub-agent、MCP、Memory、Todo、ToolRegistry 与 DatasetRegistry 均包含在全量单测中通过。

## 剩余风险与待处理

- 当前没有阻塞验收的问题。
- MCP 第一版仅验证内存模拟 Server；真实 MCP 的 stdio/HTTP 传输、协议握手、认证、连接生命周期和取消语义尚未接入。
- Adapter 可限制主线程等待时间，但 Python 线程无法强制终止已进入阻塞 I/O 的调用；未来真实 Client 必须同时实现传输层 timeout、取消和进程清理。
- MCP inputSchema 当前必须兼容现有 ToolRegistry 支持的 JSON Schema 子集；复杂 `$ref`、`oneOf`、资源和二进制内容尚未支持。
- Day16 第一版只有一个本地静态 Skill；尚未处理在线安装、热更新、Skill 依赖或多 Skill 冲突选择。
- Skill Trigger 使用确定性关键词并要求数据集；仍需通过真实请求观察误命中和漏命中，不能为提高召回而直接放宽到所有 analysis。
- Skill 输出依赖模型遵守 JSON contract；当前非法输出会明确失败，不自动追加 LLM 修复轮次。
- evidenceCallId 校验能确认引用了成功工具调用，但不能单独证明每句话的因果推导正确。
- Todo 属于模型遵循的软约束，模型仍可能跳过规划、忘记更新状态或同时设置多个 `in_progress`。
- 兼容入口 `todos` 仍采用完整快照覆盖；旧调用使用该入口时，遗漏项仍会被移除。
- Todo 默认属于单次 Agent 运行；使用 ConversationRunner 时，仅未完成 Todo 会在当前会话内跨轮续接，不做长期持久化。
- TodoWrite 会占用 Agent Loop 迭代次数，较长任务可能更容易达到 `max_iter`。
- 同轮批量调用只能减少不依赖新 Observation 的 Todo 更新轮次；依赖分析结果的状态调整仍需要下一轮。
- 当前 Semantic Memory 的 embedding 仍为增强 hashing 的轻量本地方案；已通过 `Embedder` 接口与 embedding 版本标识支持后续替换实现，并可在实现或向量维度变化后对已有文本重建向量，避免新旧向量不兼容。
- 显式 remember 当前由调用方提交结构化请求，不会从自然语言对话中自动抽取或总结长期记忆。
- 图表当前支持 SVG 单系列柱状图、折线图和散点图，且调用方必须提供受控 artifact 目录；现有 Node P0 CLI 不负责展示 Agent Loop 的图表 artifact。
- 图表最多接受 100 个结果点，不进行静默采样；更大结果需要用户先缩小分析范围。
- 图表类型与来源工具固定映射，尚不支持饼图、多系列或交互式渲染。
- 多文件第一版最多注册 20 个数据集；每个文件仍受现有 20MB 限制。
- merge 第一版仅支持两个数据集的一对一 `inner` / `left join`；一对多、多对一、多对多会明确提示风险并阻止执行。
- DatasetRegistry 是任务/会话级状态，不提供跨会话数据集持久化；派生文件的生命周期由调用方提供的工作目录管理。
- ConversationState 当前是进程内对象，不支持进程重启后的会话恢复，也不处理多进程共享或分布式并发。
- Historical Summary 是可选依赖；未配置摘要客户端时仍采用最近 12 轮固定窗口。
- 摘要缓存当前为进程内、ConversationRunner 生命周期内状态，不支持进程重启后的复用。
- 摘要语义安全依赖结构化 schema、成功 ToolResult 引用和不确定性关键词校验；隐含歧义仍需要真实模型专项评测持续观察。
- 显式模型 call ID 理论上可能跨轮重复；现有查找采用最近结果优先，自动生成的 call ID 已带 turn 前缀。
- Context Compression 当前使用 JSON 字符数近似上下文规模，不是模型精确 tokenizer；不同模型窗口需要调整 CompressionPolicy。
- 最新关键 ToolResult、system 和当前问题优先级高于目标长度，因此单条超大最新结果可能使压缩后视图仍略高于 `target_total_chars`。
- Historical Summary 不把旧分析数值作为数据证据；被省略的旧数值仍需引用当前保留的 ToolResult 或重新调用确定性工具获取。
- Dataset profile 默认最多向模型展示 40 个字段名；若用户一次明确列举超过 40 个字段，严格上限下只保留最先匹配的 40 个。
- `compare_datasets` 当前支持不同数据集的同口径 `basic_stats` 和 `group_compare` ToolResult；仍不支持任意异构分析结果之间的比较。
- 多文件正式语义评测当前为 5 个持久化用例；本轮覆盖十项验收重点的补充专项验证为独立临时验证，尚未固化为新的正式评测文件。

## 下一步

- 在不改变当前 P0 / P1 边界的前提下，继续观察真实复杂任务中 Todo 的创建与更新质量。
- 如实际使用出现遗漏更新或上下文过长，再基于真实失败案例补充最小测试和约束。
- 后续任何主要修改继续运行 Node 基础测试、Python 单元测试、P0、robustness 和多步语义回归。
- 继续观察真实请求中的 KV 相关性选择、semantic top-k 命中质量和 memory context 长度。
- 在不改变真实 ToolResult 数据来源原则的前提下，根据后续 P1 范围评估多系列和其他图表类型。
- 根据真实多文件请求评估字段映射确认、一对多人工授权和更多 join 类型，不在当前版本自动放宽 merge 风险限制。
