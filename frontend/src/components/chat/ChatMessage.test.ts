import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatMessage } from "./ChatMessage";

describe("ChatMessage", () => {
  it("only renders the edit affordance when the caller says this user message is editable", () => {
    const locked = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        canEdit: false,
        content: "旧问题",
        id: "user:locked",
        retrievals: [],
        role: "user",
        toolCalls: [],
      }),
    );
    const editable = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        canEdit: true,
        content: "最后一条问题",
        id: "user:editable",
        retrievals: [],
        role: "user",
        toolCalls: [],
      }),
    );

    expect(locked).not.toContain("编辑消息");
    expect(editable).toContain("编辑消息");
  });

  it("renders a copy affordance for assistant prose only", () => {
    const assistant = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "这是一段可复制的回复。",
        id: "assistant:copy",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );
    const user = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "用户消息不需要复制按钮。",
        id: "user:no-copy",
        retrievals: [],
        role: "user",
        toolCalls: [],
      }),
    );

    expect(assistant).toContain("复制回复");
    expect(user).not.toContain("复制回复");
  });

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

  it("hides routine output boundary cleanup state without hiding the assistant message", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "progress_only",
        answerChannel: "task_control",
        answerFallbackReason: "task_executor_scheduled",
        answerLeakFlags: ["inline_pseudo_tool_call_final_text"],
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

    expect(html).toContain("我会按这个目标推进");
    expect(html).not.toContain("任务控制消息");
    expect(html).not.toContain("不写入长期记忆");
    expect(html).not.toContain("已清理内部协议");
    expect(html).not.toContain("输出状态");
  });

  it("hides stable answer boundary metadata even when protocol cleanup flags are present", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerLeakFlags: ["internal_protocol_final_text"],
        answerPersistPolicy: "persist_canonical",
        answerSelectedChannel: "answer_candidate",
        content: "稳定回复正文。",
        id: "message:stable-boundary",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).toContain("稳定回复正文");
    expect(html).not.toContain("稳定答案");
    expect(html).not.toContain("可写入记忆");
    expect(html).not.toContain("answer_candidate");
    expect(html).not.toContain("已清理内部协议");
  });

  it("projects live public timeline into the chat message before runtime attachments arrive", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:runtime-progress",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "progress:model",
            kind: "assistant_text",
            title: "我先检查当前目录和关键文件，再决定下一步修改范围。",
            text: "我先检查当前目录和关键文件，再决定下一步修改范围。",
            state: "running",
          },
          {
            item_id: "progress:tool",
            kind: "tool_activity",
            title: "正在运行 npm test -- --run src/components/chat",
            detail: "npm test -- --run src/components/chat",
            state: "running",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("我先检查当前目录和关键文件");
    expect(html).toContain("当前判断");
    expect(html.match(/我先检查当前目录和关键文件/g)?.length ?? 0).toBe(1);
    expect(html).toContain("运行命令");
    expect(html).toContain("npm test -- --run src/components/chat");
    expect(html.indexOf("我先检查当前目录和关键文件")).toBeLessThan(html.indexOf("运行命令"));
  });

  it("does not keep stale live tool activity spinning after a stable assistant answer", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerPersistPolicy: "persist_canonical",
        content: "写好了。\n\nD:\\AI应用\\langchain-agent\\storage\\task_environments\\general\\workspace\\artifacts\\football.html",
        id: "message:stable-with-draft",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "tool:football:start",
            kind: "tool_activity",
            title: "正在调用 storage/task_environments/general/workspace/artifacts/football.html",
            state: "running",
            stream_state: "streaming",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("写好了");
    expect(html).toContain("工具已完成 artifacts/football.html");
    expect(html).toContain("public-run-activity__row--done");
    expect(html).not.toContain("public-run-activity__row--current");
    expect(html).not.toContain("public-run-activity__spinner");
  });
});
