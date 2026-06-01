# 单 Agent 控制系统实施蓝图

日期：2026-06-02

状态：核心链路已实施并通过当前回归验收。

实施进度：

- Phase 1-6 已完成：生产路径不再使用独立 route 层；single turn / task_run 的模型动作进入 admission；工具调用统一进入 Runtime Tool Control Plane；TaskExecutor 的调度、恢复和自动续跑由 `TaskExecutorController` 承担；single turn 已具备只读工具观察循环。
- Phase 7 已完成：新增 model-aware context budget policy，按 provider/model/mode/context preset 编译动态上下文预算，并写入 prompt manifest / context window diagnostics；旧的低固定 volatile char budget 不再作为主预算入口。
- Phase 8 已完成：开发执行策略从 environment prompt 移入主 agent 的 task execution work role；environment prompt 只保留资源、工作区、sandbox、artifact、权限边界说明。
- 验收结果：相关 harness/tool/runtime/prompt/cache 回归已通过；残留扫描未发现旧 route、旧 capability plan、TaskRun-owned tool runtime、环境 strategy prompt 或低固定预算回挂核心单 agent 链路。

## 0. 范围

本蓝图只处理单 agent 控制系统：

```text
QueryRuntime
-> single_agent_turn
-> Runtime Tool Control Plane
-> TaskRun lifecycle
-> TaskExecutor scheduling
-> TaskExecutor execution loop
-> ModelActionAdmission
-> ToolAdmission / ToolSupervisor
-> OperationGate
-> ToolRuntime / ToolRegistry / ToolResultProjection
-> RuntimeCompiler / dynamic context / prompt cache accounting
```

不处理：

- GraphHarness。
- graph work order。
- graph node task run。
- 图像生成 direct route。
- 多 agent / subagent 架构重构。

本蓝图不是方向性计划，而是实施前的函数级迁移蓝图。每个结构调整必须有理由、边界、迁移位置、事件/状态契约、删除项、测试和阻断条件。

## 1. 成熟 Agent 对照

### 1.1 要学习的点

Codex / Claude Code 的共同点：

- 有中心 session/query loop。
- 工具和权限有统一 gate/pipeline。
- 工具执行上下文和会话状态由中心 runtime 持有，但工具执行细节不写在 API adapter 中。
- 模型可在普通回合使用稳定工具，不必把所有真实观察都升级成长任务。
- prompt/cache 依赖稳定前缀、稳定工具 schema、稳定消息顺序，而不是手写“prompt cache”逻辑。
- 工具层是 session/turn runtime 的核心控制面，不依附长期任务对象。长期任务只是工具调用的 caller/source 之一。

本地核查依据：

- `..\openai-codex\codex-rs\core\src\codex_thread.rs`：`CodexThread` 承担 submit / next_event / steer / inject 的会话主循环边界。
- `..\openai-codex\codex-rs\core\src\session\session.rs`：`Session` 持有 active turn、input queue、services、tool approval、network approval、model client、environment manager 等运行态权威。
- `..\openai-codex\codex-rs\core\src\tools\context.rs`：`ToolInvocation` 绑定 `Session`、`TurnContext`、call id、tool name、payload 和 cancellation token；它不以 TaskRun 为根。
- `..\openai-codex\codex-rs\core\src\tools\spec_plan.rs`：`build_tool_router()` 从 `TurnContext` 编译 model-visible specs 和 `ToolRegistry`，工具 schema 与 dispatch registry 同源。
- `..\openai-codex\codex-rs\core\src\tools\registry.rs`：`ToolRegistry` 统一 dispatch、PreToolUse、PostToolUse、telemetry、hook input rewrite 和 tool result projection。
- `..\openai-codex\codex-rs\core\src\tools\orchestrator.rs`：`ToolOrchestrator` 集中处理 approval、sandbox selection、retry semantics、network approval，不挂在某个长期任务结构下面。
- `D:\AI应用\Claude-Code-Source-Study-main\docs\05-对话循环.md`：Claude Code 的 `queryLoop` 是中心对话循环。
- `D:\AI应用\Claude-Code-Source-Study-main\docs\25-架构模式总结.md`：工具注册、工具过滤和权限检查是统一 pipeline，不是普通 turn / 任务 turn 各自绕行。
- `D:\AI应用\Claude-Code-Source-Study-main\docs\16-权限系统.md`：工具调用进入 `hasPermissionsToUseTool()` 权限管线，按权限模式转换 allow/ask/deny。
- `D:\AI应用\Claude-Code-Source-Study-main\docs\07-Prompt-Cache.md`：工具定义是 prompt cache key 的组成部分，工具 schema 必须稳定排序和稳定序列化。

### 1.2 不学习的点

不建设独立动态 route / entrypoint / 用户意图分类层。

当前 `TurnRoute/build_turn_route()` 只包装：

```text
single_agent_turn
explicit_contract_task
blocked_runtime
```

它没有权限、执行、编译、调度、状态恢复权威。成熟 agent 也没有对应目标层。它应被内联删除，只保留短期 public event 兼容投影。

禁止项：

- 不允许根据用户文本关键词决定 single turn / task turn / blocked。
- 不允许根据工具名关键词决定入口。
- 不允许根据 `source`、`runtime_entrypoint`、`contract_dispatch_source` 这类字符串白名单决定入口。
- explicit contract 只能由结构化合同对象和系统签发标记共同决定；如果上游没有系统签发标记，应修上游契约生产者，而不是在 QueryRuntime 中猜测。

## 2. 当前单 Agent 链路审计

### 2.1 QueryRuntime

文件：`backend/query/runtime.py`

当前职责：

- `__init__()`
  - 构造 `SingleAgentRuntimeHost`。
  - 绑定 prompt accounting ledger。
  - 创建 `AgentRuntimeServices`。
  - 创建 `GraphHarness`。本蓝图不处理 graph。
  - 调用 `recover_interrupted_task_executors()`。
  - `runtime_components["query_runtime"]` 当前错误标成 `adapter_only`。
- `astream()`
  - 装配 history。
  - 处理 active turn steer。
  - 提交用户消息。
  - 启动 active turn。
  - 调用图像 direct route。本蓝图不改。
  - 调用 `assemble_runtime()`。
  - 调用 `build_turn_route()`。
  - 分发 single turn / explicit contract / blocked。
- 当前 `build_turn_route()` 对 explicit contract 的判断读取 `source`、`runtime_entrypoint`、`contract_dispatch_source` 字符串，这是 route 噪声的实际风险点。
- `_run_single_agent_turn()`
  - 闭包 `start_task()` 直接把 `schedule_task_run_executor` 传给 lifecycle。
  - 闭包 `apply_active_work_control()` 处理 active work。
  - 调 `run_single_agent_turn()`。
- `_run_explicit_contract_task_turn()`
  - 构造 explicit contract action request。
  - 调 lifecycle。
- `schedule_task_run_executor()`
  - 查 task run。
  - 判断 claimed/executable。
  - append `task_run_executor_scheduled`。
  - append `step_summary_recorded`。
  - 更新 task status/diagnostics。
  - spawn `_runner()`。
  - `_runner()` 调 `execute_task_run()`，并 auto continue。
- `execute_task_run()`
  - facade 到 `harness.loop.task_executor.execute_task_run()`。

判断：

