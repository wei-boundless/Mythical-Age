import { request, sessionScopeQuery } from "./shared";
import type {
  FileChangeDiffPayload,
  FileChangeRecord,
  ManagedFileReadResponse,
  ManagedFileTarget,
  ManagedFileWriteResponse,
  SessionScope,
  WorkspaceContext,
} from "./types";

export async function listSkills() {
  return request<Array<{ name: string; title: string; description: string; path: string }>>(
    "/skills"
  );
}

export async function getWorkspaceContext() {
  return request<WorkspaceContext>("/workspace/context");
}

export async function loadFile(path: string) {
  return request<{ path: string; content: string }>(`/files?path=${encodeURIComponent(path)}`);
}

export async function loadFileForSession(path: string, sessionId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  params.set("path", path);
  params.set("session_id", sessionId);
  return request<{ path: string; content: string }>(`/files?${params.toString()}`);
}

export async function saveFile(path: string, content: string) {
  return request<{ ok: boolean; path: string }>("/files", {
    method: "POST",
    body: JSON.stringify({ path, content })
  });
}

export async function saveFileForSession(path: string, content: string, sessionId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  params.set("session_id", sessionId);
  return request<{ ok: boolean; path: string }>(`/files?${params.toString()}`, {
    method: "POST",
    body: JSON.stringify({ path, content })
  });
}

export async function readManagedFile(target: ManagedFileTarget, sessionId = "") {
  return request<ManagedFileReadResponse>("/file-management/files/read", {
    method: "POST",
    body: JSON.stringify({ target, session_id: sessionId }),
  });
}

export async function selectManagedFileForOpen(sessionId = "") {
  return request<ManagedFileReadResponse & { selected_path?: string; display_path?: string }>("/file-management/files/select-open", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export async function writeManagedFile(payload: {
  target: ManagedFileTarget;
  content: string;
  expectedSha256?: string;
  source?: string;
  reason?: string;
  force?: boolean;
  sessionId?: string;
}) {
  return request<ManagedFileWriteResponse>("/file-management/files/write", {
    method: "POST",
    body: JSON.stringify({
      target: payload.target,
      content: payload.content,
      expected_sha256: payload.expectedSha256 || "",
      source: payload.source || "agent_ui",
      reason: payload.reason || "user_save",
      force: Boolean(payload.force),
      session_id: payload.sessionId || "",
    }),
  });
}

export async function openManagedFileInVSCode(target: ManagedFileTarget, sessionId: string) {
  return request<{
    ok: boolean;
    command?: Record<string, unknown>;
    connection_status?: { connected?: boolean; stale?: boolean };
    authority: string;
  }>("/file-management/files/open-vscode", {
    method: "POST",
    body: JSON.stringify({ target, session_id: sessionId }),
  });
}

export async function listFileChanges(params: { sessionId?: string; taskRunId?: string; status?: string; limit?: number } = {}) {
  const query = new URLSearchParams();
  if (params.sessionId) query.set("session_id", params.sessionId);
  if (params.taskRunId) query.set("task_run_id", params.taskRunId);
  if (params.status) query.set("status", params.status);
  if (params.limit) query.set("limit", String(params.limit));
  return request<{
    records: FileChangeRecord[];
    summary: { count: number };
    authority: string;
  }>(`/file-changes${query.toString() ? `?${query.toString()}` : ""}`);
}

export async function openFileChangeDiffInVSCode(sessionId: string, recordId: string) {
  return request<{
    ok: boolean;
    command?: {
      command_id?: string;
      type?: string;
      left_uri?: string;
      right_uri?: string;
      title?: string;
      record_id?: string;
    };
    connection_status?: { connected?: boolean; stale?: boolean };
    authority: string;
  }>(`/vscode/sessions/${encodeURIComponent(sessionId)}/file-change-diffs/open`, {
    method: "POST",
    body: JSON.stringify({ record_id: recordId }),
  });
}

export async function getFileChangeDiff(recordId: string) {
  return request<{
    diff: FileChangeDiffPayload;
    authority: string;
  }>(`/file-changes/${encodeURIComponent(recordId)}/diff`);
}

export async function rollbackFileChange(recordId: string, options: { force?: boolean } = {}) {
  return request<{
    record: FileChangeRecord;
    rolled_back: boolean;
    authority: string;
  }>(`/file-changes/${encodeURIComponent(recordId)}/rollback`, {
    method: "POST",
    body: JSON.stringify({ force: Boolean(options.force) }),
  });
}
