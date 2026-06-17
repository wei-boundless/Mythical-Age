# 图任务系统（Task Graph System）全面运行机制总报告

> **版本**: 1.0  
> **审查范围**: 35+ 核心文件，覆盖超过 15,000 行代码  
> **报告日期**: 2026-06-17

---

## 一、系统全景架构

图任务系统是本项目的多步骤 Agent 工作流编排与执行引擎，支持定义、编译、调度和执行有向图（DAG）结构的多智能体任务流。系统设计原则是**分层分离、契约驱动**。

```
┌─────────────────────────────────────────────────────────────────┐
│                     定义层（task_graph_models）                  │
│   TaskGraphDefinition / TaskGraphNodeDefinition / TaskGraphEdge  │
└───────────────────────┬─────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│                   规范化层（layered_graph_normalizer）            │
│   execution / semantic / timeline / memory / artifact / revision  │
└───────────────────────┬─────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│                 可组合视图层（composable_graph_builder）          │
│              Unit / Port / Interface / GraphModuleExpansion      │
└───────────────────────┬─────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│                   编译层（graph_compiler）                        │
│        node/edge/resource/system 合约 + deploy package           │
└───────────────────────┬─────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│              Harness Config 发布层（graph_harness_config_publisher）│
│    图模块展开 + 协议索引 + 环境锁定 + 内容哈希 + GraphHarnessConfig  │
└───────────────────────┬─────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│                 运行时 Harness 层（harness/graph/）               │
│  GraphRuntime → GraphLoop → GraphRunRunner → WorkOrderExecutor   │
│  ContextMaterializer / StateMachine / TransitionProcessor        │
│  ReadinessEvaluator / Supervisor / ResumeService / Checkpoint    │
│  FlowPacket / FlowEdges / EdgeContracts / OutputPolicy           │
│  MemoryContext / LoopEngine / BackgroundSupervisor               │
└──────────┬──────────────────────────────────────────────────────┘
           ↕
┌─────────────────────────────────────────────────────────────────┐
│   API 层 & 实例管理层 & 生命周期层                               │
│   api/orchestration.py / api/graph_task_instances.py             │
│   task_system/graph_instances/ / lifecycle_manager.py            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、定义层 — 数据结构模型

**核心文件**: `backend/task_system/graphs/task_graph_models.py`（914 行）

### 2.1 三个核心数据结构

| 数据结构 | 角色 | 关键字段 |
|---|---|---|
| `TaskGraphDefinition` | 图根容器 | `graph_id`, `title`, `graph_kind`（single_agent/multi_agent/coordination）, `entry_node_id`, `output_node_id`, `nodes`, `edges`, `contract_bindings`, `loop_frames`, `publish_state`（draft/published/archived）, `enabled` |
| `TaskGraphNodeDefinition` | 节点 | `node_id`, `node_type`（27 种）, `agent_id`, `execution_mode`（6 种）, `wait_policy`（6 种）, `join_policy`（6 种）, `contract_bindings`, +20+ 策略字段 |
| `TaskGraphEdgeDefinition` | 边 | `edge_id`, `source/target_node_id`, `edge_type`, `failure_propagation_policy`（4 种）, `result_delivery_policy`（4 种）, `ack_policy`, `timeout_policy` |

### 2.2 27 种节点类型

**Agent 执行类**: `agent`, `agent_role`, `coordinator`, `subtask`

**记忆/资源类（10 种）**: `memory`, `memory_resource`, `memory_repository`, `memory_collection`, `memory_read`, `memory_write`, `memory_handoff`, `memory_commit`, `memory_finalize`, `artifact_repository`

**账本/存储类（5 种）**: `thread_ledger`, `progress_ledger`, `issue_ledger`, `runtime_state_store`, `working_memory_store`

**控制类（5 种）**: `barrier`, `manual_gate`, `review_gate`, `runtime_monitor`, `loop_frame`

**其他（3 种）**: `input`, `output`, `tool`, `graph_module`

### 2.3 节点执行策略

**执行模式（6 种）**: `sync`, `async`, `parallel`, `background`, `barrier`, `manual_gate`

**等待策略（6 种）**:
- `wait_all_upstream_completed` — 所有上游完成后执行
- `wait_any_upstream_completed` — 任一上游完成后执行
- `wait_required_contracts` — 所需合约到齐后执行
- `wait_handoff_ack` — 等待交接确认
- `fire_and_continue` — 触发即继续
- `manual_release` — 人工释放后执行

**合并策略（6 种）**: `all_success`, `any_success`, `quorum`, `coordinator_decides`, `allow_partial_with_issues`, `fail_on_any_error`

### 2.4 边的故障传播与交付策略

**故障传播（4 种）**: `fail_downstream`, `isolate_failure`, `coordinator_decides`, `allow_partial`

**结果交付（4 种）**: `contract_payload_and_refs`, `refs_only`, `summary_and_refs`, `notification_only`

### 2.5 验证系统

`validate_task_graph()` 检查以下约 30 种规则：
- 空图、重复 ID、入口/出口节点存在性
- 节点类型合法性
- Agent 节点必填字段
- 后台/并行/汇合/人工门控节点的特殊约束
- 边两端节点存在性

### 2.6 Contract Binding 系统

`normalize_graph_contract_bindings` / `normalize_node_contract_bindings` / `normalize_edge_contract_bindings`：

- 将输入的扁平策略字段分层标准化到 `schema` / `execution` / `memory` / `runtime` / `artifact` / `handoff` / `temporal` / `unit_batch` / `governance` / `acceptance` 等 12 个 sections
- 运行时检查 `RUNTIME_CONTRACT_KEYS`（共 18 个合法 key）
- 检查并拒绝原始密钥泄露

---

## 三、规范化层 — 语义分层

**核心文件**: `backend/task_system/compiler/layered_graph_normalizer.py`（783 行）

`normalize_task_graph_layers()` 将任务图按语义层切分为独立视图：

| 层 | 内容 |
|---|---|
| execution | 基础节点和边（控制流） |
| semantic | 语义关系边 |
| timeline | 时间线边、时间块、循环帧 |
| memory | 资源节点、记忆读写/交接边 |
| artifact_context | 制品上下文边 |
| revision | 修订反馈边 |

同时推导 `memory_matrix`（哪些节点读写哪些记忆集合）和 `memory_protocol`（访问权限协议），为后续编译提供全量语义信息。

---

## 四、可组合视图层 — Unit/Port 模型

**核心文件**: `backend/task_system/graphs/composable_graph_builder.py` + `composable_graph_models.py`（623 行）

从一个已规范化的图构建出可组合视图，将图节点映射为可组合单元：

- **ComposableUnit** — 可执行单元（type: node / graph / resource / human_gate / tool / runtime_monitor）
- **UnitInterface** — 单元接口（input_ports / output_ports）
- **UnitPort** — 端口（direction: input/output + payload_contract_id）
- **UnitPortEdge** — 端口间连接
- **GraphModuleExpansionPlan** — 图模块扩展计划

支持**元数据覆盖机制**（`_composable_overlay`）：图定义的 `metadata.composable_graph` 可以显式覆盖派生视图。

---

## 五、编译层 — 合约生成

**核心文件**: `backend/task_system/compiler/graph_compiler.py`（369 行）

`build_graph_compilation_unit()` 将规范化的图定义编译成可执行的合约集合：

| 产出 | 用途 |
|---|---|
| `graph_binding_contract` | 图的全局绑定契约 |
| `node_contract_index` | 每个节点的执行、权限、模型合约 |
| `edge_contract_index` | 边的手续、交付、失败传播合约 |
| `resource_contract_index` | 资源节点的生命周期合约 |
| `system_node_contract_index` | 系统维护节点合约 |
| `configurator_write_contract` | 配置器写入合约 |
| `maintenance_contract` | 维护合约 |
| `deployment_package` | 发布包 |
| `compile_report` | 编译报告 |

支持四种子合约构建器：
- `node_contract_models.py` — 节点级合约
- `edge_contract_models.py` — 边级合约
- `resource_contract_models.py` — 资源合约
- `system_node_contracts.py` — 系统合约

---

## 六、Harness Config 发布层 — 核心编译枢纽

**核心文件**: `backend/task_system/compiler/graph_harness_config_publisher.py`（1516 行）

这是最复杂的层次。`build_graph_harness_config_from_graph()` 完成以下工作：

### 6.1 图模块扩展

解析 `composition_plans`，自动展开 `graph_module` 节点：
- 递归导入引用的子图
- 作用域前缀（`scope_prefix`）隔离节点 ID
- 生成桥接边（`_composition_bridge_edges`）
- 防止循环扩展（`visited_graph_ids` 检测）

### 6.2 协议索引构建

`_build_protocol_indexes()` 生成包含以下内容的完整协议索引：
- **node_protocol_index** — 每个节点的合约 ID、输入/输出键、内存资源访问权限
- **edge_protocol_index** — 每个边的合约对齐、交付策略、ACK 策略、源/目标键映射
- **协议对齐检查**（`_edge_protocol_issues`）：检查边引用的源输出键是否已声明、payload 是否被目标接受等

### 6.3 合约清单

`_contract_manifest_from_projection()` 构建合约清单，包含所有节点合约和边交接合约。

### 6.4 环境锁定

`_published_environment_payload()` 根据 `task_environment_id` 锁定运行环境配置。

### 6.5 节点配置

`_node_config()` 将图节点编译为完整的 Harness 节点配置：
- 节点身份、执行模式、等待/合并策略
- 合约绑定（schema/execution/memory/handoff 等 12 个 sections）
- 执行器类型（agent / human / review_gate / tool / resource）
- Prompt 合约、上下文策略、门控策略、重试策略、循环合约
- 运行时策略合并

### 6.6 边缘配置

`_edge_config()` 编译边配置，推导 semantic_role 和 scheduler_role。

### 6.7 起始/终结节点推导

`_derive_start_node_ids()` 和 `_derive_terminal_node_ids()` 通过拓扑分析推导未显式声明的起始和终结节点。`_derived_branch_terminal_node_ids()` 支持分支终结节点。

### 6.8 最终产出：GraphHarnessConfig

包含：graph_id、nodes、edges、loop_frames、environment、permissions、tools、agents、contracts（含所有编译产出）、composition_sources、authority_map、diagnostics、content_hash

---

## 七、运行时 Harness 层 — 核心执行引擎

### 7.1 GraphRuntime — 静态装配层

**文件**: `backend/harness/graph/runtime.py`

`start()` 方法：
1. 校验 `GraphHarnessConfig` 的 `content_hash`
2. 生成 `graph_run_id` 和 `task_run_id`
3. 创建 `TaskRun` 和 `GraphRun` 持久化记录
4. 构建 `GraphRuntimeEnvelope`（包含 static_topology_view、contract_index、state_machine_spec、loop_control_spec、memory/sandbox/file scope）
5. 同步 formal memory 规格

### 7.2 GraphLoop — 动态状态控制器

**文件**: `backend/harness/graph/loop.py`（4140 行）

GraphLoop 是整个系统的状态机控制器。

#### initialize() — 图运行初始化
1. 创建初始 `node_states` 和 `edge_states`
2. 计算初始 ready_node_ids
3. 创建 `GraphLoopState`（包含 node_states、edge_states、ready/running/completed/failed/blocked 分类、result_index、result_history、loop_state 等）
4. 调度初始可调度节点（dispatch_ready）
5. 写入 checkpoint

#### dispatch_ready() — 节点调度
- 通过 `GraphStateMachine.ready_nodes()` 计算可调度节点
- 限制 `max_active_nodes` 并发数
- 通过 `GraphContextMaterializer.build_work_order()` 构建工作订单

#### accept_node_result() — 节点结果处理（核心状态机推进）
1. 验证 result 与 state 一致
2. 更新 node_states 状态
3. 通过 `GraphTransitionProcessor` 产生边状态更新
4. 更新 result_index 和 result_history
5. 评估循环路由（`_evaluate_loop_route`）
6. 评估修订路由（`_ready_rejected_revision_targets`）
7. 评估质量重试（`_quality_same_node_retry_decision`）
8. 生成状态快照（`GraphStateMachine.status_snapshot()`）
9. 检测是否达到终结状态并生成 `GraphResultEnvelope`
10. 调度下一批可调度节点
11. 写入 checkpoint

#### 其他关键方法
| 方法 | 用途 |
|---|---|
| `dispatch_ready_and_checkpoint()` | 调度并写入检查点 |
| `patch_runtime_settings_and_checkpoint()` | 动态修改运行时设置 |
| `requeue_nodes_and_checkpoint()` | 重新入队节点 |
| `requeue_blocked_nodes_and_checkpoint()` | 重试阻塞节点 |
| `requeue_recoverable_failed_nodes_and_checkpoint()` | 恢复失败节点 |
| `apply_human_gate_decision_and_checkpoint()` | 人工门控决策 |
| `apply_human_edge_decision_and_checkpoint()` | 人工边决策 |

### 7.3 GraphHarness — 生产外观层

**文件**: `backend/harness/graph_harness.py`

统一的图任务控制外观，封装了：
- `GraphRuntime` — 静态装配
- `GraphLoop` — 状态机控制
- `GraphResumeService` — 恢复服务
- `GraphNodeWorkOrderExecutor` — 工作订单执行器
- `GraphRunRunner` — 执行泵
- `GraphRunBackgroundSupervisor` — 后台调度

主要方法：`start_run()`, `accept_node_result()`, `resume_run()`, `execute_work_order()`, `run_until_idle()`, `submit_run_until_idle()`, `apply_human_gate_decision()`, `request_graph_run_pause/resume()`

### 7.4 GraphRunRunner — 执行泵

**文件**: `backend/harness/graph/runner.py`

`run_until_idle()` 的主循环逻辑：
1. 检查运行时控制边界（暂停/停止）
2. 检查状态是否已达终结
3. 检查执行预算（max_node_executions / max_runtime_seconds）
4. 获取活跃工作订单
5. 如无活跃订单则尝试调度新一批节点
6. 逐个执行活跃工作订单，回收结果
7. 循环直到闲置、预算耗尽或控制信号

### 7.5 GraphNodeWorkOrderExecutor — 工作订单执行器

**文件**: `backend/harness/graph/work_order_executor.py`（2014 行）

`execute()` 根据工作类型的路由：
- **agent** → 执行 agent 节点（调用 `execute_graph_agent_work_order_callback`）或确定性进度回执节点
- **human_gate** → 返回 `waiting_human_gate` 等待外部决策
- **tool** → 返回 unsupported（工具节点执行器未连接）

`_execute_agent_node()`：通过回调执行 agent，然后：
1. 提取 artifact refs 并物化
2. 提取 formal memory candidates 并提交
3. 提取 progress receipts（章节进度回执）
4. 运行质量门控检查（`stage_business_acceptance`）
5. 决定最终节点状态（completed/failed/blocked）

### 7.6 GraphContextMaterializer — 上下文实例化

**文件**: `backend/harness/graph/context_materializer.py`

`build_work_order()`：构建 `GraphNodeWorkOrder` 的完整上下文：
- 组装入站上下文（inbound context）
- 构建输入包（input_package）
- 构建图槽（graph_slot：节点合约、边合约、内存合约、输出合约）
- 解析循环引擎上下文（`LoopEngine`）
- 解析内存上下文（`MemoryContextAssembler`）
- 构建执行输入包、产物视图、预期结果合约

### 7.7 边与包系统

| 文件 | 角色 |
|---|---|
| `flow_packet.py` | `FlowPacket` 数据结构（packet_id, packet_type, source/target, edge_id, payload_summary, artifact_refs, memory_refs 等），支持 30+ 种边类型 |
| `flow_edges.py` | `build_inbound_flow_edges()` / `build_outbound_flow_edges()` 过滤出包含 flow packet 的边 |
| `edge_contracts.py` | `edge_contract_or_projection()` 解析边的合约/协议索引 |
| `language.py` | 定义边的 semantic_role 和 scheduler_role 推导逻辑，支持 8 种语义角色和 7 种调度角色 |

### 7.8 状态机与就绪性评估

| 组件 | 文件 | 角色 |
|---|---|---|
| `GraphStateMachine` | `state_machine.py` | 状态分类和拓扑就绪性计算：初始化节点/边状态、计算可调度节点 |
| `GraphReadinessEvaluator` | `readiness_evaluator.py` | 细致的就绪性评估：循环作用域闭合、门控、入站边就绪性、拓扑就绪性 |
| `GraphTransitionProcessor` | `transition_processor.py` | 响应节点结果触发边状态转换 |
| `GraphSupervisor` | `supervisor.py` | 运行时监控观察，检测风险和维护候选 |

### 7.9 恢复与检查点

**文件**: `backend/harness/graph/resume.py` + `checkpoint_store.py`

`GraphResumeService.resume()` 从检查点恢复图运行：
1. 加载最新检查点
2. 恢复活跃工作订单
3. 恢复陈旧执行器
4. 恢复可恢复的失败节点
5. 重新调度

`GraphCheckpointStore` 协议定义了检查点的 put/get/delete 接口。

### 7.10 其他关键组件

| 组件 | 文件 | 角色 |
|---|---|---|
| `OutputPolicyResolver` | `output_policy.py` | 解析节点输出合约，包含产物物化策略、artifact_repository 策略、环境投影 |
| `MemoryContextAssembler` | `memory_context.py` | 解析形式化记忆读取合约 |
| `LoopEngine` | `loop_engine.py` | 解析循环变量（迭代索引、frame 状态、路由历史） |
| `WorkOrderContract` | `work_order_contract.py` | 将工作订单转换为 `TaskRunContract` |
| `GraphRunBackgroundSupervisor` | `background_supervisor.py` | 在 HTTP 请求边界外调度图运行 |

---

## 八、运行时数据模型

**核心文件**: `backend/harness/graph/models.py`（916 行）

| 数据类 | 角色 |
|---|---|
| `GraphHarnessConfig` | 编译后的完整图配置（含内容哈希验证） |
| `GraphRuntimeEnvelope` | 运行时信封（含拓扑视图、合约索引、作用域） |
| `GraphRun` | 图运行持久化记录 |
| `GraphLoopState` | 循环状态（节点/边状态机、工作订单索引、结果索引、循环状态） |
| `GraphEdgeStateRecord` | 边状态记录 |
| `GraphTransitionInput` | 转换触发输入 |
| `GraphTransitionPlan` | 转换计划 |
| `GraphReadinessDecision` | 就绪性决策 |
| `GraphNodeExecutionSlot` | 节点执行槽 |
| `GraphNodeWorkOrder` | 节点工作订单 |
| `NodeResultEnvelope` | 节点结果信封 |
| `GraphResultEnvelope` | 图结果信封 |

---

## 九、API 层

### 9.1 Orchestration API — `api/orchestration.py`

| 端点 | 方法 | 用途 |
|---|---|---|
| `/orchestration/harness/task-graphs/{graph_id}/start` | POST | 直接启动图运行 |
| `/orchestration/harness/runs/{config_id}/dispatch-ready` | GET | 获取可调度节点 |
| `/orchestration/harness/runs/{config_id}/work-order/execute` | POST | 执行单个节点工作订单 |
| `/orchestration/harness/runs/{config_id}/run-until-idle` | POST | 运行到空闲（同步） |
| `/orchestration/harness/runs/{config_id}/submit-run-until-idle` | POST | 提交后台运行 |
| `/orchestration/harness/runs/{config_id}/control` | POST | 暂停/恢复/终止 |
| `/orchestration/harness/runs/{config_id}/delete` | DELETE | 删除图运行 |

### 9.2 Graph Task Instances API — `api/graph_task_instances.py`

| 端点 | 方法 | 用途 |
|---|---|---|
| `/orchestration/graph-tasks` | GET | 列出注册图 |
| `/orchestration/graph-tasks` | POST | 创建图任务实例 |
| `/orchestration/graph-tasks/{instance_id}/start` | POST | 启动实例运行 |
| `/orchestration/graph-tasks/{instance_id}/human-edge/decision` | POST | 提交人工边决策 |
| `/orchestration/graph-tasks/{instance_id}/writing/chapter-action` | POST | 写作流程章节操作 |

---

## 十、图任务实例管理

**目录**: `backend/task_system/graph_instances/`

| 文件 | 角色 |
|---|---|
| `models.py` | `GraphTaskInstance` — 持久化实例状态（idle→running→completed） |
| `repository.py` | 实例 CRUD（创建、查询、更新、修补） |
| `file_service.py` | 文件空间管理 |
| `decision_models.py` | 人工决策数据模型 |
| `edge_control_service.py` | 边级人工审批服务 |

---

## 十一、生命周期管理器

**文件**: `backend/harness/graph/lifecycle_manager.py`

`GraphTaskLifecycleManager.delete_graph_run()` 清理图运行的完整作用域：
- 形式化记忆（formal memory store）
- 制品仓库（artifact repository）
- 文件系统制品路径
- 提示词会计记录（prompt accounting ledger）
- 执行存储
- 检查点存储
- 运行时事件
- 运行时对象
- 状态索引

---

## 十二、运行时边界与安全

| 维度 | 策略 |
|---|---|
| 节点运行隔离 | `per_node_run_session` 模式 |
| 运行时资源 | 按 `task_run_scope_policy`（默认 `isolated_per_task_run`）隔离 |
| 检查点 | 每个状态变更后写入检查点，支持恢复和调试 |
| 人工门控 | `human_gate_policy` — 等待外部决策 |
| 审查门控 | `review_gate_policy` — 自动审查裁决 |
| 后台节点 | 必须有 `background_policy.enabled`、`max_runtime_seconds` 和 `notification_policy` |
| 内容哈希 | `GraphHarnessConfig` 校验 content_hash 保证配置完整性 |
| 权限作用域 | 每个节点有独立的 permission_scope |
| 质量门控 | `business_acceptance` 检查 + 质量重试 + 质量修复路由 |

---

## 十三、运行时语义学

**文件**: `backend/runtime_semantics/models.py` + `compiler.py`

`compile_runtime_semantics_manifest()` 为每个节点和边分配语义角色。

### 节点语义角色

| 角色 | 含义 |
|---|---|
| `producer` | 内容生产者 |
| `validator` | 验证者 |
| `approver` | 审批者 |
| `publisher` | 发布者 |
| `aggregator` | 汇聚者 |
| `router` | 路由器 |
| `resource` | 资源节点 |
| `monitor` | 监控节点 |

### 边语义角色

| 角色 | 含义 |
|---|---|
| `activation` | 激活 |
| `data_input` | 数据输入 |
| `validation_input` | 验证输入 |
| `approval_input` | 审批输入 |
| `publish_input` | 发布输入 |
| `resource_read` | 资源读取 |
| `resource_write` | 资源写入 |
| `reference` | 引用 |
| `retry` | 重试 |
| `failure_route` | 失败路由 |

### 制品状态机

```
produced → pending_validation → validated → published
                                    ↓
                             rejected / superseded / quarantined