- 保留 `QueryRuntime` 作为主入口。
- 移除 `TurnRoute` 内部依赖。
- QueryRuntime 只能根据结构化运行事实做分支：
  - runtime assembly 是否 blocked。
  - 是否存在非空结构化合同。
  - 该合同是否由系统显式签发。
- QueryRuntime 不得根据用户消息、prompt 文本或 `source` 字符串白名单做语义路由。
- 将 executor schedule 实现迁到 controller，但保留 QueryRuntime facade。

### 2.2 single_agent_turn

文件：`backend/harness/loop/single_agent_turn.py`

当前职责：

- `compile_single_agent_turn_packet()`。
- 发起模型调用。
- 解析 provider native tool calls。
- `request_task_run` 直接调用 lifecycle。
- `ask_user` / `block` 直接 commit final message。
- `active_work_control` 单独解析，不是 `ModelActionRequest`。
- 没有调用 `admit_model_action()`。
- 没有通用 tool observation follow-up。

判断：

- single turn 必须统一走 admission。
- active_work_control 要么纳入 `ModelActionRequest` 类型，要么明确作为 control action 走同一 admission 事件。
- single turn 可执行 read-only tool；side-effect 意图必须升级为 TaskRun/approval 后执行，但工具控制面本身不归 TaskRun。

### 2.3 TaskRun lifecycle

文件：`backend/harness/loop/task_lifecycle.py`

当前职责：

- `contract_from_action_request()`。
- `start_task_lifecycle()` 创建 TaskRun / AgentRun / lifecycle。
- `start_task_lifecycle_from_action_request()`。
- `start_task_lifecycle_from_contract()`。
- launch supervision。
- 调 `schedule_task_run_executor()`。
- public final answer 中注入 `turn_route.to_dict()`。

判断：

- lifecycle 是合理权威，不移动。
- `turn_route` 参数应删除，改为可选 `turn_context_projection` 或直接不传。
- schedule callback 保留，但最终会委托 TaskExecutorController。

### 2.4 TaskExecutor

文件：`backend/harness/loop/task_executor.py`

当前职责：

- `recover_interrupted_task_executors()`。
- `execute_task_run()`。
- claim executor sequence。
- compile task execution packet。
- model call。
- parse model action。
- `admit_model_action(... side_effect_policy="runtime_authorized")`。
- `_execute_task_tool_call()` 中创建 `RuntimeDirective`、`RuntimeActionRequest`、`ResourcePolicy`。
- `_execute_task_tool_call()` 中执行 `runtime_host.operation_gate.check()`。
- `ToolRuntimeExecutor.run()`。
- observation / artifact / closeout。

判断：

- `execute_task_run()` 是执行循环权威，保留。
- scheduling 不该在 QueryRuntime 大方法里。
- admission 阶段必须验证 action type、runtime tool set、side-effect policy。
- 当前 OperationGate 终裁在 `_execute_task_tool_call()`，这是工具层依附 TaskRun 的直接表现。
- 目标是把 OperationGate 终裁迁入 `RuntimeToolControlPlane`；TaskExecutor 只投影 task-specific resource/sandbox context，不再拥有工具权限终裁。

### 2.5 RuntimeCompiler / Assembly

文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/assembly.py`
- `backend/harness/runtime/dynamic_context/token_budget.py`

当前事实：

- single turn `available_tools=()`。
- single turn effective capabilities 强制 `may_call_tools=False`、`visible_tool_count=0`。
- assembly 已能根据 visible tools 计算 `may_call_tools`，但 compiler 覆盖为 false。
- dynamic context budget 是固定 char 数：
  - single turn 6000
  - followup 4000
  - task 8000

判断：

- single turn 工具面应在 compiler 层开放 read-only direct tools。
- context budget 需要 provider/model/mode-aware policy。
- 不先做 ToolSearch。Tool catalog/deferred discovery 是后置条件阶段。

### 2.6 Tool Runtime / Tooling

文件：

- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/runtime/tool_runtime/tool_invocation_control.py`
- `backend/runtime/tool_runtime/tool_use_context.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/runtime/tooling/supervisor.py`
- `backend/runtime/tooling/capability_table.py`
- `backend/runtime/tooling/capability_table_builder.py`
- `backend/runtime/capabilities/current_turn_capability_plan.py`
- `backend/capability_system/tool_authorization.py`
- `backend/harness/runtime/assembly.py`
- `backend/harness/loop/task_executor.py`

当前事实：

- `ToolRuntimeExecutor.run()` 是真实工具执行器，但接口要求：
  - `task_run_id`
  - `RuntimeActionRequest`
  - `RuntimeDirective`
  - `OperationExecutionRecord`
  - 可选 `RuntimeExecutionStore`
  - sandbox/file policy
- `_execute_task_tool_call()` 在 `TaskExecutor` 内部创建 `RuntimeDirective`、`RuntimeActionRequest`、`ResourcePolicy`、`OperationExecutionRecord`，再调用 `ToolRuntimeExecutor.run()`。
- `ToolInvocationControlRegistry` 已经支持 `caller_kind="agent_turn" | "task_run" | "graph_node" | "direct_route"`，但主执行器接口仍以 TaskRun 为中心。
- `ToolUseContext` 已有 `caller_kind`、`caller_ref`、`turn_id`、`task_run_id`、`tool_invocation_id`、`idempotency_key` 字段，说明底层上下文并不需要绑定 TaskRun。
- `ToolSupervisor` / `ToolCapabilityTable` 已经表达“工具能力表 + preflight + OperationGate”的方向，但目前只被测试覆盖，没有接入 single agent 主链。
- `CurrentTurnCapabilityPlan` 与 `harness.runtime.assembly` 都在做可见工具/可调度工具投影，存在重复权威。

判断：

- 工具层现在确实被 TaskRun 执行路径绑住了，这是结构性问题，不是只读工具 helper 能解决的局部问题。
- 正确方向不是给 single turn 伪造 TaskRun，也不是复制一个轻量 executor；正确方向是抽出 Runtime/Session 级工具控制面。
- TaskRun 应只是 `ToolInvocation.caller_kind="task_run"` 的一种 caller，不应拥有工具 registry、admission、supervision、execution、result projection 的主权。
- `ToolSupervisor` / `ToolCapabilityTable` 的设计方向更接近目标，但不能作为旁路继续悬空；要么接入主链成为唯一工具准入/监督层，要么删除。
- `CurrentTurnCapabilityPlan` 如果不能并入统一 `ToolCapabilityPlan`，应作为旧实验结构删除，避免两套工具可见性判断。

## 3. 目标单 Agent 权威链

```text
QueryRuntime.astream
-> RuntimeAssembly
-> RuntimeToolPlan
-> QueryRuntime structured runtime-state branch
-> RuntimeCompiler
-> model call
-> ModelActionRequest
-> ModelActionAdmission
-> ToolInvocationRequest | control execution | TaskRun lifecycle
-> RuntimeToolControlPlane
-> ToolSupervisor
-> OperationGate
-> ToolRuntimeExecutor
-> ToolObservation / ToolResultProjection
-> TaskExecutorController.schedule
-> TaskExecutor.execute_task_run
-> ModelActionAdmission
-> RuntimeToolControlPlane
-> closeout
```

明确不新增：

