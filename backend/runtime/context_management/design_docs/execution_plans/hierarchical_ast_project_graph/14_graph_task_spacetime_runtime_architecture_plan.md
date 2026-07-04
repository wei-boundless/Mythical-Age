# 图任务时空运行体系架构计划

状态：设计计划，待审阅后实施  
日期：2026-07-03  
前置文档：`13_graph_task_task_system_file_system_boundary_optimization_plan.md`

## 1. 问题定义

当前图任务系统已经具备可运行的主链路：

```text
TaskGraphDefinition
-> ExecutableGraphConfig
-> GraphRuntimeEnvelope
-> GraphLoop
-> GraphNodeWorkOrder
-> NodeResultEnvelope
-> FlowPacket
-> GraphLoopState / Checkpoint
```

但它仍然更像“图结构 + 当前状态机”，还没有形成完整的“时空任务运行体系”。

缺失的系统属性不是某个字段，而是三类统一性：

1. 空间统一性：节点、边、loop frame、subgraph、resource、agent slot、context provider 还没有统一的空间坐标。
2. 时间统一性：event cursor、checkpoint、dispatch seq、node attempt、runner iteration、result history 都存在，但没有统一的时间坐标和生命周期。
3. 时空统一性：某个 agent 在某个图运行、某个空间位置、某个调度轮次里读取了什么、输出了什么、影响了哪些下游，目前需要跨多个对象反推。

正确的终态应当是：

```text
每个图任务执行都能回答：

在哪个不可变图结构里？
在哪个运行宇宙里？
在哪个空间节点 / scope / loop frame / 子图里？
处于哪个 graph clock / super-step / dispatch round？
这个 work order 是第几次派发 / 第几次尝试？
它消费了哪些 checkpoint、flow packet、上游 result、资源快照？
它产生的 result / packet / side effect 在哪个时间点被接受？
失败、恢复、重试、fork、repair 与原时间线是什么关系？
```

这个体系的目标不是让 graph_system 更复杂，而是让图任务成为 agent 的真实运行底座：可追踪、可恢复、可 fork、可局部修复、可解释、可用于项目级语义网络和多 agent 协作。

### 1.1 核心定义：图任务是单 agent 的算法化时空扩展

图任务不是另一个 agent 系统，也不是把 agent 拆成机械步骤。

图任务应被定义为：

```text
Graph Task = Contracted Single-Agent Execution Network
图任务 = 单 agent 契约执行网络
```

更准确地说，它可以被理解为一个“活的程序”：

```text
ExecutableGraphConfig      = 程序的不可变结构定义
GraphRun                   = 一次程序运行实例
GraphLoop                  = 程序的事件循环 / 调度器
GraphLoopState             = 当前运行状态切片
GraphNodeWorkOrder         = 一次函数调用帧
Agent Runtime / Harness    = 函数本身的执行系统
Task Contract              = 函数签名 + 语义契约 + 输出约束
NodeResultEnvelope         = 函数返回值
FlowPacket                 = 跨函数传递的参数 / 信号 / 返回引用
Checkpoint                 = 可恢复的运行切片
Timeline Event             = 程序执行过的事实事件
```

这个类比的核心不是把 agent 降级为普通函数，而是明确权威边界：

- 图任务负责形成程序结构、运行时间、状态推进、调度策略、恢复、重放、审计和可视化。
- 单 agent 运行系统负责真正执行一个任务契约，它不是图里的“说明文字”，而是一次完整的 agent 判断与产出。
- 节点不是开发者写给系统看的技术节点，而是一个单 agent 可执行的任务契约位。
- 边不是普通连线，而是上下文、结果、资源、控制信号和可见性边界的传递规则。
- 算法不是语义判断者，而是调度策略：loop、tree reduce、fan-out、repair、fork、replay 都只决定何时调用哪个契约位。

因此，节点契约必须能回答：

```text
你是谁？
你负责什么？
你能看什么？
你不能做什么？
你要产出什么？
什么算合格？
失败或不确定时如何表达？
```

系统职责：

- 分解任务。
- 编排空间。
- 调度时间。
- 注入资源。
- 收集结果。
- 推进状态。
- 记录事件。
- 恢复、重放、fork 和 repair。

agent 职责：

- 理解任务契约。
- 做语义判断。
- 处理当前局部任务。
- 输出结构化 work product。
- 说明不确定性、阻塞点和失败原因。

