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
      is_live: true,
    });
    const child = item({
      task_run_id: "taskrun:child",
      task_id: "task_graph.graph_module.child",
      graph_id: "graph:main",
      has_coordination: true,
      is_live: true,
    });

    const visible = visibleRuntimeMonitorItems({ authority: "test", summary: { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 }, task_runs: [phaseRun, child], updated_at: 1 });

    expect(visible.map((entry) => entry.task_run_id)).toEqual(["taskrun:agent-runtime"]);
    expect(runtimeWorkProjectionFromMonitorItem(phaseRun).workKind).toBe("agent_runtime_run");
  });

  it("keeps only live actionable runs in the monitor dock", () => {
    const liveWaiting = item({
      task_run_id: "taskrun:waiting",
      status: "waiting_executor",
      is_live: true,
      display_bucket: "live",
    });
    const failedHistory = item({
      task_run_id: "taskrun:failed",
      status: "failed",
      is_live: false,
      display_bucket: "history",
    });
    const completedHistory = item({
      task_run_id: "taskrun:completed",
      status: "completed",
      is_live: false,
      display_bucket: "history",
    });

    const visible = visibleRuntimeMonitorItems({
      authority: "test",
      summary: { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 },
      task_runs: [failedHistory, liveWaiting, completedHistory],
      updated_at: 1,
    });

    expect(visible.map((entry) => entry.task_run_id)).toEqual(["taskrun:waiting"]);
  });

  it("keeps recent blocked, failed, and completed task runs visible for final status", () => {
    const blockedTurn = item({
      task_run_id: "turnrun:blocked",
      status: "blocked",
      latest_event_type: "agent_turn_blocked",
      is_live: false,
      display_bucket: "recent",
    });
    const failedRun = item({ task_run_id: "taskrun:failed", status: "failed", is_live: false, display_bucket: "recent" });
    const completedRun = item({ task_run_id: "taskrun:completed", status: "completed", is_live: false, display_bucket: "recent" });

    const visible = visibleRuntimeMonitorItems({
      authority: "test",
      summary: { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 },
      task_runs: [blockedTurn, failedRun, completedRun],
      updated_at: 1,
    });

    expect(visible.map((entry) => entry.task_run_id)).toEqual(["turnrun:blocked", "taskrun:failed", "taskrun:completed"]);
  });

  it("projects single agent task runs as long tasks with latest step summary", () => {
    const run = item({
      task_run_id: "taskrun:single-agent",
      runtime_lane: "single_agent_task",
      latest_step_summary: "系统已执行工具并把观察回灌给 agent。",
      is_live: true,
      display_bucket: "live",
    });

    expect(runtimeWorkProjectionFromMonitorItem(run)).toMatchObject({
      workKind: "agent_runtime_run",
      displayTypeLabel: "长任务",
      latestStepSummary: "系统已执行工具并把观察回灌给 agent。",
    });
  });

  it("keeps chat-scoped task runs attached to their conversation even when they use task runtime lane", () => {
    const run = item({
      task_run_id: "taskrun:turn:session-a:1:abc",
      session_id: "session-a",
      task_id: "task:turn:session-a:1",
      title: "task:turn:session-a:1",
      runtime_lane: "single_agent_task",
      latest_event_type: "task_run_lifecycle_waiting_executor",
      is_live: true,
      display_bucket: "live",
    });

    expect(runtimeWorkProjectionFromMonitorItem(run)).toMatchObject({
      workKind: "chat_turn_runtime",
      displayTypeLabel: "会话运行",
      primaryRunId: "taskrun:turn:session-a:1:abc",
      title: "会话运行",
    });
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
