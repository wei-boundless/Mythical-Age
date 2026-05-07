# 契约标准化与 Agent Runtime 统一重构计划书

日期：2026-05-08

范围：任务契约、单 Agent workflow、协调任务 topology、Agent runtime 组装、A2A 通信、LangGraph 协调 loop、运行监控。

说明：本文是重新编写的设计书。它只以当前代码和刚刚确定的新原则为依据，不恢复旧具体任务契约，不执行旧计划，不把 A2A 扩展为业务契约系统。

---

## 1. 设计结论

本次重构的中心结论是：

```text
契约是任务运行的声明式控制面。
workflow 是单 Agent 的契约图。
topology 是多 Agent 的契约图。
A2A 是 Agent 间通信协议，不是业务契约本身。
RuntimeAssembly 是契约真正送入 Agent loop 的执行包。
```

系统最终应形成四个稳定对象：

```text
ContractSpec
  用户和任务系统编辑的契约定义。

ContractManifest
  运行前由编译器生成的不可变契约清单。

RuntimeAssembly
  送入单 Agent loop 或节点 Agent loop 的执行包。

ContractStatus
  运行中由 runtime 写入的契约满足状态。
```

四者的关系：

```text
用户编辑任务 / workflow / topology / contract spec
  -> ContractCompiler
  -> ContractManifest
  -> RuntimeAssembly
  -> Agent Loop / Coordination Loop
  -> ContractStatus
  -> 监控与验收
```

---

## 2. 外部参考原则

### 2.1 LangGraph

LangGraph 的 `StateGraph` 强调以结构化 state 驱动节点执行；节点读写共享状态，边和条件路由决定下一步。其 `Send` 适合 fan-out / map-reduce，`Command` 适合把状态更新和路由决策放在同一步。

本系统借鉴点：

1. 协调任务不应靠 prompt 或简单 `stage_order + index` 推进。
2. 协调 loop 应由 `ready_nodes`、`blocked_nodes`、`contract_satisfaction`、`handoff_packets` 等结构化状态驱动。
3. 并行分支和汇聚节点应由图状态决定，而不是写特殊 if 分支。

参考：

- LangGraph Graph API: https://docs.langchain.com/oss/python/langgraph/graph-api

### 2.2 Multi-Agent Handoff

LangChain / OpenAI Agents SDK 的 handoff 都强调：交接不是复制完整上下文，而是显式控制下游 agent 能看到什么。OpenAI Agents SDK 支持 `input_type` 和 `input_filter`；LangChain handoff 文档也强调上下文工程。

本系统借鉴点：

1. 多 Agent 不共享完整主会话历史。
2. 下游节点只接收边契约允许的 handoff packet。
3. 主 Agent 只接收总状态、进度摘要和最终结果 envelope。

参考：

- LangChain Multi-Agent: https://docs.langchain.com/oss/python/langchain/multi-agent
- OpenAI Agents SDK Handoffs: https://openai.github.io/openai-agents-python/handoffs/

### 2.3 A2A Protocol

A2A 定义 Agent Card、Message、Task、Part、Artifact、JSON-RPC / streaming 等协议对象。它解决 Agent 间互操作和通信格式问题，但不定义本项目的业务输入、输出、验收、权限和 runtime 装配。

本系统借鉴点：

1. A2A 是通信层。
2. 边契约负责决定 A2A message 中承载什么业务 payload。
3. Agent Card 用于能力发现和节点 Agent 匹配。

参考：

- A2A Specification: https://a2a-protocol.org/latest/specification/

### 2.4 Spec / Status 模式

Kubernetes controller 和 Temporal durable execution 都强调：用户声明期望状态，runtime 记录实际状态，控制器负责推进与恢复。

本系统借鉴点：

1. `ContractSpec` 是期望状态。
2. `ContractManifest` 是某次运行的编译快照。
3. `ContractStatus` 是运行状态和契约满足度。
4. runtime 不直接改用户编辑的 spec，只写状态和事件。

---

## 3. 当前代码诊断

### 3.1 已有基础

当前系统已经有可继续演进的基础：

1. 契约描述已有雏形：
   - `backend/tasks/contract_models.py`
   - `TaskContractDescriptor`
   - 目前更像派生展示，不是主契约定义。

2. 任务执行 envelope 已存在：
   - `backend/tasks/contracts.py`
   - `TaskContract`
   - 当前偏向单次任务执行，不适合作为可复用契约库。

