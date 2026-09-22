import type { AgentEvent } from "../shared/ipc";

export type RunStatus =
  | "idle"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "waiting_approval"
  | "partial";

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
  if (event.type === "run_started") next.status = "running";
  if (event.type === "approval_required") next.status = "waiting_approval";
  if (event.type === "run_cancelled") next.status = "cancelled";
  if (event.type === "run_failed" || event.type === "runtime_error") {
    next.status = event.payload.partial === true ? "partial" : "failed";
    next.error = event.error;
    next.answer = typeof event.payload.response === "string" ? event.payload.response : next.answer;
  }
  if (event.type === "run_completed") {
    next.status = event.payload.partial === true ? "partial" : "completed";
    next.answer = typeof event.payload.response === "string" ? event.payload.response : null;
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
    };
  }
}
