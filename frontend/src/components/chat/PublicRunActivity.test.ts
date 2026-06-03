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

  it("keeps only the active action prominent while folding older activity into context", () => {
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

    expect(html).toContain("已核对 3 项上下文，正在基于结果继续。");
    expect(html).not.toContain("处理已开始");
    expect(html).not.toContain("读取项目结构");
    expect(html).not.toContain("检查配置文件");
    expect(html).not.toContain("搜索入口组件");
    expect(html).toContain("运行命令");
    expect(html).toContain("npm test");
    expect(html).toContain("public-run-activity__row--current");
  });

  it("collapses duplicated file reads and presents search as a single current action", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        attachments: [
          {
            attachment_id: "runtime-attachment:search",
            run_id: "taskrun:search",
            anchor_turn_id: "turn:session:1",
            status: "running",
            public_timeline: [
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
          },
        ],
      }),
    );

    expect(html).toContain("已核对 1 项上下文，正在基于结果继续。");
    expect(html).toContain("搜索代码引用");
    expect(html).toContain("function attack");
    expect(html.match(/storage/g)?.length ?? 0).toBe(0);
    expect(html).toContain("public-run-activity__row--current");
  });

  it("keeps agent feedback separate from the active tool action", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        attachments: [
          {
            attachment_id: "runtime-attachment:agent-feedback",
            run_id: "taskrun:agent-feedback",
            anchor_turn_id: "turn:session:1",
            status: "running",
            public_timeline: [
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
          },
        ],
      }),
    );

    expect(html).toContain("public-run-activity__agent-message");
    expect(html).toContain("我先检查文件写入权限和可用路径");
    expect(html).toContain("public-run-activity__row--current");
    expect(html).toContain("检查路径信息");
  });

  it("suppresses duplicate tool guard system control text", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        attachments: [
          {
            attachment_id: "runtime-attachment:duplicate",
            run_id: "taskrun:duplicate",
            anchor_turn_id: "turn:session:1",
            status: "running",
            public_timeline: [
              {
                item_id: "duplicate",
                kind: "tool_activity",
                title: "重复只读工具调用被拦截，已有观察将继续参与上下文。",
                state: "running",
              },
            ],
          },
        ],
      }),
    );

    expect(html).toBe("");
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

  it("renders artifact refs from attachment using logical paths only", () => {
    const html = renderToStaticMarkup(
      React.createElement(PublicRunActivity, {
        attachments: [
          {
            attachment_id: "runtime-attachment:artifact",
            run_id: "taskrun:artifact",
            anchor_turn_id: "turn:session:1",
            status: "completed",
            artifact_refs: [
              {
                path: "storage/task_environments/general/workspace/artifacts/plan.md",
                absolute_path: "D:/workspace/storage/runtime_state/sandboxes/taskrun/plan.md",
                kind: "file",
              },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("产物已生成");
    expect(html).toContain("storage/task_environments/general/workspace/artifacts/plan.md");
    expect(html).not.toContain("runtime_state/sandboxes");
  });
});
