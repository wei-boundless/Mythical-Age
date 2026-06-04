import type { Store } from "@/lib/store/core";
import type { ChatTaskEnvironmentBinding, StoreState, TaskGraphMonitorBinding, WorkspaceView } from "@/lib/store/types";
import {
  isRequestAbortError,
  runGraphRunUntilIdle,
  type GraphRunMonitorView,
  type RunMonitorEventPayload,
  type SessionScope,
} from "@/lib/api";

import {
  fetchRunMonitor,
  fetchRunMonitorGraphDetail,
  fetchRunMonitorTaskDetail,
  getRuntimeMonitorEventStreamUrl,
} from "./api";
import {
  applyRunMonitorSnapshot,
  findRunMonitorSignal,
  runMonitorRevision,
  selectRunMonitorSignal,
  signalDetailTaskRunId,
} from "./reducer";
import type { RunMonitorEnvelope, RunMonitorSignal } from "./types";

type RunMonitorHost = {
  hasActiveChatStream: () => boolean;
  patchRuntimeAttachmentFromRuntimeEvent: (prev: StoreState, event: NonNullable<RunMonitorEventPayload["runtime_event"]>) => StoreState;
  applySelectedSessionShell: (sessionId: string, scope?: Partial<SessionScope>) => boolean;
  bindTaskEnvironmentContext: (
    taskEnvironmentId: string,
    options?: {
      environmentLabel?: string;
      source?: ChatTaskEnvironmentBinding["source"];
    },
  ) => void;
  workspaceViewForTaskEnvironment: (taskEnvironmentId: string) => WorkspaceView;
  refreshSessionDetails: (sessionId: string) => Promise<void>;
  hydrateLatestOrchestrationSnapshot: (sessionId: string) => Promise<boolean>;
  syncWorkspaceViewUrl: (view: StoreState["activeWorkspaceView"]) => void;
};

export class RunMonitorController {
  private eventSource: EventSource | null = null;
  private timer: number | null = null;
  private reconnectTimer: number | null = null;
  private polling = false;
  private inFlight = false;
  private request = 0;
  private reconnectAttempts = 0;
  private graphAutoAdvanceTimer: number | null = null;
  private graphAutoAdvanceInFlight = false;

  constructor(
    private readonly store: Store<StoreState>,
    private readonly host: RunMonitorHost,
  ) {}

  start() {
    if (typeof window === "undefined") return;
    this.polling = true;
    if (typeof EventSource !== "undefined") {
      this.openStream();
      void this.refresh({ schedule: false });
      return;
    }
    this.store.setState((prev) => ({ ...prev, runMonitorStreamStatus: "fallback" }));
    void this.refresh();
  }

  stop() {
    if (typeof window === "undefined") return;
    this.polling = false;
    this.closeStream();
    this.clearTimer();
    this.clearReconnectTimer();
    this.stopGraphAutoAdvance();
    this.inFlight = false;
    this.store.setState((prev) => ({ ...prev, runMonitorStreamStatus: "closed" }));
  }

  async refresh(options: { schedule?: boolean } = {}) {
    if (this.inFlight) {
      if (options.schedule !== false) this.schedulePoll(5000);
      return;
    }
    this.inFlight = true;
    const requestId = ++this.request;
    this.store.setState((prev) => ({ ...prev, runMonitorLoading: true }));
    try {
      const monitor = await fetchRunMonitor(40);
      if (!this.polling || requestId !== this.request) return;
      this.applySnapshot(monitor);
    } catch (error) {
      if (!this.polling || requestId !== this.request) return;
      if (!this.isTransientError(error)) {
        this.store.setState((prev) => ({
          ...prev,
          runMonitorError: error instanceof Error ? error.message : "运行监控读取失败",
        }));
      }
    } finally {
      if (requestId === this.request) {
        this.inFlight = false;
        this.store.setState((prev) => ({ ...prev, runMonitorLoading: false }));
        if (options.schedule !== false && this.store.getState().runMonitorStreamStatus !== "connected") {
          this.schedulePoll();
        }
      }
    }
  }

