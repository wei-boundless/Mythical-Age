import type {
  OrchestrationAgentGroup,
  OrchestrationAgentRuntimeCatalog,
  OrchestrationAgentRuntimeProfile,
  OrchestrationAgentUpsertPayload,
  OrchestrationOption,
  ToolPackageDefinition,
  ToolPackageSelection,
} from "@/lib/api";

export type AgentCategory = "main_agent" | "builtin_agent" | "custom_agent";
export type AgentDirectorySection = "main_agent" | "builtin_system_agent" | "builtin_specialist_agent" | "custom_agent";
export type OrchestrationLayer =
  | "identity"
  | "groups"
  | "runtime_permissions"
  | "runtime_config"
  | "model_runtime"
  | "context_memory"
  | "collaboration"
  | "overview"
  | "diagnostics";
export type AssemblySelectionKind = "agent" | "group" | "empty";

export type AssemblyAgentRecord = Record<string, unknown> & {
  runtime_profile?: Partial<OrchestrationAgentRuntimeProfile>;
};

export type AgentDraft = OrchestrationAgentUpsertPayload;
export type RuntimeDraft = OrchestrationAgentRuntimeProfile;
export type AgentGroupDraft = OrchestrationAgentGroup & {
  member_agent_ids_text: string;
};

export type LayerTab = [OrchestrationLayer, string, string];
export type LayerNavGroup = {
  title: string;
  items: LayerTab[];
};

export const CATEGORY_ORDER: AgentCategory[] = ["main_agent", "builtin_agent", "custom_agent"];
export const DIRECTORY_SECTION_ORDER: AgentDirectorySection[] = [
  "main_agent",
  "builtin_system_agent",
  "builtin_specialist_agent",
  "custom_agent",
];
export const DEFAULT_SUB_AGENT_GROUP_ID = "__default_sub_agent_group__";

export const CATEGORY_LABELS: Record<AgentCategory, string> = {
  main_agent: "主 Agent",
  builtin_agent: "内置 Agent",
  custom_agent: "子 Agent",
};

export const DIRECTORY_SECTION_LABELS: Record<AgentDirectorySection, string> = {
  main_agent: "主 Agent",
  builtin_system_agent: "系统 Agent",
  builtin_specialist_agent: "专业内置 Agent",
  custom_agent: "子 Agent",
};

export const DIRECTORY_SECTION_DESCRIPTIONS: Record<AgentDirectorySection, string> = {
  main_agent: "主会话入口与最终整合输出",
  builtin_system_agent: "系统管理与平台治理 Agent",
  builtin_specialist_agent: "知识、PDF、表格、网页等专业 Agent",
  custom_agent: "可分组、可作为子 Agent 的任务执行 Agent",
};

export const EMPTY_AGENT_DRAFT: AgentDraft = {
  agent_id: "",
  agent_name: "",
  agent_category: "custom_agent",
  interface_target: "worker_task_console",
  description: "",
  enabled: true,
  editable: true,
  default_projection_id: "",
  metadata: { managed_by: "orchestration_console" },
};

export const EMPTY_RUNTIME_DRAFT: RuntimeDraft = {
  agent_profile_id: "",
  agent_id: "",
  allowed_tool_packages: [],
  extra_allowed_operations: ["op.model_response"],
  allowed_operations: ["op.model_response"],
  final_allowed_operations: ["op.model_response"],
  blocked_operations: [],
  allowed_memory_scopes: [],
  allowed_context_sections: [],
  subagent_policy: {
    enabled: false,
    allowed_subagent_ids: [],
    max_subagent_runs_per_task: 1,
    max_active_subagents: 1,
    context_policy: "summary_and_refs_only",
    result_policy: "observation_refs_only",
    allow_nested_subagents: false,
  },
  approval_policy: "default",
  trace_policy: "runtime_event_log",
  lifecycle_policy: "orchestration_managed",
  model_profile: {},
  metadata: { managed_by: "orchestration_console" },
};

