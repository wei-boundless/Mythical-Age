import { describe, expect, it } from "vitest";

import type { GlobalRuntimeMonitorItem } from "@/lib/api";
import { monitorEventLabel, monitorProgressLabel, statusLabel } from "./runtimeMonitorFormat";

function item(patch: Partial<GlobalRuntimeMonitorItem>): GlobalRuntimeMonitorItem {
  return {
    task_run_id: "taskrun:turn:session-a:1:abc",
    session_id: "session-a",
    task_id: "task:turn:session-a:1",
    execution_runtime_kind: "single_agent_task",
    title: "task:turn:session-a:1",
    status: "running",
    terminal_reason: "",
    started_at: 1,
    duration_seconds: 1,
    elapsed_seconds: 1,
    lifecycle: "running",
    bucket: "running",
    resource_class: "dynamic",
    latest_event_type: "step_summary_recorded",
    latest_event_at: 2,
    event_count: 2,
    graph_id: "",
    active_node_id: "",
    project_id: "",
    project_title: "",
    project_runtime_status: null,
    has_graph_run: false,
    route: { kind: "chat_turn_runtime", session_id: "session-a", task_run_id: "taskrun:turn:session-a:1:abc" },
    ...patch,
  };
}

describe("runtimeMonitorFormat", () => {
  it("uses user-facing labels for waiting and runtime event states", () => {
    expect(statusLabel("waiting_executor")).toBe("等待继续");
    expect(monitorEventLabel("task_run_lifecycle_waiting_executor")).toBe("等待继续");
    expect(monitorEventLabel("step_summary_recorded")).toBe("进展已更新");
    expect(monitorEventLabel("unknown_internal_event")).toBe("进展同步");
  });

  it("projects monitor progress without raw runtime terms", () => {
    const label = monitorProgressLabel(item({
      latest_public_progress_note: "系统已为当前任务步骤装配 runtime packet，并交给 agent 判断下一步。",
    }));

    expect(label).toBe("正在整理上下文，准备继续处理。");
    expect(label).not.toContain("runtime packet");
    expect(label).not.toContain("agent");
    expect(label).not.toContain("装配");
  });

  it("does not use internal identifiers as display text", () => {
    expect(monitorProgressLabel(item({
      latest_public_progress_note: "taskrun:turn:session-a:1:abc",
      latest_step_summary: "",
      summary: "",
      latest_event_type: "task_run_lifecycle_started",
    }))).toBe("处理已开始");
  });
});
