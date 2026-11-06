# 任务框架稳定定义与 Agent/System 对接契约

状态：框架定义锁定稿，待审阅后实施  
日期：2026-07-04  
前置文档：`17_task_graph_runtime_interface_detail_alignment.md`、`18_task_environment_runtime_mechanics_plan.md`

## 1. 定义目标

本文只解决一个问题：什么才叫本项目里的 `Task`，以及 agent 和系统如何共同推动任务进行。

前面文档已经说明：

```text
Task 不是普通 turn。
Task 不是一个函数。
Task 不是一个大 todo。
Task 不是 GraphNode。
Task 不是 TaskRun。
Task 不是 assistant message。
```

本文把任务框架稳定定义为：

```text
Task = 一个由系统持久化管理的工作环境。
它承载 agent 围绕独立目标进行可恢复、可审计、可归并产物的持续工作。
```

### 1.1 TaskWorkEnvironment 的硬定义

`TaskWorkEnvironment` 不是任务目标本身，不是 agent，不是 session，也不是 GraphNode。

它是系统为一个任务建立的持久工作现场：

```text
Task = 要完成的目标
TaskWorkEnvironment = 这个目标正在被执行时的持久工作现场
AgentExecutionEpisode = agent 在任务环境中的一次执行片段
Session = 用户与系统交互的入口窗口
GraphNodeWorkOrder = 图系统发出的节点调度请求
Harness = 唯一单 agent 执行 runtime
```

任务环境存在的必要性来自普通 turn 的天然缺陷。普通 turn 只能表达当前一轮对话，不能稳定回答：

- 这个任务做到哪一步；
- 当前是否有 agent 正在执行；
- 中断后从哪里恢复；
- 哪些产物已经交付，哪些只是候选；
- 哪些证据、文件、AST、graph binding 与当前任务相关；
- 当前应该由用户、GraphSystem、Harness、TaskReducer 还是维护任务来接手。

因此任务环境的工程职责是：

```text
把一次性对话升级为可追踪、可恢复、可审计、可继续推进的任务运行现场。
```

它必须承载：

| 承载对象 | 作用 |
| --- | --- |
| 任务身份 | 目标、范围、验收、所属项目、绑定 session / graph run |
| 运行状态 | ready / leased / paused / blocked / completed 等生命周期投影 |
| 上下文包 | agent 本次 episode 需要的 stable context、current context、refs 和资源边界 |
| 执行片段 | 每次 agent 执行的 AgentExecutionEpisode，不把 episode 当成任务本身 |
| 产物 | WorkProduct candidate / accepted / repair-needed，不把 assistant final answer 当唯一产物 |
| 控制信号 | pause / resume / replan / abort 等可审计控制意图和处理回执 |
| 恢复锚点 | checkpoint、continuation hint、blocked reason、latest context package |
| 查询投影 | 给 UI、session、graph、维护任务读取的任务进度视图 |

核心裁决：

```text
任务环境是承载层，不是执行权威。
```

权威分工必须保持：

```text
TaskSystem 记录任务环境、事件、episode、work product、control signal。
GraphSystem 决定图结构、节点 ready、dispatch、requeue、checkpoint。
Harness 执行单 agent episode。
Agent 做语义判断、提出计划、执行工具、提交产物候选。
ProjectNetworkSystem 保存项目控制网络资产。
FileManagement 提供文件树、AST、物理事实和资源引用。
```

设计成熟度的判断标准是：任务环境应该像一个持久工位，保存任务资料、当前进度、交付物、暂停原因和恢复入口；但真正工作的是 agent，调度复杂流程的是 GraphSystem，长期项目资产由 ProjectNetworkSystem 维护。

一句话：

```text
TaskWorkEnvironment = 持久工作现场 + 状态账本 + 恢复锚点。
它让 agent 不靠记忆硬扛任务连续性，让系统不靠聊天记录猜任务状态。
```

## 2. 任务的要素

### 2.1 最小成立要素

一个任务要成立，至少必须具备六个要素：

