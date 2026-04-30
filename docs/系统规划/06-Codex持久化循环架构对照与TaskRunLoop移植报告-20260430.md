# Codex 持久化循环架构对照与 TaskRunLoop 移植报告

日期：2026-04-30  
定位：本文件用于把公开 Codex CLI 架构、本机 Codex 运行痕迹、以及洪荒时代当前系统分层对照起来，确定我们如何采用 Codex 的循环范式，但不照搬其一体化实现。

---

## 0. 总结论

我们应采用 Codex 的核心范式：

```text
持久化 agent loop = event-sourced rollout + runtime state index + context history manager + compaction + resume。
```

但不能照搬成一个新的 `query` 大脑。洪荒时代应落成：

```text
OrchestrationSystem
  owns TaskRunLoop
    -> RuntimeEventLog(JSONL)
    -> RuntimeCheckpoint
    -> RuntimeStateIndex(SQLite/JSON index)
    -> RuntimeContextManager
    -> StageProjectionCycle
    -> OperationGate
    -> CommitGate
```

一句话：

```text
Codex 的 loop 思想是对的；
统一 loop 范式也是先进 agent 架构的核心；
我们要把统一 loop 放进编排系统，而不是让各系统平行自行推进。
```

因此需要修正此前偏保守的表述：

```text
TaskRunLoop 不是附属持久化工具，
而是编排系统内部的统一 agent loop。

编排系统拥有唯一调度权；
TaskRunLoop 是这个调度权的运行时形态。
任务、操作、灵魂、记忆、输出、写回系统都作为 loop 内阶段服务被调用。
```

---

## 1. 本次读取范围

### 1.1 公开参考

```text
OpenAI Engineering:
  https://openai.com/index/unrolling-the-codex-agent-loop/

Codex CLI help:
  https://help.openai.com/en/articles/11096431-openai-codex-ci-getting-started

OpenAI Codex 源码:
  https://github.com/openai/codex

重点源码：
  codex-rs/rollout/src/recorder.rs
  codex-rs/rollout/src/session_index.rs
  codex-rs/core/src/context_manager/history.rs
```

公开源码确认了：

```text
RolloutRecorder 持久化 JSONL rollout。
session index / state db 用于快速列出和恢复。
ContextManager 管 history、token、tool call/output 不变量。
compaction 是 loop 的运行阶段，不是外部文档总结。
```

### 1.2 本机 Codex 运行痕迹

只读取了结构信息，没有展开敏感鉴权文件，也没有复制系统提示正文。

读取范围：

```text
C:/Users/admin/.codex/config.toml
C:/Users/admin/.codex/version.json
C:/Users/admin/.codex/session_index.jsonl
C:/Users/admin/.codex/history.jsonl
C:/Users/admin/.codex/sessions/**/rollout-*.jsonl
C:/Users/admin/.codex/state_5.sqlite schema
C:/Users/admin/.codex/logs_2.sqlite schema
C:/Users/admin/.codex/skills/*/SKILL.md
```

刻意未读取或未展开：

```text
C:/Users/admin/.codex/auth.json
C:/Users/admin/.codex/cap_sid
C:/Users/admin/.codex/.sandbox-secrets
rollout 中的完整 base_instructions 正文
rollout 中的完整对话正文
```

原因：

```text
本报告需要的是架构形态，不需要泄露密钥或完整私有提示内容。
```

---

## 2. 本机 Codex 运行痕迹观察

### 2.1 配置层

本机 `config.toml` 显示当前 Codex 运行具有这些结构：

```text
model_provider = crs
model = gpt-5.5
wire_api = responses
disable_response_storage = true
windows.sandbox = elevated
project trust_level = trusted
plugins documents / spreadsheets / presentations enabled
```

对我们有价值的点：

```text
1. 模型提供商、模型、reasoning effort 是运行快照的一部分。
2. response storage 可以关闭，但本地 rollout 仍存在。
3. sandbox / approval / plugin 状态是 turn context，不只是全局配置。
4. 插件不是每轮裸塞进 prompt，而是作为 runtime capability 管理。
```

