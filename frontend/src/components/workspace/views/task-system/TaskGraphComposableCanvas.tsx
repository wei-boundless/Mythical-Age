"use client";

import { Cable, GitBranch, Network, ScanLine } from "lucide-react";

import { CoordinationTopologyGraph as TaskGraphTopologyCanvas } from "@/components/coordination/CoordinationTopologyGraph";
import type { ComposableUnitSpec, GraphModuleExpansionSpec, UnitPortEdgeSpec } from "@/lib/api";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { taskGraphDisplayName } from "./taskGraphNameRegistry";
import type { TaskGraphModuleFacet } from "./taskGraphModuleComposition";
import type { TaskGraphComposableSubject } from "./taskGraphComposableEditorTypes";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function unitNodeKind(unit: ComposableUnitSpec) {
  if (unit.unit_type === "graph") return "graph_module";
  if (unit.unit_type === "resource") return "memory";
  if (unit.unit_type === "human_gate") return "manual_gate";
  if (unit.unit_type === "runtime_monitor") return "ledger";
  return "executor";
}

function edgeKind(edge: UnitPortEdgeSpec) {
  const metadata = asRecord(edge.metadata);
  if (metadata.explicit_overlay) return "port_edge_overlay";
  if (edge.edge_type === "memory_handoff") return "memory_read";
  if (edge.edge_type === "artifact_context") return "artifact_context";
  if (edge.edge_type === "temporal_dependency") return "control_flow";
  return "port_edge";
}

function edgeLabel(edge: UnitPortEdgeSpec) {
  const contract = String(edge.payload_contract_id ?? "").trim();
  if (contract) return contract.replace(/^contract[._-]/, "");
  return String(edge.edge_type ?? "handoff").trim() || "handoff";
}

function unitAgentLabel(unit: ComposableUnitSpec) {
  const ref = asRecord(unit.ref);
  if (unit.unit_type === "graph") return String(ref.graph_id ?? "图模块").trim() || "图模块";
  if (unit.unit_type === "resource") return "Resource";
  if (unit.unit_type === "human_gate") return "Human Gate";
  return String(unit.phase_id ?? unit.unit_type ?? "").trim();
}

function expansionTitle(expansion: GraphModuleExpansionSpec | null | undefined) {
  const importedGraph = asRecord(expansion?.imported_graph);
  return String(importedGraph.title ?? expansion?.linked_graph_id ?? expansion?.unit_id ?? "导入图模块").trim() || "导入图模块";
}

function expansionStatus(expansion: GraphModuleExpansionSpec | null | undefined) {
  if (!expansion) return "waiting";
  if ((expansion.issues ?? []).length) return "blocked";
  return (expansion.nodes?.length ?? 0) > 0 ? "ready" : "waiting";
}

function childNodeKind(node: Record<string, unknown>) {
  const type = String(node.node_type ?? "").trim();
  if (type === "review_gate") return "review_gate";
  if (type === "manual_gate") return "manual_gate";
  if (type.includes("memory") || type.includes("ledger") || type.includes("repository")) return "memory";
  if (type.includes("loop")) return "loop";
  return "executor";
}

function childEdgeKind(edge: Record<string, unknown>) {
  const type = String(edge.edge_type ?? "").trim();
  if (type.includes("memory")) return "memory_read";
  if (type.includes("artifact")) return "artifact_context";
  if (type.includes("temporal")) return "control_flow";
  return "port_edge";
}

