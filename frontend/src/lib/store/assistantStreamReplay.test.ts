import { describe, expect, it } from "vitest";

import { getDefaultState } from "./core";
import { reduceStreamEvent, startStreamingTurn } from "./events";

describe("assistant typed stream replay", () => {
  it("drops duplicate assistant_text_delta frames by sequence", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
    const frame = {
      sequence: 1,
      content: "第一段",
      content_utf8_start: 0,
      accumulated_utf8_bytes: 9,
      accumulated_sha256: "sha256:first",
    };

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", frame);
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", frame);

    expect(transition.state.messages.at(-1)?.content).toBe("第一段");
    expect(transition.state.assistantTextStreamsByMessageId[transition.session.assistantId]?.latestSequence).toBe(1);
  });

  it("merges CJK deltas by UTF-8 byte offsets", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: "遇到",
      content_utf8_start: 0,
      accumulated_utf8_bytes: 6,
      accumulated_sha256: "sha256:first",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 2,
      content: "前端",
      content_utf8_start: 6,
      accumulated_utf8_bytes: 12,
      accumulated_sha256: "sha256:second",
    });

    const assistant = transition.state.messages.at(-1);
    const stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("遇到前端");
    expect(stream?.latestSequence).toBe(2);
    expect(stream?.repairState).toBe("none");
  });

  it("preserves whitespace-only delta frames so byte offsets do not strand the visible prefix", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: "Lang",
      content_utf8_start: 0,
      accumulated_utf8_bytes: 4,
      accumulated_sha256: "sha256:lang",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 2,
      content: "\n\n",
      content_utf8_start: 4,
      accumulated_utf8_bytes: 6,
      accumulated_sha256: "sha256:break",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 3,
      content: "Chain-Agent",
      content_utf8_start: 6,
      accumulated_utf8_bytes: 17,
      accumulated_sha256: "sha256:full",
    });

    const assistant = transition.state.messages.at(-1);
    const stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("Lang\n\nChain-Agent");
    expect(stream?.canonicalContent).toBe("Lang\n\nChain-Agent");
    expect(stream?.latestSequence).toBe(3);
    expect(stream?.repairState).toBe("none");
  });

  it("preserves final answer whitespace instead of normalizing the model body", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 1,
      content: "第一行\n\n第二行  ",
      content_sha256: "sha256:final",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });

    const assistant = transition.state.messages.at(-1);
    const stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("第一行\n\n第二行  ");
    expect(stream?.canonicalContent).toBe("第一行\n\n第二行  ");
    expect(stream?.finalReceived).toBe(true);
  });

  it("appends a repeated final frame with the same stream ref as a new body segment", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 1,
      stream_ref: "stream:progressive",
      content: "第一段完成",
      content_sha256: "sha256:first",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 2,
      stream_ref: "stream:progressive",
      content: "第二段推进",
      content_sha256: "sha256:second",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });

    const assistant = transition.state.messages.at(-1);
    const stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("第一段完成\n\n第二段推进");
    expect(stream?.orderedSegmentIds).toHaveLength(2);
    expect(stream?.finalReceived).toBe(true);
  });

  it("only appends the suffix when a repeated final frame sends cumulative content", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 1,
      message_ref: "message:progressive",
      content: "第一段完成",
      content_sha256: "sha256:first",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 2,
      message_ref: "message:progressive",
      content: "第一段完成\n\n第二段推进",
      content_sha256: "sha256:cumulative",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });

    const assistant = transition.state.messages.at(-1);
    const stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("第一段完成\n\n第二段推进");
    expect(stream?.orderedSegmentIds).toHaveLength(2);
  });

  it("applies repair replacement without waiting for legacy done content", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: "错字",
      content_utf8_start: 0,
      accumulated_utf8_bytes: 6,
      accumulated_sha256: "sha256:bad",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_stream_repair", {
      repair_sequence: 2,
      applies_after_sequence: 1,
      replacement_content: "正确答案",
      replacement_content_sha256: "sha256:fixed",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 3,
      content: "正确答案",
      content_sha256: "sha256:fixed",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "旧 done 不应覆盖",
    });

    const assistant = transition.state.messages.at(-1);
    const stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("正确答案");
    expect(stream?.repairState).toBe("applied");
    expect(stream?.finalReceived).toBe(true);
  });

  it("keeps contiguous mismatched offset deltas visible while marking the stream for repair", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: "第一段",
      content_utf8_start: 0,
      accumulated_utf8_bytes: 9,
      accumulated_sha256: "sha256:first",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 2,
      content: "错位内容",
      content_utf8_start: 999,
      accumulated_utf8_bytes: 21,
      accumulated_sha256: "sha256:mismatch",
    });

    let assistant = transition.state.messages.at(-1);
    let stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("第一段错位内容");
    expect(stream?.canonicalContent).toBe("第一段错位内容");
    expect(stream?.latestSequence).toBe(2);
    expect(stream?.repairState).toBe("pending");

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 3,
      content: "第一段正确收口",
      content_sha256: "sha256:final",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });

    assistant = transition.state.messages.at(-1);
    stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("第一段正确收口");
    expect(stream?.repairState).toBe("applied");
    expect(stream?.finalReceived).toBe(true);
  });

  it("keeps CJK streams visible when upstream reports character offsets instead of UTF-8 bytes", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 1,
      content: "测试",
      content_utf8_start: 0,
      accumulated_utf8_bytes: 6,
      accumulated_sha256: "sha256:first",
    });
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 2,
      content: "继续",
      content_utf8_start: 2,
      accumulated_utf8_bytes: 4,
      accumulated_sha256: "sha256:char-offset",
    });

    const assistant = transition.state.messages.at(-1);
    const stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("测试继续");
    expect(stream?.canonicalContent).toBe("测试继续");
    expect(stream?.latestSequence).toBe(2);
    expect(stream?.accumulatedUtf8Bytes).toBe(12);
    expect(stream?.repairState).toBe("pending");
  });

  it("does not display a non-initial first delta when offset metadata is missing", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_delta", {
      sequence: 2,
      content: "后半段",
      accumulated_utf8_bytes: 9,
      accumulated_sha256: "sha256:tail",
    });

    let assistant = transition.state.messages.at(-1);
    let stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("");
    expect(stream?.latestSequence).toBe(0);
    expect(stream?.repairState).toBe("pending");

    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text_final", {
      sequence: 3,
      content: "完整答案",
      content_sha256: "sha256:final",
      answer_channel: "conversation",
      answer_canonical_state: "stable_answer",
    });

    assistant = transition.state.messages.at(-1);
    stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("完整答案");
    expect(stream?.repairState).toBe("applied");
  });

  it("drops internal control protocol text from delta, repair, and final frames", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续");
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
    const stream = transition.state.assistantTextStreamsByMessageId[transition.session.assistantId];
    expect(assistant?.content).toBe("");
    expect(stream).toBeUndefined();
  });
});