| 要素 | 定义 | 缺失后果 |
| --- | --- | --- |
| 目标 | 这项工作最终要达成什么 | 退化成普通聊天或临时行动 |
| 范围 | 做哪些对象，不做哪些对象 | agent 会扩散、误读、越界 |
| 验收 | 什么条件下算完成 | 无法判断任务是否结束 |
| 状态 | 当前处于哪个生命周期阶段 | 无法持续推进或恢复 |
| 上下文 | 继续任务必须知道的事实和引用 | 只能靠 session transcript 猜 |
| 产物要求 | 任务必须交付什么 WorkProduct | 后续系统无法消费 |

没有这六项，系统不应该创建任务环境。它只能是普通 turn、临时计划、工具调用、用户问题或 agent 自己的短期注意力。

### 2.2 完整任务要素

成熟任务框架的完整要素如下：

```text
Task
  goal
  scope
  acceptance
  lifecycle_state
  context
  resources
  plan
  todo
  execution_episodes
  evidence
  work_products
  controls
  recovery
  relations
  authority_boundary
```

| 要素 | 说明 | canonical owner |
| --- | --- | --- |
| `goal` | 用户或图任务真正要求完成的目标 | TaskInstance |
| `scope` | 文件、项目、图节点、业务对象、排除范围 | TaskWorkEnvironment |
| `acceptance` | 完成标准、质量标准、产物标准 | TaskInstance / TaskContract |
| `lifecycle_state` | created / ready / leased / paused / blocked / completed / archived | TaskWorkEnvironment |
| `context` | stable context、current context、memory refs、artifact refs、graph context | TaskContextPackage |
| `resources` | 文件、工具、权限、记忆、artifact、项目网络入口 | TaskWorkEnvironment |
| `plan` | 任务内的阶段路线和策略版本 | TaskPlan |
| `todo` | 任务内的当前行动队列和注意力游标 | TaskTodoList |
| `execution_episodes` | agent 进入任务环境的一次次执行片段 | AgentExecutionEpisode |
| `evidence` | 文件切片、AST ref、工具观察、证据 artifact | Evidence / Artifact refs |
| `work_products` | 结构化产物、报告、索引、NodeResultEnvelope 来源 | WorkProduct |
| `controls` | pause / stop / resume / abort / approval / replan | TaskControlSignal |
| `recovery` | checkpoint、continuation hint、blocked reason、dead letter | Checkpoint / TaskDeadLetter |
| `relations` | session、graph node、project、parent/child、repair_of | Binding records |
| `authority_boundary` | 谁能改状态、谁能执行、谁能归并、谁能发布 | TaskSystem policy |

## 3. Plan 和 Todo 的归属

### 3.1 核心裁决

`Plan` 和 `Todo` 必须纳入任务管理体系，但它们不能等同于任务。

```text
Task = 工作环境。
Plan = 任务内的策略路线。
Todo = 任务内的当前行动队列。
Episode = agent 执行 plan/todo 的一次工作片段。
WorkProduct = 执行后留下的可消费产物。
```

如果把 task 做成 todo，任务系统会退化成清单工具。  
如果把 plan 做成 graph，图任务系统会被 agent 的临时策略污染。  
如果把 todo 做成 task，每个动作都会变成持久任务，系统会碎片化。

### 3.2 TaskPlan

`TaskPlan` 是任务内的版本化策略。

```text
TaskPlan
  plan_id
  task_environment_id
  version
  status: proposed | active | revised | superseded | completed
  strategy_summary
  phases
  acceptance_mapping
  risk_notes
  created_by_episode_id
  supersedes_plan_id
  updated_at
```

规则：

- agent 可以提出 plan；
- system 负责保存 plan、版本化 plan、把 active plan 投影给后续 episode；
- plan 可以变更，但必须产生 `plan_revised` event；
- 重要任务只能有一个 active plan；
- 被替换的 plan 进入 `superseded`，不能静默覆盖；
- plan 不直接推进任务状态，必须通过 episode result 和 reducer 推进。

### 3.3 TaskTodoList

`TaskTodoList` 是任务内的当前行动队列。

