import { describe, expect, it } from "vitest";

import type { TaskSystemOverview } from "@/lib/api";

import {
  buildCenterWorkspaceTaskGraphInitialInputs,
  centerWorkspaceTaskGraphSessionId,
  listCenterWorkspaceTaskGraphs,
  resolveCenterWorkspaceSelectedGraphId,
} from "./centerWorkspaceHelpers";

describe("center workspace helpers", () => {
  const overview = {
    task_graph_management: {
      task_graphs: [
        {
          graph_id: "graph.low",
          title: "低优先级图",
          domain_id: "domain.demo",
          task_family: "demo",
          graph_kind: "coordination",
          entry_node_id: "a",
          output_node_id: "b",
          nodes: [],
          edges: [],
          publish_state: "published",
          enabled: true,
        },
        {
          graph_id: "graph.recommended",
          title: "推荐图",
          domain_id: "domain.writing.modular_novel",
          task_family: "writing_modular_novel",
          graph_kind: "coordination",
          entry_node_id: "a",
          output_node_id: "b",
          nodes: [],
          edges: [],
          publish_state: "published",
          enabled: true,
        },
      ],
    },
  } as unknown as TaskSystemOverview;

  it("keeps the current graph when it still exists", () => {
    expect(resolveCenterWorkspaceSelectedGraphId(overview, "graph.low")).toBe("graph.low");
  });

  it("falls back to the recommended graph when current selection is missing", () => {
    expect(resolveCenterWorkspaceSelectedGraphId(overview, "missing")).toBe("graph.recommended");
    expect(resolveCenterWorkspaceSelectedGraphId(overview, "")).toBe("graph.recommended");
  });

  it("builds task graph initial inputs from a natural chat message", () => {
    const graph = listCenterWorkspaceTaskGraphs(overview)[0];
    expect(buildCenterWorkspaceTaskGraphInitialInputs("写一个洪荒长篇设定", graph)).toMatchObject({
      user_goal: "写一个洪荒长篇设定",
      original_user_request: "写一个洪荒长篇设定",
      natural_request: "写一个洪荒长篇设定",
      project_brief: "写一个洪荒长篇设定",
      title: "写一个洪荒长篇设定",
      task_graph_title: "推荐图",
    });
    expect(() => buildCenterWorkspaceTaskGraphInitialInputs("   ", graph)).toThrow("请输入任务目标。");
  });

  it("normalizes the current chat session id for task graph runtime", () => {
    expect(centerWorkspaceTaskGraphSessionId("session:abc")).toBe("session_abc");
    expect(centerWorkspaceTaskGraphSessionId("")).toBe("task_graph_studio");
  });

  it("returns sorted graphs for the launch list", () => {
    const graphs = listCenterWorkspaceTaskGraphs(overview);
    expect(graphs[0]?.graph_id).toBe("graph.recommended");
  });
});
