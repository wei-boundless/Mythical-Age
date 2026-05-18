export type TaskGraphNameRegistryEntry = {
  object_id: string;
  object_type: string;
  display_name_zh: string;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function explicitDisplayName(value: unknown) {
  const record = asRecord(value);
  return String(record.display_name_zh ?? record.title_zh ?? record.name_zh ?? "").trim();
}

export function taskGraphNameRegistry(metadata: Record<string, unknown> | undefined): TaskGraphNameRegistryEntry[] {
  const raw = asRecord(metadata).name_registry;
  const items = Array.isArray(raw) ? raw : [];
  return items
    .map((item): TaskGraphNameRegistryEntry => {
      const record = asRecord(item);
      return {
        object_id: String(record.object_id ?? record.id ?? "").trim(),
        object_type: String(record.object_type ?? record.type ?? "").trim(),
        display_name_zh: explicitDisplayName(record),
      };
    })
    .filter((item) => item.object_id && item.display_name_zh);
}

export function taskGraphDisplayName(
  objectId: string,
  object: Record<string, unknown> | undefined,
  metadata: Record<string, unknown> | undefined,
  fallback = "未命名对象",
) {
  const registryName = taskGraphNameRegistry(metadata).find((item) => item.object_id === objectId)?.display_name_zh;
  if (registryName) return registryName;
  const directName = explicitDisplayName(object);
  if (directName) return directName;
  return String(object?.title ?? object?.label ?? object?.task_title ?? objectId ?? fallback).trim() || fallback;
}

export function buildTaskGraphNameRegistryPayload({
  graphTitle,
  graphId,
  nodes,
  phases,
}: {
  graphTitle: string;
  graphId: string;
  nodes: Array<Record<string, unknown>>;
  phases?: Array<Record<string, unknown>>;
}): TaskGraphNameRegistryEntry[] {
  const entries: TaskGraphNameRegistryEntry[] = [];
  if (graphId) {
    entries.push({ object_id: graphId, object_type: "graph", display_name_zh: graphTitle || graphId });
  }
  for (const node of nodes) {
    const nodeId = String(node.node_id ?? node.id ?? "").trim();
    if (!nodeId) continue;
    entries.push({
      object_id: nodeId,
      object_type: "node",
      display_name_zh: taskGraphDisplayName(nodeId, node, undefined, nodeId),
    });
  }
  for (const phase of phases ?? []) {
    const phaseId = String(phase.phase_id ?? phase.id ?? "").trim();
    if (!phaseId) continue;
    entries.push({
      object_id: phaseId,
      object_type: "phase",
      display_name_zh: String(phase.title ?? phase.display_name_zh ?? phaseId).trim() || phaseId,
    });
  }
  return entries;
}
