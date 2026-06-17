"use client";

import { AlertTriangle, Boxes, Plus, Save, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import {
  TaskSystemField,
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { Metric } from "@/components/workspace/views/task-system/managementPrimitives";
import type {
  ContractSpec,
  TaskSystemOverview,
} from "@/lib/api";
import { Notice } from "@/ui/Notice";

import {
  ContractAdvancedTab,
  ContractArtifactsTab,
  ContractOverviewTab,
  ContractRuntimeTab,
  ContractSchemaTab,
  ContractUsageTab,
  contractKindLabel,
} from "./ContractInspectorTabs";
import { contractSpecTitle, newContractSpec, normalizeContractSpec } from "./contractUtils";

type ContractTab = "overview" | "schema" | "artifacts" | "runtime" | "usage" | "advanced";
type ContractFamily = Record<string, unknown>;

const CONTRACT_TABS: Array<{ value: ContractTab; label: string }> = [
  { value: "overview", label: "概览" },
  { value: "schema", label: "Schema" },
  { value: "artifacts", label: "产物与验收" },
  { value: "runtime", label: "运行策略" },
  { value: "usage", label: "使用影响" },
  { value: "advanced", label: "高级 JSON" },
];

export function ContractManagementWorkbench({
  activePage,
  contractManagement,
  contractSpecs,
  contractUsageIndex,
  onDeleteContract,
  onSaveContract,
  saving,
}: {
  activePage?: "catalog" | "detail" | "usage";
  contractManagement: TaskSystemOverview["contract_management"] | null;
  contractSpecs: ContractSpec[];
  contractUsageIndex: TaskSystemOverview["contract_usage_index"] | null | undefined;
  onDeleteContract: (contractId: string) => Promise<void>;
  onSaveContract: (spec: ContractSpec) => Promise<void>;
  saving: boolean;
}) {
  const confirm = useConfirmDialog();
  const [selectedId, setSelectedId] = useState(contractSpecs[0]?.contract_id ?? "");
  const contractFamilies = useMemo(() => contractManagement?.contract_families ?? [], [contractManagement?.contract_families]);
  const [selectedFamilyId, setSelectedFamilyId] = useState(() => familyId(contractFamilies[0]));
  const selected = contractSpecs.find((item) => item.contract_id === selectedId) ?? contractSpecs[0] ?? null;
  const selectedFamily = contractFamilies.find((item) => familyId(item) === selectedFamilyId) ?? null;
  const [draft, setDraft] = useState<ContractSpec>(() => normalizeContractSpec(selected ?? newContractSpec(contractManagement?.contract_kind_options?.[0])));
  const [activeTab, setActiveTab] = useState<ContractTab>("overview");
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [usageFilter, setUsageFilter] = useState<"all" | "used" | "unused" | "issues">("all");
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!selectedFamilyId && !selectedId && contractFamilies[0]) {
      setSelectedFamilyId(familyId(contractFamilies[0]));
    }
  }, [contractFamilies, selectedFamilyId, selectedId]);

  useEffect(() => {
    if (selected && selected.contract_id !== draft.contract_id) {
      setDraft(normalizeContractSpec(selected));
      setLocalError("");
    }
    if (!selected && contractSpecs.length === 0) {
      setDraft(normalizeContractSpec(newContractSpec(contractManagement?.contract_kind_options?.[0])));
    }
  }, [contractManagement?.contract_kind_options, contractSpecs.length, draft.contract_id, selected]);

  useEffect(() => {
    if (activePage === "usage") setActiveTab("usage");
    if (activePage === "detail") setActiveTab("overview");
  }, [activePage]);

  const usageByContractId = useMemo(() => contractUsageIndex?.by_contract_id ?? {}, [contractUsageIndex]);
  const issues = useMemo(() => contractManagement?.validation_issues ?? [], [contractManagement]);
  const draftIssues = issues.filter((item) => item.contract_id === draft.contract_id);
  const draftUsage = usageByContractId[draft.contract_id] ?? [];

  const filteredSpecs = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return contractSpecs.filter((spec) => {
      const usageCount = (usageByContractId[spec.contract_id] ?? []).length;
      const issueCount = issues.filter((issue) => issue.contract_id === spec.contract_id).length;
      if (kindFilter && spec.contract_kind !== kindFilter) return false;
      if (usageFilter === "used" && usageCount === 0) return false;
      if (usageFilter === "unused" && usageCount > 0) return false;
      if (usageFilter === "issues" && issueCount === 0) return false;
      if (!needle) return true;
      return [
        spec.contract_id,
        spec.title_zh,
        spec.title_en,
        spec.contract_kind,
        spec.description,
      ].some((item) => String(item ?? "").toLowerCase().includes(needle));
    });
  }, [contractSpecs, issues, kindFilter, query, usageByContractId, usageFilter]);

  function selectContract(contractId: string) {
    const next = contractSpecs.find((item) => item.contract_id === contractId);
    if (!next) return;
    setSelectedFamilyId("");
    setSelectedId(contractId);
    setDraft(normalizeContractSpec(next));
    setLocalError("");
  }

  function selectFamily(family: ContractFamily) {
    setSelectedFamilyId(familyId(family));
    setSelectedId("");
    setLocalError("");
    setActiveTab("overview");
  }

  function createDraft() {
    const next = normalizeContractSpec(newContractSpec(contractManagement?.contract_kind_options?.[0]));
    setSelectedFamilyId("");
    setSelectedId("");
    setDraft(next);
    setActiveTab("overview");
    setLocalError("");
  }

  async function save() {
    setLocalError("");
    try {
      await onSaveContract(draft);
      setSelectedId(draft.contract_id);
    } catch (exc) {
      setLocalError(exc instanceof Error ? exc.message : "契约保存失败");
    }
  }

  async function remove() {
    if (!draft.contract_id) return;
    const approved = await confirm({
      title: `删除契约「${contractSpecTitle(draft)}」`,
      body: "删除后会从契约库移除该契约资产，已有引用需要重新绑定。",
      confirmLabel: "删除契约",
      tone: "warning",
    });
    if (!approved) return;
    await onDeleteContract(draft.contract_id);
    createDraft();
  }

  return (
    <main className="task-management-workbench task-system-management-workbench">
      <header className="task-management-titlebar task-system-workbench-titlebar">
        <div>
          <span>契约库</span>
          <h3>契约族、必要覆盖与高级契约</h3>
          <p>默认管理复用契约族；单个 ContractSpec 只作为高级协议资产维护。</p>
        </div>
        <div className="boundary-actions">
          <TaskSystemToolbarButton onClick={createDraft}><Plus size={15} />新契约</TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={saving || !draft.contract_id || Boolean(selectedFamily)} onClick={() => void remove()}><Trash2 size={15} />删除</TaskSystemToolbarButton>
          <TaskSystemToolbarButton disabled={saving || !draft.contract_id || Boolean(selectedFamily)} onClick={() => void save()} variant="primary"><Save size={15} />保存</TaskSystemToolbarButton>
        </div>
      </header>

      {localError ? <Notice icon={<AlertTriangle size={16} />} tone="error">{localError}</Notice> : null}

      <section className="task-system-three-pane task-system-three-pane--contracts">
        <aside className="task-system-filter-rail" aria-label="契约筛选">
          <header>
            <strong>筛选目录</strong>
            <span>{filteredSpecs.length} / {contractSpecs.length} 个契约</span>
          </header>
          <label className="task-system-search-box">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索契约、kind、说明" />
          </label>
          <section className="task-system-side-section">
            <header>
              <strong>复用契约族</strong>
              <span>{contractFamilies.length} 个模板</span>
            </header>
            <div className="task-system-list-stack">
              {contractFamilies.map((family) => {
                const active = familyId(family) === selectedFamilyId;
                return (
                  <button
                    className={active ? "task-system-list-button task-system-list-button--active" : "task-system-list-button"}
                    key={familyId(family)}
                    onClick={() => selectFamily(family)}
                    type="button"
                  >
                    <strong>{familyTitle(family)}</strong>
                    <span>{String(family.purpose ?? "")}</span>
                  </button>
                );
              })}
              {!contractFamilies.length ? <div className="boundary-empty">后端暂未返回契约族目录。</div> : null}
            </div>
          </section>
          <TaskSystemField label="契约类型">
            <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value)}>
              <option value="">全部类型</option>
              {(contractManagement?.contract_kind_options ?? []).map((item) => (
                <option key={item} value={item}>{contractKindLabel(item)}</option>
              ))}
            </select>
          </TaskSystemField>
          <TaskSystemField label="引用状态">
            <div className="task-system-segmented">
              {[
                ["all", "全部"],
                ["used", "已引用"],
                ["unused", "未引用"],
                ["issues", "有问题"],
              ].map(([value, label]) => (
                <button
                  className={usageFilter === value ? "task-system-segmented__item task-system-segmented__item--active" : "task-system-segmented__item"}
                  key={value}
                  onClick={() => setUsageFilter(value as typeof usageFilter)}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
          </TaskSystemField>
          <div className="task-system-metric-stack">
            <Metric label="引用记录" value={contractUsageIndex?.summary?.usage_count ?? 0} />
            <Metric label="契约族" value={contractFamilies.length} />
            <Metric label="有引用契约" value={contractUsageIndex?.summary?.contract_with_usage_count ?? 0} />
            <Metric label="校验问题" value={issues.length} tone={issues.length ? "warn" : "ok"} />
          </div>
        </aside>

        <section className="task-system-catalog-table" aria-label="契约列表">
          <header className="task-system-table-head">
            <span>高级契约</span>
            <span>Schema</span>
            <span>验收</span>
            <span>引用</span>
            <span>状态</span>
          </header>
          <div className="task-system-table-body">
            {filteredSpecs.map((spec) => {
              const usageCount = (usageByContractId[spec.contract_id] ?? []).length;
              const issueCount = issues.filter((issue) => issue.contract_id === spec.contract_id).length;
              const active = spec.contract_id === draft.contract_id;
              return (
                <button
                  className={active ? "task-system-table-row task-system-table-row--active" : "task-system-table-row"}
                  key={spec.contract_id}
                  onClick={() => selectContract(spec.contract_id)}
                  type="button"
                >
                  <strong>{contractSpecTitle(spec)}<small>{spec.contract_id}</small></strong>
                  <span>{(spec.input_fields?.length ?? 0) + (spec.output_fields?.length ?? 0)} 字段</span>
                  <span>{spec.acceptance_rules?.length ?? 0} 条</span>
                  <span>{usageCount}</span>
                  <em className={issueCount ? "task-system-status task-system-status--warn" : "task-system-status"}>{issueCount ? `${issueCount} 问题` : "正常"}</em>
                </button>
              );
            })}
            {!filteredSpecs.length ? <div className="boundary-empty">没有符合当前筛选条件的契约。</div> : null}
          </div>
        </section>

        <section className="task-system-detail-inspector" aria-label="契约详情">
          <header className="task-system-inspector-head">
            <div>
              <span>{selectedFamily ? "contract family" : draft.contract_kind || "contract"}</span>
              <strong>{selectedFamily ? familyTitle(selectedFamily) : contractSpecTitle(draft)}</strong>
              <small>{selectedFamily ? familyId(selectedFamily) : draft.contract_id}</small>
            </div>
          </header>
          {!selectedFamily ? (
            <nav className="task-system-inspector-tabs" aria-label="契约详情分区">
              {CONTRACT_TABS.map((tab) => (
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
          ) : null}
          <div className="task-system-inspector-body">
            {selectedFamily ? <ContractFamilyOverview family={selectedFamily} /> : null}
            {!selectedFamily && activeTab === "overview" ? (
              <ContractOverviewTab
                draft={draft}
                kindOptions={contractManagement?.contract_kind_options ?? []}
                onChange={setDraft}
              />
            ) : null}
            {!selectedFamily && activeTab === "schema" ? (
              <ContractSchemaTab
                draft={draft}
                fieldTypeOptions={contractManagement?.field_type_options ?? []}
                sourceHintOptions={contractManagement?.source_hint_options ?? []}
                visibilityOptions={contractManagement?.visibility_options ?? []}
                onChange={setDraft}
              />
            ) : null}
            {!selectedFamily && activeTab === "artifacts" ? (
              <ContractArtifactsTab
                draft={draft}
                ruleTypeOptions={contractManagement?.acceptance_rule_type_options ?? []}
                onChange={setDraft}
              />
            ) : null}
            {!selectedFamily && activeTab === "runtime" ? <ContractRuntimeTab draft={draft} onChange={setDraft} /> : null}
            {!selectedFamily && activeTab === "usage" ? <ContractUsageTab issues={draftIssues} usage={draftUsage} /> : null}
            {!selectedFamily && activeTab === "advanced" ? <ContractAdvancedTab draft={draft} onChange={setDraft} /> : null}
          </div>
        </section>
      </section>
    </main>
  );
}

function familyId(family: ContractFamily | undefined) {
  return String(family?.family_id ?? "").trim();
}

function familyTitle(family: ContractFamily) {
  return String(family.title_zh ?? family.family_id ?? "契约族");
}

function familyList(family: ContractFamily, key: string): string[] {
  const value = family[key];
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function ContractFamilyOverview({ family }: { family: ContractFamily }) {
  return (
    <div className="task-system-inspector-stack">
      <section className="task-system-inspector-section">
        <header><Boxes size={15} /><strong>复用契约族</strong><span>用户选择语义族，系统解析具体 ContractSpec</span></header>
        <div className="task-system-family-summary">
          <p><span>用途</span><strong>{String(family.purpose ?? "")}</strong></p>
          <p><span>契约类型</span><strong>{contractKindLabel(String(family.contract_kind ?? ""))}</strong></p>
          <p><span>默认产物</span><strong>{String(family.default_artifact_type ?? "按关系边决定")}</strong></p>
          <p><span>输出键</span><strong>{String(family.output_key ?? "按模板决定")}</strong></p>
        </div>
      </section>
      <section className="task-system-inspector-section">
        <header><Boxes size={15} /><strong>关系边</strong><span>这些边会自动使用该契约族</span></header>
        <div className="task-system-chip-list">
          {familyList(family, "relation_ids").map((item) => <span key={item}>{item}</span>)}
        </div>
      </section>
      <section className="task-system-inspector-section">
        <header><Boxes size={15} /><strong>必要设置</strong><span>普通用户只需要覆盖这些字段</span></header>
        <div className="task-system-chip-list">
          {familyList(family, "configurable_fields").map((item) => <span key={item}>{item}</span>)}
        </div>
      </section>
    </div>
  );
}
