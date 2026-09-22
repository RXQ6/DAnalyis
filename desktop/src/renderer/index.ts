type ProjectedEvent = {
  run_id: string | null;
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
  error: { code: string; message: string } | null;
};

const input = document.querySelector<HTMLInputElement>("#run-input");
const sendButton = document.querySelector<HTMLButtonElement>("#run-submit");
const stopButton = document.querySelector<HTMLButtonElement>("#run-stop");
const result = document.querySelector<HTMLElement>("#run-result");
const eventList = document.querySelector<HTMLOListElement>("#event-list");

if (!input || !sendButton || !stopButton || !result || !eventList) {
  throw new Error("Required renderer elements are missing.");
}

let activeRunId: string | null = null;
const eventsByRun = new Map<string, ProjectedEvent[]>();
const terminalRuns = new Set<string>();

function renderEvents(runId: string): void {
  const events = [...(eventsByRun.get(runId) ?? [])].sort(
    (left, right) => left.sequence - right.sequence,
  );
  eventList!.replaceChildren(
    ...events.map((event) => {
      const item = document.createElement("li");
      item.textContent = `${event.sequence} ${event.type} ${JSON.stringify(event.error ?? event.payload)}`;
      return item;
    }),
  );
}

window.agent.onAgentEvent((event) => {
  const key = event.run_id ?? "runtime";
  const events = eventsByRun.get(key) ?? [];
  if (!events.some((item) => item.sequence === event.sequence)) {
    events.push(event);
    eventsByRun.set(key, events);
  }
  if (event.run_id && (!activeRunId || event.type === "run_started")) {
    activeRunId = event.run_id;
  }
  if (activeRunId === key || key === "runtime") {
    renderEvents(key);
  }
  if (["run_completed", "run_failed", "run_cancelled", "approval_required"].includes(event.type)) {
    if (event.run_id) terminalRuns.add(event.run_id);
    stopButton.disabled = true;
  }
});

sendButton.addEventListener("click", async () => {
  sendButton.disabled = true;
  result.textContent = "Starting…";
  eventList!.replaceChildren();
  try {
    const response = await window.agent.startRun({ message: input.value });
    if (response.ok) {
      activeRunId = response.data.runId;
      stopButton.disabled = terminalRuns.has(activeRunId);
      result.textContent = JSON.stringify(response.data);
      renderEvents(activeRunId);
    } else {
      result.textContent = `${response.error.code}: ${response.error.message}`;
    }
  } catch {
    result.textContent = "IPC_UNAVAILABLE: The desktop shell is unavailable.";
  } finally {
    sendButton.disabled = false;
  }
});

stopButton.addEventListener("click", async () => {
  if (!activeRunId) return;
  stopButton.disabled = true;
  const response = await window.agent.cancelRun({ runId: activeRunId });
  result.textContent = response.ok
    ? JSON.stringify(response.data)
    : `${response.error.code}: ${response.error.message}`;
});
