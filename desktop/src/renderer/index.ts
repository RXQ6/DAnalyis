import type { AgentEvent, ApprovalInput, DatasetSummary, IpcError, RunsStartInput, SessionSnapshot, SessionSummary } from "../shared/ipc";
import { renderChartSpec } from "./chart-renderer";
import { datasetDescription, humanAction, humanError, humanRisk, humanStatus, presentAnswer, readableTitle, safePlainText, sessionTitle } from "./presentation";
import { describeProductState, isStaleError, productStateFromRun, type ProductState } from "./product-state";
import { OrderedRunProjector, eventBelongsToSession, type ApprovalProjection, type RunProjection } from "./run-state";
import { projectTrace, type TraceEntry } from "./trace-panel";

const input = required<HTMLInputElement>("#run-input");
const sendButton = required<HTMLButtonElement>("#run-submit");
const stopButton = required<HTMLButtonElement>("#run-stop");
const fileButton = required<HTMLButtonElement>("#file-select");
const datasetView = required<HTMLElement>("#dataset-summary");
const sessionsEmpty = required<HTMLElement>("#sessions-empty");
const welcome = required<HTMLElement>("#welcome");
const welcomeTitle = required<HTMLElement>("#welcome-title");
const welcomeCopy = required<HTMLElement>("#welcome-copy");
const welcomeSelect = required<HTMLButtonElement>("#welcome-select");
const conversationHeading = required<HTMLElement>("#conversation-heading");
const chartsHeading = required<HTMLElement>("#charts-heading");
const headerSession = required<HTMLOutputElement>("#header-session");
const headerDataset = required<HTMLOutputElement>("#header-dataset");
const productStateView = required<HTMLElement>("#product-state");
const statusView = required<HTMLElement>("#run-status");
const stateLabel = required<HTMLElement>("#state-label");
const stateHappening = required<HTMLElement>("#state-happening");
const stateContinuation = required<HTMLElement>("#state-continuation");
const stateNextAction = required<HTMLElement>("#state-next-action");
const stateRefresh = required<HTMLButtonElement>("#state-refresh");
const messages = required<HTMLElement>("#messages");
const charts = required<HTMLElement>("#charts");
const errorCard = required<HTMLElement>("#error-card");
const errorTitle = required<HTMLElement>("#error-title");
const errorCode = required<HTMLElement>("#error-code");
const errorMessage = required<HTMLElement>("#error-message");
const errorAction = required<HTMLElement>("#error-action");
const errorRetry = required<HTMLButtonElement>("#error-retry");
const eventList = required<HTMLOListElement>("#event-list");
const traceEmpty = required<HTMLElement>("#trace-empty");
const sessionList = required<HTMLOListElement>("#session-list");
const sessionsRefresh = required<HTMLButtonElement>("#sessions-refresh");
const approvalCard = required<HTMLElement>("#approval-card");
const approvalAction = required<HTMLElement>("#approval-action");
const approvalRisk = required<HTMLElement>("#approval-risk");
const approvalId = required<HTMLElement>("#approval-id");
const approvalExpires = required<HTMLElement>("#approval-expires");
const approveButton = required<HTMLButtonElement>("#approval-approve");
const rejectButton = required<HTMLButtonElement>("#approval-reject");
const workspace = required<HTMLElement>("#workspace");
const sidebar = required<HTMLElement>("#left-sidebar");
const sidebarToggle = required<HTMLButtonElement>("#sidebar-toggle");
const sidebarBackdrop = required<HTMLElement>("#sidebar-backdrop");
const leftResizer = required<HTMLElement>("#left-resizer");
const traceResizer = required<HTMLElement>("#trace-resizer");
const tracePanel = required<HTMLDetailsElement>("#trace-panel");
const headerFileAction = required<HTMLButtonElement>("#header-file-action");
const settingsOpen = required<HTMLButtonElement>("#settings-open");
const settingsNav = required<HTMLButtonElement>("#settings-nav");
const workspaceOpen = required<HTMLButtonElement>("#workspace-open");
const settingsView = required<HTMLElement>("#settings-view");
const analysisScroll = required<HTMLElement>("#analysis-scroll");
const composer = required<HTMLElement>("#composer");
const analysisHeader = required<HTMLElement>("#analysis-header");
const analysisTitle = required<HTMLElement>("#analysis-title");
const analysisContext = required<HTMLElement>("#analysis-context");
const datasetOverview = required<HTMLElement>("#dataset-overview");
const datasetOverviewName = required<HTMLElement>("#dataset-overview-name");
const metricCards = required<HTMLElement>("#metric-cards");
const analysisSummary = required<HTMLElement>("#analysis-summary");
const analysisSummaryContent = required<HTMLElement>("#analysis-summary-content");
const conversationPanel = required<HTMLDetailsElement>("#conversation-panel");
const recentAnalyses = required<HTMLElement>("#recent-analyses");

