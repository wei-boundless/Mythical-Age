export function resourceRefKey(value: unknown) {
  const record = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
  const ref = String(record.ref ?? "").trim();
  if (ref) return ref;
  const kind = String(record.kind ?? "").trim();
  const id = String(record.id ?? "").trim();
  return kind && id ? `${kind}:${id}` : "";
}

export function monitorItemInstanceId(item: { task_instance_id?: unknown; graph_run_id?: unknown; task_run_id?: unknown }) {
  return String(item.task_instance_id || item.graph_run_id || item.task_run_id || "").trim();
}

export function monitorItemTaskRunId(item: { task_run_id?: unknown }) {
  return String(item.task_run_id ?? "").trim();
}

export function resourceAvailabilityState(value: unknown) {
  const record = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
  const availability = record.availability && typeof record.availability === "object" && !Array.isArray(record.availability)
    ? record.availability as Record<string, unknown>
    : {};
  return String(availability.state ?? "").trim();
}
