# Runtime Assembly Workbench 设计书（2026-05-24）

## 1. 背景与问题定义

当前任务图编排系统已经具备运行装配能力，但这种能力主要存在于后端编译结果中，前端只暴露了部分字段编辑和发布执行包诊断。

这导致用户在编排一个节点时，很难直接回答以下问题：

- 当前节点最终由哪个 Agent 或执行器运行。
- 它采用哪个 runtime profile、runtime lane、projection 和 role prompt。
- 它真正可见的上下文有哪些，哪些被 profile 或 policy 隐藏。
- 它真正允许调用哪些 operation / tool，哪些被 deny 或 search policy 拦截。
- 它输出到哪个 boundary，如何提交为图节点结果、人工结果、子任务结果或普通回答。
- 当前配置来自 graph/node/contract_bindings/profile/template 中的哪一层。

因此，本次重构的核心不是“给搜索做一个配置页”，也不是“把 contract_bindings 表单做得更大”，而是把 runtime assembly 变成前端编排系统中的一级管理对象。

正确终态是：

```text
任务图节点
  -> 装配意图 Assembly Intent
  -> 后端编译 Effective Assembly
  -> 前端展示 Diff / Issues / Runtime Preview
  -> 发布执行包
```

## 2. 现有事实源

### 2.1 后端装配链路

后端已经有三层装配链路：

1. 任务入口装配：`TaskExecutionAssembly`
   - 文件：`backend/task_system/services/assembly_builder.py`
   - 职责：决定用户任务进入 single agent、coordination graph、task graph、projection、operation requirement 的哪条链路。

2. 任务图节点装配：`NodeRuntimeAssembly`
   - 文件：`backend/runtime/contracts/runtime_assembly_builder.py`
   - 职责：把 TaskGraph 节点编译为节点级运行装配，包括 agent、projection、context sections、handoff packets、loop policy、contract_bindings。

3. 运行工作单装配：`AgentAssemblyContract`
   - 文件：`backend/runtime/agent_assembly/assembler.py`
   - 职责：把 `WorkOrder` 装配为 prompt、capability、memory、output boundary、execution contract，再生成 permit。

### 2.2 前端现有入口

前端已经有可承载 Runtime Assembly Workbench 的基础页面：

- `frontend/src/components/workspace/views/task-system/TaskGraphWorkbench.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphModuleCompositionPage.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphComposableEditorPage.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphObjectInspector.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphNodeUnitInspector.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphContractBindingInspector.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphExecutionPackagePanel.tsx`

这些页面目前承担了 topology、module、contract、execution package 的显示与编辑，但缺少一个面向“运行装配”的明确工作区。

### 2.3 已有相关计划

`frontend/src/components/workspace/views/orchestration/AGENT_ASSEMBLY_REFACTOR_PLAN.md` 处理的是 Orchestration 里的 Agent 配置页：

- Agent 本体。
- Agent RuntimeProfile。
- Agent Group。
- 模型、权限、上下文、协作资格。

本设计书处理的是 TaskGraph 编排页里的节点装配：

- 节点选择哪个 Agent。
- 节点如何覆盖 runtime 行为。
- 节点的 effective assembly 是什么。
- 节点在图中的上下文、输入、输出、能力和交接如何被编译。

二者边界必须保持清楚：

```text
Orchestration Agent Assembly
  管理 Agent 作为可复用执行者的默认能力。

TaskGraph Runtime Assembly
  管理某个图节点如何使用执行者完成当前节点职责。
```

## 3. 目标

### 3.1 产品目标

将任务图编排系统升级为“节点级 Runtime Assembly Workbench”，让用户可以用可视化方式管理节点运行装配，并在发布前看到后端编译后的真实有效配置。

### 3.2 工程目标

- 不绕开现有 `TaskGraph -> ContractManifest -> NodeRuntimeAssembly -> WorkOrder -> AgentAssemblyContract -> ExecutionPermit` 链路。
- 不新增第二套运行图编辑器。
- 不把底层 JSON 表单继续扩大成主要交互。
- 不在前端自行推断最终权限，最终有效配置必须来自后端编译。
- 保留 `contract_bindings` 作为权威配置载体，但在 UI 上提供更高层的装配控件。

### 3.3 用户可见目标

用户选择一个节点后，可以直接看到：

