# 004-图任务GraphHarness重建计划书

日期：2026-05-28

## 1. 结论

当前单 agent 主链已经回到 `AgentHarness -> AgentLoop`，但图任务链没有重新接回生产系统。现状不是“图任务运行有 bug”，而是图任务从发布配置到 harness 执行的主链被明确切断：

```text
TaskGraphDefinition 可以保存
TaskGraphStandardView 可以预览
GraphHarnessConfig 发布被 stub 掉
GraphHarnessConfigRepository 被 stub 掉
QueryRuntime 没有 graph_harness
orchestration API 仍调用 runtime.query_runtime.graph_harness
旧 GraphHarness / GraphLoop 已迁入 maintenance
```

因此本轮不应该把旧 `GraphCoordinationEngine` 搬回来，也不应该补一层兼容适配。正确动作是重建一条小而明确的图 harness 主链：

```text
Published GraphHarnessConfig
-> GraphRuntime
-> GraphLoop
-> NodeWorkOrder
-> AgentHarness / AgentLoop
-> NodeResultEnvelope
-> GraphLoopState advance
-> GraphResultEnvelope
```

## 2. 成熟架构标准

图任务系统必须满足这些成熟 agent 控制系统标准：

1. 配置发布期和运行期分离。运行期不重新解释用户草稿、不重新编译图、不从 metadata 猜语义。
2. 静态配置和动态状态分离。`GraphHarnessConfig` 是静态合同，`GraphLoopState` 是运行状态。
3. 图循环和 agent 循环分离。`GraphLoop` 只调度节点，`AgentLoop` 执行单 agent 内环。
4. 工具、权限、文件、memory、sandbox 只通过 runtime 装配进入节点，不由 GraphLoop 临时扩大。
5. 节点 prompt 必须是 agent 可执行的角色、职责、输入、输出、裁决标准，不是开发说明。
6. 恢复只依赖已锁定 config 和 checkpoint state，不依赖 live graph。
7. 监控、API、前端只观察或发起明确控制命令，不能反向补图状态。

## 3. 当前代码证据

| 位置 | 当前事实 | 结论 |
|---|---|---|
| `backend/task_system/compiler/graph_harness_config_publisher.py` | `publish_graph_harness_config_for_graph` 直接抛错 | 发布链断开 |
| `backend/task_system/repositories/graph_harness_config_repository.py` | `list/get/get_published_for_graph` 返回空，`upsert` 抛错 | 没有可启动配置仓库 |
| `backend/api/orchestration.py` | 启动 API 读取 published config 后调用 `runtime.query_runtime.graph_harness` | API 已指向目标边界，但生产 runtime 未装配 |
| `backend/query/runtime.py` | 只初始化 `agent_harness` 和 `single_agent_runtime_host` | 缺 GraphHarness 注入 |
| `backend/harness/__init__.py` | 只导出 `AgentHarness` 相关对象 | GraphHarness 已从生产导出删除 |
| `backend/maintenance/legacy_harness_20260528` | 保存旧 GraphHarness、GraphLoop、coordination engine | 只能参考字段和行为，不能整体恢复 |
| `backend/runtime/graph_runtime` | 有 scheduler、monitor、batch 辅助函数 | 可以复用纯函数，但不能作为新 GraphRuntime 权威 |
| `backend/harness/execution/node_protocol` | `NodeExecutionRequest` 等节点协议仍在生产目录 | 可作为节点边界参考，但需要重新校准为 GraphLoop 输出 |
| `backend/runtime/agent_assembly/models.py` | 已有 `WorkOrder / NodeWorkOrder / GraphModuleWorkOrder` | 节点执行单应优先收敛到 WorkOrder 体系 |

## 4. 目标定义

### 4.1 图任务

图任务是用户可选择、可发布、可运行的固定任务形态。它不等于前端画布，也不等于 runtime 临时编译结果。

图任务的运行依据只有一个：

```text
graph_id -> published config_id -> immutable GraphHarnessConfig
```

### 4.2 GraphHarnessConfig

`GraphHarnessConfig` 是 harness 可识别的图任务静态执行合同。

它来自任务系统发布期编译，不来自运行期临时构造。GraphRuntime 和 GraphLoop 只能读它，不能修改它，也不能在缺字段时回头读 `TaskGraphDefinition`。

