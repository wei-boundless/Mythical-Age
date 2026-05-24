import type {
  GlobalRuntimeMonitor,
  GlobalRuntimeMonitorItem,
  RuntimeLoopTaskRunLiveMonitor,
  TaskOrderProjection,
} from "./api";

export type RuntimeWorkKind =
  | "task_order_run"
  | "task_graph_run"
  | "professional_task"
  | "chat_turn_runtime";

export type RuntimeWorkProjection = {
  workId: string;
  workKind: RuntimeWorkKind;
  primaryRunId: string;
  orderId?: string;
  orderRunId?: string;
  channelId?: string;
  envelopeId?: string;
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

function workLabelForOrderKind(orderKind: string, fallbackHasCoordination = false) {
  if (orderKind === "graph_run" || fallbackHasCoordination) return "任务图";
  return "任务订单";
}

export function runtimeWorkProjectionFromTaskOrderProjection(
  projection: TaskOrderProjection | null | undefined,
  fallback: RuntimeProjectionFallback = {},
): RuntimeWorkProjection | null {
  if (!projection) return null;
  const order = record(projection.task_order);
  const run = record(projection.task_order_run);
  const channel = record(projection.execution_channel);
  const envelope = record(projection.task_execution_envelope);
  const orderRunId = text(run.run_id);
  const primaryRunId = text(run.task_run_id) || text(channel.task_run_id) || text(fallback.primaryRunId);
  if (!orderRunId && !primaryRunId && !text(order.order_id)) return null;
  const orderKind = text(order.order_kind);
  const label = workLabelForOrderKind(orderKind, Boolean(fallback.hasCoordination));
  return {
    workId: orderRunId || primaryRunId || text(order.order_id),
    workKind: "task_order_run",
    primaryRunId,
    orderId: text(order.order_id),
    orderRunId,
    channelId: text(channel.channel_id),
    envelopeId: text(envelope.envelope_id),
    graphId: text(fallback.graphId),
    title: text(order.objective) || text(order.task_id) || text(fallback.title) || "运行任务",
    status: text(run.status) || text(channel.status) || text(fallback.status) || "unknown",
    displayTypeLabel: label,
    latestEventType: fallback.latestEventType,
    isLive: fallback.isLive,
  };
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

function professionalProjection(item: GlobalRuntimeMonitorItem): RuntimeWorkProjection {
  return {
    workId: text(item.task_run_id),
    workKind: "professional_task",
    primaryRunId: text(item.task_run_id),
    title: text(item.title) || text(item.task_id) || text(item.task_run_id) || "专业任务",
    status: statusFromMonitor(item),
    displayTypeLabel: "专业任务",
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
  const orderProjection = runtimeWorkProjectionFromTaskOrderProjection(item.task_order_projection, {
    primaryRunId: item.task_run_id,
    title: item.title,
    status: item.status,
    latestEventType: item.latest_event_type,
    isLive: item.is_live,
    graphId: item.graph_id,
    hasCoordination: item.has_coordination,
  });
  if (orderProjection) return orderProjection;
  if (item.has_coordination || text(item.graph_id)) return taskGraphProjection(item);
  if (text(item.latest_event_type).startsWith("professional_")) return professionalProjection(item);
  return chatTurnRuntimeProjection(item);
}

export function runtimeWorkProjectionFromLiveMonitor(
  monitor: RuntimeLoopTaskRunLiveMonitor | null | undefined,
): RuntimeWorkProjection | null {
  if (!monitor) return null;
  const taskRun = record(monitor.task_run);
  const taskRunId = text(taskRun.task_run_id);
  const orderProjection = runtimeWorkProjectionFromTaskOrderProjection(monitor.task_order_projection, {
    primaryRunId: taskRunId,
    title: text(taskRun.title) || text(taskRun.task_id),
    status: monitor.status,
    hasCoordination: monitor.has_coordination,
  });
  if (orderProjection) return orderProjection;
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
  if (record(monitor.professional_task_summary).available) {
    return {
      workId: taskRunId,
      workKind: "professional_task",
      primaryRunId: taskRunId,
      title: text(record(monitor.professional_task_summary).goal) || text(taskRun.title) || text(taskRun.task_id) || "专业任务",
      status: text(monitor.status) || "unknown",
      displayTypeLabel: "专业任务",
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
