"use client";

import { CheckCircle2, Network, Send } from "lucide-react";

import type { OrchestrationAgentRuntimeCatalog } from "@/lib/api";

import { TaskOrchestrationResourcePage } from "../TaskSystemPages";
import { TaskSystemToolbarButton as ToolbarButton } from "../TaskSystemWorkbenchUi";

type ProjectionCardSummary = {
  projection_id: string;
};

export function TaskOrchestrationResourceLibraryPage({
  orchestrationAgentCatalog,
  onOpenOrchestration,
  onOpenWorkbench,
  projectionCards,
  selectedTaskGraphId,
}: {
  orchestrationAgentCatalog: OrchestrationAgentRuntimeCatalog | null;
  onOpenOrchestration: (focus?: { layer?: "registry" | "groups" | "runtime" | "eligibility"; reason?: string }) => void;
  onOpenWorkbench: () => void;
  projectionCards: ProjectionCardSummary[];
  selectedTaskGraphId?: string;
}) {
  const orchestrationAgents = orchestrationAgentCatalog?.agents ?? [];
  const orchestrationProfiles = orchestrationAgentCatalog?.profiles ?? [];

  return (
    <TaskOrchestrationResourcePage>
      <header className="task-management-titlebar">
        <div>
          <span>编排资源</span>
          <h3>Agent 与运行档案</h3>
          <p>这里直接对接编排系统。任务系统负责任务与任务图，编排系统负责 Agent 主数据、投影引用和运行档案。</p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton onClick={() => onOpenOrchestration({ layer: "registry", reason: "从任务系统进入编排控制台：管理 Agent 名册和主数据。" })}>
            <Network size={15} />打开编排控制台
          </ToolbarButton>
          <ToolbarButton onClick={() => onOpenOrchestration({ layer: "runtime", reason: "从任务系统进入运行档案：配置 Agent 的运行边界与装配信息。" })}>
            <Send size={15} />配置运行档案
          </ToolbarButton>
        </div>
      </header>
      <div className="boundary-notice">
        <CheckCircle2 size={16} />
        任务侧只声明节点引用和模型能力需求。Provider Base URL、密钥和运行档案由系统配置与编排系统统一解析。
      </div>
      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong>Agent 库</strong><span>{orchestrationAgentCatalog?.agents?.length ?? 0} agents</span></header>
          <div className="boundary-list boundary-list--scroll">
            {orchestrationAgents.slice(0, 8).map((agent) => (
              <article className="boundary-list-row" key={String(agent.agent_id ?? agent.id ?? agent.agent_name)}>
                <strong>{String(agent.display_name ?? agent.agent_name ?? agent.agent_id ?? "Agent")}</strong>
                <span>{String(agent.agent_id ?? "")}</span>
              </article>
            ))}
            {!orchestrationAgents.length ? <div className="boundary-empty">编排系统暂未加载到 Agent。</div> : null}
          </div>
        </article>
        <article className="boundary-card">
          <header><strong>运行档案</strong><span>{orchestrationProfiles.length} 份</span></header>
          <div className="boundary-list boundary-list--scroll">
            {orchestrationProfiles.slice(0, 8).map((profile) => (
              <article className="boundary-list-row" key={String(profile.agent_profile_id)}>
                <strong>{String(profile.agent_profile_id)}</strong>
                <span>{String(profile.agent_id)} · {profile.allowed_context_sections.length} 上下文段 / {profile.allowed_memory_scopes.length} 记忆范围</span>
              </article>
            ))}
            {!orchestrationProfiles.length ? <div className="boundary-empty">还没有可用于节点装配的运行档案。</div> : null}
          </div>
        </article>
        <article className="boundary-card">
          <header><strong>投影引用</strong><span>{projectionCards.length} 项</span></header>
          <div className="boundary-kv">
            <p><span>职责语言</span><strong>由 Projection / Prompt 主数据提供</strong></p>
            <p><span>节点绑定</span><strong>在图工作台对象编辑台选择引用</strong></p>
            <p><span>资源读写</span><strong>在图工作台资源流配置</strong></p>
            <p><span>运行边界</span><strong>统一进入运行档案</strong></p>
          </div>
        </article>
      </section>
      <section className="boundary-card">
        <header><strong>图节点装配入口</strong><span>由图工作台负责</span></header>
        <div className="boundary-kv">
          <p><span>Agent 主数据</span><strong>编排控制台维护</strong></p>
          <p><span>运行档案</span><strong>编排控制台维护</strong></p>
          <p><span>节点引用</span><strong>图工作台 / 节点对象</strong></p>
          <p><span>模型需求</span><strong>图工作台 / contract_bindings.runtime.model_requirement</strong></p>
        </div>
        <div className="boundary-actions">
          <ToolbarButton disabled={!selectedTaskGraphId} onClick={onOpenWorkbench}>进入图工作台</ToolbarButton>
          <ToolbarButton onClick={() => onOpenOrchestration({ layer: "runtime", reason: "从当前任务图检查所有 Agent 运行档案。" })}>管理运行档案</ToolbarButton>
        </div>
      </section>
    </TaskOrchestrationResourcePage>
  );
}
