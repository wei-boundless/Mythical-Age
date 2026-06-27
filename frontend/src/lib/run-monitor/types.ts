import type {
  GraphRunMonitorView,
  HarnessTaskRunLiveMonitor,
  RunMonitorEventPayload,
  RunMonitorEnvelope as ApiRunMonitorEnvelope,
  RunMonitorSignal as ApiRunMonitorSignal,
} from "@/lib/api";

export type RunMonitorEnvelope = ApiRunMonitorEnvelope;
export type RunMonitorSignal = ApiRunMonitorSignal;
export type RunMonitorEvent = RunMonitorEventPayload;

export type RunMonitorStreamStatus = "connecting" | "connected" | "disconnected" | "closed";

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
