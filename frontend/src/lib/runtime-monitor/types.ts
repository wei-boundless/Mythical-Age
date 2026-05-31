import type {
  GlobalRuntimeMonitor,
  GlobalRuntimeMonitorItem,
  GraphRunMonitorView,
  HarnessTaskRunLiveMonitor,
  RuntimeMonitorEventPayload,
} from "@/lib/api";

export type RuntimeMonitorEnvelope = GlobalRuntimeMonitor;
export type RuntimeMonitorItem = GlobalRuntimeMonitorItem;
export type RuntimeMonitorDetail = HarnessTaskRunLiveMonitor;
export type RuntimeMonitorEventEnvelope = RuntimeMonitorEventPayload;

export type RuntimeTaskInstanceState = {
  taskInstanceId: string;
  rootTaskRunId: string;
  kind: string;
  sessionId: string;
  graphRunId: string;
  graphId: string;
  monitorItem: RuntimeMonitorItem | null;
  detail: RuntimeMonitorDetail | null;
  graphMonitor: GraphRunMonitorView | null;
  graphStatus: Record<string, unknown> | null;
  childRuntimeRefs: Array<Record<string, unknown>>;
  selectedNodeId: string;
  nodeOutputsById: Record<string, Record<string, unknown>>;
  artifactRefs: Array<Record<string, unknown>>;
  lastLoadedAt: number;
  loading: boolean;
  error: string;
};

export type RuntimeMonitorState = {
  monitor: RuntimeMonitorEnvelope | null;
  revision: string;
  selectedTaskInstanceId: string;
  selectedTaskRunId: string;
  selectedDetail: RuntimeMonitorDetail | null;
  selectedGraphMonitor: GraphRunMonitorView | null;
  instancesById: Record<string, RuntimeTaskInstanceState>;
  loading: boolean;
  error: string;
  streamStatus: "connecting" | "connected" | "fallback" | "closed";
  lastEvent: RuntimeMonitorEventEnvelope["runtime_event"] | null;
};
