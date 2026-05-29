import type { GlobalRuntimeMonitorItem } from "@/lib/api";

const WAITING_STATUSES = new Set(["waiting_executor", "waiting_approval", "blocked"]);

export function statusLabel(status: string) {
  if (status === "running" || status === "created") return "进行中";
  if (status === "waiting_executor") return "等待执行器";
  if (status === "waiting_approval") return "等待审批";
  if (status === "blocked") return "受阻";
  if (status === "completed" || status === "success") return "已完成";
  if (status === "failed") return "失败";
  if (status === "aborted") return "已停止";
  return status || "未知";
}

export function monitorStatusLabel(item: GlobalRuntimeMonitorItem) {
  if (item.bucket === "diagnostics" || item.lifecycle === "stale" || item.stale) return "需诊断";
  return statusLabel(item.status);
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

export function monitorTimeLabel(item: GlobalRuntimeMonitorItem, nowSeconds?: number) {
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

export function taskTitle(item: GlobalRuntimeMonitorItem) {
  return publicTitle(item.project_title) || publicTitle(item.title) || fallbackTitle(item);
}

export function isWaitingStatus(status: string) {
  return WAITING_STATUSES.has(status);
}

function publicTitle(value: unknown) {
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

function fallbackTitle(item: GlobalRuntimeMonitorItem) {
  if (item.lifecycle === "completed" || item.bucket === "completed") return "会话运行已完成";
  if (item.lifecycle === "failed" || item.bucket === "failed") return "会话运行失败";
  if (item.bucket === "diagnostics" || item.lifecycle === "stale" || item.stale) return "运行状态需诊断";
  if (item.lifecycle === "waiting" || item.lifecycle === "action_required") return "会话运行等待处理";
  return "会话运行中";
}