```text
TaskTodoItem
  todo_id
  task_environment_id
  plan_id
  title
  status: pending | active | blocked | done | canceled
  evidence_refs
  blocker
  created_by_episode_id
  completed_by_episode_id
  updated_at
```

规则：

- todo 是执行焦点，不是任务真相；
- todo 完成不代表任务完成；
- todo 可以由 agent 更新，但必须通过系统事件保存；
- active todo 进入 `current_context / volatile_tail`；
- completed todo 只保留摘要或 ref，不反复塞进上下文；
- blocked todo 进入 `blocked_reason` 和 recovery hint；
- todo 不应该成为 graph node，除非它被显式提升为图任务节点。

### 3.4 Plan/Todo 与上下文

| 内容 | 上下文位置 |
| --- | --- |
| active plan 摘要 | stable context 或 plan ref |
| active todo | current context / volatile tail |
| completed todos | refs / history summary |
| blocked todo | blocked_reason / recovery hint |
| plan 全文 | ref，不默认塞入 prompt |
| todo 全列表 | 只在任务管理 UI 或必要恢复时展示 |

## 4. Agent 与系统的职责分工

### 4.1 Agent 负责什么

Agent 是任务环境里的智能执行体。

Agent 负责：

- 判断当前工作是否需要任务环境；
- 提出任务目标、范围、验收、最小下一步；
- 阅读 TaskContextPackage；
- 制定或修订 TaskPlan；
- 选择当前 TaskTodoItem；
- 使用工具获取证据；
- 做语义判断；
- 产出 EpisodeResult；
- 产出 WorkProduct candidate；
- 在不确定时提出 blocker、question、repair need；
- 在暂停时给出 checkpoint summary 和 continuation hint。

Agent 不负责：

- 直接改 TaskWorkEnvironment canonical state；
- 直接发布 project network generation；
- 直接推进 GraphLoop；
- 直接覆盖 WorkProduct accepted/published 状态；
- 伪造 physical ref；
- 绕过 lease 执行任务；
- 靠 session transcript 恢复任务真相。

### 4.2 System 负责什么

System 是任务环境的管理者和执行边界。

System 负责：

- 创建 TaskInstance / TaskWorkEnvironment；
- 校验任务契约是否足够；
- 持久化状态、事件、plan、todo、episode、work product；
- 建立 TaskContextPackage；
- 分配 lease；
- 控制 tool/model/action admission；
- 写 checkpoint；
- 处理 pause / stop / resume / abort；
- 调用 harness 执行 agent episode；
- 调用 reducer 归并 EpisodeResult；
- 投影 NodeResultEnvelope；
- 查询、恢复、审计和修复任务。

System 不负责：

- 替 agent 做语义判断；
- 根据关键词自动把普通 turn 升级成任务；
- 从自然语言报告反解析结构事实；
- 让旧 task_executor 继续作为第二模型 loop；
- 用兼容名义保留旧任务主链。

## 5. Agent/System 推动任务的固定协议

任务推进不是 agent 自己写数据库，也不是系统自己猜下一步。正确协议是：

```text
agent proposes
-> system validates and persists
-> system provides context and lease
-> agent executes through harness
-> agent returns structured result
-> system reduces and advances state
```

### 5.1 Admission：任务是否成立

入口：

```text
agent emits request_task_run
```

agent 必须提供：

```text
goal
scope
acceptance
durable_reason
minimum_next_step
expected_work_products
```

system 校验：

- 目标是否明确；
- 范围是否可执行；
- 验收是否能判断完成；
- 是否真的需要持久环境；
- 是否有产物或恢复需求；
- 是否与普通 turn 边界冲突。

输出：

```text
accepted -> create TaskInstance + TaskWorkEnvironment + SessionTaskBinding
needs_clarification -> ask_user
rejected -> stay ordinary turn
```

### 5.2 Planning：计划如何进入任务

agent 可以在 episode 中提出：

```text
TaskPlanProposal
TaskTodoPatch
```

system 处理：

```text
validate plan shape
append task_event(plan_proposed / plan_revised)
write TaskPlan
update active_plan_id
project active plan summary into future TaskContextPackage
```

