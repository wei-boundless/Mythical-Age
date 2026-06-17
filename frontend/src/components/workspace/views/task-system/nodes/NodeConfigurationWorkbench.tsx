"use client";

import { AlertTriangle, Plus, Save, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import {
  TaskSystemField,
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { Metric } from "@/components/workspace/views/task-system/managementPrimitives";
import type {
  ContractSpec,
  OrchestrationAgentRuntimeCatalog,
  TaskNodeConfigurationSpec,
  TaskSystemOverview,
} from "@/lib/api";
import { Notice } from "@/ui/Notice";

import {
  taskEnvironmentDisplayTitle,
  userVisibleEnvironmentItems,
} from "../environment/environmentPresentation";
import {
  NodeCapabilityTab,
  NodeContractTab,
  NodeDetailTab,
  NodeExecutionTab,
  NodePreviewTab,
} from "./NodeConfigurationTabs";
import {
  newNodeConfiguration,
  nodeConfigTitle,
  normalizeNodeConfiguration,
  recordId,
} from "./nodeConfigurationModel";

type NodeTab = "detail" | "execution" | "contracts" | "capability" | "preview";

const NODE_TABS: Array<{ value: NodeTab; label: string }> = [
  { value: "detail", label: "节点详情" },
  { value: "execution", label: "执行装配" },
  { value: "contracts", label: "契约绑定" },
  { value: "capability", label: "能力与权限" },
  { value: "preview", label: "装配预览" },
];

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
  const visibleEnvironmentItems = userVisibleEnvironmentItems(environmentItems);
  const environmentOptions = visibleEnvironmentItems.map((item) => ({
    value: item.record.environment_id,
    label: taskEnvironmentDisplayTitle(item),
  }));
  const environmentLabelById = new Map(environmentOptions.map((item) => [item.value, item.label]));
  const contractOptions = contractSpecs.map((item) => item.contract_id).filter(Boolean);
  const contractFamilies = taskSystemOverview?.contract_management?.contract_families ?? [];
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

      {localError ? <Notice icon={<AlertTriangle size={16} />} tone="error">{localError}</Notice> : null}

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
                  <span>{spec.environment_scope?.[0] ? environmentLabelById.get(spec.environment_scope[0]) ?? "自定义环境" : "通用"}</span>
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
            {activeTab === "detail" ? <NodeDetailTab draft={draft} onChange={setDraft} environmentOptions={environmentOptions} /> : null}
            {activeTab === "execution" ? <NodeExecutionTab agentOptions={agentOptions} draft={draft} onChange={setDraft} profileOptions={profileOptions} /> : null}
            {activeTab === "contracts" ? <NodeContractTab contractFamilies={contractFamilies} contractOptions={contractOptions} draft={draft} onChange={setDraft} /> : null}
            {activeTab === "capability" ? <NodeCapabilityTab capabilityItems={capabilityItems} draft={draft} onChange={setDraft} /> : null}
            {activeTab === "preview" ? (
              <NodePreviewTab
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
