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
  getNextOrchestrationWorkerAgentId,
  getOrchestrationAgents,
  upsertOrchestrationAgent,
  upsertOrchestrationAgentGroup,
  updateOrchestrationAgentRuntimeProfile,
  type OrchestrationAgentGroup,
  type OrchestrationAgentRuntimeCatalog,
  type OrchestrationAgentRuntimeProfile,
  type OrchestrationAgentUpsertPayload,
} from "@/lib/api";

type AgentCategory = "main_agent" | "system_management_agent" | "worker_sub_agent";
type OrchestrationLayer = "registry" | "groups" | "scope" | "runtime" | "permissions" | "context" | "eligibility";

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
  default_topology_template_ids_text: string;
  default_communication_protocol_ids_text: string;
  allowed_coordination_task_ids_text: string;
};

const CATEGORY_ORDER: AgentCategory[] = ["main_agent", "system_management_agent", "worker_sub_agent"];

const CATEGORY_LABELS: Record<AgentCategory, string> = {
  main_agent: "主 Agent",
  system_management_agent: "系统管理 Agent",
  worker_sub_agent: "子/工作子 Agent",
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
  default_topology_template_ids_text: "",
  default_communication_protocol_ids_text: "",
  allowed_coordination_task_ids_text: "",
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
    default_topology_template_ids_text: listText(base.default_topology_template_ids ?? []),
    default_communication_protocol_ids_text: listText(base.default_communication_protocol_ids ?? []),
    allowed_coordination_task_ids_text: listText(base.allowed_coordination_task_ids ?? []),
  };
}

