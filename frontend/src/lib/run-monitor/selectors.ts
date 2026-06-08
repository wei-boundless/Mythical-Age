import type { RunMonitorEnvelope, RunMonitorSignal } from "./types";

const ATTENTION_STATES = new Set(["waiting", "attention", "stale", "failed"]);
const TERMINAL_STATES = new Set(["completed", "stopped", "done", "terminal"]);
const PROJECT_LIVE_STATES = new Set(["active", "running"]);
const PROJECT_ATTENTION_STATES = new Set(["attention", "stale", "failed"]);

export function selectRunMonitorTaskLane(monitor: RunMonitorEnvelope | null | undefined): RunMonitorSignal[] {
  if (!monitor) return [];
  const management = monitor.management?.lanes;
  if (management) {
    return uniqueSignals([
      ...(Array.isArray(management.current) ? management.current : []),
      ...(Array.isArray(management.projects) ? management.projects : []),
      ...(Array.isArray(management.attention) ? management.attention : []),
      ...(Array.isArray(management.recent) ? management.recent : []),
    ].filter(shouldShowTaskSignal));
  }
  const primary = Array.isArray(monitor.primary) ? monitor.primary : [];
  const attention = Array.isArray(monitor.attention) ? monitor.attention : [];
  const recent = Array.isArray(monitor.recent) ? monitor.recent : [];
  const projects = Array.isArray(monitor.projects) ? monitor.projects : [];
  const merged = [...primary, ...projects, ...attention, ...recent].filter(shouldShowTaskSignal);
  return uniqueSignals(merged);
}

export function selectRunMonitorProjectLane(monitor: RunMonitorEnvelope | null | undefined): RunMonitorSignal[] {
  if (!monitor) return [];
  const managementProjects = monitor.management?.lanes?.projects;
  if (Array.isArray(managementProjects) && managementProjects.length) {
    return uniqueSignals(managementProjects.filter(shouldShowProjectSignal));
  }
  const projects = Array.isArray(monitor.projects) ? monitor.projects : [];
  if (projects.length) return uniqueSignals(projects.filter(shouldShowProjectSignal));
  return uniqueSignals((Array.isArray(monitor.signals) ? monitor.signals : []).filter((signal) =>
    signal.work_kind === "graph_task" && shouldShowProjectSignal(signal)
  ));
}

export function visibleRunMonitorSignals(monitor: RunMonitorEnvelope | null | undefined): RunMonitorSignal[] {
  if (!monitor) return [];
  const management = monitor.management?.lanes;
  if (management) {
    return uniqueSignals([
      ...(Array.isArray(management.current) ? management.current : []),
      ...(Array.isArray(management.projects) ? management.projects : []),
      ...(Array.isArray(management.attention) ? management.attention : []),
      ...(Array.isArray(management.recent) ? management.recent : []),
      ...(Array.isArray(management.hidden) ? management.hidden : []),
    ]);
  }
  return uniqueSignals([
    ...selectRunMonitorTaskLane(monitor),
    ...(Array.isArray(monitor.signals) ? monitor.signals.filter((signal) =>
      ATTENTION_STATES.has(signal.state) && shouldShowTaskSignal(signal)
    ) : []),
  ]);
}

function shouldShowTaskSignal(signal: RunMonitorSignal) {
  return signal.work_kind === "graph_task" ? shouldShowProjectSignal(signal) : shouldShowActivitySignal(signal);
}

function shouldShowActivitySignal(signal: RunMonitorSignal) {
  return !isHiddenSignal(signal) && !isTerminalSignal(signal);
}

function shouldShowProjectSignal(signal: RunMonitorSignal) {
  if (isHiddenSignal(signal) || isTerminalSignal(signal)) {
    return false;
  }
  const state = signalText(signal.state);
  const activityState = signalText(signal.activity_state);
  const status = signalText(signal.status);
  const lifecycle = signalText(signal.lifecycle);
  if (Boolean(signal.is_running) || PROJECT_LIVE_STATES.has(state) || PROJECT_LIVE_STATES.has(activityState)) {
    return true;
  }
  return [state, activityState, status, lifecycle].some((value) => PROJECT_ATTENTION_STATES.has(value));
}

function isHiddenSignal(signal: RunMonitorSignal) {
  return Boolean(signal.visibility?.hidden) || signal.visibility?.visible === false;
}

function isTerminalSignal(signal: RunMonitorSignal) {
  return [
    signal.state,
    signal.activity_state,
    signal.status,
    signal.lifecycle,
    signal.bucket,
  ].some((value) => TERMINAL_STATES.has(signalText(value)));
}

function signalText(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
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
