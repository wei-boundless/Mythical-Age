import { describe, expect, it } from "vitest";

import { chatMessageRenderKeys, sessionContextMeterPresentation, shouldSuppressSessionActivityBar } from "./ChatPanel";
import type { Message, MessagePublicProjection, TokenStats } from "@/lib/store/types";

function publicProjection(patch: Partial<MessagePublicProjection>): MessagePublicProjection {
  return {
    bodyText: "",
    bodyState: "streaming",
    bodyBlocks: [],
    pinned: [],
    finalResults: [],
    status: [],
    trace: [],
    timeline: [],
    traceAvailable: false,
    traceCount: 0,
    commitState: "none",
    ...patch,
  };
}

function message(patch: Partial<Message>): Message {
  return {
    content: "",
    id: "message:assistant",
    retrievals: [],
    role: "assistant",
    toolCalls: [],
    ...patch,
  };
}

function tokenStats(patch: Partial<TokenStats>): TokenStats {
  return {
    system_tokens: 0,
    message_tokens: 0,
    total_tokens: 0,
    raw_history_tokens: 0,
    history_tokens: 0,
    history_budget_tokens: 1000,
    history_remaining_tokens: 1000,
    history_usage_ratio: 0,
    history_remaining_ratio: 1,
    history_pressure_level: "normal",
    history_compaction_strategy: "none",
    history_did_compact: false,
    history_did_microcompact: false,
    history_did_full_compact: false,
    ...patch,
  };
}

describe("ChatPanel", () => {
  it("hides footer activity during an active assistant turn before model prose arrives", () => {
    expect(shouldSuppressSessionActivityBar([message({})], true)).toBe(true);
  });

  it("keeps footer activity available for an idle assistant message without visible feedback", () => {
    expect(shouldSuppressSessionActivityBar([message({})], false)).toBe(false);
  });

  it("hides footer activity once assistant prose owns visible turn feedback", () => {
    expect(shouldSuppressSessionActivityBar([
      message({ content: "好，我接着处理。" }),
    ], true)).toBe(true);
  });

  it("hides footer activity when publicProjection body owns visible feedback", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        publicProjection: publicProjection({
          bodyText: "我已经形成稳定结论。",
          bodyState: "finalized",
        }),
      }),
    ], true)).toBe(true);
  });

  it("hides footer activity when projection activity exists without promoting it to prose", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        publicProjection: publicProjection({
          currentAction: {
            itemId: "tool:read",
            slot: "current_action",
            text: "读取投影链路",
            state: "running",
            mainVisibility: "visible_live",
            retention: "transient",
            toolCallId: "call:read",
          },
        }),
      }),
    ], true)).toBe(true);
  });

  it("shows current context usage against the auto-compaction threshold", () => {
    expect(sessionContextMeterPresentation(tokenStats({
      context_meter: {
        current_context_ratio: 0.03,
        current_context_tokens: 34000,
        compaction_pressure_tokens: 34000,
        context_window_tokens: 1_000_000,
        replacement_threshold_tokens: 900000,
        compaction_pressure_ratio: 34000 / 900000,
        compaction_remaining_tokens: 866000,
        compaction_remaining_ratio: 866000 / 900000,
        pressure_level: "normal",
      },
      cumulative_transcript_tokens: 52000,
    }))).toEqual({
      label: "上下文",
      usedPercent: 4,
      thresholdPercentText: "4%",
      tokenRatioText: "34.0K/900.0K",
      title: "当前上下文 34,000 tokens；自动压缩阈值 900,000 tokens；阈值占比 4%；模型窗口 1,000,000 tokens；距自动压缩还剩 866,000 tokens",
      levelClass: "normal",
    });
  });

  it("does not mix recovery package status into the context threshold meter", () => {
    expect(sessionContextMeterPresentation(tokenStats({
      context_meter: {
        current_context_tokens: 34000,
        compaction_pressure_tokens: 34000,
        replacement_threshold_tokens: 900000,
        compaction_pressure_ratio: 34000 / 900000,
        compaction_remaining_tokens: 866000,
        pressure_level: "normal",
      },
      context_recovery_package: {
        present: true,
        fresh: true,
        source: "agent:1",
        covered_message_count: 4,
      },
    })).title).not.toContain("恢复包");
  });

  it("keeps the context status slot visible while token stats are loading", () => {
    expect(sessionContextMeterPresentation(null)).toEqual({
      label: "上下文",
      usedPercent: 0,
      thresholdPercentText: "--",
      tokenRatioText: "--",
      title: "正在读取当前 session 上下文状态",
      levelClass: "pending",
    });
  });

  it("does not fall back to history budget when context meter is missing", () => {
    expect(sessionContextMeterPresentation(tokenStats({
      history_tokens: 800,
      history_budget_tokens: 1000,
      history_usage_ratio: 0.8,
      history_pressure_level: "warning",
    }))).toEqual({
      label: "上下文",
      usedPercent: 0,
      thresholdPercentText: "--",
      tokenRatioText: "--",
      title: "正在读取当前 session 上下文状态",
      levelClass: "pending",
    });
  });

  it("keeps duplicate persisted message ids from colliding in React keys", () => {
    expect(chatMessageRenderKeys([
      message({ id: "history-message:turn:1:assistant", role: "assistant", sourceIndex: 1 }),
      message({ id: "history-message:turn:1:assistant", role: "assistant", sourceIndex: 2 }),
      message({ id: "history-message:turn:2:user", role: "user", sourceIndex: 3 }),
    ])).toEqual([
      "history-message:turn:1:assistant",
      "history-message:turn:1:assistant:duplicate-1",
      "history-message:turn:2:user",
    ]);
  });

  it("uses current context rather than internal compaction pressure for the user meter", () => {
    expect(sessionContextMeterPresentation(tokenStats({
      context_meter: {
        current_context_ratio: 0.012598,
        current_context_tokens: 12598,
        compaction_pressure_tokens: 41444,
        context_window_tokens: 1_000_000,
        replacement_threshold_tokens: 850000,
        compaction_pressure_ratio: 41444 / 850000,
        compaction_remaining_tokens: 808556,
        compaction_remaining_ratio: 808556 / 850000,
        pressure_level: "normal",
      },
    }))).toEqual({
      label: "上下文",
      usedPercent: 1,
      thresholdPercentText: "1%",
      tokenRatioText: "12.6K/850.0K",
      title: "当前上下文 12,598 tokens；自动压缩阈值 850,000 tokens；阈值占比 1%；模型窗口 1,000,000 tokens；距自动压缩还剩 837,402 tokens",
      levelClass: "normal",
    });
  });
});
