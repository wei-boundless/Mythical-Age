import { describe, expect, it } from "vitest";

import type { SessionSummary, SessionTaskSummary } from "@/lib/api";
import { sessionSummaryIsRunning, sessionTaskActivityKind, sessionTaskStatusLabel } from "./sessionTaskPresentation";

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
  it("treats waiting task state as waiting even when the bucket still says running", () => {
    const waitingTask = task({
      action_required: true,
      bucket: "running",
      lifecycle: "paused",
      status: "waiting_executor",
    });

    expect(sessionTaskActivityKind(waitingTask)).toBe("waiting");
    expect(sessionTaskStatusLabel(waitingTask)).toBe("等待继续");
    expect(sessionSummaryIsRunning(session(waitingTask), ["session:main"])).toBe(false);
  });

  it("lets waiting semantics beat terminal and stale stream residue", () => {
    const waitingTerminalTask = task({
      bucket: "running",
      lifecycle: "paused",
      status: "waiting_executor",
      terminal: true,
    });
    const staleDiagnosticTask = task({
      bucket: "diagnostics",
      lifecycle: "stale",
      stale: true,
      status: "running",
    });

    expect(sessionTaskActivityKind(waitingTerminalTask)).toBe("waiting");
    expect(sessionSummaryIsRunning(session(waitingTerminalTask), ["session:main"])).toBe(false);
    expect(sessionTaskStatusLabel(staleDiagnosticTask)).toBe("等待继续");
    expect(sessionSummaryIsRunning(session(staleDiagnosticTask), ["session:main"])).toBe(false);
  });

  it("marks sessions as running for active streams or true running task state", () => {
    const runningTask = task({ bucket: "running", status: "running" });
    const completedTask = task({ status: "completed", terminal: true });
    const stoppedTask = task({ status: "user_aborted" });

    expect(sessionSummaryIsRunning(session(runningTask), [])).toBe(true);
    expect(sessionSummaryIsRunning(session(completedTask), ["session:main"])).toBe(true);
    expect(sessionSummaryIsRunning(session(completedTask), [])).toBe(false);
    expect(sessionSummaryIsRunning(session(stoppedTask), ["session:main"])).toBe(false);
  });
});
