"use client";

import type {
  ComposableUnitSpec,
  ContractSpec,
  GraphModuleRuntimePlanSpec,
  OrchestrationAgentRuntimeCatalog,
  TaskGraphRecord,
  GraphModuleExpansionSpec,
  UnitInterfaceSpec,
  UnitPortEdgeSpec,
} from "@/lib/api";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { taskGraphDisplayName } from "./taskGraphNameRegistry";
import {
  TaskGraphGraphModuleInspector,
  TaskGraphModuleRuntimeInspector,
} from "./TaskGraphGraphModuleInspector";
import {
  TaskGraphInterfacePlaceholderPanel,
  TaskGraphIssueInspector,
  TaskGraphOverlayStatusPanel,
  TaskGraphModuleExpansionInspector,
  TaskGraphUnmappedUnitPanel,
} from "./TaskGraphInspectorUtilityPanels";
import { TaskGraphNodeUnitInspector } from "./TaskGraphNodeUnitInspector";
import { TaskGraphPortEdgeInspector } from "./TaskGraphPortEdgeInspector";
import { TaskGraphRootInspector } from "./TaskGraphRootInspector";
import {
  removeTaskGraphOverlayPortEdge,
  taskGraphComposableOverlayMetadataPatch,
  taskGraphComposableOverlayFromMetadata,
} from "./taskGraphModuleComposition";
import type { TaskGraphComposableSubject } from "./taskGraphComposableEditorTypes";
import type { TaskGraphWorkbenchAgentCatalog } from "./taskGraphTypes";
import { graphEdgeId } from "./taskGraphTopologyUtils";
import { coordinationTimelineBlocks } from "./taskGraphTimeline";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function selectedUnit(subject: TaskGraphComposableSubject, units: ComposableUnitSpec[]) {
  return subject.kind === "unit" ? units.find((unit) => unit.unit_id === subject.unit_id) ?? null : null;
}

function selectedPortEdge(subject: TaskGraphComposableSubject, portEdges: UnitPortEdgeSpec[]) {
  return subject.kind === "port_edge" ? portEdges.find((edge) => edge.edge_id === subject.edge_id) ?? null : null;
}

function selectedGraphModuleRuntime(subject: TaskGraphComposableSubject, plans: GraphModuleRuntimePlanSpec[]) {
  return subject.kind === "graph_module_runtime" ? plans.find((plan) => plan.plan_id === subject.plan_id) ?? null : null;
}

function selectedGraphModuleExpansion(subject: TaskGraphComposableSubject, expansions: GraphModuleExpansionSpec[]) {
  if (subject.kind !== "graph_module_expansion" && subject.kind !== "graph_module_expansion_node" && subject.kind !== "graph_module_expansion_edge") {
    return null;
  }
  return expansions.find((expansion) => expansion.unit_id === subject.unit_id) ?? null;
}

function isOverlayEdge(edge: UnitPortEdgeSpec | null, overlayEdgeIds: Set<string>) {
  return Boolean(edge && (overlayEdgeIds.has(edge.edge_id) || asRecord(edge.metadata).explicit_overlay));
}

function nodeIdFromUnit(unit: ComposableUnitSpec | null) {
  return stringValue(asRecord(unit?.ref).node_id);
}

function graphEdgeSource(edge: Record<string, unknown>) {
  return stringValue(edge.source_node_id ?? edge.from ?? edge.source);
}

function graphEdgeTarget(edge: Record<string, unknown>) {
  return stringValue(edge.target_node_id ?? edge.to ?? edge.target);
}

function nodeTitle(node: Record<string, unknown> | null, fallback = "节点") {
  return stringValue(node?.title ?? node?.label ?? node?.task_title ?? node?.node_id, fallback);
}

function contractTitle(contract: ContractSpec) {
  return stringValue(contract.title_zh ?? contract.title_en ?? contract.contract_id, contract.contract_id);
}

