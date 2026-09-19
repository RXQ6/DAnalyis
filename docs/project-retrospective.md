# 数据分析 Agent 最终项目复盘

更新时间：2026-09-19
依据：`docs/PRD-v1.1.md`、当前实现、正式评测结果和 M1–M3 改造记录。

## 1. 项目目标与 PRD 边界

项目目标是让业务用户上传 CSV/XLSX 后，用自然语言完成真实、可追溯的数据分析。LLM 负责理解问题、选择工具、决定是否继续分析和解释结果；数据读取、统计、分组、趋势、异常、占比、同比等计算由确定性程序完成。

PRD 将范围分为：

- P0：CSV/XLSX 读取、基础统计、分组对比、Top N、趋势分析、异常识别和异常输入提示。
- P1：图表、多文件分析和历史对话。
- 明确不做：机器学习预测、复杂建模、自动修改原始数据、模型动态生成并执行任意 Python。
- 运行边界：CSV/XLSX，单文件不超过 20MB；不支持 PDF、图片和超大数据集。

验收目标包括 P0 100%、整体准确率至少 85%、异常识别至少 90%、平均响应不超过 30 秒、单次成本不超过 0.5 元。最终结果均达到或超过这些指标。

## 2. P0：先建立可信的真实计算链路

P0 实现了文件校验、profile、基础统计、分组比较、趋势、异常检测和 Top N。设计重点不是让模型“算对”，而是让模型不能绕过确定性工具自行计算。

数据层对空文件、缺失字段、混合数值文本、不规则 CSV、损坏 XLSX、非法 UTF-8、混合日期和超限文件提供结构化错误。含糊问题会要求澄清，趋势问题必须选择趋势工具，避免凭空给出业务结论。

最终 P0 正式用例 10/10，包含 Bad Cases 的总体结果 15/15；平均响应 0.167 秒，最大 0.206 秒，评测成本为 0。

## 3. Agent Loop、ToolRegistry 与 ToolResult

单步路由无法覆盖“检查数据—执行分析—根据结果继续—生成答案”，因此项目引入受控 Agent Loop：每轮模型只能调用注册工具、请求用户补充或结束；工具 Observation 回填下一轮；`max_iter` 防止无限循环；`stop_reason` 区分正常答案、需要输入、达到上限和不可恢复错误。

随着工具增加，若 Agent Loop 直接认识每个 handler，会形成难以测试的分支。因此引入 ToolRegistry：

- 所有工具通过统一定义注册，禁止绕过 Registry。
- 参数由 schema 校验；注册时检查名称、重复项和 handler 签名。
- 统一处理 timeout、异常、结果大小上限和未知工具。
- Agent Loop 只依赖 Registry 接口，没有图表、多文件、Memory 专用执行分支。

ToolResult 统一包含 `ok`、`data`、`error`、`duration`、`truncated`。它既是模型 Observation，也是后续图表、比较和 merge 的可信输入。下游工具只接受成功、完整且来源可验证的 ToolResult，模型不能提交或覆盖计算值。

## 4. TodoWrite：复杂任务的短期计划状态

TodoWrite 用于多步任务的计划连续性，不承担数据分析。Todo 支持 `pending`、`in_progress`、`completed`，优先按 ID 增量更新，避免完整快照遗漏旧项；Todo summary 会进入后续模型上下文。

Todo 是软约束：简单任务无需创建；未完成 Todo 不阻塞合理工具调用；当前会话可续接未完成项，但不写入长期 Memory。这样既改善复杂任务执行，又没有把规划状态变成 Agent Loop 的硬编码流程。

## 5. 三层 Memory 设计

Memory 被拆为三层，避免把不同生命周期的数据混在一起：

1. 短期层：复用当前运行的 `messages`、AgentState、ToolResult 和 Todo，不新增重复存储。
2. 长期 KV：SQLite 保存少量稳定偏好，如 preferred metric、chart type、time column 和 aggregation。
3. 长期 Semantic：SQLite 保存 SOP、分析经验和稳定摘要，使用本地可替换 embedding 与余弦检索。

