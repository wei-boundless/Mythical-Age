import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PublicTimelineActivity } from "./PublicTimelineActivity";
import type { ProjectionRenderBlock } from "@/lib/projection/chronological";

function renderActivity(blocks: ProjectionRenderBlock[]) {
  return renderToStaticMarkup(
    React.createElement(PublicTimelineActivity, { blocks }),
  );
}

describe("PublicTimelineActivity", () => {
  it("renders runtime recovery reason codes as public status text", () => {
    const html = renderActivity([
      {
        kind: "terminal_event",
        id: "status:restart",
        title: "运行已结束",
        detail: "runtime_cell_missing_after_restart",
        state: "stopped",
        offset: 1,
      },
    ]);

    expect(html).toContain("连接恢复后需要重新接续运行");
    expect(html).not.toContain("runtime_cell_missing_after_restart");
  });
});