- `RuntimeEntrypointDecision`
- `backend/harness/runtime/entrypoint.py`
- 新 route 层
- 用户文本关键词路由
- `source` 字符串白名单路由

明确保留：

- `QueryRuntime` 主入口。
- `SingleAgentRuntimeHost` 状态和 gate。
- `TaskRun lifecycle`。
- `TaskExecutor.execute_task_run()`。
- `OperationGate` 终裁。
- `ToolRuntimeExecutor` 的工具调用、sandbox、validation、result envelope 能力。
- `ToolInvocationControlRegistry` 的 invocation tracking / cancellation 能力。
- `ToolSupervisor` / `ToolCapabilityTable` 的方向，但必须接入主链或删除。

明确新增：

- `RuntimeToolControlPlane`，作为 session/runtime 级工具控制面。
- `RuntimeToolPlan`，作为每个 invocation 的稳定工具 schema + dispatch registry + capability table。
- `ToolInvocationRequest`，作为 caller-agnostic 工具调用请求。
- `TaskExecutorController`，只管 schedule/resume/recover/auto-continuation。
- `ContextBudgetPolicy`，只管预算计算。

明确禁止的替代方案：

- `single_turn_readonly_tool_executor.py` 这种只服务普通回合的旁路 executor。
- 伪造 TaskRun / RuntimeDirective / ExecutionRecord 来让 single turn 使用工具。

## 4. 数据契约

### 4.1 Admission 输入

扩展 `admit_model_action()` 入参：

```python
packet_allowed_action_types: tuple[str, ...] = ()
invocation_kind: str = ""
runtime_tool_plan_ref: str = ""
runtime_visible_tool_names: tuple[str, ...] = ()
runtime_dispatchable_tool_names: tuple[str, ...] = ()
side_effect_policy: Literal["deny", "needs_contract", "allow"] = "deny"
permission_mode: str = "default"
```

输入迁移结果：

```python
definitions_by_name
allowed_tool_names
runtime_profile
side_effect_policy
```

必须删除的 admission 入参和内部逻辑：

```python
operation_gate
operation_gate_mode
directive_ref
workspace_root  # 作为 OperationGate 上下文输入时删除；作为普通诊断事实不在 admission 中使用
_check_operation_gate()
ResourcePolicy  # admission 不再构造资源策略
OperationGatePipelineContext  # admission 不再构造 gate 上下文
```

迁移规则：

- 旧副作用工具布尔开关已删除，避免“允许副作用工具”的模糊权限语义。
- task execution 使用 `side_effect_policy="runtime_authorized"`。
- single turn 使用 `side_effect_policy="requires_task_run"`。
- `admit_model_action()` 只决定“模型动作是否允许进入下一步”，不做资源权限终裁。
- single turn read-only observation 经 `RuntimeToolControlPlane` 进入 OperationGate。
- task execution 不在 admission 中构造 task resource policy；由 `RuntimeToolControlPlane` 统一构造并交 OperationGate 终裁。
- `permission_mode` 只作为后续 `ToolInvocationRequest` 的输入事实传递，不在 admission 内触发 gate。

### 4.2 Admission 输出

`AdmissionDecision.to_dict()` 增加：

```python
{
  "invocation_kind": "...",
  "action_type": "...",
  "allowed_action_types": [...],
  "tool_name": "...",
  "operation_id": "...",
  "side_effect_policy": "...",
  "gate_checked": true|false,
  "gate_stage": "not_applicable|deferred_to_tool_control_plane|denied_before_gate",
}
```

兼容：

- 保留 `decision`、`system_reason`、`resource_errors`、`contract_errors`。
- 不删除现有字段。

### 4.3 TaskExecutorController 输出

`schedule()` 返回：

```python
{
  "ok": bool,
  "scheduled": bool,
  "task_run_id": str,
  "reason": str,
  "scheduler": str,
  "background_task_name": str,
  "recovered_from": str,
}
```

必须保持兼容现有调用检查：

- `ok`
- `scheduled`
- `reason`
- `task_run_id`

### 4.4 Public event 兼容

短期保留：

- `turn_route_decided`
- `turn_route`
- `single_agent_turn_started.turn_route`

同时新增：

- `runtime_branch_decided`
- `runtime_branch`
- `single_agent_turn_started.runtime_branch`

迁移规则：

- `turn_route` 不再来自 `TurnRoute` 类，只由 `QueryRuntime` 临时投影。
- `turn_route` 只是迁移期 public projection，不是内部架构概念。
- 前端和 API projection 必须改读 `runtime_branch`。
- 最终验收时删除 `turn_route_decided` 和所有 `turn_route` payload，除非用户另行要求外部 API 兼容窗口。

删除条件：

- 前端监控和 API projection 已改为读取 `runtime_branch` 或不依赖该字段。
- 测试覆盖旧字段仍可兼容或已删除。

### 4.5 RuntimeToolPlan

新增 runtime 级工具计划，替代 scattered visible-tools 判断。

```python
RuntimeToolPlan:
  plan_id: str
  session_id: str
  turn_id: str
  agent_invocation_id: str
  invocation_kind: "single_agent_turn" | "task_execution" | "tool_followup"
  model_visible_tools: tuple[dict[str, Any], ...]
  dispatchable_tool_names: tuple[str, ...]
  capability_table: dict[str, Any]
  operation_authorization: dict[str, Any]
  schema_hash: str
  registry_hash: str
  diagnostics: dict[str, Any]
```

约束：

- `model_visible_tools` 与 dispatch registry 必须同源。
- 排序必须稳定，服务 prompt cache。
- single turn、task execution 共用同一 plan 数据结构。
- task contract / environment / profile 只能影响 plan 的输入，不能让 TaskRun 拥有工具 registry。

### 4.6 ToolInvocationRequest

新增 caller-agnostic 工具调用请求。

```python
ToolInvocationRequest:
  invocation_id: str
  caller_kind: "agent_turn" | "task_run"
  caller_ref: str
  session_id: str
  turn_id: str
  task_run_id: str = ""
  agent_run_id: str = ""
  action_request_ref: str
  packet_ref: str
  tool_name: str
  tool_call_id: str
  tool_args: dict[str, Any]
  operation_id: str
  tool_plan_ref: str
  admission_ref: str
  permission_mode: str
  caller_resource_scope: dict[str, Any]
  sandbox_scope: dict[str, Any]
  file_scope: dict[str, Any]
  requested_constraints: dict[str, Any]
```

约束：

- `task_run_id` 只在 `caller_kind="task_run"` 时必填。
- `RuntimeToolControlPlane.invoke()` 只接受 `ToolInvocationRequest`，不接受裸 dict 工具调用。
- single turn 不允许伪造 TaskRun；其 caller 是 `agent_turn`。
- task execution 不再在 `_execute_task_tool_call()` 中独占构造所有工具执行结构；它只负责把 task context 投影成 `ToolInvocationRequest`。
- `ToolInvocationRequest` 不携带最终 `ResourcePolicy`。最终 `ResourcePolicy` 只能由 `RuntimeToolControlPlane` 根据 `RuntimeToolPlan`、caller scope、permission mode 和 tool contract 构造。

### 4.7 ToolObservation

工具结果统一返回 `ToolObservation`，再由调用方决定是否继续模型回合、写 TaskRun observation 或收口。

