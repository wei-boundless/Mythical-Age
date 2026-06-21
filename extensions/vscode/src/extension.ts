import * as vscode from "vscode";
import { configuredSessionId, createChatRun, postEditorContext } from "./connection/apiClient";
import { collectEditorContext } from "./connection/editorContext";
import { startContextHeartbeat } from "./connection/heartbeat";
import { acquireConnectionLease } from "./connection/lease";

let output: vscode.OutputChannel | undefined;
let heartbeat: vscode.Disposable | undefined;

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel("Langchain Agent");
  context.subscriptions.push(output);
  if (shouldStartBackgroundConnection()) {
    startBackgroundConnection(context);
  }
  context.subscriptions.push(
    vscode.commands.registerCommand("langchainAgent.sendToAgent", () => sendCurrentContext(context)),
    vscode.commands.registerCommand("langchainAgent.showEditorContext", showEditorContext),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("langchainAgent.sessionId") || event.affectsConfiguration("langchainAgent.autoConnect")) {
        syncBackgroundConnection(context);
      }
    })
  );
}

export function deactivate(): void {
  heartbeat?.dispose();
  heartbeat = undefined;
  output?.dispose();
  output = undefined;
}

function syncBackgroundConnection(context: vscode.ExtensionContext): void {
  if (shouldStartBackgroundConnection()) {
    startBackgroundConnection(context);
    return;
  }
  heartbeat?.dispose();
  heartbeat = undefined;
}

function startBackgroundConnection(context: vscode.ExtensionContext): void {
  if (heartbeat || !output) {
    return;
  }
  heartbeat = startContextHeartbeat(context, output);
  context.subscriptions.push(heartbeat);
}

function shouldStartBackgroundConnection(): boolean {
  if (configuredSessionId()) {
    return true;
  }
  return vscode.workspace.getConfiguration("langchainAgent").get<boolean>("autoConnect", false) === true;
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
  try {
    const lease = await acquireConnectionLease(context, editorContext, { createIfMissing: true });
    if (!lease) {
      vscode.window.showWarningMessage("No Langchain Agent session is available for this VS Code window.");
      return;
    }
    const sessionId = lease.sessionId;
    output?.show(true);
    output?.appendLine(`Sending request to local agent session ${sessionId}.`);
    await postEditorContext(sessionId, lease.connectionId, editorContext);
    startBackgroundConnection(context);
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

async function showEditorContext(): Promise<void> {
  const snapshot = collectEditorContext();
  const document = await vscode.workspace.openTextDocument({
    language: "json",
    content: JSON.stringify(snapshot, null, 2)
  });
  await vscode.window.showTextDocument(document, { preview: true });
}
