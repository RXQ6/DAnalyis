import assert from "node:assert/strict";
import test from "node:test";
import { validateRunsCancelInput } from "../src/main/ipc/runs-cancel";
import { validateFilesSelectInput } from "../src/main/ipc/files-select";
import { validateRunsStartInput } from "../src/main/ipc/runs-start";
import { validateApprovalInput, validateSessionInput } from "../src/main/ipc/session-approval";

test("runs:start accepts, normalizes, and validates thread id", () => {
  assert.deepEqual(validateRunsStartInput({ message: "  hello  ", threadId: "thread_1", datasetId: "ds_sales" }), {
    ok: true,
    value: { message: "hello", threadId: "thread_1", datasetId: "ds_sales" },
  });
});

test("runs:start rejects invalid renderer input", () => {
  for (const input of [null, "message", {}, { message: "   " }, { message: 42 }, { message: "ok", unexpected: true }, { message: "ok", threadId: "bad id" }, { message: "ok", datasetId: "bad" }]) {
    assert.equal(validateRunsStartInput(input).ok, false);
  }
});

test("files:select accepts only an optional thread id and never a renderer path", () => {
  assert.deepEqual(validateFilesSelectInput(undefined), { ok: true, value: {} });
  assert.deepEqual(validateFilesSelectInput({ threadId: "thread_1" }), {
    ok: true,
    value: { threadId: "thread_1" },
  });
  assert.equal(validateFilesSelectInput({ filePath: "C:\\secret.csv" }).ok, false);
  assert.equal(validateFilesSelectInput({ threadId: "bad id" }).ok, false);
});

test("runs:start enforces the message length limit", () => {
  assert.equal(validateRunsStartInput({ message: "x".repeat(4_000) }).ok, true);
  assert.equal(validateRunsStartInput({ message: "x".repeat(4_001) }).ok, false);
});

test("runs:cancel requires one valid run id", () => {
  assert.deepEqual(validateRunsCancelInput({ runId: "run_1" }), {
    ok: true,
    value: { runId: "run_1" },
  });
  assert.equal(validateRunsCancelInput({ runId: "bad id" }).ok, false);
  assert.equal(validateRunsCancelInput({ runId: "run_1", extra: true }).ok, false);
});

test("session and approval channels validate opaque runtime identifiers", () => {
  assert.deepEqual(validateSessionInput({ threadId: "thread_1" }), {
    ok: true,
    value: { threadId: "thread_1" },
  });
  assert.equal(validateSessionInput({ threadId: "bad id" }).ok, false);
  assert.deepEqual(validateApprovalInput({
    threadId: "thread_1", approvalId: "approval_1", actionHash: "hash-1",
  }), {
    ok: true,
    value: { threadId: "thread_1", approvalId: "approval_1", actionHash: "hash-1" },
  });
  assert.equal(validateApprovalInput({ threadId: "thread_1", approvalId: "approval_1" }).ok, false);
});
