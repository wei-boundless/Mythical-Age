# 图任务程序化 Agent 时空架构重设计

状态：顶层架构设计稿，待审阅后实施  
日期：2026-07-06  
适用范围：`graph_system`、`task_system`、`harness`、图任务配置编译器、写作图、项目网络审查图、repair / maintenance 图

## 1. 核心定义

图任务不是流程图工具，也不是普通任务清单。

本项目里的图任务应定义为：

```text
GraphTask = Programmed Agent Spacetime Runtime
图任务 = 面向 agent 的程序化时空调控系统
```

它把复杂任务空间化，把 agent、记忆库、资源、控制路由、物化点和子图入口都编译成可运行的物理节点，并通过节点适配器与任务契约显式调用 agent 或系统能力完成局部工作。

换成工程语言：

```text
ExecutableGraphConfig = 不可变程序结构
GraphRun = 一次程序运行宇宙
GraphAlgorithm = 程序控制流算法
GraphLoop = 时空推进器
GraphNode = 图任务空间中的物理单位，不等同于 agent
NodeExecutionAdapter = 节点如何被执行或物化
NodePort = 节点输入、输出、控制、资源端口
NodeTaskContract = agent 可执行任务契约
AgentBinding = agent 执行节点使用哪个已注册 agent / profile
TaskWorkEnvironment = agent 执行节点的持久工作现场
Harness = 唯一单 agent 执行 runtime
NodeResultEnvelope = 可执行节点返回给图系统的结构化结果
OutcomeSignal = 返回值的通用控制语义
TransitionPolicy = outcome 到边的选择规则
ControlFrame = 返修、重试、人工门控、repair、fork 的时空帧
GraphTime = 结构代际、运行 epoch、逻辑事件、superstep、attempt、frame、物化和 checkpoint 的统一时间坐标
Checkpoint / Timeline = 可恢复、可审计的运行时间切面与因果事件线
```

这套定义的关键点是：

- 图任务负责“什么时候、在哪个状态、激活哪个物理节点、通过哪个适配器执行或物化”。
- agent 负责“在当前契约下做语义判断、使用工具、产出候选结果”。
- 系统负责“校验、调度、归并、持久化、恢复、审计、发布”。
- 业务图实例只声明契约、节点、边、outcome 能力和算法参数，不把业务词写入 `graph_system` core。

## 2. 当前设计为什么不够成熟

当前系统已经有可运行骨架：

```text
TaskGraphDefinition
-> ExecutableGraphConfig
-> GraphRuntimeEnvelope
-> GraphLoopState
-> GraphNodeWorkOrder
-> Harness execution
-> NodeResultEnvelope
-> TransitionProcessor
-> Checkpoint
```

但它仍然存在五个结构性问题：

| 问题 | 现状 | 风险 |
| --- | --- | --- |
| 算法与业务语义混合 | 返修、质量重试、提交失败等逻辑分散在 executor、transition、loop、resume | 写作图、项目网络图、repair 图都会各自堆特例 |
| 节点物理单位与执行适配器混淆 | 节点有时被当作 agent 调用位，有时又承载 resource / memory / human gate / tool，空间身份、执行方式和 agent 契约没有分层 | 记忆库、资源节点、控制路由会被硬塞进 agent 节点模型，节点配置、agent 配置、任务契约容易混淆 |
| `status` 过载 | 执行失败、业务不通过、返修、可恢复阻塞都压在一个字段 | 合法业务拒绝会终止整图 |
| 配置策略没有成为运行裁决权威 | `transition_policy/readiness_policy` 有编译字段，但运行时仍靠旧启发式 | 图编辑器看起来有策略，实际运行不消费 |
| 恢复与控制没有 frame 化 | revision / retry / human gate / repair 各走特殊分支 | 无法稳定 checkpoint、恢复、审计、补线和重放 |

成熟架构必须把图任务从“状态机 + 特例处理”升级为“程序化时空 + 通用控制算法 + 多类型物理节点 + 契约化可执行节点”。

## 3. 成熟架构参照原则

本设计综合此前本地审查的成熟 agent / workflow 源码与本项目现有实现，采用以下不变量：

```text
Session != Task != GraphRun != NodeExecution != WorkProduct
```

成熟系统共同点：

- 运行结构和运行实例分离。
- 状态推进有唯一权威。
- agent 执行是受控调用，不是自由漂移。
- checkpoint / event / result 都是可追踪对象。
- 工具、副作用、产物写入有显式授权和回执。
- 任务恢复靠持久状态和 checkpoint，不靠模型读旧聊天记录猜。
- 输出先成为结构化结果，再由系统归并为状态或长期资产。

本项目不应照搬任何外部 runner，而应吸收其工程不变量：

```text
不可变结构
明确运行实例
结构化状态
事件时间线
checkpoint 恢复边界
显式 action / result contract
可审计副作用
```

## 4. 总体架构

目标系统分为七层。

```text
Graph Program Layer
  图模板、算法声明、节点规格、端口、边契约、资源声明、agent 绑定。

Graph Runtime Layer
  graph run、clock、checkpoint、timeline、ready state、active frames。

Algorithm Layer
  readiness、transition、loop、tree_reduce、fanout、revision、retry、repair、fork。

Task Environment Layer
  TaskCommand、TaskWorkEnvironment、AgentExecutionEpisode、WorkProduct、Reducer；只承载 agent 执行节点。

Harness Execution Layer
  单 agent runtime、工具授权、动作协议、模型调用、输出提交。

Domain Adapter Layer
  写作图、项目网络图、repair 图等领域契约、context provider、outcome adapter。

Projection / Control Layer
  前端图任务工作台、timeline、checkpoint、node trace、control command。
```

硬权威链：

```text
GraphSystem
  只拥有图结构、图运行状态、算法调度、work order、transition、checkpoint。

TaskSystem
  只拥有任务环境、命令、episode、work product、reducer、任务状态。

Harness
  只拥有单 agent 执行循环、工具调用、模型动作协议。

Domain Adapter
  只把领域输出映射成通用 outcome / work product，不推进图状态。

ProjectNetworkSystem
  只拥有项目控制网络长期资产、generation、repair records。
```

