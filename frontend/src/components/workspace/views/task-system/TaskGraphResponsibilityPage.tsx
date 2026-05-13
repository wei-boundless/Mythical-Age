"use client";

import { EdgeHandoffCard } from "./EdgeHandoffCard";
import { NodeResponsibilityCard } from "./NodeResponsibilityCard";

export function TaskGraphResponsibilityPage({
  selectedGraphNode,
  selectedGraphNodeId,
  selectedGraphEdge,
  selectedGraphEdgeId,
  updateTaskGraphNode,
  updateTaskGraphEdge,
}: {
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphNodeId: string;
  selectedGraphEdge: Record<string, unknown> | null;
  selectedGraphEdgeId: string;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
}) {
  return (
    <section className="task-graph-studio-page">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>职责与交接</strong>
        <small>用 Agent 可理解的语义定义节点职责和边交接标准。</small>
      </header>

      <section className="task-graph-form-grid">
        <NodeResponsibilityCard
          selectedGraphNode={selectedGraphNode}
          selectedGraphNodeId={selectedGraphNodeId}
          updateTaskGraphNode={updateTaskGraphNode}
        />
        <EdgeHandoffCard
          selectedGraphEdge={selectedGraphEdge}
          selectedGraphEdgeId={selectedGraphEdgeId}
          updateTaskGraphEdge={updateTaskGraphEdge}
        />
      </section>
    </section>
  );
}
