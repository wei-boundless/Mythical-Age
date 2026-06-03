import type { SessionActivityState, StoreState } from "./types";

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

export function createIdleSessionActivity(updatedAt = 0): SessionActivityState {
  return {
    level: "idle",
    title: "待命",
    detail: "输入消息后，会在这里显示当前处理阶段。",
    event: "",
    updatedAt
  };
}

export function getDefaultState(): StoreState {
  return {
    activeWorkspaceView: "chat",
    workspaceContext: null,
    workspaceTree: null,
    workspaceTreeLoading: false,
    workspaceTreeError: "",
    sessions: [],
    currentSessionId: null,
    activeSessionScope: null,
    activeSessionRef: null,
    workspaceInitializing: true,
    messages: [],
    isStreaming: false,
    activeStreamSessionIds: [],
    sessionActivity: createIdleSessionActivity(),
    sessionActivitiesById: {},
    ragMode: false,
    searchPolicy: {
      rag: false,
      local_files: true,
      web: false
    },
    modelProviderConfig: null,
    imageAssetConfig: null,
    selectedChatModelId: "system-default",
    selectedChatMode: "chat",
    chatThinkingMode: "normal",
    skills: [],
    pendingEphemeralSystemMessages: [],
    inspectorPath: "durable_memory/index/MEMORY.md",
    inspectorContent: "",
    inspectorDirty: false,
    sidebarWidth: 308,
    inspectorWidth: 300,
    tokenStats: null,
    memoryInspectorTarget: null,
    orchestrationSnapshot: null,
    taskGraphMonitorBinding: null,
    activeTurnSnapshot: null,
    taskGraphLiveMonitor: null,
    globalRuntimeMonitor: null,
    globalRuntimeMonitorRevision: "",
    globalRuntimeMonitorSelectedTaskInstanceId: "",
    globalRuntimeMonitorSelectedTaskRunId: "",
    globalRuntimeMonitorSelectedLiveMonitor: null,
    globalRuntimeMonitorSelectedGraphMonitor: null,
    runtimeMonitorInstancesById: {},
    globalRuntimeMonitorLoading: false,
    globalRuntimeMonitorError: "",
    globalRuntimeMonitorStreamStatus: "closed",
    globalRuntimeMonitorLastEvent: null,
    taskGraphBoundRunMonitor: null,
    taskGraphMonitorLoading: false,
    taskGraphMonitorActionLoading: false,
    taskGraphAutoAdvanceEnabled: false,
    taskGraphAutoAdvancePending: false,
    taskGraphMonitorError: "",
    taskGraphRunInteractionOpen: false,
    orchestrationInspectorTarget: null,
    taskSelection: null,
    chatTaskEnvironmentBinding: null,
    centerWorkspaceTarget: null
  };
}

