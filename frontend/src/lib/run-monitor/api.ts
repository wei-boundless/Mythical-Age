import {
  getGraphRunMonitor,
  getOrchestrationHarnessTaskRunLiveMonitor,
  getRunMonitor,
  getRuntimeMonitorEventStreamUrl,
  type SessionScope,
} from "@/lib/api";

export async function fetchRunMonitor(limit = 40) {
  return getRunMonitor(limit);
}

export async function fetchRunMonitorTaskDetail(taskRunId: string) {
  return getOrchestrationHarnessTaskRunLiveMonitor(taskRunId);
}

export async function fetchRunMonitorGraphDetail(
  graphRunId: string,
  graphHarnessConfigId: string,
  sessionScope?: Partial<SessionScope>,
) {
  return getGraphRunMonitor(graphRunId, graphHarnessConfigId, 80, sessionScope);
}

export { getRuntimeMonitorEventStreamUrl };
