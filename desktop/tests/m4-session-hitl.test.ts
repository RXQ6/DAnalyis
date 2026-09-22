import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { RuntimeProcessManager } from "../src/bridge/processManager";
import { RuntimeClient } from "../src/bridge/runtimeClient";
import type { AgentEvent } from "../src/bridge/protocol";

const pythonExecutable = process.env.DATA_AGENT_PYTHON;
const repoRoot = resolve(__dirname, "../../..");

function waitFor(events: AgentEvent[], predicate: (event: AgentEvent) => boolean, timeoutMs = 15000): Promise<AgentEvent> {
  return new Promise((resolveEvent, reject) => {
    const started = Date.now();
    const timer = setInterval(() => {
      const event = events.find(predicate);
      if (event) {
        clearInterval(timer);
        resolveEvent(event);
      } else if (Date.now() - started > timeoutMs) {
        clearInterval(timer);
        reject(new Error(`timed out waiting for event; events=${JSON.stringify(events)}`));
      }
    }, 10);
  });
}

test("M4 Session list/resume and HITL approval lifecycle stay Runtime-owned", { skip: !pythonExecutable }, async () => {
  const runtimeDir = mkdtempSync(join(tmpdir(), "desktop-m4-"));
  const manager = new RuntimeProcessManager({
    repoRoot,
    pythonExecutable,
    environment: { DATA_AGENT_RUNTIME_DIR: runtimeDir },
  });
  const runtime = new RuntimeClient(manager);
  const events: AgentEvent[] = [];
  runtime.onEvent((event) => events.push(event));
  try {
    const first = await runtime.startRun("分析数据并执行外部写操作");
    const requested = await waitFor(events, (event) => event.run_id === first.runId && event.type === "approval_required");
    assert.equal(requested.payload.action_type, "mcp_write");
    assert.equal(requested.payload.risk_level, "high");
    assert.equal("arguments" in requested.payload, false);

    const sessions = await runtime.listSessions();
    assert.equal(sessions[0].threadId, first.threadId);
    assert.match(sessions[0].summary, /外部写/);
    const readOnlySnapshot = await runtime.getSession(first.threadId);
    assert.equal(readOnlySnapshot.threadId, first.threadId);
    const snapshot = await runtime.getSession(first.threadId, true);
    assert.equal(snapshot.threadId, first.threadId);
    assert.ok(snapshot.messages.some((message) => message.role === "user"));
    assert.ok(snapshot.events.some((event) => event.event_type === "approval_requested"));

    const approved = await runtime.resolveApproval(
      first.threadId,
      String(requested.payload.approval_id),
      String(requested.payload.action_hash),
      "approve",
    );
    assert.equal(approved.threadId, first.threadId);
    assert.notEqual(approved.traceId, first.traceId);
    const approvedEvent = await waitFor(events, (event) => event.run_id === approved.runId && event.type === "approval_resolved");
    assert.equal(approvedEvent.payload.status, "approved");
    assert.equal(approvedEvent.payload.executed, true);

    const replay = await runtime.resolveApproval(
      first.threadId,
      String(requested.payload.approval_id),
      String(requested.payload.action_hash),
      "approve",
    );
    const replayEvent = await waitFor(events, (event) => event.run_id === replay.runId && event.type === "approval_resolved");
    assert.equal(replayEvent.payload.executed, false);
    assert.equal(replayEvent.error?.code, "approval_already_consumed");

    const second = await runtime.startRun("分析数据并执行外部写操作", first.threadId);
    assert.notEqual(second.traceId, first.traceId);
    const secondRequest = await waitFor(events, (event) => event.run_id === second.runId && event.type === "approval_required");
    assert.equal(events.find((event) => event.run_id === second.runId)?.sequence, 1);
    const rejected = await runtime.resolveApproval(
      first.threadId,
      String(secondRequest.payload.approval_id),
      String(secondRequest.payload.action_hash),
      "reject",
    );
    const rejectedEvent = await waitFor(events, (event) => event.run_id === rejected.runId && event.type === "approval_resolved");
    assert.equal(rejectedEvent.payload.status, "rejected");
    assert.equal(rejectedEvent.payload.executed, false);

    const third = await runtime.startRun("分析数据并执行外部写操作", first.threadId);
    const thirdRequest = await waitFor(events, (event) => event.run_id === third.runId && event.type === "approval_required");
    const mismatch = await runtime.resolveApproval(
      first.threadId,
      String(thirdRequest.payload.approval_id),
      "wrong-action-hash",
      "approve",
    );
    const mismatchEvent = await waitFor(events, (event) => event.run_id === mismatch.runId && event.type === "approval_resolved");
    assert.equal(mismatchEvent.payload.status, "rejected");
    assert.equal(mismatchEvent.payload.executed, false);

    const other = await runtime.startRun("hello");
    await waitFor(events, (event) => event.run_id === other.runId && event.type === "run_completed");
    const otherSnapshot = await runtime.getSession(other.threadId, true);
    assert.ok(otherSnapshot.messages.every((message) => !String(message.content).includes("外部写")));
  } finally {
    manager.stop();
    rmSync(runtimeDir, { recursive: true, force: true });
  }
});

