import assert from "node:assert/strict";
import { existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { app, BrowserWindow, dialog } from "electron";
import type { RuntimeClient } from "../bridge/runtimeClient";
import type { AgentEvent } from "../shared/ipc";
import type { RuntimePaths } from "./runtime-paths";

const question = "各地区销售额总和是多少？";

async function waitFor(window: BrowserWindow, label: string, expression: string, timeoutMs = 30000): Promise<unknown> {
  return window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const started = Date.now();
    const timer = setInterval(() => {
      try {
        const value = (${expression});
        if (value) { clearInterval(timer); resolve(value); }
        else if (Date.now() - started > ${timeoutMs}) {
          clearInterval(timer);
          reject(new Error(${JSON.stringify(label)} + " timed out; state=" +
            document.querySelector("#run-status")?.textContent + "; error=" +
            document.querySelector("#error-code")?.textContent));
        }
      } catch (error) { clearInterval(timer); reject(error); }
    }, 25);
  })`);
}

async function click(window: BrowserWindow, selector: string): Promise<void> {
  const clicked = await window.webContents.executeJavaScript(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element || element.disabled || element.hidden) return false;
    element.click();
    return true;
  })()`);
  assert.equal(clicked, true, `Cannot click ${selector}`);
}

export async function runPackagedSmoke(
  window: BrowserWindow,
  runtime: RuntimeClient,
  paths: RuntimePaths,
  phase: "first" | "resume",
): Promise<void> {
  let step = "packaged startup";
  const resultPath = process.env.DATA_AGENT_PACKAGING_SMOKE_RESULT;
  assert.ok(resultPath, "Packaged smoke result path is missing");
  assert.equal(app.isPackaged, true, "M6.4 must run from the packaged executable");
  for (const file of [paths.bridgeScriptPath, paths.pythonExecutable, join(process.resourcesPath, "app.asar")]) {
    assert.ok(file && existsSync(file), `Packaged resource is missing: ${file}`);
  }

  const events: AgentEvent[] = [];
  runtime.onEvent((event) => events.push(event));
  try {
    step = "Main / Preload / Renderer initialization";
    assert.match(window.webContents.getURL(), /app\.asar/);
    await waitFor(window, step, `Boolean(window.agent && document.querySelector("#file-select") &&
      document.querySelector("#session-list") && document.querySelector("#run-status")?.textContent !== "loading")`);

    if (phase === "first") {
      const file = process.env.DATA_AGENT_PACKAGING_SMOKE_FILE;
      assert.ok(file && existsSync(file), `Smoke CSV is missing: ${file}`);
      const originalDialog = dialog.showOpenDialog;
      // Only the OS chooser is supplied with a deterministic answer. The UI,
      // Preload, IPC handler, DatasetRegistry and Python sidecar all remain real.
      (dialog as unknown as { showOpenDialog: (...args: unknown[]) => Promise<{ canceled: boolean; filePaths: string[] }> }).showOpenDialog = async (...args) => {
        const options = args.at(-1) as { filters?: Array<{ extensions?: string[] }> };
        assert.deepEqual(options.filters?.[0]?.extensions, ["csv", "xlsx"]);
        return { canceled: false, filePaths: [file] };
      };
      try {
        step = "CSV selection through Renderer / Preload / Main / Python";
        await click(window, "#file-select");
        await waitFor(window, step, `document.querySelector("#dataset-summary")?.textContent?.includes("sales.csv")`);
      } finally {
        (dialog as unknown as { showOpenDialog: typeof dialog.showOpenDialog }).showOpenDialog = originalDialog;
      }

      step = "Send and completed Runtime event projection";
      await window.webContents.executeJavaScript(`document.querySelector("#run-input").value = ${JSON.stringify(question)}`);
      await click(window, "#run-submit");
      await waitFor(window, "running UI state", `document.querySelector("#run-status")?.textContent === "running"`);
      await waitFor(window, "completed UI state", `document.querySelector("#run-status")?.textContent === "completed"`, 45000);
      const ui = await window.webContents.executeJavaScript(`({
        dataset: document.querySelector("#dataset-summary")?.textContent,
        answer: [...document.querySelectorAll('#messages [data-role="assistant"] p')].at(-1)?.textContent,
        status: document.querySelector("#run-status")?.textContent,
        trace: document.querySelector("#event-list")?.textContent,
        sequences: [...document.querySelectorAll("#event-list > li")].map((item) => Number(item.dataset.sequence)),
      })`);
      assert.match(String(ui.dataset), /sales\.csv.*5 rows/);
      assert.match(String(ui.answer), /1580/);
      assert.match(String(ui.trace), /route_selected/);
      assert.match(String(ui.trace), /tool_called/);
      assert.match(String(ui.trace), /run_completed/);
      assert.deepEqual(ui.sequences, [...ui.sequences].sort((a: number, b: number) => a - b));
      const completed = events.find((event) => event.type === "run_completed");
      assert.ok(completed?.thread_id && completed.trace_id, "Packaged Python sidecar did not emit a completed run");

      step = "Python SessionStore persistence";
      const sessions = await window.webContents.executeJavaScript("window.agent.listSessions()");
      assert.equal(sessions.ok, true);
      assert.ok(sessions.data.sessions.some((session: { threadId: string }) => session.threadId === completed.thread_id));
      writeFileSync(resultPath, JSON.stringify({
        phase, pid: process.pid, packaged: app.isPackaged, executable: process.execPath,
        resources: process.resourcesPath, userData: app.getPath("userData"),
        rendererUrl: window.webContents.getURL(), bridge: paths.bridgeScriptPath,
        python: paths.pythonExecutable, threadId: completed.thread_id,
        traceId: completed.trace_id, eventTypes: events.map((event) => event.type),
        dataset: ui.dataset, answer: ui.answer, status: ui.status, traceCount: ui.sequences.length,
      }, null, 2));
    } else {
      const threadId = process.env.DATA_AGENT_PACKAGING_SMOKE_THREAD;
      assert.ok(threadId, "Session thread id is missing for restart verification");
      step = "Session List after process restart";
      await waitFor(window, step, `Boolean(document.querySelector(${JSON.stringify(`[data-thread-id="${threadId}"]`)}))`);
      step = "Session Resume after process restart";
      await click(window, `[data-thread-id="${threadId}"]`);
      await waitFor(window, step, `document.querySelector("#messages")?.textContent?.includes(${JSON.stringify(question)}) &&
        document.querySelector("#messages")?.textContent?.includes("1580") &&
        document.querySelector("#run-status")?.textContent === "completed"`);
      const ui = await window.webContents.executeJavaScript(`({
        messages: document.querySelector("#messages")?.textContent,
        status: document.querySelector("#run-status")?.textContent,
        traceCount: document.querySelectorAll("#event-list > li").length,
      })`);
      assert.ok(ui.traceCount > 0, "Hydrated Session has no Runtime events");
      assert.equal(events.some((event) => event.type === "run_started"), false, "Resume unexpectedly started a new run");
      const snapshot = await window.webContents.executeJavaScript(`window.agent.getSession({ threadId: ${JSON.stringify(threadId)} })`);
      assert.equal(snapshot.ok, true);
      assert.equal(snapshot.data.threadId, threadId);
      writeFileSync(resultPath, JSON.stringify({
        phase, pid: process.pid, packaged: app.isPackaged, executable: process.execPath,
        resources: process.resourcesPath, userData: app.getPath("userData"),
        rendererUrl: window.webContents.getURL(), threadId,
        status: ui.status, traceCount: ui.traceCount,
        messageCount: snapshot.data.messages.length, traceIds: snapshot.data.traceIds,
        newRuntimeEvents: events.length,
      }, null, 2));
    }
  } catch (error) {
    throw new Error(`M6.4 packaged smoke failed at ${step}: ${error instanceof Error ? error.stack : String(error)}`);
  }
}
