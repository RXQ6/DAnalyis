# 项目进度

更新时间：2026-09-24

## Phase 1.4 产品级桌面视觉重设计与标题栏收尾

- 在现有 Renderer 和 Runtime 合约上实施新的分析工作台：主分析画布、数据文件和 Session
  辅助导航、CSV/XLSX 与示例问题空首页、最近分析、数据概览、结构化分析摘要、Chart Card、
  可折叠对话记录，以及默认收起并改称“分析过程”的 Trace。左右区域在宽屏下可拖拽、
  键盘调整与折叠；900px 以下左侧成为抽屉，760px 以下 Trace 移至底部。设置页提供
  AI Providers、MCP Servers、Data Sources、External Tools 和 Chart / Report Providers
  的“规划中”入口，没有 API Key 输入、连接测试或真实 Provider 调用。
- 新增 Renderer presentation mapping：Session 取首条真实用户问题作为自然语言标题，
  无安全标题时显示“未命名分析”；状态、审批动作与风险、错误、Trace 事件和结构化回答
  映射为人类可读内容。普通 UI 隐藏 thread / trace / run / approval ID、sequence、
  raw JSON、tool args 和路径等内部字段。异步刷新 Session 列表时保留当前真实标题，
  防止运行中回退为“未命名分析”。Metric Card 仅显示 DatasetSummary 已有行数和字段数；
  没有从自然语言答案抽取或伪造业务 KPI / Insight。
- Chart 仅消费现有 Chart Spec v1 数据，重做标题、副标题、轴、网格、负值基线、柱线散点
  标记、键盘可达 Tooltip、图表数据表与宽图内部滚动。当前单系列 Spec 不携带系列图例
  元数据，因此没有推断或生成多系列 Legend。设计 token 统一在 Renderer CSS 中。
- 品牌资产统一从 `desktop/assets/brand/mark.svg` 派生应用内标记和 Windows `icon.ico`；
  BrowserWindow、electron-builder 的窗口/安装器/卸载器配置指向同一资产入口。当前图形
  在资产说明中明确标为工作占位，后续审核定稿后替换。窗口改为 38px 可拖动标题栏，
  保留系统最小化、最大化与关闭区，移除可见通用英文标题和默认菜单；新增简洁图标按钮。
- 仅调整 Desktop Main 窗口外观、Renderer、静态资产复制和 UI 测试/打包烟测；Python
  Runtime、IPC/Event contract、Session/HITL/Dataset/Chart 业务事实源与评测目标未改。
- 2026-09-24 实测：TypeScript build、Desktop 30/30、Electron smoke、开发态与打包资源态
  E2E 各 9 步、最终 Windows unpacked exe 双启动 smoke、packaged sidecar、Python 全量
  261/261、Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、Day19 60/60、
  Regression Gate 11/11 均通过；security violations=0、contract failures=0。NSIS
  installer 重新构建成功，SHA256
  `AE6C43AEB007C33BA0F41323432637B161DCCBF1829E5B45E696D0E8F88DB54D`。
  Python 全量初跑所用的精简 sidecar 缺少测试专用 MCP SDK；按项目固定的
  `requirements-mcp.txt` 在临时测试目录补齐依赖后 261/261 通过，未更改业务代码。
- 剩余风险：工作占位图形仍需品牌定稿；新 NSIS installer 未单独安装验收；Chart Spec v1
  仍仅支持单系列 bar / line / scatter 与最多 100 点，Runtime 未提供结构化 Insight；
  原生文件选择框由 E2E 提供确定性选择结果，干净机器与多显示器缩放仍待后续人工检查。

## Folio 启发的桌面工作区布局与 HTML 启动提示

- 在保留既有未提交改动的基础上，重整 Renderer 的视觉层级：数据文件入口置于左侧首位，
  最近 Session 位于其下；中间以分析对话为主，空态提供明确的文件选择入口；Trace 默认
  折叠为窄侧栏，700px 以下移到主区下方，520px 时侧栏置顶。统一使用中性色工作台、
  细分隔线、克制的状态色与紧凑按钮。保留原有 DOM ID、事件绑定、Runtime 状态投影及
  Renderer→Preload→Main→Python 链路，没有向前端加入分析计算。
- 直接打开源 HTML 或构建后的 HTML 时，页面明确提示必须启动 Electron 应用；没有
  preload bridge 的浏览器页面不再展示看似可操作却无法调用 IPC 的假界面。Electron
  环境仍显示完整应用。Electron smoke 新增无 preload 的静态 HTML 回归检查。
- 真实 Electron 窗口检查 1600/1200/900/700/520px：五档均无页面横向溢出，
  数据文件按钮、主区及 Composer 可见。TypeScript build、Desktop 27/27、Electron
  smoke、开发态与打包资源态 E2E 各 8/8 PASS；Node 13/13、Python 261/261、P0
  15/15、P1 20/20、Robustness 25/25、Day19 60/60、Regression Gate 11/11 PASS，
  security violations=0、contract failures=0。新 Renderer 的独立 Windows unpacked
  产物双启动 smoke PASS：真实 CSV run 完成，Session 可在重启后恢复。
- 初次 NSIS 资源下载超时，重试后成功生成独立的新 installer：
  `desktop/release/folio-polish/Data Analysis Agent Setup 0.1.0.exe`，SHA256
  `379DA192257DA58294F634BF93990A657A696AD5EC5393048BF50F1F987B3585`。
  同批产物 `desktop/release/folio-polish/win-unpacked/Data Analysis Agent.exe`
  再次双启动 smoke PASS；原先安装目录未被覆盖。新版 NSIS 尚未实际安装验证，
  原生文件选择框的人工可见检查也未在本轮完成。

## Phase 1.4 Visual Design Polish：Renderer 展示层完成

- 保留 Phase 1.1–1.3 未提交改动，仅在 Renderer 调整 App Bar、Session/Dataset Sidebar、
  Chat/Analysis、Chart Card、Trace Timeline、Approval/Error/Product State 与底部 Composer。
  Session 摘要优先、thread ID 次级显示、当前 Session 选中态和状态点均只投影既有字段；
  Dataset 展示已有 filename/format/rowCount/columnCount。Chart 类型标签只来自 Chart Spec，
  不解析回答生成指标、不重算图表或改变既有事件绑定。
- 统一字体层级、4/8/12/16/24/32px 间距尺度、6px 控件/12px 卡片圆角、浅边框、
  单一操作强调色和 Runtime 状态语义色。按钮 hover/focus/disabled/busy、长文本换行、
  Chart 内滚动与折叠 Trace 沿用既有行为。保留全部原有 DOM ID、IPC/Event contract 和
  Renderer→Preload→Main→Python 调用链。
- 真实 Electron 几何/截图检查 1600/1200/900/700/520px：页面均无横向溢出；
  700px Trace 下移，520px Sidebar 置顶且文件按钮、主区、Composer 仍可见。临时布局
  检查窗口未注册 Runtime IPC，其 failed 画面仅用于观察布局，不作为业务链路结果。
- TypeScript build PASS；Desktop 单元 27/27、Electron smoke、开发态与打包资源态
  E2E 各 8/8 PASS；
  最新 Renderer 重新构建的 Windows unpacked exe 双启动 smoke PASS，真实 CSV run 为
  completed 且 Session 重启恢复。Python 全量 261/261、Node 13/13、P0 15/15、
  P1 20/20、Robustness 25/25、Day19 60/60、Regression Gate 11/11 全 PASS；
  security violations=0、contract failures=0。未修改 Python Runtime 或业务语义。
