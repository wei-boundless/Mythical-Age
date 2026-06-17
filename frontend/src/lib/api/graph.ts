import { request } from "./shared";
import type {
  GraphHarnessConfigPayload,
  GraphRunBackgroundSubmitResult,
  GraphRunControlResult,
  GraphRunDispatchReadyResult,
  GraphRunMonitorView,
  GraphTaskDefinitionList,
  GraphTaskInstanceArtifacts,
  GraphTaskInstanceCreateResult,
  GraphTaskInstanceDetail,
  GraphTaskInstanceFileReadResult,
  GraphTaskInstanceFileTree,
  GraphTaskInstanceFileWriteResult,
  GraphTaskInstanceList,
  GraphTaskInstanceMonitor,
  GraphTaskInstanceRunStartResult,
  HumanEdgeDecisionSubmitRequest,
  HumanEdgeDecisionSubmitResult,
  ProjectRuntimeStatusView,
  SessionScope,
  SessionSummary,
  TaskGraphRunStartResult,
  WritingChapterActionRequest,
  WritingChapterActionSubmitResult,
  WritingGraphInstanceDesk,
} from "./types";

export async function getProjectRuntimeStatus(projectId: string) {
  return request<ProjectRuntimeStatusView>(
    `/orchestration/projects/${encodeURIComponent(projectId)}/runtime-status`
  );
}

export async function startTaskGraphHarnessRun(
  graphId: string,
  payload: {
    session_id: string;
    task_id?: string;
    session_scope?: Partial<SessionScope>;
    initial_inputs?: Record<string, unknown>;
    include_trace?: boolean;
    dispatch_ready?: boolean;
    run_mode?: "dispatch_only" | "auto_run" | string;
    wait_for_completion?: boolean;
    runner_budget?: Record<string, unknown>;
    runtime_overrides?: Record<string, unknown>;
    runtime_settings_patch?: Record<string, unknown>;
  }
) {
  return request<TaskGraphRunStartResult>(
    `/orchestration/harness/task-graphs/${encodeURIComponent(graphId)}/start`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getPublishedTaskGraphHarnessConfig(graphId: string) {
  return request<GraphHarnessConfigPayload>(
    `/orchestration/harness/task-graphs/${encodeURIComponent(graphId)}/published-config`
  );
}

export async function submitGraphRunUntilIdle(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    session_scope?: Partial<SessionScope>;
    max_node_executions?: number;
    max_loop_iterations?: number;
    max_node_steps?: number;
    max_dispatches?: number;
    max_runtime_seconds?: number;
    max_dispatch_requests?: number | null;
  }
) {
  return request<GraphRunBackgroundSubmitResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/run-until-idle/background`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function pauseGraphRun(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    session_scope?: Partial<SessionScope>;
    reason?: string;
  }
) {
  return request<GraphRunControlResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/pause`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function resumeGraphRun(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    session_scope?: Partial<SessionScope>;
    reason?: string;
  }
) {
  return request<GraphRunControlResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getGraphRunMonitor(
  graphRunId: string,
  graphHarnessConfigId = "",
  eventLimit = 80,
  sessionScope?: Partial<SessionScope>,
) {
  const params = new URLSearchParams();
  if (graphHarnessConfigId) {
    params.set("graph_harness_config_id", graphHarnessConfigId);
  }
  if (sessionScope?.workspace_view) params.set("workspace_view", sessionScope.workspace_view);
  if (sessionScope?.task_environment_id) params.set("task_environment_id", sessionScope.task_environment_id);
  if (sessionScope?.project_id) params.set("project_id", sessionScope.project_id);
  params.set("event_limit", String(Math.max(1, Math.min(Number(eventLimit || 80), 240))));
  return request<GraphRunMonitorView>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/monitor?${params.toString()}`
  );
}

export async function listGraphTasks() {
  return request<GraphTaskDefinitionList>("/orchestration/graph-tasks");
}

export async function listGraphTaskInstances(graphId: string) {
  return request<GraphTaskInstanceList>(
    `/orchestration/graph-tasks/${encodeURIComponent(graphId)}/instances`
  );
}

export async function createGraphTaskInstance(
  graphId: string,
  payload: {
    title: string;
    description?: string;
    initial_inputs?: Record<string, unknown>;
    run_config?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
  }
) {
  return request<GraphTaskInstanceCreateResult>(
    `/orchestration/graph-tasks/${encodeURIComponent(graphId)}/instances`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getGraphTaskInstance(instanceId: string) {
  return request<GraphTaskInstanceDetail>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}`
  );
}

export async function startGraphTaskInstanceRun(
  instanceId: string,
  payload: {
    initial_inputs?: Record<string, unknown>;
    dispatch_ready?: boolean;
    run_mode?: "dispatch_only" | "auto_run" | string;
    wait_for_completion?: boolean;
    runner_budget?: Record<string, unknown>;
    runtime_overrides?: Record<string, unknown>;
    runtime_settings_patch?: Record<string, unknown>;
  } = {}
) {
  return request<GraphTaskInstanceRunStartResult>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/runs`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getGraphTaskInstanceMonitor(instanceId: string, eventLimit = 80) {
  const params = new URLSearchParams();
  params.set("event_limit", String(Math.max(1, Math.min(Number(eventLimit || 80), 240))));
  return request<GraphTaskInstanceMonitor>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/monitor?${params.toString()}`
  );
}

