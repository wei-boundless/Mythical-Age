import type { RunMonitorEnvelope, RunMonitorSignal } from "./types";

const ATTENTION_STATES = new Set(["waiting", "attention", "stale", "failed"]);

export function selectRunMonitorActivityLane(monitor: RunMonitorEnvelope | null | undefined): RunMonitorSignal[] {
  if (!monitor) return [];
  const primary = Array.isArray(monitor.primary) ? monitor.primary : [];
  const attention = Array.isArray(monitor.attention) ? monitor.attention : [];
  const recent = Array.isArray(monitor.recent) ? monitor.recent : [];
  const graphIds = new Set((Array.isArray(monitor.projects) ? monitor.projects : []).map((signal) => signal.signal_id));
  const merged = [...primary, ...attention, ...recent].filter((signal) =>
    signal.work_kind !== "graph_task"
    && !graphIds.has(signal.signal_id)
  );
  return uniqueSignals(merged);
}

export function selectRunMonitorProjectLane(monitor: RunMonitorEnvelope | null | undefined): RunMonitorSignal[] {
  if (!monitor) return [];
  const projects = Array.isArray(monitor.projects) ? monitor.projects : [];
  if (projects.length) return uniqueSignals(projects);
  return uniqueSignals((Array.isArray(monitor.signals) ? monitor.signals : []).filter((signal) => signal.work_kind === "graph_task"));
}

export function visibleRunMonitorSignals(monitor: RunMonitorEnvelope | null | undefined): RunMonitorSignal[] {
  if (!monitor) return [];
  return uniqueSignals([
    ...selectRunMonitorProjectLane(monitor),
    ...selectRunMonitorActivityLane(monitor),
    ...(Array.isArray(monitor.signals) ? monitor.signals.filter((signal) => ATTENTION_STATES.has(signal.state)) : []),
  ]);
}

function uniqueSignals(signals: RunMonitorSignal[]) {
  const seen = new Set<string>();
  const result: RunMonitorSignal[] = [];
  for (const signal of signals) {
    const key = signal.signal_id || signal.task_instance_id || signal.task_run_id;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(signal);
  }
  return result;
}
