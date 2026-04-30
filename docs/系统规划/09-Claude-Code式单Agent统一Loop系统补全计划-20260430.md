# Claude Code 式单 Agent 统一 Loop 系统补全计划

日期：2026-04-30  
定位：本文件是当前阶段的最终施工蓝图。它根据 Claude Code 的统一循环范式，重新审视洪荒时代现有系统，并给出把单 agent 主链补成成熟 AgentRuntime 的落地计划。多智能体只保留接口准备，不进入本轮实现。

---

## 0. 最终结论

我们采用的核心架构口径是：

```text
单 agent 阶段先做一个统一 TaskRunLoop。
TaskRunLoop 归 OrchestrationSystem 所有。
它是当前 TaskRun 的唯一运行循环和唯一推进权。
```

这里的 loop 不是旧 `backend/query` 重新变厚，也不是把所有系统揉进一个大函数。

正确形态是：

```text
while True:
  读取/恢复 LoopState
  准备上下文
  构建灵魂投影和 PromptManifest
  生成或读取 RuntimeDirective
  OperationGate 执行前检查
  调 executor
  收集 observation / result candidate
  更新 context / event log / checkpoint
  判断 continue / waiting / completed / failed / aborted
```

各系统的角色必须固定：

```text
编排系统：拥有 loop 和调度顺序。
任务系统：提供任务目标、约束和 TaskContract。
记忆系统：提供对话记忆、状态记忆、长期记忆候选和上下文包。
上下文管理：维护模型可见消息、token 压力、压缩和 tool_result 配对不变量。
灵魂系统：提供当前阶段投影和 PromptManifest。
操作系统：提供 ResourcePolicy、OperationGate、审批和安全验证。
执行层：只消费 RuntimeDirective，返回 observation / result candidate。
输出边界：治理可见答案和 canonical answer。
写回门：决定哪些结果能落入 session / task / artifact / memory。
query：只做 API adapter 和事件流 adapter。
```

当前最大缺口不是“还缺一个框架库”，而是：

```text
已有系统还没有被一个统一 while loop 串成可继续、可等待、可恢复、可审计的运行体。
```

---

## 1. 我们从 Claude Code 借什么

根据 `docs/设计原则/05-对话循环.md` 的 Claude Code 源码拆解，真正值得迁移的不是 `query.ts` 这个文件名，而是它的循环不变量。

### 1.1 统一 Async / Event Loop

Claude Code 的核心是：

```text
AsyncGenerator + while(true) + 显式 State + 多个 continue 点 + terminal reason。
```

对我们来说，对应为：

```text
TaskRunLoop.run_stream()
  -> async event stream
  -> RuntimeLoopState
  -> RuntimeTransition
  -> RuntimeTerminalReason
```

要求：

```text
每次模型输出、工具请求、工具结果、审批等待、压缩、错误恢复、最终输出都要变成 RuntimeEvent。
QueryRuntime 只转发这些 RuntimeEvent。
```

### 1.2 State 和 transition 必须显式

Claude Code 的 `transition` 记录“上一次为什么 continue”。

我们必须有：

```text
RuntimeLoopState.transition
```

首批 transition：

```text
start
next_turn
continue_after_model_result
continue_after_tool_result
continue_after_worker_result
continue_after_context_compaction
continue_after_approval
continue_after_recovery
stop_after_final_output
```

这能避免裸 `while True` 变成黑盒。

### 1.3 工具/动作结果必须回填成 observation

Claude Code 的工具循环是：

```text
model -> tool_use -> run tool -> tool_result -> next model call
```

我们要抽象成：

```text
model -> RuntimeActionRequest -> OperationGate -> Executor -> Observation -> RuntimeContextManager -> next model call
```

第一阶段可以只有 model-only，但接口必须能自然扩展到：

```text
tool_result
worker_result
agent_result
```

### 1.4 压缩和恢复是 loop 阶段

Claude Code 不是把压缩当后台摘要，而是在循环顶部和错误恢复路径中处理：

```text
tool result budget
snip / microcompact
context collapse
autocompact
reactive compact
```

我们对应为：

```text
RuntimeContextManager.prepare()
  -> ContextPressureState
  -> CompactionDirective
  -> MemorySystem / ContextPolicy 执行候选压缩
  -> context_compacted event
  -> checkpoint
  -> continue
```

第一阶段不做复杂压缩，但必须留下阶段和事件。

### 1.5 权限、审批、失败恢复必须在 loop 内

Claude Code 的 canUseTool / stop hook / fallback / retry 都在循环控制流里。

我们对应为：

