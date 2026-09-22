import assert from "node:assert/strict";
import test from "node:test";
import { IPC_CHANNELS, PUBLIC_API_METHODS } from "../src/shared/ipc";
import { secureWebPreferences } from "../src/main/window-options";

test("BrowserWindow uses the required isolation settings", () => {
  const preferences = secureWebPreferences("C:\\trusted\\preload.js");
  assert.equal(preferences.contextIsolation, true);
  assert.equal(preferences.nodeIntegration, false);
  assert.equal(preferences.sandbox, true);
});

test("M4 exposes only the declared channels and preload methods", () => {
  assert.deepEqual(IPC_CHANNELS, {
    runsStart: "runs:start",
    runsCancel: "runs:cancel",
    filesSelect: "files:select",
    sessionsList: "sessions:list",
    sessionsGet: "sessions:get",
    sessionsResume: "sessions:resume",
    approvalsApprove: "approvals:approve",
    approvalsReject: "approvals:reject",
    agentEvent: "agent:event",
  });
  assert.match(IPC_CHANNELS.runsStart, /^[a-z]+:[a-z]+$/);
  assert.match(IPC_CHANNELS.runsCancel, /^[a-z]+:[a-z]+$/);
  assert.match(IPC_CHANNELS.filesSelect, /^[a-z]+:[a-z]+$/);
  assert.deepEqual(PUBLIC_API_METHODS, [
    "startRun", "cancelRun", "selectDataset", "listSessions", "getSession",
    "resumeSession", "approve", "reject", "onAgentEvent",
  ]);
});