3. workflow 已存在：
   - `backend/tasks/workflow_models.py`
   - `TaskWorkflowBinding`
   - 当前有 steps、input_boundary、output_boundary、stop_conditions、output_contract_id。

4. 协调拓扑已存在：
   - `backend/tasks/coordination_graph_models.py`
   - `backend/tasks/coordination_graph_compiler.py`
   - 当前能编译节点和边，但不编译业务契约。

5. 协调 runtime 已接入 LangGraph：
   - `backend/orchestration/runtime_loop/langgraph_coordination_runtime.py`
   - `CoordinationRuntimeState`
   - `_stage_accept`
   - `_route_next`
   - `_stage_prepare`
   - `_stage_execute`

6. 阶段契约已有过渡层：
   - `backend/orchestration/runtime_loop/continuation_policy.py`
   - `CoordinationStageContract`
   - 可作为迁移兼容输入，但不能成为最终契约体系。

7. 节点执行请求已有基础：
   - `backend/orchestration/runtime_loop/stage_execution_request.py`
   - 已包含 `explicit_inputs`、`expected_outputs`、`a2a_payload`。

8. 单 Agent 上下文组装口已存在：
   - `backend/orchestration/runtime_loop/context_manager.py`
   - `RuntimeContextManager.prepare_model_context()`
   - 当前仍按单 Agent 模式组装 history、user message、projection、context policy。

9. 官方 A2A 适配器已存在：
   - `backend/agents/a2a_official_adapter.py`
   - 当前负责 Agent Card catalog、官方 Task 构建、协调 A2A preview。

### 3.2 核心问题

当前系统的核心问题不是缺字段，而是缺少统一的契约所有权。

1. 契约不是一等主数据
   - `TaskContractDescriptor` 是派生展示。
   - `TaskContract` 是执行 envelope。
   - 缺少可编辑、可校验、可编译的 `ContractSpec`。

2. workflow 和 topology 没有统一语义
   - workflow 表示单 Agent 步骤流。
   - topology 表示多 Agent 节点图。
   - 二者本质都是执行契约图，但当前没有共同编译模型。

3. runtime assembly 不显式
   - Agent loop 当前主要从 `task_operation`、projection、context policy 中取材料。
   - 缺少一个正式的 `RuntimeAssembly` 来说明本轮 Agent 应该拿什么输入、用什么能力、产出什么、怎么验收。

4. 协调 runtime 仍偏线性
   - `_route_next()` 依赖 `stage_order`。
   - 不能表达复杂拓扑、并行分支、汇聚、人工 gate、失败回路。

5. A2A 和业务契约边界需要锁定
   - A2A payload 已接入。
   - 但后续必须避免把 A2A 当作契约主模型。
   - 正确关系是：边契约编译 handoff packet，A2A 负责承载和传输。

6. 多 Agent 上下文边界尚未建立
   - 当前 `continuation_payload()` 只把 stage request 和 explicit inputs 塞进 `current_turn_context`。
   - 后续必须通过 `RuntimeAssembly` / `NodeRuntimeAssembly` 控制节点 Agent 可见上下文。

---

## 4. 目标架构

### 4.1 契约分层

契约分为六类：

```text
GlobalTaskContract
  描述整体目标、最终产物、全局验收。

WorkflowContract
  描述单 Agent workflow 的 step、输入绑定、输出写回、停止条件。

NodeContract
  描述一个可执行节点的目标、输入、输出、验收和运行要求。

EdgeHandoffContract
  描述上游输出如何交给下游，使用什么 A2A message type，哪些字段可见。

RuntimeContract
  描述 Agent loop 运行时需要的能力、上下文、工具、记忆和投影要求。

AcceptanceContract
  描述结果如何验收，失败如何返回，是否需要人工 gate。
```

注意：这些契约不是都需要用户从零填写。系统应提供通用模板，具体任务只绑定和覆盖必要部分。

### 4.2 四个核心对象

#### ContractSpec

用户可编辑或任务配置可引用的契约定义。

建议字段：

```text
contract_id
title_zh
title_en
contract_kind
description
input_fields
output_fields
artifact_requirements
acceptance_rules
runtime_requirements
context_visibility_policy
allowed_agent_kinds
allowed_runtime_lanes
version
enabled
metadata
```

约束：

1. `contract_id` 使用稳定英文 ID。
2. 前端选择必须显示中文名称。
3. 所有契约必须有 `contract_kind`。
4. input/output 字段必须结构化，不能只放自然语言。

#### ContractManifest

运行前由编译器生成的不可变快照。

建议字段：

