import assert from "node:assert/strict";
import test from "node:test";
import { resolve } from "node:path";
import { RuntimeProcessManager } from "../src/bridge/processManager";
import { RuntimeClient } from "../src/bridge/runtimeClient";
import type { AgentEvent } from "../src/bridge/protocol";

const pythonExecutable = process.env.DATA_AGENT_PYTHON;
const repoRoot = resolve(__dirname, "../../..");

function waitFor(events: AgentEvent[], type: string, timeoutMs = 15000): Promise<AgentEvent> {
  return new Promise((resolveEvent, reject) => {
    const started = Date.now();
    const timer = setInterval(() => {
      const event = events.find((item) => item.type === type);
      if (event) {
        clearInterval(timer);
        resolveEvent(event);
      } else if (Date.now() - started > timeoutMs) {
        clearInterval(timer);
        reject(new Error(`timed out waiting for ${type}; events=${JSON.stringify(events)}`));
      }
    }, 10);
  });
}

test("Python Runtime streams ordered events with real ids", { skip: !pythonExecutable }, async () => {
  const manager = new RuntimeProcessManager({ repoRoot, pythonExecutable });
  const runtime = new RuntimeClient(manager);
  const events: AgentEvent[] = [];
  runtime.onEvent((event) => events.push(event));
  try {
    const run = await runtime.startRun("hello");
    await waitFor(events, "run_completed");
    assert.match(run.runId, /^run_/);
    assert.match(run.threadId, /^thread_/);
    assert.match(run.traceId, /^trace_/);
    assert.deepEqual(events.map((event) => event.sequence), events.map((event) => event.sequence).sort((a, b) => a - b));
  } finally {
    manager.stop();
  }
});

test("dataset registration returns only public summary and binds dataset id to its thread", { skip: !pythonExecutable }, async () => {
  const manager = new RuntimeProcessManager({ repoRoot, pythonExecutable });
  const runtime = new RuntimeClient(manager);
  try {
    const registered = await runtime.registerDataset(resolve(repoRoot, "tests/fixtures/sales.csv"));
    assert.match(registered.threadId, /^thread_/);
    assert.match(String(registered.dataset.datasetId), /^ds_/);
    assert.equal(registered.dataset.filename, "sales.csv");
    assert.equal(registered.dataset.rowCount, 5);
    assert.equal("path" in registered.dataset, false);

    const events: AgentEvent[] = [];
    runtime.onEvent((event) => events.push(event));
    const run = await runtime.startRun(
      "按地区生成销售额柱状图",
      registered.threadId,
      String(registered.dataset.datasetId),
    );
    const chart = await waitFor(events, "chart_ready");
    const completed = await waitFor(events, "run_completed");
    assert.equal(run.threadId, registered.threadId);
    assert.equal((chart.payload.spec as Record<string, unknown>).chartType, "bar");
    assert.equal("path" in (chart.payload.artifact as Record<string, unknown>), false);
    assert.equal(String(completed.payload.response).includes("sales.csv"), false);
    assert.equal(String(completed.payload.response).includes(".svg"), false);
  } finally {
    manager.stop();
  }
});

test("run.cancel reaches Python and no business event follows run_cancelled", { skip: !pythonExecutable }, async () => {
  const manager = new RuntimeProcessManager({
    repoRoot,
    pythonExecutable,
    environment: { DESKTOP_BRIDGE_WORKER_DELAY_MS: "1000" },
  });
  const runtime = new RuntimeClient(manager);
  const events: AgentEvent[] = [];
  runtime.onEvent((event) => events.push(event));
  const run = await runtime.startRun("hello");
  const cancelled = await runtime.cancelRun(run.runId);
  assert.equal(cancelled.status, "cancelled");
  await waitFor(events, "run_cancelled");
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 200));
  assert.equal(events.at(-1)?.type, "run_cancelled");
  assert.deepEqual(events.map((event) => event.sequence), events.map((event) => event.sequence).sort((a, b) => a - b));
  manager.stop();
});

test("unexpected Python exit becomes runtime_error instead of crashing Main", { skip: !pythonExecutable }, async () => {
  const manager = new RuntimeProcessManager({
    repoRoot,
    pythonExecutable,
    environment: { DESKTOP_BRIDGE_WORKER_DELAY_MS: "1000" },
  });
  const runtime = new RuntimeClient(manager);
  const events: AgentEvent[] = [];
  runtime.onEvent((event) => events.push(event));
  await runtime.startRun("hello");
  manager.kill();
  const event = await waitFor(events, "runtime_error");
  assert.equal(event.error?.code, "RUNTIME_PROCESS_EXIT");
});
