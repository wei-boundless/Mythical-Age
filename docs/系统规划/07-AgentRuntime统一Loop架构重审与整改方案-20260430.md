# AgentRuntime 统一 Loop 架构重审与整改方案

日期：2026-04-30  
定位：本文件重新审视洪荒时代当前结构，明确采用 Codex / Claude Code 的统一 loop 范式，并给出不足清单、目标架构和整改顺序。它不是为现有结构辩护，而是指出当前结构离成熟 AgentRuntime 还差什么。

---

## 0. 结论先行

必须修正架构主口径：

```text
先进 agent 架构的核心不是“很多系统互相配合”，
而是“一个统一 loop 管住当前运行态，并在 loop 内调用各专业系统”。
```

因此洪荒时代的目标不是：

```text
TaskSystem + OperationSystem + MemorySystem + SoulSystem + OutputSystem 各自运行，
然后靠约定拼在一起。
```

而是：

```text
OrchestrationSystem.TaskRunLoop 统一管理当前 TaskRun。

TaskRunLoop 负责：
  调度顺序
  step 状态
  loop event
  checkpoint
  resume
  tool / worker / agent iteration
  context pressure
  approval waiting
  commit cycle

其他系统负责：
  给 loop 提供合同、候选、投影、权限判断、上下文、执行器、输出治理和写回决策。
```

一句话：

```text
编排层管所有系统的运行协作。
其他系统不自行推进任务，只作为统一 loop 的阶段服务。
```

---

## 1. 先进架构原则重新提炼

从 Codex / Claude Code 的源码和本地运行痕迹看，成熟 AgentRuntime 至少有 10 个硬原则。

### 1.1 统一 Loop 原则

```text
所有当前任务的推进必须经过一个 loop。
```

loop 统一管理：

```text
turn context
model call
tool call
worker call
agent call
permission check
approval wait
context compact
result collect
final output
commit
resume
```

如果没有统一 loop，系统会出现：

```text
query 路径一套逻辑
tool 路径一套逻辑
memory 路径一套逻辑
worker 路径一套逻辑
最终无法保证恢复、权限、上下文、写回一致。
```

### 1.2 Event-Sourced 原则

成熟 loop 不只保存最终结果。

必须保存：

```text
turn_context
model message
reasoning item
function/tool call
tool output
permission decision
token count
checkpoint
compaction
approval state
commit decision
```

Codex 的 rollout JSONL 就是这个范式。

对应我们：

```text
RuntimeEventLog 是第一事实轨迹。
RuntimeCheckpoint 是恢复快照。
RuntimeStateIndex 是查询入口。
```

### 1.3 ContextManager 原则

上下文不是 prompt 拼接。

成熟系统必须有专门的 RuntimeContextManager 管：

```text
model-visible history
tool call / tool result 配对
history version
token pressure
large result truncation
compaction boundary
current-turn goal preservation
rollback boundary
```

当前我们的 ContextPolicy / MemorySystem 还不能替代它。

### 1.4 Tool / Operation Contract 原则

工具不是函数。

工具/操作必须是厚合同：

```text
input schema
output schema
read_only
destructive
concurrency_safe
open_world
requires_user_interaction
max_result_size
interrupt_behavior
deferred_loading
permission matcher
safety validator
```

当前我们已经开始补 OperationDescriptor，但还没有在统一 loop 中强制执行全部字段。

### 1.5 Permission Pipeline 原则

权限不能靠 prompt。

必须由 loop 在执行前统一调用：

```text
ResourcePolicy
OperationGate
ApprovalState
SafetyValidator
IdempotencyPolicy
HeadlessPolicy
DenialTracking
```

OperationGate 有否决权，但没有调度权。

### 1.6 Compaction 是 Loop 阶段

压缩不是 MemorySystem 的后台摘要功能。

它必须是 loop 中的运行阶段：

```text
detect token pressure
choose compaction strategy
preserve message invariants
rewrite context state
append compact event
write checkpoint
continue / block
```

当前我们还没有这个 loop 阶段。

### 1.7 Agent 生命周期原则

多 agent 不是多个聊天窗口相加。

必须由统一 loop 管：

