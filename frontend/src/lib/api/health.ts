import { request } from "./shared";
import type {
  HealthAgentConversationMessage,
  HealthAgentConversationSession,
  HealthAgentRunPreview,
  HealthCommandResponse,
  HealthEfficiency,
  HealthIssue,
  HealthManagementReceipt,
  HealthMonitorGovernance,
  HealthReport,
  HealthRiskEvent,
  HealthSystemOverview,
  HealthTaskRecord,
  HealthTaskRecordMaintenance,
  HealthTaskRecordPruneResult,
  HealthTokenUsage,
  HealthTraceReport,
} from "./types";

export async function getHealthSystemOverview() {
  return request<HealthSystemOverview>("/health-system/overview");
}

export async function getHealthSystemTasks(limit = 100) {
  return request<{
    authority: string;
    tasks: HealthTaskRecord[];
    summary: Record<string, number>;
    updated_at: number;
  }>(`/health-system/tasks?limit=${limit}`);
}

export async function getHealthSystemTaskDetail(taskRunId: string) {
  return request<{
    authority: string;
    task: HealthTaskRecord;
    monitor: Record<string, unknown>;
    task_graph_monitor: Record<string, unknown>;
    risks: HealthRiskEvent[];
    recent_events: Array<Record<string, unknown>>;
    updated_at: number;
  }>(`/health-system/tasks/${encodeURIComponent(taskRunId)}`);
}

export async function getHealthSystemTaskRecordMaintenance(bucket = "static", minAgeSeconds = 24 * 60 * 60) {
  return request<HealthTaskRecordMaintenance>(
    `/health-system/task-records/maintenance?bucket=${encodeURIComponent(bucket)}&min_age_seconds=${minAgeSeconds}`,
  );
}

export async function pruneHealthSystemTaskRecords(payload: {
  bucket?: "static" | "completed" | "failed" | "diagnostics" | string;
  task_run_ids?: string[];
  dry_run?: boolean;
  min_age_seconds?: number;
  operation?: string;
}) {
  return request<HealthTaskRecordPruneResult>("/health-system/task-records/prune", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getHealthSystemMonitorGovernance() {
  return request<HealthMonitorGovernance>("/health-system/monitor-governance");
}

export async function getHealthSystemRisks(limit = 100) {
  return request<{
    authority: string;
    risks: HealthRiskEvent[];
    summary: Record<string, number>;
    updated_at: number;
  }>(`/health-system/risks?limit=${limit}`);
}

export async function getHealthSystemTokenUsage(limit = 100) {
  return request<HealthTokenUsage>(`/health-system/token-usage?limit=${limit}`);
}

export async function getHealthSystemEfficiency(limit = 100) {
  return request<HealthEfficiency>(`/health-system/efficiency?limit=${limit}`);
}

export async function createHealthAgentConversationSession(payload: {
  active_issue_ref?: string;
  active_run_ref?: string;
}) {
  return request<{
    authority: string;
    session: HealthAgentConversationSession;
    messages: HealthAgentConversationMessage[];
  }>("/health-system/conversation-sessions", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function sendHealthAgentConversationMessage(
  sessionId: string,
  payload: {
    role?: "user" | "assistant" | "system" | string;
    content: string;
    command_ref?: string;
    receipt_ref?: string;
    report_ref?: string;
  }
) {
  return request<{
    authority: string;
    message: HealthAgentConversationMessage;
    assistant_message: HealthAgentConversationMessage | null;
  }>(`/health-system/conversation-sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createHealthManagementCommand(payload: {
  command_type: string;
  initiator_type: "user" | "agent" | "system" | "test_system" | string;
  initiator_ref?: string;
  requested_by?: string;
  source?: string;
  conversation_session_ref?: string;
  target_scope?: string;
  target_ref?: string;
  health_action?: string;
  payload?: Record<string, unknown>;
}) {
  return request<HealthCommandResponse>("/health-system/commands", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getHealthManagementReceipt(receiptId: string) {
  return request<HealthManagementReceipt>(`/health-system/receipts/${encodeURIComponent(receiptId)}`);
}

export async function listHealthReports() {
  return request<{ authority: string; reports: HealthReport[] }>("/health-system/reports");
}

export async function createHealthIssue(payload: {
  title: string;
  owner_system?: string;
  severity?: string;
  status?: string;
  source?: string;
  conversation_ref?: string;
  runtime_trace_refs?: string[];
  prompt_manifest_refs?: string[];
  memory_refs?: string[];
  assertion_refs?: string[];
  metadata?: Record<string, unknown>;
}) {
  return request<HealthIssue>("/health-system/issues", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getHealthAgentRunResult(runId: string) {
  return request<Record<string, unknown>>(`/health-system/agent-runs/${encodeURIComponent(runId)}/result`);
}

export async function getHealthAgentRunTraceReport(runId: string) {
  return request<HealthTraceReport>(`/health-system/agent-runs/${encodeURIComponent(runId)}/trace-report`);
}

export async function previewHealthAgentRun(issueId: string, healthAction = "issue_triage") {
  return request<HealthAgentRunPreview>(
    `/health-system/issues/${encodeURIComponent(issueId)}/agent-runs/preview`,
    {
      method: "POST",
      body: JSON.stringify({ health_action: healthAction })
    }
  );
}