- 本轮未重新构建 NSIS installer；既有已安装版本仍为 Phase 1.3。现有 Chart Spec
  未提供结构化 evidence/metrics/legend，Renderer 不补造这些内容；原生文件对话框
  仍由系统提供，E2E 注入确定性选择结果而非自动点击系统对话框。

## UI Product Polish 最终安装验收（已完成，用户人工确认）

- 2026-09-23，用户在打开最终安装版进行人工验收后明确确认“都检查通过了”。
  据此记录剩余人工检查项通过，Phase 1 UI/UX Product Polish 最终收尾完成。
  人工结论来源为用户确认，不记作 Agent 独立完成了此前受阻的目视检查。

- 使用最新 Renderer 重新构建 Windows NSIS installer：
  `desktop/release/Data Analysis Agent Setup 0.1.0.exe`，SHA256
  `59B68B68F17A35883142099C4C2164CFEE68A8629500EDB6E89C8BD48F91A356`。
  旧 installer 另存为 `Data Analysis Agent Setup 0.1.0-pre-phase1.3.exe`，未丢失
  历史产物。
- 最终 installer 静默安装到独立目录
  `desktop/release/phase1.3-final-installed`，退出码 0。安装目录含真实 exe、
  `resources/app.asar` 和 `resources/python-runtime/python.exe`；可见窗口的
  Renderer URL 指向该安装目录，不是 dev/unpacked。
- 可见窗口发现 Recent sessions 的长摘要会把 Dataset 入口推到滚动区以下；
  仅在 Renderer 将 Session 列表设为独立滚动、将 Dataset 固定在侧栏底部，
  并分行/截断显示 thread ID、更新时间与摘要。重建并重装后 Empty 页布局和
  Dataset 按钮可见。真实 Windows 打开对话框从该按钮弹出，CSV/XLSX 筛选器正确，
  测试 CSV 路径已填入；确认“打开”前目标窗口被最小化且检测到其他用户输入，
  工具恢复失败，当时未宣称真实文件确认后的人工链路通过；后续人工补验由用户
  明确确认通过。
- 安装版真实 exe 双启动自动烟测 PASS：CSV 分析完成、6 条 Runtime Events、
  重启恢复原 thread 与 4 条消息；证据位于
  `desktop/release/phase1.3-final-installed-smoke-17pfIK`。Desktop 27/27、
  Electron smoke、开发态及打包资源态 E2E 各 8/8、packaged Python sidecar、
  Python 261/261、Node 13/13、Day19 60/60 和 Regression Gate 11/11 全 PASS；
  P0/P1/Robustness 为 15/15、20/20、25/25，security violation 与
  contract failure 均为 0。
- 用户确认安装版 Chart Card、长 Trace/长文本滚动、Partial/Stale/Failed/Completed、
  HITL Approval Card、Error/Retry、700px/520px 缩放和真实文件选择链路均通过
  人工检查。本次仅更新进度文档，沿用最近一次回归结果，没有修改代码或重复运行测试。
  Python Runtime、IPC/Event contract 与业务逻辑保持原样；installer
  Authenticode 状态仍为 NotSigned。下一阶段等待用户指定。

## Phase 1.3 UI/UX Product Polish：视觉与交互细节统一

- 仅调整 Renderer 展示层：统一 Segoe UI/system 字体、13px 基准字号、8/12/16px
  间距、10px 卡片/6px 控件圆角、边框和浅色卡片层级。Sidebar、Header、Chat、
  Chart、Trace、Approval、Error 沿用同一视觉变量，不改变 DOM ID、事件绑定或协议。
- empty、loading、running、partial、stale、waiting_approval、completed、failed、
  cancelled 使用一致的状态卡样式；蓝色表示处理中/审批，绿色表示完成，琥珀色表示
  部分结果/过期，红色表示失败。状态说明仍直接来自既有 Product State 映射。
- 按钮统一 hover、active、disabled、focus 样式；文件选择、Send、Stop、审批决策
  和 Retry 的原有异步按钮增加文字与 aria-busy 加载反馈，仅改变展示。
- 长消息、错误、Session 摘要和 Trace 文本可换行；Chart SVG 保持既有 Chart Spec
  渲染，窄列内水平滚动而不撑宽整页。取消固定 600px 页面最小宽度，并在 760px/
  640px 断点重排 Trace、Sidebar、Header 和输入区；无复杂动画。
- Electron smoke 新增图表卡内滚动与页面无横向溢出断言；开发态/打包资源态
  E2E 各新增 700px/520px 真实窗口缩放检查。TypeScript build、Desktop 27/27、
  Electron smoke、两种 E2E 各 8/8、重建 unpacked 真实 exe 双启动 smoke、
  Python 261/261、Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、
  Day19 Eval Harness 60/60、Regression Gate 11/11 全 PASS；security violation 与
  contract failure 均为 0。
- 未修改 Python Runtime、IPC/Event contract、Session/HITL/Dataset/Chart 业务逻辑。
  本轮未生成新 NSIS installer；现有 installer 仍是 Phase 1 前 UI。真实原生文件
  对话框的人手操作、干净机器与不同显示缩放下的人工视觉检查尚未在本轮验收。

## Phase 1.2 UI/UX Product Polish：Chart / Trace / HITL / 状态卡

- Chart Renderer 在原 Chart Spec SVG 外增加 `<figure>` Chart Card 和标题；只使用既有
  `chartType`、`title`、`data.values` 作 SVG 绘制，不新增统计、分组或业务数据计算。
- Trace Panel 将现有按 sequence 的脱敏 `TraceEntry` 渲染为可折叠时间线，显示 sequence、
  category、受控 label、status 与 error code；不渲染 arguments、metadata、文件路径或错误正文。
- waiting_approval 独立卡展示 action type、risk summary、approval ID、expires_at 与原
  Approve/Reject 按钮；不显示 action hash 或原始参数，不在 Renderer 判断审批有效性。
- Error Card 根据现有状态视觉区分 failed、partial、stale；partial 保留回答/Chart，stale
  保留现有 Refresh，Retry 的显隐和安全边界仍沿用原逻辑。所有既有 DOM ID 与绑定不变。
- 新增 Electron smoke/E2E 断言 Chart Card、Trace Timeline 与 partial/stale/error 视觉投影。
  首次新增测试将既有 `file_not_found` 错误误判为 failed，已只把断言修正为原有 stale 映射。
- TypeScript build、Desktop 单元 27/27、原 Electron smoke、开发态与打包资源态 E2E 各
  7/7、重建 unpacked 真实 exe 双启动 smoke、Python 261/261、Node 13/13、P0 15/15、
  P1 20/20、Robustness 25/25、Day19 60/60、Regression Gate 11/11 全 PASS。
  未改 Python Runtime、IPC/Event contract、Session/HITL/Dataset 业务逻辑或评测标准。
- 本轮仍只重建 unpacked；现有 NSIS installer 为 Phase 1 前布局。原生文件对话框实际
  人工交互、干净机器/安装态新 UI、窄窗口视觉检查和更深层样式仍待后续阶段。

## Phase 1 UI/UX Product Polish：第一轮最小布局

- Renderer 页面重排为顶部 Session/Dataset/Run Status、左侧 Session/Dataset Sidebar、
  中间 Chat/Analysis/Chart 可滚动区域与底部固定输入区；原 Trace Panel 保留在右侧。
  新增外部 `styles.css` 并由静态资源构建脚本复制，未放宽 CSP。
