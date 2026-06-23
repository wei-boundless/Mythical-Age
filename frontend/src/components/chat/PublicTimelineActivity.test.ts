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
    expect(html).toContain("参数预览");
    expect(html).not.toContain("读取请求");
    expect(html).not.toContain("返回结果");
    expect(html).not.toContain("系统返回");
  });

  it("does not render target-only detail as a separate detail row", () => {
    const target = "_structured_bundle_capabilities";
    const html = renderActivity([
      {
        kind: "tool_event",
        id: "tool:search-duplicate-detail",
        title: `搜索文件 ${target}`,
        detail: target,
        state: "done",
        toolCallId: "call:search-duplicate-detail",
        toolLifecycleId: "toolinv:search-duplicate-detail",
        toolName: "search_files",
        actionKind: "",
        target,
        argumentsPreview: `query=${target}, context=10, output_mode=content`,
        commandLine: "",
        output: "搜索完成。",
        sourceItemId: "",
        sourceEventType: "tool_item_completed",
        sourceEventId: "event:tool:search-duplicate-detail",
        firstOffset: 1,
        lastOffset: 2,
      },
    ]);

    expect(html).toContain("<dt>目标</dt>");
    expect(html).toContain("<dt>参数预览</dt>");
    expect(html).not.toContain("<dt>详情</dt>");
  });

  it("does not render public status placeholders as tool output", () => {
    const detail = "[1] backend/harness/agent_control/controller.py [2] backend/harness/runtime/control_events.py";
    const html = renderActivity([
      {
        kind: "tool_event",
        id: "tool:search",
        title: "搜索文件 control",
        detail,
        state: "done",
        toolCallId: "call:search",
        toolLifecycleId: "toolinv:search",
        toolName: "search_files",
        actionKind: "",
        target: "control",
        argumentsPreview: "query=control",
        commandLine: "search_files control query=control",
        output: "状态已更新",
        sourceItemId: "",
        sourceEventType: "tool_item_completed",
        sourceEventId: "event:tool:search",
        firstOffset: 1,
        lastOffset: 2,
      },
    ]);

    expect(html).toContain("data-tool-family=\"search\"");
    expect(html).toContain("backend/harness/agent_control/controller.py");
    expect(html).toContain("返回结果");
    expect(html).not.toContain("<dt>详情</dt>");
    expect(html).not.toContain("状态已更新");
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
