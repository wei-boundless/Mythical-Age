import {
  buildTaskGraphSemanticEdge,
  taskGraphSemanticRelationPresetById,
  type TaskGraphSemanticRelationId,
  type TaskGraphSemanticRelationPreset,
} from "./taskGraphSemanticRelations";
import type { TaskGraphEdge, TaskGraphNode } from "./taskGraphTypes";

export type TaskGraphSemanticNodeKind =
  | "writer"
  | "reviewer"
  | "repairer"
  | "memory_repository"
  | "artifact_repository"
  | "human_gate";

export type TaskGraphEditorActionGroup = {
  id: string;
  title: string;
  description: string;
  actions: TaskGraphEditorAction[];
};

export type TaskGraphEditorAction = {
  id: string;
  title: string;
  description: string;
  kind: "node" | "edge";
  nodeKind?: TaskGraphSemanticNodeKind;
  relationId?: TaskGraphSemanticRelationId;
};

export const TASK_GRAPH_EDITOR_ACTION_GROUPS: TaskGraphEditorActionGroup[] = [
  {
    id: "roles",
    title: "协作角色",
    description: "先表达节点职责，再让后端装配运行协议。",
    actions: [
      {
        id: "node.writer",
        title: "写作节点",
        description: "产出可审核草稿或交付文本。",
        kind: "node",
        nodeKind: "writer",
      },
      {
        id: "node.reviewer",
        title: "审核节点",
        description: "给出通过、返修或阻断裁决。",
        kind: "node",
        nodeKind: "reviewer",
      },
      {
        id: "node.repairer",
        title: "返修节点",
        description: "只根据审核意见修订产物。",
        kind: "node",
        nodeKind: "repairer",
      },
    ],
  },
  {
    id: "relations",
    title: "语义关系",
    description: "选中现有边，或先设起点再选终点。",
    actions: [
      {
        id: "edge.review",
        title: "交给审核",
        description: "草稿进入审核门。",
        kind: "edge",
        relationId: "writing.draft_to_review",
      },
      {
        id: "edge.revision",
        title: "返修关系",
        description: "审核未通过时回到返修/写作节点。",
        kind: "edge",
        relationId: "writing.review_revise_to_writer",
      },
      {
        id: "edge.review-again",
        title: "返修复审",
        description: "修订结果回到审核节点。",
        kind: "edge",
        relationId: "writing.revision_to_review",
      },
    ],
  },
  {
    id: "resources",
    title: "资源与记忆",
    description: "把读写意图挂到图上，协议由编译层解析。",
    actions: [
      {
        id: "node.memory",
        title: "记忆仓库",
        description: "保存事实、决策、返修问题或连续状态。",
        kind: "node",
        nodeKind: "memory_repository",
      },
      {
        id: "node.artifact",
        title: "产物仓库",
        description: "保存草稿、审稿结果和提交引用。",
        kind: "node",
        nodeKind: "artifact_repository",
      },
      {
        id: "edge.memory-read",
        title: "读取记忆",
        description: "仓库记录进入节点输入包。",
        kind: "edge",
        relationId: "memory.read_required",
      },
      {
        id: "edge.memory-write",
        title: "写候选",
        description: "节点输出先写成候选记录。",
        kind: "edge",
        relationId: "memory.write_candidate",
      },
      {
        id: "edge.memory-commit",
        title: "提交记忆",
        description: "审核后把候选转为正式可见记录。",
        kind: "edge",
        relationId: "memory.commit_after_review",
      },
    ],
  },
  {
    id: "guards",
    title: "门控",
    description: "把需要人类确认的阻塞点挂到图上。",
    actions: [
      {
        id: "node.human-gate",
        title: "人工门控",
        description: "关键点需要人工确认后继续。",
        kind: "node",
        nodeKind: "human_gate",
      },
    ],
  },
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function sanitizeId(value: string) {
  return value.replace(/[^a-zA-Z0-9_.:-]+/g, "_").replace(/^_+|_+$/g, "") || "item";
}

function nextId(prefix: string, existingIds: Set<string>) {
  let index = 1;
  let candidate = `${prefix}.${index}`;
  while (existingIds.has(candidate)) {
    index += 1;
    candidate = `${prefix}.${index}`;
  }
  return candidate;
}

function rolePromptFor(kind: TaskGraphSemanticNodeKind) {
  const prompts: Record<TaskGraphSemanticNodeKind, string> = {
    writer: [
      "你是一名交付写作者。",
      "你只负责根据当前任务目标和输入资料产出可审核的草稿或正文。",
      "你不负责替审核员放行结果，也不得把缺失资料自行补写成事实。",
      "你需要明确引用依据、保留不确定点，并输出可交接给审核节点的结果。",
    ].join("\n"),
    reviewer: [
      "你是一名质量审核员。",
      "你只负责判断上游产物是否达到当前任务图的质量标准。",
      "你不负责替写作者扩写正文，也不负责降低质量门。",
      "你必须给出通过、返修或阻断裁决，并说明证据、问题和返修要求。",
    ].join("\n"),
    repairer: [
      "你是一名返修执行者。",
      "你只负责根据审核意见修订指定产物。",
      "你不负责扩大任务范围，也不得忽略审核指出的问题。",
      "你需要输出修订结果、修改说明和仍需复核的风险。",
    ].join("\n"),
    human_gate: [
      "你是一名人工门控协调员。",
      "你只负责把需要人类裁决的事项整理成清晰工作单。",
      "你不负责替人类作出不可逆决定。",
      "你必须说明阻塞原因、可选决策和继续执行所需条件。",
    ].join("\n"),
    memory_repository: "",
    artifact_repository: "",
  };
  return prompts[kind];
}

export function createTaskGraphSemanticNodeDraft(
  kind: TaskGraphSemanticNodeKind,
  existingNodes: Array<Record<string, unknown>>,
): TaskGraphNode {
  const existingIds = new Set(existingNodes.map((node) => String(node.node_id ?? node.id ?? "")).filter(Boolean));
  if (kind === "memory_repository") {
    const nodeId = nextId("memory.repository", existingIds);
    return {
      node_id: nodeId,
      node_type: "memory_repository",
      title: "记忆仓库",
      label: "记忆仓库",
      role: "resource",
      work_posture: "resource",
      metadata: {
        memory_repository: {
          repository_id: nodeId,
          schema_id: "schema.memory_record",
          collections: [{
            collection_id: "default",
            title: "默认集合",
            record_kinds: ["memory_record"],
            key_strategy: "stable_key",
            default_version_selector: "latest_committed_before_clock",
            required_commit_status: "committed",
          }],
        },
      },
      resource_lifecycle_policy: {
        versioning: "append_version",
        mutable: true,
        commit_required: true,
      },
    };
  }
  if (kind === "artifact_repository") {
    const nodeId = nextId("artifact.repository", existingIds);
    return {
      node_id: nodeId,
      node_type: "artifact_repository",
      title: "产物仓库",
      label: "产物仓库",
      role: "resource",
      work_posture: "resource",
      metadata: {
        artifact_repository: {
          repository_id: nodeId,
          schema_id: "schema.artifact_ref",
        },
      },
      resource_lifecycle_policy: {
        versioning: "append_version",
        mutable: true,
        commit_required: false,
      },
    };
  }

  const roleByKind: Record<Exclude<TaskGraphSemanticNodeKind, "memory_repository" | "artifact_repository">, string> = {
    writer: "writer",
    reviewer: "reviewer",
    repairer: "repairer",
    human_gate: "manual_gate",
  };
  const titleByKind: Record<Exclude<TaskGraphSemanticNodeKind, "memory_repository" | "artifact_repository">, string> = {
    writer: "写作节点",
    reviewer: "审核节点",
    repairer: "返修节点",
    human_gate: "人工门控",
  };
  const role = roleByKind[kind];
  const nodeId = nextId(`agent.${sanitizeId(role)}`, existingIds);
  const metadata = {
    role_identity: rolePromptFor(kind).split("\n")[0] ?? "",
    responsibility_scope: rolePromptFor(kind).split("\n")[1] ?? "",
    responsibility_exclusions: rolePromptFor(kind).split("\n")[2] ?? "",
    definition_of_done: rolePromptFor(kind).split("\n")[3] ?? "",
  };
  return {
    node_id: nodeId,
    node_type: kind === "human_gate" ? "manual_gate" : "agent_role",
    title: titleByKind[kind],
    label: titleByKind[kind],
    role,
    work_posture: role,
    execution_mode: kind === "human_gate" ? "manual_gate" : "sync",
    wait_policy: "wait_all_upstream_completed",
    join_policy: "all_success",
    blocks_phase_exit: true,
    role_prompt: rolePromptFor(kind),
    metadata,
    ...(kind === "reviewer"
      ? {
        review_gate_policy: {
          is_review_gate: true,
          gate_kind: "quality_gate",
          verdict_key: "review_result",
        },
        output_contract_id: "contract.review.verdict",
      }
      : {}),
    ...(kind === "human_gate"
      ? {
        human_gate_policy: {
          mode: "manual_required",
          blocking: true,
          work_order_schema: "node_standard_input_output",
        },
      }
      : {}),
  };
}

export function createTaskGraphSemanticEdgeDraft({
  existingEdges,
  relationId,
  semanticRelations,
  sourceNodeId,
  targetNodeId,
}: {
  existingEdges: Array<Record<string, unknown>>;
  relationId: TaskGraphSemanticRelationId;
  semanticRelations?: TaskGraphSemanticRelationPreset[];
  sourceNodeId: string;
  targetNodeId: string;
}): TaskGraphEdge {
  const existingIds = new Set(existingEdges.map((edge) => String(edge.edge_id ?? edge.id ?? "")).filter(Boolean));
  const edgeIdBase = `edge.${sanitizeId(relationId)}.${sanitizeId(sourceNodeId)}.${sanitizeId(targetNodeId)}`;
  const edgeId = existingIds.has(edgeIdBase) ? nextId(edgeIdBase, existingIds) : edgeIdBase;
  return buildTaskGraphSemanticEdge({
    edgeId,
    relationId,
    semanticRelations,
    sourceNodeId,
    targetNodeId,
    title: relationId,
    parameters: defaultSemanticParameters(relationId, sourceNodeId, targetNodeId, semanticRelations),
  });
}

export function semanticEdgePatchForRelation(
  edge: Record<string, unknown>,
  relationId: TaskGraphSemanticRelationId,
  semanticRelations?: TaskGraphSemanticRelationPreset[],
): Record<string, unknown> {
  const sourceNodeId = String(edge.source_node_id ?? edge.from ?? edge.source ?? "").trim();
  const targetNodeId = String(edge.target_node_id ?? edge.to ?? edge.target ?? "").trim();
  const draft = createTaskGraphSemanticEdgeDraft({
    existingEdges: [edge],
    relationId,
    semanticRelations,
    sourceNodeId,
    targetNodeId,
  });
  return {
    edge_type: draft.edge_type,
    mode: draft.mode,
    title: draft.title,
    metadata: {
      ...asRecord(edge.metadata),
      ...asRecord(draft.metadata),
    },
  };
}

function defaultSemanticParameters(
  relationId: TaskGraphSemanticRelationId,
  sourceNodeId: string,
  targetNodeId: string,
  semanticRelations: TaskGraphSemanticRelationPreset[] = [],
): Record<string, unknown> {
  const preset = taskGraphSemanticRelationPresetById(relationId, semanticRelations);
  const presetParameters = { ...(preset?.default_parameters ?? {}) };
  if (relationId === "memory.read_required") {
    return {
      ...presetParameters,
      repository_id: sourceNodeId,
      collection_id: "default",
      record_kind: "memory_record",
      model_visible_label: "default",
      usage_instruction: "你必须按这份记忆输入包约束当前任务；缺失信息不能自行补写成事实。",
      limit: 50,
    };
  }
  if (relationId === "memory.write_candidate") {
    return {
      ...presetParameters,
      repository_id: targetNodeId,
      collection_id: "default",
      record_kind: "memory_record",
      record_key: `${targetNodeId}.default.current`,
      source_output_key: "memory_candidate",
    };
  }
  if (relationId === "memory.commit_after_review") {
    return {
      ...presetParameters,
      repository_id: targetNodeId,
      collection_id: "default",
      record_kind: "memory_record",
      record_key: `${targetNodeId}.default.current`,
      candidate_ref_key: "memory_candidate",
      verdict_key: "review_result",
      required_verdict: "pass",
      approval_source_node_id: sourceNodeId,
      visible_after: "next_clock",
    };
  }
  if (relationId === "writing.review_revise_to_writer") {
    return {
      ...presetParameters,
      original_artifact_key: "candidate_ref",
      review_result_key: "review_result",
      usage_instruction: "你必须依据审核结果修改被退回的原始产物，只处理审核指出的问题。",
    };
  }
  return presetParameters;
}
