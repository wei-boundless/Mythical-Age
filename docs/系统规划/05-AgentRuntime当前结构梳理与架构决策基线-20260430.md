# AgentRuntime 当前结构梳理与架构决策基线

日期：2026-04-30  
定位：本文件用于在决定持久化工作流架构之前，梳理当前已经存在的核心结构、职责边界、缺口和下一步架构决策依据。它回答的问题不是“马上用哪个框架”，而是“我们现在有哪些结构，哪些结构应该成为 RuntimeWorkflow 的根，哪些结构还只是 preview / candidate”。

---

## 0. 总结论

当前系统已经有了任务导向 AgentRuntime 的骨架：

```text
TaskContract
ResourcePolicy / OperationGate
SoulProjection / PromptManifest
MemoryRuntimeView / MemoryCandidate
OrchestrationPlanPreview / ExecutionGraphPreview
RuntimeDirective(model-only)
OutputBoundary / CommitGate(blocked)
QueryAdapter
```

但它还不能成为“持久化完成任务”的系统，因为缺少：

```text
TaskRun
RuntimeWorkflow
RuntimeStepState
RuntimeCheckpointStore
正式 Adoption 管线
StageProjectionCycle
Artifact / ResultRef
CommitGate 真写回
```

架构决策基线：

```text
现有结构已经足够支撑自有 TaskRunLoop 合同。
TaskRunLoop 必须归属于 OrchestrationSystem，是统一 agent loop。
编排系统拥有唯一调度权。
下一步不应先选 LangGraph / DBOS / Temporal。
下一步应先把现有结构映射成 TaskRun -> TaskRunLoop -> WorkflowPlan -> RuntimeStep -> EventLog/Checkpoint。
成熟框架只能作为后续 graph / checkpoint / durable step 的承载实现。
```

---

## 1. 当前代码结构总览

### 1.1 已经分出的系统包

当前生产结构已经从旧 `backend/query` 中拆出：

```text
backend/tasks
backend/operations
backend/orchestration
backend/memory_system
backend/runtime
backend/execution
backend/soul
backend/prompting
backend/output_boundary
```

当前 `backend/query` 的定位：

```text
API 输入 adapter。
事件流输出 adapter。
调用 AgentRuntimeChain / model-only executor。
不再拥有 planner / tool / worker / follow-up 执行权。
```

### 1.2 当前真实主链

当前真实可执行链路仍然是最窄的 model-only lane：

```text
QueryRuntime
  -> AgentRuntimeChainAssembler.build_live_preview()
  -> TaskOperationPreview
  -> Orchestration preview / ControlKernel
  -> ModelResponseRuntimeExecutor.stream()
  -> RuntimeDirective(model)
  -> adopted ResourcePolicy(model_only)
  -> OperationGate.check(op.model_response)
  -> model_runtime.invoke_messages()
  -> OutputBoundary
  -> CommitGate(blocked)
```

这个状态的意义：

```text
执行真相已经开始从 query 迁到 RuntimeDirective。
模型回答也必须经过 OperationGate。
输出已经进入 OutputBoundary。
写回仍被 CommitGate 阻断。
```

---

## 2. 结构一：TaskContract

代码落点：

```text
backend/tasks/contracts.py
```

当前字段：

```text
task_id
session_id
user_goal
source
task_family
task_mode
parent_task_id
bindings
constraints
requested_outputs
candidate_refs
refs
status
authority = task_contract
```

当前职责：

```text
定义任务真相。
保存用户目标和任务分类。
承载 bindings / constraints / requested outputs。
为任务系统、灵魂投影、编排系统提供根输入。
```

不能承担：

```text
不能表示一次正在运行的任务实例。
不能表示步骤状态。
不能表示 checkpoint。
不能直接触发工具/worker/agent。
```

架构判断：

```text
TaskContract 是 TaskRun 的输入，不是 TaskRun 本身。
```

需要新增：

```text
TaskRun:
  task_run_id
  task_contract_ref
  owner_agent_seat_id
  status
  workflow_plan_ref
  execution_graph_ref
  latest_checkpoint_ref
```

---

## 3. 结构二：ResourcePolicy 与 OperationGate

代码落点：

```text
backend/operations/policies.py
backend/operations/gate.py
backend/operations/registry.py
```

当前 `ResourcePolicy` 字段：

