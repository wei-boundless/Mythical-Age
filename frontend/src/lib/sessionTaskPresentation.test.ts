import { describe, expect, it } from "vitest";

import type { SessionSummary, SessionTaskSummary } from "@/lib/api";
import {
  sessionSummaryCanInterrupt,
  sessionSummaryCanResume,
  sessionSummaryIsRunning,
  sessionTaskActivityKind,
  sessionTaskStatusLabel,
} from "./sessionTaskPresentation";

function task(patch: Partial<SessionTaskSummary>): SessionTaskSummary {
  return {
    available: true,
    task_run_count: 1,
    ...patch,
  };
}

function session(activeTask: SessionTaskSummary): SessionSummary {
  return {
    id: "session:main",
    title: "会话",
    created_at: 1,
    updated_at: 1,
    message_count: 2,
    active_task: activeTask,
  };
}

describe("sessionTaskPresentation", () => {
  it("uses backend activity fields instead of legacy bucket or stream state", () => {
    const waitingTask = task({
      activity_state: "waiting",
      activity_label: "等待继续",
      bucket: "running",
      is_running: false,
      is_waiting: true,
      status: "waiting_executor",
    });

    expect(sessionTaskActivityKind(waitingTask)).toBe("waiting");
    expect(sessionTaskStatusLabel(waitingTask)).toBe("等待继续");
    expect(sessionSummaryIsRunning(session(waitingTask))).toBe(false);
  });

  it("does not treat completed or stopped tasks as running because a stream exists elsewhere", () => {
    const completedTask = task({ activity_state: "completed", activity_label: "已完成", is_running: false });
    const stoppedTask = task({ activity_state: "stopped", activity_label: "已停止", is_running: false });

    expect(sessionSummaryIsRunning(session(completedTask))).toBe(false);
    expect(sessionTaskStatusLabel(stoppedTask)).toBe("已停止");
    expect(sessionSummaryIsRunning(session(stoppedTask))).toBe(false);
  });

  it("exposes control capability separately from display state", () => {
    const pausedTask = task({
      activity_state: "paused",
      activity_label: "已暂停",
      is_running: false,
      is_waiting: true,
      is_resumable: true,
      is_interruptible: false,
    });
    const runningTask = task({
      activity_state: "running",
      activity_label: "运行中",
      is_running: true,
      is_interruptible: true,
      is_resumable: false,
    });

    expect(sessionTaskActivityKind(pausedTask)).toBe("paused");
    expect(sessionSummaryCanResume(session(pausedTask))).toBe(true);
    expect(sessionSummaryCanInterrupt(session(pausedTask))).toBe(false);
    expect(sessionSummaryIsRunning(session(runningTask))).toBe(true);
    expect(sessionSummaryCanInterrupt(session(runningTask))).toBe(true);
  });
});
