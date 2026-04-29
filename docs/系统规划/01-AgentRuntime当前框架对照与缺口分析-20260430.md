# AgentRuntime 当前框架对照与缺口分析

日期：2026-04-30  
定位：本文件用于对照 `docs/02-先进调度架构对齐与洪荒时代编排重写方案-20260427.md`，盘点当前代码和总框架已经完成什么、仍缺什么，以及下一阶段应按什么顺序继续重构。

---

## 0. 当前结论

当前系统已经从“旧 query 大脑”进入“分层 AgentRuntime”阶段。

已经成立的事实：

```text
QueryRuntime 不再是规划器。
QueryRuntime 不再执行旧 planner / direct tool / worker / follow-up 链。
backend/query 源码只剩 API adapter、事件 adapter、请求模型。
任务系统、操作系统、编排系统、记忆系统、上下文策略、输出边界已经分包。
当前真实可执行链只有 op.model_response。
工具、worker、agent、memory write、assistant session write 仍未放行。
```

但还不能说成熟系统已经完成。

当前系统的成熟度判断：

```text
框架边界：基本正确。
旧 query 清理：生产源码层面基本完成。
单 agent 主链：已贯通到 model-only runtime lane。
真实工具/worker执行：未完成。
正式 Adoption：未完成。
正式 CommitGate 写回：未完成。
TaskCoordinator 生命周期接管：未完成。
测试体系：待重建。
```

一句话：

```text
我们已经把大脑从 query 里拆出来了，但还没有把所有真实执行能力重新、安全地装回新大脑。
```

---

## 1. 当前真实框架快照

### 1.1 当前生产主链

当前 `backend/query/runtime.py` 的主链是：

```text
QueryRuntime.astream
  -> input user message RuntimeCommitGateDecision
  -> AgentRuntimeChainAssembler.build_live_preview
      -> MemoryRuntimeView
      -> ContextPolicyPreview
      -> TaskOperationPreview
      -> AgentRuntimeChainPreview
  -> ModelResponseRuntimeExecutor.stream
      -> RuntimeDirective(executor_type=model)
      -> adopted ResourcePolicy(model_only)
      -> OperationGate.check(op.model_response)
      -> model_runtime.invoke_messages
      -> AssistantOutputBoundary
      -> Runtime CommitGate blocked
      -> done(commit_gate_blocked)
```

这说明当前链路已经符合：

```text
入口 adapter 与执行器分离。
模型回答也必须有 RuntimeDirective。
模型回答也必须经过 OperationGate。
模型输出先进入 OutputBoundary。
assistant 写回仍被 CommitGate 阻断。
```

关键文件：

```text
backend/query/runtime.py
backend/runtime/agent_chain.py
backend/execution/model_response.py
backend/orchestration/runtime_directive.py
backend/orchestration/commit_gate.py
backend/operations/gate.py
backend/output_boundary/boundary.py
```

### 1.2 当前 query 目录状态

当前源码目录只保留：

```text
backend/query/__init__.py
backend/query/models.py
backend/query/runtime.py
```

已迁出能力：

```text
output / answer / tool output -> backend/output_boundary
prompt builder / prompt manifest -> backend/prompting
evidence graph / store / materializer -> backend/evidence
retrieval / pdf / structured worker -> backend/workers
context runtime models -> backend/context_policy
structured binding model -> backend/tasks
model response executor -> backend/execution
runtime chain assembler -> backend/runtime
```

注意：

```text
backend/query/__pycache__ 中仍可能残留旧模块 .pyc。
这只是编译缓存，不代表旧源码仍在生产链路。
后续可以作为工程清理删除，但不影响架构判断。
```

### 1.3 当前系统分工

