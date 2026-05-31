import type {
  RuntimeMonitorDetail,
  RuntimeMonitorEnvelope,
  RuntimeMonitorEventEnvelope,
  RuntimeMonitorItem,
  RuntimeMonitorState,
  RuntimeTaskInstanceState,
} from "./types";
import { monitorItemInstanceId, monitorItemTaskRunId } from "./resourceRefs";

export function createRuntimeMonitorState(): RuntimeMonitorState {
  return {
    monitor: null,
    revision: "",
    selectedTaskInstanceId: "",
    selectedTaskRunId: "",
    selectedDetail: null,
    selectedGraphMonitor: null,
    instancesById: {},
    loading: false,
    error: "",
    streamStatus: "closed",
    lastEvent: null,
  };
}

export function runtimeMonitorRevision(monitor: RuntimeMonitorEnvelope | null | undefined) {
  return String(monitor?.revision || monitor?.updated_at || "").trim();
}

export function runtimeMonitorRevisionOrdinal(revision: string) {
  const match = revision.match(/^rtmon:(\d+(?:\.\d+)?):/);
  if (match) return Number(match[1]);
  const numeric = Number(revision);
  return Number.isFinite(numeric) ? numeric : 0;
}

export function isStaleRuntimeMonitorRevision(incoming: string, current: string) {
  if (!incoming || !current) return false;
  const incomingOrdinal = runtimeMonitorRevisionOrdinal(incoming);
  const currentOrdinal = runtimeMonitorRevisionOrdinal(current);
  return incomingOrdinal > 0 && currentOrdinal > 0 && incomingOrdinal < currentOrdinal;
}

