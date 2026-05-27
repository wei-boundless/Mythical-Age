import type {
  GlobalRuntimeMonitor,
  GlobalRuntimeMonitorItem,
  HarnessTaskRunLiveMonitor,
} from "./api";

export type RuntimeWorkKind =
  | "task_graph_run"
  | "agent_runtime_run"
  | "chat_turn_runtime";

export type RuntimeWorkProjection = {
  workId: string;
  workKind: RuntimeWorkKind;
  primaryRunId: string;
  graphId?: string;
  title: string;
  status: string;
  displayTypeLabel: string;
  latestEventType?: string;
  isLive?: boolean;
};

type RuntimeProjectionFallback = {
  primaryRunId?: string;
  title?: string;
  status?: string;
  latestEventType?: string;
  isLive?: boolean;
  graphId?: string;
  hasCoordination?: boolean;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown) {
  return String(value ?? "").trim();
}

function bool(value: unknown) {
  return value === true || value === "true";
}

function statusFromMonitor(item: GlobalRuntimeMonitorItem) {
  return text(item.status) || text(item.coordination_status) || "unknown";
}

function taskGraphProjection(item: GlobalRuntimeMonitorItem): RuntimeWorkProjection {
  return {
    workId: text(item.task_run_id),
    workKind: "task_graph_run",
    primaryRunId: text(item.task_run_id),
    graphId: text(item.graph_id),
    title: text(item.project_title) || text(item.title) || text(item.task_id) || text(item.task_run_id) || "任务图",
    status: statusFromMonitor(item),
    displayTypeLabel: "任务图",
    latestEventType: text(item.latest_event_type),
    isLive: bool(item.is_live) || item.display_bucket === "live",
  };
}

function agentRuntimeProjection(item: GlobalRuntimeMonitorItem): RuntimeWorkProjection {
  return {
    workId: text(item.task_run_id),
    workKind: "agent_runtime_run",
    primaryRunId: text(item.task_run_id),
    title: text(item.title) || text(item.task_id) || text(item.task_run_id) || "Agent 运行",
    status: statusFromMonitor(item),
    displayTypeLabel: "Agent 运行",
    latestEventType: text(item.latest_event_type),
    isLive: bool(item.is_live) || item.display_bucket === "live",
  };
}

function chatTurnRuntimeProjection(item: GlobalRuntimeMonitorItem): RuntimeWorkProjection {
  return {
    workId: text(item.task_run_id),
    workKind: "chat_turn_runtime",
    primaryRunId: text(item.task_run_id),
    title: text(item.title) || text(item.task_id) || text(item.task_run_id) || "会话运行",
    status: statusFromMonitor(item),
    displayTypeLabel: "会话运行",
    latestEventType: text(item.latest_event_type),
    isLive: bool(item.is_live) || item.display_bucket === "live",
  };
}

export function runtimeWorkProjectionFromMonitorItem(item: GlobalRuntimeMonitorItem): RuntimeWorkProjection {
  if (item.has_coordination || text(item.graph_id)) return taskGraphProjection(item);
  if (text(item.latest_event_type).startsWith("agent_runtime_")) return agentRuntimeProjection(item);
  return chatTurnRuntimeProjection(item);
}

export function runtimeWorkProjectionFromLiveMonitor(
  monitor: HarnessTaskRunLiveMonitor | null | undefined,
): RuntimeWorkProjection | null {
  if (!monitor) return null;
  const taskRun = record(monitor.task_run);
  const taskRunId = text(taskRun.task_run_id);
  if (monitor.has_coordination) {
    return {
      workId: taskRunId,
      workKind: "task_graph_run",
      primaryRunId: taskRunId,
      title: text(taskRun.title) || text(taskRun.task_id) || taskRunId || "任务图",
      status: text(monitor.status) || "unknown",
      displayTypeLabel: "任务图",
    };
  }
  const phaseSummary = record(monitor.agent_runtime_phase_summary);
  if (phaseSummary.available) {
    return {
      workId: taskRunId,
      workKind: "agent_runtime_run",
      primaryRunId: taskRunId,
      title: text(phaseSummary.task_goal) || text(taskRun.title) || text(taskRun.task_id) || "Agent 运行",
      status: text(monitor.status) || "unknown",
      displayTypeLabel: "Agent 运行",
    };
  }
  if (!taskRunId) return null;
  return {
    workId: taskRunId,
    workKind: "chat_turn_runtime",
    primaryRunId: taskRunId,
    title: text(taskRun.title) || text(taskRun.task_id) || taskRunId || "会话运行",
    status: text(monitor.status) || "unknown",
    displayTypeLabel: "会话运行",
  };
}

export function isVisibleRuntimeMonitorItem(item: GlobalRuntimeMonitorItem) {
  const taskId = text(item.task_id);
  const bucket = text(item.display_bucket);
  if (!text(item.task_run_id)) return false;
  if (taskId.startsWith("task_graph.graph_module.")) return false;
  if (taskId.startsWith("taskinst:")) return false;
  if (["child_run", "internal", "hidden", "graph_module_imported_run"].includes(bucket)) return false;
  const work = runtimeWorkProjectionFromMonitorItem(item);
  return Boolean(work.workId && work.primaryRunId);
}

export function visibleRuntimeMonitorItems(monitor: GlobalRuntimeMonitor | null | undefined) {
  return (monitor?.task_runs ?? []).filter(isVisibleRuntimeMonitorItem);
}

export function summarizeRuntimeMonitorItems(items: GlobalRuntimeMonitorItem[]) {
  return items.reduce(
    (summary, item) => {
      summary.total += 1;
      if (item.status === "running" || item.status === "created") summary.running += 1;
      if (item.status === "waiting_approval" || item.status === "blocked") summary.waiting += 1;
      if (item.status === "completed" || item.status === "success") summary.completed += 1;
      if (item.status === "failed" || item.status === "aborted" || item.status === "cancelled") summary.failed += 1;
      if (item.display_bucket === "stale") summary.stale += 1;
      if (item.display_bucket === "recent") summary.recent += 1;
      return summary;
    },
    { total: 0, running: 0, waiting: 0, completed: 0, failed: 0, stale: 0, recent: 0 },
  );
}
