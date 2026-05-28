"use client";

import { AlertTriangle, BrainCircuit, CheckCircle2, Database, GitBranch, Info, KeyRound, Save, Settings2, ShieldCheck, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  OrchestrationBadge,
  OrchestrationField,
  OrchestrationOptionSelection,
  OrchestrationReadinessCard,
  type OrchestrationOption,
} from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";
import type { OrchestrationCapabilityItem } from "@/lib/api";
import {
  BUILTIN_RUNTIME_MODES,
  normalizeDefaultRuntimeMode,
  normalizeRuntimeModes,
  runtimeModeCatalogFrom,
  type RuntimeModeConfig,
} from "@/lib/runtimeModeConfig";

type RuntimeDraftLike = {
  agent_profile_id?: string;
  approval_policy?: string;
  trace_policy?: string;
  lifecycle_policy?: string;
  enabled_runtime_modes?: string[];
  default_runtime_mode?: string;
  allowed_operations?: string[];
  blocked_operations?: string[];
  allowed_memory_scopes?: string[];
  allowed_context_sections?: string[];
  use_shared_contract?: boolean;
  can_delegate_to_agents?: boolean;
  allowed_delegate_agent_ids?: string[];
  max_delegate_calls_per_turn?: number;
  delegate_context_policy?: string;
  model_profile?: {
    profile_id?: string;
    display_name?: string;
    provider?: string;
    model?: string;
    credential_ref?: string;
    max_output_tokens?: number | null;
    timeout_seconds?: number | null;
    long_output_timeout_seconds?: number | null;
    max_retries?: number | null;
    temperature?: number | null;
    thinking_mode?: string;
    reasoning_effort?: string;
    stream_policy?: Record<string, unknown>;
    fallback_profile_ref?: string;
    capability_tags?: string[];
    metadata?: Record<string, unknown>;
  };
  runtime_mode_catalog?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
};

type AgentDraftLike = {
  agent_id?: string;
  agent_name?: string;
  agent_category?: string;
  enabled?: boolean;
  default_projection_id?: string;
  default_soul_id?: string;
};

function dedupe(values: string[]) {
  return Array.from(new Set(values.map((item) => String(item || "").trim()).filter(Boolean)));
}

type CapabilityPool = "skill" | "tool" | "mcp";
type CapabilityStatus = "allowed" | "blocked" | "conflict" | "partial" | "neutral" | "unbound";

const POOL_META: Record<CapabilityPool, { title: string; summary: string }> = {
  skill: {
    title: "任务能力",
    summary: "模型可见的能力入口；这里只把它依赖的运行操作加入允许或阻断列表。",
  },
  tool: {
    title: "本地工具",
    summary: "本地工具映射到 operation，最终执行仍由 ResourcePolicy 与 OperationGate 放行。",
  },
  mcp: {
    title: "本地能力端点",
    summary: "检索、PDF、结构化数据等端点能力；这里不是第二套权限源。",
  },
};

function capabilityStatus(operationIds: string[], allowedSet: Set<string>, blockedSet: Set<string>): CapabilityStatus {
  if (!operationIds.length) return "unbound";
  const allowed = operationIds.filter((id) => allowedSet.has(id));
  const blocked = operationIds.filter((id) => blockedSet.has(id));
  if (allowed.length && blocked.length) return "conflict";
  if (blocked.length) return "blocked";
  if (allowed.length === operationIds.length) return "allowed";
  if (allowed.length) return "partial";
  return "neutral";
}

function statusLabel(status: CapabilityStatus) {
  const labels: Record<CapabilityStatus, string> = {
    allowed: "已允许",
    blocked: "已阻断",
    conflict: "冲突",
    neutral: "未配置",
    partial: "部分允许",
    unbound: "未绑定操作",
  };
  return labels[status];
}

