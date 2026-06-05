import { describe, expect, it } from "vitest";

import {
  assistantContentFromPublicTimeline,
  hasAgentRunProjection,
  looksLikeRawToolOutput,
  projectAgentRun,
} from "./agentRunProjection";

describe("agentRunProjection", () => {
  it("does not synthesize opening prose from tool activity", () => {
    const items = [
      {
        item_id: "tool:agents",
        kind: "tool_activity",
        title: "正在读取文件 langchain-agent/AGENTS.md",
        state: "running",
        stream_state: "streaming",
      },
    ];

    const projection = projectAgentRun(items, "");

    expect(assistantContentFromPublicTimeline("", items)).toBe("");
    expect(projection.opening).toBe("");
    expect(projection.liveAction).toContain("我先读取 langchain-agent/AGENTS.md");
    expect(projection.liveAction).not.toContain("工具");
    expect(hasAgentRunProjection(projection)).toBe(true);
  });

  it("keeps explicit opening judgment as message-level prose only", () => {
    const items = [
      {
        item_id: "opening:1",
        kind: "opening_judgment",
        text: "我先确认现有输出链路，再改公开反馈状态。",
        state: "running",
      },
    ];

    const content = assistantContentFromPublicTimeline("", items);
    const projection = projectAgentRun(items, content);

    expect(content).toBe("我先确认现有输出链路，再改公开反馈状态。");
    expect(projection.opening).toBe("");
    expect(hasAgentRunProjection(projection)).toBe(false);
  });

  it("replaces a running action with the returned observation fact", () => {
    const projection = projectAgentRun([
      {
        item_id: "work:test",
        kind: "work_action",
        action_kind: "verify",
        title: "正在运行验证",
        subject_label: "前端测试",
        public_summary: "正在运行验证 前端测试",
        state: "running",
        stream_state: "streaming",
      },
      {
        item_id: "observation:test",
        kind: "observation_report",
        title: "观察报告",
        detail: "验证已返回，22 tests passed",
        state: "done",
      },
    ]);

    expect(projection.liveAction).toBe("");
    expect(projection.feedback).toBe("验证已返回，22 tests passed。");
    expect(projection.feedback).not.toContain("观察报告");
  });

  it("keeps an observation fact over a stale monitor running action for the same work", () => {
    const projection = projectAgentRun([
      {
        item_id: "observation:test",
        kind: "observation_report",
        title: "观察报告",
        detail: "验证已返回，22 tests passed",
        implication: "下一步会根据测试结果收口。",
        state: "done",
      },
      {
        item_id: "live:stale-verify",
        kind: "work_action",
        action_kind: "verify",
        title: "正在运行验证",
        subject_label: "验证结果",
        public_summary: "正在运行验证 验证结果",
        state: "running",
        stream_state: "streaming",
      },
    ]);

    expect(projection.liveAction).toBe("");
    expect(projection.feedback).toBe("验证已返回，22 tests passed。 下一步会根据测试结果收口。");
    expect(projection.feedback).not.toContain("观察报告");
    expect(projection.feedback).not.toContain("验证验证结果");
  });

  it("still shows a genuinely new running action after an earlier observation", () => {
    const projection = projectAgentRun([
      {
        item_id: "observation:read",
        kind: "observation_report",
        detail: "已读到主会话组件。",
        state: "done",
      },
      {
        item_id: "work:test",
        kind: "work_action",
        action_kind: "verify",
        title: "正在运行验证",
        subject_label: "前端测试",
        public_summary: "正在运行验证 前端测试",
        state: "running",
        stream_state: "streaming",
      },
    ]);

    expect(projection.feedback).toBe("");
    expect(projection.liveAction).toBe("我正在跑前端测试，用结果判断是否还要继续修正。");
  });

  it("makes stopped state exclusive over previous tool failures", () => {
    const projection = projectAgentRun([
      {
        item_id: "tool:error",
        kind: "tool_activity",
        title: "读取失败",
        observation: "Read failed: start_line 900 exceeds total_lines 872",
        state: "error",
      },
      {
        item_id: "stream:stopped",
        kind: "status_update",
        title: "已停止本轮生成",
        detail: "你已停止本轮生成，当前运行不会继续推进。",
        state: "stopped",
        phase: "stopped",
      },
    ]);

    expect(projection.tone).toBe("stopped");
    expect(projection.stopped).toContain("已停止本轮生成");
    expect(projection.liveAction).toBe("");
    expect(projection.feedback).toBe("");
    expect(projection.stopped).not.toContain("Read failed");
  });

  it("suppresses closeout when assistant prose already owns the final answer", () => {
    const projection = projectAgentRun([
      {
        item_id: "final:1",
        kind: "final_summary",
        text: "已完成实现、测试和收口说明。",
        state: "done",
      },
    ], "已完成实现、测试和收口说明。");

    expect(projection.closeout).toBe("");
    expect(hasAgentRunProjection(projection)).toBe(false);
  });

  it("uses final summary as assistant prose when content is otherwise empty", () => {
    const items = [
      {
        item_id: "final:summary",
        kind: "final_summary",
        text: "已完成页面投影修复，最终回答会保留在正文区域。",
        state: "done",
      },
    ];

    const content = assistantContentFromPublicTimeline("", items);
    const projection = projectAgentRun(items, content);

    expect(content).toBe("已完成页面投影修复，最终回答会保留在正文区域。");
    expect(projection.closeout).toBe("");
    expect(hasAgentRunProjection(projection)).toBe(false);
  });

  it("turns raw file listing observations into natural public feedback", () => {
    const projection = projectAgentRun([
      {
        item_id: "work:list",
        kind: "work_action",
        action_kind: "inspect",
        title: "已确认目标",
        observation: "file frontend/src/app/adventure-island/assets.ts 2938 bytes file frontend/src/app/adventure-island/config.ts 5177 bytes file frontend/src/app/adventure-island/game-data.ts 23749 bytes",
        state: "done",
      },
    ]);

    expect(projection.feedback).toContain("已确认 app/adventure-island 下的相关文件");
    expect(projection.feedback).not.toContain("2938 bytes");
    expect(projection.feedback).not.toContain("assets.ts");
    expect(projection.feedback).not.toContain("file frontend");
  });

  it("projects copied shell output as natural feedback with folded command output", () => {
    const items = [
      {
        item_id: "work:copy-assets",
        kind: "work_action",
        action_kind: "run",
        title: "复制素材",
        observation: "Copied: game-boss-demon-king.png Copied: game-map-castle.png",
        state: "done",
      },
    ];
    const projection = projectAgentRun(items);

    expect(assistantContentFromPublicTimeline("", items)).toBe("");
    expect(projection.feedback).toBe("已复制 2 个素材文件，下一步会确认目标页面是否能正确引用。");
    expect(projection.feedback).not.toContain("Copied:");
    expect(projection.commandOutput?.label).toBe("终端");
    expect(projection.commandOutput?.content).toContain("Copied: game-boss-demon-king.png");
    expect(projection.commandOutput?.content).toContain("Copied: game-map-castle.png");
  });

  it("classifies read-only shell validator failures as raw internal output", () => {
    const raw = "shell command executable is not allowlisted read-only";
    const projection = projectAgentRun([
      {
        item_id: "blocked:shell",
        kind: "blocked",
        text: raw,
        state: "error",
      },
    ]);

    expect(looksLikeRawToolOutput(raw)).toBe(true);
    expect(assistantContentFromPublicTimeline(raw, [])).toBe("");
    expect(projection.feedback).toBe("命令被只读权限拦截，我会改用允许的读取方式继续。");
    expect(projection.feedback).not.toContain("allowlisted");
  });

  it("classifies persisted tool result read failures as raw internal output", () => {
    const raw = "Read persisted tool result failed: D:\\AI应用\\langchain-agent\\backend\\storage\\task_environments\\general\\workspace\\runtime_state\\storage\\runtime_context\\tool-results\\session-fad8ee446.txt";
    const projection = projectAgentRun([
      {
        item_id: "blocked:persisted-tool-result",
        kind: "blocked",
        text: raw,
        state: "error",
      },
    ]);

    expect(looksLikeRawToolOutput(raw)).toBe(true);
    expect(assistantContentFromPublicTimeline(raw, [])).toBe("");
    expect(projection.feedback).toBe("上一段执行结果没有成功读回，我会重新获取可用结果后继续判断。");
    expect(projection.feedback).not.toContain("runtime_state");
    expect(projection.feedback).not.toContain("tool-results");
  });

  it("does not promote raw file listing final summaries to assistant prose", () => {
    const items = [
      {
        item_id: "final:raw",
        kind: "final_summary",
        text: "file frontend/src/app/adventure-island/assets.ts 2938 bytes file frontend/src/app/adventure-island/config.ts 5177 bytes",
        state: "done",
      },
    ];

    expect(assistantContentFromPublicTimeline("", items)).toBe("");
    expect(hasAgentRunProjection(projectAgentRun(items, ""))).toBe(false);
  });

  it("does not keep raw file listing content as assistant prose fallback", () => {
    expect(assistantContentFromPublicTimeline(
      "file frontend/src/app/adventure-island/assets.ts 2938 bytes file frontend/src/app/adventure-island/config.ts 5177 bytes",
      [],
    )).toBe("");
  });
});
