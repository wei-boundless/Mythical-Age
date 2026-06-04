import { describe, expect, it } from "vitest";

import { sessionContextPressurePresentation, shouldSuppressSessionActivityBar } from "./ChatPanel";
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

  it("shows remaining context tokens and percent even when pressure is normal", () => {
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
      label: "压缩余量",
      usedPercent: 4,
      remainingPercent: 96,
      remainingPercentText: "96%",
      remainingTokens: 866000,
      remainingTokenText: "剩 866.0K",
      title: "当前 session 压缩压力 4%；距离自动压缩阈值 96%；距压缩 866,000 tokens",
      levelClass: "normal",
    });
  });

  it("keeps the context status slot visible while token stats are loading", () => {
    expect(sessionContextPressurePresentation(null)).toEqual({
      label: "上下文同步中",
      usedPercent: 0,
      remainingPercent: 0,
      remainingPercentText: "--",
      remainingTokens: 0,
      remainingTokenText: "",
      title: "正在读取当前 session 上下文状态",
      levelClass: "pending",
    });
  });

  it("shows current session pressure and remaining context when near compaction", () => {
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
      label: "余量偏低",
      usedPercent: 91,
      remainingPercent: 9,
      remainingPercentText: "9%",
      remainingTokens: 80000,
      remainingTokenText: "剩 80.0K",
      title: "当前 session 压缩压力 91%；距离自动压缩阈值 9%；距压缩 80,000 tokens",
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
      label: "已压缩",
      usedPercent: 13,
      remainingPercent: 87,
      remainingPercentText: "87%",
      remainingTokens: 780000,
      remainingTokenText: "剩 780.0K",
      levelClass: "normal",
    });
  });
});