- 保留全部原有按钮、DOM ID、事件绑定与 Renderer → Preload → Main → Python 调用链。
  顶栏 Session/Dataset 只展示 Runtime 已返回的当前 thread ID 和 Dataset 摘要；恢复旧 Session
  后仍按原逻辑清空当前 Dataset，不伪造文件已重新绑定。
- Electron E2E 新增样式加载、布局位置、固定输入区和顶栏上下文断言。TypeScript build、
  Desktop 27/27、原 Electron smoke、开发态及打包资源态 E2E 各 7/7、重新构建的真实
  unpacked exe 双启动 smoke 均 PASS；Python 261/261、Node 13/13、P0 15/15、
  P1 20/20、Robustness 25/25、Day19 60/60、Regression Gate 11/11 均 PASS。
- 本轮只重建 Windows unpacked 产物用于 UI 回归，未重新生成 NSIS installer；此前
  M6.5 安装包仍是布局改造前版本。原生文件对话框的实际人工交互、窄窗口视觉 QA、
  深度样式和完整响应式体验留待后续轮次。

## Desktop M6.5 Release Gate + Release Report

- Required Release Gate 全部 PASS，Desktop M6 完成。统一证据和产物 SHA256 见
  `docs/Desktop-M6.5-Release-Report.md`。版本为 0.1.0；未修改 Python Runtime 业务语义、
  P0/P1 逻辑、Day19 baseline 或既有评测阈值。
- TypeScript build PASS；Desktop 27/27、原 Electron smoke、开发态 E2E 7/7、
  打包资源态 E2E 7/7、unpacked 真实 exe 双启动 smoke 与 packaged sidecar 全部 PASS。
- NSIS 安装包实际以静默模式安装到独立目录 `desktop/release/m6.5-installed`，退出码 0。
  从该目录的真实安装后 exe 两次启动：首轮 CSV 分析得到销售额 1580、6 条 Runtime Events、
  completed；重启后恢复同一 thread、4 条消息、6 条 Trace，未启动新 run。
  安装态证据：`desktop/release/m6.5-installed-smoke-xR3Qia/{first,resume}.json`。
- Python 全量 261/261、Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、
  Day19 Eval Harness 60/60、Regression Gate 11/11 全 PASS；security violations=0、
  contract failures=0。
- 本轮仅扩展 packaged smoke 脚本接受安装后 exe 路径，并修正标签校验；一次标签校验失败发生在
  应用启动前，修复后两种真实 exe smoke 均重跑通过。剩余风险：原生文件选择框的实际交互
  未自动化、干净机器/升级卸载未验证、installer 与 exe 未签名。上述不计入本轮 required gate。

## Desktop M6.4 Packaged Smoke

- 从 electron-builder 重新生成的真实 Windows unpacked 产物
  `desktop/release/win-unpacked/Data Analysis Agent.exe` 启动两次独立进程；同时重新生成
  `desktop/release/Data Analysis Agent Setup 0.1.0.exe`，未使用 dev 模式，也未执行 NSIS 安装。
- 首次进程确认 `app.isPackaged=true`、Main 启动、`app.asar` Renderer 加载、Preload API 可用；
  通过 Renderer 文件按钮、Preload、`files:select` IPC 和 Python DatasetRegistry 注册 CSV，页面显示
  `sales.csv · 5 rows · 4 columns`。Send 后观察到 running、6 条有序 Runtime Events 与
  completed，真实销售额求和回答为 1580；Python SessionStore 列表包含本次 thread。
- 关闭首个进程后再次启动同一 exe，使用同一 Electron 标准 userData
  `C:\Users\29486\AppData\Roaming\data-analysis-agent-desktop`；Session List 与 Resume 恢复原
  `thread_ae90bf36e90d45a88bfe0bd2b3a1d718`、4 条持久化消息、6 条 Trace 和原 trace ID，
  恢复未产生新 run。两次验收的 PID 分别为 58052、54616；原始机器可读结果在
  `desktop/release/m6.4-smoke-y1aRT9/first.json` 与 `resume.json`。
- 验收脚本仅向系统文件对话框注入确定性 CSV 路径，不 mock Renderer、Preload、Main IPC、
  Python Bridge、Runtime Event 或 SessionStore；因此真实原生对话框的人工点击仍未自动覆盖。
  第一次受限沙箱运行因标准 AppData 缓存目录拒绝访问失败，正常桌面权限下重跑通过；
  未因测试环境限制修改产品路径或 Python 业务语义。
- Desktop 单元 27/27、原 Electron smoke、M6.3 开发态 7 场景、打包资源态 7 场景、
  packaged sidecar 分析 run、M6.4 真实 exe 双启动 smoke 全部 PASS；Python 全量 261/261、
  Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、Day19 60/60、
  11 项 Regression Gate 全 PASS。剩余 NSIS 独立安装、干净机器、真实文件对话框自动化、
  代码签名及分发许可清单待后续阶段；本轮停止，不自动进入 M6.5。

## Desktop M6.3 Electron E2E

- 新增真实 Electron BrowserWindow UI 端到端测试，在开发资源及 M6.2 unpacked
  `app.asar` Renderer/Preload + 私有 Python/Node 资源两种模式各完成 7 个分步场景。
  通过实际按钮点击与 Renderer → Preload → Main IPC → Python Bridge 链路验证：
  启动、CSV/XLSX 选择、Send、running/completed、Runtime Events 与 Trace 排序/折叠、
  Stop/Cancel、Session List/Resume、HITL Reject/Approve、真实文件错误与 Retry。
- 仅系统文件对话框的选择结果注入确定性测试路径；未 mock 核心 IPC、Runtime Event、
  SessionStore 或 Python HITL。失败输出步骤名、异常及 UI state/error/trace 摘要。
- 首次完整复跑发现测试入口把 `dist/tests` 误作为 Main 路径基准，导致开发态 Bridge
  定位失败；只修正测试目录参数后，开发态与打包资源态两轮 E2E 全部通过。
- Desktop 单元 27/27、原 Electron smoke、新 E2E 两种模式 PASS；Python 全量 261/261、
  Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、Day19 60/60、
  11 项 Regression Gate 全 PASS。未改 Python 业务语义或评测标准。
- 剩余：真实 OS 文件选择框未被自动点击；打包资源 E2E 由测试 Electron 宿主加载，
  NSIS 安装后的完整应用未在干净机器验证；签名、图标、许可清单仍待后续阶段。
  本阶段停止，不自动进入 M6.4。

## Desktop M6.2 Packaged Python Runtime

- Windows sidecar 构建从构建机 Python 3.12 复制私有解释器、标准库、cryptography 等必要依赖，
  同时分发原有 Python 项目模块、JSONL Bridge、Node 数据桥 JS 与私有 Node 可执行文件。
  electron-builder `extraResources` 将其放在 unpacked/installer 的 resources，不进入 app.asar。
- packaged Main 通过 `process.resourcesPath` 定位私有 Python 和 Bridge，显式设置 PYTHONHOME、
  PYTHONPATH、Node PATH 前缀及标准 userData/runtime。开发态保持原仓库相对路径；产物不引用
  构建机的 Python/Node 绝对路径。
- 真 Electron unpacked 启动烟测经 Preload/Main/Python 完成真实 chat run，退出码 0。
  packaged sidecar 另完成 CSV 注册与真实分析 run，销售额求和 1580；8 条 stdout 帧均为 JSONL
  协议，stderr 无协议帧。缺失私有 Python 时专项测试验证结构化错误。
