import { describe, expect, it } from "vitest";

import { toUiMessages } from "./utils";
import type { SessionRuntimeAttachment } from "@/lib/api";

describe("toUiMessages runtime attachments", () => {
  it("attaches a runtime timeline to the next assistant message after the anchor turn", () => {
    const attachment: SessionRuntimeAttachment = {
      attachment_id: "runtime-attachment:taskrun:turn:session-a:3:abc",
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
      task_run_id: "taskrun:turn:session-a:8:root:checkout:abc",
      anchor_turn_id: "turn:session-a:3",
      status: "completed",
    });
  });
});
