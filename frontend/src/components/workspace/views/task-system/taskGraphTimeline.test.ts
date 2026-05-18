import { describe, expect, it } from "vitest";

import { buildTimelinePreflightIssues, coordinationTimelineBlocks } from "./taskGraphTimeline";

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
        timeline_blocks: [{ block_id: "block.design", title: "设计阶段图", phase_id: "phase.design" }],
      },
    );

    expect(issues.some((issue) => issue.code === "timeline_block_entry_missing")).toBe(true);
    expect(issues.some((issue) => issue.code === "timeline_block_handoff_contract_missing")).toBe(true);
    expect(issues.some((issue) => issue.code === "timeline_edge_visibility_timing_missing")).toBe(true);
  });
});
