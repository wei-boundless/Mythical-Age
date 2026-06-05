import type { SessionSummary, SessionTaskSummary } from "@/lib/api";

export type SessionTaskActivityKind = "idle" | "running" | "waiting" | "completed" | "failed" | "stopped";

const WAITING_TASK_STATUSES = new Set([
  "action_required",
  "blocked",
  "paused",
  "pause_requested",
  "waiting",
  "waiting_approval",
  "waiting_executor",
  "waiting_user",
]);

const RUNNING_TASK_STATUSES = new Set(["created", "in_progress", "running"]);
const COMPLETED_TASK_STATUSES = new Set(["completed", "done", "success", "succeeded"]);
const FAILED_TASK_STATUSES = new Set(["error", "failed"]);
const STOPPED_TASK_STATUSES = new Set(["aborted", "cancelled", "canceled", "stopped", "user_aborted"]);

function taskValue(value: unknown) {
  return String(value || "").trim().toLowerCase();
}

function taskStatusValues(task: SessionTaskSummary | undefined) {
  return {
    bucket: taskValue(task?.bucket),
    lifecycle: taskValue(task?.lifecycle),
    status: taskValue(task?.status),
  };
}

export function sessionTaskActivityKind(task: SessionTaskSummary | undefined): SessionTaskActivityKind {
  if (!task) return "idle";
  const { bucket, lifecycle, status } = taskStatusValues(task);
  if (task.terminal || COMPLETED_TASK_STATUSES.has(status) || COMPLETED_TASK_STATUSES.has(lifecycle)) {
    return "completed";
  }
  if (FAILED_TASK_STATUSES.has(status) || FAILED_TASK_STATUSES.has(lifecycle)) {
    return "failed";
  }
  if (STOPPED_TASK_STATUSES.has(status) || STOPPED_TASK_STATUSES.has(lifecycle)) {
    return "stopped";
  }
  if (
    task.action_required
    || WAITING_TASK_STATUSES.has(status)
    || WAITING_TASK_STATUSES.has(lifecycle)
    || WAITING_TASK_STATUSES.has(bucket)
  ) {
    return "waiting";
  }
  if (RUNNING_TASK_STATUSES.has(status) || RUNNING_TASK_STATUSES.has(lifecycle) || bucket === "running") {
    return "running";
  }
  return "idle";
}

export function sessionTaskStatusLabel(task: SessionTaskSummary | undefined) {
  if (!task) return "任务";
  const { bucket, lifecycle, status } = taskStatusValues(task);
  if (status === "waiting_executor" || lifecycle === "waiting_executor" || status === "waiting_user") return "等待继续";
  if (status === "waiting_approval" || lifecycle === "waiting_approval") return "等待确认";
  if (status === "paused" || lifecycle === "paused" || status === "pause_requested" || lifecycle === "pause_requested") return "已暂停";
  if (task.action_required || status === "blocked" || lifecycle === "blocked" || lifecycle === "action_required" || bucket === "waiting") return "等待处理";
  const kind = sessionTaskActivityKind(task);
  if (kind === "running") return "运行中";
  if (kind === "completed") return "已完成";
  if (kind === "failed") return "失败";
  if (kind === "stopped") return "已停止";
  return status || lifecycle || bucket || "任务";
}

export function sessionSummaryTask(session: SessionSummary) {
  return session.active_task?.available ? session.active_task : undefined;
}

export function sessionSummaryIsRunning(session: SessionSummary, activeStreamSessionIds: string[]) {
  const task = sessionSummaryTask(session);
  if (sessionTaskActivityKind(task) === "waiting") {
    return false;
  }
  if (activeStreamSessionIds.includes(session.id)) {
    return true;
  }
  return sessionTaskActivityKind(task) === "running";
}
