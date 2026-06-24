"use client";

import type { ReactNode } from "react";
import { Home, Link2, Settings2 } from "lucide-react";
import type { TaskGraphEdgeRecord, TaskGraphNodeRecord } from "@/lib/api";

import { taskGraphEdgeRelationRegistrations } from "../registry/taskGraphEdgeRelationRegistry";
import type { GraphEditorLayout } from "../templates/graphTemplateTypes";

export function GraphTaskPropertyPanel({
  edges,
  graphId,
  layout,
  nodes,
  onEdgeChange,
  onGraphChange,
  onLayoutChange,
  onNodeChange,
  selectedEdgeId,
  selectedNodeId,
  title,
}: {
  edges: TaskGraphEdgeRecord[];
  graphId: string;
  layout: GraphEditorLayout;
  nodes: TaskGraphNodeRecord[];
  selectedNodeId: string;
  selectedEdgeId: string;
  title: string;
  onGraphChange: (patch: { title?: string }) => void;
  onNodeChange: (nodeId: string, patch: Partial<TaskGraphNodeRecord>) => void;
  onEdgeChange: (edgeId: string, patch: Partial<TaskGraphEdgeRecord>) => void;
  onLayoutChange: (layout: GraphEditorLayout) => void;
}) {
  const selectedNode = nodes.find((node) => node.node_id === selectedNodeId) ?? null;
  const selectedEdge = edges.find((edge) => edge.edge_id === selectedEdgeId) ?? null;

  if (selectedNode) {
    const prompt = String(asRecord(asRecord(selectedNode.contract_bindings).prompt).role_prompt ?? "");
    return (
      <aside className="graph-repository-property-panel" aria-label="节点属性">
        <header>
          <span><Settings2 size={14} />节点</span>
          <strong>{selectedNode.title || selectedNode.node_id}</strong>
        </header>
        <div className="graph-repository-form-stack">
          <Field label="节点标题">
            <input
              onChange={(event) => onNodeChange(selectedNode.node_id, { title: event.target.value })}
              value={selectedNode.title || ""}
            />
          </Field>
          <Field label="角色">
            <input
              onChange={(event) => onNodeChange(selectedNode.node_id, { role: event.target.value })}
              value={selectedNode.role || ""}
            />
          </Field>
          <Field label="Agent">
            <input
              onChange={(event) => onNodeChange(selectedNode.node_id, { agent_id: event.target.value })}
              placeholder="agent.id"
              value={selectedNode.agent_id || ""}
            />
          </Field>
          <Field label="角色 prompt">
            <textarea
              onChange={(event) => {
                const contract_bindings = {
                  ...asRecord(selectedNode.contract_bindings),
                  prompt: {
                    ...asRecord(asRecord(selectedNode.contract_bindings).prompt),
                    role_prompt: event.target.value,
                  },
                };
                onNodeChange(selectedNode.node_id, { contract_bindings });
              }}
              placeholder="写给这个 agent 的可执行角色说明"
              rows={8}
              value={prompt}
            />
          </Field>
          <button
            className="graph-repository-secondary-action"
            onClick={() => onLayoutChange({ ...layout, home_node_id: selectedNode.node_id })}
            type="button"
          >
            <Home size={14} />
            <span>设为 home 坐标锚点</span>
          </button>
          <p className="graph-repository-inline-note">home 只影响打开画布时的默认视角，不改变运行入口、调度权或边关系。</p>
        </div>
      </aside>
    );
  }

  if (selectedEdge) {
    return (
      <aside className="graph-repository-property-panel" aria-label="边属性">
        <header>
          <span><Link2 size={14} />边</span>
          <strong>{selectedEdge.edge_id}</strong>
        </header>
        <div className="graph-repository-form-stack">
          <Field label="关系类型">
            <select
              onChange={(event) => {
                const registration = taskGraphEdgeRelationRegistrations.find((item) => item.relation === event.target.value);
                if (!registration) return;
                onEdgeChange(selectedEdge.edge_id, {
                  edge_type: registration.defaultEdgePatch.edge_type || registration.relation,
                  metadata: {
                    ...asRecord(selectedEdge.metadata),
                    visual_tone: registration.visual.tone,
                  },
                });
              }}
              value={relationValue(selectedEdge.edge_type)}
            >
              {taskGraphEdgeRelationRegistrations.map((item) => (
                <option key={item.relation} value={item.relation}>{item.displayName}</option>
              ))}
            </select>
          </Field>
          <div className="graph-repository-edge-endpoints">
            <span>{selectedEdge.source_node_id}</span>
            <strong>→</strong>
            <span>{selectedEdge.target_node_id}</span>
          </div>
          <Field label="交接说明">
            <textarea
              onChange={(event) => onEdgeChange(selectedEdge.edge_id, {
                metadata: {
                  ...asRecord(selectedEdge.metadata),
                  description: event.target.value,
                },
              })}
              rows={5}
              value={String(selectedEdge.metadata?.description ?? "")}
            />
          </Field>
          <p className="graph-repository-inline-note">边是关系权威。节点坐标、中心位置或视觉大小都不会产生隐式关系。</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="graph-repository-property-panel" aria-label="图属性">
      <header>
        <span><Settings2 size={14} />图</span>
        <strong>{title || graphId}</strong>
      </header>
      <div className="graph-repository-form-stack">
        <Field label="图名称">
          <input onChange={(event) => onGraphChange({ title: event.target.value })} value={title || ""} />
        </Field>
        <div className="graph-repository-kv-list">
          <p><span>图 ID</span><strong>{graphId}</strong></p>
          <p><span>节点</span><strong>{nodes.length}</strong></p>
          <p><span>边</span><strong>{edges.length}</strong></p>
          <p><span>home</span><strong>{layout.home_node_id || "未设置"}</strong></p>
        </div>
        <p className="graph-repository-inline-note">自由世界只保存布局。真正的协作、上下游和运行交接都来自显式边。</p>
      </div>
    </aside>
  );
}

function Field({ children, label }: { children: ReactNode; label: string }) {
  return (
    <label className="graph-repository-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function relationValue(edgeType: string) {
  return taskGraphEdgeRelationRegistrations.find((item) => item.relation === edgeType || item.backendMapping.edgeTypes.includes(edgeType))?.relation
    ?? taskGraphEdgeRelationRegistrations[0].relation;
}
