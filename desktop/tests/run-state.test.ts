import assert from "node:assert/strict";
import test from "node:test";
import type { AgentEvent } from "../src/shared/ipc";
import { OrderedRunProjector, eventBelongsToSession } from "../src/renderer/run-state";

function event(sequence: number, type: string, payload: Record<string, unknown> = {}, error: AgentEvent["error"] = null): AgentEvent {
  return {
    protocol_version: 1,
    request_id: "req_1",
    run_id: "run_1",
    thread_id: "thread_1",
    trace_id: "trace_1",
    sequence,
    type,
    payload,
    error,
  };
}

test("run projection applies out-of-order events strictly by sequence", () => {
  const projector = new OrderedRunProjector("run_1");
  assert.equal(projector.push(event(2, "route_selected")).status, "idle");
  const running = projector.push(event(1, "run_started", { status: "running" }));
  assert.equal(running.status, "running");
  assert.equal(running.lastSequence, 2);
  assert.deepEqual(running.events.map((item) => item.sequence), [1, 2]);
  assert.equal(projector.push(event(2, "route_selected")).events.length, 2);
});

test("run projection maps terminal, approval and partial states from Runtime events", () => {
  const approval = new OrderedRunProjector("run_1");
  approval.push(event(1, "run_started"));
  assert.equal(approval.push(event(2, "approval_required")).status, "waiting_approval");

  const completed = new OrderedRunProjector("run_1");
  completed.push(event(1, "run_started"));
  const final = completed.push(event(2, "run_completed", { response: "done", partial: false }));
  assert.equal(final.status, "completed");
  assert.equal(final.answer, "done");

  const partial = new OrderedRunProjector("run_1");
  partial.push(event(1, "run_started"));
  const failed = partial.push(event(2, "run_failed", { partial: true }, { code: "boom", message: "failed" }));
  assert.equal(failed.status, "partial");
  assert.equal(failed.error?.code, "boom");
  assert.deepEqual(failed.partialMissing, ["Some requested tool results are unavailable."]);

  const cancelled = new OrderedRunProjector("run_1");
  cancelled.push(event(1, "run_started"));
  assert.equal(cancelled.push(event(2, "run_cancelled")).status, "cancelled");
});

test("chart_ready projects existing Chart Spec without data recomputation", () => {
  const projector = new OrderedRunProjector("run_1");
  projector.push(event(1, "run_started"));
  const projection = projector.push(event(2, "chart_ready", {
    spec: { version: "1.0", chartType: "bar", title: "Sales", data: { values: [{ x: "East", y: 10 }] } },
    artifact: { mediaType: "image/svg+xml", sha256: "abc" },
  }));
  assert.equal(projection.charts.length, 1);
  assert.deepEqual(projection.charts[0].spec, {
    version: "1.0",
    chartType: "bar",
    title: "Sales",
    data: { values: [{ x: "East", y: 10 }] },
  });
});

test("approval projection uses Runtime fields and maps resume/reject/expiry states", () => {
  const pending = new OrderedRunProjector("run_1");
  pending.push(event(1, "run_started"));
  const waiting = pending.push(event(2, "approval_required", {
    approval_id: "approval_1", action_hash: "secret-hash", action_type: "mcp_write",
    risk_level: "high", expires_at: "2030-01-01T00:00:00+00:00",
  }));
  assert.equal(waiting.status, "waiting_approval");
  assert.equal(waiting.approval?.approvalId, "approval_1");

  const rejected = new OrderedRunProjector("run_1");
  rejected.push(event(1, "run_started", { status: "resuming" }));
  assert.equal(rejected.snapshot().status, "resuming");
  assert.equal(rejected.push(event(2, "approval_resolved", { status: "rejected" })).status, "rejected");

  const expired = new OrderedRunProjector("run_1");
  expired.push(event(1, "run_started", { status: "resuming" }));
  assert.equal(expired.push(event(2, "approval_resolved", { status: "expired" })).status, "expired");
});

test("Session A events cannot project into Session B", () => {
  const fromA = event(1, "run_started");
  assert.equal(eventBelongsToSession(fromA, "thread_1"), true);
  assert.equal(eventBelongsToSession(fromA, "thread_2"), false);
});
