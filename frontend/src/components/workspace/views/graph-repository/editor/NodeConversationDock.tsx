"use client";

import { Send, Sparkles } from "lucide-react";
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
  const selectedNode = nodes.find((node) => node.node_id === selectedNodeId) ?? null;
  const selectedEdge = edges.find((edge) => edge.edge_id === selectedEdgeId) ?? null;
  const binding = resolveGraphConversationPortBinding({
    graphId,
    instanceId,
    graphRunId,
    selectedNodeId,
    selectedEdgeId,
  });
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
  const portState = binding?.mode === "node_session"
    ? "等待运行会话"
    : binding?.mode === "node_config"
      ? "可调整配置"
      : binding?.mode === "edge_contract"
        ? "可调整边契约"
        : "可做结构预检";
  const targetLabel = selectedNode
    ? selectedNode.node_id
    : selectedEdge
      ? selectedEdge.edge_id
      : graphId;
  const detail = binding?.mode === "node_session"
    ? "这里聚焦运行节点的会话上下文，适合观察多 agent 协作。"
    : binding?.mode === "node_config"
      ? "这里聚焦当前节点的角色、契约和资源边界。"
      : binding?.mode === "edge_contract"
        ? "边关系只由显式边和契约决定，不从节点位置推断。"
        : "未选中对象时用于检查整体结构、模板缺口和运行风险。";

  return (
    <section className="graph-repository-conversation-dock" aria-label="节点会话口">
      <header>
        <span><Sparkles size={14} />{modeLabel}</span>
        <strong>{title}</strong>
      </header>
      <div className="graph-repository-conversation-body">
        <p>{detail}</p>
        <dl>
          <div>
            <dt>端口</dt>
            <dd>{modeLabel}</dd>
          </div>
          <div>
            <dt>对象</dt>
            <dd>{targetLabel}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>{portState}</dd>
          </div>
        </dl>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
        }}
      >
        <input placeholder="选择运行中的节点会话后可发送消息" />
        <button disabled title="当前端口尚未连接可写会话" type="submit">
          <Send size={14} />
        </button>
      </form>
    </section>
  );
}
