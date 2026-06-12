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

  it("does not render stage status as assistant prose or public activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "assistant:thinking-stage",
        retrievals: [],
        role: "assistant",
        stageStatus: "正在思考",
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("chat-message-shell__stage-status");
    expect(html).not.toContain("正在思考");
    expect(html).not.toContain("chat-message-shell__content");
    expect(html).not.toContain("public-run-activity");
    expect(html).not.toContain("复制回复");
  });

  it("does not render blocked tool-loop control metadata as assistant prose", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerChannel: "blocked",
        answerSource: "harness.single_agent_turn.tool_loop",
        content: '{"authority":"harness.loop.single_agent_turn.runtime_control_signal","signal_kind":"tool_budget_exhausted","agent_closeout_required":true}',
        id: "message:tool-loop-control",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("harness.loop.single_agent_turn.runtime_control_signal");
    expect(html).not.toContain("tool_budget_exhausted");
    expect(html).not.toContain("agent_closeout_required");
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
                slot: "tool",
                surface: "tool_window",
                source_authority: "tool",
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

  it("keeps task progress visible after an opening judgment starts a task", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "opening_judgment",
        answerPersistPolicy: "persist_canonical",
        answerSource: "harness.single_agent_turn.request_task_run.opening_judgment",
        content: "根据用户要求，将启动一个任务来完成剩余三项审查。",
        id: "history-message:turn:session-a:21:assistant",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:turn:session-a:21:abc",
            anchor_message_id: "history-message:turn:session-a:21:assistant",
            anchor_role: "assistant",
            anchor_turn_id: "turn:session-a:21",
            run_id: "taskrun:turn:session-a:21:abc",
            status: "running",
            task_run_id: "taskrun:turn:session-a:21:abc",
            task_projection: {
              authority: "harness.runtime.single_agent_task_projection.v1",
              projection_id: "projection:taskrun:turn:session-a:21:abc",
              status: "running",
              task_id: "task:turn:session-a:21",
              task_run_id: "taskrun:turn:session-a:21:abc",
              title: "完成剩余审查",
              current_action: {
                activity_id: "activity:read-profile",
                kind: "progress",
                title: "正在读取 profile 配置并追踪切换分支。",
                state: "running",
              },
            },
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("根据用户要求，将启动一个任务");
    expect(html).toContain("正在读取 profile 配置并追踪切换分支");
    expect(html).toContain("public-run-activity");
  });

  it("keeps runtime restart recovery visible beside an opening judgment", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "opening_judgment",
        answerPersistPolicy: "persist_canonical",
        answerSource: "harness.single_agent_turn.request_task_run.opening_judgment",
        content: "根据用户要求，将启动一个任务来完成剩余三项审查。",
        id: "history-message:turn:session-a:21:assistant",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:turnrun:turn:session-a:21",
            anchor_message_id: "history-message:turn:session-a:21:assistant",
            anchor_role: "assistant",
            anchor_turn_id: "turn:session-a:21",
            run_id: "turnrun:turn:session-a:21",
            status: "aborted",
          },
          {
            attachment_id: "runtime-attachment:taskrun:turn:session-a:21:abc",
            anchor_message_id: "history-message:turn:session-a:21:assistant",
            anchor_role: "assistant",
            anchor_turn_id: "turn:session-a:21",
            run_id: "taskrun:turn:session-a:21:abc",
            status: "waiting_executor",
            task_run_id: "taskrun:turn:session-a:21:abc",
            public_timeline: [
              {
                item_id: "runtime-status:restart",
                kind: "status_update",
                slot: "status",
                surface: "timeline",
                source_authority: "runtime",
                title: "等待继续",
                detail: "后端运行时已重启，当前任务可继续。",
                state: "waiting",
              },
            ],
            task_projection: {
              authority: "harness.runtime.single_agent_task_projection.v1",
              projection_id: "projection:taskrun:turn:session-a:21:abc",
              status: "waiting",
              task_id: "task:turn:session-a:21",
              task_run_id: "taskrun:turn:session-a:21:abc",
              title: "完成剩余审查",
              current_action: {
                kind: "lifecycle",
                title: "后端运行时已重启，当前任务可继续。",
                detail: "任务可以继续续跑。",
                state: "waiting",
                display_surface: "timeline",
                visibility_level: "primary",
                source_kind: "runtime_recovery",
              },
            },
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("根据用户要求，将启动一个任务");
    expect(html).toContain("后端运行时已重启，当前任务可继续。");
    expect(html).toContain("public-run-activity");
    expect(html).not.toContain("任务已停止");
  });

  it("renders tool window metadata without keyword or path filtering", () => {
    const privatePath = "backend/mythical-agent/sessions/session-123/environments/coding/vibe-workspace/runtime_state/dynamic_context/replacements/replacement_e21050df8baca858bdde6a4d.json";
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:private-tool-window",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "tool:private",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            action_kind: "read",
            title: "正在读取上下文",
            subject_label: privatePath,
            public_summary: "正在读取上下文",
            observation: privatePath,
            state: "running",
            tool_window: {
              tool_label: "read_file",
              status: "运行中",
              target: privatePath,
              sections: [{ label: "结果", text: privatePath }],
            },
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("正在读取上下文");
    expect(html).toContain("public-run-activity");
    expect(html).toContain("replacement_e21050df8baca858bdde6a4d");
    expect(html).toContain("runtime_state");
    expect(html).toContain("mythical-agent");
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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

  it("keeps task projection tools visible without low-signal recovery status", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:restore-with-task-projection",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:restore",
            anchor_turn_id: "turn:restore",
            run_id: "taskrun:restore",
            task_run_id: "taskrun:restore",
            status: "running",
            task_projection: {
              projection_id: "projection:taskrun:restore",
              authority: "harness.runtime.single_agent_task_projection.v1",
              task_run_id: "taskrun:restore",
              status: "running",
              activities: [
                {
                  activity_id: "activity:empty-tool",
                  kind: "action",
                  display_surface: "tool_window",
                  visibility_level: "primary",
                  title: "正在执行操作",
                  state: "running",
                },
                {
                  activity_id: "activity:inspect-backend",
                  kind: "action",
                  tool_target: "backend",
                  display_surface: "tool_window",
                  visibility_level: "primary",
                  title: "正在确认目标 backend",
                  state: "running",
                },
              ],
            },
          },
        ],
        runtimePublicTimelineDraft: [
          {
            item_id: "stream-restore:strun:restore",
            kind: "status_update",
            slot: "timeline",
            surface: "status_bar",
            source_authority: "system",
            title: "同步运行进度",
            detail: "已拿到上次进度，继续同步后续结果。",
            state: "running",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("正在确认目标 backend");
    expect(html).not.toContain("正在执行操作");
    expect(html).not.toContain("同步运行进度");
    expect(html).toContain("data-entry-count=\"1\"");
  });

  it("shows stage feedback from public timeline when message content is non-public", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerChannel: "stage_feedback",
        answerPersistPolicy: "do_not_persist",
        content: "这段如果只放在 message.content 会被隐藏。",
        id: "message:stage-feedback-timeline",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:stage-feedback",
            anchor_turn_id: "turn:stage-feedback",
            run_id: "taskrun:stage-feedback",
            task_run_id: "taskrun:stage-feedback",
            status: "running",
            task_projection: {
              projection_id: "projection:stage-feedback",
              authority: "harness.runtime.single_agent_task_projection.v1",
              task_run_id: "taskrun:stage-feedback",
              status: "running",
              activities: [
                {
                  activity_id: "activity:run-tool",
                  kind: "action",
                  tool_target: "frontend tests",
                  display_surface: "tool_window",
                  visibility_level: "primary",
                  title: "正在运行验证",
                  state: "running",
                },
              ],
            },
          },
        ],
        runtimePublicTimelineDraft: [
          {
            item_id: "stage-feedback:after-tool",
            kind: "stage_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            title: "阶段反馈",
            text: "工具结果已返回，我会根据证据继续收口。",
            state: "running",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("工具结果已返回，我会根据证据继续收口。");
    expect(html).toContain("正在运行验证");
    expect(html).not.toContain("这段如果只放在 message.content 会被隐藏。");
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            title: "我先检查当前目录和关键文件，再决定下一步修改范围。",
            text: "我先检查当前目录和关键文件，再决定下一步修改范围。",
            state: "running",
          },
          {
            item_id: "progress:tool",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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
            slot: "status",
            surface: "status_bar",
            source_authority: "system",
            title: "正在思考",
            state: "running",
          },
          {
            item_id: "tool:read",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            action_kind: "inspect",
            title: "读取文件内容",
            subject_label: "backend/api/chat.py",
            public_summary: "读取文件内容 backend/api/chat.py",
            state: "done",
          },
          {
            item_id: "verify:evidence",
            kind: "verification",
            slot: "status",
            surface: "status_bar",
            source_authority: "system",
            title: "补齐验收证据",
            state: "running",
          },
          {
            item_id: "observation:status",
            kind: "observation_report",
            slot: "status",
            surface: "status_bar",
            source_authority: "model",
            title: "观察反馈",
            detail: "已确认任务间观察反馈仍需要显示。",
            state: "done",
          },
          {
            item_id: "tool:verify",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            action_kind: "run",
            title: "正在运行验证 前端测试",
            subject_label: "前端测试",
            public_summary: "正在运行验证 前端测试",
            state: "running",
          },
          {
            item_id: "ask:user",
            kind: "status_update",
            slot: "control",
            surface: "control",
            source_authority: "system",
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
    expect(html).toContain("读取文件内容 backend/api/chat.py");
    expect(html).not.toContain("补齐验收证据");
    expect(html).toContain("backend/api/chat.py");
    expect(html).toContain("正在运行验证 前端测试");
    expect(html).toContain("data-entry-count=\"3\"");
    expect(html).not.toContain("请选择要优先验证的页面。");
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
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "我先确认任务投影链路，再继续修复。",
            state: "running",
          },
          {
            item_id: "tool:write",
            kind: "tool_activity",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
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
    expect(html).toContain("chat-message-shell__content");
    expect(html).not.toContain("public-run-activity");
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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

  it("lets a stable assistant answer suppress completed process feedback", () => {
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            title: "正在调用 storage/task_environments/general/workspace/artifacts/football.html",
            state: "running",
            stream_state: "streaming",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("写好了");
    expect(html).not.toContain("public-run-activity");
    expect(html).not.toContain("artifacts/football.html 已返回");
    expect(html).not.toContain("观察结果");
    expect(html).not.toContain("观察：");
    expect(html).not.toContain("动作已返回");
    expect(html).not.toContain("public-run-activity__row--done");
    expect(html).not.toContain("public-run-activity__row--current");
    expect(html).not.toContain("public-run-activity__spinner");
  });

  it("lets stable assistant prose suppress completed task projection activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerPersistPolicy: "persist_canonical",
        content: "修好了。",
        id: "message:stable-with-task-projection",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:projection-final",
            anchor_turn_id: "turn:projection-final",
            run_id: "taskrun:projection-final",
            task_run_id: "taskrun:projection-final",
            status: "completed",
            public_timeline: [],
            task_projection: {
              projection_id: "projection:taskrun:projection-final",
              authority: "harness.runtime.single_agent_task_projection.v1",
              task_run_id: "taskrun:projection-final",
              status: "completed",
              activities: [
                {
                  activity_id: "activity:write-report",
                  kind: "action",
                  source_kind: "write_file",
                  tool_name: "write_file",
                  tool_target: "docs/report.md",
                  display_surface: "tool_window",
                  visibility_level: "primary",
                  title: "写入报告",
                  detail: "docs/report.md 已更新。",
                  state: "completed",
                },
              ],
            },
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html.match(/修好了。/g)?.length ?? 0).toBe(1);
    expect(html).toContain("复制回复");
    expect(html).not.toContain("写入报告");
    expect(html).not.toContain("public-run-activity__tool-window");
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            action_kind: "read",
            title: "已读取上下文",
            subject_label: "adventure-island/renderer.ts",
            observation: "观察：关键上下文已拿到，下一步可以基于文件事实判断。",
            state: "done",
          },
          {
            item_id: "final:summary",
            kind: "final_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
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
                slot: "body",
                surface: "assistant_body",
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

  it("renders canonical closeout prose that mentions control terms instead of completed tool cards", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerPersistPolicy: "persist_canonical",
        content: "收口结论：active_work_control、ask_user 和 continue_active_work 是控制周期的一部分，需要按信号边界解释。",
        id: "message:control-closeout",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:turnrun:control-closeout",
            run_id: "turnrun:control-closeout",
            anchor_turn_id: "turn:session-control:3",
            status: "completed",
            public_timeline: [
              {
                item_id: "tool:read",
                kind: "work_action",
                slot: "tool",
                surface: "tool_window",
                source_authority: "tool",
                action_kind: "read",
                title: "读取完成 backend/harness/loop/single_agent_turn.py",
                subject_label: "backend/harness/loop/single_agent_turn.py",
                state: "done",
              },
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("active_work_control");
    expect(html).toContain("continue_active_work");
    expect(html).not.toContain("public-run-activity");
    expect(html).not.toContain("读取完成 backend/harness/loop/single_agent_turn.py");
  });

  it("keeps canonical prose when it discusses protocol keywords from search results", () => {
    const content = "审查结论：搜索结果里出现 answer_source、terminal_reason、task_control 和 Get-Content，只是被分析的正文关键词，不是运行时协议泄露。";
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerPersistPolicy: "persist_canonical",
        content,
        id: "message:protocol-keyword-prose",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).toContain("answer_source");
    expect(html).toContain("terminal_reason");
    expect(html).toContain("task_control");
    expect(html).toContain("Get-Content");
    expect(html).toContain("不是运行时协议泄露");
  });

  it("keeps completed closeout tool activity folded when answer metadata is missing", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "收口总结：已经完成检查，结论以这段正文为准。",
        id: "message:completed-runtime-closeout",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:turnrun:completed-closeout",
            run_id: "turnrun:completed-closeout",
            anchor_turn_id: "turn:session-completed:7",
            status: "completed",
            public_timeline: [
              {
                item_id: "tool:read-completed",
                kind: "work_action",
                slot: "tool",
                surface: "tool_window",
                source_authority: "tool",
                action_kind: "read",
                title: "读取完成 backend/harness/runtime/compiler.py",
                subject_label: "backend/harness/runtime/compiler.py",
                state: "done",
              },
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("收口总结");
    expect(html).toContain("public-run-activity");
    expect(html).toContain("读取完成 backend/harness/runtime/compiler.py");
    expect(html).not.toContain("open=\"\"");
  });

  it("keeps executor handoff activity visible because it is not a closeout turn", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerChannel: "task_control",
        answerCanonicalState: "progress_only",
        answerPersistPolicy: "persist_debug_only",
        content: "",
        id: "message:executor-handoff",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:taskrun:handoff",
            run_id: "taskrun:handoff",
            anchor_turn_id: "turn:session-handoff:9",
            task_run_id: "taskrun:handoff",
            status: "completed",
            terminal_reason: "task_executor_scheduled",
            public_timeline: [
              {
                item_id: "tool:handoff",
                kind: "work_action",
                slot: "tool",
                surface: "tool_window",
                source_authority: "runtime",
                action_kind: "run",
                title: "任务执行器已接管",
                subject_label: "继续处理当前任务",
                state: "running",
              },
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("public-run-activity");
    expect(html).toContain("继续处理当前任务");
  });

  it("renders agent-authored closeout prose instead of leaving terminal tool cards as the message", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerPersistPolicy: "persist_canonical",
        answerSource: "harness.single_agent_turn.agent_closeout",
        content: "我已经达到本轮工具边界。下一步应缩小搜索范围，或把这次检查升级为项目级任务继续。",
        id: "message:blocked-closeout",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:turnrun:blocked-closeout",
            run_id: "turnrun:blocked-closeout",
            anchor_turn_id: "turn:session-blocked:5",
            status: "blocked",
            public_timeline: [
              {
                item_id: "tool:search",
                kind: "work_action",
                slot: "tool",
                surface: "tool_window",
                source_authority: "tool",
                action_kind: "search",
                title: "搜索完成 backend/harness/loop/single_agent_turn.py",
                subject_label: "backend/harness/loop/single_agent_turn.py",
                state: "done",
              },
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("升级为项目级任务");
    expect(html).not.toContain("public-run-activity");
    expect(html).not.toContain("搜索完成 backend/harness/loop/single_agent_turn.py");
  });

  it("does not synthesize failed prose or show tool windows when terminal closeout has no body", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:terminal-no-closeout",
        retrievals: [],
        role: "assistant",
        runtimeAttachments: [
          {
            attachment_id: "runtime-attachment:turnrun:no-closeout",
            run_id: "turnrun:no-closeout",
            anchor_turn_id: "turn:session-blocked:5",
            status: "blocked",
            terminal_reason: "single_agent_turn_protocol_error:agent_closeout_not_returned",
            public_timeline: [
              {
                item_id: "control:error",
                kind: "error_notice",
                slot: "control",
                surface: "control",
                source_authority: "system",
                title: "运行中断",
                detail: "agent 没有回传收口正文。",
                state: "error",
              },
              {
                item_id: "tool:search",
                kind: "work_action",
                slot: "tool",
                surface: "tool_window",
                source_authority: "tool",
                action_kind: "search",
                title: "搜索失败 def admission",
                subject_label: "backend/harness/loop",
                state: "error",
              },
              {
                item_id: "tool:read",
                kind: "work_action",
                slot: "tool",
                surface: "tool_window",
                source_authority: "tool",
                action_kind: "read",
                title: "读取完成 backend/harness/runtime/compiler.py",
                subject_label: "backend/harness/runtime/compiler.py",
                state: "done",
              },
            ],
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("运行中断");
    expect(html).toContain("agent 没有回传收口正文");
    expect(html).toContain("public-run-activity");
    expect(html).not.toContain("搜索失败 def admission");
    expect(html).not.toContain("读取完成 backend/harness/runtime/compiler.py");
    expect(html).not.toContain("public-run-activity__tool-window");
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
                slot: "tool",
                surface: "tool_window",
                source_authority: "tool",
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

  it("does not render ask-user control detail as assistant prose", () => {
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
            slot: "control",
            surface: "control",
            source_authority: "system",
            phase: "waiting_user",
            title: "等待补充信息",
            detail: "审查项目没问题。不过在开始之前，我需要确认一下你的期望： 1. **审查范围**——你希望我全面审查整个项目，还是聚焦某个具体方面？ 2. **审查深度**——是要做快速健康评估，还是深入到具体模块逐文件审查？",
            state: "waiting",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("审查项目没问题。不过在开始之前");
    expect(html).not.toContain("<ol>");
    expect(html).not.toContain("<strong>审查范围</strong>");
    expect(html).not.toContain("等待补充信息");
    expect(html).not.toContain("public-run-activity");
    expect(html).not.toContain("复制回复");
  });

  it("renders model body timeline markdown as assistant prose", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        content: "",
        id: "message:timeline-markdown-body",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "body:final-markdown",
            kind: "final_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "第一段说明。\n\n第二段说明。\n\n- 第三段要点",
            state: "done",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("<p>第一段说明。</p>");
    expect(html).toContain("<p>第二段说明。</p>");
    expect(html).toContain("<li>第三段要点</li>");
    expect(html).toContain("复制回复");
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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

  it("hides generic completed tool activity once final answer exists", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        content: "这是最终总结。",
        id: "message:final-over-tools",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "call:read",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            action_kind: "read",
            title: "工具已完成",
            public_summary: "工具已完成",
            state: "done",
            stream_state: "done",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("这是最终总结");
    expect(html).not.toContain("工具已完成");
    expect(html).not.toContain("public-run-activity");
  });

  it("lets stable final prose suppress terminal tool activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        content: "final-result",
        id: "message:final-over-failed-tool",
        retrievals: [],
        role: "assistant",
        runtimePublicTimelineDraft: [
          {
            item_id: "tool:fetch-failed",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            action_kind: "browse",
            title: "tool-failed",
            subject_label: "https://example.test/final",
            public_summary: "tool-failed",
            recovery_hint: "fetch failed",
            state: "error",
            stream_state: "done",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("final-result");
    expect(html).not.toContain("public-run-activity");
    expect(html).not.toContain("data-activity-kind=\"tool\"");
  });

  it("keeps raw file listing output in activity instead of assistant prose while the turn is not terminal", () => {
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            action_kind: "inspect",
            title: "已确认目标",
            observation: "file frontend/src/app/adventure-island/assets.ts 2938 bytes file frontend/src/app/adventure-island/config.ts 5177 bytes file frontend/src/app/adventure-island/game-data.ts 23749 bytes",
            state: "done",
          },
        ],
        toolCalls: [],
      }),
    );

    expect(html).toContain("public-run-activity__tool-window");
    expect(html).toContain("已确认目标");
    expect(html).toContain("2938 bytes");
    expect(html).toContain("assets.ts");
    expect(html).toContain("file frontend");
    expect(html).not.toContain("<p>file frontend");
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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
    expect(html).toContain("Copied: game-boss-demon-king.png");
    expect(html).not.toContain("<p>Copied:");
    expect(html).toContain("结果");
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
                slot: "body",
                surface: "assistant_body",
                source_authority: "model",
                title: "观察报告",
                detail: "验证已返回，22 tests passed",
                implication: "下一步会根据测试结果收口。",
                state: "done",
              },
              {
                item_id: "live:stale-verify",
                kind: "work_action",
                slot: "tool",
                surface: "tool_window",
                source_authority: "tool",
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

  it("renders copied shell text when it is stored as assistant content", () => {
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

    expect(html).toContain("Copied: game-boss-demon-king.png");
    expect(html).toContain("Copied: game-map-castle.png");
    expect(html).toContain("复制回复");
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

  it("renders stored read-only shell validator text as assistant content", () => {
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

    expect(html).not.toContain("public-run-activity");
    expect(html).toContain("allowlisted");
    expect(html).toContain("read-only");
    expect(html).toContain("复制回复");
  });

  it("renders stored persisted tool result text as assistant content", () => {
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

    expect(html).not.toContain("public-run-activity");
    expect(html).toContain("Read persisted tool result failed");
    expect(html).toContain("runtime_state");
    expect(html).toContain("tool-results");
    expect(html).toContain("复制回复");
  });

  it("hides stored internal model action protocol content", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, {
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerPersistPolicy: "persist_canonical",
        content: '{"authority":"harness.loop.model_action_request","action_type":"active_work_control","active_work_control":{"action":"continue_active_work"}}',
        id: "message:raw-model-action",
        retrievals: [],
        role: "assistant",
        toolCalls: [],
      }),
    );

    expect(html).not.toContain("harness.loop.model_action_request");
    expect(html).not.toContain("active_work_control");
    expect(html).not.toContain("continue_active_work");
    expect(html).not.toContain("复制回复");
  });

});
