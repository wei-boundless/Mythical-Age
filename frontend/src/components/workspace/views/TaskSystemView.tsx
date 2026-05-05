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
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getSoulProjectionCards,
  getTaskSystemNextIds,
  getTaskSystemOverview,
  upsertTaskSystemCommunicationProtocol,
  upsertTaskSystemCoordinationTask,
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
  type SoulProjectionCatalog,
  type SpecificTaskRecord,
  type TaskCommunicationProtocol,
  type TaskExecutionPolicy,
  type TaskFlowContractBinding,
  type TaskMemoryRequestProfile,
  type TaskProjectionBinding,
  type TaskSystemOverview,
  type TaskWorkflowRecord,
  type TopologyTemplate,
} from "@/lib/api";

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
  participant_agent_ids_text: string;
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
    coordination_task_id: "",
    communication_protocol_id: "",
    topology_template_id: "",
    agent_group_id: "",
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

function emptyCoordination(templateId = "", protocolId = ""): CoordinationDraft {
  return {
    coordination_task_id: "coord.dev.task",
    title: "新协调任务",
    coordination_mode: "review_merge",
    coordinator_agent_id: "agent:0",
    agent_group_id: "",
    participant_agent_ids: [],
    topology_template_id: templateId,
    shared_context_policy: "explicit_refs_only",
    memory_sharing_policy: "isolated_by_default",
    handoff_policy: "filtered_handoff",
    conflict_resolution_policy: "coordinator_review",
    output_merge_policy: "coordinator_final_merge",
    stop_conditions: [],
    enabled: false,
    metadata: { managed_by: "task_domain_console", protocol_id: protocolId },
    participant_agent_ids_text: "",
    stop_conditions_text: "",
  };
}

function coordinationDraftFrom(task?: CoordinationTask | null): CoordinationDraft {
  const base = task ?? emptyCoordination();
  return {
    ...base,
    participant_agent_ids: base.participant_agent_ids ?? [],
    stop_conditions: base.stop_conditions ?? [],
    metadata: base.metadata ?? {},
    participant_agent_ids_text: listText(base.participant_agent_ids ?? []),
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

const TASK_FAMILY_CHOICES = ["development", "writing", "health", "general", "capability"];
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

function optionLabel(value: string) {
  return displayId(value);
}

function buildDomains(consolePayload: TaskSystemOverview | null): DomainRecord[] {
  const tasks = consolePayload?.task_management.specific_task_records ?? [];
  const entryPolicies = consolePayload?.task_management.entry_policies ?? [];
  const grouped = new Map<string, SpecificTaskRecord[]>();
  for (const task of tasks) {
    const key = task.task_family || "general";
    grouped.set(key, [...(grouped.get(key) ?? []), task]);
  }
  if (!grouped.size) grouped.set("general", []);
  return Array.from(grouped.entries()).map(([family, items], index) => ({
    domain_id: `domain.${family}`,
    title: domainTitle(family),
    task_family: family,
    task_modes: Array.from(new Set(items.map((item) => item.task_mode).filter(Boolean))),
    tasks: items,
    entry_policy: entryPolicies[index] ?? entryPolicies[0] ?? null,
  }));
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
}: {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  messages: string[];
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
          const from = positionById.get(text(edge.from, ""));
          const to = positionById.get(text(edge.to, ""));
          if (!from || !to) return null;
          return (
            <line
              className="boundary-graph__edge"
              key={`${text(edge.from)}-${text(edge.to)}-${index}`}
              markerEnd="url(#boundary-arrow)"
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
        return (
          <article className="boundary-graph__node" key={position.id} style={{ left: `${position.x}%`, top: `${position.y}%` }}>
            <strong>{position.id}</strong>
            <span>{text(node.role || node.agent_category || node.agent_id, "role")}</span>
          </article>
        );
      })}
    </div>
  );
}

