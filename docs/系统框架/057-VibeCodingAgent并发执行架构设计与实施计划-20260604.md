# Vibe Coding Agent 并发执行架构设计与实施计划

日期：2026-06-04

## 1. 技术源报告

### 1.1 当前真实问题

当前项目已经具备“同轮多个工具调用”“TaskRun 生命周期执行器”“task_system/graph 业务任务入口”三类执行基础，但三者的边界还没有被明确建模：

- `single_agent_turn` 已允许模型同轮产生多个 native tool calls，并在准入通过后直接并发执行。
- `TaskRun` 已经有执行合同、后台调度、executor lease、暂停/恢复/停止控制；它是 runtime 层的 durable task lifecycle boundary，不是业务任务接口，也不是普通并发批处理 item。
- `task_system`、graph、engagement、project lifecycle 是业务任务入口；它们可以在 runtime 层创建或调度 TaskRun，但不应被 TaskRun execute API 取代。
- operation registry 已经记录 `read_only`、`destructive`、`concurrency_safe` 等能力元数据，但 single-turn 工具调度没有消费这些元数据。
- 审批等待和已完成工具结果混在同一批时，事件日志和模型协议消息可能分叉。

因此，缺失的不是“能不能并发”，而是成熟 agent 需要的并发控制面：

- 哪些操作可并发。
- 哪些操作必须排他。
- 哪些意图需要升级为带 contract/recovery 的 TaskRun lifecycle，而不属于交互轮工具批处理。
- 哪些入口属于 task_system/graph 业务编排，不能被 TaskRun execute API 混用。
- 执行结果、审批等待、恢复上下文如何保持一致。
- 并发失败后如何可诊断、可恢复、可测试。

### 1.2 当前代码证据

交互轮工具并发：

- `backend/harness/loop/single_agent_turn.py`：`pending_tool_invocations` 收集所有 admission=allow 的工具后通过 `asyncio.gather(..., return_exceptions=True)` 执行。该路径没有按 `concurrency_safe` 或资源冲突分流。
- `backend/harness/loop/single_agent_turn.py`：模型调用固定传入 `tool_call_options={"parallel_tool_calls": True}`。
- `backend/harness/runtime/compiler.py`：输出契约中 `ordinary_tool_calls.parallel_allowed=True`、`native_tool_calls.parallel_tool_calls=True`，提示模型同轮可以提出多个普通工具调用。

工具元数据和权限：

- `backend/permissions/operations.py`：`OperationDescriptor` 已有 `read_only`、`destructive`、`concurrency_safe` 字段。
- `backend/permissions/operations.py`：`read_file/search_text/list_dir/path_exists` 等只读操作被标为 `concurrency_safe=True`。
- `backend/permissions/operations.py`：`write_file/edit_file/shell/python_repl/git_write/browser/image_generate` 等副作用操作默认不是并发安全。
- `backend/capability_system/tools/native_tool_catalog.py`：`ToolDefinition.is_concurrency_safe` 已从 operation registry 投影出来。
- `backend/runtime/tool_runtime/tool_control_plane.py`：agent_turn 下，副作用工具在可见 RuntimeToolPlan 和 sandbox boundary 满足时会被允许执行，但没有同批资源锁或冲突检测。

审批和协议提交：

- `backend/harness/loop/single_agent_turn.py`：同批工具结果收集后，如果存在 `needs_approval`，代码记录 `approval_waiting` 并直接返回。
- 同一路径中，成功工具的 assistant tool call message 和 tool result message 只有在没有 approval observation 时才会追加到 `api_protocol_messages`。
- 这会导致同批中已执行成功的工具结果只存在事件流，未进入后续模型协议历史。

TaskRun 生命周期语义：

