import {
  executeRunMonitorAction,
  getGraphRunMonitor,
  getOrchestrationHarnessTaskRunLiveMonitor,
  getRunMonitor,
  getRuntimeMonitorEventStreamUrl,
  preflightRunMonitorAction,
  type RuntimeMonitorActionPayload,
  type SessionScope,
} from "@/lib/api";

export async function fetchRunMonitor(limit = 40) {
  return getRunMonitor(limit);
}

export async function preflightRunMonitorSignalAction(payload: RuntimeMonitorActionPayload) {
  return preflightRunMonitorAction(payload);
}

export async function executeRunMonitorSignalAction(payload: RuntimeMonitorActionPayload) {
  return executeRunMonitorAction(payload);
}

export async function fetchRunMonitorTaskDetail(taskRunId: string) {
  return getOrchestrationHarnessTaskRunLiveMonitor(taskRunId);
}

export async function fetchRunMonitorGraphDetail(
  graphRunId: string,
  graphConfigId: string,
  sessionScope?: Partial<SessionScope>,
) {
  return getGraphRunMonitor(graphRunId, graphConfigId, 80, sessionScope);
}

export { getRuntimeMonitorEventStreamUrl };

