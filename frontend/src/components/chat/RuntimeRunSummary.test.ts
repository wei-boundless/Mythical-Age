import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RuntimeRunSummary } from "./RuntimeRunSummary";

describe("RuntimeRunSummary", () => {
  it("renders backend progress presentation as a mission and one work unit", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [],
        attachments: [
          {
            attachment_id: "runtime-attachment:taskrun:turn:session-progress:1:abc",
            run_id: "taskrun:turn:session-progress:1:abc",
            anchor_turn_id: "turn:session-progress:1",
            task_run_id: "taskrun:turn:session-progress:1:abc",
            status: "running",
            progress_presentation: {
              mission: {
                goal: "创建 calculator.html 并验证路径可用",
                phase: "确认 artifact 路径",
                state: "running",
                current_action: "检查 calculator.html 是否已存在。",
                next_action: "创建 calculator.html。",
                progress_label: "0/1 确认 artifact 路径",
              },
              work_units: [
                {
                  unit_id: "workunit:path-check",
                  kind: "inspect_path",
                  title: "确认 artifact 路径",
                  state: "completed",
                  judgment: "需要先确认 artifact 路径状态。",
                  action: "检查 storage/task_environments/general/workspace/calculator.html 是否已存在。",
                  evidence: [
                    {
                      label: "path_exists",
                      summary: "目标文件尚未存在，路径检查成功；下一步需要创建。",
                      status: "negative_evidence",
                    },
                  ],
                  next_action: "创建 calculator.html。",
                  technical_trace_refs: ["rtevt:obs"],
                },
              ],
              technical_trace: [
                {
                  event_id: "rtevt:obs",
                  event_type: "task_tool_observation_recorded",
                  tool_name: "path_exists",
                  target: "storage/task_environments/general/workspace/calculator.html",
                  raw_preview: "false",
                },
              ],
            },
          },
        ],
      }),
    );

    expect(html).toContain("确认 artifact 路径");
    expect(html).toContain("需要先确认 artifact 路径状态");
    expect(html).toContain("目标文件尚未存在，路径检查成功");
    expect(html).toContain("我正在处理");
    expect(html).toContain("查看执行细节");
    expect(html).not.toContain("Tool Call");
    expect(html).not.toContain("Observation");
    expect(html).not.toContain("Agent 判断");
  });

  it("keeps technical trace available but collapsed by default", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [],
        attachments: [
          {
            attachment_id: "runtime-attachment:taskrun:turn:session-progress:1:abc",
            run_id: "taskrun:turn:session-progress:1:abc",
            anchor_turn_id: "turn:session-progress:1",
            status: "running",
            progress_presentation: {
              mission: {
                phase: "写入文件",
                state: "running",
                current_action: "写入 calculator.html。",
              },
              work_units: [],
              technical_trace: [
                {
                  event_id: "rtevt:write",
                  event_type: "task_tool_observation_recorded",
                  tool_name: "write_file",
                  raw_preview: "{\"ok\":true}",
                },
              ],
            },
          },
        ],
      }),
    );

    expect(html).toContain("查看技术细节");
    expect(html).toContain("write_file");
    expect(html).toContain("<details class=\"runtime-technical-trace\">");
    expect(html).not.toContain("<details open");
  });

  it("shows a closeout summary when the backend marks the run completed", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [],
        attachments: [
          {
            attachment_id: "runtime-attachment:taskrun:turn:session-closeout:1:abc",
            run_id: "taskrun:turn:session-closeout:1:abc",
            anchor_turn_id: "turn:session-closeout:1",
            status: "completed",
            progress_presentation: {
              mission: {
                goal: "完成五层地下塔长任务验收",
                phase: "结果收口",
                state: "completed",
                current_action: "已完成五层地下塔的核心结构、关键交互和验收记录。",
                progress_label: "1/1 结果收口",
                closeout_summary: "已完成五层地下塔的核心结构、关键交互和验收记录。",
              },
              work_units: [
                {
                  unit_id: "workunit:closeout",
                  kind: "terminal",
                  title: "结果收口",
                  state: "completed",
                  judgment: "已完成五层地下塔的核心结构、关键交互和验收记录。",
                },
              ],
              technical_trace: [],
            },
          },
        ],
      }),
    );

    expect(html).toContain("结果收口");
    expect(html).toContain("已完成五层地下塔的核心结构、关键交互和验收记录");
    expect(html).toContain("runtime-run-summary--success");
  });

  it("falls back to a minimal status summary without restoring split event cards", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [
          {
            id: "model",
            kind: "model",
            level: "running",
            title: "Agent 判断",
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
    expect(html).toContain("查看技术细节");
    expect(html).not.toContain("Tool Call");
    expect(html).not.toContain("Observation");
    expect(html).not.toContain("Agent 判断");
  });

  it("renders tool failure as an assistant-style progress sentence", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [
          {
            id: "image-generate-failed",
            kind: "observation",
            level: "error",
            title: "观察结果",
            body: "工具返回失败：Image generation is not configured",
            publicNote: "工具返回失败：Image generation is not configured",
            eventType: "step_summary_recorded",
            statusText: "failed",
            toolName: "image_generate",
          },
        ],
      }),
    );

    expect(html).toContain("我这一步卡住了");
    expect(html).toContain("Image generation is not configured");
    expect(html).toContain("查看执行细节");
    expect(html).not.toContain("Running");
  });
});
