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

  it("creates a runtime placeholder instead of attaching to a later assistant after the anchor turn", () => {
    const attachment: SessionRuntimeAttachment = {
      attachment_id: "runtime-attachment:taskrun:turn:session-a:3:abc",
      run_id: "taskrun:turn:session-a:8:root:checkout:abc",
      anchor_turn_id: "turn:session-a:3",
      task_run_id: "taskrun:turn:session-a:8:root:checkout:abc",
      status: "completed",
      lifecycle: "completed",
      public_timeline: [
        {
          item_id: "task:done",
          kind: "status_update",
          slot: "timeline",
          surface: "timeline",
          title: "处理已完成",
          text: "已完成收口并记录交付证据。",
          state: "done",
        },
      ],
    };

    const messages = toUiMessages(
      [
        { role: "user", content: "开始旧任务", turn_id: "turn:session-a:1" },
        { role: "assistant", content: "任务已接管", turn_id: "turn:session-a:1" },
        { role: "user", content: "继续旧任务", turn_id: "turn:session-a:3" },
        { role: "assistant", content: "收到，继续执行。", turn_id: "turn:session-a:8" },
        { role: "assistant", content: "任务完成。", turn_id: "turn:session-a:9" },
      ],
      [attachment],
    );

    expect(messages.find((message) => message.content === "任务已接管")?.runtimeAttachments ?? []).toEqual([]);
    expect(messages.find((message) => message.content === "收到，继续执行。")?.runtimeAttachments ?? []).toEqual([]);
    expect(messages.find((message) => message.content === "任务完成。")?.runtimeAttachments ?? []).toEqual([]);
    const placeholder = messages.find((message) => message.id === "history-message:turn:session-a:3:assistant");
    expect(placeholder).toMatchObject({
      role: "assistant",
      content: "",
      sourceIndex: 2.5,
      sourceTurnId: "turn:session-a:3",
    });
    expect(placeholder?.runtimeAttachments?.[0]).toMatchObject({
      run_id: "taskrun:turn:session-a:8:root:checkout:abc",
      task_run_id: "taskrun:turn:session-a:8:root:checkout:abc",
      anchor_turn_id: "turn:session-a:3",
      status: "completed",
    });
  });

  it("does not create a runtime placeholder from legacy progress entries alone", () => {
    const attachment = {
      attachment_id: "runtime-attachment:taskrun:legacy-progress",
      run_id: "taskrun:legacy-progress",
      anchor_turn_id: "turn:session-a:3",
      task_run_id: "taskrun:legacy-progress",
      status: "completed",
      progress_entries: [
        {
          id: "legacy:step",
          title: "旧 progress entry",
          body: "这不应成为可见投影。",
          kind: "terminal",
        },
      ],
    } as unknown as SessionRuntimeAttachment;

    const messages = toUiMessages(
      [
        { role: "user", content: "继续旧任务", turn_id: "turn:session-a:3" },
      ],
      [attachment],
    );

    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ role: "user", content: "继续旧任务" });
  });

  it("does not create a runtime placeholder from assistant-body public timeline alone", () => {
    const attachment: SessionRuntimeAttachment = {
      attachment_id: "runtime-attachment:turnrun:body-only",
      run_id: "turnrun:body-only",
      anchor_turn_id: "turn:session-a:3",
      anchor_role: "assistant",
      status: "running",
      public_timeline: [
        {
          item_id: "body:progress",
          kind: "assistant_text",
          slot: "body",
          surface: "assistant_body",
          source_authority: "model",
          text: "这段运行投影不应生成正文占位。",
          state: "running",
        },
      ],
    };

    const messages = toUiMessages(
      [
        { role: "user", content: "继续旧任务", turn_id: "turn:session-a:3" },
      ],
      [attachment],
    );

    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ role: "user", content: "继续旧任务" });
  });

  it("does not let task_run_id override the explicit turn/message anchor", () => {
    const taskRunId = "taskrun:turn:session-a:1:abc";
    const attachment: SessionRuntimeAttachment = {
      attachment_id: `runtime-attachment:${taskRunId}`,
      run_id: taskRunId,
      anchor_turn_id: "turn:session-a:1",
      anchor_message_id: "assistant-opening",
      anchor_role: "assistant",
      task_run_id: taskRunId,
      status: "completed",
      public_timeline: [
        {
          item_id: "tool:1",
          kind: "tool_activity",
          state: "done",
        },
      ],
    };

    const messages = toUiMessages(
      [
        { role: "user", content: "request", turn_id: "turn:session-a:1" },
        { id: "assistant-opening", role: "assistant", content: "opening", turn_id: "turn:session-a:1" },
        { id: "assistant-final", role: "assistant", content: "final", task_run_id: taskRunId, completion_state: "completed" },
      ],
      [attachment],
    );

    const opening = messages.find((message) => message.id === "assistant-opening");
    const final = messages.find((message) => message.id === "assistant-final");

    expect(opening?.runtimeAttachments?.[0]).toMatchObject({
      attachment_id: `runtime-attachment:${taskRunId}`,
      task_run_id: taskRunId,
      anchor_turn_id: "turn:session-a:1",
      status: "completed",
    });
    expect(final?.sourceTaskRunId).toBe(taskRunId);
    expect(final?.runtimeAttachments ?? []).toEqual([]);
  });

  it("creates a runtime assistant placeholder when the anchored assistant message is not persisted yet", () => {
    const attachment: SessionRuntimeAttachment = {
      attachment_id: "runtime-attachment:turnrun:turn:session-a:3",
      run_id: "turnrun:turn:session-a:3",
      anchor_turn_id: "turn:session-a:3",
      anchor_message_id: "history-message:turn:session-a:3:assistant",
      anchor_role: "assistant",
      status: "running",
      public_timeline: [
        {
          item_id: "work:read",
          kind: "work_action",
          action_kind: "read",
          title: "正在读取文件",
          subject_label: "adventure-island-standalone/index.html",
          public_summary: "正在读取 adventure-island-standalone/index.html",
          state: "running",
        },
      ],
    };

    const messages = toUiMessages(
      [
        { role: "user", content: "先审查", turn_id: "turn:session-a:1" },
        { role: "assistant", content: "我先读一部分。", turn_id: "turn:session-a:1" },
        { role: "user", content: "继续修复", turn_id: "turn:session-a:3" },
      ],
      [attachment],
    );

    expect(messages.map((message) => [message.role, message.content])).toEqual([
      ["user", "先审查"],
      ["assistant", "我先读一部分。"],
      ["user", "继续修复"],
      ["assistant", ""],
    ]);
    expect(messages[1].runtimeAttachments ?? []).toEqual([]);
    expect(messages[3]).toMatchObject({
      id: "history-message:turn:session-a:3:assistant",
      role: "assistant",
      sourceIndex: 2.5,
    });
    expect(messages[3].runtimeAttachments?.[0]).toMatchObject({
      run_id: "turnrun:turn:session-a:3",
      anchor_turn_id: "turn:session-a:3",
    });
  });

  it("keeps canonical assistant prose that explains active work control terms", () => {
    const messages = toUiMessages(
      [
        { role: "user", content: "审查控制系统", turn_id: "turn:session-a:3" },
        {
          role: "assistant",
          content: "收口结论：active_work_control、ask_user 和 continue_active_work 是控制周期的一部分，需要按信号边界解释。",
          turn_id: "turn:session-a:3",
          answer_channel: "conversation",
          answer_canonical_state: "stable_answer",
          answer_persist_policy: "persist_canonical",
        },
      ],
      [
        {
          attachment_id: "runtime-attachment:turnrun:turn:session-a:3",
          run_id: "turnrun:turn:session-a:3",
          anchor_turn_id: "turn:session-a:3",
          anchor_message_id: "history-message:turn:session-a:3:assistant",
          anchor_role: "assistant",
          status: "completed",
          public_timeline: [
            {
              item_id: "tool:read",
              kind: "work_action",
              slot: "tool",
              surface: "tool_window",
              source_authority: "tool",
              title: "读取完成 backend/harness/loop/single_agent_turn.py",
              subject_label: "backend/harness/loop/single_agent_turn.py",
              state: "done",
            },
          ],
        },
      ],
    );

    expect(messages).toHaveLength(2);
    expect(messages[1]).toMatchObject({
      id: "history-message:turn:session-a:3:assistant",
      role: "assistant",
      content: "收口结论：active_work_control、ask_user 和 continue_active_work 是控制周期的一部分，需要按信号边界解释。",
      answerCanonicalState: "stable_answer",
      answerPersistPolicy: "persist_canonical",
    });
    expect(messages[1].runtimeAttachments?.[0]).toMatchObject({
      attachment_id: "runtime-attachment:turnrun:turn:session-a:3",
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
          answer_canonical_state: "progress_only",
          answer_persist_policy: "persist_debug_only",
          answer_selected_channel: "progress_text",
          answer_leak_flags: ["internal_protocol_final_text"],
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
      answerCanonicalState: "progress_only",
      answerPersistPolicy: "persist_debug_only",
      answerSelectedChannel: "progress_text",
      answerLeakFlags: ["internal_protocol_final_text"],
      content: "任务已卡住，因为生图工具未配置。",
    });
  });

  it("filters structured tool-call records out of the visible chat transcript", () => {
    const messages = toUiMessages(
      [
        { role: "user", content: "修复 bug" },
        {
          role: "tool",
          content: "Edit failed: old_text not found",
          name: "edit_file",
          tool_call_id: "call_1",
        },
        {
          role: "assistant",
          content: "",
          tool_calls: [{ id: "call_2", name: "read_file", args: {}, type: "tool_call" }],
        },
        { role: "assistant", content: "我看到文件里已经有一部分 timer 递减代码了。" },
      ] as any,
      [],
    );

    expect(messages.map((message) => message.content)).toEqual([
      "修复 bug",
      "我看到文件里已经有一部分 timer 递减代码了。",
    ]);
    expect(JSON.stringify(messages)).not.toContain("Edit failed");
  });
});