  applySnapshot(monitor: RunMonitorEnvelope, options: { selectedSignalId?: string; lastEvent?: RunMonitorEventPayload["runtime_event"] | null } = {}) {
    const state = this.store.getState();
    const next = applyRunMonitorSnapshot(
      {
        monitor: state.runMonitor,
        revision: state.runMonitorRevision,
        selectedSignalId: state.runMonitorSelectedSignalId,
        selectedTaskRunId: state.runMonitorSelectedTaskRunId,
        selectedDetail: state.runMonitorSelectedDetail,
        selectedGraphMonitor: state.runMonitorSelectedGraphMonitor,
        loading: state.runMonitorLoading,
        error: state.runMonitorError,
        streamStatus: state.runMonitorStreamStatus,
        lastEvent: state.runMonitorLastEvent,
      },
      monitor,
      options,
    );
    this.store.setState((prev) => ({
      ...prev,
      runMonitor: next.monitor,
      runMonitorRevision: next.revision,
      runMonitorSelectedSignalId: next.selectedSignalId,
      runMonitorSelectedTaskRunId: next.selectedTaskRunId,
      runMonitorSelectedDetail: next.selectedDetail,
      runMonitorSelectedGraphMonitor: next.selectedGraphMonitor,
      runMonitorError: next.error,
      runMonitorLastEvent: next.lastEvent,
    }));
  }

  applyStreamPayload(payload: RunMonitorEventPayload | null) {
    if (!payload) return;
    if (payload.monitor) {
      this.applySnapshot(payload.monitor, {
        lastEvent: payload.runtime_event ?? null,
        selectedSignalId: signalIdFromRuntimeEvent(payload.runtime_event, payload.monitor),
      });
    }
    if (payload.runtime_event) {
      this.store.setState((prev) => this.host.patchRuntimeAttachmentFromRuntimeEvent(prev, payload.runtime_event as NonNullable<RunMonitorEventPayload["runtime_event"]>));
    }
  }

  selectSignal(signalId: string) {
    const normalized = signalId.trim();
    this.store.setState((prev) => {
      const next = selectRunMonitorSignal(
        {
          monitor: prev.runMonitor,
          revision: prev.runMonitorRevision,
          selectedSignalId: prev.runMonitorSelectedSignalId,
          selectedTaskRunId: prev.runMonitorSelectedTaskRunId,
          selectedDetail: prev.runMonitorSelectedDetail,
          selectedGraphMonitor: prev.runMonitorSelectedGraphMonitor,
          loading: prev.runMonitorLoading,
          error: prev.runMonitorError,
          streamStatus: prev.runMonitorStreamStatus,
          lastEvent: prev.runMonitorLastEvent,
        },
        normalized,
      );
      return {
        ...prev,
        runMonitorSelectedSignalId: next.selectedSignalId,
        runMonitorSelectedTaskRunId: next.selectedTaskRunId,
        runMonitorSelectedDetail: null,
        runMonitorSelectedGraphMonitor: null,
      };
    });
  }

  openSignal(signalId: string) {
    const signal = findRunMonitorSignal(this.store.getState().runMonitor, signalId);
    if (!signal) {
      this.selectSignal(signalId);
      return;
    }
    this.selectSignal(signal.signal_id);
    this.navigateSignal(signal);
    void this.loadSignalDetail(signal, this.store.getState().runMonitorRevision);
  }

  bindGraphRun(binding: Omit<TaskGraphMonitorBinding, "bound_at"> & { bound_at?: number }) {
    const normalized = normalizeTaskGraphBinding(binding);
    if (!normalized) return;
    this.store.setState((prev) => ({
      ...prev,
      taskGraphMonitorBinding: normalized,
      taskGraphMonitorError: "",
      taskGraphRunInteractionOpen: prev.taskGraphRunInteractionOpen,
    }));
  }

  clearGraphRun() {
    this.stopGraphAutoAdvance();
    this.store.setState((prev) => ({
      ...prev,
      taskGraphMonitorBinding: null,
      taskGraphBoundRunMonitor: null,
      taskGraphAutoAdvanceEnabled: false,
      taskGraphAutoAdvancePending: false,
      taskGraphMonitorError: "",
      taskGraphRunInteractionOpen: false,
    }));
  }

