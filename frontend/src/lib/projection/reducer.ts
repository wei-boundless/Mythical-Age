import type {
  MessagePublicProjection,
  ProjectionLedger,
  PublicProjectionFrame,
  PublicProjectionItem,
} from "@/lib/api";

import type { ActiveTurnState, Message, SessionActivityState, StoreState } from "@/lib/store/types";

type ApplyProjectionOptions = {
  assistantId?: string;
  streamAnchor?: ProjectionStreamAnchor;
};

type ProjectionStreamAnchor = {
  turnId?: string;
  runId?: string;
  taskRunId?: string;
  turnRunId?: string;
};

const ACCEPTED_PUBLIC_PROJECTION_AUTHORITIES = new Set(["harness.public_projection"]);
const REQUIRED_FRAME_KEYS = ["op", "slot", "main_visibility", "retention"] as const;

export function publicProjectionFrameFromRecord(value: unknown): PublicProjectionFrame | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Partial<PublicProjectionFrame>;
  if (!ACCEPTED_PUBLIC_PROJECTION_AUTHORITIES.has(text(record.authority))) return null;
  if (!text(record.frame_id || record.projection_id)) return null;
  if (!Number.isFinite(Number(record.event_offset ?? record.sequence ?? 0))) return null;
  if (REQUIRED_FRAME_KEYS.some((key) => !text(record[key]))) return null;
  return record as PublicProjectionFrame;
}

export function publicProjectionFrameSuppressesLegacy(frame: PublicProjectionFrame | null): boolean {
  return Boolean(frame);
}

export function applyPublicProjectionFrame(
  state: StoreState,
  frame: PublicProjectionFrame | null,
  options: ApplyProjectionOptions = {},
): StoreState {
  if (!frame) return state;
  const withActiveTurn = applyActiveTurnUpdate(state, frame);
  const withActivity = applySessionActivity(withActiveTurn, frame);
  return patchProjectionMessage(withActivity, frame, options);
}

function applyActiveTurnUpdate(state: StoreState, frame: PublicProjectionFrame): StoreState {
  const anchor = frame.anchor ?? {};
  const turnId = text(anchor.turn_id);
  const taskRunId = text(anchor.task_run_id);
  if (!turnId && !taskRunId) return state;
  if (frame.op === "turn_terminal" && !taskRunId) {
    return { ...state, activeTurnSnapshot: null };
  }
  return {
    ...state,
    activeTurnSnapshot: {
      turn_id: turnId || state.activeTurnSnapshot?.turn_id || "",
      task_run_id: taskRunId || state.activeTurnSnapshot?.task_run_id,
      state: activeTurnState(frame.state) || state.activeTurnSnapshot?.state,
      turn_run_id: text(anchor.turn_run_id) || state.activeTurnSnapshot?.turn_run_id,
      updated_at: Date.now() / 1000,
    },
  };
}

function applySessionActivity(state: StoreState, frame: PublicProjectionFrame): StoreState {
  if (!frameIsMainVisible(frame)) return state;
  const title = text(frame.title || frame.text);
  if (!title) return state;
  const detail = text(frame.detail);
  const level = activityLevel(frame.state || frame.main_visibility);
  const activity: SessionActivityState = {
    level,
    title,
    detail: detail && detail !== title ? detail : "",
    event: "public_projection_frame",
    receipt: {
      level,
      title,
      body: detail && detail !== title ? detail : undefined,
      debug: { event: "public_projection_frame", frame: text(frame.frame_id || frame.projection_id) },
    },
    updatedAt: Date.now(),
  };
  return { ...state, sessionActivity: activity };
}

function patchProjectionMessage(
  state: StoreState,
  frame: PublicProjectionFrame,
  options: ApplyProjectionOptions,
): StoreState {
  const stateWithProjectionMessage = ensureProjectionMessage(state, frame, options);
  const index = projectionMessageIndex(stateWithProjectionMessage, frame, options);
  if (index < 0) return stateWithProjectionMessage;
  const nextMessages = [...stateWithProjectionMessage.messages];
  const message = nextMessages[index];
  const ledger = reduceProjectionLedger(message.projectionLedger, frame);
  const publicProjection = messagePublicProjectionFromLedger(ledger);
  nextMessages[index] = {
    ...message,
    projectionLedger: ledger,
    publicProjection,
    content: publicProjection.bodyText || message.content,
    stageStatus: publicProjection.currentAction?.text || publicProjection.pinned[0]?.text || message.stageStatus,
  };
  return { ...stateWithProjectionMessage, messages: nextMessages };
}