明确禁止的反模式：

- 把节点写成“这是 runtime 节点”“执行某某步骤”这类开发说明。
- 让图算法替代 agent 的语义判断。
- 把无限上下文塞给一个 agent，而不是通过契约、层级和算法拆分。
- 把项目网络、写作图、审查图等领域逻辑写进 graph_system core。
- 让系统以兜底名义覆盖 agent 的合法表达；系统只能校验边界、协议和状态推进。

## 2. 当前系统来源审查

### 2.1 空间结构现状

当前空间权威主要在：

```text
backend/graph_system/models.py
  ExecutableGraphConfig
  GraphRuntimeEnvelope
  GraphRun

backend/graph_system/context_materializer.py
  GraphContextMaterializer
  GraphNodeExecutionSlot projection

backend/task_system/compiler/executable_graph_config_publisher.py
  TaskGraphDefinition -> ExecutableGraphConfig
```

已具备的空间能力：

- `ExecutableGraphConfig` 拥有 `nodes`、`edges`、`loop_frames`、`resources`、`memory`、`artifacts`、`contracts`。
- `content_hash` 与 `expected_structural_hash()` 已经把“图配置身份”和“结构身份”区分开。
- `GraphRuntimeEnvelope` 已经携带 `static_topology_view`、`contract_index`、`state_machine_spec`、`loop_control_spec`。
- `GraphContextMaterializer` 已能把节点编译成 `GraphNodeWorkOrder` 和 `GraphNodeExecutionSlot`。
- 第 13 号计划已把领域 adapter/provider 抽离，`graph_system` 已回到通用母体。

缺口：

- `loop_frames` 目前是配置字典，不是正式的空间 frame 模型。
- 节点、边、资源、provider 注入的上下文，没有统一 `space_ref` / `scope_path`。
- 子图、tree_reduce frame、repair frame、动态展开图仍然主要靠业务 metadata 表达。

### 2.2 时间推进现状

当前时间权威主要在：

```text
backend/graph_system/loop.py
  GraphLoop.initialize()
  GraphLoop.dispatch_ready_and_checkpoint()
  GraphLoop.accept_node_result()

backend/graph_system/runner.py
  GraphRunRunner.run_until_idle()

backend/graph_system/checkpoint_store.py
backend/graph_system/langgraph_checkpoint_store.py

backend/graph_system/resume.py
```

已具备的时间能力：

- `GraphLoopState.event_cursor` 是当前图运行的时间游标。
- `GraphLoop.initialize()`、`dispatch_ready_and_checkpoint()`、`accept_node_result()` 会推进状态并写 checkpoint。
- `GraphRunRunner` 有 loop iteration、dispatch budget、node execution budget。
- `LangGraphCheckpointStore` 已经把 `graph_loop_state`、`active_work_orders`、`work_order_index`、`event_cursor` 写入 checkpoint channel。
- `GraphResumeService` 已经能根据 checkpoint 恢复 blocked / failed / active work orders。

缺口：

- `event_cursor` 只是数值游标，还没有独立的 `GraphClock` / `SuperStep` / `Attempt` 模型。
- runner iteration、dispatch count、node dispatch seq、event cursor 各自存在，但没有统一语义。
- checkpoint 是恢复事实，但 event history 还没有成为 replay / fork / audit 的一等时间线。
- pending writes 只通过 LangGraph checkpointer 适配器暴露，还没有成为 graph_system 的通用模型。

### 2.3 信号传播现状

当前信号传播主要在：

```text
backend/graph_system/flow_packet.py
backend/graph_system/transition_processor.py
backend/graph_system/flow_edges.py
backend/graph_system/edge_contracts.py
```

已具备的能力：

- `FlowPacket` 具备 `graph_run_id`、`task_run_id`、`source_unit_id`、`target_unit_id`、`edge_id`、`payload_refs`、`artifact_refs`、`memory_refs`、`result_refs`、`lineage`。
- `GraphTransitionProcessor` 能在节点结果被接受后更新 edge state，并在需要时持久化 flow packet。
- `flow_packet_inbound_projection()` 能把 packet 投影为下游 inbound context。

缺口：

- FlowPacket lineage 是局部链路，不足以表达完整时空坐标。
- Edge transition 与 event history 的关系还不够强：edge state 是结果，transition event 是旁路记录。
- 多轮 repair、fork 后的 packet 与原 packet 的血缘关系还没有标准字段。

