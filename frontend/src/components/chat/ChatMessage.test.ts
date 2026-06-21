import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ChronologicalProjectionView } from "@/lib/projection/chronological";
import { ChatMessage } from "./ChatMessage";

type ProjectionBlock = ChronologicalProjectionView["blocks"][number];
type ActivityArchiveBlock = Extract<ProjectionBlock, { kind: "activity_archive" }>;
type BodyBlock = Extract<ProjectionBlock, { kind: "body_segment" }>;
type ToolBlock = Extract<ProjectionBlock, { kind: "tool_event" }>;

function projectionView(patch: Partial<ChronologicalProjectionView> = {}): ChronologicalProjectionView {
  return {
    displayMode: "committed",
    canonicalContent: "已经完成的正文。",
    copyText: "已经完成的正文。",
    bodyState: "committed",
    blocks: [
      bodyBlock(),
      toolBlock(),
    ],
    toolEventCount: 1,
    traceAvailable: true,
    diagnostics: [],
    ...patch,
  };
}

function bodyBlock(text = "已经完成的正文。", firstOffset = 10): BodyBlock {
  return {
    kind: "body_segment",
    id: `body:${firstOffset}`,
    text,
    firstOffset,
    lastOffset: firstOffset,
    state: "committed",
  };
}

function toolBlock(): ToolBlock {
  return {
    kind: "tool_event",
    id: "tool:read-project",
    title: "读取项目文件",
    detail: "读取 frontend/src/components/chat/ChatMessage.tsx",
    state: "done",
    toolCallId: "call:read-project",
    toolLifecycleId: "",
    toolName: "read_file",
    actionKind: "",
    target: "ChatMessage.tsx",
    argumentsPreview: "frontend/src/components/chat/ChatMessage.tsx",
    commandLine: "read_file ChatMessage.tsx frontend/src/components/chat/ChatMessage.tsx",
    output: "读取完成。",
    sourceItemId: "",
    sourceEventType: "tool_item_completed",
    sourceEventId: "event:tool:done",
    firstOffset: 9,
    lastOffset: 9,
  };
}

function activityArchiveBlock(blocks: ActivityArchiveBlock["blocks"] = [toolBlock()]): ActivityArchiveBlock {
  return {
    kind: "activity_archive",
    id: "activity-archive:test",
    title: "",
    detail: "2 条",
    state: "done",
    blocks,
    offset: 9,
  };
}

function todoPlanBlock(): Extract<ProjectionBlock, { kind: "todo_plan" }> {
  return {
    kind: "todo_plan",
    id: "todo-plan:taskrun:test",
    title: "任务清单",
    detail: "1/2 已完成，正在：正在补前端清单渲染。",
    state: "done",
    statusKind: "todo_plan",
    planId: "agent-todo:session:test:taskrun:test",
    activeItemId: "todo:2",
    completionReady: false,
    items: [
      {
        todo_id: "todo:1",
        content: "补后端结构化投影",
        status: "completed",
      },
      {
        todo_id: "todo:2",
        content: "补前端清单渲染",
        active_form: "正在补前端清单渲染",
        status: "in_progress",
      },
    ],
    offset: 8,
    sourceEventType: "tool_item_completed",
    sourceEventId: "event:todo",
  };
}

function renderChatMessage(options: {
  streamingContent: boolean;
  content?: string;
  projectionView?: ChronologicalProjectionView;
}) {
  return renderToStaticMarkup(
    React.createElement(ChatMessage, {
      id: "message:assistant:1",
      role: "assistant",
      content: options.content ?? "持久化正文。",
      projectionView: options.projectionView ?? projectionView(),
      streamingContent: options.streamingContent,
      toolCalls: [],
      retrievals: [],
    }),
  );
}

