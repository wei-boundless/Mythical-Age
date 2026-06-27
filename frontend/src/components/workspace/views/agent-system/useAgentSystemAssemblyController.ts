"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteAgentSystemAgent,
  deleteAgentSystemAgentGroup,
  getNextAgentSystemWorkerAgentId,
  getAgentSystemAgents,
  getAgentSystemCapabilityItems,
  getAgentSystemRuntimeOptions,
  updateAgentSystemAgentRuntimeProfile,
  upsertAgentSystemAgent,
  upsertAgentSystemAgentGroup,
  type AgentSystemAgentRuntimeCatalog,
  type AgentSystemCapabilityItem,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { taskSystemDisplayLabel } from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";

import {
  CATEGORY_LABELS,
  DEFAULT_SUB_AGENT_GROUP_ID,
  DIRECTORY_SECTION_DESCRIPTIONS,
  DIRECTORY_SECTION_LABELS,
  DIRECTORY_SECTION_ORDER,
  EMPTY_AGENT_DRAFT,
  EMPTY_GROUP_DRAFT,
  EMPTY_RUNTIME_DRAFT,
  agentCategory,
  agentDirectorySection,
  agentDraftFrom,
  displayAgentName,
  displayAssemblyId,
  displayOptionList,
  effectiveAllowedOperations,
  formatAssemblyText,
  groupDraftFrom,
  groupPayloadFromDraft,
  isGroupEligibleAgent,
  makeCustomGroupId,
  mergeAgentSystemOptions,
  optionLabelMap,
  runtimeDraftFrom,
  runtimePayloadFromDraft,
  searchText,
  selectedContextSystemGroups,
  splitList,
  uniqueList,
  type AgentDirectorySection,
  type AgentDraft,
  type AgentGroupDraft,
  type AssemblyAgentRecord,
  type AssemblySelectionKind,
  type LayerNavGroup,
  type LayerTab,
  type AgentSystemLayer,
  type RuntimeDraft,
} from "./agentSystemAssemblyModel";

export type AgentSystemSavingState = "" | "agent" | "runtime" | "group" | "create" | "delete";

