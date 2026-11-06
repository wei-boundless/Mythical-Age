# Task 作为普通 Turn 覆盖层的链路审查与升级设计书

## 0. 文档状态

本文是任务系统从“分离执行版”改为“普通 turn 覆盖版”的链路审查与升级设计书。

状态：等待用户审阅后再实施。

本文不替代 `task_system_control_action_architecture_upgrade_plan_20260628.md`，而是先解决更底层的问题：`TaskRun` 与普通 `turn` 的关系。

本文的核心判断：

- `TaskRun` 不是另一种 agent 执行模式。
- agent 面对普通 turn 和 task-bound turn 时，不应该拥有两套不同心智模型。
- `TaskRun` 是 agent 通过控制动作向系统开启的一段长任务运行资源。
- task 更考验系统侧资源分配、状态持久化、投影、恢复和控制，而不是 agent 自己进入某个“任务人格”。
- 普通 turn 仍然是唯一模型决策与工具执行单位。
- `TaskRun` 是系统在普通 turn 外部维护的长任务资源和持久状态覆盖层。
- task prompt 不应形成独立 prompt loop；任务期间提示词应该作为普通 turn 的 overlay/tail context 注入。
- `request_task_run` 即使保留，也只是一种请求系统分配长任务资源并持久化当前工作的控制信号，不是让 agent 切换到 task agent。

## 1. 核心定义

### 1.1 普通 Turn

普通 `turn` 是模型唯一的决策执行事务。

它负责：

- 阅读用户当前输入；
- 接收上下文、工具、状态和约束；
- 选择一个动作；
- 调用工具或回复用户；
- 产生可提交输出；
- 形成可被系统记录的观察和状态变化。

普通 turn 可以很短，也可以包含多次工具调用。是否复杂，不决定它是不是任务。

### 1.2 TaskRun

`TaskRun` 是系统侧长任务运行资源。

它负责：

- 分配并绑定长任务身份；
- 管理这段长任务资源的暂停、恢复、停止、替换和收口；
- 绑定持续工作身份；
- 保存目标、范围、验收、计划和 todo 游标；
- 接收普通 turn 的状态回写；
- 投影当前进展；
- 给下一次普通 turn 提供 task overlay。

`TaskRun` 不负责：

- 独立调用模型；
- 独立解释用户语义；
- 独立执行工具；
- 替普通 turn 生成 final answer；
- 训练 agent 进入另一套 task prompt。

### 1.3 Task Overlay

`Task Overlay` 是系统把长任务资源的当前状态投影进普通 turn 的方式。

它包含：

- 当前 `task_run_id`；
- 任务目标和范围；
- 当前 plan step；
- 当前 todo cursor；
- 当前 shape focus；
- pending user steer；
- 验收边界；
- 最近失败或恢复点；
- 可用控制动作。

它不改变普通 turn 的本质。agent 仍然按普通 turn 选择 `respond / tool_call / ask_user / block / active_work_control` 等动作。

### 1.4 Task State Patch

`Task State Patch` 是普通 turn 执行结束后，系统从本轮结果中抽取并写回 `TaskRun` 的状态变化。

它可以记录：

- plan step 变化；
- todo cursor 变化；
- 工具观察摘要；
- 验收进度；
- 阻塞原因；
- 恢复句柄；
- closeout 结果。

它不要求 agent 进入单独的 task execution action schema。

## 2. 当前链路审查

### 2.1 入口层已经有普通 turn 与 task 分支

证据：

- `backend/harness/entrypoint/runtime_facade.py:743`：`branch_kind == "single_agent_turn"` 时进入普通 turn。
- `backend/harness/entrypoint/runtime_facade.py:762`：`branch_kind == "explicit_contract_task"` 时进入显式任务分支。
- `backend/harness/entrypoint/runtime_facade.py:856`：普通 turn 内部定义 `start_task` 回调。
- `backend/harness/entrypoint/runtime_facade.py:890`：普通 turn 调用 `run_single_agent_turn(...)`。

判断：

当前系统已经把普通 turn 当作主入口，但任务分支仍然可能绕开普通 turn，进入独立任务资源分配和调度链路。

### 2.2 普通 turn 已经能接收 task overlay

证据：

- `backend/harness/loop/single_agent_turn.py:1783`：`run_single_agent_turn` 接收 `active_work_context`。
- `backend/harness/runtime/compiler.py:381`：`compile_single_agent_turn_packet` 接收 `active_work_context` 和 `current_work_boundary_receipt`。
- `backend/harness/runtime/compiler.py:611`：普通 turn 把 `active_work_context` 放入 volatile runtime payload。
- `backend/harness/runtime/packet_assembler.py:20`：`build_single_agent_turn_packet_context` 接收 `active_work_context`。
- `backend/harness/runtime/packet_assembler.py:350`：普通 turn 根据 `current_work_boundary_receipt` 计算 `active_work_control` 可用性。

判断：

这是 overlay 架构的雏形。正确方向不是新建 task prompt loop，而是加强普通 turn 的 task overlay 投影和回写。

### 2.3 TaskRun 创建层也已经具备可保留资产

证据：

- `backend/harness/loop/task_lifecycle.py:915`：`start_task_lifecycle` 创建 `TaskRun`。
- `backend/harness/loop/task_lifecycle.py:1062`：启动时绑定 active turn。
- `backend/harness/runtime/active_turn.py:157`：`ActiveTurnRegistry.bind_task_run` 可把普通 turn 与 task 绑定。
- `backend/harness/runtime/active_turn.py:178`：`complete_bound_task` 可在任务结束时释放绑定。

判断：

这些是应该保留的系统侧状态能力。它们不要求任务拥有独立执行器。

### 2.4 当前真正的问题是 task_executor 复制了普通 turn

证据：

- `backend/harness/entrypoint/runtime_facade.py:2407`：`execute_task_run` 直接调用 task executor。
- `backend/harness/loop/task_executor.py:1257`：`execute_task_run` 是独立任务执行入口。
- `backend/harness/loop/task_executor.py:1641`：`_execute_claimed_task_run` 自己驱动步骤循环。
- `backend/harness/loop/task_executor.py:1845`：task executor 等待 task model action。
- `backend/harness/loop/task_executor.py:4272`：`_invoke_task_model_action` 独立调用模型。
- `backend/harness/loop/task_executor.py:2105`：task executor 自己做 `decide_model_action_lifecycle`。
- `backend/harness/loop/task_executor.py:6124`：task executor 自己提交 task final message。

判断：

这条链路让任务系统拥有第二套模型决策、动作准入、工具执行和最终输出路径。它是“分离版 task”的核心结构风险。

### 2.5 Compiler 和 Packet 层也有两套 invocation kind

