import { EventEmitter } from "node:events";
import {
  MAX_JSONL_LINE_BYTES,
  command,
  type AgentEvent,
  type RuntimeCommand,
  type RuntimeResponse,
  validateProtocolMessage,
} from "./protocol";
import { RuntimeProcessManager } from "./processManager";

export class RuntimeRequestError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export interface StartedRun {
  requestId: string;
  runId: string;
  threadId: string;
  traceId: string;
  status: "running" | "resuming";
}

export interface CancelledRun {
  requestId: string;
  runId: string;
  status: "cancelled" | "already_finished";
}

export interface RegisteredDataset {
  requestId: string;
  threadId: string;
  dataset: Record<string, unknown>;
}

export interface RuntimeSessionSummary {
  threadId: string;
  updatedAt: string;
  status: string;
  summary: string;
}

export interface RuntimeSessionSnapshot {
  threadId: string;
  messages: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  traceIds: string[];
}

interface PendingRequest {
  resolve: (response: RuntimeResponse) => void;
  reject: (error: Error) => void;
}

const TERMINAL = new Set(["run_completed", "run_failed", "run_cancelled", "approval_required", "approval_resolved"]);

export class RuntimeClient {
  private readonly emitter = new EventEmitter();
  private readonly pending = new Map<string, PendingRequest>();
  private readonly sequences = new Map<string, number>();
  private readonly activeRuns = new Map<string, AgentEvent>();
  private buffer = "";

  constructor(readonly processManager: RuntimeProcessManager) {
    processManager.on("stdout", (chunk: Buffer) => this.consume(chunk));
    processManager.on("stderr", (message: string) => this.emitter.emit("stderr", message));
    processManager.on(
      "exit",
      (info: { code: number | null; signal: NodeJS.Signals | null; expected: boolean }) =>
        this.handleExit(info),
    );
  }

  async startRun(message: string, threadId?: string, datasetId?: string): Promise<StartedRun> {
    const response = await this.request(
      command("run.start", { message, ...(datasetId ? { dataset_id: datasetId } : {}) }, { threadId }),
    );
    if (!response.run_id || !response.thread_id || !response.trace_id) {
      throw new RuntimeRequestError("INVALID_RUNTIME_RESPONSE", "Runtime did not return run identifiers");
    }
    return {
      requestId: response.request_id,
      runId: response.run_id,
      threadId: response.thread_id,
      traceId: response.trace_id,
      status: "running",
    };
  }

  async registerDataset(filePath: string, threadId?: string): Promise<RegisteredDataset> {
    const response = await this.request(
      command("dataset.register", { file_path: filePath }, { threadId }),
    );
    if (!response.thread_id || typeof response.payload.dataset !== "object" || response.payload.dataset === null) {
      throw new RuntimeRequestError("INVALID_RUNTIME_RESPONSE", "Runtime did not return a dataset summary");
    }
    return {
      requestId: response.request_id,
      threadId: response.thread_id,
      dataset: response.payload.dataset as Record<string, unknown>,
    };
  }

  async cancelRun(runId: string): Promise<CancelledRun> {
    const response = await this.request(command("run.cancel", {}, { runId }));
    return {
      requestId: response.request_id,
      runId,
      status: response.payload.status === "already_finished" ? "already_finished" : "cancelled",
    };
  }

  async listSessions(): Promise<RuntimeSessionSummary[]> {
    const response = await this.request(command("session.list", { limit: 20 }));
    const sessions = response.payload.sessions;
    if (!Array.isArray(sessions)) {
      throw new RuntimeRequestError("INVALID_RUNTIME_RESPONSE", "Runtime did not return sessions");
    }
    return sessions.map((item) => {
      if (!isRecord(item) || typeof item.thread_id !== "string" || typeof item.updated_at !== "string") {
        throw new RuntimeRequestError("INVALID_RUNTIME_RESPONSE", "Runtime returned an invalid session");
      }
      return {
        threadId: item.thread_id,
        updatedAt: item.updated_at,
        status: typeof item.status === "string" ? item.status : "active",
        summary: typeof item.summary === "string" ? item.summary : "",
      };
    });
  }

  async getSession(threadId: string, resume = false): Promise<RuntimeSessionSnapshot> {
    const response = await this.request(command(resume ? "session.resume" : "session.get", {}, { threadId }));
    const conversation = response.payload.conversation;
    if (!response.thread_id || !Array.isArray(response.payload.messages) || !Array.isArray(response.payload.events) || !isRecord(conversation)) {
      throw new RuntimeRequestError("INVALID_RUNTIME_RESPONSE", "Runtime returned an invalid session snapshot");
    }
    return {
      threadId: response.thread_id,
      messages: response.payload.messages.filter(isRecord),
      events: response.payload.events.filter(isRecord),
      traceIds: Array.isArray(conversation.trace_ids)
        ? conversation.trace_ids.filter((value): value is string => typeof value === "string")
        : [],
    };
  }

