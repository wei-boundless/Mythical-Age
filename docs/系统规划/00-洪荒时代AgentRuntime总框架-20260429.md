# 洪荒时代 Agent Runtime 总框架

日期：2026-04-29  
定位：本文件是 `docs/系统规划` 的总框架文件，用于指导后续灵魂系统、任务系统、操作系统、编排系统、记忆系统、执行层、写回层和旧 `query` 层迁移。  
当前口径：先完成单主 agent 主链；多智能体作为后续可扩展架构，由任务系统作为管理总入口，再与编排系统、记忆系统协同实现。

---

## 0. 总结论

洪荒时代的新系统不是在旧 `backend/query` 里继续堆分支，而是把旧查询运行层拆成一套职责清晰的 agent runtime：

```text
UserRequest
  -> UnderstandingCandidateLayer
  -> TaskSystem
  -> OperationSystem
  -> SoulSystem
  -> MemorySystem
  -> OrchestrationSystem
  -> ExecutionRuntime
  -> CommitGate / OutputBoundary
```

一句话分工：

```text
任务系统：要做什么。
理解层：把用户话语拆成候选信号。
操作系统：能碰什么。
灵魂系统：以什么身份和结构呈现给模型。
记忆系统：带什么上下文，产生什么写回候选。
编排系统：怎么做，是否能做，按什么顺序做。
执行层：只按 RuntimeDirective 执行。
写回层：决定什么能落入 session / memory / artifact / final answer。
```

成熟完成态：

```text
当前轮执行真相只能来自：

OrchestrationPlan
  -> ExecutionGraph
  -> RuntimeDirective
  -> OperationGate
  -> Executor
  -> ResultCandidate
  -> CommitGate
```

旧 `query` 层最终应降级为：

```text
请求入口 adapter
事件流 adapter
旧 planner / worker / tool adapter 的过渡容器
```

而不是继续承担系统大脑。

---

## 1. 我们现在已经有了什么

### 1.1 灵魂系统已经形成

已有文档：

```text
docs/系统规划/灵魂系统/01-灵魂系统完整构建方案-20260427.md
docs/系统规划/灵魂系统/02-任务系统与灵魂意志联动方案-20260427.md
docs/系统规划/灵魂系统/03-灵魂系统管理与多态投影方案-20260427.md
docs/系统规划/灵魂系统/04-灵魂系统框架展示与技术报告-20260428.md
```

已有定位：

```text
灵魂系统不是语气包。
灵魂系统是身份、认知姿态、投影和 PromptManifest 管理层。
SoulProjection 只呈现已裁剪的信息，不扩大权限。
PromptManifest 记录模型可见上下文来源。
```

当前已有代码能力：

```text
backend/soul/projection.py
  能从 TaskPromptContract / ResourceRuntimeView / SkillRuntimeView 生成 soul runtime preview。

backend/prompting/manifest.py
  PromptManifest 已从 query 迁出，作为独立 Prompting 边界继续记录模型可见上下文来源。
```

成熟度：

```text
架构清晰。
已能参与任务/资源 preview 链。
仍需和未来 MemorySystem / OrchestrationSystem 的正式 PromptManifest 合并。
```

### 1.2 任务系统已经有 preview 主链

已有文档：

```text
docs/系统规划/操作系统与任务系统/01-任务系统重构实施计划-20260429.md
```

已有代码能力：

```text
backend/tasks/definitions.py
backend/tasks/models.py
backend/tasks/contracts.py
backend/tasks/contract_builder.py
backend/tasks/coordinator.py
```

当前能生成：

```text
TaskContract
TaskDefinition
TaskBinding
SkillRuntimeView
TaskPromptContract
```

当前完成状态：

```text
能把用户请求整理成任务契约。
能选择 task definitions。
能合并 task binding。
能生成 task prompt contract。
能接入 ResourcePolicyPreview 和 SoulRuntimeView。
```

当前限制：

```text
TaskCoordinator 仍保留旧任务生命周期和部分自然语言推断。
TaskSystem 还不能作为真实执行生命周期 owner。
多智能体未来应以 TaskSystem 为管理总入口，但当前只预留接口。
```

### 1.3 操作系统已经有资源边界 preview

已有文档：

```text
docs/系统规划/操作系统与任务系统/02-操作系统重构实施计划-20260429.md
docs/系统规划/操作系统与任务系统/03-任务系统与操作系统接线方案-20260429.md
```

已有代码能力：

