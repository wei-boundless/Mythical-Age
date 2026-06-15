import { apiRequest, getApiBase, getRuntimeLogEventStreamUrl, getRuntimeMonitorEventStreamUrl } from "./api/client";

export { getApiBase, getRuntimeLogEventStreamUrl, getRuntimeMonitorEventStreamUrl, isRequestAbortError } from "./api/client";

export type ToolCall = {
  tool: string;
  input: string;
  output: string;
};

export type RetrievalResult = {
  text: string;
  score: number;
  source: string;
};

export type SessionSummary = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
  turn_count?: number;
  scope?: SessionScope;
  task_binding?: SessionTaskBinding;
  conversation_state?: ConversationState;
  active_task?: SessionTaskSummary;
};

export type ConversationActiveEnvironment = {
  task_environment_id: string;
  environment_label: string;
  source?: string;
  updated_at?: number;
  authority?: string;
};

export type SessionProjectBinding = {
  workspace_root: string;
  source?: string;
  bound_at?: number;
  last_seen_at?: number;
  immutable?: boolean;
  authority?: string;
};

export type ConversationState = {
  active_task_environment?: ConversationActiveEnvironment;
  project_binding?: SessionProjectBinding;
  permission_mode?: string;
  authority?: string;
};

export type TurnEnvironmentSnapshot = {
  turn_id?: string;
  task_environment_id?: string;
  environment_kind?: string;
  environment_prompt_refs?: string[];
  runtime_assembly_id?: string;
  task_run_id?: string;
  authority?: string;
};

export type SessionTaskBinding = {
  kind: "task_graph" | string;
  graph_run_id: string;
  task_run_id?: string;
  graph_id?: string;
  graph_harness_config_id?: string;
  task_environment_id?: string;
  project_id?: string;
  session_scope?: SessionScope;
  bound_at?: number;
  updated_at?: number;
};

export type SessionScope = {
  workspace_view: string;
  task_environment_id?: string;
  project_id?: string;
};

export type WorkbenchSessionRef = {
  authority?: string;
  session_id?: string;
  sessionId?: string;
  scope?: Partial<SessionScope>;
  pool_key?: string;
  poolKey?: string;
  updated_at?: number;
};

export type WorkbenchCurrentSessionPayload = {
  authority: string;
  current_session: WorkbenchSessionRef | null;
};

export type SessionTaskSummary = {
  available: boolean;
  selection?: "active" | "latest" | string;
  task_run_count: number;
  latest_task_run_id?: string;
  task_run_id?: string;
  task_instance_id?: string;
  task_id?: string;
  kind?: string;
  title?: string;
  summary?: string;
  status?: string;
  lifecycle?: string;
  bucket?: string;
  terminal?: boolean;
  action_required?: boolean;
  stale?: boolean;
  activity_state?: "running" | "waiting" | "paused" | "stopped" | "failed" | "completed" | "stale" | "idle" | string;
  activity_label?: string;
  is_running?: boolean;
  is_waiting?: boolean;
  is_resumable?: boolean;
  is_interruptible?: boolean;
  control_reason?: string;
  recovery_cause?: string;
  tone?: "active" | "neutral" | "attention" | "done" | string;
  activity?: Record<string, unknown>;
  control_capability?: Record<string, unknown>;
  graph_run_id?: string;
  graph_id?: string;
  graph_harness_config_id?: string;
  created_at?: number;
  updated_at?: number;
};

function sessionScopeQuery(scope?: Partial<SessionScope>) {
  const params = new URLSearchParams();
  if (scope?.workspace_view) params.set("workspace_view", scope.workspace_view);
  if (scope?.task_environment_id) params.set("task_environment_id", scope.task_environment_id);
  if (scope?.project_id) params.set("project_id", scope.project_id);
  return params;
}

function withSessionScopeQuery(path: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export type SessionHistory = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  compressed_context?: string;
  scope?: SessionScope;
  task_binding?: SessionTaskBinding;
  conversation_state?: ConversationState;
  messages: Array<{
    id?: string;
    message_id?: string;
    turn_id?: string;
    task_run_id?: string;
    task_id?: string;
    completion_state?: string;
    terminal_reason?: string;
    role: "user" | "assistant";
    content: string;
    turn_environment_snapshot?: TurnEnvironmentSnapshot;
    tool_calls?: ToolCall[];
    answer_channel?: string;
    answer_source?: string;
    answer_canonical_state?: string;
    answer_persist_policy?: string;
    answer_finalization_policy?: string;
    answer_fallback_reason?: string;
    answer_selected_channel?: string;
    answer_selected_source?: string;
    answer_leak_flags?: string[];
    image?: {
      src: string;
      alt?: string;
      caption?: string;
    } | null;
    attachments?: ChatAttachment[];
  }>;
};

export type ChatAttachment = {
  attachment_id: string;
  session_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  path: string;
  created_at: number;
  width?: number;
  height?: number;
  authority?: string;
  storage_authority?: string;
};

export type PublicTodoItem = {
  todo_id?: string;
  content: string;
  active_form?: string;
  status: "pending" | "in_progress" | "completed" | "blocked" | string;
  notes?: string;
};

export type PublicChatTimelineItem = {
  item_id?: string;
  source_item_id?: string;
  kind: "status_update" | "assistant_text" | "opening_judgment" | "todo_plan" | "work_action" | "tool_activity" | "observation_report" | "artifact" | "verification" | "blocked" | "final_summary" | string;
  slot?: "body" | "timeline" | "tool" | "status" | "task" | "control" | string;
  surface?: "assistant_body" | "body" | "tool_window" | "status_bar" | "status" | "timeline" | "control" | string;
  source_authority?: "model" | "runtime" | "tool" | "system" | string;
  event_family?: "assistant_body" | "tool_control" | "runtime_commit" | "turn_anchor_terminal" | "status_trace" | string;
  channel?: "body" | "control" | "commit" | "terminal" | "status" | string;
  status_kind?: string;
  statusKind?: string;
  lossless?: boolean;
  sequence?: number;
  event_offset?: number;
  eventOffset?: number;
  created_at?: number;
  createdAt?: number;
  source_run_id?: string;
  sourceRunId?: string;
  source_event_id?: string;
  sourceEventId?: string;
  source_event_type?: string;
  sourceEventType?: string;
  updated_event_offset?: number;
  updated_at?: number;
  updated_source_event_id?: string;
  action_kind?: "inspect" | "read" | "search" | "edit" | "write" | "run" | "verify" | "memory" | "prepare" | "artifact" | "browse" | "image" | "work" | string;
  tool_lifecycle_id?: string;
  tool_call_id?: string;
  tool_name?: string;
  permission_decision_id?: string;
  arguments_preview?: string;
  target?: string;
  phase?: "running" | "done" | "adjusting" | string;
  phase_ref?: string;
  subject_label?: string;
  public_summary?: string;
  observation?: string;
  next_step?: string;
  title?: string;
  detail?: string;
  text?: string;
  implication?: string;
  recovery_hint?: string;
  tool_window?: {
    tool_label?: string;
    target?: string;
    status?: string;
    command_line?: string;
    output?: string;
    sections?: Array<{
      label?: string;
      text?: string;
    }>;
  };
  href?: string;
  path?: string;
  state?: "running" | "done" | "error" | "ready" | "missing" | "passed" | "failed" | "partial" | string;
  stream_state?: "streaming" | "done" | string;
  collapse_after_body_feedback?: boolean;
  collapsed?: boolean;
  covers_tool_refs?: string[];
  trace_refs?: string[];
  artifacts?: Array<Record<string, unknown>>;
  verified?: string[];
  todo_items?: PublicTodoItem[];
  active_item_id?: string;
  completion_ready?: boolean;
};

export type PublicProjectionItem = {
  itemId: string;
  sourceItemId?: string;
  slot: "current_action" | "pinned" | "final_result" | "status" | "trace" | string;
  text?: string;
  title?: string;
  detail?: string;
  state?: "running" | "done" | "failed" | "blocked" | "waiting" | "stopped" | string;
  statusKind?: string;
  sourceAuthority?: "model" | "tool" | "runtime" | "system" | string;
  eventFamily?: "assistant_body" | "tool_control" | "runtime_commit" | "turn_anchor_terminal" | "status_trace" | string;
  channel?: "body" | "control" | "commit" | "terminal" | "status" | string;
  lossless?: boolean;
  mainVisibility?: "visible_live" | "visible_final" | "pinned" | "trace_only" | "hidden" | string;
  retention?: "transient" | "final" | "pinned_until_resolved" | "trace" | string;
  pinReason?: string;
  toolCallId?: string;
  permissionDecisionId?: string;
  toolName?: string;
  toolLifecycleId?: string;
  actionKind?: string;
  subjectLabel?: string;
  argumentsPreview?: string;
  target?: string;
  traceRefs?: string[];
  artifactRefs?: Array<Record<string, unknown>>;
  collapsed?: boolean;
  eventOffset?: number;
  updatedEventOffset?: number;
  sourceEventType?: string;
  sourceEventId?: string;
};

export type ProjectionLedger = {
  body: {
    text: string;
    stream_state: "streaming" | "finalized" | "committed";
    source_offsets: number[];
    blocks: PublicProjectionBodyBlock[];
  };
  displayCursor?: {
    kind: "body" | "activity";
    itemId?: string;
  };
  currentAction?: PublicProjectionItem;
  pinned: PublicProjectionItem[];
  finalResults: PublicProjectionItem[];
  status: PublicProjectionItem[];
  trace: PublicProjectionItem[];
  timeline: PublicProjectionItem[];
  commit: {
    state: "none" | "checked" | "committed" | "failed" | "skipped";
    key?: string;
  };
  terminal?: {
    state?: string;
    eventOffset?: number;
  };
};

export type PublicProjectionBodyBlock = {
  kind: "body";
  blockId: string;
  text: string;
  firstOffset: number;
  lastOffset: number;
  state?: "streaming" | "finalized" | "committed" | string;
  sourceFrameIds: string[];
};

export type MessagePublicProjection = {
  bodyText: string;
  bodyState: "streaming" | "finalized" | "committed";
  bodyBlocks: PublicProjectionBodyBlock[];
  currentAction?: PublicProjectionItem;
  pinned: PublicProjectionItem[];
  finalResults: PublicProjectionItem[];
  status: PublicProjectionItem[];
  trace: PublicProjectionItem[];
  timeline: PublicProjectionItem[];
  bodyEventOffset?: number;
  traceAvailable: boolean;
  traceCount: number;
  commitState: "none" | "checked" | "committed" | "failed" | "skipped";
};

export type PublicProjectionFrame = {
  authority: "harness.public_projection" | string;
  contract_revision?: "20260614-dual-channel-v1" | string;
  frame_id: string;
  projection_id?: string;
  source_event_id?: string;
  source_event_type?: string;
  sequence?: number;
  event_offset?: number;
  event_family?: "assistant_body" | "tool_control" | "runtime_commit" | "turn_anchor_terminal" | "status_trace" | string;
  channel?: "body" | "control" | "commit" | "terminal" | "status" | string;
  lossless?: boolean;
  created_at?: number;
  anchor?: {
    session_id?: string;
    turn_id?: string;
    message_id?: string;
    task_run_id?: string;
    stream_run_id?: string;
    run_id?: string;
    turn_run_id?: string;
  };
  source_item_id?: string;
  tool_call_id?: string;
  permission_decision_id?: string;
  parent_tool_call_id?: string;
  op:
    | "body_append"
    | "body_finalize"
    | "item_upsert"
    | "item_retire"
    | "scope_retire"
    | "commit_ack"
    | "commit_failed"
    | "turn_terminal"
    | string;
  slot: "body" | "current_action" | "pinned" | "final_result" | "status" | "trace" | string;
  source_authority: "model" | "tool" | "runtime" | "system" | string;
  main_visibility: "visible_live" | "visible_final" | "pinned" | "trace_only" | "hidden" | string;
  retention: "transient" | "final" | "pinned_until_resolved" | "trace" | string;
  pin_reason?: string;
  item_id?: string;
  title?: string;
  text?: string;
  detail?: string;
  state?: "running" | "done" | "failed" | "blocked" | "waiting" | "stopped" | string;
  status_kind?: string;
  tool_name?: string;
  tool_lifecycle_id?: string;
  action_kind?: string;
  subject_label?: string;
  arguments_preview?: string;
  target?: string;
  collapsed?: boolean;
  trace_refs?: string[];
  artifact_refs?: Array<Record<string, unknown>>;
  commit?: {
    state: "checked" | "committed" | "failed" | "skipped" | string;
    commit_event_offset?: number;
    message_id?: string;
    content_sha256?: string;
  };
};

export type PublicChatTimelineDelta = {
  items: PublicChatTimelineItem[];
};

export type TaskEnvironmentSessionResolvePayload = {
  workspace_view?: string;
  project_id?: string;
  intent?: "open_project" | "continue_conversation" | "new_conversation" | "resume_graph" | string;
  title?: string;
  preferred_session_id?: string;
  create_if_missing?: boolean;
  graph_run_id?: string;
  startup_parameters?: Record<string, unknown>;
};

export type TaskEnvironmentSessionResolveResponse = {
  authority: string;
  scope: SessionScope;
  session: SessionSummary | null;
  created: boolean;
  reason: string;
};

export type SessionRuntimeAttachment = {
  attachment_id: string;
  run_id: string;
  stream_run_id?: string;
  event_log_id?: string;
  anchor_turn_id: string;
  anchor_message_id?: string;
  anchor_role?: "assistant" | string;
  turn_run_id?: string;
  task_run_id?: string;
  task_id?: string;
  status: string;
  terminal_reason?: string;
  lifecycle?: string;
  bucket?: string;
  title?: string;
  summary?: string;
  latest_event_type?: string;
  event_count?: number;
  display_state?: "normal_turn" | "task_live" | "task_closed" | "log_only" | string;
  main_chat_surface?: "body_only" | "live_timeline" | "closeout_summary" | "log_only" | string;
  tool_event_count?: number;
  closeout_summary?: string;
  log_ref?: string;
  session_output_commit?: RuntimeMonitorSignal["session_output_commit"];
  projection_anchor?: {
    session_id?: string;
    anchor_turn_id?: string;
    anchor_message_id?: string;
    run_id?: string;
    stream_run_id?: string;
    event_log_id?: string;
    task_run_id?: string;
    turn_run_id?: string;
  };
  public_projection_frames?: PublicProjectionFrame[];
  artifact_refs?: Array<Record<string, unknown>>;
  trace_available?: boolean;
  debug_trace_ref?: string;
  created_at?: number;
  updated_at?: number;
};

export type SessionTimeline = SessionHistory & {
  session_id?: string;
  runtime_attachments?: SessionRuntimeAttachment[];
  authority?: string;
};

export type WorkspaceContext = {
  project_name: string;
  project_root: string;
  backend_root: string;
  storage_root: string;
  editable_prefixes: string[];
  readable_prefixes: string[];
};

export type CodeEnvironmentDiagnostic = {
  level: "info" | "warning" | "error";
  code: string;
  message: string;
  path?: string | null;
};

export type CodeEnvironmentStatus = {
  authority: string;
  host: {
    mode: "web" | "desktop";
    local_runtime_available: boolean;
    code_environment_host_available: boolean;
  };
  pi: {
    available: boolean;
    mode: "web_only" | "desktop_host" | "sidecar_ready" | "sidecar_running" | "error";
    enabled: boolean;
    sidecar_enabled: boolean;
    sidecar_mode: string;
    pi_source_root: string;
    pi_cli_path: string;
    workspace_root: string;
    config_source: string;
    workspace_root_policy: string;
    node_version: string;
    npm_version: string;
    package_name: string;
    coding_agent_package_name: string;
    cli_built: boolean;
    rpc_source_available: boolean;
    diagnostics: CodeEnvironmentDiagnostic[];
  };
};

export type CodeEnvironmentTreeNode = {
  name: string;
  path: string;
  kind: "directory" | "file";
  depth: number;
  children: CodeEnvironmentTreeNode[];
  truncated: boolean;
};

export type CodeEnvironmentWorkspaceTree = {
  authority: string;
  root_name: string;
  root_path: string;
  max_depth: number;
  max_entries: number;
  total_entries: number;
  truncated: boolean;
  tree: CodeEnvironmentTreeNode;
};

export type ProjectWorkspaceSummary = {
  key: string;
  workspace_root: string;
  name: string;
  source: string;
  created_at: number;
  last_seen_at: number;
  session_count: number;
  latest_session_at: number;
  available: boolean;
  authority: string;
};

export type FileChangeRecord = {
  record_id: string;
  session_id: string;
  task_run_id: string;
  agent_run_id: string;
  tool_call_id: string;
  tool_name: string;
  operation_id: string;
  workspace_root: string;
  logical_path: string;
  absolute_path: string;
  before_exists: boolean;
  after_exists: boolean;
  before_sha256: string;
  after_sha256: string;
  before_snapshot_path: string;
  after_snapshot_path: string;
  status: string;
  created_at: number;
  rolled_back_at?: number;
  rollback_error?: string;
  metadata?: Record<string, unknown>;
  authority?: string;
};

export type CodeEnvironmentGitStatus = {
  authority: string;
  available: boolean;
  branch: string;
  items: Array<{ status: string; path: string }>;
  changed_count?: number;
  captured_at?: number;
  cache_status?: "fresh" | "cached" | string;
  diff_stat?: {
    additions?: number;
    deletions?: number;
  };
  gh_available?: boolean;
  ttl_seconds?: number;
  error?: string;
};

export type PiSidecarStatus = {
  running: boolean;
  pid?: number | null;
  workspace_root: string;
  cli_path: string;
  started_at?: number | null;
  last_error: string;
  stderr_tail: string;
};

export type PiSidecarLifecycleResponse = {
  authority: string;
  status: PiSidecarStatus;
};

export type PiSidecarCommandResponse = {
  authority: string;
  command: "get_state" | "get_available_models" | string;
  success: boolean;
  response: Record<string, unknown>;
  error: string;
};

export type AgentTaskConnectionProfile = {
  profile_id: string;
  agent_id: string;
  agent_profile_id: string;
  owner_system: string;
  profile_type: string;
  lifecycle_state: string;
  domain_refs: string[];
  available_task_modes: string[];
  flow_refs: string[];
  binding_refs: string[];
  workflow_refs: string[];
  default_flow_ref: string;
  default_workflow_ref: string;
  validation_state: string;
  blocked_reasons: string[];
  diagnostics: Record<string, unknown>;
};

export type TaskSystemAgentUpsertPayload = {
  agent_id: string;
  agent_name: string;
  agent_category?: string;
  interface_target?: string;
  description?: string;
  enabled?: boolean;
  editable?: boolean;
  default_projection_id?: string;
  metadata?: Record<string, unknown>;
};

export type OrchestrationAgentUpsertPayload = TaskSystemAgentUpsertPayload;

export type TaskSystemNextIds = {
  authority: string;
  task_id: string;
  flow_id: string;
  workflow_id: string;
  graph_id: string;
  display_numbers: {
    task: string;
    flow: string;
    workflow: string;
    graph: string;
  };
};

export type TaskSystemFlowUpsertPayload = {
  flow_id: string;
  title: string;
  input_contract_id?: string;
  output_contract_id?: string;
  default_agent_id: string;
  default_workflow_id?: string;
  default_projection_id?: string;
  default_memory_scope?: string;
  enabled?: boolean;
  metadata?: Record<string, unknown>;
};

export type ConversationEntryPolicy = {
  profile_id: string;
  entry_policy_id?: string;
  title: string;
  default_workflow_id: string;
  default_projection_id?: string;
  input_contract_id: string;
  output_contract_id: string;
  conversation_entry_policy: string;
  enabled: boolean;
  authority?: string;
  metadata?: Record<string, unknown>;
};

export type SpecificTaskRecord = {
  task_id: string;
  task_title: string;
  domain_id?: string;
  task_mode?: string;
  description: string;
  input_contract_id: string;
  output_contract_id: string;
  acceptance_profile_id: string;
  default_flow_contract_id: string;
  default_workflow_id: string;
  default_projection_policy: string;
  task_policy: Record<string, unknown>;
  enabled: boolean;
  metadata?: Record<string, unknown>;
};

export type EngagementAssignee = {
  kind: "agent" | "workflow" | "human" | "system" | string;
  agent_id?: string;
  agent_profile_id?: string;
  workflow_id?: string;
  participant_agent_ids?: string[];
};

export type EngagementRuntimeProfile = {
  runtime_policy?: Record<string, unknown>;
};

export type EngagementExecutionStrategy = {
  kind: "graph_task_run" | string;
  startup_policy?: Record<string, unknown>;
  lifecycle_policy?: Record<string, unknown>;
};

export type RegisteredEngagementPlan = {
  plan_id: string;
  title: string;
  description: string;
  version: string;
  status: "draft" | "active" | "deprecated" | "disabled" | "archived" | string;
  task_environment_id: string;
  assignee: EngagementAssignee;
  runtime_profile: EngagementRuntimeProfile;
  execution_strategy: EngagementExecutionStrategy;
  input_contract: Record<string, unknown>;
  output_contract: Record<string, unknown>;
  prompt_contract: Record<string, unknown>;
  resource_requirements: Record<string, unknown>;
  capability_requirements: Record<string, unknown>;
  memory_requirements: Record<string, unknown>;
  acceptance_policy: Record<string, unknown>;
  recovery_policy: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  supersedes_plan_id: string;
  metadata?: Record<string, unknown>;
  authority?: string;
};

