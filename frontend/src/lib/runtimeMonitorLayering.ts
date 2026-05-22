import type { GlobalRuntimeMonitor, GlobalRuntimeMonitorItem } from "@/lib/api";

function text(value: unknown) {
  return String(value ?? "").trim();
}

export function isTopLevelTaskGraphMonitorItem(item: GlobalRuntimeMonitorItem) {
  const graphId = text(item.graph_id);
  const taskId = text(item.task_id);
  if (!graphId || !taskId) return false;
  if (taskId.startsWith("task_graph.graph_module.")) return false;
  if (taskId.startsWith("taskinst:")) return false;
  return taskId === graphId;
}

export function topLevelTaskGraphMonitorItems(monitor: GlobalRuntimeMonitor | null | undefined) {
  return (monitor?.task_runs ?? []).filter(isTopLevelTaskGraphMonitorItem);
}

export function summarizeTopLevelTaskGraphMonitor(items: GlobalRuntimeMonitorItem[]) {
  return items.reduce(
    (summary, item) => {
      summary.total += 1;
      if (item.status === "running" || item.status === "created") summary.running += 1;
      if (item.status === "waiting_approval" || item.status === "blocked") summary.waiting += 1;
      if (item.status === "completed" || item.status === "success") summary.completed += 1;
      if (item.status === "failed" || item.status === "aborted") summary.failed += 1;
      if (item.display_bucket === "stale") summary.stale += 1;
      if (item.display_bucket === "recent") summary.recent += 1;
      return summary;
    },
    { total: 0, running: 0, waiting: 0, completed: 0, failed: 0, stale: 0, recent: 0 },
  );
}