```text
AgentSeat
spawn edge
memory scope
permission mode
context isolation
output handle
max turns
background / foreground
recursion guard
commit ownership
```

当前我们的多 agent 仍是规划口径，缺运行态生命周期。

### 1.8 Prompt Cache / Prompt Manifest 原则

prompt 不是一次性字符串。

成熟系统会区分：

```text
global stable section
session-memoized section
per-turn volatile section
tool/dynamic capability section
memory/context section
critical reminder section
```

当前 PromptManifest 有雏形，但没有进入 loop 的 context manager 和 checkpoint。

### 1.9 Result Governance 原则

执行结果不能直接进最终答案。

必须经过：

```text
ResultCandidate
ResultArtifact
OutputBoundary
CommitGate
```

当前 model-only lane 做了一部分，但 tool / worker / agent 尚未统一。

### 1.10 Query Adapter 原则

`backend/query` 不能重新变厚。

但这不意味着没有 query loop。

正确口径：

```text
旧 query layer 不恢复。
统一 loop 迁入 OrchestrationSystem.TaskRunLoop。
QueryRuntime 只做 API 输入和事件流输出。
```

---

## 2. 当前结构的主要不足

下面不再强调“已有骨架”，只列不足。

### 2.1 编排系统还没有真正的统一 loop

当前有：

```text
OrchestrationPlanPreview
ExecutionGraphPreview
ControlKernel preview
RuntimeDirectiveCandidate
```

但缺：

```text
OrchestrationSystem.TaskRunLoop
RuntimeLoopState
RuntimeEventLog
RuntimeStepState 状态机
loop continuation / wait / resume
```

这意味着当前编排系统还没有真正成为 agent 大脑。

### 2.2 model-only lane 绕过了正式 Adoption

当前 `ModelResponseRuntimeExecutor` 内部临时构造：

```text
RuntimeDirective(model)
ResourcePolicy(model_only)
```

这是过渡方案，不是成熟架构。

问题：

```text
执行器内部有临时调度材料。
TaskRunLoop 无法 replay。
AdoptionPipeline 没有成为运行前置。
ResourcePolicy 的 adopted 状态不是统一来源。
```

### 2.3 缺 RuntimeEventLog

当前 trace / preview event 不是持久化事实日志。

缺少：

```text
append-only runtime events
event offset
replay ability
event -> checkpoint consistency
event -> state index consistency
```

没有 EventLog，就不能真正说“可恢复 agent loop”。

### 2.4 缺 RuntimeContextManager

当前有：

```text
MemoryRuntimeView
ContextPolicyPreview
PromptManifest
build_system_prompt
```

但缺一个统一管理模型可见上下文的运行时组件。

风险：

```text
tool call / tool output 未来可能被 compact 切断。
worker 大结果可能污染主上下文。
当前 turn goal 保护只能靠约定。
prompt cache 分段策略无法落成。
context pressure 不能驱动 loop 决策。
```

### 2.5 记忆系统还没有被 loop 收编

当前记忆系统能提供候选，但没有成为 loop 阶段：

```text
conversation memory candidate
state memory candidate
long-term memory candidate
write candidate
compaction preview
```

缺：

```text
memory phase in TaskRunLoop
memory_state_ref in checkpoint
context_state_ref in checkpoint
compaction event
memory write candidate -> CommitGate cycle
```

### 2.6 灵魂投影还没有每步运行化

当前 SoulProjection 更像 preview / prompt assembly。

缺：

```text
StageProjectionCycle
AgentSeatProjection
ProjectionCheckpointRef
per-step prompt manifest rebuild
critical reminder reinjection
```

没有这个，灵魂系统无法成为 loop 的稳定认知层。

### 2.7 OperationGate 已增强，但没有成为 loop preflight

当前 OperationGatePipeline 已有不少细节：

```text
ApprovalState
DenialTrackingState
SafetyValidator
dangerous allow stripping
headless denial
```

但它还没有由统一 loop 强制调用每个 RuntimeDirective。

缺：

```text
OperationGateChecked event
approval waiting state
approval_state checkpoint
idempotency check
result size enforcement
executor-level mandatory preflight
```

