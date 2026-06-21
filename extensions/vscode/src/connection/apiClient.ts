import * as vscode from "vscode";
import type {
  ChatRunResponse,
  EditorContextSnapshot,
  ProjectBindingPayload,
  SessionResponse,
  VSCodeCommandPollResponse,
  VSCodeCommandResultPayload,
  VSCodeConnectionAcquireResponse
} from "./types";

export type ChatRunPayload = {
  message: string;
  session_id: string;
  stream: true;
  editor_context: EditorContextSnapshot;
};

export class VSCodeConnectionLeaseDeniedError extends Error {
  readonly code: string;
  readonly retryAfterMs: number;

  constructor(message: string, code: string, retryAfterMs: number) {
    super(message);
    this.name = "VSCodeConnectionLeaseDeniedError";
    this.code = code;
    this.retryAfterMs = retryAfterMs;
  }
}

export async function createChatRun(payload: ChatRunPayload): Promise<ChatRunResponse> {
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/chat/runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`Local agent request failed: ${response.status} ${text}`.trim());
  }
  return (await response.json()) as ChatRunResponse;
}

export async function postEditorContext(sessionId: string, connectionId: string, snapshot: EditorContextSnapshot): Promise<void> {
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/vscode/sessions/${encodeURIComponent(sessionId)}/context`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      ...snapshot,
      connection_id: connectionId
    })
  });
  if (!response.ok) {
    throw await responseError(response, "VS Code context update failed");
  }
}

export async function pollNextCommand(sessionId: string, connectionId: string): Promise<VSCodeCommandPollResponse> {
  const apiBase = normalizedApiBase();
  const params = new URLSearchParams({ connection_id: connectionId });
  const response = await fetch(`${apiBase}/vscode/sessions/${encodeURIComponent(sessionId)}/commands/next?${params.toString()}`, {
    method: "GET"
  });
  if (!response.ok) {
    throw await responseError(response, "VS Code command poll failed");
  }
  return (await response.json()) as VSCodeCommandPollResponse;
}

export async function postCommandResult(sessionId: string, connectionId: string, commandId: string, payload: VSCodeCommandResultPayload): Promise<void> {
  const apiBase = normalizedApiBase();
  const params = new URLSearchParams({ connection_id: connectionId });
  const response = await fetch(`${apiBase}/vscode/sessions/${encodeURIComponent(sessionId)}/commands/${encodeURIComponent(commandId)}/result?${params.toString()}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw await responseError(response, "VS Code command result update failed");
  }
}

export async function acquireVSCodeConnection(payload: {
  sessionId: string;
  connectionId: string;
  workspaceRoots: string[];
  source?: string;
  clientName?: string;
}): Promise<VSCodeConnectionAcquireResponse> {
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/vscode/sessions/${encodeURIComponent(payload.sessionId)}/connections/acquire`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      connection_id: payload.connectionId,
      workspace_roots: payload.workspaceRoots,
      source: payload.source || "vscode.extension",
      client_name: payload.clientName || ""
    })
  });
  if (!response.ok) {
    throw await responseError(response, "VS Code connection acquire failed");
  }
  return (await response.json()) as VSCodeConnectionAcquireResponse;
}

export async function heartbeatVSCodeConnection(sessionId: string, connectionId: string, workspaceRoots: string[]): Promise<VSCodeConnectionAcquireResponse> {
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/vscode/sessions/${encodeURIComponent(sessionId)}/connections/${encodeURIComponent(connectionId)}/heartbeat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ workspace_roots: workspaceRoots })
  });
  if (!response.ok) {
    throw await responseError(response, "VS Code connection heartbeat failed");
  }
  return (await response.json()) as VSCodeConnectionAcquireResponse;
}

export async function releaseVSCodeConnection(sessionId: string, connectionId: string): Promise<void> {
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/vscode/sessions/${encodeURIComponent(sessionId)}/connections/${encodeURIComponent(connectionId)}`, {
    method: "DELETE"
  });
  if (!response.ok) {
    throw await responseError(response, "VS Code connection release failed");
  }
}

export function configuredSessionId(): string {
  const configured = vscode.workspace.getConfiguration("langchainAgent").get<string>("sessionId");
  const fromConfig = sanitizeSessionId(configured || "");
  if (fromConfig) {
    return fromConfig;
  }
  return sanitizeSessionId(process.env.LANGCHAIN_AGENT_SESSION_ID || "");
}

export async function createSession(title: string, projectBinding?: ProjectBindingPayload): Promise<SessionResponse> {
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      title,
      scope: {
        workspace_view: "chat"
      },
      ...(projectBinding ? { project_binding: projectBinding } : {})
    })
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`Session create failed: ${response.status} ${text}`.trim());
  }
  return (await response.json()) as SessionResponse;
}

export async function sessionExists(sessionId: string): Promise<boolean> {
  if (!sessionId) {
    return false;
  }
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/sessions/${encodeURIComponent(sessionId)}`, {
    method: "GET"
  });
  return response.ok;
}

export async function resolveLaunchSession(workspaceRoots: string[], connectionId = ""): Promise<string> {
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/vscode/sessions/resolve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ workspace_roots: workspaceRoots, connection_id: connectionId })
  });
  if (!response.ok) {
    throw await responseError(response, "VS Code session resolve failed");
  }
  const payload = (await response.json()) as { session_id?: string };
  return sanitizeSessionId(payload.session_id || "");
}

function normalizedApiBase(): string {
  const configured = vscode.workspace.getConfiguration("langchainAgent").get<string>("apiBase");
  const value = (configured || "http://127.0.0.1:8003/api").trim();
  return value.replace(/\/+$/, "");
}

function sanitizeSessionId(value: string): string {
  return value.trim().replace(/[^a-zA-Z0-9:_-]/g, "-");
}

async function responseError(response: Response, fallback: string): Promise<Error> {
  const text = await response.text().catch(() => "");
  const detail = parseErrorDetail(text);
  const code = String(detail.code || "").trim();
  const message = String(detail.message || text || fallback).trim();
  const retryAfterMs = positiveNumber(detail.retry_after_ms);
  if (response.status === 409 || response.status === 429) {
    if (code.includes("lease") || code.includes("connection") || code.includes("duplicate")) {
      return new VSCodeConnectionLeaseDeniedError(message, code || "lease_denied", retryAfterMs || 15000);
    }
  }
  return new Error(`${fallback}: ${response.status} ${text}`.trim());
}

function parseErrorDetail(text: string): Record<string, unknown> {
  if (!text) {
    return {};
  }
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    const detail = parsed.detail && typeof parsed.detail === "object" && !Array.isArray(parsed.detail)
      ? parsed.detail
      : parsed;
    return detail && typeof detail === "object" && !Array.isArray(detail) ? detail as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function positiveNumber(value: unknown): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}