function ensureProjectionMessage(state: StoreState, frame: PublicProjectionFrame, options: ApplyProjectionOptions): StoreState {
  if (!frameCreatesVisibleMessage(frame)) return state;
  if (projectionMessageIndex(state, frame, options) >= 0) return state;
  const anchor = frame.anchor ?? {};
  const turnId = text(anchor.turn_id);
  if (!turnId) return state;
  const userIndex = state.messages.findIndex((message) =>
    message.role === "user" && text(message.sourceTurnId) === turnId
  );
  if (userIndex < 0) return state;
  const userMessage = state.messages[userIndex];
  const requestedId = text(anchor.message_id);
  const requestedIdIsAvailable = requestedId && !state.messages.some((message) => message.id === requestedId);
  const id = requestedIdIsAvailable ? requestedId : `history-message:${turnId}:assistant`;
  if (state.messages.some((message) => message.id === id)) return state;
  const projectionMessage: Message = {
    id,
    role: "assistant",
    content: "",
    toolCalls: [],
    retrievals: [],
    sourceIndex: typeof userMessage.sourceIndex === "number" ? userMessage.sourceIndex + 0.5 : userIndex + 0.5,
    sourceTurnId: turnId,
    sourceRunId: text(anchor.run_id) || undefined,
    sourceTaskRunId: text(anchor.task_run_id) || undefined,
    sourceTurnRunId: text(anchor.turn_run_id) || undefined,
    projectionLedger: emptyProjectionLedger(),
    publicProjection: messagePublicProjectionFromLedger(emptyProjectionLedger()),
  };
  return {
    ...state,
    messages: [...state.messages, projectionMessage].sort(compareProjectionMessages),
  };
}

function projectionMessageIndex(state: StoreState, frame: PublicProjectionFrame, options: ApplyProjectionOptions) {
  const anchor = frame.anchor ?? {};
  const turnId = text(anchor.turn_id);
  const runId = text(anchor.run_id);
  const taskRunId = text(anchor.task_run_id);
  const turnRunId = text(anchor.turn_run_id);
  if (options.assistantId && streamAnchorMatchesFrame(options.streamAnchor, frame)) {
    const streamIndex = state.messages.findIndex((message) => message.id === options.assistantId && message.role === "assistant");
    if (streamIndex >= 0) return streamIndex;
  }
  const messageId = text(anchor.message_id);
  if (messageId) {
    const index = state.messages.findIndex((message) =>
      message.id === messageId
      && message.role === "assistant"
      && messageCanAcceptProjectionAnchor(message, { turnId, runId, taskRunId, turnRunId })
    );
    if (index >= 0) return index;
  }
  if (turnId) {
    const turnIndex = findAssistantMessageIndexByTurnId(state, turnId);
    if (turnIndex >= 0) return turnIndex;
  }
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    if (
      message.role === "assistant"
      && (
        (runId && message.sourceRunId === runId)
        || (turnRunId && message.sourceTurnRunId === turnRunId)
        || (taskRunId && message.sourceTaskRunId === taskRunId)
      )
    ) {
      return index;
    }
  }
  return -1;
}

