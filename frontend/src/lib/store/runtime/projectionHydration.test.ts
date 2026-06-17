import { describe, expect, it } from "vitest";

import type { PublicProjectionFrame, SessionRuntimeAttachment } from "@/lib/api";

import { hydrateSessionRuntimeProjection } from "./projectionHydration";
import type { Message } from "../types";

type ProjectionSlice = NonNullable<SessionRuntimeAttachment["projection_slices"]>[number];

const anchor = {
  session_id: "session:projection-hydration",
  turn_id: "turn:projection-hydration:1",
  message_id: "assistant:projection-hydration:1",
  stream_run_id: "strun:projection-hydration:1",
  run_id: "strun:projection-hydration:1",
  task_run_id: "taskrun:projection-hydration:1",
  turn_run_id: "turnrun:projection-hydration:1",
};

function messages(): Message[] {
  return [
    {
      id: "user:projection-hydration:1",
      role: "user",
      content: "执行任务",
      toolCalls: [],
      retrievals: [],
      sourceIndex: 0,
      sourceTurnId: anchor.turn_id,
    },
    {
      id: anchor.message_id,
      role: "assistant",
      content: "最终正文。",
      toolCalls: [],
      retrievals: [],
      sourceIndex: 1,
      sourceTurnId: anchor.turn_id,
    },
  ];
}

function frame(patch: Partial<PublicProjectionFrame> & { frame_id: string; event_offset: number }): PublicProjectionFrame {
  return {
    authority: "harness.public_projection",
    contract_revision: "20260614-dual-channel-v1",
    channel: "body",
    event_family: "assistant_body",
    lossless: true,
    op: "body_append",
    slot: "body",
    source_authority: "model",
    source_event_type: "assistant_text_delta",
    main_visibility: "visible_live",
    retention: "final",
    anchor,
    ...patch,
  };
}

function committedAttachment(frames: PublicProjectionFrame[], patch: Partial<ProjectionSlice> = {}): SessionRuntimeAttachment {
  return {
    attachment_id: "runtime-attachment:strun:projection-hydration:1",
    run_id: anchor.stream_run_id,
    stream_run_id: anchor.stream_run_id,
    event_log_id: "chatrun:projection-hydration:1",
    anchor_turn_id: anchor.turn_id,
    anchor_message_id: anchor.message_id,
    anchor_role: "assistant",
    turn_run_id: anchor.turn_run_id,
    task_run_id: anchor.task_run_id,
    status: "completed",
    display_state: "task_closed",
    main_chat_surface: "closeout_summary",
    tool_event_count: 1,
    closeout_summary: "最终正文。",
    log_ref: "chatrun:projection-hydration:1",
    projection_anchor: {
      session_id: anchor.session_id,
      anchor_turn_id: anchor.turn_id,
      anchor_message_id: anchor.message_id,
      stream_run_id: anchor.stream_run_id,
      run_id: anchor.run_id,
      task_run_id: anchor.task_run_id,
      turn_run_id: anchor.turn_run_id,
    },
    projection_slices: [{
      slice_id: "projection-slice:chatrun:projection-hydration:1",
      schema_version: "chronological_projection",
      event_log_id: "chatrun:projection-hydration:1",
      start_offset: frames[0]?.event_offset ?? 0,
      end_offset: frames.at(-1)?.event_offset ?? 0,
      integrity: "complete",
      committed: true,
      projection_key: {
        session_id: anchor.session_id,
        turn_id: anchor.turn_id,
        message_id: anchor.message_id,
        stream_run_id: anchor.stream_run_id,
        run_id: anchor.run_id,
        task_run_id: anchor.task_run_id,
        turn_run_id: anchor.turn_run_id,
        event_log_id: "chatrun:projection-hydration:1",
      },
      cursor: {
        min_event_offset: frames[0]?.event_offset ?? 0,
        max_event_offset: frames.at(-1)?.event_offset ?? 0,
        frame_count: frames.length,
      },
      frames,
      display_hint: {
        lifecycle: "committed",
        main_surface_hint: "closeout",
        closeout_summary: "最终正文。",
        log_ref: "chatrun:projection-hydration:1",
        tool_event_count: 1,
      },
      authority: "session_runtime_timeline.projection_slice",
      ...patch,
    }],
    trace_available: true,
    debug_trace_ref: "chatrun:projection-hydration:1",
  };
}

