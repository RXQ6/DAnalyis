import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { app, BrowserWindow, ipcMain } from "electron";
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
    environment: {
      DESKTOP_BRIDGE_WORKER_DELAY_MS: "200",
      DATA_AGENT_RUNTIME_DIR: join(electronData, "runtime"),
    },
  });
  const runtime = new RuntimeClient(manager);
  const observedEvents: AgentEvent[] = [];
  runtime.onEvent((event) => observedEvents.push(event));
  registerIpcHandlers(runtime);
  await app.whenReady();
  await manager.start();
  let window = await createWindow({ show: false });
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
        const status = document.querySelector('#run-status').dataset.state;
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
  assert.match(chatProjection.events, /分析已完成/);
  assert.doesNotMatch(chatProjection.events, /run_completed|thread_|trace_|tool_args/);

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
  window.show();
  const chartCard = await window.webContents.executeJavaScript(`({
    title: document.querySelector('#charts .chart-card figcaption')?.textContent,
    svgInsideCard: Boolean(document.querySelector('#charts .chart-card .chart-card-visual svg')),
    chartScrollsWithinCard: (() => {
      const visual = document.querySelector('#charts .chart-card .chart-card-visual');
      return visual && visual.scrollWidth > visual.clientWidth &&
        getComputedStyle(visual).overflowX === 'auto';
    })(),
    noPageOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
    hasAxesAndGrid: Boolean(document.querySelector('#charts svg .axis-title') && document.querySelector('#charts svg .grid-line')),
    hasDataTable: Boolean(document.querySelector('#charts .chart-data-details table td')),
    hasTypeLabel: document.querySelector('#charts .chart-type')?.textContent,
    tooltipOnFocus: (() => {
      const mark = document.querySelector('#charts svg .data-mark');
      mark?.focus();
      const shown = !document.querySelector('#charts .chart-tooltip')?.hidden;
      mark?.blur();
      return shown;
    })(),
  })`);
  assert.equal(chartCard.title, "Sales");
  assert.equal(chartCard.svgInsideCard, true);
  assert.equal(chartCard.chartScrollsWithinCard, true);
  assert.equal(chartCard.noPageOverflow, true);
  assert.equal(chartCard.hasAxesAndGrid, true);
  assert.equal(chartCard.hasDataTable, true);
  assert.equal(chartCard.hasTypeLabel, "分类比较");
  assert.equal(chartCard.tooltipOnFocus, true);
  if (process.env.DATA_AGENT_CAPTURE_UI === "1") {
    window.show();
    window.setContentSize(1280, 800);
    await window.webContents.executeJavaScript(`document.querySelector('#charts .chart-card').scrollIntoView({ block: 'center' })`);
    const path = join(electronData, "phase14-chart.png");
    writeFileSync(path, (await window.webContents.capturePage()).toPNG());
    console.log(`Phase 1.4 chart screenshot: ${path}`);
  }
  const traceProjection = await window.webContents.executeJavaScript(`({
    sequences: [...document.querySelectorAll('#event-list > li')].map((item) => Number(item.dataset.sequence)),
    text: document.querySelector('#event-list').textContent,
  })`);
  assert.deepEqual(traceProjection.sequences, [...traceProjection.sequences].sort((a: number, b: number) => a - b));
  assert.equal(traceProjection.text.includes("hello"), false);
  assert.equal(traceProjection.text.includes("arguments"), false);

  window.webContents.send(IPC_CHANNELS.agentEvent, {
    protocol_version: 1,
    request_id: uiRun.request_id,
    run_id: uiRun.run_id,
    thread_id: uiRun.thread_id,
    trace_id: uiRun.trace_id,
    sequence: Number(uiRun.sequence) + 2,
    type: "run_failed",
    payload: { status: "failed", partial: true, missing: ["Regional breakdown is unavailable."] },
    error: { code: "PARTIAL_TOOL_FAILURE", message: "one tool failed" },
  });
  const partialProjection = await window.webContents.executeJavaScript(`({
    state: document.querySelector('#run-status').dataset.state,
    missing: document.querySelector('#error-message').textContent,
    retryVisible: !document.querySelector('#error-retry').hidden,
    chartPresent: Boolean(document.querySelector('#charts svg')),
    answerPresent: Boolean(document.querySelector('[data-role="assistant"] p')),
    errorVisualState: document.querySelector('#error-card').dataset.state,
    stateLabel: document.querySelector('#state-label').textContent,
  })`);
  assert.equal(partialProjection.state, "partial");
  assert.match(partialProjection.missing, /Regional breakdown/);
  assert.equal(partialProjection.retryVisible, true);
  assert.equal(partialProjection.chartPresent, true);
  assert.equal(partialProjection.answerPresent, true);
  assert.equal(partialProjection.errorVisualState, "partial");
  assert.equal(partialProjection.stateLabel, "部分完成");

  const partialRetry = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      document.querySelector('#error-retry').click();
      const timeout = setTimeout(() => reject(new Error('partial retry timeout')), 10000);
      const timer = setInterval(() => {
        if (document.querySelector('#run-status').dataset.state === 'completed' && document.querySelector('#error-card').hidden) {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve(true);
        }
      }, 20);
    })
  `);
  assert.equal(partialRetry, true);
  const retriedCompleted = observedEvents.filter((event) => event.type === "run_completed").at(-1);
  assert.ok(retriedCompleted);
  assert.equal(retriedCompleted.thread_id, uiRun.thread_id);
  assert.notEqual(retriedCompleted.trace_id, uiRun.trace_id);

  window.webContents.send(IPC_CHANNELS.agentEvent, {
    protocol_version: 1,
    request_id: retriedCompleted.request_id,
    run_id: retriedCompleted.run_id,
    thread_id: retriedCompleted.thread_id,
    trace_id: retriedCompleted.trace_id,
    sequence: Number(retriedCompleted.sequence) + 1,
    type: "run_failed",
    payload: { status: "failed", partial: false },
    error: { code: "RECOVERABLE_FAILURE", message: "retry is available" },
  });
  const failedRetry = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('failed retry timeout')), 10000);
      let sawFailure = false;
      const waitForFailure = setInterval(() => {
        if (document.querySelector('#run-status').dataset.state === 'failed' && !document.querySelector('#error-retry').hidden) {
          sawFailure = true;
          clearInterval(waitForFailure);
          document.querySelector('#error-retry').click();
        }
      }, 20);
      const waitForCompletion = setInterval(() => {
        if (sawFailure && document.querySelector('#run-status').dataset.state === 'completed' && document.querySelector('#error-card').hidden) {
          clearInterval(waitForCompletion);
          clearTimeout(timeout);
          resolve(true);
        }
      }, 20);
    })
  `);
  assert.equal(failedRetry, true);

  const invalid = await window.webContents.executeJavaScript(
    "window.agent.startRun({ message: '   ' })",
  );
  assert.equal(invalid.ok, false);
  assert.equal(invalid.error.code, "INVALID_RUN_INPUT");

  const sessionProjection = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      document.querySelector('#sessions-refresh').click();
      const timeout = setTimeout(() => reject(new Error('session list timeout')), 5000);
      const timer = setInterval(() => {
        const text = document.querySelector('#session-list').textContent;
        if (document.querySelector('#session-list button')) {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve(text);
        }
      }, 20);
    })
  `);
  assert.doesNotMatch(sessionProjection, /thread_|trace_|\{"metric"/);
  const resumedMessages = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      document.querySelector('#session-list button').click();
      const timeout = setTimeout(() => reject(new Error('session resume timeout')), 5000);
      const timer = setInterval(() => {
        const text = document.querySelector('#messages').textContent;
        if (text.includes('hello')) {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve(text);
        }
      }, 20);
    })
  `);
  assert.match(resumedMessages, /hello/);
  const isolated = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      const target = document.querySelector('[data-thread-id="${projection.startResult.data.threadId}"]');
      target.click();
      const timeout = setTimeout(() => reject(new Error('session isolation timeout')), 5000);
      const timer = setInterval(() => {
        if (target.getAttribute('aria-current') === 'true' && document.querySelector('#header-session').textContent === 'hello') {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve(document.querySelector('#event-list').textContent);
        }
      }, 20);
    })
  `);
  const priorEventText = String(isolated);
  window.webContents.send(IPC_CHANNELS.agentEvent, {
    protocol_version: 1,
    request_id: "req_cross_session",
    run_id: null,
    thread_id: uiRun.thread_id,
    trace_id: null,
    sequence: 0,
    type: "runtime_error",
    payload: { status: "failed" },
    error: { code: "CROSS_SESSION", message: "must be ignored" },
  });
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 50));
  const isolationAfter = await window.webContents.executeJavaScript(`({
    events: document.querySelector('#event-list').textContent,
    error: document.querySelector('#error-code').textContent,
  })`);
  assert.equal(isolationAfter.events, priorEventText);
  assert.equal(isolationAfter.error.includes("CROSS_SESSION"), false);
  window.webContents.send(IPC_CHANNELS.agentEvent, {
    protocol_version: 1,
    request_id: "req_stale_session",
    run_id: null,
    thread_id: projection.startResult.data.threadId,
    trace_id: null,
    sequence: 0,
    type: "runtime_error",
    payload: { status: "failed" },
    error: { code: "session_not_found", message: "session is stale" },
  });
  const staleProjection = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('stale state timeout')), 5000);
      const timer = setInterval(() => {
        if (document.querySelector('#run-status').dataset.state === 'stale') {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve({
            refreshVisible: !document.querySelector('#state-refresh').hidden,
            action: document.querySelector('#state-next-action').textContent,
            visualState: document.querySelector('#product-state').dataset.state,
            errorVisualState: document.querySelector('#error-card').dataset.state,
          });
        }
      }, 20);
    })
  `);
  assert.equal(staleProjection.refreshVisible, true);
  assert.equal(staleProjection.visualState, "stale");
  assert.equal(staleProjection.errorVisualState, "stale");
  assert.match(staleProjection.action, /刷新/);
  await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      document.querySelector('#state-refresh').click();
      const timeout = setTimeout(() => reject(new Error('stale refresh timeout')), 5000);
      const timer = setInterval(() => {
        if (document.querySelector('#run-status').dataset.state === 'completed') {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve(true);
        }
      }, 20);
    })
  `);

  const rejectedApproval = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      document.querySelector('#run-input').value = '分析数据并执行外部写操作';
      document.querySelector('#run-submit').click();
      const timeout = setTimeout(() => reject(new Error(
        'approval UI timeout state=' + document.querySelector('#run-status').textContent +
        ' events=' + document.querySelector('#event-list').textContent +
        ' error=' + document.querySelector('#error-code').textContent
      )), 10000);
      let submitted = false;
      const timer = setInterval(() => {
        const card = document.querySelector('#approval-card');
        if (!card.hidden && !submitted) {
          submitted = true;
          const snapshot = {
            action: document.querySelector('#approval-action').textContent,
            risk: document.querySelector('#approval-risk').textContent,
            approvalId: document.querySelector('#approval-id').textContent,
            body: card.innerText,
            idHidden: document.querySelector('#approval-id').hidden,
            retryHidden: document.querySelector('#error-retry').hidden,
            trace: document.querySelector('#event-list').textContent,
          };
          document.querySelector('#approval-reject').click();
          const terminal = setInterval(() => {
            if (document.querySelector('#run-status').dataset.state === 'failed') {
              clearInterval(terminal);
              clearInterval(timer);
              clearTimeout(timeout);
              resolve(snapshot);
            }
          }, 20);
        }
      }, 20);
    })
  `);
  assert.equal(rejectedApproval.action, "向外部服务写入数据");
  assert.match(rejectedApproval.risk, /高风险/);
  assert.match(rejectedApproval.approvalId, /^approval_/);
  assert.equal(rejectedApproval.idHidden, true);
  assert.equal(rejectedApproval.body.includes(rejectedApproval.approvalId), false);
  assert.equal(rejectedApproval.body.includes("分析数据并执行外部写操作"), false);
  assert.equal(rejectedApproval.trace.includes("分析数据并执行外部写操作"), false);
  assert.equal(rejectedApproval.retryHidden, true);

  await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      document.querySelector('#run-input').value = '分析数据并执行外部写操作';
      document.querySelector('#run-submit').click();
      const timeout = setTimeout(() => reject(new Error('pending approval timeout')), 10000);
      const timer = setInterval(() => {
        if (!document.querySelector('#approval-card').hidden) {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve(true);
        }
      }, 20);
    })
  `);
  const pendingForRestart = observedEvents.filter((event) => event.type === "approval_required").at(-1);
  assert.ok(pendingForRestart?.thread_id);
  await new Promise<void>((resolveReload) => {
    window.webContents.once("did-finish-load", () => resolveReload());
    window.webContents.reload();
  });
  const approvedProjection = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('approval restart resume timeout')), 10000);
      let selected = false;
      let submitted = false;
      const timer = setInterval(() => {
        const target = document.querySelector('[data-thread-id="${pendingForRestart.thread_id}"]');
        if (target && !selected) {
          selected = true;
          target.click();
        }
        if (!document.querySelector('#approval-card').hidden && !submitted) {
          submitted = true;
          document.querySelector('#approval-approve').click();
        }
        if (document.querySelector('#run-status').dataset.state === 'completed') {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve(document.querySelector('#event-list').textContent);
        }
      }, 20);
    })
  `);
  assert.match(approvedProjection, /确认已处理/);
  assert.ok(observedEvents.some((event) =>
    event.type === "approval_resolved" && event.payload.status === "approved" && event.payload.executed === true,
  ));

  let hydrateAttempts = 0;
  ipcMain.removeHandler(IPC_CHANNELS.sessionsResume);
  ipcMain.handle(IPC_CHANNELS.sessionsResume, async (_event, input: { threadId: string }) => {
    hydrateAttempts += 1;
    if (hydrateAttempts === 1) {
      return { ok: false, error: { code: "SESSION_HYDRATE_FAILED", message: "temporary recovery failure" } };
    }
    return {
      ok: true,
      data: {
        threadId: input.threadId,
        messages: [{ role: "assistant", content: "Recovered after retry" }],
        events: [],
        traceIds: [],
      },
    };
  });
  const retryProjection = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      document.querySelector('#session-list button').click();
      const timeout = setTimeout(() => reject(new Error('hydrate retry timeout')), 5000);
      const timer = setInterval(() => {
        const retry = document.querySelector('#error-retry');
        if (!retry.hidden && document.querySelector('#error-code').textContent.includes('SESSION_HYDRATE_FAILED')) {
          retry.click();
        }
        if (document.querySelector('#messages').textContent.includes('Recovered after retry')) {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve({ error: document.querySelector('#error-code').textContent, retryHidden: retry.hidden });
        }
      }, 20);
    })
  `);
  assert.equal(hydrateAttempts, 2);
  assert.equal(retryProjection.error, "");
  assert.equal(retryProjection.retryHidden, true);

  const cancelledProjection = await window.webContents.executeJavaScript(`
    new Promise((resolve, reject) => {
      document.querySelector('#run-input').value = 'hello';
      document.querySelector('#run-submit').click();
      const timeout = setTimeout(() => reject(new Error('cancelled state timeout')), 5000);
      const timer = setInterval(() => {
        const state = document.querySelector('#run-status').dataset.state;
        if (state === 'running') document.querySelector('#run-stop').click();
        if (state === 'cancelled') {
          clearInterval(timer);
          clearTimeout(timeout);
          resolve({
            state,
            happening: document.querySelector('#state-happening').textContent,
            next: document.querySelector('#state-next-action').textContent,
          });
        }
      }, 10);
    })
  `);
  assert.equal(cancelledProjection.state, "cancelled");
  assert.match(cancelledProjection.happening, /已停止/);
  assert.ok(cancelledProjection.next);

  await window.webContents.executeJavaScript(`
    document.querySelector('#run-input').value = 'hello';
    document.querySelector('#run-submit').click();
    new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('run did not start')), 5000);
      const timer = setInterval(() => {
        if (document.querySelector('#run-status').dataset.state === 'running') {
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
        const text = document.querySelector("#error-code").textContent;
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

  const staticWindow = new BrowserWindow({
    width: 800,
    height: 600,
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  await staticWindow.loadFile(join(repoRoot, "desktop", "src", "renderer", "index.html"));
  const staticPage = await staticWindow.webContents.executeJavaScript(`({
    noteVisible: getComputedStyle(document.querySelector('#desktop-only-note')).display !== 'none',
    appHidden: getComputedStyle(document.querySelector('#app-shell')).display === 'none',
    text: document.querySelector('#desktop-only-note').textContent,
  })`);
  assert.equal(staticPage.noteVisible, true);
  assert.equal(staticPage.appHidden, true);
  assert.match(staticPage.text, /请启动桌面应用/);
  staticWindow.destroy();

  window.destroy();
  manager.stop();
  app.quit();
}

void run().catch((error: unknown) => {
  console.error(error);
  app.exit(1);
});
