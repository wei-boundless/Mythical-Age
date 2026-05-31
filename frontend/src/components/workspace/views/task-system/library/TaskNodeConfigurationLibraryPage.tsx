"use client";

import { CheckCircle2, Cpu, ShieldCheck } from "lucide-react";

import type { OrchestrationAgentRuntimeCatalog } from "@/lib/api";

import { TaskNodeConfigurationPage } from "../TaskSystemPages";

export function TaskNodeConfigurationLibraryPage({
  nodeRuntimeCatalog,
}: {
  nodeRuntimeCatalog: OrchestrationAgentRuntimeCatalog | null;
}) {
  const nodeExecutorOptions = nodeRuntimeCatalog?.agents ?? [];
  const nodeRuntimeProfiles = nodeRuntimeCatalog?.profiles ?? [];
  const capabilityItems = nodeRuntimeCatalog?.options?.capability_items ?? [];
  const enabledProfileCount = nodeRuntimeProfiles.filter((profile) => profile.enabled_runtime_modes?.length || profile.default_runtime_mode).length;

  return (
    <TaskNodeConfigurationPage>
      <header className="task-management-titlebar">
        <div>
          <span>节点配置</span>
          <h3>节点装配边界</h3>
          <p>这里定义任务环境内节点可引用的执行者、运行档案、模型能力和权限边界；不维护执行者注册信息，也不承载运行图编辑。</p>
        </div>
      </header>
      <div className="boundary-notice">
        <CheckCircle2 size={16} />
        节点配置只保存引用关系和约束条件；Provider Base URL、密钥、执行者名册和运行档案实体由系统配置与运行资源注册表解析。
      </div>
      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong>可选执行者</strong><span>{nodeRuntimeCatalog?.agents?.length ?? 0} agents</span></header>
          <div className="boundary-list boundary-list--scroll">
            {nodeExecutorOptions.slice(0, 8).map((agent) => (
              <article className="boundary-list-row" key={String(agent.agent_id ?? agent.id ?? agent.agent_name)}>
                <strong>{String(agent.display_name ?? agent.agent_name ?? agent.agent_id ?? "Agent")}</strong>
                <span>{String(agent.agent_id ?? "")}</span>
              </article>
            ))}
            {!nodeExecutorOptions.length ? <div className="boundary-empty">暂未加载到可供节点引用的执行者。</div> : null}
          </div>
        </article>
        <article className="boundary-card">
          <header><strong>运行档案引用</strong><span>{nodeRuntimeProfiles.length} 份</span></header>
          <div className="boundary-list boundary-list--scroll">
            {nodeRuntimeProfiles.slice(0, 8).map((profile) => (
              <article className="boundary-list-row" key={String(profile.agent_profile_id)}>
                <strong>{String(profile.agent_profile_id)}</strong>
                <span>{String(profile.agent_id)} · {profile.allowed_context_sections.length} 上下文段 / {profile.allowed_memory_scopes.length} 记忆范围</span>
              </article>
            ))}
            {!nodeRuntimeProfiles.length ? <div className="boundary-empty">还没有可用于节点装配的运行档案。</div> : null}
          </div>
        </article>
        <article className="boundary-card">
          <header><strong>节点边界</strong><span>Node runtime</span></header>
          <div className="boundary-kv">
            <p><span>节点职责</span><strong>由节点角色 Prompt 和契约定义</strong></p>
            <p><span>执行者引用</span><strong>节点只引用已注册执行者</strong></p>
            <p><span>运行档案引用</span><strong>节点只绑定运行档案 ID</strong></p>
            <p><span>权限边界</span><strong>任务环境、契约和运行档案共同约束</strong></p>
          </div>
        </article>
      </section>
      <section className="boundary-card">
        <header><strong>节点配置检查点</strong><span>Reference / Capability</span></header>
        <div className="boundary-kv">
          <p><span>执行者候选</span><strong>{nodeExecutorOptions.length} 个可引用 Agent</strong></p>
          <p><span>可用运行档案</span><strong>{enabledProfileCount || nodeRuntimeProfiles.length} 份可用于节点绑定</strong></p>
          <p><span>模型能力</span><strong>由节点需求、运行档案和 Provider 配置共同解析</strong></p>
          <p><span>能力条目</span><strong>{capabilityItems.length} 个工具 / 技能 / 操作候选</strong></p>
        </div>
      </section>
      <section className="task-system-task-cover">
        <article className="boundary-card">
          <header><strong><Cpu size={15} />模型能力约束</strong><span>Node requirement</span></header>
          <div className="boundary-kv">
            <p><span>能力标签</span><strong>节点声明所需推理、代码、检索或长文本能力</strong></p>
            <p><span>输出预算</span><strong>由节点长度策略与模型上限共同裁决</strong></p>
            <p><span>流式要求</span><strong>节点可声明是否必须支持 streaming</strong></p>
          </div>
        </article>
        <article className="boundary-card">
          <header><strong><ShieldCheck size={15} />权限与契约</strong><span>Policy merge</span></header>
          <div className="boundary-kv">
            <p><span>输入输出</span><strong>来自契约库，不在节点内复制主数据</strong></p>
            <p><span>工具上限</span><strong>运行档案给出上限，任务环境继续收窄</strong></p>
            <p><span>失败处理</span><strong>节点必须声明可恢复、重试和人工介入边界</strong></p>
          </div>
        </article>
      </section>
    </TaskNodeConfigurationPage>
  );
}
