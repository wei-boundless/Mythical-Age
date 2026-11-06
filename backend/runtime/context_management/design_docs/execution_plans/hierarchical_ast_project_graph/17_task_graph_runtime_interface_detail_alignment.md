# 任务环境与图任务运行接口细节对接方案

状态：细节对接方案，待审阅后实施  
日期：2026-07-04  
前置文档：`15_persistent_task_work_environment_spine_plan.md`、`16_unified_agent_task_project_control_overall_plan.md`、`agent_source_audits/00_turn_session_task_reference_synthesis.md`

## 1. 文档定位

第 16 号文档已经锁定总体架构。本文件只解决下一层问题：如何把现有源码里的 `TaskRun`、`AgentRun`、`GraphNodeWorkOrder`、`NodeResultEnvelope`、`compile_task_execution_packet()` 和旧 `task_executor` 断点，对接到成熟的任务环境与图任务运行接口。

本文件不是新的原则文档，也不是立即实施代码的补丁清单。它要固定以下细节：

```text
任务身份怎么命名
任务环境由谁拥有
图节点如何绑定任务环境
agent 一次进入任务环境如何记录
上下文包如何拼装
产物如何回写
NodeResultEnvelope 如何从 WorkProduct 投影
旧 TaskRun / AgentRun 如何过渡
哪些旧链路必须清理
```

核心目标：

```text
GraphNodeWorkOrder
-> GraphNodeTaskBinding
-> TaskWorkEnvironment
-> AgentExecutionEpisode
-> WorkProduct
-> NodeResultEnvelope
-> GraphLoop.accept_node_result()
```

图任务仍然是复杂任务的算法母体，单 agent 运行仍然由 harness 主脊柱执行，任务系统负责持久工作环境和产物归并。

### 1.1 为什么要设计任务环境

任务环境的价值不是把普通 turn 包装得更复杂，而是提供普通 turn 天生不该承担的工作能力。

普通 turn 的本质是当前交互节拍：

```text
用户当前请求
-> 当前上下文
-> agent 本轮判断和行动
-> 本轮回答或提交
```

它可以很复杂，也可以读文件、改代码、运行工具、做验证。只要工作能在当前回合内收口，它仍然是普通 turn。

任务环境的本质是持久工作场：

```text
独立目标
独立范围
独立状态
独立记忆
独立产物
独立证据
独立恢复点
独立验收标准
```

也就是说，任务环境不是为了让 agent “多想一会儿”，而是为了让 agent 拥有一个可持续工作的外部结构。它把一项工作从聊天流里抽出来，变成系统可管理、agent 可继续、产物可消费、状态可审计的工作单元。

如果没有任务环境，复杂工作只能退化成：

```text
更长的上下文
更多的动态尾提示
反复让 agent 重新读文件
靠聊天记录恢复进度
靠自然语言报告充当产物
靠人工记住哪些节点做过
```

这些都不是成熟 agent 架构。成熟系统必须把“对话连续性”和“工作连续性”分开。

### 1.2 任务环境可以提供什么

任务环境至少要向 agent 提供十类强化。

| 能力 | 提供给 agent 的内容 | 普通 turn 的不足 |
| --- | --- | --- |
| 持久身份 | `task_environment_id`、`task_instance_id`、当前 owner、当前状态 | turn 结束后没有独立工作身份 |
| 生命周期 | active、paused、waiting、blocked、completed、archived | 普通 turn 只能本轮完成、询问或中断 |
| 工作契约 | 目标、范围、角色、禁止事项、验收标准、失败表达方式 | 容易把开发说明、用户闲聊和任务边界混在一起 |
| 上下文包 | stable context、current context、memory refs、artifact refs、graph context | 容易依赖完整聊天记录或动态尾堆叠 |
| 任务记忆 | 决策、未解问题、恢复提示、稳定事实、历史产物索引 | 稳定事实会反复插入上下文，污染当前注意力 |
| 产物空间 | WorkProduct、报告、结构化 payload、证据 refs、下游 refs | assistant message 不适合作为可消费产物 |
| 证据空间 | 文件切片、AST refs、工具观察、审查证据、artifact refs | 证据容易散落在 transcript 和工具输出里 |
| 权限和工具边界 | 当前任务允许的文件、工具、写入范围、审批策略 | 普通 turn 的工具范围难以表达长期工作边界 |
| 恢复与交接 | checkpoint、continuation hint、episode history、lease | 中断后只能靠回放对话和猜下一步 |
| 调度接口 | graph node binding、work order、retry policy、并发和回传 | 普通 turn 不能成为图任务节点的稳定执行体 |

这些强化共同指向一个目的：

```text
让 agent 不必靠记忆硬撑复杂工作，
而是靠系统提供的工作环境进行定位、恢复、审查、交付和维护。
```

### 1.3 任务环境与普通 turn 的硬区别

| 维度 | 普通 turn | 任务环境 |
| --- | --- | --- |
| 核心问题 | 当前用户这句话怎么处理 | 这项工作如何持续推进 |
| 身份 | `turn_id` / `turn_run_id` | `task_environment_id` / `task_instance_id` |
| 上下文来源 | 会话历史、当前消息、动态上下文 | TaskContextPackage、任务记忆、产物、证据、恢复提示 |
| 状态 | 本轮运行状态 | 持久任务状态 |
| 记忆 | session / turn 级记忆 | task memory + project memory refs |
| 输出 | assistant 回复、工具观察、当前提交 | WorkProduct、TaskState update、artifact、NodeResultEnvelope |
| 恢复 | 恢复当前交互或从历史推断 | 从 checkpoint、continuation hint、work product 和 task state 恢复 |
| 调度 | 用户触发当前回合 | 用户、图任务、repair、maintenance 都可调度 |
| 验收 | 本轮是否回答好 | 任务目标是否达成、产物是否可消费 |
| 审计 | turn trace | task timeline + episode ledger + evidence refs |

