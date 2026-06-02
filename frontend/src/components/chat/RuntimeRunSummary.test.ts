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
    expect(html).not.toContain("{&quot;ok&quot;:true}");
  });

  it("does not render internal runtime event rows as chat progress", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [],
        attachments: [
          {
            attachment_id: "runtime-attachment:taskrun:turn:session-internal:1",
            run_id: "taskrun:turn:session-internal:1",
            anchor_turn_id: "turn:session-internal:1",
            status: "running",
            progress_presentation: {
              mission: {
                phase: "整理上下文",
                state: "running",
                current_action: "我正在分析当前任务。"
              },
              work_units: [],
              technical_trace: [
                {
                  event_id: "rtevt:step",
                  event_type: "step_summary_recorded",
                  raw_preview: "已进入任务生命周期，正在准备执行。",
                },
                {
                  event_id: "rtevt:packet",
                  event_type: "runtime_invocation_packet_compiled",
                  raw_preview: "{\"envelope\":{\"agent_profile_ref\":\"main_interactive_agent\"}}",
                },
                {
                  event_id: "rtevt:heartbeat",
                  event_type: "task_model_action_wait_heartbeat",
                  raw_preview: "{\"status\":\"running\"}",
                },
              ],
            },
          },
        ],
      }),
    );

    expect(html).toContain("我正在分析当前任务");
    expect(html).not.toContain("step_summary_recorded");
    expect(html).not.toContain("runtime_invocation_packet_compiled");
    expect(html).not.toContain("task_model_action_wait_heartbeat");
    expect(html).not.toContain("agent_profile_ref");
    expect(html).not.toContain("已进入任务生命周期");
    expect(html).not.toContain("查看技术细节");
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
    expect(html).not.toContain("查看技术细节");
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

    expect(html).toContain("我卡在这里");
    expect(html).toContain("图像生成这一步卡住了，因为生图服务还没有可用配置。");
    expect(html).toContain("查看执行细节");
    expect(html).not.toContain("Image generation is not configured");
    expect(html).not.toContain("Running");
  });

  it("lets a failed terminal reason override completed-looking progress rows", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [],
        attachments: [
          {
            attachment_id: "runtime-attachment:turnrun:limit",
            run_id: "turnrun:limit",
            anchor_turn_id: "turn:session-limit:2",
            status: "completed",
            terminal_reason: "single_turn_tool_iteration_limit",
            progress_presentation: {
              mission: {
                phase: "推进中",
                state: "completed",
                current_action: "回答已生成并写回会话",
              },
              work_units: [
                {
                  unit_id: "done-row",
                  title: "done",
                  state: "completed",
                  judgment: "回答已生成并写回会话",
                },
              ],
              technical_trace: [],
            },
          },
        ],
      }),
    );

    expect(html).toContain("runtime-run-summary--error");
    expect(html).toContain("我卡在这里");
    expect(html).not.toContain("我已经处理完");
  });

  it("keeps provider errors conversational and pushes raw filenames out of the main feedback", () => {
    const html = renderToStaticMarkup(
      React.createElement(RuntimeRunSummary, {
        entries: [],
        attachments: [
          {
            attachment_id: "runtime-attachment:image",
            run_id: "taskrun:image",
            anchor_turn_id: "turn:image:1",
            status: "failed",
            terminal_reason: "task_executor_schedule_failed",
            progress_presentation: {
              mission: {
                phase: "处理已停止",
                state: "failed",
                current_action:
                  "图像生成服务不可用（Image generation is not configured），无法生成合同要求的像素风场景图Boss图（target id: five-floor-dungeon-pixel-tower-five_floor_dungeon_e2e_20260602_133927_e98c34）。",
                progress_label: "1/4 步",
              },
              work_units: [],
              technical_trace: [],
            },
          },
        ],
      }),
    );

    expect(html).toContain("我卡在这里");
    expect(html).toContain("图像生成这一步卡住了，因为生图服务还没有可用配置。");
    expect(html).not.toContain("1/4 步");
    expect(html).not.toContain("处理已停止");
    expect(html).not.toContain("错误代码");
    expect(html).not.toContain("Image generation is not configured");
    expect(html).not.toContain("five-floor-dungeon");
  });
});