  setGraphRunInteractionOpen(open: boolean) {
    this.store.setState((prev) => ({ ...prev, taskGraphRunInteractionOpen: open }));
  }

  setGraphAutoAdvanceEnabled(enabled: boolean) {
    if (!enabled) {
      this.stopGraphAutoAdvance();
      this.store.setState((prev) => ({
        ...prev,
        taskGraphAutoAdvanceEnabled: false,
        taskGraphAutoAdvancePending: false,
      }));
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      taskGraphAutoAdvanceEnabled: true,
      taskGraphMonitorError: "",
    }));
    const state = this.store.getState();
    if (state.taskGraphBoundRunMonitor) {
      this.scheduleGraphAutoAdvance(state.taskGraphBoundRunMonitor);
      return;
    }
    void this.evaluateBoundGraphMonitor().then(() => {
      const nextState = this.store.getState();
      if (nextState.taskGraphAutoAdvanceEnabled && nextState.taskGraphBoundRunMonitor) {
        this.scheduleGraphAutoAdvance(nextState.taskGraphBoundRunMonitor);
      }
    });
  }

  async evaluateBoundGraphMonitor() {
    const binding = this.store.getState().taskGraphMonitorBinding;
    const graphRunId = String(binding?.graph_run_id || "").trim();
    const graphHarnessConfigId = String(binding?.graph_harness_config_id || "").trim();
    if (!graphRunId || !graphHarnessConfigId) {
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorError: "当前没有绑定可刷新的 GraphRun。" }));
      return;
    }
    this.store.setState((prev) => ({ ...prev, taskGraphMonitorLoading: true, taskGraphMonitorError: "" }));
    try {
      const monitor = await fetchRunMonitorGraphDetail(graphRunId, graphHarnessConfigId, binding?.session_scope);
      this.store.setState((prev) => ({ ...prev, taskGraphBoundRunMonitor: monitor }));
      await this.refresh({ schedule: false });
      if (this.store.getState().taskGraphAutoAdvanceEnabled) {
        this.scheduleGraphAutoAdvance(monitor);
      }
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: runMonitorErrorMessage(error, "GraphRun 监控刷新失败"),
      }));
    } finally {
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorLoading: false }));
    }
  }

  async continueBoundGraphRun() {
    const state = this.store.getState();
    const binding = state.taskGraphMonitorBinding;
    const graphRunId = String(binding?.graph_run_id || state.taskGraphBoundRunMonitor?.graph_run_id || "").trim();
    const graphHarnessConfigId = String(binding?.graph_harness_config_id || "").trim();
    if (!graphRunId || !graphHarnessConfigId) {
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorError: "当前没有可派发的 GraphRun。" }));
      return;
    }
    this.store.setState((prev) => ({ ...prev, taskGraphMonitorActionLoading: true, taskGraphMonitorError: "" }));
    try {
      await runGraphRunUntilIdle(graphRunId, {
        graph_harness_config_id: graphHarnessConfigId,
        session_scope: binding?.session_scope,
        max_dispatch_requests: 1,
      });
      const monitor = await fetchRunMonitorGraphDetail(graphRunId, graphHarnessConfigId, binding?.session_scope);
      this.store.setState((prev) => ({ ...prev, taskGraphBoundRunMonitor: monitor }));
      await this.refresh({ schedule: false });
      if (this.store.getState().taskGraphAutoAdvanceEnabled) {
        this.scheduleGraphAutoAdvance(monitor);
      }
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: error instanceof Error ? error.message : "续跑失败",
      }));
    } finally {
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorActionLoading: false }));
    }
  }

  private openStream() {
    this.closeStream();
    this.store.setState((prev) => ({ ...prev, runMonitorStreamStatus: "connecting" }));
    const source = new EventSource(getRuntimeMonitorEventStreamUrl(40));
    this.eventSource = source;
    source.onopen = () => {
      this.reconnectAttempts = 0;
      this.clearTimer();
      this.store.setState((prev) => ({ ...prev, runMonitorStreamStatus: "connected", runMonitorError: "" }));
    };
    source.onerror = () => {
      this.closeStream();
      this.store.setState((prev) => ({ ...prev, runMonitorStreamStatus: "fallback" }));
      this.scheduleReconnect();
      this.schedulePoll(2500);
    };
    source.addEventListener("runtime_monitor_snapshot", (event) => this.handleStreamMessage(event));
    source.addEventListener("runtime_monitor_event", (event) => this.handleStreamMessage(event));
    source.addEventListener("runtime_monitor_heartbeat", () => {
      this.store.setState((prev) => ({ ...prev, runMonitorStreamStatus: "connected" }));
    });
  }

  private handleStreamMessage(event: MessageEvent) {
    try {
      this.applyStreamPayload(JSON.parse(String(event.data || "{}")) as RunMonitorEventPayload);
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        runMonitorError: error instanceof Error ? error.message : "运行监控事件解析失败",
      }));
    }
  }

  private closeStream() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  private scheduleReconnect() {
    if (typeof window === "undefined" || !this.polling || typeof EventSource === "undefined") return;
    this.clearReconnectTimer();
    const delay = Math.min(30000, 1000 * Math.pow(2, Math.min(this.reconnectAttempts, 5)));
    this.reconnectAttempts += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.polling && this.store.getState().runMonitorStreamStatus !== "connected") {
        this.openStream();
      }
    }, delay);
  }

  private schedulePoll(delayMs = 2500) {
    if (typeof window === "undefined" || !this.polling) return;
    if (this.store.getState().runMonitorStreamStatus === "connected") return;
    const effectiveDelay = this.host.hasActiveChatStream() ? Math.max(delayMs, 15000) : delayMs;
    this.clearTimer();
    this.timer = window.setTimeout(() => void this.refresh(), effectiveDelay);
  }

  private clearTimer() {
    if (this.timer !== null && typeof window !== "undefined") {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer !== null && typeof window !== "undefined") {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private navigateSignal(signal: RunMonitorSignal) {
    const navigation = signal.navigation_target && typeof signal.navigation_target === "object" && !Array.isArray(signal.navigation_target)
      ? signal.navigation_target as Record<string, unknown>
      : {};
    const sessionId = String(navigation.session_id || signal.session_id || "").trim();
    const workspaceView = String(navigation.workspace_view || "").trim();
    const taskEnvironmentId = String(navigation.task_environment_id || "").trim();
    const environmentLabel = String(navigation.environment_label || taskEnvironmentId).trim();
    const owningTaskEnvironmentView = workspaceView === "task_environment" && taskEnvironmentId
      ? this.host.workspaceViewForTaskEnvironment(taskEnvironmentId)
      : "chat";
    if (workspaceView === "task_environment" && taskEnvironmentId) {
      this.host.bindTaskEnvironmentContext(taskEnvironmentId, {
        environmentLabel,
        source: "workspace-mode",
      });
    }
    if (sessionId) {
      this.host.applySelectedSessionShell(sessionId, { workspace_view: workspaceView || "chat", task_environment_id: taskEnvironmentId });
      void this.host.refreshSessionDetails(sessionId).catch(() => undefined);
      void this.host.hydrateLatestOrchestrationSnapshot(sessionId).catch(() => false);
    }
    if (signal.work_kind === "graph_task" || navigation.target_kind === "graph_task") {
      const graphRunId = String(signal.graph_ref?.graph_run_id || navigation.graph_run_id || "").trim();
      const graphHarnessConfigId = String(signal.graph_ref?.graph_harness_config_id || "").trim();
      const projectId = String(navigation.project_id || "").trim();
      this.host.syncWorkspaceViewUrl(owningTaskEnvironmentView);
      this.store.setState((prev) => ({
        ...prev,
        activeWorkspaceView: owningTaskEnvironmentView,
        taskGraphMonitorBinding: normalizeTaskGraphBinding({
          task_run_id: signal.task_run_id,
          graph_run_id: graphRunId,
          graph_harness_config_id: graphHarnessConfigId,
          graph_id: String(signal.graph_ref?.graph_id || navigation.graph_id || signal.graph_id || "").trim(),
          session_id: sessionId,
          project_id: projectId,
          title: signal.title,
          session_scope: {
            workspace_view: workspaceView || "task_environment",
            task_environment_id: taskEnvironmentId,
            project_id: projectId,
          },
        }) ?? prev.taskGraphMonitorBinding,
        centerWorkspaceTarget: {
          layer: "task-graph",
          mode: "monitor",
          graph_id: String(signal.graph_ref?.graph_id || navigation.graph_id || signal.graph_id || "").trim() || undefined,
          task_run_id: signal.task_run_id || undefined,
          task_instance_id: signal.signal_id,
          graph_run_id: graphRunId || undefined,
          focus_node_id: String(navigation.focus_node_id || "").trim() || undefined,
          requested_at: Date.now(),
        },
      }));
      return;
    }
    this.host.syncWorkspaceViewUrl(owningTaskEnvironmentView);
    this.store.setState((prev) => ({ ...prev, activeWorkspaceView: owningTaskEnvironmentView }));
  }

  private async loadSignalDetail(signal: RunMonitorSignal, expectedRevision: string) {
    const taskRunId = signalDetailTaskRunId(signal);
    const graphRunId = String(signal.graph_ref?.graph_run_id || signal.detail_ref?.graph_run_id || "").trim();
    const graphHarnessConfigId = String(signal.graph_ref?.graph_harness_config_id || signal.detail_ref?.graph_harness_config_id || "").trim();
    try {
      if (signal.work_kind === "graph_task" && graphRunId && graphHarnessConfigId) {
        const graphMonitor = await fetchRunMonitorGraphDetail(graphRunId, graphHarnessConfigId, { workspace_view: "task_environment" });
        if (this.store.getState().runMonitorRevision !== expectedRevision) return;
        this.store.setState((prev) => ({
          ...prev,
          runMonitorSelectedGraphMonitor: graphMonitor,
          taskGraphBoundRunMonitor: graphMonitor,
        }));
        return;
      }
      if (!taskRunId) return;
      const detail = await fetchRunMonitorTaskDetail(taskRunId).catch(() => null);
      if (this.store.getState().runMonitorRevision !== expectedRevision) return;
      this.store.setState((prev) => ({ ...prev, runMonitorSelectedDetail: detail }));
    } catch (error) {
      if (this.isTransientError(error)) return;
      this.store.setState((prev) => ({
        ...prev,
        runMonitorError: error instanceof Error ? error.message : "运行详情读取失败",
      }));
    }
  }

  private isTransientError(error: unknown) {
    if (isRequestAbortError(error)) return true;
    const message = error instanceof Error ? error.message : String(error ?? "");
    return message.includes("Failed to fetch") || message.includes("NetworkError") || message.includes("Load failed");
  }

  private stopGraphAutoAdvance() {
    if (typeof window !== "undefined" && this.graphAutoAdvanceTimer !== null) {
      window.clearTimeout(this.graphAutoAdvanceTimer);
    }
    this.graphAutoAdvanceTimer = null;
    this.graphAutoAdvanceInFlight = false;
  }

  private scheduleGraphAutoAdvance(monitor: GraphRunMonitorView) {
    if (typeof window === "undefined") return;
    const state = this.store.getState();
    if (!state.taskGraphAutoAdvanceEnabled || this.graphAutoAdvanceInFlight || this.graphAutoAdvanceTimer !== null) return;
    const loopState = monitor.graph_loop_state && typeof monitor.graph_loop_state === "object"
      ? monitor.graph_loop_state as Record<string, unknown>
      : {};
    const readyNodeIds = Array.isArray(loopState.ready_node_ids) ? loopState.ready_node_ids : [];
    const runningNodeIds = Array.isArray(loopState.running_node_ids) ? loopState.running_node_ids : [];
    const status = String(loopState.status || monitor.task_run?.status || monitor.graph_run?.status || "").toLowerCase();
    const activeWorkOrderCount = Number(monitor.active_node_work_order_count ?? (Array.isArray(monitor.active_node_work_orders) ? monitor.active_node_work_orders.length : 0));
    const terminal = ["completed", "succeeded", "success", "failed", "cancelled", "canceled", "stopped"].includes(status);
    if (terminal || readyNodeIds.length === 0 || runningNodeIds.length > 0 || activeWorkOrderCount > 0) {
      this.store.setState((prev) => ({ ...prev, taskGraphAutoAdvancePending: false }));
      return;
    }
    const binding = state.taskGraphMonitorBinding;
    const graphRunId = String(binding?.graph_run_id || monitor.graph_run_id || "").trim();
    const graphHarnessConfigId = String(binding?.graph_harness_config_id || loopState.config_id || "").trim();
    if (!graphRunId || !graphHarnessConfigId) {
      this.store.setState((prev) => ({ ...prev, taskGraphAutoAdvancePending: false }));
      return;
    }
    this.store.setState((prev) => ({ ...prev, taskGraphAutoAdvancePending: true }));
    this.graphAutoAdvanceTimer = window.setTimeout(() => {
      this.graphAutoAdvanceTimer = null;
      void this.runGraphAutoAdvance(graphRunId, graphHarnessConfigId);
    }, 2500);
  }

  private async runGraphAutoAdvance(graphRunId: string, graphHarnessConfigId: string) {
    const state = this.store.getState();
    if (!state.taskGraphAutoAdvanceEnabled || this.graphAutoAdvanceInFlight) {
      this.store.setState((prev) => ({ ...prev, taskGraphAutoAdvancePending: false }));
      return;
    }
    this.graphAutoAdvanceInFlight = true;
    this.store.setState((prev) => ({
      ...prev,
      taskGraphAutoAdvancePending: false,
      taskGraphMonitorActionLoading: true,
      taskGraphMonitorError: "",
    }));
    try {
      await runGraphRunUntilIdle(graphRunId, {
        graph_harness_config_id: graphHarnessConfigId,
        session_scope: state.taskGraphMonitorBinding?.session_scope,
        max_dispatch_requests: 1,
      });
      const monitor = await fetchRunMonitorGraphDetail(graphRunId, graphHarnessConfigId, state.taskGraphMonitorBinding?.session_scope);
      this.store.setState((prev) => ({ ...prev, taskGraphBoundRunMonitor: monitor }));
      await this.refresh({ schedule: false });
      this.scheduleGraphAutoAdvance(monitor);
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphAutoAdvanceEnabled: false,
        taskGraphMonitorError: runMonitorErrorMessage(error, "自动推进失败"),
      }));
    } finally {
      this.graphAutoAdvanceInFlight = false;
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorActionLoading: false }));
    }
  }
}