证据：

- `backend/harness/runtime/compiler.py:381`：`compile_single_agent_turn_packet`。
- `backend/harness/runtime/compiler.py:1059`：`compile_task_execution_packet`。
- `backend/harness/runtime/packet_assembler.py:20`：`build_single_agent_turn_packet_context`。
- `backend/harness/runtime/packet_assembler.py:134`：`build_task_execution_packet_context`。
- `backend/harness/runtime/packet_context.py:66`：`RuntimePacketContext` 明确支持 `single_agent_turn` 与 `task_execution`。

判断：

当前 prompt/context 编译也复制了两套入口。overlay 目标下，chat/task-bound 工作应该统一走 `single_agent_turn`，`task_execution` 不能再作为普通任务的默认模型调用路径。

### 2.6 active_work_control 是正确方向但仍被 executor 牵引

证据：

- `backend/harness/entrypoint/current_work_boundary.py:113`：系统根据 active work facts 生成 current work boundary decision。
- `backend/harness/loop/active_work.py:48`：`ActiveWorkContext` 是 task-bound work 的模型可见上下文。
- `backend/harness/entrypoint/runtime_facade.py:1328`：普通 turn 可以执行 active work control。
- `backend/harness/entrypoint/runtime_facade.py:2204`：继续 active work 最终仍调度 task executor。

判断：

active work 的“边界判断、状态投影、控制动作”方向是正确的；问题在于 continue/resume 最终回到 task executor，而不是回到普通 turn。

### 2.7 外部成熟 agent 源码审查

本节审查项目目录外的成熟 agent 源码，只抽取与 task / turn / todo / background work 直接相关的机制，不做泛化类比。

审查来源：

- Codex：`D:/AI应用/openai-codex/codex-rs`
- Claude Code：`D:/AI应用/claude-code-nb-main`
- Claude Code 源码研究材料：`D:/AI应用/Claude-Code-Source-Study-main`
- Hermes：`D:/AI应用/hermes/hermes-agent-main`

#### 2.7.1 Codex：task 是 session 生命周期包装，turn 是执行核心

关键文件：

- `D:/AI应用/openai-codex/codex-rs/app-server-protocol/src/protocol/v2/turn.rs`
- `D:/AI应用/openai-codex/codex-rs/app-server/src/request_processors/turn_processor.rs`
- `D:/AI应用/openai-codex/codex-rs/core/src/tasks/mod.rs`
- `D:/AI应用/openai-codex/codex-rs/core/src/tasks/regular.rs`
- `D:/AI应用/openai-codex/codex-rs/core/src/state/turn.rs`
- `D:/AI应用/openai-codex/codex-rs/protocol/src/plan_tool.rs`
- `D:/AI应用/openai-codex/codex-rs/core/src/tools/handlers/plan.rs`
- `D:/AI应用/openai-codex/codex-rs/core/src/tools/handlers/goal_spec.rs`
- `D:/AI应用/openai-codex/codex-rs/core/src/tools/handlers/multi_agents_spec.rs`

审查结论：

- Codex 对外协议以 turn 为中心：`TurnStartParams`、`TurnSteerParams`、`TurnInterruptParams` 和 `TurnStatus` 构成主生命周期。
- `turn_steer` 必须携带 `expected_turn_id`，说明继续/转向是绑定当前 active turn 的控制动作，而不是让系统重新猜语义。
- Codex 内部也有 `SessionTask`，但 `RegularTask.run()` 进入的是 `run_turn`。这里的 task 是 Tokio 后台任务、取消、事件和 telemetry 的运行包装，不是第二套 agent 语义模型。
- `TaskKind = Regular | Review | Compact` 是运行类型，不是用户任务模式。`Review` 和 `Compact` 还会被限制为不可普通 steer。
- `update_plan` 在源码注释中被定义为 todo/checklist tool，不是 plan mode；Plan mode 中调用 `update_plan` 会被拒绝。这一点直接证明：成熟系统会把 checklist/todo 当作状态工具，而不是任务模式。
- `create_goal / update_goal` 是结构化工具面。`update_goal` 只允许模型标记 `complete` 或 `blocked`；暂停、恢复、预算限制、用量限制由用户或系统控制。
- `spawn_agent` 使用结构化 tool/function calling 表达子 agent 控制动作。它创建有身份的子任务/子 agent，但仍属于显式控制面，不是把主 agent 切进一个普通 task prompt loop。

对本项目的含义：

- `TaskRun` 可以是系统生命周期对象，但普通任务执行不应该绕开 `single_agent_turn`。
- todo / plan cursor 应作为工具或状态游标进入当前 turn，而不是升级为 `primary_mode`。
- pause / resume / stop / budget / ownership 等生命周期动作应由系统状态层承接，模型只发出被允许的结构化控制信号。

#### 2.7.2 Claude Code：conversation/query loop 是唯一模型循环，task 是预算、工具或后台对象

关键文件：

- `D:/AI应用/claude-code-nb-main/QueryEngine.ts`
- `D:/AI应用/claude-code-nb-main/query.ts`
- `D:/AI应用/claude-code-nb-main/Task.ts`
- `D:/AI应用/claude-code-nb-main/tasks.ts`
- `D:/AI应用/claude-code-nb-main/tools/TodoWriteTool/TodoWriteTool.ts`
- `D:/AI应用/claude-code-nb-main/tools/TodoWriteTool/prompt.ts`
- `D:/AI应用/claude-code-nb-main/tools/TaskCreateTool/TaskCreateTool.ts`
- `D:/AI应用/claude-code-nb-main/tools/AgentTool/AgentTool.tsx`
- `D:/AI应用/claude-code-nb-main/tools/AgentTool/runAgent.ts`
- `D:/AI应用/claude-code-nb-main/tools/AgentTool/prompt.ts`
- `D:/AI应用/claude-code-nb-main/tools/EnterPlanModeTool/EnterPlanModeTool.ts`

审查结论：

- `QueryEngine` 明确表达：一个 conversation 一个 `QueryEngine`，每次 `submitMessage()` 开始一个新 turn，同一 conversation 的 messages、file cache、usage 等状态跨 turn 持续。
- `query.ts` 是主模型循环：组装消息、调用模型、接收 tool_use、执行工具、写回 tool_result，然后继续同一 query loop。`taskBudget` 是 API 预算控制参数，不是另一个 task executor。
- `Task.ts` 中的 `TaskType` 包括 `local_bash`、`local_agent`、`remote_agent`、`in_process_teammate`、`local_workflow`、`monitor_mcp`、`dream`。这些是操作型后台对象，不是让主 agent 选择的语义 task mode。
- `TodoWriteTool` 是严格 schema 工具，`searchHint` 是管理当前 session checklist，状态按 `context.agentId ?? getSessionId()` 归属。todo 存在 app state 里，不改变主循环。
- `AgentTool` 通过结构化字段创建子 agent，例如任务描述、prompt、subagent type、模型、是否后台运行。子 agent 仍运行同一类 `query()` 循环。
- `EnterPlanModeTool` 是权限/模式控制工具，不是独立的计划任务执行器。
- Claude Code 对缓存很敏感：动态 agent 列表、计划附件、skill 附件等会以 attachment 或尾部上下文注入，避免频繁改变稳定 tool schema 和稳定 prompt prefix。

