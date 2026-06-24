"use client";

import { ArrowUp, Bot, GitBranch, RadioTower, Settings2, Sparkles } from "lucide-react";
import { useState } from "react";
import type { TaskGraphEdgeRecord, TaskGraphNodeRecord } from "@/lib/api";

import { resolveGraphConversationPortBinding } from "../registry/taskGraphConversationPortRegistry";

export function NodeConversationDock({
  edges,
  graphId,
  graphRunId,
  instanceId,
  nodes,
  selectedEdgeId,
  selectedNodeId,
}: {
  graphId: string;
  instanceId?: string;
  graphRunId?: string;
  nodes: TaskGraphNodeRecord[];
  edges: TaskGraphEdgeRecord[];
  selectedNodeId: string;
  selectedEdgeId: string;
}) {
  const [messageDraft, setMessageDraft] = useState("");
  const selectedNode = nodes.find((node) => node.node_id === selectedNodeId) ?? null;
  const selectedEdge = edges.find((edge) => edge.edge_id === selectedEdgeId) ?? null;
  const binding = resolveGraphConversationPortBinding({
    graphId,
    instanceId,
    graphRunId,
    selectedNodeId,
    selectedEdgeId,
  });
  const targetKind = selectedNode ? "节点" : selectedEdge ? "边" : "图";
  const title = selectedNode
    ? selectedNode.title || selectedNode.node_id
    : selectedEdge
      ? `${selectedEdge.source_node_id} → ${selectedEdge.target_node_id}`
      : "图编辑助手";
  const modeLabel = binding?.mode === "node_session"
    ? "运行节点会话"
    : binding?.mode === "node_config"
      ? "节点配置端口"
      : binding?.mode === "edge_contract"
        ? "边契约端口"
        : "图助手";
  const targetLabel = selectedNode
    ? selectedNode.node_id
    : selectedEdge
      ? selectedEdge.edge_id
      : graphId;
  const portIcon = binding?.mode === "node_session"
    ? RadioTower
    : binding?.mode === "edge_contract"
      ? GitBranch
      : binding?.mode === "node_config"
        ? Settings2
        : Bot;
  const PortIcon = portIcon;
  const messagePlaceholder = binding?.mode === "node_session"
    ? "向当前运行节点发送消息"
    : binding?.mode === "node_config"
      ? "输入节点角色、契约或资源调整说明"
      : binding?.mode === "edge_contract"
        ? "输入边交接、payload 或失败策略调整说明"
        : "输入图结构、发布预检或运行编排说明";
  const canSend = Boolean(binding?.session_id && messageDraft.trim());

  return (
    <section className="graph-repository-conversation-dock graph-node-port-dock chat-input-panel chat-input-panel--inline" aria-label="节点会话口">
      <div className="graph-node-port-dock__header">
        <span className="chat-model-select graph-node-port-dock__select" title={modeLabel}>
          <PortIcon size={15} />
          <span className="graph-node-port-dock__select-value">{modeLabel}</span>
        </span>
        <div className="graph-node-port-dock__title">
          <span>{targetKind}</span>
          <strong>{title}</strong>
        </div>
        <span className="graph-node-port-dock__state">
          <Sparkles size={13} />
          {binding?.mode === "node_session" ? "运行投影" : "配置端口"}
        </span>
      </div>
      <div className="chat-input-panel__composer graph-node-port-dock__composer">
        <textarea
          aria-label="输入图任务端口消息"
          className="chat-input-panel__textarea graph-node-port-dock__textarea"
          onChange={(event) => setMessageDraft(event.target.value)}
          placeholder={messagePlaceholder}
          value={messageDraft}
        />
      </div>
      <form
        className="chat-input-panel__footer graph-node-port-dock__footer"
        onSubmit={(event) => {
          event.preventDefault();
        }}
      >
        <div className="chat-input-panel__controls">
          <span className="chat-model-select graph-node-port-dock__select" title={graphId}>
            <Bot size={15} />
            <span className="graph-node-port-dock__select-value">{graphId}</span>
          </span>
          <span className="chat-model-select graph-node-port-dock__select" title={targetLabel}>
            <Settings2 size={15} />
            <span className="graph-node-port-dock__select-value">{targetLabel}</span>
          </span>
          <span className="chat-model-select graph-node-port-dock__select" title={instanceId || "未绑定实例"}>
            <RadioTower size={15} />
            <span className="graph-node-port-dock__select-value">{instanceId || "编辑态"}</span>
          </span>
        </div>
        <div className="chat-input-panel__actions">
          <button
            aria-label="发送端口消息"
            className="chat-send-button"
            disabled={!canSend}
            title={canSend ? "发送端口消息" : "当前端口尚未连接可写节点会话"}
            type="submit"
          >
            <ArrowUp size={18} />
          </button>
        </div>
      </form>
    </section>
  );
}
