"use client";

import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Database,
  FileStack,
  Loader2,
  Monitor,
  Network,
  Plus,
  RefreshCw,
  Save,
  Send,
  Pencil,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ContractLibraryPanel, contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import { ContractOverviewPanel } from "@/components/workspace/views/task-system/ContractOverviewPanel";
import { TaskContractPanel } from "@/components/workspace/views/task-system/TaskContractPanel";
import { TaskAssemblyPreflightPanel } from "@/components/workspace/views/task-system/TaskAssemblyPreflightPanel";
import { TaskGraphWorkbench } from "@/components/workspace/views/task-system/TaskGraphWorkbench";
import {
  TaskDefinitionPage,
  TaskContractManagementPage,
  TaskDomainManagementPage,
  TaskGraphManagementPage,
  TaskOrchestrationResourcePage,
  TaskRuntimeManagementPage,
} from "@/components/workspace/views/task-system/TaskSystemPages";
import { TaskSystemShell } from "@/components/workspace/views/task-system/TaskSystemShell";
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
  buildTaskGraphResourceStandardModel,
  buildTaskGraphTimelineStandardModel,
} from "@/components/workspace/views/task-system/taskGraphStandardView";
import { buildTaskGraphTemplateDraft, type TaskGraphTemplateId } from "@/components/workspace/views/task-system/taskGraphTemplates";
import {
  graphEdgeId,
  graphEdgeSource,
  graphEdgeTarget,
  graphNodeTaskId,
} from "@/components/workspace/views/task-system/taskGraphTopologyUtils";
import {
  TaskGraphChromeSelect,
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
  getArtifactRepositoryOverview,
  getFormalMemoryOverview,
  getOrchestrationAgents,
  getOrchestrationRuntimeLoopTaskRunLiveMonitor,
  listOrchestrationRuntimeLoopTaskRuns,
  getSoulProjectionCards,
  compileTaskSystemTaskGraphRuntimeSpec,
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
import { useAppStore } from "@/lib/store";

type TaskLayer = "management" | "editor";
type TaskSystemLayer = "domains" | "tasks" | "graphs" | "contracts" | "orchestration" | "runtime";
type TaskConfigPanel = "definition";
type ContractPanel = "library" | "templates" | "bindings" | "manifest";

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

function formatRuntimeTime(value: unknown) {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "-";
  }
  const millis = numeric > 1_000_000_000_000 ? numeric : numeric * 1000;
  return new Date(millis).toLocaleString();
}