- `backend/runtime/shared/models.py`：`TaskRun` 被定义为 OrchestrationSystem 拥有的 durable single-agent task run，包含 `task_contract_ref`、`agent_profile_id`、`execution_runtime_kind`、status、checkpoint/event diagnostics。
- `backend/runtime/shared/models.py`：`TurnRun` 被明确注释为一轮 conversational trace，不是 task lifecycle object，也不能作为 orchestrated TaskRun 暴露。
- `backend/runtime/shared/models.py`：`AgentRun` 是某个 TaskRun 下的 concrete agent execution instance，说明 TaskRun 与 AgentRun 是 lifecycle/container 和执行实例的关系。
- `backend/harness/loop/task_lifecycle.py`：`TaskRunContract` 强制要求 `user_visible_goal`、`task_run_goal`，并通过 `completion_criteria`、`required_artifacts` 或 `required_verifications` 建立完成证据。
- `backend/harness/loop/task_lifecycle.py`：single-turn 的 `request_task_run` 会先从 model action 解析 contract，再创建 `TaskRun + AgentRun + TaskLifecycleRecord`，初始状态为 `waiting_executor`，随后才调用 `schedule_task_run_executor`。
- `backend/api/orchestration_harness.py`：`POST /orchestration/harness/task-runs/{task_run_id}/execute` 只接受已有 `task_run_id`，并通过 `schedule_or_recover_task_run_executor` 启动或恢复后台 executor；它不是业务任务创建接口。
- `backend/harness/loop/task_executor_controller.py`：TaskRun 调度有 `already_running` 检查、后台 task、恢复 scheduled lease、运行时重启恢复。
- `backend/harness/loop/task_executor.py`：TaskRun executor 按 step loop 执行，每步处理一个模型动作，并已有重复只读工具调用 guard、控制信号边界、模型协议修复、恢复状态。
- `backend/harness/runtime/compiler.py`：Task execution packet 的 envelope `scope_kind="task_run"`，模型可见内容包含 task contract、artifact execution scope、observations、execution state、work rollout。
- `backend/harness/graph/runtime.py`、`backend/harness/entrypoint/runtime_facade.py`、`backend/harness/agent_control/controller.py`：graph root、graph node executor、subagent executor 都会使用 TaskRun 作为 runtime 账本，进一步说明 TaskRun 是执行生命周期承载层，不是某一个业务任务 API 的同义词。
- `backend/api/orchestration_harness.py`、`backend/harness/loop/task_executor.py`：`execute_task_run` 只接受 `execution_runtime_kind in {"single_agent_task", "subagent_task"}` 的 TaskRun。graph root TaskRun 可以作为 graph ledger 存在，但不能当作 single-agent executor TaskRun 调度。

业务任务入口：

- `backend/api/task_system.py`：`/tasks/engagement-plans/{plan_id}/start`、`/tasks/projects/{project_id}/lifecycle-runs`、`/tasks/task-graphs/{graph_id}` 等接口属于 task_system 业务任务/图/项目生命周期入口。
- 这些入口可以通过 graph work order、engagement run、project lifecycle 间接创建或调度 TaskRun，但它们的业务语义不应下沉到 `execute_task_run` API。

### 1.3 外部成熟架构中可借鉴但不照搬的点

Codex 的有价值原则：

- 并发资格由工具 runtime/handler 明确声明，不由模型自由决定。
- 未知或未声明工具默认不并发。
- 执行层有一个统一的工具调用 runtime，负责分流并发和排他。
- 取消、失败、超时、终态通知在工具调用 runtime 内集中处理。

不照搬的点：

- 不把本项目的 TaskRun lifecycle/executor lease 塞进 single-turn 工具并发模型。
- 不按 Codex 的 handler trait 形态重写现有 Python 工具体系。
- 不把 shell 是否并发照搬为固定策略；本项目应由 operation metadata、sandbox scope、resource key、permission mode 共同决定。

Claude Code 的有价值原则：

- 并行 tool result 必须用 tool_use_id / tool_call_id 精确归属。
- 并行结果进入上下文时要保持协议消息顺序和预算处理一致。
- 工具并发不仅是执行问题，也是 transcript、resume、budget、UI 展示问题。

不照搬的点：

- 不按 Claude Code 的消息数组结构重写当前 HarnessRuntime。
- 不把多个工具结果拆成前端展示模型优先的结构；本项目应先保证 runtime event log、api_protocol_messages、state_index 一致。

## 2. 推荐设计方向

采用“三层并发控制面”：

1. **交互轮工具批处理层**
   - 服务于 single-agent turn 内的短工具调用。
   - 允许只读、幂等、并发安全工具同批并发。
   - 对写文件、编辑、shell、git 写、browser、image、memory write、subagent lifecycle 等非并发安全操作实行排他或降级串行。
   - 遇到审批时不丢失已完成工具结果，先提交可见协议结果，再进入 waiting approval。