type RetryAction = () => Promise<void>;

let activeRunId: string | null = null;
let currentThreadId: string | undefined;
let selectedDataset: DatasetSummary | undefined;
let currentApproval: ApprovalProjection | null = null;
let currentProductState: ProductState = "loading";
let currentRetry: RetryAction | null = null;
let lastRunRequest: RunsStartInput | null = null;
let activePage: "workspace" | "settings" = "workspace";
let currentSessionTitle = "新分析";
let sessionLoadVersion = 0;
const sessionTitles = new Map<string, { updatedAt: string; title: string }>();
const projectors = new Map<string, OrderedRunProjector>();
const pendingEvents = new Map<string, AgentEvent[]>();

function setButtonBusy(button: HTMLButtonElement, busy: boolean, busyLabel: string, idleLabel: string): void {
  button.textContent = busy ? busyLabel : idleLabel;
  if (busy) button.setAttribute("aria-busy", "true");
  else button.removeAttribute("aria-busy");
}

if (typeof window.agent?.onAgentEvent === "function") window.agent.onAgentEvent((event) => {
  if (!eventBelongsToSession(event, currentThreadId)) return;
  if (!event.run_id) {
    if (event.type === "runtime_error") {
      showError(event.error, safeRunRetry(), event.error && isStaleError(event.error.code) ? "stale" : "failed");
    }
    return;
  }
  const projector = projectors.get(event.run_id);
  if (!projector) {
    const queued = pendingEvents.get(event.run_id) ?? [];
    queued.push(event);
    pendingEvents.set(event.run_id, queued);
    return;
  }
  renderProjection(projector.push(event));
});

sessionsRefresh.addEventListener("click", () => void loadSessions());
stateRefresh.addEventListener("click", () => void loadSessions());
headerFileAction.addEventListener("click", () => fileButton.click());
sidebarToggle.addEventListener("click", () => setSidebarOpen(!workspace.classList.contains("sidebar-open")));
sidebarBackdrop.addEventListener("click", () => setSidebarOpen(false));
workspaceOpen.addEventListener("click", () => showPage("workspace"));
settingsOpen.addEventListener("click", () => showPage("settings"));
settingsNav.addEventListener("click", () => showPage("settings"));
document.querySelectorAll<HTMLButtonElement>(".example-question").forEach((button) => {
  button.addEventListener("click", () => {
    showPage("workspace");
    input.value = button.dataset.example ?? "";
    input.focus();
  });
});
installResizer(leftResizer, "left");
installResizer(traceResizer, "right");
errorRetry.addEventListener("click", async () => {
  if (!currentRetry || currentProductState === "waiting_approval") return;
  const retry = currentRetry;
  currentRetry = null;
  errorRetry.disabled = true;
  setButtonBusy(errorRetry, true, "重试中…", "重试");
  clearError();
  try {
    await retry();
  } finally {
    errorRetry.disabled = false;
    setButtonBusy(errorRetry, false, "重试中…", "重试");
  }
});

