import type { PublicProjectionFrame } from "@/lib/api";

import type { FrameIdentity, NormalizedProjectionFrame, ProjectionKey } from "./types";

export function normalizeProjectionFrame(frame: PublicProjectionFrame | null | undefined): NormalizedProjectionFrame | null {
  if (!frame) return null;
  const anchor = frame.anchor ?? {};
  const key: ProjectionKey = {
    sessionId: text(anchor.session_id),
    turnId: text(anchor.turn_id),
    messageId: text(anchor.message_id),
    streamRunId: text(anchor.stream_run_id),
    runId: text(anchor.run_id),
    turnRunId: text(anchor.turn_run_id),
    taskRunId: text(anchor.task_run_id),
  };
  if (!projectionKeyHasAnchor(key)) return null;
  const offset = finiteNumber(frame.event_offset ?? frame.sequence);
  const frameId = text(frame.frame_id || frame.projection_id || frame.source_event_id);
  if (!frameId || !Number.isFinite(offset)) return null;
  const eventLogId = text((frame as { event_log_id?: unknown }).event_log_id) || key.runId || key.streamRunId || key.turnRunId || key.taskRunId || key.turnId || "live";
  const identity: FrameIdentity = {
    eventLogId,
    eventOffset: offset,
    frameId,
    key: `${eventLogId}:${offset}:${frameId}`,
  };
  return {
    frame,
    identity,
    key,
    keyString: projectionKeyString(key),
    offset,
    frameId,
    op: text(frame.op),
    slot: text(frame.slot),
    channel: text(frame.channel),
    eventFamily: text(frame.event_family),
    sourceAuthority: text(frame.source_authority),
    sourceEventType: text(frame.source_event_type),
    mainVisibility: text(frame.main_visibility),
    retention: text(frame.retention),
  };
}

export function projectionKeyString(key: ProjectionKey) {
  return [
    key.sessionId,
    key.messageId,
    key.streamRunId,
    key.turnRunId,
    key.taskRunId,
    key.turnId,
  ].map(text).join("|");
}

export function projectionKeyHasAnchor(key: ProjectionKey) {
  return Boolean(key.messageId || key.streamRunId || key.turnRunId || key.taskRunId || key.turnId);
}

function finiteNumber(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number : Number.NaN;
}

export function text(value: unknown) {
  return String(value ?? "").trim();
}

