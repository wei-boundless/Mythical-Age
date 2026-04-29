# AgentRuntime 任务导向持久化工作流初步计划书

日期：2026-04-30  
定位：本文件用于定义洪荒时代 AgentRuntime 的自有持久化工作流内核初步计划。它不是全自研框架宣言，也不是选择某个外部框架的选型报告，而是基于当前任务系统、操作系统、灵魂系统、记忆系统、编排系统的分层结构，设计一套任务导向、可恢复、可扩展到多 agent 协作的 RuntimeWorkflow。

---

## 0. 总结论

洪荒时代不应该建设强自治、强自驱、无限循环的 agent，而应该建设：

```text
任务导向的智能体工作流运行时。
```

它的基本单位不是 query，也不是 agent 自己的一轮思考，而是：

```text
TaskRun
  -> WorkflowPlan
  -> ExecutionGraph
  -> RuntimeStep / RuntimeDirective
  -> ResultArtifact / ResultCandidate
  -> CommitPlan
  -> Checkpoint / Trace
```

核心判断：

```text
Agent 层级决定工作流如何触发。
TaskSystem 决定任务是什么。
OrchestrationSystem 决定任务如何推进。
RuntimeWorkflow 负责持久推进和恢复。
OperationSystem 控制资源和权限。
MemorySystem 提供上下文和隔离记忆。
CommitGate 控制阶段成果、最终交付和记忆写回。
```

一句话：

```text
Agent 是任务执行席位，不是系统主权者。
Workflow 是任务运行真相，不是 query loop。
```

---

## 1. 为什么从 Agent 层级触发工作流

我们当前已经有清晰的 agent 层级口径：

```text
Soul 不是 Agent。
AgentProfile 是任务身份。
Agent + Projection 是任务执行席位。
Skill / Tool / Worker 是执行资源。
TaskSystem 是多 agent 协作管理入口。
ControlKernel / OrchestrationSystem 是执行图和当前轮真相。
```

因此持久化工作流不应该从“模型想调用工具”开始，也不应该从旧 query 入口开始，而应该从 agent 层级触发：

```text
UserRequest / SystemEvent
  -> TaskSystem 创建 TaskContract
  -> TaskAgentRequirement 选择 agent 层级
  -> AgentSeatPlan 生成执行席位
  -> OrchestrationSystem 生成 WorkflowPlan
  -> RuntimeWorkflow 开始或恢复 TaskRun
```

这样可以保证：

```text
1. 单 agent 和多 agent 是同一个体系。
2. 多 agent 是任务拓扑扩展，不是自治 agent 群聊。
3. agent 的权限、记忆、输出边界可以提前约束。
4. 后续写作流程、公司协作流程可以被建模成 workflow，而不是 prompt 分支。
```

---

## 2. Agent 层级模型

### 2.1 层级定义

第一版建议定义四个层级：

```text
L0 User / External Trigger
  用户请求、系统事件、定时任务、外部 webhook。

L1 MainAgent
  当前会话主 agent，负责承接用户、归口最终答案、发起 TaskRun。

L2 TaskAgent / RoleAgent
  某个任务阶段的角色 agent，例如 researcher、writer、editor、critic、planner。

L3 Worker / Tool / Service
  确定性工具、检索 worker、PDF worker、模型响应 executor、外部服务。
```

注意：

```text
Worker 不是 Agent。
Tool 不是 Agent。
Soul 不是 Agent。
AgentProfile 不能直接执行。
```

### 2.2 AgentSeat

`AgentSeat` 是工作流中的执行席位，不等于长期存在的“人格实例”。

建议字段：

```text
AgentSeat:
  seat_id
  agent_profile_ref
  soul_projection_ref
  task_scope
  memory_scope
  resource_policy_ref
  allowed_operation_refs
  output_contract_ref
  parent_seat_id
  lifecycle
```

生命周期：

```text
candidate
adopted
active
waiting
completed
failed
cancelled
archived
```

约束：

