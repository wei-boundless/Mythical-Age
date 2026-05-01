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

export type TaskSystemOverview = {
  authority: string;
  summary: Record<string, number>;
  agents: Array<Record<string, unknown>>;
  flows: Array<Record<string, unknown>>;
  bindings: Array<Record<string, unknown>>;
  coordination_tasks: Array<Record<string, unknown>>;
  topology_templates: Array<Record<string, unknown>>;
  link_permission_matrix: {
    authority: string;
    rows: Array<Record<string, unknown>>;
  };
};

export type OperationAgentCatalog = {
  authority: string;
  agents: Array<Record<string, unknown>>;
  capabilities: Array<Record<string, unknown>>;
  summary: Record<string, number>;
};

export type SkillWorkflowCatalog = {
  authority: string;
  workflows: Array<Record<string, unknown>>;
  summary: Record<string, number>;
};

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
  recent_runs: TestRun[];
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
  issue_id: string;
  task_run_id: string;
  agent_id: string;
  agent_profile_id: string;
  runtime_lane: string;
  task_mode: string;
  workflow_id: string;
  projection_id: string;
  prompt_manifest_id: string;
  status: string;
  terminal_reason: string;
  result_ref?: string;
  created_at?: number;
  metadata?: Record<string, unknown>;
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

export type HealthAgentRunPreview = {
  authority: string;
  status: string;
  issue: Record<string, unknown>;
  flow: Record<string, unknown>;
  binding: Record<string, unknown>;
  projection_instance?: Record<string, unknown>;
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
    allowed_tools: string[];
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
  tool_scope: Record<string, unknown>;
};

export type OrchestrationCatalogTool = {
  name: string;
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
    bound_skills: Array<{
      name: string;
      title: string;
      activation_policy: string;
      context_mode: string;
    }>;
    bound_agents: Array<{
      agent_id: string;
      name: string;
    }>;
    ownership_label: string;
    governance_hints: string[];
  };
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
  skill_tool_edges: Array<{
    from: string;
    from_label: string;
    to: string;
    to_label: string;
    relation: string;
  }>;
  agent_tool_edges: Array<{
    from: string;
    from_label: string;
    to: string;
    to_label: string;
    relation: string;
  }>;
  recommendations: string[];
};

export type OperationCatalog = {
  skills: OperationSkill[];
  tools: OperationTool[];
  binding_graph: OperationBindingGraph;
  tool_type_options: string[];
  summary: {
    skill_count: number;
    tool_count: number;
    model_visible_skills: number;
    tool_types: string[];
    tool_boundaries: Record<string, number>;
    tool_sources: Record<string, number>;
    tool_risks: Record<string, number>;
  };
  validation_issues?: Array<{
    severity: string;
    code: string;
    message: string;
    subject: string;
  }>;
};

export type AgentSystemSkill = {
  id: string;
  name: string;
  description: string;
  tags: string[];
  input_modes: string[];
  output_modes: string[];
};

export type AgentSystemAgent = {
  agent_id: string;
  name: string;
  description: string;
  kind: string;
  worker_route: string;
  protocol_version: string;
  supports_streaming: boolean;
  supports_long_task: boolean;
  default_input_modes: string[];
  default_output_modes: string[];
  skills: AgentSystemSkill[];
  mcp_profile: Record<string, unknown>;
  extensions: Record<string, unknown>;
  enabled: boolean;
};

export type AgentProtocolLink = {
  link_id: string;
  from_agent: string;
  to_agent: string;
  label: string;
  enabled: boolean;
  input_contract: string;
  output_contract: string;
  handoff_policy: string;
  channels: string[];
};