function reduceProjectionLedger(current: ProjectionLedger | undefined, frame: PublicProjectionFrame): ProjectionLedger {
  const ledger = cloneLedger(current ?? emptyProjectionLedger());
  const offset = frameOffset(frame);
  switch (frame.op) {
    case "body_append": {
      const bodyChunk = typeof frame.text === "string" ? frame.text : "";
      if (bodyChunk.length > 0 && !ledger.body.source_offsets.includes(offset)) {
        ledger.body.text += bodyChunk;
        ledger.body.source_offsets.push(offset);
        ledger.body.stream_state = "streaming";
      }
      return sortLedger(ledger);
    }
    case "body_finalize": {
      const body = String(frame.text ?? "");
      if (body) ledger.body.text = body;
      ledger.body.stream_state = "finalized";
      if (!ledger.body.source_offsets.includes(offset)) ledger.body.source_offsets.push(offset);
      return sortLedger(ledger);
    }
    case "item_upsert": {
      const item = projectionItemFromFrame(frame);
      if (!item) return sortLedger(ledger);
      if (frame.slot === "current_action") {
        if (!text(frame.tool_call_id)) return addTrace(ledger, item);
        if (ledger.currentAction && ledger.currentAction.itemId !== item.itemId) {
          ledger.trace = upsertProjectionItem(ledger.trace, { ...ledger.currentAction, mainVisibility: "trace_only", retention: "trace" });
        }
        ledger.currentAction = item;
        return sortLedger(ledger);
      }
      if (frame.slot === "pinned") ledger.pinned = upsertProjectionItem(ledger.pinned, item);
      else if (frame.slot === "final_result") ledger.finalResults = upsertProjectionItem(ledger.finalResults, item);
      else if (frame.slot === "status") ledger.status = upsertProjectionItem(ledger.status, item);
      else ledger.trace = upsertProjectionItem(ledger.trace, item);
      return sortLedger(ledger);
    }
    case "item_retire": {
      const item = projectionItemFromFrame(frame);
      const retireId = item?.itemId || text(frame.item_id || frame.tool_call_id);
      if (!retireId) return sortLedger(ledger);
      if (ledger.currentAction && itemMatchesRetireId(ledger.currentAction, retireId)) {
        ledger.trace = upsertProjectionItem(ledger.trace, { ...ledger.currentAction, ...item, mainVisibility: "trace_only", retention: "trace" });
        ledger.currentAction = undefined;
      }
      ledger.pinned = retireItems(ledger.pinned, retireId, item, ledger);
      ledger.finalResults = retireItems(ledger.finalResults, retireId, item, ledger);
      ledger.status = retireItems(ledger.status, retireId, item, ledger);
      if (item) ledger.trace = upsertProjectionItem(ledger.trace, { ...item, mainVisibility: "trace_only", retention: "trace" });
      return sortLedger(ledger);
    }
    case "scope_retire": {
      if (ledger.currentAction?.retention === "transient") {
        ledger.trace = upsertProjectionItem(ledger.trace, { ...ledger.currentAction, mainVisibility: "trace_only", retention: "trace" });
        ledger.currentAction = undefined;
      }
      ledger.status = ledger.status.filter((item) => {
        if (item.retention !== "transient") return true;
        ledger.trace = upsertProjectionItem(ledger.trace, { ...item, mainVisibility: "trace_only", retention: "trace" });
        return false;
      });
      return sortLedger(ledger);
    }
    case "commit_ack": {
      ledger.commit = { state: "committed", key: commitKey(frame) };
      ledger.body.stream_state = "committed";
      return reduceProjectionLedger(ledger, { ...frame, op: "scope_retire", slot: "trace" });
    }
    case "commit_failed": {
      ledger.commit = { state: "failed", key: commitKey(frame) };
      const item = projectionItemFromFrame(frame);
      if (item) ledger.pinned = upsertProjectionItem(ledger.pinned, item);
      return sortLedger(ledger);
    }
    case "turn_terminal": {
      ledger.terminal = { state: text(frame.state), eventOffset: offset };
      const item = projectionItemFromFrame(frame);
      if (item && frame.main_visibility === "pinned") {
        ledger.pinned = upsertProjectionItem(ledger.pinned, item);
      } else if (item) {
        ledger.trace = upsertProjectionItem(ledger.trace, item);
      }
      return sortLedger(ledger);
    }
    default:
      return sortLedger(ledger);
  }
}

