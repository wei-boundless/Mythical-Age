"use client";

import { AlertTriangle } from "lucide-react";

import {
  OrchestrationBadge,
  OrchestrationField,
  OrchestrationOptionSelection,
  OrchestrationReadinessCard,
  OrchestrationSuggestionGrid,
  type OrchestrationOption,
} from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";

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
};

type AgentDraftLike = {
  task_scope_text?: string;
  managed_object_types_text?: string;
  capability_refs_text?: string;
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

export function OrchestrationScopeWorkbench({
  agentDraft,
  patchAgentDraft,
  taskScopeCount,
  scopeSuggestions,
  addAgentLine,
  taskScopeSummary,
  managedObjectsSummary,
  capabilityRefsSummary,
}: {
  agentDraft: AgentDraftLike;
  patchAgentDraft: (patch: Partial<AgentDraftLike>) => void;
  taskScopeCount: number;
  scopeSuggestions: string[];
  addAgentLine: (field: "task_scope_text" | "managed_object_types_text" | "capability_refs_text", value: string) => void;
  taskScopeSummary: string;
  managedObjectsSummary: string;
  capabilityRefsSummary: string;
}) {
  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header><strong>固定职责与任务覆盖范围</strong><OrchestrationBadge>{taskScopeCount} 项</OrchestrationBadge></header>
        <div className="boundary-form">
          <OrchestrationField label="任务覆盖范围" wide><textarea value={agentDraft.task_scope_text || ""} onChange={(event) => patchAgentDraft({ task_scope_text: event.target.value })} /></OrchestrationField>
          <OrchestrationField label="可管理对象类型" wide><textarea value={agentDraft.managed_object_types_text || ""} onChange={(event) => patchAgentDraft({ managed_object_types_text: event.target.value })} /></OrchestrationField>
          <OrchestrationField label="能力引用" wide><textarea value={agentDraft.capability_refs_text || ""} onChange={(event) => patchAgentDraft({ capability_refs_text: event.target.value })} /></OrchestrationField>
        </div>
        <OrchestrationSuggestionGrid items={scopeSuggestions} onAdd={(item) => addAgentLine("task_scope_text", item)} />
      </div>
      <aside className="boundary-card">
        <header><strong>覆盖摘要</strong></header>
        <div className="boundary-kv">
          <p><span>任务范围</span><strong>{taskScopeSummary}</strong></p>
          <p><span>管理对象</span><strong>{managedObjectsSummary}</strong></p>
          <p><span>能力</span><strong>{capabilityRefsSummary}</strong></p>
        </div>
      </aside>
    </section>
  );
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
  displayId,
  taskModesSummary,
  runtimeLanesSummary,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  approvalPolicies: string[];
  tracePolicies: string[];
  approvalPolicyOptions: OrchestrationOption[];
  tracePolicyOptions: OrchestrationOption[];
  taskModeOptions: string[];
  runtimeLaneOptions: string[];
  taskModeOptionItems: OrchestrationOption[];
  runtimeLaneOptionItems: OrchestrationOption[];
  displayId: (value: unknown, fallback?: string) => string;
  taskModesSummary: string;
  runtimeLanesSummary: string;
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
      </div>
      <aside className="boundary-card">
        <header><strong>运行摘要</strong></header>
        <div className="boundary-kv">
          <p><span>任务范围</span><strong>{taskModesSummary}</strong></p>
          <p><span>运行通道</span><strong>{runtimeLanesSummary}</strong></p>
        </div>
      </aside>
    </section>
  );
}

export function OrchestrationPermissionsWorkbench({
  runtimeDraft,
  patchRuntimeDraft,
  overlapOps,
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
  operationOptions: string[];
  operationOptionItems: OrchestrationOption[];
  displayId: (value: unknown, fallback?: string) => string;
  allowedOpsCount: number;
  blockedOpsCount: number;
  overlapSummary: string;
}) {
  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header><strong>权限与能力边界</strong><OrchestrationBadge tone={overlapOps.length ? "danger" : "ok"}>{overlapOps.length ? "冲突" : "清晰"}</OrchestrationBadge></header>
        {overlapOps.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{overlapOps.join(" / ")} 同时出现在允许和阻断列表。</div> : null}
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={operationOptions}
          label="允许操作"
          onChange={(values) => patchRuntimeDraft({ allowed_operations_text: serializeList(values) })}
          options={operationOptionItems}
          selectedValues={splitList(runtimeDraft.allowed_operations_text)}
        />
        <OrchestrationOptionSelection
          displayId={displayId}
          fallbackOptions={operationOptions}
          label="阻断操作"
          onChange={(values) => patchRuntimeDraft({ blocked_operations_text: serializeList(values) })}
          options={operationOptionItems}
          selectedValues={splitList(runtimeDraft.blocked_operations_text)}
        />
      </div>
      <aside className="boundary-card">
        <header><strong>权限摘要</strong></header>
        <div className="boundary-kv">
          <p><span>允许</span><strong>{allowedOpsCount}</strong></p>
          <p><span>阻断</span><strong>{blockedOpsCount}</strong></p>
          <p><span>冲突</span><strong>{overlapSummary}</strong></p>
        </div>
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
      </div>
      <aside className="boundary-card">
        <header><strong>边界摘要</strong></header>
        <div className="boundary-kv">
          <p><span>记忆</span><strong>{memorySummary}</strong></p>
          <p><span>上下文</span><strong>{contextSummary}</strong></p>
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
