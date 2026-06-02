"use client";

import { ArrowRightLeft, Link2, Plus, Trash2 } from "lucide-react";

import { CoordinationTopologyGraph as TaskGraphTopologyCanvas } from "@/components/coordination/CoordinationTopologyGraph";

type CanvasNode = {
  id: string;
  title: string;
  agentLabel?: string;
  role?: string;
  nodeKind?: string;
  status?: string;
};

type CanvasEdge = {
  id: string;
  from: string;
  to: string;
  label?: string;
  edgeKind?: string;
  status?: string;
};

export function TaskGraphCanvasPanel({
  disabled,
  edgeCount,
  edges,
  entryNodeId,
  filteredEdgeCount,
  linkingFromNodeId,
  nodes,
  onAddSuccessor,
  onReverseEdge,
  onSelectEdge,
  onSelectNode,
  onSetLinkingFrom,
  onRemoveEdge,
  outputNodeId,
  selectedEdgeId,
  selectedNodeId,
  title,
}: {
  disabled: boolean;
  edgeCount: number;
  edges: CanvasEdge[];
  entryNodeId: string;
  filteredEdgeCount: number;
  linkingFromNodeId: string;
  nodes: CanvasNode[];
  onAddSuccessor: (nodeId: string) => void;
  onReverseEdge: (edgeId: string) => void;
  onSelectEdge: (edgeId: string) => void;
  onSelectNode: (nodeId: string) => void;
  onSetLinkingFrom: (nodeId: string) => void;
  onRemoveEdge: (edgeId: string) => void;
  outputNodeId: string;
  selectedEdgeId: string;
  selectedNodeId: string;
  title: string;
}) {
  return (
    <main className="task-graph-canvas-panel">
      <header className="task-graph-canvas-panel__head">
        <div>
          <span>任务图编辑</span>
          <strong>{title}</strong>
        </div>
        <div className="task-graph-topology-metrics" aria-label="拓扑计数">
          <span>{nodes.length} 节点</span>
          <span>{filteredEdgeCount}/{edgeCount} 边</span>
          <span>{entryNodeId || "无入口"} {"->"} {outputNodeId || "无出口"}</span>
        </div>
      </header>
      {linkingFromNodeId ? (
        <div className="task-graph-linking-hint" role="status">
          <strong>正在建立关系</strong>
          <span>起点 {linkingFromNodeId}。选择终点后用左侧关系下拉应用语义关系。</span>
        </div>
      ) : null}
      <div className="coordination-topology-viewport coordination-topology-viewport--builder task-graph-topology-viewport">
        <TaskGraphTopologyCanvas
          edges={edges}
          emptyDescription="先用左侧添加节点创建角色或资源，再用关系下拉连接节点。"
          emptyTitle="当前任务图还没有拓扑节点"
          linkingFromNodeId={linkingFromNodeId}
          nodes={nodes}
          onSelectEdge={onSelectEdge}
          onSelectNode={onSelectNode}
          renderEdgeTools={(edge) => (
            <>
              <button disabled={disabled} onClick={() => onReverseEdge(edge.id)} title="反转边" type="button">
                <ArrowRightLeft size={13} />
              </button>
              <button disabled={disabled} onClick={() => onRemoveEdge(edge.id)} title="删除边" type="button">
                <Trash2 size={13} />
              </button>
            </>
          )}
          renderNodeTools={(node) => (
            <>
              <button disabled={disabled} onClick={() => onSetLinkingFrom(node.id)} title="设为关系起点" type="button">
                <Link2 size={13} />
              </button>
              <button disabled={disabled} onClick={() => onAddSuccessor(node.id)} title="添加后继节点" type="button">
                <Plus size={13} />
              </button>
            </>
          )}
          selectedEdgeId={selectedEdgeId}
          selectedNodeId={selectedNodeId}
        />
      </div>
    </main>
  );
}
