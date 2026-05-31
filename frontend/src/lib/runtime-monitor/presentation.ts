import type { RuntimeMonitorItem } from "./types";

const WAITING_STATUSES = new Set(["waiting_executor", "waiting_approval", "blocked"]);
const INTERNAL_ID_PREFIXES = ["task:", "taskrun:", "turn:", "turnrun:", "session:", "taskinst:", "coordrun:", "grun:"];

const EVENT_LABELS: Record<string, string> = {
  active_task_steer_recorded: "收到补充要求",
  agent_runtime_planning_phase_checked: "处理阶段已检查",
  agent_turn_blocked: "需要处理",
  bounded_observation_recorded: "观察结果已记录",
  executor_observation_recorded: "操作结果已记录",
  graph_run_created: "处理已开始",
  runtime_live_monitor: "进展同步",
  runtime_step_summary: "进展已更新",
  step_summary_recorded: "进展已更新",
  task_run_executor_scheduled: "等待继续",
  task_run_executor_started: "处理已开始",
  task_run_lifecycle_finished: "处理已完成",
  task_run_lifecycle_started: "处理已开始",
  task_run_lifecycle_waiting_approval: "等待确认",
  task_run_lifecycle_waiting_executor: "等待继续",
  task_run_started: "处理已开始",
  user_work_instruction_recorded: "收到补充要求",
};

export function statusLabel(status: string) {
  if (status === "running" || status === "created") return "进行中";
  if (status === "waiting_executor") return "等待继续";
  if (status === "waiting_approval") return "等待审批";
  if (status === "blocked") return "受阻";
  if (status === "completed" || status === "success") return "已完成";
  if (status === "failed") return "失败";
  if (status === "aborted") return "已停止";
  return status || "未知";
}

export function monitorStatusLabel(item: RuntimeMonitorItem) {
  if (item.bucket === "diagnostics" || item.lifecycle === "stale" || item.stale) return "需诊断";
  return statusLabel(item.status);
}

export function publicMonitorText(value: unknown) {
  const candidate = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
  return looksInternalIdentifier(candidate) ? "" : candidate;
}

export function monitorEventLabel(eventType: unknown) {
  const normalized = String(eventType ?? "").trim().toLowerCase();
  if (!normalized) return "";
  return EVENT_LABELS[normalized] || "进展同步";
}

export function monitorProgressLabel(item: RuntimeMonitorItem, fallback = "") {
  const progress = item.latest_progress && typeof item.latest_progress === "object" && !Array.isArray(item.latest_progress)
    ? item.latest_progress as Record<string, unknown>
    : {};
  const graphStatus = item.graph_status && typeof item.graph_status === "object" && !Array.isArray(item.graph_status)
    ? item.graph_status as Record<string, unknown>
    : {};
  return publicMonitorText(progress.tool_status)
    || publicMonitorText(progress.observation)
    || publicMonitorText(progress.current_judgment)
    || publicMonitorText(progress.next_action)
    || publicMonitorText(progress.completion_status)
    || publicMonitorText(progress.summary)
    || publicMonitorText(item.latest_public_progress_note)
    || publicMonitorText(item.latest_step_summary)
    || publicMonitorText(item.summary)
    || publicMonitorText(graphStatus.current_stage_summary)
    || monitorEventLabel(item.latest_event_type)
    || fallback;
}

export function formatDuration(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds || 0));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = safe % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

export function formatTime(timestamp: number) {
  if (!timestamp) return "-";
  return new Date(timestamp * 1000).toLocaleTimeString();
}

export function monitorTimeLabel(item: RuntimeMonitorItem, nowSeconds?: number) {
  const now = Number.isFinite(nowSeconds) ? Number(nowSeconds) : 0;
  const startedAt = Number(item.started_at || 0);
  const lastActivityAt = Number(item.last_activity_at || item.latest_event_at || item.updated_at || 0);
  const durationSeconds = Number(item.duration_seconds ?? 0);
  const live = item.resource_class === "dynamic" && item.bucket === "running";
  const liveDuration = live && now && startedAt ? Math.max(durationSeconds, now - startedAt) : durationSeconds;
  const staleAge = now && lastActivityAt
    ? Math.max(Number(item.last_activity_age_seconds ?? 0), now - lastActivityAt)
    : Number(item.last_activity_age_seconds ?? 0);
  const duration = formatDuration(liveDuration);
  if (live) return `运行 ${duration}`;
  if (item.bucket === "diagnostics" || item.lifecycle === "stale" || item.stale) return `停滞 ${formatDuration(staleAge)}`;
  if (item.resource_class === "static") return `耗时 ${duration}`;
  return `结束 ${formatTime(Number(item.last_activity_at || item.updated_at || 0))}`;
}

export function taskTitle(item: RuntimeMonitorItem) {
  return publicTitle(item.project_title) || publicTitle(item.title) || fallbackTitle(item);
}

export function isWaitingStatus(status: string) {
  return WAITING_STATUSES.has(status);
}

function publicTitle(value: unknown) {
  const candidate = String(value ?? "").trim();
  if (!candidate || looksInternalIdentifier(candidate)) return "";
  return candidate;
}

function looksInternalIdentifier(value: string) {
  const lowered = value.trim().toLowerCase();
  return INTERNAL_ID_PREFIXES.some((prefix) => lowered.startsWith(prefix));
}

function fallbackTitle(item: RuntimeMonitorItem) {
  if (item.lifecycle === "completed" || item.bucket === "completed") return "会话运行已完成";
  if (item.lifecycle === "failed" || item.bucket === "failed") return "会话运行失败";
  if (item.bucket === "diagnostics" || item.lifecycle === "stale" || item.stale) return "运行状态需诊断";
  if (item.lifecycle === "waiting" || item.lifecycle === "action_required") return "会话运行等待处理";
  return "会话运行中";
}
