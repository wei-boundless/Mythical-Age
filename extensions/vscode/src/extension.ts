import * as vscode from "vscode";
import { createChatRun, postEditorContext } from "./connection/apiClient";
import { collectEditorContext } from "./connection/editorContext";
import { startContextHeartbeat } from "./connection/heartbeat";
import { resolveSessionId } from "./connection/sessionBinding";

let output: vscode.OutputChannel | undefined;

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel("Langchain Agent");
  context.subscriptions.push(output);
  context.subscriptions.push(startContextHeartbeat(context, output));
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
  const sessionId = await resolveSessionId(context, editorContext, { createIfMissing: true });
  output?.show(true);
  output?.appendLine(`Sending request to local agent session ${sessionId}.`);
  try {
    await postEditorContext(sessionId, editorContext);
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
