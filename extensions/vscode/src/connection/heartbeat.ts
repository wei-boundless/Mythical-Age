import * as vscode from "vscode";
import { pollNextCommand, postCommandResult, postEditorContext, VSCodeConnectionLeaseDeniedError } from "./apiClient";
import { collectEditorContext } from "./editorContext";
import { acquireConnectionLease, releaseConnectionLease, renewConnectionLease, type ActiveVSCodeConnectionLease } from "./lease";
import type { VSCodeCommand } from "./types";

const HEARTBEAT_INTERVAL_MS = 15000;
const COMMAND_POLL_BASE_INTERVAL_MS = 2500;
const COMMAND_POLL_AFTER_COMMAND_INTERVAL_MS = 250;
const COMMAND_POLL_NO_SESSION_INTERVAL_MS = 15000;
const COMMAND_POLL_IDLE_MAX_INTERVAL_MS = 15000;
const COMMAND_POLL_ERROR_MAX_INTERVAL_MS = 30000;
const DEBOUNCE_MS = 800;
const MIN_DUPLICATE_CONTEXT_PUBLISH_INTERVAL_MS = 10000;

export function startContextHeartbeat(context: vscode.ExtensionContext, output: vscode.OutputChannel): vscode.Disposable {
  let disposed = false;
  let debounceTimer: NodeJS.Timeout | undefined;
  let publishInFlight = false;
  let publishPending = false;
  let pollInFlight = false;
  let commandPollTimer: NodeJS.Timeout | undefined;
  let leaseInFlight: Promise<ActiveVSCodeConnectionLease | null> | undefined;
  let activeLease: ActiveVSCodeConnectionLease | undefined;
  let leaseRetryAfterUntil = 0;
  let commandPollIdleDelayMs = COMMAND_POLL_BASE_INTERVAL_MS;
  let lastContextFingerprint = "";
  let lastContextPublishedAt = 0;
  const interval = setInterval(() => {
    schedulePublish();
    void heartbeatLease();
  }, HEARTBEAT_INTERVAL_MS);
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
    if (publishInFlight) {
      publishPending = true;
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
    if (publishInFlight) {
      publishPending = true;
      return;
    }
    publishInFlight = true;
    try {
      const snapshot = collectEditorContext();
      const fingerprint = editorContextFingerprint(snapshot);
      const now = Date.now();
      if (
        fingerprint === lastContextFingerprint
        && now - lastContextPublishedAt < MIN_DUPLICATE_CONTEXT_PUBLISH_INTERVAL_MS
      ) {
        return;
      }
      const lease = await ensureLease(snapshot);
      if (!lease) {
        return;
      }
      await postEditorContext(lease.sessionId, lease.connectionId, snapshot);
      lastContextFingerprint = fingerprint;
      lastContextPublishedAt = Date.now();
    } catch (error) {
      const text = error instanceof Error ? error.message : String(error);
      output.appendLine(text);
    } finally {
      publishInFlight = false;
      if (publishPending && !disposed) {
        publishPending = false;
        schedulePublish();
      }
    }
  }

  async function pollCommands(): Promise<void> {
    if (disposed) {
      return;
    }
    if (pollInFlight) {
      scheduleCommandPoll(COMMAND_POLL_BASE_INTERVAL_MS);
      return;
    }
    let nextDelayMs = COMMAND_POLL_BASE_INTERVAL_MS;
    pollInFlight = true;
    try {
      const snapshot = collectEditorContext();
      const lease = await ensureLease(snapshot);
      if (!lease) {
        commandPollIdleDelayMs = COMMAND_POLL_NO_SESSION_INTERVAL_MS;
        nextDelayMs = commandPollIdleDelayMs;
        return;
      }
      const payload = await pollNextCommand(lease.sessionId, lease.connectionId);
      const commands = payload.command ? [payload.command] : (payload.commands || []);
      for (const command of commands) {
        await executeCommand(lease, command, output);
      }
      if (commands.length > 0) {
        commandPollIdleDelayMs = COMMAND_POLL_BASE_INTERVAL_MS;
        nextDelayMs = COMMAND_POLL_AFTER_COMMAND_INTERVAL_MS;
      } else {
        const retryAfterMs = positiveNumber(payload.retry_after_ms);
        commandPollIdleDelayMs = Math.min(
          COMMAND_POLL_IDLE_MAX_INTERVAL_MS,
          Math.max(COMMAND_POLL_BASE_INTERVAL_MS, retryAfterMs || commandPollIdleDelayMs * 2),
        );
        nextDelayMs = commandPollIdleDelayMs;
      }
    } catch (error) {
      const text = error instanceof Error ? error.message : String(error);
      output.appendLine(text);
      commandPollIdleDelayMs = Math.min(
        COMMAND_POLL_ERROR_MAX_INTERVAL_MS,
        Math.max(COMMAND_POLL_BASE_INTERVAL_MS, commandPollIdleDelayMs * 2),
      );
      nextDelayMs = commandPollIdleDelayMs;
    } finally {
      pollInFlight = false;
      scheduleCommandPoll(nextDelayMs);
    }
  }

  function scheduleCommandPoll(delayMs: number): void {
    if (disposed) {
      return;
    }
    if (commandPollTimer) {
      clearTimeout(commandPollTimer);
    }
    commandPollTimer = setTimeout(() => {
      commandPollTimer = undefined;
      void pollCommands();
    }, Math.max(0, delayMs));
  }

  async function ensureLease(snapshot: ReturnType<typeof collectEditorContext>): Promise<ActiveVSCodeConnectionLease | null> {
    if (disposed) {
      return null;
    }
    const now = Date.now();
    if (activeLease && activeLease.expiresAtMs - now > 5000) {
      return activeLease;
    }
    if (now < leaseRetryAfterUntil) {
      return null;
    }
    if (leaseInFlight) {
      return leaseInFlight;
    }
    leaseInFlight = acquireConnectionLease(context, snapshot, { createIfMissing: false })
      .then((lease) => {
        activeLease = lease || undefined;
        return lease;
      })
      .catch((error) => {
        activeLease = undefined;
        handleLeaseError(error, output);
        return null;
      })
      .finally(() => {
        leaseInFlight = undefined;
      });
    return leaseInFlight;
  }

  async function heartbeatLease(): Promise<void> {
    if (disposed) {
      return;
    }
    const snapshot = collectEditorContext();
    const now = Date.now();
    if (now < leaseRetryAfterUntil) {
      return;
    }
    try {
      if (!activeLease) {
        await ensureLease(snapshot);
        return;
      }
      activeLease = await renewConnectionLease(context, activeLease, snapshot);
    } catch (error) {
      activeLease = undefined;
      handleLeaseError(error, output);
    }
  }

  function handleLeaseError(error: unknown, output: vscode.OutputChannel): void {
    if (error instanceof VSCodeConnectionLeaseDeniedError) {
      leaseRetryAfterUntil = Date.now() + Math.max(COMMAND_POLL_NO_SESSION_INTERVAL_MS, error.retryAfterMs);
      output.appendLine(`VS Code connection lease denied: ${error.code}; retrying after ${Math.round((leaseRetryAfterUntil - Date.now()) / 1000)}s.`);
      return;
    }
    const text = error instanceof Error ? error.message : String(error);
    output.appendLine(text);
  }

  schedulePublish();
  scheduleCommandPoll(0);
  return new vscode.Disposable(() => {
    disposed = true;
    clearInterval(interval);
    if (commandPollTimer) {
      clearTimeout(commandPollTimer);
    }
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    void releaseConnectionLease(activeLease).catch(() => undefined);
    for (const subscription of subscriptions) {
      subscription.dispose();
    }
  });
}

