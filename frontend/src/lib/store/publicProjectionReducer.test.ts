import { describe, expect, it } from "vitest";

import { getDefaultState } from "./core";
import { reduceStreamEvent, startStreamingTurn } from "./events";

describe("public projection reducer contract", () => {
  it("renders body only from explicit model body slot in a public projection envelope", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      public_projection_envelope: {
        authority: "harness.public_projection.v1",
        projection_id: "publicproj:body",
        lifecycle: "running",
        source_authority: "model",
        surface: "assistant_body",
        items: [
          {
            item_id: "body:1",
            kind: "stage_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "I am checking the projection chain.",
            state: "running",
          },
        ],
      },
    });

    expect(transition.state.messages.at(-1)?.content).toBe("I am checking the projection chain.");
  });

  it("fails closed for body-looking projection items without explicit slot", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      public_projection_envelope: {
        authority: "harness.public_projection.v1",
        projection_id: "publicproj:no-slot",
        lifecycle: "running",
        source_authority: "model",
        surface: "assistant_body",
        items: [
          {
            item_id: "legacy-body",
            kind: "final_summary",
            surface: "assistant_body",
            source_authority: "model",
            text: "Legacy body must not render.",
            state: "done",
          },
        ],
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.runtimePublicTimelineDraft).toEqual([]);
  });

  it("does not use done content as an assistant body fallback", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "Done content must not become visible body.",
      answer_channel: "conversation",
      answer_source: "model",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.stageStatus).toBe("完成");
  });

  it("ignores legacy public timeline delta without an envelope", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_step_summary", {
      public_timeline_delta: [
        {
          item_id: "body:legacy",
          kind: "final_summary",
          slot: "body",
          surface: "assistant_body",
          source_authority: "model",
          text: "Legacy delta must not render.",
          state: "done",
        },
      ],
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.runtimePublicTimelineDraft).toEqual([]);
  });

  it("still attaches task projection carried by a raw monitor event", () => {
    let transition = startStreamingTurn(getDefaultState(), "run task");
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_status", {
      task_projection_delta: {
        authority: "harness.runtime.single_agent_task_projection.v1",
        projection_id: "projection:taskrun:test",
        task_run_id: "taskrun:test",
        status: "running",
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.runtimeAttachments?.[0]?.task_projection).toMatchObject({
      task_run_id: "taskrun:test",
      status: "running",
    });
  });

  it("keeps public timeline feedback alongside task projection attachments", () => {
    let transition = startStreamingTurn(getDefaultState(), "run task");
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_status", {
      public_projection_envelope: {
        authority: "harness.public_projection.v1",
        projection_id: "publicproj:task-feedback",
        lifecycle: "running",
        source_authority: "model",
        surface: "status_bar",
        anchor: {
          task_run_id: "taskrun:feedback",
          turn_id: "turn:session:feedback:1",
        },
        task_projection: {
          authority: "harness.runtime.single_agent_task_projection.v1",
          projection_id: "projection:taskrun:feedback",
          task_run_id: "taskrun:feedback",
          status: "running",
        },
        items: [
          {
            item_id: "observation:task-feedback",
            kind: "observation_report",
            slot: "status",
            surface: "status_bar",
            source_authority: "model",
            title: "观察反馈",
            detail: "已确认上一阶段结果，可以继续推进。",
            state: "done",
          },
        ],
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.runtimePublicTimelineDraft?.[0]?.detail).toBe("已确认上一阶段结果，可以继续推进。");
    expect(assistant?.runtimeAttachments?.[0]?.task_projection?.task_run_id).toBe("taskrun:feedback");
    expect(assistant?.runtimeAttachments?.[0]?.public_timeline?.[0]?.detail).toBe("已确认上一阶段结果，可以继续推进。");
  });

  it("uses thinking stage status for tool-window projection without creating body text", () => {
    let transition = startStreamingTurn(getDefaultState(), "inspect files");
    transition = reduceStreamEvent(transition.state, transition.session, "model_action_admission", {
      public_projection_envelope: {
        authority: "harness.public_projection.v1",
        projection_id: "publicproj:tool",
        lifecycle: "running",
        source_authority: "tool",
        surface: "tool_window",
        items: [
          {
            item_id: "tool:1",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            title: "正在执行操作",
            subject_label: "docs",
            state: "running",
          },
        ],
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.stageStatus).toBe("正在思考");
  });

  it("does not overwrite active-work pause projection with generic steer text", () => {
    let transition = startStreamingTurn(getDefaultState(), "pause it");
    transition = reduceStreamEvent(transition.state, transition.session, "active_task_steer_accepted", {
      public_projection_envelope: {
        authority: "harness.public_projection.v1",
        projection_id: "publicproj:pause",
        lifecycle: "running",
        source_authority: "system",
        surface: "status_bar",
        items: [
          {
            item_id: "pause:1",
            kind: "status_update",
            slot: "status",
            surface: "status_bar",
            source_authority: "system",
            title: "已暂停当前工作",
            detail: "暂停请求已记录。",
            state: "done",
            phase: "work_control",
          },
        ],
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.stageStatus).toBe("已暂停当前工作");
    expect(assistant?.runtimePublicTimelineDraft?.[0]?.title).toBe("已暂停当前工作");
  });

  it("preserves done task-steer projection title from the envelope", () => {
    let transition = startStreamingTurn(getDefaultState(), "pause it");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      completion_state: "task_steer_accepted",
      summary: "好，我先停在这里。",
      public_projection_envelope: {
        authority: "harness.public_projection.v1",
        projection_id: "publicproj:pause-done",
        lifecycle: "done",
        source_authority: "system",
        surface: "control",
        items: [
          {
            item_id: "pause-done:1",
            kind: "status_update",
            slot: "status",
            surface: "status_bar",
            source_authority: "system",
            title: "已暂停当前工作",
            detail: "好，我先停在这里。",
            state: "running",
            phase: "work_control",
          },
        ],
        terminal: {
          event: "done",
          visible: true,
          reason: "work_control",
        },
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.stageStatus).toBe("已暂停当前工作");
    expect(assistant?.runtimePublicTimelineDraft?.[0]?.title).toBe("已暂停当前工作");
  });
});
