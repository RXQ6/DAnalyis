import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { app, BrowserWindow, dialog } from "electron";
import { RuntimeProcessManager } from "../src/bridge/processManager";
import { RuntimeClient } from "../src/bridge/runtimeClient";
import type { AgentEvent } from "../src/bridge/protocol";
import { IPC_CHANNELS } from "../src/shared/ipc";
import { createWindow } from "../src/main/create-window";
import { registerIpcHandlers } from "../src/main/ipc/register-handlers";
import { resolveRuntimePaths } from "../src/main/runtime-paths";
import { secureWebPreferences } from "../src/main/window-options";

const projectRoot = resolve(__dirname, "../../..");
const packagedAssets = process.env.DATA_AGENT_E2E_PACKAGED === "1";

async function waitFor(window: BrowserWindow, label: string, predicate: string, timeout = 12000): Promise<unknown> {
  return window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const started = Date.now();
    const timer = setInterval(() => {
      try {
        const value = (${predicate});
        if (value) { clearInterval(timer); resolve(value); }
        else if (Date.now() - started > ${timeout}) {
          clearInterval(timer);
          reject(new Error(${JSON.stringify(`${label} timed out`)} +
            " state=" + document.querySelector("#run-status")?.textContent +
            " error=" + document.querySelector("#error-code")?.textContent +
            " trace=" + document.querySelector("#event-list")?.textContent));
        }
      } catch (error) { clearInterval(timer); reject(error); }
    }, 20);
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

async function fillAndSend(window: BrowserWindow, message: string): Promise<void> {
  await window.webContents.executeJavaScript(`document.querySelector("#run-input").value = ${JSON.stringify(message)}`);
  await click(window, "#run-submit");
}

async function run(): Promise<void> {
  const pythonExecutable = process.env.DATA_AGENT_PYTHON;
  assert.ok(pythonExecutable, "Set DATA_AGENT_PYTHON for the Electron E2E test");
  const electronData = mkdtempSync(join(tmpdir(), "data-agent-m6-e2e-"));
  const xlsx = join(electronData, "sample.xlsx");
  const fixtureScript = "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[2]); from eval_agent import create_average_xlsx; create_average_xlsx(Path(sys.argv[1]))";
  const fixture = spawnSync(pythonExecutable, ["-c", fixtureScript, xlsx, join(projectRoot, "tests")], {
    cwd: projectRoot,
    encoding: "utf8",
    windowsHide: true,
  });
  assert.equal(fixture.status, 0, `XLSX fixture generation failed: ${fixture.stderr}`);
  const csv = join(projectRoot, "tests", "fixtures", "sales.csv");
  assert.ok(existsSync(csv));

  app.setPath("userData", electronData);
  app.setPath("sessionData", electronData);
  app.disableHardwareAcceleration();
  const resources = join(projectRoot, "desktop", "release", "win-unpacked", "resources");
  const mainDirectory = join(projectRoot, "desktop", "dist", "src", "main");
  const paths = resolveRuntimePaths(packagedAssets, mainDirectory, resources, electronData);
  if (packagedAssets) {
    for (const file of [paths.pythonExecutable, paths.bridgeScriptPath, join(resources, "app.asar")]) {
      assert.ok(file && existsSync(file), `Packaged E2E resource is missing: ${file}`);
    }
  }
  const manager = new RuntimeProcessManager({
    repoRoot: packagedAssets ? paths.repoRoot : projectRoot,
    bridgeScriptPath: paths.bridgeScriptPath,
    workingDirectory: paths.workingDirectory,
    pythonExecutable: packagedAssets ? paths.pythonExecutable : pythonExecutable,
    environment: {
      DATA_AGENT_RUNTIME_DIR: join(electronData, "runtime"),
      DESKTOP_BRIDGE_WORKER_DELAY_MS: "650",
      ...(packagedAssets ? {
        PYTHONHOME: paths.pythonHome,
        PYTHONPATH: paths.repoRoot,
        PYTHONNOUSERSITE: "1",
        PATH: `${paths.nodeBinDirectory};${process.env.PATH ?? ""}`,
      } : {}),
    },
  });
  const runtime = new RuntimeClient(manager);
  const events: AgentEvent[] = [];
  runtime.onEvent((event) => events.push(event));
  registerIpcHandlers(runtime);

  // Only the operating-system file chooser is supplied with deterministic files.
  // Renderer, Preload, all IPC handlers, Main and Python Runtime remain real.
  const selections: string[] = [];
  const originalDialog = dialog.showOpenDialog;
  (dialog as unknown as { showOpenDialog: (...args: unknown[]) => Promise<{ canceled: boolean; filePaths: string[] }> }).showOpenDialog = async (...args) => {
    const options = args.at(-1) as { filters?: Array<{ extensions?: string[] }> };
    assert.deepEqual(options.filters?.[0]?.extensions, ["csv", "xlsx"]);
    const selected = selections.shift();
    assert.ok(selected, "File chooser was invoked without a queued test selection");
    return { canceled: false, filePaths: [selected] };
  };

  let window: BrowserWindow | null = null;
  let currentStep = "startup";
  try {
    await app.whenReady();
    await manager.start();
    if (packagedAssets) {
      window = new BrowserWindow({
        width: 800,
        height: 600,
        show: true,
        webPreferences: secureWebPreferences(join(resources, "app.asar", "dist", "src", "preload", "index.js")),
      });
      window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      window.webContents.on("will-navigate", (event) => event.preventDefault());
      await window.loadFile(join(resources, "app.asar", "dist", "src", "renderer", "index.html"));
    } else {
      window = await createWindow({ show: true });
    }
    const activeWindow = window;
    runtime.onEvent((event) => activeWindow.webContents.send(IPC_CHANNELS.agentEvent, event));
    const step = async (name: string, action: () => Promise<void>): Promise<void> => {
      currentStep = name;
      await action();
      console.log(`PASS M6.3 ${packagedAssets ? "packaged-resources " : ""}E2E: ${name}`);
    };

    await step("1 application startup", async () => {
      await waitFor(activeWindow, "initial empty state", `document.querySelector("#run-status")?.textContent === "empty"`);
      assert.equal(activeWindow.webContents.getURL().startsWith("file:"), true);
      if (packagedAssets) assert.match(activeWindow.webContents.getURL(), /app\.asar/);
      assert.equal(await activeWindow.webContents.executeJavaScript(`Boolean(window.agent && document.querySelector("#file-select") && document.querySelector("#trace-panel"))`), true);
    });

    await step("2 file error and real Retry", async () => {
      selections.push(join(electronData, "missing.csv"));
      await click(activeWindow, "#file-select");
      await waitFor(activeWindow, "structured file error", `!document.querySelector("#error-card").hidden && !document.querySelector("#error-retry").hidden`);
      const code = await activeWindow.webContents.executeJavaScript(`document.querySelector("#error-code").textContent`);
      assert.ok(String(code).length > 0);
      selections.push(csv);
      await click(activeWindow, "#error-retry");
      await waitFor(activeWindow, "CSV retry selection", `document.querySelector("#dataset-summary").textContent.includes("sales.csv") && document.querySelector("#error-card").hidden`);
    });

    await step("3 XLSX then CSV selection through UI and Main dialog", async () => {
      selections.push(xlsx);
      await click(activeWindow, "#file-select");
      await waitFor(activeWindow, "XLSX summary", `document.querySelector("#dataset-summary").textContent.includes("sample.xlsx")`);
      selections.push(csv);
      await click(activeWindow, "#file-select");
      const summary = await waitFor(activeWindow, "CSV summary", `document.querySelector("#dataset-summary").textContent.includes("sales.csv") && document.querySelector("#dataset-summary").textContent`);
      assert.match(String(summary), /5 rows/);
    });

    await step("4 Send, running/completed, Runtime Events and Trace", async () => {
      await fillAndSend(activeWindow, "各地区销售额总和是多少？");
      await waitFor(activeWindow, "running state", `document.querySelector("#run-status").textContent === "running"`);
      await waitFor(activeWindow, "completed state", `document.querySelector("#run-status").textContent === "completed"`, 20000);
      const snapshot = await activeWindow.webContents.executeJavaScript(`({
        answer: document.querySelector('[data-role="assistant"]:last-of-type p')?.textContent,
        sequences: [...document.querySelectorAll("#event-list > li")].map((item) => Number(item.dataset.sequence)),
        trace: document.querySelector("#event-list").textContent,
      })`);
      assert.match(String(snapshot.answer), /1580/);
      assert.deepEqual(snapshot.sequences, [...snapshot.sequences].sort((a: number, b: number) => a - b));
      assert.match(snapshot.trace, /route_selected|route/);
      assert.match(snapshot.trace, /tool_called|tool/);
      assert.match(snapshot.trace, /run_completed/);
      assert.equal(snapshot.trace.includes(csv), false);
      assert.ok(events.some((event) => event.type === "run_completed"));
      await click(activeWindow, "#trace-panel > summary");
      await click(activeWindow, "#event-list > li:first-child summary");
      assert.equal(await activeWindow.webContents.executeJavaScript(`document.querySelector("#event-list > li:first-child details").open`), true);
    });

    await step("5 Stop/Cancel through UI", async () => {
      await fillAndSend(activeWindow, "hello");
      await waitFor(activeWindow, "cancellable running state", `document.querySelector("#run-status").textContent === "running" && !document.querySelector("#run-stop").disabled`);
      await click(activeWindow, "#run-stop");
      await waitFor(activeWindow, "cancelled state", `document.querySelector("#run-status").textContent === "cancelled"`);
      assert.ok(events.some((event) => event.type === "run_cancelled"));
    });

    await step("6 Session List and Resume", async () => {
      await click(activeWindow, "#sessions-refresh");
      await waitFor(activeWindow, "session list", `document.querySelector("#session-list button[data-thread-id]")`);
      const threadId = events.find((event) => event.type === "run_completed")?.thread_id;
      assert.ok(threadId);
      await click(activeWindow, `[data-thread-id="${threadId}"]`);
      await waitFor(activeWindow, "session messages", `document.querySelector("#messages").textContent.includes("各地区销售额总和")`);
      const trace = await activeWindow.webContents.executeJavaScript(`document.querySelector("#event-list").textContent`);
      assert.ok(String(trace).length > 0);
    });

    await step("7 HITL Reject then Approve", async () => {
      await fillAndSend(activeWindow, "分析数据并执行外部写操作");
      await waitFor(activeWindow, "waiting approval", `document.querySelector("#run-status").textContent === "waiting_approval" && !document.querySelector("#approval-card").hidden`);
      const approval = await activeWindow.webContents.executeJavaScript(`({
        action: document.querySelector("#approval-action").textContent,
        id: document.querySelector("#approval-id").textContent,
        expires: document.querySelector("#approval-expires").textContent,
        body: document.querySelector("#approval-card").textContent,
      })`);
      assert.equal(approval.action, "mcp_write");
      assert.match(approval.id, /^approval_/);
      assert.ok(approval.expires);
      assert.equal(approval.body.includes("分析数据并执行外部写操作"), false);
      await click(activeWindow, "#approval-reject");
      await waitFor(activeWindow, "rejected state", `document.querySelector("#run-status").textContent === "failed"`);
      assert.ok(events.some((event) => event.type === "approval_resolved" && event.payload.status === "rejected"));

      await fillAndSend(activeWindow, "分析数据并执行外部写操作");
      await waitFor(activeWindow, "second waiting approval", `document.querySelector("#run-status").textContent === "waiting_approval" && !document.querySelector("#approval-card").hidden`);
      await click(activeWindow, "#approval-approve");
      await waitFor(activeWindow, "approved completion", `document.querySelector("#run-status").textContent === "completed"`, 20000);
      assert.ok(events.some((event) => event.type === "approval_resolved" && event.payload.status === "approved" && event.payload.executed === true));
      const trace = await activeWindow.webContents.executeJavaScript(`document.querySelector("#event-list").textContent`);
      assert.match(trace, /approval_resolved/);
    });
  } catch (error) {
    let ui = "unavailable";
    if (window && !window.isDestroyed()) {
      ui = await window.webContents.executeJavaScript(`JSON.stringify({
        state: document.querySelector("#run-status")?.textContent,
        errorCode: document.querySelector("#error-code")?.textContent,
        errorMessage: document.querySelector("#error-message")?.textContent,
        trace: document.querySelector("#event-list")?.textContent?.slice(-500),
      })`).catch(() => "unavailable");
    }
    throw new Error(`M6.3 E2E failed at ${currentStep}: ${error instanceof Error ? error.stack : String(error)}; UI=${ui}`);
  } finally {
    (dialog as unknown as { showOpenDialog: typeof dialog.showOpenDialog }).showOpenDialog = originalDialog;
    window?.destroy();
    manager.stop();
  }
  app.quit();
}

void run().catch((error: unknown) => {
  console.error(error);
  app.exit(1);
});
