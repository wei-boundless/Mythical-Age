import { describe, expect, it } from "vitest";

import type { TaskGraphStandardView } from "@/lib/api";

import {
  buildTaskGraphComposableStandardModel,
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
  units: [
    {
      unit_id: "unit.node.writer",
      unit_type: "node",
      title: "写手",
      ref: { node_id: "writer" },
      interface_id: "interface.node.writer",
      runtime_policy: { execution_mode: "async" },
      phase_id: "phase.draft",
      sequence_index: 1,
      source_kind: "task_graph_node",
      metadata: {},
    },
    {
      unit_id: "unit.graph.block.creation",
      unit_type: "graph",
      title: "正式创作图",
      ref: { graph_id: "graph.creation", version_ref: "v1" },
      interface_id: "interface.graph.block.creation",
      runtime_policy: { execution_mode: "nested_graph_run" },
      phase_id: "phase.draft",
      sequence_index: 2,
      source_kind: "timeline_block",
      metadata: {},
    },
  ],
  interfaces: [
    {
      interface_id: "interface.node.writer",
      unit_id: "unit.node.writer",
      display_name_zh: "写手接口",
      input_ports: [{ port_id: "input.default", title: "默认输入", direction: "input", payload_contract_id: "contract.input" }],
      output_ports: [{ port_id: "output.default", title: "默认输出", direction: "output", payload_contract_id: "contract.chapter" }],
      version: "v1",
      metadata: {},
    },
    {
      interface_id: "interface.graph.block.creation",
      unit_id: "unit.graph.block.creation",
      display_name_zh: "正式创作图接口",
      input_ports: [{ port_id: "input.default", title: "图输入包", direction: "input", payload_contract_id: "contract.design.commit" }],
      output_ports: [{ port_id: "output.default", title: "图提交包", direction: "output", payload_contract_id: "contract.creation.commit", status_required: "committed" }],
      version: "v1",
      metadata: {},
    },
  ],
  port_edges: [
    {
      edge_id: "edge.writer.creation",
      source_unit_id: "unit.node.writer",
      source_port_id: "output.default",
      target_unit_id: "unit.graph.block.creation",
      target_port_id: "input.default",
      payload_contract_id: "contract.chapter",
      edge_type: "handoff",
      temporal_semantics: { trigger_timing: "after_source_success" },
      handoff: {},
      metadata: {},
    },
  ],
  nested_runtime: [
    {
      plan_id: "nested.block.creation",
      parent_graph_id: "graph.novel",
      unit_id: "unit.graph.block.creation",
      linked_graph_id: "graph.creation",
      version_ref: "v1",
      handoff_contract_id: "contract.creation.commit",
      input_port_id: "input.default",
      output_port_id: "output.default",
      isolation_policy: "isolated_per_nested_run",
      visibility_policy: "committed_only",
      detach_policy: "preserve_version_anchor",
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

  it("summarizes composable units, interfaces, port edges, and nested runtime", () => {
    const model = buildTaskGraphComposableStandardModel(STANDARD_VIEW_FIXTURE);

    expect(model.units).toHaveLength(2);
    expect(model.nodeUnits[0]?.unit_id).toBe("unit.node.writer");
    expect(model.graphUnits[0]?.unit_id).toBe("unit.graph.block.creation");
    expect(model.interfaces).toHaveLength(2);
    expect(model.interfaceByUnitId.get("unit.graph.block.creation")?.output_ports[0]?.status_required).toBe("committed");
    expect(model.portEdgesByUnitId.get("unit.node.writer")).toHaveLength(1);
    expect(model.nestedRuntime[0]?.linked_graph_id).toBe("graph.creation");
  });
});
