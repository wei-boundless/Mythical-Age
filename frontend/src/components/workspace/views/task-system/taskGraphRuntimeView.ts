import { latestTaskGraphRunFromTrace, type HarnessTaskRunTrace, type TaskGraphRuntimeSpec } from "../../../../lib/api";

export type TaskGraphSchedulerSummary = {
  available: boolean;
  graph_id: string;
  mode: string;
  terminal_status: string;
  ready_node_ids: string[];
  blocked_node_ids: string[];
  running_node_ids: string[];
  completed_node_ids: string[];
  failed_node_ids: string[];
  phase_count: number;
  node_count: number;
  edge_count: number;
  active_phase_ids: string[];
  active_sequence_by_phase: Record<string, number>;
  phase_states: Array<Record<string, unknown>>;
  node_states: Array<Record<string, unknown>>;
  edge_states: Array<Record<string, unknown>>;
};

export type TaskGraphBatchLifecycleSummary = {
  available: boolean;
  authority: string;
  graph_id: string;
  mode: string;
  summary: Record<string, number>;
  ready_batch_ids: string[];
  running_batch_ids: string[];
  committed_batch_ids: string[];
  failed_batch_ids: string[];
  active_batch_by_node: Record<string, string>;
  active_execution_by_node: Record<string, string>;
  active_execution_by_batch: Record<string, string>;
  execution_mode_by_plan: Record<string, string>;
  plans: Array<Record<string, unknown>>;
  batches: Array<Record<string, unknown>>;
  execution_instances: Array<Record<string, unknown>>;
  merge_states: Array<Record<string, unknown>>;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function asStringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item ?? "")).filter(Boolean) : [];
}

function asNumberRecord(value: unknown): Record<string, number> {
  const record = asRecord(value);
  return Object.fromEntries(
    Object.entries(record)
      .map(([key, item]) => [key, Number(item)])
      .filter(([, item]) => Number.isFinite(item)),
  );
}

export function schedulerStateFromRuntimeSpec(runtimeSpec: TaskGraphRuntimeSpec | { diagnostics?: Record<string, unknown> } | null | undefined) {
  return asRecord(asRecord(runtimeSpec?.diagnostics).scheduler_support);
}

export function schedulerStateFromTrace(trace: HarnessTaskRunTrace | { coordination_runs?: Array<Record<string, unknown>> } | null | undefined) {
  const taskGraphRun = latestTaskGraphRunFromTrace(trace);
  const diagnostics = asRecord(taskGraphRun?.diagnostics);
  const runtimeState = asRecord(diagnostics.graph_coordination_state);
  return {
    ...asRecord(runtimeState.task_graph_scheduler_state),
    ...asRecord(diagnostics.task_graph_scheduler_state),
  };
}

export function batchLifecycleFromTrace(trace: HarnessTaskRunTrace | { coordination_runs?: Array<Record<string, unknown>> } | null | undefined) {
  const taskGraphRun = latestTaskGraphRunFromTrace(trace);
  const diagnostics = asRecord(taskGraphRun?.diagnostics);
  const runtimeState = asRecord(diagnostics.graph_coordination_state);
  const runtimeBatch = asRecord(runtimeState.batch_lifecycle_runtime_state);
  const diagnosticsBatch = asRecord(diagnostics.batch_lifecycle_runtime_state);
  return Object.keys(diagnosticsBatch).length ? diagnosticsBatch : runtimeBatch;
}

export function buildTaskGraphBatchLifecycleSummary(rawState: unknown): TaskGraphBatchLifecycleSummary {
  const state = asRecord(rawState);
  const summary = asRecord(state.summary);
  const activeBatchByNode = asRecord(state.active_batch_by_node);
  const activeExecutionByNode = asRecord(state.active_execution_by_node);
  const activeExecutionByBatch = asRecord(state.active_execution_by_batch);
  const executionModeByPlan = asRecord(state.execution_mode_by_plan);
  return {
    available: state.available === true || String(state.authority ?? "") === "task_system.batch_lifecycle_runtime_state",
    authority: String(state.authority ?? ""),
    graph_id: String(state.graph_id ?? ""),
    mode: String(state.mode ?? ""),
    summary: Object.fromEntries(
      Object.entries(summary).map(([key, value]) => [key, Number(value) || 0]),
    ),
    ready_batch_ids: asStringArray(state.ready_batch_ids),
    running_batch_ids: asStringArray(state.running_batch_ids),
    committed_batch_ids: asStringArray(state.committed_batch_ids),
    failed_batch_ids: asStringArray(state.failed_batch_ids),
    active_batch_by_node: Object.fromEntries(Object.entries(activeBatchByNode).map(([key, value]) => [key, String(value ?? "")])),
    active_execution_by_node: Object.fromEntries(Object.entries(activeExecutionByNode).map(([key, value]) => [key, String(value ?? "")])),
    active_execution_by_batch: Object.fromEntries(Object.entries(activeExecutionByBatch).map(([key, value]) => [key, String(value ?? "")])),
    execution_mode_by_plan: Object.fromEntries(Object.entries(executionModeByPlan).map(([key, value]) => [key, String(value ?? "")])),
    plans: asRecordArray(state.plans ?? state.plan_states),
    batches: asRecordArray(state.batches ?? state.batch_states),
    execution_instances: asRecordArray(state.execution_instances ?? state.batch_execution_instances),
    merge_states: asRecordArray(state.merge_states),
  };
}

export function buildTaskGraphSchedulerSummary(rawState: unknown): TaskGraphSchedulerSummary {
  const state = asRecord(rawState);
  const diagnostics = asRecord(state.diagnostics);
  const nodeStates = asRecordArray(state.node_states);
  const edgeStates = asRecordArray(state.edge_states);
  const phaseStates = asRecordArray(state.phase_states);
  return {
    available: String(state.authority ?? "") === "task_system.task_graph_scheduler_state",
    graph_id: String(state.graph_id ?? ""),
    mode: String(state.mode ?? ""),
    terminal_status: String(state.terminal_status ?? ""),
    ready_node_ids: asStringArray(state.ready_node_ids),
    blocked_node_ids: asStringArray(state.blocked_node_ids),
    running_node_ids: asStringArray(state.running_node_ids),
    completed_node_ids: asStringArray(state.completed_node_ids),
    failed_node_ids: asStringArray(state.failed_node_ids),
    phase_count: Number(diagnostics.phase_count ?? phaseStates.length) || phaseStates.length,
    node_count: Number(diagnostics.node_count ?? nodeStates.length) || nodeStates.length,
    edge_count: Number(diagnostics.edge_count ?? edgeStates.length) || edgeStates.length,
    active_phase_ids: asStringArray(diagnostics.active_phase_ids),
    active_sequence_by_phase: asNumberRecord(diagnostics.active_sequence_by_phase),
    phase_states: phaseStates,
    node_states: nodeStates,
    edge_states: edgeStates,
  };
}
