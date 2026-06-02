import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { hasPublicRunActivity, PublicRunActivity } from "./PublicRunActivity";

describe("PublicRunActivity", () => {
  it("renders public tool activity as compact assistant-side rows", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        attachments: [
          {
            attachment_id: "runtime-attachment:tool",
            run_id: "taskrun:tool",
            anchor_turn_id: "turn:session:1",
            status: "running",
            public_timeline: [
              {
                item_id: "tool:path",
                kind: "tool_activity",
                title: "确认 artifact 路径",
                detail: "目标文件尚未存在，下一步需要创建。",
                state: "done",
                trace_refs: ["rtevt:obs"],
              },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("public-run-activity");
    expect(html).toContain("确认 artifact 路径");
    expect(html).toContain("目标文件尚未存在");
    expect(html).not.toContain("查看执行细节");
    expect(html).not.toContain("查看技术细节");
    expect(html).not.toContain("rtevt:obs");
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

    expect(hasPublicRunActivity(attachments, "已完成五层地下塔的核心结构、关键交互和验收记录。")).toBe(false);
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        attachments,
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

    expect(hasPublicRunActivity(attachments)).toBe(false);
  });

  it("keeps the active action visible while folding older activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        attachments: [
          {
            attachment_id: "runtime-attachment:active",
            run_id: "taskrun:active",
            anchor_turn_id: "turn:session:1",
            status: "running",
            public_timeline: [
              { item_id: "status:start", kind: "status_update", title: "处理已开始", state: "running" },
              { item_id: "tool:1", kind: "tool_activity", title: "读取项目结构", state: "done" },
              { item_id: "tool:2", kind: "tool_activity", title: "检查配置文件", state: "done" },
              { item_id: "tool:3", kind: "tool_activity", title: "搜索入口组件", state: "done" },
              { item_id: "tool:4", kind: "tool_activity", title: "正在运行测试", detail: "npm test", state: "running", stream_state: "streaming" },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("已完成 1 个步骤，已折叠。");
    expect(html).not.toContain("处理已开始");
    expect(html).not.toContain("读取项目结构");
    expect(html).toContain("检查配置文件");
    expect(html).toContain("搜索入口组件");
    expect(html).toContain("正在运行测试");
    expect(html).toContain("public-run-activity__row--current");
  });

  it("shows a background closeout summary when it is not duplicated by assistant prose", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        attachments: [
          {
            attachment_id: "runtime-attachment:final",
            run_id: "taskrun:final",
            anchor_turn_id: "turn:session:1",
            status: "completed",
            public_timeline: [
              {
                item_id: "final:closeout",
                kind: "final_summary",
                text: "已完成实现、测试和收口说明。",
                state: "done",
              },
            ],
          },
        ],
        assistantContent: "",
      }),
    );

    expect(html).toContain("已完成实现、测试和收口说明。");
    expect(html).toContain("public-run-activity__row--final");
  });
});
