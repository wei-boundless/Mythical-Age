import type { TaskGraphStandardView } from "@/lib/api";

import type { TaskGraphStudioLayerId } from "./TaskGraphLayerNav";
import type { TaskGraphEditorFocus } from "./taskGraphEditorFocus";

export type TaskGraphEditorSelection = {
  canonicalNodeId: string;
  canonicalEdgeId: string;
  resourceId: string;
  previewUnitId: string;
  previewPortEdgeId: string;
  issueId: string;
};

export type TaskGraphStandardViewState = {
  view: TaskGraphStandardView | null;
  graphId: string;
  revisionKey: string;
  loadedAt: string;
  stale: boolean;
};

export function emptyTaskGraphEditorSelection(): TaskGraphEditorSelection {
  return {
    canonicalNodeId: "",
    canonicalEdgeId: "",
    resourceId: "",
    previewUnitId: "",
    previewPortEdgeId: "",
    issueId: "",
  };
}

export function clearCanonicalSelection(selection: TaskGraphEditorSelection): TaskGraphEditorSelection {
  return {
    ...selection,
    canonicalNodeId: "",
    canonicalEdgeId: "",
  };
}

export function selectCanonicalNode(selection: TaskGraphEditorSelection, nodeId: string): TaskGraphEditorSelection {
  return {
    ...selection,
    canonicalNodeId: String(nodeId ?? "").trim(),
    canonicalEdgeId: "",
    previewUnitId: "",
    previewPortEdgeId: "",
  };
}

export function selectCanonicalEdge(selection: TaskGraphEditorSelection, edgeId: string): TaskGraphEditorSelection {
  return {
    ...selection,
    canonicalNodeId: "",
    canonicalEdgeId: String(edgeId ?? "").trim(),
    previewUnitId: "",
    previewPortEdgeId: "",
  };
}

export function selectResource(selection: TaskGraphEditorSelection, resourceId: string): TaskGraphEditorSelection {
  return {
    ...selection,
    resourceId: String(resourceId ?? "").trim(),
  };
}

export function selectionFromFocus(
  selection: TaskGraphEditorSelection,
  focus: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphStudioLayerId },
): TaskGraphEditorSelection {
  let next = { ...selection };
  if (Object.prototype.hasOwnProperty.call(focus, "issue_id")) {
    next.issueId = String(focus.issue_id ?? "").trim();
  }
  if (Object.prototype.hasOwnProperty.call(focus, "repository_id")) {
    next = selectResource(next, String(focus.repository_id ?? ""));
  }
  if (focus.layer === "modules") {
    if (Object.prototype.hasOwnProperty.call(focus, "node_id")) {
      next.previewUnitId = String(focus.node_id ?? "").trim();
      next.previewPortEdgeId = "";
    }
    if (Object.prototype.hasOwnProperty.call(focus, "edge_id")) {
      next.previewPortEdgeId = String(focus.edge_id ?? "").trim();
      next.previewUnitId = "";
    }
    return next;
  }
  if (Object.prototype.hasOwnProperty.call(focus, "node_id")) {
    next = selectCanonicalNode(next, String(focus.node_id ?? ""));
  }
  if (Object.prototype.hasOwnProperty.call(focus, "edge_id")) {
    next = selectCanonicalEdge(next, String(focus.edge_id ?? ""));
  }
  return next;
}

export function focusFromSelection(
  selection: TaskGraphEditorSelection,
  layer: TaskGraphStudioLayerId,
): TaskGraphEditorFocus {
  if (layer === "modules") {
    return {
      layer,
      node_id: selection.previewUnitId || undefined,
      edge_id: selection.previewPortEdgeId || undefined,
      issue_id: selection.issueId || undefined,
    };
  }
  return {
    layer,
    node_id: selection.canonicalNodeId || undefined,
    edge_id: selection.canonicalEdgeId || undefined,
    repository_id: selection.resourceId || undefined,
    issue_id: selection.issueId || undefined,
  };
}

export function taskGraphDraftRevisionKey(input: {
  graphId: string;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
}): string {
  const nodeIds = input.nodes.map((node) => String(node.node_id ?? node.id ?? "")).join("|");
  const edgeIds = input.edges.map((edge) => [
    String(edge.edge_id ?? edge.id ?? ""),
    String(edge.source_node_id ?? edge.from ?? edge.source ?? ""),
    String(edge.target_node_id ?? edge.to ?? edge.target ?? ""),
    String(edge.edge_type ?? edge.mode ?? ""),
  ].join(":")).join("|");
  const metadata = input.metadata ?? {};
  const publishState = String(metadata.editor_publish_state ?? "");
  return [input.graphId, input.nodes.length, nodeIds, input.edges.length, edgeIds, publishState].join("#");
}

export function emptyTaskGraphStandardViewState(): TaskGraphStandardViewState {
  return {
    view: null,
    graphId: "",
    revisionKey: "",
    loadedAt: "",
    stale: false,
  };
}

export function loadedTaskGraphStandardViewState(input: {
  view: TaskGraphStandardView;
  graphId: string;
  revisionKey: string;
  loadedAt?: string;
}): TaskGraphStandardViewState {
  return {
    view: input.view,
    graphId: input.graphId,
    revisionKey: input.revisionKey,
    loadedAt: input.loadedAt ?? new Date().toISOString(),
    stale: false,
  };
}

export function markTaskGraphStandardViewStale(
  state: TaskGraphStandardViewState,
  currentGraphId: string,
  currentRevisionKey: string,
): TaskGraphStandardViewState {
  if (!state.view) return state;
  return {
    ...state,
    stale: state.graphId !== currentGraphId || state.revisionKey !== currentRevisionKey,
  };
}
