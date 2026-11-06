# 图任务 / 任务系统 / 文件系统边界优化方案

状态：架构边界优化方案  
日期：2026-07-03  
关联报告：`12_apix_project_network_status_and_optimization_report.md`

## 1. 背景判断

当前项目网络能力已经跑通，但代码分布出现了结构性问题：

```text
graph_system
  已经有图运行、loop、checkpoint、work order、algorithm adapter

task_system
  已经有任务定义、契约、图配置、节点配置、运行管理、仓库

file_management.project_structure
  已经有文件树、skeleton、slice、navigation control、maintenance

task_system.project_network
  同时塞入了项目网络任务编排、store、repository、semantic artifact、repair、report materializer
```

问题不是单个文件放错，而是职责边界没有稳定下来：

- 图任务运行系统里混入了 project network 领域逻辑。
- 任务系统里混入了项目网络资产和控制图存储。
- 文件系统已经承担物理骨架，却还没有成为项目网络的唯一物理环境来源。
- 项目网络既像任务生产线，又像长期项目知识资产，两种职责混在一起。

这会带来后续风险：

- `graph_system` 变成领域系统，难以支持写作图、审查图、维护图等多种算法。
- `task_system` 越来越像杂物仓库，既管任务又管项目知识资产。
- 项目网络 store 和 task run store 混合，generation、repair、semantic overlay 的生命周期不清楚。
- 后续 Architecture Intelligence Layer 会进一步扩大职责，如果不先划边界，会继续放大混乱。

## 2. 总体裁决

采用四层边界：

```text
graph_system
  图任务母体：提供图任务架构、运行循环、动力算法和通用执行协议

task_system
  任务仓库与管理系统：管理任务定义、契约、配置、运行记录和任务生命周期

file_management
  文件环境支持系统：提供文件树、AST、git、物理结构、读取窗口和文件级环境

project_network_system
  项目网络领域系统：管理项目网络资产、语义层、信号链、架构智能和维护 generation
```

其中：

- `graph_system` 是动力系统，不是业务系统。
- `task_system` 是任务资产和任务运行管理，不是项目知识库。
- `file_management` 是物理环境和结构事实来源，不负责语义判断。
- `project_network_system` 是项目控制网络的领域系统，消费前三者能力，不反向拥有它们。

## 3. 目标职责分配

### 3.1 graph_system：图任务母体

职责：

- 定义并执行 `ExecutableGraphConfig`。
- 管理 `GraphRun`、`GraphLoopState`、`GraphNodeWorkOrder`、`NodeResultEnvelope`。
- 负责 loop、scheduler、state machine、checkpoint、resume。
- 提供通用 runtime algorithm adapter 机制。
- 提供通用 context materialization 框架。
- 提供 side effect sink 协议。

不应承担：

- 不应硬编码 `project_network_file_review`。
- 不应直接 import `ProjectNetworkRepository`。
- 不应知道 project network work product 的具体 schema。
- 不应知道写作图、审查图、项目网络图的业务细节。

目标形态：

```text
graph_system
  models.py
  loop.py
  loop_engine.py
  runner.py
  work_order_executor.py
  context_materializer.py
  runtime_algorithm_adapters.py
  runtime_algorithm_effects.py
  checkpoint_store.py
  ...
```

其中领域能力通过注册进入：

```text
GraphRuntimeAlgorithmAdapterRegistry
GraphContextProviderRegistry
GraphSideEffectSinkRegistry
```

### 3.2 task_system：任务仓库与运行管理

职责：

- 管理任务定义、任务契约、任务模板。
- 管理 task profile、environment、node configuration。
- 编译任务图配置，发布 `ExecutableGraphConfig`。
- 管理任务运行记录、任务实例、任务生命周期。
- 作为 graph run 与具体 task run 的关联管理层。

不应承担：

- 不应拥有 project network 的长期 semantic store。
- 不应拥有项目网络 generation。
- 不应负责架构总览、信号链索引、复用索引、smell index。
- 不应把项目网络当成任务系统内部子模块长期维护。

目标形态：

```text
task_system
  tasks/
  contracts/
  registry/
  compiler/
  graph_instances/
  node_configurations/
  environments/
  services/
  repositories/
  planning/
```

可保留的 project network 相关职责应迁成“任务类型/任务包”：

```text
project_network_tasks
  build_contract_models.py
  graph_builder.py
  template_catalog.py
  shard_planner.py
  directory_runtime_service.py
  repair_runtime_service.py
```