export type AgentSystemCatalog = {
  protocol_version: string;
  agents: AgentSystemAgent[];
  protocol_links: AgentProtocolLink[];
  status_summary: {
    total_agents: number;
    enabled_agents: number;
    enabled_links: number;
    protocol_enabled_links?: number;
    blocked_links?: number;
  };
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
  working_habits: string[];
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
  role_type: string;
  task_mode: string;
  agent_profile_id: string;
  task_contract_summary: string;
  skill_views: Array<Record<string, unknown>>;
  tool_views: Array<Record<string, unknown>>;
  memory_policy_summary: string;
  output_contract_summary: string;
  style_content: string;
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
  role_type?: string;
  task_mode?: string;
  agent_profile_id?: string;
  projection_name?: string;
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
  task_contract_summary?: string;
  memory_policy_summary?: string;
  output_contract_summary?: string;
  style_content?: string;
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
  debug_policy: string;
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
  context_preview: MemorySessionInspect | null;
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
  return request<ExperimentProfile[]>("/experiments/profiles");
}

export async function listExperimentRuns(limit = 20) {
  return request<ExperimentRun[]>(`/experiments/runs?limit=${limit}`);
}

export async function startExperimentRun(profile: string) {
  return request<ExperimentRun>("/experiments/runs", {
    method: "POST",
    body: JSON.stringify({ profile })
  });
}

export async function getExperimentRun(runId: string) {
  return request<ExperimentRun>(`/experiments/runs/${encodeURIComponent(runId)}`);
}

export async function getExperimentArtifacts(runId: string) {
  return request<ExperimentArtifacts>(`/experiments/runs/${encodeURIComponent(runId)}/artifacts`);
}

export async function listExperimentTurns(runId: string) {
  return request<ExperimentTurn[]>(`/experiments/runs/${encodeURIComponent(runId)}/turns`);
}

export async function getExperimentGraphOverlay(runId: string) {
  return request<SystemGraphOverlay>(`/experiments/runs/${encodeURIComponent(runId)}/graph-overlay`);
}

export async function getExperimentTurnGraphOverlay(runId: string, turnId: string) {
  return request<SystemGraphOverlay>(
    `/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/graph-overlay`
  );
}

export async function getExperimentTurnPromptManifest(runId: string, turnId: string) {
  return request<PromptManifestResponse>(
    `/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/prompt-manifest`
  );
}

export async function getExperimentTurnMemoryTrace(runId: string, turnId: string) {
  return request<ExperimentTurnMemoryTraceResponse>(
    `/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/memory-trace`
  );
}

