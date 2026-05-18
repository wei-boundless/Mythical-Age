"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  RefreshCw,
  Save,
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
  getOrchestrationCapabilityItems,
  getOrchestrationRuntimeOptions,
  getNextOrchestrationWorkerAgentId,
  upsertOrchestrationAgent,
  upsertOrchestrationAgentGroup,
  updateOrchestrationAgentRuntimeProfile,
  type OrchestrationAgentGroup,
  type OrchestrationOption,
  type OrchestrationAgentRuntimeCatalog,
  type OrchestrationAgentRuntimeProfile,
  type OrchestrationAgentUpsertPayload,
  type OrchestrationCapabilityItem,
  type SoulProjectionCard,
  type SoulProjectionCatalog,
  type SoulSystemCatalog,
} from "@/lib/api";
import { OrchestrationDirectoryRail } from "@/components/workspace/views/orchestration/OrchestrationDirectoryRail";
import {
  OrchestrationAssemblyOverviewWorkbench,
  OrchestrationCollaborationWorkbench,
  OrchestrationContextMemoryWorkbench,
  OrchestrationDiagnosticsWorkbench,
  OrchestrationRuntimePermissionWorkbench,
} from "@/components/workspace/views/orchestration/OrchestrationAgentConfigWorkbenches";
import { OrchestrationGroupWorkbench } from "@/components/workspace/views/orchestration/OrchestrationGroupWorkbench";
import { OrchestrationRegistryWorkbench } from "@/components/workspace/views/orchestration/OrchestrationRegistryWorkbench";
import { OrchestrationToolbarButton } from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";
import { taskSystemDisplayLabel } from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { useAppStore } from "@/lib/store";

type AgentCategory = "main_agent" | "builtin_agent" | "custom_agent";
type OrchestrationLayer = "identity" | "groups" | "runtime_permissions" | "context_memory" | "collaboration" | "overview" | "diagnostics";
type CustomDirectoryMode = "grouped" | "ungrouped";

type AgentDraft = OrchestrationAgentUpsertPayload & {
};

type RuntimeDraft = OrchestrationAgentRuntimeProfile;

type AgentGroupDraft = OrchestrationAgentGroup & {
  member_agent_ids_text: string;
};

const CATEGORY_ORDER: AgentCategory[] = ["main_agent", "builtin_agent", "custom_agent"];

const CATEGORY_LABELS: Record<AgentCategory, string> = {
  main_agent: "主 Agent",
  builtin_agent: "内置 Agent",
  custom_agent: "自定义 Agent",
};

const EMPTY_AGENT_DRAFT: AgentDraft = {
  agent_id: "",
  agent_name: "",
  agent_category: "custom_agent",
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
  allowed_runtime_lanes: [],
  allowed_operations: ["op.model_response"],
  blocked_operations: [],
  allowed_memory_scopes: [],
  allowed_context_sections: [],
  use_shared_contract: true,
  can_delegate_to_agents: false,
  allowed_delegate_agent_ids: [],
  max_delegate_calls_per_turn: 1,
  delegate_context_policy: "summary_and_refs_only",
  approval_policy: "default",
  trace_policy: "runtime_event_log",
  lifecycle_policy: "orchestration_managed",
  metadata: { managed_by: "orchestration_console" },
};

