# CurrentWorkBoundary 单 Agent 控制边界优化计划书

日期：2026-06-13  
状态：待审阅，未实施  
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

### 2.2 现有测试依据

当前测试已经保护了一些成熟约束：

- `backend/tests/active_turn_authority_regression.py:355`：普通补充不应靠关键词变成暂停，必须使用模型结构化 decision。
- `backend/tests/active_turn_authority_regression.py:434`：active turn 缺失时，steer 不应提升历史 waiting task。
- `backend/tests/harness_model_action_protocol_regression.py:680`：`active_work_control` 接受 intent alias，但仍必须是结构化 action。
- `backend/tests/harness_model_action_protocol_regression.py:706`：裸 active work payload 不合法，必须走 JSON action protocol。
- `backend/tests/dynamic_prompt_context_projection_test.py:1678`：prompt 明确 active work 是 current active-turn-bound work，不是 latest-task fallback。

缺口是：测试还没有证明 `CurrentWorkBoundaryDecision` 是唯一入口，也没有证明普通 single-agent turn 在 boundary 已裁定后不能二次开放 `active_work_control` 或替换当前任务。

### 2.3 6 月 5 日体系对照

6 月 5 日计划 `245-当前工作续接与单轮终止权威重构计划书-20260605.md` 已经把问题定义成：

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

当前源码相较 6 月 5 日已有进步：

- `TurnInputFacts` 已明确不裁决 intent。
- active turn 不再从历史 waiting task 自动恢复。
- active work prompt 已强调 current active-turn-bound work。
- active work 控制 payload 需要结构化 action。
- public response obligation 已开始约束工具调用前的公开回应。

仍未完成的是：6 月 5 日提出的 `CurrentWorkBoundary` 没有独立成层。现在实际链路仍是“入口层拿到 active work 候选，然后把 active_work_context 放入普通模型 action schema，由模型在普通 turn 内选择 active_work_control / request_task_run / tool_call / respond”。这会让 prompt 规则、入口 wrapper、执行环、payload validator 共同承担边界裁决，权威分裂仍存在。

### 2.4 Codex 源码借鉴

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

### 2.5 Claude Code 源码借鉴

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
active_work_context
current_task_run_identity
request_active_turn_policy
expected_active_turn_id
runtime_branch
control_capabilities
editor_context_summary
```

禁止：

- 选择具体工具。
- 启动 TaskRun。
- 写入 session message。
- 生成用户最终正文。
- 从历史 waiting task 推断 active work。

### 4.3 CurrentWorkBoundaryDecision

建议动作集合：

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
你的输出必须是结构化 JSON，不得请求普通工具调用。
```

### 5.2 硬边界优先级

硬边界不交给模型判断：

1. `active_turn_input_policy=steer` 且 `expected_active_turn_id` 缺失：block。
2. `active_turn_input_policy=steer` 且 expected id 与 actual active turn 不匹配：block。
3. `active_turn_input_policy=steer` 且没有 active turn：block，不提升历史 waiting task。
4. active work context 不是 `harness.runtime.active_turn_context`：不允许 steer 控制。
5. active work 已 terminal：不允许 current work control，只能作为 recent outcome 只读事实。
6. control branch 中不得开放普通 `tool_call`。
7. boundary denial 不得自动改成替代工具动作。

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
| Authorization | `admit_model_action` 只知道 allowed action types，不知道 current work receipt | ActionPermit 校验 action 是否被 receipt 授权 | 修改 `backend/harness/loop/admission.py` 或接入处，不扩大权限层职责 |
| Execution | `single_agent_turn` 执行 active_work_control 并可 request_task_run | ExecutionLoop 只执行已允许动作，不裁决当前工作 | 收敛 `backend/harness/loop/single_agent_turn.py` |
| Task lifecycle | `_prepare_current_task_for_new_task_request()` 临时停止旧任务 | 替换由 `replace_current_work` receipt 驱动 | 移动决策部分，保留执行函数 |
| Presentation | active_work 观察和 runtime status 可见，但不应成为主正文推断 | 控制回执 + Runtime Monitor public projection | 保持 `backend/api/chat.py` / projector，不重做前端投影 |

## 7. 文件级改造计划

### 7.1 新增 `backend/harness/entrypoint/current_work_boundary.py`

职责：

- 定义 boundary input / decision / receipt dataclass。
- 提供 hard gate。
- 提供 semantic boundary schema parser。
- 提供 receipt builder。
- 不调用工具、不写 session、不启动 task。

建议函数：

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
- 删除或降级 `_active_turn_steer_fast_path()`，让 steer 也走 boundary receipt。
- 将 `apply_active_work_control()` 从 `_run_single_agent_turn()` wrapper 中迁出，改成 `apply_current_work_boundary_decision()`。
- 将 `_prepare_current_task_for_new_task_request()` 中“是否替换”的决策迁到 boundary，只保留执行旧任务收口的函数。
- 所有 current work 分流都 emit `current_work_boundary_decided`。

完成标准：

- 入口层只 orchestrate，不再同时承担语义裁决。
- active turn stale、current work control、independent turn、replacement 都有同一 receipt。

### 7.3 修改 `backend/harness/runtime/compiler.py`

改造点：

- 新增 `compile_current_work_boundary_packet()` 或等价窄 schema 装配。
- 普通 `compile_single_agent_turn_packet()` 接收 `current_work_boundary_receipt`。
- 当 receipt 不是允许 active work 控制时，普通 packet 不再追加 `active_work_control`。
- 当 receipt 是 `new_independent_turn_allowed` 时，active work 只作为 read-only receipt，不作为可控上下文。
- prompt 中现有 active_work_context 规则改为解释 receipt，而不是要求模型自己裁决边界。