任务环境不是普通 turn 的上位替代。正确关系是：

```text
普通 turn 负责当前交互。
任务环境负责持久工作。
AgentExecutionEpisode 是 agent 进入任务环境工作的一次运行片段。
```

### 1.4 任务环境对项目控制网络的意义

项目控制网络尤其需要任务环境，因为它不是一次回答，而是一套长期资产的生产、发布和维护。

没有任务环境时，项目语义网络构建会出现几个问题：

- 单文件审查结果无法稳定成为可追踪产物；
- 目录汇总不知道哪些子节点已完成、哪些是候选、哪些需要 repair；
- 根报告和机器索引容易混成一段自然语言；
- git 修改后无法知道哪些语义 facet 和信号链路需要更新；
- graph node 中断后只能重跑或靠人工补；
- agent 不能从一个明确的工作状态继续，只能重新读项目。

有任务环境后，项目网络构建可以变成：

```text
每个审查节点 = 一个可恢复的 TaskWorkEnvironment
每次 agent 工作 = 一个 AgentExecutionEpisode
每个审查结果 = 一个 WorkProduct
每层汇总 = 一组可归并的 WorkProduct
最终发布 = project_network_system generation
后续维护 = repair / maintenance task environment
```

这就是任务环境存在的核心理由：它把 agent 的智能判断接入系统的持久控制能力，让复杂项目工作从“聊天式推进”升级为“工作环境式推进”。

### 1.5 新任务系统的任务场景预测

新任务系统的价值应通过真实场景验证。它至少会带来以下实际能力，并规避对应风险。

| 场景 | 新任务系统带来的能力 | 可规避的风险 |
| --- | --- | --- |
| 项目语义网络构建 | 把文件审查、目录汇总、根报告、语义坐标、链路信号拆成可调度、可恢复、可归并的任务环境 | 大项目审查中断后重跑；报告只有根目录一份；文件级产物丢失；candidate 关系被误发布 |
| 大型架构重构 | 为重构建立独立目标、范围、阶段、验收、证据、影响面和 continuation hint | agent 只围绕当前 turn 修补；忘记前置裁决；中途上下文丢失；旧链路以兼容名义回流 |
| 长链路 debug | 保存假设、已查证据、失败路径、命令观察、当前 blocker 和下一步恢复点 | 反复查同一文件；重复跑无效命令；把旧观察当最新事实；中断后无法继续追查 |
| Git 变更后的项目网络维护 | 根据 git delta 找到受影响物理节点，生成 repair task，局部更新语义 facet 和信号链路 | 项目网络快速过期；全量重审成本过高；修改者理解的语义变化无法沉淀 |
| 多 agent 审查图任务 | 每个节点有独立 TaskWorkEnvironment、WorkProduct 和 NodeResultEnvelope，父层只消费归并产物 | 多 agent 输出散乱；并发节点互相污染；父节点重新读源码；图节点失败无法定位 |
| 跨 session 持续工作 | 用户换会话或 agent 中断后，可通过 task state、work products、memory refs 和 continuation hint 恢复 | 把 session transcript 当任务真相；依赖用户手工复述；恢复时目标漂移 |
| 设计方案和实施计划 | 把调研、源码依据、裁决、阶段计划、风险控制和验证标准沉淀为 WorkProduct | 规划只停留在聊天回复；后续实施找不到依据；原则正确但接口缺失 |
| 人类审批和阻塞等待 | 任务可进入 `waiting_user`、`waiting_external`、`blocked`，保留上下文和下一步 | agent 为了收口强行猜；等待期间上下文丢失；审批结果和任务状态脱节 |
| 可审计工具执行 | episode ledger 记录工具调用、证据 refs、状态更新和产物来源 | 工具观察只存在 transcript；无法追溯某个结论来自哪个文件或命令 |
| 产物驱动的后续自动化 | WorkProduct 可被 graph_system、project_network_system、repair/maintenance 消费 | assistant message 被当作结构化产物；后续系统需要反解析自然语言 |

这些场景说明任务系统的核心收益不是“能跑更久”，而是：

```text
工作有身份
进度有状态
上下文有边界
证据有引用
产物有格式
中断有恢复
失败有归因
后续系统有可消费输入
```

因此，新任务系统应优先服务于三类高价值工作：

1. 需要跨 session 持续推进的工作。
2. 需要被图任务调度和归并的工作。
3. 需要产出可被后续系统消费的 WorkProduct 的工作。

不应把所有复杂 turn 都升级为任务。普通代码修改、单次问答、当前回合可完成的文件阅读和局部修复，仍应由普通 turn 完成。

## 2. 当前源码约束

### 2.1 `TaskRun` 不是新的任务真相

当前 `backend/runtime/shared/models.py` 中：

```text
TaskRun:
  task_run_id
  session_id
  task_id
  task_run_contract_ref
  owner_agent_seat_id
  agent_id
  agent_profile_id
  execution_runtime_kind
  status
  latest_event_offset
  latest_checkpoint_ref
```

关键约束：

- `TaskRun` 强制需要 `session_id`。
- `TaskRun` 的 authority 是 `runtime.task_run`。
- 字段更像一次 runtime task trace / execution lease，而不是跨 session 的任务工作环境。
- 因此不能把 `TaskRun` 直接升级成 `TaskWorkEnvironment`。

裁决：

```text
TaskRun 在迁移期只作为 runtime trace / legacy projection。
TaskWorkEnvironment 才是任务真相。
```

### 2.2 `AgentRun` 接近 episode trace，但还不够

当前 `AgentRun`：

