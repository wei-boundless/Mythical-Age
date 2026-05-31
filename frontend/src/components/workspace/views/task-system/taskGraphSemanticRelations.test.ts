import { describe, expect, it } from "vitest";

import {
  buildTaskGraphSemanticEdge,
  normalizeTaskGraphSemanticRelationPresets,
  taskGraphSemanticEdgeType,
  taskGraphSemanticRelationLabel,
} from "./taskGraphSemanticRelations";

describe("TaskGraph semantic relations", () => {
  it("keeps the full backend relation family available through the fallback catalog", () => {
    const presets = normalizeTaskGraphSemanticRelationPresets([]);
    const relationIds = presets.map((item) => item.relation_id);

    expect(relationIds).toContain("writing.review_pass_to_commit");
    expect(relationIds).toContain("writing.review_reject_to_human");
    expect(relationIds).toContain("memory.commit_after_review");
  });

  it("uses catalog relation metadata when creating semantic edges", () => {
    const presets = normalizeTaskGraphSemanticRelationPresets([
      {
        relation_id: "custom.qa_gate",
        title_zh: "QA 门",
        category: "quality",
        description: "QA gate",
        edge_type: "conditional_feedback",
        payload_contract_id: "contract.qa.verdict",
        default_parameters: { verdict_key: "qa_verdict" },
        configurable_fields: ["verdict_key"],
      },
    ]);
    const edge = buildTaskGraphSemanticEdge({
      edgeId: "edge.qa",
      relationId: "custom.qa_gate",
      semanticRelations: presets,
      sourceNodeId: "review",
      targetNodeId: "human",
      parameters: { required_verdict: "reject" },
    });
    const metadata = edge.metadata as Record<string, unknown>;

    expect(taskGraphSemanticEdgeType("custom.qa_gate", presets)).toBe("conditional_feedback");
    expect(taskGraphSemanticRelationLabel("custom.qa_gate", presets)).toBe("QA 门 · custom.qa_gate");
    expect(edge.edge_type).toBe("conditional_feedback");
    expect(metadata.semantic_relation_id).toBe("custom.qa_gate");
    expect(metadata.semantic_parameters).toEqual({ required_verdict: "reject" });
  });
});