```

---

## 十四、循环与路由机制

图任务系统支持完整的循环帧（loop frame）机制：

- 定义 `loop_frame` 包含 `scope_id`, `entry_node_id`, `router_node_id`, `exit_node_id`, `scope_node_ids`
- 迭代通过 `cursor_key`, `start`, `end`, `step` 控制
- 路由决策通过 `_evaluate_loop_route()` 评估进度回执
- 支持 `progress_receipt_key` 和 `metric_target` 两种路由模式
- **修订路由**：检测被拒绝的 review 并重置下游节点
- **质量重试**：在同一节点上重试质量不合格的执行

---

## 十五、现有架构总结

| 维度 | 数据 |
|---|---|
| 核心文件数 | 35+ |
| 代码规模 | 约 15,000+ 行 |
| 节点类型 | 27 种 |
| 执行模式 | 6 种 |
| 等待策略 | 6 种 |
| 合并策略 | 6 种 |
| 边类型 | 30+ 种 |
| 编译产出 | 8 种合约 + 1 个发布包 |
| 运行时组件 | 20+ 个子模块 |
| 检查点 | 每个状态变更后持久化 |
| 恢复 | 支持断点恢复、失败节点重试 |

---

## 附录：核心文件一览

| 层级 | 文件路径 | 行数 |
|---|---|---|
| 定义层 | `backend/task_system/graphs/task_graph_models.py` | 914 |
| 规范化层 | `backend/task_system/compiler/layered_graph_normalizer.py` | 783 |
| 可组合视图层 | `backend/task_system/graphs/composable_graph_builder.py` | 623 |
| 编译层 | `backend/task_system/compiler/graph_compiler.py` | 369 |
| Harness Config 发布层 | `backend/task_system/compiler/graph_harness_config_publisher.py` | 1516 |
| 调度器视图 | `backend/harness/graph/scheduler_view.py` | - |
| 运行时语义学 | `backend/runtime_semantics/` | - |
| 运行时 - Loop | `backend/harness/graph/loop.py` | 4140 |
| 运行时 - 工作订单执行器 | `backend/harness/graph/work_order_executor.py` | 2014 |
| 运行时 - 上下文实例化 | `backend/harness/graph/context_materializer.py` | - |
| 运行时 - GraphHarness | `backend/harness/graph_harness.py` | - |
| 运行时 - 执行泵 | `backend/harness/graph/runner.py` | - |
| 运行时 - 恢复服务 | `backend/harness/graph/resume.py` | - |
| 运行时 - 检查点存储 | `backend/harness/graph/checkpoint_store.py` | 84 |
| 运行时 - 后台调度 | `backend/harness/graph/background_supervisor.py` | 415 |
| 运行时 - 运行时对象 | `backend/harness/graph/runtime_objects.py` | 158 |
| 运行时 - 数据模型 | `backend/harness/graph/models.py` | 916 |
| API | `backend/api/orchestration.py` | - |
| API | `backend/api/graph_task_instances.py` | - |
| 实例管理层 | `backend/task_system/graph_instances/` | - |
| 生命周期管理 | `backend/harness/graph/lifecycle_manager.py` | - |
