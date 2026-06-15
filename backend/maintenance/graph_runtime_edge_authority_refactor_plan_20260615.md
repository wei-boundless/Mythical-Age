# 图任务运行时边状态权威统一实施方案

创建日期：2026-06-15  
统一修订日期：2026-06-16  
状态：统一方案待确认，未实施代码  
范围：图任务运行时推进、边状态、节点就绪、人审分支、恢复、后台重排、相关结构性测试

## 1. 最终结论

本次优化只采用一个方案：

```text
GraphRuntime 锁定配置
-> GraphLoop 作为唯一编排入口
-> GraphTransitionProcessor 作为唯一边状态转移权威
-> GraphReadinessEvaluator 作为唯一节点就绪判断权威
-> GraphContextMaterializer 只负责组装 work order
-> GraphNodeWorkOrderExecutor 只负责执行节点
-> CheckpointStore 记录规范状态
-> Resume/Background 只恢复或重排规范状态
```

必须落地的结构：

- 新增 `backend/harness/graph/transition_processor.py`。
- 新增 `backend/harness/graph/readiness_evaluator.py`。
- 新增 `backend/task_system/compiler/writing_graph_config_migrator.py`，旧写作图配置必须在发布/编译阶段直接迁移到新结构。
- 在 `backend/harness/graph/models.py` 中明确 transition、edge state、readiness decision 的数据结构。
- 改造 `backend/harness/graph/state_machine.py`，让 `ready_nodes` 不再用上游节点 completed 推断，而是读取规范 `edge_states`。
- 改造 `backend/harness/graph/loop.py`，让节点结果、人审 gate、人审边、失败重置都通过 `GraphTransitionProcessor`。
- 改造 `backend/harness/graph/resume.py` 和 `backend/harness/graph/background_supervisor.py`，禁止恢复和后台监督重新决定图路线。
- 删除旧的散落推进 helper 和保护旧结构的测试。

不采用的路线：

- 不只修 `state_machine.ready_nodes`，因为那会留下人审、恢复、失败路径的第二套推进权威。
- 不照搬 Dify/graphon 的整套 `GraphEngine`，因为本项目已有 `GraphHarnessConfig`、契约索引、work order、artifact/memory receipt、人审证据链。
- 不保留旧 upstream-completed ready 逻辑作为生产兜底。
- 不让旧写作图在运行时走旧兼容分支。旧配置必须先迁移成新 canonical transition/readiness 配置，再进入运行时。

一句话标准：

> 图能不能往下走，只能由 canonical edge state 和 readiness policy 决定；任何模块不得绕过边状态直接激活下游节点。

旧写作图迁移标准：

> 旧写作图的 graph id、node id、edge id、合同、章节循环和人审入口保持稳定；迁移发生在发布/编译层；运行时只接收迁移后的新结构。

## 2. 当前必须修正的问题

### P0：旧写作图配置必须直接迁移

现状：

- 模块化长篇写作图已经存在 master/design/chapter/finalize 四类配置。
- 旧配置包含 graph module、章节循环、审核返修、记忆提交、章节动作 API、章节进度 receipt 等专用语义。

问题：

- 如果新运行时只接受全新字段，旧写作图需要人工重建，会破坏现有写作任务资产。
- 如果为了旧写作图在 runtime 保留旧分支，会破坏本方案的单一推进权威。

修正：

- 旧写作图配置必须在 compiler/publisher 层直接迁移成新 canonical transition/readiness metadata。
- 迁移后 graph id、node id、edge id 保持稳定。
- runtime 不出现 `graph.writing.modular_novel.*` 路线特判。

### P1：节点就绪权威错误

现状：

- `backend/harness/graph/state_machine.py:64` 的 `ready_nodes` 是当前就绪判断入口。
- `backend/harness/graph/state_machine.py:90` 到 `backend/harness/graph/state_machine.py:92` 用所有上游节点 completed 推断 ready。
- 这条路径没有真正消费 `edge_states`。

问题：

- 条件分支中，未选中分支的上游节点 completed 仍可能影响下游判断。
- 人审、修订、重路由、失败边无法统一表达。
- `wait_policy`、`join_policy` 已在图定义里存在，但运行时没有真实执行它们。

修正：

- `ready_nodes` 必须改为调用 `GraphReadinessEvaluator.evaluate(...)`。
- `GraphReadinessEvaluator` 只读 `node_states`、`edge_states`、topology、`wait_policy`、`join_policy`。
- `all(upstream completed)` 逻辑从生产路径删除。

### P1：人审 gate 绕过配置一致性检查

现状：

- `backend/harness/graph/loop.py:250` 的 `accept_node_result` 会调用 `assert_graph_config_compatible_with_state`。
- `backend/harness/graph/loop.py:697` 的 `apply_human_gate_decision_and_checkpoint` 没有同等检查。

问题：

- 人审路径可能在 graph config 与 checkpoint state 不匹配时继续推进。

修正：

- `apply_human_gate_decision_and_checkpoint` 入口必须先调用 `assert_graph_config_compatible_with_state`。
- human gate decision 必须转成 `GraphTransitionInput(trigger_type="human_gate_decision")`。

### P1：人审修订和重路由直接激活目标节点

现状：

- `backend/harness/graph/loop.py:750` 到 `backend/harness/graph/loop.py:764` 中，`request_revision` 和 `reroute_to_node` 可直接影响目标节点 ready。

问题：

- 人审动作成为图推进捷径。
- 边契约、选择证据、未选中边 skipped、恢复审计都不完整。

修正：

- `request_revision` 和 `reroute_to_node` 必须只产生 edge transition。
- 目标节点是否 ready 只能由 `GraphReadinessEvaluator` 判断。
- 如果图中没有声明可用修订边或重路由边，则输出 `blocked` transition，原因是 `route_edge_not_declared`，不得临时补造路线。

### P2：wait/join 策略只有定义，没有运行时权威

现状：

- `backend/task_system/graphs/task_graph_models.py:14` 到 `backend/task_system/graphs/task_graph_models.py:29` 定义了 `NODE_WAIT_POLICIES`、`NODE_JOIN_POLICIES`。
- `backend/task_system/graphs/task_graph_models.py:520` 到 `backend/task_system/graphs/task_graph_models.py:523` 有编译期校验。
- 运行时仍主要按 completed upstream 判断。

修正：

- `GraphReadinessEvaluator` 必须实现所有已公开策略的运行时语义。
- 第一阶段必须覆盖这些策略的结构测试：
  - `wait_all_upstream_completed`
  - `wait_any_upstream_completed`
  - `wait_required_contracts`
  - `wait_handoff_ack`
  - `fire_and_continue`
  - `manual_release`
  - `all_success`
  - `any_success`
  - `quorum`
  - `coordinator_decides`
  - `allow_partial_with_issues`
  - `fail_on_any_error`