function valueLabel(value: string, displayId: (value: unknown, fallback?: string) => string) {
  return displayId(value).replace(` · ${value}`, "");
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function numberOrNull(value: string) {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

type SearchRuntimeConfig = {
  runtime_mode: "single_search" | "deepsearch";
  search_sources: string[];
  web_provider: string;
  allow_fetch_url: boolean;
  allow_local_files: boolean;
  allow_memory_read: boolean;
  max_iterations: number;
  max_queries: number;
  max_fetches: number;
  max_sources: number;
  search_depth: "basic" | "advanced";
  include_raw_content: boolean;
  prefer_primary_sources: boolean;
  freshness_required_by_default: boolean;
  evidence_packet_required: boolean;
  stop_policy: string;
};

const DEFAULT_SEARCH_RUNTIME_CONFIG: SearchRuntimeConfig = {
  runtime_mode: "deepsearch",
  search_sources: ["web", "local_files", "rag", "memory"],
  web_provider: "tavily",
  allow_fetch_url: true,
  allow_local_files: true,
  allow_memory_read: true,
  max_iterations: 4,
  max_queries: 6,
  max_fetches: 8,
  max_sources: 12,
  search_depth: "advanced",
  include_raw_content: false,
  prefer_primary_sources: true,
  freshness_required_by_default: false,
  evidence_packet_required: true,
  stop_policy: "enough_evidence_or_budget_exhausted",
};

type GenericRuntimeConfig = {
  template_id: string;
  runtime_kind: string;
  runtime_mode: string;
  max_iterations: number;
  max_tool_calls: number;
  max_sources: number;
  evidence_packet_required: boolean;
  stop_policy: string;
  search?: SearchRuntimeConfig;
  context_compaction?: Record<string, unknown>;
};

const DEFAULT_GENERIC_RUNTIME_CONFIG: GenericRuntimeConfig = {
  template_id: "runtime.template.general_agent",
  runtime_kind: "agent_loop",
  runtime_mode: "standard",
  max_iterations: 4,
  max_tool_calls: 12,
  max_sources: 12,
  evidence_packet_required: false,
  stop_policy: "task_complete_or_budget_exhausted",
};

const DEEPSEARCH_RUNTIME_TEMPLATE: GenericRuntimeConfig = {
  ...DEFAULT_GENERIC_RUNTIME_CONFIG,
  template_id: "runtime.template.deepsearch",
  runtime_kind: "search_agent",
  runtime_mode: "deepsearch",
  max_iterations: DEFAULT_SEARCH_RUNTIME_CONFIG.max_iterations,
  max_tool_calls: DEFAULT_SEARCH_RUNTIME_CONFIG.max_queries + DEFAULT_SEARCH_RUNTIME_CONFIG.max_fetches,
  max_sources: DEFAULT_SEARCH_RUNTIME_CONFIG.max_sources,
  evidence_packet_required: true,
  stop_policy: DEFAULT_SEARCH_RUNTIME_CONFIG.stop_policy,
  search: DEFAULT_SEARCH_RUNTIME_CONFIG,
};

const CONTEXT_COMPACTOR_RUNTIME_TEMPLATE: GenericRuntimeConfig = {
  ...DEFAULT_GENERIC_RUNTIME_CONFIG,
  template_id: "runtime.template.context_compactor",
  runtime_kind: "context_compactor",
  runtime_mode: "llm_compaction",
  max_iterations: 1,
  max_tool_calls: 0,
  max_sources: 0,
  evidence_packet_required: false,
  stop_policy: "recovery_point_ready_or_fallback",
  context_compaction: {
    output_contract: "context_recovery_point",
    fallback: "deterministic",
    keep_last_messages: 6,
    max_summary_chars: 4000,
    trigger_pressure_levels: ["high", "critical"],
    actual_context_bytes_threshold: 120000,
  },
};

const BASE_SEARCH_RUNTIME_OPERATIONS = ["op.model_response", "op.web_search"];
const SEARCH_RUNTIME_FETCH_OPERATIONS = ["op.fetch_url"];
const SEARCH_RUNTIME_LOCAL_OPERATIONS = ["op.search_files", "op.search_text", "op.read_file"];
const SEARCH_RUNTIME_RAG_OPERATIONS = ["op.mcp_retrieval"];
const SEARCH_RUNTIME_MEMORY_OPERATIONS = ["op.memory_read"];

function searchRuntimeConfigFrom(value: unknown): SearchRuntimeConfig {
  const raw = asRecord(value);
  const runtimeMode = String(raw.runtime_mode || DEFAULT_SEARCH_RUNTIME_CONFIG.runtime_mode);
  const searchDepth = String(raw.search_depth || DEFAULT_SEARCH_RUNTIME_CONFIG.search_depth);
  return {
    ...DEFAULT_SEARCH_RUNTIME_CONFIG,
    ...raw,
    runtime_mode: runtimeMode === "single_search" ? "single_search" : "deepsearch",
    search_sources: dedupe(Array.isArray(raw.search_sources) ? raw.search_sources.map(String) : DEFAULT_SEARCH_RUNTIME_CONFIG.search_sources),
    web_provider: String(raw.web_provider || DEFAULT_SEARCH_RUNTIME_CONFIG.web_provider),
    allow_fetch_url: Boolean(raw.allow_fetch_url ?? DEFAULT_SEARCH_RUNTIME_CONFIG.allow_fetch_url),
    allow_local_files: Boolean(raw.allow_local_files ?? DEFAULT_SEARCH_RUNTIME_CONFIG.allow_local_files),
    allow_memory_read: Boolean(raw.allow_memory_read ?? DEFAULT_SEARCH_RUNTIME_CONFIG.allow_memory_read),
    max_iterations: Math.max(1, Math.min(12, Number(raw.max_iterations ?? DEFAULT_SEARCH_RUNTIME_CONFIG.max_iterations))),
    max_queries: Math.max(1, Math.min(30, Number(raw.max_queries ?? DEFAULT_SEARCH_RUNTIME_CONFIG.max_queries))),
    max_fetches: Math.max(0, Math.min(40, Number(raw.max_fetches ?? DEFAULT_SEARCH_RUNTIME_CONFIG.max_fetches))),
    max_sources: Math.max(1, Math.min(60, Number(raw.max_sources ?? DEFAULT_SEARCH_RUNTIME_CONFIG.max_sources))),
    search_depth: searchDepth === "basic" ? "basic" : "advanced",
    include_raw_content: Boolean(raw.include_raw_content ?? DEFAULT_SEARCH_RUNTIME_CONFIG.include_raw_content),
    prefer_primary_sources: Boolean(raw.prefer_primary_sources ?? DEFAULT_SEARCH_RUNTIME_CONFIG.prefer_primary_sources),
    freshness_required_by_default: Boolean(raw.freshness_required_by_default ?? DEFAULT_SEARCH_RUNTIME_CONFIG.freshness_required_by_default),
    evidence_packet_required: Boolean(raw.evidence_packet_required ?? DEFAULT_SEARCH_RUNTIME_CONFIG.evidence_packet_required),
    stop_policy: String(raw.stop_policy || DEFAULT_SEARCH_RUNTIME_CONFIG.stop_policy),
  };
}

function runtimeConfigFrom(metadata: Record<string, unknown> | undefined): GenericRuntimeConfig {
  const raw = asRecord(metadata?.runtime_config);
  const nestedSearch = raw.search ? searchRuntimeConfigFrom(raw.search) : undefined;
  const derivedToolCallBudget = (nestedSearch?.max_queries ?? 0) + (nestedSearch?.max_fetches ?? 0);
  return {
    ...DEFAULT_GENERIC_RUNTIME_CONFIG,
    ...raw,
    template_id: String(raw.template_id || (nestedSearch ? DEEPSEARCH_RUNTIME_TEMPLATE.template_id : DEFAULT_GENERIC_RUNTIME_CONFIG.template_id)),
    runtime_kind: String(raw.runtime_kind || (nestedSearch ? "search_agent" : DEFAULT_GENERIC_RUNTIME_CONFIG.runtime_kind)),
    runtime_mode: String(raw.runtime_mode || (nestedSearch ? "deepsearch" : DEFAULT_GENERIC_RUNTIME_CONFIG.runtime_mode)),
    max_iterations: Math.max(1, Math.min(30, Number(raw.max_iterations ?? nestedSearch?.max_iterations ?? DEFAULT_GENERIC_RUNTIME_CONFIG.max_iterations))),
    max_tool_calls: Math.max(1, Math.min(100, Number(raw.max_tool_calls ?? (derivedToolCallBudget || DEFAULT_GENERIC_RUNTIME_CONFIG.max_tool_calls)))),
    max_sources: Math.max(1, Math.min(100, Number(raw.max_sources ?? nestedSearch?.max_sources ?? DEFAULT_GENERIC_RUNTIME_CONFIG.max_sources))),
    evidence_packet_required: Boolean(raw.evidence_packet_required ?? nestedSearch?.evidence_packet_required ?? DEFAULT_GENERIC_RUNTIME_CONFIG.evidence_packet_required),
    stop_policy: String(raw.stop_policy || nestedSearch?.stop_policy || DEFAULT_GENERIC_RUNTIME_CONFIG.stop_policy),
    ...(nestedSearch ? { search: nestedSearch } : {}),
  };
}

function operationsForSearchRuntime(config: SearchRuntimeConfig) {
  const sources = new Set(config.search_sources.length ? config.search_sources : ["web"]);
  return dedupe([
    "op.model_response",
    ...(sources.has("web") ? ["op.web_search"] : []),
    ...(sources.has("web") && config.allow_fetch_url && config.max_fetches > 0 ? SEARCH_RUNTIME_FETCH_OPERATIONS : []),
    ...(sources.has("local_files") || config.allow_local_files ? SEARCH_RUNTIME_LOCAL_OPERATIONS : []),
    ...(sources.has("rag") ? SEARCH_RUNTIME_RAG_OPERATIONS : []),
    ...(sources.has("memory") || config.allow_memory_read ? SEARCH_RUNTIME_MEMORY_OPERATIONS : []),
  ]);
}

function runtimeTemplateRuntimeKind(templateId: string) {
  if (templateId === DEEPSEARCH_RUNTIME_TEMPLATE.template_id) return DEEPSEARCH_RUNTIME_TEMPLATE.runtime_kind;
  if (templateId === CONTEXT_COMPACTOR_RUNTIME_TEMPLATE.template_id) return CONTEXT_COMPACTOR_RUNTIME_TEMPLATE.runtime_kind;
  return DEFAULT_GENERIC_RUNTIME_CONFIG.runtime_kind;
}

function runtimeTemplateModes(templateId: string) {
  if (templateId === DEEPSEARCH_RUNTIME_TEMPLATE.template_id) return ["deepsearch", "single_search"];
  if (templateId === CONTEXT_COMPACTOR_RUNTIME_TEMPLATE.template_id) return ["llm_compaction", "deterministic_fallback"];
  return ["standard"];
}

function validRuntimeModeForTemplate(templateId: string, runtimeMode: string) {
  const modes = runtimeTemplateModes(templateId);
  return modes.includes(runtimeMode) ? runtimeMode : modes[0];
}

function runtimeTemplateIssue(config: GenericRuntimeConfig) {
  const expectedKind = runtimeTemplateRuntimeKind(config.template_id);
  if (config.runtime_kind !== expectedKind) return `模板要求 Runtime Kind 为 ${expectedKind}`;
  if (!runtimeTemplateModes(config.template_id).includes(config.runtime_mode)) return `模板不支持 Runtime Mode ${config.runtime_mode}`;
  return "";
}

function nextSearchSources(config: SearchRuntimeConfig) {
  return dedupe([
    "web",
    ...(config.allow_local_files ? ["local_files"] : []),
    ...(config.search_sources.includes("rag") ? ["rag"] : []),
    ...(config.allow_memory_read ? ["memory"] : []),
  ]);
}

type PendingRuntimeModeChange = {
  mode: string;
  checked: boolean;
} | null;

function runtimeModeLabel(mode: RuntimeModeConfig) {
  return mode.label || mode.mode;
}

function runtimeModeConfigSummary(mode: RuntimeModeConfig) {
  if (mode.mode === "custom") return "自定义行为配置";
  return mode.interaction_mode || mode.recipe_id || "-";
}

function runtimeModeDefaultLabel(mode: RuntimeModeConfig, defaultMode: string) {
  if (mode.mode === "custom") return "手工";
  return defaultMode === mode.mode ? "默认" : "设默认";
}

export function OrchestrationModelRuntimeWorkbench({
  runtimeDraft,
  patchRuntimeDraft,
  providerCatalog,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  providerCatalog?: Record<string, unknown>;
}) {
  const modelProfile = runtimeDraft.model_profile ?? {};
  const catalog = asRecord(providerCatalog);
  const providers = asRecord(catalog.providers);
  const providerEntries = Object.entries(providers).map(([provider, payload]) => ({ provider, payload: asRecord(payload) }));
  const selectedProvider = String(modelProfile.provider || catalog.default_provider || "deepseek");
  const selectedProviderPayload = asRecord(providers[selectedProvider]);
  const providerModels = (Array.isArray(selectedProviderPayload.model_presets)
    ? selectedProviderPayload.model_presets
    : [selectedProviderPayload.default_model]).map((item) => String(item || "").trim()).filter(Boolean);
  const providerEndpoint = String(
    selectedProviderPayload.active
      ? (catalog.default_base_url || selectedProviderPayload.default_base_url || "")
      : (selectedProviderPayload.default_base_url || ""),
  );
  const capabilityText = dedupe(modelProfile.capability_tags ?? []).join(", ");
  const credentialRef = String(modelProfile.credential_ref || selectedProviderPayload.credential_ref || `provider:${selectedProvider}:primary`);

  function patchModelProfile(patch: Record<string, unknown>) {
    patchRuntimeDraft({
      model_profile: {
        ...modelProfile,
        ...patch,
      },
    });
  }

  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header>
          <strong>模型运行档案</strong>
          <OrchestrationBadge tone={modelProfile.provider || modelProfile.model ? "ok" : "neutral"}>
            {modelProfile.provider || modelProfile.model ? "Agent 覆盖" : "继承系统默认"}
          </OrchestrationBadge>
        </header>
        <div className="orchestration-identity-note">
          <span>模型配置属于 AgentRuntimeProfile。</span>
          <strong>任务图节点只声明模型需求；API Key 只通过 credential_ref 解析。</strong>
        </div>
        <div className="boundary-form">
          <OrchestrationField label="档案标识">
            <input value={modelProfile.profile_id || ""} onChange={(event) => patchModelProfile({ profile_id: event.target.value })} placeholder="例如 writer_long_output" />
          </OrchestrationField>
          <OrchestrationField label="显示名">
            <input value={modelProfile.display_name || ""} onChange={(event) => patchModelProfile({ display_name: event.target.value })} placeholder="长输出写作模型" />
          </OrchestrationField>
          <OrchestrationField label="Provider">
            <select
              value={selectedProvider}
              onChange={(event) => {
                const nextProvider = event.target.value;
                const nextProviderPayload = asRecord(providers[nextProvider]);
                patchModelProfile({
                  provider: nextProvider,
                  model: String(nextProviderPayload.default_model || ""),
                  credential_ref: String(nextProviderPayload.credential_ref || `provider:${nextProvider}:primary`),
                });
              }}
            >
              {providerEntries.length ? providerEntries.map(({ provider, payload }) => (
                <option key={provider} value={provider}>{String(payload.display_name || provider)}</option>
              )) : <option value="deepseek">DeepSeek</option>}
            </select>
          </OrchestrationField>
          <OrchestrationField label="模型">
            <input
              list="orchestration-model-runtime-presets"
              value={modelProfile.model || ""}
              onChange={(event) => patchModelProfile({ model: event.target.value })}
              placeholder={String(selectedProviderPayload.default_model || "继承系统默认")}
            />
            <datalist id="orchestration-model-runtime-presets">
              {providerModels.map((model) => <option key={model} value={model} />)}
            </datalist>
          </OrchestrationField>
          <OrchestrationField label="凭据引用">
            <input value={credentialRef} onChange={(event) => patchModelProfile({ credential_ref: event.target.value })} />
          </OrchestrationField>
          <OrchestrationField label="最大输出 tokens">
            <input min={1} type="number" value={modelProfile.max_output_tokens ?? ""} onChange={(event) => patchModelProfile({ max_output_tokens: numberOrNull(event.target.value) })} placeholder="继承系统默认" />
          </OrchestrationField>
          <OrchestrationField label="普通超时秒">
            <input min={1} type="number" value={modelProfile.timeout_seconds ?? ""} onChange={(event) => patchModelProfile({ timeout_seconds: numberOrNull(event.target.value) })} placeholder="继承系统默认" />
          </OrchestrationField>
          <OrchestrationField label="长输出超时秒">
            <input min={1} type="number" value={modelProfile.long_output_timeout_seconds ?? ""} onChange={(event) => patchModelProfile({ long_output_timeout_seconds: numberOrNull(event.target.value) })} placeholder="继承系统默认" />
          </OrchestrationField>
          <OrchestrationField label="最大重试">
            <input min={0} type="number" value={modelProfile.max_retries ?? ""} onChange={(event) => patchModelProfile({ max_retries: numberOrNull(event.target.value) })} placeholder="继承系统默认" />
          </OrchestrationField>
          <OrchestrationField label="温度">
            <input min={0} max={2} step={0.1} type="number" value={modelProfile.temperature ?? ""} onChange={(event) => patchModelProfile({ temperature: numberOrNull(event.target.value) })} placeholder="0" />
          </OrchestrationField>
          <OrchestrationField label="Thinking 模式">
            <select value={modelProfile.thinking_mode || ""} onChange={(event) => patchModelProfile({ thinking_mode: event.target.value })}>
              <option value="">继承系统默认</option>
              <option value="disabled">disabled</option>
              <option value="enabled">enabled</option>
            </select>
          </OrchestrationField>
          <OrchestrationField label="推理强度">
            <select value={modelProfile.reasoning_effort || ""} onChange={(event) => patchModelProfile({ reasoning_effort: event.target.value })}>
              <option value="">继承系统默认</option>
              <option value="high">high</option>
              <option value="max">max</option>
            </select>
          </OrchestrationField>
          <OrchestrationField label="能力标签" wide>
            <input
              value={capabilityText}
              onChange={(event) => patchModelProfile({ capability_tags: dedupe(event.target.value.split(/[,，\n]/)) })}
              placeholder="long_output, reasoning, creative_generation"
            />
          </OrchestrationField>
        </div>
      </div>
      <aside className="boundary-card">
        <header><strong>解析预览</strong></header>
        <div className="boundary-readiness-list boundary-readiness-list--grid">
          <OrchestrationReadinessCard label="Provider" ready={Boolean(modelProfile.provider)} value={modelProfile.provider || String(catalog.default_provider || "系统默认")} />
          <OrchestrationReadinessCard label="模型" ready={Boolean(modelProfile.model)} value={modelProfile.model || String(catalog.default_model || "系统默认")} />
          <OrchestrationReadinessCard label="凭据" ready={Boolean(selectedProviderPayload.credential_configured) || selectedProvider === "ollama"} value={credentialRef} />
          <OrchestrationReadinessCard label="输出上限" ready={Boolean(modelProfile.max_output_tokens)} value={modelProfile.max_output_tokens ? `${modelProfile.max_output_tokens}` : "继承系统默认"} />
        </div>
        <div className="boundary-kv">
          <p><span>适配器</span><strong>{String(selectedProviderPayload.adapter || "openai_compatible")}</strong></p>
          <p><span>Base URL 来源</span><strong>{providerEndpoint || "系统配置 / Provider 预设"}</strong></p>
          <p><span>推荐默认</span><strong>{String(catalog.recommended_provider || "deepseek")}</strong></p>
          <p><span>密钥策略</span><strong><KeyRound size={13} /> credential_ref only</strong></p>
          <p><span>作用范围</span><strong><BrainCircuit size={13} /> 当前 Agent 执行调用</strong></p>
        </div>
      </aside>
    </section>
  );
}

export function OrchestrationRuntimePermissionWorkbench({
  runtimeDraft,
  patchRuntimeDraft,
  approvalPolicies,
  tracePolicies,
  approvalPolicyOptions,
  tracePolicyOptions,
  displayId,
  runtimeModeSummary,
  capabilityItems,
  operationOptions,
  operationOptionItems,
  overlapOps,
  overlapSummary,
  allowedOpsCount,
  blockedOpsCount,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  approvalPolicies: string[];
  tracePolicies: string[];
  approvalPolicyOptions: OrchestrationOption[];
  tracePolicyOptions: OrchestrationOption[];
  displayId: (value: unknown, fallback?: string) => string;
  runtimeModeSummary: string;
  capabilityItems: OrchestrationCapabilityItem[];
  operationOptions: string[];
  operationOptionItems: OrchestrationOption[];
  overlapOps: string[];
  overlapSummary: string;
  allowedOpsCount: number;
  blockedOpsCount: number;
}) {
  const runtimeModeCatalog = useMemo(
    () => runtimeModeCatalogFrom(runtimeDraft.runtime_mode_catalog),
    [runtimeDraft.runtime_mode_catalog],
  );
  const enabledModes = normalizeRuntimeModes(runtimeDraft.enabled_runtime_modes, runtimeModeCatalog);
  const defaultMode = normalizeDefaultRuntimeMode(runtimeDraft.default_runtime_mode, enabledModes);
  const enabledModeSet = useMemo(() => new Set(enabledModes), [enabledModes]);
  const [pendingModeChange, setPendingModeChange] = useState<PendingRuntimeModeChange>(null);

  function applyModes(nextModes: string[], nextDefaultMode = defaultMode) {
    const normalizedModes = normalizeRuntimeModes(nextModes, runtimeModeCatalog);
    const normalizedDefault = normalizeDefaultRuntimeMode(nextDefaultMode, normalizedModes);
    patchRuntimeDraft({
      enabled_runtime_modes: normalizedModes,
      default_runtime_mode: normalizedDefault,
    });
  }

  function confirmPendingModeChange() {
    if (!pendingModeChange) return;
    const { mode, checked } = pendingModeChange;
    const nextModes = checked
      ? dedupe([...enabledModes, mode])
      : enabledModes.filter((item) => item !== mode);
    const nonEmptyModes = nextModes.length ? nextModes : ["custom"];
    const nextDefaultMode = checked
      ? mode === "custom"
        ? defaultMode
        : mode
      : defaultMode === mode
        ? nonEmptyModes[0] || "custom"
        : defaultMode;
    applyModes(nonEmptyModes, nextDefaultMode);
    setPendingModeChange(null);
  }

  function setDefaultMode(mode: string) {
    if (mode === "custom") return;
    if (!enabledModeSet.has(mode)) return;
    patchRuntimeDraft({ default_runtime_mode: mode });
  }

  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header>
          <strong>运行权限档案</strong>
          <OrchestrationBadge>{runtimeDraft.agent_profile_id || "草稿"}</OrchestrationBadge>
        </header>
        <div className="orchestration-identity-note">
          <span>权限事实源：AgentRuntimeProfile。</span>
          <strong>工具可见性只来自 Agent 的 operation 权限；环境和模式不授予额外工具权限。</strong>
        </div>
        <div className="boundary-form">
          <OrchestrationField label="运行档案标识">
            <input value={runtimeDraft.agent_profile_id || ""} onChange={(event) => patchRuntimeDraft({ agent_profile_id: event.target.value })} />
          </OrchestrationField>
          <OrchestrationField label="审批策略">
            <select value={runtimeDraft.approval_policy} onChange={(event) => patchRuntimeDraft({ approval_policy: event.target.value })}>
              {(approvalPolicyOptions.length ? approvalPolicyOptions : approvalPolicies.map((item) => ({ id: item, value: item, label: displayId(item) }))).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </OrchestrationField>
          <OrchestrationField label="追踪策略">
            <select value={runtimeDraft.trace_policy} onChange={(event) => patchRuntimeDraft({ trace_policy: event.target.value })}>
              {(tracePolicyOptions.length ? tracePolicyOptions : tracePolicies.map((item) => ({ id: item, value: item, label: displayId(item) }))).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </OrchestrationField>
          <OrchestrationField label="生命周期">
            <input value={runtimeDraft.lifecycle_policy || ""} onChange={(event) => patchRuntimeDraft({ lifecycle_policy: event.target.value })} />
          </OrchestrationField>
        </div>
        <div className="orchestration-runtime-mode-panel">
          <div className="orchestration-runtime-mode-panel__head">
            <span>运行模式配置</span>
            <small>{enabledModes.length} 项 / 默认 {runtimeModeCatalog.find((mode) => mode.mode === defaultMode)?.label || defaultMode}</small>
          </div>
          <div className="orchestration-runtime-mode-grid">
            {runtimeModeCatalog.map((mode) => {
              const active = enabledModeSet.has(mode.mode);
              return (
                <div className={active ? "orchestration-runtime-mode-row orchestration-runtime-mode-row--active" : "orchestration-runtime-mode-row"} key={mode.mode}>
                  <button
                    aria-pressed={active}
                    onClick={() => setPendingModeChange({ mode: mode.mode, checked: !active })}
                    type="button"
                  >
                    <span>{runtimeModeLabel(mode)}</span>
                    <strong>{runtimeModeConfigSummary(mode)}</strong>
                  </button>
                  <button
                    className={defaultMode === mode.mode ? "orchestration-runtime-mode-default orchestration-runtime-mode-default--active" : "orchestration-runtime-mode-default"}
                    disabled={!active || mode.mode === "custom"}
                    onClick={() => setDefaultMode(mode.mode)}
                    type="button"
                  >
                    {runtimeModeDefaultLabel(mode, defaultMode)}
                  </button>
                </div>
              );
            })}
          </div>
          {pendingModeChange ? (
            <div className="orchestration-runtime-mode-confirm">
              <span>
                确认{pendingModeChange.checked ? "启用" : "关闭"}
                {runtimeModeCatalog.find((mode) => mode.mode === pendingModeChange.mode)?.label || pendingModeChange.mode}
                ？
              </span>
              <button onClick={confirmPendingModeChange} type="button">确认</button>
              <button onClick={() => setPendingModeChange(null)} type="button">取消</button>
            </div>
          ) : null}
        </div>
      </div>
      <aside className="boundary-card">
        <header><strong>运行权限摘要</strong></header>
        <div className="boundary-kv">
          <p><span>运行模式</span><strong>{displayModeSummary(enabledModes, runtimeModeCatalog)}</strong></p>
          <p><span>模式摘要</span><strong>{runtimeModeSummary}</strong></p>
          <p><span>允许操作</span><strong>{allowedOpsCount}</strong></p>
          <p><span>阻断操作</span><strong>{blockedOpsCount}</strong></p>
          <p><span>冲突</span><strong>{overlapSummary}</strong></p>
        </div>
      </aside>

      <OrchestrationOperationAuthorizationWorkbench
        allowedOpsCount={allowedOpsCount}
        blockedOpsCount={blockedOpsCount}
        capabilityItems={capabilityItems}
        displayId={displayId}
        operationOptionItems={operationOptionItems}
        operationOptions={operationOptions}
        overlapOps={overlapOps}
        overlapSummary={overlapSummary}
        patchRuntimeDraft={patchRuntimeDraft}
        runtimeDraft={runtimeDraft}
      />
    </section>
  );
}

function displayModeSummary(enabledModes: string[], catalog: RuntimeModeConfig[]) {
  const labels = new Map(catalog.map((mode) => [mode.mode, runtimeModeLabel(mode)]));
  return enabledModes.length ? enabledModes.map((mode) => labels.get(mode) || mode).join(" / ") : "未配置";
}

export function OrchestrationOperationAuthorizationWorkbench({
  runtimeDraft,
  patchRuntimeDraft,
  overlapOps,
  capabilityItems,
  operationOptions,
  operationOptionItems,
  displayId,
  allowedOpsCount,
  blockedOpsCount,
  overlapSummary,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  overlapOps: string[];
  capabilityItems: OrchestrationCapabilityItem[];
  operationOptions: string[];
  operationOptionItems: OrchestrationOption[];
  displayId: (value: unknown, fallback?: string) => string;
  allowedOpsCount: number;
  blockedOpsCount: number;
  overlapSummary: string;
}) {
  const allowedOps = dedupe(runtimeDraft.allowed_operations ?? []);
  const blockedOps = dedupe(runtimeDraft.blocked_operations ?? []);
  const allowedSet = useMemo(() => new Set(allowedOps), [allowedOps]);
  const blockedSet = useMemo(() => new Set(blockedOps), [blockedOps]);
  const capabilityRows = useMemo(() => capabilityItems, [capabilityItems]);
  const [selectedCapabilityId, setSelectedCapabilityId] = useState("");
  const selectedCapability = capabilityRows.find((item) => item.capability_id === selectedCapabilityId) ?? capabilityRows[0] ?? null;

  useEffect(() => {
    if (!capabilityRows.length) {
      setSelectedCapabilityId("");
      return;
    }
    setSelectedCapabilityId((current) => capabilityRows.some((item) => item.capability_id === current) ? current : capabilityRows[0].capability_id);
  }, [capabilityRows]);

  function applyCapability(operationIds: string[], mode: "allow" | "block") {
    const ids = dedupe(operationIds);
    if (!ids.length) return;
    if (mode === "allow") {
      patchRuntimeDraft({
        allowed_operations: dedupe([...allowedOps, ...ids]),
        blocked_operations: dedupe(blockedOps.filter((item) => !ids.includes(item))),
      });
      return;
    }
    patchRuntimeDraft({
      allowed_operations: dedupe(allowedOps.filter((item) => !ids.includes(item))),
      blocked_operations: dedupe([...blockedOps, ...ids]),
    });
  }

  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide orchestration-permission-workbench">
      <div className="boundary-card orchestration-permission-matrix-shell">
        <header>
          <strong>能力授权矩阵</strong>
          <OrchestrationBadge tone={overlapOps.length ? "danger" : "ok"}>{overlapOps.length ? "冲突" : "映射清晰"}</OrchestrationBadge>
        </header>
        <div className="orchestration-permission-summary" aria-label="授权概况">
          <span>允许 <b>{allowedOpsCount}</b></span>
          <span>阻断 <b>{blockedOpsCount}</b></span>
          <span>冲突 <b>{overlapSummary}</b></span>
        </div>
        {overlapOps.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{overlapOps.join(" / ")} 同时出现在允许和阻断列表。</div> : null}
        {!capabilityRows.length ? <div className="boundary-notice"><Info size={16} />能力目录尚未就绪，当前没有可展示的授权能力项。</div> : null}
        <div className="orchestration-permission-matrix" role="table" aria-label="能力授权矩阵">
          <div className="orchestration-permission-matrix__head" role="row">
            <span role="columnheader">类型</span>
            <span role="columnheader">能力</span>
            <span role="columnheader">来源</span>
            <span role="columnheader">操作</span>
            <span role="columnheader">风险</span>
            <span role="columnheader">状态</span>
            <span role="columnheader">动作</span>
          </div>
          {!capabilityRows.length ? (
            <div className="orchestration-permission-row orchestration-permission-row--empty" role="row">
              <span role="cell">空</span>
              <span role="cell">能力准入项未加载</span>
              <span role="cell">等待能力目录</span>
              <span role="cell">0 项</span>
              <span role="cell">无</span>
              <span role="cell">不可配置</span>
              <span role="cell">-</span>
            </div>
          ) : null}
          {capabilityRows.map((capability) => {
            const status = capabilityStatus(capability.operation_ids, allowedSet, blockedSet);
            const active = selectedCapability?.capability_id === capability.capability_id;
            const pool = capability.capability_kind === "operation" ? "tool" : capability.capability_kind;
            const poolLabel = pool === "skill" || pool === "tool" || pool === "mcp" ? POOL_META[pool].title : capability.capability_kind;
            return (
              <div
                aria-selected={active}
                className={[
                  "orchestration-permission-row",
                  `orchestration-permission-row--${status}`,
                  active ? "orchestration-permission-row--active" : "",
                ].filter(Boolean).join(" ")}
                key={capability.capability_id}
                onClick={() => setSelectedCapabilityId(capability.capability_id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedCapabilityId(capability.capability_id);
                  }
                }}
                role="row"
                tabIndex={0}
              >
                <span className="orchestration-permission-row__type" role="cell">{poolLabel}</span>
                <span className="orchestration-permission-row__name" role="cell"><strong>{capability.title}</strong></span>
                <span role="cell">{capability.source_label || capability.source_detail}</span>
                <span role="cell">{capability.operation_ids.length ? `${capability.operation_ids.length} 项` : "未绑定"}</span>
                <span role="cell">{capability.risk_label || "未声明"}</span>
                <span className="orchestration-permission-row__status" role="cell"><em>{statusLabel(status)}</em></span>
                <span className="orchestration-permission-row__actions" role="cell">
                  <button
                    aria-label={`允许 ${capability.title}`}
                    className={status === "allowed" ? "is-active" : ""}
                    disabled={!capability.operation_ids.length}
                    onClick={(event) => {
                      event.stopPropagation();
                      applyCapability(capability.operation_ids, "allow");
                    }}
                    type="button"
                  >
                    <CheckCircle2 size={13} />允许
                  </button>
                  <button
                    aria-label={`阻断 ${capability.title}`}
                    className={status === "blocked" ? "is-danger-active" : ""}
                    disabled={!capability.operation_ids.length}
                    onClick={(event) => {
                      event.stopPropagation();
                      applyCapability(capability.operation_ids, "block");
                    }}
                    type="button"
                  >
                    <XCircle size={13} />阻断
                  </button>
                </span>
              </div>
            );
          })}
        </div>
        <details className="orchestration-permission-raw">
          <summary>运行操作明细</summary>
          <OrchestrationOptionSelection
            displayId={displayId}
            fallbackOptions={operationOptions}
            label="允许操作"
            onChange={(values) => patchRuntimeDraft({ allowed_operations: dedupe(values) })}
            options={operationOptionItems}
            selectedValues={allowedOps}
          />
          <OrchestrationOptionSelection
            displayId={displayId}
            fallbackOptions={operationOptions}
            label="阻断操作"
            onChange={(values) => patchRuntimeDraft({ blocked_operations: dedupe(values) })}
            options={operationOptionItems}
            selectedValues={blockedOps}
          />
        </details>
      </div>
      <aside className="boundary-card orchestration-permission-inspector">
        <header><strong>能力注册说明</strong>{selectedCapability ? <OrchestrationBadge tone={selectedCapability.risk_tone === "danger" ? "danger" : selectedCapability.risk_tone === "warn" ? "warn" : selectedCapability.risk_tone === "ok" ? "ok" : "neutral"}>{statusLabel(capabilityStatus(selectedCapability.operation_ids, allowedSet, blockedSet))}</OrchestrationBadge> : null}</header>
        {selectedCapability ? (
          <>
            <div className="orchestration-permission-inspector__hero">
              <span>{selectedCapability.source_label}</span>
              <h4>{selectedCapability.title}</h4>
              <p>{selectedCapability.description}</p>
            </div>
            <div className="boundary-kv">
              <p><span>来源</span><strong>{selectedCapability.source_detail}</strong></p>
              <p><span>运行操作映射</span><strong>{selectedCapability.operation_ids.length ? selectedCapability.operation_ids.map((item) => valueLabel(item, displayId)).join(" / ") : "未绑定运行操作"}</strong></p>
              <p><span>风险</span><strong>{selectedCapability.risk_label}</strong></p>
              <p><span>允许</span><strong>{allowedOpsCount}</strong></p>
              <p><span>阻断</span><strong>{blockedOpsCount}</strong></p>
              <p><span>冲突</span><strong>{overlapSummary}</strong></p>
            </div>
            <section className="orchestration-permission-detail-block">
              <strong>风险与限制</strong>
              <div>
                {selectedCapability.risk_items.length ? selectedCapability.risk_items.map((item, index) => <span key={`${item}-${index}`}>{item}</span>) : <span>注册信息不足</span>}
              </div>
            </section>
            <section className="orchestration-permission-detail-block">
              <strong>能力注册元数据</strong>
              <div>
                {selectedCapability.metadata.map((item) => <p key={item.label}><span>{item.label}</span><b>{item.value}</b></p>)}
              </div>
            </section>
            <div className="orchestration-permission-inspector__actions">
              <button disabled={!selectedCapability.operation_ids.length} onClick={() => applyCapability(selectedCapability.operation_ids, "allow")} type="button"><CheckCircle2 size={14} />加入允许操作</button>
              <button disabled={!selectedCapability.operation_ids.length} onClick={() => applyCapability(selectedCapability.operation_ids, "block")} type="button"><XCircle size={14} />加入阻断操作</button>
            </div>
          </>
        ) : <div className="boundary-empty">请选择一个能力行查看来源、风险和说明。</div>}
      </aside>
    </section>
  );
}

