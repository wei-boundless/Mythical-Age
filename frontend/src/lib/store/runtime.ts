"use client";

import {
  submitGraphRunUntilIdle,
  loadFile,
  loadFileForSession,
  createSession,
  deleteSession,
  deriveSessionTitleFromSummary,
  getChatRun,
  getLatestChatRunForSession,
  getCodeEnvironmentWorkspaceTree,
  getModelProviderConfig,
  getImageAssetConfig,
  getTaskEnvironmentCatalog,
  getWorkspaceContext,
  getOrchestrationHarnessSessionLiveMonitor,
  approveOrchestrationHarnessTaskRunToolCall,
  pauseOrchestrationHarnessTaskRun,
  pauseGraphRun,
  getPermissionMode,
  resumeOrchestrationHarnessTaskRun,
  resumeGraphRun,
  setPermissionMode as setRuntimePermissionMode,
  setSessionActiveTaskEnvironment,
  setSessionPermissionMode,
  setWorkbenchCurrentSession,
  getSessionHistory,
  getSessionRuntimeProjection,
  getSessionSummary,
  getSessionTokens,
  getWorkbenchCurrentSession,
  getProjectWorkspaceTree,
  listProjectWorkspaces,
  listProjectWorkspaceSessions,
  listSessions,
  listSkills,
  renameSession,
  removeProjectWorkspace,
  saveFile,
  saveFileForSession,
  createProjectWorkspaceSession,
  selectProjectWorkspaceDirectory,
  stopOrchestrationHarnessTaskRun,
  clearChatStreamCursor,
  clearWorkbenchCurrentSession,
  readChatStreamCursor,
  streamChat,
  streamExistingChatRun,
  truncateSessionMessages,
  uploadChatAttachment
} from "@/lib/api";
import type { ChatAttachment, ChatRun, ChatStreamCursor, PublicProjectionFrame, RunMonitorEventPayload, RuntimeMonitorActionPayload, RuntimeMonitorActionResult, RuntimeMonitorEnvelope, RuntimeMonitorSignal, SessionRuntimeAttachment, SessionScope, SessionSummary } from "@/lib/api";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";

import { createIdleSessionActivity, type Store } from "./core";
import { reduceStreamEvent, startQueuedActiveTurn, startStreamingTurn, type StreamSession } from "./events";
import { projectionFrameFromRecord } from "@/lib/projection/reducer";
import { RunMonitorController } from "../run-monitor/controller";
import { allRunMonitorSignals } from "../run-monitor/reducer";
import { chatThinkingModeFromProviderConfig, isOpenAIReasoningModel, normalizeChatThinkingMode } from "./runtime/chatThinking";
import {
  ACTIVE_TURN_STATES,
  CODE_TASK_ENVIRONMENT_IDS,
  CODING_TASK_ENVIRONMENT_ID,
  DEFAULT_INSPECTOR_PATH,
  DEFAULT_PERMISSION_MODE,
  FRONTEND_EDITOR_CONTEXT_TEXT_LIMIT,
  GENERAL_TASK_ENVIRONMENT_ID,
  GRAPH_ONLY_TASK_ENVIRONMENT_IDS,
  LAST_ACTIVE_TASK_ENVIRONMENT_KEY,
  MAIN_CHAT_POOL_KEY,
  MAX_LIVE_RUNTIME_PROGRESS_ENTRIES,
  SESSION_RUNTIME_PROJECTION_DELAY_MS,
  SESSION_TOKEN_STATS_DELAY_MS,
  TOKEN_STATS_MONITOR_REFRESH_INTERVAL_MS,
  VISIBLE_STREAM_BODY_FLUSH_DELAY_MS,
} from "./runtime/constants";
import { hydrateSessionRuntimeProjection, recoveredChatRunActivityDetail } from "./runtime/projectionHydration";
import {
  isVisibleMainChatSession,
  mergeProjectWorkspaces,
  mergeSessionSummaries,
  sessionBelongsToProject,
  sessionPoolKeyForScope,
  sessionProjectRoot,
  unboundMainChatSessions,
  visibleMainChatSessions,
} from "./runtime/sessionModels";
import {
  clearRememberedSessionRef,
  isProjectDirectorySelectionCancelled,
  readRememberedChatStreamDisplayEnabled,
  readRememberedSessionRef,
  rememberChatStreamDisplayEnabled,
  rememberSessionRef,
  sessionRefFromStoredValue,
  shouldClearRememberedSessionAfterError,
  storageGet,
  storageRemove,
  storageSet,
} from "./runtime/sessionMemory";
import { streamEventStopsActiveWork } from "./runtime/streamEvents";
import { isCatalogEnvironmentVisible, taskEnvironmentIdOf, taskEnvironmentLabelOf } from "./runtime/taskEnvironmentCatalog";
import { errorDetailMessage, runtimeText } from "./runtime/text";
import type { ActiveTurnSnapshot, ActiveTurnState, ChatMode, ChatModelSelection, ChatTaskEnvironmentBinding, ChatThinkingMode, Message, PermissionMode, RuntimeLogCenterWorkspaceTarget, RuntimeProgressEntry, SessionEditorContext, SessionEditorPageStatePatch, SessionRef, StoreActions, StoreState, TaskEnvironmentWorkspaceView, TaskGraphMonitorBinding, TaskGraphWorkspaceTarget, TaskSelectionState, WorkspaceView } from "./types";
import { makeId, toUiMessages } from "./utils";

type HarnessSessionMonitor = NonNullable<Awaited<ReturnType<typeof getOrchestrationHarnessSessionLiveMonitor>>["monitor"]>;
type ActiveChatStreamBinding = {
  streamRunId: string;
  taskRunId: string;
  turnId: string;
};

type QueuedUserInput = {
  content: string;
  messageId: string;
  inputPolicy?: "auto" | "steer";
  expectedActiveTurnId?: string;
  taskRunId?: string;
};

type VisibleStreamStateOptions = {
  preserveTaskGraphLiveMonitor?: boolean;
};

type PendingVisibleStreamFlush = {
  streamState: StoreState;
  activeStreamSessionIds: string[];
  options: VisibleStreamStateOptions;
  timer: number | ReturnType<typeof setTimeout> | null;
  frame: number | null;
};

const DEFAULT_SESSION_TITLE = "New Session";

export class WorkspaceRuntime {
  private initializePromise: Promise<void> | null = null;
  private createSessionPromise: Promise<string> | null = null;
  private sessionDetailsRequest = 0;
  private sessionRuntimeProjectionRequest = 0;
  private sessionRuntimeProjectionTimer: ReturnType<typeof setTimeout> | null = null;
  private sessionTokenStatsTimer: ReturnType<typeof setTimeout> | null = null;
  private orchestrationHydrateRequest = 0;
  private workspaceTreeRequest = 0;
  private workspaceTreeInFlightKey = "";
  private workspaceTreeInFlightPromise: Promise<void> | null = null;
  private runMonitorController: RunMonitorController;
  private sessionRefreshTimers: number[] = [];
  private sessionListFailureNotifiedAt = 0;
  private tokenStatsRefreshInFlight = false;
  private lastMonitorTokenStatsRefreshAt = 0;
  private streamingSessionCache = new Map<string, Pick<StoreState, "messages" | "activeProjectionsByKey" | "orchestrationSnapshot" | "activeTurnSnapshot">>();
  private activeChatStreamBindings = new Map<string, ActiveChatStreamBinding>();
  private chatStreamEpochBySession = new Map<string, number>();
  private removedStreamingSessionIds = new Set<string>();
  private streamAbortControllers = new Map<string, AbortController>();
  private stoppedStreamingSessionIds = new Set<string>();
  private recoveringStreamSessionIds = new Set<string>();
  private activeTaskSteerStreamSessionIds = new Set<string>();
  private pendingVisibleStreamFlushes = new Map<string, PendingVisibleStreamFlush>();
  private queuedUserInputsBySession = new Map<string, QueuedUserInput[]>();
  private flushingQueuedUserInputs = new Set<string>();
  private pendingProjectionCommitHydrates = new Map<string, string>();
  private hydratedProjectionCommitKeys = new Set<string>();
  private summaryTitleRequests = new Set<string>();

  readonly actions: StoreActions;

