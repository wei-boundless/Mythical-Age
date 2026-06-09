"use client";

import { AlertTriangle, CheckCircle2, RefreshCw, UserCog } from "lucide-react";
import type { ReactNode } from "react";

import { OrchestrationToolbarButton } from "./OrchestrationWorkbenchUi";
import type { OrchestrationAssemblyController } from "./useOrchestrationAssemblyController";

export function OrchestrationAssemblyShell({
  children,
  controller,
  directory,
}: {
  children: ReactNode;
  controller: OrchestrationAssemblyController;
  directory: ReactNode;
}) {
  return (
    <div className="workspace-view boundary-console orchestration-boundary orchestration-console">
      <header className="orchestration-console-head">
        <div className="orchestration-console-head__title">
          <span>Agent Assembly</span>
          <h2>编排系统</h2>
          <p>{controller.agents.length} 个 Agent / {controller.agentGroups.length} 个分组 / {controller.catalog?.profiles?.length ?? 0} 个运行档案</p>
        </div>
        <div className="orchestration-console-head__summary" aria-label="对象摘要">
          <div>
            <span>当前装配对象</span>
            <strong>{controller.focusSummary.title}</strong>
            <small>{controller.focusSummary.body}</small>
          </div>
          <div>
            <span>当前步骤</span>
            <strong>{controller.activeLayerLabel}</strong>
            <small>{controller.activeLayerHint}</small>
          </div>
          <div>
            <span>对象类型</span>
            <strong>{controller.selectionKindLabel}</strong>
            <small>{controller.focusSummary.id}</small>
          </div>
          <div>
            <span>运行权限</span>
            <strong>{controller.allowedOps.length} 允 / {controller.blockedOps.length} 阻</strong>
            <small>{controller.overlapOps.length ? `${controller.overlapOps.length} 项冲突` : "无冲突"}</small>
          </div>
        </div>
        <div className="boundary-actions orchestration-console-head__actions">
          <OrchestrationToolbarButton onClick={controller.startBlankAgentDraft}>
            <UserCog size={15} />
            新建 Agent
          </OrchestrationToolbarButton>
          <OrchestrationToolbarButton onClick={() => void controller.load()}>
            <RefreshCw size={15} />
            刷新
          </OrchestrationToolbarButton>
        </div>
      </header>

      {controller.error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{controller.error}</div> : null}
      {controller.notice ? <div className="boundary-notice"><CheckCircle2 size={16} />{controller.notice}</div> : null}

      <section className="boundary-workbench orchestration-workbench orchestration-definition-center">
        {directory}
        <main className="boundary-main orchestration-config-main">
          {children}
        </main>
      </section>
    </div>
  );
}
