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
  plan_id?: string;
  todo_items?: PublicTodoItem[];
  active_item_id?: string;
  completion_ready?: boolean;
};

export type PublicProjectionFrame = {
  authority: "harness.public_projection" | string;
  contract_revision?: "20260614-dual-channel-v1" | string;
  frame_id: string;
  projection_id?: string;
  source_event_id?: string;
  source_event_type?: string;
  event_log_id?: string;
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
  plan_id?: string;
  todo_items?: PublicTodoItem[];
  active_item_id?: string;
  completion_ready?: boolean;
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
  projection_slices?: ProjectionSlice[];
  artifact_refs?: Array<Record<string, unknown>>;
  trace_available?: boolean;
  debug_trace_ref?: string;
  created_at?: number;
  updated_at?: number;
};

export type ProjectionSlice = {
  slice_id: string;
  schema_version: "chronological_projection" | string;
  event_log_id: string;
  start_offset: number;
  end_offset: number;
  projection_key?: {
    session_id?: string;
    turn_id?: string;
    message_id?: string;
    stream_run_id?: string;
    run_id?: string;
    task_run_id?: string;
    turn_run_id?: string;
    event_log_id?: string;
  };
  cursor?: {
    min_event_offset?: number;
    max_event_offset?: number;
    frame_count?: number;
  };
  frames: PublicProjectionFrame[];
  display_hint?: {
    lifecycle?: "running" | "committed" | "failed" | "stopped" | "log_only" | string;
    main_surface_hint?: "live" | "committed" | "closeout" | "recovery" | "log_only" | string;
    closeout_summary?: string;
    log_ref?: string;
    tool_event_count?: number;
  };
  authority?: string;
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
