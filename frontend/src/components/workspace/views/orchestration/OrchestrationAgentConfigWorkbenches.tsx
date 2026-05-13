"use client";

import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  OrchestrationBadge,
  OrchestrationField,
  OrchestrationOptionSelection,
  OrchestrationReadinessCard,
  type OrchestrationOption,
} from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";
import type {
  CapabilitySystemCatalog,
  OperationDescriptor,
  OperationMCP,
} from "@/lib/api";

type RuntimeDraftLike = {
  agent_profile_id?: string;
  approval_policy?: string;
  trace_policy?: string;
  lifecycle_policy?: string;
  allowed_task_modes_text?: string;
  allowed_runtime_lanes_text?: string;
  allowed_operations_text?: string;
  blocked_operations_text?: string;
  allowed_memory_scopes_text?: string;
  allowed_context_sections_text?: string;
  use_shared_contract?: boolean;
  output_contracts_text?: string;
  can_delegate_to_agents?: boolean;
  allowed_delegate_agent_ids_text?: string;
  allowed_delegate_agent_categories_text?: string;
  max_delegate_calls_per_turn?: number;
  delegate_context_policy?: string;
};

function splitList(value: string | undefined) {
  return String(value || "")
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function serializeList(values: string[]) {
  return Array.from(new Set(values.map((item) => String(item || "").trim()).filter(Boolean))).join("\n");
}

type CapabilityPool = "skill" | "tool" | "mcp";
type CapabilityStatus = "allowed" | "blocked" | "conflict" | "partial" | "neutral" | "unbound";
type RiskTone = "ok" | "warn" | "danger" | "neutral";

type CapabilityCardModel = {
  id: string;
  pool: CapabilityPool;
  title: string;
  subtitle: string;
  description: string;
  operationIds: string[];
  sourceLabel: string;
  sourceDetail: string;
  riskLabel: string;
  riskTone: RiskTone;
  riskItems: string[];
  tags: string[];
  metadata: Array<[string, string]>;
};

const SKILL_ROUTE_OPERATION_MAP: Record<string, string> = {
  rag: "op.mcp_retrieval",
  retrieval: "op.mcp_retrieval",
  pdf: "op.mcp_pdf",
  structured_data: "op.mcp_structured_data",
  data: "op.mcp_structured_data",
};

const POOL_META: Record<CapabilityPool, { title: string; summary: string }> = {
  skill: {
    title: "Skills",
    summary: "模型可见的任务能力入口，授权的是它依赖的运行操作。",
  },
  tool: {
    title: "Tools",
    summary: "本地工具与运行操作，直接控制 Agent 可调用的 operation。",
  },
  mcp: {
    title: "MCP",
    summary: "本地 MCP 能力端点，通常承接检索、PDF 与结构化数据处理。",
  },
};

const OPERATION_TYPE_LABELS: Record<string, string> = {
  agent: "子 Agent",
  artifact: "产物",
  filesystem: "文件系统",
  mcp: "MCP",
  memory: "记忆",
  model: "模型响应",
  network: "网络",
  session: "会话",
  shell: "本地执行",
  vcs: "版本控制",
};

const SOURCE_CLASS_LABELS: Record<string, string> = {
  data: "数据",
  document: "文档",
  local_files: "本地文件",
  rag: "知识检索",
  system_execution: "系统执行",
  web: "外部网络",
};

const RISK_TAG_LABELS: Record<string, string> = {
  agent_execution: "可启动隔离 Agent",
  artifact_write_candidate: "可能提交产物引用",
  document_analysis: "文档解析",
  external_fetch: "外部 URL 抓取",
  git_read: "Git 只读",
  indexing: "索引写入候选",
  local_read: "本地读取",
  local_write: "本地写入",
  mcp_execution: "MCP 执行",
  memory_read: "记忆读取",
  memory_write_candidate: "记忆写入候选",
  model_response: "模型回复",
  multimodal: "多模态读取",
  network_open_world: "开放网络",
  python_execution: "Python 执行",
  read_only: "只读",
  session_write_candidate: "会话写入候选",
  shell_execution: "终端执行",
  structured_config: "结构化配置读取",
  structured_data: "结构化数据",
};

function asStringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function compact(value: unknown, fallback = "未注册说明") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function operationTypeLabel(value: unknown) {
  const raw = String(value || "").trim();
  return OPERATION_TYPE_LABELS[raw] || raw || "运行操作";
}

function tagLabel(value: string) {
  return RISK_TAG_LABELS[value] || value;
}

function riskToneFromLevel(level: string): RiskTone {
  if (["高", "极高"].includes(level)) return "danger";
  if (level === "中") return "warn";
  if (level === "低") return "ok";
  return "neutral";
}

function riskFromOperation(operation?: OperationDescriptor | null): { label: string; tone: RiskTone; items: string[] } {
  if (!operation) {
    return { label: "注册信息不足", tone: "warn", items: ["缺少 operation 描述"] };
  }
  const items = [
    ...operation.risk_tags.map(tagLabel),
    operation.read_only ? "只读" : "",
    operation.destructive ? "破坏性操作" : "",
    operation.requires_approval_by_default ? "默认需要审批" : "",
    operation.concurrency_safe ? "可并发" : "",
  ].filter(Boolean);
  if (operation.destructive) return { label: "高风险", tone: "danger", items };
  if (operation.requires_approval_by_default || operation.risk_tags.some((tag) => tag.includes("write") || tag.includes("execution") || tag.includes("network"))) {
    return { label: "需审慎授权", tone: "warn", items };
  }
  if (operation.read_only) return { label: "低风险只读", tone: "ok", items };
  return { label: "中性风险", tone: "neutral", items };
}

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
    allowed: "允许",
    blocked: "禁止",
    conflict: "冲突",
    neutral: "未配置",
    partial: "部分允许",
    unbound: "未绑定操作",
  };
  return labels[status];
}

