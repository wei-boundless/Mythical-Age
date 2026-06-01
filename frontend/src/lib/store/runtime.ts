"use client";

import {
  runGraphRunUntilIdle,
  loadFile,
  createSession,
  deleteSession,
  getChatRun,
  getLatestChatRunForSession,
  getCodeEnvironmentWorkspaceTree,
  getModelProviderConfig,
  getSoulImageAssetConfig,
  getWorkspaceContext,
  getOrchestrationHarnessSessionLiveMonitor,
  pauseOrchestrationHarnessTaskRun,
  getRagMode,
  resumeOrchestrationHarnessTaskRun,
  getSessionHistory,
  getSessionTimeline,
  getSessionTokens,
  isRequestAbortError,
  listSessions,
  listSkills,
  renameSession,
  saveFile,
  setRagMode,
  stopOrchestrationHarnessTaskRun,
  clearChatStreamCursor,
  readChatStreamCursor,
  streamChat,
  streamExistingChatRun,
  switchSoulSystemSeed,
  truncateSessionMessages
} from "@/lib/api";
import type { ChatStreamCursor, GlobalRuntimeMonitor, RuntimeMonitorEventPayload, SessionRuntimeAttachment } from "@/lib/api";
import {
  ACTIVE_SOUL_PATH,
  SOUL_SEED_PATHS,
  inferSoulKey,
  parseSoulSeed,
  type SoulKey,
  type SoulSummary
} from "@/lib/souls";

import { createIdleSessionActivity, type Store } from "./core";
import { reduceStreamEvent, startStreamingTurn, type StreamSession } from "./events";
import { RuntimeMonitorController } from "../runtime-monitor/controller";
import type { CenterWorkspaceTarget, ChatMode, ChatModelSelection, ChatTaskEnvironmentBinding, ChatThinkingMode, Message, RuntimeProgressEntry, SearchPolicySource, StoreActions, StoreState, TaskGraphMonitorBinding, TaskSelectionState, WorkspaceView } from "./types";
import { makeId, toUiMessages } from "./utils";

type HarnessSessionMonitor = NonNullable<Awaited<ReturnType<typeof getOrchestrationHarnessSessionLiveMonitor>>["monitor"]>;
type RuntimeMonitorEvent = NonNullable<RuntimeMonitorEventPayload["runtime_event"]>;
const MAX_LIVE_RUNTIME_PROGRESS_ENTRIES = 24;

export class WorkspaceRuntime {
  private initializePromise: Promise<void> | null = null;
  private createSessionPromise: Promise<string> | null = null;
  private sessionDetailsRequest = 0;
  private orchestrationHydrateRequest = 0;
  private runtimeMonitorController: RuntimeMonitorController;
  private sessionRefreshTimers: number[] = [];
  private sessionListFailureNotifiedAt = 0;
  private streamingSessionCache = new Map<string, Pick<StoreState, "messages" | "orchestrationSnapshot">>();
  private removedStreamingSessionIds = new Set<string>();
  private streamAbortControllers = new Map<string, AbortController>();
  private stoppedStreamingSessionIds = new Set<string>();
  private recoveringStreamSessionIds = new Set<string>();

  readonly actions: StoreActions;

  constructor(private readonly store: Store<StoreState>) {
    this.runtimeMonitorController = new RuntimeMonitorController(this.store, {
      hasActiveChatStream: () => this.hasActiveChatStream(),
      patchRuntimeAttachmentFromRuntimeEvent: (prev, event) => this.patchRuntimeAttachmentFromRuntimeEvent(prev, event as RuntimeMonitorEvent),
      applySelectedSessionShell: (sessionId) => this.applySelectedSessionShell(sessionId),
      refreshSessionDetails: (sessionId) => this.refreshSessionDetails(sessionId),
      hydrateLatestOrchestrationSnapshot: (sessionId) => this.hydrateLatestOrchestrationSnapshot(sessionId),
      syncWorkspaceViewUrl: (view) => this.syncWorkspaceViewUrl(view),
    });
    this.actions = {
      setWorkspaceView: (view) => {
        this.setWorkspaceView(view);
      },
      refreshWorkspaceTree: async () => {
        await this.refreshWorkspaceTree();
      },
      createNewSession: async () => {
        await this.createNewSession();
      },
      selectSession: async (sessionId) => {
        await this.selectSession(sessionId);
      },
      sendMessage: async (value) => {
        await this.sendMessage(value);
      },
      stopCurrentStream: () => {
        this.stopCurrentStream();
      },
      pauseActiveTaskRun: async () => {
        await this.pauseActiveTaskRun();
      },
      resumeActiveTaskRun: async () => {
        await this.resumeActiveTaskRun();
      },
      stopActiveTaskRun: async () => {
        await this.stopActiveTaskRun();
      },
      resendEditedMessage: async (messageId, value) => {
        await this.resendEditedMessage(messageId, value);
      },
      toggleRagMode: async () => {
        await this.toggleRagMode();
      },
      toggleSearchPolicySource: (source) => {
        this.toggleSearchPolicySource(source);
      },
      setSelectedChatModel: (selectionId) => {
        this.setSelectedChatModel(selectionId);
      },
      setSelectedChatMode: (mode) => {
        this.setSelectedChatMode(mode);
      },
      setChatThinkingMode: (mode) => {
        this.setChatThinkingMode(mode);
      },
      switchSoul: async (key) => {
        await this.switchSoul(key);
      },
      renameCurrentSession: async (title) => {
        await this.renameCurrentSession(title);
      },
      removeSession: async (sessionId) => {
        await this.removeSession(sessionId);
      },
      loadInspectorFile: async (path) => {
        await this.loadInspectorFile(path);
      },
      updateInspectorContent: (value) => {
        this.updateInspectorContent(value);
      },
      saveInspector: async () => {
        await this.saveInspector();
      },
      setSidebarWidth: (width) => {
        this.setSidebarWidth(width);
      },
      setInspectorWidth: (width) => {
        this.setInspectorWidth(width);
      },
      setMemoryInspectorTarget: (target) => {
        this.setMemoryInspectorTarget(target);
      },
      setOrchestrationInspectorTarget: (target) => {
        this.setOrchestrationInspectorTarget(target);
      },
      setOrchestrationSnapshot: (snapshot) => {
        this.setOrchestrationSnapshot(snapshot);
      },
      bindTaskGraphMonitorRun: (binding) => {
        this.bindTaskGraphMonitorRun(binding);
      },
      clearTaskGraphMonitorRun: () => {
        this.clearTaskGraphMonitorRun();
      },
      setTaskGraphRunInteractionOpen: (open) => {
        this.setTaskGraphRunInteractionOpen(open);
      },
      setTaskGraphAutoAdvanceEnabled: (enabled) => {
        this.setTaskGraphAutoAdvanceEnabled(enabled);
      },
      evaluateBoundTaskGraphMonitor: async () => {
        await this.evaluateBoundTaskGraphMonitor();
      },
      continueBoundTaskGraphRun: async () => {
        await this.continueBoundTaskGraphRun();
      },
      resumeTaskGraphRun: async (taskGraphRunId, payload) => {
        await this.resumeTaskGraphRun(taskGraphRunId, payload);
      },
      setTaskSelection: (selection) => {
        this.setTaskSelection(selection);
      },
      setChatTaskEnvironmentBinding: (binding) => {
        this.setChatTaskEnvironmentBinding(binding);
      },
      clearChatTaskEnvironmentBinding: () => {
        this.clearChatTaskEnvironmentBinding();
      },
      selectGlobalRuntimeMonitorTaskRun: (taskRunId) => {
        this.selectGlobalRuntimeMonitorTaskRun(taskRunId);
      },
      openGlobalRuntimeMonitorTaskRun: (taskRunId) => {
        this.openGlobalRuntimeMonitorTaskRun(taskRunId);
      },
      openTaskGraphWorkspace: (target) => {
        this.openTaskGraphWorkspace(target);
      },
      clearCenterWorkspaceTarget: () => {
        this.clearCenterWorkspaceTarget();
      },
      refreshGlobalRuntimeMonitor: async () => {
        await this.refreshGlobalRuntimeMonitor();
      }
    };
  }

  startGlobalRuntimeMonitor() {
    this.runtimeMonitorController.start();
  }

  async initialize() {
    if (this.initializePromise) {
      return this.initializePromise;
    }
    this.initializePromise = this.initializeWorkspace().finally(() => {
      this.initializePromise = null;
    });
    return this.initializePromise;
  }

