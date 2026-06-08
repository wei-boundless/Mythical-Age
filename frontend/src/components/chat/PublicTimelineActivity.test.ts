import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PublicTimelineActivity } from "./PublicTimelineActivity";

describe("PublicTimelineActivity", () => {
  it("renders task projection todo and current action without public timeline inference", () => {
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

    expect(html).toContain("处理清单");
    expect(html).toContain("当前：正在接入投影附件");
    expect(html).toContain("正在重构投影系统");
    expect(html).toContain("已确认旧反推链路");
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
