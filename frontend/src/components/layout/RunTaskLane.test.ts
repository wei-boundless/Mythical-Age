import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RunTaskLane } from "./RunTaskLane";
import type { RunMonitorSignal } from "@/lib/run-monitor/types";

function signal(patch: Partial<RunMonitorSignal>): RunMonitorSignal {
  const signalId = patch.signal_id || patch.task_run_id || "taskrun:test";
  return {
    authority: "run_monitor.signal",
    signal_id: signalId,
    source_kind: "task_run",
    work_kind: "agent_task",
    state: "active",
    priority: 100,
    title: "运行任务",
    line: "正在处理",
    detail: "运行 1s",
    status: "running",
    lifecycle: "running",
    bucket: "running",
    activity_state: "running",
    activity_label: "运行中",
    is_running: true,
    is_waiting: false,
    is_resumable: false,
    is_interruptible: true,
    control_reason: "",
    tone: "active",
    activity: {},
    control_capability: {},
    session_id: "session:test",
    task_run_id: signalId,
    task_instance_id: signalId,
    graph_run_id: "",
    graph_id: "",
    navigation_target: {},
    timestamps: { started_at: 1, updated_at: 2, last_activity_at: 2, elapsed_seconds: 1 },
    raw_refs: {},
    actions: [],
    ...patch,
  };
}

function renderLane(signals: RunMonitorSignal[]) {
  return renderToStaticMarkup(
    React.createElement(RunTaskLane, {
      actionLoading: "",
      loading: false,
      onAction: () => undefined,
      onOpen: () => undefined,
      signals,
    }),
  );
}

function renderLaneWithLogs(signals: RunMonitorSignal[]) {
  return renderToStaticMarkup(
    React.createElement(RunTaskLane, {
      actionLoading: "",
      loading: false,
      onAction: () => undefined,
      onOpen: () => undefined,
      onOpenLog: () => undefined,
      signals,
    }),
  );
}

describe("RunTaskLane", () => {
  it("does not let a stale activity signal render as running", () => {
    const html = renderLane([
      signal({
        signal_id: "taskrun:stale",
        title: "停滞任务",
        activity_state: "stale",
        activity_label: "",
        is_running: true,
      }),
    ]);

    expect(html).toContain("等待检查");
    expect(html).not.toContain("<strong>运行中</strong>");
    expect(html).toContain("run-monitor-task--stale");
  });

  it("orders stale attention before ordinary running signals", () => {
    const html = renderLane([
      signal({ signal_id: "taskrun:running", title: "真实运行" }),
      signal({
        signal_id: "taskrun:stale",
        title: "停滞任务",
        activity_state: "stale",
        activity_label: "",
        is_running: true,
      }),
    ]);

    expect(html.indexOf("停滞任务")).toBeLessThan(html.indexOf("真实运行"));
  });

  it("renders monitor actions inline inside each task row", () => {
    const html = renderLane([
      signal({ signal_id: "taskrun:1", title: "任务一", actions: [{ action: "stop_task", enabled: true, label: "停止" }] }),
      signal({ signal_id: "taskrun:2", title: "任务二", actions: [{ action: "close_runtime", enabled: true, label: "关闭运行" }] }),
    ]);

    expect(html).toContain("run-monitor-task__actions");
    expect(html).toContain("停止");
    expect(html).toContain("关闭运行");
    expect(html).not.toContain("run-monitor-action-menu");
  });

  it("keeps navigation actions out of the task lane action group", () => {
    const html = renderLane([
      signal({
        signal_id: "taskrun:1",
        title: "任务一",
        actions: [
          { action: "open", enabled: true, label: "打开" },
          { action: "inspect", enabled: true, label: "检查" },
          { action: "delete_record", enabled: true, label: "删除记录" },
        ],
      }),
    ]);

    expect(html).toContain("删除记录");
    expect(html).not.toContain(">打开</button>");
    expect(html).not.toContain(">检查</button>");
  });

  it("shows scoped runtime log entry when a task run id is present", () => {
    const html = renderLaneWithLogs([
      signal({ signal_id: "taskrun:1", task_run_id: "taskrun:1", title: "任务一" }),
    ]);

    expect(html).toContain("日志");
    expect(html).toContain("run-monitor-task__actions");
  });

  it("renders restart recovery reason as public status text", () => {
    const html = renderLane([
      signal({
        signal_id: "taskrun:restart",
        title: "运行暂停已停止",
        line: "",
        detail: "runtime_cell_missing_after_restart",
        status: "stopped",
        activity_state: "stopped",
        activity_label: "",
        is_running: false,
      }),
    ]);

    expect(html).toContain("连接恢复后需要重新接续运行");
    expect(html).not.toContain("runtime_cell_missing_after_restart");
  });
});
