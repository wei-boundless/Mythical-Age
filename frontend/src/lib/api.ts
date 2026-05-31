import { apiRequest, getApiBase, getRuntimeMonitorEventStreamUrl } from "./api/client";

export { getApiBase, getRuntimeMonitorEventStreamUrl, isRequestAbortError } from "./api/client";

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
};

export type SessionHistory = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  compressed_context?: string;
  messages: Array<{
    role: "user" | "assistant";
    content: string;
    tool_calls?: ToolCall[];
    image?: {
      src: string;
      alt?: string;
      caption?: string;
    } | null;
  }>;
};

export type SessionRuntimeAttachment = {
  attachment_id: string;
  anchor_turn_id: string;
  task_run_id: string;
  task_id?: string;
  status: string;
  terminal_reason?: string;
  lifecycle?: string;
  bucket?: string;
  title?: string;
  summary?: string;
  latest_step?: Record<string, unknown>;
  latest_step_summary?: string;
  latest_public_progress_note?: string;
  agent_brief_output?: string;
  latest_event_type?: string;
  event_count?: number;
  progress_entries?: Array<Record<string, unknown>>;
  artifact_refs?: Array<Record<string, unknown>>;
  final_answer?: string;
  trace_available?: boolean;
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

export type CodeEnvironmentGitStatus = {
  authority: string;
  available: boolean;
  branch: string;
  items: Array<{ status: string; path: string }>;
  changed_count?: number;
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
  topology_refs: string[];
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
  default_soul_id?: string;
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
  topology_template_id: string;
  display_numbers: {
    task: string;
    flow: string;
    workflow: string;
    graph: string;
    topology: string;
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
  runtime_mode: "role" | "standard" | "professional" | "custom" | string;
  runtime_mode_policy?: Record<string, unknown>;
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
  diagnostics: Record<string, unknown>;
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

export type TopologyTemplate = {
  template_id: string;
  title: string;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  handoff_rules: Array<Record<string, unknown>>;
  join_policy: string;
  failure_policy: string;
  terminal_policy: string;
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
    topology_count: number;
  };
  diagnostics: Record<string, unknown>;
};

export type TaskSystemOverview = {
  authority: string;
  summary: Record<string, number>;
  task_environment_management?: {
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
    topology_templates?: TopologyTemplate[];
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

export type OrchestrationAgentRuntimeProfile = {
  agent_profile_id: string;
  agent_id: string;
  enabled_runtime_modes?: string[];
  default_runtime_mode?: string;
  allowed_tool_packages?: Array<{
    package_id: string;
    enabled: boolean;
    include_operations: string[];
    exclude_operations: string[];
  }>;
  extra_allowed_operations?: string[];
  allowed_operations: string[];
  final_allowed_operations?: string[];
  blocked_operations: string[];
  allowed_memory_scopes: string[];
  allowed_context_sections: string[];
  use_shared_contract: boolean;
  can_delegate_to_agents: boolean;
  allowed_delegate_agent_ids: string[];
  max_delegate_calls_per_turn: number;
  delegate_context_policy: string;
  approval_policy: string;
  trace_policy: string;
  lifecycle_policy: string;
  model_profile?: OrchestrationAgentModelProfile;
  metadata?: Record<string, unknown>;
  runtime_mode_catalog?: Array<Record<string, unknown>>;
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
    runtime_modes?: Array<Record<string, unknown>>;
    default_runtime_mode?: string;
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
    model_provider_catalog?: ModelProviderCatalog;
  };
};

export type OrchestrationAgentRuntimeProfileUpsertPayload = Omit<OrchestrationAgentRuntimeProfile, "agent_id">;

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

export type ProjectionTemplateCatalog = {
  authority: string;
  templates: Array<Record<string, unknown>>;
  summary: Record<string, number>;
};

export type TaskGraphTemplateCatalog = {
  authority: string;
  templates: Array<Record<string, unknown>>;
  summary: Record<string, unknown>;
};

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
  six_hour: Array<Record<string, unknown>>;
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
  monitor: GlobalRuntimeMonitor | Record<string, unknown>;
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
  monitor: GlobalRuntimeMonitor | Record<string, unknown>;
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

export type SoulImageAssetConfig = {
  configured: boolean;
  base_url: string;
  model: string;
  api_key_present: boolean;
  public_dir: string;
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
  task_run_id: string;
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

export type GlobalRuntimeMonitorItem = {
  task_run_id: string;
  session_id: string;
  task_id: string;
  execution_runtime_kind: string;
  task_instance_id?: string;
  root_task_run_id?: string;
  kind?: "chat_turn" | "agent_run" | "task_graph" | string;
  graph_run_id?: string;
  graph_harness_config_id?: string;
  title: string;
  status: string;
  terminal_reason: string;
  created_at?: number;
  updated_at?: number;
  started_at: number;
  ended_at?: number | null;
  duration_seconds: number;
  elapsed_seconds: number;
  runtime_seconds?: number;
  runtime_end_at?: number;
  lifecycle: "running" | "waiting" | "action_required" | "completed" | "failed" | "stale" | string;
  bucket: "running" | "completed" | "failed" | "diagnostics" | string;
  resource_class: "dynamic" | "static" | string;
  last_activity_at?: number;
  last_activity_age_seconds?: number;
  action_required?: boolean;
  terminal?: boolean;
  stale?: boolean;
  runtime_control?: Record<string, unknown>;
  control_state?: string;
  is_live?: boolean;
  summary?: string;
  latest_step?: Record<string, unknown>;
  latest_progress?: {
    tool_status?: string;
    observation?: string;
    current_judgment?: string;
    summary?: string;
    next_action?: string;
    completion_status?: string;
    agent_brief?: string;
  } | Record<string, unknown>;
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
  latest_event_type: string;
  latest_event_at: number;
  event_count: number;
  graph_id: string;
  active_node_id: string;
  project_id: string;
  project_title: string;
  project_runtime_status: Record<string, unknown> | null;
  has_graph_run: boolean;
  route: {
    kind?: "chat_turn_runtime" | "agent_runtime_run" | "task_graph_run" | string;
    session_id?: string;
    task_run_id?: string;
    graph_id?: string;
    graph_run_id?: string;
    graph_harness_config_id?: string;
  };
};

export type GlobalRuntimeMonitor = {
  authority: string;
  scope?: string;
  summary: {
    total: number;
    running: number;
    waiting?: number;
    blocked?: number;
    completed: number;
    failed: number;
    diagnostics?: number;
    action_required?: number;
  };
  buckets: {
    running: GlobalRuntimeMonitorItem[];
    completed: GlobalRuntimeMonitorItem[];
    failed: GlobalRuntimeMonitorItem[];
    diagnostics: GlobalRuntimeMonitorItem[];
  };
  bucket_limit?: number;
  revision?: string;
  items?: GlobalRuntimeMonitorItem[];
  selected?: GlobalRuntimeMonitorItem | Record<string, unknown> | null;
  events?: Array<Record<string, unknown>>;
  task_runs: GlobalRuntimeMonitorItem[];
  updated_at: number;
};

export type RuntimeMonitorEventPayload = {
  source?: string;
  monitor?: GlobalRuntimeMonitor;
  runtime_event?: {
    event_id: string;
    task_run_id: string;
    event_type: string;
    offset: number;
    created_at: number;
    payload: Record<string, unknown>;
    refs: Record<string, unknown>;
    authority: string;
  };
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
  kind?: "chat_turn" | "agent_run" | "task_graph" | string;
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
  task_run_id: string;
  task_run: Record<string, unknown>;
  graph_run: Record<string, unknown>;
  checkpoint: Record<string, unknown>;
  graph_loop_state: Record<string, unknown>;
  graph_harness_config: Record<string, unknown>;
  node_work_orders: Array<Record<string, unknown>>;
  runner_result: GraphRunUntilIdleResult | null;
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
  events: Array<Record<string, unknown>>;
  event_count: number;
  event_window?: {
    kind?: string;
    limit?: number;
    returned?: number;
  };
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

export type GraphNodeResultAcceptResult = {
  authority: string;
  graph_run_id: string;
  graph_harness_config_id: string;
  accepted_result: Record<string, unknown> | null;
  graph_result: Record<string, unknown> | null;
  graph_loop_state: Record<string, unknown>;
  checkpoint: Record<string, unknown>;
  node_work_orders: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
};

export type GraphWorkOrderExecuteResult = {
  authority: string;
  graph_run_id: string;
  graph_harness_config_id: string;
  work_order: Record<string, unknown>;
  node_result: Record<string, unknown>;
  node_executor_task_run: Record<string, unknown> | null;
  executor_result: Record<string, unknown>;
  accepted_result: Record<string, unknown> | null;
  graph_result: Record<string, unknown> | null;
  graph_loop_state: Record<string, unknown>;
  checkpoint: Record<string, unknown>;
  node_work_orders: Array<Record<string, unknown>>;
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
    search_policy: string[];
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
  mcp_management?: Record<string, unknown>;
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

export type SoulSystemFile = {
  path: string;
  label: string;
  role: string;
  model_visible: boolean;
  injection_order: number | null;
  content: string;
  chars: number;
  updated_at: number | null;
};

export type SoulSystemSeed = SoulSystemFile & {
  key: string;
  soul_id?: string;
  name: string;
  source?: "builtin" | "user" | string;
  enabled?: boolean;
  active: boolean;
  portrait_path: string;
  portrait_updated_at: number | null;
  profile?: SoulProfile;
};

export type SoulProfile = {
  soul_id: string;
  name: string;
  display_name: string;
  source: "builtin" | "user" | string;
  version: string;
  enabled: boolean;
  seed_path: string;
  description: string;
  background: string;
  personality_traits: string[];
  expression_style: string[];
  preferred_role_types: string[];
  preferred_task_modes: string[];
  collaboration_tendencies: string[];
  memory_preferences: string[];
  risk_biases: string[];
  guardrails: string[];
  portrait: string | null;
  validation_errors: string[];
  metadata: Record<string, unknown>;
};

export type SoulProjectionCard = {
  projection_id: string;
  title: string;
  soul_id: string;
  soul_name: string;
  projection_kind?: string;
  owner_system?: string;
  source_task_graph_refs?: string[];
  projection_nodes?: Array<Record<string, unknown>>;
  identity_anchor?: string;
  role_type: string;
  task_mode: string;
  agent_profile_id: string;
  posture_tags?: string[];
  expression_density?: string;
  attention_focus?: string[];
  risk_notes?: string[];
  projection_prompt?: string;
  usage_summary: string;
  skill_views: Array<Record<string, unknown>>;
  tool_views: Array<Record<string, unknown>>;
  memory_policy_summary: string;
  output_contract_summary: string;
  runtime_preview?: Record<string, unknown>;
  runtime_only_payload?: boolean;
  static_projection_card?: boolean;
  created_at: number;
  updated_at: number;
  is_primary?: boolean;
  is_system_default?: boolean;
};

export type SoulProjectionCatalog = {
  selected_projection_id: string;
  cards: SoulProjectionCard[];
};

export type SoulProjectionCardCreatePayload = {
  projection_id?: string;
  soul_id: string;
  projection_kind?: string;
  owner_system?: string;
  source_task_graph_refs?: string[];
  projection_nodes?: Array<Record<string, unknown>>;
  identity_anchor?: string;
  role_type?: string;
  task_mode?: string;
  agent_profile_id?: string;
  projection_name?: string;
  posture_tags?: string[];
  expression_density?: string;
  attention_focus?: string[];
  risk_notes?: string[];
  projection_prompt?: string;
  skill_views?: Array<{
    skill_id: string;
    title: string;
    capability_summary: string;
    use_when?: string;
    input_boundary?: string;
    output_boundary?: string;
    forbidden_uses?: string;
    current_task_reason?: string;
  }>;
  tool_views?: Array<{
    tool_id: string;
    title: string;
    capability_summary: string;
    input_schema_summary?: string;
    output_schema_summary?: string;
    risk_summary?: string;
    authorized?: boolean;
    authorization_owner?: string;
  }>;
  usage_summary?: string;
  memory_policy_summary?: string;
  output_contract_summary?: string;
  select_after_create?: boolean;
};

export type SoulResourceWorld = {
  world_id: string;
  title: string;
  summary: string;
  content: string;
  source_ref: string;
  version?: string;
  metadata?: Record<string, unknown>;
  chars?: number;
};

export type SoulResourceStory = {
  story_id: string;
  soul_id: string;
  title: string;
  summary: string;
  content: string;
  world_id: string;
  source_ref: string;
  version?: string;
  metadata?: Record<string, unknown>;
  chars?: number;
};

export type SoulResourceCard = {
  soul_id: string;
  name: string;
  display_name: string;
  story_id: string;
  world_id: string;
  manifestation_id: string;
  default_projection_id: string;
  default_work_prompt_id: string;
  description: string;
  source: "builtin" | "user" | string;
  enabled: boolean;
  tags: string[];
  metadata?: Record<string, unknown>;
};

export type SoulResourceManifestation = {
  manifestation_id: string;
  soul_id: string;
  display_name: string;
  avatar_ref: string;
  portrait_ref: string;
  model_ref: string;
  state: string;
  metadata?: Record<string, unknown>;
};

export type SoulResourceCatalog = {
  active_soul_id: string;
  worlds: SoulResourceWorld[];
  stories: SoulResourceStory[];
  cards: SoulResourceCard[];
  work_prompts: Array<Record<string, unknown>>;
  system_contracts?: Array<Record<string, unknown>>;
  common_contracts: Array<Record<string, unknown>>;
  manifestations: SoulResourceManifestation[];
  modes: Array<Record<string, unknown>>;
  authority: string;
};

export type SoulWorkLogEvent = {
  event_id: string;
  soul_id: string;
  task_run_id: string;
  session_id: string;
  task_id: string;
  projection_id: string;
  work_prompt_id: string;
  agent_id: string;
  agent_run_id: string;
  status: string;
  title: string;
  summary: string;
  artifact_count: number;
  artifact_refs: string[];
  source_refs: string[];
  last_activity_at: number;
};

export type SoulWorkLogView = {
  soul_id: string;
  limit: number;
  events: SoulWorkLogEvent[];
  authority?: string;
};

export type SoulSystemCatalog = {
  active_soul_key: string;
  active_soul_id?: string;
  active_soul_name: string;
  injection_chain: Array<{
    order: number;
    label: string;
    path: string;
  }>;
  static_files: SoulSystemFile[];
  seeds: SoulSystemSeed[];
  soul_profiles?: SoulProfile[];
  resource_catalog?: SoulResourceCatalog;
  management?: {
    planes: string[];
    authorization_owner: string;
    prompt_manifest_enabled: boolean;
    custom_soul_dir: string;
  };
};

export type ExternalMCPServerConfig = {
  server_id: string;
  title: string;
  description: string;
  transport: "stdio" | "streamable_http" | string;
  enabled: boolean;
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd: string;
  url: string;
  scope: string;
  tags: string[];
  allowed_operations: string[];
  requires_approval_operations: string[];
  denied_operations: string[];
  metadata: Record<string, unknown>;
};

export type MCPManagementTool = {
  provider_id: string;
  provider_kind: "local" | "external" | string;
  server_id: string;
  tool_name: string;
  title: string;
  description: string;
  operation_id: string;
  model_visibility: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  annotations: Record<string, unknown>;
  tags: string[];
  diagnostics: Record<string, unknown>;
  transport?: string;
  status?: string;
};

export type MCPManagementServer = {
  provider_id: string;
  server_id: string;
  title: string;
  description: string;
  provider_kind: "local" | "external" | string;
  transport: string;
  enabled: boolean;
  status: string;
  status_reason: string;
  operation_ids: string[];
  tools: MCPManagementTool[];
  diagnostics: Record<string, unknown>;
};

export type MCPManagementCatalog = {
  authority: string;
  providers: Array<{
    provider_id: string;
    provider_kind: string;
  }>;
  servers: MCPManagementServer[];
  tools: MCPManagementTool[];
  summary: {
    provider_count: number;
    server_count: number;
    local_server_count: number;
    external_server_count: number;
    tool_count: number;
    unsupported_count: number;
    failed_count: number;
  };
};

export type CustomSoulPayload = {
  soul_id: string;
  name: string;
  description?: string;
  soul_markdown?: string;
  preferred_role_types?: string[];
  preferred_task_modes?: string[];
  enabled?: boolean;
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
};

export type StreamHandlers = {
  onEvent: (event: string, data: Record<string, unknown>) => void;
};

export type StreamResult = {
  terminalEvent: "done" | "error" | "stopped";
  streamRunId: string;
  taskRunId: string;
  lastEventOffset: number;
};

export type ChatRun = {
  stream_run_id: string;
  session_id: string;
  task_run_id: string;
  root_request_ref: string;
  status: string;
  latest_event_offset: number;
  is_reconnectable?: boolean;
  terminal_event?: string;
  stream_url: string;
};

export type ChatStreamCursor = {
  streamRunId: string;
  taskRunId: string;
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

const TERMINAL_STREAM_EVENTS = new Set(["done", "error", "stopped"]);
const MAX_STREAM_BUFFER_CHARS = 1_000_000;
const MAX_CHAT_STREAM_RECONNECT_ATTEMPTS = 5;

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
    const taskRunId = String(parsed.taskRunId || "").trim();
    const lastEventOffset = Number(parsed.lastEventOffset ?? -1);
    const lastEventId = String(parsed.lastEventId || "").trim();
    if (!streamRunId || !taskRunId || !Number.isFinite(lastEventOffset)) {
      return null;
    }
    return { streamRunId, taskRunId, lastEventOffset, lastEventId };
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

export async function listSessions() {
  return request<SessionSummary[]>("/sessions");
}

export async function createSession(title = "New Session") {
  return request<SessionSummary>("/sessions", {
    method: "POST",
    body: JSON.stringify({ title })
  });
}

export async function renameSession(sessionId: string, title: string) {
  return request<SessionSummary>(`/sessions/${sessionId}`, {
    method: "PUT",
    body: JSON.stringify({ title })
  });
}

export async function deleteSession(sessionId: string) {
  return request<{ ok: boolean }>(`/sessions/${sessionId}`, {
    method: "DELETE"
  });
}

export async function getSessionHistory(sessionId: string) {
  return request<SessionHistory>(`/sessions/${sessionId}/history`);
}

export async function getSessionTimeline(sessionId: string) {
  return request<SessionTimeline>(`/sessions/${sessionId}/timeline`);
}

export async function truncateSessionMessages(sessionId: string, messageIndex: number) {
  return request<SessionTruncateResponse>(`/sessions/${sessionId}/messages/truncate`, {
    method: "POST",
    body: JSON.stringify({ message_index: messageIndex })
  });
}

export async function getSessionTokens(sessionId: string) {
  return request<{
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
  }>(`/tokens/session/${sessionId}`);
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
  return request<{ path: string; content: string }>(
    `/files?path=${encodeURIComponent(path)}`
  );
}

export async function saveFile(path: string, content: string) {
  return request<{ ok: boolean; path: string }>("/files", {
    method: "POST",
    body: JSON.stringify({ path, content })
  });
}

export async function getRagMode() {
  return request<{ enabled: boolean }>("/config/rag-mode");
}

export async function setRagMode(enabled: boolean) {
  return request<{ enabled: boolean }>("/config/rag-mode", {
    method: "PUT",
    body: JSON.stringify({ enabled })
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

export async function getSoulImageAssetConfig() {
  return request<SoulImageAssetConfig>("/soul/image-assets/config");
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

export async function getMemoryOverview(sessionId?: string, query = "") {
  const params = new URLSearchParams();
  if (sessionId) {
    params.set("session_id", sessionId);
  }
  if (query.trim()) {
    params.set("query", query.trim());
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<MemoryOverview>(`/memory/overview${suffix}`);
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

export async function getSessionMemoryFiles(sessionId: string) {
  return request<MemorySessionFilesResponse>(`/memory/session/${encodeURIComponent(sessionId)}/files`);
}

export async function recallMemoryPreview(payload: { query: string; session_id?: string; limit?: number }) {
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
}) {
  return request<MemoryGovernanceResponse>("/memory/durable", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function disableDurableMemory(filename: string, reason = "") {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/disable`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export async function activateDurableMemory(filename: string, reason = "") {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/activate`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export async function archiveDurableMemory(filename: string, reason = "") {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}/archive`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export async function deleteDurableMemory(filename: string, reason = "") {
  return request<MemoryGovernanceResponse>(`/memory/durable/${encodeURIComponent(filename)}`, {
    method: "DELETE",
    body: JSON.stringify({ reason })
  });
}

export async function getDurableMemoryNote(filename: string) {
  return request<DurableMemoryNoteDetail>(`/memory/durable/${encodeURIComponent(filename)}`);
}

export async function mergeDurableMemories(payload: {
  filenames: string[];
  title: string;
  canonical_statement: string;
  summary?: string;
  reason?: string;
}) {
  return request<MemoryGovernanceResponse>("/memory/durable/merge", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function runOrchestrationDryRun(payload: {
  session_id: string;
  message: string;
  ephemeral_system_messages?: string[];
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

export async function getOrchestrationAgents() {
  return request<OrchestrationAgentRuntimeCatalog>("/orchestration/agents");
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

export async function getGlobalRuntimeMonitor(limit = 30) {
  return request<GlobalRuntimeMonitor>(
    `/orchestration/runtime-monitor/live?limit=${encodeURIComponent(String(limit))}`
  );
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

export async function getOrchestrationHarnessTaskRunLiveMonitor(taskRunId: string) {
  return request<HarnessTaskRunLiveMonitor>(
    `/orchestration/runtime-monitor/task-runs/${encodeURIComponent(taskRunId)}`
  );
}

export async function pauseOrchestrationHarnessTaskRun(taskRunId: string, reason = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/pause`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    }
  );
}

export async function resumeOrchestrationHarnessTaskRun(taskRunId: string, maxSteps = 12) {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify({ max_steps: maxSteps }),
    }
  );
}

export async function stopOrchestrationHarnessTaskRun(taskRunId: string, reason = "") {
  return request<Record<string, unknown>>(
    `/orchestration/harness/task-runs/${encodeURIComponent(taskRunId)}/stop`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
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
    session_id?: string;
    task_id?: string;
    initial_inputs?: Record<string, unknown>;
    include_trace?: boolean;
    dispatch_ready?: boolean;
    run_mode?: "dispatch_only" | "auto_run" | string;
    runner_budget?: Record<string, unknown>;
  } = {}
) {
  return request<TaskGraphRunStartResult>(
    `/orchestration/harness/task-graphs/${encodeURIComponent(graphId)}/start`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function runGraphRunUntilIdle(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    max_node_executions?: number;
    max_loop_iterations?: number;
    max_node_steps?: number;
    max_dispatches?: number;
    max_runtime_seconds?: number;
    max_dispatch_requests?: number | null;
  }
) {
  return request<GraphRunUntilIdleResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/run-until-idle`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getGraphRunMonitor(graphRunId: string, graphHarnessConfigId = "", eventLimit = 80) {
  const params = new URLSearchParams();
  if (graphHarnessConfigId) {
    params.set("graph_harness_config_id", graphHarnessConfigId);
  }
  params.set("event_limit", String(Math.max(1, Math.min(Number(eventLimit || 80), 240))));
  return request<GraphRunMonitorView>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/monitor?${params.toString()}`
  );
}

export async function dispatchGraphRunReadyNodes(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
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

export async function acceptGraphNodeResult(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    result: Record<string, unknown>;
  }
) {
  return request<GraphNodeResultAcceptResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/node-results`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function executeGraphWorkOrder(
  graphRunId: string,
  payload: {
    graph_harness_config_id: string;
    work_order: Record<string, unknown>;
    max_steps?: number;
    accept_result?: boolean;
  }
) {
  return request<GraphWorkOrderExecuteResult>(
    `/orchestration/harness/graph-runs/${encodeURIComponent(graphRunId)}/work-orders/execute`,
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

export async function getSoulSystemCatalog() {
  return request<SoulSystemCatalog>("/soul/catalog");
}

export async function switchSoulSystemSeed(key: string) {
  return request<SoulSystemCatalog>("/soul/switch", {
    method: "POST",
    body: JSON.stringify({ key, source: "frontend" })
  });
}

export async function saveSoulSystemFile(path: string, content: string, reason = "前端编辑") {
  return request<SoulSystemCatalog>("/soul/files", {
    method: "PUT",
    body: JSON.stringify({ path, content, reason })
  });
}

export async function saveSoulCommonContract(promptId: string, payload: { title: string; content: string; version?: string; cache_scope?: string }) {
  return request<SoulSystemCatalog>(`/soul/common-contracts/${encodeURIComponent(promptId)}`, {
    method: "PUT",
    body: JSON.stringify({
      prompt_id: promptId,
      title: payload.title,
      content: payload.content,
      version: payload.version ?? "v1",
      cache_scope: payload.cache_scope ?? "static"
    })
  });
}

export async function createCustomSoul(payload: CustomSoulPayload) {
  return request<SoulSystemCatalog>("/soul/custom", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateCustomSoul(soulId: string, payload: CustomSoulPayload) {
  return request<SoulSystemCatalog>(`/soul/custom/${encodeURIComponent(soulId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function enableCustomSoul(soulId: string) {
  return request<SoulSystemCatalog>(`/soul/custom/${encodeURIComponent(soulId)}/enable`, {
    method: "POST"
  });
}

export async function disableCustomSoul(soulId: string) {
  return request<SoulSystemCatalog>(`/soul/custom/${encodeURIComponent(soulId)}/disable`, {
    method: "POST"
  });
}

export async function deleteCustomSoul(soulId: string) {
  return request<SoulSystemCatalog>(`/soul/custom/${encodeURIComponent(soulId)}`, {
    method: "DELETE"
  });
}

export async function getSoulProjectionCards() {
  return request<SoulProjectionCatalog>("/soul/projections");
}

export async function getSoulWorkLog(soulId: string, limit = 6) {
  return request<SoulWorkLogView>(`/soul/${encodeURIComponent(soulId)}/activity?limit=${limit}`);
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
} = {}) {
  const params = new URLSearchParams({
    max_depth: String(options.maxDepth || 10),
    max_entries: String(options.maxEntries || 10000),
  });
  return request<CodeEnvironmentWorkspaceTree>(`/code-environment/workspace-tree?${params.toString()}`);
}

export async function getCodeEnvironmentGitStatus() {
  return request<CodeEnvironmentGitStatus>("/code-environment/git-status");
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

export async function createSoulProjectionCard(payload: SoulProjectionCardCreatePayload) {
  return request<SoulProjectionCatalog>("/soul/projections", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function selectSoulProjectionCard(projectionId: string) {
  return request<SoulProjectionCatalog>(`/soul/projections/${encodeURIComponent(projectionId)}/select`, {
    method: "POST"
  });
}

export async function deleteSoulProjectionCard(projectionId: string) {
  return request<SoulProjectionCatalog>(`/soul/projections/${encodeURIComponent(projectionId)}`, {
    method: "DELETE"
  });
}

export async function getProjectionTemplates() {
  return request<ProjectionTemplateCatalog>("/soul/projection-templates");
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

export async function getTaskGraphTemplates() {
  return request<TaskGraphTemplateCatalog>("/tasks/task-graph-templates");
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

export async function uploadSoulPortrait(key: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return request<SoulSystemCatalog>(`/soul/portraits/${encodeURIComponent(key)}`, {
    method: "POST",
    body: formData
  });
}

export async function createChatRun(payload: {
  message: string;
  session_id: string;
  ephemeral_system_messages?: string[];
  search_policy?: string[];
  runtime_mode?: string;
  task_selection?: Record<string, unknown>;
  model_selection?: Record<string, unknown>;
  image_generation?: Record<string, unknown>;
}) {
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

export async function resumeChatRun(streamRunId: string) {
  return request<ChatRun & { resume_mode: string }>(`/chat/runs/${encodeURIComponent(streamRunId)}/resume`, {
    method: "POST",
  });
}

export async function getLatestChatRunForSession(sessionId: string, activeOnly = true) {
  const params = new URLSearchParams({ active_only: activeOnly ? "true" : "false" });
  return request<ChatRun>(`/chat/sessions/${encodeURIComponent(sessionId)}/latest-run?${params.toString()}`);
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

async function consumeChatRunStream(
  run: ChatRun,
  sessionId: string,
  handlers: StreamHandlers,
  options: {
    signal?: AbortSignal;
    initialCursor?: ChatStreamCursor | null;
    replayFromStart?: boolean;
  } = {}
): Promise<StreamResult> {
  let lastEventOffset = options.replayFromStart
    ? -1
    : Number(options.initialCursor?.lastEventOffset ?? run.latest_event_offset ?? -1);
  let lastEventId = options.replayFromStart ? "" : String(options.initialCursor?.lastEventId || "");
  let terminalEvent: StreamResult["terminalEvent"] | "" = "";
  let reconnectAttempt = 0;

  saveChatStreamCursor(sessionId, {
    streamRunId: run.stream_run_id,
    taskRunId: run.task_run_id,
    lastEventOffset,
    lastEventId,
  });

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
      lastEventId = parsed.id || `${run.stream_run_id}:${run.task_run_id}:${lastEventOffset}`;
      saveChatStreamCursor(sessionId, {
        streamRunId: run.stream_run_id,
        taskRunId: run.task_run_id,
        lastEventOffset,
        lastEventId,
      });
    }
    if (reconnectAttempt > 0) {
      handlers.onEvent("stream_reconnected", {
        stream_run_id: run.stream_run_id,
        task_run_id: run.task_run_id,
        event_offset: lastEventOffset,
        attempt: reconnectAttempt,
        max_attempts: MAX_CHAT_STREAM_RECONNECT_ATTEMPTS,
      });
      reconnectAttempt = 0;
    }
    handlers.onEvent(parsed.event, parsed.data);
    return parsed.event;
  };

  while (!terminalEvent) {
    if (options.signal?.aborted) {
      clearChatStreamCursor(sessionId);
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

      if (!response.ok || !response.body) {
        throw new Error(`Chat stream request failed: ${response.status}`);
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
        clearChatStreamCursor(sessionId);
        throw error;
      }
      reconnectReason = error instanceof Error && error.message.trim()
        ? error.message
        : "stream_transport_error";
    } finally {
      if (reader && !readerClosed && !readerCancelled) {
        await reader.cancel().catch(() => undefined);
      }
    }

    if (!terminalEvent) {
      reconnectAttempt += 1;
      handlers.onEvent("stream_reconnecting", {
        stream_run_id: run.stream_run_id,
        task_run_id: run.task_run_id,
        event_offset: lastEventOffset,
        last_event_id: lastEventId,
        attempt: reconnectAttempt,
        max_attempts: MAX_CHAT_STREAM_RECONNECT_ATTEMPTS,
        reason: reconnectReason,
      });
      if (reconnectAttempt >= MAX_CHAT_STREAM_RECONNECT_ATTEMPTS) {
        handlers.onEvent("stream_reconnect_failed", {
          stream_run_id: run.stream_run_id,
          task_run_id: run.task_run_id,
          event_offset: lastEventOffset,
          attempt: reconnectAttempt,
          max_attempts: MAX_CHAT_STREAM_RECONNECT_ATTEMPTS,
          reason: reconnectReason,
        });
        throw new Error(`Chat stream reconnect attempts exhausted after ${reconnectAttempt} attempts.`);
      }
      await delay(Math.min(15000, 500 * 2 ** Math.max(0, reconnectAttempt - 1)), options.signal);
    }
  }

  clearChatStreamCursor(sessionId);

  return {
    terminalEvent,
    streamRunId: run.stream_run_id,
    taskRunId: run.task_run_id,
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
  } = {}
) {
  const run = await resumeChatRun(streamRunId);
  return consumeChatRunStream(run, sessionId, handlers, options);
}

export async function streamChat(
  payload: {
    message: string;
    session_id: string;
    ephemeral_system_messages?: string[];
    search_policy?: string[];
    runtime_mode?: string;
    task_selection?: Record<string, unknown>;
    model_selection?: Record<string, unknown>;
    image_generation?: Record<string, unknown>;
  },
  handlers: StreamHandlers,
  options: {
    signal?: AbortSignal;
  } = {}
): Promise<StreamResult> {
  const run = await createChatRun(payload);
  return consumeChatRunStream(run, payload.session_id, handlers, options);
}
