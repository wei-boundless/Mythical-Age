import { describe, expect, it } from "vitest";

import {
  mergePublicTimelineItems,
  sanitizePublicTimelineText,
  publicTimelineTerminalStateFromAnswer,
} from "@/lib/projection/timeline";

describe("publicTimeline", () => {
  it("reconciles started and completed tool activity by semantic target", () => {
    const items = mergePublicTimelineItems(
      [
        {
          item_id: "event:start",
          kind: "tool_activity",
          title: "正在调用 storage/task_environments/general/workspace/artifacts/football.html",
          state: "running",
          stream_state: "streaming",
        },
      ],
      [
        {
          item_id: "event:done",
          kind: "tool_activity",
          title: "工具已完成 storage/task_environments/general/workspace/artifacts/football.html",
          state: "done",
        },
      ],
    );

    expect(items).toEqual([
      expect.objectContaining({
        item_id: "event:done",
        title: "工具已完成 storage/task_environments/general/workspace/artifacts/football.html",
        state: "done",
      }),
    ]);
  });

  it("finalizes streaming draft items when the owning turn is terminal", () => {
    const items = mergePublicTimelineItems(
      [
        {
          item_id: "tool:write",
          kind: "tool_activity",
          title: "正在写入 docs/plan.md",
          state: "running",
          stream_state: "streaming",
        },
      ],
      undefined,
      { terminalState: "done" },
    );

    expect(items).toEqual([
      expect.objectContaining({
        item_id: "tool:write",
        state: "done",
        stream_state: "done",
      }),
    ]);
  });

  it("maps stable assistant answers to terminal timeline state", () => {
    expect(publicTimelineTerminalStateFromAnswer({
      answerCanonicalState: "stable_answer",
      answerChannel: "conversation",
    })).toBe("done");
    expect(publicTimelineTerminalStateFromAnswer({
      answerCanonicalState: "missing_answer",
      answerChannel: "blocked",
    })).toBe("error");
  });

  it("does not treat task opening judgments as terminal answers", () => {
    expect(publicTimelineTerminalStateFromAnswer({
      answerCanonicalState: "stable_answer",
      answerChannel: "opening_judgment",
    })).toBe("");
  });

  it("orders public timeline items by backend event sequence across incoming batches", () => {
    const items = mergePublicTimelineItems(
      [
        {
          item_id: "event:3",
          kind: "status_update",
          title: "第三步",
          state: "running",
          sequence: 3,
          event_offset: 3,
          created_at: 30,
          source_event_id: "event:3",
        },
      ],
      [
        {
          item_id: "event:1",
          kind: "status_update",
          title: "第一步",
          state: "running",
          sequence: 1,
          event_offset: 1,
          created_at: 10,
          source_event_id: "event:1",
        },
        {
          item_id: "event:2",
          kind: "work_action",
          slot: "tool",
          surface: "tool_window",
          title: "第二步",
          public_summary: "第二步",
          subject_label: "docs/a.md",
          state: "done",
          sequence: 2,
          event_offset: 2,
          created_at: 20,
          source_event_id: "event:2",
        },
      ],
    );

    expect(items.map((item) => item.item_id)).toEqual(["event:1", "event:2", "event:3"]);
  });

  it("keeps the earliest sequence when reconciling a tool lifecycle", () => {
    const items = mergePublicTimelineItems(
      [
        {
          item_id: "tool:read",
          kind: "work_action",
          slot: "tool",
          surface: "tool_window",
          action_kind: "read",
          title: "正在读取上下文",
          subject_label: "docs/a.md",
          public_summary: "正在读取上下文：docs/a.md",
          state: "running",
          sequence: 4,
          event_offset: 4,
          source_event_id: "event:start",
        },
      ],
      [
        {
          item_id: "tool:read",
          kind: "work_action",
          slot: "tool",
          surface: "tool_window",
          action_kind: "read",
          title: "已读取上下文",
          subject_label: "docs/a.md",
          public_summary: "已读取上下文：docs/a.md",
          state: "done",
          sequence: 9,
          event_offset: 9,
          source_event_id: "event:done",
        },
      ],
    );

    expect(items).toEqual([
      expect.objectContaining({
        item_id: "tool:read",
        state: "done",
        sequence: 4,
        event_offset: 4,
        source_event_id: "event:start",
        updated_event_offset: 9,
        updated_source_event_id: "event:done",
      }),
    ]);
  });

  it("keeps line-numbered text as ordinary timeline text", () => {
    const rawFilePreview = "  1 | # LangChain-Agent 项目代码审查报告\n  2 | 这是一段工具读取的文件原文";

    expect(sanitizePublicTimelineText(rawFilePreview)).toBe(rawFilePreview.trim().replace(/[ \t\f\v]+/g, " "));
  });

  it("keeps artifact paths as ordinary timeline text", () => {
    const privatePaths = [
      "D:\\AI应用\\langchain-agent\\backend\\storage\\task_environments\\general\\workspace\\runtime_state\\dynamic_context\\replacements\\replacement_4ce5ea91846e3d4e34ff823e.json",
      "storage/runtime_context/tool_results/session-fad8ee446.txt",
      "runtime_context/tool-results/session-fad8ee446.txt",
      "runtime_state/tool_results/session/content-secret.txt",
      "backend/mythical-agent/sessions/session-123/environments/coding/vibe-workspace/runtime_state/dynamic_context/replacements/replacement_e21050df8baca858bdde6a4d.json",
      "replacement_e21050df8baca858bdde6a4d.json",
      "replacement:e21050df8baca858bdde6a4d",
    ];

    for (const privatePath of privatePaths) {
      expect(sanitizePublicTimelineText(privatePath)).toBe(privatePath);
    }
    expect(mergePublicTimelineItems([], [
      {
        item_id: "private:path",
        kind: "status_update",
        title: privatePaths[0],
        state: "running",
      },
    ])).toEqual([
      expect.objectContaining({
        item_id: "private:path",
        title: privatePaths[0],
      }),
    ]);
  });

});
