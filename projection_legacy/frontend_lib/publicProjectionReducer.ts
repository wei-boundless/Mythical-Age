import type {
  PublicChatTimelineItem,
  PublicProjectionEnvelope,
  PublicProjectionItem,
  SessionRuntimeAttachment,
} from "@/lib/api";
import { mergePublicTimelineItems } from "@/lib/projection/timeline";

import type { ActiveTurnState, SessionActivityState, StoreState } from "./types";

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

export const PUBLIC_PROJECTION_CONTRACT_REVISION = "20260610-authority-refactor";

const VALID_PROJECTION_SLOTS = new Set(["body", "timeline", "tool", "status", "task", "control"]);
const MESSAGE_BODY_ITEM_KINDS = new Set(["assistant_text", "final_summary"]);

export function publicProjectionEnvelopeFromRecord(value: unknown): PublicProjectionEnvelope | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Partial<PublicProjectionEnvelope>;
  return String(record.authority ?? "").trim() === "harness.public_projection.v1" ? record as PublicProjectionEnvelope : null;
}

export function publicProjectionEnvelopeSuppressesLegacy(envelope: PublicProjectionEnvelope | null): boolean {
  if (!envelope || !isAuthorityRefactorEnvelope(envelope)) {
    return false;
  }
  if (text(envelope.projection_mode).toLowerCase() !== "authoritative") {
    return false;
  }
  return hasProjectionAnchor(envelope) && hasProjectionPayload(envelope);
}

export function applyPublicProjectionEnvelope(
  state: StoreState,
  envelope: PublicProjectionEnvelope | null,
  options: ApplyProjectionOptions = {},
): StoreState {
  if (!envelope) {
    return state;
  }
  const withActiveTurn = applyActiveTurnUpdate(state, envelope);
  const withActivity = applySessionActivity(withActiveTurn, envelope);
  return patchProjectionMessage(withActivity, envelope, options);
}

function applyActiveTurnUpdate(state: StoreState, envelope: PublicProjectionEnvelope): StoreState {
  const update = envelope.active_turn_update;
  const anchor = envelope.anchor ?? {};
  const taskRunId = text(update?.task_run_id ?? anchor.task_run_id);
  const turnId = text(update?.turn_id ?? anchor.turn_id);
  if (!taskRunId && !turnId) {
    return state;
  }
  if (envelope.terminal?.event === "done" && envelope.terminal.visible !== false && !taskRunId) {
    return { ...state, activeTurnSnapshot: null };
  }
  return {
    ...state,
    activeTurnSnapshot: {
      turn_id: turnId || state.activeTurnSnapshot?.turn_id || "",
      task_run_id: taskRunId || state.activeTurnSnapshot?.task_run_id,
      state: activeTurnState(update?.state) || state.activeTurnSnapshot?.state,
      turn_run_id: text(anchor.turn_run_id) || state.activeTurnSnapshot?.turn_run_id,
      updated_at: Date.now() / 1000,
    },
  };
}

function applySessionActivity(state: StoreState, envelope: PublicProjectionEnvelope): StoreState {
  if (envelope.terminal?.visible === false) {
    return state;
  }
  const items = projectionItems(envelope);
  const statusItem = latestItemForSlot(items, "status")
    ?? (envelope.surface === "status_bar" ? latestUsefulItem(items) : null);
  const projected = sessionActivityTextFromEnvelope(envelope, statusItem);
  const title = projected.title;
  if (!title) {
    return state;
  }
  const detail = projected.detail;
  const level = activityLevel(envelope.lifecycle || statusItem?.state);
  const activity: SessionActivityState = {
    level,
    title,
    detail: detail && detail !== title ? detail : "",
    event: "public_projection",
    receipt: {
      level,
      title,
      body: detail && detail !== title ? detail : undefined,
      debug: { event: "public_projection" },
    },
    updatedAt: Date.now(),
  };
  return { ...state, sessionActivity: activity };
}

function sessionActivityTextFromEnvelope(
  envelope: PublicProjectionEnvelope,
  statusItem: PublicProjectionItem | null,
) {
  const level = activityLevel(envelope.lifecycle || statusItem?.state);
  const title = text(statusItem?.title ?? statusItem?.text);
  const detail = text(statusItem?.detail ?? statusItem?.public_summary ?? statusItem?.text);
  if (level === "running") {
    return title ? { title, detail: detail && detail !== title ? detail : "" } : { title: "", detail: "" };
  }
  if (level === "success") {
    return title ? { title, detail: detail && detail !== title ? detail : "" } : { title: "", detail: "" };
  }
  return {
    title,
    detail: detail && detail !== title ? detail : "",
  };
}

