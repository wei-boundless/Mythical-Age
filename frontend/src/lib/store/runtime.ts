"use client";

import {
  compressSession,
  createSession,
  deleteSession,
  getRagMode,
  getSessionHistory,
  getSessionTokens,
  listSessions,
  listSkills,
  loadFile,
  renameSession,
  saveFile,
  setRagMode,
  streamChat
} from "@/lib/api";

import type { Store } from "./core";
import { reduceStreamEvent, startStreamingTurn, type StreamSession } from "./events";
import type { StoreActions, StoreState } from "./types";
import { toUiMessages } from "./utils";

export class WorkspaceRuntime {
  private createSessionPromise: Promise<string> | null = null;
  private sessionDetailsRequest = 0;
  private sessionRefreshTimers: number[] = [];

  readonly actions: StoreActions;

  constructor(private readonly store: Store<StoreState>) {
    this.actions = {
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
      compressCurrentSession: async () => {
        await this.compressCurrentSession();
      },
      setSidebarWidth: (width) => {
        this.setSidebarWidth(width);
      },
      setInspectorWidth: (width) => {
        this.setInspectorWidth(width);
      }
    };
  }

  async initialize() {
    const [sessions, rag, skills] = await Promise.all([
      listSessions(),
      getRagMode(),
      listSkills()
    ]);

    this.store.setState((prev) => ({
      ...prev,
      sessions,
      ragMode: rag.enabled,
      skills
    }));

    const currentSessionId = this.store.getState().currentSessionId;
    if (!currentSessionId && sessions.length) {
      await this.selectSession(sessions[0].id);
    } else if (!currentSessionId) {
      await this.createFreshSession();
    }

    const file = await loadFile("durable_memory/MEMORY.md");
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
    let transition = startStreamingTurn(this.store.getState(), trimmed);
    this.store.setState(() => transition.state);

    try {
      await streamChat(
        { message: trimmed, session_id: sessionId },
        {
          onEvent: (event, data) => {
            transition = reduceStreamEvent(this.store.getState(), transition.session, event, data);
            this.store.setState(() => transition.state);
          }
        }
      );
    } catch (error) {
      transition = reduceStreamEvent(
        this.store.getState(),
        transition.session,
        "error",
        { error: error instanceof Error ? error.message : "unknown error" }
      );
      this.store.setState(() => transition.state);
    } finally {
      this.store.setState((prev) => ({ ...prev, isStreaming: false }));
      if (this.store.getState().currentSessionId === sessionId) {
        await this.refreshSessionDetails(sessionId);
      }
      await this.refreshSessions();
      this.scheduleSessionRefreshes();
    }
  }

  private async toggleRagMode() {
    const next = !this.store.getState().ragMode;
    this.store.setState((prev) => ({ ...prev, ragMode: next }));
    try {
      await setRagMode(next);
    } catch (error) {
      this.store.setState((prev) => ({ ...prev, ragMode: !next }));
      throw error;
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

  private async compressCurrentSession() {
    const currentSessionId = this.store.getState().currentSessionId;
    if (!currentSessionId) {
      return;
    }
    await compressSession(currentSessionId);
    await this.refreshSessionDetails(currentSessionId);
    await this.refreshSessions();
  }

  private setSidebarWidth(width: number) {
    this.store.setState((prev) => ({ ...prev, sidebarWidth: width }));
  }

  private setInspectorWidth(width: number) {
    this.store.setState((prev) => ({ ...prev, inspectorWidth: width }));
  }
}
