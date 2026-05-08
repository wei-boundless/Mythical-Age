# 契约标准化与 Agent Runtime 统一重构实施清单

日期：2026-05-08

关联设计书：`21-契约标准化与Agent-Runtime统一重构计划书-20260508.md`

目标：把契约系统、单 Agent runtime 组装、多 Agent topology、A2A handoff 和 LangGraph coordination loop 按统一模型落地。本文是执行清单，不替代设计书。

---

## 0. 总执行原则

1. 不恢复旧具体任务契约。
2. 不恢复旧 `a2a-compatible.v1` 链路。
3. A2A 只作为通信层，不承担业务契约职责。
4. ContractSpec 是用户编辑对象。
5. ContractManifest 是运行前编译快照。
6. RuntimeAssembly 是送入 Agent loop 的执行包。
7. ContractStatus 是 runtime 写入的运行状态。
8. 单 Agent workflow 和多 Agent topology 共用同一套契约编译原则。
9. 每一阶段必须有真实测试，不允许绕过 runtime。
10. 前端完整编辑器必须建立在后端模型和编译 API 稳定之后，避免先做假表单。

### 0.1 固定对象边界

```text
ContractSpec
  长期配置。用户和任务系统编辑，runtime 不直接改写。

ContractManifest
  编译快照。运行前生成，运行中只引用，不手工编辑。

RuntimeAssembly
  执行包。由 manifest、agent profile、context policy、projection 和当前输入组装而成。

ContractStatus
  运行状态。由 runtime 写入，供监控和恢复使用。

HandoffPacket
  业务交接包。由边契约生成，再由 A2A message/task 承载。
```

### 0.2 执行顺序优化

原始阶段中“前端契约库和任务契约入口”容易过早依赖未稳定的后端结构，因此实际推进时按以下门控执行：

```text
1. ContractSpec 主数据
2. ContractCompiler 最小骨架
3. RuntimeAssembly 模型与 builder
4. 前端契约库、任务契约入口、拓扑绑定
5. LangGraph coordination loop
6. 监控与可视化
```

阶段二期间前端只补类型和只读预览，不做完整编辑保存；完整编辑保存等阶段三接口稳定后再进入阶段四。

---

## A. 细化数据模型

本章是实施时的字段基线。后续代码实现可以按 Python dataclass / Pydantic / TypeScript type 分别落地，但字段语义不能漂移。

### A.1 ContractSpec

```text
contract_id: string
title_zh: string
title_en: string
contract_kind: enum
description: string
input_fields: ContractField[]
output_fields: ContractField[]
artifact_requirements: ArtifactRequirement[]
acceptance_rules: AcceptanceRule[]
runtime_requirements: RuntimeRequirement
context_visibility_policy: ContextVisibilityPolicy
handoff_policy: HandoffPolicy
failure_policy: FailurePolicy
human_gate_policy: HumanGatePolicy
allowed_agent_kinds: string[]
allowed_runtime_lanes: string[]
version: string
enabled: bool
metadata: object
```

`contract_kind` 固定枚举：

```text
global_task
workflow
workflow_step
node_execution
edge_handoff
runtime
acceptance
failure
human_gate
final_output
```

实现要求：

1. `contract_id` 保存稳定英文 ID。
2. `title_zh` 必填，用于前端选择。
3. `contract_kind` 不允许自由字符串。
4. `metadata` 只放扩展信息，不能放核心执行规则。
5. 业务输入输出必须进入 `input_fields` / `output_fields`，不能只写在 `description`。

### A.2 ContractField

```text
field_id: string
title_zh: string
field_type: enum
required: bool
description: string
default_value: any
schema: object
source_hint: enum
visibility: enum
```

`field_type` 固定枚举：

```text
string
number
boolean
object
array
artifact_ref
result_ref
agent_ref
task_ref
contract_ref
```

`source_hint` 固定枚举：

```text
user_input
upstream_output
runtime_context
artifact
system
manual_review
```

`visibility` 固定枚举：

```text
model_visible
runtime_only
human_only
monitor_visible
```

实现要求：

1. 同一个 ContractSpec 内 `field_id` 唯一。
2. `required=true` 的字段必须能在编译期追踪来源。
3. `runtime_only` 字段不能进入模型可见 prompt。
4. `artifact_ref` 和 `result_ref` 必须保存 ref，不直接塞完整内容。

