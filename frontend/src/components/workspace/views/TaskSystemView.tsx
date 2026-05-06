"use client";

import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  GitBranch,
  Loader2,
  Network,
  Plus,
  RefreshCw,
  Save,
  Pencil,
  ShieldCheck,
  Trash2,
  Workflow,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

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
  type CoordinationGraphSpec,
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
type CoordinationPanel = "definition" | "topology" | "protocol";

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
    "longform_novel_project": "长篇项目立项",
    "novel_bible_build": "小说设定总纲",
    "volume_planning": "卷规划",
    "chapter_planning": "章节规划",
    "chapter_drafting": "章节正文",
    "chapter_revision": "章节审校",
    "continuity_audit": "连续性审计",
    "final_compilation": "阶段编纂",
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

const COORDINATION_LABELS: Record<CoordinationPanel, string> = {
  definition: "协调定义",
  topology: "拓扑图",
  protocol: "通信协议",
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

function optionLabel(value: string) {
  return displayId(value);
}

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

function ToolbarButton({
  children,
  onClick,
  disabled,
  variant = "ghost",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "ghost" | "primary";
}) {
  return (
    <button className={`boundary-button boundary-button--${variant}`} disabled={disabled} onClick={onClick} type="button">
      {children}
    </button>
  );
}

function Field({ label, children, wide = false }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={wide ? "boundary-field boundary-field--wide" : "boundary-field"}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
  wide = false,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  wide?: boolean;
}) {
  const resolvedOptions = uniqueStrings([value, ...options]);
  return (
    <Field label={label} wide={wide}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {resolvedOptions.map((item) => (
          <option key={item} value={item}>{optionLabel(item)}</option>
        ))}
      </select>
    </Field>
  );
}

function DomainTaskSelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  const resolvedOptions = value && !options.some((item) => item.value === value)
    ? [{ value, label: displayId(value) }, ...options]
    : options;
  return (
    <Field label={label}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">不绑定</option>
        {resolvedOptions.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
    </Field>
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

function MultiSelectField({
  label,
  value,
  options,
  onChange,
  wide = false,
}: {
  label: string;
  value: string[];
  options: string[];
  onChange: (value: string[]) => void;
  wide?: boolean;
}) {
  const selected = new Set(value ?? []);
  return (
    <Field label={label} wide={wide}>
      <div className="boundary-choice-grid">
        {uniqueStrings([...options, ...(value ?? [])]).map((item) => (
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
            {optionLabel(item)}
          </button>
        ))}
      </div>
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

function CoordinationGraph({
  nodes,
  edges,
  messages,
  tasks = [],
  selectedNodeId = "",
  selectedEdgeId = "",
  onSelectNode,
  onSelectEdge,
}: {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  messages: string[];
  tasks?: SpecificTaskRecord[];
  selectedNodeId?: string;
  selectedEdgeId?: string;
  onSelectNode?: (nodeId: string) => void;
  onSelectEdge?: (edgeId: string) => void;
}) {
  const safeNodes = nodes.length
    ? nodes
    : [{ node_id: "coordinator", role: "coordinator", agent_id: "agent:0" }];
  const ids = safeNodes.map((node, index) => text(node.node_id || node.role || node.agent_id, `node_${index + 1}`));
  const positions = ids.map((id, index) => {
    if (ids.length === 1) return { id, x: 50, y: 45 };
    const angle = (Math.PI * 2 * index) / ids.length - Math.PI / 2;
    return { id, x: 50 + Math.cos(angle) * 34, y: 48 + Math.sin(angle) * 30 };
  });
  const positionById = new Map(positions.map((item) => [item.id, item]));
  const resolvedEdges = edges.length
    ? edges
    : ids.length > 1
      ? ids.slice(1).map((id) => ({ from: ids[0], to: id, policy: "handoff" }))
      : [];

  return (
    <div className="boundary-graph">
      <div className="boundary-graph__legend">
        {messages.length ? messages.slice(0, 6).map((item) => <span key={item}>{item}</span>) : <span>structured_handoff</span>}
      </div>
      <svg viewBox="0 0 100 86" aria-hidden="true">
        <defs>
          <marker id="boundary-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="6" refY="3">
            <path d="M0,0 L0,6 L6,3 z" fill="currentColor" />
          </marker>
        </defs>
        {resolvedEdges.map((edge, index) => {
          const sourceNodeId = graphEdgeSource(edge);
          const targetNodeId = graphEdgeTarget(edge);
          const edgeId = graphEdgeId(edge, index);
          const from = positionById.get(sourceNodeId);
          const to = positionById.get(targetNodeId);
          if (!from || !to) return null;
          return (
            <line
              className={edgeId === selectedEdgeId ? "boundary-graph__edge boundary-graph__edge--active" : "boundary-graph__edge"}
              key={edgeId}
              markerEnd="url(#boundary-arrow)"
              onClick={() => onSelectEdge?.(edgeId)}
              x1={from.x}
              x2={to.x}
              y1={from.y}
              y2={to.y}
            />
          );
        })}
      </svg>
      {positions.map((position, index) => {
        const node = safeNodes[index] ?? {};
        const taskId = graphNodeTaskId(node);
        const nodeId = text(node.node_id || node.id, position.id);
        return (
          <button
            className={nodeId === selectedNodeId ? "boundary-graph__node boundary-graph__node--active" : "boundary-graph__node"}
            key={position.id}
            onClick={() => onSelectNode?.(nodeId)}
            style={{ left: `${position.x}%`, top: `${position.y}%` }}
            type="button"
          >
            <strong>{taskId ? taskTitleById(taskId, tasks) : graphNodeLabel(node, index)}</strong>
            <span>{text(node.role || node.agent_category || node.agent_id, "role")}</span>
          </button>
        );
      })}
    </div>
  );
}

function graphNodeLabel(node: Record<string, unknown>, index: number) {
  return text(node.label || node.task_title || node.role || node.agent_id, `节点 ${index + 1}`);
}

function graphNodeTaskId(node: Record<string, unknown>) {
  return String(node.task_id ?? node.subtask_ref ?? "").trim();
}

function graphEdgeId(edge: Record<string, unknown>, index = 0) {
  return String(edge.edge_id ?? edge.id ?? `${graphEdgeSource(edge)}-${graphEdgeTarget(edge)}-${index}`).trim();
}

function graphEdgeSource(edge: Record<string, unknown>) {
  return String(edge.from ?? edge.source_node_id ?? edge.source ?? "").trim();
}

function graphEdgeTarget(edge: Record<string, unknown>) {
  return String(edge.to ?? edge.target_node_id ?? edge.target ?? "").trim();
}

function taskTitleById(taskId: string, tasks: SpecificTaskRecord[]) {
  const task = tasks.find((item) => item.task_id === taskId);
  return task?.task_title || displayId(taskId);
}

function coordinationSubtaskRefs(draft: CoordinationTask | CoordinationDraft) {
  return uniqueStrings([
    ...(draft.subtask_refs ?? []),
    ...((draft.graph_nodes ?? []).map((node) => graphNodeTaskId(node))),
  ]);
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
  const [taskLayer, setTaskLayer] = useState<TaskLayer>("domain");
  const [domainPanel, setDomainPanel] = useState<DomainPanel>("taskDetail");
  const [editingDomainName, setEditingDomainName] = useState(false);
  const [assemblyPanel, setAssemblyPanel] = useState<AssemblyPanel>("workflow");
  const [coordinationPanel, setCoordinationPanel] = useState<CoordinationPanel>("topology");
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState("");
  const [selectedGraphEdgeId, setSelectedGraphEdgeId] = useState("");

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
    setTopologyDraft(topologyDraftFrom(selectedTopology));
    setProtocolDraft(protocolDraftFrom(selectedProtocol));
    setSelectedGraphNodeId(String((selectedCoordination?.graph_nodes ?? [])[0]?.node_id ?? ""));
    setSelectedGraphEdgeId(graphEdgeId((selectedCoordination?.graph_edges ?? [])[0] ?? {}, 0));
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
    setCoordinationDraft((current) => {
      const nextIndex = (current.graph_nodes?.length || 0) + 1;
      const existingTaskIds = new Set((current.graph_nodes ?? []).map((node) => graphNodeTaskId(node)).filter(Boolean));
      const nextTask = selectedDomainTasks.find((task) => !existingTaskIds.has(task.task_id));
      const node = {
        node_id: nextTask ? `subtask_${nextIndex}` : `agent_${nextIndex}`,
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
        subtask_refs: coordinationSubtaskRefs({ ...current, graph_nodes: [...(current.graph_nodes ?? []), node] }),
        graph_nodes: [...(current.graph_nodes ?? []), node],
      };
    });
  }

  function updateCoordinationNode(nodeId: string, patch: Record<string, unknown>) {
    setCoordinationDraft((current) => {
      const nextNodes = (current.graph_nodes ?? []).map((node) =>
        String(node.node_id ?? "") === nodeId ? { ...node, ...patch } : node,
      );
      return {
        ...current,
        graph_nodes: nextNodes,
        subtask_refs: coordinationSubtaskRefs({ ...current, graph_nodes: nextNodes }),
      };
    });
  }

  function removeCoordinationNode(nodeId: string) {
    setCoordinationDraft((current) => {
      const nextNodes = (current.graph_nodes ?? []).filter((node) => String(node.node_id ?? "") !== nodeId);
      return {
        ...current,
        graph_nodes: nextNodes,
        subtask_refs: coordinationSubtaskRefs({ ...current, graph_nodes: nextNodes }),
        graph_edges: (current.graph_edges ?? []).filter(
        (edge) => graphEdgeSource(edge) !== nodeId && graphEdgeTarget(edge) !== nodeId,
        ),
      };
    });
  }

  function addCoordinationEdge() {
    setCoordinationDraft((current) => {
      const nodes = current.graph_nodes ?? [];
      if (nodes.length < 2) return current;
      const from = String(nodes[0]?.node_id ?? "");
      const to = String(nodes[1]?.node_id ?? "");
      const nextIndex = (current.graph_edges?.length || 0) + 1;
      return {
        ...current,
        graph_edges: [
          ...(current.graph_edges ?? []),
          { edge_id: `edge_${nextIndex}`, from, to, source_node_id: from, target_node_id: to, mode: current.communication_modes?.[0] || "structured_handoff" },
        ],
      };
    });
  }

  function updateCoordinationEdge(edgeId: string, patch: Record<string, unknown>) {
    setCoordinationDraft((current) => ({
      ...current,
      graph_edges: (current.graph_edges ?? []).map((edge, index) =>
        graphEdgeId(edge, index) === edgeId ? { ...edge, ...patch } : edge,
      ),
    }));
  }

  function removeCoordinationEdge(edgeId: string) {
    setCoordinationDraft((current) => ({
      ...current,
      graph_edges: (current.graph_edges ?? []).filter((edge, index) => graphEdgeId(edge, index) !== edgeId),
    }));
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

  async function saveCoordinationStack() {
    setSaving("coordination");
    setError("");
    setNotice("");
    try {
      const subtaskRefs = coordinationSubtaskRefs(coordinationDraft);
      const protocolPayload: TaskCommunicationProtocol = {
        ...protocolDraft,
        message_types: coordinationDraft.communication_modes?.length ? coordinationDraft.communication_modes : splitList(protocolDraft.message_types_text),
        payload_contracts: splitList(protocolDraft.payload_contracts_text),
        signal_rules: splitList(protocolDraft.signal_rules_text),
        handoff_rules: splitList(protocolDraft.handoff_rules_text),
        metadata: {
          ...(protocolDraft.metadata ?? {}),
          task_family: selectedDomain?.task_family || "",
          domain_id: selectedDomain?.domain_id || "",
        },
      };
      await upsertTaskSystemCommunicationProtocol(protocolPayload.protocol_id, protocolPayload);
      await upsertTaskSystemTopologyTemplate(topologyDraft.template_id, {
        ...topologyDraft,
        nodes: coordinationDraft.graph_nodes ?? [],
        edges: coordinationDraft.graph_edges ?? [],
        handoff_rules: [],
        metadata: {
          ...(topologyDraft.metadata ?? {}),
          task_family: selectedDomain?.task_family || "",
          domain_id: selectedDomain?.domain_id || "",
        },
      });
      const payload = await upsertTaskSystemCoordinationTask(coordinationDraft.coordination_task_id, {
        ...coordinationDraft,
        task_family: selectedDomain?.task_family || coordinationDraft.task_family || "",
        domain_id: selectedDomain?.domain_id || coordinationDraft.domain_id || "",
        participant_agent_ids: (coordinationDraft.graph_nodes ?? [])
          .filter((node) => String(node.role ?? "") !== "coordinator")
          .map((node) => String(node.agent_id ?? "").trim())
          .filter(Boolean),
        stop_conditions: splitList(coordinationDraft.stop_conditions_text),
        subtask_refs: subtaskRefs,
        communication_modes: coordinationDraft.communication_modes ?? [],
        graph_nodes: coordinationDraft.graph_nodes ?? [],
        graph_edges: coordinationDraft.graph_edges ?? [],
        metadata: {
          ...(coordinationDraft.metadata ?? {}),
          protocol_id: protocolPayload.protocol_id,
          task_family: selectedDomain?.task_family || "",
          domain_id: selectedDomain?.domain_id || "",
        },
      });
      setConsolePayload(payload);
      setSelectedCoordinationId(coordinationDraft.coordination_task_id);
      setNotice("协调任务、拓扑和协议已保存。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存协调任务失败");
    } finally {
      setSaving("");
    }
  }

  const taskPolicyError = jsonError(taskPolicyText, "任务策略", "object");
  const topologyNodes = coordinationDraft.graph_nodes?.length ? coordinationDraft.graph_nodes : selectedCoordinationGraphSpec?.nodes ?? [];
  const topologyEdges = coordinationDraft.graph_edges?.length ? coordinationDraft.graph_edges : selectedCoordinationGraphSpec?.edges ?? [];
  const protocolMessages = coordinationDraft.communication_modes?.length ? coordinationDraft.communication_modes : splitList(protocolDraft.message_types_text);
  const activeGraphNodes = coordinationDraft.graph_nodes ?? [];
  const activeGraphEdges = coordinationDraft.graph_edges ?? [];
  const selectedGraphNode = activeGraphNodes.find((node) => String(node.node_id ?? "") === selectedGraphNodeId) ?? activeGraphNodes[0] ?? null;
  const selectedGraphEdge = activeGraphEdges.find((edge, index) => graphEdgeId(edge, index) === selectedGraphEdgeId) ?? activeGraphEdges[0] ?? null;
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
                    setTaskLayer("domain");
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
          <nav className="boundary-layer-tabs" aria-label="任务系统层级">
            {([
              ["domain", "任务域", selectedTaskDomain?.title || selectedDomain?.title || "-"],
              ["assembly", "任务装配", taskDraft.task_title || selectedTask?.task_title || "未选任务"],
              ["coordination", "域内协调任务", coordinationDraft.title || selectedCoordination?.title || "当前域暂无"],
              ["contracts", "契约", `${contractViews.length} 项`],
            ] as Array<[TaskLayer, string, string]>).map(([value, label, meta]) => (
              <button className={taskLayer === value ? "boundary-layer-tabs__item boundary-layer-tabs__item--active" : "boundary-layer-tabs__item"} key={value} onClick={() => setTaskLayer(value)} type="button">
                <span>{label}</span>
                <small>{meta}</small>
              </button>
            ))}
          </nav>

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
                <div className="boundary-subtabs">
                  {([
                    ["taskDetail", "任务定义"],
                    ["entry", "入口规则"],
                    ["eligibility", "承接要求"],
                  ] as Array<[DomainPanel, string]>).map(([value, label]) => (
                    <button className={domainPanel === value ? "active" : ""} key={value} onClick={() => setDomainPanel(value)} type="button">{label}</button>
                  ))}
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
                <div className="boundary-subtabs boundary-subtabs--wide">
                  {([
                    ["workflow", "执行流程"],
                    ["projection", "投影绑定"],
                    ["flow", "流程契约"],
                    ["execution", "执行策略"],
                    ["memory", "记忆请求"],
                  ] as Array<[AssemblyPanel, string]>).map(([value, label]) => (
                    <button className={assemblyPanel === value ? "active" : ""} key={value} onClick={() => setAssemblyPanel(value)} type="button">{label}</button>
                  ))}
                </div>
                  <header className="boundary-editor-title"><strong>{ASSEMBLY_LABELS[assemblyPanel]}</strong></header>
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
            <section className="boundary-layer-stack">
              <div className="boundary-card boundary-card--summary">
                <header>
                  <div className="boundary-identity-stack">
                    <span>{selectedDomain?.title || "任务域"} / 域内协调任务</span>
                    <strong>{coordinationDraft.title || "协调任务"}</strong>
                    <small>{coordinationTasks.length} 个协调对象</small>
                  </div>
                  <div className="boundary-actions">
                    <ToolbarButton onClick={() => sendCoordinationToChat(selectedCoordination, selectedDomain)}>带入主会话</ToolbarButton>
                    <ToolbarButton disabled={saving === "coordination"} onClick={() => void saveCoordinationStack()} variant="primary"><Save size={15} />保存协调任务</ToolbarButton>
                  </div>
                </header>
                <div className="boundary-selector-strip">
                  {coordinationTasks.map((task) => (
                    <button className={task.coordination_task_id === selectedCoordinationId ? "active" : ""} key={task.coordination_task_id} onClick={() => setSelectedCoordinationId(task.coordination_task_id)} type="button">
                      <strong>{task.title}</strong>
                    </button>
                  ))}
                  {!coordinationTasks.length ? <div className="boundary-empty">当前任务域暂无协调任务。</div> : null}
                </div>
              </div>
              <section className="boundary-card boundary-card--editor">
                  <div className="boundary-subtabs boundary-subtabs--wide">
                    {([
                      ["definition", "协调定义"],
                      ["topology", "拓扑图"],
                      ["protocol", "通信协议"],
                    ] as Array<[CoordinationPanel, string]>).map(([value, label]) => (
                      <button className={coordinationPanel === value ? "active" : ""} key={value} onClick={() => setCoordinationPanel(value)} type="button">{label}</button>
                    ))}
                  </div>
                  <header className="boundary-editor-title"><strong>{COORDINATION_LABELS[coordinationPanel]}</strong></header>
                  {coordinationPanel === "definition" ? (
                    <div className="boundary-graph-workbench">
                      <div className="boundary-graph-stage">
                        <CoordinationGraph
                          edges={activeGraphEdges}
                          messages={coordinationDraft.communication_modes ?? []}
                          nodes={activeGraphNodes}
                          onSelectEdge={setSelectedGraphEdgeId}
                          onSelectNode={setSelectedGraphNodeId}
                          selectedEdgeId={selectedGraphEdgeId}
                          selectedNodeId={selectedGraphNodeId}
                          tasks={selectedDomainTasks}
                        />
                        <div className="boundary-graph-status">
                          <span className={selectedCoordinationGraphSpec?.valid === false ? "boundary-status boundary-status--danger" : "boundary-status boundary-status--ok"}>
                            {selectedCoordinationGraphSpec?.valid === false ? "图校验未通过" : "图校验通过"}
                          </span>
                          <span>{activeGraphNodes.length} 个节点</span>
                          <span>{activeGraphEdges.length} 条通信边</span>
                        </div>
                      </div>
                      <aside className="boundary-graph-inspector">
                        <section className="boundary-inspector-block">
                          <header><strong>协调任务</strong></header>
                          <Field label="标题"><input value={coordinationDraft.title} onChange={(event) => setCoordinationDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                          <SelectField label="协调模式" onChange={(value) => setCoordinationDraft((current) => ({ ...current, coordination_mode: value }))} options={COORDINATION_MODE_CHOICES} value={coordinationDraft.coordination_mode} />
                          <SelectField label="Agent 组" onChange={(value) => setCoordinationDraft((current) => ({ ...current, agent_group_id: value }))} options={agentGroupOptions} value={coordinationDraft.agent_group_id || ""} />
                          <label className="boundary-check"><input checked={coordinationDraft.enabled} onChange={(event) => setCoordinationDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用协调任务</label>
                        </section>
                        <section className="boundary-inspector-block">
                          <header>
                            <strong>选中节点</strong>
                            <button className="boundary-icon-button" onClick={addCoordinationNode} type="button" aria-label="新增节点"><Plus size={14} /></button>
                          </header>
                          {selectedGraphNode ? (
                            <>
                              <Field label="节点名称"><input value={String(selectedGraphNode.label ?? selectedGraphNode.title ?? graphNodeLabel(selectedGraphNode, 0))} onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { label: event.target.value, title: event.target.value })} /></Field>
                              <DomainTaskSelectField
                                label="绑定分任务"
                                onChange={(value) => {
                                  const task = selectedDomainTasks.find((item) => item.task_id === value);
                                  updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), {
                                    node_type: value ? "subtask" : "agent_role",
                                    task_id: value,
                                    task_title: task?.task_title ?? "",
                                    task_family: task?.task_family ?? selectedDomain?.task_family ?? "",
                                    label: task?.task_title ?? String(selectedGraphNode.label ?? ""),
                                    title: task?.task_title ?? String(selectedGraphNode.title ?? selectedGraphNode.label ?? ""),
                                  });
                                }}
                                options={domainTaskOptions}
                                value={graphNodeTaskId(selectedGraphNode)}
                              />
                              <SelectField label="角色" onChange={(value) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { role: value })} options={["coordinator", "participant", "reviewer", "writer", "acceptance"]} value={String(selectedGraphNode.role ?? "participant")} />
                              <Field label="Agent"><input value={String(selectedGraphNode.agent_id ?? "")} onChange={(event) => updateCoordinationNode(String(selectedGraphNode.node_id ?? ""), { agent_id: event.target.value })} /></Field>
                              {String(selectedGraphNode.role ?? "") !== "coordinator" ? (
                                <ToolbarButton onClick={() => removeCoordinationNode(String(selectedGraphNode.node_id ?? ""))}><Trash2 size={14} />删除节点</ToolbarButton>
                              ) : null}
                            </>
                          ) : <div className="boundary-empty">点击图中的节点进行配置。</div>}
                        </section>
                        <section className="boundary-inspector-block">
                          <header>
                            <strong>选中通信</strong>
                            <button className="boundary-icon-button" onClick={addCoordinationEdge} type="button" aria-label="新增连线"><Plus size={14} /></button>
                          </header>
                          {selectedGraphEdge ? (
                            <>
                              <SelectField label="起点" onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { from: value, source_node_id: value })} options={activeGraphNodes.map((node) => String(node.node_id ?? ""))} value={graphEdgeSource(selectedGraphEdge)} />
                              <SelectField label="终点" onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { to: value, target_node_id: value })} options={activeGraphNodes.map((node) => String(node.node_id ?? ""))} value={graphEdgeTarget(selectedGraphEdge)} />
                              <SelectField label="通信模式" onChange={(value) => updateCoordinationEdge(graphEdgeId(selectedGraphEdge), { mode: value })} options={GRAPH_EDGE_MODE_CHOICES} value={String(selectedGraphEdge.mode ?? "structured_handoff")} />
                              <ToolbarButton onClick={() => removeCoordinationEdge(graphEdgeId(selectedGraphEdge))}><Trash2 size={14} />删除通信</ToolbarButton>
                            </>
                          ) : <div className="boundary-empty">点击图中的通信边进行配置。</div>}
                        </section>
                        {selectedCoordinationGraphSpec?.issues?.length ? (
                          <section className="boundary-inspector-block boundary-inspector-block--warn">
                            <header><strong>图校验</strong></header>
                            {selectedCoordinationGraphSpec.issues.map((issue, index) => (
                              <p key={`${String(issue.code ?? "issue")}-${index}`}>{String(issue.message ?? issue.code ?? "校验问题")}</p>
                            ))}
                          </section>
                        ) : null}
                        <details className="boundary-system-fields">
                          <summary>系统字段</summary>
                          <div className="boundary-form">
                            <Field label="停止条件" wide><textarea value={coordinationDraft.stop_conditions_text} onChange={(event) => setCoordinationDraft((value) => ({ ...value, stop_conditions_text: event.target.value }))} /></Field>
                            <MultiSelectField label="通信模式" onChange={(value) => setCoordinationDraft((current) => ({ ...current, communication_modes: value }))} options={GRAPH_EDGE_MODE_CHOICES} value={coordinationDraft.communication_modes ?? []} wide />
                          </div>
                        </details>
                      </aside>
                    </div>
                  ) : null}
                  {coordinationPanel === "topology" ? (
                    <div className="boundary-split">
                      <CoordinationGraph edges={topologyEdges} messages={protocolMessages} nodes={topologyNodes} tasks={selectedDomainTasks} />
                      <div className="boundary-form">
                        <Field label="标题"><input value={topologyDraft.title} onChange={(event) => setTopologyDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                        <SelectField label="汇合策略" onChange={(value) => setTopologyDraft((current) => ({ ...current, join_policy: value }))} options={["explicit_join", "coordinator_join", "sequential_join"]} value={topologyDraft.join_policy} />
                        <SelectField label="失败策略" onChange={(value) => setTopologyDraft((current) => ({ ...current, failure_policy: value }))} options={["fail_closed", "retry_once", "coordinator_decides"]} value={topologyDraft.failure_policy} />
                        <SelectField label="终止策略" onChange={(value) => setTopologyDraft((current) => ({ ...current, terminal_policy: value }))} options={["coordinator_terminal", "all_nodes_complete", "manual_close"]} value={topologyDraft.terminal_policy} />
                        <label className="boundary-check"><input checked={topologyDraft.enabled} onChange={(event) => setTopologyDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用拓扑</label>
                        <SystemFields>
                          <Field label="拓扑 ID"><input value={topologyDraft.template_id} onChange={(event) => setTopologyDraft((value) => ({ ...value, template_id: event.target.value }))} /></Field>
                        </SystemFields>
                      </div>
                    </div>
                  ) : null}
                  {coordinationPanel === "protocol" ? (
                    <div className="boundary-form">
                      <Field label="标题"><input value={protocolDraft.title} onChange={(event) => setProtocolDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                      <SelectField label="确认策略" onChange={(value) => setProtocolDraft((current) => ({ ...current, ack_policy: value }))} options={["explicit_ack", "implicit_ack"]} value={protocolDraft.ack_policy} />
                      <SelectField label="超时策略" onChange={(value) => setProtocolDraft((current) => ({ ...current, timeout_policy: value }))} options={["fail_closed", "retry_once", "escalate_to_coordinator"]} value={protocolDraft.timeout_policy} />
                      <SelectField label="错误信号" onChange={(value) => setProtocolDraft((current) => ({ ...current, error_signal_policy: value }))} options={["raise_to_coordinator", "return_to_sender", "halt_chain"]} value={protocolDraft.error_signal_policy} />
                      <MultiSelectField label="通信模式" onChange={(value) => setCoordinationDraft((current) => ({ ...current, communication_modes: value }))} options={GRAPH_EDGE_MODE_CHOICES} value={coordinationDraft.communication_modes ?? []} wide />
                      <label className="boundary-check"><input checked={protocolDraft.enabled} onChange={(event) => setProtocolDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用协议</label>
                      <SystemFields>
                        <Field label="协议 ID"><input value={protocolDraft.protocol_id} onChange={(event) => setProtocolDraft((value) => ({ ...value, protocol_id: event.target.value }))} /></Field>
                      </SystemFields>
                    </div>
                  ) : null}
              </section>
            </section>
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
