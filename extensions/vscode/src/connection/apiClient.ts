import * as vscode from "vscode";
import type { ChatRunResponse, EditorContextSnapshot, ProjectBindingPayload, SessionResponse } from "./types";

export type ChatRunPayload = {
  message: string;
  session_id: string;
  stream: true;
  editor_context: EditorContextSnapshot;
};

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

export async function postEditorContext(sessionId: string, snapshot: EditorContextSnapshot): Promise<void> {
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/vscode/sessions/${encodeURIComponent(sessionId)}/context`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(snapshot)
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`VS Code context update failed: ${response.status} ${text}`.trim());
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
  const response = await fetch(`${apiBase}/sessions/${encodeURIComponent(sessionId)}/history`, {
    method: "GET"
  });
  return response.ok;
}

export async function resolveLaunchSession(workspaceRoots: string[]): Promise<string> {
  const apiBase = normalizedApiBase();
  const response = await fetch(`${apiBase}/vscode/sessions/resolve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ workspace_roots: workspaceRoots })
  });
  if (!response.ok) {
    return "";
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