async function loadSessions(background = false): Promise<void> {
  const stateBeforeLoad = currentProductState;
  if (!background) renderProductState("loading");
  try {
    const response = await window.agent.listSessions();
    if (!response.ok) {
      showError(response.error, () => loadSessions(), isStaleError(response.error.code) ? "stale" : "failed");
      return;
    }
    const loadVersion = ++sessionLoadVersion;
    sessionList.replaceChildren(...response.data.sessions.map((session) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.threadId = session.threadId;
      const cached = sessionTitles.get(session.threadId);
      const title = cached?.updatedAt === session.updatedAt ? cached.title : "未命名分析";
      button.title = title;
      const summary = document.createElement("span");
      summary.className = "session-summary";
      summary.textContent = title;
      const metadata = document.createElement("span");
      metadata.className = "session-meta";
      const status = document.createElement("span");
      status.className = "session-status";
      status.dataset.state = session.status;
      status.textContent = humanStatus(session.status);
      const updatedAt = document.createElement("span");
      updatedAt.className = "session-updated";
      updatedAt.textContent = formatDate(session.updatedAt);
      metadata.append(status, updatedAt);
      button.append(summary, metadata);
      button.addEventListener("click", () => void resumeThread(session.threadId));
      item.append(button);
      return item;
    }));
    sessionsEmpty.hidden = response.data.sessions.length > 0;
    renderRecentSessions(response.data.sessions);
    void hydrateSessionTitles(response.data.sessions, loadVersion);
    syncSessionSelection();
    if (!background) {
      clearError();
      const activeProjection = activeRunId ? projectors.get(activeRunId)?.snapshot() : null;
      renderProductState(
        currentApproval
          ? "waiting_approval"
          : stateBeforeLoad === "stale" && activeRunId
            ? "stale"
            : activeProjection
              ? productStateFromRun(activeProjection.status)
              : currentThreadId
                ? "completed"
                : "empty",
      );
    }
  } catch {
    showError(
      { code: "IPC_UNAVAILABLE", message: "Sessions could not be loaded.", action: "Retry Session refresh." },
      () => loadSessions(),
    );
  }
}

async function hydrateSessionTitles(sessions: SessionSummary[], version: number): Promise<void> {
  for (const session of sessions) {
    if (version !== sessionLoadVersion) return;
    const cached = sessionTitles.get(session.threadId);
    if (cached?.updatedAt === session.updatedAt) continue;
    try {
      const response = await window.agent.getSession({ threadId: session.threadId });
      if (!response.ok || version !== sessionLoadVersion) continue;
      const restoredTitle = sessionTitle(response.data);
      const title = restoredTitle === "未命名分析" && session.threadId === currentThreadId &&
        currentSessionTitle !== "新分析" && currentSessionTitle !== "未命名分析"
        ? currentSessionTitle : restoredTitle;
      sessionTitles.set(session.threadId, { updatedAt: session.updatedAt, title });
      const button = Array.from(sessionList.querySelectorAll<HTMLButtonElement>("button[data-thread-id]"))
        .find((candidate) => candidate.dataset.threadId === session.threadId);
      const label = button?.querySelector<HTMLElement>(".session-summary");
      if (label) label.textContent = title;
      if (button) button.title = title;
      if (session.threadId === currentThreadId) {
        currentSessionTitle = title;
        renderContextHeader();
      }
      renderRecentSessions(sessions);
    } catch {
      // A session may be removed between listing and this read-only title lookup.
    }
  }
}

function renderRecentSessions(sessions: SessionSummary[]): void {
  if (sessions.length === 0) {
    const empty = document.createElement("p");
    empty.textContent = "分析记录会出现在这里。";
    recentAnalyses.replaceChildren(empty);
    return;
  }
  recentAnalyses.replaceChildren(...sessions.slice(0, 3).map((session) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = sessionTitles.get(session.threadId)?.title ?? "未命名分析";
    button.addEventListener("click", () => void resumeThread(session.threadId));
    return button;
  }));
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "最近" : new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date);
}

async function resumeThread(threadId: string): Promise<void> {
  showPage("workspace");
  renderProductState("loading");
  clearError();
  try {
    const resumed = await window.agent.resumeSession({ threadId });
    if (!resumed.ok) {
      showError(resumed.error, () => resumeThread(threadId), isStaleError(resumed.error.code) ? "stale" : "failed");
      return;
    }
    hydrateSession(resumed.data);
    setSidebarOpen(false);
  } catch {
    showError(
      { code: "IPC_UNAVAILABLE", message: "Session recovery is unavailable.", action: "Retry Session recovery." },
      () => resumeThread(threadId),
    );
  }
}

