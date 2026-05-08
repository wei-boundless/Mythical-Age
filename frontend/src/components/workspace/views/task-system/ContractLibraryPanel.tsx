"use client";

import { Copy, Database, GitBranch, Plus, Save, ShieldCheck, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import {
  TaskSystemField,
  TaskSystemSelectField,
  TaskSystemToolbarButton,
  taskSystemOptionLabel,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import type { ContractSpec, ContractValidationIssue, TaskSystemOverview } from "@/lib/api";

function toJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJson<T>(value: string, fallback: T, label: string): T {
  try {
    return JSON.parse(value || JSON.stringify(fallback)) as T;
  } catch {
    throw new Error(`${label} 不是合法 JSON`);
  }
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
      gate_type: "",
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

type ContractDraftText = {
  input_fields: string;
  output_fields: string;
  artifact_requirements: string;
  acceptance_rules: string;
  runtime_requirements: string;
  context_visibility_policy: string;
  handoff_policy: string;
  failure_policy: string;
  human_gate_policy: string;
  allowed_agent_kinds: string;
  allowed_runtime_lanes: string;
  metadata: string;
};

function draftTextFrom(spec: ContractSpec): ContractDraftText {
  return {
    input_fields: toJson(spec.input_fields ?? []),
    output_fields: toJson(spec.output_fields ?? []),
    artifact_requirements: toJson(spec.artifact_requirements ?? []),
    acceptance_rules: toJson(spec.acceptance_rules ?? []),
    runtime_requirements: toJson(spec.runtime_requirements ?? []),
    context_visibility_policy: toJson(spec.context_visibility_policy ?? {}),
    handoff_policy: toJson(spec.handoff_policy ?? {}),
    failure_policy: toJson(spec.failure_policy ?? {}),
    human_gate_policy: toJson(spec.human_gate_policy ?? {}),
    allowed_agent_kinds: (spec.allowed_agent_kinds ?? []).join("\n"),
    allowed_runtime_lanes: (spec.allowed_runtime_lanes ?? []).join("\n"),
    metadata: toJson(spec.metadata ?? {}),
  };
}

function splitLines(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
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
  const [draft, setDraft] = useState<ContractSpec>(selected ?? newContractSpec(contractManagement.contract_kind_options?.[0]));
  const [draftText, setDraftText] = useState<ContractDraftText>(draftTextFrom(selected ?? draft));
  const [localError, setLocalError] = useState("");

  const issues = useMemo(
    () => (contractManagement.validation_issues ?? []).filter((item) => item.contract_id === draft.contract_id),
    [contractManagement.validation_issues, draft.contract_id],
  );

  function selectContract(contractId: string) {
    const next = specs.find((item) => item.contract_id === contractId) ?? newContractSpec(contractManagement.contract_kind_options?.[0]);
    setSelectedId(contractId);
    setDraft(next);
    setDraftText(draftTextFrom(next));
    setLocalError("");
  }

  function createDraft() {
    const next = newContractSpec(contractManagement.contract_kind_options?.[0]);
    setSelectedId("");
    setDraft(next);
    setDraftText(draftTextFrom(next));
    setLocalError("");
  }

  async function save() {
    setLocalError("");
    try {
      const payload: ContractSpec = {
        ...draft,
        input_fields: parseJson(draftText.input_fields, [], "输入字段"),
        output_fields: parseJson(draftText.output_fields, [], "输出字段"),
        artifact_requirements: parseJson(draftText.artifact_requirements, [], "产物要求"),
        acceptance_rules: parseJson(draftText.acceptance_rules, [], "验收规则"),
        runtime_requirements: parseJson(draftText.runtime_requirements, [], "运行要求"),
        context_visibility_policy: parseJson(draftText.context_visibility_policy, newContractSpec().context_visibility_policy, "上下文可见性"),
        handoff_policy: parseJson(draftText.handoff_policy, newContractSpec().handoff_policy, "交接策略"),
        failure_policy: parseJson(draftText.failure_policy, newContractSpec().failure_policy, "失败策略"),
        human_gate_policy: parseJson(draftText.human_gate_policy, newContractSpec().human_gate_policy, "人工门控"),
        allowed_agent_kinds: splitLines(draftText.allowed_agent_kinds),
        allowed_runtime_lanes: splitLines(draftText.allowed_runtime_lanes),
        metadata: parseJson(draftText.metadata, {}, "扩展元数据"),
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
          {!specs.length ? <div className="boundary-empty">还没有 ContractSpec。</div> : null}
        </div>
      </aside>

      <section className="boundary-card boundary-card--editor contract-library-workbench__editor">
        <header className="boundary-editor-title">
          <div className="boundary-identity-stack">
            <span>ContractSpec 主数据</span>
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

          <section className="contract-editor-section">
            <header><Copy size={15} /><strong>字段与产物</strong><span>输入、输出、产物、验收</span></header>
            <div className="boundary-form">
              <TaskSystemField label="输入字段 JSON" wide><textarea value={draftText.input_fields} onChange={(event) => setDraftText((value) => ({ ...value, input_fields: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="输出字段 JSON" wide><textarea value={draftText.output_fields} onChange={(event) => setDraftText((value) => ({ ...value, output_fields: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="产物要求 JSON" wide><textarea value={draftText.artifact_requirements} onChange={(event) => setDraftText((value) => ({ ...value, artifact_requirements: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="验收规则 JSON" wide><textarea value={draftText.acceptance_rules} onChange={(event) => setDraftText((value) => ({ ...value, acceptance_rules: event.target.value }))} /></TaskSystemField>
            </div>
          </section>

          <section className="contract-editor-section">
            <header><GitBranch size={15} /><strong>运行与通信</strong><span>可见性、交接、运行要求</span></header>
            <div className="boundary-form">
              <TaskSystemField label="运行要求 JSON" wide><textarea value={draftText.runtime_requirements} onChange={(event) => setDraftText((value) => ({ ...value, runtime_requirements: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="上下文可见性 JSON" wide><textarea value={draftText.context_visibility_policy} onChange={(event) => setDraftText((value) => ({ ...value, context_visibility_policy: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="交接策略 JSON" wide><textarea value={draftText.handoff_policy} onChange={(event) => setDraftText((value) => ({ ...value, handoff_policy: event.target.value }))} /></TaskSystemField>
            </div>
          </section>

          <section className="contract-editor-section">
            <header><ShieldCheck size={15} /><strong>治理策略</strong><span>失败、人工门控、适用范围</span></header>
            <div className="boundary-form">
              <TaskSystemField label="失败策略 JSON" wide><textarea value={draftText.failure_policy} onChange={(event) => setDraftText((value) => ({ ...value, failure_policy: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="人工门控 JSON" wide><textarea value={draftText.human_gate_policy} onChange={(event) => setDraftText((value) => ({ ...value, human_gate_policy: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="允许 Agent 类别" wide><textarea value={draftText.allowed_agent_kinds} onChange={(event) => setDraftText((value) => ({ ...value, allowed_agent_kinds: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="允许 Runtime Lane" wide><textarea value={draftText.allowed_runtime_lanes} onChange={(event) => setDraftText((value) => ({ ...value, allowed_runtime_lanes: event.target.value }))} /></TaskSystemField>
              <TaskSystemField label="扩展元数据 JSON" wide><textarea value={draftText.metadata} onChange={(event) => setDraftText((value) => ({ ...value, metadata: event.target.value }))} /></TaskSystemField>
            </div>
          </section>
        </div>
      </section>
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
