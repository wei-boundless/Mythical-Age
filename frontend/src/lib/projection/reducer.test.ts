import { describe, expect, it } from "vitest";

import type { PublicProjectionFrame } from "@/lib/api";
import { getDefaultState } from "@/lib/store/core";
import { reduceStreamEvent, startStreamingTurn } from "@/lib/store/events";

let frameOffset = 0;

function publicFrame(patch: Partial<PublicProjectionFrame>): PublicProjectionFrame {
  frameOffset += 1;
  const eventFamily = patch.event_family ?? inferEventFamily(patch);
  return {
    authority: "harness.public_projection",
    contract_revision: "20260614-dual-channel-v1",
    frame_id: `frame:${frameOffset}`,
    event_offset: frameOffset,
    event_family: eventFamily,
    channel: patch.channel ?? channelForEventFamily(eventFamily),
    lossless: patch.lossless ?? eventFamily !== "status_trace",
    anchor: {
      turn_id: "turn:projection:1",
      stream_run_id: "strun:projection:1",
      turn_run_id: "turnrun:projection:1",
      run_id: "turnrun:projection:1",
    },
    op: "item_upsert",
    slot: "status",
    source_authority: "runtime",
    main_visibility: "hidden",
    retention: "trace",
    ...patch,
  };
}

function inferEventFamily(patch: Partial<PublicProjectionFrame>) {
  const eventType = String(patch.source_event_type ?? "");
  if (patch.slot === "body" || eventType.startsWith("assistant_text") || eventType === "assistant_stream_repair") return "assistant_body";
  if (eventType.startsWith("tool_") || patch.tool_call_id) return "tool_control";
  if (patch.op === "commit_ack" || patch.op === "commit_failed" || eventType.startsWith("session_output_commit")) return "runtime_commit";
  if (patch.op === "turn_terminal" || eventType === "turn_completed") return "turn_anchor_terminal";
  return "status_trace";
}

function channelForEventFamily(eventFamily: string) {
  if (eventFamily === "assistant_body") return "body";
  if (eventFamily === "tool_control") return "control";
  if (eventFamily === "runtime_commit") return "commit";
  if (eventFamily === "turn_anchor_terminal") return "terminal";
  return "status";
}

function startBoundProjectionTurn() {
  let transition = startStreamingTurn(getDefaultState(), "inspect projection");
  transition = reduceStreamEvent(transition.state, transition.session, "harness_run_started", {
    turn_run: {
      turn_id: "turn:projection:1",
      turn_run_id: "turnrun:projection:1",
    },
  });
  return transition;
}

function project(
  transition: ReturnType<typeof startStreamingTurn>,
  patch: Partial<PublicProjectionFrame>,
) {
  return reduceStreamEvent(transition.state, transition.session, "public_projection_frame", {
    public_projection_frame: publicFrame(patch),
  });
}

