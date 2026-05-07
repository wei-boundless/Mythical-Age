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
  Pencil,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  CoordinationEditorWorkbench,
  coordinationSubtaskRefs,
  graphEdgeId,
  graphEdgeSource,
  graphEdgeTarget,
  graphNodeTaskId,
} from "@/components/workspace/views/task-system/CoordinationEditorWorkbench";
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
  getSoulProjectionCards,
  getTaskSystemNextIds,
  getTaskSystemOverview,
  upsertTaskSystemCommunicationProtocol,
  upsertTaskSystemCoordinationTask,
  upsertTaskSystemDomain,
  upsertTaskSystemEntryPolicy,
  upsertTaskSystemExecutionPolicy,
  upsertTaskSystemFlowContractBinding,
  upsertTaskSystemMemoryRequestProfile,
  upsertTaskSystemProjectionBinding,
  upsertTaskSystemSpecificRecord,
  upsertTaskSystemTopologyTemplate,
  upsertTaskWorkflow,
  type ConversationEntryPolicy,
  type CoordinationTask,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type SpecificTaskRecord,
  type TaskCommunicationProtocol,
  type TaskContractDescriptor,
  type TaskDomainRecord,
  type TaskExecutionPolicy,
  type TaskFlowContractBinding,
  type TaskMemoryRequestProfile,
  type TaskProjectionBinding,
  type TaskSystemOverview,
  type TaskWorkflowRecord,
  type TopologyTemplate,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

type TaskLayer = "domain" | "assembly" | "coordination" | "contracts";
type DomainPanel = "taskDetail" | "entry" | "eligibility";
type AssemblyPanel = "workflow" | "projection" | "flow" | "execution" | "memory";

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

function isInternalLongformItem(item: { metadata?: Record<string, unknown> } | null | undefined) {
  return Boolean(item && item.metadata && item.metadata.internal_stage === true);
}

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

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
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
    "short_story": "短篇写作",
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

const ASSEMBLY_LABELS: Record<AssemblyPanel, string> = {
  workflow: "执行流程",
  projection: "投影绑定",
  flow: "流程契约",
  execution: "执行策略",
  memory: "记忆请求",
};

const DEFAULT_PROJECTION_POLICY_CHOICES = ["workflow_compatible_or_task_default", "task_default"];
const PROJECTION_SELECTION_MODE_CHOICES = ["task_default"];
const FLOW_OVERRIDE_POLICY_CHOICES = ["task_default"];
const FLOW_FALLBACK_POLICY_CHOICES = ["fail_closed"];
const RUNTIME_SELECTION_POLICY_CHOICES = ["orchestration_default"];
const TASK_LEVEL_CHOICES = ["standard"];
const TASK_PRIVILEGE_CHOICES = ["bounded"];
const MEMORY_PRIORITY_CHOICES = ["normal"];
const MEMORY_WRITEBACK_POLICY_CHOICES = ["task_default"];
const AGENT_CATEGORY_CHOICES = ["main_agent", "system_management_agent", "worker_sub_agent"];
const COMMON_CONTRACT_CHOICES = ["UserMessage", "WorkspaceTaskInput", "AssistantFinalAnswer", "LightWebGameResult"];
const COORDINATION_MODE_CHOICES = ["review_merge", "pipeline", "parallel_review"];
const GRAPH_EDGE_MODE_CHOICES = ["structured_handoff", "review_feedback", "draft_request", "audit_request", "merge_signal"];
const CONTEXT_POLICY_CHOICES = ["explicit_refs_only", "shared_task_context"];
const MEMORY_SHARING_POLICY_CHOICES = ["isolated_by_default", "shared_readonly"];
const HANDOFF_POLICY_CHOICES = ["filtered_handoff", "direct_handoff"];
const CONFLICT_POLICY_CHOICES = ["coordinator_review", "majority_vote"];
const MERGE_POLICY_CHOICES = ["coordinator_final_merge", "ordered_append", "section_merge"];

