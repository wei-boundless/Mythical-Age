import * as vscode from "vscode";
import type { EditorContextSnapshot } from "./editorContext";

export type ChatRunResponse = {
  stream_run_id?: string;
  stream_url?: string;
  status?: string;
};

export type ChatRunPayload = {
  message: string;
  session_id: string;
  stream: true;
  editor_context: EditorContextSnapshot;
};

export type SessionResponse = {
  id: string;
  title?: string;
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

export function configuredSessionId(): string {
  const value = vscode.workspace.getConfiguration("langchainAgent").get<string>("sessionId");
  return sanitizeSessionId(value || "");
}

export async function createSession(title: string): Promise<SessionResponse> {
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
      }
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

function normalizedApiBase(): string {
  const configured = vscode.workspace.getConfiguration("langchainAgent").get<string>("apiBase");
  const value = (configured || "http://127.0.0.1:8003/api").trim();
  return value.replace(/\/+$/, "");
}

function sanitizeSessionId(value: string): string {
  const cleaned = value.trim().replace(/[^a-zA-Z0-9:_-]/g, "-");
  return cleaned;
}