function messagePublicProjectionFromLedger(ledger: ProjectionLedger): MessagePublicProjection {
  const visiblePinned = ledger.pinned.filter(itemIsMainVisible);
  const visibleFinal = ledger.finalResults.filter(itemIsMainVisible);
  const visibleStatus = ledger.status.filter(itemIsMainVisible);
  return {
    bodyText: ledger.body.text,
    bodyState: ledger.body.stream_state,
    currentAction: ledger.currentAction && itemIsMainVisible(ledger.currentAction) ? ledger.currentAction : undefined,
    pinned: visiblePinned,
    finalResults: visibleFinal,
    status: visibleStatus,
    traceAvailable: ledger.trace.length > 0,
    traceCount: ledger.trace.length,
    commitState: ledger.commit.state,
  };
}

function projectionItemFromFrame(frame: PublicProjectionFrame): PublicProjectionItem | null {
  const itemId = text(frame.item_id || frame.tool_call_id || frame.frame_id || frame.projection_id);
  if (!itemId) return null;
  return {
    itemId,
    slot: text(frame.slot),
    text: text(frame.text || frame.title),
    title: text(frame.title),
    detail: text(frame.detail),
    state: text(frame.state),
    sourceAuthority: text(frame.source_authority),
    mainVisibility: text(frame.main_visibility),
    retention: text(frame.retention),
    pinReason: text(frame.pin_reason),
    toolCallId: text(frame.tool_call_id),
    permissionDecisionId: text(frame.permission_decision_id),
    toolName: text(frame.tool_name),
    actionKind: text(frame.action_kind),
    subjectLabel: text(frame.subject_label || frame.target),
    traceRefs: Array.isArray(frame.trace_refs) ? frame.trace_refs.map(text).filter(Boolean) : [],
    artifactRefs: Array.isArray(frame.artifact_refs) ? frame.artifact_refs : [],
    eventOffset: frameOffset(frame),
    sourceEventId: text(frame.source_event_id),
  };
}

function emptyProjectionLedger(): ProjectionLedger {
  return {
    body: { text: "", stream_state: "streaming", source_offsets: [] },
    pinned: [],
    finalResults: [],
    status: [],
    trace: [],
    commit: { state: "none" },
  };
}

function cloneLedger(ledger: ProjectionLedger): ProjectionLedger {
  return {
    body: { ...ledger.body, source_offsets: [...ledger.body.source_offsets] },
    currentAction: ledger.currentAction ? { ...ledger.currentAction } : undefined,
    pinned: ledger.pinned.map((item) => ({ ...item })),
    finalResults: ledger.finalResults.map((item) => ({ ...item })),
    status: ledger.status.map((item) => ({ ...item })),
    trace: ledger.trace.map((item) => ({ ...item })),
    commit: { ...ledger.commit },
    terminal: ledger.terminal ? { ...ledger.terminal } : undefined,
  };
}

function addTrace(ledger: ProjectionLedger, item: PublicProjectionItem) {
  ledger.trace = upsertProjectionItem(ledger.trace, { ...item, mainVisibility: "trace_only", retention: "trace" });
  return sortLedger(ledger);
}

function upsertProjectionItem(items: PublicProjectionItem[], incoming: PublicProjectionItem) {
  const index = items.findIndex((item) => item.itemId === incoming.itemId);
  if (index < 0) return [...items, incoming];
  const next = [...items];
  next[index] = { ...next[index], ...incoming };
  return next;
}

function retireItems(items: PublicProjectionItem[], retireId: string, traceItem: PublicProjectionItem | null, ledger: ProjectionLedger) {
  return items.filter((item) => {
    if (!itemMatchesRetireId(item, retireId)) return true;
    ledger.trace = upsertProjectionItem(ledger.trace, { ...item, ...traceItem, mainVisibility: "trace_only", retention: "trace" });
    return false;
  });
}

function itemMatchesRetireId(item: PublicProjectionItem, retireId: string) {
  return item.itemId === retireId || item.toolCallId === retireId;
}

function sortLedger(ledger: ProjectionLedger): ProjectionLedger {
  const byOffset = (left: PublicProjectionItem, right: PublicProjectionItem) =>
    (left.eventOffset ?? 0) - (right.eventOffset ?? 0) || left.itemId.localeCompare(right.itemId);
  ledger.pinned = [...ledger.pinned].sort(byOffset);
  ledger.finalResults = [...ledger.finalResults].sort(byOffset);
  ledger.status = [...ledger.status].sort(byOffset);
  ledger.trace = [...ledger.trace].sort(byOffset);
  ledger.body.source_offsets = [...ledger.body.source_offsets].sort((left, right) => left - right);
  return ledger;
}

