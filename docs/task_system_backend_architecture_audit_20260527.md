# Task System 后端架构审查与重构计划 - 2026-05-27

## 结论

后端代码量偏大不是正常的“功能自然增长”。当前 `backend/task_system` 与 `backend/runtime/graph_runtime` 约 82 个 Python 文件、23,746 行，其中最大热点集中在少数权责过宽的模块：

| 文件 | 行数 | 当前问题 |
| --- | ---: | --- |
| `backend/task_system/registry/flow_registry.py` | 2,653 | 注册表、JSON 存储、默认值合并、迁移、任务/流程/图派生视图混在一起 |
| `backend/task_system/compiler/coordination_graph_compiler.py` | 1,288 | 编译、校验、默认边生成、graph module、模型解析、scheduler 诊断、legacy 诊断混在一起 |
| `backend/runtime/graph_runtime/batch_runtime.py` | 1,136 | 批处理生命周期复杂度较真实，但应独立成子域 |
| `backend/task_system/services/assembly_builder.py` | 1,074 | runtime assembly 聚合过宽 |
| `backend/task_system/services/assembly_support.py` | 1,012 | intent contract、workflow resolution、recall、安全、bundle/step 绑定混在一起 |
| `backend/runtime/graph_runtime/scheduler.py` | 1,014 | runtime 层仍在解释 dict/metadata，而不是只消费编译后的 RuntimeSpec |
| `backend/task_system/graphs/task_graph_standard_models.py` | 765 | 标准视图同时承担投影、编辑回写、迁移痕迹承载 |
| `backend/task_system/compiler/layered_graph_normalizer.py` | 677 | 从 canonical 字段和 metadata 中重复抽取层，成为第二套解释器 |

我认为后端偏大的根因不是某个文件写得长，而是“决策权重复”。同一个任务图概念在 registry、compiler、standard view、normalizer、scheduler、assembly 多层都被重新解释，尤其是 `metadata`、`fallback`、`timeline_blocks`、`contract_bindings`、`graph_module_runtime` 这些字段。当前范围内相关命中约 751 处，这会让每个新功能都横向扩散。

## 当前运行链路

典型 API 链路在 `backend/api/task_system.py`：

1. API 创建 `TaskFlowRegistry`，读取 graph、specific tasks、protocol。
2. 调用 `build_task_graph_standard_view(...)` 生成前端/诊断投影。
3. 调用 `compile_task_graph_definition_runtime_spec(...)` 生成 runtime spec。
4. 调用 contract manifest、scheduler bootstrap、node runtime assembly、graph module execution plan。
5. 将 standard view、runtime spec、manifest、scheduler state、assembly、split plan 一起打包为 execution package。

这条链路本身合理，但当前每一步都仍能读取原始 graph metadata 并做自己的判断。问题在这里：编译后的 `TaskGraphRuntimeSpec` 没有成为 runtime 的唯一权威输入。

## 权威边界审查

| 层 | 当前文件 | 当前实际权责 | 隐藏决策 | 目标权责 |
| --- | --- | --- | --- | --- |
| Storage | `flow_registry.py` | 读写多个 JSON、合并默认项、缓存 | 文件不存在时静默 fallback，默认配置回写 | 只做 JSON IO、schema version、原子读写 |
| Repository | `flow_registry.py` | task/domain/flow/workflow/graph/protocol/topology 全部查询和 upsert | 通过 metadata 推断 domain/task/graph 关系 | 拆为 TaskGraphRepository、TaskRecordRepository、WorkflowRepository、ProtocolRepository |
| Definition | `task_graph_models.py` | canonical graph dataclass 与基本校验 | 仍允许大量 runtime 关键含义藏在 metadata | 定义一等字段；metadata 非权威 |
| Projection | `task_graph_standard_models.py`、`composable_graph_builder.py` | 标准视图、composable view、编辑回写 | 投影层参与迁移和部分语义解释 | 只呈现 RuntimeSpec/Definition；回写只允许 canonical graph |
| Normalize | `layered_graph_normalizer.py` | 从 metadata/canonical 抽 memory/temporal/artifact/module/timeline 层 | 第二套 compiler，保留 timeline_blocks 主路径 | 迁移期只做显式 normalization report，最终并入 compiler 子模块 |
| Compile | `coordination_graph_compiler.py` | RuntimeSpec、校验、默认边、graph module、模型解析、scheduler 支持报告 | 编译期连接 AppSettings、AgentRuntimeRegistry，默认生成边 | 纯 `TaskGraphDefinition -> TaskGraphRuntimeSpec`；外部依赖作为参数传入 |
| Runtime | `scheduler.py`、`batch_runtime.py` | 调度、handoff、timeline、artifact、repair、batch 状态推进 | scheduler 接受 dict edge/node，并再次解释 metadata | 只消费 RuntimeSpec dataclass，不接受 raw dict，不做语义猜测 |
| Assembly | `assembly_builder.py`、`assembly_support.py` | 节点 runtime packet、intent contract、workflow、recall、安全、bundle | assembly 内部再查 registry、再推断 task mode | 只将 RuntimeSpec node + manifest + explicit context 组装为 agent 输入 |
| API | `backend/api/task_system.py` | 编排所有查询、编译、投影、assembly | API 内重复 protocol id fallback、重复 registry 实例化 | API 只调用应用服务，不直接知道内部组合细节 |