### A.3 AcceptanceRule

```text
rule_id: string
title_zh: string
rule_type: enum
severity: enum
target_field: string
criteria: string
config: object
```

`rule_type` 固定枚举：

```text
required_field_present
artifact_exists
schema_match
quality_review
model_judge
human_review
custom_runtime_check
```

`severity` 固定枚举：

```text
error
warning
info
```

实现要求：

1. `required_field_present`、`artifact_exists`、`schema_match` 必须可机器校验。
2. `model_judge` 只能作为辅助验收，不能替代硬性字段校验。
3. `human_review` 必须生成 human gate 状态。

### A.4 ContextVisibilityPolicy

```text
main_session_history: enum
upstream_outputs: enum
sibling_nodes: enum
artifact_access: enum
memory_scopes: string[]
model_visible_sections: string[]
hidden_sections: string[]
```

默认值：

```text
main_session_history = summary
upstream_outputs = summary
sibling_nodes = status_only
artifact_access = refs_only
```

固定枚举：

```text
main_session_history: none | summary | full
upstream_outputs: refs_only | summary | full
sibling_nodes: none | status_only | summary
artifact_access: refs_only | explicit_read | full
```

实现要求：

1. 多 Agent 节点默认不接收完整主会话 history。
2. 下游节点默认不接收上游完整内部过程。
3. `full` 级别可见性必须同时被 contract 和 agent profile 允许。
4. 监控可见不等于模型可见。

### A.5 RuntimeAssembly

单 Agent 执行包：

```text
assembly_id
assembly_kind = single_agent
task_run_id
agent_id
agent_profile_id
runtime_lane
manifest_ref
contract_refs
task_goal
workflow_ref
workflow_step
explicit_inputs
input_bindings
allowed_operations
allowed_memory_scopes
visible_context_sections
projection_snapshot_ref
output_contract
acceptance_contract
loop_policy
diagnostics
```

多 Agent 节点执行包：

```text
assembly_id
assembly_kind = coordination_node
coordination_run_id
root_task_run_id
node_id
stage_id
agent_id
agent_profile_id
runtime_lane
manifest_ref
node_contract_ref
edge_contract_refs
node_goal
explicit_inputs
upstream_handoff_packets
artifact_refs
allowed_operations
allowed_memory_scopes
visible_context_sections
projection_snapshot_ref
a2a_payload
expected_outputs
acceptance_contract
failure_contract
loop_policy
diagnostics
```

实现要求：

1. `RuntimeAssembly` 由系统生成，不由用户直接编辑。
2. `visible_context_sections` 是模型可见上下文的唯一入口之一。
3. `allowed_operations` 必须来自 AgentRuntimeProfile 与契约要求的交集。
4. 节点 assembly 不允许直接携带完整 coordination state。
5. `a2a_payload` 是通信承载，不能作为业务规则唯一来源。

### A.6 HandoffPacket

```text
handoff_id
source_node_id
target_node_id
edge_contract_ref
message_type
payload
artifact_refs
result_refs
output_satisfaction
visibility
status
diagnostics
```

`message_type` 固定使用官方 A2A 类型：

```text
message/send
message/stream
task/status
task/artifact
```

`status` 固定枚举：

```text
pending
sent
accepted
rejected
failed
```

`visibility` 建议字段：

```text
expose_summary: bool
expose_artifacts: bool
expose_raw_output: bool
```

实现要求：

1. HandoffPacket 由 EdgeHandoffContract 编译和运行时结果共同生成。
2. HandoffPacket 可以被 A2A message/task 承载。
3. 下游 NodeRuntimeAssembly 从 HandoffPacket 提取输入。
4. 不允许直接传递上游完整模型消息列表。

---

## 1. 阶段一：契约主数据

### 1.1 新增文件

```text
backend/tasks/contract_definition_models.py
backend/tasks/contract_registry.py
backend/tests/task_contract_registry_test.py
```

### 1.2 修改文件

```text
backend/tasks/__init__.py
backend/api/tasks.py
frontend/src/lib/api.ts
```

### 1.3 后端模型

新增：