describe("ChatMessage", () => {
  it("renders completed projection messages with prior activity folded before the closeout body", () => {
    const progressBody = bodyBlock("收口前的过程正文。", 8);
    const html = renderChatMessage({
      streamingContent: false,
      projectionView: projectionView({
        blocks: [
          activityArchiveBlock([progressBody, toolBlock()]),
        ],
      }),
    });

    expect(html).toContain("已经完成的正文。");
    expect(html).toContain("收口前的过程正文。");
    expect(html).toContain("aria-label=\"收口前轨迹\"");
    expect(html).toContain("public-run-activity__archive");
    expect(html).toContain("记录");
    expect(html).toContain("public-run-activity__body-note");
    expect(html).not.toContain("本轮记录");
    expect(html).toContain("读取文件");
    expect(html).toContain("ChatMessage.tsx");
    expect(html).toContain("public-run-activity__tool-window");
    expect(html.indexOf("public-run-activity__archive")).toBeLessThan(html.indexOf("已经完成的正文。"));
    expect(html.indexOf("收口前的过程正文。")).toBeLessThan(html.indexOf("已经完成的正文。"));
  });

  it("renders projection timeline only for the active streaming task message", () => {
    const html = renderChatMessage({
      streamingContent: true,
      projectionView: projectionView({
        displayMode: "live",
        bodyState: "streaming",
      }),
    });

    expect(html).toContain("已经完成的正文。");
    expect(html).toContain("运行状态");
    expect(html).toContain("读取文件");
    expect(html).toContain("ChatMessage.tsx");
    expect(html).toContain("public-run-activity");
  });

  it("restores a live projection timeline after refresh even when the local stream flag is gone", () => {
    const html = renderChatMessage({
      streamingContent: false,
      projectionView: projectionView({
        displayMode: "live",
        bodyState: "streaming",
      }),
    });

    expect(html).toContain("已经完成的正文。");
    expect(html).toContain("运行状态");
    expect(html).toContain("读取文件");
    expect(html).toContain("ChatMessage.tsx");
    expect(html).toContain("public-run-activity");
  });

  it("renders live tool projection from trace items", () => {
    const html = renderChatMessage({
      streamingContent: true,
      projectionView: projectionView({
        displayMode: "live",
        blocks: [toolBlock()],
        canonicalContent: "",
        copyText: "",
        bodyState: "streaming",
      }),
    });

    expect(html).toContain("运行状态");
    expect(html).toContain("读取文件");
    expect(html).toContain("ChatMessage.tsx");
    expect(html).toContain("public-run-activity");
  });

  it("renders non-shell tool details without the generic shell placeholder", () => {
    const html = renderChatMessage({
      streamingContent: true,
      projectionView: projectionView({
        displayMode: "live",
        blocks: [{
          ...toolBlock(),
          id: "tool:parser-adapter",
          title: "读取文件完成：backend/capability_system/capabilities/retrieval/parser_adapter.py",
          detail: "读取文件完成：backend/capability_system/capabilities/retrieval/parser_adapter.py",
          target: "backend/capability_system/capabilities/retrieval/parser_adapter.py",
          toolName: "",
          actionKind: "",
          commandLine: "tool",
          output: "读取文件完成：backend/capability_system/capabilities/retrieval/parser_adapter.py",
        }],
        canonicalContent: "",
        copyText: "",
        bodyState: "streaming",
      }),
    });

    expect(html).toContain("data-tool-family=\"file\"");
    expect(html).toContain("backend/capability_system/capabilities/retrieval/parser_adapter.py");
    expect(html).not.toContain("读取请求");
    expect(html).not.toContain("$ tool");
  });

  it("renders live todo plan projection as a task checklist", () => {
    const html = renderChatMessage({
      streamingContent: false,
      projectionView: projectionView({
        displayMode: "live",
        blocks: [todoPlanBlock()],
        canonicalContent: "",
        copyText: "",
        bodyState: "streaming",
        toolEventCount: 0,
        traceAvailable: true,
      }),
    });

    expect(html).toContain("运行状态");
    expect(html).toContain("任务清单");
    expect(html).toContain("补后端结构化投影");
    expect(html).toContain("正在补前端清单渲染");
    expect(html).toContain("public-run-activity__todo-block");
    expect(html).not.toContain("tool-window");
  });

  it("renders recovery projection blocks as visible status activity", () => {
    const html = renderChatMessage({
      streamingContent: false,
      projectionView: projectionView({
        displayMode: "recovery",
        blocks: [{
          kind: "recovery_event",
          id: "recovery:commit-failed",
          title: "输出未写入会话记录",
          detail: "最终回复未能写入会话记录。",
          state: "failed",
          offset: 18,
          sourceEventType: "session_output_commit_failed",
          sourceEventId: "event:commit-failed",
          logRef: "taskrun:test",
        }],
        canonicalContent: "",
        copyText: "",
        bodyState: "finalized",
        toolEventCount: 0,
        traceAvailable: true,
      }),
    });

    expect(html).toContain("运行状态");
    expect(html).toContain("输出未写入会话记录");
    expect(html).toContain("最终回复未能写入会话记录。");
    expect(html).toContain("异常");
    expect(html).toContain("aria-label=\"运行状态\"");
    expect(html).toContain("public-run-activity__line--status");
  });

  it("does not render a status-only recovery projection as assistant prose", () => {
    const html = renderChatMessage({
      streamingContent: false,
      content: "",
      projectionView: projectionView({
        displayMode: "recovery",
        blocks: [{
          kind: "recovery_event",
          id: "recovery:only",
          title: "状态异常",
          detail: "运行未完成",
          state: "failed",
          offset: 18,
          sourceEventType: "turn_completed",
          sourceEventId: "event:terminal",
        }],
        canonicalContent: "",
        copyText: "",
        bodyState: "finalized",
        toolEventCount: 0,
        traceAvailable: true,
      }),
    });

    expect(html).toBe("");
  });

  it("shows the thinking placeholder only from the active live stream", () => {
    const html = renderChatMessage({
      streamingContent: true,
      content: "",
      projectionView: projectionView({
        displayMode: "live",
        canonicalContent: "",
        copyText: "",
        bodyState: "streaming",
        blocks: [],
        toolEventCount: 0,
        traceAvailable: false,
      }),
    });

    expect(html).toContain("正在思考");
    expect(html).toContain("chat-message-shell__thinking-placeholder");
  });

});
