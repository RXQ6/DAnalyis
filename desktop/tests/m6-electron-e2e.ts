import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { app, BrowserWindow, dialog, Menu } from "electron";
import { RuntimeProcessManager } from "../src/bridge/processManager";
import { RuntimeClient } from "../src/bridge/runtimeClient";
import type { AgentEvent } from "../src/bridge/protocol";
import { IPC_CHANNELS } from "../src/shared/ipc";
import { createWindow, WINDOW_CHROME } from "../src/main/create-window";
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
            " viewport=" + window.innerWidth +
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
        ...WINDOW_CHROME,
        webPreferences: secureWebPreferences(join(resources, "app.asar", "dist", "src", "preload", "index.js")),
      });
      Menu.setApplicationMenu(null);
      window.setMenu(null);
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
      await waitFor(activeWindow, "initial empty state", `document.querySelector("#run-status")?.dataset.state === "empty"`);
      assert.equal(activeWindow.webContents.getURL().startsWith("file:"), true);
      assert.equal(activeWindow.isMenuBarVisible(), false);
      assert.equal(Menu.getApplicationMenu(), null);
      if (packagedAssets) assert.match(activeWindow.webContents.getURL(), /app\.asar/);
      assert.equal(await activeWindow.webContents.executeJavaScript(`Boolean(window.agent && document.querySelector("#file-select") && document.querySelector("#trace-panel"))`), true);
      const layout = await activeWindow.webContents.executeJavaScript(`(() => {
        const header = document.querySelector("#context-header").getBoundingClientRect();
        const chrome = document.querySelector("#window-chrome").getBoundingClientRect();
        const sidebar = document.querySelector("#left-sidebar").getBoundingClientRect();
        const center = document.querySelector("#center-panel").getBoundingClientRect();
        const trace = document.querySelector("#trace-panel").getBoundingClientRect();
        const composer = document.querySelector("#composer").getBoundingClientRect();
        const fileAction = document.querySelector("#header-file-action").getBoundingClientRect();
        return {
          stylesheetLoaded: [...document.styleSheets].some((sheet) => sheet.href?.endsWith("styles.css")),
          compactChrome: chrome.top === 0 && chrome.height === 38 && chrome.bottom === header.top,
          noGenericTitle: !document.querySelector("#app-shell").textContent.includes("Data Analysis Agent") && document.title === "分析工作台",
          headerAboveWorkspace: header.bottom <= center.top,
          sidebarCollapsed: sidebar.right <= 0,
          traceCollapsed: !document.querySelector("#trace-panel").open && trace.width <= 45,
          composerAtBottom: Math.abs(composer.bottom - center.bottom) <= 2,
          fileActionVisible: fileAction.top >= header.top && fileAction.bottom <= header.bottom,
        };
      })()`);
      assert.deepEqual(layout, {
        stylesheetLoaded: true,
        compactChrome: true,
        noGenericTitle: true,
        headerAboveWorkspace: true,
        sidebarCollapsed: true,
        traceCollapsed: true,
        composerAtBottom: true,
        fileActionVisible: true,
      });
    });

    await step("1a responsive layout and scrolling", async () => {
      try {
        for (const width of [700, 520]) {
          await new Promise((resolveDelay) => setTimeout(resolveDelay, 150));
          activeWindow.setContentSize(width, 600);
          await new Promise((resolveDelay) => setTimeout(resolveDelay, 150));
          if (await activeWindow.webContents.executeJavaScript(`window.innerWidth`) !== width) {
            activeWindow.restore();
            activeWindow.setContentSize(width, 600);
          }
          await waitFor(activeWindow, `viewport ${width}px`, `window.innerWidth === ${width}`);
          const layout = await activeWindow.webContents.executeJavaScript(`(() => {
            const sidebar = document.querySelector("#left-sidebar").getBoundingClientRect();
            const center = document.querySelector("#center-panel").getBoundingClientRect();
            const trace = document.querySelector("#trace-panel").getBoundingClientRect();
            const composer = document.querySelector("#composer").getBoundingClientRect();
            const fileAction = document.querySelector("#header-file-action").getBoundingClientRect();
            return {
              viewportWidth: window.innerWidth,
              noPageOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
              composerVisible: composer.height > 0 && composer.bottom <= window.innerHeight + 1,
              traceBelowCenter: trace.top >= center.bottom,
              sidebarCollapsed: sidebar.right <= 0,
              fileActionVisible: fileAction.left >= 0 && fileAction.right <= window.innerWidth,
            };
          })()`);
          assert.equal(layout.viewportWidth, width);
          assert.equal(layout.noPageOverflow, true, `Horizontal page overflow at ${width}px`);
          assert.equal(layout.composerVisible, true, `Composer not visible at ${width}px`);
          assert.equal(layout.traceBelowCenter, true, `Trace did not reflow at ${width}px`);
          assert.equal(layout.fileActionVisible, true, `File action not visible at ${width}px`);
          assert.equal(layout.sidebarCollapsed, true, `Sidebar did not collapse at ${width}px`);
        }
      } finally {
        activeWindow.setContentSize(800, 600);
      }
    });

    await step("1b workspace layout, resizing and planned integrations", async () => {
      try {
        activeWindow.setContentSize(1440, 900);
        await waitFor(activeWindow, "desktop viewport", `window.innerWidth === 1440`);
        const initial = await activeWindow.webContents.executeJavaScript(`({
          welcomeVisible: !document.querySelector("#welcome").hidden,
          examples: document.querySelectorAll(".example-question").length,
          recent: Boolean(document.querySelector("#recent-analyses")),
          capability: Boolean(document.querySelector(".capability-note")),
          brandLoaded: [...document.querySelectorAll(".brand-mark")].every((image) => image.complete && image.naturalWidth > 0),
          traceClosed: !document.querySelector("#trace-panel").open,
          leftWidth: document.querySelector("#left-sidebar").getBoundingClientRect().width,
        })`);
        assert.equal(initial.welcomeVisible, true);
        assert.equal(initial.examples, 3);
        assert.equal(initial.recent, true);
        assert.equal(initial.capability, true);
        assert.equal(initial.brandLoaded, true);
        assert.equal(initial.traceClosed, true);
        if (process.env.DATA_AGENT_CAPTURE_UI === "1") {
          const path = join(electronData, "phase14-empty.png");
          writeFileSync(path, (await activeWindow.webContents.capturePage()).toPNG());
          console.log(`Phase 1.4 empty screenshot: ${path}`);
        }
        const left = await activeWindow.webContents.executeJavaScript(`(() => {
          const rect = document.querySelector("#left-resizer").getBoundingClientRect();
          return { x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + 150) };
        })()`);
        activeWindow.webContents.sendInputEvent({ type: "mouseMove", x: left.x, y: left.y });
        activeWindow.webContents.sendInputEvent({ type: "mouseDown", x: left.x, y: left.y, button: "left", clickCount: 1 });
        activeWindow.webContents.sendInputEvent({ type: "mouseMove", x: left.x + 42, y: left.y });
        activeWindow.webContents.sendInputEvent({ type: "mouseUp", x: left.x + 42, y: left.y, button: "left", clickCount: 1 });
        await waitFor(activeWindow, "left resize", `document.querySelector("#left-sidebar").getBoundingClientRect().width > ${initial.leftWidth + 20}`);
        await click(activeWindow, "#trace-panel > summary");
        await waitFor(activeWindow, "expanded trace", `document.querySelector("#trace-panel").open && document.querySelector("#trace-resizer").getBoundingClientRect().width > 0`);
        const right = await activeWindow.webContents.executeJavaScript(`(() => {
          const rect = document.querySelector("#trace-resizer").getBoundingClientRect();
          return { x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + 150), width: document.querySelector("#trace-panel").getBoundingClientRect().width };
        })()`);
        activeWindow.webContents.sendInputEvent({ type: "mouseMove", x: right.x, y: right.y });
        activeWindow.webContents.sendInputEvent({ type: "mouseDown", x: right.x, y: right.y, button: "left", clickCount: 1 });
        activeWindow.webContents.sendInputEvent({ type: "mouseMove", x: right.x - 42, y: right.y });
        activeWindow.webContents.sendInputEvent({ type: "mouseUp", x: right.x - 42, y: right.y, button: "left", clickCount: 1 });
        await waitFor(activeWindow, "right resize", `document.querySelector("#trace-panel").getBoundingClientRect().width > ${right.width + 20}`);
        await click(activeWindow, "#trace-panel > summary");
        await click(activeWindow, "#settings-open");
        const settings = await activeWindow.webContents.executeJavaScript(`({
          shown: !document.querySelector("#settings-view").hidden,
          workspaceHidden: document.querySelector("#analysis-scroll").hidden,
          composerHidden: document.querySelector("#composer").hidden,
          providers: document.querySelectorAll(".provider-grid > div").length,
          planned: [...document.querySelectorAll(".settings-section .planned-badge")].every((badge) => badge.textContent === "规划中"),
          noKeyInput: !document.querySelector("#settings-view input"),
          traceHidden: getComputedStyle(document.querySelector("#trace-panel")).display === "none",
          settingsRendered: getComputedStyle(document.querySelector("#settings-view")).display !== "none",
          workspaceVisualHidden: getComputedStyle(document.querySelector("#analysis-scroll")).display === "none",
        })`);
        assert.deepEqual(settings, { shown: true, workspaceHidden: true, composerHidden: true, providers: 5, planned: true, noKeyInput: true, traceHidden: true, settingsRendered: true, workspaceVisualHidden: true });
        if (process.env.DATA_AGENT_CAPTURE_UI === "1") {
          await new Promise((resolveDelay) => setTimeout(resolveDelay, 120));
          const path = join(electronData, "phase14-settings.png");
          writeFileSync(path, (await activeWindow.webContents.capturePage()).toPNG());
          console.log(`Phase 1.4 settings screenshot: ${path}`);
        }
        await click(activeWindow, "#workspace-open");
        assert.equal(await activeWindow.webContents.executeJavaScript(`document.querySelector("#settings-view").hidden`), true);
        await click(activeWindow, ".example-question");
        assert.equal(await activeWindow.webContents.executeJavaScript(`document.querySelector("#run-input").value`), "按地区汇总销售额");
      } finally {
        activeWindow.setContentSize(800, 600);
      }
    });

    await step("2 file error and real Retry", async () => {
      selections.push(join(electronData, "missing.csv"));
      await click(activeWindow, "#header-file-action");
      await waitFor(activeWindow, "structured file error", `!document.querySelector("#error-card").hidden && !document.querySelector("#error-retry").hidden`);
      const code = await activeWindow.webContents.executeJavaScript(`document.querySelector("#error-code").textContent`);
      assert.ok(String(code).length > 0);
      assert.equal(await activeWindow.webContents.executeJavaScript(`document.querySelector("#error-card").dataset.state`), "stale");
      selections.push(csv);
      await click(activeWindow, "#error-retry");
      await waitFor(activeWindow, "CSV retry selection", `document.querySelector("#dataset-summary").textContent.includes("sales.csv") && document.querySelector("#error-card").hidden`);
    });

    await step("3 XLSX then CSV selection through UI and Main dialog", async () => {
      selections.push(xlsx);
      await click(activeWindow, "#header-file-action");
      await waitFor(activeWindow, "XLSX summary", `document.querySelector("#dataset-summary").textContent.includes("sample.xlsx")`);
      selections.push(csv);
      await click(activeWindow, "#header-file-action");
      const summary = await waitFor(activeWindow, "CSV summary", `document.querySelector("#dataset-summary").textContent.includes("sales.csv") && document.querySelector("#dataset-summary").textContent`);
      assert.match(String(summary), /5 行/);
      const context = await activeWindow.webContents.executeJavaScript(`({
        session: document.querySelector("#header-session").textContent,
        dataset: document.querySelector("#header-dataset").textContent,
      })`);
      assert.equal(context.session, "新分析");
      assert.doesNotMatch(context.session, /thread_/);
      assert.equal(context.dataset, "sales.csv");
      assert.equal(await activeWindow.webContents.executeJavaScript(`document.querySelector("#file-select").textContent`), "选择 CSV / XLSX");
    });

    await step("4 Send, running/completed, Runtime Events and Trace", async () => {
      await fillAndSend(activeWindow, "各地区销售额总和是多少？");
      await waitFor(activeWindow, "running state", `document.querySelector("#run-status").dataset.state === "running"`);
      await waitFor(activeWindow, "completed state", `document.querySelector("#run-status").dataset.state === "completed"`, 20000);
      const snapshot = await activeWindow.webContents.executeJavaScript(`({
        answer: document.querySelector('[data-role="assistant"]:last-of-type p')?.textContent,
        sequences: [...document.querySelectorAll("#event-list > li")].map((item) => Number(item.dataset.sequence)),
        trace: document.querySelector("#event-list").textContent,
      })`);
      assert.match(String(snapshot.answer), /1580/);
      assert.equal(await activeWindow.webContents.executeJavaScript(`document.querySelector("#header-session").textContent`), "各地区销售额总和是多少");
      assert.deepEqual(await activeWindow.webContents.executeJavaScript(`({ send: document.querySelector("#run-submit").textContent, stop: document.querySelector("#run-stop").textContent })`), { send: "发送", stop: "停止" });
      const presented = await activeWindow.webContents.executeJavaScript(`({
        summary: document.querySelector("#analysis-summary-content").textContent,
        hasTable: Boolean(document.querySelector("#analysis-summary .result-table")),
        metrics: [...document.querySelectorAll("#metric-cards .metric-card strong")].map((item) => item.textContent),
        insightsHidden: document.querySelector("#insight-cards").hidden,
      })`);
      assert.equal(presented.hasTable, true);
      assert.match(presented.summary, /1580/);
      assert.doesNotMatch(presented.summary, /\{\s*"metric"|thread_|trace_|tool_args/);
      assert.deepEqual(presented.metrics, ["5", "4"]);
      assert.equal(presented.insightsHidden, true);
      if (process.env.DATA_AGENT_CAPTURE_UI === "1") {
        await activeWindow.webContents.executeJavaScript(`document.querySelector("#analysis-summary").scrollIntoView({ block: "center" })`);
        const path = join(electronData, "phase14-analysis.png");
        writeFileSync(path, (await activeWindow.webContents.capturePage()).toPNG());
        console.log(`Phase 1.4 analysis screenshot: ${path}`);
      }
      assert.deepEqual(snapshot.sequences, [...snapshot.sequences].sort((a: number, b: number) => a - b));
      assert.match(snapshot.trace, /已选择处理方式|已选择分析路径/);
      assert.match(snapshot.trace, /数据分析步骤/);
      assert.match(snapshot.trace, /分析已完成/);
      assert.equal(snapshot.trace.includes(csv), false);
      assert.doesNotMatch(snapshot.trace, /thread_|trace_|run_completed|tool_called|#\d+/);
      const timeline = await activeWindow.webContents.executeJavaScript(`({
        className: document.querySelector("#event-list").className,
        structured: [...document.querySelectorAll("#event-list > li")].every((item) =>
          Boolean(item.dataset.sequence && item.querySelector(".trace-label") && !item.querySelector(".trace-sequence"))),
      })`);
      assert.match(timeline.className, /trace-timeline/);
      assert.equal(timeline.structured, true);
      assert.ok(events.some((event) => event.type === "run_completed"));
      await click(activeWindow, "#trace-panel > summary");
      await click(activeWindow, "#event-list > li:first-child summary");
      assert.equal(await activeWindow.webContents.executeJavaScript(`document.querySelector("#event-list > li:first-child details").open`), true);
    });

    await step("5 Stop/Cancel through UI", async () => {
      await fillAndSend(activeWindow, "hello");
      await waitFor(activeWindow, "cancellable running state", `document.querySelector("#run-status").dataset.state === "running" && !document.querySelector("#run-stop").disabled`);
      await click(activeWindow, "#run-stop");
      await waitFor(activeWindow, "cancelled state", `document.querySelector("#run-status").dataset.state === "cancelled"`);
      assert.ok(events.some((event) => event.type === "run_cancelled"));
    });

    await step("6 Session List and Resume", async () => {
      await click(activeWindow, "#sessions-refresh");
      await waitFor(activeWindow, "session list", `document.querySelector("#session-list button[data-thread-id]")`);
      assert.equal(await activeWindow.webContents.executeJavaScript(`Boolean(document.querySelector("#session-list button .session-summary") && !document.querySelector("#session-list button .session-id"))`), true);
      const threadId = events.find((event) => event.type === "run_completed")?.thread_id;
      assert.ok(threadId);
      await click(activeWindow, `[data-thread-id="${threadId}"]`);
      await waitFor(activeWindow, "session messages", `document.querySelector("#messages").textContent.includes("各地区销售额总和")`);
      assert.equal(await activeWindow.webContents.executeJavaScript(`document.querySelector("#header-session").textContent`), "各地区销售额总和是多少");
      assert.equal(await activeWindow.webContents.executeJavaScript(`document.querySelector("#session-list").textContent.includes("thread_")`), false);
      const trace = await activeWindow.webContents.executeJavaScript(`document.querySelector("#event-list").textContent`);
      assert.ok(String(trace).length > 0);
    });

    await step("7 HITL Reject then Approve", async () => {
      await fillAndSend(activeWindow, "分析数据并执行外部写操作");
      await waitFor(activeWindow, "waiting approval", `document.querySelector("#run-status").dataset.state === "waiting_approval" && !document.querySelector("#approval-card").hidden`);
      const approval = await activeWindow.webContents.executeJavaScript(`({
        action: document.querySelector("#approval-action").textContent,
        id: document.querySelector("#approval-id").textContent,
        expires: document.querySelector("#approval-expires").textContent,
        body: document.querySelector("#approval-card").innerText,
      })`);
      assert.equal(approval.action, "向外部服务写入数据");
      assert.match(approval.id, /^approval_/);
      assert.ok(approval.expires);
      assert.equal(approval.body.includes(approval.id), false);
      assert.equal(approval.body.includes("分析数据并执行外部写操作"), false);
      assert.equal(approval.body.includes("action_hash"), false);
      await click(activeWindow, "#approval-reject");
      await waitFor(activeWindow, "rejected state", `document.querySelector("#run-status").dataset.state === "failed"`);
      assert.ok(events.some((event) => event.type === "approval_resolved" && event.payload.status === "rejected"));

      await fillAndSend(activeWindow, "分析数据并执行外部写操作");
      await waitFor(activeWindow, "second waiting approval", `document.querySelector("#run-status").dataset.state === "waiting_approval" && !document.querySelector("#approval-card").hidden`);
      await click(activeWindow, "#approval-approve");
      await waitFor(activeWindow, "approved completion", `document.querySelector("#run-status").dataset.state === "completed"`, 20000);
      assert.ok(events.some((event) => event.type === "approval_resolved" && event.payload.status === "approved" && event.payload.executed === true));
      const trace = await activeWindow.webContents.executeJavaScript(`document.querySelector("#event-list").textContent`);
      assert.match(trace, /确认已处理/);
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
