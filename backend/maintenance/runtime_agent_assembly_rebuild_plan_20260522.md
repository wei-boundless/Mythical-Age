# Runtime Agent Assembly 重构计划书 - 2026-05-22

## 0. 计划立场

本计划只依据当前 backend 源码和本地 `D:\AI应用\claude-code-nb-main` 源码对照，不引用 `docs/`。

这次重构的目标不是“继续拆文件”，也不是在旧壳上再包一层新壳，而是把当前重复、交叉、容易污染上下文的 agent runtime 组装链路收敛成一条可验证主链路：

```text
Task / TaskGraph 决定要做什么
  -> WorkOrder 表达一次可执行工作单
  -> AgentAssembly 组装 agent 如何工作、有什么权限、看见什么上下文
  -> UnitRuntime 执行单 agent 循环
  -> ExecutionEngine/ToolRuntime 执行模型轮次和工具轮次
  -> CoordinationRuntime 只消费节点结果并推进图状态
```

硬性非目标：

- 不动 frontend。
- 不动 observability/monitoring。
- 不用旧 docs 作为依据。
- 不保留无用旧壳兼容层。
- 不把 TaskGraph 合并进单 agent runtime。TaskGraph 是任务系统的一部分，单 agent runtime 只是它的执行单元之一。

## 1. 源码事实报告

### 1.1 当前系统的真实臃肿点

当前不是“目录多”导致臃肿，而是同一个概念被多套 builder 和 contract 重复表达。

1. `backend/runtime/agent_assembly/assembler.py`

   `build_agent_assembly_contract()` 已经在做真正的 agent 装配：解析 agent/profile/lane/projection/soul/prompt/memory/capability/output boundary/ports，并生成 `AgentAssemblyContract`。

   这个文件最接近目标架构里的唯一 agent 组装层，应保留并强化。

2. `backend/agent_system/assembly/runtime_chain.py`

   `AgentRuntimeChainAssembler.build_runtime()` 同时做 memory intent、intent frame、continuation decision、query understanding、task execution assembly、context policy、orchestration runtime bundle。

   这不是单纯 agent assembly，而是“理解系统 + 任务选择 + memory 请求 + runtime 规格 + 上下文拼接”的混合物。它是当前 runtime 组装重复和污染的重要来源。

3. `backend/runtime/contracts/runtime_assembly_builder.py`

   这里也在构造 `SingleAgentRuntimeAssembly` 和 `NodeRuntimeAssembly`，并表达 context sections、output contracts、acceptance contracts、loop policy、handoff packets。

   其中 output/acceptance/handoff 对 TaskGraph 有价值，但 single-agent runtime assembly 与 `runtime/agent_assembly` 重叠。

4. `backend/task_system/services/assembly_builder.py`

   `build_task_execution_assembly_bundle()` 负责 task intent、execution shape、recipe、operation requirement、projection selection、communication protocol。

   它应该属于任务语义层，但现在也会间接决定 runtime operations/delegation/agent 行为，容易与 agent assembly 抢职责。

5. `backend/runtime/unit_runtime/loop.py`

   `TaskRunLoop` 初始化阶段同时拥有 event log/checkpoints/execution store/state index/runtime object store/coordination runtime/memory runtime/task registry/agent registry/execution engine/finalizer。

   `run_single_agent_lane()` 又重新拆解 task operation、graph payload、agent runtime spec、assembly contract、execution permit、sandbox policy、ledger 等。这使它成为平台内核、任务系统、agent loop、coordination adapter、finalizer 的混合体。

6. `backend/runtime/coordination_runtime/runtime.py`

   coordination runtime 在 `_build_next_stage_execution_request` 附近不仅创建 `NodeExecutionRequest` 和 `WorkOrder`，还直接调用 `build_agent_assembly_contract()`。

   这说明任务图层已经越界进入 agent 装配层。TaskGraph 应该发 WorkOrder，而不是组装 agent。

7. `backend/runtime/agent_assembly/models.py`

   `WorkOrder` 当前携带 `graph_state`、`executor_binding`、`current_turn_context`、`artifact_policy`、`stream_policy`、`memory_snapshot`、`artifact_context_packet`、`revision_packet`、`a2a_payload`、`runtime_assembly` 等大量字段。

   这些字段并非都错，但它们不应该同处于一个“可随处传递”的对象里。当前设计让控制态、模型可见上下文、图状态、产物策略、记忆快照混在一起。

