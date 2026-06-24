"use client";

import { useCallback, useEffect, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import { Bot, Database, FileOutput, FolderTree, GitBranch, Home, ShieldCheck } from "lucide-react";
import type { TaskGraphEdgeRecord, TaskGraphNodeRecord } from "@/lib/api";

import { createEdgeFromRelation, taskGraphEdgeRelationRegistrations } from "../registry/taskGraphEdgeRelationRegistry";
import {
  graphEdgesToReactFlowEdges,
  graphNodesToReactFlowNodes,
  reactFlowNodesToLayout,
  type TaskGraphCanvasEdgeData,
  type TaskGraphCanvasNodeData,
} from "./taskGraphCanvasLayout";
import type { GraphEditorLayout } from "../templates/graphTemplateTypes";

const nodeTypes = {
  taskGraphNode: TaskGraphNodeCard,
};

type TaskGraphFlowNode = Node<TaskGraphCanvasNodeData>;
type TaskGraphFlowEdge = Edge<TaskGraphCanvasEdgeData>;

export function TaskGraphInfiniteCanvas({
  nodes,
  edges,
  layout,
  selectedEdgeId,
  selectedNodeId,
  onEdgesChange,
  onLayoutChange,
  onSelectionChange,
}: {
  nodes: TaskGraphNodeRecord[];
  edges: TaskGraphEdgeRecord[];
  layout: GraphEditorLayout;
  selectedNodeId: string;
  selectedEdgeId: string;
  onEdgesChange: (edges: TaskGraphEdgeRecord[]) => void;
  onLayoutChange: (layout: GraphEditorLayout) => void;
  onSelectionChange: (selection: { nodeId?: string; edgeId?: string }) => void;
}) {
  const initialNodes = useMemo(() => graphNodesToReactFlowNodes(nodes, layout), [layout, nodes]);
  const initialEdges = useMemo(() => graphEdgesToReactFlowEdges(edges), [edges]);
  const [flowNodes, setFlowNodes] = useNodesState<TaskGraphFlowNode>(initialNodes as TaskGraphFlowNode[]);
  const [flowEdges, setFlowEdges] = useEdgesState<TaskGraphFlowEdge>(initialEdges);

  useEffect(() => {
    setFlowNodes(initialNodes);
  }, [initialNodes, setFlowNodes]);

  useEffect(() => {
    setFlowEdges(initialEdges);
  }, [initialEdges, setFlowEdges]);

  const commitNodeChanges = useCallback((changes: NodeChange<TaskGraphFlowNode>[]) => {
    setFlowNodes((current) => {
      return applyNodeChanges(changes, current);
    });
  }, [setFlowNodes]);

  const commitEdgeChanges = useCallback((changes: EdgeChange<TaskGraphFlowEdge>[]) => {
    setFlowEdges((current) => {
      const next = applyEdgeChanges(changes, current);
      const removedIds = new Set(
        changes
          .filter((change) => change.type === "remove")
          .map((change) => String(change.id)),
      );
      if (removedIds.size) {
        onEdgesChange(edges.filter((edge) => !removedIds.has(edge.edge_id)));
      }
      return next;
    });
  }, [edges, onEdgesChange, setFlowEdges]);

  const connectNodes = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target || connection.source === connection.target) return;
    const relation = taskGraphEdgeRelationRegistrations[0];
    const graphEdge = createEdgeFromRelation(relation, connection.source, connection.target, edges.length);
    const nextEdges = [...edges, graphEdge];
    onEdgesChange(nextEdges);
    const flowEdge: TaskGraphFlowEdge = {
      id: graphEdge.edge_id,
      source: graphEdge.source_node_id,
      target: graphEdge.target_node_id,
      type: "smoothstep",
      data: {
        graphEdge,
        label: relation.displayName,
        tone: relation.visual.tone,
      },
      className: `graph-repository-flow-edge graph-repository-flow-edge--${relation.visual.tone}`,
    };
    setFlowEdges((current) => [...current, flowEdge]);
    onSelectionChange({ edgeId: graphEdge.edge_id });
  }, [edges, onEdgesChange, onSelectionChange, setFlowEdges]);

  return (
    <div className="graph-repository-canvas-shell">
      <ReactFlow
        edges={flowEdges}
        fitView
        maxZoom={1.6}
        minZoom={0.35}
        nodes={flowNodes}
        nodeTypes={nodeTypes}
        onConnect={connectNodes}
        onEdgesChange={commitEdgeChanges}
        onEdgeClick={(_, edge) => onSelectionChange({ edgeId: edge.id })}
        onNodeDragStop={(_, __, currentNodes) => onLayoutChange(reactFlowNodesToLayout(layout, currentNodes))}
        onNodeClick={(_, node) => onSelectionChange({ nodeId: node.id })}
        onNodesChange={commitNodeChanges}
        onPaneClick={() => onSelectionChange({})}
        proOptions={{ hideAttribution: true }}
        selectionOnDrag
      >
        <Background color="var(--graph-canvas-grid-minor)" gap={24} size={1} variant={BackgroundVariant.Lines} />
        <MiniMap
          className="graph-repository-minimap"
          maskColor="color-mix(in srgb, var(--console-surface) 78%, transparent)"
          nodeColor={(node) => node.id === selectedNodeId ? "var(--console-accent)" : "var(--console-line-strong)"}
          pannable
          zoomable
        />
        <Controls className="graph-repository-controls" showInteractive={false} />
      </ReactFlow>
      <div className="graph-repository-canvas-status" aria-live="polite">
        <span>{nodes.length} 节点</span>
        <span>{edges.length} 边</span>
        <span>{layout.home_node_id ? `home: ${layout.home_node_id}` : "未设置 home"}</span>
        <span>{selectedNodeId || selectedEdgeId || "未选中对象"}</span>
      </div>
    </div>
  );
}

function TaskGraphNodeCard({ data, selected }: NodeProps<TaskGraphFlowNode>) {
  const node = data.graphNode;
  const tone = String(data.tone || "agent");
  const home = Boolean(data.home);
  const Icon = iconForTone(tone);
  return (
    <article
      className={[
        "graph-repository-flow-node",
        `graph-repository-flow-node--${tone}`,
        selected ? "graph-repository-flow-node--selected" : "",
        home ? "graph-repository-flow-node--home" : "",
      ].filter(Boolean).join(" ")}
    >
      <Handle className="graph-repository-flow-handle" position={Position.Left} type="target" />
      <header>
        <span className="graph-repository-flow-node__icon"><Icon size={15} /></span>
        <div>
          <strong>{String(data.label || node.node_id)}</strong>
          <small>{String(data.subtitle || node.node_type || "")}</small>
        </div>
        {home ? <em title="home 坐标锚点"><Home size={13} /></em> : null}
      </header>
      <p>{String(node.metadata?.summary || node.role || node.node_type || "图节点")}</p>
      <footer>
        <span>{node.execution_mode || "sync"}</span>
        <span>{node.node_type}</span>
      </footer>
      <Handle className="graph-repository-flow-handle" position={Position.Right} type="source" />
    </article>
  );
}

function iconForTone(tone: string) {
  if (tone === "reviewer" || tone === "approval") return ShieldCheck;
  if (tone === "planner" || tone === "loop") return GitBranch;
  if (tone === "memory") return Database;
  if (tone === "artifact") return FileOutput;
  if (tone === "file") return FolderTree;
  return Bot;
}