```python
ToolObservation:
  observation_id: str
  invocation_id: str
  caller_kind: str
  caller_ref: str
  tool_name: str
  operation_id: str
  status: "ok" | "error" | "denied" | "needs_approval" | "needs_contract"
  text: str
  result_ref: str
  result_envelope: dict[str, Any]
  operation_gate: dict[str, Any]
  execution_receipt: dict[str, Any]
  artifact_refs: tuple[dict[str, Any], ...]
  diagnostics: dict[str, Any]
```

约束：

- TaskRun observation 是 `ToolObservation` 的投影，不是工具层唯一输出格式。
- single turn follow-up 使用同一 `ToolObservation` 投影。
- public event、ledger、prompt accounting 都引用 `invocation_id` / `observation_id`，避免用 TaskRun id 当工具调用主键。

## 5. 分阶段实施蓝图

### Phase 1：纠正 QueryRuntime 主入口和 route 噪声

理由：

- 这是所有后续迁移的前提。
- 不能一边说不保留 route，一边继续新增 entrypoint 层。
- 当前 `turn_router.py` 使用 `source` / `runtime_entrypoint` / `contract_dispatch_source` 字符串白名单判断 explicit contract，这违反“禁止关键词/字符串路由”。

修改：

1. `backend/query/runtime.py`
   - `runtime_components["query_runtime"]` 从 `adapter_only` 改为 `application_runtime_facade`。
   - trace metadata `query_runtime_role` 同步改为 `application_runtime_facade`。
   - 删除 `from harness.routing import TurnRoute, build_turn_route` 的生产依赖。
   - 在 `astream()` 中只做结构化运行状态分支：
     - runtime assembly blocked -> blocked runtime。
     - 结构化合同存在且系统显式签发 -> explicit contract。
     - 其他情况 -> single turn。
   - 增加本地 helper：
     - `_runtime_branch_projection(...) -> dict`
     - `_runtime_is_blocked(...) -> bool`
     - `_system_issued_explicit_contract_payload(...) -> dict`
   - public event `turn_route_decided` 继续发，但 payload 来自 projection。
   - `_system_issued_explicit_contract_payload(...)` 只能读取：
     - `task_selection["task_contract"]`
     - `task_selection["task_contract_seed"]`
     - `task_selection["engagement_contract"]`
     - `assembly_payload["engagement_contract"]`
     - `task_selection["system_issued_contract"] is True`
     - `engagement_contract["system_issued"] is True`
   - 禁止读取 `request.message`、prompt 文本、工具名、`source`、`runtime_entrypoint`、`contract_dispatch_source` 来决定入口。

2. `backend/harness/loop/single_agent_turn.py`
   - `turn_route` 参数改为 `runtime_branch: dict[str, Any]`。
   - event 中短期仍输出 `"turn_route": runtime_branch`。
   - `answer_source` 去掉 `harness.route.*`，改为 `harness.single_agent_turn.*`。

3. `backend/harness/loop/task_lifecycle.py`
   - `turn_route` 参数改为 `runtime_branch: dict[str, Any] | None = None`。
   - 所有 `turn_route.to_dict()` 改为 `_public_runtime_branch(runtime_branch)`。

4. `backend/harness/routing/turn_router.py`
   - 本阶段不删除文件，先确保生产路径不 import。
   - 下一阶段若无引用再删除。
   - 删除或停止使用 `_has_system_issued_explicit_contract()` 中的 `source in {...}` 判断。

测试：

```powershell
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py -q
python -m pytest backend/tests/active_turn_authority_regression.py -q
```

阻断条件：

- chat 普通问答事件缺失。
- explicit contract task 不能启动。
- active turn steer 行为变化。

删除项：

- 内部 `TurnRoute` 类型依赖。
- 内部 `build_turn_route()` 调用。
- `source` / `runtime_entrypoint` / `contract_dispatch_source` 字符串白名单入口判断。

保留项：

- public `turn_route` event 兼容字段。

### Phase 2：统一 single turn admission

理由：

- 当前 single turn native action 直接执行，是控制系统最大分叉。

修改：

1. `backend/harness/loop/model_action_protocol.py`
   - 方案 A：扩展 `ModelActionType` 加入 `active_work_control`。
   - 方案 B：保留 active work payload，但统一记录 admission。
   - 推荐 A，因为这能让所有模型动作共用一个协议。
   - 新增字段：
     - `active_work_control: dict[str, Any] = field(default_factory=dict)`

2. `backend/harness/loop/single_agent_turn.py`
   - `_active_work_control_from_native_tool_calls()` 改为返回 `ModelActionRequest(action_type="active_work_control")`。
   - `_action_request_from_native_tool_calls()` 覆盖 ask/block/request_task_run/active_work_control。
   - action_request 生成后立即调用 `admit_model_action()`。
   - append event：
     - `model_action_admission_checked`
     - refs 包含 `turn_ref`、`action_request_ref`、`runtime_invocation_packet_ref`
   - admission deny/invalid/needs_contract 统一收口为 final/error event。
   - allow 后再执行 request_task_run / ask_user / block / active_work_control。

3. `backend/harness/loop/admission.py`
   - 检查 `packet_allowed_action_types`。
   - 如果 action 不在 allowed actions，返回 deny：
     - `system_reason="action_not_allowed_by_packet"`
   - 对非 tool action 不跑 OperationGate。
   - request_task_run 继续检查 task lifecycle policy 和 contract seed。

测试：

```powershell
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py -q
python -m pytest backend/tests/model_response_runtime_regression.py -q
```

新增/修改测试场景：

- single turn `request_task_run` 被 `task_lifecycle_policy.request_task_run=False` 拦截，不创建 TaskRun。
- single turn `ask_user` 有 admission event。
- single turn `block` 有 admission event。
- active work control 有 admission event。

阻断条件：

- request_task_run 没有 contract 仍能启动任务。
- allowed actions 不生效。
- admission 失败后仍执行 action。

### Phase 3：Runtime Tool Control Plane

理由：

- 当前工具层依附 TaskRun：`ToolRuntimeExecutor.run()` 必须拿 `task_run_id`、`RuntimeDirective`、`RuntimeActionRequest`、`OperationExecutionRecord`。
- 这会迫使普通 single turn 调工具时伪造任务状态，或者另写旁路 executor。两者都不成熟。
- 成熟 agent 的工具层是 Session/Turn runtime 级控制面：工具 schema、registry、permission pipeline、sandbox/orchestrator、result projection 都围绕 turn invocation，而不是围绕长期任务对象。

新增文件：

- `backend/runtime/tool_runtime/tool_invocation_request.py`
- `backend/runtime/tool_runtime/tool_control_plane.py`
- `backend/runtime/tool_runtime/tool_observation.py`
- `backend/harness/runtime/tool_plan.py`

目标结构：

```text
RuntimeAssembly
-> RuntimeToolPlan
   -> model_visible_tools
   -> dispatchable_tool_names
   -> ToolCapabilityTable
   -> schema_hash / registry_hash

ModelActionRequest(tool_call)
-> ModelActionAdmission
-> ToolInvocationRequest
-> RuntimeToolControlPlane.invoke()
-> ToolSupervisor
-> OperationGate
-> ToolRuntimeExecutor core dispatch
-> ToolObservation
```

设计决策：