function groupPayloadFromDraft(draft: AgentGroupDraft): OrchestrationAgentGroup {
  return {
    group_id: draft.group_id,
    title: draft.title,
    group_kind: draft.group_kind,
    coordinator_agent_id: draft.coordinator_agent_id,
    member_agent_ids: splitList(draft.member_agent_ids_text),
    description: draft.description,
    default_topology_template_ids: splitList(draft.default_topology_template_ids_text),
    default_communication_protocol_ids: splitList(draft.default_communication_protocol_ids_text),
    allowed_coordination_task_ids: splitList(draft.allowed_coordination_task_ids_text),
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

function ReadinessCard({ label, value, ready }: { label: string; value: string; ready: boolean }) {
  return (
    <article className={ready ? "boundary-readiness boundary-readiness--ready" : "boundary-readiness"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{ready ? "ready" : "missing"}</small>
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
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [activeCategory, setActiveCategory] = useState<AgentCategory>("main_agent");
  const [activeLayer, setActiveLayer] = useState<OrchestrationLayer>("registry");
  const [query, setQuery] = useState("");
  const [agentMode, setAgentMode] = useState<"existing" | "new">("existing");
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
      const payload = await getOrchestrationAgents();
      setCatalog(payload);
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
  const selectedAgent = agents.find((agent) => String(agent.agent_id) === selectedAgentId) ?? null;
  const selectedGroup = agentGroups.find((group) => group.group_id === selectedGroupId) ?? agentGroups[0] ?? null;
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
    setGroupDraft(groupDraftFrom(selectedGroup));
  }, [selectedGroup]);

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
    { label: "Runtime Profile", value: runtimeDraft.agent_profile_id || "未配置", ready: !profileMissing && Boolean(runtimeDraft.agent_profile_id) },
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

  function selectCategory(category: AgentCategory) {
    setActiveCategory(category);
    const first = visibleAgents.find((agent) => agentCategory(agent) === category);
    setAgentMode("existing");
    setSelectedAgentId(String(first?.agent_id || ""));
  }

  function selectAgent(agentId: string) {
    setSelectedAgentId(agentId);
    setAgentMode("existing");
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
    setSelectedAgentId("");
    setActiveCategory("worker_sub_agent");
    setActiveLayer("registry");
    setAgentDraft({ ...EMPTY_AGENT_DRAFT, metadata: { ...EMPTY_AGENT_DRAFT.metadata } });
    setRuntimeDraft({ ...EMPTY_RUNTIME_DRAFT, metadata: { ...EMPTY_RUNTIME_DRAFT.metadata } });
    setNotice("已进入新 Agent 草稿。先保存 Agent 名册，再配置 Runtime Profile。");
    setError("");
  }

  async function createWorkerDraft() {
    setSaving("create");
    setError("");
    setNotice("");
    try {
      const payload = await getNextOrchestrationWorkerAgentId();
      setAgentMode("new");
      setSelectedAgentId("");
      setActiveCategory("worker_sub_agent");
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
      setError("Agent ID 不能为空。");
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
      setNotice(`${agentDraft.agent_name || agentDraft.agent_id} 的 Runtime Profile 已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 Runtime Profile 失败");
    } finally {
      setSaving("");
    }
  }

  async function saveAgentGroup() {
    if (!groupDraft.group_id.trim()) {
      setError("Agent 组 ID 不能为空。");
      return;
    }
    if (!groupDraft.title.trim()) {
      setError("Agent 组标题不能为空。");
      return;
    }
    setSaving("group");
    setError("");
    setNotice("");
    try {
      const payload = await upsertOrchestrationAgentGroup(groupDraft.group_id, groupPayloadFromDraft(groupDraft));
      setCatalog(payload);
      setSelectedGroupId(groupDraft.group_id);
      setNotice(`${groupDraft.title} 已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 Agent 组失败");
    } finally {
      setSaving("");
    }
  }

  function startBlankGroupDraft() {
    setActiveLayer("groups");
    setSelectedGroupId("");
    setGroupDraft({
      ...EMPTY_GROUP_DRAFT,
      group_id: "group.custom.coordination_team",
      title: "新常态协调组",
      metadata: { managed_by: "orchestration_console" },
    });
    setNotice("已进入 Agent 组草稿。");
    setError("");
  }

  async function removeAgent() {
    if (!selectedAgent) return;
    setSaving("delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteOrchestrationAgent(String(selectedAgent.agent_id));
      setCatalog(payload);
      setSelectedAgentId(String(payload.agents[0]?.agent_id || ""));
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
          <p>Agent 名册、职责覆盖、Runtime Profile、权限与上下文输出</p>
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
        <aside className="boundary-rail">
          <div className="boundary-rail__head">
            <strong>Agent 分类</strong>
            <span>{agents.length}</span>
          </div>
          <div className="boundary-category-grid">
            {CATEGORY_ORDER.map((category) => (
              <button className={activeCategory === category ? "boundary-domain boundary-domain--active" : "boundary-domain"} key={category} onClick={() => selectCategory(category)} type="button">
                <strong>{CATEGORY_LABELS[category]}</strong>
                <span>{displayId(category)}</span>
                <small>{categoryCounts[category] ?? 0} 个 Agent</small>
              </button>
            ))}
          </div>
          <div className="boundary-search">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Agent / 职责 / 能力" />
          </div>
          <div className="boundary-list boundary-list--scroll">
            {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
            {activeGroup?.items.map((agent) => {
              const runtimeProfile = (agent.runtime_profile ?? {}) as Partial<OrchestrationAgentRuntimeProfile>;
              return (
                <button className={String(agent.agent_id) === selectedAgentId ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"} key={String(agent.agent_id)} onClick={() => selectAgent(String(agent.agent_id))} type="button">
                  <strong>{displayName(agent)}</strong>
                  <span>{displayId(agent.agent_id)} · {runtimeProfile.agent_profile_id ? "Runtime 已配置" : "Runtime 未配置"}</span>
                </button>
              );
            })}
            {!loading && !activeGroup?.items.length ? <div className="boundary-empty">当前分类暂无 Agent。</div> : null}
          </div>
        </aside>

        <main className="boundary-main">
          <nav className="boundary-layer-tabs" aria-label="编排系统层级">
            {([
              ["registry", "Agent 名册", displayId(agentDraft.agent_id || "draft")],
              ["groups", "Agent 组", `${agentGroups.length}`],
              ["scope", "职责覆盖", `${taskScope.length}`],
              ["runtime", "Runtime", displayId(runtimeDraft.agent_profile_id || "missing")],
              ["permissions", "权限能力", `${allowedOps.length}/${blockedOps.length}`],
              ["context", "上下文输出", `${splitList(runtimeDraft.output_contracts_text).length}`],
              ["eligibility", "承接资格", overlapOps.length ? "blocked" : "preview"],
            ] as Array<[OrchestrationLayer, string, string]>).map(([value, label, meta]) => (
              <button className={activeLayer === value ? "boundary-layer-tabs__item boundary-layer-tabs__item--active" : "boundary-layer-tabs__item"} key={value} onClick={() => setActiveLayer(value)} type="button">
                <span>{label}</span>
                <small>{meta}</small>
              </button>
            ))}
          </nav>

          {!selectedAgent && agentMode !== "new" ? <div className="boundary-empty boundary-empty--large">请选择一个 Agent，或新建 Agent 草稿。</div> : null}

          {selectedAgent || agentMode === "new" ? (
            <>
              <section className="boundary-layer-grid boundary-layer-grid--wide">
                <div className="boundary-card boundary-card--summary">
                  <header>
                    <strong>{agentDraft.agent_name || agentDraft.agent_id || "新 Agent 草稿"}</strong>
                    <Badge tone={agentDraft.enabled ? "ok" : "warn"}>{agentDraft.enabled ? "enabled" : "disabled"}</Badge>
                  </header>
                  <div className="boundary-metric-grid">
                    <ReadinessCard label="类别" ready={Boolean(agentDraft.agent_category)} value={displayId(agentDraft.agent_category)} />
                    <ReadinessCard label="职责范围" ready={Boolean(taskScope.length)} value={String(taskScope.length)} />
                    <ReadinessCard label="Runtime" ready={!profileMissing && Boolean(runtimeDraft.agent_profile_id)} value={displayId(runtimeDraft.agent_profile_id)} />
                    <ReadinessCard label="权限冲突" ready={!overlapOps.length} value={overlapOps.length ? String(overlapOps.length) : "0"} />
                  </div>
                </div>
                <aside className="boundary-card">
                  <header><strong>保存</strong></header>
                  <div className="boundary-actions boundary-actions--stack">
                    <ToolbarButton disabled={saving === "agent"} onClick={() => void saveAgent()} variant="primary"><Save size={15} />保存 Agent 名册</ToolbarButton>
                    <ToolbarButton disabled={saving === "runtime" || runtimeSaveBlocked} onClick={() => void saveRuntimeProfile()} variant="primary"><Gauge size={15} />保存 Runtime Profile</ToolbarButton>
                    <ToolbarButton disabled={saving === "delete" || agentDeleteBlocked || agentMode === "new"} onClick={() => void removeAgent()} variant="danger"><Trash2 size={15} />删除 Agent</ToolbarButton>
                  </div>
                </aside>
              </section>

              {activeLayer === "registry" ? (
                <section className="boundary-card">
                  <header><strong>Agent 名册</strong><Badge>{agentMode === "new" ? "draft" : text(selectedAgent?.builtin ? "builtin" : "custom")}</Badge></header>
                  <div className="boundary-form">
                    <Field label="Agent ID"><input value={agentDraft.agent_id} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_id: event.target.value }))} /></Field>
                    <Field label="名称"><input value={agentDraft.agent_name} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_name: event.target.value }))} /></Field>
                    <Field label="类别">
                      <select value={agentDraft.agent_category} onChange={(event) => setAgentDraft((value) => ({ ...value, agent_category: event.target.value as AgentCategory }))}>
                        <option value="main_agent">主 Agent</option>
                        <option value="system_management_agent">系统管理 Agent</option>
                        <option value="worker_sub_agent">子/工作子 Agent</option>
                      </select>
                    </Field>
                    <Field label="接口目标"><input value={agentDraft.interface_target || ""} onChange={(event) => setAgentDraft((value) => ({ ...value, interface_target: event.target.value }))} /></Field>
                    <Field label="默认灵魂"><input value={agentDraft.default_soul_id || ""} onChange={(event) => setAgentDraft((value) => ({ ...value, default_soul_id: event.target.value }))} /></Field>
                    <Field label="默认投影"><input value={agentDraft.default_projection_id || ""} onChange={(event) => setAgentDraft((value) => ({ ...value, default_projection_id: event.target.value }))} /></Field>
                    <Field label="职责说明" wide><textarea value={agentDraft.description || ""} onChange={(event) => setAgentDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                    <label className="boundary-check"><input checked={Boolean(agentDraft.enabled)} onChange={(event) => setAgentDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用 Agent</label>
                    <label className="boundary-check"><input checked={Boolean(agentDraft.editable)} onChange={(event) => setAgentDraft((value) => ({ ...value, editable: event.target.checked }))} type="checkbox" />允许编辑</label>
                  </div>
                  {legacySystemKey ? <div className="boundary-legacy">legacy system_key：{legacySystemKey}</div> : null}
                </section>
              ) : null}

              {activeLayer === "groups" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <aside className="boundary-directory">
                    <div className="boundary-panel-head"><strong>Agent 组</strong><span>{agentGroups.length}</span></div>
                    <div className="boundary-list">
                      {agentGroups.map((group) => (
                        <button
                          className={group.group_id === selectedGroupId ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"}
                          key={group.group_id}
                          onClick={() => setSelectedGroupId(group.group_id)}
                          type="button"
                        >
                          <strong>{group.title}</strong>
                          <span>{displayId(group.group_id)}</span>
                        </button>
                      ))}
                      {!agentGroups.length ? <div className="boundary-empty">暂无 Agent 组。</div> : null}
                    </div>
                  </aside>
                  <div className="boundary-card">
                    <header>
                      <strong>{groupDraft.title || "Agent 组草稿"}</strong>
                      <ToolbarButton disabled={saving === "group"} onClick={() => void saveAgentGroup()} variant="primary"><Save size={15} />保存 Agent 组</ToolbarButton>
                    </header>
                    <div className="boundary-form">
                      <Field label="Group ID"><input value={groupDraft.group_id} onChange={(event) => setGroupDraft((value) => ({ ...value, group_id: event.target.value }))} /></Field>
                      <Field label="标题"><input value={groupDraft.title} onChange={(event) => setGroupDraft((value) => ({ ...value, title: event.target.value }))} /></Field>
                      <Field label="组类型"><input value={groupDraft.group_kind} onChange={(event) => setGroupDraft((value) => ({ ...value, group_kind: event.target.value }))} /></Field>
                      <Field label="协调 Agent"><input value={groupDraft.coordinator_agent_id} onChange={(event) => setGroupDraft((value) => ({ ...value, coordinator_agent_id: event.target.value }))} /></Field>
                      <Field label="生命周期"><input value={groupDraft.lifecycle_state} onChange={(event) => setGroupDraft((value) => ({ ...value, lifecycle_state: event.target.value }))} /></Field>
                      <Field label="成员 Agent" wide><textarea value={groupDraft.member_agent_ids_text} onChange={(event) => setGroupDraft((value) => ({ ...value, member_agent_ids_text: event.target.value }))} /></Field>
                      <Field label="默认拓扑" wide><textarea value={groupDraft.default_topology_template_ids_text} onChange={(event) => setGroupDraft((value) => ({ ...value, default_topology_template_ids_text: event.target.value }))} /></Field>
                      <Field label="默认协议" wide><textarea value={groupDraft.default_communication_protocol_ids_text} onChange={(event) => setGroupDraft((value) => ({ ...value, default_communication_protocol_ids_text: event.target.value }))} /></Field>
                      <Field label="允许协调任务" wide><textarea value={groupDraft.allowed_coordination_task_ids_text} onChange={(event) => setGroupDraft((value) => ({ ...value, allowed_coordination_task_ids_text: event.target.value }))} /></Field>
                      <Field label="说明" wide><textarea value={groupDraft.description} onChange={(event) => setGroupDraft((value) => ({ ...value, description: event.target.value }))} /></Field>
                    </div>
                    <div className="boundary-flowline">
                      <article><span>协调入口</span><strong>{displayId(groupDraft.coordinator_agent_id)}</strong><small>常态协调入口</small></article>
                      <article><span>成员</span><strong>{splitList(groupDraft.member_agent_ids_text).length}</strong><small>固定成员</small></article>
                      <article><span>协调任务</span><strong>{splitList(groupDraft.allowed_coordination_task_ids_text).length}</strong><small>可执行协调任务</small></article>
                      <article><span>拓扑 / 协议</span><strong>{splitList(groupDraft.default_topology_template_ids_text).length} / {splitList(groupDraft.default_communication_protocol_ids_text).length}</strong><small>默认运行结构</small></article>
                    </div>
                  </div>
                </section>
              ) : null}

              {activeLayer === "scope" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>固定职责与任务覆盖范围</strong><Badge>{taskScope.length} scopes</Badge></header>
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
                      <p><span>任务范围</span><strong>{taskScope.map((item) => displayId(item)).join(" / ") || "未配置"}</strong></p>
                      <p><span>对象类型</span><strong>{managedObjects.map((item) => displayId(item)).join(" / ") || "未配置"}</strong></p>
                      <p><span>能力引用</span><strong>{capabilityRefs.map((item) => displayId(item)).join(" / ") || "未配置"}</strong></p>
                    </div>
                  </aside>
                </section>
              ) : null}

              {activeLayer === "runtime" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>Runtime Profile</strong><Badge>{runtimeDraft.agent_profile_id || "draft"}</Badge></header>
                    <div className="boundary-form">
                      <Field label="Profile ID"><input value={runtimeDraft.agent_profile_id} onChange={(event) => setRuntimeDraft((value) => ({ ...value, agent_profile_id: event.target.value }))} /></Field>
                      <Field label="审批策略">
                        <select value={runtimeDraft.approval_policy} onChange={(event) => setRuntimeDraft((value) => ({ ...value, approval_policy: event.target.value }))}>
                          {(catalog?.options.approval_policies ?? ["default"]).map((item) => <option key={item} value={item}>{displayId(item)}</option>)}
                        </select>
                      </Field>
                      <Field label="Trace 策略">
                        <select value={runtimeDraft.trace_policy} onChange={(event) => setRuntimeDraft((value) => ({ ...value, trace_policy: event.target.value }))}>
                          {(catalog?.options.trace_policies ?? ["runtime_event_log"]).map((item) => <option key={item} value={item}>{displayId(item)}</option>)}
                        </select>
                      </Field>
                      <Field label="生命周期"><input value={runtimeDraft.lifecycle_policy} onChange={(event) => setRuntimeDraft((value) => ({ ...value, lifecycle_policy: event.target.value }))} /></Field>
                      <Field label="允许任务模式" wide><textarea value={runtimeDraft.allowed_task_modes_text} onChange={(event) => setRuntimeDraft((value) => ({ ...value, allowed_task_modes_text: event.target.value }))} /></Field>
                      <Field label="允许运行车道" wide><textarea value={runtimeDraft.allowed_runtime_lanes_text} onChange={(event) => setRuntimeDraft((value) => ({ ...value, allowed_runtime_lanes_text: event.target.value }))} /></Field>
                    </div>
                    <SuggestionGrid items={catalog?.options.task_modes ?? []} onAdd={(item) => addRuntimeLine("allowed_task_modes_text", item)} />
                    <SuggestionGrid items={catalog?.options.runtime_lanes ?? []} onAdd={(item) => addRuntimeLine("allowed_runtime_lanes_text", item)} />
                  </div>
                  <aside className="boundary-card">
                    <header><strong>Runtime 摘要</strong></header>
                    <div className="boundary-metric-grid boundary-metric-grid--single">
                      <ReadinessCard label="Task Modes" ready={Boolean(splitList(runtimeDraft.allowed_task_modes_text).length)} value={String(splitList(runtimeDraft.allowed_task_modes_text).length)} />
                      <ReadinessCard label="Runtime Lanes" ready={Boolean(splitList(runtimeDraft.allowed_runtime_lanes_text).length)} value={String(splitList(runtimeDraft.allowed_runtime_lanes_text).length)} />
                    </div>
                  </aside>
                </section>
              ) : null}

              {activeLayer === "permissions" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>权限与能力边界</strong><Badge tone={overlapOps.length ? "danger" : "ok"}>{overlapOps.length ? "conflict" : "clear"}</Badge></header>
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
                      <p><span>冲突</span><strong>{overlapOps.map((item) => displayId(item)).join(" / ") || "无"}</strong></p>
                    </div>
                  </aside>
                </section>
              ) : null}

              {activeLayer === "context" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>记忆、上下文、输出边界</strong><Badge>{splitList(runtimeDraft.output_contracts_text).length} outputs</Badge></header>
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
                      <p><span>Memory</span><strong>{splitList(runtimeDraft.allowed_memory_scopes_text).join(" / ") || "未配置"}</strong></p>
                      <p><span>Context</span><strong>{splitList(runtimeDraft.allowed_context_sections_text).join(" / ") || "未配置"}</strong></p>
                      <p><span>Output</span><strong>{splitList(runtimeDraft.output_contracts_text).join(" / ") || "未配置"}</strong></p>
                    </div>
                  </aside>
                </section>
              ) : null}

              {activeLayer === "eligibility" ? (
                <section className="boundary-layer-grid boundary-layer-grid--wide">
                  <div className="boundary-card">
                    <header><strong>承接资格预览</strong><Badge tone={eligibilityChecks.every((item) => item.ready) ? "ok" : "warn"}>{eligibilityChecks.every((item) => item.ready) ? "ready" : "incomplete"}</Badge></header>
                    <div className="boundary-readiness-list boundary-readiness-list--grid">
                      {eligibilityChecks.map((item) => <ReadinessCard key={item.label} {...item} />)}
                    </div>
                  </div>
                  <aside className="boundary-card">
                    <header><strong>桥接出口</strong></header>
                    <div className="boundary-kv">
                      <p><span>候选依据</span><strong>类别 / task_scope / operations / context / output</strong></p>
                      <p><span>Runtime 证据</span><strong>TaskRun / AgentRun / trace</strong></p>
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
