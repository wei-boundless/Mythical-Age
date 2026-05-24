import { describe, expect, it } from "vitest";

import { projectRuntimeStreamEvent } from "./runtimeVisibilityProjection";

describe("runtimeVisibilityProjection", () => {
  it("projects task order binding as the task flow anchor", () => {
    const projection = projectRuntimeStreamEvent("task_order_projection", {
      authority: "task_system.task_order_projection",
      task_order: {
        order_id: "order:specific_task:abcdef123456",
        order_kind: "specific_task",
        task_id: "task.dev.frontend_ui",
        objective: "优化会话任务状态展示",
      },
      task_order_run: {
        run_id: "orderrun:abcdef123456",
        created_at: 10,
      },
      execution_channel: {
        channel_id: "execchan:abcdef123456",
      },
      task_execution_envelope: {
        envelope_id: "taskenv:abcdef123456",
      },
    });

    expect(projection.taskOrderProjection?.task_order?.order_id).toBe("order:specific_task:abcdef123456");
    expect(projection.progressEntry).toMatchObject({
      kind: "task_order",
      statusText: "已绑定",
      title: "已绑定任务订单",
      level: "running",
    });
    expect(projection.progressEntry?.meta?.map((item) => item.label)).toEqual(["类型", "任务"]);
  });

  it("keeps permission gate diagnostics out of the user-visible task flow", () => {
    const projection = projectRuntimeStreamEvent("runtime_loop_event", {
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
    const requested = projectRuntimeStreamEvent("runtime_loop_event", {
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
    const returned = projectRuntimeStreamEvent("runtime_loop_event", {
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
      statusText: "请求中",
      taskRunId: "taskrun:1",
    });
    expect(returned.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "write_file",
      statusText: "已返回",
      taskRunId: "taskrun:1",
    });
    expect(returned.progressEntry?.artifacts?.[0]?.path).toBe("docs/plan.md");
  });

  it("projects direct stream tool events for legacy stream adapters", () => {
    const started = projectRuntimeStreamEvent("tool_start", {
      tool: "read_file",
      input: "frontend/src/components/chat/ChatMessage.tsx",
    });
    const ended = projectRuntimeStreamEvent("tool_end", {
      tool: "read_file",
      output: "ok",
    });

    expect(started.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "read_file",
      statusText: "请求中",
    });
    expect(ended.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "read_file",
      statusText: "已返回",
    });
  });
});