export function OrchestrationContextMemoryWorkbench({
  runtimeDraft,
  patchRuntimeDraft,
  memoryScopeOptions,
  contextSectionOptions,
  memoryScopeOptionItems,
  contextSectionOptionItems,
  displayId,
  memorySummary,
  contextSummary,
  sharedContractEnabled,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  memoryScopeOptions: string[];
  contextSectionOptions: string[];
  memoryScopeOptionItems: OrchestrationOption[];
  contextSectionOptionItems: OrchestrationOption[];
  displayId: (value: unknown, fallback?: string) => string;
  memorySummary: string;
  contextSummary: string;
  sharedContractEnabled: boolean;
}) {
  const selectedMemoryScopes = dedupe(runtimeDraft.allowed_memory_scopes ?? []);
  const selectedContextSections = dedupe(runtimeDraft.allowed_context_sections ?? []);
  const selectedMemoryScopeSet = new Set(selectedMemoryScopes);
  const selectedContextSectionSet = new Set(selectedContextSections);
  const hasConversationReadonly = selectedMemoryScopeSet.has("conversation_readonly");
  const hasStateReadonly = selectedMemoryScopeSet.has("state_readonly");
  const hasSessionMaintenance = selectedMemoryScopes.includes("session_memory_write_candidate");
  const hasDurableCandidate = selectedMemoryScopes.includes("durable_memory_write_candidate") || selectedMemoryScopes.includes("long_term_candidate");
  const hasRuntimeView = selectedContextSections.includes("memory_runtime_view");

  function mergeContextSections(values: string[]) {
    return dedupe([...selectedContextSections, ...values]);
  }

  function applyMainMemoryBoundary() {
    patchRuntimeDraft({
      allowed_memory_scopes: dedupe(["conversation_readonly", "state_readonly", "long_term_candidate"]),
      allowed_context_sections: mergeContextSections(["memory_runtime_view"]),
    });
  }

  function applyMemoryAgentBoundary() {
    patchRuntimeDraft({
      allowed_memory_scopes: dedupe([
        "conversation_readonly",
        "state_readonly",
        "long_term_candidate",
        "session_memory_write_candidate",
        "durable_memory_write_candidate",
      ]),
      allowed_context_sections: mergeContextSections(["task", "runtime_trace", "memory_runtime_view", "prompt_manifest", "runtime_contracts"]),
    });
  }

  return (
    <section className="orchestration-context-workbench">
      <div className="boundary-card orchestration-context-config-card">
        <header><strong>上下文与记忆边界</strong><OrchestrationBadge>AgentRuntimeProfile</OrchestrationBadge></header>
        <div className="orchestration-identity-note">
          <span>这里只定义 Agent 可接收的上下文段和记忆范围。</span>
          <strong>正式记忆写入仍由记忆系统和记忆管理 Agent 接管。</strong>
        </div>
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={memoryScopeOptions}
          label="可接收记忆范围"
          onChange={(values) => patchRuntimeDraft({ allowed_memory_scopes: dedupe(values) })}
          options={memoryScopeOptionItems}
          selectedValues={selectedMemoryScopes}
        />
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={contextSectionOptions}
          label="可接收上下文段"
          onChange={(values) => patchRuntimeDraft({ allowed_context_sections: dedupe(values) })}
          options={contextSectionOptionItems}
          selectedValues={selectedContextSections}
        />
        <label className="boundary-check">
          <input
            checked={Boolean(runtimeDraft.use_shared_contract ?? true)}
            onChange={(event) => patchRuntimeDraft({ use_shared_contract: event.target.checked })}
            type="checkbox"
          />
          采用共同契约
        </label>
      </div>

      <section className="boundary-card orchestration-memory-interface-card">
        <header>
          <strong>记忆边界预设</strong>
          <OrchestrationBadge tone={hasRuntimeView ? "ok" : "warn"}>{hasRuntimeView ? "受控视图" : "未接入视图"}</OrchestrationBadge>
        </header>
        <div className="boundary-readiness-list boundary-readiness-list--grid orchestration-memory-readiness-grid">
          <OrchestrationReadinessCard
            label="Session Memory"
            ready={hasSessionMaintenance}
            value={hasSessionMaintenance ? "候选写入" : "不可写"}
          />
          <OrchestrationReadinessCard
            label="Durable Memory"
            ready={hasDurableCandidate}
            value={hasDurableCandidate ? "候选写入" : "不可写"}
          />
          <OrchestrationReadinessCard
            label="Runtime View"
            ready={hasRuntimeView}
            value={hasRuntimeView ? "只读上下文" : "未暴露"}
          />
        </div>
        <div className="orchestration-memory-boundary">
          <div className="orchestration-memory-boundary__actions">
            <button onClick={applyMainMemoryBoundary} type="button"><ShieldCheck size={14} />主链只读边界</button>
            <button onClick={applyMemoryAgentBoundary} type="button"><Database size={14} />记忆管理边界</button>
          </div>
          <div className="orchestration-memory-lane-grid">
            <article className="orchestration-memory-lane">
              <span><GitBranch size={15} />State Memory</span>
              <strong>{hasStateReadonly && hasRuntimeView ? "状态只读注入" : "未形成完整状态视图"}</strong>
              <small>连接 process_state.json、ContextSlots、恢复候选与活动状态上下文。</small>
            </article>
            <article className="orchestration-memory-lane">
              <span><Database size={15} />Session Memory</span>
              <strong>{hasSessionMaintenance ? "记忆管理 Agent 维护候选" : hasConversationReadonly ? "只读连续性" : "未接入"}</strong>
              <small>普通回答不读取热摘要；压缩和恢复流程读取压缩视图。</small>
            </article>
            <article className="orchestration-memory-lane">
              <span><ShieldCheck size={15} />Durable Memory</span>
              <strong>{hasDurableCandidate ? "候选写入受控" : "只允许读取或不接入"}</strong>
              <small>长期写入只接受记忆管理 Agent 输出的计划和沙箱校验。</small>
            </article>
          </div>
          <div className="orchestration-memory-path">
            <span className={selectedContextSectionSet.has("memory_runtime_view") ? "is-on" : ""}>记忆运行视图</span>
            <span className={hasStateReadonly ? "is-on" : ""}>状态快照</span>
            <span className={hasConversationReadonly ? "is-on" : ""}>会话只读</span>
            <span className={hasDurableCandidate ? "is-on" : ""}>长期候选</span>
          </div>
        </div>
      </section>

      <aside className="boundary-card orchestration-context-summary-card">
        <header><strong>边界摘要</strong></header>
        <div className="boundary-kv">
          <p><span>记忆</span><strong>{memorySummary}</strong></p>
          <p><span>上下文</span><strong>{contextSummary}</strong></p>
          <p><span>共同契约</span><strong>{sharedContractEnabled ? "采用" : "不采用"}</strong></p>
          <p><span>写入治理</span><strong>{hasSessionMaintenance || hasDurableCandidate ? "由记忆管理 Agent 接管" : "当前未开放写入"}</strong></p>
        </div>
      </aside>
    </section>
  );
}