2. **TaskRun 执行层**
   - 保持 TaskRun lifecycle、TaskRunContract、executor lease、恢复控制，不把它混同为 task_system 业务任务接口。
   - 需要合同、验收证据、跨轮推进或恢复能力的 agent 工作通过 `request_task_run`、graph node adapter、subagent adapter 等路径创建 TaskRun。
   - `execute_task_run` / `/orchestration/harness/task-runs/{task_run_id}/execute` 只负责调度或恢复已存在的 TaskRun executor，不负责创建业务任务。
   - 只有 executable TaskRun 拥有 `execute_task_run` 语义；graph root ledger TaskRun 只作为图运行账本。
   - Task executor 默认仍按 step loop 顺序执行模型动作；后续只允许在明确的 batch action 或 graph dispatch 中引入并发。

3. **图/子任务并行层**
   - 服务于 workflow/graph 中天然可并行的节点或子任务。
   - 使用已有 `execution_mode=parallel`、dispatch group、graph run ledger 和 executable TaskRun executor lease 来管理节点运行。
   - 不允许把多个共享写状态的节点当作无锁并发；必须有 resource key 和 join policy。

这不是复现 Codex 或 Claude Code，而是把成熟架构的必要不变量映射到本项目已有边界：

- single-turn 是“短工具批处理”。
- TaskRun 是“runtime lifecycle record”；其中 executable TaskRun 是“有执行合同、executor lease 和恢复语义的执行边界”。
- task_system/graph/engagement 是“业务任务和任务级并行编排入口”。
- operation registry 是并发资格来源。
- RuntimeToolControlPlane 是工具执行边界。
- event_log + state_index + api_protocol_messages 是一致性闭环。

### 2.1 术语裁决

后续实现必须固定以下语义，避免在代码和测试里再次混用：

- `TurnRun`：一次 conversational turn 的 trace。它可以记录本轮模型、工具、审批、协议消息，但不是任务生命周期。
- `TaskRun`：runtime 层的 durable lifecycle record。它绑定 contract、agent profile、executor lease、event/checkpoint diagnostics，用于可恢复的 agent 执行片段。
- `Executable TaskRun`：`execution_runtime_kind` 为 `single_agent_task` 或 `subagent_task` 的 TaskRun，允许进入 `execute_task_run` / `TaskExecutorController`。
- `Graph ledger TaskRun`：graph root 等编排账本型 TaskRun，用于记录 graph runtime 生命周期，不等同于可执行 single-agent TaskRun。
- `AgentRun`：某个 TaskRun 下的具体 agent execution instance。
- `TaskRunContract`：TaskRun 的目标、验收证据、权限、资源和恢复策略。
- `execute_task_run`：已有 TaskRun 的 executor 调度/恢复动作，不创建业务任务。
- `task_system` / graph / engagement：业务任务、任务图、项目生命周期和任务级编排入口。它们可以创建或调度 TaskRun，但业务语义归这些入口所有。
- `ToolBatchPlan`：single-turn 内短工具调用的批处理计划。它不创建 TaskRun，也不消费 TaskRun executor。

### 2.2 TurnRun 与 TaskRun 关系裁决

`TurnRun` 和 `TaskRun` 是并列的 durable runtime records，不是继承关系，也不是同一个对象的两种状态。

关系规则：

- 每个 conversational turn 启动时创建一个 `TurnRun`，用于记录本轮模型/action-loop trace。
- 一个 `TurnRun` 可以不创建 TaskRun；普通问答、普通工具调用、ask_user、block 都只需要 TurnRun 级 trace。
- 当本轮模型输出 `request_task_run` 且 contract 合法时，runtime 会创建一个新的 executable TaskRun，并通过 active turn registry 把当前 `turn_id/turn_run_id` 与 `bound_task_run_id` 关联。
- 这个关联是“本轮触发了一个可恢复工作”的因果绑定，不是父子生命周期绑定。TurnRun 可以结束，TaskRun 可以继续后台运行、等待 executor、等待审批、恢复或完成。
- TaskRun 会在 diagnostics 和 event refs 中保留 `turn_id` / `turn_ref` / `action_request_ref`，用于追踪来源；但后续 TaskRun executor 的 step loop 不等同于原 TurnRun。
- 不是所有 TaskRun 都来自 TurnRun。graph root、graph node、subagent 等路径也可以创建 TaskRun，其中 graph root 可能只是 ledger TaskRun，graph node/subagent 可以是 executable TaskRun。
- 因此 UI、监控、恢复逻辑应把 `TurnRun` 作为“交互轮 trace”，把 `TaskRun` 作为“可恢复工作生命周期”，通过 refs 关联二者，不允许把 TurnRun 升格成 TaskRun，也不允许把 TaskRun 当作聊天轮次。

