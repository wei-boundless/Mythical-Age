import type { PublicProjectionFrame } from "@/lib/api";
import {
  normalizeProjectionFrame,
  projectionViewFromLedger,
  reduceChronologicalProjectionLedger,
} from "@/lib/projection/chronological";

import type { Message, StoreState } from "@/lib/store/types";

type ProjectionPatchState = Pick<StoreState, "messages" | "activeProjectionsByKey">;

type ApplyProjectionOptions = {
  assistantId?: string;
  createMessage?: boolean;
  streamAnchor?: ProjectionStreamAnchor;
  deferViewBuild?: boolean;
};

type ProjectionStreamAnchor = {
  turnId?: string;
  streamRunId?: string;
  runId?: string;
  taskRunId?: string;
  turnRunId?: string;
};

const ACCEPTED_PROJECTION_AUTHORITIES = new Set(["harness.public_projection"]);
const REQUIRED_FRAME_KEYS = ["op", "slot", "main_visibility", "retention"] as const;

export function projectionFrameFromRecord(value: unknown): PublicProjectionFrame | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Partial<PublicProjectionFrame>;
  if (!ACCEPTED_PROJECTION_AUTHORITIES.has(text(record.authority))) return null;
  if (!text(record.frame_id || record.projection_id)) return null;
  if (!Number.isFinite(Number(record.event_offset))) return null;
  if (REQUIRED_FRAME_KEYS.some((key) => !text(record[key]))) return null;
  return record as PublicProjectionFrame;
}

export function applyProjectionFrame(
  state: StoreState,
  frame: PublicProjectionFrame | null,
  options: ApplyProjectionOptions = {},
): StoreState {
  if (!frame) return state;
  return patchProjectionMessage(state, frame, options);
}

export function applyProjectionFramesToState<T extends ProjectionPatchState>(
  state: T,
  frames: PublicProjectionFrame[],
  options: { createMessages?: boolean } = {},
): T {
  let nextState: T = {
    ...state,
    activeProjectionsByKey: state.activeProjectionsByKey ?? {},
  };
  for (const frame of frames) {
    nextState = patchProjectionMessage(nextState, frame, {
      createMessage: options.createMessages === true,
      deferViewBuild: true,
    });
  }
  return rebuildProjectionViews(nextState);
}

export function applyProjectionFramesToMessages(
  messages: Message[],
  frames: PublicProjectionFrame[],
  options: { createMessages?: boolean } = {},
): Message[] {
  return applyProjectionFramesToState(
    { messages, activeProjectionsByKey: {} },
    frames,
    options,
  ).messages;
}

function patchProjectionMessage<T extends ProjectionPatchState>(
  state: T,
  frame: PublicProjectionFrame,
  options: ApplyProjectionOptions,
): T {
  if (!frameCanPatchMainChatProjection(frame)) {
    return state;
  }
  const stateWithProjectionMessage = ensureProjectionMessage(state, frame, options);
  const index = projectionMessageIndex(stateWithProjectionMessage, frame, options);
  if (index < 0) return stateWithProjectionMessage;
  const nextMessages = [...stateWithProjectionMessage.messages];
  const message = nextMessages[index];
  const normalized = normalizeProjectionFrame(frame);
  const previousKey = normalized?.keyString || message.projectionKeyString || "";
  const previousProjection = previousKey
    ? stateWithProjectionMessage.activeProjectionsByKey?.[previousKey]
    : undefined;
  const chronologicalProjectionLedger = reduceChronologicalProjectionLedger(
    previousProjection?.ledger,
    frame,
  );
  const projectionView = options.deferViewBuild
    ? previousProjection?.view
    : projectionViewFromLedger(chronologicalProjectionLedger);
  const keyString = chronologicalProjectionLedger.keyString || previousKey;
  const activeProjectionsByKey = keyString
    ? {
        ...(stateWithProjectionMessage.activeProjectionsByKey ?? {}),
        [keyString]: {
          keyString,
          ledger: chronologicalProjectionLedger,
          view: projectionView,
        },
      }
    : stateWithProjectionMessage.activeProjectionsByKey;
  if (message.projectionKeyString === keyString) {
    return {
      ...stateWithProjectionMessage,
      activeProjectionsByKey,
    };
  }
  nextMessages[index] = {
    ...message,
    projectionKeyString: keyString || message.projectionKeyString,
    sourceStreamRunId: message.sourceStreamRunId || text(frame.anchor?.stream_run_id) || undefined,
    sourceRunId: message.sourceRunId || text(frame.anchor?.run_id) || undefined,
    sourceTaskRunId: message.sourceTaskRunId || text(frame.anchor?.task_run_id) || undefined,
    sourceTurnRunId: message.sourceTurnRunId || text(frame.anchor?.turn_run_id) || undefined,
  };
  return { ...stateWithProjectionMessage, messages: nextMessages, activeProjectionsByKey };
}