fileButton.addEventListener("click", () => void selectDataset());
welcomeSelect.addEventListener("click", () => {
  if (selectedDataset) input.focus();
  else fileButton.click();
});

async function selectDataset(): Promise<void> {
  const previousState = currentProductState;
  fileButton.disabled = true;
  welcomeSelect.disabled = true;
  setButtonBusy(fileButton, true, "选择中…", "选择 CSV / XLSX");
  renderProductState("loading");
  clearError();
  try {
    const response = await window.agent.selectDataset(currentThreadId ? { threadId: currentThreadId } : {});
    if (!response.ok) {
      showError(response.error, () => selectDataset(), isStaleError(response.error.code) ? "stale" : "failed");
      return;
    }
    if (response.data.status === "cancelled") {
      renderProductState(previousState === "loading" ? "empty" : previousState);
      return;
    }
    currentThreadId = response.data.threadId;
    selectedDataset = response.data.dataset;
    renderDataset(selectedDataset);
    showPage("workspace");
    renderProductState("empty");
  } catch {
    showError(
      { code: "IPC_UNAVAILABLE", message: "The desktop shell is unavailable.", action: "Retry file selection." },
      () => selectDataset(),
    );
  } finally {
    fileButton.disabled = false;
    welcomeSelect.disabled = false;
    setButtonBusy(fileButton, false, "选择中…", "选择 CSV / XLSX");
  }
}

sendButton.addEventListener("click", () => {
  const message = input.value.trim();
  if (!message) {
    showError({ code: "INVALID_RUN_INPUT", message: "Message is required.", action: "Enter a request and try again." });
    return;
  }
  const request: RunsStartInput = {
    message,
    ...(currentThreadId ? { threadId: currentThreadId } : {}),
    ...(selectedDataset ? { datasetId: selectedDataset.datasetId } : {}),
  };
  if (currentSessionTitle === "新分析" || currentSessionTitle === "未命名分析") {
    currentSessionTitle = readableTitle(message);
    renderContextHeader();
  }
  input.value = "";
  void startRun(request, true);
});

async function startRun(request: RunsStartInput, appendUser: boolean): Promise<void> {
  sendButton.disabled = true;
  setButtonBusy(sendButton, true, "发送中…", "发送");
  renderProductState("loading");
  clearError();
  if (appendUser) appendMessage("user", request.message);
  lastRunRequest = { ...request };
  try {
    const response = await window.agent.startRun(request);
    if (!response.ok) {
      showError(response.error, () => startRun({ ...request }, false), isStaleError(response.error.code) ? "stale" : "failed");
      return;
    }
    activeRunId = response.data.runId;
    currentThreadId = response.data.threadId;
    renderContextHeader();
    lastRunRequest = { ...request, threadId: response.data.threadId };
    const projector = new OrderedRunProjector(activeRunId);
    projectors.set(activeRunId, projector);
    for (const event of pendingEvents.get(activeRunId) ?? []) projector.push(event);
    pendingEvents.delete(activeRunId);
    renderProductState("running");
    renderProjection(projector.snapshot());
    void loadSessions(true);
  } catch {
    showError(
      { code: "IPC_UNAVAILABLE", message: "The desktop shell is unavailable.", action: "Retry this run." },
      () => startRun({ ...request }, false),
    );
  } finally {
    sendButton.disabled = false;
    setButtonBusy(sendButton, false, "发送中…", "发送");
  }
}

approveButton.addEventListener("click", () => void resolveApproval("approve"));
rejectButton.addEventListener("click", () => void resolveApproval("reject"));