```text
OperationGate.check()
ApprovalState
DenialTrackingState
RuntimeRecoveryPolicy
RuntimeTerminalReason
```

执行器不能绕过这些阶段。

---

## 2. 当前项目真实状态

### 2.1 已有的可靠基础

当前代码已经有这些可复用结构：

```text
backend/query/runtime.py
  QueryRuntime 已是 adapter-only，但仍直接调用 model-only executor。

backend/runtime/agent_chain.py
  AgentRuntimeChainAssembler 能汇总 MemoryRuntimeView / ContextPolicyPreview / TaskOperationPreview。

backend/execution/model_response.py
  ModelResponseRuntimeExecutor 已按 RuntimeDirective + OperationGate + OutputBoundary + CommitGate(blocked) 运行。

backend/orchestration/runtime_directive.py
  RuntimeDirective 合同已明确：executor 只能消费 RuntimeDirective，不消费 candidate。

backend/operations/gate.py
  OperationGatePipeline 已有 approval、headless、denial tracking、validator、dangerous allow stripping。

backend/memory_system/runtime_view.py
  三层记忆候选已能汇总成 MemoryRuntimeView。

backend/context_policy/package_builder.py
  ContextPolicyPreview 能把记忆候选裁剪成 ContextPackage。

backend/soul/projection.py
  SoulProjection / PromptManifest 能表达模型可见投影，不扩大权限。

backend/orchestration/commit_gate.py
  CommitGatePreview / RuntimeCommitGateDecision 已有 blocked 写回边界。
```

### 2.2 关键断点

当前链路仍然是：

```text
QueryRuntime
  -> AgentRuntimeChainAssembler preview
  -> ModelResponseRuntimeExecutor
```

问题：

```text
1. QueryRuntime 仍然直接调 executor。
2. RuntimeDirective / ResourcePolicy 仍在 executor 内临时构造。
3. 没有 TaskRun。
4. 没有 RuntimeLoopState。
5. 没有 RuntimeEventLog。
6. 没有 RuntimeCheckpoint。
7. 没有 RuntimeContextManager。
8. 没有统一 terminal reason。
9. CommitGate 还不能关闭 TaskRun。
10. tool / worker / agent observation 回填机制还不存在。
```

所以现在不是“系统已经成熟”，而是：

```text
边界已经清出来了，核心 loop 还没落地。
```

---

## 3. 目标结构

### 3.1 总链路

```text
QueryRuntime
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
       -> RuntimeCheckpointStore
       -> RuntimeStateIndex
```

### 3.2 单 agent 第一版执行流

第一版先只跑 model-only，但必须按完整 loop 形态跑：

```text
UserRequest
  -> QueryRuntime.astream()
  -> TaskRunLoop.run_stream()
     -> create TaskRun
     -> append task_run_started
     -> build TaskContract
     -> build MemoryRuntimeView
     -> build ContextSnapshot
     -> build StageProjection / PromptManifest
     -> adopt model-only RuntimeDirective
     -> OperationGate.check(op.model_response)
     -> ModelResponseRuntimeExecutor.dispatch()
     -> OutputBoundary.apply()
     -> CommitGate.check()
     -> write RuntimeCheckpoint
     -> terminal completed
  -> QueryRuntime yields events
```

注意：

```text
QueryRuntime 不调 ModelResponseRuntimeExecutor。
TaskRunLoop 调 ModelResponseRuntimeExecutor。
ModelResponseRuntimeExecutor 不再临时造 ResourcePolicy。
AdoptionPipeline 生成 adopted ResourcePolicy 和 RuntimeDirective。
```

### 3.3 完整 loop 的未来形态

第二阶段开始支持 read-only tool / worker 时：

```text
while True:
  context = RuntimeContextManager.prepare(state)

  if context.needs_compaction:
    state = compact_context(state)
    append context_compacted
    checkpoint
    continue

  projection = SoulSystem.project_stage(state, context)
  directive = OrchestrationPolicy.next_directive(state, projection)

  gate = OperationGate.check(directive)
  append operation_gate_checked

  if gate.requires_approval:
    state.status = waiting_approval
    checkpoint
    return waiting_approval

  if not gate.allowed:
    state.status = blocked
    checkpoint
    return blocked_by_gate

  observation = ExecutorRegistry.dispatch(directive)
  append executor_observation

  RuntimeContextManager.record_observation(state, observation)

  if observation.needs_model_followup:
    state.transition = next_turn
    checkpoint
    continue

  output = OutputBoundary.apply(observation)
  commit = CommitGate.check(output)
  append commit_checked
  checkpoint

  if commit.terminal:
    return completed
```