对本项目的含义：

- 当前任务进度、todo cursor、active plan step、recovery handle 应放入 volatile tail / overlay，不应写进稳定 schema 或稳定前缀。
- 任务期间提示词不应另起一套 task prompt loop，而应作为普通 turn 的当前状态投影。
- 后台任务可以存在，但它们必须是系统对象或子 agent 对象，不能成为普通 TaskRun 的默认模型执行路径。

#### 2.7.3 Hermes：task id 用于隔离与恢复，conversation_loop 仍是核心

关键文件：

- `D:/AI应用/hermes/hermes-agent-main/AGENTS.md`
- `D:/AI应用/hermes/hermes-agent-main/run_agent.py`
- `D:/AI应用/hermes/hermes-agent-main/agent/conversation_loop.py`
- `D:/AI应用/hermes/hermes-agent-main/tools/todo_tool.py`
- `D:/AI应用/hermes/hermes-agent-main/tools/delegate_tool.py`
- `D:/AI应用/hermes/hermes-agent-main/tools/cronjob_tools.py`
- `D:/AI应用/hermes/hermes-agent-main/tools/kanban_tools.py`
- `D:/AI应用/hermes/hermes-agent-main/agent/prompt_builder.py`
- `D:/AI应用/hermes/hermes-agent-main/toolsets.py`

审查结论：

- Hermes 的核心也是 `run_conversation()`：同步循环、interrupt 检查、预算跟踪、模型 tool call 和 tool result 都在同一个 conversation loop 中推进。
- 每轮会建立或继承 `effective_task_id`，并把 `agent._current_task_id` 设置给工具和环境隔离使用。task id 是系统归属和隔离句柄，不是第二套模型人格。
- `todo_tool.py` 把 todo 作为 session 内存状态保存，并在压缩后重新注入未完成项；行为约束主要放在工具 schema 描述，不通过反复改 system prompt 或 tool response 让模型“变成任务模式”。
- delegate 工具创建隔离子 agent，但它明确适合有边界的委托；长期后台工作使用 cronjob 或 kanban 类系统任务。
- kanban 工具只在特定 dispatcher 环境或 profile 下暴露，普通 chat 默认不可见。worker 有任务 id 和 workspace 所有权边界，不能修改不属于自己的 task。
- kanban / cronjob 这类长期任务的本质是系统调度、所有权、心跳、阻塞、完成和 handoff，不是普通 turn 里隐藏的语义猜测。

对本项目的含义：

- `TaskRun.task_run_id` 应主要服务归属、恢复、投影、控制和工具隔离。
- 图任务、监控任务、周期任务可以成为专门系统生命周期，但普通 chat task 不应因此走独立 task executor。
- 如果未来引入图任务 worker，应显式传入 task id、workspace、允许工具和完成/阻塞协议，而不是让普通 runtime 从自然语言里推断。

#### 2.7.4 可借鉴、不可借鉴与本项目适配

应借鉴：

- 单一模型执行核心：Codex 的 `run_turn`、Claude Code 的 `query()`、Hermes 的 `run_conversation()` 都是主循环。
- task 作为系统生命周期对象：负责身份、取消、恢复、投影、预算、归属和事件，而不是重新定义 agent 的行动模型。
- strict tool/function calling 承载控制动作：goal、todo、spawn agent、task create、kanban mutation 都通过结构化 schema 表达。
- todo 是工具和 cursor：它帮助 agent 维护进度，但不定义任务为什么存在，也不应成为 primary mode。
- 当前进度放在 tail / overlay：active step、todo cursor、pending steer、恢复句柄和最近观察应该作为动态上下文进入当前 turn，避免污染缓存前缀。
- 系统拥有生命周期控制：pause、resume、stop、budget、ownership、interrupt、background scheduling 由系统控制，agent 只能在授权动作面内表达请求。

不应照搬：

- 不应把 Codex 内部 `SessionTask` 名称误读为用户任务执行器。它是 session/turn 的运行包装，不是 task prompt loop。
- 不应把 Claude Code 的 background `TaskType` 当作 primary mode。那些是本地 shell、agent、workflow、monitor 等操作对象。
- 不应把 Hermes 的 kanban worker 协议用于普通 chat task。它适合显式 dispatcher / worker 场景，不适合默认会话 turn。

必须拒绝：

- 普通 TaskRun 默认进入独立模型循环。
- executor 再次选择用户语义、模式、工具和 final answer。
- runtime 根据自然语言关键词替 agent 判断是否开启任务。
- `todo` 作为 `primary_mode`。
- `investigation / recovery / monitor / open_work` 作为主任务模式。
- `open_work` 作为 unsupported mode 的自动 fallback。
- agent-facing prompt 写成“你现在进入 task executor / task_execution 模式”。

本项目适配结论：

- `request_task_run` 是结构化控制信号，用来请求系统创建或绑定 `TaskRun` 生命周期。
- `TaskRun` 是 turn 外部的系统状态覆盖层，保存目标、范围、验收、plan/todo cursor、恢复点和投影事件。
- task-bound work 后续继续时，应创建 task-bound ordinary turn continuation。
- `single_agent_turn` 是普通 chat task 的唯一模型决策和工具执行单位。
- `task_executor` 只能被降级为迁移对象、专门 graph worker adapter，或拆出状态控制函数；不能继续作为普通 TaskRun 默认执行器。
- 当前任务 attention index 应在 volatile tail 提醒模型关注 `task_run_id`、目标、范围、active step、todo cursor、pending steer、acceptance，而不是要求模型进入另一个模式。

### 2.8 成熟 agent 的生命周期与状态机划分

前一节说明了成熟 agent 不会把普通 task 做成第二套模型循环。本节补足更关键的问题：成熟 agent 不是没有状态机，而是把状态机分层，并严格区分哪个状态机拥有模型执行权。

结论：

- 进入 turn，就进入 turn execution state machine。
- 进入 turn，不等于进入 task execution state machine。
- `TaskRun` 可以有自己的生命周期状态机，但它不拥有模型调用、工具调用和 final answer 的执行权。
- task 状态机应观察、绑定、投影和更新 turn 的结果，而不是替代 turn 执行。