禁止的反向越权：

- `GraphSystem` 直接执行模型。
- `GraphSystem` 解析“世界观、章节、提交失败”等业务词。
- `TaskSystem` 决定图节点 ready 或改 GraphLoopState。
- `Harness` 保存任务真相或项目网络资产。
- `ProjectNetworkSystem` 调度 agent 审查。
- 领域 adapter 修改 graph topology。

## 5. 核心对象模型

### 5.1 GraphProgram

`GraphProgram` 是图任务的程序定义，不是运行实例。

```text
GraphProgram
  program_id
  graph_id
  graph_kind
  algorithm_family
  node_specs
  edge_specs
  frame_specs
  resource_specs
  contract_refs
  compile_policy
  version
```

它由图编辑器、脚本或模板编译而来，最终发布为 `ExecutableGraphConfig`。

### 5.2 AlgorithmSpec

算法是图任务的控制流，不是业务语义。

```text
AlgorithmSpec
  algorithm_id
  algorithm_kind:
    dag
    loop
    tree_reduce
    fanout_join
    map_reduce
    review_gate
    revision_frame
    retry_frame
    repair_frame
    fork_replay
  parameters
  concurrency_policy
  readiness_policy
  transition_policy
  checkpoint_policy
  invalidation_policy
```

同一个算法可以承载不同实例：

| 算法 | 写作图实例 | 项目网络实例 |
| --- | --- | --- |
| `loop` | 章节批次循环 | 分层修复迭代 |
| `tree_reduce` | 可用于卷级汇总 | 文件 -> 目录 -> 系统 -> 根报告 |
| `review_gate` | 世界观/章节审核 | 语义节点审核 |
| `revision_frame` | 返修正文或设定 | 返修文件语义 facet |
| `repair_frame` | 修复断章/缺口 | 修复断链、locate miss、git delta |

### 5.3 GraphNode

节点不是函数，不是 prompt 文本，不是 task 本身，也不天然等于 agent。

节点是图任务空间里的物理单位：

```text
GraphNode
  node_id
  node_kind:
    agent_execution_node
    deterministic_system_node
    resource_node
    memory_repository_node
    artifact_repository_node
    control_router_node
    human_gate_node
    subgraph_node
    materialization_node
    external_service_node
  spatial_role
  state_role
  execution_adapter_ref
  input_ports
  output_ports
  control_ports
  resource_ports
  input_contract_ref
  output_contract_ref
  resource_contract_ref
  context_policy_ref
  outcome_policy_ref
  scheduler_policy_ref
  visibility_policy_ref
  lifecycle_policy_ref
```

它回答的是：

```text
这个图空间里有什么物理点？
这个物理点持有什么资源或状态？
它从哪些端口接收输入？
它向哪些端口输出 packet、artifact、memory ref 或 control signal？
它是否需要执行，还是只作为资源、路由、物化或子图边界存在？
```

节点类别必须和执行方式分开：

| 节点类别 | 是否执行 agent | 典型作用 | 返回形式 |
| --- | --- | --- | --- |
| `agent_execution_node` | 是 | 让已注册 agent 在任务契约下做判断、写作、审查、修复 | `NodeResultEnvelope` + `WorkProduct` |
| `deterministic_system_node` | 否 | AST 抽取、hash 计算、索引刷新、确定性 transform | system receipt / materialized packet |
| `resource_node` | 否 | 文件树、AST spine、工具目录、配置资源入口 | resource handle / capability ref |
| `memory_repository_node` | 否 | 记忆库、共享状态、layer summary、checkpoint memory | memory view / commit receipt |
| `artifact_repository_node` | 否 | 文档、报告、索引文件、审查产物仓库 | artifact ref / version receipt |
| `control_router_node` | 否 | outcome 路由、条件分支、join、fanout、barrier | transition decision |
| `human_gate_node` | 否，除非绑定人工代理 | 人工确认、人工替换产物、审批分叉 | human decision result |
| `subgraph_node` | 视子图而定 | 把一张子图作为父图的物理节点 | subgraph run ref / aggregate result |
| `materialization_node` | 否 | precommit、commit、publish、generation seal | materialization receipt |
| `external_service_node` | 否，除非服务背后是 agent | 调第三方服务、索引器、编译器、数据库 | external receipt |

因此，一个节点至少有四层身份：

```text
Physical Identity:
  node_id / node_kind / spatial_role / graph_level

State Role:
  stores_state / gates_state / routes_state / materializes_state / observes_state

Execution Adapter:
  none
  agent_harness
  deterministic_function
  resource_projection
  repository_operation
  human_gate
  subgraph_runner
  external_service

Agent Visibility:
  hidden_system_node
  visible_resource_landmark
  visible_context_ref
  executable_contract_surface
```

`GraphNode` 是空间单位，`NodeExecutionAdapter` 才说明它如何动起来：

```text
NodeExecutionAdapter
  adapter_kind:
    agent_harness
    deterministic_system
    resource_projection
    repository_read
    repository_write
    control_router
    human_gate
    subgraph_runner
    external_service
  admission_policy
  idempotency_policy
  side_effect_policy
  result_projection_policy
```

只有 `agent_harness` 适配器需要以下组合：

```text
AgentExecutionNode
  agent_binding_ref
  node_task_contract_ref
  task_work_environment_policy_ref
  tool_policy_ref
  memory_policy_ref
  artifact_policy_ref
  retry_policy_ref
  node_session_policy
```

资源、记忆、物化和控制节点可以有契约，但不是 `NodeTaskContract`：

```text
MemoryRepositoryNode
  repository_ref
  read_contract_ref
  write_contract_ref
  version_policy_ref
  visibility_policy_ref

MaterializationNode
  precommit_contract_ref
  commit_contract_ref
  rollback_policy_ref
  publication_policy_ref

ControlRouterNode
  route_policy_ref
  join_policy_ref
  frame_policy_ref
```

