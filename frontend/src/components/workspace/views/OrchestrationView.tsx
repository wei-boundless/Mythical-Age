"use client";

import {
  AlertTriangle,
  CheckCircle2,
  CopyPlus,
  Gauge,
  KeyRound,
  Layers3,
  Network,
  Plus,
  RefreshCw,
  Save,
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
import { OrchestrationDirectoryRail } from "@/components/workspace/views/orchestration/OrchestrationDirectoryRail";
import {
  OrchestrationContextWorkbench,
  OrchestrationEligibilityWorkbench,
  OrchestrationPermissionsWorkbench,
  OrchestrationRuntimeWorkbench,
  OrchestrationScopeWorkbench,
} from "@/components/workspace/views/orchestration/OrchestrationAgentConfigWorkbenches";
import { OrchestrationGroupWorkbench } from "@/components/workspace/views/orchestration/OrchestrationGroupWorkbench";
import { OrchestrationRegistryWorkbench } from "@/components/workspace/views/orchestration/OrchestrationRegistryWorkbench";
import { OrchestrationToolbarButton } from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";

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

export function OrchestrationView() {
  const [catalog, setCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [activeCategory, setActiveCategory] = useState<AgentCategory>("worker_sub_agent");
  const [activeLayer, setActiveLayer] = useState<OrchestrationLayer>("groups");
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
      const firstGroupId = String(payload.agent_groups?.[0]?.group_id || "");
      setSelectedGroupId((current) => current || firstGroupId);
      setSelectedAgentId((current) => {
        if (current) return current;
        if (firstGroupId) return "";
        const preferredWorker = payload.agents.find((agent) => agentCategory(agent) === "worker_sub_agent");
        return String(preferredWorker?.agent_id || payload.agents[0]?.agent_id || "");
      });
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

  useEffect(() => {
    if (loading || groupMode === "new") return;
    if (activeCategory !== "worker_sub_agent" || workerDirectoryMode !== "grouped") return;
    if (selectedGroupId && agentGroups.some((group) => group.group_id === selectedGroupId)) return;
    const firstGroupId = agentGroups[0]?.group_id || "";
    if (firstGroupId !== selectedGroupId) {
      setSelectedGroupId(firstGroupId);
    }
    if (activeLayer !== "groups") {
      setActiveLayer("groups");
    }
    if (selectedAgentId) {
      setSelectedAgentId("");
    }
  }, [
    activeCategory,
    activeLayer,
    agentGroups,
    groupMode,
    loading,
    selectedAgentId,
    selectedGroupId,
    workerDirectoryMode,
  ]);

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
          <OrchestrationToolbarButton onClick={() => void load()}><RefreshCw size={15} />刷新</OrchestrationToolbarButton>
          <OrchestrationToolbarButton onClick={startBlankAgentDraft}><Plus size={15} />新建 Agent</OrchestrationToolbarButton>
          <OrchestrationToolbarButton onClick={startBlankGroupDraft}><Network size={15} />新建 Agent 组</OrchestrationToolbarButton>
          <OrchestrationToolbarButton disabled={saving === "create"} onClick={() => void createWorkerDraft()}><CopyPlus size={15} />生成工作子 Agent</OrchestrationToolbarButton>
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}
      {notice ? <div className="boundary-notice"><CheckCircle2 size={16} />{notice}</div> : null}

      <section className="boundary-workbench orchestration-workbench">
        <OrchestrationDirectoryRail
          activeCategory={activeCategory}
          activeGroupItems={activeGroup?.items ?? []}
          agentGroups={agentGroups}
          agents={agents}
          categoryCounts={categoryCounts}
          loading={loading}
          query={query}
          selectAgent={selectAgent}
          selectCategory={selectCategory}
          selectedAgentId={selectedAgentId}
          selectedGroupId={selectedGroupId}
          selectSubAgentGroup={selectSubAgentGroup}
          selectWorkerDirectoryMode={selectWorkerDirectoryMode}
          setQuery={setQuery}
          ungroupedWorkerAgents={ungroupedWorkerAgents}
          workerDirectoryMode={workerDirectoryMode}
        />

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
            <OrchestrationGroupWorkbench
              clearGroupMembers={clearGroupMembers}
              groupDraft={groupDraft}
              groupDraftAvailableAgents={groupDraftAvailableAgents}
              groupDraftMemberAgents={groupDraftMemberAgents}
              groupMembersChanged={groupMembersChanged}
              includeAllVisibleWorkers={includeAllVisibleWorkers}
              saveAgentGroup={saveAgentGroup}
              saving={saving}
              setGroupDraft={setGroupDraft}
              toggleGroupMember={toggleGroupMember}
            />
          ) : null}

          {activeLayer !== "groups" && (selectedAgent || agentMode === "new") ? (
            <>
              {activeLayer === "registry" ? (
                <OrchestrationRegistryWorkbench
                  agentDeleteBlocked={agentDeleteBlocked}
                  agentDraft={agentDraft}
                  agentMode={agentMode}
                  categoryLabels={CATEGORY_LABELS}
                  legacySystemKey={legacySystemKey}
                  overlapOps={overlapOps}
                  patchAgentDraft={(patch) => setAgentDraft((current) => ({ ...current, ...patch }))}
                  profileMissing={profileMissing}
                  projectionCards={projectionCards}
                  removeAgent={removeAgent}
                  runtimeDraft={runtimeDraft}
                  runtimeSaveBlocked={runtimeSaveBlocked}
                  saveAgent={saveAgent}
                  saveRuntimeProfile={saveRuntimeProfile}
                  saving={saving}
                  selectedAgentBuiltin={Boolean(selectedAgent?.builtin)}
                  taskScopeCount={taskScope.length}
                />
              ) : null}

              {activeLayer === "scope" ? (
                <OrchestrationScopeWorkbench
                  addAgentLine={addAgentLine}
                  agentDraft={agentDraft}
                  capabilityRefsSummary={displayList(capabilityRefs)}
                  managedObjectsSummary={displayList(managedObjects)}
                  patchAgentDraft={(patch) => setAgentDraft((current) => ({ ...current, ...patch }))}
                  scopeSuggestions={scopeSuggestions}
                  taskScopeCount={taskScope.length}
                  taskScopeSummary={displayList(taskScope)}
                />
              ) : null}

              {activeLayer === "runtime" ? (
                <OrchestrationRuntimeWorkbench
                  addRuntimeLine={addRuntimeLine}
                  approvalPolicies={catalog?.options.approval_policies ?? ["default"]}
                  displayId={displayId}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                  runtimeLaneOptions={catalog?.options.runtime_lanes ?? []}
                  runtimeLanesSummary={displayList(splitList(runtimeDraft.allowed_runtime_lanes_text))}
                  taskModeOptions={catalog?.options.task_modes ?? []}
                  taskModesSummary={displayList(splitList(runtimeDraft.allowed_task_modes_text))}
                  tracePolicies={catalog?.options.trace_policies ?? ["runtime_event_log"]}
                />
              ) : null}

              {activeLayer === "permissions" ? (
                <OrchestrationPermissionsWorkbench
                  addRuntimeLine={addRuntimeLine}
                  allowedOpsCount={allowedOps.length}
                  blockedOpsCount={blockedOps.length}
                  operationOptions={operationOptions}
                  overlapOps={overlapOps}
                  overlapSummary={displayList(overlapOps, "无")}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                />
              ) : null}

              {activeLayer === "context" ? (
                <OrchestrationContextWorkbench
                  addRuntimeLine={addRuntimeLine}
                  contextSectionOptions={catalog?.options.context_sections ?? []}
                  contextSummary={displayList(splitList(runtimeDraft.allowed_context_sections_text))}
                  memoryScopeOptions={catalog?.options.memory_scopes ?? []}
                  memorySummary={displayList(splitList(runtimeDraft.allowed_memory_scopes_text))}
                  outputContractOptions={catalog?.options.output_contracts ?? []}
                  outputCount={splitList(runtimeDraft.output_contracts_text).length}
                  outputSummary={displayList(splitList(runtimeDraft.output_contracts_text))}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                />
              ) : null}

              {activeLayer === "eligibility" ? (
                <OrchestrationEligibilityWorkbench eligibilityChecks={eligibilityChecks} />
              ) : null}
            </>
          ) : null}
        </main>
      </section>
    </div>
  );
}
