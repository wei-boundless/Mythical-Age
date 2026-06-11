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

  it("suppresses line-numbered tool output before timeline items reach chat rendering", () => {
    const rawFilePreview = "  1 | # LangChain-Agent 项目代码审查报告\n  2 | 这是一段工具读取的文件原文";

    expect(sanitizePublicTimelineText(rawFilePreview)).toBe("");
    expect(mergePublicTimelineItems([], [
      {
        item_id: "body:raw-file",
        kind: "final_summary",
        slot: "body",
        surface: "assistant_body",
        source_authority: "model",
        text: rawFilePreview,
        state: "done",
      },
    ])).toEqual([]);
  });

  it("suppresses runtime-private artifact paths before timeline rendering", () => {
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
      expect(sanitizePublicTimelineText(privatePath)).toBe("");
    }
    expect(mergePublicTimelineItems([], [
      {
        item_id: "private:path",
        kind: "status_update",
        title: privatePaths[0],
        state: "running",
      },
    ])).toEqual([]);
  });

});
