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
  const createdAt = Number(item.created_at || 0);
  const startedAt = Number(item.started_at || createdAt || 0);
  const lastActivityAt = Number(item.last_activity_at || item.latest_event_at || item.updated_at || 0);
  const fallbackRuntime = Number(item.duration_seconds ?? item.runtime_seconds ?? item.elapsed_seconds ?? 0);
  const dynamic = item.resource_class === "dynamic" || Boolean(item.is_live);
  const live = dynamic && (item.bucket === "running" || item.display_bucket === "running" || item.display_bucket === "live" || item.is_live);
  const liveDuration = live && now && startedAt ? Math.max(fallbackRuntime, now - startedAt) : fallbackRuntime;
  const staleAge = now && lastActivityAt
    ? Math.max(Number(item.last_activity_age_seconds ?? 0), now - lastActivityAt)
    : Number(item.last_activity_age_seconds ?? 0);
  const duration = formatDuration(liveDuration);
  if (live) return `运行 ${duration}`;
  if (item.bucket === "diagnostics" || item.lifecycle === "stale" || item.stale) return `停滞 ${formatDuration(staleAge)}`;
  if (item.bucket === "completed" || item.bucket === "failed" || item.display_bucket === "completed" || item.display_bucket === "failed" || item.display_bucket === "recent") return `耗时 ${duration}`;
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
  if (item.bucket === "completed" || item.display_bucket === "completed" || item.status === "completed" || item.status === "success") return "会话任务已完成";
  if (item.bucket === "failed" || item.display_bucket === "failed" || item.status === "failed" || item.status === "aborted" || item.status === "cancelled") return "会话任务失败";
  if (item.bucket === "diagnostics" || item.lifecycle === "stale" || item.stale) return "运行状态需诊断";
  if (item.status === "waiting_executor" || item.status === "waiting_approval") return "会话任务等待处理";
  return "会话任务运行中";
}