```text
ContractSpec
ContractField
ArtifactRequirement
AcceptanceRule
RuntimeRequirement
ContextVisibilityPolicy
HandoffPolicy
FailurePolicy
HumanGatePolicy
```

### 1.4 ContractSpec 必备字段

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

### 1.5 Registry 行为

1. 加载内置通用契约。
2. 加载用户保存的契约。
3. 按 `contract_id` upsert。
4. 校验中文名称。
5. 校验字段 ID 唯一。
6. 校验 `contract_kind` 合法。
7. 输出前端中文选择列表。

### 1.6 API 输出

`/tasks/overview` 增加：

```text
contract_management.contract_specs
contract_management.contract_kind_options
contract_management.validation_issues
```

### 1.7 完成标准

1. 后端测试覆盖保存、读取、校验。
2. contract spec 里没有旧具体任务残余。
3. 前端类型能识别 contract specs。
4. `TaskContractDescriptor` 仍可只读展示，但不作为主数据。

### 1.8 当前实施状态

状态：已完成。

已落地：

1. 新增 `backend/tasks/contract_definition_models.py`，定义 `ContractSpec`、字段、产物要求、验收规则、runtime 要求、上下文可见性、handoff、失败和人工门控策略。
2. 新增 `backend/tasks/contract_registry.py`，提供通用默认契约、用户契约存储、upsert、delete、全量校验和 catalog 输出。
3. `/tasks/overview` 已增加 `contract_management`，并在 summary 暴露 `contract_spec_count` 与 `contract_spec_validation_issue_count`。
4. 新增 `/tasks/contracts/{contract_id}` 的保存和删除接口。
5. `frontend/src/lib/api.ts` 已补齐 ContractSpec 相关类型和 API 方法。
6. 旧回归测试中要求恢复具体写作任务、长篇小说 agent 组的断言已清理，测试基线改为“空任务基线 + 通用契约主数据”。

验证：

```text
$env:PYTHONPATH='backend'; pytest backend\tests\task_contract_registry_test.py backend\tests\task_system_api_regression.py
npx tsc --noEmit
```

---

## 2. 阶段二：ContractCompiler 最小骨架

### 2.1 新增文件

```text
backend/orchestration/runtime_loop/contract_compiler_models.py
backend/orchestration/runtime_loop/contract_compiler.py
backend/tests/contract_compiler_workflow_test.py
backend/tests/contract_compiler_coordination_test.py
```

### 2.2 修改文件

```text
backend/orchestration/runtime_loop/langgraph_coordination_runtime.py
backend/orchestration/runtime_loop/continuation_policy.py
backend/tasks/flow_registry.py
```

### 2.3 编译模型

新增：

```text
ContractManifest
CompiledGlobalContract
CompiledWorkflowContract
CompiledNodeContract
CompiledEdgeHandoffContract
CompiledRuntimeContract
CompiledAcceptanceContract
ContractCompileIssue
```

### 2.4 输入来源

```text
ContractSpec registry
SpecificTaskRecord
TaskWorkflowBinding
CoordinationTaskDefinition
CoordinationGraphSpec
TopologyTemplate
TaskCommunicationProtocol
AgentRuntimeProfile
```

### 2.5 编译规则

1. 单 Agent workflow 编译为单主体契约图。
2. 多 Agent topology 编译为多主体契约图。
3. workflow step 生成 compiled node contract。
4. topology node 生成 compiled node contract。
5. topology edge 生成 compiled handoff contract。
6. AgentRuntimeProfile 校验 allowed operations、runtime lane、memory scope。
7. 输入输出字段必须能映射，否则生成 error。
8. A2A message type 来自 edge handoff contract 或官方默认类型。
9. 第一版只输出 manifest 和 issues，不改 runtime 执行路径。

### 2.6 完成标准

1. workflow fixture 可编译 manifest。
2. coordination fixture 可编译 manifest。
3. 缺输入、缺契约、权限不匹配均有结构化 issue。
4. manifest 中能定位每个节点和边的契约来源。
5. 当前 LangGraph runtime 仍可继续使用原 `CoordinationStageContract` 兼容路径。

### 2.7 当前实施状态

状态：已完成最小骨架。

已落地：