- `RuntimeToolControlPlane` 属于 `SingleAgentRuntimeHost` / runtime services，不属于 `TaskExecutor`。
- `TaskExecutor` 和 `single_agent_turn` 都只能通过 `RuntimeToolControlPlane.invoke()` 调工具。
- `ToolRuntimeExecutor` 保留底层 validation / adapter / sandbox / envelope 能力，但不能继续要求 TaskRun 作为唯一 caller。
- `ToolSupervisor` 接入主链，负责 capability table membership、preflight、OperationGate 结果转换。
- `ToolCapabilityTable` 成为工具可见性和可调度性的唯一 runtime 级权威。
- `CurrentTurnCapabilityPlan` 与 `harness.runtime.assembly` 的工具投影必须合并到 `RuntimeToolPlan`；不能继续两套判断。

修改：

1. `backend/harness/runtime/tool_plan.py`
   - 从 `RuntimeAssembly`、profile、environment、task contract、tool definitions 构建 `RuntimeToolPlan`。
   - 复用并收敛 `ToolCapabilityTable`。
   - 输出稳定排序的 `model_visible_tools`。
   - 输出 `schema_hash` / `registry_hash` 给 prompt cache diagnostics。

2. `backend/harness/runtime/assembly.py`
   - 不再单独拥有工具可见性最终权威。
   - 只提供 tool plan 的输入事实：
     - profile allowed/blocked operations。
     - environment policy。
     - task requested operations。
     - selected skills。
   - `available_tools` 字段短期保留为 `RuntimeToolPlan.model_visible_tools` 的兼容投影。

3. `backend/runtime/capabilities/current_turn_capability_plan.py`
   - 合并进 `RuntimeToolPlan` 或标记删除。
   - 如果保留，只能作为 `RuntimeToolPlan` 的内部 helper，不能被主链以外直接调用。

4. `backend/runtime/tool_runtime/tool_invocation_request.py`
   - 定义 `ToolInvocationRequest`。
   - 支持 `caller_kind="agent_turn"` 和 `caller_kind="task_run"`。
   - 禁止要求 `task_run_id` 对所有 caller 必填。

5. `backend/runtime/tool_runtime/tool_observation.py`
   - 定义 `ToolObservation`。
   - 提供：
     - `to_task_observation()`
     - `to_turn_observation_event()`
     - `to_model_followup_context()`

6. `backend/runtime/tool_runtime/tool_control_plane.py`
   - 新增 `RuntimeToolControlPlane.invoke(request) -> ToolObservation`。
   - 内部顺序固定：
     - capability table membership。
     - tool definition / runtime availability。
     - input validation / preflight。
     - OperationGate。
     - invocation registry start/complete/fail。
     - `ToolRuntimeExecutor` core dispatch。
     - result envelope normalization。
   - 所有失败必须 fail closed，返回 `ToolObservation(status=...)`，不得裸异常穿透到模型循环。

7. `backend/runtime/tool_runtime/tool_executor.py`
   - 拆出 caller-agnostic core：
     - `prepare_tool(...)`
     - `validate_tool_input(...)`
     - `dispatch_tool(...)`
     - `build_result_envelope(...)`
   - `run(task_run_id=...)` 短期保留为 task compatibility wrapper，但内部调用 control plane 或 core dispatch。
   - 删除“TaskRun 是工具执行唯一入口”的接口假设。

8. `backend/harness/runtime/services.py` / `backend/query/runtime.py`
   - 在 runtime services / host 中挂载 `RuntimeToolControlPlane`。
   - `TaskExecutorServices` 不再把 `ToolRuntimeExecutor` 当唯一工具入口。

9. `backend/runtime/tooling/supervisor.py`
   - 接入 `RuntimeToolControlPlane`。
   - 返回统一 supervision decision，映射到 `ToolObservation.status`。

测试：

```powershell
python -m pytest backend/tests/tool_capability_table_regression.py -q
python -m pytest backend/tests/tool_supervisor_regression.py -q
python -m pytest backend/tests/sandbox_tool_runtime_regression.py -q
python -m pytest backend/tests/tool_result_projection_regression.py -q
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py -q
```

新增/修改测试场景：

- `caller_kind="agent_turn"` 可执行 read-only 工具，不创建 TaskRun。
- `caller_kind="task_run"` 工具调用仍保留 execution receipt、sandbox、artifact refs。
- 工具不在 `RuntimeToolPlan.dispatchable_tool_names` 中时，control plane deny，executor 不执行。
- OperationGate deny 时 `ToolObservation.operation_gate` 完整。
- side-effect 工具在 single turn 中返回 `needs_contract` / `needs_approval`，不直接执行。
- 工具 schema hash 在同一工具集合下稳定。
- `CurrentTurnCapabilityPlan` 不再作为独立主链入口存在。

阻断条件：

- single turn 为了调工具伪造 TaskRun。
- TaskExecutor 绕过 `RuntimeToolControlPlane` 直接调用 `ToolRuntimeExecutor.run()`。
- 工具可见性仍由 `assembly.available_tools` 和 `CurrentTurnCapabilityPlan` 两套独立逻辑决定。
- OperationGate 不再执行。
- 不可见工具进入底层 executor。

### Phase 4：TaskExecutor admission 契约修正

理由：

- task execution 的 action admission 仍需要验证 action type、tool membership、side-effect policy。
- OperationGate 已下沉到 `RuntimeToolControlPlane`，TaskExecutor 不再自己终裁工具资源权限。

修改：

1. `backend/harness/loop/admission.py`
   - 支持：
     - `packet_allowed_action_types`
     - `invocation_kind`
     - `runtime_tool_plan_ref`
     - `runtime_visible_tool_names`
     - `runtime_dispatchable_tool_names`
     - `side_effect_policy`
   - 对 tool_call 只做模型动作准入：
     - action type allowed。
     - tool in RuntimeToolPlan。
     - side-effect policy allowed for invocation kind。
   - 不构造 `ResourcePolicy`。
   - 不调用 OperationGate。

2. `backend/harness/loop/task_executor.py`
   - 调 admission 时传：
     - `packet_allowed_action_types=tuple(compilation.packet.allowed_action_types)`
     - `invocation_kind="task_execution"`
     - `runtime_tool_plan_ref=runtime_tool_plan.plan_id`
     - `runtime_visible_tool_names=tuple(tool["name"] for tool in runtime_tool_plan.model_visible_tools)`
     - `runtime_dispatchable_tool_names=runtime_tool_plan.dispatchable_tool_names`
     - `side_effect_policy="allow"`
   - `execution_context.admission_ref` 使用真实 admission id。
   - tool_call allow 后构造 `ToolInvocationRequest(caller_kind="task_run")`，交给 `RuntimeToolControlPlane.invoke()`。
   - `_execute_task_tool_call()` 只保留 task-specific projection，不再拥有 OperationGate 终裁。

测试：

```powershell
python -m pytest backend/tests/tool_result_projection_regression.py -q
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py -q
```

新增/修改测试场景：

- task model 请求不可见工具，admission deny，control plane 不执行。
- OperationGate deny 时 task observation 包含 gate payload。
- execution record 的 admission_ref 指向真实 admission id。

阻断条件：

- TaskExecutor 仍直接调用 `runtime_host.operation_gate.check()` 执行工具终裁。
- 不可见工具进入 `RuntimeToolControlPlane` core dispatch。
- admission 事件缺失。

### Phase 5：TaskExecutorController

