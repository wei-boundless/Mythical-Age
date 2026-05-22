"use client";

import {
  continueOrchestrationCurrentStage,
  evaluateTaskGraphRunMonitor,
  loadFile,
  createSession,
  deleteSession,
  getCoordinationRunTaskGraphMonitor,
  getGlobalRuntimeMonitor,
  getRuntimeMonitorEventStreamUrl,
  getModelProviderConfig,
  getSoulImageAssetConfig,
  getWorkspaceContext,
  getTaskGraphRunMonitorDecisions,
  getTaskGraphRunMonitor,
  getOrchestrationRuntimeLoopTaskRunLiveMonitor,
  getOrchestrationRuntimeLoopSessionLiveMonitor,
  getRagMode,
  getSessionHistory,
  getSessionTokens,
  listSessions,
  listSkills,
  resumeOrchestrationTaskGraphRun,
  renameSession,
  resolveRuntimeLoopTaskRunApproval,
  saveFile,
  setRagMode,
  stopOrchestrationTaskRun,
  streamChat,
  switchSoulSystemSeed,
  taskGraphRunIdFromLiveMonitor,
  truncateSessionMessages
} from "@/lib/api";
import { buildMainAgentTaskSelection } from "@/lib/mainAgentAssemblyModes";
import type { GlobalRuntimeMonitor, RuntimeMonitorEventPayload } from "@/lib/api";
import {
  ACTIVE_SOUL_PATH,
  SOUL_SEED_PATHS,
  inferSoulKey,
  parseSoulSeed,
  type SoulKey,
  type SoulSummary
} from "@/lib/souls";

import type { Store } from "./core";
import { reduceStreamEvent, startStreamingTurn, type StreamSession } from "./events";
import { isTopLevelTaskGraphMonitorItem, topLevelTaskGraphMonitorItems } from "../runtimeMonitorLayering";
import type { ChatMode, ChatModelSelection, MainAgentAssemblyMode, SearchPolicySource, StoreActions, StoreState, TaskGraphMonitorBinding, TaskSelectionState, WorkspaceView } from "./types";
import { toUiMessages } from "./utils";

const TASK_GRAPH_MONITOR_BINDING_STORAGE_KEY = "task-graph-monitor-binding";

export class WorkspaceRuntime {
  private initializePromise: Promise<void> | null = null;
  private createSessionPromise: Promise<string> | null = null;
  private sessionDetailsRequest = 0;
  private orchestrationHydrateRequest = 0;
  private orchestrationMonitorRequest = 0;
  private orchestrationMonitorTimer: number | null = null;
  private orchestrationMonitorSessionId: string | null = null;
  private orchestrationMonitorInFlight = false;
  private taskGraphMonitorTimer: number | null = null;
  private taskGraphMonitorTaskRunId: string | null = null;
  private taskGraphMonitorInFlight = false;
  private globalRuntimeMonitorTimer: number | null = null;
  private globalRuntimeMonitorInFlight = false;
  private globalRuntimeMonitorPolling = false;
  private globalRuntimeMonitorRequest = 0;
  private globalRuntimeMonitorEventSource: EventSource | null = null;
  private globalRuntimeMonitorDetailRefreshTimer: number | null = null;
  private sessionRefreshTimers: number[] = [];
  private streamingSessionCache = new Map<string, Pick<StoreState, "messages" | "orchestrationSnapshot">>();
  private removedStreamingSessionIds = new Set<string>();
  private streamAbortControllers = new Map<string, AbortController>();
  private stoppedStreamingSessionIds = new Set<string>();

  readonly actions: StoreActions;