```text
manifest_id
source_task_ref
source_workflow_ref
source_topology_ref
compile_mode
global_contract
workflow_contract
node_contracts
edge_contracts
runtime_contracts
acceptance_contracts
compile_issues
compiled_at
```

约束：

1. Manifest 是运行依据，不直接手工编辑。
2. 每次运行绑定一个 manifest ref。
3. 监控和回放都引用 manifest，而不是重新读取可变 spec。

#### RuntimeAssembly

真正送入 Agent loop 的执行包。

单 Agent 结构：

```text
assembly_id
task_run_id
agent_id
agent_profile_id
runtime_lane
task_goal
workflow_step
input_bindings
allowed_operations
allowed_memory_scopes
visible_context_sections
projection_snapshot_ref
output_contract
acceptance_contract
loop_policy
```

多 Agent 节点结构：

```text
assembly_id
coordination_run_id
node_id
stage_id
agent_id
agent_profile_id
runtime_lane
node_goal
node_contract_ref
upstream_handoff_packets
explicit_inputs
artifact_refs
allowed_operations
visible_context_sections
a2a_payload
expected_outputs
acceptance_contract
failure_contract
```

约束：

1. Agent loop 消费 RuntimeAssembly。
2. Agent loop 不直接读取整个 topology state。
3. RuntimeAssembly 中必须有可审计的 context visibility。

#### ContractStatus

运行时状态。

建议字段：

```text
status_id
manifest_ref
task_run_id
coordination_run_id
node_statuses
edge_statuses
input_satisfaction
output_satisfaction
acceptance_results
handoff_packets
artifact_refs
blocked_reasons
runtime_issues
updated_at
```

约束：

1. ContractStatus 由 runtime 写入。
2. 前端监控读取 ContractStatus。
3. 用户编辑的 ContractSpec 不被运行时直接改写。

---

## 5. 单 Agent Runtime 组装

### 5.1 单 Agent workflow 是契约图

单 Agent 任务不再被视为“一个 prompt + 工具调用”，而是：

```text
TaskSpec
  -> WorkflowContract
  -> RuntimeAssembly
  -> AgentLoop
  -> ContractStatus
```

`TaskWorkflowBinding` 应升级为 workflow 契约图的配置来源。其 `steps` 不再只是展示步骤，而是编译输入。

### 5.2 单 Agent loop 接入点

当前接入点：

```text
TaskRunLoop.run_single_agent_stream()
RuntimeContextManager.prepare_model_context()
StageProjectionCycle
AgentRuntimeProfile
```

目标变化：

1. `TaskRunLoop` 在调用模型前先生成 `RuntimeAssembly`。
2. `RuntimeContextManager` 从 `RuntimeAssembly.visible_context_sections` 组装模型可见上下文。
3. projection 仍是上下文适配层，不成为契约硬绑定。
4. Agent 输出后生成 `AgentRunResult`，再由 acceptance contract 验收。

### 5.3 单 Agent 禁止事项

1. 禁止继续把契约散落在 prompt 文案里。
2. 禁止 workflow、projection、runtime profile 各自决定一部分执行规则而互不校验。
3. 禁止 output_contract_id 只是一个字符串，不可解析、不校验。

---

## 6. 多 Agent 契约、通信与协调 Loop

### 6.1 多 Agent topology 是契约图

协调任务运行路径：

```text
CoordinationTaskDefinition
  -> CoordinationGraphSpec
  -> ContractManifest
  -> ContractStatus
  -> NodeRuntimeAssembly
  -> A2A Handoff
  -> Node Agent Loop
  -> Result Envelope
  -> ContractStatus Update
  -> Next Ready Nodes
```

### 6.2 主 Agent 职责

主 Agent 是协调任务入口和出口：

1. 理解用户请求。
2. 选择或启动协调任务。
3. 生成 global task input。
4. 启动 coordination run。
5. 读取最终 result envelope。
6. 向用户汇总结果。

主 Agent 不做：

1. 不替代所有子 Agent 执行节点。
2. 不把多 Agent 路由写进自身 prompt。
3. 不持有所有子 Agent 内部上下文。

### 6.3 A2A 的位置

A2A 只负责通信对象：

```text
AgentCard
Message
Task
Part
Artifact
JSON-RPC transport
streaming
```

边契约负责业务语义：

```text
source_node
target_node
handoff_payload_schema
visible_fields
artifact_refs
required_ack
failure_route
acceptance_gate
```

二者关系：

```text
EdgeHandoffContract
  -> HandoffPacket
  -> A2A Message / Task
  -> target NodeRuntimeAssembly
```