function operationFallbacks(operationDescriptors: OperationDescriptor[], operationOptionItems: OrchestrationOption[]) {
  const byId = new Map(operationDescriptors.map((operation) => [operation.operation_id, operation]));
  const fallbackDescriptors = operationOptionItems
    .map((item) => String(item.value || item.id || "").trim())
    .filter((operationId) => operationId && !byId.has(operationId))
    .map((operationId) => ({
      operation_id: operationId,
      operation_type: "",
      title: operationOptionItems.find((item) => (item.value || item.id) === operationId)?.label || operationId,
      capability_summary: operationOptionItems.find((item) => (item.value || item.id) === operationId)?.description || "",
      provider: "operation_options",
      aliases: [],
      risk_tags: [],
      read_only: false,
      destructive: false,
      concurrency_safe: false,
      requires_user_interaction: false,
      requires_approval_by_default: false,
    }));
  return [...operationDescriptors, ...fallbackDescriptors] as OperationDescriptor[];
}

function buildCapabilityCards({
  capabilityCatalog,
  operationDescriptors,
  operationOptionItems,
}: {
  capabilityCatalog: CapabilitySystemCatalog | null;
  operationDescriptors: OperationDescriptor[];
  operationOptionItems: OrchestrationOption[];
}) {
  const operations = operationFallbacks(operationDescriptors, operationOptionItems);
  const operationById = new Map(operations.map((operation) => [operation.operation_id, operation]));
  const usedToolOperationIds = new Set<string>();
  const cards: CapabilityCardModel[] = [];

  for (const skill of capabilityCatalog?.skills ?? []) {
    const route = String(skill.runtime.preferred_route || "").trim();
    const operationId = route.startsWith("op.") ? route : SKILL_ROUTE_OPERATION_MAP[route] || "";
    const operation = operationById.get(operationId);
    const risk = riskFromOperation(operation);
    cards.push({
      id: `skill:${skill.runtime.name}`,
      pool: "skill",
      title: skill.prompt_view.title || skill.runtime.title || skill.runtime.name,
      subtitle: operationId ? `依赖 ${operationId}` : "未映射到运行操作",
      description: compact(skill.prompt_view.capability || skill.runtime.description),
      operationIds: operationId ? [operationId] : [],
      sourceLabel: "Skill · 模型可见入口",
      sourceDetail: `preferred_route=${route || "未配置"}，实际授权落到依赖 operation。`,
      riskLabel: risk.label,
      riskTone: risk.tone,
      riskItems: risk.items,
      tags: [...skill.runtime.capability_tags, ...skill.runtime.supported_modalities].slice(0, 8),
      metadata: [
        ["使用时机", compact(skill.prompt_view.use_when, "未注册 use_when")],
        ["输出规则", compact(skill.prompt_view.output_rule, "未注册 output_rule")],
        ["上下文", skill.runtime.context_mode || "未配置"],
      ],
    });
  }

  for (const tool of capabilityCatalog?.tools ?? []) {
    const operation = operationById.get(tool.operation_id);
    const metadata = tool.operation_metadata ?? {};
    const riskLevel = String(metadata.risk_level || "");
    const operationRisk = riskFromOperation(operation);
    usedToolOperationIds.add(tool.operation_id);
    cards.push({
      id: `tool:${tool.name}`,
      pool: "tool",
      title: operation?.title || tool.name,
      subtitle: `${tool.name} · ${tool.operation_id}`,
      description: compact(operation?.capability_summary || metadata.note || tool.capability_tags.join(" / ")),
      operationIds: tool.operation_id ? [tool.operation_id] : [],
      sourceLabel: `Tool · ${SOURCE_CLASS_LABELS[String(metadata.source_class || "")] || operationTypeLabel(operation?.operation_type)}`,
      sourceDetail: `${String(metadata.tool_boundary || "未标注边界")} · ${String(metadata.adapter_type || tool.module || "本地适配器")}`,
      riskLabel: riskLevel ? `${riskLevel}风险` : operationRisk.label,
      riskTone: riskLevel ? riskToneFromLevel(riskLevel) : operationRisk.tone,
      riskItems: [
        ...operationRisk.items,
        ...tool.safety_tags.map(tagLabel),
        tool.safe_for_auto_route ? "可自动路由" : "需要显式触发",
        String(metadata.runtime_policy || ""),
      ].filter(Boolean).slice(0, 10),
      tags: [...tool.capability_tags, ...tool.supported_modalities].slice(0, 8),
      metadata: [
        ["运行可见性", tool.runtime_visibility || "未配置"],
        ["Prompt 暴露", tool.prompt_exposure_policy || "未配置"],
        ["资源暴露", tool.resource_exposure_policy || "未配置"],
      ],
    });
  }

  for (const operation of operations) {
    if (operation.operation_type === "mcp" || usedToolOperationIds.has(operation.operation_id)) continue;
    const risk = riskFromOperation(operation);
    cards.push({
      id: `operation:${operation.operation_id}`,
      pool: "tool",
      title: operation.title || operation.operation_id,
      subtitle: `${operationTypeLabel(operation.operation_type)} · ${operation.operation_id}`,
      description: compact(operation.capability_summary),
      operationIds: [operation.operation_id],
      sourceLabel: "运行操作注册表",
      sourceDetail: `${operationTypeLabel(operation.operation_type)} operation，由运行时授权列表直接控制。`,
      riskLabel: risk.label,
      riskTone: risk.tone,
      riskItems: risk.items,
      tags: operation.risk_tags.map(tagLabel).slice(0, 8),
      metadata: [
        ["Provider", operation.provider || "builtin"],
        ["审批", operation.requires_approval_by_default ? "默认需要审批" : "默认不要求审批"],
        ["中断行为", String((operation as OperationDescriptor & { interrupt_behavior?: string }).interrupt_behavior || "未配置")],
      ],
    });
  }

  const mcpCandidates: OperationMCP[] = capabilityCatalog?.mcps?.length
    ? capabilityCatalog.mcps
    : (capabilityCatalog?.binding_graph.mcp_nodes ?? []).map((node) => ({
      ...node,
      transport: node.transport,
      model_visibility: node.model_visibility,
      tags: node.tags,
    }));

  const mcpOperationIds = new Set<string>();
  for (const mcp of mcpCandidates) {
    const operation = operationById.get(mcp.operation_id);
    const risk = riskFromOperation(operation);
    mcpOperationIds.add(mcp.operation_id);
    cards.push({
      id: `mcp:${mcp.mcp_id || mcp.operation_id}`,
      pool: "mcp",
      title: mcp.name || operation?.title || mcp.operation_id,
      subtitle: `${mcp.route || mcp.unit_id || "local"} · ${mcp.operation_id}`,
      description: compact(mcp.description || operation?.capability_summary),
      operationIds: mcp.operation_id ? [mcp.operation_id] : [],
      sourceLabel: "MCP · 本地能力端点",
      sourceDetail: `${mcp.transport || "in_process"} · ${mcp.model_visibility || "not_direct_model_tool"}`,
      riskLabel: risk.label,
      riskTone: risk.tone,
      riskItems: [
        ...risk.items,
        ...asStringArray(mcp.input_modes).map((item) => `输入 ${item}`),
        ...asStringArray(mcp.output_modes).map((item) => `输出 ${item}`),
      ].slice(0, 10),
      tags: asStringArray(mcp.tags).slice(0, 8),
      metadata: [
        ["MCP ID", mcp.mcp_id || "未配置"],
        ["Unit", mcp.unit_id || "未配置"],
        ["Server", mcp.server_name || "local-capability-endpoints"],
      ],
    });
  }

  for (const operation of operations.filter((item) => item.operation_type === "mcp" && !mcpOperationIds.has(item.operation_id))) {
    const risk = riskFromOperation(operation);
    cards.push({
      id: `mcp-operation:${operation.operation_id}`,
      pool: "mcp",
      title: operation.title || operation.operation_id,
      subtitle: operation.operation_id,
      description: compact(operation.capability_summary),
      operationIds: [operation.operation_id],
      sourceLabel: "MCP · Operation 后备",
      sourceDetail: "能力系统未返回 MCP endpoint 明细，当前使用 operation registry 后备展示。",
      riskLabel: risk.label,
      riskTone: risk.tone,
      riskItems: risk.items,
      tags: operation.risk_tags.map(tagLabel).slice(0, 8),
      metadata: [["注册状态", "缺少 MCP endpoint 明细"]],
    });
  }

  return cards;
}

