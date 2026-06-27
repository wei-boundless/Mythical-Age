"use client";

import {
  submitGraphRunUntilIdle,
  loadFile,
  loadFileForSession,
  readManagedFile,
  createSession,
  deleteSession,
  deriveSessionTitleFromFirstUserMessage,
  enqueueQueuedChatInput,
  getChatRun,
  getLatestChatRunForSession,
  getModelProviderConfig,
  getImageAssetConfig,
  getTaskEnvironmentCatalog,
  getWorkspaceContext,
  getHarnessSessionLiveMonitor,
  approveHarnessTaskRunLaunch,
  approveHarnessTaskRunToolCall,
  pauseHarnessTaskRun,
  pauseGraphRun,
  getPermissionMode,
  resumeHarnessTaskRun,
  resumeGraphRun,
  setPermissionMode as setRuntimePermissionMode,
  setSessionActiveTaskEnvironment,
  setSessionChatModelSelection,
  setSessionPermissionMode,
  setWorkbenchCurrentSession,
  getSessionHistory,
  getSessionRuntimeProjection,
  getSessionSummary,
  getSessionTokens,
  getSessionWorkspaceTree,
  getWorkbenchCurrentSession,
  getProjectWorkspaceTree,
  interruptChatRun,
  listProjectWorkspaces,
  listProjectWorkspaceSessions,
  listFileChanges,
  listSessions,
  listSkills,
  renameSession,
  removeProjectWorkspace,
  saveFile,
  saveFileForSession,
  writeManagedFile,
  createProjectWorkspaceSession,
  selectManagedFileForOpen,
  selectProjectWorkspaceDirectory,
  stopHarnessTaskRun,
  clearChatStreamCursor,
  clearWorkbenchCurrentSession,
  readChatStreamCursor,
  streamChat,
  streamExistingChatRun,
  truncateSessionMessages,
  uploadChatAttachment
} from "@/lib/api";
import type { ChatAttachment, ChatRun, ChatStreamCursor, FileChangeRecord, ManagedFileTarget, PublicProjectionFrame, RunMonitorEventPayload, RunMonitorActionPayload, RunMonitorActionResult, RunMonitorEnvelope, RunMonitorSignal, SessionRuntimeAttachment, SessionScope, SessionSummary } from "@/lib/api";
import { publicRuntimeProgressText } from "@/lib/runtimeStatusText";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";

