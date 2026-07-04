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
- 新增 `backend/task_system/work_products`，包含通用 `WorkProduct`、`WorkProductRef`、`TaskReducerInput`。
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