```text
backend/operations/registry.py
backend/operations/requirements.py
backend/operations/policies.py
backend/operations/policy_builder.py
backend/operations/runtime_view.py
backend/operations/gate.py
```

当前能生成：

```text
OperationRequirement
ResourcePolicyPreview
ResourceDecision
ResourceRuntimeView
OperationGateResult
```

当前完成状态：

```text
unknown operation -> deny
worker / agent operation -> preview_only
high risk operation -> requires_approval 或 deny
ResourcePolicyPreview.preview_only == true
ResourcePolicyPreview.adopted == false
ResourceRuntimeView.runtime_executable == false
```

当前限制：

```text
ResourcePolicyPreview 还不能升级为 AdoptedResourcePolicy。
OperationGate 还没有成为真实执行前的统一门。
文件、shell、network、memory scope 还需要更完整的执行前复核。
```

### 1.4 任务系统与操作系统接线已打通

当前 preview 链：

```text
UserRequest
  -> TaskContract
  -> TaskDefinition / TaskBinding / SkillRuntimeView
  -> OperationRequirement
  -> ResourcePolicyPreview
  -> ResourceRuntimeView
  -> TaskPromptContract
  -> SoulRuntimeView / PromptManifestPreview
  -> ControlKernel diagnostics
```

已有测试：

```text
backend/tests/task_operation_preview_regression.py
backend/tests/query_runtime_task_operation_preview_regression.py
backend/tests/orchestration_kernel_preview_regression.py
backend/tests/task_operation_preview_trace_regression.py
```

当前验证过：

```text
preview 主链能输出 task_operation_preview。
ControlKernel 能记录 refs。
真实主链 fail-closed。
不会真实执行工具、worker、agent、文件写入或 memory 写回。
```

### 1.5 编排系统已有骨架和设计

已有文档：

```text
docs/系统规划/操作系统与任务系统/04-编排系统重构设计准备-20260429.md
docs/系统规划/操作系统与任务系统/05-编排系统架构设计-20260429.md
```

已有代码能力：

```text
backend/orchestration/contracts.py
backend/orchestration/candidates.py
backend/orchestration/collector.py
backend/orchestration/coordinator.py
backend/orchestration/plan.py
backend/orchestration/validation.py
backend/orchestration/graph_preview.py
backend/orchestration/adoption.py
backend/orchestration/directives.py
backend/orchestration/commit_gate.py
backend/orchestration/execution_graph.py
backend/orchestration/kernel.py
backend/orchestration/topology.py
backend/orchestration/unit_registry.py
```

当前已有对象：

```text
CandidateEnvelope
CandidateSet
ControlKernelPreviewContext
ControlKernelResult
ExecutionGraph
ExecutionNode
CommitCandidate
OrchestrationPlanPreview
PlanValidationResult
ExecutionGraphPreview
AdoptionCandidate
RuntimeDirectiveCandidate
CommitGatePreview
ExecutionTopologyPreview
CoordinationPolicyPreview
AgentSeatPlanPreview
AgentAssignmentCandidate
AgentResultCandidate
```

当前能力：

```text
ControlKernel.collect() 默认 blocked。
ExecutionGraph.nodes 为空。
directives 为空。
topology 固定 single_agent preview。
真实主链已输出 candidate_set_preview / orchestration_plan_preview / plan_validation / execution_graph_preview。
真实主链已输出 adoption_candidate_preview / runtime_directive_candidate_preview / operation_gate_preflight / directive_only_executor_preview / commit_gate_preview。
CommitGatePreview 默认 blocked，所有 CommitCandidate.allowed = false。
multi-agent 只预留接口，不进入当前施工。
```

当前缺口：

```text
AdoptedResourcePolicy 尚未实现。
RuntimeDirective 尚未可消费。
OperationGate preflight 已拒绝 candidate，真实 OperationGate 尚未通过。
Executor 已有 directive-only preview 合同，尚未 dispatch。
真实 CommitGate / OutputBoundary 尚未放行写回。
```

### 1.6 记忆系统与上下文边界正在落地

已有文档：

```text
docs/系统规划/记忆系统/00-记忆系统重构设计准备-20260429.md
docs/系统规划/记忆系统/01-记忆系统与上下文管理架构设计-20260429.md
docs/系统规划/记忆系统/02-Claude-Code源码对照与记忆系统实现细节-20260429.md
```

已有代码能力：

