# CURRENT TASK

## 当前阶段

**Phase 1.5 最终产品验收已完成，Phase 1 已冻结。** 2026-09-26，未新增产品功能，
仅在 Electron E2E 中固化 1600/1200/900/700/520px 五档布局与普通 UI 工程字段
不可见的断言。Empty、Session、Dataset、Analysis、Chart、“分析过程”、Approval、
Error/Retry、左右区域拖拽与折叠均按 Phase 1.4 展示层和原有 Runtime 流程验收。
Python Runtime、IPC/Event contract、Session/HITL/Dataset/Chart 业务事实源未改。

最终回归：TypeScript build、Desktop 30/30、Electron smoke、开发态和打包资源态
E2E 各 9 步、Node 13/13、Python 261/261、P0 15/15、P1 20/20、Robustness
25/25、Day19 60/60、Regression Gate 11/11 全 PASS；security violations=0、
contract failures=0。新 unpacked 与独立安装目录中的真实 exe 双启动 smoke、
packaged sidecar 均通过。普通可见界面的整体文本断言不含 JSON、内部 ID、sequence
或 tool args；Session 标题和结构化结果保持人类可读。

最新 NSIS installer 为 `desktop/release/Data Analysis Agent Setup 0.1.0.exe`，
SHA256 `95DC64EAB21D721AA17296E95419523272CC0205E1FCCCD2B638CA0ABFC2454B`。
安装到独立目录 `desktop/release/phase1.5-installed-20260926`，安装退出码 0。
从该目录的 `resources/app.asar` 启动真实窗口并做可见操作验收：Empty 首页、
设置与集成、“分析过程”入口、系统 CSV/XLSX 文件对话框、测试 CSV 选择、
5 行/4 列数据概览和结果 1580 均实际显示，普通 UI 未出现工程字段。
这项可见验收由 Codex 操作并目视，未声称用户另行签收；Approval、Error/Retry、
Chart 和五档宽度另由真实 Electron E2E/Smoke 覆盖。

已知限制：installer 未签名；品牌图形仍为工作占位；Chart Spec v1 仍仅支持单系列
bar/line/scatter 和最多 100 点；没有 Runtime 结构化 Insight 来源；干净机器、
多显示器缩放及升级/卸载路径未验收。建议稳定标签名 `desktop-phase1.5-stable`，
本轮仅提出建议，未创建标签。下一阶段等待用户明确指令，不进入 Phase 2。

## 历史阶段：Phase 1.4 产品级桌面视觉重设计

**Phase 1.4 产品级桌面视觉重设计已实施并完成自动化回归。** 2026-09-24，
Renderer 已切换到分析画布中心布局：自然语言 Session 标题、CSV/XLSX 引导空首页、
确定性数据概览与结构化结果表、专业化 Chart Card、默认折叠的“分析过程”、可拖拽左右
宽度与窄窗口重排，以及只标记“规划中”的 Settings / Integrations。Windows 原生通用
标题文字和默认英文菜单已从可见窗口移除，使用简洁可拖动标题栏、系统窗口控制区和图标按钮。
当前品牌图形仅为统一资产入口的工作占位，不作为最终品牌确认稿。

本轮未修改 Python Runtime、IPC / Runtime Event contract、Session / HITL / Dataset /
Chart 业务事实源。普通 UI 不展示 thread / trace / run 等内部 ID、sequence、raw JSON、
tool args 或 API Key 值。数据行数、字段数量只取 DatasetSummary；当前 Runtime 投影没有
结构化业务 KPI / Insight 字段，因此不生成业务 Metric / Insight Card。

最终门禁：TypeScript build、Desktop 30/30、Electron smoke、开发态与打包资源态
E2E 各 9 步、Windows unpacked exe 双启动 smoke、packaged sidecar、Python 261/261、
Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、Day19 60/60、Regression Gate
11/11 全 PASS；security violations=0、contract failures=0。NSIS installer 已重新构建，
位于 `desktop/release/Data Analysis Agent Setup 0.1.0.exe`；本轮没有覆盖已安装的
Phase 1.3 目录，也没有对新 installer 做独立安装验收。

剩余限制：Chart Spec v1 仍只有单系列 bar / line / scatter，最多 100 点；无多系列
legend 或独立结构化 insight 来源。真实系统文件选择框在自动化中提供确定性返回路径，
新 installer 的人工视觉与安装流程尚未验收。下一阶段等待用户明确指定，不进入 Phase 2。

## 历史阶段：Phase 1.3 UI/UX Product Polish

Phase 1.3 UI/UX Product Polish 已完成。Renderer 的字体、间距、圆角、边框、卡片层级、
状态语义色、按钮反馈和溢出/滚动规则已统一；700px/520px 窗口重排通过真实 Electron
E2E 检查。仅展示层改变，原按钮 ID/事件绑定与 Python 业务事实源保持不变。

