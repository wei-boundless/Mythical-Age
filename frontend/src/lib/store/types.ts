import type {
  OrchestrationSnapshot,
  GlobalRuntimeMonitor,
  ModelProviderConfig,
  RetrievalResult,
  RuntimeMonitorEventPayload,
  SoulImageAssetConfig,
  TaskOrderProjection,
  TaskGraphMonitorDecision,
  TaskGraphRunMonitorView,
  RuntimeLoopTaskRunLiveMonitor,
  SessionSummary,
  ToolCall,
  WorkspaceContext,
  CodeEnvironmentWorkspaceTree
} from "@/lib/api";
import type { SoulKey, SoulSummary } from "@/lib/souls";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
  runtimeProgress?: RuntimeProgressEntry[];
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
    | "terminal"
    | "system";
  statusText?: string;
  meta?: Array<{ label: string; value: string }>;
  toolName?: string;
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
  | "memory"
  | "test-system"
  | "health-system"
  | "capability-system"
  | "soul-system"
  | "evidence"
  | "task-system"
  | "orchestration"
  | "code-environment"
  | "experiments"
  | "playground"
  | "system-config";

export type SearchPolicySource = "rag" | "local_files" | "web";

export type SearchPolicyState = Record<SearchPolicySource, boolean>;

export type ChatModelSelection = {
  selection_id: string;
  provider: string;
  model: string;
  base_url?: string;
  credential_ref?: string;
  thinking_mode?: "enabled" | "disabled";
  reasoning_effort?: "high" | "max";
};

export type ChatMode = "chat" | "image";

export type MainAgentAssemblyMode = "role" | "standard" | "professional";

export type MemoryInspectorTarget = {
  source: "test-system" | "manual";
  runId?: string;
  turnId?: string;
  turnIndex?: number;
  layer?: "conversation" | "state" | "durable";
  reason?: string;
};

export type OrchestrationInspectorTarget = {
  source: "test-system" | "task-system" | "live-session" | "manual";
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
  coordination_task_id?: string;
  task_graph_id?: string;
  selected_graph_id?: string;
  domain_id?: string;
  label?: string;
  mode?: "single_task" | "coordination";
  agent_id?: string;
  agent_profile_id?: string;
  runtime_lane?: string;
  interaction_mode?: string;
  runtime_interaction_mode?: string;
  runtime_assembly_hint?: Record<string, unknown>;
  mode_policy?: Record<string, unknown>;
  intent_decision?: Record<string, unknown>;
  agent_invocation?: Record<string, unknown>;
  agent_invocation_id?: string;
  task_order_id?: string;
  task_order_run_id?: string;
  execution_channel_id?: string;
  task_execution_envelope_id?: string;
};

export type TaskGraphMonitorBinding = {
  task_run_id: string;
  coordination_run_id?: string;
  graph_id?: string;
  session_id?: string;
  project_id?: string;
  title?: string;
  bound_at: number;
};

export type StoreState = {
  activeWorkspaceView: WorkspaceView;
  workspaceContext: WorkspaceContext | null;
  workspaceTree: CodeEnvironmentWorkspaceTree | null;
  workspaceTreeLoading: boolean;
  workspaceTreeError: string;
  sessions: SessionSummary[];
  currentSessionId: string | null;
  workspaceInitializing: boolean;
  messages: Message[];
  isStreaming: boolean;
  activeStreamSessionIds: string[];
  sessionActivity: SessionActivityState;
  ragMode: boolean;
  searchPolicy: SearchPolicyState;
  modelProviderConfig: ModelProviderConfig | null;
  soulImageAssetConfig: SoulImageAssetConfig | null;
  selectedChatModelId: string;
  selectedChatMode: ChatMode;
  deepSeekThinkingEnabled: boolean;
  mainAgentAssemblyMode: MainAgentAssemblyMode;
  skills: SkillSummary[];
  soulOptions: SoulSummary[];
  activeSoulKey: SoulKey | null;
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
  taskGraphLiveMonitor: RuntimeLoopTaskRunLiveMonitor | null;
  taskGraphRunMonitor: TaskGraphRunMonitorView | null;
  globalRuntimeMonitor: GlobalRuntimeMonitor | null;
  globalRuntimeMonitorSelectedTaskRunId: string;
  globalRuntimeMonitorSelectedLiveMonitor: RuntimeLoopTaskRunLiveMonitor | null;
  globalRuntimeMonitorSelectedGraphMonitor: TaskGraphRunMonitorView | null;
  globalRuntimeMonitorLoading: boolean;
  globalRuntimeMonitorError: string;
  globalRuntimeMonitorStreamStatus: RuntimeMonitorStreamStatus;
  globalRuntimeMonitorLastEvent: RuntimeMonitorEventPayload["runtime_event"] | null;
  taskGraphBoundRunMonitor: TaskGraphRunMonitorView | null;
  taskGraphMonitorDecision: TaskGraphMonitorDecision | null;
  taskGraphMonitorDecisions: TaskGraphMonitorDecision[];
  taskGraphMonitorLoading: boolean;
  taskGraphMonitorActionLoading: boolean;
  taskGraphMonitorError: string;
  taskGraphRunInteractionOpen: boolean;
  orchestrationInspectorTarget: OrchestrationInspectorTarget | null;
  taskSelection: TaskSelectionState | null;
  taskOrderProjection: TaskOrderProjection | null;
  selectedTaskOrderId: string;
  selectedTaskOrderRunId: string;
  taskOrderProjectionConsumed: boolean;
};

export type StoreActions = {
  setWorkspaceView: (view: WorkspaceView) => void;
  refreshWorkspaceTree: () => Promise<void>;
  createNewSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  sendMessage: (value: string) => Promise<void>;
  stopCurrentStream: () => void;
  resendEditedMessage: (messageId: string, value: string) => Promise<void>;
  toggleRagMode: () => Promise<void>;
  toggleSearchPolicySource: (source: SearchPolicySource) => void;
  setSelectedChatModel: (selectionId: string) => void;
  setSelectedChatMode: (mode: ChatMode) => void;
  setDeepSeekThinkingEnabled: (enabled: boolean) => void;
  setMainAgentAssemblyMode: (mode: MainAgentAssemblyMode) => void;
  switchSoul: (key: SoulKey) => Promise<void>;
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
  evaluateBoundTaskGraphMonitor: () => Promise<void>;
  continueBoundTaskGraphRun: () => Promise<void>;
  refreshAndContinueBoundTaskGraphRun: () => Promise<void>;
  submitTaskGraphMonitorDecision: (decision: string, controlAction: string, resumePayload?: Record<string, unknown>) => Promise<void>;
  resumeTaskGraphRun: (taskGraphRunId: string, payload?: Record<string, unknown>) => Promise<void>;
  resolveRuntimeApproval: (taskRunId: string, decision: "approve" | "reject", message?: string) => Promise<void>;
  setTaskSelection: (selection: TaskSelectionState | null) => void;
  setTaskOrderProjection: (projection: TaskOrderProjection | null) => void;
  selectGlobalRuntimeMonitorTaskRun: (taskRunId: string) => void;
  refreshGlobalRuntimeMonitor: () => Promise<void>;
};

export type AppStore = StoreState &
  StoreActions & {
    editableFiles: string[];
  };

