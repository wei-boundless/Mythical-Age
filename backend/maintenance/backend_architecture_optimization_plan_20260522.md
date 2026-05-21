# Backend 架构优化管理计划 - 2026-05-22

## 1. 真实问题

当前 backend 不是业务逻辑完全错误，而是领域所有权已经漂移。系统功能还能跑，但代码边界让项目越来越臃肿：

- `backend/tasks/` 同时放了普通任务、任务图、图编译器、workflow registry、契约注册、执行配方、拆分合并规划、编辑器投影。
- `backend/orchestration/` 同时放了 agent 配置、agent runtime profile、组装逻辑、资源策略、runtime lane、旧编排原语和完整 runtime loop。
- `backend/orchestration/runtime_loop/` 同时放了单任务执行、任务图调度、coordination runtime、professional runtime、runtime 契约、runtime memory、事件、checkpoint、节点 handoff。
- `backend/api/orchestration.py` 不只是 API，还夹了 graph module 启动/导入/后台调度/idempotency/event log 等运行控制逻辑。

所以要修的不是单个 bug，而是系统的“归属关系”。优化后的目录应该让人一眼看懂：

1. 任务是什么。
2. 任务图是什么。
3. agent 配置在哪里。
4. 单个执行单元和整张任务图分别由谁运行。

## 2. 对照先进代码结构后的原则

这里的“先进结构”不等于套某个框架名，而是采用成熟后端和 agent 平台都通用的几条结构原则：

- **领域优先**：按业务领域分包，而不是按历史文件来源分包。
- **控制平面和执行平面分离**：任务图负责控制流，unit runtime 负责执行单点。
- **定义和运行分离**：task system 定义/编译任务，runtime 执行任务。
- **薄 API**：API 只接请求、调 service，不承载业务流程。
- **契约优先**：任务、图、节点、边、handoff、artifact 都要有明确契约归属。
- **读模型和运行态分离**：配置/profile 是静态或半静态定义，run/checkpoint/event 是运行态。
- **兼容层短生命周期**：迁移期可以有 re-export shim，但不能永久保留旧入口。

## 3. 目标 Backend 顶层目录

讨论后确定的主结构：

```text
backend/
  agent_system/
  task_system/
  runtime/
  capability_system/
  memory_system/
  soul/
  health_system/
  artifact_system/
  permissions/
  api/
```

可以继续保留的基础设施目录：

```text
backend/
  bootstrap/
  execution/
  context_management/
  context_policy/
  output_boundary/
  retrieval/
  retrieval_core/
  document_conversion/
  normalized_ingestion/
  mcp_client/
  mcp_server/
  observability/
  sessions/
  storage/
```

后续应该折叠、迁移或删除的目录：

```text
backend/
  orchestration/       # 拆到 agent_system、runtime，少量旧控制原语再判断是否保留
  tasks/               # 迁移到 task_system
  agents/              # 并入 agent_system，或如果只是旧壳就删除
  capabilities/        # 并入 capability_system，或如果空/旧就删除
  artifact_repository/ # 如果和 artifact_system 重复，合并
  runtime_objects/     # 并入 runtime/shared
  runtime_state/       # 并入 runtime/shared 或 runtime/memory
  runtime_views/       # 并入 runtime/shared/views 或 service 层
  executions/          # 并入 execution 或 runtime
  events/              # 并入 runtime/shared 或 observability
  checkpoints/         # 并入 runtime/shared/checkpoint
  coordination_checkpoints/
  state_index/
  timeline_ledgers/
  working_memory/
  formal_memory/
```

## 4. 目标领域边界

### 4.1 agent_system

职责：定义具体 agent，包括它是谁、怎么工作、有什么权限、能用什么能力、能读写什么记忆、使用什么 soul 投影。

目标目录：

```text
backend/agent_system/
  profiles/
  permissions/
  capabilities/
  memory_scopes/
  work_modes/
  assembly/
  registry/
  groups/
  models/
  services/
```

当前迁移来源：

```text
backend/orchestration/agent_models.py
backend/orchestration/agent_registry.py
backend/orchestration/agent_runtime_models.py
backend/orchestration/agent_runtime_registry.py
backend/orchestration/agent_group_models.py
backend/orchestration/agent_group_registry.py
backend/orchestration/agent_identity.py
backend/orchestration/agent_runtime_chain.py
backend/orchestration/assembly_builder.py
backend/orchestration/assembly_models.py
backend/orchestration/body_models.py
backend/orchestration/body_registry.py
backend/orchestration/worker_agent_factory.py
backend/orchestration/worker_agent_blueprints.py
```

边界规则：

