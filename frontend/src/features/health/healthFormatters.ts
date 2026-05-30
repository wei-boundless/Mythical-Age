import type { HealthSystemOverview, HealthTaskRecord } from "@/lib/api";

export type HealthPage = "overview" | "tasks" | "maintenance" | "cost";
export type TokenChartMode = "daily" | "six_hour";
export type MaintenanceBucket = "static" | "completed" | "failed" | "diagnostics";

export function numberValue(value: unknown, fallback = 0) {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function timeLabel(value: unknown) {
  const seconds = numberValue(value);
  if (!seconds) return "-";
  return new Date(seconds * 1000).toLocaleString();
}

export function durationLabel(seconds: unknown) {
  const total = Math.max(0, Math.round(numberValue(seconds)));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return `${minutes}m ${rest}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function tokenLabel(value: unknown) {
  const tokens = numberValue(value);
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(2)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
  return String(Math.round(tokens));
}

export function tokenSourceLabel(value: unknown) {
  const source = String(value || "");
  const map: Record<string, string> = {
    provider_usage: "provider usage 精确记录",
    local_prediction: "请求前本地预测",
    trace_estimate: "旧任务轨迹估算",
    none: "暂无记录",
  };
  return map[source] || source || "暂无记录";
}

export function tokenBuckets(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => item as Record<string, unknown>)
    : [];
}

export function compactNumber(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(value));
}

export function percentLabel(value: number) {
  if (!Number.isFinite(value)) return "0%";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

export function signedTokenLabel(value: number) {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${tokenLabel(Math.abs(value))}`;
}

export function tokenSourceClass(value: unknown) {
  const source = String(value || "");
  if (source === "provider_usage") return "health-token-source health-token-source--exact";
  if (source === "local_prediction") return "health-token-source health-token-source--predicted";
  if (source === "trace_estimate") return "health-token-source health-token-source--trace";
  return "health-token-source";
}

export function statusLabel(status: string) {
  const map: Record<string, string> = {
    created: "已创建",
    queued: "排队中",
    running: "运行中",
    waiting_approval: "等待确认",
    paused: "已暂停",
    completed: "已完成",
    failed: "失败",
    aborted: "已中止",
    cancelled: "已取消",
  };
  return map[status] || status || "未知";
}

export function statusLabelValue(value: unknown) {
  return statusLabel(String(value || ""));
}

export function riskLabel(level: string) {
  const map: Record<string, string> = {
    normal: "正常",
    info: "提示",
    warning: "注意",
    high: "高风险",
    critical: "严重",
  };
  return map[level] || level || "正常";
}

export function riskLabelValue(value: unknown) {
  return riskLabel(String(value || ""));
}

export function riskClass(level: string) {
  if (level === "critical") return "health-pill health-pill--danger";
  if (level === "high") return "health-pill health-pill--warning";
  if (level === "warning") return "health-pill health-pill--notice";
  return "health-pill";
}

export function byRisk(a: HealthTaskRecord, b: HealthTaskRecord) {
  const order: Record<string, number> = { critical: 0, high: 1, warning: 2, normal: 3 };
  return (order[a.risk_level] ?? 9) - (order[b.risk_level] ?? 9)
    || numberValue(b.updated_at) - numberValue(a.updated_at);
}

export function publicTitle(value: unknown) {
  const candidate = String(value ?? "").trim();
  if (!candidate) return "";
  const lowered = candidate.toLowerCase();
  if (
    lowered.startsWith("task:")
    || lowered.startsWith("taskrun:")
    || lowered.startsWith("turn:")
    || lowered.startsWith("turnrun:")
    || lowered.startsWith("session:")
    || lowered.startsWith("taskinst:")
    || lowered.startsWith("coordrun:")
  ) {
    return "";
  }
  return candidate;
}

export function runOrdinal(value: unknown) {
  const text = String(value ?? "");
  const match = text.match(/:([0-9]+)(?::[^:]*)?$/);
  return match ? ` #${match[1]}` : "";
}

export function taskDisplayTitle(
  task: Pick<HealthTaskRecord, "title" | "task_id" | "task_run_id" | "status"> | Record<string, unknown> | null,
) {
  if (!task) return "未选择任务";
  const rawTitle = "title" in task ? task.title : undefined;
  const rawTaskId = "task_id" in task ? task.task_id : undefined;
  const rawRunId = "task_run_id" in task ? task.task_run_id : undefined;
  const title = publicTitle(rawTitle) || publicTitle(rawTaskId);
  if (title) return title;
  const status = String(("status" in task ? task.status : "") || "");
  if (status === "failed") return `会话运行失败${runOrdinal(rawRunId)}`;
  if (status === "completed" || status === "success") return `会话运行完成${runOrdinal(rawRunId)}`;
  if (status === "blocked" || status === "waiting_approval") return `会话运行等待处理${runOrdinal(rawRunId)}`;
  return `会话运行${runOrdinal(rawRunId)}`;
}

export function sessionLabel(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text) return "会话记录";
  const match = text.match(/session-([a-f0-9]{6})/i);
  if (match) return `会话 ${match[1]}`;
  if (text.toLowerCase().startsWith("session:") || text.toLowerCase().startsWith("session-")) {
    return "会话记录";
  }
  return text;
}

export function taskSecondaryLabel(row: Record<string, unknown>) {
  const agent = publicTitle(row.agent_id);
  if (agent) return agent;
  return sessionLabel(row.session_id);
}

export function taskTitle(task: HealthTaskRecord | null) {
  return taskDisplayTitle(task);
}

export function costConclusion(overview: HealthSystemOverview) {
  const highPressure = numberValue(overview.token_usage.summary.high_pressure_session_count);
  const slowTasks = numberValue(overview.efficiency.summary.slow_task_count);
  if (highPressure > 0 && slowTasks > 0) {
    return "Token 压力和慢任务同时存在，建议优先检查上下文注入、任务循环和工具等待。";
  }
  if (highPressure > 0) {
    return "当前主要压力来自高 token 会话，建议压缩上下文或拆分任务。";
  }
  if (slowTasks > 0) {
    return "当前主要压力来自慢任务，建议检查执行等待、循环重试和人工确认。";
  }
  return "当前运行成本处于可控状态，继续观察趋势和高消耗任务即可。";
}