`ThreeLayerMemory` 统一 recall/remember；长期写入必须显式触发并按 scope 隔离。当前文件、schema 和 ToolResult 永远优先于历史 Memory。完整对话、原始表格、Todo、Observation、execution trace 和临时 dataset ID 均禁止进入长期存储。Memory 失败采用 fail-open，只记录审计错误，不控制 Agent Loop。

## 6. P1：在现有边界上扩展

### 6.1 图表

`generate_chart` 只接受 `sourceCallId`、受控图表类型和可选标题。数据来自已有 ToolResult，经 Chart Spec 转换后由确定性 SVG renderer 输出。

- `group_compare`、`normalize_share`、`top_n` → bar。
- `trend_analysis` → line。
- `scatter_data` → scatter。
- 占比和散点数值均由工具层计算或提取，LLM 不能传入数据点。
- 来源失败、截断、失活 dataset、缺失 lineage、不兼容类型或超过 100 点时明确拒绝。

### 6.2 多文件

DatasetRegistry 管理任务级 dataset ID、可信路径、文件指纹、安全摘要和派生 lineage。LLM 只看到安全 profile，不看到真实路径或完整数据行。

现有单文件工具通过可选 dataset ID 复用；新增 list/inspect/compare/merge 工具。`compare_datasets` 支持同口径 basic stats、确定性同比和 group compare 分类对齐。merge 采用 inspect→execute 两阶段，只允许安全的一对一 inner/left join；类型冲突、空 key、重复 key、危险基数、文件变化和过大输出会阻止执行。

### 6.3 历史对话

ConversationRunner/ConversationState 位于 Agent Loop 外层，保存当前/最近 dataset、metric、group、filter、time range、历史 ToolResult 和未完成 Todo。新文件替换活动数据集后旧数据默认失活；当前 ToolResult 和当前文件优先于会话历史及长期 Memory。

临时 dataset ID、Todo、筛选条件、ToolResult 和完整聊天只属于当前会话。新会话使用新状态，不继承这些临时值。

## 7. Context Compression 与 Historical Summary

能力增加后，messages、ToolResult、Todo、Memory 和宽表 profile 会持续增大。项目增加独立 Context Compression 层，只压缩给 LLM 的深拷贝视图，不修改真实业务状态。

规则型 v1.1 仅在达到字符数、消息数、大 ToolResult 或宽表阈值时触发，支持：历史 turn 截断、ToolResult 元数据精简、Todo summary、Memory 限长和 Dataset profile 字段上限。system、当前问题、任务目标、最新关键 ToolResult 和当前相关字段优先保留；失败时回退原上下文。

宽表测试中，1,200 列 profile 从 98,809 字符降到 586 字符，保留 40 个字段名和用户明确涉及字段，`omittedColumnCount=1160`，真实 metadata 不变。高压上下文从 89,689 降到 22,373 字符，减少 75.05%，业务答案与 ToolResult 保持一致。

Historical Summary 只摘要更老完整 turn，最近若干轮保留原文；摘要带结构化事实引用、不确定信息区和安全校验。模型失败、非法引用、超长摘要或把不确定内容写成确定事实时，回退规则型 Compression v1.1。20 轮测试从 29,595 降到 6,531 字符，减少 77.93%。

## 8. 关键 Bad Case 与修复

| Bad case | 根因 | 修复 |
| --- | --- | --- |
| 缺失字段、空文件、脏数值、错误日期或损坏文件 | 数据质量不足仍继续分析会产生错误结论 | 输入/profile 层确定性拒绝并返回结构化错误 |
| 趋势问题选择分组工具、含糊问题直接下结论 | 工具选择或意图信息不足 | 路由/评测约束工具语义；信息不足时 needs_user_input |
| 类别占比图输出原始总额 | 缺少工具层归一化 | 新增 `normalize_share`，比例不由 LLM 计算 |
| 两数值字段无法生成散点图 | 无成对数值工具和 scatter schema | `scatter_data` + 受控 scatter spec/SVG |
| 两文件同比只有原值 | 比较工具没有变化率语义 | 工具层计算 absolute change、rate、percent，并处理零基准/缺失 |
| 分类结果不能跨文件比较 | compare 只接受 basic stats | 支持同 metric/operation/groupBy 的 group compare 对齐 |
| 新文件后仍可直接引用旧 ToolResult | 下游图表工具信任调用方来源列表 | 递归验证来源 lineage 和活动 dataset |
| group compare 误带同比模式被静默忽略 | comparisonMode 只在一个分支处理 | 返回 `incompatible_comparison_mode` |
| 临时 dataset ID 进入长期 Memory | 写入防护未覆盖运行时 ID | KV、semantic content/metadata 均禁止 runtime dataset ID |
| 截断结果被下游误用 | preview 不是完整证据 | 图表和比较工具拒绝 truncated ToolResult |
| 缺失分类被当成 0 | 缺失和业务零值语义不同 | 输出 `value=null, missing=true` |

