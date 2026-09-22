import type { AgentEvent, DatasetSummary } from "../shared/ipc";
import { renderChartSpec } from "./chart-renderer";
import { OrderedRunProjector, type RunProjection } from "./run-state";

const input = required<HTMLInputElement>("#run-input");
const sendButton = required<HTMLButtonElement>("#run-submit");
const stopButton = required<HTMLButtonElement>("#run-stop");
const fileButton = required<HTMLButtonElement>("#file-select");
const datasetView = required<HTMLElement>("#dataset-summary");
const statusView = required<HTMLElement>("#run-status");
const messages = required<HTMLElement>("#messages");
const charts = required<HTMLElement>("#charts");
const errorView = required<HTMLElement>("#run-error");
const eventList = required<HTMLOListElement>("#event-list");

let activeRunId: string | null = null;
let currentThreadId: string | undefined;
let selectedDataset: DatasetSummary | undefined;
const projectors = new Map<string, OrderedRunProjector>();
const pendingEvents = new Map<string, AgentEvent[]>();

window.agent.onAgentEvent((event) => {
  if (!event.run_id) {
    if (event.type === "runtime_error") showError(event.error);
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

fileButton.addEventListener("click", async () => {
  fileButton.disabled = true;
  clearError();
  try {
    const response = await window.agent.selectDataset(currentThreadId ? { threadId: currentThreadId } : {});
    if (!response.ok) return showError(response.error);
    if (response.data.status === "cancelled") return;
    currentThreadId = response.data.threadId;
    selectedDataset = response.data.dataset;
    renderDataset(selectedDataset);
  } catch {
    showError({ code: "IPC_UNAVAILABLE", message: "The desktop shell is unavailable." });
  } finally {
    fileButton.disabled = false;
  }
});

sendButton.addEventListener("click", async () => {
  const message = input.value.trim();
  if (!message) return showError({ code: "INVALID_RUN_INPUT", message: "Message is required." });
  sendButton.disabled = true;
  clearError();
  appendMessage("user", message);
  input.value = "";
  try {
    const response = await window.agent.startRun({
      message,
      ...(currentThreadId ? { threadId: currentThreadId } : {}),
      ...(selectedDataset ? { datasetId: selectedDataset.datasetId } : {}),
    });
    if (!response.ok) return showError(response.error);
    activeRunId = response.data.runId;
    currentThreadId = response.data.threadId;
    const projector = new OrderedRunProjector(activeRunId);
    projectors.set(activeRunId, projector);
    for (const event of pendingEvents.get(activeRunId) ?? []) projector.push(event);
    pendingEvents.delete(activeRunId);
    renderProjection(projector.snapshot());
  } catch {
    showError({ code: "IPC_UNAVAILABLE", message: "The desktop shell is unavailable." });
  } finally {
    sendButton.disabled = false;
  }
});

stopButton.addEventListener("click", async () => {
  if (!activeRunId) return;
  stopButton.disabled = true;
  const response = await window.agent.cancelRun({ runId: activeRunId });
  if (!response.ok) showError(response.error);
});

function renderProjection(projection: RunProjection): void {
  if (projection.runId !== activeRunId) return;
  statusView.textContent = projection.status;
  statusView.dataset.state = projection.status;
  stopButton.disabled = projection.status !== "running";
  eventList.replaceChildren(
    ...projection.events.map((event) => {
      const item = document.createElement("li");
      item.textContent = `${event.sequence} ${event.type}${event.error ? ` ${event.error.code}` : ""}`;
      return item;
    }),
  );
  charts.replaceChildren();
  for (const chart of projection.charts) {
    try {
      renderChartSpec(charts, chart.spec);
    } catch {
      showError({ code: "INVALID_CHART_SPEC", message: "Runtime returned an invalid Chart Spec." });
    }
  }
  if (projection.answer && !messages.querySelector(`[data-run-id="${projection.runId}"]`)) {
    const node = appendMessage("assistant", projection.answer);
    node.dataset.runId = projection.runId;
  }
  if (projection.error) showError(projection.error);
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

function showError(error: { code: string; message: string } | null): void {
  errorView.textContent = error ? `${error.code}: ${error.message}` : "Unknown runtime error";
}

function clearError(): void {
  errorView.textContent = "";
}

function required<T extends Element>(selector: string): T {
  const node = document.querySelector<T>(selector);
  if (!node) throw new Error(`Required renderer element is missing: ${selector}`);
  return node;
}