### 2.8 CommitGate 还没有成为 loop close 阶段

当前 CommitGate 多数还是 blocked / preview。

缺：

```text
CommitPlan
CommitDecision
CommitApplier
session projection write
task_run status write
artifact ref write
commit event
commit state checkpoint
```

没有 CommitGate close 阶段，任务不能真正闭环。

### 2.9 多 Agent 仍缺运行态拓扑

当前多 agent 主要停在：

```text
AgentSeatPlan preview
future topology
bounded agent candidate
```

缺：

```text
AgentSeat runtime state
spawn edge log
child loop / child TaskRun binding
memory scope isolation
permission profile inheritance
result handle
recursive spawn guard
```

### 2.10 Query 清理完成，但新 loop 尚未补位

这是当前最大断层：

```text
旧 query 大链路已经清理；
新 OrchestrationSystem.TaskRunLoop 尚未落地。
```

所以系统现在处在：

```text
架构边界更干净，
但运行能力暂时偏薄。
```

这不是“已经很好”，而是必须进入统一 loop 重构阶段。

---

## 3. 正确的目标形态

### 3.1 总结构

```text
QueryAdapter
  -> OrchestrationSystem.TaskRunLoop
       -> TaskSystem
       -> RuntimeContextManager
       -> MemorySystem
       -> SoulSystem
       -> OperationSystem
       -> ExecutorRegistry
       -> OutputBoundary
       -> CommitGate
       -> RuntimeEventLog
       -> RuntimeCheckpoint
       -> RuntimeStateIndex
```

### 3.2 Loop 拥有什么

TaskRunLoop 拥有：

```text
当前 TaskRun 的唯一推进权
RuntimeStep 状态迁移权
WorkflowPlan / ExecutionGraph 消费权
RuntimeEventLog 写入权
RuntimeCheckpoint 写入权
continue / wait / block / complete / fail 决策权
```

### 3.3 其他系统怎么配合

各系统作为 loop 阶段服务：

```text
TaskSystem:
  输入 user/system trigger。
  输出 TaskContract / TaskRequirement。

MemorySystem:
  输入 task goal / session / agent seat / memory intent。
  输出 MemoryRuntimeView / MemoryCandidates / MemoryWriteCandidates。

RuntimeContextManager:
  输入 history / context package / result candidates。
  输出 model-visible context / context snapshot / pressure state。

SoulSystem:
  输入 TaskContract / AgentSeat / ResourceRuntimeView / ContextSnapshot。
  输出 StageProjection / PromptManifest。

OperationSystem:
  输入 RuntimeDirective / ResourcePolicy / TurnContext。
  输出 OperationGateResult / ApprovalState / ValidationResult。

ExecutorRegistry:
  输入 RuntimeDirective。
  输出 ResultCandidate / stream events。

OutputBoundary:
  输入 ResultCandidate。
  输出 visible answer / canonical answer / output policy。

CommitGate:
  输入 CommitCandidate。
  输出 CommitDecision / CommitRecord。
```

关键：

```text
这些系统可以拒绝、候选、规范化、治理；
但不能自行推进 RuntimeStep。
```

---

## 4. 新执行流

第一阶段先只接 model-only，但必须按完整 loop 形态接。

```text
QueryRuntime.astream
  -> TaskRunLoop.start_or_resume
     -> append task_run_started
     -> capture RuntimeTurnContext
     -> TaskSystem.build_task_contract
     -> OrchestrationSystem.adopt_single_agent_plan
     -> RuntimeStepState.ready(model_response)
     -> MemorySystem.build_runtime_view
     -> RuntimeContextManager.build_context_snapshot
     -> SoulSystem.build_stage_projection
     -> PromptManifest built
     -> RuntimeDirective issued
     -> OperationGate.check
     -> append operation_gate_checked
     -> ExecutorRegistry.dispatch(model)
     -> ModelResponseRuntimeExecutor.stream
     -> ResultCandidate created
     -> OutputBoundary.apply
     -> CommitGate.check
     -> append commit_gate_checked
     -> RuntimeCheckpoint.write
     -> append checkpoint_written
     -> decide complete
  -> QueryRuntime streams loop events
```

