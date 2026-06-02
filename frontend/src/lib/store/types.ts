import type {
  OrchestrationSnapshot,
  GlobalRuntimeMonitor,
  GraphRunMonitorView,
  ModelProviderConfig,
  RetrievalResult,
  RuntimeMonitorEventPayload,
  ImageAssetConfig,
  HarnessTaskRunLiveMonitor,
  SessionRuntimeAttachment,
  SessionScope,
  SessionSummary,
  ToolCall,
  WorkspaceContext,
  CodeEnvironmentWorkspaceTree
} from "@/lib/api";
import type { RuntimeTaskInstanceState } from "@/lib/runtime-monitor/types";

export type {
  RuntimeProgressEvidence,
  RuntimeProgressMission,
  RuntimeProgressPresentation,
  RuntimeProgressTechnicalTrace,
  RuntimeProgressWorkUnit,
} from "@/lib/api";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
  runtimeProgress?: RuntimeProgressEntry[];
  runtimeAttachments?: SessionRuntimeAttachment[];
  stageStatus?: string;
  sourceIndex?: number;
  image?: {
    src: string;
    alt?: string;
    caption?: string;
  } | null;
};

export type SessionActivityLevel = "idle" | "running" | "waiting" | "success" | "warning" | "error" | "stopped";
export type RuntimeMonitorStreamStatus = "connecting" | "connected" | "fallback" | "closed";

export type UserReceiptArtifact = {
  label: string;
  path?: string;
  value?: string;
};

export type UserReceipt = {
  level: SessionActivityLevel;
  title: string;
  body?: string;
  scope?: string;
  artifacts?: UserReceiptArtifact[];
  debug?: Record<string, string>;
};

export type RuntimeProgressEntry = {
  id: string;
  level: SessionActivityLevel;
  title: string;
  body?: string;
  publicNote?: string;
  agentBrief?: string;
  evidenceType?: string;
  eventType: string;
  kind?:
    | "task_order"
    | "task_draft"
    | "stage"
    | "tool"
    | "artifact"
    | "verification"
    | "permission"
    | "context"
    | "memory"
    | "model"
    | "observation"
    | "terminal"
    | "system";
  statusText?: string;
  meta?: Array<{ label: string; value: string }>;
  toolName?: string;
  runId?: string;
  taskRunId?: string;
  createdAt?: number;
  startedAt?: number;
  completedAt?: number;
  artifacts?: UserReceiptArtifact[];
};

export type SessionActivityState = {
  level: SessionActivityLevel;
  title: string;
  detail: string;
  event: string;
  toolName?: string;
  receipt?: UserReceipt | null;
  updatedAt: number;
};

export type TokenStats = {
  system_tokens: number;
  message_tokens: number;
  total_tokens: number;
  raw_history_tokens: number;
  history_tokens: number;
  history_budget_tokens: number;
  history_remaining_tokens: number;
  history_usage_ratio: number;
  history_remaining_ratio: number;
  history_pressure_level: string;
  history_compaction_strategy: string;
  history_did_compact: boolean;
  history_did_microcompact: boolean;
  history_did_full_compact: boolean;
};

export type SkillSummary = {
  name: string;
  title: string;
  description: string;
  path: string;
};

export type WorkspaceView =
  | "chat"
  | "creative"
  | "memory"
  | "health-system"
  | "capability-system"
  | "task-system"
  | "orchestration"
  | "code-environment"
  | "system-config";

export type TaskEnvironmentWorkspaceView = Extract<WorkspaceView, "chat" | "code-environment" | "creative">;

export type SearchPolicySource = "rag" | "local_files" | "web";

export type SearchPolicyState = Record<SearchPolicySource, boolean>;

export type ChatModelSelection = {
  selection_id: string;
  provider: string;
  model: string;
  base_url?: string;
  credential_ref?: string;
  thinking_mode?: "enabled" | "disabled";
  reasoning_effort?: "auto" | "high" | "max";
};

export type ChatMode = "chat" | "image";
export type ChatThinkingMode = "normal" | "thinking";

export type MemoryInspectorTarget = {
  source: "manual";
  runId?: string;
  turnId?: string;
  turnIndex?: number;
  layer?: "conversation" | "state" | "durable";
  reason?: string;
};