8. `backend/runtime/agent_assembly/boundary.py`

   这个文件方向是对的：它区分 `CONTROL_CONTEXT_KEYS`、`MODEL_CONTEXT_KEYS`、`TASK_SELECTION_KEYS`，并提供 `build_runtime_control_payload()`、`build_model_context_payload()`、`build_task_selection_payload()`。

   但它目前还是“清洗辅助函数”，不是系统强制入口。重构应把它升格为 runtime assembly 的硬边界。

9. `backend/runtime/tool_runtime/tool_result_envelope.py`

   `ToolResultEnvelope` 对工具结果做了结构化封装，包括 observed paths、matched paths、artifact refs、command receipt、execution receipt。

   但它不是工具协议守卫。它没有强制保证每个 model tool_call 必有匹配 tool_result，也没有统一处理 abort/fallback/error 下的 synthetic tool_result。

### 1.2 Claude Code 可借鉴的机制

本地 Claude Code 的可借鉴点不是目录结构，而是几个工程硬约束。

1. `query.ts` 是统一 agentic loop。

   它在一次 query 开始时准备 messages、system prompt、toolUseContext、context compaction、tool budget，然后进入同一个 model/tool/follow-up 循环。

   可借鉴点：不要让 task graph、runtime chain、unit loop 各自组装 agent；只允许一个入口产出 agent invocation。

2. `tools/AgentTool/runAgent.ts` 是 agent 组装层。

   它集中处理 agent definition、模型、工具、权限、MCP、上下文继承、subagent hooks、abort controller，然后交给 `query()`。

   可借鉴点：你的 `runtime/agent_assembly` 应成为这个角色，负责把 `WorkOrder` 变成可执行的 `AgentInvocation`。

3. `ToolUseContext` 明确承载 runtime-only 信息。

   Claude Code 把工具、权限、abort、app state、MCP clients、refreshTools 等放在 `ToolUseContext`，而不是塞进模型上下文。

   可借鉴点：你的 `RuntimeControl` 与 `ModelContext` 必须强隔离，`current_turn_context` 不能再携带 raw control object。

4. 工具协议修复是硬边界。

   `query.ts` 在 fallback、异常、abort、streaming executor discard 等路径上都会为未完成 tool_use 补 synthetic tool_result，避免 provider 协议错误和上下文污染。

   可借鉴点：在 `runtime/execution_engine` 增加 tool_call/tool_result pairing guard，而不是只依赖 tool result envelope。

5. stop/finalization 与 loop 分离。

   Claude Code 的 stop hooks 在模型轮次结束后单独处理，必要时阻止 continuation 或插入 blocking errors。

   可借鉴点：你的 `TaskRunFinalizer` 应继续存在，但 `TaskRunLoop` 不应该在主循环里散落大量 finalization/ad hoc repair 逻辑。

6. 默认隔离、显式共享。

   Claude Code subagent 对上下文继承、工具权限、abort controller、background agent prompt 权限都显式处理。

   可借鉴点：你的 graph node、subruntime、delegated agent 默认只拿 `WorkOrder` 和明确授权的 context refs；共享记忆、artifact、graph handle 必须显式出现在 runtime control 中。

## 2. 目标架构

### 2.1 目标目录责任

```text
backend/task_system/
  任务定义、任务语义、recipe、operation requirement、任务图契约。
  允许产出 TaskExecutionAssembly。
  禁止产出 AgentAssemblyContract。

backend/runtime/coordination_runtime/
  TaskGraph 调度、节点状态、batch/retry/handoff、NodeExecutionRequest、WorkOrder、NodeResultEnvelope。
  允许产出 WorkOrder。
  禁止组装 agent prompt/model/tool/permission。

backend/runtime/agent_assembly/
  唯一 agent 组装层。
  输入 WorkOrder + registry/profile + explicit runtime control。
  输出 AgentAssemblyContract / ExecutionPermit / AgentInvocation / sanitized ModelContext。

backend/runtime/unit_runtime/
  单 agent loop。
  输入 AgentInvocation。
  负责 model/tool/follow-up/finalization 顺序。
  禁止重新理解任务、重新选择 agent、重新编译 task graph。

backend/runtime/execution_engine/
  模型轮次、工具调用事件翻译、tool_call/tool_result 协议守卫、follow-up 构造、final answer synthesis。

backend/runtime/tool_runtime/
  工具真实执行、sandbox、execution record、ToolResultEnvelope。

backend/runtime/contracts/
  TaskGraph contract manifest、output/acceptance/handoff/failure contract。
  禁止表达 single-agent runtime assembly。
```