节点的三条线必须分开：

```text
GraphNode = 图空间里这个物理点是什么。
ExecutionAdapter = 这个物理点如何被执行、投影、路由或物化。
TaskContract = 当且仅当它是 agent 执行节点时，交给 agent 做什么。
```

agent 执行节点的两条线仍然必须分开：

```text
AgentBinding = 这个节点用哪个已注册 agent / profile / group。
TaskContract = 这个节点把什么任务交给 agent 做。
```

图节点只负责对接契约和端口，不重新配置 agent 内部能力。工具、模型、人格、环境等来自 agent 绑定和 profile，节点可以声明额外限制，但不能私自展开成另一套 agent 配置系统。

成熟判断标准：

- 记忆库节点不伪装成 agent 节点。
- 资源节点不生成 Harness episode。
- 控制路由节点不写自然语言 prompt。
- agent 节点不直接拥有长期资产，只提交候选产物或意图。
- 图运行可以对不同节点使用不同 adapter，但仍由同一个 GraphLoop 和 Algorithm 层推进。

### 5.4 NodeTaskContract

任务契约只属于需要 agent 理解并执行的节点。它是写给 agent 执行的，不是写给开发者看的说明。

```text
NodeTaskContract
  role_contract
  responsibility
  input_description
  forbidden_actions
  output_requirements
  acceptance_criteria
  uncertainty_policy
  failure_policy
  language_policy
```

例子：

```text
你是一名单文件项目控制语义审查员。
你只负责系统提供的一个物理文件。
你需要在系统提供的 AST 骨架和文件内容证据上建立该文件的语义坐标。
你不能读取其它文件，不能伪造调用关系，不能把猜测写成 accepted relation。
证据不足时必须输出 candidate relation 和 limitations。
```

禁止：

```text
这是 file_review 节点。
根据 tree_reduce 算法执行文件审查。
```

### 5.5 NodeInvocationFrame

一次节点执行不是节点本身，而是一次调用帧。并不是所有节点都有调用帧；资源节点、记忆库节点和静态物理节点可以只产生 projection 或 version receipt。只有被调度执行的节点才生成 invocation frame。

```text
NodeInvocationFrame
  frame_id
  graph_run_id
  node_id
  execution_adapter_kind
  work_order_id
  task_environment_id
  episode_id
  attempt_index
  graph_clock_seq
  superstep_seq
  input_packet_refs
  input_checkpoint_ref
  status
```

如果 `execution_adapter_kind = agent_harness`，它对应一次 agent 执行现场，并且必须有 `TaskWorkEnvironment` 与 `AgentExecutionEpisode`。如果是 deterministic / repository / materialization / human gate，则它对应一次系统动作、仓库操作、物化提交或人工决策，不生成 agent episode。

### 5.6 OutcomeSignal

节点返回后必须归一成 outcome。

```text
OutcomeSignal
  outcome_id
  outcome_kind:
    completed
    revision_requested
    retry_requested
    waiting_human_gate
    blocked
    technical_failed
    aborted
  source:
    agent_result
    output_contract
    quality_gate
    materialization_precommit
    runtime
    human_control
  severity:
    normal
    control
    recoverable
    terminal
  reason_summary
  payload_ref
  target_hint
  authority
```

算法只看 `outcome_kind`。业务词只进入 payload。

### 5.7 TransitionPolicy

边不是静态线，而是 outcome 驱动的传递规则。

```text
TransitionPolicy
  trigger_outcomes
  excluded_outcomes
  route_role:
    normal
    revision
    retry
    repair
    human_gate
    terminal
  packet_policy
  invalidation_policy
  target_activation_policy
```

普通边默认：

```text
trigger_outcomes = ["completed"]
```

返修边默认：

```text
trigger_outcomes = ["revision_requested"]
route_role = "revision"
```

重试边默认：

```text
trigger_outcomes = ["retry_requested"]
route_role = "retry"
```

### 5.8 ControlFrame

返修、重试、人工门控、repair、fork 都是控制帧。

```text
ControlFrame
  frame_id
  frame_kind:
    revision
    retry
    human_gate
    repair
    fork
    replay
  source_node_id
  source_result_ref
  target_node_ids
  opened_at_graph_clock
  invalidation_scope
  carried_context_refs
  close_policy
  status:
    active
    waiting
    closed
    aborted
```

控制帧的作用：

- 记录为什么进入控制流。
- 标记目标节点和失效范围。
- 生成回传 packet。
- 写入 checkpoint。
- 给前端和恢复层解释当前图为什么回到某个节点。

### 5.9 GraphTime

图任务里的“时间”不能只等同于 `updated_at`、`event_cursor` 或 checkpoint。成熟图任务需要一套多层时间模型，因为它要同时回答：

```text
结构是否还是同一张图？
本次运行是不是同一个 graph run？
事件发生的因果顺序是什么？
这一批并发节点属于哪个调度波次？
某个节点是第几次 attempt？
返修/重试/人工门控 frame 何时打开、暂停、关闭？
记忆、artifact、项目网络 generation 是哪一代？
恢复点切在哪里？
真实墙钟时间只是观测，还是参与了语义裁决？
```

目标模型：

```text
GraphTime =
  StructureGenerationTime
  + RunEpochTime
  + LogicalEventTime
  + SuperstepTime
  + NodeAttemptTime
  + ControlFrameTime
  + MaterializationTime
  + CheckpointTime
  + WallClockObservation
```

各层定义：