### 4.3 GraphRuntime

GraphRuntime 是图运行启动时的装配层，负责把已发布配置和平台服务装配成一次运行的启动 envelope。

负责：

```text
校验 config schema/content_hash/status
锁定 config_id/content_hash
创建 graph_run/task_run 记录
装配 runtime services
装配权限、工具、文件、memory、sandbox 可用范围
生成 GraphRuntimeEnvelope
```

不负责：

```text
判断哪个节点 ready
执行 agent
重试节点
合并节点结果
读取 TaskGraphDefinition
调用 task_system compiler
```

### 4.4 GraphLoop

GraphLoop 是图任务动态控制器。

负责：

```text
初始化 GraphLoopState
判断 ready 节点
处理 human gate / review gate
生成 NodeWorkOrder
接收 NodeResultEnvelope
推进节点状态
推进 edge handoff 状态
判断图完成、失败、暂停、等待
写 checkpoint 和事件
```

不负责：

```text
执行模型内环
执行工具内环
选择任务环境
选择任务域
重新编译图
从 metadata 猜配置
扩大节点权限
```

## 5. 字段级合同

### 5.1 GraphHarnessConfig

```python
class GraphHarnessConfig:
    config_id: str
    config_schema_version: str
    graph_id: str
    graph_title: str
    publish_version: str
    status: Literal["published", "archived"]
    content_hash: str
    published_at: float

    task_environment_id: str
    root_task_ref: str

    control: GraphControlConfig
    nodes: tuple[GraphNodeConfig, ...]
    edges: tuple[GraphEdgeConfig, ...]
    loop_frames: tuple[GraphLoopFrameConfig, ...]

    resources: GraphResourceConfig
    memory: GraphMemoryConfig
    artifacts: GraphArtifactConfig
    permissions: GraphPermissionConfig
    tools: GraphToolConfig
    agents: GraphAgentConfig
    contracts: GraphContractConfig
    modules: tuple[GraphModuleConfig, ...]

    diagnostics: dict
    authority_map: dict
    source_refs: dict
```

字段原则：

| 字段 | 所属权威 | 运行期是否可改 |
|---|---|---|
| `config_id/content_hash` | task system publisher | 否 |
| `control` | task system publisher | 否 |
| `nodes/edges` | task system publisher | 否 |
| `permissions/tools` | task environment + task config | 否，运行期只做 permit |
| `contracts` | task system compiler | 否 |
| `diagnostics` | publisher | 否，仅观察 |
| `source_refs` | publisher | 否，只用于审计 |

### 5.2 GraphControlConfig

```python
class GraphControlConfig:
    start_node_ids: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]
    scheduling_policy: dict
    max_active_nodes: int
    completion_policy: dict
    failure_policy: dict
    retry_policy: dict
    checkpoint_policy: dict
    resume_policy: dict
    human_gate_policy: dict
    graph_loop_policy: dict
    batch_policy: dict
    temporal_edges: tuple[dict, ...]
    revision_edges: tuple[dict, ...]
```

`GraphLoop` 只解释这里的控制语义。禁止从 `graph.metadata.graph_loop_policy`、`runtime_policy` 或旧 `coordination_mode` 再取控制语义。

### 5.3 GraphNodeConfig

```python
class GraphNodeConfig:
    node_id: str
    title: str
    node_type: Literal[
        "agent",
        "human_gate",
        "review_gate",
        "tool",
        "graph_module",
        "barrier",
        "input",
        "output",
    ]
    task_ref: str
    agent_id: str
    agent_profile_id: str
    runtime_lane: str

    executor: NodeExecutorConfig
    execution: NodeExecutionConfig
    contracts: NodeContractConfig
    prompt: NodePromptContract
    context: NodeContextConfig
    memory: NodeMemoryConfig
    artifacts: NodeArtifactConfig
    stream: NodeStreamConfig
    gates: NodeGateConfig
    retry: NodeRetryConfig
    permissions: NodePermissionConfig
    tools: NodeToolConfig
    metadata: dict
```

`prompt` 必须面向 agent：

```text
你是一名世界观审核员。
你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。
你不负责替创作者扩写设定。
你需要指出问题、给出裁决、说明是否允许进入下一阶段。
```