- 执行身份：Executor / Agent / Profile / Runtime Lane。
- 角色装配：Projection / Role Prompt / Prompt Source。
- 能力装配：Operations / Tools / Delegate / Deny。
- 上下文装配：Task、Projection、Runtime Contracts、Memory、Artifacts、Upstream Outputs。
- 输出装配：Output Contract、Output Boundary、Persist Policy、Finalization Policy。
- 循环策略：Loop Mode、Max Turns、Length Budget、Acceptance、Human Gate。
- 差异解释：默认值、节点覆盖、profile 拦截、编译问题。

## 4. 核心设计原则

1. 后端编译结果是最终事实源。
2. 前端编辑的是装配意图，不伪造 effective assembly。
3. 节点装配和 Agent 本体配置分离。
4. 常用装配走结构化控件，高级配置才进入 JSON / contract bindings。
5. 不同层级分页面，不把 topology、runtime、contract、publish 全塞进一个面板。
6. Runtime Assembly Workbench 必须支持模板化：Search Agent、Verifier、Writer、Reviewer、Human Gate、Graph Module 都是模板。
7. 设计以成熟 agent runtime 为标准：权限、上下文、输出边界、状态循环都必须显式化。

## 5. 目标信息架构

任务图工作台保留现有大层级，但调整 Modules / Runtime 的职责：

```text
TaskGraphWorkbench
  Topology
    节点和边的结构关系
  Blueprint
    图目标、任务范围、发布状态
  Modules
    图模块、接口、端口、可组合结构
  Runtime Assembly
    节点运行装配、effective assembly、权限、上下文、输出边界
  Responsibility
    节点职责、projection、prompt 语义
  Timeline
    生命周期、阶段、等待与汇合
  Memory & Artifacts
    记忆仓库、产物仓库、读写边
  Risk & Governance
    风险、人工门、审批、权限策略
  Publish & Run
    执行包、预检、运行入口
```

短期可以不新增顶层 tab，而是在 `Modules` 页面中新增 `Runtime Assembly` facet。长期建议将其升级为独立层级，因为它会成为高频配置入口。

## 6. Runtime Assembly 面板结构

### 6.1 左侧对象选择

沿用当前 composable editor 的对象模型：

- Graph
- Unit / Node
- Port Edge
- Timeline Block
- Issue

Runtime Assembly 只对 Node / Graph Module / Human Gate / Tool Node 提供完整编辑。Graph 和 Edge 只展示关联装配摘要。

### 6.2 中央画布

中央画布不再只展示拓扑连线，还需要可切换到 Assembly Overlay：

```text
Node Card
  title
  executor badge
  agent badge
  projection badge
  operation count
  context count
  output contract
  issue badge
```

颜色只表示状态，不表示装饰：

- 蓝色：可运行。
- 黄色：有警告。
- 红色：阻塞发布。
- 灰色：未绑定或继承默认值。

### 6.3 右侧 Runtime Assembly Inspector

右侧 Inspector 分为 7 个区块：

1. Assembly Summary
   - node_id
   - assembly_id
   - executor_type
   - effective status
   - source path

2. Executor
   - executor_type: agent / human / graph_module / tool / subruntime
   - agent_id
   - agent_profile_id
   - runtime_lane
   - selected executor policy

3. Role & Prompt
   - projection_id
   - projection source
   - role_prompt
   - prompt overlay
   - prompt manifest ref

4. Capability
   - allowed_operations
   - denied_operations
   - visible_tools
   - dispatchable_tools
   - delegated_agent_ids
   - search_policy / allowed_search_sources

5. Context
   - visible context sections
   - hidden context sections
   - memory read policy
   - dynamic memory read policy
   - artifact refs policy
   - upstream outputs policy

6. Output Boundary
   - input contracts
   - output contracts
   - selected channel
   - canonical state
   - persist policy
   - finalization policy

7. Runtime Loop & Acceptance
   - loop mode
   - max turns
   - acceptance required
   - human gate
   - length budget
   - failure contract

## 7. 后端接口设计

### 7.1 新增 Effective Assembly View

建议新增后端视图模型：

```python
NodeEffectiveAssemblyView
```

字段结构：

