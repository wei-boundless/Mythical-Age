import { describe, expect, it } from "vitest";

import type { PublicProjectionFrame } from "@/lib/api";
import { applyProjectionFramesToMessages } from "@/lib/projection/reducer";
import { getDefaultState } from "@/lib/store/core";
import { reduceStreamEvent, startStreamingTurn } from "@/lib/store/events";
import type { Message } from "@/lib/store/types";

let frameOffset = 0;

function projectionFrame(patch: Partial<PublicProjectionFrame>): PublicProjectionFrame {
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
  if (patch.op === "commit_ack" || eventType.startsWith("session_output_commit")) return "runtime_commit";
  return "status_trace";
}

function channelForEventFamily(eventFamily: string) {
  if (eventFamily === "assistant_body") return "body";
  if (eventFamily === "tool_control") return "control";
  if (eventFamily === "runtime_commit") return "commit";
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
    public_projection_frame: projectionFrame(patch),
  });
}

function latestAssistant(messages: Message[]) {
  return [...messages].reverse().find((message) => message.role === "assistant");
}

function latestProjection(state: ReturnType<typeof getDefaultState>) {
  const assistant = latestAssistant(state.messages);
  const key = assistant?.projectionKeyString ?? "";
  return key ? state.activeProjectionsByKey[key]?.view : undefined;
}

function latestLedger(state: ReturnType<typeof getDefaultState>) {
  const assistant = latestAssistant(state.messages);
  const key = assistant?.projectionKeyString ?? "";
  return key ? state.activeProjectionsByKey[key]?.ledger : undefined;
}

