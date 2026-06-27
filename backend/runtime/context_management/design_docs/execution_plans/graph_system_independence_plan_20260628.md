# Graph System Independence Plan

日期：2026-06-28  
状态：计划书，待确认后实施。  
范围：把当前混在 `backend/harness/graph*` 下的图结构、图状态机、图调度、图 checkpoint、图 work order 和图运行监控独立为图系统；`harness` 保持 agent 神经控制层。

## 1. 问题定义

当前 `harness` 下面同时承担两类权威：

- agent 神经控制：请求事实、上下文契约、工具契约、权限边界、agent 执行循环、行动反馈。
- 图执行拓扑：图配置、节点/边协议、状态机、调度、checkpoint、resume、flow packet、work order、后台运行。

这两类权威都重要，但不应该混成一个包。正确结构应当是：

```text
harness          = agent runtime nervous system
graph_system     = executable graph topology and graph run system
task_system      = task authoring, graph authoring, compiler and registry
runtime/*        = provider, tool, context, storage, shared infrastructure
```

这样 `harness` 可以调度图系统、执行图节点中的 agent work order、接收图反馈，但图系统不再把自己的身份写成 `harness.graph_*`，也不把图状态机和 graph checkpoint 当成 agent runtime 内部实现。

## 2. 当前代码事实

| 文件 | 当前事实角色 | 目标归属 |
|---|---|---|
| `backend/harness/graph_harness.py` | 图运行 facade，聚合 GraphRuntime、GraphLoop、Resume、Runner、WorkOrderExecutor、BackgroundSupervisor | `backend/graph_system/facade.py` |
| `backend/harness/graph/models.py` | GraphHarnessConfig、GraphRun、GraphLoopState、GraphNodeWorkOrder、NodeResultEnvelope 等图核心数据模型 | `backend/graph_system/models.py` |
| `backend/harness/graph/runtime.py` | 锁定发布配置，创建 GraphRun、TaskRun、GraphRuntimeEnvelope | `backend/graph_system/runtime.py` |
| `backend/harness/graph/loop.py` | 图动态控制器、调度 ready 节点、接收 node result、checkpoint | `backend/graph_system/loop.py` |
| `backend/harness/graph/state_machine.py` | 图状态分类、ready/blocked/completed/failed 判断 | `backend/graph_system/state_machine.py` |
| `backend/harness/graph/readiness_evaluator.py` | 节点可调度性计算 | `backend/graph_system/readiness_evaluator.py` |
| `backend/harness/graph/transition_processor.py` | node result / human decision 到 edge state 的转换 | `backend/graph_system/transition_processor.py` |
| `backend/harness/graph/flow_packet.py` | 图边上的 payload packet、artifact/memory/result refs | `backend/graph_system/flow_packet.py` |
| `backend/harness/graph/context_materializer.py` | 从图状态和节点合同生成 GraphNodeWorkOrder / GraphNodeExecutionSlot | `backend/graph_system/context_materializer.py` |
| `backend/harness/graph/work_order_executor.py` | 通过 callback 执行 agent 节点，生成 NodeResultEnvelope，处理图节点输出物 | `backend/graph_system/work_order_executor.py`，agent 执行通过 harness adapter 注入 |
| `backend/harness/graph/work_order_contract.py` | 把 GraphNodeWorkOrder 转成 `harness.loop.TaskRunContract` | `backend/harness/runtime/graph_node_contract.py`，这是 harness adapter，不属于图核心 |
| `backend/task_system/compiler/graph_harness_config_publisher.py` | 从 TaskGraphDefinition 编译发布图运行配置 | 留在 `task_system/compiler`，但输出类型改为 graph_system 的 executable graph config |
| `backend/api/orchestration.py`、`backend/api/task_system.py` | 直接调用 `runtime.harness_runtime.graph_harness` | 改为调用 `runtime.harness_runtime.graph_system` 或专用 graph service port |

关键结论：

- 当前 `backend/harness/graph/` 已经是图子系统，不是 harness 的普通子模块。
- `work_order_contract.py` 是最明显的边界文件：它导入 `harness.loop.task_lifecycle.TaskRunContract`，说明它是 harness adapter，不是图系统核心。
- `GraphHarnessConfig`、`GRAPH_HARNESS_CONFIG_AUTHORITY`、`graph_harness_config_id` 等命名把图系统身份绑在 harness 下，后续应统一改成 graph system / executable graph config 语义。