```text
agent_run_id
task_run_id
agent_id
agent_profile_id
role
spawn_mode
context_scope
execution_runtime_kind
parent_agent_run_ref
status
latest_checkpoint_ref
result_ref
```

它可以投影到 `AgentExecutionEpisode`，但缺少：

- `task_environment_id`
- `input_context_package_ref`
- `tool_scope_ref`
- `event_ledger_ref`
- `output_work_product_refs`
- `continuation_hint`
- `terminal_reason`

裁决：

```text
AgentRun 可以保留为 runtime 观测投影。
AgentExecutionEpisode 是任务系统的 canonical episode。
```

### 2.3 `GraphNodeWorkOrder` 当前已经有足够的调度输入

当前 `backend/graph_system/models.py` 中 `GraphNodeWorkOrder` 已有：

```text
work_order_id
work_kind
graph_run_id
task_run_id
node_id
task_ref
config_id
config_hash
agent_id
agent_profile_id
message
explicit_inputs
input_package
graph_slot
graph_state
context_refs
memory_view_request
artifact_view_request
file_view_request
permission_scope
tool_scope
expected_result_contract
async_policy
retry_policy
timeout_policy
dispatch_context
idempotency_key
```

这些字段足够表达图节点的输入、资源视图、权限、工具、预期结果和幂等调度。

问题不是缺字段，而是执行接线错误：`GraphNodeWorkOrder` 当前会被 `runtime_facade.execute_graph_agent_work_order()` 转成旧 `TaskRun`，再调用 `harness.loop.task_executor.execute_task_run()`。

裁决：

```text
GraphNodeWorkOrder 只负责图调度请求。
它不能直接等同 TaskRun，也不能直接触发旧 task_executor 模型循环。
```

### 2.4 `NodeResultEnvelope` 已经接近正确边界

当前 `NodeResultEnvelope` 要求：

```text
result_id
graph_run_id
task_run_id
node_id
work_order_id
status
outputs
decisions
artifact_refs
memory_candidates
progress_receipts
artifact_materialization_receipts
memory_commit_receipts
handoff_summary
error
```

这说明 GraphLoop 已经不应该消费自由文本，而应该消费节点结果信封。

需要补强的是来源：

```text
NodeResultEnvelope 不应直接来自 assistant final answer。
NodeResultEnvelope 应由 EpisodeResult + WorkProduct + TaskReducer projection 生成。
```

### 2.5 `GraphLoop` 的调度模型可以保留

当前 `GraphLoop.dispatch_ready()` 已按 `max_active_nodes` 和 `active_work_orders` 控制并发；`accept_node_result()` 检查 active work order，并推进节点状态。

裁决：

```text
GraphLoop 是状态推进权威。
后续不重写 GraphLoop，只把 work order 执行体改接到 TaskWorkEnvironment / AgentExecutionEpisode。
```

### 2.6 `compile_task_execution_packet()` 可复用，但必须改输入

当前 `backend/harness/runtime/compiler.py` 有 `compile_task_execution_packet()`，并且已经存在：

```text
task_environment_ref
graph_slot
memory_context
bound_task_context
current_attention_index
cache_boundary.placement = volatile_tail
```

这说明当前 compiler 有可复用的上下文投影能力。

问题是它仍绑定旧 task execution packet 和旧 executor service。

裁决：

```text
保留 compiler 的 packet 编译职责。
把 compile_task_execution_packet() 改向 TaskContextPackage，或新增 compile_task_episode_packet() 后清理旧入口。
```

## 3. 成熟架构不变量

基于 `agent_source_audits/00_turn_session_task_reference_synthesis.md`，本项目采用以下不变量：

```text
Turn != Session != TaskWorkEnvironment != AgentExecutionEpisode != WorkProduct
```

落到工程接口：

- session 只提供对话连续性；
- task 保存目标、状态、owner、events、artifacts、recovery；
- runtime run 保存一次可观测执行；
- graph runtime 调度节点，不执行模型；
- work product 独立于 assistant message；
- resume 只能从 durable boundary 开始；
- tool retry 必须受幂等与 retry policy 约束；
- graph node 必须收敛到统一 agent runtime，而不是有第二套模型循环。

## 4. 身份模型

### 4.1 目标身份表

| 身份 | 权威系统 | 是否跨 session | 是否图绑定 | 是否用户可见 | 用途 |
| --- | --- | --- | --- | --- | --- |
| `conversation_session_id` | `sessions` | 否 | 否 | 是 | 对话连续性和 UI 入口 |
| `turn_run_id` | `runtime` | 否 | 否 | 通常否 | 一次普通 turn 执行 trace |
| `task_id` | `task_system` | 是 | 可选 | 是 | 任务定义或任务实例的业务身份 |
| `task_instance_id` | `task_system` | 是 | 可选 | 是 | 一项持久工作的实例身份 |
| `task_environment_id` | `task_system` | 是 | 可选 | 可见 | 任务工作环境权威身份 |
| `session_task_binding_id` | `task_system` / `sessions` | 否 | 可选 | 可见 | session 对任务的视图绑定 |
| `episode_id` | `task_system` | 是 | 可选 | 通常否 | agent 进入任务环境的一次工作片段 |
| `agent_run_id` | `runtime` | 否/投影 | 可选 | 否 | runtime 观测投影 |
| `graph_run_id` | `graph_system` | 是 | 是 | 是 | 一次图运行身份 |
| `work_order_id` | `graph_system` | 是 | 是 | 否 | 图节点调度请求身份 |
| `graph_node_task_binding_id` | `task_system` | 是 | 是 | 否 | work order 与 task environment 的绑定身份 |
| `node_result_id` | `graph_system` | 是 | 是 | 否 | GraphLoop 消费的节点结果身份 |
| `work_product_id` | `task_system` / domain store | 是 | 可选 | 可见 | 可消费产物身份 |
| `generation_id` | `project_network_system` | 是 | 否 | 可见 | 项目网络发布代际身份 |

