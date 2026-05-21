import { describe, expect, it } from "vitest";

import type { TaskGraphRecord } from "@/lib/api";

import {
  MODULAR_NOVEL_MASTER_GRAPH_ID,
  recommendedTaskGraphId,
  sortTaskGraphsForWorkbench,
  taskGraphFeatureBadges,
} from "./taskGraphSelection";

function graph(partial: Partial<TaskGraphRecord>): TaskGraphRecord {
  return {
    graph_id: partial.graph_id ?? "graph.test",
    title: partial.title ?? partial.graph_id ?? "测试图",
    domain_id: partial.domain_id ?? "domain.test",
    task_family: partial.task_family ?? "test",
    graph_kind: partial.graph_kind ?? "coordination",
    entry_node_id: partial.entry_node_id ?? "start",
    output_node_id: partial.output_node_id ?? "end",
    nodes: partial.nodes ?? [],
    edges: partial.edges ?? [],
    node_count: partial.node_count,
    edge_count: partial.edge_count,
    graph_contract_id: partial.graph_contract_id,
    contract_bindings: partial.contract_bindings,
    default_protocol_id: partial.default_protocol_id,
    working_memory_policy_profile_id: partial.working_memory_policy_profile_id,
    working_memory_policy: partial.working_memory_policy,
    runtime_policy: partial.runtime_policy,
    context_policy: partial.context_policy,
    publish_state: partial.publish_state ?? "draft",
    enabled: partial.enabled ?? true,
    metadata: partial.metadata,
    issues: partial.issues,
    issue_count: partial.issue_count,
    error_count: partial.error_count,
    warning_count: partial.warning_count,
    valid: partial.valid,
    overview_mode: partial.overview_mode,
  };
}

describe("task graph selection", () => {
  it("recommends the modular novel master graph before older graphs", () => {
    const graphs = [
      graph({ graph_id: "graph.old.writing", title: "旧写作图", node_count: 80 }),
      graph({
        graph_id: MODULAR_NOVEL_MASTER_GRAPH_ID,
        title: "模块化长篇写作总任务图",
        domain_id: "domain.writing.modular_novel",
        task_family: "writing_modular_novel",
        metadata: {
          timeline_blocks: [
            { block_id: "block.design", linked_graph_id: "graph.writing.modular_novel.design_init" },
          ],
        },
        contract_bindings: { schema: { graph_contract_id: "contract.writing.modular_novel.graph" } },
      }),
      graph({ graph_id: "graph.general", title: "通用图" }),
    ];

    expect(sortTaskGraphsForWorkbench(graphs)[0].graph_id).toBe(MODULAR_NOVEL_MASTER_GRAPH_ID);
    expect(recommendedTaskGraphId(graphs)).toBe(MODULAR_NOVEL_MASTER_GRAPH_ID);
  });

  it("keeps an explicitly selected graph when it still exists", () => {
    const graphs = [
      graph({ graph_id: MODULAR_NOVEL_MASTER_GRAPH_ID, domain_id: "domain.writing.modular_novel" }),
      graph({ graph_id: "graph.user.selected" }),
    ];

    expect(recommendedTaskGraphId(graphs, "graph.user.selected")).toBe("graph.user.selected");
  });

  it("surfaces graph module and batch contract feature badges", () => {
    const badges = taskGraphFeatureBadges(graph({
      graph_id: "graph.writing.modular_novel.chapter_cycle",
      contract_bindings: {
        unit_batch: { unit_kind: "chapter", requested_count: 50, batch_size: 5 },
      },
      metadata: {
        timeline_blocks: [{ block_id: "block.review", linked_graph_id: "graph.review" }],
      },
    }));

    expect(badges).toContain("图模块");
    expect(badges).toContain("批次契约");
    expect(badges).toContain("contract_bindings");
  });
});