- `AgentProfile` 表示 agent 静态/半静态工作档案。
- `AgentRuntimeProfile` 或 resolved profile 表示单次运行的有效配置。
- `agent_system` 可以引用 `permissions`、`capability_system`、`memory_system`、`soul`。
- `agent_system` 不负责任务图调度。
- 给 agent 的 prompt 必须写成职责语言，不能写成内部 runtime 标签。

### 4.2 task_system

职责：定义任务系统。普通任务和任务图都属于任务系统；任务图是图化的多 agent 协调任务流程。

目标目录：

```text
backend/task_system/
  tasks/
  graphs/
  contracts/
  compiler/
  registry/
  editor/
  planning/
  models/
  services/
```

子域含义：

```text
tasks/       # 原子任务、具体任务、任务规格
graphs/      # 任务图定义、节点、边、资源层、graph module 定义
contracts/   # 任务契约、图契约、节点/边/handoff 契约
compiler/    # Task/TaskGraph -> RuntimeSpec
registry/    # task、task graph、workflow 的注册和发布状态
editor/      # 任务图编辑器后端：standard view、预览、发布校验
planning/    # 拆分、合并、执行计划生成
services/    # 给 API 调用的应用服务
```

当前迁移来源：

```text
backend/tasks/definitions.py
backend/tasks/spec_models.py
backend/tasks/run_models.py
backend/tasks/step_models.py
backend/tasks/execution_recipe_models.py
backend/tasks/execution_recipe_builder.py
backend/tasks/execution_shape_resolver.py
backend/tasks/assembly_builder.py
backend/tasks/assembly_models.py
backend/tasks/assembly_support.py
backend/tasks/task_graph_models.py
backend/tasks/task_graph_standard_models.py
backend/tasks/layered_graph_normalizer.py
backend/tasks/composable_graph_models.py
backend/tasks/composable_graph_builder.py
backend/tasks/coordination_graph_models.py
backend/tasks/coordination_graph_compiler.py
backend/tasks/task_split_merge_models.py
backend/tasks/task_split_plan_builder.py
backend/tasks/contract_definition_models.py
backend/tasks/contract_models.py
backend/tasks/contract_registry.py
backend/tasks/contracts.py
backend/tasks/runtime_contracts.py
backend/tasks/semantic_task_contracts.py
backend/tasks/match_contracts.py
backend/tasks/flow_models.py
backend/tasks/flow_registry.py
backend/tasks/workflow_models.py
backend/tasks/workflow_registry.py
```

边界规则：

- `task_system` 负责“定义”和“编译”，不直接跑任务。
- `task_system/tasks` 只放普通任务，不再塞任务图调度。
- `task_system/graphs` 放任务图定义和编辑器投影需要的图结构。
- `task_system/compiler` 输出 runtime 可消费的 spec。
- `task_system/registry` 是 draft/published/archived 的权威来源。

### 4.3 runtime

职责：执行运行时。runtime 需要明确分成单个 runtime 和图任务 runtime。

目标目录：

```text
backend/runtime/
  unit_runtime/
  graph_runtime/
  coordination_runtime/
  professional_runtime/
  contracts/
  execution/
  memory/
  shared/
```

子域含义：

```text
unit_runtime/          # 单个 agent / 单个 node / 单个 task unit 的执行
graph_runtime/         # 整张任务图推进：scheduler、controller、batch、monitor、graph module
coordination_runtime/  # LangGraph/coordination 过渡层，目标是能合并就逐步并入 graph_runtime
professional_runtime/  # 专业模式运行策略，长期应缩成 unit_runtime 的一种模式
contracts/             # runtime 消费的契约编译和校验
execution/             # node handoff、delegation executor、执行请求
memory/                # runtime-local ledger、trace reader、state index、checkpoint 投影
shared/                # event、checkpoint、RuntimeLoopState、context manager、artifact refs
```

当前迁移来源：

```text
backend/orchestration/runtime_loop/task_run/*
backend/orchestration/runtime_loop/graph/*
backend/orchestration/runtime_loop/coordination/*
backend/orchestration/runtime_loop/professional/*
backend/orchestration/runtime_loop/contracts/*
backend/orchestration/runtime_loop/execution/*
backend/orchestration/runtime_loop/memory/*
backend/orchestration/runtime_loop/shared/*
```

边界规则：

- `runtime/unit_runtime` 只管一个执行单元怎么跑。
- `runtime/graph_runtime` 只管整张任务图怎么推进。
- `graph_runtime` 把具体节点派发给 `unit_runtime`，不自己执行 agent。
- `runtime/memory` 只放运行态 ledger/trace/index；长期记忆归 `memory_system`。
- `runtime/contracts` 是执行期契约，不是任务定义契约。

### 4.4 api

职责：HTTP 入口。API 层不应承载业务流程。

目标规则：

- API 只做参数解析、鉴权入口、调用 service、返回响应。
- API 不直接编译 task graph。
- API 不直接启动 graph module。
- API 不直接维护后台调度表。
- API 不直接写 runtime event log，除非通过 service。