## 3. 目标架构

### 3.1 新增核心概念

#### ToolConcurrencyDescriptor

从现有 operation/tool/runtime policy 汇总：

```text
tool_name
operation_id
read_only
destructive
concurrency_safe
requires_user_interaction
requires_approval_by_default
operation_type
resource_keys
parallel_group
exclusive_scope
max_parallel
conflict_policy
```

来源优先级：

1. operation registry 的 `concurrency_safe/read_only/destructive/operation_type`。
2. tool definition 的 `is_concurrency_safe/is_read_only`。
3. tool args 推导出的资源 key，例如 file path、repo root、shell cwd、browser session、memory scope、task_run_id。
4. runtime sandbox/file policy 对真实工作区、沙箱、managed storage 的约束。

#### ToolBatchPlan

single-turn 收到多个 tool action 后，不直接 gather，而是编译批计划：

```text
batch_id
turn_id
packet_ref
items[]
groups[]
diagnostics
```

item 包含：

```text
action_request
tool_call
admission
action_permit
concurrency_descriptor
resource_keys
execution_class
```

execution_class：

- `parallel_read`：可并发只读工具。
- `parallel_safe`：明确并发安全的非只读工具，默认不启用，必须显式声明。
- `exclusive`：非并发安全工具，独占执行。
- `approval_blocked`：需要审批，不执行。
- `denied_or_error`：不执行，转观察。

#### Resource Lock Model

不需要一开始实现复杂分布式锁。先实现进程内、turn/task-run 层面的资源冲突模型：

- `workspace:file:<normalized_path>`：具体文件读写。
- `workspace:tree:<root>`：目录树写或 shell 可能影响范围。
- `git:index:<repo_root>`：stage/commit/restore。
- `shell:<cwd>`：shell/python 默认排他，除非只读验证命令被安全解析为 `read_only_shell`。
- `browser:<session_id>`：浏览器控制排他。
- `task:<task_run_id>`：TaskRun 控制排他。
- `memory:<scope>`：memory write 排他，memory read 可并发。

锁语义：

- read lock 可与 read lock 并发。
- write/exclusive lock 与任何相同 resource key 冲突。
- unknown resource key 默认 exclusive。
- 非 `concurrency_safe` 的副作用工具默认占用 `workspace:tree:<workspace_root>` 或对应域级锁。
- resource key 必须先规范化再比较：文件路径按 workspace/artifact root 解析并消除 `.`、`..`、大小写差异和路径分隔符差异；repo、cwd、browser session、memory scope、task_run_id 必须有稳定 canonical id。
- 无法规范化的资源默认进入 exclusive group，不允许以“缺少 resource key”为理由并发。

### 3.2 single-turn 固定执行流

当前：

```text
model response -> parse tool actions -> admission -> gather all allowed -> observations -> followup or approval wait
```

目标：

```text
model response
-> parse tool actions
-> admission/action_permit
-> build ToolBatchPlan
-> materialize non-executable observations
-> commit executable assistant tool-call envelope for all non-approval executed items
-> execute groups in deterministic order
-> emit/record observations
-> if approval items exist:
     commit successful/denied/error tool protocol messages
     record approval_waiting with pending approval refs
     terminal blocked(waiting_approval)
     return
   else:
     append assistant tool-call message + tool result messages
     invoke followup model
```

执行分组规则：

1. 所有 `approval_blocked` 不参与执行。
2. 所有 `denied_or_error` 立即产出观察。
3. 连续可并发的 `parallel_read/parallel_safe` 按同一 group gather。
4. 任意 `exclusive` 单独 group，前后 group barrier。
5. 若同批包含 approval 和 executable：
   - executable 可以先执行，但必须把成功/失败工具协议消息提交为 turn partial protocol。
   - approval observation 不作为 tool result 发给模型，除非后续有明确的 approval resume 协议。
