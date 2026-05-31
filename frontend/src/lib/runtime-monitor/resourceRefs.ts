export function monitorItemInstanceId(item: { task_instance_id?: unknown; task_run_id?: unknown }) {
  return String(item.task_instance_id || item.task_run_id || "").trim();
}

export function monitorItemTaskRunId(item: { task_run_id?: unknown }) {
  return String(item.task_run_id ?? "").trim();
}
