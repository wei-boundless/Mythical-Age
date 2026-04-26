"use client";

import { GitBranch, ListChecks, Network, TerminalSquare } from "lucide-react";

const orchestrationNodes = [
  {
    title: "请求入口",
    path: "backend/api",
    description: "接收前端会话请求，并把用户输入、会话状态和运行参数交给后端执行链。"
  },
  {
    title: "运行时装配",
    path: "backend/runtime/app_runtime.py",
    description: "统一准备模型、记忆、检索、工具、技能和子 agent 能力。"
  },
  {
    title: "执行链调度",
    path: "backend/query/runtime.py",
    description: "根据上下文组织 prompt、决定是否检索或调用工具，并维持流式输出。"
  },
  {
    title: "结果回传",
    path: "SSE / session archive",
    description: "把模型输出、工具结果、检索证据和会话状态写回前端与存档。"
  }
];

const orchestrationRules = [
  "先判断当前轮是否需要记忆召回、RAG 检索或工具调用。",
  "工具调用后必须把工具结果和模型续写状态保持在同一执行链里。",
  "长场景中需要持续维护 session 状态，避免 follow-up 轮次漂移。",
  "子 agent、RAG 与 tools 的调用结果要通过统一协议回到主会话。"
];

export function ExperimentsView() {
  return (
    <div className="workspace-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Orchestration System</p>
          <h2 className="workspace-view__title">编排系统</h2>
        </div>
        <div className="tag-chip">调度中枢</div>
      </header>

      <div className="workspace-metrics-grid">
        <div className="workspace-stat">
          <Network size={18} />
          <span>调度对象</span>
          <strong>memory / rag / tools / agents</strong>
        </div>
        <div className="workspace-stat">
          <GitBranch size={18} />
          <span>执行链</span>
          <strong>请求到响应</strong>
        </div>
        <div className="workspace-stat">
          <TerminalSquare size={18} />
          <span>状态目标</span>
          <strong>不断链</strong>
        </div>
      </div>

      <section className="workspace-section">
        <div className="workspace-section__head">
          <Network size={18} />
          <h3>编排节点</h3>
        </div>
        <div className="framework-grid">
          {orchestrationNodes.map((node) => (
            <article className="framework-node" key={node.title}>
              <div className="framework-node__kind">orchestrator</div>
              <h4>{node.title}</h4>
              <p>{node.description}</p>
              <span>{node.path}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <div className="workspace-section__head">
          <ListChecks size={18} />
          <h3>调度约束</h3>
        </div>
        <div className="flow-list">
          {orchestrationRules.map((rule, index) => (
            <div className="flow-row" key={rule}>
              <div className="flow-row__index">{index + 1}</div>
              <p>{rule}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