理由：

- `QueryRuntime.schedule_task_run_executor()` 太多后台 runner 生命周期细节。
- 这是单 agent 控制系统的真实调度权威，应独立于 QueryRuntime 主循环。

新增文件：

- `backend/harness/loop/task_executor_controller.py`

新增类：

```python
class TaskExecutorController:
    def __init__(self, *, runtime_host: Any, execute_task_run: Callable[..., Awaitable[dict[str, Any]]]) -> None: ...
    def schedule(self, task_run_id: str, *, scheduler: str, turn_id: str = "", max_steps: int = 12) -> dict[str, Any]: ...
    def recover_scheduled(self, task_run_id: str, *, scheduler: str, max_steps: int = 12) -> dict[str, Any]: ...
```

迁移函数/逻辑：

从 `QueryRuntime.schedule_task_run_executor()` 移入 controller：

- task_run not found。
- executor claimed 判断。
- executable 判断。
- append `task_run_executor_scheduled`。
- append `step_summary_recorded`。
- state_index.upsert running diagnostics。
- `_runner()` loop。
- `_task_executor_should_auto_continue(...)`。
- `_mark_query_scheduled_task_failed(...)` 改名为 `_mark_scheduled_task_failed(...)`。

保留在 `QueryRuntime`：

```python
def schedule_task_run_executor(...):
    return self.task_executor_controller.schedule(...)
```

API 改动：

- `backend/api/orchestration_harness.py`
  - execute API 中 scheduled claim recovery 不再手写 `spawn_background_task(_recover_scheduled_executor())`。
  - 改调 `runtime.query_runtime.recover_scheduled_task_run_executor(...)` 或 `schedule_task_run_executor(..., scheduler="task_run_execute_api_recover")`，具体以 controller 方法为准。

测试：

```powershell
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py -q
python -m pytest backend/tests/active_turn_authority_regression.py -q
```

新增/修改测试场景：

- already running 返回兼容 reason。
- scheduled claim recovery 走 controller。
- auto continuation 保持原事件 `task_run_executor_rescheduled`。
- runner exception 标记 task failed/block 状态与旧行为一致。

阻断条件：

- API execute/resume 返回字段不兼容。
- background task 未启动。
- scheduled/recovered 状态无法追踪。

### Phase 6：single turn tool loop

理由：

- 当前普通 turn 没有真实观察能力，导致小任务被迫升级 TaskRun。
- 成熟 agent 普通回合可用稳定只读工具。
- Phase 3 后工具层已经脱离 TaskRun，single turn 不需要伪造任务状态。

前置条件：

- Phase 2 admission 完成。
- Phase 3 Runtime Tool Control Plane 完成。
- Phase 4 task admission 不回退。

修改：

1. `backend/harness/runtime/compiler.py`
   - single turn 不再强制 `available_tools=()`。
   - 从 `RuntimeToolPlan.model_visible_tools` 取 read-only tools。
   - `_single_agent_turn_effective_control_capabilities()`：
     - `may_call_tools=True` 当存在 read-only visible tools。
     - `visible_tool_count=len(read_only_tools)`。
   - `_single_agent_turn_output_contract()` 允许 `tool_call`，但禁止 side-effect。

2. `backend/harness/runtime/tool_plan.py`
   - 明确 single turn visible tools 策略：
     - 只读。
     - 已授权。
     - 稳定排序。
   - 不做关键词筛选。

3. `backend/harness/loop/single_agent_turn.py`
   - 增加 bounded loop：
     - max_tool_iterations 默认 3。
     - model response -> action_request。
     - admission。
     - 构造 `ToolInvocationRequest(caller_kind="agent_turn")`。
     - 调 `RuntimeToolControlPlane.invoke()`。
     - observation 写入 runtime_objects / event_log。
     - compile follow-up packet 或将 observation 作为 dynamic context 再调用模型。
   - side-effect tool admission 返回 needs_contract，并转成 request_task_run 或 ask_user，不直接执行。

4. 工具执行：
   - 只能通过 `RuntimeToolControlPlane.invoke()`。
   - 不新增 `single_turn_readonly_tool_executor.py`。
   - 不伪造 TaskRun / RuntimeDirective / ExecutionRecord。

测试：

```powershell
python -m pytest backend/tests/model_response_runtime_regression.py -q
python -m pytest backend/tests/tool_result_projection_regression.py -q
```

新增测试场景：

- 普通 turn 调 read-only tool 后回答。
- 普通 turn 调 write/edit/terminal 返回 needs_contract，不执行工具。
- tool loop 超过 max iterations 后 block 或 ask_user。
- observation 进入 prompt 后仍能生成 final answer。

阻断条件：

- side-effect 工具绕过 TaskRun。
- 工具 observation 没有 event。
- follow-up loop 无界。
- single turn 直接调用 `ToolRuntimeExecutor.run()`。
- single turn 构造假 TaskRun。

### Phase 7：model-aware context budget

理由：

- 当前 token budget 是固定 char 数，不支持 DeepSeek normal/thinking/max/long-context 差异。

新增文件：

- `backend/harness/runtime/context_budget_policy.py`

契约：

```python
ContextBudgetPolicyInput:
  provider: str
  model: str
  mode: "normal" | "thinking" | "max"
  context_window_tokens: int
  explicit_long_context: bool

ContextBudgetPolicy:
  stable_prefix_budget_tokens
  tool_schema_budget_tokens
  deferred_index_budget_tokens
  volatile_state_budget_tokens
  recent_history_budget_tokens
  observation_budget_tokens
  fallback_reason
```

修改：

- `dynamic_context/token_budget.py`
  - `budget_for_invocation()` 接受 model/budget policy。
  - char budget 只作为 fallback。
- `compiler.py`
  - segment plan metadata 增加 context budget report。
- `prompt_accounting` 相关 ledger
  - 保留原统计，增加 model/mode/preset 字段。

测试：

```powershell
python -m pytest backend/tests/deepseek_prompt_cache_diagnostics_test.py -q
python -m pytest backend/tests/prompt_accounting_ledger_test.py -q
python -m pytest backend/tests/prompt_cache_prefix_tier_regression.py -q
```

新增测试场景：

- normal/thinking/max 预算不同。
- 未显式 long-context 不启用 1M。
- 未知模型 fallback 有 warning。

阻断条件：

- 默认启用 DeepSeek 1M。
- budget report 缺失导致缓存诊断不可解释。

### Phase 8：environment / strategy prompt 拆分

理由：

- environment 是资源边界，不应携带 agent 策略。
- 这会影响 single turn 和 task execution 的 prompt 稳定性。

修改：

- `backend/task_system/environments/default_environments.py`
- `backend/agent_system/profiles/runtime_profile_registry.py`
- `backend/prompt_library/registry.py`
- `backend/prompt_library/packs.py`

迁移：

- environment prompt 保留 workspace/sandbox/artifact/storage/permission boundary。
- strategy prompt 移入 profile / invocation prompt pack / task contract prompt refs。
- compiler 只按结构 refs 装配，不按文本判断。

测试：

```powershell
python -m pytest backend/tests/prompt_library_registry_regression.py -q
python -m pytest backend/tests/prompt_cache_prefix_tier_regression.py -q
```

阻断条件：

- task execution 失去必要执行策略。
- environment 中仍出现角色执行策略。

