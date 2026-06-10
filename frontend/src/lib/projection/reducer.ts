import type {
  PublicChatTimelineItem,
  PublicProjectionEnvelope,
  PublicProjectionItem,
  SessionRuntimeAttachment,
} from "@/lib/api";
import { mergePublicTimelineItems } from "@/lib/projection/timeline";

import type { ActiveTurnState, SessionActivityState, StoreState } from "@/lib/store/types";

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

const ACCEPTED_PUBLIC_PROJECTION_AUTHORITIES = new Set([
  "harness.public_projection",
]);

export function publicProjectionEnvelopeFromRecord(value: unknown): PublicProjectionEnvelope | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Partial<PublicProjectionEnvelope>;
  return ACCEPTED_PUBLIC_PROJECTION_AUTHORITIES.has(text(record.authority)) ? record as PublicProjectionEnvelope : null;
}

export function publicProjectionEnvelopeSuppressesLegacy(envelope: PublicProjectionEnvelope | null): boolean {
  return Boolean(envelope && hasProjectionAnchor(envelope) && hasProjectionPayload(envelope));
}

export function applyPublicProjectionEnvelope(
  state: StoreState,
  envelope: PublicProjectionEnvelope | null,
  options: ApplyProjectionOptions = {},
): StoreState {
  if (!envelope) return state;
  const withActiveTurn = applyActiveTurnUpdate(state, envelope);
  const withActivity = applySessionActivity(withActiveTurn, envelope);
  return patchProjectionMessage(withActivity, envelope, options);
}

function applyActiveTurnUpdate(state: StoreState, envelope: PublicProjectionEnvelope): StoreState {
  const update = envelope.active_turn_update;
  const anchor = envelope.anchor ?? {};
  const taskRunId = text(update?.task_run_id ?? anchor.task_run_id);
  const turnId = text(update?.turn_id ?? anchor.turn_id);
  if (!taskRunId && !turnId) return state;
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
  if (envelope.terminal?.visible === false) return state;
  const item = latestUsefulItem(projectionItems(envelope));
  const title = text(item?.title ?? item?.text ?? item?.public_summary);
  if (!title) return state;
  const detail = text(item?.detail ?? item?.observation ?? item?.implication);
  const level = activityLevel(envelope.lifecycle || item?.state);
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

function patchProjectionMessage(
  state: StoreState,
  envelope: PublicProjectionEnvelope,
  options: ApplyProjectionOptions,
): StoreState {
  const attachment = runtimeAttachmentFromEnvelope(envelope);
  if (!attachment) return state;
  const index = projectionMessageIndex(state, envelope, options);
  if (index < 0) return state;
  const nextMessages = [...state.messages];
  const message = nextMessages[index];
  const existing = message.runtimeAttachments ?? [];
  const runId = runtimeAttachmentRunId(attachment);
  const nextAttachments = [...existing];
  const attachmentIndex = nextAttachments.findIndex((item) => runtimeAttachmentRunId(item) === runId);
  if (attachmentIndex >= 0) {
    const current = nextAttachments[attachmentIndex];
    nextAttachments[attachmentIndex] = {
      ...current,
      ...attachment,
      public_timeline: mergePublicTimelineItems(current.public_timeline, attachment.public_timeline),
      task_projection: attachment.task_projection ?? current.task_projection,
    };
  } else {
    nextAttachments.push(attachment);
  }
  nextMessages[index] = {
    ...message,
    runtimeAttachments: nextAttachments,
    runtimePublicTimelineDraft: mergePublicTimelineItems(message.runtimePublicTimelineDraft, attachment.public_timeline),
    stageStatus: projectedStageStatus(envelope, attachment.public_timeline ?? []) || message.stageStatus,
  };
  return { ...state, messages: nextMessages };
}

function projectionMessageIndex(state: StoreState, envelope: PublicProjectionEnvelope, options: ApplyProjectionOptions) {
  const anchor = envelope.anchor ?? {};
  const messageId = text(anchor.message_id);
  if (messageId) {
    const index = state.messages.findIndex((message) => message.id === messageId && message.role === "assistant");
    if (index >= 0) return index;
  }
  const turnId = text(anchor.turn_id);
  const runId = text(anchor.run_id);
  const taskRunId = text(anchor.task_run_id);
  const turnRunId = text(anchor.turn_run_id);
  if (options.assistantId && streamAnchorMatchesEnvelope(options.streamAnchor, envelope)) {
    const streamIndex = state.messages.findIndex((message) => message.id === options.assistantId && message.role === "assistant");
    if (streamIndex >= 0) return streamIndex;
  }
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    if (
      message.role === "assistant"
      && (
        (turnId && message.sourceTurnId === turnId)
        || (runId && message.sourceRunId === runId)
        || (taskRunId && message.sourceTaskRunId === taskRunId)
        || (turnRunId && message.sourceTurnRunId === turnRunId)
        || (message.runtimeAttachments ?? []).some((attachment) =>
          (turnId && text(attachment.anchor_turn_id) === turnId)
          || (runId && text(attachment.run_id) === runId)
          || (taskRunId && text(attachment.task_run_id) === taskRunId)
          || (turnRunId && text(attachment.turn_run_id) === turnRunId)
        )
      )
    ) {
      return index;
    }
  }
  return -1;
}