1. 新增 `backend/orchestration/runtime_loop/contract_compiler_models.py`，定义 `ContractManifest`、workflow/node/edge/runtime/acceptance 编译结果和 `ContractCompileIssue`。
2. 新增 `backend/orchestration/runtime_loop/contract_compiler.py`，支持单 Agent workflow manifest 与协调 topology manifest 编译。
3. 新增 `/tasks/contract-manifests/workflows/{workflow_id}` 与 `/tasks/contract-manifests/coordination/{coordination_task_id}` 预览接口。
4. `frontend/src/lib/api.ts` 已补齐 `ContractManifest`、`ContractCompileIssue` 和 manifest 编译预览 API。
5. 新增 workflow 与 coordination 编译器测试，覆盖有效 manifest、缺契约、runtime task mode/lane/output contract 不匹配、缺 edge handoff 契约。

边界说明：

1. 本阶段未修改 `langgraph_coordination_runtime.py` 的推进逻辑。
2. 本阶段未让 runtime 消费 manifest，只输出预览对象和结构化 issues。
3. `CoordinationStageContract` 兼容路径仍保留给现有协调执行链路。

验证：

```text
$env:PYTHONPATH='backend'; pytest backend\tests\task_contract_registry_test.py backend\tests\contract_compiler_workflow_test.py backend\tests\contract_compiler_coordination_test.py backend\tests\task_system_api_regression.py
npx tsc --noEmit
```

---

## 3. 阶段三：RuntimeAssembly

### 3.1 新增文件

```text
backend/orchestration/runtime_loop/runtime_assembly_models.py
backend/orchestration/runtime_loop/runtime_assembly_builder.py
backend/tests/runtime_assembly_builder_test.py
```

### 3.2 修改文件

```text
backend/orchestration/runtime_loop/task_run_loop.py
backend/orchestration/runtime_loop/context_manager.py
backend/orchestration/runtime_loop/stage_execution_request.py
backend/orchestration/runtime_loop/stage_projection.py
```

### 3.3 新增模型

```text
SingleAgentRuntimeAssembly
NodeRuntimeAssembly
RuntimeContextSection
RuntimeOutputContract
RuntimeAcceptanceContract
RuntimeFailureContract
RuntimeLoopPolicy
HandoffPacket
```

### 3.4 单 Agent 装配流程

```text
task_operation
  -> ContractManifest
  -> SingleAgentRuntimeAssembly
  -> RuntimeContextManager
  -> model messages
  -> agent loop
  -> acceptance
```

### 3.5 多 Agent 节点装配流程

```text
ContractManifest + ContractStatus + active node
  -> NodeRuntimeAssembly
  -> A2A payload
  -> existing agent loop continuation
  -> result envelope
  -> ContractStatus update
```

### 3.6 接入策略

1. 第一版 builder 可以只生成 assembly，不立刻改变模型 prompt。
2. `TaskRunLoop` 先把 assembly 写入 trace diagnostics。
3. `RuntimeContextManager` 在第二步支持从 assembly 读取 `visible_context_sections`。
4. 节点 assembly 暂时通过 `StageExecutionRequest` 的扩展字段进入 continuation。
5. 普通单 Agent 会话仍走原路径，直到 assembly 校验稳定。

### 3.7 完成标准

1. 普通单 Agent 任务仍可跑通。
2. runtime trace 中可看到 assembly ref。
3. `RuntimeContextManager` 能从 assembly 控制模型可见上下文。
4. 节点 assembly 默认不包含完整主会话 history。
5. A2A payload 与 NodeRuntimeAssembly 可互相追踪。

### 3.8 当前实施状态

状态：已完成第一版 builder 与只读接入。

已落地：

1. 新增 `backend/orchestration/runtime_loop/runtime_assembly_models.py`，定义 `SingleAgentRuntimeAssembly`、`NodeRuntimeAssembly`、`RuntimeContextSection`、输出/验收/失败契约、loop policy 与 `HandoffPacket`。
2. 新增 `backend/orchestration/runtime_loop/runtime_assembly_builder.py`，支持从 `ContractManifest` 生成单 Agent assembly 和节点 assembly。
3. 新增 `/tasks/runtime-assemblies/workflows/{workflow_id}` 与 `/tasks/runtime-assemblies/coordination/{coordination_task_id}/nodes/{node_id}` 预览接口。
4. `StageExecutionRequest` 已能携带 `runtime_assembly`。
5. `RuntimeContextManager` 已支持根据 assembly 的 `context_sections` 控制模型可见历史；节点 assembly 默认不含完整主会话历史。
6. `TaskRunLoop.start` 已把 `runtime_assembly_ref` 与 `contract_manifest_ref` 写入 started event、loop state 和 task run diagnostics。
7. `frontend/src/lib/api.ts` 已补齐 `RuntimeAssembly` 类型和 assembly 预览 API。