对应洪荒时代：

```text
RuntimeFeatureSnapshot
RuntimeCapabilitySnapshot
TurnContextSnapshot
```

应该进入 `RuntimeEventLog` 和 `RuntimeCheckpoint`。

### 2.2 Rollout JSONL 层

本机 rollout 文件位于：

```text
C:/Users/admin/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
```

抽样结构：

```text
每行：
  timestamp
  type
  payload
```

观察到的 `type`：

```text
session_meta
turn_context
event_msg
response_item
```

抽样前 80 行统计：

```text
event_msg      34
response_item  44
session_meta    1
turn_context    1
```

`event_msg` 类型包括：

```text
task_started
thread_name_updated
user_message
agent_message
token_count
exec_command_end
```

`response_item` 类型包括：

```text
message
reasoning
function_call
function_call_output
```

对我们有价值的点：

```text
Codex 没有只保存“最终答案”。
它保存 loop 中的模型项、工具调用、工具输出、token 事件、turn context。
这使 replay / inspect / resume 成为可能。
```

对应洪荒时代：

```text
RuntimeEventLog 不应只记录 TaskRun status。
它应记录：
  TaskRunStarted
  TurnContextCaptured
  StageProjectionBuilt
  RuntimeDirectiveIssued
  OperationGateChecked
  ExecutorStarted
  ExecutorFinished
  ResultCandidateCreated
  OutputBoundaryApplied
  CommitGateChecked
  CheckpointWritten
```

### 2.3 SessionMeta

本机 `session_meta.payload` 字段：

```text
id
timestamp
cwd
originator
cli_version
source
model_provider
base_instructions
```

其中 `base_instructions` 长度约 21468 字符。这里没有展开正文，只确认其作为 session 元数据被保存。

对我们有价值的点：

```text
system/base instructions 是 session 元数据的一部分。
但模型可见 prompt 每轮如何组织，应交给 ContextManager / PromptManifest。
```

对应洪荒时代：

```text
SessionMeta / TaskRunMeta:
  base_prompt_policy_ref
  runtime_feature_snapshot_ref
  soul_projection_policy_ref
  model_provider
  model
  source
  cwd
```

不要把完整 prompt 当成唯一真相。应该保存：

```text
PromptManifest
PromptSection refs
ProjectionCheckpointRef
ContextPackageRef
```

### 2.4 TurnContext

本机 `turn_context.payload` 字段包含：

```text
turn_id
cwd
current_date
timezone
approval_policy
sandbox_policy
permission_profile
file_system_sandbox_policy
```

观察到：

```text
approval_policy = on-request
sandbox_policy.type = workspace-write
network_access = false
permission_profile 包含 file_system / network
```

对我们有价值的点：

```text
审批策略、沙盒策略、权限 profile 是每个 turn 的快照。
它们不是执行器临时读全局配置。
```

对应洪荒时代：

```text
RuntimeTurnContext:
  turn_id
  task_run_id
  cwd
  current_date
  timezone
  approval_policy
  sandbox_policy
  permission_profile_ref
  feature_snapshot_ref
```

并且：

```text
OperationGatePipelineContext 应从 RuntimeTurnContext 派生。
```

### 2.5 State SQLite

本机 `state_5.sqlite` schema 显示了几个非常关键的表：

```text
threads
thread_goals
thread_spawn_edges
thread_dynamic_tools
agent_jobs
agent_job_items
jobs
stage1_outputs
backfill_state
```

最重要的字段观察：

```text
threads:
  id
  rollout_path
  created_at / updated_at
  source
  model_provider
  cwd
  title
  sandbox_policy
  approval_mode
  tokens_used
  archived
  git_sha / git_branch / git_origin_url
  cli_version
  first_user_message
  agent_nickname / agent_role / agent_path
  memory_mode
  model
  reasoning_effort

thread_goals:
  thread_id
  goal_id
  objective
  status
  token_budget
  tokens_used
  time_used_seconds

thread_spawn_edges:
  parent_thread_id
  child_thread_id
  status

thread_dynamic_tools:
  thread_id
  position
  name
  description
  input_schema
  defer_loading
  namespace

agent_jobs / agent_job_items:
  job / item status
  instruction
  output_schema
  attempt_count
  result_json
  last_error
```

