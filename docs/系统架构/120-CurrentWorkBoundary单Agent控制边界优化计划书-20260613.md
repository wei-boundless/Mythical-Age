# CurrentWorkBoundary 单 Agent 控制边界优化计划书

日期：2026-06-13  
状态：已审阅，已实施
范围：单 agent 当前工作边界、active turn / active work 控制、普通单轮入口、`request_task_run` 替换边界、运行时 action schema 和回归测试  
不在范围：图任务 GraphRuntime、生图任务、前端大改、模型供应商切换、TurnRun 唯一化和工具上限收口的另行计划实施

## 1. 结论摘要

本次审查结论是：当前项目已经具备 `TurnInputFacts`、`ActiveWorkContext`、`ModelActionRequest`、`ActionPermit`、`RuntimeAssembly`、Runtime Monitor public projection 等成熟组件，但还没有真正落成独立的 `CurrentWorkBoundary` 权威层。

现在“当前工作”的观察、裁决、执行、展示散落在这些位置：

- `backend/harness/runtime/request_facts.py` 只记录 facts，这是正确基础。
- `backend/harness/entrypoint/runtime_facade.py` 同时构造 active work、处理 steer 快路径、决定是否启动新任务、执行 active work 控制。
- `backend/harness/runtime/compiler.py` 通过 prompt/action schema 提示模型“有 active_work_context 时应该怎么选”，但这不是强边界。
- `backend/harness/loop/single_agent_turn.py` 在模型工具循环中接收 `active_work_control`，实际承担了部分边界仲裁。
- `backend/harness/loop/active_work.py` 能验证和归一化 active work 控制 payload，但它不是顶层边界决策源。

推荐目标是新增显式模块：

```text
TurnInputFacts
-> CurrentWorkBoundaryDecision
-> ModelTurnDecision / TaskContractAuthority
-> ActionPermit
-> RuntimeStartPacket
-> ExecutionLoop
-> OutputBoundary
```

`CurrentWorkBoundary` 必须是控制边界，不是 prompt 文案，也不是普通工具选择。它的职责是先裁定“本轮是否处在当前工作边界内，以及允许哪类动作”，再让后续 runtime 执行已经裁定的动作。

## 2. 审查依据

### 2.1 本项目源码依据

| 位置 | 证据 | 判断 |
| --- | --- | --- |
| `backend/harness/runtime/request_facts.py:8` | `TurnInputFacts` 注释明确只记录候选和约束，不分类 intent、不选择工具、不决定 active work | 保留，作为 CurrentWorkBoundary 输入 |
| `backend/harness/loop/active_work.py:97` | `ActiveWorkContext` 是当前工作可见状态结构 | 保留，但只作为 context，不拥有边界裁决 |
| `backend/harness/loop/active_work.py:147` | `active_work_turn_decision_from_payload()` 校验模型 payload，并做 alias normalization | 保留为 payload validation，不能继续承担唯一边界权威 |
| `backend/harness/entrypoint/runtime_facade.py:437` | 入口层先取 `active_work_context`，再走 `_active_turn_steer_fast_path()` | steer 是平行快路径，应该收敛到统一 CurrentWorkBoundary |
| `backend/harness/entrypoint/runtime_facade.py:625` | `_run_single_agent_turn()` 内部临时定义 `start_task()` | 新任务替换边界被塞在普通 turn wrapper 中 |
| `backend/harness/entrypoint/runtime_facade.py:665` | `_run_single_agent_turn()` 内部临时定义 `apply_active_work_control()` | active work 控制执行和边界解析混在入口 wrapper 中 |
| `backend/harness/entrypoint/runtime_facade.py:994` | `_prepare_current_task_for_new_task_request()` 在 request_task_run 时直接停止当前任务 | 替换边界应该由 CurrentWorkBoundary receipt 驱动 |
| `backend/harness/runtime/compiler.py:2067` | 普通 schema 同时开放 `respond/ask_user/tool_call/request_task_run/block` | active work 存在时普通工具与控制动作仍共享同一决策面 |
| `backend/harness/runtime/compiler.py:2272` | `_single_agent_turn_allowed_actions()` active work 存在时追加 `active_work_control` | schema 暴露不是边界裁决 |
| `backend/harness/runtime/compiler.py:4217` | prompt 规则要求模型在 active context 中选择 active_work_control | 目前主要依赖 prompt/model 自律，不是硬边界 |
| `backend/harness/loop/single_agent_turn.py:867` | 工具循环中捕获 `active_work_control` 并执行 | 执行环参与边界分支，职责过宽 |
| `backend/harness/loop/single_agent_turn.py:1678` | final dispatch 中仍处理 `request_task_run` | 普通执行环可以启动长期任务，需由 boundary/action permit 限制 |
| `backend/harness/runtime/active_turn.py:63` | `ActiveTurnRegistry` 声称是 current-turn authority，但 boundary 计划未把它列为改造对象 | 必须把 active turn 匹配、绑定、terminal 化纳入 boundary receipt 的原子校验 |
| `backend/harness/runtime/assembly.py:880` | `may_control_active_work` 默认由 context policy 推导，可能早于 boundary 决定 | control capability 只能表示服务面能力，不能直接导致普通 packet 暴露 active_work_control |
| `backend/memory_system/runtime_context_provider.py:245` | session emphasis / memory context 仍有关键词式注入条件 | 只能作为弱上下文候选，不得影响 current work 裁决或控制动作开放 |
| `backend/api/chat_direct_routes.py:19` | direct system route 当前位于 boundary 之前，且会直接提交 assistant 输出 | 当前 image direct route 属于本计划 out-of-scope；后续任何单 agent/control direct route 都不得绕过 CurrentWorkBoundary |

### 2.2 现有测试依据

