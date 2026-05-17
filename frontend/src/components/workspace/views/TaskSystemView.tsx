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
import { ContractLibraryPanel, contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import { ContractOverviewPanel } from "@/components/workspace/views/task-system/ContractOverviewPanel";
import { TaskContractPanel } from "@/components/workspace/views/task-system/TaskContractPanel";
import { TaskAssemblyPreflightPanel } from "@/components/workspace/views/task-system/TaskAssemblyPreflightPanel";
import { TaskGraphWorkbench } from "@/components/workspace/views/task-system/TaskGraphWorkbench";
import { TaskRunLoopWorkbenchPanel } from "@/components/workspace/views/task-system/TaskRunLoopWorkbenchPanel";
import {
  asRecord,
  emptyTaskGraphDraftV2,
  inferTaskGraphBoundaryNodes,
  taskGraphRecordToDraftV2,
  type TaskGraphDraftV2,
  type TaskGraphPublishStateV2,
} from "@/components/workspace/views/task-system/taskGraphDraftV2";
import { buildTaskGraphUpsertPayload } from "@/components/workspace/views/task-system/taskGraphSaveMapper";
import { buildTaskGraphTemplateDraft, type TaskGraphTemplateId } from "@/components/workspace/views/task-system/taskGraphTemplates";
import {
  graphEdgeId,
  graphEdgeSource,
  graphEdgeTarget,
  graphNodeTaskId,
} from "@/components/workspace/views/task-system/taskGraphTopologyUtils";
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
  upsertTaskSystemContract,
  upsertTaskSystemDomain,
  upsertTaskSystemEntryPolicy,
  upsertTaskSystemExecutionPolicy,
  upsertTaskSystemFlowContractBinding,
  upsertTaskSystemMemoryRequestProfile,
  upsertTaskSystemProjectionBinding,
  upsertTaskSystemSpecificRecord,
  upsertTaskSystemTaskGraph,
  upsertTaskWorkflow,
  type ConversationEntryPolicy,
  type ContractSpec,
  type OrchestrationAgentRuntimeCatalog,
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
  type TaskMemoryRequestProfile,
  type TaskProjectionBinding,
  type TaskSystemOverview,
  type TaskWorkflowRecord,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

type TaskLayer = "management" | "editor";
type TaskConfigPanel = "definition" | "contracts" | "preflight" | "runloop";
type ContractPanel = "library" | "templates" | "bindings" | "manifest";
type ChromeSelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

function TaskGraphChromeSelect({
  disabled = false,
  emptyLabel,
  label,
  onChange,
  options,
  placeholder,
  value,
}: {
  disabled?: boolean;
  emptyLabel?: string;
  label: string;
  onChange: (value: string) => void;
  options: ChromeSelectOption[];
  placeholder: string;
  value: string;
}) {
  const [open, setOpen] = useState(false);
  const selected = options.find((option) => option.value === value);
  const displayLabel = selected?.label || emptyLabel || placeholder;
  const selectableOptions = options.filter((option) => !option.disabled);
  const isDisabled = disabled || selectableOptions.length === 0;

  return (
    <label
      className={isDisabled ? "task-graph-editor-chrome__field task-graph-editor-chrome__field--disabled" : "task-graph-editor-chrome__field"}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      <span className="task-graph-editor-chrome__field-label">{label}</span>
      <div className="task-graph-editor-select">
        <button
          aria-expanded={open}
          disabled={isDisabled}
          onClick={() => setOpen((current) => !current)}
          type="button"
        >
          <span>{displayLabel}</span>
          <i aria-hidden="true" />
        </button>
        {open && !isDisabled ? (
          <div className="task-graph-editor-select__menu" role="listbox">
            {options.map((option) => (
              <button
                aria-selected={option.value === value}
                className={option.value === value ? "task-graph-editor-select__option task-graph-editor-select__option--active" : "task-graph-editor-select__option"}
                disabled={option.disabled}
                key={option.value || option.label}
                onClick={() => {
                  if (!option.disabled) {
                    onChange(option.value);
                    setOpen(false);
                  }
                }}
                role="option"
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </label>
  );
}

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
  const [taskGraphDraftV2, setTaskGraphDraftV2] = useState<TaskGraphDraftV2>(() => emptyTaskGraphDraftV2());
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
    const taskGraphs = overview.task_graph_management?.task_graphs ?? [];
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
  const allTaskGraphs = useMemo(() => consolePayload?.task_graph_management?.task_graphs ?? [], [consolePayload]);
  const allTaskGraphSpecs = useMemo(
    () => consolePayload?.task_graph_management?.task_graph_specs ?? [],
    [consolePayload],
  );
  const a2aCatalog = consolePayload?.task_graph_management?.a2a ?? null;
  const activeDomainId = selectedDomain?.domain_id || "";
  const taskGraphs = useMemo(
    () => activeDomainId ? allTaskGraphs.filter((item) => String(item.domain_id ?? "").trim() === activeDomainId) : [],
    [activeDomainId, allTaskGraphs],
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
  const editorSelectedTaskGraph = editorTaskGraphs.find((item) => item.graph_id === editorTaskGraphId) ?? null;
  const activeTaskGraph = taskLayer === "editor" ? editorSelectedTaskGraph : selectedTaskGraph;
  const activeTaskGraphSpec = allTaskGraphSpecs.find((item) => item.graph_id === activeTaskGraph?.graph_id) ?? null;
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
    editorTask?.task_mode,
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
      setTaskGraphDraftV2(emptyTaskGraphDraftV2());
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
  }, [activeTaskGraph]);

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
    const resourceNodeTypes = new Set(["memory_repository", "artifact_repository", "progress_ledger", "issue_ledger"]);
    const resourcePrefixByRole: Record<string, string> = {
      memory_repository: "memory.repository",
      artifact_repository: "artifact.repository",
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
      progress_ledger: "进度账本",
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
            required_receipt_status: "committed",
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
    const draftTask = taskLayer === "editor" ? editorTask : selectedTask;
    const draftDomainId = draftDomain?.domain_id || (draftTask ? taskDomainId(draftTask) : "");
    const draftFamily = draftTask?.task_family || domainIdToLegacyFamily(draftDomainId, "");
    if (taskLayer === "editor" && !draftTask) {
      setError("请先在图编辑器中打开一个任务。");
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
        task_id: draftTask?.task_id || "",
        metadata: {
          managed_by: "task_domain_console",
          graph_source: "task_graph_editor_v2",
          draft_identity_locked: true,
          task_family: draftFamily,
          domain_id: draftDomainId,
          task_id: draftTask?.task_id || "",
        },
      };
      nextDraft.metadata = {
        ...nextDraft.metadata,
        task_family: draftFamily,
        domain_id: draftDomainId,
        task_id: draftTask?.task_id || "",
      };
      if (taskLayer === "editor") {
        setEditorTaskGraphId(nextDraft.graph_id);
      } else {
        setSelectedTaskGraphId(nextDraft.graph_id);
      }
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
        task_id: sourceDraft.task_id,
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
        },
      };
      if (taskLayer === "editor") {
        setEditorTaskGraphId(nextGraphId);
      } else {
        setSelectedTaskGraphId(nextGraphId);
      }
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

  async function saveTaskGraphStack(nextPublished?: boolean, nextEditorPublishState?: "draft" | "saved" | "preflight_passed" | "published" | "run_bound" | "archived") {
    const draftDomain = taskLayer === "editor" ? editorDomain : selectedDomain;
    const draftTask = taskLayer === "editor" ? editorTask : selectedTask;
    const draftDomainId = draftDomain?.domain_id || (draftTask ? taskDomainId(draftTask) : "") || taskGraphDraftV2.domain_id || "";
    const draftFamily = draftTask?.task_family || taskGraphDraftV2.task_family || domainIdToLegacyFamily(draftDomainId, "");
    if (taskLayer === "editor" && !draftTask) {
      setError("请先在图编辑器中打开一个任务。");
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
        task_id: draftTask?.task_id || taskGraphDraftV2.task_id || "",
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
          task_id: draftTask?.task_id || taskGraphDraftV2.task_id || "",
        },
      };
      const taskGraphPayload = buildTaskGraphUpsertPayload({
        taskGraphDraft: effectiveTaskGraphDraftV2,
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
      const payload = await upsertTaskSystemTaskGraph(effectiveTaskGraphDraftV2.graph_id, taskGraphPayload);
      setTaskGraphDraftV2(effectiveTaskGraphDraftV2);
      syncTaskGraphTopology(graphNodes, graphEdges);
      setConsolePayload(payload);
      if (taskLayer === "editor") {
        setEditorTaskGraphId(effectiveTaskGraphDraftV2.graph_id);
      } else {
        setSelectedTaskGraphId(effectiveTaskGraphDraftV2.graph_id);
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
  const updateTaskGraphContextPolicy = (patch: Partial<TaskGraphDraftV2["context_policy"]>) => {
    setTaskGraphDraftV2((current) => ({
      ...current,
      context_policy: {
        ...current.context_policy,
        ...patch,
      },
      metadata: {
        ...asRecord(current.metadata),
        context_policy: {
          ...asRecord(asRecord(current.metadata).context_policy),
          ...patch,
        },
      },
    }));
  };
  const updateTaskGraphWorkingMemoryPolicy = (patch: Partial<TaskGraphDraftV2["working_memory_policy"]>) => {
    setTaskGraphDraftV2((current) => ({
      ...current,
      working_memory_policy: {
        ...asRecord(current.working_memory_policy),
        ...patch,
      },
      metadata: {
        ...asRecord(current.metadata),
        working_memory_policy: {
          ...asRecord(asRecord(current.metadata).working_memory_policy),
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
  const graphContextTask = taskLayer === "editor" ? editorTask : selectedTask;
  const graphContextFamily = graphContextTask?.task_family || taskGraphDraftV2.task_family || domainIdToLegacyFamily(graphContextDomain?.domain_id || taskGraphDraftV2.domain_id || "", "");
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
  const editorIssueCount = editorGraphSpec.issues.length;
  const editorValid = editorGraphSpec.valid;
  const editorPublished = taskGraphDraftV2.publish_state === "published" || taskGraphDraftV2.publish_state === "run_bound";
  const topologyDirty = false;
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
      meta: editorTask ? (taskGraphDraftV2.title || editorSelectedTaskGraph?.title || editorTask.task_title) : "未打开任务",
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
          <p>{taskLayer === "editor" ? `${editorDomain?.title || "未选择任务域"} / ${taskGraphDraftV2.title || editorSelectedTaskGraph?.title || "任务图"}` : "任务域是第一管理边界；图编辑器只编辑当前任务域下的 Agent 拓扑。"}</p>
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
                    const nextGraph = (consolePayload?.task_graph_management?.task_graphs ?? []).find((item) => String(item.domain_id ?? "").trim() === domain.domain_id);
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
              saveTaskGraphStack={saveTaskGraphStack}
              saving={saving}
              selectedTaskGraph={activeTaskGraph}
              taskGraphMetadata={taskGraphDraftV2.metadata}
              selectedGraphSpec={editorGraphSpec}
              selectedNodeId={selectedGraphNodeId}
              selectedTask={selectedTask}
              setSelectedNodeId={setSelectedGraphNodeId}
              topologyDirty={topologyDirty}
            />
          ) : null}

          {taskLayer === "management" && selectedTask && taskConfigPanel === "runloop" ? (
            <TaskRunLoopWorkbenchPanel
              taskGraphMemorySharingPolicy={taskGraphDraftV2.context_policy.memory_sharing_policy}
              taskGraphSharedContextPolicy={taskGraphDraftV2.context_policy.shared_context_policy}
              executionDraft={executionDraft}
              memoryDraft={memoryDraft}
              nodeAssembly={null}
              saveTaskGraphStack={saveTaskGraphStack}
              saveTaskStack={saveTaskStack}
              saving={saving}
              selectedTaskGraph={activeTaskGraph}
              selectedTask={selectedTask}
              setTaskGraphMemorySharingPolicy={(value) => updateTaskGraphContextPolicy({ memory_sharing_policy: value })}
              setTaskGraphSharedContextPolicy={(value) => updateTaskGraphContextPolicy({ shared_context_policy: value })}
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
                emptyLabel={!editorDomain ? "先选择任务域" : editorDomainTasks.length ? "选择任务" : "当前任务域暂无任务"}
                label="任务"
                onChange={selectTaskForEditor}
                options={editorDomainTasks.map((task) => ({ value: task.task_id, label: task.task_title }))}
                placeholder="选择任务"
                value={editorTaskId}
              />
              <TaskGraphChromeSelect
                disabled={!editorTask}
                emptyLabel={!editorTask ? "先打开任务" : editorTaskGraphs.length ? "选择图草稿" : "暂无草稿"}
                label="图草稿"
                onChange={(nextValue) => {
                  setEditorTaskGraphId(nextValue);
                  setSelectedGraphNodeId("");
                  setSelectedGraphEdgeId("");
                  setLinkingFromNodeId("");
                }}
                options={editorTaskGraphs.map((task) => ({ value: task.graph_id, label: task.title }))}
                placeholder="选择图草稿"
                value={editorTaskGraphId}
              />
            </div>
            <div className="task-graph-editor-chrome__status task-graph-editor-chrome__status--context">
              <span className={topologyDirty ? "boundary-status boundary-status--warn" : "boundary-status"}>{topologyDirty ? "拓扑未同步" : "拓扑已同步"}</span>
              <span className="boundary-status">图编辑动作请在 Studio 顶栏执行</span>
            </div>
            <div className="task-graph-editor-chrome__actions task-graph-editor-chrome__actions--minimal">
              <ToolbarButton disabled={saving === "task-graph-create"} onClick={() => void createTaskGraphDraft()}><Network size={15} />新图草稿</ToolbarButton>
            </div>
          </section>

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
            updateTaskGraphContextPolicy={updateTaskGraphContextPolicy}
            updateTaskGraphDraft={updateTaskGraphDraft}
            updateTaskGraphEdge={updateTaskGraphEdge}
            updateTaskGraphMetadata={updateTaskGraphMetadata}
            updateTaskGraphNode={updateTaskGraphNode}
            updateTaskGraphPublishState={updateTaskGraphPublishState}
            updateTaskGraphRuntimePolicy={updateTaskGraphRuntimePolicy}
            updateTaskGraphWorkingMemoryPolicy={updateTaskGraphWorkingMemoryPolicy}
            orchestrationAgentCatalog={orchestrationAgentCatalog}
            onCreateProjectionFromPrompt={createProjectionFromNodePrompt}
            projectionCards={domainProjectionCards}
          />
        </section>
      ) : null}
    </div>
  );
}