禁止写成：

```text
这是 runtime 节点。
根据任务图执行 world_review。
```

### 5.4 GraphEdgeConfig

```python
class GraphEdgeConfig:
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    wait_policy: str
    ack_policy: str
    ack_required: bool
    failure_propagation_policy: str
    result_delivery_policy: str
    payload_contract_id: str
    context_filter_policy: dict
    artifact_ref_policy: dict
    working_memory_handoff_policy: dict
    temporal_policy: dict
    revision_policy: dict
    metadata: dict
```

边只表示节点间控制和交付关系。memory/artifact/resource 边在发布期归一化到标准字段，运行期不再兼容多种别名。

### 5.5 GraphRuntimeEnvelope

```python
class GraphRuntimeEnvelope:
    envelope_id: str
    graph_run_id: str
    task_run_id: str
    session_id: str
    config_id: str
    config_hash: str
    graph_id: str
    initial_inputs: dict
    runtime_services_ref: str
    permission_scope: dict
    file_scope: dict
    memory_scope: dict
    sandbox_scope: dict
    created_at: float
```

`GraphRuntimeEnvelope` 是启动包，不是动态状态。它不保存 raw graph。

### 5.6 GraphLoopState

```python
class GraphLoopState:
    state_id: str
    graph_run_id: str
    task_run_id: str
    session_id: str
    config_id: str
    config_hash: str
    status: Literal[
        "created",
        "running",
        "waiting_node",
        "waiting_user",
        "waiting_approval",
        "paused",
        "completed",
        "failed",
        "cancelled",
    ]

    node_states: dict[str, GraphNodeRunState]
    edge_states: dict[str, GraphEdgeRunState]
    ready_node_ids: tuple[str, ...]
    running_node_ids: tuple[str, ...]
    completed_node_ids: tuple[str, ...]
    failed_node_ids: tuple[str, ...]
    blocked_node_ids: tuple[str, ...]

    active_work_orders: dict[str, str]
    result_index: dict[str, NodeResultEnvelope]
    event_cursor: int
    terminal_reason: str
    diagnostics: dict
```

禁止：

```text
GraphLoopState 保存 TaskGraphDefinition
GraphLoopState 保存 TaskGraphRuntimeSpec 作为恢复依据
GraphLoopState 发现缺字段后补配置
monitor 根据展示需要改 GraphLoopState
```

### 5.7 NodeWorkOrder

目标收敛到 `runtime.agent_assembly.models.WorkOrder / NodeWorkOrder`，不再同时维护 `stage_execution_request` 和 `node_work_order` 两套入口。

```python
class NodeWorkOrder:
    work_order_id: str
    work_kind: Literal["node", "human", "tool", "graph_module"]
    graph_run_id: str
    task_run_id: str
    node_id: str
    task_ref: str
    executor_type: str
    agent_id: str
    agent_profile_id: str
    runtime_lane: str
    message: str
    explicit_inputs: dict
    input_package: dict
    graph_state: dict
    artifact_policy: dict
    memory_snapshot: dict
    artifact_context_packet: dict
    revision_packet: dict
    handoff_packet_refs: tuple[str, ...]
    runtime_assembly: dict
    idempotency_key: str
```

`NodeExecutionRequest` 如果保留，只能作为 `NodeWorkOrder` 的序列化别名或删除对象，不允许成为第二执行入口。

### 5.8 NodeResultEnvelope

```python
class NodeResultEnvelope:
    result_id: str
    graph_run_id: str
    task_run_id: str
    node_id: str
    work_order_id: str
    executor_type: str
    status: Literal["completed", "failed", "cancelled", "waiting_user"]
    outputs: dict
    decisions: dict
    artifact_refs: tuple[str, ...]
    memory_candidates: tuple[dict, ...]
    handoff_summary: str
    error: dict
    diagnostics: dict
    created_at: float
```

`NodeResultEnvelope` 是 GraphLoop 接收节点结果的唯一入口。GraphLoop 不扫描 task run 结果来猜节点完成。

### 5.9 GraphResultEnvelope

