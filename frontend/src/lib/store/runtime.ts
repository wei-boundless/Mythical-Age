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
  getImageAssetConfig,
  getTaskEnvironmentCatalog,
  getWorkspaceContext,
  getOrchestrationHarnessSessionLiveMonitor,
  approveOrchestrationHarnessTaskRunToolCall,
  pauseOrchestrationHarnessTaskRun,
  getPermissionMode,
  getRagMode,
  resumeOrchestrationHarnessTaskRun,
  setPermissionMode as setRuntimePermissionMode,
  setSessionActiveTaskEnvironment,
  setSessionPermissionMode,
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
  truncateSessionMessages
} from "@/lib/api";
import type { ChatStreamCursor, GlobalRuntimeMonitor, PublicChatTimelineItem, RuntimeMonitorEventPayload, SessionRuntimeAttachment, SessionScope, SessionSummary } from "@/lib/api";
import { taskEnvironmentDisplayName } from "@/lib/taskEnvironmentDisplay";

import { createIdleSessionActivity, type Store } from "./core";
import { reduceStreamEvent, startQueuedActiveTurn, startStreamingTurn, type StreamSession } from "./events";
import { RuntimeMonitorController } from "../runtime-monitor/controller";
import type { ActiveTurnSnapshot, ChatMode, ChatModelSelection, ChatTaskEnvironmentBinding, ChatThinkingMode, Message, PermissionMode, RuntimeProgressEntry, SearchPolicySource, SessionPoolKey, SessionRef, StoreActions, StoreState, TaskEnvironmentWorkspaceView, TaskGraphCenterWorkspaceTarget, TaskGraphMonitorBinding, TaskSelectionState, WorkspaceView } from "./types";
import { makeId, toUiMessages } from "./utils";

type HarnessSessionMonitor = NonNullable<Awaited<ReturnType<typeof getOrchestrationHarnessSessionLiveMonitor>>["monitor"]>;
type RuntimeMonitorEvent = NonNullable<RuntimeMonitorEventPayload["runtime_event"]>;
const MAX_LIVE_RUNTIME_PROGRESS_ENTRIES = 24;
const MAIN_CHAT_POOL_KEY: SessionPoolKey = "main-chat";
const GENERAL_TASK_ENVIRONMENT_ID = "env.general.workspace";
const CODING_TASK_ENVIRONMENT_ID = "env.coding.vibe_workspace";
const DEFAULT_PERMISSION_MODE: PermissionMode = "full_access";
const GRAPH_ONLY_TASK_ENVIRONMENT_IDS = new Set(["env.creation.writing"]);
const CODE_TASK_ENVIRONMENT_IDS = new Set([CODING_TASK_ENVIRONMENT_ID, "env.development.sandbox"]);

function sessionTaskEnvironmentId(session: SessionSummary) {
  return String(
    session.scope?.task_environment_id
    || session.task_binding?.task_environment_id
    || session.task_binding?.session_scope?.task_environment_id
    || "",
  ).trim();
}

function visibleMainChatSessions(sessions: SessionSummary[]) {
  return sessions.filter((session) => {
    if (String(session.scope?.workspace_view || "").trim() === "task_environment") {
      return false;
    }
    if (String(session.task_binding?.kind || "").trim() === "task_graph") {
      return false;
    }
    return !GRAPH_ONLY_TASK_ENVIRONMENT_IDS.has(sessionTaskEnvironmentId(session));
  });
}

function sessionPoolKeyForScope(scope: Partial<SessionScope> | undefined): SessionPoolKey {
  if (scope?.workspace_view === "task_environment") {
    return `task_environment:${String(scope.task_environment_id || "").trim()}:${String(scope.project_id || "").trim()}` as SessionPoolKey;
  }
  return MAIN_CHAT_POOL_KEY;
}

type TaskEnvironmentCatalogItem = NonNullable<StoreState["taskEnvironmentCatalog"]>["environments"][number];

function taskEnvironmentIdOf(item: TaskEnvironmentCatalogItem | null | undefined) {
  const record = (item?.record ?? {}) as Record<string, unknown>;
  return String(record.environment_id || "").trim();
}

function taskEnvironmentLabelOf(item: TaskEnvironmentCatalogItem | null | undefined) {
  const record = (item?.record ?? {}) as Record<string, unknown>;
  const environmentId = String(record.environment_id || "").trim();
  return taskEnvironmentDisplayName(environmentId, String(record.title || "").trim());
}

function isCatalogEnvironmentVisible(item: TaskEnvironmentCatalogItem) {
  const record = (item.record ?? {}) as Record<string, unknown>;
  if (record.enabled === false) {
    return false;
  }
  return String(item.management_scope || record.management_scope || "").trim() !== "system_internal";
}

export class WorkspaceRuntime {
  private initializePromise: Promise<void> | null = null;
  private createSessionPromise: Promise<string> | null = null;
  private sessionDetailsRequest = 0;
  private orchestrationHydrateRequest = 0;
  private runtimeMonitorController: RuntimeMonitorController;
  private sessionRefreshTimers: number[] = [];
  private sessionListFailureNotifiedAt = 0;
  private streamingSessionCache = new Map<string, Pick<StoreState, "messages" | "orchestrationSnapshot" | "activeTurnSnapshot">>();
  private removedStreamingSessionIds = new Set<string>();
  private streamAbortControllers = new Map<string, AbortController>();
  private stoppedStreamingSessionIds = new Set<string>();
  private recoveringStreamSessionIds = new Set<string>();
  private queuedUserInputsBySession = new Map<string, Array<{ content: string; messageId: string }>>();
  private flushingQueuedUserInputs = new Set<string>();

  readonly actions: StoreActions;