describe("chronological projection frame reducer contract", () => {
  it("projects assistant body without mutating persisted message content", () => {
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

    const assistant = latestAssistant(transition.state.messages);
    const view = latestProjection(transition.state);
    const ledger = latestLedger(transition.state);
    expect(assistant?.content).toBe("");
    expect(view?.canonicalContent).toBe("正在检查投影链路。");
    expect(view?.bodyState).toBe("finalized");
    expect(ledger?.cursor.maxOffset).toBeGreaterThan(0);
    expect(transition.state.sessionActivity).toBe(activityBeforeBody);
  });

  it("keeps assistant final body separate from turn terminal projection", () => {
    let transition = startBoundProjectionTurn();
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 1,
      content: "OCR 已读取题目，下面给出完整解法。",
      event_offset: 1,
      public_projection_frame: projectionFrame({
        source_event_type: "assistant_text_final",
        op: "body_finalize",
        slot: "body",
        source_authority: "model",
        main_visibility: "visible_final",
        retention: "final",
        text: "OCR 已读取题目，下面给出完整解法。",
      }),
    });
    transition = reduceStreamEvent(transition.state, transition.session, "turn_completed", {
      status: "completed",
      terminal_reason: "assistant_message",
      event_offset: 2,
      public_projection_frame: projectionFrame({
        source_event_type: "turn_completed",
        op: "item_upsert",
        slot: "terminal",
        source_authority: "runtime",
        main_visibility: "hidden",
        retention: "trace",
        item_id: "terminal:assistant-message",
        state: "completed",
      }),
    });

    const assistant = latestAssistant(transition.state.messages);
    const view = latestProjection(transition.state);
    expect(assistant?.content).toBe("");
    expect(view?.canonicalContent).toBe("OCR 已读取题目，下面给出完整解法。");
    expect(view?.blocks.filter((block) => block.kind === "body_segment")).toHaveLength(1);
    expect(view?.blocks.some((block) => block.kind === "terminal_event")).toBe(false);
  });

  it("folds tool request, start, and completion into one chronological tool event", () => {
    let transition = startBoundProjectionTurn();
    const activityBeforeTool = transition.state.sessionActivity;

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
      title: "搜索文件：projection",
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

    const toolBlocks = latestProjection(transition.state)?.blocks
      .filter((block) => block.kind === "tool_event");
    expect(toolBlocks).toHaveLength(1);
    expect(toolBlocks?.[0]).toMatchObject({
      id: "call:search",
      toolCallId: "call:search",
      toolLifecycleId: "toolinv:search:1",
      sourceEventType: "tool_item_completed",
      state: "done",
    });
    expect(toolBlocks?.[0]?.firstOffset).toBeLessThan(toolBlocks?.[0]?.lastOffset ?? 0);
    expect(transition.state.sessionActivity).toBe(activityBeforeTool);
  });

  it("preserves request command details after a trace-only tool completion frame", () => {
    let transition = startBoundProjectionTurn();

    transition = project(transition, {
      source_event_type: "tool_call_requested",
      event_offset: 10,
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "call:read-flow-edges",
      tool_call_id: "call:read-flow-edges",
      tool_lifecycle_id: "call:read-flow-edges",
      tool_name: "read_file",
      title: "读取文件：backend/harness/graph/flow_edges.py",
      target: "backend/harness/graph/flow_edges.py",
      arguments_preview: "path=backend/harness/graph/flow_edges.py, line_count=80",
      state: "running",
    });
    transition = project(transition, {
      source_event_type: "tool_item_completed",
      event_offset: 20,
      op: "item_retire",
      slot: "trace",
      source_authority: "tool",
      main_visibility: "trace_only",
      retention: "trace",
      item_id: "call:read-flow-edges",
      tool_call_id: "call:read-flow-edges",
      tool_lifecycle_id: "toolinv:read-flow-edges",
      tool_name: "read_file",
      state: "done",
    });

    const tool = latestProjection(transition.state)?.blocks.find((block) => block.kind === "tool_event");
    expect(tool).toMatchObject({
      kind: "tool_event",
      target: "backend/harness/graph/flow_edges.py",
      commandLine: "read_file backend/harness/graph/flow_edges.py path=backend/harness/graph/flow_edges.py, line_count=80",
      output: "读取文件完成：backend/harness/graph/flow_edges.py",
      state: "done",
    });
    expect(tool?.commandLine).not.toBe("read_file");
    expect(tool?.output).not.toBe("系统调用已完成。");
  });

  it("keeps body and tool activity as ordered render blocks", () => {
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
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "final",
      text: "再继续。",
    });

    const view = latestProjection(transition.state);
    expect(view?.canonicalContent).toBe("先说明。再继续。");
    expect(view?.blocks.map((block) => block.kind)).toEqual([
      "body_segment",
      "tool_event",
      "body_segment",
    ]);
  });

  it("does not create main-view activity for hidden protocol diagnostics", () => {
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

    const view = latestProjection(transition.state);
    expect(view?.blocks).toEqual([]);
    expect(view?.traceAvailable).toBe(false);
  });

  it("does not render hidden status frames even when their slot is status", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "runtime_status",
      op: "item_upsert",
      slot: "status",
      source_authority: "runtime",
      main_visibility: "hidden",
      retention: "trace",
      item_id: "status:hidden",
      title: "内部状态不应显示",
      state: "running",
    });

    const view = latestProjection(transition.state);
    expect(view).toBeUndefined();
  });

  it("drops hidden model body frames before they can become assistant prose", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "runtime_step_summary",
      op: "body_append",
      slot: "body",
      source_authority: "model",
      event_family: "assistant_body",
      channel: "body",
      main_visibility: "hidden",
      retention: "trace",
      item_id: "body:hidden",
      text: "这段隐藏正文不能进主聊天。",
    });

    const assistant = latestAssistant(transition.state.messages);
    expect(assistant?.content).toBe("");
    expect(latestProjection(transition.state)).toBeUndefined();
  });

  it("drops visible runtime status frames before they can create chat messages or activity", () => {
    let transition = startBoundProjectionTurn();
    const beforeMessages = transition.state.messages;
    const beforeActivity = transition.state.sessionActivity;

    transition = project(transition, {
      source_event_type: "runtime_status",
      op: "item_upsert",
      slot: "status",
      source_authority: "runtime",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "status:visible-noise",
      title: "status noise",
      state: "running",
    });

    expect(transition.state.messages).toHaveLength(beforeMessages.length);
    expect(latestAssistant(transition.state.messages)?.content).toBe("");
    expect(latestProjection(transition.state)).toBeUndefined();
    expect(transition.state.sessionActivity).toBe(beforeActivity);
  });

  it("renders active task steer accepted as a lightweight status event outside assistant prose", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "active_task_steer_accepted",
      op: "item_upsert",
      slot: "status",
      source_authority: "runtime",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "status:steer:1",
      status_kind: "status_event",
      title: "补充要求已接入当前任务",
      detail: "继续检查投影时序。",
      state: "done",
    });

    const assistant = latestAssistant(transition.state.messages);
    const view = latestProjection(transition.state);
    expect(assistant?.content).toBe("");
    expect(view?.canonicalContent).toBe("");
    expect(view?.displayMode).toBe("live");
    expect(view?.blocks).toEqual([
      expect.objectContaining({
        kind: "status_event",
        title: "补充要求已接入当前任务",
        detail: "继续检查投影时序。",
      }),
    ]);
  });

  it("renders commit failed as recovery event with log entry but never assistant body", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "session_output_commit_failed",
      op: "item_upsert",
      slot: "status",
      source_authority: "runtime",
      main_visibility: "visible_live",
      retention: "final",
      item_id: "status:commit-failed",
      status_kind: "recovery_event",
      title: "最终输出写回失败",
      detail: "history write failed",
      state: "failed",
      commit: {
        state: "failed",
        commit_event_offset: 21,
      },
    });

    const assistant = latestAssistant(transition.state.messages);
    const view = latestProjection(transition.state);
    const ledger = latestLedger(transition.state);
    expect(assistant?.content).toBe("");
    expect(view?.canonicalContent).toBe("");
    expect(view?.displayMode).toBe("recovery");
    expect(ledger?.commit.state).toBe("failed");
    expect(view?.blocks).toEqual([
      expect.objectContaining({ kind: "recovery_event", title: "输出未写入会话记录" }),
      expect.objectContaining({ kind: "log_entry" }),
    ]);
  });

  it("neutralizes persisted legacy runtime recovery wording on replay", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "turn_completed",
      op: "item_upsert",
      slot: "status",
      source_authority: "runtime",
      main_visibility: "visible_live",
      retention: "final",
      item_id: "turn-terminal:legacy",
      status_kind: "recovery_event",
      title: "旧运行恢复标题",
      text: "旧运行恢复标题",
      detail: "系统自动生成的恢复说明。",
      state: "failed",
    });

    const assistant = latestAssistant(transition.state.messages);
    const view = latestProjection(transition.state);
    const rendered = JSON.stringify(view?.blocks ?? []);
    expect(assistant?.content).toBe("");
    expect(view?.displayMode).toBe("recovery");
    expect(view?.blocks).toEqual([
      expect.objectContaining({ kind: "recovery_event", title: "需要处理", detail: "" }),
      expect.objectContaining({ kind: "log_entry" }),
    ]);
    expect(rendered).not.toContain("旧运行恢复标题");
    expect(rendered).not.toContain("系统自动生成的恢复说明");
  });

  it("renders stopped terminal as typed terminal event with log entry", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "stopped",
      op: "item_upsert",
      slot: "status",
      source_authority: "runtime",
      main_visibility: "visible_live",
      retention: "final",
      item_id: "status:stopped",
      status_kind: "terminal_event",
      title: "旧停止标题",
      detail: "用户停止了当前运行。",
      state: "stopped",
    });

    const assistant = latestAssistant(transition.state.messages);
    const view = latestProjection(transition.state);
    expect(assistant?.content).toBe("");
    expect(view?.displayMode).toBe("recovery");
    expect(view?.blocks).toEqual([
      expect.objectContaining({ kind: "terminal_event", title: "运行已停止" }),
      expect.objectContaining({ kind: "log_entry" }),
    ]);
  });

  it("does not let trace-only tool frames open a visible tool block without a model request", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "tool_item_completed",
      op: "item_retire",
      slot: "trace",
      source_authority: "tool",
      main_visibility: "trace_only",
      retention: "trace",
      item_id: "toolinv:orphan",
      tool_call_id: "call:orphan",
      tool_lifecycle_id: "toolinv:orphan",
      tool_name: "read_file",
      title: "孤立工具完成",
      state: "done",
    });

    const view = latestProjection(transition.state);
    expect(view?.blocks).toEqual([]);
    expect(view?.traceAvailable).toBe(false);
  });

  it("does not let out-of-order tool lifecycle frames regress terminal state", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "tool_call_requested",
      event_offset: 10,
      op: "item_upsert",
      slot: "current_action",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "tool:read",
      tool_call_id: "call:read",
      tool_lifecycle_id: "call:read",
      tool_name: "read_file",
      title: "读取文件",
      state: "running",
    });
    transition = project(transition, {
      source_event_type: "tool_item_completed",
      event_offset: 30,
      op: "item_retire",
      slot: "trace",
      source_authority: "tool",
      main_visibility: "trace_only",
      retention: "trace",
      item_id: "tool:read",
      tool_call_id: "call:read",
      tool_lifecycle_id: "call:read",
      tool_name: "read_file",
      state: "done",
    });
    transition = project(transition, {
      source_event_type: "tool_item_started",
      event_offset: 20,
      op: "item_upsert",
      slot: "trace",
      source_authority: "tool",
      main_visibility: "trace_only",
      retention: "trace",
      item_id: "tool:read",
      tool_call_id: "call:read",
      tool_lifecycle_id: "call:read",
      tool_name: "read_file",
      state: "running",
    });

    const tool = latestProjection(transition.state)?.blocks.find((block) => block.kind === "tool_event");
    expect(tool).toMatchObject({
      kind: "tool_event",
      state: "done",
      firstOffset: 10,
      lastOffset: 30,
    });
  });

  it("rejects non-model body frames before they can become assistant prose", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      op: "body_append",
      slot: "body",
      source_authority: "tool",
      main_visibility: "visible_live",
      retention: "final",
      text: "工具输出不能成为正文",
    });

    const assistant = latestAssistant(transition.state.messages);
    expect(assistant?.content).toBe("");
    expect(latestProjection(transition.state)).toBeUndefined();
    expect(latestLedger(transition.state)).toBeUndefined();
  });

  it("deduplicates replayed model feedback body by semantic feedback identity", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "assistant_public_feedback",
      op: "body_append",
      slot: "body",
      source_authority: "model",
      event_family: "assistant_body",
      channel: "body",
      main_visibility: "visible_live",
      retention: "transient",
      frame_id: "frame:live-feedback",
      item_id: "assistant-public-feedback:feedback:1",
      text: "正在核对当前文件。\n\n下一步执行修改。",
    });
    transition = project(transition, {
      source_event_type: "assistant_public_feedback",
      op: "body_append",
      slot: "body",
      source_authority: "model",
      event_family: "assistant_body",
      channel: "body",
      main_visibility: "visible_live",
      retention: "transient",
      frame_id: "frame:history-replay-feedback",
      item_id: "assistant-public-feedback:feedback:1",
      text: "正在核对当前文件。\n\n下一步执行修改。",
    });

    const assistant = latestAssistant(transition.state.messages);
    const view = latestProjection(transition.state);
    const ledger = latestLedger(transition.state);
    expect(view?.canonicalContent).toBe("正在核对当前文件。\n\n下一步执行修改。");
    expect(view?.blocks.filter((block) => block.kind === "body_segment")).toHaveLength(1);
    expect(ledger?.bodySegments[0]?.sourceKeys).toContain("assistant-public-feedback:feedback:1");
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

    expect(latestProjection(transition.state)).toBeUndefined();

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

    const assistant = latestAssistant(transition.state.messages);
    const view = latestProjection(transition.state);
    expect(assistant?.sourceTurnId).toBe("turn:new");
    expect(assistant?.sourceStreamRunId).toBe("strun:new");
    expect(view?.canonicalContent).toBe("新时序内容");
    expect(view?.canonicalContent).not.toContain("旧时序内容");
  });

  it("uses final body phase as the archive boundary while commit_ack only marks committed state", () => {
    let transition = startBoundProjectionTurn();
    transition = project(transition, {
      source_event_type: "assistant_public_feedback",
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "assistant-public-feedback:before-closeout",
      text: "收口前的过程正文。",
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
      source_event_type: "assistant_public_feedback",
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      item_id: "assistant-public-feedback:closeout-shadow",
      text: "最终正文。",
    });
    transition = project(transition, {
      source_event_type: "assistant_text_delta",
      op: "body_append",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      text: "最终正文。",
    });
    transition = project(transition, {
      source_event_type: "assistant_stream_repair",
      op: "body_finalize",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_live",
      retention: "transient",
      text: "最终正文。",
    });
    transition = project(transition, {
      source_event_type: "assistant_text_final",
      op: "body_finalize",
      slot: "body",
      source_authority: "model",
      main_visibility: "visible_final",
      retention: "final",
      text: "最终正文。",
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

    const assistant = latestAssistant(transition.state.messages);
    const view = latestProjection(transition.state);
    expect(assistant?.content).toBe("");
    expect(view?.canonicalContent).toBe("最终正文。");
    expect(view?.bodyState).toBe("committed");
    expect(view?.displayMode).toBe("committed");
    expect(view?.blocks.some((block) => block.kind === "tool_event")).toBe(false);
    expect(view?.blocks).toEqual([
      expect.objectContaining({
        kind: "activity_archive",
        title: "",
        blocks: [
          expect.objectContaining({
            kind: "body_segment",
            sourceEventType: "assistant_public_feedback",
            text: "收口前的过程正文。",
          }),
          expect.objectContaining({ kind: "tool_event", toolCallId: "call:verify" }),
        ],
      }),
      expect.objectContaining({
        kind: "body_segment",
        sourceEventType: "assistant_text_final",
        text: "最终正文。",
      }),
      expect.objectContaining({ kind: "log_entry" }),
    ]);
    const archive = view?.blocks.find((block) => block.kind === "activity_archive");
    expect(archive).toEqual(expect.objectContaining({
      blocks: expect.not.arrayContaining([
        expect.objectContaining({ kind: "body_segment", sourceEventType: "assistant_text_delta" }),
        expect.objectContaining({ kind: "body_segment", sourceEventType: "assistant_stream_repair" }),
        expect.objectContaining({ kind: "body_segment", sourceEventType: "assistant_text_final" }),
        expect.objectContaining({
          kind: "body_segment",
          sourceEventType: "assistant_public_feedback",
          text: "最终正文。",
        }),
      ]),
    }));
    expect(view?.blocks.filter((block) => block.kind === "body_segment")).toEqual([
      expect.objectContaining({
        kind: "body_segment",
        sourceEventType: "assistant_text_final",
        text: "最终正文。",
      }),
    ]);
    expect(view?.blocks.some((block) => block.kind === "log_entry")).toBe(true);
  });

  it("does not hydrate empty assistant messages from status-only projection history", () => {
    const messages = applyProjectionFramesToMessages([
      {
        id: "user:projection:history",
        role: "user",
        content: "inspect projection",
        toolCalls: [],
        retrievals: [],
        sourceTurnId: "turn:projection:1",
      },
    ], [
      projectionFrame({
        source_event_type: "runtime_status",
        op: "item_upsert",
        slot: "status",
        source_authority: "runtime",
        main_visibility: "visible_live",
        retention: "transient",
        item_id: "status:history-noise",
        title: "history noise",
        state: "running",
      }),
    ], { createMessages: true });

    expect(messages).toHaveLength(1);
    expect(messages[0]?.role).toBe("user");
  });

  it("does not hydrate empty assistant messages from typed recovery projection history", () => {
    const messages = applyProjectionFramesToMessages([
      {
        id: "user:projection:history",
        role: "user",
        content: "inspect projection",
        toolCalls: [],
        retrievals: [],
        sourceTurnId: "turn:projection:1",
      },
    ], [
      projectionFrame({
        source_event_type: "turn_completed",
        op: "item_upsert",
        slot: "status",
        source_authority: "runtime",
        main_visibility: "visible_live",
        retention: "final",
        item_id: "status:recovery-only",
        status_kind: "recovery_event",
        title: "需要处理",
        detail: "处理失败",
        state: "failed",
      }),
    ], { createMessages: true });

    expect(messages).toHaveLength(1);
    expect(messages[0]?.role).toBe("user");
  });

  it("does not hydrate empty assistant messages from trace-only tool history", () => {
    const messages = applyProjectionFramesToMessages([
      {
        id: "user:projection:history",
        role: "user",
        content: "inspect projection",
        toolCalls: [],
        retrievals: [],
        sourceTurnId: "turn:projection:1",
      },
    ], [
      projectionFrame({
        source_event_type: "tool_item_completed",
        op: "item_retire",
        slot: "trace",
        source_authority: "tool",
        main_visibility: "trace_only",
        retention: "trace",
        item_id: "toolinv:orphan",
        tool_call_id: "call:orphan",
        tool_lifecycle_id: "toolinv:orphan",
        tool_name: "read_file",
        state: "done",
      }),
    ], { createMessages: true });

    expect(messages).toHaveLength(1);
    expect(messages[0]?.role).toBe("user");
  });

});