```text
policy_id
task_id
allowed_operations
denied_operations
requires_approval_operations
preview_only_operations
allowed_tools / denied_tools
allowed_workers / denied_workers
allowed_agents / denied_agents
memory_read_scope
memory_write_scope
filesystem_scope
network_scope
shell_scope
approval_policy
preview_only
adopted
runtime_executable
decisions
```

当前 `OperationGate.check()` 做到：

```text
unknown operation -> deny
missing directive_ref -> deny
missing resource policy -> deny
preview-only / not adopted / not runtime_executable -> deny
denied_operations -> deny
requires_approval_operations -> requires_approval / approval token satisfied -> allow
operation-specific safety validator -> deny / pass
dangerous auto/bypass allow rule -> deny
denial tracking circuit open -> deny
not in allowed_operations -> deny
allowed_operations -> allow
```

当前职责：

```text
资源和操作授权边界。
执行前 fail-closed。
RuntimeDirective 前置检查。
```

当前缺口：

```text
缺 idempotency check。
缺 ApprovalState -> RuntimeCheckpoint 接线。
缺 headless hook / bubble-to-parent 事件接线。
缺真实 executor 层的 result size enforcement。
```

架构判断：

```text
OperationGate 是副作用前置真相。
TaskRunLoop 必须调用 OperationGate，但不能替代 OperationGate。
OperationGate 有否决权，没有调度权。
```

需要新增：

```text
OperationGatePipeline
IdempotencyPolicy
ApprovalState
OperationValidationResult
```

---

## 4. 结构三：OrchestrationPlanPreview 与 Adoption

代码落点：

```text
backend/orchestration/plan.py
backend/orchestration/adoption.py
```

当前 `OrchestrationPlanPreview` 字段：

```text
plan_id
task_id
topology_ref
topology_mode
task_contract_ref
task_prompt_contract_ref
resource_policy_ref
prompt_manifest_ref
selected_candidate_refs
stages
preview_only = True
adopted = False
runtime_executable = False
authority = orchestration_plan_preview
```

当前 `OrchestrationStagePreview` 字段：

```text
stage_id
plan_id
stage_type
stage_goal
executor_hint
candidate_refs
operation_refs
policy_refs
depends_on
blocked_reason = preview_only
runtime_executable = False
```

当前 `AdoptionCandidate`：

```text
只能报告 blocked。
不能真正 adopt plan。
不能真正 adopt resource policy。
authority = candidate_only。
```

已有 `AdoptedResourcePolicy`：

```text
已定义，但还不是主链正式 adoption 的结果。
```

架构判断：

```text
当前编排系统已经有 plan/stage 概念，但还停在 preview。
下一步必须让编排系统拥有统一 TaskRunLoop。
TaskRunLoop 只能消费 adopted plan / graph，不能消费 preview plan。
```

需要新增：

```text
WorkflowPlan / AdoptedWorkflowPlan
AdoptedExecutionGraph
AdoptionPipeline
PlanAdoptionResult
```

---

## 5. 结构四：ExecutionGraph 与 RuntimeDirective

代码落点：

```text
backend/orchestration/execution_graph.py
backend/orchestration/runtime_directive.py
```

当前 `ExecutionGraph` 字段：

```text
graph_id
task_id
nodes
edges
source_plan_id
refs
```

当前 `ExecutionNode` 字段：

```text
node_id
node_type = model / tool / worker / agent
executor
directive_ref
inputs
depends_on
policy_refs
authority = runtime_directive
```

当前 `RuntimeDirective` 字段：

```text
directive_id
task_id
plan_ref
stage_ref
executor_type = model / tool / worker / agent
adopted_resource_policy_ref
operation_refs
input_contract_ref
output_contract_ref
execution_graph_ref
runtime_executable = True
authority = runtime_directive
```

当前已成立的好原则：

```text
Executor 只能消费 RuntimeDirective。
RuntimeDirective 不能引用 preview plan/stage。
RuntimeDirective 必须有 adopted_resource_policy_ref。
```

当前缺口：

```text
RuntimeDirective 还没有 RuntimeStepState。
ExecutionGraph 还没有成为持久执行拓扑。
model-only executor 内部临时构造 RuntimeDirective。
tool / worker / agent executor 还未接入。
```

架构判断：

```text
ExecutionGraph / RuntimeDirective 是执行真相。
但持久化任务还需要 RuntimeStepState 包住 RuntimeDirective，并由 TaskRunLoop 统一推进。
```

需要新增：

