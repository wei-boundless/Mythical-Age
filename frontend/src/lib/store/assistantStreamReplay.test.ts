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
});
