import type { RunMonitorEnvelope, RunMonitorEvent, RunMonitorSignal, RunMonitorState } from "./types";
import { autoSelectableRunMonitorSignals } from "./selectors";

export function createRunMonitorState(): RunMonitorState {
  return {
    monitor: null,
    revision: "",
    selectedSignalId: "",
    selectedTaskRunId: "",
    selectedDetail: null,
    selectedGraphMonitor: null,
    loading: false,
    error: "",
    streamStatus: "closed",
    lastEvent: null,
  };
}

export function runMonitorRevision(monitor: RunMonitorEnvelope | null | undefined) {
  return String(monitor?.revision || monitor?.updated_at || "").trim();
}

export function runMonitorRevisionOrdinal(revision: string) {
  const match = revision.match(/^rtmon:(\d+(?:\.\d+)?):/);
  if (match) return Number(match[1]);
  const numeric = Number(revision);
  return Number.isFinite(numeric) ? numeric : 0;
}

export function isStaleRunMonitorRevision(incoming: string, current: string) {
  if (!incoming || !current) return false;
  const incomingOrdinal = runMonitorRevisionOrdinal(incoming);
  const currentOrdinal = runMonitorRevisionOrdinal(current);
  return incomingOrdinal > 0 && currentOrdinal > 0 && incomingOrdinal < currentOrdinal;
}

export function allRunMonitorSignals(monitor: RunMonitorEnvelope | null | undefined) {
  if (!monitor) return [];
  const rows = Array.isArray(monitor.signals) ? [...monitor.signals] : [];
  const lanes = monitor.management?.lanes;
  if (lanes) {
    rows.push(
      ...(Array.isArray(lanes.current) ? lanes.current : []),
      ...(Array.isArray(lanes.attention) ? lanes.attention : []),
      ...(Array.isArray(lanes.projects) ? lanes.projects : []),
      ...(Array.isArray(lanes.recent) ? lanes.recent : []),
      ...(Array.isArray(lanes.hidden) ? lanes.hidden : []),
    );
  }
  const seen = new Set<string>();
  return rows.filter((signal) => {
    const key = signal.signal_id || signal.task_instance_id || signal.task_run_id || signal.graph_run_id;
    if (!key) return true;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function findRunMonitorSignal(monitor: RunMonitorEnvelope | null | undefined, signalId: string) {
  const normalized = signalId.trim();
  if (!normalized) return null;
  return allRunMonitorSignals(monitor).find((signal) =>
    signal.signal_id === normalized
    || signal.task_instance_id === normalized
    || signal.task_run_id === normalized
  ) ?? null;
}

export function applyRunMonitorSnapshot(
  state: RunMonitorState,
  monitor: RunMonitorEnvelope,
  options: { selectedSignalId?: string; lastEvent?: RunMonitorEvent["runtime_event"] | null } = {},
): RunMonitorState {
  const nextRevision = runMonitorRevision(monitor);
  if (isStaleRunMonitorRevision(nextRevision, state.revision)) return state;
  const requested = findRunMonitorSignal(monitor, options.selectedSignalId || "");
  const current = findRunMonitorSignal(monitor, state.selectedSignalId);
  const autoSignals = autoSelectableRunMonitorSignals(monitor);
  const autoSignalIds = new Set(autoSignals.map(signalKey).filter(Boolean));
  const currentIsAutoSelectable = current ? autoSignalIds.has(signalKey(current)) : false;
  const selected = requested ?? (currentIsAutoSelectable ? current : null) ?? autoSignals[0] ?? null;
  return {
    ...state,
    monitor,
    revision: nextRevision,
    selectedSignalId: selected?.signal_id ?? "",
    selectedTaskRunId: selected?.task_run_id ?? "",
    selectedDetail: selected?.signal_id === state.selectedSignalId && nextRevision === state.revision ? state.selectedDetail : null,
    selectedGraphMonitor: selected?.signal_id === state.selectedSignalId && nextRevision === state.revision ? state.selectedGraphMonitor : null,
    error: "",
    lastEvent: options.lastEvent ?? state.lastEvent,
  };
}

export function selectRunMonitorSignal(state: RunMonitorState, signalId: string): RunMonitorState {
  const selected = findRunMonitorSignal(state.monitor, signalId);
  return {
    ...state,
    selectedSignalId: selected?.signal_id ?? "",
    selectedTaskRunId: selected?.task_run_id ?? "",
    selectedDetail: null,
    selectedGraphMonitor: null,
  };
}

export function signalDetailTaskRunId(signal: RunMonitorSignal | null | undefined) {
  const detail = signal?.detail_ref;
  return String(detail?.task_run_id || signal?.task_run_id || "").trim();
}

function signalKey(signal: RunMonitorSignal | null | undefined) {
  return signal?.signal_id || signal?.task_instance_id || signal?.task_run_id || signal?.graph_run_id || "";
}