验收：TypeScript build、Desktop 27/27、Electron smoke、开发态/打包资源态 E2E
各 8/8、重建 unpacked 真实 exe 双启动 smoke、Python 261/261、Node 13/13、
P0 15/15、P1 20/20、Robustness 25/25、Day19 60/60、Regression Gate 11/11 全 PASS。
本轮未生成新 NSIS installer，现有 installer 仍是 Phase 1 前 UI；真实原生文件对话框
人手操作及多显示缩放/干净机器人工视觉检查未覆盖。下一轮等待用户指定。

## 历史阶段：Phase 1.2 UI/UX Product Polish

Renderer 增加 Chart Card、按 sequence 的脱敏 Trace Timeline、仅显示安全字段的 HITL
Approval Card，以及 failed/partial/stale 的 Error/Retry 状态视觉区分；所有原按钮 ID、
事件绑定和 Python 业务事实源保持不变。当时验收为 TypeScript build、Desktop 27/27、
原 Electron smoke、开发态/打包资源态 E2E 各 7/7、重建 unpacked 真实 exe 双启动 smoke、
Python 261/261、Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、Day19 60/60、
Regression Gate 11/11 全 PASS。

## 历史阶段：Phase 1 第一轮最小布局

Phase 1 UI/UX Product Polish 第一轮最小布局已完成。Renderer 现在有顶部 Session/Dataset/
Run Status、左侧 Session/Dataset Sidebar、中间 Chat/Analysis/Chart、底部固定输入区；
右侧 Trace 和原有 Error/HITL/状态卡保留。所有原按钮 ID、事件绑定与 Python 业务边界不变。

验收：TypeScript build、Desktop 27/27、原 Electron smoke、开发态/打包资源态 E2E 各 7/7、
新 unpacked exe 双启动 smoke、Python 全量 261/261、Node 13/13、P0 15/15、P1 20/20、
Robustness 25/25、Day19 60/60、Regression Gate 11/11 全 PASS。仅重新构建了 unpacked，
现有 NSIS installer 仍为 Phase 1 之前的 UI；本轮没有进行新的安装包验收。

当时的下一轮 UI/UX 工作现已完成 Phase 1.2，见上文；不自动进入深度美化或业务能力扩展。

## 历史阶段：Desktop M6.5

Desktop M6.5：Release Gate + Release Report 已完成；全部 required gate PASS，Desktop M6 完成。
统一报告：`docs/Desktop-M6.5-Release-Report.md`。版本 0.1.0 的 NSIS installer 已实际安装到
`desktop/release/m6.5-installed`，安装后 exe 首次完成 CSV 真实分析，退出并重启后恢复旧 Session；
不是 unpacked/dev 启动。安装态 smoke 证据位于
`desktop/release/m6.5-installed-smoke-xR3Qia/{first,resume}.json`。

最终门禁：TypeScript build、Desktop 27/27、开发态与打包资源态 Electron E2E 各 7/7、
unpacked 与 installed 双启动 smoke、packaged sidecar、Python 261/261、Node 13/13、
P0 15/15、P1 20/20、Robustness 25/25、Day19 60/60、Regression Gate 11/11 全 PASS；
security violations=0、contract failures=0。未修改 Python Runtime 业务语义或评测标准。

剩余非门禁风险：真实原生文件选择框交互未自动化、未在干净机器测试、安装包升级/卸载路径未验收，
installer/exe 未签名。下一阶段等待用户明确指定，不自动继续。

## 历史阶段：Desktop M6.4

Desktop M6.4：Packaged Smoke 已完成。从重新构建的 electron-builder 真实
`desktop/release/win-unpacked/Data Analysis Agent.exe` 先后启动两个独立进程，不用 dev 模式。
首次确认 Main/Preload/Renderer 与 packaged Python sidecar，经过文件按钮、Send 和真实 Python
数据分析得到 6 条 Runtime Events、`completed` 和销售额总和 1580。关闭进程后重启同一 exe，
从标准 userData 恢复原 thread、4 条消息和 6 条 Trace，没有重复执行旧 run。
NSIS installer 同时重新构建，但尚未执行独立安装；仅系统文件对话框的返回路径由测试提供，
核心 IPC、Runtime、SessionStore 没有 mock。验收结果位于
`desktop/release/m6.4-smoke-y1aRT9/first.json` 与 `resume.json`。

当时的下一阶段候选为 Desktop M6.5；现已完成，见上文。

M6.4 Desktop 单元 27/27、原 Electron smoke、M6.3 开发态与打包资源态 E2E 各 7 个场景、
packaged sidecar、真实 exe 双启动 smoke 均 PASS；Python 全量 261/261、Node 13/13、
P0 15/15、P1 20/20、Robustness 25/25、Day19 60/60、11 项 Regression Gate 全 PASS。
未修改 Python Runtime 业务语义、评测标准或 P0/P1 逻辑。首次在受限测试沙箱中因标准
AppData 缓存目录权限不足失败；正常桌面权限重跑通过，未修改产品路径。