这说明 Codex 本地并不是“只有 JSONL”。它至少有三层：

```text
1. rollout JSONL：可 replay 的事实日志。
2. state sqlite：线程、目标、动态工具、子线程、agent job 的索引/运行状态。
3. history / session_index：快速入口和用户历史。
```

对应洪荒时代：

```text
RuntimeEventLog(JSONL)        -> replay truth
RuntimeStateIndex(SQLite)     -> query / list / resume / inspect
RuntimeCheckpoint(JSON/DB)    -> fast resume snapshot
```

### 2.6 SessionIndex 和 History

本机 `session_index.jsonl` 每行包含：

```text
id
thread_name
updated_at
```

本机 `history.jsonl` 每行包含：

```text
session_id
ts
text
```

对我们有价值的点：

```text
可恢复系统需要轻量列表入口。
不要每次都扫完整 event log。
```

对应洪荒时代：

```text
TaskRunIndex:
  task_run_id
  session_id
  title
  status
  updated_at
  latest_checkpoint_ref
  event_log_path
```

---

## 3. 本机 Prompt / Skill 观察

### 3.1 Base instructions 是 session meta，不是普通消息

Codex rollout 中 `base_instructions` 出现在 `session_meta`。这说明：

```text
基础指令属于 session-level runtime metadata。
它不是普通 user/assistant history。
```

对我们：

```text
SoulProjection / PromptManifest 应进入 TaskRunLoop 的元数据和 checkpoint。
不要把灵魂投影只当字符串拼接。
```

### 3.2 Skill 是可加载的 prompt contract

本机 `C:/Users/admin/.codex/skills/*/SKILL.md` 显示：

```text
Skill 有 frontmatter:
  name
  description

正文定义:
  使用场景
  工作流
  约束
  输出合同
```

这和我们当前 `skill_system/contracts.py` / `soul projection` 的方向一致。

对我们：

```text
SkillPromptContract 应该是 PromptManifest 的 section source。
Skill 不能直接扩大 ResourcePolicy。
Skill 加载应记录到 RuntimeEventLog:
  SkillSelected
  SkillPromptSectionAttached
  SkillRuntimePolicyResolved
```

### 3.3 插件启用是 runtime capability，不应混入任务真相

本机配置里 documents / spreadsheets / presentations 插件启用。它们应类比为：

```text
CapabilityProvider
OperationDescriptor provider
Tool/Worker contract source
```

但对洪荒时代：

```text
插件启用只表示 capability 可发现。
是否能执行仍由 ResourcePolicy + OperationGate 决定。
```

---

## 4. Codex 架构对我们的直接启发

### 4.1 Event log 是第一真相，checkpoint 是恢复加速

我们之前偏向：

```text
TaskRun -> RuntimeCheckpoint
```

现在应升级为：

```text
TaskRunLoop
  -> RuntimeEventLog append-only
  -> RuntimeCheckpoint snapshot
  -> RuntimeStateIndex
```

原则：

```text
RuntimeEventLog 可 replay。
RuntimeCheckpoint 可快速恢复。
RuntimeStateIndex 可查询和列表。
三者互相校验，不互相替代。
```

### 4.2 Loop 是统一调度形态，但不吞并专业系统

Codex / Claude Code 都说明了一个事实：

```text
成熟 agent runtime 需要统一 loop。
没有统一 loop，工具、记忆、审批、压缩、恢复会散成多个互相猜测的分支。
```

因此洪荒时代不能只保留“分层系统”，还必须把分层系统装进一个统一调度循环。

新的边界应改为：

