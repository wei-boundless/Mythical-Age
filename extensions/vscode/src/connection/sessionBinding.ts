import * as vscode from "vscode";
import { configuredSessionId, createSession, resolveLaunchSession, sessionExists } from "./apiClient";
import type { EditorContextSnapshot, ProjectBindingPayload } from "./types";

const SESSION_STATE_KEY = "langchainAgent.sessionId";
const RESOLVED_SESSION_CACHE_TTL_MS = 120_000;
const EMPTY_SESSION_CACHE_TTL_MS = 30_000;

export type ResolveSessionOptions = {
  createIfMissing: boolean;
};

type ResolvedSessionCache = {
  key: string;
  sessionId: string;
  expiresAt: number;
};

let resolvedSessionCache: ResolvedSessionCache | undefined;
let resolveInFlight: { key: string; promise: Promise<string> } | undefined;

export async function resolveSessionId(
  context: vscode.ExtensionContext,
  editorContext: EditorContextSnapshot,
  options: ResolveSessionOptions,
  connectionId = ""
): Promise<string> {
  const configured = configuredSessionId();
  const cacheKey = sessionResolutionCacheKey(configured, editorContext.workspace_roots, connectionId);
  const now = Date.now();
  if (
    resolvedSessionCache
    && resolvedSessionCache.key === cacheKey
    && resolvedSessionCache.expiresAt > now
    && (resolvedSessionCache.sessionId || !options.createIfMissing)
  ) {
    return resolvedSessionCache.sessionId;
  }
  const inFlightKey = `${cacheKey}|create:${options.createIfMissing ? "1" : "0"}`;
  if (resolveInFlight?.key === inFlightKey) {
    return resolveInFlight.promise;
  }
  const promise = resolveSessionIdUncached(context, editorContext, options, configured, connectionId)
    .then((sessionId) => {
      resolvedSessionCache = {
        key: cacheKey,
        sessionId,
        expiresAt: Date.now() + (sessionId ? RESOLVED_SESSION_CACHE_TTL_MS : EMPTY_SESSION_CACHE_TTL_MS),
      };
      return sessionId;
    })
    .finally(() => {
      if (resolveInFlight?.key === inFlightKey) {
        resolveInFlight = undefined;
      }
    });
  resolveInFlight = { key: inFlightKey, promise };
  return promise;
}

async function resolveSessionIdUncached(
  context: vscode.ExtensionContext,
  editorContext: EditorContextSnapshot,
  options: ResolveSessionOptions,
  configured: string,
  connectionId: string
): Promise<string> {
  if (configured) {
    await context.workspaceState.update(SESSION_STATE_KEY, configured);
    return configured;
  }
  const launchSession = await resolveLaunchSession(editorContext.workspace_roots, connectionId);
  if (launchSession && await sessionExists(launchSession)) {
    await context.workspaceState.update(SESSION_STATE_KEY, launchSession);
    return launchSession;
  }
  const stored = context.workspaceState.get<string>(SESSION_STATE_KEY) || "";
  if (stored && await sessionExists(stored)) {
    return stored;
  }
  if (stored) {
    await context.workspaceState.update(SESSION_STATE_KEY, undefined);
  }
  if (!options.createIfMissing) {
    return "";
  }
  const projectBinding = await projectBindingFromEditorContext(editorContext);
  const created = await createSession("VS Code Agent Session", projectBinding);
  await context.workspaceState.update(SESSION_STATE_KEY, created.id);
  return created.id;
}

function sessionResolutionCacheKey(configuredSessionId: string, workspaceRoots: string[], connectionId: string): string {
  const roots = Array.from(new Set(workspaceRoots.map((item) => item.trim()).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right));
  return JSON.stringify({
    configured_session_id: configuredSessionId,
    connection_id: connectionId,
    workspace_roots: roots,
  });
}

async function projectBindingFromEditorContext(editorContext: EditorContextSnapshot): Promise<ProjectBindingPayload | undefined> {
  const roots = Array.from(new Set(editorContext.workspace_roots.map((item) => item.trim()).filter(Boolean)));
  if (roots.length === 0) {
    return undefined;
  }
  if (roots.length === 1) {
    return { workspace_root: roots[0], source: "vscode" };
  }
  const selected = await vscode.window.showQuickPick(roots, {
    title: "Bind Langchain Agent Session",
    placeHolder: "Select the project root for this local agent session.",
    ignoreFocusOut: true
  });
  if (!selected) {
    throw new Error("A project root must be selected before creating a VS Code agent session.");
  }
  return { workspace_root: selected, source: "vscode" };
}