## 3. 外部成熟参考

### 3.1 LangGraph 可借鉴点

LangGraph 官方文档把 persistence 分成 checkpointer 与 store：checkpointer 保存单个 thread 的图状态快照，store 保存跨 thread 的长期数据。它还明确 checkpointer 支持 human-in-the-loop、time travel、fault tolerance 和 pending writes。

可借鉴不变量：

- thread/run 是 checkpoint 的主键边界。
- checkpoint 是 super-step 边界的状态快照。
- pending writes 用于同一 super-step 内成功节点的恢复，避免恢复时重跑已经成功的节点。
- checkpoint namespace 用于区分父图和子图。
- time travel / fork 必须以 checkpoint 边界为起点。

不照搬点：

- 不把当前 GraphLoop 替换成 LangGraph runner。
- 不把所有业务状态塞进 LangGraph state channel。
- 不让 LangGraph checkpointer 成为 graph_system 的调度权威。

本项目已经正确选择了“只借 checkpointer contract，不借 runner”的路线，`LangGraphCheckpointStore` 注释中也明确 GraphLoop 仍是唯一状态推进权威。

参考：

- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/checkpointers

### 3.2 Temporal 可借鉴点

Temporal 把 Workflow Definition、Workflow Type、Workflow Execution 区分开；每个 Workflow Execution 产生 commands 并处理 events，Event History 是恢复和 replay 的权威。外部 I/O 被建模为 Activity，Activity 结果写入 Event History，replay 时复用结果而不是重做外部副作用。

可借鉴不变量：

- Definition 和 Execution 必须分离。
- Event History 是执行发生过什么的顺序事实。
- Replay 不应重新执行外部副作用。
- 工作流逻辑必须尽量 deterministic；非确定性必须记录为事件或活动结果。

不照搬点：

- 不要求本项目短期做到完整 event-sourcing replay。
- 不要求 GraphLoop 每次从 event history 重放构建 state。
- 不把 LLM 调用变成 Temporal Activity；本项目已有 TaskRun / WorkOrder 执行边界。

参考：

- https://docs.temporal.io/workflows

## 4. 目标架构

### 4.1 三层时空模型

目标模型分三层：

```text
Spatial Plane
  不可变图结构、scope、loop frame、subgraph、resource、agent slot。

Temporal Plane
  graph clock、super-step、dispatch round、attempt、event history、checkpoint、pending writes。

Spacetime Plane
  某个 work order / result / packet / side effect 在某个空间坐标和时间坐标上的事实。
```

### 4.2 空间坐标 GraphSpaceRef

新增概念：

```text
GraphSpaceRef
  graph_id
  config_id
  structure_hash
  scope_path
  scope_kind
  frame_id
  parent_frame_id
  node_id
  edge_id
  resource_ref
```

职责：

- 表达“在哪个图空间里”。
- 不表达运行时间。
- 不读取 checkpoint。
- 不判断节点是否 ready。

来源：

- `ExecutableGraphConfig`
- `loop_frames`
- `resources`
- node / edge / contract index
- domain provider 注册的 scope keys

### 4.3 时间坐标 GraphTimeRef

新增概念：

```text
GraphTimeRef
  graph_run_id
  task_run_id
  graph_clock_seq
  event_cursor
  superstep_id
  dispatch_round
  node_dispatch_seq
  attempt
  checkpoint_id
  parent_checkpoint_id
```

职责：

- 表达“在运行时间线的哪个点”。
- 统一 runner iteration、dispatch count、event cursor、node dispatch seq 的语义。
- 让 resume / retry / fork / repair 能说明自己从哪里来。

来源：

- `GraphLoopState.event_cursor`
- `GraphRunRunner` dispatch/execution counters
- `GraphCheckpointRecord`
- `GraphNodeWorkOrder`
- event log

### 4.4 时空坐标 GraphSpacetimeRef

新增概念：

```text
GraphSpacetimeRef
  space: GraphSpaceRef
  time: GraphTimeRef
  execution_ref:
    work_order_id
    result_id
    packet_id
    side_effect_ref
  lineage:
    parent_spacetime_ref
    replay_of
    forked_from
    repair_of
    supersedes
```

职责：

- 每个 work order、result、flow packet、side effect 都能落在一个明确坐标上。
- 下游 agent 不需要猜“这个输入来自哪个节点第几轮输出”。
- 调试界面可以按图空间或时间线检索。