| 时间层 | 关键字段 | 负责什么 | 禁止承担什么 |
| --- | --- | --- | --- |
| `structure_time` | `config_id`、`structure_hash`、`structure_generation` | 判断运行使用的图结构是否一致 | 不决定节点是否 ready |
| `run_time` | `graph_run_id`、`run_epoch`、`parent_graph_run_id` | 标识一次运行宇宙、fork 和 replay 边界 | 不混同 session 或 task |
| `logical_time` | `graph_clock_seq`、`event_cursor`、`timeline_event_id` | 表示因果事件顺序，是审计与确定性恢复的主时间 | 不使用 wall clock 替代 |
| `superstep_time` | `superstep_seq`、`dispatch_wave_id`、`barrier_id` | 表示一次并发调度波次，支撑 fanout/join/tree_reduce | 不表示单节点 retry 次数 |
| `node_time` | `node_dispatch_seq`、`attempt_index`、`retry_index` | 表示同一节点多次执行的谱系 | 不覆盖旧 result |
| `frame_time` | `frame_id`、`opened_at_graph_clock`、`suspended_at`、`closed_at_graph_clock` | 表示 revision/retry/repair/human gate/fork 的控制帧生命周期 | 不替代节点 attempt |
| `materialization_time` | `artifact_generation`、`memory_version`、`commit_seq`、`publication_generation` | 表示长期资产、记忆、artifact、项目网络 generation 的版本 | 不用来直接推进图 ready |
| `checkpoint_time` | `checkpoint_id`、`parent_checkpoint_id`、`checkpoint_seq`、`resume_boundary` | 表示恢复切面和可重放边界 | 不当作完整历史真相 |
| `wall_time` | `created_at`、`updated_at`、`duration_ms` | 用于观测、排序 UI、超时和运行诊断 | 不参与业务语义和边选择 |

核心对象：

```text
GraphTimeRef
  graph_run_id
  structure_hash
  run_epoch
  graph_clock_seq
  event_cursor
  superstep_seq
  checkpoint_id

GraphEpoch
  graph_run_id
  parent_graph_run_id
  fork_reason
  structure_hash
  opened_at_checkpoint_id
  status

GraphSuperstep
  superstep_seq
  dispatch_wave_id
  ready_node_ids
  dispatched_node_ids
  barrier_policy
  opened_at_graph_clock
  closed_at_graph_clock

NodeAttemptRef
  node_id
  node_dispatch_seq
  attempt_index
  retry_index
  work_order_id
  previous_attempt_ref
  source_frame_id

FrameLifetime
  frame_id
  frame_kind
  opened_at_graph_clock
  suspended_at_checkpoint_id
  resumed_at_checkpoint_id
  closed_at_graph_clock
  close_reason

MaterializationClock
  resource_ref
  generation
  commit_seq
  source_result_ref
  source_attempt_ref
  validity:
    candidate
    committed
    superseded
    invalidated
```

时间不变量：

- `logical_time` 是图语义和审计的主轴；`wall_time` 只能做观测、超时和 UI 排序。
- `structure_time` 决定能否 resume；结构 hash 不一致时必须 fork、migrate 或拒绝恢复，不能静默套旧 checkpoint。
- `superstep_time` 把并发调度聚成波次；同一 superstep 内节点可以并发完成，但写入 timeline 时必须拥有确定的 logical event order。
- `node_time` 永不覆盖旧 attempt；重试、返修和 repair 都产生新 attempt，并保留 lineage。
- `frame_time` 描述控制流生命周期；返修不是“把指针倒回去”，而是打开一个 frame，frame 内的重放、失效、回传都可审计。
- `materialization_time` 管长期资产代际；记忆提交、artifact 发布和项目网络 generation 必须能追溯到 source result / source attempt。
- `checkpoint_time` 是恢复切面，不是长期事实全量；完整因果真相在 timeline event + result / frame / materialization records。
- resume 只能从 checkpoint 恢复可执行现场，再用 timeline 与 state snapshot 校验一致性；不能从自然语言 summary 推断图状态。

一个节点结果被接受时，时间写入顺序应固定为：

```text
NodeAttemptRef completed
-> append TimelineEvent(graph_clock_seq + 1)
-> normalize OutcomeSignal
-> build TransitionPlan
-> open/close ControlFrame if needed
-> update MaterializationClock if committed
-> update GraphSuperstep barrier state
-> write Checkpoint if policy requires
-> dispatch next superstep
```

这套时间系统的目标不是制造复杂度，而是防止五类成熟系统最常见的问题：

- 并发节点结果乱序导致 ready 判定漂移。
- retry 覆盖旧 result，恢复后无法解释为什么重跑。
- revision 只重置节点状态，没有 frame 解释和回传证据。
- checkpoint 被误当成真相，丢失 event lineage。
- artifact / memory / semantic generation 更新后无法追踪来自哪个节点 attempt。

### 5.10 HarnessTurnTime

`GraphTime` 是图任务外层时间，不替代 Harness 内部的 turn 时间。

现有代码已经有明确的内层时间对象：

```text
TurnRun
  turn_run_id
  session_id
  turn_id
  status
  latest_event_offset

ExecutorSequence
  executor_epoch
  invocation_index

ModelActionRequest
  request_id
  turn_id
  action_type

ActionLifecycle
  action_request_ref
  action_type
  started / completed / failed
```

因此，agent 执行节点的真实时间嵌套关系应固定为：

```text
GraphRun
-> GraphSuperstep
-> NodeAttemptRef
-> TaskWorkEnvironment
-> AgentExecutionEpisode
-> HarnessTurnRun
-> RuntimeInvocation / ProviderStep
-> ModelActionRequest
-> ToolLifecycle / Observation
-> HarnessSavePoint
```

这意味着：

- 一个 `NodeAttemptRef` 可以包含一个或多个 `HarnessTurnRun`。
- 一个 `HarnessTurnRun` 可以包含多次 provider request、工具调用、工具 observation、协议修复、上下文压缩和 continuation。
- `turn_run_id` 是 agent 内部执行 trace，不是 `graph_run_id`，也不是 `task_environment_id`。
- `latest_event_offset` 是 Harness 事件日志里的偏移，不等于 Graph 的 `graph_clock_seq`。
- `executor_epoch + invocation_index` 标识同一任务执行环境内的 provider packet / model action 序列，不替代图节点 attempt。
- Harness 可以因为工具结果、MCP 结果、上下文压缩、approval、recovery 进入下一次内部 turn，但 Graph 只有在 `NodeResultEnvelope` 被接受后才推进外层图状态。