### 4.2 旧字段映射

| 旧字段 | 迁移解释 | 不允许的解释 |
| --- | --- | --- |
| `TaskRun.session_id` | runtime trace 所属 session 或 graph node session | 跨 session 任务真相 |
| `TaskRun.task_id` | legacy task ref / task instance projection | 完整任务环境 |
| `TaskRun.task_run_id` | legacy runtime task trace id | 新任务环境唯一身份 |
| `AgentRun.agent_run_id` | episode runtime projection id | 完整 episode truth |
| `GraphRun.task_run_id` | graph 所属父任务或 legacy runtime anchor | 每个节点的子任务真相 |
| `GraphNodeWorkOrder.task_run_id` | graph parent task/run anchor | 节点内部 TaskWorkEnvironment |
| `NodeResultEnvelope.task_run_id` | graph parent task/run anchor，迁移期保留 | work product owner |

新增要求：

```text
GraphNodeWorkOrder.dispatch_context.graph_node_task_binding_id
GraphNodeWorkOrder.dispatch_context.task_environment_id
GraphNodeWorkOrder.dispatch_context.episode_policy_ref
NodeResultEnvelope.diagnostics.source_episode_id
NodeResultEnvelope.diagnostics.source_work_product_refs
```

长期可提升为显式字段，但第一阶段可先放入 `dispatch_context` / `diagnostics`，避免一次性破坏 GraphLoop schema。

## 5. 生命周期

### 5.1 TaskInstance

状态：

```text
draft
active
paused
waiting_user
waiting_external
completed
failed
aborted
archived
```

合法转移：

```text
draft -> active
active -> paused / waiting_user / waiting_external / completed / failed / aborted
paused -> active / aborted / archived
waiting_user -> active / aborted
waiting_external -> active / failed / aborted
completed -> archived
failed -> archived
aborted -> archived
```

禁止：

- `completed -> active`
- `archived -> active`
- `failed -> active` 直接复活；必须创建 repair task 或 new attempt。

### 5.2 TaskWorkEnvironment

状态：

```text
created
ready
leased
paused
blocked
completed
archived
```

语义：

- `created`：环境身份已分配，存储尚未完全准备。
- `ready`：可被 episode lease。
- `leased`：某个 episode 正在使用。
- `paused`：可恢复，但暂不调度。
- `blocked`：缺少用户、外部资源或修复条件。
- `completed`：任务目标完成，环境只读。
- `archived`：归档，不参与调度。

禁止：

- 多个非幂等 episode 同时 lease 同一环境。
- `archived` 环境被 graph node 继续调度。
- 系统在 `created` 环境中直接执行模型。

### 5.3 AgentExecutionEpisode

状态：

```text
scheduled
running
waiting_tool
waiting_user
interrupted
completed
failed
aborted
```

完成规则：

- `completed` 必须有 `EpisodeResult`。
- `interrupted` 必须有 save point 或 continuation hint。
- `failed` 必须有 machine-readable reason。
- `waiting_tool` 必须记录 tool call refs 和 retry policy。

### 5.4 WorkProduct

状态：

```text
candidate
accepted
rejected
superseded
published
```

规则：

- agent 只能产出 `candidate` 或带证据的 `accepted_claim`。
- reducer / curator 决定是否进入 `accepted`。
- project network generation 决定是否 `published`。
- `candidate` 不得伪装成物理事实。

### 5.5 GraphRun

保留现有状态推进，但补充运行语义：

```text
created
running
waiting_executor
waiting_human_gate
paused
completed
failed
aborted
```

GraphLoop 只根据 `NodeResultEnvelope` 推进，不根据 assistant message 推进。

## 6. 运行接口

### 6.1 TaskExecutionRequest

创建或继续任务环境的入口请求。

```text
TaskExecutionRequest
  request_id: str
  caller_kind: "user_turn" | "graph_node" | "repair" | "maintenance" | "api"
  session_id: str
  task_instance_id: str
  task_environment_id: str
  task_goal: str
  task_contract_ref: str
  acceptance_contract_ref: str
  requested_episode_kind: str
  requested_agent_profile_id: str
  input_refs: dict
  visible_user_request: str
  graph_binding_ref: str
  continuation_ref: str
  priority: str
  idempotency_key: str
```

创建规则：

- `task_goal`、`task_contract_ref`、`acceptance_contract_ref` 至少要能表达任务边界。
- `caller_kind=graph_node` 时必须有 `graph_binding_ref`。
- `requested_agent_profile_id` 不存在时只能使用任务模板默认 profile，不能系统猜角色。

### 6.2 TaskEnvironmentLease

episode 使用任务环境前必须获得 lease。

```text
TaskEnvironmentLease
  lease_id: str
  task_environment_id: str
  episode_id: str
  lease_kind: "exclusive" | "shared_read" | "idempotent_retry"
  caller_kind: str
  graph_run_id: str
  work_order_id: str
  expires_at: float
  heartbeat_ref: str
  resumable: bool
  idempotency_key: str
```

规则：

- 普通 agent 写任务状态时使用 `exclusive`。
- 目录汇总类只读聚合可使用 `shared_read`。
- 重试必须声明 `idempotent_retry`，并复用同一 `work_order_id` 或明确 attempt ref。

### 6.3 TaskContextPackage

agent episode 的上下文输入。