## 5. 权威边界

### 5.1 GraphConfig 是空间定义权威

`ExecutableGraphConfig` 仍是不可变空间定义。

禁止：

- 运行中修改 `nodes` / `edges`。
- 在 GraphLoopState 里偷偷追加新空间结构。
- 让 domain adapter 修改 graph topology。

允许：

- 动态展开生成新的 `ExecutableGraphConfig` generation。
- 子图 / repair 图通过新的 config_id 表达。
- 原图和新图用 lineage 关联，不共享可变 topology。

### 5.2 GraphLoop 是当前状态推进权威

短期仍保持：

```text
GraphLoopState checkpoint = resume 的直接恢复对象
GraphLoop = 状态推进权威
Event history = 审计、回放、fork 的事实线
```

中长期升级：

```text
Event history = replay / fork / audit 权威
Checkpoint = 加速恢复快照
```

这个升级必须分阶段，不能一次性把 GraphLoop 改成 event-sourced runner。

### 5.3 WorkOrder 是 agent 执行的时空包

`GraphNodeWorkOrder` 应升级为明确携带：

```text
space_ref
time_ref
spacetime_ref
input_checkpoint_ref
input_packet_refs
attempt_policy
replay_policy
```

WorkOrder 只能执行当前坐标的任务，不能推进图状态。

### 5.4 NodeResult 是时间线上的提交，不是状态本身

`NodeResultEnvelope` 应明确：

```text
produced_at_time_ref
consumed_work_order_spacetime_ref
side_effect_refs
flow_packet_refs
candidate_state_updates
```

GraphLoop 接受 result 后，才产生正式状态推进、edge transition 和 checkpoint。

### 5.5 FlowPacket 是跨空间传播的信号

FlowPacket 应升级为：

```text
source_spacetime_ref
target_space_ref
accepted_at_time_ref
packet_generation
fork_lineage
visibility_boundary
```

它不应该只是一条 edge payload，而应成为跨节点传播的可审计信号。

## 6. 固定运行流程

目标流程：

```text
1. Publish Space
   TaskGraphDefinition -> ExecutableGraphConfig
   输出不可变 config_id / content_hash / structure_hash

2. Start Runtime Universe
   ExecutableGraphConfig + initial_inputs -> GraphRuntimeEnvelope -> GraphRun
   输出 graph_run_id / initial GraphTimeRef

3. Initialize Time Slice
   GraphLoop.initialize()
   输出 GraphLoopState(event_cursor=0), checkpoint, start events

4. Dispatch Superstep
   GraphLoop.dispatch_ready_and_checkpoint()
   为每个 ready node 生成 GraphNodeWorkOrder
   每个 work order 带 GraphSpacetimeRef

5. Execute Node Attempt
   Runner 执行 WorkOrder
   外部副作用只发生在节点执行层
   输出 NodeResultEnvelope

6. Accept Result
   GraphLoop.accept_node_result()
   校验 WorkOrder 坐标
   写 NodeResult
   规划 edge transitions
   生成 FlowPacket
   推进 GraphLoopState
   写 Event + Checkpoint

7. Resume / Replay / Fork
   Resume 默认从 latest checkpoint 恢复
   Replay / fork 必须声明 checkpoint_id 与 parent time ref
   成功节点 pending writes 不重跑
```

## 7. 数据模型设计

### 7.1 新增 graph_system/spacetime_models.py

建议新增：

```python
GraphSpaceRef
GraphTimeRef
GraphSpacetimeRef
GraphEventRef
GraphCheckpointRef
GraphAttemptRef
GraphForkLineage
```

这些模型只做坐标、身份和 lineage，不承载业务 payload。

### 7.2 扩展 GraphLoopState

新增字段建议：

```text
graph_clock_seq: int
superstep_seq: int
latest_checkpoint_id: str
latest_event_ref: dict
timeline_summary: dict
fork_lineage: dict
```

兼容策略：

- 旧 `event_cursor` 保留，短期仍作为 checkpoint id 的 step 来源。
- `graph_clock_seq` 初期可等于 `event_cursor`，但语义上明确为图时钟。
- `superstep_seq` 只在 dispatch boundary 推进。

### 7.3 扩展 GraphNodeWorkOrder

新增字段建议：

