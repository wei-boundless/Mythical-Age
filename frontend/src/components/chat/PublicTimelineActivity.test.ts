import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PublicTimelineActivity } from "./PublicTimelineActivity";

function attributeValues(html: string, name: string) {
  return Array.from(html.matchAll(new RegExp(`${name}="([^"]*)"`, "g"))).map((match) => match[1]);
}

describe("PublicTimelineActivity", () => {
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
            state: "waiting",
            sequence: 3,
          },
          {
            item_id: "event:1",
            kind: "status_update",
            slot: "timeline",
            surface: "timeline",
            title: "第一步",
            state: "waiting",
            sequence: 1,
          },
          {
            item_id: "event:2",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            action_kind: "read",
            title: "第二步",
            subject_label: "docs/a.md",
            state: "done",
            sequence: 2,
          },
        ],
      }),
    );

    expect(html.indexOf("第一步")).toBeLessThan(html.indexOf("第二步"));
    expect(html.indexOf("第二步")).toBeLessThan(html.indexOf("第三步"));
  });

  it("renders tool windows from semantic public projection items", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "tool:read-context",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            source_authority: "model",
            title: "读取上下文 frontend/src/lib/store/runtime.ts",
            subject_label: "frontend/src/lib/store/runtime.ts",
            state: "running",
            tool_window: {
              tool_label: "read_file",
              target: "frontend/src/lib/store/runtime.ts",
              status: "运行中",
              sections: [
                { label: "说明", text: "模型请求读取运行链路。" },
              ],
            },
          },
        ],
      }),
    );

    expect(html).toContain("public-run-activity__tool-window");
    expect(html).toContain("读取上下文 frontend/src/lib/store/runtime.ts");
    expect(html).toContain("read_file");
    expect(html).toContain("<dt>说明</dt>");
    expect(html).toContain("模型请求读取运行链路");
  });

  it("keeps failed and waiting status visible while filtering generic status", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "status:generic",
            kind: "status_update",
            slot: "status",
            surface: "status_bar",
            title: "正在处理任务",
            state: "running",
          },
          {
            item_id: "status:waiting",
            kind: "status_update",
            slot: "status",
            surface: "timeline",
            title: "等待权限确认",
            detail: "需要用户批准写入。",
            state: "waiting",
          },
          {
            item_id: "status:failed",
            kind: "status_update",
            slot: "status",
            surface: "timeline",
            title: "提交失败",
            detail: "commit_ack 未返回。",
            state: "failed",
          },
        ],
      }),
    );

    expect(html).toContain("等待权限确认");
    expect(html).toContain("提交失败");
    expect(html).not.toContain("正在处理任务");
    expect(attributeValues(html, "data-activity-kind")).toEqual(["status", "status"]);
  });

  it("does not render body or control items as activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "body:final",
            kind: "final_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "正文应由 ChatMessage 渲染。",
            state: "done",
          },
          {
            item_id: "control:ask",
            kind: "status_update",
            slot: "control",
            surface: "control",
            source_authority: "system",
            title: "等待补充信息",
            detail: "不要把控制问题塞进活动区。",
            state: "waiting",
          },
        ],
      }),
    );

    expect(html).toBe("");
  });

  it("folds completed tool windows but keeps their result available", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicTimelineActivity, {
        items: [
          {
            item_id: "tool:verify",
            kind: "work_action",
            slot: "tool",
            surface: "tool_window",
            action_kind: "verify",
            title: "验证完成",
            observation: "12 tests passed",
            state: "done",
          },
        ],
      }),
    );

    expect(html).toContain("public-run-activity__tool-window");
    expect(html).toContain("<summary>验证完成</summary>");
    expect(html).toContain("12 tests passed");
    expect(html).not.toContain("open=\"\"");
  });
});
