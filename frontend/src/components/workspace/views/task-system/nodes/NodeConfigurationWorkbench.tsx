"use client";

import { AlertTriangle, Cpu, GitBranch, Plus, Save, Search, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import {
  TaskSystemField,
  TaskSystemSelectField,
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import type {
  ContractSpec,
  OrchestrationAgentRuntimeCatalog,
  OrchestrationCapabilityItem,
  TaskNodeConfigurationSpec,
  TaskSystemOverview,
} from "@/lib/api";

type NodeTab = "detail" | "execution" | "contracts" | "capability" | "preview";

const NODE_TABS: Array<{ value: NodeTab; label: string }> = [
  { value: "detail", label: "节点详情" },
  { value: "execution", label: "执行装配" },
  { value: "contracts", label: "契约绑定" },
  { value: "capability", label: "能力与权限" },
  { value: "preview", label: "装配预览" },
];

function toJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJsonObject(value: string, label: string) {
  const text = String(value ?? "").trim();
  const parsed = text ? JSON.parse(text) : {};
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

function splitLines(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function nodeConfigTitle(spec: TaskNodeConfigurationSpec | null | undefined) {
  if (!spec) return "未选择节点配置";
  return spec.title || spec.node_config_id;
}

function newNodeConfiguration(): TaskNodeConfigurationSpec {
  return {
    node_config_id: "nodecfg.custom.agent",
    title: "新节点配置",
    description: "",
    node_kind: "agent",
    environment_scope: [],
    role_prompt: "你是一名任务节点执行员。\n你只负责当前节点契约声明的职责。\n你必须按输入契约理解任务，按输出契约交付结果。\n当资源、权限或上游输入不足时，你需要停止并说明缺口。",
    executor_ref: {
      agent_selection_policy: "explicit_agent",
    },
    contract_bindings: {},
    model_requirements: {},
    tool_policy: {},
    memory_policy: {},
    artifact_policy: {},
    failure_policy: {
      failure_mode: "fail_closed",
      retry_allowed: false,
    },
    human_gate_policy: {
      required: false,
      gate_type: "none",
    },
    metadata: { managed_by: "task_node_configuration_console" },
    enabled: true,
  };
}

function normalizeNodeConfiguration(spec: TaskNodeConfigurationSpec): TaskNodeConfigurationSpec {
  const fallback = newNodeConfiguration();
  return {
    ...fallback,
    ...spec,
    environment_scope: spec.environment_scope ?? [],
    executor_ref: spec.executor_ref ?? {},
    contract_bindings: spec.contract_bindings ?? {},
    model_requirements: spec.model_requirements ?? {},
    tool_policy: spec.tool_policy ?? {},
    memory_policy: spec.memory_policy ?? {},
    artifact_policy: spec.artifact_policy ?? {},
    failure_policy: spec.failure_policy ?? {},
    human_gate_policy: spec.human_gate_policy ?? {},
    metadata: spec.metadata ?? {},
    enabled: spec.enabled ?? true,
  };
}

function recordId(value: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const raw = String(value[key] ?? "").trim();
    if (raw) return raw;
  }
  return "";
}

function capabilityLabel(item: OrchestrationCapabilityItem) {
  return item.title ? `${item.title} · ${item.capability_id}` : item.capability_id;
}

function JsonObjectEditor({
  label,
  onChange,
  rows = 6,
  value,
}: {
  label: string;
  onChange: (value: Record<string, unknown>) => void;
  rows?: number;
  value: Record<string, unknown>;
}) {
  const [text, setText] = useState(toJson(value));
  const [error, setError] = useState("");

  useEffect(() => {
    setText(toJson(value));
    setError("");
  }, [value]);

  function update(nextText: string) {
    setText(nextText);
    try {
      onChange(parseJsonObject(nextText, label));
      setError("");
    } catch {
      setError(`${label} 不是合法 JSON，对象暂未写入草稿。`);
    }
  }

  return (
    <TaskSystemField label={label} wide>
      <div className={error ? "task-system-json-editor task-system-json-editor--invalid" : "task-system-json-editor"}>
        <textarea rows={rows} value={text} onChange={(event) => update(event.target.value)} spellCheck={false} />
        {error ? <small>{error}</small> : null}
      </div>
    </TaskSystemField>
  );
}

export function NodeConfigurationWorkbench({
  activePage,
  contractSpecs,
  environmentItems,
  nodeRuntimeCatalog,
  onDeleteNodeConfiguration,
  onPreviewNodeConfiguration,
  onSaveNodeConfiguration,
  saving,
  selectedEnvironmentId,
  taskSystemOverview,
}: {
  activePage?: "catalog" | "detail" | "capability" | "preview";
  contractSpecs: ContractSpec[];
  environmentItems: NonNullable<TaskSystemOverview["task_environment_management"]>["environments"];
  nodeRuntimeCatalog: OrchestrationAgentRuntimeCatalog | null;
  onDeleteNodeConfiguration: (nodeConfigId: string) => Promise<void>;
  onPreviewNodeConfiguration: (nodeConfigId: string, environmentId?: string) => Promise<Record<string, unknown>>;
  onSaveNodeConfiguration: (spec: TaskNodeConfigurationSpec) => Promise<void>;
  saving: boolean;
  selectedEnvironmentId: string;
  taskSystemOverview: TaskSystemOverview | null;
}) {
  const confirm = useConfirmDialog();
  const nodeManagement = taskSystemOverview?.node_configuration_management;
  const nodeConfigs = useMemo(() => nodeManagement?.node_configurations ?? [], [nodeManagement]);
  const issues = useMemo(() => nodeManagement?.issues ?? [], [nodeManagement]);
  const usageIndex = useMemo(() => nodeManagement?.usage_index ?? {}, [nodeManagement]);
  const [selectedId, setSelectedId] = useState(nodeConfigs[0]?.node_config_id ?? "");
  const selected = nodeConfigs.find((item) => item.node_config_id === selectedId) ?? nodeConfigs[0] ?? null;
  const [draft, setDraft] = useState<TaskNodeConfigurationSpec>(() => normalizeNodeConfiguration(selected ?? newNodeConfiguration()));
  const [activeTab, setActiveTab] = useState<NodeTab>("detail");
  const [query, setQuery] = useState("");
  const [envFilter, setEnvFilter] = useState("");
  const [localError, setLocalError] = useState("");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [previewEnvironmentId, setPreviewEnvironmentId] = useState(selectedEnvironmentId);

  useEffect(() => {
    if (selected && selected.node_config_id !== draft.node_config_id) {
      setDraft(normalizeNodeConfiguration(selected));
      setPreview(null);
      setLocalError("");
    }
    if (!selected && nodeConfigs.length === 0) {
      setDraft(normalizeNodeConfiguration(newNodeConfiguration()));
    }
  }, [draft.node_config_id, nodeConfigs.length, selected]);

  useEffect(() => {
    if (activePage === "detail") setActiveTab("detail");
    if (activePage === "capability") setActiveTab("capability");
    if (activePage === "preview") setActiveTab("preview");
  }, [activePage]);

  useEffect(() => {
    setPreviewEnvironmentId(selectedEnvironmentId);
  }, [selectedEnvironmentId]);

  const agentOptions = useMemo(
    () => (nodeRuntimeCatalog?.agents ?? []).map((agent) => ({
      value: recordId(agent, ["agent_id", "id", "agent_name"]),
      label: String(agent.display_name ?? agent.agent_name ?? agent.agent_id ?? agent.id ?? "Agent"),
    })).filter((item) => item.value),
    [nodeRuntimeCatalog?.agents],
  );
  const profileOptions = nodeRuntimeCatalog?.profiles?.map((profile) => profile.agent_profile_id).filter(Boolean) ?? [];
  const capabilityItems = nodeRuntimeCatalog?.options?.capability_items ?? [];
  const environmentOptions = environmentItems.map((item) => ({
    value: item.record.environment_id,
    label: item.record.title || item.record.environment_id,
  }));
  const contractOptions = contractSpecs.map((item) => item.contract_id).filter(Boolean);
  const draftIssues = issues.filter((item) => String(item.node_config_id ?? "") === draft.node_config_id);
  const draftUsage = usageIndex[draft.node_config_id] ?? [];

  const filteredConfigs = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return nodeConfigs.filter((spec) => {
      if (envFilter && !(spec.environment_scope ?? []).includes(envFilter)) return false;
      if (!needle) return true;
      return [
        spec.node_config_id,
        spec.title,
        spec.description,
        spec.node_kind,
        spec.role_prompt,
        String(spec.executor_ref?.agent_id ?? ""),
        String(spec.executor_ref?.agent_profile_id ?? ""),
      ].some((item) => String(item ?? "").toLowerCase().includes(needle));
    });
  }, [envFilter, nodeConfigs, query]);

  function selectNodeConfig(nodeConfigId: string) {
    const next = nodeConfigs.find((item) => item.node_config_id === nodeConfigId);
    if (!next) return;
    setSelectedId(nodeConfigId);
    setDraft(normalizeNodeConfiguration(next));
    setPreview(null);
    setLocalError("");
  }

  function createDraft() {
    const next = normalizeNodeConfiguration(newNodeConfiguration());
    setSelectedId("");
    setDraft(next);
    setPreview(null);
    setActiveTab("detail");
    setLocalError("");
  }

  async function save() {
    setLocalError("");
    try {
      if (!draft.node_config_id.startsWith("nodecfg.")) {
        throw new Error("节点配置 ID 必须以 nodecfg. 开头。");
      }
      await onSaveNodeConfiguration(draft);
      setSelectedId(draft.node_config_id);
    } catch (exc) {
      setLocalError(exc instanceof Error ? exc.message : "节点配置保存失败");
    }
  }

  async function remove() {
    if (!draft.node_config_id) return;
    const approved = await confirm({
      title: `删除节点配置「${nodeConfigTitle(draft)}」`,
      body: "删除后引用该配置的任务图节点需要重新绑定。任务系统不会删除 agent 注册或运行档案。",
      confirmLabel: "删除节点配置",
      tone: "warning",
    });
    if (!approved) return;
    await onDeleteNodeConfiguration(draft.node_config_id);
    createDraft();
  }

  async function previewRuntime() {
    setLocalError("");
    setPreview(null);
    try {
      const payload = await onPreviewNodeConfiguration(draft.node_config_id, previewEnvironmentId);
      setPreview(payload);
    } catch (exc) {
      setLocalError(exc instanceof Error ? exc.message : "节点装配预览失败");
    }
  }

  return (
    <main className="task-management-workbench task-system-management-workbench">
      <header className="task-management-titlebar task-system-workbench-titlebar">
        <div>
          <span>节点配置</span>
          <h3>节点角色、契约与运行装配</h3>
          <p>节点配置只管理节点主数据和引用关系；agent 注册、Provider、密钥和运行档案仍由编排系统维护。</p>
        </div>
        <div className="boundary-actions">
          <TaskSystemToolbarButton onClick={createDraft}><Plus size={15} />新节点配置</TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={saving || !draft.node_config_id} onClick={() => void remove()}><Trash2 size={15} />删除</TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={saving || !draft.node_config_id} onClick={() => void save()} variant="primary"><Save size={15} />保存</TaskSystemToolbarButton>
        </div>
      </header>

      {localError ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{localError}</div> : null}

      <section className="task-system-three-pane task-system-three-pane--nodes">
        <aside className="task-system-filter-rail" aria-label="节点配置筛选">
          <header>
            <strong>节点目录</strong>
            <span>{filteredConfigs.length} / {nodeConfigs.length} 个配置</span>
          </header>
          <label className="task-system-search-box">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索节点配置、执行者、prompt" />
          </label>
          <TaskSystemField label="环境范围">
            <select value={envFilter} onChange={(event) => setEnvFilter(event.target.value)}>
              <option value="">全部环境</option>
              {environmentOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </TaskSystemField>
          <div className="task-system-metric-stack">
            <Metric label="节点配置" value={nodeConfigs.length} />
            <Metric label="迁移候选" value={nodeManagement?.summary?.migration_candidate_count ?? 0} />
            <Metric label="配置问题" value={issues.length} tone={issues.length ? "warn" : "ok"} />
            <Metric label="能力候选" value={capabilityItems.length} />
          </div>
        </aside>

        <section className="task-system-catalog-table" aria-label="节点配置列表">
          <header className="task-system-table-head">
            <span>节点配置</span>
            <span>环境</span>
            <span>执行者</span>
            <span>引用</span>
            <span>状态</span>
          </header>
          <div className="task-system-table-body">
            {filteredConfigs.map((spec) => {
              const active = spec.node_config_id === draft.node_config_id;
              const issueCount = issues.filter((item) => String(item.node_config_id ?? "") === spec.node_config_id).length;
              const usageCount = (usageIndex[spec.node_config_id] ?? []).length;
              return (
                <button
                  className={active ? "task-system-table-row task-system-table-row--active" : "task-system-table-row"}
                  key={spec.node_config_id}
                  onClick={() => selectNodeConfig(spec.node_config_id)}
                  type="button"
                >
                  <strong>{nodeConfigTitle(spec)}<small>{spec.node_config_id}</small></strong>
                  <span>{spec.environment_scope?.[0] || "通用"}</span>
                  <span>{String(spec.executor_ref?.agent_id ?? spec.executor_ref?.agent_profile_id ?? "未绑定")}</span>
                  <span>{usageCount}</span>
                  <em className={issueCount ? "task-system-status task-system-status--warn" : "task-system-status"}>{issueCount ? `${issueCount} 问题` : "正常"}</em>
                </button>
              );
            })}
            {!filteredConfigs.length ? <div className="boundary-empty">没有符合条件的节点配置。</div> : null}
          </div>
        </section>

        <section className="task-system-detail-inspector" aria-label="节点配置详情">
          <header className="task-system-inspector-head">
            <div>
              <span>{draft.node_kind || "agent"}</span>
              <strong>{nodeConfigTitle(draft)}</strong>
              <small>{draft.node_config_id}</small>
            </div>
          </header>
          <nav className="task-system-inspector-tabs" aria-label="节点配置分区">
            {NODE_TABS.map((tab) => (
              <button
                className={activeTab === tab.value ? "task-system-inspector-tab task-system-inspector-tab--active" : "task-system-inspector-tab"}
                key={tab.value}
                onClick={() => setActiveTab(tab.value)}
                type="button"
              >
                {tab.label}
              </button>
            ))}
          </nav>
          <div className="task-system-inspector-body">
            {activeTab === "detail" ? <DetailTab draft={draft} onChange={setDraft} environmentOptions={environmentOptions} /> : null}
            {activeTab === "execution" ? <ExecutionTab agentOptions={agentOptions} draft={draft} onChange={setDraft} profileOptions={profileOptions} /> : null}
            {activeTab === "contracts" ? <ContractTab contractOptions={contractOptions} draft={draft} onChange={setDraft} /> : null}
            {activeTab === "capability" ? <CapabilityTab capabilityItems={capabilityItems} draft={draft} onChange={setDraft} /> : null}
            {activeTab === "preview" ? (
              <PreviewTab
                draftIssues={draftIssues}
                draftUsage={draftUsage}
                environmentOptions={environmentOptions}
                onPreview={() => void previewRuntime()}
                preview={preview}
                previewEnvironmentId={previewEnvironmentId}
                saving={saving}
                setPreviewEnvironmentId={setPreviewEnvironmentId}
              />
            ) : null}
          </div>
        </section>
      </section>
    </main>
  );
}

function Metric({ label, tone = "neutral", value }: { label: string; tone?: "neutral" | "warn" | "ok"; value: number }) {
  return (
    <article className={`task-system-metric task-system-metric--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function DetailTab({
  draft,
  environmentOptions,
  onChange,
}: {
  draft: TaskNodeConfigurationSpec;
  environmentOptions: Array<{ value: string; label: string }>;
  onChange: (draft: TaskNodeConfigurationSpec) => void;
}) {
  return (
    <section className="task-system-inspector-section">
      <header><Cpu size={15} /><strong>角色与职责</strong><span>写给 agent 的节点角色 prompt</span></header>
      <div className="boundary-form">
        <TaskSystemField label="节点配置 ID"><input value={draft.node_config_id} onChange={(event) => onChange({ ...draft, node_config_id: event.target.value })} /></TaskSystemField>
        <TaskSystemField label="名称"><input value={draft.title} onChange={(event) => onChange({ ...draft, title: event.target.value })} /></TaskSystemField>
        <TaskSystemSelectField label="节点类型" value={draft.node_kind || "agent"} options={["agent", "coordinator", "review_gate", "tool", "manual_gate", "runtime_monitor"]} onChange={(node_kind) => onChange({ ...draft, node_kind })} />
        <label className="boundary-check"><input checked={draft.enabled !== false} onChange={(event) => onChange({ ...draft, enabled: event.target.checked })} type="checkbox" />启用节点配置</label>
        <TaskSystemField label="说明" wide><textarea value={draft.description || ""} onChange={(event) => onChange({ ...draft, description: event.target.value })} /></TaskSystemField>
        <TaskSystemField label="环境范围" wide>
          <textarea
            value={(draft.environment_scope ?? []).join("\n")}
            onChange={(event) => onChange({ ...draft, environment_scope: splitLines(event.target.value) })}
            placeholder={environmentOptions.map((item) => item.value).join("\n")}
          />
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

function ExecutionTab({
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
          <JsonObjectEditor label="执行者引用 JSON" value={executorRef} onChange={(executor_ref) => onChange({ ...draft, executor_ref })} />
        </div>
      </section>
    </div>
  );
}

function ContractTab({
  contractOptions,
  draft,
  onChange,
}: {
  contractOptions: string[];
  draft: TaskNodeConfigurationSpec;
  onChange: (draft: TaskNodeConfigurationSpec) => void;
}) {
  const bindings = draft.contract_bindings ?? {};
  function patchBinding(key: string, value: string) {
    onChange({ ...draft, contract_bindings: { ...bindings, [key]: value } });
  }
  return (
    <section className="task-system-inspector-section">
      <header><ShieldCheck size={15} /><strong>契约绑定</strong><span>节点只绑定契约 ID，不复制契约主数据</span></header>
      <div className="boundary-form">
        <OptionalContractSelect label="输入契约" value={String(bindings.input_contract_id ?? "")} options={contractOptions} onChange={(value) => patchBinding("input_contract_id", value)} />
        <OptionalContractSelect label="输出契约" value={String(bindings.output_contract_id ?? "")} options={contractOptions} onChange={(value) => patchBinding("output_contract_id", value)} />
        <OptionalContractSelect label="节点执行契约" value={String(bindings.node_contract_id ?? "")} options={contractOptions} onChange={(value) => patchBinding("node_contract_id", value)} />
        <JsonObjectEditor label="契约绑定 JSON" value={bindings} onChange={(contract_bindings) => onChange({ ...draft, contract_bindings })} />
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

function CapabilityTab({
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

function PreviewTab({
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
