"use client";

import {
  Network,
  Plus,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import { TaskGraphWorkbench } from "@/components/workspace/views/task-system/TaskGraphWorkbench";
import { ProfessionalRunSessionPage } from "@/components/workspace/views/task-system/ProfessionalRunSessionPage";
import { ResourceAuthorityMapPage } from "@/components/workspace/views/task-system/ResourceAuthorityMapPage";
import { TaskSystemShell } from "@/components/workspace/views/task-system/TaskSystemShell";
import { TaskContractLibraryPage } from "@/components/workspace/views/task-system/library/TaskContractLibraryPage";
import { TaskDefinitionLibraryPage } from "@/components/workspace/views/task-system/library/TaskDefinitionLibraryPage";
import { TaskDomainLibraryPage } from "@/components/workspace/views/task-system/library/TaskDomainLibraryPage";
import { TaskGraphLibraryPage } from "@/components/workspace/views/task-system/library/TaskGraphLibraryPage";
import { TaskOrchestrationResourceLibraryPage } from "@/components/workspace/views/task-system/library/TaskOrchestrationResourceLibraryPage";
import { TaskRuntimeLibraryPage } from "@/components/workspace/views/task-system/library/TaskRuntimeLibraryPage";
import {
  asRecord,
  emptyTaskGraphDraftV2,
  inferTaskGraphBoundaryNodes,
  taskGraphRecordToDraftV2,
  type TaskGraphDraftV2,
  type TaskGraphPublishStateV2,
} from "@/components/workspace/views/task-system/taskGraphDraftV2";
import { buildTaskGraphUpsertPayload } from "@/components/workspace/views/task-system/taskGraphSaveMapper";
import {
  MODULAR_NOVEL_DOMAIN_ID,
  recommendedTaskGraphId,
  sortTaskGraphsForWorkbench,
} from "@/components/workspace/views/task-system/taskGraphSelection";
import { buildTaskGraphTemplateDraft, type TaskGraphTemplateId } from "@/components/workspace/views/task-system/taskGraphTemplates";
import {
  graphEdgeId,
  graphEdgeSource,
  graphEdgeTarget,
  graphNodeTaskId,
} from "@/components/workspace/views/task-system/taskGraphTopologyUtils";
import {
  TaskGraphChromeSelect,
  TaskSystemToolbarButton as ToolbarButton,
  taskSystemDisplayLabel,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import {
  deleteTaskSystemDomain,
  deleteTaskSystemSpecificRecord,
  createSoulProjectionCard,
  getArtifactRepositoryOverview,
  getFormalMemoryOverview,
  getOrchestrationAgents,
  getOrchestrationResourceInventory,
  getOrchestrationRuntimeLoopTaskRunLiveMonitor,
  listOrchestrationRuntimeLoopTaskRuns,
  getSoulProjectionCards,
  getTaskSystemTaskGraph,
  getTaskSystemTaskGraphStandardView,
  getTaskSystemNextIds,
  getTaskSystemOverview,
  deleteTaskSystemContract,
  upsertTaskSystemContract,
  upsertTaskSystemDomain,
  upsertTaskSystemEntryPolicy,
  upsertTaskSystemExecutionPolicy,
  upsertTaskSystemFlowContractBinding,
  upsertTaskSystemProjectionBinding,
  upsertTaskSystemSpecificRecord,
  upsertTaskSystemTaskGraph,
  upsertTaskWorkflow,
  type ConversationEntryPolicy,
  type ContractSpec,
  type ArtifactRepositoryOverview,
  type FormalMemoryOverview,
  type OrchestrationAgentRuntimeCatalog,
  type RuntimeResourceInventory,
  type RuntimeLoopTaskRunLiveMonitor,
  type RuntimeLoopTaskRunSummary,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type SpecificTaskRecord,
  type TaskContractDescriptor,
  type TaskDomainRecord,
  type TaskExecutionPolicy,
  type TaskFlowContractBinding,
  type TaskGraphEdgeRecord,
  type TaskGraphNodeRecord,
  type TaskGraphRecord,
  type TaskGraphRuntimeSpec,
  type TaskGraphStandardView,
  type TaskProjectionBinding,
  type TaskSystemOverview,
  type TaskWorkflowRecord,
} from "@/lib/api";
import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { useAppStore } from "@/lib/store";

type TaskLayer = "management" | "editor";
type TaskSystemLayer = "domains" | "tasks" | "graphs" | "contracts" | "resource-authority" | "professional-run" | "orchestration" | "runtime";
type TaskConfigPanel = "definition";
type ContractPanel = "library" | "templates";

type WorkflowDraft = TaskWorkflowRecord & {
  compatible_projection_ids_text: string;
  visible_skill_ids_text: string;
  steps_text: string;
  stop_conditions_text: string;
  required_evidence_refs_text: string;
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

function recordFieldText(record: Record<string, unknown> | null | undefined, keys: string[], fallback = "-") {
  for (const key of keys) {
    const value = record?.[key];
    if (value !== null && value !== undefined && String(value).trim()) {
      return String(value);
    }
  }
  return fallback;
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function getRuntimeTaskRunId(summary: RuntimeLoopTaskRunSummary | null | undefined) {
  return recordFieldText(dictOf(summary?.task_run), ["task_run_id", "id", "run_id"], "");
}

function runtimeTaskRunGraphId(summary: RuntimeLoopTaskRunSummary | null | undefined) {
  return recordFieldText(dictOf(summary?.task_run), ["graph_id", "coordination_task_id", "task_graph_id"], "");
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
    allow_worker_agent_spawn: false,
    worker_agent_blueprint_id: "",
    worker_agent_naming_rule: "",
    notes: "",
    metadata: { managed_by: "task_domain_console" },
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
    "bounded": "受限准入",
    "main_agent": "主 Agent",
    "builtin_agent": "内置 Agent",
    "custom_agent": "自定义 Agent",
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
    ["op.", "操作准入"],
  ];
  const matched = prefixLabels.find(([prefix]) => raw.startsWith(prefix));
  return matched ? `${matched[1]} · ${raw}` : raw;
}

const PROJECTION_SELECTION_MODE_CHOICES = ["task_default"];
const FLOW_OVERRIDE_POLICY_CHOICES = ["task_default"];
const FLOW_FALLBACK_POLICY_CHOICES = ["fail_closed"];
const RUNTIME_SELECTION_POLICY_CHOICES = ["orchestration_default"];
const COMMON_CONTRACT_CHOICES = ["UserMessage", "WorkspaceTaskInput", "AssistantFinalAnswer", "LightWebGameResult"];
const COORDINATION_MODE_CHOICES = ["review_merge", "pipeline", "parallel_review"];
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
  return true;
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
): TaskGraphRuntimeSpec {
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

function taskDomainId(task: SpecificTaskRecord) {
  const metadata = dictOf(task.metadata);
  return String(metadata.domain_id ?? "").trim() || `domain.${task.task_family || "general"}`;
}

type LayerNavItem<T extends string> = {
  value: T;
  label: string;
  meta: string;
  detail: string;
};

export function TaskSystemView() {
  const confirm = useConfirmDialog();
  const {
    activeWorkspaceView,
    currentSessionId,
    setOrchestrationInspectorTarget,
    setTaskGraphRunInteractionOpen,
    setTaskSelection,
    setWorkspaceView,
    taskGraphLiveMonitor,
    taskGraphMonitorBinding,
  } = useAppStore();
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
  const [editorTaskGraphId, setEditorTaskGraphId] = useState("");
  const [taskLayer, setTaskLayer] = useState<TaskLayer>("management");
  const [taskSystemLayer, setTaskSystemLayer] = useState<TaskSystemLayer>("domains");
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
  const [taskPolicyText, setTaskPolicyText] = useState("{}");
  const [artifactPolicyDraft, setArtifactPolicyDraft] = useState<ArtifactPolicyDraft>(defaultArtifactPolicyDraft());
  const [taskGraphDraftV2, setTaskGraphDraftV2] = useState<TaskGraphDraftV2>(() => emptyTaskGraphDraftV2());
  const [taskGraphStandardView, setTaskGraphStandardView] = useState<TaskGraphStandardView | null>(null);
  const [taskGraphStandardViewLoading, setTaskGraphStandardViewLoading] = useState(false);
  const [taskGraphStandardViewError, setTaskGraphStandardViewError] = useState("");
  const [activeTaskGraphDetail, setActiveTaskGraphDetail] = useState<TaskGraphRecord | null>(null);
  const [activeTaskGraphDetailError, setActiveTaskGraphDetailError] = useState("");
  const [runtimeTaskRunId, setRuntimeTaskRunId] = useState("");
  const [runtimeTaskRuns, setRuntimeTaskRuns] = useState<RuntimeLoopTaskRunSummary[]>([]);
  const [runtimeFormalOverview, setRuntimeFormalOverview] = useState<FormalMemoryOverview | null>(null);
  const [runtimeArtifactOverview, setRuntimeArtifactOverview] = useState<ArtifactRepositoryOverview | null>(null);
  const [runtimeLiveMonitor, setRuntimeLiveMonitor] = useState<RuntimeLoopTaskRunLiveMonitor | null>(null);
  const [runtimeResourceInventory, setRuntimeResourceInventory] = useState<RuntimeResourceInventory | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runtimeError, setRuntimeError] = useState("");
  const selectedDomainIdRef = useRef("");
  const projectionCatalogLoadRef = useRef<Promise<void> | null>(null);
  const orchestrationAgentCatalogLoadRef = useRef<Promise<void> | null>(null);
  const runtimeDefaultedRef = useRef(false);

  useEffect(() => {
    selectedDomainIdRef.current = selectedDomainId;
  }, [selectedDomainId]);

  const applyOverview = useCallback((overview: TaskSystemOverview) => {
    setConsolePayload(overview);
    const nextDomains = buildDomains(overview);
    const modularNovelDomain = nextDomains.find((item) => item.domain_id === MODULAR_NOVEL_DOMAIN_ID) ?? null;
    const firstDomainWithTasks = nextDomains.find((item) => item.tasks.length > 0) ?? null;
    const fallbackDomain = firstDomainWithTasks ?? nextDomains[0] ?? null;
    const preferredDomain = nextDomains.find((item) => item.domain_id === selectedDomainIdRef.current) ?? null;
    const selectedDomain = preferredDomain && (preferredDomain.tasks.length > 0 || !firstDomainWithTasks)
      ? preferredDomain
      : modularNovelDomain ?? fallbackDomain;
    const taskGraphs = sortTaskGraphsForWorkbench(overview.task_graph_management?.task_graphs ?? []);
    setSelectedDomainId(selectedDomain?.domain_id ?? "");
    setSelectedTaskId((current) => current || selectedDomain?.tasks[0]?.task_id || overview.task_management.specific_task_records[0]?.task_id || "");
    setEditorDomainId((current) => current || selectedDomain?.domain_id || "");
    setSelectedTaskGraphId((current) => recommendedTaskGraphId(taskGraphs, current));
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
  const selectedWorkflow = workflows.find((item) => item.workflow_id === selectedTask?.default_workflow_id);
  const allTaskGraphs = useMemo(
    () => sortTaskGraphsForWorkbench(consolePayload?.task_graph_management?.task_graphs ?? []),
    [consolePayload],
  );
  const a2aCatalog = useMemo(() => {
    const protocol = consolePayload?.task_graph_management?.a2a;
    if (!protocol) return null;
    const runtimeAgents = orchestrationAgentCatalog?.agents ?? [];
    const agentCards = protocol.agent_cards?.length ? protocol.agent_cards : runtimeAgents;
    return {
      ...protocol,
      agent_cards: agentCards,
    };
  }, [consolePayload, orchestrationAgentCatalog]);
  const activeDomainId = selectedDomain?.domain_id || "";
  const taskGraphs = useMemo(
    () => activeDomainId ? sortTaskGraphsForWorkbench(allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === activeDomainId)) : [],
    [activeDomainId, allTaskGraphs],
  );
  const selectedTaskGraph = taskGraphs.find((item) => item.graph_id === selectedTaskGraphId) ?? taskGraphs[0] ?? null;
  const editorDomain = visibleDomains.find((domain) => domain.domain_id === editorDomainId) ?? visibleDomains[0] ?? null;
  const editorDomainTasks = useMemo(() => editorDomain?.tasks ?? [], [editorDomain]);
  const editorDomainFilterId = editorDomain?.domain_id || "";
  const editorContractSpecs = useMemo(() => scopedContractSpecs(contractSpecs, editorDomain), [contractSpecs, editorDomain]);
  const editorTaskGraphs = useMemo(
    () => editorDomainFilterId ? sortTaskGraphsForWorkbench(allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === editorDomainFilterId)) : [],
    [allTaskGraphs, editorDomainFilterId],
  );
  const editorGraphSelectOptions = useMemo(() => {
    const options = editorTaskGraphs.map((task) => ({ value: task.graph_id, label: `${task.title} · ${task.graph_id}` }));
    const draftGraphId = String(taskGraphDraftV2.graph_id || "").trim();
    const draftInEditorDomain = draftGraphId
      && String(taskGraphDraftV2.domain_id || "").trim() === editorDomainFilterId;
    if (draftInEditorDomain && !options.some((option) => option.value === draftGraphId)) {
      return [
        {
          value: draftGraphId,
          label: `${taskGraphDraftV2.title || draftGraphId}（未保存草稿）`,
        },
        ...options,
      ];
    }
    return options;
  }, [editorDomainFilterId, editorTaskGraphs, taskGraphDraftV2.domain_id, taskGraphDraftV2.graph_id, taskGraphDraftV2.title]);
  const editorSelectedTaskGraph = editorTaskGraphs.find((item) => item.graph_id === editorTaskGraphId) ?? null;
  const activeTaskGraphSummary = taskLayer === "editor" ? editorSelectedTaskGraph : selectedTaskGraph;
  const activeTaskGraph = activeTaskGraphDetail?.graph_id === activeTaskGraphSummary?.graph_id
    ? activeTaskGraphDetail
    : activeTaskGraphSummary;
  const activeTaskGraphHasFullTopology = Boolean((activeTaskGraphDetail?.nodes?.length || activeTaskGraphDetail?.edges?.length) && activeTaskGraphDetail.graph_id === activeTaskGraphSummary?.graph_id);
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
  const activeTaskGraphId = activeTaskGraphSummary?.graph_id || "";

  useEffect(() => {
    if (activeWorkspaceView !== "task-system") return;
    if (!activeTaskGraphId) {
      setActiveTaskGraphDetail(null);
      setActiveTaskGraphDetailError("");
      return;
    }
    let cancelled = false;
    setActiveTaskGraphDetailError("");
    void getTaskSystemTaskGraph(activeTaskGraphId)
      .then((payload) => {
        if (!cancelled) setActiveTaskGraphDetail(payload);
      })
      .catch((exc) => {
        if (!cancelled) {
          setActiveTaskGraphDetail(null);
          setActiveTaskGraphDetailError(exc instanceof Error ? exc.message : "任务图详情加载失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeTaskGraphId, activeWorkspaceView]);

  const refreshTaskGraphStandardView = useCallback(async () => {
    if (!activeTaskGraphId) {
      setTaskGraphStandardView(null);
      setTaskGraphStandardViewError("");
      return;
    }
    setTaskGraphStandardViewLoading(true);
    setTaskGraphStandardViewError("");
    try {
      const payload = await getTaskSystemTaskGraphStandardView(activeTaskGraphId);
      setTaskGraphStandardView(payload);
    } catch (exc) {
      setTaskGraphStandardView(null);
      setTaskGraphStandardViewError(exc instanceof Error ? exc.message : "标准对象视图加载失败");
    } finally {
      setTaskGraphStandardViewLoading(false);
    }
  }, [activeTaskGraphId]);

  useEffect(() => {
    if (activeWorkspaceView !== "task-system") return;
    if (!activeTaskGraphId) {
      setTaskGraphStandardView(null);
      setTaskGraphStandardViewError("");
      return;
    }
    void refreshTaskGraphStandardView();
  }, [activeTaskGraphId, activeWorkspaceView, refreshTaskGraphStandardView]);
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

  const openOrchestrationControl = useCallback((focus?: {
    agentId?: string;
    agentProfileId?: string;
    layer?: "registry" | "groups" | "runtime" | "eligibility";
    nodeId?: string;
    reason?: string;
  }) => {
    const focusedGraphId = taskLayer === "editor"
      ? (editorTaskGraphId || taskGraphDraftV2.graph_id)
      : (selectedTaskGraphId || taskGraphDraftV2.graph_id);
    setOrchestrationInspectorTarget({
      source: "task-system",
      orchestrationLayer: focus?.layer ?? "runtime",
      agentId: focus?.agentId,
      agentProfileId: focus?.agentProfileId,
      graphId: focusedGraphId || undefined,
      nodeId: focus?.nodeId,
      reason: focus?.reason ?? "从任务系统进入编排页：配置 Agent 运行档案。",
    });
    setWorkspaceView("orchestration");
  }, [editorTaskGraphId, selectedTaskGraphId, setOrchestrationInspectorTarget, setWorkspaceView, taskGraphDraftV2.graph_id, taskLayer]);

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
    const graphRef = taskGraphDraftV2.graph_id || editorTaskGraphId || selectedTaskGraphId || "task_graph";
    const graphSlug = slugFromTitle(graphRef);
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
      source_task_graph_refs: [graphRef].filter(Boolean),
      projection_name: `${text(node.title ?? node.label ?? nodeId, nodeId)} / 节点职责`,
      role_type: role,
      task_mode: editorDomainTasks.find((task) => task.task_id === graphNodeTaskId(node))?.task_mode || selectedTask?.task_mode || "task_graph_node",
      agent_profile_id: agentProfileId,
      projection_prompt: prompt,
      usage_summary: "由图工作台节点职责生成的静态投影，用于运行装配时绑定节点 Prompt。",
      memory_policy_summary: "记忆读写连接由 TaskGraph 资源节点、读写边与 Agent 运行档案共同决定。",
      output_contract_summary: "输出边界由 TaskGraph 节点契约和边交接契约决定。",
      select_after_create: false,
    });
    setProjectionCatalog(nextCatalog);
    return nextProjectionId;
  }, [
    editorDomainTasks,
    editorTaskGraphId,
    orchestrationAgentCatalog?.profiles,
    projectionCatalog,
    selectedTask?.task_mode,
    selectedTaskGraphId,
    taskGraphDraftV2.graph_id,
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
      setSelectedTaskGraphId(recommendedTaskGraphId(taskGraphs));
    }
  }, [taskGraphs, selectedTaskGraphId]);

  useEffect(() => {
    if (!editorTaskGraphs.some((item) => item.graph_id === editorTaskGraphId)) {
      if (editorTaskGraphId && editorTaskGraphId === taskGraphDraftV2.graph_id) {
        return;
      }
      setEditorTaskGraphId(recommendedTaskGraphId(editorTaskGraphs));
    }
  }, [editorTaskGraphId, editorTaskGraphs, taskGraphDraftV2.graph_id]);

  useEffect(() => {
    if (!selectedTask) return;
    setTaskDraft({ ...selectedTask, metadata: selectedTask.metadata ?? {}, task_policy: selectedTask.task_policy ?? {} });
    setTaskPolicyText(JSON.stringify(selectedTask.task_policy ?? {}, null, 2));
    setArtifactPolicyDraft(artifactPolicyDraftFrom(selectedTask.task_policy ?? {}));
    setWorkflowDraft(workflowDraftFrom(selectedWorkflow, selectedTask.task_mode));
    setProjectionDraft(projectionBinding ?? emptyProjectionBinding(selectedTask.task_id, ""));
    setFlowDraft(flowBinding ?? emptyFlowBinding(selectedTask.task_id, selectedTask.default_flow_contract_id));
    setExecutionDraft(executionPolicy ?? emptyExecutionPolicy(selectedTask.task_id));
  }, [selectedTask, selectedWorkflow, projectionBinding, flowBinding, executionPolicy]);

  useEffect(() => {
    if (!activeTaskGraph) {
      if (taskLayer === "editor" && editorTaskGraphId && editorTaskGraphId === taskGraphDraftV2.graph_id) {
        return;
      }
      setTaskGraphDraftV2(emptyTaskGraphDraftV2());
      return;
    }
    if (!activeTaskGraphHasFullTopology && activeTaskGraph.overview_mode === "summary") {
      return;
    }
    const nextNodes = (activeTaskGraph.nodes ?? []).map(normalizeTaskGraphNode);
    const nextEdges = (activeTaskGraph.edges ?? []).map(normalizeTaskGraphEdge);
    const graphDraftV2 = taskGraphRecordToDraftV2({
      ...activeTaskGraph,
      nodes: nextNodes,
      edges: nextEdges,
    });
    setTaskGraphDraftV2(graphDraftV2);
    setSelectedGraphNodeId(String((activeTaskGraph.nodes ?? [])[0]?.node_id ?? ""));
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }, [activeTaskGraph, activeTaskGraphHasFullTopology, editorTaskGraphId, taskGraphDraftV2.graph_id, taskLayer]);

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

  function normalizeTaskGraphNode(node: Record<string, unknown>, index = 0): TaskGraphNodeRecord {
    const nodeId = String(node.node_id ?? node.id ?? `node_${index + 1}`).trim();
    const title = String(node.title ?? node.label ?? node.task_title ?? nodeId).trim() || nodeId;
    return {
      ...node,
      node_id: nodeId,
      node_type: String(node.node_type ?? "agent_role"),
      title,
    };
  }

  function normalizeTaskGraphEdge(edge: Record<string, unknown>, index = 0): TaskGraphEdgeRecord {
    const source = graphEdgeSource(edge);
    const target = graphEdgeTarget(edge);
    const edgeId = String(edge.edge_id ?? edge.id ?? (source && target ? `${source}->${target}` : `edge_${index + 1}`)).trim();
    return {
      ...edge,
      edge_id: edgeId,
      source_node_id: source,
      target_node_id: target,
      edge_type: String(edge.edge_type ?? edge.mode ?? "handoff"),
    };
  }

  function syncTaskGraphTopology(nodes: Array<Record<string, unknown>>, edges: Array<Record<string, unknown>>) {
    const nextNodes = nodes.map(normalizeTaskGraphNode);
    const nextEdges = edges.map(normalizeTaskGraphEdge);
    const boundaries = inferTaskGraphBoundaryNodes(nextNodes, nextEdges);
    setTaskGraphDraftV2((current) => ({
      ...current,
      nodes: nextNodes,
      edges: nextEdges,
      entry_node_id: boundaries.entry_node_id,
      output_node_id: boundaries.output_node_id,
    }));
  }

  function addTaskGraphNode() {
    const existingNodes = taskGraphDraftV2.nodes ?? [];
    const nextIndex = existingNodes.length + 1;
    const existingTaskIds = new Set(existingNodes.map((node) => graphNodeTaskId(node)).filter(Boolean));
    const nextTask = graphContextDomainTasks.find((task) => !existingTaskIds.has(task.task_id));
    const nodeId = nextTask ? `subtask_${nextIndex}` : `agent_${nextIndex}`;
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
    syncTaskGraphTopology([...existingNodes, node], taskGraphDraftV2.edges ?? []);
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function addTaskGraphTaskNode(task: SpecificTaskRecord, role = "participant") {
    const nodeId = `subtask_${String((taskGraphDraftV2.nodes?.length || 0) + 1)}`;
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
    syncTaskGraphTopology([...(taskGraphDraftV2.nodes ?? []), node], taskGraphDraftV2.edges ?? []);
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function addTaskGraphRoleNode(role: string) {
    const nextIndex = (taskGraphDraftV2.nodes?.length || 0) + 1;
    const normalizedRole = role === "memory" ? "memory_repository" : role;
    const resourceNodeTypes = new Set(["memory_repository", "artifact_repository", "thread_ledger", "progress_ledger", "issue_ledger"]);
    const resourcePrefixByRole: Record<string, string> = {
      memory_repository: "memory.repository",
      artifact_repository: "artifact.repository",
      thread_ledger: "thread.ledger",
      progress_ledger: "progress.ledger",
      issue_ledger: "issue.ledger",
    };
    const isResourceNode = resourceNodeTypes.has(normalizedRole);
    const existingNodeIds = new Set((taskGraphDraftV2.nodes ?? []).map((node) => String(node.node_id ?? "")));
    let nodeId = normalizedRole === "coordinator"
      ? `coordinator_${nextIndex}`
      : isResourceNode
        ? `${resourcePrefixByRole[normalizedRole]}.1`
        : `agent_${nextIndex}`;
    if (isResourceNode) {
      let resourceIndex = 1;
      while (existingNodeIds.has(nodeId)) {
        resourceIndex += 1;
        nodeId = `${resourcePrefixByRole[normalizedRole]}.${resourceIndex}`;
      }
    }
    const titleByRole: Record<string, string> = {
      coordinator: "协调器",
      planner: "规划节点",
      executor: "执行节点",
      reviewer: "审查节点",
      verifier: "验证节点",
      summarizer: "整理节点",
      merge: "汇总节点",
      memory: "记忆仓库",
      memory_repository: "记忆仓库",
      artifact_repository: "产物仓库",
      thread_ledger: "线程账本",
      progress_ledger: "线程账本（旧名）",
      issue_ledger: "问题台账",
      writer: "执行节点",
      acceptance: "验收节点",
      participant: "协作节点",
    };
    const resourceMetadata = normalizedRole === "memory_repository" || normalizedRole.endsWith("_ledger")
      ? {
        memory_repository: {
          repository_id: nodeId,
          schema_id: "schema.memory_record",
          collections: [{
            collection_id: "default",
            title: "默认集合",
            record_kinds: [],
            key_strategy: "stable_key",
            default_version_selector: "latest_committed_before_clock",
            required_commit_status: "committed",
          }],
        },
      }
      : normalizedRole === "artifact_repository"
        ? {
          artifact_repository: {
            repository_id: nodeId,
            schema_id: "schema.artifact_ref",
          },
        }
        : {};
    const node = {
      node_id: nodeId,
      node_type: isResourceNode ? normalizedRole : "agent_role",
      task_id: "",
      task_title: "",
      task_family: graphContextFamily,
      agent_id: "",
      role: isResourceNode ? "resource" : normalizedRole,
      work_posture: isResourceNode ? "resource" : normalizedRole,
      label: titleByRole[normalizedRole] ?? "协作节点",
      title: titleByRole[normalizedRole] ?? "协作节点",
      ...(isResourceNode ? {
        metadata: resourceMetadata,
        resource_lifecycle_policy: {
          versioning: "append_version",
          mutable: true,
          commit_required: normalizedRole !== "artifact_repository",
        },
      } : {}),
    };
    syncTaskGraphTopology([...(taskGraphDraftV2.nodes ?? []), node], taskGraphDraftV2.edges ?? []);
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  async function applyTaskGraphTemplate(template: TaskGraphTemplateId, options: Partial<Parameters<typeof buildTaskGraphTemplateDraft>[0]> = {}) {
    const shouldReplace = !(taskGraphDraftV2.nodes?.length || taskGraphDraftV2.edges?.length)
      || await confirm({
        title: "替换当前拓扑草稿",
        body: "应用图模板会替换当前未保存的节点和边。",
        confirmLabel: "替换",
        tone: "warning",
      });
    if (!shouldReplace) return;
    const metadata = asRecord(taskGraphDraftV2.metadata);
    const communicationModes = Array.isArray(metadata.business_communication_modes) ? metadata.business_communication_modes : [];
    const mode = String(communicationModes[0] ?? "structured_handoff");
    const selectedTaskForNode = graphContextDomainTasks[0] ?? null;
    const templateDraft = buildTaskGraphTemplateDraft({
      template_id: template,
      task_family: graphContextFamily,
      selected_task_title: selectedTaskForNode?.task_title || "",
      communication_mode: mode,
      ...options,
    });
    const nodes = templateDraft.nodes;
    const edges = templateDraft.edges;
    syncTaskGraphTopology(nodes, edges);
    setTaskGraphDraftV2((current) => ({
      ...current,
      entry_node_id: templateDraft.entry_node_id,
      output_node_id: templateDraft.output_node_id,
      runtime_policy: {
        ...current.runtime_policy,
        coordination_mode: templateDraft.coordination_mode,
        participant_agent_ids: templateDraft.participant_agent_ids,
      },
      metadata: {
        ...asRecord(current.metadata),
        ...templateDraft.metadata,
        setup_template_id: template,
      },
    }));
    setSelectedGraphNodeId(nodes[0]?.node_id ?? "");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
    setTaskLayer("editor");
  }

  function addTaskGraphSuccessorNode(fromNodeId: string) {
    const nextIndex = (taskGraphDraftV2.nodes?.length || 0) + 1;
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
      edge_id: `edge_${String((taskGraphDraftV2.edges?.length || 0) + 1)}`,
      from: fromNodeId,
      to: nodeId,
      source_node_id: fromNodeId,
      target_node_id: nodeId,
      mode: "structured_handoff",
    };
    syncTaskGraphTopology([...(taskGraphDraftV2.nodes ?? []), node], [...(taskGraphDraftV2.edges ?? []), edge]);
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }

  function updateTaskGraphNode(nodeId: string, patch: Record<string, unknown>) {
    const nextNodesSnapshot = (taskGraphDraftV2.nodes ?? []).map((node) =>
      String(node.node_id ?? "") === nodeId ? { ...node, ...patch } : node,
    );
    syncTaskGraphTopology(nextNodesSnapshot, taskGraphDraftV2.edges ?? []);
  }

  function removeTaskGraphNode(nodeId: string) {
    const nextNodes = (taskGraphDraftV2.nodes ?? []).filter((node) => String(node.node_id ?? "") !== nodeId);
    const nextEdges = (taskGraphDraftV2.edges ?? []).filter(
      (edge) => graphEdgeSource(edge) !== nodeId && graphEdgeTarget(edge) !== nodeId,
    );
    syncTaskGraphTopology(nextNodes, nextEdges);
    if (selectedGraphNodeId === nodeId) setSelectedGraphNodeId("");
    if (linkingFromNodeId === nodeId) setLinkingFromNodeId("");
  }

  function handleTopologyNodeClick(nodeId: string) {
    if (linkingFromNodeId) {
      if (linkingFromNodeId !== nodeId) {
        const from = linkingFromNodeId;
        const to = nodeId;
        const exists = (taskGraphDraftV2.edges ?? []).some((edge) => graphEdgeSource(edge) === from && graphEdgeTarget(edge) === to);
        if (!exists) {
          const nextIndex = (taskGraphDraftV2.edges?.length || 0) + 1;
          const edge = {
            edge_id: `edge_${nextIndex}`,
            from,
            to,
            source_node_id: from,
            target_node_id: to,
            mode: "structured_handoff",
          };
          setSelectedGraphEdgeId(graphEdgeId(edge, nextIndex - 1));
          syncTaskGraphTopology(taskGraphDraftV2.nodes ?? [], [...(taskGraphDraftV2.edges ?? []), edge]);
        }
      }
      setLinkingFromNodeId("");
      setSelectedGraphNodeId("");
      return;
    }
    setSelectedGraphNodeId(nodeId);
    setSelectedGraphEdgeId("");
  }

  function updateTaskGraphEdge(edgeId: string, patch: Record<string, unknown>) {
    const nextEdgesSnapshot = (taskGraphDraftV2.edges ?? []).map((edge, index) =>
      graphEdgeId(edge, index) === edgeId ? { ...edge, ...patch } : edge,
    );
    syncTaskGraphTopology(taskGraphDraftV2.nodes ?? [], nextEdgesSnapshot);
  }

  function reverseTaskGraphEdge(edgeId: string) {
    const nextEdges = (taskGraphDraftV2.edges ?? []).map((edge, index) => {
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
    syncTaskGraphTopology(taskGraphDraftV2.nodes ?? [], nextEdges);
  }

  function removeTaskGraphEdge(edgeId: string) {
    const nextEdges = (taskGraphDraftV2.edges ?? []).filter((edge, index) => graphEdgeId(edge, index) !== edgeId);
    syncTaskGraphTopology(taskGraphDraftV2.nodes ?? [], nextEdges);
    if (selectedGraphEdgeId === edgeId) setSelectedGraphEdgeId("");
  }

  async function createTaskGraphDraft() {
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftDomainId = draftDomain?.domain_id || taskGraphDraftV2.domain_id || "";
    const draftFamily = domainIdToLegacyFamily(draftDomainId, "");
    if (!draftDomainId) {
      setError("请先选择任务域，再创建任务图。");
      return;
    }
    setSaving("task-graph-create");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const graphId = ids.graph_id;
      const nextDraft: TaskGraphDraftV2 = {
        ...emptyTaskGraphDraftV2(),
        graph_id: graphId,
        title: `${ids.display_numbers.graph} 任务图`,
        domain_id: draftDomainId,
        task_family: draftFamily,
        task_id: "",
        metadata: {
          managed_by: "task_domain_console",
          graph_source: "task_graph_editor_v2",
          draft_identity_locked: true,
          task_family: draftFamily,
          domain_id: draftDomainId,
        },
      };
      nextDraft.metadata = {
        ...nextDraft.metadata,
        task_family: draftFamily,
        domain_id: draftDomainId,
      };
      setEditorDomainId(draftDomainId);
      setEditorTaskGraphId(nextDraft.graph_id);
      setSelectedTaskGraphId(nextDraft.graph_id);
      setTaskLayer("editor");
      setTaskGraphDraftV2(nextDraft);
      setSelectedGraphNodeId("");
      setSelectedGraphEdgeId("");
      setLinkingFromNodeId("");
      setNotice(`已生成任务图草稿：${nextDraft.graph_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "生成任务图草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function duplicateTaskGraphDraft() {
    const sourceTaskGraph = taskLayer === "editor" ? editorSelectedTaskGraph : selectedTaskGraph;
    if (!sourceTaskGraph) {
      setError("当前没有可复制的任务图");
      return;
    }
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const sourceDraft = taskGraphRecordToDraftV2(sourceTaskGraph);
    const draftDomainId = draftDomain?.domain_id || sourceDraft.domain_id || "";
    const draftFamily = sourceDraft.task_family || domainIdToLegacyFamily(draftDomainId, "");
    setSaving("task-graph-duplicate");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const nextGraphId = ids.graph_id;
      const nextTitle = `${sourceDraft.title || ids.display_numbers.graph} 副本`;
      const nextNodes = (sourceDraft.nodes ?? []).map(normalizeTaskGraphNode);
      const nextEdges = (sourceDraft.edges ?? []).map(normalizeTaskGraphEdge);
      const boundaries = inferTaskGraphBoundaryNodes(nextNodes, nextEdges);
      const nextDraft: TaskGraphDraftV2 = {
        ...sourceDraft,
        graph_id: nextGraphId,
        title: nextTitle,
        domain_id: draftDomainId,
        task_family: draftFamily,
        task_id: "",
        nodes: nextNodes,
        edges: nextEdges,
        entry_node_id: boundaries.entry_node_id,
        output_node_id: boundaries.output_node_id,
        publish_state: "draft",
        metadata: {
          ...asRecord(sourceDraft.metadata),
          graph_source: "task_graph_editor_v2",
          duplicated_from_graph_id: sourceDraft.graph_id,
          task_family: draftFamily,
          domain_id: draftDomainId,
          task_id: undefined,
        },
      };
      setEditorDomainId(draftDomainId);
      setEditorTaskGraphId(nextGraphId);
      setSelectedTaskGraphId(nextGraphId);
      setTaskLayer("editor");
      setTaskGraphDraftV2(nextDraft);
      setSelectedGraphNodeId(String((nextDraft.nodes ?? [])[0]?.node_id ?? ""));
      setSelectedGraphEdgeId("");
      setLinkingFromNodeId("");
      setNotice(`已复制任务图草稿：${nextGraphId}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "复制任务图草稿失败");
    } finally {
      setSaving("");
    }
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
    const confirmed = await confirm({
      title: `删除任务域「${domain.title}」`,
      body: `这会同时删除该任务域下的 ${domain.tasks.length} 个特定任务及其装配配置。`,
      confirmLabel: "删除任务域",
    });
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
    const confirmed = await confirm({
      title: `删除特定任务「${task.task_title}」`,
      body: "这会同时删除该任务的单任务装配配置。",
      confirmLabel: "删除任务",
    });
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
      const payload = await upsertTaskSystemExecutionPolicy(taskPayload.task_id, {
        ...executionDraft,
      });
      setConsolePayload(payload);
      setSelectedTaskId(taskPayload.task_id);
      setNotice("任务定义与单任务装配已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务装配失败");
    } finally {
      setSaving("");
    }
  }

  async function saveTaskGraphStack(nextPublished?: boolean, nextEditorPublishState?: "draft" | "saved" | "preflight_passed" | "published" | "run_bound" | "archived") {
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftDomainId = draftDomain?.domain_id || taskGraphDraftV2.domain_id || "";
    const draftFamily = taskGraphDraftV2.task_family || domainIdToLegacyFamily(draftDomainId, "");
    if (!draftDomainId) {
      setError("请先选择任务域，再保存任务图。");
      return;
    }
    setSaving("task-graph");
    setError("");
    setNotice("");
    try {
      const graphNodes = (taskGraphDraftV2.nodes ?? []).map(normalizeTaskGraphNode);
      const graphEdges = (taskGraphDraftV2.edges ?? []).map(normalizeTaskGraphEdge);
      const effectiveTaskGraphDraftV2: TaskGraphDraftV2 = {
        ...taskGraphDraftV2,
        domain_id: draftDomainId,
        task_family: draftFamily,
        task_id: "",
        nodes: graphNodes,
        edges: graphEdges,
        publish_state: nextPublished === true
          ? "published"
          : nextPublished === false
            ? "draft"
            : nextEditorPublishState ?? taskGraphDraftV2.publish_state,
        metadata: {
          ...asRecord(taskGraphDraftV2.metadata),
          ...(nextEditorPublishState ? { editor_publish_state: nextEditorPublishState } : {}),
          domain_id: draftDomainId,
          task_family: draftFamily,
          task_id: undefined,
        },
      };
      const taskGraphPayload = buildTaskGraphUpsertPayload({
        taskGraphDraft: effectiveTaskGraphDraftV2,
        domain_id: draftDomainId,
        task_family: draftFamily,
        task_id: "",
        publish_state: nextPublished === true
          ? "published"
          : nextPublished === false
            ? "draft"
            : effectiveTaskGraphDraftV2.publish_state === "published" || effectiveTaskGraphDraftV2.publish_state === "run_bound"
              ? "published"
              : "draft",
      });
      const payload = await upsertTaskSystemTaskGraph(effectiveTaskGraphDraftV2.graph_id, taskGraphPayload);
      setTaskGraphDraftV2(effectiveTaskGraphDraftV2);
      syncTaskGraphTopology(graphNodes, graphEdges);
      setConsolePayload(payload);
      if (taskLayer === "editor") {
        setEditorTaskGraphId(effectiveTaskGraphDraftV2.graph_id);
      } else {
        setSelectedTaskGraphId(effectiveTaskGraphDraftV2.graph_id);
      }
      try {
        setTaskGraphStandardView(await getTaskSystemTaskGraphStandardView(effectiveTaskGraphDraftV2.graph_id));
        setTaskGraphStandardViewError("");
      } catch (viewExc) {
        setTaskGraphStandardView(null);
        setTaskGraphStandardViewError(viewExc instanceof Error ? viewExc.message : "标准对象视图刷新失败");
      }
      setNotice(nextPublished === true ? "任务图已发布。" : "任务图已保存。");
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
  const activeGraphNodes = taskGraphDraftV2.nodes ?? [];
  const activeGraphEdges = taskGraphDraftV2.edges ?? [];
  const updateTaskGraphPublishState = (nextState: TaskGraphPublishStateV2) => {
    setTaskGraphDraftV2((current) => ({
      ...current,
      metadata: {
        ...asRecord(current.metadata),
        editor_publish_state: nextState,
      },
      publish_state: nextState,
    }));
  };
  const updateTaskGraphDraft = (patch: Partial<TaskGraphDraftV2>) => {
    setTaskGraphDraftV2((current) => {
      const metadataPatch = asRecord(patch.metadata);
      const nextNodes = patch.nodes ? patch.nodes.map(normalizeTaskGraphNode) : current.nodes;
      const nextEdges = patch.edges ? patch.edges.map(normalizeTaskGraphEdge) : current.edges;
      const boundaries = (patch.nodes || patch.edges)
        ? inferTaskGraphBoundaryNodes(nextNodes, nextEdges, {
          fallback_entry_node_id: patch.entry_node_id ?? current.entry_node_id,
          fallback_output_node_id: patch.output_node_id ?? current.output_node_id,
        })
        : null;
      return {
        ...current,
        title: patch.title ?? current.title,
        graph_kind: patch.graph_kind ?? current.graph_kind,
        entry_node_id: patch.entry_node_id ?? boundaries?.entry_node_id ?? current.entry_node_id,
        output_node_id: patch.output_node_id ?? boundaries?.output_node_id ?? current.output_node_id,
        graph_contract_id: patch.graph_contract_id ?? current.graph_contract_id,
        nodes: nextNodes,
        edges: nextEdges,
        metadata: {
          ...asRecord(current.metadata),
          ...metadataPatch,
        },
      };
    });
  };
  const updateTaskGraphMetadata = (patch: Record<string, unknown>) => {
    setTaskGraphDraftV2((current) => ({
      ...current,
      metadata: {
        ...asRecord(current.metadata),
        ...patch,
      },
    }));
  };
  const updateTaskGraphRuntimePolicy = (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => {
    setTaskGraphDraftV2((current) => ({
      ...current,
      runtime_policy: {
        ...current.runtime_policy,
        ...patch,
      },
      metadata: {
        ...asRecord(current.metadata),
        runtime_policy: {
          ...asRecord(asRecord(current.metadata).runtime_policy),
          ...patch,
        },
      },
    }));
  };
  const selectedGraphNode = activeGraphNodes.find((node) => String(node.node_id ?? "") === selectedGraphNodeId) ?? null;
  const selectedGraphEdge = activeGraphEdges.find((edge, index) => graphEdgeId(edge, index) === selectedGraphEdgeId) ?? null;
  const boundTaskGraphTaskIds = new Set(activeGraphNodes.map((node) => graphNodeTaskId(node)).filter(Boolean));
  const graphContextDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
  const graphContextDomainTasks = taskLayer === "editor" ? editorDomainTasks : selectedDomainTasks;
  const graphContextFamily = taskGraphDraftV2.task_family || domainIdToLegacyFamily(graphContextDomain?.domain_id || taskGraphDraftV2.domain_id || "", "");
  const graphContextDomainId = graphContextDomain?.domain_id || taskGraphDraftV2.domain_id || "";
  const draftGraphSpec = deriveTaskGraphSpec(
    taskGraphDraftV2.graph_id || "",
    graphContextDomainId,
    graphContextFamily,
    activeGraphNodes,
    activeGraphEdges,
  );
  const editorGraphSpec: TaskGraphRuntimeSpec = {
    ...draftGraphSpec,
  };
  editorGraphSpec.valid = editorGraphSpec.issues.length === 0 && draftGraphSpec.valid;
  if (activeTaskGraphDetailError) {
    editorGraphSpec.issues = [
      ...editorGraphSpec.issues,
      {
        severity: "warning",
        code: "task_graph_detail_load_failed",
        message: activeTaskGraphDetailError,
      },
    ];
    editorGraphSpec.valid = false;
  }
  const editorIssueCount = editorGraphSpec.issues.length;
  const editorValid = editorGraphSpec.valid;
  const editorPublished = taskGraphDraftV2.publish_state === "published" || taskGraphDraftV2.publish_state === "run_bound";
  const topologyDirty = false;
  const eligibilityRows = [
    { label: "任务范围", value: selectedTaskDomain?.title || domainTitle(domainIdToLegacyFamily(taskDomainId(taskDraft))) },
    { label: "运行准入", value: `${displayId(executionDraft.task_level)} / ${displayId(executionDraft.task_privilege)}` },
    { label: "输出契约", value: contractLabel(taskDraft.output_contract_id || workflowDraft.output_contract_id || "", domainContractSpecs, contractCatalog) },
  ];
  const selectedTaskGraphReferences = useMemo(() => {
    const taskId = String(selectedTask?.task_id ?? "").trim();
    if (!taskId) return [];
    return allTaskGraphs
      .map((graph) => {
        const nodeRefs = (graph.nodes ?? [])
          .map((node, index) => {
            const nodeRecord = asRecord(node);
            return {
              nodeId: String(node.node_id ?? nodeRecord.id ?? `node_${index + 1}`),
              title: String(nodeRecord.title ?? nodeRecord.label ?? node.node_id ?? `节点 ${index + 1}`),
              taskId: graphNodeTaskId(node),
            };
          })
          .filter((item) => item.taskId === taskId);
        return { graph, nodeRefs };
      })
      .filter((item) => item.nodeRefs.length > 0);
  }, [allTaskGraphs, selectedTask?.task_id]);
  const runtimeBoundTaskRunId = String(taskGraphMonitorBinding?.task_run_id ?? "").trim();
  const runtimeRunsForSelectedGraph = useMemo(() => {
    const graphId = String(selectedTaskGraph?.graph_id ?? "").trim();
    if (!graphId) return runtimeTaskRuns;
    const matched = runtimeTaskRuns.filter((item) => runtimeTaskRunGraphId(item) === graphId);
    return matched.length ? matched : runtimeTaskRuns;
  }, [runtimeTaskRuns, selectedTaskGraph?.graph_id]);
  const selectedRuntimeSummary = runtimeTaskRuns.find((item) => getRuntimeTaskRunId(item) === runtimeTaskRunId.trim()) ?? null;
  const selectedRuntimeRunRecord = dictOf(selectedRuntimeSummary?.task_run);
  const runtimeMonitorForSelectedRun = runtimeTaskRunId.trim()
    && taskGraphLiveMonitor
    && recordFieldText(dictOf(taskGraphLiveMonitor.task_run), ["task_run_id", "id", "run_id"], "") === runtimeTaskRunId.trim()
    ? taskGraphLiveMonitor
    : runtimeLiveMonitor;
  const runtimeArtifactStatusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const artifact of runtimeArtifactOverview?.artifacts ?? []) {
      const status = String(artifact.status || "unknown");
      counts[status] = (counts[status] ?? 0) + 1;
    }
    return counts;
  }, [runtimeArtifactOverview?.artifacts]);
  const runtimePageActive = activeWorkspaceView === "task-system" && taskLayer === "management" && taskSystemLayer === "runtime";
  const professionalRunPageActive = activeWorkspaceView === "task-system" && taskLayer === "management" && taskSystemLayer === "professional-run";
  const resourceAuthorityPageActive = activeWorkspaceView === "task-system" && taskLayer === "management" && taskSystemLayer === "resource-authority";
  const loadRuntimeTaskRuns = useCallback(async () => {
    if (!currentSessionId) {
      setRuntimeTaskRuns([]);
      return;
    }
    try {
      const response = await listOrchestrationRuntimeLoopTaskRuns(currentSessionId);
      setRuntimeTaskRuns(response.task_runs ?? []);
    } catch (exc) {
      setRuntimeError(exc instanceof Error ? `运行实例列表加载失败：${exc.message}` : "运行实例列表加载失败");
    }
  }, [currentSessionId]);
  const loadRuntimeStores = useCallback(async () => {
    const taskRunId = runtimeTaskRunId.trim();
    setRuntimeLoading(true);
    setRuntimeError("");
    try {
      const [formal, artifacts, monitor] = await Promise.all([
        getFormalMemoryOverview({ task_run_id: taskRunId, limit: 80 }),
        getArtifactRepositoryOverview({ task_run_id: taskRunId, limit: 80 }),
        taskRunId ? getOrchestrationRuntimeLoopTaskRunLiveMonitor(taskRunId).catch(() => null) : Promise.resolve(null),
      ]);
      setRuntimeFormalOverview(formal);
      setRuntimeArtifactOverview(artifacts);
      setRuntimeLiveMonitor(monitor);
    } catch (exc) {
      setRuntimeError(exc instanceof Error ? exc.message : "运行库加载失败");
    } finally {
      setRuntimeLoading(false);
    }
  }, [runtimeTaskRunId]);
  const loadRuntimeResourceInventory = useCallback(async () => {
    try {
      setRuntimeResourceInventory(await getOrchestrationResourceInventory());
    } catch (exc) {
      setRuntimeError(exc instanceof Error ? `资源权威地图加载失败：${exc.message}` : "资源权威地图加载失败");
    }
  }, []);
  const refreshRuntimeManagement = useCallback(async () => {
    await Promise.all([
      loadRuntimeTaskRuns(),
      loadRuntimeStores(),
    ]);
  }, [loadRuntimeStores, loadRuntimeTaskRuns]);
  const refreshProfessionalRun = useCallback(async () => {
    await Promise.all([
      loadRuntimeTaskRuns(),
      loadRuntimeStores(),
    ]);
  }, [loadRuntimeStores, loadRuntimeTaskRuns]);
  const refreshResourceAuthority = useCallback(async () => {
    setRuntimeLoading(true);
    setRuntimeError("");
    try {
      await loadRuntimeResourceInventory();
    } finally {
      setRuntimeLoading(false);
    }
  }, [loadRuntimeResourceInventory]);

  useEffect(() => {
    if (!runtimePageActive && !professionalRunPageActive) return;
    void loadRuntimeTaskRuns();
  }, [loadRuntimeTaskRuns, professionalRunPageActive, runtimePageActive]);

  useEffect(() => {
    if ((!runtimePageActive && !professionalRunPageActive) || runtimeDefaultedRef.current || runtimeTaskRunId.trim()) return;
    const nextTaskRunId = runtimeBoundTaskRunId
      || getRuntimeTaskRunId(runtimeRunsForSelectedGraph[0])
      || getRuntimeTaskRunId(runtimeTaskRuns[0]);
    if (!nextTaskRunId) return;
    runtimeDefaultedRef.current = true;
    setRuntimeTaskRunId(nextTaskRunId);
  }, [professionalRunPageActive, runtimeBoundTaskRunId, runtimePageActive, runtimeRunsForSelectedGraph, runtimeTaskRunId, runtimeTaskRuns]);

  useEffect(() => {
    if (!runtimePageActive && !professionalRunPageActive) return;
    void loadRuntimeStores();
  }, [loadRuntimeStores, professionalRunPageActive, runtimePageActive]);

  useEffect(() => {
    if (!resourceAuthorityPageActive) return;
    void refreshResourceAuthority();
  }, [refreshResourceAuthority, resourceAuthorityPageActive]);

  const taskSystemLayerItems: Array<LayerNavItem<TaskSystemLayer>> = [
    {
      value: "domains",
      label: "任务域",
      meta: selectedDomain?.title || `${visibleDomains.length} 个任务域`,
      detail: "分类与入口",
    },
    {
      value: "tasks",
      label: "任务定义",
      meta: selectedTask?.task_title || `${selectedDomainTasks.length} 个任务`,
      detail: "可执行任务",
    },
    {
      value: "graphs",
      label: "任务图",
      meta: `${taskGraphs.length} 张图`,
      detail: "多 Agent 流程",
    },
    {
      value: "contracts",
      label: "契约库",
      meta: `${domainContractSpecs.length} 个契约`,
      detail: "输入输出边界",
    },
    {
      value: "resource-authority",
      label: "资源权威",
      meta: `${runtimeResourceInventory?.items?.length ?? 0} 层资源`,
      detail: "资源归属",
    },
    {
      value: "professional-run",
      label: "专业运行",
      meta: runtimeTaskRunId.trim() || "未选择 TaskRun",
      detail: "长任务会话",
    },
    {
      value: "orchestration",
      label: "编排资源",
      meta: `${orchestrationAgentCatalog?.agents?.length ?? 0} Agent / ${projectionCards.length} Projection`,
      detail: "Agent 与 Projection",
    },
    {
      value: "runtime",
      label: "运行管理",
      meta: activeTaskGraph?.graph_id || "未绑定运行",
      detail: "监控与产物",
    },
  ];
  const primaryTaskSystemLayerItems = taskSystemLayerItems.filter((item) => ["domains", "tasks", "graphs"].includes(item.value));
  const supportingTaskSystemLayerItems = taskSystemLayerItems.filter((item) => ["contracts", "resource-authority", "professional-run", "orchestration", "runtime"].includes(item.value));
  const taskConfigPanelItems: Array<LayerNavItem<TaskConfigPanel>> = [
    {
      value: "definition",
      label: "基础定义",
      meta: selectedTask ? (taskDraft.task_title || selectedTask.task_title) : "未选择任务",
      detail: "任务身份、输入输出、Workflow、投影与执行策略",
    },
  ];
  const taskDetailPanelItems = taskConfigPanelItems;
  const contractPanelItems: Array<LayerNavItem<ContractPanel>> = [
    {
      value: "library",
      label: "契约库",
      meta: `${domainContractSpecs.length} 个契约`,
      detail: "管理可被任务图、节点和边引用的契约主数据",
    },
    {
      value: "templates",
      label: "契约模板",
      meta: "域级模板",
      detail: "模板只作为契约草案入口，按任务域隔离管理",
    },
  ];
  const domainContextSlot = (
    <div className="task-system-project-selector">
      <div>
        <span>项目</span>
        <strong>{selectedDomain?.title || "未选择任务域"}</strong>
      </div>
      <TaskGraphChromeSelect
        emptyLabel="暂无任务域"
        label="任务域"
        onChange={(domainId) => {
          const domain = visibleDomains.find((item) => item.domain_id === domainId);
          setSelectedDomainId(domainId);
          setEditorDomainId(domainId);
          setSelectedTaskId(domain?.tasks[0]?.task_id || "");
          const nextGraphs = sortTaskGraphsForWorkbench((consolePayload?.task_graph_management?.task_graphs ?? []).filter((item) => String(item.domain_id ?? "").trim() === domainId));
          setSelectedTaskGraphId(recommendedTaskGraphId(nextGraphs));
          setEditingDomainName(false);
        }}
        options={visibleDomains.map((domain) => ({ value: domain.domain_id, label: domain.title }))}
        placeholder="选择任务域"
        value={selectedDomain?.domain_id || ""}
      />
      <small>{selectedDomain?.domain_id || "未选择任务域"}</small>
      <ToolbarButton onClick={createDomainDraft}><Plus size={15} />新项目</ToolbarButton>
    </div>
  );
  const managementLayerSlot = (
    <div className="task-system-object-table" aria-label="任务系统对象目录">
      <div className="task-system-object-table__head" aria-hidden="true">
        <span>对象</span>
        <span>当前记录</span>
        <span>状态</span>
      </div>
      {[...primaryTaskSystemLayerItems, ...supportingTaskSystemLayerItems].map((item) => {
        const active = taskSystemLayer === item.value;
        const scope = primaryTaskSystemLayerItems.some((entry) => entry.value === item.value) ? "主对象" : "支撑对象";
        return (
          <button
            aria-current={active ? "page" : undefined}
            className={active ? "task-system-object-row task-system-object-row--active" : "task-system-object-row"}
            key={item.value}
            onClick={() => selectTaskSystemLayer(item.value)}
            type="button"
          >
            <strong><span className="task-system-object-row__scope">{scope}</span>{item.label}</strong>
            <span className="task-system-object-row__meta">{item.meta}</span>
            <em>{active ? "当前" : "可配置"}</em>
          </button>
        );
      })}
    </div>
  );
  function openTaskGraphEditor(graphId = selectedTaskGraph?.graph_id || "") {
    const nextDomain = selectedDomain ?? editorDomain;
    const nextDomainId = nextDomain?.domain_id || "";
    const domainGraphs = sortTaskGraphsForWorkbench(allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === nextDomainId));
    const nextGraph = allTaskGraphs.find((item) => String(item.graph_id ?? "") === graphId)
      ?? domainGraphs.find((item) => item.graph_id === recommendedTaskGraphId(domainGraphs))
      ?? null;
    setEditorDomainId(nextDomain?.domain_id || "");
    setEditorTaskGraphId(nextGraph?.graph_id || "");
    setSelectedTaskGraphId(nextGraph?.graph_id || graphId || "");
    setSelectedGraphNodeId("");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
    setTaskLayer("editor");
    setTaskSystemLayer("graphs");
  }

  function enterManagementLayer() {
    setTaskLayer("management");
  }

  function selectTaskSystemLayer(layer: TaskSystemLayer) {
    setTaskSystemLayer(layer);
    setTaskLayer("management");
    if (layer === "tasks") {
      setTaskConfigPanel("definition");
    }
  }

  function selectEditorDomain(domainId: string) {
    const nextDomain = visibleDomains.find((domain) => domain.domain_id === domainId) ?? null;
    const nextDomainId = nextDomain?.domain_id || "";
    const domainGraphs = sortTaskGraphsForWorkbench(allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === nextDomainId));
    const nextGraph = domainGraphs.find((item) => item.graph_id === recommendedTaskGraphId(domainGraphs)) ?? null;
    setEditorDomainId(nextDomain?.domain_id || "");
    setEditorTaskGraphId(nextGraph?.graph_id || "");
    setSelectedGraphNodeId("");
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }

  const editorWorkspaceSlot = (
    <>
      <div className="task-graph-editor-chrome__controls">
        <TaskGraphChromeSelect
          emptyLabel={visibleDomains.length ? "选择任务域" : "暂无任务域"}
          label="任务域"
          onChange={selectEditorDomain}
          options={visibleDomains.map((domain) => ({ value: domain.domain_id, label: domain.title }))}
          placeholder="选择任务域"
          value={editorDomainId}
        />
        <TaskGraphChromeSelect
          disabled={!editorDomain}
          emptyLabel={!editorDomain ? "先选择任务域" : editorGraphSelectOptions.length ? "选择图草稿" : "当前任务域暂无图"}
          label="图草稿"
          onChange={(nextValue) => {
            setEditorTaskGraphId(nextValue);
            setSelectedTaskGraphId(nextValue);
            setSelectedGraphNodeId("");
            setSelectedGraphEdgeId("");
            setLinkingFromNodeId("");
          }}
          options={editorGraphSelectOptions}
          placeholder="选择图草稿"
          value={editorTaskGraphId}
        />
      </div>
      <div className="task-graph-editor-chrome__status task-graph-editor-chrome__status--context">
        <span className={topologyDirty ? "boundary-status boundary-status--warn" : "boundary-status"}>{topologyDirty ? "拓扑未同步" : "拓扑已同步"}</span>
        <span className="boundary-status">{editorDomain?.title || "未选择任务域"}</span>
      </div>
      <div className="task-graph-editor-chrome__actions task-graph-editor-chrome__actions--minimal">
        <ToolbarButton onClick={() => selectTaskSystemLayer("graphs")}>返回任务图库</ToolbarButton>
        <ToolbarButton disabled={saving === "task-graph-create"} onClick={() => void createTaskGraphDraft()}><Network size={15} />新图草稿</ToolbarButton>
      </div>
    </>
  );

  const taskGraphEditorWorkbench = (
    <TaskGraphWorkbench
      addTaskGraphNode={addTaskGraphNode}
      addTaskGraphRoleNode={addTaskGraphRoleNode}
      addTaskGraphSuccessorNode={addTaskGraphSuccessorNode}
      addTaskGraphTaskNode={addTaskGraphTaskNode}
      a2aCatalog={a2aCatalog}
      agentGroupOptions={editorAgentGroupOptions}
      applyTaskGraphTemplate={applyTaskGraphTemplate}
      boundTaskGraphTaskIds={boundTaskGraphTaskIds}
      contractSpecs={editorContractSpecs}
      taskGraphs={editorTaskGraphs}
      domainTaskOptions={editorDomainTaskOptions}
      duplicateTaskGraphDraft={duplicateTaskGraphDraft}
      editorIssueCount={editorIssueCount}
      editorPublished={editorPublished}
      editorValid={editorValid}
      activeGraphEdges={activeGraphEdges}
      activeGraphNodes={activeGraphNodes}
      handleTopologyNodeClick={handleTopologyNodeClick}
      linkingFromNodeId={linkingFromNodeId}
      removeTaskGraphEdge={removeTaskGraphEdge}
      removeTaskGraphNode={removeTaskGraphNode}
      reverseTaskGraphEdge={reverseTaskGraphEdge}
      saveTaskGraphStack={saveTaskGraphStack}
      saving={saving}
      selectedTaskGraph={editorSelectedTaskGraph}
      selectedTaskGraphId={editorTaskGraphId}
      selectedDomain={editorDomain}
      selectedDomainTasks={editorDomainTasks}
      selectedGraphEdge={selectedGraphEdge}
      selectedGraphEdgeId={selectedGraphEdgeId}
      selectedGraphNode={selectedGraphNode}
      selectedGraphNodeId={selectedGraphNodeId}
      setLinkingFromNodeId={setLinkingFromNodeId}
      setSelectedTaskGraphId={setEditorTaskGraphId}
      setSelectedGraphEdgeId={setSelectedGraphEdgeId}
      setSelectedGraphNodeId={setSelectedGraphNodeId}
      taskGraphDirty={topologyDirty}
      taskGraphDraftV2={taskGraphDraftV2}
      workspaceSlot={editorWorkspaceSlot}
      taskGraphStandardView={taskGraphStandardView}
      taskGraphStandardViewError={taskGraphStandardViewError}
      taskGraphStandardViewLoading={taskGraphStandardViewLoading}
      refreshTaskGraphStandardView={refreshTaskGraphStandardView}
      updateTaskGraphDraft={updateTaskGraphDraft}
      updateTaskGraphEdge={updateTaskGraphEdge}
      updateTaskGraphMetadata={updateTaskGraphMetadata}
      updateTaskGraphNode={updateTaskGraphNode}
      updateTaskGraphPublishState={updateTaskGraphPublishState}
      updateTaskGraphRuntimePolicy={updateTaskGraphRuntimePolicy}
      orchestrationAgentCatalog={orchestrationAgentCatalog}
      onCreateProjectionFromPrompt={createProjectionFromNodePrompt}
      projectionCards={domainProjectionCards}
    />
  );

  if (taskLayer === "editor") {
    return (
      <section className="workspace-view task-graph-editor-page" aria-label="任务图编辑器">
        {error ? <div className="boundary-notice boundary-notice--error">{error}</div> : null}
        {notice ? <div className="boundary-notice">{notice}</div> : null}
        {taskGraphEditorWorkbench}
      </section>
    );
  }

  return (
    <TaskSystemShell
      activeLayer={taskSystemLayer}
      error={error}
      contextSlot={domainContextSlot}
      layerSlot={managementLayerSlot}
      mode="management"
      navItems={taskSystemLayerItems}
      notice={notice}
      onBackToGraphs={() => selectTaskSystemLayer("graphs")}
      onRefresh={() => void load()}
      onSelectLayer={(layer) => {
        void load();
        selectTaskSystemLayer(layer);
      }}
      path={selectedDomain?.title || "请选择任务域"}
      title="任务系统"
    >

      <section className={`task-management-stage task-management-stage--${taskSystemLayer}`}>
          {taskSystemLayer === "domains" ? (
            <TaskDomainLibraryPage
              contractCount={domainContractSpecs.length}
              domainDraft={domainDraft}
              editingDomainName={editingDomainName}
              entryDraft={entryDraft}
              graphCount={taskGraphs.length}
              loading={loading}
              onDeleteDomain={() => selectedDomain ? void deleteDomain(selectedDomain) : undefined}
              onSaveDomain={() => void saveDomain()}
              onSaveEntry={() => void saveEntry()}
              onSelectLayer={selectTaskSystemLayer}
              onSetDomainDraft={setDomainDraft}
              onSetEditingDomainName={setEditingDomainName}
              onSetEntryDraft={setEntryDraft}
              projectionCount={domainProjectionCards.length}
              projectionLoading={projectionLoading}
              saving={saving}
              selectedDomain={selectedDomain}
              workflowOptions={workflowOptions}
            />
          ) : null}

          {taskSystemLayer === "tasks" ? (
            <TaskDefinitionLibraryPage
              artifactPolicyDraft={artifactPolicyDraft}
              commonContractOptions={commonContractOptions}
              contractCatalog={contractCatalog}
              domainContractSpecs={domainContractSpecs}
              eligibilityRows={eligibilityRows}
              onCreateTask={() => void createTaskDraft()}
              onDeleteTask={() => selectedTask ? void deleteTaskRecord(selectedTask) : undefined}
              onOpenTaskGraph={openTaskGraphEditor}
              onSaveTask={() => void saveTaskStack()}
              onSelectTask={setSelectedTaskId}
              onSendTaskToChat={() => selectedTask ? sendTaskToChat(selectedTask, selectedTaskDomain) : undefined}
              onSetArtifactPolicyDraft={setArtifactPolicyDraft}
              onSetTaskConfigPanel={setTaskConfigPanel}
              onSetTaskDraft={setTaskDraft}
              onSetTaskPolicyText={setTaskPolicyText}
              saving={saving}
              selectedDomain={selectedDomain}
              selectedTask={selectedTask}
              selectedTaskGraphReferences={selectedTaskGraphReferences}
              selectedTaskId={selectedTaskId}
              taskConfigPanel={taskConfigPanel}
              taskDetailPanelItems={taskDetailPanelItems}
              taskDraft={taskDraft}
              taskFlowDefinitions={taskFlowDefinitions}
              taskPolicyError={taskPolicyError}
              taskPolicyText={taskPolicyText}
              tasks={selectedDomainTasks}
              workflowOptions={workflowOptions}
            />
          ) : null}

          {taskSystemLayer === "contracts" ? (
            <TaskContractLibraryPage
              contractManagement={contractManagement}
              contractPanel={contractPanel}
              contractPanelItems={contractPanelItems}
              domainContractSpecs={domainContractSpecs}
              onDeleteContract={removeContractSpec}
              onOpenWorkbench={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}
              onSaveContract={saveContractSpec}
              onSelectPanel={setContractPanel}
              saving={saving}
              selectedTaskGraphId={selectedTaskGraph?.graph_id}
            />
          ) : null}

          {taskSystemLayer === "graphs" ? (
            <TaskGraphLibraryPage
              activeGraphEdges={activeGraphEdges}
              activeGraphNodes={activeGraphNodes}
              editorIssueCount={editorIssueCount}
              editorPublished={editorPublished}
              editorValid={editorValid}
              onCreateGraph={() => void createTaskGraphDraft()}
              onDuplicateGraph={() => void duplicateTaskGraphDraft()}
              onOpenWorkbench={openTaskGraphEditor}
              onSaveGraph={() => void saveTaskGraphStack(false)}
              onSelectGraph={setSelectedTaskGraphId}
              saving={saving}
              selectedDomain={selectedDomain}
              selectedTaskGraph={selectedTaskGraph}
              selectedTaskGraphId={selectedTaskGraphId}
              standardViewError={taskGraphStandardViewError}
              taskGraphDraft={taskGraphDraftV2}
              taskGraphs={taskGraphs}
            />
          ) : null}

          {taskSystemLayer === "orchestration" ? (
            <TaskOrchestrationResourceLibraryPage
              onOpenOrchestration={openOrchestrationControl}
              onOpenWorkbench={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}
              orchestrationAgentCatalog={orchestrationAgentCatalog}
              projectionCards={projectionCards}
              selectedTaskGraphId={selectedTaskGraph?.graph_id}
            />
          ) : null}

          {taskSystemLayer === "resource-authority" ? (
            <ResourceAuthorityMapPage
              inventory={runtimeResourceInventory}
              loading={runtimeLoading}
              onRefresh={() => void refreshResourceAuthority()}
              selectedTaskGraphId={selectedTaskGraph?.graph_id}
            />
          ) : null}

          {taskSystemLayer === "professional-run" ? (
            <ProfessionalRunSessionPage
              monitorForSelectedRun={runtimeMonitorForSelectedRun || null}
              onRefresh={() => void refreshProfessionalRun()}
              onTaskRunIdChange={(taskRunId) => {
                runtimeDefaultedRef.current = true;
                setRuntimeTaskRunId(taskRunId);
              }}
              runtimeLoading={runtimeLoading}
              runtimeRunsForSelectedGraph={runtimeRunsForSelectedGraph}
              runtimeTaskRunId={runtimeTaskRunId}
              selectedRuntimeSummary={selectedRuntimeSummary}
            />
          ) : null}

          {taskSystemLayer === "runtime" ? (
            <TaskRuntimeLibraryPage
              artifactOverview={runtimeArtifactOverview}
              artifactStatusCounts={runtimeArtifactStatusCounts}
              formalOverview={runtimeFormalOverview}
              monitorForSelectedRun={runtimeMonitorForSelectedRun || null}
              onOpenMonitor={() => setTaskGraphRunInteractionOpen(true)}
              onOpenWorkbench={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}
              onRefresh={() => void refreshRuntimeManagement()}
              onTaskRunIdChange={(taskRunId) => {
                runtimeDefaultedRef.current = true;
                setRuntimeTaskRunId(taskRunId);
              }}
              runtimeBoundTaskRunId={runtimeBoundTaskRunId}
              runtimeError={runtimeError}
              runtimeLoading={runtimeLoading}
              runtimeRunsForSelectedGraph={runtimeRunsForSelectedGraph}
              runtimeTaskRunId={runtimeTaskRunId}
              selectedDomain={selectedDomain}
              selectedRuntimeRunRecord={selectedRuntimeRunRecord}
              selectedRuntimeSummary={selectedRuntimeSummary}
              selectedTaskGraph={selectedTaskGraph}
              taskGraphDraft={taskGraphDraftV2}
            />
          ) : null}
      </section>
    </TaskSystemShell>
  );
}