边界说明：

1. 本阶段未把 assembly 全量接管模型 prompt，只增加可见性控制与诊断追踪。
2. 本阶段未改变协调 runtime 的推进顺序。
3. 节点 handoff packet 保留 A2A trace，但业务契约仍来自 manifest/assembly。

验证：

```text
$env:PYTHONPATH='backend'; pytest backend\tests\task_contract_registry_test.py backend\tests\contract_compiler_workflow_test.py backend\tests\contract_compiler_coordination_test.py backend\tests\runtime_assembly_builder_test.py backend\tests\task_system_api_regression.py
npx tsc --noEmit
```

---

## 4. 阶段四：前端契约库和任务契约入口

### 4.1 新增文件

```text
frontend/src/components/workspace/views/task-system/ContractLibraryPanel.tsx
frontend/src/components/workspace/views/task-system/ContractOverviewPanel.tsx
frontend/src/components/workspace/views/task-system/TaskContractPanel.tsx
```

### 4.2 修改文件

```text
frontend/src/components/workspace/views/TaskSystemView.tsx
frontend/src/components/workspace/views/task-system/CoordinationEditorWorkbench.tsx
frontend/src/lib/api.ts
frontend/src/app/globals.css
```

### 4.3 页面层级

任务系统层级调整为：

```text
domain
assembly
coordination
contract_overview
contract_library
```

### 4.4 编辑职责

```text
domain
  编辑具体任务默认契约。

coordination
  绑定节点契约和边契约，允许显式覆盖。

contract_overview
  按任务汇总、预检、跳转，不做复杂编辑。

contract_library
  编辑通用 ContractSpec。
```

### 4.5 表单要求

```text
ContractSpec 表单
  基础信息、输入字段、输出字段、验收规则、上下文可见性、runtime 要求。

TaskContractPanel
  任务默认输入、输出、验收、runtime、workflow 契约绑定。

Coordination node inspector
  节点 task、agent、node contract、runtime lane、override 标记。

Coordination edge inspector
  source、target、handoff contract、A2A message type、visibility policy。
```

### 4.6 完成标准

1. 契约库可新建、编辑、删除 ContractSpec。
2. 具体任务详情可绑定输入、输出、验收、runtime 契约。
3. 协调节点可选择 NodeContract。
4. 协调边可选择 EdgeHandoffContract。
5. 保存前可显示编译预检结果。
6. 按钮和页面切换符合现有任务系统层级，不混页。

### 4.7 当前实施状态

状态：已完成第一版前端契约入口与拓扑契约绑定。

已落地：

1. 任务系统层级已从 `contracts` 拆为 `contract_overview` 与 `contract_library`。
2. 新增 `ContractLibraryPanel`，支持新建、编辑、删除 `ContractSpec`，并以中文名称作为选择主显示。
3. 新增 `ContractOverviewPanel`，支持按当前单任务生成 workflow manifest、single-agent runtime assembly，并支持按当前协调任务生成 coordination manifest、选中节点 runtime assembly。
4. 新增 `TaskContractPanel`，把具体任务的默认输入契约、默认输出契约、workflow 输出契约集中成任务契约入口。
5. 协调任务节点检查器已支持绑定节点契约和 runtime lane。
6. 协调任务边检查器已支持绑定 edge handoff 契约，并继续保持 A2A 只作为通信层预览。
7. 后端 `contract_compiler` 已识别节点 `node_contract_id` / `contract_refs` 覆盖，并将其编入 `CompiledNodeContract.contract_refs`。

边界说明：

1. `ContractSpec` 的字段、验收、上下文策略第一版使用 JSON 编辑区，后续可继续细化为结构化字段编辑器。
2. 前端已提供 manifest / assembly 预览入口，但阶段四不改变协调 runtime 推进逻辑。
3. 节点契约覆盖已进入 manifest；真正参与多 Agent loop 的状态推进仍留到阶段五。

