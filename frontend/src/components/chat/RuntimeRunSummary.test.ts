import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RuntimeRunSummary } from "./RuntimeRunSummary";

describe("RuntimeRunSummary", () => {
  it("labels completed chat TaskRun attachments as task activity even when early task_order entries are truncated", () => {
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

    expect(html).toContain("任务运行");
    expect(html).not.toContain("会话运行");
  });
});
