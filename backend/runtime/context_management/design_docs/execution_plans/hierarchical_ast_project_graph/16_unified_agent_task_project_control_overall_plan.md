# Agent 任务系统与项目控制网络总体规划

状态：总体规划锁定稿，待确认后实施  
日期：2026-07-04  
前置文档：`13_graph_task_task_system_file_system_boundary_optimization_plan.md`、`14_graph_task_spacetime_runtime_architecture_plan.md`、`15_persistent_task_work_environment_spine_plan.md`、`agent_source_audits/00_turn_session_task_reference_synthesis.md`

## 1. 规划目标

本规划把前面关于 Deep AST、项目语义网络、图任务、持久任务环境、成熟 agent 边界的讨论收束成一套总架构。

目标不是继续增加一个任务入口、一个搜索工具或一个审查图模板，而是建立一套能长期支撑 coding agent 工作的项目控制系统：

```text
ConversationSession
-> TaskWorkEnvironment
-> AgentExecutionEpisode
-> GraphRuntime / GraphNodeWorkOrder
-> WorkProduct
-> ProjectControlNetwork
-> Repair / Maintenance / Generation
```

最终系统应让 agent 获得三类能力：

1. 任务能力：一项工作可以跨 session 持续推进、暂停、恢复、交接、审计和归档。
2. 图任务能力：复杂工作可以通过图算法调度多个单 agent 任务环境，而不是重造一套模型执行 loop。
3. 项目控制能力：agent 可以沿物理骨架、语义路标和信号链路定位、理解、修改、验证和维护项目。

## 2. 当前源码依据

### 2.1 已经具备的成熟基础

`harness` 已经有单 agent 执行主脊柱：

```text
backend/harness/entrypoint/runtime_facade.py
backend/harness/runtime/single_agent_host.py
backend/harness/runtime/services.py
backend/harness/loop/single_agent_turn.py
backend/harness/runtime/compiler.py
backend/harness/runtime/output_commit_authority.py
```

现有链路已经覆盖：

- RuntimeHost 的 store、event log、trace、tool control plane、run monitor。
- 单 turn 的 prompt/context/tool/model/action/commit 主链。
- 输出提交权威。
- turn run 与 task run 的基础记录。

因此后续任务系统不应再新建第二套 agent runtime。

### 2.2 当前最大的结构断点

`runtime_facade.py` 中 `request_task_run` 已经被切断为 `task_system_cut`：

```text
已接收 request_task_run 控制信号；旧 TaskRun 生命周期暂不启动，等待后续任务体系重做后重新接入。
```

这说明旧 TaskRun 生命周期不能直接恢复使用。正确方向是先建立新的 `TaskWorkEnvironment` 底座，再把任务启动重新接回。

同时，图节点当前仍然走：

```text
GraphNodeWorkOrder
-> execute_graph_agent_work_order_callback
-> _create_graph_node_task_run()
-> harness.loop.task_executor.execute_task_run()
```

而 `backend/harness/loop/task_executor.py` 本身包含 `call_model_invoker`、`call_model_streamer`、`compile_task_execution_packet`、工具执行、输出提交等完整执行逻辑。这构成第二套模型执行权威，是后续必须降级和清理的核心风险。

### 2.3 graph_system 已经接近通用母体

当前 `graph_system` 已有：

```text
ExecutableGraphConfig
GraphRuntimeEnvelope
GraphRun
GraphLoopState
GraphNodeWorkOrder
NodeResultEnvelope
GraphRunRunner
GraphResumeService
GraphNodeWorkOrderExecutor
checkpoint / resume / background supervisor
```

第 13 号计划实施后，项目网络领域逻辑已迁出旧 `task_system.project_network`，形成：

```text
project_network_system
  项目网络资产、store、work product、generation、报告物化、维护信号

project_network_tasks
  项目网络图任务模板、tree reduce、runtime adapter、context provider
```

新增的 `adapter_registry.py` 与 `context_provider_registry.py` 说明方向正确：`graph_system` 应继续作为通用图任务母体，只通过注册机制接收领域任务扩展。

