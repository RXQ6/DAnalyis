# CURRENT TASK

## 当前阶段

Desktop M3：Chat + File + Chart + Run State 已完成正式验收。

下一阶段为 Desktop M4：Session + Recovery + HITL UI。当前尚未开始 M4 业务实现。

桌面层继续保持零侵入边界：Electron Main 负责原生文件选择、IPC 和进程宿主；Python Runtime 是
Workflow、Dataset、Agent、Tool、Chart 和安全决策的唯一业务事实源；Renderer 只投影事件和渲染
已有 Chart Spec。

## Desktop M3 已实现能力

- Chat UI 支持输入消息、启动/取消 run、显示用户消息、Agent 最终回答、运行状态和结构化错误。
- Run State 支持 `idle`、`running`、`completed`、`failed`、`cancelled`、
  `waiting_approval` 和 `partial`。
- `OrderedRunProjector` 按 run sequence 缓冲、去重和顺序应用事件；UI 不自行推断业务终态。
- preload 新增 `selectDataset()`；Renderer 只能传可选 thread ID，不能传文件路径。
- Main 使用原生文件对话框选择单个 CSV/XLSX，并将可信路径直接交给 Python bridge。
- JSONL protocol 新增 `dataset.register`；Python supervisor 使用现有 DatasetRegistry 完成文件验证、
  摘要和 dataset ID 生成，并将 dataset ID 绑定到 thread。
- `run.start` 支持受控 `dataset_id`；worker 从 supervisor 的可信映射恢复路径并重新注册同一 ID，
  再复用现有 Workflow、ConversationRunner、Agent Loop 和 ToolRegistry。
- Chart 工具继续在 Python 中消费真实 ToolResult 并生成既有 Chart Spec。bridge 通过
  `chart_ready` 仅传 spec 与不含路径的 artifact 元数据；Renderer 只做 bar/line/scatter 展示布局。
- Runtime 失败、partial、waiting approval、cancel 和 crash 均有明确终态，不会无限 loading 或白屏。
- Renderer 模块采用构建期本地 bundle，继续保持 `contextIsolation=true`、
  `nodeIntegration=false`、`sandbox=true` 和本地 CSP。

## 验收结果

- Desktop TypeScript/IPC/Runtime/Run State/File/Chart 专项：14/14 PASS。
- Python bridge 专项：5/5 PASS。
- 隐藏 Electron BrowserWindow E2E：PASS。
- Python 全量：260/260 PASS。
- 原 Node 测试：13/13 PASS。
- P0：15/15 PASS。
- P1：20/20 PASS。
- Robustness：25/25 PASS。
- Day19 Eval Harness：60/60 PASS。
- 原 11 项 regression gate：全部 PASS。
- Day19 average / p95 / max latency：0.260s / 0.664s / 0.852s。
- Security violations：0；Contract failures：0。
- 未修改 baseline、threshold 或既有评测预期。

## 当前剩余风险

- 桌面端尚未接入 Session 列表、SessionStore 持久化/恢复和跨进程 ConversationState UI。
- 尚未实现 HITL approve/reject 产品 UI；当前仅投影 `waiting_approval`。
- BridgeModel 是最小 composition adapter，尚未接入真实模型客户端、凭证和模型级重试。
- 每个 run 独立 worker 仍有进程启动开销，supervisor 的长期 run/dataset 状态需要有界清理。
- 尚无 heartbeat、事件重放和断线后的 sequence gap 恢复。
- Main 仍向所有窗口广播事件；未来多窗口需按 thread/run 订阅隔离。
- 本地终止 worker 不能证明外部 MCP 写操作没有副作用；仍需远端幂等键、传输层取消和结果核对。
- Renderer 当前只渲染既有 Chart Spec v1 的 bar/line/scatter；不支持交互图表、多系列或大于 100 点。
- Python sidecar、安装包、代码签名、自动更新和干净机器部署仍属于后续 M6。

## 下一阶段：Desktop M4

- 不重写 Workflow、Agent Loop、ToolRegistry、DatasetRegistry、Chart、Guardrail、HITL、Session 或 Eval Harness。
- 接入现有 SessionStore、SessionStateProjector 和 PersistentApprovalManager，提供最小 Session 列表、
  会话恢复、pending approval 展示以及 approve/reject UI。
- Electron/Renderer 只做状态承载和安全投影，不复制 Session、Recovery、Guardrail 或 HITL 业务规则。
- M4 暂不包含完整 Trace 调试面板、安装包、自动更新、多窗口或多租户能力。
- 每次主要修改继续运行 Desktop 专项、Python 全量、Node、P0/P1/Robustness 和 Day19 regression gate。