```text
RuntimeStepState
DirectiveState
ExecutionGraphRunner
RuntimeWorkflowRunner
```

---

## 6. 结构五：MemorySystem

代码落点：

```text
backend/memory_system/contracts.py
backend/memory_system/runtime_view.py
backend/memory_system/gate.py
backend/memory_system/writeback.py
```

当前已有核心对象：

```text
MemoryContextCandidate
StateMemoryRestoreCandidate
ConversationMemorySnapshot
StateMemorySnapshot
LongTermMemoryRecord
MemoryWriteCandidate
MemoryCommitRecord
```

当前已成立原则：

```text
MemoryContextCandidate authority = candidate_only。
MemoryContextCandidate cannot override current-turn truth。
StateMemoryRestoreCandidate cannot self-promote to current fact。
MemoryWriteCandidate 只是候选。
MemoryCommitRecord 是治理记录，不携带 runtime authority。
```

当前职责：

```text
提供对话记忆、状态记忆、长期记忆候选。
提供上下文包 preview。
提供写回候选。
阻止 memory restore 覆盖当前任务目标。
```

当前缺口：

```text
AgentMemoryScope 尚未正式接入 RuntimeWorkflow。
Memory state 未进入 RuntimeCheckpoint。
MemoryWriteCandidate 还不能通过 CommitGate 正式写回。
StageProjectionCycle 还没有每步消费 memory scope。
```

架构判断：

```text
MemorySystem 是上下文和候选源，不是工作流决策者。
TaskRunLoop checkpoint 应记录 memory_state_refs，而不是复制全部 memory 内容。
MemorySystem 不拥有 RuntimeStep 推进权。
```

需要新增：

```text
AgentMemoryScope
MemoryScopeRef
ContextPackageRef
CheckpointMemoryState
```

---

## 7. 结构六：SoulProjection / PromptManifest

代码落点：

```text
backend/soul/projection.py
backend/soul/contracts.py
backend/prompting/manifest.py
```

当前 SoulProjection 能生成：

```text
identity_view
static_common_rules
dynamic_task_contract
role_view
skill_view
tool_view
memory_output_view
PromptManifest
```

当前已成立原则：

```text
灵魂投影只改变承载方式，不扩大工具、记忆或调度权限。
工具授权仍由 ResourcePolicy 决定。
PromptManifest 记录模型可见上下文来源。
```

当前职责：

```text
根据 TaskPromptContract / ResourceRuntimeView / SkillRuntimeView 生成模型可见投影。
承载任务姿态、角色姿态、输出边界。
```

当前缺口：

```text
还没有 StageProjectionCycle。
还没有 AgentSeat 级投影。
还没有每个 RuntimeStep 前重建 projection 的机制。
PromptManifest 还没有进入 RuntimeCheckpoint。
```

架构判断：

```text
SoulProjection 可以成为每个 RuntimeStep 的认知承载机制。
但 SoulProjection 不能成为执行循环或编排决策者。
StageProjectionCycle 必须由 TaskRunLoop 在每个 step 前统一调用。
```

需要新增：

```text
StageProjectionCycle
AgentSeatProjection
ProjectionCheckpointRef
```

---

## 8. 结构七：OutputBoundary 与 CommitGate

代码落点：

```text
backend/output_boundary/*
backend/orchestration/commit_gate.py
backend/execution/model_response.py
```

当前行为：

```text
ModelResponseRuntimeExecutor 调用 AssistantOutputBoundary。
输出被规范化为 canonical answer / visible text / persist policy。
Runtime CommitGate 目前 blocked。
done event 带 persist_policy = commit_gate_blocked。
```

当前职责：

```text
OutputBoundary 管可见答案。
CommitGate 管写回许可。
```

当前缺口：

```text
CommitGate 还不能写 task_run status。
CommitGate 还不能写 session projection。
CommitGate 还不能写 artifact refs。
CommitGate 还不能处理 durable memory candidate。
ResultArtifact / ArtifactRef 尚未形成统一体系。
```

架构判断：

```text
持久化完成任务必须先放行最小 CommitGate：
  task_run status
  assistant/session projection
  artifact refs
  final answer record

durable memory write 可以继续 blocked。
CommitGate 有写回治理权，没有调度权。
```

需要新增：

```text
CommitPlan
CommitDecision
CommitApplier
ArtifactRef
ResultArtifact
```

---

## 9. 结构八：AgentRuntimeChainAssembler 与 ModelResponseRuntimeExecutor