```text
TaskContextPackage
  package_id: str
  task_environment_id: str
  task_instance_id: str
  episode_id: str
  package_version: str
  stable_context:
    task_goal
    role_contract
    acceptance_contract
    permission_scope
    tool_scope
    physical_refs
    semantic_network_refs
  current_context:
    current_step
    active_lease
    current_user_steer
    latest_observations
    retry_feedback
    graph_node_input
    continuation_hint
  memory_refs:
    task_memory_refs
    project_memory_refs
    relevant_work_product_refs
  artifact_refs:
    evidence_refs
    file_slice_refs
    report_refs
  graph_context:
    graph_run_id
    node_id
    work_order_id
    inbound_result_refs
    expected_result_contract
  packet_policy:
    stable_prefix_policy
    volatile_tail_policy
    ref_materialization_policy
    budget_policy
  diagnostics:
    source
    compiler_entrypoint
```

上下文分层：

| 区域 | 可放入 | 不可放入 |
| --- | --- | --- |
| `stable_context` | 任务目标、角色、验收、权限、工具范围、稳定物理 ref | 当前 todo、最新 tool observation、每轮变化的重试反馈 |
| `current_context` | 当前步骤、lease、最新观察、用户 steer、恢复提示 | 长期项目事实、完整旧 transcript |
| `memory_refs` | 任务记忆、项目记忆、相关 work product ref | 重复复制大段记忆正文 |
| `artifact_refs` | 文件切片、报告、证据 ref | 未经系统提供的裸路径猜测 |
| `graph_context` | work order、inbound refs、expected contract | 领域 store 的私有实现 |

这对应当前 compiler 里 `current_attention_index.cache_boundary.placement = volatile_tail` 的方向：变化快的注意力索引放动态尾，不把它封进稳定 prefix。

### 6.4 AgentExecutionEpisode

```text
AgentExecutionEpisode
  episode_id: str
  task_environment_id: str
  task_instance_id: str
  agent_id: str
  agent_profile_id: str
  invocation_kind: str
  caller_kind: str
  input_context_package_ref: str
  lease_id: str
  runtime_trace_refs:
    turn_run_id
    agent_run_id
    provider_request_refs
    tool_call_refs
  graph_binding_ref: str
  status: str
  started_at: float
  ended_at: float
  latest_checkpoint_ref: str
  continuation_hint: str
  terminal_reason: str
  diagnostics: dict
```

规则：

- episode 是 agent 工作片段，不是任务本体。
- episode 内部必须复用 harness 单 agent 主脊柱。
- episode 可以产生多个 tool step 和 provider step。
- episode 结束后必须进入 reducer。

### 6.5 EpisodeResult

```text
EpisodeResult
  episode_result_id: str
  episode_id: str
  task_environment_id: str
  status: "completed" | "failed" | "blocked" | "interrupted"
  final_response_ref: str
  structured_output: dict
  work_product_candidates: tuple[dict]
  artifact_refs: tuple[str]
  memory_candidates: tuple[dict]
  state_update_proposals: tuple[dict]
  acceptance_claims: tuple[dict]
  continuation_hint: str
  error: dict
  diagnostics: dict
```

注意：

```text
assistant message 只是 final_response_ref 或人类可读摘要来源。
可消费结果必须进入 structured_output / work_product_candidates / artifact_refs。
```

### 6.6 WorkProduct

通用任务系统需要一个领域无关的 WorkProduct。项目网络现有 `GraphBuildWorkProductEnvelope` 是它的领域子类型。

```text
WorkProduct
  work_product_id: str
  task_environment_id: str
  source_episode_id: str
  product_kind: str
  product_domain: str
  stable_ref: str
  payload_ref: str
  structured_payload: dict
  evidence_refs: tuple[str]
  anchor_refs: tuple[str]
  artifact_refs: tuple[str]
  confidence: "deterministic" | "derived" | "hypothesis" | "rejected" | "needs_human_review"
  status: "candidate" | "accepted" | "rejected" | "superseded" | "published"
  acceptance_claims: tuple[dict]
  downstream_refs: dict
  generation: int
  metadata: dict
```

项目网络映射：

```text
WorkProduct(product_domain="project_network")
-> GraphBuildWorkProductEnvelope
-> ProjectNetworkBuildService.ingest_work_products()
-> ProjectNetworkGenerationRecord
```

资产归属与生产机制必须分离：

```text
project_network_system
  是项目控制网络的独立长期资产系统。
  它保存统一项目控制图、semantic facets、signal chain、generation、repair records。

graph_system + project_network_tasks
  是语义网络的生产线。
  graph_system 提供图任务调度、tree_reduce、checkpoint、resume、work order 和 node result。
  project_network_tasks 提供审查任务模板、context provider、runtime adapter 和领域输出契约。

task_system
  为每个审查节点提供 TaskWorkEnvironment、AgentExecutionEpisode 和 WorkProduct 归并。
```

因此语义网络的建立不是 `project_network_system` 自己执行，也不是 agent 在 store 里自由写图，而是：

```text
物理骨架由 file_management 提供
-> 审查任务由 graph_system 调度
-> agent 在 TaskWorkEnvironment 中产出 WorkProduct
-> reducer / curator 接收候选语义
-> project_network_system 发布 generation
```

### 6.7 TaskReducerInput

episode 结束后，系统不直接把输出塞回 session，而是归并任务环境。

```text
TaskReducerInput
  task_environment_id: str
  episode_id: str
  episode_result_ref: str
  work_product_candidates: tuple[WorkProduct]
  state_update_proposals: tuple[dict]
  memory_candidates: tuple[dict]
  artifact_refs: tuple[str]
  graph_binding_ref: str
  reduction_policy: str
```

Reducer 负责：

- 更新 TaskWorkEnvironment 状态；
- 写 TaskEventLedger；
- 写 TaskMemorySpace 候选或 accepted memory；
- 写 WorkProduct store；
- 触发领域 ingest；
- 生成 NodeResultEnvelope projection；
- 释放 lease。

Reducer 不负责：

- 重新解释 agent 没有输出的语义；
- 从自然语言报告反解析结构事实；
- 替 agent 补充未声明的证据。

