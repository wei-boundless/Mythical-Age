import { describe, expect, it } from "vitest";

import { TASK_GRAPH_STUDIO_LAYERS } from "./TaskGraphLayerNav";

describe("task graph UI terminology", () => {
  it("keeps primary layer names user-facing", () => {
    const visibleText = TASK_GRAPH_STUDIO_LAYERS
      .map((layer) => `${layer.title} ${layer.description}`)
      .join(" ");

    expect(visibleText).not.toContain("Graph Builder");
    expect(visibleText).not.toContain("Compiled View");
    expect(visibleText).not.toContain("legacy 来源");
    expect(visibleText).not.toContain("编译预览");
    expect(visibleText).toContain("编辑工作台");
    expect(visibleText).toContain("检查修复");
  });
});