## 6. 残留链路清理表

清理原则：

- 不是核心链路权威的结构，要么接入唯一权威链，要么删除。
- 兼容字段只能作为短期 public projection，不能在内部继续被读取。
- 旧测试如果只保护旧内部形状，要改成保护目标行为；不能因为测试存在而保留旧链路。
- 本轮不处理 graph 和图像 direct route；它们不应成为单 agent harness 清理的理由或借口。

| 残留结构 / 文件 | 当前隐藏权威或负担 | 目标归属 | 动作 | 删除 / 保留条件 | 验收 |
| --- | --- | --- | --- | --- | --- |
| `backend/harness/routing/turn_router.py` | 以 `TurnRoute` 包装入口，并用 `source` / `runtime_entrypoint` / `contract_dispatch_source` 字符串判断 explicit contract | `QueryRuntime` 结构化 runtime-state branch | Phase 1 先移除生产 import，随后删除文件和 `backend/harness/routing/__init__.py` 导出 | 无生产引用、测试改读 `runtime_branch` 后删除 | `rg "build_turn_route|TurnRoute|harness.routing" backend/query backend/harness backend/api backend/tests` 只允许历史文档命中 |
| public `turn_route_decided` / `turn_route` | 让外部监控继续以 route 概念理解主链 | `runtime_branch_decided` / `runtime_branch` | 迁移期双发；前端/API 改读 `runtime_branch` 后删除旧字段 | 除非用户另行要求外部 API 兼容窗口，否则最终删除 | `rg "turn_route" backend/query backend/harness backend/api backend/tests` 无生产依赖 |
| `harness.route.*` / `harness.routing.*` answer_source 与 diagnostics | 把已删除 route 层继续写进审计和任务起源 | `harness.single_agent_turn.*` / `harness.explicit_contract_task.*` / `query_runtime.runtime_branch.*` | 全量改名；新任务 diagnostics 不再出现 route authority | 旧历史数据不迁移，但新代码不得写入 | 任务创建测试断言新 authority |
| `QueryRuntime.schedule_task_run_executor()` 内部 runner | QueryRuntime 拥有 schedule/recover/auto continuation 细节 | `TaskExecutorController` | 迁入 controller，QueryRuntime 只保留 facade | API 调用和 lifecycle 都走 controller 后，QueryRuntime 内部 runner 删除 | `rg "_runner|_recover_scheduled_executor|task-run-executor" backend/query backend/api` 不再命中旧实现 |
| `backend/api/orchestration_harness.py` scheduled recovery | API 层手写后台恢复，绕过调度权威 | `TaskExecutorController.recover_scheduled()` | API 改调 controller/facade | controller 覆盖 already scheduled/recovery 后删除 API 内联 recovery | execute/resume API 回归测试 |
| `backend/harness/loop/admission.py` `_check_operation_gate()` | Admission 构造 `ResourcePolicy` 并调用 OperationGate，和工具控制面重复终裁 | `RuntimeToolControlPlane` | 删除 `_check_operation_gate()`、`operation_gate` 入参、`ResourcePolicy` import；Admission 只做动作准入 | RuntimeToolControlPlane 接管所有工具 gate 后删除 | `rg "operation_gate|ResourcePolicy|OperationGatePipelineContext" backend/harness/loop/admission.py` 无命中 |
| `backend/harness/loop/task_executor.py` `_execute_task_tool_call()` | TaskExecutor 构造 `RuntimeDirective` / `RuntimeActionRequest` / `ResourcePolicy` 并直接 gate/execute | `RuntimeToolControlPlane` + `ToolInvocationRequest` | 改成 task context projection；工具执行只能调 `RuntimeToolControlPlane.invoke()` | ToolObservation 能投影为 task observation 后删除直接执行分支 | `rg "runtime_host.operation_gate.check|ToolRuntimeExecutor.run|RuntimeDirective|RuntimeActionRequest" backend/harness/loop/task_executor.py` 不再用于工具执行 |
| `backend/runtime/tool_runtime/tool_executor.py` task-only `run()` 接口 | 底层 executor 以 TaskRun 为唯一 caller | caller-agnostic core dispatch | 拆出 validate/dispatch/envelope core；旧 `run()` 只能短期 wrapper | task executor 不直接调用后，wrapper 可删除或仅保留非主链外部契约 | agent_turn/task_run 都通过 control plane 测试 |
| `backend/runtime/capabilities/current_turn_capability_plan.py` | 与 `RuntimeAssembly.available_tools` 重复决定可见/可调度工具 | `RuntimeToolPlan` | 逻辑合并到 `backend/harness/runtime/tool_plan.py`；删除模块和 `runtime/capabilities/__init__.py` 导出 | `search_policy_capability_regression.py` 等测试迁到 RuntimeToolPlan 行为后删除 | `rg "build_current_turn_capability_plan|CurrentTurnCapabilityPlan" backend` 无主链命中 |
| `ToolSupervisor` / `ToolCapabilityTable` 悬空测试层 | 有接近目标的工具监督结构，但未接主链 | `RuntimeToolControlPlane` 内部监督层 | 接入 control plane；若无法接入就删除，不能保留悬空 | 接入后保留为唯一 capability/preflight authority | supervisor 测试改为通过 control plane 覆盖 |
| `SubagentControl` 在 `TaskExecutor` 中直接分支 | 子 agent 工具绕过统一 ToolRuntime/ToolSupervisor/control plane | `RuntimeToolControlPlane` 的工具 handler / special adapter | 本轮不重构 subagent 语义，但要把分发入口从 TaskExecutor 直连迁入 tool control plane | 不处理多 agent 架构；只处理“工具调用入口统一” | `rg "SubagentControl\\(" backend/harness/loop/task_executor.py` 无命中 |
| `SUBAGENT_TOOL_NAMES` 在 TaskExecutor 中硬分支 | 工具名集合控制执行路径，违反统一工具 registry | ToolDefinition / ToolCapabilityTable / adapter registry | 从 executor 分支移除；由 tool registry/handler 解析 | subagent 工具定义保留，但不能决定 harness route | 不再按工具名在 TaskExecutor 分发 |
| `route_hints` / `safe_for_auto_route` 被误用为 harness 路由 | 工具目录关键词可能回流成入口选择 | 工具目录检索元数据 | 允许保留在 capability catalog/search；禁止参与 QueryRuntime branch 或 TaskExecutor 分发 | 若只用于 catalog/search/permission direct_route，可保留；若用于 harness 入口则删除调用点 | `rg "route_hints|safe_for_auto_route" backend/query backend/harness` 不得出现在入口分支 |
| 旧 regression tests 保护 route / task-only executor / CurrentTurnCapabilityPlan 内部形状 | 测试反向锁死旧结构 | 目标行为测试 | 修改或删除旧测试；新增 runtime_branch、control plane、ToolObservation 行为测试 | 不允许通过降低断言制造绿灯 | 测试名和断言不再要求旧内部结构 |

## 7. 删除清单

必须删除或内联：

