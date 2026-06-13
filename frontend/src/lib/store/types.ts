import type {
  OrchestrationSnapshot,
  GraphRunMonitorView,
  ModelProviderConfig,
  MessagePublicProjection,
  ProjectionLedger,
  PublicChatTimelineItem,
  PublicProjectionFrame,
  RetrievalResult,
  RuntimeLogScope,
  RuntimeMonitorActionPayload,
  RuntimeMonitorActionResult,
  RuntimeMonitorEnvelope,
  ImageAssetConfig,
  HarnessTaskRunLiveMonitor,
  SessionScope,
  SessionSummary,
  TaskEnvironmentCatalog,
  ConversationActiveEnvironment,
  ToolCall,
  WorkspaceContext,
  CodeEnvironmentWorkspaceTree,
  ProjectWorkspaceSummary
} from "@/lib/api";

export type {
  MessagePublicProjection,
  ProjectionLedger,
  PublicChatTimelineItem,
  PublicProjectionFrame,
  PublicProjectionItem,
} from "@/lib/api";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
  runtimeProgress?: RuntimeProgressEntry[];
  projectionLedger?: ProjectionLedger;
  publicProjection?: MessagePublicProjection;
  stageStatus?: string;
  sourceIndex?: number;
  sourceTurnId?: string;
  sourceRunId?: string;
  sourceTaskRunId?: string;
  sourceTurnRunId?: string;
  answerChannel?: string;
  answerSource?: string;
  answerCanonicalState?: string;
  answerPersistPolicy?: string;
  answerFinalizationPolicy?: string;
  answerFallbackReason?: string;
  answerSelectedChannel?: string;
  answerSelectedSource?: string;
  answerLeakFlags?: string[];
  image?: {
    src: string;
    alt?: string;
    caption?: string;
  } | null;
};

export type AssistantTextStreamState = {
  messageId: string;
  messageRef: string;
  streamRef: string;
  latestSequence: number;
  canonicalContent: string;
  canonicalContentSha256: string;
  accumulatedUtf8Bytes: number;
  finalReceived: boolean;
  terminal: boolean;
  repairState: "none" | "pending" | "applied" | "failed";
  displayHintsBySequence: Record<number, Record<string, unknown>>;
  orderedSegmentIds?: string[];
  segmentsById?: Record<string, AssistantTextSegmentState>;
};