function runtimeAttachmentFromEnvelope(envelope: PublicProjectionEnvelope): SessionRuntimeAttachment | null {
  const anchor = envelope.anchor ?? {};
  const runId = text(anchor.task_run_id || anchor.run_id || anchor.turn_run_id || envelope.projection_id);
  if (!runId) return null;
  const timeline = publicTimelineItemsFromEnvelope(envelope);
  const projection = envelope.task_projection;
  if (!timeline.length && !projection) return null;
  return {
    attachment_id: `runtime-attachment:${runId}`,
    run_id: runId,
    anchor_turn_id: text(anchor.turn_id),
    anchor_message_id: text(anchor.message_id) || undefined,
    anchor_role: "assistant",
    task_run_id: text(anchor.task_run_id) || undefined,
    turn_run_id: text(anchor.turn_run_id) || undefined,
    status: text(envelope.lifecycle),
    public_timeline: timeline,
    task_projection: projection,
    trace_available: true,
    debug_trace_ref: runId,
    created_at: Number(envelope.created_at ?? 0) || undefined,
    updated_at: Date.now() / 1000,
  };
}

export function publicTimelineItemsFromEnvelope(envelope: PublicProjectionEnvelope): PublicChatTimelineItem[] {
  if (envelope.terminal?.visible === false) return [];
  return projectionItems(envelope).filter(isValidProjectionItem);
}

function projectionItems(envelope: PublicProjectionEnvelope): PublicProjectionItem[] {
  return Array.isArray(envelope.items) ? envelope.items : [];
}

function isValidProjectionItem(item: PublicProjectionItem | undefined): item is PublicProjectionItem {
  if (!item || typeof item !== "object") return false;
  const slot = text(item.slot);
  const surface = text(item.surface);
  const authority = text(item.source_authority);
  if (surface === "assistant_body" && (slot !== "body" || authority !== "model")) return false;
  if (slot === "body" && (authority !== "model" || surface !== "assistant_body")) return false;
  return true;
}

function latestUsefulItem(items: PublicProjectionItem[]) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (text(item.title ?? item.text ?? item.public_summary ?? item.detail)) return item;
  }
  return null;
}

function projectedStageStatus(envelope: PublicProjectionEnvelope, items: PublicChatTimelineItem[]) {
  if (envelope.terminal?.visible === false) return "";
  const surface = text(envelope.surface);
  if (!["control", "timeline"].includes(surface)) return "";
  const item = latestUsefulItem(items);
  return text(item?.title ?? item?.text ?? item?.public_summary);
}

function streamAnchorMatchesEnvelope(anchor: ProjectionStreamAnchor | undefined, envelope: PublicProjectionEnvelope) {
  if (!anchor) return false;
  const projectionAnchor = envelope.anchor ?? {};
  return Boolean(
    (anchor.turnId && projectionAnchor.turn_id === anchor.turnId)
    || (anchor.runId && projectionAnchor.run_id === anchor.runId)
    || (anchor.taskRunId && projectionAnchor.task_run_id === anchor.taskRunId)
    || (anchor.turnRunId && projectionAnchor.turn_run_id === anchor.turnRunId)
  );
}

function hasProjectionAnchor(envelope: PublicProjectionEnvelope) {
  const anchor = envelope.anchor ?? {};
  return Boolean(text(anchor.message_id) || text(anchor.turn_id) || text(anchor.run_id) || text(anchor.task_run_id) || text(anchor.turn_run_id));
}

function hasProjectionPayload(envelope: PublicProjectionEnvelope) {
  return projectionItems(envelope).length > 0 || Boolean(envelope.task_projection) || Boolean(envelope.active_turn_update);
}

function runtimeAttachmentRunId(attachment: SessionRuntimeAttachment) {
  return text(attachment.run_id || attachment.task_run_id || attachment.turn_run_id);
}

function activeTurnState(value: unknown): ActiveTurnState | undefined {
  const normalized = text(value) as ActiveTurnState;
  return normalized || undefined;
}

function activityLevel(value: unknown): SessionActivityState["level"] {
  const normalized = text(value).toLowerCase();
  if (["error", "failed", "blocked"].includes(normalized)) return "error";
  if (["stopped", "aborted", "cancelled", "canceled"].includes(normalized)) return "stopped";
  if (["waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"].includes(normalized)) return "waiting";
  if (["done", "completed", "success"].includes(normalized)) return "success";
  return "running";
}

function text(value: unknown) {
  return String(value ?? "").trim();
}
