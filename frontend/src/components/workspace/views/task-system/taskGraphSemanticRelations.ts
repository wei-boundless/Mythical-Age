import type { TaskGraphEdge } from "./taskGraphTypes";

export type KnownTaskGraphSemanticRelationId =
  | "writing.draft_to_review"
  | "writing.review_pass_to_commit"
  | "writing.review_revise_to_writer"
  | "writing.revision_to_review"
  | "writing.review_reject_to_human"
  | "memory.read_required"
  | "memory.write_candidate"
  | "memory.commit_after_review";

export type TaskGraphSemanticRelationId = KnownTaskGraphSemanticRelationId | (string & {});

export type TaskGraphSemanticRelationPreset = {
  relation_id: TaskGraphSemanticRelationId;
  title_zh: string;
  category: string;
  description: string;
  edge_type: string;
  contract_family_id: string;
  payload_contract_id: string;
  default_parameters: Record<string, unknown>;
  configurable_fields: string[];
};

export const FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS: TaskGraphSemanticRelationPreset[] = [
  {
    relation_id: "writing.draft_to_review",
    title_zh: "草稿进入审核",
    category: "writing_review",
    description: "写手交付草稿产物，审核节点按质量门裁决是否通过。",
    edge_type: "handoff",
    contract_family_id: "writing.draft_artifact",
    payload_contract_id: "contract.writing.draft_artifact.draft",
    default_parameters: { artifact_type: "draft", handoff_mode: "structured_packet" },
    configurable_fields: ["artifact_type", "quality_bar"],
  },
  {
    relation_id: "writing.review_pass_to_commit",
    title_zh: "审核通过后提交",
    category: "writing_review",
    description: "审核节点放行产物，进入提交或下一阶段。",
    edge_type: "handoff",
    contract_family_id: "writing.commit_receipt",
    payload_contract_id: "contract.writing.commit_receipt.approved_artifact",
    default_parameters: { verdict_key: "verdict", required_verdict: "pass" },
    configurable_fields: ["verdict_key", "required_verdict", "commit_target"],
  },
  {
    relation_id: "writing.review_revise_to_writer",
    title_zh: "审核未通过返修",
    category: "writing_revision",
    description: "审核节点把问题清单和返修要求发回写手或返修节点。",
    edge_type: "review_feedback",
    contract_family_id: "writing.revision_request",
    payload_contract_id: "contract.writing.revision_request.revise",
    default_parameters: { verdict_key: "verdict", required_verdict: "revise", max_revision_attempts: 3 },
    configurable_fields: ["verdict_key", "required_verdict", "max_revision_attempts", "carry_fields"],
  },
  {
    relation_id: "writing.revision_to_review",
    title_zh: "返修后复审",
    category: "writing_revision",
    description: "返修节点把修订产物重新交给审核节点。",
    edge_type: "handoff",
    contract_family_id: "writing.draft_artifact",
    payload_contract_id: "contract.writing.draft_artifact.revision",
    default_parameters: { artifact_type: "revision", handoff_mode: "structured_packet" },
    configurable_fields: ["artifact_type", "quality_bar"],
  },
  {
    relation_id: "writing.review_reject_to_human",
    title_zh: "审核驳回转人工",
    category: "writing_review",
    description: "审核节点遇到无法自动修复的质量失败时，转给人工确认。",
    edge_type: "conditional_feedback",
    contract_family_id: "writing.review_verdict",
    payload_contract_id: "contract.writing.review_verdict.reject",
    default_parameters: { verdict_key: "verdict", required_verdict: "reject" },
    configurable_fields: ["verdict_key", "required_verdict", "human_gate_role"],
  },
  {
    relation_id: "memory.read_required",
    title_zh: "读取正式记忆",
    category: "memory",
    description: "节点运行前读取已提交记忆，缺失时按策略阻断或提醒。",
    edge_type: "memory_read",
    contract_family_id: "",
    payload_contract_id: "contract.memory.read",
    default_parameters: { on_missing: "block", version_selector: "latest_committed_before_stage_start", limit: 50 },
    configurable_fields: ["repository_id", "collection_id", "record_kind", "model_visible_label", "usage_instruction", "on_missing", "limit"],
  },
  {
    relation_id: "memory.write_candidate",
    title_zh: "写入候选记忆",
    category: "memory",
    description: "节点产出候选记忆；候选不会直接对后续节点可见。",
    edge_type: "memory_write_candidate",
    contract_family_id: "writing.memory_update",
    payload_contract_id: "contract.memory.write_candidate",
    default_parameters: { source_output_key: "memory_candidate", on_missing: "warn" },
    configurable_fields: ["repository_id", "collection_id", "record_kind", "source_output_key"],
  },
  {
    relation_id: "memory.commit_after_review",
    title_zh: "审核后提交记忆",
    category: "memory",
    description: "审核通过后把候选记忆提交为正式可读资料。",
    edge_type: "memory_commit",
    contract_family_id: "writing.memory_update",
    payload_contract_id: "contract.memory.commit",
    default_parameters: { verdict_key: "verdict", required_verdict: "pass", visible_after: "next_clock" },
    configurable_fields: ["repository_id", "collection_id", "record_kind", "approval_source_node_id", "verdict_key", "required_verdict"],
  },
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function compactRecord(value: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== "" && item !== null && item !== undefined && !(Array.isArray(item) && item.length === 0)),
  );
}