function completeCommittedFrames() {
  return [
    frame({
      frame_id: "frame:progress-body",
      event_offset: 1,
      source_event_type: "assistant_public_feedback",
      retention: "transient",
      item_id: "assistant-public-feedback:progress",
      text: "收口前的过程正文。",
    }),
    frame({
      frame_id: "frame:tool",
      event_offset: 2,
      channel: "activity",
      event_family: "tool_control",
      op: "item_upsert",
      slot: "current_action",
      source_event_type: "tool_call_requested",
      retention: "transient",
      tool_call_id: "call:read",
      tool_name: "read_file",
      target: "README.md",
      title: "读取文件",
      state: "running",
    }),
    frame({
      frame_id: "frame:after-tool-progress-body",
      event_offset: 3,
      source_event_type: "assistant_public_feedback",
      retention: "transient",
      item_id: "assistant-public-feedback:after-tool-before-final",
      text: "收口前继续输出的正文。",
    }),
    frame({
      frame_id: "frame:streaming-final-delta",
      event_offset: 4,
      source_event_type: "assistant_text_delta",
      retention: "transient",
      text: "最终正文。",
    }),
    frame({
      frame_id: "frame:repair-final-body",
      event_offset: 5,
      op: "body_finalize",
      source_event_type: "assistant_stream_repair",
      retention: "transient",
      main_visibility: "visible_live",
      text: "最终正文。",
    }),
    frame({
      frame_id: "frame:final-body",
      event_offset: 6,
      op: "body_finalize",
      source_event_type: "assistant_text_final",
      main_visibility: "visible_final",
      text: "最终正文。",
    }),
    frame({
      frame_id: "frame:commit",
      event_offset: 7,
      channel: "lifecycle",
      event_family: "runtime_commit",
      op: "commit_ack",
      slot: "trace",
      source_authority: "runtime",
      source_event_type: "session_output_commit_ack",
      main_visibility: "hidden",
      retention: "trace",
      commit: {
        state: "committed",
        commit_event_offset: 4,
        content_sha256: "sha256:final",
      },
    }),
  ];
}

describe("hydrateSessionRuntimeProjection", () => {
  it("replays complete committed slices into archived activity and log entries", () => {
    const hydrated = hydrateSessionRuntimeProjection(
      { messages: messages(), activeProjectionsByKey: {} },
      [committedAttachment(completeCommittedFrames())],
    );

    const assistant = hydrated.messages.find((message) => message.id === anchor.message_id);
    const view = assistant?.projectionKeyString
      ? hydrated.activeProjectionsByKey[assistant.projectionKeyString]?.view
      : undefined;

    expect(view?.displayMode).toBe("committed");
    expect(view?.canonicalContent).toBe("最终正文。");
    expect(view?.blocks).toEqual(expect.arrayContaining([
      expect.objectContaining({
        kind: "activity_archive",
        blocks: expect.arrayContaining([
          expect.objectContaining({
            kind: "body_segment",
            sourceEventType: "assistant_public_feedback",
            text: "收口前的过程正文。",
          }),
          expect.objectContaining({ kind: "tool_event", toolCallId: "call:read" }),
          expect.objectContaining({
            kind: "body_segment",
            sourceEventType: "assistant_public_feedback",
            text: "收口前继续输出的正文。",
          }),
        ]),
      }),
      expect.objectContaining({ kind: "log_entry", toolEventCount: 1 }),
    ]));
    const archive = view?.blocks.find((block) => block.kind === "activity_archive");
    expect(archive).toEqual(expect.objectContaining({
      blocks: expect.not.arrayContaining([
        expect.objectContaining({ kind: "body_segment", sourceEventType: "assistant_text_delta" }),
        expect.objectContaining({ kind: "body_segment", sourceEventType: "assistant_stream_repair" }),
        expect.objectContaining({ kind: "body_segment", sourceEventType: "assistant_text_final" }),
      ]),
    }));
    expect(view?.blocks.filter((block) => block.kind === "body_segment")).toEqual([]);
    expect(view?.traceAvailable).toBe(true);
    expect(view?.toolEventCount).toBe(1);
  });

  it("rejects incomplete committed slices instead of hydrating a weak closeout projection", () => {
    const incompleteFrames = [
      frame({
        frame_id: "frame:final-body-only",
        event_offset: 3,
        op: "body_finalize",
        source_event_type: "assistant_text_final",
        main_visibility: "visible_final",
        text: "最终正文。",
      }),
    ];
    const hydrated = hydrateSessionRuntimeProjection(
      { messages: messages(), activeProjectionsByKey: {} },
      [committedAttachment(incompleteFrames, {
        integrity: "incomplete",
        cursor: {
          min_event_offset: 3,
          max_event_offset: 4,
          frame_count: 2,
        },
      })],
    );

    const assistant = hydrated.messages.find((message) => message.id === anchor.message_id);

    expect(assistant?.projectionKeyString).toBeUndefined();
    expect(hydrated.activeProjectionsByKey).toEqual({});
  });
});
