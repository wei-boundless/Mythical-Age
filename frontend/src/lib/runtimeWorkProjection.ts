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
    displayTypeLabel: "Agent 运行",
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
  if (!text(item.task_run_id)) return false;
  if (!["running", "completed", "failed", "diagnostics"].includes(text(item.bucket))) return false;
  const work = runtimeWorkProjectionFromMonitorItem(item);
  return Boolean(work.workId && work.primaryRunId);
}

export function monitorBucketItems(
  monitor: GlobalRuntimeMonitor | null | undefined,
  bucket: "running" | "completed" | "failed" | "diagnostics",
) {
  const bucketItems = monitor?.buckets?.[bucket];
  const source = Array.isArray(bucketItems) ? bucketItems : [];
  return source.filter(isVisibleRuntimeMonitorItem);
}

export function visibleRuntimeMonitorItems(monitor: GlobalRuntimeMonitor | null | undefined) {
  const bucketed = [
    ...monitorBucketItems(monitor, "running"),
    ...monitorBucketItems(monitor, "completed"),
    ...monitorBucketItems(monitor, "failed"),
    ...monitorBucketItems(monitor, "diagnostics"),
  ];
  if (bucketed.length) {
    const seen = new Set<string>();
    return bucketed.filter((item) => {
      const id = text(item.task_run_id);
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }
  return [];
}
