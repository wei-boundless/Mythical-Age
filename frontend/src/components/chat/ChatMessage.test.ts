import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatMessage } from "./ChatMessage";

describe("ChatMessage", () => {
  it("hides task-control receipts when runtime progress is attached", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerChannel: "task_control",
        answerSource: "harness.task_lifecycle",
        content: "我会按这个目标推进：制作复杂版五层地下塔。",
        id: "message:task-control",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:turn:session:1",
            run_id: "taskrun:turn:session:1",
            anchor_turn_id: "turn:session:1",
            status: "failed",
            terminal_reason: "task_executor_schedule_failed",
            public_timeline: [
              {
                item_id: "blocked:image",
                kind: "blocked",
                text: "生图工具未配置，无法完成合同要求的真实美术资产。",
                state: "error",
              },
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("我会按这个目标推进");
    expect(html).toContain("生图工具未配置");
    expect(html).not.toContain("查看执行细节");
    expect(html).not.toContain("查看技术细节");
  });

  it("softens legacy single-turn tool-loop guard messages in history", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerChannel: "blocked",
        answerSource: "harness.single_agent_turn.tool_loop",
        content: "本轮工具观察次数已达到上限，我需要先停止并请你确认下一步。",
        id: "message:legacy-tool-loop",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("本轮工具观察次数已达到上限");
    expect(html).toContain("基于已有事实收口说明");
  });

  it("keeps task opening prose visible before runtime activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerChannel: "task_control",
        answerSource: "harness.single_agent_turn.request_task_run",
        content: "我先把目标转成可执行任务，然后持续推进页面实现和验证。",
        id: "message:task-opening",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:turn:session:2",
            run_id: "taskrun:turn:session:2",
            anchor_turn_id: "turn:session:2",
            status: "running",
            public_timeline: [
              {
                item_id: "tool:test",
                kind: "tool_activity",
                title: "正在运行测试",
                detail: "npm test",
                state: "running",
                stream_state: "streaming",
              },
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("我先把目标转成可执行任务");
    expect(html).toContain("运行命令");
    expect(html.indexOf("我先把目标转成可执行任务")).toBeLessThan(html.indexOf("运行命令"));
  });

  it("shows debug-only canonical output state without hiding the assistant message", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "progress_only",
        answerChannel: "task_control",
        answerFallbackReason: "task_executor_scheduled",
        answerLeakFlags: ["internal_protocol_final_text"],
        answerPersistPolicy: "persist_debug_only",
        answerSelectedChannel: "progress_text",
        answerSource: "harness.task_lifecycle",
        content: "我会按这个目标推进：整理文件管理。",
        id: "message:boundary",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).toContain("任务控制消息");
    expect(html).toContain("不写入长期记忆");
    expect(html).toContain("已清理内部协议");
    expect(html).toContain("我会按这个目标推进");
  });
});
