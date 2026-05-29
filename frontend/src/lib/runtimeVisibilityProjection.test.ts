import { describe, expect, it } from "vitest";

import { projectRuntimeStreamEvent } from "./runtimeVisibilityProjection";

describe("runtimeVisibilityProjection", () => {
  it("filters internal runtime step summaries out of user-visible progress", () => {
    for (const step of [
      "turn_started",
      "runtime_packet_compiled",
      "model_action_received",
      "action_admission_checked",
      "bounded_observation_recorded",
    ]) {
      expect(projectRuntimeStreamEvent("runtime_step_summary", {
        step,
        status: "running",
        summary: `internal ${step}`,
      })).toEqual({});
    }
  });

  it("projects public progress notes from runtime step summaries", () => {
    const projection = projectRuntimeStreamEvent("runtime_step_summary", {
      step: "model_action_received",
      status: "running",
      summary: "旧的内部摘要",
      event: {
        event_id: "rtevt:progress",
        task_run_id: "turnrun:session-1:1",
        created_at: 40,
        payload: {
          public_progress_note: "我先核对当前文件状态，确认可以从断点继续。",
          agent_brief_output: "已定位入口文件。",
        },
      },
    });

    expect(projection.progressEntry).toMatchObject({
      body: "我先核对当前文件状态，确认可以从断点继续。",
      publicNote: "我先核对当前文件状态，确认可以从断点继续。",
      agentBrief: "已定位入口文件。",
      statusText: "running",
    });
    expect(projection.activityDetail).toBe("我先核对当前文件状态，确认可以从断点继续。");
  });

  it("keeps permission gate diagnostics out of the user-visible task flow", () => {
    const projection = projectRuntimeStreamEvent("harness_loop_event", {
      event: {
        event_id: "rtevt:gate",
        task_run_id: "taskrun:1",
        event_type: "operation_gate_checked",
        created_at: 19,
        payload: {
          gate: {
            allowed: true,
            decision: "allow",
            operation_id: "op.model_response",
            reason: "operation allowed by adopted resource policy",
          },
        },
      },
    });

    expect(projection.stageStatus).toBe("准备执行");
    expect(projection.progressEntry).toBeUndefined();
  });

  it("projects runtime loop tool request and result as tool flow entries", () => {
    const requested = projectRuntimeStreamEvent("harness_loop_event", {
      event: {
        event_id: "rtevt:tool-request",
        task_run_id: "taskrun:1",
        event_type: "tool_call_requested",
        created_at: 20,
        payload: {
          action_request: {
            request_id: "rtact:taskrun:1:tool",
            operation_id: "operation.write_file",
            payload: {
              tool_name: "write_file",
              tool_call: { name: "write_file", args: { path: "docs/plan.md" } },
            },
          },
        },
      },
    });
    const returned = projectRuntimeStreamEvent("harness_loop_event", {
      event: {
        event_id: "rtevt:tool-result",
        task_run_id: "taskrun:1",
        event_type: "tool_result_received",
        created_at: 21,
        payload: {
          observation: {
            observation_id: "rtobs:tool-result",
            source: "tool:write_file",
            payload: {
              tool_name: "write_file",
              result: "wrote docs/plan.md",
              result_chars: 18,
              observed_paths: ["docs/plan.md"],
            },
          },
        },
      },
    });

    expect(requested.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "write_file",
      statusText: "写入中",
      taskRunId: "taskrun:1",
    });
    expect(returned.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "write_file",
      statusText: "已完成",
      taskRunId: "taskrun:1",
    });
    expect(returned.progressEntry?.artifacts?.[0]?.path).toBe("docs/plan.md");
  });

  it("projects terminal commands as Codex-style running activity", () => {
    const projection = projectRuntimeStreamEvent("harness_loop_event", {
      event: {
        event_id: "rtevt:terminal",
        task_run_id: "taskrun:1",
        event_type: "tool_call_requested",
        created_at: 20,
        payload: {
          action_request: {
            request_id: "rtact:terminal",
            operation_id: "operation.terminal",
            payload: {
              tool_name: "terminal",
              tool_call: { name: "terminal", args: { command: "npm test -- --run src/lib/runtimeVisibilityProjection.test.ts" } },
            },
          },
        },
      },
    });

    expect(projection).toMatchObject({
      stageStatus: "正在运行 npm test -- --run src/lib/runtimeVisibilityProjection.test.ts",
      activityTitle: "正在运行",
      activityDetail: "npm test -- --run src/lib/runtimeVisibilityProjection.test.ts",
    });
    expect(projection.progressEntry).toMatchObject({
      kind: "tool",
      title: "正在运行 npm test -- --run src/lib/runtimeVisibilityProjection.test.ts",
      statusText: "运行中",
      toolName: "terminal",
    });
    expect(projection.progressEntry?.meta?.find((item) => item.label === "目标")?.value).toBe("npm test -- --run src/lib/runtimeVisibilityProjection.test.ts");
  });

  it("projects task handoff events into natural main-chat progress", () => {
    const started = projectRuntimeStreamEvent("harness_run_started", {
      task_run: {
        task_run_id: "taskrun:turn:session-1:1:abc",
        status: "running",
      },
      event: {
        event_id: "rtevt:start",
        task_run_id: "taskrun:turn:session-1:1:abc",
        created_at: 30,
        payload: {
          contract: {
            user_visible_goal: "重构主会话监控",
          },
        },
      },
    });
    const waiting = projectRuntimeStreamEvent("agent_turn_terminal", {
      event: {
        event_id: "rtevt:terminal",
        task_run_id: "turnrun:session-1:1",
        created_at: 31,
        payload: {
          status: "task_executor_scheduled",
          terminal_reason: "task_executor_scheduled",
          task_run: {
            task_run_id: "taskrun:turn:session-1:1:abc",
            status: "running",
          },
        },
      },
    });

    expect(started).toMatchObject({
      stageStatus: "正在整理上下文",
      activityTitle: "正在整理上下文",
      activityDetail: "准备判断下一步",
      level: "running",
    });
    expect(started.progressEntry).toBeUndefined();
    expect(waiting).toMatchObject({
      stageStatus: "继续在后台处理",
      level: "waiting",
    });
    expect(waiting.progressEntry).toMatchObject({
      kind: "terminal",
      statusText: "等待",
      taskRunId: "taskrun:turn:session-1:1:abc",
    });
  });

  it("does not project chat turn runtime start as a formal task", () => {
    const projection = projectRuntimeStreamEvent("harness_run_started", {
      task_run: {
        task_run_id: "turnrun:session-1:1",
        execution_runtime_kind: "single_agent_turn",
        status: "running",
      },
      event: {
        event_id: "rtevt:turn-start",
        task_run_id: "turnrun:session-1:1",
        created_at: 30,
        payload: {},
      },
    });

    expect(projection).toMatchObject({
      stageStatus: "正在整理上下文",
      activityTitle: "正在整理上下文",
      activityDetail: "准备判断下一步",
      level: "running",
    });
    expect(projection.progressEntry).toBeUndefined();
  });

  it("does not expose internal answer source names in completion progress", () => {
    const projection = projectRuntimeStreamEvent("done", {
      answer_source: "harness.loop.single_agent.respond",
    });

    const visibleText = [
      projection.activityDetail,
      projection.progressEntry?.title,
      projection.progressEntry?.body,
    ].join(" ");

    expect(projection.progressEntry).toMatchObject({
      kind: "terminal",
      statusText: "完成",
      body: "回答已生成并写回会话",
    });
    expect(visibleText).not.toContain("harness");
    expect(visibleText).not.toContain("single_agent");
    expect(visibleText).not.toContain(".respond");
  });
});