export function OrchestrationRuntimeConfigWorkbench({
  runtimeDraft,
  patchRuntimeDraft,
  displayId,
  runtimeSaveBlocked,
  saveRuntimeProfile,
  saving,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  displayId: (value: unknown, fallback?: string) => string;
  runtimeSaveBlocked: boolean;
  saveRuntimeProfile: () => Promise<void>;
  saving: "" | "agent" | "runtime" | "group" | "create" | "delete";
}) {
  const metadata = asRecord(runtimeDraft.metadata);
  const runtimeConfig = runtimeConfigFrom(metadata);
  const config = runtimeConfig.search ?? DEFAULT_SEARCH_RUNTIME_CONFIG;
  const isSearchTemplate = runtimeConfig.runtime_kind === "search_agent" || runtimeConfig.template_id === DEEPSEARCH_RUNTIME_TEMPLATE.template_id;
  const isContextCompactorTemplate = runtimeConfig.runtime_kind === "context_compactor" || runtimeConfig.template_id === CONTEXT_COMPACTOR_RUNTIME_TEMPLATE.template_id;
  const allowedOps = dedupe(runtimeDraft.allowed_operations ?? []);
  const blockedOps = dedupe(runtimeDraft.blocked_operations ?? []);
  const requiredOps = isSearchTemplate ? operationsForSearchRuntime(config) : ["op.model_response"];
  const missingOps = requiredOps.filter((operation) => !allowedOps.includes(operation));
  const blockedRequiredOps = requiredOps.filter((operation) => blockedOps.includes(operation));
  const templateIssue = runtimeTemplateIssue(runtimeConfig);
  const localEnabled = config.allow_local_files;
  const ragEnabled = config.search_sources.includes("rag");
  const memoryEnabled = config.allow_memory_read;

  function writeRuntimeConfig(nextConfig: GenericRuntimeConfig) {
    patchRuntimeDraft({
      metadata: {
        ...metadata,
        runtime_config: nextConfig,
        managed_by: String(metadata.managed_by || "orchestration_console"),
      },
    });
  }

  function patchRuntimeConfig(patch: Partial<GenericRuntimeConfig>) {
    const nextTemplateId = String(patch.template_id ?? runtimeConfig.template_id);
    const nextRuntimeMode = String(patch.runtime_mode ?? runtimeConfig.runtime_mode);
    writeRuntimeConfig({
      ...runtimeConfig,
      ...patch,
      runtime_kind: runtimeTemplateRuntimeKind(nextTemplateId),
      runtime_mode: validRuntimeModeForTemplate(nextTemplateId, nextRuntimeMode),
    });
  }

  function patchSearchRuntime(patch: Partial<SearchRuntimeConfig>) {
    const nextConfig = {
      ...config,
      ...patch,
    };
    nextConfig.search_sources = nextSearchSources(nextConfig);
    writeRuntimeConfig({
      ...runtimeConfig,
      template_id: runtimeConfig.template_id === DEFAULT_GENERIC_RUNTIME_CONFIG.template_id ? DEEPSEARCH_RUNTIME_TEMPLATE.template_id : runtimeConfig.template_id,
      runtime_kind: "search_agent",
      runtime_mode: nextConfig.runtime_mode,
      max_iterations: nextConfig.max_iterations,
      max_tool_calls: nextConfig.max_queries + nextConfig.max_fetches,
      max_sources: nextConfig.max_sources,
      evidence_packet_required: nextConfig.evidence_packet_required,
      stop_policy: nextConfig.stop_policy,
      search: nextConfig,
    });
  }

  function applyPermissionPreset() {
    const nextRequiredOps = isSearchTemplate ? operationsForSearchRuntime(config) : ["op.model_response"];
    patchRuntimeDraft({
      allowed_operations: dedupe([...allowedOps, ...nextRequiredOps]),
      blocked_operations: dedupe(blockedOps.filter((operation) => !nextRequiredOps.includes(operation))),
      metadata: {
        ...metadata,
        runtime_config: runtimeConfig,
        managed_by: String(metadata.managed_by || "orchestration_console"),
      },
    });
  }

  function applyRuntimeTemplate(templateId: string) {
    if (templateId === DEEPSEARCH_RUNTIME_TEMPLATE.template_id) {
      writeRuntimeConfig(DEEPSEARCH_RUNTIME_TEMPLATE);
      return;
    }
    if (templateId === CONTEXT_COMPACTOR_RUNTIME_TEMPLATE.template_id) {
      writeRuntimeConfig(CONTEXT_COMPACTOR_RUNTIME_TEMPLATE);
      return;
    }
    writeRuntimeConfig({
      ...DEFAULT_GENERIC_RUNTIME_CONFIG,
      template_id: templateId,
    });
  }

  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header>
          <strong>通用运行配置</strong>
          <OrchestrationBadge tone={isSearchTemplate ? "ok" : "neutral"}>
            {runtimeConfig.template_id}
          </OrchestrationBadge>
        </header>
        <div className="orchestration-identity-note">
          <span>配置落点：AgentRuntimeProfile.metadata.runtime_config。</span>
          <strong>这里管理通用 runtime config；Search Agent、Verifier、Writer 后续都从同一份配置装配，不再做专用旁路。</strong>
        </div>
        <div className="boundary-form">
          <OrchestrationField label="运行模板">
            <select value={runtimeConfig.template_id} onChange={(event) => applyRuntimeTemplate(event.target.value)}>
              <option value="runtime.template.general_agent">通用 Agent Loop</option>
              <option value="runtime.template.deepsearch">DeepSearch Search Agent</option>
              <option value="runtime.template.context_compactor">Context Compactor Agent</option>
            </select>
          </OrchestrationField>
          <OrchestrationField label="Runtime Kind">
            <select value={runtimeConfig.runtime_kind} onChange={() => patchRuntimeConfig({ runtime_kind: runtimeTemplateRuntimeKind(runtimeConfig.template_id) })}>
              <option value={runtimeTemplateRuntimeKind(runtimeConfig.template_id)}>{runtimeTemplateRuntimeKind(runtimeConfig.template_id)}</option>
            </select>
          </OrchestrationField>
          <OrchestrationField label="Runtime Mode">
            <select value={validRuntimeModeForTemplate(runtimeConfig.template_id, runtimeConfig.runtime_mode)} onChange={(event) => patchRuntimeConfig({ runtime_mode: event.target.value })}>
              {runtimeTemplateModes(runtimeConfig.template_id).map((mode) => (
                <option key={mode} value={mode}>{mode}</option>
              ))}
            </select>
          </OrchestrationField>
          <OrchestrationField label="最大迭代">
            <input min={1} max={30} type="number" value={runtimeConfig.max_iterations} onChange={(event) => patchRuntimeConfig({ max_iterations: Number(event.target.value || DEFAULT_GENERIC_RUNTIME_CONFIG.max_iterations) })} />
          </OrchestrationField>
          <OrchestrationField label="最大工具调用">
            <input min={1} max={100} type="number" value={runtimeConfig.max_tool_calls} onChange={(event) => patchRuntimeConfig({ max_tool_calls: Number(event.target.value || DEFAULT_GENERIC_RUNTIME_CONFIG.max_tool_calls) })} />
          </OrchestrationField>
          <OrchestrationField label="最大来源">
            <input min={1} max={100} type="number" value={runtimeConfig.max_sources} onChange={(event) => patchRuntimeConfig({ max_sources: Number(event.target.value || DEFAULT_GENERIC_RUNTIME_CONFIG.max_sources) })} />
          </OrchestrationField>
          <OrchestrationField label="停止策略" wide>
            <input value={runtimeConfig.stop_policy} onChange={(event) => patchRuntimeConfig({ stop_policy: event.target.value })} />
          </OrchestrationField>
          <label className="boundary-check">
            <input checked={runtimeConfig.evidence_packet_required} onChange={(event) => patchRuntimeConfig({ evidence_packet_required: event.target.checked })} type="checkbox" />
            必须输出证据包
          </label>
        </div>
        {isSearchTemplate ? (
          <>
        <div className="orchestration-identity-note">
          <span>模板参数：DeepSearch</span>
          <strong>以下字段是通用 runtime_config.search 的结构化编辑，不是单独的 Search 专用配置页。</strong>
        </div>
        <div className="boundary-form">
          <OrchestrationField label="运行模式">
            <select value={config.runtime_mode} onChange={(event) => patchSearchRuntime({ runtime_mode: event.target.value === "single_search" ? "single_search" : "deepsearch" })}>
              <option value="deepsearch">DeepSearch 多轮研究</option>
              <option value="single_search">单次搜索</option>
            </select>
          </OrchestrationField>
          <OrchestrationField label="Web Provider">
            <select value={config.web_provider} onChange={(event) => patchSearchRuntime({ web_provider: event.target.value })}>
              <option value="tavily">Tavily</option>
            </select>
          </OrchestrationField>
          <OrchestrationField label="搜索深度">
            <select value={config.search_depth} onChange={(event) => patchSearchRuntime({ search_depth: event.target.value === "basic" ? "basic" : "advanced" })}>
              <option value="advanced">advanced</option>
              <option value="basic">basic</option>
            </select>
          </OrchestrationField>
          <OrchestrationField label="最大轮次">
            <input min={1} max={12} type="number" value={config.max_iterations} onChange={(event) => patchSearchRuntime({ max_iterations: Number(event.target.value || DEFAULT_SEARCH_RUNTIME_CONFIG.max_iterations) })} />
          </OrchestrationField>
          <OrchestrationField label="最大查询数">
            <input min={1} max={30} type="number" value={config.max_queries} onChange={(event) => patchSearchRuntime({ max_queries: Number(event.target.value || DEFAULT_SEARCH_RUNTIME_CONFIG.max_queries) })} />
          </OrchestrationField>
          <OrchestrationField label="最大抓取数">
            <input min={0} max={40} type="number" value={config.max_fetches} onChange={(event) => patchSearchRuntime({ max_fetches: Number(event.target.value || DEFAULT_SEARCH_RUNTIME_CONFIG.max_fetches) })} />
          </OrchestrationField>
          <OrchestrationField label="最大来源数">
            <input min={1} max={60} type="number" value={config.max_sources} onChange={(event) => patchSearchRuntime({ max_sources: Number(event.target.value || DEFAULT_SEARCH_RUNTIME_CONFIG.max_sources) })} />
          </OrchestrationField>
          <OrchestrationField label="停止策略" wide>
            <select value={config.stop_policy} onChange={(event) => patchSearchRuntime({ stop_policy: event.target.value })}>
              <option value="enough_evidence_or_budget_exhausted">证据足够或预算耗尽</option>
              <option value="budget_exhausted_only">只按预算停止</option>
              <option value="first_primary_source">找到首个一手来源后停止</option>
            </select>
          </OrchestrationField>
          <label className="boundary-check">
            <input checked={config.allow_fetch_url} onChange={(event) => patchSearchRuntime({ allow_fetch_url: event.target.checked })} type="checkbox" />
            允许抓取搜索结果 URL
          </label>
          <label className="boundary-check">
            <input checked={config.include_raw_content} onChange={(event) => patchSearchRuntime({ include_raw_content: event.target.checked })} type="checkbox" />
            请求原文内容
          </label>
          <label className="boundary-check">
            <input checked={config.prefer_primary_sources} onChange={(event) => patchSearchRuntime({ prefer_primary_sources: event.target.checked })} type="checkbox" />
            优先一手 / 官方来源
          </label>
          <label className="boundary-check">
            <input checked={config.freshness_required_by_default} onChange={(event) => patchSearchRuntime({ freshness_required_by_default: event.target.checked })} type="checkbox" />
            默认要求时效核验
          </label>
          <label className="boundary-check">
            <input checked={localEnabled} onChange={(event) => patchSearchRuntime({ allow_local_files: event.target.checked })} type="checkbox" />
            允许本地文件搜索
          </label>
          <label className="boundary-check">
            <input
              checked={ragEnabled}
              onChange={(event) => patchSearchRuntime({
                search_sources: event.target.checked
                  ? dedupe([...config.search_sources, "rag"])
                  : config.search_sources.filter((source) => source !== "rag"),
              })}
              type="checkbox"
            />
            允许 RAG / 知识库检索
          </label>
          <label className="boundary-check">
            <input checked={memoryEnabled} onChange={(event) => patchSearchRuntime({ allow_memory_read: event.target.checked })} type="checkbox" />
            允许记忆读取
          </label>
          <label className="boundary-check">
            <input checked={config.evidence_packet_required} onChange={(event) => patchSearchRuntime({ evidence_packet_required: event.target.checked })} type="checkbox" />
            必须输出 AgentEvidencePacket
          </label>
        </div>
          </>
        ) : null}
        {isContextCompactorTemplate ? (
          <>
            <div className="orchestration-identity-note">
              <span>模板参数：Context Compactor</span>
              <strong>压缩 Agent 只能调用模型生成恢复点；不能搜索、读写文件或发起委派。</strong>
            </div>
            <div className="boundary-form">
              <OrchestrationField label="输出契约">
                <input readOnly value={String(asRecord(runtimeConfig.context_compaction).output_contract || "context_recovery_point")} />
              </OrchestrationField>
              <OrchestrationField label="失败回退">
                <input readOnly value={String(asRecord(runtimeConfig.context_compaction).fallback || "deterministic")} />
              </OrchestrationField>
              <OrchestrationField label="保留最近消息">
                <input
                  min={1}
                  max={20}
                  type="number"
                  value={Number(asRecord(runtimeConfig.context_compaction).keep_last_messages ?? 6)}
                  onChange={(event) => patchRuntimeConfig({
                    context_compaction: {
                      ...asRecord(runtimeConfig.context_compaction),
                      keep_last_messages: Number(event.target.value || 6),
                    },
                  })}
                />
              </OrchestrationField>
              <OrchestrationField label="摘要字符上限">
                <input
                  min={500}
                  max={20000}
                  type="number"
                  value={Number(asRecord(runtimeConfig.context_compaction).max_summary_chars ?? 4000)}
                  onChange={(event) => patchRuntimeConfig({
                    context_compaction: {
                      ...asRecord(runtimeConfig.context_compaction),
                      max_summary_chars: Number(event.target.value || 4000),
                    },
                  })}
                />
              </OrchestrationField>
            </div>
          </>
        ) : null}
        <div className="boundary-actions">
          <button onClick={applyPermissionPreset} type="button"><CheckCircle2 size={14} />应用模板权限预设</button>
          <button disabled={saving === "runtime" || runtimeSaveBlocked} onClick={() => void saveRuntimeProfile()} type="button">
            <Save size={14} />{saving === "runtime" ? "保存中" : "保存运行档案"}
          </button>
          <button onClick={() => applyRuntimeTemplate(DEFAULT_GENERIC_RUNTIME_CONFIG.template_id)} type="button"><Settings2 size={14} />切换通用模板</button>
        </div>
      </div>

      <aside className="boundary-card">
        <header>
          <strong>权限与生效诊断</strong>
          <OrchestrationBadge tone={!missingOps.length && !blockedRequiredOps.length ? "ok" : "warn"}>
            {!missingOps.length && !blockedRequiredOps.length ? "权限齐备" : "需调整"}
          </OrchestrationBadge>
        </header>
        {isSearchTemplate ? <div className="boundary-readiness-list boundary-readiness-list--grid">
          <OrchestrationReadinessCard label="Web Search" ready={allowedOps.includes("op.web_search") && !blockedOps.includes("op.web_search")} value={allowedOps.includes("op.web_search") ? "已允许" : "未允许"} />
          <OrchestrationReadinessCard label="Fetch URL" ready={!config.allow_fetch_url || config.max_fetches <= 0 || (allowedOps.includes("op.fetch_url") && !blockedOps.includes("op.fetch_url"))} value={config.allow_fetch_url && config.max_fetches > 0 ? "需要" : "未启用"} />
          <OrchestrationReadinessCard label="Local Files" ready={!localEnabled || SEARCH_RUNTIME_LOCAL_OPERATIONS.every((operation) => allowedOps.includes(operation) && !blockedOps.includes(operation))} value={localEnabled ? "需要权限" : "未启用"} />
          <OrchestrationReadinessCard label="RAG Retrieval" ready={!ragEnabled || SEARCH_RUNTIME_RAG_OPERATIONS.every((operation) => allowedOps.includes(operation) && !blockedOps.includes(operation))} value={ragEnabled ? "需要权限" : "未启用"} />
          <OrchestrationReadinessCard label="Memory Read" ready={!memoryEnabled || SEARCH_RUNTIME_MEMORY_OPERATIONS.every((operation) => allowedOps.includes(operation) && !blockedOps.includes(operation))} value={memoryEnabled ? "需要权限" : "未启用"} />
        </div> : null}
        {isContextCompactorTemplate ? <div className="boundary-readiness-list boundary-readiness-list--grid">
          <OrchestrationReadinessCard label="Model Only" ready={allowedOps.includes("op.model_response") && !blockedOps.includes("op.model_response")} value="op.model_response" />
          <OrchestrationReadinessCard label="No Web" ready={!allowedOps.includes("op.web_search") && !allowedOps.includes("op.fetch_url")} value="不搜索" />
          <OrchestrationReadinessCard label="No Write" ready={!allowedOps.includes("op.write_file") && !allowedOps.includes("op.edit_file") && !allowedOps.includes("op.shell")} value="不写入" />
          <OrchestrationReadinessCard label="Contract" ready={String(asRecord(runtimeConfig.context_compaction).output_contract || "") === "context_recovery_point"} value="恢复点" />
        </div> : null}
        <div className="boundary-kv">
          <p><span>模板</span><strong>{runtimeConfig.template_id}</strong></p>
          <p><span>类型</span><strong>{runtimeConfig.runtime_kind}</strong></p>
          {isSearchTemplate ? <p><span>搜索源</span><strong>{config.search_sources.join(" / ")}</strong></p> : null}
          <p><span>所需操作</span><strong>{requiredOps.map((operation) => displayId(operation)).join(" / ")}</strong></p>
          <p><span>缺失操作</span><strong>{missingOps.length ? missingOps.join(" / ") : "无"}</strong></p>
          <p><span>被阻断操作</span><strong>{blockedRequiredOps.length ? blockedRequiredOps.join(" / ") : "无"}</strong></p>
          <p><span>模板约束</span><strong>{templateIssue || "通过"}</strong></p>
          <p><span>预算</span><strong>{runtimeConfig.max_iterations} 迭代 / {runtimeConfig.max_tool_calls} 工具调用 / {runtimeConfig.max_sources} 来源</strong></p>
        </div>
        <div className={missingOps.length || blockedRequiredOps.length || templateIssue ? "boundary-notice boundary-notice--error" : "boundary-notice"}>
          {missingOps.length || blockedRequiredOps.length || templateIssue ? <AlertTriangle size={16} /> : <Info size={16} />}
          {templateIssue
            ? "当前 runtime_config 与模板约束不一致，请重新选择运行模板或 Runtime Mode。"
            : missingOps.length || blockedRequiredOps.length
            ? "当前配置可以保存，但权限未齐备。请应用模板权限预设后保存运行档案。"
            : "配置必须点击保存运行档案后才会生效；运行时读取 metadata.runtime_config 装配。"}
        </div>
        <div className="boundary-actions">
          <button disabled={saving === "runtime" || runtimeSaveBlocked} onClick={() => void saveRuntimeProfile()} type="button">
            <Save size={14} />{saving === "runtime" ? "保存中" : "保存运行档案"}
          </button>
        </div>
      </aside>

    </section>
  );
}