agent 不直接覆盖 plan，只提交 proposal。

### 5.3 Dispatch：系统如何让 agent 开始工作

系统推进一次 episode：

```text
recover_stale_leases()
-> acquire TaskEnvironmentLease
-> create AgentExecutionEpisode
-> build TaskContextPackage
-> compile task episode packet
-> run through harness
```

系统给 agent 的不是“任务数据库”，而是经过裁剪的上下文包：

```text
role_contract
goal
scope
acceptance
active_plan_summary
active_todo
current_state
evidence refs
resource refs
tool scope
graph context
continuation hint
```

### 5.4 Execution：agent 如何推动任务

agent 在 episode 内通过标准 action protocol 行动：

```text
tool_call
respond / structured_result
ask_user
pause_for_user_steer
block
request_task_run
```

任务环境下的 agent 输出必须形成 `EpisodeResult`：

```text
EpisodeResult
  status
  summary
  work_product_candidates
  state_update_proposals
  plan_patch
  todo_patch
  memory_candidates
  artifact_refs
  blocker
  continuation_hint
```

### 5.5 Reduction：系统如何推进任务状态

episode 结束后，系统进入 reducer：

```text
validate episode owns active lease
validate state update proposal
upsert WorkProduct candidates
apply plan/todo patches
append task_events
update TaskWorkEnvironment snapshot
write checkpoint
release lease
if graph-bound: project NodeResultEnvelope
```

关键点：

- agent 提 proposal；
- reducer 做归并；
- TaskWorkEnvironment 才改变状态；
- WorkProduct 进入 store；
- GraphLoop 只消费 NodeResultEnvelope。

### 5.6 Control：暂停、停止、恢复如何对接

控制信号固定走系统：

```text
session/user/graph/API
-> TaskControlSignal
-> active episode polls signal
-> agent reaches safe boundary
-> system writes checkpoint and state
```

pause：

```text
agent 必须给 checkpoint_summary + continuation_hint
system release lease
env.status = paused
```

stop：

```text
system requests stop
episode writes stop boundary if possible
env.status = blocked / aborted
```

resume：

```text
system rebuilds TaskContextPackage
agent 不恢复旧 provider stream
episode 从 durable boundary 继续
```

## 6. Session 与 Task 的关系

`Session` 不拥有 `Task`。  
`Session` 通过 `SessionTaskBinding` 看见和控制 task。

```text
Session = 对话连续性和用户入口
Task = 工作连续性和任务真相
SessionTaskBinding = 二者之间的显式关系
```

`SessionTaskBinding`：

```text
binding_id
session_id
task_environment_id
task_instance_id
binding_kind: origin | foreground | continuation | reference | graph_node_view
control_role: viewer | controller | owner
visibility: foreground | background | archived
created_from_turn_id
last_focused_at
last_user_steer_ref
status
```

规则：

- 一个 session 可以引用多个 task；
- 一个 task 可以被多个 session 继续；
- 一个 session 同时只能有一个 foreground active task；
- graph node task 可以没有普通用户 session；
- 继续任务时优先显式 task id，其次 foreground binding；
- 多个候选时必须问用户，不能靠聊天历史猜。

## 7. Graph 与 Task 的关系

`GraphSystem` 调度复杂任务，但不执行模型，不保存领域语义资产。

```text
GraphNodeWorkOrder
-> GraphNodeTaskBinding
-> TaskWorkEnvironment
-> AgentExecutionEpisode
-> WorkProduct
-> NodeResultEnvelope
-> GraphLoop.accept_node_result()
```

规则：

- graph node 必须通过 TaskWorkEnvironment 承载 agent 工作；
- graph node 的 plan/todo 是节点任务环境内部对象；
- GraphLoop 只接收 NodeResultEnvelope；
- project_network_system 只接收 WorkProduct / generation，不接收 graph 内部临时状态。

## 8. 项目控制网络中的任务框架

项目控制网络是长期资产系统。语义网络的建立由图任务审查生产线完成。