完成标准：

- `allowed_action_types` 不再因为 active_work_context 存在而自动包含 `active_work_control`。
- boundary control branch 中不暴露普通工具。
- prompt 文案符合“角色、职责、边界、输入、输出、裁决标准”规则。

### 7.4 修改 `backend/harness/loop/active_work.py`

改造点：

- 保留 `ActiveWorkContext`。
- 将 `ActiveWorkTurnDecision` 定位为 control payload validation。
- 增加与 `CurrentWorkBoundaryDecision` 的转换函数，或让 boundary 直接生成 `ActiveWorkTurnDecision`。
- 收窄 alias 使用范围：alias 只能兼容模型 payload 字段，不能作为自然语言关键词分类器。

完成标准：

- `active_work_turn_decision_from_payload()` 不再是唯一边界决策源。
- relation 不清时返回 denied，但 denied 由 boundary receipt 转成 ask/block，不自动替代为普通 action。

### 7.5 修改 `backend/harness/loop/single_agent_turn.py`

改造点：

- 移除普通工具循环中的 active work 边界裁决职责。
- 保留执行已授权 `active_work_control` 的 observation/followup 能力，或迁出为 facade/control executor。
- final dispatch 中 `active_work_control` 不应出现 unreachable protocol error，应该在 schema 层不让它进入 final dispatch。
- `request_task_run` 只在 boundary/action schema 允许时进入 task lifecycle。

完成标准：

- `single_agent_turn` 不再决定“这轮是不是当前工作”。
- `tool_loop` 只处理普通工具和已授权控制观察。

### 7.6 修改 `backend/harness/loop/model_action_protocol.py`

改造点：

- 普通 `ModelActionRequest` 继续验证 action type。
- 可新增 `CurrentWorkBoundaryActionRequest`，避免把 boundary decision 塞进普通 model action。
- `active_work_control` 的 action 必填校验保持。
- public response obligation 和 boundary receipt 的关系明确：控制类 action 必须有公开回执意图或 receipt 指定 `no_user_reply`。

完成标准：

- boundary schema 和普通 action schema 不混用。
- 不允许裸 active work payload。

### 7.7 修改测试

新增建议：

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

完成标准：

- `active_turn_input_policy=steer` 不再走一套独立 authority。
- 缺失 active turn 时仍 fail closed，不提升历史 task。

### Phase 3：新增 boundary model decision packet

目标：语义边界不靠关键词，不走普通工具 loop。

动作：

- 在 compiler 中新增 current work boundary packet。
- 只允许输出 boundary action JSON。
- 添加 boundary prompt。
- 解析为 `CurrentWorkBoundaryDecision`，再由 hard validator 二次校验。

完成标准：

- 用户问“为什么卡住”时可以得到 `answer_about_active_work`。
- 用户说“继续但先说明原因”时可以得到 `answer_then_continue_active_work`。
- 用户提出独立问题时可以得到 `new_independent_turn_allowed`。
- 以上过程不开放普通工具。

### Phase 4：control-only branch 执行

目标：当前工作控制动作直接执行 receipt。

动作：

- 从 `_run_single_agent_turn()` wrapper 中迁出 `apply_active_work_control()`。
- 用 `apply_current_work_boundary_decision()` 执行 continue/pause/stop/append/answer。
- 保留 active work observation 和 public projection，但不让它反过来裁决边界。

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

## 9. 删除与收敛规则

必须删除或收敛：

1. `_active_turn_steer_fast_path()` 作为独立分支的权威地位。
2. active work 存在时自动在普通 schema 暴露 `active_work_control` 的逻辑。
3. `_run_single_agent_turn()` wrapper 内部临时定义并持有 active work 边界执行闭包的结构。
4. `_prepare_current_task_for_new_task_request()` 中的“是否替换”决策。
5. prompt 中把 active work 关系判断完全交给普通模型 action 的规则。
6. 任何基于自然语言关键词直接决定 pause/continue/stop 的逻辑。

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

## 11. 风险与控制

| 风险 | 控制 |
| --- | --- |
| Boundary 过度拦截独立请求 | 必须支持 `new_independent_turn_allowed`，并记录 reason/evidence |
| Boundary 变成关键词分类器 | 禁止自然语言 if/else；语义不明时走窄 schema boundary model |
| 普通 turn 仍能二次控制 active work | allowed_action_types 必须由 receipt 计算，测试锁住 |
| 替换任务绕过旧任务收口 | `replace_current_work` receipt 是唯一入口，替换失败必须 block |
| 输出层重复解释 raw event | 保持 Runtime Monitor public projection 权威，不新增前端 raw fallback |
| 旧测试保护旧结构 | 测试改为验证 receipt、事件序列和用户可见行为 |

## 12. 审阅后实施顺序

推荐一次性按下列顺序实施：

1. Phase 0：跑 baseline，确认现有 dirty 改动。
2. Phase 1：新增 `current_work_boundary.py` 和纯单元测试。
3. Phase 2：在 facade 接入 boundary，合并 steer fast path。
4. Phase 3：新增 boundary model packet 和 prompt。
5. Phase 4：迁出 active work control 执行闭包。
6. Phase 5：收敛 request_task_run replacement。
7. Phase 6：收紧 ordinary schema。
8. Phase 7：删除旧路径，补全验证矩阵。
9. 启动固定端口做 CLI 真实联调。

本计划没有未决架构选择。建议采用“硬 gate + 窄 schema boundary model + receipt 驱动执行”的方案，因为它最接近 Codex / Claude Code 的成熟控制系统原则：输入先过边界，控制动作产生可追踪凭证，执行环不重新发明意图。