#### 2.8.1 四类生命周期

成熟 agent 通常至少有四层生命周期：

| 生命周期 | 典型对象 | 负责什么 | 是否拥有模型执行权 |
| --- | --- | --- | --- |
| Conversation / Session | thread、session、conversation | 身份、历史、恢复、权限上下文、持久化 | 否 |
| Turn | turn、query iteration、conversation loop iteration | 当前用户输入、模型决策、工具调用、工具结果、最终回复 | 是 |
| Work Overlay | goal、todo、task run、active work | 当前持续工作目标、范围、计划游标、todo 游标、验收、恢复点、投影 | 否 |
| Background Job / Worker | subagent、cron、kanban worker、remote task | 独立后台进程、子 agent、调度任务、心跳、worker ownership | 仅在它自己内部启动新的 turn/query loop 时拥有 |

这四层不能混成一层。尤其不能把 Work Overlay 当成 Turn 的替代品。

#### 2.8.2 Codex 的状态机边界

Codex 的外部协议以 turn 为中心：

```text
turn_start
-> inProgress
-> completed | interrupted | failed
```

`turn_steer` 需要 `expected_turn_id`，说明 steer 是对当前 active turn 的控制，不是重新推断任务语义。

Codex 内部也有 `SessionTask`，但普通任务的 `RegularTask.run()` 调用的是 `run_turn`。这说明 `SessionTask` 是 session 运行包装，负责后台 Tokio task、取消、事件和 telemetry；真正的模型执行仍在 turn 里。

Codex 的 goal 工具也体现了状态机分层：

```text
goal: active -> complete | blocked
```

模型只能用 `update_goal` 标记 `complete` 或 `blocked`。暂停、恢复、预算、用量限制由用户或系统控制。也就是说，goal 状态机存在，但它不是模型执行循环。

#### 2.8.3 Claude Code 的状态机边界

Claude Code 的 `QueryEngine` 以 conversation 为持久外壳，每次 `submitMessage()` 开始一个新 turn。状态大致是：

```text
conversation restored
-> submitMessage
-> prepare context
-> model streaming
-> tool_use detected
-> execute tools
-> append tool_results
-> continue query loop
-> terminal response | interrupted | failed
```

这里的 `taskBudget` 是 turn/query loop 的预算控制参数，不是 task executor。

`TodoWriteTool` 是一个 session checklist 工具，状态按 session 或 agent id 保存。todo 参与当前 turn 的上下文和进度展示，但不接管 query loop。

Claude Code 的 `TaskType = local_bash | local_agent | remote_agent | ...` 是后台对象状态机，例如：

```text
pending -> running -> completed | failed | killed
```

这类 task 是 shell、子 agent、remote agent 或 workflow 的运行对象。它不是普通会话 task 的默认执行方式。

#### 2.8.4 Hermes 的状态机边界

Hermes 的核心是 `run_conversation()`。每轮可以得到 `effective_task_id`，并把当前 task id 提供给工具和环境隔离使用。

这说明 task id 主要负责：

- 工具状态归属；
- todo 恢复；
- workspace / worker 隔离；
- 压缩后重新注入未完成状态。

Hermes 的 kanban / cronjob 才是独立后台工作状态机：

```text
assigned
-> working with heartbeat
-> blocked | completed | failed
```

这种 worker 生命周期需要 dispatcher、workspace、ownership、heartbeat、block/complete handoff。它适合图任务、调度任务、后台 worker，不适合普通 chat task 默认路径。

#### 2.8.5 对“进入 turn 是否进入状态机”的回答

是，进入 turn 就进入状态机，但进入的是 turn 状态机。

目标 turn 状态机：

```text
turn_requested
-> turn_admitted
-> context_assembled
-> model_deciding
-> tool_executing
-> model_continuing
-> turn_completed | turn_interrupted | turn_failed
```

如果当前存在 `TaskRun`，系统只是在 `context_assembled` 前构建 task overlay，并在 `turn_completed / interrupted / failed` 后抽取 task state patch。

也就是：

```text
TaskRun state before turn
-> build TaskTurnOverlay
-> run ordinary turn state machine
-> extract TaskStatePatch
-> update TaskRun state after turn
```

TaskRun 不应该出现下面这种默认执行状态机：

```text
task_claimed
-> task_model_deciding
-> task_tool_executing
-> task_final_answer
```

这正是当前 `task_executor` 复制普通 turn 的问题。

#### 2.8.6 目标 TaskRun 状态机

普通 chat `TaskRun` 的状态机应只表达系统生命周期，不表达模型执行阶段。

目标状态：

```text
created
-> active
-> waiting_for_next_turn
-> active
-> paused
-> active
-> blocked
-> active
-> completed | stopped | failed
```

其中：

- `active` 表示这条持续工作仍有效。
- `waiting_for_next_turn` 表示没有 turn 正在推进，等待用户、系统 continuation 或调度器触发。
- `paused` 表示系统或用户暂停生命周期。
- `blocked` 表示 agent 或系统明确记录阻塞，且需要用户输入或外部条件变化。
- `completed` 表示满足 acceptance 并收口。
- `stopped` 表示用户或系统终止，不再继续。
- `failed` 表示系统错误导致无法安全继续。

不建议把 `running` 作为普通 `TaskRun.status` 的主状态。因为模型是否正在运行已经由 active turn / turn status 表达。TaskRun 可以保存：

```text
bound_turn_id
last_turn_id
last_patch_id
latest_projection_event_id
```

这些是绑定和观察字段，不是第二套执行状态。

#### 2.8.7 正确的状态流转位置

创建任务：

```text
ordinary turn
-> agent calls request_task_run
-> runtime validates TaskStartIntent
-> TaskRun created(active)
-> bind current session / active work
-> project task overlay for future turns
```

继续任务：

```text
user / CLI / scheduler requests continuation
-> runtime resolves TaskRun
-> create ordinary turn continuation
-> build task overlay
-> run single_agent_turn
-> extract TaskStatePatch
-> update TaskRun
```

暂停任务：

```text
pause control
-> TaskRun.status = paused
-> no model loop is started
```

恢复任务：

```text
resume control
-> TaskRun.status = active
-> next continuation creates ordinary turn with recovery overlay
```

完成任务：

```text
ordinary turn produces completion signal / acceptance evidence
-> TaskStatePatchExtractor validates source evidence
-> TaskRun.status = completed
-> final answer remains ordinary turn output
```

阻塞任务：

```text
ordinary turn or system control records blocker
-> TaskRun.status = blocked
-> overlay stores blocker and resume requirement
-> no hidden executor keeps retrying
```