## 主要问题

### 1. `TaskFlowRegistry` 是后端最大膨胀点

`flow_registry.py` 从 `class TaskFlowRegistry` 开始承担了过多责任：读取默认 profile、flow、specific task、domain、contract binding、topology、communication protocol、task graph，并且包含派生 coordination task view 的逻辑。

这不是“注册表”，而是 storage、repository、migration、domain service、projection facade 的混合体。只要它存在，其他层就会继续从 registry 中拿到半成品对象，然后自己补 metadata 推断。

目标：保留一个很薄的兼容 facade 作为迁移入口，但真实代码必须搬到分层 repository。完成后旧 facade 应删除，而不是长期兼容。

### 2. Compiler 不是纯 compiler

`compile_task_graph_definition_runtime_spec` 内部做了这些事：

- 读取 graph runtime/context policy。
- 编译 length budget。
- 调用 layered normalizer。
- 构造 graph module runtime plans。
- 构造 split plans。
- 在函数内部创建 `AppSettingsService`、`ModelProfileResolver`、`AgentRuntimeRegistry`。
- 过滤 resource nodes。
- 编译 runtime nodes/edges。
- 无边时生成默认边。
- 编译 runtime semantics。
- 生成 scheduler support report。
- 合并 layered graph、split、length budget、runtime semantics 诊断。

这导致 compiler 成为“所有下游前置处理器”。一旦 runtime、UI、写作图需要新增诊断，就会塞进这个文件。

目标：compiler 拆为 `node_compiler`、`edge_compiler`、`graph_module_compiler`、`diagnostics`、`runtime_spec_compiler`，主入口只协调这些纯函数。

### 3. Normalizer、Standard View、Composable Builder 是重复解释器

`layered_graph_normalizer.py` 仍从 `graph.metadata.timeline_blocks`、node metadata、edge metadata 抽取 timeline、memory、artifact、revision、loop、graph module 等层。`task_graph_standard_models.py` 又把这些层投影给前端，并保留 `timeline_blocks` 字段。`composable_graph_builder.py` 也在构造另一套 units/ports 视图。

这说明后端存在三套图解释：

1. canonical `TaskGraphDefinition`
2. layered graph normalization
3. standard/composable projection

目标：canonical graph 是唯一编辑/编译来源；standard/composable view 只能展示 canonical + runtime spec，不能继续成为独立语义来源。`timeline_blocks` 应降级为迁移诊断，只读，不进入主编译路径。

### 4. Runtime Scheduler 仍在吃 raw dict

`scheduler.py` 里的 edge helper 同时支持 `TaskGraphRuntimeEdge | dict[str, Any]`，并从 `edge.get(...)`、`edge.metadata`、`metadata.timeline_dependency`、`metadata.temporal_control` 中取值。这让 runtime 层拥有了第二次解释任务图的权力。

目标：scheduler 只接受 `TaskGraphRuntimeSpec` dataclass。raw dict 输入必须在 API 或 repository 边界转换失败；runtime 不负责猜字段、不负责兼容旧 edge 形状。

### 5. Assembly 支持层混入了 agent turn 决策

`assembly_support.py` 同时处理 capability needs、execution obligation、delegation protocol、interaction mode policy、continuation profile、workflow step binding、bundle spec 等。它已经超出“把节点组装成 runtime packet”的职责，接近 agent turn 决策层。

目标：按成熟 agent 架构拆分：

```text
RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> ModelTurnDecision
-> ActionPermit
-> RuntimeStartPacket
-> ExecutionLoop
```

