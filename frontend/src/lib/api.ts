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
  }>;
};

export type ExperimentProfile = {
  id: string;
  title: string;
  description: string;
  command_preview: string;
  risk: string;
  estimated_duration: string;
  harness_profile?: string;
  extra_args?: string[];
  requires_confirmation: boolean;
};

export type ExperimentRun = {
  run_id: string;
  profile: string;
  status: string;
  command_preview: string;
  output_dir: string;
  log_path: string;
  log_tail?: string;
  started_at: number;
  ended_at: number;
  duration_ms: number;
  returncode: number | null;
  pid: number | null;
  summary: {
    total: number;
    passed: number;
    failed: number;
    first_failure: string;
  };
};

export type ExperimentArtifacts = {
  run_result: Record<string, unknown>;
  issues: Array<Record<string, unknown>>;
  report: string;
  trace_tail: string;
  log_tail?: string;
  summary: ExperimentRun["summary"];
  runtime_loop?: Record<string, unknown>;
};

export type ExperimentTurn = {
  turn_id: string;
  index: number;
  scenario: string;
  session_alias: string;
  status: string;
  summary: string;
  problem_node_id?: string;
  problem_node_label?: string;
  artifact_path: string;
  issue_count: number;
  has_trace: boolean;
  has_prompt_manifest: boolean;
  has_memory_trace: boolean;
  runtime_loop?: Record<string, unknown>;
  assertions?: Array<Record<string, unknown>>;
};

export type TestProfile = ExperimentProfile & {
  monitor_owner?: string;
};

export type TestRun = ExperimentRun;

export type TestArtifacts = ExperimentArtifacts;

export type TestTurn = ExperimentTurn;

export type TestCaseDefinition = {
  case_id: string;
  title: string;
  layer: "chain" | "functional" | "system" | "scenario" | string;
  path: string;
  owner_system: string;
  runner: "pytest" | "python" | "harness" | string;
  status: "active" | "legacy" | "quarantined" | "candidate" | string;
  profiles: string[];
  description: string;
  assertions: string[];
  tags: string[];
  replaces: string[];
  reason: string;
};

export type TestCaseRegistry = {
  profiles: Record<string, {
    layers: string[];
    case_count: number;
  }>;
  layers: string[];
  active_cases: TestCaseDefinition[];
  legacy_cases: TestCaseDefinition[];
  candidate_cases: TestCaseDefinition[];
  case_count: number;
  authority: string;
};

export type TestAgentFinding = {
  severity: string;
  code: string;
  message: string;
  path: string;
  case_id: string;
  recommendation: string;
};

export type TestAgentReport = {
  authority: string;
  summary: {
    active_case_count?: number;
    legacy_case_count?: number;
    candidate_case_count?: number;
    registered_file_count?: number;
    discovered_test_file_count?: number;
    unregistered_file_count?: number;
    finding_count?: number;
  };
  findings: TestAgentFinding[];
  profile_targets: Record<string, string[]>;
  registered_paths: string[];
  unregistered_paths: string[];
  legacy_paths: string[];
};

export type TestHarnessIssue = {
  issue_id: string;
  title: string;
  origin: string;
  owner_system: string;
  severity: string;
  status: string;
  observed: string;
  expected: string;
  reproduce: string;
  related_run_id: string;
  related_turn_id: string;
  related_task_id: string;
  related_session_id: string;
  related_skill: string;
  problem_node_id: string;
  problem_node_label: string;
  tags: string[];
  created_at: number;
  updated_at: number;
};

export type TestCaseDraft = {
  draft_id: string;
  title: string;
  layer: string;
  owner_system: string;
  source_issue_id: string;
  source_run_id: string;
  source_turn_id: string;
  trigger: string;
  expected: string;
  assertions: string[];
  profile: string;
  status: string;
  created_at: number;
  updated_at: number;
};

export type TestCaseTemplate = {
  template_id: string;
  title: string;
  layer: string;
  owner_system: string;
  runner: string;
  profiles: string[];
  assertions: string[];
  tags: string[];
  description: string;
  pass_criteria: string[];
};

export type ScenarioTurnDefinition = {
  turn_id: string;
  user: string;
  expected: string;
  assistant_hint?: string;
  speaker?: string;
  session?: string;
  checks?: string[];
};

export type LongScenarioTurn = {
  turn_id: string;
  index: number;
  session: string;
  speaker: string;
  content: string;
  action: string;
  params: Record<string, unknown>;
  checks: string[];
};

export type LongScenarioDefinition = {
  scenario_id: string;
  title: string;
  category: string;
  execution_mode: string;
  goal: string;
  coverage: string[];
  assertions: string[];
  failure_modes: string[];
  expected_artifacts: string[];
  related_regressions: string[];
  scenario_sets: string[];
  profile_refs: string[];
  turns: LongScenarioTurn[];
  stress_profile?: Record<string, unknown> | null;
  runner_source: string;
};

export type LongScenarioCatalog = {
  authority: string;
  scenario_sets: Record<string, string[]>;
  scenarios: LongScenarioDefinition[];
};

export type TestHarnessRecords = {
  issues: TestHarnessIssue[];
  case_drafts: TestCaseDraft[];
  managed_cases: HarnessMapCase[];
  summary: {
    issue_count: number;
    open_issue_count: number;
    case_draft_count: number;
    managed_case_count?: number;
  };
  authority: string;
};

export type HarnessMapFeature = {
  feature_id: string;
  title: string;
  owner_system: string;
  boundary: string;
  case_count: number;
  active_case_count: number;
  candidate_case_count: number;
  legacy_case_count: number;
  open_issue_count: number;
  governance_finding_count: number;
  case_ids: string[];
  case_paths: string[];
  issue_refs: Array<Record<string, unknown>>;
  risk_status: string;
};

