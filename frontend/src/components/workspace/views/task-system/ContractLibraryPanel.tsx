"use client";

import { Copy, Database, GitBranch, Plus, Save, ShieldCheck, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  TaskSystemField,
  TaskSystemSelectField,
  TaskSystemToolbarButton,
  taskSystemOptionLabel,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import type {
  AcceptanceRule,
  ArtifactRequirement,
  ContractField,
  ContractSpec,
  ContractValidationIssue,
  RuntimeRequirement,
  TaskSystemOverview,
} from "@/lib/api";

function toJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJson<T>(value: string, fallback: T, label: string): T {
  try {
    const text = String(value ?? "").trim();
    return (text ? JSON.parse(text) : fallback) as T;
  } catch {
    throw new Error(`${label} 不是合法 JSON`);
  }
}

function tryParseJson<T>(value: string, fallback: T): { ok: true; value: T } | { ok: false } {
  try {
    const text = String(value ?? "").trim();
    return { ok: true, value: (text ? JSON.parse(text) : fallback) as T };
  } catch {
    return { ok: false };
  }
}

function splitLines(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

export function contractSpecTitle(spec: Pick<ContractSpec, "contract_id" | "title_zh" | "title_en"> | null | undefined) {
  if (!spec) return "未选择契约";
  return spec.title_zh || spec.title_en || spec.contract_id;
}

export function newContractSpec(kind = "workflow"): ContractSpec {
  return {
    contract_id: "contract.custom.new",
    title_zh: "新契约",
    title_en: "New Contract",
    contract_kind: kind,
    description: "",
    input_fields: [],
    output_fields: [],
    artifact_requirements: [],
    acceptance_rules: [],
    runtime_requirements: [],
    context_visibility_policy: {
      main_session_history: "summary",
      upstream_outputs: "summary",
      sibling_nodes: "status_only",
      artifact_access: "refs_only",
      memory_scopes: [],
      model_visible_sections: [],
      hidden_sections: [],
      metadata: {},
    },
    handoff_policy: {
      handoff_mode: "structured_handoff",
      include_artifact_refs: true,
      include_raw_messages: false,
      ack_required: true,
      timeout_policy: "fail_closed",
      metadata: {},
    },
    failure_policy: {
      failure_mode: "fail_closed",
      retry_allowed: false,
      retry_limit: 0,
      escalate_to: "coordinator",
      fallback_contract_id: "",
      metadata: {},
    },
    human_gate_policy: {
      required: false,
      gate_type: "none",
      reviewer_role: "",
      decision_contract_id: "",
      metadata: {},
    },
    allowed_agent_kinds: [],
    allowed_runtime_lanes: [],
    version: "1.0.0",
    enabled: true,
    metadata: { managed_by: "task_contract_console" },
  };
}

function normalizeContractSpec(spec: ContractSpec): ContractSpec {
  const fallback = newContractSpec(spec.contract_kind || "workflow");
  return {
    ...fallback,
    ...spec,
    input_fields: spec.input_fields ?? [],
    output_fields: spec.output_fields ?? [],
    artifact_requirements: spec.artifact_requirements ?? [],
    acceptance_rules: spec.acceptance_rules ?? [],
    runtime_requirements: spec.runtime_requirements ?? [],
    context_visibility_policy: {
      ...fallback.context_visibility_policy,
      ...(spec.context_visibility_policy ?? {}),
    },
    handoff_policy: {
      ...fallback.handoff_policy,
      ...(spec.handoff_policy ?? {}),
    },
    failure_policy: {
      ...fallback.failure_policy,
      ...(spec.failure_policy ?? {}),
    },
    human_gate_policy: {
      ...fallback.human_gate_policy,
      ...(spec.human_gate_policy ?? {}),
    },
    allowed_agent_kinds: spec.allowed_agent_kinds ?? [],
    allowed_runtime_lanes: spec.allowed_runtime_lanes ?? [],
    metadata: spec.metadata ?? {},
  };
}

function contractKindLabel(value: string) {
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

function JsonTextarea({
  label,
  value,
  onValidChange,
}: {
  label: string;
  value: Record<string, unknown> | undefined;
  onValidChange: (value: Record<string, unknown>) => void;
}) {
  const [text, setText] = useState(toJson(value ?? {}));
  const [error, setError] = useState("");

  function update(nextText: string) {
    setText(nextText);
    const parsed = tryParseJson<Record<string, unknown>>(nextText, {});
    if (parsed.ok) {
      setError("");
      onValidChange(parsed.value);
    } else {
      setError(`${label} 不是合法 JSON，当前内容暂不写入契约。`);
    }
  }

  return (
    <TaskSystemField label={label} wide>
      <div className={error ? "contract-json-editor contract-json-editor--invalid" : "contract-json-editor"}>
        <textarea value={text} onChange={(event) => update(event.target.value)} spellCheck={false} />
        {error ? <small>{error}</small> : null}
      </div>
    </TaskSystemField>
  );
}

export function ContractLibraryPanel({
  contractManagement,
  saving,
  onSave,
  onDelete,
}: {
  contractManagement: NonNullable<TaskSystemOverview["contract_management"]>;
  saving: boolean;
  onSave: (spec: ContractSpec) => Promise<void>;
  onDelete: (contractId: string) => Promise<void>;
}) {
  const specs = contractManagement.contract_specs ?? [];
  const [selectedId, setSelectedId] = useState(specs[0]?.contract_id ?? "");
  const selected = specs.find((item) => item.contract_id === selectedId) ?? specs[0] ?? null;
  const [draft, setDraft] = useState<ContractSpec>(() => normalizeContractSpec(selected ?? newContractSpec(contractManagement.contract_kind_options?.[0])));
  const [metadataText, setMetadataText] = useState(toJson((selected ?? draft).metadata ?? {}));
  const [localError, setLocalError] = useState("");

  const issues = useMemo(
    () => (contractManagement.validation_issues ?? []).filter((item) => item.contract_id === draft.contract_id),
    [contractManagement.validation_issues, draft.contract_id],
  );

  function selectContract(contractId: string) {
    const next = normalizeContractSpec(specs.find((item) => item.contract_id === contractId) ?? newContractSpec(contractManagement.contract_kind_options?.[0]));
    setSelectedId(contractId);
    setDraft(next);
    setMetadataText(toJson(next.metadata ?? {}));
    setLocalError("");
  }

  function createDraft() {
    const next = normalizeContractSpec(newContractSpec(contractManagement.contract_kind_options?.[0]));
    setSelectedId("");
    setDraft(next);
    setMetadataText(toJson(next.metadata ?? {}));
    setLocalError("");
  }

  async function save() {
    setLocalError("");
    try {
      const payload: ContractSpec = {
        ...draft,
        metadata: parseJson(metadataText, {}, "扩展元数据"),
      };
      await onSave(payload);
      setSelectedId(payload.contract_id);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "契约保存失败");
    }
  }

  async function remove() {
    if (!draft.contract_id) return;
    if (!window.confirm(`确认删除契约「${contractSpecTitle(draft)}」？内置默认契约无法删除。`)) return;
    await onDelete(draft.contract_id);
    createDraft();
  }

  function patchPolicy<K extends "context_visibility_policy" | "handoff_policy" | "failure_policy" | "human_gate_policy">(key: K, patch: Partial<ContractSpec[K]>) {
    setDraft((current) => ({
      ...current,
      [key]: {
        ...(current[key] as Record<string, unknown>),
        ...patch,
      },
    }));
  }

  return (
    <section className="contract-library-workbench">
      <aside className="boundary-card contract-library-workbench__rail">
        <header>
          <strong>契约库</strong>
          <TaskSystemToolbarButton onClick={createDraft}>
            <Plus size={14} />新建
          </TaskSystemToolbarButton>
        </header>
        <div className="boundary-list boundary-list--scroll">
          {specs.map((spec) => (
            <button
              className={spec.contract_id === draft.contract_id ? "boundary-list-row boundary-list-row--active" : "boundary-list-row"}
              key={spec.contract_id}
              onClick={() => selectContract(spec.contract_id)}
              type="button"
            >
              <strong>{contractSpecTitle(spec)}</strong>
              <span>{contractKindLabel(spec.contract_kind)}</span>
            </button>
          ))}
          {!specs.length ? <div className="boundary-empty">还没有契约规格。</div> : null}
        </div>
      </aside>

      <section className="boundary-card boundary-card--editor contract-library-workbench__editor">
        <header className="boundary-editor-title">
          <div className="boundary-identity-stack">
            <span>契约规格主数据</span>
            <strong>{contractSpecTitle(draft)}</strong>
            <small>{contractKindLabel(draft.contract_kind)}</small>
          </div>
          <div className="boundary-actions">
            <TaskSystemToolbarButton disabled={saving} onClick={() => void remove()}>
              <Trash2 size={14} />删除
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={saving} onClick={() => void save()} variant="primary">
              <Save size={14} />保存契约
            </TaskSystemToolbarButton>
          </div>
        </header>

        {localError ? <div className="boundary-alert boundary-alert--error">{localError}</div> : null}
        {issues.length ? <IssueList issues={issues} /> : null}

        <div className="contract-editor-sections">
          <section className="contract-editor-section">
            <header><Database size={15} /><strong>主数据</strong><span>身份、类型与启用状态</span></header>
            <div className="boundary-form">
              <TaskSystemField label="契约 ID"><input value={draft.contract_id} onChange={(event) => setDraft((value) => ({ ...value, contract_id: event.target.value }))} /></TaskSystemField>
              <TaskSystemSelectField label="契约类型" value={draft.contract_kind} options={contractManagement.contract_kind_options ?? []} onChange={(value) => setDraft((current) => ({ ...current, contract_kind: value }))} formatOption={contractKindLabel} />
              <TaskSystemField label="中文名称"><input value={draft.title_zh} onChange={(event) => setDraft((value) => ({ ...value, title_zh: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="英文名称"><input value={draft.title_en} onChange={(event) => setDraft((value) => ({ ...value, title_en: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="版本"><input value={draft.version} onChange={(event) => setDraft((value) => ({ ...value, version: event.target.value }))} /></TaskSystemField>
              <label className="boundary-check"><input checked={draft.enabled} onChange={(event) => setDraft((value) => ({ ...value, enabled: event.target.checked }))} type="checkbox" />启用契约</label>
              <TaskSystemField label="说明" wide><textarea value={draft.description} onChange={(event) => setDraft((value) => ({ ...value, description: event.target.value }))} /></TaskSystemField>
            </div>
          </section>

          <ContractFieldEditor
            fields={draft.input_fields ?? []}
            icon={<Copy size={15} />}
            onChange={(input_fields) => setDraft((current) => ({ ...current, input_fields }))}
            options={contractManagement}
            title="输入字段"
          />
          <ContractFieldEditor
            fields={draft.output_fields ?? []}
            icon={<Copy size={15} />}
            onChange={(output_fields) => setDraft((current) => ({ ...current, output_fields }))}
            options={contractManagement}
            title="输出字段"
          />
          <ArtifactRequirementEditor
            items={draft.artifact_requirements ?? []}
            onChange={(artifact_requirements) => setDraft((current) => ({ ...current, artifact_requirements }))}
          />
          <AcceptanceRuleEditor
            fields={[...(draft.input_fields ?? []), ...(draft.output_fields ?? [])]}
            items={draft.acceptance_rules ?? []}
            onChange={(acceptance_rules) => setDraft((current) => ({ ...current, acceptance_rules }))}
            ruleTypeOptions={contractManagement.acceptance_rule_type_options ?? []}
          />
          <RuntimeRequirementEditor
            items={draft.runtime_requirements ?? []}
            onChange={(runtime_requirements) => setDraft((current) => ({ ...current, runtime_requirements }))}
          />

          <section className="contract-editor-section">
            <header><GitBranch size={15} /><strong>运行与通信策略</strong><span>上下文、交接、失败、人工门控</span></header>
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
              <TaskSystemField label="兜底契约"><input value={draft.failure_policy.fallback_contract_id} onChange={(event) => patchPolicy("failure_policy", { fallback_contract_id: event.target.value })} /></TaskSystemField>
              <label className="boundary-check"><input checked={draft.human_gate_policy.required} onChange={(event) => patchPolicy("human_gate_policy", { required: event.target.checked })} type="checkbox" />需要人工门控</label>
              <TaskSystemField label="人工角色"><input value={draft.human_gate_policy.reviewer_role} onChange={(event) => patchPolicy("human_gate_policy", { reviewer_role: event.target.value })} /></TaskSystemField>
              <TaskSystemField label="人工裁决契约"><input value={draft.human_gate_policy.decision_contract_id} onChange={(event) => patchPolicy("human_gate_policy", { decision_contract_id: event.target.value })} /></TaskSystemField>
            </div>
          </section>

          <section className="contract-editor-section">
            <header><ShieldCheck size={15} /><strong>适用范围与高级字段</strong><span>高级 JSON 只保留扩展元数据</span></header>
            <div className="boundary-form">
              <TaskSystemField label="允许 Agent 类别" wide><textarea value={(draft.allowed_agent_kinds ?? []).join("\n")} onChange={(event) => setDraft((value) => ({ ...value, allowed_agent_kinds: splitLines(event.target.value) }))} /></TaskSystemField>
              <TaskSystemField label="适用运行场景权限" wide><textarea value={(draft.allowed_runtime_lanes ?? []).join("\n")} onChange={(event) => setDraft((value) => ({ ...value, allowed_runtime_lanes: splitLines(event.target.value) }))} /></TaskSystemField>
              <TaskSystemField label="扩展元数据 JSON" wide><textarea value={metadataText} onChange={(event) => setMetadataText(event.target.value)} /></TaskSystemField>
            </div>
          </section>
        </div>
      </section>
    </section>
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
  options: NonNullable<TaskSystemOverview["contract_management"]>;
  title: string;
}) {
  function patch(index: number, patchValue: Partial<ContractField>) {
    onChange(fields.map((item, currentIndex) => currentIndex === index ? { ...item, ...patchValue } : item));
  }
  function remove(index: number) {
    onChange(fields.filter((_, currentIndex) => currentIndex !== index));
  }
  function duplicate(index: number) {
    const source = fields[index] ?? emptyField(fields.length + 1);
    onChange([...fields, { ...source, field_id: `${source.field_id || "field"}_copy` }]);
  }
  return (
    <section className="contract-editor-section">
      <header>{icon}<strong>{title}</strong><span>{fields.length} fields</span><TaskSystemToolbarButton onClick={() => onChange([...fields, emptyField(fields.length + 1)])}><Plus size={14} />新增字段</TaskSystemToolbarButton></header>
      <div className="contract-structured-list">
        {fields.map((field, index) => (
          <article className="contract-structured-row" key={`${field.field_id}-${index}`}>
            <div className="boundary-form">
              <TaskSystemField label="字段 ID"><input value={field.field_id} onChange={(event) => patch(index, { field_id: event.target.value })} /></TaskSystemField>
              <TaskSystemField label="中文名称"><input value={field.title_zh} onChange={(event) => patch(index, { title_zh: event.target.value })} /></TaskSystemField>
              <TaskSystemSelectField label="字段类型" value={field.field_type} options={options.field_type_options ?? []} onChange={(value) => patch(index, { field_type: value })} />
              <TaskSystemSelectField label="字段来源" value={field.source_hint} options={options.source_hint_options ?? []} onChange={(value) => patch(index, { source_hint: value })} />
              <TaskSystemSelectField label="可见性" value={field.visibility} options={options.visibility_options ?? []} onChange={(value) => patch(index, { visibility: value })} />
              <TaskSystemField label="默认值"><input value={String(field.default_value ?? "")} onChange={(event) => patch(index, { default_value: event.target.value })} /></TaskSystemField>
              <label className="boundary-check"><input checked={field.required} onChange={(event) => patch(index, { required: event.target.checked })} type="checkbox" />必填字段</label>
              <TaskSystemField label="说明" wide><textarea value={field.description} onChange={(event) => patch(index, { description: event.target.value })} /></TaskSystemField>
              <JsonTextarea key={`${field.field_id}-${index}-schema`} label="Schema JSON" value={field.schema ?? {}} onValidChange={(schema) => patch(index, { schema })} />
            </div>
            <div className="boundary-actions">
              <TaskSystemToolbarButton onClick={() => duplicate(index)}><Copy size={14} />复制</TaskSystemToolbarButton>
              <TaskSystemToolbarButton onClick={() => remove(index)}><Trash2 size={14} />删除</TaskSystemToolbarButton>
            </div>
          </article>
        ))}
        {!fields.length ? <div className="boundary-empty">暂无字段。点击新增字段开始定义契约输入或输出。</div> : null}
      </div>
    </section>
  );
}

function ArtifactRequirementEditor({ items, onChange }: { items: ArtifactRequirement[]; onChange: (items: ArtifactRequirement[]) => void }) {
  function patch(index: number, patchValue: Partial<ArtifactRequirement>) {
    onChange(items.map((item, currentIndex) => currentIndex === index ? { ...item, ...patchValue } : item));
  }
  return (
    <section className="contract-editor-section">
      <header><Database size={15} /><strong>产物要求</strong><span>{items.length} artifacts</span><TaskSystemToolbarButton onClick={() => onChange([...items, emptyArtifactRequirement(items.length + 1)])}><Plus size={14} />新增产物</TaskSystemToolbarButton></header>
      <div className="contract-structured-list">
        {items.map((item, index) => (
          <article className="contract-structured-row" key={`${item.requirement_id}-${index}`}>
            <div className="boundary-form">
              <TaskSystemField label="要求 ID"><input value={item.requirement_id} onChange={(event) => patch(index, { requirement_id: event.target.value })} /></TaskSystemField>
              <TaskSystemField label="名称"><input value={item.title_zh} onChange={(event) => patch(index, { title_zh: event.target.value })} /></TaskSystemField>
              <TaskSystemField label="产物类型"><input value={item.artifact_type} onChange={(event) => patch(index, { artifact_type: event.target.value })} /></TaskSystemField>
              <TaskSystemSelectField label="存储策略" value={item.storage_policy} options={["artifact_ref", "inline_summary", "file_path", "formal_repository"]} onChange={(value) => patch(index, { storage_policy: value })} />
              <TaskSystemField label="命名规则"><input value={item.naming_rule} onChange={(event) => patch(index, { naming_rule: event.target.value })} /></TaskSystemField>
              <label className="boundary-check"><input checked={item.required} onChange={(event) => patch(index, { required: event.target.checked })} type="checkbox" />必需产物</label>
              <TaskSystemField label="说明" wide><textarea value={item.description} onChange={(event) => patch(index, { description: event.target.value })} /></TaskSystemField>
            </div>
            <div className="boundary-actions"><TaskSystemToolbarButton onClick={() => onChange(items.filter((_, currentIndex) => currentIndex !== index))}><Trash2 size={14} />删除</TaskSystemToolbarButton></div>
          </article>
        ))}
        {!items.length ? <div className="boundary-empty">暂无产物要求。</div> : null}
      </div>
    </section>
  );
}

function AcceptanceRuleEditor({
  fields,
  items,
  onChange,
  ruleTypeOptions,
}: {
  fields: ContractField[];
  items: AcceptanceRule[];
  onChange: (items: AcceptanceRule[]) => void;
  ruleTypeOptions: string[];
}) {
  function patch(index: number, patchValue: Partial<AcceptanceRule>) {
    onChange(items.map((item, currentIndex) => currentIndex === index ? { ...item, ...patchValue } : item));
  }
  const fieldOptions = fields.map((field) => field.field_id).filter(Boolean);
  return (
    <section className="contract-editor-section">
      <header><ShieldCheck size={15} /><strong>验收规则</strong><span>{items.length} rules</span><TaskSystemToolbarButton onClick={() => onChange([...items, emptyAcceptanceRule(items.length + 1)])}><Plus size={14} />新增规则</TaskSystemToolbarButton></header>
      <div className="contract-structured-list">
        {items.map((item, index) => (
          <article className="contract-structured-row" key={`${item.rule_id}-${index}`}>
            <div className="boundary-form">
              <TaskSystemField label="规则 ID"><input value={item.rule_id} onChange={(event) => patch(index, { rule_id: event.target.value })} /></TaskSystemField>
              <TaskSystemField label="名称"><input value={item.title_zh} onChange={(event) => patch(index, { title_zh: event.target.value })} /></TaskSystemField>
              <TaskSystemSelectField label="规则类型" value={item.rule_type} options={ruleTypeOptions} onChange={(value) => patch(index, { rule_type: value })} />
              <TaskSystemSelectField label="严重级别" value={item.severity} options={["error", "warning", "info"]} onChange={(value) => patch(index, { severity: value })} />
              <TaskSystemSelectField label="目标字段" value={item.target_field} options={fieldOptions} onChange={(value) => patch(index, { target_field: value })} />
              <TaskSystemField label="判定标准" wide><textarea value={item.criteria} onChange={(event) => patch(index, { criteria: event.target.value })} /></TaskSystemField>
              <JsonTextarea key={`${item.rule_id}-${index}-config`} label="配置 JSON" value={item.config ?? {}} onValidChange={(config) => patch(index, { config })} />
            </div>
            <div className="boundary-actions"><TaskSystemToolbarButton onClick={() => onChange(items.filter((_, currentIndex) => currentIndex !== index))}><Trash2 size={14} />删除</TaskSystemToolbarButton></div>
          </article>
        ))}
        {!items.length ? <div className="boundary-empty">暂无验收规则。</div> : null}
      </div>
    </section>
  );
}

function RuntimeRequirementEditor({ items, onChange }: { items: RuntimeRequirement[]; onChange: (items: RuntimeRequirement[]) => void }) {
  function patch(index: number, patchValue: Partial<RuntimeRequirement>) {
    onChange(items.map((item, currentIndex) => currentIndex === index ? { ...item, ...patchValue } : item));
  }
  return (
    <section className="contract-editor-section">
      <header><GitBranch size={15} /><strong>运行要求</strong><span>{items.length} runtime</span><TaskSystemToolbarButton onClick={() => onChange([...items, emptyRuntimeRequirement(items.length + 1)])}><Plus size={14} />新增要求</TaskSystemToolbarButton></header>
      <div className="contract-structured-list">
        {items.map((item, index) => (
          <article className="contract-structured-row" key={`${item.requirement_id}-${index}`}>
            <div className="boundary-form">
              <TaskSystemField label="要求 ID"><input value={item.requirement_id} onChange={(event) => patch(index, { requirement_id: event.target.value })} /></TaskSystemField>
              <TaskSystemField label="名称"><input value={item.title_zh} onChange={(event) => patch(index, { title_zh: event.target.value })} /></TaskSystemField>
              <TaskSystemSelectField label="要求类型" value={item.requirement_type} options={["capability", "model", "runtime_lane", "memory", "artifact", "human"]} onChange={(value) => patch(index, { requirement_type: value })} />
              <TaskSystemField label="值"><input value={item.value} onChange={(event) => patch(index, { value: event.target.value })} /></TaskSystemField>
              <label className="boundary-check"><input checked={item.required} onChange={(event) => patch(index, { required: event.target.checked })} type="checkbox" />必需</label>
              <JsonTextarea key={`${item.requirement_id}-${index}-config`} label="配置 JSON" value={item.config ?? {}} onValidChange={(config) => patch(index, { config })} />
            </div>
            <div className="boundary-actions"><TaskSystemToolbarButton onClick={() => onChange(items.filter((_, currentIndex) => currentIndex !== index))}><Trash2 size={14} />删除</TaskSystemToolbarButton></div>
          </article>
        ))}
        {!items.length ? <div className="boundary-empty">暂无运行要求。</div> : null}
      </div>
    </section>
  );
}

function IssueList({ issues }: { issues: ContractValidationIssue[] }) {
  return (
    <div className="boundary-alert boundary-alert--warn">
      {issues.map((issue, index) => (
        <p key={`${issue.contract_id}-${issue.field}-${index}`}>
          <strong>{issue.field}</strong>：{issue.message || issue.reason}
        </p>
      ))}
    </div>
  );
}