```text
backend/memory_system/contracts.py
backend/memory_system/conversation_memory.py
backend/memory_system/state_memory.py
backend/memory_system/long_term_memory.py
backend/memory_system/runtime_view.py
backend/memory_system/gate.py
backend/memory_system/writeback.py
backend/memory_system/governance.py
backend/memory_system/compaction.py
backend/context_policy/contracts.py
backend/context_policy/package_builder.py
```

当前已形成：

```text
ConversationMemorySnapshot
StateMemorySnapshot
LongTermMemoryRecord
MemoryContextCandidate
StateMemoryRestoreCandidate
MemoryWriteCandidate
MemoryRuntimeView
MemoryGateDecision
MemoryCompactionPreview
MemoryCommitRecord
ContextPolicyResult
```

当前完成状态：

```text
对话记忆、状态记忆、长期记忆已按语义分层。
StateMemory restore 已候选化，restore != decide。
ContextPolicy 已能从 MemoryRuntimeView 生成 preview-only ContextPackage。
query.runtime 的 prompt 组装已优先消费 MemorySystem / ContextPolicy preview。
query.prompt_builder 收到 ContextPackage 时不再回退读取全量 durable index。
post-turn 自动 session memory refresh / durable extraction 已改为 write candidate + blocked MemoryGate。
显式“记住”应答已改为候选审核语义，不再暗示已 durable commit。
旧执行分支的 memory_context event 已改为输出 MemoryRuntimeView / ContextPolicy preview，而不是 durable prefetch + inspect_query_context。
旧 MemoryFacade 直写入口已封存为 legacy_blocked，不再默认写 session summary 或 durable store。
手工 memory API 继续作为 governance 路径，写入 MemoryCommitRecord 形态的治理日志。
```

当前限制：

```text
旧 MemoryFacade 的 commit / refresh API 仍保留为兼容和后续治理入口。
正式 PromptManifest 仍在 query.prompt_manifest，后续要迁入 SoulSystem。
MemoryGovernance / MemoryCommitRecord 尚未落地。
旧 query 中仍残留 memory trace、prefetch、compaction 的 adapter 逻辑，需继续迁出。
```

### 1.7 旧 query 层已收缩为入口 adapter

当前目录：

```text
backend/query/
```

当前只保留：

```text
__init__.py
models.py
runtime.py
```

已迁出或删除：

```text
planner / follow-up / direct tool / runtime context state 已删除。
output / answer / tool output 迁入 backend/output_boundary。
prompt builder / prompt manifest / long-term prompt context 迁入 backend/prompting。
evidence graph / evidence store / materializer 迁入 backend/evidence。
retrieval / pdf / structured workers 迁入 backend/workers。
context runtime models 迁入 backend/context_policy。
```

它的当前定位是：

```text
API 请求入口 adapter。
事件流 adapter。
新主链 RuntimeDirective model lane 的临时装配点。
```

迁移目标：

```text
QueryRuntime 不再拥有跨系统调度权。
QueryPlanner 不再拥有执行决定权。
RuntimeToolBridge 不再自行扩大工具范围。
EvidenceOrchestrator 不再直接由 worker_plan 驱动。
AnswerAssembler / AnswerFinalizer 后续并入 OutputBoundary。
PromptManifest 后续并入 SoulSystem / ContextPolicy。
```

### 1.8 理解层需要归位

旧链路里存在理解层：

```text
QueryUnderstanding
intent analysis
route 判断
modality 判断
tool_name 判断
memory intent 判断
follow-up 判断
```

新架构不取消理解层，但必须把它降级为候选生产层：

```text
UnderstandingCandidateLayer
  -> IntentFrameCandidate
  -> RouteCandidate
  -> TaskFamilyCandidate
  -> CapabilityNeedCandidate
  -> MemoryIntentCandidate
  -> FollowupCandidate
```

当前代码落点：

```text
backend/understanding/candidate_layer.py
  build_understanding_candidates()
```

当前已候选化：

```text
IntentFrameCandidate
RouteCandidate
TaskFamilyCandidate
CapabilityNeedCandidate
MemoryIntentCandidate
```

当前未候选化：

```text
FollowupCandidate 仍待接入 RuntimeFollowupCoordinator / QueryFollowupResolver。
```

归属规则：

```text
任务相关理解进入 TaskSystem。
资源/能力相关理解进入 OperationSystem 的候选输入。
记忆相关理解进入 MemorySystem。
当前轮是否采纳这些理解结果，由 OrchestrationSystem 决定。
```

固定原则：

```text
理解可以建议。
理解不能决定。
理解层不能直接触发工具、worker、agent、memory 写回或 final answer。
```

---