- Desktop 单元 27/27、Electron E2E PASS、Python 全量 261/261、Node 13/13、P0 15/15、
  P1 20/20、Robustness 25/25、Day19 60/60、11 项 Regression Gate 全 PASS。
- 剩余：NSIS 独立安装/干净机器验证、签名、图标、第三方二进制许可清单与更广泛的 packaged E2E。
  本阶段停止，不自动进入 M6.3。

## Desktop M6.1 Packaging 基础

- electron-builder 26.15.3 已配置 Windows x64 NSIS；`npm run pack:win` 同时生成
  `desktop/release/win-unpacked` 与 `Data Analysis Agent Setup 0.1.0.exe`。
- Main、Preload、Renderer 已验证进入 app.asar，Windows unpacked 产物在隐藏窗口烟测中
  成功加载 preload API 与 Renderer，进程退出码为 0。安装包已生成，未执行独立安装验证。
- 开发态 Bridge 使用仓库相对路径，打包态使用 `process.resourcesPath`；运行数据位于
  Electron 标准 `app.getPath("userData")/runtime`。Python sidecar 尚未打包，安装包当前只
  保证 Electron 壳可启动；业务分析在打包态会显示 Runtime 不可用。
- 安全窗口配置仍为 contextIsolation=true、nodeIntegration=false、sandbox=true。
  未修改 Python Runtime 业务代码或评测标准。
- Desktop 单元 25/25、Electron E2E PASS；Python 全量 261/261、Node 13/13、P0 15/15、
  P1 20/20、Robustness 25/25、Day19 Eval Harness 60/60、11 项 Regression Gate 全 PASS。
- 剩余：Python sidecar、独立安装后验证、代码签名与自定义图标。M6.2 等待另行启动。

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
- 完成 MCP Tools 最小协议优化：新增 `MCPHost` 管理一对一 Client 生命周期、显式工具 allowlist 与 close；Adapter 自身也改为默认拒绝隐式全量授权。`MCPClient.list_tools(cursor)` 支持分页，Mock Client 与未来真实 SDK facade 使用同一独立接口；Resources / Prompts 仅保留未接线的 Protocol 扩展位。
- MCP Tool 映射支持标准无参数 object schema、最长 128 字符及点号名称、本地名称归一化碰撞检查、可选 `outputSchema` 和 annotations。调用结果增加 `resultType`、content block 与 structuredContent contract 校验；协议错误、本地 schema 不兼容、未知工具、远端异常、timeout 和暂不支持的 input-required 均返回独立结构化错误，timeout 同时调用 Client 的可选取消钩子。
- MCP 专项扩充为 22/22，覆盖分页、Host 生命周期、权限默认关闭、标准无参 schema、outputSchema、content block、input-required、server unavailable、schema 不兼容、late-binding 和多工具 handler 隔离。完成 Python 181/181、Node 13/13、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8 全量回归，未修改 Agent Loop、ToolRegistry、ToolResult 或其他业务层逻辑。
- 2026-09-21 MCP 协议优化复评再次通过：专项 22/22；额外使用独立 `AlternateClient` 完成 Host 注册、分页 Client 合约、Agent Loop 调用和完整 trace，确认 Client 可替换且 `local_echo` 与 `mcp_alt__echo` 可同时工作。复评结果保持 Python 181/181、Node 13/13、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8。

## Day18.1 官方 MCP SDK stdio 与请求取消

- 新增可选 `MCPStdioClient`，使用官方 MCP Python SDK 2.2.0 的 `Client` 与 `StdioServerParameters` 启动真实 stdio Server；在专用后台事件循环中保持单一 SDK Client 生命周期，并把 SDK typed result 转换成现有同步 `MCPClient` 合约。MCPHost、Adapter、ToolRegistry、ToolResult 和 Agent Loop 调用链保持不变。
- `MCPStdioClient` 跟踪当前 SDK asyncio task。Adapter timeout 或 facade 自身等待超时时调用 `cancel_pending()`，线程安全地取消当前 task，由官方 SDK 向 stdio Server 传播 cancellation；取消后 Client 连接仍可继续处理后续工具调用。
- 新增官方 SDK 测试 Server，提供 `echo` 与可取消的 `slow_echo`；真实集成测试验证 list/call、Adapter 复用、Agent Loop trace、structuredContent，以及 Server 捕获取消并写入 marker。保留全部 MockMCPClient / MockMCPServer 测试。
- MCP 专项 24/24、Python 183/183、Node 13/13、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8 全部通过。未实现 Streamable HTTP、Resources、Prompts、动态通知或复杂 JSON Schema。
- 2026-09-21 Day18.1 专项复验通过：官方 SDK stdio Client/Server 可连接，真实 `tools/list` 动态发现 `echo` / `slow_echo`，现有 Adapter 原样完成 ToolDefinition 映射、ToolResult 转换及 Agent trace。timeout 后 Server 捕获 `CancelledError` 并写入 marker，证明底层请求已停止；取消后同一连接仍可调用。额外让真实 stdio Server 在工具执行中以退出码 17 终止，Adapter 返回可恢复的 `mcp_server_unavailable`，Agent 记录失败 trace 后正常输出最终答案。专项保持 24/24，全量保持 Python 183/183、Node 13/13、P0 15/15、P1 20/20、robustness 25/25、Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8。

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

## Day19.1 统一 Eval Harness

- 新增独立 `eval_harness/`，定义统一 `EvalCase`、`EvalResult`、`EvalSuite` 和 `EvalRunner`；评测层不进入 Agent、Workflow、ToolRegistry 或其他业务调用链。
- P0、P1、Robustness 通过兼容适配器直接复用原案例定义、执行函数和确定性断言；原 `tests/eval_agent.py`、`tests/eval_p1.py`、`tests/robustness_eval.py` 均保留且仍可独立执行。
- 每个统一结果记录 `case_id`、`category`、`passed`、`failure_reason`、`latency`、`answer`、`trace_summary`、suite 与兼容元数据；P0/Robustness 从现有 audit 提取工具和轮次摘要，P1 对旧执行器未暴露的 trace 明确标记不可用，不编造过程。
- EvalRunner 隔离单案例执行异常、继续收集后续结果，并按 suite 汇总 PASS/FAIL；P0 与 Robustness 原百分比、时延、成本和 process-check 门禁原样保留，P1 继续要求全部案例通过。
- 新增 `tests/run_day19_eval.py` 统一入口和 `tests/results/day19-eval-harness.json` 可审计报告；暂未接入 LLM Judge，也未迁移其他专项评测。
- Day19.1 统一评测通过 60/60：P0 15/15、P1 20/20、Robustness 25/25，全部原门禁 PASS。兼容旧入口复测保持 P0 15/15、P1 20/20、Robustness 25/25；Python 全量 189/189、Node 13/13 通过。

## Day19.2 过程评测层