### 2.4 task_system 仍未成为持久任务环境系统

当前 `task_system/tasks/models.py` 的 `TaskRecord` 仍是简单 task 状态记录。  
`task_system/tasks/run_models.py` 的 `TaskRunLedger` 更像 step ledger。  
`task_system/tasks/spec_models.py` 的 `TaskSpec` 仍直接携带 `session_id`。

这些模型都不足以表达跨 session 的任务真相：

```text
TaskWorkEnvironment
AgentExecutionEpisode
TaskContextPackage
TaskMemorySpace
WorkProduct
TaskEventLedger
SessionTaskBinding
```

所以后续不是在旧 TaskRun 上补字段，而是把任务系统升级为“任务工作环境管理系统”。

### 2.5 项目控制网络已有物理和语义基础

`file_management.project_structure` 已经提供：

```text
file tree
deep AST / skeleton extractors
git change set
skeleton node / edge / fact
slice service
navigation control
maintenance projection
```

`project_network_system` 已经提供：

```text
ProjectNetworkBuildContract
GraphBuildWorkProductEnvelope
WorkProductChannel
ProjectNetworkGenerationRecord
ProjectNetworkMaintenanceSignalRecord
ProjectNetworkRepairWorkItemRecord
semantic artifact materializer
```

这说明项目控制网络不需要从零开始。真正缺口是：任务环境、图任务调度、work product、统一图、repair/maintenance 没有被一条主链完全贯通。

## 3. 成熟 agent 边界裁决

基于 `agent_source_audits/00_turn_session_task_reference_synthesis.md` 的源码调研，必须锁定以下边界：

```text
Turn != Session != TaskWorkEnvironment != TaskRun/Episode != WorkProduct
```

本项目采用的成熟标准：

| 概念 | 定义 | 不能承担 |
| --- | --- | --- |
| Turn | 当前用户输入的一次交互节拍 | 不保存任务真相 |
| Session | 对话连续性容器 | 不作为任务系统 |
| Runtime Run | 一次可观测执行过程 | 不替代任务环境 |
| TaskWorkEnvironment | 可持久、可恢复、可审计的工作环境 | 不直接执行模型 |
| AgentExecutionEpisode | agent 进入任务环境的一次工作片段 | 不代表整个任务 |
| GraphRuntime | 复杂任务的算法调度系统 | 不承载领域语义资产 |
| WorkProduct | 可被后续系统消费的产物 | 不等同 assistant message |
| ProjectControlNetwork | 项目物理/语义/控制图资产 | 不属于 graph_system 或 task_system 内部子模块 |

成熟架构共同点：

- session 只提供连续性，不拥有任务真相；
- task 必须有 goal、status、owner、events、artifacts、recovery；
- runtime run 必须可观测；
- provider stream 不可恢复，只能从 durable boundary 恢复；
- work product 必须独立于聊天消息；
- 图任务调度和单 agent 执行必须收敛到同一执行协议。

## 4. 总体目标架构

目标架构分为六个系统层。

```text
1. Conversation / Turn Layer
   保存用户交互、当前 turn、可见历史和普通单轮执行。

2. Harness Runtime Layer
   负责单 agent 执行主脊柱：context packet、model/tool loop、admission、commit、monitor。

3. Task System Layer
   负责任务定义、任务工作环境、任务上下文包、任务记忆、episode、work product refs、生命周期。

4. Graph System Layer
   负责图任务母体：config、loop、scheduler、checkpoint、resume、runner、work order、result。

5. File Management Layer
   负责物理项目环境：file tree、git、deep AST、skeleton、slice、physical refs。

6. Project Network Layer
   负责项目控制网络：semantic overlay、signal chain、architecture intelligence、generation、repair。
```

推荐依赖方向：

```text
harness
  -> task_system public services
  -> graph_system facade

task_system
  -> graph_system public graph config / graph run contracts

project_network_tasks
  -> task_system graph/config contracts
  -> graph_system adapter/provider protocols
  -> project_network_system store ports
  -> file_management physical structure ports

project_network_system
  -> file_management physical facts

graph_system
  -> adapter/provider registry protocols only
```