### P2：恢复和后台监督可能重新决定路线

现状：

- `backend/harness/graph/resume.py` 和 `backend/harness/graph/background_supervisor.py` 负责恢复、重排和后台监督。
- 当前方案中它们的边界需要收紧，否则容易从 stale node state 重新计算 ready。

修正：

- 恢复只读 checkpoint 中的 canonical `edge_states`、`node_states`、pending work orders。
- 后台监督只处理已经被 readiness decision 确认的 active/ready work order。
- 恢复和后台监督不得根据 upstream completed 重新推断路线。

### P2：语义幂等键与执行实例键边界不清

现状：

- `backend/harness/graph/models.py:430` 的 `GraphNodeWorkOrder.idempotency_key` 默认来自 `graph_run_id:node_id:stable_hash(explicit_inputs)`。
- `backend/harness/graph/context_materializer.py:55` 的 `work_order_id` 包含 dispatch seq、graph clock、timestamp。

修正：

- `idempotency_key` 表示语义幂等，不表示某一次执行实例。
- `work_order_id` 表示执行实例，不参与语义路线判断。
- transition decision ref 必须进入语义幂等输入，避免修订、重跑、恢复时误合并。

## 3. 参考架构结论

### 3.1 Dify/graphon 借鉴点

只借鉴三个不变量：

- 图推进由图引擎集中管理。
- 边状态决定 downstream readiness。
- snapshot/restore 恢复已有状态，不重新选择路径。

源码依据：

- Dify `WorkflowEntry` 在 `D:/AI应用/dify/api/core/workflow/workflow_entry.py:155`，`D:/AI应用/dify/api/core/workflow/workflow_entry.py:201` 创建 `GraphEngine`，`D:/AI应用/dify/api/core/workflow/workflow_entry.py:238` 将 `run()` 委托给图引擎。
- graphon `GraphEngine` 在 `D:/AI应用/langchain-agent/.tmp/dify_graphon_review/graphon_wheel/graphon/graph_engine/graph_engine.py:116`，集中持有 state manager、edge processor、ready queue、event manager、worker pool、command processor。
- graphon `EdgeProcessor` 在 `D:/AI应用/langchain-agent/.tmp/dify_graphon_review/graphon_wheel/graphon/graph_engine/graph_traversal/edge_processor.py:18`，`process_node_success` 在 `:43`，普通边推进在 `:65`，分支边处理在 `:119`。
- graphon `GraphStateManager.is_node_ready` 在 `D:/AI应用/langchain-agent/.tmp/dify_graphon_review/graphon_wheel/graphon/graph_engine/graph_state_manager.py:64`，核心语义是 incoming edge 未知会阻塞，至少一个 taken edge 可触发 ready。
- graphon `GraphRuntimeState` 在 `D:/AI应用/langchain-agent/.tmp/dify_graphon_review/graphon_wheel/graphon/runtime/graph_runtime_state.py:506`，snapshot 在 `:677`，from_snapshot 在 `:698`，paused/deferred node API 在 `:721` 到 `:743`。

### 3.2 本项目必须保留的能力

必须保留并接入新权威链：

- `backend/harness/graph/models.py:27` 的 `GraphHarnessConfig`。
- `backend/harness/graph/runtime.py:21` 的 published config 锁定。
- `backend/harness/graph/runtime.py:236` 的静态拓扑视图。
- `backend/harness/graph/runtime.py:280` 的 contract index。
- `backend/harness/graph/loop.py:78` 的 `GraphLoop` 编排入口。
- `backend/harness/graph/context_materializer.py:20` 的 work order 组装。
- `backend/harness/graph/context_materializer.py:316` 到 `backend/harness/graph/context_materializer.py:325` 的 node-worker-only 边界。
- `backend/harness/graph/work_order_executor.py:38` 的 work order 执行器。
- `backend/harness/graph/work_order_executor.py:418` 的契约边界检查。
- `backend/task_system/compiler/graph_harness_config_publisher.py:585` 到 `backend/task_system/compiler/graph_harness_config_publisher.py:631` 的 node/edge protocol index。
- `backend/task_system/compiler/graph_harness_config_publisher.py:845` 到 `backend/task_system/compiler/graph_harness_config_publisher.py:851` 的协议对齐失败机制。

结论：

- Dify 提供推进权威模型。
- 本项目继续保留自己的配置、契约、工作单、人审和证据链。
- 新方案是“本项目运行时权威收束”，不是“替换成 Dify”。

### 3.3 旧写作图配置依据

旧写作图不是一个简单模板，而是一套已经成型的模块化长篇写作图配置。迁移方案必须以这些真实配置为输入。

必须支持直接迁移的 graph id：

- `graph.writing.modular_novel.master`
- `graph.writing.modular_novel.design_init`
- `graph.writing.modular_novel.chapter_cycle`
- `graph.writing.modular_novel.finalize`

源码依据：

- `scripts/configure_writing_modular_novel_graph.py:41` 到 `scripts/configure_writing_modular_novel_graph.py:44` 定义 master/design/chapter/finalize 四个写作图 id。
- `scripts/configure_writing_modular_novel_graph.py:1527` 到 `scripts/configure_writing_modular_novel_graph.py:1531` 会写入三个子图并发布 master graph harness config。
- `scripts/configure_writing_modular_novel_graph.py:2363` 到 `scripts/configure_writing_modular_novel_graph.py:2415` 的 `_upsert_imported_module_graph` 会把业务边、memory 边、revision 边、loop frames 一起写入旧写作图。
- `scripts/configure_writing_modular_novel_graph.py:2989` 到 `scripts/configure_writing_modular_novel_graph.py:3032` 的 `_revision_edges_for_nodes` 已经生成 `revision_request` 边，并声明 `trigger: {"verdict": "revise"}`、返修交接包、清理字段等旧语义。
- `scripts/configure_writing_modular_novel_graph.py:3694` 到 `scripts/configure_writing_modular_novel_graph.py:3728` 的 `_review_gate_policy` 已经定义审核允许裁决、返修目标、approved slice schema、revision packet schema。
- `scripts/configure_writing_modular_novel_graph.py:3966` 到 `scripts/configure_writing_modular_novel_graph.py:4080` 的 `_graph_contract_bindings` 和 `_chapter_loop_frames` 定义章节批次、单章循环、分卷循环和章节进度路由。
- `scripts/configure_writing_modular_novel_graph.py:4091` 到 `scripts/configure_writing_modular_novel_graph.py:4128` 的 `_chapter_initial_graph_loop_inputs` 定义旧章节循环初始输入。
- `backend/task_system/graphs/semantic_relations.py:28` 到 `backend/task_system/graphs/semantic_relations.py:78` 定义写作草稿审核、通过提交、返修、复审、驳回转人工的语义关系。
- `backend/task_system/contracts/writing_contract_families.py:30` 到 `backend/task_system/contracts/writing_contract_families.py:74` 定义写作草稿、审核裁决、返修请求、提交回执、记忆更新合同族。
- `backend/task_system/runtime_semantics/chapter_progress.py:6` 到 `backend/task_system/runtime_semantics/chapter_progress.py:174` 定义章节进度 receipt 的规范化和校验。
- `backend/task_system/runtime_semantics/review_gate_verdict.py:6` 到 `backend/task_system/runtime_semantics/review_gate_verdict.py:153` 定义审核裁决 pass/revise/reject/human_review_required 的抽取和分类。
- `backend/api/graph_task_instances.py:72` 到 `backend/api/graph_task_instances.py:82` 定义旧写作章节动作 `approve`、`request_revision`、`replace_with_user_text` 到 pass/revise/replace 的映射。
- `backend/api/graph_task_instances.py:654` 到 `backend/api/graph_task_instances.py:739` 将写作章节动作转换成人审 decision payload。

