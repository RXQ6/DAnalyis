# Data Analysis Agent v1.1

一个支持上传 CSV/XLSX、使用自然语言完成单文件或受控多文件分析的数据分析 Agent。
仓库提供两种入口：根目录的 Node.js CLI，以及 Windows Electron 桌面应用。桌面端
承载界面、文件对话框与 IPC；Python Runtime、DatasetRegistry、SessionStore、
Guardrail 和 HITL 仍是业务事实源。

> **不要直接双击 `desktop/src/renderer/index.html`，也不要把它当网页打开。**
> 它依赖 Electron Main、sandboxed preload 和 Python Runtime；浏览器中没有这些桥接
> 能力，文件选择、Send、Session 等操作无法工作。请启动真正的 Electron 应用。

## Windows 桌面应用：开发启动

前提：Windows x64、Node.js 20+、npm，以及可运行本项目 Python Runtime 的 Python。
桌面依赖锁定在 `desktop/package-lock.json`。在 PowerShell 中使用 `npm.cmd`，
可以避开系统禁止执行 `npm.ps1` 时的脚本策略错误。

```powershell
cd .\desktop
npm.cmd ci
$env:DATA_AGENT_PYTHON = "C:\path\to\python.exe"
npm.cmd start
```

`DATA_AGENT_PYTHON` 指向 Python 可执行文件；开发模式也会依次尝试项目
`.venv` 和 PATH 上的 Python。上述 `npm.cmd start` 会先构建 TypeScript 与
Renderer 静态资源，然后启动 Electron Main、preload、Renderer 和 Python JSONL
Runtime，不需要另开浏览器或单独启动前端服务器。

启动后按以下顺序试用：

1. 点击 **Choose CSV/XLSX**，通过 Windows 文件对话框选择文件。仓库内的
   `tests/fixtures/sales.csv` 可用于试用；文件由 Python 数据输入层读取，
   Renderer 不解析或计算 CSV/XLSX。
2. 在 Message 中输入“按地区汇总销售额”，点击 **Send**。Run State 应由 idle/empty
   进入 running，再依据 Runtime 结果进入 completed、partial、failed 等状态；
   Runtime Events/Trace 按 sequence 展示路由、工具和最终事件。**Stop** 会请求
   取消当前 run。
3. Sessions 显示 Python SessionStore 中的历史记录。重新打开桌面应用后可选择旧
   Session 恢复消息与事件；继续执行沿用原 `thread_id`，新 run 获得新 `trace_id`。
   遇到 waiting_approval 时，审批卡仅显示安全摘要；Approve/Reject 的有效性由
   Python Runtime 校验，前端不自行决定或重放动作。

图表只渲染 Python Runtime 给出的 Chart Spec；前端不重新计算分组、趋势、占比、
同比或异常。错误、Retry、partial 与 stale 均是 Runtime/Session 状态的展示与安全
操作入口，不是另一份业务状态。

## Windows 打包、安装与实际验收

打包机需要 **Windows Python 3.12**，并在该解释器中安装 `cryptography`。
构建脚本会校验 Python 版本相关文件，并把私有 Python、受控项目模块、JSONL Bridge
和 Node 数据桥接打入应用资源；成品运行时不依赖开发机绝对路径，也无需设置
`DATA_AGENT_PYTHON`。

```powershell
cd .\desktop
npm.cmd ci
$env:DATA_AGENT_PYTHON = "C:\path\to\python.exe"
npm.cmd run pack:win
```

默认产物位于 `desktop/release/`：

| 产物 | 默认路径 | 用途 |
| --- | --- | --- |
| NSIS 安装包 | `Data Analysis Agent Setup 0.1.0.exe` | 安装版人工验收与分发候选 |
| Windows unpacked | `win-unpacked/Data Analysis Agent.exe` | 不安装即可运行的打包态检查 |

只需要 unpacked 时运行 `npm.cmd run pack:win:dir`。这些二进制产物由
`desktop/.gitignore` 排除，**不会因为 README 被推送到 GitHub 就自动出现在仓库里**；
请在本机重新构建，或另行发布经过验证的 Release 附件。版本号以
`desktop/package.json` 为准。

安装版验收不能用 dev 或 unpacked 代替：

1. 关闭旧进程，运行本次构建的 NSIS 安装包，选定安装目录。
2. 从**安装目录内**的 `Data Analysis Agent.exe` 启动；在任务管理器中“打开文件所在
   位置”，确认不是 `desktop/dist`、`win-unpacked` 或旧安装目录。
3. 点击 **Choose CSV/XLSX**，人工确认真实 Windows 文件对话框弹出，选择
   `tests/fixtures/sales.csv`；确认文件名显示。
4. 输入“按地区汇总销售额”，点击 **Send**；确认状态变化、Runtime Events/Trace
   出现且最终 completed，回答有实际数据依据。必要时再检查 Stop、图表、审批、
   Error/Retry 和窄窗口布局。
