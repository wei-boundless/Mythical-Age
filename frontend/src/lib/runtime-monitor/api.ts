import {
  getGlobalRuntimeMonitor,
  getGraphRunMonitor,
  getOrchestrationHarnessTaskRunLiveMonitor,
  getRuntimeMonitorEventStreamUrl,
} from "@/lib/api";

export async function fetchRuntimeMonitorSnapshot(limit = 40) {
  return getGlobalRuntimeMonitor(limit);
}

export async function fetchRuntimeMonitorTaskDetail(taskRunId: string) {
  return getOrchestrationHarnessTaskRunLiveMonitor(taskRunId);
}

export async function fetchRuntimeMonitorGraphDetail(graphRunId: string, graphHarnessConfigId: string) {
  return getGraphRunMonitor(graphRunId, graphHarnessConfigId);
}

export { getRuntimeMonitorEventStreamUrl };