### 2.2 目标核心对象

#### WorkOrder

表达“本次要执行什么工作”。它应该轻量化。

保留：

- `work_order_id`
- `work_kind`
- `task_ref`
- `executor_type`
- `coordination_run_id`
- `root_task_run_id`
- `stage_id`
- `node_id`
- `agent_id`
- `agent_profile_id`
- `runtime_lane`
- `message`
- `explicit_inputs`
- `input_package`
- `artifact_policy_ref` 或小型 artifact policy summary
- `stream_policy_ref` 或小型 stream policy summary
- `output_contract_id`
- `expected_outputs`
- `idempotency_key`

降级为 refs/control，不再直接作为 WorkOrder 主体传播：

- `graph_state`
- `current_turn_context`
- `memory_snapshot`
- `artifact_context_packet`
- `revision_packet`
- `a2a_payload`
- `runtime_assembly`
- 大型 `executor_binding`
- 大型 `dispatch_context`

#### RuntimeControl

表达 runtime-only 控制态。

必须只由 `runtime/agent_assembly/boundary.py` 创建和读取。

包含：

- full `stage_execution_request`
- full/sanitized `node_work_order`
- full `agent_assembly_contract`
- `execution_permit`
- `standard_input_package`
- `graph_module_runtime_handle`
- `human_work_packet`
- refs/summaries for memory/artifact/a2a/revision

禁止进入模型上下文。

#### ModelContext

表达 agent 可见上下文。

只能由 `build_model_context_payload()` 生成。

允许：

- task identity
- agent identity
- projection identity
- runtime lane
- explicit inputs after protocol-key filtering
- artifact root/ref
- coordination refs
- stage request ref
- work order ref
- assembly ref

禁止：

- raw `stage_execution_request`
- raw `node_work_order`
- raw `agent_assembly_contract`
- raw `execution_permit`
- raw `runtime_control`
- raw `a2a_payload`
- raw graph module handle
- internal protocol input keys

#### TaskSelection

表达路由和选择结果，不是 runtime control dump。

允许：

- selected task
- agent/profile/lane/projection
- executor type
- work_order_id / assembly_id / stage_execution_request_ref
- search/sandbox/stream policy summary

禁止：

- full request/work_order/contract/control object

#### AgentInvocation

建议新增或以 `AgentAssemblyContract + ExecutionPermit + ModelContext` 组合表达。

它是 `unit_runtime` 唯一消费对象：

```text
AgentInvocation
  assembly_contract
  execution_permit
  model_context
  prompt_assembly
  tool_binding
  memory_binding
  output_boundary
  runtime_control_ref
```

如果不新增类，也必须在 `runtime/agent_assembly` 提供唯一函数：

```python
build_agent_invocation(work_order, *, base_dir, runtime_profile=None) -> dict
```

## 3. 硬约束

### 3.1 智能 agent 原则约束

1. agent prompt 必须是角色任务语言，不是开发说明。

   允许：

   ```text
   你是一名世界观审核员。
   你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。
   你不负责替创作者扩写设定。
   你需要指出问题、给出裁决、说明是否允许进入下一阶段。
   ```

   禁止：

   ```text
   这是 runtime 节点。
   根据任务图执行 world_review。
   这个节点用于校验资产。
   ```

2. agent 必须只看见完成当前任务所需内容。

   RuntimeControl 里的控制对象不能泄露给模型。

3. 长任务必须有可恢复的执行边界。

   每个 WorkOrder / AgentInvocation / NodeResultEnvelope 都必须有稳定 id 和 idempotency key。

4. 多 agent 必须默认隔离、显式共享。

   子任务、图模块、委托 agent 不继承全部上下文。共享 memory/artifact/graph handle 必须通过 control refs 明确授权。