```python
class GraphResultEnvelope:
    result_id: str
    graph_run_id: str
    task_run_id: str
    graph_id: str
    config_id: str
    status: Literal["completed", "failed", "cancelled"]
    outputs: dict
    artifact_refs: tuple[str, ...]
    node_result_refs: tuple[str, ...]
    terminal_reason: str
    diagnostics: dict
    created_at: float
```

## 6. 执行链路

### 6.1 发布链路

```text
TaskGraphDefinition
-> validate_task_graph
-> normalize_task_graph_layers
-> compile_task_graph_definition_runtime_spec 仅作为发布期中间产物
-> compile contracts/prompts/resources/permissions/tools
-> GraphHarnessConfig
-> content_hash
-> GraphHarnessConfigRepository.upsert(publish=True)
-> graph_id -> config_id published binding
```

发布完成后，运行期不再读取 `TaskGraphDefinition`。

### 6.2 启动链路

```text
POST /orchestration/harness/task-graphs/{graph_id}/start
-> TaskFlowRegistry.get_published_graph_harness_config(graph_id)
-> GraphHarness.start_run(config, initial_inputs)
-> GraphRuntime.compile_start_envelope
-> GraphLoop.initialize
-> GraphLoop.dispatch_ready
-> NodeWorkOrder
```

### 6.3 节点执行链路

```text
GraphLoop emits NodeWorkOrder
-> GraphHarness dispatches by executor_type
-> executor_type=agent: AgentHarness.run_stream(AgentRunRequest)
-> AgentLoop returns final/task result
-> NodeResultEnvelope
-> GraphLoop.accept_node_result
```

GraphLoop 不调用模型，不调用工具。AgentLoop 不决定图下一个节点。

### 6.4 恢复链路

```text
graph_run_id
-> load GraphLoopState checkpoint
-> load GraphHarnessConfig by config_id
-> verify config_hash
-> continue GraphLoop
```

如果 config 缺失或 hash 不一致，fail closed。禁止 fallback 到 live graph。

### 6.5 子图链路

`graph_module` 是节点 executor 类型，不是单独 runtime。

```text
GraphLoop sees node_type=graph_module
-> NodeWorkOrder(work_kind="graph_module")
-> GraphHarness starts child graph run using linked_config_id
-> child GraphResultEnvelope
-> parent NodeResultEnvelope
-> parent GraphLoop advance
```

子图不能从 graph_id 现场编译。必须绑定已发布 `linked_config_id`。

## 7. 文件级实施计划

### Phase 0：保护边界

目标：先加失败用例，证明旧链不能被误用。

新增或更新：

```text
backend/tests/graph_harness_boundary_regression.py
backend/tests/graph_harness_config_publication_regression.py
backend/tests/graph_loop_no_live_compile_regression.py
```

断言：

```text
GraphLoop 不 import task_system.compiler
GraphLoop 不 import TaskFlowRegistry
GraphLoop 不读取 TaskGraphDefinition
GraphHarness.start_run 不接受 raw graph/runtime_spec
启动缺 published config 返回 409
config hash mismatch fail closed
```

### Phase 1：重建 GraphHarnessConfig 模型和仓库

新增：

```text
backend/harness/graph/models.py
backend/harness/graph/config_repository.py
backend/harness/graph/config_validation.py
```

改造：

```text
backend/task_system/repositories/graph_harness_config_repository.py
backend/task_system/compiler/graph_harness_config_publisher.py
backend/task_system/registry/flow_registry.py
```

要求：

```text
repository 真实读写 storage
published binding 单一
content_hash 稳定
schema 校验 fail closed
publisher 只在发布期调用 task_system compiler
```

### Phase 2：重建 GraphRuntime

新增：

```text
backend/harness/graph/runtime.py
backend/harness/graph/runtime_envelope.py
backend/harness/graph/services.py
```

要求：

```text
GraphRuntime 只接收 GraphHarnessConfig
创建 GraphRuntimeEnvelope
装配文件、memory、tool、permission、sandbox 范围
不判断 ready 节点
不生成 NodeResult
```

### Phase 3：重建 GraphLoop

新增：

```text
backend/harness/graph/loop.py
backend/harness/graph/loop_state.py
backend/harness/graph/scheduler.py
backend/harness/graph/work_order_builder.py
backend/harness/graph/result_envelope.py
backend/harness/graph/checkpoint_store.py
```

