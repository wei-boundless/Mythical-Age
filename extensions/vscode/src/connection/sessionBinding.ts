import * as vscode from "vscode";
import { configuredSessionId, createSession, resolveLaunchSession, sessionExists } from "./apiClient";
import type { EditorContextSnapshot, ProjectBindingPayload } from "./types";

const SESSION_STATE_KEY = "langchainAgent.sessionId";

export type ResolveSessionOptions = {
  createIfMissing: boolean;
};

export async function resolveSessionId(
  context: vscode.ExtensionContext,
  editorContext: EditorContextSnapshot,
  options: ResolveSessionOptions
): Promise<string> {
  const configured = configuredSessionId();
  if (configured) {
    await context.workspaceState.update(SESSION_STATE_KEY, configured);
    return configured;
  }
  const launchSession = await resolveLaunchSession(editorContext.workspace_roots);
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
