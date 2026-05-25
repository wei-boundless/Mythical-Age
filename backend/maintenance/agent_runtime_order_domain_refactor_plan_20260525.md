# Agent Runtime Order/Domain Refactor Plan 2026-05-25

Status: draft for review. Do not implement before approval.

## 1. Background

The current single-agent runtime has grown into a mixed control chain. It already contains useful pieces such as `RequestFacts`, `BoundaryPolicy`, `ModelTurnDecision`, `ActionPermit`, runtime context assembly, tool execution, observation recording, and final commit gates. However, the chain also mixes several authorities that should be separate:

- Task domain selection.
- Task order creation.
- Agent assembly mode selection.
- Agent behavior planning.
- System guardrails and validation.
- Runtime loop execution.

This refactor is not a cosmetic cleanup. It is an authority cleanup. The goal is to make the platform behave like an agent factory:

```text
TaskDomain = company that issues orders
Platform = accepts orders, prepares environment, enforces guardrails
AgentFactory = assembles an agent product for the order
Agent = completes the order
RuntimeLoop = executes the agent's work cycle
```

The key correction is that task domain must not be chosen by the agent. A domain is a system/user/order binding, not an agent decision.

## 2. Core Architectural Rules

### 2.1 Task Domain

`TaskDomain` represents the order-issuing company. It is system-level and must be selected or bound before an executable task enters the agent runtime.

Allowed task domain sources:

```text
1. User explicit selection.
2. Active session binding.
3. TaskOrder binding.
4. TaskGraph node binding.
```

Disallowed task domain sources:

```text
1. ModelTurnDecision guess.
2. Keyword classifier.
3. AgentPlan field.
4. RuntimeLoop fallback.
5. Any automatic domain switch produced by the agent.
```

`domain_id` may exist in registries, orders, audit logs, and trace metadata. It must not be an agent behavior decision field.

### 2.2 Interaction Mode

`InteractionMode` is agent assembly control, not task domain control.

Examples:

```text
role_mode
standard_mode
professional_mode
```

Mode may decide:

- Agent profile and runtime lane.
- Prompt structure.
- Whether a plan/todo/evidence packet is required.
- Whether delegation is available.
- Whether the loop is short turn or long task.

Mode must not decide:

- Which task domain is active.
- Which company's task catalog is available.
- Which system-level resource namespace is active.

### 2.3 Task Order

`TaskOrder` / `WorkOrder` is the contract passed from the task domain/platform into the agent factory.

The agent does not choose the company. The agent only receives the order translated into executable terms:

```text
WorkOrder
RolePrompt
InputContract
OutputContract
ResourcePolicy
ToolSurface
MemoryContext
AcceptanceRule
ExecutionGuardrail
```

### 2.4 Agent Behavior

The agent owns:

- Understanding the order goal.
- Producing an `AgentPlan`.
- Choosing next action.
- Requesting tool calls.
- Interpreting observations.
- Replanning.
- Producing final answer candidate.
- Asking clarification when needed.

The system may require the agent to produce a plan and may validate the plan. The system must not produce the concrete agent behavior plan and then drive the agent through it.

### 2.5 System Behavior

The system owns:

- User/session/order/domain binding.
- Runtime environment preparation.
- Agent assembly.
- Tool availability and authorization.
- Permission, sandbox, budget, and irreversible-action guardrails.
- Tool execution.
- Observation recording.
- Evidence and acceptance validation.
- Final commit to session/task result/memory/checkpoint.

The system may reject unsafe or incomplete actions. It should not steer the agent's next behavior step except by returning validation feedback or observation.

## 3. Target Runtime Flow

The target flow is:

```text
UserInput
-> Query/API Adapter
-> ActiveDomainBinding check
-> TaskOrder creation/recovery
-> WorkOrder translation
-> RuntimeEnvironment build
-> AgentFactory assembly by InteractionMode
-> AgentInvocation
-> AgentRuntimeLoop
-> ToolCall authorization/execution
-> Observation returned to agent
-> Agent replan/final answer
-> System validation/commit
```

Important property:

```text
TaskDomain is resolved before agent execution.
TaskDomain does not appear as a decision inside the agent runtime loop.
```

If no task domain is selected:

```text
Plain conversation may run in no_task_domain/general conversation.
Executable task must ask user to choose a domain.
Continuation must use the previous order's domain binding.
TaskGraph node must use the node/order binding.
```

