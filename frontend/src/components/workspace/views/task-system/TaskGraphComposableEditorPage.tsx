"use client";

import { useEffect, useMemo, useState } from "react";

import type { ComposableUnitSpec, ContractSpec, OrchestrationAgentRuntimeCatalog, TaskGraphRecord, TaskGraphStandardView, UnitPortEdgeSpec } from "@/lib/api";

import { TaskGraphComposableCanvas } from "./TaskGraphComposableCanvas";
import { TaskGraphDiagnosticsDock } from "./TaskGraphDiagnosticsDock";
import { TaskGraphGraphLayerRail } from "./TaskGraphGraphLayerRail";
import { TaskGraphObjectInspector } from "./TaskGraphObjectInspector";
import { taskGraphModuleFacetFromEditorFocus, type TaskGraphModuleFacet } from "./taskGraphModuleComposition";
import type { TaskGraphComposableSubject } from "./taskGraphComposableEditorTypes";
import { taskGraphComposableSubjectFacet } from "./taskGraphComposableEditorTypes";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import { buildTaskGraphPreflightReport } from "./taskGraphPreflight";
import { buildTaskGraphComposableStandardModel } from "./taskGraphStandardView";
import type { TaskGraphWorkbenchAgentCatalog } from "./taskGraphTypes";