## 2. 离成熟系统还差什么

### 2.1 缺真正的编排控制面

现在已有 ControlKernel 骨架，但还缺完整控制平面：

```text
CandidateCollector
OrchestrationCoordinator
OrchestrationPlanPreview
PlanValidator
ExecutionGraphPreviewBuilder
RuntimeDirectiveBuilder
AdoptionManager
```

成熟标准：

```text
所有候选都先进入 CandidateSet。
只有 OrchestrationCoordinator 能采纳候选。
只有 PlanValidator 通过后才能进入 adoption。
只有 RuntimeDirective 才能进入执行层。
```

### 2.2 缺资源策略采纳机制

现在只有：

```text
ResourcePolicyPreview
```

成熟系统还需要：

```text
AdoptedResourcePolicy
ResourcePolicySnapshot
OperationGate final check
approval token / approval record
policy hash / descriptor hash
execution-time revalidation
```

成熟标准：

```text
preview policy 只能给模型看。
adopted policy 才能进入 ExecutionGraph。
执行前 OperationGate 必须重新校验路径、网络、shell、memory、agent/worker ownership。
```

### 2.3 缺 RuntimeDirective 和执行层

现在：

```text
真实主链 fail-closed。
没有可消费 RuntimeDirective。
旧执行器仍在 query 层。
```

成熟系统需要：

```text
RuntimeDirective
ModelExecutor
ToolExecutor
WorkerExecutor
BoundedAgentExecutor
ExecutorResultEnvelope
ResultCandidate
```

成熟标准：

```text
执行层只消费 RuntimeDirective。
执行层不读 QueryExecutionPlan 决策字段。
执行层不自行决定权限。
执行层不直接写 final answer。
```

### 2.4 缺 CommitGate 和 OutputBoundary

现在仍有旧写回路径残留：

```text
session_manager.append_messages
TaskCoordinator._persist_result_ref
runtime_persistence
answer_assembler / answer_finalizer
memory extraction scheduling
```

成熟系统需要：

```text
CommitCandidate
CommitGate
OutputBoundary
AnswerPolicy
MemoryWriteCandidate
ArtifactCommitCandidate
SessionMessageCommitCandidate
```

成熟标准：

```text
工具、worker、agent、model 的输出都先变成 ResultCandidate。
最终答案由 OutputBoundary 生成。
写回由 CommitGate 统一放行。
durable memory 写入必须是候选，不是副作用默认动作。
```

### 2.5 缺记忆系统重构

当前记忆能力仍散在：

```text
memory_facade
runtime_context_state
session_memory_projection
persistent memory block
durable memory extraction
```

成熟系统需要：

```text
ConversationMemory
StateMemory
LongTermMemory
MemoryContextCandidate(memory_layer)
MemoryPolicy
MemoryRuntimeView
MemoryWriteCandidate
MemoryGate
MemoryCommitRecord
```

成熟标准：

```text
记忆系统按对话记忆、状态记忆、长期记忆分层。
状态记忆与 ContextPolicy 高度协调，负责 active bindings / context slots / flow state / task state 的恢复候选。
对话记忆服务 recent dialogue / compact summary。
长期记忆服务跨会话稳定事实与按需召回。
restore != decide。
memory read 只是上下文候选。
memory write 只是写回候选。
子任务 / 未来子 agent 默认隔离 memory scope。
对话记忆、状态记忆、长期记忆有不同写回门。
```

### 2.6 缺统一生命周期与 trace

当前已有 trace 和部分 task records，但还不成熟。

成熟系统需要：

```text
TurnTrace
CandidateTrace
PlanTrace
ExecutionGraphTrace
DirectiveTrace
OperationGateTrace
CommitTrace
orchestration_diff
```

成熟标准：

```text
能解释每一轮为什么选择这个计划。
能解释为什么 blocked。
能解释哪个候选被采纳或丢弃。
能对比 plan 和 actual execution。
能追踪 artifact / memory / session writeback 来源。
```

### 2.7 缺 API / UI 层的 preview 管理

成熟系统还需要给前端或调试台暴露：

```text
TaskOperationPreview
ResourcePolicyPreview
OrchestrationPlanPreview
PlanValidationResult
ExecutionGraphPreview
CommitCandidate preview
Trace graph
```

成熟标准：

```text
用户或开发者能看见当前系统为什么不能执行。
高风险操作能展示 requires_approval。
执行图、候选、资源边界、写回候选都可检查。
```

### 2.8 缺测试体系重构

