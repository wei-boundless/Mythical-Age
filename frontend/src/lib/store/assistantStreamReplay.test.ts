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

  it("keeps mismatched offset deltas out of visible content until final repair", () => {
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
    expect(assistant?.content).toBe("第一段");
    expect(stream?.canonicalContent).toBe("第一段");
    expect(stream?.latestSequence).toBe(1);
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
});