M6.3 新增真实 BrowserWindow UI 测试，在开发态和打包资源态各通过 7 个步骤，
覆盖启动、CSV/XLSX 选择、Send、Run State、Runtime Events、Stop/Cancel、
Session List/Resume、HITL Approve/Reject、真实文件错误/Retry 和 Trace Panel。

M6.3 未修改 Python Runtime 业务语义、P0/P1 逻辑或评测标准。首次整套复跑发现
E2E 测试将测试目录误作 Main 编译目录，已只修正测试入口路径并在两种模式重跑通过。
Desktop 单元 27/27、原 Electron smoke、新开发态 E2E 与打包资源 E2E 均 PASS；
Python 全量 261/261、Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、
Day19 60/60、11 项 Regression Gate 全 PASS。

M6.2 的 Windows unpacked 与 NSIS installer 包含私有 Python 3.12、Python JSONL Bridge、
项目业务模块、Node 数据桥和私有 Node 可执行文件。packaged Electron 经 Main/Preload
成功启动真实 run，直接 packaged sidecar 完成 CSV 注册与分析 run；不依赖开发机绝对路径。

M6.2 构建使用 `DATA_AGENT_PYTHON` 作为构建机输入，产物中使用
`process.resourcesPath/python-runtime/python.exe`。Python stdout 只传协议 JSONL，
stderr 为日志；缺少可执行文件/Bridge 时返回结构化 IPC 错误而不使 Electron 崩溃。
未修改 Python Runtime 业务语义或评测标准。

M6.1 使用 electron-builder 26.15.3、Electron 38.8.6；Main/Preload/Renderer 进入 app.asar。
开发态使用仓库相对路径，打包态使用 process.resourcesPath，运行数据位于 Electron
标准 userData/runtime。打包产物不引用开发机绝对路径。BrowserWindow 继续保持
contextIsolation=true、nodeIntegration=false、sandbox=true。

M6.2 验证：Desktop 单元 27/27、Electron E2E PASS、Windows unpacked 真实 run 烟测
退出码 0；packaged CSV 分析返回销售额总和 1580，8 条 stdout 均为协议 JSONL。
Python 全量 261/261、Node 13/13、Day19 60/60、P0 15/15、P1 20/20、
Robustness 25/25、11 项 Regression Gate 全 PASS。安装包已构建，尚未做独立安装验证。

桌面层继续保持零侵入边界：Electron Main 负责原生文件选择、IPC 和进程宿主；Python Runtime 是
Workflow、Dataset、Agent、Tool、Chart 和安全决策的唯一业务事实源；Renderer 只投影事件和渲染
已有 Chart Spec。

## Desktop M4 已实现能力

- 新增 `sessions:list`、`sessions:get`、`sessions:resume` IPC；列表、消息、事件和恢复状态均来自
  Python `SQLiteSessionStore` 与 `SessionStateProjector`，Electron 不维护第二份 Session 数据。
- Session 列表展示 `thread_id`、`updated_at` 与最近用户/Agent 消息摘要；选择旧 Session 后恢复
  messages、持久化 events 和 pending approval，并继续沿用原 `thread_id`。
- 每次新执行和审批恢复均生成新的 `run_id` / `trace_id`；恢复只 hydrate，不重放历史已完成动作。
- 新增 `approvals:approve`、`approvals:reject` IPC。Renderer 只回传 Runtime 给出的 opaque ID/hash；
  Python `PersistentApprovalManager` / `SQLiteApprovalRepository` 继续唯一校验 thread、approval ID、
  action hash、TTL 和 consumed/replay 状态。
- `waiting_approval` 显示只包含 action type、risk summary、approval ID、expires_at 的审批卡片，
  不展示原始工具参数；Approve 只执行加密保存的单个原动作，Reject/expired/mismatch/replay 均不执行。
- Run State 新增 `resuming`、`rejected`、`expired`；所有状态仍由 Runtime Event 按 sequence 投影。
  Renderer 按当前 thread 过滤事件，Session A 的事件不会投影到 Session B。
- Desktop M1/M2/M3 的 Chat、File、Chart、取消、partial 和安全 BrowserWindow 边界保持不变。

## 验收结果

- Desktop TypeScript/IPC/Runtime/Session/HITL 专项：20/20 PASS。
- 真 Electron BrowserWindow E2E：PASS；覆盖 Session 列表/恢复、审批卡片、Reject 与 Approve 恢复。
- Python 全量：261/261 PASS。
- 原 Node 测试：13/13 PASS。
- P0：15/15 PASS。
- P1：20/20 PASS。
- Robustness：25/25 PASS。
- Day19 Eval Harness：60/60 PASS。
- 原 11 项 regression gate：全部 PASS。
- Day19 average / p95 / max latency：0.284s / 0.761s / 0.947s。
- Security violations：0；Contract failures：0。
- 未修改 baseline、threshold 或既有评测预期。