## 4. System-Agent Interface

### 4.1 System to Agent

The system sends one `AgentInvocation`:

```text
AgentInvocation {
  work_order
  role_prompt
  input_contract
  output_contract
  tool_surface
  resource_policy
  memory_context
  acceptance_rules
  guardrails
  runtime_budget
}
```

It must not include:

```text
choose_task_domain
switch_domain
domain_guess
domain_reasoning_as_agent_instruction
```

### 4.2 Agent to System

The agent emits structured events:

```text
AgentPlanSubmitted
ToolCallRequested
ProgressReported
ObservationInterpreted
ReplanSubmitted
FinalAnswerCandidate
ClarificationRequested
```

The agent does not directly mutate system state.

### 4.3 System to Agent Observations

The system returns observations:

```text
ToolResult
ValidationResult
PermissionDenial
BudgetState
AcceptanceFeedback
ClarificationInput
```

This is the only feedback channel the system should use to influence the next agent turn.

## 5. Current Code Findings

### 5.1 Entry Chain

Current entry chain:

```text
backend/api/chat.py
-> backend/query/runtime.py::QueryRuntime.astream
-> backend/runtime/unit_runtime/loop.py::TaskRunLoop.run_single_agent_stream
-> backend/agent_system/assembly/runtime_chain.py::AgentRuntimeChainAssembler.build_runtime
-> backend/task_system/services/assembly_builder.py::build_task_execution_assembly_bundle
-> backend/task_system/planning/execution_recipe_builder.py::build_execution_recipe
-> backend/runtime/execution_engine/engine.py::RuntimeExecutionEngine
or backend/runtime/professional_runtime/driver.py::ProfessionalTaskRunDriver
```

Healthy pieces to preserve:

- Request facts capture.
- Boundary policy.
- Model-owned turn understanding.
- Action permit.
- Runtime start packet.
- Tool authorization and observation recording.
- Commit gates and final task result persistence.

Authority conflicts to fix:

- `TaskRunLoop` owns too many responsibilities.
- `ModelTurnDecision`/goal projection can carry domain-like semantics.
- `_fallback_model_turn_decision` can synthesize executable agent understanding.
- `interaction_mode_policy` mixes agent assembly with system resource policy.
- `execution_recipe_builder` creates `agent_plan_draft` and compiled steps.
- `ProfessionalTaskRunDriver` acts as a second controller.
- `ActionGate` mixes guardrails with next-action steering.

### 5.2 Domain Records Are Too Thin

Existing `TaskDomainRecord` is currently a registry record, not a runtime initialization profile. It does not yet express the full system environment that a domain provides.

Target: introduce a domain runtime profile that can initialize:

- Task catalog.
- Task graph catalog.
- Workflow catalog.
- Resource roots.
- Memory namespace.
- Artifact roots.
- Tool surface ceiling.
- Acceptance/evidence policy.
- Agent pool constraints.

### 5.3 Mode Policy Is Too Fat

Existing interaction mode policy currently carries items such as tool policy, sandbox policy, context policy, verification policy, and output policy. These are partly system environment concerns and should move toward domain/order/runtime environment.

Target:

```text
InteractionModePolicy = agent assembly posture
RuntimeEnvironmentPolicy = system environment and guardrails
```

### 5.4 System-Generated Agent Plan

Current `execution_recipe_builder` calls:

```text
build_agent_plan_draft
review_plan_coverage
compile_understanding_runtime_steps
```

Target:

```text
PlanRequirement
AgentPlanSchema
PlanValidationRule
PlanCoverageReview
```

The actual `AgentPlan` must be produced by the agent.

## 6. Target Module Shape

This is the desired direction, not necessarily the final package names:

```text
backend/task_system/domains/
  domain_models.py
  domain_registry.py
  domain_runtime_profile.py
  active_domain_binding.py

backend/task_system/orders/
  order_models.py
  order_factory.py
  work_order_builder.py

backend/runtime/environment/
  runtime_environment.py
  resource_policy.py
  tool_surface.py
  acceptance_policy.py

backend/agent_system/factory/
  agent_factory.py
  invocation_builder.py
  mode_assembly.py

backend/runtime/agent_loop/
  loop.py
  agent_events.py
  observations.py
  plan_validation.py

backend/runtime/guardrails/
  permission_gate.py
  budget_gate.py
  acceptance_gate.py
  evidence_recorder.py
```

