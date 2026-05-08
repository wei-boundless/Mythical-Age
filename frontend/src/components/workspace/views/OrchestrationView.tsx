"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  KeyRound,
  Layers3,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
  UserCog,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteOrchestrationAgentGroup,
  deleteOrchestrationAgent,
  getSoulSystemCatalog,
  getSoulProjectionCards,
  getOrchestrationAgents,
  getNextOrchestrationWorkerAgentId,
  upsertOrchestrationAgent,
  upsertOrchestrationAgentGroup,
  updateOrchestrationAgentRuntimeProfile,
  type OrchestrationAgentGroup,
  type OrchestrationOption,
  type OrchestrationAgentRuntimeCatalog,
  type OrchestrationAgentRuntimeProfile,
  type OrchestrationAgentUpsertPayload,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type SoulSystemCatalog,
} from "@/lib/api";
import { OrchestrationDirectoryRail } from "@/components/workspace/views/orchestration/OrchestrationDirectoryRail";
import {
  OrchestrationContextWorkbench,
  OrchestrationEligibilityWorkbench,
  OrchestrationPermissionsWorkbench,
  OrchestrationRuntimeWorkbench,
} from "@/components/workspace/views/orchestration/OrchestrationAgentConfigWorkbenches";
import { OrchestrationGroupWorkbench } from "@/components/workspace/views/orchestration/OrchestrationGroupWorkbench";
import { OrchestrationRegistryWorkbench } from "@/components/workspace/views/orchestration/OrchestrationRegistryWorkbench";
import { OrchestrationToolbarButton } from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";

type AgentCategory = "main_agent" | "system_management_agent" | "worker_sub_agent";
type OrchestrationLayer = "registry" | "groups" | "runtime" | "permissions" | "context" | "eligibility";
type WorkerDirectoryMode = "grouped" | "ungrouped";

type AgentDraft = OrchestrationAgentUpsertPayload & {
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
  use_shared_contract: true,
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
  group_id: "group.custom.worker_group_01",
  title: "新子 Agent 组",
  group_kind: "coordination_team",
  coordinator_agent_id: "",
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
  let groupId = `group.custom.worker_group_${String(index).padStart(2, "0")}`;
  const existingIds = new Set(existingGroups.map((group) => group.group_id));
  while (existingIds.has(groupId)) {
    index += 1;
    groupId = `group.custom.worker_group_${String(index).padStart(2, "0")}`;
  }
  return groupId;
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

function compactList(values: string[], limit = 3, fallback = "未配置") {
  if (!values.length) return fallback;
  const head = values.slice(0, limit).map((item) => displayId(item));
  const rest = values.length - head.length;
  return rest > 0 ? `${head.join(" / ")} / +${rest}` : head.join(" / ");
}

function optionLabelMap(options: OrchestrationOption[] = []) {
  return new Map(options.map((item) => [item.value || item.id, item.label || item.value || item.id]));
}

function displayOptionList(values: string[], labels: Map<string, string>, fallback = "未配置") {
  return values.length ? values.map((item) => labels.get(item) || displayId(item)).join(" / ") : fallback;
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
    use_shared_contract: Boolean(merged.use_shared_contract ?? true),
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
    use_shared_contract: Boolean(draft.use_shared_contract),
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
    coordinator_agent_id: draft.coordinator_agent_id || "",
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
    JSON.stringify(agent.metadata ?? {}),
    JSON.stringify(agent.runtime_profile ?? {}),
  ]
    .join(" ")
    .toLowerCase();
}