  constructor(private readonly store: Store<StoreState>) {
    this.actions = {
      setWorkspaceView: (view) => {
        this.setWorkspaceView(view);
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
      setDeepSeekThinkingEnabled: (enabled) => {
        this.setDeepSeekThinkingEnabled(enabled);
      },
      setMainAgentAssemblyMode: (mode) => {
        this.setMainAgentAssemblyMode(mode);
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
      highlightSystemGraph: (highlight) => {
        this.highlightSystemGraph(highlight);
      },
      setSystemGraphOverlay: (overlay) => {
        this.setSystemGraphOverlay(overlay);
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
      evaluateBoundTaskGraphMonitor: async () => {
        await this.evaluateBoundTaskGraphMonitor();
      },
      submitTaskGraphMonitorDecision: async (decision, controlAction, resumePayload) => {
        await this.submitTaskGraphMonitorDecision(decision, controlAction, resumePayload);
      },
      resumeTaskGraphRun: async (taskGraphRunId, payload) => {
        await this.resumeTaskGraphRun(taskGraphRunId, payload);
      },
      resolveRuntimeApproval: async (taskRunId, decision, message) => {
        await this.resolveRuntimeApproval(taskRunId, decision, message);
      },
      setTaskSelection: (selection) => {
        this.setTaskSelection(selection);
      },
      selectGlobalRuntimeMonitorTaskRun: (taskRunId) => {
        this.selectGlobalRuntimeMonitorTaskRun(taskRunId);
      },
      refreshGlobalRuntimeMonitor: async () => {
        await this.refreshGlobalRuntimeMonitor();
      }
    };
  }

  startGlobalRuntimeMonitor() {
    this.startGlobalRuntimeMonitorPolling();
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
    const [sessions, rag, skills, souls, modelProviderConfig, soulImageAssetConfig, workspaceContext] = await Promise.all([
      listSessions(),
      getRagMode(),
      listSkills(),
      this.loadSouls(),
      getModelProviderConfig().catch(() => null),
      getSoulImageAssetConfig().catch(() => null),
      getWorkspaceContext().catch(() => null)
    ]);

    this.store.setState((prev) => ({
      ...prev,
      sessions,
      ragMode: rag.enabled,
      searchPolicy: {
        ...prev.searchPolicy,
        rag: rag.enabled
      },
      modelProviderConfig,
      soulImageAssetConfig,
      workspaceContext,
      skills,
      soulOptions: souls.options,
      activeSoulKey: souls.activeSoulKey,
      selectedChatMode: this.resolveSelectedChatMode(prev.selectedChatModelId, modelProviderConfig),
      deepSeekThinkingEnabled: String(modelProviderConfig?.thinking_mode || "").trim().toLowerCase() === "enabled"
    }));

    const currentSessionId = this.store.getState().currentSessionId;
    if (!currentSessionId && sessions.length) {
      await this.selectSession(sessions[0].id);
    } else if (!currentSessionId) {
      await this.createFreshSession();
    }

    const file = await loadFile("durable_memory/index/MEMORY.md");
    this.store.setState((prev) => ({
      ...prev,
      inspectorPath: file.path,
      inspectorContent: file.content,
      inspectorDirty: false
    }));
    this.restoreTaskGraphMonitorBinding();
  }

  dispose() {
    if (typeof window === "undefined") {
      return;
    }
    for (const timer of this.sessionRefreshTimers) {
      window.clearTimeout(timer);
    }
    this.sessionRefreshTimers = [];
    this.stopOrchestrationMonitorPolling();
    this.stopTaskGraphMonitorPolling();
    this.stopGlobalRuntimeMonitorPolling();
    this.stopGlobalRuntimeMonitorEventStream();
  }

  private scheduleSessionRefreshes(delays: number[] = [1500, 4000]) {
    if (typeof window === "undefined") {
      return;
    }
    for (const timer of this.sessionRefreshTimers) {
      window.clearTimeout(timer);
    }
    this.sessionRefreshTimers = delays.map((delay) =>
      window.setTimeout(() => {
        void this.refreshSessions();
      }, delay)
    );
  }

  private async refreshSessions() {
    const sessions = await listSessions();
    this.store.setState((prev) => ({ ...prev, sessions }));
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
    const [history, tokens] = await Promise.all([
      getSessionHistory(sessionId),
      getSessionTokens(sessionId)
    ]);
    if (this.store.getState().currentSessionId !== sessionId || this.sessionDetailsRequest !== requestId) {
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      messages: toUiMessages(history.messages),
      tokenStats: tokens
    }));
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

  private applyVisibleStreamState(streamState: StoreState, activeStreamSessionIds: string[]) {
    this.store.setState((prev) => ({
      ...prev,
      messages: streamState.messages,
      orchestrationSnapshot: streamState.orchestrationSnapshot,
      taskGraphLiveMonitor: null,
      taskGraphRunMonitor: null,
      activeStreamSessionIds,
      isStreaming: activeStreamSessionIds.length > 0,
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
    const current = this.store.getState().currentSessionId;
    if (current) {
      return current;
    }
    return this.createFreshSession();
  }

  private async createNewSession() {
    const sessionId = await this.createFreshSession();
    this.store.setState((prev) => ({
      ...prev,
      currentSessionId: sessionId,
      messages: [],
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: null,
      taskGraphRunMonitor: null,
      tokenStats: null
    }));
    await this.refreshSessions();
  }

  private async selectSession(sessionId: string) {
    this.stopOrchestrationMonitorPolling();
    const streamingCache = this.streamingSessionCache.get(sessionId);
    if (this.store.getState().activeStreamSessionIds.includes(sessionId) && streamingCache) {
      this.store.setState((prev) => ({
        ...prev,
        currentSessionId: sessionId,
        messages: streamingCache.messages,
        orchestrationSnapshot: streamingCache.orchestrationSnapshot,
        taskGraphLiveMonitor: null,
        taskGraphRunMonitor: null,
        tokenStats: null
      }));
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      currentSessionId: sessionId,
      messages: [],
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: null,
      taskGraphRunMonitor: null,
      tokenStats: null
    }));
    await this.refreshSessionDetails(sessionId);
    await this.hydrateLatestOrchestrationSnapshot(sessionId);
  }

  private async sendMessage(value: string) {
    const trimmed = value.trim();
    const state = this.store.getState();
    if (!trimmed) {
      return;
    }

    const sessionId = await this.ensureSession();
    if (this.store.getState().activeStreamSessionIds.includes(sessionId)) {
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
    this.store.setState((prev) => ({
      ...prev,
      orchestrationSnapshot: null,
      taskGraphLiveMonitor: prev.taskGraphLiveMonitor,
      taskGraphRunMonitor: prev.taskGraphRunMonitor,
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
    transition = {
      ...transition,
      state: streamState
    };
    this.streamingSessionCache.set(sessionId, {
      messages: streamState.messages,
      orchestrationSnapshot: streamState.orchestrationSnapshot
    });
    this.addActiveStreamSession(sessionId);
    if (isImageGenerationTurn) {
      this.stopOrchestrationMonitorPolling();
      this.store.setState((prev) => ({
        ...prev,
        taskGraphLiveMonitor: null,
        taskGraphRunMonitor: null,
      }));
    } else {
      this.startOrchestrationMonitorPolling(sessionId);
    }
    if (this.store.getState().currentSessionId === sessionId) {
      this.applyVisibleStreamState(streamState, this.store.getState().activeStreamSessionIds);
    }

    try {
      await streamChat(
        {
          message: trimmed,
          session_id: sessionId,
          ephemeral_system_messages: ephemeralSystemMessages,
          search_policy: searchPolicy,
          task_selection: buildMainAgentTaskSelection(state.taskSelection, state.mainAgentAssemblyMode),
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
            transition = {
              ...transition,
              state: streamState
            };
            this.streamingSessionCache.set(sessionId, {
              messages: streamState.messages,
              orchestrationSnapshot: streamState.orchestrationSnapshot
            });
            if (isCurrentStreamSession) {
              this.applyVisibleStreamState(streamState, currentActiveStreamSessionIds);
            }
          }
        },
        { signal: abortController.signal }
      );
      consumedEphemeralSystemMessages = true;
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
      this.streamingSessionCache.set(sessionId, {
        messages: streamState.messages,
        orchestrationSnapshot: streamState.orchestrationSnapshot
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
        if (streamEndedWithError) {
          next.sessionActivity = streamState.sessionActivity;
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
      }
      await this.refreshSessions();
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

  private isAbortError(error: unknown) {
    return error instanceof DOMException && error.name === "AbortError";
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
      taskGraphRunMonitor: null,
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

  private setDeepSeekThinkingEnabled(enabled: boolean) {
    this.store.setState((prev) => ({ ...prev, deepSeekThinkingEnabled: enabled }));
  }

  private chatModelSelectionPayload(state: StoreState): ChatModelSelection | undefined {
    const resolved = this.resolveChatModelSelection(state);
    if (!resolved) {
      return undefined;
    }
    const { selectionId, provider, model, baseUrl, credentialRef } = resolved;
    const isDeepSeekTextModel = this.isDeepSeekChatModel(provider, model, state.selectedChatMode);
    if (selectionId === "system-default" && !isDeepSeekTextModel) {
      return undefined;
    }
    const payload: ChatModelSelection = {
      selection_id: selectionId,
      provider,
      model,
      base_url: baseUrl,
      credential_ref: credentialRef,
    };
    if (isDeepSeekTextModel) {
      payload.thinking_mode = state.deepSeekThinkingEnabled ? "enabled" : "disabled";
      payload.reasoning_effort = state.deepSeekThinkingEnabled ? "max" : "high";
    }
    return payload;
  }

  private resolveChatModelSelection(state: StoreState) {
    const config = state.modelProviderConfig;
    if (!config) {
      return null;
    }
    const selectionId = state.selectedChatModelId || "system-default";
    const catalog = config.provider_catalog;
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
    const option = catalog?.providers?.[provider];
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

  private isDeepSeekChatModel(provider: string, model: string, mode: ChatMode) {
    return mode !== "image"
      && provider.trim().toLowerCase() === "deepseek"
      && !model.trim().toLowerCase().includes("image");
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
    await this.refreshSessions();
  }

  private async removeSession(sessionId: string) {
    await deleteSession(sessionId);
    this.streamingSessionCache.delete(sessionId);
    this.removedStreamingSessionIds.add(sessionId);
    this.streamAbortControllers.get(sessionId)?.abort();
    this.streamAbortControllers.delete(sessionId);
    this.store.setState((prev) => {
      return this.removeActiveStreamSession(prev, sessionId);
    });
    await this.refreshSessions();
    if (this.store.getState().currentSessionId !== sessionId) {
      return;
    }
    const nextSessions = await listSessions();
    this.store.setState((prev) => ({
      ...prev,
      sessions: nextSessions
    }));
    if (nextSessions.length) {
      this.store.setState((prev) => ({
        ...prev,
        currentSessionId: nextSessions[0].id
      }));
      await this.refreshSessionDetails(nextSessions[0].id);
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      currentSessionId: null,
      messages: [],
      orchestrationSnapshot: null,
      tokenStats: null
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
  }

  private highlightSystemGraph(highlight: StoreState["systemGraphHighlight"]) {
    this.store.setState((prev) => ({ ...prev, systemGraphHighlight: highlight }));
  }

  private setSystemGraphOverlay(overlay: StoreState["systemGraphOverlay"]) {
    this.store.setState((prev) => ({ ...prev, systemGraphOverlay: overlay }));
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

  private normalizeTaskGraphMonitorBinding(
    binding: Omit<TaskGraphMonitorBinding, "bound_at"> & { bound_at?: number }
  ): TaskGraphMonitorBinding | null {
    const taskRunId = String(binding.task_run_id ?? "").trim();
    if (!taskRunId) {
      return null;
    }
    return {
      task_run_id: taskRunId,
      coordination_run_id: String(binding.coordination_run_id ?? "").trim() || undefined,
      graph_id: String(binding.graph_id ?? "").trim() || undefined,
      session_id: String(binding.session_id ?? "").trim() || undefined,
      project_id: String(binding.project_id ?? "").trim() || undefined,
      title: String(binding.title ?? "").trim() || undefined,
      bound_at: Number(binding.bound_at ?? Date.now() / 1000),
    };
  }

  private bindTaskGraphMonitorRun(binding: Omit<TaskGraphMonitorBinding, "bound_at"> & { bound_at?: number }) {
    const normalized = this.normalizeTaskGraphMonitorBinding(binding);
    if (!normalized) {
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      taskGraphMonitorBinding: normalized,
      taskGraphMonitorError: "",
      taskGraphRunInteractionOpen: prev.taskGraphRunInteractionOpen || Boolean(prev.taskGraphMonitorDecision?.action && prev.taskGraphMonitorDecision.action !== "no_action"),
    }));
    this.persistTaskGraphMonitorBinding(normalized);
    this.startTaskGraphMonitorPolling(normalized.task_run_id);
  }

  private clearTaskGraphMonitorRun() {
    this.stopTaskGraphMonitorPolling();
    this.persistTaskGraphMonitorBinding(null);
    this.store.setState((prev) => ({
      ...prev,
      taskGraphMonitorBinding: null,
      taskGraphBoundRunMonitor: null,
      taskGraphMonitorDecision: null,
      taskGraphMonitorDecisions: [],
      taskGraphMonitorError: "",
      taskGraphRunInteractionOpen: false,
    }));
  }

  private setTaskGraphRunInteractionOpen(open: boolean) {
    this.store.setState((prev) => ({ ...prev, taskGraphRunInteractionOpen: open }));
    const binding = this.store.getState().taskGraphMonitorBinding;
    if (open && binding?.task_run_id) {
      this.startTaskGraphMonitorPolling(binding.task_run_id);
      return;
    }
    if (!open && !binding?.task_run_id) {
      this.stopTaskGraphMonitorPolling();
    }
  }

  private restoreTaskGraphMonitorBinding() {
    if (typeof window === "undefined") {
      return;
    }
    try {
      const raw = window.localStorage.getItem(TASK_GRAPH_MONITOR_BINDING_STORAGE_KEY);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw) as Partial<TaskGraphMonitorBinding>;
      const normalized = this.normalizeTaskGraphMonitorBinding({
        task_run_id: String(parsed.task_run_id ?? ""),
        coordination_run_id: parsed.coordination_run_id,
        graph_id: parsed.graph_id,
        session_id: parsed.session_id,
        project_id: parsed.project_id,
        title: parsed.title,
        bound_at: parsed.bound_at,
      });
      if (!normalized) {
        return;
      }
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorBinding: normalized,
      }));
      this.startTaskGraphMonitorPolling(normalized.task_run_id);
    } catch {
      // Binding persistence is convenience state only.
    }
  }

  private persistTaskGraphMonitorBinding(binding: TaskGraphMonitorBinding | null) {
    if (typeof window === "undefined") {
      return;
    }
    try {
      if (!binding) {
        window.localStorage.removeItem(TASK_GRAPH_MONITOR_BINDING_STORAGE_KEY);
        return;
      }
      window.localStorage.setItem(TASK_GRAPH_MONITOR_BINDING_STORAGE_KEY, JSON.stringify(binding));
    } catch {
      // Losing local persistence must not break runtime monitoring in memory.
    }
  }

  private stopTaskGraphMonitorPolling() {
    if (typeof window === "undefined") {
      return;
    }
    if (this.taskGraphMonitorTimer !== null) {
      window.clearTimeout(this.taskGraphMonitorTimer);
      this.taskGraphMonitorTimer = null;
    }
    this.taskGraphMonitorTaskRunId = null;
    this.taskGraphMonitorInFlight = false;
  }

  private startTaskGraphMonitorPolling(taskRunId: string) {
    const targetTaskRunId = taskRunId.trim();
    if (typeof window === "undefined" || !targetTaskRunId) {
      return;
    }
    if (this.taskGraphMonitorTimer !== null) {
      window.clearTimeout(this.taskGraphMonitorTimer);
      this.taskGraphMonitorTimer = null;
    }
    this.taskGraphMonitorTaskRunId = targetTaskRunId;
    void this.pollTaskGraphMonitor(targetTaskRunId);
  }

  private scheduleNextTaskGraphMonitorPoll(taskRunId: string, delayMs = 1000) {
    if (typeof window === "undefined") {
      return;
    }
    if (this.taskGraphMonitorTimer !== null) {
      window.clearTimeout(this.taskGraphMonitorTimer);
    }
    this.taskGraphMonitorTimer = window.setTimeout(() => {
      void this.pollTaskGraphMonitor(taskRunId);
    }, delayMs);
  }

  private async pollTaskGraphMonitor(taskRunId: string) {
    const targetTaskRunId = taskRunId.trim();
    if (!targetTaskRunId || this.taskGraphMonitorTaskRunId !== targetTaskRunId) {
      return;
    }
    if (this.taskGraphMonitorInFlight) {
      this.scheduleNextTaskGraphMonitorPoll(targetTaskRunId, 900);
      return;
    }
    this.taskGraphMonitorInFlight = true;
    try {
      const monitor = await getTaskGraphRunMonitor(targetTaskRunId);
      if (this.taskGraphMonitorTaskRunId === targetTaskRunId) {
        this.store.setState((prev) => ({
          ...prev,
          taskGraphBoundRunMonitor: monitor,
          taskGraphMonitorError: "",
        }));
      }
    } catch (error) {
      if (this.taskGraphMonitorTaskRunId === targetTaskRunId) {
        this.store.setState((prev) => ({
          ...prev,
          taskGraphMonitorError: error instanceof Error ? error.message : "TaskGraph 运行监控读取失败",
        }));
      }
    } finally {
      this.taskGraphMonitorInFlight = false;
      if (this.taskGraphMonitorTaskRunId === targetTaskRunId) {
        this.scheduleNextTaskGraphMonitorPoll(targetTaskRunId);
      }
    }
  }

  private async evaluateBoundTaskGraphMonitor() {
    const binding = this.store.getState().taskGraphMonitorBinding;
    const taskRunId = binding?.task_run_id?.trim() ?? "";
    if (!taskRunId) {
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorError: "当前没有绑定可监测的 TaskRun。" }));
      return;
    }
    this.store.setState((prev) => ({ ...prev, taskGraphMonitorLoading: true, taskGraphMonitorError: "" }));
    try {
      const result = await evaluateTaskGraphRunMonitor(taskRunId, { monitor_node_id: "runtime_monitor" });
      const decisions = await getTaskGraphRunMonitorDecisions(taskRunId);
      const shouldOpen = Boolean(result.decision?.action && result.decision.action !== "no_action");
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorDecision: result.decision,
        taskGraphMonitorDecisions: decisions.decisions ?? [],
        taskGraphBoundRunMonitor: result.monitor_snapshot ?? prev.taskGraphBoundRunMonitor,
        taskGraphRunInteractionOpen: shouldOpen ? true : prev.taskGraphRunInteractionOpen,
      }));
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: error instanceof Error ? error.message : "监测评估失败",
      }));
    } finally {
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorLoading: false }));
    }
  }

  private async submitTaskGraphMonitorDecision(
    decision: string,
    controlAction: string,
    resumePayload?: Record<string, unknown>,
  ) {
    const state = this.store.getState();
    const binding = state.taskGraphMonitorBinding;
    const monitorDecision = state.taskGraphMonitorDecision;
    const coordinationRunId = String(
      monitorDecision?.coordination_run_id
      || binding?.coordination_run_id
      || state.taskGraphBoundRunMonitor?.coordination_run_id
      || ""
    ).trim();
    const taskRunId = String(binding?.task_run_id || monitorDecision?.task_run_id || "").trim();
    if (!coordinationRunId) {
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorError: "当前没有可处理运行交互的 CoordinationRun。" }));
      return;
    }
    this.store.setState((prev) => ({ ...prev, taskGraphMonitorActionLoading: true, taskGraphMonitorError: "" }));
    try {
      if (controlAction === "continue_current_stage" || decision === "continue_current_stage" || decision === "retry_current_stage") {
        await continueOrchestrationCurrentStage(coordinationRunId, {
          source: "task_graph_monitor_global_dock",
          current_turn_context: {
            decision,
            monitor_decision_id: monitorDecision?.decision_id,
            ...(resumePayload ?? {}),
          },
        });
      } else if (controlAction === "stop_task_run" || decision === "pause") {
        await stopOrchestrationTaskRun(taskRunId, {
          reason: String(resumePayload?.reason || "monitor_pause_requested"),
          message: "TaskGraph 运行交互浮窗暂停运行",
          coordination_run_id: coordinationRunId,
        });
      } else if (controlAction === "acknowledge" || decision === "acknowledge") {
        this.store.setState((prev) => ({ ...prev, taskGraphRunInteractionOpen: false }));
      } else {
        await resumeOrchestrationTaskGraphRun(coordinationRunId, {
          decision,
          source: "task_graph_monitor_global_dock",
          monitor_decision_id: monitorDecision?.decision_id,
          ...(resumePayload ?? {}),
        });
      }
      if (taskRunId) {
        const monitor = await getTaskGraphRunMonitor(taskRunId);
        this.store.setState((prev) => ({
          ...prev,
          taskGraphBoundRunMonitor: monitor,
          taskGraphRunInteractionOpen: false,
        }));
      }
    } catch (error) {
      this.store.setState((prev) => ({
        ...prev,
        taskGraphMonitorError: error instanceof Error ? error.message : "运行交互处理失败",
      }));
    } finally {
      this.store.setState((prev) => ({ ...prev, taskGraphMonitorActionLoading: false }));
    }
  }

  private stopOrchestrationMonitorPolling() {
    if (typeof window === "undefined") {
      return;
    }
    if (this.orchestrationMonitorTimer !== null) {
      window.clearTimeout(this.orchestrationMonitorTimer);
      this.orchestrationMonitorTimer = null;
    }
    this.orchestrationMonitorSessionId = null;
    this.orchestrationMonitorInFlight = false;
  }

  private startOrchestrationMonitorPolling(sessionId: string) {
    const targetSessionId = sessionId.trim();
    if (typeof window === "undefined" || !targetSessionId) {
      return;
    }
    if (this.orchestrationMonitorTimer !== null) {
      window.clearTimeout(this.orchestrationMonitorTimer);
      this.orchestrationMonitorTimer = null;
    }
    this.orchestrationMonitorSessionId = targetSessionId;
    void this.pollOrchestrationMonitor(targetSessionId);
  }

  private scheduleNextOrchestrationMonitorPoll(sessionId: string, delayMs = 1500) {
    if (typeof window === "undefined") {
      return;
    }
    if (this.orchestrationMonitorTimer !== null) {
      window.clearTimeout(this.orchestrationMonitorTimer);
    }
    this.orchestrationMonitorTimer = window.setTimeout(() => {
      void this.pollOrchestrationMonitor(sessionId);
    }, delayMs);
  }

  private async pollOrchestrationMonitor(sessionId: string) {
    const targetSessionId = sessionId.trim();
    if (!targetSessionId || this.orchestrationMonitorSessionId !== targetSessionId) {
      return;
    }
    if (this.orchestrationMonitorInFlight) {
      this.scheduleNextOrchestrationMonitorPoll(targetSessionId, 800);
      return;
    }
    this.orchestrationMonitorInFlight = true;
    try {
      const shouldContinue = await this.hydrateLatestOrchestrationSnapshot(targetSessionId);
      if (!shouldContinue && !this.store.getState().activeStreamSessionIds.includes(targetSessionId)) {
        this.stopOrchestrationMonitorPolling();
        return;
      }
    } finally {
      this.orchestrationMonitorInFlight = false;
      if (this.orchestrationMonitorSessionId === targetSessionId) {
        if (this.store.getState().activeStreamSessionIds.includes(targetSessionId)) {
          this.scheduleNextOrchestrationMonitorPoll(targetSessionId);
        } else {
          this.stopOrchestrationMonitorPolling();
        }
      }
    }
  }

  private async resumeTaskGraphRun(taskGraphRunId: string, payload?: Record<string, unknown>) {
    const runId = taskGraphRunId.trim();
    if (!runId) {
      return;
    }
    await resumeOrchestrationTaskGraphRun(runId, payload ?? {});
    const sessionId = this.store.getState().currentSessionId;
    if (sessionId) {
      await this.hydrateLatestOrchestrationSnapshot(sessionId);
      this.startOrchestrationMonitorPolling(sessionId);
    }
  }

  private async resolveRuntimeApproval(taskRunId: string, decision: "approve" | "reject", message?: string) {
    const runId = taskRunId.trim();
    if (!runId) {
      return;
    }
    await resolveRuntimeLoopTaskRunApproval(runId, { decision, message });
    const sessionId = this.store.getState().currentSessionId;
    if (sessionId) {
      await this.hydrateLatestOrchestrationSnapshot(sessionId);
      this.startOrchestrationMonitorPolling(sessionId);
    }
  }

  private async hydrateLatestOrchestrationSnapshot(sessionId: string): Promise<boolean> {
    const targetSessionId = sessionId.trim();
    const requestId = ++this.orchestrationHydrateRequest;
    if (!targetSessionId) {
      this.store.setState((prev) => ({ ...prev, taskGraphLiveMonitor: null, taskGraphRunMonitor: null }));
      return false;
    }
    try {
      const liveMonitor = await getOrchestrationRuntimeLoopSessionLiveMonitor(targetSessionId);
      if (!liveMonitor.monitor) {
        if (this.store.getState().currentSessionId === targetSessionId && this.orchestrationHydrateRequest === requestId) {
          this.store.setState((prev) => ({ ...prev, taskGraphLiveMonitor: null, taskGraphRunMonitor: null }));
        }
        return false;
      }
      const liveStatus = String(liveMonitor.monitor.status ?? liveMonitor.monitor.task_run?.status ?? "").trim();
      const hasActiveGraphRun = Boolean(liveMonitor.monitor.has_coordination) && ["created", "running", "waiting_approval", "blocked"].includes(liveStatus);
      const hasPendingApproval = liveStatus === "waiting_approval" || String((liveMonitor.monitor.loop_state as Record<string, unknown> | undefined)?.terminal_reason ?? "") === "waiting_approval";
      const taskRunId = String(liveMonitor.monitor.task_run?.task_run_id ?? "").trim();
      const coordinationRunId = String(
        liveMonitor.latest_coordination_run_id
        ?? taskGraphRunIdFromLiveMonitor(liveMonitor.monitor)
        ?? ""
      ).trim();
      if (liveMonitor.monitor.has_coordination || coordinationRunId) {
        this.updateSessionActivityFromLiveMonitor(liveStatus, taskRunId, coordinationRunId);
      }
      let taskGraphRunMonitor = this.store.getState().taskGraphRunMonitor;
      if (coordinationRunId) {
        taskGraphRunMonitor = await getCoordinationRunTaskGraphMonitor(coordinationRunId);
      } else if (taskRunId) {
        taskGraphRunMonitor = await getTaskGraphRunMonitor(taskRunId);
      }
      if (this.store.getState().currentSessionId === targetSessionId && this.orchestrationHydrateRequest === requestId) {
        this.store.setState((prev) => ({
          ...prev,
          taskGraphLiveMonitor: liveMonitor.monitor,
          taskGraphRunMonitor,
        }));
      }
      return hasActiveGraphRun || hasPendingApproval;
    } catch {
      // Keep current snapshot on transient runtime-loop query failures.
      return false;
    }
  }

  private setTaskSelection(selection: TaskSelectionState | null) {
    this.store.setState((prev) => ({ ...prev, taskSelection: selection }));
  }

  private setMainAgentAssemblyMode(mode: MainAgentAssemblyMode) {
    this.store.setState((prev) => ({ ...prev, mainAgentAssemblyMode: mode }));
  }

  private startGlobalRuntimeMonitorPolling() {
    if (typeof window === "undefined") {
      return;
    }
    this.globalRuntimeMonitorPolling = true;
    this.startGlobalRuntimeMonitorEventStream();
    if (this.globalRuntimeMonitorInFlight) {
      return;
    }
    if (this.globalRuntimeMonitorTimer !== null) {
      window.clearTimeout(this.globalRuntimeMonitorTimer);
      this.globalRuntimeMonitorTimer = null;
    }
    void this.refreshGlobalRuntimeMonitor();
  }

  private stopGlobalRuntimeMonitorPolling() {
    if (typeof window === "undefined") {
      return;
    }
    this.globalRuntimeMonitorPolling = false;
    this.stopGlobalRuntimeMonitorEventStream();
    if (this.globalRuntimeMonitorTimer !== null) {
      window.clearTimeout(this.globalRuntimeMonitorTimer);
      this.globalRuntimeMonitorTimer = null;
    }
    this.globalRuntimeMonitorInFlight = false;
  }

  private startGlobalRuntimeMonitorEventStream() {
    if (typeof window === "undefined") {
      return;
    }
    if (this.globalRuntimeMonitorEventSource) {
      return;
    }
    this.store.setState((prev) => ({
      ...prev,
      globalRuntimeMonitorStreamStatus: "connecting",
    }));
    const eventSource = new EventSource(getRuntimeMonitorEventStreamUrl(40));
    this.globalRuntimeMonitorEventSource = eventSource;
    eventSource.onopen = () => {
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorError: "",
        globalRuntimeMonitorStreamStatus: "connected",
      }));
    };
    eventSource.onerror = () => {
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorStreamStatus: "fallback",
      }));
      this.scheduleGlobalRuntimeMonitorPoll(1200);
    };
    eventSource.addEventListener("runtime_monitor_snapshot", (event) => {
      this.applyGlobalRuntimeMonitorStreamPayload(this.parseRuntimeMonitorEventPayload(event));
    });
    eventSource.addEventListener("runtime_monitor_event", (event) => {
      this.applyGlobalRuntimeMonitorStreamPayload(this.parseRuntimeMonitorEventPayload(event));
    });
  }

  private stopGlobalRuntimeMonitorEventStream() {
    if (this.globalRuntimeMonitorEventSource) {
      this.globalRuntimeMonitorEventSource.close();
      this.globalRuntimeMonitorEventSource = null;
    }
    if (this.globalRuntimeMonitorDetailRefreshTimer !== null && typeof window !== "undefined") {
      window.clearTimeout(this.globalRuntimeMonitorDetailRefreshTimer);
      this.globalRuntimeMonitorDetailRefreshTimer = null;
    }
    this.store.setState((prev) => ({
      ...prev,
      globalRuntimeMonitorStreamStatus: "closed",
    }));
  }

  private parseRuntimeMonitorEventPayload(event: Event): RuntimeMonitorEventPayload | null {
    const message = event as MessageEvent<string>;
    try {
      return JSON.parse(message.data) as RuntimeMonitorEventPayload;
    } catch {
      return null;
    }
  }

  private applyGlobalRuntimeMonitorStreamPayload(payload: RuntimeMonitorEventPayload | null) {
    if (!payload) {
      return;
    }
    if (payload.monitor) {
      this.applyGlobalRuntimeMonitorSnapshot(payload.monitor, {
        detailTaskRunId: payload.runtime_event?.task_run_id,
        lastEvent: payload.runtime_event ?? null,
      });
    } else if (payload.runtime_event) {
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorLastEvent: payload.runtime_event ?? null,
      }));
      this.queueSelectedGlobalRuntimeMonitorDetailRefresh(payload.runtime_event.task_run_id);
    }
  }

  private applyGlobalRuntimeMonitorSnapshot(
    monitor: GlobalRuntimeMonitor,
    options: {
      detailTaskRunId?: string;
      lastEvent?: RuntimeMonitorEventPayload["runtime_event"] | null;
    } = {},
  ) {
    const currentSelected = this.store.getState().globalRuntimeMonitorSelectedTaskRunId;
    const visibleTaskGraphs = topLevelTaskGraphMonitorItems(monitor);
    const currentStillVisible = visibleTaskGraphs.some((item) => item.task_run_id === currentSelected);
    const nextSelected = currentStillVisible ? currentSelected : visibleTaskGraphs[0]?.task_run_id || "";
    const detailTaskRunId = visibleTaskGraphs.some((item) => item.task_run_id === options.detailTaskRunId)
      ? options.detailTaskRunId
      : nextSelected;
    this.store.setState((prev) => ({
      ...prev,
      globalRuntimeMonitor: monitor,
      globalRuntimeMonitorSelectedTaskRunId: nextSelected,
      globalRuntimeMonitorSelectedLiveMonitor: nextSelected ? prev.globalRuntimeMonitorSelectedLiveMonitor : null,
      globalRuntimeMonitorSelectedGraphMonitor: nextSelected ? prev.globalRuntimeMonitorSelectedGraphMonitor : null,
      globalRuntimeMonitorError: "",
      globalRuntimeMonitorLastEvent: options.lastEvent ?? prev.globalRuntimeMonitorLastEvent,
    }));
    this.queueSelectedGlobalRuntimeMonitorDetailRefresh(detailTaskRunId);
  }

  private queueSelectedGlobalRuntimeMonitorDetailRefresh(taskRunId?: string) {
    if (typeof window === "undefined") {
      return;
    }
    const normalized = String(taskRunId || "").trim();
    const selected = this.store.getState().globalRuntimeMonitorSelectedTaskRunId;
    if (!normalized || normalized !== selected) {
      return;
    }
    if (this.globalRuntimeMonitorDetailRefreshTimer !== null) {
      window.clearTimeout(this.globalRuntimeMonitorDetailRefreshTimer);
    }
    this.globalRuntimeMonitorDetailRefreshTimer = window.setTimeout(() => {
      this.globalRuntimeMonitorDetailRefreshTimer = null;
      void this.loadGlobalRuntimeMonitorTaskRunDetail(normalized);
    }, 180);
  }

  private scheduleGlobalRuntimeMonitorPoll(delayMs = 2500) {
    if (typeof window === "undefined") {
      return;
    }
    if (!this.globalRuntimeMonitorPolling) {
      return;
    }
    const streamStatus = this.store.getState().globalRuntimeMonitorStreamStatus;
    const effectiveDelay = streamStatus === "connected" ? Math.max(delayMs, 30000) : delayMs;
    if (this.globalRuntimeMonitorTimer !== null) {
      window.clearTimeout(this.globalRuntimeMonitorTimer);
    }
    this.globalRuntimeMonitorTimer = window.setTimeout(() => {
      void this.refreshGlobalRuntimeMonitor();
    }, effectiveDelay);
  }

  private async refreshGlobalRuntimeMonitor() {
    if (this.globalRuntimeMonitorInFlight) {
      this.scheduleGlobalRuntimeMonitorPoll(1200);
      return;
    }
    this.globalRuntimeMonitorInFlight = true;
    const requestId = ++this.globalRuntimeMonitorRequest;
    this.store.setState((prev) => ({ ...prev, globalRuntimeMonitorLoading: true }));
    try {
      const monitor = await getGlobalRuntimeMonitor(40);
      if (!this.globalRuntimeMonitorPolling || requestId !== this.globalRuntimeMonitorRequest) {
        return;
      }
      this.applyGlobalRuntimeMonitorSnapshot(monitor);
    } catch (error) {
      if (!this.globalRuntimeMonitorPolling || requestId !== this.globalRuntimeMonitorRequest) {
        return;
      }
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorError: error instanceof Error ? error.message : "全局运行监控读取失败",
      }));
    } finally {
      if (requestId === this.globalRuntimeMonitorRequest) {
        this.globalRuntimeMonitorInFlight = false;
        this.store.setState((prev) => ({ ...prev, globalRuntimeMonitorLoading: false }));
        this.scheduleGlobalRuntimeMonitorPoll();
      }
    }
  }

  private selectGlobalRuntimeMonitorTaskRun(taskRunId: string) {
    const normalized = taskRunId.trim();
    const visibleTaskGraphs = topLevelTaskGraphMonitorItems(this.store.getState().globalRuntimeMonitor);
    const selectable = visibleTaskGraphs.some((item) => item.task_run_id === normalized);
    this.store.setState((prev) => ({
      ...prev,
      globalRuntimeMonitorSelectedTaskRunId: selectable ? normalized : "",
      globalRuntimeMonitorSelectedLiveMonitor: null,
      globalRuntimeMonitorSelectedGraphMonitor: null,
    }));
    if (normalized && selectable) {
      void this.loadGlobalRuntimeMonitorTaskRunDetail(normalized);
    }
  }

  private async loadGlobalRuntimeMonitorTaskRunDetail(taskRunId: string) {
    const normalized = taskRunId.trim();
    if (!normalized) {
      return;
    }
    const selected = topLevelTaskGraphMonitorItems(this.store.getState().globalRuntimeMonitor)
      .find((item) => item.task_run_id === normalized);
    if (!selected || !isTopLevelTaskGraphMonitorItem(selected)) {
      return;
    }
    try {
      const [liveMonitor, graphMonitor] = await Promise.all([
        getOrchestrationRuntimeLoopTaskRunLiveMonitor(normalized).catch(() => null),
        getTaskGraphRunMonitor(normalized).catch(() => null),
      ]);
      if (this.store.getState().globalRuntimeMonitorSelectedTaskRunId !== normalized) {
        return;
      }
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorSelectedLiveMonitor: liveMonitor,
        globalRuntimeMonitorSelectedGraphMonitor: graphMonitor,
        globalRuntimeMonitorError: "",
      }));
    } catch (error) {
      if (this.store.getState().globalRuntimeMonitorSelectedTaskRunId !== normalized) {
        return;
      }
      this.store.setState((prev) => ({
        ...prev,
        globalRuntimeMonitorError: error instanceof Error ? error.message : "任务详情监控读取失败",
      }));
    }
  }

  private updateSessionActivityFromLiveMonitor(liveStatus: string, taskRunId: string, coordinationRunId: string) {
    const normalizedStatus = liveStatus.trim();
    if (!normalizedStatus) {
      return;
    }
    if (normalizedStatus === "waiting_approval" || normalizedStatus === "blocked") {
      this.store.setState((prev) => ({
        ...prev,
        sessionActivity: {
          level: "waiting",
          title: normalizedStatus === "waiting_approval" ? "等待审批" : "运行受阻",
          detail: normalizedStatus === "waiting_approval" ? "需要确认后继续执行" : "任务图运行需要处理",
          event: "runtime_live_monitor",
          receipt: {
            level: "waiting",
            title: normalizedStatus === "waiting_approval" ? "等待审批" : "运行受阻",
            body: normalizedStatus === "waiting_approval" ? "需要确认后继续执行。" : "任务图运行需要处理。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              coordinationRunId: coordinationRunId || "",
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
          title: "任务运行中",
          detail: "正在同步任务图运行状态",
          event: "runtime_live_monitor",
          receipt: {
            level: "running",
            title: "任务运行中",
            body: "正在同步任务图运行状态。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              coordinationRunId: coordinationRunId || "",
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
          title: "任务已完成",
          detail: "结果已写回会话，运行记录可在监控中查看",
          event: "runtime_live_monitor",
          receipt: {
            level: "success",
            title: "任务已完成",
            body: "结果已写回会话，运行记录可在监控中查看。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              coordinationRunId: coordinationRunId || "",
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
          title: "任务失败",
          detail: "任务图运行返回失败状态，请查看运行监控",
          event: "runtime_live_monitor",
          receipt: {
            level: "error",
            title: "任务失败",
            body: "任务图运行返回失败状态，请查看运行监控。",
            debug: {
              event: "runtime_live_monitor",
              taskRunId: taskRunId || "",
              coordinationRunId: coordinationRunId || "",
            },
          },
          updatedAt: Date.now(),
        },
      }));
    }
  }
}
