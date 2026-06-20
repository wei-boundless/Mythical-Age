import { describe, expect, it } from "vitest";

import {
  chatMessageRenderKeys,
  chatTaskMonitorIsActive,
  liveAssistantMessageIdForMessages,
  sessionContextMeterPresentation,
  shouldSuppressSessionActivityBar,
} from "./ChatPanel";
import type { ChronologicalProjectionView } from "@/lib/projection/chronological";
import type { Message, TokenStats } from "@/lib/store/types";

function projectionView(patch: Partial<ChronologicalProjectionView>): ChronologicalProjectionView {
  return {
    displayMode: "live",
    canonicalContent: "",
    copyText: "",
    bodyState: "streaming",
    blocks: [],
    toolEventCount: 0,
    traceAvailable: false,
    diagnostics: [],
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

  it("hides footer activity when projection body owns visible feedback", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        projectionView: projectionView({
          canonicalContent: "我已经形成稳定结论。",
          copyText: "我已经形成稳定结论。",
          bodyState: "finalized",
        }),
      }),
    ], true)).toBe(true);
  });

  it("hides footer activity when projection activity exists without promoting it to prose", () => {
    expect(shouldSuppressSessionActivityBar([
      message({
        projectionView: projectionView({
          blocks: [{
            kind: "tool_event",
            id: "tool:read",
            title: "读取投影链路",
            detail: "",
            state: "running",
            target: "",
            commandLine: "read_file",
            output: "系统调用运行中。",
            toolCallId: "call:read",
            toolLifecycleId: "",
            toolName: "read_file",
            actionKind: "",
            argumentsPreview: "",
            sourceItemId: "",
            sourceEventType: "tool_call_requested",
            sourceEventId: "event:tool",
            firstOffset: 1,
            lastOffset: 1,
          }],
          toolEventCount: 1,
          traceAvailable: true,
        }),
      }),
    ], true)).toBe(true);
  });

  it("shows the compaction trigger window against the auto-compaction threshold", () => {
    expect(sessionContextMeterPresentation(tokenStats({
      context_meter: {
        current_context_ratio: 0.03,
        current_context_tokens: 74252,
        compaction_pressure_tokens: 74252,
        context_window_tokens: 1_000_000,
        replacement_threshold_tokens: 900000,
        compaction_pressure_ratio: 74252 / 900000,
        compaction_remaining_tokens: 825748,
        compaction_remaining_ratio: 825748 / 900000,
        pressure_level: "normal",
      },
      cumulative_transcript_tokens: 38370,
    }))).toEqual({
      usedPercent: 8,
      usedTokenText: "74.3K",
      thresholdTokenText: "900.0K",
      title: "压缩触发窗口 74,252 tokens；自动压缩阈值 900,000 tokens；阈值占比 8%；模型窗口 1,000,000 tokens；距自动压缩还剩 825,748 tokens",
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
      usedPercent: 0,
      usedTokenText: "--",
      thresholdTokenText: "--",
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
      usedPercent: 0,
      usedTokenText: "--",
      thresholdTokenText: "--",
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

  it("keeps a running task timeline attached to its bound assistant message after later replies", () => {
    const messages = [
      message({
        id: "assistant:task",
        sourceTaskRunId: "taskrun:active",
        sourceTurnId: "turn:session:3",
      }),
      message({
        id: "assistant:continue",
        sourceTurnId: "turn:session:5",
      }),
    ];

    expect(liveAssistantMessageIdForMessages(messages, {
      activeTurnSnapshot: {
        turn_id: "turn:session:3",
        task_run_id: "taskrun:active",
        state: "running_task",
      },
      currentSessionReceivingStream: true,
      currentTaskIsRunning: true,
      taskGraphLiveMonitor: null,
    })).toBe("assistant:task");
  });

  it("does not move a bound task timeline to the latest assistant when no binding matches", () => {
    expect(liveAssistantMessageIdForMessages([
      message({ id: "assistant:old", sourceTaskRunId: "taskrun:old" }),
      message({ id: "assistant:latest" }),
    ], {
      activeTurnSnapshot: {
        turn_id: "turn:session:3",
        task_run_id: "taskrun:active",
        state: "running_task",
      },
      currentSessionReceivingStream: true,
      currentTaskIsRunning: true,
      taskGraphLiveMonitor: null,
    })).toBe("");
  });

  it("falls back to the latest assistant for an unbound normal stream", () => {
    expect(liveAssistantMessageIdForMessages([
      message({ id: "assistant:old" }),
      message({ id: "assistant:latest" }),
    ], {
      activeTurnSnapshot: null,
      currentSessionReceivingStream: true,
      currentTaskIsRunning: false,
      taskGraphLiveMonitor: null,
    })).toBe("assistant:latest");
  });

  it("ignores stale diagnostic monitors when selecting the live assistant for a new stream", () => {
    expect(liveAssistantMessageIdForMessages([
      message({ id: "assistant:stale", sourceTaskRunId: "taskrun:stale" }),
      message({ id: "assistant:latest" }),
    ], {
      activeTurnSnapshot: null,
      currentSessionReceivingStream: true,
      currentTaskIsRunning: false,
      taskGraphLiveMonitor: {
        task_run_id: "taskrun:stale",
        task_run: { task_run_id: "taskrun:stale", status: "waiting_executor" },
        status: "waiting_executor",
        lifecycle: "stale",
        bucket: "diagnostics",
        stale: true,
        is_live: false,
      } as never,
    })).toBe("assistant:latest");
  });

  it("treats a live task monitor as active even before the session summary catches up", () => {
    expect(chatTaskMonitorIsActive({
      task_run_id: "taskrun:active",
      status: "running",
      lifecycle: "running",
      bucket: "running",
      is_live: true,
      task_run: {
        task_run_id: "taskrun:active",
        status: "running",
      },
    } as never)).toBe(true);
  });

  it("uses the trigger window rather than the model-current context for the user meter", () => {
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
      usedPercent: 5,
      usedTokenText: "41.4K",
      thresholdTokenText: "850.0K",
      title: "压缩触发窗口 41,444 tokens；自动压缩阈值 850,000 tokens；阈值占比 5%；模型窗口 1,000,000 tokens；距自动压缩还剩 808,556 tokens",
      levelClass: "normal",
    });
  });
});
