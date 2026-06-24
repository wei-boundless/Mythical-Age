import type { PublicProjectionFrame, SessionRuntimeAttachment } from "@/lib/api";
import { applyProjectionFramesToState, projectionFrameFromRecord } from "@/lib/projection/reducer";

import type { StoreState } from "../types";

export function recoveredChatRunActivityDetail() {
  return "检测到同一会话的流式 cursor，正在按事件时序重放公开投影。";
}

export function hydrateSessionRuntimeProjection(
  state: Pick<StoreState, "messages" | "activeProjectionsByKey">,
  attachments: SessionRuntimeAttachment[] | undefined,
) {
  const frames: PublicProjectionFrame[] = [];
  let hydratedState = state;
  for (const attachment of attachments ?? []) {
    for (const slice of attachment.projection_slices ?? []) {
      if (slice.schema_version !== "chronological_projection") continue;
      if (!projectionSliceCanHydrate(slice)) continue;
      for (const record of slice.frames ?? []) {
        const frame = projectionFrameFromRecord(record);
        if (!frame) continue;
        const anchoredFrame = frameWithRuntimeAttachmentAnchor(frame, attachment, slice.event_log_id);
        if (!projectionFrameHasHistoryAnchor(anchoredFrame)) continue;
        frames.push(anchoredFrame);
      }
    }
  }
  if (frames.length) {
    const orderedFrames = [...frames].sort((left, right) =>
      Number(left.event_offset ?? left.sequence ?? 0) - Number(right.event_offset ?? right.sequence ?? 0)
      || String(left.frame_id || left.projection_id || "").localeCompare(String(right.frame_id || right.projection_id || ""))
    );
    hydratedState = applyProjectionFramesToState(hydratedState, orderedFrames, { createMessages: true });
  }
  return hydratedState;
}

function projectionSliceCanHydrate(
  slice: NonNullable<SessionRuntimeAttachment["projection_slices"]>[number],
) {
  const frames = Array.isArray(slice.frames) ? slice.frames : [];
  if (String(slice.integrity ?? "").trim() === "incomplete") {
    return false;
  }
  const cursorFrameCount = Number(slice.cursor?.frame_count);
  if (Number.isFinite(cursorFrameCount) && cursorFrameCount !== frames.length) {
    return false;
  }
  if (!sliceRequiresCommittedIntegrity(slice)) {
    return true;
  }
  if (String(slice.integrity ?? "").trim() === "bounded") {
    return false;
  }
  return frames.some((frame) =>
    String(frame?.op ?? "").trim() === "commit_ack"
    || String(frame?.source_event_type ?? "").trim() === "session_output_commit_ack"
  );
}

function sliceRequiresCommittedIntegrity(
  slice: NonNullable<SessionRuntimeAttachment["projection_slices"]>[number],
) {
  const lifecycle = String(slice.display_hint?.lifecycle ?? "").trim();
  const surface = String(slice.display_hint?.main_surface_hint ?? "").trim();
  return slice.committed === true || lifecycle === "committed" || surface === "closeout";
}

function frameWithRuntimeAttachmentAnchor(
  frame: PublicProjectionFrame,
  attachment: SessionRuntimeAttachment,
  sliceEventLogId = "",
): PublicProjectionFrame {
  const anchor = frame.anchor ?? {};
  const projectionAnchor = attachment.projection_anchor ?? {};
  return {
    ...frame,
    event_log_id: frame.event_log_id || sliceEventLogId || attachment.event_log_id,
    anchor: compactProjectionAnchor({
      ...anchor,
      session_id: anchor.session_id || projectionAnchor.session_id,
      turn_id: anchor.turn_id || projectionAnchor.anchor_turn_id || attachment.anchor_turn_id,
      message_id: anchor.message_id || projectionAnchor.anchor_message_id || attachment.anchor_message_id,
      task_run_id: anchor.task_run_id || projectionAnchor.task_run_id || attachment.task_run_id,
      stream_run_id: anchor.stream_run_id || projectionAnchor.stream_run_id || attachment.stream_run_id,
      turn_run_id: anchor.turn_run_id || projectionAnchor.turn_run_id || attachment.turn_run_id,
      run_id: anchor.run_id || projectionAnchor.run_id || attachment.run_id,
    }),
  };
}

function projectionFrameHasHistoryAnchor(frame: PublicProjectionFrame) {
  return Boolean(String(frame.anchor?.message_id || "").trim() || String(frame.anchor?.turn_id || "").trim());
}

function compactProjectionAnchor(anchor: NonNullable<PublicProjectionFrame["anchor"]>) {
  return Object.fromEntries(
    Object.entries(anchor).filter(([, value]) => String(value ?? "").trim()),
  ) as NonNullable<PublicProjectionFrame["anchor"]>;
}
