import type { Edge, Node } from "@xyflow/react";
import type { TaskGraphEdgeRecord, TaskGraphNodeRecord } from "@/lib/api";

import { taskGraphEdgeRelationForEdge } from "../registry/taskGraphEdgeRelationRegistry";
import { taskGraphNodeRegistrationForNode } from "../registry/taskGraphNodeRegistry";
import type { GraphEditorLayout } from "../templates/graphTemplateTypes";

export type TaskGraphCanvasNodeData = Record<string, unknown> & {
  graphNode: TaskGraphNodeRecord;
  label: string;
  subtitle: string;
  tone: string;
  home: boolean;
};

export type TaskGraphCanvasEdgeData = Record<string, unknown> & {
  graphEdge: TaskGraphEdgeRecord;
  label: string;
  tone: string;
};

export function graphNodesToReactFlowNodes(
  nodes: TaskGraphNodeRecord[],
  layout: GraphEditorLayout,
): Node<TaskGraphCanvasNodeData>[] {
  return nodes.map((node, index) => {
    const registration = taskGraphNodeRegistrationForNode(node);
    const position = layout.node_positions[node.node_id] ?? {
      x: (index % 4) * 260,
      y: Math.floor(index / 4) * 150,
    };
    return {
      id: node.node_id,
      type: "taskGraphNode",
      position,
      data: {
        graphNode: node,
        label: node.title || node.node_id,
        subtitle: node.agent_id || node.role || node.node_type,
        tone: registration.visual.tone,
        home: layout.home_node_id === node.node_id,
      },
    };
  });
}

export function graphEdgesToReactFlowEdges(edges: TaskGraphEdgeRecord[]): Edge<TaskGraphCanvasEdgeData>[] {
  return edges.map((edge, index) => {
    const registration = taskGraphEdgeRelationForEdge(edge);
    return {
      id: edge.edge_id || `edge.${index + 1}`,
      source: edge.source_node_id,
      target: edge.target_node_id,
      type: "smoothstep",
      animated: Boolean(registration.visual.animated || edge.metadata?.loop),
      label: registration.displayName,
      data: {
        graphEdge: edge,
        label: registration.displayName,
        tone: registration.visual.tone,
      },
      className: `graph-repository-flow-edge graph-repository-flow-edge--${registration.visual.tone}`,
    };
  });
}

export function reactFlowNodesToLayout(
  layout: GraphEditorLayout,
  nodes: Array<Pick<Node, "id" | "position">>,
): GraphEditorLayout {
  return {
    ...layout,
    node_positions: nodes.reduce<Record<string, { x: number; y: number }>>((acc, node) => {
      acc[node.id] = {
        x: Number.isFinite(node.position.x) ? node.position.x : 0,
        y: Number.isFinite(node.position.y) ? node.position.y : 0,
      };
      return acc;
    }, {}),
  };
}

export function mergeNodePositionsIntoLayout(
  layout: GraphEditorLayout,
  patch: Record<string, { x: number; y: number }>,
): GraphEditorLayout {
  return {
    ...layout,
    node_positions: {
      ...layout.node_positions,
      ...patch,
    },
  };
}

export function autoSpreadGraphLayout(nodes: TaskGraphNodeRecord[], layout: GraphEditorLayout): GraphEditorLayout {
  const homeNodeId = layout.home_node_id || nodes[0]?.node_id || "";
  const homeIndex = nodes.findIndex((node) => node.node_id === homeNodeId);
  const ordered = homeIndex >= 0
    ? [nodes[homeIndex], ...nodes.filter((_, index) => index !== homeIndex)]
    : nodes;
  const node_positions = ordered.reduce<Record<string, { x: number; y: number }>>((acc, node, index) => {
    if (node.node_id === homeNodeId) {
      acc[node.node_id] = { x: 0, y: 0 };
      return acc;
    }
    const ringIndex = index - 1;
    const column = ringIndex % 4;
    const row = Math.floor(ringIndex / 4);
    acc[node.node_id] = {
      x: 300 + column * 300,
      y: (row % 2 === 0 ? -150 : 130) + row * 120,
    };
    return acc;
  }, {});
  return {
    ...layout,
    node_positions,
    viewport: {
      ...layout.viewport,
      x: 0,
      y: 0,
      zoom: layout.viewport.zoom || 0.88,
    },
  };
}