- 新增确定性的 `RouteEvaluator`、`ToolEvaluator`、`TraceEvaluator`、`ContractEvaluator`，由 EvalCase 通过 evaluator 名称和显式 expectations 选择；EvalRunner 统一调用、合并 evaluator 结果并参与案例 PASS/FAIL，不引入 LLM Judge。
- EvalResult 增加 `route_correct`、`tool_correct`、`contract_valid`、`trace_available`、`tool_calls`、`loop_iterations`、`retry_count`、`failure_type` 与逐 evaluator 审计明细；统一报告增加过程指标汇总。
- RouteEvaluator 支持 `analysis`、`chat`、`calc`、`memory`、`memory_recall`，缺失、非法或不匹配 route 归类 `ROUTING_ERROR`。当前 P0/P1/Robustness 不暴露 Workflow route，因此没有把分析工具名伪装成 route，RouteEvaluator 由专项用例完成验收。
- ToolEvaluator 检查预期工具、allowlist、同参数重复调用和执行错误，分别归类 `TOOL_SELECTION_ERROR`、`SECURITY_VIOLATION`、`TOOL_EXECUTION_ERROR`；P0/Robustness 使用完整 audit trace 接入。
- TraceEvaluator 对完整 trace 统计工具次数、循环轮次和 retry，检查重复调用及 max_iter；P1 旧执行器未暴露完整 trace 时输出 `trace_available=false`，过程计数保持 null，不影响原 P1 门禁且不编造过程。
- ContractEvaluator 支持结构化输出、现有 ToolResult 和 SkillInvocation 的确定性必填字段/类型校验，失败统一为 `CONTRACT_ERROR`；P0/Robustness 已接入结构化输出 contract。
- 建立稳定 failure taxonomy：`ROUTING_ERROR`、`TOOL_SELECTION_ERROR`、`TOOL_EXECUTION_ERROR`、`MEMORY_ERROR`、`CONTEXT_ERROR`、`CONTRACT_ERROR`、`ANSWER_ERROR`、`TIMEOUT`、`SECURITY_VIOLATION`，并保留 `TRACE_ERROR`、`HARNESS_ERROR` 扩展分类和安全优先级。
- Day19.2 过程层专项 17/17，通过统一 Harness 60/60（P0 15/15、P1 20/20、Robustness 25/25），原门禁全部 PASS；Python 全量 206/206、Node 13/13，旧 P0/P1/Robustness 入口分别保持 15/15、20/20、25/25；Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8。

## Day19.3 Metrics、Regression Gate 与 Unified Report

- 新增 `MetricValue`、`EvalMetrics` 和 `MetricsCollector`，统一记录 pass rate、accuracy、bad-case recognition、robustness、平均/P95/最大时延、工具调用、循环轮次、retry、timeout、安全违规、contract 失败、cost 和 token；每项携带 available、覆盖案例数、单位和不可用原因，不用 0 替代缺失值。
- 固化版本化 baseline `eval_harness/baselines/day19-stable.json`，保存稳定版本的 P0/P1/Robustness 通过率、延迟和成本及显式容差；每次运行只读取 baseline 并输出 current/baseline/delta，不自动覆盖稳定基线。
- 新增 RegressionGate：P0 必须 100%，P1 和 Robustness 不得低于 baseline，security violation 与 contract failure 必须为 0；平均/P95/最大 latency 以及平均/最大 cost 必须位于 baseline 容差内；同时继续要求原 P0/P1/Robustness gates 全部通过。required metric 不可用时明确 FAIL。
- 新增 UnifiedReportBuilder，同时生成 `tests/results/day19-unified-report.json` 和 `.md`，包含总体状态、category 通过率、过程指标、latency/cost/token、baseline delta、failure taxonomy、逐 gate PASS/FAIL 原因和当前风险。
- 当前统一报告 PASS 60/60；过程覆盖保持 Tool 40/40、Contract 40/40、trace available 40、unavailable 20，token 明确 unavailable，cost 为 60/60 实际观测值。11 项 regression gate 全部 PASS，未降低旧 threshold。
- Day19.3 专项 11/11；Python 全量 217/217、Node 13/13；旧 P0/P1/Robustness 保持 15/15、20/20、25/25；Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8。

## Day20.1 统一 Observability / Trace

- 新增统一 `TraceEvent` 与线程安全 `TraceCollector`；每个 Workflow 请求或独立 AgentLoop
  请求生成一个 `trace_id`，事件包含 event type、component、name、status、latency、
  error code、脱敏 metadata、sequence 和 UTC timestamp。
- 在不改变业务控制流的前提下接入 `request_started`、`route_selected`、`skill_triggered`、
  `tool_called`、`tool_completed`、`mcp_called`、`subagent_started`、`subagent_completed`、
  `contract_checked`、`error` 和 `request_completed`。原 ToolResult 与 execution_trace
  合约保持不变。
- Trace metadata 不保存问题原文、messages、完整 ToolResult、CSV 内容、MCP 响应或
  Sub-agent evidence；Collector 对敏感键脱敏，并限制字符串、集合、对象深度与事件总数。
- Day19 evaluator registry 新增可选 `ObservabilityEvaluator`，不改变原 P0/P1/Robustness
  cases、expectations、baseline 或 gate。
- Day20.1 专项 6/6、Python 全量 223/223、Node 13/13、P0 15/15、P1 20/20、
  Robustness 25/25、Day19 60/60 及 11 项 regression gate 全部通过；Context Compression
  9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8。
- 并行回归时 Day19 曾因资源竞争出现一次 max latency gate 抖动；未修改 baseline 或容差，
  最终无并发负载顺序复跑为 max 0.830s，小于 1.878s 上限并通过。

## Day20.2 确定性 Guardrails

- 新增统一 `GuardrailDecision`、`ToolGuardrailPolicy` 和 `DeterministicGuardrail`，固定返回
  `allow`、`block` 或 `needs_approval`，核心判断不使用 LLM。
- Guardrail 接在 ToolRegistry 参数校验之后、Handler 之前；本地工具、MCP 工具和
  Sub-agent 委派共用同一闸口。非 allow 决策不会调用底层 Handler、远端 MCP Client 或
  Sub-agent Runner。
- 读取数据、基础分析、图表、MCP 读取和只读 Sub-agent 继续 allow；修改原始数据、任意
  Python/shell 和未知高风险 action block；显式标记的 MCP 外部写操作返回包含 approval ID
  与 action hash 的结构化 pending 状态。
- 所有决策写入现有 TraceCollector 的 `guardrail_decision` 事件；Day19 evaluator registry
  新增可选 `GuardrailEvaluator`，原 cases、baseline、threshold 和 regression gate 未修改。
- Day20.2 专项 7/7、Python 全量 230/230、Node 13/13、P0 15/15、P1 20/20、
  Robustness 25/25、Day19 60/60 与原 11 项 regression gate 全部通过；Context Compression
  9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8；
  最终 Day19 max latency 1.424s，低于 1.878s 上限。

## Day20.3 HITL + Approval Resume

- 新增 `ApprovalRequest`、`ApprovalDecision`、`ApprovalResolution` 与线程安全的
  `ApprovalManager`。公开 pending 仅包含 approval ID、action hash、工具/动作类型、
  风险与有效期，不包含原始参数；待执行参数只保存在进程内私有记录中。
- `needs_approval` 后进入 pending；approve、reject、expire 均校验 approval ID 与 action
  hash。hash 不匹配会使原审批终态 rejected；approved 记录在执行前即一次性消费，重放返回
  `approval_already_consumed`；reject、expire 和不匹配均不会执行 Handler。
- ToolRegistry 提供 `resolve_approval()`，approve 后只从私有记录恢复原 tool、原 arguments、
  原 context，不接受调用方替换参数；继续复用既有 Handler、ToolResult、MCP 与 Trace 路径。
  AgentLoop 仅增加 `resume_approval()` 程序接口，并原位更新 pending observation，不新增第二个
  逻辑工具调用。