export type OrchestrationInspectorTarget = {
  source: "task-system" | "live-session" | "manual";
  runId?: string;
  turnId?: string;
  turnIndex?: number;
  artifactPath?: string;
  reason?: string;
  orchestrationLayer?: "registry" | "groups" | "runtime" | "permissions" | "model_runtime" | "context" | "eligibility";
  agentId?: string;
  agentProfileId?: string;
  graphId?: string;
  nodeId?: string;
};

export type TaskSelectionState = {
  selected_task_id?: string;
  task_graph_id?: string;
  selected_graph_id?: string;
  domain_id?: string;
  label?: string;
  mode?: "single_task" | "task_graph";
  agent_id?: string;
  agent_profile_id?: string;
  runtime_assembly_hint?: Record<string, unknown>;
  runtime_policy?: Record<string, unknown>;
  agent_invocation?: Record<string, unknown>;
  agent_invocation_id?: string;
};

export type ChatTaskEnvironmentBinding = {
  task_environment_id: string;
  environment_label: string;
  source: "task-system" | "task-graph-workbench" | "center-workspace" | "workspace-mode";
  bound_at: number;
};

export type TaskGraphMonitorBinding = {
  task_run_id?: string;
  graph_run_id: string;
  graph_harness_config_id: string;
  graph_id?: string;
  session_id?: string;
  project_id?: string;
  session_scope?: Partial<SessionScope>;
  title?: string;
  bound_at: number;
};

export type ActiveTurnSnapshot = {
  turn_id: string;
  turn_run_id?: string;
  task_run_id?: string;
  state?: string;
  updated_at?: number;
};

export type TaskGraphCenterWorkspaceTarget = {
  layer: "task-graph";
  mode?: "editor" | "monitor";
  graph_id?: string;
  task_run_id?: string;
  task_instance_id?: string;
  graph_run_id?: string;
  focus_node_id?: string;
  requested_at: number;
};

export type FileCenterWorkspaceTarget = {
  layer: "file";
  file_path: string;
  requested_at: number;
};

export type CenterWorkspaceTarget = TaskGraphCenterWorkspaceTarget | FileCenterWorkspaceTarget;

export type StoreState = {
  activeWorkspaceView: WorkspaceView;
  workspaceContext: WorkspaceContext | null;
  workspaceTree: CodeEnvironmentWorkspaceTree | null;
  workspaceTreeLoading: boolean;
  workspaceTreeError: string;
  sessions: SessionSummary[];
  currentSessionId: string | null;
  activeSessionScope: Partial<SessionScope> | null;
  workspaceInitializing: boolean;
  messages: Message[];
  isStreaming: boolean;
  activeStreamSessionIds: string[];
  sessionActivity: SessionActivityState;
  sessionActivitiesById: Record<string, SessionActivityState>;
  ragMode: boolean;
  searchPolicy: SearchPolicyState;
  modelProviderConfig: ModelProviderConfig | null;
  imageAssetConfig: ImageAssetConfig | null;
  selectedChatModelId: string;
  selectedChatMode: ChatMode;
  chatThinkingMode: ChatThinkingMode;
  skills: SkillSummary[];
  pendingEphemeralSystemMessages: string[];
  inspectorPath: string;
  inspectorContent: string;
  inspectorDirty: boolean;
  sidebarWidth: number;
  inspectorWidth: number;
  tokenStats: TokenStats | null;
  memoryInspectorTarget: MemoryInspectorTarget | null;
  orchestrationSnapshot: OrchestrationSnapshot | null;
  taskGraphMonitorBinding: TaskGraphMonitorBinding | null;
  activeTurnSnapshot: ActiveTurnSnapshot | null;
  taskGraphLiveMonitor: HarnessTaskRunLiveMonitor | null;
  globalRuntimeMonitor: GlobalRuntimeMonitor | null;
  globalRuntimeMonitorRevision: string;
  globalRuntimeMonitorSelectedTaskInstanceId: string;
  globalRuntimeMonitorSelectedTaskRunId: string;
  globalRuntimeMonitorSelectedLiveMonitor: HarnessTaskRunLiveMonitor | null;
  globalRuntimeMonitorSelectedGraphMonitor: GraphRunMonitorView | null;
  runtimeMonitorInstancesById: Record<string, RuntimeTaskInstanceState>;
  globalRuntimeMonitorLoading: boolean;
  globalRuntimeMonitorError: string;
  globalRuntimeMonitorStreamStatus: RuntimeMonitorStreamStatus;
  globalRuntimeMonitorLastEvent: RuntimeMonitorEventPayload["runtime_event"] | null;
  taskGraphBoundRunMonitor: GraphRunMonitorView | null;
  taskGraphMonitorLoading: boolean;
  taskGraphMonitorActionLoading: boolean;
  taskGraphAutoAdvanceEnabled: boolean;
  taskGraphAutoAdvancePending: boolean;
  taskGraphMonitorError: string;
  taskGraphRunInteractionOpen: boolean;
  orchestrationInspectorTarget: OrchestrationInspectorTarget | null;
  taskSelection: TaskSelectionState | null;
  chatTaskEnvironmentBinding: ChatTaskEnvironmentBinding | null;
  centerWorkspaceTarget: CenterWorkspaceTarget | null;
};