```text
AgentSeat 只能在 ExecutionGraph 中被调度。
AgentSeat 不能绕过 OperationGate 执行工具。
AgentSeat 不能直接写 durable memory。
AgentSeat 的输出必须进入 ResultCandidate / ResultArtifact。
```

### 2.3 Agent 层级触发规则

不同层级触发不同工作流粒度：

| 触发层级 | 触发对象 | 工作流粒度 | 示例 |
| --- | --- | --- | --- |
| User / SystemEvent | TaskRun | 完整任务运行 | 写作项目、公司流程、长文分析 |
| MainAgent | WorkflowPlan | 当前任务流程 | 主 agent 判断需要 research + write + edit |
| TaskAgent | RuntimeStep | 阶段执行 | writer 写一章，editor 校对 |
| Worker / Tool | RuntimeDirective | 单一动作 | PDF 读取、检索、模型回答 |

禁止：

```text
TaskAgent 不能自行创建顶层 TaskRun。
Worker / Tool 不能自行创建 WorkflowPlan。
Memory restore 不能触发工作流，只能提供候选。
旧 query 不能触发工作流决策，只能转交请求。
```

---

## 3. RuntimeWorkflow 的核心对象

### 3.1 TaskRun

`TaskRun` 是一次任务运行实例。

建议字段：

```text
TaskRun:
  schema_version
  task_run_id
  task_contract_ref
  session_id
  owner_agent_seat_id
  trigger
  task_family
  task_mode
  status
  workflow_plan_ref
  execution_graph_ref
  checkpoint_ref
  created_at
  updated_at
```

状态：

```text
created
planned
running
waiting_approval
blocked
completed
failed
cancelled
archived
```

### 3.2 WorkflowPlan

`WorkflowPlan` 是任务级流程计划，不直接执行。

建议字段：

```text
WorkflowPlan:
  plan_id
  task_run_id
  topology
  agent_seat_plan_ref
  stage_plan
  resource_policy_refs
  memory_policy_refs
  output_policy_ref
  approval_policy_ref
  resume_policy_ref
  idempotency_policy_ref
  authority
```

拓扑第一版：

```text
single_agent
sequential
parallel_fanout
loop_review
human_approval
```

当前阶段只实现：

```text
single_agent
```

### 3.3 RuntimeStep

`RuntimeStep` 是 ExecutionGraph 中可恢复的最小阶段。

建议字段：

```text
RuntimeStep:
  step_id
  task_run_id
  node_id
  agent_seat_id
  directive_ref
  input_refs
  output_refs
  status
  retry_policy_ref
  idempotency_key
  started_at
  ended_at
```

状态：

```text
pending
ready
running
waiting_approval
completed
blocked
failed
skipped
cancelled
```

### 3.4 RuntimeDirective

`RuntimeDirective` 是执行层唯一能消费的命令。

第一版 executor 类型：

```text
model
tool
worker
agent
commit
approval
```

当前已开放：

```text
model-only lane
```

后续逐步开放：

```text
read-only tool
worker
bounded agent
commit applier
```

### 3.5 RuntimeCheckpoint

`RuntimeCheckpoint` 是持久化恢复真相。

建议字段：

```text
RuntimeCheckpoint:
  schema_version
  checkpoint_id
  task_run_id
  turn_id
  workflow_plan_ref
  execution_graph_ref
  current_step_id
  step_states
  directive_states
  result_refs
  pending_approvals
  commit_state
  memory_state_refs
  context_state_refs
  trace_ref
  created_at
```

最低要求：

```text
每个 RuntimeStep 完成后 checkpoint。
每个副作用执行前后 checkpoint。
每次 waiting_approval 前 checkpoint。
每次 CommitGate 决策前后 checkpoint。
```

### 3.6 ResultArtifact / ResultCandidate

`ResultCandidate` 是执行结果候选，`ResultArtifact` 是可引用产物。

示例：

```text
model_output_candidate
tool_result_candidate
worker_result_candidate
agent_result_candidate
draft_artifact
review_artifact
final_answer_candidate
memory_write_candidate
```