function contractLabel(value: string, contracts: TaskContractDescriptor[] = []) {
  const contract = contracts.find((item) => item.contract_id === value);
  return contract?.title || displayId(value);
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
  const tasks = (consolePayload?.task_management.specific_task_records ?? []).filter((task) => !isInternalLongformItem(task));
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
  onChange,
  wide = false,
}: {
  label: string;
  value: string;
  options: string[];
  contracts: TaskContractDescriptor[];
  onChange: (value: string) => void;
  wide?: boolean;
}) {
  const resolvedOptions = uniqueStrings([value, ...options]);
  return (
    <Field label={label} wide={wide}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {resolvedOptions.map((item) => (
          <option key={item} value={item}>{contractLabel(item, contracts)}</option>
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
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedCoordinationId, setSelectedCoordinationId] = useState("");
  const [taskLayer, setTaskLayer] = useState<TaskLayer>("coordination");
  const [domainPanel, setDomainPanel] = useState<DomainPanel>("taskDetail");
  const [editingDomainName, setEditingDomainName] = useState(false);
  const [assemblyPanel, setAssemblyPanel] = useState<AssemblyPanel>("workflow");
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState("");
  const [selectedGraphEdgeId, setSelectedGraphEdgeId] = useState("");
  const [linkingFromNodeId, setLinkingFromNodeId] = useState("");

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

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [overview, projections] = await Promise.all([getTaskSystemOverview(), getSoulProjectionCards().catch(() => null)]);
      setConsolePayload(overview);
      setProjectionCatalog(projections);
      const nextDomains = buildDomains(overview);
      const preferredDomain = selectedDomainId || nextDomains[0]?.domain_id || "";
      const selectedDomain = nextDomains.find((item) => item.domain_id === preferredDomain) ?? nextDomains[0];
      setSelectedDomainId(selectedDomain?.domain_id ?? "");
      setSelectedTaskId((current) => current || selectedDomain?.tasks[0]?.task_id || overview.task_management.specific_task_records[0]?.task_id || "");
      setSelectedCoordinationId((current) => current || overview.coordination_management.coordination_tasks[0]?.coordination_task_id || "");
      setTaskLayer((current) => {
        if (current !== "coordination") return current;
        return overview.coordination_management.coordination_tasks.length ? "coordination" : "domain";
      });
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
  const activeFamily = selectedDomain?.task_family || "";
  const coordinationTasks = useMemo(
    () => allCoordinationTasks.filter((item) => !isInternalLongformItem(item) && coordinationFamily(item, tasks) === activeFamily),
    [activeFamily, allCoordinationTasks, tasks],
  );
  const topologyTemplates = useMemo(
    () => allTopologyTemplates.filter((item) => !isInternalLongformItem(item) && topologyFamily(item) === activeFamily),
    [activeFamily, allTopologyTemplates],
  );
  const communicationProtocols = useMemo(
    () => allCommunicationProtocols.filter((item) => !isInternalLongformItem(item) && protocolFamily(item, tasks) === activeFamily),
    [activeFamily, allCommunicationProtocols, tasks],
  );
  const selectedCoordination = coordinationTasks.find((item) => item.coordination_task_id === selectedCoordinationId) ?? coordinationTasks[0] ?? null;
  const selectedCoordinationGraphSpec = allCoordinationGraphSpecs.find((item) => item.coordination_task_id === selectedCoordination?.coordination_task_id) ?? null;
  const selectedTopology = topologyTemplates.find((item) => item.template_id === selectedCoordination?.topology_template_id);
  const selectedProtocol = protocolForCoordination(communicationProtocols, selectedCoordination, "");
  const taskModeOptions = useMemo(() => uniqueStrings(tasks.map((item) => item.task_mode)), [tasks]);
  const workflowOptions = useMemo(() => uniqueStrings(workflows.map((item) => item.workflow_id)), [workflows]);
  const commonContractOptions = useMemo(
    () => uniqueStrings([...COMMON_CONTRACT_CHOICES, ...contractCatalog.map((item) => item.contract_id)]),
    [contractCatalog],
  );
  const agentGroupOptions = useMemo(
    () => uniqueStrings([
      ...coordinationTasks.map((item) => item.agent_group_id),
    ]),
    [coordinationTasks],
  );
  const domainTaskOptions = useMemo(
    () => selectedDomainTasks.map((task) => ({ value: task.task_id, label: task.task_title })),
    [selectedDomainTasks],
  );
  const projectionCards = useMemo(() => projectionCatalog?.cards ?? [], [projectionCatalog]);
  const contractViews = useMemo<ContractView[]>(() => (
    contractCatalog.map((contract) => ({
      key: `${contract.contract_kind}:${contract.contract_id}`,
      title: contract.title || displayId(contract.contract_id),
      kind: CONTRACT_KIND_LABELS[contract.contract_kind] || contract.contract_kind,
      usage: contract.usage_refs?.slice(0, 3).join(" / ") || contract.summary || "未绑定",
      source: contract.source_refs?.slice(0, 3).join(" / ") || "任务系统",
      raw: contract.contract_id,
    }))
  ), [contractCatalog]);

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
    setCoordinationDraft(coordinationDraftFrom(selectedCoordination));
    const nextTopology = topologyDraftFrom(selectedTopology);
    const nextNodes = selectedCoordination?.graph_nodes?.length ? selectedCoordination.graph_nodes : (nextTopology.nodes ?? []);
    const nextEdges = selectedCoordination?.graph_edges?.length ? selectedCoordination.graph_edges : (nextTopology.edges ?? []);
    setTopologyDraft({
      ...nextTopology,
      nodes: nextNodes,
      edges: nextEdges,
      nodes_text: JSON.stringify(nextNodes, null, 2),
      edges_text: JSON.stringify(nextEdges, null, 2),
    });
    setProtocolDraft(protocolDraftFrom(selectedProtocol));
    setSelectedGraphNodeId(String((selectedCoordination?.graph_nodes ?? [])[0]?.node_id ?? ""));
    setSelectedGraphEdgeId("");
    setLinkingFromNodeId("");
  }, [selectedCoordination, selectedTopology, selectedProtocol]);

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
      setTaskLayer("domain");
      setDomainPanel("taskDetail");
      setTaskDraft(nextTask);
      setTaskPolicyText(JSON.stringify(nextTask.task_policy, null, 2));
      setWorkflowDraft({ ...emptyWorkflow(nextTask.task_mode), workflow_id: ids.workflow_id, title: `${ids.display_numbers.workflow} Workflow` });
      setProjectionDraft(emptyProjectionBinding(nextTask.task_id, ""));
      setFlowDraft(emptyFlowBinding(nextTask.task_id, ids.flow_id));
      setExecutionDraft(emptyExecutionPolicy(nextTask.task_id));
      setMemoryDraft(emptyMemoryProfile(nextTask.task_id));
      setNotice(`已生成特定任务草稿：${nextTask.task_id}`);
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
    setDomainDraft(draft);
    setSelectedDomainId(draft.domain_id);
    setSelectedTaskId("");
    setTaskLayer("domain");
    setDomainPanel("taskDetail");
    setEditingDomainName(true);
    setNotice("已生成任务域草稿，请填写名称后保存。");
  }

  function updateDomainTitle(title: string) {
    setDomainDraft((value) => {
      if (!value.domain_id.startsWith("domain.custom")) {
        return { ...value, title };
      }
      const slug = title
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_\-\u4e00-\u9fa5]+/g, "_")
        .replace(/^_+|_+$/g, "");
      const family = slug || value.task_family || "custom";
      return {
        ...value,
        title,
        task_family: family,
        domain_id: `domain.${family}`,
      };
    });
  }

  function addCoordinationNode() {
    const existingNodes = topologyDraft.nodes ?? [];
    const nextIndex = existingNodes.length + 1;
    const existingTaskIds = new Set(existingNodes.map((node) => graphNodeTaskId(node)).filter(Boolean));
    const nextTask = selectedDomainTasks.find((task) => !existingTaskIds.has(task.task_id));
    const nodeId = nextTask ? `subtask_${nextIndex}` : `agent_${nextIndex}`;
    setTopologyDraft((current) => {
      const node = {
        node_id: nodeId,
        node_type: nextTask ? "subtask" : "agent_role",
        task_id: nextTask?.task_id ?? "",
        task_title: nextTask?.task_title ?? "",
        task_family: selectedDomain?.task_family || "",
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
      task_family: task.task_family || selectedDomain?.task_family || "",
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
      reviewer: "审查节点",
      writer: "写作节点",
      acceptance: "验收节点",
      participant: "协作节点",
    };
    const node = {
      node_id: nodeId,
      node_type: "agent_role",
      task_id: "",
      task_title: "",
      task_family: selectedDomain?.task_family || "",
      agent_id: "",
      role,
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

  function addCoordinationSuccessorNode(fromNodeId: string) {
    const nextIndex = (topologyDraft.nodes?.length || 0) + 1;
    const nodeId = `agent_${nextIndex}`;
    const node = {
      node_id: nodeId,
      node_type: "agent_role",
      task_id: "",
      task_title: "",
      task_family: selectedDomain?.task_family || "",
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
    setSaving("coordination-create");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const coordination = emptyCoordination(
        ids.topology_template_id,
        `protocol.${ids.coordination_task_id.replace(/^coord\./, "")}`,
        selectedDomain?.task_family || "",
        selectedDomain?.domain_id || "",
      );
      coordination.coordination_task_id = ids.coordination_task_id;
      coordination.title = `${ids.display_numbers.coordination} 协调任务`;
      coordination.topology_template_id = ids.topology_template_id;
      coordination.task_family = selectedDomain?.task_family || "";
      coordination.domain_id = selectedDomain?.domain_id || "";
      coordination.metadata = {
        ...(coordination.metadata ?? {}),
        task_family: selectedDomain?.task_family || "",
        domain_id: selectedDomain?.domain_id || "",
      };
      const topology = emptyTopology();
      topology.template_id = ids.topology_template_id;
      topology.title = `${ids.display_numbers.topology} 拓扑`;
      topology.metadata = {
        ...(topology.metadata ?? {}),
        task_family: selectedDomain?.task_family || "",
        domain_id: selectedDomain?.domain_id || "",
      };
      const protocol = emptyProtocol();
      protocol.protocol_id = String(coordination.metadata?.protocol_id || protocol.protocol_id);
      protocol.title = `${ids.display_numbers.coordination} 协议`;
      protocol.metadata = {
        ...(protocol.metadata ?? {}),
        task_family: selectedDomain?.task_family || "",
        domain_id: selectedDomain?.domain_id || "",
      };
      setSelectedCoordinationId(coordination.coordination_task_id);
      setTaskLayer("coordination");
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
    if (!selectedCoordination) {
      setError("当前没有可复制的协调任务");
      return;
    }
    setSaving("coordination-duplicate");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const nextCoordinationId = ids.coordination_task_id;
      const nextTopologyId = ids.topology_template_id;
      const nextProtocolId = `protocol.${nextCoordinationId.replace(/^coord\./, "")}`;
      const nextTitle = `${selectedCoordination.title || ids.display_numbers.coordination} 副本`;
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
          task_family: selectedDomain?.task_family || coordinationDraft.task_family || "",
          domain_id: selectedDomain?.domain_id || coordinationDraft.domain_id || "",
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
          task_family: selectedDomain?.task_family || "",
          domain_id: selectedDomain?.domain_id || "",
        },
      };
      const nextProtocol: ProtocolDraft = {
        ...protocolDraft,
        protocol_id: nextProtocolId,
        title: `${protocolDraft.title || nextTitle} 副本`,
        enabled: false,
        metadata: {
          ...(protocolDraft.metadata ?? {}),
          task_family: selectedDomain?.task_family || "",
          domain_id: selectedDomain?.domain_id || "",
        },
      };
      setSelectedCoordinationId(nextCoordinationId);
      setTaskLayer("coordination");
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

  async function applyLongformNovelTemplate() {
    if ((selectedDomain?.task_family || "") !== "writing") {
      setError("长篇小说持续交付模板只能用于写作任务域");
      return;
    }
    setSaving("coordination-template-longform");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const coordinationId = ids.coordination_task_id;
      const topologyId = ids.topology_template_id;
      const protocolId = `protocol.${coordinationId.replace(/^coord\./, "")}`;
      const templateTasks = selectedDomainTasks.slice(0, 4);
      const nodes = templateTasks.map((task, index) => {
        const role = index === 0 ? "coordinator" : index === templateTasks.length - 1 ? "reviewer" : "participant";
        return {
          node_id: `node_${index + 1}`,
          node_type: "subtask",
          task_id: task.task_id,
          task_title: task.task_title,
          task_family: task.task_family,
          agent_id: index === 0 ? "agent:20" : `agent:${21 + index}`,
          role,
          label: task.task_title,
          title: task.task_title,
          message_type: role === "coordinator" ? "task_scope" : role === "reviewer" ? "review_feedback" : "structured_handoff",
        };
      });
      const edges = nodes.slice(0, -1).map((stage, index) => {
        const nextStage = nodes[index + 1];
        return {
          edge_id: `edge_${index + 1}`,
          from: String(stage.node_id || ""),
          to: String(nextStage.node_id || ""),
          source_node_id: String(stage.node_id || ""),
          target_node_id: String(nextStage.node_id || ""),
          mode: String(nextStage.message_type || "structured_handoff"),
          policy: "filtered_handoff",
        };
      });
      const coordination: CoordinationDraft = {
        ...emptyCoordination(topologyId, protocolId, "writing", selectedDomain?.domain_id || "domain.writing"),
        coordination_task_id: coordinationId,
        title: "写作任务协调草稿",
        coordination_mode: "pipeline",
        coordinator_agent_id: "agent:20",
        agent_group_id: "",
        participant_agent_ids: uniqueStrings(nodes.slice(1).map((node) => String(node.agent_id || ""))),
        shared_context_policy: "explicit_refs_only",
        memory_sharing_policy: "isolated_by_default",
        handoff_policy: "filtered_handoff",
        conflict_resolution_policy: "coordinator_review",
        output_merge_policy: "coordinator_final_merge",
        stop_conditions: [
          "subtasks_completed",
          "review_concluded",
          "coordinator_finalized",
        ],
        stop_conditions_text: [
          "subtasks_completed",
          "review_concluded",
          "coordinator_finalized",
        ].join("\n"),
        graph_nodes: nodes,
        graph_edges: edges,
        subtask_refs: uniqueStrings(nodes.map((node) => String(node.task_id || ""))),
        communication_modes: uniqueStrings(["structured_handoff", ...nodes.map((node) => String(node.message_type || ""))]),
        enabled: false,
        metadata: {
          managed_by: "task_domain_console",
          template_kind: "generic_writing_pipeline",
          protocol_id: protocolId,
          task_id: String(nodes[0]?.task_id || ""),
          task_family: "writing",
          domain_id: selectedDomain?.domain_id || "domain.writing",
          continuation_policy: {
            mode: "topology_driven",
            auto_continue: true,
            max_auto_steps: 24,
            retry_budget: { default: 1 },
          },
        },
      };
      const topology: TopologyDraft = {
        ...emptyTopology(),
        template_id: topologyId,
        title: "写作任务协调拓扑",
        nodes,
        edges,
        join_policy: "explicit_join",
        failure_policy: "fail_closed",
        terminal_policy: "coordinator_terminal",
        enabled: false,
        metadata: {
          managed_by: "task_domain_console",
          template_kind: "generic_writing_pipeline",
          task_family: "writing",
          domain_id: selectedDomain?.domain_id || "domain.writing",
        },
        nodes_text: JSON.stringify(nodes, null, 2),
        edges_text: JSON.stringify(edges, null, 2),
      };
      const protocol: ProtocolDraft = {
        ...emptyProtocol(),
        protocol_id: protocolId,
        title: "写作任务协调协议",
        message_types: coordination.communication_modes,
        message_types_text: coordination.communication_modes.join("\n"),
        ack_policy: "explicit_ack",
        timeout_policy: "fail_closed",
        error_signal_policy: "raise_to_coordinator",
        enabled: false,
        metadata: {
          managed_by: "task_domain_console",
          template_kind: "generic_writing_pipeline",
          task_family: "writing",
          domain_id: selectedDomain?.domain_id || "domain.writing",
        },
      };
      setSelectedCoordinationId(coordinationId);
      setTaskLayer("coordination");
      setCoordinationDraft(coordination);
      setTopologyDraft(topology);
      setProtocolDraft(protocol);
      setSelectedGraphNodeId(String(nodes[0]?.node_id || ""));
      setSelectedGraphEdgeId("");
      setLinkingFromNodeId("");
      setNotice("已生成通用写作协调任务草稿，可继续在拓扑图中调整后保存或发布。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "生成写作协调模板失败");
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
      const normalizedFamily = domainDraft.task_family || domainDraft.domain_id.replace(/^domain\./, "") || "custom";
      const payload = await upsertTaskSystemDomain(domainDraft.domain_id, {
        ...domainDraft,
        task_family: normalizedFamily,
        title: domainDraft.title.trim() || `${normalizedFamily}任务域`,
      });
      setConsolePayload(payload);
      setSelectedDomainId(domainDraft.domain_id);
      setEditingDomainName(false);
      setNotice("任务域已保存。");
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
        message_types: effectiveCoordinationDraft.communication_modes?.length ? effectiveCoordinationDraft.communication_modes : splitList(effectiveProtocolDraft.message_types_text),
        payload_contracts: splitList(effectiveProtocolDraft.payload_contracts_text),
        signal_rules: splitList(effectiveProtocolDraft.signal_rules_text),
        handoff_rules: splitList(effectiveProtocolDraft.handoff_rules_text),
        metadata: {
          ...(effectiveProtocolDraft.metadata ?? {}),
          task_family: selectedDomain?.task_family || "",
          domain_id: selectedDomain?.domain_id || "",
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
          task_family: selectedDomain?.task_family || "",
          domain_id: selectedDomain?.domain_id || "",
        },
      });
      const payload = await upsertTaskSystemCoordinationTask(effectiveCoordinationDraft.coordination_task_id, {
        ...effectiveCoordinationDraft,
        task_family: selectedDomain?.task_family || effectiveCoordinationDraft.task_family || "",
        domain_id: selectedDomain?.domain_id || effectiveCoordinationDraft.domain_id || "",
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
          task_family: selectedDomain?.task_family || "",
          domain_id: selectedDomain?.domain_id || "",
        },
      });
      setCoordinationDraft(effectiveCoordinationDraft);
      setTopologyDraft(effectiveTopologyDraft);
      setProtocolDraft(effectiveProtocolDraft);
      setConsolePayload(payload);
      setSelectedCoordinationId(effectiveCoordinationDraft.coordination_task_id);
      setNotice(nextPublished === true ? "协调任务、拓扑和协议已发布。" : "协调任务、拓扑和协议已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存协调任务失败");
    } finally {
      setSaving("");
    }
  }

  const taskPolicyError = jsonError(taskPolicyText, "任务策略", "object");
  const activeGraphNodes = topologyDraft.nodes ?? [];
  const activeGraphEdges = topologyDraft.edges ?? [];
  const selectedGraphNode = activeGraphNodes.find((node) => String(node.node_id ?? "") === selectedGraphNodeId) ?? null;
  const selectedGraphEdge = activeGraphEdges.find((edge, index) => graphEdgeId(edge, index) === selectedGraphEdgeId) ?? null;
  const boundCoordinationTaskIds = new Set(activeGraphNodes.map((node) => graphNodeTaskId(node)).filter(Boolean));
  const editorIssueCount = selectedCoordinationGraphSpec?.issues?.length ?? 0;
  const editorValid = selectedCoordinationGraphSpec?.valid !== false;
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
    { label: "输出契约", value: contractLabel(taskDraft.output_contract_id || workflowDraft.output_contract_id || "", contractCatalog) },
  ];
  const taskLayerItems: Array<LayerNavItem<TaskLayer>> = [
    {
      value: "domain",
      label: "任务域",
      meta: selectedTaskDomain?.title || selectedDomain?.title || "未选择任务域",
      detail: "管理域定义、入口规则与特定任务清单",
    },
    {
      value: "assembly",
      label: "任务装配",
      meta: taskDraft.task_title || selectedTask?.task_title || "未选择任务",
      detail: "编辑单任务的流程、投影、执行与记忆配置",
    },
    {
      value: "coordination",
      label: "协调任务",
      meta: coordinationDraft.title || selectedCoordination?.title || "当前域暂无协调任务",
      detail: "维护多 Agent 拓扑、通信协议与发布状态",
    },
    {
      value: "contracts",
      label: "契约目录",
      meta: `${contractViews.length} 项契约`,
      detail: "查看任务系统中的输入、输出与载荷契约",
    },
  ];
  const domainPanelItems: Array<LayerNavItem<DomainPanel>> = [
    {
      value: "taskDetail",
      label: "任务定义",
      meta: taskDraft.task_title || selectedTask?.task_title || "未选择特定任务",
      detail: "编辑任务描述、模式与默认装配入口",
    },
    {
      value: "entry",
      label: "入口规则",
      meta: entryDraft.title || "主会话入口",
      detail: "定义主会话如何进入当前任务域",
    },
    {
      value: "eligibility",
      label: "承接要求",
      meta: displayId(taskDraft.task_mode || selectedTask?.task_mode || ""),
      detail: "查看任务所需的 Agent、权限与输出口径",
    },
  ];
  const assemblyPanelItems: Array<LayerNavItem<AssemblyPanel>> = [
    {
      value: "workflow",
      label: "执行流程",
      meta: workflowDraft.title || "未命名流程",
      detail: "配置任务步骤、停机条件与提示词",
    },
    {
      value: "projection",
      label: "投影绑定",
      meta: projectionDraft.default_projection_id ? projectionLabel(projectionDraft.default_projection_id, projectionCards) : "未设置默认投影",
      detail: "限定任务可用投影与默认人格入口",
    },
    {
      value: "flow",
      label: "流程契约",
      meta: flowDraft.flow_contract_id || "未绑定流程契约",
      detail: "约束任务在编排链路中的流转和回退规则",
    },
    {
      value: "execution",
      label: "执行策略",
      meta: displayId(executionDraft.runtime_agent_selection_policy || "orchestration_default"),
      detail: "定义执行权限、Agent 类别与运行策略",
    },
    {
      value: "memory",
      label: "记忆请求",
      meta: displayId(memoryDraft.memory_priority || "normal"),
      detail: "控制任务请求哪些记忆层与写回策略",
    },
  ];

  return (
    <div className="workspace-view boundary-console task-system-boundary">
      <header className="boundary-hero">
        <div>
          <span>任务边界工作台</span>
          <h2>任务系统工作台</h2>
          <p>任务域、特定任务、单任务装配、协调任务</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton onClick={() => void load()}><RefreshCw size={15} />刷新</ToolbarButton>
          <ToolbarButton disabled={saving === "task-create"} onClick={() => void createTaskDraft()}><Plus size={15} />新特定任务</ToolbarButton>
          <ToolbarButton disabled={saving === "coordination-create"} onClick={() => void createCoordinationDraft()}><Network size={15} />新协调任务</ToolbarButton>
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}
      {notice ? <div className="boundary-notice"><CheckCircle2 size={16} />{notice}</div> : null}

      <section className="boundary-workbench">
        <aside className="boundary-rail">
          <div className="boundary-rail__head">
            <strong>任务域</strong>
            <div className="boundary-inline-actions">
            <span>{visibleDomains.length}</span>
              <button className="boundary-icon-button" onClick={createDomainDraft} type="button" aria-label="新增任务域">
                <Plus size={14} />
              </button>
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
                    setSelectedTaskId(domain.tasks[0]?.task_id || selectedTaskId);
                    const domainFamily = domain.task_family;
                    const nextCoordination = (consolePayload?.coordination_management.coordination_tasks ?? []).find((item) => coordinationFamily(item, tasks) === domainFamily);
                    setSelectedCoordinationId(nextCoordination?.coordination_task_id || "");
                    setDomainPanel("taskDetail");
                    setEditingDomainName(false);
                  }}
                  type="button"
                >
                  <strong>{domain.title}</strong>
                  <small>{domain.tasks.length} 个任务</small>
                </button>
                {active ? (
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
          <section className="task-system-switchboard">
            <div className="task-system-switchboard__head">
              <div className="task-system-switchboard__copy">
                <span>工作台层级</span>
                <strong>{taskLayerItems.find((item) => item.value === taskLayer)?.label || "任务系统"}</strong>
                <p>{taskLayerItems.find((item) => item.value === taskLayer)?.detail || "选择当前要编辑的任务系统层级。"}</p>
              </div>
            </div>
            <LayerNav ariaLabel="任务系统层级" items={taskLayerItems} value={taskLayer} onChange={setTaskLayer} />
          </section>

          {taskLayer === "domain" ? (
            <section className="boundary-layer-grid">
              <div className="boundary-directory">
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
                <div className="task-system-section-switch">
                  <div className="task-system-section-switch__head">
                    <span>域内页面</span>
                    <strong>{domainPanelItems.find((item) => item.value === domainPanel)?.meta || "未选择页面"}</strong>
                  </div>
                  <LayerNav ariaLabel="任务域页面" items={domainPanelItems} value={domainPanel} onChange={setDomainPanel} variant="secondary" />
                </div>
                <div className="boundary-list">
                  {selectedDomain?.tasks.map((task) => (
                    <button className={task.task_id === selectedTaskId ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"} key={task.task_id} onClick={() => { setSelectedTaskId(task.task_id); setDomainPanel("taskDetail"); }} type="button">
                      <strong>{task.task_title}</strong>
                    </button>
                  ))}
                  {!selectedDomain?.tasks.length ? <div className="boundary-empty">当前任务域暂无特定任务。</div> : null}
                </div>
              </div>
              <div className="boundary-editor">
                <section className="task-system-context-bar">
                  <div className="task-system-context-bar__copy">
                    <span>{selectedDomain?.title || "当前任务域"}</span>
                    <strong>{domainPanelItems.find((item) => item.value === domainPanel)?.label || "任务定义"}</strong>
                    <p>{domainPanelItems.find((item) => item.value === domainPanel)?.detail || "在当前任务域内管理相关配置。"}</p>
                  </div>
                </section>
                {domainPanel === "entry" ? (
                  <section className="boundary-card">
                    <header><strong>入口规则</strong><ToolbarButton disabled={saving === "entry"} onClick={() => void saveEntry()} variant="primary"><Save size={15} />保存入口</ToolbarButton></header>
                    <div className="boundary-form">
                      <Field label="标题"><input value={entryDraft.title} onChange={(event) => setEntryDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                      <Field label="入口规则"><input value={entryDraft.conversation_entry_policy} onChange={(event) => setEntryDraft((value) => ({ ...value, conversation_entry_policy: event.target.value }))} /></Field>
                      <Field label="默认执行流程"><input value={entryDraft.default_workflow_id} onChange={(event) => setEntryDraft((value) => ({ ...value, default_workflow_id: event.target.value }))} /></Field>
                      <ProjectionSelectField cards={projectionCards} label="默认投影" onChange={(value) => setEntryDraft((current) => ({ ...current, default_projection_id: value }))} value={entryDraft.default_projection_id} />
                      <label className="boundary-check"><input checked={entryDraft.enabled} onChange={(event) => setEntryDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用</label>
                      <SystemFields>
                        <Field label="入口档案 ID"><input value={entryDraft.profile_id} onChange={(event) => setEntryDraft((value) => ({ ...value, profile_id: event.target.value }))} /></Field>
                        <ContractSelectField contracts={contractCatalog} label="输入契约" onChange={(value) => setEntryDraft((current) => ({ ...current, input_contract_id: value }))} options={commonContractOptions} value={entryDraft.input_contract_id} />
                        <ContractSelectField contracts={contractCatalog} label="输出契约" onChange={(value) => setEntryDraft((current) => ({ ...current, output_contract_id: value }))} options={commonContractOptions} value={entryDraft.output_contract_id} />
                      </SystemFields>
                    </div>
                  </section>
                ) : null}
                {domainPanel === "taskDetail" ? (
                  <section className="boundary-card">
                    <header>
                      <strong>{taskDraft.task_title || "特定任务定义"}</strong>
                      <div className="boundary-actions">
                        <ToolbarButton onClick={() => sendTaskToChat(selectedTask, selectedTaskDomain)}>带入主会话</ToolbarButton>
                        <ToolbarButton onClick={() => setTaskLayer("assembly")}>进入装配</ToolbarButton>
                        {selectedTask ? (
                          <ToolbarButton disabled={saving === "task-delete"} onClick={() => void deleteTaskRecord(selectedTask)}>
                            <Trash2 size={15} />删除任务
                          </ToolbarButton>
                        ) : null}
                        <ToolbarButton disabled={saving === "task-stack"} onClick={() => void saveTaskStack()} variant="primary"><Save size={15} />保存任务</ToolbarButton>
                      </div>
                    </header>
                    <div className="boundary-form">
                      <Field label="任务标题"><input value={taskDraft.task_title} onChange={(event) => setTaskDraft((value) => ({ ...value, task_title: event.target.value }))} /></Field>
                      <SelectField label="所属任务域" onChange={(value) => setTaskDraft((current) => ({ ...current, task_family: value }))} options={domains.map((domain) => domain.task_family)} value={taskDraft.task_family} />
                      <SelectField label="任务模式" onChange={(value) => setTaskDraft((current) => ({ ...current, task_mode: value }))} options={taskModeOptions} value={taskDraft.task_mode} />
                      <Field label="验收档案"><input value={taskDraft.acceptance_profile_id} onChange={(event) => setTaskDraft((value) => ({ ...value, acceptance_profile_id: event.target.value }))} /></Field>
                      <Field label="任务描述" wide><textarea value={taskDraft.description} onChange={(event) => setTaskDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                      <label className="boundary-check"><input checked={taskDraft.enabled} onChange={(event) => setTaskDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用任务</label>
                      <SystemFields>
                        <Field label="任务 ID"><input value={taskDraft.task_id} onChange={(event) => setTaskDraft((value) => ({ ...value, task_id: event.target.value }))} /></Field>
                        <ContractSelectField contracts={contractCatalog} label="输入契约" onChange={(value) => setTaskDraft((current) => ({ ...current, input_contract_id: value }))} options={commonContractOptions} value={taskDraft.input_contract_id} />
                        <ContractSelectField contracts={contractCatalog} label="输出契约" onChange={(value) => setTaskDraft((current) => ({ ...current, output_contract_id: value }))} options={commonContractOptions} value={taskDraft.output_contract_id} />
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
                ) : null}
                {domainPanel === "eligibility" ? (
                  <section className="boundary-card">
                    <header><strong>承接要求</strong></header>
                    <div className="boundary-kv">
                      {eligibilityRows.map((row) => <p key={row.label}><span>{row.label}</span><strong>{row.value}</strong></p>)}
                    </div>
                  </section>
                ) : null}
              </div>
            </section>
          ) : null}

          {taskLayer === "assembly" ? (
            <section className="boundary-assembly-layout">
              <aside className="boundary-directory boundary-assembly-directory">
                <div className="boundary-panel-head">
                  <strong>{selectedTaskDomain?.title || "任务域"}</strong>
                  <span>{selectedDomainTasks.length}</span>
                </div>
                <div className="boundary-current-path">
                  <span>当前装配任务</span>
                  <strong>{taskDraft.task_title || selectedTask?.task_title || "未选择任务"}</strong>
                </div>
                <div className="boundary-list boundary-list--scroll">
                  {selectedDomainTasks.map((task) => (
                    <button
                      className={task.task_id === selectedTaskId ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"}
                      key={task.task_id}
                      onClick={() => setSelectedTaskId(task.task_id)}
                      type="button"
                    >
                      <strong>{task.task_title}</strong>
                    </button>
                  ))}
                  {!selectedDomainTasks.length ? <div className="boundary-empty">当前任务域暂无可装配任务。</div> : null}
                </div>
              </aside>
              <div className="boundary-layer-stack">
                <div className="boundary-card boundary-card--summary">
                  <header>
                    <div className="boundary-identity-stack">
                      <span>{selectedTaskDomain?.title || "任务域"} / 单任务装配</span>
                      <strong>{taskDraft.task_title || "任务装配"}</strong>
                      <small>{displayId(taskDraft.task_mode)}</small>
                    </div>
                    <ToolbarButton disabled={saving === "task-stack"} onClick={() => void saveTaskStack()} variant="primary"><Save size={15} />保存装配</ToolbarButton>
                  </header>
                  <div className="boundary-metric-grid">
                    {taskReadiness.map((item) => <ReadinessCard key={item.label} {...item} value={displayId(item.value)} />)}
                  </div>
                </div>
                <section className="boundary-card boundary-card--editor">
                  <div className="task-system-section-switch">
                    <div className="task-system-section-switch__head">
                      <span>装配页面</span>
                      <strong>{assemblyPanelItems.find((item) => item.value === assemblyPanel)?.meta || "未选择页面"}</strong>
                    </div>
                    <LayerNav ariaLabel="任务装配页面" items={assemblyPanelItems} value={assemblyPanel} onChange={setAssemblyPanel} variant="secondary" />
                  </div>
                  <header className="boundary-editor-title">
                    <div className="task-system-context-bar__copy">
                      <span>{selectedTaskDomain?.title || "当前任务域"} / 单任务装配</span>
                      <strong>{ASSEMBLY_LABELS[assemblyPanel]}</strong>
                      <p>{assemblyPanelItems.find((item) => item.value === assemblyPanel)?.detail || "编辑当前任务的装配配置。"}</p>
                    </div>
                  </header>
                  {assemblyPanel === "workflow" ? (
                    <div className="boundary-form">
                      <Field label="标题"><input value={workflowDraft.title} onChange={(event) => setWorkflowDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                      <SelectField label="任务模式" onChange={(value) => setWorkflowDraft((current) => ({ ...current, task_mode: value }))} options={taskModeOptions} value={workflowDraft.task_mode} />
                      <Field label="步骤" wide><textarea value={workflowDraft.steps_text} onChange={(event) => setWorkflowDraft((value) => ({ ...value, steps_text: event.target.value }))} /></Field>
                      <Field label="停止条件" wide><textarea value={workflowDraft.stop_conditions_text} onChange={(event) => setWorkflowDraft((value) => ({ ...value, stop_conditions_text: event.target.value }))} /></Field>
                      <Field label="证据要求" wide><textarea value={workflowDraft.required_evidence_refs_text} onChange={(event) => setWorkflowDraft((value) => ({ ...value, required_evidence_refs_text: event.target.value }))} /></Field>
                      <Field label="提示词" wide><textarea value={workflowDraft.prompt} onChange={(event) => setWorkflowDraft((value) => ({ ...value, prompt: event.target.value }))} /></Field>
                      <SystemFields>
                        <Field label="执行流程 ID"><input value={workflowDraft.workflow_id} onChange={(event) => setWorkflowDraft((value) => ({ ...value, workflow_id: event.target.value }))} /></Field>
                        <ContractSelectField contracts={contractCatalog} label="输出契约" onChange={(value) => setWorkflowDraft((current) => ({ ...current, output_contract_id: value }))} options={commonContractOptions} value={workflowDraft.output_contract_id} />
                        <Field label="可见技能" wide><textarea value={workflowDraft.visible_skill_ids_text} onChange={(event) => setWorkflowDraft((value) => ({ ...value, visible_skill_ids_text: event.target.value }))} /></Field>
                        <ProjectionMultiSelectField cards={projectionCards} label="兼容投影" onChange={(value) => setWorkflowDraft((current) => ({ ...current, compatible_projection_ids_text: value.join("\n") }))} value={splitList(workflowDraft.compatible_projection_ids_text)} wide />
                        <Field label="输入边界"><input value={workflowDraft.input_boundary} onChange={(event) => setWorkflowDraft((value) => ({ ...value, input_boundary: event.target.value }))} /></Field>
                        <Field label="输出边界"><input value={workflowDraft.output_boundary} onChange={(event) => setWorkflowDraft((value) => ({ ...value, output_boundary: event.target.value }))} /></Field>
                      </SystemFields>
                    </div>
                  ) : null}
                  {assemblyPanel === "projection" ? (
                    <div className="boundary-form">
                      <SelectField label="选择模式" onChange={(value) => setProjectionDraft((current) => ({ ...current, projection_selection_mode: value }))} options={PROJECTION_SELECTION_MODE_CHOICES} value={projectionDraft.projection_selection_mode} />
                      <ProjectionSelectField cards={projectionCards} label="默认投影" onChange={(value) => setProjectionDraft((current) => ({ ...current, default_projection_id: value, allowed_projection_ids: value ? uniqueStrings([value, ...(current.allowed_projection_ids ?? [])]) : current.allowed_projection_ids }))} value={projectionDraft.default_projection_id} />
                      <Field label="备注" wide><textarea value={projectionDraft.notes} onChange={(event) => setProjectionDraft((value) => ({ ...value, notes: event.target.value }))} /></Field>
                      <label className="boundary-check"><input checked={projectionDraft.projection_required} onChange={(event) => setProjectionDraft((value) => ({ ...value, projection_required: event.target.checked }))} type="checkbox" />投影必需</label>
                      <SystemFields>
                        <ProjectionMultiSelectField cards={projectionCards} label="允许投影" onChange={(value) => setProjectionDraft((current) => ({ ...current, allowed_projection_ids: value }))} value={projectionDraft.allowed_projection_ids ?? []} wide />
                      </SystemFields>
                    </div>
                  ) : null}
                  {assemblyPanel === "flow" ? (
                    <div className="boundary-form">
                      <FlowContractSelect label="流程契约" flows={taskFlowDefinitions} onChange={(value) => setFlowDraft((current) => ({ ...current, flow_contract_id: value }))} value={flowDraft.flow_contract_id} />
                      <SelectField label="覆盖策略" onChange={(value) => setFlowDraft((current) => ({ ...current, override_policy: value }))} options={FLOW_OVERRIDE_POLICY_CHOICES} value={flowDraft.override_policy} />
                      <SelectField label="回退策略" onChange={(value) => setFlowDraft((current) => ({ ...current, fallback_policy: value }))} options={FLOW_FALLBACK_POLICY_CHOICES} value={flowDraft.fallback_policy} />
                      <SystemFields>
                        <Field label="验证门"><input value={flowDraft.verification_gate_profile} onChange={(event) => setFlowDraft((value) => ({ ...value, verification_gate_profile: event.target.value }))} /></Field>
                      </SystemFields>
                    </div>
                  ) : null}
                  {assemblyPanel === "execution" ? (
                    <div className="boundary-form">
                      <ReadinessCard label="运行形态" value="单任务运行" ready />
                      <SelectField label="运行选择策略" onChange={(value) => setExecutionDraft((current) => ({ ...current, runtime_agent_selection_policy: value }))} options={RUNTIME_SELECTION_POLICY_CHOICES} value={executionDraft.runtime_agent_selection_policy || ""} />
                      <SelectField label="任务等级" onChange={(value) => setExecutionDraft((current) => ({ ...current, task_level: value }))} options={TASK_LEVEL_CHOICES} value={executionDraft.task_level || ""} />
                      <SelectField label="任务权限" onChange={(value) => setExecutionDraft((current) => ({ ...current, task_privilege: value }))} options={TASK_PRIVILEGE_CHOICES} value={executionDraft.task_privilege || ""} />
                      <MultiSelectField label="允许 Agent 类别" onChange={(value) => setExecutionDraft((current) => ({ ...current, allowed_agent_categories: value }))} options={AGENT_CATEGORY_CHOICES} value={executionDraft.allowed_agent_categories ?? []} wide />
                      <label className="boundary-check"><input checked={executionDraft.allow_worker_agent_spawn} onChange={(event) => setExecutionDraft((value) => ({ ...value, allow_worker_agent_spawn: event.target.checked }))} type="checkbox" />允许临时子 Agent</label>
                      <SystemFields>
                        <Field label="子 Agent 蓝图"><input value={executionDraft.worker_agent_blueprint_id} onChange={(event) => setExecutionDraft((value) => ({ ...value, worker_agent_blueprint_id: event.target.value }))} /></Field>
                        <Field label="子 Agent 命名规则"><input value={executionDraft.worker_agent_naming_rule} onChange={(event) => setExecutionDraft((value) => ({ ...value, worker_agent_naming_rule: event.target.value }))} /></Field>
                        <Field label="备注" wide><textarea value={executionDraft.notes} onChange={(event) => setExecutionDraft((value) => ({ ...value, notes: event.target.value }))} /></Field>
                      </SystemFields>
                    </div>
                  ) : null}
                  {assemblyPanel === "memory" ? (
                    <div className="boundary-form">
                      <Field label="记忆层" wide><textarea value={listText(memoryDraft.requested_memory_layers)} onChange={(event) => setMemoryDraft((value) => ({ ...value, requested_memory_layers: splitList(event.target.value) }))} /></Field>
                      <Field label="记忆主题" wide><textarea value={listText(memoryDraft.requested_topics)} onChange={(event) => setMemoryDraft((value) => ({ ...value, requested_topics: splitList(event.target.value) }))} /></Field>
                      <SelectField label="优先级" onChange={(value) => setMemoryDraft((current) => ({ ...current, memory_priority: value }))} options={MEMORY_PRIORITY_CHOICES} value={memoryDraft.memory_priority} />
                      <SelectField label="写回策略" onChange={(value) => setMemoryDraft((current) => ({ ...current, writeback_policy: value }))} options={MEMORY_WRITEBACK_POLICY_CHOICES} value={memoryDraft.writeback_policy} />
                      <Field label="范围提示"><input value={memoryDraft.memory_scope_hint} onChange={(event) => setMemoryDraft((value) => ({ ...value, memory_scope_hint: event.target.value }))} /></Field>
                      <label className="boundary-check"><input checked={memoryDraft.allow_long_term_memory} onChange={(event) => setMemoryDraft((value) => ({ ...value, allow_long_term_memory: event.target.checked }))} type="checkbox" />允许长期记忆</label>
                    </div>
                  ) : null}
                </section>
              </div>
            </section>
          ) : null}

          {taskLayer === "coordination" ? (
            <CoordinationEditorWorkbench
              activeGraphEdges={activeGraphEdges}
              activeGraphNodes={activeGraphNodes}
              addCoordinationEdge={addCoordinationEdge}
              addCoordinationNode={addCoordinationNode}
              addCoordinationRoleNode={addCoordinationRoleNode}
              addCoordinationSuccessorNode={addCoordinationSuccessorNode}
              addCoordinationTaskNode={addCoordinationTaskNode}
              agentGroupOptions={agentGroupOptions}
              applyLongformNovelTemplate={applyLongformNovelTemplate}
              boundCoordinationTaskIds={boundCoordinationTaskIds}
              connectSelectedNodeTo={connectSelectedNodeTo}
              coordinationDraft={coordinationDraft}
              coordinationTasks={coordinationTasks}
              cycleCoordinationEdgeMode={cycleCoordinationEdgeMode}
              cycleCoordinationNodeRole={cycleCoordinationNodeRole}
              domainTaskOptions={domainTaskOptions}
              duplicateCoordinationDraft={duplicateCoordinationDraft}
              editorIssueCount={editorIssueCount}
              editorPublished={editorPublished}
              editorValid={editorValid}
              handleTopologyNodeClick={handleTopologyNodeClick}
              linkingFromNodeId={linkingFromNodeId}
              protocolDraft={protocolDraft}
              removeCoordinationEdge={removeCoordinationEdge}
              removeCoordinationNode={removeCoordinationNode}
              reverseCoordinationEdge={reverseCoordinationEdge}
              saveCoordinationStack={saveCoordinationStack}
              saveTopologyDraftIntoCoordination={saveTopologyDraftIntoCoordination}
              saving={saving}
              selectedCoordination={selectedCoordination}
              selectedCoordinationGraphSpec={selectedCoordinationGraphSpec}
              selectedCoordinationId={selectedCoordinationId}
              selectedDomain={selectedDomain}
              selectedDomainTasks={selectedDomainTasks}
              selectedGraphEdge={selectedGraphEdge}
              selectedGraphEdgeId={selectedGraphEdgeId}
              selectedGraphNode={selectedGraphNode}
              selectedGraphNodeId={selectedGraphNodeId}
              sendCoordinationToChat={sendCoordinationToChat}
              setCoordinationDraft={setCoordinationDraft}
              setCoordinationPublished={setCoordinationPublished}
              setLinkingFromNodeId={setLinkingFromNodeId}
              setProtocolDraft={setProtocolDraft}
              setSelectedCoordinationId={setSelectedCoordinationId}
              setSelectedGraphEdgeId={setSelectedGraphEdgeId}
              setSelectedGraphNodeId={setSelectedGraphNodeId}
              setTopologyDraft={setTopologyDraft}
              topologyDirty={topologyDirty}
              topologyDraft={topologyDraft}
              updateCoordinationEdge={updateCoordinationEdge}
              updateCoordinationNode={updateCoordinationNode}
            />
          ) : null}

          {taskLayer === "contracts" ? (
            <section className="boundary-layer-grid boundary-layer-grid--wide">
              <div className="boundary-card">
                <header><strong>契约总览</strong></header>
                <div className="boundary-task-table">
                  {contractViews.map((contract) => (
                    <article key={contract.key}>
                      <strong>{contract.title}</strong>
                      <span>{contract.kind}</span>
                      <small>{contract.usage}</small>
                    </article>
                  ))}
                  {!contractViews.length ? <div className="boundary-empty">当前没有可管理的契约对象。</div> : null}
                </div>
              </div>
              <aside className="boundary-card">
                <header><strong>当前契约</strong></header>
                <div className="boundary-kv">
                  {contractViews[0] ? (
                    <>
                      <p><span>中文名</span><strong>{contractViews[0].title}</strong></p>
                      <p><span>契约类型</span><strong>{contractViews[0].kind}</strong></p>
                      <p><span>使用位置</span><strong>{contractViews[0].usage}</strong></p>
                      <p><span>来源对象</span><strong>{contractViews[0].source}</strong></p>
                    </>
                  ) : (
                    <p><span>状态</span><strong>当前没有契约对象</strong></p>
                  )}
                </div>
                <SystemFields>
                  {contractViews[0] ? (
                    <Field label="原始契约名">
                      <input readOnly value={contractViews[0].raw} />
                    </Field>
                  ) : null}
                </SystemFields>
              </aside>
              <aside className="boundary-card">
                <header><strong>管理口径</strong></header>
                <div className="boundary-kv">
                  <p><span>流程契约</span><strong>来自任务流定义</strong></p>
                  <p><span>输入输出契约</span><strong>来自入口、任务、工作流</strong></p>
                  <p><span>通信载荷契约</span><strong>来自通信协议</strong></p>
                  <p><span>当前状态</span><strong>已进入任务系统正式目录，不再是黑箱</strong></p>
                </div>
              </aside>
            </section>
          ) : null}
        </main>
      </section>
    </div>
  );
}