| 系统 | 当前代码落点 | 当前职责 | 成熟度 |
| --- | --- | --- | --- |
| QueryAdapter | `backend/query/runtime.py` | API 输入、事件输出、调用新主链 | 中高 |
| RuntimeChain | `backend/runtime/agent_chain.py` | 组装记忆、上下文、任务操作 preview | 中 |
| TaskSystem | `backend/tasks/*` | 任务契约、任务绑定、任务 prompt contract | 中 |
| OperationSystem | `backend/operations/*` | 操作注册、ResourcePolicy、OperationGate | 中 |
| OrchestrationSystem | `backend/orchestration/*` | 候选、计划、图、directive、commit preview 合同 | 中 |
| ExecutionRuntime | `backend/execution/model_response.py` | 当前 model-only directive 执行 | 初中 |
| MemorySystem | `backend/memory_system/*` | 三层记忆、运行视图、写回候选、MemoryGate blocked | 中 |
| ContextPolicy | `backend/context_policy/*` | ContextPackage preview 裁剪 | 中 |
| OutputBoundary | `backend/output_boundary/*` | 模型输出规范化和可见答案边界 | 中 |
| Workers/Evidence | `backend/workers/*`, `backend/evidence/*` | 已分包，等待 directive 接入 | 初中 |

---

## 2. 对照先进架构原则

### 2.1 Control Plane / Execution Plane 分离

先进原则：

```text
Control Plane 负责决定怎么做。
Execution Plane 只按 directive 执行。
```

当前状态：

```text
基本符合。
```

已经做到：

```text
QueryRuntime 不再有旧 planner 执行权。
ControlKernel / Orchestration preview 负责 candidate、plan、graph、directive candidate、commit preview。
ModelResponseRuntimeExecutor 只执行 RuntimeDirective model lane。
OperationGate 在执行前检查 op.model_response。
```

仍缺：

```text
Orchestration preview 到正式 OrchestrationPlan 的 adoption 尚未完成。
ExecutionGraph 还没有成为真实执行拓扑。
tool / worker / agent executor 还没有接 RuntimeDirective。
```

判断：

```text
原则方向正确，但执行面只恢复了模型回答这一条最窄 lane。
```

### 2.2 Candidate 不等于 Decision

先进原则：

```text
理解、恢复、记忆、能力、follow-up 都只能产候选。
只有 OrchestrationCoordinator 能采纳。
```

当前状态：

```text
大体符合，但 follow-up 和 TaskCoordinator 仍有旧痕迹。
```

已经做到：

```text
TaskOperationPreview 产出 candidate_set_preview。
RuntimeDirectiveCandidate 明确 candidate_only / preview_only / runtime_executable=false。
AdoptionCandidate 明确 blocked。
CommitGatePreview 明确 blocked。
MemoryWriteCandidate 仍由 MemoryGate blocked。
```

仍缺：

```text
FollowupCandidate 尚未作为正式候选入口完全接入。
TaskCoordinator 内部仍有从 query 字符串推断 pdf/dataset/top_n/page 的旧逻辑。
旧 TaskCoordinator.run_query_tasks / run_tool_task 仍可作为直接执行任务生命周期入口。
```

判断：

```text
候选原则已经进主链，但任务生命周期层还没完全候选化、合同化。
```

### 2.3 Typed Contract 优先于 Prompt 暗示

先进原则：

```text
Prompt 不能授权执行。
可执行资源必须来自 typed contract / manifest / policy。
```

当前状态：

```text
部分符合。
```

已经做到：

```text
ResourcePolicy / ResourceDecision / OperationRequirement 已存在。
OperationGate 不接受缺 directive_ref、缺 resource_policy、preview-only policy。
RuntimeDirective 必须带 adopted_resource_policy_ref。
OutputBoundary 用结构化 OutputResponse 管最终答案。
MemorySystem 用 MemoryRuntimeView / MemoryWriteCandidate，不直接写 durable memory。
```

仍缺：

