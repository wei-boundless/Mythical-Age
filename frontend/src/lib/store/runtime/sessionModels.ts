import type { ProjectWorkspaceSummary, SessionScope, SessionSummary } from "@/lib/api";

import type { SessionPoolKey } from "../types";
import { GRAPH_ONLY_TASK_ENVIRONMENT_IDS, GRAPH_TASK_WORKSPACE_VIEW, MAIN_CHAT_POOL_KEY } from "./constants";

export function sessionTaskEnvironmentId(session: SessionSummary) {
  return String(
    session.scope?.task_environment_id
    || session.task_binding?.task_environment_id
    || session.task_binding?.session_scope?.task_environment_id
    || "",
  ).trim();
}

export function isVisibleMainChatSession(session: SessionSummary) {
  const workspaceView = String(session.scope?.workspace_view || "").trim();
  if (workspaceView === "project" || workspaceView === "task_environment" || workspaceView === GRAPH_TASK_WORKSPACE_VIEW) {
    return false;
  }
  if (String(session.task_binding?.kind || "").trim() === "task_graph") {
    return false;
  }
  if (String(session.task_binding?.graph_run_id || "").trim() || String(session.task_binding?.graph_harness_config_id || "").trim()) {
    return false;
  }
  return !GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(sessionTaskEnvironmentId(session));
}

export function visibleMainChatSessions(sessions: SessionSummary[]) {
  return sessions.filter(isVisibleMainChatSession);
}

export function sessionProjectRoot(session: SessionSummary | null | undefined) {
  return String(session?.conversation_state?.project_binding?.workspace_root || "").trim();
}

export function workspaceRootKey(root: string) {
  return root.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

export function sessionBelongsToProject(session: SessionSummary, workspaceRoot: string) {
  const root = workspaceRootKey(workspaceRoot);
  return Boolean(root && workspaceRootKey(sessionProjectRoot(session)) === root);
}

export function unboundMainChatSessions(sessions: SessionSummary[]) {
  return visibleMainChatSessions(sessions).filter((session) => !sessionProjectRoot(session));
}

export function mergeSessionSummaries(existing: SessionSummary[], incoming: SessionSummary[]) {
  const byId = new Map<string, SessionSummary>();
  for (const session of existing) byId.set(session.id, session);
  for (const session of incoming) byId.set(session.id, session);
  return [...byId.values()].sort((a, b) => b.updated_at - a.updated_at);
}

export function mergeProjectWorkspaces(existing: ProjectWorkspaceSummary[], incoming: ProjectWorkspaceSummary[]) {
  const byKey = new Map<string, ProjectWorkspaceSummary>();
  for (const project of existing) byKey.set(project.key, project);
  for (const project of incoming) byKey.set(project.key, project);
  return [...byKey.values()].sort((a, b) => {
    const bySeen = Number(b.last_seen_at || 0) - Number(a.last_seen_at || 0);
    if (bySeen) return bySeen;
    return a.name.localeCompare(b.name);
  });
}

export function sessionPoolKeyForScope(scope: Partial<SessionScope> | undefined): SessionPoolKey {
  if (scope?.workspace_view === GRAPH_TASK_WORKSPACE_VIEW) {
    return `graph_task:${String(scope.project_id || "").trim()}` as SessionPoolKey;
  }
  if (scope?.workspace_view === "task_environment") {
    return `task_environment:${String(scope.task_environment_id || "").trim()}:${String(scope.project_id || "").trim()}` as SessionPoolKey;
  }
  return MAIN_CHAT_POOL_KEY;
}