```json
{
  "node_id": "node.research",
  "status": "ready",
  "assembly_intent": {
    "executor_type": "agent",
    "agent_id": "agent:web_researcher",
    "projection_id": "projection.worker.web_evidence_researcher",
    "runtime_lane": "web_research_delegate"
  },
  "effective_assembly": {
    "assembly_id": "runtime-assembly:node:...",
    "agent_profile_id": "web_research_agent",
    "context_sections": [],
    "input_contract_refs": [],
    "output_contracts": [],
    "loop_policy": {},
    "metadata": {}
  },
  "effective_permit_preview": {
    "allowed_operations": [],
    "visible_tools": [],
    "dispatchable_tools": [],
    "delegated_agent_ids": []
  },
  "output_boundary_preview": {
    "selected_channel": "graph_node_result",
    "canonical_state": "graph_node",
    "persist_policy": "graph_commit",
    "finalization_policy": "node_result_commit"
  },
  "diff": {
    "profile_defaults": {},
    "node_overrides": {},
    "contract_binding_overrides": {},
    "blocked_by_profile": [],
    "hidden_context_sections": []
  },
  "issues": []
}
```

### 7.2 接入现有执行包

当前 `GET /task-system/task-graphs/{graph_id}/execution-package` 已经返回：

- `runtime_spec`
- `manifest`
- `scheduler_state`
- `node_runtime_assemblies`
- `assembly_errors`
- `graph_module_execution_plans`

短期可以直接扩展该执行包，新增：

```json
{
  "node_effective_assembly_views": []
}
```

长期可新增轻量接口：

```text
GET /api/task-system/task-graphs/{graph_id}/runtime-assemblies
GET /api/task-system/task-graphs/{graph_id}/nodes/{node_id}/runtime-assembly
```

短期优先扩展执行包，避免前端多次请求导致状态不一致。

### 7.3 后端生成规则

后端生成 `NodeEffectiveAssemblyView` 时必须消费：

- `TaskGraphRuntimeSpec.nodes`
- `ContractManifest.node_contracts`
- `NodeRuntimeAssembly`
- `AgentRuntimeProfile`
- `contract_bindings`
- `runtime_assembly.metadata`
- `AgentAssemblyContract` 可预览字段
- `ExecutionPermit` 可预览字段

注意：如果为了 preview 构建 `AgentAssemblyContract`，不能引发真实执行、副作用或事件提交。

## 8. 前端实施设计

### 8.1 新增文件

建议新增：

```text
frontend/src/components/workspace/views/task-system/runtime-assembly/taskGraphRuntimeAssemblyTypes.ts
frontend/src/components/workspace/views/task-system/runtime-assembly/taskGraphRuntimeAssemblyView.ts
frontend/src/components/workspace/views/task-system/runtime-assembly/TaskGraphRuntimeAssemblyPage.tsx
frontend/src/components/workspace/views/task-system/runtime-assembly/TaskGraphRuntimeAssemblyCanvas.tsx
frontend/src/components/workspace/views/task-system/runtime-assembly/TaskGraphRuntimeAssemblyInspector.tsx
frontend/src/components/workspace/views/task-system/runtime-assembly/TaskGraphRuntimeAssemblyMatrix.tsx
frontend/src/components/workspace/views/task-system/runtime-assembly/TaskGraphRuntimeAssemblyDiffPanel.tsx
frontend/src/components/workspace/views/task-system/runtime-assembly/taskGraphRuntimeAssemblyTemplates.ts
frontend/src/components/workspace/views/task-system/runtime-assembly/taskGraphRuntimeAssemblyPreflight.ts
```

### 8.2 调整现有文件

需要调整：

```text
frontend/src/components/workspace/views/task-system/TaskGraphWorkbench.tsx
frontend/src/components/workspace/views/task-system/TaskGraphLayerNav.tsx
frontend/src/components/workspace/views/task-system/TaskGraphObjectInspector.tsx
frontend/src/components/workspace/views/task-system/TaskGraphExecutionPackagePanel.tsx
frontend/src/components/workspace/views/task-system/taskGraphTypes.ts
frontend/src/components/workspace/views/task-system/taskGraphContractBindings.ts
frontend/src/lib/api.ts
```

### 8.3 UI 结构

Runtime Assembly 页面采用三栏工作台：

```text
左：Assembly Matrix / Node List
中：Assembly Canvas
右：Assembly Inspector
底：Issues / Effective Diff Dock
```

