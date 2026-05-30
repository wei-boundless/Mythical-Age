"use client";

import { CheckCircle2, ClipboardList, Network } from "lucide-react";

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
    <nav className="task-system-layer-nav task-system-layer-nav--secondary" aria-label="任务域契约页面">
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
  domainContractSpecs,
  onDeleteContract,
  onOpenWorkbench,
  onSaveContract,
  onSelectPanel,
  saving,
  selectedTaskGraphId,
}: {
  contractManagement: TaskSystemOverview["contract_management"] | null;
  contractPanel: ContractPanel;
  contractPanelItems: ContractPanelItem[];
  domainContractSpecs: ContractSpec[];
  onDeleteContract: (contractId: string) => Promise<void>;
  onOpenWorkbench: () => void;
  onSaveContract: (spec: ContractSpec) => Promise<void>;
  onSelectPanel: (panel: ContractPanel) => void;
  saving: string;
  selectedTaskGraphId?: string;
}) {
  return (
    <TaskContractManagementPage>
      <header className="task-management-titlebar">
        <div>
          <span>契约库</span>
          <h3>契约资产</h3>
          <p>这里只维护契约主数据。图、节点、边的绑定关系统一进入图工作台配置。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton disabled={saving === "contract-spec"} onClick={() => onSelectPanel("library")}>
            <ClipboardList size={15} />管理契约
          </ToolbarButton>
          <ToolbarButton onClick={onOpenWorkbench}>
            <Network size={15} />进入图工作台
          </ToolbarButton>
        </div>
      </header>
      <div className="boundary-notice">
        <CheckCircle2 size={16} />
        契约库是资产源；图级、节点级、边级 contract_bindings 在图工作台对象编辑台维护，发布页以执行包验证是否进入运行。
      </div>
      <section className="boundary-layer-stack task-system-contract-center">
        <ContractLayerNav items={contractPanelItems} value={contractPanel} onChange={onSelectPanel} />
        {contractPanel === "library" && contractManagement ? (
          <ContractLibraryPanel
            contractManagement={{ ...contractManagement, contract_specs: domainContractSpecs }}
            onDelete={onDeleteContract}
            onSave={onSaveContract}
            saving={saving === "contract-spec"}
          />
        ) : null}
        {contractPanel === "templates" ? (
          <section className="contract-template-grid">
            <article className="boundary-card contract-template-card">
              <header><div className="boundary-identity-stack"><span>域级模板中心</span><strong>契约草案模板</strong><small>按任务域隔离</small></div></header>
              <p>模板能力只注册契约草案，不直接创建 Agent 或跨域资产。正式节点装配仍由 TaskGraph 和编排资源完成。</p>
            </article>
            <article className="boundary-card contract-template-card">
              <header><div className="boundary-identity-stack"><span>通用模板</span><strong>节点执行契约</strong><small>适用于普通 Agent 节点</small></div></header>
              <p>用于普通 Agent 节点的输入输出边界。字段级模板在契约库中新建后按任务域维护。</p>
            </article>
          </section>
        ) : null}
      </section>
    </TaskContractManagementPage>
  );
}
