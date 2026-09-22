import type { RunStatus } from "./run-state";

export type ProductState =
  | "loading" | "empty" | "running" | "partial" | "stale"
  | "waiting_approval" | "completed" | "failed" | "cancelled";

export interface ProductStateDescriptor {
  state: ProductState;
  happening: string;
  canContinue: string;
  nextAction: string;
}

const DESCRIPTORS: Record<ProductState, Omit<ProductStateDescriptor, "state">> = {
  loading: {
    happening: "Loading Runtime state.",
    canContinue: "Please wait for the current request to finish.",
    nextAction: "No action is required yet.",
  },
  empty: {
    happening: "There is no active result to display.",
    canContinue: "You can start or restore a session.",
    nextAction: "Choose a file, select a session, or send a message.",
  },
  running: {
    happening: "The Python Runtime is processing this run.",
    canContinue: "You may wait or cancel the active run.",
    nextAction: "Watch Trace events or choose Stop.",
  },
  partial: {
    happening: "Some valid results are available, but part of the run failed or is missing.",
    canContinue: "Available answers and charts are preserved.",
    nextAction: "Review the missing-content notice and retry if offered.",
  },
  stale: {
    happening: "The selected Session, Dataset, approval, or cached state is stale.",
    canContinue: "It cannot be used as current Runtime state without refresh.",
    nextAction: "Refresh Sessions or choose the Dataset again.",
  },
  waiting_approval: {
    happening: "The Runtime is waiting for approval of one guarded action.",
    canContinue: "The action will not run until Python accepts Approve.",
    nextAction: "Review the approval card, then Approve or Reject.",
  },
  completed: {
    happening: "The run completed successfully.",
    canContinue: "The result is available and a new request can be started.",
    nextAction: "Review the answer, chart, or Trace panel.",
  },
  failed: {
    happening: "The run or IPC request failed.",
    canContinue: "The app remains available; completed high-risk actions are not replayed.",
    nextAction: "Review the structured error and use Retry when available.",
  },
  cancelled: {
    happening: "The active run was cancelled.",
    canContinue: "No later business events from that run will be applied.",
    nextAction: "Edit the request or send it again when ready.",
  },
};

export function describeProductState(state: ProductState): ProductStateDescriptor {
  return { state, ...DESCRIPTORS[state] };
}

export function productStateFromRun(status: RunStatus): ProductState {
  if (status === "running" || status === "resuming") return "running";
  if (status === "partial") return "partial";
  if (status === "waiting_approval") return "waiting_approval";
  if (status === "completed") return "completed";
  if (status === "cancelled") return "cancelled";
  if (status === "expired") return "stale";
  if (status === "failed" || status === "rejected") return "failed";
  return "empty";
}

export function isStaleError(code: string): boolean {
  const normalized = code.toLowerCase();
  return normalized.includes("stale") || normalized.includes("expired") || normalized.includes("not_found");
}