function frameCreatesVisibleMessage(frame: PublicProjectionFrame) {
  return frameIsMainVisible(frame) || (frame.slot === "body" && Boolean(text(frame.text)));
}

function frameIsMainVisible(frame: PublicProjectionFrame) {
  return ["visible_live", "visible_final", "pinned"].includes(text(frame.main_visibility));
}

function itemIsMainVisible(item: PublicProjectionItem) {
  return ["visible_live", "visible_final", "pinned"].includes(text(item.mainVisibility));
}

function streamAnchorMatchesFrame(anchor: ProjectionStreamAnchor | undefined, frame: PublicProjectionFrame) {
  if (!anchor) return false;
  const projectionAnchor = frame.anchor ?? {};
  return Boolean(
    (anchor.turnId && projectionAnchor.turn_id === anchor.turnId)
    || (anchor.runId && projectionAnchor.run_id === anchor.runId)
    || (anchor.taskRunId && projectionAnchor.task_run_id === anchor.taskRunId)
    || (anchor.turnRunId && projectionAnchor.turn_run_id === anchor.turnRunId)
  );
}

function messageCanAcceptProjectionAnchor(
  message: Message,
  anchor: { turnId?: string; runId?: string; taskRunId?: string; turnRunId?: string },
) {
  const turnId = text(anchor.turnId);
  const messageTurnId = text(message.sourceTurnId);
  if (turnId && messageTurnId && messageTurnId !== turnId) return false;
  const taskRunId = text(anchor.taskRunId);
  const messageTaskRunId = text(message.sourceTaskRunId);
  if (taskRunId && messageTaskRunId && messageTaskRunId !== taskRunId) return false;
  const runId = text(anchor.runId);
  const turnRunId = text(anchor.turnRunId);
  if (runId && text(message.sourceRunId) && text(message.sourceRunId) !== runId) return false;
  if (turnRunId && text(message.sourceTurnRunId) && text(message.sourceTurnRunId) !== turnRunId) return false;
  return true;
}

function findAssistantMessageIndexByTurnId(state: StoreState, turnId: string) {
  const normalized = text(turnId);
  if (!normalized) return -1;
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    if (message.role !== "assistant") continue;
    if (message.sourceTurnId === normalized) return index;
  }
  return -1;
}

function compareProjectionMessages(left: Message, right: Message) {
  const leftIndex = left.sourceIndex ?? Number.MAX_SAFE_INTEGER;
  const rightIndex = right.sourceIndex ?? Number.MAX_SAFE_INTEGER;
  if (leftIndex !== rightIndex) return leftIndex - rightIndex;
  if (left.role !== right.role) return left.role === "user" ? -1 : 1;
  return left.id.localeCompare(right.id);
}

function activeTurnState(value: unknown): ActiveTurnState | undefined {
  const normalized = text(value) as ActiveTurnState;
  return normalized || undefined;
}

function activityLevel(value: unknown): SessionActivityState["level"] {
  const normalized = text(value).toLowerCase();
  if (["error", "failed", "blocked", "pinned"].includes(normalized)) return "error";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(normalized)) return "stopped";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(normalized)) return "waiting";
  if (["done", "completed", "success", "visible_final"].includes(normalized)) return "success";
  return "running";
}

function commitKey(frame: PublicProjectionFrame) {
  const commit = (frame.commit ?? {}) as Record<string, unknown>;
  return [
    text(frame.anchor?.session_id),
    text(frame.anchor?.turn_id),
    text(frame.anchor?.task_run_id),
    text(commit.commit_event_offset),
    text(commit.content_sha256),
  ].join("|");
}

function frameOffset(frame: PublicProjectionFrame) {
  const value = Number(frame.event_offset ?? frame.sequence ?? 0);
  return Number.isFinite(value) ? value : 0;
}

function text(value: unknown) {
  return String(value ?? "").trim();
}
