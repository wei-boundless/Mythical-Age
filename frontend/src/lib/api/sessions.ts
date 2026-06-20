import { request, sessionScopeQuery, withSessionScopeQuery } from "./shared";
import type {
  CodeEnvironmentWorkspaceTree,
  ConversationState,
  ProjectWorkspaceSummary,
  SessionHistory,
  SessionProjectBinding,
  SessionScope,
  SessionSummary,
  SessionTimeline,
  SessionTruncateResponse,
  WorkbenchCurrentSessionPayload,
} from "./types";

export async function listSessions(scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  const query = params.toString();
  return request<SessionSummary[]>(query ? `/sessions?${query}` : "/sessions");
}

export async function createSession(
  title = "New Session",
  scope?: Partial<SessionScope>,
  projectBinding?: Pick<SessionProjectBinding, "workspace_root" | "source">,
) {
  return request<SessionSummary>("/sessions", {
    method: "POST",
    body: JSON.stringify({ title, ...(scope ? { scope } : {}), ...(projectBinding ? { project_binding: projectBinding } : {}) })
  });
}

export async function getSessionSummary(sessionId: string, scope?: Partial<SessionScope>) {
  return request<SessionSummary>(withSessionScopeQuery(`/sessions/${sessionId}`, scope));
}

export async function getWorkbenchCurrentSession() {
  return request<WorkbenchCurrentSessionPayload>("/workbench/current-session");
}

export async function setWorkbenchCurrentSession(ref: {
  sessionId: string;
  scope?: Partial<SessionScope>;
  poolKey?: string;
}) {
  return request<WorkbenchCurrentSessionPayload>("/workbench/current-session", {
    method: "PUT",
    body: JSON.stringify({
      session_id: ref.sessionId,
      scope: ref.scope ?? {},
      pool_key: ref.poolKey ?? "main-chat",
    }),
  });
}

export async function clearWorkbenchCurrentSession(sessionId?: string) {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  const query = params.toString();
  return request<WorkbenchCurrentSessionPayload>(query ? `/workbench/current-session?${query}` : "/workbench/current-session", {
    method: "DELETE",
  });
}

export async function renameSession(sessionId: string, title: string, scope?: Partial<SessionScope>) {
  return request<SessionSummary>(withSessionScopeQuery(`/sessions/${sessionId}`, scope), {
    method: "PUT",
    body: JSON.stringify({ title })
  });
}

