import { app, BrowserWindow } from "electron";
import { RuntimeProcessManager } from "../bridge/processManager";
import { RuntimeClient } from "../bridge/runtimeClient";
import { IPC_CHANNELS } from "../shared/ipc";
import { createWindow } from "./create-window";
import { registerIpcHandlers } from "./ipc/register-handlers";
import { runPackagedSmoke } from "./packaged-smoke";
import { resolveRuntimePaths } from "./runtime-paths";

let processManager: RuntimeProcessManager | null = null;

void app.whenReady().then(async () => {
  const paths = resolveRuntimePaths(app.isPackaged, __dirname, process.resourcesPath, app.getPath("userData"));
  processManager = new RuntimeProcessManager({
    repoRoot: paths.repoRoot,
    bridgeScriptPath: paths.bridgeScriptPath,
    workingDirectory: paths.workingDirectory,
    pythonExecutable: paths.pythonExecutable,
    environment: {
      DATA_AGENT_RUNTIME_DIR: paths.runtimeDataDirectory,
      ...(process.env.DATA_AGENT_PACKAGING_SMOKE === "m6.4-first" ? { DESKTOP_BRIDGE_WORKER_DELAY_MS: "650" } : {}),
      ...(app.isPackaged ? {
        PYTHONHOME: paths.pythonHome,
        PYTHONPATH: paths.repoRoot,
        PYTHONNOUSERSITE: "1",
        PATH: `${paths.nodeBinDirectory};${process.env.PATH ?? ""}`,
      } : {}),
    },
  });
  const runtime = new RuntimeClient(processManager);
  registerIpcHandlers(runtime);
  runtime.onEvent((event) => {
    for (const window of BrowserWindow.getAllWindows()) {
      if (!window.isDestroyed()) {
        window.webContents.send(IPC_CHANNELS.agentEvent, event);
      }
    }
  });
  runtime.onStderr((message) => process.stderr.write(`[python-runtime] ${message}`));
  try {
    await processManager.start();
  } catch (error) {
    console.error("Python Runtime failed to start", error);
  }
  const smokePhase = process.env.DATA_AGENT_PACKAGING_SMOKE;
  const packagingSmoke = smokePhase === "1" || smokePhase === "m6.4-first" || smokePhase === "m6.4-resume";
  const window = await createWindow({ show: !packagingSmoke });
  if (smokePhase === "m6.4-first" || smokePhase === "m6.4-resume") {
    await runPackagedSmoke(window, runtime, paths, smokePhase === "m6.4-first" ? "first" : "resume");
    app.exit(0);
    return;
  }
  if (packagingSmoke) {
    const ready = await window.webContents.executeJavaScript(
      "Boolean(window.agent && document.querySelector('#run-submit') && document.querySelector('#session-list'))",
    );
    if (!ready) {
      throw new Error("Packaged Renderer or Preload did not initialize");
    }
    if (app.isPackaged) {
      const result = await window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
        const events = [];
        const timeout = setTimeout(() => reject(new Error("Packaged run timed out")), 20000);
        const unsubscribe = window.agent.onAgentEvent((event) => {
          events.push(event);
          if (event.type === "run_completed" || event.type === "run_failed") {
            clearTimeout(timeout);
            unsubscribe();
            resolve({ events });
          }
        });
        window.agent.startRun({ message: "hello" }).then((started) => {
          if (!started.ok) {
            clearTimeout(timeout);
            unsubscribe();
            reject(new Error("Packaged run start failed: " + started.error.code));
          }
        }).catch(reject);
      })`);
      if (!result.events.some((event: { type: string }) => event.type === "route_selected") ||
          !result.events.some((event: { type: string }) => event.type === "run_completed")) {
        throw new Error("Packaged Python Runtime did not complete a real run");
      }
    }
    app.exit(0);
    return;
  }
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow();
    }
  });
}).catch((error: unknown) => {
  console.error("Desktop startup failed", error);
  app.exit(1);
});

app.on("before-quit", () => processManager?.stop());

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