export function OrchestrationRuntimeWorkbench({
  runtimeDraft,
  patchRuntimeDraft,
  approvalPolicies,
  tracePolicies,
  approvalPolicyOptions,
  tracePolicyOptions,
  taskModeOptions,
  runtimeLaneOptions,
  taskModeOptionItems,
  runtimeLaneOptionItems,
  outputContractOptions,
  outputContractOptionItems,
  displayId,
  taskModesSummary,
  runtimeLanesSummary,
  outputContractsSummary,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  approvalPolicies: string[];
  tracePolicies: string[];
  approvalPolicyOptions: OrchestrationOption[];
  tracePolicyOptions: OrchestrationOption[];
  taskModeOptions: string[];
  runtimeLaneOptions: string[];
  outputContractOptions: string[];
  taskModeOptionItems: OrchestrationOption[];
  runtimeLaneOptionItems: OrchestrationOption[];
  outputContractOptionItems: OrchestrationOption[];
  displayId: (value: unknown, fallback?: string) => string;
  taskModesSummary: string;
  runtimeLanesSummary: string;
  outputContractsSummary: string;
}) {
  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header><strong>运行档案</strong><OrchestrationBadge>{runtimeDraft.agent_profile_id || "草稿"}</OrchestrationBadge></header>
        <div className="boundary-form">
          <OrchestrationField label="运行档案标识"><input value={runtimeDraft.agent_profile_id || ""} onChange={(event) => patchRuntimeDraft({ agent_profile_id: event.target.value })} /></OrchestrationField>
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
          <OrchestrationField label="生命周期"><input value={runtimeDraft.lifecycle_policy || ""} onChange={(event) => patchRuntimeDraft({ lifecycle_policy: event.target.value })} /></OrchestrationField>
        </div>
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={taskModeOptions}
          label="可承接任务范围"
          onChange={(values) => patchRuntimeDraft({ allowed_task_modes_text: serializeList(values) })}
          options={taskModeOptionItems}
          selectedValues={splitList(runtimeDraft.allowed_task_modes_text)}
        />
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={runtimeLaneOptions}
          label="允许运行通道"
          onChange={(values) => patchRuntimeDraft({ allowed_runtime_lanes_text: serializeList(values) })}
          options={runtimeLaneOptionItems}
          selectedValues={splitList(runtimeDraft.allowed_runtime_lanes_text)}
        />
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={outputContractOptions}
          label="允许输出契约"
          onChange={(values) => patchRuntimeDraft({ output_contracts_text: serializeList(values) })}
          options={outputContractOptionItems}
          selectedValues={splitList(runtimeDraft.output_contracts_text)}
        />
        <section className="boundary-nested-panel">
          <header>
            <strong>子 Agent 调用授权</strong>
            <OrchestrationBadge tone={runtimeDraft.can_delegate_to_agents ? "ok" : "neutral"}>
              {runtimeDraft.can_delegate_to_agents ? "可调用" : "不可调用"}
            </OrchestrationBadge>
          </header>
          <label className="boundary-check">
            <input
              checked={Boolean(runtimeDraft.can_delegate_to_agents)}
              onChange={(event) => patchRuntimeDraft({ can_delegate_to_agents: event.target.checked })}
              type="checkbox"
            />
            允许这个 Agent 调用子 Agent
          </label>
          <div className="boundary-form">
            <OrchestrationField label="可调用 Agent ID">
              <textarea
                placeholder="agent:rag_analyst&#10;agent:pdf_reader&#10;agent:table_analyst"
                value={runtimeDraft.allowed_delegate_agent_ids_text || ""}
                onChange={(event) => patchRuntimeDraft({ allowed_delegate_agent_ids_text: event.target.value })}
              />
            </OrchestrationField>
            <OrchestrationField label="可调用类别">
              <textarea
                placeholder="worker_sub_agent"
                value={runtimeDraft.allowed_delegate_agent_categories_text || "worker_sub_agent"}
                onChange={(event) => patchRuntimeDraft({ allowed_delegate_agent_categories_text: event.target.value })}
              />
            </OrchestrationField>
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
        </section>
      </div>
      <aside className="boundary-card">
        <header><strong>运行摘要</strong></header>
        <div className="boundary-kv">
          <p><span>任务范围</span><strong>{taskModesSummary}</strong></p>
          <p><span>运行通道</span><strong>{runtimeLanesSummary}</strong></p>
          <p><span>输出契约</span><strong>{outputContractsSummary}</strong></p>
          <p><span>子 Agent 调用</span><strong>{runtimeDraft.can_delegate_to_agents ? "允许" : "禁止"}</strong></p>
        </div>
      </aside>
    </section>
  );
}

