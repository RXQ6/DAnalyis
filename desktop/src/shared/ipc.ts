export const IPC_CHANNELS = {
  runsStart: "runs:start",
  runsCancel: "runs:cancel",
  filesSelect: "files:select",
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
  datasetId?: string;
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

export interface FilesSelectInput {
  threadId?: string;
}

export interface DatasetSummary {
  datasetId: string;
  filename: string;
  format: "csv" | "xlsx";
  sizeBytes: number;
  rowCount: number;
  columnCount: number;
  columns: Array<Record<string, unknown>>;
  dateRanges: Array<Record<string, unknown>>;
  derived: boolean;
  lineage: Record<string, unknown> | null;
}

export interface DatasetSelectionResult {
  status: "selected" | "cancelled";
  requestId?: string;
  threadId?: string;
  dataset?: DatasetSummary;
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
  selectDataset(input?: FilesSelectInput): Promise<IpcResult<DatasetSelectionResult>>;
  onAgentEvent(listener: (event: AgentEvent) => void): () => void;
}

export const PUBLIC_API_METHODS = ["startRun", "cancelRun", "selectDataset", "onAgentEvent"] as const;