当前测试已经保护了一些成熟约束：

- `backend/tests/active_turn_authority_regression.py:355`：普通补充不应靠关键词变成暂停，必须使用模型结构化 decision。
- `backend/tests/active_turn_authority_regression.py:434`：active turn 缺失时，steer 不应提升历史 waiting task。
- `backend/tests/harness_model_action_protocol_regression.py:680`：`active_work_control` 接受 intent alias，但仍必须是结构化 action。
- `backend/tests/harness_model_action_protocol_regression.py:706`：裸 active work payload 不合法，必须走 JSON action protocol。
- `backend/tests/dynamic_prompt_context_projection_test.py:1678`：prompt 明确 active work 是 current active-turn-bound work，不是 latest-task fallback。

缺口是：测试还没有证明 `CurrentWorkBoundaryDecision` 是唯一入口，也没有证明普通 single-agent turn 在 boundary 已裁定后不能二次开放 `active_work_control` 或替换当前任务。

### 2.3 6 月 5 日体系对照

6 月 5 日计划位于项目外：`D:\AI应用\新文档\245-当前工作续接与单轮终止权威重构计划书-20260605.md`。它已经把问题定义成：

```text
RequestFacts
-> BoundaryPolicy / CurrentWorkControl
-> RuntimeStartPacket
-> ExecutionLoop
-> OutputBoundary
-> DurableState
-> Runtime Public Projection
-> PublicStream
```

当晚体系重点解决的是：

- 用户说“继续”后被普通 single-agent turn 截断。
- 工具上限收口和 public `done` 过早导致 TurnRun / ChatRun 状态分裂。
- 输出协议泄漏可能被持久化为稳定答案。
- TurnRun ID 复用。

本计划只承接其中的单 agent 当前工作控制边界，不把 6 月 5 日计划中的 TurnRun 唯一化、工具上限收口、OutputBoundary 协议泄漏修复、前端 public projection 重构并入本次实施。那些内容保留为独立计划或既有计划的验收项。

当前源码相较 6 月 5 日已有进步：

- `TurnInputFacts` 已明确不裁决 intent。
- active turn 不再从历史 waiting task 自动恢复。
- active work prompt 已强调 current active-turn-bound work。
- active work 控制 payload 需要结构化 action。
- public response obligation 已开始约束工具调用前的公开回应。

仍未完成的是：6 月 5 日提出的 `CurrentWorkBoundary` 没有独立成层。现在实际链路仍是“入口层拿到 active work 候选，然后把 active_work_context 放入普通模型 action schema，由模型在普通 turn 内选择 active_work_control / request_task_run / tool_call / respond”。这会让 prompt 规则、入口 wrapper、执行环、payload validator 共同承担边界裁决，权威分裂仍存在。

6 月 5 日计划还要求 `waiting_executor` / `blocked` / runtime restart recovery 能被 current-work 控制面直接续跑。本计划对此做收窄：没有 active-turn-bound `active_work_context` 时，不把 latest waiting / resumable TaskRun 直接提升为 current work。持久化 TaskRun 恢复需要另建 `TaskRecoveryBoundary` 或显式 recovery receipt，不能混入 `CurrentWorkBoundary`。

### 2.4 后续本地计划冲突收敛

本仓库后续已有两个相关计划会影响实施判断，必须在本计划中明确取舍：

- `backend/maintenance/agent_task_todo_subagent_runtime_repair_plan_20260608.md:32` 曾要求“删除旧 current-work boundary 层，保留 active turn id 守卫”，并把 current work 语义交给主模型的 `active_work_control`。这个方向已不足以解决当前“普通工具循环二次裁决 current work”的问题，本计划以 6 月 5 日的 `CurrentWorkBoundary` 方向为准，取代该条旧设计。
- `docs/系统规划/246-Agent运行期Steer与Runtime私有边界治理计划书-20260611.md:490` 把 `_active_turn_steer_fast_path()` 作为 active steer 目标流。该目标中的“steer 不能退回普通 single-agent turn / 不能被模型改成 replacement”继续保留，但实现形态不再是独立 fast path，而是并入 `CurrentWorkBoundary` hard gate 和 receipt。
- 旧计划允许后端重启后在用户明确控制时恢复 latest recoverable TaskRun；本计划不在 `CurrentWorkBoundary` 中实现该恢复。该能力只能通过独立 `TaskRecoveryBoundary` 落地，避免 current work 与 durable recovery 共用一个权威对象。

### 2.5 Codex 源码借鉴

本地 Codex 源码显示成熟 agent 对 active turn 的处理原则是“状态权威集中，控制请求必须匹配当前 active turn”：

- `D:\AI应用\openai-codex\codex-rs\app-server\src\thread_state.rs:73`：`ThreadState` 集中保存 pending interrupts、pending rollbacks、last terminal turn、listener generation、current turn history。
- `D:\AI应用\openai-codex\codex-rs\app-server\src\thread_state.rs:136`：`active_turn_snapshot()` 统一返回当前 active turn。
- `D:\AI应用\openai-codex\codex-rs\app-server\src\thread_state.rs:140`：`track_current_turn_event()` 统一跟踪 turn start / terminal，并在无 active turn 后记录 terminal turn。
- `D:\AI应用\openai-codex\codex-rs\app-server\src\request_processors\turn_processor.rs:761`：steer 请求必须有非空 expected turn id。
- `D:\AI应用\openai-codex\codex-rs\app-server\src\request_processors\turn_processor.rs:783`：steer 只注入当前 active turn。
- `D:\AI应用\openai-codex\codex-rs\core\src\session\mod.rs:3115`：`steer_input()` 明确“Inject additional user input into the currently active turn”，并返回被接受的 active turn id。
- `D:\AI应用\openai-codex\codex-rs\core\src\session\mod.rs:3130`：active turn 检查、expected id 匹配、非 steerable turn 拒绝在同一边界内完成。
- `D:\AI应用\openai-codex\codex-rs\core\src\state\turn.rs:28`：`ActiveTurn` / `TurnState` 是 turn-scoped 状态容器，pending approval、pending input、granted permissions 等不散落到普通工具循环里。

