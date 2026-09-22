import type { AgentEvent, ApprovalInput, DatasetSummary, IpcError, RunsStartInput, SessionSnapshot } from "../shared/ipc";
import { renderChartSpec } from "./chart-renderer";
import { describeProductState, isStaleError, productStateFromRun, type ProductState } from "./product-state";
import { OrderedRunProjector, eventBelongsToSession, type ApprovalProjection, type RunProjection } from "./run-state";
import { projectTrace, type TraceEntry } from "./trace-panel";

const input = required<HTMLInputElement>("#run-input");
const sendButton = required<HTMLButtonElement>("#run-submit");
const stopButton = required<HTMLButtonElement>("#run-stop");
const fileButton = required<HTMLButtonElement>("#file-select");
const datasetView = required<HTMLElement>("#dataset-summary");
const productStateView = required<HTMLElement>("#product-state");
const statusView = required<HTMLElement>("#run-status");
const stateHappening = required<HTMLElement>("#state-happening");
const stateContinuation = required<HTMLElement>("#state-continuation");
const stateNextAction = required<HTMLElement>("#state-next-action");
const stateRefresh = required<HTMLButtonElement>("#state-refresh");
const messages = required<HTMLElement>("#messages");
const charts = required<HTMLElement>("#charts");
const errorCard = required<HTMLElement>("#error-card");
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

type RetryAction = () => Promise<void>;

let activeRunId: string | null = null;
let currentThreadId: string | undefined;
let selectedDataset: DatasetSummary | undefined;
let currentApproval: ApprovalProjection | null = null;
let currentProductState: ProductState = "loading";
let currentRetry: RetryAction | null = null;
let lastRunRequest: RunsStartInput | null = null;
const projectors = new Map<string, OrderedRunProjector>();
const pendingEvents = new Map<string, AgentEvent[]>();

window.agent.onAgentEvent((event) => {
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
errorRetry.addEventListener("click", async () => {
  if (!currentRetry || currentProductState === "waiting_approval") return;
  const retry = currentRetry;
  currentRetry = null;
  errorRetry.disabled = true;
  clearError();
  try {
    await retry();
  } finally {
    errorRetry.disabled = false;
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
    sessionList.replaceChildren(...response.data.sessions.map((session) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.threadId = session.threadId;
      button.textContent = `${session.threadId} · ${session.updatedAt} · ${session.summary || "No messages"}`;
      button.addEventListener("click", () => void resumeThread(session.threadId));
      item.append(button);
      return item;
    }));
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

async function resumeThread(threadId: string): Promise<void> {
  renderProductState("loading");
  clearError();
  try {
    const resumed = await window.agent.resumeSession({ threadId });
    if (!resumed.ok) {
      showError(resumed.error, () => resumeThread(threadId), isStaleError(resumed.error.code) ? "stale" : "failed");
      return;
    }
    hydrateSession(resumed.data);
  } catch {
    showError(
      { code: "IPC_UNAVAILABLE", message: "Session recovery is unavailable.", action: "Retry Session recovery." },
      () => resumeThread(threadId),
    );
  }
}

fileButton.addEventListener("click", () => void selectDataset());

async function selectDataset(): Promise<void> {
  const previousState = currentProductState;
  fileButton.disabled = true;
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
    renderProductState("empty");
  } catch {
    showError(
      { code: "IPC_UNAVAILABLE", message: "The desktop shell is unavailable.", action: "Retry file selection." },
      () => selectDataset(),
    );
  } finally {
    fileButton.disabled = false;
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
  input.value = "";
  void startRun(request, true);
});

async function startRun(request: RunsStartInput, appendUser: boolean): Promise<void> {
  sendButton.disabled = true;
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
  }
}

approveButton.addEventListener("click", () => void resolveApproval("approve"));
rejectButton.addEventListener("click", () => void resolveApproval("reject"));

async function resolveApproval(decision: "approve" | "reject"): Promise<void> {
  if (!currentThreadId || !currentApproval) return;
  approveButton.disabled = true;
  rejectButton.disabled = true;
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
  }
}

stopButton.addEventListener("click", async () => {
  if (!activeRunId) return;
  stopButton.disabled = true;
  try {
    const response = await window.agent.cancelRun({ runId: activeRunId });
    if (!response.ok) showError(response.error, null);
  } catch {
    showError({ code: "IPC_UNAVAILABLE", message: "Cancel request failed.", action: "Check Runtime state before trying again." }, null);
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
}

function renderApproval(approval: ApprovalProjection | null): void {
  currentApproval = approval;
  approvalCard.hidden = approval === null;
  if (!approval) return;
  approvalAction.textContent = approval.actionType;
  approvalRisk.textContent = approval.riskSummary;
  approvalId.textContent = approval.approvalId;
  approvalExpires.textContent = approval.expiresAt;
  approveButton.disabled = false;
  rejectButton.disabled = false;
}

function hydrateSession(snapshot: SessionSnapshot): void {
  currentThreadId = snapshot.threadId;
  activeRunId = null;
  selectedDataset = undefined;
  lastRunRequest = null;
  renderDataset();
  messages.replaceChildren();
  charts.replaceChildren();
  renderTrace(projectTrace(snapshot.events, { useInputOrder: true }));
  for (const message of snapshot.messages) {
    const role = message.role;
    const content = message.content;
    if ((role === "user" || role === "assistant") && typeof content === "string") appendMessage(role, content);
  }
  const approval = pendingApproval(snapshot.events);
  renderApproval(approval);
  clearError();
  renderProductState(approval ? "waiting_approval" : snapshot.messages.length ? "completed" : "empty");
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
  statusView.textContent = state;
  stateHappening.textContent = description.happening;
  stateContinuation.textContent = description.canContinue;
  stateNextAction.textContent = description.nextAction;
  stateRefresh.hidden = state !== "stale";
}

function renderTrace(entries: TraceEntry[]): void {
  traceEmpty.hidden = entries.length > 0;
  eventList.replaceChildren(...entries.map((entry) => {
    const item = document.createElement("li");
    item.dataset.category = entry.category;
    item.dataset.sequence = String(entry.sequence);
    const detail = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `#${entry.sequence} ${entry.category} · ${entry.label}`;
    const fields = document.createElement("dl");
    appendField(fields, "Event", entry.eventType);
    if (entry.status) appendField(fields, "Status", entry.status);
    if (entry.errorCode) appendField(fields, "Error code", entry.errorCode);
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
  datasetView.textContent = dataset
    ? `${dataset.filename} · ${dataset.rowCount} rows · ${dataset.columnCount} columns`
    : "No file selected";
}

function appendMessage(role: "user" | "assistant", text: string): HTMLElement {
  const article = document.createElement("article");
  article.dataset.role = role;
  const label = document.createElement("strong");
  label.textContent = role === "user" ? "You" : "Agent";
  const content = document.createElement("p");
  content.textContent = text;
  article.append(label, content);
  messages.append(article);
  return article;
}

function showError(error: IpcError | null, retry: RetryAction | null = null, state: ProductState = "failed"): void {
  const structured = error ?? { code: "UNKNOWN_ERROR", message: "Unknown runtime error", action: "Review Trace and try again." };
  errorCode.textContent = structured.code;
  errorMessage.textContent = structured.message;
  errorAction.textContent = structured.action ?? "Review Trace and try again.";
  errorCard.hidden = false;
  currentRetry = state === "waiting_approval" ? null : retry;
  errorRetry.hidden = currentRetry === null;
  renderProductState(state);
}

function clearError(): void {
  errorCard.hidden = true;
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

renderProductState("loading");
void loadSessions();