export async function deriveSessionTitleFromFirstUserMessage(sessionId: string, scope?: Partial<SessionScope>) {
  return request<{ session_id: string; title: string }>(withSessionScopeQuery(`/sessions/${sessionId}/generate-title`, scope), {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function deleteSession(sessionId: string, scope?: Partial<SessionScope>) {
  return request<{ ok: boolean }>(withSessionScopeQuery(`/sessions/${sessionId}`, scope), {
    method: "DELETE"
  });
}

export async function getSessionHistory(sessionId: string, scope?: Partial<SessionScope>) {
  return request<SessionHistory>(withSessionScopeQuery(`/sessions/${sessionId}/history`, scope));
}

export async function getSessionConversationState(sessionId: string, scope?: Partial<SessionScope>) {
  return request<ConversationState>(withSessionScopeQuery(`/sessions/${sessionId}/conversation-state`, scope));
}

export async function setSessionActiveTaskEnvironment(
  sessionId: string,
  payload: {
    task_environment_id: string;
    environment_label?: string;
    source?: string;
  },
  scope?: Partial<SessionScope>,
) {
  return request<ConversationState>(withSessionScopeQuery(`/sessions/${sessionId}/active-task-environment`, scope), {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function setSessionPermissionMode(sessionId: string, mode: string, scope?: Partial<SessionScope>) {
  return request<ConversationState>(withSessionScopeQuery(`/sessions/${sessionId}/permission-mode`, scope), {
    method: "PUT",
    body: JSON.stringify({ mode }),
  });
}

export async function listProjectWorkspaces() {
  return request<{
    authority: string;
    projects: ProjectWorkspaceSummary[];
    summary: { project_count: number };
  }>("/project-workspaces");
}

export async function registerProjectWorkspace(payload: Pick<SessionProjectBinding, "workspace_root" | "source">) {
  return request<{
    authority: string;
    project: ProjectWorkspaceSummary;
  }>("/project-workspaces", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function selectProjectWorkspaceDirectory() {
  return request<{
    authority: string;
    project: ProjectWorkspaceSummary;
    selected_path: string;
  }>("/project-workspaces/select-directory", {
    method: "POST",
  });
}

export async function removeProjectWorkspace(projectKey: string, options: { detachSessions?: boolean } = {}) {
  const params = new URLSearchParams();
  params.set("detach_sessions", String(options.detachSessions ?? true));
  return request<{
    authority: string;
    project_key: string;
    ok: boolean;
    project: ProjectWorkspaceSummary;
    removed_registry_entry: boolean;
    detached_sessions: SessionSummary[];
    detached_session_count: number;
  }>(`/project-workspaces/${encodeURIComponent(projectKey)}?${params.toString()}`, {
    method: "DELETE",
  });
}

export async function listProjectWorkspaceSessions(projectKey: string) {
  return request<{
    authority: string;
    project_key: string;
    sessions: SessionSummary[];
  }>(`/project-workspaces/${encodeURIComponent(projectKey)}/sessions`);
}

export async function createProjectWorkspaceSession(projectKey: string, title = "New Session") {
  return request<{
    authority: string;
    project_key: string;
    session: SessionSummary;
    created: boolean;
  }>(`/project-workspaces/${encodeURIComponent(projectKey)}/sessions`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function getProjectWorkspaceTree(projectKey: string, options: { maxDepth?: number; maxEntries?: number } = {}) {
  const params = new URLSearchParams();
  params.set("max_depth", String(options.maxDepth || 10));
  params.set("max_entries", String(options.maxEntries || 10000));
  return request<CodeEnvironmentWorkspaceTree>(
    `/project-workspaces/${encodeURIComponent(projectKey)}/workspace-tree?${params.toString()}`
  );
}

export async function openProjectWorkspaceInVSCode(projectKey: string) {
  return request<{
    authority: string;
    ok: boolean;
    project: ProjectWorkspaceSummary;
    command: string[];
    window_mode: string;
  }>(`/project-workspaces/${encodeURIComponent(projectKey)}/open-vscode`, {
    method: "POST",
  });
}

export async function getSessionTimeline(sessionId: string, scope?: Partial<SessionScope>) {
  return request<SessionTimeline>(withSessionScopeQuery(`/sessions/${sessionId}/timeline`, scope));
}

export async function getSessionRuntimeProjection(sessionId: string, scope?: Partial<SessionScope>) {
  return request<SessionTimeline>(withSessionScopeQuery(`/sessions/${sessionId}/runtime-projection`, scope));
}

export async function truncateSessionMessages(sessionId: string, messageIndex: number, scope?: Partial<SessionScope>) {
  return request<SessionTruncateResponse>(withSessionScopeQuery(`/sessions/${sessionId}/messages/truncate`, scope), {
    method: "POST",
    body: JSON.stringify({ message_index: messageIndex })
  });
}

export async function getSessionTokens(sessionId: string, scope?: Partial<SessionScope>) {
  return request<{
    system_tokens: number;
    message_tokens: number;
    total_tokens: number;
    context_meter?: {
      current_context_tokens?: number;
      current_context_ratio?: number;
      compaction_pressure_tokens?: number;
      context_window_tokens?: number;
      input_capacity_tokens?: number;
      replacement_threshold_tokens?: number;
      compaction_pressure_ratio?: number;
      compaction_remaining_tokens?: number;
      compaction_remaining_ratio?: number;
      pressure_level?: string;
    };
    context_recovery_package?: {
      present?: boolean;
      fresh?: boolean;
      source?: string;
      schema_version?: string;
      covered_message_count?: number;
      covered_event_run_id?: string;
      covered_event_offset_end?: number | null;
      summary_hash?: string;
      source_summary_hash?: string;
      freshness_status?: string;
      stale_reason?: string;
    };
    compaction_readiness?: {
      context_recovery_package_present?: boolean;
      context_recovery_package_fresh?: boolean;
      context_recovery_package_source?: string;
    };
    cumulative_transcript_tokens?: number;
    cumulative_transcript_message_count?: number;
    compression_saved_tokens?: number;
    compression_ratio?: number;
    raw_history_tokens: number;
    history_tokens: number;
    history_budget_tokens: number;
    history_remaining_tokens: number;
    history_usage_ratio: number;
    history_remaining_ratio: number;
    history_pressure_level: string;
    history_compaction_strategy: string;
    history_did_compact: boolean;
    history_did_microcompact: boolean;
    history_did_full_compact: boolean;
  }>(withSessionScopeQuery(`/tokens/session/${sessionId}`, scope));
}