需要抽走的逻辑：

```text
backend/api/orchestration.py graph module import/start
  -> backend/runtime/graph_runtime/graph_module_service.py

backend/api/orchestration.py stage background scheduling
  -> backend/runtime/graph_runtime/node_dispatcher.py

backend/api/orchestration.py task graph run start
  -> backend/runtime/graph_runtime/graph_run_service.py

backend/api/tasks.py task graph editor/compile/package 逻辑
  -> backend/task_system/services/*
```

## 5. 当前主要结构问题

### 问题 1：tasks 是任务系统、任务图系统、契约系统、编辑器后端的混合体

典型例子：

```text
backend/tasks/flow_registry.py               # 145KB
backend/tasks/coordination_graph_compiler.py # 66KB
backend/tasks/task_graph_models.py           # 49KB
backend/tasks/assembly_support.py            # 45KB
backend/tasks/assembly_builder.py            # 39KB
```

这些不是同一层职责。继续放在 `tasks` 下，会让“任务”和“任务图”边界越来越糊。

### 问题 2：orchestration 这个名字已经失真

它现在既像 agent 配置系统，又像 runtime，又像旧控制平面。我们讨论后已经明确：

```text
agent 配置 -> agent_system
任务图推进 -> runtime/graph_runtime
单点执行 -> runtime/unit_runtime
旧控制原语 -> 最后判断是否保留 control_plane
```

### 问题 3：runtime_loop 不是一个 loop，而是多个运行引擎堆在一起

典型大文件：

```text
backend/orchestration/runtime_loop/task_run/loop.py          # 344KB
backend/orchestration/runtime_loop/coordination/runtime.py   # 255KB
backend/orchestration/runtime_loop/professional/driver.py    # 121KB
backend/orchestration/runtime_loop/memory/trace_reader.py    # 87KB
backend/orchestration/runtime_loop/graph/scheduler.py        # 45KB
backend/orchestration/runtime_loop/graph/batch_runtime.py    # 43KB
```

问题不只是文件大，而是执行单元、图推进、coordination、professional、runtime memory 都在一个历史包里。

### 问题 4：API 层承担了运行控制

`backend/api/orchestration.py` 里有 graph module 导入、后台线程调度、idempotency key、event log 逻辑。这些属于 runtime service，不属于 API。

### 问题 5：runtime 文件堆积的根因是 canonical state 没有统一归属

有些 runtime 文件是合理的，例如：

```text
task run record
coordination run record
scheduler state
checkpoint
event log
artifact refs
accepted result records
monitor decisions
```

但有些是可疑副作用：

```text
未被任务契约要求的自动写入 fallback artifact
同一份 graph spec 在多个 diagnostics 里重复嵌入
restore/snapshot 层可以覆盖 current-turn truth
graph module handle 混在无关 diagnostics 里
编辑器投影或 prompt 生成物落成 runtime 文件
```

优化原则：runtime 存 canonical state 和 handle，不存无边界的中间对象副本。

## 6. 目标依赖方向

允许：

```text
api
  -> task_system/services
  -> runtime/* service
  -> agent_system/services

runtime/graph_runtime
  -> task_system/compiler
  -> task_system/graphs
  -> runtime/unit_runtime
  -> runtime/shared

runtime/unit_runtime
  -> agent_system/assembly
  -> capability_system
  -> memory_system runtime facade
  -> artifact_system
  -> runtime/shared

task_system/compiler
  -> task_system/tasks
  -> task_system/graphs
  -> task_system/contracts
  -> agent_system registry/read model

agent_system
  -> permissions
  -> capability_system read model
  -> memory_system scope model
  -> soul read model
```

禁止：

```text
task_system -> runtime/unit_runtime 的 loop 内部
task_system -> api
agent_system -> task graph scheduler
runtime/shared -> task_system 具体 registry
api -> runtime memory state index 内部
agent prompt -> “这是 runtime 节点” 这类内部标签
```

## 7. 分阶段实施计划

### Phase 0：锁定架构语言

目标：

- 固定命名和边界，避免后续迁移边改边想。

交付：

- 本计划。
- 必要时再补一个更短的目录映射表。

完成标准：

- 固定顶层目标：`agent_system`、`task_system`、`runtime`。
- 固定 runtime 二分：`unit_runtime` 和 `graph_runtime`。
- 新功能不再往 `backend/tasks` 或 `backend/orchestration/runtime_loop` 增加非迁移代码。

### Phase 1：建立新包骨架

目标：

- 先建立新目录，不改变行为。

新增：

```text
backend/agent_system/
backend/task_system/
backend/runtime/
```

最小子目录：

