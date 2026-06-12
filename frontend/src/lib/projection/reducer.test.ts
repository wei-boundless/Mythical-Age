import { describe, expect, it } from "vitest";

import { applyPublicProjectionEnvelope } from "@/lib/projection/reducer";
import { getDefaultState } from "@/lib/store/core";
import { reduceStreamEvent, startStreamingTurn } from "@/lib/store/events";

describe("public projection reducer contract", () => {
  function bindTurnRun(transition: ReturnType<typeof startStreamingTurn>, turnId: string, turnRunId = `turnrun:${turnId}`) {
    return reduceStreamEvent(transition.state, transition.session, "harness_run_started", {
      turn_run: {
        turn_id: turnId,
        turn_run_id: turnRunId,
      },
    });
  }

  it("drops explicit model body slots from public projection envelopes", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      public_projection_envelope: {
        authority: "harness.public_projection",
        anchor: { turn_id: "turn:projection" },
        projection_id: "publicproj:body",
        lifecycle: "running",
        source_authority: "model",
        surface: "assistant_body",
        items: [
          {
            item_id: "body:1",
            kind: "assistant_text",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "I am checking the projection chain.",
            state: "running",
          },
        ],
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.runtimeAttachments ?? []).toEqual([]);
    expect(assistant?.runtimePublicTimelineDraft ?? []).toEqual([]);
  });

  it("drops stage feedback body items instead of treating them as timeline content", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      answer_channel: "stage_feedback",
      answer_source: "harness.single_agent_turn.tool_commentary",
      public_projection_envelope: {
        authority: "harness.public_projection",
        anchor: { turn_id: "turn:projection" },
        projection_id: "publicproj:stage-feedback",
        lifecycle: "running",
        source_authority: "model",
        surface: "assistant_body",
        items: [
          {
            item_id: "stage-feedback:1",
            kind: "stage_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            title: "阶段反馈",
            text: "工具结果已返回，我会根据证据继续收口。",
            state: "running",
          },
        ],
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.runtimePublicTimelineDraft ?? []).toEqual([]);
    expect(assistant?.runtimeAttachments ?? []).toEqual([]);
  });

  it("fails closed for body-looking projection items without explicit slot", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      public_projection_envelope: {
        authority: "harness.public_projection",
        projection_id: "publicproj:no-slot",
        lifecycle: "running",
        source_authority: "runtime",
        surface: "timeline",
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
    expect(assistant?.stageStatus).toBe("");
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

  it("does not let task_run_id override a stale message id when a current turn anchor exists", () => {
    const taskRunId = "taskrun:projection:final";
    const state = {
      ...getDefaultState(),
      messages: [
        {
          id: "user-current",
          role: "user",
          content: "continue",
          toolCalls: [],
          retrievals: [],
          sourceTurnId: "turn:projection:1",
        },
        {
          id: "assistant-opening",
          role: "assistant",
          content: "",
          toolCalls: [],
          retrievals: [],
          sourceTurnId: "turn:projection:old",
        },
        {
          id: "assistant-final",
          role: "assistant",
          content: "final",
          toolCalls: [],
          retrievals: [],
          sourceTaskRunId: taskRunId,
        },
      ],
    } as ReturnType<typeof getDefaultState>;

    const next = applyPublicProjectionEnvelope(state, {
      authority: "harness.public_projection",
      projection_id: "publicproj:taskrun-final",
      lifecycle: "completed",
      source_authority: "runtime",
      surface: "timeline",
      anchor: {
        message_id: "assistant-opening",
        turn_id: "turn:projection:1",
        task_run_id: taskRunId,
      },
      task_projection: {
        authority: "harness.runtime.single_agent_task_projection.v1",
        projection_id: "projection:taskrun-final",
        task_run_id: taskRunId,
        status: "completed",
      },
      items: [
        {
          item_id: "taskrun-final:item",
          kind: "status_update",
          slot: "status",
          surface: "timeline",
          source_authority: "runtime",
          state: "done",
        },
      ],
    });

    const opening = next.messages.find((message) => message.id === "assistant-opening");
    const final = next.messages.find((message) => message.id === "assistant-final");

    expect(opening?.runtimeAttachments ?? []).toEqual([]);
    expect(final?.runtimeAttachments ?? []).toEqual([]);
    const currentTurn = next.messages.find((message) =>
      message.role === "assistant"
      && message.sourceTurnId === "turn:projection:1"
      && message.id !== "assistant-opening"
    );
    expect(currentTurn?.runtimeAttachments?.[0]).toMatchObject({
      task_run_id: taskRunId,
      anchor_turn_id: "turn:projection:1",
    });
  });

  it("keeps public timeline feedback alongside task projection attachments", () => {
    let transition = startStreamingTurn(getDefaultState(), "run task");
    transition = bindTurnRun(transition, "turn:session:feedback:1");
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_status", {
      public_projection_envelope: {
        authority: "harness.public_projection",
        projection_id: "publicproj:task-feedback",
        lifecycle: "running",
        source_authority: "model",
        surface: "assistant_body",
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
            kind: "status_update",
            slot: "status",
            surface: "timeline",
            source_authority: "runtime",
            title: "观察反馈",
            detail: "已确认上一阶段结果，可以继续推进。",
            state: "done",
          },
        ],
      },
    });

    const assistant = transition.state.messages.find((message) =>
      (message.runtimeAttachments ?? []).some((attachment) => attachment.task_run_id === "taskrun:feedback")
    );
    expect(assistant?.runtimeAttachments?.[0]).toMatchObject({
      task_run_id: "taskrun:feedback",
      task_projection: {
        task_run_id: "taskrun:feedback",
        status: "running",
      },
    });
  });

  it("does not attach an old anchored projection to the current stream assistant", () => {
    let transition = startStreamingTurn(getDefaultState(), "new request");
    transition = bindTurnRun(transition, "turn:session:new:3");
    const assistantId = transition.session.assistantId;
    transition = reduceStreamEvent(transition.state, transition.session, "model_action_admission", {
      public_projection_envelope: {
        authority: "harness.public_projection",
        projection_id: "publicproj:old-tool",
        lifecycle: "running",
        source_authority: "tool",
        surface: "tool_window",
        anchor: {
          turn_id: "turn:session:old:1",
          turn_run_id: "turnrun:turn:session:old:1",
          run_id: "turnrun:turn:session:old:1",
        },
        items: [
          {
            item_id: "tool:old",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            title: "旧工具动作",
            state: "running",
          },
        ],
      },
    });

    const assistant = transition.state.messages.find((message) => message.id === assistantId);
    expect(assistant?.runtimePublicTimelineDraft ?? []).toEqual([]);
    expect(assistant?.runtimeAttachments ?? []).toEqual([]);
  });

  it("does not attach tool-window projection to the bound current stream assistant", () => {
    let transition = startStreamingTurn(getDefaultState(), "inspect files");
    transition = bindTurnRun(transition, "turn:session:current:4");
    const assistantId = transition.session.assistantId;
    transition = reduceStreamEvent(transition.state, transition.session, "model_action_admission", {
      public_projection_envelope: {
        authority: "harness.public_projection",
        projection_id: "publicproj:current-tool",
        lifecycle: "running",
        source_authority: "tool",
        surface: "tool_window",
        anchor: {
          turn_id: "turn:session:current:4",
          turn_run_id: "turnrun:turn:session:current:4",
          run_id: "turnrun:turn:session:current:4",
        },
        items: [
          {
            item_id: "tool:current",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            title: "读取文件",
            state: "running",
          },
        ],
      },
    });

    const assistant = transition.state.messages.find((message) => message.id === assistantId);
    expect(assistant?.sourceTurnId).toBe("turn:session:current:4");
    expect(assistant?.runtimePublicTimelineDraft ?? []).toEqual([]);
  });

  it("updates a first-class tool item in place by tool_call_id", () => {
    let transition = startStreamingTurn(getDefaultState(), "inspect files");
    transition = bindTurnRun(transition, "turn:session:tool:1");
    transition = reduceStreamEvent(transition.state, transition.session, "tool_item_started", {
      item_id: "call:read",
      tool_call_id: "call:read",
      turn_run_id: "turnrun:turn:session:tool:1",
      tool_name: "read_file",
      title: "读取文件",
      target: "README.md",
      state: "running",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "tool_item_completed", {
      item_id: "call:read",
      tool_call_id: "call:read",
      turn_run_id: "turnrun:turn:session:tool:1",
      tool_name: "read_file",
      state: "done",
      observation: "读取完成",
    });

    const timeline = transition.state.messages.at(-1)?.runtimePublicTimelineDraft ?? [];
    expect(timeline).toHaveLength(1);
    expect(timeline[0]).toMatchObject({
      item_id: "call:read",
      tool_name: "read_file",
      state: "done",
      stream_state: "done",
      observation: "读取完成",
    });
  });

  it("uses thinking stage status for tool-window projection without creating body text", () => {
    let transition = startStreamingTurn(getDefaultState(), "inspect files");
    transition = reduceStreamEvent(transition.state, transition.session, "model_action_admission", {
      public_projection_envelope: {
        authority: "harness.public_projection",
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
    expect(assistant?.stageStatus).toBe("");
  });

  it("fails closed for new authoritative projection envelopes without an anchor", () => {
    let transition = startStreamingTurn(getDefaultState(), "inspect files");
    transition = reduceStreamEvent(transition.state, transition.session, "model_action_admission", {
      public_projection_envelope: {
        authority: "harness.public_projection",
        contract_revision: "20260610-replacement",
        projection_mode: "authoritative",
        projection_id: "publicproj:no-anchor",
        lifecycle: "running",
        source_authority: "tool",
        surface: "tool_window",
        items: [
          {
            item_id: "tool:no-anchor",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            title: "读取文件",
            state: "running",
          },
        ],
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.runtimePublicTimelineDraft).toEqual([]);
  });

  it("does not overwrite active-work pause projection with generic steer text", () => {
    let transition = startStreamingTurn(getDefaultState(), "pause it");
    transition = reduceStreamEvent(transition.state, transition.session, "active_task_steer_accepted", {
      public_projection_envelope: {
        authority: "harness.public_projection",
        anchor: { turn_id: "turn:pause" },
        projection_id: "publicproj:pause",
        lifecycle: "running",
        source_authority: "runtime",
        surface: "control",
        items: [
          {
            item_id: "pause:1",
            kind: "control_state",
            slot: "control",
            surface: "control",
            source_authority: "runtime",
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
        authority: "harness.public_projection",
        anchor: { turn_id: "turn:pause" },
        projection_id: "publicproj:pause-done",
        lifecycle: "done",
        source_authority: "runtime",
        surface: "control",
        items: [
          {
            item_id: "pause-done:1",
            kind: "control_state",
            slot: "control",
            surface: "control",
            source_authority: "runtime",
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
