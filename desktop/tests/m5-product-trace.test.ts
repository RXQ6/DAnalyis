import assert from "node:assert/strict";
import test from "node:test";
import type { AgentEvent } from "../src/shared/ipc";
import { describeProductState, isStaleError, productStateFromRun, type ProductState } from "../src/renderer/product-state";
import { projectTrace } from "../src/renderer/trace-panel";

function event(
  sequence: number,
  type: string,
  payload: Record<string, unknown>,
  error: AgentEvent["error"] = null,
): AgentEvent {
  return {
    protocol_version: 1,
    request_id: "req_m5",
    run_id: "run_m5",
    thread_id: "thread_m5",
    trace_id: "trace_m5",
    sequence,
    type,
    payload,
    error,
  };
}

test("Trace panel sorts events and projects all required categories", () => {
  const entries = projectTrace([
    event(8, "run_failed", { status: "failed" }, { code: "boom", message: "secret message" }),
    event(2, "route_selected", { name: "analysis", status: "ok" }),
    event(3, "skill_triggered", { name: "data-diagnosis" }),
    event(4, "tool_called", { name: "basic_stats" }),
    event(5, "trace_event", { event_type: "mcp_called", name: "echo" }),
    event(6, "trace_event", { event_type: "subagent_completed", name: "data_check" }),
    event(7, "trace_event", { event_type: "guardrail_decision", status: "allow" }),
    event(1, "approval_required", { action_type: "mcp_write" }),
  ]);
  assert.deepEqual(entries.map((entry) => entry.sequence), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(new Set(entries.map((entry) => entry.category)), new Set([
    "approval", "route", "skill", "tool", "MCP", "sub-agent", "guardrail", "error",
  ]));
});

test("Trace projection never includes raw arguments, metadata, paths, or error messages", () => {
  const entries = projectTrace([event(1, "tool_called", {
    name: "mcp_mock__echo",
    arguments: { token: "TOP-SECRET" },
    metadata: { file_path: "C:\\private\\sales.csv", action_hash: "private-hash" },
  }, { code: "SAFE_CODE", message: "TOP-SECRET error" })]);
  const serialized = JSON.stringify(entries);
  assert.equal(serialized.includes("TOP-SECRET"), false);
  assert.equal(serialized.includes("private\\sales.csv"), false);
  assert.equal(serialized.includes("private-hash"), false);
  assert.equal(entries[0].errorCode, "SAFE_CODE");
});

test("every M5 product state explains happening, continuation, and next action", () => {
  const states: ProductState[] = [
    "loading", "empty", "running", "partial", "stale",
    "waiting_approval", "completed", "failed", "cancelled",
  ];
  for (const state of states) {
    const description = describeProductState(state);
    assert.ok(description.happening);
    assert.ok(description.canContinue);
    assert.ok(description.nextAction);
  }
  assert.equal(productStateFromRun("partial"), "partial");
  assert.equal(productStateFromRun("expired"), "stale");
  assert.equal(productStateFromRun("waiting_approval"), "waiting_approval");
  assert.equal(productStateFromRun("cancelled"), "cancelled");
  assert.equal(isStaleError("dataset_not_found"), true);
  assert.equal(isStaleError("session_expired"), true);
  assert.equal(isStaleError("runtime_process_exit"), false);
});