代码落点：

```text
backend/runtime/agent_chain.py
backend/execution/model_response.py
```

当前 `AgentRuntimeChainAssembler` 做：

```text
analyze_memory_intent
build_memory_runtime_view_payload
build_context_policy_result
build_task_runtime_contract_preview
build_agent_runtime_chain_preview
```

当前 `ModelResponseRuntimeExecutor` 做：

```text
build_runtime_directive(task_operation_preview)
build adopted ResourcePolicy(model_only)
OperationGate.check(op.model_response)
invoke model
OutputBoundary
CommitGate blocked
```

当前价值：

```text
已经证明 model-only lane 可以按 directive-only executor 运行。
已经证明 query 可以退到 adapter。
```

当前问题：

```text
RuntimeDirective 是 executor 内部临时构造。
ResourcePolicy 是 executor 内部临时构造。
没有 TaskRun。
没有 RuntimeStepState。
没有 checkpoint。
没有 StageProjectionCycle。
```

架构判断：

```text
这条链应该成为 Phase 1 的接管对象：
  不改变行为。
  外面包 OrchestrationSystem.TaskRunLoop / RuntimeStepState / EventLog / Checkpoint。
  再逐步把临时 directive/policy 移到 AdoptionPipeline。
```

---

## 10. 当前结构关系图

```text
UserRequest
  -> QueryAdapter
  -> AgentRuntimeChainAssembler
     -> MemoryRuntimeView
     -> ContextPolicyPreview
     -> TaskOperationPreview
        -> TaskContract
        -> ResourcePolicyPreview
        -> TaskPromptContract
        -> SoulRuntimeView / PromptManifestPreview
        -> OrchestrationPlanPreview
        -> ExecutionGraphPreview
        -> AdoptionCandidate(blocked)
        -> RuntimeDirectiveCandidate(blocked)
  -> ModelResponseRuntimeExecutor
     -> RuntimeDirective(model, temporary runtime)
     -> ResourcePolicy(model_only, temporary adopted)
     -> OperationGate
     -> ModelRuntime
     -> OutputBoundary
     -> CommitGate(blocked)
```

这个图暴露了最关键断点：

```text
preview 链与 runtime 链之间缺正式 Adoption。
runtime 链缺 TaskRun / StepState / Checkpoint。
SoulProjection 只在 preview 链中，没有每步投影循环。
CommitGate blocked 导致任务无法持久闭环。
```

---

## 11. 架构决策前的关键问题

在决定用什么架构前，必须先回答这些问题：

### 11.1 RuntimeWorkflow 的根对象是什么

建议答案：

```text
TaskRun。
```

理由：

```text
我们是任务导向，不是 query 导向。
单 agent 和多 agent 都应该挂在 TaskRun 下。
```

### 11.2 TaskRunLoop 消费什么

建议答案：

```text
AdoptedWorkflowPlan
AdoptedExecutionGraph
RuntimeStepState
RuntimeDirective
```

不应消费：

```text
OrchestrationPlanPreview
RuntimeDirectiveCandidate
MemoryRestoreCandidate
旧 query plan
```

补充：

```text
TaskRunLoop 是 OrchestrationSystem 的运行时 loop。
它消费 adopted workflow objects，推进 RuntimeStep。
其他系统只提供候选、合同、投影、权限结果、上下文包、写回决策。
```

### 11.3 每一步执行前必须有什么

建议答案：

```text
RuntimeStepState(status=ready)
RuntimeDirective
AdoptedResourcePolicy
OperationGate allow / waiting_approval
StageProjection
ContextPackageRef
IdempotencyKey
```

### 11.4 每一步执行后必须产什么

建议答案：

```text
RuntimeEvent
ResultCandidate
ResultArtifactRef(optional)
RuntimeStepState update
RuntimeCheckpoint
CommitCandidate(optional)
```

### 11.5 什么可以写回

第一阶段建议：

```text
允许：
  TaskRun status
  RuntimeCheckpoint
  RuntimeEvent
  final answer record
  artifact refs

继续 blocked：
  durable memory write
  filesystem write
  external send
  agent-to-agent autonomous handoff
```

---

## 12. 推荐的结构演进顺序

### Phase A：统一 TaskRunLoop 骨架，不改变行为

新增：

```text
TaskRun
RuntimeStepState
RuntimeCheckpoint
RuntimeEvent
RuntimeEventLog
RuntimeStateIndex
TaskRunLoop
```

