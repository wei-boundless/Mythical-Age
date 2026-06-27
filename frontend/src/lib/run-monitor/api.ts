import {
  executeRunMonitorAction,
  getGraphRunMonitor,
  getHarnessTaskRunLiveMonitor,
  getRunMonitor,
  getRunMonitorEventStreamUrl,
  preflightRunMonitorAction,
  type RunMonitorActionPayload,
  type SessionScope,
} from "@/lib/api";

export async function fetchRunMonitor(limit = 40) {
  return getRunMonitor(limit);
}

export async function preflightRunMonitorSignalAction(payload: RunMonitorActionPayload) {
  return preflightRunMonitorAction(payload);
}

export async function executeRunMonitorSignalAction(payload: RunMonitorActionPayload) {
  return executeRunMonitorAction(payload);
}

export async function fetchRunMonitorTaskDetail(taskRunId: string) {
  return getHarnessTaskRunLiveMonitor(taskRunId);
}

export async function fetchRunMonitorGraphDetail(
  graphRunId: string,
  graphConfigId: string,
  sessionScope?: Partial<SessionScope>,
) {
  return getGraphRunMonitor(graphRunId, graphConfigId, 80, sessionScope);
}

export { getRunMonitorEventStreamUrl };


