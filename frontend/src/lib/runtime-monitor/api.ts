import {
  getGlobalRuntimeMonitor,
  getGraphRunMonitor,
  getOrchestrationHarnessTaskRunLiveMonitor,
  getRuntimeMonitorEventStreamUrl,
  type SessionScope,
} from "@/lib/api";

export async function fetchRuntimeMonitorSnapshot(limit = 40) {
  return getGlobalRuntimeMonitor(limit);
}

export async function fetchRuntimeMonitorTaskDetail(taskRunId: string) {
  return getOrchestrationHarnessTaskRunLiveMonitor(taskRunId);
}

export async function fetchRuntimeMonitorGraphDetail(
  graphRunId: string,
  graphHarnessConfigId: string,
  sessionScope?: Partial<SessionScope>,
) {
  return getGraphRunMonitor(graphRunId, graphHarnessConfigId, 80, sessionScope);
}

export { getRuntimeMonitorEventStreamUrl };
