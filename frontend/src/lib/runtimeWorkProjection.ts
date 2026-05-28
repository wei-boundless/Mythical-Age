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
  latestStepSummary?: string;
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

function looksInternalIdentifier(value: string) {
  const lowered = value.trim().toLowerCase();
  return lowered.startsWith("task:")
    || lowered.startsWith("taskrun:")
    || lowered.startsWith("turn:")
    || lowered.startsWith("turnrun:")
    || lowered.startsWith("session:")
    || lowered.startsWith("taskinst:")
    || lowered.startsWith("coordrun:");
}

function publicText(value: unknown) {
  const candidate = text(value);
  return candidate && !looksInternalIdentifier(candidate) ? candidate : "";
}

function statusFromMonitor(item: GlobalRuntimeMonitorItem) {
  return text(item.status) || text(item.coordination_status) || "unknown";
}

function routeKind(item: GlobalRuntimeMonitorItem) {
  return text(item.route?.kind);
}

function isChatScopedRun(item: GlobalRuntimeMonitorItem) {
  const taskRunId = text(item.task_run_id);
  const taskId = text(item.task_id);
  return taskRunId.startsWith("turnrun:")
    || taskRunId.startsWith("taskrun:turn:")
    || taskId.startsWith("turn:")
    || taskId.startsWith("task:turn:");
}

function taskRunRecordFromLiveMonitor(monitor: HarnessTaskRunLiveMonitor) {
  const nested = record(monitor.task_run);
  if (Object.keys(nested).length) return nested;
  return record(monitor);
}

function taskGraphProjection(item: GlobalRuntimeMonitorItem): RuntimeWorkProjection {
  return {
    workId: text(item.task_run_id),
    workKind: "task_graph_run",
    primaryRunId: text(item.task_run_id),
    graphId: text(item.graph_id),
    title: publicText(item.project_title) || publicText(item.title) || "任务图",
    status: statusFromMonitor(item),
    displayTypeLabel: "任务图",
    latestEventType: text(item.latest_event_type),
    isLive: bool(item.is_live) || item.resource_class === "dynamic",
  };
}

function agentRuntimeProjection(item: GlobalRuntimeMonitorItem): RuntimeWorkProjection {
  return {
    workId: text(item.task_run_id),
    workKind: "agent_runtime_run",
    primaryRunId: text(item.task_run_id),
    title: publicText(item.title) || "Agent 运行",
    status: statusFromMonitor(item),
    displayTypeLabel: text(item.runtime_lane) === "single_agent_task" ? "长任务" : "Agent 运行",
    latestEventType: text(item.latest_event_type),
    latestStepSummary: text(item.latest_step_summary),
    isLive: bool(item.is_live) || item.resource_class === "dynamic",
  };
}

function chatTurnRuntimeProjection(item: GlobalRuntimeMonitorItem): RuntimeWorkProjection {
  return {
    workId: text(item.task_run_id),
    workKind: "chat_turn_runtime",
    primaryRunId: text(item.task_run_id),
    title: publicText(item.title) || "会话运行",
    status: statusFromMonitor(item),
    displayTypeLabel: "会话运行",
    latestEventType: text(item.latest_event_type),
    latestStepSummary: text(item.latest_step_summary),
    isLive: bool(item.is_live) || item.resource_class === "dynamic",
  };
}

export function runtimeWorkProjectionFromMonitorItem(item: GlobalRuntimeMonitorItem): RuntimeWorkProjection {
  const route = routeKind(item);
  if (route === "task_graph_run") return taskGraphProjection(item);
  if (route === "agent_runtime_run") return agentRuntimeProjection(item);
  if (route === "chat_turn_runtime") return chatTurnRuntimeProjection(item);
  if (item.has_coordination || text(item.graph_id)) return taskGraphProjection(item);
  if (isChatScopedRun(item)) return chatTurnRuntimeProjection(item);
  if (text(item.runtime_lane) === "single_agent_task") return agentRuntimeProjection(item);
  if (text(item.latest_event_type).startsWith("agent_runtime_")) return agentRuntimeProjection(item);
  return chatTurnRuntimeProjection(item);
}

