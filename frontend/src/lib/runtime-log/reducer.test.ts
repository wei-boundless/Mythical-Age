import { describe, expect, it } from "vitest";

import type { HarnessTraceEvent, RuntimeLogStreamPayload } from "@/lib/api";
import { applyRuntimeLogPayload, createRuntimeLogState, parseRuntimeLogStreamPayload } from "./reducer";

function event(offset: number, patch: Partial<HarnessTraceEvent> = {}): HarnessTraceEvent {
  return {
    event_id: `event:${offset}`,
    run_id: "taskrun:log",
    task_run_id: "taskrun:log",
    event_type: "step_summary_recorded",
    offset,
    created_at: offset,
    refs: {},
    payload_summary: {},
    ...patch,
  };
}

function payload(patch: Partial<RuntimeLogStreamPayload>): RuntimeLogStreamPayload {
  return {
    source: "snapshot",
    scope: "task_run",
    run_id: "taskrun:log",
    updated_at: 10,
    ...patch,
  };
}

describe("runtime log stream reducer", () => {
  it("uses snapshots as the scoped log window authority", () => {
    const state = applyRuntimeLogPayload(
      createRuntimeLogState("task_run", "taskrun:log"),
      payload({
        events: [event(3), event(1), event(2)],
        event_offset: 3,
      }),
    );

    expect(state.events.map((item) => item.offset)).toEqual([1, 2, 3]);
    expect(state.lastOffset).toBe(3);
    expect(state.gap).toBeNull();
  });

  it("appends event deltas without duplicating replayed offsets", () => {
    const initial = applyRuntimeLogPayload(
      createRuntimeLogState("task_run", "taskrun:log"),
      payload({ events: [event(1)], event_offset: 1 }),
    );
    const replayed = applyRuntimeLogPayload(
      initial,
      payload({
        source: "event",
        event: event(1, { event_type: "agent_turn_received" }),
        event_offset: 1,
      }),
    );
    const next = applyRuntimeLogPayload(
      replayed,
      payload({
        source: "event",
        event: event(2),
        event_offset: 2,
      }),
    );

    expect(next.events).toHaveLength(2);
    expect(next.events.map((item) => item.event_type)).toEqual(["agent_turn_received", "step_summary_recorded"]);
    expect(next.lastOffset).toBe(2);
  });

  it("ignores events from another scoped run", () => {
    const state = createRuntimeLogState("task_run", "taskrun:log");
    const next = applyRuntimeLogPayload(
      state,
      payload({
        run_id: "taskrun:other",
        events: [event(1, { run_id: "taskrun:other" })],
        event_offset: 1,
      }),
    );

    expect(next).toBe(state);
  });

  it("tracks stream gaps without inventing missing events", () => {
    const state = applyRuntimeLogPayload(
      createRuntimeLogState("task_run", "taskrun:log"),
      payload({ events: [event(1)], event_offset: 1 }),
    );
    const next = applyRuntimeLogPayload(
      state,
      payload({
        source: "gap",
        event_offset: 5,
        gap: {
          expected_after_offset: 1,
          observed_offset: 5,
          recovered: false,
        },
      }),
    );

    expect(next.events.map((item) => item.offset)).toEqual([1]);
    expect(next.gap?.observed_offset).toBe(5);
    expect(next.lastOffset).toBe(5);
  });

  it("keeps only the configured tail window", () => {
    const state = applyRuntimeLogPayload(
      createRuntimeLogState("task_run", "taskrun:log"),
      payload({ events: [event(1), event(2), event(3)], event_offset: 3 }),
      { maxEvents: 2 },
    );

    expect(state.events.map((item) => item.offset)).toEqual([2, 3]);
    expect(state.droppedEventCount).toBe(1);
  });

  it("parses EventSource message data", () => {
    expect(parseRuntimeLogStreamPayload(JSON.stringify(payload({ event_offset: 7 })))?.event_offset).toBe(7);
    expect(parseRuntimeLogStreamPayload("")).toBeNull();
  });
});
