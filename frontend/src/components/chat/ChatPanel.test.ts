import { describe, expect, it } from "vitest";

import { chatMessageRenderKeys, sessionContextPressurePresentation, shouldSuppressSessionActivityBar } from "./ChatPanel";
import type { Message, MessagePublicProjection, TokenStats } from "@/lib/store/types";

function publicProjection(patch: Partial<MessagePublicProjection>): MessagePublicProjection {
  return {
    bodyText: "",
    bodyState: "streaming",
    pinned: [],
    finalResults: [],
    status: [],
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
  it("keeps footer activity available when no message-level public projection exists", () => {
    expect(shouldSuppressSessionActivityBar([message({})], true)).toBe(false);
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

  it("hides footer activity when publicProjection action owns visible feedback", () => {
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

  it("shows context pressure ratio even when pressure is normal", () => {
    expect(sessionContextPressurePresentation(tokenStats({
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
      pressurePercentText: "4%",
      tokenRatioText: "34.0K/900.0K",
      title: "当前上下文压力 34,000 tokens；自动压缩阈值 900,000 tokens；距自动压缩还剩 866,000 tokens；阈值占比 4%；达到阈值会触发自动压缩",
      levelClass: "normal",
    });
  });

  it("includes context recovery package freshness in the pressure title", () => {
    expect(sessionContextPressurePresentation(tokenStats({
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
    })).title).toContain("恢复包 fresh；恢复包来源 agent:1；恢复包覆盖 4 条消息");
  });

  it("keeps the context status slot visible while token stats are loading", () => {
    expect(sessionContextPressurePresentation(null)).toEqual({
      label: "上下文",
      usedPercent: 0,
      pressurePercentText: "--",
      tokenRatioText: "--",
      title: "正在读取当前 session 上下文状态",
      levelClass: "pending",
    });
  });

  it("does not fall back to history budget when context meter is missing", () => {
    expect(sessionContextPressurePresentation(tokenStats({
      history_tokens: 800,
      history_budget_tokens: 1000,
      history_usage_ratio: 0.8,
      history_pressure_level: "warning",
    }))).toEqual({
      label: "上下文",
      usedPercent: 0,
      pressurePercentText: "--",
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

  it("uses compaction pressure tokens for the visible ratio when session pressure is lower", () => {
    expect(sessionContextPressurePresentation(tokenStats({
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
      usedPercent: 5,
      pressurePercentText: "5%",
      tokenRatioText: "41.4K/850.0K",
      title: "当前上下文压力 41,444 tokens；会话公开历史 12,598 tokens；自动压缩阈值 850,000 tokens；距自动压缩还剩 808,556 tokens；阈值占比 5%；达到阈值会触发自动压缩",
      levelClass: "normal",
    });
  });
});