```text
OrchestrationSystem:
  唯一调度权。
  拥有 WorkflowPlan / ExecutionGraph / RuntimeStep progression。
  拥有 TaskRunLoop。

TaskRunLoop:
  编排系统内部的统一 agent loop。
  负责当前 TaskRun 的唯一推进。
  调用各专业系统，收集结果，写 RuntimeEventLog / RuntimeCheckpoint。

TaskSystem:
  定义 TaskContract。
  提供任务目标、约束、多 agent 需求。
  不自行推进任务。

OperationSystem:
  产出 OperationDescriptor / ResourcePolicy / OperationGateResult。
  对副作用有许可/否决权。
  不决定下一步跑什么。

SoulSystem:
  产出 StageProjection / PromptManifest。
  不决定流程。

MemorySystem:
  产出 ContextPackage / MemoryCandidate。
  不覆盖当前任务目标。

OutputBoundary:
  规范最终可见输出。

CommitGate:
  决定写回。
  不调度下一步。
```

这不是“权力平均分层”，而是：

```text
调度权集中在编排系统；
专业判断权保留在各系统；
TaskRunLoop 把它们统一串成一个可恢复循环。
```

### 4.3 ContextManager 必须成为正式系统

Codex 的 `ContextManager` 维护了：

```text
history items
history_version
token_info
reference_context_item
call/output pair invariants
image stripping
tool output truncation
rollback boundary
```

我们现在有：

```text
MemoryRuntimeView
ContextPolicyPreview
PromptManifest
```

但还缺：

```text
RuntimeContextManager
```

建议新增：

```text
backend/runtime/context_manager.py
```

职责：

```text
维护 model-visible history。
维护 ContextPackageRef。
维护 PromptManifestRef。
维护 tool/worker result pair invariants。
维护 token pressure。
执行 compaction decision。
产出 ContextSnapshotRef。
```

注意：

```text
MemorySystem 管记忆候选。
ContextManager 管本次 loop 的模型可见上下文。
二者不能混为一谈。
```

### 4.4 dynamic tools 对应我们的 operation runtime views

Codex state 里有 `thread_dynamic_tools`：

```text
name
description
input_schema
defer_loading
namespace
```

这和我们刚落地的：

```text
OperationDescriptor
ResourceRuntimeView
deferred_loading
always_load
input_contract_ref
```

高度一致。

建议：

```text
TaskRunLoop 每轮记录 OperationRuntimeViewSnapshot。
PromptManifest 只引用可见工具摘要。
真实执行仍走 OperationGate。
```

### 4.5 thread_spawn_edges 对应我们的 AgentSeat topology

Codex 本地 state 有：

```text
thread_spawn_edges(parent_thread_id, child_thread_id, status)
```

对我们对应：

```text
AgentSeatSpawnEdge
TaskRunSpawnEdge
```

但我们的多 agent 不能直接变成“线程 fork 自治”。应保持：

```text
TaskSystem 是多 agent 管理入口。
OrchestrationSystem 决定拓扑。
TaskRunLoop 记录 spawn edge。
子 agent 输出进入 ResultCandidate。
主 agent / final owner 归口最终答案。
```

### 4.6 agent_jobs 对应我们的批量任务/公司流程

Codex state 有 `agent_jobs` / `agent_job_items`，字段包括：

```text
instruction
output_schema_json
input_csv_path
output_csv_path
attempt_count
result_json
last_error
```

这非常适合我们未来：

```text
公司协作流程
批量内容处理
自主写作流程中的章节/素材 item
```

对应对象：

```text
TaskBatchRun
TaskRunItem
WorkflowItemState
```

第一阶段不实现，但 schema 应预留。

---

## 5. 推荐目标设计

### 5.1 新增核心对象

```text
TaskRunLoop
RuntimeEventLog
RuntimeCheckpoint
RuntimeStateIndex
RuntimeContextManager
RuntimeTurnContext
RuntimeLoopState
```

所有这些对象都应归属于：

```text
backend/orchestration/runtime_loop/*
```

架构归属必须明确：

```text
TaskRunLoop 属于编排系统，不属于 query，也不是独立第六套调度系统。
```

### 5.2 RuntimeEventLog

文件形态建议：

```text
backend/runtime-workflows/events/YYYY/MM/DD/taskrun-<id>.jsonl
```

每行：