`HarnessTurnTime` 建议模型：

```text
HarnessTurnTime
  turn_run_id
  turn_id
  session_id
  agent_profile_id
  runtime_anchor_id
  task_environment_id
  episode_id
  graph_run_id
  node_id
  node_attempt_ref
  executor_epoch
  invocation_index
  runtime_packet_ref
  provider_step_seq
  action_request_ref
  tool_invocation_ref
  observation_ref
  latest_event_offset
```

内层 turn 生命周期：

```text
turn_start
-> build runtime packet / prompt context
-> provider request
-> model_action_request_received
-> action admission
-> tool lifecycle started/completed/failed 或 final response
-> tool observation / model observation
-> optional compaction / approval / recovery
-> next provider request or turn_closeout
-> turn_end save point
```

内层时间不变量：

- Harness turn 是 agent 执行节拍，不是持久任务真相。
- Task Episode 是任务环境里的执行片段；Harness TurnRun 是该片段内部的模型/工具运行 trace。
- Graph 不读取 Harness 内部 action 序列来判断边；Graph 只消费经过 TaskReducer / bridge 投影后的 `NodeResultEnvelope`。
- Harness 内部的工具失败、协议修复、上下文压缩可以继续在同一 NodeAttempt 内处理；只有 reducer 认定节点结果失败或阻塞时，才映射成外层 `OutcomeSignal`。
- 用户 steer / approval / follow-up 在 Harness 内部有 turn 时序，但如果它改变任务或图的因果状态，必须被提升为 TaskControlSignal 或 ControlFrame。
- 内层 `wall_time` 可用于 timeout、monitor 和用户可见进度；不能决定外层 transition。

外层 GraphTime 与内层 HarnessTurnTime 的桥接对象：

```text
ExecutionTraceBinding
  graph_run_id
  superstep_seq
  node_id
  node_attempt_ref
  task_environment_id
  episode_id
  turn_run_ids
  runtime_anchor_id
  first_harness_event_offset
  last_harness_event_offset
  node_result_ref
```

这条绑定必须进入 `NodeInvocationFrame` 或 `NodeResultEnvelope.diagnostics`，用于前端和审计从图节点跳到 agent 内部 trace。它只做追踪和诊断，不把 Harness turn 变成图任务的调度权威。

## 6. 固定运行流程

### 6.1 编译与发布

```text
GraphTemplate / Editor Draft
-> GraphProgram
-> AlgorithmSpec normalization
-> NodeSpec / Port / ExecutionAdapter validation
-> AgentBinding validation for agent execution nodes
-> EdgeContract / TransitionPolicy validation
-> ExecutableGraphConfig
-> published config_id / content_hash / structure_hash
```

编译阶段必须校验：

- 每个节点有明确 `node_kind`、端口、状态角色和 execution adapter。
- 每个 `agent_execution_node` 有 agent binding、task contract 和 output contract。
- 每个 `memory_repository_node` / `artifact_repository_node` 有仓库 contract 和版本策略。
- 每个 `control_router_node` 有 route / join / frame policy。
- 每个 `materialization_node` 有 precommit / commit / rollback policy。
- 每条控制边有 transition policy。
- 每个 revision / retry / repair 路由有合法 target。
- 输出契约能被 reducer / adapter 识别。

### 6.2 启动图运行

```text
ExecutableGraphConfig + initial_inputs
-> GraphRuntimeEnvelope
-> GraphRun
-> GraphLoopState
-> initial checkpoint
-> ready start nodes
```

GraphRun 是运行宇宙。它不能修改原 config。

### 6.3 调度节点

```text
GraphLoop.status_snapshot()
-> ReadinessEngine
-> DispatchPlan
-> NodeActivationPlan
-> NodeExecutionAdapter
-> GraphNodeWorkOrder / RepositoryOperation / MaterializationIntent / ControlDecision
```

GraphSystem 只决定哪些节点激活、使用哪个 adapter、产生什么调度意图；它不执行模型，也不把非 agent 节点伪装成 agent 任务。

### 6.4 Agent 节点进入任务环境

```text
GraphNodeWorkOrder(adapter_kind=agent_harness)
-> TaskCommand(graph_node_run)
-> GraphNodeTaskBinding
-> TaskWorkEnvironment
-> AgentExecutionEpisode
-> TaskContextPackage
```

只有 `agent_execution_node` 进入任务环境。资源节点、记忆库节点、控制路由节点和物化节点走各自 adapter，生成 resource view、repository receipt、transition decision 或 materialization receipt，再被投影为图系统可消费的结构化记录。

TaskContextPackage 给 agent 的输入必须分层：

```text
stable_context:
  role_contract
  goal
  scope
  acceptance
  output_contract

current_context:
  current node input
  active frame
  inbound packet summaries
  current todo / blocker / user steer

refs:
  artifact refs
  memory refs
  evidence refs
  graph refs
```

### 6.5 Harness 执行 agent

```text
TaskContextPackage
-> AgentExecutionEpisode
-> Harness packet / RuntimeInvocation
-> HarnessTurnRun
-> provider request
-> ModelActionRequest
-> action admission
-> ToolLifecycle / Observation / final response
-> optional compaction / approval / recovery / next turn
-> EpisodeResult
-> WorkProduct candidates
```

Harness 不知道图算法，也不推进图状态。它只维护单 agent 内部 turn 时序、动作协议、工具生命周期、上下文压缩、恢复和最终 episode 输出。`turn_run_id`、`action_request_ref`、`tool_invocation_ref` 必须通过 `ExecutionTraceBinding` 回指 `node_attempt_ref`。

### 6.6 归并和回传

```text
EpisodeResult
-> TaskReducer
-> WorkProduct
-> NodeResultEnvelope projection
-> ExecutionTraceBinding attached
-> OutcomeNormalizer
-> OutcomeSignal[]
-> GraphLoop.accept_node_result()
```