迁移结论：

- 旧写作图配置必须被视为 legacy source format。
- 旧写作图不允许在运行时保留旧推进分支。
- 旧配置必须通过 `writing_graph_config_migrator.py` 转换成新 canonical transition/readiness 配置。
- 迁移后 graph id、node id、edge id 必须保持稳定，用户不需要重建写作图。

## 4. 统一目标结构

### 4.1 模块职责

| 模块 | 最终职责 | 允许做 | 禁止做 |
| --- | --- | --- | --- |
| `GraphRuntime` | 配置锁定与 runtime envelope 创建 | 校验 published config、写入 static topology 和 contract index | 判断节点 ready、改 edge state |
| `GraphLoop` | 单一推进编排入口 | 接收 trigger、调用 transition/readiness/materializer、写 checkpoint、发事件 | 自己决定下游路线 |
| `GraphTransitionProcessor` | 唯一边状态转移权威 | 根据 trigger 产出 `GraphTransitionPlan` | 组装 work order、执行节点、写 checkpoint |
| `GraphReadinessEvaluator` | 唯一节点就绪判断权威 | 根据 edge/node state 和 wait/join policy 产出 `GraphReadinessDecision` | 修改 edge state、读取模型输出文本 |
| `GraphContextMaterializer` | work order 组装 | 把 readiness decision 转成 work order | 判断路线、跳过 edge contract |
| `GraphNodeWorkOrderExecutor` | 节点执行 | 执行工作单并返回结构化 result | 推进下游、修改 edge state |
| `GraphResumeService` | 恢复 | 读取 checkpoint 并恢复 canonical state | 重选条件分支、补造边状态 |
| `GraphRunBackgroundSupervisor` | 后台监督 | 重排 stale active work order、处理已声明 recoverable 状态 | 根据 completed upstream 推断 ready |

### 4.2 唯一推进入口

`GraphLoop` 内部统一成一个私有入口：

```text
_advance_with_transition(
    trigger: GraphTransitionInput,
    state: GraphLoopState,
    graph_config: GraphHarnessConfig,
) -> GraphLoopAdvance
```

所有推进入口必须调用它：

- `initialize`
- `accept_node_result`
- `apply_human_gate_decision_and_checkpoint`
- `apply_human_edge_decision_and_checkpoint`
- `reset_source_failed_edges_for_nodes_and_checkpoint`
- 恢复后需要重排 ready work orders 的入口

`_advance_with_transition` 固定步骤：

```text
1. assert_graph_config_compatible_with_state
2. transition_plan = GraphTransitionProcessor.plan(trigger, state, graph_config)
3. next_state = apply_transition_plan(state, transition_plan)
4. readiness = GraphReadinessEvaluator.evaluate(next_state, graph_config)
5. work_orders = GraphContextMaterializer.materialize(readiness.ready_nodes)
6. checkpoint = CheckpointStore.put_checkpoint(next_state, pending_work_orders=work_orders)
7. return GraphLoopAdvance(next_state, checkpoint, work_orders, events)
```

例外：

- 初始化时还没有 checkpoint state，可以使用 `GraphTransitionInput(trigger_type="initialize")`，但仍必须走 transition + readiness。
- 纯查询方法不调用该入口。
- runtime settings patch 只改 runtime settings，不推进图路线。

## 5. 统一数据结构

### 5.1 `GraphEdgeStatus`

固定枚举：

```text
pending
ready
skipped
source_failed
waiting_human
blocked
```

语义：

| 状态 | 含义 | 是否可使目标节点 ready |
| --- | --- | --- |
| `pending` | 源节点、人审或 ack 尚未产生推进证据 | 否 |
| `ready` | 该边已被选择并可向目标节点交付结果 | 是 |
| `skipped` | 条件、人审或策略选择中明确未走此边 | 否，但不阻塞 |
| `source_failed` | 源节点失败导致此边无法正常交付 | 默认否，除非 failure policy 明确允许 |
| `waiting_human` | 边到达人审等待态，尚未释放 | 否 |
| `blocked` | 契约、策略、权限或恢复一致性失败 | 否，且应进入阻塞诊断 |

### 5.2 `GraphEdgeState`

必须字段：

```text
edge_id: str
source_node_id: str
target_node_id: str
status: GraphEdgeStatus
reason: str
decision_ref: str
source_result_ref: str
human_decision_ref: str
selected_handle: str
policy_snapshot: dict
graph_clock_seq: int
updated_at: float
```

规则：

- `status` 是 readiness evaluator 的唯一推进状态输入。
- `decision_ref` 必须指向 node result、人审 decision、初始化 decision、失败重置 decision 或恢复 decision。
- 没有 `decision_ref` 的状态变更不得写入 checkpoint。
- `policy_snapshot` 保存边转移当时使用的 wait/join/failure/human 策略，便于审计和恢复。

### 5.3 `GraphTransitionInput`

固定类型：

```text
trigger_type:
  initialize
  node_result
  human_gate_decision
  human_edge_decision
  failure_reset
  resume_requeue

payload: dict
graph_run_id: str
config_id: str
config_hash: str
graph_clock_seq: int
```

规则：