可借鉴原则：

1. active turn 状态必须有单一读取和匹配权威。
2. steer / interrupt / approval 不能从历史任务或普通上下文猜测。
3. 控制动作必须产生明确接受或拒绝结果，不应静默转成其他工具动作。
4. active turn 检查和状态更新需要原子化，不能分散到多个 wrapper 和执行环。

### 2.6 Claude Code 源码借鉴

本地 Claude Code 源码和源码研究文档显示成熟 agent 会把输入 guard、工具集合、权限判定、prompt cache 边界拆开：

- `D:\AI应用\claude-code-nb-main\utils\handlePromptSubmit.ts:313`：当 `queryGuard.isActive` 或 external loading 存在时，新输入先进入队列或中断逻辑，而不是启动第二个执行循环。
- `D:\AI应用\claude-code-nb-main\utils\handlePromptSubmit.ts:431`：在 `processUserInput` 之前 reserve guard，确保并发输入被排队，而不是并发进入执行。
- `D:\AI应用\Claude-Code-Source-Study-main\docs\25-架构模式总结.md:180`：工具注册是单一来源加多层过滤，不让执行层临时发明工具边界。
- `D:\AI应用\Claude-Code-Source-Study-main\docs\25-架构模式总结.md:526`：权限判定是多步管线，deny/ask/tool permission/safety/bypass mode 有清晰优先级。

可借鉴原则：

1. 输入控制 guard 在模型和工具循环之前。
2. 工具可见性和权限是过滤管线，不靠模型自然语言约束。
3. 控制系统应产出结构化 decision / receipt，后续层只执行和记录。

## 3. 真实问题定义

当前问题不是“继续”关键词识别不足，也不是 `active_work_control` payload 不够丰富，而是缺少一个介于 `TurnInputFacts` 和普通模型 action 之间的硬边界。

系统正确终态应满足：

1. `TurnInputFacts` 只观察事实。
2. `CurrentWorkBoundary` 先决定本轮是否处于 current work 边界。
3. 如果处于 current work 边界，普通工具调用不能同时开放。
4. 如果允许独立新请求，必须带有 boundary receipt，后续普通 turn 不再重新裁决 active work。
5. 如果用户要求替换当前工作，必须由 boundary receipt 驱动旧任务收口和新任务启动。
6. steer、普通 active work 输入、request_task_run 替换必须汇合到同一边界出口。
7. 输出层只展示控制回执或 Runtime Monitor public projection，不消费 raw active work event 作为正文。

## 4. 目标设计

### 4.1 新增模块

新增：

```text
backend/harness/entrypoint/current_work_boundary.py
```

目标对象：

```python
CurrentWorkBoundaryInput
CurrentWorkBoundaryDecision
CurrentWorkBoundaryReceipt
CurrentWorkBoundaryAuthority
```

### 4.2 CurrentWorkBoundaryInput

输入只允许来自事实和系统状态，不允许从 prompt 文本反推：

```text
turn_input_facts
active_turn_record
active_work_context
current_task_collision_candidate
request_active_turn_policy
active_turn_input_policy
expected_active_turn_id
runtime_branch
control_capabilities
context_policy
editor_context_summary
```

禁止：

- 选择具体工具。
- 启动 TaskRun。
- 写入 session message。
- 生成用户最终正文。
- 从历史 waiting task 推断 active work。

`current_task_collision_candidate` 只用于判断新任务或 replacement 是否需要先收口旧 TaskRun，不是 current work control 的来源。没有 active-turn-bound `active_work_context` 时，不得把最新 waiting / resumable TaskRun 直接提升为可控制当前工作；若后续要支持 durable TaskRun 恢复，必须另建 `TaskRecoveryBoundary` 或显式 recovery receipt，不能混入本层。

### 4.3 CurrentWorkBoundaryDecision

锁定动作集合：

```text
no_current_work
current_work_control_required
continue_active_work
append_instruction_to_active_work
answer_about_active_work
answer_then_continue_active_work
pause_active_work
stop_active_work
new_independent_turn_allowed
replace_current_work
ask_user
block
```

必要字段：

```text
decision_id
turn_id
session_id
action
relation_to_current_work
active_work_id
task_run_id
expected_active_turn_id
actual_active_turn_id
allowed_next_actions
forbidden_next_actions
reason
evidence
public_response_obligation
requires_model_boundary_decision
authority = "harness.entrypoint.current_work_boundary"
```

设计约束：

- `current_work_control_required` 是边界结果，不是普通 model action。
- `new_independent_turn_allowed` 不是默认兜底，必须记录为什么本轮不是当前工作。
- `replace_current_work` 必须记录替换关系，后续由执行层停止旧任务。
- `ask_user` / `block` 必须公开说明，不允许静默变成工具调用。
- `active_turn_input_policy=steer` 且 active turn 匹配时，语义动作范围被收窄为 current work 控制、append、answer、ask_user、block；不得返回 `new_independent_turn_allowed`。如果用户在 steer 通道提出无关问题，应 `ask_user` 说明需要从普通输入发起，不能退回普通 single-agent turn。
- `active_turn_input_policy=steer` 下只有用户明确要求重启、替换或放弃当前工作时才允许 `replace_current_work`；不能把普通补充文本升级为 replacement。

### 4.4 CurrentWorkBoundaryReceipt

receipt 是后续层唯一可消费的边界凭证：