function text(value: unknown, fallback = "") {
  return String(value ?? "").trim() || fallback;
}

function stringArray(value: unknown): string[] {
  if (typeof value === "string") {
    return value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
  }
  return Array.isArray(value) ? value.map((item) => text(item)).filter(Boolean) : [];
}

function normalizePreset(value: unknown): TaskGraphSemanticRelationPreset | null {
  const record = asRecord(value);
  const relationId = text(record.relation_id ?? record.id);
  if (!relationId) return null;
  return {
    relation_id: relationId,
    title_zh: text(record.title_zh ?? record.title, relationId),
    category: text(record.category),
    description: text(record.description),
    edge_type: text(record.edge_type, "handoff"),
    contract_family_id: text(record.contract_family_id),
    payload_contract_id: text(record.payload_contract_id),
    default_parameters: compactRecord(asRecord(record.default_parameters)),
    configurable_fields: stringArray(record.configurable_fields),
  };
}

export function normalizeTaskGraphSemanticRelationPresets(value: unknown): TaskGraphSemanticRelationPreset[] {
  const source = Array.isArray(value) ? value : [];
  const byId = new Map(FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS.map((item) => [item.relation_id, item]));
  source.map(normalizePreset).filter((item): item is TaskGraphSemanticRelationPreset => Boolean(item)).forEach((item) => {
    byId.set(item.relation_id, {
      ...byId.get(item.relation_id),
      ...item,
      default_parameters: {
        ...(byId.get(item.relation_id)?.default_parameters ?? {}),
        ...item.default_parameters,
      },
      configurable_fields: item.configurable_fields.length
        ? item.configurable_fields
        : byId.get(item.relation_id)?.configurable_fields ?? [],
    });
  });
  return Array.from(byId.values());
}

export function taskGraphSemanticRelationPresetById(
  relationId: string,
  semanticRelations: TaskGraphSemanticRelationPreset[] = FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS,
) {
  const target = text(relationId);
  return semanticRelations.find((item) => item.relation_id === target)
    ?? FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS.find((item) => item.relation_id === target)
    ?? null;
}

export function taskGraphSemanticRelationLabel(
  relationId: string,
  semanticRelations: TaskGraphSemanticRelationPreset[] = FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS,
) {
  const preset = taskGraphSemanticRelationPresetById(relationId, semanticRelations);
  return preset?.title_zh ? `${preset.title_zh} · ${preset.relation_id}` : relationId;
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

export function taskGraphSemanticEdgeType(
  relationId: string,
  semanticRelations: TaskGraphSemanticRelationPreset[] = FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS,
) {
  return taskGraphSemanticRelationPresetById(relationId, semanticRelations)?.edge_type ?? "";
}

export function buildTaskGraphSemanticEdge({
  edgeId,
  parameters = {},
  relationId,
  semanticRelations = FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS,
  sourceNodeId,
  targetNodeId,
  title,
}: {
  edgeId: string;
  relationId: TaskGraphSemanticRelationId;
  sourceNodeId: string;
  targetNodeId: string;
  parameters?: Record<string, unknown>;
  semanticRelations?: TaskGraphSemanticRelationPreset[];
  title?: string;
}): TaskGraphEdge {
  const edgeType = taskGraphSemanticEdgeType(relationId, semanticRelations) || "handoff";
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