  async resolveApproval(
    threadId: string,
    approvalId: string,
    actionHash: string,
    decision: "approve" | "reject",
  ): Promise<StartedRun> {
    const response = await this.request(command(
      "approval.resolve",
      { approval_id: approvalId, action_hash: actionHash, decision },
      { threadId },
    ));
    if (!response.run_id || !response.thread_id || !response.trace_id) {
      throw new RuntimeRequestError("INVALID_RUNTIME_RESPONSE", "Runtime did not return approval run identifiers");
    }
    return {
      requestId: response.request_id,
      runId: response.run_id,
      threadId: response.thread_id,
      traceId: response.trace_id,
      status: response.payload.status === "resuming" ? "resuming" : "running",
    };
  }

  onEvent(listener: (event: AgentEvent) => void): () => void {
    this.emitter.on("event", listener);
    return () => this.emitter.off("event", listener);
  }

  onStderr(listener: (message: string) => void): () => void {
    this.emitter.on("stderr", listener);
    return () => this.emitter.off("stderr", listener);
  }

  private async request(message: RuntimeCommand): Promise<RuntimeResponse> {
    await this.processManager.start();
    return new Promise<RuntimeResponse>((resolve, reject) => {
      this.pending.set(message.request_id, { resolve, reject });
      try {
        this.processManager.sendLine(JSON.stringify(message));
      } catch (error) {
        this.pending.delete(message.request_id);
        reject(error instanceof Error ? error : new Error("Runtime request failed"));
      }
    }).then((response) => {
      if (response.error) {
        throw new RuntimeRequestError(response.error.code, response.error.message);
      }
      return response;
    });
  }

  private consume(chunk: Buffer): void {
    this.buffer += chunk.toString("utf8");
    let newline = this.buffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline).replace(/\r$/, "");
      this.buffer = this.buffer.slice(newline + 1);
      if (Buffer.byteLength(line, "utf8") > MAX_JSONL_LINE_BYTES) {
        this.protocolFailure("PROTOCOL_FRAME_TOO_LARGE", "Runtime emitted an oversized JSONL frame");
      } else if (line) {
        this.consumeLine(line);
      }
      newline = this.buffer.indexOf("\n");
    }
  }

  private consumeLine(line: string): void {
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      this.protocolFailure("INVALID_RUNTIME_JSON", "Runtime stdout contained invalid JSON");
      return;
    }
    let message: RuntimeResponse | AgentEvent;
    try {
      message = validateProtocolMessage(parsed);
    } catch (error) {
      this.protocolFailure(
        "INVALID_RUNTIME_MESSAGE",
        error instanceof Error ? error.message : "Runtime message is invalid",
      );
      return;
    }
    if (message.type === "response") {
      const pending = this.pending.get(message.request_id);
      if (pending) {
        this.pending.delete(message.request_id);
        pending.resolve(message);
      }
      return;
    }
    this.acceptEvent(message);
  }

  private acceptEvent(event: AgentEvent): void {
    if (event.run_id) {
      const previous = this.sequences.get(event.run_id) ?? 0;
      if (event.sequence !== previous + 1) {
        this.protocolFailure(
          "RUNTIME_SEQUENCE_ERROR",
          `Expected sequence ${previous + 1} for ${event.run_id}, received ${event.sequence}`,
          event,
        );
        return;
      }
      this.sequences.set(event.run_id, event.sequence);
      if (event.type === "run_started") {
        this.activeRuns.set(event.run_id, event);
      }
      if (TERMINAL.has(event.type)) {
        this.activeRuns.delete(event.run_id);
      }
    }
    this.emitter.emit("event", event);
  }

  private protocolFailure(code: string, message: string, source?: AgentEvent): void {
    const runId = source?.run_id ?? null;
    const sequence = runId ? (this.sequences.get(runId) ?? 0) + 1 : 0;
    const event: AgentEvent = {
      protocol_version: 1,
      request_id: source?.request_id ?? null,
      run_id: runId,
      thread_id: source?.thread_id ?? null,
      trace_id: source?.trace_id ?? null,
      sequence,
      type: "runtime_error",
      payload: { status: "failed" },
      error: { code, message },
    };
    if (runId) {
      this.sequences.set(runId, sequence);
      this.activeRuns.delete(runId);
    }
    this.emitter.emit("event", event);
  }

  private handleExit(info: {
    code: number | null;
    signal: NodeJS.Signals | null;
    expected: boolean;
  }): void {
    const error = new RuntimeRequestError(
      "RUNTIME_PROCESS_EXIT",
      `Python Runtime exited (code=${String(info.code)}, signal=${String(info.signal)})`,
    );
    for (const pending of this.pending.values()) {
      pending.reject(error);
    }
    this.pending.clear();
    if (info.expected) {
      return;
    }
    if (this.activeRuns.size === 0) {
      this.protocolFailure(error.code, error.message);
      return;
    }
    for (const event of this.activeRuns.values()) {
      this.protocolFailure(error.code, error.message, event);
    }
    this.activeRuns.clear();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
