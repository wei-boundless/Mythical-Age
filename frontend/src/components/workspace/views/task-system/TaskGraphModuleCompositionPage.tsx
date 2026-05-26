"use client";

import type { ContractSpec, OrchestrationAgentRuntimeCatalog, TaskGraphRecord, TaskGraphStandardView } from "@/lib/api";

import { TaskGraphComposableEditorPage } from "./TaskGraphComposableEditorPage";
import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";
import type { TaskGraphWorkbenchAgentCatalog } from "./taskGraphTypes";

export function TaskGraphModuleCompositionPage({
  activeGraphEdges = [],
  activeGraphNodes,
  a2aCatalog,
  contractSpecs,
  dirty = false,
  domainTaskOptions,
  editorFocus,
  editorIssueCount = 0,
  editorValid = true,
  onEditorFocus,
  onOpenGraph,
  orchestrationAgentCatalog,
  projectionCards,
  standardView,
  standardViewStale = false,
  standardViewLoading,
  taskGraphDraft,
  taskGraphs,
  updateTaskGraphDraft,
  updateTaskGraphEdge,
  updateTaskGraphMetadata,
  updateTaskGraphNode,
  updateTaskGraphRuntimePolicy,
}: {
  activeGraphEdges?: Array<Record<string, unknown>>;
  activeGraphNodes: Array<Record<string, unknown>>;
  a2aCatalog?: TaskGraphWorkbenchAgentCatalog | null;
  contractSpecs: ContractSpec[];
  dirty?: boolean;
  domainTaskOptions: Array<{ value: string; label: string }>;
  editorFocus?: TaskGraphEditorFocus;
  editorIssueCount?: number;
  editorValid?: boolean;
  onEditorFocus?: (focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphEditorFocus["layer"] }) => void;
  onOpenGraph?: (graphId: string) => void;
  orchestrationAgentCatalog?: OrchestrationAgentRuntimeCatalog | null;
  projectionCards?: Array<{ projection_id: string; title?: string; soul_name?: string; soul_id?: string }>;
  standardView: TaskGraphStandardView | null;
  standardViewStale?: boolean;
  standardViewLoading?: boolean;
  taskGraphDraft: TaskGraphDraftV2;
  taskGraphs?: TaskGraphRecord[];
  updateTaskGraphDraft: (patch: Partial<TaskGraphDraftV2>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
}) {
  return (
    <TaskGraphComposableEditorPage
      activeGraphEdges={activeGraphEdges}
      activeGraphNodes={activeGraphNodes}
      a2aCatalog={a2aCatalog}
      contractSpecs={contractSpecs}
      dirty={dirty}
      domainTaskOptions={domainTaskOptions}
      editorFocus={editorFocus}
      editorIssueCount={editorIssueCount}
      editorValid={editorValid}
      onEditorFocus={onEditorFocus}
      onOpenGraph={onOpenGraph}
      orchestrationAgentCatalog={orchestrationAgentCatalog}
      projectionCards={projectionCards}
      standardView={standardView}
      standardViewStale={standardViewStale}
      standardViewLoading={standardViewLoading}
      taskGraphDraft={taskGraphDraft}
      taskGraphs={taskGraphs}
      updateTaskGraphDraft={updateTaskGraphDraft}
      updateTaskGraphEdge={updateTaskGraphEdge}
      updateTaskGraphMetadata={updateTaskGraphMetadata}
      updateTaskGraphNode={updateTaskGraphNode}
      updateTaskGraphRuntimePolicy={updateTaskGraphRuntimePolicy}
    />
  );
}