#### 2.8.8 当前项目的结构性偏差

当前项目的问题不是缺少生命周期，而是生命周期把执行权放错了：

- `TaskRun` 创建后进入 `task_executor`。
- `task_executor` 自己 claim task。
- `task_executor` 自己编译 task execution packet。
- `task_executor` 自己调用模型。
- `task_executor` 自己执行工具和提交 final answer。

这相当于建立了第二套 turn state machine。

成熟 agent 的做法应是：

- turn 状态机负责执行；
- task 状态机负责生命周期；
- overlay 负责把 task 状态带进 turn；
- patch 负责把 turn 结果写回 task；
- projection 负责把 task 状态展示给用户。

### 2.9 当前源码与目标架构逐项对照

本节把外部成熟 agent 的状态机分层，逐项对照当前项目源码。结论是：本项目已经具备 turn overlay 的部分资产，但普通任务主链路仍被 `task_executor` 接走，导致模型执行权被复制。

#### 2.9.1 成熟 agent 对照基线

| 参照系统 | 源码证据 | 状态机边界 | 对本项目的约束 |
| --- | --- | --- | --- |
| Codex | `D:/AI应用/openai-codex/codex-rs/app-server-protocol/src/protocol/v2/turn.rs:28` 定义 `TurnStatus`；`:66` 定义 `TurnStartParams`；`:160` 定义 `TurnSteerParams`；`:173-175` 要求 `expected_turn_id` 匹配 active turn | 对外控制面以 turn 为中心，steer 是 active turn 的前置条件，不是系统重猜语义 | continuation / steer / resume 必须绑定 turn 或创建新的 ordinary turn continuation |
| Codex | `D:/AI应用/openai-codex/codex-rs/core/src/tasks/regular.rs:6` 引入 `run_turn`；`:27-33` `RegularTask` 只是 `SessionTask`；`:70-78` 进入 `run_turn` | `SessionTask` 是 Tokio/session 包装，普通模型执行仍由 turn 负责 | 不应把 `TaskRun` 命名上的 task 理解为独立 agent 执行器 |
| Codex | `D:/AI应用/openai-codex/codex-rs/protocol/src/plan_tool.rs:25` 注释说明 `update_plan` 是 todo/checklist tool；`core/src/tools/handlers/plan.rs:79-81` 在 Plan mode 禁用它 | plan/todo 是工具状态和 UI 投影，不是主执行模式 | 本项目的 todo 只能是工具契约和 cursor，不能是 `primary_mode` |
| Claude Code | `D:/AI应用/claude-code-nb-main/QueryEngine.ts:176-182` 说明一个 conversation 一个 `QueryEngine`，每次 `submitMessage()` 开始新 turn；`:209` 是 submit 入口 | conversation 保持状态，turn 是执行事务 | task-bound work 应该是同一 conversation 内的新 ordinary turn |
| Claude Code | `D:/AI应用/claude-code-nb-main/query.ts:193-197` 说明 `taskBudget` 是整个 agentic turn 的 API 预算；`:219` 是 `query()` 主循环 | task budget 是 query loop 的预算控制，不是 task executor | 生命周期状态、预算和缓存不应逼出第二套 prompt loop |
| Claude Code | `D:/AI应用/claude-code-nb-main/tools/TodoWriteTool/TodoWriteTool.ts:31-35` 定义 strict `TodoWriteTool`；`:65-70` 按 `context.agentId ?? getSessionId()` 归属 todo | todo 是 session/agent 归属状态工具 | todo cursor 应在 TaskRun overlay/tail 中投影，状态归属由系统维护 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/agent/conversation_loop.py:187-195` 定义 `run_conversation()`；`:266-272` 生成或继承 `effective_task_id` 并写入 `_current_task_id` | task id 用于隔离、工具归属和恢复；conversation loop 仍是核心 | `task_run_id` 应服务归属、恢复、投影和工具隔离，不拥有模型执行权 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/tools/todo_tool.py:5-14` 明确 todo 是 session 内存状态，压缩后重注入，不变更 system prompt；`:90-117` 只重注入未完成项 | todo 是压缩恢复后的 tail/overlay 状态 | 本项目应把 todo cursor 放 volatile tail，不污染 stable prefix |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/AGENTS.md:744-745` 说明 `delegate_task` 不持久，长期工作用 `cronjob` 或 `kanban`；`tools/kanban_tools.py:1237-1295` 注册 complete/block/heartbeat/create/link 等 worker 控制工具 | 后台长期任务是显式 worker/dispatcher 生命周期 | graph/monitor worker 可以有专门状态机，但普通 chat TaskRun 不能默认走 worker executor |

#### 2.9.2 当前项目的四套状态机

| 当前状态机 | 源码位置 | 当前职责 | 与目标架构的冲突 |
| --- | --- | --- | --- |
| runtime branch | `backend/harness/entrypoint/runtime_facade.py:743-759` 在 `single_agent_turn` 和 `explicit_contract_task` 间分支；`:3614-3628` 显式合同进入 `task_execution_start`，默认进入 `single_agent_turn` | 决定当前请求走普通 turn 还是显式任务分支 | 普通 chat task 启动后仍可能进入显式任务执行分支，形成双入口 |
| ordinary turn | `backend/harness/loop/single_agent_turn.py` 驱动普通模型动作；`backend/harness/runtime/compiler.py:381-408` 支持 `active_work_context` 和 `current_work_boundary_receipt`；`backend/harness/runtime/packet_assembler.py:28-80` 接收 active work 并计算 action surface | 已经能承载 task overlay、active work 控制和 request_task_run 控制动作 | 这是应保留和强化的唯一普通模型执行路径 |
| TaskRun lifecycle | `backend/harness/loop/task_lifecycle.py:17` 定义 `created/admitted/running/waiting_executor/...`；`:1273-1325` 从 action request 启动生命周期；`:1422-1468` 创建后调度 executor 并让 turn 以 `task_executor_scheduled` 完成 | 创建 TaskRun、记录合同、初始化 todo、绑定 active turn，并调度 executor | lifecycle 把创建任务和执行任务绑死，导致 TaskRun 一创建就脱离 ordinary turn |
| ActiveTurn state | `backend/harness/runtime/active_turn.py:10-20` 定义 `model_turn/running_task/waiting_executor/...`；`:157-164` `bind_task_run` 默认进入 `waiting_executor` | 保存当前 turn 与 TaskRun 绑定 | ActiveTurn 状态混入 executor 等待态，把 task binding 解释为 executor handoff |
| task executor | `backend/harness/entrypoint/runtime_facade.py:2407-2410` 进入 `execute_task_run`；`backend/harness/loop/task_executor.py:1257` 独立执行入口；`:1641` 执行 claimed task；`:1747` 编译 `compile_task_execution_packet`；`:2105` 独立准入；`:4272` 独立调用模型；`:6124` 独立提交 final message | 第二套 task 模型循环、动作准入、工具调用和最终回复提交 | 与 `single_agent_turn` 抢模型执行权，是当前分离版 task 的核心问题 |
| provider/control schema | `backend/harness/runtime/control_action_schema.py:19` 七类 `_TASK_START_MODES`；`:138-153` 从 provider args 生成 compact intent；`:197-233` schema 要求 `entry_reason/primary_mode/mode_payload` | 将启动合同暴露给 provider strict tool/function calling | schema 层混淆 primary mode、shape、todo tool，并要求非机器必要字段 |
| action protocol | `backend/harness/loop/model_action_protocol.py:547-572` 识别 compact intent 并对 unsupported mode fallback 到 `open_work`；`:502-515` 仍要求 `entry_reason` 和 exactly one primary work mode | 归一化 agent 的 request_task_run 动作 | fallback 和旧 seed 兼容让系统继续替 agent 补语义，违背显式契约 |
| CLI / slash | `backend/cli/main.py:60-139` 暴露 `task-run`；`:266` 接受 `/goal /plan /todo`；`backend/harness/entrypoint/task_mode_slash_command.py:121-132` 仍生成 `entry_reason` 和 mode contract | 手动启动和调试 TaskRun | CLI 仍把 todo 当模式，并走 task-run execute/resume executor 路径 |

#### 2.9.3 当前实际流向

普通 chat 中 agent 发出 `request_task_run` 后，当前流向是：

```text
single_agent_turn
-> action_type=request_task_run
-> task_lifecycle.start_task_lifecycle_from_action_request
-> TaskRun created + active turn bound
-> schedule_task_run_executor
-> turn_completed(task_executor_scheduled)
-> task_executor.execute_task_run
-> compile_task_execution_packet
-> task model action
-> task tool execution / task final answer
```

这条链路的问题不在于创建了 `TaskRun`，而在于创建后把执行权交给了 `task_executor`。

目标流向应该是：

```text
single_agent_turn
-> action_type=request_task_run
-> TaskRun created(active)
-> bind session / active work
-> commit ordinary turn result
-> next continuation builds current_task_overlay
-> single_agent_turn
-> normal tool_call/respond/ask_user/block/active_work_control
-> TaskStatePatchExtractor
-> update TaskRun projection / todo cursor / acceptance
```

#### 2.9.4 重叠状态的具体风险

| 重叠点 | 当前表现 | 结果 |
| --- | --- | --- |
| `TaskRun.status=running/waiting_executor` 与 `ActiveTurnState=running_task/waiting_executor` 重叠 | `task_lifecycle.py:17`、`active_turn.py:10-20` 都表达执行阶段 | 用户和 monitor 看到的是 task 在跑，但真正跑的是哪个 turn / executor 不清晰 |
| `task_lifecycle` 创建后直接 `schedule_task_run_executor` | `task_lifecycle.py:1422-1468` | request_task_run 变成“启动另一个模型循环”的入口，而不是系统持久化信号 |
| `TaskRunControlGateway.resume_task_run()` 继续调度 executor | `task_run_control_gateway.py:60-65` 先 resume；`:275-291` 再 schedule | resume 不是创建 ordinary turn continuation，而是重启 task executor |
| `compile_single_agent_turn_packet` 与 `compile_task_execution_packet` 并存 | `compiler.py:381` 与 `task_executor.py:1747` | prompt、context、工具面、输出边界长期分叉 |
| final answer 双提交 | `single_agent_turn` 有普通 assistant output；`task_executor.py:6124` 有 `_commit_task_run_final_message` | task 输出可能绕过普通 turn 的输出边界、stream 和 projection 不变量 |
| `entry_reason` 与七类 `primary_mode` 还在 schema/prompt/protocol 三处出现 | `control_action_schema.py:19, 202-233`；`compiler.py:3111-3157`；`model_action_protocol.py:547-572` | agent 被训练成解释“为什么当前 turn 不够”，而不是提交系统需要的机器合同 |

#### 2.9.5 对照后的架构裁决

裁决：

- `single_agent_turn` 必须成为普通 TaskRun 的唯一模型执行单位。
- `TaskRun` 只保留生命周期、身份、范围、验收、plan/todo cursor、恢复点、投影和控制状态。
- `active_work_context`、`current_work_boundary_receipt`、`packet_assembler` 的 overlay 能力是正确资产，应成为改造中心。
- `task_executor` 不能继续作为普通 chat TaskRun 默认执行器；它只能被拆成状态控制 helpers，或短期保留为 graph/worker 迁移对象。
- `TaskRun.status` 不应表达 model/tool/final-answer 运行阶段；这些阶段由 turn status / active turn 表达。
- provider strict `request_task_run` schema 应只承载 compact machine contract，不再承载 `entry_reason` 和七类混层 mode。

## 3. 当前权责图

| 层级 | 当前职责 | 问题 | 目标职责 |
| --- | --- | --- | --- |
| `single_agent_turn` | 普通 turn 模型调用、工具调用、回复、request_task_run | 本身正确，但 task 启动后交给 executor | 保持唯一模型决策执行单位 |
| `task_lifecycle` | 创建 TaskRun、绑定 active turn、保存 contract | 可保留 | 只做系统状态生命周期，不调度模型 loop |
| `active_turn_registry` | 保存当前 turn 与 task 绑定 | 可保留 | 作为 overlay 绑定权威 |
| `current_work_boundary` | 判断当前输入与 active work 的控制边界 | 可保留 | 给普通 turn 提供可用控制动作和只读上下文 |
| `task_executor` | 独立模型循环、工具执行、admission、final answer | 与普通 turn 抢执行权 | 降级为状态/control/compat 组件，移除默认模型执行权 |
| `compile_task_execution_packet` | 独立 task prompt/context 编译 | 形成第二套 prompt | 普通 chat task 不再使用；必要时只保留给专门 graph adapter 迁移期 |
| `run_monitor/projector` | 投影任务进度 | 可保留 | 从普通 turn state patch 和 TaskRun 事件投影 |
| CLI `task-run execute` | 直接执行 task executor | 分离执行入口 | 改成发起一次普通 turn continuation 或只做状态控制 |

## 4. 目标架构：Task As Turn Overlay

### 4.1 固定执行链

目标链路：

```text
User / CLI / Graph / Scheduler event
-> runtime resolves session and active TaskRun
-> build TaskTurnOverlay from TaskRun
-> run_single_agent_turn
-> normal model action
-> normal tool execution or normal response
-> TaskStatePatchExtractor
-> update TaskRun / ActiveTurn / Monitor Projection
-> commit ordinary assistant output
```

这条链路中只有一个模型执行循环：`run_single_agent_turn`。

### 4.2 TaskRun 的系统职责

TaskRun 负责系统状态：

- identity：这个持续工作是谁；
- overlay：下一次普通 turn 应该看到什么；
- cursor：plan step / todo cursor / recovery handle；
- control：pause / resume / stop / replace；
- projection：用户看到的运行进度；
- acceptance：完成边界；
- closeout：失败、完成或中断收口。

TaskRun 不负责 agent 思考。

### 4.3 Agent 的视角

agent 只面对普通 turn。

如果本轮有 task overlay，agent 看到的是：

```text
当前有一条已绑定的持续工作。
这是它的目标、范围、当前步骤、todo 游标、用户新输入、验收边界和可用控制动作。
请继续按普通 turn 决定下一步。
```

agent 不需要被要求：

- 进入 task mode；
- 使用 task execution schema；
- 区分 task prompt 与 turn prompt；
- 解释为什么当前 turn 不足以承载任务；
- 根据 task 身份改变自己的角色。

### 4.4 `request_task_run` 的重新定位

`request_task_run` 不再定义为“agent 判断当前 turn 不足以承载工作”。

目标定义：

```text
request_task_run 是一个控制信号。
当 action surface 暴露该动作，并且当前工作需要被系统登记为持续工作对象时，
agent 可以请求系统创建 TaskRun。
系统负责验证结构、创建身份、绑定 overlay、保存状态和投影进度。
```

它的重点不是让 agent 变成 task agent，而是让系统持久化当前工作。

更进一步：

- 显式任务、CLI 任务、图任务可以由系统直接创建 TaskRun，不必伪装成 agent 自己判断。
- agent-authored `request_task_run` 只是任务创建来源之一。
- 创建之后，后续执行仍回到普通 turn。

### 4.5 active_work_control 的重新定位

`active_work_control` 不应该启动 executor。

目标行为：

- `answer_about_active_work`：普通 turn 直接回答当前任务状态。
- `append_instruction_to_active_work`：系统把新指令写入 TaskRun pending steer，然后普通 turn 可以继续或收口。
- `continue_active_work`：系统生成一次 task-bound ordinary turn continuation，而不是调用 `execute_task_run`。
- `pause_active_work`：只更新 TaskRun control state。
- `stop_active_work`：只更新 TaskRun terminal state，并释放 active turn。
- `answer_then_continue_active_work`：普通 turn 先回答，再由系统安排下一次普通 turn continuation。

## 5. Prompt 设计原则

### 5.1 不再写给 agent 的 task mode prompt

禁止写法：

```text
你现在进入任务执行模式。
根据 TaskRunContract 执行当前 task_execution。
输出 task model action。
```

原因：

这会训练 agent 使用第二套执行心智。

### 5.2 普通 turn overlay 文案

目标文案：

```text
你正在处理一个普通 turn。

