"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Network,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  Pencil,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  coordinationSubtaskRefs,
  graphEdgeId,
  graphEdgeSource,
  graphEdgeTarget,
  graphNodeTaskId,
} from "@/components/workspace/views/task-system/CoordinationEditorWorkbench";
import { ContractLibraryPanel, contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import { ContractOverviewPanel } from "@/components/workspace/views/task-system/ContractOverviewPanel";
import { TaskContractPanel } from "@/components/workspace/views/task-system/TaskContractPanel";
import { TaskAssemblyPreflightPanel } from "@/components/workspace/views/task-system/TaskAssemblyPreflightPanel";
import { TaskGraphWorkbench } from "@/components/workspace/views/task-system/TaskGraphWorkbench";
import { TaskRunLoopWorkbenchPanel } from "@/components/workspace/views/task-system/TaskRunLoopWorkbenchPanel";
import { buildTaskGraphDraft } from "@/components/workspace/views/task-system/taskGraphDraft";
import {
  TaskSystemDomainTaskSelectField as DomainTaskSelectField,
  TaskSystemField as Field,
  TaskSystemMultiSelectField as MultiSelectField,
  TaskSystemSelectField as SelectField,
  TaskSystemToolbarButton as ToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import {
  deleteTaskSystemDomain,
  deleteTaskSystemSpecificRecord,
  getOrchestrationAgents,
  getSoulProjectionCards,
  getTaskSystemNextIds,
  getTaskSystemOverview,
  deleteTaskSystemContract,
  upsertTaskSystemCommunicationProtocol,
  upsertTaskSystemCoordinationTask,
  upsertTaskSystemContract,
  upsertTaskSystemDomain,
  upsertTaskSystemEntryPolicy,
  upsertTaskSystemExecutionPolicy,
  upsertTaskSystemFlowContractBinding,
  upsertTaskSystemMemoryRequestProfile,
  upsertTaskSystemProjectionBinding,
  upsertTaskSystemSpecificRecord,
  upsertTaskSystemTaskGraph,
  upsertTaskSystemTopologyTemplate,
  upsertTaskWorkflow,
  type ConversationEntryPolicy,
  type ContractSpec,
  type CoordinationGraphSpec,
  type CoordinationTask,
  type OrchestrationAgentRuntimeCatalog,
  type OrchestrationAgentRuntimeProfile,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type SpecificTaskRecord,
  type TaskCommunicationProtocol,
  type TaskContractDescriptor,
  type TaskDomainRecord,
  type TaskExecutionPolicy,
  type TaskFlowContractBinding,
  type TaskGraphRecord,
  type TaskMemoryRequestProfile,
  type TaskProjectionBinding,
  type TaskSystemOverview,
  type TaskWorkflowRecord,
  type TopologyTemplate,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

type TaskLayer = "management" | "editor";
type TaskConfigPanel = "definition" | "contracts" | "package" | "preflight" | "runloop";
type ContractPanel = "library" | "templates" | "bindings" | "manifest";
type PackagePanel = "templates" | "draft" | "pipeline" | "prerequisites";
type PackagePrerequisiteStatus = "ready" | "missing" | "partial";

type WorkflowDraft = TaskWorkflowRecord & {
  compatible_projection_ids_text: string;
  visible_skill_ids_text: string;
  steps_text: string;
  stop_conditions_text: string;
  required_evidence_refs_text: string;
};

type CoordinationDraft = CoordinationTask & {
  stop_conditions_text: string;
};

type TopologyDraft = TopologyTemplate & {
  nodes_text: string;
  edges_text: string;
  handoff_rules_text: string;
};

type ProtocolDraft = TaskCommunicationProtocol & {
  message_types_text: string;
  payload_contracts_text: string;
  signal_rules_text: string;
  handoff_rules_text: string;
};

type DomainRecord = {
  domain_id: string;
  title: string;
  task_family: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  metadata?: Record<string, unknown>;
  task_modes: string[];
  tasks: SpecificTaskRecord[];
  entry_policy: ConversationEntryPolicy | null;
};

type PackageSaveStep = {
  id: string;
  label: string;
  status: "pending" | "success" | "error";
  detail: string;
};

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  return String(value);
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
}

function dictOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function slugFromTitle(value: string, fallback = "custom") {
  const ascii = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_\-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return ascii || fallback;
}

type ContractView = {
  key: string;
  title: string;
  kind: string;
  usage: string;
  source: string;
  raw: string;
};

const CONTRACT_KIND_LABELS: Record<string, string> = {
  input: "输入契约",
  output: "输出契约",
  flow: "流程契约",
  payload: "通信载荷契约",
};

function parseJsonObject(value: string, label: string) {
  const parsed = JSON.parse(value || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

function parseJsonList(value: string, label: string) {
  const parsed = JSON.parse(value || "[]");
  if (!Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 数组`);
  }
  return parsed.filter((item) => item && typeof item === "object") as Array<Record<string, unknown>>;
}

function jsonError(value: string, label: string, kind: "object" | "array") {
  try {
    kind === "object" ? parseJsonObject(value, label) : parseJsonList(value, label);
    return "";
  } catch (error) {
    return error instanceof Error ? error.message : `${label} 解析失败`;
  }
}

function stepsFromText(value: string) {
  return splitList(value).map((line, index) => {
    const [stepId, title] = line.split("|").map((part) => part.trim());
    return { step_id: stepId || `step_${index + 1}`, title: title || stepId || `步骤 ${index + 1}` };
  });
}

function stepsToText(steps: Array<Record<string, unknown>> = []) {
  return steps.map((step) => `${text(step.step_id, "")} | ${text(step.title, "")}`).join("\n");
}

function emptyEntryPolicy(workflowId = "", projectionId = ""): ConversationEntryPolicy {
  return {
    profile_id: "general.conversation.default",
    entry_policy_id: "general.conversation.default",
    title: "主会话入口识别",
    default_workflow_id: workflowId,
    default_projection_id: projectionId,
    input_contract_id: "UserMessage",
    output_contract_id: "AssistantFinalAnswer",
    conversation_entry_policy: "user_dialogue_to_main_agent",
    enabled: true,
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptyTaskDomain(index = 0): TaskDomainRecord {
  return {
    domain_id: "domain.custom",
    task_family: "custom",
    title: "新任务域",
    description: "",
    enabled: true,
    sort_order: 100 + index * 10,
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptySpecificTaskRecord(workflowId = "", flowId = ""): SpecificTaskRecord {
  return {
    task_id: "task.dev.new_task",
    task_title: "新特定任务",
    task_family: "development",
    task_mode: "bounded_patch",
    description: "",
    input_contract_id: "WorkspaceTaskInput",
    output_contract_id: "AssistantFinalAnswer",
    acceptance_profile_id: "",
    default_flow_contract_id: flowId || "flow.dev.bounded_patch",
    default_workflow_id: workflowId || "workflow.dev.bounded_patch",
    default_projection_policy: "workflow_compatible_or_task_default",
    task_policy: {
      safety_policy: {
        safety_class: "S2_bounded",
        write_mode: "scoped",
        verification_mode: "artifact_or_trace",
      },
      task_structure: {
        execution_chain_type: "single_agent_chain",
        trigger_signals: [],
      },
    },
    enabled: true,
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptyWorkflow(taskMode = "bounded_patch"): WorkflowDraft {
  return {
    workflow_id: "workflow.dev.bounded_patch",
    title: "默认执行流程",
    task_mode: taskMode,
    compatible_projection_ids: [],
    visible_skill_ids: [],
    steps: [],
    input_boundary: "",
    output_boundary: "",
    stop_conditions: [],
    required_evidence_refs: [],
    output_contract_id: "AssistantFinalAnswer",
    prompt: "",
    enabled: true,
    metadata: { managed_by: "task_domain_console" },
    compatible_projection_ids_text: "",
    visible_skill_ids_text: "",
    steps_text: "",
    stop_conditions_text: "",
    required_evidence_refs_text: "",
  };
}

function workflowDraftFrom(workflow?: TaskWorkflowRecord | null, taskMode = "bounded_patch"): WorkflowDraft {
  const base = workflow ?? emptyWorkflow(taskMode);
  return {
    ...base,
    compatible_projection_ids: base.compatible_projection_ids ?? [],
    visible_skill_ids: base.visible_skill_ids ?? [],
    steps: base.steps ?? [],
    stop_conditions: base.stop_conditions ?? [],
    required_evidence_refs: base.required_evidence_refs ?? [],
    metadata: base.metadata ?? {},
    compatible_projection_ids_text: listText(base.compatible_projection_ids ?? []),
    visible_skill_ids_text: listText(base.visible_skill_ids ?? []),
    steps_text: stepsToText(base.steps ?? []),
    stop_conditions_text: listText(base.stop_conditions ?? []),
    required_evidence_refs_text: listText(base.required_evidence_refs ?? []),
  };
}

function emptyProjectionBinding(taskId = "", projectionId = ""): TaskProjectionBinding {
  return {
    task_id: taskId,
    projection_selection_mode: "task_default",
    allowed_projection_ids: projectionId ? [projectionId] : [],
    default_projection_id: projectionId,
    projection_required: false,
    notes: "",
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptyFlowBinding(taskId = "", flowId = ""): TaskFlowContractBinding {
  return {
    task_id: taskId,
    flow_contract_id: flowId,
    override_policy: "task_default",
    verification_gate_profile: "",
    fallback_policy: "fail_closed",
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptyExecutionPolicy(taskId = ""): TaskExecutionPolicy {
  return {
    task_id: taskId,
    execution_chain_type: "single_agent_chain",
    runtime_agent_selection_policy: "orchestration_default",
    default_agent_id: "agent:0",
    task_level: "standard",
    task_privilege: "bounded",
    allowed_agent_categories: ["main_agent"],
    allow_worker_agent_spawn: false,
    worker_agent_blueprint_id: "",
    worker_agent_naming_rule: "",
    notes: "",
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptyMemoryProfile(taskId = ""): TaskMemoryRequestProfile {
  return {
    task_id: taskId,
    requested_memory_layers: [],
    requested_topics: [],
    memory_priority: "normal",
    writeback_policy: "task_default",
    allow_long_term_memory: false,
    working_memory_policy_profile_id: "",
    working_memory_policy: {
      enabled: false,
      default_scope: "node_scope",
      default_visibility: "private_to_node",
      finalize_requires_human_review: true,
      promotion_requires_human_review: true,
    },
    allow_working_memory: false,
    allow_dynamic_working_memory_read: false,
    working_memory_default_scope: "node_scope",
    working_memory_default_visibility: "private_to_node",
    memory_scope_hint: "",
    metadata: { managed_by: "task_domain_console" },
  };
}

function emptyCoordination(templateId = "", protocolId = "", taskFamily = "", domainId = ""): CoordinationDraft {
  return {
    coordination_task_id: "coord.dev.task",
    title: "新协调任务",
    coordination_mode: "review_merge",
    coordinator_agent_id: "agent:0",
    task_family: taskFamily,
    domain_id: domainId,
    agent_group_id: "",
    participant_agent_ids: [],
    topology_template_id: templateId,
    shared_context_policy: "explicit_refs_only",
    memory_sharing_policy: "isolated_by_default",
    handoff_policy: "filtered_handoff",
    conflict_resolution_policy: "coordinator_review",
    output_merge_policy: "coordinator_final_merge",
    stop_conditions: [],
    subtask_refs: [],
    graph_nodes: [{ node_id: "coordinator", agent_id: "agent:0", role: "coordinator" }],
    graph_edges: [],
    communication_modes: ["structured_handoff"],
    enabled: false,
    metadata: { managed_by: "task_domain_console", protocol_id: protocolId },
    stop_conditions_text: "",
  };
}

function coordinationDraftFrom(task?: CoordinationTask | null): CoordinationDraft {
  const base = task ?? emptyCoordination();
  return {
    ...base,
    participant_agent_ids: base.participant_agent_ids ?? [],
    stop_conditions: base.stop_conditions ?? [],
    subtask_refs: base.subtask_refs ?? [],
    graph_nodes: base.graph_nodes?.length ? base.graph_nodes : [{ node_id: "coordinator", agent_id: base.coordinator_agent_id || "agent:0", role: "coordinator" }],
    graph_edges: base.graph_edges ?? [],
    communication_modes: base.communication_modes?.length ? base.communication_modes : ["structured_handoff"],
    metadata: base.metadata ?? {},
    stop_conditions_text: listText(base.stop_conditions ?? []),
  };
}

function emptyTopology(): TopologyDraft {
  return {
    template_id: "topology.dev.task",
    title: "新协调拓扑",
    nodes: [],
    edges: [],
    handoff_rules: [],
    join_policy: "explicit_join",
    failure_policy: "fail_closed",
    terminal_policy: "coordinator_terminal",
    enabled: false,
    metadata: { managed_by: "task_domain_console" },
    nodes_text: "[]",
    edges_text: "[]",
    handoff_rules_text: "[]",
  };
}

function topologyDraftFrom(template?: TopologyTemplate | null): TopologyDraft {
  const base = template ?? emptyTopology();
  return {
    ...base,
    nodes: base.nodes ?? [],
    edges: base.edges ?? [],
    handoff_rules: base.handoff_rules ?? [],
    nodes_text: JSON.stringify(base.nodes ?? [], null, 2),
    edges_text: JSON.stringify(base.edges ?? [], null, 2),
    handoff_rules_text: JSON.stringify(base.handoff_rules ?? [], null, 2),
  };
}

function emptyProtocol(): ProtocolDraft {
  return {
    protocol_id: "protocol.dev.task",
    title: "新通信协议",
    message_types: [],
    payload_contracts: [],
    signal_rules: [],
    handoff_rules: [],
    ack_policy: "explicit_ack",
    timeout_policy: "fail_closed",
    error_signal_policy: "raise_to_coordinator",
    enabled: false,
    metadata: { managed_by: "task_domain_console" },
    message_types_text: "",
    payload_contracts_text: "",
    signal_rules_text: "",
    handoff_rules_text: "",
  };
}

function protocolDraftFrom(protocol?: TaskCommunicationProtocol | null): ProtocolDraft {
  const base = protocol ?? emptyProtocol();
  return {
    ...base,
    message_types: base.message_types ?? [],
    payload_contracts: base.payload_contracts ?? [],
    signal_rules: base.signal_rules ?? [],
    handoff_rules: base.handoff_rules ?? [],
    metadata: base.metadata ?? {},
    message_types_text: listText(base.message_types ?? []),
    payload_contracts_text: listText(base.payload_contracts ?? []),
    signal_rules_text: listText(base.signal_rules ?? []),
    handoff_rules_text: listText(base.handoff_rules ?? []),
  };
}

function domainTitle(family: string) {
  const labels: Record<string, string> = {
    development: "开发任务域",
    health: "健康任务域",
    writing: "写作任务域",
    general: "通用入口域",
    capability: "能力调用域",
  };
  return labels[family] ?? `${family || "未分类"} 任务域`;
}

function displayId(value: unknown, fallback = "未配置") {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const labels: Record<string, string> = {
    "single_agent_chain": "单 Agent 链",
    "coordination_chain": "协调任务",
    "orchestration_default": "编排默认选择",
    "task_default": "任务默认",
    "workflow_compatible_or_task_default": "流程兼容优先",
    "standard": "标准级",
    "bounded": "受限权限",
    "main_agent": "主 Agent",
    "system_management_agent": "系统管理 Agent",
    "worker_sub_agent": "子 Agent",
    "development": "开发任务域",
    "writing": "写作任务域",
    "health": "健康任务域",
    "general": "通用入口域",
    "capability": "能力调用域",
    "bounded_patch": "受限补丁",
    "light_web_game": "轻量网页小游戏",
    "arcade_game_bundle": "复合小游戏包",
    "issue_triage": "问题分诊",
    "trace_analysis": "Trace 分析",
    "case_draft": "案例草案",
    "fix_verification": "修复验证",
    "AssistantFinalAnswer": "最终回答",
    "LightWebGameResult": "网页游戏产物",
    "UserMessage": "用户消息",
    "WorkspaceTaskInput": "工作区任务输入",
    "explicit_ack": "显式确认",
    "fail_closed": "失败即关闭",
    "raise_to_coordinator": "上报协调者",
    "explicit_join": "显式汇合",
    "coordinator_terminal": "协调者终止",
    "filtered_handoff": "过滤交接",
    "coordinator_review": "协调者审查",
    "coordinator_final_merge": "协调者最终合并",
    "explicit_refs_only": "仅显式引用",
    "isolated_by_default": "默认隔离",
    "normal": "普通优先级",
  };
  if (labels[raw]) return `${labels[raw]} · ${raw}`;
  const prefixLabels: Array<[string, string]> = [
    ["task.writing.", "写作任务"],
    ["task.dev.", "开发任务"],
    ["task.health.", "健康任务"],
    ["coord.writing.", "写作协调任务"],
    ["coord.dev.", "开发协调任务"],
    ["workflow.writing.", "写作执行流程"],
    ["workflow.dev.", "开发执行流程"],
    ["topology.writing.", "写作拓扑"],
    ["topology.dev.", "开发拓扑"],
    ["protocol.writing.", "写作协议"],
    ["protocol.dev.", "开发协议"],
    ["flow.writing.", "写作流程契约"],
    ["flow.dev.", "开发流程契约"],
    ["template.writing.", "写作模板"],
    ["domain.", "任务域"],
    ["agent:", "Agent"],
    ["group.", "Agent 组"],
    ["op.", "操作权限"],
  ];
  const matched = prefixLabels.find(([prefix]) => raw.startsWith(prefix));
  return matched ? `${matched[1]} · ${raw}` : raw;
}

const DEFAULT_PROJECTION_POLICY_CHOICES = ["workflow_compatible_or_task_default", "task_default"];
const PROJECTION_SELECTION_MODE_CHOICES = ["task_default"];
const FLOW_OVERRIDE_POLICY_CHOICES = ["task_default"];
const FLOW_FALLBACK_POLICY_CHOICES = ["fail_closed"];
const RUNTIME_SELECTION_POLICY_CHOICES = ["orchestration_default"];
const COMMON_CONTRACT_CHOICES = ["UserMessage", "WorkspaceTaskInput", "AssistantFinalAnswer", "LightWebGameResult"];
const COORDINATION_MODE_CHOICES = ["review_merge", "pipeline", "parallel_review"];
const GRAPH_EDGE_MODE_CHOICES = ["structured_handoff", "review_feedback", "draft_request", "audit_request", "merge_signal"];
const CONTEXT_POLICY_CHOICES = ["explicit_refs_only", "shared_task_context"];
const MEMORY_SHARING_POLICY_CHOICES = ["isolated_by_default", "shared_readonly"];
const HANDOFF_POLICY_CHOICES = ["filtered_handoff", "direct_handoff"];
const CONFLICT_POLICY_CHOICES = ["coordinator_review", "majority_vote"];
const MERGE_POLICY_CHOICES = ["coordinator_final_merge", "ordered_append", "section_merge"];

function novelContract(
  contractId: string,
  title: string,
  kind: string,
  outputFields: Array<Partial<ContractField> & { field_id: string; title_zh: string }>,
  description: string,
): ContractSpec {
  return {
    contract_id: contractId,
    title_zh: title,
    title_en: contractId.split(".").slice(-1)[0],
    contract_kind: kind,
    description,
    input_fields: [],
    output_fields: outputFields.map((field) => ({
      field_id: field.field_id,
      title_zh: field.title_zh,
      field_type: field.field_type || "string",
      required: field.required ?? true,
      description: field.description || "",
      default_value: field.default_value,
      schema: field.schema || {},
      source_hint: field.source_hint || "upstream_output",
      visibility: field.visibility || "model_visible",
    })),
    artifact_requirements: [],
    acceptance_rules: outputFields.filter((field) => field.required !== false).map((field) => ({
      rule_id: `${field.field_id}_present`,
      title_zh: `${field.title_zh}必须存在`,
      rule_type: "required_field_present",
      severity: "error",
      target_field: field.field_id,
      criteria: `${field.title_zh}不能为空。`,
      config: {},
    })),
    runtime_requirements: [],
    context_visibility_policy: {
      main_session_history: "summary",
      upstream_outputs: "summary",
      sibling_nodes: "status_only",
      artifact_access: "refs_only",
      memory_scopes: [],
      model_visible_sections: ["task", "runtime_contracts", "working_memory"],
      hidden_sections: [],
      notes: "",
    },
    handoff_policy: {
      handoff_mode: "structured_handoff",
      include_artifact_refs: true,
      include_raw_messages: false,
      ack_required: true,
      timeout_policy: "fail_closed",
    },
    failure_policy: {
      failure_mode: "fail_closed",
      retry_allowed: true,
      retry_limit: 1,
      escalate_to: "coordinator",
      fallback_contract_id: "contract.error_report.basic",
    },
    human_gate_policy: {
      required: false,
      gate_type: "none",
      reviewer_role: "",
      decision_contract_id: "",
    },
    allowed_agent_kinds: ["worker_sub_agent"],
    allowed_runtime_lanes: [],
    version: "1.0.0",
    enabled: true,
    metadata: { managed_by: "task_package_wizard", package_template: "longform_novel_writing" },
  };
}

function buildLongformNovelContracts(): ContractSpec[] {
  return [
    novelContract("contract.novel.project_brief", "长篇小说项目简报", "global_task", [
      { field_id: "title", title_zh: "作品标题", required: false },
      { field_id: "genre", title_zh: "题材类型", required: true },
      { field_id: "target_length", title_zh: "目标篇幅", required: true },
      { field_id: "core_premise", title_zh: "核心设定", required: true },
      { field_id: "constraints", title_zh: "创作约束", field_type: "array", required: false },
    ], "长篇小说任务的项目级输入边界。"),
    novelContract("contract.novel.project_plan", "长篇小说生产计划", "workflow", [
      { field_id: "volume_plan", title_zh: "分卷计划", field_type: "array" },
      { field_id: "chapter_count", title_zh: "章节数量", field_type: "number" },
      { field_id: "quality_gates", title_zh: "质量门控", field_type: "array" },
    ], "由 Showrunner 输出的整体生产计划。"),
    novelContract("contract.novel.world_bible_delta", "世界观设定增量", "node_execution", [
      { field_id: "world_rules", title_zh: "世界规则", field_type: "array" },
      { field_id: "setting_delta", title_zh: "设定变更", field_type: "array" },
      { field_id: "conflict_risks", title_zh: "冲突风险", field_type: "array", required: false },
    ], "故事架构阶段输出的世界观设定增量。"),
    novelContract("contract.novel.volume_outline", "分卷与章节大纲", "node_execution", [
      { field_id: "volume_outline", title_zh: "分卷大纲", field_type: "array" },
      { field_id: "chapter_briefs", title_zh: "章节简报", field_type: "array" },
      { field_id: "foreshadow_track", title_zh: "伏笔账本", field_type: "array", required: false },
    ], "故事架构阶段输出的分卷、章节和伏笔规划。"),
    novelContract("contract.novel.character_delta", "角色连续性增量", "node_execution", [
      { field_id: "character_states", title_zh: "角色状态", field_type: "array" },
      { field_id: "relationship_delta", title_zh: "关系变化", field_type: "array" },
      { field_id: "arc_risks", title_zh: "人物弧风险", field_type: "array", required: false },
    ], "故事架构与章节审校阶段输出的角色状态增量。"),
    novelContract("contract.novel.chapter_brief", "章节写作简报", "edge_handoff", [
      { field_id: "chapter_index", title_zh: "章节序号", field_type: "number" },
      { field_id: "scene_goals", title_zh: "场景目标", field_type: "array" },
      { field_id: "required_memory_refs", title_zh: "必需记忆引用", field_type: "array" },
    ], "章节计划到章节写作的交接契约。"),
    novelContract("contract.novel.chapter_draft", "章节草稿", "node_execution", [
      { field_id: "chapter_index", title_zh: "章节序号", field_type: "number" },
      { field_id: "chapter_text", title_zh: "章节正文" },
      { field_id: "new_facts", title_zh: "新增事实", field_type: "array", required: false },
    ], "章节写作阶段输出。"),
    novelContract("contract.novel.continuity_review", "连续性审查报告", "node_execution", [
      { field_id: "conflicts", title_zh: "连续性冲突", field_type: "array" },
      { field_id: "severity", title_zh: "严重程度" },
      { field_id: "fix_suggestions", title_zh: "修复建议", field_type: "array" },
    ], "连续性审校阶段输出。"),
    novelContract("contract.novel.memory_promotion_batch", "任务记忆晋升批次", "node_execution", [
      { field_id: "promotion_candidates", title_zh: "晋升候选", field_type: "array" },
      { field_id: "rejected_items", title_zh: "拒绝项", field_type: "array", required: false },
      { field_id: "review_required", title_zh: "是否需要人工复核", field_type: "boolean" },
    ], "记忆与交付管理阶段输出。"),
    novelContract("contract.novel.final_manuscript_package", "最终稿件交付包", "final_output", [
      { field_id: "manuscript_refs", title_zh: "正文产物引用", field_type: "array" },
      { field_id: "bible_refs", title_zh: "设定集引用", field_type: "array" },
      { field_id: "unresolved_issues", title_zh: "未解决问题", field_type: "array", required: false },
    ], "长篇小说任务最终交付契约。"),
  ];
}

function longformNovelNodeScheduling(nodeId: string) {
  const base = {
    execution_mode: "sync",
    dispatch_group: "",
    wait_policy: "wait_all_upstream_completed",
    join_policy: "all_success",
    background_policy: { enabled: false, blocks_downstream: true },
    notification_policy: { on_started: "event_only", on_completed: "event_only", on_failed: "queued_alert", include_result: "summary_and_refs", priority: "next" },
    resource_lifecycle_policy: { kill_on_parent_abort: true, cleanup_on_terminal: true },
    human_gate_policy: {},
    failure_policy: {
      on_contract_error: "retry_structure_only_once",
      on_content_conflict: "route_to_revision_gate",
      on_timeout: "queued_alert_and_pause_node",
      max_retries: 1,
      escalation: "revision_gate",
    },
  };
  if (nodeId === "story_architecture") {
    return {
      ...base,
      execution_mode: "sync",
      dispatch_group: "planning_assets",
      join_policy: "all_success",
      failure_policy: { ...base.failure_policy, on_failure: "fail_closed_manual_review", max_retries: 1 },
      notification_policy: { ...base.notification_policy, on_completed: "queued_summary", priority: "next" },
    };
  }
  if (nodeId === "revision_gate") {
    return {
      ...base,
      execution_mode: "barrier",
      dispatch_group: "chapter_quality",
      join_policy: "coordinator_decides",
      failure_policy: { ...base.failure_policy, on_failure: "manual_review", max_retries: 0, escalation: "human_gate" },
      human_gate_policy: {
        required_when: ["blocking_conflict_repeated", "world_rule_retroactive_change", "user_goal_changed", "final_blocking_issue"],
        decision_contract_id: "contract.novel.continuity_review",
        reviewer_role: "user_or_showrunner",
      },
      notification_policy: { ...base.notification_policy, on_completed: "queued_summary", priority: "now" },
    };
  }
  if (nodeId === "memory_publish") {
    return {
      ...base,
      execution_mode: "background",
      dispatch_group: "memory_maintenance",
      join_policy: "allow_partial_with_issues",
      background_policy: {
        enabled: true,
        blocks_downstream: false,
        result_visibility: "summary_and_refs",
        writeback_targets: ["working_memory_candidate", "task_durable_candidate"],
        max_runtime_seconds: 900,
        kill_on_parent_abort: true,
        retain_after_completion_seconds: 1800,
      },
      failure_policy: { ...base.failure_policy, on_failure: "allow_partial_pending_review", max_retries: 1, escalation: "final_assembly" },
      notification_policy: { on_started: "event_only", on_completed: "queued_summary", on_failed: "queued_alert", include_result: "summary_and_refs", priority: "later" },
    };
  }
  if (nodeId === "final_assembly") {
    return {
      ...base,
      execution_mode: "barrier",
      dispatch_group: "final_join",
      wait_policy: "wait_all_upstream_completed",
      join_policy: "all_success",
      failure_policy: { ...base.failure_policy, on_missing_stable_assets: "emit_incomplete_package", max_retries: 0 },
      notification_policy: { ...base.notification_policy, on_completed: "queued_summary", priority: "now" },
    };
  }
  if (nodeId === "continuity_review") {
    return {
      ...base,
      execution_mode: "sync",
      dispatch_group: "chapter_quality",
      join_policy: "fail_on_any_error",
      failure_policy: { ...base.failure_policy, on_failure: "fail_closed", max_retries: 1 },
      notification_policy: { ...base.notification_policy, on_completed: "queued_summary", priority: "next" },
    };
  }
  if (nodeId === "chapter_draft") {
    return {
      ...base,
      failure_policy: { ...base.failure_policy, on_failure: "retry_until_chapter_attempt_limit", max_retries: 1, escalation: "revision_gate" },
    };
  }
  return base;
}

function longformNovelNodeMemoryPolicy(nodeId: string) {
  const dynamic = {
    enabled: true,
    allow_dynamic_read: true,
    max_dynamic_reads_per_node_run: 3,
    allow_temporal_expansion: true,
    max_temporal_expansion_depth: 2,
    max_temporal_neighbors: 6,
    expansion_requires_reason: true,
  };
  const readonlyStable = {
    readable_kinds: ["task_goal", "decision_record", "plan_fragment", "world_bible_delta", "character_state_delta", "style_constraint", "foreshadow_track"],
    readable_scopes: ["task_scope", "graph_scope", "handoff_only"],
    readable_semantics: ["working_fact", "decision", "instruction", "temporal_event"],
    prefer_accepted_items: true,
    reject_unaccepted_facts: true,
  };
  if (nodeId === "input_brief") {
    return {
      memory_read_policy: { readable_kinds: [], readable_scopes: [], readable_semantics: [] },
      memory_writeback_policy: {
        writable_kinds: ["task_goal", "decision_record"],
        writable_scopes: ["graph_scope"],
        default_visibility: "shared_in_graph",
        requires_coordinator_review: false,
      },
      dynamic_memory_read_policy: { enabled: false, allow_dynamic_read: false, max_dynamic_reads_per_node_run: 0 },
    };
  }
  if (nodeId === "story_architecture") {
    return {
      memory_read_policy: {
        ...readonlyStable,
        readable_kinds: ["task_goal", "decision_record", "style_constraint", "world_bible_delta", "character_state_delta", "foreshadow_track"],
      },
      memory_writeback_policy: {
        writable_kinds: ["plan_fragment", "decision_record", "world_bible_delta", "character_state_delta", "foreshadow_track", "style_constraint"],
        writable_scopes: ["node_scope", "graph_scope"],
        default_visibility: "shared_in_graph",
        requires_coordinator_review: true,
      },
      dynamic_memory_read_policy: { ...dynamic, max_dynamic_reads_per_node_run: 4 },
    };
  }
  if (nodeId === "chapter_plan") {
    return {
      memory_read_policy: {
        ...readonlyStable,
        readable_kinds: ["plan_fragment", "decision_record", "world_bible_delta", "character_state_delta", "style_constraint", "foreshadow_track", "artifact_ref"],
      },
      memory_writeback_policy: {
        writable_kinds: ["chapter_brief", "decision_record", "foreshadow_track"],
        writable_scopes: ["node_scope", "graph_scope"],
        default_visibility: "shared_in_graph",
        requires_coordinator_review: true,
      },
      dynamic_memory_read_policy: { ...dynamic, max_dynamic_reads_per_node_run: 4 },
    };
  }
  if (nodeId === "chapter_draft") {
    return {
      memory_read_policy: {
        readable_kinds: ["chapter_brief", "decision_record", "world_bible_delta", "character_state_delta", "style_constraint", "foreshadow_track", "retry_guidance", "artifact_ref"],
        readable_scopes: ["task_scope", "graph_scope", "handoff_only"],
        readable_semantics: ["working_fact", "decision", "instruction", "temporal_event", "draft_artifact"],
        prefer_accepted_items: true,
        reject_unaccepted_facts: true,
      },
      memory_writeback_policy: {
        writable_kinds: ["chapter_draft", "character_state_delta", "world_bible_delta", "foreshadow_track", "artifact_ref"],
        writable_scopes: ["node_scope", "graph_scope"],
        default_visibility: "private_to_node",
        requires_coordinator_review: true,
        accepted_write_forbidden: true,
      },
      dynamic_memory_read_policy: dynamic,
    };
  }
  if (nodeId === "continuity_review") {
    return {
      memory_read_policy: {
        readable_kinds: ["chapter_draft", "decision_record", "world_bible_delta", "character_state_delta", "style_constraint", "foreshadow_track", "artifact_ref"],
        readable_scopes: ["task_scope", "graph_scope", "handoff_only", "node_scope"],
        readable_semantics: ["working_fact", "draft_artifact", "temporal_event", "decision", "conflict"],
        prefer_accepted_items: true,
        allow_unaccepted_draft_refs: true,
      },
      memory_writeback_policy: {
        writable_kinds: ["continuity_conflict", "evaluator_feedback", "revision_instruction"],
        writable_scopes: ["edge_scope", "graph_scope"],
        default_visibility: "shared_in_graph",
        requires_coordinator_review: true,
      },
      dynamic_memory_read_policy: { ...dynamic, max_dynamic_reads_per_node_run: 5 },
    };
  }
  if (nodeId === "revision_gate") {
    return {
      memory_read_policy: {
        readable_kinds: ["continuity_conflict", "evaluator_feedback", "revision_instruction", "chapter_draft", "decision_record", "world_bible_delta", "character_state_delta", "artifact_ref"],
        readable_scopes: ["task_scope", "graph_scope", "handoff_only", "edge_scope"],
        readable_semantics: ["decision", "conflict", "instruction", "draft_artifact", "working_fact"],
        prefer_accepted_items: false,
      },
      memory_writeback_policy: {
        writable_kinds: ["decision_record", "retry_guidance"],
        writable_scopes: ["graph_scope"],
        default_visibility: "shared_in_graph",
        requires_coordinator_review: false,
      },
      dynamic_memory_read_policy: { ...dynamic, max_dynamic_reads_per_node_run: 2, allow_temporal_expansion: false, max_temporal_expansion_depth: 0 },
    };
  }
  if (nodeId === "memory_publish") {
    return {
      memory_read_policy: {
        readable_kinds: ["decision_record", "chapter_draft", "world_bible_delta", "character_state_delta", "foreshadow_track", "style_constraint", "continuity_conflict", "artifact_ref"],
        readable_scopes: ["task_scope", "graph_scope", "handoff_only"],
        readable_semantics: ["working_fact", "decision", "temporal_event", "conflict", "draft_artifact"],
        require_acceptance_refs: true,
      },
      memory_writeback_policy: {
        writable_kinds: ["promotion_candidate", "artifact_ref"],
        writable_scopes: ["task_scope"],
        default_visibility: "coordinator_only",
        requires_coordinator_review: true,
        task_durable_candidate_only: true,
      },
      dynamic_memory_read_policy: { ...dynamic, max_dynamic_reads_per_node_run: 4 },
    };
  }
  if (nodeId === "final_assembly") {
    return {
      memory_read_policy: {
        readable_kinds: ["promotion_candidate", "artifact_ref", "decision_record", "continuity_conflict"],
        readable_scopes: ["task_scope", "graph_scope", "handoff_only"],
        readable_semantics: ["working_fact", "decision", "conflict", "artifact_ref"],
        require_stable_refs: true,
      },
      memory_writeback_policy: {
        writable_kinds: ["artifact_ref", "decision_record"],
        writable_scopes: ["task_scope"],
        default_visibility: "shared_in_graph",
        requires_coordinator_review: false,
      },
      dynamic_memory_read_policy: { ...dynamic, max_dynamic_reads_per_node_run: 2, allow_temporal_expansion: false, max_temporal_expansion_depth: 0 },
    };
  }
  return {
    memory_read_policy: readonlyStable,
    memory_writeback_policy: {
      writable_kinds: ["decision_record"],
      writable_scopes: ["node_scope"],
      default_visibility: "private_to_node",
      requires_coordinator_review: true,
    },
    dynamic_memory_read_policy: dynamic,
  };
}

function buildLongformNovelPackage(): {
  domain: TaskDomainRecord;
  task: SpecificTaskRecord;
  workflow: WorkflowDraft;
  execution: TaskExecutionPolicy;
  memory: TaskMemoryRequestProfile;
  contracts: ContractSpec[];
  topology: TopologyDraft;
  protocol: ProtocolDraft;
  coordination: CoordinationDraft;
  graph: TaskGraphRecord;
  requiredAgents: Array<{ agent_id: string; title: string; projection_id: string; output_contracts: string[]; allowed_operations: string[]; allowed_memory_scopes: string[]; required_capabilities: string[]; forbidden_actions: string[] }>;
  requiredProjections: Array<{ projection_id: string; agent_id: string; title: string }>;
} {
  const contracts = buildLongformNovelContracts();
  const domain: TaskDomainRecord = {
    domain_id: "domain.longform_novel",
    task_family: "longform_novel_writing",
    title: "长篇小说创作",
    description: "面向多章节、多角色、多设定连续性的长篇小说生产任务域。",
    enabled: true,
    sort_order: 260,
    metadata: { managed_by: "task_package_wizard", package_template: "longform_novel_writing" },
  };
  const task: SpecificTaskRecord = {
    ...emptySpecificTaskRecord("workflow.longform_novel.graph_runtime", "flow.longform_novel.graph_runtime"),
    task_id: "task.longform_novel.create_full_novel",
    task_title: "长篇小说完整创作",
    task_family: domain.task_family,
    task_mode: "longform_novel_graph",
    description: "通过多 Agent 拓扑完成项目规划、设定管理、章节写作、连续性审查、记忆整理与最终交付。",
    input_contract_id: "contract.novel.project_brief",
    output_contract_id: "contract.novel.final_manuscript_package",
    task_policy: {
      safety_policy: { safety_class: "S2_bounded", write_mode: "artifact_ref_only", verification_mode: "contract_and_review" },
      task_structure: { execution_chain_type: "graph_run_loop", trigger_signals: ["task_package.longform_novel"] },
    },
    metadata: { managed_by: "task_package_wizard", package_template: "longform_novel_writing" },
  };
  const workflow: WorkflowDraft = {
    ...emptyWorkflow(task.task_mode),
    workflow_id: task.default_workflow_id,
    title: "长篇小说图运行流程",
    output_contract_id: task.output_contract_id,
    compatible_projection_ids: [
      "projection.longform_novel.showrunner",
      "projection.longform_novel.story_architect",
      "projection.longform_novel.chapter_writer",
      "projection.longform_novel.continuity_editor",
      "projection.longform_novel.memory_publisher",
    ],
    steps: [
      { step_id: "project_plan", title: "项目规划" },
      { step_id: "asset_build", title: "设定与角色资产建立" },
      { step_id: "chapter_loop", title: "章节循环" },
      { step_id: "final_assembly", title: "最终整理" },
    ],
    steps_text: "project_plan | 项目规划\nasset_build | 设定与角色资产建立\nchapter_loop | 章节循环\nfinal_assembly | 最终整理",
    stop_conditions: ["final_manuscript_package_ready"],
    stop_conditions_text: "final_manuscript_package_ready",
    compatible_projection_ids_text: [
      "projection.longform_novel.showrunner",
      "projection.longform_novel.story_architect",
      "projection.longform_novel.chapter_writer",
      "projection.longform_novel.continuity_editor",
      "projection.longform_novel.memory_publisher",
    ].join("\n"),
    metadata: { managed_by: "task_package_wizard", package_template: "longform_novel_writing" },
  };
  const execution = {
    ...emptyExecutionPolicy(task.task_id),
    execution_chain_type: "graph_run_loop",
    runtime_agent_selection_policy: "task_graph_explicit_agent",
    default_agent_id: "agent:novel_showrunner",
    allowed_agent_categories: ["worker_sub_agent"],
    allow_worker_agent_spawn: false,
    notes: "Agent 必须先在编排系统前端创建，并由任务图节点显式绑定。",
    metadata: { managed_by: "task_package_wizard", package_template: "longform_novel_writing" },
  };
  const memory = {
    ...emptyMemoryProfile(task.task_id),
    requested_memory_layers: ["working", "task_durable"],
    requested_topics: ["story_bible", "character_state", "chapter_draft", "continuity"],
    writeback_policy: "task_durable_reviewed_promotion",
    allow_long_term_memory: true,
    allow_working_memory: true,
    allow_dynamic_working_memory_read: true,
    working_memory_policy_profile_id: "wmprofile.longform_novel",
    working_memory_default_scope: "node_scope",
    working_memory_default_visibility: "private_to_node",
    working_memory_policy: {
      enabled: true,
      default_scope: "node_scope",
      default_visibility: "private_to_node",
      allowed_kinds: ["chapter_draft", "character_state_delta", "world_bible_delta", "continuity_conflict", "promotion_candidate", "revision_instruction"],
      finalize_requires_human_review: true,
      promotion_requires_human_review: true,
    },
    memory_scope_hint: "任务工作记忆与任务长期记忆隔离，不写入 Global Durable。",
    metadata: { managed_by: "task_package_wizard", package_template: "longform_novel_writing" },
  };
  const nodes = [
    ["input_brief", "input", "项目简报", "agent:novel_showrunner", "contract.novel.project_brief"],
    ["story_architecture", "agent", "故事架构", "agent:novel_story_architect", "contract.novel.volume_outline"],
    ["chapter_plan", "agent", "章节计划", "agent:novel_story_architect", "contract.novel.chapter_brief"],
    ["chapter_draft", "agent", "章节写作", "agent:novel_chapter_writer", "contract.novel.chapter_draft"],
    ["continuity_review", "agent", "连续性审校", "agent:novel_continuity_editor", "contract.novel.continuity_review"],
    ["revision_gate", "coordinator", "修订决策", "agent:novel_showrunner", "contract.novel.project_plan"],
    ["memory_publish", "agent", "记忆与交付管理", "agent:novel_memory_publisher", "contract.novel.memory_promotion_batch"],
    ["final_assembly", "agent", "最终交付整理", "agent:novel_memory_publisher", "contract.novel.final_manuscript_package"],
  ].map(([nodeId, nodeType, title, agentId, outputContractId]) => {
    const scheduling = longformNovelNodeScheduling(String(nodeId));
    const memoryPolicy = longformNovelNodeMemoryPolicy(String(nodeId));
    return {
    node_id: String(nodeId),
    node_type: String(nodeType),
    title,
    label: title,
    task_id: task.task_id,
    task_title: task.task_title,
    task_family: domain.task_family,
    agent_id: agentId,
    role: nodeId === "input_brief" ? "coordinator" : "participant",
    work_posture: nodeId,
    node_contract_id: outputContractId,
    input_contract_id: nodeId === "input_brief" ? task.input_contract_id : "",
    output_contract_id: outputContractId,
    runtime_lane: "longform_novel_graph",
    execution_mode: scheduling.execution_mode,
    dispatch_group: scheduling.dispatch_group,
    wait_policy: scheduling.wait_policy,
    join_policy: scheduling.join_policy,
    background_policy: scheduling.background_policy,
    notification_policy: scheduling.notification_policy,
    resource_lifecycle_policy: scheduling.resource_lifecycle_policy,
    human_gate_policy: scheduling.human_gate_policy,
    failure_policy: scheduling.failure_policy,
    memory_read_policy: memoryPolicy.memory_read_policy,
    memory_writeback_policy: memoryPolicy.memory_writeback_policy,
    dynamic_memory_read_policy: memoryPolicy.dynamic_memory_read_policy,
    };
  });
  const edgePairs = [
    ["e_brief_architecture", "input_brief", "story_architecture", "contract.novel.project_brief", ["task_goal"], "fail_downstream"],
    ["e_architecture_chapter", "story_architecture", "chapter_plan", "contract.novel.volume_outline", ["plan_fragment", "foreshadow_track", "world_state_delta", "character_state_delta"], "fail_downstream"],
    ["e_chapter_plan_draft", "chapter_plan", "chapter_draft", "contract.novel.chapter_brief", ["chapter_brief", "style_constraint", "accepted_refs"], "fail_downstream"],
    ["e_draft_review", "chapter_draft", "continuity_review", "contract.novel.chapter_draft", ["chapter_draft", "character_state_delta", "world_state_delta"], "fail_downstream"],
    ["e_review_gate", "continuity_review", "revision_gate", "contract.novel.continuity_review", ["continuity_conflict", "evaluator_feedback", "revision_instruction"], "coordinator_decides"],
    ["e_gate_memory", "revision_gate", "memory_publish", "contract.novel.continuity_review", ["accepted_refs", "decision_record", "retry_guidance"], "allow_partial"],
    ["e_memory_final", "memory_publish", "final_assembly", "contract.novel.memory_promotion_batch", ["promotion_candidate", "task_durable_refs", "unresolved_conflict"], "coordinator_decides"],
  ];
  const edges = edgePairs.map(([edgeId, from, to, contractId, carryKinds, failurePolicy]) => ({
    edge_id: edgeId,
    from,
    to,
    source_node_id: from,
    target_node_id: to,
    edge_type: "handoff",
    mode: "structured_handoff",
    policy: "structured_handoff",
    a2a_message_type: "message/send",
    payload_contract_id: contractId,
    wait_policy: "wait_all_upstream_completed",
    ack_required: true,
    ack_policy: "required_before_target_start",
    failure_propagation_policy: String(failurePolicy),
    result_delivery_policy: "contract_payload_and_refs",
    timeout_policy: "fail_closed",
    context_filter_policy: { include_raw_messages: false, include_private_memory: false, prefer_refs: true },
    artifact_ref_policy: { include_artifact_refs: true, require_stable_refs_for_final: to === "final_assembly" },
    communication_policy: {
      sync_semantics: to === "memory_publish" ? "async_background_after_gate" : to === "final_assembly" ? "barrier_wait_for_stable_refs" : "sync_handoff_before_target_start",
      payload_visibility: "contract_payload_and_refs",
      ack_semantics: "target_must_ack_before_execution",
      raw_message_forwarding: false,
    },
    failure_policy: {
      duplicate_source_message_hash: "reuse_handoff_transaction",
      contract_mismatch: "block_downstream_and_route_to_revision_gate",
      missing_ack: "pause_target_and_alert",
    },
    working_memory_handoff_policy: {
      carry_kinds: carryKinds,
      carry_scopes: ["handoff_only", "graph_scope"],
      working_memory_refs: [],
      summary_only: true,
      allow_artifact_refs: true,
      prefer_accepted_items: true,
      reject_unaccepted_facts: true,
      quarantine_unaccepted_facts: true,
    },
  }));
  const topology: TopologyDraft = {
    ...emptyTopology(),
    template_id: "topology.longform_novel.production_graph",
    title: "长篇小说生产拓扑",
    nodes,
    edges,
    enabled: true,
    metadata: { managed_by: "task_package_wizard", task_family: domain.task_family, domain_id: domain.domain_id, package_template: "longform_novel_writing" },
    nodes_text: JSON.stringify(nodes, null, 2),
    edges_text: JSON.stringify(edges, null, 2),
  };
  const protocol: ProtocolDraft = {
    ...emptyProtocol(),
    protocol_id: "protocol.longform_novel.a2a_handoff",
    title: "长篇小说 A2A 交接协议",
    message_types: ["message/send"],
    payload_contracts: contracts.map((item) => item.contract_id),
    signal_rules: ["contract_payload_required", "working_memory_refs_are_refs_only"],
    handoff_rules: ["no_raw_private_memory", "ack_required", "task_durable_only_after_review"],
    enabled: true,
    metadata: { managed_by: "task_package_wizard", task_family: domain.task_family, domain_id: domain.domain_id, a2a_protocol: "official", protocol_locked: true },
    message_types_text: "message/send",
    payload_contracts_text: contracts.map((item) => item.contract_id).join("\n"),
    signal_rules_text: "contract_payload_required\nworking_memory_refs_are_refs_only",
    handoff_rules_text: "no_raw_private_memory\nack_required\ntask_durable_only_after_review",
  };
  const coordination: CoordinationDraft = {
    ...emptyCoordination(topology.template_id, protocol.protocol_id, domain.task_family, domain.domain_id),
    coordination_task_id: "coord.longform_novel.core_production",
    title: "长篇小说核心团队生产任务",
    coordination_mode: "pipeline",
    coordinator_agent_id: "agent:novel_showrunner",
    agent_group_id: "group.longform_novel_core_team",
    graph_nodes: nodes,
    graph_edges: edges,
    subtask_refs: [task.task_id],
    communication_modes: ["structured_handoff", "review_feedback", "revision_gate"],
    enabled: true,
    metadata: { managed_by: "task_package_wizard", protocol_id: protocol.protocol_id, task_family: domain.task_family, domain_id: domain.domain_id, package_template: "longform_novel_writing" },
    stop_conditions: ["final_manuscript_package_ready"],
    stop_conditions_text: "final_manuscript_package_ready",
  };
  const graph: TaskGraphRecord = {
    graph_id: "graph.longform_novel.core_production",
    title: "长篇小说核心团队任务图",
    domain_id: domain.domain_id,
    task_family: domain.task_family,
    graph_kind: "multi_agent",
    entry_node_id: "input_brief",
    output_node_id: "final_assembly",
    nodes,
    edges: edges.map((edge) => ({
      edge_id: String(edge.edge_id),
      source_node_id: String(edge.source_node_id),
      target_node_id: String(edge.target_node_id),
      edge_type: "handoff",
      a2a_message_type: "message/send",
      payload_contract_id: String(edge.payload_contract_id),
      working_memory_handoff_policy: edge.working_memory_handoff_policy,
      wait_policy: String(edge.wait_policy),
      ack_required: Boolean(edge.ack_required),
      ack_policy: String(edge.ack_policy),
      failure_propagation_policy: String(edge.failure_propagation_policy),
      result_delivery_policy: String(edge.result_delivery_policy),
    })),
    graph_contract_id: task.output_contract_id,
    default_protocol_id: protocol.protocol_id,
    runtime_policy: {
      loop_kind: "iterative_graph",
      iteration_unit: "chapter",
      max_iterations: 120,
      max_attempts_per_iteration: 3,
      revise_until: "no_error_conflict",
      memory_finalize_per_iteration: true,
      task_durable_promotion_cadence: "revision_gate_accept",
      chapter_loop: {
        plan_node_id: "chapter_plan",
        draft_node_id: "chapter_draft",
        review_node_id: "continuity_review",
        gate_node_id: "revision_gate",
        memory_node_id: "memory_publish",
        max_attempts_per_chapter: 3,
        retry_on: ["contract_error", "continuity_conflict", "style_drift"],
        manual_gate_on: ["blocking_conflict_repeated", "world_rule_retroactive_change", "user_goal_changed", "memory_promotion_ambiguous"],
        skip_policy: "coordinator_decides",
      },
      checkpoint_policy: {
        checkpoint_after_nodes: ["revision_gate", "memory_publish"],
        resume_from: "latest_successful_checkpoint",
        idempotency_keys: ["task_run_id", "graph_run_id", "chapter_index", "node_run_id", "run_attempt_id", "handoff_transaction_id", "source_message_hash", "artifact_ref"],
      },
      recovery_policy: {
        duplicate_output: "reuse_existing_artifact_ref",
        stale_handoff: "revalidate_contract_before_dispatch",
        agent_timeout: "retry_once_then_manual_review",
        background_failure: "mark_pending_review_and_continue",
        abort_policy: "kill_background_runs_keep_pending_candidates",
      },
      memory_quarantine_policy: {
        draft_kind: "draft_artifact",
        accept_requires: ["continuity_review_passed", "revision_gate_accept"],
        promotion_requires_human_review: true,
        global_durable_write: "forbidden_without_manual_secondary_promotion",
      },
      finalization_policy: {
        require_no_blocking_conflicts: true,
        incomplete_package_on_blockers: true,
        include_unresolved_conflicts: true,
      },
    },
    context_policy: { sharing: "explicit_refs_only", raw_private_memory: false, unaccepted_facts: "ephemeral_only" },
    publish_state: "draft",
    enabled: true,
    metadata: { managed_by: "task_package_wizard", coordination_task_id: coordination.coordination_task_id, package_template: "longform_novel_writing" },
  };
  const requiredAgents = [
    {
      agent_id: "agent:novel_showrunner",
      title: "长篇小说总协调",
      projection_id: "projection.longform_novel.showrunner",
      output_contracts: ["contract.novel.project_brief", "contract.novel.project_plan"],
      allowed_operations: ["op.model_response", "op.memory_read", "op.memory_write_candidate", "op.artifact_result_ref"],
      allowed_memory_scopes: ["working_memory.task_read", "working_memory.graph_read_write", "task_durable.read_candidate"],
      required_capabilities: ["coordination.decision_gate", "contract.validation", "runloop.chapter_control"],
      forbidden_actions: ["write_global_durable", "direct_accept_chapter_draft_without_review"],
    },
    {
      agent_id: "agent:novel_story_architect",
      title: "故事架构师",
      projection_id: "projection.longform_novel.story_architect",
      output_contracts: ["contract.novel.volume_outline", "contract.novel.chapter_brief", "contract.novel.world_bible_delta", "contract.novel.character_delta"],
      allowed_operations: ["op.model_response", "op.memory_read", "op.memory_write_candidate"],
      allowed_memory_scopes: ["working_memory.task_read", "working_memory.graph_read_write", "task_durable.read_candidate"],
      required_capabilities: ["story.planning", "world_bible.delta", "chapter_briefing"],
      forbidden_actions: ["write_global_durable", "overwrite_accepted_fact_without_gate"],
    },
    {
      agent_id: "agent:novel_chapter_writer",
      title: "章节写作 Agent",
      projection_id: "projection.longform_novel.chapter_writer",
      output_contracts: ["contract.novel.chapter_draft"],
      allowed_operations: ["op.model_response", "op.memory_read", "op.memory_write_candidate", "op.artifact_result_ref"],
      allowed_memory_scopes: ["working_memory.handoff_read", "working_memory.node_write", "artifact.write_ref"],
      required_capabilities: ["chapter.drafting", "revision.apply_instruction", "artifact.ref_output"],
      forbidden_actions: ["accept_own_draft", "write_task_durable", "write_global_durable"],
    },
    {
      agent_id: "agent:novel_continuity_editor",
      title: "连续性审校 Agent",
      projection_id: "projection.longform_novel.continuity_editor",
      output_contracts: ["contract.novel.continuity_review"],
      allowed_operations: ["op.model_response", "op.memory_read", "op.memory_write_candidate"],
      allowed_memory_scopes: ["working_memory.task_read", "working_memory.graph_read_write", "working_memory.edge_write"],
      required_capabilities: ["continuity.review", "conflict.detect", "revision.instruction"],
      forbidden_actions: ["rewrite_chapter_text", "accept_memory_promotion", "write_global_durable"],
    },
    {
      agent_id: "agent:novel_memory_publisher",
      title: "记忆与交付管理 Agent",
      projection_id: "projection.longform_novel.memory_publisher",
      output_contracts: ["contract.novel.memory_promotion_batch", "contract.novel.final_manuscript_package"],
      allowed_operations: ["op.model_response", "op.memory_read", "op.memory_write_candidate", "op.artifact_result_ref"],
      allowed_memory_scopes: ["working_memory.accepted_read", "task_durable.write_candidate", "artifact.read_write_ref"],
      required_capabilities: ["memory.promotion_batch", "task_durable.candidate_publish", "final.package_assembly"],
      forbidden_actions: ["write_global_durable_without_manual_secondary_promotion", "promote_unaccepted_draft"],
    },
  ];
  const requiredProjections = [
    { projection_id: "projection.longform_novel.showrunner", agent_id: "agent:novel_showrunner", title: "长篇小说总协调" },
    { projection_id: "projection.longform_novel.story_architect", agent_id: "agent:novel_story_architect", title: "故事架构师" },
    { projection_id: "projection.longform_novel.chapter_writer", agent_id: "agent:novel_chapter_writer", title: "章节写作 Agent" },
    { projection_id: "projection.longform_novel.continuity_editor", agent_id: "agent:novel_continuity_editor", title: "连续性审校 Agent" },
    { projection_id: "projection.longform_novel.memory_publisher", agent_id: "agent:novel_memory_publisher", title: "记忆与交付管理 Agent" },
  ];
  return { domain, task, workflow, execution, memory, contracts, topology, protocol, coordination, graph, requiredAgents, requiredProjections };
}

function contractLabel(value: string, specs: ContractSpec[] = [], legacyContracts: TaskContractDescriptor[] = []) {
  const spec = specs.find((item) => item.contract_id === value);
  if (spec) return `${contractSpecTitle(spec)} · ${value}`;
  const contract = legacyContracts.find((item) => item.contract_id === value);
  return contract?.title || displayId(value);
}

function deriveTaskGraphSpec(
  coordinationTaskId: string,
  domainId: string,
  taskFamily: string,
  nodes: Array<Record<string, unknown>>,
  edges: Array<Record<string, unknown>>,
): CoordinationGraphSpec {
  const nodeIds = nodes
    .map((node, index) => String(node.node_id ?? node.id ?? `node_${index + 1}`).trim())
    .filter(Boolean);
  const uniqueNodeIds = new Set(nodeIds);
  const startNodeIds = nodeIds.filter((nodeId) => !edges.some((edge) => graphEdgeTarget(edge) === nodeId));
  const terminalNodeIds = nodeIds.filter((nodeId) => !edges.some((edge) => graphEdgeSource(edge) === nodeId));
  const issues: Array<Record<string, unknown>> = [];

  if (!nodes.length) {
    issues.push({
      code: "empty_task_graph",
      severity: "blocker",
      message: "任务图还没有节点，不能预检或发布。",
    });
  }

  if (uniqueNodeIds.size !== nodeIds.length) {
    issues.push({
      code: "duplicate_node_id",
      severity: "blocker",
      message: "任务图中存在重复节点 ID。",
    });
  }

  edges.forEach((edge, index) => {
    const source = graphEdgeSource(edge);
    const target = graphEdgeTarget(edge);
    if (!source || !target) {
      issues.push({
        code: "edge_endpoint_missing",
        severity: "blocker",
        message: `第 ${index + 1} 条边缺少来源或目标节点。`,
      });
      return;
    }
    if (!uniqueNodeIds.has(source) || !uniqueNodeIds.has(target)) {
      issues.push({
        code: "edge_endpoint_unknown",
        severity: "blocker",
        message: `第 ${index + 1} 条边连接了不存在的节点。`,
      });
    }
  });

  return {
    graph_id: coordinationTaskId || "graph.draft",
    coordination_task_id: coordinationTaskId,
    domain_id: domainId,
    task_family: taskFamily,
    coordinator_agent_id: "",
    agent_group_id: "",
    nodes,
    edges,
    subtask_refs: uniqueStrings(nodes.map((node) => graphNodeTaskId(node))),
    communication_modes: uniqueStrings(edges.map((edge) => String(edge.mode ?? "").trim())),
    start_node_ids: startNodeIds,
    terminal_node_ids: terminalNodeIds,
    issues,
    valid: issues.length === 0,
    diagnostics: {
      derived_from: "task_graph_draft",
      node_count: nodes.length,
      edge_count: edges.length,
    },
  };
}

function projectionLabel(value: string, cards: SoulProjectionCard[] = []) {
  const raw = String(value || "").trim();
  if (!raw) return "不使用投影";
  const card = cards.find((item) => item.projection_id === raw);
  if (!card) return displayId(raw);
  const title = card.title || card.projection_id;
  const soul = card.soul_name || card.soul_id;
  return soul ? `${title} · ${soul}` : title;
}

function runtimeProfileHasAll(profile: Partial<OrchestrationAgentRuntimeProfile> | undefined, key: keyof OrchestrationAgentRuntimeProfile, expected: string[]) {
  const raw = profile?.[key];
  const values = Array.isArray(raw) ? new Set(raw.map(String)) : new Set<string>();
  return expected.every((item) => values.has(item));
}

function packagePrerequisiteBadge(status: PackagePrerequisiteStatus) {
  if (status === "ready") return "已就绪";
  if (status === "partial") return "需补齐";
  return "缺失";
}

function packagePrerequisiteClass(status: PackagePrerequisiteStatus) {
  if (status === "ready") return "boundary-badge boundary-badge--ok";
  if (status === "partial") return "boundary-badge boundary-badge--warn";
  return "boundary-badge boundary-badge--danger";
}

function ProjectionSelectField({
  label,
  value,
  cards,
  onChange,
  wide = false,
}: {
  label: string;
  value: string;
  cards: SoulProjectionCard[];
  onChange: (value: string) => void;
  wide?: boolean;
}) {
  const options = uniqueStrings(["", value, ...cards.map((item) => item.projection_id)]);
  return (
    <Field label={label} wide={wide}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((item) => (
          <option key={item || "none"} value={item}>{projectionLabel(item, cards)}</option>
        ))}
      </select>
    </Field>
  );
}

function ProjectionMultiSelectField({
  label,
  value,
  cards,
  onChange,
  wide = false,
}: {
  label: string;
  value: string[];
  cards: SoulProjectionCard[];
  onChange: (value: string[]) => void;
  wide?: boolean;
}) {
  const selected = new Set(value ?? []);
  const options = uniqueStrings([...cards.map((item) => item.projection_id), ...(value ?? [])]);
  return (
    <Field label={label} wide={wide}>
      <div className="boundary-choice-grid">
        {options.map((item) => (
          <button
            className={selected.has(item) ? "boundary-choice boundary-choice--active" : "boundary-choice"}
            key={item}
            onClick={() => {
              const next = selected.has(item)
                ? (value ?? []).filter((current) => current !== item)
                : [...(value ?? []), item];
              onChange(next);
            }}
            type="button"
          >
            {projectionLabel(item, cards)}
          </button>
        ))}
        {!options.length ? <div className="boundary-empty">灵魂系统暂无可选投影。</div> : null}
      </div>
    </Field>
  );
}

function buildDomains(consolePayload: TaskSystemOverview | null): DomainRecord[] {
  const tasks = consolePayload?.task_management.specific_task_records ?? [];
  const entryPolicies = consolePayload?.task_management.entry_policies ?? [];
  const formalDomains = consolePayload?.task_management.task_domains ?? [];
  const grouped = new Map<string, SpecificTaskRecord[]>();
  for (const task of tasks) {
    const key = task.task_family || "general";
    grouped.set(key, [...(grouped.get(key) ?? []), task]);
  }
  const baseDomains = formalDomains.length
    ? formalDomains
    : Array.from(grouped.keys()).map((family, index) => ({
        ...emptyTaskDomain(index),
        domain_id: `domain.${family}`,
        task_family: family,
        title: domainTitle(family),
      }));
  if (!baseDomains.length) baseDomains.push({ ...emptyTaskDomain(), domain_id: "domain.general", task_family: "general", title: "通用任务域" });
  return baseDomains
    .map((domain, index) => {
      const family = domain.task_family || String(domain.domain_id || "").replace(/^domain\./, "") || "general";
      const items = grouped.get(family) ?? [];
      return {
        domain_id: domain.domain_id || `domain.${family}`,
        title: domain.title || domainTitle(family),
        description: domain.description || "",
        enabled: domain.enabled ?? true,
        sort_order: domain.sort_order ?? index * 10,
        metadata: domain.metadata ?? {},
        task_family: family,
        task_modes: Array.from(new Set(items.map((item) => item.task_mode).filter(Boolean))),
        tasks: items,
        entry_policy: entryPolicies.find((item) => String(item.metadata?.task_family ?? "").trim() === family) ?? entryPolicies[index] ?? entryPolicies[0] ?? null,
      };
    })
    .sort((a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title));
}

function familyFromRef(value: unknown) {
  const raw = String(value ?? "").trim();
  const patterns: Array<[RegExp, string]> = [
    [/^(task|coord|topology|protocol|workflow|flow)\.dev\./, "development"],
    [/^(task|coord|topology|protocol|workflow|flow)\.writing\./, "writing"],
    [/^(task|coord|topology|protocol|workflow|flow)\.health\./, "health"],
    [/^(task|coord|topology|protocol|workflow|flow)\.general\./, "general"],
  ];
  return patterns.find(([pattern]) => pattern.test(raw))?.[1] ?? "";
}

function familyFromTaskRef(taskId: unknown, tasks: SpecificTaskRecord[]) {
  const raw = String(taskId ?? "").trim();
  const task = tasks.find((item) => item.task_id === raw);
  return task?.task_family || familyFromRef(raw);
}

function coordinationFamily(task: CoordinationTask, tasks: SpecificTaskRecord[]) {
  const metadata = task.metadata ?? {};
  if (task.task_family) return task.task_family;
  if (task.domain_id?.startsWith("domain.")) return task.domain_id.replace("domain.", "");
  return (
    String(metadata.task_family ?? "").trim()
    || familyFromTaskRef(metadata.task_id, tasks)
    || (task.subtask_refs ?? []).map((taskId) => familyFromTaskRef(taskId, tasks)).find(Boolean)
    || familyFromRef(task.coordination_task_id)
    || familyFromRef(task.topology_template_id)
  );
}

function topologyFamily(template: TopologyTemplate) {
  const metadata = template.metadata ?? {};
  return String(metadata.task_family ?? "").trim() || familyFromRef(template.template_id);
}

function protocolFamily(protocol: TaskCommunicationProtocol, tasks: SpecificTaskRecord[]) {
  const metadata = protocol.metadata ?? {};
  return (
    String(metadata.task_family ?? "").trim()
    || familyFromTaskRef(metadata.task_id, tasks)
    || familyFromRef(protocol.protocol_id)
  );
}

function protocolForCoordination(
  protocols: TaskCommunicationProtocol[],
  task: CoordinationTask | null,
  fallbackProtocolId = "",
) {
  if (!task) return null;
  const metadata = task.metadata ?? {};
  const explicitProtocol = String(metadata.protocol_id ?? fallbackProtocolId ?? "").trim();
  const taskId = String(metadata.task_id ?? "").trim();
  return (
    protocols.find((item) => item.protocol_id === explicitProtocol)
    ?? protocols.find((item) => String(item.metadata?.task_id ?? "").trim() === taskId && taskId)
    ?? protocols.find((item) => {
      const protocolTail = item.protocol_id.split(".").slice(2).join(".");
      const coordTail = task.coordination_task_id.split(".").slice(2).join(".");
      return protocolTail && protocolTail === coordTail;
    })
    ?? null
  );
}

function ContractSelectField({
  label,
  value,
  options,
  contracts,
  legacyContracts,
  onChange,
  wide = false,
}: {
  label: string;
  value: string;
  options: string[];
  contracts: ContractSpec[];
  legacyContracts?: TaskContractDescriptor[];
  onChange: (value: string) => void;
  wide?: boolean;
}) {
  const resolvedOptions = uniqueStrings([value, ...options]);
  return (
    <Field label={label} wide={wide}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {resolvedOptions.map((item) => (
          <option key={item} value={item}>{contractLabel(item, contracts, legacyContracts)}</option>
        ))}
      </select>
    </Field>
  );
}

function FlowContractSelect({
  label,
  value,
  flows,
  onChange,
}: {
  label: string;
  value: string;
  flows: TaskSystemOverview["task_management"]["task_flow_definitions"];
  onChange: (value: string) => void;
}) {
  const known = flows.map((flow) => String(flow.flow_id || "")).filter(Boolean);
  const resolvedOptions = uniqueStrings([value, ...known]);
  return (
    <Field label={label}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {resolvedOptions.map((item) => {
          const flow = flows.find((candidate) => candidate.flow_id === item);
          return <option key={item} value={item}>{flow?.title || displayId(item)}</option>;
        })}
      </select>
    </Field>
  );
}

function SystemFields({ children }: { children: React.ReactNode }) {
  return (
    <details className="boundary-system-fields">
      <summary>系统字段</summary>
      <div className="boundary-form">{children}</div>
    </details>
  );
}

function ReadinessCard({ label, value, ready }: { label: string; value: string; ready: boolean }) {
  return (
    <article className={ready ? "boundary-readiness boundary-readiness--ready" : "boundary-readiness"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{ready ? "已配置" : "待配置"}</small>
    </article>
  );
}

type LayerNavItem<T extends string> = {
  value: T;
  label: string;
  meta: string;
  detail: string;
};

function LayerNav<T extends string>({
  ariaLabel,
  items,
  value,
  onChange,
  variant = "primary",
}: {
  ariaLabel: string;
  items: Array<LayerNavItem<T>>;
  value: T;
  onChange: (value: T) => void;
  variant?: "primary" | "secondary";
}) {
  return (
    <nav className={variant === "secondary" ? "task-system-layer-nav task-system-layer-nav--secondary" : "task-system-layer-nav"} aria-label={ariaLabel}>
      {items.map((item) => (
        <button
          className={value === item.value ? "task-system-layer-nav__item task-system-layer-nav__item--active" : "task-system-layer-nav__item"}
          key={item.value}
          onClick={() => onChange(item.value)}
          type="button"
        >
          <span>{item.label}</span>
          <strong>{item.meta}</strong>
          <small>{item.detail}</small>
        </button>
      ))}
    </nav>
  );
}


export function TaskSystemView() {
  const { setTaskSelection, setWorkspaceView } = useAppStore();
  const [consolePayload, setConsolePayload] = useState<TaskSystemOverview | null>(null);
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [orchestrationCatalog, setOrchestrationCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedCoordinationId, setSelectedCoordinationId] = useState("");
  const [editorTaskId, setEditorTaskId] = useState("");
  const [editorCoordinationId, setEditorCoordinationId] = useState("");
  const [taskLayer, setTaskLayer] = useState<TaskLayer>("management");
  const [editingDomainName, setEditingDomainName] = useState(false);
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState("");
  const [selectedGraphEdgeId, setSelectedGraphEdgeId] = useState("");
  const [linkingFromNodeId, setLinkingFromNodeId] = useState("");
  const [taskConfigPanel, setTaskConfigPanel] = useState<TaskConfigPanel>("definition");
  const [contractPanel, setContractPanel] = useState<ContractPanel>("library");
  const [packagePanel, setPackagePanel] = useState<PackagePanel>("templates");

  const [entryDraft, setEntryDraft] = useState<ConversationEntryPolicy>(emptyEntryPolicy());
  const [domainDraft, setDomainDraft] = useState<TaskDomainRecord>(emptyTaskDomain());
  const [taskDraft, setTaskDraft] = useState<SpecificTaskRecord>(emptySpecificTaskRecord());
  const [workflowDraft, setWorkflowDraft] = useState<WorkflowDraft>(emptyWorkflow());
  const [projectionDraft, setProjectionDraft] = useState<TaskProjectionBinding>(emptyProjectionBinding());
  const [flowDraft, setFlowDraft] = useState<TaskFlowContractBinding>(emptyFlowBinding());
  const [executionDraft, setExecutionDraft] = useState<TaskExecutionPolicy>(emptyExecutionPolicy());
  const [memoryDraft, setMemoryDraft] = useState<TaskMemoryRequestProfile>(emptyMemoryProfile());
  const [taskPolicyText, setTaskPolicyText] = useState("{}");
  const [coordinationDraft, setCoordinationDraft] = useState<CoordinationDraft>(emptyCoordination());
  const [topologyDraft, setTopologyDraft] = useState<TopologyDraft>(emptyTopology());
  const [protocolDraft, setProtocolDraft] = useState<ProtocolDraft>(emptyProtocol());
  const [packageSteps, setPackageSteps] = useState<PackageSaveStep[]>([]);
  const longformNovelPackage = useMemo(() => buildLongformNovelPackage(), []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [overview, projections, orchestration] = await Promise.all([
        getTaskSystemOverview(),
        getSoulProjectionCards().catch(() => null),
        getOrchestrationAgents().catch(() => null),
      ]);
      setConsolePayload(overview);
      setProjectionCatalog(projections);
      setOrchestrationCatalog(orchestration);
      const nextDomains = buildDomains(overview);
      const defaultDomain = nextDomains.find((item) => item.tasks.length > 0) ?? nextDomains[0];
      const preferredDomain = selectedDomainId || defaultDomain?.domain_id || "";
      const selectedDomain = nextDomains.find((item) => item.domain_id === preferredDomain) ?? defaultDomain;
      setSelectedDomainId(selectedDomain?.domain_id ?? "");
      setSelectedTaskId((current) => current || selectedDomain?.tasks[0]?.task_id || overview.task_management.specific_task_records[0]?.task_id || "");
      setSelectedCoordinationId((current) => current || overview.coordination_management.coordination_tasks[0]?.coordination_task_id || "");
      setEditorTaskId((current) => current && overview.task_management.specific_task_records.some((task) => task.task_id === current) ? current : "");
      setEditorCoordinationId((current) => current && overview.coordination_management.coordination_tasks.some((task) => task.coordination_task_id === current) ? current : "");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "任务系统加载失败");
    } finally {
      setLoading(false);
    }
  }, [selectedDomainId]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const domains = useMemo(() => buildDomains(consolePayload), [consolePayload]);
  const visibleDomains = useMemo(() => {
    if (!selectedDomainId || domains.some((item) => item.domain_id === selectedDomainId) || !domainDraft.domain_id) {
      return domains;
    }
    return [
      ...domains,
      {
        domain_id: domainDraft.domain_id,
        title: domainDraft.title,
        description: domainDraft.description,
        enabled: domainDraft.enabled,
        sort_order: domainDraft.sort_order,
        metadata: domainDraft.metadata ?? {},
        task_family: domainDraft.task_family,
        task_modes: [],
        tasks: [],
        entry_policy: null,
      },
    ].sort((a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title));
  }, [domainDraft, domains, selectedDomainId]);
  const selectedDomain = visibleDomains.find((item) => item.domain_id === selectedDomainId) ?? visibleDomains[0] ?? null;
  const tasks = useMemo(() => consolePayload?.task_management.specific_task_records ?? [], [consolePayload]);
  const workflows = useMemo(() => consolePayload?.task_management.workflow_resources ?? [], [consolePayload]);
  const taskFlowDefinitions = useMemo(() => consolePayload?.task_management.task_flow_definitions ?? [], [consolePayload]);
  const contractCatalog = useMemo(() => consolePayload?.task_management.contract_catalog ?? [], [consolePayload]);
  const contractManagement = useMemo(() => consolePayload?.contract_management ?? null, [consolePayload]);
  const contractSpecs = useMemo(() => contractManagement?.contract_specs ?? [], [contractManagement]);
  const selectedDomainTasks = useMemo(() => selectedDomain?.tasks ?? [], [selectedDomain]);
  const selectedTask = selectedDomainTasks.find((item) => item.task_id === selectedTaskId) ?? selectedDomainTasks[0] ?? null;
  const selectedTaskDomain = selectedDomain;
  const projectionBinding = (consolePayload?.task_management.projection_bindings ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const flowBinding = (consolePayload?.task_management.flow_contract_bindings ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const executionPolicy = (consolePayload?.task_management.execution_policies ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const memoryProfile = (consolePayload?.task_management.memory_request_profiles ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const selectedWorkflow = workflows.find((item) => item.workflow_id === selectedTask?.default_workflow_id);
  const allCoordinationTasks = useMemo(() => consolePayload?.coordination_management.coordination_tasks ?? [], [consolePayload]);
  const allCoordinationGraphSpecs = useMemo(() => consolePayload?.coordination_management.coordination_graph_specs ?? [], [consolePayload]);
  const allTopologyTemplates = useMemo(() => consolePayload?.coordination_management.topology_templates ?? [], [consolePayload]);
  const allCommunicationProtocols = useMemo(() => consolePayload?.coordination_management.communication_protocols ?? [], [consolePayload]);
  const a2aCatalog = consolePayload?.coordination_management.a2a ?? null;
  const activeFamily = selectedDomain?.task_family || "";
  const coordinationTasks = useMemo(
    () => allCoordinationTasks.filter((item) => coordinationFamily(item, tasks) === activeFamily),
    [activeFamily, allCoordinationTasks, tasks],
  );
  const topologyTemplates = useMemo(
    () => allTopologyTemplates.filter((item) => topologyFamily(item) === activeFamily),
    [activeFamily, allTopologyTemplates],
  );
  const communicationProtocols = useMemo(
    () => allCommunicationProtocols.filter((item) => protocolFamily(item, tasks) === activeFamily),
    [activeFamily, allCommunicationProtocols, tasks],
  );
  const selectedCoordination = coordinationTasks.find((item) => item.coordination_task_id === selectedCoordinationId) ?? coordinationTasks[0] ?? null;
  const editorTask = tasks.find((item) => item.task_id === editorTaskId) ?? null;
  const editorDomain = visibleDomains.find((domain) => domain.tasks.some((task) => task.task_id === editorTaskId)) ?? null;
  const editorFamily = editorTask?.task_family || editorDomain?.task_family || "";
  const editorDomainTasks = useMemo(() => editorDomain?.tasks ?? [], [editorDomain]);
  const editorCoordinationTasks = useMemo(
    () => editorFamily ? allCoordinationTasks.filter((item) => coordinationFamily(item, tasks) === editorFamily) : [],
    [allCoordinationTasks, editorFamily, tasks],
  );
  const editorTopologyTemplates = useMemo(
    () => editorFamily ? allTopologyTemplates.filter((item) => topologyFamily(item) === editorFamily) : [],
    [allTopologyTemplates, editorFamily],
  );
  const editorCommunicationProtocols = useMemo(
    () => editorFamily ? allCommunicationProtocols.filter((item) => protocolFamily(item, tasks) === editorFamily) : [],
    [allCommunicationProtocols, editorFamily, tasks],
  );
  const editorSelectedCoordination = editorCoordinationTasks.find((item) => item.coordination_task_id === editorCoordinationId) ?? null;
  const activeCoordination = taskLayer === "editor" ? editorSelectedCoordination : selectedCoordination;
  const activeCoordinationGraphSpec = allCoordinationGraphSpecs.find((item) => item.coordination_task_id === activeCoordination?.coordination_task_id) ?? null;
  const activeTopology = (taskLayer === "editor" ? editorTopologyTemplates : topologyTemplates).find((item) => item.template_id === activeCoordination?.topology_template_id);
  const activeProtocol = protocolForCoordination(taskLayer === "editor" ? editorCommunicationProtocols : communicationProtocols, activeCoordination, "");
  const taskModeOptions = useMemo(() => uniqueStrings(tasks.map((item) => item.task_mode)), [tasks]);
  const workflowOptions = useMemo(() => uniqueStrings(workflows.map((item) => item.workflow_id)), [workflows]);
  const commonContractOptions = useMemo(
    () => uniqueStrings([...COMMON_CONTRACT_CHOICES, ...contractCatalog.map((item) => item.contract_id), ...contractSpecs.map((item) => item.contract_id)]),
    [contractCatalog, contractSpecs],
  );
  const editorAgentGroupOptions = useMemo(
    () => uniqueStrings(editorCoordinationTasks.map((item) => item.agent_group_id)),
    [editorCoordinationTasks],
  );
  const editorDomainTaskOptions = useMemo(
    () => editorDomainTasks.map((task) => ({ value: task.task_id, label: task.task_title })),
    [editorDomainTasks],
  );
  const projectionCards = useMemo(() => projectionCatalog?.cards ?? [], [projectionCatalog]);
  const orchestrationAgents = useMemo(() => orchestrationCatalog?.agents ?? [], [orchestrationCatalog]);
  const orchestrationProfiles = useMemo(() => orchestrationCatalog?.profiles ?? [], [orchestrationCatalog]);
  const orchestrationGroups = useMemo(() => orchestrationCatalog?.agent_groups ?? [], [orchestrationCatalog]);
  const longformProjectionStatuses = useMemo(() => longformNovelPackage.requiredProjections.map((projection) => {
    const card = projectionCards.find((item) => item.projection_id === projection.projection_id);
    const content = [
      card?.identity_anchor,
      card?.projection_prompt,
      ...(card?.projection_nodes ?? []).map((node) => String(node.content ?? "")),
    ].join("\n").trim();
    const status: PackagePrerequisiteStatus = card ? (content ? "ready" : "partial") : "missing";
    return { ...projection, status, detail: card ? (content ? "身份锚点已写入" : "投影存在但身份锚点为空") : "需要在投影系统创建" };
  }), [longformNovelPackage.requiredProjections, projectionCards]);
  const longformAgentStatuses = useMemo(() => longformNovelPackage.requiredAgents.map((agent) => {
    const descriptor = orchestrationAgents.find((item) => String(item.agent_id ?? "") === agent.agent_id);
    const profile = orchestrationProfiles.find((item) => item.agent_profile_id === agent.agent_id || item.agent_id === agent.agent_id) ?? descriptor?.runtime_profile;
    const projectionOk = String(descriptor?.default_projection_id ?? "") === agent.projection_id;
    const contractsOk = runtimeProfileHasAll(profile, "output_contracts", agent.output_contracts);
    const operationsOk = runtimeProfileHasAll(profile, "allowed_operations", agent.allowed_operations);
    const memoryOk = runtimeProfileHasAll(profile, "allowed_memory_scopes", agent.allowed_memory_scopes);
    const status: PackagePrerequisiteStatus = descriptor && projectionOk && contractsOk && operationsOk && memoryOk ? "ready" : descriptor ? "partial" : "missing";
    const missing = [
      projectionOk ? "" : "投影绑定",
      contractsOk ? "" : "输出契约",
      operationsOk ? "" : "操作权限",
      memoryOk ? "" : "记忆范围",
    ].filter(Boolean).join("、");
    return { ...agent, status, detail: descriptor ? (missing || "RuntimeProfile 已对齐") : "需要在编排系统创建 Agent" };
  }), [longformNovelPackage.requiredAgents, orchestrationAgents, orchestrationProfiles]);
  const longformGroupStatus = useMemo(() => {
    const group = orchestrationGroups.find((item) => item.group_id === "group.longform_novel_core_team");
    if (!group) return { status: "missing" as PackagePrerequisiteStatus, detail: "需要在编排系统创建 AgentGroup" };
    const memberSet = new Set(group.member_agent_ids ?? []);
    const membersOk = longformNovelPackage.requiredAgents.slice(1).every((agent) => memberSet.has(agent.agent_id));
    const coordinatorOk = group.coordinator_agent_id === longformNovelPackage.requiredAgents[0]?.agent_id;
    return {
      status: coordinatorOk && membersOk ? "ready" as PackagePrerequisiteStatus : "partial" as PackagePrerequisiteStatus,
      detail: coordinatorOk && membersOk ? "核心团队成员已对齐" : "协调者或成员列表需补齐",
    };
  }, [longformNovelPackage.requiredAgents, orchestrationGroups]);
  const longformPrerequisiteReadyCount = [
    ...longformProjectionStatuses,
    ...longformAgentStatuses,
    longformGroupStatus,
  ].filter((item) => item.status === "ready").length;
  const longformPrerequisiteTotal = longformProjectionStatuses.length + longformAgentStatuses.length + 1;
  const contractViews = useMemo<ContractView[]>(() => (
    contractSpecs.map((contract) => ({
      key: `${contract.contract_kind}:${contract.contract_id}`,
      title: contractSpecTitle(contract),
      kind: CONTRACT_KIND_LABELS[contract.contract_kind] || contract.contract_kind,
      usage: contract.description || "通用 ContractSpec",
      source: contract.metadata?.default_seed ? "内置通用契约" : "用户契约库",
      raw: contract.contract_id,
    }))
  ), [contractSpecs]);

  const sendTaskToChat = useCallback((task: SpecificTaskRecord | null, domain: DomainRecord | null) => {
    if (!task) return;
    setTaskSelection({
      selected_task_id: task.task_id,
      domain_id: domain?.domain_id || "",
      label: task.task_title,
      mode: "single_task",
    });
    setWorkspaceView("chat");
    setNotice(`已将特定任务“${task.task_title}”带入主会话。`);
  }, [setTaskSelection, setWorkspaceView]);

  const sendCoordinationToChat = useCallback((task: CoordinationTask | null, domain: DomainRecord | null) => {
    if (!task) return;
    const subtaskId = coordinationSubtaskRefs(task)[0] || "";
    setTaskSelection({
      selected_task_id: subtaskId,
      coordination_task_id: task.coordination_task_id,
      domain_id: domain?.domain_id || task.domain_id || "",
      label: task.title,
      mode: "coordination",
    });
    setWorkspaceView("chat");
    setNotice(`已将协调任务“${task.title}”带入主会话。`);
  }, [setTaskSelection, setWorkspaceView]);
  useEffect(() => {
    if (!selectedDomain) return;
    setDomainDraft({
      domain_id: selectedDomain.domain_id,
      task_family: selectedDomain.task_family,
      title: selectedDomain.title,
      description: selectedDomain.description,
      enabled: selectedDomain.enabled,
      sort_order: selectedDomain.sort_order,
      metadata: selectedDomain.metadata ?? {},
    });
    setEntryDraft(selectedDomain.entry_policy ?? emptyEntryPolicy(workflows[0]?.workflow_id ?? "", ""));
  }, [selectedDomain, workflows]);

  useEffect(() => {
    if (!selectedDomain) return;
    if (!selectedDomain.tasks.some((item) => item.task_id === selectedTaskId)) {
      setSelectedTaskId(selectedDomain.tasks[0]?.task_id || "");
    }
  }, [selectedDomain, selectedTaskId]);

  useEffect(() => {
    if (!coordinationTasks.some((item) => item.coordination_task_id === selectedCoordinationId)) {
      setSelectedCoordinationId(coordinationTasks[0]?.coordination_task_id || "");
    }
  }, [coordinationTasks, selectedCoordinationId]);

  useEffect(() => {
    if (!editorTaskId) {
      if (editorCoordinationId) setEditorCoordinationId("");
      return;
    }
    if (!editorCoordinationTasks.some((item) => item.coordination_task_id === editorCoordinationId)) {
      setEditorCoordinationId(editorCoordinationTasks[0]?.coordination_task_id || "");
    }
  }, [editorCoordinationId, editorCoordinationTasks, editorTaskId]);

  useEffect(() => {
    if (!selectedTask) return;
    setTaskDraft({ ...selectedTask, metadata: selectedTask.metadata ?? {}, task_policy: selectedTask.task_policy ?? {} });
    setTaskPolicyText(JSON.stringify(selectedTask.task_policy ?? {}, null, 2));
    setWorkflowDraft(workflowDraftFrom(selectedWorkflow, selectedTask.task_mode));
    setProjectionDraft(projectionBinding ?? emptyProjectionBinding(selectedTask.task_id, ""));
    setFlowDraft(flowBinding ?? emptyFlowBinding(selectedTask.task_id, selectedTask.default_flow_contract_id));
    setExecutionDraft(executionPolicy ?? emptyExecutionPolicy(selectedTask.task_id));
    setMemoryDraft(memoryProfile ?? emptyMemoryProfile(selectedTask.task_id));
  }, [selectedTask, selectedWorkflow, projectionBinding, flowBinding, executionPolicy, memoryProfile]);

  useEffect(() => {
    setCoordinationDraft(coordinationDraftFrom(activeCoordination));
    const nextTopology = topologyDraftFrom(activeTopology);
    const nextNodes = activeCoordination?.graph_nodes?.length ? activeCoordination.graph_nodes : (nextTopology.nodes ?? []);
    const nextEdges = activeCoordination?.graph_edges?.length ? activeCoordination.graph_edges : (nextTopology.edges ?? []);
    setTopologyDraft({
      ...nextTopology,
      nodes: nextNodes,
      edges: nextEdges,
      nodes_text: JSON.stringify(nextNodes, null, 2),
      edges_text: JSON.stringify(nextEdges, null, 2),
    });
    setProtocolDraft(protocolDraftFrom(activeProtocol));
    setSelectedGraphNodeId(String((activeCoordination?.graph_nodes ?? [])[0]?.node_id ?? ""));
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }, [activeCoordination, activeTopology, activeProtocol]);

  async function createTaskDraft() {
    setSaving("task-create");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const nextTask = emptySpecificTaskRecord(ids.workflow_id, ids.flow_id);
      nextTask.task_id = ids.task_id;
      nextTask.task_family = selectedDomain?.task_family || nextTask.task_family;
      nextTask.task_mode = selectedDomain?.task_modes[0] || nextTask.task_mode;
      nextTask.task_title = `${ids.display_numbers.task} 特定任务`;
      nextTask.default_flow_contract_id = ids.flow_id;
      nextTask.default_workflow_id = ids.workflow_id;
      setSelectedTaskId(nextTask.task_id);
      setTaskLayer("management");
      setTaskConfigPanel("definition");
      setTaskDraft(nextTask);
      setTaskPolicyText(JSON.stringify(nextTask.task_policy, null, 2));
      setWorkflowDraft({ ...emptyWorkflow(nextTask.task_mode), workflow_id: ids.workflow_id, title: `${ids.display_numbers.workflow} Workflow` });
      setProjectionDraft(emptyProjectionBinding(nextTask.task_id, ""));
      setFlowDraft(emptyFlowBinding(nextTask.task_id, ids.flow_id));
      setExecutionDraft(emptyExecutionPolicy(nextTask.task_id));
      setMemoryDraft(emptyMemoryProfile(nextTask.task_id));
      setNotice("已生成任务草稿，请补充任务名称与装配配置后保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "生成任务草稿失败");
    } finally {
      setSaving("");
    }
  }

  function createDomainDraft() {
    const index = visibleDomains.length + 1;
    const draft = emptyTaskDomain(index);
    draft.domain_id = `domain.custom_${index}`;
    draft.task_family = `custom_${index}`;
    draft.title = `新任务域 ${index}`;
    draft.metadata = { ...(draft.metadata ?? {}), draft_identity_locked: true };
    setDomainDraft(draft);
    setSelectedDomainId(draft.domain_id);
    setSelectedTaskId("");
    setTaskLayer("management");
    setEditingDomainName(true);
    setNotice("已生成任务域草稿，请填写名称后保存。");
  }

  function updateDomainTitle(title: string) {
    setDomainDraft((value) => ({ ...value, title }));
  }

  function previewLongformNovelPackage() {
    const pack = longformNovelPackage;
    setDomainDraft(pack.domain);
    setTaskDraft(pack.task);
    setTaskPolicyText(JSON.stringify(pack.task.task_policy, null, 2));
    setWorkflowDraft(pack.workflow);
    setProjectionDraft(emptyProjectionBinding(pack.task.task_id, ""));
    setFlowDraft(emptyFlowBinding(pack.task.task_id, pack.task.default_flow_contract_id));
    setExecutionDraft(pack.execution);
    setMemoryDraft(pack.memory);
    setCoordinationDraft(pack.coordination);
    setTopologyDraft(pack.topology);
    setProtocolDraft(pack.protocol);
    setSelectedDomainId(pack.domain.domain_id);
    setSelectedTaskId(pack.task.task_id);
    setSelectedCoordinationId(pack.coordination.coordination_task_id);
    setSelectedGraphNodeId("input_brief");
    setSelectedGraphEdgeId("");
    setTaskLayer("management");
    setTaskConfigPanel("package");
    setPackagePanel("draft");
    setNotice("已生成长篇小说任务包草案。Agent 和 AgentGroup 仍需在编排系统前端配置。");
  }

  async function saveLongformNovelPackage() {
    const pack = longformNovelPackage;
    const domainPayload = { ...pack.domain, ...domainDraft };
    const taskPayload = { ...pack.task, ...taskDraft, task_policy: taskPolicyObject };
    const workflowPayload = { ...pack.workflow, ...workflowDraft };
    const executionPayload = { ...pack.execution, ...executionDraft };
    const memoryPayload = { ...pack.memory, ...memoryDraft };
  const protocolPayload = { ...pack.protocol, ...protocolDraft };
  const topologyPayload = { ...pack.topology, ...topologyDraft };
  const coordinationPayload = { ...pack.coordination, ...coordinationDraft };
  const projectionPayload = {
    ...emptyProjectionBinding(taskPayload.task_id, pack.requiredProjections[0]?.projection_id || ""),
    task_id: taskPayload.task_id,
    projection_selection_mode: "task_graph_agent_projection",
    allowed_projection_ids: pack.requiredProjections.map((item) => item.projection_id),
    default_projection_id: pack.requiredProjections[0]?.projection_id || "",
    projection_required: true,
    notes: "长篇小说任务使用任务图节点 Agent 的专属投影；具体 prompt 在投影卡身份锚点中维护。",
    metadata: { task_family: domainPayload.task_family, managed_by: "task_package_wizard", package_template: "longform_novel_writing" },
  };
  const graphPayload = {
    ...pack.graph,
    domain_id: domainPayload.domain_id,
    task_family: domainPayload.task_family,
    nodes: topologyPayload.nodes,
    edges: topologyPayload.edges,
    default_protocol_id: protocolPayload.protocol_id,
      metadata: {
        ...dictOf(pack.graph.metadata),
        coordination_task_id: coordinationPayload.coordination_task_id,
        package_template: "longform_novel_writing",
      },
    };
    const steps: PackageSaveStep[] = [
      { id: "domain", label: "任务域", status: "pending", detail: domainPayload.domain_id },
      { id: "contracts", label: "ContractSpec 批量契约", status: "pending", detail: `${pack.contracts.length} 个契约` },
      { id: "workflow", label: "Workflow", status: "pending", detail: workflowPayload.workflow_id },
      { id: "task", label: "SpecificTask", status: "pending", detail: taskPayload.task_id },
      { id: "projection", label: "投影绑定", status: "pending", detail: `${projectionPayload.allowed_projection_ids.length} 个专属投影` },
      { id: "execution", label: "执行策略", status: "pending", detail: taskPayload.task_id },
      { id: "memory", label: "记忆请求策略", status: "pending", detail: memoryPayload.working_memory_policy_profile_id || taskPayload.task_id },
      { id: "protocol", label: "A2A 通信协议", status: "pending", detail: protocolPayload.protocol_id },
      { id: "topology", label: "拓扑模板", status: "pending", detail: topologyPayload.template_id },
      { id: "coordination", label: "协调任务", status: "pending", detail: coordinationPayload.coordination_task_id },
      { id: "graph", label: "任务图", status: "pending", detail: graphPayload.graph_id },
    ];
    const updateStep = (id: string, status: PackageSaveStep["status"], detail = "") => {
      setPackageSteps((current) => current.map((step) => step.id === id ? { ...step, status, detail: detail || step.detail } : step));
    };
    setPackageSteps(steps);
    setSaving("package");
    setError("");
    setNotice("");
    try {
      let payload = await upsertTaskSystemDomain(domainPayload.domain_id, domainPayload);
      updateStep("domain", "success");
      for (const contract of pack.contracts) {
        payload = await upsertTaskSystemContract(contract.contract_id, contract);
      }
      updateStep("contracts", "success");
      await upsertTaskWorkflow(workflowPayload.workflow_id, {
        ...workflowPayload,
        compatible_projection_ids: workflowPayload.compatible_projection_ids,
        visible_skill_ids: workflowPayload.visible_skill_ids,
        steps: workflowPayload.steps,
        stop_conditions: workflowPayload.stop_conditions,
        required_evidence_refs: workflowPayload.required_evidence_refs,
      });
      updateStep("workflow", "success");
      await upsertTaskSystemSpecificRecord(taskPayload.task_id, taskPayload);
      updateStep("task", "success");
      await upsertTaskSystemProjectionBinding(taskPayload.task_id, projectionPayload);
      updateStep("projection", "success");
      await upsertTaskSystemExecutionPolicy(taskPayload.task_id, executionPayload);
      updateStep("execution", "success");
      await upsertTaskSystemMemoryRequestProfile(taskPayload.task_id, memoryPayload);
      updateStep("memory", "success");
      await upsertTaskSystemCommunicationProtocol(protocolPayload.protocol_id, protocolPayload);
      updateStep("protocol", "success");
      await upsertTaskSystemTopologyTemplate(topologyPayload.template_id, {
        ...topologyPayload,
        handoff_rules: [],
      });
      updateStep("topology", "success");
      await upsertTaskSystemCoordinationTask(coordinationPayload.coordination_task_id, coordinationPayload);
      updateStep("coordination", "success");
      payload = await upsertTaskSystemTaskGraph(graphPayload.graph_id, graphPayload);
      updateStep("graph", "success");
      setConsolePayload(payload);
      setSelectedDomainId(domainPayload.domain_id);
      setSelectedTaskId(taskPayload.task_id);
      setSelectedCoordinationId(coordinationPayload.coordination_task_id);
      setPackagePanel("pipeline");
      setNotice("长篇小说任务包的任务层资产已通过正式 API 保存。请到编排系统创建并配置 Agent / AgentGroup。");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "保存长篇小说任务包失败";
      setPackageSteps((current) => {
        const pending = current.find((step) => step.status === "pending");
        return pending
          ? current.map((step) => step.id === pending.id ? { ...step, status: "error", detail: message } : step)
          : current;
      });
      setError(message);
    } finally {
      setSaving("");
    }
  }

  function addCoordinationNode() {
    const existingNodes = topologyDraft.nodes ?? [];
    const nextIndex = existingNodes.length + 1;
    const existingTaskIds = new Set(existingNodes.map((node) => graphNodeTaskId(node)).filter(Boolean));
    const nextTask = graphContextDomainTasks.find((task) => !existingTaskIds.has(task.task_id));
    const nodeId = nextTask ? `subtask_${nextIndex}` : `agent_${nextIndex}`;
    setTopologyDraft((current) => {
      const node = {
        node_id: nodeId,
        node_type: nextTask ? "subtask" : "agent_role",
        task_id: nextTask?.task_id ?? "",
        task_title: nextTask?.task_title ?? "",
        task_family: graphContextFamily,
        agent_id: "",
        role: "participant",
        label: nextTask?.task_title ?? `节点 ${nextIndex}`,
      };
      return {
        ...current,
        nodes: [...(current.nodes ?? []), node],
        nodes_text: JSON.stringify([...(current.nodes ?? []), node], null, 2),
      };
    });
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function addCoordinationTaskNode(task: SpecificTaskRecord, role = "participant") {
    const nodeId = `subtask_${String((topologyDraft.nodes?.length || 0) + 1)}`;
    const node = {
      node_id: nodeId,
      node_type: "subtask",
      task_id: task.task_id,
      task_title: task.task_title,
      task_family: task.task_family || graphContextFamily,
      agent_id: "",
      role,
      label: task.task_title,
      title: task.task_title,
    };
    setTopologyDraft((current) => {
      const nextNodes = [...(current.nodes ?? []), node];
      return {
        ...current,
        nodes: nextNodes,
        nodes_text: JSON.stringify(nextNodes, null, 2),
      };
    });
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function addCoordinationRoleNode(role: string) {
    const nextIndex = (topologyDraft.nodes?.length || 0) + 1;
    const nodeId = role === "coordinator" ? `coordinator_${nextIndex}` : `agent_${nextIndex}`;
    const titleByRole: Record<string, string> = {
      coordinator: "协调器",
      planner: "规划节点",
      executor: "执行节点",
      reviewer: "审查节点",
      verifier: "验证节点",
      summarizer: "整理节点",
      merge: "汇总节点",
      writer: "执行节点",
      acceptance: "验收节点",
      participant: "协作节点",
    };
    const node = {
      node_id: nodeId,
      node_type: "agent_role",
      task_id: "",
      task_title: "",
      task_family: graphContextFamily,
      agent_id: "",
      role,
      work_posture: role,
      label: titleByRole[role] ?? "协作节点",
      title: titleByRole[role] ?? "协作节点",
    };
    setTopologyDraft((current) => ({
      ...current,
      nodes: [...(current.nodes ?? []), node],
      nodes_text: JSON.stringify([...(current.nodes ?? []), node], null, 2),
    }));
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function applyCoordinationGraphTemplate(template: "single_agent" | "multi_sequence" | "multi_parallel_merge") {
    const shouldReplace = !(topologyDraft.nodes?.length || topologyDraft.edges?.length)
      || window.confirm("应用图模板会替换当前未保存的拓扑草稿，确认继续吗？");
    if (!shouldReplace) return;
    const domainFamily = graphContextFamily;
    const makeNode = (nodeId: string, role: string, title: string) => ({
      node_id: nodeId,
      node_type: role === "merge" ? "merge" : "agent_role",
      task_id: "",
      task_title: "",
      task_family: domainFamily,
      agent_id: "",
      role,
      work_posture: role,
      label: title,
      title,
    });
    const mode = coordinationDraft.communication_modes?.[0] || "structured_handoff";
    const makeEdge = (edgeId: string, from: string, to: string, edgeType = "handoff") => ({
      edge_id: edgeId,
      from,
      to,
      source_node_id: from,
      target_node_id: to,
      edge_type: edgeType,
      mode,
      policy: mode,
    });
    const selectedTaskForNode = graphContextTask ?? graphContextDomainTasks[0] ?? null;
    const nodes = template === "single_agent"
      ? [
        makeNode("input_1", "input", "任务输入"),
        {
          ...makeNode("agent_1", "executor", selectedTaskForNode?.task_title || "Agent 执行节点"),
          node_type: "subtask",
          task_id: selectedTaskForNode?.task_id || "",
          task_title: selectedTaskForNode?.task_title || "",
        },
        makeNode("output_1", "output", "最终输出"),
      ]
      : template === "multi_parallel_merge"
      ? [
        makeNode("agent_a", "executor", "Agent A"),
        makeNode("agent_b", "reviewer", "Agent B"),
        makeNode("merge_1", "merge", "汇总节点"),
      ]
      : [
        makeNode("agent_a", "planner", "Agent A"),
        makeNode("agent_b", "executor", "Agent B"),
      ];
    const edges = template === "single_agent"
      ? [
        makeEdge("edge_input_agent", "input_1", "agent_1", "handoff"),
        makeEdge("edge_agent_output", "agent_1", "output_1", "finalize"),
      ]
      : template === "multi_parallel_merge"
      ? [
        makeEdge("edge_1", "agent_a", "merge_1", "parallel_join"),
        makeEdge("edge_2", "agent_b", "merge_1", "parallel_join"),
      ]
      : [
        makeEdge("edge_1", "agent_a", "agent_b", "handoff"),
      ];
    setTopologyDraft((current) => ({
      ...current,
      nodes,
      edges,
      nodes_text: JSON.stringify(nodes, null, 2),
      edges_text: JSON.stringify(edges, null, 2),
    }));
    setSelectedGraphNodeId(nodes[0]?.node_id ?? "");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
    setTaskLayer("editor");
  }

  function addCoordinationSuccessorNode(fromNodeId: string) {
    const nextIndex = (topologyDraft.nodes?.length || 0) + 1;
    const nodeId = `agent_${nextIndex}`;
    const node = {
      node_id: nodeId,
      node_type: "agent_role",
      task_id: "",
      task_title: "",
      task_family: graphContextFamily,
      agent_id: "",
      role: "participant",
      label: `节点 ${nextIndex}`,
      title: `节点 ${nextIndex}`,
    };
    const edge = {
      edge_id: `edge_${String((topologyDraft.edges?.length || 0) + 1)}`,
      from: fromNodeId,
      to: nodeId,
      source_node_id: fromNodeId,
      target_node_id: nodeId,
      mode: coordinationDraft.communication_modes?.[0] || "structured_handoff",
    };
    setTopologyDraft((current) => {
      const nextNodes = [...(current.nodes ?? []), node];
      const nextEdges = [...(current.edges ?? []), edge];
      return {
        ...current,
        nodes: nextNodes,
        edges: nextEdges,
        nodes_text: JSON.stringify(nextNodes, null, 2),
        edges_text: JSON.stringify(nextEdges, null, 2),
      };
    });
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }

  function updateCoordinationNode(nodeId: string, patch: Record<string, unknown>) {
    setTopologyDraft((current) => {
      const nextNodes = (current.nodes ?? []).map((node) =>
        String(node.node_id ?? "") === nodeId ? { ...node, ...patch } : node,
      );
      return {
        ...current,
        nodes: nextNodes,
        nodes_text: JSON.stringify(nextNodes, null, 2),
      };
    });
  }

  function removeCoordinationNode(nodeId: string) {
    setTopologyDraft((current) => {
      const nextNodes = (current.nodes ?? []).filter((node) => String(node.node_id ?? "") !== nodeId);
      const nextEdges = (current.edges ?? []).filter(
        (edge) => graphEdgeSource(edge) !== nodeId && graphEdgeTarget(edge) !== nodeId,
      );
      return {
        ...current,
        nodes: nextNodes,
        edges: nextEdges,
        nodes_text: JSON.stringify(nextNodes, null, 2),
        edges_text: JSON.stringify(nextEdges, null, 2),
      };
    });
    if (selectedGraphNodeId === nodeId) setSelectedGraphNodeId("");
    if (linkingFromNodeId === nodeId) setLinkingFromNodeId("");
  }

  function addCoordinationEdge() {
    setTopologyDraft((current) => {
      const nodes = current.nodes ?? [];
      if (nodes.length < 2) return current;
      const from = selectedGraphNodeId && nodes.some((node) => String(node.node_id ?? "") === selectedGraphNodeId)
        ? selectedGraphNodeId
        : String(nodes[0]?.node_id ?? "");
      const to = String(nodes.find((node) => String(node.node_id ?? "") !== from)?.node_id ?? "");
      if (!from || !to) return current;
      const nextIndex = (current.edges?.length || 0) + 1;
      const edge = { edge_id: `edge_${nextIndex}`, from, to, source_node_id: from, target_node_id: to, mode: coordinationDraft.communication_modes?.[0] || "structured_handoff" };
      setSelectedGraphEdgeId(graphEdgeId(edge, nextIndex - 1));
      setSelectedGraphNodeId("");
      const nextEdges = [
        ...(current.edges ?? []),
        edge,
      ];
      return {
        ...current,
        edges: nextEdges,
        edges_text: JSON.stringify(nextEdges, null, 2),
      };
    });
  }

  function connectSelectedNodeTo(targetNodeId: string) {
    const from = selectedGraphNodeId;
    const to = targetNodeId;
    if (!from || !to || from === to) return;
    setTopologyDraft((current) => {
      const exists = (current.edges ?? []).some((edge) => graphEdgeSource(edge) === from && graphEdgeTarget(edge) === to);
      if (exists) return current;
      const nextIndex = (current.edges?.length || 0) + 1;
      const edge = {
        edge_id: `edge_${nextIndex}`,
        from,
        to,
        source_node_id: from,
        target_node_id: to,
        mode: coordinationDraft.communication_modes?.[0] || "structured_handoff",
      };
      setSelectedGraphEdgeId(graphEdgeId(edge, nextIndex - 1));
      setSelectedGraphNodeId("");
      const nextEdges = [...(current.edges ?? []), edge];
      return {
        ...current,
        edges: nextEdges,
        edges_text: JSON.stringify(nextEdges, null, 2),
      };
    });
  }

  function handleTopologyNodeClick(nodeId: string) {
    if (linkingFromNodeId) {
      if (linkingFromNodeId !== nodeId) {
        const from = linkingFromNodeId;
        const to = nodeId;
        setTopologyDraft((current) => {
          const exists = (current.edges ?? []).some((edge) => graphEdgeSource(edge) === from && graphEdgeTarget(edge) === to);
          if (exists) return current;
          const nextIndex = (current.edges?.length || 0) + 1;
          const edge = {
            edge_id: `edge_${nextIndex}`,
            from,
            to,
            source_node_id: from,
            target_node_id: to,
            mode: coordinationDraft.communication_modes?.[0] || "structured_handoff",
          };
          setSelectedGraphEdgeId(graphEdgeId(edge, nextIndex - 1));
          const nextEdges = [...(current.edges ?? []), edge];
          return {
            ...current,
            edges: nextEdges,
            edges_text: JSON.stringify(nextEdges, null, 2),
          };
        });
      }
      setLinkingFromNodeId("");
      setSelectedGraphNodeId("");
      return;
    }
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function cycleCoordinationNodeRole(nodeId: string, currentRole: string) {
    const roles = ["participant", "writer", "reviewer", "acceptance"];
    const currentIndex = roles.indexOf(currentRole);
    const nextRole = roles[(currentIndex + 1) % roles.length] ?? "participant";
    updateCoordinationNode(nodeId, { role: nextRole });
  }

  function updateCoordinationEdge(edgeId: string, patch: Record<string, unknown>) {
    setTopologyDraft((current) => {
      const nextEdges = (current.edges ?? []).map((edge, index) =>
        graphEdgeId(edge, index) === edgeId ? { ...edge, ...patch } : edge,
      );
      return {
        ...current,
        edges: nextEdges,
        edges_text: JSON.stringify(nextEdges, null, 2),
      };
    });
  }

  function cycleCoordinationEdgeMode(edgeId: string, currentMode: string) {
    const modes = coordinationDraft.communication_modes?.length ? coordinationDraft.communication_modes : GRAPH_EDGE_MODE_CHOICES;
    const currentIndex = modes.indexOf(currentMode);
    const nextMode = modes[(currentIndex + 1) % modes.length] ?? "structured_handoff";
    updateCoordinationEdge(edgeId, { mode: nextMode, policy: nextMode });
  }

  function reverseCoordinationEdge(edgeId: string) {
    setTopologyDraft((current) => {
      const nextEdges = (current.edges ?? []).map((edge, index) => {
        if (graphEdgeId(edge, index) !== edgeId) {
          return edge;
        }
        const from = graphEdgeSource(edge);
        const to = graphEdgeTarget(edge);
        return {
          ...edge,
          from: to,
          to: from,
          source_node_id: to,
          target_node_id: from,
        };
      });
      return {
        ...current,
        edges: nextEdges,
        edges_text: JSON.stringify(nextEdges, null, 2),
      };
    });
  }

  function removeCoordinationEdge(edgeId: string) {
    setTopologyDraft((current) => {
      const nextEdges = (current.edges ?? []).filter((edge, index) => graphEdgeId(edge, index) !== edgeId);
      return {
        ...current,
        edges: nextEdges,
        edges_text: JSON.stringify(nextEdges, null, 2),
      };
    });
    if (selectedGraphEdgeId === edgeId) setSelectedGraphEdgeId("");
  }

  function saveTopologyDraftIntoCoordination() {
    const nextNodes = (topologyDraft.nodes ?? []).map((node) => ({ ...node }));
    const nextEdges = (topologyDraft.edges ?? []).map((edge) => ({ ...edge }));
    setCoordinationDraft((current) => ({
      ...current,
      graph_nodes: nextNodes,
      graph_edges: nextEdges,
      subtask_refs: coordinationSubtaskRefs({ ...current, graph_nodes: nextNodes }),
    }));
    setTopologyDraft((current) => ({
      ...current,
      nodes_text: JSON.stringify(current.nodes ?? [], null, 2),
      edges_text: JSON.stringify(current.edges ?? [], null, 2),
    }));
    setNotice("拓扑草稿已同步到协调任务，接下来可继续保存草稿或发布。");
    setError("");
  }

  async function createCoordinationDraft() {
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftTask = taskLayer === "editor" ? editorTask : selectedTask;
    const draftFamily = draftTask?.task_family || draftDomain?.task_family || "";
    const draftDomainId = draftDomain?.domain_id || "";
    if (taskLayer === "editor" && !draftTask) {
      setError("请先在图编辑器中打开一个任务。");
      return;
    }
    setSaving("coordination-create");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const coordination = emptyCoordination(
        ids.topology_template_id,
        `protocol.${ids.coordination_task_id.replace(/^coord\./, "")}`,
        draftFamily,
        draftDomainId,
      );
      coordination.coordination_task_id = ids.coordination_task_id;
      coordination.title = `${ids.display_numbers.coordination} 协调任务`;
      coordination.topology_template_id = ids.topology_template_id;
      coordination.task_family = draftFamily;
      coordination.domain_id = draftDomainId;
      coordination.metadata = {
        ...(coordination.metadata ?? {}),
        task_family: draftFamily,
        domain_id: draftDomainId,
        task_id: draftTask?.task_id || "",
      };
      const topology = emptyTopology();
      topology.template_id = ids.topology_template_id;
      topology.title = `${ids.display_numbers.topology} 拓扑`;
      topology.metadata = {
        ...(topology.metadata ?? {}),
        task_family: draftFamily,
        domain_id: draftDomainId,
        task_id: draftTask?.task_id || "",
      };
      const protocol = emptyProtocol();
      protocol.protocol_id = String(coordination.metadata?.protocol_id || protocol.protocol_id);
      protocol.title = `${ids.display_numbers.coordination} 协议`;
      protocol.metadata = {
        ...(protocol.metadata ?? {}),
        task_family: draftFamily,
        domain_id: draftDomainId,
        task_id: draftTask?.task_id || "",
      };
      if (taskLayer === "editor") {
        setEditorCoordinationId(coordination.coordination_task_id);
      } else {
        setSelectedCoordinationId(coordination.coordination_task_id);
      }
      setTaskLayer("editor");
      setCoordinationDraft(coordination);
      setTopologyDraft(topology);
      setProtocolDraft(protocol);
      setNotice(`已生成协调任务草稿：${coordination.coordination_task_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "生成协调任务草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function duplicateCoordinationDraft() {
    const sourceCoordination = taskLayer === "editor" ? editorSelectedCoordination : selectedCoordination;
    if (!sourceCoordination) {
      setError("当前没有可复制的协调任务");
      return;
    }
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftFamily = draftDomain?.task_family || coordinationDraft.task_family || "";
    const draftDomainId = draftDomain?.domain_id || coordinationDraft.domain_id || "";
    setSaving("coordination-duplicate");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const nextCoordinationId = ids.coordination_task_id;
      const nextTopologyId = ids.topology_template_id;
      const nextProtocolId = `protocol.${nextCoordinationId.replace(/^coord\./, "")}`;
      const nextTitle = `${sourceCoordination.title || ids.display_numbers.coordination} 副本`;
      const nextCoordination: CoordinationDraft = {
        ...coordinationDraft,
        coordination_task_id: nextCoordinationId,
        title: nextTitle,
        topology_template_id: nextTopologyId,
        enabled: false,
        stop_conditions_text: coordinationDraft.stop_conditions_text,
        graph_nodes: (coordinationDraft.graph_nodes ?? []).map((node) => ({ ...node })),
        graph_edges: (coordinationDraft.graph_edges ?? []).map((edge) => ({ ...edge })),
        subtask_refs: coordinationSubtaskRefs(coordinationDraft),
        metadata: {
          ...(coordinationDraft.metadata ?? {}),
          protocol_id: nextProtocolId,
          task_family: draftFamily,
          domain_id: draftDomainId,
        },
      };
      const nextTopology: TopologyDraft = {
        ...topologyDraft,
        template_id: nextTopologyId,
        title: `${topologyDraft.title || nextTitle} 副本`,
        enabled: false,
        nodes: nextCoordination.graph_nodes ?? [],
        edges: nextCoordination.graph_edges ?? [],
        nodes_text: JSON.stringify(nextCoordination.graph_nodes ?? [], null, 2),
        edges_text: JSON.stringify(nextCoordination.graph_edges ?? [], null, 2),
        metadata: {
          ...(topologyDraft.metadata ?? {}),
          task_family: draftFamily,
          domain_id: draftDomainId,
        },
      };
      const nextProtocol: ProtocolDraft = {
        ...protocolDraft,
        protocol_id: nextProtocolId,
        title: `${protocolDraft.title || nextTitle} 副本`,
        enabled: false,
        metadata: {
          ...(protocolDraft.metadata ?? {}),
          task_family: draftFamily,
          domain_id: draftDomainId,
        },
      };
      if (taskLayer === "editor") {
        setEditorCoordinationId(nextCoordinationId);
      } else {
        setSelectedCoordinationId(nextCoordinationId);
      }
      setTaskLayer("editor");
      setCoordinationDraft(nextCoordination);
      setTopologyDraft(nextTopology);
      setProtocolDraft(nextProtocol);
      setSelectedGraphNodeId(String((nextCoordination.graph_nodes ?? [])[0]?.node_id ?? ""));
      setSelectedGraphEdgeId("");
      setLinkingFromNodeId("");
      setNotice(`已复制协调任务草稿：${nextCoordinationId}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "复制协调任务草稿失败");
    } finally {
      setSaving("");
    }
  }

  function setCoordinationPublished(enabled: boolean) {
    setCoordinationDraft((current) => ({
      ...current,
      enabled,
    }));
    setTopologyDraft((current) => ({
      ...current,
      enabled,
    }));
    setProtocolDraft((current) => ({
      ...current,
      enabled,
    }));
  }

  async function saveEntry() {
    setSaving("entry");
    setError("");
    setNotice("");
    try {
      const payload = await upsertTaskSystemEntryPolicy(entryDraft.profile_id, entryDraft);
      setConsolePayload(payload);
      setNotice("入口识别已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存入口识别失败");
    } finally {
      setSaving("");
    }
  }

  async function saveDomain() {
    setSaving("domain");
    setError("");
    setNotice("");
    try {
      const isNewDraft = !domains.some((domain) => domain.domain_id === domainDraft.domain_id);
      const normalizedFamily = domainDraft.task_family || domainDraft.domain_id.replace(/^domain\./, "") || slugFromTitle(domainDraft.title);
      const normalizedDomainId = domainDraft.domain_id || `domain.${normalizedFamily}`;
      const payload = await upsertTaskSystemDomain(normalizedDomainId, {
        ...domainDraft,
        domain_id: normalizedDomainId,
        task_family: normalizedFamily,
        title: domainDraft.title.trim() || `${normalizedFamily}任务域`,
        metadata: {
          ...(domainDraft.metadata ?? {}),
        },
      });
      setConsolePayload(payload);
      setSelectedDomainId(normalizedDomainId);
      setEditingDomainName(false);
      setNotice(isNewDraft ? "新任务域已保存。" : "任务域名称已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务域失败");
    } finally {
      setSaving("");
    }
  }

  async function deleteDomain(domain: DomainRecord) {
    const confirmed = window.confirm(`删除「${domain.title}」会同时删除该任务域下的 ${domain.tasks.length} 个特定任务及其装配配置。确认删除？`);
    if (!confirmed) return;
    setSaving("domain-delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemDomain(domain.domain_id);
      const nextDomains = buildDomains(payload);
      setConsolePayload(payload);
      setSelectedDomainId(nextDomains[0]?.domain_id || "");
      setSelectedTaskId(nextDomains[0]?.tasks[0]?.task_id || "");
      setSelectedCoordinationId("");
      setEditingDomainName(false);
      setNotice("任务域及其特定任务已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除任务域失败");
    } finally {
      setSaving("");
    }
  }

  async function deleteTaskRecord(task: SpecificTaskRecord) {
    const confirmed = window.confirm(`删除「${task.task_title}」会同时删除该任务的单任务装配配置。确认删除？`);
    if (!confirmed) return;
    setSaving("task-delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemSpecificRecord(task.task_id);
      const nextDomains = buildDomains(payload);
      const nextDomain = nextDomains.find((item) => item.domain_id === selectedDomainId) ?? nextDomains[0];
      setConsolePayload(payload);
      setSelectedDomainId(nextDomain?.domain_id || "");
      setSelectedTaskId(nextDomain?.tasks[0]?.task_id || "");
      setNotice("特定任务及其装配配置已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除特定任务失败");
    } finally {
      setSaving("");
    }
  }

  async function saveTaskStack() {
    const policyError = jsonError(taskPolicyText, "任务策略", "object");
    if (policyError) {
      setError(policyError);
      return;
    }
    setSaving("task-stack");
    setError("");
    setNotice("");
    try {
      const taskPayload = { ...taskDraft, task_policy: parseJsonObject(taskPolicyText, "任务策略") };
      await upsertTaskWorkflow(workflowDraft.workflow_id, {
        ...workflowDraft,
        compatible_projection_ids: splitList(workflowDraft.compatible_projection_ids_text),
        visible_skill_ids: splitList(workflowDraft.visible_skill_ids_text),
        steps: stepsFromText(workflowDraft.steps_text),
        stop_conditions: splitList(workflowDraft.stop_conditions_text),
        required_evidence_refs: splitList(workflowDraft.required_evidence_refs_text),
      });
      await upsertTaskSystemSpecificRecord(taskPayload.task_id, taskPayload);
      await upsertTaskSystemProjectionBinding(taskPayload.task_id, projectionDraft);
      await upsertTaskSystemFlowContractBinding(taskPayload.task_id, flowDraft);
      await upsertTaskSystemExecutionPolicy(taskPayload.task_id, {
        ...executionDraft,
      });
      const payload = await upsertTaskSystemMemoryRequestProfile(taskPayload.task_id, memoryDraft);
      setConsolePayload(payload);
      setSelectedTaskId(taskPayload.task_id);
      setNotice("任务定义与单任务装配已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务装配失败");
    } finally {
      setSaving("");
    }
  }

  async function saveCoordinationStack(nextPublished?: boolean) {
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftTask = taskLayer === "editor" ? editorTask : selectedTask;
    const draftFamily = draftTask?.task_family || draftDomain?.task_family || coordinationDraft.task_family || "";
    const draftDomainId = draftDomain?.domain_id || coordinationDraft.domain_id || "";
    if (taskLayer === "editor" && !draftTask) {
      setError("请先在图编辑器中打开一个任务。");
      return;
    }
    setSaving("coordination");
    setError("");
    setNotice("");
    try {
      const effectiveCoordinationDraft = nextPublished === undefined
        ? coordinationDraft
        : { ...coordinationDraft, enabled: nextPublished };
      const effectiveTopologyDraft = nextPublished === undefined
        ? topologyDraft
        : { ...topologyDraft, enabled: nextPublished };
      const effectiveProtocolDraft = nextPublished === undefined
        ? protocolDraft
        : { ...protocolDraft, enabled: nextPublished };
      const coordinationNodes = effectiveCoordinationDraft.graph_nodes ?? [];
      const coordinationEdges = effectiveCoordinationDraft.graph_edges ?? [];
      const subtaskRefs = coordinationSubtaskRefs(effectiveCoordinationDraft);
      const protocolPayload: TaskCommunicationProtocol = {
        ...effectiveProtocolDraft,
        message_types: a2aCatalog?.message_types?.length ? a2aCatalog.message_types : ["message/send", "message/stream", "task/status", "task/artifact"],
        payload_contracts: splitList(effectiveProtocolDraft.payload_contracts_text),
        signal_rules: splitList(effectiveProtocolDraft.signal_rules_text),
        handoff_rules: splitList(effectiveProtocolDraft.handoff_rules_text),
        metadata: {
          ...(effectiveProtocolDraft.metadata ?? {}),
          task_family: draftFamily,
          domain_id: draftDomainId,
          task_id: draftTask?.task_id || "",
          a2a_protocol: "official",
          a2a_protocol_version: a2aCatalog?.protocol_version || "0.3.0",
          a2a_transport: a2aCatalog?.transport || "JSONRPC",
          protocol_locked: true,
          business_communication_modes: effectiveCoordinationDraft.communication_modes ?? [],
        },
      };
      await upsertTaskSystemCommunicationProtocol(protocolPayload.protocol_id, protocolPayload);
      await upsertTaskSystemTopologyTemplate(effectiveTopologyDraft.template_id, {
        ...effectiveTopologyDraft,
        nodes: coordinationNodes,
        edges: coordinationEdges,
        handoff_rules: [],
        metadata: {
          ...(effectiveTopologyDraft.metadata ?? {}),
          task_family: draftFamily,
          domain_id: draftDomainId,
          task_id: draftTask?.task_id || "",
        },
      });
      const payload = await upsertTaskSystemCoordinationTask(effectiveCoordinationDraft.coordination_task_id, {
        ...effectiveCoordinationDraft,
        task_family: draftFamily,
        domain_id: draftDomainId,
        participant_agent_ids: (effectiveCoordinationDraft.graph_nodes ?? [])
          .filter((node) => String(node.role ?? "") !== "coordinator")
          .map((node) => String(node.agent_id ?? "").trim())
          .filter(Boolean),
        stop_conditions: splitList(effectiveCoordinationDraft.stop_conditions_text),
        subtask_refs: subtaskRefs,
        communication_modes: effectiveCoordinationDraft.communication_modes ?? [],
        graph_nodes: effectiveCoordinationDraft.graph_nodes ?? [],
        graph_edges: effectiveCoordinationDraft.graph_edges ?? [],
        metadata: {
          ...(effectiveCoordinationDraft.metadata ?? {}),
          protocol_id: protocolPayload.protocol_id,
          task_family: draftFamily,
          domain_id: draftDomainId,
          task_id: draftTask?.task_id || "",
        },
      });
      setCoordinationDraft(effectiveCoordinationDraft);
      setTopologyDraft(effectiveTopologyDraft);
      setProtocolDraft(effectiveProtocolDraft);
      setConsolePayload(payload);
      if (taskLayer === "editor") {
        setEditorCoordinationId(effectiveCoordinationDraft.coordination_task_id);
      } else {
        setSelectedCoordinationId(effectiveCoordinationDraft.coordination_task_id);
      }
      setNotice(nextPublished === true ? "协调任务、拓扑和协议已发布。" : "协调任务、拓扑和协议已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存协调任务失败");
    } finally {
      setSaving("");
    }
  }

  async function saveContractSpec(spec: ContractSpec) {
    setSaving("contract-spec");
    setError("");
    setNotice("");
    try {
      const payload = await upsertTaskSystemContract(spec.contract_id, spec);
      setConsolePayload(payload);
      setNotice(`契约“${contractSpecTitle(spec)}”已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存契约失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  async function removeContractSpec(contractId: string) {
    setSaving("contract-spec");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemContract(contractId);
      setConsolePayload(payload);
      setNotice(`契约“${contractId}”已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除契约失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  const taskPolicyError = jsonError(taskPolicyText, "任务策略", "object");
  const activeGraphNodes = topologyDraft.nodes ?? [];
  const activeGraphEdges = topologyDraft.edges ?? [];
  const taskGraphDraft = buildTaskGraphDraft({
    coordinationDraft,
    topologyDraft,
    protocolDraft,
  });
  const selectedGraphNode = activeGraphNodes.find((node) => String(node.node_id ?? "") === selectedGraphNodeId) ?? null;
  const selectedGraphEdge = activeGraphEdges.find((edge, index) => graphEdgeId(edge, index) === selectedGraphEdgeId) ?? null;
  const boundCoordinationTaskIds = new Set(activeGraphNodes.map((node) => graphNodeTaskId(node)).filter(Boolean));
  const graphContextDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
  const graphContextDomainTasks = taskLayer === "editor" ? editorDomainTasks : selectedDomainTasks;
  const graphContextTask = taskLayer === "editor" ? editorTask : selectedTask;
  const graphContextFamily = graphContextTask?.task_family || graphContextDomain?.task_family || coordinationDraft.task_family || "";
  const graphContextDomainId = graphContextDomain?.domain_id || coordinationDraft.domain_id || "";
  const draftGraphSpec = deriveTaskGraphSpec(
    coordinationDraft.coordination_task_id || activeCoordination?.coordination_task_id || "",
    graphContextDomainId,
    graphContextFamily,
    activeGraphNodes,
    activeGraphEdges,
  );
  const editorGraphSpec: CoordinationGraphSpec = {
    ...(activeCoordinationGraphSpec ?? draftGraphSpec),
    ...draftGraphSpec,
    issues: [
      ...draftGraphSpec.issues,
      ...((activeCoordinationGraphSpec?.issues ?? []).filter((issue) => {
        const code = String(issue.code ?? "");
        return code && !draftGraphSpec.issues.some((draftIssue) => String(draftIssue.code ?? "") === code);
      })),
    ],
  };
  editorGraphSpec.valid = editorGraphSpec.issues.length === 0 && draftGraphSpec.valid;
  const editorIssueCount = editorGraphSpec.issues.length;
  const editorValid = editorGraphSpec.valid;
  const editorPublished = Boolean(coordinationDraft.enabled && topologyDraft.enabled && protocolDraft.enabled);
  const topologyDirty = JSON.stringify(topologyDraft.nodes ?? []) !== JSON.stringify(coordinationDraft.graph_nodes ?? [])
    || JSON.stringify(topologyDraft.edges ?? []) !== JSON.stringify(coordinationDraft.graph_edges ?? []);
  const taskReadiness = [
    { label: "任务定义", value: taskDraft.task_title || taskDraft.task_id, ready: Boolean(taskDraft.task_id && taskDraft.task_title) },
    { label: "执行流程", value: workflowDraft.title || "已选择", ready: Boolean(workflowDraft.workflow_id) },
    { label: "投影", value: projectionDraft.default_projection_id ? projectionLabel(projectionDraft.default_projection_id, projectionCards) : "未使用投影", ready: true },
    { label: "执行方式", value: "单任务运行", ready: true },
    { label: "记忆", value: memoryDraft.memory_priority, ready: Boolean(memoryDraft.memory_priority) },
  ];
  const eligibilityRows = [
    { label: "允许 Agent", value: executionDraft.allowed_agent_categories?.map((item) => displayId(item)).join(" / ") || "未配置" },
    { label: "任务范围", value: `${domainTitle(taskDraft.task_family || selectedTaskDomain?.task_family || "")} / ${displayId(taskDraft.task_mode)}` },
    { label: "权限口径", value: `${displayId(executionDraft.task_level)} / ${displayId(executionDraft.task_privilege)}` },
    { label: "输出契约", value: contractLabel(taskDraft.output_contract_id || workflowDraft.output_contract_id || "", contractSpecs, contractCatalog) },
  ];
  const taskLayerItems: Array<LayerNavItem<TaskLayer>> = [
    {
      value: "management",
      label: "任务管理",
      meta: selectedDomain?.title || "未选择任务域",
      detail: "管理任务域、任务定义、契约、任务包和运行策略",
    },
    {
      value: "editor",
      label: "图编辑器",
      meta: editorTask ? (coordinationDraft.title || editorSelectedCoordination?.title || editorTask.task_title) : "未打开任务",
      detail: "打开任务并编辑它的 Agent 能力拓扑",
    },
  ];
  const taskConfigPanelItems: Array<LayerNavItem<TaskConfigPanel>> = [
    {
      value: "definition",
      label: "基础定义",
      meta: selectedTask ? (taskDraft.task_title || selectedTask.task_title) : "未选择任务",
      detail: "任务身份、输入输出、Workflow、投影与执行策略",
    },
    {
      value: "contracts",
      label: "契约",
      meta: `${contractViews.length} 项`,
      detail: "当前任务的契约库、契约绑定与 Manifest",
    },
    {
      value: "package",
      label: "任务包",
      meta: "模板安装",
      detail: "生成和保存当前任务相关的任务层资产",
    },
    {
      value: "preflight",
      label: "预检",
      meta: editorValid ? "图校验通过" : `${editorIssueCount} 个问题`,
      detail: "当前任务图的 ContractManifest、RuntimeAssembly 与 A2A 预检",
    },
    {
      value: "runloop",
      label: "RunLoop",
      meta: memoryDraft.allow_long_term_memory ? "长期记忆已启用" : "运行配置",
      detail: "当前任务的循环、记忆、上下文连续性与写回策略",
    },
  ];
  const contractPanelItems: Array<LayerNavItem<ContractPanel>> = [
    {
      value: "library",
      label: "契约库",
      meta: `${contractSpecs.length} 个契约`,
      detail: "管理契约主数据、字段、通信与治理策略",
    },
    {
      value: "templates",
      label: "契约模板",
      meta: "模板草案",
      detail: "从模板生成草案，编辑后再保存",
    },
    {
      value: "bindings",
      label: "任务绑定",
      meta: selectedTask?.task_title || "未选择任务",
      detail: "维护当前任务、Workflow 与图节点的契约引用",
    },
    {
      value: "manifest",
      label: "Manifest",
      meta: activeCoordination?.title || "协调任务",
      detail: "查看当前任务图的契约覆盖与校验摘要",
    },
  ];
  const packagePanelItems: Array<LayerNavItem<PackagePanel>> = [
    {
      value: "templates",
      label: "模板库",
      meta: "1 个可用模板",
      detail: "选择任务包模板并生成前端草案",
    },
    {
      value: "draft",
      label: "草案审查",
      meta: domainDraft.domain_id === longformNovelPackage.domain.domain_id ? (domainDraft.title || "长篇小说草案") : "尚未生成",
      detail: "审查将要创建的任务层对象",
    },
    {
      value: "pipeline",
      label: "保存管线",
      meta: packageSteps.length ? `${packageSteps.filter((step) => step.status === "success").length}/${packageSteps.length}` : "未开始",
      detail: "逐项调用正式 API 并显示失败位置",
    },
    {
      value: "prerequisites",
      label: "前置条件",
      meta: `${longformNovelPackage.requiredAgents.length} 个 Agent`,
      detail: "Agent / AgentGroup / RuntimeProfile 必须到编排系统配置",
    },
  ];
  function selectTaskForEditor(taskId: string) {
    const nextTask = tasks.find((item) => item.task_id === taskId) ?? null;
    const nextDomain = visibleDomains.find((domain) => domain.tasks.some((task) => task.task_id === taskId)) ?? null;
    const nextFamily = nextTask?.task_family || nextDomain?.task_family || "";
    const nextCoordination = allCoordinationTasks.find((item) => coordinationFamily(item, tasks) === nextFamily);
    setEditorTaskId(nextTask?.task_id || "");
    setEditorCoordinationId(nextCoordination?.coordination_task_id || "");
    setSelectedGraphNodeId("");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }

  return (
    <div className={`workspace-view boundary-console task-system-boundary task-system-boundary--${taskLayer}`}>
      <header className="boundary-hero">
        <div>
          <span>任务边界工作台</span>
          <h2>任务系统工作台</h2>
          <p>任务管理负责两层资产；图编辑器负责当前任务的 Agent 拓扑。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton onClick={() => void load()}><RefreshCw size={15} />刷新</ToolbarButton>
          {taskLayer === "management" ? (
            <>
              <ToolbarButton onClick={createDomainDraft}><Plus size={15} />新任务域</ToolbarButton>
              <ToolbarButton disabled={saving === "task-create" || !selectedDomain} onClick={() => void createTaskDraft()}><Plus size={15} />新任务</ToolbarButton>
            </>
          ) : null}
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}
      {notice ? <div className="boundary-notice"><CheckCircle2 size={16} />{notice}</div> : null}

      <section className="task-system-switchboard task-system-switchboard--compact">
        <LayerNav ariaLabel="任务系统层级" items={taskLayerItems} value={taskLayer} onChange={setTaskLayer} />
      </section>

      {taskLayer === "management" ? (
      <section className="boundary-workbench">
        <aside className="boundary-rail">
          <div className="boundary-rail__head">
            <strong>任务域</strong>
            <div className="boundary-inline-actions">
              <span>{visibleDomains.length}</span>
              {taskLayer === "management" ? (
                <button className="boundary-icon-button" onClick={createDomainDraft} type="button" aria-label="新增任务域">
                  <Plus size={14} />
                </button>
              ) : null}
            </div>
          </div>
          {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
          {visibleDomains.map((domain) => {
            const active = domain.domain_id === selectedDomainId;
            return (
              <article className={active ? "boundary-domain boundary-domain--active" : "boundary-domain"} key={domain.domain_id}>
                <button
                  className="boundary-domain__select"
                  onClick={() => {
                    setSelectedDomainId(domain.domain_id);
                    setSelectedTaskId(domain.tasks[0]?.task_id || "");
                    const domainFamily = domain.task_family;
                    const nextCoordination = (consolePayload?.coordination_management.coordination_tasks ?? []).find((item) => coordinationFamily(item, tasks) === domainFamily);
                    setSelectedCoordinationId(nextCoordination?.coordination_task_id || "");
                    setEditingDomainName(false);
                  }}
                  type="button"
                >
                  <strong>{domain.title}</strong>
                  <small>{domain.tasks.length} 个任务</small>
                </button>
                {active && taskLayer === "management" ? (
                  <div className="boundary-domain__tools">
                    <button className="boundary-domain__save" onClick={() => setEditingDomainName(true)} type="button" aria-label="修改任务域名称">
                      <Pencil size={14} />
                    </button>
                    <button className="boundary-domain__save boundary-domain__save--danger" disabled={saving === "domain-delete"} onClick={() => void deleteDomain(domain)} type="button" aria-label="删除任务域">
                      <Trash2 size={14} />
                    </button>
                  </div>
                ) : null}
              </article>
            );
          })}
        </aside>

        <main className="boundary-main">
          {taskLayer === "management" ? (
            <section className="boundary-layer-grid task-domain-workbench">
              <div className="boundary-directory task-domain-directory">
                <div className="boundary-panel-head">
                  {editingDomainName ? (
                    <input
                      className="boundary-title-input"
                      autoFocus
                      value={domainDraft.title}
                      onChange={(event) => updateDomainTitle(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") void saveDomain();
                        if (event.key === "Escape") setEditingDomainName(false);
                      }}
                    />
                  ) : (
                    <strong>{selectedDomain?.title || "任务域"}</strong>
                  )}
                  <div className="boundary-inline-actions">
                    <span>{selectedDomain?.tasks.length || 0}</span>
                    {editingDomainName ? (
                      <button className="boundary-icon-button" disabled={saving === "domain"} onClick={() => void saveDomain()} type="button" aria-label="保存任务域名称">
                        <Save size={14} />
                      </button>
                    ) : (
                      <button className="boundary-icon-button" onClick={() => setEditingDomainName(true)} type="button" aria-label="修改任务域名称">
                        <Pencil size={14} />
                      </button>
                    )}
                  </div>
                </div>
                <section className="boundary-card task-domain-compact-editor">
                  <header>
                    <strong>任务域设置</strong>
                    <div className="boundary-actions">
                      <ToolbarButton disabled={saving === "domain"} onClick={() => void saveDomain()}><Save size={15} />保存域</ToolbarButton>
                      <ToolbarButton disabled={saving === "entry"} onClick={() => void saveEntry()}><Save size={15} />保存入口</ToolbarButton>
                    </div>
                  </header>
                  <div className="boundary-form">
                    <Field label="任务族群"><input value={domainDraft.task_family} onChange={(event) => setDomainDraft((value) => ({ ...value, task_family: event.target.value }))} /></Field>
                    <label className="boundary-check"><input checked={domainDraft.enabled} onChange={(event) => setDomainDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用任务域</label>
                    <Field label="任务域描述" wide><textarea value={domainDraft.description} onChange={(event) => setDomainDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                  </div>
                </section>
                <div className="task-domain-list-head">
                  <strong>域内任务</strong>
                  <ToolbarButton disabled={saving === "task-create" || !selectedDomain} onClick={() => void createTaskDraft()}><Plus size={15} />新任务</ToolbarButton>
                </div>
                <div className="boundary-list">
                  {selectedDomain?.tasks.map((task) => (
                    <button className={task.task_id === selectedTaskId ? "boundary-list-row boundary-list-row--active task-domain-task-row" : "boundary-list-row task-domain-task-row"} key={task.task_id} onClick={() => setSelectedTaskId(task.task_id)} type="button">
                      <strong>{task.task_title}</strong>
                      <span>{task.enabled ? "启用" : "停用"} / {displayId(task.task_mode)}</span>
                    </button>
                  ))}
                  {!selectedDomain?.tasks.length ? (
                    <div className="boundary-empty">
                      当前任务域暂无任务。请使用上方“新任务”创建特定任务。
                    </div>
                  ) : null}
                </div>
              </div>
              <div className="boundary-editor task-domain-editor">
                <section className="task-system-context-bar">
                  <div className="task-system-context-bar__copy">
                    <span>{selectedDomain?.title || "当前任务域"}</span>
                    <strong>{selectedTask ? (taskDraft.task_title || selectedTask.task_title) : "未选择任务"}</strong>
                    <p>配置只作用于当前任务。</p>
                  </div>
                </section>
                {selectedTask ? (
                  <section className="boundary-layer-stack">
                    <section className="task-system-section-switch">
                      <div className="task-system-section-switch__head">
                        <span>任务配置</span>
                        <strong>{taskConfigPanelItems.find((item) => item.value === taskConfigPanel)?.meta || taskDraft.task_title}</strong>
                      </div>
                      <LayerNav ariaLabel="任务配置页面" items={taskConfigPanelItems} value={taskConfigPanel} onChange={setTaskConfigPanel} variant="secondary" />
                    </section>
                    {taskConfigPanel === "definition" ? (
                      <>
                        <section className="boundary-card">
                          <header>
                            <strong>{taskDraft.task_title || "特定任务定义"}</strong>
                            <div className="boundary-actions">
                              <ToolbarButton onClick={() => sendTaskToChat(selectedTask, selectedTaskDomain)}>带入主会话</ToolbarButton>
                              <ToolbarButton onClick={() => {
                                if (selectedTask) selectTaskForEditor(selectedTask.task_id);
                                setTaskLayer("editor");
                              }}>进入任务图</ToolbarButton>
                              <ToolbarButton disabled={saving === "task-delete"} onClick={() => void deleteTaskRecord(selectedTask)}>
                                <Trash2 size={15} />删除任务
                              </ToolbarButton>
                              <ToolbarButton disabled={saving === "task-stack"} onClick={() => void saveTaskStack()} variant="primary"><Save size={15} />保存任务</ToolbarButton>
                            </div>
                          </header>
                          <div className="boundary-form task-definition-form">
                            <Field label="任务标题"><input value={taskDraft.task_title} onChange={(event) => setTaskDraft((value) => ({ ...value, task_title: event.target.value }))} /></Field>
                            <Field label="所属任务域"><input readOnly value={selectedDomain?.title || domainTitle(taskDraft.task_family)} /></Field>
                            <SelectField label="任务模式" onChange={(value) => setTaskDraft((current) => ({ ...current, task_mode: value }))} options={taskModeOptions} value={taskDraft.task_mode} />
                            <Field label="验收档案"><input value={taskDraft.acceptance_profile_id} onChange={(event) => setTaskDraft((value) => ({ ...value, acceptance_profile_id: event.target.value }))} /></Field>
                            <Field label="任务描述" wide><textarea value={taskDraft.description} onChange={(event) => setTaskDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                            <label className="boundary-check"><input checked={taskDraft.enabled} onChange={(event) => setTaskDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用任务</label>
                            <SystemFields>
                              <Field label="任务 ID"><input value={taskDraft.task_id} onChange={(event) => setTaskDraft((value) => ({ ...value, task_id: event.target.value }))} /></Field>
                              <ContractSelectField contracts={contractSpecs} legacyContracts={contractCatalog} label="输入契约" onChange={(value) => setTaskDraft((current) => ({ ...current, input_contract_id: value }))} options={commonContractOptions} value={taskDraft.input_contract_id} />
                              <ContractSelectField contracts={contractSpecs} legacyContracts={contractCatalog} label="输出契约" onChange={(value) => setTaskDraft((current) => ({ ...current, output_contract_id: value }))} options={commonContractOptions} value={taskDraft.output_contract_id} />
                              <SelectField label="默认执行流程" onChange={(value) => setTaskDraft((current) => ({ ...current, default_workflow_id: value }))} options={workflowOptions} value={taskDraft.default_workflow_id} />
                              <FlowContractSelect label="默认流程契约" flows={taskFlowDefinitions} onChange={(value) => setTaskDraft((current) => ({ ...current, default_flow_contract_id: value }))} value={taskDraft.default_flow_contract_id} />
                              <SelectField label="投影策略" onChange={(value) => setTaskDraft((current) => ({ ...current, default_projection_policy: value }))} options={DEFAULT_PROJECTION_POLICY_CHOICES} value={taskDraft.default_projection_policy} />
                              <Field label="任务策略" wide>
                                <>
                                  <textarea value={taskPolicyText} onChange={(event) => setTaskPolicyText(event.target.value)} />
                                  <small className={taskPolicyError ? "boundary-json-state boundary-json-state--error" : "boundary-json-state"}>{taskPolicyError || "JSON 可解析"}</small>
                                </>
                              </Field>
                            </SystemFields>
                          </div>
                        </section>
                        <section className="boundary-card">
                          <header><strong>承接要求</strong></header>
                          <div className="boundary-kv task-eligibility-grid">
                            {eligibilityRows.map((row) => <p key={row.label}><span>{row.label}</span><strong>{row.value}</strong></p>)}
                          </div>
                        </section>
                      </>
                    ) : null}
                  </section>
                ) : (
                  <section className="boundary-card">
                    <header>
                      <strong>当前任务域暂无任务</strong>
                      <ToolbarButton disabled={saving === "task-create" || !selectedDomain} onClick={() => void createTaskDraft()} variant="primary"><Plus size={15} />新任务</ToolbarButton>
                    </header>
                    <div className="boundary-empty">任务定义是任务域下的第二层对象。先创建任务，再进入图编辑器配置单 Agent 或多 Agent 拓扑。</div>
                  </section>
                )}
              </div>
            </section>
          ) : null}

          {taskLayer === "management" && selectedTask && taskConfigPanel === "contracts" ? (
            <section className="boundary-layer-stack task-system-contract-center">
              <section className="task-system-context-bar">
                <div className="task-system-context-bar__copy">
                  <span>当前任务配置</span>
                  <strong>{contractPanelItems.find((item) => item.value === contractPanel)?.label || "契约库"}</strong>
                  <p>{contractPanelItems.find((item) => item.value === contractPanel)?.detail || "维护当前任务的契约边界。"}</p>
                </div>
              </section>
              <LayerNav ariaLabel="当前任务契约页面" items={contractPanelItems} value={contractPanel} onChange={setContractPanel} variant="secondary" />

              {contractPanel === "library" && contractManagement ? (
                <ContractLibraryPanel
                  contractManagement={contractManagement}
                  onDelete={removeContractSpec}
                  onSave={saveContractSpec}
                  saving={saving === "contract-spec"}
                />
              ) : null}

              {contractPanel === "templates" ? (
                <section className="contract-template-grid">
                  <article className="boundary-card contract-template-card">
                    <header>
                      <div className="boundary-identity-stack">
                        <span>任务包契约组</span>
                        <strong>长篇小说契约组</strong>
                        <small>{longformNovelPackage.contracts.length} 个契约草案</small>
                      </div>
                      <ToolbarButton onClick={() => { previewLongformNovelPackage(); setContractPanel("library"); }}>
                        <Plus size={15} />载入草案
                      </ToolbarButton>
                    </header>
                    <p>生成项目简报、章节草稿、连续性审查、记忆晋升、最终交付等契约草案。草案只进入当前工作台，需要用户审查后通过正式 API 保存。</p>
                    <div className="boundary-list boundary-list--scroll">
                      {longformNovelPackage.contracts.map((contract) => (
                        <article className="boundary-list-row" key={contract.contract_id}>
                          <strong>{contractSpecTitle(contract)}</strong>
                          <span>{CONTRACT_KIND_LABELS[contract.contract_kind] || contract.contract_kind}</span>
                        </article>
                      ))}
                    </div>
                  </article>
                  <article className="boundary-card contract-template-card">
                    <header>
                      <div className="boundary-identity-stack">
                        <span>通用模板</span>
                        <strong>节点执行契约</strong>
                        <small>适用于普通 Agent 节点</small>
                      </div>
                    </header>
                    <p>用于普通 Agent 节点的输入输出边界。后续可以扩展为字段级模板；当前建议从契约库新建后按分区填写。</p>
                    <div className="boundary-readiness-list boundary-readiness-list--grid">
                      <ReadinessCard label="字段" value="输入 / 输出" ready />
                      <ReadinessCard label="运行" value="可见性 / Runtime" ready />
                      <ReadinessCard label="治理" value="失败 / 门控" ready />
                    </div>
                  </article>
                </section>
              ) : null}

              {contractPanel === "bindings" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  {selectedTask ? (
                  <TaskContractPanel
                    contractSpecs={contractSpecs}
                    onWorkflowOutputContractChange={(contractId) => setWorkflowDraft((current) => ({ ...current, output_contract_id: contractId }))}
                    setTaskDraft={setTaskDraft}
                    taskDraft={taskDraft}
                    workflowOutputContractId={workflowDraft.output_contract_id}
                  />
                ) : null}
                  <section className="boundary-card">
                    <header><strong>当前任务图契约引用</strong><span className="boundary-badge">{activeGraphNodes.length} 节点 / {activeGraphEdges.length} 边</span></header>
                    <div className="boundary-list boundary-list--scroll">
                      {activeGraphNodes.map((node, index) => (
                        <article className="boundary-list-row" key={String(node.node_id ?? `node_${index}`)}>
                          <strong>{String(node.title ?? node.label ?? node.node_id ?? "节点")}</strong>
                          <span>{contractLabel(String(node.node_contract_id ?? node.output_contract_id ?? ""), contractSpecs, contractCatalog)}</span>
                        </article>
                      ))}
                      {activeGraphEdges.map((edge, index) => (
                        <article className="boundary-list-row" key={String(edge.edge_id ?? `edge_${index}`)}>
                          <strong>{String(edge.label ?? edge.title ?? "交接边")}</strong>
                          <span>{contractLabel(String(edge.payload_contract_id ?? edge.contract_id ?? ""), contractSpecs, contractCatalog)}</span>
                        </article>
                      ))}
                    </div>
                  </section>
                </section>
              ) : null}

              {contractPanel === "manifest" ? (
                <ContractOverviewPanel
                  contractSpecs={contractSpecs}
                  selectedCoordination={selectedCoordination}
                  selectedNodeId={selectedGraphNodeId}
                  selectedTask={selectedTask}
                />
              ) : null}
            </section>
          ) : null}

          {taskLayer === "management" && selectedTask && taskConfigPanel === "package" ? (
            <section className="boundary-layer-stack task-package-center">
              <section className="task-system-context-bar">
                <div className="task-system-context-bar__copy">
                  <span>当前任务配置</span>
                  <strong>{packagePanelItems.find((item) => item.value === packagePanel)?.label || "模板库"}</strong>
                  <p>{packagePanelItems.find((item) => item.value === packagePanel)?.detail || "为当前任务选择模板、审查草案、保存任务层资产。"}</p>
                </div>
              </section>
              <LayerNav ariaLabel="当前任务包页面" items={packagePanelItems} value={packagePanel} onChange={setPackagePanel} variant="secondary" />

              {packagePanel === "templates" ? (
                <section className="package-template-grid">
                  <article className="boundary-card package-template-card package-template-card--featured">
                    <header>
                      <div className="boundary-identity-stack">
                        <span>可配置任务包模板</span>
                        <strong>长篇小说创作</strong>
                        <small>多 Agent 写作工作流</small>
                      </div>
                      <span className="boundary-badge boundary-badge--ok">可用</span>
                    </header>
                    <p>生成长篇小说任务域、特定任务、投影绑定、契约组、拓扑模板、通信协议、协调任务和任务图草案。Agent 团队仍由编排系统前端创建。</p>
                    <div className="boundary-readiness-list boundary-readiness-list--grid">
                      <ReadinessCard label="契约" value={`${longformNovelPackage.contracts.length} 个`} ready />
                      <ReadinessCard label="节点" value={`${longformNovelPackage.topology.nodes.length} 个`} ready />
                      <ReadinessCard label="边" value={`${longformNovelPackage.topology.edges.length} 条`} ready />
                      <ReadinessCard label="前置资源" value={`${longformPrerequisiteReadyCount}/${longformPrerequisiteTotal}`} ready={longformPrerequisiteReadyCount === longformPrerequisiteTotal} />
                    </div>
                    <div className="boundary-actions">
                      <ToolbarButton onClick={previewLongformNovelPackage} variant="primary"><Plus size={15} />生成草案</ToolbarButton>
                      <ToolbarButton onClick={() => setPackagePanel("prerequisites")}>查看前置条件</ToolbarButton>
                    </div>
                  </article>
                  <article className="boundary-card package-template-card">
                    <header><strong>后续模板位</strong><span className="boundary-badge">规划中</span></header>
                    <p>健康管理、研究报告、代码重构等任务包可以继续接入同一套模板库、草案审查和保存管线。</p>
                    <div className="boundary-readiness-list boundary-readiness-list--grid">
                      <ReadinessCard label="模板入口" value="通用" ready />
                      <ReadinessCard label="保存管线" value="复用" ready />
                    </div>
                  </article>
                </section>
              ) : null}

              {packagePanel === "draft" ? (
                <section className="package-draft-editor">
                  <div className="boundary-card package-draft-editor__main">
                    <header>
                      <div className="boundary-identity-stack">
                        <span>可编辑任务包草案</span>
                        <strong>{taskDraft.task_title || longformNovelPackage.task.task_title}</strong>
                        <small>任务层资产草案</small>
                      </div>
                      <div className="boundary-actions">
                        <ToolbarButton onClick={previewLongformNovelPackage}><RotateCcw size={15} />重置模板</ToolbarButton>
                        <ToolbarButton onClick={() => { setTaskLayer("editor"); }}>进入任务图</ToolbarButton>
                        <ToolbarButton disabled={saving === "package"} onClick={() => void saveLongformNovelPackage()} variant="primary"><Save size={15} />保存任务层资产</ToolbarButton>
                      </div>
                    </header>
                    <div className="package-draft-editor__sections">
                      <section className="contract-editor-section">
                        <header><strong>任务域与任务</strong><span>保存前可直接改标题、族群、模式和描述</span></header>
                        <div className="boundary-form">
                          <Field label="任务域标题"><input value={domainDraft.title} onChange={(event) => setDomainDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                          <Field label="任务族群"><input value={domainDraft.task_family} onChange={(event) => {
                            const nextFamily = event.target.value;
                            setDomainDraft((value) => ({ ...value, task_family: nextFamily }));
                            setTaskDraft((value) => ({ ...value, task_family: nextFamily }));
                          }} /></Field>
                          <Field label="任务标题"><input value={taskDraft.task_title} onChange={(event) => setTaskDraft((value) => ({ ...value, task_title: event.target.value }))} /></Field>
                          <Field label="任务模式"><input value={taskDraft.task_mode} onChange={(event) => setTaskDraft((value) => ({ ...value, task_mode: event.target.value }))} /></Field>
                          <Field label="任务描述" wide><textarea value={taskDraft.description} onChange={(event) => setTaskDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                        </div>
                      </section>

                      <section className="contract-editor-section">
                        <header><strong>运行与记忆</strong><span>长任务循环、记忆层和任务长期记忆策略</span></header>
                        <div className="boundary-form">
                          <Field label="默认 Agent"><input value={executionDraft.default_agent_id} onChange={(event) => setExecutionDraft((value) => ({ ...value, default_agent_id: event.target.value }))} /></Field>
                          <Field label="执行链类型"><input value={executionDraft.execution_chain_type} onChange={(event) => setExecutionDraft((value) => ({ ...value, execution_chain_type: event.target.value }))} /></Field>
                          <Field label="工作记忆策略 ID"><input value={memoryDraft.working_memory_policy_profile_id || ""} onChange={(event) => setMemoryDraft((value) => ({ ...value, working_memory_policy_profile_id: event.target.value }))} /></Field>
                          <Field label="写回策略"><input value={memoryDraft.writeback_policy} onChange={(event) => setMemoryDraft((value) => ({ ...value, writeback_policy: event.target.value }))} /></Field>
                          <label className="boundary-check"><input checked={memoryDraft.allow_working_memory === true} onChange={(event) => setMemoryDraft((value) => ({ ...value, allow_working_memory: event.target.checked }))} type="checkbox" />启用工作记忆</label>
                          <label className="boundary-check"><input checked={memoryDraft.allow_dynamic_working_memory_read === true} onChange={(event) => setMemoryDraft((value) => ({ ...value, allow_dynamic_working_memory_read: event.target.checked }))} type="checkbox" />允许动态读取</label>
                          <label className="boundary-check"><input checked={memoryDraft.allow_long_term_memory === true} onChange={(event) => setMemoryDraft((value) => ({ ...value, allow_long_term_memory: event.target.checked }))} type="checkbox" />启用任务长期记忆</label>
                          <Field label="任务策略 JSON" wide>
                            <>
                              <textarea value={taskPolicyText} onChange={(event) => setTaskPolicyText(event.target.value)} />
                              <small className={taskPolicyError ? "boundary-json-state boundary-json-state--error" : "boundary-json-state"}>{taskPolicyError || "JSON 可解析"}</small>
                            </>
                          </Field>
                        </div>
                      </section>

                      <section className="contract-editor-section">
                        <header><strong>图与通信</strong><span>协调任务、拓扑模板、A2A 协议</span></header>
                        <div className="boundary-form">
                          <Field label="协调任务标题"><input value={coordinationDraft.title} onChange={(event) => setCoordinationDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                          <Field label="协调模式"><input value={coordinationDraft.coordination_mode} onChange={(event) => setCoordinationDraft((value) => ({ ...value, coordination_mode: event.target.value }))} /></Field>
                          <Field label="拓扑标题"><input value={topologyDraft.title} onChange={(event) => setTopologyDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                          <Field label="协议标题"><input value={protocolDraft.title} onChange={(event) => setProtocolDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                          <Field label="停止条件" wide><textarea value={coordinationDraft.stop_conditions_text} onChange={(event) => setCoordinationDraft((value) => ({ ...value, stop_conditions_text: event.target.value, stop_conditions: splitList(event.target.value) }))} /></Field>
                        </div>
                      </section>
                    </div>
                  </div>

                  <aside className="boundary-layer-stack package-draft-editor__side">
                    <section className="boundary-card">
                      <header><strong>对象摘要</strong><span className="boundary-badge">将保存</span></header>
                      <div className="boundary-kv">
                        <p><span>任务域</span><strong>{domainDraft.title || longformNovelPackage.domain.title}</strong></p>
                        <p><span>特定任务</span><strong>{taskDraft.task_title || longformNovelPackage.task.task_title}</strong></p>
                        <p><span>Workflow</span><strong>{workflowDraft.title || longformNovelPackage.workflow.title}</strong></p>
                        <p><span>协调任务</span><strong>{coordinationDraft.title || longformNovelPackage.coordination.title}</strong></p>
                        <p><span>任务图</span><strong>完整生产任务图</strong></p>
                        <p><span>拓扑模板</span><strong>{topologyDraft.title || longformNovelPackage.topology.title}</strong></p>
                        <p><span>通信协议</span><strong>{protocolDraft.title || longformNovelPackage.protocol.title}</strong></p>
                        <p><span>契约数量</span><strong>{longformNovelPackage.contracts.length}</strong></p>
                      </div>
                    </section>
                    <section className="boundary-card">
                      <header><strong>草案质量门</strong><span className="boundary-badge">前端草案</span></header>
                    <div className="boundary-readiness-list boundary-readiness-list--grid">
                      <ReadinessCard label="正式 API" value="保存时调用" ready />
                      <ReadinessCard label="投影绑定" value="随任务包保存" ready />
                      <ReadinessCard label="Agent 注册" value="前置校验" ready={longformAgentStatuses.every((item) => item.status === "ready")} />
                      <ReadinessCard label="调度策略" value="已内置草案" ready />
                      <ReadinessCard label="记忆策略" value="Working + Task Durable" ready />
                    </div>
                    <div className="boundary-notice">
                      <AlertTriangle size={16} />
                      <span>草案进入工作台后仍可在任务域、契约、任务图、RunLoop 页面继续编辑。</span>
                    </div>
                    </section>
                  </aside>
                </section>
              ) : null}

              {packagePanel === "pipeline" ? (
                <section className="boundary-card">
                  <header>
                    <strong>保存管线</strong>
                    <div className="boundary-actions">
                      <span className="boundary-badge">{packageSteps.length ? `${packageSteps.filter((step) => step.status === "success").length}/${packageSteps.length}` : "未开始"}</span>
                      <ToolbarButton disabled={saving === "package"} onClick={() => void saveLongformNovelPackage()} variant="primary"><Save size={15} />运行保存</ToolbarButton>
                    </div>
                  </header>
                  <div className="package-pipeline-list">
                    {(packageSteps.length ? packageSteps : [
                      { id: "ready", label: "等待保存", status: "pending", detail: "点击运行保存后逐项调用正式 API。" } as PackageSaveStep,
                    ]).map((step) => (
                      <article className={`package-pipeline-step package-pipeline-step--${step.status}`} key={step.id}>
                        <span>{step.status === "success" ? <CheckCircle2 size={15} /> : step.status === "error" ? <AlertTriangle size={15} /> : <Loader2 size={15} />}</span>
                        <strong>{step.label}</strong>
                        <small>{step.status === "error" ? step.detail : step.status === "success" ? "已保存" : "等待执行"}</small>
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}

              {packagePanel === "prerequisites" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header>
                      <strong>编排系统前置清单</strong>
                      <div className="boundary-actions">
                        <span className={packagePrerequisiteClass(longformPrerequisiteReadyCount === longformPrerequisiteTotal ? "ready" : longformPrerequisiteReadyCount > 0 ? "partial" : "missing")}>
                          {longformPrerequisiteReadyCount}/{longformPrerequisiteTotal}
                        </span>
                        <ToolbarButton onClick={() => void load()}><RefreshCw size={15} />刷新状态</ToolbarButton>
                        <ToolbarButton onClick={() => setWorkspaceView("orchestration")}>去编排系统</ToolbarButton>
                      </div>
                    </header>
                    <div className="boundary-notice">
                      <AlertTriangle size={16} />
                      <span>先在投影系统创建以下专属投影卡，并写入各 Agent 的 prompt；再到编排系统创建 Agent 并绑定对应投影。</span>
                    </div>
                    <div className="boundary-list boundary-list--scroll">
                      {longformProjectionStatuses.map((projection) => (
                        <article className="boundary-list-row" key={projection.projection_id}>
                          <strong>{projection.projection_id}</strong>
                          <span>{projection.title} · {projection.detail}</span>
                          <small className={packagePrerequisiteClass(projection.status)}>{packagePrerequisiteBadge(projection.status)}</small>
                        </article>
                      ))}
                      {longformAgentStatuses.map((agent) => (
                        <article className="boundary-list-row" key={agent.agent_id}>
                          <strong>{agent.title}</strong>
                          <span>{agent.agent_id} · {agent.detail}</span>
                          <small className={packagePrerequisiteClass(agent.status)}>{packagePrerequisiteBadge(agent.status)}</small>
                        </article>
                      ))}
                      <article className="boundary-list-row">
                        <strong>group.longform_novel_core_team</strong>
                        <span>{longformGroupStatus.detail}</span>
                        <small className={packagePrerequisiteClass(longformGroupStatus.status)}>{packagePrerequisiteBadge(longformGroupStatus.status)}</small>
                      </article>
                    </div>
                  </div>
                  <aside className="boundary-card">
                    <header><strong>不可在任务包页创建</strong><span className="boundary-badge boundary-badge--warn">边界保护</span></header>
                    <div className="boundary-kv">
                      <p><span>Agent</span><strong>OrchestrationView 创建</strong></p>
                      <p><span>AgentGroup</span><strong>OrchestrationView 创建</strong></p>
                      <p><span>专属投影</span><strong>投影系统创建并写入角色 prompt</strong></p>
                      <p><span>RuntimeProfile</span><strong>编排系统配置权限和 output_contracts</strong></p>
                      <p><span>任务资产</span><strong>本页面只保存任务层对象</strong></p>
                    </div>
                  </aside>
                </section>
              ) : null}
            </section>
          ) : null}

          {taskLayer === "management" && selectedTask && taskConfigPanel === "preflight" ? (
            <TaskAssemblyPreflightPanel
              a2aCatalog={a2aCatalog}
              editorIssueCount={editorIssueCount}
              editorPublished={editorPublished}
              editorValid={editorValid}
              onBackToGraph={() => setTaskLayer("editor")}
              saveCoordinationStack={saveCoordinationStack}
              saveTopologyDraftIntoCoordination={saveTopologyDraftIntoCoordination}
              saving={saving}
              selectedCoordination={selectedCoordination}
              selectedGraphSpec={editorGraphSpec}
              selectedNodeId={selectedGraphNodeId}
              selectedTask={selectedTask}
              setSelectedNodeId={setSelectedGraphNodeId}
              topologyDirty={topologyDirty}
            />
          ) : null}

          {taskLayer === "management" && selectedTask && taskConfigPanel === "runloop" ? (
            <TaskRunLoopWorkbenchPanel
              coordinationMemorySharingPolicy={coordinationDraft.memory_sharing_policy}
              coordinationSharedContextPolicy={coordinationDraft.shared_context_policy}
              executionDraft={executionDraft}
              memoryDraft={memoryDraft}
              nodeAssembly={null}
              saveCoordinationStack={saveCoordinationStack}
              saveTaskStack={saveTaskStack}
              saving={saving}
              selectedCoordination={selectedCoordination}
              selectedTask={selectedTask}
              setCoordinationMemorySharingPolicy={(value) => setCoordinationDraft((current) => ({ ...current, memory_sharing_policy: value }))}
              setCoordinationSharedContextPolicy={(value) => setCoordinationDraft((current) => ({ ...current, shared_context_policy: value }))}
              setExecutionDraft={setExecutionDraft}
              setMemoryDraft={setMemoryDraft}
              workflowAssembly={null}
            />
          ) : null}
        </main>
      </section>
      ) : null}

      {taskLayer === "editor" ? (
        <section className="task-system-editor-shell">
          <section className="task-graph-loader">
            <div className="task-graph-loader__copy">
              <span>当前编辑任务</span>
              <strong>{editorTask ? editorTask.task_title : "未打开任务"}</strong>
            </div>
            <div className="task-graph-loader__controls">
              <label>
                <span>打开任务</span>
                <select value={editorTaskId} onChange={(event) => selectTaskForEditor(event.target.value)}>
                  <option disabled={tasks.length > 0} value="">{tasks.length ? "选择要编辑的任务" : "暂无任务"}</option>
                  {visibleDomains.map((domain) => (
                    <optgroup key={domain.domain_id} label={domain.title}>
                      {domain.tasks.map((task) => (
                        <option key={task.task_id} value={task.task_id}>{task.task_title}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </label>
              <label>
                <span>图草稿</span>
                <select disabled={!editorTask} value={editorCoordinationId} onChange={(event) => {
                  setEditorCoordinationId(event.target.value);
                  setSelectedGraphNodeId("");
                  setSelectedGraphEdgeId("");
                  setLinkingFromNodeId("");
                }}>
                  {!editorTask ? <option value="">先打开任务</option> : null}
                  {editorTask && !editorCoordinationTasks.length ? <option value="">暂无草稿</option> : null}
                  {editorCoordinationTasks.map((task) => (
                    <option key={task.coordination_task_id} value={task.coordination_task_id}>{task.title}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="task-graph-loader__actions">
              <ToolbarButton disabled={saving === "coordination-create"} onClick={() => void createCoordinationDraft()}><Network size={15} />新图草稿</ToolbarButton>
            </div>
          </section>

          <TaskGraphWorkbench
            addTaskGraphEdge={addCoordinationEdge}
            addTaskGraphNode={addCoordinationNode}
            addTaskGraphRoleNode={addCoordinationRoleNode}
            addTaskGraphSuccessorNode={addCoordinationSuccessorNode}
            addTaskGraphTaskNode={addCoordinationTaskNode}
            a2aCatalog={a2aCatalog}
            agentGroupOptions={editorAgentGroupOptions}
            applyTaskGraphTemplate={applyCoordinationGraphTemplate}
            boundCoordinationTaskIds={boundCoordinationTaskIds}
            connectSelectedNodeTo={connectSelectedNodeTo}
            contractSpecs={contractSpecs}
            coordinationTasks={editorCoordinationTasks}
            cycleTaskGraphEdgeMode={cycleCoordinationEdgeMode}
            cycleTaskGraphNodeRole={cycleCoordinationNodeRole}
            domainTaskOptions={editorDomainTaskOptions}
            duplicateTaskGraphDraft={duplicateCoordinationDraft}
            editorIssueCount={editorIssueCount}
            editorPublished={editorPublished}
            editorValid={editorValid}
            activeGraphEdges={activeGraphEdges}
            activeGraphNodes={activeGraphNodes}
            handleTopologyNodeClick={handleTopologyNodeClick}
            legacyDrafts={{ coordinationDraft, topologyDraft, protocolDraft }}
            linkingFromNodeId={linkingFromNodeId}
            removeTaskGraphEdge={removeCoordinationEdge}
            removeTaskGraphNode={removeCoordinationNode}
            reverseTaskGraphEdge={reverseCoordinationEdge}
            saveTaskGraphDraft={saveTopologyDraftIntoCoordination}
            saveTaskGraphStack={saveCoordinationStack}
            saving={saving}
            selectedCoordination={editorSelectedCoordination}
            selectedCoordinationId={editorCoordinationId}
            selectedDomain={editorDomain}
            selectedDomainTasks={editorDomainTasks}
            selectedGraphEdge={selectedGraphEdge}
            selectedGraphEdgeId={selectedGraphEdgeId}
            selectedGraphNode={selectedGraphNode}
            selectedGraphNodeId={selectedGraphNodeId}
            selectedTaskGraphSpec={editorGraphSpec}
            sendTaskGraphToChat={sendCoordinationToChat}
            setCoordinationDraft={setCoordinationDraft}
            setLinkingFromNodeId={setLinkingFromNodeId}
            setProtocolDraft={setProtocolDraft}
            setSelectedCoordinationId={setEditorCoordinationId}
            setSelectedGraphEdgeId={setSelectedGraphEdgeId}
            setSelectedGraphNodeId={setSelectedGraphNodeId}
            setTaskGraphPublished={setCoordinationPublished}
            setTopologyDraft={setTopologyDraft}
            taskGraphDirty={topologyDirty}
            taskGraphDraft={taskGraphDraft}
            updateTaskGraphEdge={updateCoordinationEdge}
            updateTaskGraphNode={updateCoordinationNode}
          />
        </section>
      ) : null}
    </div>
  );
}