export function rebuildProjectionViews<T extends ProjectionPatchState>(state: T): T {
  const projections = state.activeProjectionsByKey ?? {};
  const entries = Object.entries(projections);
  if (!entries.length) {
    return state;
  }
  let changed = false;
  const activeProjectionsByKey: ProjectionPatchState["activeProjectionsByKey"] = {};
  for (const [key, projection] of entries) {
    const view = projectionViewFromLedger(projection.ledger);
    activeProjectionsByKey[key] = projection.view === view
      ? projection
      : {
          ...projection,
          view,
        };
    changed ||= activeProjectionsByKey[key] !== projection;
  }
  return changed ? { ...state, activeProjectionsByKey } : state;
}

function ensureProjectionMessage<T extends ProjectionPatchState>(state: T, frame: PublicProjectionFrame, options: ApplyProjectionOptions): T {
  if (options.createMessage === false) return state;
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
    sourceStreamRunId: text(anchor.stream_run_id) || undefined,
    sourceRunId: text(anchor.run_id) || undefined,
    sourceTaskRunId: text(anchor.task_run_id) || undefined,
    sourceTurnRunId: text(anchor.turn_run_id) || undefined,
  };
  return {
    ...state,
    messages: [...state.messages, projectionMessage].sort(compareProjectionMessages),
  };
}

function projectionMessageIndex(state: ProjectionPatchState, frame: PublicProjectionFrame, options: ApplyProjectionOptions) {
  const anchor = frame.anchor ?? {};
  const turnId = text(anchor.turn_id);
  const streamRunId = text(anchor.stream_run_id);
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
      && messageCanAcceptProjectionAnchor(message, { turnId, streamRunId, taskRunId, turnRunId })
    );
    if (index >= 0) return index;
  }
  if (turnId) {
    const turnIndex = findAssistantMessageIndexByTurnId(state, turnId, { streamRunId, taskRunId, turnRunId });
    if (turnIndex >= 0) return turnIndex;
  }
  const frameHasStrongAnchor = hasStrongProjectionAnchor({ turnId, streamRunId, turnRunId });
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    if (
      message.role === "assistant"
      && messageCanAcceptProjectionAnchor(message, { turnId, streamRunId, taskRunId, turnRunId })
      && (
        strongMessageAnchorMatches(message, { streamRunId, taskRunId, turnRunId })
        || (!frameHasStrongAnchor && taskOnlyMessageAnchorMatches(message, { taskRunId }))
      )
    ) {
      return index;
    }
  }
  return -1;
}

function frameCreatesVisibleMessage(frame: PublicProjectionFrame) {
  if (!frameCanPatchMainChatProjection(frame)) return false;
  if (!frameIsMainVisible(frame)) return false;
  return (frame.slot === "body" && Boolean(text(frame.text)))
    || frameIsToolProjection(frame)
    || frameIsTodoPlanProjection(frame);
}

function frameIsMainVisible(frame: PublicProjectionFrame) {
  return ["visible_live", "visible_final", "pinned"].includes(text(frame.main_visibility));
}

function frameCanPatchMainChatProjection(frame: PublicProjectionFrame) {
  if (frame.slot === "body") {
    return text(frame.source_authority) === "model" && frameIsMainVisible(frame);
  }
  if (frame.op === "commit_ack" || frame.op === "scope_retire") {
    return true;
  }
  return frameIsToolProjection(frame)
    || (frameIsTodoPlanProjection(frame) && frameIsMainVisible(frame));
}

function frameIsToolProjection(frame: PublicProjectionFrame) {
  return Boolean(text(frame.tool_call_id) || text(frame.tool_lifecycle_id) || text(frame.tool_name) || text(frame.event_family) === "tool_control");
}

function frameIsTodoPlanProjection(frame: PublicProjectionFrame) {
  return text(frame.status_kind) === "todo_plan" && Array.isArray(frame.todo_items);
}

function streamAnchorMatchesFrame(anchor: ProjectionStreamAnchor | undefined, frame: PublicProjectionFrame) {
  if (!anchor) return false;
  const projectionAnchor = frame.anchor ?? {};
  if (!projectionAnchorsAreCompatible(anchor, projectionAnchor)) return false;
  return Boolean(
    (anchor.turnId && projectionAnchor.turn_id === anchor.turnId)
    || (anchor.streamRunId && projectionAnchor.stream_run_id === anchor.streamRunId)
    || (anchor.turnRunId && projectionAnchor.turn_run_id === anchor.turnRunId)
    || (
      anchor.taskRunId
      && projectionAnchor.task_run_id === anchor.taskRunId
      && !hasStrongProjectionAnchor(anchor)
      && !hasStrongProjectionAnchor({
        turnId: text(projectionAnchor.turn_id),
        streamRunId: text(projectionAnchor.stream_run_id),
        turnRunId: text(projectionAnchor.turn_run_id),
      })
    )
  );
}

