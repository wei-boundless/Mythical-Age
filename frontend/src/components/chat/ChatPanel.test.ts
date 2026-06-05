import { describe, expect, it } from "vitest";

import { chatMessageRenderKeys, sessionContextPressurePresentation, shouldSuppressSessionActivityBar } from "./ChatPanel";
import type { Message, TokenStats } from "@/lib/store/types";

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
  it("hides the footer activity when the latest assistant message owns live public progress", () => {
    const messages = [
      message({
        runtimePublicTimelineDraft: [
          {
            item_id: "work:image",
            kind: "work_action",
            action_kind: "image",
            public_summary: "正在生成图像",
            state: "running",
            stream_state: "streaming",
          },
        ],
      }),
    ];

    expect(shouldSuppressSessionActivityBar(messages, true)).toBe(true);
  });

  it("keeps the footer activity available when no message-level feedback exists", () => {
    expect(shouldSuppressSessionActivityBar([message({})], true)).toBe(false);
  });

  it("hides the footer activity when assistant prose already owns the live feedback", () => {
    expect(shouldSuppressSessionActivityBar([
      message({ runtimePublicTimelineDraft: [{ kind: "assistant_text", text: "我正在接回刚才的运行。", state: "running" }] }),
    ], true)).toBe(true);
  });

  it("hides the footer activity when active work control feedback is already in assistant prose", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        answerChannel: "active_work_control",
        content: "已加入当前任务队列，会在当前执行中优先纳入。",
      }),
    ], false)).toBe(true);
  });

  it("hides the footer activity when message progress is waiting outside an active stream", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        runtimePublicTimelineDraft: [
          {
            item_id: "live:task:monitor-status",
            kind: "status_update",
            title: "等待继续",
            detail: "当前任务已停在等待队列，继续后会接上现有进度。",
            state: "waiting",
            phase: "waiting",
          },
        ],
      }),
    ], false)).toBe(true);
  });

  it("shows context pressure ratio even when pressure is normal", () => {
    expect(sessionContextPressurePresentation(tokenStats({
      context_meter: {
        current_context_ratio: 0.03,
        current_context_tokens: 34000,
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
      title: "当前上下文 34,000 tokens；自动压缩阈值 900,000 tokens；阈值占比 4%；达到阈值会触发自动压缩",
      levelClass: "normal",
    });
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

  it("shows current session pressure ratio when near compaction", () => {
    expect(sessionContextPressurePresentation(tokenStats({
      context_meter: {
        current_context_ratio: 0.82,
        current_context_tokens: 820000,
        context_window_tokens: 1_000_000,
        replacement_threshold_tokens: 900000,
        compaction_pressure_ratio: 820000 / 900000,
        compaction_remaining_tokens: 80000,
        compaction_remaining_ratio: 80000 / 900000,
        pressure_level: "warning",
      },
      cumulative_transcript_tokens: 2_000_000,
    }))).toEqual({
      label: "上下文",
      usedPercent: 91,
      pressurePercentText: "91%",
      tokenRatioText: "820.0K/900.0K",
      title: "当前上下文 820,000 tokens；自动压缩阈值 900,000 tokens；阈值占比 91%；达到阈值会触发自动压缩",
      levelClass: "warning",
    });
  });

  it("shows compacted state without falling back to cumulative transcript pressure", () => {
    expect(sessionContextPressurePresentation(tokenStats({
      context_meter: {
        current_context_ratio: 0.12,
        current_context_tokens: 120000,
        context_window_tokens: 1_000_000,
        replacement_threshold_tokens: 900000,
        compaction_pressure_ratio: 120000 / 900000,
        compaction_remaining_tokens: 780000,
        compaction_remaining_ratio: 780000 / 900000,
        pressure_level: "normal",
      },
      cumulative_transcript_tokens: 4_000_000,
      history_did_compact: true,
    }))).toMatchObject({
      label: "上下文",
      usedPercent: 13,
      pressurePercentText: "13%",
      tokenRatioText: "120.0K/900.0K",
      levelClass: "normal",
    });
  });
});
