import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PublicTimelineActivity } from "./PublicTimelineActivity";

describe("PublicTimelineActivity", () => {
  it("renders task projection current action and activities without exposing todo", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        taskProjections: [
          {
            projection_id: "projection:taskrun:test",
            authority: "harness.runtime.single_agent_task_projection.v1",
            task_run_id: "taskrun:test",
            status: "running",
            current_action: {
              title: "正在重构投影系统",
              state: "running",
            },
            todo: {
              active_item_id: "wire",
              items: [
                { todo_id: "read", content: "读取现有链路", status: "completed" },
                { todo_id: "wire", content: "接入投影附件", active_form: "正在接入投影附件", status: "in_progress" },
                { todo_id: "verify", content: "运行聚焦验证", status: "pending" },
              ],
            },
            activities: [
              { activity_id: "activity:read", kind: "observation", title: "已确认旧反推链路", state: "completed" },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("正在重构投影系统");
    expect(html).toContain("已确认旧反推链路");
    expect(html).not.toContain("处理清单");
    expect(html).not.toContain("当前：正在接入投影附件");
    expect(html).not.toContain("运行聚焦验证");
  });

  it("filters low-signal task projection activities while keeping meaningful task activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        taskProjections: [
          {
            projection_id: "projection:taskrun:test",
            authority: "harness.runtime.single_agent_task_projection.v1",
            task_run_id: "taskrun:test",
            status: "running",
            todo: {
              active_item_id: "review",
              items: [
                { todo_id: "review", content: "审查显示投影", status: "in_progress" },
              ],
            },
            activities: [
              {
                activity_id: "activity:todo-tool",
                kind: "status",
                source_kind: "tool_action",
                title: "执行 agent_todo",
                detail: "调用 agent_todo。",
                state: "completed",
              },
              {
                activity_id: "activity:read-file",
                kind: "status",
                source_kind: "inspect_path",
                title: "读取文件内容",
                detail: "读取目标文件。",
                state: "completed",
              },
              {
                activity_id: "activity:search-failed",
                kind: "status",
                source_kind: "search_text",
                title: "搜索证据",
                detail: "工具调用失败，正在根据失败原因调整处理路径。",
                state: "failed",
              },
              {
                activity_id: "activity:list-subagents",
                kind: "status",
                source_kind: "tool_action",
                title: "执行 list_subagents",
                detail: "调用 list_subagents。",
                state: "completed",
              },
              {
                activity_id: "activity:write-report",
                kind: "action",
                source_kind: "write_file",
                tool_name: "write_file",
                tool_target: "docs/report.md",
                display_surface: "tool_window",
                visibility_level: "primary",
                title: "写入报告",
                detail: "写入 docs/report.md。",
                state: "completed",
              },
              {
                activity_id: "activity:stage",
                kind: "status",
                source_kind: "stage",
                title: "正在思考",
                detail: "执行 2 个工具调用：读取目录 backend/、执行 agent todo。",
                state: "running",
              },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("写入报告");
    expect(html).toContain("写入 docs/report.md");
    expect(html).toContain("public-run-activity__tool-window");
    expect(html).not.toContain("open=\"\"");
    expect(html).not.toContain("处理清单");
    expect(html).not.toContain("审查显示投影");
    expect(html).not.toContain("正在思考");
    expect(html).not.toContain("执行 agent_todo");
    expect(html).not.toContain("读取文件内容");
    expect(html).not.toContain("搜索证据");
    expect(html).not.toContain("执行 list_subagents");
    expect(html).not.toContain("执行 2 个工具调用");
    expect(html).not.toContain("工具调用失败");
  });

  it("honors task projection visibility levels from the backend", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        taskProjections: [
          {
            projection_id: "projection:taskrun:test",
            authority: "harness.runtime.single_agent_task_projection.v1",
            task_run_id: "taskrun:test",
            status: "running",
            current_action: {
              title: "正在思考",
              state: "running",
              display_surface: "timeline",
              visibility_level: "internal",
            },
            activities: [
              {
                activity_id: "activity:debug-read",
                kind: "status",
                source_kind: "inspect_path",
                display_surface: "diagnostics",
                visibility_level: "debug",
                title: "读取文件内容",
                detail: "读取 backend/sessions/a.json。",
                state: "completed",
              },
              {
                activity_id: "activity:primary-write",
                kind: "action",
                source_kind: "write_file",
                tool_name: "write_file",
                tool_target: "docs/report.md",
                display_surface: "tool_window",
                visibility_level: "primary",
                title: "写入报告",
                detail: "写入 docs/report.md。",
                state: "completed",
              },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("写入报告");
    expect(html).toContain("docs/report.md");
    expect(html).not.toContain("读取文件内容");
    expect(html).not.toContain("backend/sessions");
    expect(html).not.toContain("正在思考");
  });

  it("renders tool windows from semantic public timeline items", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "tool:read-context",
            kind: "work_action",
            surface: "tool_window",
            public_summary: "正在读取上下文 frontend/src/lib/store/runtime.ts",
            state: "running",
            tool_window: {
              tool_label: "读取文件",
              target: "frontend/src/lib/store/runtime.ts",
              status: "调用中",
              sections: [
                { label: "调用", text: "读取文件 frontend/src/lib/store/runtime.ts" },
                { label: "参数", text: "行数 80" },
              ],
            },
          },
        ],
      }),
    );

    expect(html).toContain("public-run-activity__tool-window");
    expect(html).toContain("读取文件");
    expect(html).toContain("调用中");
    expect(html).toContain("<dt>调用</dt>");
    expect(html).toContain("行数 80");
  });

  it("hides completed low-signal inspect and search tool activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "tool:inspect-root",
            kind: "work_action",
            action_kind: "inspect",
            title: "已确认目标",
            subject_label: ".",
            public_summary: "已确认目标 .",
            observation: "No paths matched.",
            phase: "done",
            state: "done",
          },
          {
            item_id: "tool:search-ts",
            kind: "work_action",
            action_kind: "search",
            title: "已搜索引用",
            subject_label: "**/*.{ts,tsx}",
            public_summary: "已搜索引用 **/*.{ts,tsx}",
            observation: "No paths matched.",
            phase: "done",
            state: "done",
          },
          {
            item_id: "tool:write-report",
            kind: "work_action",
            action_kind: "edit",
            title: "已更新文件",
            subject_label: "docs/report.md",
            public_summary: "已更新文件 docs/report.md",
            observation: "报告已写入。",
            phase: "done",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("已更新文件 docs/report.md");
    expect(html).not.toContain("已确认目标 .");
    expect(html).not.toContain("已搜索引用 **/*.{ts,tsx}");
    expect(html).not.toContain("No paths matched");
  });

  it("keeps model body items in chronological order with tool activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "body:start",
            kind: "opening_judgment",
            surface: "body",
            source_authority: "model",
            text: "我先确认当前文件状态。",
            state: "running",
          },
          {
            item_id: "tool:read",
            kind: "work_action",
            surface: "tool_window",
            title: "正在读取 ChatMessage.tsx",
            detail: "读取聊天消息组件。",
            state: "done",
          },
          {
            item_id: "body:after",
            kind: "observation_report",
            surface: "body",
            source_authority: "model",
            detail: "已确认投影入口。",
            state: "done",
          },
        ],
      }),
    );

    expect(html.indexOf("我先确认当前文件状态。")).toBeLessThan(html.indexOf("正在读取 ChatMessage.tsx"));
    expect(html.indexOf("正在读取 ChatMessage.tsx")).toBeLessThan(html.indexOf("已确认投影入口。"));
  });

  it("does not render ask-user control status as public activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "status:waiting-user",
            kind: "status_update",
            surface: "status",
            phase: "waiting_user",
            title: "等待补充信息",
            detail: "审查项目没问题。不过在开始之前，我需要确认一下你的期望： 1. **审查范围**——你希望我全面审查整个项目，还是聚焦某个具体方面？ 2. **审查深度**——是要做快速健康评估，还是深入到具体模块逐文件审查？",
            state: "waiting",
          },
        ],
      }),
    );

    expect(html).toBe("");
  });

  it("preserves markdown paragraphs for model body timeline text", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "body:final",
            kind: "final_summary",
            surface: "body",
            source_authority: "model",
            text: "第一段说明。\n\n第二段说明。\n\n- 第三段要点",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("<p>第一段说明。</p>");
    expect(html).toContain("<p>第二段说明。</p>");
    expect(html).toContain("<li>第三段要点</li>");
    expect(html).not.toContain("第一段说明。 第二段说明。");
  });

  it("restores readable paragraphs for long single-line model body text", () => {
    const denseText = Array(3).fill([
      "柳如焰没有立刻回答。",
      "她的手指仍贴在他腹部，感受着那片滚烫的皮肤底下越来越失控的脉动。",
      "烛火在她眼底跳动，映出一层薄薄的光。",
      "良久，她抽回手，退了一步。",
      "沈雁回瞳孔一缩。",
      "他哑着嗓子，把头别向一边。",
      "柳如焰轻轻笑了。",
      "那笑声在密室里回荡，像银铃碎裂的声音。",
      "他知道自己不该开口。",
      "可他更清楚，在这间密室里，沉默也是一种交锋。",
    ].join(" ")).join(" ");
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "body:dense",
            kind: "final_summary",
            surface: "body",
            source_authority: "model",
            text: denseText,
            state: "done",
          },
        ],
      }),
    );

    expect(html.match(/<p>/g)?.length ?? 0).toBeGreaterThan(1);
  });
});
