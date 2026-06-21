import type { SessionSummary, SessionTaskSummary } from "@/lib/api";
import { publicRuntimeStatusText } from "@/lib/runtimeStatusText";

export type SessionTaskActivityKind = "idle" | "running" | "waiting" | "paused" | "stale" | "completed" | "failed" | "stopped";

function taskValue(value: unknown) {
  return String(value || "").trim().toLowerCase();
}

export function sessionTaskActivityKind(task: SessionTaskSummary | undefined): SessionTaskActivityKind {
  if (!task) return "idle";
  const state = taskValue(task.activity_state);
  if (state === "running") return "running";
  if (state === "waiting") return "waiting";
  if (state === "paused") return "paused";
  if (state === "stale") return "stale";
  if (state === "completed") return "completed";
  if (state === "failed") return "failed";
  if (state === "stopped") return "stopped";
  if (task.is_running) return "running";
  if (task.is_waiting) return "waiting";
  return "idle";
}

export function sessionTaskStatusLabel(task: SessionTaskSummary | undefined) {
  if (!task) return "任务";
  const label = publicRuntimeStatusText(task.activity_label);
  if (label) return label;
  const kind = sessionTaskActivityKind(task);
  if (kind === "running") return "运行中";
  if (kind === "waiting") return "等待继续";
  if (kind === "paused") return "已暂停";
  if (kind === "stale") return "等待检查";
  if (kind === "failed") return "失败";
  if (kind === "stopped") return "已停止";
  if (kind === "completed") return "已完成";
  return "任务";
}

export function sessionSummaryTask(session: SessionSummary) {
  return session.active_task?.available ? session.active_task : undefined;
}

export function sessionSummaryIsRunning(session: SessionSummary) {
  const task = sessionSummaryTask(session);
  return sessionTaskActivityKind(task) === "running" || task?.is_running === true;
}

export function sessionSummaryCanResume(session: SessionSummary) {
  const task = sessionSummaryTask(session);
  return task?.is_resumable === true;
}

export function sessionSummaryCanInterrupt(session: SessionSummary) {
  const task = sessionSummaryTask(session);
  return task?.is_interruptible === true;
}