export function visibleRuntimeMonitorItemsFromEnvelope(monitor: RuntimeMonitorEnvelope | null | undefined) {
  const buckets = monitor?.buckets;
  const source = buckets
    ? [
        ...(Array.isArray(buckets.running) ? buckets.running : []),
        ...(Array.isArray(buckets.completed) ? buckets.completed : []),
        ...(Array.isArray(buckets.failed) ? buckets.failed : []),
        ...(Array.isArray(buckets.diagnostics) ? buckets.diagnostics : []),
      ]
    : Array.isArray(monitor?.items)
      ? monitor.items
      : Array.isArray(monitor?.task_runs)
        ? monitor.task_runs
        : [];
  const seen = new Set<string>();
  return source.filter((item) => {
    const id = monitorItemInstanceId(item);
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

export function applyRuntimeMonitorSnapshot(
  state: RuntimeMonitorState,
  monitor: RuntimeMonitorEnvelope,
  options: { detailTaskRunId?: string; lastEvent?: RuntimeMonitorEventEnvelope["runtime_event"] | null } = {},
): RuntimeMonitorState {
  const nextRevision = runtimeMonitorRevision(monitor);
  if (isStaleRuntimeMonitorRevision(nextRevision, state.revision)) {
    return state;
  }
  const visibleItems = visibleRuntimeMonitorItemsFromEnvelope(monitor);
  const requestedDetailTaskRunId = String(options.detailTaskRunId || "").trim();
  const requestedItem = requestedDetailTaskRunId
    ? visibleItems.find((item) => monitorItemTaskRunId(item) === requestedDetailTaskRunId)
    : null;
  const currentStillVisible = visibleItems.some((item) => monitorItemInstanceId(item) === state.selectedTaskInstanceId);
  const nextSelectedItem = requestedItem
    ?? (currentStillVisible
    ? visibleItems.find((item) => monitorItemInstanceId(item) === state.selectedTaskInstanceId) ?? null
    : visibleItems[0] ?? null);
  const nextSelectedTaskInstanceId = nextSelectedItem ? monitorItemInstanceId(nextSelectedItem) : "";
  const nextSelectedTaskRunId = nextSelectedItem ? monitorItemTaskRunId(nextSelectedItem) : "";
  const instancesById = { ...state.instancesById };
  for (const item of visibleItems) {
    const instanceId = monitorItemInstanceId(item);
    if (!instanceId) continue;
    instancesById[instanceId] = mergeMonitorItemIntoInstance(instancesById[instanceId], item);
  }
  return {
    ...state,
    monitor,
    revision: nextRevision,
    selectedTaskInstanceId: nextSelectedTaskInstanceId,
    selectedTaskRunId: nextSelectedTaskRunId,
    selectedDetail: nextSelectedTaskInstanceId && nextRevision === state.revision ? state.selectedDetail : null,
    selectedGraphMonitor: nextSelectedTaskInstanceId && nextRevision === state.revision ? state.selectedGraphMonitor : null,
    instancesById,
    error: "",
    lastEvent: options.lastEvent ?? state.lastEvent,
  };
}

export function selectRuntimeMonitorTaskInstance(state: RuntimeMonitorState, taskInstanceId: string) {
  const normalized = taskInstanceId.trim();
  const visibleItems = visibleRuntimeMonitorItemsFromEnvelope(state.monitor);
  const item = visibleItems.find((candidate) => monitorItemInstanceId(candidate) === normalized || monitorItemTaskRunId(candidate) === normalized);
  if (!item) {
    return {
      ...state,
      selectedTaskInstanceId: "",
      selectedTaskRunId: "",
      selectedDetail: null,
      selectedGraphMonitor: null,
    };
  }
  return {
    ...state,
    selectedTaskInstanceId: monitorItemInstanceId(item),
    selectedTaskRunId: monitorItemTaskRunId(item),
    selectedDetail: null,
    selectedGraphMonitor: null,
  };
}

export function applyRuntimeMonitorDetail(state: RuntimeMonitorState, detail: RuntimeMonitorDetail | null) {
  if (!detail) return state;
  const taskRunId = String(detail.task_run_id || detail.task_run?.task_run_id || "").trim();
  const instanceId = String(detail.task_instance_id || taskRunId).trim();
  if (!instanceId) return state;
  const nextInstance = {
    ...emptyInstance(instanceId),
    ...state.instancesById[instanceId],
    detail,
    lastLoadedAt: Date.now(),
    loading: false,
    error: "",
  };
  return {
    ...state,
    selectedDetail: state.selectedTaskInstanceId === instanceId || state.selectedTaskRunId === taskRunId ? detail : state.selectedDetail,
    instancesById: {
      ...state.instancesById,
      [instanceId]: nextInstance,
    },
  };
}

function mergeMonitorItemIntoInstance(
  current: RuntimeTaskInstanceState | undefined,
  item: RuntimeMonitorItem,
): RuntimeTaskInstanceState {
  const instanceId = monitorItemInstanceId(item);
  return {
    ...emptyInstance(instanceId),
    ...current,
    taskInstanceId: instanceId,
    rootTaskRunId: String(item.root_task_run_id || item.task_run_id || ""),
    kind: String(item.kind || ""),
    sessionId: String(item.session_id || ""),
    graphRunId: String(item.graph_run_id || ""),
    graphId: String(item.graph_id || ""),
    monitorItem: item,
    graphStatus: item.graph_status ?? null,
    childRuntimeRefs: Array.isArray(item.child_runtime_refs) ? item.child_runtime_refs : [],
    artifactRefs: Array.isArray(item.artifact_refs) ? item.artifact_refs : [],
  };
}

function emptyInstance(taskInstanceId: string): RuntimeTaskInstanceState {
  return {
    taskInstanceId,
    rootTaskRunId: "",
    kind: "",
    sessionId: "",
    graphRunId: "",
    graphId: "",
    monitorItem: null,
    detail: null,
    graphMonitor: null,
    graphStatus: null,
    childRuntimeRefs: [],
    selectedNodeId: "",
    nodeOutputsById: {},
    artifactRefs: [],
    lastLoadedAt: 0,
    loading: false,
    error: "",
  };
}
