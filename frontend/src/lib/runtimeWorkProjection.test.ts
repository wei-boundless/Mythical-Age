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
  it("shows task order runs as first-class runtime work", () => {
    const monitorItem = item({
      task_order_projection: {
        authority: "task_system.task_order_projection",
        task_order: {
          order_id: "order:1",
          order_kind: "specific_task",
          objective: "实现五关 roguelike",
        },
        task_order_run: {
          run_id: "orderrun:1",
          task_run_id: "taskrun:1",
          status: "running",
        },
        execution_channel: {
          channel_id: "execchan:1",
        },
      },
    });

    const projection = runtimeWorkProjectionFromMonitorItem(monitorItem);

    expect(projection).toMatchObject({
      workKind: "task_order_run",
      workId: "orderrun:1",
      primaryRunId: "taskrun:1",
      displayTypeLabel: "任务订单",
      title: "实现五关 roguelike",
    });
  });

  it("includes professional tasks and excludes graph module children", () => {
    const professional = item({
      task_run_id: "taskrun:professional",
      latest_event_type: "professional_task_stage_summary",
    });
    const child = item({
      task_run_id: "taskrun:child",
      task_id: "task_graph.graph_module.child",
      graph_id: "graph:main",
      has_coordination: true,
    });

    const visible = visibleRuntimeMonitorItems({ authority: "test", summary: { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 }, task_runs: [professional, child], updated_at: 1 });

    expect(visible.map((entry) => entry.task_run_id)).toEqual(["taskrun:professional"]);
    expect(runtimeWorkProjectionFromMonitorItem(professional).workKind).toBe("professional_task");
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
      professional_task_summary: null,
      latest_checkpoint: null,
      task_order_projection: null,
      updated_at: 1,
    })).toBeNull();
  });
});