function positiveNumber(value: unknown): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function editorContextFingerprint(snapshot: ReturnType<typeof collectEditorContext>): string {
  return JSON.stringify({
    workspace_roots: snapshot.workspace_roots,
    active_file: snapshot.active_file,
    visible_files: snapshot.visible_files,
    open_tabs: snapshot.open_tabs,
    diagnostics: snapshot.diagnostics,
    limits: snapshot.limits,
  });
}

async function executeCommand(lease: ActiveVSCodeConnectionLease, command: VSCodeCommand, output: vscode.OutputChannel): Promise<void> {
  const commandId = String(command.command_id || "").trim();
  try {
    if (command.type === "open_diff") {
      await executeOpenDiff(command);
      await reportCommandResult(lease, commandId, {
        status: "ok",
        message: "Diff opened in VS Code.",
        applied_at: new Date().toISOString(),
        metadata: { type: command.type, record_id: command.record_id || "" }
      }, output);
      return;
    }
    if (command.type === "open_file") {
      const document = await executeOpenFile(command);
      await reportCommandResult(lease, commandId, {
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
    await reportCommandResult(lease, commandId, {
      status: "unsupported",
      message,
      applied_at: new Date().toISOString(),
      metadata: { type: command.type || "" }
    }, output);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(message);
    await reportCommandResult(lease, commandId, {
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
  lease: ActiveVSCodeConnectionLease,
  commandId: string,
  payload: Parameters<typeof postCommandResult>[3],
  output: vscode.OutputChannel
): Promise<void> {
  if (!commandId) {
    return;
  }
  try {
    await postCommandResult(lease.sessionId, lease.connectionId, commandId, payload);
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