- `node_result` 来自 `GraphNodeWorkOrderExecutor` 的结构化结果。
- `human_gate_decision` 来自 human gate，不得直接包含“把某节点 ready”的命令。
- `human_edge_decision` 只表达边选择、释放或拒绝。
- `resume_requeue` 只能引用 checkpoint 中已有 ready/active 状态。
- `failure_reset` 只能重置已声明可恢复节点或边，不能创建新路线。

### 5.4 `GraphTransitionPlan`

固定输出：

```text
edge_updates: tuple[GraphEdgeState, ...]
node_updates: tuple[GraphNodeStatePatch, ...]
blocked_reasons: tuple[dict, ...]
events: tuple[dict, ...]
diagnostics: dict
```

规则：

- `GraphTransitionProcessor` 只产出 plan，不写 checkpoint。
- `GraphLoop` 负责应用 plan 并写 checkpoint。
- plan 中的每个 edge update 都必须有 `decision_ref`。
- plan 不包含 work order。

### 5.5 `GraphReadinessDecision`

固定输出：

```text
ready_node_ids: tuple[str, ...]
blocked_node_ids: tuple[str, ...]
waiting_node_ids: tuple[str, ...]
skipped_node_ids: tuple[str, ...]
reasons: dict[str, dict]
```

规则：

- readiness decision 不改状态，只说明“此刻哪些节点可以派发”。
- `GraphLoop` 根据 decision 调用 `GraphContextMaterializer`。
- `GraphContextMaterializer` 不重新判断 ready。

## 6. 统一转移规则

### 6.1 初始化

输入：`trigger_type="initialize"`

规则：

- 无 required incoming edge 的 root/start 节点进入 ready decision。
- 所有普通边初始为 `pending`。
- manual gate 起始节点如需人工释放，进入 `waiting_human` 或等待节点状态，不直接 ready。
- 初始化必须写入 initial decision ref。

输出：

- 初始 `edge_states`
- 初始 `node_states`
- root readiness decision
- checkpoint

### 6.2 普通节点成功

输入：`trigger_type="node_result"`，result status 为 success。

规则：

- 普通 outgoing edge：`pending -> ready`。
- 条件 outgoing edge：被选中的边 `pending -> ready`，未选中的边 `pending -> skipped`。
- 需要人审释放的 outgoing edge：`pending -> waiting_human`。
- 未声明 outgoing edge：不产生 edge update。
- 所有 edge update 写入 `source_result_ref`。

禁止：

- 根据目标节点 id 直接标记 ready。
- 未声明 edge 时临时补造 edge。

### 6.3 普通节点失败

输入：`trigger_type="node_result"`，result status 为 failed。

规则：

- 默认 outgoing edge：`pending -> source_failed`。
- 如果 edge failure policy 是 `allow_partial`，可将允许部分交付的边转为 `ready`，但必须记录 issue refs。
- 如果 edge failure policy 是 `isolate_failure`，目标节点不 ready，边记录 `source_failed`，失败不传播到其他无关分支。
- 如果 edge failure policy 是 `fail_downstream`，目标节点进入 blocked/failed 诊断。
- 如果 edge failure policy 是 `coordinator_decides`，边进入 `waiting_human` 或 `blocked`，等待 coordinator/human 决策。

禁止：

- 失败后自动选择另一条未声明路线。
- 用空结果让下游继续执行。

### 6.4 human gate approve

输入：`trigger_type="human_gate_decision"`，action 为 `approve_continue`。

规则：

- 与 gate 绑定的继续边：`waiting_human|pending -> ready`。
- 人审 decision ref 写入 `human_decision_ref`。
- 未选中 gate 分支进入 `skipped`。

### 6.5 human gate request_revision

输入：`trigger_type="human_gate_decision"`，action 为 `request_revision`。

规则：

- 只能选择图中声明的 revision edge。
- revision edge：`waiting_human|pending -> ready`。
- 同一 gate 下未选中的 continue/reroute edges：`skipped`。
- 如果没有声明 revision edge，产生 `blocked`，reason 为 `revision_edge_not_declared`。

禁止：

- 直接把被修订节点写成 ready。

### 6.6 human gate reroute_to_node

输入：`trigger_type="human_gate_decision"`，action 为 `reroute_to_node`。

规则：

- 只能选择图中声明的 reroute/control edge。
- 选中的 reroute edge：`waiting_human|pending -> ready`。
- 未选中的同组边：`skipped`。
- 如果目标节点没有声明可达 reroute edge，产生 `blocked`，reason 为 `reroute_edge_not_declared`。

禁止：

- 通过 target node id 绕过 edge contract。

### 6.7 human edge decision

输入：`trigger_type="human_edge_decision"`。

规则：

- approve/release：对应 edge `waiting_human -> ready`。
- reject：对应 edge `waiting_human -> skipped` 或 `blocked`，取决于 edge policy。
- request_more_info：保持 `waiting_human`，追加 decision ref。

### 6.8 failure reset

输入：`trigger_type="failure_reset"`。

规则：

- 只允许重置 `source_failed`、`blocked` 且 policy 标记可恢复的边。
- reset 后边回到 `pending`，并记录 reset decision ref。
- 不重置已完成或已 skipped 的分支，除非图有显式 revision/control edge。

### 6.9 resume requeue

输入：`trigger_type="resume_requeue"`。

规则：

- 不改变边路线。
- 只重新派发 checkpoint 中已记录为 ready 但未完成的节点。
- 如果 checkpoint 缺少必要 edge state，恢复失败，reason 为 `canonical_edge_state_missing`。
- 历史状态需要支持时，只允许写一次性迁移脚本，不允许运行时静默猜测。

## 7. 统一就绪规则

### 7.1 基础规则

一个节点可派发必须同时满足：

- 节点不是 completed/running/failed/blocked/waiting_human。
- 节点输入契约可由 ready incoming edge 或 root input 满足。
- 节点 wait policy 满足。
- 节点 join policy 满足。
- 不存在 required incoming edge 处于 `blocked`。
- 不存在 required human edge 处于 `waiting_human`。

### 7.2 wait policy

| wait_policy | 运行时语义 |
| --- | --- |
| `wait_all_upstream_completed` | 所有 required incoming edge 必须为 `ready`；`skipped` 的非必需边不阻塞 |
| `wait_any_upstream_completed` | 至少一个 eligible incoming edge 为 `ready`；其他 pending 非必需边不阻塞 |
| `wait_required_contracts` | 所有目标节点 input contract 标记 required 的来源必须由 `ready` edge 提供 |
| `wait_handoff_ack` | 对应 edge 必须处于 ack 已满足后的 `ready`；未 ack 前视为 `pending` 或 `waiting_human` |
| `fire_and_continue` | 源节点成功即可释放对应 edge；目标节点仍必须满足自己的 required input contract |
| `manual_release` | 必须有人审或 coordinator release decision 将 edge 转为 `ready` |