### 6.8 GraphNodeTaskBinding

图节点与任务环境之间的绑定。

```text
GraphNodeTaskBinding
  binding_id: str
  graph_run_id: str
  graph_id: str
  config_id: str
  structure_hash: str
  node_id: str
  work_order_id: str
  parent_task_environment_id: str
  node_task_environment_id: str
  task_instance_id: str
  task_ref: str
  agent_profile_id: str
  input_package_ref: str
  expected_result_contract_ref: str
  lease_policy: dict
  result_projection_policy: dict
  idempotency_key: str
  status: str
```

规则：

- 一个 active `work_order_id` 对应一个 active binding。
- retry 复用 binding，并增加 attempt / episode。
- binding 不创建 graph topology，不直接执行模型。
- binding 的输出只能通过 reducer 投影为 NodeResultEnvelope。

## 7. 固定执行流

### 7.1 显式任务启动

```text
agent emits request_task_run
-> RuntimeFacade validates action shape
-> TaskExecutionRequest
-> TaskWorkEnvironmentService.create_or_resume()
-> TaskContextPackageBuilder.build_initial()
-> return task_environment receipt to current turn
```

第一阶段只创建任务环境和初始上下文，不自动进入旧 executor。

### 7.2 继续任务

```text
task_environment_id
-> TaskWorkEnvironmentService.acquire_lease()
-> TaskContextPackageBuilder.build_for_episode()
-> RuntimeCompiler.compile_task_episode_packet()
-> Harness single-agent execution
-> EpisodeResult
-> TaskReducer.reduce()
-> release lease
```

继续任务不得依赖完整 session transcript。必须由 task environment、work products、memory refs、artifact refs 和 continuation hint 重建上下文。

### 7.3 图节点执行

```text
GraphLoop.dispatch_ready()
-> GraphNodeWorkOrder
-> GraphNodeTaskBindingService.bind()
-> TaskWorkEnvironmentService.create_or_resume(caller_kind=graph_node)
-> AgentExecutionEpisode
-> WorkProduct
-> TaskReducer.reduce()
-> NodeResultEnvelopeProjection
-> GraphLoop.accept_node_result()
```

旧链：

```text
GraphNodeWorkOrder
-> _create_graph_node_task_run()
-> task_executor.execute_task_run()
```

迁移后必须删除或降级为 legacy projection，不再承担模型执行。

### 7.4 项目语义网络建立

项目控制网络是独立系统，但项目语义网络必须由图任务审查生产线建立。

```text
file_management.project_structure
-> physical skeleton / stable refs / file slices
-> project_network_tasks.compile_build_graph()
-> graph_system tree_reduce run
-> file review node TaskWorkEnvironment
-> directory aggregate node TaskWorkEnvironment
-> root summary node TaskWorkEnvironment
-> WorkProduct candidates
-> TaskReducer / ProjectNetworkCurator
-> project_network_system generation
```

分工：

- `file_management` 负责物理事实，不写语义判断。
- `graph_system` 负责审查任务的拓扑、并发、回传、checkpoint 和 resume。
- `project_network_tasks` 负责把项目网络构建需求编译成审查图任务。
- `task_system` 负责让每个审查节点成为可恢复的任务环境。
- `agent` 负责在证据约束下建立语义 facet、语义坐标和候选链路信号。
- `project_network_system` 负责保存、归并、审计、发布和维护项目控制网络。

禁止：

- 让 `project_network_system` 直接调度 agent 审查。
- 让 `graph_system` 保存项目网络长期资产。
- 让审查 agent 绕过物理骨架自由铺语义网。
- 让自然语言报告直接成为 published semantic graph。

### 7.5 repair / maintenance

```text
MaintenanceSignal
-> RepairWorkItem
-> RepairTaskExecutionRequest
-> TaskWorkEnvironment(caller_kind=repair)
-> AgentExecutionEpisode
-> WorkProduct
-> same generation / next generation
```

repair 和 maintenance 必须同源。断线补图、语义过期、git delta、locate miss 都进入同一个 signal -> work item -> task environment -> work product 链。

## 8. 上下文包与动态尾规则

第 16 号文档已经确认：不能用动态尾承载所有事实。

本文件把规则落到字段：

### 8.1 进入 stable prefix 的内容

```text
role_contract
task_goal
acceptance_contract
permission_scope
tool_scope
physical_ref table
semantic coordinate refs
expected output contract
```

这些内容变化低，适合稳定前缀或 session stable context。

### 8.2 进入 current context / volatile tail 的内容

```text
current_step
active_lease
current_attention_index
latest_tool_observations
retry_feedback
user_steer
unfinished action status
current inbound graph packet summary
```

这些内容每次 episode 或每个调度点可能变化，必须保持 volatile。

### 8.3 只进入 ref 的内容

```text
完整旧 transcript
大文件全文
大量 AST 节点
历史 work products
目录级全部报告
完整项目网络图
```

agent 需要时通过工具或系统投影读取，不反复塞进 prompt。

### 8.4 禁止

- 把稳定事实每轮重复插入动态尾。
- 把当前 todo 封进 provider global prefix。
- 把旧 session transcript 当任务恢复事实。
- 把大报告自然语言塞入 graph node 输入，让节点自行反解析。
- 把文件路径猜测当 physical ref。

## 9. Prompt 契约字段

任务节点 prompt 必须是 agent 可执行的工作契约。

推荐结构：

```text
你是谁
你只负责什么
你会收到哪些输入
你不能做什么
你必须产出什么
怎样判断合格
证据不足时如何表达
失败或阻塞时如何交付
```

图节点契约必须落到 `TaskContextPackage.stable_context.role_contract` 和 `expected_result_contract`，不能只藏在模板描述里。