现有测试足够保住当前 preview，但还缺成熟系统测试：

```text
contract tests
policy tests
validator tests
execution graph tests
directive tests
operation gate tests
commit gate tests
end-to-end preview snapshots
plan-vs-actual regression tests
```

成熟标准：

```text
不是只测最终答案。
必须测控制平面产物。
必须测 fail-closed。
必须测旧链路不能复活。
必须测 preview 不会变成 runtime_executable。
```

### 2.9 缺理解层候选化重构

当前旧理解链仍可能通过旧 planner / runtime 字段影响执行：

```text
query_understanding.route
query_understanding.modality
query_understanding.tool_name
memory_intent
followup_resolution
```

成熟系统需要：

```text
UnderstandingCandidate
IntentFrameCandidate
RouteCandidate
TaskFamilyCandidate
CapabilityNeedCandidate
MemoryIntentCandidate
FollowupCandidate
```

成熟标准：

```text
理解层输出只能进入 CandidateSet。
理解层不能直接生成 ExecutionGraph。
理解层不能直接生成 RuntimeDirective。
理解层不能直接选择 ToolExecutor / WorkerExecutor。
```

---

## 3. 正式总架构

### 3.1 总链路

```text
UserRequest
  -> QueryAdapter
  -> UnderstandingCandidateLayer
      IntentFrameCandidate
      TaskFamilyCandidate
      CapabilityNeedCandidate
      MemoryIntentCandidate
      FollowupCandidate
  -> TaskSystem
      TaskContract
      TaskDefinition
      TaskBinding
      TaskPromptContract
  -> OperationSystem
      OperationRequirement
      ResourcePolicyPreview
      ResourceRuntimeView
  -> SoulSystem
      SoulRuntimeView
      PromptManifestPreview
  -> MemorySystem
      MemoryContextCandidate
      MemoryPolicy
  -> OrchestrationSystem
      CandidateSet
      OrchestrationPlanPreview
      PlanValidationResult
      ExecutionGraphPreview
      RuntimeDirectiveCandidate
      ControlKernelResult
  -> ExecutionRuntime
      RuntimeDirective
      ExecutorResultEnvelope
  -> CommitGate / OutputBoundary
      ResultCandidate
      CommitCandidate
      FinalAnswer
      MemoryWriteCandidate
      ArtifactRef
```

### 3.2 第一阶段实际主链

当前只做：

```text
UserRequest
  -> QueryRuntime adapter
  -> build_task_runtime_contract_preview()
  -> TaskOperationPreview
  -> ControlKernel
  -> blocked / preview_only
```

接下来补齐：

```text
TaskOperationPreview
  -> CandidateCollector
  -> OrchestrationPlanPreview(single_agent)
  -> PlanValidationResult
  -> ExecutionGraphPreview
  -> ControlKernel
  -> blocked / preview_only
```

### 3.3 成熟执行主链

后续完成态：

```text
OrchestrationPlanPreview
  -> PlanValidator
  -> AdoptionCandidate
  -> OrchestrationPlan
  -> AdoptedResourcePolicy
  -> ExecutionGraph
  -> RuntimeDirective
  -> OperationGate
  -> Executor
  -> ResultCandidate
  -> CommitCandidate
  -> CommitGate
  -> OutputBoundary
```

---

## 4. 系统职责总表

| 系统 | 拥有的真相 | 产物 | 不能做 |
| --- | --- | --- | --- |
| QueryAdapter | 请求入口和事件流 | request event / response event | 不再调度工具、worker、agent |
| UnderstandingCandidateLayer | 用户话语候选信号 | IntentFrameCandidate / RouteCandidate / MemoryIntentCandidate | 不决定任务真相，不决定执行 |
| TaskSystem | 任务事实 | TaskContract / TaskPromptContract / TaskRecord | 不授予资源权限，不直接执行 |
| OperationSystem | 资源边界事实 | OperationRequirement / ResourcePolicy / ResourceRuntimeView / OperationGate | 不生成最终答案，不写回 |
| SoulSystem | 模型可见投影事实 | SoulRuntimeView / PromptManifest | 不扩大权限，不决定执行 |
| MemorySystem | 记忆上下文与写回候选事实 | MemoryContextCandidate / MemoryPolicy / MemoryWriteCandidate | 不覆盖当前任务，不直接写 durable memory |
| OrchestrationSystem | 当前轮控制事实 | CandidateSet / OrchestrationPlan / ExecutionGraph / RuntimeDirective | 不直接执行，不直接写回 |
| ExecutionRuntime | 实际执行结果事实 | ExecutorResultEnvelope / ResultCandidate | 不决定权限，不决定最终答案 |
| CommitGate | 写回事实 | CommitRecord / denied reason | 不重新规划任务 |
| OutputBoundary | 用户可见答案事实 | FinalAnswer / answer metadata | 不绕过 CommitGate |