避免做成大面积卡片墙。节点列表和矩阵保持高密度、可扫描。

### 8.4 装配模板

前端可以提供模板，但模板只写入装配意图，不直接伪造 effective assembly。

第一批模板：

- 普通 Agent 节点。
- Web Research Agent。
- Evidence Verifier。
- Human Review Gate。
- Graph Module Node。
- Tool-only Node。
- Memory Reader Node。
- Artifact Producer Node。

SearchRuntime 后续作为模板接入：

```text
template_id: runtime.template.search_researcher
agent_id: agent:web_researcher
projection_id: projection.worker.web_evidence_researcher
runtime_lane: web_research_delegate
operation_policy:
  required_operations:
    - op.model_response
    - op.web_search
    - op.fetch_url
```

## 9. 数据写入边界

前端编辑时只写以下位置：

1. 节点基础字段
   - `agent_id`
   - `projection_id`
   - `runtime_lane`
   - `node_type`
   - `execution_mode`

2. 节点 `contract_bindings`
   - `schema`
   - `execution`
   - `memory`
   - `artifact`
   - `acceptance`
   - `runtime`
   - `governance`

3. 节点 `metadata`
   - `role_prompt`
   - `tool_execution_policy`
   - `context_visibility_policy`
   - template marker

4. 图级 `runtime_policy`
   - 只处理图全局默认值，不覆盖节点显式装配。

禁止前端写入：

- `effective_assembly`
- `execution_permit`
- `output_boundary_preview`
- 后端 diagnostics
- 编译后 runtime spec

## 10. 迁移方案

### 阶段一：只读 Effective Assembly Preview

目标：

- 后端执行包新增 `node_effective_assembly_views`。
- 前端在 Publish & Run 或 Modules 页面展示节点装配矩阵。
- 不改变现有编辑行为。

完成标准：

- 每个非 graph_module 节点能看到 effective agent/profile/projection/context/output。
- 缺失 agent 或 profile 时有明确 issue。
- 前端测试覆盖 API 类型和视图投影。

### 阶段二：Runtime Assembly Inspector

目标：

- 新增节点 Runtime Assembly Inspector。
- 将 agent、projection、runtime_lane、operation policy、memory policy、output contract 作为结构化控件。
- 保留 `TaskGraphContractBindingInspector`，但降级为高级契约区。

完成标准：

- 用户不需要打开 JSON 就能完成常见 runtime 装配。
- 编辑后重新编译执行包，effective view 能反映变化。
- 原有 contract binding 测试通过。

### 阶段三：Assembly Templates

目标：

- 提供常用节点装配模板。
- 模板写入节点基础字段、metadata 和 contract_bindings。
- 支持 Search Researcher 模板，为 DeepSearch 做准备。

完成标准：

- 应用模板后不会产生无效节点。
- 模板结果可以被后端执行包解释。
- Search Researcher 模板至少能形成现有 web researcher 单跳能力。

### 阶段四：Diff / Policy Debugger

目标：

- 显示 profile default、node override、contract binding override、policy block。
- 展示工具权限为何可见或被拦截。
- 展示 context section 为何隐藏。

完成标准：

- 用户能定位“为什么这个节点没有 web_search / fetch_url / memory_read”。
- 用户能定位“为什么 projection 没生效”。
- 用户能定位“为什么输出契约没有进入 assembly”。

### 阶段五：运行态闭环

目标：

- 将运行监控中的实际 WorkOrder / AgentAssemblyContract / ExecutionPermit 与设计期 Effective Assembly 对齐显示。
- 支持“设计期装配”和“运行期实际装配”对比。

完成标准：

- 运行一个 TaskGraph 后，用户能看到每个节点实际采用的 assembly。
- 如果运行期因策略、搜索源、审批、profile 产生变化，UI 能指出差异。

## 11. 验证策略

### 后端测试

新增或扩展：

```text
backend/tests/runtime_assembly_builder_test.py
backend/tests/task_system_api_regression.py
backend/tests/task_graph_permission_boundary_regression.py
backend/tests/orchestration_agent_management_regression.py
```

重点验证：

- execution package 返回 effective assembly views。
- agent/profile/projection resolution 正确。
- operation policy 和 profile allowed/blocked 合并正确。
- graph_module 节点不被普通 node assembly 误处理。
- 缺失 profile、缺失 contract、缺失 projection 有稳定 issue。

