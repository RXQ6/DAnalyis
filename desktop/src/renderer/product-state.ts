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
    happening: "正在准备分析工作区。",
    canContinue: "当前请求完成后会自动更新。",
    nextAction: "请稍候。",
  },
  empty: {
    happening: "还没有分析结果。",
    canContinue: "可以从数据文件或历史分析开始。",
    nextAction: "选择文件，然后提出问题。",
  },
  running: {
    happening: "正在根据数据分析你的问题。",
    canContinue: "可以等待结果，也可以停止本次分析。",
    nextAction: "需要时展开“分析过程”查看进度。",
  },
  partial: {
    happening: "部分分析结果已完成。",
    canContinue: "已得到的回答和图表仍可查看。",
    nextAction: "查看缺失内容，需要时重试。",
  },
  stale: {
    happening: "当前内容需要刷新。",
    canContinue: "刷新后可重新确认可用的数据与分析。",
    nextAction: "刷新最近分析，或重新选择数据文件。",
  },
  waiting_approval: {
    happening: "分析已暂停，等待你确认一项操作。",
    canContinue: "未经确认，该操作不会执行。",
    nextAction: "检查下方操作卡，然后确认或拒绝。",
  },
  completed: {
    happening: "分析已完成。",
    canContinue: "结果已可查看，也可以继续提问。",
    nextAction: "查看摘要与图表。",
  },
  failed: {
    happening: "本次分析遇到问题。",
    canContinue: "工作区仍可使用。",
    nextAction: "查看问题说明，需要时重试。",
  },
  cancelled: {
    happening: "本次分析已停止。",
    canContinue: "可以修改问题后重新开始。",
    nextAction: "准备好后再次发送。",
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
