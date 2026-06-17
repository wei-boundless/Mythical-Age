import { request, withSessionScopeQuery } from "./shared";
import type {
  ArtifactRepositoryOverview,
  DurableMemoryNoteDetail,
  FormalMemoryOverview,
  MemoryGovernanceResponse,
  MemoryNamespaceScope,
  MemoryOverview,
  MemoryRecallPreview,
  MemorySessionFilesResponse,
  ProjectInstructionManagement,
  SessionScope,
} from "./types";

export async function getMemoryOverview(sessionId?: string, query = "", scope?: MemoryNamespaceScope) {
  const params = new URLSearchParams();
  if (sessionId) {
    params.set("session_id", sessionId);
  }
  if (query.trim()) {
    params.set("query", query.trim());
  }
  if (scope?.namespace_id?.trim()) {
    params.set("namespace_id", scope.namespace_id.trim());
  }
  if (scope?.task_environment_id?.trim()) {
    params.set("task_environment_id", scope.task_environment_id.trim());
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<MemoryOverview>(`/memory/overview${suffix}`);
}

export async function getProjectInstructionManagement() {
  return request<ProjectInstructionManagement>("/memory/project-instructions");
}

export async function saveProjectInstructionSource(path: string, content: string) {
  return request<ProjectInstructionManagement>("/memory/project-instructions", {
    method: "PUT",
    body: JSON.stringify({ path, content })
  });
}

export async function getFormalMemoryOverview(payload?: {
  task_run_id?: string;
  repository_id?: string;
  collection_id?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(payload ?? {})) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) params.set(key, text);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<FormalMemoryOverview>(`/memory/formal/overview${suffix}`);
}

export async function getArtifactRepositoryOverview(payload?: {
  task_run_id?: string;
  repository_id?: string;
  collection_id?: string;
  status?: string;
  graph_run_id?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(payload ?? {})) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) params.set(key, text);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<ArtifactRepositoryOverview>(`/memory/artifacts/overview${suffix}`);
}

export async function getSessionMemoryFiles(sessionId: string, scope?: Partial<SessionScope>) {
  return request<MemorySessionFilesResponse>(
    withSessionScopeQuery(`/memory/session/${encodeURIComponent(sessionId)}/files`, scope)
  );
}

export async function recallMemoryPreview(payload: { query: string; session_id?: string; limit?: number } & MemoryNamespaceScope) {
  return request<MemoryRecallPreview>("/memory/recall-preview", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createDurableMemory(payload: {
  title: string;
  canonical_statement: string;
  summary?: string;
  memory_type?: string;
  memory_class?: string;
  retrieval_hints?: string[];
  confidence?: string;
  source_kind?: string;
  source_message_excerpt?: string;
} & MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>("/memory/durable", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function disableDurableMemory(filename: string, reason = "", scope?: MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/disable`, {
    method: "POST",
    body: JSON.stringify({ reason, ...scope })
  });
}

export async function activateDurableMemory(filename: string, reason = "", scope?: MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/activate`, {
    method: "POST",
    body: JSON.stringify({ reason, ...scope })
  });
}

export async function archiveDurableMemory(filename: string, reason = "", scope?: MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/archive`, {
    method: "POST",
    body: JSON.stringify({ reason, ...scope })
  });
}

export async function deleteDurableMemory(filename: string, reason = "", scope?: MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}`, {
    method: "DELETE",
    body: JSON.stringify({ reason, ...scope })
  });
}

export async function getDurableMemoryNote(filename: string, scope?: MemoryNamespaceScope) {
  const params = new URLSearchParams();
  if (scope?.namespace_id?.trim()) params.set("namespace_id", scope.namespace_id.trim());
  if (scope?.task_environment_id?.trim()) params.set("task_environment_id", scope.task_environment_id.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<DurableMemoryNoteDetail>(`/memory/durable/${encodeURIComponent(filename)}${suffix}`);
}

export async function mergeDurableMemories(payload: {
  filenames: string[];
  title: string;
  canonical_statement: string;
  summary?: string;
  reason?: string;
} & MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>("/memory/durable/merge", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
