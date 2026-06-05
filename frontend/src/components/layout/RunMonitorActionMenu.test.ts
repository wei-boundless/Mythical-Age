import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RunMonitorActionMenu } from "./RunMonitorActionMenu";
import type { RunMonitorSignal } from "@/lib/run-monitor/types";

function signalWithActions(actions: RunMonitorSignal["actions"]): RunMonitorSignal {
  return {
    actions,
    activity_state: "paused",
    is_running: false,
    signal_id: "signal:paused",
    state: "waiting",
    task_run_id: "taskrun:paused",
    title: "暂停任务",
  } as RunMonitorSignal;
}

describe("RunMonitorActionMenu", () => {
  it("does not expose resume actions as a continuation button", () => {
    const html = renderToStaticMarkup(
      React.createElement(RunMonitorActionMenu, {
        loadingAction: "",
        onAction: () => undefined,
        signal: signalWithActions([
          { action: "resume_task", enabled: true, label: "继续" },
        ]),
      }),
    );

    expect(html).toBe("");
  });

  it("keeps non-resume actions available", () => {
    const html = renderToStaticMarkup(
      React.createElement(RunMonitorActionMenu, {
        loadingAction: "",
        onAction: () => undefined,
        signal: signalWithActions([
          { action: "stop_task", enabled: true, label: "停止" },
        ]),
      }),
    );

    expect(html).toContain("运行操作");
  });
});