---

## 5. 旧 query 层迁移原则

### 5.1 query 当前是什么

```text
backend/query 已不再是系统大脑。
它不是新架构里的正式系统。
它只保留入口 adapter 职责。
```

### 5.2 query 未来保留什么

```text
QueryRuntime:
  请求入口 adapter。
  事件流 adapter。
  新系统 preview / execution events 的组装处。

旧 planner / direct tools / follow-up:
  已从 query 生产链路删除。

workers / evidence:
  已迁入 backend/workers 与 backend/evidence，未来只能通过 RuntimeDirective + OperationGate 接入。
```

### 5.3 query 需要迁出的职责

```text
planner decision -> OrchestrationSystem
query understanding -> UnderstandingCandidateLayer
tool route -> RuntimeDirective + ToolExecutor
worker route -> RuntimeDirective + WorkerExecutor
prompt manifest -> SoulSystem / ContextPolicy
answer assembly -> OutputBoundary
memory context state -> MemorySystem
persistence -> CommitGate
```

---

## 6. 成熟度评估

| 领域 | 当前状态 | 成熟度 | 主要缺口 |
| --- | --- | --- | --- |
| 灵魂系统 | 架构基本成型，能参与 preview | 中高 | 与正式 PromptManifest / MemorySystem 统一 |
| 任务系统 | preview contract 已可用 | 中 | 生命周期、TaskRecord、真实执行阶段接管 |
| 操作系统 | ResourcePolicyPreview 已可用 | 中 | AdoptedResourcePolicy、OperationGate 执行前复核 |
| 理解层 | 前五类理解候选已接入 CandidateSet | 初中 | FollowupCandidate、与 MemorySystem 正式合流 |
| 编排系统 | single_agent preview 控制面与执行前置合同已收口 | 中 | 真实 Adoption、真实 OperationGate pass、只读 executor dispatch |
| 记忆系统 | 三层记忆、ContextPolicy、写回候选、blocked MemoryGate、Governance 记录已落地 | 中 | PromptManifest 正式迁移、记忆治理 UI 与 CommitGate 统一 |
| 执行层 | 旧 query runtime 内仍能执行 | 初 | Executor 分层、Directive-only 执行 |
| 写回层 | 旧 persistence 可用 | 初 | CommitGate / OutputBoundary 统一 |
| 测试体系 | preview 回归已有 | 初中 | 控制平面、写回门、plan-vs-actual 测试 |
| API / UI | 部分接口存在 | 初 | preview 调试面板、审批、trace graph |

---

## 7. 重构路线图

### Phase 0：当前已完成

```text
灵魂系统设计完成。
任务系统 preview 主链完成。
操作系统 ResourcePolicyPreview 完成。
任务系统与操作系统接线完成。
ControlKernel fail-closed 接入完成。
single_agent topology preview 接口预留完成。
```

验收：

```text
task_operation_preview 可输出。
resource_policy preview_only。
control_kernel blocked。
不真实执行。
```

### Phase 1：编排系统 preview 控制面

目标：

```text
CandidateCollector
OrchestrationPlanPreview
PlanValidationResult
ExecutionGraphPreview
AdoptionCandidate
AdoptionBlock
RuntimeDirectiveCandidate
RuntimeDirectiveBuildBlock
CommitGatePreview
```

完成标准：

```text
真实主链输出 candidate_set_preview。
真实主链输出 orchestration_plan_preview。
真实主链输出 plan_validation。
真实主链输出 execution_graph_preview。
真实主链输出 adoption_candidate_preview。
真实主链输出 adoption_block。
真实主链输出 runtime_directive_candidate_preview。
真实主链输出 runtime_directive_block。
真实主链输出 commit_gate_preview。
QueryRuntime.astream 不再保留 return 后的旧执行事件处理分支。
仍 fail-closed。
```

### Phase 1B：理解层候选化

目标：

```text
UnderstandingCandidateLayer
IntentFrameCandidate
RouteCandidate
TaskFamilyCandidate
CapabilityNeedCandidate
MemoryIntentCandidate
FollowupCandidate
```

完成标准：

