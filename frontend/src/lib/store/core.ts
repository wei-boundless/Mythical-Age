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
    projectWorkspaces: [],
    projectWorkspacesLoading: false,
    projectWorkspacesError: "",
    activeProjectKey: "",
    activeProjectRoot: "",
    projectSessions: [],
    sessions: [],
    currentSessionId: null,
    activeSessionScope: null,
    activeSessionRef: null,
    taskEnvironmentCatalog: null,
    taskEnvironmentCatalogLoading: false,
    taskEnvironmentCatalogError: "",
    conversationActiveEnvironment: null,
    workspaceInitializing: true,
    messages: [],
    activeProjectionsByKey: {},
    assistantTextStreamsByMessageId: {},
    isStreaming: false,
    activeStreamSessionIds: [],
    chatStreamConnectionStatus: { state: "idle", updatedAt: 0 },
    chatStreamLatencySummary: null,
    sessionActivity: createIdleSessionActivity(),
    sessionActivitiesById: {},
    permissionMode: "full_access",
    supportedPermissionModes: ["default", "plan", "accept_edits", "bypass", "full_access"],
    modelProviderConfig: null,
    imageAssetConfig: null,
    selectedChatModelId: "system-default",
    selectedChatMode: "chat",
    chatThinkingMode: "normal",
    chatStreamDisplayEnabled: true,
    skills: [],
    inspectorPath: "durable_memory/index/MEMORY.md",
    inspectorContent: "",
    inspectorDirty: false,
    sessionEditorContexts: {},
    sidebarWidth: 308,
    inspectorWidth: 300,
    tokenStats: null,
    memoryInspectorTarget: null,
    orchestrationSnapshot: null,
    taskGraphMonitorBinding: null,
    activeTurnSnapshot: null,
    taskGraphLiveMonitor: null,
    runMonitor: null,
    runMonitorRevision: "",
    runMonitorSelectedSignalId: "",
    runMonitorSelectedTaskRunId: "",
    runMonitorSelectedDetail: null,
    runMonitorSelectedGraphMonitor: null,
    runMonitorLoading: false,
    runMonitorError: "",
    runMonitorStreamStatus: "closed",
    runMonitorActionLoading: "",
    runMonitorLastActionResult: null,
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
    taskGraphWorkspaceTarget: null,
    centerWorkspaceTarget: null
  };
}