export function useAgentSystemAssemblyController() {
  const { agentSystemInspectorTarget } = useAppStore();
  const [catalog, setCatalog] = useState<AgentSystemAgentRuntimeCatalog | null>(null);
  const [capabilityItems, setCapabilityItems] = useState<AgentSystemCapabilityItem[]>([]);
  const [capabilityItemsLoading, setCapabilityItemsLoading] = useState(false);
  const [capabilityItemsError, setCapabilityItemsError] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [activeSection, setActiveSection] = useState<AgentDirectorySection>("custom_agent");
  const [activeLayer, setActiveLayer] = useState<AgentSystemLayer>("groups");
  const [query, setQuery] = useState("");
  const [agentMode, setAgentMode] = useState<"existing" | "new">("existing");
  const [groupMode, setGroupMode] = useState<"existing" | "new">("existing");
  const [agentDraft, setAgentDraft] = useState<AgentDraft>(EMPTY_AGENT_DRAFT);
  const [runtimeDraft, setRuntimeDraft] = useState<RuntimeDraft>(EMPTY_RUNTIME_DRAFT);
  const [groupDraft, setGroupDraft] = useState<AgentGroupDraft>(EMPTY_GROUP_DRAFT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<AgentSystemSavingState>("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const displayId = useCallback(
    (value: unknown, fallback = "未配置") => displayAssemblyId(value, fallback, taskSystemDisplayLabel),
    [],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await getAgentSystemAgents({ includeOptions: false });
      const mergedPayload = mergeAgentSystemOptions(payload, payload.options);
      setCatalog(mergedPayload);
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
      void getAgentSystemRuntimeOptions()
        .then((runtimeOptions) => {
          setCatalog((current) => current ? mergeAgentSystemOptions(current, runtimeOptions.options) : current);
        })
        .catch((exc) => {
          setError(exc instanceof Error ? exc.message : "Agent 管理运行选项加载失败");
        });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Agent 管理系统加载失败");
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
    void getAgentSystemCapabilityItems()
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
  const selectedAgent = agents.find((agent) => String(agent.agent_id) === selectedAgentId) ?? null;
  const selectedGroup = agentGroups.find((group) => group.group_id === selectedGroupId) ?? null;
  const selectedDefaultSubAgentGroup = activeSection === "custom_agent" && selectedGroupId === DEFAULT_SUB_AGENT_GROUP_ID;
  const selectionKind: AssemblySelectionKind = activeSection === "custom_agent" && activeLayer === "groups" && !selectedDefaultSubAgentGroup
    ? "group"
    : selectedAgent || agentMode === "new"
      ? "agent"
      : "empty";
  const selectedProfile = (selectedAgent?.runtime_profile ?? {}) as Partial<RuntimeDraft>;

  useEffect(() => {
    if (!agentSystemInspectorTarget) return;
    const requestedLayer = agentSystemInspectorTarget.agentSystemLayer;
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
    const validLayers: AgentSystemLayer[] = ["identity", "groups", "runtime_permissions", "runtime_config", "model_runtime", "context_memory", "collaboration", "overview", "diagnostics"];
    if (focusLayer && validLayers.includes(focusLayer as AgentSystemLayer)) {
      setActiveLayer(focusLayer as AgentSystemLayer);
    }
    const focusAgentId = String(agentSystemInspectorTarget.agentId ?? "").trim();
    if (focusAgentId && agents.length) {
      const focusedAgent = agents.find((agent) => String(agent.agent_id ?? "") === focusAgentId);
      if (focusedAgent) {
        const category = agentCategory(focusedAgent);
        setSelectedAgentId(focusAgentId);
        setSelectedGroupId("");
        setAgentMode("existing");
        setGroupMode("existing");
        setActiveSection(agentDirectorySection(focusedAgent));
        if (category === "custom_agent") {
          const group = agentGroups.find((item) => item.member_agent_ids.some((memberId) => String(memberId) === focusAgentId));
          setSelectedGroupId(group?.group_id || DEFAULT_SUB_AGENT_GROUP_ID);
        }
      }
    }
    if (agentSystemInspectorTarget.reason) {
      setNotice(agentSystemInspectorTarget.reason);
    }
  }, [agentGroups, agents, agentSystemInspectorTarget]);

  const operationOptions = useMemo(
    () => (catalog?.options.operations ?? []).map((item) => String(item.operation_id || "")).filter(Boolean),
    [catalog],
  );
  const operationOptionItems = useMemo(() => catalog?.options.operation_options ?? [], [catalog]);
  const toolPackageOptions = useMemo(() => catalog?.options.tool_packages ?? [], [catalog]);
  const memoryScopeOptionItems = useMemo(() => catalog?.options.memory_scope_options ?? [], [catalog]);
  const contextSectionOptionItems = useMemo(() => catalog?.options.context_section_options ?? [], [catalog]);
  const systemGroupOptionItems = useMemo(() => catalog?.options.system_group_options ?? [], [catalog]);
  const approvalPolicyOptions = useMemo(() => catalog?.options.approval_policy_options ?? [], [catalog]);
  const tracePolicyOptions = useMemo(() => catalog?.options.trace_policy_options ?? [], [catalog]);
  const runtimeOptionLabels = useMemo(
    () => new Map([
      ...optionLabelMap(operationOptionItems),
      ...optionLabelMap(memoryScopeOptionItems),
      ...optionLabelMap(contextSectionOptionItems),
      ...optionLabelMap(systemGroupOptionItems),
      ...optionLabelMap(approvalPolicyOptions),
      ...optionLabelMap(tracePolicyOptions),
    ]),
    [
      approvalPolicyOptions,
      contextSectionOptionItems,
      memoryScopeOptionItems,
      operationOptionItems,
      systemGroupOptionItems,
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
  const directoryGroups = useMemo(
    () =>
      DIRECTORY_SECTION_ORDER.map((section) => ({
        section,
        label: DIRECTORY_SECTION_LABELS[section],
        description: DIRECTORY_SECTION_DESCRIPTIONS[section],
        items: visibleAgents.filter((agent) => agentDirectorySection(agent) === section),
      })),
    [visibleAgents],
  );

  useEffect(() => {
    if (!selectedAgent) return;
    setAgentDraft(agentDraftFrom(selectedAgent));
    setRuntimeDraft(runtimeDraftFrom(String(selectedAgent.agent_id), selectedProfile));
    setAgentMode("existing");
    setActiveSection(agentDirectorySection(selectedAgent));
  }, [selectedAgentId, selectedAgent]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (groupMode === "new") return;
    setGroupDraft(groupDraftFrom(selectedGroup));
  }, [selectedGroup, groupMode]);

  useEffect(() => {
    if (loading || groupMode === "new") return;
    if (activeSection !== "custom_agent") return;
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
    activeSection,
    activeLayer,
    agentGroups,
    groupMode,
    loading,
    selectedAgentId,
    selectedGroupId,
  ]);

  const activeDirectoryGroup = directoryGroups.find((group) => group.section === activeSection);
  const agentDeleteBlocked = false;
  const profileMissing = Boolean(selectedAgent && !selectedProfile.agent_profile_id);
  const allowedOps = effectiveAllowedOperations(runtimeDraft, toolPackageOptions);
  const blockedOps = uniqueList(runtimeDraft.blocked_operations);
  const overlapOps = allowedOps.filter((item) => blockedOps.includes(item));
  const runtimeSaveBlocked = agentMode === "new" || !agentDraft.agent_id.trim();
  const builtinManagedAgent = Boolean(selectedAgent?.builtin);
  const modelProfile = runtimeDraft.model_profile ?? {};
  const runtimeConfig = (runtimeDraft.metadata?.runtime_config && typeof runtimeDraft.metadata.runtime_config === "object")
    ? runtimeDraft.metadata.runtime_config as Record<string, unknown>
    : {};
  const runtimeConfigMode = String(runtimeConfig.runtime_kind || runtimeConfig.template_id || "默认");
  const modelSummary = modelProfile.provider || modelProfile.model
    ? `${modelProfile.provider || "继承默认"} / ${modelProfile.model || "继承模型"}`
    : "继承系统默认";
  const sectionCounts = directoryGroups.reduce<Record<string, number>>((acc, group) => {
    acc[group.section] = group.items.length;
    return acc;
  }, {});
  const eligibilityChecks = [
    { label: "类别", value: CATEGORY_LABELS[agentDraft.agent_category as keyof typeof CATEGORY_LABELS] ?? formatAssemblyText(agentDraft.agent_category), ready: Boolean(agentDraft.agent_category) },
    { label: "允许操作", value: displayOptionList(allowedOps.slice(0, 4), runtimeOptionLabels), ready: Boolean(allowedOps.length) },
    { label: "阻断冲突", value: overlapOps.length ? overlapOps.join(" / ") : "无", ready: !overlapOps.length },
    { label: "上下文段", value: displayOptionList(uniqueList(runtimeDraft.allowed_context_sections).slice(0, 4), runtimeOptionLabels), ready: Boolean(uniqueList(runtimeDraft.allowed_context_sections).length) },
  ];
  const agentLayerTabs: LayerTab[] = [
    ["identity", "身份", agentMode === "new" ? "草稿" : "名册"],
    ["runtime_permissions", "权限", runtimeDraft.agent_profile_id && !runtimeSaveBlocked ? `${allowedOps.length} 项` : "待保存"],
    ["runtime_config", "运行配置", runtimeConfigMode],
    ["model_runtime", "模型", modelProfile.provider || modelProfile.model ? "覆盖" : "继承"],
    ["context_memory", "上下文", `${uniqueList(runtimeDraft.allowed_context_sections).length + uniqueList(runtimeDraft.allowed_memory_scopes).length}`],
    ["collaboration", "协作", runtimeDraft.subagent_policy.enabled ? "开放" : "关闭"],
    ["overview", "总览", "摘要"],
    ["diagnostics", "诊断", overlapOps.length ? "冲突" : "正常"],
  ];
  const layerTabs: LayerTab[] = selectionKind === "group"
    ? [["groups", "分组", String(splitList(groupDraft.member_agent_ids_text).length)]]
    : activeSection === "custom_agent"
      ? [["groups", "分组", String(agentGroups.length)], ...agentLayerTabs]
      : agentLayerTabs;
  const assemblyNavGroups: LayerNavGroup[] = selectionKind === "group"
    ? [{ title: "Agent 组", items: layerTabs }]
    : [
        { title: "对象定义", items: layerTabs.filter(([value]) => value === "groups" || value === "identity" || value === "overview") },
        { title: "运行边界", items: layerTabs.filter(([value]) => value === "runtime_permissions" || value === "runtime_config" || value === "model_runtime") },
        { title: "上下文协作", items: layerTabs.filter(([value]) => value === "context_memory" || value === "collaboration") },
        { title: "核验", items: layerTabs.filter(([value]) => value === "diagnostics") },
      ].filter((group) => group.items.length);
  const activeLayerTab = layerTabs.find(([value]) => value === activeLayer) ?? layerTabs[0] ?? (["identity", "身份", ""] as LayerTab);
  const activeLayerLabel = selectionKind === "group" ? "Agent 组" : activeLayerTab[1];
  const activeLayerHint = selectionKind === "group"
    ? "先定组，再看成员与协调者。"
    : activeLayerTab[2] || "当前层配置。";

  const selectedGroupAgents = useMemo(() => {
    if (!selectedGroup) return [];
    const memberIds = new Set((selectedGroup.member_agent_ids ?? []).map((item) => String(item)));
    return visibleCustomAgents.filter((agent) => memberIds.has(String(agent.agent_id)));
  }, [selectedGroup, visibleCustomAgents]);
  const subagentOptions = useMemo(
    () =>
      agents
        .filter((agent) => String(agent.agent_id || "") !== String(agentDraft.agent_id || ""))
        .map((agent) => ({
          id: String(agent.agent_id || ""),
          value: String(agent.agent_id || ""),
          label: displayAgentName(agent, displayId),
          description: String(agent.description || ""),
          category: CATEGORY_LABELS[agentCategory(agent)],
        })),
    [agentDraft.agent_id, agents, displayId],
  );
  const memorySummary = displayOptionList(uniqueList(runtimeDraft.allowed_memory_scopes), runtimeOptionLabels);
  const contextSummary = displayOptionList(uniqueList(runtimeDraft.allowed_context_sections), runtimeOptionLabels);
  const systemGroupSummary = displayOptionList(
    selectedContextSystemGroups(runtimeDraft.metadata, systemGroupOptionItems),
    runtimeOptionLabels,
  );
  const overlapSummary = displayOptionList(overlapOps, runtimeOptionLabels, "无");
  const operationSummary = `${allowedOps.length} 允许 / ${blockedOps.length} 阻断`;
  const collaborationSummary = runtimeDraft.subagent_policy.enabled
    ? `${uniqueList(runtimeDraft.subagent_policy.allowed_subagent_ids).length || "不限"} 个目标`
    : "未开放子 Agent";
  const selectedGroupCoordinator = selectedGroup
    ? agents.find((agent) => String(agent.agent_id ?? "") === selectedGroup.coordinator_agent_id)
    : null;
  const focusSummary = selectionKind === "group"
    ? {
        eyebrow: groupMode === "new" ? "子 Agent 分组草稿" : "子 Agent 分组",
        title: groupDraft.title || groupDraft.group_id || "请选择或新建 Agent 组",
        body: groupDraft.description || `协调者 ${displayAgentName(selectedGroupCoordinator, displayId)}`,
        id: groupDraft.group_id || "未生成组 ID",
        badge: groupMembersChanged ? "成员未保存" : `${splitList(groupDraft.member_agent_ids_text).length} 个成员`,
      }
    : {
        eyebrow: CATEGORY_LABELS[agentDraft.agent_category as keyof typeof CATEGORY_LABELS] ?? "Agent",
        title: agentDraft.agent_name || agentDraft.agent_id || "请选择或新建 Agent",
        body: agentDraft.description || "配置 Agent 身份与运行边界。",
        id: agentDraft.agent_id || "未生成 ID",
        badge: agentMode === "new" ? "新建草稿" : builtinManagedAgent ? "内置来源" : "可配置",
      };
  const selectionKindLabel = selectionKind === "group" ? "Agent 组" : selectionKind === "agent" ? "Agent" : "待选";

  function selectCategory(section: AgentDirectorySection) {
    setActiveSection(section);
    const first = visibleAgents.find((agent) => agentDirectorySection(agent) === section);
    setAgentMode("existing");
    if (section === "custom_agent") {
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
      setActiveSection("custom_agent");
      setSelectedGroupId(group?.group_id || DEFAULT_SUB_AGENT_GROUP_ID);
    } else {
      setActiveSection(agentDirectorySection(agent));
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
      const nextId = await getNextAgentSystemWorkerAgentId();
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
    setActiveSection("custom_agent");
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
        managed_by: "agent_system_console",
      };
      const payload = await upsertAgentSystemAgent(agentDraft.agent_id, {
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
      const payload = await updateAgentSystemAgentRuntimeProfile(agentDraft.agent_id, runtimePayloadFromDraft(runtimeDraft));
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
      const payload = await upsertAgentSystemAgentGroup(groupDraft.group_id, groupPayloadFromDraft(groupDraft));
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
    setActiveSection("custom_agent");
    setActiveLayer("groups");
    setGroupMode("new");
    setSelectedGroupId("");
    setGroupDraft({
      ...EMPTY_GROUP_DRAFT,
      group_id: makeCustomGroupId(agentGroups),
      title: "新子 Agent 组",
      metadata: { managed_by: "agent_system_console" },
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
      const payload = await deleteAgentSystemAgent(String(targetAgent.agent_id));
      const firstCustomAgent = payload.agents.find((agent) => agentCategory(agent) === "custom_agent");
      const nextAgent = firstCustomAgent ?? payload.agents[0] ?? null;
      setCatalog(payload);
      setSelectedAgentId(String(nextAgent?.agent_id || ""));
      setActiveSection(agentDirectorySection(nextAgent));
      setGroupMode("existing");
      setNotice(`${displayAgentName(targetAgent, displayId)} 已删除。`);
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
      const payload = await deleteAgentSystemAgentGroup(selectedGroupId);
      const nextGroupId = String(payload.agent_groups?.[0]?.group_id || "");
      setCatalog(payload);
      setSelectedGroupId(nextGroupId);
      setSelectedAgentId("");
      setGroupMode("existing");
      setActiveSection("custom_agent");
      setActiveLayer("groups");
      setNotice(`${currentGroup?.title || selectedGroupId} 已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 Agent 组失败");
    } finally {
      setSaving("");
    }
  }

  const patchAgentDraft = useCallback((patch: Partial<AgentDraft>) => {
    setAgentDraft((current) => ({ ...current, ...patch }));
  }, []);

  const patchRuntimeDraft = useCallback((patch: Partial<RuntimeDraft>) => {
    setRuntimeDraft((current) => ({ ...current, ...patch }));
  }, []);

  return {
    activeDirectoryGroup,
    activeLayer,
    activeLayerHint,
    activeLayerLabel,
    activeSection,
    agentDeleteBlocked,
    agentDraft,
    agentGroups,
    agentMode,
    agents: agents as AssemblyAgentRecord[],
    allowedOps,
    approvalPolicyOptions,
    assemblyNavGroups,
    blockedOps,
    capabilityItems,
    capabilityItemsError,
    capabilityItemsLoading,
    catalog,
    collaborationSummary,
    contextSectionOptionItems,
    contextSummary,
    displayId,
    eligibilityChecks,
    error,
    focusSummary,
    groupDraft,
    groupDraftAvailableAgents,
    groupDraftMemberAgents,
    groupMembersChanged,
    load,
    loading,
    memoryScopeOptionItems,
    memorySummary,
    modelProfile,
    modelSummary,
    notice,
    operationOptionItems,
    operationOptions,
    operationSummary,
    overlapOps,
    overlapSummary,
    patchAgentDraft,
    patchRuntimeDraft,
    profileMissing,
    query,
    removeAgent,
    removeAgentGroup,
    runtimeConfigMode,
    runtimeDraft,
    runtimeOptionLabels,
    runtimeSaveBlocked,
    saveAgent,
    saveAgentGroup,
    saveRuntimeProfile,
    saving,
    sectionCounts,
    selectAgent,
    selectCategory,
    selectSubAgentGroup,
    selectedAgent,
    selectedAgentId,
    selectedGroup,
    selectedGroupAgents,
    selectedGroupId,
    selectionKind,
    selectionKindLabel,
    setActiveLayer,
    setGroupDraft,
    setQuery,
    startBlankAgentDraft,
    startBlankGroupDraft,
    subagentOptions,
    systemGroupOptionItems,
    systemGroupSummary,
    toolPackageOptions,
    tracePolicyOptions,
    toggleGroupMember,
    ungroupedCustomAgents,
  };
}

export type AgentSystemAssemblyController = ReturnType<typeof useAgentSystemAssemblyController>;