```text
backend/task_system/tasks/
backend/task_system/graphs/
backend/task_system/contracts/
backend/task_system/compiler/
backend/task_system/registry/
backend/task_system/editor/
backend/task_system/planning/
backend/task_system/services/

backend/runtime/unit_runtime/
backend/runtime/graph_runtime/
backend/runtime/coordination_runtime/
backend/runtime/professional_runtime/
backend/runtime/contracts/
backend/runtime/execution/
backend/runtime/memory/
backend/runtime/shared/

backend/agent_system/profiles/
backend/agent_system/registry/
backend/agent_system/assembly/
backend/agent_system/groups/
backend/agent_system/models/
backend/agent_system/services/
```

验证：

```text
python -m compileall -q backend
```

### Phase 2：迁移 task_system 定义、图、契约、编译器

目标：

- 把 `backend/tasks` 拆成真正的 `task_system`。

迁移映射：

```text
backend/tasks/definitions.py                  -> backend/task_system/tasks/definitions.py
backend/tasks/spec_models.py                  -> backend/task_system/tasks/spec_models.py
backend/tasks/step_models.py                  -> backend/task_system/tasks/step_models.py
backend/tasks/run_models.py                   -> backend/task_system/tasks/run_models.py
backend/tasks/execution_recipe_models.py      -> backend/task_system/tasks/execution_recipe_models.py
backend/tasks/execution_recipe_builder.py     -> backend/task_system/tasks/execution_recipe_builder.py
backend/tasks/execution_shape_resolver.py     -> backend/task_system/tasks/execution_shape_resolver.py

backend/tasks/task_graph_models.py            -> backend/task_system/graphs/models.py
backend/tasks/task_graph_standard_models.py   -> backend/task_system/editor/standard_view.py
backend/tasks/layered_graph_normalizer.py     -> backend/task_system/graphs/layered_normalizer.py
backend/tasks/composable_graph_models.py      -> backend/task_system/graphs/composable_models.py
backend/tasks/composable_graph_builder.py     -> backend/task_system/graphs/composable_builder.py
backend/tasks/coordination_graph_models.py    -> backend/task_system/graphs/runtime_models.py
backend/tasks/coordination_graph_compiler.py  -> backend/task_system/compiler/graph_runtime_compiler.py

backend/tasks/task_split_merge_models.py      -> backend/task_system/planning/split_merge_models.py
backend/tasks/task_split_plan_builder.py      -> backend/task_system/planning/split_plan_builder.py

backend/tasks/contract_definition_models.py   -> backend/task_system/contracts/definition_models.py
backend/tasks/contract_models.py              -> backend/task_system/contracts/models.py
backend/tasks/contract_registry.py            -> backend/task_system/contracts/registry.py
backend/tasks/contracts.py                    -> backend/task_system/contracts/task_contracts.py
backend/tasks/runtime_contracts.py            -> backend/task_system/contracts/runtime_views.py
backend/tasks/semantic_task_contracts.py      -> backend/task_system/contracts/semantic_contracts.py
backend/tasks/match_contracts.py              -> backend/task_system/contracts/match_contracts.py

backend/tasks/flow_models.py                  -> backend/task_system/registry/flow_models.py
backend/tasks/flow_registry.py                -> backend/task_system/registry/task_flow_registry.py
backend/tasks/workflow_models.py              -> backend/task_system/registry/workflow_models.py
backend/tasks/workflow_registry.py            -> backend/task_system/registry/workflow_registry.py
```

兼容策略：

- `backend/tasks/*.py` 可以短期保留为空 re-export shim。
- shim 不允许有业务逻辑。
- 对应生产 import 迁移完成后删除 shim，不长期保留。

验证：

```text
python -m compileall -q backend/task_system backend/tasks
python -m pytest backend/tests/task_contract_registry_test.py backend/tests/task_graph_registry_test.py backend/tests/task_graph_standard_models_test.py backend/tests/task_split_plan_builder_regression.py
python -m pytest backend/tests/contract_compiler_coordination_test.py backend/tests/contract_compiler_workflow_test.py backend/tests/writing_modular_novel_graph_config_regression.py
```

### Phase 3：迁移 graph_runtime

目标：

- 把任务图运行从 `orchestration/runtime_loop/graph` 升到 `runtime/graph_runtime`。

迁移映射：

```text
backend/orchestration/runtime_loop/graph/scheduler.py        -> backend/runtime/graph_runtime/scheduler.py
backend/orchestration/runtime_loop/graph/scheduler_models.py -> backend/runtime/graph_runtime/scheduler_models.py
backend/orchestration/runtime_loop/graph/batch_runtime.py    -> backend/runtime/graph_runtime/batch_runtime.py
backend/orchestration/runtime_loop/graph/run_monitor.py      -> backend/runtime/graph_runtime/run_monitor.py
backend/orchestration/runtime_loop/graph/monitoring.py       -> backend/runtime/graph_runtime/monitoring.py
```