## Desktop M4 边界复验

- Runtime 宿主重启后 Session 列表、messages/events 与 pending approval 可从同一 SessionStore 恢复。
- Renderer reload 后 pending approval 卡片可重新 hydrate，Approve 保持原 thread ID 并生成新 trace ID。
- approval 重复点击由按钮 pending 状态阻止，Python consumed 状态继续阻止跨进程 replay；expired、
  reject 和 action hash mismatch 均不执行。
- Session A/B 除单元隔离外，Electron E2E 注入其他 thread 的迟到 event 后也未污染当前 UI。
- Session 切换不注册新的 Runtime listener；Renderer reload 会销毁旧 preload context/listener。
- hydrate 失败现在显示结构化错误和最小 Retry；Retry 成功后清除错误并恢复消息。
- 不存在的 thread ID 返回 `session_not_found`；重复 hydrate 已完成 Session 不新增
  `approval_resumed`，不重复执行历史动作。

## Desktop M5 已实现能力

- 新增纯 Renderer `Trace Panel` 投影，覆盖 route、skill、tool、MCP、sub-agent、guardrail、
  approval、error 和通用 Runtime 事件；run 内按 Runtime sequence 排序，Session hydrate 使用
  SessionStore 返回的规范顺序。面板和每条事件均可折叠。
- Trace 只显示 sequence、分类、受控名称、状态和 error code，不渲染 metadata、arguments、
  ToolResult、路径、错误正文或 action hash；thread/run 切换继续沿用 M4 隔离边界。
- 统一 `loading`、`empty`、`running`、`partial`、`stale`、`waiting_approval`、`completed`、
  `failed`、`cancelled` 九种产品状态。每种状态均说明当前发生的事情、是否可继续及下一步操作。
- Runtime/IPC/Session/File/Chart 错误统一显示 code、message、action；可恢复错误显示 Retry。
  Session hydrate Retry、run Retry 和 Session refresh 均不会绕过 Python Runtime。
- partial 状态保留已生成回答与图表，单独展示缺失内容；stale 状态提供 Session refresh 入口，
  Dataset 仍通过原文件选择入口重新选择。
- Retry 沿用当前 thread ID，并由 Runtime 创建新 run/trace。`waiting_approval` 不提供通用 Retry；
  approval 决策失败也不自动重放，已完成高风险动作继续由 Python consumed/replay 规则保护。
- 未修改 Python Runtime、Session、Guardrail、HITL、P0/P1 或评测业务语义。

## Desktop M5 验收

- Desktop TypeScript/IPC/Runtime/Trace/Product State 专项：23/23 PASS。
- Electron E2E：PASS；覆盖 Trace 顺序与脱敏、partial 保留、failed→Retry、stale、cancelled、
  waiting approval Retry 隔离、Session/run 隔离和 Renderer reload。
- Python 全量：261/261 PASS；Node：13/13 PASS。
- Day19 Eval Harness：60/60 PASS；原 11 项 regression gate 全部 PASS。
- Security violations：0；Contract failures：0。
- Day19 average / p95 / max latency：0.265s / 0.692s / 0.917s。

## 当前剩余风险

- BridgeModel 是最小 composition adapter，尚未接入真实模型客户端、凭证和模型级重试。
- 每个 run 独立 worker 仍有进程启动开销，supervisor 的长期 run/dataset 状态需要有界清理。
- 尚无 heartbeat、事件重放和断线后的 sequence gap 恢复。
- Main 仍向所有窗口广播事件；当前 Renderer 做 thread 隔离，未来多窗口仍需 Main 订阅隔离。
- 本地终止 worker 不能证明外部 MCP 写操作没有副作用；仍需远端幂等键、传输层取消和结果核对。
- Renderer 当前只渲染既有 Chart Spec v1 的 bar/line/scatter；不支持交互图表、多系列或大于 100 点。
- NSIS 独立安装后的完整 E2E、真实操作系统文件对话框自动化、代码签名、自动更新和
  干净机器部署仍属于后续阶段；M6.4 已从真实 unpacked exe 完成双启动恢复，未做安装后测试。

## 下一阶段

- 等待用户明确指定下一阶段；暂不加入 heartbeat、sequence gap 自动补洞、多窗口、Trace 导出/深度调试、
  UI 深度美化、真实 Provider 扩展或自动更新。
- 每次主要修改继续运行 Desktop 专项、Python 全量、Node、P0/P1/Robustness 和 Day19 regression gate。
