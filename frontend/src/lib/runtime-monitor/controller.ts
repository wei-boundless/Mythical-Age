import type { Store } from "@/lib/store/core";
import type { StoreState, TaskGraphMonitorBinding } from "@/lib/store/types";
import type { GraphRunMonitorView, RuntimeMonitorEventPayload } from "@/lib/api";
import { isRequestAbortError, runGraphRunUntilIdle } from "@/lib/api";

import {
  fetchRuntimeMonitorGraphDetail,
  fetchRuntimeMonitorSnapshot,
  fetchRuntimeMonitorTaskDetail,
  getRuntimeMonitorEventStreamUrl,
} from "./api";
import { monitorItemInstanceId } from "./resourceRefs";
import {
  applyRuntimeMonitorSnapshot,
  runtimeMonitorRevision,
  selectRuntimeMonitorTaskInstance,
  visibleRuntimeMonitorItemsFromEnvelope,
} from "./reducer";
import { runtimeWorkProjectionFromMonitorItem, visibleRuntimeMonitorItems } from "./selectors";

type RuntimeMonitorHost = {
  hasActiveChatStream: () => boolean;
  patchRuntimeAttachmentFromRuntimeEvent: (prev: StoreState, event: NonNullable<RuntimeMonitorEventPayload["runtime_event"]>) => StoreState;
  applySelectedSessionShell: (sessionId: string) => boolean;
  refreshSessionDetails: (sessionId: string) => Promise<void>;
  hydrateLatestOrchestrationSnapshot: (sessionId: string) => Promise<boolean>;
  syncWorkspaceViewUrl: (view: StoreState["activeWorkspaceView"]) => void;
};

export class RuntimeMonitorController {
  private timer: number | null = null;
  private inFlight = false;
  private polling = false;
  private request = 0;
  private eventSource: EventSource | null = null;
  private reconnectTimer: number | null = null;
  private detailRefreshTimer: number | null = null;
  private detailInFlightTaskRunId: string | null = null;
  private detailInFlightRevision = "";
  private queuedDetailTaskRunId: string | null = null;
  private queuedDetailRevision = "";
  private detailLoadedAt = new Map<string, number>();
  private visibilityListener: (() => void) | null = null;
  private graphAutoAdvanceTimer: number | null = null;
  private graphAutoAdvanceInFlight = false;

  constructor(
    private readonly store: Store<StoreState>,
    private readonly host: RuntimeMonitorHost,
  ) {}