本轮可能包含 current_task_overlay。
如果存在，它只是当前工作的系统状态：目标、范围、当前步骤、todo 游标、恢复点、验收边界和可用控制动作。

不要因为看到 current_task_overlay 就改变你的行动模型。
继续根据用户当前输入、可用工具、运行边界和上下文事实选择下一步。

如果用户是在提问、纠错、质疑或要求解释状态，先回应这个输入。
如果需要工具，就正常选择 tool_call。
如果可以完成，就正常 respond。
如果需要用户确认，就 ask_user。
如果要控制已绑定工作，只在 active_work_control 可用且用户输入确实指向当前工作时使用它。

current_task_overlay 是状态和约束，不是另一个 agent。
```

### 5.3 Task attention tail

尾部注意力索引应该作为普通 turn 的 volatile tail：

```json
{
  "current_task_overlay": {
    "task_run_id": "",
    "task_objective": "",
    "task_state": "active|waiting|paused|blocked|completed",
    "primary_contract": {},
    "task_shape": "",
    "active_plan_step": {},
    "todo_cursor": {},
    "pending_user_steers": [],
    "acceptance_focus": {},
    "available_controls": [],
    "agent_use_contract": "这只是当前普通 turn 的工作上下文。先回应用户当前输入，再按普通 turn 选择动作。"
  }
}
```

## 6. 状态回写模型

普通 turn 结束后，系统执行 `TaskStatePatchExtractor`。

输入：

- `turn_id`
- `task_run_id`
- `model_action_request`
- tool observations
- final answer
- active_work_control payload
- task overlay snapshot

输出：

```json
{
  "task_run_id": "",
  "status_patch": {},
  "plan_patch": {},
  "todo_cursor_patch": {},
  "acceptance_patch": {},
  "recovery_patch": {},
  "projection_events": [],
  "closeout": {}
}
```

规则：

- patch 只更新系统状态，不重新解释用户意图。
- patch 不让系统补猜 agent 没表达的语义。
- patch 来源必须可追溯到本轮 action、工具观察、用户输入或系统控制事件。
- task status 不能只因为 final answer 存在就自动 completed；必须满足 acceptance 或 agent 显式收口。

## 7. 代码升级计划

### Phase 1：锁定架构语义

目标：

- 本文通过审阅。
- 明确：普通 turn 是唯一模型执行单位。
- 明确：TaskRun 是系统 overlay 状态容器。
- 明确：task_executor 不再作为普通任务默认模型循环。

完成标准：

- 所有后续改造都以本文为准。

### Phase 2：重命名和收敛 packet 概念

涉及文件：

- `backend/harness/runtime/packet_context.py`
- `backend/harness/runtime/packet_assembler.py`
- `backend/harness/runtime/compiler.py`

目标：

- 为普通 turn 增加 `task_overlay` / `current_task_overlay` 字段。
- `single_agent_turn` packet 负责承载 task overlay。
- `task_execution` invocation kind 从普通 chat task 路径移除。
- `compile_task_execution_packet` 标记为迁移对象，不再被普通 TaskRun 调用。

完成标准：

- task-bound 普通 turn 不需要 `compile_task_execution_packet`。

### Phase 3：改造 TaskRun 启动

涉及文件：

- `backend/harness/loop/task_lifecycle.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/single_agent_turn.py`

目标：

- `start_task_lifecycle_from_action_request` 只创建 TaskRun、绑定 active turn、初始化 overlay 状态。
- 启动后不默认调用 `schedule_task_run_executor`。
- 普通 turn 可以返回“已建立持续工作”或继续在本轮执行一次普通动作。

完成标准：

- `request_task_run` 不再默认让当前 turn 终结为 `task_executor_scheduled`。
- 创建 TaskRun 后，后续推进由普通 turn continuation 完成。

### Phase 4：改造 active_work_control

涉及文件：

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/active_work.py`
- `backend/harness/current_work_receipt.py`
- `backend/harness/entrypoint/current_work_boundary.py`