async function resolveApproval(decision: "approve" | "reject"): Promise<void> {
  if (!currentThreadId || !currentApproval) return;
  const decisionButton = decision === "approve" ? approveButton : rejectButton;
  approveButton.disabled = true;
  rejectButton.disabled = true;
  setButtonBusy(decisionButton, true, "提交中…", decision === "approve" ? "确认并继续" : "拒绝");
  currentRetry = null;
  errorRetry.hidden = true;
  renderProductState("running");
  const approvalInput: ApprovalInput = {
    threadId: currentThreadId,
    approvalId: currentApproval.approvalId,
    actionHash: currentApproval.actionHash,
  };
  try {
    const response = decision === "approve"
      ? await window.agent.approve(approvalInput)
      : await window.agent.reject(approvalInput);
    if (!response.ok) {
      approveButton.disabled = false;
      rejectButton.disabled = false;
      showError(response.error, null);
      return;
    }
    activeRunId = response.data.runId;
    const projector = new OrderedRunProjector(activeRunId);
    projectors.set(activeRunId, projector);
    for (const event of pendingEvents.get(activeRunId) ?? []) projector.push(event);
    pendingEvents.delete(activeRunId);
    renderProjection(projector.snapshot());
  } catch {
    approveButton.disabled = false;
    rejectButton.disabled = false;
    showError(
      { code: "IPC_UNAVAILABLE", message: "Approval resolution is unavailable.", action: "Review the approval card and try the decision again." },
      null,
    );
  } finally {
    setButtonBusy(decisionButton, false, "提交中…", decision === "approve" ? "确认并继续" : "拒绝");
  }
}

stopButton.addEventListener("click", async () => {
  if (!activeRunId) return;
  stopButton.disabled = true;
  setButtonBusy(stopButton, true, "停止中…", "停止");
  try {
    const response = await window.agent.cancelRun({ runId: activeRunId });
    if (!response.ok) showError(response.error, null);
  } catch {
    showError({ code: "IPC_UNAVAILABLE", message: "Cancel request failed.", action: "Check Runtime state before trying again." }, null);
  } finally {
    setButtonBusy(stopButton, false, "停止中…", "停止");
  }
});

function renderProjection(projection: RunProjection): void {
  if (projection.runId !== activeRunId) return;
  renderProductState(productStateFromRun(projection.status));
  stopButton.disabled = projection.status !== "running" && projection.status !== "resuming";
  renderApproval(projection.approval);
  renderTrace(projectTrace(projection.events));
  charts.replaceChildren();
  for (const chart of projection.charts) {
    try {
      renderChartSpec(charts, chart.spec);
    } catch {
      showError(
        { code: "INVALID_CHART_SPEC", message: "Runtime returned an invalid Chart Spec.", action: "Retry the run or inspect Trace." },
        safeRunRetry(),
      );
    }
  }
  if (projection.answer && !messages.querySelector(`[data-run-id="${projection.runId}"]`)) {
    const node = appendMessage("assistant", projection.answer);
    node.dataset.runId = projection.runId;
    renderAnalysisSummary(projection.answer);
  }
  if (projection.status === "waiting_approval") {
    clearError();
    currentRetry = null;
    errorRetry.hidden = true;
  } else if (projection.status === "partial") {
    const missing = projection.partialMissing.join(" ") || "Some requested content is unavailable.";
    showError(
      {
        code: projection.error?.code ?? "PARTIAL_RESULT",
        message: missing,
        action: "Keep the available result, review Trace, or retry the run.",
      },
      safeRunRetry(),
      "partial",
    );
  } else if (projection.error) {
    showError(
      { ...projection.error, action: "Review Trace and retry when available." },
      safeRunRetry(),
      isStaleError(projection.error.code) ? "stale" : "failed",
    );
  } else if (["completed", "cancelled"].includes(projection.status)) {
    clearError();
  } else if (projection.status === "expired") {
    showError(
      { code: "APPROVAL_EXPIRED", message: "The approval is no longer valid.", action: "Start a new request if the action is still needed." },
      null,
      "stale",
    );
  }
  syncContentVisibility();
}

function renderApproval(approval: ApprovalProjection | null): void {
  currentApproval = approval;
  approvalCard.hidden = approval === null;
  if (!approval) return;
  approvalAction.textContent = humanAction(approval.actionType);
  approvalRisk.textContent = humanRisk(approval.riskSummary || approval.riskLevel);
  approvalId.textContent = approval.approvalId;
  const expires = new Date(approval.expiresAt);
  approvalExpires.textContent = Number.isNaN(expires.getTime()) ? "请及时处理" : new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(expires);
  approveButton.disabled = false;
  rejectButton.disabled = false;
}