describe("public projection frame reducer contract", () => {
  it("progressively appends and finalizes assistant body from public_projection_frame", () => {
    let transition = startBoundProjectionTurn();
    const activityBeforeBody = transition.state.sessionActivity;
    transition = project(transition, {
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "final",
      text: "正在检查",
    });
    transition = project(transition, {
      op: "body_finalize",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_final",
      retention: "final",
      text: "正在检查投影链路。",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("正在检查投影链路。");
    expect(assistant?.publicProjection?.bodyText).toBe("正在检查投影链路。");
    expect(assistant?.publicProjection?.bodyState).toBe("finalized");
    expect(assistant?.publicProjection?.bodyEventOffset).toBeGreaterThan(0);
    expect(transition.state.sessionActivity).toBe(activityBeforeBody);
  });

  it("opens the main tool action only from the model tool_call_requested frame", () => {
    let transition = startBoundProjectionTurn();
    const activityBeforeTool = transition.state.sessionActivity;
    transition = project(transition, {
      source_event_type: "tool_call_requested",
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "tool:read",
      tool_call_id: "call:read",
      permission_decision_id: "permission:read",
      tool_name: "read_file",
      title: "读取投影 reducer",
      subject_label: "frontend/src/lib/projection/reducer.ts",
      state: "running",
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.currentAction).toMatchObject({
      itemId: "tool:read",
      toolCallId: "call:read",
      permissionDecisionId: "permission:read",
      mainVisibility: "visible_live",
    });
    expect(projection?.timeline).toEqual([
      expect.objectContaining({
        toolCallId: "call:read",
        eventFamily: "tool_control",
        channel: "control",
        lossless: true,
        sourceEventType: "tool_call_requested",
      }),
    ]);
    expect(transition.state.sessionActivity).toBe(activityBeforeTool);
  });

  it("keeps raw tool_item_started invisible when it has no public projection frame", () => {
    let transition = startBoundProjectionTurn();
    transition = reduceStreamEvent(transition.state, transition.session, "tool_item_started", {
      item_id: "tool:raw",
      tool_name: "read_file",
      title: "读取文件",
      state: "running",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.stageStatus).toBe("");
    expect(assistant?.publicProjection).toBeUndefined();
    expect(transition.state.sessionActivity.title).toBe("");
  });

  it("records protocol diagnostics in trace without creating main-view activity", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "tool_item_started",
      op: "item_upsert",
      slot: "trace",
      source_authority: "runtime",
      main_visibility: "hidden",
      retention: "trace",
      item_id: "diagnostic:raw-tool-start",
      title: "tool_item_started_without_model_request",
      state: "running",
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.currentAction).toBeUndefined();
    expect(projection?.pinned).toEqual([]);
    expect(projection?.traceAvailable).toBe(true);
    expect(projection?.traceCount).toBe(1);
  });

  it("retires successful transient tool actions into trace", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "tool_call_requested",
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "tool:read",
      tool_call_id: "call:read",
      title: "读取文件",
      state: "running",
    });
    transition = project(transition, {
      source_event_type: "tool_item_completed",
      op: "item_retire",
      slot: "trace",
      source_authority: "tool",
      main_visibility: "trace_only",
      retention: "trace",
      item_id: "tool:read",
      tool_call_id: "call:read",
      state: "done",
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.currentAction).toBeUndefined();
    expect(projection?.pinned).toEqual([]);
    expect(projection?.traceCount).toBeGreaterThan(0);
    expect(projection?.timeline).toHaveLength(1);
    expect(projection?.timeline[0]).toMatchObject({
      itemId: "call:read",
      toolCallId: "call:read",
      sourceEventType: "tool_item_completed",
      state: "done",
    });
    expect(projection?.timeline[0]?.eventOffset).toBeLessThan(projection?.timeline[0]?.updatedEventOffset ?? 0);
  });

  it("updates one tool trajectory across request start and completion by tool call id", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "tool_call_requested",
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "call:search",
      tool_call_id: "call:search",
      tool_lifecycle_id: "call:search",
      tool_name: "search_files",
      title: "搜索文件：mario修复计划",
      state: "running",
    });
    transition = project(transition, {
      source_event_type: "tool_item_started",
      op: "item_upsert",
      slot: "trace",
      source_authority: "tool",
      main_visibility: "trace_only",
      retention: "trace",
      item_id: "toolinv:search:1",
      tool_call_id: "call:search",
      tool_lifecycle_id: "toolinv:search:1",
      tool_name: "search_files",
      state: "running",
    });
    transition = project(transition, {
      source_event_type: "tool_item_completed",
      op: "item_retire",
      slot: "trace",
      source_authority: "tool",
      main_visibility: "trace_only",
      retention: "trace",
      item_id: "toolinv:search:1",
      tool_call_id: "call:search",
      tool_lifecycle_id: "toolinv:search:1",
      tool_name: "search_files",
      state: "done",
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.timeline).toHaveLength(1);
    expect(projection?.timeline[0]).toMatchObject({
      itemId: "call:search",
      toolCallId: "call:search",
      toolLifecycleId: "toolinv:search:1",
      sourceEventType: "tool_item_completed",
      state: "done",
    });
  });

  it("does not merge separate tool calls that share the same title", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "tool_call_requested",
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "tool-life:search:1",
      tool_call_id: "call:search:1",
      tool_lifecycle_id: "tool-life:search:1",
      tool_name: "search_files",
      title: "搜索文件：mario",
      state: "running",
    });
    transition = project(transition, {
      source_event_type: "tool_call_requested",
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "tool-life:search:2",
      tool_call_id: "call:search:2",
      tool_lifecycle_id: "tool-life:search:2",
      tool_name: "search_files",
      title: "搜索文件：mario",
      state: "running",
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.timeline).toHaveLength(2);
    expect(projection?.timeline.map((item) => item.itemId)).toEqual([
      "call:search:1",
      "call:search:2",
    ]);
    expect(projection?.timeline.map((item) => item.toolCallId)).toEqual([
      "call:search:1",
      "call:search:2",
    ]);
  });

  it("keeps assistant body separate from tool lifecycle activity", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "final",
      text: "先说明。",
    });
    transition = project(transition, {
      source_event_type: "tool_call_requested",
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "tool:read",
      tool_call_id: "call:read",
      tool_lifecycle_id: "tool-life:read",
      tool_name: "read_file",
      title: "读取文件",
      state: "running",
    });
    transition = project(transition, {
      source_event_type: "tool_item_completed",
      op: "item_retire",
      slot: "trace",
      source_authority: "tool",
      main_visibility: "trace_only",
      retention: "trace",
      item_id: "tool-life:read",
      tool_call_id: "call:read",
      tool_lifecycle_id: "tool-life:read",
      tool_name: "read_file",
      state: "done",
    });
    transition = project(transition, {
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "final",
      text: "再继续。",
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.bodyText).toBe("先说明。再继续。");
    expect(projection?.timeline).toHaveLength(1);
    expect(projection?.timeline[0]).toMatchObject({
      itemId: "call:read",
      toolCallId: "call:read",
      toolLifecycleId: "tool-life:read",
      sourceEventType: "tool_item_completed",
    });
  });

  it("merges replayed model feedback body frames by semantic feedback identity", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "runtime_step_summary",
      op: "body_append",
      slot: "body",
      source_authority: "model",
      event_family: "assistant_body",
      channel: "body",
      main_visibility: "visible_live",
      retention: "transient",
      frame_id: "frame:live-feedback",
      item_id: "model-action-feedback-body:feedback:1",
      text: "正在核对当前文件。\n\n下一步执行修改。",
    });
    transition = project(transition, {
      source_event_type: "runtime_step_summary",
      op: "body_append",
      slot: "body",
      source_authority: "model",
      event_family: "assistant_body",
      channel: "body",
      main_visibility: "visible_live",
      retention: "transient",
      frame_id: "frame:history-replay-feedback",
      item_id: "model-action-feedback-body:feedback:1",
      text: "正在核对当前文件。\n\n下一步执行修改。",
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.bodyText).toBe("正在核对当前文件。\n\n下一步执行修改。");
    expect(projection?.bodyBlocks).toHaveLength(1);
    expect(projection?.bodyBlocks[0]?.sourceFrameIds).toContain("model-action-feedback-body:feedback:1");
  });

  it("pins failed tool results until they are resolved", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "tool_item_completed",
      op: "item_upsert",
      slot: "pinned",
      source_authority: "tool",
      main_visibility: "pinned",
      retention: "pinned_until_resolved",
      pin_reason: "tool_failed",
      item_id: "tool:read:failed",
      tool_call_id: "call:read",
      title: "读取失败",
      detail: "文件不存在。",
      state: "failed",
    });

    expect(transition.state.messages.at(-1)?.publicProjection?.pinned).toEqual([
      expect.objectContaining({
        itemId: "tool:read:failed",
        pinReason: "tool_failed",
        state: "failed",
      }),
    ]);
  });

  it("does not let turn_completed clear live body or current action", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "final",
      text: "正文仍在推进。",
    });
    transition = project(transition, {
      source_event_type: "tool_call_requested",
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "tool:verify",
      tool_call_id: "call:verify",
      title: "运行验证",
      state: "running",
    });
    transition = project(transition, {
      source_event_type: "turn_completed",
      op: "turn_terminal",
      slot: "trace",
      source_authority: "runtime",
      main_visibility: "hidden",
      retention: "trace",
      state: "completed",
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.bodyText).toBe("正文仍在推进。");
    expect(projection?.currentAction?.itemId).toBe("tool:verify");
  });

  it("rejects stale task frames from a different turn even when task_run_id is shared", () => {
    let transition = startStreamingTurn(getDefaultState(), "new instruction");
    transition = {
      ...transition,
      session: {
        ...transition.session,
        boundTurnId: "turn:new",
        boundStreamRunId: "strun:new",
        boundTurnRunId: "turnrun:new",
        boundRunId: "run:new",
        boundTaskRunId: "taskrun:shared",
      },
    };
    transition = project(transition, {
      anchor: {
        turn_id: "turn:old",
        stream_run_id: "strun:old",
        turn_run_id: "turnrun:old",
        run_id: "run:old",
        task_run_id: "taskrun:shared",
      },
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "final",
      text: "旧时序内容",
    });

    expect(transition.state.messages.at(-1)?.publicProjection).toBeUndefined();

    transition = project(transition, {
      anchor: {
        turn_id: "turn:new",
        stream_run_id: "strun:new",
        turn_run_id: "turnrun:new",
        run_id: "run:new",
        task_run_id: "taskrun:shared",
      },
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "final",
      text: "新时序内容",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.sourceTurnId).toBe("turn:new");
    expect(assistant?.sourceStreamRunId).toBe("strun:new");
    expect(assistant?.publicProjection?.bodyText).toBe("新时序内容");
    expect(assistant?.publicProjection?.bodyText).not.toContain("旧时序内容");
  });

  it("uses commit_ack as the only commit authority and retires transient activity", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      op: "body_finalize",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_final",
      retention: "final",
      text: "最终正文。",
    });
    transition = project(transition, {
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "tool:verify",
      tool_call_id: "call:verify",
      title: "运行验证",
      state: "running",
    });
    transition = project(transition, {
      source_event_type: "commit_ack",
      op: "commit_ack",
      slot: "trace",
      source_authority: "runtime",
      main_visibility: "hidden",
      retention: "trace",
      commit: {
        state: "committed",
        commit_event_offset: 99,
        content_sha256: "sha256:final",
      },
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.bodyText).toBe("最终正文。");
    expect(projection?.bodyState).toBe("committed");
    expect(projection?.bodyEventOffset).toBeGreaterThan(0);
    expect(projection?.commitState).toBe("committed");
    expect(projection?.currentAction).toBeUndefined();
    expect(projection?.traceCount).toBeGreaterThan(0);
  });

});