硬边界：

- `graph_system` 不直接依赖 `project_network_system` 领域实现。
- `graph_system` 不应静态拥有 `project_network_tasks` 业务类；领域包只能通过通用 registry 注册。
- `task_system` 不拥有 `project_network_system` 的长期资产。
- `file_management` 不接收 agent 语义判断来改写物理事实。
- `project_network_tasks` 是任务包，不是资产 store。

## 5. 三条主脊柱

### 5.1 单 agent 执行脊柱

单 agent 执行继续以现有 harness 为权威：

```text
RuntimeInvocationPacket
-> run_single_agent_turn compatible execution
-> model action protocol
-> tool control plane
-> output commit authority
-> event / trace / monitor
```

任务系统只给它提供 `TaskContextPackage` 和 `TaskExecutionEpisodeScope`，不能新建第二套 provider/tool loop。

### 5.2 持久任务环境脊柱

任务的本体不是函数，而是持久工作环境：

```text
TaskDefinition
-> TaskInstance
-> TaskWorkEnvironment
-> TaskContextPackage
-> AgentExecutionEpisode
-> EpisodeResult
-> WorkProduct
-> TaskReducer
-> TaskTimeline / TaskMemory / TaskArtifacts
```

任务与普通 turn 的区别不是复杂度，而是是否需要独立工作环境：

- 跨 turn 继续；
- 独立目标和验收；
- 独立存储、证据、产物；
- 可暂停、恢复、交接；
- 可被图节点或维护系统调度；
- 结果需要被后续系统消费。

### 5.3 项目控制网络脊柱

项目控制网络是一张统一图的三种职责，不是三张图：

```text
Physical Spine
  系统确定性抽取：git / file tree / deep AST / import / route / IPC / registry。

Semantic Facet
  agent 在物理节点和边上赋予职责、标签、控制意义、风险和证据。

Neural Control Surface
  agent 使用统一图进行 locate / jump / trace / audit / repair / impact review。
```

统一身份必须是：

```text
stable_ref / node_id / edge_id
```

不允许物理层一套 ref、语义层一套 ref、工具层再一套 ref。

## 6. 固定执行流

### 6.1 普通 turn

```text
User Message
-> ConversationSession
-> HarnessRuntimeFacade
-> run_single_agent_turn
-> assistant output / tool observations / commit
```

普通 turn 可以读文件、改代码、运行工具，只要当前回合能完成，就不应被强行升级为任务。

### 6.2 显式任务启动

```text
agent emits request_task_run
-> TaskRouter validates durable-work reason
-> TaskWorkEnvironmentAllocator
-> TaskInstance + TaskWorkEnvironment
-> initial TaskContextPackage
-> optional first AgentExecutionEpisode
```

系统只校验任务边界是否足够，不替 agent 猜任务目标。

### 6.3 继续任务

```text
task_id / task_environment_id
-> load TaskWorkEnvironment
-> rebuild TaskContextPackage
-> run AgentExecutionEpisode through harness spine
-> TaskReducer writes state/memory/artifacts/work products
```

继续时不能依赖完整 session transcript。系统必须提供目标、当前状态、最近产物、未解问题、必要证据和 continuation hint。

### 6.4 图节点执行

目标链路：

```text
GraphNodeWorkOrder
-> GraphNodeTaskBinding
-> create or resume TaskWorkEnvironment(caller=graph_node)
-> AgentExecutionEpisode
-> WorkProduct
-> NodeResultEnvelope
-> GraphLoop.accept_node_result()
```

图节点不是 prompt，也不是旧 TaskRun executor。它是一个由图任务调度的单 agent 任务环境。

### 6.5 项目网络构建

```text
file_management.project_structure
-> physical skeleton generation
-> project_network_tasks tree_reduce graph
-> file/module review episodes
-> directory aggregate episodes
-> typed work products
-> project_network_system ingest
-> unified control graph materialization
-> human reports + machine indexes
```