```text
旧 QueryUnderstanding 字段不再直接进入执行分支。
理解结果进入 CandidateSet。
TaskSystem / MemorySystem / OperationSystem 消费结构化候选。
OrchestrationSystem 统一采纳。
当前已完成前五类候选接入，FollowupCandidate 后续单独接。
```

### Phase 2：Adoption 与 RuntimeDirective 合同

目标：

```text
AdoptionCandidate
AdoptedResourcePolicy
RuntimeDirectiveCandidate
RuntimeDirective
AdoptionBlock
RuntimeDirectiveBuildBlock
```

完成标准：

```text
preview 与 adopted 严格分离。
RuntimeDirectiveCandidate 不能被 executor 消费。
RuntimeDirective 存在但先不开放真实执行。
AdoptionBlock / RuntimeDirectiveBuildBlock 解释为什么当前不可采纳、不可生成指令。
```

### Phase 2 收口：编排系统阶段冻结

状态：

```text
single_agent preview 控制面已收口。
Adoption / RuntimeDirective 合同已定义。
OperationGate / directive-only executor 前置合同已定义。
真实执行面暂停。
下一阶段转入 MemorySystem 重构。
```

收口文档：

```text
docs/系统规划/操作系统与任务系统/06-编排系统阶段收口-20260429.md
```

### Phase 3：只读执行试点

目标：

```text
ReadOnly ModelExecutor / ToolExecutor
OperationGate final check
ResultCandidate
CommitCandidate denied by default
```

完成标准：

```text
只读操作可以经 RuntimeDirective 执行。
写操作仍 blocked / requires_approval。
结果不直接写回。
```

### Phase 4：CommitGate / OutputBoundary

目标：

```text
FinalAnswer
SessionMessageCommitCandidate
ArtifactCommitCandidate
MemoryWriteCandidate
CommitGate
```

完成标准：

```text
所有写回统一走 CommitGate。
AnswerAssembler / AnswerFinalizer 迁到 OutputBoundary。
durable memory 写回候选化。
```

### Phase 5：记忆系统重构

当前施工文档：

```text
docs/系统规划/记忆系统/00-记忆系统重构设计准备-20260429.md
docs/系统规划/记忆系统/01-记忆系统与上下文管理架构设计-20260429.md
docs/系统规划/记忆系统/02-Claude-Code源码对照与记忆系统实现细节-20260429.md
```

目标：

```text
ConversationMemory
StateMemory
LongTermMemory
ContextPolicy
MemoryRuntimeView
MemoryGate
MemoryWritebackPreviewService
MemoryGovernance
MemoryCommitRecord
```

已落地：

```text
ConversationMemory / StateMemory / LongTermMemory 只读适配。
MemoryRuntimeView 三层候选汇总。
ContextPolicy preview-only 上下文裁剪。
MemoryGateDecision blocked 写回封门。
MemoryWritebackPreviewService 从 QueryRuntime 迁出记忆写回预览逻辑。
MemoryGovernance 记录手工治理提交与 legacy_blocked 调用。
MemoryCompactionPreview 替代旧 runtime compactor 直连。
```

完成标准：

```text
三层记忆边界清晰。
状态记忆与上下文管理接线清晰。
记忆读写都有边界。
restore 不再等于 decide。
session memory 与 durable memory 写回分开。
旧 QueryRuntime / MemoryFacade 不再默认触发记忆写副作用。
```

### Phase 6：多智能体架构专题

前置条件：

```text
single_agent 主链成熟。
TaskSystem 生命周期成熟。
MemorySystem 隔离成熟。
OrchestrationSystem directive 执行成熟。
```

目标：

```text
TaskSystem 作为多智能体管理总入口。
MultiAgentTaskContract。
AgentSeat lifecycle。
sub-agent memory scope。
multi-agent result merge。
```

当前不进入施工。

---

## 8. 成熟系统验收标准

### 8.1 控制平面验收

```text
所有候选都有 CandidateEnvelope。
所有决策都有 OrchestrationPlan。
所有执行节点都有 ExecutionGraph。
所有执行动作都有 RuntimeDirective。
所有资源授权都有 AdoptedResourcePolicy。
所有执行前都有 OperationGate。
所有写回都有 CommitGate。
```

### 8.2 防回退验收

```text
QueryPlanner 不能直接决定执行。
UnderstandingCandidate 不能直接决定执行。
QueryRuntime 不能根据 execution_kind 直接调度。
RuntimeToolBridge 不能自己扩大 allowed tools。
EvidenceOrchestrator 不能由 worker_plan 直接进入。
TaskCoordinator 不能从自然语言猜绑定后直接写结果。
SoulProjection 不能声明工具权限。
Memory restore 不能覆盖当前任务。
WorkerResult / AgentResult 不能直接成为 final answer。
```