export function OrchestrationCollaborationWorkbench({
  agentDraft,
  runtimeDraft,
  patchRuntimeDraft,
  delegateAgentOptions,
  displayId,
}: {
  agentDraft: AgentDraftLike;
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  delegateAgentOptions: OrchestrationOption[];
  displayId: (value: unknown, fallback?: string) => string;
}) {
  const allowedDelegateIds = dedupe(runtimeDraft.allowed_delegate_agent_ids ?? []);
  const canDelegate = Boolean(runtimeDraft.can_delegate_to_agents);
  const delegateOperationAllowed = dedupe(runtimeDraft.allowed_operations ?? []).includes("op.delegate_to_agent");
  const delegateOperationBlocked = dedupe(runtimeDraft.blocked_operations ?? []).includes("op.delegate_to_agent");
  const category = String(agentDraft.agent_category || "");
  const canBeDelegatedByDefault = category === "custom_agent" || category === "builtin_agent";

  function toggleDelegateOperation(enabled: boolean) {
    const allowedOps = dedupe(runtimeDraft.allowed_operations ?? []);
    const blockedOps = dedupe(runtimeDraft.blocked_operations ?? []);
    if (enabled) {
      patchRuntimeDraft({
        allowed_operations: dedupe([...allowedOps, "op.delegate_to_agent"]),
        blocked_operations: blockedOps.filter((item) => item !== "op.delegate_to_agent"),
      });
      return;
    }
    patchRuntimeDraft({
      allowed_operations: allowedOps.filter((item) => item !== "op.delegate_to_agent"),
    });
  }

  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header>
          <strong>协作资格</strong>
          <OrchestrationBadge tone={canDelegate && delegateOperationAllowed && !delegateOperationBlocked ? "ok" : "neutral"}>
            {canDelegate && delegateOperationAllowed && !delegateOperationBlocked ? "可发起委派" : "未开放委派"}
          </OrchestrationBadge>
        </header>
        <div className="orchestration-identity-note">
          <span>协作不是 Agent 分类本身。</span>
          <strong>系统管理 Agent 也可以显式进入委派池；是否能被调用由目标暴露策略、父 Agent 白名单和运行权限共同决定。</strong>
        </div>
        <div className="boundary-form">
          <label className="boundary-check">
            <input
              checked={canDelegate}
              onChange={(event) => patchRuntimeDraft({ can_delegate_to_agents: event.target.checked })}
              type="checkbox"
            />
            允许这个 Agent 发起委派
          </label>
          <label className="boundary-check">
            <input
              checked={delegateOperationAllowed && !delegateOperationBlocked}
              onChange={(event) => toggleDelegateOperation(event.target.checked)}
              type="checkbox"
            />
            允许运行操作 op.delegate_to_agent
          </label>
          <OrchestrationField label="单轮最大调用次数">
            <input
              min={0}
              type="number"
              value={runtimeDraft.max_delegate_calls_per_turn ?? 1}
              onChange={(event) => patchRuntimeDraft({ max_delegate_calls_per_turn: Number(event.target.value || 0) })}
            />
          </OrchestrationField>
          <OrchestrationField label="上下文交接策略">
            <input
              value={runtimeDraft.delegate_context_policy || "summary_and_refs_only"}
              onChange={(event) => patchRuntimeDraft({ delegate_context_policy: event.target.value })}
            />
          </OrchestrationField>
        </div>
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={delegateAgentOptions.map((item) => item.value)}
          label="允许委派目标"
          onChange={(values) => patchRuntimeDraft({ allowed_delegate_agent_ids: dedupe(values) })}
          options={delegateAgentOptions}
          selectedValues={allowedDelegateIds}
          emptyText="未设置白名单时由委派目录和目标 Agent 暴露策略决定"
        />
      </div>
      <aside className="boundary-card">
        <header><strong>协作诊断</strong></header>
        <div className="boundary-readiness-list boundary-readiness-list--grid">
          <OrchestrationReadinessCard label="可被委派" ready={canBeDelegatedByDefault} value={canBeDelegatedByDefault ? "默认可配置" : "默认不暴露"} />
          <OrchestrationReadinessCard label="可发起委派" ready={canDelegate} value={canDelegate ? "已开启" : "未开启"} />
          <OrchestrationReadinessCard label="委派操作" ready={delegateOperationAllowed && !delegateOperationBlocked} value={delegateOperationBlocked ? "被阻断" : delegateOperationAllowed ? "已允许" : "未允许"} />
          <OrchestrationReadinessCard label="目标白名单" ready={Boolean(allowedDelegateIds.length)} value={allowedDelegateIds.length ? `${allowedDelegateIds.length} 个` : "未限制"} />
        </div>
        <div className="boundary-kv">
          <p><span>Agent</span><strong>{agentDraft.agent_name || agentDraft.agent_id || "未选择"}</strong></p>
          <p><span>分类</span><strong>{valueLabel(category, displayId)}</strong></p>
          <p><span>交接策略</span><strong>{runtimeDraft.delegate_context_policy || "summary_and_refs_only"}</strong></p>
        </div>
      </aside>
    </section>
  );
}