```text
ResourcePolicy 现在主要来自 operations registry 和 preview builder，尚未完全从 CapabilityManifest / ToolContract / WorkerContract 汇总。
model-only lane 中 ResourcePolicy 是 executor 内部构造的临时 adopted policy。
正式 AdoptedResourcePolicy 类已定义，但还没有成为主链 ResourcePolicy adoption 结果。
PromptManifest 仍在 prompting 边界，尚未和 SoulSystem / ContextPolicy 完全统一为正式模型可见事实源。
```

判断：

```text
typed contract 骨架已经有，但资源事实源还不够集中。
```

### 2.4 Fail-Closed 默认行为

先进原则：

```text
缺 plan、缺 directive、未知资源、缺 policy、权限不足都必须 fail-closed。
```

当前状态：

```text
符合。
```

已经做到：

```text
旧 query execution_events 链直接 fail-closed。
旧 refresh_session_memory / durable extraction 返回 blocked 或 0。
OperationGate 对 unknown operation / missing directive_ref / missing policy / preview-only policy 均 deny。
CommitGatePreview 默认 blocked。
MemoryGateDecision 通过 __post_init__ 强制 blocked。
```

仍缺：

```text
未来放开 tool / worker / file / shell / network 时，需要继续保持 fail-closed。
审批链没有完成，requires_approval 目前不能转为 allow。
```

判断：

```text
当前阶段的安全姿态是对的，后续风险在“重新放权”阶段。
```

### 2.5 ResourcePolicy 不能来自 prompt 推断

先进原则：

```text
ResourcePolicy 必须从 capability / operation manifests 导出。
```

当前状态：

```text
部分符合。
```

已经做到：

```text
operations registry 作为操作定义来源。
ResourcePolicy 有 allowed / denied / requires_approval / preview_only 结构。
OperationGate 只看 ResourcePolicy 和 operation registry。
```

仍缺：

```text
CapabilityManifest、SkillContract、ToolContract、WorkerContract 与 ResourcePolicy 的统一导出链还没闭环。
worker/tool 的 ownership、risk、read_only/destructive/open_world 没有全部进入运行时 OperationGate。
ResourcePolicySnapshot / policy hash / descriptor hash 未完成。
```

判断：

```text
操作系统骨架正确，但还没成为全资源的单一授权事实源。
```

### 2.6 ExecutionGraph / RuntimeDirective 是执行真相

先进原则：

```text
只有 ExecutionGraph / RuntimeDirective 可以进入执行。
旧 planner 字段不能决定执行。
```

当前状态：

```text
方向符合，但成熟度不足。
```

已经做到：

```text
RuntimeDirective 类已定义，禁止引用 preview plan / stage。
ModelResponseRuntimeExecutor 已消费 RuntimeDirective。
QueryRuntime 不再根据 execution_kind 分支执行旧 worker/direct tool。
```

仍缺：

```text
ExecutionGraph 当前仍是 preview。
RuntimeDirective 当前只有 model lane 被构造和消费。
tool / worker / agent RuntimeDirective 尚未实现。
RuntimeDirective 当前由 model executor 根据 preview 自建，后续应由 Orchestration adoption 产出。
```

判断：

```text
已经从“旧 planner 执行”跨到“directive-only model lane”，但还没到完整 directive runtime。
```

### 2.7 OutputCommitGate 是唯一写回门

先进原则：

```text
所有 session / memory / artifact / task result 写回必须统一经过 CommitGate。
```

当前状态：

```text
部分符合。
```

已经做到：

```text
assistant 输出只生成 CommitCandidate，CommitGatePreview blocked。
memory write 只生成候选，MemoryGate blocked。
durable extraction 和 session refresh 旧入口 blocked。
用户输入写入 session 通过 RuntimeCommitGateDecision 明确标记 inbound_user_message_only。
```

仍缺：