5. 工具调用必须协议完整。

   任意 tool_call 无论成功、失败、拒绝、取消、abort，都必须产生匹配 tool_result 或 synthetic error result。

6. 输出必须有边界。

   单 agent 输出不能直接污染 graph state。TaskGraph 只能通过 NodeResultEnvelope 接收 accepted outputs。

### 3.2 工程约束

1. `coordination_runtime` 不再调用 `build_agent_assembly_contract()`。

2. `TaskRunLoop` 不再调用 task understanding / task assembly builder 来重新决定 agent。

3. `runtime/contracts` 不再产出 single-agent runtime assembly。

4. `task_system/services/assembly_builder.py` 不再产出或修改 agent runtime spec。

5. `current_turn_context` 必须经过 `build_model_context_payload()`。

6. `task_selection` 必须经过 `build_task_selection_payload()`。

7. event/checkpoint/diagnostics 默认存 refs 和 summary，不存大对象全文。需要全文时进入 runtime object store。

8. 删除确认无调用的旧兼容 helper，不保留“也许以后有用”的旧壳。

## 4. 执行计划

### Phase 1 - 锁定边界与测试护栏

目标：先把“不能泄露、不能重复装配”的规则变成测试，防止后续重构跑偏。

涉及文件：

- `backend/runtime/agent_assembly/boundary.py`
- `backend/runtime/agent_assembly/models.py`
- `backend/tests/agent_assembly_models_regression.py`
- `backend/tests/node_execution_request_regression.py`
- `backend/tests/langgraph_coordination_runtime_regression.py`
- 新增或扩展 `backend/tests/runtime_agent_assembly_boundary_regression.py`

工作：

1. 为 `build_runtime_control_payload()`、`build_model_context_payload()`、`build_task_selection_payload()` 增加更严格测试。
2. 测试 `current_turn_context` 不出现 full control object。
3. 测试 raw `a2a_payload`、raw `stage_execution_request`、raw `node_work_order`、raw `agent_assembly_contract` 不进入 model context。
4. 测试 assembly identity 优先级高于 stale task_selection。
5. 测试 explicit inputs 会过滤 internal protocol keys。

完成标准：

- 边界测试失败时能明确指出泄露字段。
- 未改业务逻辑时，现有 regression tests 仍可通过或暴露真实旧问题。

### Phase 2 - 建立唯一 AgentInvocation 入口

目标：把 `runtime/agent_assembly` 升级为唯一 agent 组装层。

涉及文件：

- `backend/runtime/agent_assembly/models.py`
- `backend/runtime/agent_assembly/assembler.py`
- `backend/runtime/agent_assembly/__init__.py`
- `backend/runtime/agent_assembly/validation.py`
- 新增 `backend/runtime/agent_assembly/invocation.py`

工作：

1. 新增 `AgentInvocation` 或等价 dict contract。
2. 新增 `build_agent_invocation(work_order, *, base_dir, agent_runtime_profile=None)`。
3. `build_agent_invocation()` 内部统一生成：
   - `AgentAssemblyContract`
   - `ExecutionPermit`
   - `RuntimeControl`
   - `ModelContext`
   - `TaskSelection`
4. `build_agent_assembly_contract()` 保留为内部能力，但外部调用逐步迁移到 `build_agent_invocation()`。
5. `validation.py` 增加 invocation validation：
   - 有 assembly
   - 有 permit
   - model_context 无 control keys
   - permit 与 assembly agent identity 一致

完成标准：

- 所有 direct/node/subruntime/human work order 都能生成 invocation。
- invocation 是 `unit_runtime` 可消费的唯一结构。

### Phase 3 - 切断 CoordinationRuntime 对 agent assembly 的越界调用

目标：TaskGraph 只产出 WorkOrder，不装配 agent。

涉及文件：

- `backend/runtime/coordination_runtime/runtime.py`
- `backend/runtime/coordination_runtime/work_order_builder.py`
- `backend/runtime/coordination_runtime/runner.py`
- `backend/runtime/subruntime/graph_module_executor.py`
- `backend/runtime/agent_assembly/boundary.py`

工作：

