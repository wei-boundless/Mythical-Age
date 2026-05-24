import type { GlobalRuntimeMonitorItem } from "@/lib/api";

const WAITING_STATUSES = new Set(["waiting_approval", "blocked"]);

export function statusLabel(status: string) {
  if (status === "running" || status === "created") return "进行中";
  if (status === "waiting_approval") return "等待审批";
  if (status === "blocked") return "受阻";
  if (status === "completed" || status === "success") return "已完成";
  if (status === "failed") return "失败";
  if (status === "aborted") return "已停止";
  return status || "未知";
}

export function monitorStatusLabel(item: GlobalRuntimeMonitorItem) {
  if (item.display_bucket === "stale") return "停滞";
  if (item.display_bucket === "recent" && (item.status === "completed" || item.status === "success")) return "刚完成";
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
  const lastActivityAt = Number(item.last_activity_at || item.latest_event_at || item.updated_at || 0);
  const fallbackRuntime = Number(item.runtime_seconds ?? item.elapsed_seconds ?? 0);
  const liveDuration = now && createdAt ? Math.max(fallbackRuntime, now - createdAt) : fallbackRuntime;
  const staleAge = now && lastActivityAt
    ? Math.max(Number(item.last_activity_age_seconds ?? 0), now - lastActivityAt)
    : Number(item.last_activity_age_seconds ?? 0);
  const duration = formatDuration(liveDuration);
  if (item.display_bucket === "live" || item.is_live) return `运行 ${duration}`;
  if (item.display_bucket === "stale") return `停滞 ${formatDuration(staleAge)}`;
  if (item.display_bucket === "recent") return `耗时 ${duration}`;
  return `结束 ${formatTime(item.last_activity_at || item.updated_at)}`;
}

export function taskTitle(item: GlobalRuntimeMonitorItem) {
  const order = item.task_order_projection?.task_order;
  const objective = order && typeof order === "object" && !Array.isArray(order)
    ? String(order.objective ?? "").trim()
    : "";
  return objective || item.project_title || item.title || item.task_id || item.task_run_id;
}

export function isWaitingStatus(status: string) {
  return WAITING_STATUSES.has(status);
}