目标：

- `continue_active_work` 不再调用 `execute_task_run`。
- `continue_active_work` 创建 task-bound ordinary turn continuation。
- `append_instruction_to_active_work` 写入 pending steer，并通过下一次普通 turn overlay 展示。
- `pause/stop` 只更新 TaskRun control state。

完成标准：

- active work control 不进入 task executor。

### Phase 5：拆解 task_executor

涉及文件：

- `backend/harness/loop/task_executor.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/cli/main.py`
- `backend/cli/client.py`

目标：

- 移除普通 TaskRun 的独立模型调用职责。
- 保留或迁移可复用的状态控制函数：
  - pause；
  - stop；
  - approval；
  - runtime control signal；
  - monitor projection；
  - failure closeout helper。
- CLI `task-run execute/resume` 改为发起普通 turn continuation 或状态控制。

完成标准：

- 普通任务不会经过 `_invoke_task_model_action`。
- 普通任务不会经过 `compile_task_execution_packet`。
- 普通任务 final answer 由 `single_agent_turn` 提交。

### Phase 6：TaskStatePatchExtractor

新增或改造模块：

- `backend/harness/loop/task_turn_overlay.py`
- `backend/harness/loop/task_state_patch.py`
- `backend/harness/runtime/task_contract_manifest.py`
- `backend/harness/runtime/dynamic_context/task_mode_tail_context.py`