```text
用户输入写入当前仍由 QueryRuntime._commit_user_message 调用 session_manager.append_messages，这是有 gate decision 的例外通道，但不是完全抽象后的 CommitApplier。
assistant session write 尚未放行。
task_result / artifact / title commit 尚未放行。
MemoryGate 与 Runtime CommitGate 尚未合并成完整治理闭环。
OutputCommitPlan 类和正式 CommitApplier 尚未完成。
```

判断：

```text
写回已经被封门，但还没有成熟的“可审批、可落盘”的写回系统。
```

### 2.8 QueryRuntime 无跨系统调度权

先进原则：

```text
QueryRuntime 只能作为 adapter，不能继续当系统大脑。
```

当前状态：

```text
基本符合。
```

已经做到：

```text
QueryRuntime docstring 明确 adapter-only。
legacy_runtime_components 标记 query_planner / runtime_tool_bridge / runtime_followup / evidence_orchestrator / worker_direct_execution removed。
_execution_events 只输出 preview + fail-closed。
astream 只装配 preview 并调用 model-only executor。
```

仍缺：

```text
QueryRuntime 仍承担事件格式化、preview ref payload、input commit adapter、system prompt builder adapter。
这些不是旧大脑问题，但后续可以继续迁到 API event adapter / PromptRuntime / CommitApplier。
```

判断：

```text
架构风险已经大幅下降，剩下是边界细化，不是旧 query 复活。
```

### 2.9 TaskCoordinator 不能从自然语言猜绑定

先进原则：

```text
TaskCoordinator 应消费 TaskContract / ExecutionNode，不能从 raw query 推断 binding 后直接执行。
```

当前状态：

```text
未完全符合。
```

当前问题：

```text
backend/tasks/coordinator.py 仍有 _derive_task_bindings(query)。
backend/tasks/coordinator.py 仍有 _derive_task_constraints(query)。
backend/tasks/coordinator.py 仍有 run_query_tasks / run_tool_task 旧执行生命周期。
backend/tasks/coordinator.py 仍有 _persist_result_ref 直接写 task result 文件。
```

这不是当前主链直接执行风险，因为旧 query worker/direct tool 已移除，但它是后续恢复工具/worker执行前必须处理的风险。

判断：

```text
TaskCoordinator 是下一阶段最重要的旧核心之一。
必须把它改成 TaskRecord / TaskResultRef 的 CommitCandidate 生产者，而不是执行与写回 owner。
```

### 2.10 MemoryFacade 不能覆盖当前轮目标

先进原则：

```text
memory restore 只能是候选，不能决定当前轮任务。
```

当前状态：

```text
基本符合。
```

已经做到：

```text
MemoryRuntimeView 汇总 conversation / state / long_term。
ContextPolicyPreview 负责上下文裁剪。
MemoryGateDecision 强制 blocked。
旧 durable extraction 和 session refresh 不落盘。
MemoryWriteCandidate 不直接写 durable store。
```

仍缺：

```text
MemoryGovernance / MemoryCommitRecord 与 Runtime CommitGate 还没完全接线。
记忆整理子 agent / 后台 summarizer 尚未接入。
多 agent memory scope 还只是未来设计。
```

判断：

```text
记忆系统第一阶段已经正确，后续重点是治理和真实 commit。
```

---

## 3. 当前仍缺的东西

### 3.1 正式 Adoption 管线

现在有：

```text
AdoptionCandidate(blocked)
AdoptionBlock(preview_only)
AdoptedResourcePolicy class
```

还缺：

```text
OrchestrationPlanPreview -> OrchestrationPlan
ResourcePolicyPreview -> AdoptedResourcePolicy
PlanValidationResult -> adoption decision
policy snapshot / hash / descriptor refs
adoption trace
```

为什么重要：

```text
没有正式 adoption，就只能让 model-only executor 临时构造 runtime policy。
这可以作为过渡，但不能成为成熟系统。
```

### 3.2 ExecutionGraph 真实化

现在有：

```text
ExecutionGraphPreview
RuntimeDirectiveCandidate
RuntimeDirective(model-only)
```

