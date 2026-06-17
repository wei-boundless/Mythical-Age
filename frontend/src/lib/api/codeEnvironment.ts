import { request, sessionScopeQuery } from "./shared";
import type {
  CodeEnvironmentGitStatus,
  CodeEnvironmentStatus,
  CodeEnvironmentWorkspaceTree,
  PiSidecarCommandResponse,
  PiSidecarLifecycleResponse,
  SessionScope,
} from "./types";

export async function getCodeEnvironment(host?: {
  mode?: "web" | "desktop";
  localRuntimeAvailable?: boolean;
  codeEnvironmentHostAvailable?: boolean;
}) {
  const params = new URLSearchParams({
    host_mode: host?.mode || "web",
    local_runtime_available: String(Boolean(host?.localRuntimeAvailable)),
    code_environment_host_available: String(Boolean(host?.codeEnvironmentHostAvailable)),
  });
  return request<CodeEnvironmentStatus>(`/code-environment/environment?${params.toString()}`);
}

export async function getCodeEnvironmentWorkspaceTree(options: {
  maxDepth?: number;
  maxEntries?: number;
  sessionId?: string;
  scope?: Partial<SessionScope>;
} = {}) {
  const params = sessionScopeQuery(options.scope);
  params.set("max_depth", String(options.maxDepth || 10));
  params.set("max_entries", String(options.maxEntries || 10000));
  if (options.sessionId) {
    params.set("session_id", options.sessionId);
  }
  return request<CodeEnvironmentWorkspaceTree>(`/code-environment/workspace-tree?${params.toString()}`);
}

export async function openCodeEnvironmentWorkspaceRoot() {
  return request<{ authority: string; opened: boolean; path: string }>("/code-environment/open-workspace-root", {
    method: "POST",
  });
}

export async function getCodeEnvironmentGitStatus(options: { refresh?: boolean } = {}) {
  const params = new URLSearchParams();
  if (options.refresh) params.set("refresh", "true");
  const query = params.toString();
  return request<CodeEnvironmentGitStatus>(`/code-environment/git-status${query ? `?${query}` : ""}`);
}

export async function getPiSidecarStatus() {
  return request<PiSidecarLifecycleResponse>("/code-environment/sidecar/status");
}

export async function startPiSidecar() {
  return request<PiSidecarLifecycleResponse>("/code-environment/sidecar/start", { method: "POST" });
}

export async function stopPiSidecar() {
  return request<PiSidecarLifecycleResponse>("/code-environment/sidecar/stop", { method: "POST" });
}

export async function runPiSidecarReadOnlyCommand(command: "get_state" | "get_available_models") {
  return request<PiSidecarCommandResponse>("/code-environment/sidecar/read-only-command", {
    method: "POST",
    body: JSON.stringify({ command }),
  });
}