`NodeResultEnvelope` 是 GraphLoop 的唯一节点结果输入。

### 6.7 图状态推进

```text
NodeResultEnvelope + OutcomeSignal[]
-> TransitionProcessor
-> TransitionPlan
-> FlowPacket generation
-> ControlFrameManager
-> InvalidationEngine
-> StatusSnapshot
-> Checkpoint
-> next DispatchPlan
```

这条链路是图任务的核心程序化时空推进。

## 7. 算法层设计

算法层只处理通用控制逻辑。

### 7.1 ReadinessEngine

职责：

- 根据 node status、edge states、frame status、join policy 判断 ready。
- 消费编译后的 `readiness_policy`。
- 不解析业务文本。

输入：

```text
GraphLoopState
ExecutableGraphConfig
active ControlFrames
edge state
```

输出：

```text
ReadinessDecision
  ready_node_ids
  waiting_node_ids
  blocked_node_ids
  reasons
```

### 7.2 TransitionEngine

职责：

- 根据 `OutcomeSignal` 和 `TransitionPolicy` 选择 outgoing edges。
- 生成 `TransitionPlan`。
- 生成 packet intent。
- 标记 skipped / blocked / source_failed。

禁止：

- 解析 agent 输出自然语言。
- 用 node_id 判断业务路由。
- 用 edge_id 命名片段决定是否激活。

### 7.3 FrameManager

职责：

- 打开 control frame。
- 关闭 control frame。
- 把 frame 写入 checkpoint。
- 生成 frame context packet。
- 暴露 frame projection 给 agent 和前端。

统一管理：

```text
revision
retry
human gate
repair
fork
replay
```

### 7.4 InvalidationEngine

职责：

- 按因果边界失效下游。
- 保留不受影响结果。
- 保留历史 result / audit。
- 清理 active work order 和 packet refs。
- 不删除长期资产，只标记引用代际。

输入：

```text
ControlFrame.invalidation_scope
TransitionPolicy.invalidation_policy
edge roles
loop frame boundaries
resource/materialization dependency
```

### 7.5 LoopEngine

职责：

- 维护循环 cursor、iteration、active frame。
- 决定 continue / exit。
- 不处理业务返修。

写作图章节循环和其它循环任务都走同一算法。

### 7.6 TreeReduceEngine

职责：

- 基于确定物理结构 fan-out 子节点。
- 等待子节点回传。
- 调度父节点聚合。
- 支持层层回推到根。

项目网络审查图应使用 TreeReduceEngine：

```text
file nodes
-> directory aggregate nodes
-> system aggregate nodes
-> root aggregate node
```

### 7.7 RepairEngine

职责：

- 根据断链、失败 outcome、git delta、locate miss 生成 repair frame。
- 将 repair 映射为 TaskCommand / graph repair run。
- 不在原图上静默补状态。

## 8. 任务契约与 agent 调用

图任务必须把节点契约写成 agent 能直接执行的合同。

节点契约由四部分组成：

```text
RoleContract
  agent 是谁，工作姿态是什么。

WorkContract
  本节点只负责什么，边界是什么。

InputContract
  系统会提供哪些输入，输入可信度如何。

OutputContract
  必须输出什么结构，什么算合格，失败如何表达。
```

示例：写作世界观审核节点。

```text
你是一名商业长篇小说世界观审核员。
你只负责审核当前世界观候选是否完整、一致、能支撑后续人物、剧情和章节写作。
你不负责扩写世界观，不负责替作者重写正文。
你会收到世界观候选、项目风格目标、上游创作约束和审核输出契约。
你必须指出阻塞问题、非阻塞建议、是否允许进入记忆提交阶段。
如果不能通过，你必须输出返修原因、返修目标和下游不得继续使用的内容范围。
```

示例：项目网络文件审查节点。

```text
你是一名单文件项目控制语义审查员。
你只负责当前文件，不读取其它文件。
你需要在系统提供的 AST 骨架、文件内容和父目录目标上建立该文件的语义坐标。
你必须区分 accepted relation、candidate relation 和 unresolved signal。
证据不足时不要猜测，把缺口写入 limitations 和 repair suggestions。
```

## 9. 实例配置模型

图任务 core 不关心业务。业务通过实例配置声明。

### 9.1 写作图实例

```text
algorithm_family = loop + review_gate + revision_frame

nodes:
  world_design
  world_review
  memory_commit_world
  character_design
  chapter_draft
  chapter_review

edges:
  normal handoff edges trigger completed
  revision edges trigger revision_requested
  memory commit edges trigger completed only
```

业务 adapter 只负责：

- 从写作节点输出中提取结构化 verdict。
- 映射成 `OutcomeSignal`。
- 生成写作领域 WorkProduct。

### 9.2 项目网络审查图实例

```text
algorithm_family = tree_reduce + repair_frame

levels:
  file
  directory
  system
  root

nodes:
  file_review_agent
  directory_summary_agent
  system_summary_agent
  root_control_network_curator

outputs:
  file semantic coordinates
  directory semantic map
  signal chain audit
  deep route index
  root human report
```

系统物理层提供文件树和 AST。agent 只在物理层约束下铺语义层。

### 9.3 Repair / Maintenance 图实例

```text
algorithm_family = repair_frame + fanout_join

triggers:
  failed outcome
  missing relation
  stale semantic facet
  git delta
  locate miss

outputs:
  repaired WorkProduct
  relation patch candidate
  generation dirty signal
```

## 10. 存储与生命周期

### 10.1 GraphSystem 存储

```text
ExecutableGraphConfig
GraphRun
GraphLoopState
GraphTimelineEvent
GraphCheckpointRecord
GraphNodeWorkOrder
NodeActivationPlan
NodeAttemptRef
ExecutionTraceBinding
NodeResultEnvelope
FlowPacket
ControlFrame
GraphSuperstep
TransitionPlan audit
```

