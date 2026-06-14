import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatMessage } from "./ChatMessage";
import type { MessagePublicProjection } from "@/lib/api";

function projection(patch: Partial<MessagePublicProjection>): MessagePublicProjection {
  return {
    bodyText: "",
    bodyState: "streaming",
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
          bodyText: "最终回复。",
          bodyState: "finalized",
          bodyEventOffset: 5,
          currentAction: {
            itemId: "tool:read",
            slot: "current_action",
            text: "读取投影 reducer",
            title: "读取投影 reducer",
            detail: "模型请求读取 reducer.ts。",
            state: "running",
            sourceAuthority: "model",
            mainVisibility: "visible_live",
            retention: "transient",
            toolCallId: "call:read",
            permissionDecisionId: "permission:read",
            toolName: "read_file",
            subjectLabel: "frontend/src/lib/projection/reducer.ts",
          },
          timeline: [
            {
              itemId: "frame:tool-requested",
              slot: "tool",
              text: "读取投影 reducer",
              title: "读取投影 reducer",
              detail: "模型请求读取 reducer.ts。",
              state: "running",
              sourceAuthority: "model",
              mainVisibility: "visible_live",
              retention: "transient",
              toolCallId: "call:read",
              toolName: "read_file",
              subjectLabel: "frontend/src/lib/projection/reducer.ts",
              eventOffset: 1,
              sourceEventType: "tool_call_requested",
            },
            {
              itemId: "frame:tool-completed",
              slot: "tool",
              text: "读取完成",
              title: "读取完成",
              state: "done",
              sourceAuthority: "tool",
              mainVisibility: "trace_only",
              retention: "trace",
              toolCallId: "call:read",
              toolName: "read_file",
              eventOffset: 4,
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
    expect(html).toContain("读取完成");
    expect(html).toContain("最终回复。");
    expect(html.indexOf("读取投影 reducer")).toBeLessThan(html.indexOf("最终回复。"));
    expect(html).toContain("public-run-activity__tool-window");
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