export function OrchestrationAssemblyOverviewWorkbench({
  agentDraft,
  runtimeDraft,
  runtimeSummary,
  operationSummary,
  memorySummary,
  contextSummary,
  collaborationSummary,
  modelSummary,
  openLayer,
}: {
  agentDraft: AgentDraftLike;
  runtimeDraft: RuntimeDraftLike;
  runtimeSummary: string;
  operationSummary: string;
  memorySummary: string;
  contextSummary: string;
  collaborationSummary: string;
  modelSummary: string;
  openLayer: (layer: "identity" | "runtime_permissions" | "model_runtime" | "context_memory" | "collaboration" | "diagnostics") => void;
}) {
  const cards = [
    { label: "Agent 身份", value: agentDraft.agent_name || agentDraft.agent_id || "未配置", ready: Boolean(agentDraft.agent_id && agentDraft.agent_name), layer: "identity" as const },
    { label: "运行模式", value: runtimeSummary, ready: Boolean((runtimeDraft.enabled_runtime_modes ?? []).length), layer: "runtime_permissions" as const },
    { label: "运行操作", value: operationSummary, ready: Boolean((runtimeDraft.allowed_operations ?? []).length), layer: "runtime_permissions" as const },
    { label: "模型运行", value: modelSummary, ready: true, layer: "model_runtime" as const },
    { label: "记忆边界", value: memorySummary, ready: Boolean((runtimeDraft.allowed_memory_scopes ?? []).length), layer: "context_memory" as const },
    { label: "上下文段", value: contextSummary, ready: Boolean((runtimeDraft.allowed_context_sections ?? []).length), layer: "context_memory" as const },
    { label: "协作资格", value: collaborationSummary, ready: true, layer: "collaboration" as const },
  ];

  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card boundary-card--summary">
        <header>
          <strong>装配总览</strong>
          <OrchestrationBadge>只读汇总</OrchestrationBadge>
        </header>
        <div className="boundary-readiness-list boundary-readiness-list--grid">
          {cards.map((item) => (
            <button className="boundary-readiness boundary-readiness--button" key={item.label} onClick={() => openLayer(item.layer)} type="button">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
              <small>{item.ready ? "已配置" : "待配置"}</small>
            </button>
          ))}
        </div>
      </div>
      <aside className="boundary-card">
        <header><strong>配置落点</strong></header>
        <div className="boundary-kv">
          <p><span>身份</span><strong>AgentRegistry / AgentDescriptor</strong></p>
          <p><span>运行权限</span><strong>AgentRuntimeProfile</strong></p>
          <p><span>模型运行</span><strong>AgentRuntimeProfile.model_profile</strong></p>
          <p><span>任务环境</span><strong>TaskEnvironmentRegistry</strong></p>
          <p><span>最终执行</span><strong>ResourcePolicy / OperationGate</strong></p>
        </div>
      </aside>
    </section>
  );
}

