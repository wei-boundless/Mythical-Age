"use client";

import { AlertTriangle, ClipboardList, Copy, Database, GitBranch, Plus, ShieldCheck, Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import {
  TaskSystemField,
  TaskSystemSelectField,
  TaskSystemToolbarButton,
  taskSystemOptionLabel,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { JsonObjectEditor, splitList } from "@/components/workspace/views/task-system/managementPrimitives";
import type {
  AcceptanceRule,
  ArtifactRequirement,
  ContractField,
  ContractSpec,
  ContractValidationIssue,
  RuntimeRequirement,
} from "@/lib/api";

export function contractKindLabel(value: string) {
  const labels: Record<string, string> = {
    global_task: "全局任务",
    workflow: "单任务 Workflow",
    workflow_step: "Workflow 步骤",
    node_execution: "协调节点执行",
    edge_handoff: "边交接",
    runtime: "运行要求",
    acceptance: "验收",
    failure: "失败处理",
    human_gate: "人工门控",
    final_output: "最终输出",
  };
  return labels[value] ? `${labels[value]} · ${value}` : taskSystemOptionLabel(value);
}

function emptyField(index: number): ContractField {
  return {
    field_id: `field_${index}`,
    title_zh: "新字段",
    field_type: "string",
    required: true,
    description: "",
    default_value: "",
    schema: {},
    source_hint: "user_input",
    visibility: "model_visible",
  };
}

function emptyArtifactRequirement(index: number): ArtifactRequirement {
  return {
    requirement_id: `artifact_${index}`,
    title_zh: "新产物要求",
    artifact_type: "markdown",
    required: true,
    description: "",
    naming_rule: "",
    storage_policy: "artifact_ref",
    metadata: {},
  };
}

function emptyAcceptanceRule(index: number): AcceptanceRule {
  return {
    rule_id: `rule_${index}`,
    title_zh: "新验收规则",
    rule_type: "required_field_present",
    severity: "error",
    target_field: "",
    criteria: "",
    config: {},
  };
}

function emptyRuntimeRequirement(index: number): RuntimeRequirement {
  return {
    requirement_id: `runtime_${index}`,
    title_zh: "新运行要求",
    requirement_type: "capability",
    required: true,
    value: "",
    config: {},
  };
}

function usageLabel(value: unknown) {
  const item = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return `${String(item.source_kind ?? "unknown")} / ${String(item.source_id ?? "")} / ${String(item.field ?? "")}`;
}

export function ContractOverviewTab({
  draft,
  kindOptions,
  onChange,
}: {
  draft: ContractSpec;
  kindOptions: string[];
  onChange: (draft: ContractSpec) => void;
}) {
  return (
    <section className="task-system-inspector-section">
      <header><ClipboardList size={15} /><strong>身份与用途</strong><span>契约主数据</span></header>
      <div className="boundary-form">
        <TaskSystemField label="契约 ID"><input value={draft.contract_id} onChange={(event) => onChange({ ...draft, contract_id: event.target.value })} /></TaskSystemField>
        <TaskSystemSelectField label="契约类型" value={draft.contract_kind} options={kindOptions} onChange={(contract_kind) => onChange({ ...draft, contract_kind })} formatOption={contractKindLabel} />
        <TaskSystemField label="中文名称"><input value={draft.title_zh} onChange={(event) => onChange({ ...draft, title_zh: event.target.value })} /></TaskSystemField>
        <TaskSystemField label="英文名称"><input value={draft.title_en} onChange={(event) => onChange({ ...draft, title_en: event.target.value })} /></TaskSystemField>
        <TaskSystemField label="版本"><input value={draft.version} onChange={(event) => onChange({ ...draft, version: event.target.value })} /></TaskSystemField>
        <label className="boundary-check"><input checked={draft.enabled} onChange={(event) => onChange({ ...draft, enabled: event.target.checked })} type="checkbox" />启用契约</label>
        <TaskSystemField label="说明" wide><textarea value={draft.description} onChange={(event) => onChange({ ...draft, description: event.target.value })} /></TaskSystemField>
      </div>
    </section>
  );
}

export function ContractSchemaTab({
  draft,
  fieldTypeOptions,
  onChange,
  sourceHintOptions,
  visibilityOptions,
}: {
  draft: ContractSpec;
  fieldTypeOptions: string[];
  onChange: (draft: ContractSpec) => void;
  sourceHintOptions: string[];
  visibilityOptions: string[];
}) {
  return (
    <div className="task-system-inspector-stack">
      <ContractFieldEditor
        fields={draft.input_fields ?? []}
        icon={<Database size={15} />}
        onChange={(input_fields) => onChange({ ...draft, input_fields })}
        options={{ fieldTypeOptions, sourceHintOptions, visibilityOptions }}
        title="输入字段"
      />
      <ContractFieldEditor
        fields={draft.output_fields ?? []}
        icon={<Copy size={15} />}
        onChange={(output_fields) => onChange({ ...draft, output_fields })}
        options={{ fieldTypeOptions, sourceHintOptions, visibilityOptions }}
        title="输出字段"
      />
    </div>
  );
}

function ContractFieldEditor({
  fields,
  icon,
  onChange,
  options,
  title,
}: {
  fields: ContractField[];
  icon: ReactNode;
  onChange: (fields: ContractField[]) => void;
  options: { fieldTypeOptions: string[]; sourceHintOptions: string[]; visibilityOptions: string[] };
  title: string;
}) {
  function patch(index: number, patchValue: Partial<ContractField>) {
    onChange(fields.map((item, currentIndex) => currentIndex === index ? { ...item, ...patchValue } : item));
  }
  return (
    <section className="task-system-inspector-section">
      <header>{icon}<strong>{title}</strong><span>{fields.length} fields</span><TaskSystemToolbarButton onClick={() => onChange([...fields, emptyField(fields.length + 1)])}><Plus size={14} />新增</TaskSystemToolbarButton></header>
      <div className="task-system-structured-list">
        {fields.map((field, index) => (
          <article className="task-system-structured-row" key={`${field.field_id}-${index}`}>
            <div className="boundary-form">
              <TaskSystemField label="字段 ID"><input value={field.field_id} onChange={(event) => patch(index, { field_id: event.target.value })} /></TaskSystemField>
              <TaskSystemField label="名称"><input value={field.title_zh} onChange={(event) => patch(index, { title_zh: event.target.value })} /></TaskSystemField>
              <TaskSystemSelectField label="类型" value={field.field_type} options={options.fieldTypeOptions} onChange={(value) => patch(index, { field_type: value })} />
              <TaskSystemSelectField label="来源" value={field.source_hint} options={options.sourceHintOptions} onChange={(value) => patch(index, { source_hint: value })} />
              <TaskSystemSelectField label="可见性" value={field.visibility} options={options.visibilityOptions} onChange={(value) => patch(index, { visibility: value })} />
              <TaskSystemField label="默认值"><input value={String(field.default_value ?? "")} onChange={(event) => patch(index, { default_value: event.target.value })} /></TaskSystemField>
              <label className="boundary-check"><input checked={field.required} onChange={(event) => patch(index, { required: event.target.checked })} type="checkbox" />必填</label>
              <TaskSystemField label="说明" wide><textarea value={field.description} onChange={(event) => patch(index, { description: event.target.value })} /></TaskSystemField>
              <JsonObjectEditor label="字段 Schema" value={field.schema ?? {}} onChange={(schema) => patch(index, { schema })} rows={5} />
            </div>
            <div className="boundary-actions">
              <TaskSystemToolbarButton onClick={() => onChange([...fields, { ...field, field_id: `${field.field_id || "field"}_copy` }])}><Copy size={14} />复制</TaskSystemToolbarButton>
              <TaskSystemToolbarButton onClick={() => onChange(fields.filter((_, currentIndex) => currentIndex !== index))}><Trash2 size={14} />删除</TaskSystemToolbarButton>
            </div>
          </article>
        ))}
        {!fields.length ? <div className="boundary-empty">暂无字段。点击新增开始定义 Schema。</div> : null}
      </div>
    </section>
  );
}

export function ContractArtifactsTab({
  draft,
  onChange,
  ruleTypeOptions,
}: {
  draft: ContractSpec;
  onChange: (draft: ContractSpec) => void;
  ruleTypeOptions: string[];
}) {
  const fieldOptions = [...(draft.input_fields ?? []), ...(draft.output_fields ?? [])].map((field) => field.field_id).filter(Boolean);
  return (
    <div className="task-system-inspector-stack">
      <section className="task-system-inspector-section">
        <header><Database size={15} /><strong>产物要求</strong><span>{draft.artifact_requirements.length} artifacts</span><TaskSystemToolbarButton onClick={() => onChange({ ...draft, artifact_requirements: [...draft.artifact_requirements, emptyArtifactRequirement(draft.artifact_requirements.length + 1)] })}><Plus size={14} />新增</TaskSystemToolbarButton></header>
        <div className="task-system-structured-list">
          {draft.artifact_requirements.map((item, index) => (
            <article className="task-system-structured-row" key={`${item.requirement_id}-${index}`}>
              <div className="boundary-form">
                <TaskSystemField label="要求 ID"><input value={item.requirement_id} onChange={(event) => patchArtifact(draft, onChange, index, { requirement_id: event.target.value })} /></TaskSystemField>
                <TaskSystemField label="名称"><input value={item.title_zh} onChange={(event) => patchArtifact(draft, onChange, index, { title_zh: event.target.value })} /></TaskSystemField>
                <TaskSystemField label="类型"><input value={item.artifact_type} onChange={(event) => patchArtifact(draft, onChange, index, { artifact_type: event.target.value })} /></TaskSystemField>
                <TaskSystemSelectField label="存储策略" value={item.storage_policy} options={["artifact_ref", "inline_summary", "file_path", "formal_repository"]} onChange={(storage_policy) => patchArtifact(draft, onChange, index, { storage_policy })} />
                <TaskSystemField label="命名规则"><input value={item.naming_rule} onChange={(event) => patchArtifact(draft, onChange, index, { naming_rule: event.target.value })} /></TaskSystemField>
                <label className="boundary-check"><input checked={item.required} onChange={(event) => patchArtifact(draft, onChange, index, { required: event.target.checked })} type="checkbox" />必需产物</label>
                <TaskSystemField label="说明" wide><textarea value={item.description} onChange={(event) => patchArtifact(draft, onChange, index, { description: event.target.value })} /></TaskSystemField>
              </div>
              <div className="boundary-actions"><TaskSystemToolbarButton onClick={() => onChange({ ...draft, artifact_requirements: draft.artifact_requirements.filter((_, currentIndex) => currentIndex !== index) })}><Trash2 size={14} />删除</TaskSystemToolbarButton></div>
            </article>
          ))}
          {!draft.artifact_requirements.length ? <div className="boundary-empty">暂无产物要求。</div> : null}
        </div>
      </section>

      <section className="task-system-inspector-section">
        <header><ShieldCheck size={15} /><strong>验收规则</strong><span>{draft.acceptance_rules.length} rules</span><TaskSystemToolbarButton onClick={() => onChange({ ...draft, acceptance_rules: [...draft.acceptance_rules, emptyAcceptanceRule(draft.acceptance_rules.length + 1)] })}><Plus size={14} />新增</TaskSystemToolbarButton></header>
        <div className="task-system-structured-list">
          {draft.acceptance_rules.map((item, index) => (
            <article className="task-system-structured-row" key={`${item.rule_id}-${index}`}>
              <div className="boundary-form">
                <TaskSystemField label="规则 ID"><input value={item.rule_id} onChange={(event) => patchAcceptance(draft, onChange, index, { rule_id: event.target.value })} /></TaskSystemField>
                <TaskSystemField label="名称"><input value={item.title_zh} onChange={(event) => patchAcceptance(draft, onChange, index, { title_zh: event.target.value })} /></TaskSystemField>
                <TaskSystemSelectField label="规则类型" value={item.rule_type} options={ruleTypeOptions} onChange={(rule_type) => patchAcceptance(draft, onChange, index, { rule_type })} />
                <TaskSystemSelectField label="严重级别" value={item.severity} options={["error", "warning", "info"]} onChange={(severity) => patchAcceptance(draft, onChange, index, { severity })} />
                <TaskSystemSelectField label="目标字段" value={item.target_field} options={fieldOptions} onChange={(target_field) => patchAcceptance(draft, onChange, index, { target_field })} />
                <TaskSystemField label="判定标准" wide><textarea value={item.criteria} onChange={(event) => patchAcceptance(draft, onChange, index, { criteria: event.target.value })} /></TaskSystemField>
                <JsonObjectEditor label="规则配置" value={item.config ?? {}} onChange={(config) => patchAcceptance(draft, onChange, index, { config })} rows={5} />
              </div>
              <div className="boundary-actions"><TaskSystemToolbarButton onClick={() => onChange({ ...draft, acceptance_rules: draft.acceptance_rules.filter((_, currentIndex) => currentIndex !== index) })}><Trash2 size={14} />删除</TaskSystemToolbarButton></div>
            </article>
          ))}
          {!draft.acceptance_rules.length ? <div className="boundary-empty">暂无验收规则。</div> : null}
        </div>
      </section>
    </div>
  );
}

function patchArtifact(draft: ContractSpec, onChange: (draft: ContractSpec) => void, index: number, patch: Partial<ArtifactRequirement>) {
  onChange({ ...draft, artifact_requirements: draft.artifact_requirements.map((item, currentIndex) => currentIndex === index ? { ...item, ...patch } : item) });
}

function patchAcceptance(draft: ContractSpec, onChange: (draft: ContractSpec) => void, index: number, patch: Partial<AcceptanceRule>) {
  onChange({ ...draft, acceptance_rules: draft.acceptance_rules.map((item, currentIndex) => currentIndex === index ? { ...item, ...patch } : item) });
}

export function ContractRuntimeTab({ draft, onChange }: { draft: ContractSpec; onChange: (draft: ContractSpec) => void }) {
  function patchPolicy<K extends "context_visibility_policy" | "handoff_policy" | "failure_policy" | "human_gate_policy">(key: K, patch: Partial<ContractSpec[K]>) {
    onChange({ ...draft, [key]: { ...(draft[key] as Record<string, unknown>), ...patch } });
  }
  return (
    <div className="task-system-inspector-stack">
      <section className="task-system-inspector-section">
        <header><GitBranch size={15} /><strong>上下文与交接</strong><span>可见性、交接和失败边界</span></header>
        <div className="boundary-form">
          <TaskSystemSelectField label="主会话历史" value={draft.context_visibility_policy.main_session_history} options={["none", "summary", "full"]} onChange={(value) => patchPolicy("context_visibility_policy", { main_session_history: value })} />
          <TaskSystemSelectField label="上游输出" value={draft.context_visibility_policy.upstream_outputs} options={["none", "summary", "full", "refs_only"]} onChange={(value) => patchPolicy("context_visibility_policy", { upstream_outputs: value })} />
          <TaskSystemSelectField label="同级节点" value={draft.context_visibility_policy.sibling_nodes} options={["hidden", "status_only", "summary", "full"]} onChange={(value) => patchPolicy("context_visibility_policy", { sibling_nodes: value })} />
          <TaskSystemSelectField label="产物访问" value={draft.context_visibility_policy.artifact_access} options={["none", "refs_only", "summary", "full"]} onChange={(value) => patchPolicy("context_visibility_policy", { artifact_access: value })} />
          <TaskSystemSelectField label="交接模式" value={draft.handoff_policy.handoff_mode} options={["structured_handoff", "structured_packet", "summary_and_refs", "notification_only"]} onChange={(value) => patchPolicy("handoff_policy", { handoff_mode: value })} />
          <TaskSystemSelectField label="超时策略" value={draft.handoff_policy.timeout_policy} options={["fail_closed", "warn", "manual_release"]} onChange={(value) => patchPolicy("handoff_policy", { timeout_policy: value })} />
          <label className="boundary-check"><input checked={draft.handoff_policy.include_artifact_refs} onChange={(event) => patchPolicy("handoff_policy", { include_artifact_refs: event.target.checked })} type="checkbox" />交接包含产物引用</label>
          <label className="boundary-check"><input checked={draft.handoff_policy.ack_required} onChange={(event) => patchPolicy("handoff_policy", { ack_required: event.target.checked })} type="checkbox" />需要确认交接</label>
          <TaskSystemSelectField label="失败模式" value={draft.failure_policy.failure_mode} options={["fail_closed", "retry_once", "manual_review", "continue_with_warning"]} onChange={(value) => patchPolicy("failure_policy", { failure_mode: value })} />
          <TaskSystemField label="重试次数"><input type="number" value={draft.failure_policy.retry_limit} onChange={(event) => patchPolicy("failure_policy", { retry_limit: Number(event.target.value) || 0 })} /></TaskSystemField>
          <TaskSystemField label="升级对象"><input value={draft.failure_policy.escalate_to} onChange={(event) => patchPolicy("failure_policy", { escalate_to: event.target.value })} /></TaskSystemField>
          <label className="boundary-check"><input checked={draft.human_gate_policy.required} onChange={(event) => patchPolicy("human_gate_policy", { required: event.target.checked })} type="checkbox" />需要人工门控</label>
          <TaskSystemField label="人工角色"><input value={draft.human_gate_policy.reviewer_role} onChange={(event) => patchPolicy("human_gate_policy", { reviewer_role: event.target.value })} /></TaskSystemField>
        </div>
      </section>
      <section className="task-system-inspector-section">
        <header><Database size={15} /><strong>运行要求</strong><span>{draft.runtime_requirements.length} runtime</span><TaskSystemToolbarButton onClick={() => onChange({ ...draft, runtime_requirements: [...draft.runtime_requirements, emptyRuntimeRequirement(draft.runtime_requirements.length + 1)] })}><Plus size={14} />新增</TaskSystemToolbarButton></header>
        <div className="task-system-structured-list">
          {draft.runtime_requirements.map((item, index) => (
            <article className="task-system-structured-row" key={`${item.requirement_id}-${index}`}>
              <div className="boundary-form">
                <TaskSystemField label="要求 ID"><input value={item.requirement_id} onChange={(event) => patchRuntime(draft, onChange, index, { requirement_id: event.target.value })} /></TaskSystemField>
                <TaskSystemField label="名称"><input value={item.title_zh} onChange={(event) => patchRuntime(draft, onChange, index, { title_zh: event.target.value })} /></TaskSystemField>
                <TaskSystemSelectField label="要求类型" value={item.requirement_type} options={["capability", "model", "memory", "artifact", "human", "tool", "permission", "task_environment"]} onChange={(requirement_type) => patchRuntime(draft, onChange, index, { requirement_type })} />
                <TaskSystemField label="值"><input value={item.value} onChange={(event) => patchRuntime(draft, onChange, index, { value: event.target.value })} /></TaskSystemField>
                <label className="boundary-check"><input checked={item.required} onChange={(event) => patchRuntime(draft, onChange, index, { required: event.target.checked })} type="checkbox" />必需</label>
                <JsonObjectEditor label="要求配置" value={item.config ?? {}} onChange={(config) => patchRuntime(draft, onChange, index, { config })} rows={5} />
              </div>
              <div className="boundary-actions"><TaskSystemToolbarButton onClick={() => onChange({ ...draft, runtime_requirements: draft.runtime_requirements.filter((_, currentIndex) => currentIndex !== index) })}><Trash2 size={14} />删除</TaskSystemToolbarButton></div>
            </article>
          ))}
          {!draft.runtime_requirements.length ? <div className="boundary-empty">暂无运行要求。</div> : null}
        </div>
      </section>
    </div>
  );
}

function patchRuntime(draft: ContractSpec, onChange: (draft: ContractSpec) => void, index: number, patch: Partial<RuntimeRequirement>) {
  onChange({ ...draft, runtime_requirements: draft.runtime_requirements.map((item, currentIndex) => currentIndex === index ? { ...item, ...patch } : item) });
}

export function ContractUsageTab({ issues, usage }: { issues: ContractValidationIssue[]; usage: Array<Record<string, unknown>> }) {
  return (
    <div className="task-system-inspector-stack">
      <section className="task-system-inspector-section">
        <header><GitBranch size={15} /><strong>引用影响</strong><span>{usage.length} references</span></header>
        <div className="task-system-usage-list">
          {usage.map((item, index) => (
            <article className="task-system-usage-row" key={`${usageLabel(item)}-${index}`}>
              <strong>{usageLabel(item)}</strong>
              <span>{String(item.title ?? "")}</span>
            </article>
          ))}
          {!usage.length ? <div className="boundary-empty">当前契约还没有被任务、任务图、节点或边引用。</div> : null}
        </div>
      </section>
      <section className="task-system-inspector-section">
        <header><AlertTriangle size={15} /><strong>校验问题</strong><span>{issues.length} issues</span></header>
        <div className="task-system-usage-list">
          {issues.map((issue, index) => (
            <article className="task-system-usage-row task-system-usage-row--warn" key={`${issue.contract_id}-${issue.field}-${index}`}>
              <strong>{issue.field}</strong>
              <span>{issue.message || issue.reason}</span>
            </article>
          ))}
          {!issues.length ? <div className="boundary-empty">没有契约校验问题。</div> : null}
        </div>
      </section>
    </div>
  );
}

export function ContractAdvancedTab({ draft, onChange }: { draft: ContractSpec; onChange: (draft: ContractSpec) => void }) {
  return (
    <section className="task-system-inspector-section">
      <header><Database size={15} /><strong>高级 JSON</strong><span>高级入口只保留策略对象和扩展元数据</span></header>
      <div className="boundary-form">
        <TaskSystemField label="允许 Agent 类别" wide><textarea value={(draft.allowed_agent_kinds ?? []).join("\n")} onChange={(event) => onChange({ ...draft, allowed_agent_kinds: splitList(event.target.value) })} /></TaskSystemField>
        <JsonObjectEditor label="上下文可见性策略" value={draft.context_visibility_policy as unknown as Record<string, unknown>} onChange={(context_visibility_policy) => onChange({ ...draft, context_visibility_policy: context_visibility_policy as ContractSpec["context_visibility_policy"] })} />
        <JsonObjectEditor label="交接策略" value={draft.handoff_policy as unknown as Record<string, unknown>} onChange={(handoff_policy) => onChange({ ...draft, handoff_policy: handoff_policy as ContractSpec["handoff_policy"] })} />
        <JsonObjectEditor label="失败策略" value={draft.failure_policy as unknown as Record<string, unknown>} onChange={(failure_policy) => onChange({ ...draft, failure_policy: failure_policy as ContractSpec["failure_policy"] })} />
        <JsonObjectEditor label="人工门控策略" value={draft.human_gate_policy as unknown as Record<string, unknown>} onChange={(human_gate_policy) => onChange({ ...draft, human_gate_policy: human_gate_policy as ContractSpec["human_gate_policy"] })} />
        <JsonObjectEditor label="扩展元数据" value={draft.metadata ?? {}} onChange={(metadata) => onChange({ ...draft, metadata })} />
      </div>
    </section>
  );
}
