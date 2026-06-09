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
  it("keeps the footer activity when the latest assistant message only has message-level public timeline", () => {
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

    expect(shouldSuppressSessionActivityBar(messages, true)).toBe(false);
  });

  it("keeps the footer activity available when no message-level feedback exists", () => {
    expect(shouldSuppressSessionActivityBar([message({})], true)).toBe(false);
  });

  it("hides the footer activity once assistant prose owns the visible turn feedback", () => {
    expect(shouldSuppressSessionActivityBar([
      message({ content: "好，我接着处理。" }),
    ], true)).toBe(true);
  });

  it("keeps the footer activity when only projected body timeline exists", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        runtimePublicTimelineDraft: [
          {
            kind: "assistant_text",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "我正在接回刚才的运行。",
            state: "running",
          },
        ],
      }),
    ], true)).toBe(false);
  });

  it("keeps footer activity when runtime control has no assistant prose", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        answerChannel: "runtime_control",
        content: "",
      }),
    ], false)).toBe(false);
  });

  it("keeps footer activity for waiting public timeline without backend projection", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        runtimePublicTimelineDraft: [
          {
            item_id: "live:task:monitor-status",
            kind: "status_update",
            slot: "status",
            surface: "status_bar",
            source_authority: "runtime",
            title: "等待继续",
            detail: "当前任务已停在等待队列，继续后会接上现有进度。",
            state: "waiting",
            phase: "waiting",
          },
        ],
      }),
    ], false)).toBe(false);
  });

  it("suppresses footer status when ask-user question is shown as assistant content", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        runtimePublicTimelineDraft: [
          {
            item_id: "control:ask-user",
            kind: "status_update",
            slot: "control",
            surface: "control",
            source_authority: "system",
            phase: "waiting_user",
            title: "等待补充信息",
            detail: "请补充要优先审查的范围。",
            state: "waiting",
          },
        ],
      }),
    ], false)).toBe(true);
  });

  it("suppresses footer status when a task projection owns the message-level activity", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:projection",
            anchor_turn_id: "turn:projection",
            run_id: "taskrun:projection",
            task_run_id: "taskrun:projection",
            status: "running",
            task_projection: {
              projection_id: "projection:taskrun",
              authority: "runtime_projection",
              task_run_id: "taskrun:projection",
              status: "running",
              todo: {
                active_item_id: "todo:1",
                completion_ready: false,
                items: [{ todo_id: "todo:1", content: "处理任务", status: "in_progress" }],
              },
            },
          },
        ],
        runtimePublicTimelineDraft: [
          {
            item_id: "stage:thinking",
            kind: "status_update",
            slot: "status",
            surface: "status_bar",
            source_authority: "system",
            title: "正在思考",
            state: "running",
          },
        ],
      }),
    ], true)).toBe(true);
  });

  it("still suppresses footer status for ask-user control when a task projection exists", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:projection",
            anchor_turn_id: "turn:projection",
            run_id: "taskrun:projection",
            task_run_id: "taskrun:projection",
            status: "waiting_executor",
            task_projection: {
              projection_id: "projection:taskrun",
              authority: "runtime_projection",
              task_run_id: "taskrun:projection",
              status: "waiting_user",
              todo: {
                active_item_id: "todo:1",
                completion_ready: false,
                items: [{ todo_id: "todo:1", content: "等待补充", status: "in_progress" }],
              },
            },
          },
        ],
        runtimePublicTimelineDraft: [
          {
            item_id: "control:ask-user",
            kind: "status_update",
            slot: "control",
            surface: "control",
            source_authority: "system",
            phase: "waiting_user",
            title: "等待补充信息",
            detail: "请补充要优先审查的范围。",
            state: "waiting",
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

  it("shows current session pressure ratio when near compaction", () => {
    expect(sessionContextPressurePresentation(tokenStats({
      context_meter: {
        current_context_ratio: 0.82,
        current_context_tokens: 820000,
        compaction_pressure_tokens: 820000,
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
      title: "当前上下文压力 820,000 tokens；自动压缩阈值 900,000 tokens；距自动压缩还剩 80,000 tokens；阈值占比 91%；达到阈值会触发自动压缩",
      levelClass: "warning",
    });
  });

  it("shows compacted state without falling back to cumulative transcript pressure", () => {
    expect(sessionContextPressurePresentation(tokenStats({
      context_meter: {
        current_context_ratio: 0.12,
        current_context_tokens: 120000,
        compaction_pressure_tokens: 120000,
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
