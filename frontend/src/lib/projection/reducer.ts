import type {
  MessagePublicProjection,
  ProjectionLedger,
  PublicProjectionBodyBlock,
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
  streamRunId?: string;
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
  if (!Number.isFinite(Number(record.event_offset))) return null;
  if (REQUIRED_FRAME_KEYS.some((key) => !text(record[key]))) return null;
  return record as PublicProjectionFrame;
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

export function applyPublicProjectionFramesToMessages(
  messages: Message[],
  frames: PublicProjectionFrame[],
): Message[] {
  let state = { messages } as StoreState;
  for (const frame of frames) {
    state = patchProjectionMessage(state, frame, {});
  }
  return state.messages;
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
  if (!frameShouldUpdateSessionActivity(frame)) return state;
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

function frameShouldUpdateSessionActivity(frame: PublicProjectionFrame) {
  if (!frameIsMainVisible(frame)) return false;
  const slot = text(frame.slot);
  const eventFamily = text(frame.event_family);
  const channel = text(frame.channel);
  if (slot === "body" || eventFamily === "assistant_body" || channel === "body") return false;
  if (slot === "current_action" || eventFamily === "tool_control" || channel === "control" || text(frame.tool_call_id)) return false;
  return ["status", "pinned", "final_result"].includes(slot)
    || eventFamily === "status_trace"
    || eventFamily === "turn_anchor_terminal";
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
    sourceStreamRunId: text(anchor.stream_run_id) || undefined,
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
        appendBodyBlock(ledger, frame, bodyChunk, "streaming");
      }
      return sortLedger(ledger);
    }
    case "body_finalize": {
      const body = String(frame.text ?? "");
      const previousBody = ledger.body.text;
      if (body) {
        const missingSuffix = body.startsWith(previousBody) ? body.slice(previousBody.length) : "";
        ledger.body.text = body;
        if (missingSuffix) {
          appendBodyBlock(ledger, frame, missingSuffix, "finalized");
        } else if (previousBody && body !== previousBody) {
          ledger.body.blocks = [];
          appendBodyBlock(ledger, frame, body, "finalized");
        }
      }
      ledger.body.stream_state = "finalized";
      if (!ledger.body.source_offsets.includes(offset)) ledger.body.source_offsets.push(offset);
      if (!ledger.body.blocks.length && body) {
        appendBodyBlock(ledger, frame, body, "finalized");
      } else {
        markLatestBodyBlockState(ledger, "finalized", offset);
      }
      return sortLedger(ledger);
    }
    case "item_upsert": {
      const item = projectionItemFromFrame(frame);
      if (!item) return sortLedger(ledger);
      if (frame.slot === "current_action") {
        if (
          !text(frame.tool_call_id)
          || text(frame.source_authority) !== "model"
          || text(frame.source_event_type) !== "tool_call_requested"
        ) {
          return addTrace(ledger, item);
        }
        if (ledger.currentAction && ledger.currentAction.itemId !== item.itemId) {
          ledger.trace = upsertProjectionItem(ledger.trace, { ...ledger.currentAction, mainVisibility: "trace_only", retention: "trace" });
        }
        recordTimelineItem(ledger, frame, item);
        ledger.currentAction = item;
        return sortLedger(ledger);
      }
      recordTimelineItem(ledger, frame, item);
      if (frame.slot === "pinned") ledger.pinned = upsertProjectionItem(ledger.pinned, item);
      else if (frame.slot === "final_result") ledger.finalResults = upsertProjectionItem(ledger.finalResults, item);
      else if (frame.slot === "status") ledger.status = upsertProjectionItem(ledger.status, item);
      else ledger.trace = upsertProjectionItem(ledger.trace, item);
      return sortLedger(ledger);
    }
    case "item_retire": {
      const item = projectionItemFromFrame(frame);
      const retireIds = retireIdsForFrame(frame, item);
      if (!retireIds.length) return sortLedger(ledger);
      if (item) recordTimelineItem(ledger, frame, item);
      if (ledger.currentAction && retireIds.some((retireId) => itemMatchesRetireId(ledger.currentAction!, retireId))) {
        const retiredAction = item ? mergeProjectionItem(ledger.currentAction, item) : ledger.currentAction;
        ledger.trace = upsertProjectionItem(ledger.trace, { ...retiredAction, mainVisibility: "trace_only", retention: "trace" });
        if (item && itemIsMainVisible(item)) {
          ledger.status = upsertProjectionItem(ledger.status, {
            ...retiredAction,
            slot: "status",
            mainVisibility: item.mainVisibility,
            retention: item.retention,
          });
        }
        ledger.currentAction = undefined;
      }
      for (const retireId of retireIds) {
        ledger.pinned = retireItems(ledger.pinned, retireId, item, ledger);
        ledger.finalResults = retireItems(ledger.finalResults, retireId, item, ledger);
        ledger.status = retireItems(ledger.status, retireId, item, ledger);
      }
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
      ledger.body.blocks = ledger.body.blocks.map((block) => ({ ...block, state: "committed" }));
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
  const bodyEventOffset = ledger.body.source_offsets.length
    ? ledger.body.source_offsets[ledger.body.source_offsets.length - 1]
    : undefined;
  return {
    bodyText: ledger.body.text,
    bodyState: ledger.body.stream_state,
    bodyBlocks: ledger.body.blocks,
    currentAction: ledger.currentAction && itemIsMainVisible(ledger.currentAction) ? ledger.currentAction : undefined,
    pinned: visiblePinned,
    finalResults: visibleFinal,
    status: visibleStatus,
    trace: ledger.trace,
    timeline: ledger.timeline ?? [],
    bodyEventOffset,
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
    statusKind: text(frame.status_kind),
    sourceAuthority: text(frame.source_authority),
    eventFamily: text(frame.event_family),
    channel: text(frame.channel),
    lossless: typeof frame.lossless === "boolean" ? frame.lossless : undefined,
    mainVisibility: text(frame.main_visibility),
    retention: text(frame.retention),
    pinReason: text(frame.pin_reason),
    toolCallId: text(frame.tool_call_id),
    permissionDecisionId: text(frame.permission_decision_id),
    toolName: text(frame.tool_name),
    toolLifecycleId: text(frame.tool_lifecycle_id),
    actionKind: text(frame.action_kind),
    subjectLabel: text(frame.subject_label || frame.target),
    argumentsPreview: text(frame.arguments_preview),
    target: text(frame.target),
    collapsed: typeof frame.collapsed === "boolean" ? frame.collapsed : undefined,
    traceRefs: Array.isArray(frame.trace_refs) ? frame.trace_refs.map(text).filter(Boolean) : [],
    artifactRefs: Array.isArray(frame.artifact_refs) ? frame.artifact_refs : [],
    eventOffset: frameOffset(frame),
    updatedEventOffset: frameOffset(frame),
    sourceEventType: text(frame.source_event_type),
    sourceEventId: text(frame.source_event_id),
  };
}

function emptyProjectionLedger(): ProjectionLedger {
  return {
    body: { text: "", stream_state: "streaming", source_offsets: [], blocks: [] },
    pinned: [],
    finalResults: [],
    status: [],
    trace: [],
    timeline: [],
    commit: { state: "none" },
  };
}

function cloneLedger(ledger: ProjectionLedger): ProjectionLedger {
  return {
    body: {
      ...ledger.body,
      source_offsets: [...ledger.body.source_offsets],
      blocks: [...(ledger.body.blocks ?? [])].map((block) => ({
        ...block,
        sourceFrameIds: [...(block.sourceFrameIds ?? [])],
      })),
    },
    displayCursor: ledger.displayCursor ? { ...ledger.displayCursor } : undefined,
    currentAction: ledger.currentAction ? { ...ledger.currentAction } : undefined,
    pinned: ledger.pinned.map((item) => ({ ...item })),
    finalResults: ledger.finalResults.map((item) => ({ ...item })),
    status: ledger.status.map((item) => ({ ...item })),
    trace: ledger.trace.map((item) => ({ ...item })),
    timeline: (ledger.timeline ?? []).map((item) => ({ ...item })),
    commit: { ...ledger.commit },
    terminal: ledger.terminal ? { ...ledger.terminal } : undefined,
  };
}

function addTrace(ledger: ProjectionLedger, item: PublicProjectionItem) {
  ledger.trace = upsertProjectionItem(ledger.trace, { ...item, mainVisibility: "trace_only", retention: "trace" });
  return sortLedger(ledger);
}

function recordTimelineItem(ledger: ProjectionLedger, frame: PublicProjectionFrame, item: PublicProjectionItem) {
  const timelineItem = timelineItemFromFrame(frame, item);
  if (!timelineItem) return;
  ledger.timeline = upsertProjectionItem(ledger.timeline, timelineItem);
  ledger.displayCursor = { kind: "activity", itemId: timelineItem.itemId };
}

function appendBodyBlock(
  ledger: ProjectionLedger,
  frame: PublicProjectionFrame,
  textValue: string,
  state: PublicProjectionBodyBlock["state"],
) {
  const frameId = bodyFrameId(frame);
  const offset = frameOffset(frame);
  const previous = ledger.body.blocks[ledger.body.blocks.length - 1];
  if (previous?.sourceFrameIds.includes(frameId)) {
    return;
  }
  if (ledger.displayCursor?.kind === "body" && previous) {
    previous.text += textValue;
    previous.lastOffset = offset;
    previous.state = state;
    previous.sourceFrameIds = [...previous.sourceFrameIds, frameId];
  } else {
    ledger.body.blocks.push({
      kind: "body",
      blockId: text(frame.item_id) || stableBodyBlockId(frame, offset),
      text: textValue,
      firstOffset: offset,
      lastOffset: offset,
      state,
      sourceFrameIds: [frameId],
    });
  }
  ledger.displayCursor = { kind: "body" };
}

function markLatestBodyBlockState(
  ledger: ProjectionLedger,
  state: PublicProjectionBodyBlock["state"],
  offset: number,
) {
  const latest = ledger.body.blocks[ledger.body.blocks.length - 1];
  if (!latest) return;
  latest.state = state;
  latest.lastOffset = Math.max(latest.lastOffset, offset);
}

function bodyFrameId(frame: PublicProjectionFrame) {
  return text(frame.frame_id || frame.projection_id || frame.source_event_id) || stableBodyBlockId(frame, frameOffset(frame));
}

function stableBodyBlockId(frame: PublicProjectionFrame, offset: number) {
  return `body:${text(frame.anchor?.message_id || frame.anchor?.turn_id || frame.source_event_id || "message")}:${offset}`;
}

function timelineItemFromFrame(frame: PublicProjectionFrame, item: PublicProjectionItem): PublicProjectionItem | null {
  if (!itemShouldEnterTimeline(frame, item)) return null;
  const offset = frameOffset(frame);
  const toolCallId = text(frame.tool_call_id || item.toolCallId);
  const lifecycleId = text(frame.tool_lifecycle_id || item.toolLifecycleId);
  const frameId = text(frame.frame_id || frame.projection_id || item.sourceEventId);
  const toolOwned = Boolean(toolCallId || lifecycleId || item.toolName);
  const timelineItemId = toolOwned
    ? toolCallId || lifecycleId || item.itemId || frameId || `${item.itemId}:timeline:${offset}:${text(frame.op)}`
    : frameId || item.sourceEventId || `${item.itemId}:timeline:${offset}:${text(frame.op)}`;
  return {
    ...item,
    itemId: timelineItemId,
    slot: toolOwned ? "tool" : item.slot,
    toolCallId: toolCallId || item.toolCallId,
    toolLifecycleId: lifecycleId || item.toolLifecycleId,
    toolName: text(frame.tool_name || item.toolName),
    eventOffset: offset,
    updatedEventOffset: offset,
    sourceEventType: text(frame.source_event_type),
    sourceEventId: text(frame.source_event_id),
  };
}

function itemShouldEnterTimeline(frame: PublicProjectionFrame, item: PublicProjectionItem) {
  const slot = text(frame.slot);
  const visibility = text(frame.main_visibility);
  const sourceEventType = text(frame.source_event_type);
  if (sourceEventType === "tool_permission_decided" && visibility === "trace_only") return false;
  if (frame.tool_call_id || frame.tool_lifecycle_id || item.toolCallId || item.toolLifecycleId || item.toolName) return true;
  if (visibility === "hidden") return false;
  return ["current_action", "pinned", "status", "final_result"].includes(slot);
}

function upsertProjectionItem(items: PublicProjectionItem[], incoming: PublicProjectionItem) {
  const index = items.findIndex((item) => item.itemId === incoming.itemId);
  if (index < 0) return [...items, incoming];
  const next = [...items];
  next[index] = mergeProjectionItem(next[index], incoming);
  return next;
}

function mergeProjectionItem(existing: PublicProjectionItem, incoming: PublicProjectionItem): PublicProjectionItem {
  const merged: PublicProjectionItem = { ...existing };
  for (const [key, value] of Object.entries(incoming) as Array<[keyof PublicProjectionItem, PublicProjectionItem[keyof PublicProjectionItem]]>) {
    if (key === "eventOffset") continue;
    if (value === "" || value === undefined || value === null) continue;
    if (Array.isArray(value) && value.length === 0) continue;
    merged[key] = value as never;
  }
  merged.eventOffset = existing.eventOffset ?? incoming.eventOffset;
  merged.updatedEventOffset = incoming.updatedEventOffset ?? incoming.eventOffset ?? existing.updatedEventOffset;
  return merged;
}

function retireItems(items: PublicProjectionItem[], retireId: string, traceItem: PublicProjectionItem | null, ledger: ProjectionLedger) {
  return items.filter((item) => {
    if (!itemMatchesRetireId(item, retireId)) return true;
    ledger.trace = upsertProjectionItem(ledger.trace, { ...item, ...traceItem, mainVisibility: "trace_only", retention: "trace" });
    return false;
  });
}

function itemMatchesRetireId(item: PublicProjectionItem, retireId: string) {
  return item.itemId === retireId || item.toolCallId === retireId || item.toolLifecycleId === retireId;
}

function retireIdsForFrame(frame: PublicProjectionFrame, item: PublicProjectionItem | null) {
  return [
    item?.itemId,
    item?.toolCallId,
    item?.toolLifecycleId,
    frame.item_id,
    frame.tool_call_id,
    frame.tool_lifecycle_id,
  ].map(text).filter(Boolean);
}

function sortLedger(ledger: ProjectionLedger): ProjectionLedger {
  const byOffset = (left: PublicProjectionItem, right: PublicProjectionItem) =>
    (left.eventOffset ?? 0) - (right.eventOffset ?? 0) || left.itemId.localeCompare(right.itemId);
  ledger.pinned = [...ledger.pinned].sort(byOffset);
  ledger.finalResults = [...ledger.finalResults].sort(byOffset);
  ledger.status = [...ledger.status].sort(byOffset);
  ledger.trace = [...ledger.trace].sort(byOffset);
  ledger.timeline = [...(ledger.timeline ?? [])].sort(byOffset);
  ledger.body.source_offsets = [...ledger.body.source_offsets].sort((left, right) => left - right);
  ledger.body.blocks = [...(ledger.body.blocks ?? [])].sort((left, right) =>
    left.firstOffset - right.firstOffset || left.blockId.localeCompare(right.blockId)
  );
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
  state: StoreState,
  turnId: string,
  anchor: { streamRunId?: string; taskRunId?: string; turnRunId?: string },
) {
  const normalized = text(turnId);
  if (!normalized) return -1;
  const hasExecutionAnchor = Boolean(text(anchor.streamRunId) || text(anchor.turnRunId));
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    if (message.role !== "assistant") continue;
    if (message.sourceTurnId !== normalized) continue;
    if (!messageCanAcceptProjectionAnchor(message, { turnId: normalized, ...anchor })) continue;
    if (hasExecutionAnchor && !strongMessageAnchorMatches(message, anchor)) continue;
    return index;
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
