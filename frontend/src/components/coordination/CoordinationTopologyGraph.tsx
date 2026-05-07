"use client";

import type { ReactNode } from "react";

import { Network } from "lucide-react";

export type CoordinationTopologyNode = {
  id: string;
  title: string;
  agentLabel?: string;
  role?: string;
  status?: string;
};

export type CoordinationTopologyEdge = {
  id: string;
  from: string;
  to: string;
  label?: string;
  status?: string;
};

type TopologyNodeLayout = CoordinationTopologyNode & {
  x: number;
  y: number;
  shortLabel: string;
};

type TopologyEdgeLayout = CoordinationTopologyEdge & {
  path: string;
  current: boolean;
  toolX: number;
  toolY: number;
};

type TopologyLayout = {
  width: number;
  height: number;
  nodes: TopologyNodeLayout[];
  edges: TopologyEdgeLayout[];
};

function shortNodeGlyph(label: string) {
  const compact = label.replace(/\s+/g, "");
  return compact.slice(0, Math.min(2, compact.length)) || "A";
}

function statusClass(status = "") {
  if (status === "completed" || status === "success") {
    return "is-complete";
  }
  if (status === "running") {
    return "is-running";
  }
  if (status === "failed") {
    return "is-failed";
  }
  return "is-idle";
}

export function buildCoordinationTopologyLayout(
  nodes: CoordinationTopologyNode[],
  edges: CoordinationTopologyEdge[],
  currentNodeId = "",
  currentHandoffKey = "",
): TopologyLayout {
  if (!nodes.length) {
    return {
      width: 760,
      height: 320,
      nodes: [],
      edges: [],
    };
  }

  const nodeCount = nodes.length;
  const columns = nodeCount <= 4 ? nodeCount : Math.min(4, Math.ceil(nodeCount / 2));
  const rows = Math.ceil(nodeCount / columns);
  const xGap = 220;
  const yGap = 210;
  const sidePadding = 120;
  const topPadding = 120;
  const bottomPadding = 120;
  const width = Math.max(760, sidePadding * 2 + Math.max(columns - 1, 0) * xGap);
  const height = Math.max(300, topPadding + bottomPadding + Math.max(rows - 1, 0) * yGap);
  const positioned = new Map<string, TopologyNodeLayout>();

  for (let row = 0; row < rows; row += 1) {
    const rowStart = row * columns;
    const remaining = nodeCount - rowStart;
    const rowCount = Math.min(columns, remaining);
    for (let offset = 0; offset < rowCount; offset += 1) {
      const index = rowStart + offset;
      const visualColumn = row % 2 === 0 ? offset : rowCount - 1 - offset;
      const centeringOffset = (columns - rowCount) / 2;
      const x = sidePadding + (visualColumn + centeringOffset) * xGap;
      const y = topPadding + row * yGap;
      const node = nodes[index];
      positioned.set(node.id, {
        ...node,
        x,
        y,
        shortLabel: shortNodeGlyph(node.agentLabel || node.title),
      });
    }
  }

  const edgeLayouts = edges
    .map((edge): TopologyEdgeLayout | null => {
      const from = positioned.get(edge.from);
      const to = positioned.get(edge.to);
      if (!from || !to) {
        return null;
      }
      const middleX = (from.x + to.x) / 2;
      return {
        ...edge,
        current:
          `${edge.from}->${edge.to}` === currentHandoffKey
          || edge.from === currentNodeId
          || edge.to === currentNodeId,
        path: `M ${from.x} ${from.y} C ${middleX} ${from.y}, ${middleX} ${to.y}, ${to.x} ${to.y}`,
        toolX: middleX,
        toolY: (from.y + to.y) / 2,
      };
    })
    .filter((edge): edge is TopologyEdgeLayout => Boolean(edge));

  return {
    width,
    height,
    nodes: Array.from(positioned.values()),
    edges: edgeLayouts,
  };
}