export function runtimeWorkProjectionFromLiveMonitor(
  monitor: HarnessTaskRunLiveMonitor | null | undefined,
): RuntimeWorkProjection | null {
  if (!monitor) return null;
  const taskRun = taskRunRecordFromLiveMonitor(monitor);
  const taskRunId = text(taskRun.task_run_id);
  if (monitor.has_coordination) {
    return {
      workId: taskRunId,
      workKind: "task_graph_run",
      primaryRunId: taskRunId,
      title: publicText(taskRun.title) || "任务图",
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
      title: publicText(phaseSummary.task_goal) || publicText(taskRun.title) || "Agent 运行",
      status: text(monitor.status) || "unknown",
      displayTypeLabel: "Agent 运行",
    };
  }
  if (!taskRunId) return null;
  return {
    workId: taskRunId,
    workKind: "chat_turn_runtime",
    primaryRunId: taskRunId,
    title: publicText(taskRun.title) || "会话运行",
    status: text(monitor.status) || "unknown",
    displayTypeLabel: "会话运行",
  };
}

export function isVisibleRuntimeMonitorItem(item: GlobalRuntimeMonitorItem) {
  const taskId = text(item.task_id);
  const bucket = text(item.bucket) || text(item.display_bucket);
  const status = statusFromMonitor(item);
  if (!text(item.task_run_id)) return false;
  if (taskId.startsWith("task_graph.graph_module.")) return false;
  if (taskId.startsWith("taskinst:")) return false;
  if (["child_run", "internal", "hidden", "graph_module_imported_run"].includes(bucket)) return false;
  if (!["running", "completed", "failed", "diagnostics", "live", "stale", "recent"].includes(bucket) && item.is_live !== true) return false;
  if (!["created", "running", "waiting_executor", "waiting_approval", "blocked", "failed", "aborted", "cancelled", "completed", "success", "error"].includes(status)) return false;
  const work = runtimeWorkProjectionFromMonitorItem(item);
  return Boolean(work.workId && work.primaryRunId);
}

export function monitorBucketItems(
  monitor: GlobalRuntimeMonitor | null | undefined,
  bucket: "running" | "completed" | "failed" | "diagnostics",
) {
  const bucketItems = monitor?.buckets?.[bucket];
  const source = Array.isArray(bucketItems)
    ? bucketItems
    : (monitor?.task_runs ?? []).filter((item) => {
      const displayBucket = text(item.display_bucket);
      const normalizedBucket = text(item.bucket);
      if (normalizedBucket === bucket) return true;
      if (displayBucket === bucket) return true;
      const status = statusFromMonitor(item);
      if (bucket === "running") return ["created", "running", "waiting_executor", "waiting_approval", "blocked"].includes(status);
      if (bucket === "completed") return ["completed", "success"].includes(status);
      if (bucket === "diagnostics") return item.stale === true || normalizedBucket === "diagnostics";
      return ["failed", "aborted", "cancelled", "error"].includes(status);
    });
  return source.filter(isVisibleRuntimeMonitorItem);
}

export function visibleRuntimeMonitorItems(monitor: GlobalRuntimeMonitor | null | undefined) {
  return (monitor?.task_runs ?? []).filter(isVisibleRuntimeMonitorItem);
}

export function summarizeRuntimeMonitorItems(items: GlobalRuntimeMonitorItem[]) {
  return items.reduce(
    (summary, item) => {
      summary.total += 1;
      if (item.status === "running" || item.status === "created") summary.running += 1;
      if (item.status === "waiting_executor" || item.status === "waiting_approval") summary.waiting += 1;
      if (item.status === "completed" || item.status === "success") summary.completed += 1;
      if (item.status === "failed" || item.status === "aborted" || item.status === "cancelled" || item.status === "blocked") summary.failed += 1;
      if (item.bucket === "diagnostics") summary.diagnostics += 1;
      if (item.display_bucket === "stale") summary.stale += 1;
      if (item.display_bucket === "recent") summary.recent += 1;
      return summary;
    },
    { total: 0, running: 0, waiting: 0, completed: 0, failed: 0, diagnostics: 0, stale: 0, recent: 0 },
  );
}