约束：

```text
ResultCandidate 不能自动成为 final answer。
ResultArtifact 只能通过 ref 进入上下文。
CommitGate 决定结果是否写回 session / memory / artifact store。
```

---

## 4. 工作流触发路径

### 4.1 普通对话 / 单主 agent

```text
UserRequest
  -> QueryAdapter
  -> TaskSystem.create(TaskContract)
  -> MainAgentSeat candidate
  -> OrchestrationSystem.plan(single_agent)
  -> RuntimeWorkflow.start(TaskRun)
  -> RuntimeStep(model_response)
  -> OutputBoundary
  -> CommitGate(blocked / allowed)
  -> Checkpoint
```

当前阶段落地目标：

```text
把已有 model-only lane 纳入 TaskRun / RuntimeCheckpoint。
不改变模型回答行为。
不开放工具写入。
```

### 4.2 自主写作流程

示例流程：

```text
WritingTask
  -> planner seat：拆章节与标准
  -> researcher seat：资料收集
  -> writer seat：分章节草稿
  -> editor seat：统一风格和结构
  -> critic seat：质量审查
  -> main agent：最终归口交付
```

映射：

```text
TaskSystem:
  task_family = writing
  task_mode = workflow

WorkflowPlan:
  topology = sequential + loop_review

AgentSeat:
  planner / researcher / writer / editor / critic

CommitGate:
  阶段 draft artifact 可写入 artifact store
  final answer 由 main agent 归口
  durable memory write 默认候选，不自动写入
```

第一阶段不实现完整写作流，只把 topology 和对象预留好。

### 4.3 公司协作流程

示例流程：

```text
BusinessWorkflowTask
  -> intake seat：需求归档
  -> analyst seat：背景分析
  -> operator seat：执行建议
  -> reviewer seat：审批或风险检查
  -> reporter seat：汇报总结
```

关键要求：

```text
每个角色有独立 memory scope。
每个阶段有明确输入输出合同。
审批节点必须 waiting_approval。
外部系统副作用必须 OperationGate + idempotency_key。
```

---

## 5. 持久化策略

### 5.1 第一阶段存储

第一阶段建议使用轻量本地持久化：

```text
backend/runtime-workflows/
  task_runs/
  checkpoints/
  traces/
  artifacts/
```

或用 SQLite：

```text
runtime_workflow.db
  task_runs
  workflow_plans
  runtime_steps
  checkpoints
  runtime_events
  artifacts
```

初步建议：

```text
先用 JSON 文件实现最小可读性。
如果步骤状态查询和恢复变复杂，再切 SQLite。
```

### 5.2 后续可替换承载

成熟框架作为可替换承载：

```text
LangGraph:
  graph / checkpoint / interrupt。

DBOS:
  workflow / step / durable sleep / queue。

Temporal:
  长任务 / 强恢复 / signal / activity retry。
```

但无论接谁：

```text
RuntimeWorkflow 合同不变。
TaskSystem / OperationSystem / MemorySystem / CommitGate 主权不变。
```

---

## 6. 恢复策略

恢复不是重新理解用户请求，也不是重跑所有步骤。

恢复流程：

```text
load TaskRun
load latest RuntimeCheckpoint
validate schema_version
validate ExecutionGraph ref
validate completed step outputs
validate pending approvals
resume from first unfinished safe step
```

重试规则：

```text
model step 可重试。
read-only tool step 可按策略重试。
worker step 必须检查 idempotency_key。
write / send / memory commit step 默认不可自动重放。
CommitGate step 必须读取 commit_state。
```

恢复禁止：

```text
不能让 Memory restore 改写当前 TaskRun。
不能让模型重新决定已经 adopted 的 WorkflowPlan。
不能重复执行已 completed 的副作用 step。
不能跳过 waiting_approval。
```

---

## 7. 与现有系统的关系

### 7.1 TaskSystem

新增职责：