还缺：

```text
ExecutionGraph(runtime)
ExecutionNode -> RuntimeDirective builder
graph node status
plan-vs-actual diff
retry/fallback policy
```

为什么重要：

```text
tool / worker / agent 执行不能靠 QueryRuntime 分支。
它们必须从 ExecutionGraph 节点生成 directive。
```

### 3.3 ToolExecutor / WorkerExecutor / BoundedAgentExecutor

现在有：

```text
ModelResponseRuntimeExecutor
workers 包已经迁出
evidence 包已经迁出
```

还缺：

```text
ToolExecutor
WorkerExecutor
BoundedAgentExecutor
ExecutorResultEnvelope
WorkerArtifactRef
ToolOutputContract runtime validation
```

为什么重要：

```text
当前系统能自然对话，但不能按新架构真实调用工具/worker。
下一步放权必须先做只读 executor。
```

### 3.4 CommitGate 真实写回系统

现在有：

```text
CommitGatePreview
RuntimeCommitGateDecision
blocked runtime commit candidates
AssistantOutputBoundary
```

还缺：

```text
OutputCommitPlan
CommitApplier
assistant session message commit allow path
task result commit allow path
artifact commit allow path
memory commit allow path
title commit allow path
approval / governance audit
```

为什么重要：

```text
现在模型可以返回给用户，但不会写 assistant session。
这保证安全，但不适合作为长期产品态。
```

### 3.5 TaskCoordinator 重构

现在有：

```text
TaskContract / TaskPromptContract preview
TaskCoordinator legacy lifecycle
```

还缺：

```text
TaskCoordinator 消费 TaskContract / ExecutionNode
TaskResultRef 变成 CommitCandidate
任务绑定不再从 raw query regex 推断
任务生命周期事件由 Orchestration trace 统一记录
```

为什么重要：

```text
任务系统未来是多智能体管理总入口。
如果 TaskCoordinator 仍保留旧执行和推断逻辑，多 agent 会重新耦合。
```

### 3.6 CapabilityManifest / ResourcePolicy 统一导出

现在有：

```text
OperationRegistry
ResourcePolicy
OperationGate
Skill / Task / Operation preview
```

还缺：

```text
CapabilityManifest -> ResourcePolicyBuilder
ToolContract / WorkerContract / AgentProfileContract -> OperationRequirement
read_only / destructive / idempotent / open_world 风险维度
approval token / approval record
filesystem / shell / network scope runtime recheck
```

为什么重要：

```text
OperationGate 只有在资源事实源完整时才是真正的门。
```

### 3.7 PromptManifest / Soul / ContextPolicy 统一

现在有：

```text
SoulRuntimeView
Prompting package
ContextPolicyPreview
MemoryRuntimeView
```

还缺：

```text
正式 PromptManifest 归位
SoulProjection / ContextPolicy / MemoryRuntimeView 的统一可见上下文 manifest
prompt section source refs
prompt cache / static-dynamic boundary
```

为什么重要：

```text
模型看到什么，必须和任务、资源、记忆、灵魂投影都有 trace。
否则后续很难解释模型为何执行或回答。
```

### 3.8 观察性与测试体系

现在有：

```text
preview events
turn trace
部分 preview regression tests
```

还缺：

```text
plan-vs-actual diff
directive trace
operation gate trace
commit trace
resource policy adoption tests
old query resurrection tests
tool/worker fail-closed tests
```

为什么重要：

```text
成熟 agent runtime 不能只看最终答案。
必须能解释每个候选为什么被采纳、阻断或执行。
```

---

## 4. 下一阶段建议顺序

### Phase A：把当前框架状态冻结成基线

目标：

```text
承认当前 query 清理已完成。
承认 model-only 主链已贯通。
明确禁止旧 planner / direct tool / worker 回流。
```

验收：

```text
backend/query 源码保持三件套。
没有 backend/query/planner.py 等旧源码复活。
QueryRuntime 继续 adapter-only。
```

