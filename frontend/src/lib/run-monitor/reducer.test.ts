import { describe, expect, it } from "vitest";

import { applyRunMonitorSnapshot, createRunMonitorState } from "./reducer";
import { selectRunMonitorTaskLane, visibleRunMonitorSignals } from "./selectors";
import type { RunMonitorEnvelope, RunMonitorSignal } from "./types";

function signal(patch: Partial<RunMonitorSignal>): RunMonitorSignal {
  return {
    signal_id: "signal:default",
    task_run_id: "taskrun:default",
    task_instance_id: "taskrun:default",
    graph_run_id: "",
    work_kind: "agent_task",
    state: "active",
    activity_state: "running",
    is_running: true,
    visibility: { visible: true, lane: "current", default_lane: "current", hidden: false },
    ...patch,
  } as RunMonitorSignal;
}

function monitor(lanes: NonNullable<RunMonitorEnvelope["management"]>["lanes"]): RunMonitorEnvelope {
  return {
    authority: "runtime_monitor",
    revision: "rtmon:1:test",
    updated_at: 1,
    summary: {},
    signals: [
      ...(lanes.current ?? []),
      ...(lanes.attention ?? []),
      ...(lanes.projects ?? []),
      ...(lanes.recent ?? []),
      ...(lanes.hidden ?? []),
    ],
    primary: lanes.current ?? [],
    attention: lanes.attention ?? [],
    projects: lanes.projects ?? [],
    recent: lanes.recent ?? [],
    management: {
      authority: "runtime_monitor.management",
      lanes,
    },
  } as RunMonitorEnvelope;
}

describe("run monitor projection boundary", () => {
  it("keeps recent records out of the side task lane while preserving management visibility", () => {
    const current = signal({ signal_id: "taskrun:current", task_run_id: "taskrun:current" });
    const recent = signal({
      signal_id: "taskrun:recent",
      task_run_id: "taskrun:recent",
      state: "completed",
      activity_state: "stopped",
      is_running: false,
      visibility: { visible: true, lane: "recent", default_lane: "recent", hidden: false },
    });
    const snapshot = monitor({
      current: [current],
      attention: [],
      projects: [],
      recent: [recent],
      hidden: [],
    });

    expect(selectRunMonitorTaskLane(snapshot).map((item) => item.signal_id)).toEqual(["taskrun:current"]);
    expect(visibleRunMonitorSignals(snapshot).map((item) => item.signal_id)).toContain("taskrun:recent");
  });

  it("does not auto-select an old recent record from a global monitor snapshot", () => {
    const recent = signal({
      signal_id: "taskrun:recent",
      task_run_id: "taskrun:recent",
      state: "completed",
      activity_state: "stopped",
      is_running: false,
      visibility: { visible: true, lane: "recent", default_lane: "recent", hidden: false },
    });
    const snapshot = monitor({
      current: [],
      attention: [],
      projects: [],
      recent: [recent],
      hidden: [],
    });

    const next = applyRunMonitorSnapshot(createRunMonitorState(), snapshot);

    expect(next.selectedSignalId).toBe("");
    expect(next.selectedTaskRunId).toBe("");
  });

  it("keeps explicit selection authority for opened records", () => {
    const recent = signal({
      signal_id: "taskrun:recent",
      task_run_id: "taskrun:recent",
      state: "completed",
      activity_state: "stopped",
      is_running: false,
      visibility: { visible: true, lane: "recent", default_lane: "recent", hidden: false },
    });
    const snapshot = monitor({
      current: [],
      attention: [],
      projects: [],
      recent: [recent],
      hidden: [],
    });

    const next = applyRunMonitorSnapshot(createRunMonitorState(), snapshot, { selectedSignalId: "taskrun:recent" });

    expect(next.selectedSignalId).toBe("taskrun:recent");
    expect(next.selectedTaskRunId).toBe("taskrun:recent");
  });
});