export async function getExperimentTurnOrchestration(runId: string, turnId: string, artifactPath = "") {
  const params = new URLSearchParams();
  if (artifactPath.trim()) {
    params.set("artifact_path", artifactPath.trim());
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<OrchestrationSnapshot>(
    `/experiments/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/orchestration${suffix}`
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

export async function getOperationCatalog() {
  return request<OperationCatalog>("/operations/catalog");
}

export async function refreshOperationCatalog() {
  return request<OperationCatalog>("/operations/catalog/refresh", {
    method: "POST"
  });
}

export async function createOperationSkill(payload: {
  name: string;
  title: string;
  description: string;
  content?: string;
}) {
  return request<OperationCatalog>("/operations/skills", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function saveOperationSkill(skillName: string, content: string) {
  return request<OperationCatalog>(`/operations/skills/${encodeURIComponent(skillName)}`, {
    method: "PUT",
    body: JSON.stringify({ content })
  });
}

export async function deleteOperationSkill(skillName: string) {
  return request<OperationCatalog>(`/operations/skills/${encodeURIComponent(skillName)}`, {
    method: "DELETE"
  });
}

export async function updateOperationSkillTools(skillName: string, allowedTools: string[]) {
  return request<OperationCatalog>(`/operations/skills/${encodeURIComponent(skillName)}/tools`, {
    method: "PUT",
    body: JSON.stringify({ allowed_tools: allowedTools })
  });
}

export async function updateOperationTool(toolName: string, payload: { tool_type: string; note?: string }) {
  return request<OperationCatalog>(`/operations/tools/${encodeURIComponent(toolName)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export async function getAgentSystemCatalog() {
  return request<AgentSystemCatalog>("/agents/catalog");
}

export async function setAgentEnabled(agentId: string, enabled: boolean) {
  return request<AgentSystemCatalog>(`/agents/${encodeURIComponent(agentId)}/enabled`, {
    method: "PUT",
    body: JSON.stringify({ enabled })
  });
}

export async function updateAgentProtocolLink(
  linkId: string,
  payload: Partial<Pick<AgentProtocolLink, "enabled" | "input_contract" | "output_contract" | "handoff_policy">>
) {
  return request<AgentSystemCatalog>(`/agents/protocol-links/${encodeURIComponent(linkId)}`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
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

export async function getOperationAgents() {
  return request<OperationAgentCatalog>("/operations/agents");
}

export async function getSkillWorkflows() {
  return request<SkillWorkflowCatalog>("/skills/workflows");
}

export async function getTaskSystemOverview() {
  return request<TaskSystemOverview>("/tasks/overview");
}

export async function getHealthSystemOverview() {
  return request<HealthSystemOverview>("/health-system/overview");
}

export async function getHealthWorkbenchOverview() {
  return request<HealthWorkbenchOverview>("/health-workbench/overview");
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

export async function startHealthAgentRun(issueId: string, taskMode = "issue_triage", sessionId = "health-system") {
  return request<HealthAgentRunStart>(
    `/health-system/issues/${encodeURIComponent(issueId)}/agent-runs`,
    {
      method: "POST",
      body: JSON.stringify({
        task_mode: taskMode,
        session_id: sessionId,
        source: "health_system_workspace"
      })
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
  return request<ExperimentRun>(`/experiments/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST"
  });
}

export async function listTestProfiles() {
  return request<TestProfile[]>("/test-system/profiles");
}

export async function getTestCases(includeLegacy = true) {
  return request<TestCaseRegistry>(`/test-system/cases?include_legacy=${includeLegacy ? "true" : "false"}`);
}

export async function getTestAgentReport() {
  return request<TestAgentReport>("/test-system/agent/report");
}

export async function getHarnessMap() {
  return request<HarnessMap>("/test-system/harness-map");
}

export async function getTestCaseTemplates() {
  return request<{ authority: string; templates: TestCaseTemplate[] }>("/test-system/case-templates");
}

export async function listLongScenarios() {
  return request<LongScenarioCatalog>("/test-system/long-scenarios");
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
  return request<HarnessMapCase>("/test-system/managed-cases", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function deleteManagedTestCase(caseId: string) {
  return request<{ ok: boolean; case_id: string }>(`/test-system/managed-cases/${encodeURIComponent(caseId)}`, {
    method: "DELETE"
  });
}

export async function listTestRuns(limit = 20) {
  return request<TestRun[]>(`/test-system/runs?limit=${limit}`);
}

export async function startTestRun(profile: string, scenarioIds: string[] = []) {
  return request<TestRun>("/test-system/runs", {
    method: "POST",
    body: JSON.stringify({ profile, scenario_ids: scenarioIds })
  });
}

export async function getTestRun(runId: string) {
  return request<TestRun>(`/test-system/runs/${encodeURIComponent(runId)}`);
}

export async function cancelTestRun(runId: string) {
  return request<TestRun>(`/test-system/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST"
  });
}

export async function getTestArtifacts(runId: string) {
  return request<TestArtifacts>(`/test-system/runs/${encodeURIComponent(runId)}/artifacts`);
}

export async function listTestTurns(runId: string) {
  return request<TestTurn[]>(`/test-system/runs/${encodeURIComponent(runId)}/turns`);
}

export async function getTestTurnRuntimeLoop(runId: string, turnId: string) {
  return request<Record<string, unknown>>(
    `/test-system/runs/${encodeURIComponent(runId)}/turns/${encodeURIComponent(turnId)}/runtime-loop`
  );
}

export async function streamChat(
  payload: {
    message: string;
    session_id: string;
    ephemeral_system_messages?: string[];
    search_policy?: string[];
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
