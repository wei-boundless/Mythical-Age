import * as vscode from "vscode";
import { postEditorContext } from "./apiClient";
import { collectEditorContext } from "./editorContext";
import { resolveSessionId } from "./sessionBinding";

const HEARTBEAT_INTERVAL_MS = 15000;
const DEBOUNCE_MS = 800;

export function startContextHeartbeat(context: vscode.ExtensionContext, output: vscode.OutputChannel): vscode.Disposable {
  let disposed = false;
  let debounceTimer: NodeJS.Timeout | undefined;
  const interval = setInterval(() => schedulePublish(), HEARTBEAT_INTERVAL_MS);
  const subscriptions: vscode.Disposable[] = [
    vscode.window.onDidChangeActiveTextEditor(() => schedulePublish()),
    vscode.window.onDidChangeVisibleTextEditors(() => schedulePublish()),
    vscode.window.onDidChangeTextEditorSelection(() => schedulePublish()),
    vscode.workspace.onDidChangeTextDocument(() => schedulePublish()),
    vscode.languages.onDidChangeDiagnostics(() => schedulePublish())
  ];

  function schedulePublish(): void {
    if (disposed) {
      return;
    }
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(() => {
      void publishContext();
    }, DEBOUNCE_MS);
  }

  async function publishContext(): Promise<void> {
    if (disposed) {
      return;
    }
    try {
      const snapshot = collectEditorContext();
      const sessionId = await resolveSessionId(context, snapshot, { createIfMissing: false });
      if (!sessionId) {
        return;
      }
      await postEditorContext(sessionId, snapshot);
    } catch (error) {
      const text = error instanceof Error ? error.message : String(error);
      output.appendLine(text);
    }
  }

  schedulePublish();
  return new vscode.Disposable(() => {
    disposed = true;
    clearInterval(interval);
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    for (const subscription of subscriptions) {
      subscription.dispose();
    }
  });
}