export type AssistantTextSegmentState = {
  segmentId: string;
  messageRef: string;
  streamRef: string;
  bodySequence: number;
  segmentRole: string;
  latestSequence: number;
  canonicalContent: string;
  canonicalContentSha256: string;
  accumulatedUtf8Bytes: number;
  finalReceived: boolean;
  terminal: boolean;
  repairState: "none" | "pending" | "applied" | "failed";
  displayHintsBySequence: Record<number, Record<string, unknown>>;
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
  context_meter?: {
    current_context_tokens?: number;
    current_context_ratio?: number;
    compaction_pressure_tokens?: number;
    context_window_tokens?: number;
    input_capacity_tokens?: number;
    replacement_threshold_tokens?: number;
    compaction_pressure_ratio?: number;
    compaction_remaining_tokens?: number;
    compaction_remaining_ratio?: number;
    pressure_level?: string;
  };
  context_recovery_package?: {
    present?: boolean;
    fresh?: boolean;
    source?: string;
    schema_version?: string;
    covered_message_count?: number;
    covered_event_run_id?: string;
    covered_event_offset_end?: number | null;
    summary_hash?: string;
    source_summary_hash?: string;
    freshness_status?: string;
    stale_reason?: string;
  };
  compaction_readiness?: {
    context_recovery_package_present?: boolean;
    context_recovery_package_fresh?: boolean;
    context_recovery_package_source?: string;
  };
  cumulative_transcript_tokens?: number;
  cumulative_transcript_message_count?: number;
  compression_saved_tokens?: number;
  compression_ratio?: number;
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

export type TaskEnvironmentWorkspaceView = Extract<WorkspaceView, "chat" | "code-environment">;

export type ChatModelSelection = {
  selection_id?: string;
  provider?: string;
  model?: string;
  base_url?: string;
  credential_ref?: string;
  thinking_mode?: "enabled" | "disabled";
  reasoning_effort?: "auto" | "high" | "max";
  stream_policy?: Record<string, unknown>;
};

export type ChatMode = "chat" | "image";
export type ChatThinkingMode = "normal" | "thinking";
export type PermissionMode = string;

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

export type ConversationTaskEnvironment = ConversationActiveEnvironment;

export type ChatTaskEnvironmentBinding = {
  task_environment_id: string;
  environment_label: string;
  source: "task-system" | "task-graph-workbench" | "center-workspace" | "workspace-mode";
  bound_at: number;
};

export type SessionPoolKey = "main-chat" | `task_environment:${string}:${string}` | `graph_task:${string}`;

export type SessionRef = {
  sessionId: string;
  scope?: Partial<SessionScope>;
  poolKey?: SessionPoolKey;
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

export type ActiveTurnState =
  | "starting"
  | "model_turn"
  | "running_task"
  | "waiting_executor"
  | "waiting_user"
  | "waiting_approval"
  | "waiting_safe_boundary"
  | "interrupting"
  | "terminal";

export type ActiveTurnSnapshot = {
  turn_id: string;
  turn_run_id?: string;
  task_run_id?: string;
  state?: ActiveTurnState;
  updated_at?: number;
};

export type TaskGraphWorkspaceTarget = {
  layer: "task-graph";
  mode?: "editor" | "monitor";
  task_environment_id?: string;
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

export type RuntimeLogCenterWorkspaceTarget = {
  layer: "runtime-log";
  scope: RuntimeLogScope;
  run_id: string;
  title?: string;
  subtitle?: string;
  requested_at: number;
};

export type CenterWorkspaceTarget = FileCenterWorkspaceTarget | RuntimeLogCenterWorkspaceTarget;

export type SessionEditorContext = {
  activeFilePath: string;
  openFilePaths: string[];
  inspectorPath: string;
  inspectorContent: string;
  inspectorDirty: boolean;
  updatedAt: number;
};

export type SessionEditorPageStatePatch = {
  activeFilePath?: string;
  openFilePaths?: string[];
};

export type StoreState = {
  activeWorkspaceView: WorkspaceView;
  workspaceContext: WorkspaceContext | null;
  workspaceTree: CodeEnvironmentWorkspaceTree | null;
  workspaceTreeLoading: boolean;
  workspaceTreeError: string;
  projectWorkspaces: ProjectWorkspaceSummary[];
  projectWorkspacesLoading: boolean;
  projectWorkspacesError: string;
  activeProjectKey: string;
  activeProjectRoot: string;
  projectSessions: SessionSummary[];
  sessions: SessionSummary[];
  currentSessionId: string | null;
  activeSessionScope: Partial<SessionScope> | null;
  activeSessionRef: SessionRef | null;
  taskEnvironmentCatalog: TaskEnvironmentCatalog | null;
  taskEnvironmentCatalogLoading: boolean;
  taskEnvironmentCatalogError: string;
  conversationActiveEnvironment: ConversationTaskEnvironment | null;
  workspaceInitializing: boolean;
  messages: Message[];
  assistantTextStreamsByMessageId: Record<string, AssistantTextStreamState>;
  isStreaming: boolean;
  activeStreamSessionIds: string[];
  sessionActivity: SessionActivityState;
  sessionActivitiesById: Record<string, SessionActivityState>;
  permissionMode: PermissionMode;
  supportedPermissionModes: PermissionMode[];
  modelProviderConfig: ModelProviderConfig | null;
  imageAssetConfig: ImageAssetConfig | null;
  selectedChatModelId: string;
  selectedChatMode: ChatMode;
  chatThinkingMode: ChatThinkingMode;
  chatStreamDisplayEnabled: boolean;
  skills: SkillSummary[];
  inspectorPath: string;
  inspectorContent: string;
  inspectorDirty: boolean;
  sessionEditorContexts: Record<string, SessionEditorContext>;
  sidebarWidth: number;
  inspectorWidth: number;
  tokenStats: TokenStats | null;
  memoryInspectorTarget: MemoryInspectorTarget | null;
  orchestrationSnapshot: OrchestrationSnapshot | null;
  taskGraphMonitorBinding: TaskGraphMonitorBinding | null;
  activeTurnSnapshot: ActiveTurnSnapshot | null;
  taskGraphLiveMonitor: HarnessTaskRunLiveMonitor | null;
  runMonitor: RuntimeMonitorEnvelope | null;
  runMonitorRevision: string;
  runMonitorSelectedSignalId: string;
  runMonitorSelectedTaskRunId: string;
  runMonitorSelectedDetail: HarnessTaskRunLiveMonitor | null;
  runMonitorSelectedGraphMonitor: GraphRunMonitorView | null;
  runMonitorLoading: boolean;
  runMonitorError: string;
  runMonitorStreamStatus: RuntimeMonitorStreamStatus;
  runMonitorActionLoading: string;
  runMonitorLastActionResult: RuntimeMonitorActionResult | null;
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
  taskGraphWorkspaceTarget: TaskGraphWorkspaceTarget | null;
  centerWorkspaceTarget: CenterWorkspaceTarget | null;
};

export type StoreActions = {
  setWorkspaceView: (view: WorkspaceView) => void;
  setTaskEnvironmentWorkspaceView: (view: TaskEnvironmentWorkspaceView) => void;
  refreshTaskEnvironmentCatalog: () => Promise<void>;
  setActiveTaskEnvironment: (environmentId: string, options?: { environmentLabel?: string; source?: string }) => Promise<void>;
  refreshWorkspaceTree: () => Promise<void>;
  selectProjectWorkspace: (projectKey: string) => Promise<void>;
  selectProjectWorkspaceDirectory: () => Promise<void>;
  removeProjectWorkspace: (projectKey: string) => Promise<void>;
  refreshProjectWorkspaces: () => Promise<void>;
  refreshProjectSessions: () => Promise<void>;
  createNewSession: () => Promise<void>;
  selectSession: (ref: SessionRef) => Promise<void>;
  sendMessage: (value: string) => Promise<void>;
  stopCurrentStream: () => void;
  pauseActiveTaskRun: () => Promise<void>;
  resumeActiveTaskRun: () => Promise<void>;
  stopActiveTaskRun: () => Promise<void>;
  resendEditedMessage: (messageId: string, value: string) => Promise<void>;
  setPermissionMode: (mode: PermissionMode) => Promise<void>;
  setSelectedChatModel: (selectionId: string) => void;
  setSelectedChatMode: (mode: ChatMode) => void;
  setChatThinkingMode: (mode: ChatThinkingMode) => void;
  setChatStreamDisplayEnabled: (enabled: boolean) => void;
  renameCurrentSession: (title: string) => Promise<void>;
  removeSession: (ref: SessionRef) => Promise<void>;
  loadInspectorFile: (path: string) => Promise<void>;
  updateInspectorContent: (value: string) => void;
  saveInspector: () => Promise<void>;
  setSessionEditorPageState: (patch: SessionEditorPageStatePatch) => void;
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
  pauseBoundTaskGraphRun: () => Promise<void>;
  continueBoundTaskGraphRun: () => Promise<void>;
  stopBoundTaskGraphRun: () => Promise<void>;
  resumeTaskGraphRun: (taskGraphRunId: string, payload?: Record<string, unknown>) => Promise<void>;
  setTaskSelection: (selection: TaskSelectionState | null) => void;
  setChatTaskEnvironmentBinding: (
    binding: Omit<ChatTaskEnvironmentBinding, "bound_at"> & { bound_at?: number }
  ) => void;
  clearChatTaskEnvironmentBinding: () => void;
  openRunMonitorSignal: (signalId: string) => void;
  refreshRunMonitor: () => Promise<void>;
  runMonitorAction: (payload: RuntimeMonitorActionPayload) => Promise<RuntimeMonitorActionResult | null>;
  openTaskGraphWorkspace: (target?: Omit<TaskGraphWorkspaceTarget, "layer" | "requested_at">) => void;
  openWorkspaceFile: (path: string) => void;
  openRuntimeLog: (target: Omit<RuntimeLogCenterWorkspaceTarget, "layer" | "requested_at">) => void;
  clearTaskGraphWorkspaceTarget: () => void;
  clearCenterWorkspaceTarget: () => void;
};

export type AppStore = StoreState &
  StoreActions & {
    editableFiles: string[];
  };


