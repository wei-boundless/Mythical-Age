import type { TaskGraphStudioLayerId } from "./TaskGraphLayerNav";
import type { TaskGraphPreflightIssue } from "./taskGraphPreflight";

export type TaskGraphEditorFocus = {
  layer: TaskGraphStudioLayerId;
  facet?: string;
  node_id?: string;
  edge_id?: string;
  repository_id?: string;
  collection_id?: string;
  issue_id?: string;
};

export function mergeTaskGraphEditorFocus(
  current: TaskGraphEditorFocus,
  next: Partial<TaskGraphEditorFocus> & { layer?: TaskGraphStudioLayerId },
): TaskGraphEditorFocus {
  return {
    ...current,
    ...next,
    layer: next.layer ?? current.layer,
  };
}

export function focusForPreflightIssue(issue: TaskGraphPreflightIssue): TaskGraphEditorFocus {
  const base = {
    issue_id: issue.issue_id,
  };

  if (
    issue.source.includes("memory_selector")
    || issue.source.includes("receipt")
    || issue.source.includes("memory_commit_path")
    || issue.source.includes("memory_write_contract")
    || issue.source.includes("memory_commit_contract")
  ) {
    return {
      ...base,
      layer: "memory",
      facet: "selector",
      edge_id: issue.scope === "edge" ? issue.target_id : undefined,
      repository_id: issue.scope === "graph" ? issue.target_id : undefined,
    };
  }

  if (issue.source.includes("memory_repository")) {
    return {
      ...base,
      layer: "memory",
      facet: "repositories",
      repository_id: issue.target_id,
    };
  }

  if (issue.source.includes("cognition") || issue.source.includes("projection") || issue.source.includes("prompt")) {
    return {
      ...base,
      layer: "responsibility",
      facet: "cognition",
      node_id: issue.scope === "node" ? issue.target_id : undefined,
      edge_id: issue.scope === "edge" ? issue.target_id : undefined,
    };
  }

  if (issue.source.includes("revision")) {
    return {
      ...base,
      layer: "timeline",
      facet: "revision",
      edge_id: issue.scope === "edge" ? issue.target_id : undefined,
      node_id: issue.scope === "node" ? issue.target_id : undefined,
    };
  }

  if (issue.source.includes("timeline")) {
    return {
      ...base,
      layer: "timeline",
      facet: issue.scope === "phase" ? "phase" : "clock",
      node_id: issue.scope === "node" ? issue.target_id : undefined,
      edge_id: issue.scope === "edge" ? issue.target_id : undefined,
    };
  }

  if (issue.source.includes("contract") || issue.source.includes("review_gate")) {
    return {
      ...base,
      layer: "contracts",
      facet: issue.scope === "edge" ? "payload" : "quality_gate",
      node_id: issue.scope === "node" ? issue.target_id : undefined,
      edge_id: issue.scope === "edge" ? issue.target_id : undefined,
    };
  }

  if (issue.source.includes("agent")) {
    return {
      ...base,
      layer: "agents",
      facet: "binding",
      node_id: issue.scope === "node" ? issue.target_id : undefined,
    };
  }

  if (issue.scope === "node") {
    return {
      ...base,
      layer: "responsibility",
      facet: "cognition",
      node_id: issue.target_id,
    };
  }

  if (issue.scope === "edge") {
    return {
      ...base,
      layer: "responsibility",
      facet: "handoff",
      edge_id: issue.target_id,
    };
  }

  if (issue.scope === "phase") {
    return {
      ...base,
      layer: "timeline",
      facet: "phase",
    };
  }

  return {
    ...base,
    layer: issue.scope === "graph" ? "blueprint" : "publish",
    facet: issue.scope,
  };
}

export function focusTargetLabel(focus: TaskGraphEditorFocus) {
  const parts = [
    focus.layer,
    focus.facet,
    focus.node_id ? `node:${focus.node_id}` : "",
    focus.edge_id ? `edge:${focus.edge_id}` : "",
    focus.repository_id ? `repository:${focus.repository_id}` : "",
    focus.collection_id ? `collection:${focus.collection_id}` : "",
  ].filter(Boolean);
  return parts.join(" / ");
}