可迁移纯逻辑：

```text
backend/runtime/graph_runtime/scheduler.py
backend/runtime/graph_runtime/scheduler_models.py
backend/runtime/graph_runtime/batch_runtime.py
```

迁移条件：

```text
只接受 GraphHarnessConfig/GraphLoopState
删除 TaskGraphRuntimeSpec/dict 双输入
删除 metadata fallback
删除 shadow/diagnostic authority wording
```

### Phase 4：GraphHarness facade 和 QueryRuntime 装配

新增：

```text
backend/harness/graph_harness.py
backend/harness/graph/__init__.py
```

改造：

```text
backend/harness/__init__.py
backend/query/runtime.py
backend/bootstrap/app_runtime.py
```

要求：

```text
harness 导出 AgentHarness 和 GraphHarness
QueryRuntime 初始化 graph_harness
GraphHarness 持有 GraphRuntime + GraphLoop + AgentHarness
GraphHarness 不实现第二套 agent loop
```

### Phase 5：节点执行接入 AgentHarness

改造：

```text
backend/harness/execution/node_protocol/node_execution_request.py
backend/runtime/agent_assembly/models.py
backend/harness/loop/agent_loop.py
backend/harness/runtime/agent_request.py
```

目标：

```text
NodeWorkOrder -> AgentRunRequest
AgentRunRequest 支持 node work order 上下文
AgentLoop final output -> NodeResultEnvelope
```

必须检查 prompt：

```text
节点 message 必须是角色任务语言
禁止“继续执行任务图节点：xxx”这种开发说明成为主要 agent prompt
```

### Phase 6：API 和调度入口收口

改造：

```text
backend/api/orchestration.py
backend/orchestration/coordination_scheduler.py
backend/api/orchestration_harness.py
frontend/src/lib/api.ts
```

目标：

```text
start graph -> GraphHarness.start_run
dispatch ready -> GraphHarness.dispatch_ready
resume -> GraphHarness.resume
accept node result -> GraphHarness.accept_node_result
monitor -> read GraphLoopState projection
```

旧 `coordination_*` API 如果还被前端使用，要么同步重命名为 graph run 语义，要么作为本阶段明确删除对象，不作为内部兼容链保留。

### Phase 7：monitor/read model 重建

改造：

```text
backend/runtime/graph_runtime/run_monitor.py
backend/runtime/graph_runtime/monitoring.py
frontend/src/components/task-graph-monitor
```

目标：

```text
monitor = GraphHarnessConfig + GraphLoopState + events 的投影
monitor 不读取 raw graph
monitor 不读取 TaskGraphRuntimeSpec
monitor 不修改状态
```

### Phase 8：删除旧残留

删除或继续隔离：

```text
backend/maintenance/legacy_harness_20260528/graph_harness.py
backend/maintenance/legacy_harness_20260528/loop_legacy/graph_loop.py
backend/maintenance/legacy_harness_20260528/loop_legacy/graph_coordination/*
backend/orchestration/coordination_recovery.py
backend/orchestration/coordination_replay.py
backend/orchestration/coordination_rewind.py
backend/orchestration/coordination_scheduler.py
```

删除条件：

```text
新 GraphHarness start/resume/result/monitor 测试通过
前端不再调用旧 coordination endpoint
rg 确认生产目录无旧 graph runtime 入口
```

### Phase 9：反推图编辑器

只有后端 `GraphHarnessConfig` 字段稳定后，才改图编辑器。

改造目标：

```text
编辑器字段一一映射 GraphHarnessConfig
TaskGraphStandardView 展示 GraphHarnessConfig preview
保存草稿不发布配置
发布按钮触发 GraphHarnessConfig publication
运行按钮只能启动 published config
```

## 8. 旧结构清理清单

