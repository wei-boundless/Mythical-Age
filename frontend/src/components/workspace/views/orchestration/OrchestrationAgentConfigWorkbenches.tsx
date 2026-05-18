"use client";

import { AlertTriangle, CheckCircle2, Database, GitBranch, Info, ShieldCheck, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  OrchestrationBadge,
  OrchestrationField,
  OrchestrationOptionSelection,
  OrchestrationReadinessCard,
  type OrchestrationOption,
} from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";
import type { OrchestrationCapabilityItem } from "@/lib/api";

type RuntimeDraftLike = {
  agent_profile_id?: string;
  approval_policy?: string;
  trace_policy?: string;
  lifecycle_policy?: string;
  allowed_runtime_lanes?: string[];
  allowed_operations?: string[];
  blocked_operations?: string[];
  allowed_memory_scopes?: string[];
  allowed_context_sections?: string[];
  use_shared_contract?: boolean;
  can_delegate_to_agents?: boolean;
  allowed_delegate_agent_ids?: string[];
  max_delegate_calls_per_turn?: number;
  delegate_context_policy?: string;
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

export function OrchestrationRuntimePermissionWorkbench({
  runtimeDraft,
  patchRuntimeDraft,
  approvalPolicies,
  tracePolicies,
  approvalPolicyOptions,
  tracePolicyOptions,
  runtimeLaneOptions,
  runtimeLaneOptionItems,
  displayId,
  runtimeLanesSummary,
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
  runtimeLaneOptions: string[];
  runtimeLaneOptionItems: OrchestrationOption[];
  displayId: (value: unknown, fallback?: string) => string;
  runtimeLanesSummary: string;
  capabilityItems: OrchestrationCapabilityItem[];
  operationOptions: string[];
  operationOptionItems: OrchestrationOption[];
  overlapOps: string[];
  overlapSummary: string;
  allowedOpsCount: number;
  blockedOpsCount: number;
}) {
  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header>
          <strong>运行权限档案</strong>
          <OrchestrationBadge>{runtimeDraft.agent_profile_id || "草稿"}</OrchestrationBadge>
        </header>
        <div className="orchestration-identity-note">
          <span>权限事实源：AgentRuntimeProfile。</span>
          <strong>运行场景只定义准入场景，最终工具执行仍由当前回合 ResourcePolicy 与 OperationGate 决定。</strong>
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
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={runtimeLaneOptions}
          label="可承接运行场景权限"
          onChange={(values) => patchRuntimeDraft({ allowed_runtime_lanes: dedupe(values) })}
          options={runtimeLaneOptionItems}
          selectedValues={runtimeDraft.allowed_runtime_lanes ?? []}
        />
      </div>
      <aside className="boundary-card">
        <header><strong>运行权限摘要</strong></header>
        <div className="boundary-kv">
          <p><span>运行场景权限</span><strong>{runtimeLanesSummary}</strong></p>
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
  const capabilityCards = useMemo(() => capabilityItems, [capabilityItems]);
  const [selectedCapabilityId, setSelectedCapabilityId] = useState("");
  const selectedCapability = capabilityCards.find((item) => item.capability_id === selectedCapabilityId) ?? capabilityCards[0] ?? null;

  useEffect(() => {
    if (!capabilityCards.length) {
      setSelectedCapabilityId("");
      return;
    }
    setSelectedCapabilityId((current) => capabilityCards.some((item) => item.capability_id === current) ? current : capabilityCards[0].capability_id);
  }, [capabilityCards]);

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
    <section className="boundary-layer-grid boundary-layer-grid--wide orchestration-capability-permissions">
      <div className="boundary-card orchestration-capability-pools">
        <header>
          <strong>能力目录与授权快捷入口</strong>
          <OrchestrationBadge tone={overlapOps.length ? "danger" : "ok"}>{overlapOps.length ? "冲突" : "映射清晰"}</OrchestrationBadge>
        </header>
        <div className="orchestration-identity-note">
          <span>这里只是把能力映射到 operation 列表。</span>
          <strong>真正权限仍保存到 AgentRuntimeProfile 的允许/阻断操作。</strong>
        </div>
        {overlapOps.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{overlapOps.join(" / ")} 同时出现在允许和阻断列表。</div> : null}
        {!capabilityCards.length ? <div className="boundary-notice"><Info size={16} />能力目录尚未就绪，当前没有可展示的授权能力项。</div> : null}
        {(["skill", "tool", "mcp"] as CapabilityPool[]).map((pool) => {
          const cards = capabilityCards.filter((item) => item.capability_kind === pool || (pool === "tool" && item.capability_kind === "operation"));
          const allowedCount = cards.filter((item) => capabilityStatus(item.operation_ids, allowedSet, blockedSet) === "allowed").length;
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
                  const status = capabilityStatus(card.operation_ids, allowedSet, blockedSet);
                  const active = selectedCapability?.capability_id === card.capability_id;
                  return (
                    <article
                      className={[
                        "orchestration-capability-card",
                        `orchestration-capability-card--${status}`,
                        active ? "orchestration-capability-card--active" : "",
                      ].filter(Boolean).join(" ")}
                      key={card.capability_id}
                      onClick={() => setSelectedCapabilityId(card.capability_id)}
                    >
                      <div className="orchestration-capability-card__top">
                        <span>{card.source_label}</span>
                        <em>{statusLabel(status)}</em>
                      </div>
                      <strong>{card.title}</strong>
                      <div className="orchestration-capability-card__actions">
                        <button
                          className={status === "allowed" ? "is-active" : ""}
                          disabled={!card.operation_ids.length}
                          onClick={(event) => {
                            event.stopPropagation();
                            applyCapability(card.operation_ids, "allow");
                          }}
                          type="button"
                        >
                          <CheckCircle2 size={14} />加入允许
                        </button>
                        <button
                          className={status === "blocked" ? "is-danger-active" : ""}
                          disabled={!card.operation_ids.length}
                          onClick={(event) => {
                            event.stopPropagation();
                            applyCapability(card.operation_ids, "block");
                          }}
                          type="button"
                        >
                          <XCircle size={14} />加入阻断
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
      <aside className="boundary-card orchestration-capability-inspector">
        <header><strong>能力注册说明</strong>{selectedCapability ? <OrchestrationBadge tone={selectedCapability.risk_tone === "danger" ? "danger" : selectedCapability.risk_tone === "warn" ? "warn" : selectedCapability.risk_tone === "ok" ? "ok" : "neutral"}>{statusLabel(capabilityStatus(selectedCapability.operation_ids, allowedSet, blockedSet))}</OrchestrationBadge> : null}</header>
        {selectedCapability ? (
          <>
            <div className="orchestration-capability-inspector__hero">
              <span>{selectedCapability.source_label}</span>
              <h4>{selectedCapability.title}</h4>
              <p>{selectedCapability.description}</p>
            </div>
            <div className="boundary-kv">
              <p><span>来源</span><strong>{selectedCapability.source_detail}</strong></p>
              <p><span>运行操作映射</span><strong>{selectedCapability.operation_ids.length ? selectedCapability.operation_ids.map((item) => displayId(item)).join(" / ") : "未绑定运行操作"}</strong></p>
              <p><span>风险</span><strong>{selectedCapability.risk_label}</strong></p>
              <p><span>允许</span><strong>{allowedOpsCount}</strong></p>
              <p><span>阻断</span><strong>{blockedOpsCount}</strong></p>
              <p><span>冲突</span><strong>{overlapSummary}</strong></p>
            </div>
            <section className="orchestration-capability-detail-block">
              <strong>风险与限制</strong>
              <div>
                {selectedCapability.risk_items.length ? selectedCapability.risk_items.map((item, index) => <span key={`${item}-${index}`}>{item}</span>) : <span>注册信息不足</span>}
              </div>
            </section>
            <section className="orchestration-capability-detail-block">
              <strong>能力注册元数据</strong>
              <div>
                {selectedCapability.metadata.map((item) => <p key={item.label}><span>{item.label}</span><b>{item.value}</b></p>)}
              </div>
            </section>
            <div className="orchestration-capability-inspector__actions">
              <button disabled={!selectedCapability.operation_ids.length} onClick={() => applyCapability(selectedCapability.operation_ids, "allow")} type="button"><CheckCircle2 size={14} />加入允许操作</button>
              <button disabled={!selectedCapability.operation_ids.length} onClick={() => applyCapability(selectedCapability.operation_ids, "block")} type="button"><XCircle size={14} />加入阻断操作</button>
            </div>
          </>
        ) : <div className="boundary-empty">请选择一个能力卡片查看来源、风险和说明。</div>}
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
  openLayer,
}: {
  agentDraft: AgentDraftLike;
  runtimeDraft: RuntimeDraftLike;
  runtimeSummary: string;
  operationSummary: string;
  memorySummary: string;
  contextSummary: string;
  collaborationSummary: string;
  openLayer: (layer: "identity" | "runtime_permissions" | "context_memory" | "collaboration" | "diagnostics") => void;
}) {
  const cards = [
    { label: "Agent 身份", value: agentDraft.agent_name || agentDraft.agent_id || "未配置", ready: Boolean(agentDraft.agent_id && agentDraft.agent_name), layer: "identity" as const },
    { label: "运行场景", value: runtimeSummary, ready: Boolean((runtimeDraft.allowed_runtime_lanes ?? []).length), layer: "runtime_permissions" as const },
    { label: "运行操作", value: operationSummary, ready: Boolean((runtimeDraft.allowed_operations ?? []).length), layer: "runtime_permissions" as const },
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
          <p><span>场景目录</span><strong>RuntimeLaneRegistry</strong></p>
          <p><span>最终执行</span><strong>ResourcePolicy / OperationGate</strong></p>
        </div>
      </aside>
    </section>
  );
}

export function OrchestrationDiagnosticsWorkbench({
  eligibilityChecks,
  overlapOps,
  runtimeLaneDiagnostics,
  capabilityItemsCount,
}: {
  eligibilityChecks: Array<{ label: string; value: string; ready: boolean }>;
  overlapOps: string[];
  runtimeLaneDiagnostics?: Record<string, unknown>;
  capabilityItemsCount: number;
}) {
  const profileUnregistered = Array.isArray(runtimeLaneDiagnostics?.profile_unregistered_lanes)
    ? runtimeLaneDiagnostics?.profile_unregistered_lanes as string[]
    : [];
  const taskGraphUnregistered = Array.isArray(runtimeLaneDiagnostics?.task_graph_unregistered_lanes)
    ? runtimeLaneDiagnostics?.task_graph_unregistered_lanes as string[]
    : [];

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
        </div>
        {overlapOps.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />允许和阻断操作冲突：{overlapOps.join(" / ")}</div> : null}
      </div>
      <aside className="boundary-card">
        <header><strong>运行场景注册诊断</strong></header>
        <div className="boundary-kv">
          <p><span>Profile 未注册场景</span><strong>{profileUnregistered.length ? profileUnregistered.join(" / ") : "无"}</strong></p>
          <p><span>TaskGraph 未注册场景</span><strong>{taskGraphUnregistered.length ? taskGraphUnregistered.join(" / ") : "无"}</strong></p>
          <p><span>权威源</span><strong>{String(runtimeLaneDiagnostics?.authority || "orchestration.runtime_lane_registry")}</strong></p>
        </div>
      </aside>
    </section>
  );
}