export type EngagementRunRecord = {
  engagement_run_id: string;
  request_id: string;
  contract_id: string;
  plan_id: string;
  plan_version: string;
  strategy_kind: string;
  status: string;
  task_run_id: string;
  turn_result_ref: string;
  workflow_run_id: string;
  human_gate_id: string;
  artifact_refs: Array<Record<string, unknown>>;
  verification_refs: Array<Record<string, unknown>>;
  closeout: Record<string, unknown>;
  authority?: string;
};

export type EngagementEventRecord = {
  engagement_run_id: string;
  event_type: string;
  summary: string;
  payload_ref?: string;
  user_visible?: boolean;
  created_at?: string;
  authority?: string;
};

export type TaskDomainRecord = {
  domain_id: string;
  title: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  metadata?: Record<string, unknown>;
};

export type TaskFlowContractBinding = {
  binding_id?: string;
  task_id: string;
  flow_contract_id: string;
  override_policy: string;
  verification_gate_profile: string;
  fallback_policy: string;
  metadata?: Record<string, unknown>;
};

export type TaskExecutionPolicy = {
  plan_id?: string;
  execution_policy_id?: string;
  task_id: string;
  execution_chain_type: string;
  runtime_agent_selection_policy?: string;
  default_agent_id: string;
  task_level?: string;
  task_privilege?: string;
  allow_worker_agent_spawn: boolean;
  worker_agent_blueprint_id: string;
  worker_agent_naming_rule: string;
  notes: string;
  authority?: string;
  metadata?: Record<string, unknown>;
};

export type TaskContractDescriptor = {
  contract_id: string;
  title: string;
  contract_kind: string;
  summary: string;
  source_refs: string[];
  usage_refs: string[];
  editable: boolean;
  status: string;
  metadata?: Record<string, unknown>;
};

export type ContractField = {
  field_id: string;
  title_zh: string;
  field_type: string;
  required: boolean;
  description: string;
  default_value?: unknown;
  schema: Record<string, unknown>;
  source_hint: string;
  visibility: string;
};

export type ArtifactRequirement = {
  requirement_id: string;
  title_zh: string;
  artifact_type: string;
  required: boolean;
  description: string;
  naming_rule: string;
  storage_policy: string;
  metadata?: Record<string, unknown>;
};

export type AcceptanceRule = {
  rule_id: string;
  title_zh: string;
  rule_type: string;
  severity: string;
  target_field: string;
  criteria: string;
  config: Record<string, unknown>;
};

export type RuntimeRequirement = {
  requirement_id: string;
  title_zh: string;
  requirement_type: string;
  required: boolean;
  value: string;
  config: Record<string, unknown>;
};

export type ContextVisibilityPolicy = {
  main_session_history: string;
  upstream_outputs: string;
  sibling_nodes: string;
  artifact_access: string;
  memory_scopes: string[];
  model_visible_sections: string[];
  hidden_sections: string[];
  notes?: string;
  metadata?: Record<string, unknown>;
};

export type HandoffPolicy = {
  handoff_mode: string;
  include_artifact_refs: boolean;
  include_raw_messages: boolean;
  ack_required: boolean;
  timeout_policy: string;
  metadata?: Record<string, unknown>;
};

export type FailurePolicy = {
  failure_mode: string;
  retry_allowed: boolean;
  retry_limit: number;
  escalate_to: string;
  fallback_contract_id: string;
  metadata?: Record<string, unknown>;
};

export type HumanGatePolicy = {
  required: boolean;
  gate_type: string;
  reviewer_role: string;
  decision_contract_id: string;
  metadata?: Record<string, unknown>;
};

export type ContractSpec = {
  contract_id: string;
  title_zh: string;
  title_en: string;
  contract_kind: string;
  description: string;
  input_fields: ContractField[];
  output_fields: ContractField[];
  artifact_requirements: ArtifactRequirement[];
  acceptance_rules: AcceptanceRule[];
  runtime_requirements: RuntimeRequirement[];
  context_visibility_policy: ContextVisibilityPolicy;
  handoff_policy: HandoffPolicy;
  failure_policy: FailurePolicy;
  human_gate_policy: HumanGatePolicy;
  allowed_agent_kinds: string[];
  version: string;
  enabled: boolean;
  metadata?: Record<string, unknown>;
};

export type ContractValidationIssue = {
  contract_id: string;
  field: string;
  reason: string;
  severity: string;
  message: string;
};

export type ContractCompileIssue = {
  code: string;
  message: string;
  severity: string;
  source_ref: string;
  contract_id: string;
  node_id: string;
  edge_id: string;
  agent_id: string;
};

export type RuntimeContextSection = {
  section_id: string;
  title: string;
  visibility: string;
  content_mode: string;
  source_ref: string;
  model_visible: boolean;
  metadata?: Record<string, unknown>;
};

export type TaskGraphDraftTopologySpec = {
  graph_id: string;
  domain_id: string;
  coordinator_agent_id: string;
  agent_group_id?: string;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  subtask_refs: string[];
  communication_modes: string[];
  start_node_ids: string[];
  terminal_node_ids: string[];
  resource_nodes?: Array<Record<string, unknown>>;
  temporal_edges?: Array<Record<string, unknown>>;
  memory_edges?: Array<Record<string, unknown>>;
  artifact_context_edges?: Array<Record<string, unknown>>;
  revision_edges?: Array<Record<string, unknown>>;
  loop_frames?: Array<Record<string, unknown>>;
  graph_module_expansion_plans?: Array<Record<string, unknown>>;
  graph_modules?: Array<Record<string, unknown>>;
  issues: Array<Record<string, unknown>>;
  valid: boolean;
  diagnostics?: Record<string, unknown>;
};

export type GraphHarnessConfigPayload = {
  authority: string;
  config_id: string;
  graph_id: string;
  graph_title: string;
  publish_version: string;
  status: string;
  content_hash: string;
  task_environment_id?: string;
  root_task_ref?: string;
  control: Record<string, unknown>;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  loop_frames?: Array<Record<string, unknown>>;
  environment?: Record<string, unknown>;
  resources?: Record<string, unknown>;
  memory?: Record<string, unknown>;
  artifacts?: Record<string, unknown>;
  permissions?: Record<string, unknown>;
  tools?: Record<string, unknown>;
  agents?: Record<string, unknown>;
  contracts?: Record<string, unknown>;
  composition_sources?: Array<Record<string, unknown>>;
  diagnostics?: Record<string, unknown>;
  authority_map?: Record<string, unknown>;
  source_refs?: Record<string, unknown>;
};

export type GraphSchedulerViewPayload = {
  authority: string;
  config_id: string;
  config_hash: string;
  dependency_edges: Array<Record<string, unknown>>;
  executable_node_ids: string[];
  start_node_ids: string[];
  terminal_node_ids: string[];
  diagnostics: Record<string, unknown>;
};

export type TaskGraphContractPreview = {
  authority: string;
  contract_id: string;
  graph_id: string;
  title: string;
  valid: boolean;
  graph_harness_config: GraphHarnessConfigPayload;
  scheduler_view: GraphSchedulerViewPayload;
  composition_sources?: Array<Record<string, unknown>>;
  split_plans?: Array<Record<string, unknown>>;
  object_trace_index?: Array<Record<string, unknown>>;
  issues: Array<Record<string, unknown>>;
  summary: Record<string, number | string | boolean>;
};