  private async initializeWorkspace() {
    this.store.setState((prev) => ({
      ...prev,
      workspaceInitializing: true,
    }));
    try {
      let sessions = await listSessions();
      this.store.setState((prev) => ({
        ...prev,
        sessions,
      }));

      const currentSessionId = this.store.getState().currentSessionId;
      if (!currentSessionId && sessions.length) {
        const sessionId = sessions[0].id;
        const restoredFromStreamCache = this.applySelectedSessionShell(sessionId);
        if (!restoredFromStreamCache) {
          const reattached = await this.reattachChatRunForSession(sessionId);
          if (!reattached) {
            void this.refreshSessionDetails(sessionId).catch(() => undefined);
            void this.hydrateLatestOrchestrationSnapshot(sessionId).catch(() => undefined);
          }
        }
      } else if (!currentSessionId) {
        await this.createFreshSession();
      }
      this.store.setState((prev) => ({
        ...prev,
        workspaceInitializing: false,
      }));
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        workspaceInitializing: false,
        sessionActivity: {
          level: "error",
          title: "会话连接失败",
          detail: this.errorMessage(error, "无法创建或读取会话，请确认后端服务仍在 127.0.0.1:8003。"),
          event: "workspace_initialize_failed",
          receipt: {
            level: "error",
            title: "会话连接失败",
            body: this.errorMessage(error, "无法创建或读取会话，请确认后端服务仍在 127.0.0.1:8003。"),
            debug: {
              event: "workspace_initialize_failed",
            },
          },
          updatedAt: Date.now(),
        },
      }));
    }

    void this.loadWorkspaceMetadata().catch(() => undefined);
    void this.refreshWorkspaceTree().catch(() => undefined);
    void this.loadInspectorMemoryFile().catch(() => undefined);
  }

  private async loadWorkspaceMetadata() {
    const [rag, skills, souls, modelProviderConfig, soulImageAssetConfig, workspaceContext] = await Promise.all([
      getRagMode().catch(() => null),
      listSkills().catch(() => []),
      this.loadSouls().catch(() => ({ options: [], activeSoulKey: null })),
      getModelProviderConfig().catch(() => null),
      getSoulImageAssetConfig().catch(() => null),
      getWorkspaceContext().catch(() => null),
    ]);
    this.store.setState((prev) => ({
      ...prev,
      ragMode: Boolean(rag?.enabled),
      searchPolicy: {
        ...prev.searchPolicy,
        rag: Boolean(rag?.enabled)
      },
      modelProviderConfig,
      soulImageAssetConfig,
      workspaceContext,
      skills,
      soulOptions: souls.options,
      activeSoulKey: souls.activeSoulKey,
      selectedChatMode: this.resolveSelectedChatMode(prev.selectedChatModelId, modelProviderConfig),
      chatThinkingMode: chatThinkingModeFromProviderConfig(modelProviderConfig),
    }));
  }

  private async loadInspectorMemoryFile() {
    const file = await loadFile("durable_memory/index/MEMORY.md").catch(() => null);
    if (!file) {
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      inspectorPath: file.path,
      inspectorContent: file.content,
      inspectorDirty: false
    }));
  }

  dispose() {
    if (typeof window === "undefined") {
      return;
    }
    for (const timer of this.sessionRefreshTimers) {
      window.clearTimeout(timer);
    }
    this.sessionRefreshTimers = [];
    this.runtimeMonitorController.stop();
  }

  private scheduleSessionRefreshes(delays: number[] = [5000, 15000]) {
    if (typeof window === "undefined") {
      return;
    }
    for (const timer of this.sessionRefreshTimers) {
      window.clearTimeout(timer);
    }
    this.sessionRefreshTimers = delays.map((delay) =>
      window.setTimeout(() => {
        void this.refreshSessions().catch((error) => {
          this.noteSessionRefreshFailure(error);
        });
      }, delay)
    );
  }

  private async refreshSessions() {
    const sessions = await listSessions();
    this.sessionListFailureNotifiedAt = 0;
    this.store.setState((prev) => ({ ...prev, sessions }));
  }

  private refreshSessionsInBackground() {
    void this.refreshSessions().catch((error) => {
      this.noteSessionRefreshFailure(error);
    });
  }

  private noteSessionRefreshFailure(error: unknown) {
    const now = Date.now();
    if (now - this.sessionListFailureNotifiedAt < 15000) {
      return;
    }
    this.sessionListFailureNotifiedAt = now;
    console.debug("[workspace-runtime] background session refresh skipped", {
      event: "session_list_refresh_failed",
      error: this.errorMessage(error, "会话列表读取超时，前端已保持当前页面不掉线。"),
    });
  }

  private async refreshSkills() {
    const skills = await listSkills();
    this.store.setState((prev) => ({ ...prev, skills }));
  }

  private async refreshSouls() {
    const souls = await this.loadSouls();
    this.store.setState((prev) => ({
      ...prev,
      soulOptions: souls.options,
      activeSoulKey: souls.activeSoulKey
    }));
  }

  private async refreshSessionDetails(sessionId: string) {
    const requestId = ++this.sessionDetailsRequest;
    try {
      const [history, tokens] = await Promise.all([
        getSessionTimeline(sessionId).catch(() => getSessionHistory(sessionId)),
        getSessionTokens(sessionId)
      ]);
      if (this.store.getState().currentSessionId !== sessionId || this.sessionDetailsRequest !== requestId) {
        return;
      }
      this.store.setState((prev) => {
        const refreshedMessages = this.mergeVolatileMessageProgress(
          toUiMessages(
            history.messages,
            "runtime_attachments" in history ? history.runtime_attachments ?? [] : [],
          ),
          prev.messages,
        );
        const next: StoreState = {
          ...prev,
          messages: refreshedMessages,
          tokenStats: tokens,
        };
        return prev.sessionActivity.event === "session_history_load_failed"
          ? this.clearSessionActivityFor(next, sessionId)
          : next;
      });
    } catch (error) {
      if (this.store.getState().currentSessionId !== sessionId || this.sessionDetailsRequest !== requestId) {
        return;
      }
      this.store.setState((prev) => {
        const activity: StoreState["sessionActivity"] = {
          level: "error",
          title: "历史读取超时",
          detail: this.errorMessage(error, "会话历史暂时读取失败，当前页面不会中断，可以继续使用或稍后重试。"),
          event: "session_history_load_failed",
          receipt: {
            level: "error",
            title: "历史读取超时",
            body: this.errorMessage(error, "会话历史暂时读取失败，当前页面不会中断，可以继续使用或稍后重试。"),
            debug: {
              event: "session_history_load_failed",
              sessionId,
            },
          },
          updatedAt: Date.now(),
        };
        return {
          ...prev,
          sessionActivity: activity,
          sessionActivitiesById: {
            ...prev.sessionActivitiesById,
            [sessionId]: activity,
          },
        };
      });
    }
  }

  private mergeVolatileMessageProgress(refreshedMessages: Message[], currentMessages: Message[]) {
    if (!currentMessages.some((message) => message.runtimeProgress?.length)) {
      return refreshedMessages;
    }
    const currentBySourceIndex = new Map<number, Message>();
    for (const message of currentMessages) {
      if (message.role === "assistant" && message.sourceIndex !== undefined) {
        currentBySourceIndex.set(message.sourceIndex, message);
      }
    }
    return refreshedMessages.map((message) => {
      if (message.role !== "assistant" || message.sourceIndex === undefined) {
        return message;
      }
      const current = currentBySourceIndex.get(message.sourceIndex);
      if (!current?.runtimeProgress?.length) {
        return message;
      }
      return {
        ...message,
        runtimeProgress: this.mergeMessageRuntimeProgress(message.runtimeProgress, current.runtimeProgress),
        stageStatus: message.stageStatus ?? current.stageStatus,
      };
    });
  }

  private mergeMessageRuntimeProgress(
    persisted: RuntimeProgressEntry[] | undefined,
    volatile: RuntimeProgressEntry[],
  ) {
    const merged = [...(persisted ?? [])];
    const ids = new Set(merged.map((entry) => entry.id));
    for (const entry of volatile) {
      if (ids.has(entry.id)) {
        continue;
      }
      merged.push(entry);
      ids.add(entry.id);
    }
    return merged
      .sort((left, right) => {
        const leftTime = Number(left.createdAt ?? left.completedAt ?? left.startedAt ?? 0) || 0;
        const rightTime = Number(right.createdAt ?? right.completedAt ?? right.startedAt ?? 0) || 0;
        if (leftTime && rightTime && leftTime !== rightTime) {
          return leftTime - rightTime;
        }
        return 0;
      })
      .slice(-MAX_LIVE_RUNTIME_PROGRESS_ENTRIES);
  }

  private addActiveStreamSession(sessionId: string) {
    this.store.setState((prev) => {
      const activeStreamSessionIds = prev.activeStreamSessionIds.includes(sessionId)
        ? prev.activeStreamSessionIds
        : [...prev.activeStreamSessionIds, sessionId];
      return {
        ...prev,
        activeStreamSessionIds,
        isStreaming: activeStreamSessionIds.length > 0,
      };
    });
  }

  private removeActiveStreamSession(prev: StoreState, sessionId: string): StoreState {
    const activeStreamSessionIds = prev.activeStreamSessionIds.filter((id) => id !== sessionId);
    return {
      ...prev,
      isStreaming: activeStreamSessionIds.length > 0,
      activeStreamSessionIds,
    };
  }

  private visibleSessionActivity(state: StoreState, sessionId: string | null = state.currentSessionId) {
    if (!sessionId) {
      return createIdleSessionActivity();
    }
    return state.sessionActivitiesById[sessionId] ?? createIdleSessionActivity();
  }

  private clearSessionActivityFor(state: StoreState, sessionId: string) {
    const idle = createIdleSessionActivity(Date.now());
    return {
      ...state,
      sessionActivity: state.currentSessionId === sessionId ? idle : state.sessionActivity,
      sessionActivitiesById: {
        ...state.sessionActivitiesById,
        [sessionId]: idle,
      },
    };
  }

  private captureSessionActivity(state: StoreState, sessionId: string): StoreState {
    return {
      ...state,
      sessionActivitiesById: {
        ...state.sessionActivitiesById,
        [sessionId]: state.sessionActivity,
      },
    };
  }

  private projectSelectedSessionActivity(state: StoreState, sessionId: string | null): StoreState {
    return {
      ...state,
      sessionActivity: this.visibleSessionActivity(state, sessionId),
    };
  }

  private applyVisibleStreamState(streamState: StoreState, activeStreamSessionIds: string[]) {
    this.store.setState((prev) => ({
      ...prev,
      messages: streamState.messages,
      orchestrationSnapshot: streamState.orchestrationSnapshot,
      taskGraphLiveMonitor: null,
      activeStreamSessionIds,
      isStreaming: activeStreamSessionIds.length > 0,
      sessionActivity: streamState.sessionActivity,
      sessionActivitiesById: {
        ...prev.sessionActivitiesById,
        ...streamState.sessionActivitiesById,
      },
    }));
  }

  private async createFreshSession() {
    if (this.createSessionPromise) {
      return this.createSessionPromise;
    }

    const pending = (async () => {
      const created = await createSession();
      this.store.setState((prev) => ({
        ...prev,
        sessions: [created, ...prev.sessions.filter((session) => session.id !== created.id)],
        currentSessionId: created.id,
        messages: [],
        tokenStats: null
      }));
      this.store.setState((prev) => this.clearSessionActivityFor(prev, created.id));
      return created.id;
    })();

    this.createSessionPromise = pending;
    try {
      return await pending;
    } finally {
      this.createSessionPromise = null;
    }
  }

  private async ensureSession() {
    const pendingSession = this.createSessionPromise;
    if (pendingSession) {
      return pendingSession;
    }
    const current = this.store.getState().currentSessionId;
    if (current) {
      return current;
    }
    return this.createFreshSession();
  }

  private async createNewSession() {
    let sessionId: string;
    try {
      sessionId = await this.createFreshSession();
    } catch (error) {
      this.noteSessionRefreshFailure(error);
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      currentSessionId: sessionId,
      messages: [],
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: null,
      tokenStats: null
    }));
    this.store.setState((prev) => this.clearSessionActivityFor(prev, sessionId));
    await this.refreshSessions().catch((error) => {
      this.noteSessionRefreshFailure(error);
    });
  }

  private async selectSession(sessionId: string) {
    const restoredFromStreamCache = this.applySelectedSessionShell(sessionId);
    if (restoredFromStreamCache) {
      return;
    }
    const reattached = await this.reattachChatRunForSession(sessionId);
    if (reattached) {
      return;
    }
    await this.refreshSessionDetails(sessionId).catch(() => undefined);
    await this.hydrateLatestOrchestrationSnapshot(sessionId).catch(() => false);
  }

  private applySelectedSessionShell(sessionId: string) {
    const streamingCache = this.streamingSessionCache.get(sessionId);
    if (this.store.getState().activeStreamSessionIds.includes(sessionId) && streamingCache) {
      this.store.setState((prev) => ({
        ...prev,
        currentSessionId: sessionId,
        messages: streamingCache.messages,
        orchestrationSnapshot: streamingCache.orchestrationSnapshot,
        taskGraphLiveMonitor: null,
        tokenStats: null
      }));
      this.store.setState((prev) => this.projectSelectedSessionActivity(prev, sessionId));
      return true;
    }
    this.store.setState((prev) => ({
      ...prev,
      currentSessionId: sessionId,
      messages: [],
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: null,
      tokenStats: null
    }));
    this.store.setState((prev) => this.projectSelectedSessionActivity(prev, sessionId));
    return false;
  }

  private async reattachChatRunForSession(sessionId: string) {
    if (this.store.getState().activeStreamSessionIds.includes(sessionId) || this.recoveringStreamSessionIds.has(sessionId)) {
      return true;
    }
    this.recoveringStreamSessionIds.add(sessionId);
    try {
      const cursor = readChatStreamCursor(sessionId);
      let streamRunId = cursor?.streamRunId || "";
      if (streamRunId) {
        const cursorRun = await getChatRun(streamRunId).catch(() => null);
        if (
          !cursorRun
          || cursorRun.session_id !== sessionId
          || cursorRun.is_reconnectable === false
        ) {
          clearChatStreamCursor(sessionId);
          streamRunId = "";
        }
      }
      if (!streamRunId) {
        const latestRun = await getLatestChatRunForSession(sessionId, true).catch(() => null);
        streamRunId = String(latestRun?.stream_run_id || "");
      }
      if (!streamRunId) {
        return false;
      }
      await this.refreshSessionDetails(sessionId).catch(() => undefined);
      this.startRecoveredChatRunStream(sessionId, streamRunId, cursor);
      return true;
    } finally {
      this.recoveringStreamSessionIds.delete(sessionId);
    }
  }

  private startRecoveredChatRunStream(sessionId: string, streamRunId: string, cursor: ChatStreamCursor | null) {
    if (this.store.getState().activeStreamSessionIds.includes(sessionId)) {
      return;
    }
    const abortController = new AbortController();
    this.streamAbortControllers.set(sessionId, abortController);
    this.removedStreamingSessionIds.delete(sessionId);
    this.stoppedStreamingSessionIds.delete(sessionId);

    const assistantId = makeId();
    const sourceIndex = this.nextMessageSourceIndex(this.store.getState().messages);
    const activeStreamSessionIds = this.store.getState().activeStreamSessionIds.includes(sessionId)
      ? this.store.getState().activeStreamSessionIds
      : [...this.store.getState().activeStreamSessionIds, sessionId];
    let streamState: StoreState = {
      ...this.store.getState(),
      messages: [
        ...this.store.getState().messages,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          toolCalls: [],
          retrievals: [],
          runtimeProgress: [],
          stageStatus: "正在重新连接",
          sourceIndex,
        }
      ],
      orchestrationSnapshot: null,
      activeStreamSessionIds,
      isStreaming: activeStreamSessionIds.length > 0,
      sessionActivity: {
        level: "running",
        title: "正在重新连接",
        detail: "正在挂回当前运行并回放进度。",
        event: "stream_restore_started",
        receipt: {
          level: "running",
          title: "正在重新连接",
          body: "正在挂回当前运行并回放进度。",
          debug: { event: "stream_restore_started" },
        },
        updatedAt: Date.now(),
      },
    };
    streamState = this.captureSessionActivity(streamState, sessionId);
    const transitionSession: StreamSession = { assistantId };
    this.streamingSessionCache.set(sessionId, {
      messages: streamState.messages,
      orchestrationSnapshot: streamState.orchestrationSnapshot,
    });
    this.addActiveStreamSession(sessionId);
    this.deferMonitorPollingForActiveStream();
    if (this.store.getState().currentSessionId === sessionId) {
      this.applyVisibleStreamState(streamState, activeStreamSessionIds);
    }

    void (async () => {
      let streamEndedWithError = false;
      try {
        const streamResult = await streamExistingChatRun(
          sessionId,
          streamRunId,
          {
            onEvent: (event, data) => {
              if (this.removedStreamingSessionIds.has(sessionId)) {
                return;
              }
              const isCurrentStreamSession = this.store.getState().currentSessionId === sessionId;
              const baseState = isCurrentStreamSession ? this.store.getState() : streamState;
              const transition = reduceStreamEvent(baseState, transitionSession, event, data);
              const currentActiveStreamSessionIds = this.store.getState().activeStreamSessionIds.includes(sessionId)
                ? this.store.getState().activeStreamSessionIds
                : [...this.store.getState().activeStreamSessionIds, sessionId];
              streamState = {
                ...transition.state,
                currentSessionId: sessionId,
                activeStreamSessionIds: currentActiveStreamSessionIds,
                isStreaming: currentActiveStreamSessionIds.length > 0,
              };
              streamState = this.captureSessionActivity(streamState, sessionId);
              this.streamingSessionCache.set(sessionId, {
                messages: streamState.messages,
                orchestrationSnapshot: streamState.orchestrationSnapshot,
              });
              if (isCurrentStreamSession) {
                this.applyVisibleStreamState(streamState, currentActiveStreamSessionIds);
              }
            }
          },
          {
            signal: abortController.signal,
            initialCursor: cursor,
            replayFromStart: true,
          }
        );
        if (streamResult.terminalEvent === "stopped") {
          this.stoppedStreamingSessionIds.add(sessionId);
        }
      } catch (error) {
        if (this.removedStreamingSessionIds.has(sessionId)) {
          return;
        }
        streamEndedWithError = true;
        const streamWasStopped = this.stoppedStreamingSessionIds.has(sessionId) || this.isAbortError(error);
        const transition = reduceStreamEvent(
          this.store.getState().currentSessionId === sessionId ? this.store.getState() : streamState,
          transitionSession,
          streamWasStopped ? "stopped" : "error",
          streamWasStopped
            ? { reason: "user_stopped" }
            : { error: error instanceof Error ? error.message : "unknown error" }
        );
        const currentActiveStreamSessionIds = this.store.getState().activeStreamSessionIds.includes(sessionId)
          ? this.store.getState().activeStreamSessionIds
          : [...this.store.getState().activeStreamSessionIds, sessionId];
        streamState = {
          ...transition.state,
          currentSessionId: sessionId,
          activeStreamSessionIds: currentActiveStreamSessionIds,
          isStreaming: currentActiveStreamSessionIds.length > 0,
        };
        streamState = this.captureSessionActivity(streamState, sessionId);
        this.streamingSessionCache.set(sessionId, {
          messages: streamState.messages,
          orchestrationSnapshot: streamState.orchestrationSnapshot,
        });
        if (this.store.getState().currentSessionId === sessionId) {
          this.applyVisibleStreamState(streamState, currentActiveStreamSessionIds);
        }
      } finally {
        this.streamAbortControllers.delete(sessionId);
        this.store.setState((prev) => {
          const next = this.removeActiveStreamSession(prev, sessionId);
          next.sessionActivitiesById = {
            ...next.sessionActivitiesById,
            [sessionId]: streamState.sessionActivity,
          };
          if (streamEndedWithError) {
            next.sessionActivity = next.currentSessionId === sessionId
              ? streamState.sessionActivity
              : this.visibleSessionActivity(next);
          }
          return next;
        });
        this.streamingSessionCache.delete(sessionId);
        const streamSessionWasRemoved = this.removedStreamingSessionIds.has(sessionId);
        const streamSessionWasStopped = this.stoppedStreamingSessionIds.has(sessionId);
        this.removedStreamingSessionIds.delete(sessionId);
        this.stoppedStreamingSessionIds.delete(sessionId);
        if (
          !streamSessionWasRemoved
          && !streamSessionWasStopped
          && !streamEndedWithError
          && this.store.getState().currentSessionId === sessionId
        ) {
          await this.refreshSessionDetails(sessionId);
          await this.hydrateLatestOrchestrationSnapshot(sessionId);
          await this.refreshGlobalRuntimeMonitor();
        }
        this.refreshSessionsInBackground();
        this.scheduleSessionRefreshes();
      }
    })();
  }

  private async sendMessage(value: string) {
    const trimmed = value.trim();
    const state = this.store.getState();
    if (!trimmed) {
      return;
    }

    let sessionId: string;
    try {
      sessionId = await this.ensureSession();
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "error",
          title: "会话连接失败",
          detail: this.errorMessage(error, "无法创建会话，请确认后端服务仍在 127.0.0.1:8003。"),
          event: "session_create_failed",
          receipt: {
            level: "error",
            title: "会话连接失败",
            body: this.errorMessage(error, "无法创建会话，请确认后端服务仍在 127.0.0.1:8003。"),
            debug: {
              event: "session_create_failed",
            },
          },
          updatedAt: Date.now(),
        },
      }));
      throw error;
    }
    if (this.store.getState().activeStreamSessionIds.includes(sessionId)) {
      const error = new Error("当前会话仍在生成回答，请等待收口后再发送。");
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "running",
          title: "正在生成回答",
          detail: error.message,
          event: "session_stream_already_active",
          updatedAt: Date.now(),
        },
      }));
      throw error;
    }
    this.removedStreamingSessionIds.delete(sessionId);
    this.stoppedStreamingSessionIds.delete(sessionId);
    const abortController = new AbortController();
    this.streamAbortControllers.set(sessionId, abortController);
    const ephemeralSystemMessages = [...(state.pendingEphemeralSystemMessages ?? [])];
    const searchPolicy = this.enabledSearchPolicy(state);
    const imageGeneration = this.chatImageGenerationPayload(state);
    const isImageGenerationTurn = Boolean(imageGeneration);
    let consumedEphemeralSystemMessages = false;
    let streamEndedWithError = false;
    this.store.setState((prev) => ({
      ...prev,
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: prev.taskGraphLiveMonitor,
      orchestrationInspectorTarget: prev.orchestrationInspectorTarget?.source === "live-session"
        ? null
        : prev.orchestrationInspectorTarget,
    }));
    let transition = startStreamingTurn(this.store.getState(), trimmed);
    const nextSourceIndex = this.nextMessageSourceIndex(this.store.getState().messages);
    transition = {
      ...transition,
      state: {
        ...transition.state,
        messages: transition.state.messages.map((message, index, list) =>
          index === list.length - 2 && message.role === "user"
            ? { ...message, sourceIndex: nextSourceIndex }
            : index === list.length - 1 && message.role === "assistant"
              ? { ...message, sourceIndex: nextSourceIndex + 1 }
            : message
        )
      }
    };
    const activeStreamSessionIds = this.store.getState().activeStreamSessionIds.includes(sessionId)
      ? this.store.getState().activeStreamSessionIds
      : [...this.store.getState().activeStreamSessionIds, sessionId];
    let streamState: StoreState = {
      ...transition.state,
      activeStreamSessionIds,
      isStreaming: activeStreamSessionIds.length > 0,
    };
    streamState = this.captureSessionActivity(streamState, sessionId);
    transition = {
      ...transition,
      state: streamState
    };
    this.streamingSessionCache.set(sessionId, {
      messages: streamState.messages,
      orchestrationSnapshot: streamState.orchestrationSnapshot,
    });
    this.addActiveStreamSession(sessionId);
    this.deferMonitorPollingForActiveStream();
    if (isImageGenerationTurn) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphLiveMonitor: null,
      }));
    }
    if (this.store.getState().currentSessionId === sessionId) {
      this.applyVisibleStreamState(streamState, this.store.getState().activeStreamSessionIds);
    }

    try {
      const streamResult = await streamChat(
        {
          message: trimmed,
          session_id: sessionId,
          ephemeral_system_messages: ephemeralSystemMessages,
          search_policy: searchPolicy,
          task_selection: this.chatTaskSelectionPayload(state),
          model_selection: this.chatModelSelectionPayload(state),
          image_generation: imageGeneration
            ? {
                ...imageGeneration,
                target_id: `turn-${sessionId}-${Date.now()}`,
                overwrite: true,
              }
            : undefined,
        },
        {
          onEvent: (event, data) => {
            if (this.removedStreamingSessionIds.has(sessionId)) {
              return;
            }
            const isCurrentStreamSession = this.store.getState().currentSessionId === sessionId;
            const baseState = isCurrentStreamSession ? this.store.getState() : streamState;
            transition = reduceStreamEvent(baseState, transition.session, event, data);
            const currentActiveStreamSessionIds = this.store.getState().activeStreamSessionIds.includes(sessionId)
              ? this.store.getState().activeStreamSessionIds
              : [...this.store.getState().activeStreamSessionIds, sessionId];
            streamState = {
              ...transition.state,
              currentSessionId: sessionId,
              activeStreamSessionIds: currentActiveStreamSessionIds,
              isStreaming: currentActiveStreamSessionIds.length > 0,
            };
            streamState = this.captureSessionActivity(streamState, sessionId);
            transition = {
              ...transition,
              state: streamState
            };
            this.streamingSessionCache.set(sessionId, {
              messages: streamState.messages,
              orchestrationSnapshot: streamState.orchestrationSnapshot,
            });
            if (isCurrentStreamSession) {
              this.applyVisibleStreamState(streamState, currentActiveStreamSessionIds);
            }
          }
        },
        { signal: abortController.signal }
      );
      consumedEphemeralSystemMessages = streamResult.terminalEvent === "done";
      streamEndedWithError = streamResult.terminalEvent === "error";
      if (streamResult.terminalEvent === "stopped") {
        this.stoppedStreamingSessionIds.add(sessionId);
      }
    } catch (error) {
      if (this.removedStreamingSessionIds.has(sessionId)) {
        return;
      }
      streamEndedWithError = true;
      const streamWasStopped = this.stoppedStreamingSessionIds.has(sessionId) || this.isAbortError(error);
      transition = reduceStreamEvent(
        this.store.getState().currentSessionId === sessionId ? this.store.getState() : streamState,
        transition.session,
        streamWasStopped ? "stopped" : "error",
        streamWasStopped
          ? { reason: "user_stopped" }
          : { error: error instanceof Error ? error.message : "unknown error" }
      );
      const currentActiveStreamSessionIds = this.store.getState().activeStreamSessionIds.includes(sessionId)
        ? this.store.getState().activeStreamSessionIds
        : [...this.store.getState().activeStreamSessionIds, sessionId];
      streamState = {
        ...transition.state,
        currentSessionId: sessionId,
        activeStreamSessionIds: currentActiveStreamSessionIds,
        isStreaming: currentActiveStreamSessionIds.length > 0,
      };
      streamState = this.captureSessionActivity(streamState, sessionId);
      this.streamingSessionCache.set(sessionId, {
        messages: streamState.messages,
        orchestrationSnapshot: streamState.orchestrationSnapshot,
      });
      if (this.store.getState().currentSessionId === sessionId) {
        this.applyVisibleStreamState(streamState, currentActiveStreamSessionIds);
      }
    } finally {
      this.streamAbortControllers.delete(sessionId);
      const shouldClearEphemeral = (prev: StoreState) =>
        consumedEphemeralSystemMessages
        && ephemeralSystemMessages.length > 0
        && prev.pendingEphemeralSystemMessages.join("\n") === ephemeralSystemMessages.join("\n");
      const shouldRestoreEphemeral = (prev: StoreState) =>
        !consumedEphemeralSystemMessages
        && ephemeralSystemMessages.length > 0
        && !prev.pendingEphemeralSystemMessages.length;
      this.store.setState((prev) => {
        const next = this.removeActiveStreamSession(prev, sessionId);
        next.sessionActivitiesById = {
          ...next.sessionActivitiesById,
          [sessionId]: streamState.sessionActivity,
        };
        if (streamEndedWithError) {
          next.sessionActivity = next.currentSessionId === sessionId
            ? streamState.sessionActivity
            : this.visibleSessionActivity(next);
        }
        if (
          shouldClearEphemeral(prev)
        ) {
          next.pendingEphemeralSystemMessages = [];
        }
        if (
          shouldRestoreEphemeral(prev)
        ) {
          next.pendingEphemeralSystemMessages = ephemeralSystemMessages;
        }
        return next;
      });
      this.streamingSessionCache.delete(sessionId);
      const streamSessionWasRemoved = this.removedStreamingSessionIds.has(sessionId);
      const streamSessionWasStopped = this.stoppedStreamingSessionIds.has(sessionId);
      this.removedStreamingSessionIds.delete(sessionId);
      this.stoppedStreamingSessionIds.delete(sessionId);
      if (
        !streamSessionWasRemoved
        && !streamSessionWasStopped
        && !streamEndedWithError
        && !isImageGenerationTurn
        && this.store.getState().currentSessionId === sessionId
      ) {
        await this.refreshSessionDetails(sessionId);
        await this.hydrateLatestOrchestrationSnapshot(sessionId);
        await this.refreshGlobalRuntimeMonitor();
      }
      this.refreshSessionsInBackground();
      this.scheduleSessionRefreshes();
    }
  }

  private stopCurrentStream() {
    const sessionId = this.store.getState().currentSessionId;
    if (!sessionId || !this.store.getState().activeStreamSessionIds.includes(sessionId)) {
      return;
    }
    this.stoppedStreamingSessionIds.add(sessionId);
    this.streamAbortControllers.get(sessionId)?.abort();
  }

  private async pauseActiveTaskRun() {
    const taskRunId = this.activeControllableTaskRunId();
    if (!taskRunId) {
      return;
    }
    await pauseOrchestrationHarnessTaskRun(taskRunId, "user_pause_from_chat");
    await this.refreshActiveSessionMonitor();
  }

  private async resumeActiveTaskRun() {
    const taskRunId = this.activeControllableTaskRunId();
    if (!taskRunId) {
      return;
    }
    await resumeOrchestrationHarnessTaskRun(taskRunId, 12);
    await this.refreshActiveSessionMonitor();
  }

  private async stopActiveTaskRun() {
    const taskRunId = this.activeControllableTaskRunId();
    if (!taskRunId) {
      return;
    }
    await stopOrchestrationHarnessTaskRun(taskRunId, "user_stop_from_chat");
    await this.refreshActiveSessionMonitor();
  }

  private activeControllableTaskRunId() {
    const monitor = this.store.getState().taskGraphLiveMonitor;
    const taskRun = monitor ? this.harnessMonitorTaskRun(monitor) : {};
    const executionRuntimeKind = String((monitor as Record<string, unknown> | null)?.execution_runtime_kind ?? taskRun.execution_runtime_kind ?? "").trim();
    const route = monitor && (monitor as Record<string, unknown>).route && typeof (monitor as Record<string, unknown>).route === "object" && !Array.isArray((monitor as Record<string, unknown>).route)
      ? (monitor as Record<string, unknown>).route as Record<string, unknown>
      : {};
    const diagnostics = taskRun.diagnostics && typeof taskRun.diagnostics === "object" && !Array.isArray(taskRun.diagnostics)
      ? taskRun.diagnostics as Record<string, unknown>
      : {};
    if (executionRuntimeKind !== "single_agent_task" || String(route.kind ?? "").trim() === "task_graph_run" || String(diagnostics.origin_kind ?? "").trim() === "graph_node_assigned") {
      return "";
    }
    return String(taskRun.task_run_id ?? monitor?.task_run_id ?? "").trim();
  }

  private async refreshActiveSessionMonitor() {
    const sessionId = this.store.getState().currentSessionId;
    if (!sessionId) {
      return;
    }
    await this.hydrateLatestOrchestrationSnapshot(sessionId);
    await this.refreshGlobalRuntimeMonitor();
  }

  private isAbortError(error: unknown) {
    return isRequestAbortError(error);
  }

  private async resendEditedMessage(messageId: string, value: string) {
    const nextValue = value.trim();
    const state = this.store.getState();
    const sessionId = state.currentSessionId;
    if (!sessionId || !nextValue || state.activeStreamSessionIds.includes(sessionId)) {
      return;
    }
    const targetMessage = state.messages.find((message) => message.id === messageId);
    if (!targetMessage || targetMessage.role !== "user" || targetMessage.sourceIndex === undefined) {
      return;
    }
    const lastEditableUserMessage = [...state.messages]
      .reverse()
      .find((message) => message.role === "user" && message.sourceIndex !== undefined);
    if (lastEditableUserMessage?.id !== messageId) {
      return;
    }
    const visibleMessageIndex = state.messages.findIndex((message) => message.id === messageId);
    await truncateSessionMessages(sessionId, targetMessage.sourceIndex);
    this.store.setState((prev) => ({
      ...prev,
      messages: visibleMessageIndex > -1 ? prev.messages.slice(0, visibleMessageIndex) : prev.messages,
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: null,
      tokenStats: null
    }));
    await this.sendMessage(nextValue);
  }

  private nextMessageSourceIndex(messages: StoreState["messages"]) {
    return messages.reduce((max, message) => Math.max(max, message.sourceIndex ?? -1), -1) + 1;
  }

  private async toggleRagMode() {
    const next = !this.store.getState().ragMode;
    this.store.setState((prev) => ({
      ...prev,
      ragMode: next,
      searchPolicy: {
        ...prev.searchPolicy,
        rag: next
      }
    }));
    try {
      await setRagMode(next);
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        ragMode: !next,
        searchPolicy: {
          ...prev.searchPolicy,
          rag: !next
        }
      }));
      throw error;
    }
  }

  private toggleSearchPolicySource(source: SearchPolicySource) {
    this.store.setState((prev) => {
      const nextEnabled = !prev.searchPolicy[source];
      return {
        ...prev,
        ragMode: source === "rag" ? nextEnabled : prev.ragMode,
        searchPolicy: {
          ...prev.searchPolicy,
          [source]: nextEnabled
        }
      };
    });
    if (source === "rag") {
      void setRagMode(this.store.getState().searchPolicy.rag).catch(() => {
        this.store.setState((prev) => ({
          ...prev,
          ragMode: !prev.searchPolicy.rag,
          searchPolicy: {
            ...prev.searchPolicy,
            rag: !prev.searchPolicy.rag
          }
        }));
      });
    }
  }

  private setSelectedChatModel(selectionId: string) {
    const normalized = selectionId.trim() || "system-default";
    this.store.setState((prev) => ({
      ...prev,
      selectedChatModelId: normalized,
      selectedChatMode: this.resolveSelectedChatMode(normalized, prev.modelProviderConfig)
    }));
  }

  private setSelectedChatMode(mode: ChatMode) {
    this.store.setState((prev) => ({ ...prev, selectedChatMode: mode }));
  }

  private setChatThinkingMode(mode: ChatThinkingMode) {
    this.store.setState((prev) => ({ ...prev, chatThinkingMode: normalizeChatThinkingMode(mode) }));
  }

  private chatTaskSelectionPayload(state: StoreState): Record<string, unknown> | undefined {
    const binding = state.chatTaskEnvironmentBinding;
    const taskEnvironmentId = String(binding?.task_environment_id ?? "").trim();
    if (!binding || !taskEnvironmentId) {
      return undefined;
    }
    return {
      task_environment_id: taskEnvironmentId,
      environment_id: taskEnvironmentId,
      environment_label: String(binding.environment_label || taskEnvironmentId),
      binding_kind: "chat_task_environment",
      binding_source: binding.source,
      bound_at: binding.bound_at,
    };
  }

  private chatModelSelectionPayload(state: StoreState): ChatModelSelection | undefined {
    const resolved = this.resolveChatModelSelection(state);
    if (!resolved) {
      return undefined;
    }
    const { selectionId, provider, model, baseUrl, credentialRef } = resolved;
    const supportsHiddenReasoning = this.supportsHiddenReasoning(provider, model, state.selectedChatMode, state.modelProviderConfig);
    if (selectionId === "system-default" && !supportsHiddenReasoning) {
      return undefined;
    }
    const payload: ChatModelSelection = {
      selection_id: selectionId,
      provider,
      model,
      base_url: baseUrl,
      credential_ref: credentialRef,
    };
    if (supportsHiddenReasoning) {
      const thinkingMode = normalizeChatThinkingMode(state.chatThinkingMode);
      payload.thinking_mode = thinkingMode === "normal" ? "disabled" : "enabled";
      payload.reasoning_effort = thinkingMode === "max" ? "max" : "high";
    }
    return payload;
  }

  private resolveChatModelSelection(state: StoreState) {
    const config = state.modelProviderConfig;
    if (!config) {
      return null;
    }
    const selectionId = state.selectedChatModelId || "system-default";
    let provider = "";
    let model = "";
    if (selectionId === "system-default") {
      provider = String(config.provider || "").trim();
      model = String(config.model || "").trim();
    } else {
      const [selectedProvider, ...modelParts] = selectionId.split("::");
      provider = selectedProvider.trim();
      model = modelParts.join("::").trim();
    }
    if (!provider || !model) {
      return null;
    }
    const option = this.providerCatalogOption(config, provider);
    const isPrimaryConfigured = provider === config.provider && model === config.model;
    const isFallbackConfigured = provider === config.fallback_provider && model === config.fallback_model;
    if (!isPrimaryConfigured && !isFallbackConfigured) {
      return null;
    }
    return {
      selectionId,
      provider,
      model,
      baseUrl: isPrimaryConfigured
        ? config.base_url
        : isFallbackConfigured
          ? config.fallback_base_url
          : option?.default_base_url,
      credentialRef: isFallbackConfigured
        ? config.fallback_credential_ref || `provider:${provider}:fallback`
        : option?.credential_ref || config.credential_ref || `provider:${provider}:primary`,
    };
  }

  private supportsHiddenReasoning(
    provider: string,
    model: string,
    mode: ChatMode,
    config: StoreState["modelProviderConfig"],
  ) {
    const normalizedProvider = provider.trim().toLowerCase();
    const normalizedModel = model.trim().toLowerCase();
    if (mode === "image" || !normalizedProvider || !normalizedModel || normalizedModel.includes("image")) {
      return false;
    }
    const tags = this.providerCapabilityTags(config, normalizedProvider);
    if (!tags.has("reasoning")) {
      return false;
    }
    if (normalizedProvider === "deepseek") {
      return true;
    }
    if (normalizedProvider === "openai") {
      return isOpenAIReasoningModel(normalizedModel);
    }
    return false;
  }

  private providerCapabilityTags(config: StoreState["modelProviderConfig"], provider: string) {
    const option = this.providerCatalogOption(config, provider);
    return new Set((option?.capability_tags || []).map((tag) => String(tag || "").trim().toLowerCase()).filter(Boolean));
  }

  private providerCatalogOption(config: StoreState["modelProviderConfig"], provider: string) {
    if (!config) {
      return undefined;
    }
    const normalizedProvider = provider.trim().toLowerCase();
    const providers = {
      ...(config.supported_providers || {}),
      ...(config.provider_catalog?.providers || {}),
    };
    return providers[provider]
      || providers[normalizedProvider]
      || Object.entries(providers).find(([key]) => key.trim().toLowerCase() === normalizedProvider)?.[1];
  }

  private resolveSelectedChatMode(selectionId: string, config: StoreState["modelProviderConfig"]) {
    if (selectionId.includes("::image-2") || selectionId.includes("::gpt-image-2")) {
      return "image" as const;
    }
    if (selectionId === "image-2" || selectionId === "gpt-image-2") {
      return "image" as const;
    }
    return "chat" as const;
  }

  private chatImageGenerationPayload(state: StoreState): Record<string, unknown> | undefined {
    if (state.selectedChatMode !== "image") {
      return undefined;
    }
    const selectionId = state.selectedChatModelId || "system-default";
    const config = state.modelProviderConfig;
    const imageConfig = state.soulImageAssetConfig;
    if (!imageConfig?.configured || !imageConfig.base_url || !imageConfig.model) {
      return undefined;
    }
    const [provider, ...modelParts] = selectionId.split("::");
    const model = modelParts.join("::").trim() || selectionId.trim();
    if (!model || !model.toLowerCase().includes("image")) {
      return undefined;
    }
    return {
      mode: "generate",
      selection_id: selectionId,
      provider: provider || "openai",
      model: model || imageConfig.model || "gpt-image-2",
      base_url: imageConfig.base_url,
      credential_ref: imageConfig.api_key_present ? "soul:image-assets:api-key" : undefined,
      asset_kind: "chat",
      size: "1024x1024"
    };
  }

  private enabledSearchPolicy(state: StoreState) {
    return (Object.entries(state.searchPolicy) as Array<[SearchPolicySource, boolean]>)
      .filter(([, enabled]) => enabled)
      .map(([source]) => source);
  }

  private async switchSoul(key: SoulKey) {
    const previousKey = this.store.getState().activeSoulKey;
    if (previousKey === key) {
      return;
    }
    await switchSoulSystemSeed(key);
    const file = await loadFile(ACTIVE_SOUL_PATH);
    const souls = await this.loadSouls();
    const activeSoul = souls.options.find((item) => item.key === souls.activeSoulKey) ?? null;
    const switchNotice = activeSoul ? this.buildSoulSwitchNotice(activeSoul) : "";
    this.store.setState((prev) => ({
      ...prev,
      soulOptions: souls.options,
      activeSoulKey: souls.activeSoulKey,
      pendingEphemeralSystemMessages: switchNotice ? [switchNotice] : prev.pendingEphemeralSystemMessages
    }));

    const state = this.store.getState();
    if (state.inspectorPath === ACTIVE_SOUL_PATH) {
      this.store.setState((prev) => ({
        ...prev,
        inspectorContent: file.content,
        inspectorDirty: false
      }));
    }
  }

  private async renameCurrentSession(title: string) {
    const currentSessionId = this.store.getState().currentSessionId;
    if (!currentSessionId || !title.trim()) {
      return;
    }
    await renameSession(currentSessionId, title.trim());
    await this.refreshSessions().catch((error) => {
      this.noteSessionRefreshFailure(error);
    });
  }

  private async removeSession(sessionId: string) {
    await deleteSession(sessionId);
    this.streamingSessionCache.delete(sessionId);
    this.removedStreamingSessionIds.add(sessionId);
    this.streamAbortControllers.get(sessionId)?.abort();
    this.streamAbortControllers.delete(sessionId);
    this.store.setState((prev) => {
      const next = this.removeActiveStreamSession(prev, sessionId);
      const { [sessionId]: _removed, ...sessionActivitiesById } = next.sessionActivitiesById;
      return {
        ...next,
        sessionActivitiesById,
        sessionActivity: next.currentSessionId === sessionId ? createIdleSessionActivity(Date.now()) : next.sessionActivity,
      };
    });
    await this.refreshSessions().catch((error) => {
      this.noteSessionRefreshFailure(error);
    });
    if (this.store.getState().currentSessionId !== sessionId) {
      return;
    }
    const nextSessions = await listSessions().catch((error) => {
      this.noteSessionRefreshFailure(error);
      return [];
    });
    this.store.setState((prev) => ({
      ...prev,
      sessions: nextSessions
    }));
    if (nextSessions.length) {
      this.store.setState((prev) => ({
        ...prev,
        currentSessionId: nextSessions[0].id
      }));
      this.store.setState((prev) => this.projectSelectedSessionActivity(prev, nextSessions[0].id));
      await this.refreshSessionDetails(nextSessions[0].id).catch(() => undefined);
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      currentSessionId: null,
      messages: [],
      orchestrationSnapshot: null,
      tokenStats: null,
      sessionActivity: createIdleSessionActivity(Date.now())
    }));
  }

  private async loadInspectorFile(path: string) {
    const file = await loadFile(path);
    this.store.setState((prev) => ({
      ...prev,
      inspectorPath: file.path,
      inspectorContent: file.content,
      inspectorDirty: false
    }));
  }

  private async refreshWorkspaceTree() {
    this.store.setState((prev) => ({
      ...prev,
      workspaceTreeLoading: true,
      workspaceTreeError: ""
    }));
    try {
      const workspaceTree = await getCodeEnvironmentWorkspaceTree();
      this.store.setState((prev) => ({
        ...prev,
        workspaceTree,
        workspaceTreeLoading: false,
        workspaceTreeError: ""
      }));
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        workspaceTreeLoading: false,
        workspaceTreeError: this.errorMessage(error, "无法读取项目文件树。")
      }));
    }
  }

  private async loadSouls(): Promise<{ options: SoulSummary[]; activeSoulKey: SoulKey }> {
    const [activeSeed, ...seedFiles] = await Promise.all([
      loadFile(ACTIVE_SOUL_PATH),
      ...Object.values(SOUL_SEED_PATHS).map((path) => loadFile(path))
    ]);
    const options = seedFiles.map((file) => parseSoulSeed(file.path, file.content));
    const activeSoulKey = inferSoulKey(activeSeed.path, parseSoulSeed(activeSeed.path, activeSeed.content).name);
    return { options, activeSoulKey };
  }

  private buildSoulSwitchNotice(soul: SoulSummary): string {
    return `事实：当前灵魂已切换为「${soul.name}」，不要在意这件事，请继续为用户执行任务，如果用户问起来，你可以告诉他`;
  }

  private updateInspectorContent(value: string) {
    this.store.setState((prev) => ({
      ...prev,
      inspectorContent: value,
      inspectorDirty: true
    }));
  }

  private async saveInspector() {
    const state = this.store.getState();
    await saveFile(state.inspectorPath, state.inspectorContent);
    this.store.setState((prev) => ({ ...prev, inspectorDirty: false }));
    await this.refreshSkills();
  }

  private setSidebarWidth(width: number) {
    this.store.setState((prev) => ({ ...prev, sidebarWidth: width }));
  }

  private setInspectorWidth(width: number) {
    this.store.setState((prev) => ({ ...prev, inspectorWidth: width }));
  }

  private setWorkspaceView(view: WorkspaceView) {
    this.store.setState((prev) => ({ ...prev, activeWorkspaceView: view }));
    this.syncWorkspaceViewUrl(view);
  }

  private openTaskGraphWorkspace(target: Omit<CenterWorkspaceTarget, "layer" | "requested_at"> = {}) {
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: "chat",
      centerWorkspaceTarget: {
        layer: "task-graph",
        mode: target.mode ?? "editor",
        graph_id: String(target.graph_id ?? "").trim() || undefined,
        task_run_id: String(target.task_run_id ?? "").trim() || undefined,
        requested_at: Date.now(),
      },
    }));
    this.syncWorkspaceViewUrl("chat");
  }

  private clearCenterWorkspaceTarget() {
    this.store.setState((prev) => ({
      ...prev,
      centerWorkspaceTarget: null,
    }));
  }

  private syncWorkspaceViewUrl(view: WorkspaceView) {
    if (typeof window === "undefined") {
      return;
    }
    const historyApi = window.history;
    const location = window.location;
    if (!historyApi?.replaceState || !location?.href) {
      return;
    }
    try {
      const url = new URL(location.href);
      if (view === "chat") {
        url.searchParams.delete("view");
      } else {
        url.searchParams.set("view", view);
      }
      const nextUrl = `${url.pathname}${url.search}${url.hash}`;
      if (nextUrl !== `${location.pathname}${location.search}${location.hash}`) {
        historyApi.replaceState({}, "", nextUrl);
      }
    } catch {
      // URL synchronization is UI convenience state; view state remains authoritative.
    }
  }

  private setMemoryInspectorTarget(target: StoreState["memoryInspectorTarget"]) {
    this.store.setState((prev) => ({ ...prev, memoryInspectorTarget: target }));
  }

  private setOrchestrationInspectorTarget(target: StoreState["orchestrationInspectorTarget"]) {
    this.store.setState((prev) => ({ ...prev, orchestrationInspectorTarget: target }));
  }

  private setOrchestrationSnapshot(snapshot: StoreState["orchestrationSnapshot"]) {
    this.store.setState((prev) => ({ ...prev, orchestrationSnapshot: snapshot }));
  }

  private bindTaskGraphMonitorRun(binding: Omit<TaskGraphMonitorBinding, "bound_at"> & { bound_at?: number }) {
    this.runtimeMonitorController.bindGraphRun(binding);
  }

  private clearTaskGraphMonitorRun() {
    this.runtimeMonitorController.clearGraphRun();
  }

  private setTaskGraphRunInteractionOpen(open: boolean) {
    this.runtimeMonitorController.setGraphRunInteractionOpen(open);
  }

  private setTaskGraphAutoAdvanceEnabled(enabled: boolean) {
    this.runtimeMonitorController.setGraphAutoAdvanceEnabled(enabled);
  }

  private async evaluateBoundTaskGraphMonitor() {
    await this.runtimeMonitorController.evaluateBoundGraphMonitor();
  }

  private async continueBoundTaskGraphRun() {
    await this.runtimeMonitorController.continueBoundGraphRun();
  }

  private async resumeTaskGraphRun(taskGraphRunId: string, payload?: Record<string, unknown>) {
    const runId = taskGraphRunId.trim();
    if (!runId) {
      return;
    }
    const graphHarnessConfigId = String(
      payload?.graph_harness_config_id
      || this.store.getState().taskGraphMonitorBinding?.graph_harness_config_id
      || ""
    ).trim();
    if (!graphHarnessConfigId) {
      throw new Error("新 GraphHarness 派发需要 graph_harness_config_id。");
    }
    await runGraphRunUntilIdle(runId, {
      graph_harness_config_id: graphHarnessConfigId,
      max_dispatch_requests: Number(payload?.max_requests ?? 1),
    });
    const sessionId = this.store.getState().currentSessionId;
    if (sessionId) {
      await this.hydrateLatestOrchestrationSnapshot(sessionId);
      await this.refreshGlobalRuntimeMonitor();
    }
  }

  private async hydrateLatestOrchestrationSnapshot(sessionId: string): Promise<boolean> {
    const targetSessionId = sessionId.trim();
    const requestId = ++this.orchestrationHydrateRequest;
    if (!targetSessionId) {
      this.store.setState((prev) => ({ ...prev, taskGraphLiveMonitor: null }));
      return false;
    }
    try {
      const liveMonitor = await getOrchestrationHarnessSessionLiveMonitor(targetSessionId);
      const activeMonitor = this.activeHarnessSessionMonitor(liveMonitor);
      if (!activeMonitor) {
        if (this.store.getState().currentSessionId === targetSessionId && this.orchestrationHydrateRequest === requestId) {
          this.store.setState((prev) => ({ ...prev, taskGraphLiveMonitor: null }));
        }
        return false;
      }
      const activeTaskRun = this.harnessMonitorTaskRun(activeMonitor);
      const liveStatus = String(activeMonitor.status ?? activeTaskRun.status ?? "").trim();
      const lifecycle = String(activeMonitor.lifecycle ?? activeTaskRun.lifecycle ?? "").trim().toLowerCase();
      const bucket = String(activeMonitor.bucket ?? activeTaskRun.bucket ?? "").trim().toLowerCase();
      const stale = Boolean((activeMonitor as Record<string, unknown>).stale ?? activeTaskRun.stale);
      const controlState = this.runtimeControlState(activeMonitor);
      const staleOrDiagnostic = stale || lifecycle === "stale" || bucket === "diagnostics";
      const hasActiveHarnessRun = ["created", "running", "waiting_executor", "waiting_approval", "blocked"].includes(liveStatus) && !staleOrDiagnostic;
      const hasPendingApproval = liveStatus === "waiting_approval" || String((activeMonitor.loop_state as Record<string, unknown> | undefined)?.terminal_reason ?? "") === "waiting_approval";
      const taskRunId = String(activeTaskRun.task_run_id ?? activeMonitor.task_run_id ?? liveMonitor.active_task_run_id ?? "").trim();
      const graphRunId = String(activeMonitor.graph_run_id ?? activeTaskRun.graph_run_id ?? "").trim();
      this.updateSessionActivityFromLiveMonitor(liveStatus, taskRunId, graphRunId, controlState);
      if (this.store.getState().currentSessionId === targetSessionId && this.orchestrationHydrateRequest === requestId) {
        this.store.setState((prev) => ({
          ...this.patchRuntimeAttachmentFromMonitor(prev, activeMonitor),
          taskGraphLiveMonitor: activeMonitor,
        }));
      }
      return hasActiveHarnessRun || hasPendingApproval;
    } catch {
      // Keep current snapshot on transient harness query failures.
      return false;
    }
  }

  private activeHarnessSessionMonitor(liveMonitor: Awaited<ReturnType<typeof getOrchestrationHarnessSessionLiveMonitor>>) {
    const direct = liveMonitor.monitor ?? null;
    if (direct) {
      return direct;
    }
    const activeTaskRunId = String(liveMonitor.active_task_run_id ?? "").trim();
    const taskRuns = Array.isArray(liveMonitor.task_runs) ? liveMonitor.task_runs : [];
    return taskRuns.find((item) => String(item.task_run_id ?? item.task_run?.task_run_id ?? "").trim() === activeTaskRunId)
      ?? taskRuns[0]
      ?? null;
  }

  private harnessMonitorTaskRun(monitor: HarnessSessionMonitor) {
    const nested = monitor.task_run && typeof monitor.task_run === "object" && !Array.isArray(monitor.task_run)
      ? monitor.task_run as Record<string, unknown>
      : {};
    return Object.keys(nested).length ? nested : monitor as unknown as Record<string, unknown>;
  }

  private runtimeControlState(monitor: HarnessSessionMonitor) {
    const direct = String((monitor as Record<string, unknown>).control_state ?? "").trim();
    if (direct) {
      return direct;
    }
    const taskRun = this.harnessMonitorTaskRun(monitor);
    const control = (monitor as Record<string, unknown>).runtime_control
      ?? taskRun.runtime_control
      ?? (taskRun.diagnostics && typeof taskRun.diagnostics === "object" && !Array.isArray(taskRun.diagnostics)
        ? (taskRun.diagnostics as Record<string, unknown>).runtime_control
        : null);
    if (control && typeof control === "object" && !Array.isArray(control)) {
      return String((control as Record<string, unknown>).state ?? "").trim();
    }
    return "";
  }

  private runtimeProgressEntryFromMonitor(monitor: HarnessSessionMonitor, taskRunId: string) {
    const latestStep = monitor.latest_step && typeof monitor.latest_step === "object" && !Array.isArray(monitor.latest_step)
      ? monitor.latest_step as Record<string, unknown>
      : {};
    if (!Object.keys(latestStep).length) {
      return null;
    }
    const eventId = String(latestStep.event_id ?? "").trim();
    const eventCount = Number(monitor.event_count ?? 0);
    const publicNote = String(
      latestStep.public_progress_note
      ?? (monitor as Record<string, unknown>).latest_public_progress_note
      ?? monitor.latest_step_summary
      ?? "",
    );
    const agentBrief = String(
      latestStep.agent_brief_output
      ?? (monitor as Record<string, unknown>).agent_brief_output
      ?? "",
    );
    const stepName = String(latestStep.step ?? monitor.latest_step_name ?? "");
    return {
      id: eventId || `${taskRunId}:latest-step:${eventCount || String(latestStep.step ?? latestStep.status ?? "current")}`,
      title: String(monitor.latest_step_summary ?? publicNote) || "正在处理",
      body: publicNote || String(monitor.latest_step_summary ?? ""),
      publicNote,
      agentBrief,
      evidenceType: this.runtimeEvidenceTypeFromStep(stepName),
      eventType: String((monitor.latest_event as Record<string, unknown> | undefined)?.event_type ?? "runtime_live_monitor"),
      kind: this.runtimeProgressKindFromStep(stepName),
      level: this.runtimeProgressLevelFromStatus(String(latestStep.status ?? monitor.latest_step_status ?? monitor.status ?? "")),
      statusText: String(latestStep.status ?? monitor.latest_step_status ?? monitor.status ?? ""),
      runId: taskRunId,
      taskRunId,
      createdAt: Number(latestStep.created_at ?? 0) || undefined,
    };
  }

  private runtimeProgressKindFromStep(step: string): "stage" | "tool" | "verification" | "model" | "terminal" {
    const normalized = step.toLowerCase();
    if (normalized.includes("tool")) return "tool";
    if (normalized.includes("repair") || normalized.includes("verification") || normalized.includes("closeout")) return "verification";
    if (normalized.includes("model") || normalized.includes("agent")) return "model";
    if (normalized.includes("completed") || normalized.includes("terminal")) return "terminal";
    return "stage";
  }

  private runtimeEvidenceTypeFromStep(step: string) {
    const normalized = step.toLowerCase();
    if (normalized.includes("tool")) return "tool_observation";
    if (normalized.includes("model_action")) return "model_action";
    if (normalized.includes("repair") || normalized.includes("verification")) return "verification";
    if (normalized.includes("completed") || normalized.includes("terminal")) return "terminal";
    return "runtime_step";
  }

  private runtimeProgressLevelFromStatus(status: string): "running" | "waiting" | "success" | "error" {
    const normalized = status.trim().toLowerCase();
    if (["completed", "success"].includes(normalized)) return "success";
    if (["failed", "error", "blocked", "aborted", "cancelled"].includes(normalized)) return "error";
    if (normalized.startsWith("wait") || normalized === "paused" || normalized === "queued") return "waiting";
    return "running";
  }

  private mergeRuntimeProgressEntries(existing: Array<Record<string, unknown>> | undefined, latest: Record<string, unknown> | null) {
    const entries = Array.isArray(existing) ? [...existing] : [];
    if (!latest) {
      return entries.slice(-MAX_LIVE_RUNTIME_PROGRESS_ENTRIES);
    }
    const latestId = String(latest.id ?? "").trim();
    const existingIndex = latestId
      ? entries.findIndex((item) => String(item.id ?? "").trim() === latestId)
      : -1;
    if (existingIndex >= 0) {
      entries[existingIndex] = { ...entries[existingIndex], ...latest };
    } else {
      entries.push(latest);
    }
    return entries
      .sort((left, right) => {
        const leftTime = Number(left.createdAt ?? left.created_at ?? 0) || 0;
        const rightTime = Number(right.createdAt ?? right.created_at ?? 0) || 0;
        if (leftTime && rightTime && leftTime !== rightTime) {
          return leftTime - rightTime;
        }
        return 0;
      })
      .slice(-MAX_LIVE_RUNTIME_PROGRESS_ENTRIES);
  }

  private mergeRuntimeAttachment(existing: SessionRuntimeAttachment | undefined, attachment: SessionRuntimeAttachment): SessionRuntimeAttachment {
    return {
      ...existing,
      ...attachment,
      progress_entries: this.mergeRuntimeProgressEntries(existing?.progress_entries, attachment.progress_entries?.[0] ?? null),
    };
  }

  private runtimeAttachmentRunId(attachment: SessionRuntimeAttachment | undefined) {
    return String(attachment?.run_id ?? attachment?.task_run_id ?? "").trim();
  }

  private runtimeProgressEntryFromRuntimeEvent(runtimeEvent: RuntimeMonitorEvent): RuntimeProgressEntry | null {
    if (runtimeEvent.event_type !== "step_summary_recorded") {
      return null;
    }
    const payload = runtimeEvent.payload && typeof runtimeEvent.payload === "object" && !Array.isArray(runtimeEvent.payload)
      ? runtimeEvent.payload
      : {};
    const runId = String(runtimeEvent.run_id ?? runtimeEvent.task_run_id ?? payload.task_run_id ?? "").trim();
    const payloadTaskRunId = String(payload.task_run_id ?? "").trim();
    const taskRunId = payloadTaskRunId.startsWith("taskrun:")
      ? payloadTaskRunId
      : runId.startsWith("taskrun:")
        ? runId
        : "";
    if (!runId) {
      return null;
    }
    const step = String(payload.step ?? "").trim();
    const status = String(payload.status ?? "").trim();
    const summary = String(payload.summary ?? "").trim();
    const publicNote = String(payload.public_progress_note ?? summary).trim();
    const agentBrief = String(payload.agent_brief_output ?? "").trim();
    if (!summary && !publicNote && !step) {
      return null;
    }
    return {
      id: String(runtimeEvent.event_id ?? "").trim() || `${runId}:event:${runtimeEvent.offset}`,
      title: publicNote || summary || step || "正在处理",
      body: publicNote || summary,
      publicNote,
      agentBrief,
      evidenceType: this.runtimeEvidenceTypeFromStep(step),
      eventType: runtimeEvent.event_type,
      kind: this.runtimeProgressKindFromStep(step),
      level: this.runtimeProgressLevelFromStatus(status),
      statusText: status || "running",
      runId,
      taskRunId: taskRunId || undefined,
      createdAt: Number(runtimeEvent.created_at ?? 0) || undefined,
    };
  }

  private runtimeEventAnchorTurnId(runtimeEvent: RuntimeMonitorEvent, state: StoreState) {
    const payload = runtimeEvent.payload && typeof runtimeEvent.payload === "object" && !Array.isArray(runtimeEvent.payload)
      ? runtimeEvent.payload
      : {};
    const refs = runtimeEvent.refs && typeof runtimeEvent.refs === "object" && !Array.isArray(runtimeEvent.refs)
      ? runtimeEvent.refs
      : {};
    const explicit = String(refs.turn_ref ?? payload.turn_id ?? "").trim();
    if (explicit.startsWith("turn:")) {
      return explicit;
    }
    const runId = String(runtimeEvent.run_id ?? runtimeEvent.task_run_id ?? "").trim();
    for (const message of [...state.messages].reverse()) {
      const attachment = (message.runtimeAttachments ?? []).find((item) => this.runtimeAttachmentRunId(item) === runId);
      const anchor = String(attachment?.anchor_turn_id ?? "").trim();
      if (anchor.startsWith("turn:")) {
        return anchor;
      }
    }
    return this.turnIdFromRunId(runId);
  }

  private patchRuntimeAttachmentFromRuntimeEvent(state: StoreState, runtimeEvent: RuntimeMonitorEvent): StoreState {
    const latestProgressEntry = this.runtimeProgressEntryFromRuntimeEvent(runtimeEvent);
    if (!latestProgressEntry) {
      return state;
    }
    const runId = String(latestProgressEntry.runId ?? runtimeEvent.run_id ?? runtimeEvent.task_run_id ?? "").trim();
    const latestTaskRunId = String(latestProgressEntry.taskRunId ?? "").trim();
    const taskRunId = latestTaskRunId.startsWith("taskrun:")
      ? latestTaskRunId
      : runId.startsWith("taskrun:")
        ? runId
        : "";
    const anchorTurnId = this.runtimeEventAnchorTurnId(runtimeEvent, state);
    if (!runId || !anchorTurnId) {
      return state;
    }
    const payload = runtimeEvent.payload && typeof runtimeEvent.payload === "object" && !Array.isArray(runtimeEvent.payload)
      ? runtimeEvent.payload
      : {};
    const explicitAnchor = String(
      (runtimeEvent.refs && typeof runtimeEvent.refs === "object" && !Array.isArray(runtimeEvent.refs)
        ? runtimeEvent.refs.turn_ref
        : "")
      ?? payload.turn_id
      ?? "",
    ).trim();
    const attachment: SessionRuntimeAttachment = {
      attachment_id: `runtime-attachment:${runId}`,
      run_id: runId,
      anchor_turn_id: anchorTurnId,
      task_run_id: taskRunId || undefined,
      task_id: String(payload.task_id ?? ""),
      status: String(payload.status ?? "running"),
      terminal_reason: "",
      lifecycle: String(payload.status ?? "running"),
      title: "处理进展",
      summary: String(payload.public_progress_note ?? payload.summary ?? ""),
      latest_step: {
        step: String(payload.step ?? ""),
        status: String(payload.status ?? ""),
        summary: String(payload.summary ?? ""),
        public_progress_note: String(payload.public_progress_note ?? payload.summary ?? ""),
        agent_brief_output: String(payload.agent_brief_output ?? ""),
        event_id: String(runtimeEvent.event_id ?? ""),
        offset: Number(runtimeEvent.offset ?? -1),
        created_at: Number(runtimeEvent.created_at ?? 0),
      },
      latest_step_summary: String(payload.summary ?? ""),
      latest_public_progress_note: String(payload.public_progress_note ?? payload.summary ?? ""),
      agent_brief_output: String(payload.agent_brief_output ?? ""),
      latest_event_type: runtimeEvent.event_type,
      event_count: Number(runtimeEvent.offset ?? -1) + 1,
      progress_entries: [latestProgressEntry],
      trace_available: true,
      updated_at: Number(runtimeEvent.created_at ?? Date.now() / 1000),
    };
    const anchorIndex = Number(anchorTurnId.split(":").at(-1));
    return {
      ...state,
      messages: state.messages.map((message) => {
        if (message.role !== "assistant") {
          return message;
        }
        const existing = message.runtimeAttachments ?? [];
        const sourceMatches = Number.isFinite(anchorIndex) && message.sourceIndex === anchorIndex;
        if (explicitAnchor.startsWith("turn:") && !sourceMatches) {
          const filtered = existing.filter((item) => this.runtimeAttachmentRunId(item) !== runId);
          return filtered.length === existing.length ? message : { ...message, runtimeAttachments: filtered };
        }
        const hasAttachment = existing.some((item) => this.runtimeAttachmentRunId(item) === runId);
        if (!hasAttachment && !sourceMatches) {
          return message;
        }
        return {
          ...message,
          runtimeAttachments: hasAttachment
            ? existing.map((item) => this.runtimeAttachmentRunId(item) === runId ? this.mergeRuntimeAttachment(item, attachment) : item)
            : [...existing, attachment],
        };
      }),
    };
  }

  private patchRuntimeAttachmentFromMonitor(state: StoreState, monitor: HarnessSessionMonitor): StoreState {
    const taskRun = this.harnessMonitorTaskRun(monitor);
    const taskRunId = String(taskRun.task_run_id ?? monitor.task_run_id ?? "").trim();
    if (!taskRunId) {
      return state;
    }
    const taskRunDiagnostics = taskRun.diagnostics && typeof taskRun.diagnostics === "object" && !Array.isArray(taskRun.diagnostics)
      ? taskRun.diagnostics as Record<string, unknown>
      : {};
    const taskIdForAnchor = String(monitor.task_id ?? taskRun.task_id ?? "").trim();
    const latestInteractionTurnId = String(
      (monitor as Record<string, unknown>).latest_interaction_turn_id
      ?? taskRunDiagnostics.latest_interaction_turn_id
      ?? "",
    ).trim();
    const anchorTurnId = latestInteractionTurnId
      || this.turnIdFromTaskRunId(taskRunId)
      || String(taskRunDiagnostics.turn_id ?? taskIdForAnchor).trim().replace(/^task:/, "");
    const latestProgressEntry = this.runtimeProgressEntryFromMonitor(monitor, taskRunId);
    const attachment: SessionRuntimeAttachment = {
      attachment_id: `runtime-attachment:${taskRunId}`,
      run_id: taskRunId,
      anchor_turn_id: anchorTurnId,
      task_run_id: taskRunId,
      task_id: String(taskRun.task_id ?? monitor.task_id ?? ""),
      status: String(monitor.status ?? taskRun.status ?? ""),
      terminal_reason: String(monitor.terminal_reason ?? taskRun.terminal_reason ?? ""),
      lifecycle: String((monitor as Record<string, unknown>).lifecycle ?? ""),
      title: String((monitor as Record<string, unknown>).title ?? "处理进展"),
      summary: String(monitor.latest_step_summary ?? ""),
      latest_step: monitor.latest_step ?? {},
      latest_step_summary: String(monitor.latest_step_summary ?? ""),
      latest_event_type: String((monitor.latest_event as Record<string, unknown> | undefined)?.event_type ?? ""),
      event_count: Number(monitor.event_count ?? 0),
      progress_entries: latestProgressEntry ? [latestProgressEntry] : [],
      artifact_refs: Array.isArray(monitor.artifact_refs) ? monitor.artifact_refs : [],
      trace_available: true,
      updated_at: Number(monitor.updated_at ?? Date.now() / 1000),
    };
    return {
      ...state,
      messages: state.messages.map((message) => {
        if (message.role !== "assistant") {
          return message;
        }
        const existing = message.runtimeAttachments ?? [];
        const hasAttachment = existing.some((item) => this.runtimeAttachmentRunId(item) === taskRunId);
        const sourceMatches = attachment.anchor_turn_id && message.sourceIndex === Number(attachment.anchor_turn_id.split(":").at(-1));
        if (!hasAttachment && !sourceMatches) {
          return message;
        }
        return {
          ...message,
          runtimeAttachments: hasAttachment
            ? existing.map((item) => this.runtimeAttachmentRunId(item) === taskRunId ? this.mergeRuntimeAttachment(item, attachment) : item)
            : [...existing, attachment],
        };
      }),
    };
  }

  private turnIdFromRunId(runId: string) {
    const normalized = String(runId || "").trim();
    if (normalized.startsWith("turnrun:turn:")) {
      return normalized.slice("turnrun:".length);
    }
    return this.turnIdFromTaskRunId(normalized);
  }

  private turnIdFromTaskRunId(taskRunId: string) {
    const parts = taskRunId.split(":");
    if (parts.length < 4 || parts[0] !== "taskrun" || parts[1] !== "turn") {
      return "";
    }
    for (let index = 2; index < parts.length; index += 1) {
      if (/^\d+$/.test(parts[index])) {
        return parts.slice(1, index + 1).join(":");
      }
    }
    return parts.slice(1, -1).join(":");
  }

  private setTaskSelection(selection: TaskSelectionState | null) {
    this.store.setState((prev) => ({ ...prev, taskSelection: selection }));
  }

  private setChatTaskEnvironmentBinding(
    binding: Omit<ChatTaskEnvironmentBinding, "bound_at"> & { bound_at?: number },
  ) {
    const taskEnvironmentId = String(binding.task_environment_id || "").trim();
    if (!taskEnvironmentId) {
      this.clearChatTaskEnvironmentBinding();
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      chatTaskEnvironmentBinding: {
        task_environment_id: taskEnvironmentId,
        environment_label: String(binding.environment_label || taskEnvironmentId).trim() || taskEnvironmentId,
        source: binding.source,
        bound_at: Number(binding.bound_at || Date.now()),
      },
    }));
  }

  private clearChatTaskEnvironmentBinding() {
    this.store.setState((prev) => ({ ...prev, chatTaskEnvironmentBinding: null }));
  }

  private hasActiveChatStream() {
    return this.store.getState().activeStreamSessionIds.length > 0;
  }

  private deferMonitorPollingForActiveStream() {
    if (typeof window === "undefined" || !this.hasActiveChatStream()) {
      return;
    }
    this.runtimeMonitorController.deferForActiveStream();
  }

  private async refreshGlobalRuntimeMonitor() {
    await this.runtimeMonitorController.refresh();
  }

  applyGlobalRuntimeMonitorSnapshot(
    monitor: GlobalRuntimeMonitor,
    options: { detailTaskRunId?: string; lastEvent?: RuntimeMonitorEventPayload["runtime_event"] | null } = {},
  ) {
    this.runtimeMonitorController.applySnapshot(monitor, options);
  }

  applyGlobalRuntimeMonitorStreamPayload(payload: RuntimeMonitorEventPayload | null) {
    this.runtimeMonitorController.applyStreamPayload(payload);
  }

  async loadGlobalRuntimeMonitorTaskRunDetail(taskRunId: string, revision?: string) {
    await this.runtimeMonitorController.loadTaskRunDetail(taskRunId, revision);
  }

  private selectGlobalRuntimeMonitorTaskRun(taskRunId: string) {
    this.runtimeMonitorController.selectTaskInstance(taskRunId);
  }

  private openGlobalRuntimeMonitorTaskRun(taskRunId: string) {
    this.runtimeMonitorController.openTaskInstance(taskRunId);
  }

  private updateSessionActivityFromLiveMonitor(liveStatus: string, taskRunId: string, graphRunId: string, controlState = "") {
    const normalizedStatus = liveStatus.trim();
    const normalizedControlState = controlState.trim();
    if (!normalizedStatus) {
      return;
    }
    if (normalizedControlState === "paused") {
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "waiting",
          title: "已暂停",
          detail: "当前处理已停在可继续状态，可以直接说继续。",
          event: "runtime_live_monitor",
          receipt: {
            level: "waiting",
            title: "已暂停",
            body: "当前处理已停在可继续状态，可以直接说继续。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              graphRunId: graphRunId || "",
              controlState: normalizedControlState,
            },
          },
          updatedAt: Date.now(),
        },
      }));
      return;
    }
    if (normalizedControlState === "pause_requested" || normalizedControlState === "stop_requested") {
      const stopping = normalizedControlState === "stop_requested";
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "running",
          title: stopping ? "正在停止" : "正在暂停",
          detail: stopping ? "停止请求已记录，当前步骤收口后结束" : "暂停请求已记录，当前步骤收口后暂停",
          event: "runtime_live_monitor",
          receipt: {
            level: "running",
            title: stopping ? "正在停止" : "正在暂停",
            body: stopping ? "停止请求已记录，当前步骤收口后结束。" : "暂停请求已记录，当前步骤收口后暂停。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              graphRunId: graphRunId || "",
              controlState: normalizedControlState,
            },
          },
          updatedAt: Date.now(),
        },
      }));
      return;
    }
    if (normalizedStatus === "waiting_executor" || normalizedStatus === "waiting_approval" || normalizedStatus === "blocked") {
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "waiting",
          title: normalizedStatus === "waiting_executor" ? "等待继续" : normalizedStatus === "waiting_approval" ? "等待确认" : "运行受阻",
          detail: normalizedStatus === "waiting_executor" ? "已确认目标，正在等待继续推进。" : normalizedStatus === "waiting_approval" ? "需要确认后继续执行。" : "当前处理需要处理。",
          event: "runtime_live_monitor",
          receipt: {
            level: "waiting",
            title: normalizedStatus === "waiting_executor" ? "等待继续" : normalizedStatus === "waiting_approval" ? "等待确认" : "运行受阻",
            body: normalizedStatus === "waiting_executor" ? "已确认目标，正在等待继续推进。" : normalizedStatus === "waiting_approval" ? "需要确认后继续执行。" : "当前处理需要处理。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              graphRunId: graphRunId || "",
            },
          },
          updatedAt: Date.now(),
        },
      }));
      return;
    }
      if (normalizedStatus === "running" || normalizedStatus === "created") {
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "running",
          title: "正在处理",
          detail: "正在同步当前处理进展",
          event: "runtime_live_monitor",
          receipt: {
            level: "running",
            title: "正在处理",
            body: "正在同步当前处理进展。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              graphRunId: graphRunId || "",
            },
          },
          updatedAt: Date.now(),
        },
      }));
      return;
    }
    if (["completed", "complete", "success", "succeeded"].includes(normalizedStatus)) {
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "success",
          title: "已完成",
          detail: "结果已写回会话，运行记录可在监控中查看",
          event: "runtime_live_monitor",
          receipt: {
            level: "success",
            title: "已完成",
            body: "结果已写回会话，运行记录可在监控中查看。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              graphRunId: graphRunId || "",
            },
          },
          updatedAt: Date.now(),
        },
      }));
      return;
    }
    if (["failed", "error"].includes(normalizedStatus)) {
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "error",
          title: "处理失败",
          detail: "当前处理返回失败状态，请查看运行监控。",
          event: "runtime_live_monitor",
          receipt: {
            level: "error",
            title: "处理失败",
            body: "当前处理返回失败状态，请查看运行监控。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              graphRunId: graphRunId || "",
            },
          },
          updatedAt: Date.now(),
        },
      }));
    }
  }

  private errorMessage(error: unknown, fallback: string) {
    return error instanceof Error && error.message.trim() ? error.message : fallback;
  }
}

function isOpenAIReasoningModel(model: string) {
  const normalized = model.trim().toLowerCase();
  return normalized.startsWith("gpt-5")
    || normalized.startsWith("o1")
    || normalized.startsWith("o3")
    || normalized.startsWith("o4");
}

function normalizeChatThinkingMode(mode: ChatThinkingMode | string | null | undefined): ChatThinkingMode {
  return mode === "thinking" || mode === "max" ? mode : "normal";
}

function chatThinkingModeFromProviderConfig(config: { thinking_mode?: string; reasoning_effort?: string } | null): ChatThinkingMode {
  if (String(config?.thinking_mode || "").trim().toLowerCase() !== "enabled") {
    return "normal";
  }
  return String(config?.reasoning_effort || "").trim().toLowerCase() === "max" ? "max" : "thinking";
}