function hydrateSession(snapshot: SessionSnapshot): void {
  currentThreadId = snapshot.threadId;
  currentSessionTitle = sessionTitle(snapshot);
  activeRunId = null;
  selectedDataset = undefined;
  lastRunRequest = null;
  renderDataset();
  messages.replaceChildren();
  charts.replaceChildren();
  analysisSummaryContent.replaceChildren();
  analysisSummary.hidden = true;
  renderTrace(projectTrace(snapshot.events, { useInputOrder: true }));
  for (const message of snapshot.messages) {
    const role = message.role;
    const content = message.content;
    if ((role === "user" || role === "assistant") && typeof content === "string") {
      appendMessage(role, content);
      if (role === "assistant") renderAnalysisSummary(content);
    }
  }
  const approval = pendingApproval(snapshot.events);
  renderApproval(approval);
  clearError();
  renderProductState(approval ? "waiting_approval" : snapshot.messages.length ? "completed" : "empty");
  syncContentVisibility();
}

function pendingApproval(events: Array<Record<string, unknown>>): ApprovalProjection | null {
  const decided = new Set<string>();
  for (const event of events) {
    if (event.event_type === "approval_decided" && isRecord(event.metadata) && typeof event.metadata.approval_id === "string") {
      decided.add(event.metadata.approval_id);
    }
  }
  for (const event of [...events].reverse()) {
    if (event.event_type !== "approval_requested" || !isRecord(event.metadata)) continue;
    const metadata = event.metadata;
    if (
      typeof metadata.approval_id === "string" && !decided.has(metadata.approval_id) &&
      typeof metadata.action_hash === "string" && typeof metadata.action_type === "string" &&
      typeof metadata.risk_level === "string" && typeof metadata.expires_at === "string"
    ) {
      return {
        approvalId: metadata.approval_id,
        actionHash: metadata.action_hash,
        actionType: metadata.action_type,
        riskLevel: metadata.risk_level,
        riskSummary: typeof metadata.risk_summary === "string" ? metadata.risk_summary : metadata.risk_level,
        expiresAt: metadata.expires_at,
      };
    }
  }
  return null;
}

function renderProductState(state: ProductState): void {
  currentProductState = state;
  const description = describeProductState(state);
  productStateView.dataset.state = state;
  statusView.textContent = humanStatus(state);
  statusView.dataset.state = state;
  stateLabel.textContent = humanStatus(state);
  stateHappening.textContent = description.happening;
  stateContinuation.textContent = description.canContinue;
  stateNextAction.textContent = description.nextAction;
  stateRefresh.hidden = state !== "stale";
  syncContentVisibility();
}

function renderTrace(entries: TraceEntry[]): void {
  traceEmpty.hidden = entries.length > 0;
  eventList.replaceChildren(...entries.map((entry) => {
    const item = document.createElement("li");
    item.className = "trace-item";
    item.dataset.category = entry.category;
    item.dataset.sequence = String(entry.sequence);
    const detail = document.createElement("details");
    const summary = document.createElement("summary");
    const label = document.createElement("span");
    label.className = "trace-label";
    label.textContent = entry.label;
    summary.setAttribute("aria-label", entry.label);
    summary.append(label);
    const fields = document.createElement("dl");
    if (entry.status) appendField(fields, "状态", entry.status);
    detail.append(summary, fields);
    item.append(detail);
    return item;
  }));
}

function appendField(list: HTMLDListElement, label: string, value: string): void {
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value;
  list.append(term, description);
}