5. 完全退出后从同一安装目录重新启动，选择刚才的 Session，确认消息与事件恢复，
   且旧动作没有再次执行。

自动化 smoke 会给原生文件对话框提供确定性的测试返回路径，但不会替代第 3 步的
人工点击验收。默认 Session 与审批持久化数据位于 Electron 标准
`app.getPath("userData")/runtime` 下；不要为了重新测试而随意删除用户数据。
已完成的 Desktop M6.5 发布门禁与当时产物哈希见
[`docs/Desktop-M6.5-Release-Report.md`](docs/Desktop-M6.5-Release-Report.md)；
该报告不证明以后重新构建的安装包已通过安装验收。

## 自动化验证

```powershell
# 仓库根目录：Node 核心、Python 全量与确定性评测
npm.cmd test
python -m unittest discover -s tests -p "test_*.py"
python tests/eval_agent.py
python tests/eval_p1.py
python tests/robustness_eval.py
python tests/run_day19_eval.py

# desktop 目录：构建、单元/集成、Electron smoke 与真实 Electron E2E
cd .\desktop
npm.cmd test
npm.cmd run test:e2e:packaged
npm.cmd run test:smoke:packaged
npm.cmd run verify:packaged-sidecar
```

先运行 `pack:win`，再运行依赖默认 `release/win-unpacked` 的 packaged E2E、
packaged smoke 和 sidecar 检查。若要对**安装目录的 exe** 做双启动 smoke：

```powershell
node scripts/verify-packaged-smoke.cjs --executable "C:\path\to\installed\Data Analysis Agent.exe" --label installed-smoke
```

`desktop/README.md` 记录了桌面端的开发与打包细节。完整门禁除测试通过外，
还要求 Day19 Regression Gate 11/11、security violations=0、
contract failures=0；不得以界面可见或 unpacked smoke 替代安装版验证。

## 核心能力与边界

项目已完成 PRD v1.1 的 M1–M3：P0 确定性分析、受控多步 Agent、图表、多文件、
历史对话、Todo、三层 Memory、Context Compression、Historical Summary 和 Bad Case 优化。
在这些能力外层提供规则优先的 Workflow / Router 统一入口，将请求分流到
`chat`、`analysis`、`calc` 或 `memory_recall`；其中 `analysis` 继续复用现有
ConversationRunner 和 Agent Loop。
复杂 analysis 任务可选注册一个只读的数据检查 Sub-agent：它使用独立 AgentState/messages、
固定工具白名单和独立迭代/超时预算，只把结构化摘要与证据回填主 Agent。
当前还提供可选的 MCP Adapter：它在 Registry 组装阶段发现 MCP 工具并映射成现有
`ToolDefinition`，因此本地工具和 MCP 工具共用参数校验、`ToolResult`、结果截断和 trace；
默认测试保留内存模拟 MCP Server，Day18.1 另以官方 MCP Python SDK 验证真实 stdio
Client/Server，并把 Adapter timeout 传播为底层 pending request cancellation。
Day16 在 analysis route 内增加可选的项目级 SkillRuntime：Router 先完成粗粒度分流，
SkillRegistry 只使用轻量目录发现 `data-diagnosis`，命中后才加载完整 `SKILL.md`，并通过
受限 ToolRegistry 视图复用现有 Agent Loop，最后校验结构化诊断输出并记录 SkillInvocation。
Day20.1 增加旁路式统一 Observability：每次请求生成 `trace_id`，Workflow、Skill、
ToolRegistry、MCP 和 Sub-agent 继续执行原有逻辑，同时向线程安全 TraceCollector 写入
脱敏、限长的 TraceEvent；旧 `execution_trace`、ToolResult 和 Day19 评测接口保持兼容。
Day20.2 在 ToolRegistry 的 Handler 前增加确定性 Guardrail：读取、分析、图表和只读
Sub-agent 继续执行，原始数据修改与任意 Python/shell 被阻断，显式 MCP 外部写操作返回
结构化 pending approval；所有决策进入同一个 TraceCollector。
Day20.3 为 pending action 增加进程内 HITL 状态机：审批只公开 action hash 与动作摘要，
approve 时一次性取回并执行原动作，reject、expire、hash 不匹配和重放均不会触达底层 Handler。
Day21.1 增加独立 SQLite SessionStore：使用 `thread_id` 持久化会话元数据、canonical
messages 和通用 structured events；支持内存测试与文件数据库跨进程读取，但尚未接入复杂恢复编排。
Day21.2 增加显式状态投影和加密的 SQLite approval repository：调用方组合 Session 读原语
恢复 ConversationState 与结构化事件，pending approval 可在重启后绑定当前 Registry 继续处理。
Day21.3 提供应用层 `Day21Demo`，把 Workflow、Skill、Sub-agent、Memory、Context、MCP、
Observability、Guardrail、HITL、Session 与 Eval Harness 串成可执行 Happy Path 和审批恢复场景。

