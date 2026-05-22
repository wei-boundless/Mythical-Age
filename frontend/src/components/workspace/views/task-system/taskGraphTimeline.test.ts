import { describe, expect, it } from "vitest";

import { buildTimelinePreflightIssues, coordinationTimelineBlocks, timelineBlockHandoffContractIdOf } from "./taskGraphTimeline";

describe("TaskGraph timeline layering", () => {
  it("reads phase graph blocks from graph metadata", () => {
    const blocks = coordinationTimelineBlocks({
      timeline_blocks: [{
        block_id: "block.design",
        block_type: "design_graph",
        title: "设计阶段图",
        phase_id: "phase.design",
        entry_node_id: "world.plan",
        exit_node_id: "outline.commit",
        handoff_contract_id: "contract.design.handoff",
        visibility_policy: "committed_only",
        version_ref: "v1",
      }],
    });

    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.block_type).toBe("design_graph");
    expect(blocks[0]?.detach_policy).toBe("preserve_version_anchor");
  });

  it("uses timeline block contract_bindings before legacy handoff fields", () => {
    const blocks = coordinationTimelineBlocks({
      timeline_blocks: [{
        block_id: "block.creation",
        block_type: "creation_graph",
        title: "创作阶段图",
        phase_id: "phase.creation",
        handoff_contract_id: "contract.legacy.handoff",
        contract_bindings: {
          handoff: { handoff_contract_id: "contract.binding.handoff" },
        },
      }],
    });

    expect(timelineBlockHandoffContractIdOf(blocks[0] as unknown as Record<string, unknown>)).toBe("contract.binding.handoff");
    expect(buildTimelinePreflightIssues([], [], { timeline_blocks: blocks }).some((issue) => issue.code === "timeline_block_handoff_contract_missing")).toBe(false);
  });

  it("preflights timeline block stitching and edge temporal semantics", () => {
    const issues = buildTimelinePreflightIssues(
      [
        { node_id: "world.plan", phase_id: "phase.design", sequence_index: 1 },
        { node_id: "outline.commit", phase_id: "phase.design", sequence_index: 2 },
      ],
      [
        {
          edge_id: "edge.design.commit",
          source_node_id: "world.plan",
          target_node_id: "outline.commit",
          edge_type: "temporal_dependency",
          metadata: { temporal_semantics: { trigger_timing: "after_source_success" } },
        },
      ],
      {
        phase_definitions: [{ phase_id: "phase.design", title: "设计阶段" }],
        timeline_blocks: [{ block_id: "block.design", block_type: "design_graph", title: "设计阶段图", phase_id: "phase.design" }],
      },
    );

    expect(issues.some((issue) => issue.code === "timeline_block_entry_missing")).toBe(true);
    expect(issues.some((issue) => issue.code === "timeline_block_handoff_contract_missing")).toBe(true);
    expect(issues.some((issue) => issue.code === "timeline_block_imported_graph_missing")).toBe(true);
    expect(issues.some((issue) => issue.code === "timeline_edge_visibility_timing_missing")).toBe(true);
  });

  it("does not require linked_graph_id for ordinary phase graph blocks", () => {
    const issues = buildTimelinePreflightIssues(
      [
        { node_id: "plan", phase_id: "phase.plan", sequence_index: 1 },
        { node_id: "execute", phase_id: "phase.plan", sequence_index: 2 },
      ],
      [{ edge_id: "edge.plan.execute", source_node_id: "plan", target_node_id: "execute", edge_type: "handoff" }],
      {
        phase_definitions: [{ phase_id: "phase.plan", title: "计划" }],
        timeline_blocks: [{
          block_id: "block.phase.plan",
          block_type: "phase_graph",
          title: "计划阶段",
          phase_id: "phase.plan",
          entry_node_id: "plan",
          exit_node_id: "execute",
          handoff_contract_id: "contract.phase.plan",
          version_ref: "template",
        }],
      },
    );

    expect(issues.some((issue) => issue.code === "timeline_block_imported_graph_missing")).toBe(false);
  });
});