export type HarnessMapCase = TestCaseDefinition & {
  feature_id: string;
  feature_title: string;
  feature_boundary: string;
  behavior_under_test: string;
  problem_statement: string;
  pass_criteria: string[];
  scenario_turns?: ScenarioTurnDefinition[];
  issue_refs: Array<Record<string, unknown>>;
  case_draft_refs: Array<Record<string, unknown>>;
  governance_findings: Array<Record<string, unknown>>;
  traceability: Record<string, unknown>;
};

export type HarnessMap = {
  authority: string;
  summary: Record<string, number>;
  features: HarnessMapFeature[];
  cases: HarnessMapCase[];
  issues: TestHarnessIssue[];
  case_drafts: TestCaseDraft[];
  governance_findings: Array<Record<string, unknown>>;
  managed_cases: HarnessMapCase[];
  profile_matrix: Array<{
    profile: string;
    case_count: number;
    case_ids: string[];
  }>;
  link_contract: Record<string, string>;
};

export type AgentTaskConnectionProfile = {
  profile_id: string;
  agent_id: string;
  agent_profile_id: string;
  owner_system: string;
  profile_type: string;
  lifecycle_state: string;
  task_family_refs: string[];
  available_task_modes: string[];
  flow_refs: string[];
  binding_refs: string[];
  workflow_refs: string[];
  topology_refs: string[];
  default_flow_ref: string;
  default_workflow_ref: string;
  default_runtime_lane_hint: string;
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
  coordination_task_id: string;
  topology_template_id: string;
  display_numbers: {
    task: string;
    flow: string;
    workflow: string;
    coordination: string;
    topology: string;
  };
};

export type TaskSystemFlowUpsertPayload = {
  flow_id: string;
  task_family: string;
  task_mode: string;
  title: string;
  input_contract_id?: string;
  output_contract_id?: string;
  default_agent_id: string;
  default_workflow_id?: string;
  default_projection_id?: string;
  default_runtime_lane?: string;
  default_memory_scope?: string;
  enabled?: boolean;
  metadata?: Record<string, unknown>;
};