```json
{
  "timestamp": "...",
  "task_run_id": "...",
  "turn_id": "...",
  "type": "runtime_event",
  "payload": {}
}
```

事件类型第一版：

```text
task_run_started
turn_context_captured
workflow_plan_adopted
runtime_step_started
stage_projection_built
context_package_built
runtime_directive_issued
operation_gate_checked
executor_started
executor_finished
result_candidate_created
output_boundary_applied
commit_gate_checked
checkpoint_written
task_run_completed
task_run_failed
```

### 5.3 RuntimeCheckpoint

文件形态建议：

```text
backend/runtime-workflows/checkpoints/<task_run_id>/latest.json
backend/runtime-workflows/checkpoints/<task_run_id>/<checkpoint_id>.json
```

内容：

```text
task_run_id
turn_id
workflow_plan_ref
execution_graph_ref
current_step_id
step_states
approval_state
context_snapshot_ref
prompt_manifest_ref
projection_ref
result_refs
commit_state
event_log_offset
created_at
```

### 5.4 RuntimeStateIndex

第一阶段可以用 JSONL index，后续可切 SQLite。

建议先做：

```text
backend/runtime-workflows/task_run_index.jsonl
```

字段：

```text
task_run_id
session_id
title
status
updated_at
event_log_path
latest_checkpoint_ref
model
reasoning_effort
approval_policy
sandbox_policy
```

后续 SQLite 表：

```text
task_runs
runtime_steps
runtime_events_index
task_run_spawn_edges
runtime_dynamic_operations
runtime_goals
batch_task_items
```

### 5.5 RuntimeContextManager

职责：

```text
record_model_visible_items
normalize_history
preserve_call_output_pairs
track_history_version
track_token_usage
truncate_large_outputs
build_context_package_ref
apply_compaction_result
rollback_turn_boundary
```

与已有系统关系：

```text
MemorySystem:
  提供 memory candidates。

ContextPolicy:
  选择 candidates 进入上下文。

RuntimeContextManager:
  维护 loop 内模型可见 history 和压缩/裁剪不变量。

PromptManifest:
  记录每个可见 prompt section 的来源。
```

---

## 6. 固定执行流

第一版 `TaskRunLoop` 固定流程应体现“统一 loop”：

```text
QueryAdapter
  -> TaskSystem.build_task_contract
  -> OrchestrationSystem.start_or_resume_task_run_loop
     -> append task_run_started
     -> capture RuntimeTurnContext
     -> append turn_context_captured
     -> adopt / load WorkflowPlan
     -> select next RuntimeStep
     -> build RuntimeStepState(model_response)
     -> call SoulSystem.build StageProjectionCycle
     -> call MemorySystem / ContextPolicy build ContextPackage
     -> call RuntimeContextManager build model-visible context
     -> issue RuntimeDirective from ExecutionGraph
     -> call OperationGate.check
     -> Executor.stream
     -> RuntimeContextManager.record_items
     -> call OutputBoundary.apply
     -> call CommitGate.check
     -> write RuntimeCheckpoint
     -> append checkpoint_written
     -> decide continue / wait / complete / fail
  -> QueryAdapter stream events
```

强约束：

```text
Executor 只能消费 RuntimeDirective。
OperationGate 必须发生在副作用前。
CommitGate 必须发生在写回前。
ContextManager 不能直接写 memory。
QueryAdapter 不拥有 loop 状态。
TaskSystem / MemorySystem / SoulSystem / OperationSystem 不自行推进 RuntimeStep。
只有 OrchestrationSystem.TaskRunLoop 可以推进当前 TaskRun。
```

---

## 7. 不照搬 Codex 的部分

```text
不照搬 Codex 的一体化 query/codex loop 文件结构。
不把 base_instructions 当作唯一 prompt 真相。
不让 loop 直接决定长期记忆写入。
不让 dynamic tools 自动获得执行权。
不让子线程/子 agent 默认继承完整父上下文。
不把 SQLite 当唯一恢复真相。
不只靠最终答案做持久化。
```

原因：