## 3. 目标权威链

目标链路：

```text
TaskGraphDefinition
-> GraphConfigCompiler
-> ExecutableGraphConfig
-> GraphSystem.start_run
-> GraphRunEnvelope
-> GraphLoopState
-> GraphNodeWorkOrder
-> HarnessGraphNodeAdapter
-> Agent TaskRun
-> NodeResultEnvelope
-> GraphTransitionProcessor
-> GraphCheckpoint
-> GraphRunMonitor
```

各层权威：

| 层 | 允许 | 禁止 |
|---|---|---|
| `task_system` | 定义任务图、编辑图、编译图配置、发布 graph config | 执行图节点、推进运行状态 |
| `graph_system` | 持有图拓扑、图运行状态、调度、checkpoint、resume、flow packet、graph monitor | 直接改写 agent prompt、直接决定 agent 工具权限 |
| `harness` | 执行 agent 节点、组织 agent context/tool/permission/action feedback | 重新计算图拓扑、私自推进 graph edge state |
| `runtime` | provider/tool/context/storage 基础设施 | 代替 graph_system 或 harness 作语义裁决 |

## 4. 推荐目标目录

第一版以移动和重命名为主，不因为文件大而拆大文件。

```text
backend/graph_system/
  __init__.py
  facade.py                         # GraphSystem facade, replaces GraphHarness
  models.py                         # ExecutableGraphConfig, GraphRun, GraphLoopState, work orders, results
  language.py                       # edge/node protocol vocabulary
  edge_contracts.py
  flow_edges.py
  flow_packet.py
  scheduler_view.py
  state_machine.py
  readiness_evaluator.py
  transition_processor.py
  runtime.py                        # run start and envelope assembly
  loop.py                           # graph state progression and checkpointed dispatch
  resume.py
  runner.py
  background_supervisor.py
  lifecycle_manager.py
  context_materializer.py
  memory_context.py
  output_policy.py
  runtime_objects.py
  checkpoint_store.py
  langgraph_checkpoint_store.py
  model_overrides.py
  supervisor.py
  work_order_executor.py

backend/harness/runtime/
  graph_node_contract.py             # GraphNodeWorkOrder -> TaskRunContract adapter
  graph_node_execution.py             # optional adapter port if needed
```

说明：

- 不先拆成过多子包，避免移动期 import 噪声过大。
- 等图系统稳定后，再按 `contracts/`、`runtime/`、`topology/`、`execution/`、`storage/` 分子包。
- `harness.graph` 和 `harness.graph_harness` 不保留为长期兼容壳。若实施时需要数据迁移，只能做一次性迁移脚本或同一阶段内的 import cutover，不能保留两套 active graph path。

## 5. 命名和 authority 修正

推荐新命名：

| 当前名 | 目标名 | 原因 |
|---|---|---|
| `GraphHarness` | `GraphSystem` | 它是图运行系统 facade，不是 harness 本身 |
| `GraphHarnessConfig` | `ExecutableGraphConfig` | 它是可执行图配置，来源是 task graph compiler，消费方是 graph system |
| `GRAPH_HARNESS_CONFIG_AUTHORITY` | `EXECUTABLE_GRAPH_CONFIG_AUTHORITY` | authority 不应绑定 harness |
| `graph_harness_config_id` | `graph_config_id` 或 `executable_graph_config_id` | API/存储字段后续 cutover，避免继续扩散旧名 |
| `harness.graph_runtime_envelope` | `graph_system.runtime_envelope` | 图运行 envelope 属于图系统 |
| `harness.graph_loop` | `graph_system.loop` | loop/state progression 属于图系统 |
| `harness.graph_flow_packet` | `graph_system.flow_packet` | flow packet 是图边传输合同 |
| `harness.graph.node_execution_slot` | `graph_system.node_execution_slot` | node slot 由图系统 materialize |
| `harness.graph.graph_node_runtime_contract` | `harness.graph_node_contract` | 转成 agent TaskRunContract 的动作属于 harness adapter |

字段改名需要成组实施，不能只改常量名。尤其是 persisted runtime objects、repository、API payload、frontend 读取字段需要同一阶段明确 cutover。

## 6. 实施阶段

### Phase 0：计划确认

目标：锁定边界，不动运行代码。

完成标准：

- 本文档被确认。
- 总后端结构计划同步说明：`harness` 收束 agent 神经控制，`graph_system` 独立为图系统。