```text
receipt_id
decision_id
boundary_action
execution_route
active_work_ref
task_run_ref
turn_ref
runtime_branch_ref
allowed_action_types_for_next_packet
active_work_control_payload
replacement_policy
public_projection_policy
diagnostics
authority = "harness.entrypoint.current_work_boundary_receipt"
```

后续层只能根据 receipt 开放 action schema：

- `no_current_work`：进入普通 single-agent turn，不暴露 active_work_control。
- `new_independent_turn_allowed`：进入普通 single-agent turn，active work 只作为 read-only boundary receipt，不暴露 active_work_control。
- `current_work_control_required` / 具体 current work 控制动作：进入 control-only branch，不开放普通 `tool_call`。
- `replace_current_work`：允许 `request_task_run`，但必须先执行 replacement receipt，不能在普通 action 中临时停止旧任务。
- `ask_user` / `block`：直接进入公开收口，不进入普通工具循环。

## 5. 固定执行流

目标执行流：

```text
1. runtime_facade 接收 HarnessRuntimeRequest
2. direct_system_route
3. assemble_runtime
4. build_turn_input_facts
5. CurrentWorkBoundaryAuthority.decide()
6. emit current_work_boundary_decided event
7. 根据 boundary receipt 分流：
   7.1 no_current_work -> run_single_agent_turn
   7.2 new_independent_turn_allowed -> run_single_agent_turn_without_active_work_control
   7.3 current work control -> apply_current_work_boundary_decision
   7.4 replace_current_work -> prepare replacement, then task request branch
   7.5 ask_user/block -> terminal final event
8. ActionPermit / admission 只验证 receipt 允许的动作
9. ExecutionLoop 执行，不再重判 active work 边界
10. OutputBoundary / Runtime Monitor public projection 展示
```

`direct_system_route` 是固定执行流中的唯一前置例外。它只能服务明确 out-of-scope 的系统路由，例如当前的 image generation；它不得处理 single-agent/current-work/control 语义，也不得成为绕过 `CurrentWorkBoundary` 的新入口。

### 5.1 控制模型的使用方式

禁止硬编码“继续”“暂停”等关键词。对于语义不明显的输入，允许调用一个窄 schema 的 boundary model decision，但它必须与普通工具循环隔离。

Boundary prompt 必须是 agent 可执行的角色说明，不能写成开发节点说明：

```text
你是当前工作边界裁决员。
你只判断用户这一轮输入与系统暴露的当前工作之间的关系。
你不执行工具，不改文件，不启动任务，也不生成最终交付物。
你需要在给定的结构化动作中选择一个，并说明依据。
如果用户明确是在继续、暂停、停止、补充、追问或纠正当前工作，选择对应的 current work 控制动作。
如果用户提出的是独立问题或新的无关请求，选择 new_independent_turn_allowed，并说明为什么它不应控制当前工作。
如果用户要求用新任务替换当前工作，选择 replace_current_work。
如果 active turn id 不匹配、当前工作已失效或关系不清，选择 ask_user 或 block。
如果本轮 active_turn_input_policy 是 steer，且 active turn 已通过硬校验，你不能选择 new_independent_turn_allowed；无关问题应选择 ask_user 或 block，说明这条输入没有接入当前任务。
你的输出必须是结构化 JSON，不得请求普通工具调用。
```

### 5.2 硬边界优先级

硬边界不交给模型判断：

1. `active_turn_input_policy=steer` 且 `expected_active_turn_id` 缺失：block。
2. `active_turn_input_policy=steer` 且 expected id 与 actual active turn 不匹配：block。
3. `active_turn_input_policy=steer` 且没有 active turn：block，不提升历史 waiting task。
4. active work context 不是 `harness.runtime.active_turn_context`：不允许 steer 控制。
5. active work 已 terminal：不允许 current work control，只能作为 recent outcome 只读事实。
6. `active_turn_input_policy=steer` 已通过 active turn 校验后，不允许分流到 `new_independent_turn_allowed`。
7. control branch 中不得开放普通 `tool_call`。
8. boundary denial 不得自动改成替代工具动作。
9. transient active turn 如果没有 `bound_task_run_id`，只代表当前模型 turn handle，不是 current work。
10. context policy / memory / session emphasis / recent outcome 只能提供候选事实，不能开放 active_work_control。
11. direct system route 只有在明确 out-of-scope 且不会控制单 agent 当前工作时可先行；任何单 agent 控制类直达路由必须位于 CurrentWorkBoundary 之后。

语义边界才交给 boundary model：

- 用户是在问状态，还是要求继续。
- 用户是在补充当前任务，还是提出独立问题。
- 用户是在要求替换当前工作，还是只是追加约束。
- 用户问题是否需要先回答再继续。

## 6. 权威表