```text
洪荒时代的唯一调度权属于 OrchestrationSystem。
TaskRunLoop 是 OrchestrationSystem 的统一 loop，而不是旧 query 的复活。
其他系统保留专业边界，但必须由 loop 统一调用。
```

---

## 8. 分期实施建议

### Phase 1：落 RuntimeEventLog

新增：

```text
backend/orchestration/runtime_loop/events.py
backend/orchestration/runtime_loop/event_log.py
```

目标：

```text
当前 model-only lane 每次请求生成 taskrun event log。
不改变输出行为。
```

完成标准：

```text
有 task_run_started / turn_context_captured / operation_gate_checked / checkpoint_written。
JSONL 可读、可 replay。
```

### Phase 2：落 RuntimeCheckpoint

新增：

```text
backend/orchestration/runtime_loop/checkpoint.py
backend/orchestration/runtime_loop/store.py
```

目标：

```text
每次 model_response 完成后写 latest checkpoint。
checkpoint 记录 OperationGateResult、CommitGate 状态、PromptManifestRef。
```

### Phase 3：TaskRunLoop 包住 model-only lane

新增：

```text
backend/orchestration/runtime_loop/task_run_loop.py
backend/orchestration/runtime_loop/models.py
```

改造：

```text
backend/query/runtime.py
backend/execution/model_response.py
backend/runtime/agent_chain.py
```

目标：

```text
QueryRuntime 调 TaskRunLoop。
ModelResponseRuntimeExecutor 仍只执行 directive。
```

### Phase 4：RuntimeContextManager

新增：

```text
backend/orchestration/runtime_loop/context_manager.py
```

目标：

```text
把 history normalization、token pressure、call/output pair invariant 放进运行时。
```

### Phase 5：StateIndex

第一阶段：

```text
task_run_index.jsonl
```

第二阶段：

```text
runtime_workflow.sqlite
```

目标：

```text
支持列出、恢复、查找最近 TaskRun。
```

### Phase 6：read-only tool / worker 恢复

前置：

```text
RuntimeEventLog
RuntimeCheckpoint
RuntimeContextManager
OperationGatePipeline
ResultCandidate
```

目标：

```text
工具调用和输出进入 event log。
工具输出先变 ResultCandidate，不直接进 final answer。
```

---

## 9. 文件级落点

建议新建包：

```text
backend/orchestration/runtime_loop/
  __init__.py
  models.py
  events.py
  event_log.py
  checkpoint.py
  store.py
  task_run_loop.py
  context_manager.py
  state_index.py
```

现有文件接线：

```text
backend/query/runtime.py
  从调用 ModelResponseRuntimeExecutor，改为调用 TaskRunLoop。

backend/execution/model_response.py
  保持 directive-only executor，不拥有 TaskRunLoop。

backend/runtime/agent_chain.py
  短期继续 build preview，后续下沉到 Orchestration adoption。

backend/orchestration/runtime_directive.py
  RuntimeDirective 进入 RuntimeStepState。

backend/operations/gate.py
  OperationGateResult 写入 RuntimeEventLog / Checkpoint。

backend/output_boundary/*
  OutputBoundaryResult 写入 RuntimeEventLog。

backend/orchestration/commit_gate.py
  CommitGateResult 写入 RuntimeCheckpoint。
```

---

## 10. 最终建议

正式采用：

```text
Codex-style persisted loop
```

但在洪荒时代中命名和实现为：

```text
TaskRunLoop
```

设计口径：

```text
Event log 是事实轨迹。
Checkpoint 是恢复快照。
State index 是查询入口。
ContextManager 是模型可见历史治理。
TaskRunLoop 是编排系统内的统一 agent loop。
编排系统拥有唯一调度权。
各系统作为 loop 阶段服务被统一调用。
```

下一步最稳的实施顺序：

```text
1. 先实现 RuntimeEventLog + RuntimeCheckpoint。
2. 用 TaskRunLoop 包住当前 model-only lane。
3. 再补 RuntimeContextManager。
4. 最后恢复 read-only tool / worker。
```

这样，我们既学到了 Codex 的成熟循环架构，又不会把刚清理出来的系统边界重新揉成旧 query。
