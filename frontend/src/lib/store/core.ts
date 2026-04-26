import type { StoreState } from "./types";

type Listener = () => void;

export type Store<T> = {
  getState: () => T;
  setState: (updater: (prev: T) => T) => void;
  subscribe: (listener: Listener) => () => void;
};

export function createStore<T>(initialState: T): Store<T> {
  let state = initialState;
  const listeners = new Set<Listener>();

  return {
    getState: () => state,
    setState: (updater) => {
      const next = updater(state);
      if (Object.is(next, state)) {
        return;
      }
      state = next;
      for (const listener of listeners) {
        listener();
      }
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    }
  };
}

export function getDefaultState(): StoreState {
  return {
    activeWorkspaceView: "chat",
    sessions: [],
    currentSessionId: null,
    messages: [],
    isStreaming: false,
    ragMode: false,
    skills: [],
    soulOptions: [],
    activeSoulKey: null,
    pendingEphemeralSystemMessages: [],
    inspectorPath: "durable_memory/MEMORY.md",
    inspectorContent: "",
    inspectorDirty: false,
    sidebarWidth: 308,
    inspectorWidth: 300,
    tokenStats: null,
    systemGraphHighlight: null,
    systemGraphOverlay: null,
    memoryInspectorTarget: null,
    orchestrationSnapshot: null,
    orchestrationInspectorTarget: null
  };
}
