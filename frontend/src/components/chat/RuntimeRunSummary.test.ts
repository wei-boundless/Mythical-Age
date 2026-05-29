import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RuntimeRunSummary } from "./RuntimeRunSummary";

describe("RuntimeRunSummary", () => {
  it("uses model authored public progress notes before runtime fallback text", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [
          {
            id: "model-action",
            kind: "model",
            level: "running",
            title: "agent 正在处理",
            body: "系统已为当前任务步骤装配 runtime packet，并交给 agent 判断下一步。",
            publicNote: "我先核对当前文件状态，确认可以从断点继续。",
            agentBrief: "已定位到上次中断前的入口文件。",
            eventType: "step_summary_recorded",
            statusText: "running",
          },
        ],
      }),
    );

    expect(html).toContain("我先核对当前文件状态");
    expect(html).toContain("已定位到上次中断前的入口文件");
    expect(html).not.toContain("runtime packet");
    expect(html).not.toContain("装配");
  });

  it("labels completed work attachments as process progress without exposing internal task wording", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [],
        attachments: [
          {
            attachment_id: "runtime-attachment:taskrun:turn:session-e2e:1:abc",
            anchor_turn_id: "turn:session-e2e:1",
            task_run_id: "taskrun:turn:session-e2e:1:abc",
            status: "completed",
            progress_entries: [
              {
                id: "tool:1",
                kind: "tool",
                level: "running",
                title: "工具调用完成",
                body: "系统已执行 agent 请求的任务工具调用。",
              },
              {
                id: "terminal:1",
                kind: "terminal",
                level: "success",
                title: "任务已完成",
                body: "任务合同已满足。",
              },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("目标已满足");
    expect(html).toContain("2 步");
    expect(html).not.toContain("任务运行");
    expect(html).not.toContain("会话运行");
    expect(html).not.toContain("TaskRun");
  });

  it("presents runtime records as process progress with a short stage output", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [
          {
            id: "packet",
            kind: "stage",
            level: "running",
            title: "系统已为当前任务步骤装配 runtime packet，并交给 agent 判断下一步。",
            body: "系统已为当前任务步骤装配 runtime packet，并交给 agent 判断下一步。",
            eventType: "runtime_live_monitor",
            statusText: "running",
          },
          {
            id: "model",
            kind: "model",
            level: "running",
            title: "agent 正在处理",
            body: "模型调用仍在进行中，系统继续等待 agent 动作返回。等待轮次：1。",
            eventType: "step_summary_recorded",
            statusText: "running",
          },
        ],
      }),
    );

    expect(html).toContain("思考下一步");
    expect(html).toContain("正在生成下一步动作");
    expect(html).toContain("1/2 已完成");
    expect(html).not.toContain("系统已为当前任务步骤装配 runtime packet");
    expect(html).not.toContain("任务模型调用仍在进行中");
    expect(html).not.toContain("Agent 判断");
    expect(html).not.toContain("agent");
    expect(html).toContain("runtime-run-summary--inline");
    expect(html).not.toContain("<details");
  });

  it("marks completed phases explicitly while the newest phase remains running", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [],
        attachments: [
          {
            attachment_id: "runtime-attachment:taskrun:turn:session-live:1:abc",
            anchor_turn_id: "turn:session-live:1",
            task_run_id: "taskrun:turn:session-live:1:abc",
            status: "running",
            progress_entries: [
              {
                id: "step:packet",
                kind: "stage",
                level: "running",
                title: "装配任务运行时",
                body: "系统已为当前任务步骤装配 runtime packet，并交给 agent 判断下一步。",
                statusText: "running",
              },
              {
                id: "step:model",
                kind: "model",
                level: "running",
                title: "agent 正在处理",
                body: "模型调用仍在进行中，系统继续等待 agent 动作返回。等待轮次：1。",
                statusText: "running",
              },
            ],
          },
        ],
      }),
    );

    expect(html).toContain("runtime-run-summary--work");
    expect(html).toContain("思考下一步");
    expect(html).toContain("1/2 已完成");
    expect(html).not.toContain("runtime-run-summary--task");
  });

  it("marks historical steps completed when the run has reached a terminal success state", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [
          {
            id: "tool",
            kind: "tool",
            level: "running",
            title: "工具调用完成",
            body: "系统已执行 agent 请求的任务工具调用。",
            eventType: "step_summary_recorded",
            statusText: "running",
          },
          {
            id: "terminal",
            kind: "terminal",
            level: "success",
            title: "任务已完成",
            body: "任务合同已满足。",
            eventType: "task_run_lifecycle_finished",
            statusText: "completed",
          },
        ],
      }),
    );

    expect(html).toContain("目标已满足");
    expect(html).not.toContain(">进行中<");
    expect(html).toContain("已完成");
    expect(html).not.toContain("会话运行");
  });

  it("filters internal module names from historical progress entries", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [
          {
            id: "done",
            kind: "terminal",
            level: "success",
            title: "会话输出完成",
            body: "harness.loop.single_agent.respond",
            eventType: "done",
            statusText: "completed",
          },
        ],
      }),
    );

    expect(html).toContain("目标已满足");
    expect(html).not.toContain("harness");
    expect(html).not.toContain("single_agent");
    expect(html).not.toContain(".respond");
  });
});
