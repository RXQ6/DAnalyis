import type { DatasetSummary, SessionSnapshot } from "../shared/ipc";

const INTERNAL_TEXT = /(?:\b(?:thread|trace|run|request|approval)_[a-z0-9_-]+\b|\b(?:event_type|tool[_\s-]*args|action_hash|api[_-]?key|authorization|bearer)\b|\bsequence\s*[:=]\s*\d+\b|\braw\s+json\b|\bsk-[a-z0-9_-]{8,}\b|[A-Za-z]:\\|\/[^\s]+\.(?:csv|xlsx))/i;
const LABELS: Record<string, string> = {
  metric: "指标", operation: "计算方式", value: "结果", total: "总计",
  sum: "总和", count: "数量", average: "平均值", mean: "平均值",
  group: "分类", label: "项目", date: "日期", x: "项目", y: "数值",
  groups: "分组结果", items: "项目结果", points: "数据点", result: "结果",
  validCount: "有效记录数",
};
const OPERATIONS: Record<string, string> = {
  sum: "求和", count: "计数", average: "平均值", mean: "平均值",
  max: "最大值", min: "最小值", median: "中位数",
};

export function sessionTitle(snapshot: SessionSnapshot): string {
  const firstQuestion = snapshot.messages.find((message) => message.role === "user" && typeof message.content === "string");
  return readableTitle(typeof firstQuestion?.content === "string" ? firstQuestion.content : "");
}

export function readableTitle(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim().replace(/[。！？?]+$/, "");
  if (!normalized || looksStructured(normalized) || INTERNAL_TEXT.test(normalized)) return "未命名分析";
  return normalized.length > 34 ? `${normalized.slice(0, 33)}…` : normalized;
}

export function datasetDescription(dataset: DatasetSummary): string {
  return `${dataset.filename} · ${dataset.format.toUpperCase()} · ${dataset.rowCount} 行 · ${dataset.columnCount} 列`;
}

export function humanStatus(value: string): string {
  const labels: Record<string, string> = {
    loading: "准备中", empty: "待开始", idle: "待开始", active: "可继续",
    running: "分析中", resuming: "继续分析", completed: "已完成",
    partial: "部分完成", stale: "需刷新", waiting_approval: "待确认",
    failed: "遇到问题", rejected: "已拒绝", cancelled: "已停止", expired: "已过期",
  };
  return labels[value] ?? "已保存";
}

export function humanAction(value: string): string {
  if (value === "mcp_write") return "向外部服务写入数据";
  if (value === "file_write") return "修改文件";
  return "需要确认的外部操作";
}

export function humanRisk(value: string): string {
  if (value === "high" || /high risk/i.test(value)) return "高风险 · 请确认目标和影响后再继续";
  if (value === "medium" || /medium risk/i.test(value)) return "需要确认 · 请检查操作内容";
  return "请检查操作内容后再继续";
}

export function humanError(code: string, message: string): string {
  if (/not_found|stale|expired/i.test(code)) return "当前内容已失效或不可用，请刷新后重试。";
  if (/invalid_chart/i.test(code)) return "本次图表数据无法展示，其他分析结果仍可查看。";
  if (/ipc|runtime_unavailable/i.test(code)) return "分析服务暂时不可用，请稍后重试。";
  if (/invalid_run_input/i.test(code)) return "请先输入一个分析问题。";
  return safePlainText(message) ?? "本次操作遇到问题，请重试。";
}

export type PresentedAnswer = { kind: "text"; text: string } | { kind: "table"; rows: Array<[string, string]> } | { kind: "unsupported" };

export function presentAnswer(answer: string): PresentedAnswer {
  const trimmed = answer.trim();
  const candidate = trimmed.replace(/^(?:分析完成|分析结果|Analysis complete)\s*[:：]\s*/i, "");
  if (!looksStructured(candidate)) return { kind: "text", text: redactInternalText(answer) };
  try {
    const parsed: unknown = JSON.parse(candidate);
    const rows: Array<[string, string]> = [];
    collectRows(parsed, rows, "", 0);
    return rows.length ? { kind: "table", rows: rows.slice(0, 50) } : { kind: "unsupported" };
  } catch {
    return { kind: "unsupported" };
  }
}

export function safePlainText(value: string): string | null {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized || looksStructured(normalized) || INTERNAL_TEXT.test(normalized)) return null;
  return normalized.slice(0, 240);
}

function looksStructured(value: string): boolean {
  return /^[\[{]/.test(value) || /\{\s*"[^"]+"\s*:/.test(value);
}

function redactInternalText(value: string): string {
  return value
    .replace(/\b(?:thread|trace|run|request|approval)_[a-z0-9_-]+\b/gi, "〈内部标识〉")
    .replace(/\bsk-[a-z0-9_-]{8,}\b/gi, "〈已隐藏〉")
    .replace(/\bsequence\s*[:=]\s*\d+\b/gi, "〈内部顺序〉")
    .replace(/\b(?:tool[_\s-]*args|raw\s+json)\b/gi, "〈内部数据〉")
    .replace(/\b(?:api[_-]?key|authorization|bearer)\s*[:=]\s*\S+/gi, "〈已隐藏〉");
}

function collectRows(value: unknown, output: Array<[string, string]>, prefix: string, depth: number): void {
  if (depth > 3 || output.length >= 50) return;
  if (Array.isArray(value)) {
    value.slice(0, 20).forEach((item, index) => collectRows(item, output, `${prefix}${prefix ? " · " : ""}${index + 1}`, depth + 1));
    return;
  }
  if (typeof value === "object" && value !== null) {
    for (const [key, item] of Object.entries(value)) {
      const label = LABELS[key];
      if (!label) continue;
      const presented = key === "operation" && typeof item === "string" ? OPERATIONS[item] ?? item : item;
      collectRows(presented, output, `${prefix}${prefix ? " · " : ""}${label}`, depth + 1);
    }
    return;
  }
  if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") return;
  const display = String(value);
  if (prefix && display.length <= 160 && !INTERNAL_TEXT.test(display) && !looksStructured(display)) output.push([prefix, display]);
}