| 层 | 当前问题 | 目标权威 | 文件动作 |
| --- | --- | --- | --- |
| Observe | `TurnInputFacts` 已正确，但后续层仍可直接消费 active_work_context 做决策 | `TurnInputFacts` 只输出事实 | 保留 `backend/harness/runtime/request_facts.py` |
| Boundary | 入口层、compiler prompt、single_agent_turn、active_work payload validator 共同裁决 | `CurrentWorkBoundaryAuthority` 唯一裁决 current work 关系 | 新增 `backend/harness/entrypoint/current_work_boundary.py` |
| Model Decision | 普通 schema 同时开放 active_work_control/request_task_run/tool_call | 根据 boundary receipt 编译不同 action schema | 修改 `backend/harness/runtime/compiler.py` |
| Authorization | `admit_model_action` 只知道 allowed action types，不知道 current work receipt | ActionPermit 校验 action 是否被 receipt 授权 | 在 `RuntimeInvocationPacket` 携带 boundary receipt，并让 admission 使用 receipt 派生出的 allowed action types；不得再用 active_work_context 重新放权 |
| Execution | `single_agent_turn` 执行 active_work_control 并可 request_task_run | ExecutionLoop 只执行已允许动作，不裁决当前工作 | 收敛 `backend/harness/loop/single_agent_turn.py` |
| Task lifecycle | `_prepare_current_task_for_new_task_request()` 临时停止旧任务 | 替换由 `replace_current_work` receipt 驱动 | 移动决策部分，保留执行函数 |
| Presentation | active_work 观察和 runtime status 可见，但不应成为主正文推断 | 控制回执 + Runtime Monitor public projection | 保持 `backend/api/chat.py` / projector，不重做前端投影 |
| Active turn state | `ActiveTurnRegistry` 是状态权威，但 start/bind/complete 分散被调用 | Boundary receipt 校验 expected/actual turn、task binding、owner instance 和 terminal 状态 | 修改 `backend/harness/runtime/active_turn.py`，新增 compare-and-update helper 并补测试 |
| Context candidates | assembly/context/memory 会把 active work 和关键词信号注入 prompt | 只允许作为候选上下文，不允许改变 allowed actions | 修改 `backend/harness/runtime/assembly.py`、`backend/memory_system/runtime_context_provider.py` 的边界约束和测试 |

## 7. 文件级改造计划

### 7.1 新增 `backend/harness/entrypoint/current_work_boundary.py`

职责：

- 定义 boundary input / decision / receipt dataclass。
- 提供 hard gate。
- 提供 semantic boundary schema parser。
- 提供 receipt builder。
- 不调用工具、不写 session、不启动 task。

必须实现函数：

```python
build_current_work_boundary_input(...)
decide_current_work_boundary(...)
current_work_boundary_decision_from_payload(...)
current_work_boundary_receipt_from_decision(...)
```

完成标准：

- 单元测试可直接构造 input 并验证 decision。
- 没有 active work 时稳定返回 `no_current_work`。
- stale steer 稳定返回 `block`。

### 7.2 修改 `backend/harness/entrypoint/runtime_facade.py`

改造点：

- 在 `build_turn_input_facts()` 后、`_run_single_agent_turn()` 前调用 boundary。
- 将 `_active_turn_steer_fast_path()` 降级为 boundary receipt 的事件投影 helper；如果无法保持单一 authority，则删除该函数。
- 将 `apply_active_work_control()` 从 `_run_single_agent_turn()` wrapper 中迁出，改成 `apply_current_work_boundary_decision()`。
- 将 `_prepare_current_task_for_new_task_request()` 中“是否替换”的决策迁到 boundary，只保留执行旧任务收口的函数。
- `_active_turn_control_guard()`、`_active_turn_steer_terminal_events()`、`_apply_active_work_turn_decision()`、`_apply_continue_active_work()`、`_apply_append_instruction_to_active_work()`、`_bind_current_turn_to_task_run()`、`_complete_active_turn_for_task_run()` 必须全部变成 receipt 执行链下的 helper，或迁入新的 control executor；这些 helper 不得再读取上下文后自行判断本轮是否属于 current work。
- 现有 active turn 校验只能通过 `ActiveTurnRegistry.compare_and_update_current_turn()` 或其返回结果进入 receipt，不能在 facade helper 内重复 snapshot 后得出第二套结论。
- 所有 current work 分流都 emit `current_work_boundary_decided`。
- `direct_system_route` 当前只服务 image generation，属于本计划 out-of-scope；实施时必须加注释和测试，禁止未来新增单 agent/control direct route 绕过 boundary。

完成标准：

- 入口层只 orchestrate，不再同时承担语义裁决。
- active turn stale、current work control、independent turn、replacement 都有同一 receipt。

### 7.3 修改 `backend/harness/runtime/compiler.py`

改造点：

- 新增 `compile_current_work_boundary_packet()`，只装配 boundary decision 窄 schema。
- 普通 `compile_single_agent_turn_packet()` 接收 `current_work_boundary_receipt`。
- 当 receipt 不是允许 active work 控制时，普通 packet 不再追加 `active_work_control`。
- 当 receipt 是 `new_independent_turn_allowed` 时，active work 只作为 read-only receipt，不作为可控上下文。
- prompt 中现有 active_work_context 规则改为解释 receipt，而不是要求模型自己裁决边界。
- `compile_single_agent_turn_packet()` 不再直接从 `active_work_context` 推导 `active_work_control`，只能从 `current_work_boundary_receipt.allowed_action_types_for_next_packet` 推导。

完成标准：

- `allowed_action_types` 不再因为 active_work_context 存在而自动包含 `active_work_control`。
- boundary control branch 中不暴露普通工具。
- prompt 文案符合“角色、职责、边界、输入、输出、裁决标准”规则。

### 7.4 修改 `backend/harness/loop/active_work.py`

改造点：

- 保留 `ActiveWorkContext`。
- 将 `ActiveWorkTurnDecision` 定位为 control payload validation。
- 增加 `CurrentWorkBoundaryDecision.to_active_work_turn_decision()`，由 boundary decision 显式转换为 `ActiveWorkTurnDecision`。
- 收窄 alias 使用范围：alias 只能兼容模型 payload 字段，不能作为自然语言关键词分类器。

完成标准：

- `active_work_turn_decision_from_payload()` 不再是唯一边界决策源。
- relation 不清时返回 denied，但 denied 由 boundary receipt 转成 ask/block，不自动替代为普通 action。

### 7.5 修改 `backend/harness/loop/single_agent_turn.py`

改造点：

