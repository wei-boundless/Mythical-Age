import type {
  GraphRunMonitorView,
  HarnessTaskRunLiveMonitor,
  RunMonitorEventPayload,
  RuntimeMonitorEnvelope,
  RuntimeMonitorSignal,
} from "@/lib/api";

export type RunMonitorEnvelope = RuntimeMonitorEnvelope;
export type RunMonitorSignal = RuntimeMonitorSignal;
export type RunMonitorEvent = RunMonitorEventPayload;

export type RunMonitorStreamStatus = "connecting" | "connected" | "fallback" | "closed";

export type RunMonitorState = {
  monitor: RunMonitorEnvelope | null;
  revision: string;
  selectedSignalId: string;
  selectedTaskRunId: string;
  selectedDetail: HarnessTaskRunLiveMonitor | null;
  selectedGraphMonitor: GraphRunMonitorView | null;
  loading: boolean;
  error: string;
  streamStatus: RunMonitorStreamStatus;
};