const EMPTY_GROUP_DRAFT: AgentGroupDraft = {
  group_id: "group.custom.worker_group_01",
  title: "新自定义 Agent 组",
  group_kind: "coordination_team",
  coordinator_agent_id: "",
  member_agent_ids: [],
  description: "",
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
  const registeredLabel = taskSystemDisplayLabel(raw, fallback);
  if (registeredLabel !== raw) return registeredLabel;
  const labels: Record<string, string> = {
    main_agent: "主 Agent",
    builtin_agent: "内置 Agent",
    custom_agent: "自定义 Agent",
    coordination_team: "协调任务组",
    enabled: "启用",
    disabled: "停用",
    default: "默认审批",
    runtime_event_log: "运行事件追踪",
    orchestration_managed: "编排系统管理",
    health_management: "健康管理",
    trace_analysis: "Trace 分析",
    memory_management: "记忆管理",
    permission_management: "能力准入管理",
    memory_system_agent: "记忆管理 Agent",
    development: "开发任务",
    full_interactive: "完整交互运行",
    memory_trace_read: "记忆追踪读取",
    session_memory_maintenance: "会话记忆维护",
    durable_memory_extraction: "长期记忆提取",
    memory_candidate_review: "记忆候选审核",
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
    conversation_readonly: "会话记忆只读",
    state_readonly: "状态记忆只读",
    long_term_candidate: "长期记忆候选",
    session_memory_write_candidate: "会话记忆写入候选",
    durable_memory_write_candidate: "长期记忆写入候选",
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
    ["op.", "操作准入"],
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

function uniqueList(value: unknown) {
  return Array.isArray(value)
    ? Array.from(new Set(value.map((item) => String(item || "").trim()).filter(Boolean)))
    : [];
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
  const value = String(agent?.agent_category || agent?.profile_type || "custom_agent");
  return CATEGORY_ORDER.includes(value as AgentCategory) ? (value as AgentCategory) : "custom_agent";
}

function isGroupEligibleAgent(agent: Record<string, unknown> | null | undefined) {
  return Boolean(agent?.group_eligible) || agentCategory(agent) === "custom_agent";
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

function mergeOrchestrationOptions(
  payload: OrchestrationAgentRuntimeCatalog,
  options: OrchestrationAgentRuntimeCatalog["options"],
): OrchestrationAgentRuntimeCatalog {
  return {
    ...payload,
    options: {
      ...payload.options,
      ...options,
    },
  };
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
  const allowedOps = uniqueList(merged.allowed_operations).length ? uniqueList(merged.allowed_operations) : ["op.model_response"];
  return {
    ...merged,
    agent_profile_id: profileId,
    allowed_runtime_lanes: uniqueList(merged.allowed_runtime_lanes),
    allowed_operations: allowedOps,
    blocked_operations: uniqueList(merged.blocked_operations),
    allowed_memory_scopes: uniqueList(merged.allowed_memory_scopes),
    allowed_context_sections: uniqueList(merged.allowed_context_sections),
    use_shared_contract: Boolean(merged.use_shared_contract ?? true),
    can_delegate_to_agents: Boolean(merged.can_delegate_to_agents ?? false),
    allowed_delegate_agent_ids: uniqueList(merged.allowed_delegate_agent_ids),
    max_delegate_calls_per_turn: Number(merged.max_delegate_calls_per_turn ?? 1),
    delegate_context_policy: String(merged.delegate_context_policy || "summary_and_refs_only"),
    approval_policy: String(merged.approval_policy || "default"),
    trace_policy: String(merged.trace_policy || "runtime_event_log"),
    lifecycle_policy: String(merged.lifecycle_policy || "orchestration_managed"),
    metadata: merged.metadata ?? { managed_by: "orchestration_console" },
  };
}

function runtimePayloadFromDraft(draft: RuntimeDraft) {
  return {
    agent_profile_id: draft.agent_profile_id,
    allowed_runtime_lanes: uniqueList(draft.allowed_runtime_lanes),
    allowed_operations: Array.from(new Set(["op.model_response", ...uniqueList(draft.allowed_operations)])),
    blocked_operations: uniqueList(draft.blocked_operations),
    allowed_memory_scopes: uniqueList(draft.allowed_memory_scopes),
    allowed_context_sections: uniqueList(draft.allowed_context_sections),
    use_shared_contract: Boolean(draft.use_shared_contract),
    can_delegate_to_agents: Boolean(draft.can_delegate_to_agents),
    allowed_delegate_agent_ids: uniqueList(draft.allowed_delegate_agent_ids),
    max_delegate_calls_per_turn: Math.max(0, Number(draft.max_delegate_calls_per_turn ?? 1)),
    delegate_context_policy: draft.delegate_context_policy || "summary_and_refs_only",
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
    metadata: base.metadata ?? { managed_by: "orchestration_console" },
    member_agent_ids_text: uniqueList(base.member_agent_ids ?? []).join("\n"),
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
  const { activeWorkspaceView, orchestrationInspectorTarget } = useAppStore();
  const [catalog, setCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [capabilityItems, setCapabilityItems] = useState<OrchestrationCapabilityItem[]>([]);
  const [capabilityItemsLoading, setCapabilityItemsLoading] = useState(false);
  const [capabilityItemsError, setCapabilityItemsError] = useState("");
  const [projectionCatalog, setProjectionCatalog] = useState<SoulProjectionCatalog | null>(null);
  const [soulCatalog, setSoulCatalog] = useState<SoulSystemCatalog | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [activeCategory, setActiveCategory] = useState<AgentCategory>("custom_agent");
  const [activeLayer, setActiveLayer] = useState<OrchestrationLayer>("groups");
  const [customDirectoryMode, setCustomDirectoryMode] = useState<CustomDirectoryMode>("grouped");
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
      const [payload, runtimeOptions, projections, souls] = await Promise.all([
        getOrchestrationAgents(),
        getOrchestrationRuntimeOptions(),
        getSoulProjectionCards(),
        getSoulSystemCatalog(),
      ]);
      const mergedPayload = mergeOrchestrationOptions(payload, runtimeOptions.options);
      setCatalog(mergedPayload);
      setProjectionCatalog(projections);
      setSoulCatalog(souls);
      const firstGroupId = String(mergedPayload.agent_groups?.[0]?.group_id || "");
      setSelectedGroupId((current) => current || firstGroupId);
      setSelectedAgentId((current) => {
        if (current) return current;
        if (firstGroupId) return "";
        const preferredCustom = mergedPayload.agents.find((agent) => agentCategory(agent) === "custom_agent");
        return String(preferredCustom?.agent_id || mergedPayload.agents[0]?.agent_id || "");
      });
      if (!firstGroupId && mergedPayload.agents.some((agent) => agentCategory(agent) === "custom_agent")) {
        setCustomDirectoryMode("ungrouped");
        setActiveLayer("identity");
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "编排系统加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeWorkspaceView !== "orchestration") return;
    void load();
  }, [activeWorkspaceView, load]);

  useEffect(() => {
    if (activeWorkspaceView !== "orchestration" || activeLayer !== "runtime_permissions") return;
    let cancelled = false;
    setCapabilityItemsLoading(true);
    setCapabilityItemsError("");
    void getOrchestrationCapabilityItems()
      .then((payload) => {
        if (!cancelled) setCapabilityItems(payload.capability_items ?? []);
      })
      .catch((exc) => {
        if (!cancelled) {
          setCapabilityItems([]);
          setCapabilityItemsError(exc instanceof Error ? exc.message : "能力准入项加载失败");
        }
      })
      .finally(() => {
        if (!cancelled) setCapabilityItemsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeLayer, activeWorkspaceView]);

  const agents = useMemo(() => catalog?.agents ?? [], [catalog]);
  const agentGroups = useMemo(() => catalog?.agent_groups ?? [], [catalog]);
  const projectionCards = useMemo(() => projectionCatalog?.cards ?? [], [projectionCatalog]);
  const soulSeeds = useMemo(() => soulCatalog?.seeds ?? [], [soulCatalog]);

  useEffect(() => {
    if (activeWorkspaceView !== "orchestration") return;
    if (!orchestrationInspectorTarget) return;
    const requestedLayer = orchestrationInspectorTarget.orchestrationLayer;
      const focusLayer =
      requestedLayer === "permissions"
        ? "runtime_permissions"
        : requestedLayer === "context"
          ? "context_memory"
          : requestedLayer === "registry"
            ? "identity"
            : requestedLayer === "runtime"
              ? "runtime_permissions"
              : requestedLayer === "eligibility"
                ? "diagnostics"
                : requestedLayer;
    const validLayers: OrchestrationLayer[] = ["identity", "groups", "runtime_permissions", "context_memory", "collaboration", "overview", "diagnostics"];
    if (focusLayer && validLayers.includes(focusLayer)) {
      setActiveLayer(focusLayer);
    }
    const focusAgentId = String(orchestrationInspectorTarget.agentId ?? "").trim();
    if (focusAgentId && agents.length) {
      const focusedAgent = agents.find((agent) => String(agent.agent_id ?? "") === focusAgentId);
      if (focusedAgent) {
        const category = agentCategory(focusedAgent);
        setSelectedAgentId(focusAgentId);
        setSelectedGroupId("");
        setAgentMode("existing");
        setGroupMode("existing");
        setActiveCategory(category);
        if (category === "custom_agent") {
          const group = agentGroups.find((item) => item.member_agent_ids.some((memberId) => String(memberId) === focusAgentId));
          setCustomDirectoryMode(group ? "grouped" : "ungrouped");
          setSelectedGroupId(group?.group_id || "");
        }
      }
    }
    if (orchestrationInspectorTarget.reason) {
      setNotice(orchestrationInspectorTarget.reason);
    }
  }, [activeWorkspaceView, agentGroups, agents, orchestrationInspectorTarget]);

  const selectedAgent = agents.find((agent) => String(agent.agent_id) === selectedAgentId) ?? null;
  const selectedGroup = agentGroups.find((group) => group.group_id === selectedGroupId) ?? null;
  const selectedProfile = (selectedAgent?.runtime_profile ?? {}) as Partial<OrchestrationAgentRuntimeProfile>;
  const operationOptions = useMemo(
    () => (catalog?.options.operations ?? []).map((item) => String(item.operation_id || "")).filter(Boolean),
    [catalog],
  );
  const operationOptionItems = useMemo(() => catalog?.options.operation_options ?? [], [catalog]);
  const runtimeLaneOptionItems = useMemo(() => catalog?.options.runtime_lane_options ?? [], [catalog]);
  const memoryScopeOptionItems = useMemo(() => catalog?.options.memory_scope_options ?? [], [catalog]);
  const contextSectionOptionItems = useMemo(() => catalog?.options.context_section_options ?? [], [catalog]);
  const approvalPolicyOptions = useMemo(() => catalog?.options.approval_policy_options ?? [], [catalog]);
  const tracePolicyOptions = useMemo(() => catalog?.options.trace_policy_options ?? [], [catalog]);
  const runtimeOptionLabels = useMemo(
    () => new Map([
      ...optionLabelMap(operationOptionItems),
      ...optionLabelMap(runtimeLaneOptionItems),
      ...optionLabelMap(memoryScopeOptionItems),
      ...optionLabelMap(contextSectionOptionItems),
      ...optionLabelMap(approvalPolicyOptions),
      ...optionLabelMap(tracePolicyOptions),
    ]),
    [
      approvalPolicyOptions,
      contextSectionOptionItems,
      memoryScopeOptionItems,
      operationOptionItems,
      runtimeLaneOptionItems,
      tracePolicyOptions,
    ],
  );
  const normalizedQuery = query.trim().toLowerCase();
  const visibleAgents = useMemo(
    () => agents.filter((agent) => !normalizedQuery || searchText(agent).includes(normalizedQuery)),
    [agents, normalizedQuery],
  );
  const visibleCustomAgents = useMemo(
    () => visibleAgents.filter((agent) => agentCategory(agent) === "custom_agent" && isGroupEligibleAgent(agent)),
    [visibleAgents],
  );
  const ungroupedCustomAgents = useMemo(() => {
    const groupedIds = new Set(agentGroups.flatMap((group) => group.member_agent_ids.map((item) => String(item))));
    return visibleCustomAgents.filter((agent) => !groupedIds.has(String(agent.agent_id)));
  }, [agentGroups, visibleCustomAgents]);
  const groupDraftMemberIds = useMemo(() => new Set(splitList(groupDraft.member_agent_ids_text)), [groupDraft.member_agent_ids_text]);
  const groupDraftMemberAgents = useMemo(
    () => visibleCustomAgents.filter((agent) => groupDraftMemberIds.has(String(agent.agent_id))),
    [groupDraftMemberIds, visibleCustomAgents],
  );
  const groupDraftAvailableAgents = useMemo(
    () => visibleCustomAgents.filter((agent) => !groupDraftMemberIds.has(String(agent.agent_id))),
    [groupDraftMemberIds, visibleCustomAgents],
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
    if (activeCategory !== "custom_agent" || customDirectoryMode !== "grouped") return;
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
    customDirectoryMode,
  ]);

  const activeGroup = groupedAgents.find((group) => group.category === activeCategory);
  const agentDeleteBlocked = false;
  const profileMissing = Boolean(selectedAgent && !selectedProfile.agent_profile_id);
  const allowedOps = uniqueList(runtimeDraft.allowed_operations);
  const blockedOps = uniqueList(runtimeDraft.blocked_operations);
  const overlapOps = allowedOps.filter((item) => blockedOps.includes(item));
  const runtimeSaveBlocked = agentMode === "new" || !agentDraft.agent_id.trim();
  const builtinManagedAgent = Boolean(selectedAgent?.builtin);
  const categoryCounts = groupedAgents.reduce<Record<string, number>>((acc, group) => {
    acc[group.category] = group.items.length;
    return acc;
  }, {});
  const eligibilityChecks = [
    { label: "类别", value: CATEGORY_LABELS[agentDraft.agent_category as AgentCategory] ?? text(agentDraft.agent_category), ready: Boolean(agentDraft.agent_category) },
    { label: "允许操作", value: displayOptionList(allowedOps.slice(0, 4), runtimeOptionLabels), ready: Boolean(allowedOps.length) },
    { label: "阻断冲突", value: overlapOps.length ? overlapOps.join(" / ") : "无", ready: !overlapOps.length },
    { label: "上下文段", value: `${displayOptionList(uniqueList(runtimeDraft.allowed_context_sections).slice(0, 4), runtimeOptionLabels)} / ${runtimeDraft.use_shared_contract ? "采用共同契约" : "不采用共同契约"}`, ready: Boolean(uniqueList(runtimeDraft.allowed_context_sections).length) },
  ];
  const agentLayerTabs: Array<[OrchestrationLayer, string, string]> = [
    ["identity", "身份", agentMode === "new" ? "草稿" : ""],
    ["runtime_permissions", "运行权限", runtimeDraft.agent_profile_id && !runtimeSaveBlocked ? "已配置" : "待保存"],
    ["context_memory", "上下文记忆", `${uniqueList(runtimeDraft.allowed_context_sections).length + uniqueList(runtimeDraft.allowed_memory_scopes).length}`],
    ["collaboration", "协作", runtimeDraft.can_delegate_to_agents ? "可委派" : ""],
    ["overview", "总览", ""],
    ["diagnostics", "诊断", overlapOps.length ? "冲突" : ""],
  ];
  const layerTabs: Array<[OrchestrationLayer, string, string]> = activeCategory === "custom_agent"
    ? customDirectoryMode === "grouped" && !selectedAgent && agentMode !== "new"
      ? [["groups", "组", String(agentGroups.length)]]
      : customDirectoryMode === "grouped"
        ? [["groups", "组", String(agentGroups.length)], ...agentLayerTabs]
        : agentLayerTabs
    : agentLayerTabs;

  const selectedGroupAgents = useMemo(() => {
    if (!selectedGroup) return [];
    const memberIds = new Set((selectedGroup.member_agent_ids ?? []).map((item) => String(item)));
    return visibleCustomAgents.filter((agent) => memberIds.has(String(agent.agent_id)));
  }, [selectedGroup, visibleCustomAgents]);
  const delegateAgentOptions = useMemo(
    () =>
      agents
        .filter((agent) => String(agent.agent_id || "") !== String(agentDraft.agent_id || ""))
        .map((agent) => ({
          id: String(agent.agent_id || ""),
          value: String(agent.agent_id || ""),
          label: displayName(agent),
          description: String(agent.description || ""),
          category: CATEGORY_LABELS[agentCategory(agent)],
        })),
    [agentDraft.agent_id, agents],
  );
  const runtimeLanesSummary = displayOptionList(uniqueList(runtimeDraft.allowed_runtime_lanes), runtimeOptionLabels);
  const memorySummary = displayOptionList(uniqueList(runtimeDraft.allowed_memory_scopes), runtimeOptionLabels);
  const contextSummary = displayOptionList(uniqueList(runtimeDraft.allowed_context_sections), runtimeOptionLabels);
  const operationSummary = `${allowedOps.length} 允许 / ${blockedOps.length} 阻断`;
  const collaborationSummary = runtimeDraft.can_delegate_to_agents
    ? `${uniqueList(runtimeDraft.allowed_delegate_agent_ids).length || "不限"} 个目标`
    : "未开放委派";
  const runtimeLaneDiagnostics = (catalog?.options as { runtime_lane_diagnostics?: Record<string, unknown> } | undefined)?.runtime_lane_diagnostics;

  function selectCategory(category: AgentCategory) {
    setActiveCategory(category);
    const first = visibleAgents.find((agent) => agentCategory(agent) === category);
    setAgentMode("existing");
    if (category === "custom_agent") {
      setCustomDirectoryMode("grouped");
      setActiveLayer("groups");
      setGroupMode("existing");
      const firstGroup = agentGroups[0];
      setSelectedGroupId(firstGroup?.group_id || "");
      setSelectedAgentId("");
    } else {
        setActiveLayer("identity");
      setSelectedAgentId(String(first?.agent_id || ""));
    }
  }

  function selectAgent(agentId: string) {
    const agent = agents.find((item) => String(item.agent_id) === agentId);
    setSelectedAgentId(agentId);
    setAgentMode("existing");
    setGroupMode("existing");
    if (agentCategory(agent) === "custom_agent") {
      const group = agentGroups.find((item) => item.member_agent_ids.some((memberId) => String(memberId) === agentId));
      setActiveCategory("custom_agent");
      if (group) {
        setCustomDirectoryMode("grouped");
        setSelectedGroupId(group.group_id);
      } else {
        setCustomDirectoryMode("ungrouped");
      }
    }
      setActiveLayer("identity");
  }

  function selectSubAgentGroup(groupId: string) {
    setSelectedGroupId(groupId);
    setGroupMode("existing");
    setCustomDirectoryMode("grouped");
    setSelectedAgentId("");
    setActiveLayer("groups");
  }

  function selectCustomDirectoryMode(mode: CustomDirectoryMode) {
    setCustomDirectoryMode(mode);
    setAgentMode("existing");
    setGroupMode("existing");
    if (mode === "grouped") {
      setSelectedAgentId("");
      setSelectedGroupId((current) => current || agentGroups[0]?.group_id || "");
      setActiveLayer("groups");
      return;
    }
    setSelectedGroupId("");
    setSelectedAgentId(String(ungroupedCustomAgents[0]?.agent_id || ""));
    setActiveLayer(ungroupedCustomAgents[0] ? "identity" : "groups");
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
    setActiveCategory("custom_agent");
    setCustomDirectoryMode("ungrouped");
    setActiveLayer("identity");
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
      setError("自定义 Agent 组标识不能为空。");
      return;
    }
    if (!groupDraft.title.trim()) {
      setError("自定义 Agent 组名称不能为空。");
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
    setActiveCategory("custom_agent");
    setCustomDirectoryMode("grouped");
    setActiveLayer("groups");
    setGroupMode("new");
    setSelectedGroupId("");
    setGroupDraft({
      ...EMPTY_GROUP_DRAFT,
      group_id: makeCustomGroupId(agentGroups),
      title: "新自定义 Agent 组",
      metadata: { managed_by: "orchestration_console" },
    });
    setNotice("已进入自定义 Agent 组草稿。");
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
      member_agent_ids_text: visibleCustomAgents.map((agent) => String(agent.agent_id)).join("\n"),
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
      const firstCustomAgent = payload.agents.find((agent) => agentCategory(agent) === "custom_agent");
      setCatalog(payload);
      setSelectedAgentId(String(firstCustomAgent?.agent_id || payload.agents[0]?.agent_id || ""));
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
      setActiveCategory("custom_agent");
      setCustomDirectoryMode("grouped");
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
          <p>Agent 名册与运行档案</p>
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
          selectCustomDirectoryMode={selectCustomDirectoryMode}
          setQuery={setQuery}
          selectedGroupAgents={selectedGroupAgents}
          saving={saving}
          startBlankAgentDraft={startBlankAgentDraft}
          startBlankGroupDraft={startBlankGroupDraft}
          ungroupedCustomAgents={ungroupedCustomAgents}
          customDirectoryMode={customDirectoryMode}
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
              <p>{agentDraft.description || "配置 Agent 身份与运行边界。"}</p>
            </div>
            <div className="orchestration-agent-focus__meta">
              <span>{agentDraft.agent_id || "未生成 ID"}</span>
              <b>{agentMode === "new" ? "新建草稿" : builtinManagedAgent ? "内置来源" : "可配置"}</b>
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

          {!selectedAgent && agentMode !== "new" && !(activeCategory === "custom_agent" && activeLayer === "groups") ? <div className="boundary-empty boundary-empty--large">请选择一个 Agent，或新建 Agent 草稿。</div> : null}

          {activeCategory === "custom_agent" && activeLayer === "groups" ? (
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
              {activeLayer === "identity" ? (
                <OrchestrationRegistryWorkbench
                  agentDeleteBlocked={agentDeleteBlocked}
                  agentDraft={agentDraft}
                  agentMode={agentMode}
                  categoryLabels={CATEGORY_LABELS}
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

              {activeLayer === "runtime_permissions" ? (
                <>
                {capabilityItemsError ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{capabilityItemsError}</div> : null}
                {capabilityItemsLoading ? <div className="boundary-notice"><RefreshCw size={16} />正在加载能力准入项...</div> : null}
                <OrchestrationRuntimePermissionWorkbench
                  allowedOpsCount={allowedOps.length}
                  blockedOpsCount={blockedOps.length}
                  capabilityItems={capabilityItems}
                  approvalPolicies={catalog?.options.approval_policies ?? ["default"]}
                  approvalPolicyOptions={approvalPolicyOptions}
                  displayId={displayId}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                  runtimeLaneOptionItems={runtimeLaneOptionItems}
                  runtimeLaneOptions={catalog?.options.runtime_lanes ?? []}
                  runtimeLanesSummary={runtimeLanesSummary}
                  tracePolicyOptions={tracePolicyOptions}
                  tracePolicies={catalog?.options.trace_policies ?? ["runtime_event_log"]}
                  operationOptionItems={operationOptionItems}
                  operationOptions={operationOptions}
                  overlapOps={overlapOps}
                  overlapSummary={displayOptionList(overlapOps, runtimeOptionLabels, "无")}
                />
                </>
              ) : null}

              {activeLayer === "context_memory" ? (
                <OrchestrationContextMemoryWorkbench
                  contextSectionOptionItems={contextSectionOptionItems}
                  contextSectionOptions={catalog?.options.context_sections ?? []}
                  contextSummary={contextSummary}
                  displayId={displayId}
                  memoryScopeOptionItems={memoryScopeOptionItems}
                  memoryScopeOptions={catalog?.options.memory_scopes ?? []}
                  memorySummary={memorySummary}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                  sharedContractEnabled={Boolean(runtimeDraft.use_shared_contract)}
                />
              ) : null}

              {activeLayer === "collaboration" ? (
                <OrchestrationCollaborationWorkbench
                  agentDraft={agentDraft}
                  delegateAgentOptions={delegateAgentOptions}
                  displayId={displayId}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                />
              ) : null}

              {activeLayer === "overview" ? (
                <OrchestrationAssemblyOverviewWorkbench
                  agentDraft={agentDraft}
                  collaborationSummary={collaborationSummary}
                  contextSummary={contextSummary}
                  memorySummary={memorySummary}
                  openLayer={setActiveLayer}
                  operationSummary={operationSummary}
                  runtimeDraft={runtimeDraft}
                  runtimeSummary={runtimeLanesSummary}
                />
              ) : null}

              {activeLayer === "diagnostics" ? (
                <OrchestrationDiagnosticsWorkbench
                  capabilityItemsCount={capabilityItems.length}
                  eligibilityChecks={eligibilityChecks}
                  overlapOps={overlapOps}
                  runtimeLaneDiagnostics={runtimeLaneDiagnostics}
                />
              ) : null}
            </>
          ) : null}
        </main>
      </section>
    </div>
  );
}