function patchProjectionMessage(
  state: StoreState,
  envelope: PublicProjectionEnvelope,
  options: ApplyProjectionOptions,
): StoreState {
  const messageIndex = projectionMessageIndex(state, envelope, options);
  if (messageIndex < 0) {
    return state;
  }
  const bodyText = envelope.source_authority === "model" && envelope.surface === "assistant_body"
    ? bodyFromItems(projectionItems(envelope))
    : "";
  const timelineItems = timelineItemsFromEnvelope(envelope);
  const taskAttachment = runtimeAttachmentFromEnvelope(envelope);
  if (!bodyText && !timelineItems.length && !taskAttachment && envelope.terminal?.visible === false) {
    return state;
  }
  return {
    ...state,
    messages: state.messages.map((message, index) => {
      if (index !== messageIndex || message.role !== "assistant") {
        return message;
      }
      const runtimeAttachments = taskAttachment
        ? mergeRuntimeAttachment(message.runtimeAttachments, {
            ...taskAttachment,
            anchor_message_id: taskAttachment.anchor_message_id || message.id,
          })
        : message.runtimeAttachments;
      return {
        ...message,
        content: bodyText && !message.content.trim() ? bodyText : message.content,
        runtimePublicTimelineDraft: timelineItems.length
          ? mergePublicTimelineItems(message.runtimePublicTimelineDraft, timelineItems)
          : message.runtimePublicTimelineDraft,
        runtimeAttachments,
        stageStatus: stageStatusFromEnvelope(envelope) || message.stageStatus,
      };
    }),
  };
}

function projectionMessageIndex(
  state: StoreState,
  envelope: PublicProjectionEnvelope,
  options: ApplyProjectionOptions,
) {
  const anchor = envelope.anchor ?? {};
  const anchorMessageId = text(anchor.message_id);
  if (anchorMessageId) {
    const index = state.messages.findIndex((message) => message.id === anchorMessageId);
    if (index >= 0) return index;
  }
  const runIds = projectionRunIds(anchor);
  for (const runId of runIds) {
    const index = state.messages.findIndex((message) =>
      message.role === "assistant"
      && (
        text(message.sourceRunId) === runId
        || text(message.sourceTaskRunId) === runId
        || text(message.sourceTurnRunId) === runId
        || (message.runtimeAttachments ?? []).some((attachment) => runtimeAttachmentRunId(attachment) === runId)
      )
    );
    if (index >= 0) return index;
  }
  const turnId = text(anchor.turn_id);
  if (turnId) {
    const index = state.messages.findIndex((message) =>
      message.role === "assistant" && text(message.sourceTurnId) === turnId
    );
    if (index >= 0) return index;
  }
  const hasAnchor = Boolean(anchorMessageId || turnId || runIds.length);
  if (isAuthorityRefactorEnvelope(envelope) && !hasAnchor) {
    return -1;
  }
  const assistantId = text(options.assistantId);
  if (assistantId && (!hasAnchor || streamAnchorMatches(anchor, options.streamAnchor))) {
    const index = state.messages.findIndex((message) => message.id === assistantId);
    if (index >= 0) return index;
  }
  return -1;
}

function projectionRunIds(anchor: NonNullable<PublicProjectionEnvelope["anchor"]>) {
  const ids = [anchor.task_run_id, anchor.run_id, anchor.turn_run_id]
    .map(text)
    .filter(Boolean);
  return [...new Set(ids)];
}

function streamAnchorMatches(
  anchor: NonNullable<PublicProjectionEnvelope["anchor"]>,
  streamAnchor: ProjectionStreamAnchor | undefined,
) {
  if (!streamAnchor) return false;
  const anchorTurnId = text(anchor.turn_id);
  if (anchorTurnId && text(streamAnchor.turnId) && anchorTurnId === text(streamAnchor.turnId)) {
    return true;
  }
  const anchorRunIds = projectionRunIds(anchor);
  const streamRunIds = [streamAnchor.runId, streamAnchor.taskRunId, streamAnchor.turnRunId]
    .map(text)
    .filter(Boolean);
  return anchorRunIds.some((runId) => streamRunIds.includes(runId));
}

function runtimeAttachmentFromEnvelope(envelope: PublicProjectionEnvelope): SessionRuntimeAttachment | null {
  const projection = envelope.task_projection;
  const anchor = envelope.anchor ?? {};
  const taskRunId = text(projection?.task_run_id ?? anchor.task_run_id);
  const runId = taskRunId || text(anchor.run_id);
  if (!runId) {
    return null;
  }
  const timeline = timelineItemsFromEnvelope(envelope);
  return {
    attachment_id: `runtime-attachment:${runId}`,
    run_id: runId,
    anchor_turn_id: text(projection?.anchor_turn_id ?? projection?.turn_id ?? anchor.turn_id),
    anchor_message_id: text(projection?.anchor_message_id ?? anchor.message_id) || undefined,
    anchor_role: text(anchor.anchor_role) || "assistant",
    turn_run_id: text(anchor.turn_run_id) || undefined,
    task_run_id: taskRunId || undefined,
    task_id: text(projection?.task_id) || undefined,
    status: text(projection?.status ?? envelope.lifecycle),
    lifecycle: text(envelope.lifecycle),
    title: "处理进展",
    public_timeline: timeline,
    task_projection: projection,
    trace_available: true,
    debug_trace_ref: taskRunId || runId,
    updated_at: Number(projection?.updated_at ?? envelope.created_at ?? Date.now() / 1000) || Date.now() / 1000,
  };
}