```text
space_ref: dict
time_ref: dict
spacetime_ref: dict
attempt_ref: dict
input_checkpoint_ref: dict
input_packet_refs: tuple[dict, ...]
replay_policy: dict
```

其中：

- `node_dispatch_seq` 表示同一 node 在当前 graph run 中第几次派发。
- `attempt` 表示同一 work_order 或同一 node dispatch 的第几次执行尝试。
- retry 不应覆盖旧 result，必须形成新 attempt。

### 7.4 扩展 NodeResultEnvelope

新增字段建议：

```text
work_order_spacetime_ref: dict
result_time_ref: dict
consumed_packet_refs: tuple[dict, ...]
produced_packet_refs: tuple[dict, ...]
side_effect_refs: tuple[dict, ...]
replay_status: str
lineage: dict
```

### 7.5 扩展 FlowPacket

新增字段建议：

```text
source_spacetime_ref: dict
target_space_ref: dict
accepted_time_ref: dict
packet_generation: int
parent_packet_ref: str
fork_lineage: dict
```

### 7.6 新增 GraphTimelineEvent

当前 event log 已经存在，但 graph_system 内部没有统一事件模型。建议新增：

```text
GraphTimelineEvent
  event_id
  graph_run_id
  graph_id
  config_id
  event_cursor
  graph_clock_seq
  superstep_seq
  event_kind
  subject_space_ref
  subject_spacetime_ref
  payload_ref
  payload_summary
  causality_refs
  created_at
  authority
```

事件类型第一批：

```text
graph_initialized
superstep_dispatched
node_work_order_created
node_attempt_started
node_result_accepted
edge_transition_committed
flow_packet_committed
checkpoint_committed
resume_loaded
replay_started
fork_created
repair_requeued
graph_terminal
```

## 8. 子图、动态展开与 Tree Reduce

### 8.1 子图必须有 checkpoint namespace

借鉴 LangGraph checkpoint namespace，但不照搬命名：

```text
root graph namespace:
  graph_run_id

subgraph namespace:
  graph_run_id/scope_path/frame_id

tree_reduce frame namespace:
  graph_run_id/tree_reduce/<frame_id>

repair namespace:
  graph_run_id/repair/<repair_batch_id>
```

用途：

- 子图状态不污染父图 checkpoint。
- 父图只接收子图 publish 的 result / packet。
- 子图可以独立 replay / repair。

### 8.2 动态展开不是修改原图

动态展开应生成新空间版本：

```text
parent_config_id
-> child_config_id
-> dynamic_generation_id
```

父图只记录：

```text
dynamic_graph_materialized event
child_config_ref
child_graph_run_ref
handoff packet
```

禁止：

- 在原 `ExecutableGraphConfig.nodes` 里追加节点。
- 在旧 checkpoint 里塞新拓扑。

### 8.3 Tree Reduce 的时空语义

Tree Reduce 应固定为：

```text
物理下探 = 空间展开
子节点审查 = 子空间 work orders
回传汇总 = 时间线上的 child return packets
父节点汇总 = 当前 frame 的 reduce superstep
```

项目网络目录树已经很接近这个模型，后续只需要把 frame / return / aggregate work product 的时空坐标补齐。

## 9. 恢复、重试、Fork、Repair 规则

### 9.1 Resume

Resume 默认：

```text
latest checkpoint
-> validate config identity
-> recover active work orders
-> dispatch ready if allowed
```

补强：

- ResumeResult 必须带 `resume_time_ref`。
- 每次 resume 写 `resume_loaded` event。
- 如果 active work order 被恢复，必须保留原 work_order_id，并追加 attempt。

### 9.2 Retry

Retry 不是覆盖：

```text
same node_id
new attempt_ref
new result_id
same or new work_order_id 由 retry_policy 决定
lineage.retry_of = previous_attempt_ref
```

### 9.3 Replay

Replay 必须声明：

```text
source_checkpoint_id
replay_from_time_ref
replay_mode
```

初期只支持：

- 从 checkpoint 恢复 state。
- checkpoint 之前的 node result 不重跑。
- checkpoint 之后重新派发。

后续再支持 event history 全量重放。

### 9.4 Fork

Fork 必须生成新 `graph_run_id`，不能在原 graph_run 上分叉。

```text
parent_graph_run_id
parent_checkpoint_id
fork_graph_run_id
fork_reason
fork_boundary
```

Fork 后：