export function OrchestrationDiagnosticsWorkbench({
  eligibilityChecks,
  overlapOps,
  capabilityItemsCount,
  runtimeDraft,
}: {
  eligibilityChecks: Array<{ label: string; value: string; ready: boolean }>;
  overlapOps: string[];
  capabilityItemsCount: number;
  runtimeDraft?: RuntimeDraftLike;
}) {
  const modelProfile = runtimeDraft?.model_profile ?? {};
  const modelHasRawSecret = Object.keys(modelProfile).some((key) => key.toLowerCase().includes("api_key") || key.toLowerCase().includes("secret"));
  const modelMode = modelProfile.provider || modelProfile.model ? "Agent 覆盖" : "继承默认";

  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header>
          <strong>运行诊断</strong>
          <OrchestrationBadge tone={eligibilityChecks.every((item) => item.ready) && !overlapOps.length ? "ok" : "warn"}>
            {eligibilityChecks.every((item) => item.ready) && !overlapOps.length ? "清晰" : "需处理"}
          </OrchestrationBadge>
        </header>
        <div className="boundary-readiness-list boundary-readiness-list--grid">
          {eligibilityChecks.map((item) => <OrchestrationReadinessCard key={item.label} {...item} />)}
          <OrchestrationReadinessCard label="能力目录" ready={capabilityItemsCount > 0} value={capabilityItemsCount > 0 ? `${capabilityItemsCount} 项` : "未加载"} />
          <OrchestrationReadinessCard label="模型档案" ready={!modelHasRawSecret} value={modelHasRawSecret ? "包含敏感字段" : modelMode} />
        </div>
        {overlapOps.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />允许和阻断操作冲突：{overlapOps.join(" / ")}</div> : null}
        {modelHasRawSecret ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />模型档案不能保存 API Key 或 secret；请使用 credential_ref。</div> : null}
      </div>
    </section>
  );
}
