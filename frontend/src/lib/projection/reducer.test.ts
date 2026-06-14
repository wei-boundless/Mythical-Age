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
  });

  it("opens the main tool action only from the model tool_call_requested frame", () => {
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
      text: "读取投影 reducer",
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
      title: "读取完成",
      state: "done",
    });

    const projection = transition.state.messages.at(-1)?.publicProjection;
    expect(projection?.currentAction).toBeUndefined();
    expect(projection?.pinned).toEqual([]);
    expect(projection?.traceCount).toBeGreaterThan(0);
    expect(projection?.timeline.map((item) => item.sourceEventType)).toEqual([
      "tool_call_requested",
      "tool_item_completed",
    ]);
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