function signalIdFromRuntimeEvent(event: RunMonitorEventPayload["runtime_event"] | null | undefined, monitor: RunMonitorEnvelope) {
  if (!event) return "";
  const taskRunId = String(event.task_run_id || event.run_id || "").trim();
  if (!taskRunId) return "";
  return monitor.signals.find((signal) => signal.task_run_id === taskRunId || signal.signal_id === taskRunId)?.signal_id ?? "";
}

function normalizeTaskGraphBinding(
  binding: Omit<TaskGraphMonitorBinding, "bound_at"> & { bound_at?: number },
): TaskGraphMonitorBinding | null {
  const graphRunId = String(binding.graph_run_id || "").trim();
  const graphHarnessConfigId = String(binding.graph_harness_config_id || "").trim();
  if (!graphRunId || !graphHarnessConfigId) return null;
  return {
    task_run_id: String(binding.task_run_id || "").trim() || undefined,
    graph_run_id: graphRunId,
    graph_harness_config_id: graphHarnessConfigId,
    graph_id: String(binding.graph_id || "").trim() || undefined,
    session_id: String(binding.session_id || "").trim() || undefined,
    project_id: String(binding.project_id || "").trim() || undefined,
    session_scope: binding.session_scope,
    title: String(binding.title || "").trim() || undefined,
    bound_at: Number(binding.bound_at ?? Date.now() / 1000),
  };
}

function runMonitorErrorMessage(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  if (!message) return fallback;
  if (/request timed out after \d+ms/i.test(message)) return `${fallback}（请求超时）`;
  if (/failed to fetch|networkerror|load failed/i.test(message)) return `${fallback}（连接中断）`;
  return message;
}