export type TaskGraphStandardNodeSpec = {
  node_id: string;
  title: string;
  node_type: string;
  task_id?: string;
  phase_id?: string;
  sequence_index?: number;
  timeline_group_id?: string;
  main_chain?: boolean;
  blocks_phase_exit?: boolean;
  executor?: Record<string, unknown>;
  contracts?: Record<string, unknown>;
  context?: Record<string, unknown>;
  runtime?: Record<string, unknown>;
  artifacts?: Record<string, unknown>;
  loop?: Record<string, unknown>;
  resource?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type TaskGraphStandardEdgeSpec = {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
  payload_contract_id?: string;
  contract_bindings?: Record<string, unknown>;
  handoff?: Record<string, unknown>;
  semantic?: Record<string, unknown>;
  memory?: Record<string, unknown>;
  artifact_context?: Record<string, unknown>;
  revision?: Record<string, unknown>;
  temporal?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type TaskGraphStandardResourceSpec = {
  node_id: string;
  title: string;
  resource_type: string;
  repository_id: string;
  collections: string[];
  collection_specs?: Array<Record<string, unknown>>;
  lifecycle?: Record<string, unknown>;
  readable_by?: string[];
  write_owner_node_ids?: string[];
  metadata?: Record<string, unknown>;
};

export type TaskGraphStandardTimelineSpec = {
  entry_node_id: string;
  output_node_id: string;
  temporal_edges: Array<Record<string, unknown>>;
  loop_frames: Array<Record<string, unknown>>;
  timeline_blocks?: Array<Record<string, unknown>>;
  phases: Array<Record<string, unknown>>;
  scheduler?: Record<string, unknown>;
  runtime_semantics?: Record<string, unknown>;
};

export type TaskGraphRuntimeIsolationSpec = {
  task_run_scope_policy: string;
  memory_repositories: Array<Record<string, unknown>>;
  artifact_repositories: Array<Record<string, unknown>>;
  runtime_state_stores: Array<Record<string, unknown>>;
};

export type TaskGraphMemoryProtocolRepository = {
  repository_id: string;
  repository_node_id?: string;
  title?: string;
  repository_kind?: string;
  lifecycle_policy?: Record<string, unknown>;
  scope_policy?: Record<string, unknown>;
  mutable?: boolean;
  authority?: string;
};

export type TaskGraphMemoryProtocolCollection = {
  repository_id: string;
  repository_node_id?: string;
  collection_id: string;
  title?: string;
  schema_id?: string;
  record_kinds?: string[];
  key_strategy?: string;
  default_version_selector?: string;
  content_requirement?: Record<string, unknown>;
  snapshot_budget?: Record<string, unknown>;
  retention_policy?: Record<string, unknown>;
  authority?: string;
};

export type TaskGraphMemoryProtocolEdge = {
  edge_id: string;
  operation: "read" | "write" | "write_candidate" | "commit" | string;
  source_node_id?: string;
  target_node_id?: string;
  repository_id: string;
  collection_id: string;
  address?: Record<string, unknown>;
  selector?: Record<string, unknown>;
  version_selector?: string;
  missing_policy?: string;
  source_output_key?: string;
  candidate_ref_key?: string;
  verdict_key?: string;
  required_verdict?: string;
  approval_source_node_id?: string;
  commit_visibility_policy?: Record<string, unknown>;
  content_requirement?: Record<string, unknown>;
  materialization_policy?: Record<string, unknown>;
  model_visible_label?: string;
  usage_instruction?: string;
  authority?: string;
};

export type TaskGraphMemoryProtocol = {
  authority?: string;
  repositories: TaskGraphMemoryProtocolRepository[];
  collections: TaskGraphMemoryProtocolCollection[];
  read_edges: TaskGraphMemoryProtocolEdge[];
  write_edges: TaskGraphMemoryProtocolEdge[];
  commit_edges: TaskGraphMemoryProtocolEdge[];
  issues: Array<Record<string, unknown>>;
  summary?: Record<string, unknown>;
};

export type UnitPortSpec = {
  port_id: string;
  title: string;
  direction: "input" | "output" | string;
  payload_contract_id?: string;
  required?: boolean;
  status_required?: string;
  visibility_policy?: string;
  metadata?: Record<string, unknown>;
};

export type UnitInterfaceSpec = {
  interface_id: string;
  unit_id: string;
  display_name_zh: string;
  input_ports: UnitPortSpec[];
  output_ports: UnitPortSpec[];
  memory_visibility_policy?: string;
  artifact_visibility_policy?: string;
  runtime_state_policy?: string;
  version?: string;
  metadata?: Record<string, unknown>;
};

export type ComposableUnitSpec = {
  unit_id: string;
  unit_type: "node" | "graph" | "resource" | "human_gate" | "tool" | "runtime_monitor" | string;
  title: string;
  ref?: Record<string, unknown>;
  interface_id?: string;
  runtime_policy?: Record<string, unknown>;
  phase_id?: string;
  sequence_index?: number;
  source_kind?: string;
  metadata?: Record<string, unknown>;
};

export type UnitPortEdgeSpec = {
  edge_id: string;
  source_unit_id: string;
  source_port_id: string;
  target_unit_id: string;
  target_port_id: string;
  payload_contract_id?: string;
  edge_type?: string;
  temporal_semantics?: Record<string, unknown>;
  handoff?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type GraphModuleExpansionPlanSpec = {
  plan_id: string;
  importing_graph_id: string;
  unit_id: string;
  linked_graph_id: string;
  version_ref?: string;
  handoff_contract_id?: string;
  input_port_id?: string;
  output_port_id?: string;
  runtime_node_id?: string;
  scope_prefix?: string;
  isolation_policy?: string;
  visibility_policy?: string;
  detach_policy?: string;
  metadata?: Record<string, unknown>;
};

export type GraphModuleExpansionSpec = {
  plan_id: string;
  runtime_node_id: string;
  unit_id: string;
  linked_graph_id: string;
  scope_prefix: string;
  imported_graph?: Record<string, unknown>;
  entry_node_id?: string;
  output_node_id?: string;
  nodes?: Array<Record<string, unknown> & { scoped_node_id?: string; node_id?: string; title?: string; node_type?: string; phase_id?: string }>;
  edges?: Array<Record<string, unknown> & { scoped_edge_id?: string; edge_id?: string; scoped_source_node_id?: string; scoped_target_node_id?: string; source_node_id?: string; target_node_id?: string; edge_type?: string; payload_contract_id?: string }>;
  resources?: Array<Record<string, unknown> & { scoped_node_id?: string; node_id?: string; title?: string; resource_type?: string; repository_id?: string }>;
  issues?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
};

export type TaskGraphStandardIssue = {
  code: string;
  message: string;
  severity: string;
  node_id?: string;
  edge_id?: string;
  unit_id?: string;
  source?: string;
};

export type TaskGraphLoopPlanEdgePreview = {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
  semantic_role?: string;
  scheduler_role?: string;
  runtime_role?: string;
};

export type TaskGraphLoopPlanFramePreview = {
  frame_id: string;
  scope_id?: string;
  kind?: string;
  entry_node_id?: string;
  router_node_id?: string;
  continue_node_id?: string;
  exit_node_id?: string;
  initial_input_keys?: string[];
  derived_field_count?: number;
};

export type TaskGraphLoopPlanPreview = {
  available: boolean;
  authority: string;
  graph_id?: string;
  config_id?: string;
  config_hash?: string;
  start_node_ids: string[];
  terminal_node_ids: string[];
  executable_node_ids: string[];
  initial_ready_node_ids: string[];
  dependency_edges: TaskGraphLoopPlanEdgePreview[];
  context_edges: TaskGraphLoopPlanEdgePreview[];
  commit_edges: TaskGraphLoopPlanEdgePreview[];
  revision_edges: TaskGraphLoopPlanEdgePreview[];
  loop_frames: TaskGraphLoopPlanFramePreview[];
  execution_levels?: Array<Record<string, unknown> & { level_index?: number; node_ids?: string[]; status?: string }>;
  summary?: Record<string, unknown>;
  issues?: Array<Record<string, unknown> & { code?: string; message?: string; severity?: string }>;
};

export type TaskGraphStandardView = {
  authority: string;
  graph: Record<string, unknown>;
  nodes: TaskGraphStandardNodeSpec[];
  edges: TaskGraphStandardEdgeSpec[];
  resources: TaskGraphStandardResourceSpec[];
  units?: ComposableUnitSpec[];
  interfaces?: UnitInterfaceSpec[];
  port_edges?: UnitPortEdgeSpec[];
  graph_module_expansion?: GraphModuleExpansionPlanSpec[];
  graph_module_expansions?: GraphModuleExpansionSpec[];
  timeline: TaskGraphStandardTimelineSpec;
  runtime_isolation: TaskGraphRuntimeIsolationSpec;
  memory_matrix: Record<string, unknown>;
  memory_protocol?: TaskGraphMemoryProtocol;
  diagnostics: Record<string, unknown> & { loop_plan?: TaskGraphLoopPlanPreview };
  issues: TaskGraphStandardIssue[];
};

export type TaskGraphNodeRecord = {
  node_id: string;
  node_type: string;
  title: string;
  node_config_id?: string;
  node_config_overrides?: Record<string, unknown>;
  task_id?: string;
  agent_id?: string;
  agent_selection_policy?: string;
  agent_group_id?: string;
  role?: string;
  work_posture?: string;
  contract_id?: string;
  node_contract_id?: string;
  input_contract_id?: string;
  output_contract_id?: string;
  contract_bindings?: Record<string, unknown>;
  context_visibility_policy?: Record<string, unknown>;
  executor_policy?: Record<string, unknown>;
  failure_policy?: Record<string, unknown>;
  human_gate_policy?: Record<string, unknown>;
  memory_read_policy?: Record<string, unknown>;
  memory_writeback_policy?: Record<string, unknown>;
  dynamic_memory_read_policy?: Record<string, unknown>;
  execution_mode?: "sync" | "async" | "parallel" | "background" | "barrier" | "manual_gate" | string;
  dispatch_group?: string;
  wait_policy?: string;
  join_policy?: string;
  phase_id?: string;
  sequence_index?: number;
  timeline_group_id?: string;
  main_chain?: boolean;
  start_policy?: string;
  completion_policy?: string;
  blocks_phase_exit?: boolean;
  loop?: Record<string, unknown>;
  review_gate_policy?: Record<string, unknown>;
  artifact_policy?: Record<string, unknown>;
  stream_policy?: Record<string, unknown>;
  artifact_target?: string;
  output_path?: string;
  background_policy?: Record<string, unknown>;
  notification_policy?: Record<string, unknown>;
  resource_lifecycle_policy?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type TaskGraphEdgeRecord = {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
  a2a_message_type?: string;
  contract_id?: string;
  payload_contract_id?: string;
  contract_bindings?: Record<string, unknown>;
  context_filter_policy?: Record<string, unknown>;
  artifact_ref_policy?: Record<string, unknown>;
  working_memory_handoff_policy?: Record<string, unknown>;
  ack_policy?: string;
  timeout_policy?: string;
  wait_policy?: string;
  ack_required?: boolean;
  failure_propagation_policy?: string;
  result_delivery_policy?: string;
  failure_policy?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type TaskGraphRecord = {
  graph_id: string;
  title: string;
  domain_id?: string;
  graph_kind: "single_agent" | "multi_agent" | "coordination";
  entry_node_id: string;
  output_node_id: string;
  nodes: TaskGraphNodeRecord[];
  edges: TaskGraphEdgeRecord[];
  node_count?: number;
  edge_count?: number;
  graph_contract_id?: string;
  contract_bindings?: Record<string, unknown>;
  default_protocol_id?: string;
  working_memory_policy_profile_id?: string;
  working_memory_policy?: Record<string, unknown>;
  runtime_policy?: Record<string, unknown>;
  context_policy?: Record<string, unknown>;
  loop_frames?: Array<Record<string, unknown>>;
  publish_state: "draft" | "published" | "archived";
  enabled: boolean;
  metadata?: Record<string, unknown>;
  issues?: Array<Record<string, unknown>>;
  issue_count?: number;
  error_count?: number;
  warning_count?: number;
  valid?: boolean;
  overview_mode?: string;
};

export type TaskCommunicationProtocol = {
  protocol_id: string;
  title: string;
  message_types: string[];
  payload_contracts: string[];
  signal_rules: string[];
  handoff_rules: string[];
  ack_policy: string;
  timeout_policy: string;
  error_signal_policy: string;
  enabled: boolean;
  metadata?: Record<string, unknown>;
};

export type AgentTaskCarryingProfile = {
  agent_id: string;
  display_name: string;
  profile_type: string;
  owner_system: string;
  lifecycle_state: string;
  carried_general_task_refs: string[];
  carried_specific_task_refs: string[];
  workflow_refs: string[];
  validation_state: string;
  blocked_reasons: string[];
  diagnostics: Record<string, unknown>;
};

export type TaskConnectionDiagnosticIssue = {
  object_id: string;
  object_type: string;
  reason: string;
  field: string;
  value?: string;
  severity: string;
};

export type ConversationEntryPolicyUpsertPayload = ConversationEntryPolicy;
export type TaskDomainUpsertPayload = TaskDomainRecord;
export type EngagementPlanUpsertPayload = RegisteredEngagementPlan;
export type EngagementPlanListResponse = {
  authority: string;
  engagement_plans: RegisteredEngagementPlan[];
  summary: Record<string, number>;
};
export type EngagementPlanDetailResponse = {
  authority: string;
  engagement_plan: RegisteredEngagementPlan;
};
export type EngagementStartPayload = {
  session_id?: string;
  startup_parameters?: Record<string, unknown>;
};
export type EngagementStartResult = {
  authority: string;
  decision: string;
  engagement_contract_ref?: string;
  engagement_contract?: Record<string, unknown>;
  admission?: Record<string, unknown>;
  task_run?: Record<string, unknown>;
  errors?: string[];
};
export type EngagementRunListResponse = {
  authority: string;
  engagement_runs: EngagementRunRecord[];
  engagement_events: EngagementEventRecord[];
  summary: Record<string, number>;
};
export type EngagementRunDetailResponse = {
  authority: string;
  engagement_run: EngagementRunRecord;
  engagement_events: EngagementEventRecord[];
};
export type EngagementRunCloseoutSyncResult = {
  authority?: string;
  changed: boolean;
  reason?: string;
  task_run_status?: string;
  engagement_run: EngagementRunRecord;
  closeout?: Record<string, unknown>;
};
export type TaskFlowContractBindingUpsertPayload = TaskFlowContractBinding;
export type TaskExecutionPolicyUpsertPayload = TaskExecutionPolicy;
export type ContractSpecUpsertPayload = ContractSpec;
export type TaskEnvironmentGroupUpsertPayload = {
  group_id: string;
  title: string;
  description?: string;
  enabled?: boolean;
};
export type TaskEnvironmentKindTemplate = {
  kind_id: string;
  title: string;
  description?: string;
  group_id?: string;
  allowed_resource_refs?: string[];
  default_sandbox_policy?: Record<string, unknown>;
  default_execution_policy?: Record<string, unknown>;
  default_risk_policy?: Record<string, unknown>;
  default_prompt_cache_scope?: string;
  allowed_task_graph_kinds?: string[];
  enabled?: boolean;
  metadata?: Record<string, unknown>;
};
export type TaskEnvironmentKindTemplateUpsertPayload = TaskEnvironmentKindTemplate;
export type TaskEnvironmentUpsertPayload = {
  record?: Record<string, unknown>;
  spec?: Record<string, unknown>;
  environment_id?: string;
  title?: string;
  description?: string;
  group_id?: string;
  environment_kind?: string;
  enabled?: boolean;
  owner?: string;
  default_visibility?: string;
  environment_prompts?: Array<Record<string, unknown>>;
  sandbox_policy?: Record<string, unknown>;
  file_management?: Record<string, unknown>;
  resource_space?: Record<string, unknown>;
  memory_space?: Record<string, unknown>;
  execution_policy?: Record<string, unknown>;
  risk_policy?: Record<string, unknown>;
  artifact_policy?: Record<string, unknown>;
  observability_policy?: Record<string, unknown>;
  lifecycle_policy?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};
export type TaskAssignmentUpsertPayload = {
  task_id: string;
  task_title: string;
  task_kind?: string;
  flow_id?: string;
  domain_id?: string;
  task_environment_id?: string;
  default_agent_id?: string;
  participant_agent_ids?: string[];
  workflow_id?: string;
  workflow_file_ref?: string;
  input_contract_id?: string;
  output_contract_id?: string;
  safety_policy?: Record<string, unknown>;
  task_structure?: Record<string, unknown>;
  enabled?: boolean;
  metadata?: Record<string, unknown>;
};

export type ProjectInstance = {
  project_id: string;
  environment_id: string;
  title: string;
  project_kind: string;
  template_id?: string;
  library_id: string;
  lifecycle_state: string;
  schema_version: string;
  created_at?: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
  authority?: string;
};

export type ProjectRepositoryBinding = {
  repository_id: string;
  role: string;
  root_ref: string;
  lifecycle: string;
  readable: boolean;
  writable: boolean;
  searchable: boolean;
  commit_gate?: string;
  metadata?: Record<string, unknown>;
};

export type ProjectLifecycleActionSpec = {
  action_id: string;
  title: string;
  operation: string;
  description?: string;
  enabled: boolean;
  requires_confirmation: boolean;
  selectors?: Record<string, unknown>;
  safeguards?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  authority?: string;
};

export type ProjectLibraryManifest = {
  library_id: string;
  project_id: string;
  environment_id: string;
  file_profile_id: string;
  schema_version: string;
  template_id?: string;
  repositories: ProjectRepositoryBinding[];
  lifecycle_actions?: ProjectLifecycleActionSpec[];
  indexes: Record<string, string>;
  migration_log: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
  authority?: string;
};

export type ProjectLibraryPayload = {
  authority: string;
  project: ProjectInstance;
  library: ProjectLibraryManifest;
};

export type ProjectLibraryRepository = {
  repository_id: string;
  repository_kind: string;
  title: string;
  readable?: boolean;
  writable?: boolean;
  searchable?: boolean;
  project_role?: string;
  project_root_ref?: string;
  project_lifecycle?: string;
  selected_roles?: string[];
  metadata?: Record<string, unknown>;
};

export type ProjectRepositoriesPayload = {
  authority: string;
  project_id: string;
  library_id: string;
  repositories: ProjectLibraryRepository[];
  summary: Record<string, number>;
};

export type ProjectTreeNode = {
  name: string;
  path: string;
  kind: "directory" | "file";
  depth: number;
  children: ProjectTreeNode[];
  truncated: boolean;
};

export type ProjectFileTreePayload = {
  authority: string;
  project_id: string;
  library_id: string;
  repository_id: string;
  path: string;
  total_entries: number;
  truncated: boolean;
  tree: ProjectTreeNode;
};

export type ProjectFilePayload = {
  authority: string;
  project_id: string;
  library_id: string;
  repository_id: string;
  path: string;
  content: string;
  metadata?: Record<string, unknown>;
};

export type ProjectLifecycleActionsPayload = {
  authority: string;
  project_id: string;
  actions: ProjectLifecycleActionSpec[];
  summary: Record<string, number>;
};

export type ProjectLifecyclePreviewPayload = {
  authority: string;
  project_id: string;
  action: string;
  action_spec?: ProjectLifecycleActionSpec;
  preview: {
    task_ids?: string[];
    flow_ids?: string[];
    counts?: Record<string, number>;
    preserved?: Record<string, boolean>;
    [key: string]: unknown;
  };
};

export type ProjectLifecycleRunPayload = {
  authority: string;
  run: {
    run_id: string;
    project_id: string;
    action: string;
    status: string;
    preview: Record<string, unknown>;
    result: Record<string, unknown>;
    created_at?: string;
    updated_at?: string;
    metadata?: Record<string, unknown>;
  };
};

export type TaskEnvironmentTasksPayload = {
  authority: string;
  environment_id: string;
  tasks: Array<Record<string, unknown>>;
  summary: Record<string, number>;
};
export type TaskNodeConfigurationSpec = {
  node_config_id: string;
  title: string;
  description?: string;
  node_kind?: string;
  environment_scope?: string[];
  role_prompt?: string;
  executor_ref?: Record<string, unknown>;
  contract_bindings?: Record<string, unknown>;
  model_requirements?: Record<string, unknown>;
  tool_policy?: Record<string, unknown>;
  memory_policy?: Record<string, unknown>;
  artifact_policy?: Record<string, unknown>;
  failure_policy?: Record<string, unknown>;
  human_gate_policy?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  enabled?: boolean;
};
export type TaskNodeConfigurationUpsertPayload = TaskNodeConfigurationSpec;

export type TaskGraphUpsertPayload = TaskGraphRecord;
export type TaskGraphStandardViewUpsertPayload = {
  graph: Record<string, unknown>;
  nodes: TaskGraphStandardNodeSpec[];
  edges: TaskGraphStandardEdgeSpec[];
  resources?: TaskGraphStandardResourceSpec[];
  timeline?: Partial<TaskGraphStandardTimelineSpec>;
  runtime_isolation?: Partial<TaskGraphRuntimeIsolationSpec>;
  metadata?: Record<string, unknown>;
};

export type TaskAgentConnectionOverview = {
  authority: string;
  profiles: AgentTaskConnectionProfile[];
  summary: {
    profile_count: number;
    invalid_profile_count: number;
    domain_count: number;
  };
  diagnostics: Record<string, unknown>;
};

export type TaskEnvironmentCatalog = {
  authority: string;
  groups?: Array<{
    group_id: string;
    title: string;
    description?: string;
    enabled?: boolean;
  }>;
  environments: Array<{
    record: {
      environment_id: string;
      title: string;
      description?: string;
      group_id?: string;
      enabled?: boolean;
      owner?: string;
      environment_kind?: string;
      default_visibility?: string;
      definition_source?: string;
      management_scope?: string;
      metadata?: Record<string, unknown>;
    };
    spec: Record<string, unknown>;
    definition_source?: string;
    management_scope?: string;
    group?: Record<string, unknown>;
    environment_prompts?: Array<Record<string, unknown>>;
    environment_boundary?: Record<string, unknown>;
    sandbox_policy?: Record<string, unknown>;
    storage_space?: Record<string, unknown>;
    resource_space?: Record<string, unknown>;
    file_management?: Record<string, unknown>;
    file_access_tables?: Array<Record<string, unknown>>;
    memory_space?: Record<string, unknown>;
    artifact_policy?: Record<string, unknown>;
    execution_policy?: Record<string, unknown>;
    risk_policy?: Record<string, unknown>;
    observability_policy?: Record<string, unknown>;
    lifecycle_policy?: Record<string, unknown>;
    task_library?: {
      environment_id: string;
      engagement_plan_ids?: string[];
      task_ids: string[];
      task_count: number;
      task_library_root?: string;
      authority?: string;
    };
  }>;
  records: Array<{
    environment_id: string;
    title: string;
    description?: string;
    group_id?: string;
    enabled?: boolean;
    owner?: string;
    environment_kind?: string;
    default_visibility?: string;
    definition_source?: string;
    management_scope?: string;
    metadata?: Record<string, unknown>;
  }>;
  summary: Record<string, number>;
};

export type TaskSystemOverview = {
  authority: string;
  summary: Record<string, number>;
  task_environment_management?: TaskEnvironmentCatalog;
  project_instance_management?: {
    authority: string;
    projects: ProjectInstance[];
    by_environment?: Record<string, ProjectInstance[]>;
    summary: Record<string, number>;
  };
  task_management: {
    entry_policies: ConversationEntryPolicy[];
    task_domains: TaskDomainRecord[];
    engagement_plans: RegisteredEngagementPlan[];
    specific_task_records: SpecificTaskRecord[];
    task_flow_definitions: TaskSystemFlowUpsertPayload[];
    workflow_resources: TaskWorkflowRecord[];
    flow_contract_bindings: TaskFlowContractBinding[];
    execution_policies: TaskExecutionPolicy[];
    contract_catalog?: TaskContractDescriptor[];
    task_assignments?: Array<Record<string, unknown>>;
  };
  environment_kind_management?: {
    authority: string;
    kind_templates: TaskEnvironmentKindTemplate[];
    summary: Record<string, number>;
  };
  environment_task_inventory?: {
    authority: string;
    items: Array<Record<string, unknown>>;
    by_environment?: Record<string, Array<Record<string, unknown>>>;
    summary: Record<string, number>;
  };
  environment_graph_inventory?: {
    authority: string;
    items: Array<Record<string, unknown>>;
    by_environment?: Record<string, Array<Record<string, unknown>>>;
    summary: Record<string, number>;
  };
  contract_management?: {
    authority: string;
    contract_specs: ContractSpec[];
    contract_families?: Array<Record<string, unknown>>;
    contract_family_catalog?: Record<string, unknown>;
    contract_kind_options: string[];
    field_type_options: string[];
    source_hint_options: string[];
    visibility_options: string[];
    acceptance_rule_type_options: string[];
    validation_issues: ContractValidationIssue[];
    summary: Record<string, number>;
  };
  contract_usage_index?: {
    authority: string;
    by_contract_id: Record<string, Array<Record<string, unknown>>>;
    summary: Record<string, number>;
  };
  node_configuration_management?: {
    authority: string;
    node_configurations: TaskNodeConfigurationSpec[];
    usage_index?: Record<string, Array<Record<string, unknown>>>;
    issues?: Array<Record<string, unknown>>;
    summary: Record<string, number>;
  };
  task_graph_management?: {
    task_graphs: TaskGraphRecord[];
    task_graph_specs?: TaskGraphDraftTopologySpec[];
    semantic_relation_catalog?: Record<string, unknown>;
    semantic_relations?: Array<Record<string, unknown>>;
    communication_protocols?: TaskCommunicationProtocol[];
    a2a?: {
      protocol_version: string;
      transport: string;
      protocol_locked: boolean;
      agent_cards: Array<Record<string, unknown>>;
      message_types: string[];
      part_types: string[];
      task_states: string[];
    };
  };
  diagnostics?: Record<string, unknown>;
};

export type CapabilitySystemAgentCatalog = {
  authority: string;
  agents: Array<Record<string, unknown>>;
  summary: Record<string, number>;
};

export type ToolPackageSelection = {
  package_id: string;
  enabled: boolean;
  include_operations: string[];
  exclude_operations: string[];
};

export type OrchestrationAgentRuntimeProfile = {
  agent_profile_id: string;
  agent_id: string;
  allowed_tool_packages?: ToolPackageSelection[];
  extra_allowed_operations?: string[];
  allowed_operations: string[];
  final_allowed_operations?: string[];
  blocked_operations: string[];
  allowed_memory_scopes: string[];
  allowed_context_sections: string[];
  subagent_policy: OrchestrationSubagentPolicy;
  approval_policy: string;
  trace_policy: string;
  lifecycle_policy: string;
  model_profile?: OrchestrationAgentModelProfile;
  metadata?: Record<string, unknown>;
};

export type OrchestrationAgentModelProfile = {
  profile_id?: string;
  display_name?: string;
  provider?: string;
  model?: string;
  credential_ref?: string;
  max_output_tokens?: number | null;
  timeout_seconds?: number | null;
  long_output_timeout_seconds?: number | null;
  max_retries?: number | null;
  temperature?: number | null;
  thinking_mode?: string;
  reasoning_effort?: string;
  stream_policy?: Record<string, unknown>;
  fallback_profile_ref?: string;
  capability_tags?: string[];
  metadata?: Record<string, unknown>;
};

export type OrchestrationAgentGroup = {
  group_id: string;
  title: string;
  group_kind: string;
  coordinator_agent_id: string;
  member_agent_ids: string[];
  description: string;
  lifecycle_state: string;
  metadata?: Record<string, unknown>;
};

export type OrchestrationOption = {
  id: string;
  value: string;
  label: string;
  description?: string;
  category?: string;
  requestable?: boolean;
  system_only?: boolean;
  deprecated?: boolean;
  metadata?: Record<string, unknown>;
  operation_type?: string;
};

export type PersonalitySelection = {
  personality_attitude_refs: string[];
  work_attitude_refs: string[];
};

export type PersonalitySelectorOption = {
  id: string;
  value: string;
  prompt_ref: string;
  label: string;
  title?: string;
  description?: string;
  dimension: "personality_attitude" | "work_attitude" | string;
  order?: number;
};

export type PersonalitySelectorDimension = {
  dimension: "personality_attitude" | "work_attitude" | string;
  label: string;
  description?: string;
  options: PersonalitySelectorOption[];
};

export type PersonalitySelectorCatalog = {
  authority: string;
  schema_version: string;
  selection_key: string;
  dimensions: PersonalitySelectorDimension[];
  options_by_dimension?: Record<string, PersonalitySelectorOption[]>;
};

export type OrchestrationCapabilityItem = {
  capability_id: string;
  capability_kind: "skill" | "tool" | "mcp" | "operation" | string;
  title: string;
  subtitle: string;
  description: string;
  operation_ids: string[];
  source_label: string;
  source_detail: string;
  risk_label: string;
  risk_tone: "ok" | "warn" | "danger" | "neutral" | string;
  risk_items: string[];
  tags: string[];
  metadata: Array<{
    label: string;
    value: string;
  }>;
};

export type OrchestrationAgentRuntimeCatalog = {
  authority: string;
  agents: Array<Record<string, unknown> & { runtime_profile?: Partial<OrchestrationAgentRuntimeProfile> }>;
  agent_groups?: OrchestrationAgentGroup[];
  profiles: OrchestrationAgentRuntimeProfile[];
  summary: Record<string, number>;
  options: {
    operations: OperationDescriptor[];
    task_graphs: string[];
    memory_scopes: string[];
    context_sections: string[];
    approval_policies: string[];
    trace_policies: string[];
    operation_options?: OrchestrationOption[];
    task_graph_options?: OrchestrationOption[];
    memory_scope_options?: OrchestrationOption[];
    context_section_options?: OrchestrationOption[];
    approval_policy_options?: OrchestrationOption[];
    trace_policy_options?: OrchestrationOption[];
    worker_blueprints?: Array<Record<string, unknown>>;
    capability_items?: OrchestrationCapabilityItem[];
    tool_packages?: ToolPackageDefinition[];
    model_provider_catalog?: ModelProviderCatalog;
    personality_options?: PersonalitySelectorCatalog;
  };
};

export type OrchestrationAgentRuntimeProfileUpsertPayload =
  Omit<OrchestrationAgentRuntimeProfile, "agent_id" | "allowed_operations" | "final_allowed_operations"> & {
    allowed_tool_packages: ToolPackageSelection[];
    extra_allowed_operations: string[];
  };

export type OrchestrationAgentGroupUpsertPayload = OrchestrationAgentGroup;

export type TaskWorkflowCatalog = {
  authority: string;
  workflows: TaskWorkflowRecord[];
  summary: Record<string, number>;
};

export type TaskWorkflowRecord = {
  workflow_id: string;
  title: string;
  task_mode: string;
  visible_skill_ids: string[];
  steps: Array<Record<string, unknown>>;
  input_boundary: string;
  output_boundary: string;
  stop_conditions: string[];
  required_evidence_refs: string[];
  output_contract_id: string;
  prompt: string;
  enabled: boolean;
  metadata?: Record<string, unknown>;
};

export type TaskWorkflowUpsertPayload = TaskWorkflowRecord;

export type HealthRiskEvent = {
  event_id: string;
  source: string;
  scope: "task" | "system" | "token" | "efficiency" | string;
  severity: "info" | "warning" | "high" | "critical" | string;
  target_ref: string;
  title: string;
  summary: string;
  recommended_action: string;
  created_at: number;
};

export type HealthTaskRecord = {
  task_run_id: string;
  session_id: string;
  task_contract_ref: string;
  title: string;
  task_id: string;
  agent_id: string;
  agent_profile_id: string;
  runtime_lane: string;
  status: string;
  terminal_reason: string;
  created_at: number;
  updated_at: number;
  duration_seconds: number;
  agent_count: number;
  worker_request_count: number;
  worker_result_count: number;
  tool_call_count: number;
  event_count: number;
  error_count: number;
  token_total: number;
  token_source?: "provider_usage" | "local_prediction" | "trace_estimate" | "none" | string;
  exact_token_total?: number;
  predicted_token_total?: number;
  trace_estimate_token_total?: number;
  cached_tokens?: number;
  cache_savings_tokens?: number;
  token_record_count?: number;
  risk_level: "normal" | "warning" | "high" | "critical" | string;
  latest_risk_event: string;
  supervision_count: number;
  latest_event_type: string;
  monitor_ref: string;
  record_refs: Record<string, string>;
};

export type HealthTokenUsage = {
  authority: string;
  summary: Record<string, number>;
  sessions: Array<Record<string, unknown>>;
  tasks: Array<Record<string, unknown>>;
  daily: Array<Record<string, unknown>>;
  note?: string;
  updated_at: number;
};

export type HealthEfficiency = {
  authority: string;
  summary: Record<string, number>;
  tasks: Array<Record<string, unknown>>;
  updated_at: number;
};

export type HealthRecommendation = {
  title: string;
  summary: string;
  priority: "info" | "medium" | "high" | string;
};

export type HealthSystemOverview = {
  authority: string;
  summary: Record<string, number>;
  tasks: HealthTaskRecord[];
  risks: HealthRiskEvent[];
  system_risks: HealthRiskEvent[];
  token_usage: HealthTokenUsage;
  efficiency: HealthEfficiency;
  recommendations: HealthRecommendation[];
  monitor: Record<string, unknown>;
  monitor_governance?: HealthMonitorGovernance;
  updated_at: number;
  issues?: HealthIssue[];
  agent_runs?: HealthAgentRun[];
  problem_nodes?: HealthProblemNode[];
  commands?: HealthManagementCommand[];
  reports?: HealthReport[];
};

export type HealthTaskRecordPruneResult = {
  authority: string;
  mode?: string;
  operation?: string;
  bucket: string;
  requested_task_run_ids: string[];
  candidate_count: number;
  eligible_task_run_ids?: string[];
  protected_task_run_ids?: string[];
  deleted_task_run_ids: string[];
  deleted_event_log_task_run_ids: string[];
  deleted_counts: Record<string, number>;
  skipped: Array<Record<string, unknown>>;
  preflight?: HealthTaskRecordMaintenance;
  policy?: Record<string, unknown>;
  maintenance_receipt?: Record<string, unknown>;
  monitor: Record<string, unknown>;
  updated_at: number;
};

export type HealthTaskRecordMaintenance = {
  authority: string;
  mode: string;
  bucket: string;
  requested_task_run_ids: string[];
  policy: Record<string, unknown>;
  summary: Record<string, number>;
  candidates: Array<Record<string, unknown>>;
  recent_receipts: Array<Record<string, unknown>>;
  updated_at: number;
};

export type HealthMonitorGovernance = {
  authority: string;
  monitor_authority: string;
  revision: string;
  status: string;
  summary: Record<string, number>;
  risk_escalations: HealthRiskEvent[];
  recommended_actions: HealthRecommendation[];
  updated_at: number;
};

export type ContextBudgetPreset = {
  preset_id: string;
  title: string;
  model_hint: string;
  context_window_tokens: number;
  available_context_tokens: number;
  reserved_output_tokens: number;
  long_term_token_cap: number;
  description: string;
};

export type ContextBudgetConfig = {
  active_preset: ContextBudgetPreset;
  preset_id: string;
  presets: ContextBudgetPreset[];
  authority: string;
};

export type ModelProviderOption = {
  provider: string;
  display_name?: string;
  default_model: string;
  default_base_url: string;
  adapter?: string;
  credential_ref?: string;
  fallback_credential_ref?: string;
  credential_configured?: boolean;
  credential_envs?: string[];
  model_presets?: string[];
  capability_tags?: string[];
  recommended?: boolean;
  active?: boolean;
  metadata?: Record<string, unknown>;
};

export type ModelCredentialRef = {
  credential_ref: string;
  provider: string;
  slot: string;
  configured?: boolean;
};

export type ModelProviderCatalog = {
  authority: string;
  default_provider: string;
  default_model: string;
  default_base_url?: string;
  recommended_provider?: string;
  providers: Record<string, ModelProviderOption>;
  credential_refs: ModelCredentialRef[];
};

export type ModelProviderConfig = {
  provider: string;
  model: string;
  base_url: string;
  credential_ref?: string;
  api_key_configured: boolean;
  thinking_mode?: string;
  reasoning_effort?: string;
  fallback_provider: string;
  fallback_model: string;
  fallback_base_url: string;
  fallback_credential_ref?: string;
  fallback_api_key_configured: boolean;
  supported_providers: Record<string, ModelProviderOption>;
  provider_catalog?: ModelProviderCatalog;
  authority: string;
};

export type ImageAssetConfig = {
  configured: boolean;
  base_url: string;
  model: string;
  api_key_present: boolean;
  asset_dir: string;
  asset_route_prefix: string;
  asset_store_relative_dir: string;
};

export type RuntimeConfigField = {
  key: string;
  label: string;
  type: "text" | "number" | "boolean" | "select" | "secret";
  value?: string | number | boolean | null;
  configured?: boolean;
  options?: string[];
  source: "runtime_override" | "env_or_default" | string;
  description: string;
  restart_required: boolean;
};

export type RuntimeConfigGroup = {
  group_id: string;
  title: string;
  description: string;
  status: string;
  fields: RuntimeConfigField[];
  metadata?: Record<string, unknown>;
};

export type RuntimeConfigConsole = {
  authority: string;
  groups: RuntimeConfigGroup[];
};

export type HealthIssue = {
  issue_id: string;
  title: string;
  owner_system: string;
  severity: string;
  status: string;
  source: string;
  conversation_ref?: string;
  runtime_trace_refs?: string[];
  prompt_manifest_refs?: string[];
  memory_refs?: string[];
  assertion_refs?: string[];
  duplicate_of?: string;
  created_at?: number;
  updated_at?: number;
  metadata?: Record<string, unknown>;
};

export type HealthAgentRun = {
  run_id: string;
  request_id?: string;
  issue_id: string;
  task_run_id: string;
  agent_id: string;
  agent_profile_id: string;
  runtime_lane: string;
  health_action: string;
  workflow_id: string;
  admission_status?: string;
  projection_id: string;
  prompt_manifest_id: string;
  status: string;
  terminal_reason: string;
  blocked_reasons?: string[];
  report_refs?: string[];
  trace_refs?: string[];
  artifact_refs?: string[];
  result_ref?: string;
  created_at?: number;
  metadata?: Record<string, unknown>;
};

export type VerificationRun = {
  verification_run_id: string;
  profile_id: string;
  status: string;
  command_ref?: string;
  source_run_ref?: string;
  process_ref?: string;
  output_dir?: string;
  log_path?: string;
  artifact_manifest_ref?: string;
  summary: {
    total: number;
    passed: number;
    failed: number;
    first_failure: string;
  };
  artifact_refs?: string[];
  issue_refs?: string[];
  report_refs?: string[];
  trace_refs?: string[];
  started_at?: number;
  ended_at?: number;
  metadata?: Record<string, unknown>;
  authority: string;
};

export type HealthProblemNode = {
  node_id: string;
  issue_id: string;
  system: string;
  stage: string;
  evidence_refs: string[];
  diagnosis: string;
  confidence: number;
  suggested_action: string;
};

export type HealthTraceReport = {
  authority: string;
  run: HealthAgentRun;
  issue: HealthIssue | null;
  result: Record<string, unknown> | null;
  event_count: number;
  event_type_counts: Record<string, number>;
  problem_events: Array<Record<string, unknown>>;
  prompt_manifest_ref: string;
  projection_ref: string;
  task_run_trace: Record<string, unknown>;
};

export type HealthManagementCommand = {
  command_id: string;
  command_type: string;
  initiator_type: "user" | "agent" | "system" | "test_system" | string;
  initiator_ref: string;
  requested_by: string;
  source: string;
  conversation_session_ref: string;
  target_scope: string;
  target_ref: string;
  health_action: string;
  payload: Record<string, unknown>;
  status: string;
  created_at: number;
  updated_at: number;
};

export type HealthManagementReceipt = {
  receipt_id: string;
  command_ref: string;
  accepted: boolean;
  status: string;
  health_issue_ref: string;
  health_run_ref: string;
  report_ref: string;
  blocked_reasons: string[];
  diagnostics: Record<string, unknown>;
  created_at: number;
};

export type HealthReport = {
  report_id: string;
  report_type: string;
  issue_ref: string;
  command_ref: string;
  agent_run_ref: string;
  evidence_refs: string[];
  verdict: string;
  severity: string;
  summary: string;
  recommended_actions: string[];
  created_at: number;
};

export type HealthAgentConversationSession = {
  session_id: string;
  agent_id: string;
  agent_profile_id: string;
  workflow_id: string;
  runtime_lane: string;
  active_issue_ref: string;
  active_run_ref: string;
  command_refs: string[];
  status: string;
  created_at: number;
  updated_at: number;
};

export type HealthAgentConversationMessage = {
  message_id: string;
  session_id: string;
  role: "user" | "assistant" | "system" | string;
  content: string;
  command_ref?: string;
  receipt_ref?: string;
  report_ref?: string;
  created_at: number;
};

export type HealthCommandResponse = {
  authority: string;
  command: HealthManagementCommand;
  receipt: HealthManagementReceipt;
  report?: HealthReport;
  issue?: HealthIssue;
  run_result?: Record<string, unknown>;
};

export type HealthAgentRunPreview = {
  authority: string;
  status: string;
  issue: Record<string, unknown>;
  flow: Record<string, unknown>;
  binding: Record<string, unknown>;
  runtime_directive_lane?: Record<string, unknown>;
  reason?: string;
};

export type HealthAgentRunStart = HealthAgentRunPreview & {
  health_agent_run?: Record<string, unknown>;
  task_run?: Record<string, unknown>;
  loop_state?: Record<string, unknown>;
  checkpoint?: Record<string, unknown>;
  events?: Array<Record<string, unknown>>;
  trace?: Record<string, unknown> | null;
};

export type OrchestrationNodeStatus = "idle" | "visited" | "warning" | "failed" | "success" | "blocked" | "skipped";

export type OrchestrationNode = {
  id: string;
  index: number;
  label: string;
  description: string;
  status: OrchestrationNodeStatus;
  summary: string;
  source_event: string;
  source_module?: string;
  reasons?: string[];
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  refs?: Record<string, unknown>;
};

export type OrchestrationEdge = {
  id: string;
  from: string;
  to: string;
  label: string;
  status: OrchestrationNodeStatus;
  summary: string;
};

export type OrchestrationEvent = {
  index: number;
  event: string;
  node_id: string;
  summary: string;
  ts_ms?: number | null;
  data: Record<string, unknown>;
};

export type OrchestrationSnapshot = {
  source: "live-session" | "test-turn" | "inferred" | "dry-run" | string;
  session_id: string;
  run_id?: string;
  task_run_id?: string;
  graph_run_ids?: string[];
  turn_id?: string;
  turn_index?: number;
  execution_mode: string;
  route: string;
  status: "idle" | "running" | "success" | "warning" | "failed" | string;
  summary: string;
  problem_node_id?: string;
  nodes: OrchestrationNode[];
  edges: OrchestrationEdge[];
  events: OrchestrationEvent[];
  artifacts?: Record<string, string>;
  decision_trace?: Record<string, unknown>;
  dry_run?: Record<string, unknown>;
  orchestration_plan?: Record<string, unknown>;
  orchestration_diff?: Record<string, unknown>;
};

export type HarnessTraceEvent = {
  event_id: string;
  run_id: string;
  task_run_id?: string;
  event_type: string;
  offset: number;
  created_at: number;
  refs?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  payload_summary?: Record<string, unknown>;
};

export type HarnessTaskRunSummary = {
  task_run_id: string;
  session_id: string;
  task_id: string;
  status: string;
  execution_runtime_kind: string;
  created_at: number;
  updated_at: number;
  terminal_reason: string;
  latest_event_offset: number;
  graph_runs?: Array<Record<string, unknown>>;
  graph_run_count?: number;
};

export type HarnessSessionTaskRuns = {
  authority: string;
  session_id: string;
  task_run_count: number;
  task_runs: HarnessTaskRunSummary[];
};

export type RuntimeMonitorSignal = {
  authority: string;
  signal_id: string;
  source_kind: "task_run" | "turn_run" | "runtime_run" | "graph_run" | "diagnostic" | string;
  work_kind: "chat_turn" | "agent_task" | "graph_task" | string;
  state: "active" | "waiting" | "attention" | "completed" | "failed" | "stale" | string;
  priority: number;
  title: string;
  line: string;
  detail: string;
  status: string;
  lifecycle: string;
  bucket: string;
  activity_state?: "running" | "waiting" | "paused" | "stopped" | "failed" | "completed" | "stale" | "idle" | string;
  activity_label?: string;
  is_running?: boolean;
  is_waiting?: boolean;
  is_resumable?: boolean;
  is_interruptible?: boolean;
  control_reason?: string;
  recovery_cause?: string;
  tone?: "active" | "neutral" | "attention" | "done" | string;
  activity?: Record<string, unknown>;
  control_capability?: Record<string, unknown>;
  session_output_commit?: {
    authority?: string;
    state?: "none" | "checked" | "committed" | "failed" | "skipped" | string;
    status?: string;
    session_id?: string;
    turn_id?: string;
    task_run_id?: string;
    task_id?: string;
    anchor_message_id?: string;
    content_sha256?: string;
    reason?: string;
    commit_event_offset?: number;
    checked_event_offset?: number;
    created_at?: number;
  };
  session_id: string;
  task_run_id: string;
  task_instance_id: string;
  graph_run_id: string;
  graph_id: string;
  navigation_target: Record<string, unknown>;
  detail_ref?: {
    kind?: "task_run" | "turn_run" | "graph_run" | "resource" | "none" | string;
    task_run_id?: string;
    turn_run_id?: string;
    graph_run_id?: string;
    graph_harness_config_id?: string;
    resource_ref?: string;
  };
  graph_ref?: {
    graph_id?: string;
    graph_run_id?: string;
    graph_harness_config_id?: string;
  };
  timestamps: {
    started_at?: number;
    updated_at?: number;
    last_activity_at?: number;
    elapsed_seconds?: number;
  };
  raw_refs?: Record<string, unknown>;
  visibility?: {
    visible?: boolean;
    lane?: "current" | "attention" | "projects" | "recent" | "hidden" | string;
    default_lane?: "current" | "attention" | "projects" | "recent" | "hidden" | string;
    hidden?: boolean;
    hidden_reason?: string;
    hidden_at?: number;
    expires_at?: number;
  };
  actions?: RuntimeMonitorSignalAction[];
};

export type RuntimeMonitorSignalAction = {
  action: string;
  label: string;
  enabled: boolean;
  disabled_reason?: string;
};

export type RuntimeMonitorManagement = {
  authority: string;
  policy: Record<string, unknown>;
  summary: Record<string, number>;
  lanes: {
    current?: RuntimeMonitorSignal[];
    attention?: RuntimeMonitorSignal[];
    projects?: RuntimeMonitorSignal[];
    recent?: RuntimeMonitorSignal[];
    hidden?: RuntimeMonitorSignal[];
  };
  capacity?: Record<string, number>;
  updated_at?: number;
};

export type RuntimeMonitorEnvelope = {
  authority: string;
  revision: string;
  updated_at: number;
  summary: {
    active: number;
    attention: number;
    waiting: number;
    failed: number;
    recent: number;
    projects: number;
    hidden?: number;
    total: number;
  };
  primary: RuntimeMonitorSignal[];
  attention: RuntimeMonitorSignal[];
  recent: RuntimeMonitorSignal[];
  projects: RuntimeMonitorSignal[];
  signals: RuntimeMonitorSignal[];
  management?: RuntimeMonitorManagement;
};

export type RuntimeMonitorActionPayload = {
  action: string;
  signal_id?: string;
  task_run_id?: string;
  graph_run_id?: string;
  reason?: string;
  source_revision?: string;
  max_steps?: number;
};

export type RuntimeMonitorActionResult = {
  authority: string;
  mode?: "preflight" | "execute" | string;
  accepted: boolean;
  action: string;
  target: Record<string, string>;
  effects: Record<string, unknown>;
  disabled_reason?: string;
  receipt?: Record<string, unknown>;
  monitor: RuntimeMonitorEnvelope;
  updated_at: number;
};

export type RunMonitorEventPayload = {
  source?: string;
  monitor?: RuntimeMonitorEnvelope;
  updated_at?: number;
};

export type RuntimeLogScope = "task_run" | "turn_run";

export type RuntimeLogGap = {
  expected_after_offset: number;
  observed_offset: number;
  recovered: boolean;
};

export type RuntimeLogStreamPayload = {
  source?: "snapshot" | "event" | "gap" | "heartbeat" | "closed" | string;
  scope: RuntimeLogScope;
  run_id: string;
  event?: HarnessTraceEvent;
  events?: HarnessTraceEvent[];
  event_offset?: number;
  last_event_id?: string;
  gap?: RuntimeLogGap;
  updated_at?: number;
};

export type HarnessTaskRunTrace = {
  authority: string;
  task_run: Record<string, unknown>;
  graph_runs: Array<Record<string, unknown>>;
  graph_run_count: number;
  event_count: number;
  events: HarnessTraceEvent[];
};

export type HarnessTurnRunTrace = {
  authority: string;
  turn_run: Record<string, unknown>;
  event_count: number;
  events: HarnessTraceEvent[];
  event_window?: Record<string, unknown>;
};

export type OrchestrationRuntimeOptionsPayload = {
  authority: string;
  options: OrchestrationAgentRuntimeCatalog["options"];
};

export type HarnessTaskRunLiveMonitor = {
  authority: string;
  scope?: string;
  task_run: Record<string, unknown>;
  task_run_id?: string;
  task_instance_id?: string;
  root_task_run_id?: string;
  kind?: "agent_run" | "task_graph" | string;
  session_id?: string;
  task_id?: string;
  execution_runtime_kind?: string;
  is_live?: boolean;
  event_count?: number;
  latest_event?: Record<string, unknown>;
  latest_step?: Record<string, unknown>;
  latest_progress?: Record<string, unknown>;
  latest_step_summary?: string;
  latest_step_name?: string;
  latest_step_status?: string;
  latest_public_progress_note?: string;
  agent_brief_output?: string;
  artifact_count?: number;
  artifact_refs?: Array<Record<string, unknown>>;
  resource_refs?: Array<Record<string, unknown>>;
  primary_resource_ref?: Record<string, unknown> | null;
  graph_status?: Record<string, unknown> | null;
  child_runtime_refs?: Array<Record<string, unknown>>;
  navigation_target?: Record<string, unknown> | null;
  loop_state: Record<string, unknown>;
  graph_run_id?: string;
  graph_harness_config_id?: string;
  agent_runtime_phase_summary?: Record<string, unknown> | null;
  has_graph_run: boolean;
  runtime_control?: Record<string, unknown>;
  control_state?: string;
  lifecycle?: string;
  bucket?: string;
  stale?: boolean;
  activity_state?: "running" | "waiting" | "paused" | "stopped" | "failed" | "completed" | "stale" | "idle" | string;
  activity_label?: string;
  is_running?: boolean;
  is_waiting?: boolean;
  is_resumable?: boolean;
  is_interruptible?: boolean;
  control_reason?: string;
  tone?: "active" | "neutral" | "attention" | "done" | string;
  activity?: Record<string, unknown>;
  control_capability?: Record<string, unknown>;
  status: string;
  terminal_reason: string;
  updated_at: number;
};

export type RuntimeApprovalResolution = {
  authority: string;
  task_run_id: string;
  decision: string;
  approval: Record<string, unknown>;
  resume_result: Record<string, unknown>;
  events: Array<Record<string, unknown>>;
};

export type RuntimeResourceInventoryItem = {
  resource_id: string;
  title: string;
  authority_layer: string;
  path: string;
  runtime_consumer: string;
  can_authorize_side_effects: boolean;
  notes: string;
};

export type RuntimeResourceInventory = {
  authority: string;
  inventory_id: string;
  items: RuntimeResourceInventoryItem[];
};

export type TaskGraphBatchLifecycleView = {
  available: boolean;
  authority?: string;
  mode?: string;
  graph_id?: string;
  summary: {
    plan_count?: number;
    batch_count?: number;
    ready_batch_count?: number;
    running_batch_count?: number;
    committed_batch_count?: number;
    failed_batch_count?: number;
    merge_ready_count?: number;
    [key: string]: number | undefined;
  };
  plans: Array<Record<string, unknown>>;
  batches: Array<Record<string, unknown>>;
  execution_instances?: Array<Record<string, unknown>>;
  merge_states: Array<Record<string, unknown>>;
  active_batch_by_node?: Record<string, string>;
  active_execution_by_node?: Record<string, string>;
  active_execution_by_batch?: Record<string, string>;
  execution_mode_by_plan?: Record<string, string>;
  ready_batch_ids?: string[];
  running_batch_ids?: string[];
  committed_batch_ids?: string[];
  failed_batch_ids?: string[];
};

export function taskGraphRunsFromTrace(trace: { graph_runs?: Array<Record<string, unknown>> } | null | undefined) {
  return Array.isArray(trace?.graph_runs) ? trace.graph_runs : [];
}

export function taskGraphRunIdsFromTrace(trace: { graph_runs?: Array<Record<string, unknown>> } | null | undefined) {
  return taskGraphRunsFromTrace(trace)
    .map((item) => taskGraphRunIdOf(item))
    .filter(Boolean);
}

export function latestTaskGraphRunFromTrace(trace: { graph_runs?: Array<Record<string, unknown>> } | null | undefined) {
  return taskGraphRunsFromTrace(trace)[0] ?? null;
}

export function taskGraphRunIdOf(run: Record<string, unknown> | null | undefined) {
  return String(run?.graph_run_id ?? run?.run_id ?? "").trim();
}

export type HarnessSessionLiveMonitor = {
  authority: string;
  session_id: string;
  active_task_run_id?: string;
  active_turn_snapshot?: {
    turn_id?: string;
    turn_run_id?: string;
    bound_task_run_id?: string;
    task_run_id?: string;
    state?: string;
    updated_at?: number;
  } | null;
  task_runs?: HarnessTaskRunLiveMonitor[];
  task_run_count: number;
  latest_task_run_id: string;
  project_runtime_status?: Record<string, unknown> | null;
  monitor: HarnessTaskRunLiveMonitor | null;
};

export type ProjectRuntimeStatusView = {
  authority: string;
  project_runtime_status: Record<string, unknown>;
  project_progress_ledger: Record<string, unknown> | null;
  supervision_records: Array<Record<string, unknown>>;
};

export type SessionTruncateResponse = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  compressed_context?: string;
  messages: SessionHistory["messages"];
};

export type TaskGraphRunStartResult = {
  authority: string;
  graph_id: string;
  graph_run_id: string;
  graph_harness_config_id: string;
  launch_session_id: string;
  graph_session_id: string;
  task_run_id: string;
  task_run: Record<string, unknown>;
  graph_run: Record<string, unknown>;
  checkpoint: Record<string, unknown>;
  graph_loop_state: Record<string, unknown>;
  graph_harness_config: Record<string, unknown>;
  node_work_orders: Array<Record<string, unknown>>;
  runner_result: GraphRunUntilIdleResult | null;
  background_submission: GraphRunBackgroundSubmitResult | null;
  trace: HarnessTaskRunTrace | null;
  events: Array<Record<string, unknown>>;
};

export type GraphRunMonitorView = {
  authority: "harness.graph_run_monitor" | string;
  graph_run_id: string;
  graph_run: Record<string, unknown>;
  task_run: Record<string, unknown> | null;
  task_run_monitor?: HarnessTaskRunLiveMonitor | Record<string, unknown> | null;
  runtime_monitor?: HarnessTaskRunLiveMonitor | Record<string, unknown> | null;
  graph_harness_config: GraphHarnessConfigPayload | Record<string, unknown>;
  graph_loop_state: Record<string, unknown>;
  active_node_work_orders: Array<Record<string, unknown>>;
  active_node_work_order_count: number;
  active_node_runtime_views?: Array<Record<string, unknown>>;
  events?: Array<Record<string, unknown>>;
  event_count: number;
  event_window?: {
    kind?: string;
    limit?: number;
    returned?: number;
  };
};

export type GraphTaskInstanceSummary = {
  authority?: string;
  graph_task_instance_id: string;
  graph_id: string;
  title: string;
  description?: string;
  status: string;
  root_session_id?: string;
  active_graph_run_id?: string;
  graph_run_ids?: string[];
  file_space_id?: string;
  artifact_index_id?: string;
  created_at?: number;
  updated_at?: number;
  metadata?: Record<string, unknown>;
};

export type GraphTaskDefinitionSummary = {
  graph_id: string;
  title: string;
  domain_id?: string;
  graph_kind?: string;
  publish_state?: string;
  enabled?: boolean;
  metadata?: Record<string, unknown>;
};

export type GraphTaskInstanceDetail = {
  authority: string;
  instance: GraphTaskInstanceSummary;
  repositories?: Record<string, unknown>;
  artifacts?: GraphTaskInstanceArtifacts;
};

export type GraphTaskDefinitionList = {
  authority: string;
  graph_tasks: GraphTaskDefinitionSummary[];
  summary?: Record<string, unknown>;
};

export type GraphTaskInstanceList = {
  authority: string;
  graph_id: string;
  instances: GraphTaskInstanceSummary[];
  summary?: Record<string, unknown>;
};

export type GraphTaskInstanceCreateResult = {
  authority: string;
  instance: GraphTaskInstanceSummary;
  root_session?: SessionSummary | Record<string, unknown>;
  file_space?: Record<string, unknown>;
};

export type GraphTaskInstanceMonitor = {
  authority: string;
  instance: GraphTaskInstanceSummary;
  graph_monitor: GraphRunMonitorView | null;
  node_sessions: SessionSummary[];
  artifacts: GraphTaskInstanceArtifacts;
  human_controls?: GraphTaskInstanceHumanControls;
  summary: Record<string, unknown>;
};

export type HumanEdgeDecisionKind = "pass" | "revise" | "replace";

export type WritingChapterIndexItem = {
  authority?: string;
  chapter_id: string;
  title: string;
  path: string;
  status: string;
  source?: string;
  chapter_number?: number | null;
  updated_at?: number;
  size?: number;
  selection_reason?: string;
};

export type WritingChapterAction = {
  authority?: string;
  action: "approve" | "request_revision" | "replace_with_user_text" | string;
  decision: HumanEdgeDecisionKind;
  label: string;
  description?: string;
  enabled: boolean;
  control_id: string;
  edge_id: string;
  source_node_id?: string;
  target_node_id?: string;
  reason?: string;
};

export type WritingAssetCategory = {
  authority?: string;
  category_id: string;
  title: string;
  items: Array<Record<string, unknown>>;
  summary?: Record<string, unknown>;
};

export type WritingGraphInstanceDesk = {
  authority: string;
  projection_authority?: string;
  graph_task_instance_id: string;
  instance: GraphTaskInstanceSummary;
  chapter_index: WritingChapterIndexItem[];
  current_chapter: Partial<WritingChapterIndexItem> & Record<string, unknown>;
  reader: {
    authority?: string;
    path: string;
    content: string;
    content_kind: string;
    empty?: boolean;
  };
  writing_assets: {
    authority?: string;
    categories: WritingAssetCategory[];
    summary?: Record<string, unknown>;
  };
  chapter_actions: WritingChapterAction[];
  node_sessions: SessionSummary[];
  artifacts: GraphTaskInstanceArtifacts;
  human_controls?: GraphTaskInstanceHumanControls;
  file_tree?: GraphTaskInstanceFileTree;
  graph_debug_ref?: Record<string, unknown>;
  summary?: Record<string, unknown>;
};

export type WritingChapterActionRequest = {
  chapter_id?: string;
  action: WritingChapterAction["action"];
  instruction?: string;
  content?: string;
  target_path?: string;
  control_id?: string;
  apply_now?: boolean;
  metadata?: Record<string, unknown>;
};

export type HumanEdgeControlView = {
  authority?: string;
  control_id: string;
  graph_run_id: string;
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  source_node_status?: string;
  target_node_status?: string;
  source_result_ref?: string;
  pending_node_id?: string;
  artifact_refs?: Array<Record<string, unknown>>;
  allowed_decisions: HumanEdgeDecisionKind[];
  decision_labels?: Record<string, string>;
  default_decision?: HumanEdgeDecisionKind;
  reason?: string;
  human_control_policy?: Record<string, unknown>;
};

export type GraphTaskInstanceHumanControls = {
  authority?: string;
  pending: HumanEdgeControlView[];
  available: HumanEdgeControlView[];
  history: Array<Record<string, unknown>>;
  summary?: Record<string, unknown>;
};

export type HumanEdgeDecisionSubmitRequest = {
  graph_run_id?: string;
  edge_id: string;
  decision: HumanEdgeDecisionKind;
  instruction?: string;
  artifact_refs?: Array<Record<string, unknown>>;
  content_submission?: Record<string, unknown> | null;
  apply_now?: boolean;
  idempotency_key?: string;
  operator?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type HumanEdgeDecisionSubmitResult = {
  authority: string;
  decision: Record<string, unknown>;
  apply_result?: Record<string, unknown> | null;
  idempotent?: boolean;
};

export type WritingChapterActionSubmitResult = {
  authority: string;
  graph_task_instance_id: string;
  chapter_action: WritingChapterAction;
  control?: HumanEdgeControlView | Record<string, unknown>;
  decision_result: HumanEdgeDecisionSubmitResult;
  summary?: Record<string, unknown>;
};

export type GraphTaskInstanceArtifacts = {
  authority?: string;
  graph_task_instance_id?: string;
  artifacts: Array<Record<string, unknown>>;
  summary?: Record<string, unknown>;
};

export type GraphTaskInstanceFileTree = {
  authority: string;
  graph_task_instance_id: string;
  repository_id: string;
  path: string;
  total_entries: number;
  truncated: boolean;
  tree: Record<string, unknown>;
};

export type GraphTaskInstanceFileReadResult = {
  authority: string;
  graph_task_instance_id: string;
  repository_id: string;
  path: string;
  content: string;
  size?: number;
  updated_at?: number;
};

export type GraphTaskInstanceFileWriteResult = {
  authority: string;
  graph_task_instance_id: string;
  repository_id: string;
  path: string;
  written?: boolean;
  size?: number;
  updated_at?: number;
};

export type GraphTaskInstanceRunStartResult = {
  authority: string;
  instance: GraphTaskInstanceSummary;
  start: TaskGraphRunStartResult;
};

export type GraphRunDispatchReadyResult = {
  authority: string;
  graph_run_id: string;
  graph_harness_config_id: string;
  graph_loop_state: Record<string, unknown>;
  checkpoint: Record<string, unknown>;
  node_work_orders: Array<Record<string, unknown>>;
  work_order_count: number;
  events: Array<Record<string, unknown>>;
};

export type GraphRunUntilIdleResult = {
  authority: string;
  graph_run_id: string;
  status: string;
  terminal_reason: string;
  executed_work_order_count: number;
  accepted_result_count: number;
  dispatch_count: number;
  blocked_reason: string;
  budget_exhausted: boolean;
  graph_loop_state: Record<string, unknown>;
  graph_result: Record<string, unknown>;
  events: Array<Record<string, unknown>>;
};

export type GraphRunBackgroundSubmitResult = {
  authority: string;
  accepted: boolean;
  background_started: boolean;
  already_running: boolean;
  graph_run_id: string;
  graph_harness_config_id: string;
  background_task_name: string;
  background_task_names?: string[];
  scheduled_work_order_count?: number;
  already_running_work_order_count?: number;
  active_work_order_count?: number;
  monitor_url: string;
  diagnostics?: Record<string, unknown>;
};

export type GraphRunControlResult = {
  authority: string;
  ok: boolean;
  accepted: boolean;
  action: "pause" | "resume" | string;
  reason: string;
  graph_run_id: string;
  task_run_id: string;
  graph_run: Record<string, unknown>;
  task_run: Record<string, unknown>;
  control: Record<string, unknown>;
};

export type OrchestrationCatalogSkill = {
  runtime: {
    name: string;
    title: string;
    description: string;
    path: string;
    supported_modalities: string[];
    supported_task_kinds: string[];
    supported_source_kinds: string[];
    capability_tags: string[];
    preferred_route: string;
    forbidden_routes: string[];
    routing_hints: string[];
    examples: string[];
    activation_policy: string;
    context_mode: string;
    route_authority: string;
    reference_paths: string[];
  };
  prompt_view: {
    name: string;
    title: string;
    capability: string;
    use_when: string;
    output_rule: string;
  };
};

export type OrchestrationCatalogTool = {
  name: string;
  display_name: string;
  operation_id: string;
  module: string;
  contract: Record<string, unknown>;
  resolution_contract: Record<string, unknown>;
  output_contract: Record<string, unknown>;
  projection_contract: Record<string, unknown>;
  capability_tags: string[];
  supported_modalities: string[];
  safety_tags: string[];
  route_hints: string[];
  safe_for_auto_route: boolean;
  runtime_visibility: string;
  prompt_exposure_policy: string;
  resource_exposure_policy: string;
  is_read_only: boolean;
  is_destructive: boolean;
  is_concurrency_safe: boolean;
};

export type OrchestrationCatalog = {
  permission_mode: string;
  supported_permission_modes: string[];
  tool_invocation_validation_mode: string;
  orchestration_plan_mode: string;
  supported_orchestration_plan_modes: string[];
  skills: OrchestrationCatalogSkill[];
  tools: OrchestrationCatalogTool[];
};

export type OperationSkill = OrchestrationCatalogSkill & {
  prompt_block: string;
  content: string;
  validation_errors: string[];
};

export type OperationDescriptor = {
  operation_id: string;
  operation_type: string;
  title: string;
  capability_summary: string;
  provider: string;
  aliases: string[];
  risk_tags: string[];
  read_only: boolean;
  destructive: boolean;
  concurrency_safe: boolean;
  requires_user_interaction: boolean;
  requires_approval_by_default: boolean;
};

export type OperationTool = OrchestrationCatalogTool & {
  operation_metadata: {
    tool_type: string;
    note: string;
    llm_description: string;
    source_class: string;
    tool_boundary: string;
    adapter_type: string;
    risk_level: string;
    risk_rank: number;
    visibility_label: string;
    runtime_policy: string;
    editable_policy: string;
    bound_agents: Array<{
      agent_id: string;
      name: string;
    }>;
    ownership_label: string;
    governance_hints: string[];
  };
};

export type OperationWorker = {
  worker_id: string;
  route: string;
  name: string;
  description: string;
  operation_id: string;
  agent_id: string;
  implementation_module: string;
  endpoint_protocol: string;
  a2a_protocol_version: string;
  transport: string;
  server_name: string;
  invocation_channel: string;
  model_visibility: string;
  input_modes: string[];
  output_modes: string[];
  tags: string[];
  mcp_profile: Record<string, unknown>;
  operation: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
};

export type OperationMCP = {
  mcp_id: string;
  unit_id: string;
  route: string;
  name: string;
  description: string;
  operation_id: string;
  implementation_module?: string;
  endpoint_protocol?: string;
  transport: string;
  server_name?: string;
  invocation_channel?: string;
  model_visibility: string;
  input_modes?: string[];
  output_modes?: string[];
  tags: string[];
  mcp_profile?: Record<string, unknown>;
  operation?: OperationDescriptor | Record<string, unknown>;
  diagnostics?: Record<string, unknown>;
};

export type CapabilityEndpoint = {
  endpoint_id: string;
  kind: "local_worker" | "mcp_server" | string;
  name: string;
  title: string;
  description: string;
  operation_id: string;
  protocol_family: string;
  server_name: string;
  transport: string;
  invocation_channel: string;
  invocation_mode: string;
  model_visibility: string;
  runtime_visibility: string;
  prompt_exposure_policy: string;
  resource_exposure_policy: string;
  source_ref: string;
  owner_units: Array<{
    unit_id: string;
    name: string;
  }>;
  tags: string[];
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  annotations: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

export type CapabilityUnit = {
  capability_id: string;
  kind: "tool" | "skill" | "mcp" | "operation" | string;
  title: string;
  summary: string;
  operation_ids: string[];
  provider: string;
  provider_kind: string;
  transport: string;
  runtime_visibility: string;
  model_visibility: string;
  risk: string[];
  resource_policy: string;
  status: string;
  source_ref: string;
  dependencies: Array<{
    from_id: string;
    to_id: string;
    relation: string;
  }>;
  health: {
    status: string;
    reason: string;
    diagnostics: Record<string, unknown>;
  };
  permission_view: {
    capability_id: string;
    operation_ids: string[];
    profile_state: string;
    adoption_state: string;
    gate_state: string;
    approval_state: string;
    sandbox_state: string;
    reasons: string[];
    diagnostics: Record<string, unknown>;
  } | null;
  display_facets: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
};

export type ExternalMCPServerConfig = {
  server_id: string;
  title: string;
  description: string;
  transport: string;
  enabled: boolean;
  command?: string;
  args: string[];
  env: Record<string, string>;
  cwd?: string;
  url?: string;
  scope?: string;
  tags: string[];
  allowed_operations: string[];
  requires_approval_operations: string[];
  denied_operations: string[];
  metadata: Record<string, unknown>;
};

export type MCPManagementTool = {
  provider_id: string;
  provider_kind: string;
  server_id: string;
  tool_name: string;
  title: string;
  description: string;
  operation_id: string;
  model_visibility: string;
  status: string;
  transport: string;
  tags: string[];
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  annotations?: Record<string, unknown>;
  diagnostics?: Record<string, unknown>;
};

export type MCPManagementServer = {
  provider_id: string;
  provider_kind: string;
  server_id: string;
  title: string;
  description: string;
  transport: string;
  enabled: boolean;
  status: string;
  status_reason: string;
  operation_ids: string[];
  tools: MCPManagementTool[];
  tags?: string[];
  diagnostics: {
    external_config?: Record<string, unknown>;
    [key: string]: unknown;
  };
};

export type MCPManagementCatalog = {
  authority: string;
  providers?: Array<Record<string, unknown>>;
  servers: MCPManagementServer[];
  tools: MCPManagementTool[];
  summary: {
    provider_count?: number;
    server_count: number;
    tool_count: number;
    external_server_count?: number;
    active_server_count?: number;
    [key: string]: unknown;
  };
  validation_issues?: Array<{
    severity: string;
    code: string;
    message: string;
    subject?: string;
  }>;
};

export type OperationBindingGraph = {
  agent_nodes: Array<{
    agent_id: string;
    name: string;
    kind: string;
    description: string;
    bound_tools: string[];
    protocol_version: string;
  }>;
  mcp_nodes?: Array<{
    mcp_id: string;
    unit_id: string;
    route: string;
    name: string;
    description: string;
    operation_id: string;
    transport: string;
    model_visibility: string;
    tags: string[];
  }>;
  agent_tool_edges: Array<{
    from: string;
    from_label: string;
    to: string;
    to_label: string;
    relation: string;
  }>;
  mcp_operation_edges?: Array<{
    from: string;
    from_label: string;
    to: string;
    to_label: string;
    relation: string;
  }>;
  recommendations: string[];
};

export type CapabilitySystemCatalog = {
  skills: OperationSkill[];
  tools: OperationTool[];
  tool_packages?: ToolPackageDefinition[];
  default_library?: Array<{
    tool_name: string;
    operation_id: string;
    tool_type?: string;
  }>;
  mcps?: OperationMCP[];
  local_mcp_units?: Array<Record<string, unknown>>;
  mcp_management?: MCPManagementCatalog;
  capability_units?: CapabilityUnit[];
  workers?: OperationWorker[];
  capability_endpoints?: CapabilityEndpoint[];
  operations?: OperationDescriptor[];
  capability_supply_package?: {
    package_id: string;
    task_id: string;
    agent_id: string;
    tool_refs: Array<{
      tool_name: string;
      operation_id: string;
      tool_type: string;
      runtime_visibility: string;
      prompt_exposure_policy: string;
      risk_level: string;
      source_class: string;
    }>;
    skill_refs: Array<{
      skill_name: string;
      title: string;
      activation_policy: string;
      context_mode: string;
      preferred_route: string;
      capability_tags: string[];
    }>;
    mcp_refs: Array<{
      mcp_id: string;
      operation_id: string;
      route: string;
      unit_id: string;
      transport: string;
      model_visibility: string;
    }>;
    capability_constraints: Record<string, unknown>;
    visibility_rules: Record<string, unknown>;
    diagnostics: Record<string, unknown>;
    authority: string;
  };
  binding_graph: OperationBindingGraph;
  tool_type_options: string[];
  summary: {
    skill_count: number;
    tool_count: number;
    worker_count?: number;
    local_mcp_endpoint_count?: number;
    capability_endpoint_count?: number;
    capability_unit_count?: number;
    mcp_management_server_count?: number;
    model_visible_skills: number;
    tool_types: string[];
    tool_boundaries: Record<string, number>;
    tool_sources: Record<string, number>;
    tool_risks: Record<string, number>;
    operation_count?: number;
    tool_package_count?: number;
    default_library_tool_count?: number;
    validation_issue_count?: number;
    validation_error_count?: number;
  };
  validation_issues?: Array<{
    severity: string;
    code: string;
    message: string;
    subject: string;
  }>;
};

export type PromptManifestSection = {
  id: string;
  title: string;
  layer: "static" | "session" | "turn" | string;
  source: string;
  model_visible: boolean;
  chars: number;
  preview: string;
  order: number;
};

export type PromptManifest = {
  prompt_id: string;
  session_id: string;
  turn_id: string;
  assembly_order: string[];
  total_chars: number;
  total_sections: number;
  sections: PromptManifestSection[];
};

export type PromptManifestResponse = {
  status: "available" | "missing_manifest";
  reason: string;
  prompt_manifest: PromptManifest | null;
};

export type MemoryTraceSection = {
  id: string;
  label: string;
  items: string[];
  count: number;
};

export type ExperimentTurnMemoryTrace = {
  run_id: string;
  turn_id: string;
  has_memory_signal: boolean;
  turn_context?: {
    index: number;
    session_alias: string;
    speaker: string;
    user_input: string;
    assistant_output: string;
    status: string;
    failed_checks: string[];
    artifact_path: string;
  };
  summary: string;
  context_management: {
    pressure_level: string;
    strategy: string;
    selected_sections: string[];
    debug_selected_sections: string[];
    dropped_sections: string[];
    token_accounting: Record<string, number>;
  };
  session_memory: {
    section_count: number;
    model_sections: MemoryTraceSection[];
    debug_sections: MemoryTraceSection[];
    active_goal: string;
    flow_state: Record<string, unknown>;
    task_state: Record<string, unknown>;
    context_slots: Record<string, unknown>;
  };
  durable_memory: {
    exact_count: number;
    relevant_count: number;
    exact_matches: Array<Record<string, unknown>>;
    relevant_notes: Array<Record<string, unknown>>;
    model_sections: MemoryTraceSection[];
    debug_sections: MemoryTraceSection[];
  };
  prompt_injection: {
    section_count: number;
    total_chars: number;
    sections: Array<{
      id: string;
      title: string;
      layer: string;
      source: string;
      chars: number;
      preview: string;
      order: number;
    }>;
  };
};

export type ExperimentTurnMemoryTraceResponse = {
  status: "available" | "missing_trace";
  reason: string;
  memory_trace: ExperimentTurnMemoryTrace | null;
};

export type MemoryHeader = {
  note_id: string;
  filename: string;
  memory_type: string;
  memory_class: string;
  title: string;
  description: string;
  status: string;
  confidence: string;
  updated_at: string;
  retrieval_hints: string[];
  eligible_for_injection: boolean;
  canonical_statement: string;
  summary: string;
};

export type MemorySessionInspect = {
  present: boolean;
  preview: string;
  model_preview: string;
  debug_preview: string;
  active_goal: string;
  flow_state: Record<string, unknown>;
  task_state: Record<string, unknown>;
  context_slots: Record<string, unknown>;
  risk: Record<string, unknown>;
  warm_snapshots: Array<Record<string, unknown>>;
  storage: Record<string, unknown>;
  context_management: Record<string, unknown>;
  durable_matches: Record<string, unknown>;
};

export type MemorySessionFile = {
  id: string;
  label: string;
  description: string;
  path: string;
  kind: "json" | "markdown" | string;
  exists: boolean;
  size: number;
  updated_at: number | null;
  preview: string;
};

export type MemorySessionFilesResponse = {
  session_id: string;
  root: string;
  present: boolean;
  existing_count: number;
  missing_count: number;
  files: MemorySessionFile[];
};

export type FormalMemoryRepository = {
  repository_id: string;
  logical_repository_id: string;
  effective_repository_id: string;
  task_run_id: string;
  scope_kind: string;
  scope_id: string;
  graph_id: string;
  node_id: string;
  title: string;
  repository_kind?: string;
  lifecycle_policy?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  authority: string;
};

export type FormalMemoryRecord = {
  record_id: string;
  repository_id: string;
  logical_repository_id: string;
  effective_repository_id: string;
  task_run_id: string;
  scope_kind: string;
  scope_id: string;
  collection_id: string;
  record_key: string;
  record_kind: string;
  status: string;
  current_committed_version?: number;
  head_version_id?: string;
  created_at: string;
  updated_at: string;
  authority: string;
};

export type FormalMemoryVersion = FormalMemoryRecord & {
  version_id: string;
  version: number;
  payload: Record<string, unknown>;
  canonical_text: string;
  summary: string;
  artifact_refs: string[];
  source_node_id: string;
  source_edge_id: string;
  source_node_run_id: string;
  source_clock: string;
  source_clock_seq: number;
  visible_after_clock: string;
  visible_after_clock_seq: number;
  content_hash: string;
};

export type FormalMemoryReadLog = {
  read_log_id: string;
  edge_id: string;
  node_run_id: string;
  repository_id: string;
  logical_repository_id: string;
  effective_repository_id: string;
  task_run_id: string;
  scope_kind: string;
  scope_id: string;
  collection_id: string;
  selector: Record<string, unknown>;
  selected_version_ids: string[];
  clock: string;
  clock_seq: number;
  created_at: string;
  authority: string;
};

export type FormalMemoryOverview = {
  task_run_id: string;
  repository_id: string;
  collection_id: string;
  repository_count: number;
  collection_count: number;
  record_count: number;
  version_count: number;
  read_log_count: number;
  repositories: FormalMemoryRepository[];
  collections: Array<Record<string, unknown>>;
  records: FormalMemoryRecord[];
  versions: FormalMemoryVersion[];
  read_logs: FormalMemoryReadLog[];
  authority: string;
};

export type ArtifactRepositoryRecord = {
  artifact_id: string;
  artifact_ref: string;
  path: string;
  repository_id: string;
  logical_repository_id: string;
  effective_repository_id: string;
  task_run_id: string;
  scope_kind: string;
  scope_id: string;
  collection_id: string;
  graph_id: string;
  stage_id: string;
  node_run_id: string;
  task_ref: string;
  graph_run_id: string;
  status: string;
  content_hash: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  authority: string;
};

export type ArtifactRepositoryOverview = {
  task_run_id: string;
  repository_id: string;
  collection_id: string;
  status: string;
  graph_run_id?: string;
  repository_count: number;
  artifact_count: number;
  repositories: Array<Record<string, unknown>>;
  artifacts: ArtifactRepositoryRecord[];
  authority: string;
};

export type MemoryOverview = {
  session_id: string;
  query: string;
  namespace_id?: string;
  durable_memory: {
    total: number;
    active: number;
    injectable: number;
    by_type: Record<string, number>;
    by_class: Record<string, number>;
    headers: MemoryHeader[];
    maintenance_runtime: Record<string, unknown>;
  };
  session_memory: MemorySessionInspect | null;
};

export type ProjectInstructionSource = {
  path: string;
  absolute_path: string;
  scope_root: string;
  source_kind: "project_instruction_file" | string;
  exists: boolean;
  loaded: boolean;
  editable: boolean;
  content: string;
  content_hash: string;
  mtime_ns: number;
  size_bytes: number;
};

export type ProjectInstructionManagement = {
  authority: string;
  project_root: string;
  canonical_filename: string;
  runtime_loader: {
    authority: string;
    loaded_filename: string;
    ignored_filenames: string[];
    scope_rule: string;
  };
  model_visibility: {
    sent_to_model: boolean;
    slot: string;
    message_role: string;
    cache_role: string;
    compression_role: string;
    memory_write_policy: string;
  };
  memory_relation: {
    managed_in_memory_console: boolean;
    durable_memory_note: boolean;
    semantic_memory_write: string;
    reason: string;
  };
  bundle: {
    prompt_ref?: string;
    source_count?: number;
    source_hash?: string;
    cache_scope?: string;
    sources?: Array<Record<string, unknown>>;
    authority?: string;
  };
  sources: ProjectInstructionSource[];
};

export type MemoryRecallPreview = {
  query: string;
  session_id: string;
  intent: {
    intent: string;
    read_mode: string;
    write_mode: string;
    explicit_read_inventory: boolean;
    ignore_memory: boolean;
    preferred_types: string[];
    preferred_memory_classes: string[];
  };
  selection: {
    should_recall: boolean;
    selected_note_ids: string[];
    reason: string;
    confidence: number;
    needs_verification: boolean;
    manifest_only: boolean;
    ignore_memory: boolean;
  };
  selected_headers: MemoryHeader[];
  selected_notes: Array<{
    note_id: string;
    filename: string;
    title: string;
    summary: string;
    canonical_statement: string;
    content_preview: string;
    memory_type: string;
    memory_class: string;
    confidence: string;
    status: string;
    retrieval_hints: string[];
    eligible_for_injection: boolean;
  }>;
  rendered_summary: string;
  context_result: MemorySessionInspect | null;
};

export type MemoryGovernanceResponse = {
  ok: boolean;
  action: string;
  filename: string;
  merged?: string[];
  deleted_at?: string;
  trash_path?: string;
  header?: MemoryHeader | null;
};

export type DurableMemoryNoteDetail = {
  header: MemoryHeader | null;
  content_preview: string;
  path: string;
  namespace_id?: string;
};

export type MemoryNamespaceScope = {
  namespace_id?: string;
  task_environment_id?: string;
};

export type StreamHandlers = {
  onEvent: (event: string, data: Record<string, unknown>) => void;
};

export type StreamResult = {
  terminalEvent: "turn_completed";
  terminalStatus: "completed" | "failed" | "stopped" | string;
  streamRunId: string;
  eventLogId: string;
  lastEventOffset: number;
};

export type ChatRun = {
  stream_run_id: string;
  session_id: string;
  event_log_id: string;
  root_request_ref: string;
  status: string;
  diagnostics?: Record<string, unknown>;
  latest_event_offset: number;
  active_turn_snapshot?: {
    turn_id?: string;
    turn_run_id?: string;
    bound_task_run_id?: string;
    task_run_id?: string;
    state?: string;
  } | null;
  is_reconnectable?: boolean;
  terminal_event?: string;
  stream_url: string;
};

export type LatestChatRunResult = ChatRun | null;

export type SessionContinuationRecord = {
  continuation_id?: string;
  session_id?: string;
  task_run_id?: string;
  state?: string;
  resume_allowed?: boolean;
  resume_strategy?: string;
  recovery_cause?: string;
  task_status?: string;
  user_visible_goal?: string;
  latest_progress?: string;
  event_cursor?: number;
  updated_at?: number;
  authority?: string;
  [key: string]: unknown;
};

export type SessionContinuationProjection = {
  session_id: string;
  available: boolean;
  record?: SessionContinuationRecord;
  reason?: string;
  authority?: string;
};

export type ChatStreamCursor = {
  streamRunId: string;
  eventLogId: string;
  lastEventOffset: number;
  lastEventId: string;
};

export type ToolPackageDefinition = {
  package_id: string;
  title: string;
  description: string;
  category: string;
  operation_ids: string[];
  risk_level: string;
  managed: boolean;
  default_enabled: boolean;
  tags: string[];
  metadata?: Record<string, unknown>;
};

export type OrchestrationSubagentPolicy = {
  enabled: boolean;
  allowed_subagent_ids: string[];
  max_subagent_runs_per_task: number;
  max_active_subagents: number;
  context_policy: string;
  result_policy: string;
  allow_nested_subagents: boolean;
};

const TURN_COMPLETED_EVENT = "turn_completed";
const TERMINAL_STREAM_EVENTS = new Set([TURN_COMPLETED_EVENT]);
const MAX_STREAM_BUFFER_CHARS = 1_000_000;
const CHAT_STREAM_RECONNECT_INITIAL_DELAY_MS = 500;
const CHAT_STREAM_RECONNECT_MAX_DELAY_MS = 30_000;

type ChatStreamError = Error & {
  status?: number;
  reconnectable?: boolean;
};

function nonReconnectableChatStreamError(message: string, status?: number): ChatStreamError {
  const error = new Error(message) as ChatStreamError;
  error.name = "ChatStreamProtocolError";
  error.reconnectable = false;
  if (status !== undefined) {
    error.status = status;
  }
  return error;
}

function chatStreamErrorMessage(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  return message || fallback;
}

function isReconnectableChatStreamTransportError(error: unknown) {
  if (error instanceof TypeError) {
    return true;
  }
  if (!error || typeof error !== "object") {
    return false;
  }
  const record = error as { name?: unknown; message?: unknown; reconnectable?: unknown };
  if (record.reconnectable === false) {
    return false;
  }
  const name = String(record.name ?? "");
  const message = String(record.message ?? "");
  return name === "AbortError"
    || name === "TimeoutError"
    || name === "NetworkError"
    || name === "RequestTimeoutError"
    || message.includes("Failed to fetch")
    || message.includes("NetworkError")
    || message.includes("Load failed")
    || message.includes("The network connection was lost");
}

function findSseBoundary(buffer: string): { index: number; length: number } | null {
  const boundaries = [
    { index: buffer.indexOf("\n\n"), length: 2 },
    { index: buffer.indexOf("\r\n\r\n"), length: 4 },
    { index: buffer.indexOf("\r\r"), length: 2 },
  ].filter((item) => item.index >= 0);
  if (!boundaries.length) {
    return null;
  }
  return boundaries.sort((left, right) => left.index - right.index)[0];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path, init);
}

function chatStreamCursorKey(sessionId: string) {
  return `chat.stream.cursor.${sessionId}`;
}

function browserStorage() {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

export function readChatStreamCursor(sessionId: string): ChatStreamCursor | null {
  const storage = browserStorage();
  if (!storage) return null;
  try {
    const raw = storage.getItem(chatStreamCursorKey(sessionId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ChatStreamCursor>;
    const streamRunId = String(parsed.streamRunId || "").trim();
    const eventLogId = String(parsed.eventLogId || "").trim();
    const lastEventOffset = Number(parsed.lastEventOffset ?? -1);
    const lastEventId = String(parsed.lastEventId || "").trim();
    if (!streamRunId || !eventLogId || !Number.isFinite(lastEventOffset)) {
      return null;
    }
    return { streamRunId, eventLogId, lastEventOffset, lastEventId };
  } catch {
    return null;
  }
}

export function saveChatStreamCursor(sessionId: string, cursor: ChatStreamCursor) {
  const storage = browserStorage();
  if (!storage) return;
  try {
    storage.setItem(chatStreamCursorKey(sessionId), JSON.stringify(cursor));
  } catch {
    // Storage can be unavailable in private or locked-down browser contexts.
  }
}

export function clearChatStreamCursor(sessionId: string) {
  const storage = browserStorage();
  if (!storage) return;
  try {
    storage.removeItem(chatStreamCursorKey(sessionId));
  } catch {
    // Storage cleanup is best-effort; the backend run remains authoritative.
  }
}

function delay(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export async function listSessions(scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  const query = params.toString();
  return request<SessionSummary[]>(query ? `/sessions?${query}` : "/sessions");
}

export async function createSession(
  title = "New Session",
  scope?: Partial<SessionScope>,
  projectBinding?: Pick<SessionProjectBinding, "workspace_root" | "source">,
) {
  return request<SessionSummary>("/sessions", {
    method: "POST",
    body: JSON.stringify({ title, ...(scope ? { scope } : {}), ...(projectBinding ? { project_binding: projectBinding } : {}) })
  });
}

export async function getSessionSummary(sessionId: string, scope?: Partial<SessionScope>) {
  return request<SessionSummary>(withSessionScopeQuery(`/sessions/${sessionId}`, scope));
}

export async function getWorkbenchCurrentSession() {
  return request<WorkbenchCurrentSessionPayload>("/workbench/current-session");
}

export async function setWorkbenchCurrentSession(ref: {
  sessionId: string;
  scope?: Partial<SessionScope>;
  poolKey?: string;
}) {
  return request<WorkbenchCurrentSessionPayload>("/workbench/current-session", {
    method: "PUT",
    body: JSON.stringify({
      session_id: ref.sessionId,
      scope: ref.scope ?? {},
      pool_key: ref.poolKey ?? "main-chat",
    }),
  });
}

export async function clearWorkbenchCurrentSession(sessionId?: string) {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  const query = params.toString();
  return request<WorkbenchCurrentSessionPayload>(query ? `/workbench/current-session?${query}` : "/workbench/current-session", {
    method: "DELETE",
  });
}

export async function renameSession(sessionId: string, title: string, scope?: Partial<SessionScope>) {
  return request<SessionSummary>(withSessionScopeQuery(`/sessions/${sessionId}`, scope), {
    method: "PUT",
    body: JSON.stringify({ title })
  });
}

export async function deleteSession(sessionId: string, scope?: Partial<SessionScope>) {
  return request<{ ok: boolean }>(withSessionScopeQuery(`/sessions/${sessionId}`, scope), {
    method: "DELETE"
  });
}

export async function getSessionHistory(sessionId: string, scope?: Partial<SessionScope>) {
  return request<SessionHistory>(withSessionScopeQuery(`/sessions/${sessionId}/history`, scope));
}

export async function getSessionConversationState(sessionId: string, scope?: Partial<SessionScope>) {
  return request<ConversationState>(withSessionScopeQuery(`/sessions/${sessionId}/conversation-state`, scope));
}

export async function setSessionActiveTaskEnvironment(
  sessionId: string,
  payload: {
    task_environment_id: string;
    environment_label?: string;
    source?: string;
  },
  scope?: Partial<SessionScope>,
) {
  return request<ConversationState>(withSessionScopeQuery(`/sessions/${sessionId}/active-task-environment`, scope), {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function setSessionPermissionMode(sessionId: string, mode: string, scope?: Partial<SessionScope>) {
  return request<ConversationState>(withSessionScopeQuery(`/sessions/${sessionId}/permission-mode`, scope), {
    method: "PUT",
    body: JSON.stringify({ mode }),
  });
}

export async function listProjectWorkspaces() {
  return request<{
    authority: string;
    projects: ProjectWorkspaceSummary[];
    summary: { project_count: number };
  }>("/project-workspaces");
}

export async function registerProjectWorkspace(payload: Pick<SessionProjectBinding, "workspace_root" | "source">) {
  return request<{
    authority: string;
    project: ProjectWorkspaceSummary;
  }>("/project-workspaces", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function selectProjectWorkspaceDirectory() {
  return request<{
    authority: string;
    project: ProjectWorkspaceSummary;
    selected_path: string;
  }>("/project-workspaces/select-directory", {
    method: "POST",
  });
}

export async function removeProjectWorkspace(projectKey: string, options: { detachSessions?: boolean } = {}) {
  const params = new URLSearchParams();
  params.set("detach_sessions", String(options.detachSessions ?? true));
  return request<{
    authority: string;
    project_key: string;
    ok: boolean;
    project: ProjectWorkspaceSummary;
    removed_registry_entry: boolean;
    detached_sessions: SessionSummary[];
    detached_session_count: number;
  }>(`/project-workspaces/${encodeURIComponent(projectKey)}?${params.toString()}`, {
    method: "DELETE",
  });
}

export async function listProjectWorkspaceSessions(projectKey: string) {
  return request<{
    authority: string;
    project_key: string;
    sessions: SessionSummary[];
  }>(`/project-workspaces/${encodeURIComponent(projectKey)}/sessions`);
}

export async function createProjectWorkspaceSession(projectKey: string, title = "New Session") {
  return request<{
    authority: string;
    project_key: string;
    session: SessionSummary;
    created: boolean;
  }>(`/project-workspaces/${encodeURIComponent(projectKey)}/sessions`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function getProjectWorkspaceTree(projectKey: string, options: { maxDepth?: number; maxEntries?: number } = {}) {
  const params = new URLSearchParams();
  params.set("max_depth", String(options.maxDepth || 10));
  params.set("max_entries", String(options.maxEntries || 10000));
  return request<CodeEnvironmentWorkspaceTree>(
    `/project-workspaces/${encodeURIComponent(projectKey)}/workspace-tree?${params.toString()}`
  );
}

export async function openProjectWorkspaceInVSCode(projectKey: string) {
  return request<{
    authority: string;
    ok: boolean;
    project: ProjectWorkspaceSummary;
    command: string[];
    window_mode: string;
  }>(`/project-workspaces/${encodeURIComponent(projectKey)}/open-vscode`, {
    method: "POST",
  });
}

export async function getSessionTimeline(sessionId: string, scope?: Partial<SessionScope>) {
  return request<SessionTimeline>(withSessionScopeQuery(`/sessions/${sessionId}/timeline`, scope));
}

export async function truncateSessionMessages(sessionId: string, messageIndex: number, scope?: Partial<SessionScope>) {
  return request<SessionTruncateResponse>(withSessionScopeQuery(`/sessions/${sessionId}/messages/truncate`, scope), {
    method: "POST",
    body: JSON.stringify({ message_index: messageIndex })
  });
}

export async function getSessionTokens(sessionId: string, scope?: Partial<SessionScope>) {
  return request<{
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
  }>(withSessionScopeQuery(`/tokens/session/${sessionId}`, scope));
}

export async function listSkills() {
  return request<Array<{ name: string; title: string; description: string; path: string }>>(
    "/skills"
  );
}

export async function getWorkspaceContext() {
  return request<WorkspaceContext>("/workspace/context");
}

export async function loadFile(path: string) {
  return request<{ path: string; content: string }>(`/files?path=${encodeURIComponent(path)}`);
}

export async function loadFileForSession(path: string, sessionId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  params.set("path", path);
  params.set("session_id", sessionId);
  return request<{ path: string; content: string }>(`/files?${params.toString()}`);
}

export async function saveFile(path: string, content: string) {
  return request<{ ok: boolean; path: string }>("/files", {
    method: "POST",
    body: JSON.stringify({ path, content })
  });
}

export async function saveFileForSession(path: string, content: string, sessionId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  params.set("session_id", sessionId);
  return request<{ ok: boolean; path: string }>(`/files?${params.toString()}`, {
    method: "POST",
    body: JSON.stringify({ path, content })
  });
}

export async function listFileChanges(params: { sessionId?: string; taskRunId?: string; status?: string; limit?: number } = {}) {
  const query = new URLSearchParams();
  if (params.sessionId) query.set("session_id", params.sessionId);
  if (params.taskRunId) query.set("task_run_id", params.taskRunId);
  if (params.status) query.set("status", params.status);
  if (params.limit) query.set("limit", String(params.limit));
  return request<{
    records: FileChangeRecord[];
    summary: { count: number };
    authority: string;
  }>(`/file-changes${query.toString() ? `?${query.toString()}` : ""}`);
}

export async function openFileChangeDiffInVSCode(sessionId: string, recordId: string) {
  return request<{
    ok: boolean;
    command?: {
      command_id?: string;
      type?: string;
      left_uri?: string;
      right_uri?: string;
      title?: string;
      record_id?: string;
    };
    connection_status?: { connected?: boolean; stale?: boolean };
    authority: string;
  }>(`/vscode/sessions/${encodeURIComponent(sessionId)}/file-change-diffs/open`, {
    method: "POST",
    body: JSON.stringify({ record_id: recordId }),
  });
}

export async function rollbackFileChange(recordId: string, options: { force?: boolean } = {}) {
  return request<{
    record: FileChangeRecord;
    rolled_back: boolean;
    authority: string;
  }>(`/file-changes/${encodeURIComponent(recordId)}/rollback`, {
    method: "POST",
    body: JSON.stringify({ force: Boolean(options.force) }),
  });
}

export async function getPermissionMode() {
  return request<{ mode: string; supported_modes: string[] }>("/config/permission-mode");
}

export async function setPermissionMode(mode: string) {
  return request<{ mode: string; supported_modes: string[] }>("/config/permission-mode", {
    method: "PUT",
    body: JSON.stringify({ mode })
  });
}

export async function getContextBudgetConfig() {
  return request<ContextBudgetConfig>("/config/context-budget");
}

export async function setContextBudgetPreset(presetId: string) {
  return request<ContextBudgetConfig>("/config/context-budget", {
    method: "PUT",
    body: JSON.stringify({ preset_id: presetId })
  });
}

export async function getModelProviderConfig() {
  return request<ModelProviderConfig>("/config/model-provider");
}

export async function getImageAssetConfig() {
  return request<ImageAssetConfig>("/image-assets/config");
}

export async function setModelProviderConfig(payload: {
  provider: string;
  model: string;
  base_url: string;
  api_key?: string;
}) {
  return request<ModelProviderConfig>("/config/model-provider", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getRuntimeConfigConsole() {
  return request<RuntimeConfigConsole>("/config/runtime-console");
}

export async function setRuntimeConfigGroup(groupId: string, values: Record<string, string | number | boolean>) {
  return request<RuntimeConfigConsole>("/config/runtime-console", {
    method: "PUT",
    body: JSON.stringify({ group_id: groupId, values })
  });
}

export async function getMemoryOverview(sessionId?: string, query = "", scope?: MemoryNamespaceScope) {
  const params = new URLSearchParams();
  if (sessionId) {
    params.set("session_id", sessionId);
  }
  if (query.trim()) {
    params.set("query", query.trim());
  }
  if (scope?.namespace_id?.trim()) {
    params.set("namespace_id", scope.namespace_id.trim());
  }
  if (scope?.task_environment_id?.trim()) {
    params.set("task_environment_id", scope.task_environment_id.trim());
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<MemoryOverview>(`/memory/overview${suffix}`);
}

export async function getProjectInstructionManagement() {
  return request<ProjectInstructionManagement>("/memory/project-instructions");
}

export async function saveProjectInstructionSource(path: string, content: string) {
  return request<ProjectInstructionManagement>("/memory/project-instructions", {
    method: "PUT",
    body: JSON.stringify({ path, content })
  });
}

export async function getFormalMemoryOverview(payload?: {
  task_run_id?: string;
  repository_id?: string;
  collection_id?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(payload ?? {})) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) params.set(key, text);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<FormalMemoryOverview>(`/memory/formal/overview${suffix}`);
}

export async function getArtifactRepositoryOverview(payload?: {
  task_run_id?: string;
  repository_id?: string;
  collection_id?: string;
  status?: string;
  graph_run_id?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(payload ?? {})) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) params.set(key, text);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<ArtifactRepositoryOverview>(`/memory/artifacts/overview${suffix}`);
}

export async function getSessionMemoryFiles(sessionId: string, scope?: Partial<SessionScope>) {
  return request<MemorySessionFilesResponse>(
    withSessionScopeQuery(`/memory/session/${encodeURIComponent(sessionId)}/files`, scope)
  );
}

export async function recallMemoryPreview(payload: { query: string; session_id?: string; limit?: number } & MemoryNamespaceScope) {
  return request<MemoryRecallPreview>("/memory/recall-preview", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createDurableMemory(payload: {
  title: string;
  canonical_statement: string;
  summary?: string;
  memory_type?: string;
  memory_class?: string;
  retrieval_hints?: string[];
  confidence?: string;
  source_kind?: string;
  source_message_excerpt?: string;
} & MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>("/memory/durable", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function disableDurableMemory(filename: string, reason = "", scope?: MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/disable`, {
    method: "POST",
    body: JSON.stringify({ reason, ...scope })
  });
}

export async function activateDurableMemory(filename: string, reason = "", scope?: MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/activate`, {
    method: "POST",
    body: JSON.stringify({ reason, ...scope })
  });
}

export async function archiveDurableMemory(filename: string, reason = "", scope?: MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/archive`, {
    method: "POST",
    body: JSON.stringify({ reason, ...scope })
  });
}

export async function deleteDurableMemory(filename: string, reason = "", scope?: MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}`, {
    method: "DELETE",
    body: JSON.stringify({ reason, ...scope })
  });
}

export async function getDurableMemoryNote(filename: string, scope?: MemoryNamespaceScope) {
  const params = new URLSearchParams();
  if (scope?.namespace_id?.trim()) params.set("namespace_id", scope.namespace_id.trim());
  if (scope?.task_environment_id?.trim()) params.set("task_environment_id", scope.task_environment_id.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<DurableMemoryNoteDetail>(`/memory/durable/${encodeURIComponent(filename)}${suffix}`);
}

export async function mergeDurableMemories(payload: {
  filenames: string[];
  title: string;
  canonical_statement: string;
  summary?: string;
  reason?: string;
} & MemoryNamespaceScope) {
  return request<MemoryGovernanceResponse>("/memory/durable/merge", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function runOrchestrationDryRun(payload: {
  session_id: string;
  message: string;
  explicit_subtasks?: Array<Record<string, unknown>>;
}) {
  return request<OrchestrationSnapshot>("/orchestration/dry-run", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getOrchestrationCatalog() {
  return request<OrchestrationCatalog>("/orchestration/catalog");
}

export async function refreshOrchestrationCatalog() {
  return request<OrchestrationCatalog>("/orchestration/catalog/refresh", {
    method: "POST"
  });
}

export async function setOrchestrationPlanMode(mode: string) {
  return request<{ mode: string; supported_modes: string[] }>("/orchestration/plan-mode", {
    method: "PUT",
    body: JSON.stringify({ mode })
  });
}

export async function getOrchestrationAgents(options: { includeOptions?: boolean } = {}) {
  const includeOptions = options.includeOptions ?? true;
  const suffix = includeOptions ? "" : "?include_options=false";
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agents${suffix}`);
}

export async function getOrchestrationRuntimeOptions() {
  return request<OrchestrationRuntimeOptionsPayload>("/orchestration/runtime-options");
}

export async function getOrchestrationCapabilityItems() {
  return request<{ authority: string; capability_items: OrchestrationCapabilityItem[] }>("/orchestration/capability-items");
}

export async function getNextOrchestrationWorkerAgentId() {
  return request<{ authority: string; agent_id: string }>("/orchestration/agents/next-worker-id");
}

export async function upsertOrchestrationAgent(agentId: string, payload: OrchestrationAgentUpsertPayload) {
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agents/${encodeURIComponent(agentId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteOrchestrationAgent(agentId: string) {
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agents/${encodeURIComponent(agentId)}`, {
    method: "DELETE"
  });
}

export async function upsertOrchestrationAgentGroup(groupId: string, payload: OrchestrationAgentGroupUpsertPayload) {
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agent-groups/${encodeURIComponent(groupId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteOrchestrationAgentGroup(groupId: string) {
  return request<OrchestrationAgentRuntimeCatalog>(`/orchestration/agent-groups/${encodeURIComponent(groupId)}`, {
    method: "DELETE"
  });
}

export async function updateOrchestrationAgentRuntimeProfile(
  agentId: string,
  payload: OrchestrationAgentRuntimeProfileUpsertPayload
) {
  return request<OrchestrationAgentRuntimeCatalog>(
    `/orchestration/agents/${encodeURIComponent(agentId)}/runtime-profile`,
    {
      method: "PUT",
      body: JSON.stringify(payload)
    }
  );
}

export async function listOrchestrationHarnessTaskRuns(sessionId: string) {
  return request<HarnessSessionTaskRuns>(
    `/orchestration/harness/sessions/${encodeURIComponent(sessionId)}/task-runs`
  );
}

export async function getRunMonitor(limit = 30) {
  return request<RuntimeMonitorEnvelope>(
    `/orchestration/runtime-monitor?limit=${encodeURIComponent(String(limit))}`
  );
}

export async function getRunMonitorManagement(limit = 80) {
  return request<{ authority: string; monitor: RuntimeMonitorEnvelope; management: RuntimeMonitorManagement; updated_at: number }>(
    `/orchestration/runtime-monitor/management?limit=${encodeURIComponent(String(limit))}`,
  );
}

export async function preflightRunMonitorAction(payload: RuntimeMonitorActionPayload) {
  return request<RuntimeMonitorActionResult>("/orchestration/runtime-monitor/actions/preflight", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function executeRunMonitorAction(payload: RuntimeMonitorActionPayload) {
  return request<RuntimeMonitorActionResult>("/orchestration/runtime-monitor/actions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getOrchestrationHarnessSessionLiveMonitor(sessionId: string) {
  return request<HarnessSessionLiveMonitor>(
    `/orchestration/runtime-monitor/sessions/${encodeURIComponent(sessionId)}`
  );
}

export async function getOrchestrationResourceInventory() {
  return request<RuntimeResourceInventory>("/orchestration/resource-inventory");
}

export async function getOrchestrationHarnessTrace(
  taskRunId: string,
  options?: {
    includePayloads?: boolean;
    includeModelMessages?: boolean;
    eventLimit?: number;
  }
) {
  const params = new URLSearchParams();
  if (options?.includePayloads) {
    params.set("include_payloads", "true");
  }
  if (options?.includeModelMessages) {
    params.set("include_model_messages", "true");
  }
  if (options?.eventLimit) {
    params.set("event_limit", String(options.eventLimit));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<HarnessTaskRunTrace>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}${suffix}`
  );
}

export async function getOrchestrationHarnessTurnTrace(
  turnRunId: string,
  options?: {
    includePayloads?: boolean;
    includeModelMessages?: boolean;
    eventLimit?: number;
  }
) {
  const params = new URLSearchParams();
  if (options?.includePayloads) {
    params.set("include_payloads", "true");
  }
  if (options?.includeModelMessages) {
    params.set("include_model_messages", "true");
  }
  if (options?.eventLimit) {
    params.set("event_limit", String(options.eventLimit));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<HarnessTurnRunTrace>(
    `/orchestration/harness/turn-runs/${encodeURIComponent(turnRunId)}${suffix}`
  );
}

export async function getOrchestrationHarnessTaskRunLiveMonitor(taskRunId: string) {
  return request<HarnessTaskRunLiveMonitor>(
    `/orchestration/runtime-monitor/task-runs/${encodeURIComponent(taskRunId)}`
  );
}

export async function pauseOrchestrationHarnessTaskRun(taskRunId: string, reason = "", expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/pause`,
    {
      method: "POST",
      body: JSON.stringify({ reason, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function resumeOrchestrationHarnessTaskRun(taskRunId: string, maxSteps = 12, expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify({ max_steps: maxSteps, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function approveOrchestrationHarnessTaskRunToolCall(taskRunId: string, reason = "", maxSteps = 12, expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/approve-tool-call`,
    {
      method: "POST",
      body: JSON.stringify({ reason, max_steps: maxSteps, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function stopOrchestrationHarnessTaskRun(taskRunId: string, reason = "", expectedActiveTurnId = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/stop`,
    {
      method: "POST",
      body: JSON.stringify({ reason, expected_active_turn_id: expectedActiveTurnId }),
    }
  );
}

export async function getHarnessTaskRunArtifacts(taskRunId: string) {
  return request<{
    authority: string;
    task_run_id: string;
    artifact_root: string;
    files: string[];
    created_files: string[];
    artifact_refs: string[];
  }>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/artifacts`
  );
}

export async function getHarnessTaskRunMemoryReceipts(taskRunId: string) {
  return request<{
    authority: string;
    task_run_id: string;
    memory_operations: Array<Record<string, unknown>>;
    stage_results: Array<Record<string, unknown>>;
  }>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/memory-receipts`
  );
}

export async function getProjectRuntimeStatus(projectId: string) {
  return request<ProjectRuntimeStatusView>(
    `/orchestration/projects/${encodeURIComponent(projectId)}/runtime-status`
  );
}

export async function startTaskGraphHarnessRun(
  graphId: string,
  payload: {
    session_id: string;
    task_id?: string;
    session_scope?: Partial<SessionScope>;
    initial_inputs?: Record<string, unknown>;
    include_trace?: boolean;
    dispatch_ready?: boolean;
    run_mode?: "dispatch_only" | "auto_run" | string;
    wait_for_completion?: boolean;
    runner_budget?: Record<string, unknown>;
    runtime_overrides?: Record<string, unknown>;
    runtime_settings_patch?: Record<string, unknown>;
  }
) {
  return request<TaskGraphRunStartResult>(
    `/orchestration/harness/task-graphs/${encodeURIComponent(graphId)}/start`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getPublishedTaskGraphHarnessConfig(graphId: string) {
  return request<GraphHarnessConfigPayload>(
    `/orchestration/harness/task-graphs/${encodeURIComponent(graphId)}/published-config`
  );
}

export async function submitGraphRunUntilIdle(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    session_scope?: Partial<SessionScope>;
    max_node_executions?: number;
    max_loop_iterations?: number;
    max_node_steps?: number;
    max_dispatches?: number;
    max_runtime_seconds?: number;
    max_dispatch_requests?: number | null;
  }
) {
  return request<GraphRunBackgroundSubmitResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/run-until-idle/background`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function pauseGraphRun(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    session_scope?: Partial<SessionScope>;
    reason?: string;
  }
) {
  return request<GraphRunControlResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/pause`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function resumeGraphRun(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    session_scope?: Partial<SessionScope>;
    reason?: string;
  }
) {
  return request<GraphRunControlResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getGraphRunMonitor(
  graphRunId: string,
  graphHarnessConfigId = "",
  eventLimit = 80,
  sessionScope?: Partial<SessionScope>,
) {
  const params = new URLSearchParams();
  if (graphHarnessConfigId) {
    params.set("graph_harness_config_id", graphHarnessConfigId);
  }
  if (sessionScope?.workspace_view) params.set("workspace_view", sessionScope.workspace_view);
  if (sessionScope?.task_environment_id) params.set("task_environment_id", sessionScope.task_environment_id);
  if (sessionScope?.project_id) params.set("project_id", sessionScope.project_id);
  params.set("event_limit", String(Math.max(1, Math.min(Number(eventLimit || 80), 240))));
  return request<GraphRunMonitorView>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/monitor?${params.toString()}`
  );
}

export async function listGraphTasks() {
  return request<GraphTaskDefinitionList>("/orchestration/graph-tasks");
}

export async function listGraphTaskInstances(graphId: string) {
  return request<GraphTaskInstanceList>(
    `/orchestration/graph-tasks/${encodeURIComponent(graphId)}/instances`
  );
}

export async function createGraphTaskInstance(
  graphId: string,
  payload: {
    title: string;
    description?: string;
    initial_inputs?: Record<string, unknown>;
    run_config?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
  }
) {
  return request<GraphTaskInstanceCreateResult>(
    `/orchestration/graph-tasks/${encodeURIComponent(graphId)}/instances`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getGraphTaskInstance(instanceId: string) {
  return request<GraphTaskInstanceDetail>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}`
  );
}

export async function startGraphTaskInstanceRun(
  instanceId: string,
  payload: {
    initial_inputs?: Record<string, unknown>;
    dispatch_ready?: boolean;
    run_mode?: "dispatch_only" | "auto_run" | string;
    wait_for_completion?: boolean;
    runner_budget?: Record<string, unknown>;
    runtime_overrides?: Record<string, unknown>;
    runtime_settings_patch?: Record<string, unknown>;
  } = {}
) {
  return request<GraphTaskInstanceRunStartResult>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/runs`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getGraphTaskInstanceMonitor(instanceId: string, eventLimit = 80) {
  const params = new URLSearchParams();
  params.set("event_limit", String(Math.max(1, Math.min(Number(eventLimit || 80), 240))));
  return request<GraphTaskInstanceMonitor>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/monitor?${params.toString()}`
  );
}

export async function getWritingGraphInstanceDesk(
  instanceId: string,
  eventLimit = 80,
  options: {
    includeRuntime?: boolean;
    includeFileTree?: boolean;
  } = {}
) {
  const params = new URLSearchParams();
  params.set("event_limit", String(Math.max(1, Math.min(Number(eventLimit || 80), 240))));
  if (options.includeRuntime !== undefined) params.set("include_runtime", String(options.includeRuntime));
  if (options.includeFileTree !== undefined) params.set("include_file_tree", String(options.includeFileTree));
  return request<WritingGraphInstanceDesk>(
    `/orchestration/writing-graph-instances/${encodeURIComponent(instanceId)}/desk?${params.toString()}`
  );
}

export async function submitWritingGraphChapterAction(
  instanceId: string,
  payload: WritingChapterActionRequest
) {
  return request<WritingChapterActionSubmitResult>(
    `/orchestration/writing-graph-instances/${encodeURIComponent(instanceId)}/chapter-actions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function listGraphTaskInstanceNodeSessions(instanceId: string) {
  return request<{
    authority: string;
    graph_task_instance_id: string;
    sessions: SessionSummary[];
    summary?: Record<string, unknown>;
  }>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/node-sessions`
  );
}

export async function getGraphTaskInstanceFileTree(
  instanceId: string,
  options: {
    path?: string;
    maxDepth?: number;
    maxEntries?: number;
  } = {}
) {
  const params = new URLSearchParams();
  if (options.path) params.set("path", options.path);
  if (options.maxDepth !== undefined) params.set("max_depth", String(options.maxDepth));
  if (options.maxEntries !== undefined) params.set("max_entries", String(options.maxEntries));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<GraphTaskInstanceFileTree>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/files/tree${suffix}`
  );
}

export async function readGraphTaskInstanceFile(instanceId: string, path: string) {
  const params = new URLSearchParams({ path });
  return request<GraphTaskInstanceFileReadResult>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/files?${params.toString()}`
  );
}

export async function writeGraphTaskInstanceFile(instanceId: string, path: string, content: string) {
  return request<GraphTaskInstanceFileWriteResult>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/files`,
    {
      method: "PUT",
      body: JSON.stringify({ path, content }),
    }
  );
}

export async function listGraphTaskInstanceArtifacts(instanceId: string) {
  return request<GraphTaskInstanceArtifacts>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/artifacts`
  );
}

export async function listGraphTaskInstanceHumanEdgeDecisions(instanceId: string, limit = 100) {
  const params = new URLSearchParams();
  params.set("limit", String(Math.max(1, Math.min(Number(limit || 100), 500))));
  return request<{
    authority: string;
    graph_task_instance_id: string;
    decisions: Array<Record<string, unknown>>;
    summary?: Record<string, unknown>;
  }>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/human-edge-decisions?${params.toString()}`
  );
}

export async function submitGraphTaskInstanceHumanEdgeDecision(
  instanceId: string,
  payload: HumanEdgeDecisionSubmitRequest
) {
  return request<HumanEdgeDecisionSubmitResult>(
    `/orchestration/graph-task-instances/${encodeURIComponent(instanceId)}/human-edge-decisions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function dispatchGraphRunReadyNodes(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    session_scope?: Partial<SessionScope>;
    max_requests?: number;
  }
) {
  return request<GraphRunDispatchReadyResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/dispatch-ready`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getCapabilitySystemCatalog() {
  return request<CapabilitySystemCatalog>("/capability-system/catalog");
}

export async function refreshCapabilitySystemCatalog() {
  return request<CapabilitySystemCatalog>("/capability-system/catalog/refresh", {
    method: "POST"
  });
}

export async function createCapabilitySystemSkill(payload: {
  name: string;
  title: string;
  description: string;
  content?: string;
}) {
  return request<CapabilitySystemCatalog>("/capability-system/skills", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function saveCapabilitySystemSkill(skillName: string, content: string) {
  return request<CapabilitySystemCatalog>(`/capability-system/skills/${encodeURIComponent(skillName)}`, {
    method: "PUT",
    body: JSON.stringify({ content })
  });
}

export async function updateCapabilitySystemSkillPromptView(
  skillName: string,
  payload: {
    title: string;
    capability: string;
    use_when: string;
    output_rule: string;
  }
) {
  return request<CapabilitySystemCatalog>(`/capability-system/skills/${encodeURIComponent(skillName)}/prompt-view`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteCapabilitySystemSkill(skillName: string) {
  return request<CapabilitySystemCatalog>(`/capability-system/skills/${encodeURIComponent(skillName)}`, {
    method: "DELETE"
  });
}

export async function updateCapabilitySystemTool(toolName: string, payload: { tool_type: string; note?: string; llm_description?: string }) {
  return request<CapabilitySystemCatalog>(`/capability-system/tools/${encodeURIComponent(toolName)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getMCPManagementCatalog() {
  return request<MCPManagementCatalog>("/mcp-system/management/catalog");
}

export async function upsertMCPManagementExternalServer(serverId: string, payload: ExternalMCPServerConfig) {
  return request<MCPManagementCatalog>(`/mcp-system/management/providers/external/servers/${encodeURIComponent(serverId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteMCPManagementExternalServer(serverId: string) {
  return request<MCPManagementCatalog>(`/mcp-system/management/providers/external/servers/${encodeURIComponent(serverId)}`, {
    method: "DELETE"
  });
}

export async function inspectMCPManagementServer(providerId: string, serverId: string) {
  return request<MCPManagementServer>(
    `/mcp-system/management/providers/${encodeURIComponent(providerId)}/servers/${encodeURIComponent(serverId)}/inspect`,
    {
      method: "POST"
    }
  );
}

export async function previewMCPManagementTool(
  providerId: string,
  serverId: string,
  toolName: string,
  argumentsPayload: Record<string, unknown>
) {
  return request<Record<string, unknown>>(
    `/mcp-system/management/providers/${encodeURIComponent(providerId)}/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}/preview`,
    {
      method: "POST",
      body: JSON.stringify({ arguments: argumentsPayload })
    }
  );
}

export async function callMCPManagementTool(
  providerId: string,
  serverId: string,
  toolName: string,
  argumentsPayload: Record<string, unknown>
) {
  return request<Record<string, unknown>>(
    `/mcp-system/management/providers/${encodeURIComponent(providerId)}/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}/call`,
    {
      method: "POST",
      body: JSON.stringify({ arguments: argumentsPayload })
    }
  );
}

export async function getCodeEnvironment(host?: {
  mode?: "web" | "desktop";
  localRuntimeAvailable?: boolean;
  codeEnvironmentHostAvailable?: boolean;
}) {
  const params = new URLSearchParams({
    host_mode: host?.mode || "web",
    local_runtime_available: String(Boolean(host?.localRuntimeAvailable)),
    code_environment_host_available: String(Boolean(host?.codeEnvironmentHostAvailable)),
  });
  return request<CodeEnvironmentStatus>(`/code-environment/environment?${params.toString()}`);
}

export async function getCodeEnvironmentWorkspaceTree(options: {
  maxDepth?: number;
  maxEntries?: number;
  sessionId?: string;
  scope?: Partial<SessionScope>;
} = {}) {
  const params = sessionScopeQuery(options.scope);
  params.set("max_depth", String(options.maxDepth || 10));
  params.set("max_entries", String(options.maxEntries || 10000));
  if (options.sessionId) {
    params.set("session_id", options.sessionId);
  }
  return request<CodeEnvironmentWorkspaceTree>(`/code-environment/workspace-tree?${params.toString()}`);
}

export async function openCodeEnvironmentWorkspaceRoot() {
  return request<{ authority: string; opened: boolean; path: string }>("/code-environment/open-workspace-root", {
    method: "POST",
  });
}

export async function getCodeEnvironmentGitStatus(options: { refresh?: boolean } = {}) {
  const params = new URLSearchParams();
  if (options.refresh) params.set("refresh", "true");
  const query = params.toString();
  return request<CodeEnvironmentGitStatus>(`/code-environment/git-status${query ? `?${query}` : ""}`);
}

export async function getPiSidecarStatus() {
  return request<PiSidecarLifecycleResponse>("/code-environment/sidecar/status");
}

export async function startPiSidecar() {
  return request<PiSidecarLifecycleResponse>("/code-environment/sidecar/start", { method: "POST" });
}

export async function stopPiSidecar() {
  return request<PiSidecarLifecycleResponse>("/code-environment/sidecar/stop", { method: "POST" });
}

export async function runPiSidecarReadOnlyCommand(command: "get_state" | "get_available_models") {
  return request<PiSidecarCommandResponse>("/code-environment/sidecar/read-only-command", {
    method: "POST",
    body: JSON.stringify({ command }),
  });
}

export async function getCapabilitySystemAgents() {
  return request<CapabilitySystemAgentCatalog>("/capability-system/agents");
}

export async function getTaskWorkflows() {
  return request<TaskWorkflowCatalog>("/tasks/workflows");
}

export async function upsertTaskWorkflow(workflowId: string, payload: TaskWorkflowUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/workflows/${encodeURIComponent(workflowId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getTaskSystemOverview() {
  return request<TaskSystemOverview>("/tasks/overview");
}

export async function upsertTaskSystemContract(contractId: string, payload: ContractSpecUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/contracts/${encodeURIComponent(contractId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemContract(contractId: string) {
  return request<TaskSystemOverview>(`/tasks/contracts/${encodeURIComponent(contractId)}`, {
    method: "DELETE"
  });
}

export async function compileTaskSystemTaskGraphContract(graphId: string) {
  return request<TaskGraphContractPreview>(
    `/tasks/task-graph-contracts/task-graphs/${encodeURIComponent(graphId)}/compile`
  );
}

export async function getTaskSystemTaskGraph(graphId: string) {
  return request<TaskGraphRecord>(`/tasks/task-graphs/${encodeURIComponent(graphId)}`);
}

export async function getTaskSystemTaskGraphStandardView(graphId: string) {
  return request<TaskGraphStandardView>(
    `/tasks/task-graphs/${encodeURIComponent(graphId)}/standard-view`
  );
}

export async function upsertTaskSystemTaskGraphStandardView(graphId: string, payload: TaskGraphStandardViewUpsertPayload) {
  return request<TaskGraphStandardView>(`/tasks/task-graphs/${encodeURIComponent(graphId)}/standard-view`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getTaskSystemNextIds() {
  return request<TaskSystemNextIds>("/tasks/next-ids");
}

export async function upsertTaskSystemEntryPolicy(profileId: string, payload: ConversationEntryPolicyUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/entry-policies/${encodeURIComponent(profileId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemDomain(domainId: string, payload: TaskDomainUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/domains/${encodeURIComponent(domainId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemDomain(domainId: string) {
  return request<TaskSystemOverview>(`/tasks/domains/${encodeURIComponent(domainId)}`, {
    method: "DELETE"
  });
}

export async function getTaskSystemEngagementPlans() {
  return request<EngagementPlanListResponse>("/tasks/engagement-plans");
}

export async function getTaskSystemEngagementPlan(planId: string) {
  return request<EngagementPlanDetailResponse>(`/tasks/engagement-plans/${encodeURIComponent(planId)}`);
}

export async function upsertTaskSystemEngagementPlan(planId: string, payload: EngagementPlanUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/engagement-plans/${encodeURIComponent(planId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemEngagementPlan(planId: string) {
  return request<TaskSystemOverview>(`/tasks/engagement-plans/${encodeURIComponent(planId)}`, {
    method: "DELETE"
  });
}

export async function startTaskSystemEngagementPlan(planId: string, payload: EngagementStartPayload = {}) {
  return request<EngagementStartResult>(`/tasks/engagement-plans/${encodeURIComponent(planId)}/start`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getTaskSystemEngagementRuns() {
  return request<EngagementRunListResponse>("/tasks/engagement-runs");
}

export async function getTaskSystemEngagementRun(engagementRunId: string) {
  return request<EngagementRunDetailResponse>(`/tasks/engagement-runs/${encodeURIComponent(engagementRunId)}`);
}

export async function syncTaskSystemEngagementRunCloseout(engagementRunId: string) {
  return request<EngagementRunCloseoutSyncResult>(`/tasks/engagement-runs/${encodeURIComponent(engagementRunId)}/sync-closeout`, {
    method: "POST"
  });
}

export async function upsertTaskSystemFlowContractBinding(taskId: string, payload: TaskFlowContractBindingUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/flow-contract-bindings/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemExecutionPolicy(taskId: string, payload: TaskExecutionPolicyUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/execution-policies/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemTaskAssignment(taskId: string, payload: TaskAssignmentUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/task-assignments/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemTaskAssignment(taskId: string) {
  return request<TaskSystemOverview>(`/tasks/task-assignments/${encodeURIComponent(taskId)}`, {
    method: "DELETE"
  });
}

export async function getTaskSystemEnvironmentProjects(environmentId: string) {
  return request<{
    authority: string;
    environment_id: string;
    projects: ProjectInstance[];
    summary: Record<string, number>;
  }>(`/tasks/environments/${encodeURIComponent(environmentId)}/projects`);
}

export async function listTaskEnvironmentSessions(environmentId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery({
    workspace_view: scope?.workspace_view ?? "task_environment",
    task_environment_id: environmentId,
    project_id: scope?.project_id,
  });
  return request<{ authority: string; scope: SessionScope; sessions: SessionSummary[] }>(
    `/task-environments/${encodeURIComponent(environmentId)}/sessions?${params.toString()}`
  );
}

export async function resolveTaskEnvironmentSession(
  environmentId: string,
  payload: TaskEnvironmentSessionResolvePayload
) {
  return request<TaskEnvironmentSessionResolveResponse>(
    `/task-environments/${encodeURIComponent(environmentId)}/sessions/resolve`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getTaskSystemEnvironmentTasks(environmentId: string) {
  return request<TaskEnvironmentTasksPayload>(`/tasks/environments/${encodeURIComponent(environmentId)}/tasks`);
}

export async function getTaskEnvironmentCatalog() {
  return request<TaskEnvironmentCatalog>("/tasks/environments/catalog");
}

export async function getTaskSystemProject(projectId: string) {
  return request<ProjectLibraryPayload>(`/tasks/projects/${encodeURIComponent(projectId)}`);
}

export async function getTaskSystemProjectRepositories(projectId: string) {
  return request<ProjectRepositoriesPayload>(`/tasks/projects/${encodeURIComponent(projectId)}/repositories`);
}

export async function getTaskSystemProjectLifecycleActions(projectId: string) {
  return request<ProjectLifecycleActionsPayload>(`/tasks/projects/${encodeURIComponent(projectId)}/lifecycle-actions`);
}

export async function getTaskSystemProjectRepositoryTree(
  projectId: string,
  repositoryId: string,
  options: { path?: string; maxDepth?: number; maxEntries?: number } = {}
) {
  const params = new URLSearchParams();
  if (options.path) params.set("path", options.path);
  if (options.maxDepth) params.set("max_depth", String(options.maxDepth));
  if (options.maxEntries) params.set("max_entries", String(options.maxEntries));
  const query = params.toString();
  return request<ProjectFileTreePayload>(
    `/tasks/projects/${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(repositoryId)}/tree${query ? `?${query}` : ""}`
  );
}

export async function getTaskSystemProjectRepositoryFile(projectId: string, repositoryId: string, path: string) {
  const params = new URLSearchParams({ path });
  return request<ProjectFilePayload>(
    `/tasks/projects/${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(repositoryId)}/files?${params.toString()}`
  );
}

export async function previewTaskSystemProjectLifecycle(projectId: string, action: string) {
  return request<ProjectLifecyclePreviewPayload>(
    `/tasks/projects/${encodeURIComponent(projectId)}/lifecycle-preview/${encodeURIComponent(action)}`
  );
}

export async function startTaskSystemProjectLifecycleRun(projectId: string, payload: { action: string; execute?: boolean; metadata?: Record<string, unknown> }) {
  return request<ProjectLifecycleRunPayload>(`/tasks/projects/${encodeURIComponent(projectId)}/lifecycle-runs`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemEnvironmentGroup(groupId: string, payload: TaskEnvironmentGroupUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/environment-groups/${encodeURIComponent(groupId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getTaskSystemEnvironmentKindTemplates() {
  return request<{ authority: string; kind_templates: TaskEnvironmentKindTemplate[]; summary: Record<string, number> }>("/tasks/environment-kind-templates");
}

export async function upsertTaskSystemEnvironmentKindTemplate(kindId: string, payload: TaskEnvironmentKindTemplateUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/environment-kind-templates/${encodeURIComponent(kindId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemEnvironmentKindTemplate(kindId: string) {
  return request<TaskSystemOverview>(`/tasks/environment-kind-templates/${encodeURIComponent(kindId)}`, {
    method: "DELETE"
  });
}

export async function upsertTaskSystemEnvironment(environmentId: string, payload: TaskEnvironmentUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/environments/${encodeURIComponent(environmentId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemEnvironment(environmentId: string) {
  return request<TaskSystemOverview>(`/tasks/environments/${encodeURIComponent(environmentId)}`, {
    method: "DELETE"
  });
}

export async function getTaskSystemNodeConfigurations() {
  return request<NonNullable<TaskSystemOverview["node_configuration_management"]>>("/tasks/node-configurations");
}

export async function upsertTaskSystemNodeConfiguration(nodeConfigId: string, payload: TaskNodeConfigurationUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/node-configurations/${encodeURIComponent(nodeConfigId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemNodeConfiguration(nodeConfigId: string) {
  return request<TaskSystemOverview>(`/tasks/node-configurations/${encodeURIComponent(nodeConfigId)}`, {
    method: "DELETE"
  });
}

export async function previewTaskSystemNodeConfigurationRuntime(nodeConfigId: string, payload: { environment_id?: string; graph_id?: string } = {}) {
  return request<Record<string, unknown>>(`/tasks/node-configurations/${encodeURIComponent(nodeConfigId)}/runtime-preview`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemTaskGraph(graphId: string, payload: TaskGraphUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/task-graphs/${encodeURIComponent(graphId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function getHealthSystemOverview() {
  return request<HealthSystemOverview>("/health-system/overview");
}

export async function getHealthSystemTasks(limit = 100) {
  return request<{
    authority: string;
    tasks: HealthTaskRecord[];
    summary: Record<string, number>;
    updated_at: number;
  }>(`/health-system/tasks?limit=${limit}`);
}

export async function getHealthSystemTaskDetail(taskRunId: string) {
  return request<{
    authority: string;
    task: HealthTaskRecord;
    monitor: Record<string, unknown>;
    task_graph_monitor: Record<string, unknown>;
    risks: HealthRiskEvent[];
    recent_events: Array<Record<string, unknown>>;
    updated_at: number;
  }>(`/health-system/tasks/${encodeURIComponent(taskRunId)}`);
}

export async function getHealthSystemTaskRecordMaintenance(bucket = "static", minAgeSeconds = 24 * 60 * 60) {
  return request<HealthTaskRecordMaintenance>(
    `/health-system/task-records/maintenance?bucket=${encodeURIComponent(bucket)}&min_age_seconds=${minAgeSeconds}`,
  );
}

export async function pruneHealthSystemTaskRecords(payload: {
  bucket?: "static" | "completed" | "failed" | "diagnostics" | string;
  task_run_ids?: string[];
  dry_run?: boolean;
  min_age_seconds?: number;
  operation?: string;
}) {
  return request<HealthTaskRecordPruneResult>("/health-system/task-records/prune", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getHealthSystemMonitorGovernance() {
  return request<HealthMonitorGovernance>("/health-system/monitor-governance");
}

export async function getHealthSystemRisks(limit = 100) {
  return request<{
    authority: string;
    risks: HealthRiskEvent[];
    summary: Record<string, number>;
    updated_at: number;
  }>(`/health-system/risks?limit=${limit}`);
}

export async function getHealthSystemTokenUsage(limit = 100) {
  return request<HealthTokenUsage>(`/health-system/token-usage?limit=${limit}`);
}

export async function getHealthSystemEfficiency(limit = 100) {
  return request<HealthEfficiency>(`/health-system/efficiency?limit=${limit}`);
}

export async function createHealthAgentConversationSession(payload: {
  active_issue_ref?: string;
  active_run_ref?: string;
}) {
  return request<{
    authority: string;
    session: HealthAgentConversationSession;
    messages: HealthAgentConversationMessage[];
  }>("/health-system/conversation-sessions", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function sendHealthAgentConversationMessage(
  sessionId: string,
  payload: {
    role?: "user" | "assistant" | "system" | string;
    content: string;
    command_ref?: string;
    receipt_ref?: string;
    report_ref?: string;
  }
) {
  return request<{
    authority: string;
    message: HealthAgentConversationMessage;
    assistant_message: HealthAgentConversationMessage | null;
  }>(`/health-system/conversation-sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function createHealthManagementCommand(payload: {
  command_type: string;
  initiator_type: "user" | "agent" | "system" | "test_system" | string;
  initiator_ref?: string;
  requested_by?: string;
  source?: string;
  conversation_session_ref?: string;
  target_scope?: string;
  target_ref?: string;
  health_action?: string;
  payload?: Record<string, unknown>;
}) {
  return request<HealthCommandResponse>("/health-system/commands", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getHealthManagementReceipt(receiptId: string) {
  return request<HealthManagementReceipt>(`/health-system/receipts/${encodeURIComponent(receiptId)}`);
}

export async function listHealthReports() {
  return request<{ authority: string; reports: HealthReport[] }>("/health-system/reports");
}

export async function createHealthIssue(payload: {
  title: string;
  owner_system?: string;
  severity?: string;
  status?: string;
  source?: string;
  conversation_ref?: string;
  runtime_trace_refs?: string[];
  prompt_manifest_refs?: string[];
  memory_refs?: string[];
  assertion_refs?: string[];
  metadata?: Record<string, unknown>;
}) {
  return request<HealthIssue>("/health-system/issues", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function getHealthAgentRunResult(runId: string) {
  return request<Record<string, unknown>>(`/health-system/agent-runs/${encodeURIComponent(runId)}/result`);
}

export async function getHealthAgentRunTraceReport(runId: string) {
  return request<HealthTraceReport>(`/health-system/agent-runs/${encodeURIComponent(runId)}/trace-report`);
}

export async function previewHealthAgentRun(issueId: string, healthAction = "issue_triage") {
  return request<HealthAgentRunPreview>(
    `/health-system/issues/${encodeURIComponent(issueId)}/agent-runs/preview`,
    {
      method: "POST",
      body: JSON.stringify({ health_action: healthAction })
    }
  );
}

export type ChatRunCreatePayload = {
  message: string;
  session_id: string;
  session_scope?: Partial<SessionScope>;
  environment_binding?: Record<string, unknown>;
  runtime_contract?: Record<string, unknown>;
  model_selection?: Record<string, unknown>;
  image_generation?: Record<string, unknown>;
  attachments?: ChatAttachment[];
  permission_mode?: string;
  expected_active_turn_id?: string;
  active_turn_input_policy?: string;
  expected_task_run_id?: string;
  expected_continuation_id?: string;
  recovery_input_policy?: string;
  editor_context?: Record<string, unknown>;
};

export async function uploadChatAttachment(sessionId: string, file: File) {
  const formData = new FormData();
  formData.set("session_id", sessionId);
  formData.set("file", file);
  return request<ChatAttachment>("/chat/attachments", {
    method: "POST",
    body: formData,
  });
}

export async function createChatRun(payload: ChatRunCreatePayload) {
  return request<ChatRun>("/chat/runs", {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      stream: true,
    }),
  });
}

export async function getChatRun(streamRunId: string) {
  return request<ChatRun>(`/chat/runs/${encodeURIComponent(streamRunId)}`);
}

export async function getLatestChatRunForSession(sessionId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  params.set("active_only", "true");
  return request<LatestChatRunResult>(`/chat/sessions/${encodeURIComponent(sessionId)}/latest-run?${params.toString()}`);
}

export async function getLatestSessionContinuation(sessionId: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  const query = params.toString();
  return request<SessionContinuationProjection>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/continuations/latest${query ? `?${query}` : ""}`,
  );
}

export async function resumeChatRun(streamRunId: string) {
  return request<ChatRun & { resume_mode: string }>(`/chat/runs/${encodeURIComponent(streamRunId)}/resume`, {
    method: "POST",
  });
}

function parseSseBlock(block: string): { id: string; event: string; data: Record<string, unknown> } | null {
  const lines = block.split(/\r?\n|\r/);
  let id = "";
  let event = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("id:")) {
      id = line.slice(3).trim();
    } else if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (!dataLines.length) {
    return null;
  }
  return {
    id,
    event,
    data: JSON.parse(dataLines.join("\n")) as Record<string, unknown>,
  };
}

function terminalStatusFromTurnCompleted(data: Record<string, unknown>) {
  const status = String(data.status ?? "").trim().toLowerCase();
  if (status === "failed" || status === "stopped" || status === "completed") {
    return status;
  }
  return "completed";
}

async function consumeChatRunStream(
  run: ChatRun,
  sessionId: string,
  handlers: StreamHandlers,
  options: {
    signal?: AbortSignal;
    initialCursor?: ChatStreamCursor | null;
    replayFromStart?: boolean;
    persistCursor?: boolean;
  } = {}
): Promise<StreamResult> {
  const persistCursor = options.persistCursor !== false;
  let lastEventOffset = options.replayFromStart
    ? -1
    : Number(options.initialCursor?.lastEventOffset ?? run.latest_event_offset ?? -1);
  let lastEventId = options.replayFromStart ? "" : String(options.initialCursor?.lastEventId || "");
  let terminalEvent: StreamResult["terminalEvent"] | "" = "";
  let terminalStatus: StreamResult["terminalStatus"] = "";
  let reconnectAttempt = 0;

  if (persistCursor) {
    saveChatStreamCursor(sessionId, {
      streamRunId: run.stream_run_id,
      eventLogId: run.event_log_id,
      lastEventOffset,
      lastEventId,
    });
  }

  const consumeBlock = (block: string) => {
    const parsed = parseSseBlock(block);
    if (!parsed) {
      return "";
    }
    const eventOffset = Number(parsed.data.event_offset);
    if (Number.isFinite(eventOffset)) {
      if (eventOffset <= lastEventOffset) {
        return parsed.event;
      }
      lastEventOffset = eventOffset;
      lastEventId = parsed.id || `${run.stream_run_id}:${run.event_log_id}:${lastEventOffset}`;
      if (persistCursor) {
        saveChatStreamCursor(sessionId, {
          streamRunId: run.stream_run_id,
          eventLogId: run.event_log_id,
          lastEventOffset,
          lastEventId,
        });
      }
    }
    if (reconnectAttempt > 0) {
      handlers.onEvent("stream_reconnected", {
        stream_run_id: run.stream_run_id,
        event_log_id: run.event_log_id,
        event_offset: lastEventOffset,
        attempt: reconnectAttempt,
      });
      reconnectAttempt = 0;
    }
    handlers.onEvent(parsed.event, parsed.data);
    if (TERMINAL_STREAM_EVENTS.has(parsed.event)) {
      terminalStatus = terminalStatusFromTurnCompleted(parsed.data);
    }
    return parsed.event;
  };

  while (!terminalEvent) {
    if (options.signal?.aborted) {
      if (persistCursor) {
        clearChatStreamCursor(sessionId);
      }
      throw new DOMException("Aborted", "AbortError");
    }
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    let readerClosed = false;
    let readerCancelled = false;
    let reconnectReason = "stream_closed_without_terminal";
    try {
      const params = new URLSearchParams({ after_offset: String(lastEventOffset) });
      const response = await fetch(`${getApiBase()}/chat/runs/${encodeURIComponent(run.stream_run_id)}/events?${params.toString()}`, {
        method: "GET",
        headers: lastEventId ? { "Last-Event-ID": lastEventId } : undefined,
        signal: options.signal,
      });

      if (!response.ok) {
        throw nonReconnectableChatStreamError(`Chat stream request failed: ${response.status}`, response.status);
      }
      if (!response.body) {
        throw nonReconnectableChatStreamError("Chat stream response did not include a readable body.");
      }

      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        if (buffer.length > MAX_STREAM_BUFFER_CHARS) {
          throw new Error("Chat stream SSE buffer exceeded 1MB without a complete event boundary.");
        }

        let boundary = findSseBoundary(buffer);
        while (boundary) {
          const event = consumeBlock(buffer.slice(0, boundary.index));
          buffer = buffer.slice(boundary.index + boundary.length);
          if (TERMINAL_STREAM_EVENTS.has(event)) {
            terminalEvent = event as StreamResult["terminalEvent"];
            break;
          }
          boundary = findSseBoundary(buffer);
        }

        if (terminalEvent) {
          if (!done) {
            await reader.cancel().catch(() => undefined);
            readerCancelled = true;
          } else {
            readerClosed = true;
          }
          break;
        }

        if (done) {
          readerClosed = true;
          if (buffer.trim()) {
            const event = consumeBlock(buffer);
            if (TERMINAL_STREAM_EVENTS.has(event)) {
              terminalEvent = event as StreamResult["terminalEvent"];
            }
          }
          break;
        }
      }
    } catch (error) {
      if (options.signal?.aborted) {
        if (persistCursor) {
          clearChatStreamCursor(sessionId);
        }
        throw error;
      }
      if (!isReconnectableChatStreamTransportError(error)) {
        handlers.onEvent("stream_reconnect_failed", {
          stream_run_id: run.stream_run_id,
          event_log_id: run.event_log_id,
          event_offset: lastEventOffset,
          last_event_id: lastEventId,
          attempt: reconnectAttempt,
          reason: chatStreamErrorMessage(error, "stream_protocol_error"),
        });
        throw error;
      }
      reconnectReason = chatStreamErrorMessage(error, "stream_transport_error");
    } finally {
      if (reader && !readerClosed && !readerCancelled) {
        await reader.cancel().catch(() => undefined);
      }
    }

    if (!terminalEvent) {
      reconnectAttempt += 1;
      handlers.onEvent("stream_reconnecting", {
        stream_run_id: run.stream_run_id,
        event_log_id: run.event_log_id,
        event_offset: lastEventOffset,
        last_event_id: lastEventId,
        attempt: reconnectAttempt,
        reason: reconnectReason,
      });
      const reconnectDelay = Math.min(
        CHAT_STREAM_RECONNECT_MAX_DELAY_MS,
        CHAT_STREAM_RECONNECT_INITIAL_DELAY_MS * 2 ** Math.min(Math.max(0, reconnectAttempt - 1), 6),
      );
      await delay(reconnectDelay, options.signal);
    }
  }

  if (persistCursor) {
    clearChatStreamCursor(sessionId);
  }

  return {
    terminalEvent,
    terminalStatus: terminalStatus || "completed",
    streamRunId: run.stream_run_id,
    eventLogId: run.event_log_id,
    lastEventOffset,
  };
}

export async function streamExistingChatRun(
  sessionId: string,
  streamRunId: string,
  handlers: StreamHandlers,
  options: {
    signal?: AbortSignal;
    initialCursor?: ChatStreamCursor | null;
    replayFromStart?: boolean;
    persistCursor?: boolean;
  } = {}
) {
  const run = await resumeChatRun(streamRunId);
  return consumeChatRunStream(run, sessionId, handlers, options);
}

export async function streamChat(
  payload: ChatRunCreatePayload,
  handlers: StreamHandlers,
  options: {
    signal?: AbortSignal;
    persistCursor?: boolean;
  } = {}
): Promise<StreamResult> {
  const run = await createChatRun(payload);
  return consumeChatRunStream(run, payload.session_id, handlers, options);
}
