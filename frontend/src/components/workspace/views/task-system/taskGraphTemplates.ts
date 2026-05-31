import type { TaskGraphEdge, TaskGraphNode } from "./taskGraphTypes";
import { buildTaskGraphNameRegistryPayload } from "./taskGraphNameRegistry";
import { buildTaskGraphSemanticEdge } from "./taskGraphSemanticRelations";

export type TaskGraphTemplateId =
  | "single_agent"
  | "multi_sequence"
  | "multi_parallel_merge"
  | "review_repair_loop"
  | "rag_research_writing"
  | "pdf_table_synthesis"
  | "long_project_cycle";

export type TaskGraphTemplateCard = {
  template_id: TaskGraphTemplateId;
  title: string;
  intent: string;
  best_for: string;
  participant_roles: string[];
};

export type TaskGraphTemplateBuildInput = {
  template_id: TaskGraphTemplateId;
  domain_id: string;
  selected_task_title?: string;
  communication_mode?: string;
  task_intent?: string;
  input_material_type?: "general" | "rag_corpus" | "pdf" | "table" | "pdf_and_table";
  artifact_type?: "markdown_report" | "structured_json" | "table_dataset" | "decision_brief";
  review_strength?: "light" | "standard" | "strict";
  loop_count?: number;
  require_human_confirmation?: boolean;
  agent_bindings?: Partial<Record<string, string>>;
};

export type TaskGraphTemplateBuildResult = {
  nodes: TaskGraphNode[];
  edges: TaskGraphEdge[];
  metadata: Record<string, unknown>;
  entry_node_id: string;
  output_node_id: string;
  coordination_mode: string;
  participant_agent_ids: string[];
};