tree reduce 是 graph harness 的算法结构，不是项目网络自己写的平行调度器。

### 6.6 repair / maintenance

```text
git delta / audit signal / locate miss / bridge gap / stale semantic overlay
-> ProjectNetworkMaintenanceSignal
-> repair work item
-> localized repair graph
-> agent semantic judgement
-> curator / validation
-> new generation
```

repair 与 maintenance 同源，不另建补网系统。

## 7. 核心数据模型规划

### 7.1 task_system 新主模型

```text
TaskDefinition
  任务类型、契约、目标形态、验收策略、默认环境模板。

TaskInstance
  跨 session 的任务身份、目标、状态、owner、优先级、生命周期。

TaskWorkEnvironment
  任务工作空间：storage_scope、memory_scope、artifact_scope、tool_scope、
  permission_scope、context_policy、checkpoint_policy、acceptance_policy。

SessionTaskBinding
  session 与 task 的视图绑定。session 可引用任务，但不拥有任务真相。

TaskContextPackage
  当前 episode 的上下文包：stable refs、current state、memory refs、artifact refs、
  file refs、graph packets、user steer、acceptance refs。

AgentExecutionEpisode
  agent 进入任务环境的一次运行记录：agent profile、invocation kind、input package、
  event refs、output refs、terminal status、continuation hint。

TaskEventLedger
  durable 事件流：episode started、tool used、artifact emitted、state proposed、
  interrupted、resumed、completed。

WorkProduct
  可消费产物：summary、structured payload、artifact refs、evidence refs、
  memory candidates、downstream refs、acceptance claims。
```

### 7.2 graph_system 需要补强的模型

沿用第 14 号计划：

```text
GraphSpaceRef
GraphTimeRef
GraphSpacetimeRef
GraphTimelineEvent
GraphAttemptRef
```

短期原则：

- 不推翻当前 GraphLoop。
- 先为 WorkOrder / Result / FlowPacket 增加只读时空投影。
- 再逐步让 checkpoint、resume、fork、repair 使用统一 lineage。

### 7.3 project_network_system 需要稳定的模型

统一项目控制图实体：

```text
UnifiedProjectControlNode
  identity
  physical_facts
  semantic_facets
  control_surface

UnifiedProjectControlEdge
  identity
  physical_facts
  semantic_facets
  control_surface
```

长期索引：

```text
semantic_coordinates
deep_network_route_index
signal_chain_index
link_signal_audit
capability_index
reuse_candidate_index
architecture_smell_index
maintenance_signals
repair_items
generation_records
```

## 8. 模块权威边界

### 8.1 harness

可以：

- 执行 agent episode；
- 装配 runtime packet；
- 控制 tool/model/action/commit；
- 记录 runtime event、trace、monitor。

不能：

- 拥有任务真相；
- 保存项目网络 generation；
- 为图任务创造领域语义；
- 让旧 `task_executor.py` 继续作为第二模型执行主循环。

### 8.2 task_system

可以：

- 管任务定义、任务实例、任务环境、任务契约、任务生命周期；
- 管 session-task binding；
- 管 TaskContextPackage、TaskEventLedger、WorkProduct refs；
- 编译/发布通用 graph config。

不能：

- 拥有项目网络长期 semantic store；
- 直接执行模型；
- 把 session 当任务表；
- 把 graph node 当 prompt。

### 8.3 graph_system

可以：

- 执行图任务母体；
- 管 config、loop、state、checkpoint、resume、work order、node result；
- 提供 adapter/provider registry；
- 执行通用算法，如 tree_reduce、loop_iteration、fanout/fanin。

不能：

- import 项目网络 repository 细节；
- 判断项目语义；
- 直接执行模型；
- 把写作质量、项目网络、审查领域逻辑继续写进核心。

### 8.4 file_management

可以：

- 抽取物理事实；
- 管 file tree、git、deep AST、skeleton、slice、stable refs；
- 输出 physical facts 和 affected change set。