| 旧结构 | 问题 | 动作 |
|---|---|---|
| `TaskGraphRuntimeSpec` 作为运行输入 | 运行期临时编译产物，不是锁定合同 | 限定为发布期中间产物，后续合并进 publisher |
| `stage_execution_request` | 与 WorkOrder 重叠 | 迁移到 NodeWorkOrder，删除双入口 |
| `coordination_run` 命名 | 表达旧多 agent 协调，不等于图任务通用运行 | 内部迁移到 graph_run 语义 |
| `GraphCoordinationEngine` | 过厚，拥有编译、调度、恢复、结果提交多重权力 | 不恢复，按 GraphRuntime/GraphLoop 重写 |
| `runtime/graph_runtime` | 名字像 runtime，实为 scheduler/monitor/batch 辅助 | 纯函数迁入 harness/graph 或改名 |
| graph module 独立 runtime | 模糊子图和 runtime 边界 | 改为 GraphLoop 的 executor 类型 |
| metadata fallback | 运行期第二解释权 | 删除 |
| monitor decision 修改控制状态 | 观察层越权 | monitor 只投影 |

## 9. 验证矩阵

### 后端单元测试

```powershell
python -m pytest backend/tests/graph_harness_config_publication_regression.py -q
python -m pytest backend/tests/graph_harness_boundary_regression.py -q
python -m pytest backend/tests/graph_loop_no_live_compile_regression.py -q
python -m pytest backend/tests/task_graph_scheduler_regression.py -q
python -m pytest backend/tests/task_system_api_regression.py -q
```

### 集成链路测试

```powershell
python -m pytest backend/tests/graph_task_runtime_facade_regression.py -q
python -m pytest backend/tests/runtime_assembly_builder_test.py -q
python -m pytest backend/tests/orchestration_execution_scheduler_regression.py -q
```

### 搜索型结构验证

```powershell
rg "compile_task_graph_definition_runtime_spec|TaskFlowRegistry|get_task_graph" backend/harness
rg "TaskGraphRuntimeSpec" backend/harness backend/api backend/query
rg "stage_execution_request" backend/harness backend/api backend/orchestration
rg "GraphHarness|GraphLoop|graph_harness" backend
```

目标：

```text
backend/harness 不出现 task_system compiler/repository 依赖
GraphLoop 不出现 TaskGraphRuntimeSpec
GraphLoop 不出现 raw graph fallback
NodeWorkOrder 成为节点执行唯一入口
```

### CLI 真实运行验证

涉及启动链路后必须用固定端口实测：

```powershell
# 后端固定 8003
python -m uvicorn main:app --host 127.0.0.1 --port 8003

# 前端固定 3000
npm run dev -- --host 127.0.0.1 --port 3000
```

验证：

```text
保存图草稿
发布图配置
启动图任务
首节点生成 NodeWorkOrder
agent 节点完成后 GraphLoop 推进下一节点
monitor 正确展示 GraphLoopState
resume 不重新编译图
```

## 10. 实施顺序

本计划必须按以下顺序执行：

```text
1. GraphHarnessConfig 模型和仓库
2. publisher 发布配置
3. GraphRuntime 启动 envelope
4. GraphLoop state 初始化和 ready 判断
5. NodeWorkOrder 生成
6. AgentHarness 节点执行接入
7. NodeResultEnvelope 回交推进
8. API 接入
9. monitor 投影
10. 旧 coordination/graph runtime 清理
11. 编辑器字段反推
```

不能先改编辑器，也不能先恢复旧 engine。因为图编辑器的字段必须反推自 GraphHarnessConfig，旧 engine 会重新引入运行期编译和 metadata fallback。

## 11. 成功标准

完成后必须满足：

```text
用户启动的是 graph_id
系统解析到 published GraphHarnessConfig
GraphRuntime 只装配启动 envelope
GraphLoop 只推进 GraphLoopState
节点执行只通过 NodeWorkOrder
agent 节点只通过 AgentHarness / AgentLoop
子图只通过 linked_config_id 启动 child GraphHarness
monitor 只投影 config + state + events
运行期没有任何 graph rebuild / fallback compile
生产目录没有旧 GraphCoordinationEngine 入口
```

## 12. 不做事项

本轮不做：

```text
不恢复旧 GraphCoordinationEngine
不让 GraphLoop 读取 TaskGraphDefinition
不让 GraphLoop 调用 compile_task_graph_definition_runtime_spec
不在 runtime 缺字段时从 metadata 兜底
不把 graph module 写成独立 runtime
不保留 stage_execution_request 和 NodeWorkOrder 双轨
不先改编辑器再猜 harness 字段
```

