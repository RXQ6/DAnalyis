# CURRENT TASK

## 当前阶段

Desktop M5：Trace Panel + Error/Retry + Product States 已完成实现与自动化验收。

下一阶段尚未定义；在收到新的阶段目标前保持当前 Desktop M1–M5 架构与回归基线。

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
- Python sidecar、安装包、代码签名、自动更新和干净机器部署仍属于后续 M6。

## 下一阶段

- 等待下一阶段范围确认；暂不加入 heartbeat、sequence gap 自动补洞、多窗口、Trace 导出/深度调试、
  UI 深度美化、真实 Provider 扩展、安装包或自动更新。
- 每次主要修改继续运行 Desktop 专项、Python 全量、Node、P0/P1/Robustness 和 Day19 regression gate。
