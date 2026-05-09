"use client";

import { useState, type MouseEvent, type ReactNode } from "react";

export type CoordinationTopologyNode = {
  id: string;
  title: string;
  agentLabel?: string;
  role?: string;
  nodeKind?: string;
  status?: string;
};

export type CoordinationTopologyEdge = {
  id: string;
  from: string;
  to: string;
  label?: string;
  status?: string;
};

export type CoordinationTopologyFrame = {
  id: string;
  title: string;
  frameType: string;
  nodeIds: string[];
  edgeIds?: string[];
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
  compact: boolean;
  dense: boolean;
  nodes: TopologyNodeLayout[];
  edges: TopologyEdgeLayout[];
};

function shortNodeGlyph(label: string) {
  const compact = label.replace(/\s+/g, "");
  return compact.slice(0, Math.min(2, compact.length)) || "A";
}

function statusClass(status = "") {
  if (status === "completed" || status === "success" || status === "satisfied") {
    return "is-complete";
  }
  if (status === "running") {
    return "is-running";
  }
  if (status === "failed") {
    return "is-failed";
  }
  if (status === "blocked") {
    return "is-blocked";
  }
  if (status === "waiting" || status === "waiting_for_human" || status === "human_gate") {
    return "is-waiting";
  }
  if (status === "ready") {
    return "is-ready";
  }
  if (status === "pending_retry") {
    return "is-ready";
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
      compact: false,
      dense: false,
      nodes: [],
      edges: [],
    };
  }

  const nodeCount = nodes.length;
  const compact = nodeCount >= 6;
  const dense = nodeCount >= 10;
  const columns = nodeCount <= 4
    ? nodeCount
    : dense
      ? Math.min(6, Math.ceil(nodeCount / 2))
      : Math.min(5, Math.ceil(nodeCount / 2));
  const rows = Math.ceil(nodeCount / columns);
  const xGap = dense ? 154 : compact ? 176 : 220;
  const yGap = dense ? 146 : compact ? 174 : 210;
  const sidePadding = dense ? 70 : compact ? 88 : 120;
  const topPadding = dense ? 82 : compact ? 96 : 120;
  const bottomPadding = dense ? 88 : compact ? 100 : 120;
  const width = Math.max(760, sidePadding * 2 + Math.max(columns - 1, 0) * xGap);
  const height = Math.max(dense ? 280 : 300, topPadding + bottomPadding + Math.max(rows - 1, 0) * yGap);
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
    compact,
    dense,
    nodes: Array.from(positioned.values()),
    edges: edgeLayouts,
  };
}