### 6.4 协调 loop 状态

`CoordinationRuntimeState` 应从当前结构扩展为：

```text
contract_manifest
contract_status
node_contracts
edge_contracts
ready_nodes
blocked_nodes
running_nodes
completed_nodes
failed_nodes
handoff_packets
acceptance_results
stage_execution_request
a2a_payload
```

路由规则：

1. `ready_nodes` 由拓扑依赖和 input satisfaction 计算。
2. 节点执行前生成 `NodeRuntimeAssembly`。
3. 节点完成后 `_stage_accept()` 校验 output / acceptance。
4. 通过边契约生成 handoff packet。
5. 下游 required inputs 满足后进入 ready。
6. terminal node 或 final contract 满足后 complete。

第一阶段可以仍串行执行 ready nodes；后续再引入 LangGraph `Send` 并行 fan-out。

---

## 7. 上下文管理原则

多 Agent 上下文默认隔离。

上下文分四层：

```text
MainSessionContext
  主 Agent 与用户入口使用。

CoordinationRunState
  协调 runtime 的结构化事实来源。

NodeRuntimeContext
  某个节点 Agent 本次执行可见上下文。

HandoffContext
  节点间通过边契约传递的结构化交接上下文。
```

规则：

1. 子 Agent 默认不能看完整主会话 history。
2. 下游 Agent 默认不能看上游 Agent 的内部推理过程。
3. handoff 只传结构化摘要、字段、artifact refs、验证状态。
4. 主 Agent 默认只看进度摘要和最终 result envelope。
5. 需要共享记忆时必须由 contract visibility policy 和 agent profile 同时允许。

---

## 8. 后端实施阶段

### 阶段 1：契约主数据

新增文件：

```text
backend/tasks/contract_definition_models.py
backend/tasks/contract_registry.py
```

修改文件：

```text
backend/tasks/__init__.py
backend/api/tasks.py
frontend/src/lib/api.ts
```

工作：

1. 新增 `ContractSpec`、`ContractField`、`ContractAcceptanceRule`。
2. 新增 `TaskContractRegistry`。
3. `/tasks/overview` 输出 contract specs。
4. `TaskContractDescriptor` 降级为只读派生视图。
5. 清理旧具体契约残余，不恢复历史测试契约。

完成标准：

1. 契约可保存、读取、校验。
2. 所有契约有中文名称。
3. 前端可按中文选择契约。

### 阶段 2：契约编译器

新增文件：

```text
backend/orchestration/runtime_loop/contract_compiler_models.py
backend/orchestration/runtime_loop/contract_compiler.py
```

工作：

1. 编译 `ContractManifest`。
2. 编译 `NodeContract`、`EdgeHandoffContract`、`RuntimeContract`。
3. 校验 AgentRuntimeProfile 能力权限。
4. 校验 workflow step 输入输出。
5. 校验 topology 节点边输入输出。
6. 输出 compile issues。

完成标准：

1. 单 Agent workflow 能编译 manifest。
2. 多 Agent topology 能编译 manifest。
3. 权限不匹配、输入缺失、输出无法满足会在编译期报告。

### 阶段 3：RuntimeAssembly

新增文件：

```text
backend/orchestration/runtime_loop/runtime_assembly_models.py
backend/orchestration/runtime_loop/runtime_assembly_builder.py
```

修改文件：

```text
backend/orchestration/runtime_loop/task_run_loop.py
backend/orchestration/runtime_loop/context_manager.py
backend/orchestration/runtime_loop/stage_execution_request.py
```

工作：

1. 单 Agent loop 进入模型前生成 `RuntimeAssembly`。
2. `StageExecutionRequest` 扩展为可携带 `node_runtime_assembly_ref` 或 assembly payload。
3. `RuntimeContextManager` 支持从 assembly 构造模型上下文。
4. 保持普通单 Agent 会话兼容。

完成标准：

1. 普通单 Agent 任务仍可运行。
2. runtime trace 中可以看到本轮 assembly。
3. 模型可见上下文可审计。

### 阶段 4：协调 Runtime 改造

修改文件：

```text
backend/orchestration/runtime_loop/langgraph_coordination_runtime.py
backend/orchestration/runtime_loop/continuation_inputs.py
backend/orchestration/runtime_loop/coordination_trace_adapter.py
backend/orchestration/runtime_loop/a2a_stage_payload.py
```

工作：

