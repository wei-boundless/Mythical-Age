import { request } from "./shared";
import type {
  HarnessSessionLiveMonitor,
  HarnessSessionTaskRuns,
  HarnessTaskRunLiveMonitor,
  HarnessTaskRunTrace,
  HarnessTurnRunTrace,
  RunMonitorActionPayload,
  RunMonitorActionResult,
  RunMonitorEnvelope,
  RunMonitorManagement,
} from "./types";

export async function listHarnessTaskRuns(sessionId: string) {
  return request<HarnessSessionTaskRuns>(
    `/harness/sessions/${encodeURIComponent(sessionId)}/task-runs`
  );
}

export async function getRunMonitor(limit = 30) {
  return request<RunMonitorEnvelope>(
    `/harness/run-monitor?limit=${encodeURIComponent(String(limit))}`
  );
}

export async function getRunMonitorManagement(limit = 80) {
  return request<{ authority: string; monitor: RunMonitorEnvelope; management: RunMonitorManagement; updated_at: number }>(
    `/harness/run-monitor/management?limit=${encodeURIComponent(String(limit))}`,
  );
}

export async function preflightRunMonitorAction(payload: RunMonitorActionPayload) {
  return request<RunMonitorActionResult>("/harness/run-monitor/actions/preflight", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function executeRunMonitorAction(payload: RunMonitorActionPayload) {
  return request<RunMonitorActionResult>("/harness/run-monitor/actions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getHarnessSessionLiveMonitor(sessionId: string) {
  return request<HarnessSessionLiveMonitor>(
    `/harness/run-monitor/sessions/${encodeURIComponent(sessionId)}`
  );
}

export async function getHarnessTrace(
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
    `/harness/task-runs/${encodeURIComponent(taskRunId)}${suffix}`
  );
}

export async function getHarnessTurnTrace(
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
    `/harness/turn-runs/${encodeURIComponent(turnRunId)}${suffix}`
  );
}

export async function getHarnessTaskRunLiveMonitor(taskRunId: string) {
  return request<HarnessTaskRunLiveMonitor>(
    `/harness/run-monitor/task-runs/${encodeURIComponent(taskRunId)}`
  );
}

export async function pauseHarnessTaskRun(taskRunId: string, reason = "", expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/harness/task-runs/${encodeURIComponent(taskRunId)}/pause`,
    {
      method: "POST",
      body: JSON.stringify({ reason, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function resumeHarnessTaskRun(taskRunId: string, maxSteps = 12, expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/harness/task-runs/${encodeURIComponent(taskRunId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify({ max_steps: maxSteps, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function approveHarnessTaskRunToolCall(taskRunId: string, reason = "", maxSteps = 12, expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/harness/task-runs/${encodeURIComponent(taskRunId)}/approve-tool-call`,
    {
      method: "POST",
      body: JSON.stringify({ reason, max_steps: maxSteps, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function approveHarnessTaskRunLaunch(taskRunId: string, reason = "", maxSteps = 12, expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/harness/task-runs/${encodeURIComponent(taskRunId)}/approve-launch`,
    {
      method: "POST",
      body: JSON.stringify({ reason, max_steps: maxSteps, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function stopHarnessTaskRun(taskRunId: string, reason = "", expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/harness/task-runs/${encodeURIComponent(taskRunId)}/stop`,
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
    `/harness/task-runs/${encodeURIComponent(taskRunId)}/artifacts`
  );
}

export async function getHarnessTaskRunMemoryReceipts(taskRunId: string) {
  return request<{
    authority: string;
    task_run_id: string;
    memory_operations: Array<Record<string, unknown>>;
    stage_results: Array<Record<string, unknown>>;
  }>(
    `/harness/task-runs/${encodeURIComponent(taskRunId)}/memory-receipts`
  );
}