export function CoordinationTopologyGraph({
  nodes,
  edges,
  frames = [],
  currentNodeId = "",
  currentHandoffKey = "",
  emptyTitle = "协调任务已启动，正在等待拓扑数据",
  emptyDescription = "节点与交接关系会在后续运行事件到达后显示。",
  onSelectNode,
  onSelectEdge,
  onSelectFrame,
  onBoxSelect,
  onConnectNode,
  onNodeContextMenu,
  onEdgeContextMenu,
  onCanvasContextMenu,
  renderNodeTools,
  renderEdgeTools,
  selectedNodeId = "",
  selectedEdgeId = "",
  selectedNodeIds = [],
  selectedEdgeIds = [],
  selectedFrameIds = [],
  linkingFromNodeId = "",
}: {
  nodes: CoordinationTopologyNode[];
  edges: CoordinationTopologyEdge[];
  frames?: CoordinationTopologyFrame[];
  currentNodeId?: string;
  currentHandoffKey?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  onSelectNode?: (nodeId: string, event?: MouseEvent<SVGGElement>) => void;
  onSelectEdge?: (edgeId: string, event?: MouseEvent<SVGPathElement>) => void;
  onSelectFrame?: (frameId: string, event?: MouseEvent<SVGGElement>) => void;
  onBoxSelect?: (selection: { nodeIds: string[]; edgeIds: string[] }) => void;
  onConnectNode?: (nodeId: string) => void;
  onNodeContextMenu?: (nodeId: string, event: MouseEvent<SVGGElement>) => void;
  onEdgeContextMenu?: (edgeId: string, event: MouseEvent<SVGPathElement>) => void;
  onCanvasContextMenu?: (event: MouseEvent<SVGSVGElement>) => void;
  renderNodeTools?: (node: CoordinationTopologyNode) => ReactNode;
  renderEdgeTools?: (edge: CoordinationTopologyEdge) => ReactNode;
  selectedNodeId?: string;
  selectedEdgeId?: string;
  selectedNodeIds?: string[];
  selectedEdgeIds?: string[];
  selectedFrameIds?: string[];
  linkingFromNodeId?: string;
}) {
  const [boxSelect, setBoxSelect] = useState<{ active: boolean; startX: number; startY: number; endX: number; endY: number }>({
    active: false,
    startX: 0,
    startY: 0,
    endX: 0,
    endY: 0,
  });
  const topology = buildCoordinationTopologyLayout(nodes, edges, currentNodeId, currentHandoffKey);
  const haloRadius = topology.dense ? 22 : topology.compact ? 26 : 30;
  const surfaceRadius = topology.dense ? 14 : topology.compact ? 17 : 20;
  const agentLabelY = topology.dense ? -42 : topology.compact ? -48 : -56;
  const titleY = topology.dense ? 38 : topology.compact ? 44 : 52;
  const glyphY = topology.dense ? 4 : 5;
  const nodeToolsY = topology.dense ? 50 : topology.compact ? 58 : 68;
  const nodeToolsX = topology.dense ? -54 : -66;
  const nodeToolsWidth = topology.dense ? 108 : 132;
  const edgeToolsWidth = topology.dense ? 112 : 132;
  const edgeToolsHalfWidth = edgeToolsWidth / 2;
  const nodeLayoutById = new Map(topology.nodes.map((node) => [node.id, node]));
  const frameLayouts = frames
    .map((frame) => {
      const frameNodes = frame.nodeIds.map((nodeId) => nodeLayoutById.get(nodeId)).filter((node): node is TopologyNodeLayout => Boolean(node));
      if (!frameNodes.length) return null;
      const paddingX = topology.dense ? 54 : topology.compact ? 64 : 78;
      const paddingY = topology.dense ? 58 : topology.compact ? 70 : 82;
      const minX = Math.min(...frameNodes.map((node) => node.x)) - paddingX;
      const maxX = Math.max(...frameNodes.map((node) => node.x)) + paddingX;
      const minY = Math.min(...frameNodes.map((node) => node.y)) - paddingY;
      const maxY = Math.max(...frameNodes.map((node) => node.y)) + paddingY;
      return {
        ...frame,
        x: Math.max(12, minX),
        y: Math.max(12, minY),
        width: Math.min(topology.width - Math.max(12, minX) - 12, maxX - minX),
        height: Math.min(topology.height - Math.max(12, minY) - 12, maxY - minY),
      };
    })
    .filter((frame): frame is CoordinationTopologyFrame & { x: number; y: number; width: number; height: number } => Boolean(frame));

  function svgPoint(event: MouseEvent<SVGSVGElement>) {
    const svg = event.currentTarget;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(svg.getScreenCTM()?.inverse());
  }

  function normalizedBox() {
    const x = Math.min(boxSelect.startX, boxSelect.endX);
    const y = Math.min(boxSelect.startY, boxSelect.endY);
    return {
      x,
      y,
      width: Math.abs(boxSelect.endX - boxSelect.startX),
      height: Math.abs(boxSelect.endY - boxSelect.startY),
    };
  }

  if (!topology.nodes.length) {
    return (
      <div className="coordination-topology-empty">
        <div className="coordination-topology-empty__copy">
          <strong>{emptyTitle}</strong>
          <p>{emptyDescription}</p>
        </div>
      </div>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${topology.width} ${topology.height}`}
      aria-label="协调任务拓扑图"
      onContextMenu={(event) => {
        event.preventDefault();
        onCanvasContextMenu?.(event);
      }}
      onMouseDown={(event) => {
        if (!onBoxSelect || event.button !== 0) return;
        const targetElement = event.target as Element;
        if (targetElement.closest(".coordination-topology-node-group, .coordination-topology-edge, .coordination-topology-frame")) return;
        const point = svgPoint(event);
        setBoxSelect({ active: true, startX: point.x, startY: point.y, endX: point.x, endY: point.y });
      }}
      onMouseMove={(event) => {
        if (!boxSelect.active) return;
        const point = svgPoint(event);
        setBoxSelect((current) => ({ ...current, endX: point.x, endY: point.y }));
      }}
      onMouseUp={() => {
        if (!boxSelect.active) return;
        const box = normalizedBox();
        setBoxSelect((current) => ({ ...current, active: false }));
        if (box.width < 8 || box.height < 8) return;
        const nodeIds = topology.nodes
          .filter((node) => node.x >= box.x && node.x <= box.x + box.width && node.y >= box.y && node.y <= box.y + box.height)
          .map((node) => node.id);
        const edgeIds = topology.edges
          .filter((edge) => edge.toolX >= box.x && edge.toolX <= box.x + box.width && edge.toolY >= box.y && edge.toolY <= box.y + box.height)
          .map((edge) => edge.id);
        onBoxSelect?.({ nodeIds, edgeIds });
      }}
      role="img"
    >
      <defs>
        <radialGradient id="coordination-node-core" cx="35%" cy="30%" r="70%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.82)" />
          <stop offset="38%" stopColor="rgba(255,255,255,0.26)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0.04)" />
        </radialGradient>
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
      {frameLayouts.length ? (
        <g className="coordination-topology-frames">
          {frameLayouts.map((frame) => {
            const selected = selectedFrameIds.includes(frame.id);
            return (
              <g
                className={selected ? "coordination-topology-frame coordination-topology-frame--selected" : "coordination-topology-frame"}
                key={frame.id}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectFrame?.(frame.id, event);
                }}
              >
                <rect
                  className={`coordination-topology-frame__rect coordination-topology-frame__rect--${frame.frameType}`}
                  height={frame.height}
                  rx="10"
                  width={frame.width}
                  x={frame.x}
                  y={frame.y}
                />
                <text className="coordination-topology-frame__label" x={frame.x + 12} y={frame.y + 20}>
                  {frame.title}
                </text>
                <text className="coordination-topology-frame__meta" x={frame.x + 12} y={frame.y + 36}>
                  {frame.frameType} · {frame.nodeIds.length} nodes
                </text>
              </g>
            );
          })}
        </g>
      ) : null}
      <g>
        {topology.edges.map((edge) => {
          const selected = edge.id === selectedEdgeId || selectedEdgeIds.includes(edge.id);
          return (
            <g key={edge.id}>
              <path
                className={`coordination-topology-edge ${statusClass(edge.status)} ${edge.current ? "is-current" : ""} ${selected ? "is-selected" : ""}`}
                d={edge.path}
                markerEnd="url(#coordination-topology-arrow)"
                onClick={(event) => onSelectEdge?.(edge.id, event)}
                onContextMenu={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onEdgeContextMenu?.(edge.id, event);
                }}
              />
              {renderEdgeTools && selected ? (
                <foreignObject
                  className="coordination-topology-edge-tools"
                  height="40"
                  width={edgeToolsWidth}
                  x={edge.toolX - edgeToolsHalfWidth}
                  y={topology.dense ? edge.toolY - 18 : edge.toolY - 20}
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
          const selected = node.id === selectedNodeId || selectedNodeIds.includes(node.id);
          const linking = node.id === linkingFromNodeId;
          const clickable = Boolean(onSelectNode || onConnectNode);
          const isMemoryNode = node.nodeKind === "memory" || node.role === "memory";
          return (
            <g
              className={clickable ? "coordination-topology-node-group is-clickable" : "coordination-topology-node-group"}
              key={node.id}
              onClick={(event) => {
                if (onConnectNode) {
                  onConnectNode(node.id);
                  return;
                }
                onSelectNode?.(node.id, event);
              }}
              onContextMenu={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onNodeContextMenu?.(node.id, event);
              }}
              transform={`translate(${node.x}, ${node.y})`}
            >
              <text className={`coordination-topology-agent-label ${topology.compact ? "is-compact" : ""} ${current || selected || linking ? "is-current" : ""}`} textAnchor="middle" x="0" y={agentLabelY}>
                {node.agentLabel || node.title}
              </text>
              {isMemoryNode ? (
                <>
                  <rect
                    className={`coordination-topology-node-halo coordination-topology-node-halo--memory ${statusClass(node.status)} ${current ? "is-current" : ""} ${selected ? "is-selected" : ""} ${linking ? "is-linking" : ""}`}
                    filter={current ? "url(#coordination-node-glow)" : undefined}
                    height={haloRadius * 1.62}
                    rx="8"
                    width={haloRadius * 1.62}
                    x={-haloRadius * 0.81}
                    y={-haloRadius * 0.81}
                  />
                  <rect
                    className={`coordination-topology-node-surface coordination-topology-node-surface--memory ${statusClass(node.status)} ${current ? "is-current" : ""} ${selected ? "is-selected" : ""} ${linking ? "is-linking" : ""}`}
                    height={surfaceRadius * 1.72}
                    rx="6"
                    width={surfaceRadius * 1.72}
                    x={-surfaceRadius * 0.86}
                    y={-surfaceRadius * 0.86}
                  />
                  <rect className="coordination-topology-node-core coordination-topology-node-core--memory" height={Math.max(12, surfaceRadius * 0.9)} rx="4" width={Math.max(12, surfaceRadius * 0.9)} x={-Math.max(12, surfaceRadius * 0.9) / 2} y={-Math.max(12, surfaceRadius * 0.9) / 2} />
                </>
              ) : (
                <>
                  <circle
                    className={`coordination-topology-node-halo ${statusClass(node.status)} ${current ? "is-current" : ""} ${selected ? "is-selected" : ""} ${linking ? "is-linking" : ""}`}
                    cx="0"
                    cy="0"
                    filter={current ? "url(#coordination-node-glow)" : undefined}
                    r={haloRadius}
                  />
                  <circle className={`coordination-topology-node-surface ${statusClass(node.status)} ${current ? "is-current" : ""} ${selected ? "is-selected" : ""} ${linking ? "is-linking" : ""}`} cx="0" cy="0" r={surfaceRadius} />
                  <circle className="coordination-topology-node-core" cx="0" cy="0" r={Math.max(7, surfaceRadius * 0.48)} />
                </>
              )}
              <text className={`coordination-topology-node-glyph ${topology.compact ? "is-compact" : ""}`} textAnchor="middle" x="0" y={glyphY}>
                {node.shortLabel}
              </text>
              <text className={`coordination-topology-node-title ${topology.compact ? "is-compact" : ""} ${current || selected || linking ? "is-current" : ""}`} textAnchor="middle" x="0" y={titleY}>
                {node.title}
              </text>
              {renderNodeTools && selected ? (
                <foreignObject className="coordination-topology-node-tools" height="40" width={nodeToolsWidth} x={nodeToolsX} y={nodeToolsY}>
                  <div className="coordination-topology-node-tools__bar">
                    {renderNodeTools(node)}
                  </div>
                </foreignObject>
              ) : null}
            </g>
          );
        })}
      </g>
      {boxSelect.active ? (
        <rect
          className="coordination-topology-box-select"
          height={normalizedBox().height}
          rx="6"
          width={normalizedBox().width}
          x={normalizedBox().x}
          y={normalizedBox().y}
        />
      ) : null}
    </svg>
  );
}
