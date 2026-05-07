"use client";

import { AlertTriangle } from "lucide-react";

import {
  OrchestrationBadge,
  OrchestrationField,
  OrchestrationReadinessCard,
  OrchestrationSuggestionGrid,
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
  output_contracts_text?: string;
};

type AgentDraftLike = {
  task_scope_text?: string;
  managed_object_types_text?: string;
  capability_refs_text?: string;
};

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
  taskModeOptions,
  runtimeLaneOptions,
  addRuntimeLine,
  displayId,
  taskModesSummary,
  runtimeLanesSummary,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  approvalPolicies: string[];
  tracePolicies: string[];
  taskModeOptions: string[];
  runtimeLaneOptions: string[];
  addRuntimeLine: (field: keyof RuntimeDraftLike, value: string) => void;
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
              {approvalPolicies.map((item) => <option key={item} value={item}>{displayId(item)}</option>)}
            </select>
          </OrchestrationField>
          <OrchestrationField label="追踪策略">
            <select value={runtimeDraft.trace_policy} onChange={(event) => patchRuntimeDraft({ trace_policy: event.target.value })}>
              {tracePolicies.map((item) => <option key={item} value={item}>{displayId(item)}</option>)}
            </select>
          </OrchestrationField>
          <OrchestrationField label="生命周期"><input value={runtimeDraft.lifecycle_policy || ""} onChange={(event) => patchRuntimeDraft({ lifecycle_policy: event.target.value })} /></OrchestrationField>
          <OrchestrationField label="允许任务模式" wide><textarea value={runtimeDraft.allowed_task_modes_text || ""} onChange={(event) => patchRuntimeDraft({ allowed_task_modes_text: event.target.value })} /></OrchestrationField>
          <OrchestrationField label="允许运行通道" wide><textarea value={runtimeDraft.allowed_runtime_lanes_text || ""} onChange={(event) => patchRuntimeDraft({ allowed_runtime_lanes_text: event.target.value })} /></OrchestrationField>
        </div>
        <OrchestrationSuggestionGrid items={taskModeOptions} onAdd={(item) => addRuntimeLine("allowed_task_modes_text", item)} />
        <OrchestrationSuggestionGrid items={runtimeLaneOptions} onAdd={(item) => addRuntimeLine("allowed_runtime_lanes_text", item)} />
      </div>
      <aside className="boundary-card">
        <header><strong>运行摘要</strong></header>
        <div className="boundary-kv">
          <p><span>任务模式</span><strong>{taskModesSummary}</strong></p>
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
  addRuntimeLine,
  allowedOpsCount,
  blockedOpsCount,
  overlapSummary,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  overlapOps: string[];
  operationOptions: string[];
  addRuntimeLine: (field: keyof RuntimeDraftLike, value: string) => void;
  allowedOpsCount: number;
  blockedOpsCount: number;
  overlapSummary: string;
}) {
  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header><strong>权限与能力边界</strong><OrchestrationBadge tone={overlapOps.length ? "danger" : "ok"}>{overlapOps.length ? "冲突" : "清晰"}</OrchestrationBadge></header>
        {overlapOps.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{overlapOps.join(" / ")} 同时出现在允许和阻断列表。</div> : null}
        <div className="boundary-form">
          <OrchestrationField label="允许操作" wide><textarea value={runtimeDraft.allowed_operations_text || ""} onChange={(event) => patchRuntimeDraft({ allowed_operations_text: event.target.value })} /></OrchestrationField>
          <OrchestrationField label="阻断操作" wide><textarea value={runtimeDraft.blocked_operations_text || ""} onChange={(event) => patchRuntimeDraft({ blocked_operations_text: event.target.value })} /></OrchestrationField>
        </div>
        <OrchestrationSuggestionGrid items={operationOptions} onAdd={(item) => addRuntimeLine("allowed_operations_text", item)} />
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
  outputContractOptions,
  addRuntimeLine,
  memorySummary,
  contextSummary,
  outputSummary,
  outputCount,
}: {
  runtimeDraft: RuntimeDraftLike;
  patchRuntimeDraft: (patch: Partial<RuntimeDraftLike>) => void;
  memoryScopeOptions: string[];
  contextSectionOptions: string[];
  outputContractOptions: string[];
  addRuntimeLine: (field: keyof RuntimeDraftLike, value: string) => void;
  memorySummary: string;
  contextSummary: string;
  outputSummary: string;
  outputCount: number;
}) {
  return (
    <section className="boundary-layer-grid boundary-layer-grid--wide">
      <div className="boundary-card">
        <header><strong>记忆、上下文、输出边界</strong><OrchestrationBadge>{outputCount} 项输出</OrchestrationBadge></header>
        <div className="boundary-form">
          <OrchestrationField label="允许记忆范围" wide><textarea value={runtimeDraft.allowed_memory_scopes_text || ""} onChange={(event) => patchRuntimeDraft({ allowed_memory_scopes_text: event.target.value })} /></OrchestrationField>
          <OrchestrationField label="允许上下文段" wide><textarea value={runtimeDraft.allowed_context_sections_text || ""} onChange={(event) => patchRuntimeDraft({ allowed_context_sections_text: event.target.value })} /></OrchestrationField>
          <OrchestrationField label="输出契约" wide><textarea value={runtimeDraft.output_contracts_text || ""} onChange={(event) => patchRuntimeDraft({ output_contracts_text: event.target.value })} /></OrchestrationField>
        </div>
        <OrchestrationSuggestionGrid items={memoryScopeOptions} onAdd={(item) => addRuntimeLine("allowed_memory_scopes_text", item)} />
        <OrchestrationSuggestionGrid items={contextSectionOptions} onAdd={(item) => addRuntimeLine("allowed_context_sections_text", item)} />
        <OrchestrationSuggestionGrid items={outputContractOptions} onAdd={(item) => addRuntimeLine("output_contracts_text", item)} />
      </div>
      <aside className="boundary-card">
        <header><strong>边界摘要</strong></header>
        <div className="boundary-kv">
          <p><span>记忆</span><strong>{memorySummary}</strong></p>
          <p><span>上下文</span><strong>{contextSummary}</strong></p>
          <p><span>输出</span><strong>{outputSummary}</strong></p>
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