export const EMPTY_GROUP_DRAFT: AgentGroupDraft = {
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

export function formatAssemblyText(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  return String(value);
}

export function displayAssemblyId(
  value: unknown,
  fallback = "未配置",
  registeredLabel?: (value: string, fallback?: string) => string,
) {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const registryLabel = registeredLabel?.(raw, fallback);
  if (registryLabel && registryLabel !== raw) return registryLabel;
  const labels: Record<string, string> = {
    main_agent: "主 Agent",
    builtin_agent: "内置 Agent",
    custom_agent: "子 Agent",
    coordination_team: "协调任务组",
    worker_pool: "执行池",
    review_team: "审查组",
    enabled: "启用",
    disabled: "停用",
    draft: "草稿",
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
    batch_edit_file: "批量编辑文件",
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

export function splitList(value: string) {
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function uniqueList(value: unknown) {
  return Array.isArray(value)
    ? Array.from(new Set(value.map((item) => String(item || "").trim()).filter(Boolean)))
    : [];
}

export function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function agentCategory(agent: AssemblyAgentRecord | null | undefined): AgentCategory {
  const value = String(agent?.agent_category || agent?.profile_type || "custom_agent");
  return CATEGORY_ORDER.includes(value as AgentCategory) ? (value as AgentCategory) : "custom_agent";
}

export function agentDirectorySection(agent: AssemblyAgentRecord | null | undefined): AgentDirectorySection {
  const category = agentCategory(agent);
  if (category !== "builtin_agent") return category;
  const metadata = recordOf(agent?.metadata);
  const builtinKind = String(agent?.builtin_kind || metadata.builtin_kind || "").trim();
  const role = String(metadata.role || "").trim();
  return builtinKind === "specialist" || role === "worker_specialist"
    ? "builtin_specialist_agent"
    : "builtin_system_agent";
}

export function isGroupEligibleAgent(agent: AssemblyAgentRecord | null | undefined) {
  return Boolean(agent?.group_eligible) || agentCategory(agent) === "custom_agent";
}

export function displayAgentName(
  agent: AssemblyAgentRecord | null | undefined,
  displayId: (value: unknown, fallback?: string) => string = displayAssemblyId,
) {
  return formatAssemblyText(agent?.agent_name || agent?.display_name, displayId(agent?.agent_id, "未命名 Agent"));
}

export function normalizeSubagentPolicy(policy?: Partial<OrchestrationAgentRuntimeProfile["subagent_policy"]>) {
  const raw = policy ?? {};
  const allowedIds = uniqueList(raw.allowed_subagent_ids);
  return {
    enabled: Boolean(raw.enabled) && Boolean(allowedIds.length),
    allowed_subagent_ids: allowedIds,
    max_subagent_runs_per_task: Math.max(0, Number(raw.max_subagent_runs_per_task ?? 1)),
    max_active_subagents: Math.max(0, Number(raw.max_active_subagents ?? 1)),
    context_policy: String(raw.context_policy || "summary_and_refs_only"),
    result_policy: String(raw.result_policy || "observation_refs_only"),
    allow_nested_subagents: Boolean(raw.allow_nested_subagents),
  };
}

export function normalizeToolPackageSelections(value?: OrchestrationAgentRuntimeProfile["allowed_tool_packages"]): ToolPackageSelection[] {
  return Array.isArray(value)
    ? value
      .map((item) => ({
        package_id: String(item?.package_id || "").trim(),
        enabled: item?.enabled !== false,
        include_operations: uniqueList(item?.include_operations ?? []),
        exclude_operations: uniqueList(item?.exclude_operations ?? []),
      }))
      .filter((item) => item.package_id)
    : [];
}

export function packageOperations(selection: ToolPackageSelection, toolPackages: ToolPackageDefinition[]) {
  if (!selection.enabled) return [];
  const definition = toolPackages.find((item) => item.package_id === selection.package_id);
  const base = selection.include_operations.length ? selection.include_operations : definition?.operation_ids ?? [];
  const excluded = new Set(selection.exclude_operations);
  return uniqueList(base).filter((operation) => !excluded.has(operation));
}

export function effectiveAllowedOperations(draft: Partial<OrchestrationAgentRuntimeProfile>, toolPackages: ToolPackageDefinition[]) {
  const blocked = new Set(uniqueList(draft.blocked_operations ?? []));
  if (!toolPackages.length) {
    const resolved = uniqueList(draft.final_allowed_operations ?? draft.allowed_operations ?? []);
    const fallback = resolved.length ? resolved : uniqueList(["op.model_response", ...(draft.extra_allowed_operations ?? [])]);
    return fallback.filter((operation) => !blocked.has(operation));
  }
  const selectedPackages = normalizeToolPackageSelections(draft.allowed_tool_packages);
  const packageOps = selectedPackages.flatMap((selection) => packageOperations(selection, toolPackages));
  const extraOps = uniqueList(draft.extra_allowed_operations ?? []);
  return uniqueList(["op.model_response", ...packageOps, ...extraOps]).filter((operation) => !blocked.has(operation));
}

export function normalizeModelProfile(profile?: OrchestrationAgentRuntimeProfile["model_profile"]) {
  const { base_url: _legacyBaseUrl, ...rest } = ((profile ?? {}) as OrchestrationAgentRuntimeProfile["model_profile"] & { base_url?: string });
  return {
    ...rest,
    capability_tags: uniqueList(rest.capability_tags ?? []),
    stream_policy: rest.stream_policy ?? {},
    metadata: rest.metadata ?? {},
  };
}

export function makeCustomGroupId(existingGroups: OrchestrationAgentGroup[]) {
  let index = existingGroups.length + 1;
  let groupId = `group.custom.worker_group_${String(index).padStart(2, "0")}`;
  const existingIds = new Set(existingGroups.map((group) => group.group_id));
  while (existingIds.has(groupId)) {
    index += 1;
    groupId = `group.custom.worker_group_${String(index).padStart(2, "0")}`;
  }
  return groupId;
}

export function optionLabelMap(options: OrchestrationOption[] = []) {
  return new Map(options.map((item) => [item.value || item.id, item.label || item.value || item.id]));
}

export function displayOptionList(values: string[], labels: Map<string, string>, fallback = "未配置") {
  return values.length ? values.map((item) => labels.get(item) || displayAssemblyId(item)).join(" / ") : fallback;
}

export function mergeOrchestrationOptions(
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

export function agentDraftFrom(agent?: AssemblyAgentRecord | null): AgentDraft {
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
    default_projection_id: String(agent.default_projection_id || ""),
    metadata: { ...metadata, managed_by: "orchestration_console" },
  };
}

export function runtimeDraftFrom(
  agentId: string,
  profile?: Partial<OrchestrationAgentRuntimeProfile>,
): RuntimeDraft {
  const merged = { ...EMPTY_RUNTIME_DRAFT, ...(profile ?? {}), agent_id: agentId };
  const profileId = String(merged.agent_profile_id || `${agentId.replace(/[:]/g, "_")}_runtime`);
  const allowedOps = uniqueList(merged.final_allowed_operations ?? merged.allowed_operations).length
    ? uniqueList(merged.final_allowed_operations ?? merged.allowed_operations)
    : ["op.model_response"];
  const extraAllowedOps = uniqueList(merged.extra_allowed_operations ?? []).length
    ? uniqueList(merged.extra_allowed_operations ?? [])
    : ["op.model_response"];
  return {
    ...merged,
    agent_profile_id: profileId,
    allowed_tool_packages: normalizeToolPackageSelections(merged.allowed_tool_packages),
    extra_allowed_operations: extraAllowedOps,
    allowed_operations: allowedOps,
    final_allowed_operations: allowedOps,
    blocked_operations: uniqueList(merged.blocked_operations),
    allowed_memory_scopes: uniqueList(merged.allowed_memory_scopes),
    allowed_context_sections: uniqueList(merged.allowed_context_sections),
    subagent_policy: normalizeSubagentPolicy(merged.subagent_policy),
    approval_policy: String(merged.approval_policy || "default"),
    trace_policy: String(merged.trace_policy || "runtime_event_log"),
    lifecycle_policy: String(merged.lifecycle_policy || "orchestration_managed"),
    model_profile: normalizeModelProfile(merged.model_profile),
    metadata: merged.metadata ?? { managed_by: "orchestration_console" },
  };
}

export function runtimePayloadFromDraft(draft: RuntimeDraft) {
  return {
    agent_profile_id: draft.agent_profile_id,
    allowed_tool_packages: normalizeToolPackageSelections(draft.allowed_tool_packages),
    extra_allowed_operations: Array.from(new Set(["op.model_response", ...uniqueList(draft.extra_allowed_operations ?? [])])),
    blocked_operations: uniqueList(draft.blocked_operations),
    allowed_memory_scopes: uniqueList(draft.allowed_memory_scopes),
    allowed_context_sections: uniqueList(draft.allowed_context_sections),
    subagent_policy: normalizeSubagentPolicy(draft.subagent_policy),
    approval_policy: draft.approval_policy,
    trace_policy: draft.trace_policy,
    lifecycle_policy: draft.lifecycle_policy,
    model_profile: normalizeModelProfile(draft.model_profile),
    metadata: { ...(draft.metadata ?? {}), managed_by: "orchestration_console" },
  };
}

export function groupDraftFrom(group?: OrchestrationAgentGroup | null): AgentGroupDraft {
  const base = group ?? EMPTY_GROUP_DRAFT;
  return {
    ...base,
    member_agent_ids: base.member_agent_ids ?? [],
    metadata: base.metadata ?? { managed_by: "orchestration_console" },
    member_agent_ids_text: uniqueList(base.member_agent_ids ?? []).join("\n"),
  };
}

export function groupPayloadFromDraft(draft: AgentGroupDraft): OrchestrationAgentGroup {
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

export function searchText(agent: AssemblyAgentRecord) {
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