它们负责“如何用图任务生产项目网络”，不负责“项目网络资产长期怎么存”。

### 3.3 file_management：文件环境支持

职责：

- workspace root / backend root 解析。
- 文件树扫描。
- git diff / change set。
- Deep AST / symbol / import / route / IPC 物理抽取。
- physical skeleton graph。
- 文件读取窗口和结构切片。
- 文件环境权限、路径解析、变更维护。

不应承担：

- 不应决定模块语义。
- 不应判断架构职责。
- 不应发布 semantic generation。
- 不应存项目语义 overlay。

目标形态：

```text
file_management.project_structure
  skeleton_models.py
  skeleton_index_service.py
  skeleton_slice_service.py
  skeleton_normalizer.py
  skeleton_refs.py
  control_service.py
  maintenance_service.py
  repository.py
  deep_ast/
  extractors/
  git_changes/
```

它是项目网络物理层权威来源。

### 3.4 project_network_system：项目网络领域系统

职责：

- 管理 semantic overlay。
- 管理 signal chain。
- 管理 architecture overview。
- 管理 capability index。
- 管理 reuse candidate index。
- 管理 architecture smell index。
- 管理 generation / publication / repair / maintenance。
- 把 file structure、task work product、agent semantic review 合成统一项目控制网络。

不应承担：

- 不应执行 graph loop。
- 不应管理通用 task registry。
- 不应直接读写任意文件绕过 file_management。
- 不应把 agent 审查任务调度写成自己的平行 graph runtime。

目标形态：

```text
project_network_system
  store_models.py
  repository.py
  build_service.py
  semantic_artifact_materializer.py
  signal_chain/
  architecture/
  capability_index/
  reuse_index/
  smell_index/
  maintenance/
  repair/
  projection.py
```

## 4. 当前错位点

### 4.1 graph_system 中的领域污染

当前 `graph_system.runtime_algorithm_adapters.py` 中直接包含：

```text
_project_network_tree_reduce_postprocess
project_network_work_product_contract
project_network_semantic_submissions
```

这不成熟。`graph_system` 可以支持 tree_reduce，但不应该知道 project network 的输出 schema。

目标改法：

```text
graph_system.runtime_algorithm_adapters
  只负责调用 adapter registry

project_network_tasks.runtime_adapters
  注册 project_network_work_product_adapter

writing_tasks.runtime_adapters
  注册 writing_iteration_adapter
```

### 4.2 graph_system context_materializer 中的领域输入构造

当前 `graph_system.context_materializer.py` 中直接构造：

```text
project_network_file_review
project_network_directory_aggregate
project_network_work_product_cards
ProjectNetworkRepository
```

这使图运行系统依赖项目网络仓库。

目标改法：

```text
GraphContextMaterializer
  -> ContextProviderRegistry
  -> provider.provide(node, graph_config, work_order, services)

project_network_tasks.context_provider
  -> 构造 file review / directory aggregate 输入
```

### 4.3 task_system.project_network 同时承担任务生产和资产管理

当前 `task_system.project_network` 包含：

```text
repository.py
store_models.py
semantic_artifact_materializer.py
service.py
directory_runtime_service.py
repair_runtime_service.py
graph_builder.py
template_catalog.py
```

这些应拆分为两类。

迁往 `project_network_system`：

```text
repository.py
store_models.py
semantic_artifact_materializer.py
service.py 中的 work product ingest / generation / publication 部分
projection.py
lifecycle_policy.py 中的 generation 生命周期部分
```

迁往 `project_network_tasks`：

```text
build_contract_models.py
layer_plan_models.py
graph_builder.py
template_catalog.py
shard_models.py
shard_planner.py
directory_run_models.py
directory_runtime_service.py
repair_run_models.py
repair_runtime_service.py
directory_render_models.py
directory_render_service.py
work_product_models.py
work_product_extractor.py
```

### 4.4 file_management 与 project_network_system 的关系没有固定

当前 `file_management.project_structure` 已经有：

```text
skeleton
slice
navigation control
maintenance
repository
```

但项目网络 semantic store 仍在 `task_system.project_network`。

目标关系：

```text
file_management.project_structure
  提供 physical facts

project_network_system
  读取 physical facts，叠加 semantic overlay 和 signal chain

project_network_tasks
  通过 graph task 生产 semantic work products
```