type TemplateNodeInput = {
  node_id: string;
  role: string;
  title: string;
  agent_id: string;
  phase_id: string;
  sequence_index: number;
  role_identity: string;
  responsibility_scope: string;
  responsibility_exclusions: string;
  definition_of_done: string;
  node_type?: string;
  task_id?: string;
  task_title?: string;
  blocks_phase_exit?: boolean;
  review_gate?: boolean;
  input_contract_id?: string;
  output_contract_id?: string;
  dispatch_group?: string;
  execution_mode?: string;
  join_policy?: string;
  loop?: Record<string, unknown>;
  context_visibility_policy?: Record<string, unknown>;
  memory_read_policy?: Record<string, unknown>;
  memory_writeback_policy?: Record<string, unknown>;
  artifact_target?: string;
  metadata?: Record<string, unknown>;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function collectionRecordKind(collection: string) {
  return `${collection.replace(/[^a-zA-Z0-9_:-]+/g, "_")}_record`;
}

function agentIdFor(input: TaskGraphTemplateBuildInput, roleKey: string, fallback: string) {
  return String(input.agent_bindings?.[roleKey] ?? fallback).trim() || fallback;
}

export const TASK_GRAPH_TEMPLATE_CARDS: TaskGraphTemplateCard[] = [
  {
    template_id: "single_agent",
    title: "单 Agent 长任务",
    intent: "一个 Agent 持续完成任务，并输出最终结果。",
    best_for: "轻量任务、个人助理式长任务、低交接成本流程",
    participant_roles: ["执行者"],
  },
  {
    template_id: "multi_sequence",
    title: "管线式多 Agent",
    intent: "规划、执行、审查按顺序推进。",
    best_for: "有明确前后依赖的多步骤任务",
    participant_roles: ["规划者", "执行者", "审查者"],
  },
  {
    template_id: "multi_parallel_merge",
    title: "并行审查 + 协调者汇总",
    intent: "多个 Agent 并行给出判断，由协调者合并裁决。",
    best_for: "方案评审、风险复核、创作多视角审阅",
    participant_roles: ["审查者 A", "审查者 B", "协调汇总者"],
  },
  {
    template_id: "review_repair_loop",
    title: "审核门 + 返修循环",
    intent: "执行结果必须通过审核门，未通过则回到返修节点。",
    best_for: "质量门明确、需要反复打磨的持续任务",
    participant_roles: ["执行者", "审核员", "返修者"],
  },
  {
    template_id: "rag_research_writing",
    title: "RAG + 资料分析 + 写作",
    intent: "先检索资料，再分析证据，最后形成可交付文本。",
    best_for: "知识密集型报告、资料问答、研究写作",
    participant_roles: ["RAG 检索员", "资料分析员", "写作者"],
  },
  {
    template_id: "pdf_table_synthesis",
    title: "PDF 分析 + 表格分析 + 汇总",
    intent: "PDF 阅读和表格分析并行产出证据，由汇总 Agent 形成结论。",
    best_for: "报告解读、财务/运营材料分析、PDF 表格混合资料",
    participant_roles: ["PDF 分析员", "表格分析员", "汇总员"],
  },
  {
    template_id: "long_project_cycle",
    title: "长期项目循环执行",
    intent: "计划、执行、复盘、记忆写回形成持续循环。",
    best_for: "长期项目管理、持续运营、周期性研究",
    participant_roles: ["计划员", "执行者", "复盘员", "记忆管理员"],
  },
];

function makeNode(input: TemplateNodeInput, domainId: string): TaskGraphNode {
  return {
    node_id: input.node_id,
    node_type: input.node_type ?? "agent_role",
    task_id: input.task_id ?? "",
    task_title: input.task_title ?? "",
    agent_id: input.agent_id,
    role: input.role,
    work_posture: input.role,
    input_contract_id: input.input_contract_id,
    output_contract_id: input.output_contract_id ?? (input.review_gate ? "contract.review.verdict" : undefined),
    node_contract_id: input.output_contract_id ?? (input.review_gate ? "contract.review.verdict" : undefined),
    label: input.title,
    title: input.title,
    phase_id: input.phase_id,
    sequence_index: input.sequence_index,
    execution_mode: input.execution_mode ?? "sync",
    dispatch_group: input.dispatch_group ?? "",
    wait_policy: "wait_all_upstream_completed",
    join_policy: input.join_policy ?? "all_success",
    blocks_phase_exit: input.blocks_phase_exit ?? true,
    context_visibility_policy: input.context_visibility_policy,
    memory_read_policy: input.memory_read_policy,
    memory_writeback_policy: input.memory_writeback_policy,
    review_gate_policy: input.review_gate ? { is_review_gate: true, gate_kind: "quality_gate", ...asRecord(input.metadata?.review_policy) } : undefined,
    loop: input.loop,
    artifact_policy: input.artifact_target ? {
      required: true,
      artifact_target: input.artifact_target,
      storage_policy: "task_artifact_ref",
    } : undefined,
    artifact_target: input.artifact_target,
    output_path: input.artifact_target,
    metadata: {
      role_identity: input.role_identity,
      responsibility_scope: input.responsibility_scope,
      responsibility_exclusions: input.responsibility_exclusions,
      definition_of_done: input.definition_of_done,
      domain_id: domainId,
      ...(input.metadata ?? {}),
    },
  };
}

function makeMemoryRepositoryNode(
  nodeId: string,
  title: string,
  repositoryId: string,
  collections: string[],
  options: {
    mutable: boolean;
    writeOwnerNodeIds: string[];
    readableBy: string[];
    phaseId?: string;
    sequenceIndex?: number;
    libraryRole?: string;
  },
): TaskGraphNode {
  return {
    node_id: nodeId,
    node_type: repositoryId.includes("issue") ? "issue_ledger" : "memory_repository",
    title,
    label: title,
    role: "resource",
    work_posture: "resource",
    phase_id: options.phaseId ?? "phase.resources",
    sequence_index: options.sequenceIndex ?? 0,
    resource_lifecycle_policy: {
      versioning: "append_version",
      mutable: options.mutable,
      commit_required: options.mutable,
      write_owner_node_ids: options.writeOwnerNodeIds,
      readable_by: options.readableBy,
    },
    metadata: {
      repository_id: repositoryId,
      collections,
      mutable: options.mutable,
      readable_by: options.readableBy,
      write_owner_node_ids: options.writeOwnerNodeIds,
      library_role: options.libraryRole ?? "template_memory_repository",
      memory_repository: {
        repository_id: repositoryId,
        title,
        schema_id: "schema.template.memory_record",
        collections: collections.map((collection) => {
          const recordKind = collectionRecordKind(collection);
          return {
            collection_id: collection,
            title: collection,
            schema_id: "schema.template.memory_record",
            record_kinds: [recordKind],
            key_strategy: "stable_key",
            required_commit_status: "committed",
            default_version_selector: "latest_committed_before_stage_start",
          };
        }),
      },
    },
  };
}

function standardMemoryRepositoryNodes(options: { phaseId?: string } = {}): TaskGraphNode[] {
  return [
    makeMemoryRepositoryNode("memory.baseline", "基准记忆库", "memory.baseline", ["facts", "plans", "decisions"], {
      mutable: false,
      writeOwnerNodeIds: [],
      readableBy: ["agent.planner", "agent.executor", "agent.reviewer", "agent.memory"],
      phaseId: options.phaseId,
      libraryRole: "committed_canon",
    }),
    makeMemoryRepositoryNode("memory.mutable", "动态记忆库", "memory.mutable", ["progress", "state_delta", "continuity"], {
      mutable: true,
      writeOwnerNodeIds: ["agent.memory"],
      readableBy: ["agent.planner", "agent.executor", "agent.reviewer"],
      phaseId: options.phaseId,
      libraryRole: "runtime_delta",
    }),
    makeMemoryRepositoryNode("memory.issue_ledger", "问题台账", "memory.issue_ledger", ["issues", "revision_requests", "risk_notes"], {
      mutable: true,
      writeOwnerNodeIds: ["agent.reviewer"],
      readableBy: ["agent.planner", "agent.executor", "agent.reviewer", "agent.memory"],
      phaseId: options.phaseId,
      libraryRole: "review_issues",
    }),
    makeMemoryRepositoryNode("memory.artifact_index", "产物索引库", "memory.artifact_index", ["candidate_refs", "review_refs", "commit_refs"], {
      mutable: true,
      writeOwnerNodeIds: ["agent.memory", "agent.reviewer"],
      readableBy: ["*"],
      phaseId: options.phaseId,
      libraryRole: "artifact_refs",
    }),
  ];
}

function memoryReadEdge(edgeId: string, repositoryNodeId: string, targetNodeId: string, collection: string): TaskGraphEdge {
  return buildTaskGraphSemanticEdge({
    edgeId,
    relationId: "memory.read_required",
    sourceNodeId: repositoryNodeId,
    targetNodeId,
    title: "读取正式记忆",
    parameters: {
      repository_id: repositoryNodeId,
      collection_id: collection,
      record_kind: collectionRecordKind(collection),
      model_visible_label: `${repositoryNodeId}.${collection}`,
    },
  });
}

function memoryWriteCandidateEdge(edgeId: string, sourceNodeId: string, repositoryNodeId: string, collection: string): TaskGraphEdge {
  return buildTaskGraphSemanticEdge({
    edgeId,
    relationId: "memory.write_candidate",
    sourceNodeId,
    targetNodeId: repositoryNodeId,
    title: "写入候选记忆",
    parameters: {
      repository_id: repositoryNodeId,
      collection_id: collection,
      record_kind: collectionRecordKind(collection),
      record_key: `${repositoryNodeId}.${collection}.current`,
      source_output_key: `${collection}_memory_candidate`,
    },
  });
}

function memoryCommitEdge(
  edgeId: string,
  sourceNodeId: string,
  repositoryNodeId: string,
  collection: string,
  options: { approvalSourceNodeId?: string } = {},
): TaskGraphEdge {
  return buildTaskGraphSemanticEdge({
    edgeId,
    relationId: "memory.commit_after_review",
    sourceNodeId,
    targetNodeId: repositoryNodeId,
    title: "审核后提交记忆",
    parameters: {
      repository_id: repositoryNodeId,
      collection_id: collection,
      record_kind: collectionRecordKind(collection),
      record_key: `${repositoryNodeId}.${collection}.current`,
      approval_source_node_id: options.approvalSourceNodeId,
      visible_after: "next_clock",
    },
  });
}

function applyTemplateOptions(
  result: TaskGraphTemplateBuildResult,
  input: TaskGraphTemplateBuildInput,
): TaskGraphTemplateBuildResult {
  const taskIntent = String(input.task_intent ?? "").trim();
  const inputMaterialType = input.input_material_type ?? "general";
  const artifactType = input.artifact_type ?? "markdown_report";
  const reviewStrength = input.review_strength ?? "standard";
  const loopCount = Math.max(0, Number(input.loop_count ?? 0) || 0);
  const requireHumanConfirmation = input.require_human_confirmation === true;
  const optionLines = [
    taskIntent ? `当前任务意图：${taskIntent}` : "",
    inputMaterialType !== "general" ? `输入资料类型：${inputMaterialType}` : "",
    `主要产物类型：${artifactType}`,
    `审核强度：${reviewStrength}`,
    requireHumanConfirmation ? "关键阶段需要请求人类确认后再继续。" : "",
  ].filter(Boolean);
  const nodes = result.nodes.map((node) => {
    const metadata = (node.metadata ?? {}) as Record<string, unknown>;
    const agentBound = Boolean(String(node.agent_id ?? "").trim());
    return {
      ...node,
      metadata: {
        ...metadata,
        template_task_intent: taskIntent,
        template_input_material_type: inputMaterialType,
        template_artifact_type: artifactType,
        template_review_strength: reviewStrength,
        template_prompt_context: optionLines,
        agent_binding_source: agentBound && Object.values(input.agent_bindings ?? {}).includes(String(node.agent_id ?? "")) ? "template_parameter" : "template_default",
      },
    };
  });
  return {
    ...result,
    nodes,
    metadata: {
      ...result.metadata,
      editor_foundation: {
        authority: "task_graph.editor_foundation",
        template_id: input.template_id,
        structure_pattern: result.metadata.structure_pattern ?? result.coordination_mode,
        foundation_layers: ["structure", "roles", "memory", "artifacts", "validation"],
        role_slots: nodes
          .filter((node) => String(node.role ?? "") !== "resource" && !String(node.node_type ?? "").includes("repository"))
          .map((node) => ({
            node_id: node.node_id,
            role: String(node.role ?? ""),
            node_type: String(node.node_type ?? "agent_role"),
            prompt_contract: {
              role_identity_required: true,
              responsibility_scope_required: true,
              responsibility_exclusions_required: true,
              definition_of_done_required: true,
            },
          })),
        memory_layers: nodes
          .filter((node) => String(node.role ?? "") === "resource" || String(node.node_type ?? "").includes("repository") || String(node.node_type ?? "") === "issue_ledger")
          .map((node) => ({
            node_id: node.node_id,
            node_type: node.node_type,
            repository_id: asRecord(node.metadata).repository_id,
            collections: asRecord(node.metadata).collections,
            mutable: asRecord(node.metadata).mutable,
          })),
        artifact_layers: [
          ...(
            Array.isArray(asRecord(result.metadata).artifact_layers)
              ? asRecord(result.metadata).artifact_layers as unknown[]
              : []
          ),
          asRecord(result.metadata).artifact_policy,
        ].filter((item) => Object.keys(asRecord(item)).length > 0),
        validation_rules: [
          "role_contract_complete",
          "entry_and_output_nodes_required",
          "memory_repository_has_explicit_collections",
          "memory_commit_has_visibility_and_verdict",
          "review_cannot_write_canon",
        ],
      },
      name_registry: buildTaskGraphNameRegistryPayload({
        graphId: "",
        graphTitle: input.selected_task_title || result.metadata.template_title as string || "任务图",
        nodes,
        phases: Array.isArray(result.metadata.phase_definitions) ? result.metadata.phase_definitions as Array<Record<string, unknown>> : [],
      }).filter((entry) => entry.object_type !== "graph"),
      template_parameters: {
        task_intent: taskIntent,
        input_material_type: inputMaterialType,
        artifact_type: artifactType,
        review_strength: reviewStrength,
        loop_count: loopCount,
        require_human_confirmation: requireHumanConfirmation,
      },
      artifact_policy: {
        ...((result.metadata.artifact_policy ?? {}) as Record<string, unknown>),
        artifact_type: artifactType,
        require_human_confirmation: requireHumanConfirmation,
      },
      loop: loopCount
        ? {
          ...((result.metadata.loop ?? {}) as Record<string, unknown>),
          max_attempts: loopCount,
        }
        : result.metadata.loop,
      review_policy: {
        strength: reviewStrength,
        require_human_confirmation: requireHumanConfirmation,
      },
    },
  };
}

function makeEdge(edgeId: string, from: string, to: string, mode: string, title: string): TaskGraphEdge {
  return {
    edge_id: edgeId,
    from,
    to,
    source_node_id: from,
    target_node_id: to,
    edge_type: "handoff",
    mode,
    policy: mode,
    title,
    payload_contract_id: `${edgeId}.payload`,
    ack_required: true,
    wait_policy: "wait_all_upstream_completed",
    failure_propagation_policy: "fail_downstream",
    result_delivery_policy: "contract_payload_and_refs",
  };
}

function makeContractEdge(
  edgeId: string,
  from: string,
  to: string,
  payloadContractId: string,
  title: string,
  options: Partial<TaskGraphEdge> = {},
): TaskGraphEdge {
  return {
    ...makeEdge(edgeId, from, to, "structured_handoff", title),
    payload_contract_id: payloadContractId,
    working_memory_handoff_policy: {
      mode: "carry_selected",
      carry_shape: "artifact_refs_and_summaries",
    },
    ...options,
  };
}

function metadataFor(phases: Array<{ phase_id: string; title: string; node_ids: string[] }>) {
  return {
    phase_definitions: phases.map((phase, index) => ({
      phase_id: phase.phase_id,
      title: phase.title,
      sequence_index: index + 1,
      exit_policy: { kind: "all_blocking_nodes_complete" },
    })),
    timeline_frames: phases.map((phase, index) => ({
      frame_id: `frame.${phase.phase_id}`,
      frame_type: "phase_frame",
      title: phase.title,
      phase_id: phase.phase_id,
      sequence_index: index + 1,
      node_ids: phase.node_ids,
      edge_ids: [],
    })),
    timeline_blocks: phases.map((phase, index) => ({
      block_id: `block.${phase.phase_id}`,
      block_type: "phase_graph",
      title: phase.title,
      phase_id: phase.phase_id,
      entry_node_id: phase.node_ids[0] ?? "",
      exit_node_id: phase.node_ids[phase.node_ids.length - 1] ?? "",
      handoff_contract_id: `contract.${phase.phase_id}.handoff`,
      visibility_policy: "committed_only",
      version_ref: "template",
      detach_policy: "preserve_version_anchor",
      sequence_index: index + 1,
    })),
    template_generated: true,
  };
}

export function buildTaskGraphTemplateDraft(input: TaskGraphTemplateBuildInput): TaskGraphTemplateBuildResult {
  const mode = input.communication_mode || "structured_handoff";
  const taskTitle = input.selected_task_title || "当前任务";
  const domainId = input.domain_id || "domain.general";
  const node = (item: TemplateNodeInput) => makeNode(item, domainId);
  const finalize = (result: TaskGraphTemplateBuildResult) => applyTemplateOptions(result, input);
  if (input.template_id === "single_agent") {
    const nodes = [
      node({
        node_id: "agent.executor",
        role: "executor",
        title: taskTitle || "Agent 执行者",
        agent_id: agentIdFor(input, "executor", "agent.executor"),
        phase_id: "phase.execute",
        sequence_index: 1,
        role_identity: "你是一名任务执行者。",
        responsibility_scope: "你只负责理解当前任务目标，持续推进执行，并整理可以交付给用户的结果。",
        responsibility_exclusions: "你不负责引入未经确认的新目标，也不负责替其他专业 Agent 做专项分析。",
        definition_of_done: "你必须给出清晰结果、关键依据、未解决问题和下一步建议。",
      }),
    ];
    return finalize({
      nodes,
      edges: [],
      metadata: metadataFor([{ phase_id: "phase.execute", title: "执行", node_ids: ["agent.executor"] }]),
      entry_node_id: "agent.executor",
      output_node_id: "agent.executor",
      coordination_mode: "pipeline",
      participant_agent_ids: [agentIdFor(input, "executor", "agent.executor")],
    });
  }

  if (input.template_id === "multi_parallel_merge") {
    const nodes = [
      node({
        node_id: "agent.review_a",
        role: "reviewer",
        title: "审查者 A",
        agent_id: agentIdFor(input, "reviewer_a", "agent.reviewer.a"),
        phase_id: "phase.parallel_review",
        sequence_index: 1,
        role_identity: "你是一名独立审查员。",
        responsibility_scope: "你只负责从完整性和一致性角度审查当前方案，并列出必须修正的问题。",
        responsibility_exclusions: "你不负责替执行者重写方案，也不负责代表其他审查员做最终裁决。",
        definition_of_done: "你必须输出通过/不通过判断、问题清单和证据说明。",
      }),
      node({
        node_id: "agent.review_b",
        role: "reviewer",
        title: "审查者 B",
        agent_id: agentIdFor(input, "reviewer_b", "agent.reviewer.b"),
        phase_id: "phase.parallel_review",
        sequence_index: 1,
        role_identity: "你是一名风险审查员。",
        responsibility_scope: "你只负责识别执行风险、遗漏条件和可能导致失败的假设。",
        responsibility_exclusions: "你不负责扩展需求，也不负责压制其他审查意见。",
        definition_of_done: "你必须输出风险等级、风险原因和建议处理方式。",
      }),
      node({
        node_id: "agent.merge",
        role: "coordinator",
        title: "协调汇总者",
        agent_id: agentIdFor(input, "coordinator", "agent.coordinator"),
        phase_id: "phase.merge",
        sequence_index: 2,
        role_identity: "你是一名协调汇总者。",
        responsibility_scope: "你只负责合并多个审查意见，给出最终裁决和下一步行动。",
        responsibility_exclusions: "你不负责忽略分歧，也不负责创造审查者没有提出的新事实。",
        definition_of_done: "你必须输出最终结论、采纳意见、未采纳理由和后续任务。",
      }),
    ];
    return finalize({
      nodes,
      edges: [
        makeEdge("edge.review_a.merge", "agent.review_a", "agent.merge", mode, "审查 A 交接给汇总者"),
        makeEdge("edge.review_b.merge", "agent.review_b", "agent.merge", mode, "审查 B 交接给汇总者"),
      ],
      metadata: metadataFor([
        { phase_id: "phase.parallel_review", title: "并行审查", node_ids: ["agent.review_a", "agent.review_b"] },
        { phase_id: "phase.merge", title: "协调汇总", node_ids: ["agent.merge"] },
      ]),
      entry_node_id: "agent.review_a",
      output_node_id: "agent.merge",
      coordination_mode: "parallel_review",
      participant_agent_ids: [
        agentIdFor(input, "reviewer_a", "agent.reviewer.a"),
        agentIdFor(input, "reviewer_b", "agent.reviewer.b"),
        agentIdFor(input, "coordinator", "agent.coordinator"),
      ],
    });
  }

  if (input.template_id === "review_repair_loop") {
    const nodes = [
      node({
        node_id: "agent.executor",
        role: "executor",
        title: "执行者",
        agent_id: agentIdFor(input, "executor", "agent.executor"),
        phase_id: "phase.execute",
        sequence_index: 1,
        role_identity: "你是一名执行者。",
        responsibility_scope: "你只负责根据当前目标产出可审核的工作结果。",
        responsibility_exclusions: "你不负责给自己的结果放行，也不负责绕过审核标准。",
        definition_of_done: "你必须提交结果、依据和需要审核员确认的事项。",
      }),
      node({
        node_id: "agent.reviewer",
        role: "reviewer",
        title: "审核员",
        agent_id: agentIdFor(input, "reviewer", "agent.reviewer"),
        phase_id: "phase.review",
        sequence_index: 2,
        role_identity: "你是一名质量审核员。",
        responsibility_scope: "你只负责判断执行结果是否达到进入下一阶段的标准。",
        responsibility_exclusions: "你不负责替执行者重做结果，也不负责降低质量门。",
        definition_of_done: "你必须给出通过或返修裁决，并说明返修要求。",
        review_gate: true,
      }),
      node({
        node_id: "agent.repair",
        role: "repairer",
        title: "返修者",
        agent_id: agentIdFor(input, "repairer", "agent.repairer"),
        phase_id: "phase.repair",
        sequence_index: 3,
        role_identity: "你是一名返修执行者。",
        responsibility_scope: "你只负责根据审核意见修正结果，并保留修改说明。",
        responsibility_exclusions: "你不负责推翻审核裁决，也不负责新增未经确认的范围。",
        definition_of_done: "你必须提交修订结果、修改点和仍需复核的问题。",
      }),
    ];
    return finalize({
      nodes,
      edges: [
        buildTaskGraphSemanticEdge({
          edgeId: "edge.execute.review",
          relationId: "writing.draft_to_review",
          sourceNodeId: "agent.executor",
          targetNodeId: "agent.reviewer",
          title: "执行结果进入审核门",
          parameters: { artifact_type: "work_result" },
        }),
        buildTaskGraphSemanticEdge({
          edgeId: "edge.review.repair",
          relationId: "writing.review_revise_to_writer",
          sourceNodeId: "agent.reviewer",
          targetNodeId: "agent.repair",
          title: "审核未通过返修",
        }),
        buildTaskGraphSemanticEdge({
          edgeId: "edge.repair.review",
          relationId: "writing.revision_to_review",
          sourceNodeId: "agent.repair",
          targetNodeId: "agent.reviewer",
          title: "返修结果回到审核门",
          parameters: { artifact_type: "revised_work_result" },
        }),
      ],
      metadata: {
        ...metadataFor([
          { phase_id: "phase.execute", title: "执行", node_ids: ["agent.executor"] },
          { phase_id: "phase.review", title: "审核门", node_ids: ["agent.reviewer"] },
          { phase_id: "phase.repair", title: "返修", node_ids: ["agent.repair"] },
        ]),
        loop: { max_attempts: 3, exit_condition: "review_gate_passed" },
      },
      entry_node_id: "agent.executor",
      output_node_id: "agent.reviewer",
      coordination_mode: "review_merge",
      participant_agent_ids: [
        agentIdFor(input, "executor", "agent.executor"),
        agentIdFor(input, "reviewer", "agent.reviewer"),
        agentIdFor(input, "repairer", "agent.repairer"),
      ],
    });
  }

  if (input.template_id === "rag_research_writing") {
    const nodes = [
      node({
        node_id: "agent.rag",
        role: "retriever",
        title: "RAG 检索员",
        agent_id: agentIdFor(input, "rag", "agent:rag_analyst"),
        phase_id: "phase.evidence",
        sequence_index: 1,
        role_identity: "你是一名资料检索员。",
        responsibility_scope: "你只负责围绕任务目标检索相关资料，并返回可追溯的证据片段。",
        responsibility_exclusions: "你不负责写最终报告，也不负责把没有来源的判断当作事实。",
        definition_of_done: "你必须输出资料来源、关键片段、相关性说明和证据缺口。",
      }),
      node({
        node_id: "agent.analyst",
        role: "analyst",
        title: "资料分析员",
        agent_id: agentIdFor(input, "analyst", "agent.evidence_analyst"),
        phase_id: "phase.analysis",
        sequence_index: 2,
        role_identity: "你是一名资料分析员。",
        responsibility_scope: "你只负责分析检索证据之间的关系，提炼稳定结论和不确定点。",
        responsibility_exclusions: "你不负责扩大资料范围，也不负责撰写包装性文案。",
        definition_of_done: "你必须输出结论、证据依据、冲突点和可信度判断。",
      }),
      node({
        node_id: "agent.writer",
        role: "writer",
        title: "写作者",
        agent_id: agentIdFor(input, "writer", "agent.writer"),
        phase_id: "phase.delivery",
        sequence_index: 3,
        role_identity: "你是一名交付写作者。",
        responsibility_scope: "你只负责把已分析的证据组织成清晰、可读、可交付的文本。",
        responsibility_exclusions: "你不负责编造证据，也不负责覆盖分析员标记的不确定性。",
        definition_of_done: "你必须输出结构化正文、引用依据和待确认问题。",
      }),
    ];
    return finalize({
      nodes,
      edges: [
        makeEdge("edge.rag.analysis", "agent.rag", "agent.analyst", mode, "资料证据交接给分析员"),
        makeEdge("edge.analysis.writer", "agent.analyst", "agent.writer", mode, "分析结论交接给写作者"),
      ],
      metadata: metadataFor([
        { phase_id: "phase.evidence", title: "资料检索", node_ids: ["agent.rag"] },
        { phase_id: "phase.analysis", title: "证据分析", node_ids: ["agent.analyst"] },
        { phase_id: "phase.delivery", title: "写作交付", node_ids: ["agent.writer"] },
      ]),
      entry_node_id: "agent.rag",
      output_node_id: "agent.writer",
      coordination_mode: "pipeline",
      participant_agent_ids: [
        agentIdFor(input, "rag", "agent:rag_analyst"),
        agentIdFor(input, "analyst", "agent.evidence_analyst"),
        agentIdFor(input, "writer", "agent.writer"),
      ],
    });
  }

  if (input.template_id === "pdf_table_synthesis") {
    const nodes = [
      node({
        node_id: "agent.pdf",
        role: "pdf_analyst",
        title: "PDF 分析员",
        agent_id: agentIdFor(input, "pdf_analyst", "agent:pdf_reader"),
        phase_id: "phase.extract",
        sequence_index: 1,
        role_identity: "你是一名 PDF 分析员。",
        responsibility_scope: "你只负责阅读指定 PDF，提取章节、页面证据和稳定结论。",
        responsibility_exclusions: "你不负责分析表格数据，也不负责脱离 PDF 证据扩写。",
        definition_of_done: "你必须输出页码或章节定位、关键证据和 PDF 结论。",
      }),
      node({
        node_id: "agent.table",
        role: "table_analyst",
        title: "表格分析员",
        agent_id: agentIdFor(input, "table_analyst", "agent:table_analyst"),
        phase_id: "phase.extract",
        sequence_index: 1,
        role_identity: "你是一名表格分析员。",
        responsibility_scope: "你只负责分析表格、CSV 或从 PDF 中抽取出的结构化数据。",
        responsibility_exclusions: "你不负责解读正文叙述，也不负责把不稳定表格当作可靠数据。",
        definition_of_done: "你必须输出字段解释、关键指标、异常值和可复核的数据依据。",
      }),
      node({
        node_id: "agent.synthesizer",
        role: "summarizer",
        title: "综合汇总员",
        agent_id: agentIdFor(input, "synthesizer", "agent.synthesizer"),
        phase_id: "phase.synthesis",
        sequence_index: 2,
        role_identity: "你是一名综合汇总员。",
        responsibility_scope: "你只负责合并 PDF 证据和表格分析结果，形成一致结论。",
        responsibility_exclusions: "你不负责凭空补充数据，也不负责隐藏 PDF 与表格之间的冲突。",
        definition_of_done: "你必须输出综合结论、证据来源、冲突说明和建议动作。",
      }),
    ];
    return finalize({
      nodes,
      edges: [
        makeEdge("edge.pdf.synthesis", "agent.pdf", "agent.synthesizer", mode, "PDF 证据交接给汇总员"),
        makeEdge("edge.table.synthesis", "agent.table", "agent.synthesizer", mode, "表格分析交接给汇总员"),
      ],
      metadata: metadataFor([
        { phase_id: "phase.extract", title: "资料抽取", node_ids: ["agent.pdf", "agent.table"] },
        { phase_id: "phase.synthesis", title: "综合汇总", node_ids: ["agent.synthesizer"] },
      ]),
      entry_node_id: "agent.pdf",
      output_node_id: "agent.synthesizer",
      coordination_mode: "parallel_review",
      participant_agent_ids: [
        agentIdFor(input, "pdf_analyst", "agent:pdf_reader"),
        agentIdFor(input, "table_analyst", "agent:table_analyst"),
        agentIdFor(input, "synthesizer", "agent.synthesizer"),
      ],
    });
  }

  if (input.template_id === "long_project_cycle") {
    const nodes = [
      node({
        node_id: "agent.planner",
        role: "planner",
        title: "计划员",
        agent_id: agentIdFor(input, "planner", "agent.planner"),
        phase_id: "phase.plan",
        sequence_index: 1,
        role_identity: "你是一名项目计划员。",
        responsibility_scope: "你只负责把长期目标拆成当前周期可以执行的计划。",
        responsibility_exclusions: "你不负责执行任务，也不负责忽略上轮复盘结论。",
        definition_of_done: "你必须输出本周期目标、任务顺序、风险和验收标准。",
      }),
      node({
        node_id: "agent.executor",
        role: "executor",
        title: "执行者",
        agent_id: agentIdFor(input, "executor", "agent.executor"),
        phase_id: "phase.execute",
        sequence_index: 2,
        role_identity: "你是一名项目执行者。",
        responsibility_scope: "你只负责完成本周期计划中的执行项，并记录执行证据。",
        responsibility_exclusions: "你不负责改变项目目标，也不负责跳过风险记录。",
        definition_of_done: "你必须输出完成项、未完成项、证据和阻塞原因。",
      }),
      node({
        node_id: "agent.reviewer",
        role: "reviewer",
        title: "复盘员",
        agent_id: agentIdFor(input, "reviewer", "agent.reviewer"),
        phase_id: "phase.review",
        sequence_index: 3,
        role_identity: "你是一名复盘员。",
        responsibility_scope: "你只负责评估本周期执行结果，提炼下轮需要继承的经验。",
        responsibility_exclusions: "你不负责替执行者补做任务，也不负责掩盖失败原因。",
        definition_of_done: "你必须输出复盘结论、改进项、下轮建议和是否继续循环。",
        input_contract_id: "contract.review.input",
        output_contract_id: "contract.review.verdict",
        memory_writeback_policy: {
          writable_kinds: ["review_issue_record"],
          writable_scopes: ["graph_scope"],
          default_status: "draft",
          default_visibility: "shared_in_graph",
        },
        review_gate: true,
        metadata: {
          review_policy: {
            on_pass: "agent.memory",
            on_fail: "agent.executor",
            verdict_key: "review_verdict",
          },
        },
      }),
      node({
        node_id: "agent.memory",
        role: "memory_steward",
        title: "记忆管理员",
        agent_id: agentIdFor(input, "memory", "agent.memory_manager"),
        phase_id: "phase.memory",
        sequence_index: 4,
        role_identity: "你是一名项目记忆管理员。",
        responsibility_scope: "你只负责把稳定结论、决策和待办写入可复用记忆。",
        responsibility_exclusions: "你不负责写入临时猜测，也不负责覆盖仍有争议的结论。",
        definition_of_done: "你必须输出写入条目、来源、保留期限和下轮读取建议。",
        node_type: "memory_commit",
        input_contract_id: "contract.memory.commit.input",
        output_contract_id: "contract.memory.commit.result",
        memory_writeback_policy: {
          writable_kinds: ["memory_commit_record"],
          writable_scopes: ["graph_scope"],
          default_status: "draft",
          default_visibility: "shared_in_graph",
        },
        metadata: {
          operation: "commit",
          publisher_role: "memory_steward",
          commit_requires_review: true,
        },
      }),
      ...standardMemoryRepositoryNodes({ phaseId: "phase.memory" }),
    ];
    return finalize({
      nodes,
      edges: [
        memoryReadEdge("edge.memory_baseline.plan", "memory.baseline", "agent.planner", "plans"),
        memoryReadEdge("edge.memory_mutable.plan", "memory.mutable", "agent.planner", "progress"),
        memoryReadEdge("edge.issue_ledger.plan", "memory.issue_ledger", "agent.planner", "issues"),
        makeEdge("edge.plan.execute", "agent.planner", "agent.executor", mode, "计划交接给执行者"),
        memoryReadEdge("edge.memory_baseline.execute", "memory.baseline", "agent.executor", "facts"),
        memoryReadEdge("edge.memory_mutable.execute", "memory.mutable", "agent.executor", "continuity"),
        makeEdge("edge.execute.review", "agent.executor", "agent.reviewer", mode, "执行结果交接给复盘员"),
        memoryReadEdge("edge.memory_baseline.review", "memory.baseline", "agent.reviewer", "decisions"),
        memoryReadEdge("edge.memory_mutable.review", "memory.mutable", "agent.reviewer", "state_delta"),
        makeEdge("edge.review.memory", "agent.reviewer", "agent.memory", mode, "复盘结论写入记忆"),
        memoryWriteCandidateEdge("edge.review.issue_ledger.candidate", "agent.reviewer", "memory.issue_ledger", "issues"),
        memoryCommitEdge("edge.review.issue_ledger", "agent.reviewer", "memory.issue_ledger", "issues", { approvalSourceNodeId: "agent.reviewer" }),
        memoryWriteCandidateEdge("edge.memory.mutable.candidate", "agent.memory", "memory.mutable", "progress"),
        memoryCommitEdge("edge.memory.mutable", "agent.memory", "memory.mutable", "progress", { approvalSourceNodeId: "agent.reviewer" }),
        memoryWriteCandidateEdge("edge.memory.artifact_index.candidate", "agent.memory", "memory.artifact_index", "commit_refs"),
        memoryCommitEdge("edge.memory.artifact_index", "agent.memory", "memory.artifact_index", "commit_refs", { approvalSourceNodeId: "agent.reviewer" }),
        {
          ...makeEdge("edge.memory.plan", "agent.memory", "agent.planner", "review_feedback", "记忆反馈到下一轮计划"),
          failure_propagation_policy: "allow_partial",
          metadata: {
            original_artifact_key: "memory_commit_result",
            review_result_key: "review_verdict",
            usage_instruction: "下一轮计划只能读取已提交记忆和本轮复盘裁决，不得把未提交候选当成事实。",
          },
        },
      ],
      metadata: {
        ...metadataFor([
          { phase_id: "phase.plan", title: "计划", node_ids: ["agent.planner"] },
          { phase_id: "phase.execute", title: "执行", node_ids: ["agent.executor"] },
          { phase_id: "phase.review", title: "复盘", node_ids: ["agent.reviewer"] },
          { phase_id: "phase.memory", title: "记忆写回", node_ids: ["agent.memory", "memory.baseline", "memory.mutable", "memory.issue_ledger", "memory.artifact_index"] },
        ]),
        loop: { max_attempts: 12, exit_condition: "project_goal_reached_or_human_stop" },
        artifact_policy: {
          candidate_layer: "artifact.candidates",
          committed_layer: "artifact.commits",
          visibility: "downstream_after_review_and_commit",
        },
      },
      entry_node_id: "agent.planner",
      output_node_id: "agent.memory",
      coordination_mode: "pipeline",
      participant_agent_ids: [
        agentIdFor(input, "planner", "agent.planner"),
        agentIdFor(input, "executor", "agent.executor"),
        agentIdFor(input, "reviewer", "agent.reviewer"),
        agentIdFor(input, "memory", "agent.memory_manager"),
      ],
    });
  }

  const nodes = [
    node({
      node_id: "agent.planner",
      role: "planner",
      title: "规划者",
      agent_id: agentIdFor(input, "planner", "agent.planner"),
      phase_id: "phase.plan",
      sequence_index: 1,
      role_identity: "你是一名任务规划者。",
      responsibility_scope: "你只负责理解任务目标，拆分步骤，并指出后续执行需要的输入。",
      responsibility_exclusions: "你不负责直接完成执行结果，也不负责替审查者做质量裁决。",
      definition_of_done: "你必须输出执行计划、依赖条件和交接给执行者的清单。",
    }),
    node({
      node_id: "agent.executor",
      role: "executor",
      title: "执行者",
      agent_id: agentIdFor(input, "executor", "agent.executor"),
      phase_id: "phase.execute",
      sequence_index: 2,
      role_identity: "你是一名任务执行者。",
      responsibility_scope: "你只负责根据规划执行任务并产出可审查结果。",
      responsibility_exclusions: "你不负责改变规划目标，也不负责替审查者放行结果。",
      definition_of_done: "你必须输出执行结果、依据和需要审查的问题。",
    }),
    node({
      node_id: "agent.reviewer",
      role: "reviewer",
      title: "审查者",
      agent_id: agentIdFor(input, "reviewer", "agent.reviewer"),
      phase_id: "phase.review",
      sequence_index: 3,
      role_identity: "你是一名审查者。",
      responsibility_scope: "你只负责判断执行结果是否满足计划和用户目标。",
      responsibility_exclusions: "你不负责扩写执行结果，也不负责忽视明显风险。",
      definition_of_done: "你必须输出通过/不通过判断、问题清单和修正建议。",
      review_gate: true,
    }),
  ];
  return finalize({
    nodes,
    edges: [
      makeEdge("edge.plan.execute", "agent.planner", "agent.executor", mode, "规划交接给执行者"),
      makeEdge("edge.execute.review", "agent.executor", "agent.reviewer", mode, "执行结果交接给审查者"),
    ],
    metadata: metadataFor([
      { phase_id: "phase.plan", title: "规划", node_ids: ["agent.planner"] },
      { phase_id: "phase.execute", title: "执行", node_ids: ["agent.executor"] },
      { phase_id: "phase.review", title: "审查", node_ids: ["agent.reviewer"] },
    ]),
    entry_node_id: "agent.planner",
    output_node_id: "agent.reviewer",
    coordination_mode: "pipeline",
    participant_agent_ids: [
      agentIdFor(input, "planner", "agent.planner"),
      agentIdFor(input, "executor", "agent.executor"),
      agentIdFor(input, "reviewer", "agent.reviewer"),
    ],
  });
}