接入：

```text
model-only lane。
```

目标：

```text
每次请求都有 TaskRun。
每次模型执行有 step。
每次 loop 关键节点有 event。
每次结束有 checkpoint。
TaskRunLoop 归 OrchestrationSystem 所有。
```

### Phase B：StageProjectionCycle

新增：

```text
AgentSeat
StageProjectionCycle
ProjectionCheckpointRef
```

目标：

```text
每个 RuntimeStep 执行前调用 SoulProjection。
投影进入 PromptManifest。
投影 ref 进入 checkpoint。
```

### Phase C：正式 Adoption

新增：

```text
AdoptionPipeline
AdoptedWorkflowPlan
AdoptedExecutionGraph
AdoptedResourcePolicy
```

目标：

```text
executor 不再临时构造 runtime policy。
RuntimeWorkflow 只消费 adopted 对象。
```

### Phase D：最小 CommitGate

新增：

```text
CommitPlan
CommitDecision
CommitApplier
ArtifactRef
```

目标：

```text
task_run 状态、checkpoint、final answer、artifact ref 能持久闭环。
长期记忆写回仍 blocked。
```

### Phase E：read-only tool / worker

新增：

```text
ToolExecutor(read_only)
WorkerExecutor
OperationGatePipeline
ResultArtifact
```

目标：

```text
只读能力作为 RuntimeStep 接入。
结果不直接变 final answer。
```

### Phase F：多 AgentSeat preview

新增：

```text
AgentSeatPlan
AgentMemoryScope
BoundedAgentDirectiveCandidate
```

目标：

```text
写作流程 / 公司协作流程可以 preview。
真实子 agent 仍等后续放行。
```

---

## 13. 架构选择基线

根据当前结构，架构选择应该遵守：

```text
先补 OrchestrationSystem.TaskRunLoop 合同。
再决定承载实现。
```

候选承载：

```text
轻量自有 store:
  适合 Phase A-D。
  JSON / SQLite 均可。
  最低引入成本。

LangGraph:
  适合 graph / checkpoint / interrupt。
  但必须等 TaskRunLoop 合同稳定后再接。

DBOS:
  适合 durable workflow / step。
  适合未来后台长任务。

Temporal:
  适合强恢复、跨进程、复杂长任务。
  当前不是第一阶段。
```

当前建议：

```text
Phase A-D 使用自有 TaskRunLoop 合同 + 轻量持久化。
Phase E 后再评估 LangGraph / DBOS 是否值得接入。
Temporal 保留为强工程化外层。
```

---

## 14. 最终判断

当前结构离持久化完成任务还差的不是一个框架，而是几个核心运行态对象：

```text
TaskRun
TaskRunLoop
RuntimeStepState
RuntimeEventLog
RuntimeCheckpoint
StageProjectionCycle
CommitPlan
ArtifactRef
```

等这些对象稳定后，外部框架的选择才会变清楚：

```text
如果主要需要状态图和中断恢复，接 LangGraph。
如果主要需要 durable step 和后台任务，接 DBOS。
如果主要需要跨进程强恢复，接 Temporal。
如果当前只是 model/tool/worker 主链持久化，先用自有轻量 store。
```

一句话：

```text
我们先把自己的结构梳理成 Orchestration-owned TaskRunLoop，
再让框架为我们的结构服务。
不要让框架反过来重写我们的系统边界。
```

---

## 15. 对 Claude Code Query Loop 的重新判断

经过对 Claude Code 源码细节和当前系统状态的再次对照，需要修正一个口径：

```text
我们不应该恢复旧 backend/query 的职责，
但确实应该吸收 Claude Code query loop 的运行范式。
```

这里的关键区别是：

```text
旧 query:
  API 输入、理解、规划、检索、工具、worker、记忆写回、最终答案混在一起。

Claude Code query loop 的成熟思想:
  一个持续运行的 turn / task loop，
  严格管理消息、工具调用、权限、压缩、审批、中断、恢复和输出。

洪荒时代应采用的形态:
  OrchestrationSystem.TaskRunLoop，
  而不是 QueryRuntime 重新变厚。
```

### 15.1 应该移植的部分

Claude Code query loop 值得移植的是“运行时循环不变量”，不是文件结构：

