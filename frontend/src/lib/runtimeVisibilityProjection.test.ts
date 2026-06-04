import { describe, expect, it } from "vitest";

import { projectRuntimeStreamEvent } from "./runtimeVisibilityProjection";

describe("runtimeVisibilityProjection", () => {
  it("projects stream reconnects as calm continuation feedback", () => {
    expect(projectRuntimeStreamEvent("stream_reconnecting", {
      attempt: 1,
      max_attempts: 5,
    })).toMatchObject({
      stageStatus: "正在续接当前运行",
      activityTitle: "正在续接当前运行",
      activityDetail: "连接短暂中断，已保留当前进度。第 1/5 次尝试。",
      level: "running",
    });

    expect(projectRuntimeStreamEvent("stream_reconnected", {})).toMatchObject({
      stageStatus: "已接回当前运行",
      activityDetail: "后续进度会继续在这里同步。",
      level: "running",
    });

    expect(projectRuntimeStreamEvent("stream_reconnect_failed", {})).toMatchObject({
      stageStatus: "续接暂未完成",
      activityTitle: "需要重新接回会话",
      level: "warning",
    });
  });

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
        run_id: "turnrun:session-1:1",
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
        run_id: "taskrun:1",
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

    expect(projection.stageStatus).toBe("权限已检查");
    expect(projection.progressEntry).toBeUndefined();
  });

  it("projects runtime loop tool requests as visible tool flow entries", () => {
    const requested = projectRuntimeStreamEvent("harness_loop_event", {
      event: {
        event_id: "rtevt:tool-request",
        run_id: "taskrun:1",
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

    expect(requested.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "write_file",
      statusText: "写入中",
      taskRunId: "taskrun:1",
    });
  });

  it("does not project legacy runtime loop tool result events", () => {
    const projection = projectRuntimeStreamEvent("harness_loop_event", {
      event: {
        event_id: "rtevt:tool-result",
        run_id: "taskrun:1",
        event_type: "tool_result_received",
        created_at: 21,
        payload: {
          observation: {
            observation_id: "rtobs:tool-result",
            source: "tool:terminal",
            payload: {
              tool_name: "terminal",
              error: "Blocked: command references an absolute path outside the sandbox workspace.",
              tool_args: { command: "cd \"D:\\AI应用\\langchain-agent\"; python -m pytest backend/tests/" },
            },
          },
        },
      },
    });

    expect(projection).toEqual({});
  });

  it("projects single-agent turn tool admission and observation as visible tool flow entries", () => {
    const requested = projectRuntimeStreamEvent("model_action_admission", {
      event: {
        event_id: "rtevt:turn-tool-request",
        run_id: "turnrun:turn:session-a:7",
        event_type: "model_action_admission_checked",
        created_at: 20,
        payload: {
          model_action_request: {
            action_type: "tool_call",
            public_progress_note: "已发起工具调用，正在等待工具返回：write_file。",
            tool_call: {
              name: "write_file",
              args: { path: "storage/task_environments/general/workspace/artifacts/wuxia_rpg/templates/index.html" },
            },
          },
          admission: {
            decision: "allow",
          },
        },
      },
    });
    const returned = projectRuntimeStreamEvent("turn_tool_observation_recorded", {
      event: {
        event_id: "rtevt:turn-tool-result",
        run_id: "turnrun:turn:session-a:7",
        event_type: "turn_tool_observation_recorded",
        created_at: 21,
        payload: {
          preview: {
            tool_observation: {
              observation_id: "toolobs:1",
              caller_ref: "turnrun:turn:session-a:7",
              tool_name: "write_file",
              status: "ok",
              text: "Write succeeded: storage/task_environments/general/workspace/artifacts/wuxia_rpg/templates/index.html",
              result_envelope: {
                tool_args: { path: "storage/task_environments/general/workspace/artifacts/wuxia_rpg/templates/index.html" },
              },
              structured_payload: {
                artifact_refs: [{
                  path: "storage/task_environments/general/workspace/artifacts/wuxia_rpg/templates/index.html",
                  kind: "file",
                }],
              },
            },
          },
        },
      },
    });

    expect(requested).toMatchObject({
      stageStatus: "正在写入 storage/task_environments/general/workspace/artifacts/wuxia_rpg/templates/index.html",
      activityTitle: "正在写入",
      activityDetail: "storage/task_environments/general/workspace/artifacts/wuxia_rpg/templates/index.html",
    });
    expect(requested.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "write_file",
      runId: "turnrun:turn:session-a:7",
      statusText: "写入中",
    });
    expect(returned).toMatchObject({
      activityTitle: "写入完成",
      activityDetail: "storage/task_environments/general/workspace/artifacts/wuxia_rpg/templates/index.html",
    });
    expect(returned.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "write_file",
      runId: "turnrun:turn:session-a:7",
      statusText: "已完成",
      artifacts: [{ label: "产物", path: "storage/task_environments/general/workspace/artifacts/wuxia_rpg/templates/index.html" }],
    });
  });

  it("projects direct public tool observation events from single-agent turns", () => {
    const projection = projectRuntimeStreamEvent("tool_observation", {
      tool_observation: {
        observation_id: "toolobs:direct",
        caller_ref: "turnrun:turn:session-a:8",
        tool_name: "read_file",
        status: "ok",
        text: "Read succeeded",
        result_envelope: {
          tool_args: { path: "docs/plan.md" },
        },
        structured_payload: {
          observed_paths: ["docs/plan.md"],
        },
      },
    });

    expect(projection).toMatchObject({
      activityTitle: "读取完成",
      activityDetail: "docs/plan.md",
    });
    expect(projection.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "read_file",
      runId: "turnrun:turn:session-a:8",
      artifacts: [{ label: "产物", path: "docs/plan.md" }],
    });
  });

  it("hides sandbox boundary command failures from public progress", () => {
    const projection = projectRuntimeStreamEvent("turn_tool_observation_recorded", {
      event: {
        event_id: "rtevt:sandbox-boundary",
        run_id: "turnrun:turn:session-a:9",
        event_type: "turn_tool_observation_recorded",
        created_at: 22,
        payload: {
          preview: {
            tool_observation: {
              observation_id: "toolobs:sandbox-boundary",
              caller_ref: "turnrun:turn:session-a:9",
              tool_name: "terminal",
              status: "error",
              error: "Blocked: command references an absolute path outside the sandbox workspace.",
              text: "Blocked: command references an absolute path outside the sandbox workspace.",
              result_envelope: {
                tool_name: "terminal",
                tool_args: {
                  command: "cd \"D:\\AI应用\\langchain-agent\"; python -m pytest backend/tests/",
                },
                structured_error: {
                  message: "Blocked: command references an absolute path outside the sandbox workspace.",
                },
              },
            },
          },
        },
      },
    });

    expect(projection).toEqual({});
  });

  it("projects terminal commands as Codex-style running activity", () => {
    const projection = projectRuntimeStreamEvent("harness_loop_event", {
      event: {
        event_id: "rtevt:terminal",
        run_id: "taskrun:1",
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
        run_id: "taskrun:turn:session-1:1:abc",
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
        run_id: "turnrun:session-1:1",
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
      stageStatus: "处理已开始",
      activityTitle: "处理已开始",
      activityDetail: "重构主会话监控",
      level: "running",
    });
    expect(started.progressEntry).toMatchObject({
      kind: "task_order",
      taskRunId: "taskrun:turn:session-1:1:abc",
    });
    expect(waiting).toMatchObject({
      stageStatus: "继续在后台处理",
      activityDetail: "任务已切到后台继续执行。",
      level: "waiting",
    });
    expect(waiting.progressEntry).toMatchObject({
      title: "继续在后台处理",
      body: "任务已切到后台继续执行。",
      level: "waiting",
      taskRunId: "taskrun:turn:session-1:1:abc",
    });
  });

  it("keeps formal task run starts visible even when runtime metadata is present", () => {
    const projection = projectRuntimeStreamEvent("harness_run_started", {
      task_run: {
        task_run_id: "taskrun:visible-formal-task",
        execution_runtime_kind: "single_agent_turn",
        status: "running",
      },
      event: {
        event_id: "rtevt:formal-task-start",
        run_id: "taskrun:visible-formal-task",
        created_at: 32,
        payload: {
          contract: {
            user_visible_goal: "执行正式后台任务",
          },
        },
      },
    });

    expect(projection).toMatchObject({
      stageStatus: "处理已开始",
      activityTitle: "处理已开始",
      activityDetail: "执行正式后台任务",
      level: "running",
    });
    expect(projection.progressEntry).toMatchObject({
      kind: "task_order",
      taskRunId: "taskrun:visible-formal-task",
    });
  });

  it("ignores chat turn runtime start because it is an internal trace", () => {
    const projection = projectRuntimeStreamEvent("harness_run_started", {
      turn_run: {
        turn_run_id: "turnrun:session-1:1",
        execution_runtime_kind: "single_agent_turn",
        status: "running",
      },
      event: {
        event_id: "rtevt:turn-start",
        run_id: "turnrun:session-1:1",
        created_at: 30,
        payload: {},
      },
    });

    expect(projection).toEqual({});
    expect(projection.progressEntry).toBeUndefined();
  });

  it("keeps blocked turn reasons out of terminal receipt progress", () => {
    const reason = "当前环境的写入权限不足，且创建文件的工具不可见，无法在沙盒中创建 HTML 文件。";
    const projection = projectRuntimeStreamEvent("agent_turn_terminal", {
      event: {
        event_id: "rtevt:blocked",
        run_id: "turnrun:session-1:2",
        event_type: "agent_turn_blocked",
        created_at: 42,
        payload: {
          status: "blocked",
          terminal_reason: reason,
          turn_run: {
            turn_run_id: "turnrun:session-1:2",
            status: "blocked",
          },
        },
      },
    });

    expect(projection).toMatchObject({
      stageStatus: "处理失败",
      activityTitle: "处理失败",
      activityDetail: "详情已写入会话。",
      level: "error",
    });
    expect(projection.progressEntry).toBeUndefined();
  });

  it("keeps stream error detail in the assistant message progress, not the global status detail", () => {
    const projection = projectRuntimeStreamEvent("error", {
      error: "当前环境的写入权限不足。",
      code: "agent_blocked",
    });

    expect(projection.activityTitle).toBe("处理失败");
    expect(projection.activityDetail).toBe("详情已写入会话。");
    expect(projection.progressEntry).toMatchObject({
      kind: "terminal",
      statusText: "失败",
      body: "当前环境的写入权限不足。",
    });
  });

  it("does not expose internal answer source names in completion progress", () => {
    const projection = projectRuntimeStreamEvent("done", {
      answer_source: "harness.loop.single_agent.respond",
    });

    const visibleText = [projection.activityDetail, projection.progressEntry?.title, projection.progressEntry?.body].join(" ");

    expect(projection.progressEntry).toBeUndefined();
    expect(visibleText).not.toContain("回答已生成并写回会话");
    expect(visibleText).not.toContain("harness");
    expect(visibleText).not.toContain("single_agent");
    expect(visibleText).not.toContain(".respond");
  });
});