注意：

```text
不是 QueryRuntime 调所有系统。
是 QueryRuntime 调 TaskRunLoop。
TaskRunLoop 调所有系统。
```

---

## 5. 当前文档需要统一的术语

废弃或降级：

```text
RuntimeWorkflow 作为独立系统
runtime_workflow 作为独立包
TaskRunLoop 只是推进器
各系统平行协作
先补 checkpoint 再考虑 loop
```

统一改为：

```text
OrchestrationSystem.TaskRunLoop
统一 agent loop
编排系统唯一调度权
RuntimeEventLog first
RuntimeCheckpoint second
RuntimeStateIndex third
专业系统是 loop stage service
```

---

## 6. 整改优先级

### P0：锁定架构口径

必须完成：

```text
所有规划文档统一：
  编排系统拥有唯一 TaskRunLoop。
  TaskRunLoop 是统一 agent loop。
  其他系统不自行推进任务。
```

完成标准：

```text
不再出现 runtime_workflow 独立主权。
不再出现 TaskRunLoop 只是外围持久化工具。
```

### P1：新增 runtime_loop 包

新增：

```text
backend/orchestration/runtime_loop/
  __init__.py
  models.py
  events.py
  event_log.py
  checkpoint.py
  state_index.py
  context_manager.py
  task_run_loop.py
```

完成标准：

```text
能创建 TaskRun。
能 append RuntimeEvent。
能写 latest checkpoint。
能写 task_run index。
```

### P2：model-only lane 进入 loop

改造：

```text
backend/query/runtime.py
backend/execution/model_response.py
backend/runtime/agent_chain.py
```

完成标准：

```text
QueryRuntime 不直接调 ModelResponseRuntimeExecutor。
QueryRuntime 调 TaskRunLoop。
TaskRunLoop 调 ModelResponseRuntimeExecutor。
每次请求有 EventLog + Checkpoint。
```

### P3：OperationGate 成为强制 preflight

完成标准：

```text
所有 RuntimeDirective 执行前都有 OperationGateChecked event。
approval_state 写 checkpoint。
headless / approval / validator / denial tracking 全部进入 loop state。
```

### P4：RuntimeContextManager 接管模型可见上下文

完成标准：

```text
history 进入 context snapshot。
PromptManifest 进入 checkpoint。
tool call/output invariant 有 validator。
token pressure 可触发 compact phase。
```

### P5：CommitGate 成为 close phase

完成标准：

```text
final answer record / task_run status / artifact refs 可被最小写回。
durable memory write 继续 blocked。
所有 commit decision 写 event + checkpoint。
```

### P6：恢复 read-only tool / worker

完成标准：

```text
tool / worker 是 RuntimeStep。
结果是 ResultCandidate / ResultArtifact。
不直接进入 final answer。
OperationGate + ContextManager + CommitGate 全部经过 loop。
```

---

## 7. 反模式清单

后续实现必须避免：

```text
1. QueryRuntime 重新长出 planner/tool/worker/memory write。
2. Executor 内部临时构造 ResourcePolicy 并长期保留。
3. MemorySystem 自动推进任务或自动写长期记忆。
4. SoulProjection 变成调度器。
5. OperationGate 返回 allow 后 executor 绕过 event log。
6. Tool/Worker 输出直接拼进 final answer。
7. Checkpoint 没有对应 event log。
8. Event log 只记最终答案，不记中间动作。
9. Context compaction 不维护 tool call/output 配对。
10. 多 agent 子任务不记录 spawn edge / memory scope / permission profile。
```

---

## 8. 最终判断

洪荒时代当前结构的问题不是“有没有分层”，而是：

```text
分层已经有了，
但统一 loop 还没有真正接管这些层。
```

先进架构不是让模块各自保持优雅，而是让一个 loop 把它们组织成可执行、可恢复、可审计的运行体。

因此下一阶段的核心任务只有一个：

```text
把 OrchestrationSystem.TaskRunLoop 做出来。
```

这一步完成之前，不应该急着恢复复杂工具、worker、多 agent 或长期记忆自动写入。否则又会回到多个系统各自长出执行路径的状态。