  start() {
    if (typeof window === "undefined") return;
    this.polling = true;
    this.startVisibilityBackoff();
    this.startEventStream();
    if (this.inFlight) return;
    if (this.timer !== null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
    void this.refresh();
  }

  stop() {
    if (typeof window === "undefined") return;
    this.polling = false;
    this.stopVisibilityBackoff();
    this.stopEventStream();
    this.stopGraphAutoAdvance();
    if (this.timer !== null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.inFlight = false;
  }

  deferForActiveStream() {
    if (typeof window === "undefined" || !this.host.hasActiveChatStream()) return;
    if (this.timer !== null) {
      window.clearTimeout(this.timer);
      this.timer = null;
      this.schedulePoll(90000);
    }
  }

  async refresh() {
    if (this.inFlight) {
      this.schedulePoll(5000);
      return;
    }
    this.inFlight = true;
    const requestId = ++this.request;
    this.store.setState((prev) => ({ ...prev, globalRuntimeMonitorLoading: true }));
    try {
      const monitor = await fetchRuntimeMonitorSnapshot(40);
      if (!this.polling || requestId !== this.request) return;
      this.applySnapshot(monitor);
    } catch (error) {
      if (!this.polling || requestId !== this.request) return;
      if (this.isTransientError(error)) {
        this.store.setState((prev) => ({
          ...prev,
          globalRuntimeMonitorStreamStatus: prev.globalRuntimeMonitorStreamStatus === "connected"
            ? "fallback"
            : prev.globalRuntimeMonitorStreamStatus,
        }));
        return;
      }
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorError: error instanceof Error ? error.message : "全局运行监控读取失败",
      }));
    } finally {
      if (requestId === this.request) {
        this.inFlight = false;
        this.store.setState((prev) => ({ ...prev, globalRuntimeMonitorLoading: false }));
        this.schedulePoll();
      }
    }
  }

  selectTaskInstance(taskInstanceId: string) {
    const normalized = taskInstanceId.trim();
    this.store.setState((prev) => {
      const monitorState = selectRuntimeMonitorTaskInstance(
        {
          monitor: prev.globalRuntimeMonitor,
          revision: prev.globalRuntimeMonitorRevision,
          selectedTaskInstanceId: prev.globalRuntimeMonitorSelectedTaskInstanceId,
          selectedTaskRunId: prev.globalRuntimeMonitorSelectedTaskRunId,
          selectedDetail: prev.globalRuntimeMonitorSelectedLiveMonitor,
          selectedGraphMonitor: prev.globalRuntimeMonitorSelectedGraphMonitor,
          instancesById: prev.runtimeMonitorInstancesById,
          loading: prev.globalRuntimeMonitorLoading,
          error: prev.globalRuntimeMonitorError,
          streamStatus: prev.globalRuntimeMonitorStreamStatus,
          lastEvent: prev.globalRuntimeMonitorLastEvent,
        },
        normalized,
      );
      return {
        ...prev,
        globalRuntimeMonitorSelectedTaskInstanceId: monitorState.selectedTaskInstanceId,
        globalRuntimeMonitorSelectedTaskRunId: monitorState.selectedTaskRunId,
        globalRuntimeMonitorSelectedLiveMonitor: null,
        globalRuntimeMonitorSelectedGraphMonitor: null,
        runtimeMonitorInstancesById: monitorState.instancesById,
      };
    });
    const state = this.store.getState();
    if (state.globalRuntimeMonitorSelectedTaskRunId) {
      this.queueDetailRefresh(state.globalRuntimeMonitorSelectedTaskRunId, state.globalRuntimeMonitorRevision);
    }
  }

  openTaskInstance(taskInstanceId: string) {
    const normalized = taskInstanceId.trim();
    const visibleRuns = visibleRuntimeMonitorItems(this.store.getState().globalRuntimeMonitor);
    const selected = visibleRuns.find((item) => monitorItemInstanceId(item) === normalized || item.task_run_id === normalized);
    if (!selected) {
      this.selectTaskInstance(normalized);
      return;
    }
    const navigation = selected.navigation_target && typeof selected.navigation_target === "object" && !Array.isArray(selected.navigation_target)
      ? selected.navigation_target as Record<string, unknown>
      : {};
    const work = runtimeWorkProjectionFromMonitorItem(selected);
    const taskInstanceIdForState = monitorItemInstanceId(selected);
    if (navigation.target_kind === "session") {
      const sessionId = String(navigation.session_id || selected.session_id || "").trim();
      if (sessionId) {
        this.host.applySelectedSessionShell(sessionId);
        void this.host.refreshSessionDetails(sessionId).catch(() => undefined);
        void this.host.hydrateLatestOrchestrationSnapshot(sessionId).catch(() => false);
      }
      this.store.setState((prev) => ({
        ...prev,
        activeWorkspaceView: "chat",
        globalRuntimeMonitorSelectedTaskInstanceId: taskInstanceIdForState,
        globalRuntimeMonitorSelectedTaskRunId: selected.task_run_id,
        globalRuntimeMonitorSelectedLiveMonitor: null,
        globalRuntimeMonitorSelectedGraphMonitor: null,
      }));
      this.queueDetailRefresh(selected.task_run_id, this.store.getState().globalRuntimeMonitorRevision);
      return;
    }
    const graphRunId = String(navigation.graph_run_id || selected.graph_run_id || "").trim();
    const graphHarnessConfigId = String(selected.graph_harness_config_id || "").trim();
    const taskGraphBinding = work.workKind === "task_graph_run"
      ? this.normalizeTaskGraphMonitorBinding({
          task_run_id: selected.task_run_id,
          graph_run_id: graphRunId,
          graph_harness_config_id: graphHarnessConfigId,
          graph_id: String(navigation.graph_id || selected.graph_id || ""),
          session_id: String(navigation.session_id || selected.session_id || ""),
          title: work.title,
        })
      : null;
    const openGraphWorkspace = navigation.target_kind === "graph_task" || work.workKind === "task_graph_run";
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: openGraphWorkspace ? "chat" : "orchestration",
      globalRuntimeMonitorSelectedTaskInstanceId: taskInstanceIdForState,
      globalRuntimeMonitorSelectedTaskRunId: selected.task_run_id,
      globalRuntimeMonitorSelectedLiveMonitor: null,
      globalRuntimeMonitorSelectedGraphMonitor: null,
      taskGraphMonitorBinding: taskGraphBinding ?? prev.taskGraphMonitorBinding,
      taskGraphRunInteractionOpen: false,
      centerWorkspaceTarget: openGraphWorkspace ? {
        layer: "task-graph",
        mode: "monitor",
        graph_id: String(navigation.graph_id || selected.graph_id || work.graphId || "").trim() || undefined,
        task_run_id: selected.task_run_id,
        task_instance_id: taskInstanceIdForState,
        graph_run_id: graphRunId || undefined,
        focus_node_id: String(navigation.focus_node_id || "").trim() || undefined,
        requested_at: Date.now(),
      } : prev.centerWorkspaceTarget,
    }));
    this.host.syncWorkspaceViewUrl(openGraphWorkspace ? "chat" : "orchestration");
    this.queueDetailRefresh(selected.task_run_id, this.store.getState().globalRuntimeMonitorRevision);
  }

  bindGraphRun(binding: Omit<TaskGraphMonitorBinding, "bound_at"> & { bound_at?: number }) {
    const normalized = this.normalizeTaskGraphMonitorBinding(binding);
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
    } else {
      void this.evaluateBoundGraphMonitor().then(() => {
        const nextState = this.store.getState();
        if (nextState.taskGraphAutoAdvanceEnabled && nextState.taskGraphBoundRunMonitor) {
          this.scheduleGraphAutoAdvance(nextState.taskGraphBoundRunMonitor);
        }
      });
    }
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
      const monitor = await fetchRuntimeMonitorGraphDetail(graphRunId, graphHarnessConfigId);
      this.store.setState((prev) => ({ ...prev, taskGraphBoundRunMonitor: monitor }));
      await this.refresh();
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: error instanceof Error ? error.message : "GraphRun 监控刷新失败",
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
        max_dispatch_requests: 1,
      });
      const monitor = await fetchRuntimeMonitorGraphDetail(graphRunId, graphHarnessConfigId);
      this.store.setState((prev) => ({ ...prev, taskGraphBoundRunMonitor: monitor }));
      await this.refresh();
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: error instanceof Error ? error.message : "续跑失败",
      }));
    } finally {
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorActionLoading: false }));
    }
  }

  private startEventStream() {
    if (typeof window === "undefined") return;
    if (typeof EventSource !== "function") {
      this.store.setState((prev) => ({ ...prev, globalRuntimeMonitorStreamStatus: "fallback" }));
      this.schedulePoll(1200);
      return;
    }
    if (this.eventSource) return;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.store.setState((prev) => ({ ...prev, globalRuntimeMonitorStreamStatus: "connecting" }));
    const eventSource = new EventSource(getRuntimeMonitorEventStreamUrl(40));
    this.eventSource = eventSource;
    eventSource.onopen = () => {
      if (this.timer !== null) {
        window.clearTimeout(this.timer);
        this.timer = null;
      }
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorError: "",
        globalRuntimeMonitorStreamStatus: "connected",
      }));
      this.schedulePoll(60000);
    };
    eventSource.onerror = () => {
      if (this.eventSource === eventSource) {
        eventSource.close();
        this.eventSource = null;
      }
      this.store.setState((prev) => ({ ...prev, globalRuntimeMonitorStreamStatus: "fallback" }));
      this.schedulePoll(5000);
      this.scheduleReconnect();
    };
    eventSource.addEventListener("runtime_monitor_snapshot", (event) => {
      this.applyStreamPayload(this.parsePayload(event));
    });
    eventSource.addEventListener("runtime_monitor_event", (event) => {
      this.applyStreamPayload(this.parsePayload(event));
    });
  }

  private stopEventStream() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    if (this.reconnectTimer !== null && typeof window !== "undefined") {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.detailRefreshTimer !== null && typeof window !== "undefined") {
      window.clearTimeout(this.detailRefreshTimer);
      this.detailRefreshTimer = null;
    }
    this.detailInFlightTaskRunId = null;
    this.detailInFlightRevision = "";
    this.queuedDetailTaskRunId = null;
    this.queuedDetailRevision = "";
    this.store.setState((prev) => ({ ...prev, globalRuntimeMonitorStreamStatus: "closed" }));
  }

  private scheduleReconnect(delayMs = 5000) {
    if (typeof window === "undefined" || !this.polling) return;
    if (this.reconnectTimer !== null || this.eventSource) return;
    const pageHidden = typeof document !== "undefined" && document.visibilityState === "hidden";
    const effectiveDelay = pageHidden ? Math.max(delayMs, 60000) : delayMs;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.polling) this.startEventStream();
    }, effectiveDelay);
  }

  private parsePayload(event: Event): RuntimeMonitorEventPayload | null {
    const message = event as MessageEvent<string>;
    try {
      return JSON.parse(message.data) as RuntimeMonitorEventPayload;
    } catch {
      return null;
    }
  }

  applyStreamPayload(payload: RuntimeMonitorEventPayload | null) {
    if (!payload) return;
    const eventTaskRunId = formalTaskRunIdFromRuntimeEvent(payload.runtime_event);
    if (payload.monitor) {
      this.applySnapshot(payload.monitor, {
        detailTaskRunId: eventTaskRunId,
        lastEvent: payload.runtime_event ?? null,
      });
      if (payload.runtime_event) {
        this.store.setState((prev) => this.host.patchRuntimeAttachmentFromRuntimeEvent(prev, payload.runtime_event as NonNullable<RuntimeMonitorEventPayload["runtime_event"]>));
      }
    } else if (payload.runtime_event) {
      this.store.setState((prev) => this.host.patchRuntimeAttachmentFromRuntimeEvent({
        ...prev,
        globalRuntimeMonitorLastEvent: payload.runtime_event ?? null,
      }, payload.runtime_event as NonNullable<RuntimeMonitorEventPayload["runtime_event"]>));
      if (eventTaskRunId) {
        this.queueDetailRefresh(eventTaskRunId);
      }
    }
  }

  applySnapshot(
    monitor: NonNullable<RuntimeMonitorEventPayload["monitor"]>,
    options: { detailTaskRunId?: string; lastEvent?: RuntimeMonitorEventPayload["runtime_event"] | null } = {},
  ) {
    const state = this.store.getState();
    const monitorState = applyRuntimeMonitorSnapshot(
      {
        monitor: state.globalRuntimeMonitor,
        revision: state.globalRuntimeMonitorRevision,
        selectedTaskInstanceId: state.globalRuntimeMonitorSelectedTaskInstanceId,
        selectedTaskRunId: state.globalRuntimeMonitorSelectedTaskRunId,
        selectedDetail: state.globalRuntimeMonitorSelectedLiveMonitor,
        selectedGraphMonitor: state.globalRuntimeMonitorSelectedGraphMonitor,
        instancesById: state.runtimeMonitorInstancesById,
        loading: state.globalRuntimeMonitorLoading,
        error: state.globalRuntimeMonitorError,
        streamStatus: state.globalRuntimeMonitorStreamStatus,
        lastEvent: state.globalRuntimeMonitorLastEvent,
      },
      monitor,
      options,
    );
    const visibleRuns = visibleRuntimeMonitorItemsFromEnvelope(monitor);
    const detailTaskRunId = visibleRuns.some((item) => item.task_run_id === options.detailTaskRunId)
      ? options.detailTaskRunId
      : monitorState.selectedTaskRunId;
    this.store.setState((prev) => ({
      ...prev,
      globalRuntimeMonitor: monitorState.monitor,
      globalRuntimeMonitorRevision: monitorState.revision,
      globalRuntimeMonitorSelectedTaskInstanceId: monitorState.selectedTaskInstanceId,
      globalRuntimeMonitorSelectedTaskRunId: monitorState.selectedTaskRunId,
      globalRuntimeMonitorSelectedLiveMonitor: monitorState.selectedDetail,
      globalRuntimeMonitorSelectedGraphMonitor: monitorState.selectedGraphMonitor,
      runtimeMonitorInstancesById: monitorState.instancesById,
      globalRuntimeMonitorError: "",
      globalRuntimeMonitorLastEvent: monitorState.lastEvent,
    }));
    this.queueDetailRefresh(detailTaskRunId, runtimeMonitorRevision(monitor));
  }

  private queueDetailRefresh(taskRunId?: string, revision?: string) {
    if (typeof window === "undefined") return;
    const normalized = String(taskRunId || "").trim();
    const state = this.store.getState();
    const selected = state.globalRuntimeMonitorSelectedTaskRunId;
    const monitorRevision = revision || state.globalRuntimeMonitorRevision;
    if (!normalized || normalized !== selected || !monitorRevision || monitorRevision !== state.globalRuntimeMonitorRevision) return;
    if (this.detailInFlightTaskRunId) {
      this.queuedDetailTaskRunId = normalized;
      this.queuedDetailRevision = monitorRevision;
      return;
    }
    const lastLoadedAt = this.detailLoadedAt.get(normalized) ?? 0;
    const cooldownRemainingMs = Math.max(0, 3000 - (Date.now() - lastLoadedAt));
    const delayMs = Math.max(this.host.hasActiveChatStream() ? 6000 : 750, cooldownRemainingMs);
    if (this.detailRefreshTimer !== null) {
      window.clearTimeout(this.detailRefreshTimer);
    }
    this.detailRefreshTimer = window.setTimeout(() => {
      this.detailRefreshTimer = null;
      void this.loadTaskRunDetail(normalized, monitorRevision);
    }, delayMs);
  }

  async loadTaskRunDetail(taskRunId: string, revision?: string) {
    const normalized = taskRunId.trim();
    if (!normalized) return;
    const stateAtStart = this.store.getState();
    const expectedRevision = revision || stateAtStart.globalRuntimeMonitorRevision;
    if (stateAtStart.globalRuntimeMonitorSelectedTaskRunId !== normalized || stateAtStart.globalRuntimeMonitorRevision !== expectedRevision) return;
    const selected = visibleRuntimeMonitorItems(stateAtStart.globalRuntimeMonitor).find((item) => item.task_run_id === normalized);
    if (!selected) return;
    if (this.detailInFlightTaskRunId) {
      this.queuedDetailTaskRunId = normalized;
      this.queuedDetailRevision = expectedRevision;
      return;
    }
    const work = runtimeWorkProjectionFromMonitorItem(selected);
    this.detailInFlightTaskRunId = normalized;
    this.detailInFlightRevision = expectedRevision;
    try {
      const liveMonitor = await fetchRuntimeMonitorTaskDetail(normalized).catch(() => null);
      const stateAfterLoad = this.store.getState();
      if (stateAfterLoad.globalRuntimeMonitorSelectedTaskRunId !== normalized || stateAfterLoad.globalRuntimeMonitorRevision !== expectedRevision) return;
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorSelectedLiveMonitor: liveMonitor,
        globalRuntimeMonitorSelectedGraphMonitor: null,
        runtimeMonitorInstancesById: {
          ...prev.runtimeMonitorInstancesById,
          [monitorItemInstanceId(selected)]: {
            ...(prev.runtimeMonitorInstancesById[monitorItemInstanceId(selected)] ?? {}),
            taskInstanceId: monitorItemInstanceId(selected),
            rootTaskRunId: String(selected.root_task_run_id || selected.task_run_id || ""),
            kind: String(selected.kind || ""),
            sessionId: String(selected.session_id || ""),
            graphRunId: String(selected.graph_run_id || ""),
            graphId: String(selected.graph_id || ""),
            monitorItem: selected,
            detail: liveMonitor,
            graphMonitor: null,
            graphStatus: selected.graph_status ?? null,
            childRuntimeRefs: Array.isArray(selected.child_runtime_refs) ? selected.child_runtime_refs : [],
            artifactRefs: Array.isArray(selected.artifact_refs) ? selected.artifact_refs : [],
            lastLoadedAt: Date.now(),
            loading: false,
            error: "",
            selectedNodeId: "",
            nodeOutputsById: {},
          },
        },
        globalRuntimeMonitorError: "",
      }));
      this.detailLoadedAt.set(normalized, Date.now());
    } catch (error) {
      const stateAfterError = this.store.getState();
      if (stateAfterError.globalRuntimeMonitorSelectedTaskRunId !== normalized || stateAfterError.globalRuntimeMonitorRevision !== expectedRevision) return;
      if (this.isTransientError(error)) return;
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorError: error instanceof Error ? error.message : "任务详情监控读取失败",
      }));
    } finally {
      if (this.detailInFlightTaskRunId === normalized && this.detailInFlightRevision === expectedRevision) {
        this.detailInFlightTaskRunId = null;
        this.detailInFlightRevision = "";
      }
      const queued = this.queuedDetailTaskRunId;
      const queuedRevision = this.queuedDetailRevision;
      this.queuedDetailTaskRunId = null;
      this.queuedDetailRevision = "";
      const current = this.store.getState();
      if (queued && queued === current.globalRuntimeMonitorSelectedTaskRunId && queuedRevision && queuedRevision === current.globalRuntimeMonitorRevision) {
        this.queueDetailRefresh(queued, queuedRevision);
      }
    }
  }

  private schedulePoll(delayMs = 2500) {
    if (typeof window === "undefined" || !this.polling) return;
    const streamStatus = this.store.getState().globalRuntimeMonitorStreamStatus;
    const pageHidden = typeof document !== "undefined" && document.visibilityState === "hidden";
    const connectedDelay = this.host.hasActiveChatStream() ? 90000 : 60000;
    const fallbackDelay = this.host.hasActiveChatStream() ? 15000 : delayMs;
    const streamDelay = streamStatus === "connected" ? Math.max(delayMs, connectedDelay) : Math.max(delayMs, fallbackDelay);
    const effectiveDelay = pageHidden ? Math.max(streamDelay, 60000) : streamDelay;
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => void this.refresh(), effectiveDelay);
  }

  private startVisibilityBackoff() {
    if (typeof document === "undefined" || this.visibilityListener) return;
    this.visibilityListener = () => {
      if (!this.polling) return;
      if (document.visibilityState === "visible") {
        if (this.timer !== null) {
          window.clearTimeout(this.timer);
          this.timer = null;
        }
        void this.refresh();
      }
    };
    document.addEventListener("visibilitychange", this.visibilityListener);
  }

  private stopVisibilityBackoff() {
    if (typeof document === "undefined" || !this.visibilityListener) return;
    document.removeEventListener("visibilitychange", this.visibilityListener);
    this.visibilityListener = null;
  }

  private normalizeTaskGraphMonitorBinding(
    binding: Omit<TaskGraphMonitorBinding, "bound_at"> & { bound_at?: number },
  ): TaskGraphMonitorBinding | null {
    const taskRunId = String(binding.task_run_id ?? "").trim();
    const graphRunId = String(binding.graph_run_id ?? "").trim();
    const graphHarnessConfigId = String(binding.graph_harness_config_id ?? "").trim();
    if (!graphRunId || !graphHarnessConfigId) return null;
    return {
      task_run_id: taskRunId || undefined,
      graph_run_id: graphRunId,
      graph_harness_config_id: graphHarnessConfigId,
      graph_id: String(binding.graph_id ?? "").trim() || undefined,
      session_id: String(binding.session_id ?? "").trim() || undefined,
      project_id: String(binding.project_id ?? "").trim() || undefined,
      title: String(binding.title ?? "").trim() || undefined,
      bound_at: Number(binding.bound_at ?? Date.now() / 1000),
    };
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
        max_dispatch_requests: 1,
      });
      const monitor = await fetchRuntimeMonitorGraphDetail(graphRunId, graphHarnessConfigId);
      this.store.setState((prev) => ({ ...prev, taskGraphBoundRunMonitor: monitor }));
      this.scheduleGraphAutoAdvance(monitor);
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphAutoAdvanceEnabled: false,
        taskGraphMonitorError: error instanceof Error ? error.message : "自动推进失败",
      }));
    } finally {
      this.graphAutoAdvanceInFlight = false;
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorActionLoading: false }));
    }
  }

  private isTransientError(error: unknown) {
    if (isRequestAbortError(error)) return true;
    const message = error instanceof Error ? error.message : String(error ?? "");
    return message.includes("Failed to fetch") || message.includes("NetworkError") || message.includes("Load failed");
  }
}

function formalTaskRunIdFromRuntimeEvent(event: RuntimeMonitorEventPayload["runtime_event"] | null | undefined) {
  if (!event) return "";
  const payload = event.payload && typeof event.payload === "object" && !Array.isArray(event.payload)
    ? event.payload
    : {};
  const taskRun = payload.task_run && typeof payload.task_run === "object" && !Array.isArray(payload.task_run)
    ? payload.task_run as Record<string, unknown>
    : {};
  for (const value of [taskRun.task_run_id, payload.task_run_id, event.run_id, event.task_run_id]) {
    const normalized = String(value ?? "").trim();
    if (normalized.startsWith("taskrun:")) {
      return normalized;
    }
  }
  return "";
}