- 共享同一个 `ExecutableGraphConfig`，除非动态展开生成新 config。
- 不共享 active work_orders。
- 可引用父 timeline，但不修改父 timeline。

### 9.5 Repair

Repair 是带目的的 fork/requeue，不是普通 retry。

Repair 必须声明：

```text
repair_of_spacetime_ref
repair_scope_ref
repair_reason_codes
expected_repaired_outputs
```

项目网络维护 agent 可以使用同一套 lineage，不需要另建补网系统。

## 10. 前端与可观测性

图任务前端应从“节点状态列表”升级为“时空观察面板”：

```text
空间视图：
  GraphConfig topology
  scope tree
  loop frames
  subgraphs
  resource/context slots

时间视图：
  event timeline
  supersteps
  checkpoints
  dispatch rounds
  attempts
  resume/replay/fork markers

时空视图：
  点击一个节点，看到每次派发、每次 attempt、输入 packet、输出 result、下游 packet。
  点击一个 checkpoint，看到当时 ready/running/completed/blocked 状态。
  点击一个 FlowPacket，看到 source result、target node、visibility、lineage。
```

前端不应重新推断状态，只消费后端投影：

```text
GraphTimelineProjection
GraphSpaceProjection
GraphSpacetimeTraceProjection
```

## 11. 实施计划

### Phase 1：时空模型与投影，不改变运行语义

目标：

- 新增坐标模型。
- 为现有对象生成只读时空投影。
- 不改 GraphLoop 状态推进。

文件：

```text
backend/graph_system/spacetime_models.py
backend/graph_system/spacetime_projection.py
backend/graph_system/models.py
backend/graph_system/context_materializer.py
backend/graph_system/flow_packet.py
```

验收：

- 现有图任务可运行。
- 每个 WorkOrder / FlowPacket 可投影出 `GraphSpacetimeRef`。
- 不新增领域专用逻辑到 graph_system。

### Phase 2：GraphClock 与 Superstep 语义固定

目标：

- 明确 `event_cursor`、`graph_clock_seq`、`superstep_seq`、`dispatch_round` 的关系。
- Dispatch boundary 与 result acceptance boundary 分离。

文件：

```text
backend/graph_system/loop.py
backend/graph_system/runner.py
backend/graph_system/checkpoint_store.py
backend/graph_system/langgraph_checkpoint_store.py
```

规则：

```text
dispatch_ready_and_checkpoint -> superstep_seq + 1
accept_node_result -> event_cursor + 1
checkpoint -> 记录 graph_clock_seq / superstep_seq / event_cursor
```

验收：

- checkpoint metadata 可看到 graph clock。
- runner summary 可看到 superstep / dispatch / attempt。

### Phase 3：WorkOrder / Result / Packet 坐标化

目标：

- WorkOrder 输入带 checkpoint、packet、space、time。
- NodeResult 回传携带 work_order 坐标。
- FlowPacket 携带 source/target 时空 ref。

文件：

```text
backend/graph_system/models.py
backend/graph_system/context_materializer.py
backend/graph_system/flow_packet.py
backend/graph_system/runtime_objects.py
backend/graph_system/work_order_executor.py
```

验收：

- 对任意 active work order，可以追溯输入 checkpoint 与 inbound packets。
- 对任意 flow packet，可以追溯 source result 与 target node。

### Phase 4：Timeline Event 模型与事件索引

目标：

- 新增标准 GraphTimelineEvent。
- 现有 event_log append 统一补充 graph spacetime fields。
- 提供 timeline query。

文件：

```text
backend/graph_system/timeline_models.py
backend/graph_system/timeline_projection.py
backend/graph_system/loop.py
backend/graph_system/runner.py
backend/graph_system/resume.py
backend/graph_system/facade.py
```

验收：

- 可按 graph_run_id 查询完整时间线。
- 可按 node_id 查询该节点所有 attempt。
- 可按 checkpoint_id 查询前后事件。

### Phase 5：Replay / Fork / Repair 统一控制

目标：

- Resume、Replay、Fork、Repair 用统一 lineage。
- 引入 fork graph run，不在原 run 上分叉。

文件：

```text
backend/graph_system/resume.py
backend/graph_system/fork.py
backend/graph_system/replay.py
backend/graph_system/runner.py
backend/project_network_tasks/repair_runtime_service.py
```

验收：

- 从 checkpoint fork 出新 graph_run。
- 原 graph_run 不被修改。
- repair 任务可声明 `repair_of_spacetime_ref`。

