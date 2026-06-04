import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { hasPublicRunActivity, PublicRunActivity } from "./PublicRunActivity";

describe("PublicRunActivity", () => {
  it("renders persisted todo plans as compact public work state", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "todo:plan",
            kind: "todo_plan",
            title: "处理清单",
            detail: "1/3 已完成",
            state: "running",
            active_item_id: "persist",
            todo_items: [
              { todo_id: "inspect", content: "确认现有事件投影链路", status: "completed" },
              { todo_id: "persist", content: "持久化 todo 到会话公开状态", active_form: "正在持久化 todo 状态", status: "in_progress" },
              { todo_id: "summary", content: "优化最终总结", status: "pending" },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("处理清单");
    expect(html).toContain("当前：正在持久化 todo 状态");
    expect(html).toContain("1/3 已完成");
    expect(html).toContain("确认现有事件投影链路");
    expect(html).toContain("优化最终总结");
    expect(html).not.toContain("agent_todo");
    expect(html).not.toContain("plan_id");
  });

  it("renders backend observation reports without exposing tool names as the main copy", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "observation:read",
            kind: "observation_report",
            title: "观察报告",
            detail: "已读到主会话从 public_timeline 渲染运行反馈。",
            implication: "根据真实调用链修改公开投影。",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("观察报告");
    expect(html).toContain("已读到主会话从 public_timeline 渲染运行反馈");
    expect(html).not.toContain("下一步：");
    expect(html).not.toContain("工具已完成");
  });

  it("renders public tool activity as compact assistant-side rows", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:path",
            kind: "tool_activity",
            title: "确认 artifact 路径",
            detail: "目标文件尚未存在，下一步需要创建。",
            state: "done",
            trace_refs: ["rtevt:obs"],
          },
        ],
      }),
    );

    expect(html).toContain("public-run-activity");
    expect(html).toContain("观察结果");
    expect(html).toContain("观察：目标文件尚未存在");
    expect(html).toContain("目标文件尚未存在");
    expect(html).not.toContain("查看执行细节");
    expect(html).not.toContain("查看技术细节");
    expect(html).not.toContain("rtevt:obs");
  });

  it("renders a tool observation report after completed tool activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:agents:done",
            kind: "tool_activity",
            title: "读取完成 langchain-agent/AGENTS.md",
            detail: "项目要求固定端口、先读代码、工具观察要真实反馈。",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("观察结果");
    expect(html).toContain("观察：项目约定已读到");
    expect(html).toContain("项目要求固定端口");
  });

  it("suppresses duplicated assistant final summary", () => {
    const attachments = [
      {
        attachment_id: "runtime-attachment:final",
        run_id: "taskrun:final",
        anchor_turn_id: "turn:session:1",
        status: "completed",
        public_timeline: [
          {
            item_id: "final:1",
            kind: "final_summary",
            text: "已完成五层地下塔的核心结构、关键交互和验收记录。",
            state: "done",
          },
        ],
      },
    ];

    expect(hasPublicRunActivity(attachments[0].public_timeline ?? [], "已完成五层地下塔的核心结构、关键交互和验收记录。")).toBe(false);
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: attachments[0].public_timeline ?? [],
        assistantContent: "已完成五层地下塔的核心结构、关键交互和验收记录。",
      }),
    );
    expect(html).toBe("");
  });

  it("suppresses stale raw tool failures once assistant prose is available", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        assistantContent: "我没有继续调用工具，直接基于已有信息回答。",
        items: [
          {
            item_id: "tool:fetch:failed",
            kind: "tool_activity",
            title: "Tool execution failed: Fetch failed for https://www.hko.gov.hk/en/wxinfo/fcstact/dailywx/20260603.htm: HTTP 404",
            state: "error",
          },
        ],
      }),
    );

    expect(html).toBe("");
  });

  it("keeps process feedback readable when the answer owns the outcome", () => {
    const items = [
      {
        item_id: "todo:plan",
        kind: "todo_plan",
        title: "处理清单",
        detail: "2/2 已完成",
        state: "done",
        completion_ready: true,
        todo_items: [
          { todo_id: "search", content: "检索项目记忆", status: "completed" },
          { todo_id: "answer", content: "整理最终回答", status: "completed" },
        ],
      },
      {
        item_id: "tool:memory",
        kind: "tool_activity",
        title: "工具已完成 memory_search",
        detail: "{\"authority\":\"formal_memory.memory_search_tool\",\"diagnostics\":{\"matched_version_count\":2}}",
        state: "done",
      },
      {
        item_id: "observation:memory",
        kind: "observation_report",
        title: "观察报告",
        detail: "已检索记忆，命中 2 条相关记录。",
        state: "done",
      },
    ];

    expect(hasPublicRunActivity(items, "已根据记忆整理完成。")).toBe(true);
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        assistantContent: "已根据记忆整理完成。",
        items,
      }),
    );

    expect(html).toContain("观察报告");
    expect(html).toContain("已检索记忆，命中 2 条相关记录。");
    expect(html).not.toContain("authority");
    expect(html).not.toContain("diagnostics");
    expect(html).not.toContain("matched_version_count");
  });

  it("does not surface structured tool diagnostics from old activity rows", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:memory",
            kind: "tool_activity",
            title: "工具已完成 memory_search",
            detail: "{\"authority\":\"formal_memory.memory_search_tool\",\"diagnostics\":{\"matched_version_count\":2},\"results\":[]}",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("观察结果");
    expect(html).not.toContain("authority");
    expect(html).not.toContain("diagnostics");
    expect(html).not.toContain("matched_version_count");
    expect(html).not.toContain("memory_search");
  });

  it("does not render completion-only receipts or internal event names", () => {
    const attachments = [
      {
        attachment_id: "runtime-attachment:done",
        run_id: "taskrun:done",
        anchor_turn_id: "turn:session:1",
        status: "completed",
        public_timeline: [
          {
            item_id: "done",
            kind: "assistant_text",
            text: "回答已生成并写回会话",
            state: "done",
          },
          {
            item_id: "terminal",
            kind: "tool_activity",
            title: "agent_turn_terminal",
            detail: "done",
            state: "done",
          },
        ],
      },
    ];

    expect(hasPublicRunActivity(attachments[0].public_timeline ?? [])).toBe(false);
  });

  it("keeps the active action prominent while retaining recent readable observations", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          { item_id: "status:start", kind: "status_update", title: "处理已开始", state: "running" },
          { item_id: "work:1", kind: "work_action", action_kind: "read", title: "已读取上下文", subject_label: "项目结构", public_summary: "已读取上下文 项目结构", observation: "观察：关键上下文已拿到，下一步可以基于文件事实判断。", state: "done" },
          { item_id: "work:2", kind: "work_action", action_kind: "inspect", title: "已确认目标", subject_label: "配置文件", public_summary: "已确认目标 配置文件", observation: "观察：已确认配置文件。", state: "done" },
          { item_id: "work:3", kind: "work_action", action_kind: "search", title: "已搜索引用", subject_label: "入口组件", public_summary: "已搜索引用 入口组件", observation: "观察：相关引用已定位。", state: "done" },
          { item_id: "work:4", kind: "work_action", action_kind: "read", title: "已读取上下文", subject_label: "样式文件", public_summary: "已读取上下文 样式文件", observation: "观察：关键上下文已拿到。", state: "done" },
          { item_id: "work:5", kind: "work_action", action_kind: "verify", title: "正在运行验证", subject_label: "前端测试", public_summary: "正在运行验证 前端测试", state: "running", stream_state: "streaming" },
        ],
      }),
    );

    expect(html).toContain("执行中");
    expect(html).toContain("正在运行验证 前端测试");
    expect(html).not.toContain("较早的 1 条进展已收起");
    expect(html).not.toContain("已完成 3 步");
    expect(html).not.toContain("处理已开始");
    expect(html).not.toContain("读取项目结构");
    expect(html).toContain("已确认目标");
    expect(html).toContain("已搜索引用 入口组件");
    expect(html).toContain("样式文件");
    expect(html).toContain("运行验证");
    expect(html).not.toContain("npm test");
    expect(html).not.toContain("public-run-activity__row--current");
  });

  it("dedupes repeated file reads and keeps them as quiet context for the current search", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "read:1",
            kind: "work_action",
            action_kind: "read",
            title: "已读取上下文",
            subject_label: "artifacts/game.html",
            public_summary: "已读取上下文 artifacts/game.html",
            observation: "观察：关键上下文已拿到，下一步可以基于文件事实判断。",
            state: "done",
          },
          {
            item_id: "read:2",
            kind: "work_action",
            action_kind: "read",
            title: "已读取上下文",
            subject_label: "artifacts/game.html",
            public_summary: "已读取上下文 artifacts/game.html",
            observation: "观察：关键上下文已拿到，下一步可以基于文件事实判断。",
            state: "done",
          },
          {
            item_id: "search:1",
            kind: "work_action",
            action_kind: "search",
            title: "正在搜索引用",
            subject_label: "相关引用",
            public_summary: "正在搜索引用 相关引用",
            state: "running",
            stream_state: "streaming",
          },
        ],
      }),
    );

    expect(html).not.toContain("前面已完成");
    expect(html).toContain("已读取上下文 artifacts/game.html");
    expect(html).toContain("观察：关键上下文已拿到");
    expect(html).toContain("正在搜索");
    expect(html).not.toContain("function attack");
    expect(html.match(/storage/g)?.length ?? 0).toBe(0);
    expect(html).not.toContain("public-run-activity__row--current");
  });

  it("renders path checks as inspection instead of generic tool calls", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:path-exists",
            kind: "tool_activity",
            title: "正在检查 storage/task_environments/general/workspace/artifacts/mythical_sphere.html",
            detail: "已发起工具调用，正在等待工具返回：path_exists。",
            state: "running",
            stream_state: "streaming",
          },
        ],
      }),
    );

    expect(html).toContain("正在确认 artifacts/mythical_sphere.html");
    expect(html).toContain("mythical_sphere.html");
    expect(html).not.toContain("正在调用");
    expect(html).not.toContain("等待工具返回");
  });

  it("renders completed tool observations as a separate report", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:agents:done",
            kind: "tool_activity",
            title: "读取完成 langchain-agent/AGENTS.md",
            detail: "项目要求先说明判断、读取调用链、固定端口验证。",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("观察结果");
    expect(html).toContain("观察：项目约定已读到");
    expect(html).toContain("项目要求先说明判断");
  });

  it("keeps command return observations visible after verification", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:test:done",
            kind: "work_action",
            action_kind: "verify",
            title: "验证已返回",
            subject_label: "前端测试",
            public_summary: "验证已返回 前端测试",
            observation: "观察：验证已返回，22 tests passed",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("观察结果");
    expect(html).toContain("观察：验证已返回，22 tests passed");
    expect(html).not.toContain("npm test");
  });

  it("keeps assistant feedback out of the status lane and renders the active tool action", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "agent:1",
            kind: "assistant_text",
            title: "我先检查文件写入权限和可用路径，然后创建游戏文件。",
            state: "running",
          },
          {
            item_id: "tool:stat",
            kind: "tool_activity",
            title: "检查路径信息",
            detail: "output",
            state: "running",
            stream_state: "streaming",
          },
        ],
      }),
    );

    expect(html).not.toContain("public-run-activity__agent-message");
    expect(html).not.toContain("我先检查文件写入权限和可用路径");
    expect(html).not.toContain("public-run-activity__row--current");
    expect(html).toContain("正在确认 output");
  });

  it("does not duplicate the running prefix for generic tool calls", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:generic-call",
            kind: "tool_activity",
            title: "正在调用 storage/task_environments/general/workspace/artifacts/football.html",
            state: "running",
            stream_state: "streaming",
          },
        ],
      }),
    );

    expect(html).toContain("正在推进当前步骤 artifacts/football.html");
    expect(html).not.toContain("执行动作");
    expect(html).not.toContain("正在正在");
    expect(html).not.toContain("正在调用工具");
    expect(html).not.toContain("storage/task_environments/general/workspace/artifacts/football.html");
  });

  it("renders memory search as meaningful work instead of a blank generic step", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:memory:start",
            kind: "tool_activity",
            title: "已发起工具调用，正在等待工具返回：memory_search。",
            state: "running",
            stream_state: "streaming",
          },
        ],
      }),
    );

    expect(html).toContain("正在检索相关记忆");
    expect(html).not.toContain("正在处理步骤");
    expect(html).not.toContain("memory_search");
    expect(html).not.toContain("等待工具返回");
  });

  it("does not expose a raw shell command from legacy activity rows", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:shell:start",
            kind: "tool_activity",
            title: '正在运行 New-Item -ItemType Directory -Path "frontend/src/app/adventure-island" -Force',
            state: "running",
            stream_state: "streaming",
          },
        ],
      }),
    );

    expect(html).toContain("正在准备输出");
    expect(html).not.toContain("New-Item");
    expect(html).not.toContain("ItemType");
    expect(html).not.toContain("frontend/src/app/adventure-island");
  });

  it("suppresses duplicate tool guard system control text", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "duplicate",
            kind: "tool_activity",
            title: "重复只读工具调用被拦截，已有观察将继续参与上下文。",
            state: "running",
          },
        ],
      }),
    );

    expect(html).toBe("");
  });

  it("shows a background closeout summary when it is not duplicated by assistant prose", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "final:closeout",
            kind: "final_summary",
            text: "已完成实现、测试和收口说明。",
            state: "done",
          },
        ],
        assistantContent: "",
      }),
    );

    expect(html).toContain("已完成实现、测试和收口说明。");
    expect(html).not.toContain("public-run-activity__row--final");
  });

  it("keeps the latest tool observation visible before the closeout summary", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:test:done",
            kind: "work_action",
            action_kind: "verify",
            title: "验证已返回",
            subject_label: "前端测试",
            public_summary: "验证已返回 前端测试",
            observation: "观察：验证已返回，31 tests passed",
            state: "done",
          },
          {
            item_id: "final:closeout",
            kind: "final_summary",
            text: "已完成开局反馈、运行反馈和收尾展示调整。",
            state: "done",
          },
        ],
        assistantContent: "",
      }),
    );

    expect(html).toContain("观察结果");
    expect(html).toContain("观察：验证已返回，31 tests passed");
    expect(html).not.toContain("npm test");
    expect(html).toContain("收尾总结");
    expect(html).toContain("已完成开局反馈、运行反馈和收尾展示调整。");
    expect(html.indexOf("观察结果")).toBeLessThan(html.indexOf("收尾总结"));
    expect(html).not.toContain("阶段完成");
  });

  it("renders artifact refs from attachment using logical paths only", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "artifact:plan",
            kind: "artifact",
            title: "产物已生成",
            path: "storage/task_environments/general/workspace/artifacts/plan.md",
            state: "ready",
          },
        ],
      }),
    );

    expect(html).toContain("产物已生成");
    expect(html).not.toContain("storage/task_environments/general/workspace/artifacts/plan.md");
    expect(html).not.toContain("runtime_state/sandboxes");
  });

  it("treats completed public tool entries as done instead of streaming", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "progress:tool:done",
            kind: "tool_activity",
            title: "工具已完成 storage/task_environments/coding/vibe-workspace/artifacts/test_placeholder",
            detail: "true",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("观察：artifacts/test_placeholder 已返回");
    expect(html).not.toContain("动作已返回");
    expect(html).not.toContain("public-run-activity__row--done");
    expect(html).not.toContain("public-run-activity__spinner");
  });

  it("reconciles a completed tool event over a stale running event for the same target", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:football:start",
            kind: "tool_activity",
            title: "正在调用 storage/task_environments/general/workspace/artifacts/football.html",
            state: "running",
            stream_state: "streaming",
          },
          {
            item_id: "tool:football:done",
            kind: "tool_activity",
            title: "工具已完成 storage/task_environments/general/workspace/artifacts/football.html",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("观察：artifacts/football.html 已返回");
    expect(html).not.toContain("动作已返回");
    expect(html).not.toContain("public-run-activity__row--done");
    expect(html).not.toContain("public-run-activity__row--current");
    expect(html).not.toContain("public-run-activity__spinner");
  });
});