task system 在这里最多应该提供 `RuntimeStartPacket` 的任务图部分，不应该在 assembly support 中重做 intent、能力、交互模式的上游判断。

### 6. Batch runtime 大，但属于可隔离复杂度

`batch_runtime.py` 大量代码围绕 writing graph 的批次计划、review、repair、commit 生命周期。这部分复杂度有业务真实性，不应简单删除。但它不应和通用 graph scheduler 混在同一抽象层。

目标：迁移为 `backend/runtime/graph_runtime/batch_lifecycle/` 子包，输入是 split/batch plan，输出是 lifecycle state transition。通用 scheduler 只调度节点，不理解写作批次细节。

## 重构目标架构

目标不是“拆文件显得小”，而是让每层只有一个决策权：

```text
API
-> TaskSystemApplicationService
-> Repositories
-> TaskGraphDefinition
-> RuntimeSpecCompiler
-> ContractManifestCompiler
-> RuntimeStartPacketAssembler
-> GraphRuntimeScheduler
-> GraphBatchLifecycleRuntime
```

### 包结构建议

```text
backend/task_system/
  storage/
    json_store.py
    schema_version.py
  repositories/
    task_graph_repository.py
    task_record_repository.py
    flow_repository.py
    protocol_repository.py
    topology_repository.py
  definition/
    task_graph_definition.py
    task_graph_validation.py
  compiler/
    runtime_spec_compiler.py
    node_compiler.py
    edge_compiler.py
    graph_module_compiler.py
    diagnostics.py
  projection/
    standard_view.py
    composable_view.py
    migration_report.py
  application/
    task_graph_compile_service.py
    task_graph_execution_package_service.py
  assembly/
    runtime_start_packet.py
    node_context_packet.py
```

```text
backend/runtime/graph_runtime/
  scheduler.py
  run_monitor.py
  batch_lifecycle/
    plan_models.py
    state_machine.py
    transitions.py
```

## 分阶段计划

### Phase 1：拆 storage/repository，削薄 `TaskFlowRegistry`

目标：

- 新建 `TaskSystemStorage`，统一 `_read_json/_write_json`、路径解析、默认 payload 行为。
- 新建 graph/task/flow/protocol/topology repositories。
- `TaskFlowRegistry` 暂时只作为 facade 调用 repositories。
- 所有新代码禁止再向 `flow_registry.py` 添加业务逻辑。

删除/迁移标准：

- registry 中的 path helper、JSON helper、默认 overlay 合并迁移到 storage/repository。
- registry 中的 graph list/get/upsert/delete 迁移到 `TaskGraphRepository`。
- registry 中的 flow/task/domain/protocol/topology 分别迁移。

验证：

```powershell
python -m pytest backend/tests/writing_modular_novel_graph_config_regression.py -q
python -m pytest backend/tests/task_*_regression.py -q
```

### Phase 2：拆 compiler，移除隐式外部依赖

目标：

- `runtime_spec_compiler.py` 主入口只做 orchestration。
- `node_compiler.py` 编译 runtime nodes。
- `edge_compiler.py` 编译 runtime edges。
- `graph_module_compiler.py` 编译 canonical graph_module nodes。
- `diagnostics.py` 汇总 validation issues。
- `ModelProfileResolver`、`AgentRuntimeRegistry` 不在 compiler 内部 new，由调用方传入或预解析为 `CompilerContext`。

删除/迁移标准：

- compiler 不再读取 AppSettingsService。
- compiler 不再生成 hidden fallback graph，缺少必要边时返回 blocking issue；只有明确允许的默认图模板可生成边。
- `timeline_blocks` 不再是 graph module 主来源，只作为 migration diagnostics。

验证：

```powershell
python -m pytest backend/tests/writing_modular_novel_graph_config_regression.py -q
python -m pytest backend/tests/*task_graph* -q
```

### Phase 3：让 scheduler 只消费 RuntimeSpec

目标：

- `scheduler.py` 删除 `TaskGraphRuntimeEdge | dict[str, Any]` 双输入。
- 删除 `_edge_source/_edge_target/_edge_id` 对 raw dict 的兼容分支。
- `timeline_dependency`、`artifact_ref_policy`、`handoff ack` 必须由 compiler 编入 runtime edge 的一等字段或明确 metadata 子结构。

删除/迁移标准：

- runtime 层不再从 `edge.get("from")`、`edge.get("to")`、`metadata.temporal_control` 猜测。
- 旧 dict 输入测试删除或改为 repository/API 边界转换测试。