---

## 4. 核心数据合同

### 4.1 TaskRun

归属：`backend/orchestration/runtime_loop/models.py`

职责：

```text
表示一次任务运行实例，不等于 TaskContract。
```

字段建议：

```text
task_run_id
session_id
task_id
task_contract_ref
owner_agent_seat_id = main
status
created_at
updated_at
latest_event_offset
latest_checkpoint_ref
terminal_reason
diagnostics
```

### 4.2 RuntimeLoopState

职责：

```text
表示 while loop 当前可恢复状态。
```

字段建议：

```text
task_run_id
turn_count
step_count
current_step_id
transition
terminal_reason
messages_ref
context_snapshot_ref
memory_state_ref
projection_ref
prompt_manifest_ref
pending_action_requests
pending_approval_state
denial_tracking_state
token_pressure
compaction_state
result_refs
commit_state
```

### 4.3 RuntimeEvent

职责：

```text
append-only 事实轨迹。
```

首批事件：

```text
task_run_started
loop_iteration_started
task_contract_built
memory_runtime_view_built
context_snapshot_built
stage_projection_built
runtime_directive_issued
operation_gate_checked
executor_started
model_item_received
executor_observation_received
output_boundary_applied
commit_gate_checked
checkpoint_written
loop_terminal
loop_error
```

后续事件：

```text
tool_call_requested
tool_result_received
worker_requested
worker_result_received
context_compaction_requested
context_compacted
approval_waiting
approval_resumed
recovery_attempted
```

### 4.4 RuntimeCheckpoint

职责：

```text
加速恢复，不取代 RuntimeEventLog。
```

字段建议：

```text
checkpoint_id
task_run_id
event_offset
loop_state
context_snapshot_ref
prompt_manifest_ref
approval_state
commit_state
created_at
checksum
```

规则：

```text
checkpoint 必须对应 event_offset。
不能出现只有 checkpoint 没有 event 的状态跳变。
```

### 4.5 RuntimeTerminalReason

首批：

```text
completed
waiting_approval
blocked_by_gate
budget_exhausted
max_turns
context_unrecoverable
executor_failed
commit_failed
user_aborted
internal_error
```

---

## 5. 各系统如何参与 Loop

### 5.1 TaskSystem

输入：

```text
session_id
user_message
understanding_candidates
```

输出：

```text
TaskContract
TaskPromptContract
```

禁止：

```text
不推进 RuntimeStep。
不直接调用 executor。
不写 final answer。
```

### 5.2 MemorySystem

输入：

```text
session_id
task_contract
memory_intent
loop_state
```

输出：

```text
MemoryRuntimeView
MemoryContextCandidate
StateMemoryRestoreCandidate
MemoryWriteCandidate
```

规则：

```text
restore != decide。
状态记忆优先进入 active_process_context。
长期记忆必须保持候选和验证语义。
durable memory 写入继续走 CommitGate，第一阶段 blocked。
```

### 5.3 RuntimeContextManager

这是当前必须新增的关键组件。

输入：

```text
history
pending_user_message
memory_runtime_view
context_policy_result
observations
loop_state
```

输出：

```text
RuntimeContextSnapshot
model_messages
token_pressure
compaction_directive
context_invariant_report
```

必须负责：

```text
模型可见消息。
tool_use / tool_result 配对不变量。
大结果截断。
token 压力。
压缩边界。
当前任务目标保护。
上下文 ref 进入 checkpoint。
```

### 5.4 SoulSystem

输入：

```text
TaskContract
RuntimeContextSnapshot
ResourceRuntimeView
AgentSeat(main)
```

输出：

```text
StageProjection
PromptManifest
```

规则：

```text
每个 RuntimeStep 前由 TaskRunLoop 调用。
灵魂投影不能扩大 OperationGate 权限。
PromptManifest ref 必须进入 checkpoint。
```

### 5.5 OperationSystem

输入：

```text
RuntimeDirective
AdoptedResourcePolicy
OperationGatePipelineContext
```

输出：

```text
OperationGateResult
ApprovalState
DenialTrackingState
```

规则：

```text
每个 RuntimeDirective 执行前强制检查。
requires_approval 让 loop 进入 waiting_approval。
headless 无 token 必须 fail-closed。
allowed 也必须写 operation_gate_checked event。
```

### 5.6 ExecutorRegistry

输入：

```text
RuntimeDirective
RuntimeExecutionContext
```

输出：

```text
RuntimeObservation
ResultCandidate
ResultArtifactRef
```

第一阶段：

```text
只注册 model executor。
```

后续：

