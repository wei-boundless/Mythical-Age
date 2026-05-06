"use client";

import {
  AlertTriangle,
  CheckCircle2,
  CopyPlus,
  Gauge,
  KeyRound,
  Layers3,
  Loader2,
  Network,
  Plus,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Trash2,
  UserCog,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteOrchestrationAgent,
  getSoulProjectionCards,
  getNextOrchestrationWorkerAgentId,
  getOrchestrationAgents,
  upsertOrchestrationAgent,
  upsertOrchestrationAgentGroup,
  updateOrchestrationAgentRuntimeProfile,
  type OrchestrationAgentGroup,
  type OrchestrationAgentRuntimeCatalog,
  type OrchestrationAgentRuntimeProfile,
  type OrchestrationAgentUpsertPayload,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
} from "@/lib/api";

type AgentCategory = "main_agent" | "system_management_agent" | "worker_sub_agent";
type OrchestrationLayer = "registry" | "groups" | "scope" | "runtime" | "permissions" | "context" | "eligibility";
type WorkerDirectoryMode = "grouped" | "ungrouped";

type AgentDraft = OrchestrationAgentUpsertPayload & {
  task_scope_text: string;
  managed_object_types_text: string;
  capability_refs_text: string;
};

type RuntimeDraft = OrchestrationAgentRuntimeProfile & {
  allowed_task_modes_text: string;
  allowed_runtime_lanes_text: string;
  allowed_operations_text: string;
  blocked_operations_text: string;
  allowed_memory_scopes_text: string;
  allowed_context_sections_text: string;
  output_contracts_text: string;
};

type AgentGroupDraft = OrchestrationAgentGroup & {
  member_agent_ids_text: string;
};

const CATEGORY_ORDER: AgentCategory[] = ["main_agent", "system_management_agent", "worker_sub_agent"];

const CATEGORY_LABELS: Record<AgentCategory, string> = {
  main_agent: "主 Agent",
  system_management_agent: "系统管理 Agent",
  worker_sub_agent: "子 Agent",
};

const EMPTY_AGENT_DRAFT: AgentDraft = {
  agent_id: "",
  agent_name: "",
  agent_category: "worker_sub_agent",
  interface_target: "worker_task_console",
  description: "",
  enabled: true,
  editable: true,
  default_soul_id: "",
  default_projection_id: "",
  task_scope: [],
  task_scope_text: "",
  managed_object_types_text: "",
  capability_refs_text: "",
  metadata: { managed_by: "orchestration_console" },
};

const EMPTY_RUNTIME_DRAFT: RuntimeDraft = {
  agent_profile_id: "",
  agent_id: "",
  allowed_task_modes: [],
  allowed_runtime_lanes: [],
  allowed_operations: ["op.model_response"],
  blocked_operations: [],
  allowed_memory_scopes: [],
  allowed_context_sections: [],
  output_contracts: [],
  approval_policy: "default",
  trace_policy: "runtime_event_log",
  lifecycle_policy: "orchestration_managed",
  metadata: { managed_by: "orchestration_console" },
  allowed_task_modes_text: "",
  allowed_runtime_lanes_text: "",
  allowed_operations_text: "op.model_response",
  blocked_operations_text: "",
  allowed_memory_scopes_text: "",
  allowed_context_sections_text: "",
  output_contracts_text: "",
};

const EMPTY_GROUP_DRAFT: AgentGroupDraft = {
  group_id: "group.writing.longform_novel_core",
  title: "长篇小说常态协调组",
  group_kind: "coordination_team",
  coordinator_agent_id: "agent:20",
  member_agent_ids: [],
  description: "",
  default_topology_template_ids: [],
  default_communication_protocol_ids: [],
  allowed_coordination_task_ids: [],
  lifecycle_state: "enabled",
  metadata: { managed_by: "orchestration_console" },
  member_agent_ids_text: "",
};

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  return String(value);
}

function displayId(value: unknown, fallback = "未配置") {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const labels: Record<string, string> = {
    main_agent: "主 Agent",
    system_management_agent: "系统管理 Agent",
    worker_sub_agent: "子 Agent",
    coordination_team: "协调任务组",
    enabled: "启用",
    disabled: "停用",
    default: "默认审批",
    runtime_event_log: "运行事件追踪",
    orchestration_managed: "编排系统管理",
    health_management: "健康管理",
    trace_analysis: "Trace 分析",
    memory_management: "记忆管理",
    permission_management: "权限管理",
    development: "开发任务",
    full_interactive: "完整交互运行",
    op_model_response: "模型响应",
    "op.model_response": "模型响应",
    "op.read_file": "读取文件",
    "op.write_file": "写入文件",
    "op.edit_file": "编辑文件",
    "op.shell": "终端命令",
    conversation: "会话内容",
    state: "当前状态",
    task: "任务信息",
    projection: "投影信息",
    tool: "工具结果",
    health_issue: "健康事项",
    runtime_trace: "运行追踪",
    prompt_manifest: "提示结构",
    memory_runtime_view: "记忆视图",
    assertions: "验收断言",
    AssistantFinalAnswer: "最终回答",
  };
  if (labels[raw]) return `${labels[raw]} · ${raw}`;
  const prefixLabels: Array<[string, string]> = [
    ["agent:", "Agent"],
    ["group.", "Agent 组"],
    ["task.", "任务"],
    ["coord.", "协调任务"],
    ["topology.", "拓扑"],
    ["protocol.", "协议"],
    ["workflow.", "执行流程"],
    ["op.", "操作权限"],
  ];
  const matched = prefixLabels.find(([prefix]) => raw.startsWith(prefix));
  return matched ? `${matched[1]} · ${raw}` : raw;
}

function splitList(value: string) {
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
}

function makeCustomGroupId(existingGroups: OrchestrationAgentGroup[]) {
  let index = existingGroups.length + 1;
  let groupId = `group.custom.sub_agent_group_${String(index).padStart(2, "0")}`;
  const existingIds = new Set(existingGroups.map((group) => group.group_id));
  while (existingIds.has(groupId)) {
    index += 1;
    groupId = `group.custom.sub_agent_group_${String(index).padStart(2, "0")}`;
  }
  return groupId;
}