不能：

- 决定模块语义；
- 接受 agent 语义来修改物理拓扑；
- 保存项目网络 semantic generation。

### 8.5 project_network_system

可以：

- 保存项目控制网络长期资产；
- 管 semantic overlay、signal chain、generation、repair、architecture intelligence；
- 物化人读报告和机器索引；
- 消费 file_management 物理骨架和 graph task work products。

不能：

- 执行 graph loop；
- 管通用任务系统；
- 绕过 file_management 直接散乱读项目；
- 另起平行调度器。

### 8.6 project_network_tasks

可以：

- 定义项目网络任务模板；
- 提供 context provider、runtime adapter、tree_reduce frame builder；
- 把 project network build / repair 编译成 graph config。

不能：

- 保存长期项目网络资产；
- 替 graph_system 调度节点；
- 替 agent 判断语义。

## 9. Agent 契约原则

所有任务节点 prompt 必须是 agent 可执行的任务契约，不是开发说明。

契约必须包含：

```text
身份
职责
可见输入
不可做事项
必须输出
合格标准
不确定或失败时如何表达
```

项目网络单文件审查契约应以这种方式表达：

```text
你是一名单文件项目控制语义审查员。
你只负责系统提供的一个物理文件。
你的任务不是泛泛总结文件，而是在该物理文件上建立可被后续 agent 使用的语义坐标、控制路标和候选链路信号。
你不能读取其它文件、不能搜索项目、不能伪造物理关系。
当证据不足时，你必须把关系放入 candidate 或 limitations，不能写成 accepted。
```

目录汇总契约应表达：

```text
你是一名目录级项目控制语义汇总员。
你只消费系统提供的直接文件审查结果和直接子目录汇总结果。
你不重新审查源码，不展开孙目录，不把自然语言摘要反推成结构事实。
你要为父层提交压缩后的语义路标、覆盖率、冲突和候选关系。
```

## 10. 分阶段实施计划

### Phase 0：冻结旧执行权威

目标：

- 明确旧 `harness.loop.task_executor` 不再作为目标执行主线。
- 所有新任务环境设计围绕 `run_single_agent_turn` compatible harness spine。

影响文件：

```text
backend/harness/entrypoint/runtime_facade.py
backend/harness/loop/task_executor.py
backend/harness/runtime/services.py
backend/harness/runtime/compiler.py
```

完成标准：

- 文档和代码注释明确旧 executor 的降级目标。
- 不再向旧 executor 添加新任务语义。

### Phase 1：任务环境模型和只读投影

目标：

- 新增 `TaskWorkEnvironment`、`TaskContextPackage`、`AgentExecutionEpisode`、`WorkProduct` 模型。
- 现有 `TaskRun` / `GraphNodeWorkOrder` 可投影成新模型视图。
- 不改变运行语义。

建议新增：

```text
backend/task_system/work_environments/models.py
backend/task_system/work_environments/repository.py
backend/task_system/work_environments/service.py
backend/task_system/work_products/models.py
backend/task_system/work_products/repository.py
backend/task_system/episodes/models.py
backend/task_system/episodes/repository.py
```

完成标准：

- `TaskRun` 不再被解释为完整任务环境；
- 可以从现有记录生成 task environment projection；
- session binding 与 task truth 分离。

### Phase 2：request_task_run 重新接入资源分配

目标：

- `request_task_run` 不再只返回 cut receipt。
- 它只创建任务环境和初始上下文，不直接跑旧 executor。

影响文件：

```text
backend/harness/entrypoint/runtime_facade.py
backend/harness/loop/single_agent_turn.py
backend/harness/runtime/compiler.py
backend/task_system/work_environments/service.py
```

完成标准：

- agent 发出合格 `request_task_run` 后能得到 `task_environment_id`；
- 系统不猜任务目标；
- 未满足任务边界时返回 ask/block，而不是创建模糊任务。

### Phase 3：TaskContextPackage 接入 harness

目标：

