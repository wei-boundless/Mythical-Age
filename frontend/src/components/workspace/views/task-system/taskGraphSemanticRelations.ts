import type { TaskGraphEdge } from "./taskGraphTypes";

export type TaskGraphSemanticRelationId =
  | "writing.draft_to_review"
  | "writing.review_pass_to_commit"
  | "writing.review_revise_to_writer"
  | "writing.revision_to_review"
  | "writing.review_reject_to_human"
  | "memory.read_required"
  | "memory.write_candidate"
  | "memory.commit_after_review";

const EDGE_TYPE_BY_RELATION: Record<TaskGraphSemanticRelationId, string> = {
  "writing.draft_to_review": "handoff",
  "writing.review_pass_to_commit": "handoff",
  "writing.review_revise_to_writer": "review_feedback",
  "writing.revision_to_review": "handoff",
  "writing.review_reject_to_human": "conditional_feedback",
  "memory.read_required": "memory_read",
  "memory.write_candidate": "memory_write_candidate",
  "memory.commit_after_review": "memory_commit",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function compactRecord(value: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== "" && item !== null && item !== undefined && !(Array.isArray(item) && item.length === 0)),
  );
}

function text(value: unknown) {
  return String(value ?? "").trim();
}

export function taskGraphSemanticRelationIdFromEdge(edge: Record<string, unknown>) {
  const metadata = asRecord(edge.metadata);
  const semantic = asRecord(asRecord(edge.contract_bindings).semantic);
  return text(edge.semantic_relation_id ?? metadata.semantic_relation_id ?? semantic.relation_id);
}

export function taskGraphSemanticParametersFromEdge(edge: Record<string, unknown>) {
  const metadata = asRecord(edge.metadata);
  const semantic = asRecord(asRecord(edge.contract_bindings).semantic);
  return compactRecord({
    ...asRecord(semantic.parameters),
    ...asRecord(metadata.semantic_parameters),
    ...asRecord(edge.semantic_parameters),
  });
}

export function taskGraphSemanticEdgeType(relationId: string) {
  return EDGE_TYPE_BY_RELATION[relationId as TaskGraphSemanticRelationId] ?? "";
}

export function buildTaskGraphSemanticEdge({
  edgeId,
  parameters = {},
  relationId,
  sourceNodeId,
  targetNodeId,
  title,
}: {
  edgeId: string;
  relationId: TaskGraphSemanticRelationId;
  sourceNodeId: string;
  targetNodeId: string;
  parameters?: Record<string, unknown>;
  title?: string;
}): TaskGraphEdge {
  const edgeType = taskGraphSemanticEdgeType(relationId) || "handoff";
  return {
    edge_id: edgeId,
    from: sourceNodeId,
    to: targetNodeId,
    source_node_id: sourceNodeId,
    target_node_id: targetNodeId,
    edge_type: edgeType,
    mode: edgeType,
    title: title || relationId,
    metadata: {
      semantic_relation_id: relationId,
      semantic_parameters: compactRecord(parameters),
    },
  };
}