export function CoordinationTopologyGraph({
  nodes,
  edges,
  currentNodeId = "",
  currentHandoffKey = "",
  emptyTitle = "协调任务已启动，正在等待拓扑数据",
  emptyDescription = "节点与交接关系会在后续运行事件到达后显示。",
  onSelectNode,
  onSelectEdge,
  onConnectNode,
  renderNodeTools,
  renderEdgeTools,
  selectedNodeId = "",
  selectedEdgeId = "",
  linkingFromNodeId = "",
}: {
  nodes: CoordinationTopologyNode[];
  edges: CoordinationTopologyEdge[];
  currentNodeId?: string;
  currentHandoffKey?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  onSelectNode?: (nodeId: string) => void;
  onSelectEdge?: (edgeId: string) => void;
  onConnectNode?: (nodeId: string) => void;
  renderNodeTools?: (node: CoordinationTopologyNode) => ReactNode;
  renderEdgeTools?: (edge: CoordinationTopologyEdge) => ReactNode;
  selectedNodeId?: string;
  selectedEdgeId?: string;
  linkingFromNodeId?: string;
}) {
  const topology = buildCoordinationTopologyLayout(nodes, edges, currentNodeId, currentHandoffKey);

  if (!topology.nodes.length) {
    return (
      <div className="coordination-topology-empty">
        <Network size={18} />
        <strong>{emptyTitle}</strong>
        <p>{emptyDescription}</p>
      </div>
    );
  }

  return (
    <svg viewBox={`0 0 ${topology.width} ${topology.height}`} aria-label="协调任务拓扑图" role="img">
      <defs>
        <filter id="coordination-node-glow" x="-120%" y="-120%" width="340%" height="340%">
          <feGaussianBlur stdDeviation="10" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <marker
          id="coordination-topology-arrow"
          markerWidth="10"
          markerHeight="10"
          refX="9"
          refY="5"
          markerUnits="strokeWidth"
          orient="auto"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" className="coordination-topology-arrowhead" />
        </marker>
      </defs>
      <g>
        {topology.edges.map((edge) => {
          const selected = edge.id === selectedEdgeId;
          return (
            <g key={edge.id}>
              <path
                className={`coordination-topology-edge ${statusClass(edge.status)} ${edge.current ? "is-current" : ""} ${selected ? "is-selected" : ""}`}
                d={edge.path}
                markerEnd="url(#coordination-topology-arrow)"
                onClick={() => onSelectEdge?.(edge.id)}
              />
              {renderEdgeTools && selected ? (
                <foreignObject
                  className="coordination-topology-edge-tools"
                  height="40"
                  width="132"
                  x={edge.toolX - 66}
                  y={edge.toolY - 20}
                >
                  <div className="coordination-topology-node-tools__bar">
                    {renderEdgeTools(edge)}
                  </div>
                </foreignObject>
              ) : null}
            </g>
          );
        })}
      </g>
      <g>
        {topology.nodes.map((node) => {
          const current = node.id === currentNodeId;
          const selected = node.id === selectedNodeId;
          const linking = node.id === linkingFromNodeId;
          const clickable = Boolean(onSelectNode || onConnectNode);
          return (
            <g
              className={clickable ? "coordination-topology-node-group is-clickable" : "coordination-topology-node-group"}
              key={node.id}
              onClick={() => {
                if (onConnectNode) {
                  onConnectNode(node.id);
                  return;
                }
                onSelectNode?.(node.id);
              }}
              transform={`translate(${node.x}, ${node.y})`}
            >
              <text className={`coordination-topology-agent-label ${current || selected || linking ? "is-current" : ""}`} textAnchor="middle" x="0" y="-56">
                {node.agentLabel || node.title}
              </text>
              <circle
                className={`coordination-topology-node-halo ${statusClass(node.status)} ${current ? "is-current" : ""} ${selected ? "is-selected" : ""} ${linking ? "is-linking" : ""}`}
                cx="0"
                cy="0"
                filter={current ? "url(#coordination-node-glow)" : undefined}
                r="30"
              />
              <circle className={`coordination-topology-node-surface ${statusClass(node.status)} ${current ? "is-current" : ""} ${selected ? "is-selected" : ""} ${linking ? "is-linking" : ""}`} cx="0" cy="0" r="20" />
              <text className="coordination-topology-node-glyph" textAnchor="middle" x="0" y="5">
                {node.shortLabel}
              </text>
              <text className={`coordination-topology-node-title ${current || selected || linking ? "is-current" : ""}`} textAnchor="middle" x="0" y="52">
                {node.title}
              </text>
              {renderNodeTools && selected ? (
                <foreignObject className="coordination-topology-node-tools" height="40" width="132" x="-66" y="68">
                  <div className="coordination-topology-node-tools__bar">
                    {renderNodeTools(node)}
                  </div>
                </foreignObject>
              ) : null}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