- 任务继续时，harness 接收任务上下文包。
- 稳定事实、当前状态、记忆、证据、产物、用户 steer 分层进入 packet。

影响文件：

```text
backend/harness/runtime/compiler.py
backend/harness/runtime/packet_assembler.py
backend/harness/runtime/bound_task_context.py
backend/harness/runtime/dynamic_context/*
backend/task_system/work_environments/service.py
```

完成标准：

- 继续任务不依赖完整 session transcript；
- 当前任务上下文可解释、可裁剪、可恢复；
- 稳定事实不反复塞进动态尾。

### Phase 4：AgentExecutionEpisode 复用单 agent 主脊柱

目标：

- 任务运行被表达为一次 episode。
- episode 内部仍走 harness 单 agent 执行链。
- 输出经 TaskReducer 写成 work product、memory、artifact、state update。

影响文件：

```text
backend/harness/entrypoint/runtime_facade.py
backend/harness/runtime/single_agent_host.py
backend/harness/loop/single_agent_turn.py
backend/task_system/episodes/service.py
backend/task_system/work_products/service.py
```

完成标准：

- 没有第二 model loop；
- 没有第二 tool authorization path；
- 没有第二 output commit path；
- episode 中断时能写 continuation hint。

### Phase 5：图节点接入任务环境

目标：

- `GraphNodeWorkOrder` 不再直接创建旧 TaskRun executor。
- 图节点创建或恢复 `TaskWorkEnvironment(caller_kind=graph_node)`。
- `NodeResultEnvelope` 从 work product 和 episode result 生成。

影响文件：

```text
backend/graph_system/work_order_executor.py
backend/graph_system/facade.py
backend/harness/entrypoint/runtime_facade.py
backend/task_system/work_environments/service.py
backend/task_system/graph_instances/*
```

完成标准：

- 图节点可中断、恢复、审计；
- 图节点产物进入 WorkProduct store；
- GraphLoop 仍是状态推进权威。

### Phase 6：图任务时空模型补强

目标：

- WorkOrder / Result / FlowPacket 拥有时空坐标投影。
- checkpoint、resume、retry、fork、repair 有统一 lineage。

影响文件：

```text
backend/graph_system/spacetime_models.py
backend/graph_system/spacetime_projection.py
backend/graph_system/timeline_models.py
backend/graph_system/models.py
backend/graph_system/loop.py
backend/graph_system/resume.py
backend/graph_system/flow_packet.py
```

完成标准：

- 任意 node result 可追溯输入 work order、checkpoint、inbound packets；
- 任意 repair 可说明 repair_of；
- 不推翻当前 GraphLoop。

### Phase 7：项目控制网络硬化

目标：

- 统一图成为项目网络主产物。
- route index、signal chain、semantic coordinates、audit 分工清楚。
- bridge extractor、capability index、reuse index、smell index 开始落地。

影响文件：

```text
backend/project_network_system/*
backend/project_network_tasks/*
backend/file_management/project_structure/skeleton_extractors/*
backend/capability_system/tools/tool_units/project_network_tool.py
```

完成标准：

- 物理线由系统抽取；
- 语义 facet 绑定 evidence；
- candidate 不伪装 accepted；
- locate / jump / trace / read_audit / queue_repair 走统一图入口。

### Phase 8：repair / maintenance 闭环

目标：

- git change、artifact audit、locate miss、bridge gap、coverage gap 进入同源 maintenance signal。
- repair graph 本地化运行，不全量重审。

影响文件：

```text
backend/project_network_system/store_models.py
backend/project_network_system/repository.py
backend/project_network_system/service.py
backend/project_network_tasks/repair_runtime_service.py
backend/file_management/project_structure/maintenance_service.py
backend/capability_system/tools/tool_units/project_network_tool.py
```

完成标准：

- `unknown_target_ref`、`candidate_relation_needs_resolution` 等可生成 repair item；
- repair 完成后进入同一 generation；
- 维护 agent 共享任务记忆和项目网络记忆，但不污染普通 session 上下文。

### Phase 9：清理旧链路