export function TaskGraphComposableCanvas({
  activeFacet,
  graphModuleExpansions,
  graphDraft,
  onFacetChange,
  onSelectSubject,
  portEdges,
  selectedSubject,
  units,
}: {
  activeFacet: TaskGraphModuleFacet;
  graphModuleExpansions: GraphModuleExpansionSpec[];
  graphDraft: TaskGraphDraftV2;
  onFacetChange: (facet: TaskGraphModuleFacet) => void;
  onSelectSubject: (subject: TaskGraphComposableSubject) => void;
  portEdges: UnitPortEdgeSpec[];
  selectedSubject: TaskGraphComposableSubject;
  units: ComposableUnitSpec[];
}) {
  const metadata = asRecord(graphDraft.metadata);
  const graphNodes = units.map((unit) => ({
    id: unit.unit_id,
    title: taskGraphDisplayName(unit.unit_id, unit as unknown as Record<string, unknown>, metadata, unit.title || unit.unit_id),
    agentLabel: unitAgentLabel(unit),
    role: unit.unit_type,
    nodeKind: unitNodeKind(unit),
    status: unit.unit_type === "graph" && !String(asRecord(unit.ref).graph_id ?? "").trim() ? "waiting" : "idle",
  }));
  const unitIds = new Set(units.map((unit) => unit.unit_id));
  const graphEdges = portEdges
    .filter((edge) => unitIds.has(edge.source_unit_id) && unitIds.has(edge.target_unit_id))
    .map((edge) => ({
      id: edge.edge_id,
      from: edge.source_unit_id,
      to: edge.target_unit_id,
      label: edgeLabel(edge),
      edgeKind: edgeKind(edge),
      status: asRecord(edge.metadata).explicit_overlay ? "ready" : "idle",
    }));
  const selectedNodeId = selectedSubject.kind === "unit" ? selectedSubject.unit_id : "";
  const selectedEdgeId = selectedSubject.kind === "port_edge" ? selectedSubject.edge_id : "";
  const graphModuleCount = units.filter((unit) => unit.unit_type === "graph").length;
  const explicitEdgeCount = portEdges.filter((edge) => asRecord(edge.metadata).explicit_overlay).length;
  const expansionByUnitId = new Map(graphModuleExpansions.map((item) => [item.unit_id, item]));
  const selectedExpansionUnitId = selectedSubject.kind === "graph_module_expansion"
    ? selectedSubject.unit_id
    : selectedSubject.kind === "graph_module_expansion_node" || selectedSubject.kind === "graph_module_expansion_edge"
      ? selectedSubject.unit_id
      : selectedSubject.kind === "unit" && units.find((unit) => unit.unit_id === selectedSubject.unit_id)?.unit_type === "graph"
        ? selectedSubject.unit_id
        : "";
  const selectedExpansion = selectedExpansionUnitId ? expansionByUnitId.get(selectedExpansionUnitId) ?? null : null;
  const showingImportedGraph = activeFacet === "graph_module_runtime" && Boolean(selectedExpansion);
  const moduleNodes = units
    .filter((unit) => unit.unit_type === "graph")
    .map((unit) => {
      const expansion = expansionByUnitId.get(unit.unit_id);
      return {
        id: unit.unit_id,
        title: unit.title || expansionTitle(expansion),
        agentLabel: String(asRecord(unit.ref).graph_id ?? expansion?.linked_graph_id ?? "导入图模块"),
        role: "graph_module",
        nodeKind: "graph_module",
        status: expansionStatus(expansion),
      };
    });
  const moduleUnitIds = new Set(moduleNodes.map((node) => node.id));
  const moduleEdges = portEdges
    .filter((edge) => moduleUnitIds.has(edge.source_unit_id) && moduleUnitIds.has(edge.target_unit_id))
    .map((edge) => ({
      id: edge.edge_id,
      from: edge.source_unit_id,
      to: edge.target_unit_id,
      label: edgeLabel(edge),
      edgeKind: edgeKind(edge),
      status: asRecord(edge.metadata).explicit_overlay ? "ready" : "idle",
    }));
  const importedNodes = (selectedExpansion?.nodes ?? []).map((node) => ({
    id: String(node.scoped_node_id ?? node.node_id ?? "").trim(),
    title: String(node.title ?? node.node_id ?? "节点").trim() || "节点",
    agentLabel: String(node.phase_id ?? node.node_type ?? "").trim(),
    role: String(node.node_type ?? "node").trim(),
    nodeKind: childNodeKind(node),
    status: "idle",
  })).filter((node) => node.id);
  const importedEdges = (selectedExpansion?.edges ?? []).map((edge) => ({
    id: String(edge.scoped_edge_id ?? edge.edge_id ?? "").trim(),
    from: String(edge.scoped_source_node_id ?? edge.source_node_id ?? "").trim(),
    to: String(edge.scoped_target_node_id ?? edge.target_node_id ?? "").trim(),
    label: String(edge.payload_contract_id ?? edge.edge_type ?? "handoff").trim() || "handoff",
    edgeKind: childEdgeKind(edge),
    status: "idle",
  })).filter((edge) => edge.id && edge.from && edge.to);
  const canvasNodes = activeFacet === "graph_module_runtime"
    ? showingImportedGraph ? importedNodes : moduleNodes
    : graphNodes;
  const canvasEdges = activeFacet === "graph_module_runtime"
    ? showingImportedGraph ? importedEdges : moduleEdges
    : graphEdges;
  const selectedCanvasNodeId = activeFacet === "graph_module_runtime"
    ? selectedSubject.kind === "graph_module_expansion"
      ? selectedSubject.unit_id
      : selectedSubject.kind === "graph_module_expansion_node"
        ? selectedSubject.scoped_node_id
        : selectedSubject.kind === "unit" && moduleUnitIds.has(selectedSubject.unit_id)
          ? selectedSubject.unit_id
          : ""
    : selectedNodeId;
  const selectedCanvasEdgeId = activeFacet === "graph_module_runtime"
    ? selectedSubject.kind === "graph_module_expansion_edge" ? selectedSubject.scoped_edge_id : ""
    : selectedEdgeId;
  const canvasTitle = showingImportedGraph ? expansionTitle(selectedExpansion) : graphDraft.title || graphDraft.graph_id;
  const canvasOverline = activeFacet === "graph_module_runtime"
    ? showingImportedGraph ? "图模块内部拓扑" : "导入模块关系图"
    : "封装图画布";
  const canvasDescription = activeFacet === "graph_module_runtime"
    ? showingImportedGraph
      ? "当前只读查看被导入图模块的内部节点与边；编辑请进入该图模块工作台。"
      : "当前显示已导入图模块之间的交接关系；选择一个模块可查看它的内部拓扑。"
    : "当前画布显示本封装图边界内的节点、图模块、端口边和阶段图块派生关系。";

  return (
    <main className="task-graph-composer-canvas-shell" aria-label="当前层级可组合图画布">
      <header className="task-graph-composer-canvas-head">
        <div>
          <span>{canvasOverline}</span>
          <strong>{canvasTitle}</strong>
          <small>{canvasDescription}</small>
        </div>
        <div className="task-graph-composer-canvas-metrics">
          <span>{canvasNodes.length} 节点</span>
          <span>{canvasEdges.length} 边</span>
          <span>{graphModuleCount} 图模块</span>
          <span>{explicitEdgeCount} 覆盖</span>
        </div>
      </header>

      <section className="task-graph-composer-mode-strip" aria-label="画布语义">
        <button className={activeFacet === "units" ? "active" : ""} onClick={() => onFacetChange("units")} type="button">
          <GitBranch aria-hidden="true" size={14} />
          <span>单元</span>
          <strong>图和节点同构</strong>
        </button>
        <button className={activeFacet === "connections" ? "active" : ""} onClick={() => onFacetChange("connections")} type="button">
          <Cable aria-hidden="true" size={14} />
          <span>边</span>
          <strong>端口与时序语义</strong>
        </button>
        <button className={activeFacet === "graph_module_runtime" ? "active" : ""} onClick={() => onFacetChange("graph_module_runtime")} type="button">
          <Network aria-hidden="true" size={14} />
          <span>图模块</span>
          <strong>导入关系图</strong>
        </button>
        <button className={activeFacet === "stitching" ? "active" : ""} onClick={() => onFacetChange("stitching")} type="button">
          <ScanLine aria-hidden="true" size={14} />
          <span>图块</span>
          <strong>时序层拼接</strong>
        </button>
      </section>

      <div className="coordination-topology-viewport coordination-topology-viewport--builder task-graph-composer-viewport">
        <TaskGraphTopologyCanvas
          edges={canvasEdges}
          emptyDescription={activeFacet === "graph_module_runtime" ? "绑定 linked_graph_id 并刷新标准视图后，导入图模块会生成可浏览的关系图。" : "保存或刷新标准视图后，节点、阶段图块和显式覆盖层会被编译成可组合单元。"}
          emptyTitle={activeFacet === "graph_module_runtime" ? "当前还没有导入图模块" : "当前层级还没有可组合单元"}
          nodes={canvasNodes}
          onSelectEdge={(edgeId) => {
            if (activeFacet === "graph_module_runtime" && showingImportedGraph && selectedExpansion) {
              const edge = selectedExpansion.edges?.find((item) => String(item.scoped_edge_id ?? item.edge_id ?? "").trim() === edgeId);
              onSelectSubject({ kind: "graph_module_expansion_edge", unit_id: selectedExpansion.unit_id, scoped_edge_id: edgeId, edge_id: edge?.edge_id });
              return;
            }
            onSelectSubject({ kind: "port_edge", edge_id: edgeId });
          }}
          onSelectNode={(nodeId) => {
            if (activeFacet === "graph_module_runtime") {
              if (showingImportedGraph && selectedExpansion) {
                const node = selectedExpansion.nodes?.find((item) => String(item.scoped_node_id ?? item.node_id ?? "").trim() === nodeId);
                onSelectSubject({ kind: "graph_module_expansion_node", unit_id: selectedExpansion.unit_id, scoped_node_id: nodeId, node_id: node?.node_id });
                return;
              }
              onSelectSubject({ kind: "graph_module_expansion", unit_id: nodeId, plan_id: expansionByUnitId.get(nodeId)?.plan_id });
              return;
            }
            onSelectSubject({ kind: "unit", unit_id: nodeId });
          }}
          selectedEdgeId={selectedCanvasEdgeId}
          selectedNodeId={selectedCanvasNodeId}
        />
      </div>

      <footer className="task-graph-composer-legend" aria-label="画布图例">
        <span><i className="legend-dot legend-dot--unit" />普通 Unit</span>
        <span><i className="legend-dot legend-dot--graph" />图模块</span>
        <span><i className="legend-line legend-line--derived" />派生端口边</span>
        <span><i className="legend-line legend-line--overlay" />显式覆盖边</span>
      </footer>
    </main>
  );
}