- 移除普通工具循环中的 active work 边界裁决职责。
- 将已授权 `active_work_control` 的执行迁出为 entrypoint 层 control executor；`single_agent_turn` 不再接收 `apply_active_work_control` 闭包。
- final dispatch 中 `active_work_control` 不应出现 unreachable protocol error，应该在 schema 层不让它进入 final dispatch。
- `request_task_run` 只在 boundary/action schema 允许时进入 task lifecycle。
- 对显式合同任务分支同样适用 replacement receipt，不能让 `_run_explicit_contract_task_turn()` 通过旧 `_prepare_current_task_for_new_task_request()` 绕过 boundary。

完成标准：

- `single_agent_turn` 不再决定“这轮是不是当前工作”。
- `tool_loop` 只处理普通工具和已授权控制观察。

### 7.6 修改 `backend/harness/loop/model_action_protocol.py`

改造点：

- 普通 `ModelActionRequest` 继续验证 action type。
- 新增 `CurrentWorkBoundaryActionRequest`，避免把 boundary decision 塞进普通 model action。
- `active_work_control` 的 action 必填校验保持。
- public response obligation 和 boundary receipt 的关系明确：控制类 action 必须有公开回执意图；纯控制不需要普通 assistant 正文时，也必须由 runtime_control/status 事件给出用户可理解的状态 detail，不能以空白输出替代回应。

完成标准：

- boundary schema 和普通 action schema 不混用。
- 不允许裸 active work payload。

### 7.7 修改 `backend/harness/runtime/active_turn.py`

改造点：

- 将 expected turn id、actual turn id、bound task run id、owner instance、terminal state 的校验结果暴露给 boundary receipt。
- 新增 `compare_and_update_current_turn()` helper，让 boundary 执行控制动作前的校验和状态更新保持单一入口。该 helper 必须返回结构化 check/receipt 片段，至少包含 expected/actual turn id、expected/actual task_run_id、owner instance、terminal reason、accepted/denied reason。
- transient active turn 没有 bound task run 时，不得被投影成 current work。

完成标准：

- stale expected id、runtime instance restarted、bound task terminal、bound task missing 都有明确 boundary denial。
- active turn start/bind/complete 的测试不只看状态，还检查 boundary receipt 是否引用正确 turn/task。
- facade 层不得保留第二套 `_active_turn_control_guard()` 结论；若保留函数名，它只能委托 `compare_and_update_current_turn()`。

### 7.8 修改 `backend/harness/runtime/assembly.py` 与 memory context

改造点：

- `may_control_active_work` 只表示运行服务面支持控制，不再直接等于本轮允许 active_work_control。
- `context_policy.active_work_context=available` 只允许提供候选事实，不允许改变 action schema。
- `should_inject_session_emphasis()` 中的关键词命中只能触发候选上下文读取，不能作为 current work relation 证据。
- `RuntimeMemoryContextProvider` 注入 active work / recent outcome 时必须带 `read_only_context` 或 receipt ref，避免被 prompt 当成控制授权。

完成标准：

- 无 boundary receipt 时，memory/context 注入不会让 compiler 暴露 active_work_control。
- 有 independent receipt 时，active work 相关上下文只能作为只读背景，不能成为可控制工作。

### 7.9 修改测试

新增测试：

```text
backend/tests/current_work_boundary_regression.py
backend/tests/current_work_boundary_facade_regression.py
```

补充现有：

```text
backend/tests/active_turn_authority_regression.py
backend/tests/harness_model_action_protocol_regression.py
backend/tests/dynamic_prompt_context_projection_test.py
backend/tests/harness_context_policy_regression.py
backend/tests/task_executor_diagnostics_projection_test.py
```

## 8. 分阶段实施计划

### Phase 0：基线确认

目标：锁定当前行为，不改代码。

动作：

- 跑 active turn / model action protocol / context projection 相关测试。
- 记录当前 `allowed_action_types` 中 active_work_control 的暴露条件。
- 记录 stale steer、valid steer、ordinary active work input 的事件序列。

完成标准：

- 得到可复现 baseline。
- 确认 dirty worktree 中用户已有改动不被覆盖。

### Phase 1：建立数据模型和 hard gate

目标：先让 `CurrentWorkBoundary` 成为显式对象。

动作：

- 新增 `current_work_boundary.py`。
- 实现 input / decision / receipt。
- 实现 deterministic hard gate。
- 添加纯单元测试。

完成标准：

- no current work、stale steer、mismatched active turn、terminal task、valid current work candidate 都有明确 decision。

### Phase 2：入口层接入统一 boundary

目标：让 steer fast path 和普通 active work candidate 汇合。

动作：

- `runtime_facade.py` 在普通 single-agent turn 前调用 boundary。
- `_active_turn_steer_fast_path()` 改为 boundary hard gate 的事件投影，或删除平行分支。
- 所有 branch emit `current_work_boundary_decided`。
- 显式合同任务和普通 `request_task_run` 都必须通过同一 replacement receipt。
- `active_turn_input_policy=steer` 的有效输入不得退回普通 single-agent turn；无关输入走 `ask_user/block`，明确 replacement 才走 `replace_current_work`。

完成标准：

- `active_turn_input_policy=steer` 不再走一套独立 authority。
- 缺失 active turn 时仍 fail closed，不提升历史 task。
- 有效 steer 的普通补充只会进入 current work control/append/answer 路径，不会被普通模型裁决为新任务。

### Phase 3：新增 boundary model decision packet

目标：语义边界不靠关键词，不走普通工具 loop。

动作：

- 在 compiler 中新增 current work boundary packet。
- 只允许输出 boundary action JSON。
- 添加 boundary prompt。
- 解析为 `CurrentWorkBoundaryDecision`，再由 hard validator 二次校验。
- boundary packet 不加载普通工具，不读取 memory 弱信号来改写 allowed actions。

完成标准：