function arrayFromMetadata(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function agentCategory(agent: Record<string, unknown> | null | undefined): AgentCategory {
  const value = String(agent?.agent_category || agent?.profile_type || "worker_sub_agent");
  return CATEGORY_ORDER.includes(value as AgentCategory) ? (value as AgentCategory) : "worker_sub_agent";
}

function displayName(agent: Record<string, unknown> | null | undefined) {
  return text(agent?.agent_name || agent?.display_name, displayId(agent?.agent_id, "未命名 Agent"));
}

function displayList(values: string[], fallback = "未配置") {
  return values.length ? values.map((item) => displayId(item)).join(" / ") : fallback;
}

function projectionLabel(value: string, cards: SoulProjectionCard[] = []) {
  const raw = String(value || "").trim();
  if (!raw) return "不使用投影";
  const card = cards.find((item) => item.projection_id === raw);
  if (!card) return raw;
  const owner = card.soul_name || card.soul_id || "灵魂系统";
  return `${card.title || card.projection_id} · ${owner}`;
}

function agentDraftFrom(agent?: Record<string, unknown> | null): AgentDraft {
  if (!agent) return { ...EMPTY_AGENT_DRAFT, metadata: { ...EMPTY_AGENT_DRAFT.metadata } };
  const metadata = { ...((agent.metadata as Record<string, unknown> | undefined) ?? {}) };
  const taskScope = Array.isArray(agent.task_scope) ? agent.task_scope.map((item) => String(item)) : [];
  return {
    agent_id: String(agent.agent_id || ""),
    agent_name: String(agent.agent_name || agent.display_name || ""),
    agent_category: agentCategory(agent),
    interface_target: String(agent.interface_target || ""),
    description: String(agent.description || ""),
    enabled: Boolean(agent.enabled ?? true),
    editable: Boolean(agent.editable ?? true),
    default_soul_id: String(agent.default_soul_id || ""),
    default_projection_id: String(agent.default_projection_id || ""),
    task_scope: taskScope,
    task_scope_text: taskScope.join("\n"),
    managed_object_types_text: arrayFromMetadata(metadata, "managed_object_types").join("\n"),
    capability_refs_text: arrayFromMetadata(metadata, "capability_refs").join("\n"),
    metadata: { ...metadata, managed_by: "orchestration_console" },
  };
}

function runtimeDraftFrom(agentId: string, profile?: Partial<OrchestrationAgentRuntimeProfile>): RuntimeDraft {
  const merged = { ...EMPTY_RUNTIME_DRAFT, ...(profile ?? {}), agent_id: agentId };
  const profileId = String(merged.agent_profile_id || `${agentId.replace(/[:]/g, "_")}_runtime`);
  const allowedOps = merged.allowed_operations?.length ? merged.allowed_operations : ["op.model_response"];
  return {
    ...merged,
    agent_profile_id: profileId,
    allowed_task_modes: merged.allowed_task_modes ?? [],
    allowed_runtime_lanes: merged.allowed_runtime_lanes ?? [],
    allowed_operations: allowedOps,
    blocked_operations: merged.blocked_operations ?? [],
    allowed_memory_scopes: merged.allowed_memory_scopes ?? [],
    allowed_context_sections: merged.allowed_context_sections ?? [],
    output_contracts: merged.output_contracts ?? [],
    approval_policy: String(merged.approval_policy || "default"),
    trace_policy: String(merged.trace_policy || "runtime_event_log"),
    lifecycle_policy: String(merged.lifecycle_policy || "orchestration_managed"),
    metadata: merged.metadata ?? { managed_by: "orchestration_console" },
    allowed_task_modes_text: listText(merged.allowed_task_modes ?? []),
    allowed_runtime_lanes_text: listText(merged.allowed_runtime_lanes ?? []),
    allowed_operations_text: listText(allowedOps),
    blocked_operations_text: listText(merged.blocked_operations ?? []),
    allowed_memory_scopes_text: listText(merged.allowed_memory_scopes ?? []),
    allowed_context_sections_text: listText(merged.allowed_context_sections ?? []),
    output_contracts_text: listText(merged.output_contracts ?? []),
  };
}

function runtimePayloadFromDraft(draft: RuntimeDraft) {
  return {
    agent_profile_id: draft.agent_profile_id,
    allowed_task_modes: splitList(draft.allowed_task_modes_text),
    allowed_runtime_lanes: splitList(draft.allowed_runtime_lanes_text),
    allowed_operations: Array.from(new Set(["op.model_response", ...splitList(draft.allowed_operations_text)])),
    blocked_operations: splitList(draft.blocked_operations_text),
    allowed_memory_scopes: splitList(draft.allowed_memory_scopes_text),
    allowed_context_sections: splitList(draft.allowed_context_sections_text),
    output_contracts: splitList(draft.output_contracts_text),
    approval_policy: draft.approval_policy,
    trace_policy: draft.trace_policy,
    lifecycle_policy: draft.lifecycle_policy,
    metadata: { ...(draft.metadata ?? {}), managed_by: "orchestration_console" },
  };
}

function groupDraftFrom(group?: OrchestrationAgentGroup | null): AgentGroupDraft {
  const base = group ?? EMPTY_GROUP_DRAFT;
  return {
    ...base,
    member_agent_ids: base.member_agent_ids ?? [],
    default_topology_template_ids: base.default_topology_template_ids ?? [],
    default_communication_protocol_ids: base.default_communication_protocol_ids ?? [],
    allowed_coordination_task_ids: base.allowed_coordination_task_ids ?? [],
    metadata: base.metadata ?? { managed_by: "orchestration_console" },
    member_agent_ids_text: listText(base.member_agent_ids ?? []),
  };
}

function groupPayloadFromDraft(draft: AgentGroupDraft): OrchestrationAgentGroup {
  const memberAgentIds = splitList(draft.member_agent_ids_text);
  return {
    group_id: draft.group_id,
    title: draft.title,
    group_kind: draft.group_kind,
    coordinator_agent_id: draft.coordinator_agent_id || memberAgentIds[0] || "agent:20",
    member_agent_ids: memberAgentIds,
    description: draft.description,
    default_topology_template_ids: draft.default_topology_template_ids ?? [],
    default_communication_protocol_ids: draft.default_communication_protocol_ids ?? [],
    allowed_coordination_task_ids: draft.allowed_coordination_task_ids ?? [],
    lifecycle_state: draft.lifecycle_state,
    metadata: { ...(draft.metadata ?? {}), managed_by: "orchestration_console" },
  };
}

function searchText(agent: Record<string, unknown>) {
  return [
    agent.agent_id,
    agent.agent_name,
    agent.display_name,
    agent.agent_category,
    agent.interface_target,
    agent.description,
    JSON.stringify(agent.task_scope ?? []),
    JSON.stringify(agent.metadata ?? {}),
    JSON.stringify(agent.runtime_profile ?? {}),
  ]
    .join(" ")
    .toLowerCase();
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "ok" | "warn" | "danger" }) {
  return <span className={`boundary-badge boundary-badge--${tone}`}>{children}</span>;
}

