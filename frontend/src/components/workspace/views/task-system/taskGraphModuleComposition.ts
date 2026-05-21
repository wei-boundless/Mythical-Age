import type { UnitPortEdgeSpec } from "@/lib/api";

export type TaskGraphModuleFacet = "units" | "interfaces" | "connections" | "graph_module_runtime" | "stitching";

export type TaskGraphComposableGraphOverlay = {
  version: string;
  units: Array<Record<string, unknown>>;
  interfaces: Array<Record<string, unknown>>;
  port_edges: UnitPortEdgeSpec[];
  graph_module_runtime: Array<Record<string, unknown>>;
};

export const TASK_GRAPH_MODULE_FACET_ITEMS: Array<{
  id: TaskGraphModuleFacet;
  title: string;
  desc: string;
}> = [
  { id: "units", title: "可组合单元", desc: "graph / node / resource" },
  { id: "interfaces", title: "接口端口", desc: "input / output ports" },
  { id: "connections", title: "端口连接", desc: "port edge contracts" },
  { id: "graph_module_runtime", title: "导入模块", desc: "module relation graph" },
  { id: "stitching", title: "图块来源", desc: "timeline blocks" },
];

const TASK_GRAPH_MODULE_FACETS = new Set<TaskGraphModuleFacet>(
  TASK_GRAPH_MODULE_FACET_ITEMS.map((item) => item.id),
);

export function taskGraphModuleFacetFromEditorFocus(facet?: string | null): TaskGraphModuleFacet {
  if (facet === "blocks") return "stitching";
  if (TASK_GRAPH_MODULE_FACETS.has(facet as TaskGraphModuleFacet)) {
    return facet as TaskGraphModuleFacet;
  }
  return "units";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)).map((item) => ({ ...item })) : [];
}

function asPortEdgeArray(value: unknown): UnitPortEdgeSpec[] {
  return asRecordArray(value).map((item) => ({
    edge_id: String(item.edge_id ?? "").trim(),
    source_unit_id: String(item.source_unit_id ?? "").trim(),
    source_port_id: String(item.source_port_id ?? "").trim(),
    target_unit_id: String(item.target_unit_id ?? "").trim(),
    target_port_id: String(item.target_port_id ?? "").trim(),
    payload_contract_id: String(item.payload_contract_id ?? "").trim(),
    edge_type: String(item.edge_type ?? "handoff").trim() || "handoff",
    temporal_semantics: asRecord(item.temporal_semantics),
    handoff: asRecord(item.handoff),
    metadata: asRecord(item.metadata),
  }));
}

export function taskGraphComposableOverlayFromMetadata(metadata: Record<string, unknown>): TaskGraphComposableGraphOverlay {
  const overlay = asRecord(metadata.composable_graph);
  return {
    version: String(overlay.version ?? "v1").trim() || "v1",
    units: asRecordArray(overlay.units),
    interfaces: asRecordArray(overlay.interfaces),
    port_edges: asPortEdgeArray(overlay.port_edges),
    graph_module_runtime: asRecordArray(overlay.graph_module_runtime),
  };
}

export function taskGraphComposableOverlayMetadataPatch(
  metadata: Record<string, unknown>,
  patch: Partial<TaskGraphComposableGraphOverlay>,
): { composable_graph: TaskGraphComposableGraphOverlay } {
  return {
    composable_graph: {
      ...taskGraphComposableOverlayFromMetadata(metadata),
      ...patch,
    },
  };
}

export function upsertTaskGraphOverlayPortEdge(
  metadata: Record<string, unknown>,
  edge: UnitPortEdgeSpec,
): { composable_graph: TaskGraphComposableGraphOverlay } {
  const overlay = taskGraphComposableOverlayFromMetadata(metadata);
  const edgeId = String(edge.edge_id ?? "").trim();
  const nextEdge = {
    ...edge,
    edge_id: edgeId,
    edge_type: String(edge.edge_type ?? "handoff").trim() || "handoff",
    temporal_semantics: asRecord(edge.temporal_semantics),
    handoff: asRecord(edge.handoff),
    metadata: {
      ...asRecord(edge.metadata),
      explicit_overlay: true,
    },
  };
  const exists = overlay.port_edges.some((item) => item.edge_id === edgeId);
  return taskGraphComposableOverlayMetadataPatch(metadata, {
    port_edges: exists
      ? overlay.port_edges.map((item) => (item.edge_id === edgeId ? nextEdge : item))
      : [...overlay.port_edges, nextEdge],
  });
}

export function removeTaskGraphOverlayPortEdge(
  metadata: Record<string, unknown>,
  edgeId: string,
): { composable_graph: TaskGraphComposableGraphOverlay } {
  const overlay = taskGraphComposableOverlayFromMetadata(metadata);
  return taskGraphComposableOverlayMetadataPatch(metadata, {
    port_edges: overlay.port_edges.filter((item) => item.edge_id !== edgeId),
  });
}
