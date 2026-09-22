import { randomUUID } from "node:crypto";

export const PROTOCOL_VERSION = 1;
export const MAX_JSONL_LINE_BYTES = 1024 * 1024;

export type RuntimeCommandType = "run.start" | "run.cancel" | "dataset.register";
export type AgentEventType =
  | "run_started"
  | "route_selected"
  | "skill_triggered"
  | "tool_called"
  | "tool_completed"
  | "chart_ready"
  | "approval_required"
  | "run_completed"
  | "run_failed"
  | "run_cancelled"
  | "trace_event"
  | "runtime_error";

export interface ProtocolError {
  code: string;
  message: string;
}

export interface ProtocolEnvelope {
  protocol_version: 1;
  request_id: string | null;
  run_id: string | null;
  thread_id: string | null;
  trace_id: string | null;
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
  error: ProtocolError | null;
}

export interface RuntimeCommand extends ProtocolEnvelope {
  request_id: string;
  type: RuntimeCommandType;
}

export interface RuntimeResponse extends ProtocolEnvelope {
  request_id: string;
  type: "response";
}

export interface AgentEvent extends ProtocolEnvelope {
  type: AgentEventType;
}

const EVENT_TYPES = new Set<AgentEventType>([
  "run_started",
  "route_selected",
  "skill_triggered",
  "tool_called",
  "tool_completed",
  "chart_ready",
  "approval_required",
  "run_completed",
  "run_failed",
  "run_cancelled",
  "trace_event",
  "runtime_error",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export function validateProtocolMessage(value: unknown): RuntimeResponse | AgentEvent {
  if (!isRecord(value)) {
    throw new Error("protocol message must be an object");
  }
  if (value.protocol_version !== PROTOCOL_VERSION) {
    throw new Error("unsupported protocol_version");
  }
  if (
    !nullableString(value.request_id) ||
    !nullableString(value.run_id) ||
    !nullableString(value.thread_id) ||
    !nullableString(value.trace_id)
  ) {
    throw new Error("protocol identifiers must be strings or null");
  }
  if (!Number.isSafeInteger(value.sequence) || Number(value.sequence) < 0) {
    throw new Error("sequence must be a non-negative integer");
  }
  if (typeof value.type !== "string" || !isRecord(value.payload)) {
    throw new Error("protocol type or payload is invalid");
  }
  if (
    value.error !== null &&
    (!isRecord(value.error) ||
      typeof value.error.code !== "string" ||
      typeof value.error.message !== "string")
  ) {
    throw new Error("protocol error is invalid");
  }
  if (value.type === "response") {
    if (typeof value.request_id !== "string") {
      throw new Error("response requires request_id");
    }
    return value as unknown as RuntimeResponse;
  }
  if (!EVENT_TYPES.has(value.type as AgentEventType)) {
    throw new Error(`unknown protocol message type: ${value.type}`);
  }
  return value as unknown as AgentEvent;
}

export function command(
  type: RuntimeCommandType,
  payload: Record<string, unknown>,
  identifiers: { runId?: string; threadId?: string } = {},
): RuntimeCommand {
  return {
    protocol_version: PROTOCOL_VERSION,
    request_id: `req_${randomUUID().replaceAll("-", "")}`,
    run_id: identifiers.runId ?? null,
    thread_id: identifiers.threadId ?? null,
    trace_id: null,
    sequence: 0,
    type,
    payload,
    error: null,
  };
}