验证：

```powershell
python -m pytest backend/tests/*graph_runtime* backend/tests/*coordination* -q
```

### Phase 4：投影层迁到 `projection/`，timeline blocks 只读化

目标：

- `task_graph_standard_models.py` 移到 `projection/standard_view.py`。
- `composable_graph_builder.py` 移到 `projection/composable_view.py`。
- migration diagnostics 集中到 `projection/migration_report.py`。
- 标准视图回写只允许 canonical nodes/edges/contract/runtime policy。

删除/迁移标准：

- 删除 primary path 中的 `metadata.timeline_blocks` 编辑和回写。
- 标准视图中的 `timeline_blocks` 字段若仍保留，只标记 `migration_only`，并有删除条件。

验证：

```powershell
python -m pytest backend/tests/*standard* backend/tests/*task_graph* -q
npm test -- taskGraphStandardView taskGraphModuleComposition taskGraphSaveMapper
```

### Phase 5：拆 assembly 支持层

目标：

- `assembly_support.py` 拆为：
  - `intent_contract_builder.py`
  - `workflow_resolution.py`
  - `recall_context_builder.py`
  - `safety_envelope_builder.py`
  - `bundle_step_binding.py`
- task graph node assembly 只接收 `RuntimeSpec node + manifest + explicit_inputs`。

删除/迁移标准：

- assembly 内不再直接创建 `TaskFlowRegistry`。
- task graph runtime packet 不再重跑 task mode 推断。
- agent prompt 只写角色、职责、边界、裁决要求，不写“这是 runtime 节点”这类开发说明。

验证：

```powershell
python -m pytest backend/tests/*assembly* backend/tests/*agent_runtime* -q
```

### Phase 6：隔离 batch lifecycle runtime

目标：

- `batch_runtime.py` 拆成 batch lifecycle 子包。
- 通用 scheduler 不理解 chapter/repair/commit 业务细节，只推进 runtime node 状态。
- 写作图的 batch 行为由 split/batch plan 显式驱动。

删除/迁移标准：

- batch lifecycle 的状态枚举、transition、summary 分离。
- 旧散落在 scheduler/run_monitor 的 batch 特例迁移到 batch 子域。

验证：

```powershell
python -m pytest backend/tests/writing_modular_novel_graph_config_regression.py -q
python -m pytest backend/tests/*batch* backend/tests/*writing* -q
```

### Phase 7：测试重排

目标：

- 删除保护旧内部形状的测试。
- 增加 authority tests：
  - compiler 不访问 storage。
  - scheduler 不接受 raw dict graph。
  - projection 不改变 runtime semantics。
  - metadata 不能覆盖 canonical runtime 字段。
  - timeline_blocks 不参与主编译。

验证：

```powershell
python -m pytest backend/tests -q
npx tsc --noEmit
npm test -- taskGraphEditorSelection taskGraphEditorFocus taskGraphSaveMapper taskGraphUiTerminology taskGraphPreflight taskGraphStandardView taskGraphModuleComposition
```

## 第一轮建议执行范围

我建议下一轮不要一口气动 runtime、compiler、assembly 三条大链。第一轮最好只做：

1. `TaskFlowRegistry` storage/repository 拆分。
2. `coordination_graph_compiler.py` 拆出 `graph_module_compiler` 和 `diagnostics`。
3. 标记并收口 `timeline_blocks` 到 migration-only。

这三项能直接压住代码继续膨胀的根因，同时不会立刻动 scheduler 的运行状态机，风险可控。

## 风险

- 现有工作区有大量非本次任务产生的 runtime/memory/professional 改动，重构前需要保持不回滚、不覆盖。
- API 目前直接拼 execution package，Phase 1/2 后需要一个 application service 承接，否则 API 会继续变大。
- 如果保留 `TaskFlowRegistry` facade 太久，它会重新变成业务入口；必须给 facade 设置删除条件。
- scheduler 改为只吃 dataclass 会暴露旧测试和旧调用方依赖 raw dict 的问题，这些应当修正，不应再加兼容分支。

## 判定

后端代码量异常的核心原因是架构权威边界失守，而不是 Python 文件拆分不足。应优先删除重复解释权、fallback 权和 legacy 主路径。只要 registry、compiler、projection、runtime 继续共同解释 `metadata`，代码量还会继续增长。

下一步应按上面的 Phase 1-3 开始重构，并在每个阶段同步删除旧测试和旧逻辑，不能用兼容层长期保留旧结构。
