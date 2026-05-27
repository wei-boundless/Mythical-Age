import { describe, expect, it } from "vitest";

import type { GlobalRuntimeMonitorItem } from "./api";
import { runtimeWorkProjectionFromLiveMonitor, runtimeWorkProjectionFromMonitorItem, visibleRuntimeMonitorItems } from "./runtimeWorkProjection";

function item(patch: Partial<GlobalRuntimeMonitorItem>): GlobalRuntimeMonitorItem {
  return {
    task_run_id: "taskrun:1",
    session_id: "session:1",
    task_id: "task:general",
    title: "General run",
    status: "running",
    terminal_reason: "",
    created_at: 1,
    updated_at: 2,
    elapsed_seconds: 1,
    latest_event_type: "task_run_started",
    latest_event_at: 2,
    event_count: 1,
    coordination_run_id: "",
    coordination_status: "",
    graph_id: "",
    active_node_id: "",
    project_id: "",
    project_title: "",
    project_runtime_status: null,
    has_coordination: false,
    ...patch,
  };
}

describe("runtimeWorkProjection", () => {
  it("shows task graph runs as first-class runtime work", () => {
    const monitorItem = item({
      has_coordination: true,
      graph_id: "graph:main",
      title: "实现五关 roguelike",
    });

    const projection = runtimeWorkProjectionFromMonitorItem(monitorItem);

    expect(projection).toMatchObject({
      workKind: "task_graph_run",
      workId: "taskrun:1",
      primaryRunId: "taskrun:1",
      displayTypeLabel: "任务图",
      title: "实现五关 roguelike",
    });
  });

  it("includes agent runtime phase runs and excludes graph module children", () => {
    const phaseRun = item({
      task_run_id: "taskrun:agent-runtime",
      latest_event_type: "agent_runtime_planning_phase_checked",
    });
    const child = item({
      task_run_id: "taskrun:child",
      task_id: "task_graph.graph_module.child",
      graph_id: "graph:main",
      has_coordination: true,
    });

    const visible = visibleRuntimeMonitorItems({ authority: "test", summary: { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 }, task_runs: [phaseRun, child], updated_at: 1 });

    expect(visible.map((entry) => entry.task_run_id)).toEqual(["taskrun:agent-runtime"]);
    expect(runtimeWorkProjectionFromMonitorItem(phaseRun).workKind).toBe("agent_runtime_run");
  });

  it("does not project live monitor payloads without a task run identity", () => {
    expect(runtimeWorkProjectionFromLiveMonitor({
      authority: "test",
      task_run: {},
      status: "running",
      terminal_reason: "",
      has_coordination: false,
      coordination_run: null,
      loop_state: {},
      agent_runtime_phase_summary: null,
      latest_checkpoint: null,
      updated_at: 1,
    })).toBeNull();
  });
});
