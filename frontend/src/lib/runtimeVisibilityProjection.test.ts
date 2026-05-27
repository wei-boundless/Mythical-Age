import { describe, expect, it } from "vitest";

import { projectRuntimeStreamEvent } from "./runtimeVisibilityProjection";

describe("runtimeVisibilityProjection", () => {
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
      title: "正在读取 frontend/src/components/chat/ChatMessage.tsx",
      statusText: "读取中",
    });
    expect(ended.progressEntry).toMatchObject({
      kind: "tool",
      toolName: "read_file",
      statusText: "已完成",
    });
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
});