```text
file_management physical skeleton
-> project_network_tasks build graph
-> graph_system dispatch review nodes
-> each node gets TaskWorkEnvironment
-> agent produces WorkProduct candidates
-> reducer / curator
-> project_network_system generation
```

任务框架在这里提供：

- 每个文件审查节点的独立工作环境；
- 每个目录汇总节点的独立计划、todo、episode 和产物；
- 每层结果可恢复、可归并、可审计；
- git delta 后可生成 repair task；
- candidate / accepted / published 分层。

## 9. 不变量

```text
Task 是持久工作环境。
Plan 是任务内策略，不是 task。
Todo 是任务内行动队列，不是 task。
Episode 是一次 agent 工作片段，不是 task。
WorkProduct 是可消费产物，不是 assistant message。
Session 是用户入口，不是 task owner。
GraphNodeWorkOrder 是调度请求，不是 agent execution。
TaskReducer 是状态归并权威。
TaskWorkEnvironment 是任务真相。
```

## 10. 严禁反模式

1. 把普通复杂 turn 自动升级成 task。
2. 把 task 做成 todo list。
3. 把 plan 做成 graph scheduler。
4. 把 todo 做成 graph node。
5. 让 agent 直接改 task state。
6. 让 session transcript 成为 task truth。
7. 让 assistant final answer 成为唯一 WorkProduct。
8. 让 GraphLoop 执行模型。
9. 让 project_network_system 调度 agent 审查。
10. 没有 lease 就执行 episode。
11. 没有 checkpoint 就暂停。
12. 没有 reducer 就推进任务状态。

## 11. 最终定义

本项目的任务框架最终定义为：

```text
TaskFramework =
  TaskDefinition
  + TaskInstance
  + TaskWorkEnvironment
  + TaskPlan
  + TaskTodoList
  + SessionTaskBinding
  + TaskContextPackage
  + TaskEnvironmentLease
  + AgentExecutionEpisode
  + EpisodeResult
  + WorkProduct
  + TaskReducer
  + Checkpoint
  + TaskControlSignal
  + GraphNodeTaskBinding
```

一句话：

```text
Task 是系统管理的持久工作环境。
Agent 通过 Episode 在环境中判断、行动和交付。
System 通过状态、上下文、资源、lease、checkpoint、reducer 和产物 store 管理任务推进。
```

## 12. Agent/System 对接的工程化实现蓝图

前面的协议说明“谁负责什么”。工程实现还必须回答一个更硬的问题：

```text
agent 产生的是判断、意图、证据和产物候选；
system 产生的是持久状态、调度资格、上下文包、资源边界和归并结果。
```

所以任务推进不能设计成“agent 自己改任务”，也不能设计成“system 替 agent 猜语义”。它必须是一个显式的双边协议：

```text
Task Store 保存事实
Task Scheduler 选择下一次执行
Context Builder 组包
Harness Bridge 调 agent
Agent 返回 EpisodeResult
Task Reducer 归并
Projection / Graph Bridge 通知下游
```

### 12.1 工程组件分工

| 组件 | 工程职责 | 输入 | 输出 | 禁止事项 |
| --- | --- | --- | --- | --- |
| `TaskAdmissionService` | 判断是否创建任务环境 | user turn / graph work order / repair request | TaskInstance + TaskWorkEnvironment | 不根据关键词自动升级任务 |
| `TaskStore` | 任务 canonical truth | command / event | event ledger + snapshot | 不保存未校验的 agent 自述为真相 |
| `TaskScheduler` | 选择 ready task，发起 episode | ready env、priority、lease 状态 | dispatch decision | 不执行模型，不做语义裁决 |
| `TaskContextBuilder` | 生成 agent 可读上下文包 | task snapshot、plan、todo、refs、budget | TaskContextPackage | 不把全量历史塞进上下文 |
| `HarnessBridge` | 把任务 episode 接入单 agent runtime | TaskContextPackage + profile | AgentExecutionEpisode result | 不新增第二套模型 loop |
| `ActionAdmissionPolicy` | 校验 episode 内动作是否合法 | action request、tool scope、task controls | allowed / denied / needs approval | 不越权替 agent 做判断 |
| `TaskReducer` | 把 EpisodeResult 归并为任务状态 | episode result、lease、snapshot | events + snapshot patch | 不接受无 lease、过期 episode 或伪造 ref |
| `WorkProductStore` | 保存可消费产物 | work product candidate | accepted / rejected / needs repair | 不把 assistant final answer 当唯一产物 |
| `TaskControlService` | pause / stop / resume / abort | user / graph / API signal | TaskControlSignal + state transition | 不直接杀掉无 checkpoint 的任务 |
| `TaskQueryProjection` | 给 UI、graph、session 查询任务状态 | event ledger + snapshot | status / timeline / report view | 不反向修改任务真相 |
| `GraphTaskBridge` | 图节点与任务环境绑定 | GraphNodeWorkOrder | GraphNodeTaskBinding + NodeResultEnvelope | 不让 GraphLoop 直接调模型 |