export function TaskSystemView() {
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
  const [assemblyPanel, setAssemblyPanel] = useState<AssemblyPanel>("workflow");
  const [coordinationPanel, setCoordinationPanel] = useState<CoordinationPanel>("topology");

  const [entryDraft, setEntryDraft] = useState<ConversationEntryPolicy>(emptyEntryPolicy());
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
  const selectedDomain = domains.find((item) => item.domain_id === selectedDomainId) ?? domains[0] ?? null;
  const tasks = useMemo(() => consolePayload?.task_management.specific_task_records ?? [], [consolePayload]);
  const workflows = useMemo(() => consolePayload?.task_management.workflow_resources ?? [], [consolePayload]);
  const taskFlowDefinitions = useMemo(() => consolePayload?.task_management.task_flow_definitions ?? [], [consolePayload]);
  const selectedTask = tasks.find((item) => item.task_id === selectedTaskId) ?? selectedDomain?.tasks[0] ?? tasks[0] ?? null;
  const selectedTaskDomain = domains.find((item) => item.tasks.some((task) => task.task_id === selectedTask?.task_id)) ?? selectedDomain;
  const selectedDomainTasks = selectedTaskDomain?.tasks ?? selectedDomain?.tasks ?? [];
  const projectionBinding = (consolePayload?.task_management.projection_bindings ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const flowBinding = (consolePayload?.task_management.flow_contract_bindings ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const executionPolicy = (consolePayload?.task_management.execution_policies ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const memoryProfile = (consolePayload?.task_management.memory_request_profiles ?? []).find((item) => item.task_id === selectedTask?.task_id);
  const selectedWorkflow = workflows.find((item) => item.workflow_id === selectedTask?.default_workflow_id);
  const coordinationTasks = consolePayload?.coordination_management.coordination_tasks ?? [];
  const coordinationFromPolicy = coordinationTasks.find((item) => item.coordination_task_id === executionPolicy?.coordination_task_id);
  const selectedCoordination = coordinationTasks.find((item) => item.coordination_task_id === selectedCoordinationId) ?? coordinationFromPolicy ?? coordinationTasks[0] ?? null;
  const selectedTopology = (consolePayload?.coordination_management.topology_templates ?? []).find((item) => item.template_id === selectedCoordination?.topology_template_id);
  const selectedProtocol = (consolePayload?.coordination_management.communication_protocols ?? []).find((item) =>
    item.protocol_id === executionPolicy?.communication_protocol_id || item.protocol_id === selectedCoordination?.metadata?.protocol_id
  );
  const taskModeOptions = useMemo(() => uniqueStrings(tasks.map((item) => item.task_mode)), [tasks]);
  const workflowOptions = useMemo(() => uniqueStrings(workflows.map((item) => item.workflow_id)), [workflows]);
  const flowContractOptions = useMemo(
    () => uniqueStrings((consolePayload?.task_management.flow_contract_bindings ?? []).map((item) => item.flow_contract_id)),
    [consolePayload],
  );
  const topologyOptions = useMemo(
    () => uniqueStrings((consolePayload?.coordination_management.topology_templates ?? []).map((item) => item.template_id)),
    [consolePayload],
  );
  const protocolOptions = useMemo(
    () => uniqueStrings((consolePayload?.coordination_management.communication_protocols ?? []).map((item) => item.protocol_id)),
    [consolePayload],
  );
  const coordinationOptions = useMemo(
    () => uniqueStrings((consolePayload?.coordination_management.coordination_tasks ?? []).map((item) => item.coordination_task_id)),
    [consolePayload],
  );
  const agentGroupOptions = useMemo(
    () => uniqueStrings([
      ...(consolePayload?.task_management.execution_policies ?? []).map((item) => item.agent_group_id),
      ...(consolePayload?.coordination_management.coordination_tasks ?? []).map((item) => item.agent_group_id),
    ]),
    [consolePayload],
  );
  const projectionOptions = useMemo(
    () => projectionCatalog?.cards?.map((item) => String(item.projection_id || "")).filter(Boolean) ?? [],
    [projectionCatalog],
  );
  const contractViews = useMemo<ContractView[]>(() => {
    const fromFlows = taskFlowDefinitions.flatMap((flow) => {
      const items: ContractView[] = [];
      if (flow.input_contract_id) {
        items.push({
          key: `input:${flow.input_contract_id}`,
          title: displayId(flow.input_contract_id),
          kind: "输入契约",
          usage: flow.title,
          source: "任务流",
          raw: flow.input_contract_id,
        });
      }
      if (flow.output_contract_id) {
        items.push({
          key: `output:${flow.output_contract_id}`,
          title: displayId(flow.output_contract_id),
          kind: "输出契约",
          usage: flow.title,
          source: "任务流",
          raw: flow.output_contract_id,
        });
      }
      items.push({
        key: `flow:${flow.flow_id}`,
        title: flow.title,
        kind: "流程契约",
        usage: displayId(flow.task_mode),
        source: "任务流",
        raw: flow.flow_id,
      });
      return items;
    });
    const fromProtocols = (consolePayload?.coordination_management.communication_protocols ?? []).flatMap((protocol) =>
      (protocol.payload_contracts ?? []).map((contract) => ({
        key: `protocol:${protocol.protocol_id}:${contract}`,
        title: displayId(contract),
        kind: "通信载荷契约",
        usage: protocol.title,
        source: "通信协议",
        raw: contract,
      })),
    );
    return [...fromFlows, ...fromProtocols].filter((item, index, array) => array.findIndex((candidate) => candidate.key === item.key) === index);
  }, [consolePayload, taskFlowDefinitions]);
  const projectionOptionsKey = projectionOptions.join("|");

  useEffect(() => {
    if (!selectedDomain) return;
    setEntryDraft(selectedDomain.entry_policy ?? emptyEntryPolicy(workflows[0]?.workflow_id ?? "", projectionOptions[0] ?? ""));
  }, [selectedDomain, workflows, projectionOptions, projectionOptionsKey]);

  useEffect(() => {
    if (!selectedTask) return;
    setTaskDraft({ ...selectedTask, metadata: selectedTask.metadata ?? {}, task_policy: selectedTask.task_policy ?? {} });
    setTaskPolicyText(JSON.stringify(selectedTask.task_policy ?? {}, null, 2));
    setWorkflowDraft(workflowDraftFrom(selectedWorkflow, selectedTask.task_mode));
    setProjectionDraft(projectionBinding ?? emptyProjectionBinding(selectedTask.task_id, projectionOptions[0] ?? ""));
    setFlowDraft(flowBinding ?? emptyFlowBinding(selectedTask.task_id, selectedTask.default_flow_contract_id));
    setExecutionDraft(executionPolicy ?? emptyExecutionPolicy(selectedTask.task_id));
    setMemoryDraft(memoryProfile ?? emptyMemoryProfile(selectedTask.task_id));
  }, [selectedTask, selectedWorkflow, projectionBinding, flowBinding, executionPolicy, memoryProfile, projectionOptions, projectionOptionsKey]);

  useEffect(() => {
    setCoordinationDraft(coordinationDraftFrom(selectedCoordination));
    setTopologyDraft(topologyDraftFrom(selectedTopology));
    setProtocolDraft(protocolDraftFrom(selectedProtocol));
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
      setProjectionDraft(emptyProjectionBinding(nextTask.task_id, projectionOptions[0] ?? ""));
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

  async function createCoordinationDraft() {
    setSaving("coordination-create");
    setError("");
    setNotice("");
    try {
      const ids = await getTaskSystemNextIds();
      const coordination = emptyCoordination(ids.topology_template_id, `protocol.${ids.coordination_task_id.replace(/^coord\./, "")}`);
      coordination.coordination_task_id = ids.coordination_task_id;
      coordination.title = `${ids.display_numbers.coordination} 协调任务`;
      coordination.topology_template_id = ids.topology_template_id;
      const topology = emptyTopology();
      topology.template_id = ids.topology_template_id;
      topology.title = `${ids.display_numbers.topology} 拓扑`;
      const protocol = emptyProtocol();
      protocol.protocol_id = String(coordination.metadata?.protocol_id || protocol.protocol_id);
      protocol.title = `${ids.display_numbers.coordination} 协议`;
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
      await upsertTaskSystemExecutionPolicy(taskPayload.task_id, executionDraft);
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
    const nodeError = jsonError(topologyDraft.nodes_text, "拓扑节点", "array");
    const edgeError = jsonError(topologyDraft.edges_text, "拓扑边", "array");
    const handoffError = jsonError(topologyDraft.handoff_rules_text, "交接规则", "array");
    const firstError = nodeError || edgeError || handoffError;
    if (firstError) {
      setError(firstError);
      return;
    }
    setSaving("coordination");
    setError("");
    setNotice("");
    try {
      const protocolPayload: TaskCommunicationProtocol = {
        ...protocolDraft,
        message_types: splitList(protocolDraft.message_types_text),
        payload_contracts: splitList(protocolDraft.payload_contracts_text),
        signal_rules: splitList(protocolDraft.signal_rules_text),
        handoff_rules: splitList(protocolDraft.handoff_rules_text),
      };
      await upsertTaskSystemCommunicationProtocol(protocolPayload.protocol_id, protocolPayload);
      await upsertTaskSystemTopologyTemplate(topologyDraft.template_id, {
        ...topologyDraft,
        nodes: parseJsonList(topologyDraft.nodes_text, "拓扑节点"),
        edges: parseJsonList(topologyDraft.edges_text, "拓扑边"),
        handoff_rules: parseJsonList(topologyDraft.handoff_rules_text, "交接规则"),
      });
      const payload = await upsertTaskSystemCoordinationTask(coordinationDraft.coordination_task_id, {
        ...coordinationDraft,
        participant_agent_ids: splitList(coordinationDraft.participant_agent_ids_text),
        stop_conditions: splitList(coordinationDraft.stop_conditions_text),
        metadata: { ...(coordinationDraft.metadata ?? {}), protocol_id: protocolPayload.protocol_id },
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
  const topologyNodes = useMemo(() => {
    try {
      return parseJsonList(topologyDraft.nodes_text, "拓扑节点");
    } catch {
      return [];
    }
  }, [topologyDraft.nodes_text]);
  const topologyEdges = useMemo(() => {
    try {
      return parseJsonList(topologyDraft.edges_text, "拓扑边");
    } catch {
      return [];
    }
  }, [topologyDraft.edges_text]);
  const protocolMessages = splitList(protocolDraft.message_types_text);
  const taskReadiness = [
    { label: "任务定义", value: taskDraft.task_title || taskDraft.task_id, ready: Boolean(taskDraft.task_id && taskDraft.task_title) },
    { label: "执行流程", value: workflowDraft.title || "已选择", ready: Boolean(workflowDraft.workflow_id) },
    { label: "投影", value: projectionCatalog?.cards?.find((item) => item.projection_id === projectionDraft.default_projection_id)?.title || (projectionDraft.default_projection_id ? "已选择" : String(projectionDraft.allowed_projection_ids?.length || 0)), ready: Boolean(projectionDraft.default_projection_id || projectionDraft.allowed_projection_ids?.length) },
    { label: "执行方式", value: executionDraft.execution_chain_type, ready: Boolean(executionDraft.execution_chain_type) },
    { label: "记忆", value: memoryDraft.memory_priority, ready: Boolean(memoryDraft.memory_priority) },
  ];
  const eligibilityRows = [
    { label: "允许 Agent", value: executionDraft.allowed_agent_categories?.map((item) => displayId(item)).join(" / ") || "未配置" },
    { label: "任务范围", value: `${domainTitle(taskDraft.task_family || selectedTaskDomain?.task_family || "")} / ${displayId(taskDraft.task_mode)}` },
    { label: "权限口径", value: `${displayId(executionDraft.task_level)} / ${displayId(executionDraft.task_privilege)}` },
    { label: "输出契约", value: displayId(taskDraft.output_contract_id || workflowDraft.output_contract_id || "") },
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
            <span>{domains.length}</span>
          </div>
          {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
          {domains.map((domain) => (
            <button
              className={domain.domain_id === selectedDomainId ? "boundary-domain boundary-domain--active" : "boundary-domain"}
              key={domain.domain_id}
              onClick={() => {
                setSelectedDomainId(domain.domain_id);
                setSelectedTaskId(domain.tasks[0]?.task_id || selectedTaskId);
                setTaskLayer("domain");
                setDomainPanel("taskDetail");
              }}
              type="button"
            >
              <strong>{domain.title}</strong>
              <small>{domain.tasks.length} 个任务</small>
            </button>
          ))}
        </aside>

        <main className="boundary-main">
          <nav className="boundary-layer-tabs" aria-label="任务系统层级">
            {([
              ["domain", "任务域", selectedTaskDomain?.title || selectedDomain?.title || "-"],
              ["assembly", "任务装配", taskDraft.task_title || selectedTask?.task_title || "未选任务"],
              ["coordination", "协调任务", coordinationDraft.title || selectedCoordination?.title || "-"],
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
                  <strong>{selectedDomain?.title || "任务域"}</strong>
                  <span>{selectedDomain?.tasks.length || 0}</span>
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
                      <Field label="默认投影"><input value={entryDraft.default_projection_id} onChange={(event) => setEntryDraft((value) => ({ ...value, default_projection_id: event.target.value }))} /></Field>
                      <label className="boundary-check"><input checked={entryDraft.enabled} onChange={(event) => setEntryDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用</label>
                      <SystemFields>
                        <Field label="入口档案 ID"><input value={entryDraft.profile_id} onChange={(event) => setEntryDraft((value) => ({ ...value, profile_id: event.target.value }))} /></Field>
                        <SelectField label="输入契约" onChange={(value) => setEntryDraft((current) => ({ ...current, input_contract_id: value }))} options={COMMON_CONTRACT_CHOICES} value={entryDraft.input_contract_id} />
                        <SelectField label="输出契约" onChange={(value) => setEntryDraft((current) => ({ ...current, output_contract_id: value }))} options={COMMON_CONTRACT_CHOICES} value={entryDraft.output_contract_id} />
                      </SystemFields>
                    </div>
                  </section>
                ) : null}
                {domainPanel === "taskDetail" ? (
                  <section className="boundary-card">
                    <header>
                      <strong>{taskDraft.task_title || "特定任务定义"}</strong>
                      <div className="boundary-actions">
                        <ToolbarButton onClick={() => setTaskLayer("assembly")}>进入装配</ToolbarButton>
                        <ToolbarButton disabled={saving === "task-stack"} onClick={() => void saveTaskStack()} variant="primary"><Save size={15} />保存任务</ToolbarButton>
                      </div>
                    </header>
                    <div className="boundary-form">
                      <Field label="任务标题"><input value={taskDraft.task_title} onChange={(event) => setTaskDraft((value) => ({ ...value, task_title: event.target.value }))} /></Field>
                      <SelectField label="所属任务域" onChange={(value) => setTaskDraft((current) => ({ ...current, task_family: value }))} options={TASK_FAMILY_CHOICES} value={taskDraft.task_family} />
                      <SelectField label="任务模式" onChange={(value) => setTaskDraft((current) => ({ ...current, task_mode: value }))} options={taskModeOptions} value={taskDraft.task_mode} />
                      <Field label="验收档案"><input value={taskDraft.acceptance_profile_id} onChange={(event) => setTaskDraft((value) => ({ ...value, acceptance_profile_id: event.target.value }))} /></Field>
                      <Field label="任务描述" wide><textarea value={taskDraft.description} onChange={(event) => setTaskDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                      <label className="boundary-check"><input checked={taskDraft.enabled} onChange={(event) => setTaskDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用任务</label>
                      <SystemFields>
                        <Field label="任务 ID"><input value={taskDraft.task_id} onChange={(event) => setTaskDraft((value) => ({ ...value, task_id: event.target.value }))} /></Field>
                        <SelectField label="输入契约" onChange={(value) => setTaskDraft((current) => ({ ...current, input_contract_id: value }))} options={COMMON_CONTRACT_CHOICES} value={taskDraft.input_contract_id} />
                        <SelectField label="输出契约" onChange={(value) => setTaskDraft((current) => ({ ...current, output_contract_id: value }))} options={COMMON_CONTRACT_CHOICES} value={taskDraft.output_contract_id} />
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
                        <SelectField label="输出契约" onChange={(value) => setWorkflowDraft((current) => ({ ...current, output_contract_id: value }))} options={COMMON_CONTRACT_CHOICES} value={workflowDraft.output_contract_id} />
                        <Field label="可见技能" wide><textarea value={workflowDraft.visible_skill_ids_text} onChange={(event) => setWorkflowDraft((value) => ({ ...value, visible_skill_ids_text: event.target.value }))} /></Field>
                        <Field label="兼容投影" wide><textarea value={workflowDraft.compatible_projection_ids_text} onChange={(event) => setWorkflowDraft((value) => ({ ...value, compatible_projection_ids_text: event.target.value }))} /></Field>
                        <Field label="输入边界"><input value={workflowDraft.input_boundary} onChange={(event) => setWorkflowDraft((value) => ({ ...value, input_boundary: event.target.value }))} /></Field>
                        <Field label="输出边界"><input value={workflowDraft.output_boundary} onChange={(event) => setWorkflowDraft((value) => ({ ...value, output_boundary: event.target.value }))} /></Field>
                      </SystemFields>
                    </div>
                  ) : null}
                  {assemblyPanel === "projection" ? (
                    <div className="boundary-form">
                      <SelectField label="选择模式" onChange={(value) => setProjectionDraft((current) => ({ ...current, projection_selection_mode: value }))} options={PROJECTION_SELECTION_MODE_CHOICES} value={projectionDraft.projection_selection_mode} />
                      <Field label="默认投影"><input list="task-projection-options" value={projectionDraft.default_projection_id} onChange={(event) => setProjectionDraft((value) => ({ ...value, default_projection_id: event.target.value }))} /></Field>
                      <Field label="备注" wide><textarea value={projectionDraft.notes} onChange={(event) => setProjectionDraft((value) => ({ ...value, notes: event.target.value }))} /></Field>
                      <label className="boundary-check"><input checked={projectionDraft.projection_required} onChange={(event) => setProjectionDraft((value) => ({ ...value, projection_required: event.target.checked }))} type="checkbox" />投影必需</label>
                      <SystemFields>
                        <Field label="允许投影" wide><textarea value={listText(projectionDraft.allowed_projection_ids)} onChange={(event) => setProjectionDraft((value) => ({ ...value, allowed_projection_ids: splitList(event.target.value) }))} /></Field>
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
                      <Field label="执行链类型">
                        <select value={executionDraft.execution_chain_type} onChange={(event) => setExecutionDraft((value) => ({ ...value, execution_chain_type: event.target.value }))}>
                          <option value="single_agent_chain">单 Agent 链</option>
                          <option value="coordination_chain">协调任务</option>
                        </select>
                      </Field>
                      <SelectField label="运行选择策略" onChange={(value) => setExecutionDraft((current) => ({ ...current, runtime_agent_selection_policy: value }))} options={RUNTIME_SELECTION_POLICY_CHOICES} value={executionDraft.runtime_agent_selection_policy || ""} />
                      <SelectField label="任务等级" onChange={(value) => setExecutionDraft((current) => ({ ...current, task_level: value }))} options={TASK_LEVEL_CHOICES} value={executionDraft.task_level || ""} />
                      <SelectField label="任务权限" onChange={(value) => setExecutionDraft((current) => ({ ...current, task_privilege: value }))} options={TASK_PRIVILEGE_CHOICES} value={executionDraft.task_privilege || ""} />
                      <MultiSelectField label="允许 Agent 类别" onChange={(value) => setExecutionDraft((current) => ({ ...current, allowed_agent_categories: value }))} options={AGENT_CATEGORY_CHOICES} value={executionDraft.allowed_agent_categories ?? []} wide />
                      <SelectField label="协调任务" onChange={(value) => setExecutionDraft((current) => ({ ...current, coordination_task_id: value }))} options={coordinationOptions} value={executionDraft.coordination_task_id || ""} />
                      <SelectField label="Agent 组" onChange={(value) => setExecutionDraft((current) => ({ ...current, agent_group_id: value }))} options={agentGroupOptions} value={executionDraft.agent_group_id || ""} />
                      <label className="boundary-check"><input checked={executionDraft.allow_worker_agent_spawn} onChange={(event) => setExecutionDraft((value) => ({ ...value, allow_worker_agent_spawn: event.target.checked }))} type="checkbox" />允许临时子 Agent</label>
                      <Field label="备注" wide><textarea value={executionDraft.notes} onChange={(event) => setExecutionDraft((value) => ({ ...value, notes: event.target.value }))} /></Field>
                      <SystemFields>
                        <SelectField label="拓扑模板" onChange={(value) => setExecutionDraft((current) => ({ ...current, topology_template_id: value }))} options={topologyOptions} value={executionDraft.topology_template_id || ""} />
                        <SelectField label="通信协议" onChange={(value) => setExecutionDraft((current) => ({ ...current, communication_protocol_id: value }))} options={protocolOptions} value={executionDraft.communication_protocol_id || ""} />
                        <Field label="子 Agent 蓝图"><input value={executionDraft.worker_agent_blueprint_id} onChange={(event) => setExecutionDraft((value) => ({ ...value, worker_agent_blueprint_id: event.target.value }))} /></Field>
                        <Field label="子 Agent 命名规则"><input value={executionDraft.worker_agent_naming_rule} onChange={(event) => setExecutionDraft((value) => ({ ...value, worker_agent_naming_rule: event.target.value }))} /></Field>
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
                  <strong>{coordinationDraft.title || "协调任务"}</strong>
                  <ToolbarButton disabled={saving === "coordination"} onClick={() => void saveCoordinationStack()} variant="primary"><Save size={15} />保存协调任务</ToolbarButton>
                </header>
                <div className="boundary-selector-strip">
                  {coordinationTasks.map((task) => (
                    <button className={task.coordination_task_id === selectedCoordinationId ? "active" : ""} key={task.coordination_task_id} onClick={() => setSelectedCoordinationId(task.coordination_task_id)} type="button">
                      <strong>{task.title}</strong>
                    </button>
                  ))}
                  {!coordinationTasks.length ? <div className="boundary-empty">暂无协调任务。</div> : null}
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
                    <div className="boundary-form">
                      <Field label="协调任务 ID"><input value={coordinationDraft.coordination_task_id} onChange={(event) => setCoordinationDraft((value) => ({ ...value, coordination_task_id: event.target.value }))} /></Field>
                      <Field label="标题"><input value={coordinationDraft.title} onChange={(event) => setCoordinationDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                      <Field label="模式"><input value={coordinationDraft.coordination_mode} onChange={(event) => setCoordinationDraft((value) => ({ ...value, coordination_mode: event.target.value }))} /></Field>
                      <Field label="默认协调主体"><input value={coordinationDraft.coordinator_agent_id} onChange={(event) => setCoordinationDraft((value) => ({ ...value, coordinator_agent_id: event.target.value }))} /></Field>
                      <Field label="Agent 组 ID"><input value={coordinationDraft.agent_group_id || ""} onChange={(event) => setCoordinationDraft((value) => ({ ...value, agent_group_id: event.target.value }))} /></Field>
                      <Field label="默认参与主体" wide><textarea value={coordinationDraft.participant_agent_ids_text} onChange={(event) => setCoordinationDraft((value) => ({ ...value, participant_agent_ids_text: event.target.value }))} /></Field>
                      <Field label="拓扑模板"><input value={coordinationDraft.topology_template_id} onChange={(event) => setCoordinationDraft((value) => ({ ...value, topology_template_id: event.target.value }))} /></Field>
                      <Field label="上下文共享"><input value={coordinationDraft.shared_context_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, shared_context_policy: event.target.value }))} /></Field>
                      <Field label="记忆共享"><input value={coordinationDraft.memory_sharing_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, memory_sharing_policy: event.target.value }))} /></Field>
                      <Field label="交接策略"><input value={coordinationDraft.handoff_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, handoff_policy: event.target.value }))} /></Field>
                      <Field label="冲突收敛"><input value={coordinationDraft.conflict_resolution_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, conflict_resolution_policy: event.target.value }))} /></Field>
                      <Field label="合并策略"><input value={coordinationDraft.output_merge_policy} onChange={(event) => setCoordinationDraft((value) => ({ ...value, output_merge_policy: event.target.value }))} /></Field>
                      <Field label="停止条件" wide><textarea value={coordinationDraft.stop_conditions_text} onChange={(event) => setCoordinationDraft((value) => ({ ...value, stop_conditions_text: event.target.value }))} /></Field>
                      <label className="boundary-check"><input checked={coordinationDraft.enabled} onChange={(event) => setCoordinationDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用协调任务</label>
                    </div>
                  ) : null}
                  {coordinationPanel === "topology" ? (
                    <div className="boundary-split">
                      <CoordinationGraph edges={topologyEdges} messages={protocolMessages} nodes={topologyNodes} />
                      <div className="boundary-form">
                        <Field label="拓扑 ID"><input value={topologyDraft.template_id} onChange={(event) => setTopologyDraft((value) => ({ ...value, template_id: event.target.value }))} /></Field>
                        <Field label="标题"><input value={topologyDraft.title} onChange={(event) => setTopologyDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                        <Field label="汇合策略"><input value={topologyDraft.join_policy} onChange={(event) => setTopologyDraft((value) => ({ ...value, join_policy: event.target.value }))} /></Field>
                        <Field label="失败策略"><input value={topologyDraft.failure_policy} onChange={(event) => setTopologyDraft((value) => ({ ...value, failure_policy: event.target.value }))} /></Field>
                        <Field label="终止策略"><input value={topologyDraft.terminal_policy} onChange={(event) => setTopologyDraft((value) => ({ ...value, terminal_policy: event.target.value }))} /></Field>
                        <Field label="节点 JSON" wide><textarea value={topologyDraft.nodes_text} onChange={(event) => setTopologyDraft((value) => ({ ...value, nodes_text: event.target.value }))} /></Field>
                        <Field label="边 JSON" wide><textarea value={topologyDraft.edges_text} onChange={(event) => setTopologyDraft((value) => ({ ...value, edges_text: event.target.value }))} /></Field>
                        <Field label="交接规则 JSON" wide><textarea value={topologyDraft.handoff_rules_text} onChange={(event) => setTopologyDraft((value) => ({ ...value, handoff_rules_text: event.target.value }))} /></Field>
                        <label className="boundary-check"><input checked={topologyDraft.enabled} onChange={(event) => setTopologyDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用拓扑</label>
                      </div>
                    </div>
                  ) : null}
                  {coordinationPanel === "protocol" ? (
                    <div className="boundary-form">
                      <Field label="协议 ID"><input value={protocolDraft.protocol_id} onChange={(event) => setProtocolDraft((value) => ({ ...value, protocol_id: event.target.value }))} /></Field>
                      <Field label="标题"><input value={protocolDraft.title} onChange={(event) => setProtocolDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                      <Field label="确认策略"><input value={protocolDraft.ack_policy} onChange={(event) => setProtocolDraft((value) => ({ ...value, ack_policy: event.target.value }))} /></Field>
                      <Field label="超时策略"><input value={protocolDraft.timeout_policy} onChange={(event) => setProtocolDraft((value) => ({ ...value, timeout_policy: event.target.value }))} /></Field>
                      <Field label="错误信号"><input value={protocolDraft.error_signal_policy} onChange={(event) => setProtocolDraft((value) => ({ ...value, error_signal_policy: event.target.value }))} /></Field>
                      <Field label="消息类型" wide><textarea value={protocolDraft.message_types_text} onChange={(event) => setProtocolDraft((value) => ({ ...value, message_types_text: event.target.value }))} /></Field>
                      <Field label="载荷契约" wide><textarea value={protocolDraft.payload_contracts_text} onChange={(event) => setProtocolDraft((value) => ({ ...value, payload_contracts_text: event.target.value }))} /></Field>
                      <Field label="信号规则" wide><textarea value={protocolDraft.signal_rules_text} onChange={(event) => setProtocolDraft((value) => ({ ...value, signal_rules_text: event.target.value }))} /></Field>
                      <Field label="交接规则" wide><textarea value={protocolDraft.handoff_rules_text} onChange={(event) => setProtocolDraft((value) => ({ ...value, handoff_rules_text: event.target.value }))} /></Field>
                      <label className="boundary-check"><input checked={protocolDraft.enabled} onChange={(event) => setProtocolDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用协议</label>
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
                <header><strong>来源说明</strong></header>
                <div className="boundary-kv">
                  <p><span>流程契约</span><strong>来自任务流定义，当前用任务流标题展示</strong></p>
                  <p><span>输入/输出契约</span><strong>来自任务流与任务定义，当前用契约名展示</strong></p>
                  <p><span>通信载荷契约</span><strong>来自通信协议，当前用载荷契约名展示</strong></p>
                  <p><span>当前状态</span><strong>已有管理入口，不再是黑箱</strong></p>
                </div>
              </aside>
            </section>
          ) : null}
        </main>
      </section>
      <datalist id="task-projection-options">
        {projectionOptions.map((item) => <option key={item} value={item} />)}
      </datalist>
    </div>
  );
}
