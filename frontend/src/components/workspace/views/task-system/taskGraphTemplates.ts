import type { TaskGraphEdge, TaskGraphNode } from "./taskGraphTypes";

export type TaskGraphTemplateId =
  | "single_agent"
  | "multi_sequence"
  | "multi_parallel_merge"
  | "review_repair_loop"
  | "rag_research_writing"
  | "pdf_table_synthesis"
  | "long_project_cycle"
  | "writing_team_long_novel";

export type TaskGraphTemplateCard = {
  template_id: TaskGraphTemplateId;
  title: string;
  intent: string;
  best_for: string;
  participant_roles: string[];
};

export type TaskGraphTemplateBuildInput = {
  template_id: TaskGraphTemplateId;
  task_family: string;
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
  projection_id?: string;
  input_contract_id?: string;
  output_contract_id?: string;
  dispatch_group?: string;
  execution_mode?: string;
  join_policy?: string;
  loop_policy?: Record<string, unknown>;
  context_visibility_policy?: Record<string, unknown>;
  memory_read_policy?: Record<string, unknown>;
  memory_writeback_policy?: Record<string, unknown>;
  artifact_target?: string;
  metadata?: Record<string, unknown>;
};

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
  {
    template_id: "writing_team_long_novel",
    title: "长篇小说写作团队",
    intent: "从世界观、人物、大纲到双创作者隔离互审、裁判通关和资产入库的连续写作团队。",
    best_for: "长篇小说、多章节连续创作、需要双作者互审、独立裁判和记忆入库的写作项目",
    participant_roles: ["协调者", "设定", "大纲", "人物", "A 初稿", "B 审读", "A 修订", "B 终稿", "裁判", "入库"],
  },
];

function makeNode(input: TemplateNodeInput, taskFamily: string): TaskGraphNode {
  return {
    node_id: input.node_id,
    node_type: input.node_type ?? "agent_role",
    task_id: input.task_id ?? "",
    task_title: input.task_title ?? "",
    task_family: taskFamily,
    agent_id: input.agent_id,
    role: input.role,
    work_posture: input.role,
    projection_id: input.projection_id,
    projection_overlay_id: input.projection_id,
    input_contract_id: input.input_contract_id,
    output_contract_id: input.output_contract_id,
    node_contract_id: input.output_contract_id,
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
    review_gate_policy: input.review_gate ? { is_review_gate: true, gate_kind: "quality_gate" } : undefined,
    loop_policy: input.loop_policy,
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
      ...(input.metadata ?? {}),
    },
  };
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
    return {
      ...node,
      metadata: {
        ...metadata,
        template_task_intent: taskIntent,
        template_input_material_type: inputMaterialType,
        template_artifact_type: artifactType,
        template_review_strength: reviewStrength,
        template_prompt_context: optionLines,
        agent_binding_source: Object.values(input.agent_bindings ?? {}).includes(String(node.agent_id ?? "")) ? "template_parameter" : "template_default",
      },
    };
  });
  return {
    ...result,
    nodes,
    metadata: {
      ...result.metadata,
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
      loop_policy: loopCount
        ? {
          ...((result.metadata.loop_policy ?? {}) as Record<string, unknown>),
          max_attempts: loopCount,
        }
        : result.metadata.loop_policy,
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
    template_generated: true,
  };
}

