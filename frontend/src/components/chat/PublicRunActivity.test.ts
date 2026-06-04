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
    expect(html).toContain("下一步：根据真实调用链修改公开投影");
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
    expect(html).toContain("阶段完成");
    expect(html).toContain("已确认目标");
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

    expect(html).toContain("已读取上下文 langchain-agent/AGENTS.md");
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

  it("keeps only the active action prominent while folding older activity into context", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          { item_id: "status:start", kind: "status_update", title: "处理已开始", state: "running" },
          { item_id: "tool:1", kind: "tool_activity", title: "读取项目结构", state: "done" },
          { item_id: "tool:2", kind: "tool_activity", title: "检查配置文件", state: "done" },
          { item_id: "tool:3", kind: "tool_activity", title: "搜索入口组件", state: "done" },
          { item_id: "tool:4", kind: "tool_activity", title: "正在运行测试", detail: "npm test", state: "running", stream_state: "streaming" },
        ],
      }),
    );

    expect(html).toContain("前面已完成 2 步，继续处理中。");
    expect(html).toContain("执行中");
    expect(html).not.toContain("处理已开始");
    expect(html).not.toContain("读取项目结构");
    expect(html).not.toContain("检查配置文件");
    expect(html).toContain("已搜索引用 入口组件");
    expect(html).toContain("观察：相关引用已定位");
    expect(html).toContain("运行验证");
    expect(html).toContain("npm test");
    expect(html).toContain("public-run-activity__row--current");
  });

  it("collapses duplicated file reads and presents search as a single current action", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "read:1",
            kind: "tool_activity",
            title: "正在使用文件读取工具处理",
            detail: "storage/task_environments/development/sandbox/artifacts/game.html",
            state: "done",
          },
          {
            item_id: "read:2",
            kind: "tool_activity",
            title: "正在使用文件读取工具处理",
            detail: "storage/task_environments/development/sandbox/artifacts/game.html",
            state: "done",
          },
          {
            item_id: "search:1",
            kind: "tool_activity",
            title: "正在使用search_text处理 function attack|function damage|function kill|monster.*dead|monster.*remove。",
            state: "running",
            stream_state: "streaming",
          },
        ],
      }),
    );

    expect(html).not.toContain("前面已完成");
    expect(html).toContain("已读取上下文 artifacts/game.html");
    expect(html).toContain("正在搜索");
    expect(html).toContain("function attack");
    expect(html.match(/storage/g)?.length ?? 0).toBe(0);
    expect(html).toContain("public-run-activity__row--current");
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

    expect(html).toContain("已读取上下文 langchain-agent/AGENTS.md");
    expect(html).toContain("观察：项目约定已读到");
    expect(html).toContain("项目要求先说明判断");
  });

  it("keeps command return observations visible after verification", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        items: [
          {
            item_id: "tool:test:done",
            kind: "tool_activity",
            title: "命令已完成 npm test -- --run src/components/chat",
            detail: "22 tests passed",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("验证已返回 npm test -- --run src/components/chat");
    expect(html).toContain("观察：验证命令已返回，22 tests passed");
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
    expect(html).toContain("public-run-activity__row--current");
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

    expect(html).toContain("正在执行动作 artifacts/football.html");
    expect(html).not.toContain("正在正在");
    expect(html).not.toContain("正在调用工具");
    expect(html).not.toContain("storage/task_environments/general/workspace/artifacts/football.html");
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
    expect(html).toContain("public-run-activity__row--final");
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
    expect(html).toContain("storage/task_environments/general/workspace/artifacts/plan.md");
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

    expect(html).toContain("动作已返回 artifacts/test_placeholder");
    expect(html).toContain("public-run-activity__row--done");
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

    expect(html).toContain("动作已返回 artifacts/football.html");
    expect(html).toContain("public-run-activity__row--done");
    expect(html).not.toContain("public-run-activity__row--current");
    expect(html).not.toContain("public-run-activity__spinner");
  });
});