Large moves should be done only after the authority chain is implemented and tests are ready.

## 7. Refactor Stages

### Stage 0: Freeze Authority Contract

Deliverables:

- Add a small architecture document or contract tests that assert:
  - Agent cannot select domain.
  - Runtime loop cannot switch domain.
  - Executable task requires active domain/order binding.
  - Agent receives work order and environment, not domain selection authority.

No runtime behavior rewrite yet.

### Stage 1: Domain Binding and Runtime Profile

Introduce system-side domain binding:

```text
ActiveDomainBinding
TaskDomainRuntimeProfile
DomainRuntimeEnvironmentSeed
```

Rules:

- Domain comes from user/session/order/task graph node.
- If executable task has no domain, return clarification/domain selection required.
- Existing general conversation may continue without executable domain.

Files likely touched:

- `backend/task_system/registry/flow_models.py`
- `backend/task_system/registry/flow_registry.py`
- `backend/task_system/domains/*`
- `backend/query/runtime.py`
- `backend/task_system/orders/*`

### Stage 2: WorkOrder Boundary

Create a clean `WorkOrder` object between task system and agent runtime.

The work order should contain:

- Objective.
- Inputs.
- Output contract.
- Acceptance rules.
- Resource needs.
- Tool needs.
- Memory needs.
- Execution constraints.
- Agent assembly hints.

It should not contain agent-selected domain.

Files likely touched:

- `backend/task_system/orders/order_factory.py`
- `backend/task_system/services/assembly_builder.py`
- new `backend/task_system/orders/work_order_builder.py`
- `backend/agent_system/assembly/runtime_chain.py`

### Stage 3: RuntimeEnvironment Boundary

Move system environment initialization out of interaction mode.

Create:

```text
RuntimeEnvironment
ToolSurface
ResourcePolicy
AcceptancePolicy
EvidencePolicy
BudgetPolicy
SandboxPolicy
```

These are built from:

```text
TaskDomainRuntimeProfile
TaskOrder / WorkOrder
TaskGraph node binding
Platform settings
```

They are not chosen by the agent.

Files likely touched:

- `backend/orchestration/interaction_mode_policy.py`
- `backend/task_system/services/assembly_support.py`
- `backend/task_system/services/assembly_builder.py`
- `backend/runtime/unit_runtime/loop.py`
- `backend/permissions/*`
- `backend/runtime/tool_runtime/*`

### Stage 4: AgentFactory and AgentInvocation

Replace broad runtime assembly with an explicit agent invocation package:

```text
AgentInvocation = AgentFactory.build(
  work_order,
  runtime_environment,
  interaction_mode,
  agent_profile
)
```

The invocation contains model-visible instructions and system-side execution permissions, but does not include domain decision authority.

Files likely touched:

- `backend/agent_system/assembly/runtime_chain.py`
- `backend/runtime/agent_assembly/*`
- `backend/agent_system/profiles/*`
- `backend/runtime/shared/context_manager.py`

### Stage 5: Agent-Owned Plan

Remove system-generated concrete plan from recipe building.

Replace:

```text
build_agent_plan_draft
compile_understanding_runtime_steps as agent behavior script
```

With:

```text
PlanRequirement
AgentPlan schema
PlanValidation
PlanCoverageReview
```

System can reject and ask the agent to repair the plan. System cannot create the concrete plan.

Files likely touched:

- `backend/task_system/planning/execution_recipe_builder.py`
- `backend/runtime/professional_runtime/agent_plan.py`
- `backend/runtime/professional_runtime/plan_coverage.py`
- `backend/task_system/planning/understanding_step_compiler.py`
- professional task tests protecting old draft behavior.

### Stage 6: Runtime Loop Slimming

Split `TaskRunLoop.run_single_agent_stream` into:

```text
RuntimeRunCoordinator
AgentLoop
ToolObservationBridge
CommitFinalizer
TraceRecorder
```

Rules:

- Loop does not parse domain.
- Loop does not synthesize agent understanding.
- Loop does not generate agent plan.
- Loop executes agent events and returns observations.

Files likely touched:

- `backend/runtime/unit_runtime/loop.py`
- `backend/runtime/execution_engine/*`
- `backend/runtime/unit_runtime/finalizer.py`
- `backend/runtime/shared/*`