- `backend/harness/routing/turn_router.py` 的生产依赖。
- `backend/harness/routing/turn_router.py` 和 `backend/harness/routing/__init__.py`，在无生产/测试引用后删除。
- `TurnRoute` 类型在 single agent 主链路中的传递。
- public `turn_route_decided` / `turn_route`，在 frontend/API projection 迁移到 `runtime_branch` 后删除。
- `harness.route.*` answer_source 命名。
- `QueryRuntime.schedule_task_run_executor()` 内部 runner 实现。
- 工具主链对 `CurrentTurnCapabilityPlan` 的直接依赖。
- `backend/runtime/capabilities/current_turn_capability_plan.py`，在逻辑并入 `RuntimeToolPlan` 后删除。
- `backend/runtime/capabilities/__init__.py` 对 `CurrentTurnCapabilityPlan` / `build_current_turn_capability_plan` 的导出。
- `TaskExecutor` 内部直接构造并终裁工具 `RuntimeDirective` / `RuntimeActionRequest` / `ResourcePolicy` 的权威。
- `TaskExecutor` 对 `SubagentControl` 的直接分支调用。
- `admission.py` 中 `_check_operation_gate()` 和 OperationGate / ResourcePolicy 构造逻辑。
- single turn 专用工具 executor 方案。

短期兼容保留：

- public event `turn_route_decided`。
- public payload `turn_route`。

删除条件：

- 前端/API 不再依赖 `turn_route`。
- regression tests 改用 `runtime_branch` 或其他 public status。
- `RuntimeToolControlPlane` 已覆盖 task_run / agent_turn 两类 caller。
- `RuntimeToolPlan` 已覆盖原 `CurrentTurnCapabilityPlan` 的工具可见性/实例过滤能力。

明确不删除：

- `QueryRuntime`。
- `SingleAgentRuntimeHost`。
- `TaskRun lifecycle`。
- `TaskExecutor.execute_task_run()`。
- `OperationGate`。
- `ToolRuntimeExecutor` 的底层工具 dispatch 能力。
- `ToolInvocationControlRegistry`。
- `ToolResultEnvelope`。
- `route_hints` / `safe_for_auto_route` 作为工具目录元数据，但它们不得参与 harness 入口路由或 TaskExecutor 工具分发。

## 8. 运行链路验收矩阵

| 场景 | 必须验证 |
| --- | --- |
| 普通问答 | 不启动 TaskRun，能提交 assistant final message |
| request_task_run | admission 通过后创建 TaskRun，controller schedule |
| task lifecycle policy 禁止 | admission deny，不创建 TaskRun |
| explicit contract | 创建 TaskRun，controller schedule |
| active turn steer | 不进入新普通 turn，不破坏 running executor |
| task execute API | 走 controller，不手写 background recovery |
| task resume API | 走 controller，保持返回字段 |
| runtime tool plan | model-visible tools 与 dispatchable tools 同源且稳定排序 |
| tool control plane | agent_turn/task_run 都只能通过 RuntimeToolControlPlane 调工具 |
| task tool_call 不可见工具 | admission/control plane deny，底层 executor 不执行 |
| task tool_call OperationGate deny | observation 有 gate payload |
| single turn read-only tool | observation 后继续回答 |
| single turn side-effect tool | needs_contract / TaskRun，不直接执行 |
| 工具层独立性 | single turn 不伪造 TaskRun / RuntimeDirective / ExecutionRecord |
| subagent 工具入口 | TaskExecutor 不再按 `SUBAGENT_TOOL_NAMES` 直连分发，入口统一进入 RuntimeToolControlPlane |
| prompt cache diagnostics | 能解释 stable/volatile/model/mode/tool 变化 |
| 禁止关键词/字符串路由 | explicit contract 只由结构化合同 + 系统签发标记触发 |
| 残留扫描 | 核心路径中无 `TurnRoute`、task-only tool executor 直连、admission gate 终裁、CurrentTurnCapabilityPlan 主链依赖 |

## 9. 阶段推进规则

- Phase 1 未完成，不做 admission 扩展。
- Phase 2 未完成，不开放 single turn tools。
- Phase 3 未完成，不允许 single turn 或 task executor 调工具控制面。
- Phase 4 未完成，不迁移 TaskExecutor 工具调用。
- Phase 5 未完成，不动 API execute/resume 之外的 runner 语义。
- Phase 6 未完成，不做 ToolSearch/deferred discovery。
- Phase 7 未完成，不扩大上下文预算。

任何阶段如果出现以下情况，停止继续实施：

- 需要改动 GraphHarness 或 graph work order。
- 需要改动图像生成 direct route。
- 需要降低测试断言。
- 需要保留两套长期执行链路。
- 需要让工具层继续依附 TaskRun 才能工作。
- 需要为 single turn 新增专用工具 executor。
- 需要伪造 TaskRun / RuntimeDirective / ExecutionRecord。
- 工具可见性需要保留两套独立权威。
- explicit contract 只能靠用户文本或 `source` 字符串推断；此时应先修契约生产者，不能在 QueryRuntime 中新增猜测逻辑。
- TaskExecutor 仍需要按工具名直接分支执行某类工具。
- Admission 仍需要构造 `ResourcePolicy` 或调用 `OperationGate`。

## 10. 最终验收命令

```powershell
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py -q
python -m pytest backend/tests/active_turn_authority_regression.py -q
python -m pytest backend/tests/tool_capability_table_regression.py -q
python -m pytest backend/tests/tool_supervisor_regression.py -q
python -m pytest backend/tests/sandbox_tool_runtime_regression.py -q
python -m pytest backend/tests/model_response_runtime_regression.py -q
python -m pytest backend/tests/tool_result_projection_regression.py -q
python -m pytest backend/tests/prompt_accounting_ledger_test.py -q
python -m pytest backend/tests/prompt_cache_prefix_tier_regression.py -q
python -m pytest backend/tests/deepseek_prompt_cache_diagnostics_test.py -q
```

最终残留扫描：

```powershell
rg "build_turn_route|TurnRoute|harness\.routing|harness\.route" backend/query backend/harness backend/api backend/tests
rg "CurrentTurnCapabilityPlan|build_current_turn_capability_plan" backend
rg "runtime_host\.operation_gate\.check|_check_operation_gate|OperationGatePipelineContext|ResourcePolicy" backend/harness/loop/admission.py backend/harness/loop/task_executor.py
rg "SubagentControl\(|SUBAGENT_TOOL_NAMES" backend/harness/loop/task_executor.py
rg "ToolRuntimeExecutor\.run|tool_runtime_executor\.run" backend/harness/loop backend/query
```

涉及前后端运行链路时，按项目固定端口真实启动：

```powershell
# backend: 127.0.0.1:8003
# frontend: 127.0.0.1:3000
```

## 11. 最终成功标准

- `QueryRuntime` 保持主入口，不散架。
- 单 agent 主链路无内部 route 层。
- 所有模型动作进入 admission。
- TaskRun schedule/recover/auto continuation 有单一 controller。
- TaskExecutor 保持执行循环权威。
- 工具层是 Runtime/Session 级控制面，不依附 TaskRun。
- TaskRun 只是工具调用 caller，不拥有工具 registry/admission/supervision/execution 权威。
- OperationGate 保持资源权限终裁。
- single turn 有安全的只读观察能力。
- side-effect 工具不会绕过 TaskRun/approval。
- context budget 与 provider/model/mode 对齐。
- prompt/cache 诊断能解释命中和失效。
- 残留链路扫描结果可解释：命中只能来自历史文档、非核心 graph/image direct route、或明确短期 public projection；核心单 agent 路径不能再依赖旧结构。