- 现有 TraceCollector 新增 `approval_requested`、`approval_decided`、`approval_resumed`；三类
  事件携带一致的 approval ID/action hash，且不保存原始参数。Day19 evaluator registry 新增
  可选 `HITLEvaluator`，检查状态、身份连续性以及 reject/expire 后没有底层执行。
- Day20.3 专项 8/8、Day20.2 联合专项 15/15、Python 全量 238/238、Node 13/13、P0
  15/15、P1 20/20、Robustness 25/25、Day19 60/60 与原 11 项 regression gate 全部通过；
  Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件
  5/5、历史对话 8/8。最终 Day19 max latency 0.826s，低于 1.878s 上限。

## Day21.1 SQLite SessionStore

- 新增独立 `session/` 包，提供 `SessionRecord` 与 `SQLiteSessionStore`；默认使用 `:memory:`，
  传入文件路径时规范化为绝对路径并支持关闭后由另一个 Python 进程继续读取。
- 完成 `create_session`、`get_session`、`append_message`、`get_messages`、`append_event`、
  `get_events` 六个通用原语；没有增加业务型 `resume()`，也没有把 Session 注入 Memory、
  TraceCollector、Context Compression、Workflow 或 Agent Loop。
- SQLite 仅包含 `sessions`、`session_messages`、`session_events` 三张业务表。message/event
  使用独立的 thread 内 sequence，在 `BEGIN IMMEDIATE` 事务内分配；读取固定按 sequence 升序，
  并支持 `after_sequence` 与 `limit`。
- 所有存储层时间由服务端生成 UTC ISO 8601；payload 必须是 JSON mapping，写入时保存快照。
  event type 保持通用，专项测试已覆盖 Guardrail、approval、tool、MCP 和 validated result 类型。
- Day21.1 专项 10/10、Python 全量 248/248、Node 13/13、P0 15/15、P1 20/20、
  Robustness 25/25、Day19 60/60 与原 11 项 regression gate 全部通过；Context Compression
  9/9、Historical Summary 8/8、多步语义 3/3、图表 5/5、多文件 5/5、历史对话 8/8。
  最终 Day19 max latency 1.382s，低于 1.878s 上限。

## Day21.2 会话恢复与 HITL 跨进程恢复

- 新增纯 `SessionStateProjector`，由调用方传入 `get_messages()`、`get_events()` 的结果与
  DatasetRegistry，恢复 thread 对应 ConversationState，并分类 Guardrail、approval、tool、
  MCP、validated result 与 trace ID；没有增加业务型万能 resume。
- Session events 表增加私有 approval 列；公开 event JSON 不含动作参数，原 arguments 使用
  Fernet 密文保存。新增 `requirements-session.txt`，跨进程必须由调用方提供同一密钥。
- 新增 `PersistentApprovalManager` 与 SQLite approval repository。approve/reject/expire/hash
  mismatch 使用 `BEGIN IMMEDIATE` 串行决策，终态清除密文；approved 在执行前消费，重放失败。
- 重启后重新绑定当前 ToolRegistry 中同名且 Guardrail policy 一致的 ToolDefinition；审批执行
  创建新 trace ID，同时继续沿用同一 thread ID，并把 tool/MCP/approval resume 摘要写回 Session。
- Day19 evaluator registry 新增可选 SessionEvaluator，不修改原 suite、baseline 或 gate。
- Day21.2 专项 7/7、相关联合专项 25/25、Python 全量 255/255、Node 13/13、P0 15/15、
  P1 20/20、Robustness 25/25、Day19 60/60 与原 11 项 regression gate 全部通过；最终
  Day19 max latency 1.152s，低于 1.878s 上限。

## Day21.3 端到端整合 Demo

- 新增应用层 `demo/Day21Demo`，不增加执行核心。Happy Path 在一个 thread 内依次经过
  Workflow/Router、data-diagnosis Skill、Agent Loop、本地 ToolRegistry、Memory recall、
  Context Compression、只读 Sub-agent、Observability 与 Session 持久化。
- HITL Demo 通过真实 MCP adapter 创建外部写 pending，关闭旧 Store 后用同一 SQLite 文件、
  thread ID 和外部密钥重建 ApprovalManager/Registry；approve 使用新 trace 执行原动作。
- Demo 同时暴露 reject、expire、action hash mismatch 和 replay；这些路径均未调用远端工具。
  pending assistant tool-call 参数在写入 Session message 前替换为 sealed marker，公开 events、trace
  与 SQLite 明文扫描均不包含敏感参数。
- Day19 SessionEvaluator 对完整 Session event 链执行确定性过程检查；未改动旧 suite、baseline、
  threshold 或 regression gate。
- Day21.3 专项 4/4、Python 全量 259/259、Node 13/13、P0 15/15、P1 20/20、
  Robustness 25/25、Day19 60/60 与原 11 项 regression gate 全部通过；Day19 max latency
  0.900s，低于 1.878s 上限。

## Day21.3 专项验收（2026-09-22）

- Day21 Session / recovery / E2E 联合专项 21/21，覆盖 Happy Path、HITL 跨进程恢复、
  reject、expire、action hash mismatch、审批重放与 Day19 SessionEvaluator；Demo 返回值新增
  `first_answer` / `final_answer` 显式断言，确认最终答案确实由完整链路产出。
- Happy Path 验收使用同一 `thread_accept_happy`，产生两个独立 trace；事件依次覆盖
  Workflow/Router、Skill、Agent Loop、本地 Tool、Sub-agent、contract check、Final Answer 与
  Session 持久化。HITL 验收使用同一 `thread_accept_hitl`，pending trace 与恢复 trace 不同，
  模拟重启 approve 后远端 mock MCP 只执行一次。
- pending、approved、rejected、expired、hash mismatch 和 replay 均经过持久化状态验证；只有
  匹配 `approval_id + action_hash` 且未消费的 approved 动作可恢复执行。公开 Session event、
  Trace 及 SQLite 明文扫描不包含测试敏感值。
- Workflow、Skill、MCP、Sub-agent、Memory、Todo、Context Compression、Observability、
  Guardrails、HITL 分组回归 126/126；Python 全量 259/259，Node 13/13。
- P0 15/15、P1 20/20、Robustness 25/25；Day19 Eval Harness 60/60，原 11 项 regression
  gate 全部通过，security violation 与 contract failure 均为 0。最终 Day19 average / p95 /
  max latency 分别为 0.372s / 0.935s / 1.237s，均在版本化容差内。
- 补充语义评测：Context Compression 9/9、Historical Summary 8/8、多步语义 3/3、
  图表 5/5、多文件 5/5、历史对话 8/8。本次验收未修改 P0/P1 业务逻辑、评测预期、
  baseline、threshold 或 regression gate。

## Desktop M1 Electron Shell + 第一条 IPC

- 新增完全独立的 `desktop/` Electron + TypeScript 工程；没有修改 Python Runtime、根目录
  Node P0 实现或现有业务模块。Main、preload、renderer、shared 按承载职责分层。
- 创建最小 BrowserWindow，明确启用 `contextIsolation: true`、`nodeIntegration: false`、
  `sandbox: true`，并拒绝新窗口和页面导航；Renderer CSP 仅允许本地资源。
- 新增唯一 IPC `runs:start`。preload 只暴露 `startRun(input)`，Main 对 unknown payload
  重新验证对象结构、唯一 `message` 字段、字符串类型、非空和 4000 字符上限。
- 定义统一 `IpcResult<T>`：成功为 `ok: true + data`，失败为 `ok: false +
  error { code, message, action? }`。M1 handler 只返回 Electron Shell 接收确认，不启动或
  模拟 Python Runtime。