### 7.3 join policy

| join_policy | 运行时语义 |
| --- | --- |
| `all_success` | required incoming edge 全部 `ready`，任一 required `source_failed` 则目标 blocked/failed |
| `any_success` | 至少一个 eligible incoming edge `ready` 即可；失败边记录 issue，不阻塞 |
| `quorum` | 达到节点或 edge policy 声明的 quorum 数量后 ready；未声明 quorum 时配置失败 |
| `coordinator_decides` | evaluator 不自动 ready，等待 coordinator/human decision 转换边状态 |
| `allow_partial_with_issues` | 部分 required 输入失败时允许 ready，但必须把 issue refs 写入 readiness reason |
| `fail_on_any_error` | 任一 required incoming edge `source_failed` 或 `blocked`，目标进入 blocked/failed |

### 7.4 skipped 与 source_failed

- `skipped` 表示明确不走此边，不阻塞目标节点。
- `source_failed` 默认阻塞 required input。
- `source_failed` 是否可忽略只能由 edge failure policy 或 join policy 决定。
- `blocked` 永远不能被 evaluator 当作 ready。

## 8. 旧写作图任务配置直接迁移方案

### 8.1 迁移目标

旧写作图配置必须可以直接迁移到新结构，具体含义如下：

- 用户不需要重画图。
- 已有 graph id 保持不变。
- 已有 node id 保持不变。
- 已有 edge id 保持不变。
- 已有 contract id、payload contract id、artifact policy、memory policy 保持可追踪。
- 已有章节循环、单章循环、分卷循环语义迁移为新 transition/readiness policy。
- 已有审核返修、人审章节动作、章节进度 receipt 迁移为新 edge transition。
- 迁移后运行时只看到新结构，不知道“旧写作图分支”。

### 8.2 迁移入口

固定迁移链路：

```text
TaskGraphDefinition legacy writing graph
-> WritingGraphConfigMigrator.normalize(...)
-> TaskGraphDefinition with canonical transition/readiness metadata
-> GraphHarnessConfigPublisher
-> GraphHarnessConfig
-> GraphRuntime
```

新增文件：

```text
backend/task_system/compiler/writing_graph_config_migrator.py
```

接入点：

- `backend/task_system/compiler/graph_harness_config_publisher.py` 在构造 node/edge protocol index 之前调用迁移器。
- `scripts/configure_writing_modular_novel_graph.py` 继续生成旧写作图配置，但发布时由迁移器补齐新结构。
- `backend/task_system/repositories/task_graph_repository.py` 不承担迁移判断，只负责存取。

禁止：

- `GraphLoop` 根据 graph id 判断是否是旧写作图。
- `GraphReadinessEvaluator` 根据 graph id 写特殊分支。
- `GraphTransitionProcessor` 根据 `graph.writing.modular_novel.*` 写硬编码路线。

### 8.3 旧写作图识别规则

满足任一条件即进入迁移器：

- `graph_id` 等于 `graph.writing.modular_novel.master`、`graph.writing.modular_novel.design_init`、`graph.writing.modular_novel.chapter_cycle`、`graph.writing.modular_novel.finalize`。
- `graph_id` 以 `graph.writing.modular_novel.` 开头。
- `domain_id` 为 `domain.writing.modular_novel` 或 `domain.writing`。
- `contract_bindings.schema.graph_contract_id` 以 `contract.writing.modular_novel.` 开头。
- metadata 中 `managed_by` 指向 modular writing configure script，或 `architecture` 为 `native_modular_task_graph_child` / `compile_time_graph_module_expansion`。

迁移器输出必须写入：

```text
metadata.migration.authority = "task_system.compiler.writing_graph_config_migrator"
metadata.migration.version = "writing_graph_transition_migration.v1"
metadata.migration.source_graph_id = <原 graph_id>
metadata.migration.node_id_preserved = true
metadata.migration.edge_id_preserved = true
```

### 8.4 节点迁移映射

| 旧节点配置 | 新结构映射 |
| --- | --- |
| `node_type=review_gate` | 保留节点；`review_gate_policy` 转为 `transition_policy.review_gate` |
| `review_gate_policy.allowed_verdicts` | 转为 `GraphTransitionProcessor` 可识别的 verdict routing table |
| `review_gate_policy.revision_stage_id` | 必须解析到显式 revision edge；没有则迁移失败 |
| `node_type=manual_gate` 或 `human_gate_policy` | 转为 manual release policy；运行时以 `waiting_human -> ready/skipped/blocked` 表达 |
| `progress_commit_policy` | 转为 progress transition policy，消费 `chapter_progress_receipt` |
| `quality_retry_policy` | 转为 retry transition policy，不直接重置 target ready |
| `execution_mode=barrier` | 强制 `join_policy=all_success` 或显式配置；不允许 `fire_and_continue` |
| `wait_policy` / `join_policy` | 原值保留，并由 `GraphReadinessEvaluator` 执行 |
| `loop_frames` | 转为 loop transition frame，不允许 loop helper 直接改节点 ready |

### 8.5 边迁移映射

| 旧边配置 | 新结构映射 |
| --- | --- |
| `edge_type=handoff` / `structured_handoff` | 普通 dependency edge，初始 `pending`，源成功后 `ready` |
| `edge_type=revision_request` | revision edge，只有审核 verdict 为 revise/blocker/reject/fail_closed 时 `ready` |
| `edge_type=review_feedback` / `repair_feedback` / `conditional_feedback` / `repair_route` | conditional revision/control edge，未选中同组边 `skipped` |
| `edge_type=memory_read` | context edge，不直接决定 ready；缺失按 `on_missing` 变为 blocked 或 issue |
| `edge_type=memory_write_candidate` | commit/candidate edge，记录候选，不让候选对下游作为 committed fact 可见 |
| `edge_type=memory_commit` | commit edge，只有 approval verdict 满足后才 `ready` |
| `ack_required=true` | `wait_handoff_ack` 或 edge ack condition；未 ack 不 ready |
| `failure_propagation_policy` | 转为 edge failure transition policy |
| `artifact_ref_policy.target_input_key` | 进入 edge delivery policy，供 context materializer 使用 |

### 8.6 写作语义关系迁移