function ToolbarButton({
  children,
  disabled,
  onClick,
  variant = "ghost",
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  variant?: "ghost" | "primary" | "danger";
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

function ProjectionSelectField({
  cards,
  label,
  onChange,
  value,
}: {
  cards: SoulProjectionCard[];
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const options = Array.from(new Set(["", value, ...cards.map((item) => item.projection_id).filter(Boolean)]));
  return (
    <Field label={label}>
      <select value={value || ""} onChange={(event) => onChange(event.target.value)}>
        {options.map((item) => (
          <option key={item || "none"} value={item}>
            {projectionLabel(item, cards)}
          </option>
        ))}
      </select>
    </Field>
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

function SuggestionGrid({
  items,
  onAdd,
}: {
  items: string[];
  onAdd: (item: string) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="boundary-chip-grid">
      {items.slice(0, 18).map((item) => (
        <button className="boundary-chip" key={item} onClick={() => onAdd(item)} type="button">
          <CheckCircle2 size={13} />
          <span>{displayId(item)}</span>
        </button>
      ))}
    </div>
  );
}

export function OrchestrationView() {
  const [catalog, setCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [activeCategory, setActiveCategory] = useState<AgentCategory>("main_agent");
  const [activeLayer, setActiveLayer] = useState<OrchestrationLayer>("registry");
  const [workerDirectoryMode, setWorkerDirectoryMode] = useState<WorkerDirectoryMode>("grouped");
  const [query, setQuery] = useState("");
  const [agentMode, setAgentMode] = useState<"existing" | "new">("existing");
  const [groupMode, setGroupMode] = useState<"existing" | "new">("existing");
  const [agentDraft, setAgentDraft] = useState<AgentDraft>(EMPTY_AGENT_DRAFT);
  const [runtimeDraft, setRuntimeDraft] = useState<RuntimeDraft>(EMPTY_RUNTIME_DRAFT);
  const [groupDraft, setGroupDraft] = useState<AgentGroupDraft>(EMPTY_GROUP_DRAFT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<"" | "agent" | "runtime" | "group" | "create" | "delete">("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [payload, projections] = await Promise.all([getOrchestrationAgents(), getSoulProjectionCards()]);
      setCatalog(payload);
      setProjectionCatalog(projections);
      setSelectedAgentId((current) => current || String(payload.agents[0]?.agent_id || ""));
      setSelectedGroupId((current) => current || String(payload.agent_groups?.[0]?.group_id || ""));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "编排系统加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const agents = useMemo(() => catalog?.agents ?? [], [catalog]);
  const agentGroups = useMemo(() => catalog?.agent_groups ?? [], [catalog]);
  const projectionCards = useMemo(() => projectionCatalog?.cards ?? [], [projectionCatalog]);
  const selectedAgent = agents.find((agent) => String(agent.agent_id) === selectedAgentId) ?? null;
  const selectedGroup = agentGroups.find((group) => group.group_id === selectedGroupId) ?? null;
  const selectedProfile = (selectedAgent?.runtime_profile ?? {}) as Partial<OrchestrationAgentRuntimeProfile>;
  const operationOptions = useMemo(
    () => (catalog?.options.operations ?? []).map((item) => String(item.operation_id || "")).filter(Boolean),
    [catalog],
  );
  const normalizedQuery = query.trim().toLowerCase();
  const visibleAgents = useMemo(
    () => agents.filter((agent) => !normalizedQuery || searchText(agent).includes(normalizedQuery)),
    [agents, normalizedQuery],
  );
  const visibleWorkerAgents = useMemo(
    () => visibleAgents.filter((agent) => agentCategory(agent) === "worker_sub_agent"),
    [visibleAgents],
  );
  const selectedGroupMemberAgents = useMemo(() => {
    const memberIds = new Set((selectedGroup?.member_agent_ids ?? []).map((item) => String(item)));
    return visibleWorkerAgents.filter((agent) => memberIds.has(String(agent.agent_id)));
  }, [selectedGroup, visibleWorkerAgents]);
  const ungroupedWorkerAgents = useMemo(() => {
    const groupedIds = new Set(agentGroups.flatMap((group) => group.member_agent_ids.map((item) => String(item))));
    return visibleWorkerAgents.filter((agent) => !groupedIds.has(String(agent.agent_id)));
  }, [agentGroups, visibleWorkerAgents]);
  const groupDraftMemberIds = useMemo(() => new Set(splitList(groupDraft.member_agent_ids_text)), [groupDraft.member_agent_ids_text]);
  const groupDraftMemberAgents = useMemo(
    () => visibleWorkerAgents.filter((agent) => groupDraftMemberIds.has(String(agent.agent_id))),
    [groupDraftMemberIds, visibleWorkerAgents],
  );
  const groupDraftAvailableAgents = useMemo(
    () => visibleWorkerAgents.filter((agent) => !groupDraftMemberIds.has(String(agent.agent_id))),
    [groupDraftMemberIds, visibleWorkerAgents],
  );
  const groupMembersChanged = useMemo(() => {
    const savedIds = new Set((selectedGroup?.member_agent_ids ?? []).map((item) => String(item)));
    if (savedIds.size !== groupDraftMemberIds.size) return true;
    return Array.from(groupDraftMemberIds).some((agentId) => !savedIds.has(agentId));
  }, [groupDraftMemberIds, selectedGroup]);
  const groupedAgents = useMemo(
    () =>
      CATEGORY_ORDER.map((category) => ({
        category,
        label: CATEGORY_LABELS[category],
        items: visibleAgents.filter((agent) => agentCategory(agent) === category),
      })),
    [visibleAgents],
  );

  useEffect(() => {
    if (!selectedAgent) return;
    setAgentDraft(agentDraftFrom(selectedAgent));
    setRuntimeDraft(runtimeDraftFrom(String(selectedAgent.agent_id), selectedProfile));
    setAgentMode("existing");
    setActiveCategory(agentCategory(selectedAgent));
  }, [selectedAgentId, selectedAgent]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (groupMode === "new") return;
    setGroupDraft(groupDraftFrom(selectedGroup));
  }, [selectedGroup, groupMode]);

  const activeGroup = groupedAgents.find((group) => group.category === activeCategory);
  const agentDeleteBlocked = Boolean(selectedAgent?.builtin);
  const profileMissing = Boolean(selectedAgent && !selectedProfile.agent_profile_id);
  const allowedOps = splitList(runtimeDraft.allowed_operations_text);
  const blockedOps = splitList(runtimeDraft.blocked_operations_text);
  const overlapOps = allowedOps.filter((item) => blockedOps.includes(item));
  const taskScope = splitList(agentDraft.task_scope_text);
  const capabilityRefs = splitList(agentDraft.capability_refs_text);
  const managedObjects = splitList(agentDraft.managed_object_types_text);
  const runtimeSaveBlocked = agentMode === "new" || !agentDraft.agent_id.trim();
  const categoryCounts = groupedAgents.reduce<Record<string, number>>((acc, group) => {
    acc[group.category] = group.items.length;
    return acc;
  }, {});
  const legacySystemKey = String(agentDraft.metadata?.system_key || "");
  const scopeSuggestions = Array.from(new Set([...(catalog?.options.task_modes ?? []), "health_management", "trace_analysis", "memory_management", "permission_management", "development"]));
  const readinessRows = [
    { label: "Agent 名册", value: agentDraft.agent_id || "未保存", ready: Boolean(agentDraft.agent_id && agentDraft.agent_name) },
    { label: "职责覆盖", value: String(taskScope.length), ready: Boolean(taskScope.length) },
    { label: "运行配置", value: runtimeDraft.agent_profile_id || "未配置", ready: !profileMissing && Boolean(runtimeDraft.agent_profile_id) },
    { label: "权限边界", value: `${allowedOps.length}/${blockedOps.length}`, ready: Boolean(allowedOps.length) && !overlapOps.length },
    { label: "上下文输出", value: String(splitList(runtimeDraft.output_contracts_text).length), ready: Boolean(splitList(runtimeDraft.output_contracts_text).length) },
  ];
  const eligibilityChecks = [
    { label: "类别", value: CATEGORY_LABELS[agentDraft.agent_category as AgentCategory] ?? text(agentDraft.agent_category), ready: Boolean(agentDraft.agent_category) },
    { label: "任务范围", value: taskScope.slice(0, 4).join(" / ") || "未配置", ready: Boolean(taskScope.length) },
    { label: "能力引用", value: capabilityRefs.slice(0, 4).join(" / ") || "未配置", ready: Boolean(capabilityRefs.length) || agentDraft.agent_category !== "system_management_agent" },
    { label: "允许操作", value: allowedOps.slice(0, 4).join(" / ") || "未配置", ready: Boolean(allowedOps.length) },
    { label: "阻断冲突", value: overlapOps.length ? overlapOps.join(" / ") : "无", ready: !overlapOps.length },
    { label: "输出契约", value: splitList(runtimeDraft.output_contracts_text).slice(0, 4).join(" / ") || "未配置", ready: Boolean(splitList(runtimeDraft.output_contracts_text).length) },
  ];
  const agentLayerTabs: Array<[OrchestrationLayer, string, string]> = [
    ["registry", "名册", agentMode === "new" ? "草稿" : ""],
    ["scope", "职责覆盖", `${taskScope.length}`],
    ["runtime", "运行", runtimeDraft.agent_profile_id ? "已配置" : ""],
    ["permissions", "权限能力", `${allowedOps.length}/${blockedOps.length}`],
    ["context", "上下文输出", `${splitList(runtimeDraft.output_contracts_text).length}`],
    ["eligibility", "承接资格", overlapOps.length ? "冲突" : ""],
  ];
  const layerTabs: Array<[OrchestrationLayer, string, string]> = activeCategory === "worker_sub_agent"
    ? workerDirectoryMode === "grouped" && !selectedAgent && agentMode !== "new"
      ? [["groups", "组", String(agentGroups.length)]]
      : workerDirectoryMode === "grouped"
        ? [["groups", "组", String(agentGroups.length)]]
        : agentLayerTabs
    : agentLayerTabs;

  function selectCategory(category: AgentCategory) {
    setActiveCategory(category);
    const first = visibleAgents.find((agent) => agentCategory(agent) === category);
    setAgentMode("existing");
    if (category === "worker_sub_agent") {
      setWorkerDirectoryMode("grouped");
      setActiveLayer("groups");
      setGroupMode("existing");
      const firstGroup = agentGroups[0];
      setSelectedGroupId(firstGroup?.group_id || "");
      setSelectedAgentId("");
    } else {
      setActiveLayer("registry");
      setSelectedAgentId(String(first?.agent_id || ""));
    }
  }

  function selectAgent(agentId: string) {
    const agent = agents.find((item) => String(item.agent_id) === agentId);
    setSelectedAgentId(agentId);
    setAgentMode("existing");
    setGroupMode("existing");
    if (agentCategory(agent) === "worker_sub_agent") {
      const group = agentGroups.find((item) => item.member_agent_ids.some((memberId) => String(memberId) === agentId));
      setActiveCategory("worker_sub_agent");
      if (group) {
        setWorkerDirectoryMode("grouped");
        setSelectedGroupId(group.group_id);
      } else {
        setWorkerDirectoryMode("ungrouped");
      }
    }
    setActiveLayer("registry");
  }

  function selectSubAgentGroup(groupId: string) {
    setSelectedGroupId(groupId);
    setGroupMode("existing");
    setWorkerDirectoryMode("grouped");
    setSelectedAgentId("");
    setActiveLayer("groups");
  }

  function selectWorkerDirectoryMode(mode: WorkerDirectoryMode) {
    setWorkerDirectoryMode(mode);
    setAgentMode("existing");
    setGroupMode("existing");
    if (mode === "grouped") {
      setSelectedAgentId("");
      setSelectedGroupId((current) => current || agentGroups[0]?.group_id || "");
      setActiveLayer("groups");
      return;
    }
    setSelectedGroupId("");
    setSelectedAgentId(String(ungroupedWorkerAgents[0]?.agent_id || ""));
    setActiveLayer(ungroupedWorkerAgents[0] ? "registry" : "groups");
  }

  function addRuntimeLine(field: keyof RuntimeDraft, value: string) {
    if (!value) return;
    setRuntimeDraft((current) => ({
      ...current,
      [field]: Array.from(new Set([...splitList(String(current[field] || "")), value])).join("\n"),
    }));
  }

  function addAgentLine(field: "task_scope_text" | "managed_object_types_text" | "capability_refs_text", value: string) {
    if (!value) return;
    setAgentDraft((current) => ({
      ...current,
      [field]: Array.from(new Set([...splitList(String(current[field] || "")), value])).join("\n"),
    }));
  }

  function startBlankAgentDraft() {
    setAgentMode("new");
    setGroupMode("existing");
    setSelectedAgentId("");
    setActiveCategory("worker_sub_agent");
    setWorkerDirectoryMode("ungrouped");
    setActiveLayer("registry");
    setAgentDraft({ ...EMPTY_AGENT_DRAFT, metadata: { ...EMPTY_AGENT_DRAFT.metadata } });
    setRuntimeDraft({ ...EMPTY_RUNTIME_DRAFT, metadata: { ...EMPTY_RUNTIME_DRAFT.metadata } });
    setNotice("已进入新 Agent 草稿。先保存 Agent 名册，再配置运行档案。");
    setError("");
  }

  async function createWorkerDraft() {
    setSaving("create");
    setError("");
    setNotice("");
    try {
      const payload = await getNextOrchestrationWorkerAgentId();
      setAgentMode("new");
      setGroupMode("existing");
      setSelectedAgentId("");
      setActiveCategory("worker_sub_agent");
      setWorkerDirectoryMode("ungrouped");
      setActiveLayer("registry");
      setAgentDraft({
        ...EMPTY_AGENT_DRAFT,
        agent_id: payload.agent_id,
        agent_name: `${payload.agent_id} 工作子 Agent`,
        agent_category: "worker_sub_agent",
        interface_target: "worker_task_console",
        metadata: { managed_by: "orchestration_console" },
      });
      setRuntimeDraft({
        ...EMPTY_RUNTIME_DRAFT,
        agent_id: payload.agent_id,
        agent_profile_id: `${payload.agent_id.replace(/[:]/g, "_")}_runtime`,
        metadata: { managed_by: "orchestration_console" },
      });
      setNotice(`已生成工作子 Agent 草稿：${payload.agent_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "生成工作子 Agent 草稿失败");
    } finally {
      setSaving("");
    }
  }

  async function saveAgent() {
    if (!agentDraft.agent_id.trim()) {
      setError("Agent 标识不能为空。");
      return;
    }
    if (!agentDraft.agent_name.trim()) {
      setError("Agent 名称不能为空。");
      return;
    }
    setSaving("agent");
    setError("");
    setNotice("");
    try {
      const metadata = {
        ...(agentDraft.metadata ?? {}),
        managed_by: "orchestration_console",
        managed_object_types: managedObjects,
        capability_refs: capabilityRefs,
      };
      const payload = await upsertOrchestrationAgent(agentDraft.agent_id, {
        ...agentDraft,
        task_scope: taskScope,
        metadata,
      });
      setCatalog(payload);
      setSelectedAgentId(agentDraft.agent_id);
      setAgentMode("existing");
      setNotice(`${agentDraft.agent_name} 的 Agent 名册已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 Agent 名册失败");
    } finally {
      setSaving("");
    }
  }

  async function saveRuntimeProfile() {
    if (!agentDraft.agent_id.trim()) {
      setError("请先保存 Agent 名册。");
      return;
    }
    setSaving("runtime");
    setError("");
    setNotice("");
    try {
      const payload = await updateOrchestrationAgentRuntimeProfile(agentDraft.agent_id, runtimePayloadFromDraft(runtimeDraft));
      setCatalog(payload);
      setNotice(`${agentDraft.agent_name || agentDraft.agent_id} 的运行档案已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存运行档案失败");
    } finally {
      setSaving("");
    }
  }

  async function saveAgentGroup() {
    if (!groupDraft.group_id.trim()) {
      setError("子 Agent 组标识不能为空。");
      return;
    }
    if (!groupDraft.title.trim()) {
      setError("子 Agent 组名称不能为空。");
      return;
    }
    setSaving("group");
    setError("");
    setNotice("");
    try {
      const payload = await upsertOrchestrationAgentGroup(groupDraft.group_id, groupPayloadFromDraft(groupDraft));
      setCatalog(payload);
      setSelectedGroupId(groupDraft.group_id);
      setGroupMode("existing");
      setNotice(`${groupDraft.title} 已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 Agent 组失败");
    } finally {
      setSaving("");
    }
  }

  function startBlankGroupDraft() {
    setActiveCategory("worker_sub_agent");
    setWorkerDirectoryMode("grouped");
    setActiveLayer("groups");
    setGroupMode("new");
    setSelectedGroupId("");
    setGroupDraft({
      ...EMPTY_GROUP_DRAFT,
      group_id: makeCustomGroupId(agentGroups),
      title: "新子 Agent 组",
      metadata: { managed_by: "orchestration_console" },
    });
    setNotice("已进入子 Agent 组草稿。");
    setError("");
  }

  function toggleGroupMember(agentId: string) {
    setGroupDraft((current) => {
      const currentIds = splitList(current.member_agent_ids_text);
      const nextIds = currentIds.includes(agentId)
        ? currentIds.filter((item) => item !== agentId)
        : [...currentIds, agentId];
      return { ...current, member_agent_ids_text: nextIds.join("\n") };
    });
  }

  function includeAllVisibleWorkers() {
    setGroupDraft((current) => ({
      ...current,
      member_agent_ids_text: visibleWorkerAgents.map((agent) => String(agent.agent_id)).join("\n"),
    }));
  }

  function clearGroupMembers() {
    setGroupDraft((current) => ({ ...current, member_agent_ids_text: "" }));
  }

  async function removeAgent() {
    if (!selectedAgent) return;
    setSaving("delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteOrchestrationAgent(String(selectedAgent.agent_id));
      const firstWorkerAgent = payload.agents.find((agent) => agentCategory(agent) === "worker_sub_agent");
      setCatalog(payload);
      setSelectedAgentId(String(firstWorkerAgent?.agent_id || payload.agents[0]?.agent_id || ""));
      setGroupMode("existing");
      setNotice(`${displayName(selectedAgent)} 已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 Agent 失败");
    } finally {
      setSaving("");
    }
  }

  return (
    <div className="workspace-view boundary-console orchestration-boundary">
      <header className="boundary-hero">
        <div>
          <span>Agent Runtime Studio</span>
          <h2>编排系统工作台</h2>
          <p>Agent 名册、职责覆盖、运行档案、权限与上下文输出</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton onClick={() => void load()}><RefreshCw size={15} />刷新</ToolbarButton>
          <ToolbarButton onClick={startBlankAgentDraft}><Plus size={15} />新建 Agent</ToolbarButton>
          <ToolbarButton onClick={startBlankGroupDraft}><Network size={15} />新建 Agent 组</ToolbarButton>
          <ToolbarButton disabled={saving === "create"} onClick={() => void createWorkerDraft()}><CopyPlus size={15} />生成工作子 Agent</ToolbarButton>
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}
      {notice ? <div className="boundary-notice"><CheckCircle2 size={16} />{notice}</div> : null}

      <section className="boundary-workbench orchestration-workbench">
        <aside className="boundary-rail orchestration-subagent-rail">
          <div className="boundary-rail__head">
            <strong>Agent 分类</strong>
            <span>{agents.length}</span>
          </div>
          <div className="boundary-search">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Agent / 职责 / 能力" />
          </div>
          <div className="orchestration-agent-type-strip" aria-label="Agent 类型快速入口">
            {CATEGORY_ORDER.map((category) => (
              <button className={activeCategory === category ? "active" : ""} key={category} onClick={() => selectCategory(category)} type="button">
                <span>{CATEGORY_LABELS[category]}</span>
                <b>{categoryCounts[category] ?? 0}</b>
              </button>
            ))}
          </div>
          {activeCategory === "worker_sub_agent" ? (
            <div className="orchestration-subagent-mode-strip" aria-label="子 Agent 目录切换">
              <button className={workerDirectoryMode === "grouped" ? "active" : ""} onClick={() => selectWorkerDirectoryMode("grouped")} type="button">有组</button>
              <button className={workerDirectoryMode === "ungrouped" ? "active" : ""} onClick={() => selectWorkerDirectoryMode("ungrouped")} type="button">无组</button>
            </div>
          ) : null}
          <div className="boundary-list boundary-list--scroll">
            {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
            {activeCategory === "worker_sub_agent" && workerDirectoryMode === "grouped" ? (
              <>
                <div className="orchestration-list-label">有组子 Agent</div>
                {agentGroups.map((group) => (
                  <div className={group.group_id === selectedGroupId ? "orchestration-group-tree orchestration-group-tree--active" : "orchestration-group-tree"} key={group.group_id}>
                    <button
                      className="boundary-list-row"
                      onClick={() => selectSubAgentGroup(group.group_id)}
                      type="button"
                    >
                      <strong>{group.title}</strong>
                      <span>{group.member_agent_ids.length} 个成员</span>
                    </button>
                  </div>
                ))}
                {!loading && !agentGroups.length ? <div className="boundary-empty">暂无子 Agent 组。</div> : null}
              </>
            ) : null}
            {activeCategory === "worker_sub_agent" && workerDirectoryMode === "ungrouped" ? (
              <>
                <div className="orchestration-list-label">无组子 Agent</div>
                {ungroupedWorkerAgents.map((agent) => (
                  <button className={String(agent.agent_id) === selectedAgentId ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"} key={String(agent.agent_id)} onClick={() => selectAgent(String(agent.agent_id))} type="button">
                    <strong>{displayName(agent)}</strong>
                  </button>
                ))}
                {!loading && !ungroupedWorkerAgents.length ? <div className="boundary-empty">暂无无组子 Agent。</div> : null}
              </>
            ) : null}
            {(activeCategory === "worker_sub_agent" ? [] : activeGroup?.items ?? []).map((agent) => {
              return (
                <button className={String(agent.agent_id) === selectedAgentId ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"} key={String(agent.agent_id)} onClick={() => selectAgent(String(agent.agent_id))} type="button">
                  <strong>{displayName(agent)}</strong>
                </button>
              );
            })}
            {!loading && (
              activeCategory === "worker_sub_agent"
                ? workerDirectoryMode === "grouped"
                  ? !agentGroups.length
                  : !ungroupedWorkerAgents.length
                : !(activeGroup?.items ?? []).length
            ) ? <div className="boundary-empty">当前层级暂无 Agent。</div> : null}
          </div>
        </aside>

        <main className="boundary-main">
          <nav className="boundary-layer-tabs" aria-label="编排系统层级">
            {layerTabs.map(([value, label, meta]) => (
              <button className={activeLayer === value ? "boundary-layer-tabs__item boundary-layer-tabs__item--active" : "boundary-layer-tabs__item"} key={value} onClick={() => setActiveLayer(value)} type="button">
                <span>{label}</span>
                <small>{meta}</small>
              </button>
            ))}
          </nav>

          {!selectedAgent && agentMode !== "new" && !(activeCategory === "worker_sub_agent" && activeLayer === "groups") ? <div className="boundary-empty boundary-empty--large">请选择一个 Agent，或新建 Agent 草稿。</div> : null}

          {activeCategory === "worker_sub_agent" && activeLayer === "groups" ? (
            <section className="boundary-card orchestration-group-main">
                <header>
                  <strong>{groupDraft.title || "子 Agent 组草稿"}</strong>
                  <div className="boundary-inline-actions">
                    {groupMembersChanged ? <Badge tone="warn">未保存</Badge> : <Badge tone="ok">已同步</Badge>}
                    <ToolbarButton disabled={saving === "group"} onClick={() => void saveAgentGroup()} variant="primary"><Save size={15} />保存组</ToolbarButton>
                  </div>
                </header>
                <div className="boundary-form">
                  <Field label="组名"><input value={groupDraft.title} onChange={(event) => setGroupDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                  <Field label="说明" wide><textarea value={groupDraft.description} onChange={(event) => setGroupDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                </div>
                <div className="orchestration-member-toolbar">
                  <button disabled={!groupDraftAvailableAgents.length} onClick={includeAllVisibleWorkers} type="button">全部加入</button>
                  <button disabled={!groupDraftMemberAgents.length} onClick={clearGroupMembers} type="button">清空成员</button>
                </div>
                <div className="orchestration-member-workbench">
                  <section className="orchestration-member-column">
                    <header className="boundary-panel-head">
                      <strong>已进组</strong>
                      <span>{groupDraftMemberAgents.length}</span>
                    </header>
                    <div className="orchestration-member-picker">
                      {groupDraftMemberAgents.map((agent) => (
                        <button
                          className="orchestration-member-card orchestration-member-card--selected"
                          key={String(agent.agent_id)}
                          onClick={() => toggleGroupMember(String(agent.agent_id))}
                          type="button"
                        >
                          <strong>{displayName(agent)}</strong>
                          <span>点击移出</span>
                        </button>
                      ))}
                      {!groupDraftMemberAgents.length ? <div className="boundary-empty">当前还没有子 Agent 进入这个组。</div> : null}
                    </div>
                  </section>
                  <section className="orchestration-member-column">
                    <header className="boundary-panel-head">
                      <strong>未进组</strong>
                      <span>{groupDraftAvailableAgents.length}</span>
                    </header>
                    <div className="orchestration-member-picker">
                      {groupDraftAvailableAgents.map((agent) => (
                        <button
                          className="orchestration-member-card"
                          key={String(agent.agent_id)}
                          onClick={() => toggleGroupMember(String(agent.agent_id))}
                          type="button"
                        >
                          <strong>{displayName(agent)}</strong>
                          <span>点击加入</span>
                        </button>
                      ))}
                      {!groupDraftAvailableAgents.length ? <div className="boundary-empty">当前没有可加入的子 Agent。</div> : null}
                    </div>
                  </section>
                </div>
            </section>
          ) : null}

          {activeLayer !== "groups" && (selectedAgent || agentMode === "new") ? (
            <>
              <section className="boundary-layer-grid boundary-layer-grid--wide">
                <div className="boundary-card boundary-card--summary">
                  <header>
                    <strong>{agentDraft.agent_name || agentDraft.agent_id || "新 Agent 草稿"}</strong>
                    <Badge tone={agentDraft.enabled ? "ok" : "warn"}>{agentDraft.enabled ? "启用" : "停用"}</Badge>
                  </header>
                  <div className="boundary-metric-grid">
                    <ReadinessCard label="类别" ready={Boolean(agentDraft.agent_category)} value={CATEGORY_LABELS[agentDraft.agent_category as AgentCategory] ?? "未配置"} />
                    <ReadinessCard label="职责范围" ready={Boolean(taskScope.length)} value={String(taskScope.length)} />
                    <ReadinessCard label="运行" ready={!profileMissing && Boolean(runtimeDraft.agent_profile_id)} value={runtimeDraft.agent_profile_id || "未配置"} />
                    <ReadinessCard label="权限冲突" ready={!overlapOps.length} value={overlapOps.length ? String(overlapOps.length) : "0"} />
                  </div>
                </div>
                <aside className="boundary-card">
                  <header><strong>保存</strong></header>
                  <div className="boundary-actions boundary-actions--stack">
                    <ToolbarButton disabled={saving === "agent"} onClick={() => void saveAgent()} variant="primary"><Save size={15} />保存 Agent 名册</ToolbarButton>
                    <ToolbarButton disabled={saving === "runtime" || runtimeSaveBlocked} onClick={() => void saveRuntimeProfile()} variant="primary"><Gauge size={15} />保存运行档案</ToolbarButton>
                    <ToolbarButton disabled={saving === "delete" || agentDeleteBlocked || agentMode === "new"} onClick={() => void removeAgent()} variant="danger"><Trash2 size={15} />删除 Agent</ToolbarButton>
                  </div>
                </aside>
              </section>

              {activeLayer === "registry" ? (
                <section className="boundary-card">
                  <header><strong>Agent 名册</strong><Badge>{agentMode === "new" ? "草稿" : text(selectedAgent?.builtin ? "内置" : "自定义")}</Badge></header>
                  <div className="boundary-form">
                    <Field label="Agent 标识"><input value={agentDraft.agent_id} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_id: event.target.value }))} /></Field>
                    <Field label="名称"><input value={agentDraft.agent_name} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_name: event.target.value }))} /></Field>
                    <Field label="类别">
                      <select value={agentDraft.agent_category} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_category: event.target.value as AgentCategory }))}>
                        <option value="main_agent">主 Agent</option>
                        <option value="system_management_agent">系统管理 Agent</option>
                        <option value="worker_sub_agent">子 Agent</option>
                      </select>
                    </Field>
                    <Field label="入口位置"><input value={agentDraft.interface_target || ""} onChange={(event) => setAgentDraft((value) => ({ ...value, interface_target: event.target.value }))} /></Field>
                    <Field label="默认灵魂"><input value={agentDraft.default_soul_id || ""} onChange={(event) => setAgentDraft((value) => ({ ...value, default_soul_id: event.target.value }))} /></Field>
                    <ProjectionSelectField cards={projectionCards} label="默认投影" onChange={(value) => setAgentDraft((current) => ({ ...current, default_projection_id: value }))} value={agentDraft.default_projection_id || ""} />
                    <Field label="职责说明" wide><textarea value={agentDraft.description || ""} onChange={(event) => setAgentDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                    <label className="boundary-check"><input checked={Boolean(agentDraft.enabled)} onChange={(event) => setAgentDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用 Agent</label>
                    <label className="boundary-check"><input checked={Boolean(agentDraft.editable)} onChange={(event) => setAgentDraft((value) => ({ ...value, editable: event.target.checked }))} type="checkbox" />允许编辑</label>
                  </div>
                  {legacySystemKey ? <div className="boundary-legacy">legacy system_key：{legacySystemKey}</div> : null}
                </section>
              ) : null}

              {activeLayer === "scope" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>固定职责与任务覆盖范围</strong><Badge>{taskScope.length} 项</Badge></header>
                    <div className="boundary-form">
                      <Field label="任务覆盖范围" wide><textarea value={agentDraft.task_scope_text} onChange={(event) => setAgentDraft((value) => ({ ...value, task_scope_text: event.target.value }))} /></Field>
                      <Field label="可管理对象类型" wide><textarea value={agentDraft.managed_object_types_text} onChange={(event) => setAgentDraft((value) => ({ ...value, managed_object_types_text: event.target.value }))} /></Field>
                      <Field label="能力引用" wide><textarea value={agentDraft.capability_refs_text} onChange={(event) => setAgentDraft((value) => ({ ...value, capability_refs_text: event.target.value }))} /></Field>
                    </div>
                    <SuggestionGrid items={scopeSuggestions} onAdd={(item) => addAgentLine("task_scope_text", item)} />
                  </div>
                  <aside className="boundary-card">
                    <header><strong>覆盖摘要</strong></header>
                    <div className="boundary-kv">
                      <p><span>任务范围</span><strong>{displayList(taskScope)}</strong></p>
                      <p><span>管理对象</span><strong>{displayList(managedObjects)}</strong></p>
                      <p><span>能力</span><strong>{displayList(capabilityRefs)}</strong></p>
                    </div>
                  </aside>
                </section>
              ) : null}

              {activeLayer === "runtime" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>运行档案</strong><Badge>{runtimeDraft.agent_profile_id || "草稿"}</Badge></header>
                    <div className="boundary-form">
                      <Field label="运行档案标识"><input value={runtimeDraft.agent_profile_id} onChange={(event) => setRuntimeDraft((value) => ({ ...value, agent_profile_id: event.target.value }))} /></Field>
                      <Field label="审批策略">
                        <select value={runtimeDraft.approval_policy} onChange={(event) => setRuntimeDraft((value) => ({ ...value, approval_policy: event.target.value }))}>
                          {(catalog?.options.approval_policies ?? ["default"]).map((item) => <option key={item} value={item}>{displayId(item)}</option>)}
                        </select>
                      </Field>
                      <Field label="追踪策略">
                        <select value={runtimeDraft.trace_policy} onChange={(event) => setRuntimeDraft((value) => ({ ...value, trace_policy: event.target.value }))}>
                          {(catalog?.options.trace_policies ?? ["runtime_event_log"]).map((item) => <option key={item} value={item}>{displayId(item)}</option>)}
                        </select>
                      </Field>
                      <Field label="生命周期"><input value={runtimeDraft.lifecycle_policy} onChange={(event) => setRuntimeDraft((value) => ({ ...value, lifecycle_policy: event.target.value }))} /></Field>
                      <Field label="允许任务模式" wide><textarea value={runtimeDraft.allowed_task_modes_text} onChange={(event) => setRuntimeDraft((value) => ({ ...value, allowed_task_modes_text: event.target.value }))} /></Field>
                      <Field label="允许运行通道" wide><textarea value={runtimeDraft.allowed_runtime_lanes_text} onChange={(event) => setRuntimeDraft((value) => ({ ...value, allowed_runtime_lanes_text: event.target.value }))} /></Field>
                    </div>
                    <SuggestionGrid items={catalog?.options.task_modes ?? []} onAdd={(item) => addRuntimeLine("allowed_task_modes_text", item)} />
                    <SuggestionGrid items={catalog?.options.runtime_lanes ?? []} onAdd={(item) => addRuntimeLine("allowed_runtime_lanes_text", item)} />
                  </div>
                  <aside className="boundary-card">
                    <header><strong>运行摘要</strong></header>
                    <div className="boundary-kv">
                      <p><span>任务模式</span><strong>{displayList(splitList(runtimeDraft.allowed_task_modes_text))}</strong></p>
                      <p><span>运行通道</span><strong>{displayList(splitList(runtimeDraft.allowed_runtime_lanes_text))}</strong></p>
                    </div>
                  </aside>
                </section>
              ) : null}

              {activeLayer === "permissions" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>权限与能力边界</strong><Badge tone={overlapOps.length ? "danger" : "ok"}>{overlapOps.length ? "冲突" : "清晰"}</Badge></header>
                    {overlapOps.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{overlapOps.join(" / ")} 同时出现在允许和阻断列表。</div> : null}
                    <div className="boundary-form">
                      <Field label="允许操作" wide><textarea value={runtimeDraft.allowed_operations_text} onChange={(event) => setRuntimeDraft((value) => ({ ...value, allowed_operations_text: event.target.value }))} /></Field>
                      <Field label="阻断操作" wide><textarea value={runtimeDraft.blocked_operations_text} onChange={(event) => setRuntimeDraft((value) => ({ ...value, blocked_operations_text: event.target.value }))} /></Field>
                    </div>
                    <SuggestionGrid items={operationOptions} onAdd={(item) => addRuntimeLine("allowed_operations_text", item)} />
                  </div>
                  <aside className="boundary-card">
                    <header><strong>权限摘要</strong></header>
                    <div className="boundary-kv">
                      <p><span>允许</span><strong>{allowedOps.length}</strong></p>
                      <p><span>阻断</span><strong>{blockedOps.length}</strong></p>
                      <p><span>冲突</span><strong>{displayList(overlapOps, "无")}</strong></p>
                    </div>
                  </aside>
                </section>
              ) : null}

              {activeLayer === "context" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>记忆、上下文、输出边界</strong><Badge>{splitList(runtimeDraft.output_contracts_text).length} 项输出</Badge></header>
                    <div className="boundary-form">
                      <Field label="允许记忆范围" wide><textarea value={runtimeDraft.allowed_memory_scopes_text} onChange={(event) => setRuntimeDraft((value) => ({ ...value, allowed_memory_scopes_text: event.target.value }))} /></Field>
                      <Field label="允许上下文段" wide><textarea value={runtimeDraft.allowed_context_sections_text} onChange={(event) => setRuntimeDraft((value) => ({ ...value, allowed_context_sections_text: event.target.value }))} /></Field>
                      <Field label="输出契约" wide><textarea value={runtimeDraft.output_contracts_text} onChange={(event) => setRuntimeDraft((value) => ({ ...value, output_contracts_text: event.target.value }))} /></Field>
                    </div>
                    <SuggestionGrid items={catalog?.options.memory_scopes ?? []} onAdd={(item) => addRuntimeLine("allowed_memory_scopes_text", item)} />
                    <SuggestionGrid items={catalog?.options.context_sections ?? []} onAdd={(item) => addRuntimeLine("allowed_context_sections_text", item)} />
                    <SuggestionGrid items={catalog?.options.output_contracts ?? []} onAdd={(item) => addRuntimeLine("output_contracts_text", item)} />
                  </div>
                  <aside className="boundary-card">
                    <header><strong>边界摘要</strong></header>
                    <div className="boundary-kv">
                      <p><span>记忆</span><strong>{displayList(splitList(runtimeDraft.allowed_memory_scopes_text))}</strong></p>
                      <p><span>上下文</span><strong>{displayList(splitList(runtimeDraft.allowed_context_sections_text))}</strong></p>
                      <p><span>输出</span><strong>{displayList(splitList(runtimeDraft.output_contracts_text))}</strong></p>
                    </div>
                  </aside>
                </section>
              ) : null}

              {activeLayer === "eligibility" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>承接资格预览</strong><Badge tone={eligibilityChecks.every((item) => item.ready) ? "ok" : "warn"}>{eligibilityChecks.every((item) => item.ready) ? "可承接" : "未完整"}</Badge></header>
                    <div className="boundary-readiness-list boundary-readiness-list--grid">
                      {eligibilityChecks.map((item) => <ReadinessCard key={item.label} {...item} />)}
                    </div>
                  </div>
                  <aside className="boundary-card">
                    <header><strong>桥接出口</strong></header>
                    <div className="boundary-kv">
                      <p><span>候选依据</span><strong>类别 / 职责 / 权限 / 上下文 / 输出</strong></p>
                      <p><span>运行证据</span><strong>任务运行 / Agent 运行 / 追踪</strong></p>
                      <p><span>实测记录</span><strong>docs/系统规划/任务系统实测记录/</strong></p>
                    </div>
                  </aside>
                </section>
              ) : null}
            </>
          ) : null}
        </main>
      </section>
    </div>
  );
}