### Phase 1：内部包迁移，不改行为

目标：把纯图系统代码从 `backend/harness/graph*` 移到 `backend/graph_system`，更新所有 imports。

动作：

- 移动 `backend/harness/graph/*.py` 到 `backend/graph_system/*.py`，但先不拆小包。
- 移动 `backend/harness/graph_harness.py` 到 `backend/graph_system/facade.py`，类名改为 `GraphSystem`。
- 更新 `backend/harness/entrypoint/runtime_facade.py`：持有 `self.graph_system`。
- 更新 API、task_system、health_system 中的 import 目标。
- 删除 `backend/harness/graph/` 和 `backend/harness/graph_harness.py`，不保留长期 re-export。

完成标准：

- 没有 active import 仍指向 `harness.graph` 或 `harness.graph_harness`。
- 行为不变：start graph、dispatch、accept result、resume、checkpoint 路径仍可运行。

### Phase 2：拆出 harness adapter

目标：切断 graph core 对 harness agent runtime 的直接依赖。

动作：

- 移动 `backend/harness/graph/work_order_contract.py` 的逻辑到 `backend/harness/runtime/graph_node_contract.py`。
- `GraphSystem` 只通过 callback/port 请求执行 agent work order。
- harness adapter 负责：`GraphNodeWorkOrder -> TaskRunContract -> execute_task_run -> executor_result`。
- graph_system 只接收 executor_result 并生成 `NodeResultEnvelope`。

完成标准：

- `backend/graph_system` 不 import `harness.loop`、`harness.runtime.compiler`、`harness.runtime.tool_plan`。
- `harness` 可以 import `graph_system` 的公开模型和 facade。

### Phase 3：authority 和模型命名 cutover

目标：去掉 `GraphHarness*` 和 `harness.graph_*` 语义污染。

动作：

- `GraphHarnessConfig` 改为 `ExecutableGraphConfig`。
- `graph_harness_config_from_dict` 改为 `executable_graph_config_from_dict`。
- repository、compiler publisher、API payload 内部字段统一到 `executable_graph_config_id` 或 `graph_config_id`。
- persisted runtime object 如需保留用户数据，编写一次性 migration，把旧 authority 和字段迁到新 authority。迁移完成后不保留旧 authority 接收分支。

完成标准：

- 新图运行对象 authority 统一是 `graph_system.*`。
- 没有新代码写出 `harness.graph_*` authority。
- 旧字段只有迁移脚本或历史数据说明中可见。

### Phase 4：API / 前端协议 cutover

目标：对外协议不再暴露 `graph_harness_config_id` 这种旧命名。

动作：

- 后端 API request/response 字段改为新名。
- 前端 graph/task 页面同步读取新字段。
- 删除旧字段输出，不做双字段长期兼容。

完成标准：

- 前端固定端口真实启动后，图运行、图监控、人工 gate、resume 都可用。
- `rg "graph_harness_config_id|GraphHarness|harness\\.graph"` 只剩迁移说明或历史设计文档。

## 7. 验证策略

不新增回归测试文件。允许验证：

- `python -m compileall backend/graph_system backend/harness backend/task_system backend/api backend/health_system`
- `rg "from harness\\.graph|harness\\.graph_harness|GraphHarness|graph_harness_config_id" backend`
- 固定端口启动后端 `127.0.0.1:8003` 和前端 `127.0.0.1:3000`，真实运行一条图任务。
- 检查 graph run monitor、checkpoint、resume、accept_node_result、human gate 是否仍通过新 graph system path。

## 8. 禁止事项

- 禁止把 `backend/graph_system` 做成 `harness.graph` 的薄包装。
- 禁止保留 `harness.graph` 与 `graph_system` 两套 active 图运行路径。
- 禁止让 graph_system 直接修改 agent prompt、工具契约或权限契约。
- 禁止让 harness 重新计算 graph edge state 或绕过 graph checkpoint。
- 禁止为了迁移方便长期输出新旧两套 API 字段。

## 9. 推荐结论

这次结构整理应分成两条主线：

```text
harness/runtime/context_contract  收束 agent 语义控制和上下文契约
backend/graph_system              独立图拓扑、图调度、图运行和图 checkpoint
```

`harness` 是 agent 神经系统；`graph_system` 是独立的图执行系统。两者通过明确端口连接：图系统签发 `GraphNodeWorkOrder`，harness 执行 agent 节点并返回结果，图系统再推进状态机。