test("M4 expired approvals never execute", { skip: !pythonExecutable }, async () => {
  const runtimeDir = mkdtempSync(join(tmpdir(), "desktop-m4-expired-"));
  const manager = new RuntimeProcessManager({
    repoRoot,
    pythonExecutable,
    environment: { DATA_AGENT_RUNTIME_DIR: runtimeDir, DESKTOP_APPROVAL_TTL_SECONDS: "0.01" },
  });
  const runtime = new RuntimeClient(manager);
  const events: AgentEvent[] = [];
  runtime.onEvent((event) => events.push(event));
  try {
    const run = await runtime.startRun("分析数据并执行外部写操作");
    const requested = await waitFor(events, (event) => event.run_id === run.runId && event.type === "approval_required");
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 30));
    const resumed = await runtime.resolveApproval(
      run.threadId,
      String(requested.payload.approval_id),
      String(requested.payload.action_hash),
      "approve",
    );
    const resolved = await waitFor(events, (event) => event.run_id === resumed.runId && event.type === "approval_resolved");
    assert.equal(resolved.payload.status, "expired");
    assert.equal(resolved.payload.executed, false);
  } finally {
    manager.stop();
    rmSync(runtimeDir, { recursive: true, force: true });
  }
});

test("M4 session and pending approval survive Runtime host restart", { skip: !pythonExecutable }, async () => {
  const runtimeDir = mkdtempSync(join(tmpdir(), "desktop-m4-restart-"));
  const firstManager = new RuntimeProcessManager({
    repoRoot,
    pythonExecutable,
    environment: { DATA_AGENT_RUNTIME_DIR: runtimeDir },
  });
  const firstRuntime = new RuntimeClient(firstManager);
  const firstEvents: AgentEvent[] = [];
  firstRuntime.onEvent((event) => firstEvents.push(event));
  let secondManager: RuntimeProcessManager | null = null;
  try {
    const original = await firstRuntime.startRun("分析数据并执行外部写操作");
    const pending = await waitFor(firstEvents, (event) =>
      event.run_id === original.runId && event.type === "approval_required",
    );
    firstManager.stop();
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 150));

    secondManager = new RuntimeProcessManager({
      repoRoot,
      pythonExecutable,
      environment: { DATA_AGENT_RUNTIME_DIR: runtimeDir },
    });
    const secondRuntime = new RuntimeClient(secondManager);
    const secondEvents: AgentEvent[] = [];
    secondRuntime.onEvent((event) => secondEvents.push(event));

    const listed = await secondRuntime.listSessions();
    assert.ok(listed.some((session) => session.threadId === original.threadId));
    const hydrated = await secondRuntime.getSession(original.threadId, true);
    assert.ok(hydrated.events.some((event) => event.event_type === "approval_requested"));
    const eventCount = hydrated.events.length;

    const resumed = await secondRuntime.resolveApproval(
      original.threadId,
      String(pending.payload.approval_id),
      String(pending.payload.action_hash),
      "approve",
    );
    assert.equal(resumed.threadId, original.threadId);
    assert.notEqual(resumed.traceId, original.traceId);
    const resolved = await waitFor(secondEvents, (event) =>
      event.run_id === resumed.runId && event.type === "approval_resolved",
    );
    assert.equal(resolved.payload.executed, true);

    const afterApproval = await secondRuntime.getSession(original.threadId, true);
    assert.ok(afterApproval.events.length > eventCount);
    const completedCount = afterApproval.events.filter((event) => event.event_type === "approval_resumed").length;
    const hydratedAgain = await secondRuntime.getSession(original.threadId, true);
    assert.equal(
      hydratedAgain.events.filter((event) => event.event_type === "approval_resumed").length,
      completedCount,
    );

    await assert.rejects(
      secondRuntime.getSession("thread_does_not_exist", true),
      (error: unknown) => error instanceof Error && "code" in error && error.code === "session_not_found",
    );
  } finally {
    firstManager.stop();
    secondManager?.stop();
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
    rmSync(runtimeDir, { recursive: true, force: true });
  }
});
