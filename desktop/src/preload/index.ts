import { contextBridge, ipcRenderer } from "electron";
import type { AgentEvent, DesktopApi, FilesSelectInput, RunsCancelInput, RunsStartInput } from "../shared/ipc";

// A sandboxed preload cannot require local modules at runtime. Keep the shared
// types, but compile the single M1 channel into this preload bundle.
const RUNS_START_CHANNEL: "runs:start" = "runs:start";
const RUNS_CANCEL_CHANNEL: "runs:cancel" = "runs:cancel";
const FILES_SELECT_CHANNEL: "files:select" = "files:select";
const AGENT_EVENT_CHANNEL: "agent:event" = "agent:event";

const api: DesktopApi = Object.freeze({
  startRun: (input: RunsStartInput) =>
    ipcRenderer.invoke(RUNS_START_CHANNEL, input),
  cancelRun: (input: RunsCancelInput) =>
    ipcRenderer.invoke(RUNS_CANCEL_CHANNEL, input),
  selectDataset: (input: FilesSelectInput = {}) =>
    ipcRenderer.invoke(FILES_SELECT_CHANNEL, input),
  onAgentEvent: (listener: (event: AgentEvent) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, value: AgentEvent): void => listener(value);
    ipcRenderer.on(AGENT_EVENT_CHANNEL, handler);
    return () => ipcRenderer.removeListener(AGENT_EVENT_CHANNEL, handler);
  },
});

contextBridge.exposeInMainWorld("agent", api);
