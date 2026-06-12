import type { HarnessTraceEvent, RuntimeLogGap, RuntimeLogScope, RuntimeLogStreamPayload } from "@/lib/api";

export type RuntimeLogState = {
  scope: RuntimeLogScope;
  runId: string;
  events: HarnessTraceEvent[];
  gap: RuntimeLogGap | null;
  lastOffset: number;
  lastEventId: string;
  updatedAt: number;
  droppedEventCount: number;
};

export function createRuntimeLogState(scope: RuntimeLogScope, runId: string): RuntimeLogState {
  return {
    scope,
    runId,
    events: [],
    gap: null,
    lastOffset: -1,
    lastEventId: "",
    updatedAt: 0,
    droppedEventCount: 0,
  };
}

export function applyRuntimeLogPayload(
  state: RuntimeLogState,
  payload: RuntimeLogStreamPayload | null | undefined,
  options: { maxEvents?: number } = {},
): RuntimeLogState {
  if (!payload || payload.scope !== state.scope || payload.run_id !== state.runId) {
    return state;
  }
  const maxEvents = clampMaxEvents(options.maxEvents);
  const updatedAt = numberValue(payload.updated_at, state.updatedAt);
  const payloadOffset = numberValue(payload.event_offset, state.lastOffset);

  if (payload.source === "snapshot") {
    const events = trimRuntimeLogEvents(normalizeEvents(payload.events), maxEvents);
    return {
      ...state,
      events,
      gap: null,
      lastOffset: Math.max(payloadOffset, latestEventOffset(events, state.lastOffset)),
      lastEventId: String(payload.last_event_id || state.lastEventId || ""),
      updatedAt,
      droppedEventCount: Math.max(0, normalizeEvents(payload.events).length - events.length),
    };
  }

  if (payload.source === "event" && payload.event) {
    const merged = mergeRuntimeLogEvent(state.events, payload.event);
    const trimmed = trimRuntimeLogEvents(merged, maxEvents);
    return {
      ...state,
      events: trimmed,
      gap: null,
      lastOffset: Math.max(payloadOffset, latestEventOffset(trimmed, state.lastOffset)),
      lastEventId: String(payload.last_event_id || state.lastEventId || ""),
      updatedAt,
      droppedEventCount: state.droppedEventCount + Math.max(0, merged.length - trimmed.length),
    };
  }

  if (payload.source === "gap") {
    return {
      ...state,
      gap: payload.gap ?? null,
      lastOffset: Math.max(payloadOffset, numberValue(payload.gap?.observed_offset, state.lastOffset)),
      updatedAt,
    };
  }

  if (payload.source === "heartbeat") {
    return {
      ...state,
      lastOffset: Math.max(payloadOffset, state.lastOffset),
      updatedAt,
    };
  }

  return state;
}

export function parseRuntimeLogStreamPayload(data: string): RuntimeLogStreamPayload | null {
  const raw = String(data || "").trim();
  if (!raw) return null;
  const payload = JSON.parse(raw) as RuntimeLogStreamPayload;
  if (!payload || typeof payload !== "object") return null;
  return payload;
}

function mergeRuntimeLogEvent(events: HarnessTraceEvent[], event: HarnessTraceEvent) {
  const next = new Map<string, HarnessTraceEvent>();
  for (const item of events) {
    next.set(runtimeLogEventKey(item), item);
  }
  next.set(runtimeLogEventKey(event), event);
  return normalizeEvents([...next.values()]);
}

function normalizeEvents(events: HarnessTraceEvent[] | undefined) {
  if (!Array.isArray(events)) return [];
  return [...events].sort((left, right) => {
    const leftOffset = numberValue(left.offset, -1);
    const rightOffset = numberValue(right.offset, -1);
    if (leftOffset !== rightOffset) return leftOffset - rightOffset;
    return numberValue(left.created_at, 0) - numberValue(right.created_at, 0);
  });
}

function trimRuntimeLogEvents(events: HarnessTraceEvent[], maxEvents: number) {
  if (events.length <= maxEvents) return events;
  return events.slice(events.length - maxEvents);
}

function runtimeLogEventKey(event: HarnessTraceEvent) {
  const eventId = String(event.event_id || "").trim();
  if (eventId) return `id:${eventId}`;
  return `offset:${numberValue(event.offset, -1)}:${String(event.event_type || "")}`;
}

function latestEventOffset(events: HarnessTraceEvent[], fallback: number) {
  return events.reduce((latest, event) => Math.max(latest, numberValue(event.offset, latest)), fallback);
}

function clampMaxEvents(value: number | undefined) {
  if (!Number.isFinite(value)) return 240;
  return Math.max(1, Math.min(Math.trunc(value as number), 1000));
}

function numberValue(value: unknown, fallback: number) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}