- Renderer 仅包含输入框、发送按钮和结果区域，不 import Node、Electron Main、Python Runtime
  或现有 Agent 业务模块。sandbox preload 采用零本地运行时依赖，避免受限 `require`。
- Desktop M1 类型编译、IPC/校验/安全专项 5/5；隐藏 BrowserWindow smoke test 实际完成
  Renderer context → preload → `ipcRenderer.invoke('runs:start')` → Main → `IpcResult` 链路，
  并分别断言合法输入的成功信封和非法空消息的失败信封。
- 原项目 Python 全量 259/259、Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、
  Day19 60/60 与原 11 项 regression gate 全部通过；没有修改 baseline、threshold 或评测预期。

## Desktop M2 Python Runtime Bridge + Agent Event Streaming

- `desktop/src/bridge/` 新增 ProcessManager、RuntimeClient 与版本化 JSONL protocol；Electron Main
  启动 Python supervisor，`runs:start` 现在返回由 Python 生成的真实 run/thread ID 和现有
  TraceCollector 生成的 trace ID，不再返回 Shell acknowledgement。
- Python supervisor 为每个 run 创建独立 worker，stdout 仅输出 ASCII-safe UTF-8 JSONL，普通输出和
  诊断重定向到 stderr。非法 JSON、未知 command、非法 payload 和未知 event type 均 fail-closed，
  不会使 Main 或 Python supervisor 崩溃。
- TraceCollector 增加默认关闭、fail-safe 的 event sink，Workflow 允许通过私有 state 注入统一
  collector；默认执行路径不变。route、skill、tool 和 approval 等事件仍由现有 Runtime 产生，
  bridge 只映射协议字段并实时转发。
- preload 仅暴露 `startRun`、`cancelRun`、`onAgentEvent`；Main 使用 `agent:event` 推送，Renderer
  只按 per-run sequence 排序展示，不重新计算或解释 Runtime 结果。
- `run.cancel` 由 Main 传入 Python supervisor；supervisor 终止对应 run worker，原子标记 cancelled，
  产生严格递增的 `run_cancelled`，并丢弃所有迟到业务事件。Python supervisor 异常退出时，
  RuntimeClient 将 pending request 失败并向仍存活的 Renderer 投影结构化 `runtime_error`。
- Desktop M2 TypeScript/IPC/进程/顺序/取消/崩溃专项 9/9、Python bridge 协议专项 3/3、
  隐藏 Electron 窗口 E2E 通过；E2E 明确断言 Python 事件已渲染、真实 ID 已返回，以及 Python
  崩溃后页面仍存在并展示 `RUNTIME_PROCESS_EXIT`。
- 原项目 Python 全量 260/260、Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、
  Day19 60/60 与原 11 项 regression gate 全部通过；Day19 average/p95/max latency 分别为
  0.318s/0.764s/1.117s，均在稳定基线容差内。

## Desktop M3 Chat + File + Chart + Run State

- Renderer 增加最小 Chat UI：发送用户消息、展示 Runtime 最终回答、显示运行状态、结构化错误、
  partial 结果、取消按钮和折叠的 Runtime event 列表；不在前端生成分析结论。
- Run State 明确支持 `idle`、`running`、`completed`、`failed`、`cancelled`、
  `waiting_approval` 和 `partial`。`OrderedRunProjector` 按每个 run 的 sequence 缓冲、去重并顺序
  应用事件；所有业务状态均来自 Runtime Event。
- preload 新增 `selectDataset()`，Renderer 只能提交可选 thread ID。Electron Main 使用原生文件
  对话框取得 CSV/XLSX 路径并直接交给 RuntimeClient，文件路径不会返回 Renderer。
- JSONL protocol 新增 `dataset.register` 和 `chart_ready`。Python supervisor 使用现有
  DatasetRegistry 完成格式、20MB 上限、读取、摘要与 dataset ID 生成，并将 dataset ID 绑定到
  thread；run worker 仅按该受控映射恢复活动数据集。
- M3 BridgeModel 仍是桌面 composition adapter，只负责基于公开 DatasetSummary 选择现有受控工具；
  所有读取、分组、统计、趋势和图表数据继续由 ToolRegistry 中的确定性工具完成。
- run worker 为既有 Chart 工具传入受控 artifact 目录；`generate_chart` 的既有 Chart Spec 经
  `chart_ready` 投影到 Renderer。JSONL 只包含 spec 和不含路径的 artifact 元数据，不传完整 SVG、
  ToolResult 或本地路径；Renderer 仅执行 bar/line/scatter 的展示布局，不重新计算业务数据。
- Renderer TypeScript 模块通过构建期本地 bundle 运行，未开启 Node integration，也未放宽 CSP、
  contextIsolation 或 sandbox 安全配置。
- Desktop M3 TypeScript/IPC/协议/Run State/文件隔离/真实 Dataset+Chart 专项 14/14，Python bridge
  专项 5/5，隐藏 Electron E2E 通过；E2E 覆盖 Chat 最终回答、completed 状态、Chart Spec 渲染、
  Runtime crash 结构化错误和页面存活。
- 2026-09-22 完成真实 Electron 窗口人工最终验收：原生 CSV/XLSX 文件选择、DatasetSummary 展示、
  Send、Run State 变化、Runtime events 实时投影与 Stop cancel 均确认可用；运行环境为 Electron
  Main + preload + Renderer，不是浏览器静态页。Desktop M3 正式验收完成。
- 原项目 Python 全量 260/260、Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、
  Day19 60/60 与原 11 项 regression gate 全部通过；Day19 average/p95/max latency 分别为
  0.260s/0.664s/0.852s，均在稳定基线容差内。

## Desktop M4 Session + Recovery + HITL UI

- 新增 `sessions:list`、`sessions:get`、`sessions:resume` 的 Renderer → preload → Main →
  Runtime Bridge 调用链。最近 Session 的 thread ID、更新时间、消息摘要以及恢复后的 messages/events
  全部从现有 `SQLiteSessionStore` 读取，并由 `SessionStateProjector` 在 Python 侧 hydrate
  `ConversationState`；Electron 没有新增 Session 副本或业务数据库。
- Session 恢复沿用原 `thread_id`，每次后续 run 和 approval resume 生成新的 `trace_id`。恢复接口只读取
  与投影历史状态，不执行历史 Tool call；BridgeModel 只消费当前 user 之后的新 Tool observation，避免把
  已完成旧动作当作当前动作重复处理。
- 新增 `approvals:approve` / `approvals:reject` IPC 与最小审批卡片。卡片仅展示 action type、Runtime
  生成的 risk summary、approval ID 和 expires_at；action hash 只作为 opaque 回传值保存在 Renderer
  状态中，原始工具参数不展示且持久化消息使用 sealed 占位符。
- 审批执行继续复用 `PersistentApprovalManager`、`SQLiteApprovalRepository`、Guardrail 和
  ToolRegistry。thread ID、approval ID、action hash、TTL 与 consumed/replay 校验都在 Python 完成；
  Approve 只执行加密保存的单个原动作，Reject、expired、hash mismatch 和 replay 均不执行底层工具。
- Run State 新增 `resuming`、`rejected`、`expired`，保留 `waiting_approval`；`approval_required` 与
  `approval_resolved` 均为 Runtime Event。Renderer 继续按 run sequence 应用事件，并按当前 thread
  过滤，防止 Session A/B 事件交叉投影。