LLM 只负责理解问题、选择受控工具、决定是否继续分析和解释结果。数据读取、统计、
分组、趋势、异常、占比、同比等真实计算由确定性工具执行。项目不运行用户提供的代码，
不让模型动态生成并执行任意 Python，也不修改原始数据。

## 命令行入口

Requirements: Node.js 20 or newer. 核心 CLI 不需要第三方包；真实 MCP stdio 集成需要
Python 3.10+ 并安装 `requirements-mcp.txt`。

```powershell
node src/cli.js --file .\tests\fixtures\sales.csv --question "按地区分组统计销售额总和"
node src/cli.js --file .\sales.xlsx --question "销售额平均值" --log .\audit.jsonl

# 仅在使用真实 MCP stdio 集成时安装
python -m pip install -r requirements-mcp.txt
```

Exit code is non-zero for invalid input or unsafe/invalid calculations. A valid but
underspecified question returns `status: "needs_input"`. See
[`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) for the deliberately narrow MVP choices.

## 已验证基线（2026-09-23）

以下是 Desktop M6.5 发布门禁记录对应的测试结果，不代表以后每一次本地重建的
安装包都自动通过安装验收；细节和当时产物哈希见上文链接的 Release Report。

| 评测 | 结果 |
| --- | ---: |
| P0 | 10/10 |
| P0 整体（含原 Bad Cases） | 15/15 |
| P1 | 20/20 |
| Robustness | 25/25 |
| Day19.3 统一 Eval Harness（Metrics + Regression Gate + Unified Report） | 60/60 |
| Python 全量 | 261/261 |
| Node 全量 | 13/13 |
| Desktop M6.5 发布门禁 | 27/27 Desktop 测试、Electron E2E、unpacked/installed 双启动 smoke PASS |
| Day19 Regression Gate | 11/11；security violations=0；contract failures=0 |
| Day20.1 Observability 专项 | 6/6 |
| Day20.2 Guardrails 专项 | 7/7 |
| Day20.3 HITL + Approval Resume 专项 | 8/8 |
| Day21.1 SQLite SessionStore 专项 | 10/10 |
| Day21.2 Session Recovery + Persistent HITL 专项 | 7/7 |
| Day21.3 端到端 Demo 专项 | 4/4 |
| Workflow / Router 专项 | 16/16 |
| Sub-agent 专项 | 12/12 |
| MCP Adapter 专项 | 24/24 |
| Day16 Skill 专项 | 18/18 |
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
| `workflow/` | Agent Loop 外层的规则优先请求编排：通过统一 dict state 和 `Workflow.invoke()` 分流到 chat、analysis、calc、memory_recall。 |
| `subagents/` | 可选的单场景数据检查 Sub-agent：隔离上下文、限制工具和执行预算，并向主 Agent 返回精简证据。 |
| `mcp_adapter/` | 可选 MCP Tools 接入：MCPHost 管理 Client 生命周期和权限，Adapter 负责分页发现、ToolRegistry 映射、结果校验与错误归一化；支持 mock Client 与官方 SDK stdio Client，Resources/Prompts 仅保留扩展接口。 |
| `skill_runtime/` | analysis route 内的懒加载专业能力层：发现并运行 data-diagnosis，限制工具、校验输出契约并记录调用 trace。 |
| `eval_harness/` | Day19.3 统一确定性评测层：归一化 P0/P1/Robustness，评估 Route/Tool/Trace/Contract，并可选校验 Day20 Observability/Guardrail/HITL，收集指标、对比版本化 baseline、执行 regression gate 并生成 JSON/Markdown 报告。 |
| `observability/` | Day20.1 统一 TraceEvent 与线程安全 TraceCollector：为请求、路由、Skill、工具、MCP、Sub-agent、契约和错误提供脱敏结构化事件。 |
| `guardrails/` | Day20.2 确定性执行前安全策略：统一 allow、block、needs_approval 决策，并生成不含原始参数的 pending approval 摘要。 |
| `hitl/` | Day20.3 进程内人工审批状态机：私有保存待执行动作，校验 approval ID/action hash，提供单次 approve/reject/expire 与安全恢复接口。 |
| `session/` | Day21.1 独立 SQLite SessionStore：以 thread ID 管理 session，并按写入顺序持久化 messages 与通用 structured events。 |
| `desktop/` | Windows Electron Main、sandboxed preload、Renderer、Runtime Bridge、打包脚本与桌面 E2E；只承载产品界面和状态投影。 |
| `docs/` | 产品需求、架构设计、实现假设与鲁棒性复盘文档。 |
| `tests/` | 自动化测试、P0/P1 语义评测、鲁棒性评测、测试数据与可审计评测结果。 |
| `package.json` | Node.js 项目信息及 `npm test` 测试入口。 |
| `AGENTS.md` | 项目开发边界、修改原则与交付验证要求。 |
| `.gitignore` | 排除缓存等不应上传的本地生成文件。 |