function messageCanAcceptProjectionAnchor(
  message: Message,
  anchor: { turnId?: string; streamRunId?: string; taskRunId?: string; turnRunId?: string },
) {
  const turnId = text(anchor.turnId);
  const messageTurnId = text(message.sourceTurnId);
  if (turnId && messageTurnId && messageTurnId !== turnId) return false;
  const streamRunId = text(anchor.streamRunId);
  const messageStreamRunId = text(message.sourceStreamRunId);
  if (streamRunId && messageStreamRunId && messageStreamRunId !== streamRunId) return false;
  const taskRunId = text(anchor.taskRunId);
  const messageTaskRunId = text(message.sourceTaskRunId);
  if (taskRunId && messageTaskRunId && messageTaskRunId !== taskRunId) return false;
  const turnRunId = text(anchor.turnRunId);
  if (turnRunId && text(message.sourceTurnRunId) && text(message.sourceTurnRunId) !== turnRunId) return false;
  return true;
}

function projectionAnchorsAreCompatible(
  streamAnchor: ProjectionStreamAnchor,
  frameAnchor: NonNullable<PublicProjectionFrame["anchor"]>,
) {
  const checks: Array<[unknown, unknown]> = [
    [streamAnchor.turnId, frameAnchor.turn_id],
    [streamAnchor.streamRunId, frameAnchor.stream_run_id],
    [streamAnchor.taskRunId, frameAnchor.task_run_id],
    [streamAnchor.turnRunId, frameAnchor.turn_run_id],
  ];
  return checks.every(([left, right]) => {
    const normalizedLeft = text(left);
    const normalizedRight = text(right);
    return !normalizedLeft || !normalizedRight || normalizedLeft === normalizedRight;
  });
}

function hasStrongProjectionAnchor(anchor: ProjectionStreamAnchor) {
  return Boolean(text(anchor.turnId) || text(anchor.streamRunId) || text(anchor.turnRunId));
}

function strongMessageAnchorMatches(
  message: Message,
  anchor: { streamRunId?: string; taskRunId?: string; turnRunId?: string },
) {
  return Boolean(
    (anchor.turnRunId && text(message.sourceTurnRunId) === anchor.turnRunId)
    || (anchor.streamRunId && text(message.sourceStreamRunId) === anchor.streamRunId)
  );
}

function taskOnlyMessageAnchorMatches(message: Message, anchor: { taskRunId?: string }) {
  const taskRunId = text(anchor.taskRunId);
  if (!taskRunId || text(message.sourceTaskRunId) !== taskRunId) return false;
  return !text(message.sourceTurnId) && !text(message.sourceStreamRunId) && !text(message.sourceTurnRunId);
}

function findAssistantMessageIndexByTurnId(
  state: ProjectionPatchState,
  turnId: string,
  anchor: { streamRunId?: string; taskRunId?: string; turnRunId?: string },
) {
  const normalized = text(turnId);
  if (!normalized) return -1;
  const hasExecutionAnchor = Boolean(text(anchor.streamRunId) || text(anchor.turnRunId));
  let turnOnlyIndex = -1;
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    if (message.role !== "assistant") continue;
    if (message.sourceTurnId !== normalized) continue;
    if (!messageCanAcceptProjectionAnchor(message, { turnId: normalized, ...anchor })) continue;
    if (hasExecutionAnchor) {
      if (strongMessageAnchorMatches(message, anchor)) return index;
      if (!text(message.sourceStreamRunId) && !text(message.sourceTurnRunId) && turnOnlyIndex < 0) {
        turnOnlyIndex = index;
      }
      continue;
    }
    return index;
  }
  return turnOnlyIndex;
}

function compareProjectionMessages(left: Message, right: Message) {
  const leftIndex = left.sourceIndex ?? Number.MAX_SAFE_INTEGER;
  const rightIndex = right.sourceIndex ?? Number.MAX_SAFE_INTEGER;
  if (leftIndex !== rightIndex) return leftIndex - rightIndex;
  if (left.role !== right.role) return left.role === "user" ? -1 : 1;
  return left.id.localeCompare(right.id);
}

function text(value: unknown) {
  return String(value ?? "").trim();
}