从 API 抽出：

```text
backend/api/orchestration.py graph module import/start
  -> backend/runtime/graph_runtime/graph_module_service.py

backend/api/orchestration.py background stage scheduling
  -> backend/runtime/graph_runtime/node_dispatcher.py

backend/api/orchestration.py task graph run start
  -> backend/runtime/graph_runtime/graph_run_service.py
```

规则：

- `graph_runtime` 可以依赖 `task_system/compiler` 和 `task_system/graphs`。
- `graph_runtime` 通过 `unit_runtime` 或过渡 adapter 派发具体节点。
- API 变薄，只调 service。

验证：

```text
python -m compileall -q backend/runtime/graph_runtime backend/api
python -m pytest backend/tests/task_graph_scheduler_regression.py backend/tests/task_graph_batch_runtime_regression.py backend/tests/task_graph_run_monitor_test.py backend/tests/task_graph_health_projection_regression.py
python -m pytest backend/tests/task_system_api_regression.py backend/tests/writing_modular_novel_graph_config_regression.py
```

### Phase 4：迁移 runtime/shared 和 unit_runtime

目标：

- 把现在的 runtime_loop 拆成共享运行态和单点执行引擎。

迁移映射：

```text
backend/orchestration/runtime_loop/shared/*    -> backend/runtime/shared/*
backend/orchestration/runtime_loop/task_run/*  -> backend/runtime/unit_runtime/*
backend/orchestration/runtime_loop/execution/* -> backend/runtime/execution/*
backend/orchestration/runtime_loop/memory/*    -> backend/runtime/memory/*
backend/orchestration/runtime_loop/contracts/* -> backend/runtime/contracts/*
```

后续抽离重点：

```text
runtime/unit_runtime/loop.py
  -> start_task_run_service.py
  -> coordination_continue_service.py
  -> artifact_validation_service.py
  -> answer_readiness_service.py
  -> search_source_resolver.py
  -> delegation_classifier.py
```

验证：

```text
python -m compileall -q backend/runtime
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py backend/tests/professional_task_run_regression.py backend/tests/task_run_state_machine_regression.py backend/tests/runtime_loop_budget_regression.py backend/tests/runtime_recovery_idempotency_regression.py
python -m pytest backend/tests/langgraph_coordination_runtime_regression.py backend/tests/langgraph_checkpoint_adapter_regression.py
```

### Phase 5：迁移 agent_system

目标：

- 把现在 `orchestration` 里的 agent 配置系统正名为 `agent_system`。

迁移映射：

```text
backend/orchestration/agent_models.py             -> backend/agent_system/models/agent_models.py
backend/orchestration/agent_registry.py           -> backend/agent_system/registry/agent_registry.py
backend/orchestration/agent_runtime_models.py     -> backend/agent_system/profiles/runtime_profile_models.py
backend/orchestration/agent_runtime_registry.py   -> backend/agent_system/profiles/runtime_profile_registry.py
backend/orchestration/agent_group_models.py       -> backend/agent_system/groups/models.py
backend/orchestration/agent_group_registry.py     -> backend/agent_system/groups/registry.py
backend/orchestration/agent_identity.py           -> backend/agent_system/identity.py
backend/orchestration/agent_runtime_chain.py      -> backend/agent_system/assembly/runtime_chain.py
backend/orchestration/assembly_builder.py         -> backend/agent_system/assembly/agent_runtime_assembly_builder.py
backend/orchestration/assembly_models.py          -> backend/agent_system/assembly/models.py
backend/orchestration/body_models.py              -> backend/agent_system/profiles/body_models.py
backend/orchestration/body_registry.py            -> backend/agent_system/profiles/body_registry.py
backend/orchestration/worker_agent_factory.py     -> backend/agent_system/registry/worker_agent_factory.py
backend/orchestration/worker_agent_blueprints.py  -> backend/agent_system/registry/worker_agent_blueprints.py
```

可能的后续迁移：

```text
backend/orchestration/model_profile_models.py     -> backend/agent_system/models/model_profile_models.py
backend/orchestration/model_profile_resolver.py   -> backend/agent_system/models/model_profile_resolver.py
backend/orchestration/runtime_lane_registry.py    -> backend/runtime/shared/runtime_lane_registry.py
```

验证：

```text
python -m compileall -q backend/agent_system backend/orchestration
python -m pytest backend/tests/orchestration_agent_management_regression.py backend/tests/agent_main_assembly_semantic_boundary_regression.py backend/tests/runtime_assembly_builder_test.py backend/tests/task_graph_permission_boundary_regression.py
python -m pytest backend/tests/soul_projection_resource_boundary_regression.py backend/tests/soul_projection_interaction_mode_regression.py
```