### 10.2 TaskSystem 存储

```text
TaskCommand
TaskWorkEnvironment
AgentExecutionEpisode
TaskContextPackage
TaskCheckpoint
TaskPlan
TaskTodo
WorkProduct
TaskReducer events
```

### 10.3 Harness 存储

```text
TurnRun
RuntimeAnchor
runtime invocation packet
model action request
action lifecycle records
tool invocation lifecycle
model/tool observations
context compaction / recovery events
latest_event_offset
episode execution diagnostics
```

### 10.4 Domain 存储

写作图：

```text
writing artifacts
writing memory candidates
chapter outputs
review reports
```

项目网络：

```text
unified_control_graph
semantic_coordinates
route_index
signal_chain_index
link_signal_audit
generation record
repair queue
```

## 11. 恢复、暂停、重放和 fork

### 11.1 Resume

```text
latest checkpoint
-> validate config identity
-> restore active frames
-> restore active work orders or requeue attempts
-> dispatch ready nodes if allowed
```

Resume 不解析自然语言，不靠 reason 字符串白名单。

### 11.2 Retry

```text
retry_requested outcome
-> retry control frame
-> same node ready
-> new attempt
-> old result preserved
```

### 11.3 Revision

```text
revision_requested outcome
-> revision control frame
-> invalidation scope
-> target node ready
-> carried revision packet
```

### 11.4 Fork

Fork 必须生成新 `graph_run_id`。

```text
parent_graph_run_id
parent_checkpoint_id
fork_graph_run_id
fork_reason
fork_boundary
```

禁止在原 graph run 上偷偷分叉。

### 11.5 Repair

Repair 是有目的的控制帧。

```text
repair_of_spacetime_ref
repair_scope
repair_reason
expected_patch_kind
```

项目网络维护和 graph node 失败修复都走同源 repair 机制。

## 12. 前端控制面

图任务前端不应只是节点列表。

需要三个视图：

```text
空间视图：
  graph topology
  scopes
  frames
  node contracts
  agent bindings

时间视图：
  timeline
  supersteps
  checkpoints
  attempts
  resume / fork / repair markers

时空视图：
  node invocation frames
  inbound packets
  outputs
  outcome signals
  transition decisions
  control frames
```

前端只消费后端 projection，不重新推断运行状态。

## 13. 目标模块划分

### 13.1 `graph_system`

建议目标结构：

```text
backend/graph_system/
  models.py
  program_models.py
  algorithm_models.py
  outcome_models.py
  control_frame_models.py
  spacetime_models.py
  timeline_models.py
  compiler_contracts.py
  readiness_engine.py
  transition_engine.py
  frame_manager.py
  invalidation_engine.py
  dispatch_planner.py
  loop_engine.py
  tree_reduce_engine.py
  repair_engine.py
  loop.py
  runner.py
  resume.py
  runtime_objects.py
```

### 13.2 `task_system`

```text
backend/task_system/
  commands/
  scheduler/
  work_environments/
  episodes/
  work_products/
  graph_bindings/
  reducer.py
```

### 13.3 `harness`

```text
backend/harness/entrypoint/
  task_environment_episode_bridge.py
  graph_node_work_order_bridge.py

backend/harness/runtime/
  compiler.py
  packet_assembler.py
  control_action_schema.py
  turn_trace_projection.py
  execution_trace_binding.py
```

### 13.4 domain adapters

```text
backend/task_system/writing_graphs/
  runtime_adapters.py
  context_providers.py
  outcome_adapters.py

backend/project_network_tasks/
  template_catalog.py
  runtime_adapters.py
  context_providers.py
  runtime_effects.py
  repair_runtime_service.py
```

## 14. 迁移实施计划

### Phase 1：锁定模型与权威边界

目标：

- 增加 `OutcomeSignal`、`ControlFrame`、`TransitionPolicy` 一等模型。
- 明确 `GraphNode = 图任务空间物理单位`，不是 agent 的同义词。
- 增加节点类别、端口、`NodeExecutionAdapter`、`NodeActivationPlan`。
- 明确只有 `agent_execution_node` 才需要 `AgentBinding + TaskContract + TaskWorkEnvironment`。
- 增加 `GraphTimeRef`、`NodeAttemptRef`、`ExecutionTraceBinding`，把 Graph 外层时间与 HarnessTurnTime 内层时间接起来。

涉及：

```text
backend/graph_system/models.py
backend/graph_system/outcome_models.py
backend/graph_system/control_frame_models.py
backend/graph_system/spacetime_models.py
backend/graph_system/node_adapter_models.py
backend/task_system/compiler/*
backend/harness/runtime/execution_trace_binding.py
```

完成标准：

- 新配置可以声明 node outcome policy 和 edge transition policy。
- 新配置可以区分 agent / resource / memory / artifact / router / materialization / subgraph 节点。
- agent 节点有 agent binding 和 task contract；非 agent 节点不能生成 Harness episode。
- 节点 attempt 能追踪到 turn_run_id、action_request_ref 和 harness event offset。
- GraphSystem core 不出现业务词。

### Phase 2：重写结果归一和边选择

目标：

- `work_order_executor` 不再把所有 postprocess error 压成 failed。
- 新增 `OutcomeNormalizer`。
- `TransitionProcessor` 改为只消费 outcome + transition policy。

涉及：

```text
backend/graph_system/work_order_executor.py
backend/graph_system/outcome_normalizer.py
backend/graph_system/transition_processor.py
backend/graph_system/runtime_algorithm_types.py
```

完成标准：

- 业务返修不会进入 graph failed。
- edge selection 不再依赖 review 文本解析。

### Phase 3：ControlFrame 与失效重放

目标：

- revision / retry / human gate / repair 统一为 control frame。
- `_state_after_revision_requeue` 收缩为 frame manager + invalidation engine。

涉及：

```text
backend/graph_system/loop.py
backend/graph_system/frame_manager.py
backend/graph_system/invalidation_engine.py
backend/graph_system/resume.py
```