## 5. 新目标架构

```text
backend/
  graph_system/
    通用图运行母体

  task_system/
    通用任务仓库、任务管理、任务图配置

  file_management/
    文件环境、物理结构、AST、git、读取窗口

  project_network_system/
    项目网络资产、语义层、信号链、架构智能、维护闭环

  project_network_tasks/
    项目网络建图/审查/修复任务包
```

依赖方向：

```text
project_network_tasks
  -> task_system
  -> graph_system
  -> project_network_system
  -> file_management

project_network_system
  -> file_management

graph_system
  -> 不依赖 project_network_system

task_system
  -> 不依赖 project_network_system 的具体实现
```

更准确地说：

```text
graph_system 提供执行母体
task_system 管理任务资产和运行
project_network_tasks 把项目网络任务编译成 graph config
graph_system 执行这些 graph config
project_network_tasks 的 adapter/provider 把结果交给 project_network_system
project_network_system 存储和发布项目网络资产
file_management 提供物理环境支持
```

## 6. 接口设计

### 6.1 Graph Runtime Algorithm Adapter Registry

目标：从 `graph_system` 移除领域 postprocess。

接口草案：

```python
class RuntimeAlgorithmAdapter(Protocol):
    adapter_id: str

    def matches(self, graph_config, work_order, node) -> bool:
        ...

    def postprocess(self, structured_outputs, graph_config, work_order, node, final_answer):
        ...
```

注册：

```python
register_runtime_algorithm_adapter(ProjectNetworkWorkProductAdapter())
register_runtime_algorithm_adapter(WritingIterationAdapter())
```

`graph_system` 只做：

```text
for adapter in registry.matching(...):
    result = adapter.postprocess(...)
```

### 6.2 Graph Context Provider Registry

目标：从 `graph_system.context_materializer` 移除 project network 输入构造。

接口草案：

```python
class GraphContextProvider(Protocol):
    provider_id: str

    def matches(self, graph_config, node, work_order) -> bool:
        ...

    def provide(self, graph_config, node, work_order, services) -> dict:
        ...
```

project network 任务包注册：

```text
ProjectNetworkFileReviewContextProvider
ProjectNetworkDirectoryAggregateContextProvider
ProjectNetworkRepairContextProvider
```

### 6.3 Project Network Store Port

目标：让 task/graph 侧通过端口提交 work product，不直接依赖 repository 细节。

接口草案：

```python
class ProjectNetworkStorePort(Protocol):
    def ingest_work_products(self, build_id, graph_run_id, node_result, products):
        ...

    def read_work_products(self, build_id, refs):
        ...

    def materialize_artifacts(self, build_id):
        ...

    def queue_repairs(self, signals):
        ...
```

实现位于：

```text
project_network_system.store_service
```

### 6.4 File Environment Port

目标：project network 不直接散乱读取文件，而是通过 file_management。

接口草案：

```python
class FileEnvironmentPort(Protocol):
    def read_file_module_packet(self, file_ref, budget):
        ...

    def read_directory_slice(self, folder_ref, depth, limit):
        ...

    def collect_git_changes(self, mode):
        ...

    def resolve_ref(self, stable_ref):
        ...
```

实现位于：

```text
file_management.project_structure
```

## 7. 迁移计划

### Phase 1：冻结边界并建立新包

新增：

```text
backend/project_network_system/
backend/project_network_tasks/
```

先只建立包结构和 README，不搬大逻辑。

目标：

- 所有新 project network 资产逻辑进入 `project_network_system`。
- 所有新 project network 任务编排逻辑进入 `project_network_tasks`。
- 不再向 `task_system.project_network` 增加新能力。

### Phase 2：迁移资产层

迁移：

```text
task_system.project_network.store_models
-> project_network_system.store_models

task_system.project_network.repository
-> project_network_system.repository

task_system.project_network.semantic_artifact_materializer
-> project_network_system.semantic_artifact_materializer

task_system.project_network.projection
-> project_network_system.projection
```

调整调用方：

- `project_network_tool.py`
- `graph_system.context_materializer.py`
- CLI project network artifact materialize 入口
- harness runtime facade

验收：

- Apix build 可重新 materialize。
- `project_network.locate / trace / jump` 正常。
- `PROJECT_ARCHITECTURE_OVERVIEW.md` 正常生成。

### Phase 3：迁移任务编排层

迁移：