function subjectFromFocus(editorFocus: TaskGraphEditorFocus | undefined, graphId: string): TaskGraphComposableSubject {
  if (editorFocus?.edge_id) return { kind: "port_edge", edge_id: editorFocus.edge_id };
  if ((editorFocus?.facet === "stitching" || editorFocus?.facet === "blocks") && editorFocus?.node_id) {
    return { kind: "timeline_block", block_id: editorFocus.node_id };
  }
  if (editorFocus?.node_id) return { kind: "unit", unit_id: editorFocus.node_id.startsWith("unit.") ? editorFocus.node_id : `unit.node.${editorFocus.node_id.replace(/[:/\\]+/g, ".")}` };
  return { kind: "graph", graph_id: graphId };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function graphUnitShadowUnitIds(units: ComposableUnitSpec[]) {
  const shadowIds = new Set<string>();
  units.filter((unit) => unit.unit_type === "graph").forEach((unit) => {
    const graphUnitSuffix = unit.unit_id.replace(/^unit\.graph\./, "").trim();
    if (graphUnitSuffix && graphUnitSuffix !== unit.unit_id) {
      shadowIds.add(`unit.node.graph_unit.${graphUnitSuffix}`);
    }
    const timelineBlockId = String(asRecord(unit.ref).timeline_block_id ?? "").trim();
    const blockSuffix = timelineBlockId.replace(/^block\./, "").trim();
    if (blockSuffix) {
      shadowIds.add(`unit.node.graph_unit.${blockSuffix}`);
    }
  });
  return shadowIds;
}

function graphUnitDisplayUnits(units: ComposableUnitSpec[]) {
  const shadowUnitIds = graphUnitShadowUnitIds(units);
  return units.filter((unit) => !shadowUnitIds.has(unit.unit_id));
}

function graphUnitDisplayPortEdges(edges: UnitPortEdgeSpec[], units: ComposableUnitSpec[]) {
  const visibleUnitIds = new Set(graphUnitDisplayUnits(units).map((unit) => unit.unit_id));
  return edges.filter((edge) => visibleUnitIds.has(edge.source_unit_id) && visibleUnitIds.has(edge.target_unit_id));
}

export function TaskGraphComposableEditorPage({
  activeGraphEdges,
  activeGraphNodes,
  a2aCatalog,
  contractSpecs,
  dirty,
  domainTaskOptions,
  editorFocus,
  editorIssueCount,
  editorValid,
  onEditorFocus,
  onOpenGraph,
  orchestrationAgentCatalog,
  projectionCards,
  standardView,
  standardViewLoading,
  taskGraphDraft,
  taskGraphs,
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
  dirty: boolean;
  domainTaskOptions: Array<{ value: string; label: string }>;
  editorFocus?: TaskGraphEditorFocus;
  editorIssueCount: number;
  editorValid: boolean;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  onOpenGraph?: (graphId: string) => void;
  orchestrationAgentCatalog?: OrchestrationAgentRuntimeCatalog | null;
  projectionCards?: Array<{ projection_id: string; title?: string; soul_name?: string; soul_id?: string }>;
  standardView: TaskGraphStandardView | null;
  standardViewLoading?: boolean;
  taskGraphDraft: TaskGraphDraftV2;
  taskGraphs?: TaskGraphRecord[];
  updateTaskGraphDraft: (patch: Partial<TaskGraphDraftV2>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
}) {
  const focusLayer = editorFocus?.layer;
  const focusFacet = editorFocus?.facet;
  const focusEdgeId = editorFocus?.edge_id;
  const focusNodeId = editorFocus?.node_id;
  const [facet, setFacet] = useState<TaskGraphModuleFacet>(() => taskGraphModuleFacetFromEditorFocus(editorFocus?.facet));
  const [selectedSubject, setSelectedSubject] = useState<TaskGraphComposableSubject>(() => subjectFromFocus(editorFocus, taskGraphDraft.graph_id));
  const composableModel = buildTaskGraphComposableStandardModel(standardView);
  const displayUnits = useMemo(() => graphUnitDisplayUnits(composableModel.units), [composableModel.units]);
  const displayPortEdges = useMemo(() => graphUnitDisplayPortEdges(composableModel.portEdges, composableModel.units), [composableModel.portEdges, composableModel.units]);
  const preflightReport = useMemo(
    () => buildTaskGraphPreflightReport({
      nodes: activeGraphNodes,
      edges: activeGraphEdges,
      dirty,
      editorValid,
      editorIssueCount,
      metadata: taskGraphDraft.metadata,
      standardView,
    }),
    [activeGraphEdges, activeGraphNodes, dirty, editorIssueCount, editorValid, standardView, taskGraphDraft.metadata],
  );

  useEffect(() => {
    if (focusLayer !== "modules") return;
    setFacet(taskGraphModuleFacetFromEditorFocus(focusFacet));
    if (focusEdgeId) {
      setSelectedSubject({ kind: "port_edge", edge_id: focusEdgeId });
      return;
    }
    if ((focusFacet === "stitching" || focusFacet === "blocks") && focusNodeId) {
      setSelectedSubject({ kind: "timeline_block", block_id: focusNodeId });
      return;
    }
    if (focusNodeId) {
      setSelectedSubject({
        kind: "unit",
        unit_id: focusNodeId.startsWith("unit.") ? focusNodeId : `unit.node.${focusNodeId.replace(/[:/\\]+/g, ".")}`,
      });
      return;
    }
    setSelectedSubject({ kind: "graph", graph_id: taskGraphDraft.graph_id });
  }, [focusEdgeId, focusFacet, focusLayer, focusNodeId, taskGraphDraft.graph_id]);

  const applyFacet = (nextFacet: TaskGraphModuleFacet) => {
    setFacet(nextFacet);
    onEditorFocus?.({ layer: "modules", facet: nextFacet });
  };

  const applySubject = (subject: TaskGraphComposableSubject) => {
    setSelectedSubject(subject);
    const nextFacet = taskGraphComposableSubjectFacet(subject);
    setFacet(nextFacet);
    if (subject.kind === "unit") {
      onEditorFocus?.({ layer: "modules", facet: nextFacet, node_id: subject.unit_id });
      return;
    }
    if (subject.kind === "port_edge") {
      onEditorFocus?.({ layer: "modules", facet: nextFacet, edge_id: subject.edge_id });
      return;
    }
    if (subject.kind === "timeline_block") {
      onEditorFocus?.({ layer: "modules", facet: nextFacet, node_id: subject.block_id });
      return;
    }
    if (subject.kind === "issue") {
      onEditorFocus?.({ layer: "modules", facet: nextFacet, issue_id: subject.issue.issue_id });
      return;
    }
    onEditorFocus?.({ layer: "modules", facet: nextFacet });
  };

  return (
    <section className="task-graph-composer-page" aria-label="任务图编辑器">
      <section className="task-graph-composer-workbench">
        <TaskGraphGraphLayerRail
          activeFacet={facet}
          graphDraft={taskGraphDraft}
          issues={preflightReport.issues.filter((issue) => issue.source.includes("composable_graph") || issue.source.includes("timeline") || issue.scope === "unit" || issue.scope === "port_edge")}
          nestedRuntime={composableModel.nestedRuntime}
          onOpenGraph={onOpenGraph}
          onFacetChange={applyFacet}
          onSelectSubject={applySubject}
          portEdges={displayPortEdges}
          selectedSubject={selectedSubject}
          standardView={standardView}
          standardViewLoading={standardViewLoading}
          units={displayUnits}
        />
        <TaskGraphComposableCanvas
          activeFacet={facet}
          graphDraft={taskGraphDraft}
          onFacetChange={applyFacet}
          onSelectSubject={applySubject}
          portEdges={displayPortEdges}
          selectedSubject={selectedSubject}
          units={displayUnits}
        />
        <TaskGraphObjectInspector
          activeGraphEdges={activeGraphEdges}
          activeGraphNodes={activeGraphNodes}
          a2aCatalog={a2aCatalog}
          contractSpecs={contractSpecs}
          domainTaskOptions={domainTaskOptions}
          graphDraft={taskGraphDraft}
          interfaces={composableModel.interfaces}
          nestedRuntime={composableModel.nestedRuntime}
          onOpenGraph={onOpenGraph}
          onSelectSubject={applySubject}
          orchestrationAgentCatalog={orchestrationAgentCatalog}
          portEdges={displayPortEdges}
          projectionCards={projectionCards}
          selectedSubject={selectedSubject}
          taskGraphs={taskGraphs}
          units={displayUnits}
          updateTaskGraphDraft={updateTaskGraphDraft}
          updateTaskGraphEdge={updateTaskGraphEdge}
          updateTaskGraphMetadata={updateTaskGraphMetadata}
          updateTaskGraphNode={updateTaskGraphNode}
          updateTaskGraphRuntimePolicy={updateTaskGraphRuntimePolicy}
        />
      </section>
      <TaskGraphDiagnosticsDock
        onSelectSubject={applySubject}
        report={preflightReport}
        standardViewIssueCount={standardView?.issues?.length ?? 0}
      />
    </section>
  );
}