- 用户问“为什么卡住”时可以得到 `answer_about_active_work`。
- 用户说“继续但先说明原因”时可以得到 `answer_then_continue_active_work`。
- 普通入口中用户提出独立问题时可以得到 `new_independent_turn_allowed`。
- steer 入口中用户提出独立问题时得到 `ask_user/block`，不退回普通工具循环。
- 以上过程不开放普通工具。

### Phase 4：control-only branch 执行

目标：当前工作控制动作直接执行 receipt。

动作：

- 从 `_run_single_agent_turn()` wrapper 中迁出 `apply_active_work_control()`。
- 用 `apply_current_work_boundary_decision()` 执行 continue/pause/stop/append/answer。
- 保留 active work observation 和 public projection，但不让它反过来裁决边界。
- 删除或委托 facade 内旧 active turn guard / apply helper 的决策权，所有执行 helper 只能消费 receipt。

完成标准：

- 明确继续当前工作时，不触发普通 `tool_call`。
- append instruction 后事件仍绑定同一个 `task_run_id`。
- pause/stop 不会被普通工具替代。

### Phase 5：request_task_run 替换收敛

目标：替换当前工作由 boundary receipt 驱动。

动作：

- `replace_current_work` receipt 先执行旧任务收口。
- `_prepare_current_task_for_new_task_request()` 改名/拆分为执行函数，不再决定是否替换。
- `task_contract_seed.active_work_relationship` 仅作为模型声明，不作为唯一替换权威。

完成标准：

- 有 current work 时，只有 boundary 允许 replace，才可启动替换任务。
- 替换失败时 block，不启动新任务。
- 替换成功记录 replacement receipt。

### Phase 6：普通 single-agent schema 收紧

目标：boundary 已裁定后，普通模型 action 不再二次裁决 current work。

动作：

- `compile_single_agent_turn_packet()` 根据 receipt 计算 allowed actions。
- `new_independent_turn_allowed` 下不暴露 active_work_control。
- `no_current_work` 下不暴露 active_work_context。
- `replace_current_work` 下才允许 request_task_run replacement。
- `assembly.control_capabilities.may_control_active_work` 不再直接进入普通 packet allowed actions。
- `session_emphasis` / memory context 不得覆盖 receipt。

完成标准：

- active work context 存在不再自动导致 `active_work_control` 可用。
- prompt 中 current work 说明从“你自己判断”变成“按 boundary receipt 行动”。

### Phase 7：测试与旧路径删除

目标：防止双链路残留。

动作：

- 删除或收敛 parallel steer fast path。
- 搜索旧 authority 字符串，确认不再出现两个 current work branch。
- 更新测试，不保护旧内部 shape。

完成标准：

- 搜索 `_active_turn_steer_fast_path` 不再是独立执行入口。
- 搜索 `request_task_run_while_current_work_exists` 只在 replacement receipt 执行记录中出现。
- 所有 current work 控制测试都能检查 boundary receipt。
- 搜索 direct route、memory emphasis、context policy，确认没有绕过 boundary 的 action 开放路径。
- 搜索 facade 内 active turn guard / apply helpers，确认没有 helper 在 receipt 外重判 current work。

## 9. 删除与收敛规则

必须删除或收敛：

1. `_active_turn_steer_fast_path()` 作为独立分支的权威地位。
2. active work 存在时自动在普通 schema 暴露 `active_work_control` 的逻辑。
3. `_run_single_agent_turn()` wrapper 内部临时定义并持有 active work 边界执行闭包的结构。
4. `_prepare_current_task_for_new_task_request()` 中的“是否替换”决策。
5. prompt 中把 active work 关系判断完全交给普通模型 action 的规则。
6. 任何基于自然语言关键词直接决定 pause/continue/stop 的逻辑。
7. facade 内绕过 receipt 的 active turn guard / apply helper 决策权。

允许保留：

1. `ActiveWorkContext` 作为模型可见状态摘要。
2. `active_work_turn_decision_from_payload()` 作为结构化 payload validator。
3. Runtime Monitor public projection 作为公开展示权威。
4. 历史事件读取兼容，但不得作为新运行路径。

## 10. 验证矩阵

### 10.1 单元测试

```powershell
pytest backend/tests/current_work_boundary_regression.py -q
pytest backend/tests/harness_model_action_protocol_regression.py -k "active_work or boundary or request_task_run" -q
pytest backend/tests/dynamic_prompt_context_projection_test.py -k "active_work" -q
```

必须覆盖：

- no current work -> 普通 turn。
- valid active turn + steer -> boundary receipt。
- stale expected active turn -> block before model。
- valid steer + unrelated text -> ask_user/block，不进入 `new_independent_turn_allowed`。
- active turn missing + historical waiting task -> block / no current work，不提升历史任务。
- active work terminal -> recent outcome read-only，不可控制。
- relation ambiguous -> ask_user 或 block，不转普通工具。

### 10.2 Facade 回归

```powershell
pytest backend/tests/current_work_boundary_facade_regression.py -q
pytest backend/tests/active_turn_authority_regression.py -q
pytest backend/tests/harness_context_policy_regression.py -q
```

必须覆盖：

- 有 current work + 明确继续：不触发普通 `tool_call`。
- 有 current work + 状态问题：先 answer，不静默继续。
- 有 current work + 追加要求：append instruction 绑定同一个 task_run。
- 有 current work + 独立问题：进入 `new_independent_turn_allowed`，普通 turn 不暴露 active_work_control。
- `active_turn_input_policy=steer` + 有效 active turn + 独立问题：不进入 ordinary turn，返回 ask_user/block。
- 有 current work + 新任务替换：必须有 replacement receipt。
- boundary denial 不会变成替代工具动作。

### 10.3 Compiler / Prompt 回归