```text
read-only tool executor
worker executor
bounded agent executor
```

### 5.7 OutputBoundary

输入：

```text
RuntimeObservation
ResultCandidate
```

输出：

```text
visible_text
canonical_answer
answer metadata
leak flags
persist policy
```

规则：

```text
工具/worker/agent 原始输出不能直接成为 final answer。
```

### 5.8 CommitGate

输入：

```text
CommitCandidate
OutputBoundaryResult
TaskRun state
```

输出：

```text
CommitDecision
CommitRecord
```

第一阶段允许：

```text
RuntimeEventLog
RuntimeCheckpoint
TaskRun status
final answer record
```

第一阶段继续 blocked：

```text
durable memory write
filesystem write
external side effect
autonomous multi-agent handoff
```

---

## 6. 文件级施工计划

### Phase 0：冻结口径和文档

目标：

```text
把 07 / 08 / 09 作为统一 Loop 的施工依据。
```

文件：

```text
docs/系统规划/07-AgentRuntime统一Loop架构重审与整改方案-20260430.md
docs/系统规划/08-Runtime与Loop本质分析-Claude-Code与Codex循环策略-20260430.md
docs/系统规划/09-Claude-Code式单Agent统一Loop系统补全计划-20260430.md
docs/系统规划/README.md
```

验收：

```text
不再把 RuntimeWorkflow 设计成独立主权系统。
不再让 QueryRuntime 恢复 planner / tool / worker / memory write。
```

### Phase 1：新增 runtime_loop 包

新增：

```text
backend/orchestration/runtime_loop/__init__.py
backend/orchestration/runtime_loop/models.py
backend/orchestration/runtime_loop/events.py
backend/orchestration/runtime_loop/event_log.py
backend/orchestration/runtime_loop/checkpoint.py
backend/orchestration/runtime_loop/state_index.py
backend/orchestration/runtime_loop/terminal.py
```

实现：

```text
TaskRun
RuntimeLoopState
RuntimeTransition
RuntimeTerminalReason
RuntimeEvent
RuntimeEventLog
RuntimeCheckpoint
RuntimeStateIndex
```

验收：

```text
能创建 TaskRun。
能 append RuntimeEvent。
能写 latest checkpoint。
能从 state index 查 latest task run。
```

### Phase 2：TaskRunLoop 接管 model-only lane

新增：

```text
backend/orchestration/runtime_loop/task_run_loop.py
backend/orchestration/runtime_loop/context.py
```

改造：

```text
backend/query/runtime.py
backend/runtime/agent_chain.py
backend/execution/model_response.py
backend/orchestration/__init__.py
```

目标链路：

```text
QueryRuntime.astream
  -> TaskRunLoop.run_stream
  -> ModelResponseRuntimeExecutor
```

验收：

```text
QueryRuntime 不直接调用 ModelResponseRuntimeExecutor。
每次请求都有 task_run_started event。
每次执行都有 operation_gate_checked event。
每次结束都有 checkpoint_written + loop_terminal event。
行为仍保持 model-only。
```

### Phase 3：RuntimeContextManager

新增：

```text
backend/orchestration/runtime_loop/context_manager.py
backend/orchestration/runtime_loop/context_snapshot.py
```

可能复用：

```text
backend/context_policy/package_builder.py
backend/memory_system/runtime_view.py
backend/prompting/builder.py
```

职责：

```text
构建 model_messages。
接收 ContextPolicyResult。
记录 context_snapshot_ref。
为后续 tool_result pairing / compaction 留出不变量检查。
```

验收：

```text
ModelResponseRuntimeExecutor 不自己拼完整模型消息。
prompt / context package / manifest ref 能进入 checkpoint。
```

### Phase 4：正式 AdoptionPipeline

新增或改造：

```text
backend/orchestration/adoption.py
backend/orchestration/runtime_loop/adoption_runtime.py
backend/operations/policy_builder.py
```

目标：

```text
把 executor 内临时构造 RuntimeDirective / ResourcePolicy 移出来。
```

验收：

```text
RuntimeDirective 来自 TaskRunLoop / AdoptionPipeline。
AdoptedResourcePolicy 来自 OperationSystem。
executor 只消费 RuntimeDirective + RuntimeExecutionContext。
executor 不再构造 resource policy。
```

### Phase 5：CommitGate 最小闭环

改造：

```text
backend/orchestration/commit_gate.py
backend/orchestration/runtime_loop/task_run_loop.py
backend/query/runtime.py
```

目标：

```text
CommitGate 允许最小运行态写回：
  TaskRun status
  final answer record
  RuntimeCheckpoint
```

