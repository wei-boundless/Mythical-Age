import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RunTaskLane } from "./RunTaskLane";
import type { RunMonitorSignal } from "@/lib/run-monitor/types";

function signal(patch: Partial<RunMonitorSignal>): RunMonitorSignal {
  const signalId = patch.signal_id || patch.task_run_id || "taskrun:test";
  return {
    authority: "runtime_monitor.signal",
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

  it("opens action menus upward for the bottom monitor rows", () => {
    const html = renderLane([
      signal({ signal_id: "taskrun:1", title: "任务一", actions: [{ action: "stop_task", enabled: true, label: "停止" }] }),
      signal({ signal_id: "taskrun:2", title: "任务二", actions: [{ action: "stop_task", enabled: true, label: "停止" }] }),
      signal({ signal_id: "taskrun:3", title: "任务三", actions: [{ action: "stop_task", enabled: true, label: "停止" }] }),
    ]);

    expect(html).toContain("run-monitor-action-menu--down");
    expect(html.match(/run-monitor-action-menu--up/g)?.length).toBe(2);
  });

  it("keeps a single monitor action menu opening downward", () => {
    const html = renderLane([
      signal({ signal_id: "taskrun:1", title: "任务一", actions: [{ action: "stop_task", enabled: true, label: "停止" }] }),
    ]);

    expect(html).toContain("run-monitor-action-menu--down");
    expect(html).not.toContain("run-monitor-action-menu--up");
  });
});