export function buildTaskGraphTemplateDraft(input: TaskGraphTemplateBuildInput): TaskGraphTemplateBuildResult {
  const mode = input.communication_mode || "structured_handoff";
  const taskTitle = input.selected_task_title || "当前任务";
  const taskFamily = input.task_family || "general";
  const node = (item: TemplateNodeInput) => makeNode(item, taskFamily);
  const finalize = (result: TaskGraphTemplateBuildResult) => applyTemplateOptions(result, input);

  if (input.template_id === "writing_team_long_novel") {
    const taskFamily = "writing_team_long_novel";
    const node = (item: TemplateNodeInput) => makeNode(item, taskFamily);
    const nodes = [
      node({
        node_id: "world_designer_a",
        role: "world_designer_a",
        title: "世界观设计师 A",
        task_id: "task.writing_team.long_novel.world_designer_a",
        agent_id: agentIdFor(input, "world_designer_a", "agent:world_designer_a"),
        projection_id: "projection.writing_team.long_novel.world_designer_a",
        input_contract_id: "UserMessage",
        output_contract_id: "contract.writing_team.long_novel.world_proposal_a",
        context_visibility_policy: { shared_context_policy: "explicit_refs_only", memory_sharing_policy: "isolated_by_default", conversation_memory: "hidden", suppress_conversation_memory: true },
        memory_read_policy: { mode: "authorized_refs_only", topics: ["project_brief", "world_canon_current", "peer_public_world_proposal", "world_review_requirements"], summary_only: true, enabled: true, token_budget: 4000 },
        memory_writeback_policy: { mode: "candidate_only", promotion_requires: "judge_or_memory_commit", capture_artifact_refs: true, writable_kinds: ["intermediate_result"], writable_scopes: ["node_scope"], default_status: "draft", default_visibility: "private_to_node" },
        phase_id: "phase.foundation_world",
        sequence_index: 1,
        role_identity: "你是一名世界观创作者 A。",
        responsibility_scope: "你只基于本轮结构化输入包工作，从结构稳定、规则闭环、长期可写性角度打磨同一个项目的世界观方案。",
        responsibility_exclusions: "你不继承自由会话记忆，不写章节正文，不直接写入世界观记忆库，也不推翻用户硬设定。",
        definition_of_done: "你必须输出本轮世界观方案 A、设定依据、长期写作支撑规则、与已批准 canon 的关系、风险点和待审核问题。",
        execution_mode: "parallel",
        dispatch_group: "phase.foundation_world",
        artifact_target: "world/world_proposal_a.md",
      }),
      node({
        node_id: "world_designer_b",
        role: "world_designer_b",
        title: "世界观设计师 B",
        task_id: "task.writing_team.long_novel.world_designer_b",
        agent_id: agentIdFor(input, "world_designer_b", "agent:world_designer_b"),
        projection_id: "projection.writing_team.long_novel.world_designer_b",
        input_contract_id: "UserMessage",
        output_contract_id: "contract.writing_team.long_novel.world_proposal_b",
        context_visibility_policy: { shared_context_policy: "explicit_refs_only", memory_sharing_policy: "isolated_by_default", conversation_memory: "hidden", suppress_conversation_memory: true },
        memory_read_policy: { mode: "authorized_refs_only", topics: ["project_brief", "world_canon_current", "peer_public_world_proposal", "world_review_requirements"], summary_only: true, enabled: true, token_budget: 4000 },
        memory_writeback_policy: { mode: "candidate_only", promotion_requires: "judge_or_memory_commit", capture_artifact_refs: true, writable_kinds: ["intermediate_result"], writable_scopes: ["node_scope"], default_status: "draft", default_visibility: "private_to_node" },
        phase_id: "phase.foundation_world",
        sequence_index: 1,
        role_identity: "你是一名世界观创作者 B。",
        responsibility_scope: "你只基于本轮结构化输入包工作，从叙事牵引力、想象辨识度、正文可用性角度打磨同一个项目的世界观方案。",
        responsibility_exclusions: "你不继承自由会话记忆，不写章节正文，不直接写入世界观记忆库，也不为了当前章节便利包装世界观升级。",
        definition_of_done: "你必须输出本轮世界观方案 B、与 A 的互补点、可采纳条目、长期风险和待审核问题。",
        execution_mode: "parallel",
        dispatch_group: "phase.foundation_world",
        artifact_target: "world/world_proposal_b.md",
      }),
      node({
        node_id: "world_judge",
        role: "world_judge",
        title: "世界观裁判",
        task_id: "task.writing_team.long_novel.world_judge",
        agent_id: agentIdFor(input, "world_judge", "agent:world_judge"),
        projection_id: "projection.writing_team.long_novel.world_judge",
        input_contract_id: "contract.writing_team.long_novel.world_judge_input",
        output_contract_id: "contract.writing_team.long_novel.world_judgement",
        memory_read_policy: { mode: "authorized_refs_only", topics: ["project_brief", "world_proposal_a", "world_proposal_b", "world_canon_current", "world_review_history", "chapter_progress_world_feedback"], summary_only: true, enabled: true, token_budget: 4000 },
        memory_writeback_policy: { mode: "review_decision_only", promotion_requires: "judge_or_memory_commit", capture_artifact_refs: true, writable_kinds: ["intermediate_result"], writable_scopes: ["node_scope"], default_status: "reviewed", default_visibility: "private_to_node" },
        phase_id: "phase.foundation_world",
        sequence_index: 2,
        role_identity: "你是一名世界观审核员。",
        responsibility_scope: "你必须同时评审方案 A 与方案 B，并结合结构化评审记忆判断本轮是否比上一轮进步。",
        responsibility_exclusions: "你不是第三位世界观创作者，不创造第三套设定，不把未通过内容写入稳定资产。",
        definition_of_done: "你必须输出 pass、revise_current_stage、repair_world、human_review_required 或 fail_closed 裁决，列出证据、已改善项、未解决项、新增退步、允许入库条目和下一轮要求。",
        review_gate: true,
        artifact_target: "reviews/world_judgement.md",
      }),
      node({
        node_id: "memory_commit_world",
        role: "memory_steward",
        title: "世界观入库",
        task_id: "task.writing_team.long_novel.memory_commit_world",
        agent_id: agentIdFor(input, "memory_commit_world", "agent:memory_steward"),
        projection_id: "projection.writing_team.long_novel.memory_commit_world",
        input_contract_id: "contract.writing_team.long_novel.world_judgement",
        output_contract_id: "contract.writing_team.long_novel.memory_commit_world",
        memory_read_policy: { mode: "authorized_refs_only", topics: ["approved_artifact_refs", "world_judgement", "world_canon_version_log", "chapter_progress_world_feedback"], summary_only: false, enabled: true, token_budget: 4000 },
        memory_writeback_policy: { mode: "session_and_durable", promotion_requires: "judge_or_memory_commit", capture_artifact_refs: true, writable_kinds: ["approved_asset", "world_canon"], writable_scopes: ["project_scope"], default_status: "accepted", default_visibility: "project_visible" },
        phase_id: "phase.foundation_world",
        sequence_index: 3,
        role_identity: "你是一名世界观资产管理员。",
        responsibility_scope: "你只负责整理世界观裁判明确允许入库的设定条目、规则、边界和来源引用。",
        responsibility_exclusions: "你不创造新世界观，不补写未通过设定，也不把候选内容写成稳定事实。",
        definition_of_done: "你必须输出世界观入库条目、来源引用、变更摘要和后续节点可读取建议。",
        node_type: "memory_resource",
        metadata: { operation: "commit" },
        artifact_target: "memory/world_commit.md",
      }),
      node({
        node_id: "outline_designer_a",
        role: "outline_designer_a",
        title: "大纲结构师 A",
        task_id: "task.writing_team.long_novel.outline_designer_a",
        agent_id: agentIdFor(input, "outline_designer_a", "agent:outline_designer_a"),
        projection_id: "projection.writing_team.long_novel.outline_designer_a",
        input_contract_id: "contract.writing_team.long_novel.memory_commit_world",
        output_contract_id: "contract.writing_team.long_novel.outline_proposal_a",
        phase_id: "phase.foundation_outline",
        sequence_index: 1,
        role_identity: "你是一名大纲结构师 A。",
        responsibility_scope: "你只负责基于已通过世界观提出全书结构、分卷计划、阶段目标和章节钩子方案 A。",
        responsibility_exclusions: "你不写正文，不直接写入大纲记忆库，也不为了当前章节便利牺牲全书结构。",
        definition_of_done: "你必须输出大纲方案 A、阶段目标、关键冲突、信息释放节奏和待裁判风险。",
        execution_mode: "parallel",
        dispatch_group: "phase.foundation_outline",
        artifact_target: "outline/outline_proposal_a.md",
      }),
      node({
        node_id: "outline_designer_b",
        role: "outline_designer_b",
        title: "大纲结构师 B",
        task_id: "task.writing_team.long_novel.outline_designer_b",
        agent_id: agentIdFor(input, "outline_designer_b", "agent:outline_designer_b"),
        projection_id: "projection.writing_team.long_novel.outline_designer_b",
        input_contract_id: "contract.writing_team.long_novel.memory_commit_world",
        output_contract_id: "contract.writing_team.long_novel.outline_proposal_b",
        phase_id: "phase.foundation_outline",
        sequence_index: 1,
        role_identity: "你是一名大纲结构师 B。",
        responsibility_scope: "你只负责提出大纲方案 B，或对方案 A 形成替代性修订，重点检查章节钩子、人物变化和分卷节奏。",
        responsibility_exclusions: "你不写正文，不直接写入大纲记忆库，也不把抽象口号当成可执行大纲。",
        definition_of_done: "你必须输出大纲方案 B、与方案 A 的差异、可采纳条目、风险点和裁判问题。",
        execution_mode: "parallel",
        dispatch_group: "phase.foundation_outline",
        artifact_target: "outline/outline_proposal_b.md",
      }),
      node({
        node_id: "outline_judge",
        role: "outline_judge",
        title: "大纲裁判",
        task_id: "task.writing_team.long_novel.outline_judge",
        agent_id: agentIdFor(input, "outline_judge", "agent:outline_judge"),
        projection_id: "projection.writing_team.long_novel.outline_judge",
        input_contract_id: "contract.writing_team.long_novel.outline_proposal_b",
        output_contract_id: "contract.writing_team.long_novel.outline_judgement",
        phase_id: "phase.foundation_outline",
        sequence_index: 2,
        role_identity: "你是一名大纲通关裁判。",
        responsibility_scope: "你只负责仲裁大纲方案 A 和方案 B 是否能支撑百万字长篇推进、人物成长和章节生产。",
        responsibility_exclusions: "你不重写大纲，不创造第三套结构，也不为了当前便利降低结构标准。",
        definition_of_done: "你必须输出采纳 A、采纳 B、合并采纳或返修裁决，并列出允许入库条目、拒绝条目和返修目标。",
        review_gate: true,
        artifact_target: "reviews/outline_judgement.md",
      }),
      node({
        node_id: "memory_commit_outline",
        role: "memory_steward",
        title: "大纲入库",
        task_id: "task.writing_team.long_novel.memory_commit_outline",
        agent_id: agentIdFor(input, "memory_commit_outline", "agent:memory_steward"),
        projection_id: "projection.writing_team.long_novel.memory_commit_outline",
        input_contract_id: "contract.writing_team.long_novel.outline_judgement",
        output_contract_id: "contract.writing_team.long_novel.memory_commit_outline",
        phase_id: "phase.foundation_outline",
        sequence_index: 3,
        role_identity: "你是一名大纲资产管理员。",
        responsibility_scope: "你只负责整理大纲裁判明确允许入库的结构、分卷、阶段目标、伏笔和来源引用。",
        responsibility_exclusions: "你不创造新大纲，不补写未通过结构，也不把候选内容写成稳定事实。",
        definition_of_done: "你必须输出大纲入库条目、来源引用、变更摘要和后续节点可读取建议。",
        node_type: "memory_resource",
        metadata: { operation: "commit" },
        artifact_target: "memory/outline_commit.md",
      }),
      node({
        node_id: "character_designer_a",
        role: "character_designer_a",
        title: "人物设计师 A",
        task_id: "task.writing_team.long_novel.character_designer_a",
        agent_id: agentIdFor(input, "character_designer_a", "agent:character_designer_a"),
        projection_id: "projection.writing_team.long_novel.character_designer_a",
        input_contract_id: "contract.writing_team.long_novel.memory_commit_outline",
        output_contract_id: "contract.writing_team.long_novel.character_proposal_a",
        phase_id: "phase.foundation_character",
        sequence_index: 1,
        role_identity: "你是一名人物设计师 A。",
        responsibility_scope: "你只负责提出主角、关键人物、关系网、秘密、能力和人物弧方案 A。",
        responsibility_exclusions: "你不写正文，不直接写入人物记忆库，也不绕开已通过世界观和大纲。",
        definition_of_done: "你必须输出人物方案 A、关系变化、动机、成长线、冲突来源和裁判问题。",
        execution_mode: "parallel",
        dispatch_group: "phase.foundation_character",
        artifact_target: "characters/character_proposal_a.md",
      }),
      node({
        node_id: "character_designer_b",
        role: "character_designer_b",
        title: "人物设计师 B",
        task_id: "task.writing_team.long_novel.character_designer_b",
        agent_id: agentIdFor(input, "character_designer_b", "agent:character_designer_b"),
        projection_id: "projection.writing_team.long_novel.character_designer_b",
        input_contract_id: "contract.writing_team.long_novel.memory_commit_outline",
        output_contract_id: "contract.writing_team.long_novel.character_proposal_b",
        phase_id: "phase.foundation_character",
        sequence_index: 1,
        role_identity: "你是一名人物设计师 B。",
        responsibility_scope: "你只负责提出人物方案 B，或对方案 A 形成替代性修订，重点检查动机、关系变化和成长弧可信度。",
        responsibility_exclusions: "你不写正文，不直接写入人物记忆库，也不把人物便利改动包装成稳定事实。",
        definition_of_done: "你必须输出人物方案 B、与方案 A 的差异、可采纳条目、风险点和裁判问题。",
        execution_mode: "parallel",
        dispatch_group: "phase.foundation_character",
        artifact_target: "characters/character_proposal_b.md",
      }),
      node({
        node_id: "character_judge",
        role: "character_judge",
        title: "人物裁判",
        task_id: "task.writing_team.long_novel.character_judge",
        agent_id: agentIdFor(input, "character_judge", "agent:character_judge"),
        projection_id: "projection.writing_team.long_novel.character_judge",
        input_contract_id: "contract.writing_team.long_novel.character_proposal_b",
        output_contract_id: "contract.writing_team.long_novel.character_judgement",
        phase_id: "phase.foundation_character",
        sequence_index: 2,
        role_identity: "你是一名人物设定通关裁判。",
        responsibility_scope: "你只负责仲裁人物方案 A 和方案 B 是否符合世界观、大纲、人物动机和长篇成长线。",
        responsibility_exclusions: "你不写正文，不创造第三套人物方案，也不把未通过内容放入稳定人物资产。",
        definition_of_done: "你必须输出采纳 A、采纳 B、合并采纳或返修裁决，并列出允许入库条目、拒绝条目和返修目标。",
        review_gate: true,
        artifact_target: "reviews/character_judgement.md",
      }),
      node({
        node_id: "memory_commit_character",
        role: "memory_steward",
        title: "人物入库",
        task_id: "task.writing_team.long_novel.memory_commit_character",
        agent_id: agentIdFor(input, "memory_commit_character", "agent:memory_steward"),
        projection_id: "projection.writing_team.long_novel.memory_commit_character",
        input_contract_id: "contract.writing_team.long_novel.character_judgement",
        output_contract_id: "contract.writing_team.long_novel.memory_commit_character",
        phase_id: "phase.foundation_character",
        sequence_index: 3,
        role_identity: "你是一名人物资产管理员。",
        responsibility_scope: "你只负责整理人物裁判明确允许入库的人物设定、关系、状态、成长节点和来源引用。",
        responsibility_exclusions: "你不创造新人物，不补写未通过人物设定，也不把候选内容写成稳定事实。",
        definition_of_done: "你必须输出人物入库条目、来源引用、变更摘要和后续章节可读取建议。",
        node_type: "memory_resource",
        metadata: { operation: "commit" },
        artifact_target: "memory/character_commit.md",
      }),
      node({
        node_id: "chapter_plan",
        role: "chapter_planner",
        title: "章节细纲",
        task_id: "task.writing_team.long_novel.chapter_plan",
        agent_id: agentIdFor(input, "chapter_plan", "agent:chapter_planner"),
        projection_id: "projection.writing_team.long_novel.chapter_plan",
        input_contract_id: "contract.writing_team.long_novel.memory_commit_character",
        output_contract_id: "contract.writing_team.long_novel.chapter_plan",
        phase_id: "phase.chapter_planning",
        sequence_index: 1,
        role_identity: "你是一名章节规划师。",
        responsibility_scope: "你只负责把通过审核的世界观、大纲和人物设定转成当前章节的目标、场景顺序、冲突和伏笔。",
        responsibility_exclusions: "你不负责写正文，也不负责忽略裁判返修意见。",
        definition_of_done: "你必须输出章节目标、场景列表、人物状态、冲突推进、伏笔和写作约束。",
        artifact_target: "chapters/chapter_plan.md",
      }),
      node({
        node_id: "writer_a_draft",
        role: "writer_a_draft",
        title: "作者 A 初稿",
        task_id: "task.writing_team.long_novel.writer_a_draft",
        agent_id: agentIdFor(input, "writer_a_draft", "agent:novel_writer_a"),
        projection_id: "projection.writing_team.long_novel.writer_a_draft",
        input_contract_id: "contract.writing_team.long_novel.chapter_plan",
        output_contract_id: "contract.writing_team.long_novel.writer_a_draft",
        phase_id: "phase.chapter_production",
        sequence_index: 1,
        role_identity: "你是一名章节初稿作者。",
        responsibility_scope: "你只负责根据已通过的世界观、人物设定、章节细纲和必要前情摘要写当前批次正文初稿。",
        responsibility_exclusions: "你不负责审核自己，不负责替裁判下结论，也不负责把未审核的新设定当成既成事实。",
        definition_of_done: "你必须输出正文初稿、使用的设定依据、候选新增事实、伏笔、人物状态变化和不确定点。",
        artifact_target: "chapters/writer_a_draft.md",
      }),
      node({
        node_id: "writer_b_review",
        role: "writer_b_review",
        title: "作者 B 审读",
        task_id: "task.writing_team.long_novel.writer_b_review",
        agent_id: agentIdFor(input, "writer_b_review", "agent:novel_writer_b"),
        projection_id: "projection.writing_team.long_novel.writer_b_review",
        input_contract_id: "contract.writing_team.long_novel.writer_a_draft",
        output_contract_id: "contract.writing_team.long_novel.writer_b_review",
        phase_id: "phase.chapter_production",
        sequence_index: 2,
        role_identity: "你是一名章节审读作者。",
        responsibility_scope: "你只负责阅读作者 A 的初稿，并根据章节细纲、人物动机、世界观边界和长篇推进目标提出审读意见。",
        responsibility_exclusions: "你不直接写终稿，不替裁判下结论，也不把个人偏好包装成硬性规则。",
        definition_of_done: "你必须输出必须修复项、可保留亮点、节奏问题、设定风险、建议修改方向和证据引用。",
        artifact_target: "reviews/writer_b_review.md",
      }),
      node({
        node_id: "writer_a_revision",
        role: "writer_a_revision",
        title: "作者 A 修订",
        task_id: "task.writing_team.long_novel.writer_a_revision",
        agent_id: agentIdFor(input, "writer_a_revision", "agent:novel_writer_a"),
        projection_id: "projection.writing_team.long_novel.writer_a_revision",
        input_contract_id: "contract.writing_team.long_novel.writer_b_review",
        output_contract_id: "contract.writing_team.long_novel.writer_a_revision",
        phase_id: "phase.chapter_production",
        sequence_index: 3,
        role_identity: "你是一名章节修订作者。",
        responsibility_scope: "你只负责综合作者 B 的审读意见，对自己的初稿进行修订。",
        responsibility_exclusions: "你不负责绕过章节细纲，不负责新增未经说明的重大设定，也不负责替裁判宣布通过。",
        definition_of_done: "你必须输出综合修订稿、采纳意见清单、未采纳意见及理由、仍需裁判检查的问题。",
        artifact_target: "chapters/writer_a_revision.md",
      }),
      node({
        node_id: "writer_b_final_candidate",
        role: "writer_b_final_candidate",
        title: "作者 B 终稿候选",
        task_id: "task.writing_team.long_novel.writer_b_final_candidate",
        agent_id: agentIdFor(input, "writer_b_final_candidate", "agent:novel_writer_b"),
        projection_id: "projection.writing_team.long_novel.writer_b_final_candidate",
        input_contract_id: "contract.writing_team.long_novel.writer_a_revision",
        output_contract_id: "contract.writing_team.long_novel.writer_b_final_candidate",
        phase_id: "phase.chapter_production",
        sequence_index: 4,
        role_identity: "你是一名终稿处理作者。",
        responsibility_scope: "你只负责基于综合修订稿做终稿候选整理，提升连贯性、节奏和可读性。",
        responsibility_exclusions: "你不能替裁判宣布通过，也不能把未解决的问题隐藏起来。",
        definition_of_done: "你必须输出终稿候选、保留问题、候选事实清单和建议裁判重点检查的风险。",
        artifact_target: "chapters/writer_b_final_candidate.md",
      }),
      node({
        node_id: "novel_quality_judge",
        role: "novel_quality_judge",
        title: "独立裁判通关",
        task_id: "task.writing_team.long_novel.novel_quality_judge",
        agent_id: agentIdFor(input, "novel_quality_judge", "agent:novel_quality_judge"),
        projection_id: "projection.writing_team.long_novel.novel_quality_judge",
        input_contract_id: "contract.writing_team.long_novel.writer_b_final_candidate",
        output_contract_id: "contract.writing_team.long_novel.novel_quality_judge",
        phase_id: "phase.review_gate",
        sequence_index: 1,
        role_identity: "你是一名长篇小说通关裁判。",
        responsibility_scope: "你只负责根据授权资产、章节细纲、初稿、审读意见、修订稿和终稿候选进行评分与裁决。",
        responsibility_exclusions: "你不是第三作者，不写正文，不创造第三套设定，也不把未通过内容放行入库。",
        definition_of_done: "你必须输出总分、分项评分、pass、repair_required 或 blocked 裁决、必须修复项、可保留项、偏差类型和是否允许入库；低于 85 分不得入库。",
        review_gate: true,
        artifact_target: "reviews/novel_quality_judge.md",
      }),
      node({
        node_id: "world_deviation_router",
        role: "deviation_router",
        title: "世界观偏差路由",
        task_id: "task.writing_team.long_novel.world_deviation_router",
        agent_id: agentIdFor(input, "world_deviation_router", "agent:novel_quality_judge"),
        projection_id: "projection.writing_team.long_novel.world_deviation_router",
        input_contract_id: "contract.writing_team.long_novel.novel_quality_judge",
        output_contract_id: "contract.writing_team.long_novel.world_deviation_route",
        memory_read_policy: { mode: "authorized_refs_only", topics: ["novel_quality_judge", "world_canon_current", "chapter_fact", "chapter_progress_world_feedback"], summary_only: true, enabled: true, token_budget: 4000 },
        memory_writeback_policy: { mode: "review_decision_only", promotion_requires: "judge_or_memory_commit", capture_artifact_refs: true, writable_kinds: ["intermediate_result"], writable_scopes: ["node_scope"], default_status: "reviewed", default_visibility: "private_to_node" },
        phase_id: "phase.deviation_repair",
        sequence_index: 1,
        role_identity: "你是一名世界观偏差路由员。",
        responsibility_scope: "你只负责根据章节质量裁判、既成正文事实和当前世界观 canon 判断问题是否属于世界观偏差，并整理修正输入。",
        responsibility_exclusions: "你不创造修正方案，不写正文，也不绕过世界观修正裁判。",
        definition_of_done: "你必须输出偏差证据、影响范围、修正目标、可读取资产、是否进入世界观修正，以及必须回到哪个审核节点复审。",
        artifact_target: "repairs/world_deviation_route.md",
      }),
      node({
        node_id: "world_repair_a",
        role: "world_repair_a",
        title: "世界观修正 A",
        task_id: "task.writing_team.long_novel.world_repair_a",
        agent_id: agentIdFor(input, "world_repair_a", "agent:world_designer_a"),
        projection_id: "projection.writing_team.long_novel.world_repair_a",
        input_contract_id: "contract.writing_team.long_novel.world_deviation_route",
        output_contract_id: "contract.writing_team.long_novel.world_repair_a",
        context_visibility_policy: { shared_context_policy: "explicit_refs_only", memory_sharing_policy: "isolated_by_default", conversation_memory: "hidden", suppress_conversation_memory: true },
        memory_read_policy: { mode: "authorized_refs_only", topics: ["world_canon_current", "chapter_fact", "deviation_signal", "world_review_requirements"], summary_only: true, enabled: true, token_budget: 4000 },
        memory_writeback_policy: { mode: "candidate_only", promotion_requires: "judge_or_memory_commit", capture_artifact_refs: true, writable_kinds: ["intermediate_result"], writable_scopes: ["node_scope"], default_status: "draft", default_visibility: "private_to_node" },
        phase_id: "phase.deviation_repair",
        sequence_index: 2,
        role_identity: "你是一名世界观修正创作者 A。",
        responsibility_scope: "你只基于本轮结构化修正输入包工作，从规则闭环、兼容旧 canon、最小变更角度提出世界观修正方案 A。",
        responsibility_exclusions: "你不重写世界观，不为当前章节便利推翻已通过设定，也不直接入库。",
        definition_of_done: "你必须输出修正方案 A、影响范围、风险、来源正文事实、兼容旧 canon 的说明和待审核问题。",
        artifact_target: "repairs/world_repair_a.md",
      }),
      node({
        node_id: "world_repair_b",
        role: "world_repair_b",
        title: "世界观修正 B",
        task_id: "task.writing_team.long_novel.world_repair_b",
        agent_id: agentIdFor(input, "world_repair_b", "agent:world_designer_b"),
        projection_id: "projection.writing_team.long_novel.world_repair_b",
        input_contract_id: "contract.writing_team.long_novel.world_deviation_route",
        output_contract_id: "contract.writing_team.long_novel.world_repair_b",
        context_visibility_policy: { shared_context_policy: "explicit_refs_only", memory_sharing_policy: "isolated_by_default", conversation_memory: "hidden", suppress_conversation_memory: true },
        memory_read_policy: { mode: "authorized_refs_only", topics: ["world_canon_current", "chapter_fact", "deviation_signal", "world_review_requirements"], summary_only: true, enabled: true, token_budget: 4000 },
        memory_writeback_policy: { mode: "candidate_only", promotion_requires: "judge_or_memory_commit", capture_artifact_refs: true, writable_kinds: ["intermediate_result"], writable_scopes: ["node_scope"], default_status: "draft", default_visibility: "private_to_node" },
        phase_id: "phase.deviation_repair",
        sequence_index: 2,
        role_identity: "你是一名世界观修正创作者 B。",
        responsibility_scope: "你只基于本轮结构化修正输入包工作，从正文可用性、叙事牵引力、读者理解成本角度提出世界观修正方案 B。",
        responsibility_exclusions: "你不重写世界观，不直接入库，也不把华丽设定优先于既成事实。",
        definition_of_done: "你必须输出修正方案 B、与 A 的互补点、影响范围、风险、来源正文事实和待审核问题。",
        artifact_target: "repairs/world_repair_b.md",
      }),
      node({
        node_id: "outline_deviation_router",
        role: "deviation_router",
        title: "大纲偏差路由",
        task_id: "task.writing_team.long_novel.outline_deviation_router",
        agent_id: agentIdFor(input, "outline_deviation_router", "agent:novel_quality_judge"),
        projection_id: "projection.writing_team.long_novel.outline_deviation_router",
        input_contract_id: "contract.writing_team.long_novel.novel_quality_judge",
        output_contract_id: "contract.writing_team.long_novel.outline_deviation_route",
        phase_id: "phase.deviation_repair",
        sequence_index: 1,
        role_identity: "你是一名大纲偏差路由员。",
        responsibility_scope: "你只负责根据裁判评分单判断当前问题是否属于大纲结构偏差，并整理修正输入。",
        responsibility_exclusions: "你不创造修正方案，不写正文，也不绕过大纲修正裁判。",
        definition_of_done: "你必须输出偏差证据、修正目标、可读取资产和是否进入大纲修正。",
        artifact_target: "repairs/outline_deviation_route.md",
      }),
      node({
        node_id: "outline_repair_a",
        role: "outline_repair_a",
        title: "大纲修正 A",
        task_id: "task.writing_team.long_novel.outline_repair_a",
        agent_id: agentIdFor(input, "outline_repair_a", "agent:outline_designer_a"),
        projection_id: "projection.writing_team.long_novel.outline_repair_a",
        input_contract_id: "contract.writing_team.long_novel.outline_deviation_route",
        output_contract_id: "contract.writing_team.long_novel.outline_repair_a",
        phase_id: "phase.deviation_repair",
        sequence_index: 2,
        role_identity: "你是一名大纲偏差修正结构师 A。",
        responsibility_scope: "你只负责基于既成正文事实和裁判指出的偏差提出最小结构修正方案 A。",
        responsibility_exclusions: "你不重写全书大纲，不为当前章节便利牺牲长期走向，也不直接入库。",
        definition_of_done: "你必须输出修正方案 A、影响章节、风险、来源事实和待裁判问题。",
        artifact_target: "repairs/outline_repair_a.md",
      }),
      node({
        node_id: "outline_repair_b",
        role: "outline_repair_b",
        title: "大纲修正 B",
        task_id: "task.writing_team.long_novel.outline_repair_b",
        agent_id: agentIdFor(input, "outline_repair_b", "agent:outline_designer_b"),
        projection_id: "projection.writing_team.long_novel.outline_repair_b",
        input_contract_id: "contract.writing_team.long_novel.outline_deviation_route",
        output_contract_id: "contract.writing_team.long_novel.outline_repair_b",
        phase_id: "phase.deviation_repair",
        sequence_index: 2,
        role_identity: "你是一名大纲偏差修正结构师 B。",
        responsibility_scope: "你只负责提出替代性结构修正方案 B，并检查方案 A 是否牺牲长篇走向。",
        responsibility_exclusions: "你不重写全书大纲，不直接入库，也不把当前章节方便性置于全书结构之上。",
        definition_of_done: "你必须输出修正方案 B、与 A 的差异、影响章节、风险和待裁判问题。",
        artifact_target: "repairs/outline_repair_b.md",
      }),
      node({
        node_id: "character_deviation_router",
        role: "deviation_router",
        title: "人物偏差路由",
        task_id: "task.writing_team.long_novel.character_deviation_router",
        agent_id: agentIdFor(input, "character_deviation_router", "agent:novel_quality_judge"),
        projection_id: "projection.writing_team.long_novel.character_deviation_router",
        input_contract_id: "contract.writing_team.long_novel.novel_quality_judge",
        output_contract_id: "contract.writing_team.long_novel.character_deviation_route",
        phase_id: "phase.deviation_repair",
        sequence_index: 1,
        role_identity: "你是一名人物偏差路由员。",
        responsibility_scope: "你只负责根据裁判评分单判断当前问题是否属于人物动机、关系或成长线偏差，并整理修正输入。",
        responsibility_exclusions: "你不创造修正方案，不写正文，也不绕过人物修正裁判。",
        definition_of_done: "你必须输出偏差证据、修正目标、可读取资产和是否进入人物修正。",
        artifact_target: "repairs/character_deviation_route.md",
      }),
      node({
        node_id: "character_repair_a",
        role: "character_repair_a",
        title: "人物修正 A",
        task_id: "task.writing_team.long_novel.character_repair_a",
        agent_id: agentIdFor(input, "character_repair_a", "agent:character_designer_a"),
        projection_id: "projection.writing_team.long_novel.character_repair_a",
        input_contract_id: "contract.writing_team.long_novel.character_deviation_route",
        output_contract_id: "contract.writing_team.long_novel.character_repair_a",
        phase_id: "phase.deviation_repair",
        sequence_index: 2,
        role_identity: "你是一名人物偏差修正设计师 A。",
        responsibility_scope: "你只负责基于既成正文事实和裁判指出的偏差提出最小人物设定修正方案 A。",
        responsibility_exclusions: "你不重写人物线，不直接入库，也不把角色便利改动包装成稳定事实。",
        definition_of_done: "你必须输出修正方案 A、影响人物、关系变化、风险、来源事实和待裁判问题。",
        artifact_target: "repairs/character_repair_a.md",
      }),
      node({
        node_id: "character_repair_b",
        role: "character_repair_b",
        title: "人物修正 B",
        task_id: "task.writing_team.long_novel.character_repair_b",
        agent_id: agentIdFor(input, "character_repair_b", "agent:character_designer_b"),
        projection_id: "projection.writing_team.long_novel.character_repair_b",
        input_contract_id: "contract.writing_team.long_novel.character_deviation_route",
        output_contract_id: "contract.writing_team.long_novel.character_repair_b",
        phase_id: "phase.deviation_repair",
        sequence_index: 2,
        role_identity: "你是一名人物偏差修正设计师 B。",
        responsibility_scope: "你只负责提出替代性人物修正方案 B，并检查方案 A 是否破坏人物动机和成长线。",
        responsibility_exclusions: "你不重写人物线，不直接入库，也不把当前情节刺激性置于人物可信度之上。",
        definition_of_done: "你必须输出修正方案 B、与 A 的差异、影响人物、风险和待裁判问题。",
        artifact_target: "repairs/character_repair_b.md",
      }),
      node({
        node_id: "memory_commit_chapter",
        role: "memory_steward",
        title: "章节入库",
        task_id: "task.writing_team.long_novel.memory_commit_chapter",
        agent_id: agentIdFor(input, "memory_commit_chapter", "agent:memory_steward"),
        projection_id: "projection.writing_team.long_novel.memory_commit_chapter",
        input_contract_id: "contract.writing_team.long_novel.novel_quality_judge",
        output_contract_id: "contract.writing_team.long_novel.memory_commit_chapter",
        phase_id: "phase.memory_commit",
        sequence_index: 1,
        role_identity: "你是一名章节资产管理员。",
        responsibility_scope: "你只负责整理已经通过裁判的终稿、评分单和新增事实。",
        responsibility_exclusions: "你不负责写新剧情、新设定或替裁判补充裁决，也不负责入库未通过审核的内容。",
        definition_of_done: "你必须输出章节摘要、人物状态变化、世界观事实、伏笔、冲突、后续追踪项和来源引用。",
        node_type: "memory_resource",
        metadata: { operation: "commit" },
        artifact_target: "memory/chapter_commit.md",
      }),
      node({
        node_id: "memory_finalize",
        role: "memory_steward",
        title: "工作记忆收尾",
        task_id: "task.writing_team.long_novel.memory_finalize",
        agent_id: agentIdFor(input, "memory_finalize", "agent:memory_steward"),
        projection_id: "projection.writing_team.long_novel.memory_finalize",
        input_contract_id: "contract.writing_team.long_novel.memory_commit_chapter",
        output_contract_id: "contract.writing_team.long_novel.memory_finalize",
        phase_id: "phase.memory_commit",
        sequence_index: 2,
        role_identity: "你是一名工作记忆收尾管理员。",
        responsibility_scope: "你只负责归档本轮任务中的候选、冲突、采纳和丢弃记录，并形成下一轮可读取摘要。",
        responsibility_exclusions: "你不创造新内容，不改变裁判裁决，也不提升未通过候选。",
        definition_of_done: "你必须输出归档摘要、已提交 refs、丢弃 refs、冲突 refs 和下一轮读取建议。",
        node_type: "memory_resource",
        metadata: { operation: "commit" },
        artifact_target: "memory/finalize.md",
      }),
    ];
    return finalize({
      nodes,
      edges: [
        makeContractEdge("edge.world_a.world_judge", "world_designer_a", "world_judge", "contract.writing_team.long_novel.world_proposal_a", "世界观 A 进入裁判"),
        makeContractEdge("edge.world_b.world_judge", "world_designer_b", "world_judge", "contract.writing_team.long_novel.world_proposal_b", "世界观 B 进入裁判"),
        makeContractEdge("edge.world_judge.memory_commit_world", "world_judge", "memory_commit_world", "contract.writing_team.long_novel.world_judgement", "世界观裁判通过后入库"),
        makeContractEdge("edge.memory_world.outline_a", "memory_commit_world", "outline_designer_a", "contract.writing_team.long_novel.memory_commit_world", "世界观资产交接给大纲 A"),
        makeContractEdge("edge.memory_world.outline_b", "memory_commit_world", "outline_designer_b", "contract.writing_team.long_novel.memory_commit_world", "世界观资产交接给大纲 B"),
        makeContractEdge("edge.outline_a.outline_judge", "outline_designer_a", "outline_judge", "contract.writing_team.long_novel.outline_proposal_a", "大纲 A 进入裁判"),
        makeContractEdge("edge.outline_b.outline_judge", "outline_designer_b", "outline_judge", "contract.writing_team.long_novel.outline_proposal_b", "大纲 B 进入裁判"),
        makeContractEdge("edge.outline_judge.memory_commit_outline", "outline_judge", "memory_commit_outline", "contract.writing_team.long_novel.outline_judgement", "大纲裁判通过后入库"),
        makeContractEdge("edge.memory_outline.character_a", "memory_commit_outline", "character_designer_a", "contract.writing_team.long_novel.memory_commit_outline", "大纲资产交接给人物 A"),
        makeContractEdge("edge.memory_outline.character_b", "memory_commit_outline", "character_designer_b", "contract.writing_team.long_novel.memory_commit_outline", "大纲资产交接给人物 B"),
        makeContractEdge("edge.character_a.character_judge", "character_designer_a", "character_judge", "contract.writing_team.long_novel.character_proposal_a", "人物 A 进入裁判"),
        makeContractEdge("edge.character_b.character_judge", "character_designer_b", "character_judge", "contract.writing_team.long_novel.character_proposal_b", "人物 B 进入裁判"),
        makeContractEdge("edge.character_judge.memory_commit_character", "character_judge", "memory_commit_character", "contract.writing_team.long_novel.character_judgement", "人物裁判通过后入库"),
        makeContractEdge("edge.memory_character.chapter_plan", "memory_commit_character", "chapter_plan", "contract.writing_team.long_novel.memory_commit_character", "人物资产交接给章节规划"),
        makeContractEdge("edge.chapter_plan.writer_a_draft", "chapter_plan", "writer_a_draft", "contract.writing_team.long_novel.chapter_plan", "章节细纲交接给作者 A 初稿"),
        makeContractEdge("edge.writer_a_draft.writer_b_review", "writer_a_draft", "writer_b_review", "contract.writing_team.long_novel.writer_a_draft", "A 初稿交接给作者 B 审读"),
        makeContractEdge("edge.writer_b_review.writer_a_revision", "writer_b_review", "writer_a_revision", "contract.writing_team.long_novel.writer_b_review", "B 审读意见交接给作者 A 修订"),
        makeContractEdge("edge.writer_a_revision.writer_b_final_candidate", "writer_a_revision", "writer_b_final_candidate", "contract.writing_team.long_novel.writer_a_revision", "A 综合修订稿交接给作者 B 终稿处理"),
        makeContractEdge("edge.writer_b_final_candidate.novel_quality_judge", "writer_b_final_candidate", "novel_quality_judge", "contract.writing_team.long_novel.writer_b_final_candidate", "终稿候选进入独立裁判"),
        makeContractEdge("edge.novel_quality_judge.writer_a_revision", "novel_quality_judge", "writer_a_revision", "contract.writing_team.long_novel.novel_quality_judge", "章节执行问题返修给作者 A", { failure_propagation_policy: "allow_partial", edge_type: "review_feedback" }),
        makeContractEdge("edge.novel_quality_judge.chapter_plan", "novel_quality_judge", "chapter_plan", "contract.writing_team.long_novel.novel_quality_judge", "章节规划问题返修给章节规划", { failure_propagation_policy: "allow_partial", edge_type: "review_feedback" }),
        makeContractEdge("edge.novel_quality_judge.world_router", "novel_quality_judge", "world_deviation_router", "contract.writing_team.long_novel.novel_quality_judge", "世界观偏差进入路由", { failure_propagation_policy: "allow_partial", edge_type: "review_feedback" }),
        makeContractEdge("edge.world_router.repair_a", "world_deviation_router", "world_repair_a", "contract.writing_team.long_novel.world_deviation_route", "世界观偏差交接给修正 A"),
        makeContractEdge("edge.world_router.repair_b", "world_deviation_router", "world_repair_b", "contract.writing_team.long_novel.world_deviation_route", "世界观偏差交接给修正 B"),
        makeContractEdge("edge.world_repair_a.world_judge", "world_repair_a", "world_judge", "contract.writing_team.long_novel.world_repair_a", "世界观修正 A 进入裁判"),
        makeContractEdge("edge.world_repair_b.world_judge", "world_repair_b", "world_judge", "contract.writing_team.long_novel.world_repair_b", "世界观修正 B 进入裁判"),
        makeContractEdge("edge.novel_quality_judge.outline_router", "novel_quality_judge", "outline_deviation_router", "contract.writing_team.long_novel.novel_quality_judge", "大纲偏差进入路由", { failure_propagation_policy: "allow_partial", edge_type: "review_feedback" }),
        makeContractEdge("edge.outline_router.repair_a", "outline_deviation_router", "outline_repair_a", "contract.writing_team.long_novel.outline_deviation_route", "大纲偏差交接给修正 A"),
        makeContractEdge("edge.outline_router.repair_b", "outline_deviation_router", "outline_repair_b", "contract.writing_team.long_novel.outline_deviation_route", "大纲偏差交接给修正 B"),
        makeContractEdge("edge.outline_repair_a.outline_judge", "outline_repair_a", "outline_judge", "contract.writing_team.long_novel.outline_repair_a", "大纲修正 A 进入裁判"),
        makeContractEdge("edge.outline_repair_b.outline_judge", "outline_repair_b", "outline_judge", "contract.writing_team.long_novel.outline_repair_b", "大纲修正 B 进入裁判"),
        makeContractEdge("edge.novel_quality_judge.character_router", "novel_quality_judge", "character_deviation_router", "contract.writing_team.long_novel.novel_quality_judge", "人物偏差进入路由", { failure_propagation_policy: "allow_partial", edge_type: "review_feedback" }),
        makeContractEdge("edge.character_router.repair_a", "character_deviation_router", "character_repair_a", "contract.writing_team.long_novel.character_deviation_route", "人物偏差交接给修正 A"),
        makeContractEdge("edge.character_router.repair_b", "character_deviation_router", "character_repair_b", "contract.writing_team.long_novel.character_deviation_route", "人物偏差交接给修正 B"),
        makeContractEdge("edge.character_repair_a.character_judge", "character_repair_a", "character_judge", "contract.writing_team.long_novel.character_repair_a", "人物修正 A 进入裁判"),
        makeContractEdge("edge.character_repair_b.character_judge", "character_repair_b", "character_judge", "contract.writing_team.long_novel.character_repair_b", "人物修正 B 进入裁判"),
        makeContractEdge("edge.memory_world.chapter_plan", "memory_commit_world", "chapter_plan", "contract.writing_team.long_novel.memory_commit_world", "世界观修正入库后回章节规划"),
        makeContractEdge("edge.memory_outline.chapter_plan", "memory_commit_outline", "chapter_plan", "contract.writing_team.long_novel.memory_commit_outline", "大纲修正入库后回章节规划"),
        makeContractEdge("edge.memory_character.chapter_plan.repair", "memory_commit_character", "chapter_plan", "contract.writing_team.long_novel.memory_commit_character", "人物修正入库后回章节规划"),
        makeContractEdge("edge.novel_quality_judge.memory_commit_chapter", "novel_quality_judge", "memory_commit_chapter", "contract.writing_team.long_novel.novel_quality_judge", "章节通过后入库"),
        makeContractEdge("edge.memory_commit_chapter.memory_finalize", "memory_commit_chapter", "memory_finalize", "contract.writing_team.long_novel.memory_commit_chapter", "章节入库后工作记忆收尾"),
      ],
      metadata: {
        ...metadataFor([
          { phase_id: "phase.foundation_world", title: "世界观双方案裁判", node_ids: ["world_designer_a", "world_designer_b", "world_judge", "memory_commit_world"] },
          { phase_id: "phase.foundation_outline", title: "大纲双方案裁判", node_ids: ["outline_designer_a", "outline_designer_b", "outline_judge", "memory_commit_outline"] },
          { phase_id: "phase.foundation_character", title: "人物双方案裁判", node_ids: ["character_designer_a", "character_designer_b", "character_judge", "memory_commit_character"] },
          { phase_id: "phase.chapter_planning", title: "章节规划", node_ids: ["chapter_plan"] },
          { phase_id: "phase.chapter_production", title: "双创作者隔离互审", node_ids: ["writer_a_draft", "writer_b_review", "writer_a_revision", "writer_b_final_candidate"] },
          { phase_id: "phase.review_gate", title: "裁判通关", node_ids: ["novel_quality_judge"] },
          { phase_id: "phase.deviation_repair", title: "偏差修正", node_ids: ["world_deviation_router", "world_repair_a", "world_repair_b", "outline_deviation_router", "outline_repair_a", "outline_repair_b", "character_deviation_router", "character_repair_a", "character_repair_b"] },
          { phase_id: "phase.memory_commit", title: "章节入库与收尾", node_ids: ["memory_commit_chapter", "memory_finalize"] },
        ]),
        assembly_namespace: "writing_team_long_novel",
        required_static_assets: ["agents", "projections", "contracts", "specific_tasks", "bindings", "communication_protocol"],
        graph_contract_id: "contract.writing_team.long_novel.memory_finalize",
        default_protocol_id: "protocol.writing_team.long_novel",
        working_memory_policy_profile_id: "wmprofile.writing_team.long_novel",
        context_policy: {
          shared_context_policy: "explicit_refs_only",
          memory_sharing_policy: "isolated_by_default",
        },
        loop_policy: {
          max_attempts: Math.max(0, Number(input.loop_count ?? 3) || 3),
          exit_condition: "memory_finalize_or_human_stop",
        },
        world_phase_policy: {
          stage_order: ["world_designer_a_and_b_parallel", "world_judge_review_gate", "memory_commit_world_on_pass"],
          creator_context: "structured_round_input_without_conversation_memory",
          judge_context: "structured_review_memory_with_version_comparison",
          canon_update_policy: "only_memory_commit_world_may_promote_world_canon",
          progress_feedback_policy: "chapter_progress_may_trigger_world_deviation_router",
          world_adjustment_boundary: "allow_minimal_compatible_world_canon_revision_when_chapter_progress_exposes_structural_deviation",
        },
      },
      entry_node_id: "world_designer_a",
      output_node_id: "memory_finalize",
      coordination_mode: "pipeline",
      participant_agent_ids: [
        agentIdFor(input, "world_designer_a", "agent:world_designer_a"),
        agentIdFor(input, "world_designer_b", "agent:world_designer_b"),
        agentIdFor(input, "world_judge", "agent:world_judge"),
        agentIdFor(input, "memory_commit_world", "agent:memory_steward"),
        agentIdFor(input, "outline_designer_a", "agent:outline_designer_a"),
        agentIdFor(input, "outline_designer_b", "agent:outline_designer_b"),
        agentIdFor(input, "outline_judge", "agent:outline_judge"),
        agentIdFor(input, "memory_commit_outline", "agent:memory_steward"),
        agentIdFor(input, "character_designer_a", "agent:character_designer_a"),
        agentIdFor(input, "character_designer_b", "agent:character_designer_b"),
        agentIdFor(input, "character_judge", "agent:character_judge"),
        agentIdFor(input, "memory_commit_character", "agent:memory_steward"),
        agentIdFor(input, "chapter_plan", "agent:chapter_planner"),
        agentIdFor(input, "writer_a_draft", "agent:novel_writer_a"),
        agentIdFor(input, "writer_b_review", "agent:novel_writer_b"),
        agentIdFor(input, "writer_a_revision", "agent:novel_writer_a"),
        agentIdFor(input, "writer_b_final_candidate", "agent:novel_writer_b"),
        agentIdFor(input, "novel_quality_judge", "agent:novel_quality_judge"),
        agentIdFor(input, "world_deviation_router", "agent:novel_quality_judge"),
        agentIdFor(input, "world_repair_a", "agent:world_designer_a"),
        agentIdFor(input, "world_repair_b", "agent:world_designer_b"),
        agentIdFor(input, "outline_deviation_router", "agent:novel_quality_judge"),
        agentIdFor(input, "outline_repair_a", "agent:outline_designer_a"),
        agentIdFor(input, "outline_repair_b", "agent:outline_designer_b"),
        agentIdFor(input, "character_deviation_router", "agent:novel_quality_judge"),
        agentIdFor(input, "character_repair_a", "agent:character_designer_a"),
        agentIdFor(input, "character_repair_b", "agent:character_designer_b"),
        agentIdFor(input, "memory_commit_chapter", "agent:memory_steward"),
        agentIdFor(input, "memory_finalize", "agent:memory_steward"),
      ],
    });
  }

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
        makeEdge("edge.execute.review", "agent.executor", "agent.reviewer", mode, "执行结果进入审核门"),
        { ...makeEdge("edge.review.repair", "agent.reviewer", "agent.repair", "review_feedback", "审核未通过返修"), failure_propagation_policy: "allow_partial" },
        makeEdge("edge.repair.review", "agent.repair", "agent.reviewer", mode, "返修结果回到审核门"),
      ],
      metadata: {
        ...metadataFor([
          { phase_id: "phase.execute", title: "执行", node_ids: ["agent.executor"] },
          { phase_id: "phase.review", title: "审核门", node_ids: ["agent.reviewer"] },
          { phase_id: "phase.repair", title: "返修", node_ids: ["agent.repair"] },
        ]),
        loop_policy: { max_attempts: 3, exit_condition: "review_gate_passed" },
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
        review_gate: true,
      }),
      node({
        node_id: "agent.memory",
        role: "memory",
        title: "记忆管理员",
        agent_id: agentIdFor(input, "memory", "agent.memory_manager"),
        phase_id: "phase.memory",
        sequence_index: 4,
        role_identity: "你是一名项目记忆管理员。",
        responsibility_scope: "你只负责把稳定结论、决策和待办写入可复用记忆。",
        responsibility_exclusions: "你不负责写入临时猜测，也不负责覆盖仍有争议的结论。",
        definition_of_done: "你必须输出写入条目、来源、保留期限和下轮读取建议。",
        node_type: "memory_resource",
        metadata: { operation: "commit" },
      }),
    ];
    return finalize({
      nodes,
      edges: [
        makeEdge("edge.plan.execute", "agent.planner", "agent.executor", mode, "计划交接给执行者"),
        makeEdge("edge.execute.review", "agent.executor", "agent.reviewer", mode, "执行结果交接给复盘员"),
        makeEdge("edge.review.memory", "agent.reviewer", "agent.memory", mode, "复盘结论写入记忆"),
        { ...makeEdge("edge.memory.plan", "agent.memory", "agent.planner", "review_feedback", "记忆反馈到下一轮计划"), failure_propagation_policy: "allow_partial" },
      ],
      metadata: {
        ...metadataFor([
          { phase_id: "phase.plan", title: "计划", node_ids: ["agent.planner"] },
          { phase_id: "phase.execute", title: "执行", node_ids: ["agent.executor"] },
          { phase_id: "phase.review", title: "复盘", node_ids: ["agent.reviewer"] },
          { phase_id: "phase.memory", title: "记忆写回", node_ids: ["agent.memory"] },
        ]),
        loop_policy: { max_attempts: 12, exit_condition: "project_goal_reached_or_human_stop" },
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