继续 blocked：

```text
assistant session append 可先维持 blocked 或单独小心放行。
durable memory write 继续 blocked。
artifact/filesystem 外部副作用继续 blocked。
```

验收：

```text
done event 来自 loop_terminal。
commit_gate_checked 写入 event log。
CommitDecision 能解释哪些写回允许、哪些 blocked。
```

### Phase 6：read-only tool loop

新增：

```text
backend/execution/tool_executor.py
backend/orchestration/runtime_loop/action_request.py
backend/orchestration/runtime_loop/observation.py
```

接入：

```text
OperationDescriptor.concurrency_safe
OperationDescriptor.max_result_size_chars
OperationGate validators
RuntimeContextManager.record_observation
```

执行形态：

```text
model emits tool request
  -> TaskRunLoop creates RuntimeDirective(tool)
  -> OperationGate
  -> ToolExecutor
  -> RuntimeObservation(tool_result)
  -> ContextManager records tool_result
  -> transition next_turn
```

验收：

```text
只读工具可作为 observation 回填模型。
工具原始输出不能直接进 final answer。
写工具、shell、文件写入仍 blocked / requires_approval。
```

### Phase 7：worker loop

新增：

```text
backend/execution/worker_executor.py
backend/orchestration/runtime_loop/result_artifact.py
```

验收：

```text
WorkerResult 作为 ResultArtifactRef / Observation 回填。
worker 不直接写 final answer。
worker 不绕过 OperationGate。
```

### Phase 8：多 agent 只预留，不实现拓扑

保留接口：

```text
AgentSeat
AgentSeatRuntimeRef
AgentMemoryScopeRef
AgentResultObservation
spawn_edge event
```

本阶段不做：

```text
多 agent 拓扑规划。
agent 间协议。
子 agent 自主循环。
agent-to-agent message bus。
```

验收：

```text
单 agent 主链不因未来多 agent 接口而复杂化。
多 agent 不影响当前 loop 的唯一推进权。
```

---

## 7. 验收标准

### 7.1 架构验收

```text
QueryRuntime 是 adapter-only。
TaskRunLoop 是唯一运行 loop。
所有 executor 只消费 RuntimeDirective。
所有副作用前置都走 OperationGate。
所有写回都走 CommitGate。
所有可见答案都走 OutputBoundary。
```

### 7.2 Loop 验收

```text
每个 TaskRun 有 LoopState。
每次 continue 有 transition。
每次终止有 terminal reason。
每个关键阶段有 RuntimeEvent。
每个终止点前有 RuntimeCheckpoint。
```

### 7.3 Claude Code 原则验收

```text
有显式 while loop。
有流式事件。
有 action -> observation -> continue 的闭环。
有权限前置。
有上下文治理阶段。
有恢复/等待/失败 terminal。
有 event log + checkpoint。
```

### 7.4 防跑偏验收

禁止：

```text
1. QueryRuntime 重新生成执行计划。
2. executor 内部长期构造 ResourcePolicy。
3. MemorySystem 自动推进任务。
4. SoulProjection 扩大权限。
5. OperationGate allow 后不写 event。
6. tool / worker 结果直接成为 final answer。
7. checkpoint 没有 event offset。
8. context 压缩破坏 tool_use/tool_result 配对。
9. 多 agent 提前进入本轮施工。
10. 用 preview object 直接执行。
```

---

## 8. 当前优先级

下一步不该先做复杂工具、不该先做多 agent、不该先做长期记忆自动写入。

优先级必须是：

```text
P0 文档口径冻结。
P1 runtime_loop 数据模型与 event log。
P2 TaskRunLoop 接管 model-only lane。
P3 RuntimeContextManager 接管模型可见上下文。
P4 AdoptionPipeline 移出 executor 临时 policy/directive。
P5 CommitGate 最小闭环。
P6 read-only tool loop。
P7 worker loop。
P8 多 agent 接口预留。
```

---

## 9. 最终判断

我们现在要补的不是“一个更好的 query”，而是：

```text
一个 Claude Code 式的、由编排系统拥有的、任务导向的单 agent 统一循环。
```

这套循环必须先把单 agent 做扎实：

```text
能持续推进。
能等待审批。
能失败收束。
能恢复状态。
能记录事件。
能治理上下文。
能把动作结果回填给模型。
能通过 CommitGate 关闭任务。
```

等单 agent 的 loop 稳定后，多 agent 才是多个 TaskRunLoop / AgentSeat / spawn edge / memory scope / interaction protocol 的拓扑问题，而不是现在就混进主链的执行问题。

