export const IPC_CHANNELS = {
  runsStart: "runs:start",
  runsCancel: "runs:cancel",
  agentEvent: "agent:event",
} as const;

export interface IpcError {
  code: string;
  message: string;
  action?: string;
}

export type IpcResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: IpcError };

export interface RunsStartInput {
  message: string;
  threadId?: string;
}

export interface RunStartResult {
  status: "running";
  requestId: string;
  runId: string;
  threadId: string;
  traceId: string;
}

export interface RunsCancelInput {
  runId: string;
}

export interface RunCancelResult {
  status: "cancelled" | "already_finished";
  requestId: string;
  runId: string;
}

export interface AgentEvent {
  protocol_version: 1;
  request_id: string | null;
  run_id: string | null;
  thread_id: string | null;
  trace_id: string | null;
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
  error: { code: string; message: string } | null;
}

export interface DesktopApi {
  startRun(input: RunsStartInput): Promise<IpcResult<RunStartResult>>;
  cancelRun(input: RunsCancelInput): Promise<IpcResult<RunCancelResult>>;
  onAgentEvent(listener: (event: AgentEvent) => void): () => void;
}

export const PUBLIC_API_METHODS = ["startRun", "cancelRun", "onAgentEvent"] as const;