  constructor(private readonly store: Store<StoreState>) {
    const rememberedChatStreamDisplayEnabled = readRememberedChatStreamDisplayEnabled();
    if (rememberedChatStreamDisplayEnabled !== null) {
      this.store.setState((prev) => ({
        ...prev,
        chatStreamDisplayEnabled: rememberedChatStreamDisplayEnabled,
      }));
    }
    this.runMonitorController = new RunMonitorController(this.store, {
      applySelectedSessionShell: (sessionId, scope) => this.applySelectedSessionShell(sessionId, scope ? { scope, poolKey: sessionPoolKeyForScope(scope) } : undefined),
      bindTaskEnvironmentContext: (taskEnvironmentId, options) => this.bindTaskEnvironmentContext(taskEnvironmentId, options),
      workspaceViewForTaskEnvironment: (taskEnvironmentId) => this.workspaceViewForTaskEnvironment(taskEnvironmentId),
      refreshSessionDetails: (sessionId) => this.refreshSessionDetails(sessionId),
      hydrateLatestOrchestrationSnapshot: (sessionId) => this.hydrateLatestOrchestrationSnapshot(sessionId),
      syncWorkspaceViewUrl: (view) => this.syncWorkspaceViewUrl(view),
    });
    this.actions = {
      setWorkspaceView: (view) => {
        this.setWorkspaceView(view);
      },
      setTaskEnvironmentWorkspaceView: (view) => {
        this.setTaskEnvironmentWorkspaceView(view);
      },
      refreshTaskEnvironmentCatalog: async () => {
        await this.refreshTaskEnvironmentCatalog();
      },
      setActiveTaskEnvironment: async (environmentId, options) => {
        await this.setActiveTaskEnvironment(environmentId, options);
      },
      refreshWorkspaceTree: async () => {
        await this.refreshWorkspaceTree();
      },
      selectProjectWorkspace: async (projectKey) => {
        await this.selectProjectWorkspace(projectKey);
      },
      selectProjectWorkspaceDirectory: async () => {
        await this.selectProjectWorkspaceDirectory();
      },
      removeProjectWorkspace: async (projectKey) => {
        await this.removeProjectWorkspace(projectKey);
      },
      refreshProjectWorkspaces: async () => {
        await this.refreshProjectWorkspaces();
      },
      refreshProjectSessions: async () => {
        await this.refreshProjectSessions();
      },
      createNewSession: async () => {
        await this.createNewSession();
      },
      selectSession: async (ref) => {
        await this.selectSession(ref);
      },
      sendMessage: async (value, options) => {
        await this.sendMessage(value, options);
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
      setPermissionMode: async (mode) => {
        await this.setPermissionMode(mode);
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
      setChatStreamDisplayEnabled: (enabled) => {
        this.setChatStreamDisplayEnabled(enabled);
      },
      renameCurrentSession: async (title) => {
        await this.renameCurrentSession(title);
      },
      removeSession: async (ref) => {
        await this.removeSession(ref);
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
      setSessionEditorPageState: (patch) => {
        this.setSessionEditorPageState(patch);
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
      pauseBoundTaskGraphRun: async () => {
        await this.pauseBoundTaskGraphRun();
      },
      continueBoundTaskGraphRun: async () => {
        await this.continueBoundTaskGraphRun();
      },
      stopBoundTaskGraphRun: async () => {
        await this.stopBoundTaskGraphRun();
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
      openRunMonitorSignal: (signalId) => {
        this.openRunMonitorSignal(signalId);
      },
      refreshRunMonitor: async () => {
        await this.refreshRunMonitor();
      },
      runMonitorAction: async (payload) => {
        return await this.runMonitorAction(payload);
      },
      openTaskGraphWorkspace: (target) => {
        this.openTaskGraphWorkspace(target);
      },
      openWorkspaceFile: (path) => {
        this.openWorkspaceFile(path);
      },
      openRuntimeLog: (target) => {
        this.openRuntimeLog(target);
      },
      clearTaskGraphWorkspaceTarget: () => {
        this.clearTaskGraphWorkspaceTarget();
      },
      clearCenterWorkspaceTarget: () => {
        this.clearCenterWorkspaceTarget();
      }
    };
  }

  startRunMonitor() {
    this.runMonitorController.start();
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
      void this.refreshTaskEnvironmentCatalog().catch(() => undefined);
      let restoredCurrentSession = false;
      let preferLatestVisibleSession = false;
      const rememberedSessionRef = readRememberedSessionRef();
      if (rememberedSessionRef?.sessionId) {
        const restored = await this.restoreRememberedSessionOnStartup(rememberedSessionRef);
        restoredCurrentSession = restored === "restored";
        preferLatestVisibleSession = restored === "non_main";
      } else {
        const persistedSessionRef = await this.readPersistedCurrentSessionRef();
        if (persistedSessionRef?.sessionId) {
          const restored = await this.restoreRememberedSessionOnStartup(persistedSessionRef);
          restoredCurrentSession = restored === "restored";
          preferLatestVisibleSession = restored === "non_main";
        }
      }
      if (!restoredCurrentSession) {
        await this.initializeFromSessionList(undefined, { preferLatestVisibleSession });
      }
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

  private async readPersistedCurrentSessionRef() {
    try {
      const payload = await getWorkbenchCurrentSession();
      return sessionRefFromStoredValue(payload.current_session);
    } catch (error) {
      console.debug("[workspace-runtime] persisted current session read skipped", {
        event: "workbench_current_session_read_failed",
        error: this.errorMessage(error, "当前会话指针读取失败。"),
      });
      return null;
    }
  }

  private persistCurrentSessionRef(ref: SessionRef) {
    const normalized = this.normalizeSessionRef(ref, this.store.getState());
    if (!normalized.sessionId) {
      return;
    }
    void setWorkbenchCurrentSession({
      sessionId: normalized.sessionId,
      scope: normalized.scope,
      poolKey: normalized.poolKey,
    }).catch((error) => {
      console.debug("[workspace-runtime] persisted current session write skipped", {
        event: "workbench_current_session_write_failed",
        sessionId: normalized.sessionId,
        error: this.errorMessage(error, "当前会话指针写入失败。"),
      });
    });
  }

  private clearPersistedCurrentSessionRef(sessionId?: string) {
    void clearWorkbenchCurrentSession(sessionId).catch((error) => {
      console.debug("[workspace-runtime] persisted current session clear skipped", {
        event: "workbench_current_session_clear_failed",
        sessionId: sessionId || "",
        error: this.errorMessage(error, "当前会话指针清理失败。"),
      });
    });
  }

  private async restoreRememberedSessionOnStartup(ref: SessionRef) {
    const normalized = this.normalizeSessionRef(ref, this.store.getState());
    if (!normalized.sessionId) {
      clearRememberedSessionRef();
      return false;
    }

    let summary: SessionSummary;
    try {
      summary = await getSessionSummary(normalized.sessionId, normalized.scope);
    } catch (error) {
      if (shouldClearRememberedSessionAfterError(error)) {
        clearRememberedSessionRef(normalized.sessionId);
        this.clearPersistedCurrentSessionRef(normalized.sessionId);
        return "invalid";
      }
      return "failed";
    }

    const restoredPoolKey = normalized.poolKey ?? sessionPoolKeyForScope(summary.scope);
    if (restoredPoolKey === MAIN_CHAT_POOL_KEY && !isVisibleMainChatSession(summary)) {
      clearRememberedSessionRef(normalized.sessionId);
      this.clearPersistedCurrentSessionRef(normalized.sessionId);
      return "non_main";
    }

    const restoredScope = summary.scope ?? normalized.scope;
    const restoredRef: SessionRef = {
      sessionId: summary.id,
      ...(restoredScope ? { scope: restoredScope } : {}),
      poolKey: normalized.poolKey ?? sessionPoolKeyForScope(restoredScope),
    };
    this.store.setState((prev) => ({
      ...prev,
      sessions: mergeSessionSummaries(prev.sessions, [summary]),
    }));

    const restoredFromStreamCache = this.applySelectedSessionShell(summary.id, restoredRef);
    if (!restoredFromStreamCache) {
      const reattached = await this.reattachChatRunForSession(summary.id);
      if (!reattached) {
        void this.refreshSessionDetails(summary.id).catch(() => undefined);
        void this.hydrateLatestOrchestrationSnapshot(summary.id).catch(() => undefined);
      }
    }
    this.store.setState((prev) => ({
      ...prev,
      workspaceInitializing: false,
    }));
    if (sessionProjectRoot(summary)) {
      void this.hydrateProjectWorkspaceForRestoredSession(summary).catch((error) => {
        this.noteSessionRefreshFailure(error);
      });
    } else {
      this.refreshRestoredSessionIndexesInBackground(summary);
    }
    return "restored";
  }

  private async hydrateProjectWorkspaceForRestoredSession(summary: SessionSummary) {
    if (!sessionProjectRoot(summary)) {
      return;
    }
    const { projects, activeProject } = await this.resolveProjectWorkspaceForSession(summary);
    if (this.store.getState().currentSessionId !== summary.id) {
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      projectWorkspaces: mergeProjectWorkspaces(prev.projectWorkspaces, projects),
    }));
    if (!activeProject) {
      return;
    }
    await this.selectProjectWorkspace(activeProject.key, {
      preferredSessionId: summary.id,
      fallbackSession: summary,
    });
  }

  private refreshRestoredSessionIndexesInBackground(restoredSession: SessionSummary) {
    void this.refreshRestoredSessionIndexes(restoredSession).catch((error) => {
      this.noteSessionRefreshFailure(error);
    });
  }

  private async refreshRestoredSessionIndexes(restoredSession: SessionSummary) {
    const [projectPayload, allSessions] = await Promise.all([
      listProjectWorkspaces(),
      listSessions(),
    ]);
    const visibleRestored = isVisibleMainChatSession(restoredSession) ? [restoredSession] : [];
    const sessions = mergeSessionSummaries(visibleMainChatSessions(allSessions), visibleRestored);
    const projects = Array.isArray(projectPayload.projects) ? projectPayload.projects : [];
    this.sessionListFailureNotifiedAt = 0;
    this.store.setState((prev) => {
      const activeProjectRoot = prev.activeProjectRoot;
      const nextState = {
        ...prev,
        sessions,
        projectWorkspaces: projects,
      };
      return {
        ...nextState,
        projectSessions: activeProjectRoot
          ? sessions.filter((session) => sessionBelongsToProject(session, activeProjectRoot))
          : prev.projectSessions,
        permissionMode: this.permissionModeForSession(prev.currentSessionId, nextState, prev.permissionMode),
      };
    });
  }

  private async resolveProjectWorkspaceForSession(session: SessionSummary) {
    const projectRoot = sessionProjectRoot(session);
    const currentProjects = this.store.getState().projectWorkspaces;
    if (!projectRoot) {
      return {
        projects: currentProjects,
        activeProject: null,
      };
    }
    const hasProject = currentProjects.some((project) => sessionBelongsToProject(session, project.workspace_root));
    let projects = currentProjects;
    if (!hasProject) {
      const payload = await listProjectWorkspaces();
      projects = Array.isArray(payload.projects) ? payload.projects : [];
    }
    return {
      projects,
      activeProject: projects.find((project) => sessionBelongsToProject(session, project.workspace_root)) ?? null,
    };
  }

  private async initializeFromSessionList(
    projectPayloadOverride?: Awaited<ReturnType<typeof listProjectWorkspaces>>,
    options: { preferLatestVisibleSession?: boolean } = {},
  ) {
    const [projectPayload, allSessions] = await Promise.all([
      projectPayloadOverride ? Promise.resolve(projectPayloadOverride) : listProjectWorkspaces(),
      listSessions(),
    ]);
    const sessions = visibleMainChatSessions(allSessions);
    const projects = Array.isArray(projectPayload.projects) ? projectPayload.projects : [];
    const currentSessionId = this.store.getState().currentSessionId;
    const currentSession = currentSessionId ? sessions.find((session) => session.id === currentSessionId) : null;
    const fallbackSession = currentSession
      ? null
      : options.preferLatestVisibleSession
        ? sessions[0] ?? null
        : unboundMainChatSessions(sessions)[0] ?? null;
    const targetSession = currentSession ?? fallbackSession;
    const targetProjectRoot = sessionProjectRoot(targetSession);
    const activeProject = targetProjectRoot
      ? projects.find((project) => sessionBelongsToProject(targetSession!, project.workspace_root))
      : null;
    this.store.setState((prev) => ({
      ...prev,
      sessions,
      projectWorkspaces: projects,
      activeProjectKey: activeProject?.key || "",
      activeProjectRoot: activeProject?.workspace_root || "",
    }));

    if (activeProject) {
      await this.selectProjectWorkspace(activeProject.key, { preferredSessionId: targetSession?.id || undefined, fallbackSession: targetSession || undefined });
    } else if (!currentSession) {
      const nextSession = fallbackSession;
      if (!nextSession) {
        this.clearActiveSession();
      } else {
        const sessionId = nextSession.id;
        const restoredFromStreamCache = this.applySelectedSessionShell(sessionId, {
          scope: nextSession.scope,
          poolKey: MAIN_CHAT_POOL_KEY,
        });
        if (!restoredFromStreamCache) {
          const reattached = await this.reattachChatRunForSession(sessionId);
          if (!reattached) {
            void this.refreshSessionDetails(sessionId).catch(() => undefined);
            void this.hydrateLatestOrchestrationSnapshot(sessionId).catch(() => undefined);
          }
        }
      }
    } else if (currentSession) {
      const restoredFromStreamCache = this.applySelectedSessionShell(currentSession.id, {
        scope: currentSession.scope,
        poolKey: MAIN_CHAT_POOL_KEY,
      });
      if (!restoredFromStreamCache) {
        const reattached = await this.reattachChatRunForSession(currentSession.id);
        if (!reattached) {
          void this.refreshSessionDetails(currentSession.id).catch(() => undefined);
          void this.hydrateLatestOrchestrationSnapshot(currentSession.id).catch(() => undefined);
        }
      }
    }
    this.store.setState((prev) => ({
      ...prev,
      workspaceInitializing: false,
    }));
  }

  private async loadWorkspaceMetadata() {
    const [permissionMode, skills, modelProviderConfig, imageAssetConfig, workspaceContext] = await Promise.all([
      getPermissionMode().catch(() => null),
      listSkills().catch(() => []),
      getModelProviderConfig().catch(() => null),
      getImageAssetConfig().catch(() => null),
      getWorkspaceContext().catch(() => null),
    ]);
    this.store.setState((prev) => {
      const supportedPermissionModes = Array.isArray(permissionMode?.supported_modes) && permissionMode.supported_modes.length
        ? permissionMode.supported_modes.map(String)
        : prev.supportedPermissionModes;
      return {
        ...prev,
        permissionMode: this.permissionModeForSession(
          prev.currentSessionId,
          prev,
          String(permissionMode?.mode || DEFAULT_PERMISSION_MODE),
        ),
        supportedPermissionModes,
        modelProviderConfig,
        imageAssetConfig,
        workspaceContext,
        skills,
        selectedChatMode: this.resolveSelectedChatMode(prev.selectedChatModelId, modelProviderConfig),
        chatThinkingMode: chatThinkingModeFromProviderConfig(modelProviderConfig),
      };
    });
  }

  private async loadInspectorMemoryFile() {
    const state = this.store.getState();
    const sessionId = state.currentSessionId || "";
    if (!sessionId && state.activeProjectKey) {
      return;
    }
    if (sessionId && !this.sessionProjectRoot(state, sessionId)) {
      return;
    }
    const file = sessionId
      ? await loadFileForSession(DEFAULT_INSPECTOR_PATH, sessionId, this.sessionScopeForSession(sessionId)).catch(() => null)
      : await loadFile(DEFAULT_INSPECTOR_PATH).catch(() => null);
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
    this.clearAllPendingVisibleStreamFlushes();
    for (const timer of this.sessionRefreshTimers) {
      window.clearTimeout(timer);
    }
    this.sessionRefreshTimers = [];
    if (this.sessionTokenStatsTimer) {
      window.clearTimeout(this.sessionTokenStatsTimer);
      this.sessionTokenStatsTimer = null;
    }
    if (this.sessionRuntimeProjectionTimer) {
      window.clearTimeout(this.sessionRuntimeProjectionTimer);
      this.sessionRuntimeProjectionTimer = null;
    }
    this.runMonitorController.stop();
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
        void this.refreshMainSessionPool().catch((error) => {
          this.noteSessionRefreshFailure(error);
        });
      }, delay)
    );
  }

  private async refreshMainSessionPool() {
    const sessions = visibleMainChatSessions(await listSessions());
    this.sessionListFailureNotifiedAt = 0;
    this.store.setState((prev) => {
      const activeProjectRoot = prev.activeProjectRoot;
      const nextState = { ...prev, sessions };
      const projected = {
        ...nextState,
        projectSessions: activeProjectRoot
          ? sessions.filter((session) => sessionBelongsToProject(session, activeProjectRoot))
          : prev.projectSessions,
        permissionMode: this.permissionModeForSession(prev.currentSessionId, nextState, prev.permissionMode),
      };
      if (prev.currentSessionId && prev.sessionActivity.event === "workspace_initialize_failed") {
        return this.clearSessionActivityFor(projected, prev.currentSessionId);
      }
      return projected;
    });
    return sessions;
  }

  private async refreshProjectWorkspaces() {
    this.store.setState((prev) => ({
      ...prev,
      projectWorkspacesLoading: true,
      projectWorkspacesError: "",
    }));
    try {
      const payload = await listProjectWorkspaces();
      this.store.setState((prev) => ({
        ...prev,
        projectWorkspaces: Array.isArray(payload.projects) ? payload.projects : [],
        projectWorkspacesLoading: false,
        projectWorkspacesError: "",
      }));
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        projectWorkspacesLoading: false,
        projectWorkspacesError: this.errorMessage(error, "项目列表读取失败。"),
      }));
    }
  }

  private async refreshProjectSessions(projectKey = this.store.getState().activeProjectKey) {
    if (!projectKey) {
      this.store.setState((prev) => ({ ...prev, projectSessions: [] }));
      return [];
    }
    const payload = await listProjectWorkspaceSessions(projectKey);
    const projectSessions = visibleMainChatSessions(payload.sessions);
    this.store.setState((prev) => ({
      ...prev,
      projectSessions,
      sessions: mergeSessionSummaries(prev.sessions, projectSessions),
    }));
    return projectSessions;
  }

  private async selectProjectWorkspace(
    projectKey: string,
    options: { preferredSessionId?: string; fallbackSession?: SessionSummary } = {},
  ) {
    const normalizedKey = String(projectKey || "").trim();
    if (!normalizedKey) {
      await this.selectGeneralConversationScope();
      return;
    }
    const projectPayload = this.store.getState().projectWorkspaces.length
      ? { projects: this.store.getState().projectWorkspaces }
      : await listProjectWorkspaces();
    const project = projectPayload.projects.find((item) => item.key === normalizedKey);
    if (!project) {
      throw new Error("项目工作区不存在。");
    }
    this.store.setState((prev) => ({
      ...prev,
      activeProjectKey: project.key,
      activeProjectRoot: project.workspace_root,
      projectWorkspaces: mergeProjectWorkspaces(prev.projectWorkspaces, [project]),
      workspaceTree: null,
      workspaceTreeError: "",
    }));
    let projectSessions = await this.refreshProjectSessions(project.key);
    const fallbackSession = options.fallbackSession && sessionBelongsToProject(options.fallbackSession, project.workspace_root)
      ? options.fallbackSession
      : null;
    if (fallbackSession && !projectSessions.some((session) => session.id === fallbackSession.id)) {
      projectSessions = mergeSessionSummaries(projectSessions, [fallbackSession]);
      this.store.setState((prev) => ({
        ...prev,
        sessions: mergeSessionSummaries(prev.sessions, [fallbackSession]),
        projectSessions,
      }));
    }
    const preferred = options.preferredSessionId
      ? projectSessions.find((session) => session.id === options.preferredSessionId)
      : null;
    const nextSession = preferred ?? projectSessions[0] ?? null;
    if (!nextSession) {
      this.clearActiveSession();
      void this.refreshWorkspaceTree().catch(() => undefined);
      return;
    }
    const restoredFromStreamCache = this.applySelectedSessionShell(nextSession.id, {
      scope: nextSession.scope,
      poolKey: MAIN_CHAT_POOL_KEY,
    });
    if (!restoredFromStreamCache) {
      const reattached = await this.reattachChatRunForSession(nextSession.id);
      if (!reattached) {
        void this.refreshSessionDetails(nextSession.id).catch(() => undefined);
        void this.hydrateLatestOrchestrationSnapshot(nextSession.id).catch(() => undefined);
      }
    }
  }

  private async selectProjectWorkspaceDirectory() {
    this.store.setState((prev) => ({
      ...prev,
      projectWorkspacesLoading: true,
      projectWorkspacesError: "",
    }));
    try {
      const payload = await selectProjectWorkspaceDirectory();
      this.store.setState((prev) => ({
        ...prev,
        projectWorkspacesLoading: false,
        projectWorkspacesError: "",
        projectWorkspaces: mergeProjectWorkspaces(prev.projectWorkspaces, [payload.project]),
      }));
      await this.selectProjectWorkspace(payload.project.key);
    } catch (error) {
      if (isProjectDirectorySelectionCancelled(error)) {
        this.store.setState((prev) => ({
          ...prev,
          projectWorkspacesLoading: false,
          projectWorkspacesError: "",
        }));
        return;
      }
      this.store.setState((prev) => ({
        ...prev,
        projectWorkspacesLoading: false,
        projectWorkspacesError: this.errorMessage(error, "无法选择项目目录。"),
      }));
      throw error;
    }
  }

  private async selectGeneralConversationScope() {
    this.store.setState((prev) => ({
      ...prev,
      activeProjectKey: "",
      activeProjectRoot: "",
      projectSessions: [],
      workspaceTree: null,
      workspaceTreeError: "",
    }));
    const refreshedSessions = await this.refreshMainSessionPool().catch((error) => {
      this.noteSessionRefreshFailure(error);
      return null;
    });
    const sessions = refreshedSessions ?? this.store.getState().sessions;
    const unboundSessions = unboundMainChatSessions(sessions);
    const currentSessionId = this.store.getState().currentSessionId || "";
    const currentUnboundSession = currentSessionId
      ? unboundSessions.find((session) => session.id === currentSessionId) ?? null
      : null;
    const nextSession = currentUnboundSession ?? unboundSessions[0] ?? null;
    if (nextSession) {
      await this.activateMainChatSession(nextSession);
    } else {
      this.clearActiveSession();
    }
    void this.refreshWorkspaceTree().catch(() => undefined);
  }

  private async removeProjectWorkspace(projectKey: string) {
    const normalizedKey = String(projectKey || "").trim();
    if (!normalizedKey) {
      return;
    }
    const previous = this.store.getState();
    const previousSessionId = previous.currentSessionId || "";
    const removingActiveProject = previous.activeProjectKey === normalizedKey;
    this.store.setState((prev) => ({
      ...prev,
      projectWorkspacesLoading: true,
      projectWorkspacesError: "",
    }));
    try {
      const removal = await removeProjectWorkspace(normalizedKey, { detachSessions: true });
      const [projectPayload, allSessions] = await Promise.all([
        listProjectWorkspaces(),
        listSessions(),
      ]);
      const sessions = visibleMainChatSessions(allSessions);
      const projects = Array.isArray(projectPayload.projects) ? projectPayload.projects : [];
      const detachedSessionIds = new Set((removal.detached_sessions || []).map((session) => session.id));
      const detachedCurrentSession = previousSessionId
        ? sessions.find((session) => detachedSessionIds.has(session.id) && session.id === previousSessionId && !sessionProjectRoot(session)) ?? null
        : null;
      const shouldClearActiveProject = removingActiveProject || Boolean(detachedCurrentSession);
      const nextActiveProjectKey = shouldClearActiveProject ? "" : this.store.getState().activeProjectKey;
      const nextActiveProjectRoot = shouldClearActiveProject ? "" : this.store.getState().activeProjectRoot;
      this.store.setState((prev) => ({
        ...prev,
        sessions,
        projectWorkspaces: projects,
        projectWorkspacesLoading: false,
        projectWorkspacesError: "",
        activeProjectKey: nextActiveProjectKey,
        activeProjectRoot: nextActiveProjectRoot,
        projectSessions: nextActiveProjectRoot
          ? sessions.filter((session) => sessionBelongsToProject(session, nextActiveProjectRoot))
          : [],
        workspaceTree: shouldClearActiveProject ? null : prev.workspaceTree,
        workspaceTreeError: shouldClearActiveProject ? "" : prev.workspaceTreeError,
      }));

      if (shouldClearActiveProject) {
        const unboundSessions = unboundMainChatSessions(sessions);
        const nextSession = detachedCurrentSession ?? unboundSessions[0] ?? null;
        if (nextSession) {
          await this.activateMainChatSession(nextSession);
        } else {
          this.clearActiveSession();
        }
        void this.refreshWorkspaceTree().catch(() => undefined);
      }
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        projectWorkspacesLoading: false,
        projectWorkspacesError: this.errorMessage(error, "项目移出失败。"),
      }));
      throw error;
    }
  }

  private async activateMainChatSession(session: SessionSummary) {
    const restoredFromStreamCache = this.applySelectedSessionShell(session.id, {
      scope: session.scope,
      poolKey: MAIN_CHAT_POOL_KEY,
    });
    if (restoredFromStreamCache) {
      return;
    }
    const reattached = await this.reattachChatRunForSession(session.id);
    if (!reattached) {
      void this.refreshSessionDetails(session.id).catch(() => undefined);
      void this.hydrateLatestOrchestrationSnapshot(session.id).catch(() => undefined);
    }
  }

  private refreshMainSessionPoolInBackground() {
    void this.refreshMainSessionPool().catch((error) => {
      this.noteSessionRefreshFailure(error);
    });
  }

  private requestSummarySessionTitleInBackground(sessionId: string) {
    const normalizedSessionId = String(sessionId || "").trim();
    if (
      !normalizedSessionId
      || this.summaryTitleRequests.has(normalizedSessionId)
      || !this.shouldDeriveSessionTitleFromSummary(normalizedSessionId)
    ) {
      return;
    }
    this.summaryTitleRequests.add(normalizedSessionId);
    void deriveSessionTitleFromSummary(normalizedSessionId, this.sessionScopeForSession(normalizedSessionId))
      .then((result) => {
        const title = String(result.title || "").trim();
        if (!title || this.isDefaultSessionTitle(title)) {
          return;
        }
        this.store.setState((prev) => ({
          ...prev,
          sessions: prev.sessions.map((session) =>
            session.id === normalizedSessionId && this.isDefaultSessionTitle(session.title)
              ? { ...session, title }
              : session
          ),
          projectSessions: prev.projectSessions.map((session) =>
            session.id === normalizedSessionId && this.isDefaultSessionTitle(session.title)
              ? { ...session, title }
              : session
          ),
        }));
      })
      .catch((error) => {
        console.debug("[workspace-runtime] summary session title derivation skipped", {
          event: "summary_session_title_derivation_failed",
          sessionId: normalizedSessionId,
          error: this.errorMessage(error, "会话摘要命名失败。"),
        });
      })
      .finally(() => {
        this.summaryTitleRequests.delete(normalizedSessionId);
      });
  }

  private shouldDeriveSessionTitleFromSummary(sessionId: string, state = this.store.getState()) {
    const session = state.sessions.find((item) => item.id === sessionId)
      ?? state.projectSessions.find((item) => item.id === sessionId);
    return Boolean(session && this.isDefaultSessionTitle(session.title));
  }

  private isDefaultSessionTitle(title: string | null | undefined) {
    return String(title || "").trim() === DEFAULT_SESSION_TITLE;
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

  private async refreshTaskEnvironmentCatalog() {
    this.store.setState((prev) => ({
      ...prev,
      taskEnvironmentCatalogLoading: true,
      taskEnvironmentCatalogError: "",
    }));
    try {
      const catalog = await getTaskEnvironmentCatalog();
      this.store.setState((prev) => {
        const active = prev.conversationActiveEnvironment
          ? this.normalizeActiveTaskEnvironment(prev.conversationActiveEnvironment, catalog)
          : null;
        return {
          ...prev,
          taskEnvironmentCatalog: catalog,
          taskEnvironmentCatalogLoading: false,
          taskEnvironmentCatalogError: "",
          conversationActiveEnvironment: active,
        };
      });
      if (!this.store.getState().conversationActiveEnvironment) {
        this.store.setState((prev) => ({
          ...prev,
          conversationActiveEnvironment: this.defaultActiveTaskEnvironment("workspace-mode"),
        }));
      }
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskEnvironmentCatalogLoading: false,
        taskEnvironmentCatalogError: this.errorMessage(error, "任务环境目录读取失败。"),
      }));
    }
  }

  private async refreshSessionDetails(sessionId: string) {
    const requestId = ++this.sessionDetailsRequest;
    try {
      const scope = this.sessionScopeForSession(sessionId);
      const history = await getSessionHistory(sessionId, scope);
      if (this.store.getState().currentSessionId !== sessionId || this.sessionDetailsRequest !== requestId) {
        return;
      }
      this.store.setState((prev) => {
        const conversationActiveEnvironment = this.shouldUseConversationEnvironment(prev.activeSessionRef ?? undefined)
          ? this.activeEnvironmentFromConversationState(history.conversation_state) ?? prev.conversationActiveEnvironment ?? this.defaultActiveTaskEnvironment()
          : prev.conversationActiveEnvironment;
        const permissionMode = history.conversation_state
          ? this.permissionModeFromConversationState(history.conversation_state)
          : this.permissionModeForSession(sessionId, prev);
        const hydratedProjection = hydrateSessionRuntimeProjection(
          {
            messages: toUiMessages(history.messages),
            activeProjectionsByKey: {},
          },
          (history as { runtime_attachments?: SessionRuntimeAttachment[] }).runtime_attachments,
        );
        const refreshedMessages = this.mergeVolatileMessageProgress(
          hydratedProjection.messages,
          prev.messages,
        );
        const visibleMessages = this.messagesForSessionDetailsRefresh(sessionId, prev, refreshedMessages);
        const activeProjectionsByKey = this.activeProjectionsForSessionDetailsRefresh(
          sessionId,
          prev,
          hydratedProjection.activeProjectionsByKey,
        );
        const next: StoreState = {
          ...prev,
          messages: visibleMessages,
          activeProjectionsByKey,
          tokenStats: prev.tokenStats,
          conversationActiveEnvironment,
          permissionMode,
          sessions: prev.sessions.map((session) => session.id === sessionId
            ? {
                ...session,
                conversation_state: history.conversation_state
                  ? history.conversation_state
                  : this.conversationStateWithPermissionMode(session.conversation_state, permissionMode),
              }
            : session
          ),
        };
        return prev.sessionActivity.event === "session_history_load_failed" || prev.sessionActivity.event === "workspace_initialize_failed"
          ? this.clearSessionActivityFor(next, sessionId)
          : next;
      });
      this.scheduleSessionTokenStatsRefresh(sessionId, requestId);
      this.scheduleSessionRuntimeProjectionRefresh(sessionId, requestId);
      void this.refreshWorkspaceTree().catch(() => undefined);
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

  private async refreshSessionRuntimeProjection(sessionId: string, detailsRequestId = this.sessionDetailsRequest) {
    const requestId = ++this.sessionRuntimeProjectionRequest;
    const scope = this.sessionScopeForSession(sessionId);
    const projection = await getSessionRuntimeProjection(sessionId, scope);
    if (
      this.store.getState().currentSessionId !== sessionId
      || this.sessionDetailsRequest !== detailsRequestId
      || this.sessionRuntimeProjectionRequest !== requestId
    ) {
      return;
    }
    this.store.setState((prev) => {
      const hydratedProjection = hydrateSessionRuntimeProjection(
        {
          messages: toUiMessages(projection.messages),
          activeProjectionsByKey: {},
        },
        projection.runtime_attachments,
      );
      const refreshedMessages = this.mergeVolatileMessageProgress(
        hydratedProjection.messages,
        prev.messages,
      );
      return {
        ...prev,
        messages: this.messagesForSessionDetailsRefresh(sessionId, prev, refreshedMessages),
        activeProjectionsByKey: this.activeProjectionsForSessionDetailsRefresh(
          sessionId,
          prev,
          hydratedProjection.activeProjectionsByKey,
        ),
      };
    });
  }

  private scheduleSessionRuntimeProjectionRefresh(sessionId: string, detailsRequestId: number) {
    if (this.sessionRuntimeProjectionTimer) {
      clearTimeout(this.sessionRuntimeProjectionTimer);
      this.sessionRuntimeProjectionTimer = null;
    }
    this.sessionRuntimeProjectionTimer = setTimeout(() => {
      this.sessionRuntimeProjectionTimer = null;
      if (
        this.store.getState().currentSessionId !== sessionId
        || this.sessionDetailsRequest !== detailsRequestId
      ) {
        return;
      }
      void this.refreshSessionRuntimeProjection(sessionId, detailsRequestId).catch(() => undefined);
    }, SESSION_RUNTIME_PROJECTION_DELAY_MS);
  }

  private scheduleSessionTokenStatsRefresh(sessionId: string, detailsRequestId: number) {
    if (this.sessionTokenStatsTimer) {
      clearTimeout(this.sessionTokenStatsTimer);
      this.sessionTokenStatsTimer = null;
    }
    this.sessionTokenStatsTimer = setTimeout(() => {
      this.sessionTokenStatsTimer = null;
      if (
        this.store.getState().currentSessionId !== sessionId
        || this.sessionDetailsRequest !== detailsRequestId
      ) {
        return;
      }
      void this.refreshCurrentSessionTokenStats("session_details_refresh").catch(() => undefined);
    }, SESSION_TOKEN_STATS_DELAY_MS);
  }

  private messagesForSessionDetailsRefresh(
    sessionId: string,
    current: StoreState,
    refreshedMessages: Message[],
  ) {
    if (
      current.currentSessionId === sessionId
      && current.activeStreamSessionIds.includes(sessionId)
      && current.messages.length > 0
    ) {
      return current.messages;
    }
    return refreshedMessages;
  }

  private activeProjectionsForSessionDetailsRefresh(
    sessionId: string,
    current: StoreState,
    refreshedActiveProjections: StoreState["activeProjectionsByKey"],
  ) {
    if (
      current.currentSessionId === sessionId
      && current.activeStreamSessionIds.includes(sessionId)
      && current.messages.length > 0
    ) {
      return current.activeProjectionsByKey;
    }
    return refreshedActiveProjections;
  }

  private mergeVolatileMessageProgress(refreshedMessages: Message[], currentMessages: Message[]) {
    if (!currentMessages.some((message) => this.messageHasRuntimeVolatileState(message))) {
      return refreshedMessages;
    }
    const currentVolatileMessages = currentMessages.filter((message) =>
      message.role === "assistant" && this.messageHasRuntimeVolatileState(message)
    );
    const currentById = new Map(currentVolatileMessages.map((message) => [message.id, message]));
    const refreshedWithMergedProgress = refreshedMessages.map((message) => {
      if (message.role !== "assistant") {
        return message;
      }
      const current = currentById.get(message.id)
        ?? this.findCurrentRuntimeMessageForRefresh(message, currentVolatileMessages);
      if (!current || !this.messageHasRuntimeVolatileState(current)) {
        return message;
      }
      return {
        ...message,
        runtimeProgress: this.mergeMessageRuntimeProgress(message.runtimeProgress, current.runtimeProgress ?? []),
        closeoutSummary: message.closeoutSummary ?? current.closeoutSummary,
        runtimeLogRef: message.runtimeLogRef ?? current.runtimeLogRef,
        toolEventCount: message.toolEventCount ?? current.toolEventCount,
        content: message.content || current.content,
        stageStatus: message.stageStatus ?? current.stageStatus,
      };
    });
    const refreshedMessageIds = new Set(refreshedWithMergedProgress.map((message) => message.id));
    const preservedRuntimeMessages = currentVolatileMessages.filter((message) =>
      !refreshedMessageIds.has(message.id)
      && !this.refreshedMessagesContainRuntimeAnchor(refreshedWithMergedProgress, message)
      && this.refreshedHistoryContainsRuntimeTurn(refreshedMessages, message)
    );
    return [...refreshedWithMergedProgress, ...preservedRuntimeMessages]
      .sort((left, right) => {
        const leftIndex = left.sourceIndex ?? Number.MAX_SAFE_INTEGER;
        const rightIndex = right.sourceIndex ?? Number.MAX_SAFE_INTEGER;
        if (leftIndex !== rightIndex) return leftIndex - rightIndex;
        if (left.role !== right.role) return left.role === "user" ? -1 : 1;
        return left.id.localeCompare(right.id);
      });
  }

  private messageHasRuntimeVolatileState(message: Message) {
    return Boolean(
      message.runtimeProgress?.length
      || message.projectionKeyString
    );
  }

  private findCurrentRuntimeMessageForRefresh(message: Message, candidates: Message[]) {
    return candidates.find((candidate) => this.messagesShareRuntimeIdentity(message, candidate));
  }

  private refreshedMessagesContainRuntimeAnchor(refreshedMessages: Message[], current: Message) {
    return refreshedMessages.some((message) =>
      message.role === "assistant" && this.messagesShareRuntimeIdentity(message, current)
    );
  }

  private refreshedHistoryContainsRuntimeTurn(refreshedMessages: Message[], current: Message) {
    const turns = this.messageRuntimeTurnIds(current);
    if (!turns.size) {
      return false;
    }
    return refreshedMessages.some((message) =>
      message.role === "user" && turns.has(String(message.sourceTurnId ?? "").trim())
    );
  }

  private messagesShareRuntimeIdentity(left: Message, right: Message) {
    const leftTurns = this.messageRuntimeTurnIds(left);
    const rightTurns = this.messageRuntimeTurnIds(right);
    const sharedTurn = this.setsIntersect(leftTurns, rightTurns);
    const leftRuns = this.messageRuntimeRunIds(left);
    const rightRuns = this.messageRuntimeRunIds(right);
    const sharedRun = this.setsIntersect(leftRuns, rightRuns);
    if (sharedTurn && (!leftRuns.size || !rightRuns.size || sharedRun)) {
      return true;
    }
    return sharedRun && (!leftTurns.size || !rightTurns.size || sharedTurn);
  }

  private messageRuntimeTurnIds(message: Message) {
    const values = new Set<string>();
    const add = (value: unknown) => {
      const text = String(value ?? "").trim();
      if (text) values.add(text);
    };
    add(message.sourceTurnId);
    return values;
  }

  private messageRuntimeRunIds(message: Message) {
    const values = new Set<string>();
    const add = (value: unknown) => {
      const text = String(value ?? "").trim();
      if (text) values.add(text);
    };
    add(message.sourceRunId);
    add(message.sourceTaskRunId);
    add(message.sourceTurnRunId);
    return values;
  }

  private setsIntersect(left: Set<string>, right: Set<string>) {
    for (const item of left) {
      if (right.has(item)) return true;
    }
    return false;
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
        chatStreamConnectionStatus: {
          state: "streaming",
          updatedAt: Date.now(),
        },
      };
    });
  }

  private async uploadChatAttachmentsForSession(sessionId: string, files: File[]) {
    const uploaded: ChatAttachment[] = [];
    for (const file of files) {
      uploaded.push(await uploadChatAttachment(sessionId, file));
    }
    return uploaded;
  }

  private activeTaskQueueTarget(state: StoreState, sessionId: string): Partial<QueuedUserInput> {
    if (!this.shouldQueueActiveTurnInput(state, sessionId)) {
      return {};
    }
    const monitorInfo = this.singleAgentTaskMonitorInfo(state.taskGraphLiveMonitor);
    const taskRunId = String(state.activeTurnSnapshot?.task_run_id ?? monitorInfo?.taskRunId ?? "").trim();
    const expectedActiveTurnId = this.expectedActiveTurnIdForSession(state, sessionId, taskRunId);
    return {
      inputPolicy: "steer",
      expectedActiveTurnId,
      taskRunId,
    };
  }

  private queuedUserInputForSession(
    sessionId: string,
    content: string,
    messageId: string,
    target: Partial<QueuedUserInput> = this.activeTaskQueueTarget(this.store.getState(), sessionId),
  ): QueuedUserInput {
    return {
      content,
      messageId,
      inputPolicy: target.inputPolicy,
      expectedActiveTurnId: target.expectedActiveTurnId,
      taskRunId: target.taskRunId,
    };
  }

  private enqueueUserInputForSession(sessionId: string, content: string, target?: Partial<QueuedUserInput>) {
    const messageId = makeId();
    const queued = this.queuedUserInputsBySession.get(sessionId) ?? [];
    this.queuedUserInputsBySession.set(sessionId, [
      ...queued,
      this.queuedUserInputForSession(sessionId, content, messageId, target),
    ]);
    this.store.setState((prev) => {
      const shouldPatchVisibleMessages = prev.currentSessionId === sessionId;
      const nextMessages = shouldPatchVisibleMessages
        ? [
            ...prev.messages,
            {
              id: messageId,
              role: "user" as const,
              content,
              toolCalls: [],
              retrievals: [],
            },
          ]
        : prev.messages;
      return {
        ...prev,
        messages: nextMessages,
        sessionActivity: prev.currentSessionId === sessionId
          ? {
              level: "running",
              title: "已加入发送队列",
              detail: "当前回合结束后会按顺序提交这条消息。",
              event: "user_input_queued",
              receipt: {
                level: "running",
                title: "已加入发送队列",
                body: "当前回合结束后会按顺序提交这条消息。",
                debug: { event: "user_input_queued" },
              },
              updatedAt: Date.now(),
            }
          : prev.sessionActivity,
        sessionActivitiesById: {
          ...prev.sessionActivitiesById,
          [sessionId]: {
            level: "running",
            title: "已加入发送队列",
            detail: "当前回合结束后会按顺序提交这条消息。",
            event: "user_input_queued",
            receipt: {
              level: "running",
              title: "已加入发送队列",
              body: "当前回合结束后会按顺序提交这条消息。",
              debug: { event: "user_input_queued" },
            },
            updatedAt: Date.now(),
          },
        },
      };
    });
  }

  private async flushQueuedUserInputsForSession(sessionId: string) {
    if (this.flushingQueuedUserInputs.has(sessionId) || this.store.getState().activeStreamSessionIds.includes(sessionId)) {
      return;
    }
    const queue = this.queuedUserInputsBySession.get(sessionId) ?? [];
    const next = queue.shift();
    if (!next) {
      this.queuedUserInputsBySession.delete(sessionId);
      return;
    }
    if (queue.length) {
      this.queuedUserInputsBySession.set(sessionId, queue);
    } else {
      this.queuedUserInputsBySession.delete(sessionId);
    }
    this.flushingQueuedUserInputs.add(sessionId);
    try {
      await this.sendMessage(next.content, {
        queuedUserMessageId: next.messageId,
        activeTurnInputPolicy: next.inputPolicy,
        expectedActiveTurnId: next.expectedActiveTurnId,
        taskRunId: next.taskRunId,
      });
    } finally {
      this.flushingQueuedUserInputs.delete(sessionId);
      if ((this.queuedUserInputsBySession.get(sessionId) ?? []).length) {
        void this.flushQueuedUserInputsForSession(sessionId);
      }
    }
  }

  private async submitActiveTurnSteerDuringActiveStream(
    sessionId: string,
    content: string,
    options: {
      queuedUserMessageId?: string;
      activeTurnInputPolicy?: "auto" | "steer";
      expectedActiveTurnId?: string;
      taskRunId?: string;
    } = {},
  ) {
    const preflightState = this.store.getState();
    if (!this.shouldQueueActiveTurnInput(preflightState, sessionId)) {
      if (options.queuedUserMessageId) {
        const queued = this.queuedUserInputsBySession.get(sessionId) ?? [];
        this.queuedUserInputsBySession.set(sessionId, [
          this.queuedUserInputForSession(sessionId, content, options.queuedUserMessageId, {
            inputPolicy: options.activeTurnInputPolicy,
            expectedActiveTurnId: options.expectedActiveTurnId,
            taskRunId: options.taskRunId,
          }),
          ...queued,
        ]);
      } else {
        this.enqueueUserInputForSession(sessionId, content);
      }
      return;
    }

    const expectedActiveTurnId = options.expectedActiveTurnId || this.expectedActiveTurnIdForSession(preflightState, sessionId, options.taskRunId);
    const activeStreamSessionIds = this.store.getState().activeStreamSessionIds;
    let transition = startQueuedActiveTurn(preflightState, content, { existingUserMessageId: options.queuedUserMessageId });
    const nextSourceIndex = this.nextMessageSourceIndex(this.store.getState().messages);
    transition = {
      ...transition,
      state: {
        ...transition.state,
        messages: transition.state.messages.map((message) =>
          transition.session.userId && message.id === transition.session.userId
            ? { ...message, sourceIndex: nextSourceIndex }
            : transition.session.assistantId && message.id === transition.session.assistantId
              ? { ...message, sourceIndex: nextSourceIndex + 1 }
              : message
        ),
      },
    };
    let streamState: StoreState = {
      ...transition.state,
      activeStreamSessionIds,
      isStreaming: activeStreamSessionIds.length > 0,
    };
    streamState = this.captureSessionActivity(streamState, sessionId);
    this.streamingSessionCache.set(sessionId, {
      messages: streamState.messages,
      activeProjectionsByKey: streamState.activeProjectionsByKey,
      orchestrationSnapshot: streamState.orchestrationSnapshot,
      activeTurnSnapshot: streamState.activeTurnSnapshot,
    });
    if (this.store.getState().currentSessionId === sessionId) {
      this.applyVisibleStreamState(streamState, activeStreamSessionIds, { preserveTaskGraphLiveMonitor: true });
    }
    const streamEpoch = this.chatStreamEpochBySession.get(sessionId) ?? 0;

    try {
      const requestState = this.store.getState();
      const permissionMode = this.permissionModeForSession(sessionId, requestState);
      await streamChat(
        {
          message: content,
          session_id: sessionId,
          session_scope: this.sessionScopeForSession(sessionId),
          environment_binding: this.chatEnvironmentBindingPayload(requestState),
          model_selection: this.chatModelSelectionPayload(requestState),
          permission_mode: permissionMode,
          expected_active_turn_id: expectedActiveTurnId,
          active_turn_input_policy: "steer",
          editor_context: this.chatEditorContextPayload(requestState, sessionId),
        },
        {
          onEvent: (event, data) => {
            if (!this.isCurrentChatStreamEpoch(sessionId, streamEpoch)) {
              return;
            }
            if (this.removedStreamingSessionIds.has(sessionId)) {
              return;
            }
            if (this.stoppedStreamingSessionIds.has(sessionId)) {
              return;
            }
            const eventBinding = this.eventChatStreamBinding(data);
            this.updateActiveChatStreamBinding(sessionId, eventBinding);
            const isCurrentStreamSession = this.store.getState().currentSessionId === sessionId;
            const baseState = isCurrentStreamSession && !this.pendingVisibleStreamFlushes.has(sessionId)
              ? this.store.getState()
              : streamState;
            transition = reduceStreamEvent(baseState, transition.session, event, data);
            const currentActiveStreamSessionIds = this.store.getState().activeStreamSessionIds;
            streamState = {
              ...transition.state,
              currentSessionId: sessionId,
              activeStreamSessionIds: currentActiveStreamSessionIds,
              isStreaming: currentActiveStreamSessionIds.length > 0,
            };
            streamState = this.captureSessionActivity(streamState, sessionId);
            if (currentActiveStreamSessionIds.includes(sessionId)) {
              this.streamingSessionCache.set(sessionId, {
                messages: streamState.messages,
                activeProjectionsByKey: streamState.activeProjectionsByKey,
                orchestrationSnapshot: streamState.orchestrationSnapshot,
                activeTurnSnapshot: streamState.activeTurnSnapshot,
              });
            }
            if (isCurrentStreamSession) {
              this.presentVisibleStreamState(
                sessionId,
                streamState,
                currentActiveStreamSessionIds,
                event,
                data,
                { preserveTaskGraphLiveMonitor: true },
              );
            }
            if (streamEventStopsActiveWork(event, data)) {
              this.releaseStoppedChatStreamBoundary(sessionId, "active_work_stopped", {
                taskRunId: eventBinding.taskRunId,
                turnId: eventBinding.turnId,
              });
            }
          },
        },
        { persistCursor: false },
      );
    } catch (error) {
      const transitionAfterError = reduceStreamEvent(
        this.store.getState().currentSessionId === sessionId ? this.store.getState() : streamState,
        transition.session,
        "error",
        { error: error instanceof Error ? error.message : "unknown error" },
      );
      const currentActiveStreamSessionIds = this.store.getState().activeStreamSessionIds;
      streamState = {
        ...transitionAfterError.state,
        currentSessionId: sessionId,
        activeStreamSessionIds: currentActiveStreamSessionIds,
        isStreaming: currentActiveStreamSessionIds.length > 0,
      };
      streamState = this.captureSessionActivity(streamState, sessionId);
      if (currentActiveStreamSessionIds.includes(sessionId)) {
        this.streamingSessionCache.set(sessionId, {
          messages: streamState.messages,
          activeProjectionsByKey: streamState.activeProjectionsByKey,
          orchestrationSnapshot: streamState.orchestrationSnapshot,
          activeTurnSnapshot: streamState.activeTurnSnapshot,
        });
      }
      if (this.store.getState().currentSessionId === sessionId) {
        this.flushVisibleStreamStateNow(
          sessionId,
          streamState,
          currentActiveStreamSessionIds,
          { preserveTaskGraphLiveMonitor: true },
        );
      }
    } finally {
      if (this.store.getState().currentSessionId === sessionId) {
        this.flushVisibleStreamStateNow(
          sessionId,
          streamState,
          this.store.getState().activeStreamSessionIds,
          { preserveTaskGraphLiveMonitor: true },
        );
      }
      if (!this.store.getState().activeStreamSessionIds.includes(sessionId)) {
        this.streamingSessionCache.delete(sessionId);
      }
    }
  }

  private removeActiveStreamSession(prev: StoreState, sessionId: string): StoreState {
    const activeStreamSessionIds = prev.activeStreamSessionIds.filter((id) => id !== sessionId);
    const shouldClearConnectionStatus = activeStreamSessionIds.length === 0
      && ["streaming", "reconnected", "idle"].includes(prev.chatStreamConnectionStatus.state);
    return {
      ...prev,
      isStreaming: activeStreamSessionIds.length > 0,
      activeStreamSessionIds,
      chatStreamConnectionStatus: shouldClearConnectionStatus
        ? { state: "idle", updatedAt: Date.now() }
        : prev.chatStreamConnectionStatus,
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

  private withVisibleEditorContextForSession(state: StoreState, sessionId: string | null): StoreState {
    const context = sessionId ? state.sessionEditorContexts[sessionId] : undefined;
    if (!context || (!context.activeFilePath && !context.openFilePaths.length)) {
      return {
        ...state,
        inspectorPath: DEFAULT_INSPECTOR_PATH,
        inspectorContent: "",
        inspectorDirty: false,
      };
    }
    return {
      ...state,
      inspectorPath: context.inspectorPath || context.activeFilePath || DEFAULT_INSPECTOR_PATH,
      inspectorContent: context.inspectorContent || "",
      inspectorDirty: Boolean(context.inspectorDirty),
    };
  }

  private uniqueFilePaths(paths: string[]) {
    const result: string[] = [];
    const seen = new Set<string>();
    for (const path of paths.map((item) => String(item || "").trim()).filter(Boolean)) {
      if (seen.has(path)) {
        continue;
      }
      seen.add(path);
      result.push(path);
    }
    return result;
  }

  private patchCurrentSessionEditorContext(state: StoreState, patch: Partial<SessionEditorContext>): StoreState {
    const sessionId = state.currentSessionId;
    if (!sessionId) {
      return state;
    }
    const current = state.sessionEditorContexts[sessionId] ?? {
      activeFilePath: "",
      openFilePaths: [],
      inspectorPath: "",
      inspectorContent: "",
      inspectorDirty: false,
      updatedAt: 0,
    };
    const activeFilePath = String(patch.activeFilePath ?? current.activeFilePath ?? "").trim();
    const inspectorPath = String(patch.inspectorPath ?? current.inspectorPath ?? "").trim();
    let openFilePaths = this.uniqueFilePaths(Array.isArray(patch.openFilePaths) ? patch.openFilePaths : current.openFilePaths);
    if (activeFilePath && !openFilePaths.includes(activeFilePath)) {
      openFilePaths = [...openFilePaths, activeFilePath];
    }
    const nextContext: SessionEditorContext = {
      activeFilePath,
      openFilePaths,
      inspectorPath,
      inspectorContent: String(patch.inspectorContent ?? current.inspectorContent ?? ""),
      inspectorDirty: Boolean(patch.inspectorDirty ?? current.inspectorDirty),
      updatedAt: Date.now(),
    };
    return {
      ...state,
      sessionEditorContexts: {
        ...state.sessionEditorContexts,
        [sessionId]: nextContext,
      },
    };
  }

  private applyVisibleStreamState(
    streamState: StoreState,
    activeStreamSessionIds: string[],
    options: VisibleStreamStateOptions = {},
  ) {
    this.store.setState((prev) => ({
      ...prev,
      messages: streamState.messages,
      activeProjectionsByKey: streamState.activeProjectionsByKey,
      orchestrationSnapshot: streamState.orchestrationSnapshot,
      activeTurnSnapshot: streamState.activeTurnSnapshot,
      taskGraphLiveMonitor: options.preserveTaskGraphLiveMonitor ? prev.taskGraphLiveMonitor : null,
      activeStreamSessionIds,
      isStreaming: activeStreamSessionIds.length > 0,
      chatStreamConnectionStatus: streamState.chatStreamConnectionStatus,
      sessionActivity: streamState.sessionActivity,
      sessionActivitiesById: {
        ...prev.sessionActivitiesById,
        ...streamState.sessionActivitiesById,
      },
    }));
  }

  private presentVisibleStreamState(
    sessionId: string,
    streamState: StoreState,
    activeStreamSessionIds: string[],
    event: string,
    data: Record<string, unknown>,
    options: VisibleStreamStateOptions = {},
  ) {
    if (this.store.getState().currentSessionId !== sessionId) {
      return;
    }
    if (this.streamEventCanUseDeferredVisibleFlush(event, data)) {
      this.deferVisibleStreamState(sessionId, streamState, activeStreamSessionIds, options);
      return;
    }
    this.flushVisibleStreamStateNow(sessionId, streamState, activeStreamSessionIds, options);
  }

  private streamEventCanUseDeferredVisibleFlush(event: string, data: Record<string, unknown>) {
    if (event !== "assistant_text_delta") {
      return false;
    }
    const frame = projectionFrameFromRecord(data.public_projection_frame);
    return frame?.op === "body_append" && frame.slot === "body";
  }

  private deferVisibleStreamState(
    sessionId: string,
    streamState: StoreState,
    activeStreamSessionIds: string[],
    options: VisibleStreamStateOptions,
  ) {
    const existing = this.pendingVisibleStreamFlushes.get(sessionId);
    if (existing) {
      existing.streamState = streamState;
      existing.activeStreamSessionIds = activeStreamSessionIds;
      existing.options = options;
      return;
    }
    const pending: PendingVisibleStreamFlush = {
      streamState,
      activeStreamSessionIds,
      options,
      timer: null,
      frame: null,
    };
    this.pendingVisibleStreamFlushes.set(sessionId, pending);
    const flush = () => {
      const latest = this.pendingVisibleStreamFlushes.get(sessionId);
      if (!latest) {
        return;
      }
      this.pendingVisibleStreamFlushes.delete(sessionId);
      if (this.store.getState().currentSessionId !== sessionId) {
        return;
      }
      if (this.removedStreamingSessionIds.has(sessionId)) {
        return;
      }
      this.applyVisibleStreamState(latest.streamState, latest.activeStreamSessionIds, latest.options);
    };
    if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
      pending.timer = window.setTimeout(() => {
        pending.timer = null;
        pending.frame = window.requestAnimationFrame(() => {
          pending.frame = null;
          flush();
        });
      }, VISIBLE_STREAM_BODY_FLUSH_DELAY_MS);
      return;
    }
    pending.timer = setTimeout(() => {
      pending.timer = null;
      flush();
    }, VISIBLE_STREAM_BODY_FLUSH_DELAY_MS);
  }

  private flushVisibleStreamStateNow(
    sessionId: string,
    streamState: StoreState,
    activeStreamSessionIds: string[],
    options: VisibleStreamStateOptions = {},
  ) {
    this.clearPendingVisibleStreamFlush(sessionId);
    if (this.store.getState().currentSessionId !== sessionId) {
      return;
    }
    this.applyVisibleStreamState(streamState, activeStreamSessionIds, options);
  }

  private clearPendingVisibleStreamFlush(sessionId: string) {
    const pending = this.pendingVisibleStreamFlushes.get(sessionId);
    if (!pending) {
      return;
    }
    if (pending.timer) {
      clearTimeout(pending.timer);
    }
    if (typeof window !== "undefined") {
      if (pending.frame !== null && typeof window.cancelAnimationFrame === "function") {
        window.cancelAnimationFrame(pending.frame);
      }
    }
    this.pendingVisibleStreamFlushes.delete(sessionId);
  }

  private clearAllPendingVisibleStreamFlushes() {
    for (const sessionId of Array.from(this.pendingVisibleStreamFlushes.keys())) {
      this.clearPendingVisibleStreamFlush(sessionId);
    }
  }

  private async createFreshSession() {
    if (this.createSessionPromise) {
      return this.createSessionPromise;
    }

    const pending = (async () => {
      const activeProjectKey = this.store.getState().activeProjectKey;
      const created = activeProjectKey
        ? (await createProjectWorkspaceSession(activeProjectKey, DEFAULT_SESSION_TITLE)).session
        : await createSession(DEFAULT_SESSION_TITLE);
      const conversationActiveEnvironment =
        this.activeEnvironmentForSession(created)
        ?? this.store.getState().conversationActiveEnvironment
        ?? this.defaultActiveTaskEnvironment();
      const permissionMode = this.permissionModeForSession(created.id, { ...this.store.getState(), sessions: [created] }, DEFAULT_PERMISSION_MODE);
      this.store.setState((prev) => this.withVisibleEditorContextForSession({
        ...prev,
        sessions: [
          {
            ...created,
            conversation_state: this.conversationStateWithPermissionMode(created.conversation_state, permissionMode),
          },
          ...prev.sessions.filter((session) => session.id !== created.id),
        ],
        projectSessions: activeProjectKey
          ? [
              {
                ...created,
                conversation_state: this.conversationStateWithPermissionMode(created.conversation_state, permissionMode),
              },
              ...prev.projectSessions.filter((session) => session.id !== created.id),
            ]
          : prev.projectSessions,
        currentSessionId: created.id,
        activeSessionScope: created.scope ?? null,
        activeSessionRef: {
          sessionId: created.id,
          ...(created.scope ? { scope: created.scope } : {}),
          poolKey: MAIN_CHAT_POOL_KEY,
        },
        conversationActiveEnvironment,
        permissionMode,
        messages: [],
        tokenStats: null
      }, created.id));
      rememberSessionRef({
        sessionId: created.id,
        ...(created.scope ? { scope: created.scope } : {}),
        poolKey: MAIN_CHAT_POOL_KEY,
      });
      this.persistCurrentSessionRef({
        sessionId: created.id,
        ...(created.scope ? { scope: created.scope } : {}),
        poolKey: MAIN_CHAT_POOL_KEY,
      });
      this.store.setState((prev) => this.clearSessionActivityFor(prev, created.id));
      await setSessionPermissionMode(created.id, permissionMode).catch((error) => {
        console.debug("[workspace-runtime] default permission mode persist skipped", {
          event: "conversation_permission_mode_default_persist_failed",
          error: this.errorMessage(error, "默认权限模式写入失败。"),
        });
      });
      this.projectPermissionModeToRuntime(permissionMode);
      await this.persistActiveTaskEnvironment(created.id, conversationActiveEnvironment).catch((error) => {
        console.debug("[workspace-runtime] default active task environment persist skipped", {
          event: "conversation_active_environment_default_persist_failed",
          error: this.errorMessage(error, "默认任务环境写入失败。"),
        });
      });
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
    const createdScope = this.sessionScopeForSession(sessionId);
    const createdRef: SessionRef = {
      sessionId,
      ...(createdScope ? { scope: createdScope } : {}),
      poolKey: MAIN_CHAT_POOL_KEY,
    };
    this.store.setState((prev) => this.withVisibleEditorContextForSession({
      ...prev,
      currentSessionId: sessionId,
      activeSessionScope: createdScope ?? null,
      activeSessionRef: createdRef,
      messages: [],
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: null,
      tokenStats: null
    }, sessionId));
    rememberSessionRef(createdRef);
    this.persistCurrentSessionRef(createdRef);
    this.store.setState((prev) => this.clearSessionActivityFor(prev, sessionId));
    const activeProjectKey = this.store.getState().activeProjectKey;
    if (activeProjectKey) {
      await this.refreshProjectSessions(activeProjectKey).catch((error) => {
        this.noteSessionRefreshFailure(error);
      });
    } else {
      await this.refreshMainSessionPool().catch((error) => {
        this.noteSessionRefreshFailure(error);
      });
    }
  }

  private async selectSession(ref: SessionRef) {
    const normalized = this.normalizeSessionRef(ref, this.store.getState());
    if (!normalized.sessionId) {
      return;
    }
    const restoredFromStreamCache = this.applySelectedSessionShell(normalized.sessionId, normalized);
    if (restoredFromStreamCache) {
      return;
    }
    const reattached = await this.reattachChatRunForSession(normalized.sessionId);
    if (reattached) {
      return;
    }
    await this.refreshSessionDetails(normalized.sessionId).catch(() => undefined);
    await this.hydrateLatestOrchestrationSnapshot(normalized.sessionId).catch(() => false);
  }

  private sessionScopeForSession(sessionId: string): Partial<SessionScope> | undefined {
    const state = this.store.getState();
    if (state.activeSessionRef?.sessionId === sessionId) {
      return state.activeSessionRef.scope ?? undefined;
    }
    if (state.currentSessionId === sessionId && state.activeSessionScope) {
      return state.activeSessionScope;
    }
    return state.sessions.find((session) => session.id === sessionId)?.scope ?? undefined;
  }

  private resolveSessionScope(sessionId: string, state: StoreState): Partial<SessionScope> | null {
    return state.sessions.find((session) => session.id === sessionId)?.scope
      ?? (state.currentSessionId === sessionId ? state.activeSessionScope : null);
  }

  private normalizeSessionScope(scope: Partial<SessionScope> | null | undefined): Partial<SessionScope> | undefined {
    const workspaceView = String(scope?.workspace_view || "").trim();
    const taskEnvironmentId = String(scope?.task_environment_id || "").trim();
    const projectId = String(scope?.project_id || "").trim();
    if (!workspaceView && !taskEnvironmentId && !projectId) {
      return undefined;
    }
    return {
      ...(workspaceView ? { workspace_view: workspaceView } : {}),
      ...(taskEnvironmentId ? { task_environment_id: taskEnvironmentId } : {}),
      ...(projectId ? { project_id: projectId } : {}),
    };
  }

  private normalizeSessionRef(ref: SessionRef, state: StoreState): SessionRef {
    const sessionId = String(ref.sessionId || "").trim();
    const explicitScope = this.normalizeSessionScope(ref.scope);
    const inferredScope = !explicitScope
      ? this.normalizeSessionScope(this.resolveSessionScope(sessionId, state))
      : undefined;
    const scope = explicitScope ?? inferredScope;
    return {
      sessionId,
      scope,
      poolKey: ref.poolKey ?? sessionPoolKeyForScope(scope),
    };
  }

  private shouldUseConversationEnvironment(ref: Pick<SessionRef, "scope" | "poolKey"> | undefined) {
    const poolKey = ref?.poolKey ?? sessionPoolKeyForScope(ref?.scope);
    return poolKey === MAIN_CHAT_POOL_KEY;
  }

  private normalizePermissionMode(mode: string | null | undefined): PermissionMode {
    const normalized = String(mode || "").trim();
    return normalized || DEFAULT_PERMISSION_MODE;
  }

  private permissionModeFromConversationState(conversationState: SessionSummary["conversation_state"] | null | undefined) {
    return this.normalizePermissionMode(conversationState?.permission_mode || DEFAULT_PERMISSION_MODE);
  }

  private permissionModeForSession(
    sessionId: string | null | undefined,
    state: StoreState,
    fallback: string | null | undefined = DEFAULT_PERMISSION_MODE,
  ) {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return this.normalizePermissionMode(fallback);
    }
    const selectedSession = state.sessions.find((session) => session.id === normalizedSessionId);
    if (selectedSession?.conversation_state) {
      return this.permissionModeFromConversationState(selectedSession.conversation_state);
    }
    if (state.currentSessionId === normalizedSessionId && state.permissionMode) {
      return this.normalizePermissionMode(state.permissionMode);
    }
    return this.normalizePermissionMode(fallback);
  }

  private conversationStateWithPermissionMode(
    conversationState: SessionSummary["conversation_state"] | null | undefined,
    permissionMode: PermissionMode,
  ): NonNullable<SessionSummary["conversation_state"]> {
    return {
      ...(conversationState ?? {}),
      permission_mode: this.normalizePermissionMode(permissionMode),
      authority: conversationState?.authority || "sessions.conversation_state",
    };
  }

  private projectPermissionModeToRuntime(permissionMode: PermissionMode) {
    const mode = this.normalizePermissionMode(permissionMode);
    void setRuntimePermissionMode(mode)
      .then((result) => {
        this.store.setState((prev) => ({
          ...prev,
          supportedPermissionModes: Array.isArray(result.supported_modes) && result.supported_modes.length
            ? result.supported_modes.map(String)
            : prev.supportedPermissionModes,
        }));
      })
      .catch((error) => {
        console.debug("[workspace-runtime] permission mode projection skipped", {
          event: "permission_mode_projection_failed",
          mode,
          error: this.errorMessage(error, "权限模式投影失败。"),
        });
      });
  }

  private taskEnvironmentCatalogItem(
    taskEnvironmentId: string,
    catalog = this.store.getState().taskEnvironmentCatalog,
  ) {
    const normalized = String(taskEnvironmentId || "").trim();
    if (!normalized) {
      return null;
    }
    return catalog?.environments.find((item) => taskEnvironmentIdOf(item) === normalized) ?? null;
  }

  private visibleTaskEnvironmentCatalogItem(
    taskEnvironmentId: string,
    catalog = this.store.getState().taskEnvironmentCatalog,
  ) {
    const item = this.taskEnvironmentCatalogItem(taskEnvironmentId, catalog);
    return item && isCatalogEnvironmentVisible(item) ? item : null;
  }

  private taskEnvironmentRegistryLabel(
    taskEnvironmentId: string,
    catalog = this.store.getState().taskEnvironmentCatalog,
  ) {
    return taskEnvironmentLabelOf(this.taskEnvironmentCatalogItem(taskEnvironmentId, catalog));
  }

  private taskEnvironmentLabel(
    taskEnvironmentId: string,
    catalog = this.store.getState().taskEnvironmentCatalog,
  ) {
    return this.taskEnvironmentRegistryLabel(taskEnvironmentId, catalog) || taskEnvironmentId;
  }

  private normalizeActiveTaskEnvironment(
    activeEnvironment: Partial<NonNullable<StoreState["conversationActiveEnvironment"]>> | null | undefined,
    catalog = this.store.getState().taskEnvironmentCatalog,
  ): StoreState["conversationActiveEnvironment"] {
    const taskEnvironmentId = String(
      activeEnvironment?.task_environment_id
      || (activeEnvironment as Record<string, unknown> | null | undefined)?.environment_id
      || ""
    ).trim();
    if (!taskEnvironmentId) {
      return null;
    }
    if (catalog?.environments.length && !this.visibleTaskEnvironmentCatalogItem(taskEnvironmentId, catalog)) {
      return null;
    }
    const registryLabel = this.taskEnvironmentRegistryLabel(taskEnvironmentId, catalog);
    return {
      task_environment_id: taskEnvironmentId,
      environment_label: taskEnvironmentDisplayName(
        taskEnvironmentId,
        String(registryLabel || activeEnvironment?.environment_label || "").trim(),
      ),
      source: String(activeEnvironment?.source || "conversation").trim() || "conversation",
      updated_at: Number(activeEnvironment?.updated_at || Date.now() / 1000),
      authority: String(activeEnvironment?.authority || "frontend.conversation_active_task_environment"),
    };
  }

  private rememberedTaskEnvironmentId() {
    const remembered = storageGet(LAST_ACTIVE_TASK_ENVIRONMENT_KEY);
    if (!remembered || GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(remembered)) {
      return "";
    }
    return this.visibleTaskEnvironmentCatalogItem(remembered) ? remembered : "";
  }

  private rememberTaskEnvironment(activeEnvironment: StoreState["conversationActiveEnvironment"]) {
    const taskEnvironmentId = String(activeEnvironment?.task_environment_id || "").trim();
    if (!taskEnvironmentId || GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(taskEnvironmentId)) {
      return;
    }
    storageSet(LAST_ACTIVE_TASK_ENVIRONMENT_KEY, taskEnvironmentId);
  }

  private activeTaskEnvironmentWithRememberedDefault(
    activeEnvironment: StoreState["conversationActiveEnvironment"],
  ): StoreState["conversationActiveEnvironment"] {
    const activeId = String(activeEnvironment?.task_environment_id || "").trim();
    const rememberedId = this.rememberedTaskEnvironmentId();
    if (!activeEnvironment || !rememberedId || rememberedId === activeId) {
      return activeEnvironment;
    }
    if (activeId === GENERAL_TASK_ENVIRONMENT_ID) {
      return {
        task_environment_id: rememberedId,
        environment_label: this.taskEnvironmentLabel(rememberedId),
        source: "workspace-mode",
        updated_at: Date.now() / 1000,
        authority: "frontend.conversation_active_task_environment",
      };
    }
    return activeEnvironment;
  }

  private defaultActiveTaskEnvironment(source = "conversation"): NonNullable<StoreState["conversationActiveEnvironment"]> {
    const rememberedId = this.rememberedTaskEnvironmentId();
    const defaultId = rememberedId || (this.taskEnvironmentCatalogItem(GENERAL_TASK_ENVIRONMENT_ID)
      ? GENERAL_TASK_ENVIRONMENT_ID
      : taskEnvironmentIdOf(this.store.getState().taskEnvironmentCatalog?.environments.find(isCatalogEnvironmentVisible))
        || GENERAL_TASK_ENVIRONMENT_ID);
    return {
      task_environment_id: defaultId,
      environment_label: this.taskEnvironmentLabel(defaultId),
      source,
      updated_at: Date.now() / 1000,
      authority: "frontend.conversation_active_task_environment",
    };
  }

  private activeEnvironmentFromConversationState(
    conversationState: SessionSummary["conversation_state"] | null | undefined,
  ): StoreState["conversationActiveEnvironment"] {
    return this.activeTaskEnvironmentWithRememberedDefault(
      this.normalizeActiveTaskEnvironment(conversationState?.active_task_environment),
    );
  }

  private activeEnvironmentForSession(
    session: Pick<SessionSummary, "conversation_state"> | null | undefined,
  ): StoreState["conversationActiveEnvironment"] {
    return this.activeEnvironmentFromConversationState(session?.conversation_state);
  }

  private async persistActiveTaskEnvironment(
    sessionId: string,
    activeEnvironment: NonNullable<StoreState["conversationActiveEnvironment"]>,
  ) {
    const state = this.store.getState();
    const sessionScope = this.sessionScopeForSession(sessionId);
    if (String(sessionScope?.workspace_view || "").trim() === "task_environment") {
      return;
    }
    if (state.activeSessionRef?.sessionId === sessionId && !this.shouldUseConversationEnvironment(state.activeSessionRef)) {
      return;
    }
    const conversationState = await setSessionActiveTaskEnvironment(
      sessionId,
      {
        task_environment_id: activeEnvironment.task_environment_id,
        environment_label: activeEnvironment.environment_label,
        source: activeEnvironment.source || "conversation",
      },
      sessionScope,
    );
    const nextActive = this.activeEnvironmentFromConversationState(conversationState) ?? activeEnvironment;
    this.rememberTaskEnvironment(nextActive);
    this.store.setState((prev) => ({
      ...prev,
      conversationActiveEnvironment: prev.currentSessionId === sessionId ? nextActive : prev.conversationActiveEnvironment,
      sessions: prev.sessions.map((session) => session.id === sessionId
        ? {
            ...session,
            conversation_state: conversationState.permission_mode
              ? conversationState
              : this.conversationStateWithPermissionMode(conversationState, this.permissionModeForSession(sessionId, prev)),
          }
        : session
      ),
    }));
  }

  private applySelectedSessionShell(sessionId: string, ref?: Pick<SessionRef, "scope" | "poolKey">) {
    const normalized = this.normalizeSessionRef({ sessionId, ...ref }, this.store.getState());
    if (!normalized.sessionId) {
      return false;
    }
    rememberSessionRef(normalized);
    this.persistCurrentSessionRef(normalized);
    const streamingCache = this.streamingSessionCache.get(normalized.sessionId);
    if (this.store.getState().activeStreamSessionIds.includes(normalized.sessionId) && streamingCache) {
      const selectedSession = this.store.getState().sessions.find((session) => session.id === normalized.sessionId);
      const conversationActiveEnvironment = this.shouldUseConversationEnvironment(normalized)
        ? this.activeEnvironmentForSession(selectedSession) ?? this.store.getState().conversationActiveEnvironment ?? this.defaultActiveTaskEnvironment()
        : this.store.getState().conversationActiveEnvironment;
      const permissionMode = this.permissionModeForSession(normalized.sessionId, this.store.getState());
      this.store.setState((prev) => this.withVisibleEditorContextForSession({
        ...prev,
        currentSessionId: normalized.sessionId,
        activeSessionScope: normalized.scope ?? null,
        activeSessionRef: normalized,
        conversationActiveEnvironment,
        permissionMode,
        messages: streamingCache.messages,
        activeProjectionsByKey: streamingCache.activeProjectionsByKey,
        orchestrationSnapshot: streamingCache.orchestrationSnapshot,
        activeTurnSnapshot: streamingCache.activeTurnSnapshot,
        taskGraphLiveMonitor: null,
        tokenStats: null
      }, normalized.sessionId));
      this.store.setState((prev) => this.projectSelectedSessionActivity(prev, normalized.sessionId));
      this.projectPermissionModeToRuntime(permissionMode);
      void this.refreshWorkspaceTree().catch(() => undefined);
      return true;
    }
    const selectedSession = this.store.getState().sessions.find((session) => session.id === normalized.sessionId);
    const conversationActiveEnvironment = this.shouldUseConversationEnvironment(normalized)
      ? this.activeEnvironmentForSession(selectedSession) ?? this.store.getState().conversationActiveEnvironment ?? this.defaultActiveTaskEnvironment()
      : this.store.getState().conversationActiveEnvironment;
    const permissionMode = this.permissionModeForSession(normalized.sessionId, this.store.getState());
    this.store.setState((prev) => this.withVisibleEditorContextForSession({
      ...prev,
      currentSessionId: normalized.sessionId,
      activeSessionScope: normalized.scope ?? null,
      activeSessionRef: normalized,
      conversationActiveEnvironment,
      permissionMode,
      messages: [],
      activeProjectionsByKey: {},
      orchestrationSnapshot: null,
      activeTurnSnapshot: null,
      taskGraphLiveMonitor: null,
      tokenStats: null
    }, normalized.sessionId));
    this.store.setState((prev) => this.projectSelectedSessionActivity(prev, normalized.sessionId));
    this.projectPermissionModeToRuntime(permissionMode);
    void this.refreshWorkspaceTree().catch(() => undefined);
    return false;
  }

  private async reattachChatRunForSession(sessionId: string) {
    if (this.recoveringStreamSessionIds.has(sessionId)) {
      return true;
    }
    this.recoveringStreamSessionIds.add(sessionId);
    try {
      const latestRun = await getLatestChatRunForSession(sessionId, this.sessionScopeForSession(sessionId)).catch(() => undefined);
      if (this.store.getState().activeStreamSessionIds.includes(sessionId)) {
        if (latestRun === null) {
          this.releaseActiveChatStreamForSwitch(sessionId);
          clearChatStreamCursor(sessionId);
          await this.refreshSessionDetails(sessionId).catch(() => undefined);
          return false;
        }
        if (latestRun && !this.activeChatStreamMatchesRun(sessionId, latestRun)) {
          this.releaseActiveChatStreamForSwitch(sessionId);
          clearChatStreamCursor(sessionId);
        } else {
          if (!this.streamingSessionCache.has(sessionId) || this.visibleSessionNeedsHistoryHydration(sessionId)) {
            await this.refreshSessionDetails(sessionId).catch(() => undefined);
          }
          return true;
        }
      }
      let cursor = readChatStreamCursor(sessionId);
      if (latestRun?.stream_run_id && latestRun.stream_run_id !== cursor?.streamRunId) {
        cursor = {
          streamRunId: latestRun.stream_run_id,
          eventLogId: latestRun.event_log_id,
          lastEventOffset: -1,
          lastEventId: "",
        };
      }
      let streamRunId = cursor?.streamRunId || "";
      if (!streamRunId) {
        return false;
      }
      const cursorRun = latestRun?.stream_run_id === streamRunId
        ? latestRun
        : await getChatRun(streamRunId).catch(() => null);
      if (
        !cursorRun
        || cursorRun.session_id !== sessionId
        || cursorRun.is_reconnectable === false
      ) {
        clearChatStreamCursor(sessionId);
        return false;
      }
      if (this.chatRunCursorAlreadyReachedTerminal(cursorRun, cursor)) {
        clearChatStreamCursor(sessionId);
        await this.refreshSessionDetails(sessionId).catch(() => undefined);
        return false;
      }
      this.applyActiveTurnSnapshotFromChatRun(cursorRun);
      this.updateActiveChatStreamBinding(sessionId, this.chatRunBinding(cursorRun));
      await this.refreshSessionDetails(sessionId).catch(() => undefined);
      this.startRecoveredChatRunStream(sessionId, streamRunId, cursor, cursorRun);
      return true;
    } finally {
      this.recoveringStreamSessionIds.delete(sessionId);
    }
  }

  private visibleSessionNeedsHistoryHydration(sessionId: string) {
    const state = this.store.getState();
    return state.currentSessionId === sessionId && state.messages.length === 0;
  }

  private chatRunCursorAlreadyReachedTerminal(run: { terminal_event?: string; latest_event_offset?: number }, cursor: ChatStreamCursor | null) {
    const terminalEvent = String(run.terminal_event || "").trim();
    if (terminalEvent !== "turn_completed") {
      return false;
    }
    const latestOffset = Number(run.latest_event_offset ?? -1);
    const cursorOffset = Number(cursor?.lastEventOffset ?? -1);
    return Number.isFinite(latestOffset)
      && Number.isFinite(cursorOffset)
      && cursorOffset >= latestOffset;
  }

  private applyActiveTurnSnapshotFromChatRun(run: ChatRun | null | undefined) {
    if (!run) {
      return;
    }
    const hasSnapshotField = Object.prototype.hasOwnProperty.call(run, "active_turn_snapshot");
    const activeTurnSnapshot = this.activeTurnSnapshotFromPayload(run.active_turn_snapshot)
      ?? this.activeTurnSnapshotFromChatRunDiagnostics(run);
    if (!hasSnapshotField && !activeTurnSnapshot) {
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      activeTurnSnapshot,
    }));
  }

  private activeTurnSnapshotFromChatRunDiagnostics(run: ChatRun): ActiveTurnSnapshot | null {
    const diagnostics = run.diagnostics && typeof run.diagnostics === "object" && !Array.isArray(run.diagnostics)
      ? run.diagnostics
      : {};
    const turnId = runtimeText(diagnostics.active_turn_id)
      || runtimeText(diagnostics.public_anchor_turn_id);
    if (!turnId) {
      return null;
    }
    const taskRunId = runtimeText(diagnostics.runtime_task_run_id)
      || runtimeText(diagnostics.task_run_id)
      || runtimeText(diagnostics.public_anchor_task_run_id);
    const state = this.activeTurnStateFromPayload(diagnostics.active_turn_state)
      ?? (taskRunId ? "running_task" : "model_turn");
    return {
      turn_id: turnId,
      turn_run_id: runtimeText(diagnostics.runtime_turn_run_id)
        || runtimeText(diagnostics.turn_run_id)
        || undefined,
      task_run_id: taskRunId || undefined,
      state,
      updated_at: Date.now() / 1000,
    };
  }

  private activeTurnSnapshotFromPayload(value: unknown): ActiveTurnSnapshot | null {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    const payload = value as Record<string, unknown>;
    const turnId = String(payload.turn_id ?? "").trim();
    if (!turnId) {
      return null;
    }
    return {
      turn_id: turnId,
      turn_run_id: String(payload.turn_run_id ?? "").trim() || undefined,
      task_run_id: String(payload.bound_task_run_id ?? payload.task_run_id ?? "").trim() || undefined,
      state: this.activeTurnStateFromPayload(payload.state),
      updated_at: Number(payload.updated_at ?? 0) || undefined,
    };
  }

  private activeTurnStateFromPayload(value: unknown): ActiveTurnState | undefined {
    const normalized = String(value ?? "").trim();
    return ACTIVE_TURN_STATES.has(normalized) ? normalized as ActiveTurnState : undefined;
  }

  private chatRunBinding(run: ChatRun | null | undefined): ActiveChatStreamBinding | null {
    if (!run) {
      return null;
    }
    const diagnostics: Record<string, unknown> = run.diagnostics && typeof run.diagnostics === "object" && !Array.isArray(run.diagnostics)
      ? run.diagnostics
      : {};
    const activeTurn = run.active_turn_snapshot ?? null;
    const streamRunId = runtimeText(run.stream_run_id);
    const taskRunId = runtimeText(activeTurn?.bound_task_run_id)
      || runtimeText(activeTurn?.task_run_id)
      || runtimeText(diagnostics.runtime_task_run_id)
      || runtimeText(diagnostics.task_run_id)
      || runtimeText(diagnostics.public_anchor_task_run_id);
    const turnId = runtimeText(activeTurn?.turn_id)
      || runtimeText(diagnostics.active_turn_id)
      || runtimeText(diagnostics.public_anchor_turn_id);
    if (!streamRunId) {
      return null;
    }
    return { streamRunId, taskRunId, turnId };
  }

  private eventChatStreamBinding(data: Record<string, unknown>, fallbackStreamRunId = ""): Partial<ActiveChatStreamBinding> {
    const frame = data.public_projection_frame && typeof data.public_projection_frame === "object" && !Array.isArray(data.public_projection_frame)
      ? data.public_projection_frame as Record<string, unknown>
      : {};
    const frameAnchor = frame.anchor && typeof frame.anchor === "object" && !Array.isArray(frame.anchor)
      ? frame.anchor as Record<string, unknown>
      : {};
    return {
      streamRunId: runtimeText(data.stream_run_id)
        || runtimeText(data.streamRunId)
        || runtimeText(frameAnchor.stream_run_id)
        || fallbackStreamRunId,
      taskRunId: runtimeText(data.runtime_task_run_id)
        || runtimeText(data.task_run_id)
        || runtimeText(data.bound_task_run_id)
        || runtimeText(frameAnchor.task_run_id),
      turnId: runtimeText(data.active_turn_id)
        || runtimeText(data.turn_id)
        || runtimeText(frameAnchor.turn_id),
    };
  }

  private updateActiveChatStreamBinding(
    sessionId: string,
    patch: Partial<ActiveChatStreamBinding> | null | undefined,
  ) {
    if (!sessionId || !patch) {
      return;
    }
    const current = this.activeChatStreamBindings.get(sessionId) ?? { streamRunId: "", taskRunId: "", turnId: "" };
    const next = {
      streamRunId: patch.streamRunId || current.streamRunId,
      taskRunId: patch.taskRunId || current.taskRunId,
      turnId: patch.turnId || current.turnId,
    };
    if (!next.streamRunId && !next.taskRunId && !next.turnId) {
      return;
    }
    this.activeChatStreamBindings.set(sessionId, next);
  }

  private nextChatStreamEpoch(sessionId: string) {
    const next = (this.chatStreamEpochBySession.get(sessionId) ?? 0) + 1;
    this.chatStreamEpochBySession.set(sessionId, next);
    return next;
  }

  private isCurrentChatStreamEpoch(sessionId: string, epoch: number) {
    return this.chatStreamEpochBySession.get(sessionId) === epoch;
  }

  private activeChatStreamMatchesRun(sessionId: string, run: ChatRun | null | undefined) {
    const current = this.activeChatStreamBindings.get(sessionId);
    const next = this.chatRunBinding(run);
    if (!current || !next) {
      return true;
    }
    if (current.streamRunId && next.streamRunId && current.streamRunId !== next.streamRunId) {
      return false;
    }
    if (current.taskRunId && next.taskRunId && current.taskRunId !== next.taskRunId) {
      return false;
    }
    if (current.turnId && next.turnId && current.turnId !== next.turnId) {
      return false;
    }
    return true;
  }

  private releaseActiveChatStreamForSwitch(sessionId: string) {
    this.nextChatStreamEpoch(sessionId);
    this.removedStreamingSessionIds.add(sessionId);
    this.clearPendingVisibleStreamFlush(sessionId);
    this.streamAbortControllers.get(sessionId)?.abort();
    this.streamAbortControllers.delete(sessionId);
    this.streamingSessionCache.delete(sessionId);
    this.activeChatStreamBindings.delete(sessionId);
    this.store.setState((prev) => this.removeActiveStreamSession(prev, sessionId));
  }

  private recordProjectionCommitAck(sessionId: string, data: Record<string, unknown>) {
    const frame = projectionFrameFromRecord(data.public_projection_frame);
    if (frame?.op !== "commit_ack") {
      return;
    }
    const commitKey = this.projectionCommitKey(frame, sessionId);
    if (!commitKey || this.hydratedProjectionCommitKeys.has(commitKey)) {
      return;
    }
    this.pendingProjectionCommitHydrates.set(sessionId, commitKey);
    if (!this.store.getState().activeStreamSessionIds.includes(sessionId)) {
      void this.hydrateCommittedProjectionIfPending(sessionId).catch(() => undefined);
    }
  }

  private async hydrateCommittedProjectionIfPending(sessionId: string) {
    const commitKey = this.pendingProjectionCommitHydrates.get(sessionId);
    if (!commitKey || this.hydratedProjectionCommitKeys.has(commitKey)) {
      return false;
    }
    if (this.store.getState().activeStreamSessionIds.includes(sessionId)) {
      return false;
    }
    if (this.store.getState().currentSessionId !== sessionId) {
      return false;
    }
    await this.refreshSessionDetails(sessionId);
    this.hydratedProjectionCommitKeys.add(commitKey);
    if (this.pendingProjectionCommitHydrates.get(sessionId) === commitKey) {
      this.pendingProjectionCommitHydrates.delete(sessionId);
    }
    return true;
  }

  private projectionCommitKey(frame: PublicProjectionFrame, sessionId: string) {
    const commit = (frame.commit ?? {}) as Record<string, unknown>;
    return [
      String(frame.anchor?.session_id || sessionId || "").trim(),
      String(frame.anchor?.turn_id || "").trim(),
      String(frame.anchor?.task_run_id || "").trim(),
      String(commit.commit_event_offset ?? commit.event_offset ?? "").trim(),
      String(commit.content_sha256 || "").trim(),
      String(frame.frame_id || frame.projection_id || "").trim(),
    ].join("|");
  }

  private recoveredAssistantMessageId(streamRunId: string, run: ChatRun | null) {
    const state = this.store.getState();
    const activeTurn = run?.active_turn_snapshot ?? null;
    const turnId = String(activeTurn?.turn_id ?? "").trim();
    const turnRunId = String(activeTurn?.turn_run_id ?? "").trim();
    const taskRunId = String(activeTurn?.bound_task_run_id ?? activeTurn?.task_run_id ?? "").trim();
    for (let index = state.messages.length - 1; index >= 0; index -= 1) {
      const message = state.messages[index];
      if (message.role !== "assistant") {
        continue;
      }
      if (streamRunId && (message.sourceStreamRunId === streamRunId || message.sourceRunId === streamRunId)) {
        return message.id;
      }
      if (turnRunId && message.sourceTurnRunId === turnRunId) {
        return message.id;
      }
      if (taskRunId && message.sourceTaskRunId === taskRunId) {
        return message.id;
      }
      if (turnId && message.sourceTurnId === turnId) {
        return message.id;
      }
    }
    return "";
  }

  private messagesWithRecoveredAssistantShell(
    messages: Message[],
    assistantId: string,
    streamRunId: string,
    run: ChatRun | null,
  ) {
    if (messages.some((message) => message.role === "assistant" && message.id === assistantId)) {
      return messages;
    }
    const activeTurn = run?.active_turn_snapshot ?? null;
    const diagnostics = run?.diagnostics ?? {};
    const turnId = runtimeText(activeTurn?.turn_id)
      || runtimeText(diagnostics.active_turn_id)
      || runtimeText(diagnostics.public_anchor_turn_id);
    const turnRunId = runtimeText(activeTurn?.turn_run_id)
      || runtimeText(diagnostics.runtime_turn_run_id)
      || runtimeText(diagnostics.turn_run_id);
    const taskRunId = runtimeText(activeTurn?.bound_task_run_id)
      || runtimeText(activeTurn?.task_run_id)
      || runtimeText(diagnostics.runtime_task_run_id)
      || runtimeText(diagnostics.task_run_id)
      || runtimeText(diagnostics.public_anchor_task_run_id);
    const userIndex = turnId
      ? messages.findIndex((message) => message.role === "user" && message.sourceTurnId === turnId)
      : -1;
    const userMessage = userIndex >= 0 ? messages[userIndex] : null;
    const assistantMessage: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      toolCalls: [],
      retrievals: [],
      runtimeProgress: [],
      stageStatus: "",
      sourceIndex: userMessage && typeof userMessage.sourceIndex === "number"
        ? userMessage.sourceIndex + 0.5
        : this.nextMessageSourceIndex(messages),
      sourceTurnId: turnId || undefined,
      sourceStreamRunId: streamRunId || undefined,
      sourceTaskRunId: taskRunId || undefined,
      sourceTurnRunId: turnRunId || undefined,
    };
    if (userIndex < 0) {
      return [...messages, assistantMessage];
    }
    return [
      ...messages.slice(0, userIndex + 1),
      assistantMessage,
      ...messages.slice(userIndex + 1),
    ];
  }

  private startRecoveredChatRunStream(
    sessionId: string,
    streamRunId: string,
    cursor: ChatStreamCursor | null,
    run: ChatRun | null = null,
  ) {
    if (this.store.getState().activeStreamSessionIds.includes(sessionId)) {
      return;
    }
    const streamEpoch = this.nextChatStreamEpoch(sessionId);
    const abortController = new AbortController();
    this.streamAbortControllers.set(sessionId, abortController);
    this.removedStreamingSessionIds.delete(sessionId);
    this.stoppedStreamingSessionIds.delete(sessionId);
    const shouldDeriveTitleAfterCompletion = this.shouldDeriveSessionTitleFromSummary(sessionId);

    const existingAssistantId = this.recoveredAssistantMessageId(streamRunId, run);
    const assistantId = existingAssistantId || makeId();
    const messages = existingAssistantId
      ? this.store.getState().messages
      : this.messagesWithRecoveredAssistantShell(this.store.getState().messages, assistantId, streamRunId, run);
    const activeStreamSessionIds = this.store.getState().activeStreamSessionIds.includes(sessionId)
      ? this.store.getState().activeStreamSessionIds
      : [...this.store.getState().activeStreamSessionIds, sessionId];
    const recoveryActivityDetail = recoveredChatRunActivityDetail();
    let streamState: StoreState = {
      ...this.store.getState(),
      messages,
      orchestrationSnapshot: null,
      activeStreamSessionIds,
      isStreaming: activeStreamSessionIds.length > 0,
      sessionActivity: {
        level: "running",
        title: "恢复输出流",
        detail: recoveryActivityDetail,
        event: "stream_cursor_restore_started",
        receipt: {
          level: "running",
          title: "恢复输出流",
          body: recoveryActivityDetail,
          debug: { event: "stream_cursor_restore_started" },
        },
        updatedAt: Date.now(),
      },
    };
    streamState = this.captureSessionActivity(streamState, sessionId);
    let transitionSession: StreamSession = { assistantId };
    this.streamingSessionCache.set(sessionId, {
      messages: streamState.messages,
      activeProjectionsByKey: streamState.activeProjectionsByKey,
      orchestrationSnapshot: streamState.orchestrationSnapshot,
      activeTurnSnapshot: streamState.activeTurnSnapshot,
    });
    this.updateActiveChatStreamBinding(
      sessionId,
      this.chatRunBinding(run) ?? { streamRunId, taskRunId: "", turnId: "" },
    );
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
              if (!this.isCurrentChatStreamEpoch(sessionId, streamEpoch)) {
                return;
              }
              if (this.removedStreamingSessionIds.has(sessionId)) {
                return;
              }
              if (this.stoppedStreamingSessionIds.has(sessionId)) {
                return;
              }
              this.updateActiveChatStreamBinding(sessionId, this.eventChatStreamBinding(data, streamRunId));
              const isCurrentStreamSession = this.store.getState().currentSessionId === sessionId;
              const baseState = isCurrentStreamSession && !this.pendingVisibleStreamFlushes.has(sessionId)
                ? this.store.getState()
                : streamState;
              const transition = reduceStreamEvent(baseState, transitionSession, event, data);
              this.recordProjectionCommitAck(sessionId, data);
              transitionSession = transition.session;
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
                activeProjectionsByKey: streamState.activeProjectionsByKey,
                orchestrationSnapshot: streamState.orchestrationSnapshot,
                activeTurnSnapshot: streamState.activeTurnSnapshot,
              });
              if (isCurrentStreamSession) {
                this.presentVisibleStreamState(sessionId, streamState, currentActiveStreamSessionIds, event, data);
              }
              if (streamEventStopsActiveWork(event, data)) {
                const eventBinding = this.eventChatStreamBinding(data, streamRunId);
                this.releaseStoppedChatStreamBoundary(sessionId, "active_work_stopped", {
                  taskRunId: eventBinding.taskRunId,
                  turnId: eventBinding.turnId,
                });
              }
            }
          },
          {
            signal: abortController.signal,
            initialCursor: cursor,
            replayFromStart: true,
          }
        );
        streamEndedWithError = streamResult.terminalStatus === "failed";
        if (streamResult.terminalStatus === "stopped") {
          this.stoppedStreamingSessionIds.add(sessionId);
        }
      } catch (error) {
        if (!this.isCurrentChatStreamEpoch(sessionId, streamEpoch)) {
          return;
        }
        if (this.removedStreamingSessionIds.has(sessionId)) {
          return;
        }
        streamEndedWithError = true;
        const streamWasStopped = this.stoppedStreamingSessionIds.has(sessionId);
        const transition = reduceStreamEvent(
          this.store.getState().currentSessionId === sessionId ? this.store.getState() : streamState,
          transitionSession,
          streamWasStopped ? "stopped" : "error",
          streamWasStopped
            ? { reason: "user_stopped" }
            : { error: error instanceof Error ? error.message : "unknown error" }
        );
        transitionSession = transition.session;
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
          activeProjectionsByKey: streamState.activeProjectionsByKey,
          orchestrationSnapshot: streamState.orchestrationSnapshot,
          activeTurnSnapshot: streamState.activeTurnSnapshot,
        });
        if (this.store.getState().currentSessionId === sessionId) {
          this.flushVisibleStreamStateNow(sessionId, streamState, currentActiveStreamSessionIds);
        }
      } finally {
        if (!this.isCurrentChatStreamEpoch(sessionId, streamEpoch)) {
          return;
        }
        this.flushVisibleStreamStateNow(sessionId, streamState, this.store.getState().activeStreamSessionIds);
        this.streamAbortControllers.delete(sessionId);
        const currentBinding = this.activeChatStreamBindings.get(sessionId);
        if (!currentBinding || currentBinding.streamRunId === streamRunId) {
          this.activeChatStreamBindings.delete(sessionId);
        }
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
        if (!streamSessionWasRemoved) {
          await this.hydrateCommittedProjectionIfPending(sessionId);
        }
        if (
          shouldDeriveTitleAfterCompletion
          && !streamSessionWasRemoved
          && !streamSessionWasStopped
          && !streamEndedWithError
        ) {
          this.requestSummarySessionTitleInBackground(sessionId);
        }
        if (
          !streamSessionWasRemoved
          && !streamSessionWasStopped
          && !streamEndedWithError
          && this.store.getState().currentSessionId === sessionId
        ) {
          await this.hydrateLatestOrchestrationSnapshot(sessionId);
          await this.refreshRunMonitor();
        }
        this.refreshMainSessionPoolInBackground();
        this.scheduleSessionRefreshes();
        void this.flushQueuedUserInputsForSession(sessionId);
      }
    })();
  }

  private async sendMessage(
    value: string,
    options: {
      queuedUserMessageId?: string;
      files?: File[];
      activeTurnInputPolicy?: "auto" | "steer";
      expectedActiveTurnId?: string;
      taskRunId?: string;
    } = {},
  ) {
    const files = (options.files ?? []).filter(Boolean);
    const hasFiles = files.length > 0;
    const trimmed = value.trim() || (hasFiles ? "请识别图片中的文字。" : "");
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
    const activeStreamState = this.store.getState();
    if (hasFiles && activeStreamState.activeStreamSessionIds.includes(sessionId)) {
      const message = "当前运行中暂不支持追加图片，请等待本轮结束。";
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "error",
          title: "图片暂不能排队发送",
          detail: message,
          event: "chat_attachment_active_stream_rejected",
          receipt: {
            level: "error",
            title: "图片暂不能排队发送",
            body: message,
            debug: {
              event: "chat_attachment_active_stream_rejected",
            },
          },
          updatedAt: Date.now(),
        },
      }));
      throw new Error(message);
    }
    let attachments: ChatAttachment[] = [];
    if (hasFiles) {
      try {
        attachments = await this.uploadChatAttachmentsForSession(sessionId, files);
      } catch (error) {
        this.store.setState((prev) => ({
          ...prev,
          sessionActivity: {
            level: "error",
            title: "图片上传失败",
            detail: this.errorMessage(error, "无法上传图片，请确认文件格式和后端服务。"),
            event: "chat_attachment_upload_failed",
            receipt: {
              level: "error",
              title: "图片上传失败",
              body: this.errorMessage(error, "无法上传图片，请确认文件格式和后端服务。"),
              debug: {
                event: "chat_attachment_upload_failed",
              },
            },
            updatedAt: Date.now(),
          },
        }));
        throw error;
      }
    }
    if (activeStreamState.activeStreamSessionIds.includes(sessionId)) {
      if (this.activeTaskSteerStreamSessionIds.has(sessionId)) {
        if (options.queuedUserMessageId) {
          const queued = this.queuedUserInputsBySession.get(sessionId) ?? [];
          this.queuedUserInputsBySession.set(sessionId, [
            this.queuedUserInputForSession(sessionId, trimmed, options.queuedUserMessageId),
            ...queued,
          ]);
          return;
        }
        this.enqueueUserInputForSession(sessionId, trimmed);
        return;
      }
      if (this.shouldQueueActiveTurnInput(activeStreamState, sessionId)) {
        await this.submitActiveTurnSteerDuringActiveStream(sessionId, trimmed, options);
        return;
      }
      if (options.queuedUserMessageId) {
        const queued = this.queuedUserInputsBySession.get(sessionId) ?? [];
        this.queuedUserInputsBySession.set(sessionId, [
          this.queuedUserInputForSession(sessionId, trimmed, options.queuedUserMessageId, {
            inputPolicy: options.activeTurnInputPolicy,
            expectedActiveTurnId: options.expectedActiveTurnId,
            taskRunId: options.taskRunId,
          }),
          ...queued,
        ]);
        return;
      }
      this.enqueueUserInputForSession(sessionId, trimmed);
      return;
    }
    const shouldDeriveTitleAfterCompletion = this.shouldDeriveSessionTitleFromSummary(sessionId);
    this.removedStreamingSessionIds.delete(sessionId);
    this.stoppedStreamingSessionIds.delete(sessionId);
    const streamEpoch = this.nextChatStreamEpoch(sessionId);
    const abortController = new AbortController();
    this.streamAbortControllers.set(sessionId, abortController);
    const imageGeneration = this.chatImageGenerationPayload(state);
    const isImageGenerationTurn = Boolean(imageGeneration);
    let streamEndedWithError = false;
    let completedStreamRunId = "";
    const preflightState = this.store.getState();
    const activeTurnSnapshotForTransition = preflightState.currentSessionId === sessionId
      ? preflightState.activeTurnSnapshot
      : null;
    const forcedSteerInput = options.activeTurnInputPolicy === "steer";
    const queueActiveTurnInput = forcedSteerInput || this.shouldQueueActiveTurnInput(preflightState, sessionId);
    const activeTurnInputPolicy = forcedSteerInput ? "steer" : this.activeTurnInputPolicyForSession(preflightState, sessionId);
    const expectedActiveTurnIdForRequest = activeTurnInputPolicy === "steer"
      ? options.expectedActiveTurnId || this.expectedActiveTurnIdForSession(preflightState, sessionId, options.taskRunId)
      : "";
    if (forcedSteerInput) {
      this.updateActiveChatStreamBinding(sessionId, {
        taskRunId: options.taskRunId || "",
        turnId: expectedActiveTurnIdForRequest,
      });
    }
    this.store.setState((prev) => ({
      ...prev,
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: queueActiveTurnInput ? prev.taskGraphLiveMonitor : null,
      orchestrationInspectorTarget: prev.orchestrationInspectorTarget?.source === "live-session"
        ? null
        : prev.orchestrationInspectorTarget,
    }));
    let transition = queueActiveTurnInput
      ? startQueuedActiveTurn(this.store.getState(), trimmed, { existingUserMessageId: options.queuedUserMessageId, attachments })
      : startStreamingTurn(this.store.getState(), trimmed, { existingUserMessageId: options.queuedUserMessageId, attachments });
    const nextSourceIndex = this.nextMessageSourceIndex(this.store.getState().messages);
    transition = {
      ...transition,
      state: {
        ...transition.state,
        messages: transition.state.messages.map((message) =>
          transition.session.userId && message.id === transition.session.userId
            ? { ...message, sourceIndex: nextSourceIndex }
            : transition.session.assistantId && message.id === transition.session.assistantId
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
      activeProjectionsByKey: streamState.activeProjectionsByKey,
      orchestrationSnapshot: streamState.orchestrationSnapshot,
      activeTurnSnapshot: streamState.activeTurnSnapshot,
    });
    this.addActiveStreamSession(sessionId);
    if (queueActiveTurnInput) {
      this.activeTaskSteerStreamSessionIds.add(sessionId);
    }
    if (!queueActiveTurnInput) {
      this.deferMonitorPollingForActiveStream();
    }
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
      const requestState = this.store.getState();
      const activeTurnForRequest = activeTurnSnapshotForTransition ?? (
        requestState.currentSessionId === sessionId ? requestState.activeTurnSnapshot : null
      );
      const expectedActiveTurnId = activeTurnInputPolicy === "steer"
        ? expectedActiveTurnIdForRequest
        : String(activeTurnForRequest?.turn_id ?? "");
      const permissionMode = this.permissionModeForSession(sessionId, requestState);
      const streamResult = await streamChat(
        {
          message: trimmed,
          session_id: sessionId,
          session_scope: this.sessionScopeForSession(sessionId),
          environment_binding: this.chatEnvironmentBindingPayload(requestState),
          model_selection: this.chatModelSelectionPayload(requestState),
          permission_mode: permissionMode,
          expected_active_turn_id: expectedActiveTurnId,
          active_turn_input_policy: activeTurnInputPolicy,
          editor_context: this.chatEditorContextPayload(requestState, sessionId),
          attachments,
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
            if (!this.isCurrentChatStreamEpoch(sessionId, streamEpoch)) {
              return;
            }
            if (this.removedStreamingSessionIds.has(sessionId)) {
              return;
            }
            if (this.stoppedStreamingSessionIds.has(sessionId)) {
              return;
            }
            this.updateActiveChatStreamBinding(sessionId, this.eventChatStreamBinding(data));
            const isCurrentStreamSession = this.store.getState().currentSessionId === sessionId;
            const baseState = isCurrentStreamSession && !this.pendingVisibleStreamFlushes.has(sessionId)
              ? this.store.getState()
              : streamState;
            transition = reduceStreamEvent(baseState, transition.session, event, data);
            this.recordProjectionCommitAck(sessionId, data);
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
              activeProjectionsByKey: streamState.activeProjectionsByKey,
              orchestrationSnapshot: streamState.orchestrationSnapshot,
              activeTurnSnapshot: streamState.activeTurnSnapshot,
            });
            if (isCurrentStreamSession) {
              this.presentVisibleStreamState(sessionId, streamState, currentActiveStreamSessionIds, event, data);
            }
            if (streamEventStopsActiveWork(event, data)) {
              const eventBinding = this.eventChatStreamBinding(data);
              this.releaseStoppedChatStreamBoundary(sessionId, "active_work_stopped", {
                taskRunId: eventBinding.taskRunId,
                turnId: eventBinding.turnId,
              });
            }
          }
        },
        { signal: abortController.signal }
      );
      completedStreamRunId = streamResult.streamRunId;
      streamEndedWithError = streamResult.terminalStatus === "failed";
      if (streamResult.terminalStatus === "stopped") {
        this.stoppedStreamingSessionIds.add(sessionId);
      }
    } catch (error) {
      if (!this.isCurrentChatStreamEpoch(sessionId, streamEpoch)) {
        return;
      }
      if (this.removedStreamingSessionIds.has(sessionId)) {
        return;
      }
      streamEndedWithError = true;
      const streamWasStopped = this.stoppedStreamingSessionIds.has(sessionId);
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
        activeProjectionsByKey: streamState.activeProjectionsByKey,
        orchestrationSnapshot: streamState.orchestrationSnapshot,
        activeTurnSnapshot: streamState.activeTurnSnapshot,
      });
      if (this.store.getState().currentSessionId === sessionId) {
        this.flushVisibleStreamStateNow(sessionId, streamState, currentActiveStreamSessionIds);
      }
    } finally {
      if (!this.isCurrentChatStreamEpoch(sessionId, streamEpoch)) {
        return;
      }
      this.flushVisibleStreamStateNow(sessionId, streamState, this.store.getState().activeStreamSessionIds);
      this.streamAbortControllers.delete(sessionId);
      this.activeTaskSteerStreamSessionIds.delete(sessionId);
      const currentBinding = this.activeChatStreamBindings.get(sessionId);
      if (!currentBinding || !completedStreamRunId || currentBinding.streamRunId === completedStreamRunId) {
        this.activeChatStreamBindings.delete(sessionId);
      }
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
      if (!streamSessionWasRemoved) {
        await this.hydrateCommittedProjectionIfPending(sessionId);
      }
      if (
        shouldDeriveTitleAfterCompletion
        && !streamSessionWasRemoved
        && !streamSessionWasStopped
        && !streamEndedWithError
      ) {
        this.requestSummarySessionTitleInBackground(sessionId);
      }
      if (
        !streamSessionWasRemoved
        && !streamSessionWasStopped
        && !streamEndedWithError
        && !isImageGenerationTurn
        && this.store.getState().currentSessionId === sessionId
      ) {
        await this.hydrateLatestOrchestrationSnapshot(sessionId);
        await this.refreshRunMonitor();
      }
      this.refreshMainSessionPoolInBackground();
      this.scheduleSessionRefreshes();
      void this.flushQueuedUserInputsForSession(sessionId);
    }
  }

  private stopCurrentStream() {
    const sessionId = this.store.getState().currentSessionId;
    const taskRunId = this.activeControllableTaskRunId();
    const expectedTurnId = taskRunId ? this.activeExpectedTurnIdForTaskRun(taskRunId) : "";
    this.releaseStoppedChatStreamBoundary(sessionId, "user_stopped", { taskRunId, turnId: expectedTurnId });
    if (taskRunId) {
      void this.stopTaskRunFromSystemInterrupt(taskRunId, expectedTurnId, "user_stop_from_chat_stream");
    }
  }

  private releaseStoppedChatStreamBoundary(
    sessionId: string | null | undefined,
    reason = "user_stopped",
    options: { abortStream?: boolean; taskRunId?: string; turnId?: string } = {},
  ) {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId || !this.store.getState().activeStreamSessionIds.includes(normalizedSessionId)) {
      return false;
    }
    this.nextChatStreamEpoch(normalizedSessionId);
    this.stoppedStreamingSessionIds.add(normalizedSessionId);
    this.clearPendingVisibleStreamFlush(normalizedSessionId);
    if (options.abortStream !== false) {
      this.streamAbortControllers.get(normalizedSessionId)?.abort();
      this.streamAbortControllers.delete(normalizedSessionId);
    }
    this.streamingSessionCache.delete(normalizedSessionId);
    this.activeTaskSteerStreamSessionIds.delete(normalizedSessionId);
    const streamBinding = this.activeChatStreamBindings.get(normalizedSessionId);
    const stoppedTaskRunId = String(options.taskRunId ?? "").trim() || String(streamBinding?.taskRunId ?? "").trim();
    const stoppedTurnId = String(options.turnId ?? "").trim() || String(streamBinding?.turnId ?? "").trim();
    this.activeChatStreamBindings.delete(normalizedSessionId);
    this.store.setState((prev) => ({
      ...this.releaseActiveTurnGateForStoppedStream(
        this.removeActiveStreamSession(prev, normalizedSessionId),
        stoppedTaskRunId,
        stoppedTurnId,
      ),
      chatStreamConnectionStatus: {
        state: "stopped",
        reason,
        updatedAt: Date.now(),
      },
    }));
    void this.flushQueuedUserInputsForSession(normalizedSessionId);
    return true;
  }

  private releaseActiveTurnGateForStoppedStream(state: StoreState, taskRunId: string, turnId: string) {
    const activeTurnSnapshot = state.activeTurnSnapshot;
    const snapshotMatches = Boolean(activeTurnSnapshot) && (
      Boolean(turnId && activeTurnSnapshot?.turn_id === turnId)
      || Boolean(taskRunId && activeTurnSnapshot?.task_run_id === taskRunId)
    );
    const monitorInfo = this.singleAgentTaskMonitorInfo(state.taskGraphLiveMonitor);
    const monitorMatches = Boolean(taskRunId && monitorInfo?.taskRunId === taskRunId);
    if (!snapshotMatches && !monitorMatches) {
      return state;
    }
    return {
      ...state,
      activeTurnSnapshot: snapshotMatches ? null : state.activeTurnSnapshot,
      taskGraphLiveMonitor: monitorMatches ? null : state.taskGraphLiveMonitor,
    };
  }

  private async pauseActiveTaskRun() {
    const taskRunId = this.activeControllableTaskRunId();
    if (!taskRunId) {
      return;
    }
    this.setActiveTaskControlActivity({
      taskRunId,
      level: "running",
      title: "正在暂停",
      detail: "暂停请求已发送，等待当前步骤停在可继续边界。",
      event: "active_task_pause_requested",
    });
    try {
      await pauseOrchestrationHarnessTaskRun(taskRunId, "user_pause_from_chat", this.activeExpectedTurnIdForTaskRun(taskRunId));
      await this.refreshActiveSessionMonitor();
    } catch (error) {
      this.setActiveTaskControlError("pause", taskRunId, error);
    }
  }

  private async resumeActiveTaskRun() {
    const taskRunId = this.activeControllableTaskRunId();
    if (!taskRunId) {
      return;
    }
    const expectedTurnId = this.activeExpectedTurnIdForTaskRun(taskRunId);
    const approvingToolCall = this.activeTaskRunStatus(taskRunId) === "waiting_approval";
    this.setActiveTaskControlActivity({
      taskRunId,
      level: "running",
      title: approvingToolCall ? "正在确认" : "正在继续",
      detail: approvingToolCall ? "确认请求已发送，等待工具调用继续。" : "继续请求已发送，等待当前任务恢复执行。",
      event: approvingToolCall ? "active_task_approval_requested" : "active_task_resume_requested",
    });
    try {
      if (approvingToolCall) {
        await approveOrchestrationHarnessTaskRunToolCall(taskRunId, "user_approve_tool_from_chat", 12, expectedTurnId);
      } else {
        await resumeOrchestrationHarnessTaskRun(taskRunId, 12, expectedTurnId);
      }
      await this.refreshActiveSessionMonitor();
    } catch (error) {
      this.setActiveTaskControlError(approvingToolCall ? "approve" : "resume", taskRunId, error);
    }
  }

  private async stopActiveTaskRun() {
    const taskRunId = this.activeControllableTaskRunId();
    if (!taskRunId) {
      this.releaseStoppedChatStreamBoundary(this.store.getState().currentSessionId);
      return;
    }
    const expectedTurnId = this.activeExpectedTurnIdForTaskRun(taskRunId);
    this.releaseStoppedChatStreamBoundary(this.store.getState().currentSessionId, "user_stopped", { taskRunId, turnId: expectedTurnId });
    this.setActiveTaskControlActivity({
      taskRunId,
      level: "running",
      title: "正在停止",
      detail: "停止请求已发送，当前步骤到达运行边界后会结束。",
      event: "active_task_stop_requested",
    });
    try {
      await stopOrchestrationHarnessTaskRun(taskRunId, "user_stop_from_chat", expectedTurnId);
      await this.refreshActiveSessionMonitor();
    } catch (error) {
      this.setActiveTaskControlError("stop", taskRunId, error);
    }
  }

  private async stopTaskRunFromSystemInterrupt(taskRunId: string, expectedTurnId: string, reason: string) {
    try {
      await stopOrchestrationHarnessTaskRun(taskRunId, reason, expectedTurnId);
      await this.refreshActiveSessionMonitor();
    } catch (error) {
      this.setActiveTaskControlError("stop", taskRunId, error);
    }
  }

  private setActiveTaskControlActivity(input: {
    taskRunId: string;
    level: StoreState["sessionActivity"]["level"];
    title: string;
    detail: string;
    event: string;
  }) {
    const sessionId = this.store.getState().currentSessionId;
    this.store.setState((prev) => ({
      ...prev,
      sessionActivity: sessionId
        ? {
            level: input.level,
            title: input.title,
            detail: input.detail,
            event: input.event,
            receipt: {
              level: input.level,
              title: input.title,
              body: input.detail,
              debug: {
                event: input.event,
                taskRunId: input.taskRunId,
              },
            },
            updatedAt: Date.now(),
          }
        : prev.sessionActivity,
      sessionActivitiesById: sessionId
        ? {
            ...prev.sessionActivitiesById,
            [sessionId]: {
              level: input.level,
              title: input.title,
              detail: input.detail,
              event: input.event,
              receipt: {
                level: input.level,
                title: input.title,
                body: input.detail,
                debug: {
                  event: input.event,
                  taskRunId: input.taskRunId,
                },
              },
              updatedAt: Date.now(),
            },
          }
        : prev.sessionActivitiesById,
    }));
  }

  private setActiveTaskControlError(action: "approve" | "pause" | "resume" | "stop", taskRunId: string, error: unknown) {
    const titles: Record<typeof action, string> = {
      approve: "确认失败",
      pause: "暂停失败",
      resume: "继续失败",
      stop: "停止失败",
    };
    const fallback = `${titles[action]}，请稍后重试或在运行监控里查看当前状态。`;
    this.setActiveTaskControlActivity({
      taskRunId,
      level: "error",
      title: titles[action],
      detail: this.errorMessage(error, fallback),
      event: `active_task_${action}_failed`,
    });
  }

  private activeControllableTaskRunId() {
    const state = this.store.getState();
    const monitor = state.taskGraphLiveMonitor;
    const monitorInfo = this.singleAgentTaskMonitorInfo(monitor);
    if (monitorInfo) {
      return monitorInfo.taskRunId;
    }
    if (monitor) {
      return "";
    }
    return String(
      state.currentSessionId
        ? this.activeChatStreamBindings.get(state.currentSessionId)?.taskRunId ?? ""
        : ""
    ).trim();
  }

  private activeTaskRunStatus(taskRunId: string) {
    const monitor = this.store.getState().taskGraphLiveMonitor;
    if (!monitor) {
      return "";
    }
    const taskRun = this.harnessMonitorTaskRun(monitor);
    const currentId = String(taskRun.task_run_id ?? monitor.task_run_id ?? "").trim();
    if (currentId !== taskRunId) {
      return "";
    }
    return String(monitor.status ?? taskRun.status ?? "").trim();
  }

  private activeExpectedTurnIdForTaskRun(taskRunId: string) {
    return this.expectedActiveTurnIdForSession(this.store.getState(), this.store.getState().currentSessionId ?? "", taskRunId);
  }

  private expectedActiveTurnIdForSession(state: StoreState, sessionId: string, taskRunId = "") {
    if (!sessionId || state.currentSessionId !== sessionId) {
      return "";
    }
    const snapshot = state.activeTurnSnapshot;
    const snapshotTaskRunId = String(snapshot?.task_run_id ?? "").trim();
    if (snapshot?.turn_id && (!taskRunId || !snapshotTaskRunId || snapshotTaskRunId === taskRunId)) {
      return String(snapshot.turn_id).trim();
    }
    const monitor = state.taskGraphLiveMonitor;
    const monitorInfo = this.singleAgentTaskMonitorInfo(monitor);
    if (!monitorInfo || (taskRunId && monitorInfo.taskRunId !== taskRunId)) {
      return "";
    }
    const monitorRecord = monitor as unknown as Record<string, unknown>;
    const monitorSnapshot = this.activeTurnSnapshotFromPayload(monitorRecord.active_turn_snapshot);
    if (monitorSnapshot?.turn_id) {
      const monitorSnapshotTaskRunId = String(monitorSnapshot.task_run_id ?? "").trim();
      if (!taskRunId || !monitorSnapshotTaskRunId || monitorSnapshotTaskRunId === taskRunId) {
        return monitorSnapshot.turn_id;
      }
    }
    return String(monitorRecord.latest_interaction_turn_id ?? "").trim();
  }

  private singleAgentTaskMonitorInfo(monitor: StoreState["taskGraphLiveMonitor"]) {
    if (!monitor) {
      return null;
    }
    const taskRun = this.harnessMonitorTaskRun(monitor);
    const monitorRecord = monitor as unknown as Record<string, unknown>;
    const route = monitorRecord.route && typeof monitorRecord.route === "object" && !Array.isArray(monitorRecord.route)
      ? monitorRecord.route as Record<string, unknown>
      : {};
    const diagnostics = taskRun.diagnostics && typeof taskRun.diagnostics === "object" && !Array.isArray(taskRun.diagnostics)
      ? taskRun.diagnostics as Record<string, unknown>
      : {};
    const executionRuntimeKind = String(monitor.execution_runtime_kind ?? taskRun.execution_runtime_kind ?? "").trim();
    const taskRunId = String(taskRun.task_run_id ?? monitor.task_run_id ?? "").trim();
    if (
      !taskRunId
      || executionRuntimeKind !== "single_agent_task"
      || String(route.kind ?? "").trim() === "task_graph_run"
      || String(diagnostics.origin_kind ?? "").trim() === "graph_node_assigned"
    ) {
      return null;
    }
    const runtimeControl = monitor.runtime_control ?? {};
    return {
      taskRunId,
      status: String(monitor.status ?? taskRun.status ?? "").trim(),
      controlState: String(monitor.control_state ?? runtimeControl.state ?? "").trim(),
    };
  }

  private activeTaskIsOpenForSteer(monitorInfo: { status: string; controlState: string } | null) {
    if (!monitorInfo) {
      return false;
    }
    const status = monitorInfo.status.trim().toLowerCase();
    const controlState = monitorInfo.controlState.trim().toLowerCase();
    return ["created", "running"].includes(status)
      && !["paused", "pause_requested", "stopped", "stop_requested"].includes(controlState);
  }

  private activeSnapshotIsTaskBound(snapshot: ActiveTurnSnapshot | null) {
    const snapshotState = String(snapshot?.state ?? "").trim();
    return snapshotState === "running_task"
      || snapshotState === "waiting_executor"
      || snapshotState === "waiting_approval"
      || snapshotState === "waiting_safe_boundary";
  }

  private activeSnapshotCanDeferToMonitor(snapshot: ActiveTurnSnapshot | null) {
    const snapshotState = String(snapshot?.state ?? "").trim();
    return !snapshotState || snapshotState === "starting" || this.activeSnapshotIsTaskBound(snapshot);
  }

  private activeTurnInputPolicyForSession(state: StoreState, sessionId: string) {
    return this.shouldQueueActiveTurnInput(state, sessionId) ? "steer" : "auto";
  }

  private shouldQueueActiveTurnInput(state: StoreState, sessionId: string) {
    if (state.currentSessionId !== sessionId) {
      return false;
    }
    const snapshot = state.activeTurnSnapshot;
    const activeTurnId = String(snapshot?.turn_id ?? "").trim();
    const activeTaskRunId = String(snapshot?.task_run_id ?? "").trim();
    const monitor = state.taskGraphLiveMonitor;
    const snapshotIsTaskBound = this.activeSnapshotIsTaskBound(snapshot);
    const monitorInfo = this.singleAgentTaskMonitorInfo(monitor);
    if (!monitorInfo) {
      return Boolean(activeTurnId && snapshotIsTaskBound);
    }
    if (!activeTurnId && !this.activeSnapshotCanDeferToMonitor(snapshot)) {
      return false;
    }
    if (!activeTaskRunId && this.activeSnapshotCanDeferToMonitor(snapshot)) {
      return this.activeTaskIsOpenForSteer(monitorInfo);
    }
    if (activeTaskRunId && activeTaskRunId !== monitorInfo.taskRunId) {
      return true;
    }
    return this.activeTaskIsOpenForSteer(monitorInfo);
  }

  private async refreshActiveSessionMonitor() {
    const sessionId = this.store.getState().currentSessionId;
    if (!sessionId) {
      return;
    }
    await this.hydrateLatestOrchestrationSnapshot(sessionId);
    await this.refreshRunMonitor();
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
    await truncateSessionMessages(sessionId, targetMessage.sourceIndex, this.sessionScopeForSession(sessionId));
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

  private async setPermissionMode(mode: PermissionMode) {
    const requestedMode = this.normalizePermissionMode(mode);
    const state = this.store.getState();
    const sessionId = state.currentSessionId;
    const sessionScope = sessionId ? this.sessionScopeForSession(sessionId) : undefined;
    const previousMode = state.permissionMode;
    const previousSessions = state.sessions;
    this.store.setState((prev) => ({
      ...prev,
      permissionMode: requestedMode,
      sessions: sessionId
        ? prev.sessions.map((session) => session.id === sessionId
          ? {
              ...session,
              conversation_state: this.conversationStateWithPermissionMode(session.conversation_state, requestedMode),
            }
          : session
        )
        : prev.sessions,
    }));
    try {
      const [conversationState, result] = await Promise.all([
        sessionId ? setSessionPermissionMode(sessionId, requestedMode, sessionScope) : Promise.resolve(null),
        setRuntimePermissionMode(requestedMode),
      ]);
      this.store.setState((prev) => ({
        ...prev,
        permissionMode: String(result.mode || requestedMode),
        sessions: sessionId && conversationState
          ? prev.sessions.map((session) => session.id === sessionId
            ? { ...session, conversation_state: conversationState }
            : session
          )
          : prev.sessions,
        supportedPermissionModes: Array.isArray(result.supported_modes) && result.supported_modes.length
          ? result.supported_modes.map(String)
          : prev.supportedPermissionModes,
      }));
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        permissionMode: previousMode,
        sessions: previousSessions,
        sessionActivity: {
          level: "error",
          title: "权限模式切换失败",
          detail: this.errorMessage(error, "无法更新运行权限模式。"),
          event: "permission_mode_update_failed",
          receipt: {
            level: "error",
            title: "权限模式切换失败",
            body: this.errorMessage(error, "无法更新运行权限模式。"),
            debug: {
              event: "permission_mode_update_failed",
              requestedMode,
            },
          },
          updatedAt: Date.now(),
        },
      }));
      throw error;
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

  private setChatStreamDisplayEnabled(enabled: boolean) {
    rememberChatStreamDisplayEnabled(enabled);
    this.store.setState((prev) => ({
      ...prev,
      chatStreamDisplayEnabled: Boolean(enabled),
    }));
  }

  private chatEnvironmentBindingPayload(state: StoreState): Record<string, unknown> | undefined {
    const activeEnvironment = state.conversationActiveEnvironment ?? this.defaultActiveTaskEnvironment();
    const taskEnvironmentId = String(activeEnvironment.task_environment_id ?? "").trim();
    if (!taskEnvironmentId) {
      return undefined;
    }
    return {
      task_environment_id: taskEnvironmentId,
      environment_id: taskEnvironmentId,
      environment_label: String(activeEnvironment.environment_label || this.taskEnvironmentLabel(taskEnvironmentId)),
      binding_kind: "conversation_active_task_environment",
      binding_source: activeEnvironment.source || "conversation",
      bound_at: activeEnvironment.updated_at,
    };
  }

  private chatModelSelectionPayload(state: StoreState): ChatModelSelection | undefined {
    const resolved = this.resolveChatModelSelection(state);
    const streamPolicy = this.chatStreamPolicyPayload(state);
    if (!resolved) {
      return { stream_policy: streamPolicy };
    }
    const { selectionId, provider, model, baseUrl, credentialRef } = resolved;
    const supportsHiddenReasoning = this.supportsHiddenReasoning(provider, model, state.selectedChatMode, state.modelProviderConfig);
    if (selectionId === "system-default" && !supportsHiddenReasoning) {
      return { stream_policy: streamPolicy };
    }
    const payload: ChatModelSelection = {
      selection_id: selectionId,
      provider,
      model,
      base_url: baseUrl,
      credential_ref: credentialRef,
      stream_policy: streamPolicy,
    };
    if (supportsHiddenReasoning) {
      const thinkingMode = normalizeChatThinkingMode(state.chatThinkingMode);
      payload.thinking_mode = thinkingMode === "normal" ? "disabled" : "enabled";
    }
    return payload;
  }

  private chatStreamPolicyPayload(state: StoreState) {
    const liveDisplayEnabled = Boolean(state.chatStreamDisplayEnabled);
    return {
      enabled: true,
      mode: liveDisplayEnabled ? "model_text_stream" : "public_projection_stream",
      emit_assistant_text_delta: true,
      source: "frontend.chat_stream_display_toggle",
    };
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
    const isProviderPreset = provider === config.provider
      && Boolean(option?.model_presets?.some((preset) => String(preset || "").trim() === model));
    if (!isPrimaryConfigured && !isFallbackConfigured && !isProviderPreset) {
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
          : config.base_url || option?.default_base_url,
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
    const modelId = (selectionId.split("::").pop() || selectionId).trim().toLowerCase();
    if (modelId.includes("image")) {
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
    const imageConfig = state.imageAssetConfig;
    if (!imageConfig?.configured || !imageConfig.base_url || !imageConfig.model) {
      return undefined;
    }
    const [provider, ...modelParts] = selectionId.split("::");
    const selectedModel = modelParts.join("::").trim() || selectionId.trim();
    const imageModel = String(imageConfig.model || "").trim();
    if (!imageModel || !imageModel.toLowerCase().includes("image")) {
      return undefined;
    }
    return {
      mode: "generate",
      selection_id: selectionId,
      provider: selectionId.includes("::") ? provider || "openai" : "openai",
      selected_model: selectedModel,
      model: imageModel,
      base_url: imageConfig.base_url,
      credential_ref: imageConfig.api_key_present ? "image-assets:api-key" : undefined,
      asset_kind: "chat",
      size: "1024x1024"
    };
  }

  private chatEditorContextPayload(state: StoreState, sessionId: string): Record<string, unknown> | undefined {
    const context = state.sessionEditorContexts[sessionId];
    const activePath = String(context?.activeFilePath || "").trim();
    const openFilePaths = this.uniqueFilePaths([
      ...(context?.openFilePaths ?? []),
      ...(activePath ? [activePath] : []),
    ]).slice(0, 20);
    if (!activePath && !openFilePaths.length) {
      return undefined;
    }
    const workspaceRoots = this.uniqueFilePaths([
      this.sessionProjectRoot(state, sessionId),
    ]);
    const activeFileLoaded = Boolean(activePath && context?.inspectorPath === activePath);
    const activeText = activeFileLoaded ? String(context?.inspectorContent || "") : "";
    const previewText = activeText.slice(0, FRONTEND_EDITOR_CONTEXT_TEXT_LIMIT);
    const contentPreview = previewText
      ? {
          start: { line: 0, character: 0 },
          end: this.editorEndPosition(previewText),
          text: previewText,
          truncated: activeText.length > previewText.length,
          source: "frontend_inspector",
        }
      : undefined;
    return {
      source: "frontend.center_workspace",
      captured_at: new Date().toISOString(),
      workspace_roots: workspaceRoots,
      active_file: activePath
        ? {
            path: activePath,
            language_id: this.languageIdForPath(activePath),
            dirty: Boolean(context?.inspectorDirty),
            content_preview: contentPreview,
            selection: undefined,
          }
        : undefined,
      visible_files: openFilePaths.map((path) => ({
        path,
        language_id: this.languageIdForPath(path),
        dirty: path === activePath ? Boolean(context?.inspectorDirty) : false,
      })),
    };
  }

  private editorEndPosition(text: string) {
    const lines = text.split(/\r\n|\r|\n/);
    return {
      line: Math.max(0, lines.length - 1),
      character: lines.length ? lines[lines.length - 1].length : 0,
    };
  }

  private languageIdForPath(path: string) {
    const normalized = path.toLowerCase();
    const extension = normalized.includes(".") ? normalized.slice(normalized.lastIndexOf(".") + 1) : "";
    switch (extension) {
      case "ts":
        return "typescript";
      case "tsx":
        return "typescriptreact";
      case "js":
        return "javascript";
      case "jsx":
        return "javascriptreact";
      case "py":
        return "python";
      case "json":
        return "json";
      case "md":
        return "markdown";
      case "css":
        return "css";
      case "html":
        return "html";
      default:
        return extension || "plaintext";
    }
  }

  private sessionProjectRoot(state: StoreState, sessionId: string) {
    return sessionProjectRoot(state.sessions.find((session) => session.id === sessionId));
  }

  private async renameCurrentSession(title: string) {
    const currentSessionId = this.store.getState().currentSessionId;
    if (!currentSessionId || !title.trim()) {
      return;
    }
    await renameSession(currentSessionId, title.trim(), this.sessionScopeForSession(currentSessionId));
    await this.refreshMainSessionPool().catch((error) => {
      this.noteSessionRefreshFailure(error);
    });
  }

  private async removeSession(ref: SessionRef) {
    const normalized = this.normalizeSessionRef(ref, this.store.getState());
    const sessionId = normalized.sessionId;
    if (!sessionId) {
      return;
    }
    const deletedSessionScope = normalized.scope;
    const poolKey = normalized.poolKey ?? sessionPoolKeyForScope(deletedSessionScope);
    const beforeDelete = this.store.getState();
    const wasCurrentSession = beforeDelete.currentSessionId === sessionId;
    const deletedSession = beforeDelete.sessions.find((session) => session.id === sessionId) ?? null;
    const deletedProjectSession = beforeDelete.projectSessions.find((session) => session.id === sessionId) ?? null;
    const deletedActivity = beforeDelete.sessionActivitiesById[sessionId] ?? null;
    const deletedEditorContext = beforeDelete.sessionEditorContexts[sessionId] ?? null;
    this.streamingSessionCache.delete(sessionId);
    this.removedStreamingSessionIds.add(sessionId);
    this.clearPendingVisibleStreamFlush(sessionId);
    this.streamAbortControllers.get(sessionId)?.abort();
    this.streamAbortControllers.delete(sessionId);
    this.store.setState((prev) => {
      const next = this.removeActiveStreamSession(prev, sessionId);
      const { [sessionId]: _removed, ...sessionActivitiesById } = next.sessionActivitiesById;
      const { [sessionId]: _removedEditorContext, ...sessionEditorContexts } = next.sessionEditorContexts;
      return {
        ...next,
        sessions: next.sessions.filter((session) => session.id !== sessionId),
        projectSessions: next.projectSessions.filter((session) => session.id !== sessionId),
        sessionActivitiesById,
        sessionEditorContexts,
        sessionActivity: next.currentSessionId === sessionId ? createIdleSessionActivity(Date.now()) : next.sessionActivity,
      };
    });
    try {
      await deleteSession(sessionId, deletedSessionScope);
    } catch (error) {
      this.removedStreamingSessionIds.delete(sessionId);
      this.store.setState((prev) => ({
        ...prev,
        sessions: deletedSession ? mergeSessionSummaries(prev.sessions, [deletedSession]) : prev.sessions,
        projectSessions: deletedProjectSession ? mergeSessionSummaries(prev.projectSessions, [deletedProjectSession]) : prev.projectSessions,
        sessionActivitiesById: deletedActivity
          ? { ...prev.sessionActivitiesById, [sessionId]: deletedActivity }
          : prev.sessionActivitiesById,
        sessionEditorContexts: deletedEditorContext
          ? { ...prev.sessionEditorContexts, [sessionId]: deletedEditorContext }
          : prev.sessionEditorContexts,
      }));
      throw error;
    }
    clearRememberedSessionRef(sessionId);
    this.clearPersistedCurrentSessionRef(sessionId);

    if (poolKey === MAIN_CHAT_POOL_KEY) {
      const refreshedSessions = await this.refreshMainSessionPool().catch((error) => {
        this.noteSessionRefreshFailure(error);
        return null;
      });
      if (!wasCurrentSession || this.store.getState().currentSessionId !== sessionId) {
        return;
      }
      const nextSessions = refreshedSessions ?? [];
      if (nextSessions.length) {
        const nextSession = nextSessions[0];
        await this.selectSession({
          sessionId: nextSession.id,
          scope: nextSession.scope,
          poolKey: MAIN_CHAT_POOL_KEY,
        });
        return;
      }
      this.clearActiveSession();
      return;
    }

    const scopedNextSessions = wasCurrentSession
      ? await listSessions(deletedSessionScope).catch((error) => {
          this.noteSessionRefreshFailure(error);
          return null;
        })
      : null;
    if (!wasCurrentSession || this.store.getState().currentSessionId !== sessionId) {
      return;
    }
    const nextSessions = scopedNextSessions ?? [];
    if (nextSessions.length) {
      const nextSession = nextSessions[0];
      await this.selectSession({
        sessionId: nextSession.id,
        scope: nextSession.scope ?? deletedSessionScope,
        poolKey,
      });
      return;
    }
    this.clearActiveSession();
  }

  private clearActiveSession() {
    clearRememberedSessionRef();
    this.clearPersistedCurrentSessionRef();
    this.store.setState((prev) => ({
      ...prev,
      currentSessionId: null,
      activeSessionScope: null,
      activeSessionRef: null,
      messages: [],
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: null,
      activeTurnSnapshot: null,
      tokenStats: null,
      inspectorPath: DEFAULT_INSPECTOR_PATH,
      inspectorContent: "",
      inspectorDirty: false,
      sessionActivity: createIdleSessionActivity(Date.now())
    }));
  }

  private async loadInspectorFile(path: string) {
    try {
      let state = this.store.getState();
      let sessionId = state.currentSessionId || "";
      if (!sessionId && state.activeProjectKey) {
        sessionId = await this.ensureSession();
        state = this.store.getState();
      }
      const scope = sessionId ? this.sessionScopeForSession(sessionId) : undefined;
      if (sessionId && !this.sessionProjectRoot(state, sessionId)) {
        throw new Error("当前会话未绑定项目，不能打开项目文件。");
      }
      const file = sessionId
        ? await loadFileForSession(path, sessionId, scope)
        : await loadFile(path);
      this.store.setState((prev) => this.patchCurrentSessionEditorContext({
        ...prev,
        inspectorPath: file.path,
        inspectorContent: file.content,
        inspectorDirty: false,
        workspaceTreeError: ""
      }, {
        activeFilePath: file.path,
        inspectorPath: file.path,
        inspectorContent: file.content,
        inspectorDirty: false,
      }));
    } catch (error) {
      const message = this.errorMessage(error, `无法打开文件：${path}`);
      this.store.setState((prev) => this.patchCurrentSessionEditorContext({
        ...prev,
        inspectorPath: path,
        inspectorContent: message,
        inspectorDirty: false,
        workspaceTreeError: message
      }, {
        activeFilePath: path,
        inspectorPath: path,
        inspectorContent: "",
        inspectorDirty: false,
      }));
    }
  }

  private async refreshWorkspaceTree() {
    const state = this.store.getState();
    const activeProjectKey = state.activeProjectKey;
    const sessionId = state.currentSessionId || "";
    const scope = sessionId ? this.sessionScopeForSession(sessionId) : undefined;
    const requestKey = this.workspaceTreeRefreshKey(activeProjectKey, sessionId, scope);
    if (this.workspaceTreeInFlightPromise && this.workspaceTreeInFlightKey === requestKey) {
      return this.workspaceTreeInFlightPromise;
    }
    const requestId = ++this.workspaceTreeRequest;
    if (!activeProjectKey && sessionId && !this.sessionProjectRoot(state, sessionId)) {
      this.store.setState((prev) => ({
        ...prev,
        workspaceTree: null,
        workspaceTreeLoading: false,
        workspaceTreeError: "",
      }));
      return;
    }
    const request = (async () => {
      this.store.setState((prev) => ({
        ...prev,
        workspaceTreeLoading: true,
        workspaceTreeError: ""
      }));
      const workspaceTree = activeProjectKey
        ? await getProjectWorkspaceTree(activeProjectKey)
        : await getCodeEnvironmentWorkspaceTree({
            sessionId: sessionId || undefined,
            scope,
          });
      if (
        this.workspaceTreeRequest !== requestId
        || this.workspaceTreeRefreshKeyForState(this.store.getState()) !== requestKey
      ) {
        return;
      }
      this.store.setState((prev) => ({
        ...prev,
        workspaceTree,
        workspaceTreeLoading: false,
        workspaceTreeError: ""
      }));
    })();
    const handledRequest = request.catch((error) => {
      if (
        this.workspaceTreeRequest !== requestId
        || this.workspaceTreeRefreshKeyForState(this.store.getState()) !== requestKey
      ) {
        return;
      }
      this.store.setState((prev) => ({
        ...prev,
        workspaceTreeLoading: false,
        workspaceTreeError: this.errorMessage(error, "无法读取项目文件树。")
      }));
    }).finally(() => {
      if (this.workspaceTreeRequest === requestId && this.workspaceTreeInFlightKey === requestKey) {
        this.workspaceTreeInFlightKey = "";
        this.workspaceTreeInFlightPromise = null;
      }
    });
    this.workspaceTreeInFlightKey = requestKey;
    this.workspaceTreeInFlightPromise = handledRequest;
    await handledRequest;
  }

  private workspaceTreeRefreshKeyForState(state: StoreState) {
    const sessionId = state.currentSessionId || "";
    return this.workspaceTreeRefreshKey(
      state.activeProjectKey,
      sessionId,
      sessionId ? this.sessionScopeForSession(sessionId) : undefined,
    );
  }

  private workspaceTreeRefreshKey(activeProjectKey: string, sessionId: string, scope: Partial<SessionScope> | undefined) {
    if (activeProjectKey) {
      return `project:${activeProjectKey}`;
    }
    return `session:${sessionId || ""}:${JSON.stringify(scope ?? {})}`;
  }

  private updateInspectorContent(value: string) {
    this.store.setState((prev) => this.patchCurrentSessionEditorContext({
      ...prev,
      inspectorContent: value,
      inspectorDirty: true
    }, {
      inspectorPath: prev.inspectorPath,
      inspectorContent: value,
      inspectorDirty: true,
    }));
  }

  private async saveInspector() {
    let state = this.store.getState();
    let sessionId = state.currentSessionId || "";
    if (!sessionId && state.activeProjectKey) {
      sessionId = await this.ensureSession();
      state = this.store.getState();
    }
    const scope = sessionId ? this.sessionScopeForSession(sessionId) : undefined;
    if (sessionId && !this.sessionProjectRoot(state, sessionId)) {
      this.store.setState((prev) => ({
        ...prev,
        workspaceTreeError: "当前会话未绑定项目，不能保存项目文件。",
      }));
      return;
    }
    if (sessionId) {
      await saveFileForSession(state.inspectorPath, state.inspectorContent, sessionId, scope);
    } else {
      await saveFile(state.inspectorPath, state.inspectorContent);
    }
    this.store.setState((prev) => this.patchCurrentSessionEditorContext({
      ...prev,
      inspectorDirty: false,
    }, {
      inspectorPath: prev.inspectorPath,
      inspectorContent: prev.inspectorContent,
      inspectorDirty: false,
    }));
    await this.refreshSkills();
  }

  private setSessionEditorPageState(patch: SessionEditorPageStatePatch) {
    this.store.setState((prev) => {
      const clearsFiles = patch.activeFilePath === "" && Array.isArray(patch.openFilePaths) && patch.openFilePaths.length === 0;
      return this.patchCurrentSessionEditorContext(clearsFiles
        ? {
            ...prev,
            inspectorPath: DEFAULT_INSPECTOR_PATH,
            inspectorContent: "",
            inspectorDirty: false,
          }
        : prev,
        {
          activeFilePath: patch.activeFilePath,
          openFilePaths: patch.openFilePaths,
          ...(clearsFiles ? { inspectorPath: "", inspectorContent: "", inspectorDirty: false } : {}),
        }
      );
    });
  }

  private setSidebarWidth(width: number) {
    this.store.setState((prev) => ({ ...prev, sidebarWidth: width }));
  }

  private setInspectorWidth(width: number) {
    this.store.setState((prev) => ({ ...prev, inspectorWidth: width }));
  }

  private setWorkspaceView(view: WorkspaceView) {
    if (view === "chat") {
      this.openCurrentTaskEnvironmentWorkspace();
      return;
    }
    if (view === "code-environment") {
      this.setTaskEnvironmentWorkspaceView(view);
      return;
    }
    this.syncWorkspaceViewUrl(view);
    this.store.setState((prev) => ({ ...prev, activeWorkspaceView: view }));
  }

  private openCurrentTaskEnvironmentWorkspace() {
    const activeEnvironmentId = String(
      this.store.getState().conversationActiveEnvironment?.task_environment_id || "",
    ).trim();
    const view = activeEnvironmentId
      ? this.workspaceViewForTaskEnvironment(activeEnvironmentId)
      : "chat";
    const workspaceView = view === "creative" ? "chat" : view;
    this.syncWorkspaceViewUrl(workspaceView);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: workspaceView,
    }));
  }

  private setTaskEnvironmentWorkspaceView(view: TaskEnvironmentWorkspaceView) {
    const taskEnvironmentId = this.defaultTaskEnvironmentIdForView(view);
    void this.setActiveTaskEnvironment(taskEnvironmentId, { source: "workspace-mode" });
  }

  private defaultTaskEnvironmentIdForView(view: TaskEnvironmentWorkspaceView) {
    const catalog = this.store.getState().taskEnvironmentCatalog;
    if (view === "code-environment") {
      const rememberedId = this.rememberedTaskEnvironmentId();
      if (rememberedId && this.workspaceViewForTaskEnvironment(rememberedId) === "code-environment") {
        return rememberedId;
      }
      for (const candidate of [CODING_TASK_ENVIRONMENT_ID]) {
        if (catalog?.environments.some((item) => isCatalogEnvironmentVisible(item) && taskEnvironmentIdOf(item) === candidate)) {
          return candidate;
        }
      }
      const codeCandidate = catalog?.environments.find((item) => {
        const kind = String(item.record?.environment_kind || "").trim();
        return isCatalogEnvironmentVisible(item) && kind === "coding";
      });
      return taskEnvironmentIdOf(codeCandidate) || CODING_TASK_ENVIRONMENT_ID;
    }
    const rememberedId = this.rememberedTaskEnvironmentId();
    if (rememberedId && this.workspaceViewForTaskEnvironment(rememberedId) === "chat") {
      return rememberedId;
    }
    if (catalog?.environments.some((item) => isCatalogEnvironmentVisible(item) && taskEnvironmentIdOf(item) === GENERAL_TASK_ENVIRONMENT_ID)) {
      return GENERAL_TASK_ENVIRONMENT_ID;
    }
    return taskEnvironmentIdOf(catalog?.environments.find((item) => isCatalogEnvironmentVisible(item) && !GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(taskEnvironmentIdOf(item))))
      || GENERAL_TASK_ENVIRONMENT_ID;
  }

  private workspaceViewForTaskEnvironment(taskEnvironmentId: string): WorkspaceView {
    const normalized = String(taskEnvironmentId || "").trim();
    if (GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(normalized)) {
      return "creative";
    }
    const kind = String(this.taskEnvironmentCatalogItem(normalized)?.record?.environment_kind || "").trim();
    if (CODE_TASK_ENVIRONMENT_IDS.has(normalized) || kind === "coding") {
      return "code-environment";
    }
    return "chat";
  }

  private async setActiveTaskEnvironment(environmentId: string, options: { environmentLabel?: string; source?: string } = {}) {
    const taskEnvironmentId = String(environmentId || "").trim();
    if (!taskEnvironmentId) {
      return;
    }
    const catalog = this.store.getState().taskEnvironmentCatalog;
    if (catalog?.environments.length && !this.visibleTaskEnvironmentCatalogItem(taskEnvironmentId)) {
      storageRemove(LAST_ACTIVE_TASK_ENVIRONMENT_KEY);
      const fallback = this.defaultActiveTaskEnvironment(options.source || "workspace-mode");
      if (fallback.task_environment_id !== taskEnvironmentId) {
        await this.setActiveTaskEnvironment(fallback.task_environment_id, {
          environmentLabel: fallback.environment_label,
          source: fallback.source,
        });
      }
      return;
    }
    const view = this.workspaceViewForTaskEnvironment(taskEnvironmentId);
    if (view === "creative" || GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(taskEnvironmentId)) {
      this.syncWorkspaceViewUrl("creative");
      this.store.setState((prev) => ({
        ...prev,
        activeWorkspaceView: "creative",
        chatTaskEnvironmentBinding: null,
      }));
      return;
    }
    const activeEnvironment = {
      task_environment_id: taskEnvironmentId,
      environment_label: String(this.taskEnvironmentRegistryLabel(taskEnvironmentId) || options.environmentLabel || "").trim() || taskEnvironmentId,
      source: options.source || "conversation",
      updated_at: Date.now() / 1000,
      authority: "frontend.conversation_active_task_environment",
    };
    this.syncWorkspaceViewUrl(view);
    this.rememberTaskEnvironment(activeEnvironment);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: view,
      conversationActiveEnvironment: activeEnvironment,
      chatTaskEnvironmentBinding: null,
    }));
    const sessionId = this.store.getState().currentSessionId;
    if (sessionId) {
      await this.persistActiveTaskEnvironment(sessionId, activeEnvironment).catch((error) => {
        this.store.setState((prev) => ({
          ...prev,
          taskEnvironmentCatalogError: this.errorMessage(error, "任务环境切换已在前端生效，但会话状态写入失败。"),
        }));
      });
    }
  }

  private bindTaskEnvironmentContext(
    taskEnvironmentId: string,
    options: {
      environmentLabel?: string;
      source?: ChatTaskEnvironmentBinding["source"];
    } = {},
  ) {
    const normalized = String(taskEnvironmentId || "").trim();
    if (!normalized) {
      return;
    }
    if (GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(normalized)) {
      this.syncWorkspaceViewUrl("creative");
      this.store.setState((prev) => ({
        ...prev,
        activeWorkspaceView: "creative",
        chatTaskEnvironmentBinding: null,
      }));
      return;
    }
    void this.setActiveTaskEnvironment(normalized, {
      environmentLabel: options.environmentLabel,
      source: options.source ?? "workspace-mode",
    }).catch((error) => {
      this.store.setState((prev) => ({
        ...prev,
        taskEnvironmentCatalogError: this.errorMessage(error, "任务环境切换失败。"),
      }));
    });
  }

  private centerWorkspaceHostView(view: WorkspaceView): TaskEnvironmentWorkspaceView {
    return view === "code-environment" ? "code-environment" : "chat";
  }

  private openTaskGraphWorkspace(target: Omit<TaskGraphWorkspaceTarget, "layer" | "requested_at"> = {}) {
    const mode = target.mode ?? "monitor";
    const workspaceView: WorkspaceView = mode === "editor" ? "task-system" : "creative";
    this.syncWorkspaceViewUrl(workspaceView);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: workspaceView,
      taskGraphWorkspaceTarget: {
        layer: "task-graph",
        mode,
        task_environment_id: "",
        graph_id: String(target.graph_id ?? "").trim() || undefined,
        task_run_id: String(target.task_run_id ?? "").trim() || undefined,
        task_instance_id: String(target.task_instance_id ?? "").trim() || undefined,
        graph_run_id: String(target.graph_run_id ?? "").trim() || undefined,
        focus_node_id: String(target.focus_node_id ?? "").trim() || undefined,
        requested_at: Date.now(),
      },
    }));
  }

  private openWorkspaceFile(path: string) {
    const filePath = String(path || "").trim();
    if (!filePath) {
      return;
    }
    const view = this.centerWorkspaceHostView(this.store.getState().activeWorkspaceView);
    this.syncWorkspaceViewUrl(view);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: view,
      centerWorkspaceTarget: {
        layer: "file",
        file_path: filePath,
        requested_at: Date.now(),
      },
    }));
  }

  private openRuntimeLog(target: Omit<RuntimeLogCenterWorkspaceTarget, "layer" | "requested_at">) {
    const runId = String(target?.run_id || "").trim();
    if (!runId) {
      return;
    }
    const scope = target.scope === "turn_run" ? "turn_run" : "task_run";
    const view = this.centerWorkspaceHostView(this.store.getState().activeWorkspaceView);
    this.syncWorkspaceViewUrl(view);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: view,
      centerWorkspaceTarget: {
        layer: "runtime-log",
        scope,
        run_id: runId,
        title: String(target.title || "").trim() || undefined,
        subtitle: String(target.subtitle || "").trim() || undefined,
        requested_at: Date.now(),
      },
    }));
  }

  private clearCenterWorkspaceTarget() {
    this.store.setState((prev) => ({
      ...prev,
      centerWorkspaceTarget: null,
    }));
  }

  private clearTaskGraphWorkspaceTarget() {
    this.store.setState((prev) => ({
      ...prev,
      taskGraphWorkspaceTarget: null,
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
    this.runMonitorController.bindGraphRun(binding);
  }

  private clearTaskGraphMonitorRun() {
    this.runMonitorController.clearGraphRun();
  }

  private setTaskGraphRunInteractionOpen(open: boolean) {
    this.runMonitorController.setGraphRunInteractionOpen(open);
  }

  private setTaskGraphAutoAdvanceEnabled(enabled: boolean) {
    this.runMonitorController.setGraphAutoAdvanceEnabled(enabled);
  }

  private async evaluateBoundTaskGraphMonitor() {
    await this.runMonitorController.evaluateBoundGraphMonitor();
  }

  private async continueBoundTaskGraphRun() {
    await this.runMonitorController.continueBoundGraphRun();
  }

  private async pauseBoundTaskGraphRun() {
    const state = this.store.getState();
    const monitor = state.taskGraphBoundRunMonitor as Record<string, unknown> | null;
    const graphConfig = monitor?.graph_harness_config && typeof monitor.graph_harness_config === "object" && !Array.isArray(monitor.graph_harness_config)
      ? monitor.graph_harness_config as Record<string, unknown>
      : {};
    const graphRunId = String(state.taskGraphMonitorBinding?.graph_run_id || monitor?.graph_run_id || "").trim();
    const graphHarnessConfigId = String(state.taskGraphMonitorBinding?.graph_harness_config_id || graphConfig.config_id || graphConfig.graph_harness_config_id || "").trim();
    if (!graphRunId || !graphHarnessConfigId) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: "当前 GraphRun 缺少可暂停的图运行绑定。",
      }));
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      taskGraphAutoAdvanceEnabled: false,
      taskGraphAutoAdvancePending: false,
      taskGraphMonitorActionLoading: true,
      taskGraphMonitorError: "",
    }));
    try {
      await pauseGraphRun(graphRunId, {
        graph_harness_config_id: graphHarnessConfigId,
        session_scope: state.taskGraphMonitorBinding?.session_scope,
        reason: "user_pause_graph_run",
      });
      await this.runMonitorController.evaluateBoundGraphMonitor().catch(() => undefined);
      await this.refreshRunMonitor();
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: this.errorMessage(error, "GraphRun 暂停失败"),
      }));
    } finally {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorActionLoading: false,
      }));
    }
  }

  private async stopBoundTaskGraphRun() {
    const taskRunId = this.boundTaskGraphRunTaskRunId();
    if (!taskRunId) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: "当前 GraphRun 没有关联可停止的 TaskRun。",
      }));
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      taskGraphAutoAdvanceEnabled: false,
      taskGraphAutoAdvancePending: false,
      taskGraphMonitorActionLoading: true,
      taskGraphMonitorError: "",
    }));
    try {
      await stopOrchestrationHarnessTaskRun(taskRunId, "user_stop_graph_run", "");
      await this.runMonitorController.evaluateBoundGraphMonitor().catch(() => undefined);
      await this.refreshRunMonitor();
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: this.errorMessage(error, "GraphRun 停止失败"),
      }));
    } finally {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorActionLoading: false,
      }));
    }
  }

  private boundTaskGraphRunTaskRunId() {
    const state = this.store.getState();
    const monitor = state.taskGraphBoundRunMonitor as Record<string, unknown> | null;
    const taskRun = monitor?.task_run && typeof monitor.task_run === "object" && !Array.isArray(monitor.task_run)
      ? monitor.task_run as Record<string, unknown>
      : {};
    const taskRunMonitor = (monitor?.task_run_monitor && typeof monitor.task_run_monitor === "object" && !Array.isArray(monitor.task_run_monitor)
      ? monitor.task_run_monitor
      : monitor?.runtime_monitor && typeof monitor.runtime_monitor === "object" && !Array.isArray(monitor.runtime_monitor)
        ? monitor.runtime_monitor
        : {}) as Record<string, unknown>;
    return String(
      state.taskGraphMonitorBinding?.task_run_id
      || monitor?.task_run_id
      || taskRun.task_run_id
      || taskRunMonitor.task_run_id
      || ""
    ).trim();
  }

  private boundTaskGraphRunControlState() {
    const state = this.store.getState();
    const monitor = state.taskGraphBoundRunMonitor as Record<string, unknown> | null;
    const taskRun = monitor?.task_run && typeof monitor.task_run === "object" && !Array.isArray(monitor.task_run)
      ? monitor.task_run as Record<string, unknown>
      : {};
    const taskRunMonitor = (monitor?.task_run_monitor && typeof monitor.task_run_monitor === "object" && !Array.isArray(monitor.task_run_monitor)
      ? monitor.task_run_monitor
      : monitor?.runtime_monitor && typeof monitor.runtime_monitor === "object" && !Array.isArray(monitor.runtime_monitor)
        ? monitor.runtime_monitor
        : {}) as Record<string, unknown>;
    const monitorControl = taskRunMonitor.runtime_control && typeof taskRunMonitor.runtime_control === "object" && !Array.isArray(taskRunMonitor.runtime_control)
      ? taskRunMonitor.runtime_control as Record<string, unknown>
      : {};
    const taskRunDiagnostics = taskRun.diagnostics && typeof taskRun.diagnostics === "object" && !Array.isArray(taskRun.diagnostics)
      ? taskRun.diagnostics as Record<string, unknown>
      : {};
    const taskControl = taskRunDiagnostics.runtime_control && typeof taskRunDiagnostics.runtime_control === "object" && !Array.isArray(taskRunDiagnostics.runtime_control)
      ? taskRunDiagnostics.runtime_control as Record<string, unknown>
      : {};
    const graphRun = monitor?.graph_run && typeof monitor.graph_run === "object" && !Array.isArray(monitor.graph_run)
      ? monitor.graph_run as Record<string, unknown>
      : {};
    const graphDiagnostics = graphRun.diagnostics && typeof graphRun.diagnostics === "object" && !Array.isArray(graphRun.diagnostics)
      ? graphRun.diagnostics as Record<string, unknown>
      : {};
    const graphControl = graphDiagnostics.runtime_control && typeof graphDiagnostics.runtime_control === "object" && !Array.isArray(graphDiagnostics.runtime_control)
      ? graphDiagnostics.runtime_control as Record<string, unknown>
      : {};
    return String(
      taskRunMonitor.control_state
      || monitorControl.state
      || taskControl.state
      || graphControl.state
      || ""
    ).trim();
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
    const controlState = this.boundTaskGraphRunControlState().toLowerCase();
    if (controlState === "paused") {
      await resumeGraphRun(runId, {
        graph_harness_config_id: graphHarnessConfigId,
        session_scope: this.store.getState().taskGraphMonitorBinding?.session_scope,
        reason: "task_graph_interaction_resume",
      });
    } else if (controlState === "pause_requested" || controlState === "stop_requested") {
      throw new Error(controlState === "pause_requested" ? "暂停请求正在等待运行边界，等状态变为已暂停后再续跑。" : "停止请求正在等待运行边界，不能继续派发。");
    }
    await submitGraphRunUntilIdle(runId, {
      graph_harness_config_id: graphHarnessConfigId,
      session_scope: this.store.getState().taskGraphMonitorBinding?.session_scope,
      max_node_executions: 1,
      max_loop_iterations: 4,
      max_dispatches: 1,
      max_dispatch_requests: Number(payload?.max_requests ?? 1),
    });
    await this.runMonitorController.evaluateBoundGraphMonitor().catch(() => undefined);
    await this.refreshRunMonitor();
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
      const liveMonitorRecord = liveMonitor && typeof liveMonitor === "object" && !Array.isArray(liveMonitor)
        ? liveMonitor as Record<string, unknown>
        : {};
      const activeTurnSnapshotFieldPresent = Object.prototype.hasOwnProperty.call(liveMonitorRecord, "active_turn_snapshot");
      const activeTurnSnapshot = this.activeTurnSnapshotFromPayload(liveMonitorRecord.active_turn_snapshot);
      const activeMonitor = this.activeHarnessSessionMonitor(liveMonitor);
      if (!activeMonitor) {
        if (this.store.getState().currentSessionId === targetSessionId && this.orchestrationHydrateRequest === requestId) {
          this.store.setState((prev) => ({
            ...prev,
            activeTurnSnapshot: activeTurnSnapshot ?? (
              activeTurnSnapshotFieldPresent && !prev.activeStreamSessionIds.includes(targetSessionId)
                ? null
                : prev.activeTurnSnapshot
            ),
            taskGraphLiveMonitor: null,
          }));
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
      const hasActiveHarnessRun = ["created", "running", "waiting_executor", "waiting_approval", "waiting_safe_boundary", "blocked"].includes(liveStatus) && !staleOrDiagnostic;
      const hasPendingApproval = liveStatus === "waiting_approval" || String((activeMonitor.loop_state as Record<string, unknown> | undefined)?.terminal_reason ?? "") === "waiting_approval";
      const taskRunId = String(activeTaskRun.task_run_id ?? activeMonitor.task_run_id ?? liveMonitor.active_task_run_id ?? "").trim();
      const graphRunId = String(activeMonitor.graph_run_id ?? activeTaskRun.graph_run_id ?? "").trim();
      this.updateSessionActivityFromLiveMonitor(
        staleOrDiagnostic && controlState.trim().toLowerCase() !== "paused" ? "stale" : liveStatus,
        taskRunId,
        graphRunId,
        controlState,
        activeMonitor as Record<string, unknown>,
      );
      if (this.store.getState().currentSessionId === targetSessionId && this.orchestrationHydrateRequest === requestId) {
        this.store.setState((prev) => {
          const nextActiveTurnSnapshot = activeTurnSnapshot ?? prev.activeTurnSnapshot;
          return {
            ...prev,
            activeTurnSnapshot: nextActiveTurnSnapshot,
            taskGraphLiveMonitor: activeMonitor,
          };
        });
      }
      return hasActiveHarnessRun || hasPendingApproval;
    } catch {
      // Keep current snapshot on transient harness query failures.
      return false;
    }
  }

  private activeHarnessSessionMonitor(liveMonitor: Awaited<ReturnType<typeof getOrchestrationHarnessSessionLiveMonitor>>) {
    if (!liveMonitor) {
      return null;
    }
    const direct = liveMonitor.monitor ?? null;
    if (direct) {
      return direct;
    }
    const activeTaskRunId = String(liveMonitor.active_task_run_id ?? "").trim();
    const taskRuns = Array.isArray(liveMonitor.task_runs) ? liveMonitor.task_runs : [];
    if (!activeTaskRunId) {
      return null;
    }
    return taskRuns.find((item) => String(item.task_run_id ?? item.task_run?.task_run_id ?? "").trim() === activeTaskRunId)
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

  private runtimeVisibleProgressText(value: unknown) {
    const text = String(value ?? "").trim();
    if (!text) return "";
    if (this.runtimeLooksLikeMachineStatusLeak(text)) return "";
    return text;
  }

  private runtimeLooksLikeMachineStatusLeak(value: string) {
    const lowered = String(value ?? "").trim().toLowerCase();
    if (!lowered) return false;
    const machineStates = new Set([
      "thinking",
      "working",
      "responding",
      "verifying",
      "waiting_for_tool",
      "tool_returned",
      "ready_to_finish",
      "blocked",
    ]);
    if (machineStates.has(lowered)) return true;
    if (/^(状态|status|completion[_\s-]*status|visible[_\s-]*status)\s*[:：]?\s*(thinking|working|responding|verifying|waiting_for_tool|tool_returned|ready_to_finish|blocked)$/i.test(lowered)) {
      return true;
    }
    const compact = lowered.replace(/[\s。.!！?？,，;；:：_-]+/g, "");
    return Array.from(machineStates).some((item) => item.replace(/_/g, "") === compact);
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
    if (GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(taskEnvironmentId)) {
      this.syncWorkspaceViewUrl("creative");
      this.store.setState((prev) => ({
        ...prev,
        activeWorkspaceView: "creative",
        chatTaskEnvironmentBinding: null,
      }));
      return;
    }
    void this.setActiveTaskEnvironment(taskEnvironmentId, {
      environmentLabel: binding.environment_label,
      source: binding.source,
    }).catch((error) => {
      this.store.setState((prev) => ({
        ...prev,
        taskEnvironmentCatalogError: this.errorMessage(error, "任务环境切换失败。"),
      }));
    });
  }

  private clearChatTaskEnvironmentBinding() {
    void this.setActiveTaskEnvironment(GENERAL_TASK_ENVIRONMENT_ID, { source: "conversation" }).catch((error) => {
      this.store.setState((prev) => ({
        ...prev,
        taskEnvironmentCatalogError: this.errorMessage(error, "任务环境切换失败。"),
      }));
    });
  }

  private hasActiveChatStream() {
    return this.store.getState().activeStreamSessionIds.length > 0;
  }

  private deferMonitorPollingForActiveStream() {
    if (typeof window === "undefined" || !this.hasActiveChatStream()) {
      return;
    }
    void this.runMonitorController.refresh({ schedule: false });
  }

  private async refreshRunMonitor() {
    await this.runMonitorController.refresh();
    void this.refreshCurrentSessionTokenStats("run_monitor_refresh").catch(() => undefined);
  }

  private async refreshCurrentSessionTokenStats(reason: string) {
    const now = Date.now();
    if (now - this.lastMonitorTokenStatsRefreshAt < TOKEN_STATS_MONITOR_REFRESH_INTERVAL_MS) {
      return;
    }
    if (this.tokenStatsRefreshInFlight) {
      return;
    }
    const sessionId = this.store.getState().currentSessionId;
    if (!sessionId) {
      return;
    }
    this.lastMonitorTokenStatsRefreshAt = now;
    this.tokenStatsRefreshInFlight = true;
    try {
      const scope = this.sessionScopeForSession(sessionId);
      const tokens = await getSessionTokens(sessionId, scope);
      if (this.store.getState().currentSessionId !== sessionId) {
        return;
      }
      this.store.setState((prev) => ({
        ...prev,
        tokenStats: tokens,
      }));
    } catch (error) {
      console.debug("[workspace-runtime] monitor token refresh skipped", {
        event: "monitor_token_refresh_failed",
        sessionId,
        reason,
        error: this.errorMessage(error, "会话 token 统计暂时读取失败。"),
      });
    } finally {
      this.tokenStatsRefreshInFlight = false;
    }
  }

  private async runMonitorAction(payload: RuntimeMonitorActionPayload): Promise<RuntimeMonitorActionResult | null> {
    return await this.runMonitorController.runAction(payload);
  }

  applyRunMonitorSnapshot(
    monitor: RuntimeMonitorEnvelope,
    options: { selectedSignalId?: string } = {},
  ) {
    this.runMonitorController.applySnapshot(monitor, options);
    this.syncCurrentSessionActivityFromRunMonitor();
  }

  applyRunMonitorStreamPayload(payload: RunMonitorEventPayload | null) {
    this.runMonitorController.applyStreamPayload(payload);
    this.syncCurrentSessionActivityFromRunMonitor();
    void this.refreshCurrentSessionTokenStats("run_monitor_stream").catch(() => undefined);
  }

  private openRunMonitorSignal(signalId: string) {
    this.runMonitorController.openSignal(signalId);
  }

  private syncCurrentSessionActivityFromRunMonitor() {
    const state = this.store.getState();
    const currentSessionId = String(state.currentSessionId || "").trim();
    if (!currentSessionId || !state.runMonitor) {
      return;
    }
    const signal = this.currentSessionActivitySignal(state.runMonitor, currentSessionId);
    if (!signal) {
      return;
    }
    const liveStatus = runtimeText(signal.status || signal.activity_state || signal.state);
    const taskRunId = runtimeText(signal.task_run_id || signal.detail_ref?.task_run_id || signal.task_instance_id);
    const graphRunId = runtimeText(signal.graph_run_id || signal.graph_ref?.graph_run_id || signal.detail_ref?.graph_run_id);
    this.updateSessionActivityFromLiveMonitor(
      liveStatus,
      taskRunId,
      graphRunId,
      this.runMonitorSignalControlState(signal),
      signal as unknown as Record<string, unknown>,
    );
  }

  private currentSessionActivitySignal(monitor: RuntimeMonitorEnvelope, currentSessionId: string): RuntimeMonitorSignal | null {
    const candidates = allRunMonitorSignals(monitor)
      .filter((signal) => this.runMonitorSignalSessionId(signal) === currentSessionId)
      .filter((signal) => !this.runMonitorSignalHidden(signal))
      .filter((signal) => this.shouldSyncRunMonitorSignalActivity(signal));
    if (!candidates.length) {
      return null;
    }
    return [...candidates].sort((left, right) =>
      this.runMonitorSignalActivityRank(right) - this.runMonitorSignalActivityRank(left)
      || Number(right.timestamps?.last_activity_at ?? right.timestamps?.updated_at ?? 0) - Number(left.timestamps?.last_activity_at ?? left.timestamps?.updated_at ?? 0)
      || Number(right.priority ?? 0) - Number(left.priority ?? 0)
    )[0] ?? null;
  }

  private runMonitorSignalSessionId(signal: RuntimeMonitorSignal) {
    const navigation = signal.navigation_target && typeof signal.navigation_target === "object" && !Array.isArray(signal.navigation_target)
      ? signal.navigation_target as Record<string, unknown>
      : {};
    return runtimeText(navigation.session_id || signal.session_id || signal.raw_refs?.session_id);
  }

  private runMonitorSignalHidden(signal: RuntimeMonitorSignal) {
    const visibility = signal.visibility && typeof signal.visibility === "object" && !Array.isArray(signal.visibility)
      ? signal.visibility
      : {};
    return visibility.hidden === true || visibility.visible === false;
  }

  private shouldSyncRunMonitorSignalActivity(signal: RuntimeMonitorSignal) {
    const activityState = runtimeText(signal.activity_state || signal.activity?.activity_state);
    const status = runtimeText(signal.status);
    const lifecycle = runtimeText(signal.lifecycle);
    const bucket = runtimeText(signal.bucket);
    const state = runtimeText(signal.state);
    const recoveryCause = runtimeText(signal.recovery_cause);
    const controlReason = runtimeText(signal.control_reason || signal.activity?.control_reason);
    if (recoveryCause === "runtime_restart" || controlReason === "runtime_restart_waiting_resume") {
      return true;
    }
    return ["waiting", "paused", "stale", "failed"].includes(activityState)
      || ["waiting", "attention", "stale", "failed"].includes(state)
      || ["waiting_executor", "waiting_approval", "waiting_safe_boundary", "blocked", "failed", "error"].includes(status)
      || ["waiting", "action_required", "paused", "stale", "failed"].includes(lifecycle)
      || ["waiting", "diagnostics", "failed"].includes(bucket);
  }

  private runMonitorSignalActivityRank(signal: RuntimeMonitorSignal) {
    const activityState = runtimeText(signal.activity_state || signal.activity?.activity_state);
    const status = runtimeText(signal.status);
    const state = runtimeText(signal.state);
    if (runtimeText(signal.recovery_cause) === "runtime_restart" || runtimeText(signal.control_reason || signal.activity?.control_reason) === "runtime_restart_waiting_resume") {
      return 60;
    }
    if (status === "waiting_approval" || status === "waiting_safe_boundary") return 55;
    if (activityState === "waiting" || state === "waiting" || status === "waiting_executor") return 50;
    if (activityState === "paused") return 45;
    if (activityState === "failed" || state === "failed" || status === "failed" || status === "error") return 40;
    if (activityState === "stale" || state === "stale") return 30;
    return 10;
  }

  private runMonitorSignalControlState(signal: RuntimeMonitorSignal) {
    const activity = signal.activity && typeof signal.activity === "object" && !Array.isArray(signal.activity)
      ? signal.activity
      : {};
    const controlCapability = signal.control_capability && typeof signal.control_capability === "object" && !Array.isArray(signal.control_capability)
      ? signal.control_capability
      : {};
    return runtimeText(
      activity.control_state
      || controlCapability.control_state
      || signal.raw_refs?.control_state
    );
  }

  private updateSessionActivityFromLiveMonitor(liveStatus: string, taskRunId: string, graphRunId: string, controlState = "", monitor: Record<string, unknown> | null = null) {
    const normalizedStatus = liveStatus.trim();
    const normalizedControlState = controlState.trim();
    if (!normalizedStatus) {
      return;
    }
    const monitorRecord = monitor && typeof monitor === "object" && !Array.isArray(monitor) ? monitor : {};
    const activityRecord = monitorRecord.activity && typeof monitorRecord.activity === "object" && !Array.isArray(monitorRecord.activity)
      ? monitorRecord.activity as Record<string, unknown>
      : {};
    const projectedActivityState = normalizedStatus === "stale"
      ? ""
      : String(monitorRecord.activity_state || activityRecord.activity_state || "").trim();
    const effectiveStatus = projectedActivityState === "waiting" ? "waiting_executor" : projectedActivityState || normalizedStatus;
    const recoveryCause = String(monitorRecord.recovery_cause || "").trim();
    const controlReason = String(monitorRecord.control_reason || "").trim();
    const runtimeRestartWaitingResume = recoveryCause === "runtime_restart" || controlReason === "runtime_restart_waiting_resume";
    const projectedTitle = this.runtimeVisibleProgressText(monitorRecord.activity_label || activityRecord.activity_label);
    const latestProgress = monitorRecord.latest_progress && typeof monitorRecord.latest_progress === "object" && !Array.isArray(monitorRecord.latest_progress)
      ? monitorRecord.latest_progress as Record<string, unknown>
      : {};
    const projectedDetail = this.runtimeVisibleProgressText(
      activityRecord.detail
      || monitorRecord.activity_detail
      || monitorRecord.latest_public_progress_note
      || latestProgress.current_judgment
      || latestProgress.next_action
      || latestProgress.summary
      || monitorRecord.summary
      || monitorRecord.latest_step_summary,
    );
    if (effectiveStatus === "stale") {
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "warning",
          title: "等待检查",
          detail: "运行已经停滞，需要在监控中检查或关闭运行",
          event: "runtime_live_monitor",
          receipt: {
            level: "warning",
            title: "等待检查",
            body: "运行已经停滞，需要在监控中检查或关闭运行。",
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
    if (effectiveStatus === "paused" || normalizedControlState === "paused") {
      const title = projectedTitle || "已暂停";
      const detail = projectedDetail || "当前处理已停在可继续状态，可以直接说继续。";
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "waiting",
          title,
          detail,
          event: "runtime_live_monitor",
          receipt: {
            level: "waiting",
            title,
            body: detail.endsWith("。") ? detail : `${detail}。`,
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
          detail: stopping ? "停止请求已记录，当前步骤到达运行边界后结束" : "暂停请求已记录，当前步骤到达运行边界后暂停",
          event: "runtime_live_monitor",
          receipt: {
            level: "running",
            title: stopping ? "正在停止" : "正在暂停",
            body: stopping ? "停止请求已记录，当前步骤到达运行边界后结束。" : "暂停请求已记录，当前步骤到达运行边界后暂停。",
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
    if (effectiveStatus === "waiting_executor" || effectiveStatus === "waiting_approval" || effectiveStatus === "waiting_safe_boundary" || effectiveStatus === "blocked") {
      const title = projectedTitle || (runtimeRestartWaitingResume ? "运行时重启后待续跑" : effectiveStatus === "waiting_executor" ? "等待继续" : effectiveStatus === "waiting_approval" ? "等待确认" : effectiveStatus === "waiting_safe_boundary" ? "等待安全边界" : "运行受阻");
      const detail = projectedDetail || (runtimeRestartWaitingResume ? "后端运行时已重启，任务已停在可恢复边界；点击继续或发送继续后会从当前任务继续调度。" : effectiveStatus === "waiting_executor" ? "任务已进入等待队列。" : effectiveStatus === "waiting_approval" ? "需要确认后继续执行。" : effectiveStatus === "waiting_safe_boundary" ? "暂停或中断请求已记录，当前步骤到达安全边界后会暂停或结束。" : "当前处理受阻。");
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "waiting",
          title,
          detail,
          event: "runtime_live_monitor",
          receipt: {
            level: "waiting",
            title,
            body: detail.endsWith("。") ? detail : `${detail}。`,
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
    if (effectiveStatus === "running" || effectiveStatus === "created") {
      if (!projectedTitle && !projectedDetail) {
        return;
      }
      const title = projectedTitle || projectedDetail;
      const detail = projectedDetail && projectedDetail !== title ? projectedDetail : "";
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "running",
          title,
          detail,
          event: "runtime_live_monitor",
          receipt: {
            level: "running",
            title,
            body: detail ? detail.endsWith("。") ? detail : `${detail}。` : undefined,
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
    if (["completed", "complete", "success", "succeeded"].includes(effectiveStatus)) {
      if (!projectedTitle && !projectedDetail) {
        return;
      }
      const title = projectedTitle || projectedDetail;
      const detail = projectedDetail && projectedDetail !== title ? projectedDetail : "";
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "success",
          title,
          detail,
          event: "runtime_live_monitor",
          receipt: {
            level: "success",
            title,
            body: detail ? detail.endsWith("。") ? detail : `${detail}。` : undefined,
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
    if (["failed", "error"].includes(effectiveStatus)) {
      const title = projectedTitle || "处理失败";
      const detail = projectedDetail || "当前处理返回失败状态，请查看运行监控。";
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "error",
          title,
          detail,
          event: "runtime_live_monitor",
          receipt: {
            level: "error",
            title,
            body: detail.endsWith("。") ? detail : `${detail}。`,
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
    const message = errorDetailMessage(error);
    if (!message) {
      return fallback;
    }
    if (/request timed out after \d+ms/i.test(message)) {
      return `${fallback}（请求超时）`;
    }
    if (/failed to fetch|networkerror|load failed/i.test(message)) {
      return `${fallback}（连接中断）`;
    }
    return message;
  }
}
