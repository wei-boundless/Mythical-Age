"use client";

import { Cable, GitBranch, Network, ScanLine } from "lucide-react";

import { CoordinationTopologyGraph as TaskGraphTopologyCanvas } from "@/components/coordination/CoordinationTopologyGraph";
import type { ComposableUnitSpec, UnitPortEdgeSpec } from "@/lib/api";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { taskGraphDisplayName } from "./taskGraphNameRegistry";
import type { TaskGraphModuleFacet } from "./taskGraphModuleComposition";
import type { TaskGraphComposableSubject } from "./taskGraphComposableEditorTypes";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function unitNodeKind(unit: ComposableUnitSpec) {
  if (unit.unit_type === "graph") return "graph_unit";
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
  if (unit.unit_type === "graph") return String(ref.graph_id ?? "GraphUnit").trim() || "GraphUnit";
  if (unit.unit_type === "resource") return "Resource";
  if (unit.unit_type === "human_gate") return "Human Gate";
  return String(unit.phase_id ?? unit.unit_type ?? "").trim();
}

export function TaskGraphComposableCanvas({
  activeFacet,
  graphDraft,
  onFacetChange,
  onSelectSubject,
  portEdges,
  selectedSubject,
  units,
}: {
  activeFacet: TaskGraphModuleFacet;
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
  const graphUnitCount = units.filter((unit) => unit.unit_type === "graph").length;
  const explicitEdgeCount = portEdges.filter((edge) => asRecord(edge.metadata).explicit_overlay).length;

  return (
    <main className="task-graph-composer-canvas-shell" aria-label="当前层级可组合图画布">
      <header className="task-graph-composer-canvas-head">
        <div>
          <span>任务图画布</span>
          <strong>{graphDraft.title || graphDraft.graph_id}</strong>
          <small>当前画布只显示本任务图边界：节点、图节点、端口边和阶段图块派生关系。</small>
        </div>
        <div className="task-graph-composer-canvas-metrics">
          <span>{units.length} 单元</span>
          <span>{graphEdges.length}/{portEdges.length} 边</span>
          <span>{graphUnitCount} 子图</span>
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
        <button className={activeFacet === "nested_runtime" ? "active" : ""} onClick={() => onFacetChange("nested_runtime")} type="button">
          <Network aria-hidden="true" size={14} />
          <span>嵌套</span>
          <strong>子图运行隔离</strong>
        </button>
        <button className={activeFacet === "stitching" ? "active" : ""} onClick={() => onFacetChange("stitching")} type="button">
          <ScanLine aria-hidden="true" size={14} />
          <span>图块</span>
          <strong>时序层拼接</strong>
        </button>
      </section>

      <div className="coordination-topology-viewport coordination-topology-viewport--builder task-graph-composer-viewport">
        <TaskGraphTopologyCanvas
          edges={graphEdges}
          emptyDescription="保存或刷新标准视图后，节点、阶段图块和显式覆盖层会被编译成可组合单元。"
          emptyTitle="当前层级还没有可组合单元"
          nodes={graphNodes}
          onSelectEdge={(edgeId) => onSelectSubject({ kind: "port_edge", edge_id: edgeId })}
          onSelectNode={(unitId) => onSelectSubject({ kind: "unit", unit_id: unitId })}
          selectedEdgeId={selectedEdgeId}
          selectedNodeId={selectedNodeId}
        />
      </div>

      <footer className="task-graph-composer-legend" aria-label="画布图例">
        <span><i className="legend-dot legend-dot--unit" />普通 Unit</span>
        <span><i className="legend-dot legend-dot--graph" />GraphUnit</span>
        <span><i className="legend-line legend-line--derived" />派生端口边</span>
        <span><i className="legend-line legend-line--overlay" />显式覆盖边</span>
      </footer>
    </main>
  );
}