这组组件的边界是任务系统成熟度的核心。后续实现时，如果一个模块同时做了 admission、调度、模型执行、状态归并和产物发布，就说明边界已经塌了。

### 12.2 固定推进循环

任务推进是一个可重复执行的闭环：

```text
1. receive command
2. validate command
3. append event
4. update snapshot
5. schedule ready environment
6. acquire lease
7. build context package
8. run agent episode through harness
9. validate episode result
10. reduce into task state
11. publish projections / graph result / work products
12. release lease or schedule continuation
```

这个循环必须支持三种入口：

| 入口 | 典型来源 | 进入方式 |
| --- | --- | --- |
| 用户前台任务 | session turn 中用户要求持续工作 | `TaskAdmissionService.create_from_session_turn()` |
| 图任务节点 | graph loop 发出 `GraphNodeWorkOrder` | `GraphTaskBridge.bind_or_create_task()` |
| 维护/修复任务 | git delta、断链、失败产物、stale lease | `TaskMaintenanceService.create_repair_task()` |

无论入口来自哪里，进入任务环境之后都走同一条 episode / reducer 主链，不能分出三套执行器。

### 12.3 任务状态机

任务状态必须是系统状态，不是 agent 自述。

```text
created
-> ready
-> leased
-> reducing
-> ready | paused | blocked | completed | failed | aborted
-> archived
```

核心转移规则：

| from | to | 触发 | 必须证据 |
| --- | --- | --- | --- |
| `created` | `ready` | admission 通过 | goal / scope / acceptance / product requirements |
| `ready` | `leased` | scheduler 获取 lease | active lease record |
| `leased` | `reducing` | episode 返回 | episode result + lease match |
| `reducing` | `ready` | reducer 认为还需继续 | continuation hint 或 pending todo |
| `reducing` | `paused` | pause signal 生效 | checkpoint summary |
| `reducing` | `blocked` | blocker 不可自行解除 | blocker reason + next unblock condition |
| `reducing` | `completed` | 验收满足 | accepted work products + acceptance evidence |
| `leased` | `ready` | lease 超时回收 | stale lease event |
| `ready/paused/blocked` | `aborted` | 用户或上游明确终止 | abort command |

agent 可以说“我认为完成了”，但只能形成 `completion_candidate`。真正的 `completed` 由 `TaskReducer` 根据验收和产物证据写入。

### 12.4 Agent 可发出的任务动作

任务环境下，agent 不应该被迫用自然语言让系统猜。它需要一组明确 action intent：

```text
propose_plan
patch_todo
request_resource
call_tool
submit_work_product
report_evidence
ask_user
block
checkpoint
complete_candidate
request_repair
```

这些动作都不是直接状态写入。系统处理规则如下：