验证：

```text
$env:PYTHONPATH='backend'; python -m compileall backend\orchestration\runtime_loop backend\tasks backend\api\tasks.py
$env:PYTHONPATH='backend'; pytest backend\tests\task_contract_registry_test.py backend\tests\contract_compiler_workflow_test.py backend\tests\contract_compiler_coordination_test.py backend\tests\runtime_assembly_builder_test.py backend\tests\task_system_api_regression.py
npx tsc --noEmit
```

---

## 5. 阶段五：LangGraph 协调 Loop

### 5.1 修改文件

```text
backend/orchestration/runtime_loop/langgraph_coordination_runtime.py
backend/orchestration/runtime_loop/continuation_inputs.py
backend/orchestration/runtime_loop/coordination_trace_adapter.py
backend/orchestration/runtime_loop/a2a_stage_payload.py
backend/orchestration/runtime_loop/stage_execution_request.py
```

### 5.2 Runtime State 扩展

新增 state 字段：

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
```

### 5.3 路由改造

1. `_bootstrap_state()` 编译 manifest。
2. `_stage_accept()` 写 ContractStatus。
3. `_route_next()` 基于 ready nodes，而不是 `stage_order + index`。
4. `_stage_prepare()` 根据 edge handoff contract 绑定输入。
5. `_stage_execute()` 生成 NodeRuntimeAssembly 和 A2A payload。
6. `_blocked()` 输出缺失字段和 contract issue。
7. `_complete()` 校验 final output contract。

### 5.4 完成标准

1. A -> B 单链路跑通。
2. A -> B/C -> D 汇聚 fixture 跑通。
3. 缺 required input 时 blocked。
4. 汇聚节点等待所有 required upstream。
5. 已 satisfied 节点恢复后不重复执行。
6. 失败节点按 failure policy 进入 retry、blocked 或 failed。

### 5.5 当前实施状态

状态：已完成第一版 ContractManifest / RuntimeAssembly 接入 LangGraph 协调 loop。

已落地：

1. `CoordinationRuntimeState` 已扩展 `contract_manifest`、`contract_status`、`node_contracts`、`edge_contracts`、`ready_nodes`、`blocked_nodes`、`running_nodes`、`completed_nodes`、`failed_nodes`、`handoff_packets`、`acceptance_results`。
2. `_bootstrap_state()` 已编译 `ContractManifest`，并把 node / edge contract 索引写入 runtime state。
3. `_route_next()` 已从线性 `stage_order + index` 改为基于拓扑边的 ready / blocked 计算；汇聚节点会等待所有上游完成。
4. `_stage_accept()` 已写入 `contract_status.node_status` 与 `acceptance_results`；失败结果会按 stage retry policy 重试或进入 failed 终态。
5. `_stage_prepare()` 在缺少必需输入时写入 blocked 状态和 contract status。
6. `_stage_execute()` 已为当前节点生成 `NodeRuntimeAssembly`，并随 `StageExecutionRequest.runtime_assembly` 进入后续 Agent loop。
7. A2A payload 已携带 `runtime_assembly_ref`、`contract_manifest_ref` 和 handoff packets，但 A2A 仍只作为通信承载，不承担业务契约定义。
8. `CoordinationTraceAdapter` 已把 manifest ref、contract status、ready/blocked/running/completed/failed 节点集合写入运行诊断。

边界说明：

1. 旧 `stage_contracts` 仍作为输入绑定的过渡来源；业务契约来源已经转为 `ContractManifest` / `RuntimeAssembly`。
2. 第一版 failure policy 已支持 stage 级 `retry_once` / `retry_limit`；更细的 contract `failure_policy`、`human_gate_policy` 仍需在后续运行状态里继续展开。
3. 本阶段先保证 topology route、assembly 注入、handoff trace 和 blocked 可观测；复杂并发执行仍按一次返回一个 `StageExecutionRequest` 推进。

验证：

```text
$env:PYTHONPATH='backend'; pytest backend\tests\task_contract_registry_test.py backend\tests\contract_compiler_workflow_test.py backend\tests\contract_compiler_coordination_test.py backend\tests\runtime_assembly_builder_test.py backend\tests\langgraph_coordination_runtime_regression.py backend\tests\task_system_api_regression.py
$env:PYTHONPATH='backend'; python -m compileall backend\tasks backend\orchestration\runtime_loop backend\api\tasks.py
npx tsc --noEmit
```

---

## 6. 阶段六：监控与可视化

### 6.1 修改文件

```text
frontend/src/components/workspace/views/OrchestrationView.tsx
frontend/src/components/workspace/views/task-system/CoordinationEditorWorkbench.tsx
frontend/src/lib/api.ts
frontend/src/app/globals.css
backend/api/tasks.py
```

### 6.2 监控内容

```text
topology graph
node status
contract satisfaction
missing inputs
latest handoff packet
artifact refs
acceptance result
a2a message preview
```

### 6.3 完成标准

1. 运行监控拓扑与任务系统拓扑一致。
2. 节点可显示 ready、running、blocked、completed、failed、human_gate。
3. 点击节点可看契约摘要和缺失输入。
4. 点击边可看 handoff packet 和 A2A payload。
5. 复杂拓扑节点尺寸不挤占画布。

### 6.4 当前实施状态

状态：已完成第一版运行监控可视化。

已落地：

1. `CoordinationTraceAdapter` 已在 `coordination_flow_*` 事件中直接输出 `langgraph_runtime_state`，包含 manifest ref、contract status、ready/blocked/running/completed/failed 节点集合和最近 handoff packets。
2. `CoordinationRunPanel` 已从运行事件提取 `ContractStatus`，并将 ready、blocked、running、completed、failed 合并进拓扑节点状态。
3. 协调监控面板新增“契约运行状态”，显示 manifest、节点集合计数、节点契约 refs、缺失 required inputs 和 manifest issues。
4. 协调监控面板新增“A2A Handoff”预览，显示最近 handoff packet 的 source/target、message type、契约 refs 与 runtime/manifest ref。
5. 拓扑节点点击后可切换节点契约摘要；拓扑边点击后可筛选对应 source/target 的 handoff packet。
6. `CoordinationTopologyGraph` 已支持 `ready`、`blocked`、`waiting/human_gate`、`satisfied` 等运行状态映射。
7. `globals.css` 已补齐对应视觉样式，并在移动端保持契约监控卡片单列布局。

边界说明：

1. 本阶段先在现有聊天协调监控面板中展示运行态，不把监控入口搬到编排系统页，避免页面层级混乱。
2. 节点/边点击当前先联动运行卡片；更完整的 inspector 级展开仍可在后续阶段细化。
3. A2A 仍只作为通信承载，前端展示的是 handoff packet 的运行摘要，不把 A2A payload 当作业务契约源。

验证：

```text
$env:PYTHONPATH='backend'; pytest backend\tests\langgraph_coordination_runtime_regression.py backend\tests\runtime_assembly_builder_test.py
$env:PYTHONPATH='backend'; python -m compileall backend\orchestration\runtime_loop
cd frontend; npx tsc --noEmit
cd frontend; npm run build
```

---

## 7. 阶段七：失败策略、人工门控与验收状态闭环

### 7.1 修改文件

```text
backend/orchestration/runtime_loop/langgraph_coordination_runtime.py
backend/orchestration/runtime_loop/coordination_trace_adapter.py
backend/tests/langgraph_coordination_runtime_regression.py
frontend/src/components/chat/CoordinationRunPanel.tsx
frontend/src/app/globals.css
```

### 7.2 Runtime 语义

```text
accepted=true
  -> ContractStatus.node_status = satisfied
  -> node_statuses = completed
  -> route_next