export type StoreActions = {
  setWorkspaceView: (view: WorkspaceView) => void;
  setTaskEnvironmentWorkspaceView: (view: TaskEnvironmentWorkspaceView) => void;
  refreshWorkspaceTree: () => Promise<void>;
  createNewSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  sendMessage: (value: string) => Promise<void>;
  stopCurrentStream: () => void;
  pauseActiveTaskRun: () => Promise<void>;
  resumeActiveTaskRun: () => Promise<void>;
  stopActiveTaskRun: () => Promise<void>;
  resendEditedMessage: (messageId: string, value: string) => Promise<void>;
  toggleRagMode: () => Promise<void>;
  toggleSearchPolicySource: (source: SearchPolicySource) => void;
  setSelectedChatModel: (selectionId: string) => void;
  setSelectedChatMode: (mode: ChatMode) => void;
  setChatThinkingMode: (mode: ChatThinkingMode) => void;
  renameCurrentSession: (title: string) => Promise<void>;
  removeSession: (sessionId: string) => Promise<void>;
  loadInspectorFile: (path: string) => Promise<void>;
  updateInspectorContent: (value: string) => void;
  saveInspector: () => Promise<void>;
  setSidebarWidth: (width: number) => void;
  setInspectorWidth: (width: number) => void;
  setMemoryInspectorTarget: (target: MemoryInspectorTarget | null) => void;
  setOrchestrationInspectorTarget: (target: OrchestrationInspectorTarget | null) => void;
  setOrchestrationSnapshot: (snapshot: OrchestrationSnapshot | null) => void;
  bindTaskGraphMonitorRun: (binding: Omit<TaskGraphMonitorBinding, "bound_at"> & { bound_at?: number }) => void;
  clearTaskGraphMonitorRun: () => void;
  setTaskGraphRunInteractionOpen: (open: boolean) => void;
  setTaskGraphAutoAdvanceEnabled: (enabled: boolean) => void;
  evaluateBoundTaskGraphMonitor: () => Promise<void>;
  continueBoundTaskGraphRun: () => Promise<void>;
  resumeTaskGraphRun: (taskGraphRunId: string, payload?: Record<string, unknown>) => Promise<void>;
  setTaskSelection: (selection: TaskSelectionState | null) => void;
  setChatTaskEnvironmentBinding: (
    binding: Omit<ChatTaskEnvironmentBinding, "bound_at"> & { bound_at?: number }
  ) => void;
  clearChatTaskEnvironmentBinding: () => void;
  selectGlobalRuntimeMonitorTaskRun: (taskRunId: string) => void;
  openGlobalRuntimeMonitorTaskRun: (taskRunId: string) => void;
  openTaskGraphWorkspace: (target?: Omit<TaskGraphCenterWorkspaceTarget, "layer" | "requested_at">) => void;
  openWorkspaceFile: (path: string) => void;
  clearCenterWorkspaceTarget: () => void;
  refreshGlobalRuntimeMonitor: () => Promise<void>;
};

export type AppStore = StoreState &
  StoreActions & {
    editableFiles: string[];
  };


