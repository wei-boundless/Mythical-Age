import * as vscode from "vscode";
import { createChatRun, configuredSessionId, createSession, sessionExists, type ProjectBindingPayload } from "./apiClient";
import { collectEditorContext, type EditorContextSnapshot } from "./editorContext";

let output: vscode.OutputChannel | undefined;
const SESSION_STATE_KEY = "langchainAgent.sessionId";

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel("Langchain Agent");
  context.subscriptions.push(output);
  context.subscriptions.push(
    vscode.commands.registerCommand("langchainAgent.sendToAgent", () => sendCurrentContext(context)),
    vscode.commands.registerCommand("langchainAgent.showEditorContext", showEditorContext)
  );
}

export function deactivate(): void {
  output?.dispose();
  output = undefined;
}

async function sendCurrentContext(context: vscode.ExtensionContext): Promise<void> {
  const message = await vscode.window.showInputBox({
    title: "Send to Langchain Agent",
    prompt: "Enter the instruction to send with the current VS Code context.",
    ignoreFocusOut: true
  });
  if (!message?.trim()) {
    return;
  }
  const editorContext = collectEditorContext();
  const sessionId = await resolveSessionId(context, editorContext);
  output?.show(true);
  output?.appendLine(`Sending request to local agent session ${sessionId}.`);
  try {
    const run = await createChatRun({
      message: message.trim(),
      session_id: sessionId,
      stream: true,
      editor_context: editorContext
    });
    output?.appendLine(`Created chat run: ${run.stream_run_id || "(unknown)"}`);
    if (run.stream_url) {
      output?.appendLine(`Stream URL: ${run.stream_url}`);
    }
    vscode.window.showInformationMessage("Langchain Agent request created.");
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error);
    output?.appendLine(text);
    vscode.window.showErrorMessage(text);
  }
}

async function resolveSessionId(context: vscode.ExtensionContext, editorContext: EditorContextSnapshot): Promise<string> {
  const configured = configuredSessionId();
  if (configured) {
    return configured;
  }
  const stored = context.workspaceState.get<string>(SESSION_STATE_KEY) || "";
  if (stored && await sessionExists(stored)) {
    return stored;
  }
  const projectBinding = await projectBindingFromEditorContext(editorContext);
  const created = await createSession("VS Code Agent Session", projectBinding);
  await context.workspaceState.update(SESSION_STATE_KEY, created.id);
  output?.appendLine(`Created local agent session ${created.id}.`);
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

async function showEditorContext(): Promise<void> {
  const snapshot = collectEditorContext();
  const document = await vscode.workspace.openTextDocument({
    language: "json",
    content: JSON.stringify(snapshot, null, 2)
  });
  await vscode.window.showTextDocument(document, { preview: true });
}