### Phase 6：清理残余 orchestration 和旧目录

目标：

- 最后判断 `backend/orchestration` 是否还需要存在。

允许保留：

```text
backend/control_plane/
```

前提是旧 `ControlKernel`、candidate、commit gate、execution graph 仍然是活跃概念。

必须删除：

- 空壳旧模块。
- 重复 registry。
- 只验证旧 import path 的旧测试。
- 纯兼容但无业务价值的旧代码。

验证：

```text
python -m compileall -q backend
python -m pytest backend/tests
```

## 8. 第一批重点瘦身对象

这些文件不能只是搬家，搬完后还要继续拆：

```text
backend/orchestration/runtime_loop/task_run/loop.py
backend/orchestration/runtime_loop/coordination/runtime.py
backend/orchestration/runtime_loop/professional/driver.py
backend/orchestration/runtime_loop/memory/trace_reader.py
backend/tasks/flow_registry.py
backend/tasks/coordination_graph_compiler.py
backend/tasks/task_graph_models.py
backend/tasks/assembly_support.py
backend/tasks/assembly_builder.py
backend/api/orchestration.py
backend/api/tasks.py
```

瘦身优先级：

1. API service 抽离。
2. graph runtime service 抽离。
3. unit runtime service 抽离。
4. registry 存储 adapter 抽离。
5. contract compiler 子模块化。
6. editor projection service 抽离。

## 9. Runtime 文件治理规则

合理 runtime 文件：

```text
task_run
coordination_run
scheduler_state
checkpoint
event_log
artifact_ref
accepted_result_record
monitor_decision
```

可疑 runtime 副作用：

```text
未被契约要求的自动产物
重复嵌入的 graph spec
restore 层覆盖当前回合判断
诊断字段里混杂运行控制 handle
编辑器投影被写进 runtime 状态
```

治理规则：

- runtime 存 canonical state，不存无限膨胀的中间对象。
- restore 只能提供候选，不能裁决当前 truth。
- graph runtime 是图进度权威。
- unit runtime 是单次执行结果权威。
- artifact system 是文件产物权威。

## 10. 验证矩阵

任务系统：

```text
backend/tests/task_contract_registry_test.py
backend/tests/task_system_api_regression.py
backend/tests/task_graph_registry_test.py
backend/tests/task_graph_standard_models_test.py
backend/tests/task_split_plan_builder_regression.py
backend/tests/contract_compiler_coordination_test.py
backend/tests/contract_compiler_workflow_test.py
backend/tests/writing_modular_novel_graph_config_regression.py
```

图 runtime：

```text
backend/tests/task_graph_scheduler_regression.py
backend/tests/task_graph_batch_runtime_regression.py
backend/tests/task_graph_run_monitor_test.py
backend/tests/task_graph_health_projection_regression.py
backend/tests/langgraph_coordination_runtime_regression.py
backend/tests/langgraph_checkpoint_adapter_regression.py
```

单点 runtime：

```text
backend/tests/query_runtime_runtime_loop_regression.py
backend/tests/professional_task_run_regression.py
backend/tests/task_run_state_machine_regression.py
backend/tests/task_run_loop_project_supervision_test.py
backend/tests/runtime_loop_budget_regression.py
backend/tests/runtime_recovery_idempotency_regression.py
```

agent 系统：

```text
backend/tests/orchestration_agent_management_regression.py
backend/tests/agent_main_assembly_semantic_boundary_regression.py
backend/tests/runtime_assembly_builder_test.py
backend/tests/task_graph_permission_boundary_regression.py
```

权限和能力：

```text
backend/tests/tool_authorization_regression.py
backend/tests/tool_scope_contract_regression.py
backend/tests/capability_system_api_regression.py
backend/tests/capability_system_preview_regression.py
```

记忆和健康：

```text
backend/tests/memory_system_contracts_regression.py
backend/tests/working_memory_isolation_regression.py
backend/tests/health_management_control_plane_regression.py
backend/tests/health_runtime_admission_cutover_regression.py
```

完整收尾：

```text
python -m compileall -q backend
python -m pytest backend/tests
```

## 11. 迁移纪律

- 一次只迁移一个所有权切片。
- 先迁生产 import，再迁测试 import。
- 兼容 shim 只能是空 re-export。
- 已迁移完成的旧 shim 要删除。
- 不保留只服务旧路径的测试。
- 不通过伪造输出绕过测试。
- 不根据旧 docs 做架构判断。
- 不把开发说明写成 agent prompt。
- 不把“临时兼容”变成永久目录。

## 12. Cutover 和 Rollback

Cutover：

- 某一切片的生产 import 全部指向新目录。
- 对应验证矩阵通过。
- 旧模块只允许短期 re-export。
- 下一切片完成后删除上一切片 shim。