1. 删除 `coordination_runtime/runtime.py` 中直接 `build_agent_assembly_contract()` 的调用。
2. `_build_next_stage_execution_request` 返回：
   - `stage_execution_request`
   - `node_work_order`
   - `runtime_control` ref/summary
   - no full `agent_assembly_contract`
3. `LangGraphCoordinationRuntimeResult.continuation_payload()` 不再要求 coordination result 自带 full assembly contract。
4. 需要执行节点时，由 `unit_runtime` 或上层 execution adapter 用 WorkOrder 调 `build_agent_invocation()`。
5. GraphModule diagnostics 只保存 parent control summary，不保存 full parent contract。

完成标准：

- `rg "build_agent_assembly_contract" backend/runtime/coordination_runtime` 无业务调用。
- TaskGraph 回归测试仍能产生 stage execution request 和 node work order。
- GraphModule 仍可启动 imported graph，但 diagnostics 只含 refs/summaries。

### Phase 4 - 收缩 AgentRuntimeChainAssembler

目标：把 `AgentRuntimeChainAssembler` 从“runtime 组装器”降级为“理解/任务选择 pipeline”，避免它继续二次装配 agent runtime。

涉及文件：

- `backend/agent_system/assembly/runtime_chain.py`
- `backend/agent_system/assembly/runtime_bundle_builder.py`
- `backend/task_system/services/assembly_builder.py`
- `backend/runtime/unit_runtime/loop.py`

工作：

1. 重命名或语义降级：
   - 当前 `AgentRuntimeChainAssembler` 不再被视为 runtime assembly。
   - 后续可迁移为 `TaskUnderstandingPipeline` 或 `TurnContextBuilder`。
2. `build_runtime()` 输出只保留：
   - query understanding
   - intent decision
   - continuation candidates/decision
   - task execution assembly
   - context policy
   - sanitized current_turn_context
3. 删除它对 `agent_assembly_contract` 的 ad hoc merge 逻辑。
4. `task_system/services/assembly_builder.py` 只返回 task contract/recipe/operation requirement，不再修改 agent runtime spec。
5. `runtime_bundle_builder.py` 如果只是在生成 agent runtime spec，应迁移进 `runtime/agent_assembly` 或删除。

完成标准：

- `AgentRuntimeChainAssembler` 不产出 `agent_runtime_spec` 作为权威 agent identity。
- stale task selection 无法覆盖 `AgentInvocation` 的 agent/profile/lane。
- `task_system` 不直接构造 agent runtime contract。

### Phase 5 - 改造 TaskRunLoop 为单 agent loop consumer

目标：让 `TaskRunLoop` 消费 `AgentInvocation`，不再自己重新组装一遍 agent。

涉及文件：

- `backend/runtime/unit_runtime/loop.py`
- `backend/runtime/unit_runtime/runtime_policy.py`
- `backend/runtime/unit_runtime/finalizer.py`
- `backend/runtime/execution_engine/engine.py`
- `backend/runtime/execution_engine/followup_cycle.py`
- `backend/runtime/execution_engine/final_output.py`

工作：

1. `run_single_agent_lane()` 入参增加或内部构造 `AgentInvocation`。
2. 移除 `_assembly_contract_from_continuation_payload()` 内的 fallback rebuild，改为明确 WorkOrder -> invocation。
3. 移除 `_agent_runtime_spec_with_assembly_contract()` 这类 spec patch helper。
4. `TaskRunLoop` 启动 task_run/agent_run 时，从 invocation 获取 agent/profile/lane/permit/model_context。
5. `TaskRunLoop` 不再展开 graph payload/task graph runtime spec 除非是 trace refs。
6. finalizer 只处理 terminal state/accepted output/continuation，不重新组装下一阶段 agent。

完成标准：

- 单 agent 执行路径中 agent identity 只有 invocation 一个权威来源。
- continuation 执行下一节点时通过 WorkOrder 生成新 invocation。
- `TaskRunLoop` 的代码体积和职责明显下降，不再做 task graph 编译/agent spec patch。

### Phase 6 - 工具协议守卫

目标：借鉴 Claude Code 的 tool_use/tool_result 配对修复，解决工具调用失败路径的协议风险。

涉及文件：

