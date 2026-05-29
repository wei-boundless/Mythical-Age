import { describe, expect, it } from "vitest";

import type { GlobalRuntimeMonitorItem } from "./api";
import { runtimeWorkProjectionFromLiveMonitor, runtimeWorkProjectionFromMonitorItem, visibleRuntimeMonitorItems } from "./runtimeWorkProjection";

function item(patch: Partial<GlobalRuntimeMonitorItem>): GlobalRuntimeMonitorItem {
  return {
    task_run_id: "taskrun:1",
    session_id: "session:1",
    task_id: "task:general",
    execution_runtime_kind: "single_agent_turn",
    title: "General run",
    status: "running",
    terminal_reason: "",
    created_at: 1,
    updated_at: 2,
    started_at: 1,
    ended_at: null,
    duration_seconds: 1,
    elapsed_seconds: 1,
    lifecycle: "running",
    bucket: "running",
    resource_class: "dynamic",
    latest_event_type: "task_run_started",
    latest_event_at: 2,
    event_count: 1,
    graph_run_id: "",
    graph_harness_config_id: "",
    graph_id: "",
    active_node_id: "",
    project_id: "",
    project_title: "",
    project_runtime_status: null,
    has_graph_run: false,
    route: { kind: "chat_turn_runtime", session_id: "session:1", task_run_id: "taskrun:1" },
    ...patch,
  };
}

describe("runtimeWorkProjection", () => {
  it("shows task graph runs as first-class runtime work", () => {
    const monitorItem = item({
      has_graph_run: true,
      graph_run_id: "grun:main",
      graph_harness_config_id: "ghcfg:main",
      graph_id: "graph:main",
      title: "实现五关 roguelike",
      route: { kind: "task_graph_run", session_id: "session:1", task_run_id: "taskrun:1", graph_id: "graph:main", graph_run_id: "grun:main" },
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
      route: { kind: "agent_runtime_run", session_id: "session:1", task_run_id: "taskrun:agent-runtime" },
    });
    const child = item({
      task_run_id: "taskrun:child",
      graph_id: "graph:main",
      has_graph_run: true,
      graph_run_id: "grun:child",
      graph_harness_config_id: "ghcfg:main",
      bucket: "diagnostics",
      route: { kind: "task_graph_run", session_id: "session:1", task_run_id: "taskrun:child", graph_id: "graph:main", graph_run_id: "grun:child" },
    });

    const visible = visibleRuntimeMonitorItems({
      authority: "test",
      summary: { total: 2, running: 1, waiting: 0, completed: 0, failed: 0, diagnostics: 1 },
      buckets: { running: [phaseRun], completed: [], failed: [], diagnostics: [child] },
      task_runs: [phaseRun, child],
      updated_at: 1,
    });

    expect(visible.map((entry) => entry.task_run_id)).toEqual(["taskrun:agent-runtime", "taskrun:child"]);
    expect(runtimeWorkProjectionFromMonitorItem(phaseRun).workKind).toBe("agent_runtime_run");
  });

  it("only exposes backend bucketed monitor items", () => {
    const liveWaiting = item({
      task_run_id: "taskrun:waiting",
      status: "waiting_executor",
    });
    const failedHistory = item({
      task_run_id: "taskrun:failed",
      status: "failed",
      lifecycle: "failed",
      bucket: "failed",
      resource_class: "static",
    });
    const completedHistory = item({
      task_run_id: "taskrun:completed",
      status: "completed",
      lifecycle: "completed",
      bucket: "completed",
      resource_class: "static",
    });

    const visible = visibleRuntimeMonitorItems({
      authority: "test",
      summary: { total: 3, running: 1, waiting: 1, completed: 1, failed: 1 },
      buckets: {
        running: [liveWaiting],
        completed: [completedHistory],
        failed: [failedHistory],
        diagnostics: [],
      },
      task_runs: [failedHistory, liveWaiting, completedHistory],
      updated_at: 1,
    });

    expect(visible.map((entry) => entry.task_run_id)).toEqual(["taskrun:waiting", "taskrun:completed", "taskrun:failed"]);
  });

  it("keeps bucketed blocked, completed, and failed task runs visible by monitor page order", () => {
    const blockedTurn = item({
      task_run_id: "turnrun:blocked",
      status: "blocked",
      latest_event_type: "agent_turn_blocked",
      is_live: false,
      bucket: "diagnostics",
      lifecycle: "action_required",
      resource_class: "static",
    });
    const failedRun = item({ task_run_id: "taskrun:failed", status: "failed", is_live: false, bucket: "failed" });
    const completedRun = item({ task_run_id: "taskrun:completed", status: "completed", is_live: false, bucket: "completed" });

    const visible = visibleRuntimeMonitorItems({
      authority: "test",
      summary: { total: 0, running: 0, waiting: 0, completed: 0, failed: 0 },
      buckets: {
        running: [],
        completed: [completedRun],
        failed: [failedRun],
        diagnostics: [blockedTurn],
      },
      task_runs: [blockedTurn, failedRun, completedRun],
      updated_at: 1,
    });

    expect(visible.map((entry) => entry.task_run_id)).toEqual(["taskrun:completed", "taskrun:failed", "turnrun:blocked"]);
  });

  it("projects single agent task runs as long tasks with latest step summary", () => {
    const run = item({
      task_run_id: "taskrun:single-agent",
      execution_runtime_kind: "single_agent_task",
      latest_step_summary: "系统已执行工具并把观察回灌给 agent。",
      route: { kind: "agent_runtime_run", session_id: "session:1", task_run_id: "taskrun:single-agent" },
    });

    expect(runtimeWorkProjectionFromMonitorItem(run)).toMatchObject({
      workKind: "agent_runtime_run",
      displayTypeLabel: "Agent 运行",
      latestStepSummary: "系统已执行工具并把观察回灌给 agent。",
    });
  });

  it("keeps chat-scoped task runs attached to their conversation even when they use task runtime mode", () => {
    const run = item({
      task_run_id: "taskrun:turn:session-a:1:abc",
      session_id: "session-a",
      task_id: "task:turn:session-a:1",
      title: "task:turn:session-a:1",
      execution_runtime_kind: "single_agent_task",
      latest_event_type: "task_run_lifecycle_waiting_executor",
      route: { kind: "chat_turn_runtime", session_id: "session-a", task_run_id: "taskrun:turn:session-a:1:abc" },
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
      has_graph_run: false,
      loop_state: {},
      agent_runtime_phase_summary: null,
      updated_at: 1,
    })).toBeNull();
  });
});