export function OrchestrationView() {
  const [catalog, setCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [soulCatalog, setSoulCatalog] = useState<SoulSystemCatalog | null>(null);
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
      const [payload, projections, souls] = await Promise.all([getOrchestrationAgents(), getSoulProjectionCards(), getSoulSystemCatalog()]);
      setCatalog(payload);
      setProjectionCatalog(projections);
      setSoulCatalog(souls);
      const firstGroupId = String(payload.agent_groups?.[0]?.group_id || "");
      setSelectedGroupId((current) => current || firstGroupId);
      setSelectedAgentId((current) => {
        if (current) return current;
        if (firstGroupId) return "";
        const preferredWorker = payload.agents.find((agent) => agentCategory(agent) === "worker_sub_agent");
        return String(preferredWorker?.agent_id || payload.agents[0]?.agent_id || "");
      });
      if (!firstGroupId && payload.agents.some((agent) => agentCategory(agent) === "worker_sub_agent")) {
        setWorkerDirectoryMode("ungrouped");
        setActiveLayer("registry");
      }
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
  const soulSeeds = useMemo(() => soulCatalog?.seeds ?? [], [soulCatalog]);
  const selectedAgent = agents.find((agent) => String(agent.agent_id) === selectedAgentId) ?? null;
  const selectedGroup = agentGroups.find((group) => group.group_id === selectedGroupId) ?? null;
  const selectedProfile = (selectedAgent?.runtime_profile ?? {}) as Partial<OrchestrationAgentRuntimeProfile>;
  const operationOptions = useMemo(
    () => (catalog?.options.operations ?? []).map((item) => String(item.operation_id || "")).filter(Boolean),
    [catalog],
  );
  const operationOptionItems = useMemo(() => catalog?.options.operation_options ?? [], [catalog]);
  const taskModeOptionItems = useMemo(() => catalog?.options.task_mode_options ?? [], [catalog]);
  const runtimeLaneOptionItems = useMemo(() => catalog?.options.runtime_lane_options ?? [], [catalog]);
  const memoryScopeOptionItems = useMemo(() => catalog?.options.memory_scope_options ?? [], [catalog]);
  const contextSectionOptionItems = useMemo(() => catalog?.options.context_section_options ?? [], [catalog]);
  const outputContractOptionItems = useMemo(() => catalog?.options.output_contract_options ?? [], [catalog]);
  const approvalPolicyOptions = useMemo(() => catalog?.options.approval_policy_options ?? [], [catalog]);
  const tracePolicyOptions = useMemo(() => catalog?.options.trace_policy_options ?? [], [catalog]);
  const runtimeOptionLabels = useMemo(
    () => new Map([
      ...optionLabelMap(operationOptionItems),
      ...optionLabelMap(taskModeOptionItems),
      ...optionLabelMap(runtimeLaneOptionItems),
      ...optionLabelMap(memoryScopeOptionItems),
      ...optionLabelMap(contextSectionOptionItems),
      ...optionLabelMap(outputContractOptionItems),
      ...optionLabelMap(approvalPolicyOptions),
      ...optionLabelMap(tracePolicyOptions),
    ]),
    [
      approvalPolicyOptions,
      contextSectionOptionItems,
      memoryScopeOptionItems,
      operationOptionItems,
      outputContractOptionItems,
      runtimeLaneOptionItems,
      taskModeOptionItems,
      tracePolicyOptions,
    ],
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
    if (!selectedAgentId && activeLayer !== "groups") {
      setActiveLayer("groups");
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
  const runtimeSaveBlocked = agentMode === "new" || !agentDraft.agent_id.trim();
  const fixedIdentityAgent = agentDraft.agent_category === "main_agent" || agentDraft.agent_category === "system_management_agent";
  const categoryCounts = groupedAgents.reduce<Record<string, number>>((acc, group) => {
    acc[group.category] = group.items.length;
    return acc;
  }, {});
  const legacySystemKey = String(agentDraft.metadata?.system_key || "");
  const readinessRows = [
    { label: "Agent 名册", value: agentDraft.agent_id || "未保存", ready: Boolean(agentDraft.agent_id && agentDraft.agent_name) },
    { label: "运行配置", value: runtimeDraft.agent_profile_id || "未配置", ready: Boolean(runtimeDraft.agent_profile_id) && !runtimeSaveBlocked },
    { label: "权限边界", value: `${allowedOps.length}/${blockedOps.length}`, ready: Boolean(allowedOps.length) && !overlapOps.length },
    { label: "上下文边界", value: `${splitList(runtimeDraft.allowed_context_sections_text).length} / ${runtimeDraft.use_shared_contract ? "含共同契约" : "无共同契约"}`, ready: Boolean(splitList(runtimeDraft.allowed_context_sections_text).length) },
  ];
  const readinessGapCount = readinessRows.filter((item) => !item.ready).length;
  const selectedAgentGroup = selectedAgentId
    ? agentGroups.find((group) => group.member_agent_ids.some((memberId) => String(memberId) === selectedAgentId))
    : null;
  const eligibilityChecks = [
    { label: "类别", value: CATEGORY_LABELS[agentDraft.agent_category as AgentCategory] ?? text(agentDraft.agent_category), ready: Boolean(agentDraft.agent_category) },
    { label: "允许操作", value: displayOptionList(allowedOps.slice(0, 4), runtimeOptionLabels), ready: Boolean(allowedOps.length) },
    { label: "阻断冲突", value: overlapOps.length ? overlapOps.join(" / ") : "无", ready: !overlapOps.length },
    { label: "上下文段", value: `${displayOptionList(splitList(runtimeDraft.allowed_context_sections_text).slice(0, 4), runtimeOptionLabels)} / ${runtimeDraft.use_shared_contract ? "采用共同契约" : "不采用共同契约"}`, ready: Boolean(splitList(runtimeDraft.allowed_context_sections_text).length) },
  ];
  const agentLayerTabs: Array<[OrchestrationLayer, string, string]> = [
    ["registry", "名册", agentMode === "new" ? "草稿" : ""],
    ["runtime", "运行", runtimeDraft.agent_profile_id && !runtimeSaveBlocked ? "已配置" : "待保存"],
    ["permissions", "权限能力", `${allowedOps.length}/${blockedOps.length}`],
    ["context", "上下文", `${splitList(runtimeDraft.allowed_context_sections_text).length}`],
    ["eligibility", "承接资格", overlapOps.length ? "冲突" : ""],
  ];
  const layerTabs: Array<[OrchestrationLayer, string, string]> = activeCategory === "worker_sub_agent"
    ? workerDirectoryMode === "grouped" && !selectedAgent && agentMode !== "new"
      ? [["groups", "组", String(agentGroups.length)]]
      : workerDirectoryMode === "grouped"
        ? [["groups", "组", String(agentGroups.length)], ...agentLayerTabs]
        : agentLayerTabs
    : agentLayerTabs;

  const selectedGroupAgents = useMemo(() => {
    if (!selectedGroup) return [];
    const memberIds = new Set((selectedGroup.member_agent_ids ?? []).map((item) => String(item)));
    return visibleWorkerAgents.filter((agent) => memberIds.has(String(agent.agent_id)));
  }, [selectedGroup, visibleWorkerAgents]);

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

  async function startBlankAgentDraft() {
    setSaving("create");
    setError("");
    let draftAgentId = "";
    try {
      const nextId = await getNextOrchestrationWorkerAgentId();
      draftAgentId = nextId.agent_id;
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "获取新 Agent 标识失败");
      setSaving("");
      return;
    }
    setSaving("");
    setAgentMode("new");
    setGroupMode("existing");
    setSelectedAgentId("");
    setActiveCategory("worker_sub_agent");
    setWorkerDirectoryMode("ungrouped");
    setActiveLayer("registry");
    setAgentDraft({
      ...EMPTY_AGENT_DRAFT,
      agent_id: draftAgentId,
      metadata: { ...EMPTY_AGENT_DRAFT.metadata },
    });
    setRuntimeDraft({
      ...EMPTY_RUNTIME_DRAFT,
      agent_id: draftAgentId,
      agent_profile_id: `${draftAgentId.replace(/[:]/g, "_")}_runtime`,
      metadata: { ...EMPTY_RUNTIME_DRAFT.metadata },
    });
    setNotice("已进入新 Agent 草稿。先保存 Agent 名册，再配置运行档案。");
    setError("");
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
      };
      const payload = await upsertOrchestrationAgent(agentDraft.agent_id, {
        ...agentDraft,
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

  async function removeAgent(agentId?: string) {
    const targetAgent = agentId
      ? agents.find((item) => String(item.agent_id) === agentId) ?? null
      : selectedAgent;
    if (!targetAgent) return;
    setSaving("delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteOrchestrationAgent(String(targetAgent.agent_id));
      const firstWorkerAgent = payload.agents.find((agent) => agentCategory(agent) === "worker_sub_agent");
      setCatalog(payload);
      setSelectedAgentId(String(firstWorkerAgent?.agent_id || payload.agents[0]?.agent_id || ""));
      setGroupMode("existing");
      setNotice(`${displayName(targetAgent)} 已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 Agent 失败");
    } finally {
      setSaving("");
    }
  }

  async function removeAgentGroup() {
    if (!selectedGroupId) return;
    const currentGroup = selectedGroup;
    setSaving("delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteOrchestrationAgentGroup(selectedGroupId);
      const nextGroupId = String(payload.agent_groups?.[0]?.group_id || "");
      setCatalog(payload);
      setSelectedGroupId(nextGroupId);
      setSelectedAgentId("");
      setGroupMode("existing");
      setActiveCategory("worker_sub_agent");
      setWorkerDirectoryMode("grouped");
      setActiveLayer("groups");
      setNotice(`${currentGroup?.title || selectedGroupId} 已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 Agent 组失败");
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
          <p>Agent 名册、运行档案、权限与上下文输出</p>
        </div>
        <div className="boundary-actions">
          <OrchestrationToolbarButton onClick={() => void load()}><RefreshCw size={15} />刷新</OrchestrationToolbarButton>
        </div>
      </header>

      {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}
      {notice ? <div className="boundary-notice"><CheckCircle2 size={16} />{notice}</div> : null}

      <section className="boundary-workbench orchestration-workbench orchestration-definition-center">
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
          selectedGroupAgents={selectedGroupAgents}
          saving={saving}
          startBlankAgentDraft={startBlankAgentDraft}
          startBlankGroupDraft={startBlankGroupDraft}
          ungroupedWorkerAgents={ungroupedWorkerAgents}
          workerDirectoryMode={workerDirectoryMode}
          removeAgentById={(agentId, agentName) => {
            if (window.confirm(`确认删除 ${agentName || agentId} 吗？`)) {
              void removeAgent(agentId);
            }
          }}
          removeSelectedGroup={() => void removeAgentGroup()}
        />

        <main className="boundary-main">
          <section className="orchestration-agent-focus">
            <div>
              <span>{CATEGORY_LABELS[agentDraft.agent_category as AgentCategory] ?? "Agent"}</span>
              <h3>{agentDraft.agent_name || agentDraft.agent_id || "请选择或新建 Agent"}</h3>
              <p>{agentDraft.description || "配置 Agent 的身份、运行权限、记忆与上下文边界。"}</p>
            </div>
            <div className="orchestration-agent-focus__meta">
              <span>{agentDraft.agent_id || "未生成 ID"}</span>
              <b>{fixedIdentityAgent ? "内置锁定" : agentMode === "new" ? "新建草稿" : "可配置"}</b>
            </div>
          </section>
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
              groupDraft={groupDraft}
              groupDraftAvailableAgents={groupDraftAvailableAgents}
              groupDraftMemberAgents={groupDraftMemberAgents}
              groupMembersChanged={groupMembersChanged}
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
                  soulSeeds={soulSeeds}
                  removeAgent={removeAgent}
                  runtimeDraft={runtimeDraft}
                  runtimeSaveBlocked={runtimeSaveBlocked}
                  saveAgent={saveAgent}
                  saveRuntimeProfile={saveRuntimeProfile}
                  saving={saving}
                  selectedAgentBuiltin={Boolean(selectedAgent?.builtin)}
                />
              ) : null}

              {activeLayer === "runtime" ? (
                <OrchestrationRuntimeWorkbench
                  approvalPolicies={catalog?.options.approval_policies ?? ["default"]}
                  approvalPolicyOptions={approvalPolicyOptions}
                  displayId={displayId}
                  outputContractOptionItems={outputContractOptionItems}
                  outputContractOptions={catalog?.options.output_contracts ?? []}
                  outputContractsSummary={displayOptionList(splitList(runtimeDraft.output_contracts_text), runtimeOptionLabels)}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                  runtimeLaneOptionItems={runtimeLaneOptionItems}
                  runtimeLaneOptions={catalog?.options.runtime_lanes ?? []}
                  runtimeLanesSummary={displayOptionList(splitList(runtimeDraft.allowed_runtime_lanes_text), runtimeOptionLabels)}
                  taskModeOptionItems={taskModeOptionItems}
                  taskModeOptions={catalog?.options.task_modes ?? []}
                  taskModesSummary={displayOptionList(splitList(runtimeDraft.allowed_task_modes_text), runtimeOptionLabels)}
                  tracePolicyOptions={tracePolicyOptions}
                  tracePolicies={catalog?.options.trace_policies ?? ["runtime_event_log"]}
                />
              ) : null}

              {activeLayer === "permissions" ? (
                <OrchestrationPermissionsWorkbench
                  allowedOpsCount={allowedOps.length}
                  blockedOpsCount={blockedOps.length}
                  displayId={displayId}
                  operationOptionItems={operationOptionItems}
                  operationOptions={operationOptions}
                  overlapOps={overlapOps}
                  overlapSummary={displayOptionList(overlapOps, runtimeOptionLabels, "无")}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                />
              ) : null}

              {activeLayer === "context" ? (
                <OrchestrationContextWorkbench
                  contextSectionOptionItems={contextSectionOptionItems}
                  contextSectionOptions={catalog?.options.context_sections ?? []}
                  contextSummary={displayOptionList(splitList(runtimeDraft.allowed_context_sections_text), runtimeOptionLabels)}
                  displayId={displayId}
                  memoryScopeOptionItems={memoryScopeOptionItems}
                  memoryScopeOptions={catalog?.options.memory_scopes ?? []}
                  memorySummary={displayOptionList(splitList(runtimeDraft.allowed_memory_scopes_text), runtimeOptionLabels)}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                  sharedContractEnabled={Boolean(runtimeDraft.use_shared_contract)}
                />
              ) : null}

              {activeLayer === "eligibility" ? (
                <OrchestrationEligibilityWorkbench eligibilityChecks={eligibilityChecks} />
              ) : null}
            </>
          ) : null}
        </main>

        <aside className="boundary-card orchestration-assembly-panel">
          <header>
            <strong>装配预览</strong>
            <span className={readinessGapCount ? "boundary-badge boundary-badge--warn" : "boundary-badge boundary-badge--ok"}>
              {readinessGapCount ? `${readinessGapCount} 个缺口` : "完整"}
            </span>
          </header>
          <div className="orchestration-assembly-identity">
            <UserCog size={18} />
            <div>
              <strong>{agentDraft.agent_name || agentDraft.agent_id || "未选择 Agent"}</strong>
              <span>{CATEGORY_LABELS[agentDraft.agent_category as AgentCategory] ?? text(agentDraft.agent_category)}</span>
            </div>
          </div>
          <div className="boundary-readiness-list">
            {readinessRows.map((item) => (
              <article className={item.ready ? "boundary-readiness boundary-readiness--ready" : "boundary-readiness"} key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.ready ? "已配置" : "待配置"}</small>
              </article>
            ))}
          </div>
          <div className="boundary-kv orchestration-assembly-kv">
            <p><span>所在组</span><strong>{selectedAgentGroup?.title || "未进组"}</strong></p>
            <p><span>默认投影</span><strong>{projectionLabel(agentDraft.default_projection_id || "", projectionCards)}</strong></p>
            <p><span>任务模式</span><strong>{compactList(splitList(runtimeDraft.allowed_task_modes_text))}</strong></p>
            <p><span>运行通道</span><strong>{compactList(splitList(runtimeDraft.allowed_runtime_lanes_text))}</strong></p>
            <p><span>允许操作</span><strong>{compactList(allowedOps)}</strong></p>
            <p><span>上下文段</span><strong>{compactList(splitList(runtimeDraft.allowed_context_sections_text))}</strong></p>
            <p><span>共同契约</span><strong>{runtimeDraft.use_shared_contract ? "采用" : "不采用"}</strong></p>
          </div>
          <div className="boundary-actions boundary-actions--stack">
            <OrchestrationToolbarButton disabled={saving === "agent"} onClick={() => void saveAgent()} variant="primary">
              <Save size={15} />
              保存 Agent
            </OrchestrationToolbarButton>
            <OrchestrationToolbarButton disabled={saving === "runtime" || runtimeSaveBlocked} onClick={() => void saveRuntimeProfile()} variant="primary">
              <Gauge size={15} />
              保存运行档案
            </OrchestrationToolbarButton>
            {activeCategory === "worker_sub_agent" ? (
              <OrchestrationToolbarButton disabled={saving === "delete" || agentDeleteBlocked || agentMode === "new" || !selectedAgent} onClick={() => void removeAgent()} variant="danger">
                <Trash2 size={15} />
                删除子 Agent
              </OrchestrationToolbarButton>
            ) : null}
          </div>
          <div className="orchestration-assembly-note">
            <ShieldCheck size={15} />
            <span>任务图只引用 Agent；Agent 的身份、能力、投影和运行边界在这里定义。</span>
          </div>
        </aside>
      </section>
    </div>
  );
}