function renderDataset(dataset?: DatasetSummary): void {
  datasetView.textContent = dataset ? datasetDescription(dataset) : "尚未选择数据文件";
  datasetView.title = dataset?.filename ?? "尚未选择数据文件";
  datasetOverview.hidden = !dataset;
  metricCards.replaceChildren();
  if (dataset) {
    datasetOverviewName.textContent = dataset.filename;
    for (const [label, value] of [["数据行数", dataset.rowCount], ["字段数量", dataset.columnCount]] as const) {
      const card = document.createElement("div");
      card.className = "metric-card";
      const name = document.createElement("span");
      name.textContent = label;
      const number = document.createElement("strong");
      number.textContent = new Intl.NumberFormat("zh-CN").format(value);
      card.append(name, number);
      metricCards.append(card);
    }
  }
  welcomeTitle.textContent = dataset ? "数据已就绪，开始提问。" : "把问题交给数据。";
  welcomeCopy.textContent = dataset
    ? "围绕当前文件提出问题。分析结果与图表会显示在这里。"
    : "选择一个 CSV 或 XLSX 文件，然后用自然语言提问。分析结果、图表与过程会汇集在这里。";
  welcomeSelect.textContent = dataset ? "提出问题" : "选择数据文件";
  analysisContext.textContent = dataset ? datasetDescription(dataset) : "选择数据并提出问题。";
  renderContextHeader();
}

function syncContentVisibility(): void {
  conversationPanel.hidden = messages.childElementCount === 0;
  chartsHeading.hidden = charts.childElementCount === 0;
  welcome.hidden = currentProductState !== "empty" || messages.childElementCount > 0 || charts.childElementCount > 0;
  analysisHeader.hidden = !welcome.hidden;
}

function renderContextHeader(): void {
  headerSession.textContent = currentSessionTitle;
  headerSession.title = currentSessionTitle;
  analysisTitle.textContent = currentSessionTitle;
  headerDataset.textContent = selectedDataset?.filename ?? "尚未选择";
  headerDataset.title = selectedDataset?.filename ?? "尚未选择";
  syncSessionSelection();
}

function syncSessionSelection(): void {
  sessionList.querySelectorAll<HTMLButtonElement>("button[data-thread-id]").forEach((button) => {
    const selected = button.dataset.threadId === currentThreadId;
    button.classList.toggle("is-selected", selected);
    if (selected) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
}

function appendMessage(role: "user" | "assistant", text: string): HTMLElement {
  const article = document.createElement("article");
  article.dataset.role = role;
  const label = document.createElement("strong");
  label.textContent = role === "user" ? "你" : "分析结果";
  const content = document.createElement("p");
  const answer = role === "assistant" ? presentAnswer(text) : null;
  content.textContent = answer?.kind === "table"
    ? answer.rows.map(([name, value]) => `${name}：${value}`).join(" · ")
    : answer?.kind === "unsupported"
      ? "此结构化结果暂时无法在当前界面安全展示。"
      : answer?.kind === "text" ? answer.text : text;
  article.append(label, content);
  messages.append(article);
  syncContentVisibility();
  return article;
}

function renderAnalysisSummary(answer: string): void {
  const presented = presentAnswer(answer);
  analysisSummaryContent.replaceChildren();
  if (presented.kind === "table") {
    const table = document.createElement("table");
    table.className = "result-table";
    const body = document.createElement("tbody");
    for (const [label, value] of presented.rows) {
      const row = document.createElement("tr");
      const heading = document.createElement("th");
      heading.scope = "row";
      heading.textContent = label;
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(heading, cell);
      body.append(row);
    }
    table.append(body);
    analysisSummaryContent.append(table);
  } else {
    const paragraph = document.createElement("p");
    paragraph.textContent = presented.kind === "text"
      ? presented.text
      : "此结构化结果暂时无法在当前界面安全展示。";
    analysisSummaryContent.append(paragraph);
  }
  analysisSummary.hidden = false;
}

function showPage(page: "workspace" | "settings"): void {
  activePage = page;
  workspace.classList.toggle("settings-page", page === "settings");
  analysisScroll.hidden = page !== "workspace";
  settingsView.hidden = page !== "settings";
  composer.hidden = page !== "workspace";
  workspaceOpen.classList.toggle("is-active", page === "workspace");
  settingsNav.classList.toggle("is-active", page === "settings");
  setSidebarOpen(false);
}

function setSidebarOpen(open: boolean): void {
  workspace.classList.toggle("sidebar-open", open);
  sidebarBackdrop.hidden = !open;
  sidebarToggle.setAttribute("aria-expanded", String(open));
  sidebar.setAttribute("aria-hidden", String(!open && window.innerWidth <= 900));
}

function installResizer(handle: HTMLElement, side: "left" | "right"): void {
  const minimum = side === "left" ? 208 : 280;
  const maximum = side === "left" ? 340 : 440;
  const defaultWidth = side === "left" ? 248 : 320;
  const property = side === "left" ? "--left-width" : "--right-width";
  const storageKey = side === "left" ? "workspace.leftWidth" : "workspace.rightWidth";
  const update = (width: number): void => {
    const bounded = Math.max(minimum, Math.min(maximum, Math.round(width)));
    workspace.style.setProperty(property, `${bounded}px`);
    handle.setAttribute("aria-valuenow", String(bounded));
    try { localStorage.setItem(storageKey, String(bounded)); } catch { /* UI preference only. */ }
  };
  try {
    const stored = Number(localStorage.getItem(storageKey));
    if (Number.isFinite(stored) && stored >= minimum && stored <= maximum) update(stored);
  } catch { /* UI preference only. */ }
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const start = event.clientX;
    const current = Number.parseInt(getComputedStyle(workspace).getPropertyValue(property), 10) || defaultWidth;
    handle.classList.add("is-dragging");
    handle.setPointerCapture(event.pointerId);
    const move = (moveEvent: PointerEvent): void => update(current + (side === "left" ? 1 : -1) * (moveEvent.clientX - start));
    const finish = (): void => {
      handle.classList.remove("is-dragging");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  });
  handle.addEventListener("keydown", (event) => {
    const current = Number.parseInt(getComputedStyle(workspace).getPropertyValue(property), 10) || defaultWidth;
    const step = event.shiftKey ? 48 : 16;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      update(current + (event.key === "ArrowRight" ? 1 : -1) * (side === "left" ? step : -step));
    } else if (event.key === "Home") { event.preventDefault(); update(minimum); }
    else if (event.key === "End") { event.preventDefault(); update(maximum); }
    else if (event.key === "Escape") { event.preventDefault(); update(defaultWidth); }
  });
  handle.addEventListener("dblclick", () => update(defaultWidth));
}