### 9.1 单文件项目网络审查契约示例

```text
你是一名单文件项目控制语义审查员。
你只负责系统提供的一个物理文件。
你的任务是在该文件的物理骨架上建立可被后续 agent 使用的语义坐标、控制路标和候选链路信号。
你不能读取其它文件，不能搜索项目，不能伪造物理关系，不能把猜测写成 accepted。
你会收到文件路径、文件内容、系统抽取的符号骨架、直接 import/export 信号、父目录的审查目标和输出契约。
你必须输出文件级语义坐标、模块职责、关键 symbol 说明、入站/出站候选关系、证据引用、限制项和后续修复建议。
当证据不足时，把关系写入 candidate 或 limitations，并说明缺少哪类证据。
```

### 9.2 目录汇总契约示例

```text
你是一名目录级项目控制语义汇总员。
你只消费系统提供的直接文件审查结果和直接子目录汇总结果。
你不重新审查源码，不展开孙目录，不把自然语言摘要反推成结构事实。
你要为父层提交压缩后的语义路标、目录职责、覆盖率、冲突、候选跨模块关系和需要 repair 的断点。
你必须区分 accepted relation、candidate relation 和 unresolved signal。
```

## 10. 存储边界

| 系统 | 拥有 | 不拥有 |
| --- | --- | --- |
| `sessions` | conversation session、可见消息、session-task view binding | 任务真相、项目网络 generation |
| `runtime` / `harness` | TurnRun、runtime trace、tool/model loop、output commit | TaskWorkEnvironment truth、GraphLoop state、项目语义资产 |
| `task_system` | TaskInstance、TaskWorkEnvironment、Episode、TaskEventLedger、通用 WorkProduct refs | 项目网络长期 store、图算法执行、模型循环 |
| `graph_system` | GraphRun、GraphLoopState、WorkOrder、NodeResultEnvelope、checkpoint、resume | 领域语义判断、项目网络资产、单 agent 模型循环 |
| `file_management` | git、file tree、deep AST、physical refs、slices | agent 语义判断、project generation |
| `project_network_system` | 统一项目控制图、semantic facets、signal chain、generation、repair records | GraphLoop 调度、单 agent 执行 |
| `project_network_tasks` | 项目网络任务模板、context provider、adapter、tree_reduce 编译 | 长期资产 store、图核心调度 |

## 11. 文件级改造清单

### 11.1 新增 task environment 模块

```text
backend/task_system/work_environments/models.py
backend/task_system/work_environments/repository.py
backend/task_system/work_environments/service.py
backend/task_system/work_environments/context_package_builder.py
```

职责：

- `TaskInstance`
- `TaskWorkEnvironment`
- `SessionTaskBinding`
- `TaskContextPackage`
- `TaskEnvironmentLease`

### 11.2 新增 episode 模块

```text
backend/task_system/episodes/models.py
backend/task_system/episodes/repository.py
backend/task_system/episodes/service.py
```

职责：

- `AgentExecutionEpisode`
- `EpisodeResult`
- episode event refs
- continuation hint

### 11.3 新增通用 work product 模块

```text
backend/task_system/work_products/models.py
backend/task_system/work_products/repository.py
backend/task_system/work_products/reducer.py
```

职责：

- 通用 `WorkProduct`
- `TaskReducerInput`
- domain projection hook
- NodeResultEnvelope projection

### 11.4 改造 harness

```text
backend/harness/entrypoint/runtime_facade.py
backend/harness/runtime/compiler.py
backend/harness/runtime/packet_assembler.py
backend/harness/loop/single_agent_turn.py
backend/harness/loop/task_executor.py
```

动作：

- `request_task_run` 接回 TaskWorkEnvironment 创建，不接回旧 executor。
- 新增或改造 `compile_task_episode_packet(TaskContextPackage)`。
- `execute_graph_agent_work_order()` 改为调用 GraphNodeTaskBinding / TaskWorkEnvironment / Episode 服务。
- `task_executor.py` 降级，清理模型循环权威。

### 11.5 改造 graph_system

```text
backend/graph_system/models.py
backend/graph_system/context_materializer.py
backend/graph_system/work_order_executor.py
backend/graph_system/loop.py
backend/graph_system/resume.py
```

动作：

- `GraphNodeWorkOrder.dispatch_context` 写入 binding hints。
- `work_order_executor` 不再直接调用旧 TaskRun executor。
- `NodeResultEnvelope` 保持 GraphLoop 输入权威。
- resume 记录 episode / binding lineage。

### 11.6 改造 project network 接入

```text
backend/project_network_system/work_product_models.py
backend/project_network_system/service.py
backend/project_network_tasks/directory_runtime_service.py
backend/project_network_tasks/repair_runtime_service.py
```

动作：

- `GraphBuildWorkProductEnvelope` 作为 domain WorkProduct projection。
- 领域 ingest 只消费 reducer accepted / candidate product。
- repair 复用同一 WorkProduct / generation 链。

## 12. 分阶段实施与完成标准

### Phase A：模型与只读投影

目标：

- 新增 TaskWorkEnvironment / Episode / WorkProduct 模型。
- 现有 TaskRun / AgentRun / GraphNodeWorkOrder 可投影到新模型。
- 不改变运行行为。

完成标准：

```text
TaskRun 不再被文档或新代码解释为任务真相。
AgentRun 可映射为 episode trace。
GraphNodeWorkOrder 可生成 GraphNodeTaskBinding projection。
```

### Phase B：request_task_run 接回环境分配

目标：

- `request_task_run` 不再只返回 cut receipt。
- 只创建任务环境、初始上下文和 receipt。
- 不启动旧 executor。

完成标准：

```text
agent 能拿到 task_environment_id。
session 只得到 binding receipt。
没有旧 task_executor 模型循环被调用。
```

