import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SessionActivityBar } from "./SessionActivityBar";

describe("SessionActivityBar", () => {
  it("does not expose terminal chat error detail in the global status line", () => {
    const html = renderToStaticMarkup(
      React.createElement(SessionActivityBar, {
        active: false,
        activity: {
          level: "error",
          title: "处理失败",
          detail: "当前环境的写入权限不足，且创建文件的工具不可见。",
          event: "error",
          receipt: {
            level: "error",
            title: "处理失败",
            body: "当前环境的写入权限不足，且创建文件的工具不可见。",
            debug: { event: "error" },
          },
          updatedAt: 1,
        },
      }),
    );

    expect(html).toContain("处理未完成");
    expect(html).toContain("详情已写入会话。");
    expect(html).not.toContain("处理失败");
    expect(html).not.toContain("当前环境的写入权限不足");
  });

  it("keeps infrastructure error detail visible in the global status line", () => {
    const html = renderToStaticMarkup(
      React.createElement(SessionActivityBar, {
        active: false,
        activity: {
          level: "error",
          title: "会话连接失败",
          detail: "无法创建会话，请确认后端服务仍在 127.0.0.1:8003。",
          event: "session_create_failed",
          updatedAt: 1,
        },
      }),
    );

    expect(html).toContain("会话连接中断");
    expect(html).toContain("无法创建会话");
    expect(html).not.toContain("会话连接失败");
  });

  it("uses a static running indicator instead of a spinner", () => {
    const html = renderToStaticMarkup(
      React.createElement(SessionActivityBar, {
        active: true,
        activity: {
          level: "running",
          title: "正在处理",
          detail: "正在同步当前处理进展。",
          event: "runtime_live_monitor",
          updatedAt: 1,
        },
      }),
    );

    expect(html).toContain("正在处理");
    expect(html).not.toContain("session-activity-bar__spin");
    expect(html).not.toContain("animate-spin");
  });
});
