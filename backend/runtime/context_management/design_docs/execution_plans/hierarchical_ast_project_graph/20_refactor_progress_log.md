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