```text
task_system.project_network.graph_builder
-> project_network_tasks.graph_builder

task_system.project_network.template_catalog
-> project_network_tasks.template_catalog

task_system.project_network.directory_runtime_service
-> project_network_tasks.directory_runtime_service

task_system.project_network.repair_runtime_service
-> project_network_tasks.repair_runtime_service

task_system.project_network.shard_planner
-> project_network_tasks.shard_planner
```

任务系统只保留通用 task registry / compiler / graph config publisher。

验收：

- 后端 CLI 可以启动 project network build graph。
- directory tree reduce 仍能生成 work products。
- repair graph 仍能运行。

### Phase 4：抽离 graph_system 领域 adapter

新增：

```text
graph_system/adapter_registry.py
graph_system/context_provider_registry.py
```

迁移：

```text
graph_system.runtime_algorithm_adapters._project_network_tree_reduce_postprocess
-> project_network_tasks.runtime_adapters.ProjectNetworkWorkProductAdapter

graph_system.context_materializer._project_network_*
-> project_network_tasks.context_providers.*
```

`graph_system` 只保留通用分发。

验收：

- 写作图 postprocess 不受影响。
- project network tree reduce postprocess 正常。
- graph_system 不再直接 import `task_system.project_network` 或 `project_network_system.repository`。

### Phase 5：收紧 task_system

移除或收缩：

```text
task_system.project_network
```

最终可选：

1. 删除该包。
2. 只保留极薄的迁移说明，不保留运行兼容链。

按照项目约定，不长期保留旧链路。迁移完成后应清理旧导入。

验收：

- `rg "task_system.project_network"` 只剩历史文档或无运行引用。
- 所有运行路径使用 `project_network_system` / `project_network_tasks`。

### Phase 6：补架构智能层

在边界稳定后，再落地：

```text
project_network_system.capability_index
project_network_system.reuse_index
project_network_system.smell_index
project_network_system.architecture_review
```

不要在旧 `task_system.project_network` 上继续堆。

## 8. 迁移后的依赖规则

硬规则：

```text
graph_system 不 import project_network_system
graph_system 不 import project_network_tasks 的具体类
graph_system 只通过 registry 调 adapter/provider

task_system 不 import project_network_system repository
task_system 只管理任务配置和运行记录

project_network_tasks 可以依赖 task_system / graph_system 的公共模型
project_network_tasks 可以调用 project_network_system store port

project_network_system 可以依赖 file_management
project_network_system 不依赖 graph_system runtime

file_management 不依赖 project_network_system
```

## 9. 风险与处理

### 风险 1：搬包导致导入链断裂

处理：

- 先通过 `rg "task_system.project_network"` 列出所有调用点。
- 按调用点分批迁移。
- 每批迁移后运行真实 CLI 路径，不写回归测试文件。

### 风险 2：graph_system adapter registry 设计过度

处理：

- 第一版只支持同步注册内置 adapter。
- 不做动态插件系统。
- 不做复杂优先级，只按 `matches()` 顺序执行。

### 风险 3：project_network_system 和 file_management 边界再次混淆

处理：

- file_management 只输出 physical facts。
- project_network_system 只读取 physical facts 并叠加 semantic facts。
- semantic overlay 不写入 file_management。

### 风险 4：任务系统被架构智能层再次污染

处理：

- capability/reuse/smell index 全部进入 project_network_system。
- task_system 只负责“触发某个任务图去审查/修复”。

## 10. 最终目标

迁移完成后，项目网络能力应变成：

```text
文件系统提供物理世界
任务系统管理任务资产
图任务系统提供运行母体和算法动力
项目网络系统沉淀长期项目语义资产
项目网络任务包用 graph task 生产和修复这些资产
```

这样深度网络才不会是塞在 `task_system` 里的大型子模块，而会成为一个真正的项目控制系统。

## 11. 总裁决

用户确认的分配是合理的：

```text
图任务是母体：负责图任务架构和动力算法
任务系统是仓库和管理：负责管理具体任务、契约、配置和运行
文件系统是环境支持：负责物理文件、AST、git 和结构事实
项目网络是领域系统：负责语义网络、信号链路、架构智能和维护闭环
```

因此，后续重构应按这个边界执行，而不是继续在 `task_system.project_network` 上堆功能。

## 12. 2026-07-03 实施记录

本轮已完成 Phase 2、Phase 3、Phase 4、Phase 5 的主体迁移。