export function OrchestrationPermissionsWorkbench({
  runtimeDraft,
  patchRuntimeDraft,
  overlapOps,
  capabilityCatalog,
  operationDescriptors,
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
  capabilityCatalog: CapabilitySystemCatalog | null;
  operationDescriptors: OperationDescriptor[];
  operationOptions: string[];
  operationOptionItems: OrchestrationOption[];
  displayId: (value: unknown, fallback?: string) => string;
  allowedOpsCount: number;
  blockedOpsCount: number;
  overlapSummary: string;
}) {
  const allowedOps = splitList(runtimeDraft.allowed_operations_text);
  const blockedOps = splitList(runtimeDraft.blocked_operations_text);
  const allowedSet = useMemo(() => new Set(allowedOps), [allowedOps]);
  const blockedSet = useMemo(() => new Set(blockedOps), [blockedOps]);
  const capabilityCards = useMemo(
    () => buildCapabilityCards({ capabilityCatalog, operationDescriptors, operationOptionItems }),
    [capabilityCatalog, operationDescriptors, operationOptionItems],
  );
  const [selectedCapabilityId, setSelectedCapabilityId] = useState("");
  const selectedCapability = capabilityCards.find((item) => item.id === selectedCapabilityId) ?? capabilityCards[0] ?? null;

  useEffect(() => {
    if (!capabilityCards.length) {
      setSelectedCapabilityId("");
      return;
    }
    setSelectedCapabilityId((current) => capabilityCards.some((item) => item.id === current) ? current : capabilityCards[0].id);
  }, [capabilityCards]);

  function applyCapability(operationIds: string[], mode: "allow" | "block") {
    const ids = operationIds.map((item) => String(item || "").trim()).filter(Boolean);
    if (!ids.length) return;
    if (mode === "allow") {
      patchRuntimeDraft({
        allowed_operations_text: serializeList([...allowedOps, ...ids]),
        blocked_operations_text: serializeList(blockedOps.filter((item) => !ids.includes(item))),
      });
      return;
    }
    patchRuntimeDraft({
      allowed_operations_text: serializeList(allowedOps.filter((item) => !ids.includes(item))),
      blocked_operations_text: serializeList([...blockedOps, ...ids]),
    });
  }

  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide orchestration-capability-permissions">
      <div className="boundary-card orchestration-capability-pools">
        <header><strong>权限与能力边界</strong><OrchestrationBadge tone={overlapOps.length ? "danger" : "ok"}>{overlapOps.length ? "冲突" : "清晰"}</OrchestrationBadge></header>
        {overlapOps.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{overlapOps.join(" / ")} 同时出现在允许和阻断列表。</div> : null}
        {!capabilityCatalog ? <div className="boundary-notice"><Info size={16} />能力系统目录加载中，当前仅使用运行操作注册表。</div> : null}
        {(["skill", "tool", "mcp"] as CapabilityPool[]).map((pool) => {
          const cards = capabilityCards.filter((item) => item.pool === pool);
          const allowedCount = cards.filter((item) => capabilityStatus(item.operationIds, allowedSet, blockedSet) === "allowed").length;
          return (
            <section className="orchestration-capability-pool" key={pool}>
              <div className="orchestration-capability-pool__head">
                <div>
                  <strong>{POOL_META[pool].title}</strong>
                  <span>{POOL_META[pool].summary}</span>
                </div>
                <small>{allowedCount}/{cards.length} 允许</small>
              </div>
              <div className="orchestration-capability-card-grid">
                {cards.length ? cards.map((card) => {
                  const status = capabilityStatus(card.operationIds, allowedSet, blockedSet);
                  const active = selectedCapability?.id === card.id;
                  return (
                    <article
                      className={[
                        "orchestration-capability-card",
                        `orchestration-capability-card--${status}`,
                        active ? "orchestration-capability-card--active" : "",
                      ].filter(Boolean).join(" ")}
                      key={card.id}
                      onClick={() => setSelectedCapabilityId(card.id)}
                    >
                      <div className="orchestration-capability-card__top">
                        <span>{card.sourceLabel}</span>
                        <em>{statusLabel(status)}</em>
                      </div>
                      <strong>{card.title}</strong>
                      <div className="orchestration-capability-card__actions">
                        <button
                          className={status === "allowed" ? "is-active" : ""}
                          disabled={!card.operationIds.length}
                          onClick={(event) => {
                            event.stopPropagation();
                            applyCapability(card.operationIds, "allow");
                          }}
                          type="button"
                        >
                          <CheckCircle2 size={14} />允许
                        </button>
                        <button
                          className={status === "blocked" ? "is-danger-active" : ""}
                          disabled={!card.operationIds.length}
                          onClick={(event) => {
                            event.stopPropagation();
                            applyCapability(card.operationIds, "block");
                          }}
                          type="button"
                        >
                          <XCircle size={14} />禁止
                        </button>
                      </div>
                    </article>
                  );
                }) : <div className="boundary-empty">没有注册到 {POOL_META[pool].title} 能力。</div>}
              </div>
            </section>
          );
        })}
        <details className="orchestration-permission-raw">
          <summary>原始 operation 列表</summary>
          <OrchestrationOptionSelection
            displayId={displayId}
            fallbackOptions={operationOptions}
            label="允许操作"
            onChange={(values) => patchRuntimeDraft({ allowed_operations_text: serializeList(values) })}
            options={operationOptionItems}
            selectedValues={allowedOps}
          />
          <OrchestrationOptionSelection
            displayId={displayId}
            fallbackOptions={operationOptions}
            label="阻断操作"
            onChange={(values) => patchRuntimeDraft({ blocked_operations_text: serializeList(values) })}
            options={operationOptionItems}
            selectedValues={blockedOps}
          />
        </details>
      </div>
      <aside className="boundary-card orchestration-capability-inspector">
        <header><strong>能力详情</strong>{selectedCapability ? <OrchestrationBadge tone={selectedCapability.riskTone === "danger" ? "danger" : selectedCapability.riskTone === "warn" ? "warn" : selectedCapability.riskTone === "ok" ? "ok" : "neutral"}>{statusLabel(capabilityStatus(selectedCapability.operationIds, allowedSet, blockedSet))}</OrchestrationBadge> : null}</header>
        {selectedCapability ? (
          <>
            <div className="orchestration-capability-inspector__hero">
              <span>{selectedCapability.sourceLabel}</span>
              <h4>{selectedCapability.title}</h4>
              <p>{selectedCapability.description}</p>
            </div>
            <div className="boundary-kv">
              <p><span>来源</span><strong>{selectedCapability.sourceDetail}</strong></p>
              <p><span>依赖操作</span><strong>{selectedCapability.operationIds.length ? selectedCapability.operationIds.map((item) => displayId(item)).join(" / ") : "未绑定 operation"}</strong></p>
              <p><span>风险</span><strong>{selectedCapability.riskLabel}</strong></p>
              <p><span>允许</span><strong>{allowedOpsCount}</strong></p>
              <p><span>阻断</span><strong>{blockedOpsCount}</strong></p>
              <p><span>冲突</span><strong>{overlapSummary}</strong></p>
            </div>
            <section className="orchestration-capability-detail-block">
              <strong>风险与限制</strong>
              <div>
                {selectedCapability.riskItems.length ? selectedCapability.riskItems.map((item) => <span key={item}>{item}</span>) : <span>注册信息不足</span>}
              </div>
            </section>
            <section className="orchestration-capability-detail-block">
              <strong>必要能力介绍</strong>
              <div>
                {selectedCapability.metadata.map(([label, value]) => <p key={label}><span>{label}</span><b>{value}</b></p>)}
              </div>
            </section>
            <div className="orchestration-capability-inspector__actions">
              <button disabled={!selectedCapability.operationIds.length} onClick={() => applyCapability(selectedCapability.operationIds, "allow")} type="button"><CheckCircle2 size={14} />允许该能力</button>
              <button disabled={!selectedCapability.operationIds.length} onClick={() => applyCapability(selectedCapability.operationIds, "block")} type="button"><XCircle size={14} />禁止该能力</button>
            </div>
          </>
        ) : <div className="boundary-empty">请选择一个能力卡片查看来源、风险和说明。</div>}
      </aside>
    </section>
  );
}

