"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Network,
  Plus,
  RefreshCw,
  Save,
  Send,
  Pencil,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
import { buildTaskGraphDraft, taskGraphRecordToDraft } from "@/components/workspace/views/task-system/taskGraphDraft";
import { legacyStackToTaskGraphDraftV2, taskGraphRecordToDraftV2 } from "@/components/workspace/views/task-system/taskGraphDraftV2";
import { buildTaskGraphUpsertPayload } from "@/components/workspace/views/task-system/taskGraphSaveMapper";
import { buildTaskGraphTemplateDraft, type TaskGraphTemplateId } from "@/components/workspace/views/task-system/taskGraphTemplates";
import {
  TaskSystemDomainTaskSelectField as DomainTaskSelectField,
  TaskSystemField as Field,
  TaskSystemMultiSelectField as MultiSelectField,
  TaskSystemSelectField as SelectField,
  TaskSystemToolbarButton as ToolbarButton,
  taskSystemDisplayLabel,
  taskSystemOptionLabel,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import {
  deleteTaskSystemDomain,
  deleteTaskSystemSpecificRecord,
  createSoulProjectionCard,
  getOrchestrationAgents,
  getSoulProjectionCards,
  getTaskSystemNextIds,
  getTaskSystemOverview,
  deleteTaskSystemContract,
  upsertTaskSystemCommunicationProtocol,
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
  type OrchestrationAgentRuntimeCatalog,
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
type TaskConfigPanel = "definition" | "contracts" | "preflight" | "runloop";
type ContractPanel = "library" | "templates" | "bindings" | "manifest";

type WorkflowDraft = TaskWorkflowRecord & {
  compatible_projection_ids_text: string;
  visible_skill_ids_text: string;
  steps_text: string;
  stop_conditions_text: string;
  required_evidence_refs_text: string;
};

type GraphRuntimeDraft = {
  graph_id: string;
  coordination_task_id: string;
  title: string;
  graph_kind: "single_agent" | "multi_agent" | "coordination";
  domain_id: string;
  task_family: string;
  coordinator_agent_id: string;
  agent_group_id: string;
  coordination_mode: string;
  topology_template_id: string;
  protocol_id: string;
  shared_context_policy: string;
  memory_sharing_policy: string;
  handoff_policy: string;
  conflict_resolution_policy: string;
  output_merge_policy: string;
  stop_conditions: string[];
  subtask_refs: string[];
  graph_nodes: Array<Record<string, unknown>>;
  graph_edges: Array<Record<string, unknown>>;
  communication_modes: string[];
  enabled: boolean;
  participant_agent_ids: string[];
  metadata?: Record<string, unknown>;
  stop_conditions_text: string;
};

type CoordinationDraft = GraphRuntimeDraft & {
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
  task_family: string;
  task_modes: string[];
  title: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  metadata?: Record<string, unknown>;
  tasks: SpecificTaskRecord[];
  entry_policy: ConversationEntryPolicy | null;
};

type ArtifactPolicyDraft = {
  enabled: boolean;
  artifact_root: string;
  subdir_template: string;
  materializer: string;
  required_files_text: string;
  optional_files_text: string;
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

function domainIdToLegacyFamily(domainId: string, fallback = "general") {
  const raw = String(domainId || "").trim();
  if (!raw) return fallback;
  const normalized = raw.replace(/^domain\./, "").trim();
  return normalized || fallback;
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

function defaultArtifactPolicyDraft(): ArtifactPolicyDraft {
  return {
    enabled: false,
    artifact_root: "",
    subdir_template: "{task_slug}/{run_slug}",
    materializer: "markdown_section_split",
    required_files_text: "",
    optional_files_text: "",
  };
}

function artifactPolicyDraftFrom(policy: Record<string, unknown>): ArtifactPolicyDraft {
  const artifactPolicy = dictOf(policy.artifact_policy);
  const artifacts = Array.isArray(artifactPolicy.artifacts) ? artifactPolicy.artifacts.filter((item) => item && typeof item === "object") as Array<Record<string, unknown>> : [];
  return {
    enabled: artifactPolicy.enabled === true,
    artifact_root: String(artifactPolicy.artifact_root || artifactPolicy.default_artifact_root || ""),
    subdir_template: String(artifactPolicy.subdir_template || ""),
    materializer: String(artifactPolicy.materializer || "markdown_section_split"),
    required_files_text: artifacts.filter((item) => item.required !== false).map((item) => String(item.path || "")).filter(Boolean).join("\n"),
    optional_files_text: artifacts.filter((item) => item.required === false).map((item) => String(item.path || "")).filter(Boolean).join("\n"),
  };
}

function artifactSpecsFromDraft(draft: ArtifactPolicyDraft) {
  const sectionHints: Record<string, string[]> = {
    "01_project_bible.md": ["项目总纲", "Project Brief"],
    "02_world_bible.md": ["世界规则", "World Rules"],
    "03_character_bible.md": ["主角设定", "人物设定", "角色设定", "Protagonist"],
    "04_volume_plan.md": ["分卷规划", "Volume Plan"],
    "chapters/chapter_001_plan.md": ["第一章规划", "Chapter 1 Plan"],
    "chapters/chapter_001_draft.md": ["第一章正文", "正文初稿", "Chapter 1 Draft"],
  };
  const required = splitList(draft.required_files_text).map((path) => ({
    path,
    required: true,
    section_keys: sectionHints[path] ?? [],
    fallback_to_full_content: path === "01_project_bible.md",
  }));
  const optional = splitList(draft.optional_files_text).map((path) => ({
    path,
    required: false,
    section_keys: sectionHints[path] ?? [],
  }));
  return [...required, ...optional];
}

function mergeArtifactPolicy(taskPolicyText: string, draft: ArtifactPolicyDraft) {
  const policy = parseJsonObject(taskPolicyText, "任务策略");
  const artifactPolicy = {
    ...dictOf(policy.artifact_policy),
    enabled: draft.enabled,
    artifact_root: draft.artifact_root.trim(),
    subdir_template: draft.subdir_template.trim(),
    materializer: draft.materializer.trim() || "markdown_section_split",
    artifacts: artifactSpecsFromDraft(draft),
  };
  return {
    ...policy,
    artifact_policy: artifactPolicy,
  };
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

function emptyCoordination(templateId = "", protocolId = "", taskFamily = "", domainId = "", graphId = "graph.dev.task"): CoordinationDraft {
  return {
    graph_id: graphId,
    coordination_task_id: graphId,
    title: "新任务图",
    graph_kind: "multi_agent",
    coordination_mode: "review_merge",
    coordinator_agent_id: "agent:0",
    task_family: taskFamily,
    domain_id: domainId,
    agent_group_id: "",
    participant_agent_ids: [],
    topology_template_id: templateId,
    protocol_id: protocolId,
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

function coordinationDraftFrom(task?: GraphRuntimeDraft | null): CoordinationDraft {
  const base = task ?? emptyCoordination();
  return {
    ...base,
    stop_conditions: base.stop_conditions ?? [],
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
  const registeredLabel = taskSystemDisplayLabel(raw, fallback);
  if (registeredLabel !== raw) return registeredLabel;
  const labels: Record<string, string> = {
    "single_agent_chain": "单 Agent 链",
    "coordination_chain": "任务图协作",
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
    ["coord.writing.", "写作任务图"],
    ["coord.dev.", "开发任务图"],
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

function contractLabel(value: string, specs: ContractSpec[] = [], legacyContracts: TaskContractDescriptor[] = []) {
  const spec = specs.find((item) => item.contract_id === value);
  if (spec) return `${contractSpecTitle(spec)} · ${value}`;
  const contract = legacyContracts.find((item) => item.contract_id === value);
  return contract?.title || displayId(value);
}

function contractBelongsToDomain(spec: ContractSpec, domain: DomainRecord | null) {
  if (!domain) return true;
  const metadata = dictOf(spec.metadata);
  const domainId = String(metadata.domain_id ?? "").trim();
  const taskFamily = String(metadata.task_family ?? "").trim();
  if (domainId || taskFamily) {
    return domainId === domain.domain_id || taskFamily === domainIdToLegacyFamily(domain.domain_id);
  }
  const familyToken = domainIdToLegacyFamily(domain.domain_id).replace(/[^a-zA-Z0-9_]+/g, "_");
  return Boolean(familyToken && spec.contract_id.includes(familyToken));
}

function scopedContractSpecs(contractSpecs: ContractSpec[], domain: DomainRecord | null) {
  return contractSpecs.filter((spec) => contractBelongsToDomain(spec, domain));
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
    const metadata = dictOf(task.metadata);
    const domainId = String(metadata.domain_id ?? "").trim() || `domain.${task.task_family || "general"}`;
    grouped.set(domainId, [...(grouped.get(domainId) ?? []), task]);
  }
  const baseDomains: Array<TaskDomainRecord & { metadata?: Record<string, unknown> }> = formalDomains.length
    ? formalDomains.map((domain) => ({
        ...domain,
        metadata: {
          ...(domain.metadata ?? {}),
          task_family_legacy: String((domain as { task_family?: string }).task_family ?? "").trim(),
        },
      }))
    : Array.from(grouped.keys()).map((domainId, index) => ({
        ...emptyTaskDomain(index),
        domain_id: domainId,
        title: domainTitle(String(domainId).replace(/^domain\./, "")),
        metadata: {
          ...(emptyTaskDomain(index).metadata ?? {}),
          task_family_legacy: domainIdToLegacyFamily(domainId),
        },
      }));
  if (!baseDomains.length) baseDomains.push({ ...emptyTaskDomain(), domain_id: "domain.general", title: "通用任务域" });
  return baseDomains
    .map((domain, index) => {
      const domainId = domain.domain_id || "domain.general";
      const family = String(domainId).replace(/^domain\./, "") || "general";
      const items = grouped.get(domainId) ?? [];
      return {
        domain_id: domainId,
        task_family: family,
        task_modes: uniqueStrings(items.map((task) => task.task_mode)),
        title: domain.title || domainTitle(family),
        description: domain.description || "",
        enabled: domain.enabled ?? true,
        sort_order: domain.sort_order ?? index * 10,
        metadata: domain.metadata ?? {},
        tasks: items,
        entry_policy: entryPolicies.find((item) => String(item.metadata?.domain_id ?? "").trim() === domainId) ?? entryPolicies[index] ?? entryPolicies[0] ?? null,
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

function taskDomainId(task: SpecificTaskRecord) {
  const metadata = dictOf(task.metadata);
  return String(metadata.domain_id ?? "").trim() || `domain.${task.task_family || "general"}`;
}

function coordinationDomainId(task: GraphRuntimeDraft, tasks: SpecificTaskRecord[]) {
  const metadata = dictOf(task.metadata);
  const explicit = String(task.domain_id ?? "").trim() || String(metadata.domain_id ?? "").trim();
  if (explicit) return explicit;
  const taskId = String(metadata.task_id ?? "").trim();
  const boundTask = tasks.find((item) => item.task_id === taskId);
  if (boundTask) return taskDomainId(boundTask);
  const fromSubtask = (task.subtask_refs ?? [])
    .map((taskRef: string) => tasks.find((item) => item.task_id === String(taskRef).trim()))
    .find(Boolean);
  if (fromSubtask) return taskDomainId(fromSubtask);
  const family = coordinationFamily(task, tasks);
  return `domain.${family || "general"}`;
}

function coordinationFamily(task: GraphRuntimeDraft, tasks: SpecificTaskRecord[]) {
  const metadata = task.metadata ?? {};
  if (task.task_family) return task.task_family;
  if (task.domain_id?.startsWith("domain.")) return task.domain_id.replace("domain.", "");
  return (
    String(metadata.task_family ?? "").trim()
    || familyFromTaskRef(metadata.task_id, tasks)
    || (task.subtask_refs ?? []).map((taskId: string) => familyFromTaskRef(taskId, tasks)).find(Boolean)
    || familyFromRef(task.coordination_task_id)
    || familyFromRef(task.topology_template_id)
  );
}

function topologyFamily(template: TopologyTemplate) {
  const metadata = template.metadata ?? {};
  return String(metadata.task_family ?? "").trim() || familyFromRef(template.template_id);
}

function topologyDomainId(template: TopologyTemplate) {
  const metadata = dictOf(template.metadata);
  return String(metadata.domain_id ?? "").trim() || `domain.${topologyFamily(template) || "general"}`;
}

function protocolFamily(protocol: TaskCommunicationProtocol, tasks: SpecificTaskRecord[]) {
  const metadata = protocol.metadata ?? {};
  return (
    String(metadata.task_family ?? "").trim()
    || familyFromTaskRef(metadata.task_id, tasks)
    || familyFromRef(protocol.protocol_id)
  );
}

function protocolDomainId(protocol: TaskCommunicationProtocol, tasks: SpecificTaskRecord[]) {
  const metadata = dictOf(protocol.metadata);
  const explicit = String(metadata.domain_id ?? "").trim();
  if (explicit) return explicit;
  const taskId = String(metadata.task_id ?? "").trim();
  const boundTask = tasks.find((item) => item.task_id === taskId);
  if (boundTask) return taskDomainId(boundTask);
  return `domain.${protocolFamily(protocol, tasks) || "general"}`;
}

function protocolForCoordination(
  protocols: TaskCommunicationProtocol[],
  task: GraphRuntimeDraft | null,
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
  const { activeWorkspaceView, setTaskSelection, setWorkspaceView } = useAppStore();
  const [consolePayload, setConsolePayload] = useState<TaskSystemOverview | null>(null);
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [orchestrationAgentCatalog, setOrchestrationAgentCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [projectionLoading, setProjectionLoading] = useState(false);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedTaskGraphId, setSelectedTaskGraphId] = useState("");
  const [editorDomainId, setEditorDomainId] = useState("");
  const [editorTaskId, setEditorTaskId] = useState("");
  const [editorTaskGraphId, setEditorTaskGraphId] = useState("");
  const [taskLayer, setTaskLayer] = useState<TaskLayer>("management");
  const [editingDomainName, setEditingDomainName] = useState(false);
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState("");
  const [selectedGraphEdgeId, setSelectedGraphEdgeId] = useState("");
  const [linkingFromNodeId, setLinkingFromNodeId] = useState("");
  const [taskConfigPanel, setTaskConfigPanel] = useState<TaskConfigPanel>("definition");
  const [contractPanel, setContractPanel] = useState<ContractPanel>("library");
  const loadInFlightRef = useRef<Promise<void> | null>(null);

  const [entryDraft, setEntryDraft] = useState<ConversationEntryPolicy>(emptyEntryPolicy());
  const [domainDraft, setDomainDraft] = useState<TaskDomainRecord>(emptyTaskDomain());
  const [taskDraft, setTaskDraft] = useState<SpecificTaskRecord>(emptySpecificTaskRecord());
  const [workflowDraft, setWorkflowDraft] = useState<WorkflowDraft>(emptyWorkflow());
  const [projectionDraft, setProjectionDraft] = useState<TaskProjectionBinding>(emptyProjectionBinding());
  const [flowDraft, setFlowDraft] = useState<TaskFlowContractBinding>(emptyFlowBinding());
  const [executionDraft, setExecutionDraft] = useState<TaskExecutionPolicy>(emptyExecutionPolicy());
  const [memoryDraft, setMemoryDraft] = useState<TaskMemoryRequestProfile>(emptyMemoryProfile());
  const [taskPolicyText, setTaskPolicyText] = useState("{}");
  const [artifactPolicyDraft, setArtifactPolicyDraft] = useState<ArtifactPolicyDraft>(defaultArtifactPolicyDraft());
  const [coordinationDraft, setCoordinationDraft] = useState<CoordinationDraft>(emptyCoordination());
  const [topologyDraft, setTopologyDraft] = useState<TopologyDraft>(emptyTopology());
  const [protocolDraft, setProtocolDraft] = useState<ProtocolDraft>(emptyProtocol());
  const selectedDomainIdRef = useRef("");
  const projectionCatalogLoadRef = useRef<Promise<void> | null>(null);
  const orchestrationAgentCatalogLoadRef = useRef<Promise<void> | null>(null);

  useEffect(() => {
    selectedDomainIdRef.current = selectedDomainId;
  }, [selectedDomainId]);

  const applyOverview = useCallback((overview: TaskSystemOverview) => {
    setConsolePayload(overview);
    const nextDomains = buildDomains(overview);
    const firstDomainWithTasks = nextDomains.find((item) => item.tasks.length > 0) ?? null;
    const fallbackDomain = firstDomainWithTasks ?? nextDomains[0] ?? null;
    const preferredDomain = nextDomains.find((item) => item.domain_id === selectedDomainIdRef.current) ?? null;
    const selectedDomain = preferredDomain && (preferredDomain.tasks.length > 0 || !firstDomainWithTasks)
      ? preferredDomain
      : fallbackDomain;
    const taskGraphs = overview.task_graph_management?.task_graphs ?? overview.coordination_management?.task_graphs ?? [];
    setSelectedDomainId(selectedDomain?.domain_id ?? "");
    setSelectedTaskId((current) => current || selectedDomain?.tasks[0]?.task_id || overview.task_management.specific_task_records[0]?.task_id || "");
    setEditorDomainId((current) => current || selectedDomain?.domain_id || "");
    setSelectedTaskGraphId((current) => current || taskGraphs[0]?.graph_id || "");
    setEditorTaskId((current) => current && overview.task_management.specific_task_records.some((task) => task.task_id === current) ? current : "");
    setEditorTaskGraphId((current) => current && taskGraphs.some((graph) => graph.graph_id === current) ? current : "");
  }, []);

  const loadProjectionCatalog = useCallback(async () => {
    if (projectionCatalogLoadRef.current) {
      return projectionCatalogLoadRef.current;
    }
    const run = (async () => {
      setProjectionLoading(true);
      try {
        setProjectionCatalog(await getSoulProjectionCards());
      } catch {
        setProjectionCatalog((current) => current ?? null);
      } finally {
        setProjectionLoading(false);
        projectionCatalogLoadRef.current = null;
      }
    })();
    projectionCatalogLoadRef.current = run;
    return run;
  }, []);

  const loadOrchestrationAgentCatalog = useCallback(async () => {
    if (orchestrationAgentCatalogLoadRef.current) {
      return orchestrationAgentCatalogLoadRef.current;
    }
    const run = (async () => {
      try {
        setOrchestrationAgentCatalog(await getOrchestrationAgents());
      } catch {
        setOrchestrationAgentCatalog((current) => current ?? null);
      } finally {
        orchestrationAgentCatalogLoadRef.current = null;
      }
    })();
    orchestrationAgentCatalogLoadRef.current = run;
    return run;
  }, []);

  const load = useCallback(async () => {
    if (loadInFlightRef.current) {
      return loadInFlightRef.current;
    }
    const run = (async () => {
      setLoading(true);
      setError("");
      try {
        const overview = await getTaskSystemOverview();
        applyOverview(overview);
        void loadProjectionCatalog();
        void loadOrchestrationAgentCatalog();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "任务系统加载失败");
      } finally {
        setLoading(false);
        loadInFlightRef.current = null;
      }
    })();
    loadInFlightRef.current = run;
    return run;
  }, [applyOverview, loadOrchestrationAgentCatalog, loadProjectionCatalog]);

  useEffect(() => {
    if (activeWorkspaceView !== "task-system") return;
    void load();
  }, [activeWorkspaceView, load]);

  const domains = useMemo(() => buildDomains(consolePayload), [consolePayload]);
  const visibleDomains = useMemo(() => {
    const draftTaskMissing = taskDraft.task_id
      && taskDomainId(taskDraft)
      && !domains.some((domain) => domain.tasks.some((task) => task.task_id === taskDraft.task_id));
    const nextDomains = domains.map((domain) => {
      if (!draftTaskMissing || domain.domain_id !== taskDomainId(taskDraft)) return domain;
      return {
        ...domain,
        tasks: [...domain.tasks, taskDraft],
      };
    });
    const hasSelectedDomain = nextDomains.some((item) => item.domain_id === selectedDomainId);
    if (!selectedDomainId || hasSelectedDomain || !domainDraft.domain_id) {
      return nextDomains;
    }
    return [
      ...nextDomains,
      {
        domain_id: domainDraft.domain_id,
        task_family: domainIdToLegacyFamily(domainDraft.domain_id),
        task_modes: draftTaskMissing && taskDomainId(taskDraft) === domainDraft.domain_id ? uniqueStrings([taskDraft.task_mode]) : [],
        title: domainDraft.title,
        description: domainDraft.description,
        enabled: domainDraft.enabled,
        sort_order: domainDraft.sort_order,
        metadata: domainDraft.metadata ?? {},
        tasks: draftTaskMissing && taskDomainId(taskDraft) === domainDraft.domain_id ? [taskDraft] : [],
        entry_policy: null,
      },
    ].sort((a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title));
  }, [domainDraft, domains, selectedDomainId, taskDraft]);
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
  const domainContractSpecs = useMemo(() => scopedContractSpecs(contractSpecs, selectedDomain), [contractSpecs, selectedDomain]);
  const projectionBinding = (consolePayload?.task_management.projection_bindings ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const flowBinding = (consolePayload?.task_management.flow_contract_bindings ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const executionPolicy = (consolePayload?.task_management.execution_policies ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const memoryProfile = (consolePayload?.task_management.memory_request_profiles ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const selectedWorkflow = workflows.find((item) => item.workflow_id === selectedTask?.default_workflow_id);
  const allTaskGraphs = useMemo(() => consolePayload?.task_graph_management?.task_graphs ?? consolePayload?.coordination_management?.task_graphs ?? [], [consolePayload]);
  const allCoordinationGraphSpecs = useMemo(
    () => consolePayload?.task_graph_management?.task_graph_specs ?? consolePayload?.coordination_management?.coordination_graph_specs ?? [],
    [consolePayload],
  );
  const allTopologyTemplates = useMemo(
    () => consolePayload?.task_graph_management?.topology_templates ?? consolePayload?.coordination_management?.topology_templates ?? [],
    [consolePayload],
  );
  const allCommunicationProtocols = useMemo(
    () => consolePayload?.task_graph_management?.communication_protocols ?? consolePayload?.coordination_management?.communication_protocols ?? [],
    [consolePayload],
  );
  const a2aCatalog = consolePayload?.task_graph_management?.a2a ?? consolePayload?.coordination_management?.a2a ?? null;
  const activeDomainId = selectedDomain?.domain_id || "";
  const taskGraphs = useMemo(
    () => activeDomainId ? allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === activeDomainId) : [],
    [activeDomainId, allTaskGraphs],
  );
  const topologyTemplates = useMemo(
    () => activeDomainId ? allTopologyTemplates.filter((item) => topologyDomainId(item) === activeDomainId) : [],
    [activeDomainId, allTopologyTemplates],
  );
  const communicationProtocols = useMemo(
    () => activeDomainId ? allCommunicationProtocols.filter((item) => protocolDomainId(item, tasks) === activeDomainId) : [],
    [activeDomainId, allCommunicationProtocols, tasks],
  );
  const selectedTaskGraph = taskGraphs.find((item) => item.graph_id === selectedTaskGraphId) ?? taskGraphs[0] ?? null;
  const editorDomain = visibleDomains.find((domain) => domain.domain_id === editorDomainId) ?? visibleDomains[0] ?? null;
  const editorDomainTaskList = useMemo(() => editorDomain?.tasks ?? [], [editorDomain]);
  const editorTask = editorDomainTaskList.find((item) => item.task_id === editorTaskId) ?? editorDomainTaskList[0] ?? null;
  const editorDomainFilterId = editorDomain?.domain_id || (editorTask ? taskDomainId(editorTask) : "");
  const editorDomainTasks = editorDomainTaskList;
  const editorContractSpecs = useMemo(() => scopedContractSpecs(contractSpecs, editorDomain), [contractSpecs, editorDomain]);
  const editorTaskGraphs = useMemo(
    () => editorDomainFilterId ? allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === editorDomainFilterId) : [],
    [allTaskGraphs, editorDomainFilterId],
  );
  const editorTopologyTemplates = useMemo(
    () => editorDomainFilterId ? allTopologyTemplates.filter((item) => topologyDomainId(item) === editorDomainFilterId) : [],
    [allTopologyTemplates, editorDomainFilterId],
  );
  const editorCommunicationProtocols = useMemo(
    () => editorDomainFilterId ? allCommunicationProtocols.filter((item) => protocolDomainId(item, tasks) === editorDomainFilterId) : [],
    [allCommunicationProtocols, editorDomainFilterId, tasks],
  );
  const editorSelectedTaskGraph = editorTaskGraphs.find((item) => item.graph_id === editorTaskGraphId) ?? null;
  const activeTaskGraph = taskLayer === "editor" ? editorSelectedTaskGraph : selectedTaskGraph;
  const activeCoordinationGraphSpec = allCoordinationGraphSpecs.find((item) => item.graph_id === activeTaskGraph?.graph_id) ?? null;
  const activeTopology = (taskLayer === "editor" ? editorTopologyTemplates : topologyTemplates).find((item) => item.template_id === String(activeTaskGraph?.metadata?.topology_template_id ?? ""));
  const activeProtocol = (taskLayer === "editor" ? editorCommunicationProtocols : communicationProtocols).find((item) => item.protocol_id === String(activeTaskGraph?.default_protocol_id ?? activeTaskGraph?.metadata?.protocol_id ?? ""));
  const workflowOptions = useMemo(() => uniqueStrings(workflows.map((item) => item.workflow_id)), [workflows]);
  const commonContractOptions = useMemo(
    () => uniqueStrings([...COMMON_CONTRACT_CHOICES, ...contractCatalog.map((item) => item.contract_id), ...domainContractSpecs.map((item) => item.contract_id)]),
    [contractCatalog, domainContractSpecs],
  );
  const editorAgentGroupOptions = useMemo(
    () => uniqueStrings(editorTaskGraphs.map((item) => String(item.runtime_policy?.agent_group_id ?? item.metadata?.agent_group_id ?? ""))),
    [editorTaskGraphs],
  );
  const editorDomainTaskOptions = useMemo(
    () => editorDomainTasks.map((task) => ({ value: task.task_id, label: task.task_title })),
    [editorDomainTasks],
  );
  const projectionCards = useMemo(() => projectionCatalog?.cards ?? [], [projectionCatalog]);
  const domainProjectionCards = useMemo(() => projectionCards.filter((card) => {
    if (!selectedDomain) return true;
    const haystack = `${String(card.projection_id ?? "")} ${String(card.soul_id ?? "")} ${String(card.soul_name ?? "")}`.toLowerCase();
    const domainToken = selectedDomain.domain_id.replace(/^domain\./, "").toLowerCase();
    return haystack.includes(domainToken) || haystack.includes(selectedDomain.title.toLowerCase());
  }), [projectionCards, selectedDomain]);
  const contractViews = useMemo<ContractView[]>(() => (
    domainContractSpecs.map((contract) => ({
      key: `${contract.contract_kind}:${contract.contract_id}`,
      title: contractSpecTitle(contract),
      kind: CONTRACT_KIND_LABELS[contract.contract_kind] || contract.contract_kind,
      usage: contract.description || "通用 ContractSpec",
      source: contract.metadata?.default_seed ? "内置通用契约" : "用户契约库",
      raw: contract.contract_id,
    }))
  ), [domainContractSpecs]);

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

  const sendTaskGraphToChat = useCallback((graph: TaskGraphRecord | null, domain: DomainRecord | null) => {
    if (!graph) return;
    const metadata = dictOf(graph.metadata);
    const subtaskId = String(metadata.task_id ?? "").trim();
    setTaskSelection({
      selected_task_id: subtaskId,
      coordination_task_id: graph.graph_id,
      domain_id: domain?.domain_id || graph.domain_id || "",
      label: graph.title,
      mode: "coordination",
    });
    setWorkspaceView("chat");
    setNotice(`已将任务图“${graph.title}”带入主会话。`);
  }, [setTaskSelection, setWorkspaceView]);

  const createProjectionFromNodePrompt = useCallback(async ({
    node,
    nodeId,
    prompt,
  }: {
    node: Record<string, unknown>;
    nodeId: string;
    prompt: string;
  }) => {
    const latestProjectionCatalog = projectionCatalog?.cards?.length ? projectionCatalog : await getSoulProjectionCards();
    if (latestProjectionCatalog !== projectionCatalog) {
      setProjectionCatalog(latestProjectionCatalog);
    }
    const cards = latestProjectionCatalog?.cards ?? [];
    const currentProjectionId = String(node.projection_id ?? node.projection_overlay_id ?? "").trim();
    const selectedProjectionId = String(latestProjectionCatalog?.selected_projection_id ?? "").trim();
    const baseCard = cards.find((card) => card.projection_id === currentProjectionId)
      ?? cards.find((card) => card.projection_id === selectedProjectionId)
      ?? cards[0];
    if (!baseCard?.soul_id) {
      throw new Error("投影系统暂无可用 Soul，无法创建节点投影");
    }
    const graphSlug = slugFromTitle(coordinationDraft.graph_id || editorTaskGraphId || selectedTaskGraphId || "task_graph");
    const nodeSlug = slugFromTitle(nodeId || String(node.node_id ?? node.title ?? "node"));
    const role = String(node.work_posture ?? node.role ?? "task_graph_node").trim() || "task_graph_node";
    const agentId = String(node.agent_id ?? "").trim();
    const agentProfile = orchestrationAgentCatalog?.profiles.find((profile) => String(profile.agent_id ?? "") === agentId);
    const agentProfileId = String(agentProfile?.agent_profile_id ?? baseCard.agent_profile_id ?? "task_graph_node_agent").trim();
    const nextProjectionId = `projection.taskgraph.${graphSlug}.${nodeSlug}`;
    const nextCatalog = await createSoulProjectionCard({
      projection_id: nextProjectionId,
      soul_id: baseCard.soul_id,
      projection_kind: "task_graph_node",
      owner_system: "task_system",
      source_task_graph_refs: [coordinationDraft.graph_id || editorTaskGraphId || selectedTaskGraphId || ""].filter(Boolean),
      projection_name: `${text(node.title ?? node.label ?? nodeId, nodeId)} / 节点职责`,
      role_type: role,
      task_mode: editorTask?.task_mode || selectedTask?.task_mode || "task_graph_node",
      agent_profile_id: agentProfileId,
      projection_prompt: prompt,
      usage_summary: "由 TaskGraph Studio 节点职责生成的静态投影，用于运行装配时绑定节点 Prompt。",
      memory_policy_summary: "记忆读写权限由 TaskGraph 节点策略与 Agent Runtime Profile 决定。",
      output_contract_summary: "输出边界由 TaskGraph 节点契约和边交接契约决定。",
      select_after_create: false,
    });
    setProjectionCatalog(nextCatalog);
    return nextProjectionId;
  }, [
    coordinationDraft.graph_id,
    editorTask?.task_mode,
    editorTaskGraphId,
    orchestrationAgentCatalog?.profiles,
    projectionCatalog,
    selectedTask?.task_mode,
    selectedTaskGraphId,
  ]);
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
  }, [selectedDomain, selectedTaskId, workflows]);

  useEffect(() => {
    if (!taskGraphs.some((item) => item.graph_id === selectedTaskGraphId)) {
      setSelectedTaskGraphId(taskGraphs[0]?.graph_id || "");
    }
  }, [taskGraphs, selectedTaskGraphId]);

  useEffect(() => {
    if (!editorTaskId) {
      if (editorTaskGraphId) setEditorTaskGraphId("");
      return;
    }
    if (!editorTaskGraphs.some((item) => item.graph_id === editorTaskGraphId)) {
      setEditorTaskGraphId(editorTaskGraphs[0]?.graph_id || "");
    }
  }, [editorTaskGraphId, editorTaskGraphs, editorTaskId]);

  useEffect(() => {
    if (!editorDomain) return;
    if (!editorTaskId || !editorDomain.tasks.some((task) => task.task_id === editorTaskId)) {
      setEditorTaskId(editorDomain.tasks[0]?.task_id || "");
    }
  }, [editorDomain, editorTaskId]);

  useEffect(() => {
    if (!selectedTask) return;
    setTaskDraft({ ...selectedTask, metadata: selectedTask.metadata ?? {}, task_policy: selectedTask.task_policy ?? {} });
    setTaskPolicyText(JSON.stringify(selectedTask.task_policy ?? {}, null, 2));
    setArtifactPolicyDraft(artifactPolicyDraftFrom(selectedTask.task_policy ?? {}));
    setWorkflowDraft(workflowDraftFrom(selectedWorkflow, selectedTask.task_mode));
    setProjectionDraft(projectionBinding ?? emptyProjectionBinding(selectedTask.task_id, ""));
    setFlowDraft(flowBinding ?? emptyFlowBinding(selectedTask.task_id, selectedTask.default_flow_contract_id));
    setExecutionDraft(executionPolicy ?? emptyExecutionPolicy(selectedTask.task_id));
    setMemoryDraft(memoryProfile ?? emptyMemoryProfile(selectedTask.task_id));
  }, [selectedTask, selectedWorkflow, projectionBinding, flowBinding, executionPolicy, memoryProfile]);

  useEffect(() => {
    if (!activeTaskGraph) {
      setCoordinationDraft(coordinationDraftFrom(null));
      setTopologyDraft(topologyDraftFrom(null));
      setProtocolDraft(protocolDraftFrom(null));
      return;
    }
    const graphDraft = taskGraphRecordToDraft(activeTaskGraph, topologyDraftFrom(activeTopology), protocolDraftFrom(activeProtocol));
    const graphDraftV2 = taskGraphRecordToDraftV2(activeTaskGraph);
    setCoordinationDraft((current) => coordinationDraftFrom({
      ...current,
      graph_id: graphDraft.graph_id,
      title: graphDraft.title,
      graph_kind: graphDraft.graph_kind,
      domain_id: graphDraft.domain_id,
      topology_template_id: graphDraft.topology_template_id,
      protocol_id: graphDraft.protocol_id,
      agent_group_id: graphDraft.agent_group_id,
      coordination_mode: graphDraft.coordination_mode,
      graph_nodes: graphDraft.nodes,
      graph_edges: graphDraft.edges,
      communication_modes: graphDraft.communication_modes,
      enabled: graphDraft.publish_state === "published",
      coordinator_agent_id: graphDraftV2.runtime_policy.coordinator_agent_id,
      participant_agent_ids: graphDraftV2.runtime_policy.participant_agent_ids,
      metadata: {
        ...graphDraft.metadata,
        runtime_policy: graphDraftV2.runtime_policy,
        working_memory_policy_profile_id: graphDraftV2.working_memory_policy_profile_id,
        working_memory_policy: graphDraftV2.working_memory_policy,
      },
      stop_conditions: [],
      task_family: domainIdToLegacyFamily(graphDraft.domain_id, ""),
      shared_context_policy: graphDraftV2.context_policy.shared_context_policy,
      memory_sharing_policy: graphDraftV2.context_policy.memory_sharing_policy,
      handoff_policy: String(activeTaskGraph.metadata?.handoff_policy ?? "filtered_handoff"),
      conflict_resolution_policy: String(activeTaskGraph.metadata?.conflict_resolution_policy ?? "coordinator_review"),
      output_merge_policy: String(activeTaskGraph.metadata?.output_merge_policy ?? "coordinator_final_merge"),
    }));
    const nextTopology = topologyDraftFrom(activeTopology);
    const nextNodes = activeTaskGraph.nodes?.length ? activeTaskGraph.nodes : (nextTopology.nodes ?? []);
    const nextEdges = activeTaskGraph.edges?.length ? activeTaskGraph.edges : (nextTopology.edges ?? []);
    setTopologyDraft({
      ...nextTopology,
      nodes: nextNodes,
      edges: nextEdges,
      nodes_text: JSON.stringify(nextNodes, null, 2),
      edges_text: JSON.stringify(nextEdges, null, 2),
    });
    setProtocolDraft(protocolDraftFrom(activeProtocol));
    setSelectedGraphNodeId(String((activeTaskGraph.nodes ?? [])[0]?.node_id ?? ""));
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }, [activeProtocol, activeTaskGraph, activeTopology]);

  async function createTaskDraft() {
    setSaving("task-create");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const nextTask = emptySpecificTaskRecord(ids.workflow_id, ids.flow_id);
      const selectedDomainId = selectedDomain?.domain_id || "domain.general";
      const legacyFamily = domainIdToLegacyFamily(selectedDomainId);
      nextTask.task_id = ids.task_id;
      nextTask.task_family = legacyFamily;
      nextTask.task_mode = nextTask.task_mode || `${legacyFamily}_task`;
      nextTask.task_title = `${ids.display_numbers.task} 特定任务`;
      nextTask.default_flow_contract_id = ids.flow_id;
      nextTask.default_workflow_id = ids.workflow_id;
      nextTask.metadata = {
        ...(nextTask.metadata ?? {}),
        domain_id: selectedDomainId,
      };
      setSelectedTaskId(nextTask.task_id);
      setTaskLayer("management");
      setTaskConfigPanel("definition");
      setTaskDraft(nextTask);
      setTaskPolicyText(JSON.stringify(nextTask.task_policy, null, 2));
      setArtifactPolicyDraft(artifactPolicyDraftFrom(nextTask.task_policy));
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
    const nodeId = role === "coordinator" ? `coordinator_${nextIndex}` : role === "memory" ? `memory_${nextIndex}` : `agent_${nextIndex}`;
    const titleByRole: Record<string, string> = {
      coordinator: "协调器",
      planner: "规划节点",
      executor: "执行节点",
      reviewer: "审查节点",
      verifier: "验证节点",
      summarizer: "整理节点",
      merge: "汇总节点",
      memory: "工作记忆节点",
      writer: "执行节点",
      acceptance: "验收节点",
      participant: "协作节点",
    };
    const node = {
      node_id: nodeId,
      node_type: role === "memory" ? "memory" : "agent_role",
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

  function applyCoordinationGraphTemplate(template: TaskGraphTemplateId, options: Partial<Parameters<typeof buildTaskGraphTemplateDraft>[0]> = {}) {
    const shouldReplace = !(topologyDraft.nodes?.length || topologyDraft.edges?.length)
      || window.confirm("应用图模板会替换当前未保存的拓扑草稿，确认继续吗？");
    if (!shouldReplace) return;
    const mode = coordinationDraft.communication_modes?.[0] || "structured_handoff";
    const selectedTaskForNode = graphContextTask ?? graphContextDomainTasks[0] ?? null;
    const templateDraft = buildTaskGraphTemplateDraft({
      template_id: template,
      task_family: graphContextFamily,
      selected_task_title: selectedTaskForNode?.task_title || "",
      communication_mode: mode,
      ...options,
    });
    const nodes = templateDraft.nodes;
    const edges = templateDraft.edges;
    setTopologyDraft((current) => ({
      ...current,
      nodes,
      edges,
      nodes_text: JSON.stringify(nodes, null, 2),
      edges_text: JSON.stringify(edges, null, 2),
    }));
    setCoordinationDraft((current) => ({
      ...current,
      coordination_mode: templateDraft.coordination_mode,
      participant_agent_ids: templateDraft.participant_agent_ids,
      metadata: {
        ...(current.metadata ?? {}),
        ...templateDraft.metadata,
        entry_node_id: templateDraft.entry_node_id,
        output_node_id: templateDraft.output_node_id,
        setup_template_id: template,
      },
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
    const nextNodesSnapshot = (topologyDraft.nodes?.length ? topologyDraft.nodes : coordinationDraft.graph_nodes ?? []).map((node) =>
      String(node.node_id ?? "") === nodeId ? { ...node, ...patch } : node,
    );
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
    setCoordinationDraft((current) => {
      return {
        ...current,
        graph_nodes: nextNodesSnapshot,
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
    const roles = ["participant", "writer", "reviewer", "acceptance", "memory"];
    const currentIndex = roles.indexOf(currentRole);
    const nextRole = roles[(currentIndex + 1) % roles.length] ?? "participant";
    updateCoordinationNode(nodeId, {
      role: nextRole,
      work_posture: nextRole,
      node_type: nextRole === "memory" ? "memory" : "agent_role",
      agent_id: "",
    });
  }

  function updateCoordinationEdge(edgeId: string, patch: Record<string, unknown>) {
    const nextEdgesSnapshot = (topologyDraft.edges?.length ? topologyDraft.edges : coordinationDraft.graph_edges ?? []).map((edge, index) =>
      graphEdgeId(edge, index) === edgeId ? { ...edge, ...patch } : edge,
    );
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
    setCoordinationDraft((current) => {
      return {
        ...current,
        graph_edges: nextEdgesSnapshot,
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
    setNotice("拓扑草稿已同步到任务图，接下来可继续保存草稿或发布。");
    setError("");
  }

  async function createCoordinationDraft() {
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftTask = taskLayer === "editor" ? editorTask : selectedTask;
    const draftDomainId = draftDomain?.domain_id || (draftTask ? taskDomainId(draftTask) : "");
    const draftFamily = draftTask?.task_family || domainIdToLegacyFamily(draftDomainId, "");
    if (taskLayer === "editor" && !draftTask) {
      setError("请先在图编辑器中打开一个任务。");
      return;
    }
    setSaving("coordination-create");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const graphId = ids.graph_id;
      const coordination = emptyCoordination(
        ids.topology_template_id,
        `protocol.${ids.graph_id.replace(/^graph\./, "")}`,
        draftFamily,
        draftDomainId,
        graphId,
      );
      coordination.coordination_task_id = graphId;
      coordination.graph_id = graphId;
      coordination.title = `${ids.display_numbers.graph} 任务图`;
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
      protocol.title = `${ids.display_numbers.graph} 协议`;
      protocol.metadata = {
        ...(protocol.metadata ?? {}),
        task_family: draftFamily,
        domain_id: draftDomainId,
        task_id: draftTask?.task_id || "",
      };
      if (taskLayer === "editor") {
        setEditorTaskGraphId(coordination.graph_id);
      } else {
        setSelectedTaskGraphId(coordination.graph_id);
      }
      setTaskLayer("editor");
      setCoordinationDraft(coordination);
      setTopologyDraft(topology);
      setProtocolDraft(protocol);
      setNotice(`已生成任务图草稿：${coordination.graph_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "生成任务图草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function duplicateCoordinationDraft() {
    const sourceCoordination = taskLayer === "editor" ? editorSelectedTaskGraph : selectedTaskGraph;
    if (!sourceCoordination) {
      setError("当前没有可复制的任务图");
      return;
    }
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftDomainId = draftDomain?.domain_id || coordinationDraft.domain_id || "";
    const draftFamily = domainIdToLegacyFamily(draftDomainId, coordinationDraft.task_family || "");
    setSaving("coordination-duplicate");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const nextGraphId = ids.graph_id;
      const nextTopologyId = ids.topology_template_id;
      const nextProtocolId = `protocol.${ids.graph_id.replace(/^graph\./, "")}`;
      const nextTitle = `${sourceCoordination.title || ids.display_numbers.graph} 副本`;
      const nextCoordination: CoordinationDraft = {
        ...coordinationDraft,
        coordination_task_id: nextGraphId,
        graph_id: nextGraphId,
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
        setEditorTaskGraphId(nextGraphId);
      } else {
        setSelectedTaskGraphId(nextGraphId);
      }
      setTaskLayer("editor");
      setCoordinationDraft(nextCoordination);
      setTopologyDraft(nextTopology);
      setProtocolDraft(nextProtocol);
      setSelectedGraphNodeId(String((nextCoordination.graph_nodes ?? [])[0]?.node_id ?? ""));
      setSelectedGraphEdgeId("");
      setLinkingFromNodeId("");
      setNotice(`已复制任务图草稿：${nextGraphId}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "复制任务图草稿失败");
    } finally {
      setSaving("");
    }
  }

  function setCoordinationPublished(enabled: boolean) {
    setCoordinationDraft((current) => ({
      ...current,
      enabled,
      metadata: {
        ...(current.metadata ?? {}),
        editor_publish_state: enabled ? "published" : "draft",
      },
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
      const normalizedFamily = domainIdToLegacyFamily(domainDraft.domain_id || `domain.${slugFromTitle(domainDraft.title)}`);
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
      setSelectedTaskGraphId("");
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
      const taskPayload = { ...taskDraft, task_policy: mergeArtifactPolicy(taskPolicyText, artifactPolicyDraft) };
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

  async function saveCoordinationStack(nextPublished?: boolean, nextEditorPublishState?: "draft" | "saved" | "preflight_passed" | "published" | "run_bound" | "archived") {
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftTask = taskLayer === "editor" ? editorTask : selectedTask;
    const draftDomainId = draftDomain?.domain_id || (draftTask ? taskDomainId(draftTask) : "") || coordinationDraft.domain_id || "";
    const draftFamily = draftTask?.task_family || domainIdToLegacyFamily(draftDomainId, coordinationDraft.task_family || "");
    if (taskLayer === "editor" && !draftTask) {
      setError("请先在图编辑器中打开一个任务。");
      return;
    }
    setSaving("coordination");
    setError("");
    setNotice("");
    try {
      const nextCoordinationMetadata = nextEditorPublishState
        ? {
          ...(coordinationDraft.metadata ?? {}),
          editor_publish_state: nextEditorPublishState,
        }
        : coordinationDraft.metadata;
      const effectiveCoordinationDraft = nextPublished === undefined
        ? { ...coordinationDraft, metadata: nextCoordinationMetadata }
        : { ...coordinationDraft, enabled: nextPublished, metadata: nextCoordinationMetadata };
      const effectiveTopologyDraft = nextPublished === undefined
        ? topologyDraft
        : { ...topologyDraft, enabled: nextPublished };
      const effectiveProtocolDraft = nextPublished === undefined
        ? protocolDraft
        : { ...protocolDraft, enabled: nextPublished };
      const coordinationNodes = effectiveCoordinationDraft.graph_nodes ?? [];
      const coordinationEdges = effectiveCoordinationDraft.graph_edges ?? [];
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
      const effectiveTaskGraphDraftV2 = legacyStackToTaskGraphDraftV2({
        coordinationDraft: effectiveCoordinationDraft,
        topologyDraft: effectiveTopologyDraft,
        protocolDraft: effectiveProtocolDraft,
      });
      const taskGraphPayload = buildTaskGraphUpsertPayload({
        taskGraphDraft: {
          ...effectiveTaskGraphDraftV2,
          publish_state: nextPublished === true
            ? "published"
            : nextPublished === false
              ? "draft"
              : effectiveTaskGraphDraftV2.publish_state,
        },
        legacyDrafts: {
          coordinationDraft: effectiveCoordinationDraft,
          topologyDraft: effectiveTopologyDraft,
          protocolDraft: effectiveProtocolDraft,
        },
        domain_id: draftDomainId,
        task_family: draftFamily,
        task_id: draftTask?.task_id || "",
        publish_state: nextPublished === true
          ? "published"
          : nextPublished === false
            ? "draft"
            : effectiveTaskGraphDraftV2.publish_state === "published" || effectiveTaskGraphDraftV2.publish_state === "run_bound"
              ? "published"
              : "draft",
      });
      const payload = await upsertTaskSystemTaskGraph(effectiveCoordinationDraft.graph_id, taskGraphPayload);
      setCoordinationDraft(effectiveCoordinationDraft);
      setTopologyDraft(effectiveTopologyDraft);
      setProtocolDraft(effectiveProtocolDraft);
      setConsolePayload(payload);
      if (taskLayer === "editor") {
        setEditorTaskGraphId(effectiveCoordinationDraft.graph_id);
      } else {
        setSelectedTaskGraphId(effectiveCoordinationDraft.graph_id);
      }
      setNotice(nextPublished === true ? "任务图、拓扑和协议已发布。" : "任务图、拓扑和协议已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务图失败");
    } finally {
      setSaving("");
    }
  }

  async function saveContractSpec(spec: ContractSpec) {
    setSaving("contract-spec");
    setError("");
    setNotice("");
    try {
      const activeDomain = selectedDomain;
      const payloadSpec = activeDomain
        ? {
          ...spec,
          metadata: {
            ...(spec.metadata ?? {}),
            domain_id: activeDomain.domain_id,
            task_family: domainIdToLegacyFamily(activeDomain.domain_id),
          },
        }
        : spec;
      const payload = await upsertTaskSystemContract(payloadSpec.contract_id, payloadSpec);
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
  const taskGraphDraftV2 = legacyStackToTaskGraphDraftV2({
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
  const graphContextFamily = graphContextTask?.task_family || domainIdToLegacyFamily(graphContextDomain?.domain_id || coordinationDraft.domain_id || "", coordinationDraft.task_family || "");
  const graphContextDomainId = graphContextDomain?.domain_id || coordinationDraft.domain_id || "";
  const draftGraphSpec = deriveTaskGraphSpec(
    coordinationDraft.graph_id || taskGraphDraft.graph_id || "",
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
    { label: "任务范围", value: selectedTaskDomain?.title || domainTitle(domainIdToLegacyFamily(taskDomainId(taskDraft))) },
    { label: "权限口径", value: `${displayId(executionDraft.task_level)} / ${displayId(executionDraft.task_privilege)}` },
    { label: "输出契约", value: contractLabel(taskDraft.output_contract_id || workflowDraft.output_contract_id || "", domainContractSpecs, contractCatalog) },
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
      meta: editorTask ? (coordinationDraft.title || editorSelectedTaskGraph?.title || editorTask.task_title) : "未打开任务",
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
      meta: "待重建",
      detail: "旧业务模板已清理；新模板将按任务域隔离注册",
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
      meta: activeTaskGraph?.title || "任务图",
      detail: "查看当前任务图的契约覆盖与校验摘要",
    },
  ];
  function selectTaskForEditor(taskId: string) {
    const nextTask = editorDomainTasks.find((item) => item.task_id === taskId) ?? null;
    const nextDomainId = editorDomain?.domain_id || (nextTask ? taskDomainId(nextTask) : "");
    const nextGraph = allTaskGraphs.find((item) => String(item.domain_id ?? "").trim() === nextDomainId);
    setEditorTaskId(nextTask?.task_id || "");
    setEditorTaskGraphId(nextGraph?.graph_id || "");
    setSelectedGraphNodeId("");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }

  function enterManagementLayer() {
    setTaskLayer("management");
  }

  function selectEditorDomain(domainId: string) {
    const nextDomain = visibleDomains.find((domain) => domain.domain_id === domainId) ?? null;
    const nextTask = nextDomain?.tasks[0] ?? null;
    const nextDomainId = nextDomain?.domain_id || (nextTask ? taskDomainId(nextTask) : "");
    const nextGraph = allTaskGraphs.find((item) => String(item.domain_id ?? "").trim() === nextDomainId);
    setEditorDomainId(nextDomain?.domain_id || "");
    setEditorTaskId(nextTask?.task_id || "");
    setEditorTaskGraphId(nextGraph?.graph_id || "");
    setSelectedGraphNodeId("");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }

  return (
    <div className={`workspace-view boundary-console task-system-boundary task-system-boundary--${taskLayer}`}>
      <header className={taskLayer === "editor" ? "boundary-hero boundary-hero--editor" : "boundary-hero"}>
        <div>
          <span>{taskLayer === "editor" ? "任务图编辑器" : "任务边界工作台"}</span>
          <h2>{taskLayer === "editor" ? editorTask?.task_title || "任务图编辑器" : "任务系统工作台"}</h2>
          <p>{taskLayer === "editor" ? `${editorDomain?.title || "未选择任务域"} / ${coordinationDraft.title || editorSelectedTaskGraph?.title || "任务图"}` : "任务域是第一管理边界；图编辑器只编辑当前任务域下的 Agent 拓扑。"}</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton onClick={() => void load()}><RefreshCw size={15} />刷新</ToolbarButton>
        </div>
      </header>

      <section className="task-system-page-strip" aria-label="任务系统页面">
        {taskLayerItems.map((item) => (
          <button
            className={taskLayer === item.value ? "task-system-page-tab task-system-page-tab--active" : "task-system-page-tab"}
            key={item.value}
            onClick={() => {
              void load();
              if (item.value === "management") {
                enterManagementLayer();
                return;
              }
              setTaskLayer("editor");
            }}
            type="button"
          >
            <span>{item.label}</span>
            <strong>{item.meta}</strong>
          </button>
        ))}
      </section>

      {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}
      {notice ? <div className="boundary-notice"><CheckCircle2 size={16} />{notice}</div> : null}

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
          {!loading && projectionLoading ? <div className="boundary-empty">投影卡片加载中，任务系统已可用</div> : null}
          {visibleDomains.map((domain) => {
            const active = domain.domain_id === selectedDomainId;
            return (
              <article className={active ? "boundary-domain boundary-domain--active" : "boundary-domain"} key={domain.domain_id}>
                <button
                  className="boundary-domain__select"
                  onClick={() => {
                    setSelectedDomainId(domain.domain_id);
                    setSelectedTaskId(domain.tasks[0]?.task_id || "");
                    const nextGraph = (consolePayload?.task_graph_management?.task_graphs ?? consolePayload?.coordination_management?.task_graphs ?? []).find((item) => String(item.domain_id ?? "").trim() === domain.domain_id);
                    setSelectedTaskGraphId(nextGraph?.graph_id || "");
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
                      <span>{task.enabled ? "启用" : "停用"}</span>
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
                            <Field label="所属任务域"><input readOnly value={selectedDomain?.title || domainTitle(domainIdToLegacyFamily(taskDomainId(taskDraft)))} /></Field>
                            <Field label="验收档案"><input value={taskDraft.acceptance_profile_id} onChange={(event) => setTaskDraft((value) => ({ ...value, acceptance_profile_id: event.target.value }))} /></Field>
                            <Field label="任务描述" wide><textarea value={taskDraft.description} onChange={(event) => setTaskDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                            <label className="boundary-check"><input checked={taskDraft.enabled} onChange={(event) => setTaskDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用任务</label>
                            <section className="contract-editor-section task-artifact-policy-editor">
                              <header><strong>产物规则</strong><span>任务运行结束后按这里的规则生成真实文件</span></header>
                              <div className="boundary-form">
                                <Field label="产物根目录"><input value={artifactPolicyDraft.artifact_root} onChange={(event) => setArtifactPolicyDraft((value) => ({ ...value, artifact_root: event.target.value }))} placeholder="output/novels/honghuang-shidai" /></Field>
                                <Field label="任务子目录"><input value={artifactPolicyDraft.subdir_template} onChange={(event) => setArtifactPolicyDraft((value) => ({ ...value, subdir_template: event.target.value }))} placeholder="{task_slug}/{run_slug}" /></Field>
                                <Field label="生成器"><input value={artifactPolicyDraft.materializer} onChange={(event) => setArtifactPolicyDraft((value) => ({ ...value, materializer: event.target.value }))} /></Field>
                                <label className="boundary-check"><input checked={artifactPolicyDraft.enabled} onChange={(event) => setArtifactPolicyDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用产物落盘</label>
                                <Field label="必需产物" wide><textarea value={artifactPolicyDraft.required_files_text} onChange={(event) => setArtifactPolicyDraft((value) => ({ ...value, required_files_text: event.target.value }))} placeholder={"01_project_bible.md\n02_world_bible.md"} /></Field>
                                <Field label="可选产物" wide><textarea value={artifactPolicyDraft.optional_files_text} onChange={(event) => setArtifactPolicyDraft((value) => ({ ...value, optional_files_text: event.target.value }))} placeholder="chapters/chapter_001_draft.md" /></Field>
                              </div>
                            </section>
                            <SystemFields>
                              <Field label="任务 ID"><input value={taskDraft.task_id} onChange={(event) => setTaskDraft((value) => ({ ...value, task_id: event.target.value }))} /></Field>
                              <ContractSelectField contracts={domainContractSpecs} legacyContracts={contractCatalog} label="输入契约" onChange={(value) => setTaskDraft((current) => ({ ...current, input_contract_id: value }))} options={commonContractOptions} value={taskDraft.input_contract_id} />
                              <ContractSelectField contracts={domainContractSpecs} legacyContracts={contractCatalog} label="输出契约" onChange={(value) => setTaskDraft((current) => ({ ...current, output_contract_id: value }))} options={commonContractOptions} value={taskDraft.output_contract_id} />
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
                  null
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
                  contractManagement={{ ...contractManagement, contract_specs: domainContractSpecs }}
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
                        <span>域级模板中心</span>
                        <strong>模板注册待重建</strong>
                        <small>按任务域隔离</small>
                      </div>
                    </header>
                    <p>旧任务包模板已经下线。后续模板能力需要从任务域进入，模板只注册契约草案，不直接创建 Agent 或跨域资产。</p>
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
                    contractSpecs={domainContractSpecs}
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
                          <span>{contractLabel(String(node.node_contract_id ?? node.output_contract_id ?? ""), domainContractSpecs, contractCatalog)}</span>
                        </article>
                      ))}
                      {activeGraphEdges.map((edge, index) => (
                        <article className="boundary-list-row" key={String(edge.edge_id ?? `edge_${index}`)}>
                          <strong>{String(edge.label ?? edge.title ?? "交接边")}</strong>
                          <span>{contractLabel(String(edge.payload_contract_id ?? edge.contract_id ?? ""), domainContractSpecs, contractCatalog)}</span>
                        </article>
                      ))}
                    </div>
                  </section>
                </section>
              ) : null}

              {contractPanel === "manifest" ? (
                <ContractOverviewPanel
                  contractSpecs={domainContractSpecs}
                  selectedCoordination={activeTaskGraph}
                  selectedNodeId={selectedGraphNodeId}
                  selectedTask={selectedTask}
                />
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
              selectedCoordination={activeTaskGraph}
              coordinationMetadata={coordinationDraft.metadata}
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
              selectedCoordination={activeTaskGraph}
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
          <section className="task-graph-editor-chrome" aria-label="任务图编辑器操作台">
            <div className="task-graph-editor-chrome__controls">
              <label className="task-graph-editor-chrome__field">
                <span className="task-graph-editor-chrome__field-label">任务域</span>
                <select value={editorDomainId} onChange={(event) => selectEditorDomain(event.target.value)}>
                  <option disabled={visibleDomains.length > 0} value="">{visibleDomains.length ? "选择任务域" : "暂无任务域"}</option>
                  {visibleDomains.map((domain) => (
                    <option key={domain.domain_id} value={domain.domain_id}>{domain.title}</option>
                  ))}
                </select>
              </label>
              <label className="task-graph-editor-chrome__field">
                <span className="task-graph-editor-chrome__field-label">任务</span>
                <select disabled={!editorDomain} value={editorTaskId} onChange={(event) => selectTaskForEditor(event.target.value)}>
                  {!editorDomain ? <option value="">先选择任务域</option> : null}
                  {editorDomain && !editorDomainTasks.length ? <option value="">当前任务域暂无任务</option> : null}
                  {editorDomainTasks.map((task) => (
                    <option key={task.task_id} value={task.task_id}>{task.task_title}</option>
                  ))}
                </select>
              </label>
              <label className="task-graph-editor-chrome__field">
                <span className="task-graph-editor-chrome__field-label">图草稿</span>
                <select disabled={!editorTask} value={editorTaskGraphId} onChange={(event) => {
                  setEditorTaskGraphId(event.target.value);
                  setSelectedGraphNodeId("");
                  setSelectedGraphEdgeId("");
                  setLinkingFromNodeId("");
                }}>
                  {!editorTask ? <option value="">先打开任务</option> : null}
                  {editorTask && !editorTaskGraphs.length ? <option value="">暂无草稿</option> : null}
                  {editorTaskGraphs.map((task) => (
                    <option key={task.graph_id} value={task.graph_id}>{task.title}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="task-graph-editor-chrome__status task-graph-editor-chrome__status--context">
              <span className={topologyDirty ? "boundary-status boundary-status--warn" : "boundary-status"}>{topologyDirty ? "拓扑未同步" : "拓扑已同步"}</span>
              <span className="boundary-status">图编辑动作请在 Studio 顶栏执行</span>
            </div>
            <div className="task-graph-editor-chrome__actions task-graph-editor-chrome__actions--minimal">
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
            contractSpecs={editorContractSpecs}
            taskGraphs={editorTaskGraphs}
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
            legacyDrafts={{ coordinationDraft: coordinationDraft as never, topologyDraft, protocolDraft }}
            linkingFromNodeId={linkingFromNodeId}
            removeTaskGraphEdge={removeCoordinationEdge}
            removeTaskGraphNode={removeCoordinationNode}
            reverseTaskGraphEdge={reverseCoordinationEdge}
            saveTaskGraphStack={saveCoordinationStack}
            saving={saving}
            selectedTaskGraph={editorSelectedTaskGraph}
            selectedTaskGraphId={editorTaskGraphId}
            selectedDomain={editorDomain}
            selectedDomainTasks={editorDomainTasks}
            selectedGraphEdge={selectedGraphEdge}
            selectedGraphEdgeId={selectedGraphEdgeId}
            selectedGraphNode={selectedGraphNode}
            selectedGraphNodeId={selectedGraphNodeId}
            selectedTaskGraphSpec={editorGraphSpec}
            sendTaskGraphToChat={sendTaskGraphToChat}
            setCoordinationDraft={setCoordinationDraft as never}
            setLinkingFromNodeId={setLinkingFromNodeId}
            setProtocolDraft={setProtocolDraft}
            setSelectedTaskGraphId={setEditorTaskGraphId}
            setSelectedGraphEdgeId={setSelectedGraphEdgeId}
            setSelectedGraphNodeId={setSelectedGraphNodeId}
            setTaskGraphPublished={setCoordinationPublished}
            setTopologyDraft={setTopologyDraft}
            taskGraphDirty={topologyDirty}
            taskGraphDraft={taskGraphDraft}
            taskGraphDraftV2={taskGraphDraftV2}
            updateTaskGraphEdge={updateCoordinationEdge}
            updateTaskGraphNode={updateCoordinationNode}
            orchestrationAgentCatalog={orchestrationAgentCatalog}
            onCreateProjectionFromPrompt={createProjectionFromNodePrompt}
            projectionCards={domainProjectionCards}
          />
        </section>
      ) : null}
    </div>
  );
}