### Phase 6：前端时空观察面板

目标：

- 后端提供投影 API。
- 前端展示空间、时间、时空三面板。

文件：

```text
backend/graph_system/facade.py
backend/api/*
frontend graph/task monitor pages
```

验收：

- 可以查看 graph run 的 timeline。
- 可以点击节点查看 attempts / packets / results。
- 可以点击 checkpoint 触发 replay/fork 入口。

## 12. 文件级执行清单

第一批应修改：

```text
backend/graph_system/spacetime_models.py           新增
backend/graph_system/spacetime_projection.py       新增
backend/graph_system/timeline_models.py            新增
backend/graph_system/timeline_projection.py        新增
backend/graph_system/models.py                     扩展 GraphLoopState / WorkOrder / Result 坐标字段
backend/graph_system/context_materializer.py       生成 WorkOrder spacetime ref
backend/graph_system/flow_packet.py                生成 packet spacetime lineage
backend/graph_system/loop.py                       写入 graph clock / timeline event
backend/graph_system/runner.py                     暴露 superstep / attempt summary
backend/graph_system/resume.py                     resume event 和 lineage
backend/graph_system/langgraph_checkpoint_store.py checkpoint metadata 扩展
backend/graph_system/facade.py                     timeline projection API
```

暂不应修改：

```text
project_network_system
project_network_tasks
task_system compiler
file_management
```

除非它们需要消费新的时空 ref。第一阶段应避免让领域系统反向影响 graph core。

## 13. 迁移与切换规则

### 13.1 兼容窗口

允许短期同时存在：

```text
event_cursor
graph_clock_seq
superstep_seq
```

但必须定义关系，不能各自自由增长。

### 13.2 旧 checkpoint 读取

旧 checkpoint 缺少新字段时：

```text
graph_clock_seq = event_cursor
superstep_seq = 0 或从 metadata 推导
latest_checkpoint_id = checkpoint_id
fork_lineage = {}
```

这是数据读取归一化，不是旧运行链路。

### 13.3 Cutover

切换点：

- WorkOrder 生成已经带 spacetime ref。
- NodeResult acceptance 校验 spacetime ref。
- FlowPacket lineage 使用 spacetime ref。
- Timeline projection 可从现有 event/checkpoint 推导。

### 13.4 Rollback

若新时空字段出现问题：

- GraphLoop 仍以旧 `GraphLoopState` 核心字段推进。
- 新字段只作为 projection / diagnostics 忽略。
- 不回退结构迁移，不恢复领域逻辑到 graph_system。

## 14. 风险控制

### 风险 1：把时空体系做成重型 event sourcing

处理：

- 第一阶段只做坐标化和投影。
- 不改变 GraphLoop 推进权威。
- Event history 先作为审计和 fork 输入，不作为每次恢复的唯一构建源。

### 风险 2：时间字段变多后语义混乱

处理：

固定定义：

```text
event_cursor = 每次状态提交事件游标
graph_clock_seq = 图运行全局逻辑时钟
superstep_seq = 调度边界序号
dispatch_round = runner 内部派发轮次
node_dispatch_seq = 同一 node 被派发次数
attempt = 同一执行坐标下的执行尝试次数
```

### 风险 3：子图和动态展开污染父图

处理：

- 子图独立 checkpoint namespace。
- 动态展开生成新 config。
- 父图只接收 child graph 的结果 packet。

### 风险 4：前端重新推断状态

处理：

- 前端只消费 projection。
- 状态计算只在 graph_system 后端。

## 15. 总裁决

图任务应升级为时空任务运行体系，但不能推翻当前 GraphLoop。

推荐路线：

```text
先坐标化
再时钟化
再 timeline 化
再 replay/fork 化
最后前端可视化
```

核心判断：

- `ExecutableGraphConfig` 是空间。
- `GraphRun` 是运行宇宙。
- `GraphLoopState` 是当前时间切片。
- `GraphCheckpointRecord` 是可恢复切片。
- `GraphTimelineEvent` 是发生事实。
- `GraphNodeWorkOrder` 是 agent 的时空执行包。
- `FlowPacket` 是跨空间传播的时空信号。

这套体系建成后，项目网络、写作图、repair 图、未来多 agent 协作图都可以复用同一个运行底座，而不是各自发明状态、恢复和审计机制。