| 旧 semantic relation | 新 transition/readiness 语义 |
| --- | --- |
| `writing.draft_to_review` | 草稿节点 success 后审核边 `ready` |
| `writing.review_pass_to_commit` | 审核 verdict 为 pass/pass_with_notes 后提交边 `ready`，返修边 `skipped` |
| `writing.review_revise_to_writer` | 审核 verdict 为 revise/blocker/reject/fail_closed 后 revision edge `ready`，通过边 `skipped` |
| `writing.revision_to_review` | 返修节点 success 后复审边 `ready` |
| `writing.review_reject_to_human` | 审核 verdict 为 human_review_required/reject 时 human edge `waiting_human` |
| `memory.read_required` | 作为 context requirement 输入 readiness；缺失按 on_missing 决定 blocked/issue |
| `memory.write_candidate` | 只产出候选记忆 ref，不直接影响下游事实可见性 |
| `memory.commit_after_review` | 审核通过后候选记忆转 committed，并在 next clock 可见 |

### 8.7 章节循环迁移

旧 `chapter_cycle` 图必须迁移以下循环：

- `loop.chapter_unit`：单章正文循环。
- `loop.chapter_batch`：章节批次循环。
- `loop.volume`：分卷大循环。

迁移规则：

- `chapter_unit_router` 不再直接把 `chapter_draft` 置为 ready，而是输出 `GraphTransitionInput(trigger_type="node_result")` 中的 progress route payload。
- `chapter_progress_router` 不再直接把下一批次或卷审节点置为 ready，而是根据 `chapter_progress_receipt` 产生 edge transition。
- `chapter_progress_receipt` 继续由 `backend/task_system/runtime_semantics/chapter_progress.py` 校验；校验失败则 transition blocked。
- `revision_queue_chapter_indexes`、`revision_active`、`revision_current_chapter_index` 迁移为 loop frame state，不作为 readiness fallback。
- 返修时只能通过 `edge.revision.<review_node>.<revision_target>` 进入目标节点。

### 8.8 写作章节动作 API 迁移

旧 API 入口保留，但 payload 必须转换为新 transition input：

| API action | 旧 decision | 新 transition |
| --- | --- | --- |
| `approve` | `pass` | `GraphTransitionInput(trigger_type="human_edge_decision", decision="approve")` |
| `request_revision` | `revise` | `GraphTransitionInput(trigger_type="human_gate_decision", action="request_revision")` |
| `replace_with_user_text` | `replace` | 先提交 content submission，再释放对应 human edge；没有 edge 则 blocked |

要求：

- `backend/api/graph_task_instances.py` 可以继续接收旧 action 字段。
- API 层只能做 action 到 transition input 的边界转换。
- API 层不得直接调用旧运行时路线分支。

### 8.9 迁移失败条件

以下情况必须在迁移/发布阶段失败，不允许进入 runtime 后再兜底：

- revision node 存在 `review_revision_stage_id`，但没有可解析的 revision edge。
- `review_gate_policy.revision_stage_id` 指向不存在的节点。
- `chapter_cycle` 缺少 `chapter_unit_router`、`chapter_progress_router` 或必要 loop frame。
- `chapter_progress_router` 缺少 `progress_receipt_key` 或无法确认 receipt schema。
- `ack_required=true` 但 `ack_policy` 缺失。
- required input contract 无法从 incoming edge 或 root input 满足。
- `quorum` join policy 缺少 quorum 数量。
- 旧图中存在未知 edge_type 且没有显式 `semantic_role=extension`、`scheduler_role=none`。

### 8.10 直接迁移验收

直接迁移必须通过以下验收：

- 运行配置脚本生成旧写作图后，无需人工编辑即可发布新 `GraphHarnessConfig`。
- master/design/chapter/finalize 四个 graph id 不变。
- 所有旧 node id 和 edge id 不变。
- `GraphHarnessConfig.contracts.edge_contract_index` 中包含迁移后的 transition/readiness policy snapshot。
- `chapter_cycle` 的 revision edge、review gate、progress router、loop frames 全部能生成 canonical transition policy。
- 旧章节动作 API 能继续被前端调用，但后端进入新 transition input。
- runtime 中没有 graph id 特判。

## 9. 分阶段实施计划

### 阶段 0：旧写作图迁移器与迁移基线

目标：

- 让旧写作图配置可以直接迁移到新 transition/readiness 结构。
- 在运行时改造前先锁定写作图迁移输入输出，防止后续实现时破坏旧写作图。

改动文件：

- `backend/task_system/compiler/writing_graph_config_migrator.py`
- `backend/task_system/compiler/graph_harness_config_publisher.py`
- `scripts/configure_writing_modular_novel_graph.py`
- `backend/tests/writing_graph_config_migration_regression.py`

具体动作：

- 新建 `WritingGraphConfigMigrator.normalize(graph)`。
- 在 publisher 构建 protocol index 前调用迁移器。
- 对 master/design/chapter/finalize 四个图做 dry-run migration。
- 将 review gate、revision edge、chapter loop、progress receipt、writing chapter action 所需策略写入 canonical metadata。
- 保持 graph/node/edge id 不变。

验收：

- `graph.writing.modular_novel.master`、`design_init`、`chapter_cycle`、`finalize` 均可迁移。
- 迁移后每条 revision edge 都有 transition policy。
- `chapter_cycle` 迁移后包含 `loop.chapter_unit`、`loop.chapter_batch`、`loop.volume` 的 canonical loop transition policy。
- `rg "graph\\.writing\\.modular_novel" backend/harness/graph` 不出现运行时路线特判。
- `python -m pytest backend/tests/writing_graph_config_migration_regression.py` 通过。

### 阶段 1：数据结构与就绪权威落地

目标：

- 建立统一数据结构。
- 建立 `GraphReadinessEvaluator`。
- 让 `GraphStateMachine.ready_nodes` 通过 evaluator 计算。

改动文件：

- `backend/harness/graph/models.py`
- `backend/harness/graph/readiness_evaluator.py`
- `backend/harness/graph/state_machine.py`
- `backend/tests/graph_state_machine_regression.py`
- 新增 `backend/tests/graph_readiness_evaluator_regression.py`

具体动作：

- 增加 `GraphEdgeStatus`、`GraphTransitionInput`、`GraphTransitionPlan`、`GraphReadinessDecision`。
- 把 `state_machine.ready_nodes` 中 upstream completed 推断删除。
- 实现 wait/join policy 运行时语义。
- 保留 `GraphStateMachine` 的 snapshot/terminal 判断职责，但移除路线判断权威。

验收：

