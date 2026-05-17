import { describe, expect, it } from "vitest";

import {
  buildTaskGraphMemoryModel,
  createMemoryEdgeDraft,
  memoryCellOperationValue,
} from "./taskGraphMemoryMatrix";

describe("TaskGraph memory matrix", () => {
  it("derives repository collection permissions from real graph edges", () => {
    const nodes = [
      {
        node_id: "memory.project",
        node_type: "memory_repository",
        title: "Project Memory",
        metadata: {
          memory_repository: {
            repository_id: "memory.project",
            schema_id: "schema.project_memory",
            collections: [
              { collection_id: "requirements", record_kinds: ["requirement"], key_strategy: "stable_key" },
            ],
          },
        },
      },
      { node_id: "draft", agent_id: "agent.writer", phase_id: "phase.plan" },
      { node_id: "review", agent_id: "agent.review", phase_id: "phase.review" },
    ];
    const edges = [
      {
        edge_id: "edge.memory.draft",
        source_node_id: "memory.project",
        target_node_id: "draft",
        edge_type: "memory_read",
        metadata: {
          repository: "memory.project",
          collection: "requirements",
          selector: { collection: "requirements", status_filter: ["committed"] },
          usage_instruction: "按需求约束起草。",
          model_visible_label: "需求记录",
        },
      },
      {
        edge_id: "edge.draft.memory",
        source_node_id: "draft",
        target_node_id: "memory.project",
        edge_type: "memory_write_candidate",
        metadata: { repository: "memory.project", collection: "requirements" },
      },
      {
        edge_id: "edge.draft.review",
        source_node_id: "draft",
        target_node_id: "review",
        edge_type: "structured_handoff",
      },
      {
        edge_id: "edge.review.memory",
        source_node_id: "review",
        target_node_id: "memory.project",
        edge_type: "memory_commit",
        metadata: {
          repository: "memory.project",
          collection: "requirements",
          receipt_policy: { visible_after: "next_clock" },
        },
      },
    ];

    const model = buildTaskGraphMemoryModel({ nodes, edges });
    const draftRow = model.matrixRows.find((row) => row.nodeId === "draft");
    const cell = draftRow?.cells[0];

    expect(model.repositories).toHaveLength(1);
    expect(model.columns[0]?.collectionId).toBe("requirements");
    expect(cell?.label).toBe("读 / 写候选");
    expect(cell ? memoryCellOperationValue(cell) : "").toBe("read_write_candidate");
    expect(cell?.writeCandidateEdge?.hasCommitPath).toBe(true);
  });

  it("creates a synthetic repository view when a memory edge declares one before the node exists", () => {
    const model = buildTaskGraphMemoryModel({
      nodes: [{ node_id: "worker", agent_id: "agent.worker" }],
      edges: [
        {
          edge_id: "edge.virtual.worker",
          source_node_id: "memory.virtual",
          target_node_id: "worker",
          edge_type: "memory_read",
          metadata: { repository: "memory.virtual", collection: "facts" },
        },
      ],
    });

    expect(model.repositories[0]?.synthetic).toBe(true);
    expect(model.columns[0]?.columnId).toBe("memory.virtual::facts");
    expect(model.snapshots[0]?.issues).toContain("edge.virtual.worker 缺少 usage_instruction");
  });

  it("builds memory edge drafts with deterministic endpoints and selectors", () => {
    const edge = createMemoryEdgeDraft({
      operation: "read",
      repositoryNodeId: "memory.project",
      repositoryId: "memory.project",
      collectionId: "requirements",
      taskNodeId: "draft",
    });

    expect(edge.edge_type).toBe("memory_read");
    expect(edge.source_node_id).toBe("memory.project");
    expect(edge.target_node_id).toBe("draft");
    expect(edge.metadata).toMatchObject({
      repository: "memory.project",
      collection: "requirements",
      selector: { collection: "requirements" },
    });
  });
});
