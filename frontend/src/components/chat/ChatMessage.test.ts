import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatMessage } from "./ChatMessage";
import type { MessagePublicProjection } from "@/lib/api";

function projection(patch: Partial<MessagePublicProjection>): MessagePublicProjection {
  return {
    bodyText: "",
    bodyState: "streaming",
    bodyBlocks: [],
    pinned: [],
    finalResults: [],
    status: [],
    trace: [],
    timeline: [],
    traceAvailable: false,
    traceCount: 0,
    commitState: "none",
    ...patch,
  };
}

function assistantProps(patch: Partial<React.ComponentProps<typeof ChatMessage>> = {}): React.ComponentProps<typeof ChatMessage> {
  return {
    content: "",
    id: "assistant:test",
    retrievals: [],
    role: "assistant",
    toolCalls: [],
    ...patch,
  };
}

describe("ChatMessage", () => {
  it("only renders the edit affordance when the caller says a user message is editable", () => {
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

  it("renders public projection body as the assistant prose authority", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        content: "旧的临时正文",
        publicProjection: projection({
          bodyText: "这是 public_projection_frame 提交的正文。",
          bodyState: "finalized",
        }),
      })),
    );

    expect(html).toContain("这是 public_projection_frame 提交的正文。");
    expect(html).not.toContain("旧的临时正文");
    expect(html).toContain("复制回复");
  });

  it("renders tool projection activity as ordered execution trajectory", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        publicProjection: projection({
          bodyText: "我先检查。检查完成。",
          bodyState: "streaming",
          bodyEventOffset: 5,
          timeline: [
            {
              itemId: "tool-life:read",
              slot: "tool",
              text: "读取投影 reducer",
              title: "读取投影 reducer",
              detail: "模型请求读取 reducer.ts。",
              state: "done",
              sourceAuthority: "model",
              mainVisibility: "visible_live",
              retention: "transient",
              toolCallId: "call:read",
              toolLifecycleId: "tool-life:read",
              toolName: "read_file",
              subjectLabel: "frontend/src/lib/projection/reducer.ts",
              eventOffset: 2,
              updatedEventOffset: 4,
              sourceEventType: "tool_item_completed",
            },
          ],
        }),
      })),
    );

    expect(html).toContain("public-run-activity");
    expect(html).toContain("执行轨迹");
    expect(html).toContain("读取投影 reducer");
    expect(html).toContain("模型请求读取 reducer.ts");
    expect(html).toContain("已完成");
    expect(html).toContain("我先检查。检查完成。");
    expect(html.indexOf("读取投影 reducer")).toBeLessThan(html.indexOf("我先检查。检查完成。"));
    expect(html).toContain("public-run-activity__line");
    expect(html).toContain('data-activity-kind="tool_lifecycle"');
    expect(html).not.toContain("public-run-activity__tool-window");
  });

  it("interleaves body blocks and tool trajectory by projection event offset", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        publicProjection: projection({
          bodyText: "先说明。再继续。",
          bodyState: "streaming",
          bodyBlocks: [
            {
              kind: "body",
              blockId: "body:1",
              text: "先说明。",
              firstOffset: 1,
              lastOffset: 1,
              state: "streaming",
              sourceFrameIds: ["frame:body:1"],
            },
            {
              kind: "body",
              blockId: "body:5",
              text: "再继续。",
              firstOffset: 5,
              lastOffset: 5,
              state: "streaming",
              sourceFrameIds: ["frame:body:5"],
            },
          ],
          timeline: [
            {
              itemId: "tool-life:read",
              slot: "tool",
              text: "读取投影 reducer",
              title: "读取投影 reducer",
              detail: "模型请求读取 reducer.ts。",
              state: "done",
              sourceAuthority: "model",
              mainVisibility: "visible_live",
              retention: "transient",
              toolCallId: "call:read",
              toolLifecycleId: "tool-life:read",
              toolName: "read_file",
              subjectLabel: "frontend/src/lib/projection/reducer.ts",
              eventOffset: 3,
              updatedEventOffset: 4,
              sourceEventType: "tool_item_completed",
            },
          ],
        }),
      })),
    );

    expect(html.indexOf("先说明。")).toBeLessThan(html.indexOf("读取投影 reducer"));
    expect(html.indexOf("读取投影 reducer")).toBeLessThan(html.indexOf("再继续。"));
    expect(html.match(/aria-label="复制回复"/g)).toHaveLength(1);
  });

  it("keeps separate tool lifecycles as separate trajectory rows even when their text matches", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        publicProjection: projection({
          timeline: [
            {
              itemId: "tool-life:search:1",
              slot: "tool",
              text: "搜索文件：mario",
              title: "搜索文件：mario",
              state: "running",
              sourceAuthority: "model",
              mainVisibility: "visible_live",
              retention: "transient",
              toolCallId: "call:search:1",
              toolLifecycleId: "tool-life:search:1",
              toolName: "search_files",
              eventOffset: 2,
            },
            {
              itemId: "tool-life:search:2",
              slot: "tool",
              text: "搜索文件：mario",
              title: "搜索文件：mario",
              state: "running",
              sourceAuthority: "model",
              mainVisibility: "visible_live",
              retention: "transient",
              toolCallId: "call:search:2",
              toolLifecycleId: "tool-life:search:2",
              toolName: "search_files",
              eventOffset: 3,
            },
          ],
        }),
      })),
    );

    expect(html.match(/搜索文件：mario/g)).toHaveLength(2);
    expect(html.match(/data-activity-kind="tool_lifecycle"/g)).toHaveLength(2);
    expect(html).not.toContain("public-run-activity__count");
  });

  it("renders feedback status separately from tool lifecycle activity", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        publicProjection: projection({
          timeline: [
            {
              itemId: "status:stage",
              slot: "status",
              text: "用更宽泛的关键词再搜。",
              title: "用更宽泛的关键词再搜。",
              state: "running",
              sourceAuthority: "model",
              mainVisibility: "visible_live",
              retention: "transient",
              eventOffset: 2,
            },
            {
              itemId: "tool-life:glob",
              slot: "tool",
              text: "匹配路径：**/*mario*",
              title: "匹配路径：**/*mario*",
              state: "running",
              sourceAuthority: "model",
              mainVisibility: "visible_live",
              retention: "transient",
              toolCallId: "call:glob",
              toolLifecycleId: "tool-life:glob",
              toolName: "glob_paths",
              eventOffset: 3,
            },
          ],
        }),
      })),
    );

    expect(html).toContain('data-activity-kind="status"');
    expect(html).toContain('data-activity-kind="tool_lifecycle"');
    expect(html).toContain("用更宽泛的关键词再搜。");
    expect(html).toContain("匹配路径：**/*mario*");
  });

  it("renders internal tool names and states as user-facing labels", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        publicProjection: projection({
          timeline: [
            {
              itemId: "tool-life:stat",
              slot: "tool",
              text: "stat_path：mario.html",
              title: "stat_path：mario.html",
              state: "running",
              sourceAuthority: "model",
              mainVisibility: "visible_live",
              retention: "transient",
              toolCallId: "call:stat",
              toolLifecycleId: "tool-life:stat",
              toolName: "stat_path",
              subjectLabel: "mario.html",
              eventOffset: 2,
            },
          ],
        }),
      })),
    );

    expect(html).toContain("检查路径：mario.html");
    expect(html).toContain("运行中");
    expect(html).not.toContain("stat_path");
  });

  it("surfaces tool-owned failures as tool trajectory instead of assistant prose", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        publicProjection: projection({
          timeline: [
            {
              itemId: "tool:failed",
              slot: "tool",
              text: "读取文件失败",
              title: "读取文件失败",
              detail: "read_file 返回错误。",
              state: "failed",
              sourceAuthority: "tool",
              mainVisibility: "pinned",
              retention: "pinned_until_resolved",
              toolName: "read_file",
              toolCallId: "call:read",
              eventOffset: 2,
            },
          ],
        }),
      })),
    );

    expect(html).toContain("public-run-activity__tool-window");
    expect(html).toContain("读取文件失败");
    expect(html).toContain("read_file 返回错误");
    expect(html).not.toContain("复制回复");
  });

  it("shows a thinking placeholder while streaming has no model body", () => {
    const thinking = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        streamingContent: true,
      })),
    );
    const active = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        streamingContent: true,
        publicProjection: projection({
          currentAction: {
            itemId: "tool:verify",
            slot: "current_action",
            text: "运行验证",
            title: "运行验证",
            state: "running",
            mainVisibility: "visible_live",
            retention: "transient",
            toolCallId: "call:verify",
          },
        }),
      })),
    );

    expect(thinking).toContain("正在思考");
    expect(active).not.toContain("正在思考");
    expect(active).toContain("运行验证");
  });

  it("hides completed transient tools after commit when the ledger has retired them", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        publicProjection: projection({
          bodyText: "最终结论已经稳定。",
          bodyState: "committed",
          commitState: "committed",
          traceAvailable: true,
          traceCount: 2,
        }),
      })),
    );

    expect(html).toContain("最终结论已经稳定。");
    expect(html).not.toContain("public-run-activity");
  });

  it("shows only finalized assistant body after projection closes", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        publicProjection: projection({
          bodyText: "最终正文。",
          bodyState: "finalized",
          timeline: [
            {
              itemId: "call:read",
              slot: "tool",
              text: "读取文件",
              title: "读取文件",
              state: "done",
              mainVisibility: "visible_live",
              retention: "transient",
              toolCallId: "call:read",
              toolName: "read_file",
              eventOffset: 2,
            },
          ],
        }),
      })),
    );

    expect(html).toContain("最终正文。");
    expect(html).not.toContain("读取文件");
    expect(html).not.toContain("public-run-activity");
  });

  it("hides internal model action protocol content", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        answerCanonicalState: "stable_answer",
        answerChannel: "conversation",
        answerPersistPolicy: "persist_canonical",
        content: '{"authority":"harness.loop.model_action_request","action_type":"active_work_control","active_work_control":{"action":"continue_active_work"}}',
      })),
    );

    expect(html).not.toContain("harness.loop.model_action_request");
    expect(html).not.toContain("continue_active_work");
    expect(html).not.toContain("复制回复");
  });

  it("hides internal model action protocol content from projection body", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatMessage, assistantProps({
        content: "",
        publicProjection: projection({
          bodyText: '已确认材料。\n{"authority":"harness.loop.model_action_request","action_type":"request_task_run","task_contract_seed":{"user_visible_goal":"继续修复"}}',
          bodyState: "finalized",
        }),
      })),
    );

    expect(html).not.toContain("harness.loop.model_action_request");
    expect(html).not.toContain("request_task_run");
    expect(html).not.toContain("继续修复");
    expect(html).not.toContain("复制回复");
  });
});