- `backend/runtime/execution_engine/tool_loop.py`
- `backend/runtime/execution_engine/engine.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- 新增 `backend/runtime/execution_engine/tool_protocol_guard.py`
- 相关 tests

工作：

1. 新增 `ToolProtocolGuard`：
   - 记录 model turn 中出现的 tool_call ids。
   - 记录已产生的 tool_result ids。
   - 对 missing result 生成 synthetic error result。
   - 对 duplicate/orphan result 产出 diagnostics 并阻断进入下一模型轮次。
2. 在 `RuntimeExecutionEngine.stream_model_turn()` 或 `TaskRunLoop._apply_model_turn_event()` 边界接入。
3. 在 abort、permission waiting、operation gate deny、executor error、replay deny 路径上都保证 tool_result 完整。
4. 保留 `ToolResultEnvelope` 作为结果内容封装，不让它承担协议守卫职责。

完成标准：

- 任意工具调用失败路径都不会留下 dangling tool_call。
- 新测试覆盖 success/deny/error/abort/replay deny。

### Phase 7 - Runtime 文件与诊断瘦身

目标：减少 runtime 文件副作用，不再到处保存大 payload。

涉及文件：

- `backend/runtime/unit_runtime/loop.py`
- `backend/runtime/coordination_runtime/runtime.py`
- `backend/runtime/subruntime/graph_module_executor.py`
- `backend/runtime/shared/*`
- `backend/runtime/storage/*` 或当前 object store 相关模块

工作：

1. 定义大对象写入规则：
   - full control object -> runtime object store
   - event/checkpoint -> refs + compact summary
   - model_context -> sanitized visible payload
2. task_contract/task_operation/agent_assembly_contract/sandbox_policy/graph runtime spec 不再在多个 event 重复全文写入。
3. GraphModule diagnostics 从 full parent objects 改为 `runtime_control_ref_summary()`。
4. 清理旧 helper 和旧 tests fixture，删除无调用兼容壳。

完成标准：

- 新 runtime 运行一次不会重复产出多份 full assembly/control payload。
- event log 可读性提升，checkpoint 仍可恢复。

## 5. 文件级执行清单

### 必改

- `backend/runtime/agent_assembly/boundary.py`
  - 升格为强制边界。
  - 增加 control/model/task selection schema guards。

- `backend/runtime/agent_assembly/models.py`
  - 增加 `AgentInvocation` 或瘦身 WorkOrder。
  - 标记将被降级的重字段。

- `backend/runtime/agent_assembly/assembler.py`
  - 新增唯一 invocation builder。
  - `build_agent_assembly_contract()` 降为内部步骤。

- `backend/runtime/coordination_runtime/runtime.py`
  - 移除 agent assembly 越界调用。
  - 只产出 request/work_order/control summary。

- `backend/runtime/unit_runtime/loop.py`
  - 改为消费 invocation。
  - 移除重复 assembly/spec patch/continuation rebuild。

- `backend/runtime/execution_engine/tool_loop.py`
  - 接入 tool protocol guard。

- `backend/runtime/execution_engine/engine.py`
  - 在 model turn 边界提供 pairing/repair。

- `backend/agent_system/assembly/runtime_chain.py`
  - 降级为理解/上下文 pipeline。
  - 不再作为 runtime assembly 权威。

- `backend/task_system/services/assembly_builder.py`
  - 收回到 task domain。

- `backend/runtime/contracts/runtime_assembly_builder.py`
  - 删除或降级 single-agent runtime assembly。
  - 保留 graph/node output/acceptance/handoff contract 能力。

### 可能改

- `backend/runtime/unit_runtime/finalizer.py`
  - 如果 finalizer 中存在下一阶段装配逻辑，迁移到 WorkOrder -> invocation。

- `backend/runtime/subruntime/graph_module_executor.py`
  - 收缩 diagnostics，保留 refs。

- `backend/api/orchestration.py`
  - 如果 API 仍要求 full assembly contract，需要调整为 work_order/runtime_control ref。

### 禁止改

- `backend/observability/`
- monitoring/live monitor 相关 UI/API，除非测试证明 runtime payload shape 改动必须适配。
- frontend。
- old docs。

## 6. 迁移与切换规则

### 6.1 Shadow 阶段

先在当前链路旁边生成 `AgentInvocation`，但不立即作为唯一执行输入。

要求：

- 旧 assembly contract 与新 invocation 中 agent/profile/lane/permit 一致。
- 若不一致，测试必须暴露差异，不能静默 fallback。

### 6.2 Cutover 阶段

当 direct run、TaskGraph node run、GraphModule run 三条路径都能生成 invocation 后：

- `TaskRunLoop` 切到只消费 invocation。
- `coordination_runtime` 删除 direct assembly 调用。
- `runtime_chain` 删除对 assembly contract 的 merge/patch 逻辑。

### 6.3 删除旧壳

切换后删除：

- 无调用的 assembly fallback helper。
- 旧 single-agent runtime assembly builder。
- 旧测试夹具里只为兼容旧 payload 存在的 fixtures。

不保留“暂时不用但以后可能有用”的兼容分支。

### 6.4 回滚规则

因为用户已提交代码，可以大胆改，但每个 phase 必须保持可测试。

回滚只允许回滚当前 phase 的新改动，不允许恢复已经确认删除的旧残留逻辑作为长期兼容层。

## 7. 验证矩阵

### 7.1 静态验证

```powershell
python -m compileall backend/runtime/agent_assembly backend/runtime/coordination_runtime backend/runtime/unit_runtime backend/runtime/execution_engine backend/runtime/tool_runtime backend/agent_system/assembly backend/task_system/services
```

### 7.2 重点测试

```powershell
pytest backend/tests/agent_assembly_models_regression.py -q
pytest backend/tests/node_execution_request_regression.py -q
pytest backend/tests/langgraph_coordination_runtime_regression.py -q
pytest backend/tests/runtime_assembly_builder_test.py -q
pytest backend/tests/query_runtime_runtime_loop_regression.py -q
pytest backend/tests/task_graph_permission_boundary_regression.py -q
```

### 7.3 新增测试目标

新增或扩展：

- `backend/tests/runtime_agent_assembly_boundary_regression.py`
- `backend/tests/runtime_agent_invocation_regression.py`
- `backend/tests/runtime_tool_protocol_guard_regression.py`

覆盖：

1. direct WorkOrder -> invocation。
2. node WorkOrder -> invocation。
3. human WorkOrder 不进入 agent loop。
4. subruntime WorkOrder 进入 graph module executor。
5. stale task_selection 不能覆盖 invocation identity。
6. model_context 不含 raw control object。
7. tool_call missing result 自动生成 synthetic error result。
8. permission denied/tool blocked 仍生成 tool_result。
9. abort 后没有 dangling tool_call。
10. GraphModule diagnostics 不保存 full parent assembly。

## 8. 风险控制

### 风险 1：TaskGraph 误伤

原因：coordination runtime 当前确实产出 agent assembly contract。

控制：

- Phase 3 只切断 assembly 越界，不改 graph scheduling。
- TaskGraph 仍产出 `NodeExecutionRequest` 和 `WorkOrder`。
- 由 unit runtime 在执行边界统一装配 invocation。

### 风险 2：旧 API 消费 full assembly contract

原因：`backend/api/orchestration.py` 多处读取 `stage_execution_request/node_work_order/agent_assembly_contract`。

控制：

- API 返回可先保留 `agent_assembly_contract_ref/summary`。
- full object 仅在 debug/internal 明确请求时从 runtime object store 取。

### 风险 3：上下文变少导致 agent 能力下降

原因：旧系统把很多 raw payload 都塞进 context，agent 可能偶然依赖噪声。

控制：

- ModelContext 不删有效任务信息，只删控制对象。
- explicit inputs、standard input package、artifact refs、acceptance/output requirements 仍通过明确可见 sections 进入 prompt。
- 对 novel writing / world review / artifact writing 这类任务做端到端回归。

### 风险 4：长任务恢复丢状态

原因：大 payload 从 event/checkpoint 移到 ref store。

控制：

- RuntimeControl refs 必须可恢复。
- WorkOrder id、stage request ref、assembly id、permit id、result envelope id 全部稳定。
- checkpoint 保留恢复所需 refs，不依赖模型上下文恢复控制态。

### 风险 5：工具协议守卫改变错误表现

原因：旧路径可能直接 loop_error，新路径会 synthetic tool_result。

控制：

- synthetic result 必须标记 `is_error/status=error/source=tool_protocol_guard`。
- 原始错误仍进入 diagnostics。
- final answer 不应把 synthetic 内部错误当成功证据。

## 9. 最终完成标准

重构完成必须满足以下条件：

1. `runtime/agent_assembly` 是唯一 agent 组装层。
2. `coordination_runtime` 不再直接构造 `AgentAssemblyContract`。
3. `TaskRunLoop` 消费 `AgentInvocation`，不再 patch agent spec。
4. `runtime_chain` 不再作为 runtime assembly 权威。
5. `task_system` 不再直接决定 agent runtime spec。
6. `runtime/contracts` 不再表达 single-agent runtime assembly。
7. `current_turn_context` 无 runtime control 泄露。
8. 工具调用协议有统一 guard。
9. runtime 文件产物从 full payload dump 改为 refs/summaries。
10. direct run、TaskGraph node run、GraphModule run、human gate、tool execution、continuation 全部有回归测试覆盖。

## 10. 实施顺序锁定

必须按以下顺序推进，不允许跳到后面先做“局部补丁”：

1. 边界测试与 guards。
2. AgentInvocation 唯一入口。
3. CoordinationRuntime 切断 agent assembly 越界。
4. RuntimeChain 降级。
5. TaskRunLoop 消费 invocation。
6. Tool protocol guard。
7. Runtime 文件与 diagnostics 瘦身。
8. 删除旧壳与重复测试夹具。

每一阶段完成后必须跑对应 focused tests。除非遇到真实阻断，不应只停在某一阶段。

## 11. 2026-05-22 执行记录

本轮已完成的结构性调整：

1. `runtime/agent_assembly` 已成为 agent 装配边界：
   - 新增并使用 `AgentInvocation`。
   - `build_agent_invocation()` 统一产出 assembly、permit、runtime control、model context、task selection。
   - `current_turn_context` / `task_selection` 继续由 boundary helpers 投影，控制态不进入模型上下文。

2. `coordination_runtime` 与 TaskGraph 已切断直接 agent 装配：
   - 图任务继续负责 `NodeExecutionRequest`、`node_work_order`、runtime control summary。
   - 单 agent 装配推迟到 UnitRuntime 执行边界。

3. `runtime_chain` 已降级为任务理解和上下文流水线：
   - 不再接收或返回旧的 full `agent_assembly_contract` 权威对象。
   - direct run 先由 runtime_chain 选择任务语义和 runtime lane，再生成 direct `AgentInvocation`。
   - 显式 TaskGraph/node invocation 会严格约束 agent 身份和 runtime lane。

4. `TaskRunLoop` 已改为消费 invocation：
   - 显式 node invocation 的身份优先于 stale task_selection。
   - direct invocation 不再提前猜测 lane；使用 runtime_chain 解析后的 lane。
   - `agent_runtime_spec` 不再被写入 `agent_assembly_contract_id` / `work_order_id` 这类 assembly 桥接字段。

5. 工具协议守卫已接入：
   - `tool_protocol_guard.py` 存在于 `runtime/execution_engine`。
   - OperationGate deny、missing executor、deny replay、search policy block 等路径都会补齐 tool result 事件。

6. runtime 文件副作用已收缩：
   - `task_contract_built` 事件不再 dump full `agent_invocation` / full `agent_assembly_contract` / full `execution_permit`。
   - full objects 进入 runtime object store，事件只保留 summary 与 refs。
   - 测试里的 `runtime-loop-test/` 根目录副作用已改成 `tmp_path` 并删除已生成目录。

7. 旧壳删除：
   - 删除 `SingleAgentRuntimeAssembly`。
   - 删除 `build_single_agent_runtime_assembly()`。
   - 删除 `agent_assembly_contract_from_runtime_control()`。
   - 删除 continuation assembly fallback helper。
   - 删除 finalizer 从 full assembly 反推 stage request 的旧 helper。
   - 修正旧 health runtime profile 测试期望：保留 `agent:3` 身份，但不恢复旧 runtime profile。

当前保留项：

- `NodeRuntimeAssembly` 保留。它承载 TaskGraph 节点输出、验收、handoff、layered context 等图任务契约，不是 single-agent runtime assembly 权威。
- `build_agent_assembly_contract()` 保留为 `build_agent_invocation()` 的内部装配步骤和边界测试入口。