Rollback：

- 回滚 import 路径，不回滚业务语义。
- 如果新目录迁移失败，可以临时恢复旧 import，但保留新目录继续修。
- 不能为了让测试过，把混乱职责重新塞回新目录。

## 13. 最终状态

最终 backend 应该能这样读：

```text
agent_system 定义 agent。
task_system 定义任务和图化任务流程。
runtime 运行单点和任务图。
capability_system 提供工具和技能。
memory_system 管长期记忆。
soul 管人格和灵魂投影。
health_system 做诊断和健康投影。
artifact_system 管真实产物。
permissions 管平台权限原语。
api 暴露服务。
```

最终判断标准：

一个新工程师不需要打开 `api/orchestration.py`、`tasks/flow_registry.py` 或 `runtime_loop/task_run/loop.py`，也能从目录结构判断任务图、agent profile、单点执行、图执行分别在哪里。

## 14. 基础设施目录补充优化

这批目录不是都应该继续作为 backend 顶层目录保留。进一步检查后，可以分成四类：保留顶层、合并成系统、下沉到 runtime/capability、移出代码结构。

### 14.1 应该合并为 knowledge_system

当前相关目录：

```text
backend/retrieval/
backend/retrieval_core/
backend/document_conversion/
backend/normalized_ingestion/
```

这四个目录本质上是一条知识管线：

```text
source file
  -> document conversion
  -> normalized ingestion
  -> indexing
  -> retrieval
  -> evidence packaging
```

现在拆成四个顶层目录，会让“知识摄取”和“知识检索”的所有权变散。建议收敛为：

```text
backend/knowledge_system/
  conversion/
  ingestion/
  indexing/
  retrieval/
  evidence/
  services/
  models/
```

迁移映射：

```text
backend/document_conversion/*  -> backend/knowledge_system/conversion/*
backend/normalized_ingestion/* -> backend/knowledge_system/ingestion/*
backend/retrieval_core/*       -> backend/knowledge_system/indexing/*
backend/retrieval/*            -> backend/knowledge_system/retrieval/*
```

保留说明：

- `backend/knowledge/` 如果主要存放 PDF、xlsx、txt、md 等知识素材，可以继续作为数据目录。
- `backend/knowledge_system/` 才是代码系统。

后续瘦身重点：

```text
backend/retrieval_core/llamaindex_backend.py
  -> dense_index.py
  -> lexical_index.py
  -> qdrant_store.py
  -> retrieval_fusion.py
  -> index_metadata.py

backend/retrieval/service.py
  -> retrieval_service.py
  -> collection_service.py
  -> evidence_service.py
```

### 14.2 应该合并为 context_system

当前相关目录：

```text
backend/context_management/
backend/context_policy/
```

这两个目录是同一个上下文系统的两面：一个处理 current-turn truth、projection、resolver、compaction；另一个处理 context package 和 policy result。继续拆成两个顶层目录会让上下文边界变薄。

建议收敛为：

```text
backend/context_system/
  current_turn/
  resolution/
  projection/
  packaging/
  policy/
  budget/
  compaction/
  models/
```

迁移映射：

```text
backend/context_management/resolver.py           -> backend/context_system/resolution/resolver.py
backend/context_management/current_turn.py       -> backend/context_system/current_turn/models.py
backend/context_management/projection.py         -> backend/context_system/projection/projection.py
backend/context_management/context_controller.py -> backend/context_system/packaging/controller.py
backend/context_management/context_compactor.py  -> backend/context_system/compaction/compactor.py
backend/context_management/budget_presets.py     -> backend/context_system/budget/presets.py
backend/context_policy/*                         -> backend/context_system/policy/*
```

边界规则：

- `context_system` 决定“本轮可见上下文是什么”。
- `memory_system` 提供候选记忆，不直接决定 current-turn truth。
- `runtime` 消费 context package，不反向拥有 context policy。

### 14.3 output_boundary 应升级为 response_system

当前目录：

```text
backend/output_boundary/
```

它不是普通基础设施，而是用户可见答案的边界系统，负责过滤内部协议泄露、识别进度文本、组装最终回答、处理 RAG evidence finalization。

建议改为：

```text
backend/response_system/
  boundary/
  classification/
  assembly/
  finalization/
  tool_outputs/
  models/
```

迁移映射：

```text
backend/output_boundary/boundary.py            -> backend/response_system/boundary/assistant_boundary.py
backend/output_boundary/classifier.py          -> backend/response_system/classification/output_classifier.py
backend/output_boundary/answer_assembler.py    -> backend/response_system/assembly/answer_assembler.py
backend/output_boundary/answer_finalizer.py    -> backend/response_system/finalization/rag_answer_finalizer.py
backend/output_boundary/tool_output_adapter.py -> backend/response_system/tool_outputs/adapter.py
```

