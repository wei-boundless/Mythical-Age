import { request } from "./shared";
import type {
  HarnessSessionLiveMonitor,
  HarnessSessionTaskRuns,
  HarnessTaskRunLiveMonitor,
  HarnessTaskRunTrace,
  HarnessTurnRunTrace,
  OrchestrationAgentGroupUpsertPayload,
  OrchestrationAgentRuntimeCatalog,
  OrchestrationAgentRuntimeProfileUpsertPayload,
  OrchestrationAgentUpsertPayload,
  OrchestrationCapabilityItem,
  OrchestrationCatalog,
  OrchestrationRuntimeOptionsPayload,
  OrchestrationSnapshot,
  RuntimeMonitorActionPayload,
  RuntimeMonitorActionResult,
  RuntimeMonitorEnvelope,
  RuntimeMonitorManagement,
  RuntimeResourceInventory,
} from "./types";

export async function runOrchestrationDryRun(payload: {
  session_id: string;
  message: string;
  explicit_subtasks?: Array<Record<string, unknown>>;
}) {
  return request<OrchestrationSnapshot>("/orchestration/dry-run", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getOrchestrationCatalog() {
  return request<OrchestrationCatalog>("/orchestration/catalog");
}

export async function refreshOrchestrationCatalog() {
  return request<OrchestrationCatalog>("/orchestration/catalog/refresh", {
    method: "POST"
  });
}

export async function setOrchestrationPlanMode(mode: string) {
  return request<{ mode: string; supported_modes: string[] }>("/orchestration/plan-mode", {
    method: "PUT",
    body: JSON.stringify({ mode })
  });
}

export async function getOrchestrationAgents(options: { includeOptions?: boolean } = {}) {
  const includeOptions = options.includeOptions ?? true;
  const suffix = includeOptions ? "" : "?include_options=false";
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agents${suffix}`);
}

export async function getOrchestrationRuntimeOptions() {
  return request<OrchestrationRuntimeOptionsPayload>("/orchestration/runtime-options");
}

export async function getOrchestrationCapabilityItems() {
  return request<{ authority: string; capability_items: OrchestrationCapabilityItem[] }>("/orchestration/capability-items");
}

export async function getNextOrchestrationWorkerAgentId() {
  return request<{ authority: string; agent_id: string }>("/orchestration/agents/next-worker-id");
}

export async function upsertOrchestrationAgent(agentId: string, payload: OrchestrationAgentUpsertPayload) {
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agents/${encodeURIComponent(agentId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteOrchestrationAgent(agentId: string) {
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agents/${encodeURIComponent(agentId)}`, {
    method: "DELETE"
  });
}

export async function upsertOrchestrationAgentGroup(groupId: string, payload: OrchestrationAgentGroupUpsertPayload) {
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agent-groups/${encodeURIComponent(groupId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteOrchestrationAgentGroup(groupId: string) {
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agent-groups/${encodeURIComponent(groupId)}`, {
    method: "DELETE"
  });
}

export async function updateOrchestrationAgentRuntimeProfile(
  agentId: string,
  payload: OrchestrationAgentRuntimeProfileUpsertPayload
) {
  return request<OrchestrationAgentRuntimeCatalog>(
    `/orchestration/agents/${encodeURIComponent(agentId)}/runtime-profile`,
    {
      method: "PUT",
      body: JSON.stringify(payload)
    }
  );
}

export async function listOrchestrationHarnessTaskRuns(sessionId: string) {
  return request<HarnessSessionTaskRuns>(
    `/orchestration/harness/sessions/${encodeURIComponent(sessionId)}/task-runs`
  );
}

export async function getRunMonitor(limit = 30) {
  return request<RuntimeMonitorEnvelope>(
    `/orchestration/runtime-monitor?limit=${encodeURIComponent(String(limit))}`
  );
}

export async function getRunMonitorManagement(limit = 80) {
  return request<{ authority: string; monitor: RuntimeMonitorEnvelope; management: RuntimeMonitorManagement; updated_at: number }>(
    `/orchestration/runtime-monitor/management?limit=${encodeURIComponent(String(limit))}`,
  );
}

export async function preflightRunMonitorAction(payload: RuntimeMonitorActionPayload) {
  return request<RuntimeMonitorActionResult>("/orchestration/runtime-monitor/actions/preflight", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function executeRunMonitorAction(payload: RuntimeMonitorActionPayload) {
  return request<RuntimeMonitorActionResult>("/orchestration/runtime-monitor/actions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getOrchestrationHarnessSessionLiveMonitor(sessionId: string) {
  return request<HarnessSessionLiveMonitor>(
    `/orchestration/runtime-monitor/sessions/${encodeURIComponent(sessionId)}`
  );
}

export async function getOrchestrationResourceInventory() {
  return request<RuntimeResourceInventory>("/orchestration/resource-inventory");
}

export async function getOrchestrationHarnessTrace(
  taskRunId: string,
  options?: {
    includePayloads?: boolean;
    includeModelMessages?: boolean;
    eventLimit?: number;
  }
) {
  const params = new URLSearchParams();
  if (options?.includePayloads) {
    params.set("include_payloads", "true");
  }
  if (options?.includeModelMessages) {
    params.set("include_model_messages", "true");
  }
  if (options?.eventLimit) {
    params.set("event_limit", String(options.eventLimit));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<HarnessTaskRunTrace>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}${suffix}`
  );
}

export async function getOrchestrationHarnessTurnTrace(
  turnRunId: string,
  options?: {
    includePayloads?: boolean;
    includeModelMessages?: boolean;
    eventLimit?: number;
  }
) {
  const params = new URLSearchParams();
  if (options?.includePayloads) {
    params.set("include_payloads", "true");
  }
  if (options?.includeModelMessages) {
    params.set("include_model_messages", "true");
  }
  if (options?.eventLimit) {
    params.set("event_limit", String(options.eventLimit));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<HarnessTurnRunTrace>(
    `/orchestration/harness/turn-runs/${encodeURIComponent(turnRunId)}${suffix}`
  );
}

export async function getOrchestrationHarnessTaskRunLiveMonitor(taskRunId: string) {
  return request<HarnessTaskRunLiveMonitor>(
    `/orchestration/runtime-monitor/task-runs/${encodeURIComponent(taskRunId)}`
  );
}

export async function pauseOrchestrationHarnessTaskRun(taskRunId: string, reason = "", expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/pause`,
    {
      method: "POST",
      body: JSON.stringify({ reason, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function resumeOrchestrationHarnessTaskRun(taskRunId: string, maxSteps = 12, expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify({ max_steps: maxSteps, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function approveOrchestrationHarnessTaskRunToolCall(taskRunId: string, reason = "", maxSteps = 12, expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/approve-tool-call`,
    {
      method: "POST",
      body: JSON.stringify({ reason, max_steps: maxSteps, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function approveOrchestrationHarnessTaskRunLaunch(taskRunId: string, reason = "", maxSteps = 12, expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/approve-launch`,
    {
      method: "POST",
      body: JSON.stringify({ reason, max_steps: maxSteps, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function stopOrchestrationHarnessTaskRun(taskRunId: string, reason = "", expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/stop`,
    {
      method: "POST",
      body: JSON.stringify({ reason, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function getHarnessTaskRunArtifacts(taskRunId: string) {
  return request<{
    authority: string;
    task_run_id: string;
    artifact_root: string;
    files: string[];
    created_files: string[];
    artifact_refs: string[];
  }>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/artifacts`
  );
}

export async function getHarnessTaskRunMemoryReceipts(taskRunId: string) {
  return request<{
    authority: string;
    task_run_id: string;
    memory_operations: Array<Record<string, unknown>>;
    stage_results: Array<Record<string, unknown>>;
  }>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/memory-receipts`
  );
}