function showError(error: IpcError | null, retry: RetryAction | null = null, state: ProductState = "failed"): void {
  const structured = error ?? { code: "UNKNOWN_ERROR", message: "Unknown runtime error", action: "Review Trace and try again." };
  errorCard.dataset.state = state;
  errorTitle.textContent = state === "partial" ? "部分结果可用" : state === "stale" ? "内容需要刷新" : "遇到问题";
  errorCode.textContent = structured.code;
  errorMessage.textContent = state === "partial"
    ? safePlainText(structured.message) ?? "部分分析内容暂时不可用。"
    : humanError(structured.code, structured.message);
  errorAction.textContent = state === "stale" ? "刷新历史记录或重新选择数据文件。" : retry ? "可重试此操作。" : "请检查当前状态后继续。";
  errorCard.hidden = false;
  currentRetry = state === "waiting_approval" ? null : retry;
  errorRetry.hidden = currentRetry === null;
  renderProductState(state);
}

function clearError(): void {
  errorCard.hidden = true;
  delete errorCard.dataset.state;
  errorCode.textContent = "";
  errorMessage.textContent = "";
  errorAction.textContent = "";
  currentRetry = null;
  errorRetry.hidden = true;
}

function safeRunRetry(): RetryAction | null {
  if (!lastRunRequest || currentApproval || currentProductState === "waiting_approval") return null;
  const request = { ...lastRunRequest, ...(currentThreadId ? { threadId: currentThreadId } : {}) };
  return () => startRun(request, false);
}

function required<T extends Element>(selector: string): T {
  const node = document.querySelector<T>(selector);
  if (!node) throw new Error(`Required renderer element is missing: ${selector}`);
  return node;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

renderContextHeader();
renderProductState("loading");
setSidebarOpen(false);
window.addEventListener("resize", () => {
  if (window.innerWidth > 900) setSidebarOpen(false);
});
if (typeof window.agent?.onAgentEvent === "function" && typeof window.agent.listSessions === "function") {
  document.body.classList.add("runtime-ready");
  void loadSessions();
}
