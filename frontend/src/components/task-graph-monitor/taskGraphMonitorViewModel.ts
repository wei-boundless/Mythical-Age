import type {
  TaskGraphRunMonitorEdge,
  TaskGraphRunMonitorNode,
  TaskGraphRunMonitorView,
} from "@/lib/api";

export type TaskGraphMonitorNodeView = {
  id: string;
  title: string;
  agentLabel: string;
  role: string;
  nodeKind: string;
  status: string;
  taskId: string;
  artifactRefs: string[];
  resultRef: string;
};

export type TaskGraphMonitorEdgeView = {
  id: string;
  from: string;
  to: string;
  label: string;
  status: string;
  contractId: string;
};

export type TaskGraphMonitorMemoryOperationView = {
  key: string;
  operation: string;
  nodeId: string;
  edgeId: string;
  status: string;
  refs: string[];
};

export type TaskGraphMonitorViewModel = {
  hasSignal: boolean;
  title: string;
  graphId: string;
  projectId: string;
  projectTitle: string;
  taskRunId: string;
  coordinationRunId: string;
  status: string;
  projectRuntimeStatus: string;
  terminalReason: string;
  failureMessage: string;
  failureDetail: string;
  failureCode: string;
  failureProvider: string;
  failureModel: string;
  failureStepId: string;
  activeNodeId: string;
  activeTaskRef: string;
  eventCount: number;
  latestEventAt: number;
  lastEffectiveOutputAt: number;
  nodeCount: number;
  edgeCount: number;
  completedCount: number;
  runningCount: number;
  blockedCount: number;
  failedCount: number;
  progressMetricLabel: string;
  targetMetricTotal: number;
  completedMetricTotal: number;
  remainingMetricTotal: number;
  committedUnitCount: number;
  lastCommittedUnitIndex: number;
  blockerKind: string;
  blockerSummary: string;
  repairSummary: string;
  nodes: TaskGraphMonitorNodeView[];
  edges: TaskGraphMonitorEdgeView[];
  artifacts: Array<Record<string, unknown>>;
  memoryOperations: TaskGraphMonitorMemoryOperationView[];
  stageResults: Array<Record<string, unknown>>;
  timelineClockSeq: number;
  timelineEventCount: number;
  timelineEvents: Array<Record<string, unknown>>;
  dispatchContext: Record<string, unknown>;
  contextPackets: Record<string, unknown>;
  timelineResultRecords: Array<Record<string, unknown>>;
  temporalActiveActivationId: string;
  temporalActiveExecutionPermitId: string;
  temporalActiveNodeId: string;
  temporalActiveRequestId: string;
  temporalBoundaryValid: boolean;
  temporalViolations: Array<{ severity: string; code: string; message: string; targetId: string }>;
  streamEnabled: boolean;
  streamChunkCount: number;
  streamAccumulatedChars: number;
  streamLatestAt: number;
  streamPreviewText: string;
  healthValid: boolean;
  healthIssues: Array<{ severity: string; code: string; message: string; targetId: string }>;
};

function text(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function stringArray(value: unknown): string[] {
  if (typeof value === "string") {
    return value.trim() ? [value.trim()] : [];
  }
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => text(item)).filter(Boolean);
}

function statusLabel(status: string) {
  if (status === "completed" || status === "success" || status === "satisfied") return "完成";
  if (status === "running") return "运行中";
  if (status === "failed") return "失败";
  if (status === "blocked") return "阻塞";
  if (status === "waiting" || status === "waiting_for_human" || status === "human_gate") return "等待确认";
  if (status === "ready" || status === "pending_retry") return "就绪";
  if (status === "pending" || status === "idle") return "待执行";
  return status || "待执行";
}

function nodeKind(node: TaskGraphRunMonitorNode) {
  const raw = text(node.node_type).toLowerCase();
  if (raw.includes("memory")) return "memory";
  if (raw.includes("review") || raw.includes("gate")) return "review";
  if (raw.includes("artifact")) return "artifact";
  return raw || "task";
}

function nodeView(node: TaskGraphRunMonitorNode): TaskGraphMonitorNodeView {
  const id = text(node.node_id);
  return {
    id,
    title: text(node.title, id),
    agentLabel: text(node.agent_id, "待分派"),
    role: text(node.node_type, "task"),
    nodeKind: nodeKind(node),
    status: text(node.status, "pending"),
    taskId: text(node.task_id),
    artifactRefs: stringArray(node.artifact_refs),
    resultRef: text(node.last_result_ref),
  };
}

function edgeView(edge: TaskGraphRunMonitorEdge): TaskGraphMonitorEdgeView {
  const from = text(edge.source_node_id);
  const to = text(edge.target_node_id);
  return {
    id: text(edge.edge_id, `${from}->${to}`),
    from,
    to,
    label: text(edge.edge_type) || text(edge.payload_contract_id) || "交接",
    status: text(edge.status, "idle"),
    contractId: text(edge.payload_contract_id),
  };
}

function isRealtimeCommunicationEdge(edge: TaskGraphMonitorEdgeView) {
  return [
    "running",
    "waiting",
    "waiting_for_human",
    "human_gate",
    "failed",
    "pending_retry",
  ].includes(edge.status);
}

function memoryOperationView(item: Record<string, unknown>, index: number): TaskGraphMonitorMemoryOperationView {
  const operation = text(item.operation);
  const nodeId = text(item.node_id) || text(item.stage_id);
  const edgeId = text(item.edge_id);
  return {
    key: `${operation}:${nodeId || edgeId || index}`,
    operation,
    nodeId,
    edgeId,
    status: text(item.status, "completed"),
    refs: stringArray(item.refs),
  };
}