accepted=false + retry policy remaining
  -> ContractStatus.node_status = pending_retry
  -> node_statuses = pending
  -> route_next 指回原节点

accepted=false + human gate policy
  -> ContractStatus.node_status = human_gate
  -> node_statuses = waiting_for_human
  -> terminal_status = waiting_for_human
  -> resume_human_gate 决定 approve / retry / reject

accepted=false + fail closed
  -> ContractStatus.node_status = failed
  -> node_statuses = failed
  -> terminal_status = failed
```

### 7.3 完成标准

1. 失败节点按策略进入 retry、human_gate 或 failed。
2. human_gate 状态可写入 checkpoint、trace diagnostics 和 ContractStatus。
3. resume_human_gate 支持 approve、retry、reject 三类决策。
4. 前端监控可显示 human_gate/pending_retry/failed 的契约节点状态。
5. 测试覆盖 retry、human_gate approve、human_gate retry、human_gate reject。

### 7.4 当前实施状态

状态：已完成第一版失败策略、人工门控与验收状态闭环。

已落地：

1. `LangGraphCoordinationRuntime._stage_accept()` 已将 `accepted=false` 分流为 retry、human_gate 或 failed。
2. retry 分支会写入 `ContractStatus.node_status = pending_retry`，并通过 `retry_stage_id` 指回原节点重新执行。
3. human gate 分支会写入 `node_statuses = waiting_for_human`、`terminal_status = waiting_for_human`、`ContractStatus.node_status = human_gate` 和 checkpoint 中的 `human_gate` 对象。
4. `resume_human_gate()` 已支持 `approve`、`retry`、`reject` 三类决策：批准后继续下游，重试后回到原节点，拒绝后 fail closed。
5. `CoordinationTraceAdapter` 已输出 `waiting_nodes` 与 `human_gate`，供前端监控读取。
6. 前端协调监控已显示 `waiting_nodes` 计数，并支持 `human_gate`、`pending_retry` 的节点契约状态样式。
7. `langgraph_coordination_runtime_regression.py` 已覆盖 retry、human_gate waiting、approve、retry、reject。

边界说明：

1. 第一版 human gate 先以 runtime resume API 为准，尚未做完整人工审批表单。
2. ContractSpec 中更细的 `human_gate_policy` 和 `failure_policy` 后续可继续编译进节点 contract；本阶段先把 runtime 状态闭环打通。
3. human gate 批准目前视为该节点验收通过；如果后续要支持“人工补产物”，需要在 resume payload 中补充 artifact/result 写入规则。

验证：

```text
$env:PYTHONPATH='backend'; pytest backend\tests\task_contract_registry_test.py backend\tests\contract_compiler_workflow_test.py backend\tests\contract_compiler_coordination_test.py backend\tests\runtime_assembly_builder_test.py backend\tests\langgraph_coordination_runtime_regression.py backend\tests\task_system_api_regression.py
$env:PYTHONPATH='backend'; python -m compileall backend\tasks backend\orchestration\runtime_loop backend\api\tasks.py
cd frontend; npx tsc --noEmit
cd frontend; npm run build
```

---

## 8. 分阶段验证命令

### 后端基础

```powershell
$env:PYTHONPATH='backend'
pytest backend\tests\task_contract_registry_test.py
pytest backend\tests\contract_compiler_workflow_test.py backend\tests\contract_compiler_coordination_test.py
pytest backend\tests\runtime_assembly_builder_test.py
pytest backend\tests\langgraph_contract_runtime_test.py
```

### 后端编译

```powershell
python -m compileall backend\tasks backend\orchestration\runtime_loop backend\agents backend\api
```

### 前端

```powershell
cd frontend
npm run lint
npm run build
```

---

## 9. 禁止清单

1. 禁止只添加字段、不接 runtime。
2. 禁止让 `ContractSpec` 直接混入运行状态。
3. 禁止让 runtime 修改用户编辑的契约定义。
4. 禁止把 A2A payload 当作业务契约存储。
5. 禁止子 Agent 默认读取完整主会话 history。
6. 禁止为某个具体任务在 loop 中写特殊分支。
7. 禁止新旧契约体系长期并行。
8. 禁止前端把不同层级页面混在一个视图里。

---

## 10. 建议执行顺序

```text
1. ContractSpec 主数据
2. ContractCompiler 最小骨架
3. RuntimeAssembly 模型与 builder
4. 前端契约库、任务契约入口、拓扑绑定
5. LangGraph coordination loop
6. 监控与可视化
7. 失败策略、人工门控与验收状态闭环
```

每阶段完成后再进入下一阶段。阶段五之前不改协调 runtime 的推进逻辑；阶段三只让 `RuntimeContextManager` 支持 assembly 可见上下文，不在此阶段启用复杂多 Agent 上下文模式。