已落地的新边界：

```text
project_network_system
  负责项目网络资产、仓储、投影、语义产物 materialize、work product ingest、维护信号。

project_network_tasks
  负责项目网络图任务生产、目录树运行、修复运行、shard 计划、节点模板、runtime adapter、context provider。

graph_system
  只保留通用图运行母体，通过 registry 调用 runtime adapter 和 context provider。
  不再直接 import project_network_system.repository。
  不再在 context_materializer / runtime_algorithm_adapters 内部写项目网络领域逻辑。

task_system
  不再拥有 task_system.project_network 包。
```

关键迁移：

```text
task_system.project_network.store_models
task_system.project_network.repository
task_system.project_network.semantic_artifact_materializer
task_system.project_network.projection
-> project_network_system.*

task_system.project_network.graph_builder
task_system.project_network.template_catalog
task_system.project_network.directory_runtime_service
task_system.project_network.repair_runtime_service
task_system.project_network.shard_planner
-> project_network_tasks.*

graph_system.runtime_algorithm_adapters._project_network_tree_reduce_postprocess
-> project_network_tasks.runtime_adapters

graph_system.context_materializer._project_network_*
-> project_network_tasks.context_providers
```

新增通用扩展点：

```text
graph_system.adapter_registry
  RuntimeAlgorithmPostprocessAdapter
  runtime_algorithm_structured_output_keys()

graph_system.context_provider_registry
  GraphContextProvider
  apply_context_providers()
  context_provider_initial_input_keys()
  context_provider_runtime_scope_keys()
  context_provider_loop_contract_input_keys()

graph_system.runtime_algorithm_types
  RuntimeAlgorithmPostprocessResult
```

清理结果：

- 删除旧 `backend/task_system/project_network` 包，不保留 import 兼容壳。
- Python 运行引用中不再存在 `task_system.project_network` import。
- `graph_system` 中只剩注册模块字符串：

```text
project_network_tasks.runtime_adapters
project_network_tasks.context_providers
```

保留的唯一旧字符串位于：

```text
project_network_system.repository._authority()
```

这是历史 SQLite 数据 authority 读入归一化，不是旧运行链路。新写入仍使用 `project_network_system.*`。

已验证：

```text
python -m compileall graph_system project_network_system project_network_tasks capability_system/tools/tool_units/project_network_tool.py cli/main.py harness/entrypoint/runtime_facade.py

python -m cli.main graph materialize-directory-tree --frame-id pndirframe:c720145cd6d4fa51f7d3 --backend-dir D:\AI应用\Apix-Version_2.1 --runtime-backend-dir D:\AI应用\langchain-agent\backend --max-total-frames 3

python -m cli.main graph publish-directory-frame --frame-id pndirframe:c720145cd6d4fa51f7d3 --backend-dir D:\AI应用\Apix-Version_2.1 --runtime-backend-dir D:\AI应用\langchain-agent\backend --max-active-nodes 5
```

真实 Apix 验证结论：

- `PROJECT_ARCHITECTURE_OVERVIEW.md` 和 `PROJECT_UNIFIED_CONTROL_GRAPH.md` 可重新 materialize。
- Apix build `apix_v2_1_project_network_probe_20260702_092845` 生成 945 条链路审计信号。
- 深度网络工具 `locate` 对“整体架构”“任务终止”“LLM供应商管理”“websocket ipc”均可返回节点、边、链路和候选审计信息。
- `GraphContextMaterializer.build_work_order()` 对真实目录图文件节点可注入 `project_network_file_review`。
- `GraphContextMaterializer.build_work_order()` 对真实目录汇总节点可注入 `project_network_directory_aggregate`，并插入目录汇总 inbound context。
- 注册后的 `project_network_tasks.runtime_adapters` 能消费真实 Apix `directory_summary` 语义提交，输出 `accepted=True`、`issues=[]`、1 个 work product side effect。

后续仍建议单独优化：

- `materialize-directory-tree --max-total-frames 3` 输出中 `frame_count` 仍显示全量 98 个 frame，说明 CLI 字段语义可能混合了“总扫描帧数”和“预算新增帧数”，需要后续收紧命名或统计口径。
- Apix 关系链路仍有一批 `unknown_target_ref` / `candidate_relation_needs_resolution`，这是语义网络质量和跨语言引用解析质量问题，不属于本次系统边界迁移阻断。
