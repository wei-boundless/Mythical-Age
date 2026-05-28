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
  OrchestrationModelRuntimeWorkbench,
  OrchestrationRuntimePermissionWorkbench,
  OrchestrationRuntimeConfigWorkbench,
} from "@/components/workspace/views/orchestration/OrchestrationAgentConfigWorkbenches";
import { OrchestrationGroupWorkbench } from "@/components/workspace/views/orchestration/OrchestrationGroupWorkbench";
import { OrchestrationRegistryWorkbench } from "@/components/workspace/views/orchestration/OrchestrationRegistryWorkbench";
import { OrchestrationToolbarButton } from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";
import { taskSystemDisplayLabel } from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { useAppStore } from "@/lib/store";
import {
  normalizeDefaultRuntimeMode,
  normalizeRuntimeModes,
  runtimeModeCatalogFrom,
} from "@/lib/runtimeModeConfig";

type AgentCategory = "main_agent" | "builtin_agent" | "custom_agent";
type OrchestrationLayer = "identity" | "groups" | "runtime_permissions" | "runtime_config" | "model_runtime" | "context_memory" | "collaboration" | "overview" | "diagnostics";
type AssemblySelectionKind = "agent" | "group" | "empty";

type AgentDraft = OrchestrationAgentUpsertPayload & {
};

type RuntimeDraft = OrchestrationAgentRuntimeProfile;

type AgentGroupDraft = OrchestrationAgentGroup & {
  member_agent_ids_text: string;
};

const CATEGORY_ORDER: AgentCategory[] = ["main_agent", "builtin_agent", "custom_agent"];
const DEFAULT_SUB_AGENT_GROUP_ID = "__default_sub_agent_group__";

const CATEGORY_LABELS: Record<AgentCategory, string> = {
  main_agent: "主 Agent",
  builtin_agent: "内置 Agent",
  custom_agent: "子 Agent",
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
  enabled_runtime_modes: ["custom"],
  default_runtime_mode: "custom",
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
  model_profile: {},
  metadata: { managed_by: "orchestration_console" },
};