export function TaskGraphObjectInspector({
  activeGraphEdges,
  activeGraphNodes,
  a2aCatalog,
  contractSpecs,
  domainTaskOptions,
  graphDraft,
  graphModuleExpansions,
  interfaces,
  graphModuleRuntime,
  onOpenGraph,
  onSelectSubject,
  orchestrationAgentCatalog,
  portEdges,
  projectionCards = [],
  selectedSubject,
  taskGraphs,
  units,
  updateTaskGraphDraft,
  updateTaskGraphEdge,
  updateTaskGraphMetadata,
  updateTaskGraphNode,
  updateTaskGraphRuntimePolicy,
}: {
  activeGraphEdges: Array<Record<string, unknown>>;
  activeGraphNodes: Array<Record<string, unknown>>;
  a2aCatalog?: TaskGraphWorkbenchAgentCatalog | null;
  contractSpecs: ContractSpec[];
  domainTaskOptions: Array<{ value: string; label: string }>;
  graphDraft: TaskGraphDraftV2;
  graphModuleExpansions: GraphModuleExpansionSpec[];
  interfaces: UnitInterfaceSpec[];
  graphModuleRuntime: GraphModuleRuntimePlanSpec[];
  onOpenGraph?: (graphId: string) => void;
  onSelectSubject: (subject: TaskGraphComposableSubject) => void;
  orchestrationAgentCatalog?: OrchestrationAgentRuntimeCatalog | null;
  portEdges: UnitPortEdgeSpec[];
  projectionCards?: Array<{ projection_id: string; title?: string; soul_name?: string; soul_id?: string }>;
  selectedSubject: TaskGraphComposableSubject;
  taskGraphs?: TaskGraphRecord[];
  units: ComposableUnitSpec[];
  updateTaskGraphDraft: (patch: Partial<TaskGraphDraftV2>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
}) {
  const metadata = asRecord(graphDraft.metadata);
  const overlay = taskGraphComposableOverlayFromMetadata(metadata);
  const overlayEdgeIds = new Set(overlay.port_edges.map((edge) => edge.edge_id));
  const blocks = coordinationTimelineBlocks(metadata);
  const unit = selectedUnit(selectedSubject, units);
  const portEdge = selectedPortEdge(selectedSubject, portEdges);
  const nestedPlan = selectedGraphModuleRuntime(selectedSubject, graphModuleRuntime);
  const graphModuleExpansion = selectedGraphModuleExpansion(selectedSubject, graphModuleExpansions);
  const unitOptions = units.map((item) => item.unit_id);
  const nodeUnitOptions = units.filter((item) => nodeIdFromUnit(item)).map((item) => item.unit_id);
  const graphName = taskGraphDisplayName(graphDraft.graph_id, undefined, metadata, graphDraft.title || graphDraft.graph_id);
  const contractOptions = contractSpecs.map((item) => item.contract_id);
  const agentOptions = uniqueStrings([
    graphDraft.runtime_policy.coordinator_agent_id,
    ...(graphDraft.runtime_policy.participant_agent_ids ?? []),
    ...activeGraphNodes.map((node) => stringValue(node.agent_id)),
    ...((orchestrationAgentCatalog?.agents ?? []).map((agent) => stringValue(agent.agent_id))),
    ...((a2aCatalog?.agent_cards ?? []).map((card) => stringValue(card.agent_id))),
  ]);
  const projectionOptions = projectionCards.map((item) => item.projection_id);
  const graphOptions = (taskGraphs ?? []).map((item) => item.graph_id);

  const formatUnit = (unitId: string) => {
    const item = units.find((candidate) => candidate.unit_id === unitId);
    if (!item) return unitId;
    const title = taskGraphDisplayName(item.unit_id, item as unknown as Record<string, unknown>, metadata, item.title || item.unit_id);
    return `${title} · ${item.unit_type}`;
  };
  const formatContract = (contractId: string) => {
    const contract = contractSpecs.find((item) => item.contract_id === contractId);
    return contract ? `${contractTitle(contract)} · ${contractId}` : contractId || "未绑定契约";
  };
  const formatAgent = (agentId: string) => {
    const agent = (orchestrationAgentCatalog?.agents ?? []).find((item) => stringValue(item.agent_id) === agentId);
    const card = (a2aCatalog?.agent_cards ?? []).find((item) => stringValue(item.agent_id) === agentId);
    if (!agentId) return "不绑定 Agent";
    const agentName = stringValue(agent?.display_name ?? agent?.agent_name);
    if (agentName) return `${agentName} · ${agentId}`;
    return card?.name ? `${String(card.name)} · ${agentId}` : agentId;
  };
  const formatProjection = (projectionId: string) => {
    const card = projectionCards.find((item) => item.projection_id === projectionId);
    if (!projectionId) return "不绑定 Projection";
    if (!card) return projectionId;
    const title = stringValue(card.title ?? card.projection_id, projectionId);
    const soul = stringValue(card.soul_name ?? card.soul_id);
    return soul ? `${title} · ${soul}` : title;
  };
  const formatGraph = (graphId: string) => {
    const graph = (taskGraphs ?? []).find((item) => item.graph_id === graphId);
    return graph ? `${graph.title || graph.graph_id} · ${graph.graph_id}` : graphId || "不绑定图模块";
  };

  const updateTimelineBlock = (blockId: string, patch: Record<string, unknown>) => {
    updateTaskGraphMetadata({
      timeline_blocks: blocks.map((item) => (item.block_id === blockId ? { ...item, ...patch } : item)),
    });
  };

  const removeOverlayEdge = (edgeId: string) => {
    updateTaskGraphMetadata(removeTaskGraphOverlayPortEdge(metadata, edgeId));
    onSelectSubject({ kind: "graph", graph_id: graphDraft.graph_id });
  };

  const nodeForUnit = (selected: ComposableUnitSpec) => {
    const nodeId = nodeIdFromUnit(selected);
    return nodeId ? activeGraphNodes.find((node) => stringValue(node.node_id ?? node.id) === nodeId) ?? null : null;
  };

  const edgeForPortEdge = (edge: UnitPortEdgeSpec) => {
    const edgeMetadata = asRecord(edge.metadata);
    const sourceNodeId = stringValue(edgeMetadata.source_node_id);
    const targetNodeId = stringValue(edgeMetadata.target_node_id);
    return activeGraphEdges.find((item, index) => graphEdgeId(item, index) === edge.edge_id)
      ?? activeGraphEdges.find((item) => sourceNodeId && targetNodeId && graphEdgeSource(item) === sourceNodeId && graphEdgeTarget(item) === targetNodeId)
      ?? null;
  };

  const updateLegacyEdgeEndpoint = (edge: Record<string, unknown>, edgeId: string, patch: Record<string, unknown>) => {
    const currentMetadata = asRecord(edge.metadata);
    const sourceUnitId = stringValue(patch.source_unit_id);
    const targetUnitId = stringValue(patch.target_unit_id);
    const sourceNodeId = sourceUnitId ? nodeIdFromUnit(units.find((item) => item.unit_id === sourceUnitId) ?? null) : "";
    const targetNodeId = targetUnitId ? nodeIdFromUnit(units.find((item) => item.unit_id === targetUnitId) ?? null) : "";
    updateTaskGraphEdge(edgeId, {
      ...(sourceNodeId ? { source_node_id: sourceNodeId, from: sourceNodeId } : {}),
      ...(targetNodeId ? { target_node_id: targetNodeId, to: targetNodeId } : {}),
      metadata: {
        ...currentMetadata,
        ...(patch.source_port_id ? { source_port_id: patch.source_port_id } : {}),
        ...(patch.target_port_id ? { target_port_id: patch.target_port_id } : {}),
      },
    });
  };

  const renderGraphEditor = () => (
    <TaskGraphRootInspector
      activeGraphNodes={activeGraphNodes}
      agentOptions={agentOptions}
      contractOptions={contractOptions}
      formatAgent={formatAgent}
      formatContract={formatContract}
      graphDraft={graphDraft}
      graphName={graphName}
      graphModuleCount={units.filter((item) => item.unit_type === "graph").length}
      interfaceCount={interfaces.length}
      nodeTitle={nodeTitle}
      portEdgeCount={portEdges.length}
      unitsCount={units.length}
      updateTaskGraphDraft={updateTaskGraphDraft}
      updateTaskGraphRuntimePolicy={updateTaskGraphRuntimePolicy}
    />
  );

  const renderNodeUnitEditor = (selected: ComposableUnitSpec, node: Record<string, unknown>) => {
    const unitEdges = portEdges.filter((edge) => edge.source_unit_id === selected.unit_id || edge.target_unit_id === selected.unit_id);
    return (
      <TaskGraphNodeUnitInspector
        agentOptions={agentOptions}
        contractOptions={contractOptions}
        domainTaskOptions={domainTaskOptions}
        formatAgent={formatAgent}
        formatContract={formatContract}
        formatProjection={formatProjection}
        interfaces={interfaces}
        node={node}
        projectionOptions={projectionOptions}
        selected={selected}
        unitEdges={unitEdges}
        updateTaskGraphNode={updateTaskGraphNode}
      />
    );
  };

  const renderGraphModuleEditor = (selected: ComposableUnitSpec) => {
    return (
      <TaskGraphGraphModuleInspector
        blocks={blocks}
        contractOptions={contractOptions}
        formatContract={formatContract}
        formatGraph={formatGraph}
        graphOptions={graphOptions}
        onOpenGraph={onOpenGraph}
        selected={selected}
        taskGraphs={taskGraphs}
        updateTimelineBlock={updateTimelineBlock}
      />
    );
  };

  const renderUnitEditor = (selected: ComposableUnitSpec) => {
    if (selected.unit_type === "graph") return renderGraphModuleEditor(selected);
    const mappedNode = nodeForUnit(selected);
    if (mappedNode) return renderNodeUnitEditor(selected, mappedNode);
    return <TaskGraphUnmappedUnitPanel selected={selected} />;
  };

  const renderPortEdgeEditor = (edge: UnitPortEdgeSpec) => {
    const originalEdge = edgeForPortEdge(edge);
    return (
      <TaskGraphPortEdgeInspector
        contractOptions={contractOptions}
        edge={edge}
        formatContract={formatContract}
        formatUnit={formatUnit}
        interfaces={interfaces}
        isOverlay={isOverlayEdge(edge, overlayEdgeIds)}
        nodeUnitOptions={nodeUnitOptions}
        originalEdge={originalEdge}
        removeOverlayEdge={removeOverlayEdge}
        unitOptions={unitOptions}
        updateLegacyEdgeEndpoint={updateLegacyEdgeEndpoint}
        updateTaskGraphEdge={updateTaskGraphEdge}
      />
    );
  };

  const renderGraphModuleRuntime = (plan: GraphModuleRuntimePlanSpec) => (
    <TaskGraphModuleRuntimeInspector plan={plan} />
  );

  return (
    <aside className="task-graph-composer-inspector" aria-label="对象编辑台">
      {selectedSubject.kind === "graph" ? renderGraphEditor() : null}
      {unit ? renderUnitEditor(unit) : null}
      {portEdge ? renderPortEdgeEditor(portEdge) : null}
      {nestedPlan ? renderGraphModuleRuntime(nestedPlan) : null}
      <TaskGraphModuleExpansionInspector
        expansion={graphModuleExpansion}
        onOpenGraph={onOpenGraph}
        selectedSubject={selectedSubject}
      />
      <TaskGraphIssueInspector selectedSubject={selectedSubject} />
      <TaskGraphInterfacePlaceholderPanel selectedSubject={selectedSubject} />
      <TaskGraphOverlayStatusPanel
        onNormalizeOverlay={() => updateTaskGraphMetadata(taskGraphComposableOverlayMetadataPatch(metadata, overlay))}
        overlay={overlay}
      />
    </aside>
  );
}