export function OrchestrationContextWorkbench({
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
  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header><strong>记忆与上下文边界</strong><OrchestrationBadge>Agent 静态边界</OrchestrationBadge></header>
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={memoryScopeOptions}
          label="允许记忆范围"
          onChange={(values) => patchRuntimeDraft({ allowed_memory_scopes_text: serializeList(values) })}
          options={memoryScopeOptionItems}
          selectedValues={splitList(runtimeDraft.allowed_memory_scopes_text)}
        />
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={contextSectionOptions}
          label="允许上下文段"
          onChange={(values) => patchRuntimeDraft({ allowed_context_sections_text: serializeList(values) })}
          options={contextSectionOptionItems}
          selectedValues={splitList(runtimeDraft.allowed_context_sections_text)}
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
      <aside className="boundary-card">
        <header><strong>边界摘要</strong></header>
        <div className="boundary-kv">
          <p><span>记忆</span><strong>{memorySummary}</strong></p>
          <p><span>上下文</span><strong>{contextSummary}</strong></p>
          <p><span>共同契约</span><strong>{sharedContractEnabled ? "采用" : "不采用"}</strong></p>
        </div>
      </aside>
    </section>
  );
}

export function OrchestrationEligibilityWorkbench({
  eligibilityChecks,
}: {
  eligibilityChecks: Array<{ label: string; value: string; ready: boolean }>;
}) {
  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header><strong>承接资格预览</strong><OrchestrationBadge tone={eligibilityChecks.every((item) => item.ready) ? "ok" : "warn"}>{eligibilityChecks.every((item) => item.ready) ? "可承接" : "未完整"}</OrchestrationBadge></header>
        <div className="boundary-readiness-list boundary-readiness-list--grid">
          {eligibilityChecks.map((item) => <OrchestrationReadinessCard key={item.label} {...item} />)}
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
  );
}