export async function getWritingGraphInstanceDesk(
  instanceId: string,
  eventLimit = 80,
  options: {
    includeRuntime?: boolean;
    includeFileTree?: boolean;
  } = {}
) {
  const params = new URLSearchParams();
  params.set("event_limit", String(Math.max(1, Math.min(Number(eventLimit || 80), 240))));
  if (options.includeRuntime !== undefined) params.set("include_runtime", String(options.includeRuntime));
  if (options.includeFileTree !== undefined) params.set("include_file_tree", String(options.includeFileTree));
  return request<WritingGraphInstanceDesk>(
    `/orchestration/writing-graph-instances/${encodeURIComponent(instanceId)}/desk?${params.toString()}`
  );
}

export async function submitWritingGraphChapterAction(
  instanceId: string,
  payload: WritingChapterActionRequest
) {
  return request<WritingChapterActionSubmitResult>(
    `/orchestration/writing-graph-instances/${encodeURIComponent(instanceId)}/chapter-actions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function listGraphTaskInstanceNodeSessions(instanceId: string) {
  return request<{
    authority: string;
    graph_task_instance_id: string;
    sessions: SessionSummary[];
    summary?: Record<string, unknown>;
  }>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/node-sessions`
  );
}

export async function getGraphTaskInstanceFileTree(
  instanceId: string,
  options: {
    path?: string;
    maxDepth?: number;
    maxEntries?: number;
  } = {}
) {
  const params = new URLSearchParams();
  if (options.path) params.set("path", options.path);
  if (options.maxDepth !== undefined) params.set("max_depth", String(options.maxDepth));
  if (options.maxEntries !== undefined) params.set("max_entries", String(options.maxEntries));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<GraphTaskInstanceFileTree>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/files/tree${suffix}`
  );
}

export async function readGraphTaskInstanceFile(instanceId: string, path: string) {
  const params = new URLSearchParams({ path });
  return request<GraphTaskInstanceFileReadResult>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/files?${params.toString()}`
  );
}

export async function writeGraphTaskInstanceFile(instanceId: string, path: string, content: string) {
  return request<GraphTaskInstanceFileWriteResult>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/files`,
    {
      method: "PUT",
      body: JSON.stringify({ path, content }),
    }
  );
}

export async function listGraphTaskInstanceArtifacts(instanceId: string) {
  return request<GraphTaskInstanceArtifacts>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/artifacts`
  );
}

export async function listGraphTaskInstanceHumanEdgeDecisions(instanceId: string, limit = 100) {
  const params = new URLSearchParams();
  params.set("limit", String(Math.max(1, Math.min(Number(limit || 100), 500))));
  return request<{
    authority: string;
    graph_task_instance_id: string;
    decisions: Array<Record<string, unknown>>;
    summary?: Record<string, unknown>;
  }>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/human-edge-decisions?${params.toString()}`
  );
}

export async function submitGraphTaskInstanceHumanEdgeDecision(
  instanceId: string,
  payload: HumanEdgeDecisionSubmitRequest
) {
  return request<HumanEdgeDecisionSubmitResult>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/human-edge-decisions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function dispatchGraphRunReadyNodes(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    session_scope?: Partial<SessionScope>;
    max_requests?: number;
  }
) {
  return request<GraphRunDispatchReadyResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/dispatch-ready`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