目标：

- 按项目要求，不长期保留旧兼容壳。
- 清理旧 TaskRun executor 模型执行权威、旧 project network 残留、旧 CLI 平行调度语义。

检查项：

```text
rg "task_system.project_network" backend
rg "call_model_invoker" backend/harness/loop/task_executor.py
rg "execute_graph_agent_work_order_callback" backend
rg "request_task_run" backend/harness backend/task_system
```

完成标准：

- 旧链路不再承担主运行职责；
- 若保留文件，只能是生命周期控制 helper 或历史迁移说明，不能继续执行模型。

## 11. 文件级执行清单

| 文件/目录 | 当前角色 | 后续行动 |
| --- | --- | --- |
| `backend/harness/entrypoint/runtime_facade.py` | API 到 runtime 的主适配层 | 接入 TaskWorkEnvironment 创建、继续、图节点 episode；移除对旧 executor 的主链依赖 |
| `backend/harness/loop/task_executor.py` | 旧 TaskRun 模型/工具执行循环 | 降级为生命周期 helper 或清理；不能继续作为第二 agent runtime |
| `backend/harness/loop/single_agent_turn.py` | 单 agent 主执行 loop | 保持执行权威；增加 task episode scope 输入 |
| `backend/harness/runtime/compiler.py` | prompt/context packet 编译 | 让 `TaskContextPackage` 成为任务执行输入，而不是散乱 task state |
| `backend/harness/runtime/services.py` | runtime service table | 收缩 callback 语义，避免 task/graph 反向决定 agent 行动 |
| `backend/task_system/tasks/*` | 旧任务记录和 ledger | 保留必要投影，新增 work environment 主模型 |
| `backend/task_system/work_environments/` | 新目录 | 管任务环境、scope、context policy、checkpoint policy |
| `backend/task_system/episodes/` | 新目录 | 管 AgentExecutionEpisode 和 episode event refs |
| `backend/task_system/work_products/` | 新目录 | 管通用 WorkProduct，不局限 project network |
| `backend/graph_system/models.py` | 图配置、run、state、work order、result | 扩展时空 ref 和 graph-node task binding |
| `backend/graph_system/work_order_executor.py` | 图节点执行入口 | 改为通过任务环境执行 episode；清理领域质量门污染 |
| `backend/graph_system/loop.py` | 图状态推进权威 | 保持权威；补 timeline / spacetime / checkpoint metadata |
| `backend/project_network_system/*` | 项目网络长期资产 | 继续承载统一图、generation、repair、architecture intelligence |
| `backend/project_network_tasks/*` | 项目网络任务包 | 承载 build/repair graph、context provider、adapter，不存长期资产 |
| `backend/file_management/project_structure/*` | 物理骨架与维护 | 强化 bridge extractor、git delta、skeleton slice，不写语义事实 |
| `backend/capability_system/tools/tool_units/project_network_tool.py` | 项目网络工具入口 | 收敛为 locate/jump/trace/audit/repair/architecture intelligence 控制面 |
| `backend/runtime/context_management/design_docs/execution_plans/hierarchical_ast_project_graph/README.md` | 规划索引 | 加入本总体规划 |

## 12. 验证与收口标准

按项目约定，不新增回归测试文件，不用伪造产物冒充通过。

### 12.1 静态审查

```powershell
rg -n "task_system.project_network" backend
rg -n "call_model_invoker|call_model_streamer" backend/harness/loop/task_executor.py
rg -n "execute_graph_agent_work_order_callback|execute_task_run_callback" backend
rg -n "TaskWorkEnvironment|AgentExecutionEpisode|WorkProduct" backend/task_system backend/harness backend/graph_system
python -m compileall backend/harness backend/task_system backend/graph_system backend/project_network_system backend/project_network_tasks backend/file_management
```

### 12.2 真实运行验证