6. 并发组内部可以按 runtime 完成顺序收集结果，但写入 `api_protocol_messages`、event projection 和 followup model context 时必须恢复为原始 tool_call 顺序。
7. 每个 group 必须有 timeout/cancellation policy；取消或超时后，已完成 item 保留 observation，未完成 item 产出 retryable error observation，不允许静默丢失。

重要约束：

- 模型可提出多个工具调用，但 runtime 不承诺全部并发。
- 提示中不能继续笼统写“普通工具调用可以在同一轮提出多个并并行执行”；应改成“可提出多个，运行时会按安全边界并发或串行执行”。
- `parallel_tool_calls=True` 只表示模型可以同轮提出多个工具，不表示 runtime 无差别并发。

### 3.3 TaskRun 生命周期执行层边界

保留现状：

- TaskRun 通过 `request_task_run`、graph node adapter、subagent adapter 等路径创建。
- `execute_task_run` API 只对已存在 executable TaskRun 做调度或恢复，并通过 `schedule_task_run_executor` 进入后台。
- executable TaskRun 当前限定为 `execution_runtime_kind in {"single_agent_task", "subagent_task"}`。
- graph root ledger TaskRun 不进入 `execute_task_run`，由 graph harness runtime 管理。
- TaskRunContract 是 TaskRun 的执行合同来源，包含目标、完成证据、权限、资源和恢复策略。
- `TaskExecutorController` 继续拥有 executor lease、防重复运行、恢复 scheduled lease。
- `execute_task_run` 继续保持 step loop，每步处理一个模型动作。

新增约束：

- Task executor 不直接消费 single-turn 的 `ToolBatchPlan`，除非后续引入 `batch_tool_call` 动作。
- `request_task_run` 是带合同和恢复语义的工作生命周期边界，不是普通并发工具，也不是 task_system 业务任务创建接口。
- 单轮可以通过 ToolBatchPlan 串行或并发处理短工具操作；只有需要跨轮推进、明确验收、恢复、暂停/继续、图节点执行或子 agent 执行的工作才应进入 TaskRun。
- TaskRun 不参与 single-turn 工具批处理分组；最多作为资源锁中的 `task:<task_run_id>` 被控制类工具引用。

可选增强：

- 在 Task executor 里新增 `batch_tool_call` 动作，但第一阶段不做。
- `batch_tool_call` 只允许明确声明为 batch-safe 的工具组合，必须走同一 ToolBatchPlanner。
- Task executor 的并行子任务通过 graph/engagement 或 subagent/task APIs 调度，不通过 bare `asyncio.gather`。
- 如果后续允许 Task executor 内部 batch tool call，必须先定义 task-run 内部协议消息提交、approval resume 和恢复去重规则，不能复用 single-turn 规则后直接上线。

### 3.4 Graph / Task 并行层边界

已有 `execution_mode=parallel`、`dispatch_group`、`ExecutionScheduler` 概念，应继续作为任务级并行入口。graph/engagement 负责业务编排，TaskRun 负责每个 agent 执行片段的 runtime 生命周期账本。

目标：

- graph parallel 负责“多个 work order / 节点执行片段”的并行；节点需要 agent 执行时可以创建自己的 executable TaskRun。
- ToolBatchPlanner 负责“同一 agent turn 内多个工具”的并发。
- 两者共享资源冲突模型，但不共享执行循环。

任务级并行规则：

- 每个 executable TaskRun 仍有自己的 executor lease。
- graph root ledger TaskRun 不参与 executor lease 竞争，只记录 graph runtime 生命周期。
- 同一 graph dispatch group 内，如果多个节点写同一 artifact/memory/file scope，必须由 graph scheduler 拒绝或串行化。
- terminal/barrier 节点必须等待 active parallel work 完成或明确失败。

## 4. 实施计划

### Phase 1：并发元数据和批计划，不改执行语义

目标：

- 新增 ToolConcurrencyDescriptor 和 ToolBatchPlan 编译能力。
- 先以 shadow diagnostics 方式记录每批工具的理论分组，不改变执行。

涉及文件：

- `backend/harness/runtime/tool_batch_planner.py` 新增。
- `backend/harness/runtime/__init__.py` 导出。
- `backend/tests/tool_batch_planner_regression.py` 新增。
- `backend/permissions/operations.py` 仅补齐明显缺失的 `concurrency_safe=False` 显式标记，不改变行为。

完成标准：