### 8.3 安全验收

```text
unknown tool / worker / agent blocked。
missing policy blocked。
preview policy 不可执行。
requires_approval 不可静默 allow。
headless 无审批通道时 fail-closed。
filesystem / shell / network / memory 执行前重校验。
CommitCandidate 默认 denied。
```

### 8.4 可观测性验收

```text
能看到 candidate_set。
能看到 orchestration_plan。
能看到 plan_validation。
能看到 execution_graph。
能看到 runtime_directive。
能看到 operation_gate decision。
能看到 commit_candidate。
能看到 final answer 来源。
能做 plan-vs-actual diff。
```

---

## 9. 后续文档关系

本文件是总框架。

子系统文档：

```text
灵魂系统：
  docs/系统规划/灵魂系统/

任务系统 / 操作系统：
  docs/系统规划/操作系统与任务系统/00-03

编排系统：
  docs/系统规划/操作系统与任务系统/04-06

记忆系统：
  docs/系统规划/记忆系统/00-记忆系统重构设计准备-20260429.md

执行层 / CommitGate / OutputBoundary：
  后续新建独立文档或归入 编排系统 后续阶段。
```

旧架构参考：

```text
docs/02-先进调度架构对齐与洪荒时代编排重写方案-20260427.md
```

后续所有新设计都应先检查是否违反本文件的总原则。

---

## 10. 最终口径

```text
洪荒时代不是一个更大的 query runtime。
洪荒时代是一套分层 agent runtime。

TaskSystem 定义任务。
UnderstandingCandidateLayer 只提供候选信号。
OperationSystem 定义边界。
SoulSystem 定义呈现。
MemorySystem 定义上下文与记忆候选。
OrchestrationSystem 定义执行真相。
ExecutionRuntime 执行指令。
CommitGate 管写回。
OutputBoundary 管最终答案。

旧 query 层逐步退化为 adapter。
```

当前最短行动口径：

```text
single_agent 编排 preview 主链与执行前置合同已收口。
MemorySystem 和上下文边界第一阶段已收口。
再做 directive-only 只读执行试点。
再做 CommitGate / OutputBoundary 真实写回。
最后讨论多智能体拓扑扩展。
```

MemorySystem 当前落地口径：

```text
ConversationMemory / StateMemory / LongTermMemory 已拆为独立候选来源。
MemoryRuntimeView 是记忆系统对编排系统的统一读接口。
ContextPackagePreview 是上下文管理对 PromptBuilder 的唯一主链输入。
preview_memory_context_compaction 是真实链路的压缩预览入口。
MemoryWriteCandidate 只能进入 MemoryGateDecision(blocked)。
旧 MemoryContextLayer 已隔离，不再允许成为运行时主链。
旧 refresh/commit/submit 写回入口只记录 legacy_blocked。
```

真实主链装配当前口径：

```text
QueryRuntime 当前只作为 API/流式事件 adapter。
AgentRuntimeChainPreview 成为单 agent 主链装配对象。
candidate_set_preview 已接入 memory_runtime_view 与 context_policy_preview。
旧 _execution_events 只产出 AgentRuntimeChainPreview + fail-closed 事件。
旧 _stream_single_execution / _stream_bundle_execution / _stream_planned_execution / _stream_direct_tool_execution
均已改为 fail-closed，不再进入 QueryPlanner / worker / direct tool 执行。
旧 QueryPlanner 执行入口 _planner_build_plan 已退役，直接拒绝调用。
真实执行只允许 RuntimeDirective + OperationGate 入口接管。
当前唯一可执行 lane 是 op.model_response：
  inbound user message -> RuntimeCommitGateDecision(allowed, user-only)
  RuntimeDirective(executor_type=model)
  adopted ResourcePolicy(model_only)
  OperationGate allow
  model invoke
  AssistantOutputBoundary 生成 canonical answer
  Runtime CommitGate 生成 session_message / task_result commit candidates
  CommitGate 仍 blocked，不做 assistant session / memory / artifact 写回。
工具、worker、文件写入、shell、记忆写入仍不得绕过 OperationGate。
旧 QueryRuntime assistant append / output commit plan 已关闭。
QueryRuntime 不再直接 save_message；用户输入只能通过 user-only RuntimeCommitGateDecision 写入 session。
```
