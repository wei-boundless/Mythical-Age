import type { TaskGraphRecord } from "@/lib/api";

export const MODULAR_NOVEL_DOMAIN_ID = "domain.writing.modular_novel";
export const MODULAR_NOVEL_MASTER_GRAPH_ID = "graph.writing.modular_novel.master";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown) {
  return String(value ?? "").trim();
}

function graphMetadata(graph: TaskGraphRecord) {
  return asRecord(graph.metadata);
}

function timelineBlocks(graph: TaskGraphRecord) {
  return asArray(graphMetadata(graph).timeline_blocks).map(asRecord);
}

function hasLinkedGraphModules(graph: TaskGraphRecord) {
  return timelineBlocks(graph).some((block) => text(block.linked_graph_id));
}

function graphHasBatchContract(graph: TaskGraphRecord) {
  const bindings = asRecord(graph.contract_bindings);
  const runtime = asRecord(bindings.runtime);
  const unitBatch = asRecord(bindings.unit_batch);
  const metadata = graphMetadata(graph);
  return Boolean(
    Object.keys(unitBatch).length
    || Object.keys(asRecord(runtime.split_policy)).length
    || Object.keys(asRecord(metadata.split_policy)).length
    || Object.keys(asRecord(metadata.unit_batch)).length,
  );
}

function graphContractBindingCount(graph: TaskGraphRecord) {
  return Object.keys(asRecord(graph.contract_bindings)).length;
}

export function taskGraphFeatureBadges(graph: TaskGraphRecord): string[] {
  const badges: string[] = [];
  if (graph.graph_id === MODULAR_NOVEL_MASTER_GRAPH_ID) badges.push("推荐主图");
  if (hasLinkedGraphModules(graph)) badges.push("图模块");
  if (graphHasBatchContract(graph)) badges.push("批次契约");
  if (graphContractBindingCount(graph)) badges.push("contract_bindings");
  if (text(graph.default_protocol_id)) badges.push("协议");
  return badges;
}

export function taskGraphSelectionScore(graph: TaskGraphRecord) {
  const metadata = graphMetadata(graph);
  const graphId = text(graph.graph_id);
  const domainId = text(graph.domain_id);
  const family = text(graph.task_family);
  const managedBy = text(metadata.managed_by);
  let score = 0;

  if (graphId === MODULAR_NOVEL_MASTER_GRAPH_ID) score += 10000;
  if (domainId === MODULAR_NOVEL_DOMAIN_ID) score += 2200;
  if (family === "writing_modular_novel") score += 1800;
  if (graphId.includes(".modular_novel.")) score += 1500;
  if (managedBy.includes("modular_novel")) score += 1200;
  if (hasLinkedGraphModules(graph)) score += 900;
  if (graphHasBatchContract(graph)) score += 700;
  if (graphContractBindingCount(graph)) score += 400;
  if (graph.enabled) score += 80;
  if (graph.publish_state === "published") score += 60;
  score += Math.min(50, (graph.node_count ?? graph.nodes?.length ?? 0));
  return score;
}

export function sortTaskGraphsForWorkbench(graphs: TaskGraphRecord[]) {
  return [...graphs].sort((left, right) => {
    const scoreDelta = taskGraphSelectionScore(right) - taskGraphSelectionScore(left);
    if (scoreDelta) return scoreDelta;
    return text(left.title || left.graph_id).localeCompare(text(right.title || right.graph_id), "zh-Hans-CN");
  });
}

export function recommendedTaskGraphId(graphs: TaskGraphRecord[], currentGraphId = "") {
  const current = text(currentGraphId);
  if (current && graphs.some((graph) => graph.graph_id === current)) {
    return current;
  }
  return sortTaskGraphsForWorkbench(graphs)[0]?.graph_id ?? "";
}

export function isRecommendedTaskGraph(graph: TaskGraphRecord, graphs: TaskGraphRecord[]) {
  return graph.graph_id === recommendedTaskGraphId(graphs);
}
