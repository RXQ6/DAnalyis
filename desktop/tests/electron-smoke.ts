import assert from "node:assert/strict";
import { resolve } from "node:path";
import { app } from "electron";
import { RuntimeProcessManager } from "../src/bridge/processManager";
import { RuntimeClient } from "../src/bridge/runtimeClient";
import { IPC_CHANNELS } from "../src/shared/ipc";
import { createWindow } from "../src/main/create-window";
import { registerIpcHandlers } from "../src/main/ipc/register-handlers";

async function run(): Promise<void> {
  const pythonExecutable = process.env.DATA_AGENT_PYTHON;
  assert.ok(pythonExecutable, "DATA_AGENT_PYTHON is required for the M2 smoke test");
  const repoRoot = resolve(__dirname, "../../..");
  const manager = new RuntimeProcessManager({
    repoRoot,
    pythonExecutable,
    environment: { DESKTOP_BRIDGE_WORKER_DELAY_MS: "200" },
  });
  const runtime = new RuntimeClient(manager);
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
  const renderedEvents = await window.webContents.executeJavaScript(
    "Array.from(document.querySelectorAll('#event-list li')).map((item) => item.textContent)",
  );
  assert.ok(renderedEvents.some((text: string) => text.includes("route_selected")));
  assert.ok(renderedEvents.some((text: string) => text.includes("run_completed")));

  const invalid = await window.webContents.executeJavaScript(
    "window.agent.startRun({ message: '   ' })",
  );
  assert.equal(invalid.ok, false);
  assert.equal(invalid.error.code, "INVALID_RUN_INPUT");

  const crashRun = await window.webContents.executeJavaScript(
    "window.agent.startRun({ message: 'hello' })",
  );
  assert.equal(crashRun.ok, true);
  manager.kill();
  const crashProjection = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("runtime_error was not rendered")), 5000);
      const timer = setInterval(() => {
        const text = document.querySelector("#event-list").textContent;
        if (text.includes("runtime_error")) {
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