- 能从 `ModelActionRequest + RuntimeToolPlan + operation registry` 生成 batch plan。
- 只读工具进入同一 parallel group。
- `write_file/edit_file/shell/python_repl/git_write/browser/image_generate` 默认 exclusive。
- 相同 file path 的读写冲突被识别。
- 路径、repo、cwd、browser session、memory scope、task_run_id 的 resource key 有 canonicalization 测试。
- unknown operation 默认 exclusive。

不允许：

- 不在本阶段改 `single_agent_turn` 的执行顺序。
- 不把 TaskRun executor 接进这个 planner。

### Phase 2：single-turn 执行切换为 ToolBatchPlan

目标：

- 用 ToolBatchPlan 替换 `single_agent_turn` 中裸 `asyncio.gather`。
- 只对可并发组 gather，exclusive 组串行 barrier。
- 修复 approval + executable 混批的协议提交问题。

涉及文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/runtime/tool_batch_planner.py`
- `backend/runtime/tool_runtime/tool_observation.py` 如需增加 partial protocol 标记，可小改。
- `backend/tests/harness_runtime_facade_regression.py`

完成标准：

- 多个只读工具仍同批并发。
- 多个非并发安全副作用工具按确定顺序串行。
- 读写同一路径不会并发。
- `read_file + needs_approval(write_file)` 场景中，read result 不丢失协议上下文。
- followup model 接收到完整、合法、有序的 assistant tool_calls + tool messages。
- 并发组结果即使乱序完成，协议消息和后续模型上下文仍按原始 tool_call 顺序提交。
- group timeout/cancel 产生可诊断 error observation，不破坏同组已完成结果。

不允许：

- 不用保留旧 gather 路径做 fallback。
- 不通过跳过测试或降低断言证明通过。

### Phase 3：提示和模型 tool_call_options 收敛

目标：

- 将提示从“允许并行执行”改为“可提出多个工具，运行时按安全边界并发或串行”。
- `parallel_tool_calls=True` 只在本轮工具数量上限大于 1 且 provider/model 支持时启用。
- 将批计划摘要加入 runtime diagnostics，而不是暴露给模型作为复杂规则。

涉及文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/runtime/tool_runtime/tool_call_policy.py`
- `backend/runtime/model_gateway/model_runtime.py`
- `backend/tests/model_runtime_regression.py`
- `backend/tests/harness_runtime_facade_regression.py`

完成标准：

- 模型提示不再承诺无条件并发。
- 单工具场景 `parallel_tool_calls=False`。
- 多工具场景可启用 provider parallel tool call，但执行层仍由 ToolBatchPlan 决定。

### Phase 4：TaskRun lifecycle 与业务任务并行边界加固

目标：

- 明确 TaskRun execute API 只是已有 executable TaskRun 的 executor 调度/恢复入口，不是 task_system 业务任务创建入口。
- 明确 graph root ledger TaskRun 与 graph node executable TaskRun 的不同生命周期。
- 防止 single-turn 把本应进入 TaskRun lifecycle 的带验收、恢复、跨轮推进工作压缩为一轮多副作用工具。
- 明确 task_system/graph/engagement 负责业务编排，TaskRun 负责 runtime 生命周期账本和 executor lease。
- 给 graph/parallel task 增加资源冲突检查设计入口。