边界规则：

- `response_system` 负责用户可见输出。
- `artifact_system` 负责文件产物。
- `runtime` 只能提交候选输出，不能绕过 response boundary。

### 14.4 execution 应下沉到 runtime，避免顶层命名冲突

当前目录：

```text
backend/execution/
```

它现在包含 model runtime、model response executor、tool executor、tool result envelope、tool call adapter。创建 `backend/runtime/` 后，如果继续保留顶层 `execution/`，会和 `runtime/execution/` 发生概念冲突。

建议下沉为：

```text
backend/runtime/
  model_gateway/
  tool_runtime/
```

迁移映射：

```text
backend/execution/model_runtime.py              -> backend/runtime/model_gateway/model_runtime.py
backend/execution/model_response.py             -> backend/runtime/model_gateway/model_response_executor.py
backend/execution/provider_tool_call_adapter.py -> backend/runtime/model_gateway/tool_call_adapter.py

backend/execution/tool_executor.py              -> backend/runtime/tool_runtime/tool_executor.py
backend/execution/tool_call_policy.py           -> backend/runtime/tool_runtime/tool_call_policy.py
backend/execution/tool_call_intent.py           -> backend/runtime/tool_runtime/tool_call_intent.py
backend/execution/tool_result_envelope.py       -> backend/runtime/tool_runtime/tool_result_envelope.py
```

边界规则：

- `runtime/model_gateway` 负责模型调用和 provider 差异。
- `runtime/tool_runtime` 负责工具调用执行和结果 envelope。
- `runtime/execution` 只保留节点 handoff、delegation executor、execution request 等运行图/节点执行协议。

### 14.5 mcp_client 和 mcp_server 应并入 capability_system

当前目录：

```text
backend/mcp_client/
backend/mcp_server/
```

MCP 在当前系统里不是独立业务域，而是能力系统的协议网关：它暴露本地能力，也接入外部 MCP server。建议并入：

```text
backend/capability_system/mcp/
  external_client/
  server/
  gateway/
  tool_pool/
  permissions/
```

迁移映射：

```text
backend/mcp_client/* -> backend/capability_system/mcp/external_client/*
backend/mcp_server/server.py -> backend/capability_system/mcp/server/server.py
backend/mcp_server/local_capability_server.py -> backend/capability_system/mcp/gateway/local_capability_executor.py
backend/mcp_server/tool_pool.py -> backend/capability_system/mcp/tool_pool.py
```

边界规则：

- MCP tool 最终仍然归 `capability_system` 统一注册、授权、暴露。
- `permissions` 提供平台权限原语，MCP 自己只做能力协议映射。

### 14.6 bootstrap 保留顶层，但 settings.py 要拆

当前目录：

```text
backend/bootstrap/
```

它是应用 composition root，应该保留顶层。但 `settings.py` 已经偏大，后续应该拆成：

```text
backend/bootstrap/
  app_runtime.py
  lifespan.py
  settings/
    service.py
    snapshots.py
    providers.py
    secrets.py
    policy_settings.py
```

边界规则：

- `bootstrap` 只组装系统，不承载业务领域逻辑。
- 领域模块不应该反向依赖 `AppRuntime`。

### 14.7 observability 和 sessions 可以保留顶层

当前目录：

```text
backend/observability/
backend/sessions/
```

建议：

- `observability` 保留顶层。当前只有 tracing，后续可自然扩展为 `tracing/`、`metrics/`、`audit/`。
- `sessions` 保留顶层。它是用户会话生命周期，不等同于 runtime state，也不属于 memory_system。

后续结构：

```text
backend/observability/
  tracing/
  metrics/
  audit/

backend/sessions/
  store.py
  models.py
  services.py
```

### 14.8 storage 不应算代码结构

当前目录：

```text
backend/storage/formal_memory/formal_memory.sqlite
```

这不是代码系统，而是本地数据根。架构计划里不应该把 `storage` 当作源代码 package 讨论。

建议：

- 保留为运行数据目录，或长期迁到 `data/` / `var/`。
- 不在 `storage/` 下放业务代码。
- 确认数据库、索引、缓存类文件不被误当作源代码提交。

## 15. 调整后的 Backend 顶层建议

加入上述优化后，更清晰的顶层应该是：

```text
backend/
  agent_system/
  task_system/
  runtime/
  capability_system/
  memory_system/
  knowledge_system/
  context_system/
  response_system/
  artifact_system/
  soul/
  health_system/
  permissions/
  observability/
  sessions/
  bootstrap/
  api/
```

不再建议长期作为顶层代码目录的包：

```text
execution/
context_management/
context_policy/
output_boundary/
retrieval/
retrieval_core/
document_conversion/
normalized_ingestion/
mcp_client/
mcp_server/
storage/
```