- 单链路、条件分支、skipped、source_failed、waiting_human、blocked 都有测试。
- `rg "all\\(.*upstream.*completed|upstream.*completed" backend/harness/graph/state_machine.py` 不再命中生产 ready 判断。
- `python -m pytest backend/tests/graph_state_machine_regression.py backend/tests/graph_readiness_evaluator_regression.py` 通过。

### 阶段 2：普通节点结果推进收束

目标：

- 建立 `GraphTransitionProcessor`。
- `accept_node_result` 不再直接改下游边/节点。

改动文件：

- `backend/harness/graph/transition_processor.py`
- `backend/harness/graph/loop.py`
- `backend/harness/graph/models.py`
- `backend/tests/graph_harness_new_boundary_regression.py`
- 新增 `backend/tests/graph_transition_processor_regression.py`

具体动作：

- 实现 `GraphTransitionProcessor.plan(...)`。
- 实现 node success、node failed、conditional selected/skipped、source_failed。
- 将 `_edge_states_after_node_result` 删除，或变成 `transition_processor.py` 内部私有函数。
- `GraphLoop.accept_node_result` 改为调用 `_advance_with_transition(...)`。

验收：

- 普通节点成功后只产生 edge update，不直接激活目标节点。
- 条件分支未选中边为 `skipped`。
- 节点失败默认生成 `source_failed`。
- `rg "_edge_states_after_node_result" backend/harness/graph` 只能命中 processor 内部私有实现或不命中。
- `python -m pytest backend/tests/graph_transition_processor_regression.py backend/tests/graph_harness_new_boundary_regression.py` 通过。

### 阶段 3：人审 gate 与人审边收束

目标：

- human gate/human edge 与普通节点结果使用同一 transition/readiness 机制。
- 修订和重路由不再直接激活目标节点。

改动文件：

- `backend/harness/graph/loop.py`
- `backend/harness/graph/transition_processor.py`
- `backend/harness/graph/readiness_evaluator.py`
- `backend/api/graph_task_instances.py`
- 新增 `backend/tests/graph_human_transition_regression.py`

具体动作：

- `apply_human_gate_decision_and_checkpoint` 开头增加 `assert_graph_config_compatible_with_state`。
- `approve_continue`、`request_revision`、`reroute_to_node`、`abort_graph`、`stop_and_checkpoint` 全部转换成 `GraphTransitionInput`。
- `request_revision` 只能选择 revision edge；缺失则 blocked。
- `reroute_to_node` 只能选择 reroute/control edge；缺失则 blocked。
- `apply_human_edge_decision_and_checkpoint` 改为调用 `_advance_with_transition(...)`。

验收：

- `request_revision` 测试证明没有直接 target ready。
- `reroute_to_node` 测试证明缺少显式边时 blocked。
- human decision ref 写入 edge state。
- 写作章节动作 API 的 `approve`、`request_revision`、`replace_with_user_text` 都转换为新 transition input。
- 配置不兼容时 human gate 失败。
- `python -m pytest backend/tests/graph_human_transition_regression.py` 通过。

### 阶段 4：恢复、后台监督和幂等边界

目标：

- resume/background 只恢复或重排规范状态。
- 明确 semantic idempotency key 与 execution instance id。

改动文件：

- `backend/harness/graph/resume.py`
- `backend/harness/graph/background_supervisor.py`
- `backend/harness/graph/context_materializer.py`
- `backend/harness/graph/models.py`
- 新增 `backend/tests/graph_resume_transition_regression.py`

具体动作：

- resume 读取 checkpoint 中的 canonical edge/node state。
- 缺失 canonical edge state 时显式失败，错误码 `canonical_edge_state_missing`。
- background supervisor 只重排 active/ready work order，不重新计算路线。
- `GraphNodeWorkOrder.idempotency_key` 纳入 transition decision ref 或 graph clock 语义输入。
- `work_order_id` 继续作为执行实例 id。

验收：

- checkpoint resume 不重新选择条件分支。
- stale running 重排不产生新路线。
- 修订后同一节点的新 work order 不被旧 idempotency_key 错误合并。
- `python -m pytest backend/tests/graph_resume_transition_regression.py` 通过。

### 阶段 5：旧链路清理与总回归

目标：

- 删除旧推进 helper、旧兼容分支、旧结构测试。
- 确认生产路径只有一套推进权威。

改动文件：

- `backend/harness/graph/loop.py`
- `backend/harness/graph/state_machine.py`
- `backend/tests/*graph*`

具体动作：

- 删除所有绕过 `GraphTransitionProcessor` 的生产推进路径。
- 删除保护旧内部结构的测试。
- 将测试调整为验证 transition plan、edge state、readiness decision、checkpoint resume。

验收：

- `rg "upstream.*completed|target.*ready|direct.*ready|fallback.*ready" backend/harness/graph` 不命中旧推进逻辑。
- `python -m pytest backend/tests -k "graph"` 通过。
- 若涉及前后端运行链路，再按固定端口启动验证：
  - 前端 `http://127.0.0.1:3000`
  - 后端 `http://127.0.0.1:8003`
  - API Base `http://127.0.0.1:8003/api`

## 10. 文件级清单

| 文件 | 必须动作 | 完成定义 |
| --- | --- | --- |
| `backend/task_system/compiler/writing_graph_config_migrator.py` | 新建旧写作图迁移器 | master/design/chapter/finalize 旧配置可迁移到 canonical transition/readiness metadata |
| `backend/task_system/compiler/graph_harness_config_publisher.py` | 接入迁移器并确保策略进入 harness config | 构建 protocol/contract index 前完成写作图迁移，transition/readiness 有完整 policy snapshot 输入 |
| `backend/harness/graph/models.py` | 增加统一 transition/readiness/edge state 数据结构 | 所有结构可序列化、可 checkpoint、字段含义固定 |
| `backend/harness/graph/transition_processor.py` | 新建 | 处理 initialize、node_result、human_gate_decision、human_edge_decision、failure_reset、resume_requeue |
| `backend/harness/graph/readiness_evaluator.py` | 新建 | 实现全部 wait/join policy，输出 `GraphReadinessDecision` |
| `backend/harness/graph/state_machine.py` | 改写 ready 判断 | 不再用 upstream completed 推断 ready |
| `backend/harness/graph/loop.py` | 收束入口 | 所有推进入口调用 `_advance_with_transition(...)` |
| `backend/harness/graph/context_materializer.py` | 接收 readiness decision | 不判断路线，只组装 work order |
| `backend/harness/graph/resume.py` | 收紧恢复边界 | 只恢复 canonical state，缺失则显式失败 |
| `backend/harness/graph/background_supervisor.py` | 收紧后台监督边界 | 只重排 canonical active/ready work order |
| `backend/api/graph_task_instances.py` | 写作章节动作转 transition input | 旧 action API 保留，运行时不走旧路线分支 |
| `backend/task_system/graphs/task_graph_models.py` | 保持策略定义，必要时补充缺失字段校验 | wait/join/failure policy 可被运行时完整读取 |
| `scripts/configure_writing_modular_novel_graph.py` | 作为旧写作图迁移输入基线 | 不要求用户重建图；必要调整只服务于迁移元数据完整性 |
| `backend/tests/writing_graph_config_migration_regression.py` | 新建 | 覆盖旧写作图直接迁移 |
| `backend/tests/graph_readiness_evaluator_regression.py` | 新建 | 覆盖 wait/join/edge status 组合 |
| `backend/tests/graph_transition_processor_regression.py` | 新建 | 覆盖 node result 与 failure transition |
| `backend/tests/graph_human_transition_regression.py` | 新建 | 覆盖 human gate/human edge/revision/reroute |
| `backend/tests/graph_resume_transition_regression.py` | 新建 | 覆盖 resume/background/idempotency |

