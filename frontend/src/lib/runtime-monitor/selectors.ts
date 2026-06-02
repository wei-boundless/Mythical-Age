import type { RuntimeMonitorEnvelope, RuntimeMonitorItem } from "./types";
import { monitorItemInstanceId } from "./resourceRefs";
import { visibleRuntimeMonitorItemsFromEnvelope } from "./reducer";

export type RuntimeWorkKind = "task_graph_run" | "agent_runtime_run";

export type RuntimeWorkProjection = {
  workId: string;
  workKind: RuntimeWorkKind;
  primaryRunId: string;
  graphId?: string;
  title: string;
  status: string;
  displayTypeLabel: string;
  latestStepSummary?: string;
  isLive?: boolean;
};

type RuntimeProjectionFallback = {
  primaryRunId?: string;
  title?: string;
  status?: string;
  isLive?: boolean;
  graphId?: string;
};

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
    || lowered.startsWith("grun:");
}

function publicText(value: unknown) {
  const candidate = text(value);
  if (candidate === "Agent 运行") return "";
  return candidate && !looksInternalIdentifier(candidate) ? candidate : "";
}

function publicTaskId(value: unknown) {
  const candidate = text(value);
  if (!candidate) return "";
  if (candidate.startsWith("task:turn:") || candidate.startsWith("taskrun:") || candidate.startsWith("turn:")) return "";
  return candidate;
}

function statusFromMonitor(item: RuntimeMonitorItem) {
  return text(item.status) || "unknown";
}

function routeKind(item: RuntimeMonitorItem) {
  return text(item.route?.kind);
}

function canonicalKind(item: RuntimeMonitorItem) {
  const kind = text(item.kind);
  if (kind === "task_graph") return "task_graph_run";
  if (kind === "agent_run") return "agent_runtime_run";
  const route = routeKind(item);
  if (route === "task_graph_run" || route === "agent_runtime_run") return route;
  return "agent_runtime_run";
}

function taskGraphProjection(item: RuntimeMonitorItem): RuntimeWorkProjection {
  return {
    workId: monitorItemInstanceId(item) || text(item.task_run_id),
    workKind: "task_graph_run",
    primaryRunId: text(item.task_run_id),
    graphId: text(item.graph_id),
    title: publicText(item.project_title) || publicText(item.title) || "任务图",
    status: statusFromMonitor(item),
    displayTypeLabel: "任务图",
    latestStepSummary: text(item.latest_step_summary),
    isLive: bool(item.is_live) || item.resource_class === "dynamic",
  };
}

function agentRuntimeProjection(item: RuntimeMonitorItem): RuntimeWorkProjection {
  return {
    workId: monitorItemInstanceId(item) || text(item.task_run_id),
    workKind: "agent_runtime_run",
    primaryRunId: text(item.task_run_id),
    title: publicText(item.title) || publicTaskId(item.task_id) || "持续处理",
    status: statusFromMonitor(item),
    displayTypeLabel: "持续处理",
    latestStepSummary: text(item.latest_step_summary),
    isLive: bool(item.is_live) || item.resource_class === "dynamic",
  };
}

export function runtimeWorkProjectionFromMonitorItem(item: RuntimeMonitorItem): RuntimeWorkProjection {
  const kind = canonicalKind(item);
  if (kind === "task_graph_run") return taskGraphProjection(item);
  return agentRuntimeProjection(item);
}

export function runtimeWorkProjectionFromLiveMonitor(monitor: Record<string, unknown> | null | undefined): RuntimeWorkProjection | null {
  if (!monitor) return null;
  const taskRun = monitor.task_run && typeof monitor.task_run === "object" && !Array.isArray(monitor.task_run)
    ? monitor.task_run as Record<string, unknown>
    : monitor;
  const taskRunId = text(taskRun.task_run_id || monitor.task_run_id);
  const kind = text(monitor.kind);
  if (kind === "task_graph") {
    return {
      workId: text(monitor.task_instance_id) || taskRunId,
      workKind: "task_graph_run",
      primaryRunId: taskRunId,
      title: publicText(taskRun.title) || "任务图",
      status: text(monitor.status) || "unknown",
      displayTypeLabel: "任务图",
    };
  }
  if (kind === "agent_run") {
    return {
      workId: text(monitor.task_instance_id) || taskRunId,
      workKind: "agent_runtime_run",
      primaryRunId: taskRunId,
      title: publicText(taskRun.title) || "持续处理",
      status: text(monitor.status) || "unknown",
      displayTypeLabel: "持续处理",
    };
  }
  if (!taskRunId) return null;
  return {
    workId: text(monitor.task_instance_id) || taskRunId,
    workKind: "agent_runtime_run",
    primaryRunId: taskRunId,
    title: publicText(taskRun.title) || "持续处理",
    status: text(monitor.status) || "unknown",
    displayTypeLabel: "持续处理",
  };
}

export function isVisibleRuntimeMonitorItem(item: RuntimeMonitorItem) {
  if (!text(item.task_run_id)) return false;
  if (!["running", "completed", "failed", "diagnostics"].includes(text(item.bucket))) return false;
  const work = runtimeWorkProjectionFromMonitorItem(item);
  return Boolean(work.workId && work.primaryRunId);
}

export function monitorBucketItems(
  monitor: RuntimeMonitorEnvelope | null | undefined,
  bucket: "running" | "completed" | "failed" | "diagnostics",
) {
  const bucketItems = monitor?.buckets?.[bucket];
  const source = Array.isArray(bucketItems) ? bucketItems : [];
  return source.filter(isVisibleRuntimeMonitorItem);
}

export function visibleRuntimeMonitorItems(monitor: RuntimeMonitorEnvelope | null | undefined) {
  return visibleRuntimeMonitorItemsFromEnvelope(monitor).filter(isVisibleRuntimeMonitorItem);
}