- Desktop M4 TypeScript/IPC/Runtime/Session/HITL 专项 19/19，通过真实隐藏 Electron BrowserWindow
  E2E，覆盖 Session 列表、选择旧 Session 恢复 messages、审批卡片脱敏、Reject 不执行和 Approve
  恢复原动作。测试主机的 Chromium 子进程 sandbox 受系统策略限制，自动化执行时使用
  `ELECTRON_DISABLE_SANDBOX=1`；生产 BrowserWindow 配置仍由专项断言保持 `sandbox=true`、
  `contextIsolation=true`、`nodeIntegration=false`。
- 回归结果：Python 全量 261/261、原 Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、
  Day19 Eval Harness 60/60、原 11 项 regression gate 全部 PASS；security violation 与 contract
  failure 均为 0。Day19 average/p95/max latency 为 0.337s/1.032s/1.233s，均在稳定基线容差内。
- 未修改 P0/P1 业务逻辑、评测预期、baseline 或 threshold；Desktop M1/M2/M3 架构边界保持不变。

### Desktop M4 边界场景复验

- 增加 Runtime 宿主重启专项：关闭首个 supervisor/client 后使用同一 runtime directory 创建新宿主，
  Session 列表、消息、events 和 pending approval 均可恢复；批准后保持原 thread ID、生成新 trace ID，
  并只执行一次原动作。
- approval 的重复点击由 Renderer pending 状态禁用按钮，跨进程 replay 继续由 Python consumed 状态
  拒绝；expired、reject、action hash mismatch 均验证为零底层执行。
- 增加 Session A/B 双层隔离验证：Run State 单元测试拒绝其他 thread event；Electron E2E 在切换
  Session 后注入旧 thread 的迟到 Runtime error，当前 messages/events/error 均未被污染。
- Session 切换复用应用级单一 `onAgentEvent` listener，不创建 session-scoped listener；Renderer reload
  销毁旧 preload context 后，pending approval 可从 SessionStore 重新 hydrate。
- 发现并最小修复 hydrate 失败缺少 Retry 的 UI 缺口：结构化 IPC error 现在保留失败 thread ID，用户可
  重试同一恢复请求；成功后清空错误和 Retry 状态。不存在的 thread ID 安全返回
  `session_not_found`。
- 重复 hydrate 已完成 Session 前后 `approval_resumed` 事件数量保持不变，确认读取恢复不会重放动作。
- 边界复验后 Desktop 专项 20/20、Electron E2E PASS、Python 全量 261/261、Day19 60/60 与
  11 项 regression gate 全部 PASS；最终 average/p95/max latency 为
  0.284s/0.761s/0.947s，security violation 与 contract failure 均为 0。

## Desktop M5 Trace Panel + Error/Retry + Product States

- 新增 `trace-panel.ts` 纯投影层，将 Runtime/Session events 分类为 route、skill、tool、MCP、
  sub-agent、guardrail、approval、error 和 runtime；run 按 Runtime sequence 排序，Session hydrate
  按 SessionStore 规范返回顺序编号。Renderer 不生成 Runtime Event，也不推导 Python 业务结论。
- Trace Panel 使用外层及逐事件 `<details>` 折叠结构，只展示 sequence、分类、受控名称、status 和
  error code。专项测试确认 arguments、metadata、文件路径、action hash、错误正文与测试 secret
  不会进入 Trace 投影。
- 新增 `product-state.ts`，统一 loading、empty、running、partial、stale、waiting_approval、
  completed、failed、cancelled 九种产品状态；每种状态固定提供 happening、can continue 和
  next action 文案。
- Error Card 统一显示 code、message、action。Session list/hydrate、文件选择、run start、Runtime
  event 和 Chart render 的可恢复错误可绑定最小 Retry；所有异步入口均有终态，避免永久 loading。
- Run Retry 复用当前 thread ID，并通过原 `runs:start` 生成新 run/trace；partial 保留已有回答和
  Chart，明确显示缺失项。stale 第一版只显示并提供 Session refresh/原 Dataset 重新选择入口。
- Retry 安全边界保持在 Python：waiting approval 不显示通用 Retry，Approve/Reject 错误不自动重放；
  即使普通 run Retry 再次遇到高风险写操作，也只会生成新的 pending approval，不能自动执行。
  已 consumed approval 的 replay 仍由 PersistentApprovalManager 拒绝。
- Electron E2E 覆盖 Trace 顺序、敏感信息不显示、partial 保留有效结果、failed→Retry、stale 刷新、
  cancelled 展示、waiting approval 无 Retry 绕过、同 thread 新 trace、Session/run 事件隔离和
  Renderer reload。Desktop TypeScript/IPC/Runtime 专项 23/23 PASS，Electron E2E PASS。
- 回归结果：Python 全量 261/261、原 Node 13/13、P0 15/15、P1 20/20、Robustness 25/25、
  Day19 Eval Harness 60/60、11 项 regression gate 全部 PASS；security violation 与 contract
  failure 均为 0，average/p95/max latency 为 0.265s/0.692s/0.917s。
- 本阶段未修改 Python Runtime 业务语义、P0/P1 业务逻辑、评测预期、baseline 或 threshold。

## 剩余风险与待处理

- 当前没有阻塞验收的问题。
- Desktop M4 已接入 Session/HITL UI；当前仍未实现 heartbeat、sequence gap 自动补洞或多实例并发协调。
- M3 的 analysis route 仍使用最小 BridgeModel composition adapter；真实模型客户端与凭证将在
  后续阶段注入，但 Workflow、Agent Loop、DatasetRegistry、Chart 和工具语义仍由现有 Python Runtime 执行。
- 开发环境需要 `DATA_AGENT_PYTHON`、项目 `.venv` 或 PATH 中的 Python；独立 Python sidecar
  和安装包属于 M6。
- 取消通过终止独立 run worker 保证不再产生后续业务事件；真实外部 MCP 写操作未来仍需传输层取消、
  幂等键和执行结果核对，不能仅凭进程终止推断外部副作用不存在。
- 当前 Main 将 Agent event 广播到全部窗口；引入多窗口后需按订阅的 thread/run 隔离事件。
- Day19 baseline 当前仍需人工审核和更新；统一评测只读取 `eval_harness/baselines/day19-stable.json`，不会在运行时自动提升或覆盖稳定基线。
- Day19 当前仍有 20 个旧 P1 案例未暴露完整 trace、Workflow route 尚未纳入正式统一 suite、token 用量未由底层客户端提供；这些字段在报告中保持 unavailable，不以 0 代替。
- latency 会受运行环境和并发影响，当前由版本化 baseline 容差与原有硬 threshold 共同约束；调整容差或 baseline 必须经过人工审核。
- 生产部署需使用 PersistentApprovalManager 与 SQLite repository；原内存 ApprovalStore 仍仅适合
  单进程测试。当前尚不支持多实例协调、审批身份认证或主动后台清理过期记录；过期状态在
  resolve 时惰性判定。
- ConversationState 与 HITL pending 已可从 Session 投影/恢复；DatasetRegistry 的文件路径映射、
  Todo 和 Memory 生命周期仍由应用层显式管理，不会被 Session 自动恢复。
- Session payload 当前按调用方提供内容原样 JSON 持久化，没有自动脱敏、加密、容量上限或保留期；
  在正式接入 messages/Trace 前必须增加持久化策略。
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
- ConversationState 可由 Session messages/events 在新进程重建，但不处理多进程共享写入或分布式并发。
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