### 前端测试

新增：

```text
frontend/src/components/workspace/views/task-system/runtime-assembly/taskGraphRuntimeAssemblyView.test.ts
frontend/src/components/workspace/views/task-system/runtime-assembly/taskGraphRuntimeAssemblyTemplates.test.ts
frontend/src/components/workspace/views/task-system/runtime-assembly/taskGraphRuntimeAssemblyPreflight.test.ts
```

扩展：

```text
frontend/src/components/workspace/views/task-system/taskGraphContractBindings.test.ts
frontend/src/components/workspace/views/task-system/taskGraphRuntimeSupport.test.ts
frontend/src/components/workspace/views/task-system/taskGraphPreflight.test.ts
```

重点验证：

- effective assembly view 投影稳定。
- 模板只写装配意图，不伪造后端结果。
- Inspector 修改字段后 patch 正确。
- issue 能映射回节点、字段和面板。

### 手工验证

固定节点：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8003`

验证页面：

- Task System -> TaskGraph Workbench。
- Modules / Runtime Assembly。
- Publish & Run。

验证案例：

1. 普通 Agent 节点。
2. Web Research Agent 节点。
3. Human Gate 节点。
4. Graph Module 节点。
5. 缺失 Agent Profile 的错误节点。
6. 被 profile deny tool 的节点。

## 12. 风险与控制

### 风险一：前端变成第二套编译器

控制：

- 前端只写 intent，只读 effective。
- 所有 effective assembly 来自后端。

### 风险二：contract_bindings 和结构化控件双写冲突

控制：

- 结构化控件必须调用统一 helper 写入 contract_bindings。
- 不允许同一个字段在多个面板独立维护不同路径。

### 风险三：页面层级继续混乱

控制：

- Runtime Assembly 独立为 facet 或页面。
- ContractBindingInspector 作为高级区，不再承担主信息架构。

### 风险四：SearchRuntime 过早下沉成特殊系统

控制：

- Search 先作为 runtime assembly template。
- 等 DeepSearch loop 成熟后，再决定是否做 subruntime 或特定 task。

### 风险五：旧残留逻辑继续影响新结构

控制：

- 新面板上线后，旧的重复配置入口要清理或降级。
- 不保留“兼容用”的第二套编辑路径。

## 13. 文件级执行清单

### 后端

```text
backend/runtime/contracts/runtime_assembly_models.py
  新增 NodeEffectiveAssemblyView / EffectivePermitPreview / OutputBoundaryPreview。

backend/runtime/contracts/runtime_assembly_builder.py
  增加 build_node_effective_assembly_view。

backend/api/task_system.py
  在 execution package 中返回 node_effective_assembly_views。

backend/runtime/agent_assembly/assembler.py
  必要时提供 preview-safe 的 output boundary / capability summary helper。
```

### 前端

```text
frontend/src/lib/api.ts
  增加 NodeEffectiveAssemblyView 类型。

frontend/src/components/workspace/views/task-system/TaskGraphWorkbench.tsx
  接入 Runtime Assembly 页面或 facet。

frontend/src/components/workspace/views/task-system/TaskGraphLayerNav.tsx
  增加 Runtime Assembly 层级入口。

frontend/src/components/workspace/views/task-system/runtime-assembly/*
  新增 runtime assembly 工作台组件。

frontend/src/components/workspace/views/task-system/TaskGraphExecutionPackagePanel.tsx
  增加 Effective Assembly Matrix 摘要。

frontend/src/components/workspace/views/task-system/TaskGraphNodeUnitInspector.tsx
  将节点基础身份字段与 Runtime Assembly Inspector 分离。

frontend/src/components/workspace/views/task-system/TaskGraphContractBindingInspector.tsx
  保留为高级契约编辑区，减少主流程曝光。
```

## 14. 最终目标形态

最终用户在任务图中选择一个节点后，看到的不应该是散乱字段，而是一份清晰的运行装配：

```text
这个节点由谁执行。
它扮演什么职责。
它能看见什么上下文。
它能调用什么能力。
它必须输出什么。
它如何被验收。
它运行时会进入哪条边界。
它为什么当前可运行或不可运行。
```

这就是后续 SearchRuntime、DeepSearch、VerifierRuntime、WriterRuntime 等专用 agent runtime 能稳定扩展的基础。

