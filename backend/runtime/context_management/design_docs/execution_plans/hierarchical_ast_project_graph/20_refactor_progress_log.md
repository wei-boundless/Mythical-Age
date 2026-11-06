# 重构进度日志

状态：实施进度记录，随阶段推进持续更新  
日期：2026-07-04  
入口索引：`00_refactor_execution_index.md`

## 1. 记录原则

每个阶段点必须记录：

- 改动目标；
- 是否贴合 `00_refactor_execution_index.md` 的权威链；
- 逻辑是否准确；
- 验证结果；
- 是否可以继续下一阶段。

本文只记录实施进度，不替代设计文档和代码审查。

## 2. 阶段记录

### Stage A0：Runtime Effect 去领域硬编码

目标：

```text
HarnessRuntimeFacade 不再直接识别 project_network_work_product_ingest。
领域副作用由 RuntimeEffectRegistry 路由到 project_network_tasks.runtime_effects。
```

权威链检查：

- 符合：`Harness = 单 agent 执行权威`。
- 符合：`RuntimeEffectRegistry = 图算法副作用请求到领域 handler 的薄路由`。
- 符合：`ProjectNetworkTasks = 项目网络建立/修复任务适配层`。
- 符合：`ProjectNetworkSystem = 项目网络资产与产物权威`。

逻辑检查：

- harness 只调用 registry，不 import `project_network_tasks` / `project_network_system`。
- project network ingest handler 位于 `project_network_tasks.runtime_effects`。
- GraphSystem 仍只承载 effect request / receipt，不处理项目网络语义。
- 这是净收敛，不是新增第二套调度。

验证：

```text
python -m compileall backend/graph_system backend/project_network_system backend/project_network_tasks backend/harness/entrypoint/runtime_facade.py backend/cli/main.py
rg -n "from project_network_tasks|import project_network_tasks|from project_network_system|import project_network_system" backend/harness backend/graph_system -g "*.py"
python -m cli.main graph materialize-directory-tree --frame-id pndirframe:198c1ec7a3bc8496c617 --max-total-frames 1
handler smoke: completed 1 project_network_tasks.runtime_effect.project_network_work_product_ingest
```

结论：通过，可以继续。

### Stage A1：Writing Runtime Adapter 去 GraphSystem 领域硬编码

目标：

```text
GraphSystem 不再直接 import task_system.runtime_semantics.chapter_progress。
writing_iteration postprocess 迁入 task_system.writing_graphs.runtime_adapters。
GraphSystem 只通过 adapter registry 合并 runtime algorithm postprocess 结果。
```

权威链检查：

- 符合：`GraphSystem = 图结构、图时空、算法调度和 work order 权威`。
- 符合：写作章节进度语义归 `task_system.writing_graphs / runtime_semantics`。
- 符合：adapter registry 只加载 handler，不承载写作语义。

逻辑检查：

- `graph_system.runtime_algorithm_adapters` 不再 import `task_system.runtime_semantics.chapter_progress`。
- `writing_iteration` 的 authority 改为 `task_system.writing_graphs.runtime_adapter.writing_iteration`。
- `postprocess_runtime_algorithm_outputs()` 的外部行为保持不变，仍通过 registry 加载 adapter。
- 删除了搬家后无调用的 `_node_algorithm_kind`。

验证：

```text
python -m compileall backend/graph_system/runtime_algorithm_adapters.py backend/graph_system/adapter_registry.py backend/task_system/writing_graphs/runtime_adapters.py
adapter registry smoke: [('project_network_work_product', 100), ('writing_iteration', 200)]
writing adapter smoke: progress_receipts=1, adapter_id=writing_iteration
```

结论：通过，可以继续。

### Stage B0：Writing Deterministic Work Order Handler 去 GraphSystem 领域硬编码

目标：

```text
GraphNodeWorkOrderExecutor 不再直接构造写作章节 progress receipt。
GraphSystem 提供 DeterministicWorkOrderHandler registry。
写作 progress router handler 迁入 task_system.writing_graphs.work_order_handlers。
```

权威链检查：

- 符合：`GraphSystem = work order 执行封装权威`，仍统一产出 `NodeResultEnvelope` 和事件。
- 符合：`task_system.writing_graphs = 写作图任务语义适配层`，负责章节 progress receipt 的确定性 handler。
- 符合：registry 只按 handler 返回结果，不理解章节语义。
- 未引入新模型 loop，未绕开 harness/graph 的结果封装。

逻辑检查：

- `GraphNodeWorkOrderExecutor` 调用 `handle_deterministic_work_order()`。
- 领域 handler 只返回 `executor_result`，不直接写 GraphLoop 状态。
- 原 `deterministic_progress_receipt` 的成功/失败语义保持：成功走 `_node_result_from_agent_execution()`，失败走 `_agent_execution_not_ok_result()`。
- 删除了执行器内的章节 receipt 构造、章节 route 判断和 artifact evidence 判断。

验证：

```text
python -m compileall backend/graph_system/work_order_executor.py backend/graph_system/work_order_handler_registry.py backend/task_system/writing_graphs/work_order_handlers.py
deterministic handler registry smoke: [('writing_progress_receipt_router', 100)]
writing deterministic handler smoke: ok=True, authority=task_system.writing_graphs.work_order_handler.progress_receipt
adapter/effect/handler registry smoke:
  adapters ['project_network_work_product', 'writing_iteration']
  handlers ['writing_progress_receipt_router']
  effects ['project_network_work_product_ingest']
```

结论：通过，可以继续。

### Stage C0：Progress Receipt Route 算法归位 GraphSystem

目标：

```text
GraphLoop 不再直接 import 或解释 task_system.runtime_semantics.chapter_progress。
progress_receipt route 作为图任务算法保留在 GraphSystem。
具体任务只负责产出 progress receipt，并通过 route_policy 声明 receipt_metric_key / receipt_complete_key / receipt_to_input_mappings。
```

权威链检查：

- 符合：`GraphSystem = 图结构、图时空、算法调度和 work order 权威`，保留 receipt-route 算法、route decision 应用和状态落盘。
- 符合：具体任务是算法实例，写作图只通过 `progress_receipt_policy` 和 `route_policy` 配置算法。
- 符合：写作章节 receipt 的产出与校验仍在 `task_system.writing_graphs.runtime_adapters / work_order_handlers`。
- 符合：删除了 `loop_route_registry` 和 `task_system.writing_graphs.loop_route_handlers`，避免具体任务包持有图算法。

逻辑检查：

- `_evaluate_loop_route()` 原生支持 `progress_receipt` 和 `metric_target`。
- `metric_target` 可在 route_policy 带 receipt 信息时使用 progress receipt 驱动。
- `_first_progress_receipt()` 只提取 receipt dict，不校验写作章节语义。
- `_evaluate_receipt_route_decision()` 只按 route_policy 取 metric、complete、mappings、patch_rules 和 derived_fields，不猜测章节字段。
- 写作图配置脚本已经提供 `receipt_complete_key` 与 `receipt_to_input_mappings`，符合“任务实例用配置套算法”的原则。

验证：

```text
python -m compileall backend/graph_system/loop.py
rg backend: no loop_route_registry / writing_graphs.loop_route_handlers references
rg graph_system-only: no ChapterProgressReceipt / first_chapter_progress_receipt / task_system.runtime_semantics.chapter_progress references
```

结论：通过，可以继续。该阶段根据用户“图任务保留算法，具体任务只是算法搭建的实例”的原则完成校正；剩余 GraphLoop 领域泄漏集中在 review verdict / quality retry / revision requeue，进入 C1。

### Stage C1：Review Verdict Signal 去 GraphSystem 直接语义解析

目标：

```text
GraphLoop / GraphTransitionProcessor 不再直接 import task_system.runtime_semantics.review_gate_verdict。
review verdict 是否触发 revision 的语义判定迁入 task_system.writing_graphs.revision_signal_handlers。
GraphSystem 只消费 revision signal，并继续负责 edge transition、revision target reset 和 state patch。
```

权威链检查：

- 符合：`GraphSystem` 保留边状态推进、revision edge 选择、节点重排权威。
- 符合：写作审稿裁决解析归 `task_system.writing_graphs`。
- 符合：`RevisionSignalRegistry` 是薄路由，返回可审计 signal，不写图状态。
- 符合：`GraphTransitionProcessor` 仍只生成 transition plan，不保存领域资产。

逻辑检查：

- `_ready_rejected_revision_targets()` 改为消费 `source_result_requests_revision()`。
- `GraphTransitionProcessor` 改为消费 `source_result_revision_signal()`，保留 edge gate 需要的 `verdict` 和 `requests_revision`。
- handler 对无 handoff summary 或无 verdict 返回 `None`，不会误触发 revision。
- 结构化 signal 仍保留 handler id 和 authority，方便后续审计。

验证：

```text
python -m compileall backend/graph_system/loop.py backend/graph_system/transition_processor.py backend/graph_system/revision_signal_registry.py backend/task_system/writing_graphs/revision_signal_handlers.py
revision signal registry smoke: [('writing_review_verdict_revision_signal', 200)]
revision signal smoke: {'requests_revision': True, 'verdict': 'revise', ...}
rg graph_system-only: no extract_review_verdict / review_verdict_is_rejected / task_system.runtime_semantics.review_gate_verdict references
```

结论：通过，可以继续。剩余 GraphSystem 到 task_system 的直接语义 import 主要集中在 `work_order_executor.py` 的 quality gate。

### Stage C2：Quality Gate Handler 去 WorkOrderExecutor 领域硬编码

目标：

```text
GraphNodeWorkOrderExecutor 不再直接 import task_system.runtime_semantics.quality_gates。
节点质量门评估迁入 task_system.writing_graphs.quality_gate_handlers。
GraphSystem 只负责合并 quality_acceptance，并据此确定 NodeResultEnvelope 状态、error 和 diagnostics。
```

权威链检查：

- 符合：`GraphSystem = work order 执行封装权威`，仍统一产出 `NodeResultEnvelope`。
- 符合：写作质量门、章节标题一致性、stage business acceptance 归 `task_system.writing_graphs`。
- 符合：`QualityGateRegistry` 是薄路由，不理解具体质量规则。
- 符合：没有保留 executor 内的旧质量门实现。

逻辑检查：

- `_execute_agent_node()` 调用 `evaluate_node_quality_acceptance()`。
- 写作 handler 保留原有触发条件：非 review_gate、存在 length_budget 或 acceptance_policies、final_answer 非空。
- 写作 handler 保留原有 `stage_business_acceptance()` 和章节标题一致性检查。
- executor 中 `_merge_quality_acceptance()`、quality soft pass、recoverable failure、repair route 判断仍由 GraphSystem 负责。

验证：

```text
python -m compileall backend/graph_system/work_order_executor.py backend/graph_system/quality_gate_registry.py backend/task_system/writing_graphs/quality_gate_handlers.py
quality gate registry smoke: [('writing_stage_business_acceptance', 200)]
rg graph_system-only: no stage_business_acceptance / task_system.runtime_semantics.quality_gates references
rg graph_system-only: no task_system.runtime_semantics references
```

结论：通过，可以继续做阶段总验收和下一轮边界审查。

### Stage C3：Revision Requeue 算法与写作返修语义拆分

目标：

```text
GraphLoop 保留 revision requeue 的图算法：发现 revision target、重置节点/边、清空相关 loop iteration、重新调度。
写作任务包负责把审查报告或结构化 revision_route 解析成章节返修队列，并投影成通用 revision_cursor_* 补丁。
```

权威链检查：

- 符合：`GraphSystem = 图结构、图时空、算法调度和 work order 权威`，不解析“第几章要返修”。
- 符合：`task_system.writing_graphs = 写作图任务语义适配层`，负责章节返修文本解析、章节队列、章节需求文本。
- 符合：具体任务只是算法实例，通过 `revision_requires_cursor_patch` 和 handler 返回的 `revision_cursor_key / revision_cursor_values / revision_cursor_start / revision_cursor_end` 套用图算法。
- 符合：删除 GraphLoop 内部的章节 route 解析、中文返修报告解析、`chapter_draft` 节点名判断和 `chapter_revision_requirements` 默认判断。

逻辑检查：

- `RevisionSignalRegistry` 增加 `RevisionRequeuePatchHandler`，仍是薄路由，不写图状态。
- `GraphLoop._revision_cursor_input_patch()` 只收集 revision source result，不解析领域文本。
- `task_system.writing_graphs.revision_signal_handlers` 负责写作章节返修 patch。
- GraphLoop 的 loop iteration 清空逻辑改为通用 cursor range，不再硬编码 `chapter_index / batch_start_index / volume_index`。
- 写作图配置通过 `revision_requires_cursor_patch=True` 声明该节点必须拿到 cursor patch 后才能进入返修。

验证：

```text
python -m compileall backend/graph_system backend/task_system/writing_graphs scripts/configure_writing_modular_novel_graph.py
revision requeue patch smoke: revision_cursor_values=[2], revision_cursor_key=chapter_index, handler_id=writing_chapter_revision_requeue_patch
rg graph_system-only: no chapter_revision / chapter_draft / revision_queue_chapter_indexes / chapter_file_prefix references
```

结论：通过，可以继续。

### Stage D0：Writing Context Provider 接管写作上下文产品

目标：

```text
GraphContextMaterializer 只生成通用 work order、通用 inbound flow、通用 loop_iteration_results。
写作章节台账、当前章节上下文、章节质量重试输入、章节返修上下文由 task_system.writing_graphs.context_providers 接管。
```

权威链检查：

- 符合：`GraphSystem` 保留上下文组装算法和 slot/materialization 权威，但不保留写作章节上下文产品。
- 符合：`task_system.writing_graphs` 负责写作图实例上下文 provider。
- 符合：GraphSystem 不再把 `batch_chapter_ledger`、`chapter_mismatch`、`chapter_file_prefix` 当作内置概念。
- 符合：provider 动态声明写作 initial input / loop contract keys，GraphSystem 白名单不再硬编码写作字段。

逻辑检查：

- `GraphContextMaterializer._loop_iteration_contexts_for_node()` 只输出 `loop_iteration_results`、artifact refs 和通用 artifact payloads。
- 写作 provider 从 loop iteration results 与 result history 生成 `batch_chapter_ledger`，并追加 `writing.batch_chapter_ledger` inbound context。
- quality retry context 在 GraphSystem 中保留为通用 latest quality failure 投影，不再写 `chapter_mismatch` 特判。
- `resume` 不再识别 `chapter_progress_receipt_*` 前缀，改为读取 postprocess error 的 `resume_retryable=True`。
- artifact template values 不再默认补 `volume_index/chapter_index/unit_index/group_index/batch_index`，只对已有的 `*_index / *_count / *_seq` 数值键做通用归一。

验证：

```text
python -m compileall backend/graph_system backend/task_system/writing_graphs backend/project_network_tasks backend/project_network_system backend/harness/entrypoint/runtime_facade.py backend/cli/main.py scripts/configure_writing_modular_novel_graph.py
progress receipt route smoke: action=continue, chapter_index mapped to 2 through explicit receipt_to_input_mappings
writing context provider smoke: batch_chapter_ledger complete_chapter_indexes=[1], appended packet_type=writing.batch_chapter_ledger
rg graph_system-only: no task_system.runtime_semantics references
rg graph_system-only: no loop_route_registry / writing_graphs.loop_route_handlers references
rg graph_system-only: no committed_words / batch_complete / volume_complete / chapter_progress_receipt_ / chapter_file_prefix / chapter_revision / chapter_mismatch / batch_chapter_ledger / revision_queue_chapter_indexes references
```

结论：通过，可以继续做 `work_order_executor` 中记忆候选语义抽取的边界审查。该部分还存在 review/world 语义评分与候选抽取，下一阶段应判断是否迁入 task-specific memory candidate handler。

### Stage D1：Formal Memory 候选语义抽取迁出 GraphSystem

目标：

```text
GraphNodeWorkOrderExecutor 保留 formal memory candidate/commit 的通用写入算法。
具体任务负责从本任务输出中抽取领域记忆候选，例如写作审核建议、阻塞审核问题。
```

权威链检查：

- 符合：`GraphSystem = work order 后处理、formal memory 写候选和提交 receipt 权威`。
- 符合：`task_system.writing_graphs = 写作审核报告语义抽取权威`。
- 符合：新增 `MemoryCandidatePayloadHandler` 只扩展 candidate source payload，不直接写 memory，也不改 graph state。
- 符合：GraphSystem 不再用 world/review/审核/返修等领域字符串给 memory source 打分或抽取候选。

逻辑检查：

- `GraphNodeWorkOrderExecutor._candidate_source_payload()` 只生成基础 diagnostics/final_action payload，并调用 `augment_candidate_source_payload()`。
- 写作审核建议与阻塞问题抽取迁入 `task_system.writing_graphs.memory_candidate_handlers`。
- `_memory_source_context_score()` 和 `_memory_source_artifact_payload_score()` 收缩为通用 candidate/content 信号；领域排除应由 edge materialization policy 配置。
- formal memory service 写候选、commit、receipt、error guard 仍在 GraphSystem 统一执行。

验证：

```text
python -m compileall backend/graph_system backend/task_system/writing_graphs
memory candidate handler smoke: ['writing_review_memory_candidates'], record_kind=planning_advisory
rg graph_system-only: no review_advisory / review_blocking / world_review / world_commit / 审核 / 返修 / 章节 / chapter references
```

结论：通过，可以继续后续任务环境底座阶段。

### Stage E0：Task Environment canonical 模型底座

目标：

```text
新增 TaskWorkEnvironment / AgentExecutionEpisode / WorkProduct / GraphNodeTaskBinding 的 canonical 模型。
只建立任务环境身份、episode、产物和图节点绑定边界，不改变运行行为，不接回旧 executor。
```

权威链检查：

- 符合：`TaskSystem = 持久任务环境、episode、事件、产物和绑定权威`。
- 符合：`TaskWorkEnvironment` 是任务真相，旧 `TaskRun` 没有被复用成 canonical task。
- 符合：`GraphNodeTaskBinding` 只表达 work order 到 task environment 的绑定，不执行图算法、不调模型。
- 符合：`WorkProduct` 是可消费产物候选，不等同 assistant final answer，也不发布项目网络 generation。
- 符合：该阶段没有改动 harness / graph runtime 主执行链，避免半接线造成第二运行路径。

逻辑检查：

- 新增 `backend/task_system/work_environments`，包含 `TaskInstance`、`TaskWorkEnvironment`、`TaskEvent`、`TaskPlan`、`TaskTodoItem`、`SessionTaskBinding`、`TaskEnvironmentLease`、`TaskContextPackage`、`TaskControlSignal`。
- 新增 `backend/task_system/episodes`，包含 `AgentExecutionEpisode` 与 `EpisodeResult`。
- 新增 `backend/task_system/work_products`，包含通用 `WorkProduct`、`WorkProductRef`；后续 `TaskReducerInput` 空模型已在 F7 清理，归并入口改为 `backend/task_system/reducer.py`。
- 新增 `backend/task_system/graph_bindings`，包含 `GraphNodeTaskBinding` 与 work order payload 投影函数。
- 模型只做必要字段校验和 `to_dict/from_dict`，未引入执行副作用、兼容壳或旧 TaskRun 包装。

验证：

```text
python -m compileall backend/task_system/work_environments backend/task_system/episodes backend/task_system/work_products backend/task_system/graph_bindings
model smoke: task_system.task_instance ready scheduled completed project_network created 659a30c3
```

结论：通过，可以继续 Stage E1。下一阶段应建立 SQLite canonical store / repository，使这些模型拥有真实持久化位置，但仍不接运行主链。

### Stage E1：Task Environment SQLite canonical store

目标：

```text
为任务环境底座建立真实 SQLite canonical store。
支持 task instance、task environment、event ledger、session binding、context package、lease、control signal、episode、work product、graph node binding 的基础持久化。
仍不启动 episode、不接旧 task_executor、不改变 graph work order 执行行为。
```

权威链检查：

- 符合：`TaskSystem = task truth store`，canonical 数据落在 `storage/tasks/task_environment.sqlite`。
- 符合：`TaskEvent` 是 append-only ledger，`TaskWorkEnvironment` 是 snapshot 投影。
- 符合：`EpisodeRepository` 只保存 episode/result 事实，不运行模型。
- 符合：`WorkProductRepository` 只保存通用任务产物，不发布项目网络 generation。
- 符合：`GraphNodeTaskBindingRepository` 只保存绑定关系，不创建 graph topology、不调度模型。
- 符合：没有恢复旧 `harness.loop.task_executor` 主线。

逻辑检查：

- `TaskEnvironmentRepository` 新增 schema 和 upsert/get/list/append_event/context_package/lease/control_signal 能力。
- `TaskWorkEnvironmentService.create_task_environment()` 只创建任务实例、环境和 `task_environment_created` 事件，不自动执行 agent。
- `EpisodeRepository` 保存 `AgentExecutionEpisode` 和 `EpisodeResult`。
- `WorkProductRepository` 保存通用 `WorkProduct`，并更新 task environment 的 `latest_work_product_id`。
- `GraphNodeTaskBindingRepository` 支持按 `(graph_run_id, work_order_id)` 查询绑定。
- SQLite 连接已显式关闭，避免 Windows 临时目录和长期服务中的连接泄漏。

验证：

```text
python -m compileall backend/task_system/work_environments backend/task_system/episodes backend/task_system/work_products backend/task_system/graph_bindings
sqlite smoke:
  env_status ready
  revision 1
  events 1 task_environment_created
  latest_product wp:demo
  products 1 project_network module_index
  binding created True
```

结论：通过，可以继续 Stage E2。下一阶段应把 `request_task_run` 从 cut receipt 接回任务环境创建，但仍禁止启动旧 executor。

### Stage E2：request_task_run 接回 TaskWorkEnvironment 分配

目标：

```text
把 request_task_run 从“资源链路已切断”的 cut receipt 改为创建 TaskWorkEnvironment。
返回 task_environment_id / task_instance_id / session_task_binding_id。
仍不启动旧 TaskRun 生命周期，不调用旧 task_executor。
```

权威链检查：

- 符合：`Harness` 只接收 agent 的 `request_task_run` 意图并调用任务环境分配服务。
- 符合：`TaskSystem` 负责创建 `TaskInstance / TaskWorkEnvironment / SessionTaskBinding` 和事件账本。
- 符合：`contract_from_action_request()` 仅作为 TaskStartIntent 规范化解析器使用，没有进入旧 `start_task_lifecycle_from_contract()`。
- 符合：没有创建旧 `TaskRun`，没有调度 `execute_task_run()`。
- 符合：普通 turn、slash task、显式合同三条入口共用同一条任务环境 receipt 逻辑。

逻辑检查：

- 新增 `_task_environment_receipt_events()`，统一创建任务环境并返回 `task_environment_allocated` receipt。
- 删除旧 `_task_system_cut_receipt_events` 及不可达旧 cut 返回块。
- receipt 中包含任务环境、任务实例、session binding 和合同摘要，方便 UI 和后续恢复查询。
- 合同不完整时 fail closed，只返回错误事件，不创建半成品任务环境。
- 成功 receipt 的 `turn_completed_event` 使用 `terminal_reason=task_environment_allocated`，不再伪装成旧 task resource recorded。

验证：

```text
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/task_system/work_environments
rg backend/harness/entrypoint/runtime_facade.py: no _task_system_cut_receipt_events / task_system_cut / 长任务资源链路已切断 / task_resource_request_recorded
receipt smoke:
  receipt task_environment_allocated
  env ready 1 session_turn
  events 1 task_environment_created
  turn_completed task_environment_allocated task_environment_allocated
```

结论：通过，可以继续 Stage E3。下一阶段应给 `GraphNodeWorkOrder` 投影 `GraphNodeTaskBinding` 所需的稳定 hint，但仍不替换 graph node 执行主链。

### Stage E3：GraphNodeWorkOrder 接入 GraphNodeTaskBinding 持久绑定

目标：

```text
GraphSystem 生成 graph node work order 时携带稳定 binding hint。
GraphLoop 在 work order 正式进入 active 状态时，通过 TaskSystem binding sink 持久化 GraphNodeTaskBinding。
仍不启动 episode，不创建旧 TaskRun，不替换 graph node 执行主链。
```

权威链检查：

- 符合：`GraphSystem = 图算法、work order 调度和 active 状态权威`，只决定何时把 work order 标记为 active。
- 符合：`TaskSystem = task environment / graph node binding 持久化权威`，binding 归一化和 SQLite 落库位于 `task_system.graph_bindings`。
- 符合：`Harness = 单 agent 执行入口`，只通过 `AgentRuntimeServices` 注入 binding sink，不解释图节点绑定语义。
- 符合：没有恢复旧 `TaskRun/task_executor`，没有新增第二条节点执行链。

逻辑检查：

- `graph_node_task_binding_hint.binding_id` 改为基于 `graph_run_id + node_id + idempotency_key` 的稳定身份，不再混入带时间戳的 `work_order_id`。
- 新增 `GraphNodeTaskBindingService.bind_work_order()`，只把 work order payload 投影成 `GraphNodeTaskBinding(status="bound")` 并落库。
- `AgentRuntimeServices` 新增 `graph_node_task_binding_sink`，默认由 runtime host 的 `backend_dir` 构造 TaskSystem binding service。
- `GraphLoop._state_with_work_orders()` 在 work order 入 active / work_order_index 同步时调用 binding sink；sink 缺失时显式失败，避免跑出没有任务环境坐标的图节点。
- work_order summary 附带 compact `graph_node_task_binding` 摘要，便于监控和后续恢复查询。

验证：

```text
python -m compileall backend/graph_system/context_materializer.py backend/graph_system/loop.py backend/harness/runtime/services.py backend/task_system/graph_bindings
rg -n "TaskExecutor|task_executor|task_run_control_gateway|TaskLifecycleRecord|start_task_lifecycle|finish_task_lifecycle|compile_task_execution_packet|task_execution_action_schema|build_task_execution_packet_context|task_run_contract_manifest|harness_spine_contract|TASK_EXECUTOR_|rerun_task_executor|task_executor_schedule_failed|task_executor_interrupted_by_runtime_restart|harness\.task_executor|task_run_contract_stable|TASK_EXECUTION_INCREMENTAL_CONTEXT|build_task_execution_incremental_context_frame_payload" backend --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
binding service smoke: gntb:stable bound wo:2 wo:2
```

结论：通过，可以继续 Stage E4。下一阶段应建立 node episode/context package 的准备层，使 graph node 可以拥有任务环境坐标和输入包，但仍不替换当前 harness 执行入口。

### Stage E4：Graph node task preparation / episode / context package 准备层

目标：

```text
GraphNodeWorkOrder 进入 active 状态时，不只保存 binding，还要准备真实 TaskInstance、TaskWorkEnvironment、AgentExecutionEpisode 和 TaskContextPackage。
这些对象只记录任务环境和输入包，不启动模型、不生成旧 TaskRun、不替换 GraphSystem work order executor。
```

权威链检查：

- 符合：`TaskSystem = persistent task environment / episode / context package 权威`，准备对象全部写入 `storage/tasks/task_environment.sqlite`。
- 符合：`GraphSystem = work order active 状态权威`，只在节点正式入 active 时触发准备动作。
- 符合：`Harness = 单 agent execution 权威`，E4 没有新增模型 loop，也没有把 episode 当作执行器。
- 符合：旧 `TaskRun/task_executor` 没有复活，所有新增对象都是新 TaskWorkEnvironment 体系。

逻辑检查：

- `GraphNodeTaskBindingService` 升级为 graph node task preparation 服务，新增 `prepare_work_order()`，返回 `GraphNodeTaskPreparation`。
- `prepare_work_order()` 原子化准备：`GraphNodeTaskBinding(status=bound)`、`TaskInstance(task_kind=graph_node)`、`TaskWorkEnvironment(environment_kind=graph_node)`、`AgentExecutionEpisode(status=scheduled)`、`TaskContextPackage`、`graph_node_task_prepared` 事件。
- `TaskContextPackage` 保存可恢复的 graph context、resource handles、output contract、packet policy 和 work order 输入投影，不复制全量图配置，不生成第二份模型 prompt。
- `AgentRuntimeServices.graph_node_task_preparation_sink` 作为服务表能力注入 GraphLoop；旧的临时 `graph_node_task_binding_sink` 命名已清理。
- GraphLoop 的 work_order_index 记录 compact `graph_node_task_preparation` 摘要，后续 UI/恢复/审计可以顺线查到 task environment、episode 和 context package。

验证：

```text
python -m compileall backend/task_system/graph_bindings backend/task_system/work_environments backend/task_system/episodes backend/harness/runtime/services.py backend/graph_system/loop.py
rg -n "graph_node_task_binding_sink|_persist_graph_node_task_binding|GraphLoop requires graph_node_task_binding_sink|graph_node_task_preparation_sink|prepare_work_order|GraphNodeTaskPreparation" backend/graph_system backend/harness/runtime backend/task_system --glob "*.py"
preparation smoke: bound ready taskctx:8d38d7b7f7a200cbdae9 scheduled 1 graph_node_task_prepared
```

结论：通过，可以继续 Stage E5。下一阶段应把 graph node 执行结果投影回 TaskSystem episode result / task environment 状态，但仍由 GraphSystem 接受 `NodeResultEnvelope` 并推进图状态。

### Stage E5：Graph node result 投影回 TaskSystem episode result / work product

目标：

```text
GraphSystem work order executor 产出 NodeResultEnvelope 后，把结果投影给 TaskSystem。
TaskSystem 记录 episode result、task environment snapshot、通用 WorkProduct candidate 和事件账本。
GraphLoop 是否接受 NodeResultEnvelope、是否推进下游节点，仍完全由 GraphSystem 决定。
```

权威链检查：

- 符合：`GraphSystem = NodeResultEnvelope 接受和图推进权威`，TaskSystem 投影发生在 `accept_node_result()` 前，但不反向决定图状态。
- 符合：`TaskSystem = episode result / work product / task snapshot 权威`，结果持久化位于 `task_system.graph_bindings`、`episodes`、`work_products`、`work_environments`。
- 符合：`WorkProduct` 只是通用候选，不发布项目网络 generation，不解析写作/项目网络领域语义。
- 符合：没有旧 `TaskRun/task_executor`，没有新增第二套模型执行 loop。

逻辑检查：

- `GraphNodeTaskBindingService.record_work_order_result()` 会先确保 preparation 存在，再更新 binding status、episode status、episode result、通用 node_result WorkProduct 和 `graph_node_task_result_recorded` 事件。
- `completed` 映射为 task environment `completed`；`failed/blocked/waiting_human_gate` 映射为 task environment `blocked` 并保留 blocker / continuation hint。
- WorkProduct 的 `product_domain=graph_node`、`product_kind=node_result`，只保存公开 node result 投影、artifact refs、quality acceptance claim 和下游定位 refs。
- `GraphSystem.execute_work_order()` 在 `accept_node_result()` 前调用 result projection；如果 TaskSystem 记录失败，不会静默推进图状态。
- API 返回增加 compact `graph_node_task_result_projection` 摘要，便于 UI/恢复/审计定位 task environment、episode result 和 work product。

验证：

```text
python -m compileall backend/task_system/graph_bindings backend/task_system/work_products backend/graph_system/facade.py backend/harness/runtime/services.py
result projection smoke: completed completed completed completed 1 node_result 2 graph_node_task_result_recorded
python -m compileall backend
rg old executor scan: only intentional legacy_task_executor_removed visible blocker text remains
rg old project_network / temporary binding sink scan: no hits
```

结论：通过，可以继续下一阶段。下一阶段应进入 TaskSystem 查询/恢复/控制面的最小 API 或 reducer 边界收口，让任务环境能够被 UI 和后续图任务恢复链路稳定查询，而不是只在内部落库。

### Stage E6：TaskWorkEnvironment 查询视图和公共 API

目标：

```text
让 TaskWorkEnvironment 不只是内部落库对象，而是可以被 UI、恢复链路和审计工具稳定查询的任务真相视图。
先接只读查询面，不急于接 pause/resume/control signal，避免控制状态机在底座未完全收敛前膨胀。
```

权威链检查：

- 符合：`TaskSystem = task truth store / query view 权威`，视图服务在 `task_system.work_environments` 内拼装环境、episode、work product、binding 和事件。
- 符合：`api.task_system = TaskSystem 公共 API 面`，没有把查询塞进 graph task instance 专属 API。
- 符合：查询 API 不修改状态，不执行模型，不推进图，不发布项目网络资产。
- 符合：没有引入旧 TaskRun 查询兼容壳。

逻辑检查：

- `TaskEnvironmentRepository` 增加 `get_context_package()` 和 `list_context_packages()`。
- `EpisodeRepository` 增加 `list_episodes()` 和 `list_episode_results()`。
- `GraphNodeTaskBindingRepository` 增加 `get_by_task_environment()`，用于从 task environment 反查图节点坐标。
- 新增 `TaskEnvironmentViewService`，提供 `list_task_environments()` 和 `task_environment_detail()`。
- `api.task_system` 新增：
  - `GET /api/task-environments`
  - `GET /api/task-environments/{environment_id}`
- 详情视图包含 task environment、task instance、graph node binding、episodes、episode results、latest/context packages、work products、events 和 summary。

验证：

```text
python -m compileall backend/task_system/work_environments backend/task_system/episodes backend/task_system/graph_bindings backend/api/task_system.py
view smoke: completed True 1 1 2 1
python -m compileall backend
rg old executor scan: only intentional legacy_task_executor_removed visible blocker text remains
rg old project_network / temporary binding sink scan: no hits
```

结论：通过。TaskWorkEnvironment 已具备最小可查询真相面。后续阶段可以继续做控制信号和恢复调度，但必须先明确 control signal 如何与 GraphSystem pause/resume/requeue、Harness episode lease 边界对齐。

### Stage F0：旧 TaskRun/task_executor 主链断权清理

目标：

```text
旧 TaskRun/task_executor 不再作为 harness 可执行主链、恢复主链、active work 控制主链或子 agent 运行主链存在。
request_task_run 只分配 TaskWorkEnvironment，不创建旧 TaskRun，不调度旧 executor。
```

权威链检查：

- 符合：`Harness = 单 agent turn/episode 执行入口`，不再调度旧 `harness.loop.task_executor`。
- 符合：`TaskSystem = persistent task environment`，`request_task_run` 进入 TaskWorkEnvironment 分配。
- 符合：`GraphSystem = graph algorithms and scheduling structure`，不通过旧 TaskRun runner 执行节点。
- 符合：旧恢复、暂停、停止、子 agent task runner 均返回可见 removed-chain receipt，不再尝试隐式调度旧 executor。

逻辑检查：

- `HarnessRuntimeFacade` 移除旧 executor/control gateway 调度方法，恢复请求只返回 `legacy_task_executor_removed`。
- API/CLI 删除旧 execute/pause/resume/approve/stop 路由和客户端命令。
- run monitor 的 pause/stop/close runtime 不再调用旧 gateway。
- agent controller 不再创建 child TaskRun，不再启动旧 subagent task runner。
- 旧 executor 模块已物理删除：`task_executor.py`、`task_executor_controller.py`、`task_run_control_gateway.py`。

验证：

```text
python -m compileall backend/harness/runtime/commit_gate.py backend/harness/loop/task_lifecycle.py backend/harness/loop/__init__.py backend/harness/runtime/control_action_schema.py backend/harness/runtime backend/harness/entrypoint backend/api backend/cli backend/graph_system backend/task_system
rg -n "TaskLifecycleRecord|start_task_lifecycle|finish_task_lifecycle|TaskRunControlGateway|TaskExecutorController|TaskExecutorServices|schedule_task_run_executor|execute_task_run\(|task_executor_controller_scheduled|harness\.loop\.task_executor|harness\.loop\.task_executor_controller|harness\.runtime\.task_run_control_gateway|task_run_control_gateway|task_executor\.pause_boundary|replacement_stop" backend --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
结果：compileall 通过；rg 无命中。
```

结论：通过。旧 TaskRun/task_executor 主链已经断权且无可执行入口残留，可以继续清理旧 packet/schema 内部死代码。

### Stage F1：旧 executor 公开面与幽灵提交特判清理

目标：

```text
删除旧 lifecycle 公开导出和旧 executor 元数据引用。
控制 action schema 指向当前真实权威：TaskWorkEnvironment 分配、旧恢复链路 removed status。
commit gate 不再保留旧 task_executor replacement_stop 专用判断。
```

权威链检查：

- 符合：`task_lifecycle.py` 只保留 TaskStartIntent/TaskRunContract 规范化和 runtime contract 投影。
- 符合：`loop.__init__` 不再导出已删除的 `TaskLifecycleRecord`。
- 符合：`control_action_schema.py` 不再把 request/resume/pause 指向已删除 executor/gateway。
- 符合：`commit_gate.py` 只保留通用输出提交规则，不保留旧 executor source 字符串特判。

逻辑检查：

- 删除 `start_task_lifecycle`、`finish_task_lifecycle`、launch supervision、editor context snapshot 等旧 lifecycle 函数。
- 删除旧 helper：`_model_selection_snapshot`、`_dedupe_tuple`、`_public_schedule_failure_reason`、`_contract_with_origin`。
- `request_task_run` 的 executor metadata 改为 `harness.entrypoint.runtime_facade.task_environment_allocation`。
- `resume_task_recovery` 和 `pause_for_user_steer` 的旧 executor metadata 改为 removed-chain 可见状态，不再引用不存在的 gateway/executor。
- `replacement_stop` 不再参与 assistant session message commit 判断。

验证：

```text
python -m compileall backend/harness/runtime/commit_gate.py backend/harness/loop/task_lifecycle.py backend/harness/loop/__init__.py backend/harness/runtime/control_action_schema.py backend/harness/runtime backend/harness/entrypoint backend/api backend/cli backend/graph_system backend/task_system
rg -n "from runtime\.shared\.models import AgentRun, TaskRun|record_turn_to_task_context_handoff|is_stopped_or_terminal_task_run|is_terminal_task_run_status|TaskLifecycleStatus|TASK_ORIGIN_BINDING_AUTHORITY|_model_selection_snapshot|_dedupe_tuple|_public_schedule_failure_reason|_contract_with_origin|runtime_task_environment_id|runtime_task_permission_mode|task_launch_supervision_policy|requires_task_launch_supervision|wait_task_launch_supervision" backend/harness/loop/task_lifecycle.py backend/harness/loop/__init__.py backend/harness/runtime/control_action_schema.py
结果：compileall 通过；旧 helper/旧导出扫描无命中。
```

结论：通过，可以继续 Stage F2：清理 `compiler.py` / `packet_assembler.py` 中不再公开导出的旧 task execution packet/action schema 死代码，防止模型面保留旧任务执行语义。

### Stage F2：旧 task execution packet / action schema 物理清理

目标：

```text
删除已经没有公开调用方的旧 task_execution packet compiler、packet assembler 分支和 task_execution action schema。
模型面不再保留旧 TaskRun executor 的独立动作协议。
```

权威链检查：

- 符合：`Harness` 当前只保留 `single_agent_turn`、observation follow-up 和 semantic compaction packet 编译入口。
- 符合：旧 `compile_task_execution_packet()` 不再作为隐藏入口存在。
- 符合：`packet_assembler.py` 只保留 single-agent turn packet context 和通用证据投影。
- 符合：旧 task execution action schema 不再向模型面暴露 `tool_call / pause_for_user_steer` 的 TaskRun executor 合同。

逻辑检查：

- 删除 `RuntimeCompiler.compile_task_execution_packet()`。
- 删除 `task_execution_action_schema()`。
- 删除 `build_task_execution_packet_context()` 及 `_task_execution_*` 私有 helper。
- 删除旧 task execution user steering、turn attention index、TaskRunContractManifest 挂载 helper。
- 移除 `compiler.py` / `packet_assembler.py` 中由旧 task execution 分支引入的 import。

验证：

```text
python -m compileall backend/harness/runtime/compiler.py backend/harness/runtime/packet_assembler.py backend/harness/runtime backend/harness/entrypoint backend/api backend/cli backend/graph_system backend/task_system
rg -n "compile_task_execution_packet|task_execution_action_schema|build_task_execution_packet_context|_task_execution_model_action_surface|TASK_EXECUTOR_BASE_ACTION_TYPES|TASK_EXECUTOR_CONDITIONAL_ACTION_TYPES|TASK_EXECUTOR_FORBIDDEN_ORDINARY_ACTION_TYPES|TASK_EXECUTOR_RUNNER_CONTRACT_ID|build_task_execution_incremental_context_frame_payload|TASK_EXECUTION_INCREMENTAL_CONTEXT_CURSOR_SOURCE_REF|TaskRunContractManifest|build_task_run_contract_manifest_from_contract|_attach_task_run_contract_manifest|_user_steering_task_payload|_turn_attention_index_payload_from_task_resource" backend/harness/runtime backend/harness/entrypoint backend/api backend/cli backend/graph_system backend/task_system --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
结果：compileall 通过；运行入口与 packet/schema 旧符号无命中。
```

结论：通过，可以继续清理旧 manifest/module 和上下文段声明。

### Stage F3：旧 task execution manifest / context segment 退役

目标：

```text
删除旧 TaskRunContractManifest 模块和旧 executor spine contract 模块。
移除上下文物理段中已经没有内容生产者的 task_run_contract_stable。
保留仍服务单 agent 工具 follow-up 的 incremental_context_frame，但删除其中 task_execution cursor builder。
```

权威链检查：

- 符合：`RuntimeInvocationPacket` 不再携带 `task_run_contract_manifest`。
- 符合：`context_system` 不再声明无生产者的 `task_run_contract_stable`。
- 符合：`prompt_composition.slot_policy` 不再给旧段分配物理层。
- 符合：`context_contract.inspection_payload` 不再把已退役旧 executor spine contract 当作拓扑资产。

逻辑检查：

- 删除 `backend/harness/runtime/task_run_contract_manifest.py`。
- 删除 `backend/harness/runtime/harness_spine_contract.py`。
- 删除 `RuntimeInvocationPacket.task_run_contract_manifest` 字段和 `to_dict()` 输出。
- 删除 `incremental_context_frame.py` 中旧 `build_task_execution_incremental_context_frame_payload()` 与 task execution constants/helper。
- `runtime.assembly` 的 `task_run_contract_intake.context_segments` 收缩为 `("task_prompt_contract",)`。
- `active_execution_lease` / `turn_state_attention_context` 的旧 `task_run_contract_stable` 引用改为 `task_prompt_contract`。

验证：

```text
python -m compileall backend/harness/runtime/incremental_context_frame.py backend/harness/runtime/invocation_packet.py backend/harness/runtime/context_contract/inspection_payload.py backend/harness/runtime/packet_assembler.py backend/harness/runtime/compiler.py backend/harness/runtime backend/context_system backend/prompt_composition
rg -n "harness_spine_contract|task_run_contract_manifest|TaskRunContractManifest|build_task_run_contract_manifest|TASK_EXECUTION_INCREMENTAL_CONTEXT|build_task_execution_incremental_context_frame_payload|task_run_contract_stable|runtime\.task_run_contract_manifest" backend --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
结果：compileall 通过；旧 manifest/context segment 运行代码无命中。
```

结论：通过，可以继续清理旧恢复动作和健康恢复信号。

### Stage F4：旧 executor recovery / health signal 收敛

目标：

```text
旧 TaskRun 恢复状态不再把 resume_task_run / rerun_task_executor 视为可执行恢复动作。
Graph resume 不再查找旧 graph-node TaskRun 并写入 rerun_task_executor。
HealthSystem 仍可识别 graph work order 停滞，但错误码改为图 work order 语义，不再指向旧 task_executor。
```

权威链检查：

- 符合：`GraphSystem` 只重排 GraphLoop blocked/failed nodes，不恢复旧 TaskRun executor。
- 符合：`Continuation / RecoveryBoundary` 可产生可见 removed-chain receipt，但不宣称会调度 `task_executor_controller.schedule`。
- 符合：`TaskRunStateView` 和 `TaskRunRecoveryState` 不再鼓励旧 TaskRun 自动续跑。
- 符合：健康管家仍保留图 work order 级恢复信号，不依赖旧 executor 名称。

逻辑检查：

- `RECOVERY_ACTIONS` 在 `task_run_recovery_state.py`、`task_run_state_view.py`、`task_run_retention.py` 收为空集合。
- 删除 `graph_system.resume` 中 `_recover_stale_active_graph_node_executors()` 及其旧 TaskRun helper。
- `recovery_boundary_receipt_from_decision()` 的 route 改为 `harness.entrypoint.legacy_task_recovery_removed`。
- `graph_breakpoint_supervisor` 的 stale executor reason 改为 `active_work_order_executor_stale_after_restart`。
- 删除旧展示/配置残留：`task_executor_schedule_failed` 映射、LangSmith 非错误终态、未调用的 `task_executor_backend_config()`、旧 staged task output commit helper。

验证：

```text
python -m compileall backend
rg -n "TaskExecutor|task_executor|task_run_control_gateway|TaskLifecycleRecord|start_task_lifecycle|finish_task_lifecycle|compile_task_execution_packet|task_execution_action_schema|build_task_execution_packet_context|task_run_contract_manifest|harness_spine_contract|TASK_EXECUTOR_|rerun_task_executor|task_executor_schedule_failed|task_executor_interrupted_by_runtime_restart|harness\.task_executor|task_run_contract_stable|TASK_EXECUTION_INCREMENTAL_CONTEXT|build_task_execution_incremental_context_frame_payload" backend --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
结果：compileall 通过；除 `runtime_facade.py` / `control_action_schema.py` 中有意保留的 `legacy_task_executor_removed` 可见阻断文案外，无旧 executor 可执行链、恢复动作、packet/schema、manifest 或上下文段残留。
```

结论：通过。旧结构清理阶段完成，可以继续回到 Stage E3：为 GraphNodeWorkOrder / TaskWorkEnvironment 建立新结构绑定 hint，且不得重新引入旧 TaskRun executor。

### Stage E7：TaskWorkEnvironment 控制信号账本与 graph pause/resume 显式桥接

目标：

```text
TaskSystem 记录任务环境控制意图和处理回执。
GraphSystem 仍拥有 graph run pause/resume 的执行权威。
API 只在 TaskWorkEnvironment 具备 graph node binding 时，把 pause/resume signal 显式桥接到 GraphSystem。
```

权威链检查：

- 符合：`TaskSystem = persistent task environment / event ledger / query view 权威`，只记录 `TaskControlSignal`、事件和任务环境 snapshot。
- 符合：`GraphSystem = graph run control 权威`，pause/resume 仍调用 `request_graph_run_pause()` / `request_graph_run_resume()`。
- 符合：API 是协调面，不成为图算法或任务 reducer；无 graph binding 或不支持的 signal 保持 `pending`，不伪装成已处理。
- 符合：没有重新接回旧 `TaskRun/task_executor` 主链，没有新增模型 loop，也没有用兼容壳吞错误。
- 符合：修正 `AgentRuntimeServices` 默认服务表中 artifact/memory service 与 graph node preparation sink 的错位残留，避免后续接线串权。

逻辑检查：

- `TaskEnvironmentRepository` 增加 `get_control_signal()`、`list_control_signals()`、`list_leases()`，详情视图可读取 control signal 和 lease。
- `TaskWorkEnvironmentService.request_control_signal()` 以稳定 `signal_id + idempotency_key` 写入请求；重复请求不会把已 handled 的 signal 回滚为 pending。
- `TaskWorkEnvironmentService.record_control_signal_handling()` 记录 handled/failed/canceled 回执事件，并只在 handled 时投影环境 snapshot。
- `api.task_system` 新增：
  - `GET /api/task-environments/{environment_id}/control-signals`
  - `POST /api/task-environments/{environment_id}/control-signals`
- POST 桥接规则：仅 `pause_requested` / `resume_requested` 且存在 graph node binding 时调用 GraphSystem；其它 signal 明确保持 pending。

验证：

```text
python -m compileall backend/task_system/work_environments backend/api/task_system.py backend/harness/runtime/services.py
control signal smoke: handled paused 1 3
route smoke: ['/task-environments/{environment_id}/control-signals', '/task-environments/{environment_id}/control-signals']
python -m compileall backend
rg old project_network / temporary binding / old task execution scan: no hits
git diff --check: clean
```

结论：通过。TaskWorkEnvironment 已具备最小控制信号账本、查询面和 graph pause/resume 显式桥接；后续可以继续做 lease acquisition/release 与 graph resume/requeue 的恢复协调，但必须仍保持 TaskSystem 记录意图、GraphSystem 执行图控制、Harness 执行单 agent episode 的三权分离。

### Stage E8：Graph node episode execution lease 落库

目标：

```text
GraphNodeWorkOrder 执行前后，在 TaskSystem 中记录真实 execution lease。
lease 只表达当前任务环境的执行占用边界，不成为第二套执行器，不决定 graph advance。
```

权威链检查：

- 符合：`TaskSystem = task environment lease / episode snapshot / event ledger 权威`。
- 符合：`GraphSystem = work order execution boundary 权威`，只在执行入口调用 acquire/release，并继续由 `NodeResultEnvelope` 决定图推进。
- 符合：`Harness = single agent execution 权威`，lease 不启动模型、不持有工具调度、不替代 harness cell。
- 符合：release 只清理 `active_lease_id`，不会覆盖已完成/阻塞的 result projection。

逻辑检查：

- `GraphNodeTaskBindingService.begin_work_order_execution()` 会确保 preparation 存在，并写入：
  - active `TaskEnvironmentLease`
  - running `AgentExecutionEpisode`
  - `graph_node_execution_lease_acquired` 事件
  - task environment `leased / active_episode_id / active_lease_id` snapshot
- `GraphNodeTaskBindingService.release_work_order_execution_lease()` 会写入 released lease 和 `graph_node_execution_lease_released` 事件。
- 如果 release 时环境仍是 `leased`，退回 `ready`；如果 result projection 已经把环境写成 `completed/blocked`，release 只清 `active_lease_id`，不覆盖结果状态。
- `GraphSystem.execute_work_order()` 在 work order executor 前 acquire lease，在 result projection 后 release lease，并把 compact lease 摘要投到返回值。

验证：

```text
python -m compileall backend/task_system/graph_bindings backend/task_system/work_environments backend/graph_system/facade.py
lease smoke: active released ready  1 3
result-before-release smoke: completed completed node completed  released completed
python -m compileall backend
rg old project_network / temporary binding / old task execution scan: no hits
git diff --check: clean
```

结论：通过。Graph node task environment 已经具备可查询、可恢复判断的 execution lease 边界。下一阶段可以做 graph resume/requeue 与 TaskSystem lease/control signal 的协调查询，但仍不得让 TaskSystem 直接推进图状态。

### Stage E9：TaskWorkEnvironment 恢复候选只读视图

目标：

```text
提供任务环境恢复候选查询面。
该查询面只回答哪些 TaskWorkEnvironment 没有有效 active lease、具备恢复/接管判断价值。
它不执行 resume、requeue、repair，也不替代 GraphSystem 或 Harness 的恢复权威。
```

权威链检查：

- 符合：`TaskSystem = 查询 task truth / lease / pending control signal 权威`。
- 符合：`GraphSystem = graph resume / requeue / repair action 权威`，E9 只给 graph binding 和 recovery hint。
- 符合：`Harness = single agent episode recovery authority`，非 graph 环境只标注 `task_system` 接管提示，不启动 runtime。
- 符合：没有新增 executor、没有旧 TaskRun 恢复链、没有隐式自动恢复。

逻辑检查：

- `TaskEnvironmentViewService.list_resumable_task_environments()` 使用 canonical `list_resumable()`，排除仍有未过期 active lease 的环境。
- 每个候选项携带：
  - task environment / task instance / graph node binding 摘要；
  - pending control signals；
  - latest leases；
  - recovery hint。
- graph node 环境的 hint 指向 GraphSystem：paused 建议 graph resume；blocked 建议先审查 node result 再 requeue/repair。
- 普通任务环境的 hint 指向 TaskSystem/Harness 后续恢复入口，不越权执行。
- `GET /api/task-environments/resumable` 放在 `{environment_id}` 动态路由前，避免路由串线。

验证：

```text
python -m compileall backend/task_system/work_environments backend/api/task_system.py
route order smoke: ['/task-environments', '/task-environments/resumable', '/task-environments/{environment_id}', ...]
resumable smoke: 1 ready 1 task_system
python -m compileall backend
rg old project_network / temporary binding / old task execution scan: no hits
git diff --check: clean
```

结论：通过。TaskWorkEnvironment 已具备查询、控制信号、lease 和恢复候选四个基础面。下一阶段可进入“恢复动作协调”设计，但必须先明确：TaskSystem 只能提出候选和记录意图，GraphSystem/Harness 才能执行恢复动作。

### Stage F5：旧 task_run_executor 控制命名和死白名单清理

目标：

```text
删除已经不再存在的 task_run_executor 控制入口和事件白名单残留。
保留当前真实能力：runtime cell control 只负责发布 runtime control signal，并取消当前 agent cell / tool invocation。
```

权威链检查：

- 符合：`Harness runtime cell control = 当前单 agent cell 的取消/暂停/停止信号权威`。
- 符合：它不调度旧 TaskRun executor，不维护 executor epoch，不恢复旧执行器。
- 符合：`TaskRunRetention`、`TaskRecordLifecycleManager`、`SessionRuntimeLifecycleManager` 只请求 runtime cell stop，不再称为 executor stop。
- 符合：Graph recovery 不再把 `task_run_executor_already_running` 当作可恢复原因。

逻辑检查：

- 新增 `harness.loop.runtime_cell_control`，只保留当前被调用的能力：
  - 发布 `control.signal.requested`；
  - 取消 active cell 的 tool invocation；
  - 无 active cell 时发布 target unavailable；
  - event adapter 改为 `runtime_cell`。
- 删除旧 `harness.loop.task_run_execution_control.py`。
- 删除未被调用的 executor epoch / model task registry / peek / clear 等旧控制函数。
- 删除 `task_run_executor_*` 事件白名单、timeline/run_monitor 旧事件识别和 graph recovery 旧原因。

验证：

```text
python -m compileall backend/harness/loop/runtime_cell_control.py backend/harness/runtime/task_run_retention.py backend/harness/runtime/task_record_lifecycle.py backend/harness/runtime/session_lifecycle.py backend/graph_system/resume.py backend/health_system/graph_breakpoint_command_supervisor.py backend/runtime/shared/events.py backend/runtime/shared/event_log.py backend/harness/runtime/session_timeline.py backend/harness/runtime/run_monitor/projector.py
runtime cell smoke: sig:1 runtime_cell stop
python -m compileall backend
rg old executor control/project-network/task-execution scan: no hits
git diff --check: clean except existing CRLF warnings for context_materializer.py and resume.py
```

结论：通过。旧 task_run_executor 控制入口和事件白名单已清掉，当前控制语义收敛到 runtime cell control。后续恢复动作协调可以基于 TaskWorkEnvironment control signal / lease / resumable view 和 GraphSystem resume/requeue 继续推进。

### Stage E10：TaskWorkEnvironment 恢复动作协调

目标：

```text
TaskSystem 记录恢复控制意图和处理回执。
API 作为显式协调面把恢复动作交给 GraphSystem / GraphLoop。
TaskSystem 不直接推进图状态、不创建第二套 executor、不吞掉失败。
```

权威链检查：

- 符合：`TaskSystem = task environment control signal / event ledger / recovery query 权威`。
- 符合：`GraphSystem = graph resume / requeue / dispatch 权威`。
- 符合：`GraphLoop = ready dispatch / node requeue / checkpoint 权威`。
- 符合：API 只在 task environment 具备完整 graph node binding 和已发布 graph config 时桥接动作；缺 binding、缺 config、缺 graph system 都显式返回 pending/failed。
- 符合：没有接回旧 `TaskRun/task_executor`，没有把 TaskWorkEnvironment 改造成图推进器。

逻辑检查：

- 新增 `POST /api/task-environments/{environment_id}/recovery-actions`。
- 支持动作：
  - `resume_graph_run`：记录 `resume_requested`，调用 `GraphSystem.resume_run()`。
  - `dispatch_ready_graph_nodes`：记录 `resume_requested`，调用 `GraphLoop.dispatch_ready_and_checkpoint()`。
  - `requeue_graph_node`：记录 `replan_requested`，调用 `GraphLoop.requeue_nodes_and_checkpoint()`，可选随后 dispatch ready nodes。
- `TaskEnvironmentRecoveryActionRequest` 可携带 `start_node_ids`、`reset_downstream`、`dispatch_ready`、`max_dispatch_requests`、`runtime_settings_patch`。
- `_apply_task_environment_recovery_action_bridge()` 只从 detail 视图读取 `graph_node_binding`，再通过 `TaskFlowRegistry.get_graph_config(config_id)` 取不可变图配置。
- 桥接返回 compact graph summary，避免把大 graph state / work order 全量塞回控制信号。
- bridge 状态为 handled/failed 时，统一调用 `record_control_signal_handling()` 写入回执；pending 状态保持待处理，不伪装成功。

验证：

```text
python -m compileall backend/api/task_system.py
recovery action smoke:
  prepared taskenv.recovery.smoke.node.a cfg.recovery.smoke
  observed [('resume_graph_run', 'handled', True, 'handled'), ('dispatch_ready_graph_nodes', 'handled', True, 'handled'), ('requeue_graph_node', 'handled', True, 'handled')]
  graph_calls include resume_run(graph_config=cfg.recovery.smoke, graph_run_id=gr.recovery.smoke, dispatch_ready=True, max_requests=3)
  loop_calls include dispatch_ready_and_checkpoint(...) and requeue_nodes_and_checkpoint(start_node_ids=('node.a',), runtime_settings_patch=...)
python -m compileall backend
rg old executor control/project-network/task-execution scan: no hits
git diff --check: clean except existing CRLF warnings for context_materializer.py and resume.py
```

结论：通过。TaskWorkEnvironment 已具备恢复动作协调入口；恢复动作仍由 GraphSystem / GraphLoop 执行，TaskSystem 只保存意图、状态和处理回执。下一阶段应继续审查是否还存在旧 TaskRun 任务环境边界残留，并补齐任务环境对 GraphSystem 状态的只读投影，而不是新增执行权威。

### Stage E11：TaskWorkEnvironment graph runtime 只读投影

目标：

```text
任务环境详情和恢复候选视图能看见绑定的 GraphSystem 当前状态。
该投影只读，不改变 TaskSystem canonical store，也不让 TaskSystem 推进 GraphLoop。
```

权威链检查：

- 符合：`TaskSystem = 任务环境、binding、episode、control signal 查询权威`。
- 符合：`GraphSystem = graph run monitor / checkpoint / loop state 权威`。
- 符合：API 只做 present/coordinate，读取 `GraphSystem.get_graph_run_monitor()` 和 `get_latest_checkpoint()`，不写 graph state。
- 符合：`TaskEnvironmentViewService` 只补充 compact binding 的 `config_id`，不 import GraphSystem。

逻辑检查：

- `GET /api/task-environments/{environment_id}` 附加 `graph_runtime_projection`。
- `GET /api/task-environments/resumable` 的每个 item 附加 `graph_runtime_projection`。
- 新增 `GET /api/task-environments/{environment_id}/graph-runtime`，用于前端轻量刷新 graph runtime 视图。
- 投影内容只包含：
  - graph run/config 可用性；
  - loop status、ready/running/blocked/failed ids；
  - 当前 node runtime status、result ref、active work order id；
  - latest checkpoint 摘要。
- 缺 graph binding、缺 GraphSystem、缺 monitor、缺 config 都以 `available=False + reason` 显式呈现。

验证：

```text
python -m compileall backend/api/task_system.py backend/task_system/work_environments/view_service.py
graph runtime projection smoke:
  detail True running {'node_id': 'node.a', 'status': 'running', 'result_ref': '', 'active_work_order_id': 'wo.a', 'is_active': True}
  checkpoint {'checkpoint_id': 'ck.projection.smoke', 'graph_run_id': 'gr.projection.smoke', 'event_cursor': 7}
  list True cfg.projection.smoke wo.a
route order smoke:
  ['/task-environments', '/task-environments/resumable', '/task-environments/{environment_id}', '/task-environments/{environment_id}/graph-runtime', ...]
python -m compileall backend
rg old executor control/project-network/task-execution scan: no hits
git diff --check: clean except existing CRLF warnings for context_materializer.py and resume.py
```

结论：通过。任务环境查询面已经能向人和前端展示 graph-bound task 的运行状态，但没有新增执行权威。下一阶段应继续补齐任务环境作为“持久工作现场”的基础能力，优先处理 status/control/recovery 的语义一致性和过期 lease 回收。

### Stage E12：TaskWorkEnvironment stale lease recovery

目标：

```text
过期 active lease 不再让任务环境永久卡在 leased。
TaskSystem 回收过期 lease，写入 interrupted episode 和可恢复环境状态。
回收动作不自动重跑 agent，不自动推进 GraphLoop。
```

权威链检查：

- 符合：`TaskSystem = lease / episode / task snapshot / event ledger 权威`。
- 符合：`Harness` 仍是唯一 agent 执行权威，stale recovery 不启动模型。
- 符合：`GraphSystem` 仍是图恢复权威，stale recovery 只让 graph-bound task environment 回到可查询、可恢复状态。
- 符合：API 暴露的是维护动作 `recover-stale-leases`，不是隐式 resume。

逻辑检查：

- `TaskEnvironmentRepository.list_expired_active_leases()` 查询 `status='active' AND expires_at <= now`。
- `TaskWorkEnvironmentService.recover_stale_leases()` 对每条过期 lease：
  - lease 状态改为 `expired`；
  - running/scheduled/waiting episode 改为 `interrupted`；
  - 追加 `task_environment_lease_expired` event；
  - 如果环境仍由该 lease 占用，则清空 `active_lease_id`，状态改为 `paused`，设置 `recovery_action='resume_task_environment'`；
  - 不 dispatch、不 requeue、不 resume。
- 新增 `POST /api/task-environments/recover-stale-leases`，路由放在 `{environment_id}` 前，避免动态路由吞掉。
- `TaskEnvironmentStatus` 字面类型补齐 `failed / aborted`，与控制语义和文档一致。

验证：

```text
python -m compileall backend/task_system/work_environments backend/task_system/episodes backend/api/task_system.py
stale lease recovery smoke:
  before leased lease:6afd103396d219313338
  after paused  resume_task_environment lease_expired
  lease expired task_environment_lease_expired
  episode interrupted task_environment_lease_expired
  recovered 1 task_environment_lease_expired
  resumable [('taskenv.stale.node', 'paused')]
route order smoke:
  ['/task-environments', '/task-environments/resumable', '/task-environments/recover-stale-leases', '/task-environments/{environment_id}', ...]
python -m compileall backend
rg old executor control/project-network/task-execution scan: no hits
git diff --check: clean except existing CRLF warnings for context_materializer.py and resume.py
```

结论：通过。TaskWorkEnvironment 现在具备 lease 过期后的可恢复边界，不会因为执行中断永久占用环境。下一阶段应继续补齐任务环境的查询/控制一致性，尤其是 active lease count、recovery hint 和 graph-bound recovery action 的前端可解释性。

### Stage E13：TaskWorkEnvironment activity/control query projection

目标：

```text
任务环境详情和恢复候选视图直接呈现 activity_state 与 control_capabilities。
前端和 agent 能判断当前环境是 running / stale_lease / paused / blocked，以及应该走哪个控制 API。
该能力只读，不发控制信号，不恢复任务，不推进图。
```

权威链检查：

- 符合：`TaskEnvironmentViewService = 查询投影权威`。
- 符合：`TaskWorkEnvironmentService = 控制/回收命令权威`，view 不写状态。
- 符合：`GraphSystem = graph recovery/action 权威`，view 只通过 binding 提示 graph recovery 是否支持。
- 符合：active lease 判断使用 lease status + expires_at，不把过期 active lease 当作正在运行。

逻辑检查：

- 详情视图新增：
  - `activity_state`：running / stale_lease / paused / blocked / completed / idle 等；
  - `recovery_hint`；
  - `control_capabilities`：can_request_pause / can_request_resume / can_request_replan / can_request_abort / can_recover_stale_lease / graph_recovery_supported / recommended_api。
- resumable 列表 item 同步新增 `activity_state` 和 `control_capabilities`。
- `summary.active_lease_count` 改为只统计未过期 active lease。
- active lease 时推荐 `POST /api/task-environments/{environment_id}/control-signals`。
- stale lease 时推荐 `POST /api/task-environments/recover-stale-leases`。
- graph-bound ready/paused/blocked 时推荐 `POST /api/task-environments/{environment_id}/recovery-actions`。

验证：

```text
python -m compileall backend/task_system/work_environments/view_service.py
projection helper smoke:
  state=running, active_lease_count=1, can_request_pause=True, recommended_api=control-signals
task environment detail smoke:
  activity_state {'state': 'running', 'environment_status': 'leased', 'active_lease_count': 1, ...}
  control_capabilities {'can_request_pause': True, 'can_request_resume': False, 'can_request_abort': True, 'graph_recovery_supported': True, ...}
python -m compileall backend
rg old executor control/project-network/task-execution scan: no hits
git diff --check: clean except existing CRLF warnings for context_materializer.py and resume.py
```

结论：通过。TaskWorkEnvironment 的查询面已经从“数据库详情”升级为可操作的任务控制台投影。下一阶段应继续检查 TaskSystem / GraphSystem / Harness 接线中是否还有旧 TaskRun 语义命名或重复恢复入口残留。

### Stage F6：旧 TaskRun recovery action 空分支清理

目标：

```text
旧 TaskRun 不能再通过 diagnostics.recovery_action 或空的 RECOVERY_ACTIONS 表暗示存在原地恢复动作体系。
TaskRun 状态视图只保留运行事实展示；任务恢复、图恢复和 stale lease 恢复分别归 TaskSystem / GraphSystem / RuntimeCell 控制链。
```

权威链检查：

- 符合：`Harness` 只负责单 agent runtime cell 的执行与运行事实投影。
- 符合：`TaskSystem` 才记录任务环境恢复意图，例如 `resume_task_environment`。
- 符合：`GraphSystem` 才处理 graph-bound node 的 resume / requeue / dispatch。
- 符合：旧 `TaskRun` 的 recoverable/error 字段只能作为诊断事实，不再驱动 same-run recovery action 表。

逻辑检查：

- 删除 `backend/harness/runtime/task_run_retention.py` 中最后一个空 `RECOVERY_ACTIONS` 常量。
- `backend/harness/loop/task_run_recovery_state.py` 已移除旧 recovery action 表驱动判断，只允许 durable paused boundary、approval grant、launch gate pass 形成 same-run executable。
- `backend/harness/task_run_state_view.py` 已移除旧 `RECOVERY_ACTIONS` 分支；`recovery_cause` 不再从 wait_reason / recoverable_error 猜旧恢复原因。
- `runtime_cell_control` 取代旧 executor control signal，retention stop 只向 runtime cell 请求停止。

验证：

```text
python -m compileall backend/harness/task_run_state_view.py backend/harness/loop/task_run_recovery_state.py backend/harness/runtime/task_run_retention.py backend/harness/entrypoint/runtime_facade.py
rg RECOVERY_ACTIONS backend/harness backend/graph_system: no hits
rg old executor control names: no hits
rg _attach_recovery_packet_to_task_run backend: no hits
```

结论：通过。旧 TaskRun recovery action 空表和空分支已清理，后续恢复入口应只从 TaskWorkEnvironment control/recovery action 或 GraphSystem recovery action 进入。

### Stage F7：TaskReducer 落地与 graph result 归并改接线

目标：

```text
EpisodeResult / WorkProduct / TaskEnvironment snapshot 的归并权威从 GraphNodeTaskBindingService 抽到通用 TaskReducer。
Graph binding service 只负责把 GraphNodeWorkOrder / NodeResultEnvelope 适配成任务系统输入，不再亲自写多张任务表。
```

权威链检查：

- 符合：`GraphSystem` 仍负责 work order 调度、执行顺序和 NodeResultEnvelope 产生。
- 符合：`GraphNodeTaskBindingService` 只负责 graph node 与 task environment 的绑定和适配。
- 符合：`TaskReducer` 是 EpisodeResult、WorkProduct candidate、TaskEvent、TaskWorkEnvironment snapshot 的归并权威。
- 符合：lease acquire/release 仍由 graph binding 的 lease 方法处理，reducer 不擅自清 lease 或调度下一节点。

逻辑检查：

- 新增 `backend/task_system/reducer.py`：
  - `TaskReducer.reduce_episode_result()` 校验 episode/result/product/event scope；
  - 更新 `AgentExecutionEpisode`；
  - 写入 `EpisodeResult`；
  - 写入通用 `WorkProduct`；
  - 追加任务事件并应用 snapshot patch。
- `GraphNodeTaskBindingService.record_work_order_result()` 改为：
  - 生成 graph-specific `EpisodeResult`、`WorkProduct`、`TaskEvent`；
  - 调用 `TaskReducer.reduce_episode_result()`；
  - 返回 reducer 写入后的 projection。
- 删除未接线的 `TaskReducerInput` / `WorkProductReducerPolicy` TaskSystem 旧模型出口，避免存在伪 reducer API。

验证：

```text
python -m compileall backend/task_system/reducer.py backend/task_system/graph_bindings/service.py backend/task_system/work_products/models.py backend/task_system/work_products/__init__.py
rg TaskReducerInput backend/task_system: no hits
graph binding reducer smoke:
  env completed completed <empty active_lease_id>
  episode completed node_result_completed True
  result completed 1
  products 1 graph_node
```

结论：通过。TaskSystem 现在具备一个通用结果归并入口，项目网络审查任务后续可以复用同一 reducer，而不需要在每个任务适配器里重复写 episode/product/snapshot 链路。

### Stage F8：普通 TaskWorkEnvironment episode/context package 准备能力

目标：

```text
request_task_run / session task 创建出的普通 TaskWorkEnvironment 不能只有环境壳。
TaskSystem 必须能为普通任务环境准备 AgentExecutionEpisode 和 TaskContextPackage，形成区别于普通 turn 的持久任务现场。
```

权威链检查：

- 符合：`TaskWorkEnvironmentService` 负责准备 episode/context package 和记录任务事件。
- 符合：`prepare_task_episode` 不运行模型、不抢占 lease、不推进 GraphLoop。
- 符合：`TaskContextPackage` 包含 role_contract、goal、scope、acceptance、resource handles、graph/project-network handles、continuation hint 和 output contract。
- 符合：episode 明确绑定 `input_context_package_id`，后续 harness bridge 可以用该 package 构造执行输入。

逻辑检查：

- 新增 `TaskEpisodePreparation`。
- 新增 `TaskWorkEnvironmentService.prepare_task_episode()`：
  - 禁止 terminal environment 准备新 episode；
  - 禁止存在未过期 active lease 时重复准备；
  - 创建/更新 `AgentExecutionEpisode(status=scheduled)`；
  - 生成并写入 `TaskContextPackage`；
  - 把 episode 的 `input_context_package_id` 指向 package；
  - 追加 `task_episode_prepared` event；
  - 更新 task environment snapshot 的 phase/step/latest_context_package。
- 新增 `POST /api/task-environments/{environment_id}/episodes/prepare`。
- 默认 role contract 写成 agent 可直接执行的职责契约，而不是开发说明。

验证：

```text
python -m compileall backend/task_system/work_environments/service.py backend/task_system/work_environments/__init__.py backend/api/task_system.py
ordinary task episode preparation smoke:
  env ready prepared True
  episode scheduled True coding_agent
  context 验证普通任务环境可以准备 episode。 b69bf0ea ['memory:stable']
  detail 1 1 True
api route order smoke:
  /task-environments/{environment_id}/episodes/prepare present
```

结论：通过。普通任务环境现在具备 episode/context package 准备入口，后续可以继续接 harness bridge / scheduler，而不是依赖旧 TaskRun 或 session transcript。

### Stage F9：TaskSystem 统一 episode lease acquire/release

目标：

```text
执行租约必须归 TaskSystem 管理。
Graph node adapter 可以声明 holder / event 语义，但不直接写 lease 表或 task environment leased snapshot。
```

权威链检查：

- 符合：`TaskWorkEnvironmentService` 负责 acquire/release episode lease。
- 符合：`GraphNodeTaskBindingService` 只把 graph node execution 映射为 lease holder/event 参数。
- 符合：GraphSystem 仍只调用 begin/release work order execution，不直接写 TaskSystem 存储。
- 符合：result reducer 不擅自清 lease；lease release 仍是单独控制边界。

逻辑检查：

- 新增 `TaskEpisodeLeaseProjection`。
- 新增 `TaskWorkEnvironmentService.acquire_episode_lease()`：
  - 校验 environment / episode 归属；
  - 阻止不同 active lease 叠加；
  - 支持 idempotency key；
  - 写 `TaskEnvironmentLease(active)`；
  - 更新 episode 为 `running`；
  - 追加 lease acquired event；
  - snapshot 进入 `leased`，写 active episode/lease。
- 新增 `TaskWorkEnvironmentService.release_episode_lease()`：
  - 写 `TaskEnvironmentLease(released)`；
  - running episode 进入 `interrupted`，等待 reducer 或后续 episode 修正最终状态；
  - 追加 lease released event；
  - 清空 active lease，leased environment 回到 ready。
- `GraphNodeTaskBindingService.begin_work_order_execution()` / `release_work_order_execution_lease()` 改接通用服务。
- 删除 graph binding 里旧 `_append_execution_lease_acquired_event` / `_append_execution_lease_released_event`。

验证：

```text
python -m compileall backend/task_system/work_environments/service.py backend/task_system/graph_bindings/service.py
graph binding lease/result smoke:
  lease_event graph_node_execution_lease_acquired active leased
  release_event graph_node_execution_lease_released released ready <empty active_lease_id>
  result_env completed <empty active_lease_id>
  episode completed node_result_completed
  products 1
ordinary task lease smoke:
  lease leased running active
  release ready <empty active_lease_id> interrupted released
rg _append_execution_lease backend/task_system/graph_bindings/service.py: no hits
```

结论：通过。任务执行租约现在有统一 TaskSystem 权威，图任务和普通任务可以复用同一 lease 生命周期。

### Stage F10：Graph node agent profile 显式承接与工具权威收束

目标：

```text
Graph node 只负责把任务契约、输入、输出和边界交给明确配置的 agent。
工具能力不由 node contract、tool_scope 或 permission_scope 授权，只由 node 显式绑定的 AgentRuntimeProfile 进入 harness runtime assembly 后决定。
```

权威链检查：

- 符合：`GraphNodeWorkOrder(work_kind="agent")` 必须带 `agent_profile_id`，缺失时作为图配置错误显式失败，不回退到 main/default/graph_node_worker。
- 符合：`GraphContextMaterializer` 从 node / compiled contract 的 agent assembly 归一生成 `agent_id` / `agent_profile_id`。
- 符合：GraphNodeTaskBinding hint 也复用同一 agent assembly 解析结果，避免 work order 有 profile、TaskSystem ledger 空 profile 的身份分裂。
- 符合：`GraphNodeWorkOrder` 不再携带 `permission_scope` / `tool_scope` 字段，避免后续层误接成工具授权。
- 符合：graph node agent-visible message 只投递职责、输入、上游上下文、输出契约和执行边界；即使旧上下文里混入 `tool_scope` / `tool_contract` / `permission_contract`，也会被 harness bridge 过滤。
- 符合：harness executor diagnostics 明确记录 `tool_authority=agent_runtime_profile_runtime_assembly`，不再记录旧的 `operation_ceiling`。
- 符合：删除不可达的 `harness/runtime/graph_node_contract.py` 旧 adapter；该 adapter 会从 node/tool contract 推导 allowed operations，不再具备合法权威。

逻辑检查：

- `backend/graph_system/models.py`
  - `GraphNodeWorkOrder.__post_init__()` 对 agent work order 强制校验 `agent_profile_id`。
  - `to_dict()` / `from_dict()` 不再包含 `permission_scope` / `tool_scope`。
- `backend/graph_system/context_materializer.py`
  - 新增 `_node_agent_config()`，统一从 node 配置和 compiled contract agent assembly 解析 agent 配置。
  - work order、input package node identity、node_contract.agent_assembly、GraphNodeTaskBinding hint 全部使用同一解析结果。
  - `node_contract` 执行投影移除 `tool_contract`、`skill_contract`、`permission_contract`。
  - `runtime_profile` 投影移除 `tool_policy`、`permission_policy`。
  - slot visibility 移除 `node_contract.tool_contract` / `node_contract.permission_contract`。
- `backend/task_system/graph_bindings/service.py`
  - context package resource handles 不再记录 `permission_scope` / `tool_scope`。
- `backend/harness/entrypoint/runtime_facade.py`
  - graph node message 新增 agent-visible 规则：工具能力只以当前 agent profile 的 runtime-visible tools 为准。
  - 新增 agent-visible graph context/resource handles 过滤，阻断伪授权字段进入节点 prompt。
- `backend/scripts/diagnose_real_writing_prompt_cache.py`
  - 删除旧 `--work-order` 重编译分支；脚本只诊断真实 runtime packet，不再私自把 GraphNodeWorkOrder 编译成旧 TaskRunContract。

验证：

```text
python -m compileall backend/graph_system/models.py backend/graph_system/context_materializer.py backend/graph_system/facade.py backend/task_system/graph_bindings/service.py backend/harness/entrypoint/runtime_facade.py
python -m compileall backend
GraphNodeWorkOrder missing profile smoke:
  ValueError Agent GraphNodeWorkOrder requires explicit agent_profile_id
GraphNodeWorkOrder profile smoke:
  has_tool_scope False
  has_permission_scope False
  agent_profile_id project_network_file_reviewer_agent
Graph node message visibility smoke:
  tool_scope False
  tool_contract False
  permission_contract False
  runtime_controls False
  agent_runtime_profile True
Compiled contract agent config smoke:
  {'agent_id': 'agent:reviewer', 'agent_profile_id': 'project_network_file_reviewer_agent'}
  {'agent_id': 'agent:node', 'agent_profile_id': 'node_profile'}
```

结论：通过。图节点现在显式承接 agent 配置，节点契约只对接职责/输入/输出/边界；工具授权回到成熟单 agent runtime 的 profile -> authorization -> visible tools 主链路。

### Stage F11：普通 TaskWorkEnvironment episode 执行桥接

目标：

```text
普通任务环境的 episode 执行进入统一单 agent harness。
TaskSystem 负责任务环境、episode、context package、lease、reducer 和查询。
Harness 负责单 agent runtime assembly / execution loop。
API 只负责协调调用，不组装或执行模型循环。
```

权威链检查：

- 符合：`backend/api/task_system.py` 只新增 `POST /task-environments/{environment_id}/episodes/{episode_id}/run` 协调入口，实际执行权交给 `HarnessRuntimeFacade.execute_task_environment_episode()`。
- 符合：`TaskWorkEnvironmentService` 仍是 episode lease acquire/release 权威；Harness 只申请和释放租约，不直接改写 lease 存储。
- 符合：`TaskReducer` 是 `EpisodeResult`、`WorkProduct`、`TaskEvent` 和任务环境 snapshot 的归并权威。
- 符合：任务环境 context package 只提供职责、范围、资源、验收和输出边界；工具能力仍来自 `AgentRuntimeProfile -> runtime assembly -> visible tools`，任务环境不授予工具。
- 符合：未解析到 agent profile 时不进入模型循环，直接记录为 blocked episode result；这是真实阻塞归档，不是伪执行结果。

逻辑检查：

- `backend/harness/entrypoint/runtime_facade.py`
  - 新增 `execute_task_environment_episode()`；
  - 从 TaskSystem 读取 `TaskWorkEnvironment`、`AgentExecutionEpisode`、`TaskContextPackage`；
  - 解析 episode 绑定的 `agent_profile_id`；
  - 正常路径创建/复用 session、提交 task episode 用户消息、申请 lease、装配 runtime、执行 `_run_single_agent_turn()`、投影 executor result；
  - 失败路径用 `_task_episode_executor_blocked_result()` / `_task_episode_exception_executor_result()` 形成可归并结果；
  - 统一调用 `_record_task_episode_execution_result()` 交给 `TaskReducer`。
- `backend/api/task_system.py`
  - 新增 `TaskEnvironmentEpisodeRunRequest`；
  - 新增 episode run route，保留 API coordination 边界。
- `backend/task_system/reducer.py`
  - 改为直接依赖 `work_environments.models` / `repository` 子模块，避免 reducer 加载 view 层。
- `backend/task_system/work_environments/__init__.py`
  - 包入口降为轻量模型/仓库导出；
  - `TaskWorkEnvironmentService` / `TaskEnvironmentViewService` 改为惰性导出，防止 record 层初始化时加载 view/graph service。
- `backend/task_system/work_environments/view_service.py`
  - 直接依赖 `graph_bindings.repository`，不通过 graph binding 包入口加载 service/reducer。
- `backend/task_system/graph_bindings/__init__.py`
  - `GraphNodeTaskBindingService` / result projection 改为惰性导出，避免轻量 repository/view 场景提前加载 reducer。

验证：

```text
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/api/task_system.py backend/task_system/reducer.py
python -m compileall backend/task_system/reducer.py backend/task_system/work_environments/__init__.py backend/task_system/work_environments/view_service.py backend/task_system/graph_bindings/__init__.py backend/harness/entrypoint/runtime_facade.py backend/api/task_system.py
python -m compileall backend
ordinary task episode missing-profile smoke:
  status blocked ok False
  executor_status blocked
  reduction_status blocked
  env_status blocked
  env_step episode_blocked
  episode_status interrupted
  result_count 1
  authority harness.task_environment_episode_bridge
rg -n "execute_task_run_callback|task_run_executor|task_environment_episode_bridge|TaskReducer|from task_system\\.work_environments import|from task_system\\.graph_bindings import" backend
  runtime source hits: task_environment_episode_bridge / TaskReducer / intentional lazy package imports
  old task_run_executor hits: tests and legacy docs; no new task episode bridge dependency on old executor
```

结论：通过。普通 TaskWorkEnvironment episode 已经能通过 Harness 单 agent runtime 权威桥接，并把 terminal result 交回 TaskSystem reducer。导入层也收敛为轻量包入口 + 显式服务依赖，避免 record/view/graph binding 互相提前初始化。

### Stage F12：节点执行投影从旧 TaskRun 收敛为 TaskExecution / Episode

目标：

```text
Graph node executor 不再把单节点 episode 包装成旧 TaskRun。
节点执行投影使用 task_execution / node_executor_execution_id。
GraphRun 根运行的 task_run_id 暂不在本切片迁移；本阶段只收敛节点执行者投影。
```

权威链检查：

- 符合：`GraphNodeWorkOrderExecutor` 仍由 GraphSystem 调度 work order，但节点执行者身份投影改为 `task_execution`，不再暴露 `node_executor_task_run`。
- 符合：Harness graph node bridge 返回 `task_execution`，其中包含 `execution_id`、`episode_id`、`task_environment_id`、`session_id`、`task_ref`、status 和 diagnostics。
- 符合：写作图确定性 handler 也输出 `task_execution`，避免系统型节点继续伪装成旧 TaskRun。
- 符合：Runner origin 校验只检查 `task_execution` 的 graph_run / work_order 来源，不再向 `state_index.get_task_run()` 回查节点执行者。
- 符合：monitor / breakpoint / runtime object summary 读取 `node_executor_execution_id`，不再读取 `node_executor_task_run_id`。
- 符合：TaskRun 清理/归档链不再把节点 execution id 当成 task_run id 处理。
- 符合：删除 `AgentRuntimeServices.execute_task_run_callback` 和未使用的 `get_graph_config_callback` 槽位，服务表不再保留旧执行权威暗门。

逻辑检查：

- `backend/harness/entrypoint/runtime_facade.py`
  - `_graph_node_executor_result_from_events()` / `_graph_node_executor_blocked_result()` 输出 `task_execution`；
  - 不再向 graph node executor result 写 `"task_run"`。
- `backend/graph_system/work_order_executor.py`
  - `GraphWorkOrderExecution.task_run` 改为 `task_execution`；
  - agent / deterministic executor result 均读取 `executor_result["task_execution"]`；
  - `NodeResultEnvelope.outputs` 写 `node_executor_execution_id`；
  - event payload 写 `node_executor_task_execution`。
- `backend/graph_system/facade.py`
  - work order execution API 返回 `node_executor_task_execution`；
  - active node runtime view 由事件中的 `task_execution` 投影，不再查节点 TaskRun monitor。
- `backend/graph_system/runner.py`
  - `_validate_executor_origin()` 改为校验 task execution origin；
  - runner event public view 写 `node_executor_task_execution` / `node_executor_execution_id`。
- `backend/task_system/writing_graphs/work_order_handlers.py`
  - deterministic progress receipt router 输出 `task_execution`。
- `backend/graph_system/runtime_objects.py`、`backend/graph_system/context_materializer.py`、`backend/health_system/graph_breakpoint_supervisor.py`、`backend/harness/runtime/run_monitor/projector.py`
  - 消费端切到 `node_executor_execution_id` / `node_executor_task_execution`。
- `backend/graph_system/lifecycle_manager.py`、`backend/runtime/shared/runtime_object_store.py`、`backend/runtime/retention_archiver.py`
  - 清理旧 TaskRun 时不再从节点执行输出读取 execution id。

验证：

```text
python -m compileall backend/harness/runtime/services.py backend/harness/entrypoint/runtime_facade.py backend/graph_system/work_order_executor.py backend/graph_system/facade.py backend/graph_system/runner.py backend/task_system/writing_graphs/work_order_handlers.py
python -m compileall backend/graph_system/runtime_objects.py backend/graph_system/context_materializer.py backend/graph_system/lifecycle_manager.py backend/runtime/shared/runtime_object_store.py backend/runtime/retention_archiver.py backend/health_system/graph_breakpoint_supervisor.py backend/harness/runtime/run_monitor/projector.py
python -m compileall backend
GraphNodeWorkOrderExecutor task_execution smoke:
  status completed
  task_execution_id episode:node-1
  output_execution_id episode:node-1
  old_output_key False
  event_has_task_execution True
  event_old_key False
facade/runner projection smoke:
  view_count 1
  view_execution_id episode:node-1
  view_has_task_execution True
  view_old_key False
  runner_origin ok
fixed backend runtime smoke:
  restarted project backend on 127.0.0.1:8003
  GET /health -> 200 {"status":"ok"}
  GET /openapi.json -> 200
  route_present /api/task-environments/{environment_id}/episodes/{episode_id}/run -> True
rg -n "node_executor_task_run|execute_task_run_callback|get_graph_config_callback|_executor_task_run_payload|_task_run_event_public_view|execution\\.task_run" backend --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
  remaining hits: runtime.memory.state_index active_executor_task_run helper name only; no node_executor_task_run key and no removed callback slot in runtime source.
```

结论：通过。节点执行者投影已经从旧 TaskRun 收敛为 TaskExecution / Episode 语义；GraphSystem 仍保留根运行的 task_run_id，本阶段没有扩大迁移范围。

### Stage F13：删除图节点 TaskRun 状态索引残留

目标：

```text
节点执行者已经由 TaskExecution / Episode 投影承载。
RuntimeStateIndex 不再维护 graph-node TaskRun 二级索引。
Graph lifecycle 清理不再探测旧 list_graph_node_task_runs API。
GraphRun 根运行 task_run_id 暂不迁移，留给独立阶段处理。
```

权威链检查：

- 符合：`RuntimeStateIndex` 继续作为普通 TaskRun / active executor TaskRun 的记录与索引层，但不再识别或分类 graph-node assigned TaskRun。
- 符合：graph node 执行结果的权威已经转移到 `task_execution`、`node_executor_execution_id`、`task_system.graph_node_task_binding_service`，状态索引层不再维护旧节点执行者身份。
- 符合：`GraphTaskLifecycleManager` 清理范围只收集根 TaskRun 和仍带有 graph_run_id 诊断的历史 TaskRun，不再通过旧节点 TaskRun 索引读取节点执行者。
- 符合：删除 `_graph_node_task_identity()`，避免 runtime state index 继续保留旧 graph-node TaskRun 识别逻辑。
- 边界：本阶段没有迁移 `GraphRun.task_run_id`。根图运行仍属于后续更大的 graph run / task environment 收敛阶段。

逻辑检查：

- `backend/runtime/memory/state_index.py`
  - 删除 `get_graph_node_task_run()` / `list_graph_node_task_runs()`；
  - 删除 `_sync_graph_node_task_run_id()` 和 upsert 写入调用；
  - 删除 `graph_node_task_runs_by_graph_run` / `graph_node_task_run_by_work_order` bucket 注册和空快照字段；
  - 删除 prune 时对 graph-node TaskRun 索引的清理分支；
  - 删除 `_graph_node_task_identity()`。
- `backend/graph_system/lifecycle_manager.py`
  - `_collect_task_run_ids()` 不再探测 `state_index.list_graph_node_task_runs`；
  - 不再从 node result outputs 中读取 `node_executor_task_run_id`；
  - 参数收敛为 `graph_run_id` + `root_task_run_id` 两个事实。

验证：

```text
python -m compileall backend/runtime/memory/state_index.py backend/graph_system/lifecycle_manager.py
rg -n "get_graph_node_task_run|list_graph_node_task_runs|_sync_graph_node_task_run_id|graph_node_task_run_by_work_order|graph_node_task_runs_by_graph_run|_graph_node_task_identity|node_executor_task_run_id" backend/runtime/memory/state_index.py backend/graph_system/lifecycle_manager.py backend --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
  no hits
python -m compileall backend
  passed; still prints the known harmless backend\.pytest_cache listing warning
```

结论：通过。图节点执行者的旧 TaskRun 索引权威已经移除，节点执行身份只保留在 TaskExecution / Episode / graph binding 投影链路中。后续如果要继续收敛，应单独规划根 `GraphRun.task_run_id` 与 graph run lifecycle 的迁移。

### Stage F14：work order executor 内部 payload 语义收敛

目标：

```text
Graph node executor 结果已经使用 task_execution。
work_order_executor 内部不再把节点执行者 payload 命名为 task_run_payload。
memory candidate 扩展链路同步改为 task_execution_payload。
保留 work_order.task_run_id 作为当前根 GraphRun TaskRun 边界，不在本阶段迁移。
```

权威链检查：

- 符合：节点执行者身份仍由 `task_execution` / `node_executor_execution_id` 承载，helper 参数不再误导为旧 TaskRun。
- 符合：artifact / memory 服务仍接收 `work_order.task_run_id` 作为当前 graph root 运行边界；节点执行 id 只作为 `node_run_id` / `node_executor_execution_id`。
- 符合：`memory_candidate_registry` 是 graph 内部扩展契约，可以与 work order executor 同步升级为 `task_execution_payload`，不保留旧参数名兼容壳。
- 边界：没有修改 `NodeResultEnvelope.task_run_id`、`GraphRun.task_run_id` 或事件日志根作用域。

逻辑检查：

- `backend/graph_system/work_order_executor.py`
  - `_artifact_refs_from_executor_result()`、`_model_output_payload()`、`_structured_agent_outputs()`、`_node_result_error()` 等私有 helper 参数改为 `task_execution_payload`；
  - `_artifact_materialization_receipts()` 和 `_formal_memory_receipts()` 中节点执行 id 改名为 `node_executor_execution_id`；
  - `_memory_candidates_from_task_run()` 改为 `_memory_candidates_from_task_execution()`；
  - `_runtime_scope()` 保留根 `"task_run_id": work_order.task_run_id`，避免把 graph root 与节点执行混淆。
- `backend/graph_system/memory_candidate_registry.py`
  - `augment_candidate_source_payload()` 的扩展参数改为 `task_execution_payload`。
- `backend/task_system/writing_graphs/memory_candidate_handlers.py`
  - 写作图 memory candidate handler 同步接收 `task_execution_payload`。

验证：

```text
rg -n "task_run_payload|_memory_candidates_from_task_run" backend/graph_system/work_order_executor.py backend/graph_system/memory_candidate_registry.py backend/task_system/writing_graphs/memory_candidate_handlers.py
  no hits
python -m compileall backend/graph_system/work_order_executor.py backend/graph_system/memory_candidate_registry.py backend/task_system/writing_graphs/memory_candidate_handlers.py
python -m compileall backend
  passed; still prints the known harmless backend\.pytest_cache listing warning
```

结论：通过。节点执行 payload 的内部命名已经与 TaskExecution / Episode 语义对齐，当前剩余的大迁移点仍是根 `GraphRun.task_run_id` 与旧恢复/当前工作控制入口。

### Stage F15：删除旧 TaskRun recovery resume 动作入口

目标：

```text
保留 continuation selector 提供的只读近期工作事实。
删除旧 TaskRun/task_executor 的 resume_task_recovery 动作、receipt、boundary 和 entrypoint callback。
模型 action surface 不再声明或解析 task_recovery_resume。
后续恢复必须走 TaskWorkEnvironment / Episode 控制与调度链路。
```

权威链检查：

- 符合：`Harness single-agent turn` 不再把旧 `resume_task_recovery` 当作可执行动作。
- 符合：`runtime control schema`、`tool_call_contract`、`turn_operating_contract` 和 `compiler` 不再向模型暴露旧恢复动作。
- 符合：只读 `ContinuationRecord` / `select_session_continuation()` 仍可作为历史上下文投影；它不再附带可执行 recovery boundary。
- 符合：删除 `harness.continuation.recovery_boundary` 和 `harness.recovery_receipt`，避免旧 TaskRun 恢复 receipt 继续伪装成控制权威。
- 符合：public stream 与 prompt guidance 中的旧恢复字段/命名已收敛为普通 boundary observation。

逻辑检查：

- 删除文件：
  - `backend/harness/continuation/recovery_boundary.py`
  - `backend/harness/recovery_receipt.py`
- `backend/harness/entrypoint/runtime_facade.py`
  - 移除 `apply_task_recovery_resume` callback；
  - 删除旧 `_run_task_recovery_resume_*` 和 `_run_recovery_boundary_status_response()` 分支；
  - `_run_single_agent_turn()` 不再接收 `continuation_record` 作为可执行恢复输入。
- `backend/harness/loop/single_agent_turn.py`
  - 移除 `ApplyTaskRecoveryResume`、动作处理分支、可见字段、修复文案和 public feedback 识别。
- `backend/harness/loop/model_action_protocol.py`
  - `ModelActionType` 不再包含 `resume_task_recovery`；
  - `ModelActionRequest` 不再携带 `task_recovery_resume`。
- `backend/harness/runtime/control_action_schema.py`、`turn_operating_contract.py`、`tool_call_contract.py`、`context_contract/inspection_payload.py`、`compiler.py`
  - 删除旧控制动作声明、schema、provider control tool name 和控制脊线。
- `backend/runtime/output_stream/public_stream_compiler.py`
  - public model action projection 不再包含 `task_recovery_resume`。
- `backend/prompt_library/environment_guidance_selection.py`
  - `_observations_include_recovery_boundary()` 改名为 `_observations_include_boundary_observation()`；
  - 保留失败/权限/能力边界观察触发环境能力提示的行为。
- `backend/health_system/evidence_extractor.py`
  - `coordination_recovery_boundary` 事件类型收敛为 `coordination_boundary`。
- `backend/harness/continuation/record.py`
  - 删除无人消费的 `resume_scheduler` 默认旧调度字段。

验证：

```text
rg -n "resume_task_recovery|task_recovery_resume|recovery_boundary|recovery_receipt|legacy_task_recovery_removed|conversation_task_recovery_resume|coordination_recovery_boundary" backend --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
  no hits
rg -n "build_recovery_boundary_input|decide_recovery_boundary|recovery_boundary_receipt_from_decision|RecoveryBoundary|task_recovery_resume|resume_task_recovery|recovery_receipt" backend --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
  no hits
python -m compileall backend/harness/continuation backend/harness/entrypoint/runtime_facade.py backend/harness/loop/single_agent_turn.py backend/harness/loop/model_action_protocol.py backend/harness/runtime/control_action_schema.py backend/harness/runtime/turn_operating_contract.py backend/harness/runtime/tool_call_contract.py backend/harness/runtime/context_contract/inspection_payload.py backend/harness/runtime/compiler.py backend/runtime/output_stream/public_stream_compiler.py backend/prompt_library/environment_guidance_selection.py backend/health_system/evidence_extractor.py
python -m compileall backend
  passed; still prints the known harmless backend\.pytest_cache listing warning
```

结论：通过。旧 TaskRun recovery resume 动作入口已从运行时 action surface、协议解析、entrypoint callback、receipt/boundary 和 public projection 中删除。恢复能力后续应只通过 TaskWorkEnvironment / Episode / lease / checkpoint 链路重新建立。

### Stage F16：移除 active_work_control 的旧执行器阻断 callback

目标：

```text
active_work_control 作为未来 TaskWorkEnvironment 控制动作保留在通用动作体系中。
当前 single-turn entrypoint 不再挂旧 TaskRun/task_executor 阻断 callback。
未挂载控制器时，由 action availability / executor_missing 通用路径处理。
后续要启用 active_work_control，必须先让 active_work_context 携带 task_environment_id，再接 TaskWorkEnvironment control signal。
```

权威链检查：

- 符合：`_active_work_context_from_active_turn()` 当前返回 `None`，普通 turn 不会开放 active_work_control 给模型。
- 符合：entrypoint 不再实现一个“永远返回旧执行器已移除”的伪控制器。
- 符合：TaskSystem 已有 `TaskControlSignal` 和 control signal API，但本阶段不在缺少 `task_environment_id` 的 active work 旧上下文上强接。
- 符合：runtime component 诊断改为正向的 `task_environment_episode_bridge=active`，不再以 legacy executor 为参照。
- 边界：`active_work_control` 类型、schema 和可用性 gate 保留；真正执行器留给 TaskWorkEnvironment 控制接线阶段。

逻辑检查：

- `backend/harness/entrypoint/runtime_facade.py`
  - `run_single_agent_turn()` 不再传入 `apply_active_work_control` legacy callback；
  - 删除 `_run_current_work_control_action_request()`；
  - 删除 `active_work_turn_decision_from_payload` / `active_work_control_denial_observation` import；
  - `runtime_components` 改为正向声明 `task_environment_episode_bridge`；
  - `request_task_run` 成功/失败提示改为 TaskWorkEnvironment 分配语义，不再描述旧 TaskRun 执行器。
- `backend/harness/runtime/control_action_schema.py`
  - `pause_for_user_steer` terminal policy 去掉旧 `task_executor` 表述。

验证：

```text
rg -n "legacy_task_executor|task_executor|旧 TaskRun/task_executor|旧任务执行器|旧 TaskRun 执行器|旧当前工作控制" backend/harness/entrypoint/runtime_facade.py backend/harness/runtime/control_action_schema.py backend/harness/loop backend/harness/runtime --glob "*.py" --glob "!backend/tests/**" --glob "!backend/scripts/**"
  no hits
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/harness/runtime/control_action_schema.py
python -m compileall backend
  passed; still prints the known harmless backend\.pytest_cache listing warning
```

结论：通过。当前工作控制不再通过旧执行器阻断 callback 伪实现；下一步若继续这条线，应先把 active work 从旧 task_run_id 坐标升级为 TaskWorkEnvironment 坐标，再把 action 接到 `TaskWorkEnvironmentService.request_control_signal()`。

### Stage F17：active work 控制坐标迁入 TaskWorkEnvironment

目标：

```text
普通 turn 的 current work 候选不再来自旧 TaskRun。
Harness 通过 session foreground SessionTaskBinding 解析 TaskWorkEnvironment 当前工作。
current_work_boundary receipt 以 task_environment_ref 作为可控工作锚点。
active_work_control 写入 TaskControlSignal，并复用共享 graph control bridge。
GraphRun 根 task_run_id 仍不在本阶段迁移。
```

权威链检查：

- 符合：`TaskSystem` 持有 `TaskWorkEnvironment`、`SessionTaskBinding`、`TaskControlSignal` 和事件账本；Harness 只解析当前 session 的 foreground binding 并投影给模型。
- 符合：`Harness current_work_boundary` 只判定当前请求是否允许控制任务环境，不再要求 `task_run_ref`。
- 符合：`single_agent_turn` 仍是唯一单 agent 执行 loop；`active_work_control` 通过 callback 写入 TaskControlSignal，不新建旧 executor。
- 符合：Graph 控制桥抽到 `task_system.work_environments.control_signal_bridge`，API 与 Harness 复用同一个桥，不复制图控制决策。
- 边界：没有迁移 `GraphRun.task_run_id`、chat interrupt 的 root TaskRun 兼容投影或 graph run lifecycle。

逻辑检查：

- `backend/task_system/work_environments/repository.py`
  - 增加 `get_session_binding()`、`list_session_bindings()`、`get_foreground_session_binding()`；
  - session binding 查询只观察 foreground/controller/active 绑定，不做任务控制决策。
- `backend/harness/loop/active_work.py`
  - `ActiveWorkContext` 增加 `task_environment_id`、`task_instance_id`、`session_binding_id`、`environment_kind`、`control_capabilities`；
  - 默认 authority 改为 `harness.runtime.task_environment_active_work_context`；
  - model-visible payload 继续隐藏旧 `task_run_id`。
- `backend/harness/entrypoint/current_work_boundary.py` 与 `backend/harness/current_work_receipt.py`
  - current work 可控 authority 改为 TaskWorkEnvironment active work context；
  - receipt 可用性要求 `task_environment_ref`，不再要求 `task_run_ref`；
  - terminal 判断覆盖 `completed/failed/aborted/archived` 任务环境状态。
- `backend/harness/entrypoint/runtime_facade.py`
  - `_active_work_context_from_active_turn()` 改为从 session foreground binding 解析 TaskWorkEnvironment；
  - active turn check 不再要求 `bound_task_run_id`；
  - `_apply_task_environment_active_work_control()` 将 pause/stop/append/status answer 映射为任务环境控制；
  - `append_instruction_to_active_work` 写入 `instruction_appended` pending signal；
  - status answer 和控制确认由 OutputCommitAuthority 统一提交。
- `backend/task_system/work_environments/control_signal_bridge.py`
  - 新增共享 graph control bridge；
  - API `POST /task-environments/{environment_id}/control-signals` 改为复用该 bridge。
- `backend/harness/loop/single_agent_turn.py`
  - active work 事件 refs 优先挂 `task_environment_id`；
  - 旧 `task_run_id` 仅在存在时作为附带历史字段。
- `backend/memory_system/runtime_context_provider.py`
  - memory main context 的 active work 摘要改为任务环境坐标。

验证：

```text
python -m compileall backend/task_system/work_environments backend/harness/loop/active_work.py backend/harness/entrypoint/current_work_boundary.py backend/harness/current_work_receipt.py backend/harness/entrypoint/runtime_facade.py backend/harness/loop/single_agent_turn.py backend/harness/runtime/compiler.py backend/memory_system/runtime_context_provider.py backend/api/task_system.py
python -m compileall backend
  passed; still prints the known harmless backend\.pytest_cache listing warning
rg -n -F "current_work_receipt_task_run_ref_missing" backend/harness backend/api backend/memory_system --glob "*.py"
  no hits
rg -n -F "active_work_context_not_active_turn_bound" backend/harness backend/api backend/memory_system --glob "*.py"
  no hits
rg -n -F "harness.runtime.active_turn_context" backend/harness backend/api backend/memory_system --glob "*.py"
  no hits
rg -n -F "no_active_turn_bound_current_work" backend/harness backend/api backend/memory_system --glob "*.py"
  no hits
isolated smoke:
  ctx_present True
  decision current_work_control_required taskenv:...
  available True active_work_control_available taskenv:...
  signal_kind instruction_appended
  signal_status pending
callback smoke:
  event_types ['active_work_control_requested', 'done']
  pending_signals [('instruction_appended', 'pending')]
  done_reason active_work_control_signal_requested
fixed backend runtime smoke:
  restarted project backend on 127.0.0.1:8003
  GET /health -> 200 {"status":"ok"}
  GET /openapi.json -> 200
  route_present /api/task-environments/{environment_id}/control-signals -> True
  route_present /api/task-environments/{environment_id}/episodes/{episode_id}/run -> True
```

结论：通过。active work/current work 控制已经从旧 TaskRun 坐标迁到 TaskWorkEnvironment 坐标；模型只有在当前请求 receipt 暴露 `active_work_control=true` 时才能写入任务环境控制信号。后续阶段可以继续收敛 chat interrupt/root GraphRun task_run 边界，但需要单独规划。

### Stage F18：Current Work Receipt 去旧 TaskRun 控制锚点与旧测试残留清理

目标：

```text
F17 已经把 current work 控制迁入 TaskWorkEnvironment。
本阶段继续收口：CurrentWorkBoundaryDecision / CurrentWorkBoundaryReceipt 不再携带 task_run_id / task_run_ref。
模型可见 active_work.work_ref 只从 task_environment_ref / task_environment_id 得到，不再兜底旧 TaskRun。
删除已经不存在的旧 task_executor / recovery_boundary 测试和现场探针，避免旧链路被测试目录重新定义为合法结构。
GraphRun 根 task_run_id 仍不在本阶段迁移。
```

权威链检查：

- 符合：`TaskWorkEnvironment` 是当前工作控制锚点，receipt 的可用性只要求 `task_environment_ref` 和 active turn ref。
- 符合：`Harness` 只把 current work boundary 投影给模型，不再通过 receipt 暴露旧 TaskRun 控制坐标。
- 符合：旧 `task_executor.py`、`task_executor_controller.py`、`task_run_execution_control.py` 和 `recovery_boundary` 已经不是运行权威，相关测试/探针不应继续保留。
- 边界：未迁移 `ActiveTurnRecord.bound_task_run_id`、chat interrupt 的 root TaskRun 投影、GraphRun 根运行作用域和 runtime cell 的 task_run 事件作用域；这些需要独立阶段处理。

逻辑检查：

- `backend/harness/entrypoint/current_work_boundary.py`
  - `CurrentWorkBoundaryDecision` 删除 `task_run_id`；
  - `CurrentWorkBoundaryReceipt` 删除 `task_run_ref`；
  - receipt 的 `active_work_ref` 只保留 `active_work_id`、`task_environment_id`、`actual_active_turn_id`。
- `backend/harness/current_work_receipt.py`
  - `CurrentWorkControlAvailability` 删除 `task_run_ref`；
  - availability 不再从 `active_work_ref.task_run_id` 读取控制锚点。
- `backend/harness/runtime/compiler.py`
  - current work 模型可见 `work_ref` 优先使用 `task_environment_ref / task_environment_id`；
  - 不再兜底 `task_run_ref / task_run_id`。
- 清理旧测试/探针：
  - 删除旧 task executor / task executor controller / task run execution control 相关测试文件；
  - 删除旧 `continuation_recovery_boundary_regression.py` 和旧 current work TaskRun boundary 测试；
  - 删除旧 live prompt cache task probe 脚本。
- `backend/tests/action_schema_manifest_regression.py`
  - canonical active work fixture 改为 TaskWorkEnvironment 坐标，防止旧 TaskRun receipt 被误认为可打开 `active_work_control`。

验证：

```text
rg -n "task_run_ref|task_run_id" backend/harness/entrypoint/current_work_boundary.py backend/harness/current_work_receipt.py
  no hits
rg -n "harness\.loop\.task_executor|harness\.loop\.task_run_execution_control|harness\.loop\.task_executor_controller|TaskExecutorController|TaskRunExecutorInterrupted|ExecutorControlSignal|request_executor_stop|_latest_requested_control_signal" backend --glob "*.py"
  no hits
rg -n "recovery_boundary|recovery_receipt|resume_task_recovery|task_recovery_resume|current_work_receipt_task_run|decision\.task_run_id|receipt\.task_run_ref" backend/tests backend/harness backend/api backend/runtime backend/memory_system --glob "*.py"
  no hits
python -m compileall backend
  passed; still prints the known harmless backend\.pytest_cache listing warning
git diff --check
  passed; only line-ending warnings for existing touched files
fixed backend runtime smoke:
  127.0.0.1:8003 listener pid=39192
  GET /health -> {"status":"ok"}
  route_present /api/task-environments/{environment_id}/control-signals -> True
  route_present /api/task-environments/{environment_id}/episodes/{episode_id}/run -> True
```

结论：通过。current work 控制 receipt 已经严格收敛为 TaskWorkEnvironment 坐标，旧 executor/recovery 测试残留已经移除。下一阶段应单独审查 `ActiveTurnRecord.bound_task_run_id`、chat interrupt root TaskRun、run monitor projection 和 runtime cell task_run 作用域，决定哪些属于 GraphRun 根作用域暂留，哪些应迁入 TaskWorkEnvironment / Episode 坐标。

### Stage F19：Chat Interrupt 与 ActiveTurn 去旧 TaskRun 控制投影

目标：

```text
聊天运行中断只由 runtime cell cancellation、active turn 状态和 context recovery fact 组成。
API 不再接收 expected_task_run_id / cascade_subagents。
API 不再返回 task_control / subagent_controls，也不再扫描旧 subagent TaskRun 做伪级联。
ActiveTurnRegistry 不再通过 bound_task_run_id 查询 TaskRun 状态来决定 active turn 是否存在。
Run monitor 不再暴露旧 pause_task / stop_task / close_runtime 假按钮。
```

权威链检查：

- 符合：`ActiveTurnRegistry` 只拥有当前 turn 句柄、steerable 状态和 runtime instance 所有权，不再读取 TaskRun 生命周期。
- 符合：`api.chat.runtime_interruption` 只取消 runtime run cells，并记录 interruption fact；不再返回“旧 TaskRun 控制已移除”的伪控制结果。
- 符合：run monitor action surface 删除无执行权威的旧任务 pause/stop/close 动作，只保留清理、恢复显示、删除记录和图运行删除预览等实际管理动作。
- 边界：`bound_task_run_id` 字段本身仍存在，因为 queued input steer、部分 runtime cell / task_run 作用域、GraphRun 根运行仍在使用旧 task_run 坐标；这些属于后续独立迁移。

逻辑检查：

- `backend/api/chat.py`
  - `ChatRunInterruptRequest` 删除 `expected_task_run_id` 和 `cascade_subagents`；
  - interrupt handler 不再解析 root TaskRun、不再生成 `task_control`、不再调用 subagent TaskRun cascade；
  - `_publish_chat_interruption_fact_signal()` 不再携带 `task_run_id`、`task_control` 或 `subagent_controls`，事件写入 chat run 的 `event_log_id`。
- `backend/harness/runtime/active_turn.py`
  - 删除 `resolve_current()` 中对 `state_index.get_task_run(bound_task_run_id)` 的读取；
  - active turn 不再因为 bound TaskRun missing/terminal 被注册表自行关闭；
  - 删除 `require_bound_task` 参数和 `active_turn_not_bound_to_task` 分支。
- `backend/harness/runtime/run_monitor/projector.py`
  - active turn monitor 的 interruptible 由 `stream_run_id / turn_run_id / turn_id` 决定；
  - resumable 不再由旧 `bound_task_run_id` 打开。
- `backend/harness/runtime/run_monitor/actions.py`
  - 删除 `pause_task`、`stop_task`、`close_runtime` 的旧禁用分支和伪执行结果；
  - 相关动作落入 `unsupported_action`，避免 UI/调用方误以为存在旧 TaskRun 控制面。

验证：

```text
rg -n "legacy TaskRun pause/stop|legacy_task_run_control_removed|subagent legacy TaskRun|subagent_cascade_removed|cascade_subagents|_validated_interrupt_cascade|_control_fact\\(" backend --glob "*.py"
  no old chat/monitor control hits; remaining task_control matches are TaskWorkEnvironment control-signal schema / generic output allowlists
rg -n "require_bound_task|active_turn_not_bound_to_task|bound_task_run_missing|bound_task_run_terminal" backend --glob "*.py"
  no hits
python -m compileall backend/api/chat.py backend/harness/runtime/active_turn.py backend/harness/runtime/run_monitor/actions.py backend/harness/runtime/run_monitor/projector.py backend/harness/entrypoint/runtime_facade.py
python -m compileall backend
  passed; still prints the known harmless backend\\.pytest_cache listing warning
git diff --check
  passed; only line-ending warnings for existing touched files
fixed backend runtime smoke:
  restarted backend on 127.0.0.1:8003, pid=35172
  GET /health -> {"status":"ok"}
  OpenAPI ChatRunInterruptRequest properties -> mode, reason, expected_active_turn_id
  route_present /api/chat/runs/{stream_run_id}/interrupt -> True
  route_present /api/task-environments/{environment_id}/control-signals -> True
  route_present /api/task-environments/{environment_id}/episodes/{episode_id}/run -> True
```

结论：通过。chat interruption 和 active turn 当前性判断已经脱离旧 TaskRun 控制投影。下一阶段应集中处理 queued input steer 与 `bound_task_run_id` 的剩余匹配语义，或者单独规划 GraphRun 根 `task_run_id` 迁移，不能混做。

### Stage F20：Queued User Input Steer 去旧 TaskRun 坐标

目标：

```text
queued user input 只按 active turn 句柄接入正在运行的单 agent turn。
steer 队列项不再保存、匹配或回传旧 task_run_id。
需要任务语义坐标时，只附带 session foreground TaskWorkEnvironment 的 task_environment_id。
队列 steer 不再 mirror 到旧 active TaskRun steering 通道。
GraphRun 根 task_run_id、runtime event/task bridge、task record lifecycle 仍不在本阶段迁移。
```

权威链检查：

- 符合：`runtime.shared.queued_user_input_dispatcher` 只观察 active turn 是否存在、是否 steerable、当前 turn id，不再读取 `bound_task_run_id`。
- 符合：`QueuedUserInputStore` 的队列记录保存 `task_environment_id`，只用于语义坐标和事件 refs；claim 只匹配 active turn id，不再用旧 TaskRun 作为准入门槛。
- 符合：`api.chat` 是会话入口层，因此只负责把 runtime admission 与 foreground `TaskWorkEnvironment` binding 合并成队列 admission；不让 runtime shared 层反向依赖 task environment repository。
- 符合：`harness.loop.active_turn_steering` 只把用户 steer 投影为 turn message、turn memory 和 lifecycle event；删除旧 `create_active_task_steer()` mirror，避免队列 steer 被第二条 TaskRun 控制链重新执行。
- 边界：`HarnessRuntimeRequest.expected_task_run_id`、`task_steering.py`、GraphRun 根 `task_run_id`、public task bridge、runtime cell/task record 作用域仍然存在；这些是后续阶段的独立迁移对象，不能在 queued input 阶段混改。

逻辑检查：

- `backend/runtime/shared/queued_user_input_store.py`
  - `QueuedUserInput.task_run_id` 改为 `task_environment_id`；
  - `enqueue()`、`claim_for_active_turn()`、`retarget_for_dispatch()` 改为保存和回传任务环境坐标；
  - `_queued_input_from_payload()` 不再兼容读取旧 `task_run_id`，旧 payload 不会被静默升级成合法 steer 坐标。
- `backend/runtime/shared/queued_user_input_dispatcher.py`
  - `queued_input_admission_target()` 不再返回 `task_run_id`；
  - `validate_queued_steer()` 删除 `expected_task_run_mismatch`，只校验 active turn id 与 steerable 状态。
- `backend/api/chat.py`
  - 队列 admission 改为本地 `_queued_input_admission_target(runtime, session_id=...)`；
  - steer admission 附带 foreground `task_environment_id`；
  - enqueue / retarget / queued request 组装均不再传 `expected_task_run_id`。
- `backend/harness/loop/active_turn_steering.py`
  - 删除 queue steer mirror 到旧 active task 的逻辑；
  - lifecycle event、public event、model message 只携带 `task_environment_id`；
  - 删除旧任务来源判断 `_task_origin_kind()`，不再让 TaskRun origin 决定队列 steer 是否可进入当前 turn。

验证：

```text
rg -n -F "task_run_id" backend/runtime/shared/queued_user_input_store.py backend/runtime/shared/queued_user_input_dispatcher.py backend/harness/loop/active_turn_steering.py
  no hits
rg -n -F "task_run_id=str(admission" backend/api/chat.py
  no hits
rg -n -F "expected_task_run_mismatch" backend/tests backend/runtime/shared backend/harness/loop backend/api --glob "*.py"
  no hits
python -m compileall backend
  passed; still prints the known harmless backend\\.pytest_cache listing warning
git diff --check
  passed; only line-ending warnings for existing touched files
fixed backend runtime smoke:
  restarted backend on 127.0.0.1:8003, pid=31004
  GET /health -> {"status":"ok"}
  OpenAPI ChatRunInterruptRequest properties -> mode, reason, expected_active_turn_id
  route_present /api/chat/sessions/{session_id}/queued-inputs -> True
  route_present /api/task-environments/{environment_id}/control-signals -> True
  route_present /api/task-environments/{environment_id}/episodes/{episode_id}/run -> True
```

结论：通过。queued user input steer 已经从旧 TaskRun 坐标收敛为 active turn + TaskWorkEnvironment 语义坐标。下一阶段建议单独审查 `HarnessRuntimeRequest.expected_task_run_id` 和 `task_steering.py`：如果它们只是在维护旧 active TaskRun steer，就应迁入 TaskWorkEnvironment control signal 或删除；如果它们承载 GraphRun 根运行边界，则必须等 GraphRun 根作用域迁移阶段处理。

### Stage F21：删除旧 Active Task Steer 子系统与 expected_task_run_id 请求契约

目标：

```text
HarnessRuntimeRequest 不再暴露 expected_task_run_id。
TurnInputFacts 不再保存旧 TaskRun steer 准入坐标。
ActiveTurnRegistry 的 compare/interrupt 只比较 active turn id 和 steerable 状态。
删除无生产调用的 harness.loop.task_steering / user_submission / task_run_contract_revision 旧链路。
删除旧 active_task_steer 公共投影、timeline/monitor 识别和对应旧测试。
bound_task_run_id 暂不迁移，因为它仍属于 runtime cell backpressure、task record lifecycle 和 GraphRun/public task bridge 的现存作用域。
```

权威链检查：

- 符合：单 agent turn 的用户 steer 入口已经由 F20 的 queued input active-turn 通道承接；旧 `ActiveTaskSteer` 不再是合法执行权威。
- 符合：`ActiveTurnRegistry` 只维护 current turn 句柄，不再接受 expected TaskRun 坐标来决定当前 turn 是否可打断/更新。
- 符合：公共投影、session timeline、run monitor 不再把旧 `active_task_steer_*` 事件显示成仍可用能力。
- 符合：删除旧测试而不是改造成兼容壳，避免测试目录重新定义旧 steer 链路为合法行为。
- 边界：`ActiveTurnRecord.bound_task_run_id`、`complete_bound_task()`、`agent_run_supervisor` 的当前 turn task handoff、`TaskRecordLifecycleManager` 的 task record 删除清理仍保留；这些不是 expected steer 准入链，需要在 GraphRun/root task_run 作用域迁移阶段单独处理。

逻辑检查：

- `backend/harness/entrypoint/models.py`
  - 删除 `HarnessRuntimeRequest.expected_task_run_id`。
- `backend/harness/runtime/request_facts.py`
  - 删除 `TurnInputFacts.expected_task_run_id` 和 builder 参数。
- `backend/harness/entrypoint/runtime_facade.py`
  - `build_turn_input_facts()` 不再传 expected TaskRun；
  - current work boundary 的 active-turn check 不再传空 expected TaskRun。
- `backend/harness/runtime/active_turn.py`
  - `mark_interrupting()` 与 `compare_and_update_current_turn()` 删除 expected TaskRun 参数；
  - compare result 删除 `expected_task_run_id` / `actual_task_run_id` 字段；
  - `complete_bound_task()` 内部变量改为 `normalized_task_run_id`，避免混淆为请求期望坐标。
- 删除旧链路文件：
  - `backend/harness/loop/task_steering.py`
  - `backend/harness/loop/user_submission.py`
  - `backend/harness/loop/task_run_contract_revision.py`
  - `backend/tests/task_steering_protocol_regression.py`
- 清理旧事件/投影残留：
  - `backend/runtime/shared/events.py` 删除 `user_submission_recorded`、`active_task_steer_*`、`task_run_contract_revision_*`；
  - `backend/runtime/output_stream/public_stream_compiler.py` 与 `public_contract.py` 删除 `active_task_steer_accepted`；
  - `backend/harness/runtime/projection/projector.py` 删除 `active_task_steer_accepted` 状态投影；
  - `backend/harness/runtime/session_timeline.py` 与 `run_monitor/projector.py` 不再把旧 steer 事件作为最新交互 turn 信号；
  - 删除旧 public projection / session timeline 测试中的 active-task-steer 用例。

验证：

```text
rg -n "expected_task_run_id|actual_task_run_id|expected_task_run_mismatch" backend --glob "*.py"
  no hits
rg -n "harness\\.loop\\.task_steering|from \\.task_steering|import .*task_steering|create_active_task_steer|list_pending_task_steers|mark_task_steers|list_task_steers|ActiveTaskSteer" backend --glob "*.py"
  no hits
rg -n "active_task_steer|task_run_contract_revision|user_submission_recorded|build_user_submission|UserSubmission|task_steering" backend --glob "*.py"
  no hits
python -m compileall backend/harness/entrypoint/models.py backend/harness/runtime/request_facts.py backend/harness/entrypoint/runtime_facade.py backend/harness/loop/turn_to_task_context_handoff.py backend/harness/runtime/active_turn.py backend/api/chat.py
  passed
python -m compileall backend/harness backend/runtime/shared/events.py backend/runtime/output_stream/public_stream_compiler.py backend/runtime/output_stream/public_contract.py backend/tests/public_projection_contract_test.py backend/tests/session_runtime_timeline_contract_test.py
  passed
python -m compileall backend
  passed; still prints the known harmless backend\\.pytest_cache listing warning
git diff --check
  passed; only line-ending warnings for existing touched files
fixed backend runtime smoke:
  restarted backend on 127.0.0.1:8003, pid=7564
  GET /health -> {"status":"ok"}
  OpenAPI ChatRunInterruptRequest properties -> mode, reason, expected_active_turn_id
  OpenAPI mentions expected_task_run_id -> False
  OpenAPI mentions active_task_steer -> False
  route_present /api/chat/sessions/{session_id}/queued-inputs -> True
  route_present /api/task-environments/{environment_id}/control-signals -> True
  route_present /api/task-environments/{environment_id}/episodes/{episode_id}/run -> True
```

结论：通过。旧 active TaskRun steer 子系统已经从请求契约、运行时判断、生产代码、事件目录、公共投影和旧测试中移除。下一阶段应继续审查 `bound_task_run_id` 的真实用途，按 runtime cell / task record lifecycle / GraphRun root scope 分类，不应直接替换成 task_environment_id。

### Stage F22：清理 ActiveTurn 到 TaskRun 的隐式绑定关系

目标：

```text
ActiveTurn 只表示当前 turn 句柄，不再携带、绑定、完成或推断 TaskRun。
TaskRun 生命周期、GraphRun 根作用域、runtime cell scope 继续通过显式 task_run_id/graph_run_id 管理。
Chat task bridge 只能依赖显式 bridge_context，不再通过 active turn 反查 bound TaskRun。
Retention / task record deletion 不再用 TaskRun 反向关闭 active turn。
```

权威链检查：

- 符合：`ActiveTurnRegistry` 只拥有 current turn、turn run、stream run、steerable 和 owner instance；不再拥有 TaskRun 关系。
- 符合：`AgentRunSupervisor` 的 session primary backpressure 只看现存 runtime cell，不再给“当前 single_turn 隐式交接到某 TaskRun”开旁路。
- 符合：`api.chat` 的 task bridge terminal 判断只走 `ChatTaskBridgeContext` 这个显式桥，不再从 active turn 推断任务桥。
- 符合：TaskRun retention 和 task record lifecycle 只清理 TaskRun/runtime cell/cache，不再凭 TaskRun 关系更新 active turn。
- 边界：显式 `task_run_id` 仍属于 GraphRun/root task record/runtime cell/legacy public task bridge 的现存作用域；本阶段没有迁移 GraphRun 根任务记录。

逻辑检查：

- `backend/harness/runtime/active_turn.py`
  - 删除 `ActiveTurnRecord.bound_task_run_id`；
  - 删除 `bind_task_run()`；
  - 删除 `complete_bound_task()`；
  - `_record_from_payload()` 不再读取旧字段。
- `backend/api/chat.py`
  - 删除 `_active_turn_requires_task_bridge_terminal()`；
  - projection stream exception / missing terminal 只检查显式 `bridge_context`；
  - missing terminal 文案改为显式 task bridge terminal 缺失。
- `backend/harness/runtime/agent_run_supervisor.py`
  - 删除 `_is_current_turn_task_handoff()`；
  - primary session task backpressure 不再通过 active turn bound task 解除。
- `backend/harness/runtime/task_record_lifecycle.py`
  - 删除 task record deletion 中的 active turn complete 结果。
- `backend/harness/runtime/task_run_retention.py`
  - 删除 retention terminal update 中的 active turn complete；
  - 旧测试桩改为确认 active turn registry 不参与 TaskRun retention。
- `backend/harness/entrypoint/runtime_facade.py`
  - transient active turn release 不再检查 bound TaskRun 状态。
- `backend/harness/loop/single_agent_turn.py`
  - active work event refs 不再投影 `active_turn.bound_task_run_id`；
  - turn terminal cleanup 不再通过 bound TaskRun 阻止 active turn complete。
- `backend/harness/runtime/run_monitor/projector.py`
  - active turn monitor 不再读取 bound TaskRun；
  - active turn 的 monitor id 只来自 turn run / stream run / turn id。
- `backend/runtime/retention_archiver.py` 与 `backend/runtime/shared/runtime_object_store.py`
  - 删除历史对象索引中的 `bound_task_run_id` 识别键，避免旧字段继续被系统语义承认为合法关系。

验证：

```text
rg -n "bound_task_run_id|bind_task_run\\(|complete_bound_task\\(|_is_current_turn_task_handoff|_active_turn_requires_task_bridge_terminal|active_turn_task_missing_terminal" backend --glob "*.py"
  no hits
python -m compileall backend
  passed; still prints the known harmless backend\\.pytest_cache listing warning
git diff --check
  passed; only line-ending warnings for existing touched files
fixed backend runtime smoke:
  restarted backend on 127.0.0.1:8003, pid=18084
  GET /health -> {"status":"ok"}
  OpenAPI mentions bound_task_run_id -> False
  OpenAPI mentions complete_bound_task -> False
  route_present /api/chat/sessions/{session_id}/queued-inputs -> True
  route_present /api/task-environments/{environment_id}/control-signals -> True
  route_present /api/task-environments/{environment_id}/episodes/{episode_id}/run -> True
```

结论：通过。ActiveTurn 到 TaskRun 的隐式绑定关系已经从模型、注册表 API、chat bridge fallback、agent runtime backpressure、retention、task record deletion、monitor 投影和历史对象识别中移除。后续新架构推进应把控制关系显式落在 `TaskWorkEnvironment / Episode / Lease / GraphNodeTaskBinding`，而不是再把 TaskRun 挂回 active turn。

### Stage F23：将 TaskEnvironment / Graph 节点的执行预算接入 single-agent loop

目标：

```text
TaskSystem / GraphSystem 可以为一次 episode 或一个 graph node 决定执行预算。
Harness facade 只传递预算，不重新解释任务。
run_single_agent_turn 是唯一工具执行循环，负责在预算耗尽时阻止下一批工具执行，并要求 agent 按 respond / ask_user / block 收口。
```

权威链检查：

- 符合：`backend/api/task_system.py` 和 `backend/api/graph_system.py` 继续只接收 `max_steps` 请求参数。
- 符合：`GraphNodeWorkOrderExecutor` 继续把节点预算传给 harness graph work order bridge。
- 符合：`HarnessRuntimeFacade.execute_task_environment_episode()` 和 `_execute_graph_agent_work_order()` 只把 `max_steps` 传给 `_run_single_agent_turn()`，没有引入第二套图调度或任务解释。
- 符合：`run_single_agent_turn()` 在模型已经提出下一批工具动作、但预算已耗尽时，生成 `tool_budget_exhausted` runtime control signal；该工具请求不会进入 admission / batch plan / execution。
- 符合：预算耗尽后仍由 agent 自己写可发布收口，不由系统伪造任务结论。

逻辑检查：

- `backend/harness/loop/single_agent_turn.py`
  - 新增 `_normalize_single_turn_tool_iteration_limit()`；
  - 新增 `_tool_budget_exhausted_closeout_control_signal()`；
  - `run_single_agent_turn(..., max_tool_iterations=None)` 接收预算；
  - `single_agent_turn_started` 事件投影 `max_tool_iterations`；
  - 工具循环在 `tool_iteration >= max_tool_iterations` 且模型继续请求工具时，记录 `turn_runtime_control_signal_observed`，再进入 `agent_authored_closeout`。
- `backend/harness/entrypoint/runtime_facade.py`
  - `execute_task_environment_episode(max_steps=...)` 传入 `_run_single_agent_turn(max_steps=max_steps)`；
  - `_execute_graph_agent_work_order(max_steps=...)` 传入 `_run_single_agent_turn(max_steps=max_steps)`；
  - `_run_single_agent_turn()` 将 `max_steps` 映射为 loop 的 `max_tool_iterations`；
  - 删除 task/graph bridge 调用点残留的 `continuation_record=None`，避免旧恢复参数成为运行时 `TypeError`。
- `backend/harness/entrypoint/runtime_facade.py`
  - `_compact_graph_node_harness_event()` 增加 `turn_runtime_control_signal_observed` 摘要，保留 `signal_kind`、`runtime_control_state`、`used_tool_iterations`、`max_tool_iterations` 和 signal ref。

验证：

```text
rg -n "continuation_record=|max_tool_iterations|max_steps=max_steps|tool_budget_exhausted_closeout" backend/harness/entrypoint/runtime_facade.py backend/harness/loop/single_agent_turn.py
  no continuation_record= hits
  max_steps -> max_tool_iterations link present
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/harness/loop/single_agent_turn.py backend/api/task_system.py backend/graph_system/work_order_executor.py
  passed
git diff --check
  passed; only existing CRLF warnings
```

结论：通过。`max_steps` 不再是 API 层挂名字段；它现在是 TaskEnvironment episode / Graph node 调用 single-agent harness 时的真实工具轮次预算。普通 chat turn 未显式传入预算，不被这次任务环境预算改动影响。

### Stage F24：episode 执行返回刷新后的任务环境视图

目标：

```text
TaskEnvironment episode 执行完成后，调用方可以直接看到归并后的任务环境状态、episode result、work products、leases、events、recovery hint 和 control capabilities。
返回面不再迫使上层通过旧 active turn / TaskRun 隐式关系反查状态。
```

权威链检查：

- 符合：`TaskReducer` 仍是 episode result / work product / snapshot patch 的归并权威。
- 符合：`TaskEnvironmentViewService` 仍是任务环境查询投影权威。
- 符合：harness bridge 只在执行完成并释放 lease 后读取刷新视图，不在执行过程中改写 view 结构。

逻辑检查：

- `backend/harness/entrypoint/runtime_facade.py`
  - 引入 `TaskEnvironmentViewService`；
  - agent profile 缺失等 blocked 路径在记录 reduction 后返回 `task_environment_view`；
  - 正常执行路径在 `release_episode_lease()` 后返回 `task_environment_view`，确保调用方看到 lease 已释放后的状态。

验证：

```text
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/task_system/work_environments/view_service.py backend/api/task_system.py
  passed
rg -n "task_environment_view|TaskEnvironmentViewService" backend/harness/entrypoint/runtime_facade.py
  import and return payload present
git diff --check
  passed; only existing CRLF warnings
```

结论：通过。TaskEnvironment episode bridge 的返回面开始贴合持久任务环境定义：执行结果、归并结果和任务环境查询视图在同一响应里闭合。

运行复验：

```text
fixed backend restart:
  old listener: python run_uvicorn.py --host 127.0.0.1 --port 8003
  first restart attempt from repository root failed because run_uvicorn.py lives under backend/
  corrected restart from D:\AI应用\langchain-agent\backend, pid=14144
GET http://127.0.0.1:8003/health
  {"status":"ok"}
GET http://127.0.0.1:8003/openapi.json
  /api/task-environments/{environment_id}/episodes/{episode_id}/run present -> True
  /api/task-environments/{environment_id}/control-signals present -> True
  bound_task_run_id exposed -> False
  complete_bound_task exposed -> False
  max_steps exposed -> True
blocked episode API smoke:
  created minimal TaskWorkEnvironment via TaskWorkEnvironmentService
  prepared one episode with unregistered agent_profile_id
  POST /api/task-environments/{environment_id}/episodes/{episode_id}/run {"max_steps":1}
  response.status -> blocked
  executor_result.error -> task_episode_agent_profile_not_registered
  reduction present -> True
  task_environment_view present -> True
  task_environment_view.summary.episode_result_count -> 1
  GET /api/task-environments/{environment_id}
    activity_state.state -> blocked
    recovery_hint.recommended_control -> resume_task_environment_from_latest_context_package
budget signal smoke:
  _normalize_single_turn_tool_iteration_limit(None) -> None
  _normalize_single_turn_tool_iteration_limit(1) -> 1
  _tool_budget_exhausted_closeout_control_signal(...) signal_kind -> tool_budget_exhausted
  runtime_control_state -> agent_closeout_required
  used/max -> 1/1
  tool_calls_allowed_after_signal -> False
  attempted_actions_not_executed count -> 1
  structured_signal.code -> single_turn_tool_iteration_limit
```

补充结论：后端固定端口真实可启动，blocked episode 的 API / reducer / view 闭环通过；预算边界对象可正确表达“未执行工具请求 + 禁止继续工具 + agent 自行收口”。

### Stage F25：修正 GraphNodeTaskBinding 的 agent identity 语义污染

目标：

```text
Graph node 必须显式承接 agent profile。
agent_id 与 agent_profile_id 是两个不同语义字段；TaskSystem 仓库层不能把 profile 字符串反向伪装成 agent_id。
```

权威链检查：

- 符合：`GraphNodeWorkOrder.__post_init__()` 已要求 agent work order 必须有显式 `agent_profile_id`。
- 符合：`project_network_tasks.template_catalog` 将 profile 放入节点 metadata，`executable_graph_config_publisher._node_config()` 会提升到 executable node 顶层 `agent_profile_id`，再进入 compiled node contract 和 work order。
- 符合：harness graph node bridge 通过 `_explicit_graph_node_agent_profile_id()` 解析 profile，并在 registry 查到 profile 后用 `_explicit_graph_node_agent_id(..., profile=profile)` 补齐 agent_id。
- 问题：`GraphNodeTaskBindingService._agent_id()` 曾把 `agent_profile_id` 当作 `agent_id` 兜底来源，污染 `TaskInstance.owner_agent_id` 和 `AgentExecutionEpisode.agent_id`。

逻辑检查：

- `backend/task_system/graph_bindings/service.py`
  - `_agent_id()` 只接受 `work_order.agent_id`、`input_package.node_identity.agent_id`、`node_contract.agent_assembly.agent_id`；
  - `_agent_profile_id()` 继续接受 `work_order.agent_profile_id`、binding、node_identity 和 agent_assembly 中的显式 profile；
  - 任务仓库层不再把 profile 反向写成 agent identity。

验证：

```text
python -m compileall backend/task_system/graph_bindings/service.py backend/harness/entrypoint/runtime_facade.py backend/graph_system/context_materializer.py backend/task_system/compiler/executable_graph_config_publisher.py
  passed
inline semantic check:
  profile-only work_order -> _agent_id(...) == ""
  profile-only work_order -> _agent_profile_id(...) == "project_network_file_reviewer_agent"
rg fixed-string residual check:
  profile fallback remains only in _agent_profile_id(), not in _agent_id()
```

结论：通过。Graph node 的 profile 显式承接保留，agent identity 不再由 profile 字符串伪造；harness 仍可通过已解析 profile 对象获得真实 `profile.agent_id`。

### Stage F26：让节点自身工具策略进入 compiled contract 和 runtime assembly

目标：

```text
节点可以显式声明自己的工具/操作边界。
如果节点声明 model-response-only，即使 agent profile 本身有工具，runtime assembly 也必须以节点合同为 ceiling。
```

权威链检查：

- 符合：agent runtime profile 仍定义基础能力上限。
- 符合：Graph node executor/runtime policy 可以进一步收缩该节点本次执行的工具面。
- 符合：harness runtime assembly 只接收 runtime contract / profile 后的显式操作集合，不自行猜测节点任务是否需要工具。

逻辑检查：

- `backend/task_system/compiler/node_contract_models.py`
  - `build_node_contract()` 从 `metadata.runtime_profile.tool_policy/tool_exposure_policy`、`executor.executor_policy.operation_policy/tool_policy/tool_exposure_policy`、节点/graph tools policy 中合并 `_node_tool_policy()`；
  - compiled node contract 新增 `tool_policy`；
  - 策略合并使用既有 `_merge_runtime_policy_dicts()`，不新造合并体系。
- `backend/harness/entrypoint/runtime_facade.py`
  - `_graph_node_runtime_contract()` 从 compiled node contract 读取 `tool_policy`；
  - 将 `tool_policy` 同时放入 runtime contract 顶层和 `runtime_profile.tool_policy/tool_exposure_policy`；
  - `build_runtime_assembly_profile()` 已会读取这些字段并执行 `operation_ceiling / blocked_operations`。

验证：

```text
python -m compileall backend/task_system/compiler/node_contract_models.py backend/harness/entrypoint/runtime_facade.py backend/harness/runtime/assembly.py backend/project_network_tasks/template_catalog.py
  passed
compiled contract smoke:
  input executor_policy.tool_policy.operation_ceiling -> ("op.model_response",)
  compiled node_contract.tool_policy.operation_ceiling -> ("op.model_response",)
  graph node runtime_contract.runtime_profile.tool_policy.operation_ceiling -> ("op.model_response",)
assembly smoke:
  profile allowed_operations: op.model_response, op.workspace_read, op.workspace_search
  runtime_contract operation_ceiling: op.model_response
  build_runtime_assembly_profile(...).allowed_operations -> op.model_response
git diff --check
  passed; only existing CRLF warnings
```

结论：通过。节点自身工具策略现在能作为运行合同的一等约束进入 harness；后续项目网络 module/directory review 这类 model-response-only 节点，不必依赖“profile 恰好无工具”才能安全运行。

### Stage F27：清理前端残留的 ActiveTurn.bound_task_run_id 协议入口

目标：

```text
后端已删除 ActiveTurn -> TaskRun 隐式绑定后，前端不能继续承认 bound_task_run_id。
active turn snapshot 只能读取显式 task_run_id / runtime_task_run_id；新 TaskEnvironment episode 不再借用旧 bound 字段。
```

权威链检查：

- 符合：后端 `ActiveTurnRecord` 已无 `bound_task_run_id`。
- 符合：OpenAPI 已不暴露 `bound_task_run_id`。
- 问题：前端 `ChatPanel`、runtime store、event normalizer、API type 和部分旧 fixture 仍把 `bound_task_run_id` 当作合法输入。

逻辑检查：

- `frontend/src/components/chat/ChatPanel.tsx`
  - live assistant binding 不再读取 `activeTurnSnapshot.bound_task_run_id`。
- `frontend/src/lib/store/runtime.ts`
  - `activeTurnSnapshotFromPayload()` 不再从 `bound_task_run_id` 兜底；
  - stream binding 不再读取 `data.bound_task_run_id`。
- `frontend/src/lib/store/events.ts`
  - stream session binding 和 active task turn gate 不再读取 `bound_task_run_id`；
  - active turn gate 改读 `activeTurn.task_run_id`。
- `frontend/src/lib/api/types.ts`
  - `HarnessSessionLiveMonitor.active_turn_snapshot` 删除 `bound_task_run_id` 类型字段。
- `frontend/src/lib/store/runtime.test.ts`
  - 旧 fixture 改为 `task_run_id`，不再教前端接受旧字段。

验证：

```text
rg -n "bound_task_run_id" backend frontend --glob "*.py" --glob "*.ts" --glob "*.tsx"
  no hits
python -m compileall backend/task_system/compiler/node_contract_models.py backend/harness/entrypoint/runtime_facade.py backend/task_system/graph_bindings/service.py backend/harness/loop/single_agent_turn.py
  passed
npx tsc --noEmit --pretty false
  passed
git diff --check
  passed; only existing CRLF warnings
```

结论：通过。`bound_task_run_id` 已从后端、前端运行协议、类型声明和旧 fixture 中清零；ActiveTurn 不再承担 TaskRun 隐式绑定语义。

### Stage F28：Turn Environment Snapshot 拆分执行范围身份

目标：

```text
session turn snapshot 不能再把 TaskEnvironment episode 或 GraphNodeWorkOrder 塞进旧 task_run_id。
task_run_id 只表示仍合法存在的旧 TaskRun / GraphRun root 运行坐标。
TaskEnvironment episode、Graph node work order、上下文包身份必须作为显式执行范围字段写入 snapshot。
```

权威链检查：

- 符合：`Harness` 只记录本次 single-agent turn 的执行范围事实，不决定 TaskSystem / GraphSystem 状态。
- 符合：`TaskSystem` 的 episode 身份使用 `episode_id / task_environment_id / context_package_id`。
- 符合：`GraphSystem` 的节点工作单身份使用 `graph_run_id / node_id / work_order_id`；根 `task_run_id` 暂留为 GraphRun root scope，不在本阶段迁移。
- 问题：`HarnessRuntimeFacade._record_turn_environment_snapshot()` 只有 `task_run_id` 参数，导致 task episode 曾被写成 `task_run_id=episode.episode_id`，graph node 也会在 `episode_id` 与 root `task_run_id` 之间混用。

逻辑检查：

- `backend/harness/entrypoint/runtime_facade.py`
  - `_record_turn_environment_snapshot()` 改为接收 `execution_scope`；
  - 普通 turn 默认 `execution_scope_kind=single_agent_turn`；
  - task environment episode 写入 `execution_scope_kind/task_environment_id/task_instance_id/episode_id/context_package_id`，不再写 `task_run_id=episode_id`；
  - graph node work order 写入 `execution_scope_kind/task_environment_id/task_instance_id/episode_id/graph_run_id/node_id/work_order_id/context_package_id`，同时仅保留真实 root `task_run_id`。
- `backend/sessions/__init__.py`
  - `_normalize_turn_environment_snapshot()` 持久化新的执行范围字段。
- `backend/memory_system/environment_context.py`
  - `MemoryEnvironmentContext` 扩展读取 `execution_scope_kind / task_instance_id / episode_id / graph_run_id / node_id / work_order_id / context_package_id`；
  - 记忆环境仍保留 `task_run_id`，但不再需要 episode 冒充 task run 才能获得范围坐标。

验证：

```text
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/sessions/__init__.py backend/memory_system/environment_context.py
  passed
rg -n "_record_turn_environment_snapshot\(|task_run_id=episode|task_run_id=str\(episode" backend/harness/entrypoint/runtime_facade.py
  only call sites and function definition; no episode-as-task_run residual
snapshot smoke:
  task_environment_episode -> execution_scope_kind=task_environment_episode, episode_id=ep1, task_run_id=""
memory context smoke:
  task_environment_episode -> task_environment_id=env1, episode_id=ep1, task_run_id="", source=session_record.turn_environment_snapshot
  graph_node_work_order -> graph_run_id=gr1, node_id=n1, work_order_id=wo1, task_run_id=taskrun:root
```

结论：通过。turn snapshot 的身份坐标已从旧 `task_run_id` 单字段拆分为显式 execution scope；episode 不再伪装成 TaskRun，GraphRun root `task_run_id` 仍按既定边界暂留。

### Stage F29：GraphNodeTaskBinding 准备事件与执行阶段副作用拆分

目标：

```text
GraphSystem 的 work order 执行链必须保持阶段单调：
prepare -> lease/running -> result/completed -> release
result/release 不能为了取 binding/episode/context package 再次触发 prepared 事件或 ready snapshot patch。
```

权威链检查：

- 符合：`GraphSystem` 只负责 work order 调度、执行和结果接纳。
- 符合：`TaskSystem` 负责 graph node task binding、episode、lease、result reducer 和 task environment snapshot。
- 问题：`GraphNodeTaskBindingService.record_work_order_result()` 和 `release_work_order_execution_lease()` 曾调用 `prepare_work_order()`，而 `prepare_work_order()` 会 append `graph_node_task_prepared` 并 patch snapshot 为 `ready/scheduled`。这会让 result/release 阶段带有 prepare 阶段副作用，存在状态回退风险。

逻辑检查：

- `backend/task_system/graph_bindings/service.py`
  - 新增内部 `GraphNodeTaskState`，只承载 binding / task instance / task environment / episode / context package；
  - 新增 `_ensure_work_order_state()`，只确保对象存在并 upsert context package，不记录 prepared event；
  - `prepare_work_order()` 继续是公开准备入口，负责调用 `_append_prepared_event()`；
  - `begin_work_order_execution()` 仍调用 `prepare_work_order()`，保证首次执行前有 prepared 事件；
  - `record_work_order_result()` 改走 `_ensure_work_order_state()`，只记录 result/reducer；
  - `release_work_order_execution_lease()` 改走 `_ensure_work_order_state()`，只释放 lease。

验证：

```text
python -m compileall backend/task_system/graph_bindings/service.py
  passed
temporary sqlite smoke:
  begin_work_order_execution -> environment status=leased, step=running
  record_work_order_result -> environment status=completed, step=completed
  release_work_order_execution_lease -> environment status=completed, step=completed
  events -> graph_node_task_prepared, graph_node_execution_lease_acquired, graph_node_task_result_recorded, graph_node_execution_lease_released
  prepared_count -> 1
```

结论：通过。graph node task binding 的对象确保逻辑和 prepared 阶段事件已经拆开；result/release 不再把任务环境 snapshot 回退到准备态。

### Stage F30：ActiveWorkContext 清理旧 task_run 坐标残留

目标：

```text
active work 是 TaskWorkEnvironment 控制面，不再携带旧 task_run_id。
GraphRun root task_run_id 仍属于 graph/event/root runtime scope，不允许通过 ActiveWorkContext 暗接回当前工作控制链。
```

权威链检查：

- 符合：`ActiveWorkContext` 由 foreground `SessionTaskBinding -> TaskWorkEnvironment` 生成。
- 符合：active work 控制动作写入 `TaskControlSignal`，再由 TaskSystem/GraphSystem bridge 处理。
- 问题：`ActiveWorkContext` 仍保留未赋值的 `task_run_id` 字段，`single_agent_turn.active_work_event_refs()` 也保留了从 active work payload 反射 `task_run_id` 的分支。虽然当前值为空，但会为后续旧坐标回灌留下入口。

逻辑检查：

- `backend/harness/loop/active_work.py`
  - 删除 `ActiveWorkContext.task_run_id`；
  - `to_model_dict()` 不再需要弹出旧字段。
- `backend/harness/loop/single_agent_turn.py`
  - `active_work_event_refs()` 只接受 `task_environment_id` 作为 active work 事件坐标；
  - 删除 active work refs 中的 `runtime_task_run_id/task_run_id` 写回；
  - reasoning projection 不再从 active work payload 读取 `task_run_id`。

验证：

```text
python -m compileall backend/harness/loop/active_work.py backend/harness/loop/single_agent_turn.py
  passed
rg -n --fixed-strings 'active_work_payload.get("task_run_id")' -- backend/harness/loop/single_agent_turn.py
  no hits
rg -n --fixed-strings 'task_run_id' -- backend/harness/loop/active_work.py
  no hits
```

结论：通过。active work/current work 控制面已经只以 TaskWorkEnvironment 为坐标，不再保留旧 TaskRun 回灌入口。

### Stage F31：任务环境与图节点执行消息改为 Agent 可执行契约

目标：

```text
发给 worker agent 的消息必须描述身份、职责、边界、输入、输出和失败处理。
不能把 runtime / episode / graph node 的开发说明当作 prompt。
```

权威链检查：

- 符合：系统提供任务输入、资源、验收和输出契约。
- 符合：agent 负责在边界内完成判断和交付。
- 问题：`_task_episode_user_message()` 和 `_graph_node_work_order_user_message()` 的开头仍偏技术说明，如“你正在执行一个持久任务环境中的单次 episode”。这不利于 worker agent 稳定理解自己的角色和交付标准。

逻辑检查：

- `backend/harness/entrypoint/runtime_facade.py`
  - task episode 消息改为“你是一名任务环境执行员”，明确只能推进目标、整理证据、产出可归并结果或说明阻塞；
  - graph node 消息改为“你是一名图任务节点执行员”，明确只负责当前节点，不负责推进整张图、调度下游、写 checkpoint 或启动新任务；
  - 两者都明确工具只以运行时展示为准；
  - 输入 JSON 仍作为资源、上下文和输出契约清单保留。

验证：

```text
python -m compileall backend/harness/entrypoint/runtime_facade.py
  passed
rg -n "你正在执行一个持久任务环境|你正在作为图任务节点|你是一名任务环境执行员|你是一名图任务节点执行员" backend/harness/entrypoint/runtime_facade.py
  old technical openings -> no hits
  new executable role openings -> present
```

结论：通过。任务环境 worker 和图节点 worker 收到的消息更接近成熟 agent 的任务契约：身份明确、边界明确、交付/阻塞标准明确。

### Stage F32：stale lease 恢复返回可导航恢复投影

目标：

```text
recover-stale-leases 只负责修复过期租约状态并呈现下一步控制入口。
它不能替 GraphSystem 自动 resume，也不能只返回清理结果让调用方再次猜测恢复路径。
```

权威链检查：

- 符合：`TaskWorkEnvironmentService.recover_stale_leases()` 仍只做 lease 过期、episode 中断、环境暂停和事件记录。
- 符合：`TaskEnvironmentViewService` 负责呈现 `activity_state / recovery_hint / control_capabilities / recommended_api`。
- 符合：API 层只在响应中附加 `graph_runtime_projection`，不改变 GraphSystem 状态。
- 问题：旧返回值只有 `lease / episode / event`，调用方知道发生了恢复，但不知道该走普通任务环境恢复还是图运行恢复。

逻辑检查：

- `backend/task_system/work_environments/view_service.py`
  - 新增 `task_environment_recovery_projection()`；
  - 返回刷新后的 `task_environment`、任务实例摘要、图节点绑定摘要、活动态、恢复提示、控制能力、推荐 API、最近 context package、最近 lease 和 pending control signals；
  - 投影保持轻量，不把完整 events/episodes/work products 塞进维护端点。
- `backend/task_system/work_environments/service.py`
  - stale lease recovery 在写入 `task_environment_lease_expired` 后读取恢复投影；
  - 返回项增加 `recovery_projection`；
  - 仍不执行 graph resume。
- `backend/api/task_system.py`
  - `/task-environments/recover-stale-leases` 将恢复投影交给 `_task_environment_graph_runtime_projection()` 做实时图运行摘要；
  - API 只负责呈现，不调度图恢复。

验证：

```text
python -m compileall backend\task_system\work_environments\view_service.py backend\task_system\work_environments\service.py backend\api\task_system.py
  passed

temporary sqlite smoke: plain task environment stale lease
  recovered_count 1
  lease_status expired
  env_status paused lease_expired resume_task_environment
  episode_status interrupted task_environment_lease_expired
  projection_authority task_system.task_environment_view.recovery_projection
  activity_state paused
  recommended_api POST /api/task-environments/{environment_id}/control-signals
  can_request_resume True
  graph_owner task_system

temporary sqlite smoke: graph node task environment stale lease
  recovered_count 1
  graph_run_id graph-run-smoke
  recovery_owner graph_system
  recommended_control graph_run_resume
  recommended_api POST /api/task-environments/{environment_id}/recovery-actions
  graph_recovery_supported True
```

结论：通过。过期租约恢复现在是一个可导航控制面：系统修复 stale 状态，view 明确下一步入口，graph 恢复仍由显式 recovery action 或 GraphSystem 控制。

### Stage F33：MemoryEnvironmentContext 取消 task_run_id 到 turn snapshot 的隐式回查

目标：

```text
task_run_id 可以作为运行日志、working memory 或 GraphRun root scope。
但它不能再作为 session turn snapshot 的查找键，把旧 turn 的任务环境隐式绑定到当前任务解析。
```

权威链检查：

- 符合：`MemoryEnvironmentContext` 仍保留 `task_run_id` 事实，用于合法运行 scope。
- 符合：turn snapshot 的环境选择只能来自明确 `turn_id` 或没有运行 scope 时的会话最近环境回退。
- 问题：旧 `latest_turn_environment_snapshot(..., task_run_id=...)` 会按 snapshot 里的 `task_run_id` 反查环境；即使删除直接匹配，如果继续 latest fallback，也会在 task run scope 下拿到会话最近环境。

逻辑检查：

- `backend/memory_system/environment_context.py`
  - `latest_turn_environment_snapshot()` 删除 `task_run_id` 参数；
  - 增加 `allow_latest_fallback`；
  - `resolve_memory_environment_context()` 在传入 `task_run_id` 时禁用 latest snapshot fallback；
  - `task_run_id` 仍可由 explicit/main context 填入 `MemoryEnvironmentContext`，但不再决定任务环境。

验证：

```text
python -m compileall backend\memory_system\environment_context.py
  passed

memory context smoke:
  task_run_only_env ""
  task_run_only_source ""
  task_run_only_scope taskrun:root
  turn_env env-old
  turn_source session_record.turn_environment_snapshot
  turn_scope taskrun:root
  ordinary_latest_env env-old
  explicit_scope_task_run taskrun:root
```

结论：通过。active turn / memory 环境解析不再通过 TaskRun root scope 暗接旧 turn 环境；GraphRun root `task_run_id` 仍作为运行 scope 保留。

### Stage F34：CurrentWorkBoundary 终态判断改用 TaskEnvironment 语义

目标：

```text
CurrentWorkBoundary 面向的是当前 TaskWorkEnvironment active work。
它不能复用 TaskRun 的 terminal status/reason catalog 来决定当前任务环境是否可控制。
```

权威链检查：

- 符合：`ActiveTurnRegistry` 本体只保存 `turn_id / turn_run_id / stream_run_id`，没有 TaskRun 绑定。
- 符合：`ActiveWorkContext` 已是 TaskEnvironment 控制面，终态判断应由 TaskEnvironment 状态表决定。
- 问题：`backend/harness/entrypoint/current_work_boundary.py` 导入 `harness.task_run_status`，用 `is_terminal_task_run_status/reason()` 判断 active work 是否终止，等于把 TaskRun lifecycle catalog 带回当前工作控制面。

逻辑检查：

- `backend/harness/entrypoint/current_work_boundary.py`
  - 删除 `harness.task_run_status` 依赖；
  - 新增 `_TERMINAL_TASK_ENVIRONMENT_STATUSES` 与 `_TERMINAL_TASK_ENVIRONMENT_REASONS`；
  - `_terminal_active_work()` 只按 TaskEnvironment 语义判断。

验证：

```text
python -m compileall backend\harness\entrypoint\current_work_boundary.py
  passed

current work boundary smoke:
  completed True
  failed True
  aborted True
  archived True
  blocked False
  paused False
  leased False
  reason_completed True
  old_task_run_reason False
```

结论：通过。当前工作边界不再借用 TaskRun 终态语义；TaskEnvironment active work 控制面保持独立。

### Stage F35：前端 ActiveTurnSnapshot 改为 turn/stream 坐标优先

目标：

```text
前端 active turn gate 必须跟随 ActiveTurn 的真实身份：turn_id / stream_run_id / turn_run_id。
task_run_id 只能作为运行日志、monitor 或文件变更归属线索，不能作为 active turn 本体的主键。
```

权威链检查：

- 符合：后端 `ActiveTurnRecord` 已只保存 `turn_id / turn_run_id / stream_run_id`。
- 符合：GraphRun root `task_run_id` 仍可用于 runtime monitor 和日志投影。
- 问题：`frontend/src/lib/store/events.ts` 过去要求 `task_run_id` 才能创建 `activeTurnSnapshot`，释放 gate 时也可仅凭 `task_run_id` 匹配 snapshot；这会把 TaskRun root scope 重新变成 active turn 绑定。

逻辑检查：

- `frontend/src/lib/store/types.ts`
  - `ActiveTurnSnapshot` 新增 `stream_run_id`。
- `frontend/src/lib/store/events.ts`
  - active turn snapshot 写入以 `turn_id` 或 `stream_run_id` 为准；
  - `task_run_id` 改为可选 runtime-log 关联；
  - 释放 active turn snapshot 时只按 `turn_id/stream_run_id` 匹配；
  - `task_run_id` 仍只用于清理 `taskGraphLiveMonitor`。
- `frontend/src/lib/store/runtime.ts`
  - `activeTurnSnapshotFromPayload()` 读取 `stream_run_id`；
  - 停止流释放 active turn gate 时传入 `stream_run_id`，不再仅靠 `task_run_id` 清 active turn snapshot。
- `frontend/src/components/chat/ChatPanel.tsx`
  - live assistant binding 优先读取 `activeTurnSnapshot.stream_run_id`。

验证：

```text
npx tsc --noEmit --pretty false
  passed
```

结论：通过。前端 active turn gate 已从 TaskRun 主键切回 ActiveTurn 自身坐标；TaskRun 只作为运行/监控归属线索保留。

### Stage F36：Run Monitor ActiveTurn 项显式暴露 turn/stream 坐标

目标：

```text
run monitor 可以为了现有行选择协议暂时使用 turn_run_id 作为行 id。
但 ActiveTurn 项不能再把 stream_run_id 或 turn_id fallback 成 task_run_id，也必须显式暴露 active_turn_id / turn_run_id / stream_run_id。
```

权威链检查：

- 符合：`ActiveTurnRecord` 是 active turn 身份权威。
- 符合：run monitor 只是呈现层，不应制造新的 TaskRun 身份。
- 问题：`RunMonitorProjector.project_active_turn()` 曾用 `turn_run_id or stream_run_id or turn_id` 填入 `task_run_id`，这会让 stream/turn 被伪装成 TaskRun 行。

逻辑检查：

- `backend/harness/runtime/run_monitor/projector.py`
  - active turn monitor item 新增 `active_turn_id / turn_id / turn_run_id / stream_run_id / source_kind=turn_run`；
  - `task_run_id` 只取 `turn_run_id`，不再 fallback 到 `stream_run_id/turn_id`；
  - route kind 改为 `turn_run`，并携带显式 turn/stream 坐标。
- `backend/harness/runtime/run_monitor/service.py`
  - `_visible_item_already_represents_active_turn()` 改用 `turn_run_id / stream_run_id / active_turn_id` 去重；
  - 不再用 `task_run_id/task_instance_id` 判断 active turn 是否已被可见项代表。
- `frontend/src/lib/api/types.ts`
  - `HarnessSessionLiveMonitor.active_turn_snapshot` 类型补上 `stream_run_id`。

验证：

```text
python -m compileall backend\harness\runtime\run_monitor\projector.py backend\harness\runtime\run_monitor\service.py
  passed
npx tsc --noEmit --pretty false
  passed

project_active_turn smoke:
  task_run_id turnrun:smoke
  turn_run_id turnrun:smoke
  stream_run_id chatrun:smoke
  active_turn_id turn:smoke
  route_kind turn_run
  route_stream chatrun:smoke
  fallback_task_run_id ""
  fallback_stream_run_id chatrun:only
```

结论：通过。run monitor active turn 呈现层不再把 stream/turn 当成 TaskRun；剩余 `task_run_id=turn_run_id` 只是现有 run-monitor 行 id，需要后续单独升级 run-monitor contract 才能完全移除。

### Stage F37：Run Monitor 详情入口拆分 TaskRun 与 TurnRun

目标：

```text
run monitor 的详情查询必须按真实运行对象分派。
TaskRun endpoint 只解析真实 TaskRun；TurnRun endpoint 只解析 turn runtime。
前端不能再把 detail_ref.kind=turn_run 的信号送进 task-runs/{id} 旧入口。
```

权威链检查：

- 符合：GraphRun root `task_run_id` 仍是图运行的合法 runtime/event scope，本阶段不迁移。
- 符合：TurnRun 已有独立 trace/log scope，run monitor signal 已暴露 `detail_ref.kind=turn_run` 与 `turn_run_id`。
- 问题：`RunMonitorService.get_task_run_live_monitor()` 过去在 `state_index.get_task_run()` 查不到时，会继续用同一个 id 调 `get_turn_run()`；这让 `/harness/run-monitor/task-runs/{id}` 成为 TaskRun/TurnRun 混合入口。
- 问题：前端 `loadSignalDetail()` 只取 `signalDetailTaskRunId()`，因此 turn-run signal 仍会请求 task-run 详情接口。

逻辑检查：

- `backend/harness/runtime/run_monitor/service.py`
  - `get_task_run_live_monitor()` 删除 turn-run fallback，只返回真实 TaskRun monitor；
  - 新增 `get_turn_run_live_monitor()`，只按 TurnRun 查询，并要求当前 active turn 与 turn_run_id 匹配。
- `backend/api/harness_run_monitor.py`
  - 新增 `/harness/run-monitor/turn-runs/{turn_run_id}`；
  - 旧 `/task-runs/{task_run_id}` 保持存在，但不再解析 TurnRun。
- `backend/harness/runtime/run_monitor/contract.py`
  - `build_task_detail_envelope()` 支持显式 `scope`；
  - `build_turn_monitor()` 输出 `scope="turn_run"`。
- `backend/harness/runtime/single_agent_host.py`
  - 新增 `get_turn_run_live_monitor()` 委托。
- `backend/cli/client.py`
  - 新增 `get_turn_run_monitor()`，CLI 不需要借 task-run 入口读取 turn-run monitor。
- `frontend/src/lib/run-monitor/*`
  - 新增 `fetchRunMonitorTurnDetail()` 与 `signalDetailTurnRunId()`；
  - `loadSignalDetail()` 按 `detail_ref.kind/source_kind` 显式分派 task-run 或 turn-run 详情。
- `frontend/src/components/layout/RunMonitorPanel.tsx`
  - 打开运行日志时，turn-run signal 使用 `scope="turn_run"`。
- `frontend/src/components/workspace/views/task-system/runs/RunManagementWorkbench.tsx`
  - 运行管理页打开日志时同样按 signal kind 选择 `task_run/turn_run` scope。

验证：

```text
python -m compileall backend\api\harness_run_monitor.py backend\harness\runtime\run_monitor\contract.py backend\harness\runtime\run_monitor\projector.py backend\harness\runtime\run_monitor\service.py backend\harness\runtime\single_agent_host.py backend\cli\client.py
  passed

npx tsc --noEmit --pretty false
  passed

run monitor service smoke:
  task_detail None
  after_task_calls [('task', 'turnrun:1')]
  turn_detail {'scope': 'turn_run', 'turn_run_id': 'turnrun:1'}
  after_turn_calls [('turn', 'turnrun:1')]

real backend/frontend smoke:
  backend http://127.0.0.1:8003/health -> {"status":"ok"}
  openapi contains /api/harness/run-monitor/turn-runs/{turn_run_id}
  /api/harness/run-monitor/task-runs/turnrun%3Asmoke -> 404
  frontend http://127.0.0.1:3000 -> 200
```

结论：通过。run monitor 详情查询权威已拆分；TaskRun endpoint 不再承担 TurnRun 的兼容入口，前端 detail/log 也按 signal 真实类型走显式线路。

### Stage F38：Session Live Monitor 不再把 ActiveTurn 标成 active_task_run_id

目标：

```text
Session live monitor 的 active_task_run_id 只能表示真实 TaskRun。
当 session 只有当前 active turn、没有真实 TaskRun monitor 时，必须暴露 turn/stream 坐标，而不是把 turn_run_id 写进 active_task_run_id。
前端 activity/debug/control 也不能把 source_kind=turn_run 的信号当作 TaskRun。
```

权威链检查：

- 符合：`build_session_monitor()` 对真实 TaskRun 仍可输出 `active_task_run_id`。
- 符合：ActiveTurn 的真实坐标是 `turn_id / turn_run_id / stream_run_id`。
- 问题：`RunMonitorService.get_session_live_monitor()` 在没有 TaskRun item 时，会用 active turn fallback 构造 session monitor，并把 `active_item.task_run_id` 写入 `active_task_run_id`；而当前 active turn item 的 `task_run_id` 已只是 `turn_run_id` 行 id。
- 问题：前端 session activity 同步会把 active turn monitor 或 run-monitor signal 的 `task_run_id` 继续当作 TaskRun debug/control id。

逻辑检查：

- `backend/harness/runtime/run_monitor/service.py`
  - active-turn fallback monitor 的 `active_task_run_id` 改为空；
  - 新增 `active_turn_id / active_turn_run_id / active_stream_run_id`。
- `frontend/src/lib/api/types.ts`
  - `HarnessSessionLiveMonitor` 增加 `active_turn_id / active_turn_run_id / active_stream_run_id`。
- `frontend/src/lib/store/runtime.ts`
  - 新增 `liveMonitorTaskRunId()`：`source_kind=turn_run` 或 `execution_runtime_kind=single_agent_turn` 时返回空 TaskRun id；
  - 新增 `runMonitorSignalTaskRunId()`：`detail_ref.kind/source_kind=turn_run` 时返回空 TaskRun id；
  - session live monitor 与 run monitor activity 同步都改用上述 helper。

验证：

```text
python -m compileall backend\harness\runtime\run_monitor\service.py
  passed

npx tsc --noEmit --pretty false
  passed

session live monitor active-turn fallback smoke:
  active_task_run_id
  active_turn_run_id turnrun:1
  active_stream_run_id strun:1
  monitor_source turn_run
```

结论：通过。session live monitor 不再把普通 active turn 的 turn_run_id 命名成 active_task_run_id；前端 activity 仍可显示 turn-run 状态，但不会把它当作可控 TaskRun id。

### Stage F39：项目网络图节点结构化产物通道接线

目标：

```text
Graph node 的语义审查产物必须走机器结构化通道，不能再让 graph bridge 从 final_answer 反解析业务 JSON。
final_answer 只保留人读收口；quality gate 继续拥有项目网络 work product 的接受权。
```

权威链检查：

- `respond` control action schema 暴露 `structured_output_json` 机器输出槽。
- `model_action_protocol` 将 `structured_output_json`、JSON action 的 `structured_output/node_output` 归一化到 `diagnostics.final_action_diagnostics`。
- `single_agent_turn` 的 done event 携带 `final_action_diagnostics`。
- `runtime_facade` 的 task episode / graph node bridge 只读取 done event 的显式机器通道，不再从 `final_answer` 解析结构化产物。
- `project_network_tasks.runtime_adapters` 接受机器通道中的单个 `submission_kind=module_index/directory_summary` 事实对象，也保留 `project_network_semantic_submissions` envelope 入口；两者都不来自自然语言文本。

修正点：

- `backend/harness/runtime/control_action_schema.py`
  - `respond` 增加 `structured_output_json`。
- `backend/harness/loop/model_action_protocol.py`
  - 增加机器结构化输出归一化，统一写入 `final_action_diagnostics.structured_output/node_output`。
- `backend/harness/loop/single_agent_turn.py`
  - terminal done event 增加 `final_action_diagnostics`。
- `backend/harness/entrypoint/runtime_facade.py`
  - 删除 graph/task episode 从 `final_answer` 反解析结构化 JSON 的主路径。
- `backend/project_network_tasks/template_catalog.py`
  - 审查契约改为在 `respond.structured_output_json` 直接提交一个语义事实对象。
- `backend/project_network_tasks/runtime_adapters.py`
  - quality gate 输入归一化接受直接语义事实对象，并排除 `structured_output/node_output` 镜像 wrapper 的重复提交。

验证：

```text
python -m compileall backend/harness/runtime/control_action_schema.py backend/harness/loop/model_action_protocol.py backend/harness/loop/single_agent_turn.py backend/harness/entrypoint/runtime_facade.py backend/project_network_tasks/template_catalog.py
  passed

protocol smoke:
  respond schema props = final_answer, public_action_state, public_progress_note, structured_output_json
  model_action_request_from_payload(structured_output_json) -> final_action_diagnostics keys = node_output, structured_output

bridge smoke:
  _graph_node_executor_result_from_events(done.final_action_diagnostics.structured_output)
  -> task_execution.diagnostics.final_action_diagnostics.structured_output

adapter smoke with real generated directory_summary:
  submission_count 1
  submission_kind directory_summary

real GraphRun smoke:
  graph_id graph.project_network.directory.apix.v2.1.project.network.probe.20260702.092845.pndirframe.63a878ba76bb0249bd1c
  graph_run_id grun:graph_project_network_directory_apix_v2_1_project_network_probe_20260702_092845_pndirframe_63a878ba76bb0249bd1c:1783193538612
  run-until-idle max_node_executions=1 -> status completed
  executed_work_order_count 1
  accepted_result_count 1
  node result status completed
  node result output structured_output.submission_kind directory_summary
  monitor status completed, completed_count 1, blocked_count 0, active_work_order_count 0
```

结论：通过。项目网络 graph node 已能把 agent 产出的目录语义事实对象作为机器结构化产物送入 quality gate 并生成 accepted node result；旧的 `final_answer` 业务解析路径已从 graph bridge 主链路移除。

### Stage F40：Run Monitor ActiveTurn 行身份与 TaskRun 身份拆分

目标：

```text
ActiveTurn / TurnRun 监控项不能再为了 run monitor 行 id 把 turn_run_id 写入 task_run_id。
task_run_id 只表示真实 TaskRun；TurnRun 的日志、详情、去重和显示入口必须走 turn_run_id / monitor_item_id。
```

权威链检查：

- 符合：TaskRun 详情入口已经在 F37 拆出 `/task-runs/{task_run_id}` 与 `/turn-runs/{turn_run_id}`。
- 符合：Session live monitor 在 F38 已不把 active turn 写成 `active_task_run_id`。
- 问题：`RunMonitorProjector.project_active_turn()` 仍设置 `task_run_id=turn_run_id`，导致 active turn 监控行在公开 item/signal 层继续伪装成 TaskRun。
- 问题：前端日志按钮仍只看 `signal.task_run_id`，一旦后端清空 active turn 的 `task_run_id`，TurnRun 日志入口会丢失。

修正点：

- `backend/harness/runtime/run_monitor/projector.py`
  - active turn item 新增 `monitor_item_id`；
  - `task_run_id/root_task_run_id` 对 active turn 清空；
  - `task_instance_id` 改用 `monitor_item_id`；
  - fact/trace 查询仍用 `turn_run_id` 作为 runtime scope，不再暴露为 TaskRun 身份。
- `backend/harness/runtime/run_monitor/signals.py`
  - signal 显式输出 `monitor_item_id/turn_run_id/stream_run_id/active_turn_id`；
  - `source_kind=turn_run` 按 `turn_run_id` 与 `execution_runtime_kind=single_agent_turn` 判定；
  - `detail_ref.kind=turn_run` 时只填 `turn_run_id`，不再把 turn_run_id 镜像到 `task_run_id`。
- `backend/harness/runtime/run_monitor/management.py`
  - signal/source 索引纳入 `monitor_item_id/turn_run_id`；
  - inspect 对 TurnRun 信号仍可用；
  - TaskRun 生命周期动作仍要求真实 `task_run_id`。
- `frontend/src/lib/api/types.ts`
  - `RunMonitorSignal` 增加 `monitor_item_id/turn_run_id/stream_run_id/active_turn_id`。
- `frontend/src/lib/run-monitor/reducer.ts`
  - signal 查找、去重和 TurnRun 详情 id 读取纳入 `monitor_item_id/turn_run_id`。
- `frontend/src/lib/run-monitor/selectors.ts`
  - 运行监控列表去重纳入 `monitor_item_id/turn_run_id`。
- `frontend/src/components/layout/RunTaskLane.tsx`
  - 打开项和日志按钮按 `signal_id/monitor_item_id/turn_run_id` 取值；
  - TurnRun 日志使用 `detail_ref.turn_run_id`。
- `frontend/src/components/layout/RunMonitorPanel.tsx`
  - 打开日志按 signal scope 分派 TaskRun / TurnRun run id。
- `frontend/src/components/workspace/views/task-system/runs/RunManagementWorkbench.tsx`
  - 运行管理页同步使用 TurnRun 日志和打开 id。

验证：

```text
python -m compileall backend/harness/runtime/run_monitor/projector.py backend/harness/runtime/run_monitor/signals.py backend/harness/runtime/run_monitor/management.py
  passed

npx tsc --noEmit --pretty false
  passed

active turn projection smoke:
  item_task_run_id ''
  item_root_task_run_id ''
  item_monitor_item_id turnrun:smoke
  signal_id turnrun:smoke
  signal_task_run_id ''
  signal_turn_run_id turnrun:smoke
  detail_ref {'kind': 'turn_run', 'task_run_id': '', 'turn_run_id': 'turnrun:smoke', ...}
  inspect_enabled {'action': 'inspect', 'enabled': True}

fixed port smoke:
  restarted backend on http://127.0.0.1:8003 with run_uvicorn.py
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:8003/api/harness/run-monitor?limit=5 -> 200 payload
  openapi contains /api/harness/run-monitor/turn-runs/{turn_run_id} -> True
  openapi contains /api/harness/run-monitor/task-runs/{task_run_id} -> True
```

结论：通过。Run monitor 的 ActiveTurn/TurnRun 行身份已经从 TaskRun 身份中拆出；TaskRun endpoint、TaskRun 生命周期动作和 TaskRun 日志入口不再需要承载 active turn。

### Stage F41：Run Monitor 管理动作只暴露真实可执行动作

目标：

```text
Run monitor management 不能展示后端 action service 不支持的控制动作。
按钮呈现必须与执行权威一致：没有接入 RuntimeControlSignal 的动作不能以 pause/stop/close 的形式出现在 UI。
```

权威链检查：

- 符合：`RunMonitorActionService` 是 `/harness/run-monitor/actions` 的执行权威。
- 符合：现有 action service 只执行 `clear_from_monitor / restore_to_monitor / preview_delete_record / preview_delete_graph_run / delete_record`。
- 问题：`RunMonitorManagementProjector` 会根据 `control_capability` 生成 `pause_task / stop_task / close_runtime`，但 action service 对这些动作返回 `unsupported_action`。
- 裁决：本阶段不临时接停止/暂停链路。停止和暂停应由 RuntimeControlSignal 专门接线；在未接入前，monitor 不应展示不可执行动作。

修正点：

- `backend/harness/runtime/run_monitor/management.py`
  - 删除 `pause_task / stop_task / close_runtime` 的动作生成；
  - management action list 只保留 action service 已支持的动作；
  - `inspect` 仍支持 TaskRun / TurnRun / GraphRun。
- `frontend/src/components/layout/RunMonitorPanel.tsx`
  - 删除 `stop_task / close_runtime` 的确认分支。
- `frontend/src/components/layout/RunTaskLane.tsx`
  - 删除不可达 warning action 分类。
- `frontend/src/components/workspace/views/task-system/runs/RunManagementWorkbench.tsx`
  - 删除 `stop_task / close_runtime` 的确认分支和 warning action 分类。

验证：

```text
python -m compileall backend/harness/runtime/run_monitor/management.py
  passed

npx tsc --noEmit --pretty false
  passed

management smoke actions:
  ['open', 'inspect', 'clear_from_monitor', 'preview_delete_record', 'delete_record']

fixed port smoke after backend restart:
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:8003/api/harness/run-monitor?limit=5 action names:
    clear_from_monitor
    delete_record
    inspect
    open
    preview_delete_record
```

结论：通过。Run monitor 不再发布后端无法执行的运行控制按钮；后续若要支持暂停、停止、关闭，应新增 RuntimeControlSignal 执行通道并在 action service 接入后再恢复 UI 动作。

### Stage F42：清理 Run Monitor 旧控制动作测试残留

目标：

```text
测试不能继续保护已经从 run monitor management 中移除的 pause/stop/close 旧动作语义。
现有测试样本必须使用 action service 真实支持的动作，避免后续维护者误以为 stop_task/close_runtime 仍是 monitor 主链能力。
```

权威链检查：

- 符合：F41 已将 run monitor management 的公开动作收紧到 action service 支持集合。
- 问题：`frontend/src/components/layout/RunTaskLane.test.ts` 仍用 `stop_task / close_runtime` 作为 inline action 样本。
- 裁决：不新增测试文件，只修正现有测试的语义样本；这属于清理旧链路保护，不是扩大测试体系。

修正点：

- `frontend/src/components/layout/RunTaskLane.test.ts`
  - inline action 样本从 `stop_task / close_runtime` 改为 `clear_from_monitor / delete_record`；
  - 断言文本同步改为 `清出 / 删除记录`。

验证：

```text
rg -n 'pause_task|stop_task|close_runtime|run-monitor-task__action--warning|run-management-row__action--warning' frontend/src -g '*.test.ts' -g '*.test.tsx' -g '*.ts' -g '*.tsx'
  no matches

npx tsc --noEmit --pretty false
  passed

python -m compileall backend/harness/runtime/run_monitor/management.py backend/harness/runtime/run_monitor/projector.py backend/harness/runtime/run_monitor/signals.py
  passed
```

结论：通过。Run Monitor 前端源代码和现有测试都不再保留已移除的 pause/stop/close 旧动作语义；后续运行控制必须通过正式 RuntimeControlSignal 通道重新接入。

### Stage F43：ProjectNetwork 旧 task_system authority 数据与运行时兼容归一化清理

目标：

```text
ProjectNetworkSystem 是项目网络资产权威，运行主链不应再在 repository schema 初始化时兼容 task_system.project_network 旧 authority。
真实存储中的旧 authority 必须一次性迁移到 project_network_system，而不是每次启动靠旧前缀归一化兜底。
```

权威链检查：

- 符合：实施索引已裁决 `task_system.project_network` 只属于历史路径，不是当前权威路径。
- 问题：`backend/project_network_system/repository.py` 在 `_ensure_schema()` 后每次调用 `_normalize_project_network_authorities()`，按旧前缀改写一部分表。
- 问题：真实 `storage/tasks/project_network.sqlite` 中仍有旧 authority，但原函数覆盖不完整，遗漏 skeleton / maintenance / semantic repair 等表。
- 裁决：删除运行时兼容归一化；对当前真实库执行一次明确数据迁移，覆盖所有 `project_network_%` 且带 `authority` 列的表。

修正点：

- `backend/project_network_system/repository.py`
  - 删除 `_ensure_schema()` 中的 `_normalize_project_network_authorities(conn)` 调用；
  - 删除 `_normalize_project_network_authorities()` 函数；
  - repository 不再引用 `task_system.project_network` 旧前缀。
- `storage/tasks/project_network.sqlite`
  - 用事务将旧 `authority LIKE 'task_system.project_network.%'` 更新为 `project_network_system.` 前缀；
  - 只更新 `authority` 字段，不改 payload、索引、产物内容。

数据迁移结果：

```text
project_network_git_change_sets before 3 after 0
project_network_maintenance_runs before 3 after 0
project_network_semantic_repair_work_items before 50 after 0
project_network_skeleton_edges before 6704 after 0
project_network_skeleton_facts before 11049 after 0
project_network_skeleton_generations before 3 after 0
project_network_skeleton_nodes before 1194 after 0
legacy_total_after 0
current_total_after 19435
```

验证：

```text
python -m compileall backend/project_network_system/repository.py
  passed

rg -n 'task_system\.project_network|_normalize_project_network_authorities|legacy_prefix = "task_system\.project_network\."' backend/project_network_system backend/project_network_tasks backend -g '*.py'
  no matches

repository smoke:
  build_ids ['agent_system_models_control_network_ast_live_20260702_063038', ...]
  legacy_total 0
  current_total 19435
  snapshot_build_id agent_system_models_control_network_ast_live_20260702_063038
  snapshot_work_products 5
  snapshot_candidates 5

fixed port smoke after backend restart:
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
```

结论：通过。ProjectNetworkSystem 的真实存储 authority 已迁到当前权威前缀，repository 运行主链不再携带 `task_system.project_network` 旧前缀兼容归一化。

### Stage F44：GraphSystem 边协议读取权威收束到 compiled edge contract

目标：

```text
图运行时不能在 edge contract 缺失时自行从 edge_protocol_index 或旧 edge 字段拼投影。
是否生成 flow packet、ack 策略、packet 可见性、上下文槽位等运行语义必须来自编译后的 edge_contract_index。
```

权威链检查：

- 符合：`task_system.compiler.graph_compiler` 已在发布期为每条边生成 `edge_contract_index`，并对缺失 contract / 缺失 protocol.kind 产出 compile issue。
- 符合：真实 `storage/tasks/graph_configs.json` 中 131 个 config、415 条边的 `edge_contract_index` 覆盖率为 100%。
- 问题：`graph_system.edge_contracts.edge_contract_or_projection()` 在 contract 缺失时会从 `edge_protocol_index` 和 edge 字段拼接运行时投影。
- 问题：`flow_packet.edge_delivers_flow_packet()` 在 graph_config 或协议信息缺失时继续使用旧 edge_type / scheduler_role / semantic_role 推断是否落包。
- 问题：`GraphStateMachine._initial_edge_state()` 仍从 `legacy_protocol_projection / edge_protocol_index / edge` 兜底 ack 策略。
- 裁决：运行期不再承担边协议推断权。缺少 compiled edge contract 属于发布配置错误，应显式失败，而不是静默按旧字段继续运行。

修正点：

- `backend/graph_system/edge_contracts.py`
  - 删除 `edge_contract_or_projection()`；
  - 新增明确入口 `edge_contract_for_edge()`；
  - contract 缺失时抛出 `ExecutableGraphConfig missing compiled edge contract`。
- `backend/graph_system/flow_packet.py`
  - `edge_delivers_flow_packet()` 强制要求 `graph_config`，只读 contract `trace.persist_packet / protocol.produces_flow_packet / protocol.kind`；
  - 删除 `_legacy_edge_delivers_flow_packet()` 和旧 edge type 判定表；
  - `build_flow_packet()` 的 packet 类型、payload contract、target context、input slot、ack、可见性过滤改为 contract 驱动。
- `backend/graph_system/state_machine.py`
  - 初始 edge state 直接读取 compiled edge contract；
  - 删除 `edge_protocol_index` 和 `legacy_protocol_projection` ack fallback。
- `backend/graph_system/transition_processor.py`
  - policy snapshot 只读取 contract `transition_policy/readiness_policy/failure/human_control`。
- `backend/graph_system/context_materializer.py`
  - outbound edge policy 只暴露 contract 中的 packet、scheduler、reliability、trace；
  - edge contract 上下文 authority 改为 `graph_system.compiled_edge_contract_context`；
  - 删除不再使用的旧 edge 字段推断 helper。
- `backend/graph_system/loop.py`
  - 改用 `edge_contract_for_edge()`。
- `backend/task_system/graph_instances/edge_control_service.py`
  - human edge control policy 改用 `edge_contract_for_edge()`。
- `backend/task_system/compiler/edge_contract_models.py`
  - 新编译产物不再生成 `legacy_edge_type` 与 `legacy_protocol_projection`。

验证：

```text
rg -n 'edge_contract_or_projection|legacy_protocol_projection|legacy_edge_type|_legacy_edge_delivers_flow_packet|FLOW_PACKET_EDGE_TYPES' backend -g '*.py'
  no matches

python -m compileall backend/graph_system/edge_contracts.py backend/graph_system/flow_packet.py backend/graph_system/state_machine.py backend/graph_system/transition_processor.py backend/graph_system/context_materializer.py backend/graph_system/loop.py backend/task_system/graph_instances/edge_control_service.py backend/task_system/compiler/edge_contract_models.py
  passed

real graph config smoke:
  configs_checked 131
  edges_checked 415
  flow_edges 415
  state_only_edges 0

compiler smoke:
  contract_id edge-contract:edge.smoke
  protocol_kind node_handoff
  has_legacy_protocol_projection False
  has_legacy_edge_type False

fixed port smoke after backend restart:
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:8003/api/harness/run-monitor?limit=3 -> 200 payload
```

结论：通过。GraphSystem 的边协议运行语义已经收束到 compiled edge contract；运行时不再保留旧 edge projection / legacy flow packet fallback。后续若发现缺 contract 的图，应回到发布/编译链修复配置，而不是在运行时补猜。

### Stage F45：GraphRuntime envelope contract_index 移除 protocol index 运行时传播

目标：

```text
GraphRuntimeEnvelope.contract_index 应只携带运行期需要锁定和引用的 compiled contract。
node_protocol_index / edge_protocol_index 是发布期协议对齐材料，不能在 runtime contract_index 中继续表现为运行契约 authority。
```

权威链检查：

- 符合：F44 后 GraphSystem 执行链已经只读取 `edge_contract_index`。
- 符合：`node_protocol_index / edge_protocol_index` 仍保存在 `ExecutableGraphConfig.contracts` 中，供发布诊断、编译审计和历史 config 追踪。
- 问题：`backend/graph_system/runtime.py::_contract_index()` 仍把 `node_protocol_index / edge_protocol_index` 放进 `GraphRuntimeEnvelope.contract_index` 和 graph run 创建事件。
- 裁决：runtime envelope 是运行时锁定包，不是发布期诊断包；protocol index 不再向 runtime envelope 传播。

修正点：

- `backend/graph_system/runtime.py`
  - `_contract_index()` 删除 `node_protocol_index / edge_protocol_index`；
  - 保留 `node_contract_index / resource_contract_index / edge_contract_index / compile_report / deployment_package / graph_binding_contract / maintenance_contract / system_node_contract_index / configurator_write_contract`。

验证：

```text
python -m compileall backend/graph_system/runtime.py
  passed

runtime contract_index smoke with real graph config:
  has_node_protocol_index False
  has_edge_protocol_index False
  has_node_contract_index True
  has_edge_contract_index True
  authority graph_system_runtime.contract_index

fixed port smoke after backend restart:
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:8003/api/harness/run-monitor?limit=1 -> authority harness.run_monitor, total 1
```

结论：通过。GraphRuntimeEnvelope 的 contract_index 现在只表达运行期 compiled contract；发布期 protocol index 不再被运行包携带为执行契约。

### Stage F46：GraphSystem 扩展注册权威移出核心默认业务模块列表

目标：

```text
GraphSystem 只提供通用 adapter / provider / handler registry。
项目网络任务包与写作图任务包的默认扩展列表属于 task/application 组合层，不属于 GraphSystem 核心。
```

权威链检查：

- 符合：F44 / F45 后 GraphSystem 运行主链已不再读取项目网络领域协议。
- 问题：`graph_system.adapter_registry / context_provider_registry / runtime_effect_registry` 内部仍硬编码 `project_network_tasks.*` 与 `task_system.writing_graphs.*` 默认模块。
- 问题：`graph_system.memory_candidate_registry / work_order_handler_registry / quality_gate_registry / revision_signal_registry` 内部仍硬编码写作图 handler 模块。
- 裁决：registry 可以拥有“加载指定模块”的机制，但不能拥有“哪些业务包默认加载”的领域判断。默认业务扩展目录应由 `task_system.graph_extensions` 作为组合层统一加载。

修正点：

- `backend/graph_system/adapter_registry.py`
  - 删除 `_DEFAULT_MODULES` 与自动默认加载；
  - 新增 `load_runtime_algorithm_adapter_module(s)`。
- `backend/graph_system/context_provider_registry.py`
  - 删除 `_DEFAULT_MODULES` 与自动默认加载；
  - 新增 `load_graph_context_provider_module(s)`。
- `backend/graph_system/runtime_effect_registry.py`
  - 删除 `_DEFAULT_MODULES` 与自动默认加载；
  - 新增 `load_runtime_algorithm_effect_module(s)`。
- `backend/graph_system/memory_candidate_registry.py`
  - 删除写作图默认 handler 模块；
  - 新增 `load_memory_candidate_payload_handler_module(s)`。
- `backend/graph_system/work_order_handler_registry.py`
  - 删除写作图默认 handler 模块；
  - 新增 `load_deterministic_work_order_handler_module(s)`。
- `backend/graph_system/quality_gate_registry.py`
  - 删除写作图默认 handler 模块；
  - 新增 `load_quality_gate_handler_module(s)`。
- `backend/graph_system/revision_signal_registry.py`
  - 删除写作图默认 handler 模块；
  - 新增 `load_revision_signal_handler_module(s)`。
- `backend/task_system/graph_extensions.py`
  - 新增 task/application 组合层扩展目录；
  - 统一加载写作图 runtime adapter / context provider / memory candidate / deterministic handler / quality gate / revision signal；
  - 统一加载 project network runtime adapter / context provider / runtime effect。
- `backend/harness/entrypoint/runtime_facade.py`
  - 在构建 `AgentRuntimeServices` 和 `GraphSystem` 前调用 `ensure_task_graph_extensions_loaded()`。
- `backend/harness/runtime/services.py`
  - `AgentRuntimeServices.from_runtime_host()` fallback 路径也加载 task graph extensions，避免 engagement fallback GraphSystem 丢扩展。

验证：

```text
rg -n 'project_network_tasks|task_system\.writing_graphs|project_network_system' backend/graph_system backend/harness backend/task_system/graph_extensions.py -g '*.py'
  only backend/task_system/graph_extensions.py contains the domain extension module list

rg -n '_DEFAULT_MODULES|_ensure_default_modules_loaded|task_system\.writing_graphs|project_network_tasks' backend/graph_system -g '*.py'
  only generic importlib.import_module(normalized) loaders remain; no default domain module list

python -m compileall backend/graph_system backend/task_system/graph_extensions.py backend/harness/entrypoint/runtime_facade.py backend/harness/runtime/services.py
  passed

extension loader smoke:
  adapters ['project_network_work_product', 'writing_iteration']
  structured_keys ['project_network_semantic_submissions']
  providers ['project_network_context', 'writing_graph_context']
  effect_handlers ['project_network_work_product_ingest']
  memory_handlers ['writing_review_memory_candidates']
  work_order_handlers ['writing_progress_receipt_router']
  quality_handlers ['writing_stage_business_acceptance']
  revision_handlers ['writing_review_verdict_revision_signal']
  revision_patch_handlers ['writing_chapter_revision_requeue_patch']

fixed port smoke after backend restart:
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:8003/api/harness/run-monitor?limit=1 -> authority harness.run_monitor, total 1
```

结论：通过。GraphSystem 核心 registry 不再持有项目网络或写作图业务模块默认列表；业务扩展加载权威转移到 `task_system.graph_extensions` 组合层。GraphSystem 仍提供通用注册表和加载指定模块的能力。

### Stage F47：Run Monitor TurnRun 身份不再从 TaskRun 字段反推

目标：

```text
ActiveTurn / TurnRun 的公开监控协议必须显式使用 turn_run_id / monitor_item_id。
run monitor signal、detail_ref、fact scope 不再把 task_run_id=turnrun:* 当作兼容入口。
```

权威链检查：

- 符合：`ActiveTurnRecord` 的身份权威是 `turn_id / turn_run_id / stream_run_id`，不是 `TaskRun`。
- 符合：`RunMonitorProjector` 只负责投影，不应通过字符串前缀把一个字段解释成另一种运行实体。
- 符合：`TaskRun` 继续表示真实任务运行；`TurnRun` 继续表示单回合运行。
- 符合：前端详情入口按 `detail_ref.kind` 与显式 `turn_run_id` 选择 TurnRun 详情，不再从 `task_run_id` 兜底。

逻辑检查：

- `backend/harness/runtime/run_monitor/signals.py`
  - `source_kind=turn_run` 只来自 `execution_runtime_kind=single_agent_turn` 或显式 `turn_run_id`；
  - `detail_ref.kind=turn_run` 只来自显式 `turn_run_id`；
  - 删除 `task_run_id.startswith("turnrun:")` 的兼容识别。
- `backend/harness/runtime/run_monitor/projector.py`
  - active turn fact / trace / diagnostic 查询显式传 `turn_run_id`；
  - `_fact_scope_ref()` 的 turn_run scope 中 `task_run_id=""`，`turn_run_id` 单独保留；
  - `_fact_records_for_scope()` 不再从 `task_run_id` 字符串前缀分流。
- `frontend/src/lib/run-monitor/reducer.ts`
  - `signalDetailTurnRunId()` 只读取 `detail_ref.turn_run_id` 或 `signal.turn_run_id`；
  - 不再用 `detail_ref.task_run_id / signal.task_run_id` 作为 TurnRun fallback。

验证：

```text
python -m compileall backend/harness/runtime/run_monitor/projector.py backend/harness/runtime/run_monitor/signals.py
  passed

npx tsc --noEmit --pretty false
  passed in frontend/

rg -n 'task_run_id.*turnrun|turnrun.*task_run_id|detail\?\.task_run_id \|\| signal\?\.task_run_id|startswith\("turnrun:|startswith\('turnrun:' backend/harness/runtime/run_monitor frontend/src/lib/run-monitor frontend/src/components/layout frontend/src/components/workspace/views/task-system/runs -g '*.py' -g '*.ts' -g '*.tsx'
  no matches

active turn projection smoke:
  item_task_run_id ''
  item_turn_run_id 'turnrun:smoke'
  scope.scope_kind 'turn_run'
  scope.task_run_id ''
  scope.turn_run_id 'turnrun:smoke'
  signal_task_run_id ''
  signal_turn_run_id 'turnrun:smoke'
  detail_ref.kind 'turn_run'

fixed port smoke after backend restart:
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:8003/api/harness/run-monitor?limit=5 -> 200 payload
  openapi contains /api/harness/run-monitor/turn-runs/{turn_run_id} -> True
  openapi contains /api/harness/run-monitor/task-runs/{task_run_id} -> True
```

结论：通过。ActiveTurn/TurnRun 在 run monitor 的公开身份和诊断 scope 已从 TaskRun 字段彻底拆开；如果后续出现 `task_run_id=turnrun:*`，系统不会再把它静默解释成 TurnRun，应回到产生该字段的上游修正。

### Stage F48：图任务单节点真实运行与 GraphNodeTaskBinding 生命周期回退修复

目标：

```text
确认当前图任务系统不是只完成静态编译和 dispatch，而是能真实启动 GraphRun、派发 work order、通过 Harness 执行单 agent 节点、接受 NodeResult，并把结果回填到 TaskSystem episode/reducer。
同时修复实测暴露的 GraphNodeTaskBinding 生命周期状态回退。
```

权威链检查：

- 符合：`GraphSystem` 负责 GraphRun、checkpoint、ready/running/completed 状态、work order 派发和 NodeResult 接受。
- 符合：`Harness` 负责单 agent 节点执行，不保存图状态。
- 符合：`TaskSystem` 负责 graph node binding、task environment、episode、lease、episode result 和 work product。
- 问题：真实执行后 `TaskWorkEnvironment.status=completed`，但 `GraphNodeTaskBinding.status` 被 release 阶段重新写成 `bound`。
- 根因：`release_work_order_execution_lease()` 调用 `_ensure_work_order_state()`，而 `_ensure_work_order_state()` 内部的 `bind_work_order(... status="bound")` 会无条件 upsert binding，覆盖 `record_work_order_result()` 刚写入的 terminal status。
- 裁决：binding 的生命周期状态不能倒退。prepare/begin/release 可以幂等保证对象存在，但不能把 completed / completed_with_failure / aborted 写回 bound。

修正点：

- `backend/task_system/graph_bindings/service.py`
  - `bind_work_order()` 在 upsert 前读取已有 binding；
  - 新增 `_binding_status_without_regression()` 和 `_binding_status_rank()`；
  - 当已有 status 等级高于 requested status 时保留已有 status；
  - release 阶段再次 ensure state 时不会覆盖 completed binding。

验证：

```text
python -m compileall backend/task_system/graph_bindings/service.py
  passed

fixed backend restart:
  GET http://127.0.0.1:8003/health -> {"status":"ok"}

dispatch-only graph start:
  graph_id graph.project_network.directory.apix.v2.1.project.network.probe.20260702.092845.pndirframe.63a878ba76bb0249bd1c
  graph_run_id grun:graph_project_network_directory_apix_v2_1_project_network_probe_20260702_092845_pndirframe_63a878ba76bb0249bd1c:1783197840551
  graph_config_id ghcfg:graph_project_network_directory_apix_v2_1_project_network_probe_20260702_092845_pndirframe_63a878ba76bb0249bd1c:10c2c1462076720c
  work_order_count 1
  event_count 3

run-until-idle:
  status completed
  terminal_reason terminal_nodes_completed
  executed_work_order_count 1
  accepted_result_count 1
  active_node_work_order_count 0

TaskSystem reducer smoke:
  binding_count 1
  binding_status completed
  environment_status completed
  environment_step completed
  task_kind graph_node
  task_event_types:
    graph_node_task_prepared
    graph_node_execution_lease_acquired
    graph_node_task_result_recorded
    graph_node_execution_lease_released
  episode_result status completed
  work_product_count 1
  work_product product_domain graph_node
  work_product product_kind node_result
  work_product status candidate

graph monitor:
  status completed
  ready_count 0
  running_count 0
  completed_count 1
  failed_count 0
  blocked_count 0
  active_work_order_count 0
```

结论：通过。图任务系统当前可以真实运行至少一个项目网络单节点 agent graph，并完成 GraphSystem -> Harness -> TaskSystem reducer 的闭环。实测发现并修复了 binding 生命周期回退；新的 graph run 在 release 后保持 `GraphNodeTaskBinding.status=completed`。

### Stage F49：旧 TaskRun executor 状态语义清理

目标：

```text
旧 task_executor / task_executor_scheduled 不再作为前端门控、公开投影、恢复动作、trace run_kind 或测试样本中的有效运行实体。
后台任务交接的当前公共状态统一表达为 waiting_executor；真实任务运行实体使用 task_run / single_agent_task / graph_node / task_graph 等现行语义。
```

权威链检查：

- 符合：`Harness` 是单 agent 运行权威，但不再暴露旧 `task_executor` 实体名。
- 符合：`TaskSystem` 负责任务环境与恢复动作；恢复样本不再使用 `rerun_task_executor`。
- 符合：前端 active turn gate 只根据当前公开状态判断是否保留或释放，不再为旧 `task_executor_scheduled` 做特殊分支。
- 符合：trace/observability 测试继续保护观测摘要不泄露 raw payload，但 run_kind 样本改为现行 `task_run`。

修正点：

- `frontend/src/lib/runtimeStatusText.ts`
  - 删除 `task_executor_scheduled` 状态标签。
- `frontend/src/lib/store/events.ts`
  - 删除 `task_executor_scheduled` 不释放 gate 的特殊判断；
  - 删除从旧 terminal reason 推断 `waiting_executor` 的兜底。
- `frontend/src/lib/store/runtime.test.ts`
  - 后台任务交接测试样本改为 `waiting_executor`；
  - runtime event 样本 step 从旧 `task_executor_started` 改为通用 `agent_runtime_started`。
- `backend/tests/public_projection_contract_test.py`
  - 删除已不存在的 `_is_task_executor_handoff_terminal` 导入和旧 handoff helper 测试。
- `backend/tests/health_governance_token_usage_test.py`
  - 恢复动作样本从 `rerun_task_executor` 改为 `resume_task_run`。
- `backend/tests/runtime_trace_monitor_projection_test.py`
- `backend/tests/runtime_trace_api_test.py`
- `backend/tests/runtime_observability_kernel_test.py`
  - trace run_kind 样本从 `task_executor` 改为 `task_run`。
- `backend/tests/tool_observation_ledger_regression.py`
  - evidence ref 从已删除的 `backend/harness/loop/task_executor.py` 改为真实存在的 `backend/harness/loop/single_agent_turn.py`。
- `backend/tests/app_runtime_recovery_test.py`
  - 测试函数名从 recovered task executors 改为 recovered task runs。

验证：

```text
rg -n "task_executor|task_executor_scheduled|_is_task_executor_handoff_terminal|rerun_task_executor|TaskRunExecutor|execute_task_run|_create_graph_node_task_run" backend frontend/src -g "*.py" -g "*.ts" -g "*.tsx"
  no matches

python -m compileall backend/tests/app_runtime_recovery_test.py backend/tests/tool_observation_ledger_regression.py backend/tests/runtime_trace_monitor_projection_test.py backend/tests/runtime_trace_api_test.py backend/tests/runtime_observability_kernel_test.py backend/tests/public_projection_contract_test.py backend/tests/health_governance_token_usage_test.py
  passed

npx tsc --noEmit --pretty false
  passed in frontend/
```

结论：通过。旧 TaskRun executor 作为运行实体、状态、恢复动作和测试样本的残留已经归零；后续任务运行语义应从 TaskSystem task run / work environment、GraphSystem work order、Harness single-agent execution 三条权威线显式表达。

### Stage F50：旧 active TaskRun 请求字段与 pause 控制契约残留清理

目标：

```text
前端和控制契约不再保留 expected_task_run_id / legacy_task_pause_removed 这类旧 active TaskRun steer 入口。
Chat interrupt 只用 active turn 坐标校验当前回合；pause_for_user_steer 归入 current work control 语义，而不是旧 task pause 语义。
```

权威链检查：

- 符合：后端 `ChatRunInterruptRequest` 已经只接受 `expected_active_turn_id`，且 `extra="forbid"`；前端继续发送 `expected_task_run_id` 会造成真实 422。
- 符合：当前可暂停/停止的对象应由 `CurrentWorkBoundaryReceipt` 和 `active_work_control` 表达，不应通过旧 task pause 文案描述。
- 符合：`task_run_id` 仍可作为 TaskRun / GraphRun root 运行日志坐标，但不能作为 active turn interrupt 请求的期望字段。

修正点：

- `frontend/src/lib/store/runtime.ts`
  - `interruptChatRunForResume()` 不再向 `/chat/runs/{stream_run_id}/interrupt` 发送 `expected_task_run_id`。
- `frontend/src/lib/api/types.ts`
  - `ChatRunInterruptPayload` 删除 `expected_task_run_id`。
- `frontend/src/lib/store/runtime.test.ts`
  - 删除旧字段 undefined 断言，避免测试索引继续保留废弃字段名。
- `backend/harness/runtime/control_action_schema.py`
  - `pause_for_user_steer.executor_ref` 改为 `harness.entrypoint.runtime_facade.current_work_control`；
  - public projection / commit policy 改为 active work control 语义；
  - 删除 `legacy_task_pause_removed` 与旧 task pause projection 文案。

验证：

```text
rg -n "expected_task_run_id" backend frontend/src -g "*.py" -g "*.ts" -g "*.tsx"
  no matches

rg -n "legacy_task_pause_removed|task_pause_public_projection|legacy_task_pause_removed_visible_status" backend frontend/src -g "*.py" -g "*.ts" -g "*.tsx"
  no matches

python -m compileall backend/harness/runtime/control_action_schema.py
  passed

npx tsc --noEmit --pretty false
  passed in frontend/
```

结论：通过。active turn interrupt 和 current work pause 控制契约不再通过旧 TaskRun steer 字段或旧 pause executor 文案表达；后续如果需要约束任务运行，应走 TaskWorkEnvironment / CurrentWorkBoundary / GraphRun 显式控制面。

### Stage F51：TaskGraphRepository 旧根聚合文件清理

目标：

```text
TaskGraphDefinition 的存储权威只保留目录化 graph store。
旧 storage/tasks/task_graphs.json 不再作为读取源、维护目标或配置脚本输出目标。
```

权威链检查：

- 符合：`TaskGraphRepository` 是 TaskSystem 内图定义仓库入口，应该只读写当前目录化 graph store。
- 符合：`GraphSystem` 消费 task graph definition，不关心旧存储迁移形态。
- 符合：配置脚本只通过仓库 API 删除托管 writing graph，不直接读写根聚合文件。
- 符合：旧聚合文件已通过目录覆盖检查确认内容存在于 `storage/tasks/task_graphs/*/graph.json`，删除后不会丢失当前 graph definition。

修正点：

- `backend/task_system/repositories/task_graph_repository.py`
  - 删除 `LEGACY_TASK_GRAPHS_FILE` 和 `_legacy_graphs()`；
  - `list()` 不再合并旧根聚合文件；
  - 新增 `delete(graph_id)`，供配置脚本按仓库权威删除 graph definition。
- `scripts/configure_writing_modular_novel_graph.py`
  - `_delete_managed_graph_runtime_records()` 通过 `TaskGraphRepository.delete()` 删除托管 writing graph；
  - 删除直接读写 `task_graphs.json` 的旧逻辑。
- `backend/scripts/maintain_runtime_artifacts.py`
  - `FORMAL_TASK_FILES` 不再把 `task_graphs.json` 当作正式任务仓库文件。
- `backend/tests/json_repository_resilience_test.py`
- `backend/tests/task_storage_snapshot_partition_test.py`
  - 测试样本改为仍然存在的 registry 文件，避免测试继续保护已删除的旧聚合文件形态。
- `storage/tasks/task_graphs.json`
  - 删除旧根聚合文件。

验证：

```text
rg -n "task_graphs\.json|LEGACY_TASK_GRAPHS_FILE|_legacy_graphs" backend scripts -g "*.py" -g "*.ts" -g "*.tsx"
  no matches

python -m compileall backend/task_system/repositories/task_graph_repository.py scripts/configure_writing_modular_novel_graph.py backend/scripts/maintain_runtime_artifacts.py backend/tests/json_repository_resilience_test.py backend/tests/task_storage_snapshot_partition_test.py
  passed

TaskGraphRepository smoke from backend/:
  graph_count 124
  has_graph_000001 True
  has_writing_master True
  legacy_file_exists False
```

结论：通过。Task graph definition 的旧根聚合存储入口已经退出运行主链；后续 graph definition 的增删改查都应通过目录化 `TaskGraphRepository` 完成，不再恢复 `storage/tasks/task_graphs.json`。

### Stage F52：图运行语义中的旧命名权威清理

目标：

```text
GraphSystem / TaskSystem 的新运行语义不再用 legacy 命名承载当前诊断或策略入口。
旧字段仍可被诊断为“已被运行语义取代”，但不再表现为一个仍有效的 legacy 主链。
```

权威链检查：

- 符合：`task_system.runtime_semantics` 的职责是编译当前图运行语义 manifest，不是继续保存旧 timeline / sequence / temporal 字段权威。
- 符合：`GraphSystem` 的输出策略解析从 contract binding 和 node artifact policy 派生，不应用 legacy 函数名表达当前策略。
- 符合：保留诊断能力，但诊断命名改为 `superseded`，表示这些字段只作为迁移和审查信号，不参与图调度裁决。

修正点：

- `backend/task_system/runtime_semantics/models.py`
  - `RuntimeSemanticsManifest.legacy_fields` 改为 `superseded_fields`；
  - `to_dict()` 输出 `superseded_fields`，不再输出 `legacy_fields`。
- `backend/task_system/runtime_semantics/compiler.py`
  - `_legacy_*_diagnostics()` 改为 `_superseded_*_field_diagnostics()`；
  - `legacy_field_count` 改为 `superseded_field_count`；
  - 相关 diagnostic code 和 authority 从 legacy 命名改为 superseded / not-runtime-authority 命名。
- `backend/graph_system/output_policy.py`
  - `_legacy_artifact_output_policy()` 改为 `_artifact_output_policy_from_contract_bindings()`，表达其真实职责。

验证：

```text
python -m compileall backend/task_system/runtime_semantics/compiler.py backend/task_system/runtime_semantics/models.py
  passed

python -m compileall backend/graph_system/output_policy.py
  passed

rg -n "legacy_fields|legacy_field_count|runtime_semantics_legacy_field|_legacy_graph_diagnostics|_legacy_node_diagnostics|_legacy_edge_diagnostics|_legacy_field_payloads|sequence_index_legacy_lifecycle_coordinate|timeline_group_legacy_display|edge_temporal_semantics_legacy_projection|legacy_timeline_policy_not_runtime_semantics" backend/task_system/runtime_semantics backend frontend/src scripts -g "*.py" -g "*.ts" -g "*.tsx"
  no matches
```

结论：通过。图运行语义层仍能发现旧配置噪声，但不再把它命名为可依赖的 legacy 运行主链；后续图任务语义应以 `node_semantics`、`edge_semantics`、`superseded_fields` 和 diagnostics 明确区分当前权威与被取代字段。

### Stage F53：Harness 内核中的图任务扩展隐式注册清理

目标：

```text
单 agent runtime service table 不再负责加载 graph task 业务扩展。
图任务扩展注册只保留在应用组合入口，避免 Harness 内核拥有业务插件装配权威。
```

权威链检查：

- 符合：`Harness` 是单 agent 执行权威，不应该在 `AgentRuntimeServices.from_runtime_host()` 中隐式注册 writing/project-network 图任务扩展。
- 符合：`task_system.graph_extensions` 是图任务扩展组合层，负责把业务 adapter/context/effect handler 注册进 GraphSystem registry。
- 符合：当前 `HarnessRuntimeFacade` 在创建 `GraphSystem` 前调用 `ensure_task_graph_extensions_loaded()`，仍保留应用组合时机，不影响图任务运行能力。

修正点：

- `backend/harness/runtime/services.py`
  - 删除 `from_runtime_host()` 内部对 `ensure_task_graph_extensions_loaded()` 的 import 和调用。

验证：

```text
python -m compileall backend/harness/runtime/services.py backend/harness/entrypoint/runtime_facade.py backend/task_system/graph_extensions.py
  passed

rg -n "ensure_task_graph_extensions_loaded\(" backend -g "*.py"
  backend/task_system/graph_extensions.py:45:def ensure_task_graph_extensions_loaded() -> None
  backend/harness/entrypoint/runtime_facade.py:148:        ensure_task_graph_extensions_loaded()
```

结论：通过。Harness 内核不再偷偷装配图任务扩展；图任务扩展仍由当前应用 runtime facade 作为组合点统一加载。后续如需进一步把组合入口从 `harness.entrypoint.runtime_facade` 外提，应作为应用启动层重构单独处理。

### Stage F54：ProjectNetworkTasks 目录运行适配层职责说明校准

目标：

```text
project_network_tasks 的 directory runtime service 只表达“发布图配置、准备启动输入、登记结果”的任务适配职责。
不再用文案暗示它可以启动 GraphSystem run 或执行 agent。
```

权威链检查：

- 符合：`ProjectNetworkTasks` 是项目网络建图/修复的图任务适配层，可以生成 task graph、发布 graph config、准备 start inputs。
- 符合：`GraphSystem` 才拥有 GraphRun 启动、调度、resume 和 work order execution 权威。
- 符合：`Harness` 才执行单 agent 节点。
- 符合：`ProjectNetworkSystem` 才保存语义资产和维护信号。

修正点：

- `backend/project_network_tasks/directory_runtime_service.py`
  - class docstring 从 “Connects directory render frames to GraphSystem execution / start GraphSystem runs” 改为 “Prepares directory render frames for graph-task execution”；
  - 明确该 service 不启动 GraphSystem runs、不执行 agents、不判断语义事实、不发布 semantic overlay records。

验证：

```text
python -m compileall backend/project_network_tasks/directory_runtime_service.py
  passed

rg -n "start GraphSystem runs|does not start GraphSystem|Prepares directory render frames" backend/project_network_tasks/directory_runtime_service.py
  backend/project_network_tasks/directory_runtime_service.py:30:    """Prepares directory render frames for graph-task execution.
```

结论：通过。ProjectNetworkTasks 的 directory runtime service 说明已经与实际实现和分层权威一致；后续如果需要启动 graph run，应走 GraphSystem / application facade，不应把启动权威塞回项目网络任务适配层。

### Stage F55：ProjectNetwork shard 资产模型中的执行配置下沉清理

目标：

```text
ProjectNetworkSystem 的 ShardPlan / SemanticShardSpec 只保存语义分片、输入、产物契约、复杂度和依赖。
agent_id / agent_profile_id / agent_group_id / executor_policy 不再作为项目网络资产字段保存，而由 ProjectNetworkTasks 的节点模板在物化 task graph node 时提供。
```

权威链检查：

- 符合：`ProjectNetworkSystem` 是项目控制网络资产权威，不应保存具体 agent 执行配置。
- 符合：`ProjectNetworkTasks` 的 template catalog 是图任务实例化层，负责把语义分片物化为带 agent/profile/executor policy 的 graph node。
- 符合：节点显式承接 agent 配置；shard 只表达“审查什么/需要什么输入/产出什么契约”。
- 符合：已有模板仍为 `project_network.module_index` 等节点提供 reviewer / aggregator / curator profile。

修正点：

- `backend/project_network_system/shard_models.py`
  - 删除 `ShardExecutorPolicy` 与 `ShardWorkPosture`；
  - `SemanticShardSpec` 删除 `executor_policy` 字段，`from_dict()` 忽略旧输入中的 executor policy，`to_dict()` 不再输出。
- `backend/project_network_system/__init__.py`
  - 不再导出 `ShardExecutorPolicy`。
- `backend/project_network_tasks/template_catalog.py`
  - `ProjectNetworkNodeTemplate.materialize_node()` 只使用模板自身的 `agent_id`、`agent_profile_id`、`agent_group_id`、`work_posture`、`executor_policy`。
- `backend/project_network_tasks/shard_planner.py`
  - 不再从 layer metadata 读取 executor policy 注入 shard asset。
- `backend/project_network_tasks/graph_builder.py`
  - 文件模块 shard 不再内嵌 reviewer agent policy；由 `project_network.module_index` 模板提供。

验证：

```text
python -m compileall backend/project_network_system/shard_models.py backend/project_network_system/__init__.py backend/project_network_tasks/template_catalog.py backend/project_network_tasks/shard_planner.py backend/project_network_tasks/graph_builder.py
  passed

rg -n "ShardExecutorPolicy|executor_policy" backend/project_network_system backend/project_network_tasks -g "*.py"
  only project_network_tasks template/graph_builder executor policy remains; no project_network_system matches

materialize smoke from backend/:
  node_id pn.directory.frame.smoke.file.module.smoke
  agent_id agent:project_network_file_reviewer
  agent_group_id group.project_network_reviewers
  agent_profile_id project_network_file_reviewer_agent
  executor_policy_authority project_network_tasks.model_response_only_executor_policy
  shard_has_executor_policy False
```

结论：通过。ProjectNetwork shard asset 不再携带任务执行配置；agent/profile/executor policy 的权威落回 ProjectNetworkTasks 节点模板，符合“语义资产层 + 图任务实例层”分离。

### Stage F56：本轮重构聚合验证与固定端口后端 smoke

目标：

```text
确认 F51-F55 的存储、语义命名、扩展装配、项目网络任务适配和 shard 资产模型清理没有破坏后端启动与公开运行面。
```

验证：

```text
rg -n "ShardExecutorPolicy|task_graphs\.json|LEGACY_TASK_GRAPHS_FILE|_legacy_graphs|legacy_fields|runtime_semantics_legacy_field" backend scripts frontend/src -g "*.py" -g "*.ts" -g "*.tsx"
  no matches

rg -n "from task_system\.project_network|import task_system\.project_network|task_system/project_network|task_system\\project_network" backend scripts frontend/src -g "*.py" -g "*.ts" -g "*.tsx"
  no matches

python -m compileall backend/project_network_system backend/project_network_tasks backend/task_system/runtime_semantics backend/harness/runtime/services.py backend/harness/entrypoint/runtime_facade.py backend/task_system/graph_extensions.py backend/task_system/repositories/task_graph_repository.py backend/graph_system/output_policy.py
  passed

fixed backend restart:
  stopped old project backend process on 127.0.0.1:8003
  started C:\Users\admin\.conda\envs\agent\python.exe run_uvicorn.py --host 127.0.0.1 --port 8003
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:8003/api/harness/run-monitor?limit=3 -> 200, keys authority/revision/updated_at/summary/primary/attention/recent/projects/signals/management
  GET http://127.0.0.1:8003/openapi.json -> 246 paths
  graph/task paths present:
    /api/graph-system/graph-runs/{graph_run_id}
    /api/graph-system/task-graphs/{graph_id}/start
    /api/graph-system/graph-runs/{graph_run_id}/run-until-idle
    /api/graph-system/graph-runs/{graph_run_id}/work-orders/execute
    /api/task-environments
    /api/tasks/overview

git diff --check on changed core refactor paths:
  passed; only CRLF normalization warnings
```

结论：通过。本轮清理后的后端可以在固定 `127.0.0.1:8003` 启动并暴露 graph/task/harness 公开面；下一阶段可以继续围绕 GraphRun root TaskRun 关系、runtime facade 应用组合外提、或任务环境底座接口继续收口。

### Stage F57：图任务扩展装配从 HarnessRuntimeFacade 外提到应用组合层

目标：

```text
graph task extension loader 不再由 HarnessRuntimeFacade 调用。
应用启动层负责装配 writing/project-network 图任务扩展；任务系统中独立创建 GraphSystem 的入口显式装配扩展。
```

权威链检查：

- 符合：`HarnessRuntimeFacade` 是单 agent runtime 的 API adapter，不应拥有 graph task 业务扩展装配权威。
- 符合：`bootstrap.app_runtime` 是应用组合入口，适合在创建 Harness / GraphSystem 前加载 task graph extension registries。
- 符合：`task_system.engagement.dispatcher` 在脱离 app runtime、独立从 `runtime_host` 创建 `GraphSystem` 时，属于任务系统组合入口，应显式加载扩展。
- 符合：`GraphSystem` core registry 仍不自动 import 业务模块；扩展仍通过 `task_system.graph_extensions` 统一注册。

修正点：

- `backend/bootstrap/app_runtime.py`
  - 在 refresh skills/tools registry 后、创建 `HarnessRuntimeFacade` 前调用 `ensure_task_graph_extensions_loaded()`。
- `backend/harness/entrypoint/runtime_facade.py`
  - 删除 `task_system.graph_extensions` import；
  - 删除 `HarnessRuntimeFacade.__init__()` 内部 loader 调用。
- `backend/task_system/engagement/dispatcher.py`
  - `_graph_system_from_runtime_host()` 在需要创建独立 `GraphSystem` 时调用 `ensure_task_graph_extensions_loaded()`；
  - 已挂载 `runtime_host.graph_system` 时直接复用，不重复干预。

验证：

```text
python -m compileall backend/bootstrap/app_runtime.py backend/harness/entrypoint/runtime_facade.py backend/task_system/engagement/dispatcher.py backend/task_system/graph_extensions.py
  passed

rg -n "ensure_task_graph_extensions_loaded\(" backend -g "*.py"
  backend/bootstrap/app_runtime.py:53:        ensure_task_graph_extensions_loaded()
  backend/task_system/engagement/dispatcher.py:190:    ensure_task_graph_extensions_loaded()
  backend/task_system/graph_extensions.py:45:def ensure_task_graph_extensions_loaded() -> None

graph extension registry smoke from backend/:
  adapters ['project_network_work_product', 'writing_iteration']
  providers ['project_network_context', 'writing_graph_context']
  effects ['project_network_work_product_ingest']

fixed backend restart:
  stopped old project backend process on 127.0.0.1:8003
  started C:\Users\admin\.conda\envs\agent\python.exe run_uvicorn.py --host 127.0.0.1 --port 8003
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:8003/api/harness/run-monitor?limit=3 -> 200
  GET http://127.0.0.1:8003/openapi.json -> 246 paths
  graph/task paths present:
    /api/graph-system/task-graphs/{graph_id}/start
    /api/graph-system/graph-runs/{graph_run_id}/run-until-idle
    /api/graph-system/graph-runs/{graph_run_id}/work-orders/execute
    /api/task-environments

git diff --check on changed F57 paths:
  passed; only CRLF normalization warnings
```

结论：通过。图任务扩展装配已经从 HarnessRuntimeFacade 外提到应用/任务组合入口；Harness entrypoint 不再知道 graph task extension loader，GraphSystem core 也没有自动加载业务模块。

### Stage F58：GraphRun root TaskRun anchor 显式化迁移准备

目标：

```text
GraphRun / GraphRuntimeEnvelope / GraphLoopState 的根 TaskRun 锚点显式暴露为 root_task_run_id / graph_root_task_run_id。
迁移期保留 task_run_id 字段，但公开响应、monitor、删除生命周期不再各自猜测 task_run_id 的语义。
```

权威链检查：

- 符合：`GraphSystem` 仍是 GraphRun 与 graph root TaskRun 的生命周期权威。
- 符合：`GraphRun.task_run_id` 暂时仍作为迁移期存储字段；但 API / monitor / graph slot identity 已显式暴露 root anchor alias。
- 符合：`GraphNodeWorkOrder.task_run_id` 和 `NodeResultEnvelope.task_run_id` 暂不在本阶段重命名，避免一次性波及 event log、checkpoint、runner、work order executor 和前端监控。
- 符合：root anchor 解析规则收敛到 `graph_system.models.resolve_graph_root_task_run_id()`，facade / lifecycle / harness 删除入口不再各自实现 fallback。

修正点：

- `backend/graph_system/models.py`
  - 新增 `resolve_graph_root_task_run_id()`，优先读取显式 root alias，再回退迁移期 `task_run_id`；
  - `GraphRuntimeEnvelope.to_dict()`、`GraphRun.to_dict()`、`GraphLoopState.to_dict()` 输出 `root_task_run_id` 和 `graph_root_task_run_id`；
  - `GraphRun.from_dict()`、`GraphLoopState.from_dict()` 使用统一解析函数。
- `backend/graph_system/runtime.py`
  - 图启动时在 root TaskRun diagnostics、GraphRun diagnostics、runtime scope、memory namespace 和 namespace template 中加入 root anchor aliases。
- `backend/graph_system/facade.py`
  - pause / resume event payload、run control response、graph run monitor、loop state public view、work order public view 输出 root anchor aliases；
  - `_require_graph_root_task_run()` 使用统一解析函数。
- `backend/graph_system/lifecycle_manager.py`
  - 删除本地 root task fallback helper，统一走模型层解析。
- `backend/harness/runtime/task_record_lifecycle.py`
  - graph root task 删除判定改为读取 graph run + checkpoint 的统一 root anchor。
- `backend/graph_system/context_materializer.py`
  - graph node execution slot 的 `graph_identity` 增加 `graph_root_task_run_id`。

验证：

```text
python -m compileall backend/graph_system/models.py backend/graph_system/runtime.py backend/graph_system/facade.py backend/graph_system/lifecycle_manager.py backend/graph_system/context_materializer.py backend/harness/runtime/task_record_lifecycle.py
  passed

root anchor helper smoke from backend/:
  resolve_graph_root_task_run_id({'graph_root_task_run_id':'root:a','task_run_id':'old'}) -> root:a
  GraphRun.from_dict(... root_task_run_id='root:b' ...) -> root:b
  GraphLoopState.from_dict(... root_task_run_id='root:c' ...).to_dict()['graph_root_task_run_id'] -> root:c

rg -n -F 'graph_run.get("task_run_id"' backend/graph_system backend/harness -g "*.py"
  no matches

rg -n -F "graph_run.get('task_run_id'" backend/graph_system backend/harness -g "*.py"
  no matches

git diff --check on changed F58 paths:
  passed; only CRLF normalization warning on backend/graph_system/context_materializer.py

fixed backend restart:
  stopped old project backend process on 127.0.0.1:8003 when present
  started C:\Users\admin\.conda\envs\agent\python.exe backend/run_uvicorn.py --host 127.0.0.1 --port 8003 from backend/
  GET http://127.0.0.1:8003/health -> {"status":"ok"}
  GET http://127.0.0.1:8003/api/harness/run-monitor?limit=3 -> authority harness.run_monitor
  GET http://127.0.0.1:8003/openapi.json -> 246 paths
  graph/task paths present:
    /api/graph-system/task-graphs/{graph_id}/start
    /api/graph-system/graph-runs/{graph_run_id}
```

结论：通过。GraphRun root TaskRun anchor 已在模型、运行 scope、公开 monitor 和删除生命周期中显式化；后续如果继续推进，应分阶段把 node-level task execution truth 从 graph root anchor 中拆出，而不是直接删除 `task_run_id` 字段。

### Stage F59：GraphSystem 运行期 edge contract fail-closed 收口

目标：

```text
GraphSystem 运行期不再在 edge 缺少编译合同时，从 edge_type / scheduler_role / protocol_index 临时投影执行合同。
TaskSystem compiler 负责生成 edge_contract_index；GraphSystem 运行期只消费 compiled edge contract，缺失即失败。
```

权威链检查：

- 符合：`TaskSystem compiler` 是 graph config 合同生成权威，可以读取 node/edge protocol index 作为编译输入材料。
- 符合：`GraphSystem` 是运行期图调度权威，只应该读取 `edge_contract_index` 中的编译合同，不应该现场补合同。
- 符合：`FlowPacket` 的 payload 可见性、artifact ref、delivery、ack、packet type 都来自编译合同，避免运行期从旧 edge 字段二次推断。
- 符合：缺少 compiled edge contract 时直接抛错，是结构性配置错误，不再由旧 projection fallback 掩盖。

修正点：

- `backend/graph_system/edge_contracts.py`
  - `edge_contract_or_projection()` 改为 `edge_contract_for_edge()`；
  - 删除 `legacy_protocol_projection` fallback；
  - 缺少 `edge_id` 或 compiled edge contract 时 fail-closed。
- `backend/graph_system/flow_packet.py`
  - `edge_delivers_flow_packet()` 必须接收 `graph_config`；
  - 删除 `FLOW_PACKET_EDGE_TYPES` 和 `_legacy_edge_delivers_flow_packet()`；
  - packet type、contract id、target context、visible payload、artifact refs、ack policy 全部来自 compiled edge contract。
- `backend/graph_system/context_materializer.py`
  - outbound edge policy 改为读取 compiled edge contract；
  - 删除 `_edge_packet_contract_id()`、`_edge_source_output_selector()`、`_edge_target_context_key()`、`_edge_target_input_slot()` 等运行期投影 helper；
  - authority 从 `graph_system.edge_contract_projection` 改为 `graph_system.compiled_edge_contract_context`。
- `backend/task_system/compiler/edge_contract_models.py`
  - compiled edge contract 不再输出 `legacy_edge_type` 和 `legacy_protocol_projection`。

验证：

```text
python -m compileall backend/graph_system/edge_contracts.py backend/graph_system/flow_packet.py backend/graph_system/context_materializer.py backend/graph_system/state_machine.py backend/graph_system/transition_processor.py backend/graph_system/loop.py backend/task_system/compiler/edge_contract_models.py backend/task_system/compiler/graph_compiler.py backend/task_system/compiler/executable_graph_config_publisher.py
  passed

compiled edge contract smoke from backend/:
  build_graph_compilation_unit(...) -> edge_contract_index contains e1
  edge_contract_for_edge(compiled_cfg, e1)['authority'] -> task_system.compiled_edge_contract
  edge_contract_for_edge(compiled_cfg, e1)['packet']['target_context_key'] -> source_result
  edge_delivers_flow_packet(e1, graph_config=compiled_cfg) -> True
  edge_contract_for_edge(cfg_without_edge_contract_index, e1) -> ValueError: ExecutableGraphConfig missing compiled edge contract: e1

rg -n "edge_contract_or_projection|legacy_protocol_projection|legacy_edge_type|FLOW_PACKET_EDGE_TYPES|_legacy_edge_delivers_flow_packet|_edge_packet_contract_id|_target_context_key|_delivery_policy\(" backend/graph_system backend/task_system/compiler -g "*.py"
  no matches

git diff --check on changed F59 paths:
  passed; only CRLF normalization warning on backend/graph_system/context_materializer.py
```

结论：通过。图运行期 edge 合同已收束到 compiled contract；旧协议索引仍可作为 compiler 输入和诊断来源，但不再是 GraphSystem 运行期的隐式兜底执行规则。

### Stage F60：GraphSystem 扩展 registry 默认业务加载清理

目标：

```text
GraphSystem core registry 不再在 iter/apply/handle 时自动 import writing/project-network 业务模块。
所有图任务业务扩展统一由 task_system.graph_extensions 在应用/任务组合入口显式装配。
```

权威链检查：

- 符合：`GraphSystem` core registry 只保存已注册 extension，不拥有业务模块发现权威。
- 符合：`task_system.graph_extensions` 是图任务扩展组合层，统一声明 writing/project-network 的 adapter、context provider、effect、memory candidate、deterministic work order、quality gate、revision signal handler。
- 符合：`bootstrap.app_runtime` 和 `task_system.engagement.dispatcher` 是实际创建/组合 GraphSystem 的入口，负责调用 `ensure_task_graph_extensions_loaded()`。
- 符合：缺少扩展时 registry 不再偷偷加载默认模块；这会暴露组合入口漏接，而不是在 graph core 内部隐藏修复。

修正点：

- `backend/graph_system/adapter_registry.py`
- `backend/graph_system/context_provider_registry.py`
- `backend/graph_system/memory_candidate_registry.py`
- `backend/graph_system/quality_gate_registry.py`
- `backend/graph_system/revision_signal_registry.py`
- `backend/graph_system/runtime_effect_registry.py`
- `backend/graph_system/work_order_handler_registry.py`

上述 registry 删除 `_DEFAULT_MODULES` / `_ensure_default_modules_loaded()`，新增显式 `load_*_module(s)` 入口。

- `backend/task_system/graph_extensions.py`
  - 统一声明并加载七类图任务扩展模块。

验证：

```text
python -m compileall backend/graph_system/adapter_registry.py backend/graph_system/context_provider_registry.py backend/graph_system/memory_candidate_registry.py backend/graph_system/quality_gate_registry.py backend/graph_system/revision_signal_registry.py backend/graph_system/runtime_effect_registry.py backend/graph_system/work_order_handler_registry.py backend/task_system/graph_extensions.py backend/bootstrap/app_runtime.py backend/task_system/engagement/dispatcher.py
  passed

graph extension registry smoke from backend/:
  adapters ['project_network_work_product', 'writing_iteration']
  providers ['project_network_context', 'writing_graph_context']
  effects ['project_network_work_product_ingest']
  memory_handlers ['writing_review_memory_candidates']
  work_order_handlers ['writing_progress_receipt_router']
  quality_handlers ['writing_stage_business_acceptance']
  revision_handlers ['writing_review_verdict_revision_signal']
  revision_patch_handlers ['writing_chapter_revision_requeue_patch']

rg -n "_DEFAULT_MODULES|_DEFAULT_MODULES_LOADED|_ensure_default_modules_loaded|iter_.*\(\).*import_module|task_system\.writing_graphs|project_network_tasks\.runtime" backend/graph_system -g "*.py"
  no matches

git diff --check on changed F60 paths:
  passed; only CRLF normalization warnings
```

结论：通过。GraphSystem core registry 已从业务扩展自动加载中解耦，图任务扩展注册权威收敛到 TaskSystem 的组合入口。

### Stage F61：Run Monitor 中 active turn 与 TaskRun 隐式绑定清理

目标：

```text
普通 single-agent turn 的监控身份使用 turn_run_id / monitor_item_id。
不再把 turnrun:* 写入 task_run_id，也不再让前端把 turn_run 当成 task_run 打开日志或控制动作。
```

权威链检查：

- 符合：`TurnRun` 是普通 turn 的运行事实；`TaskRun` 是任务/图任务的运行事实，两者不能通过字符串前缀混用。
- 符合：run monitor 可以同时呈现 `task_run`、`turn_run`、`graph_run`，但 detail/log/action 必须按 source kind 分路。
- 符合：普通 active turn 不暴露 `pause_task / stop_task / close_runtime` 这类 TaskRun 控制动作；当前用户 steer/interrupt 应走 active work control / chat run interrupt 链路。
- 符合：前端运行日志打开时显式区分 `turn_run` 与 `task_run` scope。

修正点：

- `backend/harness/runtime/run_monitor/projector.py`
  - active turn monitor item 使用 `monitor_item_id = turn_run_id || stream_run_id || turn_id`；
  - active turn 的 `task_run_id` 和 `root_task_run_id` 置空；
  - fact / trace / diagnostic refs 支持 `turn_run_id` scope；
  - `_fact_scope_ref()` 增加 `turn_run_id` 字段，不再通过 `task_run_id.startswith("turnrun:")` 识别普通 turn。
- `backend/harness/runtime/run_monitor/signals.py`
  - signal 输出 `turn_run_id`、`stream_run_id`、`active_turn_id`、`monitor_item_id`；
  - detail_ref 显式区分 `turn_run` 和 `task_run`。
- `backend/harness/runtime/run_monitor/management.py`
  - source index 和 signal id 纳入 `monitor_item_id / turn_run_id`；
  - inspect 支持 turn_run；
  - 删除对 `pause_task / stop_task / close_runtime` 的 TaskRun 控制动作投影。
- `backend/harness/runtime/control_action_schema.py`
  - `pause_for_user_steer` 改为 current work control 语义，不再指向 legacy task pause removed。
- `frontend/src/lib/api/types.ts`
  - `RunMonitorSignal` 增加 `turn_run_id`、`stream_run_id`、`active_turn_id`、`monitor_item_id`；
  - chat interrupt payload 删除 `expected_task_run_id`。
- `frontend/src/lib/run-monitor/reducer.ts`、`frontend/src/lib/run-monitor/selectors.ts`
  - signal 查找/去重纳入 `monitor_item_id / turn_run_id`；
  - `signalDetailTurnRunId()` 不再从 `task_run_id` 猜 turn_run。
- `frontend/src/components/layout/RunMonitorPanel.tsx`
- `frontend/src/components/layout/RunTaskLane.tsx`
- `frontend/src/components/workspace/views/task-system/runs/RunManagementWorkbench.tsx`
  - 打开日志时根据 detail/source kind 选择 `turn_run` 或 `task_run` scope；
  - 删除 stop/close runtime 的旧 TaskRun 控制确认和 warning action 样式。
- `frontend/src/lib/store/events.ts`、`frontend/src/lib/store/runtime.ts`、`frontend/src/lib/runtimeStatusText.ts`
  - 删除 `task_executor_scheduled` 对 active turn gate / 文案的旧耦合。

验证：

```text
python -m compileall backend/harness/runtime/run_monitor/projector.py backend/harness/runtime/run_monitor/management.py backend/harness/runtime/run_monitor/signals.py backend/harness/runtime/control_action_schema.py
  passed

npm exec tsc -- --noEmit
  passed

rg -n "expected_task_run_id|task_executor_scheduled|pause_task|stop_task|close_runtime|turnrun:.*task_run_id|task_run_id\.startsWith\(\"turnrun:" backend/harness frontend/src -g "*.py" -g "*.ts" -g "*.tsx"
  no matches

git diff --check on changed F61 paths:
  passed; only CRLF normalization warning on frontend/src/lib/run-monitor/selectors.ts

fixed frontend smoke:
  existing project frontend on 127.0.0.1:3000 was restarted through scripts/frontend_dev.ps1 -Mode dev -CleanNext
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:3000/agent-network -> 200
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=3 -> authority harness.run_monitor, recent present
```

结论：通过。Run Monitor 已把普通 turn 与 TaskRun 的身份空间拆开；后续如果要支持“暂停当前工作”，应继续强化 active work control / user steer 链路，而不是把普通 turn 伪装成 TaskRun。

### Stage F62：GraphNodeTaskBinding 重复绑定状态回退防护

目标：

```text
GraphNodeWorkOrder 在恢复、重试或重复 prepare 时可以再次进入绑定流程，但不能把已 leased / completed 的 GraphNodeTaskBinding 倒退成 bound。
```

权威链检查：

- 符合：`GraphSystem` 仍负责派发 work order；`TaskSystem.graph_bindings` 负责把 graph node work order 映射到任务环境、episode、lease 和 work product。
- 符合：节点绑定状态是任务环境桥接事实，重复 bind 只能幂等更新，不允许回退生命周期。
- 符合：agent 配置仍来自 work order / binding hint / node identity，不由绑定服务重新选择 agent。

修正点：

- `backend/task_system/graph_bindings/service.py`
  - `bind_work_order()` 在已有同一 `graph_run_id + work_order_id` binding 时合并 metadata；
  - 新增 `_binding_status_without_regression()` 和 `_binding_status_rank()`，避免 `leased / waiting_resume / completed / aborted` 被重复 bind 回退成 `bound`。

验证：

```text
python -m compileall backend/task_system/graph_bindings/service.py backend/task_system/graph_bindings/models.py backend/task_system/graph_bindings/repository.py backend/task_system/work_environments/service.py backend/task_system/work_environments/repository.py
  passed

repository smoke from backend/:
  bind_work_order(...) -> bound
  repository.upsert_binding(... status='leased', metadata={'kept':'yes'})
  bind_work_order(...) again -> status leased, metadata kept yes

git diff --check on changed F62 paths:
  passed
```

结论：通过。Graph node task binding 的重复绑定现在是非回退幂等行为，符合图恢复/节点续跑对任务环境桥接层的要求。

### Stage F63：ProjectNetwork typed semantic submission 直接对象化收口

目标：

```text
项目网络审查节点的 agent 只提交一个 respond.structured_output_json typed semantic submission 事实对象。
GraphSystem postprocess 从 structured_output / node_output 读取直接对象，不再把旧 project_network_semantic_submissions 包装字段作为主通道。
```

权威链检查：

- 符合：`Harness` 负责把 respond 的 `structured_output_json` 解析为 `final_action_diagnostics.structured_output / node_output`。
- 符合：`ProjectNetworkTasks` 的 node prompt contract 负责要求 agent 提交 `submission_kind=module_index|directory_summary` 的 typed semantic submission。
- 符合：`GraphSystem` 只把结构化机器输出交给 runtime algorithm adapter，不再为项目网络审查注册额外包装字段。
- 符合：`ProjectNetworkTasks.runtime_adapters` 负责把 typed semantic submission 装配为系统 work product envelope，并触发 `project_network_work_product_ingest` side effect。

修正点：

- `backend/project_network_tasks/runtime_adapters.py`
  - `project_network_work_product` adapter 删除旧 `structured_output_keys=("project_network_semantic_submissions",)` 注册；
  - `_raw_typed_semantic_submissions()` 只从直接 payload、`structured_output`、`node_output` 中识别带 `submission_kind` 的 typed semantic submission；
  - 删除旧包装字段提取：`project_network_semantic_submissions / semantic_submissions / project_network_review_submissions / project_network_semantic_submission`；
  - 诊断字段改为 `typed_semantic_submission_count`，缺失问题改为 `missing_typed_semantic_submission`。
- `backend/prompt_library/worker_prompts.py`
  - 项目网络审查 worker prompt 改为要求提交到 `respond.structured_output_json`，并且只能提交一个带 `submission_kind` 的 typed semantic submission 事实对象。
- `backend/agent_system/profiles/runtime_profile_registry.py`
  - project network file/directory reviewer 的 output contract required fields 从旧包装字段改为 `submission_kind`。

验证：

```text
python -m compileall backend/project_network_tasks/runtime_adapters.py backend/project_network_tasks/template_catalog.py backend/prompt_library/worker_prompts.py backend/agent_system/profiles/runtime_profile_registry.py backend/graph_system/adapter_registry.py backend/graph_system/work_order_executor.py
  passed

rg -n "project_network_semantic_submissions|semantic_submissions|project_network_review_submissions|project_network_semantic_submission|missing_project_network_semantic_submissions|semantic_submission_count|_raw_project_network_semantic_submissions|_dedupe_semantic_submissions|_from_semantic_submission" backend/project_network_tasks backend/prompt_library backend/agent_system backend/graph_system backend/task_system -g "*.py"
  no old channel matches

direct typed submission runtime adapter smoke from backend/:
  structured_outputs = {"structured_output": {"submission_kind":"module_index", ...}, "node_output": same}
  postprocess_project_network_runtime_algorithm_outputs(...) -> accepted True
  issues -> []
  typed_semantic_submission_count -> 1
  graph_build_work_products count -> 1
  side_effects -> ["project_network_work_product_ingest"]
```

结论：通过。项目网络审查产物的机器输出通道已和 agent 契约、harness 解析、GraphSystem runtime adapter 三者对齐；后续恢复/补审反馈应围绕 typed semantic submission 缺字段，而不是旧包装字段。

### Stage F64：GraphRuntime 根 TaskRun 协调身份伪默认清理

目标：

```text
GraphRuntime 只消费 compiled graph_config.agents 中显式声明的根协调 agent 身份。
缺少 coordinator_agent_id / coordinator_agent_profile_id 时不再由 GraphSystem 编造 agent:0 或 task_graph_coordinator。
```

权威链检查：

- 符合：`TaskSystem compiler` 负责把 task graph runtime_policy / metadata 中显式声明的 coordinator 身份写入 `ExecutableGraphConfig.agents`。
- 符合：`GraphRuntime` 是图运行锚点装配层，只消费 compiled config，不拥有选择 coordinator agent/profile 的权威。
- 符合：图节点的实际 agent 执行身份仍由节点配置 / compiled node contract 显式传入 `GraphNodeWorkOrder`，不受根 TaskRun 协调身份影响。
- 符合：没有显式 coordinator 时，根 `TaskRun` 的 agent fields 留空，比伪造不存在的 `task_graph_coordinator` profile 更可诊断。

修正点：

- `backend/graph_system/runtime.py`
  - 根 `TaskRun.agent_id` 改为只读取 `graph_config.agents.coordinator_agent_id`；
  - 根 `TaskRun.agent_profile_id` 改为只读取 `graph_config.agents.coordinator_agent_profile_id`；
  - 保留 `root_task_run_id / graph_root_task_run_id` aliases，不影响 GraphRun root anchor。
- `backend/task_system/compiler/executable_graph_config_publisher.py`
  - compiled config 的 `agents.coordinator_agent_id` 不再默认写入 `agent:0`，只保留 graph runtime policy / metadata 的显式值。

验证：

```text
python -m compileall backend/graph_system/runtime.py backend/task_system/compiler/executable_graph_config_publisher.py
  passed

GraphRuntime.start smoke with minimal service sink:
  explicit graph_config.agents -> task_run.agent_id agent:project_network_coordinator
  explicit graph_config.agents -> task_run.agent_profile_id project_network_coordinator_agent
  missing graph_config.agents -> task_run.agent_id == ""
  missing graph_config.agents -> task_run.agent_profile_id == ""
  graph_root_task_run_id alias still present
  persisted_task_runs -> 2
```

结论：通过。GraphRuntime 不再在根 TaskRun 上制造隐式 coordinator 身份；节点执行身份仍由 GraphNodeWorkOrder 的显式 agent/profile 配置承接。

### Stage F65：TaskGraphRegistry 与图编辑器 coordinator 伪默认清理

目标：

```text
图任务定义入口和前端图编辑器不再把缺失 coordinator_agent_id 自动写成 agent:0。
默认协调图必须有显式 coordinator_agent_id，或通过 agent_group_id 解析到 group coordinator；显式 graph nodes 则由节点自身 agent_id 承接。
```

权威链检查：

- 符合：`TaskGraphRegistryService` 是图任务定义仓库入口，可以校验默认协调图所需的 coordinator，但不应替用户选择 agent。
- 符合：`AgentGroupRegistry` 可以作为显式 `agent_group_id` 的 coordinator 来源；这不是隐藏默认，而是用户/配置指定的组事实。
- 符合：前端图编辑器只保存用户/草稿中的 coordinator 值，不应把空值改写成 `agent:0`。
- 符合：有显式 nodes 的图任务不需要仓库服务再补 coordinator；节点 agent 配置由 node 自身承担。

修正点：

- `backend/task_system/services/graph_task_registry.py`
  - 新增 `resolve_coordination_coordinator()`；
  - 默认协调图无 coordinator 时 fail-closed；
  - runtime_policy 的 `coordinator_agent_id` 改为解析后的显式值或空值；
  - `_default_coordination_graph()` 不再把空 coordinator 转成 `agent:0`。
- `frontend/src/components/workspace/views/task-system/taskGraphDraftV2.ts`
  - 新草稿默认 `coordinator_agent_id` 改为空字符串；
  - 从记录恢复 draft 时不再把缺失 coordinator 改为 `agent:0`。
- `frontend/src/components/workspace/views/task-system/taskGraphSaveMapper.ts`
  - 保存 payload 时不再把空 coordinator 写成 `agent:0`；空值会被 compact 掉。

验证：

```text
python -m compileall backend/task_system/services/graph_task_registry.py backend/graph_system/runtime.py backend/task_system/compiler/executable_graph_config_publisher.py
  passed

npm exec tsc -- --noEmit
  passed from frontend/

TaskGraphRegistryService smoke with in-memory registry:
  no nodes + no coordinator -> ValueError, missing_default_failed True
  no nodes + coordinator=agent:coordinator -> runtime_policy.coordinator_agent_id agent:coordinator
  no nodes + coordinator=agent:coordinator -> first default node agent_id agent:coordinator
  explicit node agent:worker + no coordinator -> runtime_policy.coordinator_agent_id == ""
  explicit node agent:worker + no coordinator -> first node agent_id agent:worker

rg -n "coordinator_agent_id.*agent:0|agent:0.*coordinator|task_graph_coordinator" frontend/src/components/workspace/views/task-system frontend/src/lib backend/task_system/services/graph_task_registry.py backend/graph_system/runtime.py backend/task_system/compiler/executable_graph_config_publisher.py -g "*.ts" -g "*.tsx" -g "*.py"
  no matches for the graph coordinator default chain
```

结论：通过。图任务定义、compiled config、GraphRuntime 和前端编辑器保存链路已统一为显式 coordinator；旧 `agent:0` 不再作为图任务 coordinator 的隐式默认。

### Stage F66：TaskWorkEnvironment episode 执行身份伪默认清理

目标：

```text
TaskWorkEnvironmentService.prepare_task_episode 不再编造 task_environment_worker，也不再把 owner_agent_id 当作 agent_profile_id 使用。
一次 AgentExecutionEpisode 必须有明确 agent_id 和明确 agent_profile_id。
```

权威链检查：

- 符合：`TaskSystem` 可以持久化 task environment 和 episode，但不能替调用方选择 agent profile。
- 符合：`agent_id` 可以来自 prepare 请求或 task owner；`agent_profile_id` 是 runtime profile 身份，必须显式传入，不能从 owner agent id 猜测。
- 符合：缺少执行身份时在 prepare 阶段 fail-closed，比创建一个无法真实执行的假 episode 更可诊断。
- 符合：Graph node task binding 仍通过 `GraphNodeWorkOrder` 的显式 agent/profile 创建 episode，不走 `task_environment_worker` 兜底。

修正点：

- `backend/task_system/work_environments/service.py`
  - 删除 `task_environment_worker` fallback；
  - 删除 `agent_profile_id or task_instance.owner_agent_id` 的身份混用；
  - `prepare_task_episode()` 缺 `agent_id` 且 task owner 为空时抛 `ValueError`；
  - `prepare_task_episode()` 缺显式 `agent_profile_id` 时抛 `ValueError`；
  - idempotency key 纳入 resolved `agent_id` 和 `agent_profile_id`。

验证：

```text
python -m compileall backend/task_system/work_environments/service.py backend/task_system/work_environments/models.py backend/task_system/work_environments/repository.py backend/task_system/episodes/models.py
  passed

rg -n "task_environment_worker" backend/task_system/work_environments backend/api/task_system.py backend/harness/entrypoint/runtime_facade.py -g "*.py"
  no matches

TaskWorkEnvironmentService smoke with TemporaryDirectory:
  create_task_environment(owner_agent_id="agent:owner") -> ready env
  prepare_task_episode(agent_profile_id="") -> ValueError, missing_profile_failed True
  prepare_task_episode(agent_profile_id="profile:owner") -> episode.agent_id agent:owner
  prepare_task_episode(agent_profile_id="profile:owner") -> episode.agent_profile_id profile:owner
  context_package -> present
```

结论：通过。任务环境 episode 不再携带系统伪造的 worker 身份；执行身份必须由任务 owner 或调用方与显式 runtime profile 共同确定。

补充固定端口运行链路验证：

```text
GET http://127.0.0.1:8003/health
  {"status":"ok"}

GET http://127.0.0.1:3000
  200

GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1
  authority harness.run_monitor
```

### Stage F67：Graph node bridge 执行身份解析顺序修正

目标：

```text
Harness graph node bridge 先解析 graph node runtime profile 和 agent_id，再把解析后的执行身份交给 TaskSystem 准备 GraphNodeTaskBinding / AgentExecutionEpisode。
TaskSystem 不再因为 work order 原始 agent_id 为空而早于 Harness profile 解析失败。
```

权威链检查：

- 符合：`Harness` 拥有 agent runtime registry，可以根据显式 `agent_profile_id` 解析实际 `agent_id`。
- 符合：`TaskSystem` 只记录已解析的 episode 执行身份，不负责查询 profile registry 或猜测 agent。
- 符合：`GraphSystem` 仍只传递节点配置和 work order，不需要 import agent registry。
- 符合：缺少 `agent_profile_id` 或 profile 缺少 `agent_id` 时 fail-closed，返回 graph node blocked result，不创建伪 episode。

修正点：

- `backend/harness/entrypoint/runtime_facade.py`
  - `_execute_graph_agent_work_order()` 调整顺序：先 `_resolve_graph_node_agent_profile(raw_work_order_payload)`，再调用 `_graph_node_task_preparation_payload()`；
  - 传给 TaskSystem preparation sink 的 work order payload 注入已解析的 `agent_id` 和 `agent_profile_id`；
  - `_resolve_graph_node_agent_profile()` 在 profile 缺少 agent id 时返回 `graph_node_agent_id_missing`。

验证：

```text
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/task_system/graph_bindings/service.py backend/task_system/work_environments/service.py
  passed

HarnessRuntimeFacade._resolve_graph_node_agent_profile smoke with dummy registry:
  payload agent_profile_id=profile:x + profile.agent_id=agent:x -> ok True, agent_id agent:x
  payload agent_profile_id=profile:x + profile.agent_id="" -> ok False, reason graph_node_agent_id_missing
  payload without agent_profile_id -> ok False, reason graph_node_agent_profile_missing
```

结论：通过。graph node episode 准备现在接收 Harness 已解析的真实执行身份，避免 TaskSystem 在 profile 解析前因为 agent_id 空值误失败，也避免 TaskSystem 自己猜 agent。

补充固定后端重启验证：

```text
stopped old project backend process on 127.0.0.1:8003
started C:\Users\admin\.conda\envs\agent\python.exe run_uvicorn.py --host 127.0.0.1 --port 8003 from backend/
GET http://127.0.0.1:8003/health -> {"status":"ok"}
GET http://127.0.0.1:3000 -> 200
GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> authority harness.run_monitor
127.0.0.1:8003 listener -> single project backend process
```

### Stage F68：Task episode WorkProduct 不再由 final_answer 单独触发

目标：

```text
普通 TaskWorkEnvironment episode 的 WorkProduct candidate 只能由结构化输出或 artifact refs 触发。
assistant final_answer 只作为面向人的收口摘要 / receipt，不再单独成为可消费 WorkProduct。
```

权威链检查：

- 符合：`Harness` 可以收集 final answer，但不能把自然语言回答本身提升为结构化产物事实。
- 符合：`TaskSystem WorkProductStore` 保存可消费产物 candidate；没有结构化输出或 artifact refs 时，episode result summary 足以记录人类可读收口。
- 符合：带 `structured_output` 的任务仍可形成 WorkProduct；final answer 只作为 `final_answer_receipt` 附在结构化产物旁。
- 符合：带 artifact refs 的任务仍可形成 WorkProduct，满足文件/文档类产物交付。

修正点：

- `backend/harness/entrypoint/runtime_facade.py`
  - `_task_episode_work_products()` 删除 final-answer-only WorkProduct 触发条件；
  - 只有 `structured_output` 或 `artifact_refs` 存在时才创建 WorkProduct；
  - WorkProduct payload 不再写 `final_answer` 主字段，改为可选 `final_answer_receipt`。

验证：

```text
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/task_system/work_products/models.py backend/task_system/reducer.py
  passed

_task_episode_work_products smoke:
  executor_result(status=completed, final_answer only) -> final_only_count 0
  executor_result(status=completed, structured_output + final_answer) -> structured_count 1, final_answer_receipt present, evidence_refs preserved
  executor_result(status=completed, artifact_refs + final_answer) -> artifact_count 1, artifact_refs preserved
```

结论：通过。Task episode 不再把 assistant message 当作唯一 WorkProduct；结构化产物和 artifact 产物路径保持可用。

### Stage F69：Writing graph progress receipt 不再从 final_answer 反解析

目标：

```text
写作图循环的章节进度回执只能来自结构化节点输出。
assistant final_answer 是面向人的收口文本，不能被 runtime adapter 反向解析成 progress receipt。
```

权威链检查：

- 符合：`Harness/agent` 产出自然语言回答，但自然语言回答不拥有结构化事实权威。
- 符合：`TaskSystem writing runtime semantics` 通过 `first_chapter_progress_receipt()` 统一定义哪些结构字段可作为进度回执。
- 符合：`GraphSystem runtime adapter` 只把节点结构化输出交给语义层验证，不再自行解析 fenced JSON。
- 符合：确定性 progress receipt router 仍通过 `structured_output/node_output` 交付回执，正文只做人类可读收口。

修正点：

- `backend/task_system/writing_graphs/runtime_adapters.py`
  - 删除 `json` / `re` fenced JSON 解析逻辑；
  - 删除 `_json_objects_from_text()` 和本地候选解析分支；
  - 改为调用 `first_chapter_progress_receipt([source], key=..., initial_inputs=...)`；
  - 保留 adapter 协议中的 `final_answer` 入参，但显式 `del final_answer`，防止未来误用。
- `backend/task_system/writing_graphs/work_order_handlers.py`
  - 删除 deterministic receipt final answer 中的 JSON 代码块；
  - 保留结构化回执在 `final_action_diagnostics.structured_output/node_output` 中。

验证：

```text
python -m compileall backend/task_system/writing_graphs/runtime_adapters.py backend/task_system/writing_graphs/work_order_handlers.py backend/graph_system/work_order_executor.py
  passed

Writing progress receipt smoke:
  structured_output.chapter_progress_receipt -> structured_progress_count 1, structured_error_count 0
  final_answer fenced JSON only -> final_only_progress_count 0, final_only_error_reason chapter_progress_receipt_missing
  deterministic progress receipt router -> router_has_structured True, router_final_has_json_fence False
```

结论：通过。写作图 progress receipt 已回到结构化输出通道，自然语言正文不再参与图循环事实构建。

### Stage F70：Engagement / specialist 执行身份不再伪造默认 agent

目标：

```text
任务 engagement 的承接 agent 必须来自计划显式配置。
系统不能把缺失的 assignee 或来源 agent 自动改写为 agent:0 / main_interactive_agent。
```

权威链检查：

- 符合：`EngagementPlan` 拥有任务承接者配置权威，resolver 只解析显式 `agent_profile_id` 或 `agent_id`。
- 符合：`EngagementAdmission` 用 `missing_refs` fail-closed，不把缺失承接者补成默认 agent。
- 符合：`EngagementDispatcher` 只启动 graph task run，不接收也不使用伪 profile 参数；节点执行身份继续由 graph config -> harness profile resolver 决定。
- 符合：`SpecialistRuntimeRouter` 的 `source_agent_id` 是来源事实，不存在时保持空值，不伪造为 `agent:0`。

修正点：

- `backend/task_system/engagement/resolver.py`
  - `agent_profile_id` 优先通过 `get_profile_by_profile_id()` 解析；
  - 其次才用显式 `agent_id` 通过 `get_profile()` 解析；
  - 两者都缺失时返回 `agent_assignee_ref_required`。
- `backend/task_system/engagement/service.py`
  - 删除 dispatch 调用中的 `main_interactive_agent` 默认 profile。
- `backend/task_system/engagement/dispatcher.py`
  - 删除未使用的 `agent_profile_ref` 参数。
- `backend/harness/loop/specialist_runtime_router.py`
  - `source_agent_id` 不再 fallback 到 `agent:0`。

验证：

```text
python -m compileall backend/task_system/engagement/resolver.py backend/task_system/engagement/service.py backend/task_system/engagement/dispatcher.py backend/harness/loop/specialist_runtime_router.py
  passed

Engagement resolver smoke with TemporaryDirectory:
  plan assignee kind=agent with no agent refs -> missing_refs ['agent_assignee_ref_required'], missing_profile_present False
  plan assignee agent_profile_id=main_interactive_agent -> explicit_missing_refs [], explicit_profile_id main_interactive_agent

rg -n "agent:0|main_interactive_agent|agent_profile_ref=|source_agent_id=.*agent" backend/task_system/engagement backend/harness/loop/specialist_runtime_router.py -g "*.py"
  no implicit default identity matches; source_agent_id now preserves explicit origin/agent_run value only
```

结论：通过。Engagement 和 specialist capability request 不再制造默认执行身份；缺失身份会作为配置问题显式暴露。

### Stage F71：ProjectNetworkSystem 去除对 GraphSystem NodeResultEnvelope 的 import

目标：

```text
ProjectNetworkSystem 是项目控制网络资产权威，不依赖 GraphSystem 运行模型。
图任务适配层可以把 NodeResultEnvelope / node result 交给项目网络资产服务，但资产服务只接收普通 payload 合同。
```

权威链检查：

- 符合：`GraphSystem` 拥有 `NodeResultEnvelope` 运行模型。
- 符合：`ProjectNetworkTasks` 是图任务适配层，可以承接 graph runtime effect 并调用项目网络资产服务。
- 符合：`ProjectNetworkSystem` 只声明最小 node result payload 合同，不 import `graph_system.models`。
- 符合：缺少必要节点结果字段时 fail-closed，不通过图模型 fallback 或旧兼容壳补齐。

修正点：

- `backend/project_network_system/service.py`
  - 删除 `from graph_system.models import NodeResultEnvelope`；
  - `accept_node_result()` 入参改为 `Any`，内部通过 `to_dict()` / dict 做 payload 归一；
  - 新增 `_node_result_payload()`，要求 `result_id / graph_run_id / node_id / work_order_id`；
  - `_result_build_id()` / `_result_shard_id()` / `_result_layer_id()` 改为基于 dict payload 读取。

验证：

```text
python -m compileall backend/project_network_system/service.py backend/project_network_tasks/directory_runtime_service.py backend/project_network_tasks/repair_runtime_service.py backend/project_network_tasks/runtime_effects.py
  passed

rg -n "from graph_system|import graph_system|GraphSystem|Harness|AgentRuntime|start_run|dispatch" backend/project_network_system -g "*.py"
  no matches

ProjectNetworkBuildService.accept_node_result smoke:
  dict node result payload + module_index work product -> build_id build:dict-payload-smoke, work_product_count 1, trace_status accepted
  semantic_artifact_set.authority -> project_network_system.semantic_artifact_set
  missing required node result fields -> ValueError(ProjectNetworkBuildService node result missing required fields: graph_run_id, node_id, work_order_id)
```

结论：通过。项目网络资产系统不再依赖图运行模型；图模型到资产 payload 的转换边界回到 `project_network_tasks` / runtime effect 一侧。

### Stage F72：Graph extension loader 迁回 GraphSystem

目标：

```text
GraphSystem 拥有 graph adapter / context provider / runtime effect / quality gate / revision signal 的注册入口。
TaskSystem 不再承载图系统扩展 loader；TaskSystem 只使用图任务运行能力，不管理图扩展设施。
```

权威链检查：

- 符合：`GraphSystem` 管理 graph runtime 扩展注册。
- 符合：`ProjectNetworkTasks` 与 `task_system.writing_graphs` 仍只是可加载扩展模块，不拥有 registry。
- 符合：`Bootstrap` 初始化 GraphSystem 扩展，`EngagementDispatcher` 只在需要临时创建 GraphSystem 时懒加载扩展。
- 符合：旧 `task_system.graph_extensions` 删除，不保留兼容导出。

修正点：

- 新增 `backend/graph_system/extensions.py`
  - 定义 `ensure_graph_extensions_loaded()`；
  - 加载 writing graph 与 project network task 的 adapters、context providers、runtime effects、memory candidate handlers、deterministic work order handlers、quality gates、revision signals。
- `backend/bootstrap/app_runtime.py`
  - 改为从 `graph_system.extensions` 导入并调用 `ensure_graph_extensions_loaded()`。
- `backend/task_system/engagement/dispatcher.py`
  - 懒加载路径改为 `graph_system.extensions.ensure_graph_extensions_loaded()`。
- 删除 `backend/task_system/graph_extensions.py`。

验证：

```text
python -m compileall backend/graph_system/extensions.py backend/bootstrap/app_runtime.py backend/task_system/engagement/dispatcher.py
  passed

rg -n "task_system\\.graph_extensions|ensure_task_graph_extensions_loaded|graph_extensions" backend -g "*.py"
  only new graph_system.extensions references remain

Graph extension loader smoke:
  adapter_ids ['project_network_work_product', 'writing_iteration']
  effect_kinds ['project_network_work_product_ingest']
  context_provider_ids ['project_network_context', 'writing_graph_context']
```

结论：通过。图扩展注册权威已从 TaskSystem 搬回 GraphSystem，旧入口删除。

补充固定端口运行链路验证：

```text
stopped old project backend process on 127.0.0.1:8003
started C:\Users\admin\.conda\envs\agent\python.exe run_uvicorn.py --host 127.0.0.1 --port 8003 from backend/
GET http://127.0.0.1:8003/health -> {"status":"ok"}
GET http://127.0.0.1:3000 -> 200
GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> authority harness.run_monitor
127.0.0.1:8003 listener -> single project backend process 24988
127.0.0.1:3000 listener -> single frontend process 10596
```

### Stage F77-F79：日志顺序校正

说明：

```text
Stage F77-F79 的完整记录已经写入本文，但因补写时匹配到较早的固定端口验证块，当前文件中位于 F72 之后。
后续阅读和实施以阶段编号为准：F77-F79 发生在 F76 之后，F80 继续接在 F79 之后。
```

校正原则：

- 不为顺序问题重写整份进度日志，避免把代码重构 diff 混入大规模文档搬移噪声。
- 后续阶段继续写在文件末尾，并按阶段编号保持连续。
- 若后续需要发布版文档，再做一次纯文档顺序整理。

### Stage F80：普通 request resolver 不再用 agent:0 静默兜底显式身份错误

目标：

```text
普通交互 turn 可以拥有默认主 agent，但默认边界必须是显式的 main_interactive_agent profile。
当请求或 runtime_contract 显式指定 agent_profile_id / agent_id 时，配置错误必须 fail-closed，不能静默回落到 agent:0。
Task episode 和 Graph node 继续使用各自 resolver；缺 profile 会阻断，不走普通 request 默认链路。
```

权威链检查：

- 符合：`Graph node` 运行链路走 `_resolve_graph_node_agent_profile()`，缺 `agent_profile_id` 或 `agent_id` 会返回 blocked executor result。
- 符合：`Task environment episode` 运行链路走 `_resolve_task_episode_agent_profile()`，缺 episode profile 会 fail-closed。
- 符合：普通 chat request 无显式身份时才使用 `main_interactive_agent` profile。
- 符合：`agent:0` 仍可作为主 agent 的 agent_id 存在，但不再作为 request resolver 的隐式兜底入口。
- 符合：显式 profile 与显式 agent_id 冲突时不再静默选择 profile 或默认 agent。

修正点：

- `backend/harness/entrypoint/runtime_facade.py`
  - 新增 `DEFAULT_INTERACTIVE_AGENT_PROFILE_ID = "main_interactive_agent"`；
  - `_resolve_request_agent_runtime_profile()` 对显式 `agent_profile_id/profile_ref/agent_profile_ref` 查不到时抛 `request_agent_profile_not_registered`；
  - 显式 profile 与显式 `agent_id` 不一致时抛 `request_agent_profile_agent_mismatch`；
  - 仅显式 `agent_id` 查不到时抛 `request_agent_id_not_registered`；
  - 无显式身份时通过 `get_profile_by_profile_id("main_interactive_agent")` 取默认 profile，不再调用 `get_profile(agent_id or "agent:0")`。

验证：

```text
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/agent_system/profiles/runtime_profile_registry.py
  passed

request resolver smoke:
  default_profile main_interactive_agent agent:0
  explicit_profile main_interactive_agent agent:0
  explicit_agent main_interactive_agent agent:0
  missing profile -> ValueError request_agent_profile_not_registered:missing_profile
  missing agent -> ValueError request_agent_id_not_registered:agent:missing
  profile/agent mismatch -> ValueError request_agent_profile_agent_mismatch:main_interactive_agent:agent:knowledge_searcher:agent:0

rg -n -F 'get_profile(agent_id or "agent:0"' backend/harness/entrypoint/runtime_facade.py
  no matches
rg -n -F 'get_profile("agent:0")' backend/harness/entrypoint/runtime_facade.py
  no matches

fixed-port runtime smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 24956
  started backend on 127.0.0.1:8003 pid 29728
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
  127.0.0.1:3000 listener -> single frontend process 10596
```

结论：通过。普通交互默认身份仍可用，但显式身份配置错误不再被主 agent 静默吞掉；Task/Graph 的 profile 权威保持在各自运行桥接层。

### Stage F77：ProjectNetworkTasks 不再直接承接 GraphSystem 节点结果模型

目标：

```text
ProjectNetworkTasks 是项目网络图任务适配层，可以接收图节点结果事实，但跨到 ProjectNetworkSystem 时只能传递 plain payload。
ProjectNetworkSystem 继续拥有项目网络资产 ingest 权威；GraphSystem.NodeResultEnvelope 不进入项目网络任务/资产边界作为接口类型。
```

权威链检查：

- 符合：`GraphSystem` 继续拥有 `NodeResultEnvelope` 运行模型。
- 符合：`ProjectNetworkTasks` 只做图任务 glue：发布目录 frame graph、准备 start inputs、记录 graph start、接收节点结果 payload。
- 符合：`ProjectNetworkSystem` 只接收普通 node result payload，保存 work product、evidence、candidate、layer index、generation 和 trace。
- 符合：repair runtime 继续复用 directory runtime ingest 入口，不复制图结果解析权威。

修正点：

- `backend/project_network_tasks/directory_runtime_service.py`
  - 删除 `graph_system.models.NodeResultEnvelope` import；
  - `accept_directory_node_result()` 入口改为 `Any`；
  - 新增 `_node_result_payload()`，将 `dict` 或带 `to_dict()` 的对象归一化为普通 payload 后再调用 `ProjectNetworkBuildService.accept_node_result()`。
- `backend/project_network_tasks/repair_runtime_service.py`
  - 删除 `graph_system.models.NodeResultEnvelope` import；
  - `accept_repair_node_result()` 入口改为 `Any`，继续交给 directory runtime 的统一 payload 入口。

验证：

```text
rg -n "NodeResultEnvelope" backend/project_network_tasks -g "*.py"
  no matches

python -m compileall backend/project_network_tasks/directory_runtime_service.py backend/project_network_tasks/repair_runtime_service.py backend/project_network_system/service.py
  passed

ProjectNetworkTasks payload normalization smoke:
  dict payload -> result_id r2
  to_dict payload -> graph_run_id g
```

结论：通过。项目网络任务适配层不再把 GraphSystem 节点结果模型作为接口类型，跨系统边界收敛为普通 payload；GraphSystem 模型权威与 ProjectNetworkSystem 资产权威进一步分离。

### Stage F78：Repair graph package 构造去掉旧替换链路，Graph binding 文案改为 payload 边界

目标：

```text
后端运行路径不保留“先构造错误对象、再 replace 修正”的旧壳。
Graph node task binding 可以接受带 to_dict() 的图结果对象，但接口语义描述应是 graph node result payload，而不是把 GraphSystem 模型名写成跨层要求。
```

权威链检查：

- 符合：`ProjectNetworkRepairRuntimeService` 在构造 repair frame package 前先取得 child returns，package 初始状态即为正确数据。
- 符合：repair graph publish 仍只负责图任务包发布和 repair item 状态推进，不保存项目网络语义资产。
- 符合：`GraphNodeTaskBindingService` 仍接收普通 dict 或可转 dict 的对象，但错误边界描述为 payload，不要求调用侧感知 `NodeResultEnvelope` 类名。

修正点：

- `backend/project_network_tasks/repair_runtime_service.py`
  - 删除无效的 tuple-comprehension child_returns 构造；
  - 删除随后的 `replace(package, child_returns=...)` 修补链；
  - `child_return_ref_count` 改为真实 package child returns 数量。
- `backend/task_system/graph_bindings/service.py`
  - `_node_result_payload()` 的错误信息从 `NodeResultEnvelope payload` 改为 `graph node result payload`。

验证：

```text
python -m compileall backend/project_network_tasks/repair_runtime_service.py backend/task_system/graph_bindings/service.py
  passed

rg -n "materializes child returns twice|replace\\(package, child_returns|NodeResultEnvelope payload" backend/project_network_tasks/repair_runtime_service.py backend/task_system/graph_bindings/service.py
  no matches

GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
```

结论：通过。repair graph package 构造链路不再依赖旧修补对象；图节点绑定层的公开错误语义也回到 payload 边界。

### Stage F79：Graph extension loader 与 context provider 执行合同 fail-closed

目标：

```text
GraphSystem 的扩展加载是显式能力注册，不是可静默忽略的 optional import。
扩展模块缺少注册函数、context provider 返回非 GraphContextProviderContribution，都必须显式失败，避免图任务看似加载成功但实际缺能力。
```

权威链检查：

- 符合：`GraphSystem` 拥有 adapter / context provider / effect / handler registry 的注册权威。
- 符合：领域扩展模块可以被 GraphSystem 加载，但必须通过对应 register 函数显式注册能力。
- 符合：context provider 是图运行上下文注入的权威扩展点，返回错类型不能被静默跳过。
- 符合：runtime algorithm effect 仍保留 required effect gate；handler 失败会形成 failed receipt，并由 required gate 阻断节点完成。

修正点：

- `backend/graph_system/adapter_registry.py`
  - extension module 缺 `register_runtime_algorithm_adapters()` 时抛错。
- `backend/graph_system/context_provider_registry.py`
  - provider 返回非 `GraphContextProviderContribution` 时抛错；
  - extension module 缺 `register_context_providers()` 时抛错。
- `backend/graph_system/runtime_effect_registry.py`
  - extension module 缺 `register_runtime_algorithm_effect_handlers()` 时抛错。
- `backend/graph_system/memory_candidate_registry.py`
  - extension module 缺 `register_memory_candidate_payload_handlers()` 时抛错。
- `backend/graph_system/work_order_handler_registry.py`
  - extension module 缺 `register_deterministic_work_order_handlers()` 时抛错。
- `backend/graph_system/quality_gate_registry.py`
  - extension module 缺 `register_quality_gate_handlers()` 时抛错。
- `backend/graph_system/revision_signal_registry.py`
  - extension module 至少需要 `register_revision_rejection_signal_handlers()` 或 `register_revision_requeue_patch_handlers()` 之一，否则抛错。

验证：

```text
python -m compileall backend/graph_system/adapter_registry.py backend/graph_system/context_provider_registry.py backend/graph_system/runtime_effect_registry.py backend/graph_system/memory_candidate_registry.py backend/graph_system/work_order_handler_registry.py backend/graph_system/quality_gate_registry.py backend/graph_system/revision_signal_registry.py backend/graph_system/extensions.py
  passed

Graph extension loader smoke:
  adapters ['project_network_work_product', 'writing_iteration']
  providers ['project_network_context', 'writing_graph_context']
  effects ['project_network_work_product_ingest']
  memory ['writing_review_memory_candidates']
  work_handlers ['writing_progress_receipt_router']
  quality ['writing_stage_business_acceptance']
  revision ['writing_review_verdict_revision_signal'] ['writing_chapter_revision_requeue_patch']

Invalid extension module smoke:
  load_runtime_algorithm_adapter_module('math') -> ValueError runtime algorithm adapter module has no register_runtime_algorithm_adapters(): math

Invalid context provider smoke:
  bad provider returning None -> ValueError graph context provider returned invalid contribution: bad_provider

GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
```

结论：通过。GraphSystem 扩展面不再静默吞掉缺注册或错类型 provider；图任务能力缺线会在加载/运行边界明确暴露。

### Stage F73：Task assembly / recipe 主链不再注入 agent:0 默认身份

目标：

```text
Task assembly policy 与 runtime execution recipe 只能传递显式任务身份配置。
未配置 agent 时保持空值，由后续准入、任务环境或 graph node profile bridge fail-closed；不能在合同/recipe 层改写成 agent:0。
```

权威链检查：

- 符合：`TaskSystem` 的 assembly policy 负责表达任务配置事实，不负责发明执行 agent。
- 符合：`ExecutionRecipe` 描述运行形状、操作和步骤，不拥有 agent 身份裁决权。
- 符合：显式 `execution_policy.default_agent_id` 或 `metadata.agent_profile_id` 仍被保留。
- 符合：普通 interactive turn 的产品默认 agent 不在本阶段处理；本阶段只清任务合同/recipe 主链的伪默认。

修正点：

- `backend/task_system/tasks/assembly_policy.py`
  - `AgentSelectionPolicy.default_agent_id` 默认值从 `agent:0` 改为空字符串。
- `backend/task_system/tasks/assembly_policy_resolver.py`
  - 删除 `_first_value(..., "agent:0")` fallback；
  - 只从显式 `execution_policy.default_agent_id` 或任务 metadata 读取 default agent。
- `backend/task_system/planning/execution_recipe_models.py`
  - `ExecutionRecipe.default_agent_id` 默认值改为空字符串；
  - `ExecutionRecipe.allowed_agent_ids` 默认值改为空 tuple。
- `backend/task_system/planning/execution_recipe_builder.py`
  - 删除 recipe profile 缺省时的 `agent:0` / `("agent:0",)` 注入。

验证：

```text
python -m compileall backend/task_system/tasks/assembly_policy.py backend/task_system/tasks/assembly_policy_resolver.py backend/task_system/planning/execution_recipe_models.py backend/task_system/planning/execution_recipe_builder.py backend/task_system/assembly/contract_issuer.py backend/task_system/services/assembly_builder.py
  passed

rg -n "agent:0|allowed_agent_ids=.*agent|default_agent_id=.*agent" backend/task_system/tasks/assembly_policy.py backend/task_system/tasks/assembly_policy_resolver.py backend/task_system/planning/execution_recipe_models.py backend/task_system/planning/execution_recipe_builder.py
  no implicit agent:0 defaults in runtime assembly / recipe files

Task assembly identity smoke:
  implicit_default_agent_id ''
  implicit_agent_profile_ref ''
  explicit_default_agent_id agent:explicit
  explicit_agent_profile_ref profile:explicit
  recipe_default_agent_id ''
  recipe_allowed_agent_ids []
```

结论：通过。任务 assembly / recipe 主链不再制造 `agent:0` 身份；显式配置仍能传递。

### Stage F74：Task registry / assignment 派生层不再注入 agent:0

目标：

```text
Specific task assignment、derived execution policy、registry overview 都必须表达真实配置。
缺少承接 agent 时输出缺线诊断，不能把空配置改写成 agent:0。
```

权威链检查：

- 符合：`TaskAssignment` 和 `TaskExecutionPolicy` 是任务配置事实与派生策略，不拥有默认 agent 裁决权。
- 符合：`AssignmentRepository` 从 specific task / flow 派生 assignment 时保留 flow 的显式 agent；flow 未配置时保持空。
- 符合：`TaskFlowRegistry` 派生 execution policy 时保留空值，不再注入默认 agent。
- 符合：`TaskRegistryOverviewBuilder` 将缺 agent 显示为 `agent_ref_missing` / `runtime_profile_ref_missing`，供人和前端修线。
- 符合：显式 `agent:explicit` 仍能贯穿 assignment 与 execution policy。

修正点：

- `backend/task_system/registry/flow_models.py`
  - `TaskAssignment.default_agent_id` 默认值改为空字符串；
  - `TaskExecutionPolicy.default_agent_id` 默认值改为空字符串。
- `backend/task_system/repositories/assignment_repository.py`
  - `assignment_from_specific_task_record()` 不再从空 flow agent fallback 到 `agent:0`；
  - `_assignment_from_dict()` 不再从缺失 payload fallback 到 `agent:0`。
- `backend/task_system/registry/flow_registry.py`
  - `_default_execution_policy()`、`upsert_task_assignment()`、`_assignment_from_flow()`、`_synthetic_task_from_general_profile()` 删除 `agent:0` fallback；
  - `upsert_task_execution_policy()` 参数默认值改为空字符串。
- `backend/task_system/services/registry_overview.py`
  - `build_binding_for_flow()` 对空 agent 输出 `agent_ref_missing` / `runtime_profile_ref_missing`；
  - 删除 `agent:0` 专属的 `main_agent_without_general_task` 历史规则。

验证：

```text
python -m compileall backend/task_system/registry/flow_models.py backend/task_system/repositories/assignment_repository.py backend/task_system/registry/flow_registry.py backend/task_system/services/registry_overview.py
  passed

rg -n "agent:0" backend/task_system/registry/flow_models.py backend/task_system/repositories/assignment_repository.py backend/task_system/registry/flow_registry.py backend/task_system/services/registry_overview.py
  no matches

Task registry identity smoke with TemporaryDirectory:
  assignment_default_agent_id ''
  execution_policy_default_agent_id ''
  binding_agent_id ''
  binding_failures ['agent_ref_missing', 'runtime_profile_ref_missing', 'workflow_missing']
  explicit_assignment_default_agent_id agent:explicit
  explicit_execution_policy_default_agent_id agent:explicit
```

结论：通过。任务 registry / assignment 派生层不再制造默认主 agent；缺线被显式暴露，显式 agent 配置仍然贯通。

### Stage F75：Task repository 读写层不再回填 agent:0

目标：

```text
Task repository 负责保存和读取配置事实。
当 general profile / execution policy / flow 缺少 default_agent_id 时，仓库必须保持空值，不得在读写归一化中回填 agent:0。
```

权威链检查：

- 符合：`FlowRepository` 只持久化显式 general task profile / flow 配置，不决定默认 agent。
- 符合：`TaskAssemblyConfigRepository` 只持久化显式 execution policy，不决定默认 agent。
- 符合：普通会话入口如需 main agent，应由显式 profile 或 Harness interactive profile resolver 提供，不由任务仓库隐式制造。
- 符合：F73/F74 的 assembly、assignment、derived policy 空值保真不会被仓库读写层重新污染。

修正点：

- `backend/task_system/repositories/flow_repository.py`
  - `upsert_general_profile()` 不再将空 `default_agent_id` 写成 `agent:0`；
  - `_general_profile_from_dict()` 不再将缺失 `default_agent_id` 读成 `agent:0`。
- `backend/task_system/repositories/assembly_config_repository.py`
  - `upsert_execution_policy()` 默认 `default_agent_id` 改为空字符串；
  - `_execution_policy_from_dict()` 不再将缺失 `default_agent_id` 读成 `agent:0`。

验证：

```text
python -m compileall backend/task_system/repositories/flow_repository.py backend/task_system/repositories/assembly_config_repository.py backend/task_system/registry/flow_registry.py
  passed

rg -n "agent:0" backend/task_system/repositories/flow_repository.py backend/task_system/repositories/assembly_config_repository.py backend/task_system/registry/flow_registry.py backend/task_system/registry/flow_models.py backend/task_system/repositories/assignment_repository.py backend/task_system/services/registry_overview.py backend/task_system/tasks/assembly_policy.py backend/task_system/tasks/assembly_policy_resolver.py backend/task_system/planning/execution_recipe_models.py backend/task_system/planning/execution_recipe_builder.py
  no matches

Task repository identity smoke with TemporaryDirectory:
  general_default_agent_id ''
  reread_general_default_agent_id ''
  upsert_policy_default_agent_id ''
  reread_policy_default_agent_id ''
```

结论：通过。TaskSystem 装配、派生和仓库读写层已经清掉 `agent:0` 隐式身份；剩余 `main_interactive_agent` 属于 Harness 普通 turn profile 默认链路，不在任务仓库权威范围内。

补充固定端口运行链路验证：

```text
stopped project backend process on 127.0.0.1:8003
started C:\Users\admin\.conda\envs\agent\python.exe run_uvicorn.py --host 127.0.0.1 --port 8003 from backend/
GET http://127.0.0.1:8003/health -> {"status":"ok"}
GET http://127.0.0.1:3000 -> 200
GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> authority harness.run_monitor
127.0.0.1:8003 listener -> single project backend process 24956
127.0.0.1:3000 listener -> single frontend process 10596
```

### Stage F76：Graph node WorkProduct 不再由 handoff_summary 单独触发

目标：

```text
Graph node binding 的 WorkProduct candidate 只能由结构化节点结果或 artifact / receipt 触发。
handoff_summary 是人类可读交接摘要，不得单独提升为可消费 WorkProduct。
```

权威链检查：

- 符合：`NodeResultEnvelope.handoff_summary` 可用于 episode summary、blocked reason、continuation hint，但不拥有结构化产物权威。
- 符合：`outputs`、`decisions`、`artifact_refs`、`progress_receipts`、`artifact_materialization_receipts`、`memory_commit_receipts` 是图节点结构化结果，可以形成 WorkProduct。
- 符合：这与 F68 的普通 task episode 裁决保持一致：assistant message / summary 不能作为唯一 WorkProduct。
- 符合：已有结构化产物旁边仍可保留 `handoff_summary` 作为 payload 内的收口说明。

修正点：

- `backend/task_system/graph_bindings/service.py`
  - `_result_has_product_payload()` 删除 `handoff_summary` 单独触发条件；
  - 新增 `decisions` 作为结构化触发条件；
  - `_public_node_result_payload()` 仍保留 `handoff_summary`，但只随结构化产物一起记录。

验证：

```text
python -m compileall backend/task_system/graph_bindings/service.py backend/task_system/work_products/models.py backend/task_system/reducer.py
  passed

Graph node WorkProduct smoke:
  handoff_summary only -> handoff_only_count 0
  decisions + handoff_summary -> decisions_only_count 1
  outputs -> outputs_count 1
  artifact_refs -> artifact_refs_count 1
```

结论：通过。图节点任务绑定层不再把交接摘要当作唯一 WorkProduct；结构化节点结果和 artifact / receipt 产物路径保持可用。

补充固定端口运行链路验证：

```text
GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
GET http://127.0.0.1:3000 -> 200
GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
127.0.0.1:8003 listener -> single project backend process 24956
127.0.0.1:3000 listener -> single frontend process 10596
```

### Stage F77-F80：当前日志顺序索引

说明：

```text
Stage F77-F80 的完整记录位于本文第 4627 行附近。
由于此前补写记录时命中了较早的固定端口验证块，F77-F80 在文件物理顺序上早于 F73-F76。
当前权威阅读顺序以阶段编号为准：F72 -> F73 -> F74 -> F75 -> F76 -> F77 -> F78 -> F79 -> F80。
```

后续记录从本尾部索引之后继续追加；若需要发布版进度日志，再做纯文档重排。

### Stage F81：Graph extension module 必须实际注册能力

目标：

```text
GraphSystem 的显式扩展加载不只要求模块存在 register 函数，还要求 register 调用后 registry 发生实际变化。
有 register 函数但没有注册 adapter/provider/effect/handler 的空扩展，必须 fail-closed。
```

权威链检查：

- 符合：`GraphSystem` 拥有扩展 registry 的注册权威。
- 符合：领域扩展模块只能通过 registry 注册能力，不能靠 import 副作用被视为已接入。
- 符合：空 register 是缺线，不是可忽略的 optional module。
- 符合：已经加载过的模块仍保持幂等；第一次加载时必须新增或替换至少一个能力对象。

修正点：

- `backend/graph_system/adapter_registry.py`
  - `load_runtime_algorithm_adapter_module()` 校验 `_ADAPTERS` 在 register 后发生变化。
- `backend/graph_system/context_provider_registry.py`
  - `load_graph_context_provider_module()` 校验 `_PROVIDERS` 在 register 后发生变化。
- `backend/graph_system/runtime_effect_registry.py`
  - `load_runtime_algorithm_effect_module()` 校验 `_HANDLERS` 在 register 后发生变化。
- `backend/graph_system/memory_candidate_registry.py`
  - `load_memory_candidate_payload_handler_module()` 校验 `_HANDLERS` 在 register 后发生变化。
- `backend/graph_system/work_order_handler_registry.py`
  - `load_deterministic_work_order_handler_module()` 校验 `_HANDLERS` 在 register 后发生变化。
- `backend/graph_system/quality_gate_registry.py`
  - `load_quality_gate_handler_module()` 校验 `_HANDLERS` 在 register 后发生变化。
- `backend/graph_system/revision_signal_registry.py`
  - `load_revision_signal_handler_module()` 同时检查 rejection handler 与 requeue patch handler 两个 registry，至少一个必须变化。

验证：

```text
python -m compileall backend/graph_system/adapter_registry.py backend/graph_system/context_provider_registry.py backend/graph_system/runtime_effect_registry.py backend/graph_system/memory_candidate_registry.py backend/graph_system/work_order_handler_registry.py backend/graph_system/quality_gate_registry.py backend/graph_system/revision_signal_registry.py backend/graph_system/extensions.py
  passed

Graph extension loader smoke:
  adapters ['project_network_work_product', 'writing_iteration']
  providers ['project_network_context', 'writing_graph_context']
  effects ['project_network_work_product_ingest']
  memory ['writing_review_memory_candidates']
  work_handlers ['writing_progress_receipt_router']
  quality ['writing_stage_business_acceptance']
  revision ['writing_review_verdict_revision_signal'] ['writing_chapter_revision_requeue_patch']

Empty register smoke:
  load_runtime_algorithm_adapter_module(empty_adapter_extension_for_smoke)
  -> ValueError runtime algorithm adapter module registered no adapters: empty_adapter_extension_for_smoke

Fixed-port smoke:
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
```

结论：通过。GraphSystem 扩展面不再允许空 register 假成功；能力注册缺线会在加载阶段暴露。

### Stage F82：Graph extension register 异常时回滚半注册状态

目标：

```text
GraphSystem 扩展加载必须具备事务语义。
register 函数如果先注册了一部分能力再抛错，registry 必须恢复到加载前状态，不能留下半接线能力。
```

权威链检查：

- 符合：扩展模块只有完整加载成功后才进入 `_LOADED_MODULES`。
- 符合：adapter / provider / effect / handler registry 的权威状态只接受完整成功的 register 结果。
- 符合：register 异常不被吞掉，错误继续向上暴露。
- 符合：revision signal registry 同时回滚 rejection handler 与 requeue patch handler 两张表。

修正点：

- `backend/graph_system/adapter_registry.py`
  - `load_runtime_algorithm_adapter_module()` register 异常时回滚 `_ADAPTERS`。
- `backend/graph_system/context_provider_registry.py`
  - `load_graph_context_provider_module()` register 异常时回滚 `_PROVIDERS`。
- `backend/graph_system/runtime_effect_registry.py`
  - `load_runtime_algorithm_effect_module()` register 异常时回滚 `_HANDLERS`。
- `backend/graph_system/memory_candidate_registry.py`
  - `load_memory_candidate_payload_handler_module()` register 异常时回滚 `_HANDLERS`。
- `backend/graph_system/work_order_handler_registry.py`
  - `load_deterministic_work_order_handler_module()` register 异常时回滚 `_HANDLERS`。
- `backend/graph_system/quality_gate_registry.py`
  - `load_quality_gate_handler_module()` register 异常时回滚 `_HANDLERS`。
- `backend/graph_system/revision_signal_registry.py`
  - `load_revision_signal_handler_module()` register 异常时同时回滚 `_HANDLERS` 与 `_PATCH_HANDLERS`。

验证：

```text
python -m compileall backend/graph_system/adapter_registry.py backend/graph_system/context_provider_registry.py backend/graph_system/runtime_effect_registry.py backend/graph_system/memory_candidate_registry.py backend/graph_system/work_order_handler_registry.py backend/graph_system/quality_gate_registry.py backend/graph_system/revision_signal_registry.py backend/graph_system/extensions.py
  passed

Adapter partial-register rollback smoke:
  partial adapter register -> RuntimeError boom_after_partial_register
  before []
  after []
  rolled_back True

Revision dual-registry rollback smoke:
  partial revision register -> RuntimeError boom_after_revision_register
  before_rejection []
  after_rejection []
  before_patch []
  after_patch []
  rolled_back True

Graph extension loader smoke:
  adapters ['project_network_work_product', 'writing_iteration']
  providers ['project_network_context', 'writing_graph_context']
  effects ['project_network_work_product_ingest']
  memory ['writing_review_memory_candidates']
  work_handlers ['writing_progress_receipt_router']
  quality ['writing_stage_business_acceptance']
  revision ['writing_review_verdict_revision_signal'] ['writing_chapter_revision_requeue_patch']

Fixed-port smoke:
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
```

结论：通过。GraphSystem 扩展加载现在具备事务边界；失败模块不会污染后续图运行能力集合。

### Stage F83：Graph extension registry 禁止同 id 静默覆盖

目标：

```text
GraphSystem 扩展能力 id 是接线标识，不能被后注册模块静默覆盖。
同一个 adapter/provider/effect/handler id 出现重复注册时必须 fail-closed，并由 F82 的事务边界回滚半注册结果。
```

权威链检查：

- 符合：registry 是扩展能力的唯一命名权威，同 id 代表同一条能力线。
- 符合：重复 id 是配置/扩展冲突，不是后写覆盖的正常更新。
- 符合：扩展加载仍保持事务语义；duplicate 在 register 阶段抛错后，loader 会恢复加载前 registry 状态。
- 符合：真实内置扩展没有 duplicate id，正常加载不受影响。

修正点：

- `backend/graph_system/adapter_registry.py`
  - `register_runtime_algorithm_adapter()` 对重复 `adapter_id` 抛错。
- `backend/graph_system/context_provider_registry.py`
  - `register_graph_context_provider()` 对重复 `provider_id` 抛错。
- `backend/graph_system/runtime_effect_registry.py`
  - `register_runtime_algorithm_effect_handler()` 对重复 `effect_kind` 抛错。
- `backend/graph_system/memory_candidate_registry.py`
  - `register_memory_candidate_payload_handler()` 对重复 `handler_id` 抛错。
- `backend/graph_system/work_order_handler_registry.py`
  - `register_deterministic_work_order_handler()` 对重复 `handler_id` 抛错。
- `backend/graph_system/quality_gate_registry.py`
  - `register_quality_gate_handler()` 对重复 `handler_id` 抛错。
- `backend/graph_system/revision_signal_registry.py`
  - `register_revision_rejection_signal_handler()` 和 `register_revision_requeue_patch_handler()` 分别对重复 `handler_id` 抛错。

验证：

```text
python -m compileall backend/graph_system/adapter_registry.py backend/graph_system/context_provider_registry.py backend/graph_system/runtime_effect_registry.py backend/graph_system/memory_candidate_registry.py backend/graph_system/work_order_handler_registry.py backend/graph_system/quality_gate_registry.py backend/graph_system/revision_signal_registry.py backend/graph_system/extensions.py
  passed

Graph extension loader smoke:
  adapters ['project_network_work_product', 'writing_iteration']
  providers ['project_network_context', 'writing_graph_context']
  effects ['project_network_work_product_ingest']
  memory ['writing_review_memory_candidates']
  work_handlers ['writing_progress_receipt_router']
  quality ['writing_stage_business_acceptance']
  revision ['writing_review_verdict_revision_signal'] ['writing_chapter_revision_requeue_patch']

Duplicate adapter smoke:
  duplicate adapter register -> ValueError duplicate runtime algorithm adapter id: duplicate_adapter_for_smoke
  before []
  after []
  rolled_back True

Duplicate revision smoke:
  duplicate revision register -> ValueError duplicate revision rejection signal handler id: duplicate_revision_for_smoke
  before_rejection []
  after_rejection []
  before_patch []
  after_patch []
  rolled_back True

Fixed-port smoke:
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
```

结论：通过。GraphSystem 扩展 registry 不再允许同 id 覆盖；扩展能力线的命名冲突会在注册阶段暴露并回滚。

### Stage F84：Graph extension 总加载器具备跨 registry 事务边界

目标：

```text
ensure_graph_extensions_loaded() 是 GraphSystem 扩展环境的总接线入口。
任一扩展类别加载失败时，已经加载成功的前序 registry 也必须回滚，不能留下半激活的扩展环境。
```

权威链检查：

- 符合：`GraphSystem` 总加载器拥有扩展环境的一致性边界。
- 符合：每个 registry 暴露最小 snapshot / restore 能力，只用于扩展加载事务，不承担领域决策。
- 符合：bootstrap 或 engagement dispatcher 调用 `ensure_graph_extensions_loaded()` 失败时，错误继续向上抛出，进程状态不保留前序半接线能力。
- 符合：成功加载后 `_LOADED=True`；失败回滚后 `_LOADED=False`，允许后续修复后重试。

修正点：

- `backend/graph_system/adapter_registry.py`
  - 增加 `snapshot_runtime_algorithm_adapter_registry()` / `restore_runtime_algorithm_adapter_registry()`。
- `backend/graph_system/context_provider_registry.py`
  - 增加 `snapshot_graph_context_provider_registry()` / `restore_graph_context_provider_registry()`。
- `backend/graph_system/runtime_effect_registry.py`
  - 增加 `snapshot_runtime_algorithm_effect_registry()` / `restore_runtime_algorithm_effect_registry()`。
- `backend/graph_system/memory_candidate_registry.py`
  - 增加 `snapshot_memory_candidate_payload_handler_registry()` / `restore_memory_candidate_payload_handler_registry()`。
- `backend/graph_system/work_order_handler_registry.py`
  - 增加 `snapshot_deterministic_work_order_handler_registry()` / `restore_deterministic_work_order_handler_registry()`。
- `backend/graph_system/quality_gate_registry.py`
  - 增加 `snapshot_quality_gate_handler_registry()` / `restore_quality_gate_handler_registry()`。
- `backend/graph_system/revision_signal_registry.py`
  - 增加 `snapshot_revision_signal_handler_registry()` / `restore_revision_signal_handler_registry()`。
- `backend/graph_system/extensions.py`
  - `ensure_graph_extensions_loaded()` 在加载前拍摄全部 registry 快照；
  - 任一加载步骤异常时恢复全部 registry，并保持 `_LOADED=False`；
  - 成功加载全部类别后才设置 `_LOADED=True`。

验证：

```text
python -m compileall backend/graph_system/adapter_registry.py backend/graph_system/context_provider_registry.py backend/graph_system/runtime_effect_registry.py backend/graph_system/memory_candidate_registry.py backend/graph_system/work_order_handler_registry.py backend/graph_system/quality_gate_registry.py backend/graph_system/revision_signal_registry.py backend/graph_system/extensions.py
  passed

Graph extension loader smoke:
  adapters ['project_network_work_product', 'writing_iteration']
  providers ['project_network_context', 'writing_graph_context']
  effects ['project_network_work_product_ingest']
  memory ['writing_review_memory_candidates']
  work_handlers ['writing_progress_receipt_router']
  quality ['writing_stage_business_acceptance']
  revision ['writing_review_verdict_revision_signal'] ['writing_chapter_revision_requeue_patch']

Total-loader rollback smoke:
  adapters load first, context provider module registers no providers
  -> ValueError graph context provider module registered no providers: empty_context_extension_for_total_loader_smoke
  loaded_flag False
  adapters_after_failure []
  providers_after_failure []
  rolled_back True

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 29728
  started backend on 127.0.0.1:8003 pid 13456
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
  127.0.0.1:3000 listener -> single frontend process 10596
  127.0.0.1:8003 listener -> single project backend process 13456
```

结论：通过。GraphSystem 扩展环境现在具备总事务边界；加载失败不会留下跨 registry 的半激活状态。

### Stage F85：GraphSystem root TaskRun 缺失路径 fail-closed

目标：

```text
GraphRuntime.start() 仍保留 root TaskRun 作为 graph run 的协调锚点。
但 GraphLoop / runner / background supervisor / facade 不允许在 root TaskRun 缺失时继续运行、提交状态或把缺失解释成“无控制信号”。
```

权威链检查：

- 符合：`GraphRuntime` 是 graph run 启动与 root TaskRun 锚点创建权威。
- 符合：`GraphLoop` 是图状态推进权威，但不是 TaskRun 补建权威；formal run 同步发现 root TaskRun 缺失时必须暴露断线。
- 符合：`GraphRunRunner` 和 `GraphRunBackgroundSupervisor` 只读取 runtime control，不在缺 root TaskRun 时自行推断“可继续运行”。
- 符合：`GraphSystem` facade 提交 runner 结果时要求 graph run 与 root TaskRun 均存在，不再跳过 TaskRun 更新后继续写 graph_run 投影。

修正点：

- `backend/graph_system/facade.py`
  - `start_run()` 在 `GraphRuntime.start()` 后要求 state index 能读回 root TaskRun；缺失时抛错，不再返回内存 fallback。
  - `_commit_runner_result()` 要求 graph run 与 root TaskRun 均存在；缺失时抛错，不再静默跳过 task run 状态更新。
  - `_task_run_from_payload()` 删除 fallback 返回，只接受真实 `TaskRun` 或 dict payload。
- `backend/graph_system/loop.py`
  - `_update_formal_runs()` 要求 `GraphLoopState.task_run_id` 存在并能读到 root TaskRun；缺失时抛错。
  - formal run 同步不再通过 `if current_task is not None` 静默跳过。
- `backend/graph_system/runner.py`
  - `_root_control_boundary()` 在 state 有效但 root TaskRun id 缺失或对象缺失时抛错。
- `backend/graph_system/background_supervisor.py`
  - `_root_control_boundary()` 和 `_mark_root_graph_run_paused()` 在 root TaskRun 缺失时抛错，不再把缺失当成无 pause/stop 控制。

验证：

```text
python -m compileall backend/graph_system/facade.py backend/graph_system/loop.py backend/graph_system/background_supervisor.py backend/graph_system/runner.py
  passed

Focused smoke: runner/background root control boundary missing root TaskRun
  runner GraphRun root TaskRun not found: taskrun:missing
  background GraphRun root TaskRun not found: taskrun:missing

Focused smoke: GraphLoop formal run sync missing root TaskRun
  GraphLoop root TaskRun not found: taskrun:missing

Focused smoke: GraphSystem runner result commit missing root TaskRun
  GraphRun root TaskRun not found while committing runner result: taskrun:missing

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 13456
  started backend on 127.0.0.1:8003 pid 23548
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000 -> 200
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
  127.0.0.1:3000 listener -> single frontend process 10596
  127.0.0.1:8003 listener -> single project backend process 23548
```

结论：通过。GraphSystem root TaskRun 锚点缺失现在会在图循环同步、runner 控制边界、后台调度控制边界和 runner result commit 边界明确失败，不再作为“无控制信号”或“可跳过状态同步”继续运行。

### Stage F86：Engagement closeout 改为 GraphRun monitor 驱动

目标：

```text
EngagementRun 是 TaskSystem 的承接运行记录。
graph_task_run 类型的 closeout 不能再以 root TaskRun.status / TaskRun artifacts 作为任务完成真相。
closeout 应以 EngagementRun.workflow_run_id 指向的 GraphRun monitor / GraphResult 为收口依据。
```

权威链检查：

- 符合：`EngagementDispatcher` 启动 graph task 后保存 `workflow_run_id=start.graph_run.graph_run_id`，这是承接运行与 GraphSystem 的稳定连接。
- 符合：`GraphSystem.get_graph_run_monitor()` 是 GraphRun / GraphLoopState / GraphResult 的只读投影入口。
- 符合：`TaskSystem.engagement.closeout` 只同步 EngagementRun 状态和人类可查 closeout，不执行图、不推进节点、不读取旧 TaskRun 作为完成真相。
- 符合：旧 `sync_engagement_runs_for_terminal_task(task_run_id=...)` helper 没有调用点，且命名/入参已经不符合 GraphRun closeout 权威，已删除。

修正点：

- `backend/task_system/engagement/closeout.py`
  - `sync_engagement_run_closeout()` 要求 `strategy_kind=graph_task_run`，并通过 `workflow_run_id` 读取 GraphRun monitor。
  - terminal 判定改为 `graph_loop_state.status / graph_run.status`，支持 `completed / failed / blocked / cancelled / canceled / stopped`。
  - closeout 写入 `graph_run_status / graph_run_terminal_reason / node_result_ref_count`，不再写 `task_run_status / task_run_terminal_reason`。
  - artifact refs 和 verification refs 改从 `graph_result.artifact_refs` 与 `graph_result.diagnostics` 提取。
  - 删除 `_task_run_artifacts()`、`_verification_refs(task_run)` 和 `_engagement_status_from_task_status()`。
  - 删除 `sync_engagement_runs_for_terminal_task()`。
- `backend/task_system/engagement/__init__.py`
  - 删除 `sync_engagement_runs_for_terminal_task` 导出。

验证：

```text
python -m compileall backend/task_system/engagement/closeout.py backend/task_system/engagement/__init__.py backend/api/task_system.py
  passed

rg -n "sync_engagement_runs_for_terminal_task|task_run_status|TaskRun|state_index|get_task_run|get_task_run_artifacts|terminal_task" backend/task_system/engagement backend/api/task_system.py -g "*.py"
  no matches

Engagement closeout smoke with TemporaryDirectory and GraphSystemFake:
  runtime_host exposes graph_system.get_graph_run_monitor only; no state_index
  changed True
  status completed
  graph_run_status completed
  artifact_count 1
  verification_count 1

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 23548
  started backend on 127.0.0.1:8003 pid 25024
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
  127.0.0.1:3000 listener -> single frontend process 10596
  127.0.0.1:8003 listener -> single project backend process 25024
```

结论：通过。Engagement closeout 的完成依据已经从旧 root TaskRun 转到 GraphRun monitor / GraphResult；TaskSystem 只同步承接运行记录，不再把旧 TaskRun 当作 graph_task_run 的任务真相。

### Stage F87：recent_work_outcome 改为 TaskWorkEnvironment 事实源

目标：

```text
recent_work_outcome 会进入动态上下文，是给 agent 的只读路标。
它不能再从旧 state_index.list_session_task_runs() 推断最近任务结果。
当没有 active work / continuation 时，应从 TaskSystem 的 SessionTaskBinding -> TaskWorkEnvironment 读取最近 terminal task environment。
```

权威链检查：

- 符合：`TaskWorkEnvironment` 是 request_task_run 后的任务真相；Harness 入口只读取并投影最近结果，不决定恢复或执行。
- 符合：`recent_work_outcome` 保持只读事实，不产生控制信号、不续跑任务。
- 符合：动态上下文投影保留 `task_environment_id / task_instance_id / work_product_refs`，agent 能看到新任务环境坐标。
- 符合：旧 `_looks_like_chat_task_run()` 和旧 `harness.runtime.recent_work_outcome` 事实源已删除。

修正点：

- `backend/harness/entrypoint/runtime_facade.py`
  - `active_work_context is None` 时调用 `_recent_work_outcome_from_latest_task_environment()`。
  - 新方法通过 `TaskEnvironmentRepository.list_session_bindings()` 找到当前 session 的 foreground/controller binding。
  - 只选择 `completed / failed / aborted / blocked` 或带终止原因的 TaskWorkEnvironment。
  - 输出 `task_environment_id / task_instance_id / task_kind / work_product_refs`，authority 改为 `task_system.task_environment.recent_work_outcome`。
  - 删除旧 `_recent_work_outcome_from_latest_task()` 中的 `state_index.list_session_task_runs()`、`project_task_run()` 和 `_looks_like_chat_task_run()` 逻辑。
- `backend/harness/runtime/context_message_producers.py`
  - `_recent_work_outcome_origin_ref()` 优先使用 `task_environment_id`，没有时才回退 `task_run_id`。
- `backend/harness/runtime/dynamic_context/history_projector.py`
  - recent work projection 增加 `task_environment_id / task_instance_id / task_kind / work_product_refs`。

验证：

```text
python -m compileall backend/harness/entrypoint/runtime_facade.py backend/harness/runtime/context_message_producers.py backend/harness/runtime/dynamic_context/history_projector.py
  passed

rg -n "_recent_work_outcome_from_latest_task\(|_looks_like_chat_task_run|harness\.runtime\.recent_work_outcome|list_session_task_runs\(session_id\)" backend/harness/entrypoint/runtime_facade.py backend/harness/runtime/context_message_producers.py backend/harness/runtime/dynamic_context/history_projector.py
  no matches

TaskWorkEnvironment recent outcome smoke with TemporaryDirectory:
  created real TaskWorkEnvironment + SessionTaskBinding
  authority task_system.task_environment.recent_work_outcome
  task_environment_id True
  status completed
  goal 完成任务系统重构切片
  work_product_refs [{'work_product_id': 'workproduct:one'}]

Dynamic context projection smoke:
  origin recent_work_outcome:taskenv:one:completed:05176bd0d063d096
  task_environment_id taskenv:one
  work_product_refs [{'work_product_id': 'wp:one', 'product_kind': '', 'status': ''}]

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 25024
  started backend on 127.0.0.1:8003 pid 25668
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200 authority harness.run_monitor
  127.0.0.1:3000 listener -> single frontend process 10596
  127.0.0.1:8003 listener -> single project backend process 25668
```

结论：通过。recent_work_outcome 的动态上下文路标已经从旧 TaskRun 记录切到 TaskWorkEnvironment；agent 看到的是任务环境坐标和只读结果，不再从旧 TaskRun 状态推断最近工作。

### Stage F88：移除旧 TaskRun continuation/recovery 记录权威

目标：

```text
Harness 不再通过旧 TaskRun continuation record / recovery packet 判断是否可以同运行续跑。
旧 selector 只保留上下文恢复状态投影；任务继续、暂停、停止和恢复控制权归 TaskWorkEnvironment。
```

权威链检查：

- 符合：`TaskWorkEnvironment` 是持久任务环境与可控 current work 的权威；Harness 入口只读取 active work / recent work，不再创建旧 TaskRun 续跑句柄。
- 符合：`select_session_continuation()` 现在只报告旧 selector 已移除和 session context recovery 状态，不再返回 `ContinuationRecord`。
- 符合：chat continuation API 只暴露 `available=false`、`task_continuation_authority=task_system.task_work_environment`，不再给前端一个可误用的旧 record 形状。
- 符合：active work control 不再接受 `same_run_resume` 策略；继续当前工作必须回到当前 turn 的普通行动面或 TaskWorkEnvironment 控制面。

修正点：

- `backend/harness/continuation/selector.py`
  - 删除 `ContinuationRecord` 字段和导入。
  - `to_dict()` 改为只读投影：`available=false`、`legacy_task_run_selector=removed`、`task_continuation_authority=task_system.task_work_environment`。
- `backend/harness/continuation/__init__.py`
  - 删除 `ContinuationRecord`、`continuation_record_from_payload`、`build_recovery_packet` 导出。
- 删除旧文件：
  - `backend/harness/continuation/record.py`
  - `backend/harness/continuation/recovery_packet.py`
  - `backend/harness/loop/task_run_recovery_state.py`
  - `backend/tests/task_run_status_gateway_contract_test.py`
- `backend/harness/entrypoint/runtime_facade.py`
  - 删除等待 `continuation_selection.record` 的入口分支。
  - 删除 `_recent_work_outcome_from_continuation_record()`，recent work 只从 TaskWorkEnvironment 事实源投影。
- `backend/api/chat.py`
  - `/chat/sessions/{session_id}/continuations/latest` 不再返回旧 record。
  - run restore contract 的 `continuation_available` 固定为 false，恢复事实由 context recovery / active work / TaskWorkEnvironment 表达。
- `backend/harness/loop/active_work.py`
  - `_normalize_continuation_strategy()` 删除 `same_run_resume`，只接受 `already_running / task_environment_control / defer / none`。
- `frontend/src/lib/api/types.ts`
  - 删除 `SessionContinuationRecord` 类型。
  - `SessionContinuationProjection` 改为旧 selector 移除投影。
- `frontend/src/lib/api/chatStream.ts`
  - 删除 `SessionContinuationRecord` import。

验证：

```text
rg -n "resume_task_recovery|same_run_executable|build_recovery_packet|ContinuationRecord|continuation_record_from_payload|same_run_resume|_recent_work_outcome_from_continuation_record|selection\.record|SessionContinuationRecord" backend/harness backend/api frontend/src/lib/api -g "*.py" -g "*.ts" -g "*.tsx"
  no matches

rg -n "record\?: SessionContinuationRecord|same_run_executable|continuation_available = bool\(selection\.record|selection\.record|legacy_task_run_continuation_removed" backend/harness backend/api frontend/src -g "*.py" -g "*.ts" -g "*.tsx"
  only backend/harness/continuation/selector.py reason code remains

python -m compileall backend/harness/continuation/selector.py backend/harness/continuation/__init__.py backend/harness/loop/active_work.py backend/harness/entrypoint/runtime_facade.py backend/api/chat.py
  passed

cd frontend && npx tsc --noEmit
  passed

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 25668
  started backend on 127.0.0.1:8003 pid 13160
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  127.0.0.1:3000 listener -> single frontend process 10596
  127.0.0.1:8003 listener -> single project backend process 13160
```

结论：通过。旧 TaskRun continuation/recovery packet 已从执行入口、API 投影和前端类型中移除；任务恢复/控制权不会再从旧 TaskRun 句柄进入 Harness，后续恢复语义应继续沿 TaskWorkEnvironment 和 GraphRun monitor 收敛。

### Stage F89：GraphSystem 扩展清单迁出领域硬编码

目标：

```text
GraphSystem 只提供图扩展注册表和事务化加载器。
writing / project network 等产品领域扩展清单由应用启动层组合，不写在 graph_system 包内。
```

权威链检查：

- 符合：`GraphSystem` 仍拥有算法 adapter、context provider、effect handler 等注册表，以及加载失败回滚边界。
- 符合：`bootstrap.graph_extensions` 作为应用组合层，声明本产品要加载的 writing graph 与 project network task 扩展。
- 符合：`ProjectNetworkTasks` 仍只作为图任务适配包注册 adapter/provider/effect handler；`GraphSystem` 不 import 领域包，也不识别 `project_network` 业务语义。
- 符合：`TaskSystem.engagement.dispatcher` 在缺少 runtime_host.graph_system 时只确保应用扩展已加载，再创建 GraphSystem；不再从 GraphSystem 获取领域默认清单。

修正点：

- `backend/graph_system/extensions.py`
  - 删除 `RUNTIME_ALGORITHM_ADAPTER_MODULES / GRAPH_CONTEXT_PROVIDER_MODULES / RUNTIME_ALGORITHM_EFFECT_MODULES` 等领域默认常量。
  - 新增 `GraphExtensionModules`，`ensure_graph_extensions_loaded(modules)` 只接收外部传入的模块集合。
  - 保留跨 registry snapshot/restore；加载失败时恢复各注册表并恢复已加载 fingerprint。
- `backend/bootstrap/graph_extensions.py`
  - 新增应用扩展组合清单 `APP_GRAPH_EXTENSION_MODULES`。
  - 新增 `ensure_app_graph_extensions_loaded()`，统一加载 writing graph 与 project network task 扩展。
- `backend/bootstrap/app_runtime.py`
  - 初始化阶段改为调用 `ensure_app_graph_extensions_loaded()`。
- `backend/task_system/engagement/dispatcher.py`
  - fallback 创建 GraphSystem 前改为调用 `ensure_app_graph_extensions_loaded()`。

验证：

```text
rg -n "project_network_tasks|project_network_system|task_system\.writing_graphs" backend/graph_system -g "*.py"
  no matches

rg -n "ensure_graph_extensions_loaded\(|GraphExtensionModules|ensure_app_graph_extensions_loaded|graph_system\.extensions" backend -g "*.py"
  graph_system/extensions.py keeps generic loader
  bootstrap/graph_extensions.py owns APP_GRAPH_EXTENSION_MODULES
  bootstrap/app_runtime.py and task_system/engagement/dispatcher.py call ensure_app_graph_extensions_loaded()

python -m compileall backend/graph_system/extensions.py backend/bootstrap/graph_extensions.py backend/bootstrap/app_runtime.py backend/task_system/engagement/dispatcher.py
  passed

Application extension load smoke:
  ensure_app_graph_extensions_loaded(); ensure_app_graph_extensions_loaded()
  adapters ['project_network_work_product', 'writing_iteration']
  providers ['project_network_context', 'writing_graph_context']
  effects ['project_network_work_product_ingest']

Failure rollback smoke:
  ensure_graph_extensions_loaded(GraphExtensionModules(runtime_algorithm_adapter_modules=('not_a_real_graph_extension_module',)))
  failed True
  before ['project_network_work_product', 'writing_iteration']
  after ['project_network_work_product', 'writing_iteration']
  rolled_back True

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 13160
  started backend on 127.0.0.1:8003 pid 39668
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  127.0.0.1:3000 listener -> single frontend process 10596
  127.0.0.1:8003 listener -> single project backend process 39668
```

结论：通过。GraphSystem 核心现在不再携带 writing/project-network 领域扩展清单；图任务领域能力通过应用启动层加载并进入 GraphSystem 注册表，保持母体算法系统与领域任务包分离。

### Stage F90：移除旧 Harness TaskRun 控制入口，补齐 GraphRun stop 控制面

目标：

```text
Harness TaskRun 不再作为 pause/resume/stop/approval 的可执行控制权威。
GraphRun 的运行控制由 GraphSystem facade/API 承接；TaskWorkEnvironment 控制信号桥只把环境信号转交给 GraphSystem。
前端 store 不再保留旧 active TaskRun 控制 action。
```

权威链检查：

- 符合：单 agent Harness 只保留 TaskRun/TurnRun trace、artifacts、memory receipts 等观察入口；不再暴露 `/harness/task-runs/{id}/pause|resume|stop|approve-*` 前端 wrapper。
- 符合：GraphSystem facade 新增 `request_graph_run_stop()`，和既有 pause/resume 同层，统一写入 root GraphRun 的 `runtime_control`。
- 符合：GraphSystem background supervisor 在 `stop_requested` 边界将 root TaskRun 与 GraphRun 收口为 `stopped`，不会永远停留在控制请求态。
- 符合：TaskWorkEnvironment control signal bridge 支持 `stop_requested / abort_requested` 转交 GraphSystem stop；任务环境只发控制信号，不直接操控 TaskRun。
- 符合：前端图任务停止改为 `stopGraphRun(graph_run_id, graph_config_id)`，不再通过 root TaskRun 反向控制。
- 符合：Harness `task_run_state_view` 不再投影 `same_run`/`ready_to_continue` 可执行语义；普通 TaskRun 状态只作为展示事实，`can_pause/can_resume/can_stop` 固定为 false。

修正点：

- `backend/graph_system/facade.py`
  - 新增 `_GRAPH_RUN_STOP_REQUESTED / _GRAPH_RUN_STOPPED`。
  - 新增 `request_graph_run_stop()`，写入 `graph_run_stop_requested` 事件、root TaskRun diagnostics 和 GraphRun runtime object control 状态。
  - `_update_graph_run_control_status()` 支持写入 terminal reason。
- `backend/api/graph_system.py`
  - 新增 `POST /graph-system/graph-runs/{graph_run_id}/stop`。
- `backend/graph_system/background_supervisor.py`
  - 将原 pause 边界函数重命名为 `_mark_root_graph_run_control_boundary()`。
  - 新增 `_mark_root_graph_run_stopped()`，在 stop 控制边界将 root TaskRun 和 GraphRun 收口为 stopped。
- `backend/task_system/work_environments/control_signal_bridge.py`
  - `stop_requested / abort_requested` 现在桥接到 GraphSystem stop。
- `backend/harness/task_run_state_view.py`
  - 删除旧 `_resumable_breakpoint()`。
  - 删除 `ready_to_continue` 分支。
  - 移除 TaskRun same-run resume 投影；控制能力不再从 TaskRun state view 产生。
- `backend/harness/loop/active_work.py`
  - 删除未使用的 `same_run_allowed` 字段。
- `backend/harness/entrypoint/runtime_facade.py`
  - 删除 active work context 中的 `same_run_allowed=False` 投影。
- `frontend/src/lib/api/harness.ts`
  - 删除旧 Harness TaskRun control wrapper。
- `frontend/src/lib/api/graph.ts`
  - 新增 `stopGraphRun()`。
- `frontend/src/lib/store/runtime.ts`
  - 删除 `pauseActiveTaskRun / resumeActiveTaskRun / stopActiveTaskRun` action 和私有实现。
  - 删除旧 approval/resume 推断 helper 和 pause stream boundary helper。
  - `stopBoundTaskGraphRun()` 改走 GraphRun control。
- `frontend/src/lib/store/types.ts`
  - 删除旧 active TaskRun control action 类型。
- `frontend/src/lib/store/runtime.test.ts`
  - 删除保护旧 Harness TaskRun control 的测试段。
  - 图任务停止断言改为 `stopGraphRun()`。

验证：

```text
rg -n "pauseHarnessTaskRun|resumeHarnessTaskRun|approveHarnessTaskRun|stopHarnessTaskRun|pauseActiveTaskRun|resumeActiveTaskRun|stopActiveTaskRun|same_run|ready_to_continue|_resumable_breakpoint|same_run_allowed" backend frontend/src -g "*.py" -g "*.ts" -g "*.tsx"
  no matches

python -m compileall backend/graph_system/facade.py backend/graph_system/background_supervisor.py backend/api/graph_system.py backend/task_system/work_environments/control_signal_bridge.py backend/harness/task_run_state_view.py backend/harness/loop/active_work.py backend/harness/entrypoint/runtime_facade.py
  passed

cd frontend && npx tsc --noEmit
  passed

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 39668
  started backend on 127.0.0.1:8003 pid 36600
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  POST http://127.0.0.1:8003/api/graph-system/graph-runs/grun__missing/stop with missing graph_config_id -> 404 {"detail":"ExecutableGraphConfig not found"}
  127.0.0.1:3000 listener -> single frontend process 10596
  127.0.0.1:8003 listener -> single project backend process 36600
```

结论：通过。旧 Harness TaskRun 可执行控制链已经从前端/API/状态投影中移除；GraphRun stop 作为 GraphSystem 控制能力补齐，任务环境控制信号也能沿正确权威链转交给图运行系统。

### Stage F91：TaskReducer 改为 active lease 权威归并边界

目标：

```text
EpisodeResult 只能由当前持有 TaskWorkEnvironment active lease 的 episode 归并。
成功 reduction 后由 TaskReducer 触发 lease release；GraphSystem / Harness 外层 finally 只负责未归并成功的异常清理。
非当前 lease 的 release / stale recovery 不得清掉 TaskWorkEnvironment 的 active lease 指针。
```

权威链检查：

- 符合：`TaskReducer` 在写 episode terminal state、EpisodeResult、WorkProduct 和 TaskEvent 前，会读取当前 `TaskWorkEnvironment`、stored `AgentExecutionEpisode` 和 `TaskEnvironmentLease`。
- 符合：reducer 要求 `active_episode_id == episode_id`、`active_lease_id == episode.lease_id`、lease 属于同一环境、状态为 `active` 且未过期；没有 lease、旧 episode、过期 lease 都不能推进任务状态。
- 符合：成功 reduction 后，lease release 进入 `TaskReductionResult.lease_release`，调用方可以投影释放结果，但不再拥有成功路径的第二释放权威。
- 符合：`GraphSystem.execute_work_order()` 成功记录节点结果后直接使用 reducer projection 中的 `lease_release`；只有执行或归并未完成时，finally 才调用 release 兜底。
- 符合：`HarnessRuntimeFacade` 的普通 task episode 成功归并后也使用 reducer projection 的 `lease_release`；异常路径仍保留 release 清理。
- 符合：`TaskWorkEnvironmentService.release_episode_lease()` 和 `recover_stale_leases()` 只在释放/过期的 lease 正是环境当前 active lease 时，才清理 `active_lease_id / active_episode_id`。
- 符合：`GraphNodeTaskBindingService.record_work_order_result()` 不再先把 binding 写成 completed；只有 reducer 成功后才提交 completed / completed_with_failure，避免无 lease 结果制造假完成。

修正点：

- `backend/task_system/reducer.py`
  - `TaskReductionResult` 新增 `lease_release`。
  - `reduce_episode_result()` 新增 active lease 校验和 release projection。
  - 新增 `_validate_episode_owns_active_lease()`，固定 reducer 的 owner-token 边界。
- `backend/task_system/work_environments/service.py`
  - release / stale recovery 的 snapshot patch 改为只清理匹配当前 active lease 的指针。
  - 匹配当前 active episode 时同步清理 `active_episode_id`。
- `backend/task_system/graph_bindings/service.py`
  - `GraphNodeTaskResultProjection` 新增 `lease_release`。
  - result recording 将 graph-specific release metadata 交给 reducer。
  - binding completed 状态延后到 reducer 成功后写入。
- `backend/graph_system/facade.py`
  - work order 成功路径使用 `graph_node_task_result_projection.lease_release`。
  - finally 只在没有 release projection 时执行异常清理。
- `backend/harness/entrypoint/runtime_facade.py`
  - task environment episode 成功路径使用 `TaskReductionResult.lease_release`。
  - finally 只在 reduction 未提供 release projection 时执行异常清理。

验证：

```text
python -m compileall backend/task_system/reducer.py backend/task_system/work_environments/service.py backend/task_system/graph_bindings/service.py backend/graph_system/facade.py backend/harness/entrypoint/runtime_facade.py
  passed

TaskReducer lease smoke with TemporaryDirectory:
  reduced_status completed
  release_status released
  stored_lease_status released
  active_lease_id_empty True
  active_episode_id_empty True
  no_lease_rejected ValueError TaskReducer requires TaskWorkEnvironment active_lease_id

GraphNodeTaskBindingService lease smoke with TemporaryDirectory:
  graph_binding_status completed
  graph_episode_status completed
  graph_release_status released
  graph_stored_lease_status released
  graph_active_lease_empty True
  graph_active_episode_empty True
  graph_no_lease_rejected ValueError TaskReducer requires TaskWorkEnvironment active_lease_id
  graph_no_lease_binding_status bound

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 36600
  started backend on 127.0.0.1:8003 pid 29112
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  127.0.0.1:8003 listener -> single project backend process 29112
  127.0.0.1:3000 listener -> existing frontend process 10596
```

结论：通过。TaskSystem 的 episode result 归并现在受 active lease 强约束；旧 episode 或无 lease 的结果不能推进任务状态，Graph node binding 也不会在 reducer 失败时假完成。成功 reduction 的 lease 收口进入 TaskReducer 结果，GraphSystem/Harness 只保留异常清理边界。

### Stage F92：GraphNodeTaskBinding 状态跟随 lease 边界投影

目标：

```text
GraphNodeTaskBinding 只作为 work order 与 TaskWorkEnvironment 的绑定投影，不拥有调度权威。
binding 状态必须能反映 lease 边界：bound -> leased -> completed / waiting_resume。
完成态仍只能来自 reducer 成功归并后的 result recording。
```

权威链检查：

- 符合：`TaskWorkEnvironment` 和 `TaskEnvironmentLease` 仍是任务运行与租约事实源；binding 不决定是否可以执行。
- 符合：`begin_work_order_execution()` 在 acquire lease 成功后才把 binding 投影为 `leased`。
- 符合：`record_work_order_result()` 仍然只有 reducer 成功后才把 binding 写为 `completed / completed_with_failure`。
- 符合：fallback `release_work_order_execution_lease()` 只在没有 reducer result 的运行边界使用；释放后 binding 进入 `waiting_resume`，保留后续恢复或修复入口。
- 符合：stop/abort 类 release reason 会把非终态 binding 投影为 `aborted`；已经 completed / completed_with_failure / aborted 的 binding 不回退。

修正点：

- `backend/task_system/graph_bindings/service.py`
  - `begin_work_order_execution()` acquire lease 成功后写入 binding `leased`，并记录 active lease/event metadata。
  - `release_work_order_execution_lease()` 写入 `waiting_resume` 或 `aborted`，并记录 release lease/event metadata。
  - 新增 `_binding_status_for_lease_acquired()` 和 `_binding_status_for_lease_release()`，避免把终态 binding 回退。

验证：

```text
python -m compileall backend/task_system/graph_bindings/service.py backend/task_system/reducer.py backend/task_system/work_environments/service.py backend/graph_system/facade.py
  passed

GraphNodeTaskBindingService lease state smoke with TemporaryDirectory:
  begin_binding_status leased
  graph_binding_status completed
  graph_episode_status completed
  graph_release_status released
  graph_stored_lease_status released
  graph_active_lease_empty True
  graph_active_episode_empty True
  interrupted_release_status released
  interrupted_binding_status waiting_resume
  graph_no_lease_rejected ValueError TaskReducer requires TaskWorkEnvironment active_lease_id
  graph_no_lease_binding_status bound

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 29112
  started backend on 127.0.0.1:8003 pid 20008
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  127.0.0.1:8003 listener -> single project backend process 20008
```

结论：通过。GraphNodeTaskBinding 现在能准确投影图节点 work order 的 lease 边界：运行中可见 `leased`，无 result 的释放可见 `waiting_resume`，reducer 成功后才进入完成态。这减少了 GraphSystem / TaskSystem 之间的状态漂移，同时没有给 binding 增加新的调度权威。

### Stage F93：Reducer commit 写入 TaskCheckpoint 恢复锚点

目标：

```text
TaskSystem 必须拥有自己的任务环境 checkpoint；GraphSystem checkpoint 不能替代任务恢复锚点。
Reducer 成功提交 EpisodeResult / WorkProduct / TaskEvent 后，必须写 reducer_commit checkpoint。
Graph node result projection 应暴露 reducer checkpoint ref，供 monitor / resume / repair 后续链路使用。
```

权威链检查：

- 符合：`TaskCheckpoint` 归 `task_system.work_environments`，和 `TaskWorkEnvironment.latest_checkpoint_id` 同属任务环境事实源。
- 符合：`GraphSystem` 仍只拥有图运行 checkpoint；不保存任务环境 checkpoint。
- 符合：`TaskReducer` 在 event/result/product 写入后、lease release 前写 `reducer_commit` checkpoint，表示归并已经真实提交。
- 符合：checkpoint 内容来自结构化字段：episode、event、context package、work product ids、artifact refs、continuation hint 和 hash；不从自然语言报告反解析结构事实。
- 符合：`TaskEnvironmentRepository.upsert_checkpoint()` 写入 checkpoint 并更新 `latest_checkpoint_id`，不新增模型执行或语义判断权威。
- 符合：`GraphNodeTaskResultProjection` 和 GraphSystem summary 现在能携带 checkpoint id/kind，图运行层只引用，不拥有 checkpoint 写入。

修正点：

- `backend/task_system/work_environments/models.py`
  - 新增 `TaskCheckpoint` 和 `TaskCheckpointKind`。
- `backend/task_system/work_environments/repository.py`
  - 新增 `task_checkpoints` 表。
  - 新增 `upsert_checkpoint()`、`get_checkpoint()`、`list_checkpoints()`。
  - 写 checkpoint 时更新 `task_environments.latest_checkpoint_id`。
- `backend/task_system/work_environments/__init__.py`
  - 导出 `TaskCheckpoint`。
- `backend/task_system/reducer.py`
  - `TaskReductionResult` 新增 `checkpoint`。
  - `reduce_episode_result()` 成功写 result/event/product 后调用 `_write_reducer_commit_checkpoint()`。
- `backend/task_system/graph_bindings/service.py`
  - `GraphNodeTaskResultProjection` 新增 `checkpoint`。
- `backend/graph_system/facade.py`
  - graph node task result summary 暴露 `checkpoint_id / checkpoint_kind`。

验证：

```text
python -m compileall backend/task_system/work_environments/models.py backend/task_system/work_environments/repository.py backend/task_system/work_environments/__init__.py backend/task_system/reducer.py backend/task_system/graph_bindings/service.py backend/graph_system/facade.py backend/harness/entrypoint/runtime_facade.py
  passed

TaskReducer checkpoint smoke with TemporaryDirectory:
  checkpoint_kind reducer_commit
  checkpoint_event_id ""
  checkpoint_event_seq -1
  checkpoint_context_package True
  checkpoint_artifact_refs ['artifact:one']
  latest_checkpoint_match True
  checkpoint_list_count 1
  release_status released

TaskReducer checkpoint smoke with TaskEvent:
  event_checkpoint_event_type task_episode_result_recorded
  event_checkpoint_event_seq 3
  event_checkpoint_event_id_match True
  latest_checkpoint_match True
  latest_status completed
  release_status released

GraphNodeTaskBindingService projection checkpoint smoke:
  projection_checkpoint_kind reducer_commit
  projection_checkpoint_id True
  latest_checkpoint_match True
  projection_release_status released

Fixed-port smoke after backend restart:
  stopped project backend process on 127.0.0.1:8003 pid 20008
  started backend on 127.0.0.1:8003 pid 584
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  127.0.0.1:8003 listener -> single project backend process 584
```

结论：通过。TaskSystem 现在有了 reducer commit 级别的任务 checkpoint，任务环境可以通过 `latest_checkpoint_id` 找到最近一次成功归并边界；GraphSystem 只接收 checkpoint ref，不越权保存或解释任务恢复事实。

### Stage F94：Plan/Todo patch 进入任务环境事实层

目标：

```text
EpisodeResult.plan_patch / todo_patch 不能只作为 episode result JSON 保存。
TaskPlan 必须版本化、事件化；新的 active plan 会 supersede 旧 active plan。
TaskTodoItem 必须事件化保存，但 todo 不升级为 task，也不作为任务完成依据。
```

权威链检查：

- 符合：agent 仍只提交 `plan_patch / todo_patch` proposal；`TaskReducer` 负责校验、版本化、事件化和持久化。
- 符合：`TaskPlan` 进入 `task_plans` 表；旧 active plan 被显式写为 `superseded`，不静默覆盖。
- 符合：`TaskTodoItem` 进入 `task_todo_items` 表；todo 只是任务内执行焦点，不创建 graph node，不代表任务完成。
- 符合：plan/todo 变更都写入 `TaskEvent`，进入任务环境事件账本。
- 符合：checkpoint 仍由 reducer commit 产生，且会跟随 plan/todo 事件之后的最新事件边界。
- 符合：`state_update_proposals` 尚未接入独立状态模型；本阶段没有把它强塞进 snapshot，避免用不成熟字段污染任务真相。

修正点：

- `backend/task_system/work_environments/repository.py`
  - 新增 `task_plans` 表。
  - 新增 `task_todo_items` 表。
  - 新增 `upsert_task_plan()`、`get_task_plan()`、`list_task_plans()`。
  - 新增 `upsert_todo_item()`、`get_todo_item()`、`list_todo_items()`。
- `backend/task_system/reducer.py`
  - `TaskReductionResult` 新增 `task_plans / todo_items / events`。
  - 新增 `_apply_plan_patch()`：写 active plan，旧 active plan 进入 superseded，追加 `plan_proposed / plan_revised` 事件。
  - 新增 `_apply_todo_patch()`：写 todo item，追加 `todo_created / todo_updated` 事件。
  - checkpoint event boundary 改为 reducer 本轮最后一个事件。

验证：

```text
python -m compileall backend/task_system/work_environments/models.py backend/task_system/work_environments/repository.py backend/task_system/reducer.py backend/task_system/graph_bindings/service.py backend/graph_system/facade.py backend/harness/entrypoint/runtime_facade.py
  passed

TaskReducer plan/todo smoke with TemporaryDirectory:
  first_plan_count 1
  first_plan_status active
  first_todo_count 2
  first_event_types ['plan_proposed', 'todo_created', 'todo_created']
  repo_plan_statuses_first [(1, 'active')]
  repo_todo_statuses_first [('投影 active todo', 'active'), ('收紧 reducer 权威', 'done')]
  second_event_types ['plan_revised']
  plan_versions_after_second [(2, 'active'), (1, 'superseded')]
  active_plan_count 1
  superseded_plan_count 1
  checkpoint_kind reducer_commit
  release_status released

Fixed-port smoke after F94:
  existing backend listener on 127.0.0.1:8003 pid 40836
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  listeners -> 127.0.0.1:3000 pid 10596, 127.0.0.1:8003 pid 40836
```

结论：通过。Plan/Todo 现在不再只是 episode result 的内嵌 JSON，而是进入 TaskSystem 的可查询事实层和事件账本；后续 TaskContextPackage 可以从 active plan / active todo 构建当前上下文，且 completed todo 不必反复塞入动态上下文。

### Stage F95：state_update_proposals 进入状态提案账本

目标：

```text
EpisodeResult.state_update_proposals 不能只保存在 episode result JSON。
Agent 只能提交状态变更提案；TaskReducer 负责校验、归档和事件化。
在通用 TaskState 模型成熟前，不能把任意 proposal 直接写入 TaskWorkEnvironment snapshot。
```

权威链检查：

- 符合：`Harness` 仍只从 agent structured output 组装 `EpisodeResult.state_update_proposals`，不直接改任务状态。
- 符合：`TaskReducer` 把每条 proposal 归档为 `TaskStateProposal`，并追加 `state_update_proposed` 事件。
- 符合：`TaskStateProposal.status` 初始为 `recorded`，表达“agent 提案已被系统归档”，不表达“业务状态已应用”。
- 符合：`TaskWorkEnvironment` snapshot 没有新增泛化 state JSON 字段，避免把未审计语义塞进当前状态投影。
- 符合：checkpoint 继续以 reducer commit 为恢复锚点，并可通过 event boundary 追到本轮状态提案事件。
- 符合：后续如果某类 state proposal 有成熟 schema，应由专门 reducer policy 从 `recorded` 升级到 `applied`，而不是让通用账本越权。

修正点：

- `backend/task_system/work_environments/models.py`
  - 新增 `TaskStateProposal` 和 `TaskStateProposalStatus`。
- `backend/task_system/work_environments/repository.py`
  - 新增 `task_state_proposals` 表。
  - 新增 `upsert_state_proposal()`、`get_state_proposal()`、`list_state_proposals()`。
  - 新增任意 JSON value 读取 helper，避免状态值为 list/string/number 时被同类型校验误丢。
- `backend/task_system/work_environments/__init__.py`
  - 导出 `TaskStateProposal`。
- `backend/task_system/reducer.py`
  - `TaskReductionResult` 新增 `state_proposals`。
  - 新增 `_apply_state_update_proposals()`：规范化 proposal kind/path/operation/value/evidence/confidence，写入状态提案账本并追加事件。
  - reducer commit 的 event boundary 继续使用本轮 reducer 产生的最后一个事件。

验证：

```text
python -m compileall backend/task_system/work_environments/models.py backend/task_system/work_environments/repository.py backend/task_system/work_environments/__init__.py backend/task_system/reducer.py
  passed

TaskReducer state proposal smoke with TemporaryDirectory:
  proposal_count 2
  proposal_kinds ['risk_signal', 'current_state']
  proposal_statuses ['recorded', 'recorded']
  proposal_values ['查找命令需要继续优化', {'remaining_files': 1, 'reviewed_files': 3}]
  event_types_tail ['task_episode_lease_acquired', 'task_episode_result_recorded', 'state_update_proposed', 'state_update_proposed', 'task_episode_lease_released']
  checkpoint_kind reducer_commit
  lease_release_status released
  active_lease_after ''
  latest_checkpoint_match True

Fixed-port smoke after F95:
  stopped project backend process on 127.0.0.1:8003 pid 40836
  started backend on 127.0.0.1:8003 pid 6560
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  listeners -> 127.0.0.1:3000 pid 10596, 127.0.0.1:8003 pid 6560
```

结论：通过。`state_update_proposals` 现在进入任务环境事实层，但仍保持“提案账本”语义，不抢占未来 TaskState reducer policy 的应用权威。

### Stage F96：TaskContextPackage 接入任务事实视图

目标：

```text
Plan/Todo/StateProposal 已经进入任务事实层后，下一轮 episode 必须能看到当前任务事实。
TaskContextPackage 应携带裁剪后的 task_state_context，而不是让 agent 读取全量 event log。
UI/API detail projection 也应能审计 plan、todo、state proposal 和 checkpoint。
```

权威链检查：

- 符合：`TaskWorkEnvironmentService.prepare_task_episode()` 从 TaskStore 查询事实并构造 `task_state_context`。
- 符合：`TaskContextPackage` 持久保存 `task_state_context`，这是上下文包输入，不是新的状态写入权威。
- 符合：上下文只包含 active/latest plan、active/blocked/pending todo、recent recorded state proposals、latest refs 和 reducer checkpoints，不拼接全量历史。
- 符合：`Harness` 只把 `task_state_context` 放进 worker 可见任务输入，不从中反向修改任务。
- 符合：`TaskEnvironmentViewService.task_environment_detail()` 暴露 plan/todo/state proposal/checkpoint 查询结果，作为 present/query projection。

修正点：

- `backend/task_system/work_environments/models.py`
  - `TaskContextPackage` 新增 `task_state_context`。
- `backend/task_system/work_environments/repository.py`
  - `task_context_packages` 新增 `task_state_context_json`。
  - `upsert_context_package()` / `_context_package_from_row()` 接入该字段。
  - 新增窄 schema migration helper，确保已有 SQLite 表补齐新列。
- `backend/task_system/work_environments/service.py`
  - `prepare_task_episode()` 构建 task state context。
  - task state context 包含 active plan、focus todos、recorded state proposals、latest refs、reducer checkpoints。
- `backend/harness/entrypoint/runtime_facade.py`
  - task episode worker 输入显式包含 `task_state_context`。
- `backend/task_system/work_environments/view_service.py`
  - detail projection 暴露 task plans、todo items、state proposals、checkpoints 和对应 summary counts。

验证：

```text
python -m compileall backend/task_system/work_environments/models.py backend/task_system/work_environments/repository.py backend/task_system/work_environments/service.py backend/task_system/work_environments/view_service.py backend/harness/entrypoint/runtime_facade.py
  passed

TaskContextPackage task_state_context smoke with TemporaryDirectory:
  state_context_keys ['active_plan', 'authority', 'focus_todos', 'latest_refs', 'progress', 'recorded_state_proposals', 'reducer_checkpoints', 'status', 'task_environment_id', 'task_instance_id']
  active_plan_summary 先收紧任务上下文，再继续 reducer。
  focus_todo_titles ['检查 task_state_context']
  state_proposal_paths ['task.context.ready']
  checkpoint_count 1
  detail_plan_count 1
  detail_todo_count 1
  detail_state_proposal_count 1
  latest_context_package_has_state True

Fixed-port smoke after F96:
  stopped project backend process on 127.0.0.1:8003 pid 6560
  started backend on 127.0.0.1:8003 pid 30704
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  listeners -> 127.0.0.1:3000 pid 10596, 127.0.0.1:8003 pid 30704

TaskEnvironment API smoke after F96:
  GET http://127.0.0.1:8003/api/task-environments?limit=1 -> 200
  GET http://127.0.0.1:8003/api/task-environments/{environment_id}?event_limit=5&episode_limit=5&context_package_limit=2&work_product_limit=5 -> 200
  detail_has_task_plans True
  detail_has_todo_items True
  detail_has_state_proposals True
  detail_has_checkpoints True
```

结论：通过。任务环境的下一轮 episode 现在能拿到清洁的当前任务事实视图，Plan/Todo/StateProposal 不再只是被写入 store 后沉没在历史记录里。

### Stage F97：active turn / TaskRun 隐式绑定回扫

目标：

```text
确认 active turn 没有继续作为 TaskRun truth 或任务环境 truth。
确认旧 TaskRun 术语集中在哪里，避免在任务环境重构中误删 graph/runtime 仍在使用的主链。
```

权威链检查：

- 符合：`backend/harness/runtime/active_turn.py` 明确 `ActiveTurnRegistry` 只拥有 session 当前 turn handle，并在代码注释中与 TaskRun / RuntimeRun 分离。
- 符合：active turn 只保存 session_id、turn_id、turn_run_id、stream_run_id、state、steerable、owner_instance_id，不保存 task environment、plan、todo、checkpoint 或 graph node result。
- 符合：run monitor 可以把 active turn 投影成可见 item，但 `task_run_id` 为空，不把 active turn 伪装成 TaskRun。
- 符合：`task_run_state_view` 仍会查询 `agent_run_supervisor.active_cell_for_task_run()`，这是旧 TaskRun runtime cell 的活跃执行投影，不是 active turn 绑定任务真相。
- 需保留：旧 `TaskRun` 仍是 graph root、runtime monitor、event_log、execution_store、retention、background supervisor 的现存运行主链；不能在 TaskEnvironment F95/F96 这一刀中直接删除。

结论：

```text
active turn 绑定 TaskRun 的隐式 truth 问题本阶段没有发现新的越权点。
旧 TaskRun 清理应作为后续 graph/runtime migration 独立阶段推进：
  1. 先定义 GraphRun root 是否继续使用 TaskRun 作为 runtime anchor；
  2. 再定义 TaskEnvironment 与旧 TaskRun monitor 的桥接 projection；
  3. 最后替换 lifecycle / retention / event_log / execution_store 的 task_run_id scope。
```

### Stage F98：Run Monitor 接入 TaskEnvironment 资源导航

目标：

```text
TaskEnvironment 已经成为任务事实层后，运行监控必须能指向它。
Run Monitor 只能做展示和导航，不得成为任务状态、恢复或调度权威。
```

权威链检查：

- 符合：`MonitorResourceResolver` 新增 `task_environment_ref()`，只检查 `TaskEnvironmentRepository.get_task_environment()` 是否存在。
- 符合：run monitor item/signal 带出 `task_environment_id`，但不根据它改写 lifecycle、bucket、control capability 或 graph 状态。
- 符合：`/api/harness/run-monitor/resources/task_environment:{id}` 返回 resource ref，并提供 `/api/task-environments/{id}` 作为事实详情入口。
- 符合：状态事实仍由 `TaskEnvironmentViewService` / `TaskWorkEnvironmentService` / `TaskReducer` 拥有；run monitor 只是 present/query projection。

修正点：

- `backend/harness/runtime/run_monitor/resource_resolver.py`
  - 新增 `task_environment_ref()` 和 `_task_environment_exists()`。
- `backend/harness/runtime/run_monitor/projector.py`
  - monitor item 新增 `task_environment_id`。
  - `resource_refs` 增加 `task_environment` ref。
- `backend/harness/runtime/run_monitor/service.py`
  - resource endpoint 支持 `task_environment:` kind。
- `backend/harness/runtime/run_monitor/signals.py`
  - signal 和 raw refs 暴露 `task_environment_id`。

验证：

```text
python -m compileall backend/harness/runtime/run_monitor/resource_resolver.py backend/harness/runtime/run_monitor/projector.py backend/harness/runtime/run_monitor/service.py backend/harness/runtime/run_monitor/signals.py
  passed

Fixed-port smoke after F98:
  stopped project backend process on 127.0.0.1:8003 pid 30704
  started backend on 127.0.0.1:8003 pid 41268
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  listeners -> 127.0.0.1:3000 pid 10596, 127.0.0.1:8003 pid 41268

Run Monitor TaskEnvironment resource smoke:
  GET http://127.0.0.1:8003/api/harness/run-monitor/resources/task_environment:{environment_id} -> 200
  resource_kind task_environment
  resource_state available
  resource_api_endpoint /api/task-environments/{environment_id}
  monitor_signal_count 1
  signals_with_task_environment 1
```

结论：通过。Run Monitor 现在能把运行态信号连接到 TaskEnvironment 事实详情，但没有获得任务状态或恢复决策权。

### Stage F99：TaskEnvironment 列表视图增加任务事实摘要

目标：

```text
TaskEnvironment detail 已经能展示完整任务事实，但列表视图仍缺少可扫描的当前事实。
列表视图应能帮助 UI / agent 快速判断任务当前焦点，但不能反向修改任务 truth。
```

权威链检查：

- 符合：`TaskEnvironmentViewService._environment_list_item()` 只增加 `task_fact_summary` 查询投影。
- 符合：摘要从 `task_plans`、`task_todo_items`、`task_state_proposals`、`task_checkpoints` 读取，不扫描自然语言日志。
- 符合：摘要只保留 active/latest plan、focus todos、sample counts、latest reducer checkpoint，不输出全量历史。
- 符合：列表视图不计算任务完成、不释放 lease、不修改 graph binding，不拥有 reducer 权威。

修正点：

- `backend/task_system/work_environments/view_service.py`
  - list item 新增 `task_fact_summary`。
  - 新增 compact plan / todo / checkpoint projection。

验证：

```text
python -m compileall backend/task_system/work_environments/view_service.py
  passed

Fixed-port smoke after F99:
  stopped project backend process on 127.0.0.1:8003 pid 41268
  started backend on 127.0.0.1:8003 pid 16368
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  listeners -> 127.0.0.1:3000 pid 10596, 127.0.0.1:8003 pid 16368

TaskEnvironment list fact summary smoke:
  GET http://127.0.0.1:8003/api/task-environments?limit=1 -> 200
  has_fact_summary True
  fact_authority task_system.task_environment_view.fact_summary
  has_counts True
```

结论：通过。任务环境列表现在能提供轻量事实摘要，便于 UI 和 agent 从列表层快速定位当前任务焦点，同时不扩大查询层权威。

### Stage F100：GraphNode TaskContextPackage 接入同一任务事实视图

目标：

```text
普通 task episode 已经通过 TaskWorkEnvironmentService 获得 task_state_context。
GraphNodeTaskBindingService 不能手工创建缺少任务事实视图的 TaskContextPackage。
图节点任务和普通任务必须共享同一套任务事实投影算法。
```

权威链检查：

- 符合：`build_task_state_context_for_episode()` 从 `TaskWorkEnvironmentService` 内部 helper 提升为可复用函数。
- 符合：`GraphNodeTaskBindingService._upsert_context_package()` 使用同一 builder 构造 `task_state_context`。
- 符合：图节点 context package 仍由 TaskSystem 保存；GraphSystem 只通过 work order / binding 引用，不保存任务事实。
- 符合：context hash 包含 `task_state_context`，恢复时可以追踪该 episode 当时看到的任务事实视图。

修正点：

- `backend/task_system/work_environments/service.py`
  - `_task_state_context_for_episode()` 重命名为 `build_task_state_context_for_episode()`。
- `backend/task_system/graph_bindings/service.py`
  - Graph node context package 写入 `task_state_context`。
  - `_context_payload()` 包含 `task_state_context` 参与 package hash。

验证：

```text
python -m compileall backend/task_system/work_environments/service.py backend/task_system/graph_bindings/service.py
  passed

GraphNodeTaskBindingService context package smoke with TemporaryDirectory:
  state_context_authority task_system.task_context_package.state_context
  active_plan_summary 读取图节点事实并执行。
  focus_todo_titles ['执行图节点审查']
  state_proposal_paths ['graph.node.ready']
  package_hash_present True

Fixed-port smoke after F100:
  stopped project backend process on 127.0.0.1:8003 pid 16368
  started backend on 127.0.0.1:8003 pid 16688
  GET http://127.0.0.1:8003/health -> 200 {"status":"ok"}
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
  listeners -> 127.0.0.1:3000 pid 10596, 127.0.0.1:8003 pid 16688
```

结论：通过。图节点任务和普通任务现在共用同一套 task_state_context 构建逻辑，避免图任务工作流在上下文事实层掉队。

### Stage F101：旧 TaskRunLedger 事实模型冻结

目标：

```text
执行 21_authority_audit_and_continuous_refactor_plan.md 的 Phase 1。
旧 TaskRunLedger / TaskStepRun / TaskResult 不能继续作为新任务事实写入入口。
TaskRun 仍保留为 graph/runtime/event-log 的 legacy runtime anchor，但不再被解释为 TaskSystem task truth。
```

权威链检查：

- 符合：`TaskSystem = TaskWorkEnvironment / AgentExecutionEpisode / EpisodeResult / WorkProduct / TaskReducer`。
- 符合：`TaskRun` 暂时只是 runtime anchor payload；graph root、event log、monitor、retention 迁移前不能直接删除。
- 符合：旧 `TaskRunLedger` 模型只允许历史记录读取，不允许新建、推进、终结或投影新的旧式 `TaskResult`。
- 符合：删除保护旧 ledger 状态机的 regression test，不继续让旧模型作为目标行为。

修正点：

- `backend/task_system/tasks/run_models.py`
  - 删除旧 692 行状态机实现，收缩为 frozen read-only legacy payload 模块。
  - 保留 `TaskStepRun`、`TaskRunLedger`、`TaskResult` 历史数据读取形状。
  - 增加 legacy freeze 模块说明。
  - 新增 `LEGACY_TASK_RUN_LEDGER_MIGRATION_STATUS`。
  - `build_task_run_ledger()`、step mutation、terminalize/finalize、`project_task_result_from_ledger()` 均显式拒绝新写入。
- `backend/runtime/shared/models.py`
  - `TaskRun` docstring 改为 legacy runtime anchor 语义，明确新任务真相归 `TaskWorkEnvironment / AgentExecutionEpisode / WorkProduct / TaskReducer`。
- `backend/task_system/tasks/step_summary.py`
  - 删除无人引用且依赖旧 `TaskRunLedger` 的旧 step summary helper。
- `backend/tests/task_run_state_machine_regression.py`
  - 删除旧 regression test，避免继续保护已冻结的旧任务状态机。

验证：

```text
python -m compileall backend/task_system/tasks/run_models.py backend/runtime/shared/models.py backend/task_system/tasks
rg -n "from task_system\.tasks\.run_models|import task_system\.tasks\.run_models|from \.run_models|TaskRunLedger|build_task_run_ledger|project_task_result_from_ledger|finalize_runtime_task_run_ledger" backend/task_system backend/harness backend/graph_system backend/api -g "*.py"
git diff --check -- backend/task_system/tasks/run_models.py backend/runtime/shared/models.py backend/task_system/tasks/step_summary.py backend/tests/task_run_state_machine_regression.py backend/runtime/context_management/design_docs/execution_plans/hierarchical_ast_project_graph/20_refactor_progress_log.md
```

验证结果：

- compileall 通过。
- `rg` 只命中 `backend/task_system/tasks/run_models.py` 模块内部定义，未发现 harness / graph / API / 新 TaskSystem 主链外部引用。
- `git diff --check` 通过。

结论：Phase 1 的第一刀完成。旧 ledger 写路径已冻结且外部运行链路已断开；后续如果仍有代码尝试使用旧任务事实模型，会显式暴露。下一阶段建立 `TaskCommand / TaskScheduler`，不能恢复旧 ledger。

### Stage F102：TaskCommand / TaskScheduler 主链建立

目标：

```text
执行 21_authority_audit_and_continuous_refactor_plan.md 的 Phase 2 第一轮。
prepare/run/control/recovery 不再由 API 或 harness active-work 控制路径直接推进。
任务推进动作先进入 TaskCommand，再由 TaskScheduler 写 dispatch 并调用正确执行权威。
```

权威链检查：

- 符合：`API = command submission / projection`，不再直接调用 harness episode execution、control bridge 或 graph recovery bridge。
- 符合：`TaskScheduler = task command dispatch authority`，统一执行 prepare episode、run episode、control signal、graph recovery 和 stale lease recovery。
- 符合：`TaskWorkEnvironmentService` 仍是任务事实写入服务，但不再被 API 当作运行调度入口。
- 符合：`Harness` 仍是单 agent episode 执行权威，scheduler 只是通过 `execute_task_environment_episode()` 调用它。
- 符合：`GraphSystem` 仍是 graph run / node requeue / dispatch 权威，恢复命令桥只在 scheduler 路径下调用它。
- 符合：harness active-work control 也改为提交 `request_control_signal` command，避免对话控制路径绕过命令账本。

修正点：

- `backend/task_system/work_environments/models.py`
  - 新增 `TaskCommand`、`TaskDispatchRecord`。
  - 新增 command kind / status / dispatch status 语义。
- `backend/task_system/work_environments/repository.py`
  - 新增 `task_commands`、`task_dispatch_records` 表。
  - 新增 command / dispatch upsert、query、list 方法。
  - 修正 command 幂等：重复提交返回旧命令，但 scheduler 状态更新仍可推进同一 command。
- `backend/task_system/work_environments/scheduler.py`
  - 新增 `TaskScheduler`。
  - `submit_command()` 只入账；`dispatch_command()` 写 dispatch、执行、记录结果/错误和 task event。
  - 支持 `prepare_episode`、`run_episode`、`request_control_signal`、`request_pause`、`request_resume`、`request_stop`、`recover_stale_lease`、`resume_graph_run`、`requeue_graph_node`、`dispatch_ready_graph_nodes`。
  - 收紧失败判定：graph recovery bridge pending/failed 不会被记为 succeeded；harness episode `ok=false` 会让 command failed。
- `backend/task_system/work_environments/recovery_command_bridge.py`
  - 从 API 中迁出 graph recovery bridge。
  - 只作为 scheduler command handler 的 graph recovery adapter。
- `backend/api/task_system.py`
  - 新增 `/task-environments/{environment_id}/commands` list / submit。
  - `episodes/prepare` 改为提交并调度 `prepare_episode` command。
  - `episodes/{episode_id}/run` 改为提交并调度 `run_episode` command。
  - `control-signals` 改为提交并调度 `request_control_signal` command。
  - `recovery-actions` 改为提交并调度 graph recovery command。
  - `recover-stale-leases` 改为提交并调度全局 `recover_stale_lease` command。
  - 删除旧 API 内联 `_apply_task_environment_recovery_action_bridge` 及其专用 compact helper。
- `backend/harness/entrypoint/runtime_facade.py`
  - active-work control 改为提交 `request_control_signal` command。
  - final answer / control event 里带出 `task_command_ref`、`task_dispatch_ref`。
- `backend/task_system/work_environments/view_service.py`
  - TaskEnvironment detail 投影新增 `task_commands`、`task_dispatch_records` 和 summary count。

验证：

```text
python -m compileall backend/task_system/work_environments backend/api/task_system.py backend/harness/entrypoint/runtime_facade.py
rg -n "apply_task_environment_control_signal_bridge|request_control_signal\(|record_control_signal_handling\(|recover_stale_leases\(|execute_task_environment_episode\(|prepare_task_episode\(" backend/api backend/harness backend/task_system -g "*.py"
rg -n "task_environment_recovery_action_bridge|_apply_task_environment_recovery_action_bridge|_normalized_task_environment_recovery_action|_recovery_action_signal_kind" backend -g "*.py"
git diff --check -- backend/task_system/work_environments/models.py backend/task_system/work_environments/repository.py backend/task_system/work_environments/scheduler.py backend/task_system/work_environments/recovery_command_bridge.py backend/task_system/work_environments/view_service.py backend/task_system/work_environments/__init__.py backend/api/task_system.py backend/harness/entrypoint/runtime_facade.py backend/runtime/context_management/design_docs/execution_plans/hierarchical_ast_project_graph/20_refactor_progress_log.md
```

真实 smoke：

```text
TaskScheduler request_control_signal smoke:
  dispatch_ok True
  duplicate_status succeeded

TaskScheduler prepare_episode smoke:
  dispatch_ok True
  command_status succeeded
  context_package_count 1
  result_has_preparation True

TaskScheduler recovery smoke without graph binding:
  dispatch_ok False
  command_status failed
  bridge_reason graph_node_binding_incomplete

Fixed-port read-only smoke after F102:
  backend http://127.0.0.1:8003/health -> {"status":"ok"}
  GET /api/task-environments?limit=1 -> task_environment_count 1
  GET /api/task-environments/{environment_id}/commands?limit=1 -> authority task_system.task_command_api.list
  GET http://127.0.0.1:3000/api/harness/run-monitor?limit=1 -> 200
```

扫描结果：

- API / harness 不再直接调用 control signal bridge、graph recovery bridge、TaskWorkEnvironmentService 的 prepare/run/control/recovery 执行入口。
- 这些执行入口只剩 `TaskScheduler` 和其专用 bridge 持有。
- 旧 `task_environment_recovery_action_bridge` 名称在 backend Python 代码中无残留。

结论：Phase 2 第一轮完成。TaskCommand / TaskScheduler 已成为 prepare/run/control/recovery 的主命令链；下一阶段应进入 Phase 3，把 `runtime_facade.py` 中 task episode bridge / graph node bridge 的长 helper 拆到 harness 专用 executor 模块，避免 facade 继续膨胀。

### Stage F103：TaskEnvironmentEpisodeBridge 从 runtime_facade 拆出

目标：

```text
执行 21_authority_audit_and_continuous_refactor_plan.md 的 Phase 3 第一刀。
runtime_facade.py 不再承载 task episode 的上下文包解析、运行契约、profile 预检、结果归并和 reducer 投影。
facade 只保留 execute_task_environment_episode() 的薄转发入口。
```

权威链检查：

- 符合：`HarnessRuntimeFacade = API/stream adapter`，`execute_task_environment_episode()` 只转发到 bridge。
- 符合：`TaskEnvironmentEpisodeBridge = task episode bridge authority`，负责把已准备好的 TaskContextPackage 接入单 agent harness。
- 符合：`Harness` 仍是单 agent runtime 执行权威；bridge 只调用 facade 的 `_run_single_agent_turn()`、runtime assembly 和 message commit 能力。
- 符合：`TaskReducer` 仍是 episode result / work product / checkpoint 归并权威。
- 修正：agent profile 预检失败发生在 lease 前，不能走需要 active lease 的 reducer；现在改为 `task_episode_preflight_blocked` event + blocked snapshot。

修正点：

- `backend/harness/entrypoint/task_environment_episode_bridge.py`
  - 新增 `TaskEnvironmentEpisodeBridge`。
  - 迁入 task episode execution 主逻辑。
  - 迁入 task episode context package、session id/title、environment binding、runtime contract、model selection、workspace root、session context、worker prompt、lease ttl、executor result projection、exception projection、work product projection、snapshot patch 等 helper。
  - 新增 `_record_task_episode_preflight_blocked()`，处理 profile 缺失/未注册等 lease 前阻塞。
- `backend/harness/entrypoint/runtime_facade.py`
  - `execute_task_environment_episode()` 收缩为 `TaskEnvironmentEpisodeBridge(self).execute(...)`。
  - 删除 `_resolve_task_episode_agent_profile()`、`_ensure_task_episode_execution_session()`。
  - 删除所有 `_task_episode_*` helper、`_record_task_episode_execution_result()`、`_public_task_episode_executor_projection()`。
  - 清理不再使用的 `AgentExecutionEpisode / EpisodeRepository / EpisodeResult / TaskReducer / TaskContextPackage / TaskEvent / WorkProduct` imports。

验证：

```text
python -m compileall backend/harness/entrypoint/task_environment_episode_bridge.py backend/harness/entrypoint/runtime_facade.py
python -m compileall backend/harness/entrypoint backend/task_system/work_environments backend/api/task_system.py
rg -n "\bAgentExecutionEpisode\b|\bEpisodeRepository\b|\bEpisodeResult\b|\bTaskReducer\b|\bTaskContextPackage\b|\bTaskEvent\b|\bWorkProduct\b|_task_episode_|_record_task_episode_execution_result|_public_task_episode_executor_projection|_resolve_task_episode_agent_profile|_ensure_task_episode_execution_session" backend/harness/entrypoint/runtime_facade.py
```

真实 smoke：

```text
TaskEnvironmentEpisodeBridge blocked preflight smoke:
  status blocked
  ok False
  authority harness.task_environment_episode_bridge
  env_status blocked
  event_types ['task_environment_created', 'task_episode_prepared', 'task_episode_preflight_blocked']
```

结论：Phase 3 第一刀完成。Task episode bridge 已搬出 facade；下一刀应拆 `graph_node_work_order_bridge`，否则 facade 仍然持有 graph node work order 的长执行桥。

### Stage F104：GraphNodeWorkOrderBridge 从 runtime_facade 拆出

目标：

```text
执行 21_authority_audit_and_continuous_refactor_plan.md 的 Phase 3 第二刀。
runtime_facade.py 不再承载 graph node work order 的 profile 解析、context package 接入、session 创建、prompt 拼装、runtime assembly、事件压缩和 executor projection。
facade 只保留 GraphSystem 回调入口，并转发到 harness 内部专用 bridge。
```

权威链检查：

- 符合：`HarnessRuntimeFacade = API/stream adapter`，`_execute_graph_agent_work_order()` 只转发到 `GraphNodeWorkOrderBridge`。
- 符合：`GraphNodeWorkOrderBridge = graph node work order 到单 agent harness 的执行桥权威`，负责将已物化的 graph work order 接入单 agent runtime。
- 符合：`GraphSystem` 仍拥有图节点调度、结果验收和 loop state 推进；bridge 只返回 executor projection，不写 graph state。
- 符合：`TaskSystem` 仍拥有 task environment / episode / context package 事实；bridge 只读取 graph node preparation sink 已准备好的 payload。
- 符合：facade 中迁出的 graph-node helper 已删除，不保留冻结后不可达的旧状态机逻辑。

修正点：

- `backend/harness/entrypoint/graph_node_work_order_bridge.py`
  - 新增 `GraphNodeWorkOrderBridge`。
  - 迁入 graph node work order 的 agent profile 解析、task preparation payload 读取、session 创建、用户消息、runtime contract、model selection、workspace root、session context、current work boundary、harness event compact、executor result / blocked result projection。
  - 缺少或未注册 agent profile 时返回显式 blocked projection，不触发模型执行。
- `backend/harness/entrypoint/runtime_facade.py`
  - 新增 `GraphNodeWorkOrderBridge` import。
  - `_execute_graph_agent_work_order()` 收缩为 `GraphNodeWorkOrderBridge(self).execute(...)`。
  - `runtime_components` 标记 `graph_node_work_order_bridge` active。
  - 删除 `_resolve_graph_node_agent_profile()`、`_ensure_graph_node_execution_session()`、`_graph_node_*`、`_explicit_graph_node_*`、`_public_graph_node_work_order_payload()`、`_compact_graph_node_harness_event()`、`_graph_node_executor_*` 等迁出后旧 helper。
  - 删除不再使用的 `json` import。

验证：

```text
python -m compileall backend/harness/entrypoint/graph_node_work_order_bridge.py backend/harness/entrypoint/runtime_facade.py
python -m compileall backend/harness/entrypoint backend/task_system/work_environments backend/api/task_system.py
rg -n "_graph_node_|_explicit_graph_node|_public_graph_node|_compact_graph_node_harness_event|_graph_node_executor|_object_payload|_json_for_prompt|_first_event_value|_final_action_diagnostics_from_done_event" backend/harness/entrypoint/runtime_facade.py
git diff --check -- backend/harness/entrypoint/runtime_facade.py backend/harness/entrypoint/graph_node_work_order_bridge.py
```

真实 smoke：

```text
GraphNodeWorkOrderBridge missing profile blocked smoke:
  ok False
  status blocked
  error graph_node_agent_profile_not_registered
  authority harness.graph_node_work_order_bridge
  diagnostic_authority harness.graph_node_work_order_bridge.blocked_result
  retryable True
```

验证结果：

- `compileall` 通过。
- `runtime_facade.py` graph-node 旧 helper 扫描无残留。
- `git diff --check` 无空白错误；仅提示 `runtime_facade.py` 工作区行尾后续会归一为 LF。

结论：Phase 3 完成。`runtime_facade.py` 现在对 task episode 和 graph node work order 都是薄转发入口；下一阶段应进入 Phase 4，让 graph node 执行通过 `TaskCommand` 可审计调度，而不是由 GraphSystem work order 回调直接进入 harness。

### Stage F105：Graph node work order 接入 TaskCommand 调度

目标：

```text
执行 21_authority_audit_and_continuous_refactor_plan.md 的 Phase 4 第一刀。
GraphSystem 仍决定 ready work order 和 graph loop 推进，但单个 graph node 的执行必须先进入 TaskCommand / TaskScheduler。
TaskEnvironment lease、episode result、work product、checkpoint 归并不再由 GraphSystem.execute_work_order() 直接持有。
```

权威链检查：

- 符合：`GraphSystem.execute_work_order()` 现在提交并调度 `run_graph_node_work_order` command，不再直接 begin/release task lease。
- 符合：`TaskScheduler = graph node command dispatch authority`，负责确保 graph node task environment、获取 execution lease、调用 graph executor、记录 node result、释放 lease。
- 符合：`GraphNodeTaskBindingService = graph work order 到 TaskEnvironment/Episode/WorkProduct 的事实归并权威`，仍集中处理 prepare/begin/record/release。
- 符合：`GraphSystem` 保留图算法权威：只提供 `execute_work_order_executor()`、`accept_work_order_execution_result()` 和 `project_work_order_execution()`，不直接写 TaskSystem facts。
- 符合：重复 dispatch 已完成 command 时返回历史 result，支持跨 session/恢复读取，不把 terminal command 误判为缺结果。

修正点：

- `backend/task_system/work_environments/models.py`
  - `TaskCommandKind` 新增 `run_graph_node_work_order`。
- `backend/task_system/work_environments/scheduler.py`
  - `submit_command()` 对 `run_graph_node_work_order` 自动通过 `GraphNodeTaskBindingService.prepare_work_order()` 解析并创建节点 `TaskWorkEnvironment`，再写入命令账本。
  - 新增 `_execute_graph_node_work_order_command()`。
  - command handler 内部执行顺序为：`begin_work_order_execution -> graph_system.execute_work_order_executor -> record_work_order_result -> release_work_order_execution_lease -> graph_system.accept_work_order_execution_result -> graph_system.project_work_order_execution`。
  - dispatch record 结束时补充 `episode_id / graph_run_id / work_order_id / runtime_anchor_id` refs。
  - terminal command 二次 dispatch 返回历史 result。
  - 新增别名：`graph_node_run`、`run_graph_node`、`execute_graph_node`。
- `backend/graph_system/facade.py`
  - `execute_work_order()` 改为提交并调度 `run_graph_node_work_order` command。
  - 新增 `execute_work_order_executor()`，只调用 `GraphNodeWorkOrderExecutor`。
  - 新增 `accept_work_order_execution_result()`，只负责 graph result acceptance。
  - 新增 `project_work_order_execution()` 和 `project_work_order_command_failure()`，只做 graph execution projection。
  - 删除 `GraphSystem` 内部 `_begin_graph_node_task_execution()`、`_release_graph_node_task_execution()`、`_record_graph_node_task_result()` 直接 task fact 写入入口。

验证：

```text
python -m compileall backend/task_system/work_environments/models.py backend/task_system/work_environments/scheduler.py backend/graph_system/facade.py
python -m compileall backend/graph_system backend/task_system/work_environments backend/harness/entrypoint backend/api/task_system.py
rg -n "_begin_graph_node_task_execution|_release_graph_node_task_execution|_record_graph_node_task_result|begin_work_order_execution\\(|record_work_order_result\\(|release_work_order_execution_lease\\(" backend/graph_system backend/task_system backend/harness -g "*.py"
git diff --check -- backend/task_system/work_environments/models.py backend/task_system/work_environments/scheduler.py backend/graph_system/facade.py backend/runtime/context_management/design_docs/execution_plans/hierarchical_ast_project_graph/20_refactor_progress_log.md
```

真实 smoke：

```text
TaskScheduler run_graph_node_work_order fake GraphSystem smoke:
  created True
  dispatch_ok True
  command_status succeeded
  dispatch_status succeeded
  task_environment_id taskenv:graph-node-smoke
  dispatch_graph_run_id grun:smoke
  dispatch_work_order_id wo:smoke
  episode_id_present True
  result_authority task_system.task_scheduler.run_graph_node_work_order
  graph_exec_authority graph_system_work_order_execution

Repeated terminal dispatch smoke:
  first_ok True dispatched True graph_system_work_order_execution
  second_ok True dispatched False command_terminal graph_system_work_order_execution
  second_dispatch_status succeeded
```

扫描结果：

- `GraphSystem` 中无 `_begin_graph_node_task_execution`、`_release_graph_node_task_execution`、`_record_graph_node_task_result` 残留。
- `begin_work_order_execution()`、`record_work_order_result()`、`release_work_order_execution_lease()` 只剩 `GraphNodeTaskBindingService` 定义和 `TaskScheduler` graph node command handler 调用。

结论：Phase 4 第一刀完成。Graph node work order 已进入 TaskCommand 可审计调度链；下一阶段可以开始 RuntimeAnchor 迁移，但旧 `TaskRun` 仍是 graph root / monitor / event scope，需要先做命名和投影层迁移，不能硬删。

### Stage F106：RuntimeAnchor 迁移层第一刀

目标：

```text
执行 21_authority_audit_and_continuous_refactor_plan.md 的 Phase 5 第一刀。
不硬删旧 TaskRun，不改 event_log / retention scope。
先建立 RuntimeAnchor 模型和 RuntimeStateIndex 映射，让新运行身份有真实持久化落点。
```

权威链检查：

- 符合：`TaskRun` 仍是 legacy runtime anchor payload 和旧事件范围，不再扩张为 task truth。
- 符合：`RuntimeAnchor` 是新的运行身份投影，不承载任务事实，不替代 TaskWorkEnvironment。
- 符合：`RuntimeStateIndex` 持有 RuntimeAnchor 与 legacy task_run_id / graph_run_id / session_id 的映射，避免另起仓库造成双索引漂移。
- 符合：`GraphRuntime.start()` 同步创建 `anchor_kind=graph_run` 的 RuntimeAnchor，但仍写旧 TaskRun，保证旧 monitor / event log / retention 不断裂。
- 符合：Run Monitor 只展示 `runtime_anchor_id` / `runtime_anchor`，不改变 control/delete/trace 的旧 task_run_id 行为。

修正点：

- `backend/runtime/shared/models.py`
  - 新增 `RuntimeAnchor`、`RuntimeAnchorKind`、`RuntimeAnchorStatus`。
- `backend/runtime/memory/state_index.py`
  - 新增 `upsert_runtime_anchor()`。
  - 新增 `get_runtime_anchor()`、`get_runtime_anchor_by_legacy_task_run()`、`get_runtime_anchor_by_graph_run()`、`list_session_runtime_anchors()`。
  - 新增 `runtime_anchors` record bucket。
  - 新增 `session_runtime_anchors`、`task_environment_runtime_anchors` list indexes。
  - 新增 `runtime_anchor_by_legacy_task_run`、`runtime_anchor_by_graph_run` value indexes。
- `backend/graph_system/runtime.py`
  - `GraphRuntimeStart` 增加 `runtime_anchor`。
  - `GraphRuntime.start()` 创建并写入 graph run RuntimeAnchor。
  - `graph_run_created` event payload / refs 带出 `runtime_anchor_id` / `runtime_anchor_ref`。
- `backend/graph_system/facade.py`
  - `GraphSystemStart` 增加 `runtime_anchor`。
- `backend/api/graph_system.py`
  - start graph run 响应新增 `runtime_anchor_id` 和 `runtime_anchor`，旧 `task_run_id` / `task_run` 不变。
- `backend/harness/runtime/run_monitor/projector.py`
  - monitor item 新增 `runtime_anchor_id` 和 `runtime_anchor`。
  - 新增 `_runtime_anchor_for_task_run()`，优先从 `RuntimeStateIndex.get_runtime_anchor_by_legacy_task_run()` 读取。

验证：

```text
python -m compileall backend/runtime/shared/models.py backend/runtime/memory/state_index.py backend/graph_system/runtime.py backend/graph_system/facade.py backend/api/graph_system.py backend/harness/runtime/run_monitor/projector.py
rg -n "RuntimeAnchor|runtime_anchor|upsert_runtime_anchor|get_runtime_anchor" backend/runtime/shared/models.py backend/runtime/memory/state_index.py backend/graph_system/runtime.py backend/graph_system/facade.py backend/api/graph_system.py backend/harness/runtime/run_monitor/projector.py
git diff --check -- backend/runtime/shared/models.py backend/runtime/memory/state_index.py backend/graph_system/runtime.py backend/graph_system/facade.py backend/api/graph_system.py backend/harness/runtime/run_monitor/projector.py
```

真实 smoke：

```text
RuntimeStateIndex / GraphRuntime RuntimeAnchor smoke:
  direct_by_task rtanchor:direct
  direct_by_graph rtanchor:direct
  start_anchor_id rtanchor:grun_graph_smoke_1783258476988
  stored_by_graph rtanchor:grun_graph_smoke_1783258476988
  stored_by_task rtanchor:grun_graph_smoke_1783258476988
  task_run_still_exists True
```

结论：Phase 5 第一刀完成。系统已经具备新 runtime identity 的持久化映射；下一刀应继续迁移 monitor/resource/action 投影对 RuntimeAnchor 的使用，但不能在 event log 和 retention 未迁移前删除 task_run_id。

### Stage F107：ProjectNetwork generation 生命周期第一刀

目标：

```text
执行 21_authority_audit_and_continuous_refactor_plan.md 的 Phase 6 第一刀。
ProjectNetwork ingest 只写事实和 dirty signal，不再每个节点结果触发全量 materialize。
semantic artifact materialize / publish 改为显式 generation lifecycle，并通过 TaskCommand 可审计调度。
```

权威链检查：

- 符合：`ProjectNetworkSystem = 项目网络事实、generation、维护信号和报告资产权威`。
- 符合：`TaskScheduler = 项目网络生命周期命令调度权威`，只提交和执行命令，不拥有语义网络资产。
- 符合：`RuntimeEffect project_network_work_product_ingest` 只接收 node result 并回传 ingest/dirty 摘要，不发布根报告。
- 符合：candidate materialize 只写 `storage/tasks/project_network_artifacts/<build>/...`，不污染根目录人类报告。
- 符合：publish 在权限验证后才刷新 `PROJECT_NETWORK_REVIEW.md`、`PROJECT_ARCHITECTURE_OVERVIEW.md`、`PROJECT_SEMANTIC_COORDINATES.md`、`PROJECT_SIGNAL_CHAIN_REVIEW.md`、`PROJECT_UNIFIED_CONTROL_GRAPH.md` 和 `PROJECT_NETWORK_REPORTS/`。

修正点：

- `backend/project_network_system/semantic_artifact_materializer.py`
  - `materialize_build()` 新增 `publish_human_reports` 参数。
  - 默认 candidate 模式只写 artifact root 和 artifact reports，不清空、不写根目录 human reports。
  - publish 模式才重建 `PROJECT_NETWORK_REPORTS/files|directories|layers` 并刷新根目录报告。
  - 文件级、目录级、层级报告写入函数支持 artifact-only 输出。
- `backend/project_network_system/service.py`
  - `ProjectNetworkWorkProductIngestResult` 增加 `maintenance_signals`。
  - `accept_node_result()` 删除 per-node `ProjectNetworkSemanticArtifactMaterializer.materialize_build()` 调用。
  - ingest 成功后只 queue dirty signals：
    - `semantic_facts_changed`
    - `route_index_dirty`
    - `signal_chain_dirty`
    - `link_audit_required`
  - 新增 `ProjectNetworkGenerationMaterializationResult`。
  - 新增 `materialize_generation_candidate()`：显式生成 candidate semantic artifact set。
  - 新增 `publish_materialized_generation()`：权限前置验证后刷新 human reports 并 publish generation。
  - generation identity 使用 manifest 中的 graph / coordinate / route / signal / audit hashes，不再只按路径或数量判断同一代。
- `backend/project_network_tasks/runtime_effects.py`
  - runtime effect 返回 `materialization_lifecycle`、`maintenance_signal_ids`、`dirty_signal_codes`。
  - 不再返回 per-node materialized `semantic_artifact_set`。
- `backend/task_system/work_environments/scheduler.py`
  - 接入 `materialize_project_network_generation`。
  - 接入 `publish_project_network_generation`。
  - 接入 `repair_project_network_refs`。
  - 增加 project-network command 别名，仍要求命令落在 TaskEnvironment 审计锚点上。

验证：

```text
python -m compileall backend/project_network_system backend/project_network_tasks backend/task_system/work_environments
rg -n "materialize_build\\(|ProjectNetworkSemanticArtifactMaterializer\\(" backend/project_network_system backend/project_network_tasks backend/task_system/work_environments -g "*.py"
git diff --check -- backend/project_network_system/semantic_artifact_materializer.py backend/project_network_system/service.py backend/project_network_system/__init__.py backend/project_network_tasks/runtime_effects.py backend/task_system/work_environments/scheduler.py
```

真实 smoke：

```text
ProjectNetwork lifecycle service smoke:
  ingest_work_products 1
  dirty_signal_codes ['link_audit_required', 'route_index_dirty', 'semantic_facts_changed', 'signal_chain_dirty']
  root_after_ingest False
  root_after_candidate False
  root_after_publish True
  candidate_status candidate
  published_status published

TaskScheduler materialize -> publish smoke:
  ingest_dirty_signals ['link_audit_required', 'route_index_dirty', 'semantic_facts_changed', 'signal_chain_dirty']
  materialize_ok True
  materialize_status candidate
  artifact_hash_count 5
  root_after_materialize False
  publish_ok True
  publish_status published
  root_after_publish True

Publish guard smoke:
  blocked generation publish requires curator or publish-gate authority
  root_report_exists False
```

扫描结果：

- `materialize_build()` 只剩 `ProjectNetworkBuildService.materialize_generation_candidate()` 和 `ProjectNetworkBuildService.publish_materialized_generation()` 两个显式 lifecycle 入口调用。
- `project_network_tasks.runtime_effects` 不再 materialize 或携带 materialized artifact set。
- candidate generation payload 带 `artifact_hashes`，可区分语义内容变化。

结论：Phase 6 第一刀完成。ProjectNetwork ingest、candidate materialize、publish、repair queue 已经拆成可审计生命周期；下一刀可以继续把 maintenance signals / repair work items 与 TaskCommand repair graph 彻底闭环，并补前端任务工作台投影。

### Stage F108：ProjectNetwork repair command 闭环第一刀

目标：

```text
继续执行 Phase 6。
repair_project_network_refs 不再只是登记 repair item。
TaskScheduler 负责把 repair intent 进入 ProjectNetworkSystem repair queue，并按命令策略发布 ProjectNetwork repair graph。
```

权威链检查：

- 符合：`ProjectNetworkSystem` 仍负责 maintenance signal 和 repair work item 的事实写入。
- 符合：`ProjectNetworkRepairRuntimeService` 仍负责把 repair items 批处理成目录树 repair graph。
- 符合：`TaskScheduler` 只作为命令调度层，调用 ProjectNetworkSystem / ProjectNetworkTasks，不直接构造修复图。
- 符合：repair graph publish 失败时，command 失败并保留已排队 repair item 和错误投影，不把“已登记”伪装成“已修复”。

修正点：

- `backend/task_system/work_environments/scheduler.py`
  - `_execute_project_network_repair_command()` 先调用 `ProjectNetworkBuildService.queue_repair()` 写 maintenance signal / repair item。
  - 默认 `publish_repair_graph=True`，继续调用 `ProjectNetworkRepairRuntimeService.publish_repair_graph()`。
  - 支持显式 `publish_repair_graph=False`，用于只登记 repair item 的维护场景。
  - repair graph 发布失败时返回：
    - `ok=False`
    - `project_network_repair`
    - `repair_graph_publish_error`
    - `repair_graph_published=False`
  - command status 由 `_result_failed()` 统一判定为 failed。

验证：

```text
python -m compileall backend/project_network_system backend/project_network_tasks backend/task_system/work_environments
rg -n "materialize_build\\(|ProjectNetworkSemanticArtifactMaterializer\\(|repair_project_network_refs|publish_repair_graph" backend/project_network_system backend/project_network_tasks backend/task_system/work_environments -g "*.py"
git diff --check -- backend/project_network_system/semantic_artifact_materializer.py backend/project_network_system/service.py backend/project_network_system/__init__.py backend/project_network_tasks/runtime_effects.py backend/task_system/work_environments/scheduler.py backend/runtime/context_management/design_docs/execution_plans/hierarchical_ast_project_graph/20_refactor_progress_log.md
```

真实 smoke：

```text
TaskScheduler repair queue-only smoke:
  queue_only_ok True
  queue_only_repair_count 1
  queue_only_published False

TaskScheduler repair default publish smoke without physical skeleton:
  publish_ok False
  publish_repair_count 1
  publish_error_type KeyError
```

结论：Phase 6 repair command 第一刀完成。repair intent 现在能进入 TaskCommand 审计链，并能尝试发布 repair graph；失败时不会丢 repair item。下一步可以继续做 ProjectNetwork maintenance 自动选择 dirty signals -> repair commands，或者进入 Phase 7 前端任务工作台，把 command/generation/repair queue 暴露为可操作视图。

### Stage F109：前端 Task Workbench 任务事实投影

目标：

```text
执行 21_authority_audit_and_continuous_refactor_plan.md 的 Phase 7。
在任务系统的运行管理域中新增“任务事实”页面，让 TaskEnvironment、TaskCommand、dispatch、work product、checkpoint 和 event 成为可见、可操作的运行事实。
该阶段不推进深度网络搜索算法，只把已有任务事实层投影到产品界面。
```

权威链检查：

- 符合：`TaskSystemView` 只增加运行管理子页，不把任务事实混入环境配置页。
- 符合：前端只调用 `TaskEnvironmentViewService` 已暴露的 list/detail/commands API，不重新解释任务状态，不在前端承载调度权威。
- 符合：命令入口只提交 `TaskCommand`，后续执行仍由 `TaskScheduler` 决定。
- 符合：页面显示 task environment 列表、任务概览、命令账本、work product、checkpoint、plan/todo 和 events，作为 TaskSystem facts 的观察面。

修正点：

- `frontend/src/lib/api/types.ts`
  - 增加 TaskWorkEnvironment list/detail、TaskCommandRecord、TaskDispatchRecord 和 command submit/list response 类型。
- `frontend/src/lib/api/taskSystem.ts`
  - 增加 `listTaskWorkEnvironments()`、`getTaskWorkEnvironmentDetail()`、`listTaskWorkEnvironmentCommands()`、`submitTaskWorkEnvironmentCommand()`。
- `frontend/src/components/workspace/views/task-system/runs/TaskRuntimeWorkbench.tsx`
  - 新增任务事实工作台。
  - 左侧显示 task environment 列表。
  - 右侧显示任务概览、命令提交、命令账本、运行产物、checkpoint、计划待办和事件流。
- `frontend/src/components/workspace/views/task-system/runs/RunManagementWorkbench.tsx`
  - `RunManagementSubpage` 增加 `tasks`。
  - `tasks` 子页转发到 `TaskRuntimeWorkbench`。
- `frontend/src/components/workspace/views/TaskSystemView.tsx`
  - 运行管理导航增加“任务事实”。
- `frontend/src/styles/05-system-pages.css`
  - 增加低噪声任务事实工作台样式，保持列表、表格和面板为可扫描控制台形态。

验证：

```text
python -m compileall backend/task_system/work_environments backend/api/task_system.py
npx tsc --noEmit
npm run lint
scripts/project_stack.ps1 -Action check -FrontendMode dev
Invoke-RestMethod http://127.0.0.1:8003/api/task-environments?limit=5
Edge/Playwright: open http://127.0.0.1:3000/?view=task-system -> 运行管理 -> 任务事实
git diff --check -- frontend/src/components/workspace/views/task-system/runs/TaskRuntimeWorkbench.tsx frontend/src/components/workspace/views/task-system/runs/RunManagementWorkbench.tsx frontend/src/components/workspace/views/TaskSystemView.tsx frontend/src/styles/05-system-pages.css frontend/src/lib/api/taskSystem.ts frontend/src/lib/api/types.ts
```

验证结果：

- 后端 compileall 通过。
- `npx tsc --noEmit` 通过。
- `npm run lint` 通过；仅保留既有项目 warning：
  - `agent-network/page.tsx` hook dependency。
  - `app/layout.tsx` font warning。
  - `SessionProjectionPanel.tsx` hook dependency。
  - `SystemConfigView.tsx` img warning。
  - `WritingChapterDesk.tsx` aria-selected warning。
- `project_stack.ps1 -Action check -FrontendMode dev` 确认：
  - frontend `127.0.0.1:3000` project-owned，health ok。
  - backend `127.0.0.1:8003` project-owned，health ok。
  - capability catalog ok。
- `/api/task-environments?limit=5` 返回真实 task environment facts。
- Edge/Playwright 页面 smoke 通过：
  - “任务事实”子页可打开。
  - task environment 列表可见。
  - detail 请求 `GET /api/task-environments/{environment_id}` 返回 200。
  - “命令账本”和“运行产物”可见。
  - 截图产物：`output/playwright/task-system-after-35s.png`。
- `git diff --check` 无空白错误；仅提示 `05-system-pages.css` 后续 Git touch 会把 CRLF 归一为 LF。

结论：Phase 7 第一刀完成。任务事实层已经具备前端观察和命令提交入口；下一阶段应继续 Phase 8 的旧结构收口，但在删除前必须再次扫描 `TaskRunLedger / run_models / control_signal_bridge / recovery bridge / runtime_facade helper` 的可达引用，避免误删仍被 runtime anchor 迁移依赖的边界。

### Stage F110：旧 TaskRunLedger 与直接控制桥清理

目标：

```text
执行 Phase 8 的第一刀旧结构删除。
删除已经无外部运行引用的旧 TaskRunLedger 壳。
删除绕开 TaskCommand 语义的 control/recovery bridge 命名与重复 POST 入口。
保留 control signal 作为事实查询，不保留 recovery/action 的第二推进入口。
```

权威链检查：

- 符合：`TaskRunLedger / TaskStepRun / TaskResult` 已无外部运行引用，不再作为 frozen compatibility 壳保留。
- 符合：任务推进动作统一进入 `POST /api/task-environments/{environment_id}/commands`。
- 符合：`GET /api/task-environments/{environment_id}/control-signals` 只作为信号事实查询保留。
- 符合：scheduler 仍是 command 执行权威；graph pause/resume/requeue/dispatch 被收束到 task command handler，不再暴露为旧 bridge 模块。
- 符合：前端任务事实页只调用 `/commands` 和 detail/list 投影，不依赖旧 control/recovery POST。

修正点：

- 删除 `backend/task_system/tasks/run_models.py`。
- 删除 `backend/task_system/work_environments/control_signal_bridge.py`。
- 删除 `backend/task_system/work_environments/recovery_command_bridge.py`。
- 新增 `backend/task_system/work_environments/graph_control_command_handlers.py`：
  - `apply_task_environment_graph_control_command()` 处理 pause/resume/stop 类 graph 控制。
  - `apply_task_environment_graph_recovery_command()` 处理 `resume_graph_run`、`requeue_graph_node`、`dispatch_ready_graph_nodes`。
  - 保留恢复动作规范化和 graph loop 结果压缩，但 authority 改为 task command handler 语义。
- `backend/task_system/work_environments/scheduler.py`
  - 改为引用 graph control command handlers。
  - command result 字段从旧 `bridge` 改为 `graph_control` / `graph_recovery`。
  - 失败判断改读新的 command result 字段。
  - `bridge_graph_control` 旧字段名改为 `graph_control_enabled`。
- `backend/task_system/work_environments/view_service.py`
  - `recommended_api` 改为推荐 `/commands` 和具体 command_kind。
- `backend/api/task_system.py`
  - 删除 `TaskEnvironmentControlSignalRequest`、`TaskEnvironmentRecoveryActionRequest`。
  - 删除 `POST /task-environments/{environment_id}/control-signals`。
  - 删除 `POST /task-environments/{environment_id}/recovery-actions`。
  - 保留 `GET /task-environments/{environment_id}/control-signals`。

验证：

```text
rg -n "TaskRunLedger|TaskStepRun|project_task_result_from_ledger|task_system\\.tasks\\.run_models" backend -g "*.py"
rg -n "bridge_graph_control|control_signal_bridge|recovery_command_bridge|task_environment_control_signal_bridge|task_environment_recovery_command_bridge|TaskEnvironmentControlSignalRequest|TaskEnvironmentRecoveryActionRequest|recovery-actions|request_task_work_environment_recovery_action|request_task_work_environment_control_signal" backend/api/task_system.py backend/task_system/work_environments -g "*.py"
python -m compileall backend/task_system/work_environments backend/api/task_system.py
git diff --check -- backend/api/task_system.py backend/task_system/work_environments/scheduler.py backend/task_system/work_environments/graph_control_command_handlers.py backend/task_system/work_environments/view_service.py backend/task_system/tasks/run_models.py backend/task_system/work_environments/control_signal_bridge.py backend/task_system/work_environments/recovery_command_bridge.py
scripts/project_stack.ps1 -Action stop -FrontendMode dev
scripts/project_stack.ps1 -Action start -FrontendMode dev
scripts/project_stack.ps1 -Action check -FrontendMode dev
```

真实 smoke：

```text
Fixed stack:
  frontend 127.0.0.1:3000 project-owned health ok
  backend 127.0.0.1:8003 project-owned health ok
  capability catalog ok

Old endpoint removal:
  POST /api/task-environments/{environment_id}/recovery-actions -> 404
  POST /api/task-environments/{environment_id}/control-signals -> 405

Remaining fact/API paths:
  GET /api/task-environments/{environment_id}/commands -> 200
  GET /api/task-environments/{environment_id}/control-signals -> 200
  GET /api/task-environments/{environment_id} -> 200

Edge/Playwright:
  /?view=task-system -> 运行管理 -> 任务事实
  命令账本 visible
  detail API 200
  screenshot: output/playwright/task-runtime-workbench-after-phase8.png
```

结论：Phase 8 第一刀完成。旧 TaskRunLedger 壳和旧 control/recovery bridge 命名已经清理；任务推进入口收束到 TaskCommand。剩余不能硬删的旧结构集中在 `TaskRun/task_run_id` 作为 RuntimeAnchor 迁移期的 event/log/monitor/retention legacy alias，下一阶段应继续 RuntimeAnchor 迁移，而不是删除 `TaskRun` 主存储。

### Stage F120：RuntimeAnchor 监控接线与写作图启动 smoke

目标：

```text
验证图任务系统在重构后仍能启动成熟写作图任务实例。
修复写作图配置从旧 publisher 迁移到 ExecutableGraphConfig 后暴露的节点身份断线。
让启动 API 默认返回控制面摘要，避免大图把输入包和事件 payload 直接灌回调用方。
```

权威链检查：

- 符合：`GraphNodeWorkOrder` 继续强制要求显式 `agent_profile_id`，执行层不根据 `agent_id` 猜 profile。
- 符合：写作图脚本负责生成完整节点身份；节点 payload、发布配置、编译 node contract 三处都带同一条 profile 线。
- 符合：写作图脚本每次重建托管图时清理新旧配置仓库中的托管旧发布物，不再保留迁移期旧 `graph_harness_configs` 残留。
- 符合：RuntimeAnchor 作为外部监控入口；内部仍以 legacy `task_run_id` 承载事件 scope，作为明确迁移期 alias。
- 符合：Graph start API 默认返回摘要投影，不再把 raw work order input package、raw checkpoint state、raw events 作为启动响应主面。

修正点：

- `scripts/configure_writing_modular_novel_graph.py`
  - 旧 import `task_system.compiler.graph_harness_config_publisher` 改为 `executable_graph_config_publisher.publish_graph_config_for_graph`。
  - 增加 `_agent_profile_id_for_agent()`，写作图托管 agent profile 由脚本统一确定。
  - `_node_payload()` 顶层写入 `agent_profile_id`。
  - `_node_contract_bindings()` 写入 `execution.agent_profile_id` 和 `agent.agent_profile_id`。
  - 清理逻辑改为同时清理 `graph_configs.json` 与旧 `graph_harness_configs.json` 中托管写作图配置，删除旧 active-config 保护残留。
- `backend/task_system/compiler/executable_graph_config_publisher.py`
  - `_node_config()` 发布节点时保留顶层 `agent_profile_id`。
  - `_published_node_metadata()` 将显式 profile 写回 metadata，保证编译 contract 与 config 一致。
- `backend/api/graph_system.py`
  - start 响应中的 `node_work_orders` 改用 work order summary。
  - start 响应中的 `events`、`checkpoint`、`graph_loop_state` 改为 API 摘要投影。
  - `dispatch-ready`、`requeue-nodes`、`node-results` 同步改为摘要投影，避免图控制面半轻半重。
  - 保留 `runtime_anchor_id` / `runtime_anchor`，便于外部控制面按 anchor 追踪。

验证：

```text
python scripts\configure_writing_modular_novel_graph.py
python -m compileall backend\api\graph_system.py scripts\configure_writing_modular_novel_graph.py backend\task_system\compiler\executable_graph_config_publisher.py
scripts/project_stack.ps1 -Action stop -FrontendMode dev
scripts/project_stack.ps1 -Action start -FrontendMode dev
POST /api/graph-system/task-graphs/graph.writing.modular_novel.master/start
POST /api/graph-system/graph-runs/{graph_run_id}/stop
GET /api/harness/run-monitor/runtime-anchors/{runtime_anchor_id}
GET /api/runtime/logs/runtime-anchors/{runtime_anchor_id}/events?limit=3&include_payloads=false
scripts/project_stack.ps1 -Action check -FrontendMode dev
```

真实结果：

- 写作图配置脚本成功：
  - `graph.writing.modular_novel.master`
  - `graph.writing.modular_novel.design_init`
  - `graph.writing.modular_novel.chapter_cycle`
  - `graph.writing.modular_novel.finalize`
- `storage/tasks/graph_configs.json` 中写作图配置收敛为 4 个当前发布 config。
- 60 个可执行 agent 节点全部有非空 `agent_profile_id`，编译 `node_contract_index.agent.agent_profile_id` 也全部非空。
- 真实启动 `graph.writing.modular_novel.master` 成功：
  - `runtime_anchor_id`: `rtanchor:grun_graph_writing_modular_novel_master_1783266230270`
  - 首个派发节点：`graph_module.design_init::project_brief`
  - `agent_id`: `agent:writing_modular_creator`
  - `agent_profile_id`: `writing_modular_creator_runtime`
  - `input_package_ref` 存在，启动响应中不再包含 raw `input_package`。
- compact start 响应约 `47267` bytes；此前 raw 响应会输出超大 JSON。
- smoke run 已停止：
  - `stop_status`: `stopped`
  - `terminal_reason`: `user_stopped`
- RuntimeAnchor 监控入口可读：
  - stopped smoke anchor 返回 `status=aborted`、`signal_count=1`、`has_runtime_anchor=true`。
- RuntimeAnchor SSE 短读可读：
  - 返回 `runtime_log_snapshot`。
  - `include_payloads=false` 时事件 payload 被收缩。
- 固定端口检查通过：
  - frontend `127.0.0.1:3000` project-owned，health ok。
  - backend `127.0.0.1:8003` project-owned，health ok。
  - capability catalog ok。
- 后端日志无新 traceback；仅有既有 `jieba/pkg_resources` warning。

结论：写作图任务脚本和图任务启动主链已恢复可运行。此次修复不是执行层兜底，而是把节点身份线接回配置生成和发布源头；同时把 graph control API 从“返回执行内脏”收缩为“返回控制面摘要”。下一阶段继续 RuntimeAnchor 迁移和旧 TaskRun alias 收口，重点检查 `TaskRecordLifecycleManager`、runtime log、run monitor、graph root 仍直接暴露 task_run_id 的位置。

### Stage F121：GraphNode 物理身份、时空引用与 Human Gate 附件化

目标：

```text
把图任务节点从“默认等于 agent / gate / prompt”收缩为图空间物理单位。
为 work order / result 补上 node_kind、execution_adapter、graph_time、node_attempt。
修正 human gate 语义：它不是节点，也不是 work order，而是节点或边上的审核附件。
```

权威链检查：

- 符合：`GraphNode` 只表达图空间物理点，`NodeExecutionAdapter` 表达执行方式，二者分离。
- 符合：`human_gate/manual_gate` 不能发布成 `GraphNode`，也不能编译成 `GraphNodeWorkOrder`。
- 符合：`waiting_human_gate` 只保留为状态 / outcome；人工审核入口收敛到 `NodeGateAttachment(gate_kind="human_gate")` 或 `edge.protocol_kind = human_gate`。
- 符合：执行器不再接收 `work_kind = human_gate` 并自行制造等待态；等待态必须来自 gate attachment / edge decision 控制链。
- 符合：`node_dispatch_seq` 与 `attempt_index` 分离；调度次数不是重试次数。

修正点：

- `backend/graph_system/node_adapter_models.py`
  - 新增 `GraphNodePhysicalSpec`、`NodeExecutionAdapter`、`NodeActivationPlan`、`NodeGateAttachment`。
  - 移除 `human_gate_node` / `human_gate` adapter 概念。
  - 对 `node_type = human_gate / manual_gate`、`executor_type = human / human_gate / manual_gate` 直接失败，提示改为 gate attachment / edge control。
  - `work_kind_for_adapter()` 改由 adapter 决定 work kind，且不再返回 `human_gate`。
- `backend/graph_system/spacetime_models.py`
  - 新增 `GraphTimeRef`、`NodeAttemptRef`、`HarnessTurnTime`、`ExecutionTraceBinding`。
  - `NodeAttemptRef.attempt_index` 默认从 1 开始，不再等同于 `node_dispatch_seq`。
- `backend/graph_system/models.py`
  - `GraphNodeExecutionSlot`、`GraphNodeWorkOrder`、`NodeResultEnvelope` 增加节点物理身份和图时间字段。
  - `GraphNodeWorkOrder.work_kind` 移除 `human_gate`。
  - `ExecutableGraphConfig` 结构 hash 纳入 physical / execution_adapter 投影。
- `backend/graph_system/context_materializer.py`
  - 构建 work order 时注入 node physical、adapter、graph time、node attempt。
- `backend/graph_system/work_order_executor.py`
  - 删除 `human_gate` work order 分支。
  - agent result / command failure result 继承 work order 的节点身份和时空引用。
- `backend/task_system/compiler/executable_graph_config_publisher.py`
  - 发布配置时生成 node physical / execution_adapter。
  - 拒绝把 human/manual gate 发布成 executable graph node。
- `backend/task_system/compiler/node_contract_models.py`
  - 拒绝把 human/manual gate 编译成 node contract，防止契约层继续暗示“人工门是节点”。
- `backend/runtime/context_management/design_docs/execution_plans/hierarchical_ast_project_graph/23_graph_task_programmed_agent_spacetime_architecture.md`
  - 记录实现不变量：human gate 是审核装饰器 / 控制附件，不进入节点执行队列。

验证：

```text
python -m compileall backend/graph_system/node_adapter_models.py backend/graph_system/spacetime_models.py backend/graph_system/models.py backend/graph_system/context_materializer.py backend/task_system/compiler/executable_graph_config_publisher.py backend/task_system/compiler/node_contract_models.py backend/graph_system/runtime_objects.py backend/graph_system/work_order_executor.py backend/graph_system/facade.py backend/graph_system/__init__.py
python scripts\configure_writing_modular_novel_graph.py
rg -n 'human_gate_node|adapter_kind.*human_gate|work_kind.*human_gate|human_gate_requires_external_decision' backend/graph_system backend/task_system/compiler
```

真实结果：

- 编译通过。
- 写作图配置发布成功：
  - `graph.writing.modular_novel.master`
  - `graph.writing.modular_novel.design_init`
  - `graph.writing.modular_novel.chapter_cycle`
  - `graph.writing.modular_novel.finalize`
- `human_gate` 节点边界验证通过：`node_physical_spec_from_node({"node_type": "human_gate"})` 抛出 `ValueError`。
- `human_gate` work order 边界验证通过：`GraphNodeWorkOrder(work_kind="human_gate")` 抛出 `ValueError`。
- `human_gate/manual_gate` node contract 分类已改为拒绝，写作图配置脚本二次运行成功，未误伤当前写作图。
- 普通 agent 节点挂 `human_gate_policy` 可生成 `NodeGateAttachment(gate_kind="human_gate")`。
- `rg` 未发现 `human_gate_node`、`adapter_kind=human_gate`、`work_kind=human_gate` 执行残留。

结论：human gate 已从图任务物理节点和执行队列中拔出，回到节点/边审核附件位置。下一阶段应继续收紧旧图编辑器和 composable graph 里的 `human_gate` unit 命名，避免前端/配置层继续暗示“人工门是节点”。

### Stage F122：GraphRun 启动实例化与任务系统归属

目标：

```text
每次启动图任务必须落到一个具体 GraphTaskInstance。
GraphRun 不允许作为裸运行存在于管理面。
任务系统负责实例、root session、文件空间、run 记录和控制状态同步。
GraphSystem 只负责图算法运行，不拥有项目实例归属。
```

权威链检查：

- 符合：通用 `/graph-system/task-graphs/{graph_id}/start` 启动前先调用任务系统实例启动服务。
- 符合：未指定实例时创建新的 `GraphTaskInstance`；指定已有实例时校验 graph_id 后复用。
- 符合：GraphRun 的 `project_id` 固定为 `graph_task_instance_id`，普通业务项目 ID 只作为 `source_project_id` 记录。
- 符合：`pause/resume/stop` 控制不再依赖当前发布的 `graph_config_id`，只按 GraphRun 的 session/scope 绑定校验。
- 符合：控制结果同步回 GraphTaskInstance 状态，任务系统成为运行管理账本。

修正点：

- `backend/task_system/graph_instances/launch_service.py`
  - 新增 `GraphTaskInstanceLaunchService`，统一创建/复用实例、root session、文件空间、启动输入绑定和 run/status 记录。
- `backend/api/graph_system.py`
  - 启动入口强制走实例绑定服务。
  - 返回 `graph_task_instance_id`、`graph_task_instance`、`graph_task_instance_created`。
  - 删除旧的 project-or-instance 混合 scope 校验 helper。
  - `pause/resume/stop` 控制接口不再查当前 `ExecutableGraphConfig`。
- `backend/api/graph_task_instances.py`
  - 实例启动入口复用通用启动链，不再重复 `record_run`。
  - 写作图实例启动输入改为 `user_creative_seed`，去掉 `project_brief` 启动字段残留。
- `frontend/src/lib/api/graph.ts`、`frontend/src/lib/api/types.ts`
  - 控制请求的 `graph_config_id` 改为可选。
  - 启动/控制响应类型暴露 GraphTaskInstance 信息。
- `scripts/start_writing_project_run.ps1`
  - 启动结果输出 `graph_task_instance_id` 和 `graph_task_instance_created`。

验证：

```text
python -m compileall backend/api/graph_system.py backend/api/graph_task_instances.py backend/task_system/graph_instances/launch_service.py backend/task_system/graph_instances/__init__.py
python -c "import api.graph_system, api.graph_task_instances; from task_system.graph_instances import GraphTaskInstanceLaunchService; print(GraphTaskInstanceLaunchService.authority)"
fixed backend restart: 127.0.0.1:8003
powershell -ExecutionPolicy Bypass -File scripts/start_writing_project_run.ps1 -RawCreativeText <plain creative paragraph> -UnitsPerBatch 1
POST /api/graph-system/graph-runs/{graph_run_id}/stop with body {"reason":"..."} and no graph_config_id
GET /api/graph-system/graph-task-instances/{graph_task_instance_id}
```

真实结果：

- Python 编译通过。
- 后端固定端口 `127.0.0.1:8003` 用新代码启动成功。
- 写作图 smoke 启动返回：
  - `graph_task_instance_created=true`
  - `graph_task_instance_id=gti.graph.writing.modular_novel.master.eaefc9ab05df`
  - `node_work_order_count=1`
  - `first_node_id=graph_module.design_init::project_brief`
- 无 `graph_config_id` 的 stop 成功：
  - `stop_accepted=true`
  - `stop_reason=stopped`
  - 实例 `status=stopped`
  - 实例 `graph_run_ids` 包含本次 `graph_run_id`
  - 实例文件空间存在。
- 后端日志无新 traceback；仅有既有 `jieba/pkg_resources` warning。

结论：图任务启动已从裸 GraphRun 收口为“GraphTaskInstance 管理的具体项目运行”。GraphSystem 保持算法运行权威，任务系统拥有实例和运行管理账本。下一阶段可以继续清理前端/CLI 中仍以裸 GraphRun 作为主入口的管理视图，让 UI 默认从实例维度进入监控、产物和人审控制。

### Stage F123：GraphRun 节点级 checkpoint 恢复

目标：

```text
图任务不能用“重新启动一条新 run”替代恢复。
只要 checkpoint、节点结果、事件和产物没有删除，GraphRun 就必须能选择历史坐标，把活动视图恢复到任意可执行节点边界。
恢复时不覆盖旧历史，而是在最新事件时间上开启 recovery epoch。
```

权威链检查：

- 符合：GraphLoop 仍是唯一状态推进权威，恢复动作进入 `requeue_nodes_and_checkpoint()`，不由任务系统或前端拼状态。
- 符合：LangGraph checkpointer 只作为持久化 checkpoint contract 使用，不接管图运行器。
- 符合：TaskSystem 只传递 `checkpoint_id`、`start_node_ids`、`reset_downstream` 等控制意图，不直接修改 GraphLoopState。
- 符合：恢复基底来自历史 checkpoint，事件游标使用最新 cursor 继续递增，避免覆盖旧 checkpoint。
- 符合：requeue 后重新投影 `completed_node_ids`、`failed_node_ids`、`blocked_node_ids`，避免 node state 与快捷索引不一致。
- 符合：恢复动作会清理旧 `runtime_control=stopped`，避免 monitor 把已恢复运行继续压成 stopped。

修正点：

- `backend/graph_system/checkpoint_store.py`
  - checkpoint protocol 增加 `get_checkpoint(graph_run_id, checkpoint_id)`。
- `backend/graph_system/langgraph_checkpoint_store.py`
  - 支持按 checkpoint_id 精确读取历史 checkpoint。
- `backend/graph_system/loop.py`
  - `requeue_nodes_and_checkpoint()` 支持 `checkpoint_id`。
  - 新增 recovery epoch 语义：历史 checkpoint 作为内容基底，最新 event cursor 作为新写入时间。
  - 清理恢复基底中的 stale active work order。
  - requeue 后重算状态索引。
  - formal TaskRun / GraphRun 同步时清理旧停止控制态。
- `backend/api/graph_system.py`
  - `POST /graph-system/graph-runs/{graph_run_id}/requeue-nodes` 支持 `checkpoint_id`。
  - 新增 `GET /graph-system/graph-runs/{graph_run_id}/checkpoints`。
- `backend/task_system/work_environments/graph_control_command_handlers.py`
  - 任务环境 recovery command 可透传 `checkpoint_id`。
- `backend/task_system/work_environments/scheduler.py`
  - recovery command payload 持久化并传递 `checkpoint_id`。
- `frontend/src/lib/api/graph.ts`、`frontend/src/lib/api/types.ts`
  - 增加 checkpoint 查询和 requeue API 类型。

真实验证：

```text
python -m compileall backend/graph_system/checkpoint_store.py backend/graph_system/langgraph_checkpoint_store.py backend/graph_system/loop.py backend/api/graph_system.py backend/task_system/work_environments/graph_control_command_handlers.py backend/task_system/work_environments/scheduler.py
git diff --check -- backend/graph_system/checkpoint_store.py backend/graph_system/langgraph_checkpoint_store.py backend/graph_system/loop.py backend/api/graph_system.py backend/task_system/work_environments/graph_control_command_handlers.py backend/task_system/work_environments/scheduler.py frontend/src/lib/api/graph.ts frontend/src/lib/api/types.ts
fixed backend restart: 127.0.0.1:8003
GET /api/graph-system/graph-runs/grun:graph_writing_modular_novel_master:1783288133550/checkpoints?limit=80
POST /api/graph-system/graph-runs/grun:graph_writing_modular_novel_master:1783288133550/requeue-nodes
GET /api/graph-system/graph-runs/grun:graph_writing_modular_novel_master:1783288133550/monitor
```

实测结果：

- 历史 checkpoint 29 存在，状态为 `running`，`chapter_index=5`，`chapter_draft=ready`。
- 历史 checkpoint 49 仍存在，状态为 `blocked`，`chapter_draft=blocked`，未被覆盖。
- 恢复后写入 checkpoint 51：
  - `status=running`
  - `ready_node_ids=["graph_module.chapter_cycle::chapter_draft"]`
  - `chapter_index=5`
  - `chapter_index_padded="005"`
  - `recovery_epoch=2`
  - `recovery_base_event_cursor=29`
- monitor 已同步承认恢复态：
  - `graph_status=running`
  - `task_status=running`
  - `latest_step=graph_nodes_requeued`
  - `loop_status=running`
  - `draft_status=ready`

结论：GraphRun 已具备“从历史 checkpoint 回到节点”的基础能力。下一阶段应把前端 checkpoint 时间线、节点 attempt 列表和恢复按钮做成明确控制面，并继续把写作图的章节 cursor / artifact path 作为节点输入契约审计，防止 agent 内容和系统坐标再次错位。
