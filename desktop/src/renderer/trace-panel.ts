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
    label: humanEvent(underlying, categoryFor(outerType, underlying)),
    status: status ? humanEventStatus(status) : null,
    errorCode: errorCode ? errorCode.replace(/[\r\n\t]+/g, " ").slice(0, 80) : null,
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

function humanEvent(eventType: string, category: TraceCategory): string {
  const labels: Record<string, string> = {
    run_started: "开始分析", route_selected: "已选择处理方式",
    tool_called: "正在执行数据分析", tool_result: "数据分析步骤已完成",
    tool_completed: "数据分析步骤已完成", chart_ready: "图表已就绪",
    run_completed: "分析已完成", run_failed: "分析遇到问题",
    run_cancelled: "分析已停止", approval_required: "等待你确认操作",
    approval_resolved: "确认已处理", runtime_error: "分析服务遇到问题",
  };
  if (labels[eventType]) return labels[eventType];
  if (category === "tool") return "数据分析步骤已更新";
  if (category === "approval") return "确认状态已更新";
  if (category === "error") return "有一项分析步骤遇到问题";
  if (category === "route") return "已选择分析路径";
  if (category === "skill" || category === "sub-agent") return "分析步骤已更新";
  return "分析过程已更新";
}

function humanEventStatus(status: string): string {
  const labels: Record<string, string> = {
    running: "进行中", completed: "已完成", failed: "遇到问题",
    cancelled: "已停止", pending: "待处理", approved: "已确认",
    rejected: "已拒绝", partial: "部分完成",
  };
  return labels[status] ?? "已更新";
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
