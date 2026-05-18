import { describe, expect, it } from "vitest";

import type { TaskGraphStandardView } from "@/lib/api";

import {
  buildTaskGraphResourceStandardModel,
  buildTaskGraphTimelineStandardModel,
  describeTaskGraphStandardEdge,
} from "./taskGraphStandardView";

const STANDARD_VIEW_FIXTURE: TaskGraphStandardView = {
  authority: "task_system.task_graph_standard_view",
  graph: {
    graph_id: "graph.novel",
    title: "小说写作图",
  },
  nodes: [
    {
      node_id: "writer",
      title: "写手",
      node_type: "agent_role",
      phase_id: "phase.draft",
      sequence_index: 1,
      timeline_group_id: "main",
      main_chain: true,
      blocks_phase_exit: true,
      executor: {},
      contracts: {},
      context: {},
      runtime: { execution_mode: "async" },
      artifacts: {},
      loop: {},
      resource: {},
      metadata: {},
    },
    {
      node_id: "review",
      title: "审核",
      node_type: "review_gate",
      phase_id: "phase.review",
      sequence_index: 2,
      timeline_group_id: "main",
      main_chain: true,
      blocks_phase_exit: true,
      executor: {},
      contracts: {},
      context: {},
      runtime: { execution_mode: "sync" },
      artifacts: {},
      loop: {},
      resource: {},
      metadata: {},
    },
  ],
  edges: [
    {
      edge_id: "edge.memory.read",
      source_node_id: "memory.world",
      target_node_id: "writer",
      edge_type: "memory_read",
      payload_contract_id: "",
      handoff: {},
      memory: {
        repository_id: "memory.world",
        collection: "world_bible",
      },
      artifact_context: {},
      revision: {},
      temporal: {},
      metadata: {},
    },
    {
      edge_id: "edge.temporal.review",
      source_node_id: "writer",
      target_node_id: "review",
      edge_type: "temporal_dependency",
      payload_contract_id: "",
      handoff: {},
      memory: {},
      artifact_context: {},
      revision: {},
      temporal: { dependency_role: "phase_gate" },
      metadata: {},
    },
  ],
  resources: [
    {
      node_id: "memory.world",
      title: "世界观仓库",
      resource_type: "memory_repository",
      repository_id: "memory.world",
      collections: ["world_bible", "characters"],
      lifecycle: { task_run_scope_policy: "isolated_per_task_run" },
      readable_by: ["writer"],
      write_owner_node_ids: ["review"],
      metadata: {},
    },
    {
      node_id: "artifact.chapter",
      title: "章节产物仓库",
      resource_type: "artifact_repository",
      repository_id: "artifact.chapter",
      collections: ["draft", "committed"],
      lifecycle: { task_run_scope_policy: "isolated_per_task_run" },
      readable_by: [],
      write_owner_node_ids: ["writer"],
      metadata: {},
    },
    {
      node_id: "thread.ledger.1",
      title: "线程账本",
      resource_type: "thread_ledger",
      repository_id: "thread.ledger.1",
      collections: ["threads", "decisions"],
      lifecycle: { task_run_scope_policy: "isolated_per_task_run" },
      readable_by: ["writer", "review"],
      write_owner_node_ids: ["review"],
      metadata: {},
    },
  ],
  timeline: {
    entry_node_id: "writer",
    output_node_id: "review",
    temporal_edges: [{ edge_id: "edge.temporal.review", phase_id: "phase.review" }],
    loop_frames: [{ node_id: "loop.volume", loop_kind: "while_target_not_met" }],
    phases: [
      { phase_id: "phase.draft", title: "draft" },
      { phase_id: "phase.review", title: "review" },
    ],
    scheduler: {},
  },
  runtime_isolation: {
    task_run_scope_policy: "isolated_per_task_run",
    memory_repositories: [{ repository_id: "memory.world" }],
    artifact_repositories: [{ repository_id: "artifact.chapter" }],
    runtime_state_stores: [],
  },
  memory_matrix: {},
  diagnostics: {},
  issues: [{ code: "memory.selector.missing", message: "selector missing", severity: "warn" }],
};

describe("TaskGraph standard view helpers", () => {
  it("summarizes standard resource objects by repository and edge type", () => {
    const model = buildTaskGraphResourceStandardModel(STANDARD_VIEW_FIXTURE);

    expect(model.memoryResources).toHaveLength(1);
    expect(model.artifactResources).toHaveLength(1);
    expect(model.threadLedgerResources).toHaveLength(1);
    expect(model.riskResources).toHaveLength(1);
    expect(model.memoryEdges).toHaveLength(1);
    expect(model.memoryEdgeCountByRepository["memory.world"]).toBe(1);
  });

  it("summarizes standard timeline objects by phase and loop frame", () => {
    const model = buildTaskGraphTimelineStandardModel(STANDARD_VIEW_FIXTURE);

    expect(model.entryNodeId).toBe("writer");
    expect(model.outputNodeId).toBe("review");
    expect(model.phases).toHaveLength(2);
    expect(model.phaseNodeCounts["phase.draft"]).toBe(1);
    expect(model.loopFrames).toHaveLength(1);
    expect(model.asyncNodeCount).toBe(1);
  });

  it("formats standard edge labels for resource inspector usage", () => {
    expect(describeTaskGraphStandardEdge(STANDARD_VIEW_FIXTURE.edges[0]!)).toContain("memory_read");
    expect(describeTaskGraphStandardEdge(STANDARD_VIEW_FIXTURE.edges[0]!)).toContain("memory.world.world_bible");
  });
});
