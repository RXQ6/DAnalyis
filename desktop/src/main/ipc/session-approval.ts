import type { ApprovalInput, SessionInput } from "../../shared/ipc";

type Validation<T> = { ok: true; value: T } | { ok: false; message: string };
const ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function validateSessionInput(input: unknown): Validation<SessionInput> {
  if (!record(input) || typeof input.threadId !== "string" || !ID.test(input.threadId)) {
    return { ok: false, message: "threadId is invalid" };
  }
  return { ok: true, value: { threadId: input.threadId } };
}

export function validateApprovalInput(input: unknown): Validation<ApprovalInput> {
  if (!record(input)) return { ok: false, message: "approval input must be an object" };
  if (typeof input.threadId !== "string" || !ID.test(input.threadId)) {
    return { ok: false, message: "threadId is invalid" };
  }
  if (typeof input.approvalId !== "string" || !ID.test(input.approvalId)) {
    return { ok: false, message: "approvalId is invalid" };
  }
  if (typeof input.actionHash !== "string" || input.actionHash.length < 1 || input.actionHash.length > 256) {
    return { ok: false, message: "actionHash is invalid" };
  }
  return {
    ok: true,
    value: { threadId: input.threadId, approvalId: input.approvalId, actionHash: input.actionHash },
  };
}