```powershell
pytest backend/tests/dynamic_prompt_context_projection_test.py -q
pytest backend/tests/prompt_accounting_ledger_test.py -k "active_work or boundary" -q
```

必须覆盖：

- boundary control packet 不含普通工具。
- ordinary packet 不因 active work candidate 自动暴露 control。
- prompt 不出现开发节点说明式文本。
- prompt 描述角色、职责、边界、输出和裁决标准。

### 10.4 运行链路验证

涉及运行链路改动后必须真实启动固定端口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action start -FrontendMode dev
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action check
```

固定节点：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8003`

人工验证：

1. 启动一个 running active work。
2. 输入“继续处理刚才任务”。
3. 确认事件中先出现 `current_work_boundary_decided`。
4. 确认没有普通工具先运行。
5. 确认同一个 task_run 继续更新。
6. 输入“刚才为什么卡住了？”。
7. 确认得到状态回答，不静默 resume。
8. 输入一个完全无关的一次性问题。
9. 确认进入 independent ordinary turn，且不控制当前 task。

## 11. 迁移与切换规则

本计划不允许长期双链路。实施期间可以短暂 shadow，但必须有明确切换点和删除点。

### 11.1 Shadow 规则

- Phase 1 可以只生成 `CurrentWorkBoundaryDecision` / `Receipt` 并记录事件，不改变运行分流。
- Shadow 事件必须标记 `enforced=false`，不能被 compiler、single_agent_turn 或前端展示层消费为授权。
- Shadow 期只允许用于对比：旧路径选择了什么、新 boundary 会选择什么。
- Shadow 期结束条件：核心场景测试覆盖 stale steer、valid steer、status question、append instruction、independent turn、replacement。

### 11.2 Cutover 规则

- Cutover 后，`current_work_boundary_receipt.enforced=true` 是 active_work_control / replacement / independent ordinary turn 的唯一入口凭证。
- Cutover 后，`active_work_context`、`may_control_active_work`、session emphasis、recent outcome 都不能单独让 compiler 暴露 active_work_control。
- Cutover 后，`_active_turn_steer_fast_path()` 不能继续作为独立 authority；若保留函数名，只能是 boundary receipt 的事件投影 helper。
- Cutover 后，`_prepare_current_task_for_new_task_request()` 不能再决定是否替换，只能执行已裁定的 replacement receipt。

### 11.3 Rollback 规则

- 如果 Phase 1/2 失败，允许删除新 boundary 模块和测试，回到旧路径；不得保留未消费的 receipt 字段污染 prompt。
- 如果 Phase 3 之后失败，不允许静默回退到“active_work_context 自动开放 active_work_control”；必须恢复到上一个已通过测试的 commit 或暂停并重新审阅计划。
- 如果运行验证发现 boundary denial 被替代工具动作绕过，必须停止实施并修正 ActionPermit / compiler allowed actions，不能只改 prompt。
- 已写入的 shadow receipt 仅作为 debug 事件，不进入公开投影和后续 runtime 语义。

### 11.4 删除点

这些删除点必须随 cutover 同步完成：

- 删除 active work 存在即自动追加 `active_work_control` 的普通 schema 路径。
- 删除 steer fast path 的独立 branch authority。
- 删除 request_task_run 替换当前任务的入口层隐式决策。
- 删除任何测试里“没有 boundary receipt 也可控制 active work”的假设。

## 12. 风险与控制

| 风险 | 控制 |
| --- | --- |
| Boundary 过度拦截独立请求 | 必须支持 `new_independent_turn_allowed`，并记录 reason/evidence |
| Boundary 变成关键词分类器 | 禁止自然语言 if/else；语义不明时走窄 schema boundary model |
| 普通 turn 仍能二次控制 active work | allowed_action_types 必须由 receipt 计算，测试锁住 |
| 替换任务绕过旧任务收口 | `replace_current_work` receipt 是唯一入口，替换失败必须 block |
| 输出层重复解释 raw event | 保持 Runtime Monitor public projection 权威，不新增前端 raw fallback |
| 旧测试保护旧结构 | 测试改为验证 receipt、事件序列和用户可见行为 |
| Shadow 期形成长期双链路 | Shadow receipt 不得被消费；cutover 后必须删除旧 authority |
| memory/context 弱信号越权 | session emphasis 和 recent outcome 只能是 read-only context，不得改变 allowed actions |
| durable TaskRun 被当成 current work | 没有 active-turn-bound context 或显式 recovery receipt 时，不允许控制 latest waiting task |
| 旧计划把 current work 交给主模型普通 action | 本计划明确取代 20260608 的旧方案；实施时不能以旧计划为兼容理由恢复普通 action 二次裁决 |
| steer 通道退回普通入口 | `active_turn_input_policy=steer` 有效时禁止 `new_independent_turn_allowed`，无关输入必须 ask/block |

## 13. 审阅后实施顺序

推荐一次性按下列顺序实施：

1. Phase 0：跑 baseline，确认现有 dirty 改动。
2. Phase 1：新增 `current_work_boundary.py` 和纯单元测试。
3. Phase 2：在 facade 接入 boundary，合并 steer fast path。
4. Phase 3：新增 boundary model packet 和 prompt。
5. Phase 4：迁出 active work control 执行闭包。
6. Phase 5：收敛 request_task_run replacement。
7. Phase 6：收紧 ordinary schema。
8. Phase 7：删除旧路径，补全验证矩阵。
9. 执行 cutover 搜索，确认旧 authority 不再可达。
10. 启动固定端口做 CLI 真实联调。

本计划没有未决架构选择。建议采用“硬 gate + 窄 schema boundary model + receipt 驱动执行”的方案，因为它最接近 Codex / Claude Code 的成熟控制系统原则：输入先过边界，控制动作产生可追踪凭证，执行环不重新发明意图。
