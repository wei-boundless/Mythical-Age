import * as vscode from "vscode";
import { randomUUID } from "crypto";
import {
  acquireVSCodeConnection,
  heartbeatVSCodeConnection,
  releaseVSCodeConnection
} from "./apiClient";
import { resolveSessionId } from "./sessionBinding";
import type { EditorContextSnapshot, VSCodeConnectionLease } from "./types";

const CONNECTION_STATE_KEY = "langchainAgent.connectionId";

export type ActiveVSCodeConnectionLease = {
  sessionId: string;
  connectionId: string;
  workspaceRoots: string[];
  expiresAtMs: number;
};

export async function acquireConnectionLease(
  context: vscode.ExtensionContext,
  editorContext: EditorContextSnapshot,
  options: { createIfMissing: boolean }
): Promise<ActiveVSCodeConnectionLease | null> {
  const connectionId = await getOrCreateConnectionId(context);
  const sessionId = await resolveSessionId(context, editorContext, options, connectionId);
  if (!sessionId) {
    return null;
  }
  const response = await acquireVSCodeConnection({
    sessionId,
    connectionId,
    workspaceRoots: editorContext.workspace_roots,
    source: "vscode.extension",
    clientName: vscode.env.appName || "VS Code",
  });
  return await activeLeaseFromBackendLease(context, response.lease);
}

export async function renewConnectionLease(
  context: vscode.ExtensionContext,
  lease: ActiveVSCodeConnectionLease,
  editorContext: EditorContextSnapshot
): Promise<ActiveVSCodeConnectionLease> {
  const response = await heartbeatVSCodeConnection(lease.sessionId, lease.connectionId, editorContext.workspace_roots);
  return await activeLeaseFromBackendLease(context, response.lease);
}

export async function releaseConnectionLease(lease: ActiveVSCodeConnectionLease | undefined): Promise<void> {
  if (!lease?.sessionId || !lease.connectionId) {
    return;
  }
  await releaseVSCodeConnection(lease.sessionId, lease.connectionId);
}

async function getOrCreateConnectionId(context: vscode.ExtensionContext): Promise<string> {
  const stored = sanitizeConnectionId(context.workspaceState.get<string>(CONNECTION_STATE_KEY) || "");
  if (stored) {
    return stored;
  }
  const created = `vscode:${randomUUID()}`;
  await context.workspaceState.update(CONNECTION_STATE_KEY, created);
  return created;
}

async function activeLeaseFromBackendLease(
  context: vscode.ExtensionContext,
  lease: VSCodeConnectionLease
): Promise<ActiveVSCodeConnectionLease> {
  const connectionId = sanitizeConnectionId(lease.connection_id);
  if (connectionId) {
    await context.workspaceState.update(CONNECTION_STATE_KEY, connectionId);
  }
  return {
    sessionId: String(lease.session_id || "").trim(),
    connectionId,
    workspaceRoots: lease.workspace_root ? [lease.workspace_root] : [],
    expiresAtMs: Number(lease.expires_at || 0) * 1000,
  };
}

function sanitizeConnectionId(value: string): string {
  return String(value || "").trim().replace(/[^a-zA-Z0-9:_\-.]/g, "-");
}
