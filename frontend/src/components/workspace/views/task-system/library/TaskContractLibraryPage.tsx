"use client";

import { CheckCircle2, ClipboardList } from "lucide-react";

import type { ContractSpec, TaskSystemOverview } from "@/lib/api";

import { ContractLibraryPanel } from "../ContractLibraryPanel";
import { TaskContractManagementPage } from "../TaskSystemPages";
import { TaskSystemToolbarButton as ToolbarButton } from "../TaskSystemWorkbenchUi";

type ContractPanel = "library" | "templates";

type ContractPanelItem = {
  detail: string;
  label: string;
  meta: string;
  value: ContractPanel;
};

function ContractLayerNav({
  items,
  onChange,
  value,
}: {
  items: ContractPanelItem[];
  onChange: (value: ContractPanel) => void;
  value: ContractPanel;
}) {
  return (
    <nav className="task-system-layer-nav task-system-layer-nav--secondary" aria-label="契约页面">
      {items.map((item) => (
        <button
          className={value === item.value ? "task-system-layer-nav__item task-system-layer-nav__item--active" : "task-system-layer-nav__item"}
          key={item.value}
          onClick={() => onChange(item.value)}
          type="button"
        >
          <span>{item.label}</span>
          <strong>{item.meta}</strong>
          <small>{item.detail}</small>
        </button>
      ))}
    </nav>
  );
}

export function TaskContractLibraryPage({
  contractManagement,
  contractPanel,
  contractPanelItems,
  contractSpecs,
  onDeleteContract,
  onSaveContract,
  onSelectPanel,
  saving,
}: {
  contractManagement: TaskSystemOverview["contract_management"] | null;
  contractPanel: ContractPanel;
  contractPanelItems: ContractPanelItem[];
  contractSpecs: ContractSpec[];
  onDeleteContract: (contractId: string) => Promise<void>;
  onSaveContract: (spec: ContractSpec) => Promise<void>;
  onSelectPanel: (panel: ContractPanel) => void;
  saving: string;
}) {
  return (
    <TaskContractManagementPage>
      <header className="task-management-titlebar">
        <div>
          <span>契约库</span>
          <h3>契约资产</h3>
          <p>这里只维护契约主数据、模板和质量边界，供运行图、节点与边引用。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton disabled={saving === "contract-spec"} onClick={() => onSelectPanel("library")}>
            <ClipboardList size={15} />管理契约
          </ToolbarButton>
        </div>
      </header>
      <div className="boundary-notice">
        <CheckCircle2 size={16} />
        契约库是资产源；它不承载运行图编辑，只提供可被任务运行配置引用的输入输出、载荷和审核标准。
      </div>
      <section className="boundary-layer-stack task-system-contract-center">
        <ContractLayerNav items={contractPanelItems} value={contractPanel} onChange={onSelectPanel} />
        {contractPanel === "library" && contractManagement ? (
          <ContractLibraryPanel
            contractManagement={{ ...contractManagement, contract_specs: contractSpecs }}
            onDelete={onDeleteContract}
            onSave={onSaveContract}
            saving={saving === "contract-spec"}
          />
        ) : null}
        {contractPanel === "templates" ? (
          <section className="contract-template-grid">
            <article className="boundary-card contract-template-card">
              <header><div className="boundary-identity-stack"><span>模板中心</span><strong>契约草案模板</strong><small>按用途管理</small></div></header>
              <p>模板能力只注册契约草案，不直接创建 Agent 或跨边界资产。正式装配由运行侧配置引用契约资产。</p>
            </article>
            <article className="boundary-card contract-template-card">
              <header><div className="boundary-identity-stack"><span>通用模板</span><strong>节点执行契约</strong><small>适用于普通 Agent 节点</small></div></header>
              <p>用于普通 Agent 节点的输入输出边界。字段级模板在契约库中新建后维护。</p>
            </article>
          </section>
        ) : null}
      </section>
    </TaskContractManagementPage>
  );
}