  constructor(private readonly store: Store<StoreState>) {
    this.runtimeMonitorController = new RuntimeMonitorController(this.store, {
      hasActiveChatStream: () => this.hasActiveChatStream(),
      patchRuntimeAttachmentFromRuntimeEvent: (prev, event) => this.patchRuntimeAttachmentFromRuntimeEvent(prev, event as RuntimeMonitorEvent),
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
      createNewSession: async () => {
        await this.createNewSession();
      },
      selectSession: async (ref) => {
        await this.selectSession(ref);
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
      selectGlobalRuntimeMonitorTaskRun: (taskRunId) => {
        this.selectGlobalRuntimeMonitorTaskRun(taskRunId);
      },
      openGlobalRuntimeMonitorTaskRun: (taskRunId) => {
        this.openGlobalRuntimeMonitorTaskRun(taskRunId);
      },
      openTaskGraphWorkspace: (target) => {
        this.openTaskGraphWorkspace(target);
      },
      openWorkspaceFile: (path) => {
        this.openWorkspaceFile(path);
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
      await this.refreshTaskEnvironmentCatalog();
      let sessions = visibleMainChatSessions(await listSessions());
      this.store.setState((prev) => ({
        ...prev,
        sessions,
      }));

      const currentSessionId = this.store.getState().currentSessionId;
      if (!currentSessionId && sessions.length) {
        const sessionId = sessions[0].id;
        const restoredFromStreamCache = this.applySelectedSessionShell(sessionId, {
          scope: sessions[0].scope,
          poolKey: MAIN_CHAT_POOL_KEY,
        });
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
    const [rag, permissionMode, skills, modelProviderConfig, imageAssetConfig, workspaceContext] = await Promise.all([
      getRagMode().catch(() => null),
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
        ragMode: Boolean(rag?.enabled),
        searchPolicy: {
          ...prev.searchPolicy,
          rag: Boolean(rag?.enabled)
        },
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
      const nextState = { ...prev, sessions };
      const projected = {
        ...nextState,
        permissionMode: this.permissionModeForSession(prev.currentSessionId, nextState, prev.permissionMode),
      };
      if (prev.currentSessionId && prev.sessionActivity.event === "workspace_initialize_failed") {
        return this.clearSessionActivityFor(projected, prev.currentSessionId);
      }
      return projected;
    });
    return sessions;
  }

  private refreshMainSessionPoolInBackground() {
    void this.refreshMainSessionPool().catch((error) => {
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
          ? this.normalizeActiveTaskEnvironment(prev.conversationActiveEnvironment)
          : null;
        return {
          ...prev,
          taskEnvironmentCatalog: catalog,
          taskEnvironmentCatalogLoading: false,
          taskEnvironmentCatalogError: "",
          conversationActiveEnvironment: active,
        };
      });
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
      const history = await getSessionTimeline(sessionId, scope).catch(() => getSessionHistory(sessionId, scope));
      let tokens = null;
      let tokenStatsRefreshed = false;
      try {
        tokens = await getSessionTokens(sessionId, scope);
        tokenStatsRefreshed = true;
      } catch (tokenError) {
        console.debug("[workspace-runtime] session token refresh skipped", {
          event: "session_token_refresh_failed",
          sessionId,
          error: this.errorMessage(tokenError, "会话 token 统计暂时读取失败。"),
        });
      }
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
          tokenStats: tokenStatsRefreshed ? tokens : prev.tokenStats,
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
    if (!currentMessages.some((message) => message.runtimeProgress?.length || message.runtimePublicTimelineDraft?.length)) {
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
      if (!current?.runtimeProgress?.length && !current?.runtimePublicTimelineDraft?.length) {
        return message;
      }
      const persistedPublicTimeline = (message.runtimeAttachments ?? []).flatMap((attachment) =>
        Array.isArray(attachment.public_timeline) ? attachment.public_timeline : [],
      );
      return {
        ...message,
        runtimeProgress: this.mergeMessageRuntimeProgress(message.runtimeProgress, current.runtimeProgress ?? []),
        runtimePublicTimelineDraft: this.mergePublicTimelineItems(
          persistedPublicTimeline,
          current.runtimePublicTimelineDraft,
        ),
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

  private enqueueUserInputForSession(sessionId: string, content: string) {
    const messageId = makeId();
    const queued = this.queuedUserInputsBySession.get(sessionId) ?? [];
    this.queuedUserInputsBySession.set(sessionId, [...queued, { content, messageId }]);
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
      await this.sendMessage(next.content, { queuedUserMessageId: next.messageId });
    } finally {
      this.flushingQueuedUserInputs.delete(sessionId);
      if ((this.queuedUserInputsBySession.get(sessionId) ?? []).length) {
        void this.flushQueuedUserInputsForSession(sessionId);
      }
    }
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
      activeTurnSnapshot: streamState.activeTurnSnapshot,
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
      const created = await createSession("New Session");
      const conversationActiveEnvironment =
        this.activeEnvironmentForSession(created)
        ?? this.store.getState().conversationActiveEnvironment
        ?? this.defaultActiveTaskEnvironment();
      const permissionMode = this.permissionModeForSession(created.id, { ...this.store.getState(), sessions: [created] }, DEFAULT_PERMISSION_MODE);
      this.store.setState((prev) => ({
        ...prev,
        sessions: [
          {
            ...created,
            conversation_state: this.conversationStateWithPermissionMode(created.conversation_state, permissionMode),
          },
          ...prev.sessions.filter((session) => session.id !== created.id),
        ],
        currentSessionId: created.id,
        activeSessionScope: null,
        activeSessionRef: {
          sessionId: created.id,
          poolKey: MAIN_CHAT_POOL_KEY,
        },
        conversationActiveEnvironment,
        permissionMode,
        messages: [],
        tokenStats: null
      }));
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
    this.store.setState((prev) => ({
      ...prev,
      currentSessionId: sessionId,
      activeSessionScope: null,
      activeSessionRef: {
        sessionId,
        poolKey: MAIN_CHAT_POOL_KEY,
      },
      messages: [],
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: null,
      tokenStats: null
    }));
    this.store.setState((prev) => this.clearSessionActivityFor(prev, sessionId));
    await this.refreshMainSessionPool().catch((error) => {
      this.noteSessionRefreshFailure(error);
    });
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
    const inferredScope = !explicitScope && ref.poolKey !== MAIN_CHAT_POOL_KEY
      ? this.resolveSessionScope(sessionId, state) ?? undefined
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

  private taskEnvironmentCatalogItem(taskEnvironmentId: string) {
    const normalized = String(taskEnvironmentId || "").trim();
    if (!normalized) {
      return null;
    }
    return this.store.getState().taskEnvironmentCatalog?.environments.find((item) => taskEnvironmentIdOf(item) === normalized) ?? null;
  }

  private taskEnvironmentLabel(taskEnvironmentId: string) {
    return taskEnvironmentLabelOf(this.taskEnvironmentCatalogItem(taskEnvironmentId)) || taskEnvironmentId;
  }

  private normalizeActiveTaskEnvironment(
    activeEnvironment: Partial<NonNullable<StoreState["conversationActiveEnvironment"]>> | null | undefined,
  ): StoreState["conversationActiveEnvironment"] {
    const taskEnvironmentId = String(
      activeEnvironment?.task_environment_id
      || (activeEnvironment as Record<string, unknown> | null | undefined)?.environment_id
      || ""
    ).trim();
    if (!taskEnvironmentId) {
      return null;
    }
    return {
      task_environment_id: taskEnvironmentId,
      environment_label: taskEnvironmentDisplayName(
        taskEnvironmentId,
        String(activeEnvironment?.environment_label || this.taskEnvironmentLabel(taskEnvironmentId)).trim(),
      ),
      source: String(activeEnvironment?.source || "conversation").trim() || "conversation",
      updated_at: Number(activeEnvironment?.updated_at || Date.now() / 1000),
      authority: String(activeEnvironment?.authority || "frontend.conversation_active_task_environment"),
    };
  }

  private defaultActiveTaskEnvironment(source = "conversation"): NonNullable<StoreState["conversationActiveEnvironment"]> {
    const defaultId = this.taskEnvironmentCatalogItem(GENERAL_TASK_ENVIRONMENT_ID)
      ? GENERAL_TASK_ENVIRONMENT_ID
      : taskEnvironmentIdOf(this.store.getState().taskEnvironmentCatalog?.environments.find(isCatalogEnvironmentVisible))
        || GENERAL_TASK_ENVIRONMENT_ID;
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
    return this.normalizeActiveTaskEnvironment(conversationState?.active_task_environment);
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
    const streamingCache = this.streamingSessionCache.get(normalized.sessionId);
    if (this.store.getState().activeStreamSessionIds.includes(normalized.sessionId) && streamingCache) {
      const selectedSession = this.store.getState().sessions.find((session) => session.id === normalized.sessionId);
      const conversationActiveEnvironment = this.shouldUseConversationEnvironment(normalized)
        ? this.activeEnvironmentForSession(selectedSession) ?? this.store.getState().conversationActiveEnvironment ?? this.defaultActiveTaskEnvironment()
        : this.store.getState().conversationActiveEnvironment;
      const permissionMode = this.permissionModeForSession(normalized.sessionId, this.store.getState());
      this.store.setState((prev) => ({
        ...prev,
        currentSessionId: normalized.sessionId,
        activeSessionScope: normalized.scope ?? null,
        activeSessionRef: normalized,
        conversationActiveEnvironment,
        permissionMode,
        messages: streamingCache.messages,
        orchestrationSnapshot: streamingCache.orchestrationSnapshot,
        activeTurnSnapshot: streamingCache.activeTurnSnapshot,
        taskGraphLiveMonitor: null,
        tokenStats: null
      }));
      this.store.setState((prev) => this.projectSelectedSessionActivity(prev, normalized.sessionId));
      this.projectPermissionModeToRuntime(permissionMode);
      return true;
    }
    const selectedSession = this.store.getState().sessions.find((session) => session.id === normalized.sessionId);
    const conversationActiveEnvironment = this.shouldUseConversationEnvironment(normalized)
      ? this.activeEnvironmentForSession(selectedSession) ?? this.store.getState().conversationActiveEnvironment ?? this.defaultActiveTaskEnvironment()
      : this.store.getState().conversationActiveEnvironment;
    const permissionMode = this.permissionModeForSession(normalized.sessionId, this.store.getState());
    this.store.setState((prev) => ({
      ...prev,
      currentSessionId: normalized.sessionId,
      activeSessionScope: normalized.scope ?? null,
      activeSessionRef: normalized,
      conversationActiveEnvironment,
      permissionMode,
      messages: [],
      orchestrationSnapshot: null,
      activeTurnSnapshot: null,
      taskGraphLiveMonitor: null,
      tokenStats: null
    }));
    this.store.setState((prev) => this.projectSelectedSessionActivity(prev, normalized.sessionId));
    this.projectPermissionModeToRuntime(permissionMode);
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
        } else if (this.chatRunCursorAlreadyReachedTerminal(cursorRun, cursor)) {
          clearChatStreamCursor(sessionId);
          await this.refreshSessionDetails(sessionId).catch(() => undefined);
          return false;
        } else {
          this.applyActiveTurnSnapshotFromChatRun(cursorRun);
        }
      }
      if (!streamRunId) {
        const latestRun = await getLatestChatRunForSession(sessionId, true, this.sessionScopeForSession(sessionId)).catch(() => null);
        this.applyActiveTurnSnapshotFromChatRun(latestRun);
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

  private chatRunCursorAlreadyReachedTerminal(run: { terminal_event?: string; latest_event_offset?: number }, cursor: ChatStreamCursor | null) {
    const terminalEvent = String(run.terminal_event || "").trim();
    if (!terminalEvent || !["done", "error", "stopped"].includes(terminalEvent)) {
      return false;
    }
    const latestOffset = Number(run.latest_event_offset ?? -1);
    const cursorOffset = Number(cursor?.lastEventOffset ?? -1);
    return Number.isFinite(latestOffset)
      && Number.isFinite(cursorOffset)
      && cursorOffset >= latestOffset;
  }

  private applyActiveTurnSnapshotFromChatRun(run: { active_turn_snapshot?: Record<string, unknown> | null } | null | undefined) {
    const activeTurnSnapshot = this.activeTurnSnapshotFromPayload(run?.active_turn_snapshot);
    if (!activeTurnSnapshot) {
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      activeTurnSnapshot,
    }));
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
      state: String(payload.state ?? "").trim() || undefined,
      updated_at: Number(payload.updated_at ?? 0) || undefined,
    };
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
      activeTurnSnapshot: streamState.activeTurnSnapshot,
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
                activeTurnSnapshot: streamState.activeTurnSnapshot,
              });
              if (isCurrentStreamSession) {
                this.applyVisibleStreamState(streamState, currentActiveStreamSessionIds);
              }
            }
          },
          {
            signal: abortController.signal,
            initialCursor: cursor,
            replayFromStart: !cursor,
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
          activeTurnSnapshot: streamState.activeTurnSnapshot,
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
        this.refreshMainSessionPoolInBackground();
        this.scheduleSessionRefreshes();
        void this.flushQueuedUserInputsForSession(sessionId);
      }
    })();
  }

  private async sendMessage(value: string, options: { queuedUserMessageId?: string } = {}) {
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
      if (options.queuedUserMessageId) {
        const queued = this.queuedUserInputsBySession.get(sessionId) ?? [];
        this.queuedUserInputsBySession.set(sessionId, [
          { content: trimmed, messageId: options.queuedUserMessageId },
          ...queued,
        ]);
        return;
      }
      this.enqueueUserInputForSession(sessionId, trimmed);
      return;
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
    const preflightState = this.store.getState();
    const activeTurnSnapshotForTransition = preflightState.currentSessionId === sessionId
      ? preflightState.activeTurnSnapshot
      : null;
    const queueActiveTurnInput = this.shouldQueueActiveTurnInput(preflightState, sessionId);
    this.store.setState((prev) => ({
      ...prev,
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: queueActiveTurnInput ? prev.taskGraphLiveMonitor : null,
      orchestrationInspectorTarget: prev.orchestrationInspectorTarget?.source === "live-session"
        ? null
        : prev.orchestrationInspectorTarget,
    }));
    let transition = queueActiveTurnInput
      ? startQueuedActiveTurn(this.store.getState(), trimmed, { existingUserMessageId: options.queuedUserMessageId })
      : startStreamingTurn(this.store.getState(), trimmed, { existingUserMessageId: options.queuedUserMessageId });
    const nextSourceIndex = this.nextMessageSourceIndex(this.store.getState().messages);
    transition = {
      ...transition,
      state: {
        ...transition.state,
        messages: transition.state.messages.map((message) =>
          transition.session.userId && message.id === transition.session.userId
            ? { ...message, sourceIndex: nextSourceIndex }
            : !transition.session.queueOnly && transition.session.assistantId && message.id === transition.session.assistantId
              ? { ...message, sourceIndex: nextSourceIndex + 1 }
            : message
        )
      }
    };
    const activeStreamSessionIds = queueActiveTurnInput
      ? this.store.getState().activeStreamSessionIds
      : this.store.getState().activeStreamSessionIds.includes(sessionId)
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
      activeTurnSnapshot: streamState.activeTurnSnapshot,
    });
    if (!queueActiveTurnInput) {
      this.addActiveStreamSession(sessionId);
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
      const permissionMode = this.permissionModeForSession(sessionId, requestState);
      const streamResult = await streamChat(
        {
          message: trimmed,
          session_id: sessionId,
          session_scope: this.sessionScopeForSession(sessionId),
          ephemeral_system_messages: ephemeralSystemMessages,
          search_policy: searchPolicy,
          task_selection: this.chatTaskSelectionPayload(requestState),
          model_selection: this.chatModelSelectionPayload(requestState),
          permission_mode: permissionMode,
          expected_active_turn_id: String(activeTurnForRequest?.turn_id ?? ""),
          active_turn_input_policy: activeTurnForRequest?.turn_id ? "steer" : "auto",
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
            const currentActiveStreamSessionIds = queueActiveTurnInput
              ? this.store.getState().activeStreamSessionIds
              : this.store.getState().activeStreamSessionIds.includes(sessionId)
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
              activeTurnSnapshot: streamState.activeTurnSnapshot,
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
      const currentActiveStreamSessionIds = queueActiveTurnInput
        ? this.store.getState().activeStreamSessionIds
        : this.store.getState().activeStreamSessionIds.includes(sessionId)
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
        activeTurnSnapshot: streamState.activeTurnSnapshot,
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
      this.refreshMainSessionPoolInBackground();
      this.scheduleSessionRefreshes();
      void this.flushQueuedUserInputsForSession(sessionId);
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
    await pauseOrchestrationHarnessTaskRun(taskRunId, "user_pause_from_chat", this.activeExpectedTurnIdForTaskRun(taskRunId));
    await this.refreshActiveSessionMonitor();
  }

  private async resumeActiveTaskRun() {
    const taskRunId = this.activeControllableTaskRunId();
    if (!taskRunId) {
      return;
    }
    const expectedTurnId = this.activeExpectedTurnIdForTaskRun(taskRunId);
    if (this.activeTaskRunStatus(taskRunId) === "waiting_approval") {
      await approveOrchestrationHarnessTaskRunToolCall(taskRunId, "user_approve_tool_from_chat", 12, expectedTurnId);
    } else {
      await resumeOrchestrationHarnessTaskRun(taskRunId, 12, expectedTurnId);
    }
    await this.refreshActiveSessionMonitor();
  }

  private async stopActiveTaskRun() {
    const taskRunId = this.activeControllableTaskRunId();
    if (!taskRunId) {
      return;
    }
    await stopOrchestrationHarnessTaskRun(taskRunId, "user_stop_from_chat", this.activeExpectedTurnIdForTaskRun(taskRunId));
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
    const snapshot = this.store.getState().activeTurnSnapshot;
    if (String(snapshot?.task_run_id ?? "").trim() !== taskRunId) {
      return "";
    }
    return String(snapshot?.turn_id ?? "").trim();
  }

  private shouldQueueActiveTurnInput(state: StoreState, sessionId: string) {
    if (state.currentSessionId !== sessionId) {
      return false;
    }
    const snapshot = state.activeTurnSnapshot;
    const activeTurnId = String(snapshot?.turn_id ?? "").trim();
    if (!activeTurnId) {
      return false;
    }
    const activeTaskRunId = String(snapshot?.task_run_id ?? "").trim();
    const monitor = state.taskGraphLiveMonitor;
    if (monitor && activeTaskRunId) {
      const taskRun = this.harnessMonitorTaskRun(monitor);
      const monitorTaskRunId = String(taskRun.task_run_id ?? monitor.task_run_id ?? "").trim();
      if (monitorTaskRunId === activeTaskRunId) {
        const monitorRecord = monitor as Record<string, unknown>;
        const route = monitorRecord.route && typeof monitorRecord.route === "object" && !Array.isArray(monitorRecord.route)
          ? monitorRecord.route as Record<string, unknown>
          : {};
        const executionRuntimeKind = String(monitor.execution_runtime_kind ?? taskRun.execution_runtime_kind ?? "").trim();
        const status = String(monitor.status ?? taskRun.status ?? "").trim();
        const runtimeControl = monitor.runtime_control ?? {};
        const controlState = String(monitor.control_state ?? runtimeControl.state ?? "").trim();
        return (
          executionRuntimeKind === "single_agent_task"
          && String(route.kind ?? "").trim() !== "task_graph_run"
          && ["created", "running"].includes(status)
          && !["paused", "pause_requested", "stopped", "stop_requested"].includes(controlState)
        );
      }
    }
    return String(snapshot?.state ?? "").trim() === "running_task";
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

  private chatTaskSelectionPayload(state: StoreState): Record<string, unknown> | undefined {
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
    const imageConfig = state.imageAssetConfig;
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
      credential_ref: imageConfig.api_key_present ? "image-assets:api-key" : undefined,
      asset_kind: "chat",
      size: "1024x1024"
    };
  }

  private enabledSearchPolicy(state: StoreState) {
    return (Object.entries(state.searchPolicy) as Array<[SearchPolicySource, boolean]>)
      .filter(([, enabled]) => enabled)
      .map(([source]) => source);
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
    const wasCurrentSession = this.store.getState().currentSessionId === sessionId;
    await deleteSession(sessionId, deletedSessionScope);
    this.streamingSessionCache.delete(sessionId);
    this.removedStreamingSessionIds.add(sessionId);
    this.streamAbortControllers.get(sessionId)?.abort();
    this.streamAbortControllers.delete(sessionId);
    this.store.setState((prev) => {
      const next = this.removeActiveStreamSession(prev, sessionId);
      const { [sessionId]: _removed, ...sessionActivitiesById } = next.sessionActivitiesById;
      return {
        ...next,
        sessions: next.sessions.filter((session) => session.id !== sessionId),
        sessionActivitiesById,
        sessionActivity: next.currentSessionId === sessionId ? createIdleSessionActivity(Date.now()) : next.sessionActivity,
      };
    });

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
      sessionActivity: createIdleSessionActivity(Date.now())
    }));
  }

  private async loadInspectorFile(path: string) {
    try {
      const file = await loadFile(path);
      this.store.setState((prev) => ({
        ...prev,
        inspectorPath: file.path,
        inspectorContent: file.content,
        inspectorDirty: false,
        workspaceTreeError: ""
      }));
    } catch (error) {
      const message = this.errorMessage(error, `无法打开文件：${path}`);
      this.store.setState((prev) => ({
        ...prev,
        inspectorPath: path,
        inspectorContent: message,
        inspectorDirty: false,
        workspaceTreeError: message
      }));
    }
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
    if (this.isTaskEnvironmentWorkspaceView(view)) {
      this.setTaskEnvironmentWorkspaceView(view);
      return;
    }
    this.syncWorkspaceViewUrl(view);
    this.store.setState((prev) => ({ ...prev, activeWorkspaceView: view }));
  }

  private isTaskEnvironmentWorkspaceView(view: WorkspaceView): view is TaskEnvironmentWorkspaceView {
    return view === "chat" || view === "code-environment";
  }

  private setTaskEnvironmentWorkspaceView(view: TaskEnvironmentWorkspaceView) {
    const taskEnvironmentId = this.defaultTaskEnvironmentIdForView(view);
    void this.setActiveTaskEnvironment(taskEnvironmentId, { source: "workspace-mode" });
  }

  private defaultTaskEnvironmentIdForView(view: TaskEnvironmentWorkspaceView) {
    const catalog = this.store.getState().taskEnvironmentCatalog;
    if (view === "code-environment") {
      for (const candidate of [CODING_TASK_ENVIRONMENT_ID, "env.development.sandbox"]) {
        if (catalog?.environments.some((item) => isCatalogEnvironmentVisible(item) && taskEnvironmentIdOf(item) === candidate)) {
          return candidate;
        }
      }
      const codeCandidate = catalog?.environments.find((item) => {
        const kind = String(item.record?.environment_kind || "").trim();
        return isCatalogEnvironmentVisible(item) && (kind === "coding" || kind === "development");
      });
      return taskEnvironmentIdOf(codeCandidate) || CODING_TASK_ENVIRONMENT_ID;
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
    if (CODE_TASK_ENVIRONMENT_IDS.has(normalized) || kind === "coding" || kind === "development") {
      return "code-environment";
    }
    return "chat";
  }

  private async setActiveTaskEnvironment(environmentId: string, options: { environmentLabel?: string; source?: string } = {}) {
    const taskEnvironmentId = String(environmentId || "").trim();
    if (!taskEnvironmentId) {
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
      environment_label: String(options.environmentLabel || this.taskEnvironmentLabel(taskEnvironmentId)).trim() || taskEnvironmentId,
      source: options.source || "conversation",
      updated_at: Date.now() / 1000,
      authority: "frontend.conversation_active_task_environment",
    };
    this.syncWorkspaceViewUrl(view);
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

  private openTaskGraphWorkspace(target: Omit<TaskGraphCenterWorkspaceTarget, "layer" | "requested_at"> = {}) {
    const view = this.centerWorkspaceHostView(this.store.getState().activeWorkspaceView);
    this.syncWorkspaceViewUrl(view);
    this.store.setState((prev) => ({
      ...prev,
      activeWorkspaceView: view,
      centerWorkspaceTarget: {
        layer: "task-graph",
        mode: target.mode ?? "editor",
        graph_id: String(target.graph_id ?? "").trim() || undefined,
        task_run_id: String(target.task_run_id ?? "").trim() || undefined,
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
      taskGraphMonitorActionLoading: true,
      taskGraphMonitorError: "",
    }));
    try {
      await stopOrchestrationHarnessTaskRun(taskRunId, "user_stop_graph_run", "");
      await this.runtimeMonitorController.evaluateBoundGraphMonitor().catch(() => undefined);
      await this.refreshGlobalRuntimeMonitor();
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
      session_scope: this.store.getState().taskGraphMonitorBinding?.session_scope,
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
      const hasActiveHarnessRun = ["created", "running", "waiting_executor", "waiting_approval", "blocked"].includes(liveStatus) && !staleOrDiagnostic;
      const hasPendingApproval = liveStatus === "waiting_approval" || String((activeMonitor.loop_state as Record<string, unknown> | undefined)?.terminal_reason ?? "") === "waiting_approval";
      const taskRunId = String(activeTaskRun.task_run_id ?? activeMonitor.task_run_id ?? liveMonitor.active_task_run_id ?? "").trim();
      const graphRunId = String(activeMonitor.graph_run_id ?? activeTaskRun.graph_run_id ?? "").trim();
      this.updateSessionActivityFromLiveMonitor(liveStatus, taskRunId, graphRunId, controlState);
      if (this.store.getState().currentSessionId === targetSessionId && this.orchestrationHydrateRequest === requestId) {
        this.store.setState((prev) => ({
          ...this.patchRuntimeAttachmentFromMonitor(
            activeTurnSnapshot ? { ...prev, activeTurnSnapshot } : prev,
            activeMonitor
          ),
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
    const kind = this.runtimeProgressKindFromStep(stepName);
    const meta = this.runtimeProgressMetaFromPayload(latestStep);
    const actionBody = kind === "model" && meta.length
      ? meta.map((item) => `${item.label}：${item.value}`).join("；")
      : "";
    return {
      id: eventId || `${taskRunId}:latest-step:${eventCount || String(latestStep.step ?? latestStep.status ?? "current")}`,
      title: kind === "model" ? "正在思考" : String(monitor.latest_step_summary ?? publicNote) || "正在处理",
      body: actionBody || publicNote || String(monitor.latest_step_summary ?? ""),
      publicNote,
      agentBrief,
      evidenceType: this.runtimeEvidenceTypeFromStep(stepName),
      eventType: String((monitor.latest_event as Record<string, unknown> | undefined)?.event_type ?? "runtime_live_monitor"),
      kind,
      level: this.runtimeProgressLevelFromStatus(String(latestStep.status ?? monitor.latest_step_status ?? monitor.status ?? "")),
      statusText: String(latestStep.status ?? monitor.latest_step_status ?? monitor.status ?? ""),
      runId: taskRunId,
      taskRunId,
      createdAt: Number(latestStep.created_at ?? 0) || undefined,
      meta: meta.length ? meta : undefined,
    };
  }

  private publicTimelineItemFromRuntimeProgressEntry(entry: RuntimeProgressEntry | null): PublicChatTimelineItem | null {
    if (!entry) {
      return null;
    }
    const eventType = String(entry.eventType ?? "").trim();
    if (["done", "agent_turn_terminal"].includes(eventType)) {
      return null;
    }
    const kind = String(entry.kind ?? "").trim();
    const body = this.publicRuntimeText(entry.publicNote || entry.agentBrief || entry.body || entry.title);
    const title = this.publicRuntimeText(entry.title);
    if (!body && !title) {
      return null;
    }
    if (this.publicRuntimeTextLooksInternal(body || title)) {
      return null;
    }
    const state = entry.level === "error" ? "error" : entry.level === "success" ? "done" : "running";
    if (state === "done" && kind === "terminal") {
      return null;
    }
    if (state === "error") {
      return {
        item_id: `live:${entry.id}`,
        kind: "blocked",
        text: body || title || "处理遇到阻塞",
        state: "error",
        trace_refs: [entry.id].filter(Boolean),
      };
    }
    const publicKind = this.publicTimelineKindFromProgressKind(kind);
    return {
      item_id: `live:${entry.id}`,
      kind: publicKind,
      title: title && !["正在思考", "Agent 判断", "观察结果"].includes(title) ? title : body,
      detail: title && title !== body ? body : "",
      state,
      stream_state: state === "running" ? "streaming" : "done",
      trace_refs: [entry.id].filter(Boolean),
    };
  }

  private publicTimelineKindFromProgressKind(kind: string) {
    if (kind === "model") return "assistant_text";
    if (kind === "tool" || kind === "observation") return "tool_activity";
    if (kind === "verification") return "verification";
    if (kind === "terminal") return "final_summary";
    return "status_update";
  }

  private publicRuntimeText(value: unknown) {
    const text = String(value ?? "").replace(/\s+/g, " ").trim();
    if (!text) {
      return "";
    }
    const lower = text.toLowerCase();
    if (["done", "completed", "running", "working", "ready_to_finish", "true", "false"].includes(lower)) {
      return "";
    }
    if (text === "回答已生成并写回会话" || text === "会话输出完成" || text === "工具调用已完成，正在根据结果继续。") {
      return "";
    }
    return text.length > 180 ? `${text.slice(0, 179)}...` : text;
  }

  private publicRuntimeTextLooksInternal(value: string) {
    return /(agent_turn_terminal|runtime_invocation_packet_compiled|task_execution_packet_compiled|step_summary_recorded)/.test(value)
      || /^(?:rtevt|taskrun|turnrun|task):/.test(value);
  }

  private runtimeProgressKindFromStep(step: string): "stage" | "tool" | "verification" | "model" | "observation" | "terminal" {
    const normalized = step.toLowerCase();
    if (normalized.includes("observation")) return "observation";
    if (normalized.includes("tool")) return "tool";
    if (normalized.includes("repair") || normalized.includes("verification") || normalized.includes("closeout")) return "verification";
    if (normalized.includes("model") || normalized.includes("agent")) return "model";
    if (normalized.includes("completed") || normalized.includes("terminal")) return "terminal";
    return "stage";
  }

  private runtimeEvidenceTypeFromStep(step: string) {
    const normalized = step.toLowerCase();
    if (normalized.includes("observation")) return "tool_observation";
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

  private mergePublicTimelineItems(existing: PublicChatTimelineItem[] | undefined, latest: PublicChatTimelineItem[] | undefined) {
    const items = [...(Array.isArray(existing) ? existing : [])];
    for (const item of Array.isArray(latest) ? latest : []) {
      const key = this.publicTimelineItemKey(item);
      if (!key) {
        continue;
      }
      const existingIndex = items.findIndex((candidate) => this.publicTimelineItemKey(candidate) === key);
      if (existingIndex >= 0) {
        items[existingIndex] = { ...items[existingIndex], ...item };
      } else {
        items.push(item);
      }
    }
    return items.slice(-MAX_LIVE_RUNTIME_PROGRESS_ENTRIES);
  }

  private publicTimelineItemKey(item: PublicChatTimelineItem | undefined) {
    const itemId = String(item?.item_id ?? "").trim();
    if (itemId) {
      return itemId;
    }
    const refs = Array.isArray(item?.trace_refs) ? item.trace_refs.filter(Boolean).join(",") : "";
    if (refs) {
      return `${item?.kind ?? "item"}:${refs}`;
    }
    return [
      item?.kind,
      item?.title,
      item?.detail,
      item?.text,
      item?.path,
    ].map((value) => String(value ?? "").trim()).join("|");
  }

  private mergeRuntimeAttachment(existing: SessionRuntimeAttachment | undefined, attachment: SessionRuntimeAttachment): SessionRuntimeAttachment {
    return {
      ...existing,
      ...attachment,
      progress_entries: this.mergeRuntimeProgressEntries(existing?.progress_entries, attachment.progress_entries?.[0] ?? null),
      public_timeline: this.mergePublicTimelineItems(existing?.public_timeline, attachment.public_timeline),
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
    if (step.startsWith("task_duplicate_tool_call_guarded")) {
      return null;
    }
    const status = String(payload.status ?? "").trim();
    const summary = String(payload.summary ?? "").trim();
    const publicNote = String(payload.public_progress_note ?? summary).trim();
    const agentBrief = String(payload.agent_brief_output ?? "").trim();
    const kind = this.runtimeProgressKindFromStep(step);
    if (kind === "observation" && this.runtimeIsInternalToolObservation(agentBrief)) {
      return null;
    }
    const observationBody = kind === "observation"
      ? this.runtimeToolObservationBody(agentBrief || publicNote || summary)
      : "";
    const actionState = payload.public_action_state && typeof payload.public_action_state === "object" && !Array.isArray(payload.public_action_state)
      ? payload.public_action_state as Record<string, unknown>
      : {};
    const meta = this.runtimeProgressMetaFromPayload(payload);
    const actionBody = kind === "model" && meta.length
      ? meta.map((item) => `${item.label}：${item.value}`).join("；")
      : "";
    const body = observationBody || publicNote || summary;
    const level = kind === "observation" && this.runtimeObservationLooksFailed(agentBrief || observationBody)
      ? "error"
      : this.runtimeProgressLevelFromStatus(status);
    if (!summary && !publicNote && !step) {
      return null;
    }
    return {
      id: String(runtimeEvent.event_id ?? "").trim() || `${runId}:event:${runtimeEvent.offset}`,
      title: kind === "observation" ? "观察结果" : kind === "model" ? "正在思考" : publicNote || summary || step || "正在处理",
      body: actionBody || body,
      publicNote: publicNote || actionBody || observationBody,
      agentBrief: observationBody || agentBrief,
      evidenceType: this.runtimeEvidenceTypeFromStep(step),
      eventType: runtimeEvent.event_type,
      kind,
      level,
      statusText: kind === "observation" && level === "error" ? "failed" : status || "running",
      runId,
      taskRunId: taskRunId || undefined,
      createdAt: Number(runtimeEvent.created_at ?? 0) || undefined,
      meta: meta.length ? meta : undefined,
    };
  }

  private runtimeProgressMetaFromPayload(payload: Record<string, unknown>) {
    const actionState = payload.public_action_state && typeof payload.public_action_state === "object" && !Array.isArray(payload.public_action_state)
      ? payload.public_action_state as Record<string, unknown>
      : {};
    const currentJudgment = String(payload.current_judgment ?? actionState.current_judgment ?? "").trim();
    const nextAction = this.runtimeValidatedNextAction(payload, actionState);
    return [
      { label: "模型说明", value: currentJudgment },
      { label: "计划动作", value: nextAction },
      { label: "状态", value: String(payload.completion_status ?? actionState.completion_status ?? "").trim() },
    ].filter((item) => item.value);
  }

  private runtimeValidatedNextAction(payload: Record<string, unknown>, actionState: Record<string, unknown>) {
    const candidate = String(payload.next_action ?? actionState.next_action ?? "").trim();
    if (!candidate) {
      return "";
    }
    const actionType = String(payload.action_type ?? actionState.action_type ?? "").trim().toLowerCase();
    if (!actionType) {
      return candidate;
    }
    if (actionType === "tool_call") {
      const toolName = String(payload.tool_name ?? actionState.tool_name ?? "").trim();
      const toolTarget = String(payload.tool_target ?? actionState.tool_target ?? "").trim();
      return this.runtimeTextContainsAny(candidate, [
        toolName,
        toolName.replace(/[_-]+/g, " "),
        toolTarget,
        this.runtimeTargetBasename(toolTarget),
        ...this.runtimeToolActionKeywords(toolName),
      ]) ? candidate : "";
    }
    const keywords: Record<string, string[]> = {
      respond: ["回复", "回答", "整理", "总结", "收口", "说明", "respond"],
      ask_user: ["询问", "提问", "确认", "补充", "请你", "需要你", "ask"],
      request_task_run: ["任务", "运行", "持续", "后台", "建立", "启动", "处理流程"],
      request_registered_engagement: ["任务", "运行", "持续", "后台", "建立", "启动", "处理流程"],
      block: ["阻塞", "受阻", "说明", "无法", "等待", "确认"],
    };
    return this.runtimeTextContainsAny(candidate, keywords[actionType] ?? []) ? candidate : "";
  }

  private runtimeTargetBasename(value: string) {
    const normalized = String(value ?? "").trim().replace(/\\/g, "/");
    return normalized ? normalized.split("/").pop() ?? "" : "";
  }

  private runtimeToolActionKeywords(toolName: string) {
    const normalized = String(toolName ?? "").trim().toLowerCase();
    if (["image_generate", "image_generation", "generate_image"].includes(normalized)) return ["图像", "图片", "生图", "美术", "资源", "生成", "image"];
    if (normalized === "path_exists") return ["路径", "存在", "检查", "确认", "artifact", "path"];
    if (["stat_path", "list_dir"].includes(normalized)) return ["路径", "目录", "检查", "读取", "列表", "path", "dir"];
    if (["read_file", "read_path"].includes(normalized)) return ["读取", "查看", "文件", "内容", "read"];
    if (["write_file", "edit_file", "apply_patch"].includes(normalized)) return ["写入", "创建", "修改", "编辑", "补丁", "文件", "write", "edit", "patch"];
    if (["search_text", "search_files", "glob_paths"].includes(normalized)) return ["搜索", "查找", "检索", "匹配", "search", "grep"];
    if (["terminal", "shell", "run_command", "powershell"].includes(normalized)) return ["命令", "终端", "运行", "执行", "shell", "powershell"];
    return normalized.split(/[_-]+/).filter(Boolean);
  }

  private runtimeTextContainsAny(value: string, fragments: string[]) {
    const haystack = this.runtimeMatchText(value);
    return fragments.some((fragment) => {
      const needle = this.runtimeMatchText(fragment);
      return needle.length >= 2 && haystack.includes(needle);
    });
  }

  private runtimeMatchText(value: string) {
    return String(value ?? "").trim().toLowerCase().replace(/[_-]+/g, " ");
  }

  private runtimeIsInternalToolObservation(value: string) {
    const text = String(value ?? "").trim();
    return text.startsWith("{") && text.includes("\"plan_id\"") && text.includes("\"items\"");
  }

  private runtimeToolObservationBody(value: string) {
    const text = String(value ?? "").trim();
    if (!text) return "";
    if (!this.looksLikeJson(text)) return text;
    try {
      const data = JSON.parse(text) as Record<string, unknown>;
      const structured = data.structured_error && typeof data.structured_error === "object" && !Array.isArray(data.structured_error)
        ? data.structured_error as Record<string, unknown>
        : {};
      const error = String(data.error ?? data.message ?? structured.message ?? structured.error ?? "").trim();
      if (data.ok === false || error) {
        return `工具返回失败：${error || "工具调用失败"}`;
      }
      const result = String(data.result ?? data.summary ?? data.output ?? "").trim();
      if (result) return result;
      const artifactRefs = Array.isArray(data.artifact_refs) ? data.artifact_refs : [];
      if (artifactRefs.length) return `工具返回成功，产生 ${artifactRefs.length} 个产物引用。`;
      return "工具返回成功，正在根据结果继续。";
    } catch {
      return "工具返回了结构化结果，正在根据结果继续。";
    }
  }

  private runtimeObservationLooksFailed(value: string) {
    const text = String(value ?? "").trim();
    if (!text) return false;
    if (text.includes("工具返回失败")) return true;
    if (!this.looksLikeJson(text)) return false;
    try {
      const data = JSON.parse(text) as Record<string, unknown>;
      return data.ok === false || Boolean(data.error || data.structured_error);
    } catch {
      return false;
    }
  }

  private looksLikeJson(value: string) {
    const text = String(value ?? "").trim();
    return (text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]"));
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
    if (runId.startsWith("turnrun:turn:")) {
      return runId.slice("turnrun:".length);
    }
    return "";
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
    const publicItem = this.publicTimelineItemFromRuntimeProgressEntry(latestProgressEntry);
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
      anchor_role: "assistant",
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
      public_timeline: publicItem ? [publicItem] : [],
      trace_available: true,
      debug_trace_ref: taskRunId || runId,
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
        const anchoredAttachment = {
          ...attachment,
          anchor_message_id: attachment.anchor_message_id || message.id,
        };
        return {
          ...message,
          runtimeAttachments: hasAttachment
            ? existing.map((item) => this.runtimeAttachmentRunId(item) === runId ? this.mergeRuntimeAttachment(item, anchoredAttachment) : item)
            : [...existing, anchoredAttachment],
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
    const activeTurnId = String(state.activeTurnSnapshot?.turn_id ?? "").trim();
    const activeTaskRunId = String(state.activeTurnSnapshot?.task_run_id ?? "").trim();
    const explicitTurnMatches = latestInteractionTurnId.startsWith("turn:")
      && (!activeTurnId || latestInteractionTurnId === activeTurnId);
    const activeTaskMatches = Boolean(activeTaskRunId && activeTaskRunId === taskRunId);
    if (!explicitTurnMatches && !activeTaskMatches) {
      return state;
    }
    const anchorTurnId = latestInteractionTurnId
      || activeTurnId;
    if (!anchorTurnId) {
      return state;
    }
    const latestProgressEntry = this.runtimeProgressEntryFromMonitor(monitor, taskRunId);
    const publicItem = this.publicTimelineItemFromRuntimeProgressEntry(latestProgressEntry);
    const attachment: SessionRuntimeAttachment = {
      attachment_id: `runtime-attachment:${taskRunId}`,
      run_id: taskRunId,
      anchor_turn_id: anchorTurnId,
      anchor_role: "assistant",
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
      public_timeline: publicItem ? [publicItem] : [],
      artifact_refs: Array.isArray(monitor.artifact_refs) ? monitor.artifact_refs : [],
      trace_available: true,
      debug_trace_ref: taskRunId,
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
        const anchoredAttachment = {
          ...attachment,
          anchor_message_id: attachment.anchor_message_id || message.id,
        };
        return {
          ...message,
          runtimeAttachments: hasAttachment
            ? existing.map((item) => this.runtimeAttachmentRunId(item) === taskRunId ? this.mergeRuntimeAttachment(item, anchoredAttachment) : item)
            : [...existing, anchoredAttachment],
        };
      }),
    };
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
          detail: normalizedStatus === "waiting_executor" ? "任务已进入等待队列。" : normalizedStatus === "waiting_approval" ? "需要确认后继续执行。" : "当前处理受阻。",
          event: "runtime_live_monitor",
          receipt: {
            level: "waiting",
            title: normalizedStatus === "waiting_executor" ? "等待继续" : normalizedStatus === "waiting_approval" ? "等待确认" : "运行受阻",
            body: normalizedStatus === "waiting_executor" ? "任务已进入等待队列。" : normalizedStatus === "waiting_approval" ? "需要确认后继续执行。" : "当前处理受阻。",
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
    const message = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
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

function isOpenAIReasoningModel(model: string) {
  const normalized = model.trim().toLowerCase();
  return normalized.startsWith("gpt-5")
    || normalized.startsWith("o1")
    || normalized.startsWith("o3")
    || normalized.startsWith("o4");
}

function normalizeChatThinkingMode(mode: ChatThinkingMode | string | null | undefined): ChatThinkingMode {
  return mode === "thinking" ? mode : "normal";
}

function chatThinkingModeFromProviderConfig(config: { thinking_mode?: string; reasoning_effort?: string } | null): ChatThinkingMode {
  if (String(config?.thinking_mode || "").trim().toLowerCase() !== "enabled") {
    return "normal";
  }
  return "thinking";
}