import { createIdleSessionActivity, type Store } from "./core";
import { reduceStreamEvent, startStreamingTurn, type StreamSession } from "./events";
import { projectionFrameFromRecord, rebuildProjectionViews } from "@/lib/projection/reducer";
import { RunMonitorController } from "../run-monitor/controller";
import { allRunMonitorSignals } from "../run-monitor/reducer";
import { chatThinkingModeFromProviderConfig, isOpenAIReasoningModel, normalizeChatThinkingMode } from "./runtime/chatThinking";
import {
  ACTIVE_TURN_STATES,
  DEFAULT_INSPECTOR_PATH,
  DEFAULT_PERMISSION_MODE,
  FRONTEND_EDITOR_CONTEXT_TEXT_LIMIT,
  GENERAL_TASK_ENVIRONMENT_ID,
  GRAPH_ONLY_TASK_ENVIRONMENT_IDS,
  LAST_ACTIVE_MAIN_AGENT_KEY,
  LAST_ACTIVE_TASK_ENVIRONMENT_KEY,
  MAIN_CHAT_POOL_KEY,
  MAX_LIVE_RUNTIME_PROGRESS_ENTRIES,
  SESSION_RUNTIME_PROJECTION_DELAY_MS,
  SESSION_TOKEN_STATS_DELAY_MS,
  TOKEN_STATS_MONITOR_REFRESH_INTERVAL_MS,
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
  readRememberedThinkingProjectionEnabled,
  readRememberedSessionRef,
  rememberChatStreamDisplayEnabled,
  rememberThinkingProjectionEnabled,
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
import type { ActiveMainAgentSelection, ActiveTurnSnapshot, ActiveTurnState, ChatMode, ChatModelSelection, ChatTaskEnvironmentBinding, ChatThinkingMode, FileChangeDiffCenterWorkspaceTarget, Message, PermissionMode, RuntimeLogCenterWorkspaceTarget, RuntimeProgressEntry, SessionEditorContext, SessionEditorPageStatePatch, SessionProjectionCenterWorkspaceTarget, SessionRef, StoreActions, StoreState, TaskGraphMonitorBinding, TaskGraphWorkspaceTarget, TaskSelectionState, WorkspaceView } from "./types";
import { makeId, toUiMessages } from "./utils";

type HarnessSessionMonitor = NonNullable<Awaited<ReturnType<typeof getHarnessSessionLiveMonitor>>["monitor"]>;
type ActiveChatStreamBinding = {
  streamRunId: string;
  taskRunId: string;
  turnId: string;
};

type PendingChatStreamInterruption = {
  streamEpoch: number;
  taskRunId: string;
  expectedTurnId: string;
};

const MANAGED_PROJECT_PROFILE_ID = "file_profile.managed_project_workspace";
const MANAGED_PROJECT_REPOSITORY_ID = "repo.managed_project.project_workspace";

const LEGACY_INTERNAL_INSPECTOR_PREFIXES = [
  "durable_memory/",
  "session-memory/",
  "sessions/",
  "knowledge/",
  "capability_system/skills/builtin/",
  "capability_system/skills/registries/",
  "capability_system/tools/registries/"
] as const;

type VisibleStreamStateOptions = {
  preserveTaskGraphLiveMonitor?: boolean;
  rebuildProjectionViews?: boolean;
};

type PendingVisibleStreamFlush = {
  streamState: StoreState;
  activeStreamSessionIds: string[];
  options: VisibleStreamStateOptions;
  event: string;
  data: Record<string, unknown>;
};

const DEFAULT_SESSION_TITLE = "New Session";
const VISIBLE_STREAM_FLUSH_FRAME_FALLBACK_MS = 16;

export class WorkspaceRuntime {
  private initializePromise: Promise<void> | null = null;
  private createSessionPromise: Promise<string> | null = null;
  private sessionDetailsRequest = 0;
  private sessionRuntimeProjectionRequest = 0;
  private sessionRuntimeProjectionTimer: ReturnType<typeof setTimeout> | null = null;
  private sessionTokenStatsTimer: ReturnType<typeof setTimeout> | null = null;
  private sessionHistoryInFlight = new Map<string, Promise<Awaited<ReturnType<typeof getSessionHistory>>>>();
  private harnessTurnHydrateRequest = 0;
  private workspaceTreeRequest = 0;
  private workspaceTreeInFlightKey = "";
  private workspaceTreeInFlightPromise: Promise<void> | null = null;
  private runMonitorController: RunMonitorController;
  private sessionRefreshTimers: number[] = [];
  private sessionListFailureNotifiedAt = 0;
  private tokenStatsRefreshInFlight = false;
  private lastMonitorTokenStatsRefreshAt = 0;
  private streamingSessionCache = new Map<string, Pick<StoreState, "messages" | "activeProjectionsByKey" | "harnessTurnSnapshot" | "activeTurnSnapshot">>();
  private activeChatStreamBindings = new Map<string, ActiveChatStreamBinding>();
  private chatStreamEpochBySession = new Map<string, number>();
  private pendingChatStreamInterruptions = new Map<string, PendingChatStreamInterruption>();
  private removedStreamingSessionIds = new Set<string>();
  private streamAbortControllers = new Map<string, AbortController>();
  private stoppedStreamingSessionIds = new Set<string>();
  private recoveringStreamSessionIds = new Set<string>();
  private pendingVisibleStreamFlushes = new Map<string, PendingVisibleStreamFlush>();
  private queuedVisibleUserInputsBySession = new Map<string, Map<string, Message>>();
  private pendingProjectionCommitHydrates = new Map<string, string>();
  private hydratedProjectionCommitKeys = new Set<string>();
  private firstUserTitleRequests = new Set<string>();
  private pendingChatModelSelections = new Map<string, string>();
  private chatModelSelectionPersistTimers = new Map<string, number>();
  private selectedWorkspaceFileTargets = new Map<string, ManagedFileTarget>();
  private fileChangeHydrateInFlight = new Map<string, Promise<void>>();
  private fileChangeHydratedAtByKey = new Map<string, number>();
  private fileChangeRecordFingerprints = new Map<string, string>();
  private disposed = false;

  readonly actions: StoreActions;

  constructor(private readonly store: Store<StoreState>) {
    const rememberedChatStreamDisplayEnabled = readRememberedChatStreamDisplayEnabled();
    if (rememberedChatStreamDisplayEnabled !== null) {
      this.store.setState((prev) => ({
        ...prev,
        chatStreamDisplayEnabled: rememberedChatStreamDisplayEnabled,
      }));
    }
    const rememberedThinkingProjectionEnabled = readRememberedThinkingProjectionEnabled();
    if (rememberedThinkingProjectionEnabled !== null) {
      this.store.setState((prev) => ({
        ...prev,
        thinkingProjectionEnabled: rememberedThinkingProjectionEnabled,
      }));
    }
    const rememberedMainAgent = this.rememberedMainAgentSelection();
    if (rememberedMainAgent) {
      this.store.setState((prev) => ({
        ...prev,
        activeMainAgent: rememberedMainAgent,
      }));
    }
    this.runMonitorController = new RunMonitorController(this.store, {
      applySelectedSessionShell: (sessionId, scope) => this.applySelectedSessionShell(sessionId, scope ? { scope, poolKey: sessionPoolKeyForScope(scope) } : undefined),
      bindTaskEnvironmentContext: (taskEnvironmentId, options) => this.bindTaskEnvironmentContext(taskEnvironmentId, options),
      workspaceViewForTaskEnvironment: (taskEnvironmentId) => this.workspaceViewForTaskEnvironment(taskEnvironmentId),
      refreshSessionDetails: (sessionId) => this.refreshSessionDetails(sessionId),
      hydrateLatestHarnessTurnSnapshot: (sessionId) => this.hydrateLatestHarnessTurnSnapshot(sessionId),
      syncWorkspaceViewUrl: (view) => this.syncWorkspaceViewUrl(view),
      onStreamPayload: (payload) => this.afterRunMonitorStreamPayload(payload),
    });
    this.actions = {
      setWorkspaceView: (view) => {
        this.setWorkspaceView(view);
      },
      refreshTaskEnvironmentCatalog: async () => {
        await this.refreshTaskEnvironmentCatalog();
      },
      setActiveTaskEnvironment: async (environmentId, options) => {
        await this.setActiveTaskEnvironment(environmentId, options);
      },
      setActiveMainAgent: async (selection) => {
        await this.setActiveMainAgent(selection);
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
      setThinkingProjectionEnabled: (enabled) => {
        this.setThinkingProjectionEnabled(enabled);
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
      selectWorkspaceFile: async () => {
        return await this.selectWorkspaceFile();
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
      hydrateFileChangesForSession: async (sessionId, options) => {
        await this.hydrateFileChangesForSession(sessionId, options);
      },
      applyFileChangeRecord: (record) => {
        this.noteFileChangeSignalFromRecord(record);
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
      setAgentSystemInspectorTarget: (target) => {
        this.setAgentSystemInspectorTarget(target);
      },
      setHarnessTurnSnapshot: (snapshot) => {
        this.setHarnessTurnSnapshot(snapshot);
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
      openWorkspaceFile: (path, options) => {
        this.openWorkspaceFile(path, options);
      },
      openFileChangeDiff: (target) => {
        this.openFileChangeDiff(target);
      },
      openRuntimeLog: (target) => {
        this.openRuntimeLog(target);
      },
      openSessionProjection: (target) => {
        this.openSessionProjection(target);
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
    if (this.disposed) {
      return;
    }
    this.runMonitorController.start();
  }

  async initialize() {
    if (this.disposed) {
      return;
    }
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
      const persistedSessionRef = await this.readPersistedCurrentSessionRef();
      const rememberedSessionRef = readRememberedSessionRef();
      const restoreCandidates = this.startupSessionRestoreCandidates(persistedSessionRef, rememberedSessionRef);
      for (const candidate of restoreCandidates) {
        const restored = await this.restoreRememberedSessionOnStartup(candidate);
        restoredCurrentSession = restored === "restored";
        if (restored === "non_main") {
          preferLatestVisibleSession = true;
        }
        if (restoredCurrentSession) {
          break;
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

  private startupSessionRestoreCandidates(...refs: Array<SessionRef | null | undefined>) {
    const candidates: SessionRef[] = [];
    const seen = new Set<string>();
    for (const ref of refs) {
      if (!ref?.sessionId) {
        continue;
      }
      const normalized = this.normalizeSessionRef(ref, this.store.getState());
      if (!normalized.sessionId) {
        continue;
      }
      const key = JSON.stringify({
        sessionId: normalized.sessionId,
        scope: normalized.scope ?? {},
        poolKey: normalized.poolKey ?? MAIN_CHAT_POOL_KEY,
      });
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      candidates.push(normalized);
    }
    return candidates.sort((left, right) => {
      const rightUpdatedAt = Number(right.updatedAt || 0);
      const leftUpdatedAt = Number(left.updatedAt || 0);
      if (rightUpdatedAt !== leftUpdatedAt) {
        return rightUpdatedAt - leftUpdatedAt;
      }
      return 0;
    });
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
        void this.hydrateLatestHarnessTurnSnapshot(summary.id).catch(() => undefined);
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
            void this.hydrateLatestHarnessTurnSnapshot(sessionId).catch(() => undefined);
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
          void this.hydrateLatestHarnessTurnSnapshot(currentSession.id).catch(() => undefined);
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
      inspectorContentSha256: "",
      inspectorDirty: false,
      inspectorTarget: null,
      inspectorLastChangeRecordId: "",
    }));
  }

  dispose() {
    this.disposed = true;
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
    this.sessionHistoryInFlight.clear();
    for (const timer of this.chatModelSelectionPersistTimers.values()) {
      window.clearTimeout(timer);
    }
    this.chatModelSelectionPersistTimers.clear();
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
    this.requestRecentFirstUserSessionTitlesInBackground(sessions);
    return sessions;
  }

  private requestRecentFirstUserSessionTitlesInBackground(sessions: SessionSummary[]) {
    let requested = 0;
    for (const session of sessions) {
      if (requested >= 3) return;
      if (Number(session.message_count || 0) <= 0) continue;
      if (!this.isDefaultSessionTitle(session.title) && !this.isAssistantArtifactSessionTitle(session.title)) continue;
      this.requestFirstUserSessionTitleInBackground(session.id);
      requested += 1;
    }
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
        void this.hydrateLatestHarnessTurnSnapshot(nextSession.id).catch(() => undefined);
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
      void this.hydrateLatestHarnessTurnSnapshot(session.id).catch(() => undefined);
    }
  }

  private refreshMainSessionPoolInBackground() {
    void this.refreshMainSessionPool().catch((error) => {
      this.noteSessionRefreshFailure(error);
    });
  }

  private requestFirstUserSessionTitleInBackground(sessionId: string) {
    const normalizedSessionId = String(sessionId || "").trim();
    if (
      !normalizedSessionId
      || this.firstUserTitleRequests.has(normalizedSessionId)
      || !this.shouldDeriveSessionTitleFromFirstUser(normalizedSessionId)
    ) {
      return;
    }
    this.firstUserTitleRequests.add(normalizedSessionId);
    void deriveSessionTitleFromFirstUserMessage(normalizedSessionId, this.sessionScopeForSession(normalizedSessionId))
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
        console.debug("[workspace-runtime] first user session title derivation skipped", {
          event: "first_user_session_title_derivation_failed",
          sessionId: normalizedSessionId,
          error: this.errorMessage(error, "会话摘要命名失败。"),
        });
      })
      .finally(() => {
        this.firstUserTitleRequests.delete(normalizedSessionId);
      });
  }

  private shouldDeriveSessionTitleFromFirstUser(sessionId: string, state = this.store.getState()) {
    const session = state.sessions.find((item) => item.id === sessionId)
      ?? state.projectSessions.find((item) => item.id === sessionId);
    return Boolean(session && (this.isDefaultSessionTitle(session.title) || this.isAssistantArtifactSessionTitle(session.title)));
  }

  private isDefaultSessionTitle(title: string | null | undefined) {
    return String(title || "").trim() === DEFAULT_SESSION_TITLE;
  }

  private isAssistantArtifactSessionTitle(title: string | null | undefined) {
    const text = String(title || "").replace(/\s+/g, " ").trim();
    if (!text) return false;
    if (["```", "##", "---", "|---", "###"].some((marker) => text.includes(marker))) return true;
    if (
      [
        "经过全面排查",
        "以下是我的",
        "这是我的",
        "这是一个独立的",
        "这是一个独立的小型交付请求",
        "好，我已经",
        "好了，我已经",
        "好的，我已经",
        "现在我已经",
        "我现在已经",
        "我已经完成",
        "我已经读完",
        "已完成",
      ].some((prefix) => text.startsWith(prefix))
    ) {
      return true;
    }
    return ["诊断结果", "诊断结论", "修改已完成", "交付请求", "以下是修复结果"].some((fragment) => text.includes(fragment));
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
      const history = await this.getSessionHistoryCoalesced(sessionId, scope);
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
        const selectedChatModelId = history.conversation_state
          ? this.pendingChatModelSelections.get(sessionId) ?? this.chatModelSelectionIdFromConversationState(history.conversation_state, prev.selectedChatModelId)
          : this.normalizeChatModelSelectionId(prev.selectedChatModelId);
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
          selectedChatModelId,
          selectedChatMode: this.resolveSelectedChatMode(selectedChatModelId, prev.modelProviderConfig),
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

  private getSessionHistoryCoalesced(sessionId: string, scope: Partial<SessionScope> | undefined) {
    const requestKey = this.sessionHistoryRequestKey(sessionId, scope);
    const existing = this.sessionHistoryInFlight.get(requestKey);
    if (existing) {
      return existing;
    }
    const request = getSessionHistory(sessionId, scope);
    this.sessionHistoryInFlight.set(requestKey, request);
    void request.finally(() => {
      if (this.sessionHistoryInFlight.get(requestKey) === request) {
        this.sessionHistoryInFlight.delete(requestKey);
      }
    }).catch(() => undefined);
    return request;
  }

  private sessionHistoryRequestKey(sessionId: string, scope: Partial<SessionScope> | undefined) {
    const normalizedScope = this.normalizeSessionScope(scope);
    return `${sessionId.trim()}|${JSON.stringify(normalizedScope ?? {})}`;
  }

  private invalidateSessionHistoryCache(sessionId: string) {
    const prefix = `${sessionId.trim()}|`;
    for (const key of this.sessionHistoryInFlight.keys()) {
      if (key.startsWith(prefix)) {
        this.sessionHistoryInFlight.delete(key);
      }
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
      return this.mergeActiveStreamProjectionMessages(current.messages, refreshedMessages);
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
      return this.mergeActiveStreamProjectionState(current.activeProjectionsByKey, refreshedActiveProjections);
    }
    return refreshedActiveProjections;
  }

  private mergeActiveStreamProjectionMessages(currentMessages: Message[], refreshedMessages: Message[]) {
    if (!refreshedMessages.length) {
      return currentMessages;
    }
    const nextMessages = [...currentMessages];
    const messageIds = new Set(nextMessages.map((message) => message.id));
    for (const refreshed of refreshedMessages) {
      const existingIndex = nextMessages.findIndex((message) =>
        message.id === refreshed.id
        || (
          message.role === refreshed.role
          && message.role === "assistant"
          && this.messagesShareRuntimeIdentity(message, refreshed)
        )
        || (
          message.role === refreshed.role
          && message.role === "user"
          && Boolean(message.sourceTurnId && refreshed.sourceTurnId && message.sourceTurnId === refreshed.sourceTurnId)
        )
      );
      if (existingIndex >= 0) {
        nextMessages[existingIndex] = this.mergeActiveStreamProjectionMessage(nextMessages[existingIndex], refreshed);
        messageIds.add(nextMessages[existingIndex].id);
        continue;
      }
      if (!this.refreshedMessageCanEnterActiveStream(refreshed)) {
        continue;
      }
      if (!messageIds.has(refreshed.id)) {
        nextMessages.push(refreshed);
        messageIds.add(refreshed.id);
      }
    }
    return this.sortMessagesBySourceIndex(nextMessages);
  }

  private refreshedMessageCanEnterActiveStream(message: Message) {
    if (message.role !== "assistant") {
      return true;
    }
    return Boolean(message.projectionKeyString || message.projectionView);
  }

  private mergeActiveStreamProjectionMessage(current: Message, refreshed: Message): Message {
    if (current.role !== refreshed.role) {
      return current;
    }
    return {
      ...current,
      content: current.content || refreshed.content,
      toolCalls: current.toolCalls.length ? current.toolCalls : refreshed.toolCalls,
      retrievals: current.retrievals.length ? current.retrievals : refreshed.retrievals,
      sourceIndex: current.sourceIndex ?? refreshed.sourceIndex,
      sourceTurnId: current.sourceTurnId || refreshed.sourceTurnId,
      sourceStreamRunId: current.sourceStreamRunId || refreshed.sourceStreamRunId,
      sourceRunId: current.sourceRunId || refreshed.sourceRunId,
      sourceTaskRunId: current.sourceTaskRunId || refreshed.sourceTaskRunId,
      sourceTurnRunId: current.sourceTurnRunId || refreshed.sourceTurnRunId,
      projectionKeyString: refreshed.projectionKeyString || current.projectionKeyString,
      projectionView: current.projectionView ?? refreshed.projectionView,
      closeoutSummary: current.closeoutSummary ?? refreshed.closeoutSummary,
      runtimeLogRef: current.runtimeLogRef ?? refreshed.runtimeLogRef,
      toolEventCount: current.toolEventCount ?? refreshed.toolEventCount,
      answerChannel: current.answerChannel ?? refreshed.answerChannel,
      answerSource: current.answerSource ?? refreshed.answerSource,
      answerCanonicalState: current.answerCanonicalState ?? refreshed.answerCanonicalState,
      answerPersistPolicy: current.answerPersistPolicy ?? refreshed.answerPersistPolicy,
      answerFinalizationPolicy: current.answerFinalizationPolicy ?? refreshed.answerFinalizationPolicy,
      answerFallbackReason: current.answerFallbackReason ?? refreshed.answerFallbackReason,
      answerSelectedChannel: current.answerSelectedChannel ?? refreshed.answerSelectedChannel,
      answerSelectedSource: current.answerSelectedSource ?? refreshed.answerSelectedSource,
      answerLeakFlags: current.answerLeakFlags ?? refreshed.answerLeakFlags,
      image: current.image ?? refreshed.image ?? null,
      attachments: current.attachments?.length ? current.attachments : refreshed.attachments,
    };
  }

  private mergeActiveStreamProjectionState(
    current: StoreState["activeProjectionsByKey"],
    refreshed: StoreState["activeProjectionsByKey"],
  ) {
    const next = { ...current };
    for (const [key, refreshedProjection] of Object.entries(refreshed)) {
      const currentProjection = next[key];
      if (!currentProjection || this.projectionStateIsNewer(refreshedProjection, currentProjection)) {
        next[key] = refreshedProjection;
      }
    }
    return next;
  }

  private projectionStateIsNewer(
    candidate: StoreState["activeProjectionsByKey"][string],
    current: StoreState["activeProjectionsByKey"][string],
  ) {
    const candidateOffset = Number(candidate.ledger?.cursor?.maxOffset ?? 0);
    const currentOffset = Number(current.ledger?.cursor?.maxOffset ?? 0);
    if (candidateOffset !== currentOffset) {
      return candidateOffset > currentOffset;
    }
    if (!current.view && candidate.view) {
      return true;
    }
    const candidateContentLength = String(candidate.view?.canonicalContent ?? candidate.ledger?.bodyText ?? "").length;
    const currentContentLength = String(current.view?.canonicalContent ?? current.ledger?.bodyText ?? "").length;
    return candidateContentLength > currentContentLength;
  }

  private sortMessagesBySourceIndex(messages: Message[]) {
    return [...messages].sort((left, right) => {
      const leftIndex = left.sourceIndex ?? Number.MAX_SAFE_INTEGER;
      const rightIndex = right.sourceIndex ?? Number.MAX_SAFE_INTEGER;
      if (leftIndex !== rightIndex) return leftIndex - rightIndex;
      if (left.role !== right.role) return left.role === "user" ? -1 : 1;
      return left.id.localeCompare(right.id);
    });
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

  private async enqueueUserInputForSession(sessionId: string, content: string, messageId = makeId()) {
    this.applyQueuedUserInputVisibleState(sessionId, content, messageId);
    try {
      const requestState = this.store.getState();
      const response = await enqueueQueuedChatInput(sessionId, {
        message: content,
        client_message_id: messageId,
        session_scope: this.sessionScopeForSession(sessionId),
        environment_binding: this.chatEnvironmentBindingPayload(requestState),
        runtime_contract: this.chatRuntimeContractPayload(requestState),
        model_selection: this.chatModelSelectionPayload(requestState),
        permission_mode: this.permissionModeForSession(sessionId, requestState),
        editor_context: this.chatEditorContextPayload(requestState, sessionId),
      });
      const streamRunId = String(response.item?.dispatch_stream_run_id ?? "").trim();
      if (streamRunId && !this.store.getState().activeStreamSessionIds.includes(sessionId)) {
        const run = await getChatRun(streamRunId).catch(() => null);
        const eventLogId = String(run?.event_log_id ?? "").trim();
        this.startRecoveredChatRunStream(
          sessionId,
          streamRunId,
          {
            streamRunId,
            eventLogId,
            lastEventOffset: -1,
            lastEventId: "",
          },
          run,
        );
      } else if (this.queuedInputShouldReattachActiveStream(response.item, sessionId)) {
        void this.reattachChatRunForSession(sessionId).catch(() => undefined);
      }
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: prev.currentSessionId === sessionId
          ? {
              level: "error",
              title: "队列提交失败",
              detail: this.errorMessage(error, "无法把输入加入后端队列，请确认后端服务仍在 127.0.0.1:8003。"),
              event: "user_input_queue_failed",
              receipt: {
                level: "error",
                title: "队列提交失败",
                body: this.errorMessage(error, "无法把输入加入后端队列，请确认后端服务仍在 127.0.0.1:8003。"),
                debug: { event: "user_input_queue_failed" },
              },
              updatedAt: Date.now(),
            }
          : prev.sessionActivity,
      }));
      throw error;
    }
  }

  private applyQueuedUserInputVisibleState(sessionId: string, content: string, messageId: string) {
    const queuedMessage = this.queuedUserInputMessage(content, messageId);
    const activityTitle = "已加入当前回合";
    const activityDetail = "agent 下一次判断前会纳入这条补充。";
    this.rememberQueuedVisibleUserInput(sessionId, queuedMessage);
    this.patchPendingVisibleStreamFlushWithQueuedInput(sessionId);
    this.patchStreamingSessionCacheWithQueuedInput(sessionId);
    this.store.setState((prev) => {
      const shouldPatchVisibleMessages = prev.currentSessionId === sessionId;
      const alreadyVisible = prev.messages.some((message) => message.id === messageId);
      const nextMessages = shouldPatchVisibleMessages
        ? alreadyVisible
          ? prev.messages.map((message) => message.id === messageId ? { ...message, content } : message)
          : [...prev.messages, queuedMessage]
        : prev.messages;
      return {
        ...prev,
        messages: nextMessages,
        sessionActivity: prev.currentSessionId === sessionId
          ? {
              level: "running",
              title: activityTitle,
              detail: activityDetail,
              event: "user_input_queued",
              receipt: {
                level: "running",
                title: activityTitle,
                body: activityDetail,
                debug: { event: "user_input_queued" },
              },
              updatedAt: Date.now(),
            }
          : prev.sessionActivity,
        sessionActivitiesById: {
          ...prev.sessionActivitiesById,
          [sessionId]: {
            level: "running",
            title: activityTitle,
            detail: activityDetail,
            event: "user_input_queued",
            receipt: {
              level: "running",
              title: activityTitle,
              body: activityDetail,
              debug: { event: "user_input_queued" },
            },
            updatedAt: Date.now(),
          },
        },
      };
    });
  }

  private queuedUserInputMessage(content: string, messageId: string): Message {
    return {
      id: messageId,
      role: "user",
      content,
      toolCalls: [],
      retrievals: [],
    };
  }

  private rememberQueuedVisibleUserInput(sessionId: string, message: Message) {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId || message.role !== "user") {
      return;
    }
    const existing = this.queuedVisibleUserInputsBySession.get(normalizedSessionId) ?? new Map<string, Message>();
    existing.set(message.id, message);
    this.queuedVisibleUserInputsBySession.set(normalizedSessionId, existing);
  }

  private queuedVisibleUserMessages(sessionId: string) {
    return Array.from(this.queuedVisibleUserInputsBySession.get(sessionId)?.values() ?? []);
  }

  private mergeQueuedVisibleUserInputs(sessionId: string, messages: Message[]) {
    const queuedMessages = this.queuedVisibleUserMessages(sessionId);
    if (!queuedMessages.length) {
      return messages;
    }
    const existingIds = new Set(messages.map((message) => message.id));
    const merged = messages.map((message) => {
      const queued = this.queuedVisibleUserInputsBySession.get(sessionId)?.get(message.id);
      return queued && message.role === "user"
        ? { ...message, content: queued.content, attachments: queued.attachments ?? message.attachments }
        : message;
    });
    for (const queued of queuedMessages) {
      if (!existingIds.has(queued.id)) {
        merged.push(queued);
      }
    }
    return merged;
  }

  private patchPendingVisibleStreamFlushWithQueuedInput(sessionId: string) {
    const pending = this.pendingVisibleStreamFlushes.get(sessionId);
    if (!pending) {
      return;
    }
    const queuedActivity = this.visibleQueuedUserInputActivity(sessionId);
    pending.streamState = {
      ...pending.streamState,
      messages: this.mergeQueuedVisibleUserInputs(sessionId, pending.streamState.messages),
      sessionActivity: queuedActivity ?? pending.streamState.sessionActivity,
      sessionActivitiesById: {
        ...pending.streamState.sessionActivitiesById,
        ...(queuedActivity
          ? { [sessionId]: queuedActivity }
          : {}),
      },
    };
  }

  private patchStreamingSessionCacheWithQueuedInput(sessionId: string) {
    const cache = this.streamingSessionCache.get(sessionId);
    if (!cache) {
      return;
    }
    this.streamingSessionCache.set(sessionId, {
      ...cache,
      messages: this.mergeQueuedVisibleUserInputs(sessionId, cache.messages),
    });
  }

  private visibleQueuedUserInputActivity(sessionId: string): StoreState["sessionActivity"] | null {
    if (!this.queuedVisibleUserInputsBySession.get(sessionId)?.size) {
      return null;
    }
    const activityTitle = "已加入当前回合";
    const activityDetail = "agent 下一次判断前会纳入这条补充。";
    return {
      level: "running",
      title: activityTitle,
      detail: activityDetail,
      event: "user_input_queued",
      receipt: {
        level: "running",
        title: activityTitle,
        body: activityDetail,
        debug: { event: "user_input_queued" },
      },
      updatedAt: Date.now(),
    };
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
        inspectorContentSha256: "",
        inspectorDirty: false,
        inspectorTarget: null,
        inspectorLastChangeRecordId: "",
      };
    }
    return {
      ...state,
      inspectorPath: context.inspectorPath || context.activeFilePath || DEFAULT_INSPECTOR_PATH,
      inspectorContent: context.inspectorContent || "",
      inspectorContentSha256: context.inspectorContentSha256 || "",
      inspectorDirty: Boolean(context.inspectorDirty),
      inspectorTarget: context.inspectorTarget || null,
      inspectorLastChangeRecordId: context.inspectorLastChangeRecordId || "",
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
      inspectorContentSha256: "",
      inspectorDirty: false,
      inspectorTarget: null,
      inspectorLastChangeRecordId: "",
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
      inspectorContentSha256: String(patch.inspectorContentSha256 ?? current.inspectorContentSha256 ?? ""),
      inspectorDirty: Boolean(patch.inspectorDirty ?? current.inspectorDirty),
      inspectorTarget: patch.inspectorTarget === undefined ? current.inspectorTarget ?? null : patch.inspectorTarget,
      inspectorLastChangeRecordId: String(patch.inspectorLastChangeRecordId ?? current.inspectorLastChangeRecordId ?? ""),
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
    latency?: { sessionId: string; event: string; data: Record<string, unknown> },
  ) {
    const visibleStreamState = options.rebuildProjectionViews
      ? rebuildProjectionViews(streamState)
      : streamState;
    const visibleSessionId = String(latency?.sessionId || visibleStreamState.currentSessionId || this.store.getState().currentSessionId || "").trim();
    const mergedMessages = visibleSessionId
      ? this.mergeQueuedVisibleUserInputs(visibleSessionId, visibleStreamState.messages)
      : visibleStreamState.messages;
    const queuedActivity = visibleSessionId ? this.visibleQueuedUserInputActivity(visibleSessionId) : null;
    const nextSessionActivity = queuedActivity && this.streamActivityCanKeepQueuedInputVisible(visibleStreamState.sessionActivity)
      ? queuedActivity
      : visibleStreamState.sessionActivity;
    this.store.setState((prev) => ({
      ...prev,
      messages: mergedMessages,
      activeProjectionsByKey: visibleStreamState.activeProjectionsByKey,
      harnessTurnSnapshot: visibleStreamState.harnessTurnSnapshot,
      activeTurnSnapshot: visibleStreamState.activeTurnSnapshot,
      taskGraphLiveMonitor: options.preserveTaskGraphLiveMonitor ? prev.taskGraphLiveMonitor : null,
      activeStreamSessionIds,
      isStreaming: activeStreamSessionIds.length > 0,
      chatStreamConnectionStatus: visibleStreamState.chatStreamConnectionStatus,
      sessionActivity: nextSessionActivity,
      sessionActivitiesById: {
        ...prev.sessionActivitiesById,
        ...visibleStreamState.sessionActivitiesById,
        ...(queuedActivity && visibleSessionId && this.streamActivityCanKeepQueuedInputVisible(visibleStreamState.sessionActivitiesById[visibleSessionId])
          ? { [visibleSessionId]: queuedActivity }
          : {}),
      },
    }));
    if (latency?.sessionId) {
      this.streamingSessionCache.set(latency.sessionId, {
        messages: mergedMessages,
        activeProjectionsByKey: visibleStreamState.activeProjectionsByKey,
        harnessTurnSnapshot: visibleStreamState.harnessTurnSnapshot,
        activeTurnSnapshot: visibleStreamState.activeTurnSnapshot,
      });
    }
    if (latency) {
      this.recordChatStreamLatency(latency.sessionId, latency.event, latency.data);
    }
  }

  private streamActivityCanKeepQueuedInputVisible(activity: StoreState["sessionActivity"] | undefined) {
    if (!activity) {
      return true;
    }
    const event = String(activity.event || "").trim();
    return !event
      || event === "user_input_queued"
      || event === "stream_cursor_restore_started"
      || event === "stream_reconnecting"
      || event === "stream_reconnect_failed";
  }

  private queuedInputShouldReattachActiveStream(item: { input_policy?: string; expected_active_turn_id?: string; task_run_id?: string } | undefined, sessionId: string) {
    const state = this.store.getState();
    if (state.activeStreamSessionIds.includes(sessionId)) {
      return false;
    }
    if (state.currentSessionId !== sessionId) {
      return false;
    }
    const inputPolicy = String(item?.input_policy || "").trim().toLowerCase();
    const expectedTurnId = String(item?.expected_active_turn_id || "").trim();
    const taskRunId = String(item?.task_run_id || "").trim();
    return inputPolicy === "steer" || Boolean(expectedTurnId || taskRunId);
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
      this.deferVisibleStreamState(sessionId, streamState, activeStreamSessionIds, {
        ...options,
        rebuildProjectionViews: true,
      }, event, data);
      return;
    }
    this.flushVisibleStreamStateNow(sessionId, streamState, activeStreamSessionIds, options, event, data);
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
    event: string,
    data: Record<string, unknown>,
  ) {
    const existing = this.pendingVisibleStreamFlushes.get(sessionId);
    if (existing) {
      existing.streamState = streamState;
      existing.activeStreamSessionIds = activeStreamSessionIds;
      existing.options = options;
      existing.event = event;
      existing.data = data;
      return;
    }
    const pending: PendingVisibleStreamFlush = {
      streamState,
      activeStreamSessionIds,
      options,
      event,
      data,
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
      this.applyVisibleStreamState(latest.streamState, latest.activeStreamSessionIds, latest.options, {
        sessionId,
        event: latest.event,
        data: latest.data,
      });
    };
    this.scheduleVisibleStreamFrame(flush);
  }

  private scheduleVisibleStreamFrame(callback: () => void) {
    if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => callback());
      return;
    }
    const scheduleTimeout = typeof window !== "undefined" && typeof window.setTimeout === "function"
      ? window.setTimeout.bind(window)
      : globalThis.setTimeout.bind(globalThis);
    scheduleTimeout(callback, VISIBLE_STREAM_FLUSH_FRAME_FALLBACK_MS);
  }

  private flushVisibleStreamStateNow(
    sessionId: string,
    streamState: StoreState,
    activeStreamSessionIds: string[],
    options: VisibleStreamStateOptions = {},
    event?: string,
    data?: Record<string, unknown>,
  ) {
    this.clearPendingVisibleStreamFlush(sessionId);
    if (this.store.getState().currentSessionId !== sessionId) {
      return;
    }
    this.applyVisibleStreamState(
      streamState,
      activeStreamSessionIds,
      options,
      event && data ? { sessionId, event, data } : undefined,
    );
  }

  private clearPendingVisibleStreamFlush(sessionId: string) {
    const pending = this.pendingVisibleStreamFlushes.get(sessionId);
    if (!pending) {
      return;
    }
    this.pendingVisibleStreamFlushes.delete(sessionId);
  }

  private clearAllPendingVisibleStreamFlushes() {
    for (const sessionId of Array.from(this.pendingVisibleStreamFlushes.keys())) {
      this.clearPendingVisibleStreamFlush(sessionId);
    }
  }

  private recordChatStreamLatency(sessionId: string, event: string, data: Record<string, unknown>) {
    const diagnostics = data.diagnostics && typeof data.diagnostics === "object" && !Array.isArray(data.diagnostics)
      ? data.diagnostics as Record<string, unknown>
      : {};
    const hasDiagnostics = Object.keys(diagnostics).length > 0;
    if (!hasDiagnostics) {
      return;
    }
    const summary = {
      sessionId,
      event,
      eventOffset: finiteNumber(data.event_offset),
      serverEventCreatedAt: finiteNumber(diagnostics.server_event_created_at),
      serverWsSentAt: finiteNumber(diagnostics.server_ws_sent_at),
      clientReceivedAt: finiteNumber(diagnostics.client_received_at),
      clientVisibleFlushedAt: clientNow(),
      updatedAt: Date.now(),
    };
    this.store.setState((prev) => ({
      ...prev,
      chatStreamLatencySummary: summary,
    }));
  }

  private async createFreshSession() {
    if (this.createSessionPromise) {
      return this.createSessionPromise;
    }

    const pending = (async () => {
      const initialState = this.store.getState();
      const activeProjectKey = initialState.activeProjectKey;
      const selectedChatModelId = this.normalizeChatModelSelectionId(initialState.selectedChatModelId);
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
            conversation_state: this.conversationStateWithChatModelSelection(
              this.conversationStateWithPermissionMode(created.conversation_state, permissionMode),
              selectedChatModelId,
            ),
          },
          ...prev.sessions.filter((session) => session.id !== created.id),
        ],
        projectSessions: activeProjectKey
          ? [
              {
                ...created,
                conversation_state: this.conversationStateWithChatModelSelection(
                  this.conversationStateWithPermissionMode(created.conversation_state, permissionMode),
                  selectedChatModelId,
                ),
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
        selectedChatModelId,
        selectedChatMode: this.resolveSelectedChatMode(selectedChatModelId, prev.modelProviderConfig),
        messages: [],
        harnessTurnSnapshot: null,
        taskGraphLiveMonitor: null,
        activeTurnSnapshot: null,
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
      await this.persistSelectedChatModel(created.id, selectedChatModelId).catch((error) => {
        console.debug("[workspace-runtime] default chat model selection persist skipped", {
          event: "conversation_chat_model_selection_default_persist_failed",
          error: this.errorMessage(error, "默认模型选择写入失败。"),
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
      harnessTurnSnapshot: null,
      taskGraphLiveMonitor: null,
      activeTurnSnapshot: null,
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
    await this.hydrateLatestHarnessTurnSnapshot(normalized.sessionId).catch(() => false);
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
      ...(Number.isFinite(Number(ref.updatedAt)) && Number(ref.updatedAt) > 0 ? { updatedAt: Number(ref.updatedAt) } : {}),
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

  private normalizeChatModelSelectionId(selectionId: string | null | undefined) {
    return String(selectionId || "").trim() || "system-default";
  }

  private chatModelSelectionIdFromConversationState(
    conversationState: SessionSummary["conversation_state"] | null | undefined,
    fallback = "system-default",
  ) {
    return this.normalizeChatModelSelectionId(conversationState?.chat_model_selection?.selection_id || fallback);
  }

  private chatModelSelectionStateForId(selectionId: string) {
    const normalized = this.normalizeChatModelSelectionId(selectionId);
    if (normalized === "system-default") {
      return {
        selection_id: "system-default",
        provider: "",
        model: "",
        source: "user",
      };
    }
    const [provider, ...modelParts] = normalized.split("::");
    return {
      selection_id: normalized,
      provider: provider.trim().toLowerCase(),
      model: modelParts.join("::").trim(),
      source: "user",
    };
  }

  private conversationStateWithChatModelSelection(
    conversationState: SessionSummary["conversation_state"] | null | undefined,
    selectionId: string,
  ): NonNullable<SessionSummary["conversation_state"]> {
    return {
      ...(conversationState ?? {}),
      chat_model_selection: this.chatModelSelectionStateForId(selectionId),
      authority: conversationState?.authority || "sessions.conversation_state",
    };
  }

  private sessionsWithChatModelSelection(sessions: SessionSummary[], sessionId: string, selectionId: string) {
    return sessions.map((session) => session.id === sessionId
      ? {
          ...session,
          conversation_state: this.conversationStateWithChatModelSelection(session.conversation_state, selectionId),
        }
      : session
    );
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

  private normalizeMainAgentSelection(
    selection: Partial<ActiveMainAgentSelection> | null | undefined,
  ): ActiveMainAgentSelection {
    const agentId = String(selection?.agent_id || "agent:0").trim() || "agent:0";
    const profileId = String(selection?.agent_profile_id || "main_interactive_agent").trim() || "main_interactive_agent";
    const defaultEnvironmentId = String(selection?.default_task_environment_id || GENERAL_TASK_ENVIRONMENT_ID).trim() || GENERAL_TASK_ENVIRONMENT_ID;
    return {
      agent_id: agentId,
      agent_profile_id: profileId,
      agent_name: String(selection?.agent_name || "通用主 Agent").trim() || "通用主 Agent",
      main_agent_kind: String(selection?.main_agent_kind || "general").trim() || "general",
      default_task_environment_id: defaultEnvironmentId,
      default_task_environment_label: String(selection?.default_task_environment_label || this.taskEnvironmentLabel(defaultEnvironmentId)).trim(),
      source: String(selection?.source || "agent-switcher").trim() || "agent-switcher",
      updated_at: Number(selection?.updated_at || Date.now() / 1000),
    };
  }

  private rememberedMainAgentSelection(): ActiveMainAgentSelection | null {
    const raw = storageGet(LAST_ACTIVE_MAIN_AGENT_KEY);
    if (!raw) {
      return null;
    }
    try {
      const parsed = JSON.parse(raw) as Partial<ActiveMainAgentSelection>;
      return this.normalizeMainAgentSelection(parsed);
    } catch {
      return null;
    }
  }

  private rememberMainAgentSelection(selection: ActiveMainAgentSelection) {
    storageSet(LAST_ACTIVE_MAIN_AGENT_KEY, JSON.stringify(selection));
  }

  private async setActiveMainAgent(selection: ActiveMainAgentSelection) {
    const activeAgent = this.normalizeMainAgentSelection({
      ...selection,
      source: selection.source || "agent-switcher",
      updated_at: Date.now() / 1000,
    });
    this.rememberMainAgentSelection(activeAgent);
    this.store.setState((prev) => ({
      ...prev,
      activeMainAgent: activeAgent,
    }));
    if (activeAgent.default_task_environment_id) {
      await this.setActiveTaskEnvironment(activeAgent.default_task_environment_id, {
        environmentLabel: activeAgent.default_task_environment_label,
        source: "agent-switcher",
      });
    }
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
      const currentState = this.store.getState();
      const selectedSession = currentState.sessions.find((session) => session.id === normalized.sessionId);
      const conversationActiveEnvironment = this.shouldUseConversationEnvironment(normalized)
        ? this.activeEnvironmentForSession(selectedSession) ?? currentState.conversationActiveEnvironment ?? this.defaultActiveTaskEnvironment()
        : currentState.conversationActiveEnvironment;
      const permissionMode = this.permissionModeForSession(normalized.sessionId, currentState);
      const selectedChatModelId = this.pendingChatModelSelections.get(normalized.sessionId)
        ?? this.chatModelSelectionIdFromConversationState(selectedSession?.conversation_state, "system-default");
      this.store.setState((prev) => this.withVisibleEditorContextForSession({
        ...prev,
        currentSessionId: normalized.sessionId,
        activeSessionScope: normalized.scope ?? null,
        activeSessionRef: normalized,
        conversationActiveEnvironment,
        permissionMode,
        selectedChatModelId,
        selectedChatMode: this.resolveSelectedChatMode(selectedChatModelId, prev.modelProviderConfig),
        messages: streamingCache.messages,
        activeProjectionsByKey: streamingCache.activeProjectionsByKey,
        harnessTurnSnapshot: streamingCache.harnessTurnSnapshot,
        activeTurnSnapshot: streamingCache.activeTurnSnapshot,
        taskGraphLiveMonitor: null,
        tokenStats: null
      }, normalized.sessionId));
      this.store.setState((prev) => this.projectSelectedSessionActivity(prev, normalized.sessionId));
      this.projectPermissionModeToRuntime(permissionMode);
      void this.refreshWorkspaceTree().catch(() => undefined);
      return true;
    }
    const currentState = this.store.getState();
    const selectedSession = currentState.sessions.find((session) => session.id === normalized.sessionId);
    const conversationActiveEnvironment = this.shouldUseConversationEnvironment(normalized)
      ? this.activeEnvironmentForSession(selectedSession) ?? currentState.conversationActiveEnvironment ?? this.defaultActiveTaskEnvironment()
      : currentState.conversationActiveEnvironment;
    const permissionMode = this.permissionModeForSession(normalized.sessionId, currentState);
    const selectedChatModelId = this.pendingChatModelSelections.get(normalized.sessionId)
      ?? this.chatModelSelectionIdFromConversationState(selectedSession?.conversation_state, "system-default");
    this.store.setState((prev) => this.withVisibleEditorContextForSession({
      ...prev,
      currentSessionId: normalized.sessionId,
      activeSessionScope: normalized.scope ?? null,
      activeSessionRef: normalized,
      conversationActiveEnvironment,
      permissionMode,
      selectedChatModelId,
      selectedChatMode: this.resolveSelectedChatMode(selectedChatModelId, prev.modelProviderConfig),
      messages: [],
      activeProjectionsByKey: {},
      harnessTurnSnapshot: null,
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
      let latestRunLookupFailed = false;
      const latestRun = await getLatestChatRunForSession(sessionId, this.sessionScopeForSession(sessionId)).catch(() => {
        latestRunLookupFailed = true;
        return null;
      });
      if (this.store.getState().activeStreamSessionIds.includes(sessionId)) {
        if (latestRunLookupFailed) {
          if (!this.streamingSessionCache.has(sessionId) || this.visibleSessionNeedsHistoryHydration(sessionId)) {
            await this.refreshSessionDetails(sessionId).catch(() => undefined);
          }
          return true;
        }
        if (!latestRun) {
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
      if (!latestRun) {
        clearChatStreamCursor(sessionId);
        return false;
      }
      const cursor = readChatStreamCursor(sessionId);
      const latestRunCursor = this.chatRunCursorFromActiveRun(latestRun);
      if (!latestRunCursor) {
        clearChatStreamCursor(sessionId);
        return false;
      }
      const cursorMatchesLatestRun = cursor?.streamRunId === latestRunCursor.streamRunId
        && cursor?.eventLogId === latestRunCursor.eventLogId;
      const effectiveCursor: ChatStreamCursor = cursorMatchesLatestRun && cursor ? cursor : latestRunCursor;
      if (cursor?.streamRunId && !cursorMatchesLatestRun) {
        clearChatStreamCursor(sessionId);
      }
      const streamRunId = latestRunCursor.streamRunId;
      const cursorRun = latestRun;
      if (
        !cursorRun
        || cursorRun.session_id !== sessionId
        || cursorRun.event_log_id !== effectiveCursor.eventLogId
        || cursorRun.is_reconnectable === false
      ) {
        clearChatStreamCursor(sessionId);
        return false;
      }
      if (this.chatRunCursorAlreadyReachedTerminal(cursorRun, effectiveCursor)) {
        clearChatStreamCursor(sessionId);
        await this.refreshSessionDetails(sessionId).catch(() => undefined);
        return false;
      }
      this.updateActiveChatStreamBinding(sessionId, this.chatRunBinding(cursorRun));
      if (this.visibleSessionNeedsHistoryHydration(sessionId)) {
        await this.refreshSessionDetails(sessionId).catch(() => undefined);
      }
      this.startRecoveredChatRunStream(sessionId, streamRunId, effectiveCursor, cursorRun);
      return true;
    } finally {
      this.recoveringStreamSessionIds.delete(sessionId);
    }
  }

  private chatRunCursorFromActiveRun(run: ChatRun | null | undefined): ChatStreamCursor | null {
    const streamRunId = runtimeText(run?.stream_run_id);
    const eventLogId = runtimeText(run?.event_log_id);
    if (!streamRunId || !eventLogId || run?.is_reconnectable === false) {
      return null;
    }
    return {
      streamRunId,
      eventLogId,
      lastEventOffset: -1,
      lastEventId: "",
    };
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
    const streamRunId = runtimeText(run.stream_run_id);
    const taskRunId = runtimeText(diagnostics.runtime_task_run_id)
      || runtimeText(diagnostics.task_run_id)
      || runtimeText(diagnostics.public_anchor_task_run_id);
    const turnId = runtimeText(diagnostics.active_turn_id)
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

  private bindCreatedChatRunForStream(sessionId: string, streamEpoch: number, run: ChatRun | null | undefined) {
    const binding = this.chatRunBinding(run);
    if (!binding) {
      return;
    }
    const streamStillCurrent = this.isCurrentChatStreamEpoch(sessionId, streamEpoch);
    if (streamStillCurrent) {
      this.updateActiveChatStreamBinding(sessionId, binding);
    }
    const pending = this.pendingChatStreamInterruptions.get(sessionId);
    if (!pending || pending.streamEpoch !== streamEpoch) {
      return;
    }
    this.pendingChatStreamInterruptions.delete(sessionId);
    void this.interruptChatRunForResume(binding.streamRunId, {
      taskRunId: pending.taskRunId || binding.taskRunId,
      expectedTurnId: pending.expectedTurnId || binding.turnId,
    });
  }

  private currentChatStreamEpoch(sessionId: string) {
    return this.chatStreamEpochBySession.get(sessionId) ?? 0;
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
    const diagnostics = run?.diagnostics ?? {};
    const turnId = runtimeText(diagnostics.active_turn_id)
      || runtimeText(diagnostics.public_anchor_turn_id);
    const turnRunId = runtimeText(diagnostics.runtime_turn_run_id)
      || runtimeText(diagnostics.turn_run_id);
    const taskRunId = runtimeText(diagnostics.runtime_task_run_id)
      || runtimeText(diagnostics.task_run_id)
      || runtimeText(diagnostics.public_anchor_task_run_id);
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
    const diagnostics = run?.diagnostics ?? {};
    const turnId = runtimeText(diagnostics.active_turn_id)
      || runtimeText(diagnostics.public_anchor_turn_id);
    const turnRunId = runtimeText(diagnostics.runtime_turn_run_id)
      || runtimeText(diagnostics.turn_run_id);
    const taskRunId = runtimeText(diagnostics.runtime_task_run_id)
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
    const shouldDeriveTitleAfterCompletion = this.shouldDeriveSessionTitleFromFirstUser(sessionId);

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
      harnessTurnSnapshot: null,
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
      harnessTurnSnapshot: streamState.harnessTurnSnapshot,
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
              this.noteFileChangeSignalFromPayload(data);
              this.updateActiveChatStreamBinding(sessionId, this.eventChatStreamBinding(data, streamRunId));
              const isCurrentStreamSession = this.store.getState().currentSessionId === sessionId;
              const deferProjectionViewBuild = this.streamEventCanUseDeferredVisibleFlush(event, data);
              const baseState = isCurrentStreamSession && !this.pendingVisibleStreamFlushes.has(sessionId)
                ? this.store.getState()
                : streamState;
              const transition = reduceStreamEvent(baseState, transitionSession, event, data, { deferProjectionViewBuild });
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
                harnessTurnSnapshot: streamState.harnessTurnSnapshot,
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
          harnessTurnSnapshot: streamState.harnessTurnSnapshot,
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
          this.requestFirstUserSessionTitleInBackground(sessionId);
        }
        if (
          !streamSessionWasRemoved
          && !streamSessionWasStopped
          && !streamEndedWithError
          && this.store.getState().currentSessionId === sessionId
        ) {
          await this.hydrateLatestHarnessTurnSnapshot(sessionId);
          await this.refreshRunMonitor();
        }
        this.refreshMainSessionPoolInBackground();
        this.scheduleSessionRefreshes();
      }
    })();
  }

  private async sendMessage(
    value: string,
    options: {
      queuedUserMessageId?: string;
      files?: File[];
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
    this.invalidateSessionHistoryCache(sessionId);
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
    if (
      activeStreamState.activeStreamSessionIds.includes(sessionId)
      || this.shouldQueueActiveTurnInput(activeStreamState, sessionId)
    ) {
      await this.enqueueUserInputForSession(sessionId, trimmed, options.queuedUserMessageId);
      return;
    }
    const shouldDeriveTitleAfterCompletion = this.shouldDeriveSessionTitleFromFirstUser(sessionId);
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
    this.store.setState((prev) => ({
      ...prev,
      harnessTurnSnapshot: null,
      taskGraphLiveMonitor: null,
      agentSystemInspectorTarget: prev.agentSystemInspectorTarget?.source === "live-session"
        ? null
        : prev.agentSystemInspectorTarget,
    }));
    let transition = startStreamingTurn(this.store.getState(), trimmed, { existingUserMessageId: options.queuedUserMessageId, attachments });
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
      harnessTurnSnapshot: streamState.harnessTurnSnapshot,
      activeTurnSnapshot: streamState.activeTurnSnapshot,
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
      const requestState = this.store.getState();
      const permissionMode = this.permissionModeForSession(sessionId, requestState);
      const streamResult = await streamChat(
        {
          message: trimmed,
          client_message_id: transition.session.userId,
          session_id: sessionId,
          session_scope: this.sessionScopeForSession(sessionId),
          environment_binding: this.chatEnvironmentBindingPayload(requestState),
          runtime_profile: this.chatRuntimeProfilePayload(requestState),
          runtime_contract: this.chatRuntimeContractPayload(requestState),
          model_selection: this.chatModelSelectionPayload(requestState),
          permission_mode: permissionMode,
          expected_active_turn_id: "",
          active_turn_input_policy: "auto",
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
          onRunCreated: (run) => {
            this.bindCreatedChatRunForStream(sessionId, streamEpoch, run);
          },
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
            this.noteFileChangeSignalFromPayload(data);
            this.updateActiveChatStreamBinding(sessionId, this.eventChatStreamBinding(data));
            const isCurrentStreamSession = this.store.getState().currentSessionId === sessionId;
            const deferProjectionViewBuild = this.streamEventCanUseDeferredVisibleFlush(event, data);
            const baseState = isCurrentStreamSession && !this.pendingVisibleStreamFlushes.has(sessionId)
              ? this.store.getState()
              : streamState;
            transition = reduceStreamEvent(baseState, transition.session, event, data, { deferProjectionViewBuild });
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
              harnessTurnSnapshot: streamState.harnessTurnSnapshot,
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
        harnessTurnSnapshot: streamState.harnessTurnSnapshot,
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
        this.requestFirstUserSessionTitleInBackground(sessionId);
      }
      if (
        !streamSessionWasRemoved
        && !streamSessionWasStopped
        && !streamEndedWithError
        && !isImageGenerationTurn
        && this.store.getState().currentSessionId === sessionId
      ) {
        await this.hydrateLatestHarnessTurnSnapshot(sessionId);
        await this.refreshRunMonitor();
      }
      this.refreshMainSessionPoolInBackground();
      this.scheduleSessionRefreshes();
    }
  }

  private stopCurrentStream() {
    const sessionId = this.store.getState().currentSessionId;
    const normalizedSessionId = String(sessionId || "").trim();
    const streamBinding = normalizedSessionId ? this.activeChatStreamBindings.get(normalizedSessionId) : undefined;
    const taskRunId = String(streamBinding?.taskRunId || this.activeControllableTaskRunId()).trim();
    const expectedTurnId = taskRunId
      ? this.activeExpectedTurnIdForTaskRun(taskRunId)
      : String(streamBinding?.turnId || this.store.getState().activeTurnSnapshot?.turn_id || "").trim();
    const streamRunId = String(streamBinding?.streamRunId || "").trim();
    const streamEpoch = normalizedSessionId ? this.currentChatStreamEpoch(normalizedSessionId) : 0;
    const released = this.releaseStoppedChatStreamBoundary(sessionId, "user_interrupted_for_resume", {
      taskRunId,
      turnId: expectedTurnId,
      preserveActiveWorkContext: true,
    });
    if (!released) {
      return;
    }
    if (streamRunId) {
      void this.interruptChatRunForResume(streamRunId, {
        taskRunId,
        expectedTurnId,
      });
      return;
    }
    if (normalizedSessionId && streamEpoch > 0) {
      this.pendingChatStreamInterruptions.set(normalizedSessionId, {
        streamEpoch,
        taskRunId,
        expectedTurnId,
      });
    }
  }

  private releaseStoppedChatStreamBoundary(
    sessionId: string | null | undefined,
    reason = "user_stopped",
    options: { abortStream?: boolean; taskRunId?: string; turnId?: string; preserveActiveWorkContext?: boolean } = {},
  ) {
    return this.releaseControlledChatStreamBoundary(sessionId, reason, {
      ...options,
      connectionState: "stopped",
    });
  }

  private releasePausedChatStreamBoundary(
    sessionId: string | null | undefined,
    options: { abortStream?: boolean; taskRunId?: string; turnId?: string } = {},
  ) {
    return this.releaseControlledChatStreamBoundary(sessionId, "user_paused", {
      ...options,
      connectionState: "paused",
    });
  }

  private releaseControlledChatStreamBoundary(
    sessionId: string | null | undefined,
    reason: string,
    options: {
      abortStream?: boolean;
      taskRunId?: string;
      turnId?: string;
      preserveActiveWorkContext?: boolean;
      connectionState: "stopped" | "paused";
    },
  ) {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId || !this.store.getState().activeStreamSessionIds.includes(normalizedSessionId)) {
      return false;
    }
    this.nextChatStreamEpoch(normalizedSessionId);
    if (options.connectionState === "stopped") {
      this.stoppedStreamingSessionIds.add(normalizedSessionId);
    } else {
      this.removedStreamingSessionIds.add(normalizedSessionId);
    }
    this.clearPendingVisibleStreamFlush(normalizedSessionId);
    if (options.abortStream !== false) {
      this.streamAbortControllers.get(normalizedSessionId)?.abort();
      this.streamAbortControllers.delete(normalizedSessionId);
    }
    this.streamingSessionCache.delete(normalizedSessionId);
    const streamBinding = this.activeChatStreamBindings.get(normalizedSessionId);
    const stoppedTaskRunId = String(options.taskRunId ?? "").trim() || String(streamBinding?.taskRunId ?? "").trim();
    const stoppedTurnId = String(options.turnId ?? "").trim() || String(streamBinding?.turnId ?? "").trim();
    this.activeChatStreamBindings.delete(normalizedSessionId);
    this.store.setState((prev) => {
      const detached = this.removeActiveStreamSession(prev, normalizedSessionId);
      const nextState = options.connectionState === "stopped" && options.preserveActiveWorkContext !== true
        ? this.releaseActiveTurnGateForStoppedStream(detached, stoppedTaskRunId, stoppedTurnId)
        : detached;
      return {
        ...nextState,
        chatStreamConnectionStatus: {
          state: options.connectionState,
          reason,
          updatedAt: Date.now(),
        },
      };
    });
    return true;
  }

  private async interruptChatRunForResume(
    streamRunId: string,
    input: { taskRunId?: string; expectedTurnId?: string } = {},
  ) {
    const normalizedStreamRunId = String(streamRunId || "").trim();
    if (!normalizedStreamRunId) {
      return;
    }
    const taskRunId = String(input.taskRunId || "").trim();
    const expectedTurnId = String(input.expectedTurnId || "").trim();
    this.setChatInterruptionActivity({
      level: "running",
      title: "正在中断",
      detail: "输出流已断开，正在把任务进度和运行事实交给后端保存。",
      event: "chat_stream_interrupt_requested",
      taskRunId,
      streamRunId: normalizedStreamRunId,
    });
    try {
      await interruptChatRun(normalizedStreamRunId, {
        mode: "interrupt_for_resume",
        reason: "user_stop_from_chat_stream",
        expected_active_turn_id: expectedTurnId,
        expected_task_run_id: taskRunId,
        cascade_subagents: "interrupt_for_resume",
      });
      await this.refreshActiveSessionMonitor();
      const currentSessionId = this.store.getState().currentSessionId;
      if (currentSessionId) {
        await this.hydrateLatestHarnessTurnSnapshot(currentSessionId);
      }
      this.setChatInterruptionActivity({
        level: "idle",
        title: "已中断",
        detail: "上下文已保持连续，任务断开事实会交给下一轮 agent 判断。",
        event: "chat_stream_interrupt_recorded",
        taskRunId,
        streamRunId: normalizedStreamRunId,
      });
    } catch (error) {
      this.setChatInterruptionActivity({
        level: "error",
        title: "中断记录失败",
        detail: this.errorMessage(error, "输出流已断开，但后端中断事实未确认，请在运行监控里检查当前任务状态。"),
        event: "chat_stream_interrupt_failed",
        taskRunId,
        streamRunId: normalizedStreamRunId,
      });
    }
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

  private setChatInterruptionActivity(input: {
    level: StoreState["sessionActivity"]["level"];
    title: string;
    detail: string;
    event: string;
    taskRunId?: string;
    streamRunId?: string;
  }) {
    const sessionId = this.store.getState().currentSessionId;
    if (!sessionId) {
      return;
    }
    const debug: Record<string, string> = { event: input.event };
    if (input.taskRunId) debug.taskRunId = input.taskRunId;
    if (input.streamRunId) debug.streamRunId = input.streamRunId;
    const activity = {
      level: input.level,
      title: input.title,
      detail: input.detail,
      event: input.event,
      receipt: {
        level: input.level,
        title: input.title,
        body: input.detail,
        debug,
      },
      updatedAt: Date.now(),
    };
    this.store.setState((prev) => ({
      ...prev,
      sessionActivity: activity,
      sessionActivitiesById: {
        ...prev.sessionActivitiesById,
        [sessionId]: activity,
      },
    }));
  }

  private async pauseActiveTaskRun() {
    const taskRunId = this.activeControllableTaskRunId();
    if (!taskRunId) {
      return;
    }
    const expectedTurnId = this.activeExpectedTurnIdForTaskRun(taskRunId);
    this.releasePausedChatStreamBoundary(this.store.getState().currentSessionId, {
      taskRunId,
      turnId: expectedTurnId,
    });
    this.setActiveTaskControlActivity({
      taskRunId,
      level: "running",
      title: "正在暂停",
      detail: "暂停请求已发送，当前输出流已断开。",
      event: "active_task_pause_requested",
    });
    try {
      await pauseHarnessTaskRun(taskRunId, "user_pause_from_chat", expectedTurnId);
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
    const approvalKind = this.activeTaskRunWaitingApprovalKind(taskRunId);
    const approvingLaunchGate = approvalKind === "launch_gate";
    const approvingToolCall = approvalKind === "tool_call";
    const approving = approvingLaunchGate || approvingToolCall;
    this.setActiveTaskControlActivity({
      taskRunId,
      level: "running",
      title: approving ? "正在确认" : "正在继续",
      detail: approvingLaunchGate
        ? "启动确认已发送，等待任务进入执行。"
        : approvingToolCall
          ? "确认请求已发送，等待工具调用继续。"
          : "继续请求已发送，等待当前任务恢复执行。",
      event: approving ? "active_task_approval_requested" : "active_task_resume_requested",
    });
    try {
      if (approvingLaunchGate) {
        await approveHarnessTaskRunLaunch(taskRunId, "user_approve_launch_from_chat", 12, expectedTurnId);
      } else if (approvingToolCall) {
        await approveHarnessTaskRunToolCall(taskRunId, "user_approve_tool_from_chat", 12, expectedTurnId);
      } else {
        await resumeHarnessTaskRun(taskRunId, 12, expectedTurnId);
      }
      await this.refreshActiveSessionMonitor();
    } catch (error) {
      this.setActiveTaskControlError(approving ? "approve" : "resume", taskRunId, error);
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
      await stopHarnessTaskRun(taskRunId, "user_stop_from_chat", expectedTurnId);
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

  private activeTaskRunWaitingApprovalKind(taskRunId: string) {
    const monitor = this.store.getState().taskGraphLiveMonitor;
    if (!monitor) {
      return "";
    }
    const taskRun = this.harnessMonitorTaskRun(monitor);
    const monitorRecord = monitor as unknown as Record<string, unknown>;
    const currentId = String(taskRun.task_run_id ?? monitor.task_run_id ?? "").trim();
    if (currentId !== taskRunId) {
      return "";
    }
    const status = String(monitor.status ?? taskRun.status ?? "").trim();
    if (status !== "waiting_approval") {
      return "";
    }
    const diagnostics = recordValue(taskRun.diagnostics);
    const pendingLaunchGate = {
      ...recordValue(diagnostics.pending_launch_gate),
      ...recordValue(monitorRecord.pending_launch_gate),
    };
    const waitReason = String(monitorRecord.wait_reason ?? diagnostics.wait_reason ?? "").trim();
    if (String(pendingLaunchGate.status ?? "").trim() === "pending" || waitReason === "task_launch_supervision") {
      return "launch_gate";
    }
    const pendingApproval = {
      ...recordValue(diagnostics.pending_approval),
      ...recordValue(monitorRecord.pending_approval),
    };
    if (String(pendingApproval.status ?? "").trim() === "pending" || waitReason === "tool_approval_required") {
      return "tool_call";
    }
    return "tool_call";
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
    return {
      taskRunId,
      status: String(monitor.status ?? taskRun.status ?? "").trim(),
      controlState: String(monitor.control_state ?? "").trim(),
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

  private activeSnapshotIsOpenForInput(snapshot: ActiveTurnSnapshot | null) {
    const activeTurnId = String(snapshot?.turn_id ?? "").trim();
    if (!activeTurnId) {
      return false;
    }
    const snapshotState = String(snapshot?.state ?? "").trim();
    return snapshotState !== "terminal";
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
    if (activeTurnId && !this.activeSnapshotIsOpenForInput(snapshot)) {
      return false;
    }
    if (!monitorInfo) {
      return this.activeSnapshotIsOpenForInput(snapshot);
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
    await this.hydrateLatestHarnessTurnSnapshot(sessionId);
    await this.refreshRunMonitor();
  }

  private async resendEditedMessage(messageId: string, value: string) {
    const nextValue = value.trim();
    const state = this.store.getState();
    const sessionId = state.currentSessionId;
    if (!sessionId || !nextValue || state.activeStreamSessionIds.includes(sessionId)) {
      return;
    }
    this.invalidateSessionHistoryCache(sessionId);
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
    const truncateIndex = this.truncateMessageIndexForResend(targetMessage);
    const previousMessages = state.messages;
    const previousHarnessTurnSnapshot = state.harnessTurnSnapshot;
    const previousTaskGraphLiveMonitor = state.taskGraphLiveMonitor;
    const previousTokenStats = state.tokenStats;
    this.store.setState((prev) => ({
      ...prev,
      messages: prev.currentSessionId === sessionId && visibleMessageIndex > -1
        ? prev.messages.slice(0, visibleMessageIndex)
        : prev.messages,
      harnessTurnSnapshot: prev.currentSessionId === sessionId ? null : prev.harnessTurnSnapshot,
      taskGraphLiveMonitor: prev.currentSessionId === sessionId ? null : prev.taskGraphLiveMonitor,
      tokenStats: prev.currentSessionId === sessionId ? null : prev.tokenStats,
    }));
    let truncateCommitted = false;
    try {
      await truncateSessionMessages(sessionId, truncateIndex, this.sessionScopeForSession(sessionId));
      truncateCommitted = true;
      if (this.store.getState().currentSessionId !== sessionId) {
        void this.refreshSessionDetails(sessionId).catch(() => undefined);
        return;
      }
      await this.sendMessage(nextValue);
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        messages: prev.currentSessionId === sessionId && !truncateCommitted ? previousMessages : prev.messages,
        harnessTurnSnapshot: prev.currentSessionId === sessionId && !truncateCommitted
          ? previousHarnessTurnSnapshot
          : prev.harnessTurnSnapshot,
        taskGraphLiveMonitor: prev.currentSessionId === sessionId && !truncateCommitted
          ? previousTaskGraphLiveMonitor
          : prev.taskGraphLiveMonitor,
        tokenStats: prev.currentSessionId === sessionId && !truncateCommitted ? previousTokenStats : prev.tokenStats,
      }));
      void this.refreshSessionDetails(sessionId).catch(() => undefined);
      throw error;
    }
  }

  private nextMessageSourceIndex(messages: StoreState["messages"]) {
    const maxSourceIndex = messages.reduce((max, message) => {
      const sourceIndex = Number(message.sourceIndex ?? -1);
      if (!Number.isFinite(sourceIndex)) {
        return max;
      }
      return Math.max(max, Math.floor(sourceIndex));
    }, -1);
    return maxSourceIndex + 1;
  }

  private truncateMessageIndexForResend(message: StoreState["messages"][number]) {
    const sourceIndex = Number(message.sourceIndex ?? -1);
    if (!Number.isFinite(sourceIndex) || sourceIndex < 0) {
      return 0;
    }
    return Math.floor(sourceIndex);
  }

  private async setPermissionMode(mode: PermissionMode) {
    const requestedMode = this.normalizePermissionMode(mode);
    const state = this.store.getState();
    const sessionId = state.currentSessionId;
    const sessionScope = sessionId ? this.sessionScopeForSession(sessionId) : undefined;
    if (sessionId) {
      this.invalidateSessionHistoryCache(sessionId);
    }
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
    const normalized = this.normalizeChatModelSelectionId(selectionId);
    const sessionId = this.store.getState().currentSessionId || "";
    if (sessionId) {
      this.pendingChatModelSelections.set(sessionId, normalized);
      this.invalidateSessionHistoryCache(sessionId);
    }
    this.store.setState((prev) => ({
      ...prev,
      selectedChatModelId: normalized,
      selectedChatMode: this.resolveSelectedChatMode(normalized, prev.modelProviderConfig),
      sessions: sessionId
        ? this.sessionsWithChatModelSelection(prev.sessions, sessionId, normalized)
        : prev.sessions,
      projectSessions: sessionId
        ? this.sessionsWithChatModelSelection(prev.projectSessions, sessionId, normalized)
        : prev.projectSessions,
    }));
    if (!sessionId) {
      return;
    }
    this.persistSelectedChatModelInBackground(sessionId, normalized);
  }

  private persistSelectedChatModelInBackground(sessionId: string, selectionId: string, attempt = 1) {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    const previousTimer = this.chatModelSelectionPersistTimers.get(normalizedSessionId);
    if (previousTimer) {
      clearTimeout(previousTimer);
      this.chatModelSelectionPersistTimers.delete(normalizedSessionId);
    }
    void this.persistSelectedChatModel(normalizedSessionId, selectionId).catch((error) => {
      const pendingSelection = this.pendingChatModelSelections.get(normalizedSessionId);
      if (pendingSelection !== this.normalizeChatModelSelectionId(selectionId)) {
        return;
      }
      console.debug("[workspace-runtime] chat model selection persist retry scheduled", {
        event: "chat_model_selection_persist_retry_scheduled",
        sessionId: normalizedSessionId,
        selectionId,
        attempt,
        error: this.errorMessage(error, "模型选择写入超时。"),
      });
      if (attempt >= 3 || typeof window === "undefined") {
        return;
      }
      const timer = window.setTimeout(() => {
        this.chatModelSelectionPersistTimers.delete(normalizedSessionId);
        this.persistSelectedChatModelInBackground(normalizedSessionId, selectionId, attempt + 1);
      }, attempt * 2500);
      this.chatModelSelectionPersistTimers.set(normalizedSessionId, timer);
    });
  }

  private async persistSelectedChatModel(sessionId: string, selectionId: string) {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    const normalizedSelectionId = this.normalizeChatModelSelectionId(selectionId);
    this.pendingChatModelSelections.set(normalizedSessionId, normalizedSelectionId);
    this.invalidateSessionHistoryCache(normalizedSessionId);
    try {
      const conversationState = await setSessionChatModelSelection(
        normalizedSessionId,
        this.chatModelSelectionStateForId(normalizedSelectionId),
        this.sessionScopeForSession(normalizedSessionId),
      );
      if (this.pendingChatModelSelections.get(normalizedSessionId) === normalizedSelectionId) {
        this.pendingChatModelSelections.delete(normalizedSessionId);
      }
      this.store.setState((prev) => ({
        ...prev,
        sessions: prev.sessions.map((session) => session.id === normalizedSessionId
          ? { ...session, conversation_state: conversationState }
          : session
        ),
        projectSessions: prev.projectSessions.map((session) => session.id === normalizedSessionId
          ? { ...session, conversation_state: conversationState }
          : session
        ),
      }));
    } catch (error) {
      throw error;
    }
  }

  private setSelectedChatMode(mode: ChatMode) {
    this.store.setState((prev) => ({ ...prev, selectedChatMode: mode }));
  }

  private setChatThinkingMode(mode: ChatThinkingMode) {
    this.store.setState((prev) => ({ ...prev, chatThinkingMode: normalizeChatThinkingMode(mode) }));
  }

  private setThinkingProjectionEnabled(enabled: boolean) {
    rememberThinkingProjectionEnabled(enabled);
    this.store.setState((prev) => ({
      ...prev,
      thinkingProjectionEnabled: Boolean(enabled),
    }));
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

  private chatRuntimeProfilePayload(state: StoreState): Record<string, unknown> {
    const activeAgent = this.normalizeMainAgentSelection(state.activeMainAgent);
    return {
      agent_id: activeAgent.agent_id,
      agent_profile_id: activeAgent.agent_profile_id,
      default_task_environment_id: activeAgent.default_task_environment_id,
      source: activeAgent.source || "agent-switcher",
      selected_main_agent: {
        agent_id: activeAgent.agent_id,
        agent_profile_id: activeAgent.agent_profile_id,
        agent_name: activeAgent.agent_name,
        main_agent_kind: activeAgent.main_agent_kind,
        default_task_environment_id: activeAgent.default_task_environment_id,
      },
    };
  }

  private chatRuntimeContractPayload(state: StoreState): Record<string, unknown> {
    const publicVisible = normalizeChatThinkingMode(state.chatThinkingMode) === "thinking"
      && Boolean(state.thinkingProjectionEnabled);
    const runtimeProfile = this.chatRuntimeProfilePayload(state);
    return {
      runtime_profile: runtimeProfile,
      reasoning_projection_enabled: publicVisible,
      reasoning_projection: {
        enabled: true,
        public_visible: publicVisible,
        visibility: publicVisible ? "public_collapsible_trace" : "hidden_trace_only",
        source: "frontend.thinking_projection_toggle",
      },
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
      upstream_reconnect_enabled: true,
      partial_stream_recovery: "continue_from_visible_prefix",
      chunk_strategy: "adaptive_buffer",
      first_flush_delay_ms: 70,
      target_buffer_delay_ms: 150,
      adaptive_min_buffer_delay_ms: 80,
      adaptive_max_buffer_delay_ms: 240,
      release_tick_ms: 16,
      max_buffer_delay_ms: 320,
      max_pending_utf8_bytes: 1536,
      max_release_utf8_bytes: 192,
      max_pending_line_count: 1,
      min_event_interval_ms: 16,
      event_budget_per_second: 45,
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
            label: this.fileLabelForPath(activePath),
            language_id: this.languageIdForPath(activePath),
            dirty: Boolean(context?.inspectorDirty),
            content_preview: contentPreview,
            selection: undefined,
        }
        : undefined,
      open_tabs: openFilePaths.map((path) => ({
        path,
        label: this.fileLabelForPath(path),
        language_id: this.languageIdForPath(path),
        dirty: path === activePath ? Boolean(context?.inspectorDirty) : false,
        active: path === activePath,
        visible: path === activePath,
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

  private fileLabelForPath(path: string) {
    const normalized = path.replace(/\\/g, "/");
    return normalized.split("/").filter(Boolean).pop() || path;
  }

  private sessionProjectRoot(state: StoreState, sessionId: string) {
    return sessionProjectRoot(state.sessions.find((session) => session.id === sessionId));
  }

  private managedProjectFileTarget(path: string, sessionId: string, state: StoreState): ManagedFileTarget {
    const logicalPath = normalizeInspectorLogicalPath(path);
    const workspaceRoot = String(this.sessionProjectRoot(state, sessionId) || state.activeProjectRoot || "").trim();
    if (!workspaceRoot) {
      throw new Error("当前会话未绑定项目，不能通过文件管理系统打开项目文件。");
    }
    return {
      repository_id: MANAGED_PROJECT_REPOSITORY_ID,
      repository_kind: "project_workspace",
      scope_kind: "project_scoped",
      scope_id: sessionId || state.activeProjectKey || workspaceRoot,
      logical_path: logicalPath,
      workspace_root: workspaceRoot,
      profile_id: MANAGED_PROJECT_PROFILE_ID,
    };
  }

  private async selectWorkspaceFile(): Promise<string | null> {
    try {
      let state = this.store.getState();
      let sessionId = state.currentSessionId || "";
      if (!sessionId && state.activeProjectKey) {
        sessionId = await this.ensureSession();
        state = this.store.getState();
      }
      const file = await selectManagedFileForOpen(sessionId);
      const displayPath = String(file.display_path || file.path || "").trim();
      if (!displayPath) {
        return null;
      }
      this.selectedWorkspaceFileTargets.set(displayPath, file.target);
      this.store.setState((prev) => this.patchCurrentSessionEditorContext({
        ...prev,
        inspectorPath: displayPath,
        inspectorContent: file.content,
        inspectorContentSha256: file.content_sha256,
        inspectorDirty: false,
        inspectorTarget: file.target,
        inspectorLastChangeRecordId: "",
        workspaceTreeError: "",
      }, {
        activeFilePath: displayPath,
        inspectorPath: displayPath,
        inspectorContent: file.content,
        inspectorContentSha256: file.content_sha256,
        inspectorDirty: false,
        inspectorTarget: file.target,
        inspectorLastChangeRecordId: "",
      }));
      return displayPath;
    } catch (error) {
      if (isFileSelectionCancelled(error)) {
        return null;
      }
      const message = this.errorMessage(error, "无法打开文件。");
      this.store.setState((prev) => ({ ...prev, workspaceTreeError: message }));
      throw new Error(message);
    }
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
      harnessTurnSnapshot: null,
      taskGraphLiveMonitor: null,
      activeTurnSnapshot: null,
      tokenStats: null,
      inspectorPath: DEFAULT_INSPECTOR_PATH,
      inspectorContent: "",
      inspectorContentSha256: "",
      inspectorDirty: false,
      inspectorTarget: null,
      inspectorLastChangeRecordId: "",
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
      const selectedTarget = this.selectedWorkspaceFileTargets.get(String(path || "").trim());
      if (selectedTarget) {
        const file = await readManagedFile(selectedTarget, sessionId);
        this.store.setState((prev) => this.patchCurrentSessionEditorContext({
          ...prev,
          inspectorPath: path,
          inspectorContent: file.content,
          inspectorContentSha256: file.content_sha256,
          inspectorDirty: false,
          inspectorTarget: file.target,
          inspectorLastChangeRecordId: "",
          workspaceTreeError: "",
        }, {
          activeFilePath: path,
          inspectorPath: path,
          inspectorContent: file.content,
          inspectorContentSha256: file.content_sha256,
          inspectorDirty: false,
          inspectorTarget: file.target,
          inspectorLastChangeRecordId: "",
        }));
        return;
      }
      const scope = sessionId ? this.sessionScopeForSession(sessionId) : undefined;
      const logicalPath = normalizeInspectorLogicalPath(path);
      const legacyInternalFile = isLegacyInternalInspectorPath(logicalPath);
      if (sessionId && !this.sessionProjectRoot(state, sessionId) && !legacyInternalFile) {
        throw new Error("当前会话未绑定项目，不能打开项目文件。");
      }
      if (sessionId && !legacyInternalFile) {
        const target = this.managedProjectFileTarget(logicalPath, sessionId, state);
        const file = await readManagedFile(target, sessionId);
        this.store.setState((prev) => this.patchCurrentSessionEditorContext({
          ...prev,
          inspectorPath: file.path,
          inspectorContent: file.content,
          inspectorContentSha256: file.content_sha256,
          inspectorDirty: false,
          inspectorTarget: file.target,
          inspectorLastChangeRecordId: "",
          workspaceTreeError: ""
        }, {
          activeFilePath: file.path,
          inspectorPath: file.path,
          inspectorContent: file.content,
          inspectorContentSha256: file.content_sha256,
          inspectorDirty: false,
          inspectorTarget: file.target,
          inspectorLastChangeRecordId: "",
        }));
        return;
      }
      const file = sessionId
        ? await loadFileForSession(logicalPath, sessionId, scope)
        : await loadFile(logicalPath);
      this.store.setState((prev) => this.patchCurrentSessionEditorContext({
        ...prev,
        inspectorPath: file.path,
        inspectorContent: file.content,
        inspectorContentSha256: "",
        inspectorDirty: false,
        inspectorTarget: null,
        inspectorLastChangeRecordId: "",
        workspaceTreeError: ""
      }, {
        activeFilePath: file.path,
        inspectorPath: file.path,
        inspectorContent: file.content,
        inspectorContentSha256: "",
        inspectorDirty: false,
        inspectorTarget: null,
        inspectorLastChangeRecordId: "",
      }));
    } catch (error) {
      const message = this.errorMessage(error, `无法打开文件：${path}`);
      this.store.setState((prev) => this.patchCurrentSessionEditorContext({
        ...prev,
        inspectorPath: path,
        inspectorContent: message,
        inspectorContentSha256: "",
        inspectorDirty: false,
        inspectorTarget: null,
        inspectorLastChangeRecordId: "",
        workspaceTreeError: message
      }, {
        activeFilePath: path,
        inspectorPath: path,
        inspectorContent: "",
        inspectorContentSha256: "",
        inspectorDirty: false,
        inspectorTarget: null,
        inspectorLastChangeRecordId: "",
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
        : await getSessionWorkspaceTree({
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
    const logicalPath = normalizeInspectorLogicalPath(state.inspectorPath);
    const legacyInternalFile = isLegacyInternalInspectorPath(logicalPath);
    if (sessionId && !this.sessionProjectRoot(state, sessionId) && !legacyInternalFile && !state.inspectorTarget) {
      this.store.setState((prev) => ({
        ...prev,
        workspaceTreeError: "当前会话未绑定项目，不能保存项目文件。",
      }));
      return;
    }
    try {
      if (state.inspectorTarget) {
        const payload = await writeManagedFile({
          target: state.inspectorTarget,
          content: state.inspectorContent,
          expectedSha256: state.inspectorContentSha256,
          source: "agent_ui",
          reason: "user_save_from_agent_workbench",
          sessionId,
        });
        const recordId = fileChangeRecordId(payload.file_change_record);
        this.noteFileChangeSignalFromRecord(payload.file_change_record);
        this.store.setState((prev) => this.patchCurrentSessionEditorContext({
          ...prev,
          inspectorPath: payload.path,
          inspectorContentSha256: payload.content_sha256,
          inspectorDirty: false,
          inspectorTarget: payload.target,
          inspectorLastChangeRecordId: recordId,
          workspaceTreeError: "",
        }, {
          inspectorPath: payload.path,
          inspectorContent: prev.inspectorContent,
          inspectorContentSha256: payload.content_sha256,
          inspectorDirty: false,
          inspectorTarget: payload.target,
          inspectorLastChangeRecordId: recordId,
        }));
        await this.refreshWorkspaceTree().catch(() => undefined);
        return;
      }
      if (!legacyInternalFile) {
        throw new Error("当前文件未通过文件管理系统打开，不能保存项目文件。");
      }
      if (sessionId) {
        await saveFileForSession(logicalPath, state.inspectorContent, sessionId, scope);
      } else {
        await saveFile(logicalPath, state.inspectorContent);
      }
      this.store.setState((prev) => this.patchCurrentSessionEditorContext({
        ...prev,
        inspectorDirty: false,
        inspectorContentSha256: "",
        inspectorTarget: null,
        inspectorLastChangeRecordId: "",
        workspaceTreeError: "",
      }, {
        inspectorPath: prev.inspectorPath,
        inspectorContent: prev.inspectorContent,
        inspectorContentSha256: "",
        inspectorDirty: false,
        inspectorTarget: null,
        inspectorLastChangeRecordId: "",
      }));
      await this.refreshSkills();
    } catch (error) {
      const message = this.errorMessage(error, "文件保存失败。");
      this.store.setState((prev) => ({ ...prev, workspaceTreeError: message }));
      throw error;
    }
  }

  private noteFileChangeSignalFromPayload(payload: unknown) {
    for (const record of fileChangeRecordsFromPayload(payload)) {
      this.noteFileChangeSignalFromRecord(record);
    }
  }

  private noteFileChangeSignalFromRecord(record: unknown) {
    const normalized = normalizeFileChangeRecord(record, this.store.getState().currentSessionId || "");
    if (!normalized) {
      return;
    }
    const fingerprint = fileChangeRecordFingerprint(normalized);
    if (this.fileChangeRecordFingerprints.get(normalized.record_id) === fingerprint) {
      return;
    }
    this.fileChangeRecordFingerprints.set(normalized.record_id, fingerprint);
    this.store.setState((prev) => this.mergeFileChangeRecords(prev, normalized, { incrementRevision: true }));
  }

  private async hydrateFileChangesForSession(sessionId = "", options: { force?: boolean; limit?: number } = {}) {
    const normalizedSessionId = String(sessionId || this.store.getState().currentSessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    const limit = Math.max(1, Math.min(Number(options.limit || 200), 500));
    const key = `${normalizedSessionId}:${limit}`;
    if (!options.force && this.fileChangeHydratedAtByKey.has(key)) {
      return;
    }
    const inFlight = this.fileChangeHydrateInFlight.get(key);
    if (inFlight) {
      await inFlight;
      return;
    }
    const hydrate = (async () => {
      const payload = await listFileChanges({ sessionId: normalizedSessionId, limit });
      const records = Array.isArray(payload.records)
        ? payload.records
            .map((item) => normalizeFileChangeRecord(item, normalizedSessionId))
            .filter((item): item is FileChangeRecord => Boolean(item))
        : [];
      for (const item of records) {
        this.fileChangeRecordFingerprints.set(item.record_id, fileChangeRecordFingerprint(item));
      }
      this.store.setState((prev) => ({
        ...prev,
        fileChangeRecordsBySession: {
          ...prev.fileChangeRecordsBySession,
          [normalizedSessionId]: sortFileChangeRecords(records).slice(0, limit),
        },
      }));
      this.fileChangeHydratedAtByKey.set(key, Date.now());
    })();
    this.fileChangeHydrateInFlight.set(key, hydrate);
    try {
      await hydrate;
    } finally {
      if (this.fileChangeHydrateInFlight.get(key) === hydrate) {
        this.fileChangeHydrateInFlight.delete(key);
      }
    }
  }

  private mergeFileChangeRecords(
    state: StoreState,
    record: FileChangeRecord,
    options: { incrementRevision?: boolean } = {},
  ): StoreState {
    const sessionId = record.session_id || state.currentSessionId || "";
    if (!sessionId) {
      return state;
    }
    const current = state.fileChangeRecordsBySession[sessionId] ?? [];
    const existingIndex = current.findIndex((item) => item.record_id === record.record_id);
    const nextRecords = existingIndex >= 0
      ? current.map((item, index) => (index === existingIndex ? record : item))
      : [record, ...current];
    return {
      ...state,
      fileChangesRevision: options.incrementRevision ? state.fileChangesRevision + 1 : state.fileChangesRevision,
      fileChangeRecordsBySession: {
        ...state.fileChangeRecordsBySession,
        [sessionId]: sortFileChangeRecords(nextRecords).slice(0, 500),
      },
    };
  }

  private setSessionEditorPageState(patch: SessionEditorPageStatePatch) {
    this.store.setState((prev) => {
      const clearsFiles = patch.activeFilePath === "" && Array.isArray(patch.openFilePaths) && patch.openFilePaths.length === 0;
      return this.patchCurrentSessionEditorContext(clearsFiles
        ? {
            ...prev,
            inspectorPath: DEFAULT_INSPECTOR_PATH,
            inspectorContent: "",
            inspectorContentSha256: "",
            inspectorDirty: false,
            inspectorTarget: null,
            inspectorLastChangeRecordId: "",
          }
        : prev,
        {
          activeFilePath: patch.activeFilePath,
          openFilePaths: patch.openFilePaths,
          ...(clearsFiles ? {
            inspectorPath: "",
            inspectorContent: "",
            inspectorContentSha256: "",
            inspectorDirty: false,
            inspectorTarget: null,
            inspectorLastChangeRecordId: "",
          } : {}),
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
    const workspaceView = view === "creative" ? "graph-repository" : view;
    this.syncWorkspaceViewUrl(workspaceView);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: workspaceView,
    }));
  }

  private workspaceViewForTaskEnvironment(taskEnvironmentId: string): WorkspaceView {
    const normalized = String(taskEnvironmentId || "").trim();
    if (GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(normalized)) {
      return "graph-repository";
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
    if (view === "graph-repository" || view === "creative" || GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(taskEnvironmentId)) {
      this.syncWorkspaceViewUrl("graph-repository");
      this.store.setState((prev) => ({
        ...prev,
        activeWorkspaceView: "graph-repository",
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
          taskEnvironmentCatalogError: this.errorMessage(error, "会话运行配置已在前端生效，但会话状态写入失败。"),
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
      this.syncWorkspaceViewUrl("graph-repository");
      this.store.setState((prev) => ({
        ...prev,
        activeWorkspaceView: "graph-repository",
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
        taskEnvironmentCatalogError: this.errorMessage(error, "会话运行配置切换失败。"),
      }));
    });
  }

  private centerWorkspaceHostView(_view: WorkspaceView): WorkspaceView {
    return "chat";
  }

  private openTaskGraphWorkspace(target: Omit<TaskGraphWorkspaceTarget, "layer" | "requested_at"> = {}) {
    const mode = target.mode ?? "monitor";
    const workspaceView: WorkspaceView = "graph-repository";
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

  private openWorkspaceFile(path: string, options: { lineNumber?: number } = {}) {
    const filePath = String(path || "").trim();
    if (!filePath) {
      return;
    }
    const lineNumber = normalizedWorkspaceLineNumber(options.lineNumber);
    const view = this.centerWorkspaceHostView(this.store.getState().activeWorkspaceView);
    this.syncWorkspaceViewUrl(view);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: view,
      centerWorkspaceTarget: {
        layer: "file",
        file_path: filePath,
        ...(lineNumber ? { line_number: lineNumber } : {}),
        requested_at: Date.now(),
      },
    }));
  }

  private openFileChangeDiff(target: Omit<FileChangeDiffCenterWorkspaceTarget, "layer" | "requested_at">) {
    const recordId = String(target?.record_id || "").trim();
    if (!recordId) {
      return;
    }
    const view = this.centerWorkspaceHostView(this.store.getState().activeWorkspaceView);
    this.syncWorkspaceViewUrl(view);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: view,
      centerWorkspaceTarget: {
        layer: "file-change-diff",
        record_id: recordId,
        baseline_record_id: String(target.baseline_record_id || "").trim() || undefined,
        mode: target.mode === "final" ? "final" : "single",
        change_count: finiteNumber(target.change_count),
        title: String(target.title || "").trim() || undefined,
        subtitle: String(target.subtitle || "").trim() || undefined,
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

  private openSessionProjection(target: Omit<SessionProjectionCenterWorkspaceTarget, "layer" | "requested_at">) {
    const sessionId = String(target?.session_id || "").trim();
    if (!sessionId) {
      return;
    }
    const view = this.centerWorkspaceHostView(this.store.getState().activeWorkspaceView);
    this.syncWorkspaceViewUrl(view);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: view,
      centerWorkspaceTarget: {
        layer: "session-projection",
        session_id: sessionId,
        scope: target.scope,
        title: String(target.title || "").trim() || undefined,
        subtitle: String(target.subtitle || "").trim() || undefined,
        source: String(target.source || "").trim() || undefined,
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

  private setAgentSystemInspectorTarget(target: StoreState["agentSystemInspectorTarget"]) {
    this.store.setState((prev) => ({ ...prev, agentSystemInspectorTarget: target }));
  }

  private setHarnessTurnSnapshot(snapshot: StoreState["harnessTurnSnapshot"]) {
    this.store.setState((prev) => ({ ...prev, harnessTurnSnapshot: snapshot }));
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
    const graphConfig = monitor?.graph_config && typeof monitor.graph_config === "object" && !Array.isArray(monitor.graph_config)
      ? monitor.graph_config as Record<string, unknown>
      : {};
    const graphRunId = String(state.taskGraphMonitorBinding?.graph_run_id || monitor?.graph_run_id || "").trim();
    const graphConfigId = String(state.taskGraphMonitorBinding?.graph_config_id || graphConfig.config_id || graphConfig.graph_config_id || "").trim();
    if (!graphRunId || !graphConfigId) {
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
        graph_config_id: graphConfigId,
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
      await stopHarnessTaskRun(taskRunId, "user_stop_graph_run", "");
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
      : monitor?.run_monitor && typeof monitor.run_monitor === "object" && !Array.isArray(monitor.run_monitor)
        ? monitor.run_monitor
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
      : monitor?.run_monitor && typeof monitor.run_monitor === "object" && !Array.isArray(monitor.run_monitor)
        ? monitor.run_monitor
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
    const graphConfigId = String(
      payload?.graph_config_id
      || this.store.getState().taskGraphMonitorBinding?.graph_config_id
      || ""
    ).trim();
    if (!graphConfigId) {
      throw new Error("新 GraphSystem 派发需要 graph_config_id。");
    }
    const controlState = this.boundTaskGraphRunControlState().toLowerCase();
    if (controlState === "paused") {
      await resumeGraphRun(runId, {
        graph_config_id: graphConfigId,
        session_scope: this.store.getState().taskGraphMonitorBinding?.session_scope,
        reason: "task_graph_interaction_resume",
      });
    } else if (controlState === "pause_requested" || controlState === "stop_requested") {
      throw new Error(controlState === "pause_requested" ? "暂停请求正在等待运行边界，等状态变为已暂停后再续跑。" : "停止请求正在等待运行边界，不能继续派发。");
    }
    await submitGraphRunUntilIdle(runId, {
      graph_config_id: graphConfigId,
      session_scope: this.store.getState().taskGraphMonitorBinding?.session_scope,
      max_node_executions: 1,
      max_loop_iterations: 4,
      max_dispatches: 1,
      max_dispatch_requests: Number(payload?.max_requests ?? 1),
    });
    await this.runMonitorController.evaluateBoundGraphMonitor().catch(() => undefined);
    await this.refreshRunMonitor();
  }

  private async hydrateLatestHarnessTurnSnapshot(sessionId: string): Promise<boolean> {
    const targetSessionId = sessionId.trim();
    const requestId = ++this.harnessTurnHydrateRequest;
    if (!targetSessionId) {
      this.store.setState((prev) => ({ ...prev, taskGraphLiveMonitor: null }));
      return false;
    }
    try {
      const liveMonitor = await getHarnessSessionLiveMonitor(targetSessionId);
      const liveMonitorRecord = liveMonitor && typeof liveMonitor === "object" && !Array.isArray(liveMonitor)
        ? liveMonitor as Record<string, unknown>
        : {};
      const activeTurnSnapshotFieldPresent = Object.prototype.hasOwnProperty.call(liveMonitorRecord, "active_turn_snapshot");
      const activeTurnSnapshot = this.activeTurnSnapshotFromPayload(liveMonitorRecord.active_turn_snapshot);
      const activeMonitor = this.activeHarnessSessionMonitor(liveMonitor);
      if (!activeMonitor) {
        if (this.store.getState().currentSessionId === targetSessionId && this.harnessTurnHydrateRequest === requestId) {
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
      if (this.store.getState().currentSessionId === targetSessionId && this.harnessTurnHydrateRequest === requestId) {
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

  private activeHarnessSessionMonitor(liveMonitor: Awaited<ReturnType<typeof getHarnessSessionLiveMonitor>>) {
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
    return String((monitor as Record<string, unknown>).control_state ?? "").trim();
  }

  private runtimeVisibleProgressText(value: unknown) {
    return publicRuntimeProgressText(value);
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
      this.syncWorkspaceViewUrl("graph-repository");
      this.store.setState((prev) => ({
        ...prev,
        activeWorkspaceView: "graph-repository",
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
        taskEnvironmentCatalogError: this.errorMessage(error, "会话运行配置切换失败。"),
      }));
    });
  }

  private clearChatTaskEnvironmentBinding() {
    void this.setActiveTaskEnvironment(GENERAL_TASK_ENVIRONMENT_ID, { source: "conversation" }).catch((error) => {
      this.store.setState((prev) => ({
        ...prev,
        taskEnvironmentCatalogError: this.errorMessage(error, "会话运行配置切换失败。"),
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

  private async runMonitorAction(payload: RunMonitorActionPayload): Promise<RunMonitorActionResult | null> {
    return await this.runMonitorController.runAction(payload);
  }

  applyRunMonitorSnapshot(
    monitor: RunMonitorEnvelope,
    options: { selectedSignalId?: string } = {},
  ) {
    this.runMonitorController.applySnapshot(monitor, options);
    this.syncCurrentSessionActivityFromRunMonitor();
  }

  applyRunMonitorStreamPayload(payload: RunMonitorEventPayload | null) {
    this.runMonitorController.applyStreamPayload(payload);
    this.afterRunMonitorStreamPayload(payload);
  }

  private afterRunMonitorStreamPayload(payload: RunMonitorEventPayload | null) {
    this.noteFileChangeSignalFromPayload(payload);
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

  private currentSessionActivitySignal(monitor: RunMonitorEnvelope, currentSessionId: string): RunMonitorSignal | null {
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

  private runMonitorSignalSessionId(signal: RunMonitorSignal) {
    const navigation = signal.navigation_target && typeof signal.navigation_target === "object" && !Array.isArray(signal.navigation_target)
      ? signal.navigation_target as Record<string, unknown>
      : {};
    return runtimeText(navigation.session_id || signal.session_id || signal.raw_refs?.session_id);
  }

  private runMonitorSignalHidden(signal: RunMonitorSignal) {
    const visibility = signal.visibility && typeof signal.visibility === "object" && !Array.isArray(signal.visibility)
      ? signal.visibility
      : {};
    return visibility.hidden === true || visibility.visible === false;
  }

  private shouldSyncRunMonitorSignalActivity(signal: RunMonitorSignal) {
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

  private runMonitorSignalActivityRank(signal: RunMonitorSignal) {
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

  private runMonitorSignalControlState(signal: RunMonitorSignal) {
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
      const title = projectedTitle || (runtimeRestartWaitingResume ? "连接恢复后待续跑" : effectiveStatus === "waiting_executor" ? "等待继续" : effectiveStatus === "waiting_approval" ? "等待确认" : effectiveStatus === "waiting_safe_boundary" ? "等待安全边界" : "运行受阻");
      const detail = projectedDetail || (runtimeRestartWaitingResume ? "连接已恢复，任务停在可恢复边界；点击继续或发送继续后会从当前任务继续调度。" : effectiveStatus === "waiting_executor" ? "任务已进入等待队列。" : effectiveStatus === "waiting_approval" ? "需要确认后继续执行。" : effectiveStatus === "waiting_safe_boundary" ? "暂停或中断请求已记录，当前步骤到达安全边界后会暂停或结束。" : "当前处理受阻。");
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

function finiteNumber(value: unknown): number | undefined {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : undefined;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function normalizedWorkspaceLineNumber(value: unknown): number | undefined {
  const numeric = Number(value);
  return Number.isInteger(numeric) && numeric > 0 ? Math.min(numeric, 999999) : undefined;
}

function normalizeInspectorLogicalPath(path: string) {
  return String(path || "").replace(/\\/g, "/").replace(/^\/+/, "").trim();
}

function isLegacyInternalInspectorPath(path: string) {
  const normalized = normalizeInspectorLogicalPath(path);
  return LEGACY_INTERNAL_INSPECTOR_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

function fileChangeRecordId(record: unknown) {
  if (!record || typeof record !== "object") {
    return "";
  }
  const recordId = (record as { record_id?: unknown }).record_id;
  return typeof recordId === "string" ? recordId.trim() : "";
}

function normalizeFileChangeRecord(value: unknown, sessionIdFallback = ""): FileChangeRecord | null {
  const recordId = fileChangeRecordId(value);
  if (!recordId || !value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const metadata = record.metadata && typeof record.metadata === "object" && !Array.isArray(record.metadata)
    ? record.metadata as Record<string, unknown>
    : undefined;
  return {
    record_id: recordId,
    session_id: runtimeText(record.session_id) || sessionIdFallback,
    task_run_id: runtimeText(record.task_run_id),
    agent_run_id: runtimeText(record.agent_run_id),
    tool_call_id: runtimeText(record.tool_call_id),
    tool_name: runtimeText(record.tool_name),
    operation_id: runtimeText(record.operation_id),
    workspace_root: runtimeText(record.workspace_root),
    logical_path: runtimeText(record.logical_path),
    absolute_path: runtimeText(record.absolute_path),
    before_exists: booleanValue(record.before_exists, true),
    after_exists: booleanValue(record.after_exists, true),
    before_sha256: runtimeText(record.before_sha256),
    after_sha256: runtimeText(record.after_sha256),
    before_snapshot_path: runtimeText(record.before_snapshot_path),
    after_snapshot_path: runtimeText(record.after_snapshot_path),
    status: runtimeText(record.status) || "recorded",
    created_at: finiteNumber(record.created_at) ?? Date.now() / 1000,
    rolled_back_at: finiteNumber(record.rolled_back_at),
    rollback_error: runtimeText(record.rollback_error) || undefined,
    metadata,
    authority: runtimeText(record.authority) || undefined,
  };
}

function booleanValue(value: unknown, fallback: boolean) {
  if (typeof value === "boolean") return value;
  if (value === "true") return true;
  if (value === "false") return false;
  return fallback;
}

function sortFileChangeRecords(records: FileChangeRecord[]) {
  return [...records].sort((left, right) =>
    Number(right.created_at || 0) - Number(left.created_at || 0)
    || String(right.record_id).localeCompare(String(left.record_id))
  );
}

function fileChangeRecordFingerprint(record: FileChangeRecord) {
  return JSON.stringify([
    record.record_id,
    record.session_id,
    record.task_run_id,
    record.logical_path,
    record.absolute_path,
    record.before_exists,
    record.after_exists,
    record.before_sha256,
    record.after_sha256,
    record.status,
    record.created_at,
    record.rolled_back_at ?? null,
    record.rollback_error ?? "",
  ]);
}

function fileChangeRecordsFromPayload(
  value: unknown,
  depth = 0,
  seenObjects = new WeakSet<object>(),
  seenRecordIds = new Set<string>(),
): unknown[] {
  if (!value || typeof value !== "object" || depth > 6) {
    return [];
  }
  if (seenObjects.has(value)) {
    return [];
  }
  seenObjects.add(value);
  const records: unknown[] = [];
  const collect = (candidate: unknown) => {
    const recordId = fileChangeRecordId(candidate);
    if (!recordId || seenRecordIds.has(recordId)) {
      return;
    }
    seenRecordIds.add(recordId);
    records.push(candidate);
  };
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 50)) {
      records.push(...fileChangeRecordsFromPayload(item, depth + 1, seenObjects, seenRecordIds));
    }
    return records;
  }
  const record = value as Record<string, unknown>;
  collect(record.file_change_record);
  const fileChange = record.file_change;
  if (fileChange && typeof fileChange === "object" && !Array.isArray(fileChange)) {
    collect(fileChange);
    collect((fileChange as Record<string, unknown>).record);
  }
  const fileChanges = record.file_changes;
  if (Array.isArray(fileChanges)) {
    records.push(...fileChangeRecordsFromPayload(fileChanges, depth + 1, seenObjects, seenRecordIds));
  } else if (fileChanges && typeof fileChanges === "object") {
    records.push(...fileChangeRecordsFromPayload(
      (fileChanges as Record<string, unknown>).records,
      depth + 1,
      seenObjects,
      seenRecordIds,
    ));
  }
  collect(value);
  for (const key of [
    "payload",
    "result",
    "result_envelope",
    "structured_payload",
    "tool_result",
    "monitor",
    "observation",
    "event",
    "events",
    "signals",
    "latest_event",
    "metadata",
    "data",
  ]) {
    records.push(...fileChangeRecordsFromPayload(record[key], depth + 1, seenObjects, seenRecordIds));
  }
  return records;
}

function isFileSelectionCancelled(error: unknown) {
  return /file selection cancelled|selection cancelled/i.test(errorDetailMessage(error));
}

function clientNow() {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}