function mergeRuntimeAttachment(
  existing: SessionRuntimeAttachment[] | undefined,
  attachment: SessionRuntimeAttachment,
) {
  const current = [...(existing ?? [])];
  const runId = runtimeAttachmentRunId(attachment);
  const index = current.findIndex((item) => runtimeAttachmentRunId(item) === runId);
  if (index < 0) {
    return [...current, attachment];
  }
  current[index] = {
    ...current[index],
    ...attachment,
    public_timeline: mergePublicTimelineItems(current[index]?.public_timeline, attachment.public_timeline),
  };
  return current;
}

function timelineItemsFromEnvelope(envelope: PublicProjectionEnvelope): PublicChatTimelineItem[] {
  if (envelope.terminal?.visible === false) {
    return [];
  }
  return projectionItems(envelope)
    .filter((item) => !isBodyItem(envelope, item))
    .map((item) => ({ ...item, kind: text(item.kind) || "status_update" }));
}

function bodyFromItems(items: PublicProjectionItem[] | undefined) {
  for (const item of items ?? []) {
    if (isMessageBodyItem(item)) {
      const body = text(item.text ?? item.detail ?? item.public_summary);
      if (body) return body;
    }
  }
  return "";
}

function isBodyItem(envelope: PublicProjectionEnvelope, item: PublicProjectionItem) {
  return envelope.source_authority === "model"
    && envelope.surface === "assistant_body"
    && isMessageBodyItem(item);
}

function isMessageBodyItem(item: PublicProjectionItem) {
  return text(item.slot) === "body"
    && text(item.source_authority) === "model"
    && MESSAGE_BODY_ITEM_KINDS.has(text(item.kind));
}

function latestItemForSlot(items: PublicProjectionItem[] | undefined, slot: string) {
  return [...(items ?? [])].reverse().find((item) => text(item.slot) === slot) ?? null;
}

function latestUsefulItem(items: PublicProjectionItem[] | undefined) {
  return [...(items ?? [])].reverse().find((item) => text(item.title ?? item.text)) ?? null;
}

function stageStatusFromEnvelope(envelope: PublicProjectionEnvelope) {
  if (envelope.terminal?.visible === false) {
    return "";
  }
  if (envelope.surface === "assistant_body") {
    return envelope.terminal?.event === "done" ? "完成" : "";
  }
  if (envelope.surface === "tool_window") {
    return envelope.lifecycle === "done" ? "" : "正在思考";
  }
  const item = latestUsefulItem(projectionItems(envelope));
  return text(item?.title ?? item?.text);
}

function projectionItems(envelope: PublicProjectionEnvelope): PublicProjectionItem[] {
  return (envelope.items ?? []).filter(isValidProjectionItem);
}

function isValidProjectionItem(item: PublicProjectionItem | undefined): item is PublicProjectionItem {
  if (!item) return false;
  const slot = text(item.slot);
  return VALID_PROJECTION_SLOTS.has(slot)
    && Boolean(text(item.surface))
    && Boolean(text(item.source_authority));
}

function activityLevel(value: unknown): SessionActivityState["level"] {
  const normalized = text(value).toLowerCase();
  if (["error", "failed", "blocked"].includes(normalized)) return "error";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(normalized)) return "stopped";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(normalized)) return "waiting";
  if (["done", "completed", "success"].includes(normalized)) return "success";
  return "running";
}

function runtimeAttachmentRunId(attachment: SessionRuntimeAttachment | undefined) {
  return text(attachment?.run_id ?? attachment?.task_run_id);
}

function text(value: unknown) {
  return String(value ?? "").trim();
}

function activeTurnState(value: unknown): ActiveTurnState | undefined {
  const normalized = text(value);
  return ACTIVE_TURN_STATES.has(normalized) ? normalized as ActiveTurnState : undefined;
}

const ACTIVE_TURN_STATES = new Set([
  "starting",
  "model_turn",
  "running_task",
  "waiting_executor",
  "waiting_user",
  "waiting_approval",
  "waiting_safe_boundary",
  "interrupting",
  "terminal",
]);

function isAuthorityRefactorEnvelope(envelope: PublicProjectionEnvelope) {
  return text(envelope.contract_revision) === PUBLIC_PROJECTION_CONTRACT_REVISION;
}

function hasProjectionAnchor(envelope: PublicProjectionEnvelope) {
  const anchor = envelope.anchor ?? {};
  return Boolean(text(anchor.message_id) || text(anchor.turn_id) || projectionRunIds(anchor).length);
}

function hasProjectionPayload(envelope: PublicProjectionEnvelope) {
  return projectionItems(envelope).length > 0 || Boolean(envelope.task_projection);
}
