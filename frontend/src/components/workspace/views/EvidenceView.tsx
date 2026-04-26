"use client";

import { Bot, GitBranch, Network, Workflow } from "lucide-react";

const agentTracks = [
  {
    title: "Worker Agent",
    kind: "执行型子 agent",
    path: "sub-agent worker",
    description: "承接明确的实现、修复、验证和文件级任务，完成后把结果回传主会话。"
  },
  {
    title: "RAG Agent",
    kind: "检索型子系统",
    path: "backend/query / indexes_v2",
    description: "负责知识库召回、证据整理、文档片段定位和检索结果结构化。"
  },
  {
    title: "PDF / Document Agent",
    kind: "文档型子系统",
    path: "backend/pdf_agent",
    description: "负责 PDF、长文档和页级证据链路，后续可并入统一子 agent 管理。"
  },
  {
    title: "A2A Protocol",
    kind: "通信协议",
    path: "backend/agents/a2a_*",
    description: "约定子 agent 的任务输入、状态同步、产物返回和错误上报方式。"
  }
];

const protocolSteps = [
  "主会话提出任务并生成子 agent 可执行的任务描述。",
  "编排系统选择 worker、RAG 或文档类子 agent。",
  "子 agent 独立执行任务，并返回结构化结果、证据或变更摘要。",
  "主会话合并结果，继续保持同一轮对话状态。"
];

export function EvidenceView() {
  return (
    <div className="workspace-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Agent System</p>
          <h2 className="workspace-view__title">agent系统</h2>
        </div>
        <div className="tag-chip">worker / rag / protocol</div>
      </header>

      <section className="workspace-section workspace-section--hero">
        <div className="workspace-section__head">
          <Bot size={18} />
          <h3>子 agent 入口</h3>
        </div>
        <p className="workspace-copy">
          这里负责展示和管理子 agent 体系，包括 worker、RAG 子系统、文档 agent，以及它们和主会话之间的通信协议。
        </p>
      </section>

      <div className="framework-grid">
        {agentTracks.map((track) => (
          <article className="framework-node" key={track.title}>
            <div className="framework-node__kind">
              <Network size={16} />
              {track.kind}
            </div>
            <h4>{track.title}</h4>
            <p>{track.description}</p>
            <span>{track.path}</span>
          </article>
        ))}
      </div>

      <section className="workspace-section workspace-section--compact">
        <div className="workspace-section__head">
          <GitBranch size={18} />
          <h3>通信流程</h3>
        </div>
        <div className="flow-list">
          {protocolSteps.map((step, index) => (
            <div className="flow-row" key={step}>
              <div className="flow-row__index">{index + 1}</div>
              <p>{step}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="workspace-section workspace-section--compact">
        <div className="workspace-section__head">
          <Workflow size={18} />
          <h3>后续接入</h3>
        </div>
        <p className="workspace-copy">
          后续可以把这里接到实际 agent registry，显示每个子 agent 的在线状态、能力边界、最近任务和通信日志。
        </p>
      </section>
    </div>
  );
}
