import { describe, expect, it } from "vitest";

import { toUiMessages } from "./utils";
import type { SessionRuntimeAttachment } from "@/lib/api";

describe("toUiMessages runtime attachments", () => {
  it("uses stable anchor_message_id instead of nearest assistant index when provided", () => {
    const attachment: SessionRuntimeAttachment = {
      attachment_id: "runtime-attachment:taskrun:turn:session-a:1:abc",
      run_id: "taskrun:turn:session-a:1:abc",
      anchor_turn_id: "turn:session-a:1",
      anchor_message_id: "history-message:1",
      anchor_role: "assistant",
      task_run_id: "taskrun:turn:session-a:1:abc",
      status: "completed",
      public_timeline: [
        {
          item_id: "tool:old",
          kind: "tool_activity",
          title: "旧任务活动",
          state: "done",
        },
      ],
    };

    const messages = toUiMessages(
      [
        { role: "user", content: "开始旧任务" },
        { role: "assistant", content: "任务已接管" },
        { role: "user", content: "继续" },
        { role: "assistant", content: "这是新的回复" },
      ],
      [attachment],
    );

    expect(messages.find((message) => message.content === "任务已接管")?.runtimeAttachments?.[0]).toMatchObject({
      anchor_message_id: "history-message:1",
      run_id: "taskrun:turn:session-a:1:abc",
    });
    expect(messages.find((message) => message.content === "这是新的回复")?.runtimeAttachments ?? []).toEqual([]);
  });

  it("attaches a runtime timeline to the next assistant message after the anchor turn", () => {
    const attachment: SessionRuntimeAttachment = {
      attachment_id: "runtime-attachment:taskrun:turn:session-a:3:abc",
      run_id: "taskrun:turn:session-a:8:root:checkout:abc",
      anchor_turn_id: "turn:session-a:3",
      task_run_id: "taskrun:turn:session-a:8:root:checkout:abc",
      status: "completed",
      lifecycle: "completed",
      latest_step_summary: "已完成收口并记录交付证据。",
      progress_entries: [
        {
          id: "step:done",
          eventType: "step_summary_recorded",
          title: "处理已完成",
          body: "已完成收口并记录交付证据。",
          kind: "terminal",
          level: "success",
        },
      ],
    };

    const messages = toUiMessages(
      [
        { role: "user", content: "开始旧任务" },
        { role: "assistant", content: "任务已接管" },
        { role: "user", content: "继续旧任务" },
        { role: "assistant", content: "收到，继续执行。" },
        { role: "assistant", content: "任务完成。" },
      ],
      [attachment],
    );

    expect(messages.find((message) => message.content === "任务已接管")?.runtimeAttachments ?? []).toEqual([]);
    expect(messages.find((message) => message.content === "收到，继续执行。")?.runtimeAttachments?.[0]).toMatchObject({
      run_id: "taskrun:turn:session-a:8:root:checkout:abc",
      task_run_id: "taskrun:turn:session-a:8:root:checkout:abc",
      anchor_turn_id: "turn:session-a:3",
      status: "completed",
    });
  });

  it("preserves assistant answer channel and does not merge task receipts with answers", () => {
    const messages = toUiMessages(
      [
        { role: "user", content: "开始任务" },
        {
          role: "assistant",
          content: "我会按这个目标推进：开始任务",
          answer_channel: "task_control",
          answer_source: "harness.task_lifecycle",
        },
        {
          role: "assistant",
          content: "任务已卡住，因为生图工具未配置。",
          answer_channel: "blocked",
          answer_source: "harness.single_agent_turn.tool_loop",
        },
      ],
      [],
    );

    expect(messages).toHaveLength(3);
    expect(messages[1]).toMatchObject({
      answerChannel: "task_control",
      answerSource: "harness.task_lifecycle",
      content: "我会按这个目标推进：开始任务",
    });
    expect(messages[2]).toMatchObject({
      answerChannel: "blocked",
      content: "任务已卡住，因为生图工具未配置。",
    });
  });
});