```text
创建 TaskRun seed。
提供 TaskAgentRequirement。
定义任务阶段和输出合同。
成为多 agent 协作管理入口。
```

不新增职责：

```text
不执行 workflow。
不写结果。
不直接调用 agent。
```

### 7.2 OperationSystem

新增职责：

```text
为每个 RuntimeDirective 生成 adopted ResourcePolicy。
提供 OperationGatePipeline。
提供 idempotency / risk / approval 信息。
```

不新增职责：

```text
不决定任务目标。
不决定工作流拓扑。
```

### 7.3 SoulSystem

新增职责：

```text
为 AgentSeat 提供 SoulProjection。
为多角色任务提供不同投影姿态。
生成 PromptManifest section refs。
```

不新增职责：

```text
不扩大权限。
不决定执行步骤。
```

### 7.4 MemorySystem

新增职责：

```text
提供 AgentMemoryScope。
为 TaskRun 提供 ContextPackage。
为不同 AgentSeat 提供隔离记忆视图。
生成 MemoryWriteCandidate。
```

不新增职责：

```text
不覆盖当前任务目标。
不自动写长期记忆。
不在子 agent 间共享可变 StateMemory。
```

### 7.5 OrchestrationSystem

新增职责：

```text
拥有 WorkflowPlan。
拥有 RuntimeWorkflow 状态推进。
把 TaskAgentRequirement 变成 AgentSeatPlan。
把 AgentSeatPlan 变成 ExecutionGraph。
```

不新增职责：

```text
不直接执行工具。
不直接写 memory。
不直接生成最终答案文本。
```

### 7.6 QueryAdapter

保持：

```text
API 输入。
事件流输出。
调用 RuntimeWorkflow / AgentRuntime。
错误包装。
```

禁止：

```text
不恢复 planner。
不决定 agent 拓扑。
不执行工具。
不写 session。
```

---

## 8. 分期计划

### Phase 0：冻结合同

目标：

```text
完成 TaskRun / WorkflowPlan / RuntimeStep / RuntimeCheckpoint / AgentSeat 数据合同。
```

输出：

```text
backend/orchestration/runtime_workflow_models.py
docs/系统规划/04-AgentRuntime任务导向持久化工作流设计-20260430.md 定稿
```

完成标准：

```text
合同能表达 single_agent。
合同能预留 sequential / parallel_fanout / loop_review。
合同明确 idempotency / checkpoint / approval。
```

### Phase 1：接管 model-only lane

目标：

```text
把当前 model-only 真实链路包进 TaskRun + RuntimeCheckpoint。
```

涉及：

```text
backend/runtime/agent_chain.py
backend/execution/model_response.py
backend/orchestration/runtime_directive.py
backend/orchestration/commit_gate.py
backend/query/runtime.py
```

完成标准：

```text
每次用户请求生成 TaskRun。
model_response step 有 RuntimeStepState。
模型输出后写 checkpoint。
CommitGate blocked 状态写 checkpoint。
query 仍只做 adapter。
```

### Phase 2：OperationGatePipeline 与 read-only tool

目标：

```text
恢复最小只读工具 step。
```

范围：

```text
read-only file/search/info 工具。
禁止 shell 写入。
禁止外部发送。
禁止 memory write。
```

完成标准：

```text
RuntimeDirective(tool) 必须有 adopted ResourcePolicy。
OperationGatePipeline deny-first。
tool result 进入 ResultCandidate。
不直接成为 final answer。
```

### Phase 3：WorkerExecutor 接入

目标：

```text
把 PDF / retrieval / evidence worker 作为 RuntimeStep 接入。
```

完成标准：

```text
WorkerResult 生成 ResultArtifact ref。
上下文只消费 artifact summary/ref，不塞原始大文本。
失败可恢复，不重复副作用。
```

### Phase 4：CommitGate 放行 session projection

目标：

```text
让部分低风险输出可以写 session projection。
```

范围：

```text
assistant response projection
task run summary
artifact refs
```

仍不自动：

