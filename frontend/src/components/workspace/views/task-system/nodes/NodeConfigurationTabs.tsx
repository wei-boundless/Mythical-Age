"use client";

import { AlertTriangle, Cpu, GitBranch, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";

import {
  TaskSystemField,
  TaskSystemSelectField,
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { JsonObjectEditor } from "@/components/workspace/views/task-system/managementPrimitives";
import type {
  OrchestrationCapabilityItem,
  TaskNodeConfigurationSpec,
} from "@/lib/api";

import { capabilityLabel } from "./nodeConfigurationModel";

export function NodeDetailTab({
  draft,
  environmentOptions,
  onChange,
}: {
  draft: TaskNodeConfigurationSpec;
  environmentOptions: Array<{ value: string; label: string }>;
  onChange: (draft: TaskNodeConfigurationSpec) => void;
}) {
  const environmentScope = new Set(draft.environment_scope ?? []);
  function toggleEnvironment(value: string, enabled: boolean) {
    const next = new Set(environmentScope);
    if (enabled) next.add(value);
    else next.delete(value);
    onChange({ ...draft, environment_scope: Array.from(next) });
  }
  return (
    <section className="task-system-inspector-section">
      <header><Cpu size={15} /><strong>角色与职责</strong><span>写给 agent 的节点角色 prompt</span></header>
      <div className="boundary-form">
        <TaskSystemField label="节点配置 ID"><input value={draft.node_config_id} onChange={(event) => onChange({ ...draft, node_config_id: event.target.value })} /></TaskSystemField>
        <TaskSystemField label="名称"><input value={draft.title} onChange={(event) => onChange({ ...draft, title: event.target.value })} /></TaskSystemField>
        <TaskSystemSelectField label="节点类型" value={draft.node_kind || "agent"} options={["agent", "coordinator", "review_gate", "tool", "manual_gate", "runtime_monitor"]} onChange={(node_kind) => onChange({ ...draft, node_kind })} />
        <label className="boundary-check"><input checked={draft.enabled !== false} onChange={(event) => onChange({ ...draft, enabled: event.target.checked })} type="checkbox" />启用节点配置</label>
        <TaskSystemField label="说明" wide><textarea value={draft.description || ""} onChange={(event) => onChange({ ...draft, description: event.target.value })} /></TaskSystemField>
        <TaskSystemField label="适用环境" wide>
          <div className="task-system-checkbox-stack">
            <label className="boundary-check">
              <input
                checked={(draft.environment_scope ?? []).length === 0}
                onChange={(event) => {
                  if (event.target.checked) onChange({ ...draft, environment_scope: [] });
                }}
                type="checkbox"
              />
              通用节点配置
            </label>
            {environmentOptions.map((item) => (
              <label className="boundary-check" key={item.value}>
                <input
                  checked={environmentScope.has(item.value)}
                  onChange={(event) => toggleEnvironment(item.value, event.target.checked)}
                  type="checkbox"
                />
                {item.label}
              </label>
            ))}
          </div>
        </TaskSystemField>
        <TaskSystemField label="角色 Prompt" wide>
          <textarea
            className="task-system-role-prompt"
            value={draft.role_prompt || ""}
            onChange={(event) => onChange({ ...draft, role_prompt: event.target.value })}
          />
        </TaskSystemField>
      </div>
    </section>
  );
}

export function NodeExecutionTab({
  agentOptions,
  draft,
  onChange,
  profileOptions,
}: {
  agentOptions: Array<{ value: string; label: string }>;
  draft: TaskNodeConfigurationSpec;
  onChange: (draft: TaskNodeConfigurationSpec) => void;
  profileOptions: string[];
}) {
  const executorRef = draft.executor_ref ?? {};
  const [advancedOpen, setAdvancedOpen] = useState(false);
  function patchExecutor(patch: Record<string, unknown>) {
    onChange({ ...draft, executor_ref: { ...executorRef, ...patch } });
  }
  return (
    <div className="task-system-inspector-stack">
      <section className="task-system-inspector-section">
        <header><GitBranch size={15} /><strong>执行者引用</strong><span>只引用 agent 和 runtime profile</span></header>
        <div className="boundary-form">
          <TaskSystemField label="Agent">
            <select value={String(executorRef.agent_id ?? "")} onChange={(event) => patchExecutor({ agent_id: event.target.value })}>
              <option value="">不绑定 Agent</option>
              {agentOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </TaskSystemField>
          <TaskSystemField label="运行档案">
            <select value={String(executorRef.agent_profile_id ?? "")} onChange={(event) => patchExecutor({ agent_profile_id: event.target.value })}>
              <option value="">不绑定运行档案</option>
              {profileOptions.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </TaskSystemField>
          <TaskSystemSelectField
            label="选择策略"
            value={String(executorRef.agent_selection_policy ?? "explicit_agent")}
            options={["explicit_agent", "profile_match", "orchestration_default"]}
            onChange={(agent_selection_policy) => patchExecutor({ agent_selection_policy })}
          />
        </div>
      </section>
      <section className="task-system-inspector-section">
        <header><Cpu size={15} /><strong>模型要求</strong><span>能力、预算和流式约束</span></header>
        <div className="boundary-form">
          <JsonObjectEditor label="模型要求" value={draft.model_requirements ?? {}} onChange={(model_requirements) => onChange({ ...draft, model_requirements })} />
          <button
            aria-expanded={advancedOpen}
            className="task-system-advanced-toggle"
            onClick={() => setAdvancedOpen((current) => !current)}
            type="button"
          >
            {advancedOpen ? "收起高级执行者引用" : "高级执行者引用"}
          </button>
          {advancedOpen ? (
            <div className="task-system-advanced-details">
            <JsonObjectEditor label="执行者引用 JSON" value={executorRef} onChange={(executor_ref) => onChange({ ...draft, executor_ref })} />
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

export function NodeContractTab({
  contractFamilies,
  contractOptions,
  draft,
  onChange,
}: {
  contractFamilies: Array<Record<string, unknown>>;
  contractOptions: string[];
  draft: TaskNodeConfigurationSpec;
  onChange: (draft: TaskNodeConfigurationSpec) => void;
}) {
  const bindings = draft.contract_bindings ?? {};
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const familyOptions = contractFamilies.map((item) => ({
    value: String(item.family_id ?? ""),
    label: String(item.title_zh ?? item.family_id ?? ""),
    purpose: String(item.purpose ?? ""),
  })).filter((item) => item.value);
  function patchBinding(key: string, value: unknown) {
    onChange({ ...draft, contract_bindings: { ...bindings, [key]: value } });
  }
  return (
    <section className="task-system-inspector-section">
      <header><ShieldCheck size={15} /><strong>节点输出协议</strong><span>优先选择复用契约族，只在高级区覆盖具体契约</span></header>
      <div className="boundary-form">
        <TaskSystemField label="复用契约族">
          <select value={String(bindings.contract_family_id ?? "")} onChange={(event) => patchBinding("contract_family_id", event.target.value)}>
            <option value="">按任务图关系边决定</option>
            {familyOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </TaskSystemField>
        <TaskSystemField label="产物/裁决类型">
          <input
            placeholder="chapter_draft / review_verdict / memory_update"
            value={String(bindings.artifact_type ?? "")}
            onChange={(event) => patchBinding("artifact_type", event.target.value)}
          />
        </TaskSystemField>
        <TaskSystemField label="审核裁决字段">
          <input
            placeholder="verdict / review_verdict"
            value={String(bindings.verdict_key ?? "")}
            onChange={(event) => patchBinding("verdict_key", event.target.value)}
          />
        </TaskSystemField>
        <TaskSystemField label="质量/完成标准">
          <input
            placeholder="节点输出必须满足的最低标准"
            value={String(bindings.quality_bar ?? "")}
            onChange={(event) => patchBinding("quality_bar", event.target.value)}
          />
        </TaskSystemField>
        <button
          aria-expanded={advancedOpen}
          className="task-system-advanced-toggle boundary-field--wide"
          onClick={() => setAdvancedOpen((current) => !current)}
          type="button"
        >
          {advancedOpen ? "收起高级契约覆盖" : "高级契约覆盖"}
        </button>
        {advancedOpen ? (
          <div className="task-system-advanced-details boundary-field--wide">
          <div className="boundary-form">
            <OptionalContractSelect label="输入协议覆盖" value={String(bindings.input_contract_id ?? "")} options={contractOptions} onChange={(value) => patchBinding("input_contract_id", value)} />
            <OptionalContractSelect label="输出协议覆盖" value={String(bindings.output_contract_id ?? "")} options={contractOptions} onChange={(value) => patchBinding("output_contract_id", value)} />
            <OptionalContractSelect label="节点执行协议覆盖" value={String(bindings.node_contract_id ?? "")} options={contractOptions} onChange={(value) => patchBinding("node_contract_id", value)} />
            <JsonObjectEditor label="契约覆盖 JSON" value={bindings} onChange={(contract_bindings) => onChange({ ...draft, contract_bindings })} />
          </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function OptionalContractSelect({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
}) {
  return (
    <TaskSystemField label={label}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">不绑定</option>
        {options.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
    </TaskSystemField>
  );
}

export function NodeCapabilityTab({
  capabilityItems,
  draft,
  onChange,
}: {
  capabilityItems: OrchestrationCapabilityItem[];
  draft: TaskNodeConfigurationSpec;
  onChange: (draft: TaskNodeConfigurationSpec) => void;
}) {
  const toolPolicy = draft.tool_policy ?? {};
  const operationSet = new Set((Array.isArray(toolPolicy.allowed_operations) ? toolPolicy.allowed_operations : []).map((item) => String(item)));
  function toggleOperations(item: OrchestrationCapabilityItem) {
    const next = new Set(operationSet);
    for (const operationId of item.operation_ids ?? []) {
      if (next.has(operationId)) next.delete(operationId);
      else next.add(operationId);
    }
    onChange({ ...draft, tool_policy: { ...toolPolicy, allowed_operations: Array.from(next) } });
  }
  return (
    <div className="task-system-inspector-stack">
      <section className="task-system-inspector-section">
        <header><Sparkles size={15} /><strong>能力候选</strong><span>{capabilityItems.length} capabilities</span></header>
        <div className="task-system-capability-grid">
          {capabilityItems.slice(0, 36).map((item) => {
            const active = (item.operation_ids ?? []).some((operationId) => operationSet.has(operationId));
            return (
              <button
                className={active ? "task-system-capability-chip task-system-capability-chip--active" : "task-system-capability-chip"}
                key={item.capability_id}
                onClick={() => toggleOperations(item)}
                type="button"
              >
                <strong>{capabilityLabel(item)}</strong>
                <span>{item.operation_ids?.join(", ") || item.source_label}</span>
              </button>
            );
          })}
          {!capabilityItems.length ? <div className="boundary-empty">暂未加载能力候选。刷新后会从编排能力目录读取。</div> : null}
        </div>
      </section>
      <section className="task-system-inspector-section">
        <header><ShieldCheck size={15} /><strong>权限边界</strong><span>工具、记忆、产物、失败和人工门</span></header>
        <div className="boundary-form">
          <JsonObjectEditor label="工具策略" value={draft.tool_policy ?? {}} onChange={(tool_policy) => onChange({ ...draft, tool_policy })} />
          <JsonObjectEditor label="记忆策略" value={draft.memory_policy ?? {}} onChange={(memory_policy) => onChange({ ...draft, memory_policy })} />
          <JsonObjectEditor label="产物策略" value={draft.artifact_policy ?? {}} onChange={(artifact_policy) => onChange({ ...draft, artifact_policy })} />
          <JsonObjectEditor label="失败策略" value={draft.failure_policy ?? {}} onChange={(failure_policy) => onChange({ ...draft, failure_policy })} />
          <JsonObjectEditor label="人工门控策略" value={draft.human_gate_policy ?? {}} onChange={(human_gate_policy) => onChange({ ...draft, human_gate_policy })} />
          <JsonObjectEditor label="扩展元数据" value={draft.metadata ?? {}} onChange={(metadata) => onChange({ ...draft, metadata })} />
        </div>
      </section>
    </div>
  );
}

export function NodePreviewTab({
  draftIssues,
  draftUsage,
  environmentOptions,
  onPreview,
  preview,
  previewEnvironmentId,
  saving,
  setPreviewEnvironmentId,
}: {
  draftIssues: Array<Record<string, unknown>>;
  draftUsage: Array<Record<string, unknown>>;
  environmentOptions: Array<{ value: string; label: string }>;
  onPreview: () => void;
  preview: Record<string, unknown> | null;
  previewEnvironmentId: string;
  saving: boolean;
  setPreviewEnvironmentId: (value: string) => void;
}) {
  return (
    <div className="task-system-inspector-stack">
      <section className="task-system-inspector-section">
        <header><Cpu size={15} /><strong>装配预览</strong><span>由后端合成 runtime start packet 预览</span></header>
        <div className="boundary-form">
          <TaskSystemField label="预览任务环境">
            <select value={previewEnvironmentId} onChange={(event) => setPreviewEnvironmentId(event.target.value)}>
              <option value="">使用节点默认环境</option>
              {environmentOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </TaskSystemField>
          <div className="boundary-actions">
            <TaskSystemToolbarButton disabled={saving} onClick={onPreview} variant="primary"><Cpu size={14} />生成预览</TaskSystemToolbarButton>
          </div>
        </div>
        <pre className="task-system-runtime-preview">{preview ? JSON.stringify(preview, null, 2) : "尚未生成装配预览。"}</pre>
      </section>
      <section className="task-system-inspector-section">
        <header><AlertTriangle size={15} /><strong>引用和问题</strong><span>{draftUsage.length} references / {draftIssues.length} issues</span></header>
        <div className="task-system-usage-list">
          {draftUsage.map((item, index) => (
            <article className="task-system-usage-row" key={`${String(item.graph_id ?? "")}-${String(item.node_id ?? "")}-${index}`}>
              <strong>{String(item.graph_id ?? "")}</strong>
              <span>{String(item.node_id ?? "")}</span>
            </article>
          ))}
          {draftIssues.map((item, index) => (
            <article className="task-system-usage-row task-system-usage-row--warn" key={`${String(item.code ?? "")}-${index}`}>
              <strong>{String(item.code ?? "")}</strong>
              <span>{String(item.message ?? "")}</span>
            </article>
          ))}
          {!draftUsage.length && !draftIssues.length ? <div className="boundary-empty">当前节点配置没有引用问题。</div> : null}
        </div>
      </section>
    </div>
  );
}