## 11. 测试矩阵

| 编号 | 场景 | 期望 |
| --- | --- | --- |
| M01 | 旧 `graph.writing.modular_novel.master` 迁移 | graph/node/edge id 保持不变，graph module handoff policy 进入 canonical metadata |
| M02 | 旧 `graph.writing.modular_novel.design_init` 迁移 | world/character/outline review revision edge 可生成 transition policy |
| M03 | 旧 `graph.writing.modular_novel.chapter_cycle` 迁移 | chapter loop、revision edge、progress router、chapter receipt policy 全部可迁移 |
| M04 | 旧 `graph.writing.modular_novel.finalize` 迁移 | final review/final memory handoff 可进入 canonical edge policy |
| M05 | 旧写作章节动作 API | `approve`、`request_revision`、`replace_with_user_text` 均转换成 transition input |
| T01 | A -> B，A success | edge A-B 为 `ready`，B 由 evaluator ready |
| T02 | 条件分支选 A -> B | A-B `ready`，其他同组边 `skipped` |
| T03 | 多上游 all_success | required incoming 全部 `ready` 后才 ready |
| T04 | wait_any | 任一 eligible incoming `ready` 即 ready |
| T05 | wait_required_contracts | required input contract 全部有 ready edge |
| T06 | wait_handoff_ack | ack 未满足前不 ready |
| T07 | fire_and_continue | 只释放声明边，不绕过目标 input contract |
| T08 | manual_release | 无 human/coordinator release 时不 ready |
| T09 | any_success | 一个 ready 即可，失败边记录 issue |
| T10 | quorum | 达到 quorum 数量才 ready，缺失 quorum 配置失败 |
| T11 | coordinator_decides | evaluator 不自动 ready，等待 decision |
| T12 | allow_partial_with_issues | 可 ready，但 readiness reason 必须含 issue refs |
| T13 | fail_on_any_error | 任一 required failure 导致目标 blocked/failed |
| T14 | node failed 默认 | outgoing edge 进入 `source_failed` |
| T15 | human approve | waiting human edge 转 `ready` |
| T16 | human request_revision | 只能走 revision edge；缺失则 blocked |
| T17 | human reroute_to_node | 只能走 reroute/control edge；缺失则 blocked |
| T18 | stop_and_checkpoint | 不新增 ready work order，checkpoint 可恢复 |
| T19 | abort_graph | graph terminal，不再 dispatch |
| T20 | resume | 不重选分支，只恢复 canonical state |
| T21 | stale running requeue | 不创建新路线 |
| T22 | config mismatch | 所有推进入口都失败 |
| T23 | idempotency | 修订和重跑不会被旧 semantic key 错合并 |

最低验证命令：

```powershell
python -m pytest backend/tests/writing_graph_config_migration_regression.py
python -m pytest backend/tests/graph_readiness_evaluator_regression.py
python -m pytest backend/tests/graph_transition_processor_regression.py
python -m pytest backend/tests/graph_human_transition_regression.py
python -m pytest backend/tests/graph_resume_transition_regression.py
python -m pytest backend/tests -k "graph"
```

## 12. 迁移和清理规则

迁移规则：

- 新数据结构与 processor 可以先在阶段内落地，但对应旧生产路径必须在同阶段删除。
- 旧写作图配置允许迁移层读取旧字段，但迁移输出必须是新 canonical metadata。
- 旧写作图迁移层只存在于 compiler/publisher，不存在于 runtime。
- 历史 checkpoint 缺少 canonical edge state 时，不允许运行时猜测。
- 如果必须支持历史 checkpoint，只允许一次性迁移脚本，迁移结果必须带 migration decision ref。

清理规则：

- 阶段 0 建立旧写作图迁移基线，确认旧配置不用人工重建。
- 阶段 1 删除 upstream-completed ready 生产逻辑。
- 阶段 2 删除普通节点结果散落 edge helper。
- 阶段 3 删除 human gate/human edge 直接 ready 路径。
- 阶段 4 删除 resume/background 中的路线推断。
- 阶段 5 删除旧结构测试和无权威 helper。

不允许：

- 新 processor 失败后 fallback 到旧 ready 逻辑。
- 为了兼容旧测试保留双路线。
- 用 `work_order_id` 判断语义是否已推进。
- 用模型输出文本、节点名称或 target node id 绕过 edge contract。
- 在 `backend/harness/graph` 运行时按 `graph.writing.modular_novel.*` 做路线特判。

## 13. 实施后的验收标准

实施完成必须同时满足：

- 旧写作图配置可直接迁移，无需用户重建 master/design/chapter/finalize 图。
- 迁移后 graph id、node id、edge id 保持稳定。
- 图推进只有 `GraphTransitionProcessor` 一个边转移权威。
- 节点就绪只有 `GraphReadinessEvaluator` 一个判断权威。
- `GraphLoop` 只编排，不直接决定下游节点。
- `GraphContextMaterializer` 只组装 work order。
- `GraphNodeWorkOrderExecutor` 只执行节点，不推进图。
- 人审 approve、revision、reroute 都通过 edge transition。
- resume/background 不重新选择路线。
- 所有 edge state 变更都有 `decision_ref`。
- `python -m pytest backend/tests -k "graph"` 通过。

## 14. 实施前确认

当前文档已经统一为一个明确方案。需要用户确认的不是“选哪种架构”，而是是否按此方案进入代码实施。

确认实施后，必须按阶段 1 到阶段 5 顺序推进。若实施中发现本方案的关键假设不成立，应暂停并更新方案，不允许用旧链路补丁继续绕过。
