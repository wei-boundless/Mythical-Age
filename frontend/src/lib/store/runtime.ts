"use client";

import {
  loadFile,
  createSession,
  deleteSession,
  getRagMode,
  getSessionHistory,
  getSessionTokens,
  listSessions,
  listSkills,
  renameSession,
  saveFile,
  setRagMode,
  streamChat,
  switchSoulSystemSeed
} from "@/lib/api";
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
import type { SearchPolicySource, StoreActions, StoreState, WorkspaceView } from "./types";
import { toUiMessages } from "./utils";

export class WorkspaceRuntime {
  private createSessionPromise: Promise<string> | null = null;
  private sessionDetailsRequest = 0;
  private sessionRefreshTimers: number[] = [];

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
      toggleRagMode: async () => {
        await this.toggleRagMode();
      },
      toggleSearchPolicySource: (source) => {
        this.toggleSearchPolicySource(source);
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
      }
    };
  }

  async initialize() {
    const [sessions, rag, skills, souls] = await Promise.all([
      listSessions(),
      getRagMode(),
      listSkills(),
      this.loadSouls()
    ]);

    this.store.setState((prev) => ({
      ...prev,
      sessions,
      ragMode: rag.enabled,
      searchPolicy: {
        ...prev.searchPolicy,
        rag: rag.enabled
      },
      skills,
      soulOptions: souls.options,
      activeSoulKey: souls.activeSoulKey
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
  }

  dispose() {
    if (typeof window === "undefined") {
      return;
    }
    for (const timer of this.sessionRefreshTimers) {
      window.clearTimeout(timer);
    }
    this.sessionRefreshTimers = [];
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
      tokenStats: null
    }));
    await this.refreshSessions();
  }

  private async selectSession(sessionId: string) {
    this.store.setState((prev) => ({ ...prev, currentSessionId: sessionId }));
    await this.refreshSessionDetails(sessionId);
  }

  private async sendMessage(value: string) {
    const trimmed = value.trim();
    const state = this.store.getState();
    if (!trimmed || state.isStreaming) {
      return;
    }

    const sessionId = await this.ensureSession();
    const ephemeralSystemMessages = [...(state.pendingEphemeralSystemMessages ?? [])];
    const searchPolicy = this.enabledSearchPolicy(state);
    let consumedEphemeralSystemMessages = false;
    let transition = startStreamingTurn(this.store.getState(), trimmed);
    this.store.setState(() => transition.state);

    try {
      await streamChat(
        {
          message: trimmed,
          session_id: sessionId,
          ephemeral_system_messages: ephemeralSystemMessages,
          search_policy: searchPolicy
        },
        {
          onEvent: (event, data) => {
            transition = reduceStreamEvent(this.store.getState(), transition.session, event, data);
            this.store.setState(() => transition.state);
          }
        }
      );
      consumedEphemeralSystemMessages = true;
    } catch (error) {
      transition = reduceStreamEvent(
        this.store.getState(),
        transition.session,
        "error",
        { error: error instanceof Error ? error.message : "unknown error" }
      );
      this.store.setState(() => transition.state);
    } finally {
      this.store.setState((prev) => {
        const next = { ...prev, isStreaming: false };
        if (
          consumedEphemeralSystemMessages
          && ephemeralSystemMessages.length > 0
          && prev.pendingEphemeralSystemMessages.join("\n") === ephemeralSystemMessages.join("\n")
        ) {
          next.pendingEphemeralSystemMessages = [];
        }
        if (
          !consumedEphemeralSystemMessages
          && ephemeralSystemMessages.length > 0
          && !prev.pendingEphemeralSystemMessages.length
        ) {
          next.pendingEphemeralSystemMessages = ephemeralSystemMessages;
        }
        return next;
      });
      if (this.store.getState().currentSessionId === sessionId) {
        await this.refreshSessionDetails(sessionId);
      }
      await this.refreshSessions();
      this.scheduleSessionRefreshes();
    }
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
}
