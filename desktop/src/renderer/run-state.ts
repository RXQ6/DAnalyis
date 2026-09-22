import type { AgentEvent } from "../shared/ipc";

export type RunStatus =
  | "idle"
  | "running"
  | "resuming"
  | "completed"
  | "failed"
  | "cancelled"
  | "waiting_approval"
  | "rejected"
  | "expired"
  | "partial";

export interface ApprovalProjection {
  approvalId: string;
  actionHash: string;
  actionType: string;
  riskLevel: string;
  riskSummary: string;
  expiresAt: string;
}

export interface ChartProjection {
  spec: Record<string, unknown>;
  artifact: Record<string, unknown>;
}

export interface RunProjection {
  runId: string;
  status: RunStatus;
  lastSequence: number;
  answer: string | null;
  error: { code: string; message: string } | null;
  charts: ChartProjection[];
  events: AgentEvent[];
  approval: ApprovalProjection | null;
  partialMissing: string[];
}

export function initialProjection(runId: string): RunProjection {
  return {
    runId,
    status: "idle",
    lastSequence: 0,
    answer: null,
    error: null,
    charts: [],
    events: [],
    approval: null,
    partialMissing: [],
  };
}

export function applyRuntimeEvent(current: RunProjection, event: AgentEvent): RunProjection {
  if (event.run_id !== current.runId || event.sequence !== current.lastSequence + 1) {
    return current;
  }
  const next: RunProjection = {
    ...current,
    lastSequence: event.sequence,
    events: [...current.events, event],
  };
  if (event.type === "run_started") next.status = event.payload.status === "resuming" ? "resuming" : "running";
  if (event.type === "approval_required") {
    next.status = "waiting_approval";
    const payload = event.payload;
    if (
      typeof payload.approval_id === "string" && typeof payload.action_hash === "string" &&
      typeof payload.action_type === "string" && typeof payload.risk_level === "string" &&
      typeof payload.expires_at === "string"
    ) {
      next.approval = {
        approvalId: payload.approval_id,
        actionHash: payload.action_hash,
        actionType: payload.action_type,
        riskLevel: payload.risk_level,
        riskSummary: typeof payload.risk_summary === "string" ? payload.risk_summary : payload.risk_level,
        expiresAt: payload.expires_at,
      };
    }
  }
  if (event.type === "approval_resolved") {
    const status = event.payload.status;
    next.status = status === "expired" ? "expired" : status === "rejected" ? "rejected" : "completed";
    next.approval = null;
    if (event.error) next.error = event.error;
  }
  if (event.type === "run_cancelled") next.status = "cancelled";
  if (event.type === "run_failed" || event.type === "runtime_error") {
    next.status = event.payload.partial === true ? "partial" : "failed";
    next.error = event.error;
    next.answer = typeof event.payload.response === "string" ? event.payload.response : next.answer;
    next.partialMissing = missingItems(event.payload);
  }
  if (event.type === "run_completed") {
    next.status = event.payload.partial === true ? "partial" : "completed";
    next.answer = typeof event.payload.response === "string" ? event.payload.response : null;
    next.partialMissing = missingItems(event.payload);
  }
  if (event.type === "chart_ready") {
    const spec = event.payload.spec;
    const artifact = event.payload.artifact;
    if (isRecord(spec) && isRecord(artifact)) {
      next.charts = [...current.charts, { spec, artifact }];
    }
  }
  return next;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export class OrderedRunProjector {
  private projection: RunProjection;
  private readonly pending = new Map<number, AgentEvent>();

  constructor(runId: string) {
    this.projection = initialProjection(runId);
  }

  push(event: AgentEvent): RunProjection {
    if (event.run_id !== this.projection.runId || event.sequence <= this.projection.lastSequence) {
      return this.snapshot();
    }
    this.pending.set(event.sequence, event);
    let candidate = this.pending.get(this.projection.lastSequence + 1);
    while (candidate) {
      this.pending.delete(candidate.sequence);
      this.projection = applyRuntimeEvent(this.projection, candidate);
      candidate = this.pending.get(this.projection.lastSequence + 1);
    }
    return this.snapshot();
  }

  snapshot(): RunProjection {
    return {
      ...this.projection,
      charts: [...this.projection.charts],
      events: [...this.projection.events],
      approval: this.projection.approval ? { ...this.projection.approval } : null,
      partialMissing: [...this.projection.partialMissing],
    };
  }
}

function missingItems(payload: Record<string, unknown>): string[] {
  if (Array.isArray(payload.missing)) {
    return payload.missing.filter((value): value is string => typeof value === "string").slice(0, 20);
  }
  if (typeof payload.missing === "string") return [payload.missing];
  return payload.partial === true ? ["Some requested tool results are unavailable."] : [];
}

export function eventBelongsToSession(event: AgentEvent, threadId: string | undefined): boolean {
  return threadId === undefined || event.thread_id === null || event.thread_id === threadId;
}