const EMPTY_GROUP_DRAFT: AgentGroupDraft = {
  group_id: "group.custom.worker_group_01",
  title: "新子 Agent 组",
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
    custom_agent: "子 Agent",
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

function normalizeModelProfile(profile?: OrchestrationAgentRuntimeProfile["model_profile"]) {
  const { base_url: _legacyBaseUrl, ...rest } = ((profile ?? {}) as OrchestrationAgentRuntimeProfile["model_profile"] & { base_url?: string });
  return {
    ...rest,
    capability_tags: uniqueList(rest.capability_tags ?? []),
    stream_policy: rest.stream_policy ?? {},
    metadata: rest.metadata ?? {},
  };
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
  const enabledModes = normalizeRuntimeModes((merged as Record<string, unknown>).enabled_runtime_modes, runtimeModeCatalogFrom(merged.runtime_mode_catalog), "custom");
  const defaultMode = normalizeDefaultRuntimeMode((merged as Record<string, unknown>).default_runtime_mode, enabledModes);
  return {
    ...merged,
    agent_profile_id: profileId,
    enabled_runtime_modes: enabledModes,
    default_runtime_mode: defaultMode,
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
    model_profile: normalizeModelProfile(merged.model_profile),
    metadata: merged.metadata ?? { managed_by: "orchestration_console" },
  };
}

function runtimePayloadFromDraft(draft: RuntimeDraft) {
  const enabledModes = normalizeRuntimeModes((draft as Record<string, unknown>).enabled_runtime_modes, runtimeModeCatalogFrom(draft.runtime_mode_catalog), "custom");
  const defaultMode = normalizeDefaultRuntimeMode((draft as Record<string, unknown>).default_runtime_mode, enabledModes);
  return {
    agent_profile_id: draft.agent_profile_id,
    enabled_runtime_modes: enabledModes,
    default_runtime_mode: defaultMode,
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
    model_profile: normalizeModelProfile(draft.model_profile),
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
  const confirm = useConfirmDialog();
  const { orchestrationInspectorTarget } = useAppStore();
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
        setSelectedGroupId(DEFAULT_SUB_AGENT_GROUP_ID);
        setActiveLayer("groups");
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

  useEffect(() => {
    if (activeLayer !== "runtime_permissions") return;
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
  }, [activeLayer]);

  const agents = useMemo(() => catalog?.agents ?? [], [catalog]);
  const agentGroups = useMemo(() => catalog?.agent_groups ?? [], [catalog]);
  const projectionCards = useMemo(() => projectionCatalog?.cards ?? [], [projectionCatalog]);
  const soulSeeds = useMemo(() => soulCatalog?.seeds ?? [], [soulCatalog]);

  useEffect(() => {
    if (!orchestrationInspectorTarget) return;
    const requestedLayer = orchestrationInspectorTarget.orchestrationLayer;
      const focusLayer =
      requestedLayer === "permissions"
        ? "runtime_permissions"
        : requestedLayer === "context"
          ? "context_memory"
          : requestedLayer === "model_runtime"
            ? "model_runtime"
          : requestedLayer === "registry"
            ? "identity"
            : requestedLayer === "runtime"
              ? "runtime_permissions"
              : requestedLayer === "eligibility"
                ? "diagnostics"
                : requestedLayer;
    const validLayers: OrchestrationLayer[] = ["identity", "groups", "runtime_permissions", "model_runtime", "context_memory", "collaboration", "overview", "diagnostics"];
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
          setSelectedGroupId(group?.group_id || DEFAULT_SUB_AGENT_GROUP_ID);
        }
      }
    }
    if (orchestrationInspectorTarget.reason) {
      setNotice(orchestrationInspectorTarget.reason);
    }
  }, [agentGroups, agents, orchestrationInspectorTarget]);

  const selectedAgent = agents.find((agent) => String(agent.agent_id) === selectedAgentId) ?? null;
  const selectedGroup = agentGroups.find((group) => group.group_id === selectedGroupId) ?? null;
  const selectedDefaultSubAgentGroup = activeCategory === "custom_agent" && selectedGroupId === DEFAULT_SUB_AGENT_GROUP_ID;
  const selectionKind: AssemblySelectionKind = activeCategory === "custom_agent" && activeLayer === "groups" && !selectedDefaultSubAgentGroup
    ? "group"
    : selectedAgent || agentMode === "new"
      ? "agent"
      : "empty";
  const selectedProfile = (selectedAgent?.runtime_profile ?? {}) as Partial<OrchestrationAgentRuntimeProfile>;
  const operationOptions = useMemo(
    () => (catalog?.options.operations ?? []).map((item) => String(item.operation_id || "")).filter(Boolean),
    [catalog],
  );
  const operationOptionItems = useMemo(() => catalog?.options.operation_options ?? [], [catalog]);
  const memoryScopeOptionItems = useMemo(() => catalog?.options.memory_scope_options ?? [], [catalog]);
  const contextSectionOptionItems = useMemo(() => catalog?.options.context_section_options ?? [], [catalog]);
  const approvalPolicyOptions = useMemo(() => catalog?.options.approval_policy_options ?? [], [catalog]);
  const tracePolicyOptions = useMemo(() => catalog?.options.trace_policy_options ?? [], [catalog]);
  const runtimeOptionLabels = useMemo(
    () => new Map([
      ...optionLabelMap(operationOptionItems),
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
    if (activeCategory !== "custom_agent") return;
    if (selectedGroupId === DEFAULT_SUB_AGENT_GROUP_ID) return;
    if (selectedGroupId && agentGroups.some((group) => group.group_id === selectedGroupId)) return;
    const firstGroupId = agentGroups[0]?.group_id || DEFAULT_SUB_AGENT_GROUP_ID;
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
  ]);

  const activeGroup = groupedAgents.find((group) => group.category === activeCategory);
  const agentDeleteBlocked = false;
  const profileMissing = Boolean(selectedAgent && !selectedProfile.agent_profile_id);
  const allowedOps = uniqueList(runtimeDraft.allowed_operations);
  const blockedOps = uniqueList(runtimeDraft.blocked_operations);
  const overlapOps = allowedOps.filter((item) => blockedOps.includes(item));
  const runtimeSaveBlocked = agentMode === "new" || !agentDraft.agent_id.trim();
  const builtinManagedAgent = Boolean(selectedAgent?.builtin);
  const modelProfile = runtimeDraft.model_profile ?? {};
  const runtimeConfig = (runtimeDraft.metadata?.runtime_config && typeof runtimeDraft.metadata.runtime_config === "object")
    ? runtimeDraft.metadata.runtime_config as Record<string, unknown>
    : {};
  const runtimeConfigMode = String(runtimeConfig.runtime_mode || runtimeConfig.template_id || "默认");
  const modelSummary = modelProfile.provider || modelProfile.model
    ? `${modelProfile.provider || "继承默认"} / ${modelProfile.model || "继承模型"}`
    : "继承系统默认";
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
    ["identity", "身份", agentMode === "new" ? "草稿" : "名册"],
    ["runtime_permissions", "权限", runtimeDraft.agent_profile_id && !runtimeSaveBlocked ? `${allowedOps.length} 项` : "待保存"],
    ["runtime_config", "运行配置", runtimeConfigMode],
    ["model_runtime", "模型", modelProfile.provider || modelProfile.model ? "覆盖" : "继承"],
    ["context_memory", "上下文", `${uniqueList(runtimeDraft.allowed_context_sections).length + uniqueList(runtimeDraft.allowed_memory_scopes).length}`],
    ["collaboration", "协作", runtimeDraft.can_delegate_to_agents ? "开放" : "关闭"],
    ["overview", "总览", "摘要"],
    ["diagnostics", "诊断", overlapOps.length ? "冲突" : "正常"],
  ];
  const layerTabs: Array<[OrchestrationLayer, string, string]> = selectionKind === "group"
    ? [["groups", "分组", String(splitList(groupDraft.member_agent_ids_text).length)]]
    : activeCategory === "custom_agent"
      ? [["groups", "分组", String(agentGroups.length)], ...agentLayerTabs]
      : agentLayerTabs;
  const activeLayerTab = layerTabs.find(([value]) => value === activeLayer) ?? layerTabs[0] ?? ["identity", "身份", ""];
  const activeLayerLabel = selectionKind === "group" ? "Agent 组" : activeLayerTab[1];
  const activeLayerHint = selectionKind === "group"
    ? "先定组，再看成员与协调者。"
    : activeLayerTab[2] || "当前层配置。";

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
  const runtimeModeSummary = displayOptionList(uniqueList(runtimeDraft.enabled_runtime_modes), runtimeOptionLabels);
  const memorySummary = displayOptionList(uniqueList(runtimeDraft.allowed_memory_scopes), runtimeOptionLabels);
  const contextSummary = displayOptionList(uniqueList(runtimeDraft.allowed_context_sections), runtimeOptionLabels);
  const operationSummary = `${allowedOps.length} 允许 / ${blockedOps.length} 阻断`;
  const collaborationSummary = runtimeDraft.can_delegate_to_agents
    ? `${uniqueList(runtimeDraft.allowed_delegate_agent_ids).length || "不限"} 个目标`
    : "未开放委派";
  const selectedGroupCoordinator = selectedGroup
    ? agents.find((agent) => String(agent.agent_id ?? "") === selectedGroup.coordinator_agent_id)
    : null;
  const focusSummary = selectionKind === "group"
    ? {
        eyebrow: groupMode === "new" ? "子 Agent 分组草稿" : "子 Agent 分组",
        title: groupDraft.title || groupDraft.group_id || "请选择或新建 Agent 组",
        body: groupDraft.description || `协调者 ${displayName(selectedGroupCoordinator)}`,
        id: groupDraft.group_id || "未生成组 ID",
        badge: groupMembersChanged ? "成员未保存" : `${splitList(groupDraft.member_agent_ids_text).length} 个成员`,
      }
    : {
        eyebrow: CATEGORY_LABELS[agentDraft.agent_category as AgentCategory] ?? "Agent",
        title: agentDraft.agent_name || agentDraft.agent_id || "请选择或新建 Agent",
        body: agentDraft.description || "配置 Agent 身份与运行边界。",
        id: agentDraft.agent_id || "未生成 ID",
        badge: agentMode === "new" ? "新建草稿" : builtinManagedAgent ? "内置来源" : "可配置",
      };
  const selectionKindLabel = selectionKind === "group" ? "Agent 组" : selectionKind === "agent" ? "Agent" : "待选";

  function selectCategory(category: AgentCategory) {
    setActiveCategory(category);
    const first = visibleAgents.find((agent) => agentCategory(agent) === category);
    setAgentMode("existing");
    if (category === "custom_agent") {
      setActiveLayer("groups");
      setGroupMode("existing");
      const firstGroup = agentGroups[0];
      setSelectedGroupId(firstGroup?.group_id || DEFAULT_SUB_AGENT_GROUP_ID);
      setSelectedAgentId("");
    } else {
      setSelectedGroupId("");
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
      setSelectedGroupId(group?.group_id || DEFAULT_SUB_AGENT_GROUP_ID);
    } else {
      setSelectedGroupId("");
    }
    setActiveLayer("identity");
  }

  function selectSubAgentGroup(groupId: string) {
    setSelectedGroupId(groupId);
    setGroupMode("existing");
    setAgentMode("existing");
    if (groupId === DEFAULT_SUB_AGENT_GROUP_ID) {
      const firstDefaultAgentId = String(ungroupedCustomAgents[0]?.agent_id || "");
      setSelectedAgentId(firstDefaultAgentId);
      setActiveLayer(firstDefaultAgentId ? "identity" : "groups");
      return;
    }
    setSelectedAgentId("");
    setActiveLayer("groups");
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
    setSelectedGroupId(DEFAULT_SUB_AGENT_GROUP_ID);
    setActiveCategory("custom_agent");
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
    setNotice("已进入新子 Agent 草稿。先保存 Agent 名册，再配置运行档案。");
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
    setActiveCategory("custom_agent");
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
      setActiveLayer("groups");
      setNotice(`${currentGroup?.title || selectedGroupId} 已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 Agent 组失败");
    } finally {
      setSaving("");
    }
  }

  return (
    <div className="workspace-view boundary-console orchestration-boundary orchestration-console">
      <header className="orchestration-console-head">
        <div className="orchestration-console-head__title">
          <span>Agent Assembly</span>
          <h2>编排系统</h2>
          <p>{agents.length} 个 Agent / {agentGroups.length} 个分组 / {catalog?.profiles?.length ?? 0} 个运行档案</p>
        </div>
        <div className="orchestration-console-head__summary" aria-label="对象摘要">
          <div>
            <span>当前装配对象</span>
            <strong>{focusSummary.title}</strong>
            <small>{focusSummary.body}</small>
          </div>
          <div>
            <span>当前步骤</span>
            <strong>{activeLayerLabel}</strong>
            <small>{activeLayerHint}</small>
          </div>
          <div>
            <span>对象类型</span>
            <strong>{selectionKindLabel}</strong>
            <small>{focusSummary.id}</small>
          </div>
          <div>
            <span>运行权限</span>
            <strong>{allowedOps.length} 允 / {blockedOps.length} 阻</strong>
            <small>{overlapOps.length ? `${overlapOps.length} 项冲突` : "无冲突"}</small>
          </div>
        </div>
        <div className="boundary-actions orchestration-console-head__actions">
          <OrchestrationToolbarButton onClick={startBlankAgentDraft}><UserCog size={15} />新建 Agent</OrchestrationToolbarButton>
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
          selectionKind={selectionKind}
          selectSubAgentGroup={selectSubAgentGroup}
          setQuery={setQuery}
          selectedGroupAgents={selectedGroupAgents}
          saving={saving}
          startBlankAgentDraft={startBlankAgentDraft}
          startBlankGroupDraft={startBlankGroupDraft}
          ungroupedCustomAgents={ungroupedCustomAgents}
          removeAgentById={async (agentId, agentName) => {
            if (await confirm({
              title: `删除 Agent「${agentName || agentId}」`,
              body: "该 Agent 会从编排配置中移除。",
              confirmLabel: "删除 Agent",
            })) {
              void removeAgent(agentId);
            }
          }}
          removeSelectedGroup={() => void removeAgentGroup()}
        />

        <main className="boundary-main orchestration-config-main">
          <nav className="boundary-layer-tabs orchestration-config-tabs" aria-label="编排配置页面">
            {layerTabs.map(([value, label, meta]) => (
              <button className={activeLayer === value ? "boundary-layer-tabs__item boundary-layer-tabs__item--active" : "boundary-layer-tabs__item"} key={value} onClick={() => setActiveLayer(value)} type="button">
                <span>{label}</span>
                <small>{meta}</small>
              </button>
            ))}
          </nav>

          {selectionKind === "empty" ? <div className="boundary-empty boundary-empty--large">请选择一个 Agent，或新建子 Agent 草稿。</div> : null}

          {selectionKind === "group" ? (
            <OrchestrationGroupWorkbench
              agents={agents}
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
                  runtimeModeSummary={runtimeModeSummary}
                  tracePolicyOptions={tracePolicyOptions}
                  tracePolicies={catalog?.options.trace_policies ?? ["runtime_event_log"]}
                  operationOptionItems={operationOptionItems}
                  operationOptions={operationOptions}
                  overlapOps={overlapOps}
                  overlapSummary={displayOptionList(overlapOps, runtimeOptionLabels, "无")}
                />
                </>
              ) : null}

              {activeLayer === "model_runtime" ? (
                <OrchestrationModelRuntimeWorkbench
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  providerCatalog={(catalog?.options as { model_provider_catalog?: Record<string, unknown> } | undefined)?.model_provider_catalog}
                  runtimeDraft={runtimeDraft}
                />
              ) : null}

              {activeLayer === "runtime_config" ? (
                <OrchestrationRuntimeConfigWorkbench
                  displayId={displayId}
                  patchRuntimeDraft={(patch) => setRuntimeDraft((current) => ({ ...current, ...patch }))}
                  runtimeDraft={runtimeDraft}
                  runtimeSaveBlocked={runtimeSaveBlocked}
                  saveRuntimeProfile={saveRuntimeProfile}
                  saving={saving}
                />
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
                  modelSummary={modelSummary}
                  runtimeSummary={runtimeModeSummary}
                />
              ) : null}

              {activeLayer === "diagnostics" ? (
                <OrchestrationDiagnosticsWorkbench
                  capabilityItemsCount={capabilityItems.length}
                  eligibilityChecks={eligibilityChecks}
                  overlapOps={overlapOps}
                  runtimeDraft={runtimeDraft}
                />
              ) : null}
            </>
          ) : null}
        </main>
      </section>
    </div>
  );
}