```text
durable memory write
外部系统写入
文件写入
```

### Phase 5：多 AgentSeat 拓扑预览

目标：

```text
实现多 agent 拓扑的 preview 和 dry-run。
```

范围：

```text
sequential writing workflow preview
parallel research fanout preview
review loop preview
```

完成标准：

```text
TaskSystem 能产生 TaskAgentRequirement。
OrchestrationSystem 能生成 AgentSeatPlan。
MemorySystem 能生成 per-seat MemoryScope preview。
不开放真实子 agent 执行。
```

### Phase 6：BoundedAgentExecutor

目标：

```text
开放受控子 agent 执行。
```

前置条件：

```text
AgentSeat 合同稳定。
per-seat memory scope 稳定。
subagent output contract 稳定。
递归深度和生命周期保护稳定。
CommitGate 能归口结果。
```

---

## 9. 关键风险

### 9.1 RuntimeWorkflow 变成新 query 大脑

风险：

```text
如果 RuntimeWorkflow 开始理解任务、授权资源、写记忆，它就会变成旧 query 的新名字。
```

控制：

```text
RuntimeWorkflow 只推进状态、checkpoint、resume。
决策来自 OrchestrationPlan。
授权来自 OperationGate。
写回来自 CommitGate。
```

### 9.2 过早做多 agent

风险：

```text
多 agent 拓扑会把记忆、权限、输出归口复杂度放大。
```

控制：

```text
先 single_agent。
多 agent 先 preview / dry-run。
真实子 agent 等 MemoryScope / CommitGate 稳定后再放行。
```

### 9.3 副作用重复执行

风险：

```text
恢复或重试时重复写文件、发消息、写 memory。
```

控制：

```text
所有副作用 step 必须有 idempotency_key。
副作用执行前后 checkpoint。
CommitGate step 不自动重放。
```

### 9.4 状态模型过重

风险：

```text
为了未来扩展，一开始设计过度复杂。
```

控制：

```text
第一阶段只落 single_agent + model-only。
其他 topology 只保留枚举和 preview 字段。
```

---

## 10. 第一版文件落点建议

新增：

```text
backend/orchestration/runtime_workflow_models.py
backend/orchestration/runtime_workflow.py
backend/orchestration/checkpoints.py
backend/orchestration/task_runs.py
backend/orchestration/agent_seats.py
```

暂缓：

```text
backend/orchestration/langgraph_adapter.py
backend/orchestration/dbos_adapter.py
backend/orchestration/temporal_adapter.py
```

原因：

```text
先稳定自有合同，再接外部承载。
```

---

## 11. 初步完成定义

本计划第一轮完成，不代表完整多智能体系统完成。

第一轮完成标准：

```text
1. 每次真实请求都有 TaskRun。
2. model-only lane 被 RuntimeStep 包住。
3. 每次 step 结束都有 checkpoint。
4. CommitGate blocked / allowed 状态可追踪。
5. query 仍保持 adapter。
6. 所有副作用仍 fail-closed。
7. 多 agent 只作为 AgentSeatPlan preview 存在。
```

成熟完成标准：

```text
1. single_agent / sequential / fanout / review loop 都可表达。
2. model / tool / worker / bounded agent 都可作为 RuntimeDirective 执行。
3. 每个执行步骤可恢复。
4. 每个副作用有幂等保护。
5. 每个 AgentSeat 有独立 memory scope 和 resource policy。
6. CommitGate 统一写回 session / artifact / memory。
7. 多 agent 结果由主 agent 或 final_owner 归口。
```

---

## 12. 本文件的最终口径

```text
洪荒时代要做的是任务导向持久化工作流，
不是强自治 agent，
不是旧 query loop，
也不是被某个外部框架接管。

我们的核心是：
  由 Agent 层级触发，
  由 TaskSystem 定义任务，
  由 OrchestrationSystem 规划流程，
  由 RuntimeWorkflow 持久推进，
  由 OperationGate 控制副作用，
  由 CommitGate 统一写回。
```