### Phase B：做正式 Adoption 管线

目标：

```text
OrchestrationPlanPreview -> OrchestrationPlan
ResourcePolicyPreview -> AdoptedResourcePolicy
PlanValidationResult -> adoption decision
```

验收：

```text
ModelResponseRuntimeExecutor 不再自己从 preview 构造 adopted ResourcePolicy。
RuntimeDirective 由 orchestration adoption 生成。
```

### Phase C：做 CommitGate / OutputCommitPlan

目标：

```text
OutputBoundary 只生成输出候选。
CommitGate 决定 assistant session / task result 是否写回。
CommitApplier 才能调用 session_manager / task store / memory store。
```

验收：

```text
QueryRuntime 不直接 append assistant。
用户输入的 inbound commit 也通过统一 CommitApplier 包装。
assistant session write 可以在明确 policy 下放行。
```

### Phase D：重构 TaskCoordinator

目标：

```text
TaskCoordinator 不再从 raw query regex 推断 binding。
TaskCoordinator 不再直接 run tool task。
TaskCoordinator 成为 task lifecycle / task state / result candidate 管理器。
```

验收：

```text
任务绑定来自 TaskContract / ExecutionNode / ContextPolicy。
task result 写回走 CommitGate。
```

### Phase E：只读 Tool / Worker Executor

目标：

```text
先放开 read-only retrieval / evidence / structured preview。
不放开 shell / filesystem write / memory write。
```

验收：

```text
ToolExecutor / WorkerExecutor 只消费 RuntimeDirective。
OperationGate 对每个 operation_ref 重检。
结果只进入 ResultCandidate / CommitCandidate。
```

### Phase F：清理工程残影和重建测试系统

目标：

```text
删除 __pycache__ 旧模块残影。
删除或重写导入旧 query 模块的测试。
建立新边界 regression tests。
```

验收：

```text
测试围绕 CandidateSet / OrchestrationPlan / ExecutionGraph / RuntimeDirective / OperationGate / CommitGate。
不再围绕 QueryPlanner / runtime_tools / runtime_persistence。
```

---

## 5. 严格防回退规则

后续任何代码不得重新引入：

```text
QueryPlanner.build_plan() -> QueryRuntime 执行分支
QueryRuntime 根据 execution_kind 直接调度 tool / worker
RuntimeToolBridge 从 route/tool_name 推断工具权限
TaskCoordinator 从 raw query 推断 binding 后直接执行
MemoryFacade 自动 durable commit
assistant message 绕过 CommitGate append_messages
worker / tool result 直接成为 final answer
ResourcePolicyPreview 进入 OperationGate 作为 executable policy
RuntimeDirectiveCandidate 被 executor 消费
```

后续任何可执行能力必须满足：

```text
TaskContract
  -> ResourcePolicyPreview
  -> PlanValidationResult
  -> AdoptedResourcePolicy
  -> ExecutionGraph
  -> RuntimeDirective
  -> OperationGate
  -> Executor
  -> ResultCandidate
  -> CommitGate
  -> OutputBoundary / CommitApplier
```

---

## 6. 最终判断

当前框架与先进架构原则的关系：

```text
方向：正确。
边界：基本立住。
旧 query 清理：生产源码层面基本完成。
执行恢复：只恢复了 model-only lane。
成熟度：中等，不能算完成态。
```

最需要优先补的不是继续拆 query，而是：

```text
1. OperationGatePipeline 与 OperationDescriptor 补强。
2. 正式 Adoption 管线。
3. CommitGate / OutputCommitPlan / CommitApplier。
4. TaskCoordinator 合同化。
5. ContextBoundaryValidator。
6. 只读 ToolExecutor / WorkerExecutor。
7. 新测试体系。
```

这些补完以后，系统才会从“安全的新框架骨架”进入“成熟可执行 AgentRuntime”。