export function buildTaskGraphMonitorViewModel(monitor: TaskGraphRunMonitorView | null | undefined): TaskGraphMonitorViewModel {
  const nodes = (monitor?.topology?.nodes ?? []).map(nodeView).filter((node) => node.id);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const topologyEdges = (monitor?.topology?.edges ?? [])
    .map(edgeView)
    .filter((edge) => edge.from && edge.to && nodeIds.has(edge.from) && nodeIds.has(edge.to));
  const edges = topologyEdges.filter(isRealtimeCommunicationEdge);
  const status = text(monitor?.runtime?.status, "unknown");
  const activeNodeId =
    text(monitor?.runtime?.active_node_id)
    || nodes.find((node) => node.status === "running")?.id
    || "";

  return {
    hasSignal: Boolean(monitor && (nodes.length || text(monitor.graph?.graph_id))),
    title: text(monitor?.graph?.title, "当前没有任务图运行"),
    graphId: text(monitor?.graph?.graph_id),
    projectId: text(monitor?.project?.project_id),
    projectTitle: text(monitor?.project?.project_title),
    taskRunId: text(monitor?.task_run_id),
    coordinationRunId: text(monitor?.coordination_run_id),
    status,
    projectRuntimeStatus: text(monitor?.supervision?.project_runtime_status),
    terminalReason: text(monitor?.runtime?.terminal_reason),
    failureMessage: text(monitor?.runtime?.failure?.message),
    failureDetail: text(monitor?.runtime?.failure?.detail),
    failureCode: text(monitor?.runtime?.failure?.code),
    failureProvider: text(monitor?.runtime?.failure?.provider),
    failureModel: text(monitor?.runtime?.failure?.model),
    failureStepId: text(monitor?.runtime?.failure?.step_id),
    activeNodeId,
    activeTaskRef: text(monitor?.runtime?.active_task_ref),
    eventCount: Number(monitor?.runtime?.event_count ?? 0),
    latestEventAt: Number(monitor?.supervision?.latest_event_at ?? 0),
    lastEffectiveOutputAt: Number(monitor?.supervision?.last_effective_output_at ?? 0),
    nodeCount: Number(monitor?.graph?.node_count ?? nodes.length),
    edgeCount: Number(monitor?.graph?.edge_count ?? edges.length),
    completedCount: nodes.filter((node) => node.status === "completed" || node.status === "success").length,
    runningCount: nodes.filter((node) => node.status === "running").length,
    blockedCount: nodes.filter((node) => ["blocked", "waiting", "waiting_for_human", "human_gate"].includes(node.status)).length,
    failedCount: nodes.filter((node) => node.status === "failed").length,
    progressMetricLabel: text(monitor?.progress?.metric_label, "units"),
    targetMetricTotal: Number(monitor?.progress?.target_metric_total ?? 0),
    completedMetricTotal: Number(monitor?.progress?.completed_metric_total ?? 0),
    remainingMetricTotal: Number(monitor?.progress?.remaining_metric_total ?? 0),
    committedUnitCount: Number(monitor?.progress?.committed_unit_count ?? 0),
    lastCommittedUnitIndex: Number(monitor?.progress?.last_committed_unit_index ?? 0),
    blockerKind: text(monitor?.blocker?.kind),
    blockerSummary: text(monitor?.blocker?.summary),
    repairSummary: text(monitor?.repair?.summary || monitor?.repair?.action || monitor?.supervision?.latest_record?.repair_action),
    nodes,
    edges,
    artifacts: monitor?.artifacts ?? [],
    memoryOperations: (monitor?.memory_operations ?? []).map(memoryOperationView),
    stageResults: monitor?.stage_results ?? [],
    timelineClockSeq: Number(monitor?.timeline?.current_clock_seq ?? 0),
    timelineEventCount: Number(monitor?.timeline?.event_count ?? 0),
    timelineEvents: monitor?.timeline?.recent_events ?? [],
    dispatchContext: monitor?.current_dispatch_context ?? {},
    contextPackets: monitor?.current_context_packets ?? {},
    timelineResultRecords: monitor?.timeline_result_records ?? [],
    temporalActiveActivationId: text(monitor?.temporal?.active_activation_id),
    temporalActiveExecutionPermitId: text(monitor?.temporal?.active_execution_permit_id),
    temporalActiveNodeId: text(monitor?.temporal?.active_node_id),
    temporalActiveRequestId: text(monitor?.temporal?.active_request_id),
    temporalBoundaryValid: monitor?.temporal?.boundary_valid === true,
    temporalViolations: (monitor?.temporal?.violations ?? []).map((issue) => ({
      severity: text(issue.severity),
      code: text(issue.code),
      message: text(issue.message),
      targetId: text(issue.target_id),
    })),
    streamEnabled: monitor?.streaming?.enabled === true,
    streamChunkCount: Number(monitor?.streaming?.chunk_count ?? 0),
    streamAccumulatedChars: Number(monitor?.streaming?.accumulated_chars ?? 0),
    streamLatestAt: Number(monitor?.streaming?.latest_chunk_at ?? 0),
    streamPreviewText: text(monitor?.streaming?.preview_text),
    healthValid: monitor?.health?.valid !== false,
    healthIssues: (monitor?.health?.issues ?? []).map((issue) => ({
      severity: text(issue.severity),
      code: text(issue.code),
      message: text(issue.message),
      targetId: text(issue.target_id),
    })),
  };
}

export function taskGraphMonitorStatusLabel(status: string) {
  return statusLabel(status);
}
