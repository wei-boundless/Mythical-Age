import { describe, expect, it } from "vitest";

import {
  emptyTaskGraphEditorSelection,
  loadedTaskGraphStandardViewState,
  markTaskGraphStandardViewStale,
  selectCanonicalEdge,
  selectCanonicalNode,
  selectionFromFocus,
  taskGraphDraftRevisionKey,
} from "./taskGraphEditorSelection";

describe("TaskGraph editor selection", () => {
  it("keeps repository focus separate from canonical node selection", () => {
    const selection = selectCanonicalNode(emptyTaskGraphEditorSelection(), "node.writer");
    const next = selectionFromFocus(selection, {
      layer: "memory",
      facet: "repositories",
      repository_id: "memory.writing.baseline",
    });

    expect(next.canonicalNodeId).toBe("node.writer");
    expect(next.resourceId).toBe("memory.writing.baseline");
  });

  it("canonical edge selection clears canonical node selection", () => {
    const selection = selectCanonicalNode(emptyTaskGraphEditorSelection(), "node.writer");
    const next = selectCanonicalEdge(selection, "edge.writer.review");

    expect(next.canonicalNodeId).toBe("");
    expect(next.canonicalEdgeId).toBe("edge.writer.review");
  });

  it("module focus writes preview IDs instead of writable canonical IDs", () => {
    const selection = selectCanonicalNode(emptyTaskGraphEditorSelection(), "node.writer");
    const next = selectionFromFocus(selection, {
      layer: "modules",
      facet: "connections",
      edge_id: "port.edge.writer.review",
    });

    expect(next.canonicalNodeId).toBe("node.writer");
    expect(next.canonicalEdgeId).toBe("");
    expect(next.previewPortEdgeId).toBe("port.edge.writer.review");
  });
});

describe("TaskGraph standard view freshness", () => {
  it("marks a loaded standard view stale when the draft topology revision changes", () => {
    const firstRevision = taskGraphDraftRevisionKey({
      graphId: "graph.story",
      nodes: [{ node_id: "draft" }],
      edges: [],
      metadata: {},
    });
    const nextRevision = taskGraphDraftRevisionKey({
      graphId: "graph.story",
      nodes: [{ node_id: "draft" }, { node_id: "review" }],
      edges: [{ edge_id: "edge.1", source_node_id: "draft", target_node_id: "review", edge_type: "handoff" }],
      metadata: {},
    });
    const state = loadedTaskGraphStandardViewState({
      graphId: "graph.story",
      revisionKey: firstRevision,
      loadedAt: "2026-05-27T00:00:00.000Z",
      view: { graph: { graph_id: "graph.story" }, nodes: [], edges: [], resources: [], units: [], interfaces: [], port_edges: [], graph_module_runtime: [], graph_module_expansions: [], issues: [] } as never,
    });

    expect(markTaskGraphStandardViewStale(state, "graph.story", nextRevision).stale).toBe(true);
    expect(markTaskGraphStandardViewStale(state, "graph.story", firstRevision).stale).toBe(false);
  });
});
