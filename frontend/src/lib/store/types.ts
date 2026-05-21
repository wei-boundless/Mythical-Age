import type {
  OrchestrationSnapshot,
  RetrievalResult,
  TaskGraphMonitorDecision,
  TaskGraphRunMonitorView,
  RuntimeLoopTaskRunLiveMonitor,
  SessionSummary,
  SystemGraphOverlay,
  ToolCall
} from "@/lib/api";
import type { SoulKey, SoulSummary } from "@/lib/souls";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
  stageStatus?: string;
  sourceIndex?: number;
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
  | "mcp-system"
  | "evidence"
  | "task-system"
  | "orchestration"
  | "system-framework"
  | "experiments"
  | "playground"
  | "system-config";

export type SearchPolicySource = "rag" | "local_files" | "web";

export type SearchPolicyState = Record<SearchPolicySource, boolean>;

export type SystemGraphHighlight = {
  nodeIds: string[];
  edgeIds: string[];
  reason: string;
  source: string;
};

export type MemoryInspectorTarget = {
  source: "test-system" | "system-framework" | "manual";
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
  domain_id?: string;
  label?: string;
  mode?: "single_task" | "coordination";
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
  sessions: SessionSummary[];
  currentSessionId: string | null;
  messages: Message[];
  isStreaming: boolean;
  activeStreamSessionIds: string[];
  ragMode: boolean;
  searchPolicy: SearchPolicyState;
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
  systemGraphHighlight: SystemGraphHighlight | null;
  systemGraphOverlay: SystemGraphOverlay | null;
  memoryInspectorTarget: MemoryInspectorTarget | null;
  orchestrationSnapshot: OrchestrationSnapshot | null;
  taskGraphMonitorBinding: TaskGraphMonitorBinding | null;
  taskGraphLiveMonitor: RuntimeLoopTaskRunLiveMonitor | null;
  taskGraphRunMonitor: TaskGraphRunMonitorView | null;
  taskGraphBoundRunMonitor: TaskGraphRunMonitorView | null;
  taskGraphMonitorDecision: TaskGraphMonitorDecision | null;
  taskGraphMonitorDecisions: TaskGraphMonitorDecision[];
  taskGraphMonitorLoading: boolean;
  taskGraphMonitorActionLoading: boolean;
  taskGraphMonitorError: string;
  taskGraphRunInteractionOpen: boolean;
  orchestrationInspectorTarget: OrchestrationInspectorTarget | null;
  taskSelection: TaskSelectionState | null;
};

export type StoreActions = {
  setWorkspaceView: (view: WorkspaceView) => void;
  createNewSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  sendMessage: (value: string) => Promise<void>;
  stopCurrentStream: () => void;
  resendEditedMessage: (messageId: string, value: string) => Promise<void>;
  toggleRagMode: () => Promise<void>;
  toggleSearchPolicySource: (source: SearchPolicySource) => void;
  switchSoul: (key: SoulKey) => Promise<void>;
  renameCurrentSession: (title: string) => Promise<void>;
  removeSession: (sessionId: string) => Promise<void>;
  loadInspectorFile: (path: string) => Promise<void>;
  updateInspectorContent: (value: string) => void;
  saveInspector: () => Promise<void>;
  setSidebarWidth: (width: number) => void;
  setInspectorWidth: (width: number) => void;
  highlightSystemGraph: (highlight: SystemGraphHighlight | null) => void;
  setSystemGraphOverlay: (overlay: SystemGraphOverlay | null) => void;
  setMemoryInspectorTarget: (target: MemoryInspectorTarget | null) => void;
  setOrchestrationInspectorTarget: (target: OrchestrationInspectorTarget | null) => void;
  setOrchestrationSnapshot: (snapshot: OrchestrationSnapshot | null) => void;
  bindTaskGraphMonitorRun: (binding: Omit<TaskGraphMonitorBinding, "bound_at"> & { bound_at?: number }) => void;
  clearTaskGraphMonitorRun: () => void;
  setTaskGraphRunInteractionOpen: (open: boolean) => void;
  evaluateBoundTaskGraphMonitor: () => Promise<void>;
  submitTaskGraphMonitorDecision: (decision: string, controlAction: string, resumePayload?: Record<string, unknown>) => Promise<void>;
  resumeTaskGraphRun: (taskGraphRunId: string, payload?: Record<string, unknown>) => Promise<void>;
  resolveRuntimeApproval: (taskRunId: string, decision: "approve" | "reject", message?: string) => Promise<void>;
  setTaskSelection: (selection: TaskSelectionState | null) => void;
};

export type AppStore = StoreState &
  StoreActions & {
    editableFiles: string[];
  };