涉及运行链路时必须固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
```

核心验证场景：

1. 普通 turn 不被误升级为任务。
2. `request_task_run` 能创建任务环境，但不走旧 executor。
3. 任务中断后可从 TaskContextPackage + continuation hint 继续。
4. 图节点执行能创建/恢复任务环境，并生成 WorkProduct 与 NodeResultEnvelope。
5. project network build 能生成根报告、文件报告、目录报告、统一图和 audit。
6. `locate -> jump -> trace -> read_audit -> queue_repair` 能在真实项目上形成控制闭环。
7. git 修改后能识别 affected refs，并生成局部 repair work item。

### 12.3 架构不变量

```text
没有第二 single-agent model loop。
没有第二 tool authorization path。
没有第二 assistant output commit path。
没有 session 作为 task truth。
没有 graph_system 直接保存项目网络资产。
没有 task_system 直接拥有 project network store。
没有 agent 伪造物理节点或物理边。
没有 candidate 伪装为 accepted。
没有把自然语言报告反解析成结构事实。
```

## 13. 迁移与切换规则

### 13.1 允许的过渡

允许短期存在：

- 旧 TaskRun 记录到新 TaskWorkEnvironment 的只读投影；
- 旧 task_run_id 作为 episode / environment 的 legacy ref；
- 旧 checkpoint 字段到新 spacetime 字段的读取归一化；
- project network 旧 artifact 到统一图的读取转换。

这些只能是读取归一化，不是旧运行链路。

### 13.2 不允许的兼容

禁止长期保留：

- `task_system.project_network` 运行兼容壳；
- 旧 `task_executor.py` 模型执行主循环；
- 项目网络平行 tree scheduler；
- graph_system 内部的 project network 领域后处理；
- 任务系统内部的项目网络长期 store。

### 13.3 cutover 标准

切换到新主链必须满足：

```text
TaskWorkEnvironment 可创建、恢复、归档。
AgentExecutionEpisode 复用 harness 单 agent 主脊柱。
GraphNodeWorkOrder 能绑定任务环境。
WorkProduct 能被 GraphLoop / ProjectNetworkSystem 消费。
ProjectControlNetwork 能从 work products 物化统一图。
repair / maintenance signal 能闭环。
```

### 13.4 rollback 标准

若实施中出现严重问题：

- 普通 turn 主链不得回退；
- GraphLoop 状态推进不得回退；
- 新 task environment 行为可以临时关闭；
- 已迁出的 project_network_system 不回搬到 task_system；
- 回滚只允许切断新入口，不恢复旧执行权威。

## 14. 严禁反模式

1. 把任务做成更长的 turn。
2. 把 task_run_id 当 session_id 使用。
3. 把 graph node 写成开发说明型 prompt。
4. 把旧 executor 包一层新接口继续跑。
5. 在 graph_system 里写项目网络业务逻辑。
6. 在 task_system 里塞项目网络长期资产。
7. 让 agent 自由铺物理网。
8. 为了命中率把 candidate 当 accepted。
9. 用大上下文替代任务记忆和 work product。
10. 用报告文本反推结构化图事实。
11. 用 CLI 平行推进 tree reduce 生命周期。
12. 用兼容名义长期保留旧主链。

## 15. 预期最终形态

最终系统应成为：

```text
Harness Runtime
  是 agent 执行底座。

Task System
  是跨 session 的工作环境管理系统。

Graph System
  是复杂任务的时空调度母体。

File Management
  是项目物理世界权威。

Project Network System
  是项目语义和控制资产库。

Project Network Tasks
  是用图任务生产和修复项目网络的任务包。

Project Network Tooling
  是 agent 使用项目控制网络的神经控制面。
```

这套体系建成后，agent 面对复杂项目时不再只靠 `rg + read_file` 盲搜。正确工作方式应是：

```text
小范围任务：
  rg / exact read / edit / real run

复杂架构和链路任务：
  project control network locate
  -> jump / trace / audit
  -> exact read
  -> edit
  -> local skeleton refresh
  -> impact / repair / generation
```

最终目标是让 agent 在写代码前知道项目已有架构，在写代码时遵守架构边界，在写完后能反查影响面、复用机会和架构破坏风险。