### Stage 7: Professional Driver Decomposition

Split professional runtime into:

```text
LongTaskAgentLoop
EvidenceRecorder
AcceptanceValidator
CloseoutRepairValidator
BudgetGuard
```

Keep:

- Evidence packet.
- Deliverable validation.
- Obligation validation.
- Budget/permission guards.
- Closeout repair when validation fails.

Remove/rewrite:

- Next-action steering as system decision.
- System-authored action plan.
- Any fallback that produces fake completion.

Files likely touched:

- `backend/runtime/professional_runtime/driver.py`
- `backend/runtime/professional_runtime/action_gate.py`
- `backend/runtime/professional_runtime/runtime_policy.py`
- `backend/runtime/professional_runtime/evidence_closeout.py`

### Stage 8: Tests and Legacy Cleanup

Update or delete tests that protect old authority. Tests should protect target behavior, not old internals.

Likely test changes:

- Remove tests that expect fallback model decisions to keep execution alive.
- Replace agent plan draft tests with plan requirement/validation tests.
- Add tests that domain cannot be selected by model output.
- Add tests that executable task without domain fails closed or asks for selection.
- Add tests that agent invocation excludes domain decision fields.
- Add tests that system validates but does not generate agent plan.

Existing suspicious tests:

- `backend/tests/model_turn_decision_validation_regression.py`
- `backend/tests/agent_plan_draft_regression.py`
- `backend/tests/professional_task_run_regression.py`
- `backend/tests/professional_runtime_feedback_regression.py`

## 8. Deletion and Rewrite Criteria

Delete or rewrite code when:

- It selects task domain from model output.
- It keeps old domain fallback behavior alive.
- It generates concrete agent behavior steps.
- It drives agent next action from system policy instead of returning observation/validation feedback.
- It exists only to preserve old runtime structure.
- It has tests that assert old internal fallback behavior instead of user-visible correctness.

Keep code when:

- It records facts.
- It validates authority.
- It enforces permission/budget/sandbox.
- It executes authorized tools.
- It records observations.
- It persists task/session/memory result.
- It helps assemble an agent invocation without taking agent decision authority.

## 9. Verification Plan

Focused tests to add:

```text
test_domain_requires_user_or_order_binding
test_model_turn_decision_cannot_select_domain
test_executable_task_without_domain_requests_domain_selection
test_task_order_domain_binding_flows_to_runtime_environment
test_agent_invocation_does_not_include_domain_decision_fields
test_system_requires_agent_plan_but_does_not_generate_concrete_plan
test_action_gate_rejects_invalid_action_without_steering_next_action
```

Focused test commands after implementation slices:

```powershell
pytest backend/tests/model_turn_decision_validation_regression.py
pytest backend/tests/agent_plan_draft_regression.py
pytest backend/tests/professional_runtime_feedback_regression.py
pytest backend/tests/professional_task_run_regression.py
pytest backend/tests/query_runtime_runtime_loop_regression.py
```

These commands will need to be adjusted as tests are renamed or deleted during cleanup.

Broader verification:

```powershell
pytest backend/tests
```

Manual trace checks:

- Start a normal chat without task domain.
- Start executable task without domain and confirm domain selection is required.
- Start executable task with explicit domain and confirm WorkOrder builds.
- Run a professional task and confirm agent plan is agent-authored.
- Confirm final commit writes session message, task result, checkpoint, and memory receipts.

## 10. Implementation Stop Conditions

Stop and ask for review if:

- Domain binding cannot be derived from user/session/order/task graph without changing product UX.
- Existing task graph runtime depends on domain being inferred inside agent loop.
- Tests reveal that current UI cannot create or persist active domain binding.
- A planned deletion would remove real user-visible behavior without a replacement.

Do not stop merely because an old regression test fails. If the test protects old authority, rewrite or delete it in the same implementation slice.

## 11. Expected End State

The final architecture should have one direction of authority:

```text
User/System selects TaskDomain
-> Domain issues or constrains TaskOrder
-> Platform builds WorkOrder and RuntimeEnvironment
-> AgentFactory assembles agent by InteractionMode
-> Agent performs plan/action/observation/final answer
-> System validates, executes tools, records, and commits
```

The agent runtime should no longer contain task domain selection or system-authored behavior plans.

