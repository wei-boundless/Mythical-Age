import { describe, expect, it } from "vitest";

import { toUiMessages } from "./utils";

describe("toUiMessages", () => {
  it("maps only real persisted history messages into chat messages", () => {
    const messages = toUiMessages([
      { role: "user", content: "开始任务", turn_id: "turn:session:1" },
      {
        id: "assistant:1",
        role: "assistant",
        content: "我会先检查投影链路。",
        turn_id: "turn:session:1",
        answer_channel: "conversation",
        answer_canonical_state: "stable_answer",
        answer_persist_policy: "persist_canonical",
      },
    ]);

    expect(messages).toEqual([
      expect.objectContaining({
        id: "history-message:turn:session:1:user",
        role: "user",
        content: "开始任务",
        sourceTurnId: "turn:session:1",
      }),
      expect.objectContaining({
        id: "assistant:1",
        role: "assistant",
        content: "我会先检查投影链路。",
        sourceTurnId: "turn:session:1",
        answerCanonicalState: "stable_answer",
        answerPersistPolicy: "persist_canonical",
      }),
    ]);
    expect(JSON.stringify(messages)).not.toContain("runtimeAttachments");
    expect(JSON.stringify(messages)).not.toContain("runtimePublicTimelineDraft");
  });

  it("does not synthesize assistant placeholders for missing runtime output", () => {
    const messages = toUiMessages([
      { role: "user", content: "继续旧任务", turn_id: "turn:session:3" },
    ]);

    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({
      role: "user",
      content: "继续旧任务",
      sourceTurnId: "turn:session:3",
    });
  });

  it("keeps canonical assistant prose that explains control terms", () => {
    const messages = toUiMessages([
      { role: "user", content: "审查控制系统", turn_id: "turn:session:3" },
      {
        role: "assistant",
        content: "收口结论：active_work_control、ask_user 和 continue_active_work 是控制周期的一部分，需要按信号边界解释。",
        turn_id: "turn:session:3",
        answer_channel: "conversation",
        answer_canonical_state: "stable_answer",
        answer_persist_policy: "persist_canonical",
      },
    ]);

    expect(messages).toHaveLength(2);
    expect(messages[1]).toMatchObject({
      id: "history-message:turn:session:3:assistant",
      role: "assistant",
      content: "收口结论：active_work_control、ask_user 和 continue_active_work 是控制周期的一部分，需要按信号边界解释。",
      answerCanonicalState: "stable_answer",
      answerPersistPolicy: "persist_canonical",
    });
  });

  it("preserves assistant answer channels and does not merge task receipts with answers", () => {
    const messages = toUiMessages([
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
    ]);

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

  it("does not merge steer assistant feedback into the previous assistant answer during history hydration", () => {
    const messages = toUiMessages([
      { role: "user", content: "开始一个长任务", turn_id: "turn:session:1" },
      {
        id: "assistant:turn:1",
        role: "assistant",
        content: "我会先启动长任务。",
        turn_id: "turn:session:1",
        answer_channel: "conversation",
      },
      {
        id: "assistant:turn:2",
        role: "assistant",
        content: "已收到补充要求，我会把它纳入当前任务。",
        turn_id: "turn:session:2",
        task_run_id: "taskrun:turn:session:1:abc",
        answer_channel: "conversation",
      },
    ]);

    expect(messages).toHaveLength(3);
    expect(messages[1]).toMatchObject({
      id: "assistant:turn:1",
      role: "assistant",
      content: "我会先启动长任务。",
      sourceTurnId: "turn:session:1",
    });
    expect(messages[2]).toMatchObject({
      id: "assistant:turn:2",
      role: "assistant",
      content: "已收到补充要求，我会把它纳入当前任务。",
      sourceTurnId: "turn:session:2",
      sourceTaskRunId: "taskrun:turn:session:1:abc",
    });
  });

  it("filters structured tool-call records out of the visible transcript", () => {
    const messages = toUiMessages([
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
    ] as any);

    expect(messages.map((message) => message.content)).toEqual([
      "修复 bug",
      "我看到文件里已经有一部分 timer 递减代码了。",
    ]);
    expect(JSON.stringify(messages)).not.toContain("Edit failed");
  });
});
