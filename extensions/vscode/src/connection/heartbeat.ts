import * as vscode from "vscode";
import { pollNextCommand, postCommandResult, postEditorContext } from "./apiClient";
import { collectEditorContext } from "./editorContext";
import { resolveSessionId } from "./sessionBinding";
import type { VSCodeCommand } from "./types";

const HEARTBEAT_INTERVAL_MS = 15000;
const COMMAND_POLL_INTERVAL_MS = 1500;
const DEBOUNCE_MS = 800;

export function startContextHeartbeat(context: vscode.ExtensionContext, output: vscode.OutputChannel): vscode.Disposable {
  let disposed = false;
  let debounceTimer: NodeJS.Timeout | undefined;
  const interval = setInterval(() => schedulePublish(), HEARTBEAT_INTERVAL_MS);
  const commandInterval = setInterval(() => {
    void pollCommands();
  }, COMMAND_POLL_INTERVAL_MS);
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

  async function pollCommands(): Promise<void> {
    if (disposed) {
      return;
    }
    try {
      const snapshot = collectEditorContext();
      const sessionId = await resolveSessionId(context, snapshot, { createIfMissing: false });
      if (!sessionId) {
        return;
      }
      const payload = await pollNextCommand(sessionId);
      const commands = payload.command ? [payload.command] : (payload.commands || []);
      for (const command of commands) {
        await executeCommand(sessionId, command, output);
      }
    } catch (error) {
      const text = error instanceof Error ? error.message : String(error);
      output.appendLine(text);
    }
  }

  schedulePublish();
  void pollCommands();
  return new vscode.Disposable(() => {
    disposed = true;
    clearInterval(interval);
    clearInterval(commandInterval);
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    for (const subscription of subscriptions) {
      subscription.dispose();
    }
  });
}

async function executeCommand(sessionId: string, command: VSCodeCommand, output: vscode.OutputChannel): Promise<void> {
  const commandId = String(command.command_id || "").trim();
  try {
    if (command.type === "open_diff") {
      await executeOpenDiff(command);
      await reportCommandResult(sessionId, commandId, {
        status: "ok",
        message: "Diff opened in VS Code.",
        applied_at: new Date().toISOString(),
        metadata: { type: command.type, record_id: command.record_id || "" }
      }, output);
      return;
    }
    if (command.type === "open_file") {
      const document = await executeOpenFile(command);
      await reportCommandResult(sessionId, commandId, {
        status: "ok",
        message: "File opened in VS Code.",
        dirty: document.isDirty,
        applied_at: new Date().toISOString(),
        metadata: {
          type: command.type,
          language_id: document.languageId,
          logical_path: command.logical_path || ""
        }
      }, output);
      return;
    }
    const message = `Unsupported VS Code command: ${command.type || "(missing)"}`;
    output.appendLine(message);
    await reportCommandResult(sessionId, commandId, {
      status: "unsupported",
      message,
      applied_at: new Date().toISOString(),
      metadata: { type: command.type || "" }
    }, output);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(message);
    await reportCommandResult(sessionId, commandId, {
      status: "error",
      message,
      applied_at: new Date().toISOString(),
      metadata: { type: command.type || "" }
    }, output);
  }
}

async function executeOpenDiff(command: VSCodeCommand): Promise<void> {
  const leftUri = parseUri(command.left_uri);
  const rightUri = parseUri(command.right_uri);
  if (!leftUri || !rightUri) {
    throw new Error(`Invalid diff command URIs: ${command.command_id || "(unknown)"}`);
  }
  const title = String(command.title || "File change").trim() || "File change";
  await vscode.commands.executeCommand("vscode.diff", leftUri, rightUri, title, { preview: false });
}

async function executeOpenFile(command: VSCodeCommand): Promise<vscode.TextDocument> {
  const uri = parseUri(command.uri);
  if (!uri) {
    throw new Error(`Invalid open_file URI: ${command.command_id || "(unknown)"}`);
  }
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(document, { preview: false });
  return document;
}

async function reportCommandResult(
  sessionId: string,
  commandId: string,
  payload: Parameters<typeof postCommandResult>[2],
  output: vscode.OutputChannel
): Promise<void> {
  if (!commandId) {
    return;
  }
  try {
    await postCommandResult(sessionId, commandId, payload);
  } catch (error) {
    output.appendLine(error instanceof Error ? error.message : String(error));
  }
}

function parseUri(value: unknown): vscode.Uri | null {
  const text = String(value || "").trim();
  if (!text) {
    return null;
  }
  try {
    return vscode.Uri.parse(text, true);
  } catch {
    return null;
  }
}