涉及文件：

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/task_executor.py`
- `backend/harness/loop/task_executor_controller.py`
- `backend/api/orchestration_harness.py`
- `backend/orchestration/execution_scheduler.py`
- `backend/task_system/graphs/task_graph_models.py`
- `backend/tests/harness_runtime_facade_regression.py`
- `backend/tests/orchestration_execution_scheduler_regression.py`

完成标准：

- `request_task_run` 仍通过 TaskRunContract、TaskRun lifecycle 和 scheduler 创建可恢复执行。
- `execute_task_run` 只能调度或恢复已存在 executable TaskRun，不能承担业务任务创建语义。
- graph root ledger TaskRun 调用 execute API 应保持 `not_single_agent_task_run` 类拒绝语义。
- task_system/graph/engagement 入口继续保留业务任务语义，并通过 adapter/work order/subagent 创建 runtime TaskRun。
- `TaskExecutorController` 仍拒绝 duplicate running claim。
- graph parallel 节点有明确 dispatch_group/resource conflict 诊断。
- 不把 TaskRun executor 改造成 single-turn 工具批处理。

### Phase 5：可观测性、恢复和监控

目标：

- 在 event log、runtime monitor、trace 中展示 batch plan、group 执行状态、串行化原因、冲突资源。
- 出错时能定位是 admission、batch planning、group execution、approval wait、protocol commit 哪一层。

涉及文件：

- `backend/harness/runtime/session_timeline.py`
- `backend/harness/runtime/progress_presenter.py`
- `backend/api/runtime_monitor.py`
- `backend/runtime_monitor_projection_test.py` 或对应监控测试
- `backend/tests/harness_runtime_facade_regression.py`

完成标准：

- trace 中能看到 `tool_batch_planned`、`tool_batch_group_started`、`tool_batch_group_completed`。
- monitor 能显示“并发执行/串行执行/等待审批”的原因。
- 恢复后不会重复执行已完成的工具组。
- approval resume 后只继续 pending approval 对应动作，不重放已经完成并提交协议历史的工具结果。

## 5. 文件级执行清单

新增：

- `backend/harness/runtime/tool_batch_planner.py`
  - `ToolConcurrencyDescriptor`
  - `ToolBatchItem`
  - `ToolBatchGroup`
  - `ToolBatchPlan`
  - `build_tool_batch_plan(...)`
  - `derive_resource_keys(...)`
  - `group_tool_batch_items(...)`

- `backend/tests/tool_batch_planner_regression.py`
  - 只读工具并发分组。
  - 写工具 exclusive。
  - 读写同路径冲突。
  - unknown operation 默认 exclusive。
  - approval item 不进入 execution group。

修改：

- `backend/harness/loop/single_agent_turn.py`
  - 用 batch plan 替代裸 gather。
  - 引入 group-level event。
  - 修复 approval 混批协议提交。

- `backend/harness/runtime/compiler.py`
  - 改写 action protocol 文案。
  - 删除“无条件 parallel_allowed”的语义误导，保留“multi tool call allowed”。

- `backend/runtime/tool_runtime/tool_call_policy.py`
  - 根据 max tool calls / model capability / runtime policy 输出 `parallel_tool_calls`。

- `backend/runtime/model_gateway/model_runtime.py`
  - 保持 tool options 透传，但补测试确认参数来源。

- `backend/runtime/tool_runtime/tool_control_plane.py`
  - 不负责批调度，只负责单次工具 invocation 的准入和监督。
  - 可补充 operation/resource diagnostics。

- `backend/orchestration/execution_scheduler.py`
  - 后续任务级并行资源冲突诊断，不与 single-turn planner 互相调用执行。

## 6. 验证矩阵

single-turn：

- `read_file + path_exists`：并发执行，followup 获取两个 tool results。
- `write_file + edit_file`：串行执行，事件记录串行原因。
- `write_file(path=A) + read_file(path=A)`：不得并发。
- `read_file(path=A) + read_file(path=B)`：可并发。
- `terminal + write_file`：默认串行。
- `browser_control + browser_control`：同 session 串行。
- `image_generate + read_file`：image exclusive，read 可在前后 barrier 外按 plan 排序。
- `read_file + needs_approval(write_file)`：read result 被提交到协议历史，turn 进入 waiting_approval。
- `read_file + needs_approval(write_file) + path_exists`：审批前两个已执行只读结果按原始 tool_call 顺序进入协议历史，审批恢复后不重复执行。
- 一个工具异常：同组其他工具完成后形成 error observation，不破坏协议消息顺序。
- 一个并发组超时：已完成结果保留，超时 item 产出 retryable error observation，followup/trace 不丢失原始 tool_call_id。

TaskRun：

- 已存在 TaskRun 经 execute API 调度后，重复 execute 返回 `already_running`。
- execute API 对不存在的 `task_run_id` 返回 not found，不创建业务任务。
- execute API 对 graph root ledger TaskRun 返回 `not_single_agent_task_run`，不尝试创建 executor lease。
- runtime restart 后 scheduled lease 可恢复为 waiting_executor。
- pause/resume/stop 不受 single-turn batch planner 影响。
- TaskRun 每步仍只处理一个 model action。
- graph node/subagent 创建的 TaskRun 仍保留 origin、contract、agent profile 和 executor lease。

Graph / task_system parallel：

- parallel dispatch group 中独立只读节点可并行。
- 写同一 artifact scope 的并行节点被拒绝或串行化。
- barrier/terminal 等待 active parallel work。
- engagement/project lifecycle 入口不通过 bare TaskRun execute 创建业务任务。

协议与恢复：

- 所有已执行工具都有 tool_call_id 对应 tool result。
- approval observation 不伪装成普通 tool result。
- blocked(waiting_approval) 后 trace 可恢复 pending approvals 和已完成 observations。
- api_protocol_messages、event_log、state_index 不分叉。

## 7. 迁移和切换规则

切换方式：

1. Phase 1 shadow 模式只记录 batch plan，不改变执行。
2. Phase 1 结束时必须有 shadow parity 报告：当前裸 gather 的执行结果与 ToolBatchPlan 预测分组没有发现未解释的协议/审批/资源冲突差异。
3. Phase 2 直接切换 single-turn 执行，不保留旧 gather fallback。
4. 如 Phase 2 发现关键假设错误，回滚整次提交，而不是在 runtime 内保留双路径。

旧逻辑清理：

- 删除 `single_agent_turn` 中无差别 `asyncio.gather` 执行路径。
- 删除提示里无条件“普通工具可并行”的表述。
- 删除任何为旧路径保留的兼容分支和测试。

不迁移：

- 不迁移历史 event log。
- 不改变已存在 TaskRun 的 contract/ref 结构。
- 不改变 TaskRun execute API 路径。
- 不改变 task_system/graph/engagement 作为业务任务入口的语义。

## 8. 风险控制

主要风险：

- 过度串行化导致工具调用变慢。
- resource key 推导不完整导致误判并发安全。
- approval 混批协议提交修复影响历史消息结构。
- TaskRun lifecycle、single-turn ToolBatchPlanner 和 graph parallel 如果过早共享同一个执行循环，可能造成边界混乱。

控制方式：

- 初期宁可保守串行副作用工具，只放开明确只读和明确 concurrency_safe 的工具。
- unknown operation 默认 exclusive。
- ToolBatchPlanner 只产计划，不直接执行；执行权仍在 single-turn 或 graph/task executor 所属层。
- TaskRun executor 第一阶段不引入 batch action。
- 所有协议消息按 provider 要求做回归测试，尤其 assistant tool_calls 和 tool role message 的对应关系。

## 9. 不允许的实现方式

- 不允许继续裸 `asyncio.gather` 所有 admission=allow 的工具。
- 不允许把 `parallel_tool_calls=True` 当成 runtime 执行安全依据。
- 不允许用“沙箱里安全”为理由并发所有写/执行工具；沙箱解决隔离，不解决同批状态竞态。
- 不允许把 TaskRun execute API 合并进 single-turn tool batch。
- 不允许为了通过测试跳过审批、mock 核心执行、降低断言或硬编码输出。
- 不允许保留旧 gather 路径作为 fallback。

## 10. 最终目标

完成后，本项目的并发能力应达到以下状态：

- 模型可以自然提出多个工具调用。
- runtime 能根据真实工具能力、资源冲突和审批状态决定并发或串行。
- 短工具批处理、TaskRun 生命周期执行、task_system/graph 任务级编排三层边界清楚。
- 已完成工具结果、审批等待、后续模型上下文保持一致。
- 并发执行可观测、可恢复、可测试。
- 项目保留自己的独立任务执行接口，不照搬 Codex/Claude Code 的实现形态。

## 11. 实施状态

更新日期：2026-06-04

当前 057 已完成核心升级：

- single-turn 多工具调用已由 ToolBatchPlan 负责分组，read-only/concurrency_safe 工具可并行，副作用、未知或资源冲突工具保持排他。
- provider `parallel_tool_calls` 只表达模型可提出多个 tool call；runtime 仍按工具元数据、资源锁、审批状态和安全边界决定并发或串行。
- TaskRun executor 继续保持 durable lifecycle 语义，每步一个 model action，不与 single-turn tool batch 混用。
- task_system/graph/engagement 仍是业务任务入口，`execute_task_run` 只调度或恢复已有 executable TaskRun。
- 审批等待、已完成工具结果、event log、api protocol messages 和后续模型上下文有独立回归保护。

已验证命令：

```text
python -m pytest backend/tests/tool_batch_planner_regression.py backend/tests/operation_registry_authority_regression.py backend/tests/model_runtime_regression.py
python -m pytest backend/tests/harness_runtime_facade_regression.py
```
