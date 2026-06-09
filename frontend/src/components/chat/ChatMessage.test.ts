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

  it("does not render blocked tool-loop guard metadata as assistant prose", () => {
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
    expect(html).not.toContain("基于已有事实收口说明");
    expect(html).not.toContain("public-run-activity");
  });

  it("renders public timeline activity for task-control messages without backend projection", () => {
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

    expect(html).not.toContain("我先把目标转成可执行任务");
    expect(html).toContain("正在运行测试");
    expect(html).toContain("public-run-activity");
  });

  it("keeps live streamed prose visible beside runtime activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "我正在继续生成",
        id: "message:streaming-with-activity",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "work:read",
            kind: "work_action",
            action_kind: "read",
            title: "正在读取上下文",
            public_summary: "正在读取上下文",
            state: "running",
            stream_state: "streaming",
          },
        ],
        streamingContent: true,
        toolCalls: [],
      }),
    );

    expect(html).toContain("我正在继续生成");
    expect(html).toContain("正在读取上下文");
    expect(html).toContain("复制回复");
  });

  it("keeps non-final streamed prose visible even if the live flag drops", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "继续生成中",
        id: "message:streaming-flag-dropped",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "work:context",
            kind: "work_action",
            action_kind: "read",
            title: "正在整理上下文",
            public_summary: "正在整理上下文",
            state: "running",
            stream_state: "streaming",
          },
        ],
        streamingContent: false,
        toolCalls: [],
      }),
    );

    expect(html).toContain("继续生成中");
    expect(html).toContain("正在整理上下文");
    expect(html).toContain("复制回复");
  });

  it("hides routine output boundary cleanup state", () => {
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

    expect(html).not.toContain("我会按这个目标推进");
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
            kind: "work_action",
            action_kind: "verify",
            title: "正在运行验证",
            subject_label: "前端测试",
            public_summary: "正在运行验证 前端测试",
            state: "running",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("我先检查当前目录和关键文件");
    expect(html).not.toContain("当前判断");
    expect(html.match(/我先检查当前目录和关键文件/g)?.length ?? 0).toBe(1);
    expect(html).toContain("正在运行验证 前端测试");
    expect(html).toContain("前端测试");
    expect(html).not.toContain("npm test -- --run src/components/chat");
    expect(html.indexOf("我先检查当前目录和关键文件")).toBeLessThan(html.indexOf("正在运行验证 前端测试"));
  });

  it("keeps task runtime status and tool activity out of the chat body when a task projection exists", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:task-projection-runtime-draft",
        retrievals: [],
        role: "assistant",
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
                items: [
                  { todo_id: "todo:1", content: "审查运行状态", active_form: "正在审查运行状态", status: "in_progress" },
                  { todo_id: "todo:2", content: "输出修复结果", status: "pending" },
                ],
              },
            },
          },
        ],
        runtimePublicTimelineDraft: [
          {
            item_id: "stage:thinking",
            kind: "status_update",
            title: "正在思考",
            state: "running",
          },
          {
            item_id: "tool:read",
            kind: "work_action",
            action_kind: "inspect",
            title: "读取文件内容",
            subject_label: "backend/api/chat.py",
            public_summary: "读取文件内容 backend/api/chat.py",
            state: "done",
          },
          {
            item_id: "verify:evidence",
            kind: "verification",
            title: "补齐验收证据",
            state: "running",
          },
          {
            item_id: "ask:user",
            kind: "status_update",
            phase: "waiting_user",
            title: "等待补充信息",
            detail: "请选择要优先验证的页面。",
            state: "waiting",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("处理清单");
    expect(html).not.toContain("当前：正在审查运行状态");
    expect(html).not.toContain("输出修复结果");
    expect(html).not.toContain("正在思考");
    expect(html).not.toContain("读取文件内容");
    expect(html).not.toContain("补齐验收证据");
    expect(html).not.toContain("backend/api/chat.py");
    expect(html).toContain("请选择要优先验证的页面。");
  });

  it("keeps companion timeline visible when task projection entries are all diagnostics", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:task-projection-companion",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:diagnostics-only",
            anchor_turn_id: "turn:projection",
            run_id: "taskrun:diagnostics-only",
            task_run_id: "taskrun:diagnostics-only",
            status: "running",
            task_projection: {
              projection_id: "projection:diagnostics-only",
              authority: "runtime_projection",
              task_run_id: "taskrun:diagnostics-only",
              status: "running",
              current_action: {
                title: "正在思考",
                display_surface: "timeline",
                visibility_level: "internal",
                state: "running",
              },
              activities: [
                {
                  activity_id: "activity:search",
                  kind: "status",
                  source_kind: "search_text",
                  title: "搜索证据",
                  detail: "工具调用失败，正在根据失败原因调整处理路径。",
                  display_surface: "diagnostics",
                  visibility_level: "debug",
                  state: "failed",
                },
              ],
            },
          },
        ],
        runtimePublicTimelineDraft: [
          {
            item_id: "body:opening",
            kind: "opening_judgment",
            surface: "body",
            source_authority: "model",
            text: "我先确认任务投影链路，再继续修复。",
            state: "running",
          },
          {
            item_id: "tool:write",
            kind: "tool_activity",
            surface: "tool_window",
            title: "写入修复文档",
            detail: "docs/report.md",
            state: "done",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("我先确认任务投影链路");
    expect(html).toContain("写入修复文档");
    expect(html).toContain("public-run-activity");
    expect(html).not.toContain("搜索证据");
    expect(html).not.toContain("工具调用失败");
  });

  it("renders an explicit opening judgment even before activity rows exist", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:opening-only",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "opening:1",
            kind: "opening_judgment",
            title: "开局判断",
            text: "我先确认现有输出链路，再改公开反馈状态。",
            state: "running",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("我先确认现有输出链路");
    expect(html.match(/我先确认现有输出链路/g)?.length ?? 0).toBe(1);
    expect(html).not.toContain("开局反馈");
    expect(html).not.toContain("assistant-output-signal");
    expect(html).toContain("public-run-activity");
    expect(html).not.toContain("正在思考");
  });

  it("does not synthesize message-level opening when a run starts with tool activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:tool-only-opening",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "tool:agents",
            kind: "tool_activity",
            title: "正在读取文件 langchain-agent/AGENTS.md",
            state: "running",
            stream_state: "streaming",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("正在读取文件 langchain-agent/AGENTS.md");
    expect(html.match(/正在读取文件 langchain-agent\/AGENTS\.md/g)?.length ?? 0).toBe(1);
    expect(html).not.toContain("我先确认项目约定和协作边界");
    expect(html).not.toContain("开局反馈");
    expect(html).not.toContain("assistant-output-signal");
    expect(html).toContain("public-run-activity");
    expect(html).not.toContain("复制回复");
    expect(html).not.toContain("正在思考");
  });

  it("keeps completed process feedback readable beside a stable assistant answer", () => {
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
    expect(html).toContain("public-run-activity");
    expect(html).not.toContain("artifacts/football.html 已返回");
    expect(html).not.toContain("观察结果");
    expect(html).not.toContain("观察：");
    expect(html).not.toContain("动作已返回");
    expect(html).not.toContain("public-run-activity__row--done");
    expect(html).not.toContain("public-run-activity__row--current");
    expect(html).not.toContain("public-run-activity__spinner");
  });

  it("renders final summary as assistant prose instead of leaving only activity feedback", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        content: "",
        id: "message:final-summary-only",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "work:read",
            kind: "work_action",
            action_kind: "read",
            title: "已读取上下文",
            subject_label: "adventure-island/renderer.ts",
            observation: "观察：关键上下文已拿到，下一步可以基于文件事实判断。",
            state: "done",
          },
          {
            item_id: "final:summary",
            kind: "final_summary",
            text: "已经确认问题来自 renderer.ts 的类型导入，页面编译已恢复。",
            state: "done",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("已经确认问题来自 renderer.ts 的类型导入");
    expect(html.match(/已经确认问题来自 renderer\.ts 的类型导入/g)?.length ?? 0).toBe(1);
    expect(html).not.toContain("收尾总结");
  });

  it("deduplicates persisted runtime final summaries against canonical assistant prose", () => {
    const content = [
      "我可以帮你完成以下工作：",
      "",
      "- 代码与开发：阅读、搜索、分析项目代码，编写和修改文件。",
      "- 前端相关：打开页面、点击、输入、截图验证。",
      "- 信息获取：搜索网络和官方文档。",
      "",
      "你现在有什么需要我帮忙的吗？",
    ].join("\n");
    const persistedSummary = content.replace("你现在有什么需要我帮忙的吗？", "").trim();
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerPersistPolicy: "persist_canonical",
        content,
        id: "message:dedupe-final-summary",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:turnrun:dedupe",
            run_id: "turnrun:dedupe",
            anchor_turn_id: "turn:session-dedupe:1",
            status: "completed",
            public_timeline: [
              {
                item_id: "final:persisted",
                kind: "final_summary",
                surface: "body",
                source_authority: "model",
                text: persistedSummary,
                state: "done",
              },
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html.match(/我可以帮你完成以下工作/g)?.length ?? 0).toBe(1);
    expect(html).toContain("你现在有什么需要我帮忙的吗");
  });

  it("renders runtime attachment activity even before assistant prose is persisted", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:runtime-placeholder",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:turnrun:turn:session-a:3",
            run_id: "turnrun:turn:session-a:3",
            anchor_turn_id: "turn:session-a:3",
            status: "running",
            public_timeline: [
              {
                item_id: "work:read",
                kind: "work_action",
                action_kind: "read",
                title: "正在读取文件",
                subject_label: "adventure-island-standalone/index.html",
                public_summary: "正在读取 adventure-island-standalone/index.html",
                state: "running",
                stream_state: "streaming",
              },
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("public-run-activity");
    expect(html).toContain("正在读取 adventure-island-standalone/index.html");
    expect(html).not.toContain("正在思考");
  });

  it("renders ask-user questions as assistant prose without the waiting status title", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:ask-user",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "control:ask-user",
            kind: "status_update",
            surface: "status",
            phase: "waiting_user",
            title: "等待补充信息",
            detail: "审查项目没问题。不过在开始之前，我需要确认一下你的期望： 1. **审查范围**——你希望我全面审查整个项目，还是聚焦某个具体方面？ 2. **审查深度**——是要做快速健康评估，还是深入到具体模块逐文件审查？",
            state: "waiting",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("审查项目没问题。不过在开始之前");
    expect(html).toContain("<ol>");
    expect(html).toContain("<strong>审查范围</strong>");
    expect(html).not.toContain("等待补充信息");
    expect(html).not.toContain("public-run-activity");
  });

  it("keeps completed process feedback in activity when no final answer exists", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        content: "",
        id: "message:done-with-only-tool-feedback",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "work:read",
            kind: "work_action",
            action_kind: "read",
            title: "已读取上下文",
            subject_label: "adventure-island/renderer.ts",
            observation: "观察：关键上下文已拿到，下一步可以基于文件事实判断。",
            state: "done",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("关键上下文已拿到，下一步可以基于文件事实判断");
    expect(html).not.toContain("还没有形成完整回答");
    expect(html).toContain("public-run-activity");
    expect(html).not.toContain("复制回复");
  });

  it("hides raw file listing output instead of rendering assistant prose or noisy activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        content: "",
        id: "message:raw-file-listing",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "work:list",
            kind: "work_action",
            action_kind: "inspect",
            title: "已确认目标",
            observation: "file frontend/src/app/adventure-island/assets.ts 2938 bytes file frontend/src/app/adventure-island/config.ts 5177 bytes file frontend/src/app/adventure-island/game-data.ts 23749 bytes",
            state: "done",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("public-run-activity");
    expect(html).not.toContain("已确认目标");
    expect(html).not.toContain("2938 bytes");
    expect(html).not.toContain("assets.ts");
    expect(html).not.toContain("file frontend");
  });

  it("renders copied shell output as a folded activity panel instead of assistant prose", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        content: "",
        id: "message:copied-shell-output",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "work:copy-assets",
            kind: "work_action",
            action_kind: "run",
            title: "复制素材",
            observation: "Copied: game-boss-demon-king.png Copied: game-map-castle.png",
            state: "done",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("已复制 2 个素材文件");
    expect(html).toContain("public-run-activity__tool-window");
    expect(html).toContain("复制素材");
    expect(html).not.toContain("Copied: game-boss-demon-king.png");
    expect(html).not.toContain("<p>Copied:");
    expect(html).not.toContain("观察结果");
    expect(html).not.toContain("观察：");
  });

  it("renders persisted observation feedback instead of a stale monitor action placeholder", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "好，我接着处理。",
        id: "message:stale-monitor-action",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:verify",
            run_id: "taskrun:verify",
            anchor_turn_id: "turn:session:2",
            status: "running",
            public_timeline: [
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
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("好，我接着处理。");
    expect(html).toContain("验证已返回，22 tests passed");
    expect(html).not.toContain("下一步会根据测试结果收口");
    expect(html).not.toContain("我正在验证验证结果");
    expect(html).not.toContain("观察报告");
  });

  it("does not render copied shell output when it is stored as assistant content", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        content: "Copied: game-boss-demon-king.png Copied: game-map-castle.png",
        id: "message:copied-shell-content",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("Copied: game-boss-demon-king.png");
    expect(html).not.toContain("Copied: game-map-castle.png");
    expect(html).not.toContain("正在思考");
  });

  it("keeps stable review prose visible when it contains a markdown table", () => {
    const content = [
      "我已经读取了约一半的代码，已经发现了几个 bug。",
      "",
      "| 代码引用 | 预期文件 | 实际状态 |",
      "|---|---|---|",
      "| `game-npc-village-elder.png` | `game-npc-elder.png` | 文件名不匹配 |",
      "",
      "代码还有很多没读到，我需要继续完成剩余代码审查、实施修复并实测验证。",
    ].join("\n");
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerLeakFlags: ["internal_protocol_final_text", "inline_pseudo_tool_call_final_text"],
        content,
        id: "message:review-table",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).toContain("我已经读取了约一半的代码");
    expect(html).toContain("代码引用");
    expect(html).toContain("game-npc-village-elder.png");
    expect(html).toContain("复制回复");
  });

  it("drops stored read-only shell validator failures without synthesizing activity feedback", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        content: "shell command executable is not allowlisted read-only",
        id: "message:read-only-shell-failure",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("命令被只读权限拦截");
    expect(html).not.toContain("public-run-activity");
    expect(html).not.toContain("allowlisted");
    expect(html).not.toContain("read-only");
    expect(html).not.toContain("正在思考");
    expect(html).not.toContain("复制回复");
  });

  it("drops stored persisted tool result failures without synthesizing activity feedback", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        content: "Read persisted tool result failed: D:\\AI应用\\langchain-agent\\backend\\storage\\task_environments\\general\\workspace\\runtime_state\\storage\\runtime_context\\tool-results\\session-fad8ee446.txt",
        id: "message:persisted-tool-result-failure",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("上一段执行结果没有成功读回");
    expect(html).not.toContain("public-run-activity");
    expect(html).not.toContain("Read persisted tool result failed");
    expect(html).not.toContain("runtime_state");
    expect(html).not.toContain("tool-results");
    expect(html).not.toContain("复制回复");
  });

});
