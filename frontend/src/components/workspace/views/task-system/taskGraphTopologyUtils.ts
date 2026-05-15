export function graphNodeTaskId(node: Record<string, unknown>) {
  return String(node.task_id ?? node.task_ref ?? node.subtask_ref ?? "").trim();
}

export function graphEdgeSource(edge: Record<string, unknown>) {
  return String(edge.source_node_id ?? edge.from ?? edge.source ?? "").trim();
}

export function graphEdgeTarget(edge: Record<string, unknown>) {
  return String(edge.target_node_id ?? edge.to ?? edge.target ?? "").trim();
}

export function graphEdgeId(edge: Record<string, unknown>, index = 0) {
  const source = graphEdgeSource(edge);
  const target = graphEdgeTarget(edge);
  return String(edge.edge_id ?? edge.id ?? (source && target ? `${source}->${target}` : `edge_${index + 1}`)).trim();
}

export function coordinationSubtaskRefs(draft: { graph_nodes?: Array<Record<string, unknown>>; subtask_refs?: string[] }) {
  return Array.from(new Set([
    ...((draft.subtask_refs ?? []).map((item) => String(item).trim()).filter(Boolean)),
    ...((draft.graph_nodes ?? []).map((node) => graphNodeTaskId(node)).filter(Boolean)),
  ]));
}
