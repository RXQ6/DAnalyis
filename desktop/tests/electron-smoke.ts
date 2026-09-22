import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { app } from "electron";
import { RuntimeProcessManager } from "../src/bridge/processManager";
import { RuntimeClient } from "../src/bridge/runtimeClient";
import type { AgentEvent } from "../src/bridge/protocol";
import { IPC_CHANNELS } from "../src/shared/ipc";
import { createWindow } from "../src/main/create-window";
import { registerIpcHandlers } from "../src/main/ipc/register-handlers";

async function run(): Promise<void> {
  const electronData = mkdtempSync(join(tmpdir(), "data-agent-electron-"));
  app.setPath("userData", electronData);
  app.setPath("sessionData", electronData);
  app.disableHardwareAcceleration();
  const pythonExecutable = process.env.DATA_AGENT_PYTHON;
  assert.ok(pythonExecutable, "DATA_AGENT_PYTHON is required for the M2 smoke test");
  const repoRoot = resolve(__dirname, "../../..");
  const manager = new RuntimeProcessManager({
    repoRoot,
    pythonExecutable,
    environment: { DESKTOP_BRIDGE_WORKER_DELAY_MS: "200" },
  });
  const runtime = new RuntimeClient(manager);
  const observedEvents: AgentEvent[] = [];
  runtime.onEvent((event) => observedEvents.push(event));
  registerIpcHandlers(runtime);
  await app.whenReady();
  await manager.start();
  const window = await createWindow({ show: false });
  runtime.onEvent((event) => window.webContents.send(IPC_CHANNELS.agentEvent, event));

  const projection = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      const events = [];
      let startResult = null;
      const timeout = setTimeout(() => reject(new Error("runtime event timeout")), 10000);
      const finish = () => {
        if (startResult && events.some((event) => event.type === "run_completed")) {
          clearTimeout(timeout);
          resolve({ startResult, events });
        }
      };
      const unsubscribe = window.agent.onAgentEvent((event) => {
        events.push(event);
        finish();
      });
      window.agent.startRun({ message: "hello" }).then((value) => {
        startResult = value;
        finish();
      });
    })
  `);
  assert.equal(projection.startResult.ok, true);
  assert.match(projection.startResult.data.runId, /^run_/);
  assert.match(projection.startResult.data.threadId, /^thread_/);
  assert.match(projection.startResult.data.traceId, /^trace_/);
  assert.deepEqual(
    projection.events.map((event: { sequence: number }) => event.sequence),
    projection.events.map((event: { sequence: number }) => event.sequence).sort((a: number, b: number) => a - b),
  );
  assert.ok(projection.events.some((event: { type: string }) => event.type === "route_selected"));
  assert.ok(projection.events.some((event: { type: string }) => event.type === "run_completed"));
  const chatProjection = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      document.querySelector('#run-input').value = 'hello';
      document.querySelector('#run-submit').click();
      const timeout = setTimeout(() => reject(new Error('chat projection timeout')), 10000);
      const timer = setInterval(() => {
        const status = document.querySelector('#run-status').textContent;
        const agent = document.querySelector('[data-role="assistant"] p')?.textContent;
        if (status === 'completed' && agent) {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve({ status, agent, events: document.querySelector('#event-list').textContent });
        }
      }, 20);
    })
  `);
  assert.equal(chatProjection.status, "completed");
  assert.match(chatProjection.agent, /你好|Desktop Runtime/);
  assert.match(chatProjection.events, /run_completed/);

  const uiRun = observedEvents.filter((event) => event.type === "run_completed").at(-1);
  assert.ok(uiRun);
  window.webContents.send(IPC_CHANNELS.agentEvent, {
    protocol_version: 1,
    request_id: uiRun.request_id,
    run_id: uiRun.run_id,
    thread_id: uiRun.thread_id,
    trace_id: uiRun.trace_id,
    sequence: Number(uiRun.sequence) + 1,
    type: "chart_ready",
    payload: {
      spec: { version: "1.0", chartType: "bar", title: "Sales", data: { values: [{ x: "East", y: 10 }] } },
      artifact: { mediaType: "image/svg+xml", width: 800, height: 480, sha256: "abc" },
    },
    error: null,
  });
  const renderedChart = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('chart projection timeout')), 3000);
      const timer = setInterval(() => {
        const svg = document.querySelector('#charts svg');
        if (svg) {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve(svg.getAttribute('aria-label'));
        }
      }, 20);
    })
  `);
  assert.equal(renderedChart, "Sales");

  const invalid = await window.webContents.executeJavaScript(
    "window.agent.startRun({ message: '   ' })",
  );
  assert.equal(invalid.ok, false);
  assert.equal(invalid.error.code, "INVALID_RUN_INPUT");

  await window.webContents.executeJavaScript(`
    document.querySelector('#run-input').value = 'hello';
    document.querySelector('#run-submit').click();
    new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('run did not start')), 5000);
      const timer = setInterval(() => {
        if (document.querySelector('#run-status').textContent === 'running') {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve(true);
        }
      }, 10);
    })
  `);
  manager.kill();
  const crashProjection = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("runtime_error was not rendered")), 5000);
      const timer = setInterval(() => {
        const text = document.querySelector("#run-error").textContent;
        if (text.includes("RUNTIME_PROCESS_EXIT")) {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve({ text, bodyPresent: Boolean(document.body) });
        }
      }, 20);
    })
  `);
  assert.equal(crashProjection.bodyPresent, true);
  assert.match(crashProjection.text, /RUNTIME_PROCESS_EXIT/);

  window.destroy();
  manager.stop();
  app.quit();
}

void run().catch((error: unknown) => {
  console.error(error);
  app.exit(1);
});
