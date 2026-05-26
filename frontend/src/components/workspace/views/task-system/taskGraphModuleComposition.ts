import type { UnitPortEdgeSpec } from "@/lib/api";

export type TaskGraphModuleFacet = "units" | "interfaces" | "connections" | "graph_module_runtime";

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
  { id: "units", title: "标准单元", desc: "从 canonical 图编译" },
  { id: "interfaces", title: "接口端口", desc: "输入/输出契约诊断" },
  { id: "connections", title: "端口映射", desc: "由 canonical edges 派生" },
  { id: "graph_module_runtime", title: "图模块展开", desc: "导入图只读诊断" },
];

const TASK_GRAPH_MODULE_FACETS = new Set<TaskGraphModuleFacet>(
  TASK_GRAPH_MODULE_FACET_ITEMS.map((item) => item.id),
);

export function taskGraphModuleFacetFromEditorFocus(facet?: string | null): TaskGraphModuleFacet {
  if (facet === "blocks" || facet === "stitching") return "graph_module_runtime";
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

export function removeTaskGraphOverlayPortEdge(
  metadata: Record<string, unknown>,
  edgeId: string,
): { composable_graph: TaskGraphComposableGraphOverlay } {
  const overlay = taskGraphComposableOverlayFromMetadata(metadata);
  return taskGraphComposableOverlayMetadataPatch(metadata, {
    port_edges: overlay.port_edges.filter((item) => item.edge_id !== edgeId),
  });
}