function statusBadgeClass(status: string) {
  const normalized = status.toLowerCase();
  if (["completed", "committed", "pass", "passed", "ok", "success"].includes(normalized)) return "boundary-badge boundary-badge--ok";
  if (["failed", "error", "rejected", "stale"].includes(normalized)) return "boundary-badge boundary-badge--danger";
  if (["running", "active", "pending", "staging", "warning"].includes(normalized)) return "boundary-badge boundary-badge--warn";
  return "boundary-badge";
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

const DEFAULT_PROJECTION_POLICY_CHOICES = ["workflow_compatible_or_task_default", "task_default"];
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

function taskDomainId(task: SpecificTaskRecord) {
  const metadata = dictOf(task.metadata);
  return String(metadata.domain_id ?? "").trim() || `domain.${task.task_family || "general"}`;
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
  const [activeTaskGraphRuntimeSpec, setActiveTaskGraphRuntimeSpec] = useState<TaskGraphRuntimeSpec | null>(null);
  const [activeTaskGraphRuntimeSpecError, setActiveTaskGraphRuntimeSpecError] = useState("");
  const [runtimeTaskRunId, setRuntimeTaskRunId] = useState("");
  const [runtimeTaskRuns, setRuntimeTaskRuns] = useState<RuntimeLoopTaskRunSummary[]>([]);
  const [runtimeFormalOverview, setRuntimeFormalOverview] = useState<FormalMemoryOverview | null>(null);
  const [runtimeArtifactOverview, setRuntimeArtifactOverview] = useState<ArtifactRepositoryOverview | null>(null);
  const [runtimeLiveMonitor, setRuntimeLiveMonitor] = useState<RuntimeLoopTaskRunLiveMonitor | null>(null);
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
    const firstDomainWithTasks = nextDomains.find((item) => item.tasks.length > 0) ?? null;
    const fallbackDomain = firstDomainWithTasks ?? nextDomains[0] ?? null;
    const preferredDomain = nextDomains.find((item) => item.domain_id === selectedDomainIdRef.current) ?? null;
    const selectedDomain = preferredDomain && (preferredDomain.tasks.length > 0 || !firstDomainWithTasks)
      ? preferredDomain
      : fallbackDomain;
    const taskGraphs = overview.task_graph_management?.task_graphs ?? [];
    setSelectedDomainId(selectedDomain?.domain_id ?? "");
    setSelectedTaskId((current) => current || selectedDomain?.tasks[0]?.task_id || overview.task_management.specific_task_records[0]?.task_id || "");
    setEditorDomainId((current) => current || selectedDomain?.domain_id || "");
    setSelectedTaskGraphId((current) => current || taskGraphs[0]?.graph_id || "");
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
  const allTaskGraphs = useMemo(() => consolePayload?.task_graph_management?.task_graphs ?? [], [consolePayload]);
  const allTaskGraphSpecs = useMemo(
    () => consolePayload?.task_graph_management?.task_graph_specs ?? [],
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
    () => activeDomainId ? allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === activeDomainId) : [],
    [activeDomainId, allTaskGraphs],
  );
  const selectedTaskGraph = taskGraphs.find((item) => item.graph_id === selectedTaskGraphId) ?? taskGraphs[0] ?? null;
  const editorDomain = visibleDomains.find((domain) => domain.domain_id === editorDomainId) ?? visibleDomains[0] ?? null;
  const editorDomainTasks = useMemo(() => editorDomain?.tasks ?? [], [editorDomain]);
  const editorDomainFilterId = editorDomain?.domain_id || "";
  const editorContractSpecs = useMemo(() => scopedContractSpecs(contractSpecs, editorDomain), [contractSpecs, editorDomain]);
  const editorTaskGraphs = useMemo(
    () => editorDomainFilterId ? allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === editorDomainFilterId) : [],
    [allTaskGraphs, editorDomainFilterId],
  );
  const editorGraphSelectOptions = useMemo(() => {
    const options = editorTaskGraphs.map((task) => ({ value: task.graph_id, label: task.title }));
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
  const activeTaskGraphSpec = activeTaskGraphRuntimeSpec ?? allTaskGraphSpecs.find((item) => item.graph_id === activeTaskGraph?.graph_id) ?? null;
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
  const activeTaskGraphResourceModel = useMemo(
    () => buildTaskGraphResourceStandardModel(taskGraphStandardView),
    [taskGraphStandardView],
  );
  const activeTaskGraphTimelineModel = useMemo(
    () => buildTaskGraphTimelineStandardModel(taskGraphStandardView),
    [taskGraphStandardView],
  );

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
      setActiveTaskGraphRuntimeSpec(null);
      setActiveTaskGraphRuntimeSpecError("");
      return;
    }
    void refreshTaskGraphStandardView();
  }, [activeTaskGraphId, activeWorkspaceView, refreshTaskGraphStandardView]);

  useEffect(() => {
    if (activeWorkspaceView !== "task-system") return;
    if (!activeTaskGraphId) {
      setActiveTaskGraphRuntimeSpec(null);
      setActiveTaskGraphRuntimeSpecError("");
      return;
    }
    let cancelled = false;
    setActiveTaskGraphRuntimeSpecError("");
    void compileTaskSystemTaskGraphRuntimeSpec(activeTaskGraphId)
      .then((payload) => {
        if (!cancelled) setActiveTaskGraphRuntimeSpec(payload);
      })
      .catch((exc) => {
        if (!cancelled) {
          setActiveTaskGraphRuntimeSpec(null);
          setActiveTaskGraphRuntimeSpecError(exc instanceof Error ? exc.message : "任务图运行规格加载失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeTaskGraphId, activeWorkspaceView]);
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
    setTaskSelection({
      coordination_task_id: graph.graph_id,
      domain_id: domain?.domain_id || graph.domain_id || "",
      label: graph.title,
      mode: "coordination",
    });
    setWorkspaceView("chat");
    setNotice(`已将任务图“${graph.title}”带入主会话。`);
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
      usage_summary: "由 TaskGraph Studio 节点职责生成的静态投影，用于运行装配时绑定节点 Prompt。",
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
      setSelectedTaskGraphId(taskGraphs[0]?.graph_id || "");
    }
  }, [taskGraphs, selectedTaskGraphId]);

  useEffect(() => {
    if (!editorTaskGraphs.some((item) => item.graph_id === editorTaskGraphId)) {
      if (editorTaskGraphId && editorTaskGraphId === taskGraphDraftV2.graph_id) {
        return;
      }
      setEditorTaskGraphId(editorTaskGraphs[0]?.graph_id || "");
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

  function updateDomainTitle(title: string) {
    setDomainDraft((value) => ({ ...value, title }));
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

  function applyTaskGraphTemplate(template: TaskGraphTemplateId, options: Partial<Parameters<typeof buildTaskGraphTemplateDraft>[0]> = {}) {
    const shouldReplace = !(taskGraphDraftV2.nodes?.length || taskGraphDraftV2.edges?.length)
      || window.confirm("应用图模板会替换当前未保存的拓扑草稿，确认继续吗？");
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
    ...(activeTaskGraphSpec ?? draftGraphSpec),
    ...draftGraphSpec,
    issues: [
      ...draftGraphSpec.issues,
      ...((activeTaskGraphSpec?.issues ?? []).filter((issue) => {
        const code = String(issue.code ?? "");
        return code && !draftGraphSpec.issues.some((draftIssue) => String(draftIssue.code ?? "") === code);
      })),
    ],
  };
  editorGraphSpec.valid = editorGraphSpec.issues.length === 0 && draftGraphSpec.valid;
  if (activeTaskGraphRuntimeSpecError) {
    editorGraphSpec.issues = [
      ...editorGraphSpec.issues,
      {
        severity: "warning",
        code: "runtime_spec_load_failed",
        message: activeTaskGraphRuntimeSpecError,
      },
    ];
    editorGraphSpec.valid = false;
  }
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
  const orchestrationAgents = orchestrationAgentCatalog?.agents ?? [];
  const orchestrationProfiles = orchestrationAgentCatalog?.profiles ?? [];
  const orchestrationAgentById = new Map(orchestrationAgents.map((agent) => [String(agent.agent_id ?? ""), agent]));
  const graphNodeAssemblyRows = activeGraphNodes.map((node, index) => {
    const nodeId = String(node.node_id ?? `node_${index}`);
    const agentId = String(node.agent_id ?? "").trim();
    const agent = orchestrationAgentById.get(agentId);
    const runtimeProfile =
      orchestrationProfiles.find((profile) => String(profile.agent_id ?? "") === agentId)
      ?? (agent?.runtime_profile as Partial<(typeof orchestrationProfiles)[number]> | undefined);
    const profileId = String(runtimeProfile?.agent_profile_id ?? "").trim();
    const memoryScopes = Array.isArray(runtimeProfile?.allowed_memory_scopes) ? runtimeProfile.allowed_memory_scopes : [];
    const contextSections = Array.isArray(runtimeProfile?.allowed_context_sections) ? runtimeProfile.allowed_context_sections : [];
    const projectionId = String(node.projection_id ?? node.projection_overlay_id ?? "").trim();
    return {
      agentId,
      agentLabel: String(agent?.display_name ?? agent?.agent_name ?? (agentId || "未绑定 Agent")),
      contextSummary: contextSections.length ? contextSections.map((item) => displayId(item)).join(" / ") : "未配置上下文段",
      memorySummary: memoryScopes.length ? memoryScopes.map((item) => displayId(item)).join(" / ") : "未配置可接收记忆范围",
      node,
      nodeId,
      profileId,
      projectionId,
      projectionLabel: projectionId ? projectionLabel(projectionId, projectionCards) : "未绑定 Projection",
      ready: Boolean(agentId && profileId && contextSections.length),
    };
  });
  const graphResourceEdges = activeGraphEdges.filter((edge) => {
    const edgeType = String(edge.edge_type ?? edge.a2a_message_type ?? "");
    return [
      "memory_read",
      "memory_write_candidate",
      "memory_commit",
      "artifact_context",
      "artifact_write_candidate",
      "artifact_commit",
    ].includes(edgeType);
  });
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
  const refreshRuntimeManagement = useCallback(async () => {
    await Promise.all([
      loadRuntimeTaskRuns(),
      loadRuntimeStores(),
    ]);
  }, [loadRuntimeStores, loadRuntimeTaskRuns]);

  useEffect(() => {
    if (!runtimePageActive) return;
    void loadRuntimeTaskRuns();
  }, [loadRuntimeTaskRuns, runtimePageActive]);

  useEffect(() => {
    if (!runtimePageActive || runtimeDefaultedRef.current || runtimeTaskRunId.trim()) return;
    const nextTaskRunId = runtimeBoundTaskRunId
      || getRuntimeTaskRunId(runtimeRunsForSelectedGraph[0])
      || getRuntimeTaskRunId(runtimeTaskRuns[0]);
    if (!nextTaskRunId) return;
    runtimeDefaultedRef.current = true;
    setRuntimeTaskRunId(nextTaskRunId);
  }, [runtimeBoundTaskRunId, runtimePageActive, runtimeRunsForSelectedGraph, runtimeTaskRunId, runtimeTaskRuns]);

  useEffect(() => {
    if (!runtimePageActive) return;
    void loadRuntimeStores();
  }, [loadRuntimeStores, runtimePageActive]);

  const taskSystemLayerItems: Array<LayerNavItem<TaskSystemLayer>> = [
    {
      value: "domains",
      label: "任务域",
      meta: selectedDomain?.title || "未选择任务域",
      detail: "管理任务分类、入口策略和域级边界",
    },
    {
      value: "tasks",
      label: "任务定义库",
      meta: selectedTask?.task_title || "未选择任务",
      detail: "管理可被单独执行或被图节点引用的具体任务定义",
    },
    {
      value: "graphs",
      label: "任务图库",
      meta: `${taskGraphs.length} 张图`,
      detail: "管理任务域下的一等 TaskGraph 编排对象",
    },
    {
      value: "contracts",
      label: "契约库",
      meta: `${domainContractSpecs.length} 个契约`,
      detail: "管理任务域下的节点契约、边载荷契约和质量门模板",
    },
    {
      value: "orchestration",
      label: "编排资源",
      meta: `${orchestrationAgentCatalog?.agents?.length ?? 0} Agent / ${projectionCards.length} Projection`,
      detail: "Agent、运行档案、Projection",
    },
    {
      value: "runtime",
      label: "运行管理",
      meta: activeTaskGraph?.graph_id || "未绑定运行",
      detail: "task_run、监控、记忆与产物",
    },
  ];
  const primaryTaskSystemLayerItems = taskSystemLayerItems.filter((item) => ["domains", "tasks", "graphs"].includes(item.value));
  const supportingTaskSystemLayerItems = taskSystemLayerItems.filter((item) => ["contracts", "orchestration", "runtime"].includes(item.value));
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
      detail: "管理契约主数据、字段、通信与治理策略",
    },
    {
      value: "templates",
      label: "契约模板",
      meta: "域级模板",
      detail: "模板只作为契约草案入口，按任务域隔离管理",
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
  const domainContextSlot = (
    <>
      <div className="task-system-domain-context__identity">
        <span>当前任务域</span>
        <TaskGraphChromeSelect
          emptyLabel="暂无任务域"
          label="任务域"
          onChange={(domainId) => {
            const domain = visibleDomains.find((item) => item.domain_id === domainId);
            setSelectedDomainId(domainId);
            setEditorDomainId(domainId);
            setSelectedTaskId(domain?.tasks[0]?.task_id || "");
            const nextGraph = (consolePayload?.task_graph_management?.task_graphs ?? []).find((item) => String(item.domain_id ?? "").trim() === domainId);
            setSelectedTaskGraphId(nextGraph?.graph_id || "");
            setEditingDomainName(false);
          }}
          options={visibleDomains.map((domain) => ({ value: domain.domain_id, label: domain.title }))}
          placeholder="选择任务域"
          value={selectedDomain?.domain_id || ""}
        />
        <small>{selectedDomain?.domain_id || "未选择任务域"}</small>
      </div>
      <div className="task-system-domain-context__metrics">
        <ReadinessCard label="具体任务" value={`${selectedDomainTasks.length}`} ready={selectedDomainTasks.length > 0} />
        <ReadinessCard label="任务图" value={`${taskGraphs.length}`} ready={taskGraphs.length > 0} />
        <ReadinessCard label="契约" value={`${domainContractSpecs.length}`} ready={domainContractSpecs.length > 0} />
        <ReadinessCard label="Projection" value={`${domainProjectionCards.length}`} ready={domainProjectionCards.length > 0} />
      </div>
      <div className="task-system-domain-context__actions">
        <ToolbarButton onClick={createDomainDraft}><Plus size={15} />新任务域</ToolbarButton>
        <ToolbarButton disabled={!selectedDomain} onClick={() => setTaskSystemLayer("domains")}>编辑任务域</ToolbarButton>
      </div>
    </>
  );
  const managementLayerSlot = (
    <div className="task-system-workspace-switcher-grid">
      <section className="task-system-workspace-switcher-group task-system-workspace-switcher-group--primary" aria-label="任务系统主对象">
        {primaryTaskSystemLayerItems.map((item) => (
        <button
          className={taskSystemLayer === item.value ? "task-system-workspace-card task-system-workspace-card--active" : "task-system-workspace-card"}
          key={item.value}
          onClick={() => selectTaskSystemLayer(item.value)}
          type="button"
        >
          <span>{item.label}</span>
          <strong>{item.meta}</strong>
          <small>{item.detail}</small>
        </button>
        ))}
      </section>
      <section className="task-system-workspace-switcher-group task-system-workspace-switcher-group--support" aria-label="任务系统支撑对象">
        {supportingTaskSystemLayerItems.map((item) => (
          <button
            className={taskSystemLayer === item.value ? "task-system-workspace-card task-system-workspace-card--support task-system-workspace-card--active" : "task-system-workspace-card task-system-workspace-card--support"}
            key={item.value}
            onClick={() => selectTaskSystemLayer(item.value)}
            type="button"
          >
            <span>{item.label}</span>
            <strong>{item.meta}</strong>
          </button>
        ))}
      </section>
    </div>
  );
  function openTaskGraphEditor(graphId = selectedTaskGraph?.graph_id || "") {
    const nextDomain = selectedDomain ?? editorDomain;
    const nextDomainId = nextDomain?.domain_id || "";
    const nextGraph = allTaskGraphs.find((item) => String(item.graph_id ?? "") === graphId)
      ?? allTaskGraphs.find((item) => String(item.domain_id ?? "").trim() === nextDomainId)
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
    const nextGraph = allTaskGraphs.find((item) => String(item.domain_id ?? "").trim() === nextDomainId);
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
        <ToolbarButton disabled={saving === "task-graph-create"} onClick={() => void createTaskGraphDraft()}><Network size={15} />新图草稿</ToolbarButton>
      </div>
    </>
  );

  return (
    <TaskSystemShell
      activeLayer={taskSystemLayer}
      error={error}
      contextSlot={taskLayer === "management" ? domainContextSlot : undefined}
      layerSlot={taskLayer === "management" ? managementLayerSlot : undefined}
      mode={taskLayer}
      navItems={taskSystemLayerItems}
      notice={notice}
      onBackToGraphs={() => selectTaskSystemLayer("graphs")}
      onRefresh={() => void load()}
      onSelectLayer={(layer) => {
        void load();
        selectTaskSystemLayer(layer);
      }}
      path={taskLayer === "editor"
        ? `${editorDomain?.title || "未选择任务域"} / ${taskGraphDraftV2.title || editorSelectedTaskGraph?.title || "任务图"}`
        : `${selectedDomain?.title || "未选择任务域"} / ${taskSystemLayerItems.find((item) => item.value === taskSystemLayer)?.label || "任务系统"}`}
      title={taskLayer === "editor" ? taskGraphDraftV2.title || editorSelectedTaskGraph?.title || "任务图编辑器" : taskSystemLayerItems.find((item) => item.value === taskSystemLayer)?.label || "任务系统"}
    >

      {taskLayer === "management" ? (
        <section className={`task-management-stage task-management-stage--${taskSystemLayer}`}>
          {taskSystemLayer === "domains" ? (
            <TaskDomainManagementPage>
              <main className="task-management-workbench task-management-workbench--full">
                <header className="task-management-titlebar">
                  <div>
                    <span>Domain Boundary</span>
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
                      <h3>{selectedDomain?.title || "任务域"}</h3>
                    )}
                    <p>任务域只负责分类、入口策略和域级边界，不编辑图节点和运行产物。</p>
                  </div>
                  <div className="boundary-actions">
                    <ToolbarButton onClick={() => setEditingDomainName(true)}><Pencil size={15} />改名</ToolbarButton>
                    <ToolbarButton disabled={saving === "domain-delete" || !selectedDomain} onClick={() => selectedDomain ? void deleteDomain(selectedDomain) : undefined}><Trash2 size={15} />删除域</ToolbarButton>
                    <ToolbarButton disabled={saving === "domain"} onClick={() => void saveDomain()} variant="primary"><Save size={15} />保存域</ToolbarButton>
                  </div>
                </header>
                <section className="boundary-card">
                  <header><strong>任务域设置</strong><span>{selectedDomain?.domain_id || domainDraft.domain_id}</span></header>
                  <div className="boundary-form">
                    <label className="boundary-check"><input checked={domainDraft.enabled} onChange={(event) => setDomainDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用任务域</label>
                    <Field label="任务域描述" wide><textarea value={domainDraft.description} onChange={(event) => setDomainDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                    <SystemFields>
                      <Field label="任务域 ID"><input value={domainDraft.domain_id} onChange={(event) => setDomainDraft((value) => ({ ...value, domain_id: event.target.value }))} /></Field>
                      <Field label="入口策略 ID"><input value={entryDraft.profile_id} onChange={(event) => setEntryDraft((value) => ({ ...value, profile_id: event.target.value }))} /></Field>
                      <SelectField label="默认 Workflow" onChange={(value) => setEntryDraft((current) => ({ ...current, default_workflow_id: value }))} options={workflowOptions} value={entryDraft.default_workflow_id} />
                    </SystemFields>
                  </div>
                  <div className="boundary-actions">
                    <ToolbarButton disabled={saving === "entry"} onClick={() => void saveEntry()}><Save size={15} />保存入口策略</ToolbarButton>
                    <div className="task-domain-quick-jumps">
                      <ToolbarButton onClick={() => selectTaskSystemLayer("tasks")}>任务定义库</ToolbarButton>
                      <ToolbarButton onClick={() => selectTaskSystemLayer("graphs")}>任务图库</ToolbarButton>
                      <ToolbarButton onClick={() => selectTaskSystemLayer("contracts")}>契约库</ToolbarButton>
                    </div>
                  </div>
                </section>
                {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
                {!loading && projectionLoading ? <div className="boundary-empty">投影卡片加载中，任务系统已可用</div> : null}
                <div className="task-management-status-row">
                  <ReadinessCard label="域内任务" value={`${selectedDomain?.tasks.length ?? 0}`} ready={Boolean(selectedDomain?.tasks.length)} />
                  <ReadinessCard label="任务图" value={`${taskGraphs.length}`} ready={Boolean(taskGraphs.length)} />
                  <ReadinessCard label="契约" value={`${domainContractSpecs.length}`} ready={Boolean(domainContractSpecs.length)} />
                  <ReadinessCard label="Projection" value={`${domainProjectionCards.length}`} ready={Boolean(domainProjectionCards.length)} />
                </div>
              </main>
            </TaskDomainManagementPage>
          ) : null}

          {taskSystemLayer === "tasks" ? (
            <TaskDefinitionPage>
              <aside className="task-management-directory">
                <div className="task-management-directory__head">
                  <span>{selectedDomain?.title || "未选择任务域"}</span>
                  <strong>具体任务</strong>
                  <ToolbarButton disabled={saving === "task-create" || !selectedDomain} onClick={() => void createTaskDraft()}><Plus size={15} />新任务</ToolbarButton>
                </div>
                <div className="boundary-list">
                  {selectedDomainTasks.map((task) => (
                    <button
                      className={task.task_id === selectedTaskId ? "boundary-list-row boundary-list-row--active task-domain-task-row" : "boundary-list-row task-domain-task-row"}
                      key={task.task_id}
                      onClick={() => setSelectedTaskId(task.task_id)}
                      type="button"
                    >
                      <strong>{task.task_title}</strong>
                      <span>{task.enabled ? "启用" : "停用"}</span>
                    </button>
                  ))}
                  {!selectedDomainTasks.length ? <div className="boundary-empty">当前任务域暂无任务。</div> : null}
                </div>
              </aside>
              <main className="task-management-workbench">
                <header className="task-management-titlebar">
                  <div>
                    <span>Task Definition</span>
                    <h3>{selectedTask ? (taskDraft.task_title || selectedTask.task_title) : "未选择任务"}</h3>
                    <p>这里只定义可复用的具体任务。任务图是同一任务域下的独立编排对象，图节点可以引用这里的任务定义。</p>
                  </div>
                  <div className="boundary-actions">
                    <ToolbarButton disabled={!selectedTask} onClick={() => selectedTask ? sendTaskToChat(selectedTask, selectedTaskDomain) : undefined}>带入主会话</ToolbarButton>
                    <ToolbarButton disabled={saving === "task-stack" || !selectedTask} onClick={() => void saveTaskStack()} variant="primary"><Save size={15} />保存任务</ToolbarButton>
                  </div>
                </header>
                {selectedTask ? (
                  <section className="boundary-layer-stack">
                    <LayerNav
                      ariaLabel="任务详情页面"
                      items={taskDetailPanelItems}
                      value={taskConfigPanel}
                      onChange={setTaskConfigPanel}
                      variant="secondary"
                    />
                    <>
                      <section className="boundary-card">
                          <header>
                            <strong>{taskDraft.task_title || "特定任务定义"}</strong>
                            <ToolbarButton disabled={saving === "task-delete"} onClick={() => void deleteTaskRecord(selectedTask)}>
                              <Trash2 size={15} />删除任务
                            </ToolbarButton>
                          </header>
                          <div className="boundary-form task-definition-form">
                            <Field label="任务标题"><input value={taskDraft.task_title} onChange={(event) => setTaskDraft((value) => ({ ...value, task_title: event.target.value }))} /></Field>
                            <Field label="所属任务域"><input readOnly value={selectedDomain?.title || domainTitle(domainIdToLegacyFamily(taskDomainId(taskDraft)))} /></Field>
                            <Field label="验收档案"><input value={taskDraft.acceptance_profile_id} onChange={(event) => setTaskDraft((value) => ({ ...value, acceptance_profile_id: event.target.value }))} /></Field>
                            <Field label="任务描述" wide><textarea value={taskDraft.description} onChange={(event) => setTaskDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                            <label className="boundary-check"><input checked={taskDraft.enabled} onChange={(event) => setTaskDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用任务</label>
                            <section className="contract-editor-section task-artifact-policy-editor">
                              <header><strong>产物规则</strong><span>任务级默认产物策略；正式产物记录在运行管理中查看</span></header>
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
                      <section className="boundary-card">
                        <header><strong>被任务图节点引用</strong><span>{selectedTaskGraphReferences.length} 张图</span></header>
                        <div className="boundary-list boundary-list--scroll">
                          {selectedTaskGraphReferences.map(({ graph, nodeRefs }) => (
                            <article className="boundary-list-row boundary-list-row--stacked" key={graph.graph_id}>
                              <div>
                                <strong>{graph.title || graph.graph_id}</strong>
                                <span>{graph.publish_state || "draft"} / {nodeRefs.length} 个节点引用</span>
                              </div>
                              <span>{nodeRefs.map((item) => `${item.title} · ${item.nodeId}`).join(" / ")}</span>
                              <div className="boundary-actions">
                                <ToolbarButton onClick={() => openTaskGraphEditor(graph.graph_id)}>打开这张图</ToolbarButton>
                              </div>
                            </article>
                          ))}
                          {!selectedTaskGraphReferences.length ? (
                            <div className="boundary-empty">当前具体任务还没有被任何任务图节点引用。</div>
                          ) : null}
                        </div>
                      </section>
                    </>
                  </section>
                ) : <div className="boundary-empty">先在左侧选择或创建一个具体任务。</div>}
              </main>
            </TaskDefinitionPage>
          ) : null}

          {taskSystemLayer === "contracts" ? (
            <TaskContractManagementPage>
              <header className="task-management-titlebar">
                <div>
                  <span>Contract Catalog</span>
                  <h3>契约库</h3>
                  <p>这里维护任务契约与图契约。Agent 只引用边界，不在这里单独存任务侧特例。</p>
                </div>
                <div className="boundary-actions">
                  <ToolbarButton disabled={saving === "contract-spec"} onClick={() => setContractPanel("library")}>
                    <ClipboardList size={15} />管理契约
                  </ToolbarButton>
                  <ToolbarButton disabled={!selectedTaskGraph} onClick={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}>
                    <Network size={15} />进入图契约层
                  </ToolbarButton>
                </div>
              </header>
              <section className="boundary-layer-stack task-system-contract-center">
                <LayerNav ariaLabel="任务域契约页面" items={contractPanelItems} value={contractPanel} onChange={setContractPanel} variant="secondary" />
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
                      <header><div className="boundary-identity-stack"><span>域级模板中心</span><strong>契约草案模板</strong><small>按任务域隔离</small></div></header>
                      <p>模板能力只注册契约草案，不直接创建 Agent 或跨域资产。正式节点装配仍由 TaskGraph 和编排资源完成。</p>
                    </article>
                    <article className="boundary-card contract-template-card">
                      <header><div className="boundary-identity-stack"><span>通用模板</span><strong>节点执行契约</strong><small>适用于普通 Agent 节点</small></div></header>
                      <p>用于普通 Agent 节点的输入输出边界。字段级模板在契约库中新建后按任务域维护。</p>
                    </article>
                  </section>
                ) : null}
                {contractPanel === "bindings" ? (
                  <section className="boundary-layer-grid boundary-layer-grid--wide">
                    <TaskContractPanel
                      contractSpecs={domainContractSpecs}
                      onWorkflowOutputContractChange={(contractId) => setWorkflowDraft((current) => ({ ...current, output_contract_id: contractId }))}
                      setTaskDraft={setTaskDraft}
                      taskDraft={taskDraft}
                      workflowOutputContractId={workflowDraft.output_contract_id}
                    />
                    <section className="boundary-card">
                      <header><strong>任务图契约引用</strong><span className="boundary-badge">{activeGraphNodes.length} 节点 / {activeGraphEdges.length} 边</span></header>
                      <div className="boundary-list boundary-list--scroll">
                        {activeGraphNodes.map((node, index) => (
                          <article className="boundary-list-row" key={String(node.node_id ?? `node_${index}`)}>
                            <strong>{String(node.title ?? node.node_id ?? "节点")}</strong>
                            <span>{contractLabel(String(node.node_contract_id ?? node.output_contract_id ?? ""), domainContractSpecs, contractCatalog)}</span>
                          </article>
                        ))}
                        {activeGraphEdges.map((edge, index) => (
                          <article className="boundary-list-row" key={String(edge.edge_id ?? `edge_${index}`)}>
                            <strong>{String(edge.edge_type ?? edge.edge_id ?? "交接边")}</strong>
                            <span>{contractLabel(String(edge.payload_contract_id ?? ""), domainContractSpecs, contractCatalog)}</span>
                          </article>
                        ))}
                      </div>
                    </section>
                  </section>
                ) : null}
                {contractPanel === "manifest" ? (
                  <ContractOverviewPanel
                    contractSpecs={domainContractSpecs}
                    selectedTaskGraph={activeTaskGraph}
                    selectedNodeId={selectedGraphNodeId}
                  />
                ) : null}
              </section>
            </TaskContractManagementPage>
          ) : null}

          {taskSystemLayer === "graphs" ? (
            <TaskGraphManagementPage>
              <aside className="task-management-directory">
                <div className="task-management-directory__head">
                  <span>{selectedDomain?.title || "任务域"}</span>
                  <strong>任务图库</strong>
                  <ToolbarButton disabled={saving === "task-graph-create" || !selectedDomain} onClick={() => void createTaskGraphDraft()}><Network size={15} />新图草稿</ToolbarButton>
                </div>
                <div className="boundary-list">
                  {taskGraphs.map((graph) => (
                    <button
                      className={graph.graph_id === selectedTaskGraphId ? "boundary-list-row boundary-list-row--active task-domain-task-row" : "boundary-list-row task-domain-task-row"}
                      key={graph.graph_id}
                      onClick={() => setSelectedTaskGraphId(graph.graph_id)}
                      type="button"
                    >
                      <strong>{graph.title}</strong>
                      <span>{graph.publish_state || "draft"} / {(graph.nodes ?? []).length} 节点</span>
                    </button>
                  ))}
                  {!taskGraphs.length ? <div className="boundary-empty">当前任务域暂无任务图草稿。</div> : null}
                </div>
              </aside>
              <main className="task-management-workbench">
                <header className="task-management-titlebar">
                  <div>
                    <span>Graph Workspace</span>
                    <h3>{selectedTaskGraph?.title || "未选择任务图"}</h3>
                    <p>这里管理任务域下的一等 TaskGraph。进入 Studio 后才编辑图内部节点、边、资源流和时序。</p>
                  </div>
                  <div className="boundary-actions">
                    <ToolbarButton disabled={!selectedTaskGraph} onClick={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}>进入 Studio</ToolbarButton>
                    <ToolbarButton disabled={saving === "task-graph-duplicate" || !selectedTaskGraph} onClick={() => void duplicateTaskGraphDraft()}>复制图</ToolbarButton>
                    <ToolbarButton disabled={saving === "task-graph" || !selectedTaskGraph} onClick={() => void saveTaskGraphStack(false)} variant="primary"><Save size={15} />保存图</ToolbarButton>
                  </div>
                </header>
                {selectedTaskGraph ? (
                  <section className="boundary-layer-stack">
                    <div className="task-management-status-row">
                      <ReadinessCard label="节点" value={`${activeGraphNodes.length}`} ready={Boolean(activeGraphNodes.length)} />
                      <ReadinessCard label="边" value={`${activeGraphEdges.length}`} ready={Boolean(activeGraphEdges.length)} />
                      <ReadinessCard label="预检" value={editorValid ? "通过" : `${editorIssueCount} 个问题`} ready={editorValid} />
                      <ReadinessCard label="发布状态" value={String(taskGraphDraftV2.publish_state || selectedTaskGraph.publish_state || "draft")} ready={editorPublished} />
                    </div>
                    <section className="task-system-task-cover">
                      <article className="boundary-card">
                        <header>
                          <strong>图资源总览</strong>
                          <span>{taskGraphStandardViewLoading ? "加载中" : `${activeTaskGraphResourceModel.resources.length} objects`}</span>
                        </header>
                        <div className="boundary-kv">
                          <p><span>记忆仓库</span><strong>{activeTaskGraphResourceModel.memoryResources.length}</strong></p>
                          <p><span>产物仓库</span><strong>{activeTaskGraphResourceModel.artifactResources.length}</strong></p>
                          <p><span>记忆边</span><strong>{activeTaskGraphResourceModel.memoryEdges.length}</strong></p>
                          <p><span>产物边</span><strong>{activeTaskGraphResourceModel.artifactEdges.length}</strong></p>
                          <p><span>运行隔离</span><strong>{activeTaskGraphResourceModel.runtimeIsolation?.task_run_scope_policy ?? "isolated_per_task_run"}</strong></p>
                          <p><span>标准问题</span><strong>{activeTaskGraphResourceModel.issueCount}</strong></p>
                        </div>
                        <div className="boundary-list boundary-list--scroll">
                          {activeTaskGraphResourceModel.resources.slice(0, 6).map((resource) => (
                            <article className="boundary-list-row boundary-list-row--stacked" key={resource.node_id}>
                              <div>
                                <strong>{resource.title}</strong>
                                <span>{resource.resource_type}</span>
                              </div>
                              <span>{resource.repository_id || resource.node_id}</span>
                              <span>{resource.collections.join(" / ") || "default"}</span>
                            </article>
                          ))}
                          {!activeTaskGraphResourceModel.resources.length ? (
                            <div className="boundary-empty">当前任务图还没有编译出标准资源对象。</div>
                          ) : null}
                        </div>
                      </article>
                      <article className="boundary-card">
                        <header>
                          <strong>图时序总览</strong>
                          <span>{taskGraphStandardViewLoading ? "加载中" : `${activeTaskGraphTimelineModel.phases.length} phases`}</span>
                        </header>
                        <div className="boundary-kv">
                          <p><span>入口节点</span><strong>{activeTaskGraphTimelineModel.entryNodeId || "未编译"}</strong></p>
                          <p><span>出口节点</span><strong>{activeTaskGraphTimelineModel.outputNodeId || "未编译"}</strong></p>
                          <p><span>阶段</span><strong>{activeTaskGraphTimelineModel.phases.length}</strong></p>
                          <p><span>时序边</span><strong>{activeTaskGraphTimelineModel.temporalEdges.length}</strong></p>
                          <p><span>循环体</span><strong>{activeTaskGraphTimelineModel.loopFrames.length}</strong></p>
                          <p><span>异步节点</span><strong>{activeTaskGraphTimelineModel.asyncNodeCount}</strong></p>
                        </div>
                        <div className="boundary-list boundary-list--scroll">
                          {activeTaskGraphTimelineModel.phases.slice(0, 5).map((phase, index) => {
                            const phaseId = String(phase.phase_id ?? phase.id ?? `phase_${index + 1}`);
                            return (
                              <article className="boundary-list-row" key={phaseId}>
                                <strong>{String(phase.title ?? phaseId)}</strong>
                                <span>{phaseId} / {activeTaskGraphTimelineModel.phaseNodeCounts[phaseId] ?? 0} 节点</span>
                              </article>
                            );
                          })}
                          {!activeTaskGraphTimelineModel.phases.length ? (
                            <div className="boundary-empty">当前任务图还没有编译出标准时序对象。</div>
                          ) : null}
                        </div>
                      </article>
                    </section>
                    {taskGraphStandardViewError ? (
                      <div className="boundary-notice boundary-notice--error">
                        <AlertTriangle size={16} />
                        标准对象视图加载失败：{taskGraphStandardViewError}
                      </div>
                    ) : null}
                    <TaskAssemblyPreflightPanel
                      a2aCatalog={a2aCatalog}
                      editorIssueCount={editorIssueCount}
                      editorPublished={editorPublished}
                      editorValid={editorValid}
                      onBackToGraph={() => openTaskGraphEditor(selectedTaskGraph.graph_id)}
                      saveTaskGraphStack={saveTaskGraphStack}
                      saving={saving}
                      selectedTaskGraph={activeTaskGraph}
                      taskGraphMetadata={taskGraphDraftV2.metadata}
                      selectedGraphSpec={editorGraphSpec}
                      selectedNodeId={selectedGraphNodeId}
                      selectedTask={null}
                      setSelectedNodeId={setSelectedGraphNodeId}
                      topologyDirty={topologyDirty}
                    />
                  </section>
                ) : <div className="boundary-empty">请先创建或选择一张任务图。</div>}
              </main>
            </TaskGraphManagementPage>
          ) : null}

          {taskSystemLayer === "orchestration" ? (
            <TaskOrchestrationResourcePage>
              <header className="task-management-titlebar">
                <div>
                  <span>Orchestration Resources</span>
                  <h3>编排资源</h3>
                  <p>这里直接对接编排系统。任务系统负责任务与 TaskGraph，编排系统负责 Agent 主数据、投影引用和运行档案。</p>
                </div>
                <div className="boundary-actions">
                  <ToolbarButton onClick={() => openOrchestrationControl({ layer: "registry", reason: "从任务系统进入编排控制台：管理 Agent 名册和主数据。" })}>
                    <Network size={15} />打开编排控制台
                  </ToolbarButton>
                  <ToolbarButton onClick={() => openOrchestrationControl({ layer: "runtime", reason: "从任务系统进入运行档案：配置 Agent 的运行边界与装配信息。" })}>
                    <Send size={15} />配置运行档案
                  </ToolbarButton>
                </div>
              </header>
              <div className="boundary-notice">
                <CheckCircle2 size={16} />
                任务侧只做节点装配与运行编排。Agent 侧不再维护按任务拆开的配置入口，只保留统一运行档案。
              </div>
              <section className="task-system-task-cover">
                <article className="boundary-card">
                  <header><strong>Agent 库</strong><span>{orchestrationAgentCatalog?.agents?.length ?? 0} agents</span></header>
                  <div className="boundary-list boundary-list--scroll">
                    {orchestrationAgents.slice(0, 8).map((agent) => (
                      <article className="boundary-list-row" key={String(agent.agent_id ?? agent.id ?? agent.agent_name)}>
                        <strong>{String(agent.display_name ?? agent.agent_name ?? agent.agent_id ?? "Agent")}</strong>
                        <span>{String(agent.agent_id ?? "")}</span>
                      </article>
                    ))}
                    {!orchestrationAgents.length ? <div className="boundary-empty">编排系统暂未加载到 Agent。</div> : null}
                  </div>
                </article>
                <article className="boundary-card">
                  <header><strong>运行档案</strong><span>{orchestrationProfiles.length} 份</span></header>
                  <div className="boundary-list boundary-list--scroll">
                    {orchestrationProfiles.slice(0, 8).map((profile) => (
                      <article className="boundary-list-row" key={String(profile.agent_profile_id)}>
                        <strong>{String(profile.agent_profile_id)}</strong>
                        <span>{String(profile.agent_id)} · {profile.allowed_context_sections.length} 上下文段 / {profile.allowed_memory_scopes.length} 记忆范围</span>
                      </article>
                    ))}
                    {!orchestrationProfiles.length ? <div className="boundary-empty">还没有可用于节点装配的运行档案。</div> : null}
                  </div>
                </article>
                <article className="boundary-card">
                  <header><strong>投影引用</strong><span>{projectionCards.length} 项</span></header>
                  <div className="boundary-kv">
                    <p><span>职责语言</span><strong>由 Projection / Prompt 主数据提供</strong></p>
                    <p><span>节点绑定</span><strong>在 TaskGraph 节点装配页选择引用</strong></p>
                    <p><span>资源读写</span><strong>{graphResourceEdges.length} 条资源边</strong></p>
                    <p><span>运行边界</span><strong>统一进入运行档案</strong></p>
                  </div>
                </article>
              </section>
              <section className="boundary-card">
                <header><strong>节点装配摘要</strong><span>{graphNodeAssemblyRows.length} nodes</span></header>
                <div className="boundary-list boundary-list--scroll">
                  {graphNodeAssemblyRows.map((row) => (
                    <article className="boundary-list-row boundary-list-row--stacked" key={row.nodeId}>
                      <div>
                        <strong>{String(row.node.title ?? row.nodeId ?? "节点")}</strong>
                        <span>{row.ready ? "装配可用" : "缺少 Agent / 运行档案 / 上下文段"}</span>
                      </div>
                      <span>执行 Agent {row.agentLabel} · 运行档案 {row.profileId || "未绑定"} · 投影 {row.projectionLabel}</span>
                      <span>上下文 {row.contextSummary}</span>
                      <span>记忆范围 {row.memorySummary}</span>
                      <div className="boundary-actions">
                        <ToolbarButton disabled={!row.agentId} onClick={() => openOrchestrationControl({
                          agentId: row.agentId,
                          agentProfileId: row.profileId || undefined,
                          layer: "runtime",
                          nodeId: row.nodeId,
                          reason: `配置节点“${String(row.node.title ?? row.nodeId)}”绑定 Agent 的运行档案。`,
                        })}>
                          配运行档案
                        </ToolbarButton>
                      </div>
                    </article>
                  ))}
                  {!graphNodeAssemblyRows.length ? <div className="boundary-empty">当前任务图还没有节点引用。先到任务图页创建或选择图，再进入节点装配。</div> : null}
                </div>
                <div className="boundary-actions">
                  <ToolbarButton disabled={!selectedTaskGraph} onClick={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}>进入节点装配</ToolbarButton>
                  <ToolbarButton onClick={() => openOrchestrationControl({ layer: "runtime", reason: "从当前任务图检查所有 Agent 运行档案。" })}>管理运行档案</ToolbarButton>
                </div>
              </section>
            </TaskOrchestrationResourcePage>
          ) : null}

          {taskSystemLayer === "runtime" ? (
            <TaskRuntimeManagementPage>
              <header className="task-management-titlebar">
                <div>
                  <span>Run Data</span>
                  <h3>运行管理</h3>
                  <p>运行数据以显式 task_run_id 隔离。这里直接查看正式记忆库、产物库和当前运行状态，任务定义页不再承担运行库管理。</p>
                </div>
                <div className="boundary-actions">
                  <ToolbarButton disabled={runtimeLoading} onClick={() => void refreshRuntimeManagement()}>
                    {runtimeLoading ? <Loader2 size={15} /> : <RefreshCw size={15} />}刷新运行库
                  </ToolbarButton>
                  <ToolbarButton disabled={!taskGraphMonitorBinding} onClick={() => setTaskGraphRunInteractionOpen(true)}>
                    <Monitor size={15} />打开常驻监控窗
                  </ToolbarButton>
                  <ToolbarButton disabled={!selectedTaskGraph} onClick={() => openTaskGraphEditor(selectedTaskGraph?.graph_id)}>进入发布与运行</ToolbarButton>
                </div>
              </header>
              {runtimeError ? (
                <div className="boundary-notice boundary-notice--error">
                  <AlertTriangle size={16} />
                  {runtimeError}
                </div>
              ) : null}
              <section className="boundary-card">
                <header>
                  <strong>运行实例焦点</strong>
                  <span>{runtimeTaskRunId.trim() ? "按 task_run_id 隔离" : "全局概览"}</span>
                </header>
                <div className="boundary-form">
                  <Field label="task_run_id" wide>
                    <input
                      onChange={(event) => {
                        runtimeDefaultedRef.current = true;
                        setRuntimeTaskRunId(event.target.value);
                      }}
                      placeholder="输入 task_run_id；留空时仅作全局概览，不能判断单次运行隔离"
                      value={runtimeTaskRunId}
                    />
                  </Field>
                  <Field label="当前会话运行实例">
                    <select
                      onChange={(event) => {
                        runtimeDefaultedRef.current = true;
                        setRuntimeTaskRunId(event.target.value);
                      }}
                      value={runtimeTaskRunId}
                    >
                      <option value="">全局概览，不筛选 task_run_id</option>
                      {runtimeRunsForSelectedGraph.map((item, index) => {
                        const id = getRuntimeTaskRunId(item) || `run_${index}`;
                        const run = dictOf(item.task_run);
                        const status = recordFieldText(run, ["status", "runtime_status"], "unknown");
                        const label = `${id} · ${status} · ${item.latest_event_type || "no_event"}`;
                        return <option key={id} value={id}>{label}</option>;
                      })}
                    </select>
                  </Field>
                  <Field label="常驻监控绑定">
                    <input readOnly value={runtimeBoundTaskRunId || "未绑定常驻监控运行"} />
                  </Field>
                </div>
                <div className={runtimeTaskRunId.trim() ? "boundary-notice" : "boundary-notice boundary-notice--error"}>
                  {runtimeTaskRunId.trim() ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                  {runtimeTaskRunId.trim()
                    ? `当前正式记忆库和产物库查询只读取 task_run_id=${runtimeTaskRunId.trim()} 的运行数据。`
                    : "当前为全局概览，只能看总量和最近记录，不能据此判断某一次任务是否隔离。"}
                </div>
              </section>
              <section className="task-system-task-cover">
                <article className="boundary-card">
                  <header><strong>当前任务图</strong><span>{selectedTaskGraph?.graph_id || "未选择"}</span></header>
                  <div className="boundary-kv">
                    <p><span>任务域</span><strong>{selectedDomain?.title || "-"}</strong></p>
                    <p><span>图</span><strong>{selectedTaskGraph?.title || "-"}</strong></p>
                    <p><span>发布状态</span><strong>{String(selectedTaskGraph?.publish_state || taskGraphDraftV2.publish_state || "draft")}</strong></p>
                  </div>
                </article>
                <article className="boundary-card">
                  <header><strong>运行状态</strong><span>{runtimeMonitorForSelectedRun?.status || recordFieldText(selectedRuntimeRunRecord, ["status", "runtime_status"], "未选择")}</span></header>
                  <div className="boundary-kv">
                    <p><span>task_run_id</span><strong>{runtimeTaskRunId.trim() || "未筛选"}</strong></p>
                    <p><span>最新事件</span><strong>{selectedRuntimeSummary?.latest_event_type || "-"}</strong></p>
                    <p><span>事件数量</span><strong>{selectedRuntimeSummary?.event_count ?? "-"}</strong></p>
                    <p><span>更新时间</span><strong>{formatRuntimeTime(runtimeMonitorForSelectedRun?.updated_at ?? selectedRuntimeRunRecord.updated_at)}</strong></p>
                  </div>
                </article>
              </section>
              <section className="task-system-task-cover">
                <article className="boundary-card">
                  <header><strong><Database size={15} />正式记忆库</strong><span>{runtimeFormalOverview?.record_count ?? 0} records</span></header>
                  <div className="boundary-metric-grid">
                    <div className="boundary-readiness"><span>仓库</span><strong>{runtimeFormalOverview?.repository_count ?? 0}</strong></div>
                    <div className="boundary-readiness"><span>集合</span><strong>{runtimeFormalOverview?.collection_count ?? 0}</strong></div>
                    <div className="boundary-readiness"><span>记录</span><strong>{runtimeFormalOverview?.record_count ?? 0}</strong></div>
                    <div className="boundary-readiness"><span>版本</span><strong>{runtimeFormalOverview?.version_count ?? 0}</strong></div>
                    <div className="boundary-readiness"><span>读取日志</span><strong>{runtimeFormalOverview?.read_log_count ?? 0}</strong></div>
                  </div>
                  <div className="boundary-list boundary-list--scroll">
                    {(runtimeFormalOverview?.records ?? []).slice(0, 8).map((record) => (
                      <article className="boundary-list-row boundary-list-row--stacked" key={record.record_id}>
                        <div>
                          <strong>{record.record_key || record.record_id}</strong>
                          <span className={statusBadgeClass(record.status)}>{taskSystemOptionLabel(record.status || "unknown")}</span>
                        </div>
                        <span>{record.repository_id} / {record.collection_id}</span>
                        <span>{record.record_kind || "record"} · head {record.head_version_id || "-"} · 更新 {record.updated_at || "-"}</span>
                      </article>
                    ))}
                    {!(runtimeFormalOverview?.records ?? []).length ? (
                      <div className="boundary-empty">当前筛选下没有正式记忆记录。</div>
                    ) : null}
                  </div>
                </article>
                <article className="boundary-card">
                  <header><strong><FileStack size={15} />产物库</strong><span>{runtimeArtifactOverview?.artifact_count ?? 0} artifacts</span></header>
                  <div className="boundary-metric-grid">
                    <div className="boundary-readiness"><span>仓库</span><strong>{runtimeArtifactOverview?.repository_count ?? 0}</strong></div>
                    <div className="boundary-readiness"><span>产物</span><strong>{runtimeArtifactOverview?.artifact_count ?? 0}</strong></div>
                    {Object.entries(runtimeArtifactStatusCounts).slice(0, 4).map(([status, count]) => (
                      <div className="boundary-readiness" key={status}><span>{taskSystemOptionLabel(status)}</span><strong>{count}</strong></div>
                    ))}
                  </div>
                  <div className="boundary-list boundary-list--scroll">
                    {(runtimeArtifactOverview?.artifacts ?? []).slice(0, 8).map((artifact) => (
                      <article className="boundary-list-row boundary-list-row--stacked" key={artifact.artifact_id}>
                        <div>
                          <strong>{artifact.artifact_ref || artifact.artifact_id}</strong>
                          <span className={statusBadgeClass(artifact.status)}>{taskSystemOptionLabel(artifact.status || "unknown")}</span>
                        </div>
                        <span>{artifact.repository_id} / {artifact.collection_id}</span>
                        <span>{artifact.path || "未记录路径"}</span>
                      </article>
                    ))}
                    {!(runtimeArtifactOverview?.artifacts ?? []).length ? (
                      <div className="boundary-empty">当前筛选下没有产物记录。</div>
                    ) : null}
                  </div>
                </article>
              </section>
              <section className="boundary-card">
                <header><strong><ClipboardList size={15} />运行库边界</strong><span>这里只查看运行结果</span></header>
                <div className="boundary-kv">
                  <p><span>正式记忆库配置</span><strong>TaskGraph Studio / 资源流 / 记忆仓库节点与 memory_* 边</strong></p>
                  <p><span>产物库配置</span><strong>TaskGraph Studio / 资源流 / 产物仓库节点与 artifact_* 边</strong></p>
                  <p><span>Agent 接收范围</span><strong>编排资源 / 运行档案</strong></p>
                  <p><span>运行查看</span><strong>运行管理 / 常驻监控窗 / 发布运行页</strong></p>
                </div>
              </section>
            </TaskRuntimeManagementPage>
          ) : null}
        </section>
      ) : null}

      {taskLayer === "editor" ? (
        <section className="task-system-editor-shell">
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
            sendTaskGraphToChat={sendTaskGraphToChat}
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
        </section>
      ) : null}
    </TaskSystemShell>
  );
}








