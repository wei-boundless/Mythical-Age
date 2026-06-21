import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PublicTimelineActivity } from "./PublicTimelineActivity";
import type { ProjectionRenderBlock } from "@/lib/projection/chronological";

function renderActivity(blocks: ProjectionRenderBlock[]) {
  return renderToStaticMarkup(
    React.createElement(PublicTimelineActivity, { blocks }),
  );
}

describe("PublicTimelineActivity", () => {
  it("renders file tools with specialized UI family without duplicate request rows", () => {
    const html = renderActivity([
      {
        kind: "tool_event",
        id: "tool:read",
        title: "读取文件",
        detail: "读取 frontend/src/components/chat/ToolTrace.tsx",
        state: "done",
        toolCallId: "call:read",
        toolLifecycleId: "toolinv:read",
        toolName: "read_file",
        actionKind: "",
        target: "frontend/src/components/chat/ToolTrace.tsx",
        argumentsPreview: "line_count=120",
        commandLine: "read_file frontend/src/components/chat/ToolTrace.tsx line_count=120",
        output: "读取完成。",
        sourceItemId: "",
        sourceEventType: "tool_item_completed",
        sourceEventId: "event:tool:read",
        firstOffset: 1,
        lastOffset: 2,
      },
    ]);

    expect(html).toContain("data-tool-family=\"file\"");
    expect(html).toContain("目标");
    expect(html).toContain("参数");
    expect(html).not.toContain("读取请求");
    expect(html).not.toContain("返回结果");
    expect(html).not.toContain("系统返回");
  });

  it("renders runtime recovery reason codes as public status text", () => {
    const html = renderActivity([
      {
        kind: "terminal_event",
        id: "status:restart",
        title: "运行已结束",
        detail: "runtime_cell_missing_after_restart",
        state: "stopped",
        offset: 1,
      },
    ]);

    expect(html).toContain("连接恢复后需要重新接续运行");
    expect(html).not.toContain("runtime_cell_missing_after_restart");
  });

  it("renders terminal tools with the real command instead of the tool-name placeholder", () => {
    const command = "npm test -- src/components/chat/PublicTimelineActivity.test.ts";
    const html = renderActivity([
      {
        kind: "tool_event",
        id: "tool:terminal",
        title: `运行命令：${command}`,
        detail: "",
        state: "done",
        toolCallId: "call:terminal",
        toolLifecycleId: "toolinv:terminal",
        toolName: "terminal",
        actionKind: "",
        target: command,
        argumentsPreview: `cwd=D:/AI/langchain-agent, command=${command}`,
        commandLine: "terminal",
        output: "工具调用已完成。",
        sourceItemId: "",
        sourceEventType: "tool_item_completed",
        sourceEventId: "event:tool:terminal",
        firstOffset: 1,
        lastOffset: 2,
      },
    ]);

    expect(html).toContain("data-tool-family=\"command\"");
    expect(html).toContain("命令行");
    expect(html).toContain(`$ ${command}`);
    expect(html).not.toContain("$ terminal");
  });

  it("does not render a terminal tool-name placeholder as a command", () => {
    const html = renderActivity([
      {
        kind: "tool_event",
        id: "tool:terminal-placeholder",
        title: "运行命令",
        detail: "",
        state: "done",
        toolCallId: "call:terminal-placeholder",
        toolLifecycleId: "toolinv:terminal-placeholder",
        toolName: "terminal",
        actionKind: "",
        target: "",
        argumentsPreview: "",
        commandLine: "terminal",
        output: "工具调用已完成。",
        sourceItemId: "",
        sourceEventType: "tool_item_completed",
        sourceEventId: "event:tool:terminal-placeholder",
        firstOffset: 1,
        lastOffset: 2,
      },
    ]);

    expect(html).toContain("运行命令");
    expect(html).not.toContain("命令行");
    expect(html).not.toContain("$ terminal");
  });
});
