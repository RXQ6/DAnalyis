import { contextBridge, ipcRenderer } from "electron";
import type { AgentEvent, ApprovalInput, DesktopApi, FilesSelectInput, RunsCancelInput, RunsStartInput, SessionInput } from "../shared/ipc";

// A sandboxed preload cannot require local modules at runtime. Keep the shared
// types, but compile the single M1 channel into this preload bundle.
const RUNS_START_CHANNEL: "runs:start" = "runs:start";
const RUNS_CANCEL_CHANNEL: "runs:cancel" = "runs:cancel";
const FILES_SELECT_CHANNEL: "files:select" = "files:select";
const SESSIONS_LIST_CHANNEL: "sessions:list" = "sessions:list";
const SESSIONS_GET_CHANNEL: "sessions:get" = "sessions:get";
const SESSIONS_RESUME_CHANNEL: "sessions:resume" = "sessions:resume";
const APPROVALS_APPROVE_CHANNEL: "approvals:approve" = "approvals:approve";
const APPROVALS_REJECT_CHANNEL: "approvals:reject" = "approvals:reject";
const AGENT_EVENT_CHANNEL: "agent:event" = "agent:event";

const api: DesktopApi = Object.freeze({
  startRun: (input: RunsStartInput) =>
    ipcRenderer.invoke(RUNS_START_CHANNEL, input),
  cancelRun: (input: RunsCancelInput) =>
    ipcRenderer.invoke(RUNS_CANCEL_CHANNEL, input),
  selectDataset: (input: FilesSelectInput = {}) =>
    ipcRenderer.invoke(FILES_SELECT_CHANNEL, input),
  listSessions: () => ipcRenderer.invoke(SESSIONS_LIST_CHANNEL),
  getSession: (input: SessionInput) => ipcRenderer.invoke(SESSIONS_GET_CHANNEL, input),
  resumeSession: (input: SessionInput) => ipcRenderer.invoke(SESSIONS_RESUME_CHANNEL, input),
  approve: (input: ApprovalInput) => ipcRenderer.invoke(APPROVALS_APPROVE_CHANNEL, input),
  reject: (input: ApprovalInput) => ipcRenderer.invoke(APPROVALS_REJECT_CHANNEL, input),
  onAgentEvent: (listener: (event: AgentEvent) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, value: AgentEvent): void => listener(value);
    ipcRenderer.on(AGENT_EVENT_CHANNEL, handler);
    return () => ipcRenderer.removeListener(AGENT_EVENT_CHANNEL, handler);
  },
});

contextBridge.exposeInMainWorld("agent", api);
