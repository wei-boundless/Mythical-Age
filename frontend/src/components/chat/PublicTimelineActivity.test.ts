import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PublicTimelineActivity } from "./PublicTimelineActivity";

function attributeValues(html: string, name: string) {
  return Array.from(html.matchAll(new RegExp(`${name}="([^"]*)"`, "g"))).map((match) => match[1]);
}

describe("PublicTimelineActivity", () => {
  it("renders natural-language task stage feedback with body typography", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        taskProjections: [
          {
            authority: "harness.runtime.single_agent_task_projection.v1",
            projection_id: "projection:stage-feedback",
            task_run_id: "taskrun:stage-feedback",
            status: "running",
            current_action: {
              activity_id: "activity:stage-feedback",
              kind: "progress",
              source_kind: "stage_feedback",
              display_surface: "timeline",
              visibility_level: "secondary",
              title: "开始执行三项核查：读取 prompt_ref_migrations 尾部以确认 prompt_pack_refs_by_invocation 配置，定位 single_agent_turn 中的 invocation_kind 和 compiler 调用点，并获取 profiles 目录完整列表以查找三种环境的配置文件",
              state: "running",
            },
          },
        ],
      }),
    );

    expect(html).toContain("public-run-activity__body");
    expect(attributeValues(html, "data-activity-kind")).toContain("body");
    expect(html).toContain("开始执行三项核查");
    expect(html).not.toContain("public-run-activity__line--status");
  });

  it("does not promote tool echo stage feedback to body typography", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        taskProjections: [
          {
            authority: "harness.runtime.single_agent_task_projection.v1",
            projection_id: "projection:tool-echo",
            task_run_id: "taskrun:tool-echo",
            status: "running",
            activities: [
              {
                activity_id: "activity:path",
                kind: "progress",
                source_kind: "stage_feedback",
                display_surface: "timeline",
                visibility_level: "secondary",
                title: "system_control_review.md",
                state: "running",
              },
              {
                activity_id: "activity:timeout",
                kind: "progress",
                source_kind: "stage_feedback",
                display_surface: "timeline",
                visibility_level: "secondary",
                title: "task_tool_batch_group_timeout_after_300s",
                state: "running",
              },
            ],
          },
        ],
      }),
    );

    expect(html).toBe("");
  });

  it("renders timeline activity in backend event sequence order", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "event:3",
            kind: "status_update",
            slot: "timeline",
            surface: "timeline",
            title: "第三步",
            state: "running",
            sequence: 3,
            event_offset: 3,
            source_event_id: "event:3",
          },
          {
            item_id: "event:1",
            kind: "status_update",
            slot: "timeline",
            surface: "timeline",
            title: "第一步",
            state: "running",
            sequence: 1,
            event_offset: 1,
            source_event_id: "event:1",
          },
          {
            item_id: "event:2",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            action_kind: "read",
            title: "第二步",
            public_summary: "第二步",
            subject_label: "docs/a.md",
            state: "done",
            sequence: 2,
            event_offset: 2,
            source_event_id: "event:2",
          },
        ],
      }),
    );

    expect(html.indexOf("第一步")).toBeLessThan(html.indexOf("第二步"));
    expect(html.indexOf("第二步")).toBeLessThan(html.indexOf("第三步"));
  });

  it("keeps tool error codes inside the tool window instead of using them as the activity title", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "tool:rehydrate:error",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            action_kind: "runtime_read",
            title: "工具输出读取失败",
            public_summary: "missing_required_tool_inputs",
            state: "error",
          },
        ],
      }),
    );

    expect(html).toContain("<summary>工具输出读取失败</summary>");
    expect(html).toContain("<dd>missing_required_tool_inputs</dd>");
  });

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

  it("honors timeline display surface before task activity kind", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        taskProjections: [
          {
            projection_id: "projection:taskrun:surface",
            authority: "harness.runtime.single_agent_task_projection.v1",
            task_run_id: "taskrun:surface",
            status: "running",
            activities: [
              {
                activity_id: "activity:observation",
                kind: "observation",
                display_surface: "timeline",
                visibility_level: "secondary",
                title: "已确认公开投影入口",
                detail: "后端已声明这是一条时间线活动。",
                state: "completed",
              },
              {
                activity_id: "activity:action",
                kind: "action",
                display_surface: "timeline",
                visibility_level: "secondary",
                title: "继续收口渲染逻辑",
                state: "running",
              },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("已确认公开投影入口");
    expect(html).toContain("继续收口渲染逻辑");
    expect(html).not.toContain("public-run-activity__tool-window");
  });

  it("orders timeline and task projection activity by runtime refs and merges matching tools", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "timeline:status:first",
            kind: "work_action",
            slot: "timeline",
            surface: "timeline",
            source_authority: "runtime",
            title: "phase-a",
            state: "running",
            trace_refs: ["rtevt:taskrun:test:1:aaa"],
          },
          {
            item_id: "tool:shared-read",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            action_kind: "read",
            subject_label: "src/projection.ts",
            title: "tool-a-running",
            detail: "tool-a-call",
            state: "running",
            trace_refs: ["rtevt:taskrun:test:2:bbb"],
            tool_window: {
              tool_label: "read_file",
              target: "src/projection.ts",
              status: "running",
              sections: [{ label: "call", text: "src/projection.ts" }],
            },
          },
          {
            item_id: "timeline:status:last",
            kind: "work_action",
            slot: "timeline",
            surface: "timeline",
            source_authority: "runtime",
            title: "phase-c",
            state: "running",
            trace_refs: ["rtevt:taskrun:test:4:ddd"],
          },
        ],
        taskProjections: [
          {
            projection_id: "projection:taskrun:ordered-merge",
            authority: "harness.runtime.single_agent_task_projection.v1",
            task_run_id: "taskrun:ordered-merge",
            status: "running",
            activities: [
              {
                activity_id: "activity:shared-read-result",
                kind: "action",
                source_kind: "read",
                tool_name: "read_file",
                tool_target: "src/projection.ts",
                display_surface: "tool_window",
                visibility_level: "primary",
                title: "tool-a-done",
                detail: "tool-a-result",
                state: "completed",
                event_ref: "rtevt:taskrun:test:2:bbb",
              },
              {
                activity_id: "activity:phase-b",
                kind: "observation",
                display_surface: "timeline",
                visibility_level: "secondary",
                title: "phase-b",
                state: "completed",
                event_ref: "rtevt:taskrun:test:3:ccc",
              },
            ],
          },
        ],
      }),
    );

    expect(attributeValues(html, "data-activity-kind").filter((value) => value === "tool")).toHaveLength(1);
    expect(attributeValues(html, "data-activity-source")).toContain("timeline+projection");
    const orders = attributeValues(html, "data-activity-order").map(Number);
    expect(orders).toHaveLength(4);
    expect(orders).toEqual([...orders].sort((left, right) => left - right));
    expect(Math.floor(orders[1])).toBe(2);
  });

  it("lets stopped task projection dominate stale running projection activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        taskProjections: [
          {
            projection_id: "projection:taskrun:stopped",
            authority: "harness.runtime.single_agent_task_projection.v1",
            task_run_id: "taskrun:stopped",
            status: "stopped",
            current_action: {
              title: "正在思考",
              state: "running",
            },
            activities: [
              {
                activity_id: "activity:thinking",
                kind: "status",
                title: "正在思考",
                state: "running",
              },
              {
                activity_id: "activity:write-running",
                kind: "action",
                source_kind: "write_file",
                tool_name: "write_file",
                tool_target: "docs/report.md",
                display_surface: "tool_window",
                visibility_level: "primary",
                title: "正在写入报告",
                detail: "旧的运行中工具窗口。",
                state: "running",
              },
              {
                activity_id: "activity:write-waiting",
                kind: "action",
                source_kind: "write_file",
                tool_name: "write_file",
                display_surface: "tool_window",
                visibility_level: "primary",
                title: "等待中的旧动作",
                detail: "旧的等待中工具窗口。",
                state: "waiting",
              },
            ],
          },
        ],
        items: [
          {
            item_id: "tool:stale",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            title: "旧的工具窗口仍在运行",
            detail: "这是一条已经过期的 running timeline。",
            state: "running",
          },
          {
            item_id: "tool:stale-waiting",
            kind: "status_update",
            slot: "status",
            surface: "status_bar",
            source_authority: "system",
            title: "旧等待状态",
            detail: "这是一条已经过期的 waiting timeline。",
            state: "waiting",
          },
          {
            item_id: "body:stale-progress",
            kind: "opening_judgment",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "旧的正文进度还在运行。",
            state: "running",
          },
          {
            item_id: "body:final",
            kind: "final_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "已保留的完成正文。",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("任务已停止");
    expect(html).not.toContain("正在思考");
    expect(html).not.toContain("正在写入报告");
    expect(html).not.toContain("等待中的旧动作");
    expect(html).not.toContain("旧的工具窗口仍在运行");
    expect(html).not.toContain("旧等待状态");
    expect(html).not.toContain("旧的正文进度还在运行");
    expect(html).not.toContain("已保留的完成正文");
    expect(html).not.toContain("运行中");
  });

  it("lets paused task projection suppress stale running activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        taskProjections: [
          {
            projection_id: "projection:taskrun:paused",
            authority: "harness.runtime.single_agent_task_projection.v1",
            task_run_id: "taskrun:paused",
            status: "paused",
            current_action: {
              title: "正在处理",
              state: "running",
            },
            activities: [
              {
                activity_id: "activity:running",
                kind: "action",
                display_surface: "tool_window",
                visibility_level: "primary",
                title: "仍在执行旧动作",
                detail: "旧动作不应该在暂停态继续显示。",
                state: "running",
              },
              {
                activity_id: "activity:waiting",
                kind: "action",
                display_surface: "tool_window",
                visibility_level: "primary",
                title: "等待中的旧动作",
                detail: "旧等待动作也不应该覆盖暂停态。",
                state: "waiting",
              },
            ],
          },
        ],
        items: [
          {
            item_id: "tool:paused-stale",
            kind: "tool_activity",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            title: "旧工具还在跑",
            detail: "旧 timeline 不应该覆盖暂停态。",
            state: "running",
          },
          {
            item_id: "tool:paused-waiting-stale",
            kind: "status_update",
            slot: "status",
            surface: "status_bar",
            source_authority: "system",
            title: "旧等待状态",
            detail: "旧 waiting timeline 不应该覆盖暂停态。",
            state: "waiting",
          },
        ],
      }),
    );

    expect(html).toContain("任务已暂停");
    expect(html).not.toContain("仍在执行旧动作");
    expect(html).not.toContain("等待中的旧动作");
    expect(html).not.toContain("旧工具还在跑");
    expect(html).not.toContain("旧等待状态");
    expect(html).not.toContain("运行中");
  });

  it("renders waiting safe boundary as a control-state activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        taskProjections: [
          {
            projection_id: "projection:taskrun:safe-boundary",
            authority: "harness.runtime.single_agent_task_projection.v1",
            task_run_id: "taskrun:safe-boundary",
            status: "waiting_safe_boundary",
          },
        ],
      }),
    );

    expect(html).toContain("等待安全边界");
    expect(html).not.toContain("开始处理");
    expect(html).not.toContain("处理完成");
  });

  it("renders tool windows from semantic public timeline items", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "tool:read-context",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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

  it("folds completed low-signal inspect and search tool activity instead of dropping it", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "tool:inspect-root",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
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
    expect(html).toContain("已确认目标");
    expect(html).toContain("已搜索引用 **/*.{ts,tsx}");
    expect(html).toContain("No paths matched");
    expect(attributeValues(html, "data-activity-kind").filter((value) => value === "tool")).toHaveLength(3);
    expect(html).not.toContain("open=\"\"");
  });

  it("renders tool activity without taking ownership of model body items", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "body:start",
            kind: "opening_judgment",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "我先确认当前文件状态。",
            state: "running",
          },
          {
            item_id: "tool:read",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            title: "正在读取 ChatMessage.tsx",
            detail: "读取聊天消息组件。",
            state: "done",
          },
          {
            item_id: "body:after",
            kind: "observation_report",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            detail: "已确认投影入口。",
            state: "done",
          },
        ],
      }),
    );

    expect(html).not.toContain("我先确认当前文件状态。");
    expect(html).toContain("正在读取 ChatMessage.tsx");
    expect(html).not.toContain("已确认投影入口。");
  });

  it("does not render ask-user control status as public activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "status:waiting-user",
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
      }),
    );

    expect(html).toBe("");
    expect(html).not.toContain("等待补充信息");
    expect(html).not.toContain("审查项目没问题");
    expect(html).not.toContain("LangChain-Agent");
    expect(html).not.toContain("1 | #");
    expect(html).not.toContain("这是工具读取的文件原文");
  });

  it("does not render generic system status as public activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "status:generic-running",
            kind: "status_update",
            slot: "status",
            surface: "status_bar",
            source_authority: "system",
            title: "正在处理任务",
            state: "running",
          },
          {
            item_id: "status:generic-done",
            kind: "status_update",
            slot: "status",
            surface: "status_bar",
            source_authority: "system",
            title: "处理完成",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toBe("");
  });

  it("keeps line-numbered tool output out of body while preserving the tool row", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "body:raw-tool-output",
            kind: "final_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "  1 | # LangChain-Agent 项目代码审查报告\n  2 | 这是工具读取的文件原文。",
            state: "done",
          },
          {
            item_id: "tool:raw-observation",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "tool",
            title: "读取完成",
            observation: "  1 | # LangChain-Agent 项目代码审查报告",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("public-run-activity__tool-window");
    expect(html).toContain("读取完成");
    expect(html).not.toContain("LangChain-Agent 项目代码审查报告");
    expect(html).not.toContain("1 | #");
  });

  it("leaves markdown model body timeline text for the chat message body renderer", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "body:final",
            kind: "final_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "第一段说明。\n\n第二段说明。\n\n- 第三段要点",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toBe("");
    expect(html).not.toContain("第一段说明。");
    expect(html).not.toContain("<li>第三段要点</li>");
  });

  it("does not render long single-line model body text as activity", () => {
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
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: denseText,
            state: "done",
          },
        ],
      }),
    );

    expect(html).toBe("");
    expect(html).not.toContain("柳如焰没有立刻回答");
  });
});