| agent action | system handler | 持久化结果 |
| --- | --- | --- |
| `propose_plan` | `TaskPlanService.validate_and_version()` | `plan_proposed` / `plan_revised` event |
| `patch_todo` | `TaskTodoService.apply_patch()` | `todo_created` / `todo_updated` event |
| `request_resource` | `ResourceGate.resolve()` | resource ref 或 denial reason |
| `call_tool` | `ActionAdmissionPolicy.authorize_tool()` | tool observation / artifact ref |
| `submit_work_product` | `WorkProductStore.validate_candidate()` | work product candidate / accepted |
| `report_evidence` | `EvidenceStore.attach()` | evidence ref |
| `ask_user` | `TaskControlService.pause_for_user()` | paused + question |
| `block` | `TaskReducer.mark_blocked()` | blocked state + blocker |
| `checkpoint` | `CheckpointService.write()` | checkpoint ref |
| `complete_candidate` | `TaskReducer.check_acceptance()` | completed 或 needs_more_work |
| `request_repair` | `TaskMaintenanceService.open_repair()` | repair task / repair edge |

这就是 agent 与 system 的工程接口：agent 输出意图，system 把意图变成经过校验的事件。

### 12.5 Context Package 的工程边界

系统推动任务，不是把数据库暴露给 agent，而是构造可执行上下文包。

```text
TaskContextPackage
  task_identity
  role_contract
  goal
  scope
  acceptance
  active_plan_summary
  active_todo
  current_state_summary
  relevant_evidence_refs
  work_product_requirements
  resource_handles
  graph_binding_context
  project_network_handles
  control_signals
  continuation_hint
  output_contract
```

上下文包的原则：

- `stable` 只放任务目标、验收、角色契约、关键约束；
- `current` 放当前 todo、当前问题、当前需要读取的资源；
- `refs` 保存计划全文、历史 episode、旧证据、已完成 todo；
- `volatile tail` 只放本 episode 必须即时注意的路标；
- 已完成事实不能反复注入上下文，只能以 summary/ref 形式进入；
- 如果 agent 需要更多历史，必须通过 query/resource ref 申请，而不是默认塞满 prompt。

这能避免任务越跑越臃肿，也能避免“不变事实反复进入上下文”导致模型注意力被旧内容拖偏。

### 12.6 Scheduler 如何推动任务继续

`TaskScheduler` 的职责是判断“下一次 agent episode 是否应该运行”，而不是判断“任务语义是否正确”。

调度输入：

```text
ready tasks
foreground session task
graph-ready nodes
repair tasks
maintenance tasks
control signals
lease table
priority policy
concurrency limit
```

推荐优先级：

```text
foreground user-controlled task
-> graph node whose dependencies are satisfied
-> repair task blocking published asset
-> paused task explicitly resumed
-> maintenance task
```

调度算法：

```text
for candidate in priority_queue:
  if candidate.status != ready:
    continue
  if has_active_lease(candidate):
    continue
  if dependency_not_satisfied(candidate):
    continue
  lease = acquire_lease(candidate)
  dispatch_episode(lease)
```

并发控制必须在 scheduler / lease 层完成，不应该让每个 graph adapter 自己开并发。图算法只声明哪些节点 ready，任务系统统一决定同时跑几个 episode。

### 12.7 Reducer 如何归并 agent 输出

Reducer 是任务推进的工程权威。它做三件事：

```text
validate
apply
project
```

伪流程：

```text
reduce_episode(episode_id, result):
  episode = load_episode(episode_id)
  assert lease_is_current(episode.lease_id)
  assert result.output_contract_version is supported

  validated_products = validate_work_products(result.work_product_candidates)
  validated_plan_patch = validate_plan_patch(result.plan_patch)
  validated_todo_patch = validate_todo_patch(result.todo_patch)
  validated_evidence = validate_evidence_refs(result.evidence_refs)

  append_event("episode_completed", ...)
  append_events(product_events)
  append_events(plan_todo_events)
  append_events(evidence_events)

  next_state = decide_next_state(snapshot, result, validated_products)
  write_snapshot(next_state)
  write_checkpoint(result.continuation_hint)
  release_lease()

  if graph_bound:
    emit NodeResultEnvelope
```

Reducer 的裁决依据必须是结构化字段和 evidence ref，不是自然语言报告里一句“已完成”。

### 12.8 Graph / Session / Project Network 的对接点

任务系统处在中间层：

