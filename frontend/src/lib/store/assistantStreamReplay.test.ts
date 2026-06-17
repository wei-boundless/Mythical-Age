import { beforeEach, describe, expect, it } from "vitest";

import type { PublicProjectionFrame } from "@/lib/api";
import type { StoreState } from "@/lib/store/types";
import { getDefaultState } from "./core";
import { reduceStreamEvent, startStreamingTurn } from "./events";

let frameOffset = 0;

function projectionFrame(patch: Partial<PublicProjectionFrame>): PublicProjectionFrame {
  frameOffset += 1;
  return {
    authority: "harness.public_projection",
    contract_revision: "20260614-dual-channel-v1",
    frame_id: `frame:assistant:${frameOffset}`,
    event_offset: frameOffset,
    event_family: "assistant_body",
    channel: "body",
    lossless: true,
    anchor: {
      turn_id: "turn:assistant-stream:1",
      turn_run_id: "turnrun:assistant-stream:1",
      run_id: "turnrun:assistant-stream:1",
    },
    op: "body_append",
    slot: "body",
    source_authority: "model",
    main_visibility: "visible_live",
    retention: "final",
    ...patch,
  };
}

function startBoundTurn() {
  let transition = startStreamingTurn(getDefaultState(), "继续");
  transition = reduceStreamEvent(transition.state, transition.session, "harness_run_started", {
    turn_run: {
      turn_id: "turn:assistant-stream:1",
      turn_run_id: "turnrun:assistant-stream:1",
    },
  });
  return transition;
}

function project(transition: ReturnType<typeof startStreamingTurn>, patch: Partial<PublicProjectionFrame>) {
  return reduceStreamEvent(transition.state, transition.session, "public_projection_frame", {
    public_projection_frame: projectionFrame(patch),
  });
}

function latestProjection(state: StoreState) {
  const assistant = state.messages.at(-1);
  const key = assistant?.projectionKeyString ?? "";
  return key ? state.activeProjectionsByKey[key]?.view : undefined;
}

function latestLedger(state: StoreState) {
  const assistant = state.messages.at(-1);
  const key = assistant?.projectionKeyString ?? "";
  return key ? state.activeProjectionsByKey[key]?.ledger : undefined;
}

describe("assistant chronological projection replay", () => {
  beforeEach(() => {
    frameOffset = 0;
  });

  it("does not let bare assistant_text_delta write the visible message body", () => {
    let transition = startBoundTurn();

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: "第一段",
      content_utf8_start: 0,
      accumulated_utf8_bytes: 9,
      accumulated_sha256: "sha256:first",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 2,
      content: "第一段完成",
      content_sha256: "sha256:final",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.projectionView).toBeUndefined();
    expect(transition.state.assistantTextStreamsByMessageId[transition.session.assistantId]).toBeUndefined();
  });

  it("progressively appends CJK body text from projection frames", () => {
    let transition = startBoundTurn();
    transition = project(transition, { text: "遇到" });
    transition = project(transition, { text: "前端" });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(latestProjection(transition.state)?.canonicalContent).toBe("遇到前端");
    expect(latestProjection(transition.state)?.bodyState).toBe("streaming");
    expect(latestLedger(transition.state)?.cursor).toMatchObject({ minOffset: 1, maxOffset: 2 });
  });

  it("preserves whitespace supplied by body frames", () => {
    let transition = startBoundTurn();
    transition = project(transition, { text: "Lang" });
    transition = project(transition, { text: "\n\n" });
    transition = project(transition, { text: "Chain-Agent" });

    expect(transition.state.messages.at(-1)?.content).toBe("");
    expect(latestProjection(transition.state)?.canonicalContent).toBe("Lang\n\nChain-Agent");
  });

  it("does not grow body block frame id lists for every streamed token", () => {
    let transition = startBoundTurn();
    transition = project(transition, { text: "甲" });
    transition = project(transition, { text: "乙" });
    transition = project(transition, { text: "丙" });

    const ledger = latestLedger(transition.state);
    expect(ledger?.cursor).toMatchObject({ minOffset: 1, maxOffset: 3 });
    expect(ledger?.bodySegments).toHaveLength(1);
    expect(ledger?.bodySegments[0]?.sourceKeys).toEqual(["turnrun:assistant-stream:1:1:frame:assistant:1"]);
  });

  it("finalizes body text without waiting for legacy done content", () => {
    let transition = startBoundTurn();
    transition = project(transition, {
      op: "body_append",
      text: "临时",
    });
    transition = project(transition, {
      op: "body_finalize",
      main_visibility: "visible_final",
      text: "正确答案",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "旧 done 不应覆盖",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(latestProjection(transition.state)?.canonicalContent).toBe("正确答案");
    expect(latestProjection(transition.state)?.bodyState).toBe("finalized");
  });

  it("drops internal control protocol text when it arrives outside public projection", () => {
    let transition = startBoundTurn();
    const rawAction = '{"authority":"harness.loop.model_action_request","action_type":"active_work_control","active_work_control":{"action":"continue_active_work"}}';

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: rawAction,
      content_utf8_start: 0,
      accumulated_utf8_bytes: rawAction.length,
      accumulated_sha256: "sha256:raw-delta",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_stream_repair", {
      repair_sequence: 2,
      applies_after_sequence: 1,
      replacement_content: rawAction,
      replacement_content_sha256: "sha256:raw-repair",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 3,
      content: rawAction,
      content_sha256: "sha256:raw-final",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
      answer_persist_policy: "persist_canonical",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.projectionView).toBeUndefined();
  });
});