```text
1. 每一轮都有明确 loop state。
2. 每一次模型调用、工具调用、审批等待、压缩、输出都进入事件流。
3. 工具/worker/agent 调用必须先经过权限和安全管线。
4. 中断、恢复、压缩、重试不是外围补丁，而是 loop 的内建阶段。
5. loop 负责统一推进状态，并拥有当前 TaskRun 的唯一推进权。
6. 任务、记忆、投影、权限、输出、写回都必须作为 loop 阶段被调用。
```

映射到我们这里：

```text
query loop state      -> RuntimeLoopState / RuntimeCheckpoint
tool_use iteration    -> RuntimeStep / RuntimeDirective
permission check      -> OperationGatePipeline
context compact       -> ContextPolicy / MemorySystem
subagent task         -> AgentSeat / BoundedAgentDirective
final response        -> OutputBoundary + CommitGate
```

### 15.2 不应该移植的部分

不能把 Claude Code 的 query loop 原样搬成一个新的中央大函数：

```text
不让 RuntimeLoop 自己理解任务。
不让 RuntimeLoop 自己决定工具权限。
不让 RuntimeLoop 自己写长期记忆。
不让 RuntimeLoop 自己绕过 CommitGate 写 session。
不让 backend/query 重新拥有 planner / worker / tool / memory write。
```

原因：

```text
我们的系统已经有任务系统、操作系统、灵魂系统、记忆系统、编排系统。
Claude Code 是一个成熟的一体化 coding agent loop；
洪荒时代要做的是任务导向、多系统协同、可单可多的 AgentRuntime。
```

### 15.3 新目标：OrchestrationSystem.TaskRunLoop

建议把后续持久化主循环正式命名为：

```text
OrchestrationSystem.TaskRunLoop
```

它的职责：

```text
load / create TaskRun
load latest RuntimeCheckpoint
select next RuntimeStep
call SoulSystem to build StageProjectionCycle
call MemorySystem / ContextPolicy to build ContextPackage
call executor through RuntimeDirective
call OperationGate before side effects
collect ResultCandidate / ResultArtifact
call CommitGate for writeback decision
write RuntimeEvent
write RuntimeCheckpoint
decide continue / wait / stop
```

它拥有：

```text
当前 TaskRun 的唯一推进权。
RuntimeStep 的唯一状态迁移权。
WorkflowPlan / ExecutionGraph 的运行时消费权。
RuntimeEventLog / RuntimeCheckpoint 的写入权。
```

它不负责：

```text
任务定义：归 TaskSystem。
拓扑决策：归 OrchestrationSystem 的 planner/adoption 阶段。
权限授权：归 OperationSystem。
记忆候选：归 MemorySystem。
最终可见答案治理：归 OutputBoundary。
写回：归 CommitGate。
```

### 15.4 固定执行流

第一版 `TaskRunLoop` 应该按这个固定顺序推进：

```text
UserRequest
  -> QueryAdapter
  -> TaskSystem.build TaskContract
  -> OrchestrationSystem.adopt single-agent WorkflowPlan
  -> OrchestrationSystem.TaskRunLoop.start / resume
     -> RuntimeStep.ready
     -> call SoulSystem.StageProjectionCycle
     -> call MemorySystem / ContextPolicy package
     -> RuntimeDirective
     -> call OperationGate
     -> Executor
     -> ResultCandidate
     -> call OutputBoundary
     -> call CommitGate
     -> RuntimeCheckpoint
  -> QueryAdapter streams events
```

这个流比旧 query loop 多了几个明确边界：

```text
TaskContract 是任务真相。
WorkflowPlan 是流程真相。
RuntimeDirective 是执行真相。
OperationGate 是副作用前置真相。
CommitGate 是写回真相。
RuntimeCheckpoint 是恢复真相。
```

### 15.5 对当前实施顺序的影响

因此后续不应直接恢复 tool / worker / agent，而应先落：

```text
1. TaskRunLoop 数据模型。
2. RuntimeLoopState / RuntimeCheckpoint。
3. model-only lane 进入 TaskRunLoop。
4. StageProjectionCycle 进入每个 RuntimeStep。
5. OperationGatePipeline 作为 step preflight。
6. CommitGate 写 checkpoint / final answer record。
7. 再逐步恢复 read-only tool / worker / bounded agent。
```

这意味着：

```text
我们开始从 query loop 思想改 runtime，
但不回滚 query 清理成果。
QueryRuntime 仍然保持 adapter-only。
真正变厚的是 OrchestrationSystem.TaskRunLoop。
这是对 Codex / Claude Code 统一 loop 范式的正面采用。
```