完成标准：

- checkpoint 能恢复 active frames。
- 前端和日志能看到 frame 原因、目标、失效范围。

### Phase 4：节点任务环境主线

目标：

- Graph node 执行通过 TaskCommand / TaskWorkEnvironment / Episode。
- NodeResultEnvelope 从 reducer projection 生成。

涉及：

```text
backend/task_system/commands/*
backend/task_system/scheduler/*
backend/task_system/graph_bindings/service.py
backend/harness/entrypoint/graph_node_work_order_bridge.py
backend/graph_system/work_order_executor.py
```

完成标准：

- 每个 node execution 有 command、episode、work product、node result lineage。
- 不再把 GraphNodeWorkOrder 直接等同 TaskRun。

### Phase 5：算法族抽象

目标：

- 把 dag、loop、tree_reduce、fanout_join、repair_frame 做成算法族。
- 写作图和项目网络图只作为实例。

涉及：

```text
backend/graph_system/algorithm_models.py
backend/graph_system/tree_reduce_engine.py
backend/graph_system/dispatch_planner.py
backend/task_system/compiler/executable_graph_config_publisher.py
scripts/configure_writing_modular_novel_graph.py
backend/project_network_tasks/graph_builder.py
```

完成标准：

- 写作图循环和项目网络 tree_reduce 复用 GraphSystem 算法层。
- graph_system 不出现领域特例。

### Phase 6：时空可观测和控制面

目标：

- Timeline、checkpoint、attempt、packet、outcome、frame、superstep 都可查询。
- agent 执行节点可以从图节点跳到 HarnessTurnRun、ModelActionRequest、ToolLifecycle 和 observation trace。
- 前端显示图任务时空控制面。

涉及：

```text
backend/graph_system/timeline_models.py
backend/graph_system/timeline_projection.py
backend/graph_system/spacetime_projection.py
backend/harness/runtime/turn_trace_projection.py
backend/api/graph_system.py
frontend task runtime workbench
```

完成标准：

- 用户能看到每个节点为什么 ready、为什么 blocked、为什么返修、从哪里恢复。
- 用户能从节点 attempt 进入 agent 内部 turn trace，但前端不把 Harness turn 当成图状态重新推断依据。

## 15. 验收标准

成熟图任务架构必须通过以下检查：

| 能力 | 验收 |
| --- | --- |
| 通用算法 | 写作图、项目网络图、repair 图不需要修改 graph core |
| 节点契约 | 每个 agent 节点都有 agent binding + task contract + output contract |
| 节点物理模型 | agent、resource、memory、artifact、router、materialization、subgraph 节点类别清楚，非 agent 节点不生成 Harness episode |
| outcome 分离 | 业务返修不等于 technical failed |
| 策略消费 | transition/readiness policy 是运行裁决，不只是 snapshot |
| 控制 frame | revision/retry/repair/human gate 都能 checkpoint 和恢复 |
| 任务环境 | graph node 执行有 TaskCommand、Episode、WorkProduct |
| 内外时间桥接 | GraphTime 追踪 superstep/node attempt/frame/checkpoint；HarnessTurnTime 追踪 turn/action/tool/observation；二者通过 ExecutionTraceBinding 关联 |
| 并发控制 | 并发由 GraphSystem dispatch + TaskScheduler lease 控制 |
| 可恢复 | checkpoint 恢复 active frames 和 pending work |
| 可审计 | timeline 可追踪 work order、result、packet、outcome、frame、turn_run_id、action_request_ref |
| 领域隔离 | 写作、项目网络、维护逻辑全部在 adapter / task package |

## 16. 严禁反模式

1. 在 `GraphSystem` 写业务 node id 特例。
2. 在 transition 层解析自然语言结论。
3. 用 `status=failed` 表达业务不通过。
4. 节点契约写成开发说明。
5. 把 agent 配置和任务契约混成一个配置块。
6. 让 GraphLoop 直接调模型。
7. 让项目网络 store 调度 agent。
8. 用自然语言报告反解析为结构事实。
9. 用旧 TaskRun 继续承担节点任务环境。
10. 把 retry / revision / repair 做成三个分散特殊分支。
11. 让前端重新推断图状态。
12. 为兼容旧链路保留第二套运行权威。
13. 把 Harness `TurnRun` 当成 `Task` 或 `GraphRun`。
14. 让 GraphSystem 根据 Harness 内部 tool/action trace 直接选边。

## 17. 最终裁决

图任务的目标架构不是“更灵活的 DAG”，而是：

```text
一个把复杂任务空间物理节点化、把 agent 执行契约程序化、把外层图时间和内层 Harness turn 时间都结构化、把恢复和返修 frame 化的复杂任务操作系统。
```

最终链路必须固定为：

```text
GraphProgram
-> ExecutableGraphConfig
-> GraphRun
-> Algorithm Dispatch
-> NodeActivationPlan
-> NodeExecutionAdapter
-> GraphNodeWorkOrder / RepositoryOperation / MaterializationIntent / ControlDecision
-> TaskCommand only for agent_execution_node
-> TaskWorkEnvironment
-> AgentExecutionEpisode
-> HarnessTurnRun
-> ModelActionRequest / ToolLifecycle / Observation
-> EpisodeResult
-> WorkProduct / RepositoryReceipt / MaterializationReceipt
-> NodeResultEnvelope
-> ExecutionTraceBinding
-> OutcomeSignal
-> TransitionPlan
-> ControlFrame / Checkpoint
-> Next Dispatch
```

这条链路建立后：

- 写作图是一个循环迭代 + 审核返修实例。
- 项目网络审查图是一个 tree_reduce + repair 实例。
- 维护图是一个 git delta + repair frame 实例。
- 所有图任务共享同一个程序化节点时空运行底座；agent 只是其中一种可执行节点，Harness turn 是该节点内部的执行时序。

后续实施必须先修图任务母体，再迁移具体实例；不能继续围绕某个写作节点或某个项目网络产物打补丁。
