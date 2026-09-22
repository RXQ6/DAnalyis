import { app, BrowserWindow } from "electron";
import { resolve } from "node:path";
import { RuntimeProcessManager } from "../bridge/processManager";
import { RuntimeClient } from "../bridge/runtimeClient";
import { IPC_CHANNELS } from "../shared/ipc";
import { createWindow } from "./create-window";
import { registerIpcHandlers } from "./ipc/register-handlers";

const repoRoot = resolve(__dirname, "../../../..");
const processManager = new RuntimeProcessManager({ repoRoot });
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

void app.whenReady().then(async () => {
  try {
    await processManager.start();
  } catch (error) {
    console.error("Python Runtime failed to start", error);
  }
  void createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow();
    }
  });
});

app.on("before-quit", () => processManager.stop());

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
