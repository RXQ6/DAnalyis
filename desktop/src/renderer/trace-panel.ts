import type { AgentEvent } from "../shared/ipc";

export type TraceCategory =
  | "route" | "skill" | "tool" | "MCP" | "sub-agent"
  | "guardrail" | "approval" | "error" | "runtime";

export interface TraceEntry {
  sequence: number;
  category: TraceCategory;
  eventType: string;
  label: string;
  status: string | null;
  errorCode: string | null;
}

type TraceRecord = AgentEvent | Record<string, unknown>;

export function projectTrace(records: TraceRecord[], options: { useInputOrder?: boolean } = {}): TraceEntry[] {
  return records
    .map((record, index) => projectRecord(record, index + 1, options.useInputOrder === true))
    .sort((left, right) => left.sequence - right.sequence);
}

function projectRecord(record: TraceRecord, fallbackSequence: number, useInputOrder: boolean): TraceEntry {
  const raw: Record<string, unknown> = { ...record };
  const payload = isRecord(raw.payload) ? raw.payload : raw;
  const underlying = text(payload.event_type) ?? text(raw.event_type) ?? text(raw.type) ?? "runtime_event";
  const outerType = text(raw.type) ?? underlying;
  const name = text(payload.name) ?? text(raw.name);
  const status = text(payload.status) ?? text(raw.status);
  const error = isRecord(raw.error) ? raw.error : null;
  const errorCode = text(error?.code) ?? text(payload.error_code) ?? text(raw.error_code);
  const sequence = useInputOrder
    ? fallbackSequence
    : safeSequence(raw.sequence) ?? safeSequence(payload.runtime_sequence) ?? fallbackSequence;
  return {
    sequence,
    category: categoryFor(outerType, underlying),
    eventType: underlying,
    label: safeLabel(name ?? underlying),
    status: status ? safeLabel(status) : null,
    errorCode: errorCode ? safeLabel(errorCode) : null,
  };
}

function categoryFor(outerType: string, underlying: string): TraceCategory {
  const kind = `${outerType} ${underlying}`.toLowerCase();
  if (kind.includes("route")) return "route";
  if (kind.includes("skill")) return "skill";
  if (kind.includes("mcp")) return "MCP";
  if (kind.includes("subagent") || kind.includes("sub-agent")) return "sub-agent";
  if (kind.includes("guardrail")) return "guardrail";
  if (kind.includes("approval")) return "approval";
  if (kind.includes("error") || kind.includes("failed")) return "error";
  if (kind.includes("tool")) return "tool";
  return "runtime";
}

function safeLabel(value: string): string {
  return value.replace(/[\r\n\t]+/g, " ").slice(0, 160);
}

function safeSequence(value: unknown): number | null {
  return Number.isSafeInteger(value) && Number(value) >= 0 ? Number(value) : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