目标：

- 普通 turn 开始前构建 `TaskTurnOverlay`。
- 普通 turn 结束后提取 `TaskStatePatch`。
- patch 更新 plan/todo/acceptance/recovery/projection。

完成标准：

- TaskRun 状态更新来自普通 turn 的结构化结果和工具观察。
- todo cursor 在 volatile tail 中持续可见。

### Phase 7：图任务迁移

涉及文件：

- `backend/task_system/graphs/*`
- `backend/task_system/graph_instances/*`
- `backend/harness/entrypoint/runtime_facade.py`

目标：

- 图节点不再默认创建 `single_agent_task` executor。
- 图节点产生普通 turn work order，并绑定 node task overlay。
- 图边读取 TaskRun patch/projection，不读取 executor 私有状态。

完成标准：

- 图任务和普通会话任务共用普通 turn 执行链。

## 8. 迁移规则

### 8.1 不保留双执行主链路

不允许长期同时存在：

```text
single_agent_turn 执行普通会话
task_executor 执行普通任务
```

原因：

这会让 prompt、工具准入、输出提交、状态回写和恢复逻辑长期分叉。

### 8.2 task_execution 只能作为迁移对象

如果短期无法一次性删除 `task_execution`，必须满足：

- 明确标记为 legacy 或 graph migration；
- 不作为普通 TaskRun 默认路径；
- 不在 agent-facing prompt 中宣传 task execution mode；
- 有明确删除条件。

### 8.3 系统不判断语义，但系统拥有生命周期

系统不能根据用户自然语言擅自猜测目标语义。

系统可以做的是：

- 根据显式任务入口创建 TaskRun；
- 根据 agent 的结构化控制信号创建 TaskRun；
- 根据 active turn binding 注入 overlay；
- 根据结构化动作和观察写回状态；
- 根据控制信号暂停、恢复、停止；
- 根据 acceptance 规则判断状态是否可关闭。

### 8.4 agent 不区分 task 与 turn

agent-facing prompt 不写：

- “你现在是 task executor”；
- “你正在任务模式下执行”；
- “task_execution action schema”；
- “当前 turn 不足以承载所以必须任务化”。

agent-facing prompt 只写：

- “这是当前普通 turn 的上下文”；
- “如果存在 current_task_overlay，把它作为当前工作状态和约束”；
- “按普通 turn 选择动作”。

## 9. 验证计划

项目规则：不新增回归测试文件，不伪造结果。

静态检查：

```powershell
rg -n "compile_task_execution_packet|_invoke_task_model_action|execute_task_run\\(|task_executor_scheduled|invocation_kind=\\\"task_execution\\\"|task_execution_action_schema" backend/harness backend/cli backend/task_system
rg -n "current_task_overlay|TaskTurnOverlay|TaskStatePatch|active_work_context|current_work_boundary_receipt" backend/harness backend/runtime
python -m compileall backend/harness/runtime backend/harness/loop backend/harness/entrypoint backend/cli backend/task_system
```

真实 CLI 验证：

```text
1. 固定后端端口 http://127.0.0.1:8003。
2. 启动普通会话 turn。
3. 触发 request_task_run，确认创建 TaskRun 但不进入 task_executor。
4. 下一次继续任务时，确认普通 turn 收到 current_task_overlay。
5. 普通 turn 调用工具，工具观察写回 TaskRun projection。
6. 普通 turn respond，TaskStatePatch 更新 acceptance / todo cursor。
7. active_work_control continue 触发普通 turn continuation，不调用 execute_task_run。
8. CLI task-run resume 触发普通 turn continuation，不调用 task_executor。
9. monitor 显示 task_run_id、active turn、overlay、todo cursor、latest turn patch 和 closeout。
```

验收不变量：

- agent 只有普通 turn 执行模型。
- TaskRun 只是系统状态覆盖层。
- 普通任务不调用 `_invoke_task_model_action`。
- 普通任务不使用 `compile_task_execution_packet`。
- task overlay 出现在 `single_agent_turn` volatile tail。
- TaskRun 状态来自 ordinary turn patch。
- final answer 由 `single_agent_turn` 提交。
- pause/resume/stop 控制 TaskRun 状态，不启动第二模型循环。

## 10. 预期结果

实施后：

- agent 不再被提示进入 task mode。
- 普通 turn 与 task-bound turn 共享同一套模型决策、工具调用、准入和输出提交路径。
- TaskRun 成为系统侧持久状态和控制外壳。
- request_task_run 只负责请求系统创建持续工作对象。
- active_work_control 只负责控制已绑定工作，不调度独立 executor。
- task prompt、task packet、task action schema 与普通 turn prompt 的分叉被收束。
- monitor、恢复、验收和 todo cursor 仍然可用，但它们来自系统 overlay 与 state patch。

## 11. 审批门槛

本文涉及 runtime、prompt、TaskRun lifecycle、active work、CLI、图任务和 task executor 权责迁移。按项目规则，实施前必须等待用户确认。

确认后应先收敛普通 chat TaskRun 主链路，再处理图任务和 CLI 的迁移。