1. `_bootstrap_state()` 写入 `contract_manifest`。
2. `_route_next()` 改为基于 ready nodes 和 contract satisfaction。
3. `_stage_prepare()` 基于 edge handoff contract 绑定输入。
4. `_stage_execute()` 生成 `NodeRuntimeAssembly` 和 A2A payload。
5. `_stage_accept()` 更新 ContractStatus。
6. 生成 handoff packets。

完成标准：

1. 非线性拓扑不再退化为 stage index。
2. 下游节点只在输入契约满足后运行。
3. A2A payload 与 edge handoff contract 可追踪。

### 阶段 5：前端编辑和监控

修改文件：

```text
frontend/src/components/workspace/views/TaskSystemView.tsx
frontend/src/components/workspace/views/task-system/CoordinationEditorWorkbench.tsx
frontend/src/lib/api.ts
frontend/src/app/globals.css
```

新增组件：

```text
frontend/src/components/workspace/views/task-system/ContractLibraryPanel.tsx
frontend/src/components/workspace/views/task-system/ContractOverviewPanel.tsx
frontend/src/components/workspace/views/task-system/TaskContractPanel.tsx
```

工作：

1. 任务管理中编辑具体任务契约。
2. 契约库管理通用 ContractSpec。
3. 契约总览按任务汇总，不作为复杂编辑入口。
4. 协调拓扑节点绑定 NodeContract。
5. 协调拓扑边绑定 EdgeHandoffContract。
6. 监控展示 ContractStatus。

完成标准：

1. 用户能在任务管理里填写任务契约。
2. 用户能在拓扑节点和边上绑定契约。
3. 保存前有编译预检。
4. 运行监控显示节点状态和契约满足度。

---

## 9. 数据迁移与兼容规则

1. 不恢复旧的具体任务契约。
2. 不恢复旧 `a2a-compatible.v1` 链路。
3. `TaskContractDescriptor` 只保留只读兼容展示。
4. `CoordinationStageContract` 暂时保留为迁移输入和兼容输出。
5. `input_contract_id` / `output_contract_id` 继续读取，但无效 ID 只产生 warning。
6. 新任务必须走 `ContractSpec -> ContractManifest -> RuntimeAssembly`。
7. A2A 只作为通信层，不作为业务契约存储层。

---

## 10. 验证计划

新增后端测试：

```text
backend/tests/task_contract_registry_test.py
backend/tests/contract_compiler_workflow_test.py
backend/tests/contract_compiler_coordination_test.py
backend/tests/runtime_assembly_builder_test.py
backend/tests/langgraph_contract_runtime_test.py
```

测试点：

1. 契约定义可保存读取。
2. 中文名称必填。
3. workflow 可编译 manifest。
4. topology 可编译 manifest。
5. required input 缺失时 blocked。
6. 上游 output 满足下游 input 后下游 ready。
7. AgentRuntimeProfile 不匹配时编译失败。
8. A2A handoff payload 与 edge contract 对齐。
9. 断点恢复后不重复执行已满足节点。

前端验证：

```powershell
cd frontend
npm run lint
npm run build
```

后端验证：

```powershell
$env:PYTHONPATH='backend'
pytest backend\tests\task_contract_registry_test.py backend\tests\contract_compiler_workflow_test.py backend\tests\contract_compiler_coordination_test.py backend\tests\runtime_assembly_builder_test.py backend\tests\langgraph_contract_runtime_test.py
```

---

## 11. 禁止事项

1. 禁止用 prompt 文案代替契约 schema。
2. 禁止在 `_route_next()` 中为具体任务写特殊分支。
3. 禁止让拓扑编辑器直接改运行中状态。
4. 禁止让投影和契约硬绑定。
5. 禁止让 A2A 承担业务契约职责。
6. 禁止把完整主会话 history 默认传给子 Agent。
7. 禁止只做前端展示，不改 runtime 编译链路。
8. 禁止为了测试通过伪造产物或绕过真实 runtime。

---

## 12. 最终目标

完成后，任务系统应成为一个标准化 Agent 任务搭建和运行环境：

1. 用户在任务系统里定义任务、workflow、topology 和契约。
2. 单 Agent 和多 Agent 共用一套 ContractCompiler。
3. Agent runtime 由 RuntimeAssembly 显式组装。
4. A2A 负责通信和 handoff 承载。
5. LangGraph coordination loop 根据契约满足度推进。
6. 子 Agent 只接收自己的节点执行包。
7. 监控界面实时展示拓扑、契约满足度、输出和产物。
8. 所有契约、能力、runtime lane 都有中文名称和稳定 ID。