### Phase C：TaskContextPackage 接入 compiler

目标：

- 新增 `compile_task_episode_packet()` 或重定向 `compile_task_execution_packet()`。
- compiler 输入从散乱 task state 改为 TaskContextPackage。

完成标准：

```text
stable_context / current_context / refs / graph_context 分层清晰。
current_attention_index 仍在 volatile tail。
继续任务不依赖完整旧 transcript。
```

### Phase D：episode 执行复用 harness 主脊柱

目标：

- AgentExecutionEpisode 内部走 single-agent harness。
- tool admission、tool control plane、output commit 不分叉。

完成标准：

```text
没有第二 model loop。
没有第二 tool authorization path。
没有第二 assistant output commit path。
EpisodeResult 可被 reducer 消费。
```

### Phase E：图节点接入任务环境

目标：

- `GraphNodeWorkOrder -> GraphNodeTaskBinding -> TaskWorkEnvironment` 成为主线。
- `NodeResultEnvelope` 从 reducer projection 生成。

完成标准：

```text
GraphLoop 只接收 NodeResultEnvelope。
work_order_id 与 episode/work_product 有可追踪 lineage。
旧 _create_graph_node_task_run() 不再承担执行创建主线。
```

### Phase F：领域 WorkProduct 与项目网络 generation 接通

目标：

- 通用 WorkProduct 可投影成 `GraphBuildWorkProductEnvelope`。
- project_network_system ingest 不直接吃 assistant answer。

完成标准：

```text
根报告、层级报告、文件报告、语义坐标、链路信号都来自 WorkProduct。
candidate / accepted / published 分层明确。
generation 可追溯 source_episode_id。
```

### Phase G：清理旧链路

目标：

- 按项目要求，清理旧执行权威和无用兼容壳。

检查：

```powershell
rg -n "execute_task_run\\(" backend/harness backend/graph_system
rg -n "call_model_invoker|call_model_streamer" backend/harness/loop/task_executor.py
rg -n "_create_graph_node_task_run" backend
rg -n "TaskRun\\(" backend/harness backend/graph_system backend/task_system
```

完成标准：

- 旧 executor 不再作为模型执行主线。
- 旧 TaskRun 只作为 legacy runtime projection 或已清理。
- 没有以兼容为名保留第二套运行链。

## 13. 验证方式

按项目规则，不新增回归测试文件，不伪造产物。

### 13.1 静态审查

```powershell
rg -n "TaskWorkEnvironment|AgentExecutionEpisode|TaskContextPackage|WorkProduct" backend/task_system backend/harness backend/graph_system
rg -n "execute_graph_agent_work_order|_create_graph_node_task_run|execute_task_run\\(" backend/harness backend/graph_system
rg -n "call_model_invoker|call_model_streamer" backend/harness/loop/task_executor.py
python -m compileall backend/harness backend/task_system backend/graph_system backend/project_network_system backend/project_network_tasks
```

### 13.2 真实运行

涉及运行链路时固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
```

验证场景：

1. 普通 turn 不创建任务环境。
2. 合格 `request_task_run` 返回 `task_environment_id`。
3. 继续任务能从 TaskContextPackage 恢复，不需要完整旧 transcript。
4. 图节点执行能产生 episode、work product、NodeResultEnvelope。
5. tree_reduce 项目网络构建能产出文件报告、目录报告、根报告、语义坐标和链路信号。
6. repair signal 能创建 repair task，并写回同一 generation lineage。

## 14. 架构不变量

```text
TaskWorkEnvironment 是任务真相。
TaskRun 不是任务真相。
AgentExecutionEpisode 是一次 agent 工作片段。
GraphNodeWorkOrder 是调度请求，不是 agent 执行循环。
GraphLoop 是图状态推进权威。
NodeResultEnvelope 是 GraphLoop 的唯一节点结果输入。
WorkProduct 是可消费产物，不是聊天消息。
TaskContextPackage 是 episode 输入，不是全量历史。
稳定事实进任务记忆和 stable refs，当前变化进 volatile tail。
项目网络物理事实来自 file_management，语义来自 agent 受证据约束的 WorkProduct。
```

## 15. 严禁反模式

1. 把 `TaskRun` 当新的 `TaskWorkEnvironment`。
2. 在旧 `task_executor.py` 外面包新接口继续跑模型。
3. 让 graph_system 直接执行模型。
4. 让 task_system 直接拥有项目网络长期 store。
5. 把 graph node prompt 写成开发说明。
6. 让 `NodeResultEnvelope` 直接消费 assistant final answer。
7. 把 stable facts 反复插入 dynamic tail。
8. 用完整 session transcript 恢复任务。
9. 让 agent 伪造 physical refs。
10. 把 candidate relation 写成 accepted relation。
11. 用自然语言报告反解析结构事实。
12. 以兼容为名保留旧主链。

## 16. 最终接口裁决

本阶段必须锁定的工程方向是：

```text
task_system 提供持久任务环境。
harness 提供单 agent 执行底座。
graph_system 提供图任务算法和状态推进。
project_network_system 提供项目控制网络资产。
file_management 提供物理事实。
project_network_tasks 提供项目网络任务包。
```

任务与图任务的关键接口不是 prompt，而是：

```text
TaskExecutionRequest
TaskEnvironmentLease
TaskContextPackage
AgentExecutionEpisode
EpisodeResult
WorkProduct
TaskReducerInput
GraphNodeTaskBinding
NodeResultEnvelope
```

这套接口能把用户说的“任务像系统管理的人类工作环境，agent 是智能输入输出体”落成工程结构：系统提供工作空间、资源、状态、证据、产物和恢复；agent 在其中判断和行动；图任务用算法调度这些工作片段；项目控制网络消费最终产物形成长期语义和神经控制面。