## 9. 最终评测结果

| 评测 | 结果 |
| --- | ---: |
| P0 正式用例 | 10/10 |
| P0 整体（含原 Bad Cases） | 15/15 |
| P1 正式用例 | 20/20 |
| 图表 / 多文件 / 历史对话 | 5/5、7/7、8/8 |
| Robustness bad cases / holdout | 10/10、15/15 |
| Robustness 总体 | 25/25 |
| Memory | 16/16 |
| Todo | 12/12 |
| Context Compression | 9/9 |
| Historical Summary | 8/8 |
| 历史对话独立评测 | 8/8 |
| 图表 / 多文件独立评测 | 5/5、5/5 |
| 多步语义 | 3/3 |
| Python 全量 | 113/113 |
| Node 全量 | 13/13 |

P1 平均响应 0.464 秒、最大 0.796 秒；robustness 平均 0.156 秒、最大 0.177 秒。确定性/scripted evaluator 没有外部 LLM 调用，报告成本为 CNY 0.000。

## 10. 当前限制

- 只支持 CSV/XLSX，单文件不超过 20MB；多文件数量和派生文件生命周期受任务工作目录限制。
- 图表是 SVG 单系列 bar/line/scatter，最多 100 点；不支持饼图、多系列和交互图。
- merge 只执行安全的一对一 inner/left join，不自动放宽一对多或多对多风险。
- ConversationState、Todo 和摘要缓存主要是进程内状态，不支持进程重启恢复或分布式共享。
- Semantic Memory 使用轻量 hashing embedding，长尾语义召回弱于成熟 embedding 模型。
- Context 使用字符数近似 token；单条必须保护的超大 ToolResult 可能仍超过目标窗口。
- Todo 是软约束；真实模型可能跳过规划、重复失败调用或忘记更新。
- 最终文字仍由模型生成，可能发生工具结果正确但数值抄写、基准说明或措辞不准确。
- 当前正式评测大量使用确定性/scripted model，真实模型的随机性、供应商延迟和真实成本覆盖有限。

## 11. 后续最值得优化的方向

1. **真实模型端到端评测与答案 groundedness**：校验最终回答引用的 call ID、metric、dataset、数值和不确定性，优先降低“工具正确、文字错误”的风险。
2. **真实 tokenizer 与上下文预算观测**：用目标模型 tokenizer 替代字符近似，并持续记录压缩收益、超预算和 fallback 率。
3. **Memory 检索质量**：在保持 scope 和显式写入边界的前提下，使用可版本化的成熟 embedding，并建立真实查询召回评测。
4. **会话持久化仅按需求引入**：如果产品需要跨进程恢复，再为 ConversationState 和 summary cache 设计持久化、并发和过期策略。
5. **新业务能力必须由新 PRD 驱动**：多系列图、一对多 join、更多格式或预测能力不应作为维护性优化偷偷进入当前范围。

## 12. 最终结论

M1–M3 已完成。项目从确定性 P0 分析链路演进到受控多步 Agent、统一工具协议、短期 Todo、隔离的三层 Memory、P1 图表/多文件/历史对话，以及只读上下文压缩和可回退历史摘要。最终 P0、P1 和 robustness 均为 100%，没有通过降低标准或修改答案制造通过。当前系统已经满足 PRD v1.1 的 M1、M2、M3 验收目标；后续重点应从继续堆功能转向真实模型评测、答案证据一致性和生产运行观测。