```text
Session 负责用户入口和前台控制
GraphSystem 负责复杂任务空间调度
TaskSystem 负责持久工作环境和 episode 推进
Harness 负责单 agent 执行
ProjectNetworkSystem 负责长期项目控制资产
FileManagement 负责物理事实与文件/AST 资源
```

对接关系：

| 上游 | 调用任务系统的方式 | 下游返回 |
| --- | --- | --- |
| Session | create / bind / resume / pause task | task status、foreground report、question |
| GraphSystem | create node-bound task / poll NodeResultEnvelope | node result、blocked、repair needed |
| ProjectNetworkSystem | request build/repair task | work product、generation candidate |
| FileManagement | 提供 file/AST/resource ref | evidence ref、physical skeleton |
| Harness | 执行 episode | EpisodeResult |

工程上必须坚持：GraphSystem 不保存语义网络资产，ProjectNetworkSystem 不调度 agent，Harness 不保存任务真相，Session 不拥有任务。

### 12.9 失败恢复机制

成熟任务系统必须把失败当作常态：

| 失败 | 系统处理 |
| --- | --- |
| episode 中断 | lease 过期后回收，使用 checkpoint / continuation hint 重派 |
| agent 输出格式不合约 | result rejected，写 dead letter，必要时发 repair episode |
| 工具失败 | 记录 observation，agent 决定替代路径或 blocker |
| 产物不满足验收 | WorkProduct rejected / needs repair，任务回到 ready |
| graph node 阻塞 | NodeResultEnvelope 返回 blocked，不让 GraphLoop 猜原因 |
| 用户暂停 | 写 checkpoint，release lease，保留 foreground binding |
| session 丢失 | task 仍可通过 task id / binding 查询恢复 |
| git delta 破坏语义网 | maintenance service 创建 repair task |

恢复的原则是：

```text
恢复任务状态靠 TaskStore 和 checkpoint；
恢复 agent 行动靠 TaskContextPackage；
恢复语义资产靠 WorkProduct / project network generation；
不靠旧 session transcript 重演。
```

### 12.10 最小可实施接口

第一阶段可以先落这些接口，不需要一开始做完整 UI：

```text
TaskAdmissionService.create_task(request) -> task_environment_id
TaskBindingService.bind_session(session_id, task_environment_id, role) -> binding_id
TaskScheduler.dispatch_ready(limit) -> dispatched_episode_ids
TaskContextBuilder.build(task_environment_id, episode_id) -> TaskContextPackage
HarnessBridge.run_episode(package) -> EpisodeResult
TaskReducer.reduce(episode_id, result) -> TaskSnapshot
TaskControlService.pause(task_environment_id, reason) -> TaskSnapshot
TaskControlService.resume(task_environment_id) -> dispatch token
TaskQueryService.get_task(task_environment_id) -> TaskView
TaskQueryService.list_work_products(task_environment_id) -> WorkProductView[]
GraphTaskBridge.create_node_task(work_order) -> GraphNodeTaskBinding
GraphTaskBridge.consume_node_result(binding_id) -> NodeResultEnvelope
```

这些接口足以支撑：

- 普通 session 创建一个可恢复任务；
- 图节点创建一个任务环境并等待结果；
- agent 在 episode 中提交 plan/todo/product；
- 系统暂停、恢复、归并和查询任务；
- 后续项目语义网络审查任务复用同一条底座。

### 12.11 成熟度检查清单

实现时每完成一个阶段，都必须用这组问题自检：

1. `Task` 是否仍然是持久工作环境，而不是 todo / graph node / message？
2. agent 是否只提交 proposal/result，而没有直接改 canonical state？
3. system 是否只做管理、校验、调度和归并，而没有替 agent 做语义判断？
4. episode 是否都有 lease、context package、result、checkpoint 边界？
5. plan/todo 是否版本化、事件化，而不是覆盖式字符串？
6. completed 是否由 acceptance + work product evidence 判定？
7. pause/resume 是否不依赖旧 provider stream？
8. GraphLoop 是否只消费 NodeResultEnvelope？
9. ProjectNetworkSystem 是否只保存发布后的网络资产或候选产物？
10. 失败路径是否能形成 dead letter / repair task，而不是静默丢失？