export type ConversationEntryPolicy = {
  profile_id: string;
  entry_policy_id?: string;
  title: string;
  default_workflow_id: string;
  default_projection_id: string;
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
  task_family: string;
  task_mode: string;
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

export type TaskDomainRecord = {
  domain_id: string;
  task_family: string;
  title: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  metadata?: Record<string, unknown>;
};

export type TaskProjectionBinding = {
  binding_id?: string;
  task_id: string;
  projection_selection_mode: string;
  allowed_projection_ids: string[];
  default_projection_id: string;
  projection_required: boolean;
  notes: string;
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
  allowed_agent_categories: string[];
  allow_worker_agent_spawn: boolean;
  worker_agent_blueprint_id: string;
  worker_agent_naming_rule: string;
  notes: string;
  authority?: string;
  metadata?: Record<string, unknown>;
};

export type TaskMemoryRequestProfile = {
  profile_id?: string;
  task_id: string;
  requested_memory_layers: string[];
  requested_topics: string[];
  memory_priority: string;
  writeback_policy: string;
  allow_long_term_memory: boolean;
  working_memory_policy_profile_id?: string;
  working_memory_policy?: Record<string, unknown>;
  allow_working_memory?: boolean;
  allow_dynamic_working_memory_read?: boolean;
  working_memory_default_scope?: string;
  working_memory_default_visibility?: string;
  memory_scope_hint: string;
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
  allowed_runtime_lanes: string[];
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

export type ContractManifest = {
  authority: string;
  manifest_id: string;
  manifest_kind: string;
  task_ref: string;
  workflow_id: string;
  coordination_task_id: string;
  graph_id: string;
  global_contracts: Array<Record<string, unknown>>;
  workflow_contracts: Array<Record<string, unknown>>;
  node_contracts: Array<Record<string, unknown>>;
  edge_handoff_contracts: Array<Record<string, unknown>>;
  runtime_contracts: Array<Record<string, unknown>>;
  acceptance_contracts: Array<Record<string, unknown>>;
  issues: ContractCompileIssue[];
  metadata: Record<string, unknown>;
  valid: boolean;
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

export type RuntimeAssembly = {
  authority: string;
  assembly_id: string;
  manifest_ref: string;
  task_ref?: string;
  workflow_id?: string;
  coordination_task_ref?: string;
  graph_id?: string;
  node_id?: string;
  agent_id: string;
  agent_profile_id: string;
  runtime_lane: string;
  context_sections: RuntimeContextSection[];
  output_contracts: Array<Record<string, unknown>>;
  acceptance_contracts: Array<Record<string, unknown>>;
  handoff_packets?: Array<Record<string, unknown>>;
  failure_contract: Record<string, unknown>;
  loop_policy: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
};

export type CoordinationTask = {
  coordination_task_id: string;
  title: string;
  coordination_mode: string;
  coordinator_agent_id: string;
  task_family?: string;
  domain_id?: string;
  agent_group_id?: string;
  participant_agent_ids: string[];
  topology_template_id: string;
  shared_context_policy: string;
  memory_sharing_policy: string;
  handoff_policy: string;
  conflict_resolution_policy: string;
  output_merge_policy: string;
  stop_conditions: string[];
  subtask_refs: string[];
  graph_nodes: Array<Record<string, unknown>>;
  graph_edges: Array<Record<string, unknown>>;
  communication_modes: string[];
  enabled: boolean;
  metadata?: Record<string, unknown>;
};

export type CoordinationGraphSpec = {
  graph_id: string;
  coordination_task_id: string;
  domain_id: string;
  task_family: string;
  coordinator_agent_id: string;
  agent_group_id?: string;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  subtask_refs: string[];
  communication_modes: string[];
  start_node_ids: string[];
  terminal_node_ids: string[];
  issues: Array<Record<string, unknown>>;
  valid: boolean;
  diagnostics?: Record<string, unknown>;
};

export type TaskGraphNodeRecord = {
  node_id: string;
  node_type: string;
  title: string;
  task_id?: string;
  agent_id?: string;
  agent_selection_policy?: string;
  agent_group_id?: string;
  work_posture?: string;
  node_contract_id?: string;
  input_contract_id?: string;
  output_contract_id?: string;
  runtime_lane?: string;
  context_visibility_policy?: Record<string, unknown>;
  projection_overlay_id?: string;
  failure_policy?: Record<string, unknown>;
  human_gate_policy?: Record<string, unknown>;
  memory_read_policy?: Record<string, unknown>;
  memory_writeback_policy?: Record<string, unknown>;
  dynamic_memory_read_policy?: Record<string, unknown>;
  execution_mode?: "sync" | "async" | "parallel" | "background" | "barrier" | "manual_gate" | string;
  dispatch_group?: string;
  wait_policy?: string;
  join_policy?: string;
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
  payload_contract_id?: string;
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
  task_family?: string;
  graph_kind: "single_agent" | "multi_agent" | "coordination";
  entry_node_id: string;
  output_node_id: string;
  nodes: TaskGraphNodeRecord[];
  edges: TaskGraphEdgeRecord[];
  graph_contract_id?: string;
  default_protocol_id?: string;
  runtime_policy?: Record<string, unknown>;
  context_policy?: Record<string, unknown>;
  publish_state: "draft" | "published" | "archived";
  enabled: boolean;
  metadata?: Record<string, unknown>;
  issues?: Array<Record<string, unknown>>;
  valid?: boolean;
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
export type SpecificTaskRecordUpsertPayload = SpecificTaskRecord;
export type TaskProjectionBindingUpsertPayload = TaskProjectionBinding;
export type TaskFlowContractBindingUpsertPayload = TaskFlowContractBinding;
export type TaskExecutionPolicyUpsertPayload = TaskExecutionPolicy;
export type TaskMemoryRequestProfileUpsertPayload = TaskMemoryRequestProfile;
export type ContractSpecUpsertPayload = ContractSpec;

export type CoordinationTaskUpsertPayload = CoordinationTask;
export type TaskGraphUpsertPayload = TaskGraphRecord;

export type TopologyTemplateUpsertPayload = TopologyTemplate;

export type TaskCommunicationProtocolUpsertPayload = TaskCommunicationProtocol;

export type TaskAgentConnectionOverview = {
  authority: string;
  profiles: AgentTaskConnectionProfile[];
  summary: {
    profile_count: number;
    invalid_profile_count: number;
    task_family_count: number;
    topology_count: number;
  };
  diagnostics: Record<string, unknown>;
};

export type TaskSystemOverview = {
  authority: string;
  summary: Record<string, number>;
  task_management: {
    entry_policies: ConversationEntryPolicy[];
    task_domains: TaskDomainRecord[];
    specific_task_records: SpecificTaskRecord[];
    task_flow_definitions: TaskSystemFlowUpsertPayload[];
    workflow_resources: TaskWorkflowRecord[];
    projection_bindings: TaskProjectionBinding[];
    flow_contract_bindings: TaskFlowContractBinding[];
    execution_policies: TaskExecutionPolicy[];
    memory_request_profiles: TaskMemoryRequestProfile[];
    contract_catalog?: TaskContractDescriptor[];
    compatibility_views?: {
      specific_tasks?: Array<Record<string, unknown>>;
    };
  };
  contract_management?: {
    authority: string;
    contract_specs: ContractSpec[];
    contract_kind_options: string[];
    field_type_options: string[];
    source_hint_options: string[];
    visibility_options: string[];
    acceptance_rule_type_options: string[];
    validation_issues: ContractValidationIssue[];
    summary: Record<string, number>;
  };
  task_graph_management?: {
    task_graphs: TaskGraphRecord[];
  };
  coordination_management: {
    task_graphs?: TaskGraphRecord[];
    coordination_tasks: CoordinationTask[];
    coordination_graph_specs?: CoordinationGraphSpec[];
    topology_templates: TopologyTemplate[];
    communication_protocols: TaskCommunicationProtocol[];
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
  allowed_task_modes: string[];
  allowed_runtime_lanes: string[];
  allowed_operations: string[];
  blocked_operations: string[];
  allowed_memory_scopes: string[];
  allowed_context_sections: string[];
  use_shared_contract: boolean;
  output_contracts: string[];
  approval_policy: string;
  trace_policy: string;
  lifecycle_policy: string;
  metadata?: Record<string, unknown>;
};

export type OrchestrationAgentGroup = {
  group_id: string;
  title: string;
  group_kind: string;
  coordinator_agent_id: string;
  member_agent_ids: string[];
  description: string;
  default_topology_template_ids: string[];
  default_communication_protocol_ids: string[];
  allowed_coordination_task_ids: string[];
  lifecycle_state: string;
  metadata?: Record<string, unknown>;
};

export type OrchestrationOption = {
  id: string;
  value: string;
  label: string;
  description?: string;
  operation_type?: string;
};

export type OrchestrationAgentRuntimeCatalog = {
  authority: string;
  agents: Array<Record<string, unknown> & { runtime_profile?: Partial<OrchestrationAgentRuntimeProfile> }>;
  agent_groups?: OrchestrationAgentGroup[];
  profiles: OrchestrationAgentRuntimeProfile[];
  summary: Record<string, number>;
  options: {
    operations: Array<Record<string, unknown>>;
    task_modes: string[];
    runtime_lanes: string[];
    memory_scopes: string[];
    context_sections: string[];
    output_contracts: string[];
    approval_policies: string[];
    trace_policies: string[];
    operation_options?: OrchestrationOption[];
    task_mode_options?: OrchestrationOption[];
    runtime_lane_options?: OrchestrationOption[];
    memory_scope_options?: OrchestrationOption[];
    context_section_options?: OrchestrationOption[];
    output_contract_options?: OrchestrationOption[];
    approval_policy_options?: OrchestrationOption[];
    trace_policy_options?: OrchestrationOption[];
    worker_blueprints?: Array<Record<string, unknown>>;
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
  compatible_projection_ids: string[];
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

export type HealthSystemOverview = {
  authority: string;
  summary: Record<string, number>;
  issues: HealthIssue[];
  agent_runs: HealthAgentRun[];
  problem_nodes: HealthProblemNode[];
  commands?: HealthManagementCommand[];
  reports?: HealthReport[];
  health_test_runs?: HealthTestRun[];
  verification_runs?: VerificationRun[];
  gate_projection?: {
    authority: string;
    decisions: Array<Record<string, unknown>>;
    summary: Record<string, number>;
  };
};

export type HealthWorkbenchInboxItem = {
  item_id: string;
  item_type: string;
  title: string;
  subject_type: "health_issue" | "verification_run" | string;
  subject_id: string;
  subject_title: string;
  severity: string;
  reason: string;
  primary_action: string;
  secondary_actions: string[];
  evidence_state: "linked" | "missing" | string;
  created_at?: number;
  metadata?: Record<string, unknown>;
};

export type HealthWorkbenchOverview = {
  authority: string;
  summary: Record<string, number>;
  inbox_items: HealthWorkbenchInboxItem[];
  selected_context: HealthWorkbenchInboxItem | Record<string, never>;
  features: HarnessMapFeature[];
  verification_resources: HarnessMapCase[];
  recent_runs: VerificationRun[];
  evidence_gaps: Array<Record<string, unknown>>;
  efficiency: {
    authority: string;
    latency: Record<string, number>;
    tokens: Record<string, unknown>;
    signals: Array<Record<string, unknown>>;
  };
  context_budget?: ContextBudgetConfig;
  recommended_actions: Array<Record<string, unknown>>;
  source_refs: Record<string, string>;
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
  default_model: string;
  default_base_url: string;
};

export type ModelProviderConfig = {
  provider: string;
  model: string;
  base_url: string;
  api_key_configured: boolean;
  fallback_provider: string;
  fallback_model: string;
  fallback_base_url: string;
  fallback_api_key_configured: boolean;
  supported_providers: Record<string, ModelProviderOption>;
  authority: string;
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
  task_mode: string;
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
  task_mode: string;
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
  test_run_ref: string;
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
  test_run_ref: string;
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
  health_test_run?: HealthTestRun;
};

export type HealthTestRun = {
  health_test_run_id: string;
  command_ref: string;
  test_system_run_ref: string;
  profile: string;
  scenario_refs: string[];
  status: string;
  verdict: string;
  artifact_refs: string[];
  issue_refs: string[];
  report_refs: string[];
  started_at: number;
  finished_at: number;
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

export type SystemGraphOverlayItem = {
  id: string;
  status: "passed" | "failed" | "warning" | "unknown";
  label: string;
  events: string[];
  latency_ms: number | null;
  reason: string;
};

export type SystemGraphOverlay = {
  run_id: string;
  turn_id: string | null;
  mode: "inferred" | "observed";
  status: "passed" | "failed" | "warning" | "unknown";
  summary: string;
  nodes: SystemGraphOverlayItem[];
  edges: SystemGraphOverlayItem[];
  artifacts: Record<string, string>;
  prompt_manifest_id: string | null;
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
  tool_contract_mode: string;
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
  runtime_lane: string;
  model_visibility: string;
  input_modes: string[];
  output_modes: string[];
  tags: string[];
  mcp_profile: Record<string, unknown>;
  operation: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
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
  runtime_lane: string;
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
    model_visible_skills: number;
    tool_types: string[];
    tool_boundaries: Record<string, number>;
    tool_sources: Record<string, number>;
    tool_risks: Record<string, number>;
    operation_count?: number;
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

export type ExternalMCPTool = {
  name: string;
  title: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  annotations: Record<string, unknown>;
  meta: Record<string, unknown>;
};

export type ExternalMCPResource = {
  uri: string;
  name: string;
  title: string;
  description: string;
  mime_type: string;
  size: number | null;
  annotations: Record<string, unknown>;
  meta: Record<string, unknown>;
};

export type ExternalMCPPrompt = {
  name: string;
  title: string;
  description: string;
  arguments: Array<Record<string, unknown>>;
  meta: Record<string, unknown>;
};

export type ExternalMCPSnapshot = {
  server_id: string;
  title: string;
  transport: string;
  enabled: boolean;
  scope: string;
  status: string;
  status_reason: string;
  capabilities: Record<string, unknown>;
  tools: ExternalMCPTool[];
  resources: ExternalMCPResource[];
  prompts: ExternalMCPPrompt[];
  diagnostics: Record<string, unknown>;
};

export type ExternalMCPToolPoolEntry = {
  entry_id: string;
  entry_kind: string;
  display_name: string;
  route_family: string;
  candidate_visibility: string;
  model_visibility: string;
  runtime_exposure: string;
  requires_explicit_binding: boolean;
  discovery_priority: number;
  name: string;
  source: string;
  server_id: string;
  server_title: string;
  transport: string;
  tool_name: string;
  description: string;
  authorized: boolean;
  authorization: Record<string, unknown>;
  operation: Record<string, unknown>;
};

export type ExternalMCPCatalog = {
  authority: string;
  servers: ExternalMCPServerConfig[];
  snapshots: ExternalMCPSnapshot[];
  tool_pool: ExternalMCPToolPoolEntry[];
  summary: {
    server_count: number;
    enabled_server_count: number;
    connected_server_count: number;
    tool_count: number;
    resource_count: number;
    prompt_count: number;
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

export type WorkingMemoryItem = {
  work_memory_id: string;
  task_run_id: string;
  task_id: string;
  graph_id: string;
  owner_node_id: string;
  owner_node_role: string;
  node_run_id: string;
  run_attempt_id: string;
  stage_id: string;
  writer_agent_id: string;
  last_writer_agent_id: string;
  scope: string;
  kind: string;
  memory_semantics: string;
  title: string;
  payload: Record<string, unknown>;
  payload_preview: string;
  summary: string;
  status: string;
  visibility: string;
  read_policy: Record<string, unknown>;
  write_policy: Record<string, unknown>;
  version: number;
  parent_item_id: string;
  source_event_refs: string[];
  source_message_refs: string[];
  artifact_refs: string[];
  contract_refs: string[];
  reader_policy: Record<string, unknown>;
  tags: string[];
  temporal_refs: string[];
  conflict_refs: string[];
  adopted_from_handoff_id: string;
  idempotency_key: string;
  source_message_hash: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  promotion_state: string;
  metadata: Record<string, unknown>;
  authority: string;
};

export type WorkingMemoryReadLog = {
  read_log_id: string;
  task_run_id: string;
  graph_id: string;
  owner_node_id: string;
  node_run_id: string;
  run_attempt_id: string;
  reader_agent_id: string;
  request: Record<string, unknown>;
  selected_item_ids: string[];
  excluded_item_ids: string[];
  token_estimate: number;
  denied_reason: string;
  created_at: string;
  authority: string;
};

export type WorkingMemoryTemporalEdge = {
  edge_id: string;
  task_run_id: string;
  graph_id: string;
  source_item_id: string;
  target_item_id: string;
  relation: string;
  confidence: number;
  source_node_id: string;
  created_at: string;
  metadata: Record<string, unknown>;
  authority: string;
};

export type WorkingMemoryHandoffTransaction = {
  transaction_id: string;
  task_run_id: string;
  graph_id: string;
  edge_id: string;
  source_node_run_id: string;
  target_node_run_id: string;
  handoff_id: string;
  source_message_hash: string;
  idempotency_key: string;
  candidate_work_memory_ids: string[];
  adopted_work_memory_ids: string[];
  rejected_work_memory_ids: string[];
  ephemeral_context_refs: string[];
  transaction_status: string;
  created_at: string;
  committed_at: string;
  metadata: Record<string, unknown>;
  authority: string;
};

export type WorkingMemoryOverview = {
  query: string;
  filters: Record<string, unknown>;
  total: number;
  active_run_ids: string[];
  by_status: Record<string, number>;
  by_kind: Record<string, number>;
  by_owner_node: Record<string, number>;
  by_writer_agent: Record<string, number>;
  items: WorkingMemoryItem[];
  conflict_items: WorkingMemoryItem[];
  promotion_candidates: WorkingMemoryItem[];
  archived_items: WorkingMemoryItem[];
  read_logs: WorkingMemoryReadLog[];
  temporal_edges: WorkingMemoryTemporalEdge[];
  handoff_transactions: WorkingMemoryHandoffTransaction[];
};

export type WorkingMemoryItemDetail = {
  item: WorkingMemoryItem;
  read_logs: WorkingMemoryReadLog[];
  temporal_edges: WorkingMemoryTemporalEdge[];
  handoff_transactions: WorkingMemoryHandoffTransaction[];
};

export type WorkingMemoryFinalizationResult = {
  task_run_id: string;
  finalized_count: number;
  archived_count: number;
  discarded_count: number;
  promotion_candidate_count: number;
  artifact_candidate_count: number;
  unresolved_conflict_count: number;
  unchanged_count: number;
  archive_report_path: string;
  item_actions: Array<{
    work_memory_id: string;
    kind: string;
    memory_semantics: string;
    before_status: string;
    before_promotion_state: string;
    after_status?: string;
    after_promotion_state?: string;
    owner_node_id: string;
    node_run_id: string;
    action: string;
  }>;
  authority: string;
};

export type WorkingMemoryFinalizationResponse = {
  ok: boolean;
  result: WorkingMemoryFinalizationResult;
};

export type TaskDurableMemoryNamespace = {
  namespace_id: string;
  task_family: string;
  domain_id: string;
  task_id: string;
  graph_id: string;
  project_id: string;
  artifact_namespace: string;
  item_count: number;
  updated_at: string;
};

export type TaskDurableMemoryItem = {
  task_memory_id: string;
  namespace_id: string;
  task_family: string;
  domain_id: string;
  task_id: string;
  graph_id: string;
  project_id: string;
  artifact_namespace: string;
  source_work_memory_ids: string[];
  source_artifact_refs: string[];
  memory_type: string;
  memory_class: string;
  kind: string;
  memory_semantics: string;
  title: string;
  canonical_statement: string;
  summary: string;
  payload: Record<string, unknown>;
  payload_preview: string;
  retrieval_hints: string[];
  status: string;
  confidence: string;
  stability: string;
  eligible_for_task_injection: boolean;
  eligible_for_global_promotion: boolean;
  global_promotion_state: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
  authority: string;
};

export type TaskDurableMemoryOverview = {
  query: string;
  filters: Record<string, unknown>;
  total: number;
  namespace_count: number;
  by_status: Record<string, number>;
  by_namespace: Record<string, number>;
  by_kind: Record<string, number>;
  namespaces: TaskDurableMemoryNamespace[];
  items: TaskDurableMemoryItem[];
  global_promotion_candidates: TaskDurableMemoryItem[];
};

export type TaskDurableMemoryItemDetail = {
  item: TaskDurableMemoryItem;
};

export type WorkingMemoryPromoteTaskDurableResponse = {
  ok: boolean;
  action: string;
  work_memory_id: string;
  task_memory: TaskDurableMemoryItem;
  item: WorkingMemoryItem;
};

export type TaskDurableMemoryGovernanceResponse = {
  ok: boolean;
  action: string;
  task_memory: TaskDurableMemoryItem;
  filename?: string;
  header?: MemoryHeader | null;
};

export type WorkingMemoryGovernanceResponse = {
  ok: boolean;
  action: string;
  work_memory_id: string;
  item: WorkingMemoryItem;
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
    extraction_runtime: Record<string, unknown>;
  };
  session_memory: MemorySessionInspect | null;
  working_memory?: WorkingMemoryOverview;
  task_durable_memory?: TaskDurableMemoryOverview;
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

function getApiBase() {
  const explicitBase = process.env.NEXT_PUBLIC_API_BASE?.trim();
  if (explicitBase) {
    return explicitBase.replace(/\/$/, "");
  }

  if (typeof window === "undefined") {
    return "http://127.0.0.1:8002/api";
  }

  return "http://127.0.0.1:8002/api";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
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

export async function getWorkingMemoryOverview(payload?: {
  task_run_id?: string;
  graph_id?: string;
  owner_node_id?: string;
  node_run_id?: string;
  writer_agent_id?: string;
  status?: string;
  kind?: string;
  query?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(payload ?? {})) {
    if (value === undefined || value === null) {
      continue;
    }
    const text = String(value).trim();
    if (text) {
      params.set(key, text);
    }
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<WorkingMemoryOverview>(`/memory/working/overview${suffix}`);
}

export async function getWorkingMemoryItem(workMemoryId: string) {
  return request<WorkingMemoryItemDetail>(`/memory/working/items/${encodeURIComponent(workMemoryId)}`);
}

export async function finalizeWorkingMemoryTaskRun(
  taskRunId: string,
  payload?: {
    actor_id?: string;
    terminal_reason?: string;
    policy?: Record<string, unknown>;
  }
) {
  return request<WorkingMemoryFinalizationResponse>(
    `/memory/working/runs/${encodeURIComponent(taskRunId)}/finalize`,
    {
      method: "POST",
      body: JSON.stringify(payload ?? {})
    }
  );
}

export async function getTaskDurableMemoryOverview(payload?: {
  namespace_id?: string;
  task_family?: string;
  domain_id?: string;
  task_id?: string;
  graph_id?: string;
  project_id?: string;
  artifact_namespace?: string;
  kind?: string;
  memory_semantics?: string;
  status?: string;
  query?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(payload ?? {})) {
    if (value === undefined || value === null) {
      continue;
    }
    const text = String(value).trim();
    if (text) {
      params.set(key, text);
    }
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<TaskDurableMemoryOverview>(`/memory/task-durable/overview${suffix}`);
}

export async function getTaskDurableMemoryItem(taskMemoryId: string) {
  return request<TaskDurableMemoryItemDetail>(`/memory/task-durable/items/${encodeURIComponent(taskMemoryId)}`);
}

export async function listTaskDurableMemoryNamespaces() {
  return request<{ namespaces: TaskDurableMemoryNamespace[] }>("/memory/task-durable/namespaces");
}

export async function markTaskDurableGlobalCandidate(
  taskMemoryId: string,
  payload?: {
    actor_id?: string;
    reason?: string;
  }
) {
  return request<TaskDurableMemoryGovernanceResponse>(
    `/memory/task-durable/items/${encodeURIComponent(taskMemoryId)}/promote-global-candidate`,
    {
      method: "POST",
      body: JSON.stringify(payload ?? {})
    }
  );
}

export async function promoteTaskDurableToGlobal(
  taskMemoryId: string,
  payload?: {
    title?: string;
    canonical_statement?: string;
    summary?: string;
    global_kind?: string;
    memory_type?: string;
    memory_class?: string;
    confidence?: string;
    actor_id?: string;
    reason?: string;
  }
) {
  return request<TaskDurableMemoryGovernanceResponse>(
    `/memory/task-durable/items/${encodeURIComponent(taskMemoryId)}/promote-global`,
    {
      method: "POST",
      body: JSON.stringify(payload ?? {})
    }
  );
}

export async function promoteWorkingMemoryToTaskDurable(
  workMemoryId: string,
  payload?: {
    title?: string;
    canonical_statement?: string;
    summary?: string;
    namespace_id?: string;
    task_family?: string;
    domain_id?: string;
    task_id?: string;
    graph_id?: string;
    project_id?: string;
    artifact_namespace?: string;
    memory_type?: string;
    memory_class?: string;
    retrieval_hints?: string[];
    confidence?: string;
    actor_id?: string;
    reason?: string;
  }
) {
  return request<WorkingMemoryPromoteTaskDurableResponse>(
    `/memory/working/items/${encodeURIComponent(workMemoryId)}/promote-task-durable`,
    {
      method: "POST",
      body: JSON.stringify(payload ?? {})
    }
  );
}

export async function governWorkingMemoryItem(
  workMemoryId: string,
  action: "accept" | "discard" | "conflict",
  payload?: {
    actor_id?: string;
    reason?: string;
    metadata?: Record<string, unknown>;
  }
) {
  return request<WorkingMemoryGovernanceResponse>(
    `/memory/working/items/${encodeURIComponent(workMemoryId)}/${action}`,
    {
      method: "POST",
      body: JSON.stringify(payload ?? {})
    }
  );
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

export async function listExperimentProfiles() {
  return request<ExperimentProfile[]>("/health-system/maintenance/experiments/profiles");
}

export async function listExperimentRuns(limit = 20) {
  return request<ExperimentRun[]>(`/health-system/maintenance/experiments/runs?limit=${limit}`);
}

export async function startExperimentRun(profile: string) {
  return request<ExperimentRun>("/health-system/maintenance/experiments/runs", {
    method: "POST",
    body: JSON.stringify({ profile })
  });
}

export async function getExperimentRun(runId: string) {
  return request<ExperimentRun>(`/health-system/maintenance/experiments/runs/${encodeURIComponent(runId)}`);
}

export async function getExperimentArtifacts(runId: string) {
  return request<ExperimentArtifacts>(`/health-system/maintenance/experiments/runs/${encodeURIComponent(runId)}/artifacts`);
}

export async function listExperimentTurns(runId: string) {
  return request<ExperimentTurn[]>(`/health-system/maintenance/experiments/runs/${encodeURIComponent(runId)}/turns`);
}

export async function getExperimentGraphOverlay(runId: string) {
  return request<SystemGraphOverlay>(`/health-system/maintenance/experiments/runs/${encodeURIComponent(runId)}/graph-overlay`);
}

export async function getExperimentTurnGraphOverlay(runId: string, turnId: string) {
  return request<SystemGraphOverlay>(
    `/health-system/maintenance/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/graph-overlay`
  );
}

export async function getExperimentTurnPromptManifest(runId: string, turnId: string) {
  return request<PromptManifestResponse>(
    `/health-system/maintenance/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/prompt-manifest`
  );
}

export async function getExperimentTurnMemoryTrace(runId: string, turnId: string) {
  return request<ExperimentTurnMemoryTraceResponse>(
    `/health-system/maintenance/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/memory-trace`
  );
}

export async function getExperimentTurnOrchestration(runId: string, turnId: string, artifactPath = "") {
  const params = new URLSearchParams();
  if (artifactPath.trim()) {
    params.set("artifact_path", artifactPath.trim());
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<OrchestrationSnapshot>(
    `/health-system/maintenance/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/orchestration${suffix}`
  );
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

export async function updateCapabilitySystemTool(toolName: string, payload: { tool_type: string; note?: string }) {
  return request<CapabilitySystemCatalog>(`/capability-system/tools/${encodeURIComponent(toolName)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getMCPSystemCatalog() {
  return request<ExternalMCPCatalog>("/mcp-system/catalog");
}

export async function upsertMCPSystemServer(serverId: string, payload: ExternalMCPServerConfig) {
  return request<ExternalMCPCatalog>(`/mcp-system/servers/${encodeURIComponent(serverId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteMCPSystemServer(serverId: string) {
  return request<ExternalMCPCatalog>(`/mcp-system/servers/${encodeURIComponent(serverId)}`, {
    method: "DELETE"
  });
}

export async function inspectMCPSystemServer(serverId: string) {
  return request<ExternalMCPSnapshot>(`/mcp-system/servers/${encodeURIComponent(serverId)}/inspect`, {
    method: "POST"
  });
}

export async function callMCPSystemTool(serverId: string, toolName: string, argumentsPayload: Record<string, unknown>) {
  return request<Record<string, unknown>>(
    `/mcp-system/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}/call`,
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

export async function compileTaskSystemWorkflowContractManifest(workflowId: string, taskId: string) {
  const params = new URLSearchParams({ task_id: taskId });
  return request<ContractManifest>(
    `/tasks/contract-manifests/workflows/${encodeURIComponent(workflowId)}?${params.toString()}`
  );
}

export async function compileTaskSystemCoordinationContractManifest(coordinationTaskId: string) {
  return request<ContractManifest>(
    `/tasks/contract-manifests/coordination/${encodeURIComponent(coordinationTaskId)}`
  );
}

export async function buildTaskSystemWorkflowRuntimeAssembly(workflowId: string, taskId: string) {
  const params = new URLSearchParams({ task_id: taskId });
  return request<RuntimeAssembly>(
    `/tasks/runtime-assemblies/workflows/${encodeURIComponent(workflowId)}?${params.toString()}`
  );
}

export async function buildTaskSystemNodeRuntimeAssembly(coordinationTaskId: string, nodeId: string) {
  return request<RuntimeAssembly>(
    `/tasks/runtime-assemblies/coordination/${encodeURIComponent(coordinationTaskId)}/nodes/${encodeURIComponent(nodeId)}`
  );
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

export async function upsertTaskSystemSpecificRecord(taskId: string, payload: SpecificTaskRecordUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/specific-records/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function deleteTaskSystemSpecificRecord(taskId: string) {
  return request<TaskSystemOverview>(`/tasks/specific-records/${encodeURIComponent(taskId)}`, {
    method: "DELETE"
  });
}

export async function upsertTaskSystemProjectionBinding(taskId: string, payload: TaskProjectionBindingUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/projection-bindings/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
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

export async function upsertTaskSystemMemoryRequestProfile(taskId: string, payload: TaskMemoryRequestProfileUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/memory-request-profiles/${encodeURIComponent(taskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemCoordinationTask(
  coordinationTaskId: string,
  payload: CoordinationTaskUpsertPayload
) {
  return request<TaskSystemOverview>(`/tasks/coordination-tasks/${encodeURIComponent(coordinationTaskId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemTaskGraph(graphId: string, payload: TaskGraphUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/task-graphs/${encodeURIComponent(graphId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function upsertTaskSystemTopologyTemplate(templateId: string, payload: TopologyTemplateUpsertPayload) {
  return request<TaskSystemOverview>(`/tasks/topology-templates/${encodeURIComponent(templateId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function upsertTaskSystemCommunicationProtocol(
  protocolId: string,
  payload: TaskCommunicationProtocolUpsertPayload
) {
  return request<TaskSystemOverview>(`/tasks/communication-protocols/${encodeURIComponent(protocolId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getHealthSystemOverview() {
  return request<HealthSystemOverview>("/health-system/overview");
}

export async function getHealthWorkbenchOverview() {
  return request<HealthWorkbenchOverview>("/health-workbench/overview");
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
  task_mode?: string;
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

export async function previewHealthAgentRun(issueId: string, taskMode = "issue_triage") {
  return request<HealthAgentRunPreview>(
    `/health-system/issues/${encodeURIComponent(issueId)}/agent-runs/preview`,
    {
      method: "POST",
      body: JSON.stringify({ task_mode: taskMode })
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

export async function cancelExperimentRun(runId: string) {
  return request<ExperimentRun>(`/health-system/maintenance/experiments/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST"
  });
}

export async function listTestProfiles() {
  return request<TestProfile[]>("/health-system/maintenance/test-system/profiles");
}

export async function getTestCases(includeLegacy = true) {
  const params = new URLSearchParams();
  params.set("include_legacy", includeLegacy ? "true" : "false");
  return request<TestCaseRegistry>(`/health-system/maintenance/test-system/cases?${params.toString()}`);
}

export async function getTestAgentReport() {
  return request<TestAgentReport>("/health-system/maintenance/test-system/agent/report");
}

export async function getHarnessMap() {
  return request<HarnessMap>("/health-system/maintenance/test-system/harness-map");
}

export async function getTestCaseTemplates() {
  return request<{ authority: string; templates: TestCaseTemplate[] }>("/health-system/maintenance/test-system/case-templates");
}

export async function listLongScenarios() {
  return request<LongScenarioCatalog>("/health-system/maintenance/test-system/long-scenarios");
}

export async function createManagedTestCase(payload: {
  case_id?: string;
  title: string;
  layer?: string;
  path?: string;
  owner_system?: string;
  runner?: string;
  status?: string;
  profiles?: string[] | string;
  description?: string;
  problem_statement?: string;
  pass_criteria?: string[] | string;
  scenario_turns?: Array<{
    turn_id?: string;
    user?: string;
    expected?: string;
    assistant_hint?: string;
  }>;
  assertions?: string[] | string;
  tags?: string[] | string;
  source_template_id?: string;
}) {
  return request<HarnessMapCase>("/health-system/maintenance/test-system/managed-cases", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function deleteManagedTestCase(caseId: string) {
  return request<{ ok: boolean; case_id: string }>(`/health-system/maintenance/test-system/managed-cases/${encodeURIComponent(caseId)}`, {
    method: "DELETE"
  });
}

export async function listTestRuns(limit = 20) {
  return request<TestRun[]>(`/health-system/maintenance/test-system/runs?limit=${limit}`);
}

export async function startTestRun(profile: string, scenarioIds: string[] = []) {
  return request<TestRun>("/health-system/maintenance/test-system/runs", {
    method: "POST",
    body: JSON.stringify({ profile, scenario_ids: scenarioIds })
  });
}

export async function getTestRun(runId: string) {
  return request<TestRun>(`/health-system/maintenance/test-system/runs/${encodeURIComponent(runId)}`);
}

export async function cancelTestRun(runId: string) {
  return request<TestRun>(`/health-system/maintenance/test-system/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST"
  });
}

export async function getTestArtifacts(runId: string) {
  return request<TestArtifacts>(`/health-system/maintenance/test-system/runs/${encodeURIComponent(runId)}/artifacts`);
}

export async function listTestTurns(runId: string) {
  return request<TestTurn[]>(`/health-system/maintenance/test-system/runs/${encodeURIComponent(runId)}/turns`);
}

export async function getTestTurnRuntimeLoop(runId: string, turnId: string) {
  return request<Record<string, unknown>>(
    `/health-system/maintenance/test-system/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/runtime-loop`
  );
}

export async function streamChat(
  payload: {
    message: string;
    session_id: string;
    ephemeral_system_messages?: string[];
    search_policy?: string[];
    task_selection?: Record<string, unknown>;
  },
  handlers: StreamHandlers
) {
  const response = await fetch(`${getApiBase()}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      ...payload,
      stream: true
    })
  });

  if (!response.ok || !response.body) {
    throw new Error(`Chat request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushBlock = (block: string) => {
    const lines = block.split("\n");
    let event = "message";
    const dataLines: string[] = [];

    for (const line of lines) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }

    if (!dataLines.length) {
      return;
    }

    const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    handlers.onEvent(event, data);
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      flushBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      if (buffer.trim()) {
        flushBlock(buffer);
      }
      break;
    }
  }
}
