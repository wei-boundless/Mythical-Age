# 单 Agent 控制系统统一 Turn Loop 重构方案

日期：2026-06-01

## 1. 重构目标

本次重构的目标不是继续修补 `plain_conversation`、`agent_native_turn`、`agent_action` 三条分支，而是把单 agent 控制系统收敛为一条统一、可追踪、可恢复的 turn loop。

正确目标链路：

```text
QueryRuntime.astream
-> commit user message
-> direct system route
-> assemble runtime
-> structural turn route
-> run single agent turn
   -> assistant message: commit + terminal
   -> runtime native action: authorize + execute + observe/terminal
   -> request_task_run: build contract + start lifecycle + schedule executor
   -> active work control: apply control + terminal
-> public stream projection
```

核心性质：

- 普通对话是一等结果，不创建 task run，不进入 JSON action loop。
- task run 只能由模型显式 runtime action、显式合同、或 active work continuation 开启。
- router 只做结构路由，不调用模型、不做语义判断。
- prompt packet 的 allowed / forbidden action 必须和实际装配能力一致。
- 任务启动必须同时产生用户可见 handoff、task lifecycle event、step summary、turn terminal 和 monitor 可读状态。

## 2. 当前问题

### 2.1 Prompt contract 与 native tool 冲突

`compile_plain_conversation_packet()` 的 output contract 禁止：

```text
tool_call_request
task_run_request
json_action_protocol
runtime_ids
```

但 `agent_native_turn` 又给模型装配 `request_task_run` native tool。  
这会让模型收到互相冲突的控制信号：系统一边说禁止请求任务，一边提供任务启动工具。

结论：`agent_native_turn` 不能复用 `plain_conversation_packet`。

### 2.2 Router 层越权调用模型

`turn_router.decide_turn_route()` 当前会调用 `decide_active_work_turn()`。  
这使 router 同时承担结构路由和模型语义判断。

问题：

- active work 存在时，普通对话可能在路由阶段被模型调用阻塞。
- 路由失败会表现成控制系统失败，而不是 agent 决策失败。
- 不符合成熟 agent 的分层：route 只决定进入哪个 runtime loop，模型判断属于 loop 内部。

### 2.3 Task lifecycle 启动记录不完整

新 `task_lifecycle_bridge` 能启动 task run，但没有完整复用旧 agent loop 中的 step summary、turn terminal、monitor 状态记录。

风险：

- 会话页只看到“任务已启动”，但不知道系统当前执行到哪里。
- monitor 缺少 `latest_step_summary` 或只能显示泛化等待语句。
- 长任务启动后出现用户感知上的断层。

### 2.4 QueryRuntime 仍然过重

`QueryRuntime` 当前仍包含：

- plain conversation runner
- native turn adapter
- explicit contract task starter
- active work 控制逻辑
- task todo 初始化
- checkout/resume/stop 调度

这与“API adapter only”的目标不一致。  
后续任何控制系统变化都会继续污染 `QueryRuntime`。

## 3. 成熟架构对照

### 3.1 Codex 可借鉴原则

Codex turn loop 的核心结构是：

```text
model output assistant message -> record -> complete turn
model output tool call -> route tool -> execute -> feed observation -> continue
```

关键原则：

- assistant message 是一等终态。
- tool call 是模型输出的一种结构，不需要预先把所有 turn 包成 JSON action。
- tool execution 与 permission/approval/observation 是 runtime loop 的职责。
- turn completion 与 abort 都有明确 lifecycle event。

### 3.2 Claude Code 可借鉴原则

Claude Code query loop 的核心结构是：

```text
query loop
-> model stream
-> assistant/tool_use collection
-> permission gate
-> tool execution
-> tool_result appended
-> recursive continuation or terminal assistant
```

关键原则：

- tool/subagent 是显式能力，不是模糊意图识别后的暗中转发。
- permission 与 abort 信号贯穿整个 tool execution。
- 工具结果和中断结果会补回 conversation trajectory，保证模型后续能理解。
- 普通 assistant message 与 tool-use turn 在同一 loop 中处理，不拆成互相冲突的模式。

## 4. 目标架构

### 4.1 权威链

```text
RequestFacts
-> RuntimeAssembly
-> StructuralTurnRoute
-> SingleAgentTurnPacket
-> ModelTurnOutput
-> ActionPermit
-> RuntimeActionExecution
-> Observation / Terminal
-> PublicProjection
```

职责边界：

- `QueryRuntime`：API 输入、会话提交、调用 runner、转发事件。
- `assemble_runtime`：装配 agent/environment/tool/action 能力，不做语义判断。
- `turn_router`：结构路由，不调用模型。
- `RuntimeCompiler`：生成与能力一致的 model packet。
- `single_agent_turn`：统一处理 assistant message、native action、tool action、task run request、active work action。
- `task_lifecycle`：创建、记录、审批、调度、恢复 task run。
- `runtime_monitor`：只投影事件和状态，不重新判断任务意图。

### 4.2 Route Kind 调整

目标 route kind：

```text
single_agent_turn            默认主链，支持 assistant message / native action
explicit_contract_task       API/task system 传入成型合同
blocked_runtime              runtime 装配失败或权限边界阻断
```

说明：

- `direct system route` 是 `QueryRuntime` 在 router 之前的系统级旁路，不属于 `TurnRouteKind`。
- 如果 direct system route 消费本轮请求，本轮不会进入 runtime assembly 后的 structural router。
- structural router 只处理已经进入 agent runtime 的请求，不负责系统命令、健康检查、会话元操作。

删除或废弃：

```text
agent_native_turn
plain_conversation 作为主链 route
active_work_control 作为 router 模型决策 route
plain_system_response 作为 route kind
```

说明：

- `plain_conversation` 不再作为一条独立控制链，而是 `single_agent_turn` 的一种自然结果。
- active work 不是 router 里的模型判断，而是 single agent turn 内可见的 runtime context 与可调用 action。

### 4.3 新 SingleAgentTurnPacket

新增：

```python
RuntimeCompiler.compile_single_agent_turn_packet(...)
```

packet 必须按能力动态生成 output contract：

```text
如果 may_request_task_run = true:
  allowed_actions 包含 request_task_run
  forbidden 不得包含 task_run_request

基础动作始终包含 respond、ask_user、block。

如果 may_call_tools = false:
  不暴露普通工具
  forbidden 包含 general_tool_call

如果 active_work_context 存在:
  model-visible context 包含当前任务摘要
  allowed_actions 包含 active_work_control

如果显式能力边界关闭 may_request_task_run / may_control_active_work:
  allowed_actions 不包含 request_task_run / active_work_control
  本轮仍属于 single_agent_turn，不新增 conversation-only 或 plain_conversation 控制路径
```

active work context 必须只提供事实，不做语义裁决：

```text
active_work_context:
  task_run_id
  status
  control_state
  user_visible_goal
  latest_step_summary
  latest_public_progress_note
  pending_approval
  available_controls: continue|pause|stop|append_instruction|answer_status
```

single agent turn 可以基于用户本轮消息和 active work context 输出：

```text
active_work_control:
  continue_active_work
  pause_active_work
  stop_active_work
  append_instruction_to_active_work
  answer_about_active_work
  answer_then_continue_active_work
```

约束：

- router 不得调用模型判断 active work relation。
- packet 里不得出现“当前消息一定属于当前任务”这类预裁决。
- 如果用户只是普通聊天，模型应输出 `assistant_message`，不应强制控制 active work。
- 如果用户明确修改任务目标，必须用 `append_instruction_to_active_work` 或等价 steer 记录，而不是覆盖原合同。

禁止再出现：

```text
同一个 packet 同时禁止 task_run_request 又装配 request_task_run 工具
```

### 4.4 Runtime Native Actions

统一 action 集合：

```text
assistant_message
request_task_run
request_registered_engagement
ask_user
active_work_control
tool_call
delegate_subagent
block
```

第一阶段只实现：

```text
assistant_message
request_task_run
request_registered_engagement
ask_user
active_work_control
block
```

普通工具和子 agent 后续接入同一 action loop，不再单独扩一条旧链路。

`request_registered_engagement` 的归属：

- 它不是意图识别层，也不是旧 JSON action loop 的保留理由。
- 它表示 agent 选择一个系统已注册、边界已成型的特定任务契约。
- 第一阶段必须接入统一 lifecycle starter，和 `request_task_run` 共用任务启动、monitor、todo、terminal 记录。
- 如果实现阶段决定暂不支持它，必须从 allowed action、prompt pack、schema、executor 中同步删除；禁止只在运行层忽略。

action 协议决策：

- 对模型侧，优先使用 provider native tool call 表达 `request_task_run`、`request_registered_engagement`、`active_work_control` 等 runtime native action。
- 对 harness 内部，所有 native tool call 必须 normalize 成统一内部 action request，再进入 authorization、execution、lifecycle。
- JSON `ModelActionRequest` 只允许作为旧 `agent_action` 工具/子 agent 过渡路径的输入格式；不得作为普通对话和任务启动的默认协议。
- 过渡期结束后，`agent_action` 不能继续承接单 agent 主链。

terminal / follow-up 矩阵：

```text
assistant_message              commit assistant message -> final_answer -> turn terminal
request_task_run               build contract -> start lifecycle -> schedule executor -> turn terminal
request_registered_engagement  resolve registered contract -> start lifecycle -> schedule executor -> turn terminal
ask_user                       commit clarification -> final_answer -> turn terminal
active_work_control            apply control/steer -> commit public reply -> turn terminal
tool_call                      execute tool -> append observation -> continue model sampling or terminal by next model output
delegate_subagent              start/observe subagent -> append observation -> continue model sampling or terminal by next model output
block                          commit failure/block reason -> final_answer/error -> turn terminal
```

第一阶段不实现 `tool_call` / `delegate_subagent` follow-up 时，必须把它们明确挡在 single agent packet 的 allowed actions 之外。不能让模型看到工具能力却没有执行回路。

## 5. 分阶段实施计划

### Phase 1：建立统一 single agent turn

目标：

- 新建 `backend/harness/loop/single_agent_turn.py`
- 新增 `compile_single_agent_turn_packet()`
- 用 single agent turn 替代 `agent_native_turn`

文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/query/runtime.py`
- `backend/tests/query_runtime_runtime_loop_regression.py`

完成标准：

- 简单对话走 `single_agent_turn` 并直接提交 assistant message。
- 可请求 task run 的 turn 不再复用 plain conversation packet。
- prompt contract 与 action schema 不冲突。
- 删除 `agent_native_turn` route 的主链引用。

### Phase 2：router 纯结构化

目标：

- `turn_router` 不再调用模型。
- active work 只作为 runtime context candidate 进入 single agent turn。

文件：

- `backend/harness/routing/turn_router.py`
- `backend/harness/loop/active_work.py`
- `backend/query/runtime.py`
- `backend/tests/query_runtime_runtime_loop_regression.py`

完成标准：

- route 阶段不调用 `decide_active_work_turn()`。
- active work 存在时，普通对话不会被 router 阻塞。
- 用户继续/暂停/补充任务时，由 single agent turn 输出 active work action。

### Phase 3：统一 task lifecycle starter

目标：

- 把 `task_lifecycle_bridge` 重写为正式 lifecycle starter，或并入 `task_lifecycle.py`。
- 补齐 step summary、turn terminal、monitor 状态。
- 显式合同、`request_task_run`、`request_registered_engagement` 必须共用同一个 lifecycle starter。

文件：

- `backend/harness/loop/task_lifecycle.py`
- `backend/harness/loop/task_lifecycle_bridge.py`
- `backend/harness/loop/agent_loop.py`
- `backend/harness/runtime/monitoring/projector.py`
- `backend/tests/runtime_monitor_projection_test.py`
- `backend/tests/query_runtime_runtime_loop_regression.py`

完成标准：

- task run 启动后有：
  - `task_run_lifecycle_started`
  - `agent_todo_initialized`
  - `task_run_lifecycle_event`
  - `latest_step_summary`
  - `latest_public_progress_note`
  - `task_lifecycle_started` step summary
  - `task_executor_scheduled` step summary
  - `agent_turn_terminal`
  - 用户可见 handoff
- monitor 不再显示泛化占位句。
- 显式合同路径不经过模型语义判断，但必须进入同一 lifecycle starter，不能单独写一套 task run 启动分支。
- `request_registered_engagement` 必须先解析成确定合同，再进入同一 starter；解析失败时返回公开阻塞原因。

### Phase 4：瘦身 QueryRuntime

目标：

- `QueryRuntime` 不再包含具体 turn runner 和 active work 执行细节。

文件：

- `backend/query/runtime.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/active_work_control.py` 或并入 single turn action executor

完成标准：

- `QueryRuntime.astream()` 只保留：
  - load history
  - commit user message
  - direct system route
  - assemble runtime
  - structural route
  - call runner
  - yield events
- 删除 `_run_plain_conversation_turn()`
- 删除 `_run_agent_native_turn()`
- 删除大段 active work 控制执行逻辑，移入 harness loop。

### Phase 5：清理旧链路和测试

目标：

- 删除或废弃 `agent_native_turn.py`
- 删除保护旧 JSON action 默认路径的测试
- 保留真实行为测试
- 删除旧 route 名称依赖，不删除真实用户行为保障。

文件：

- `backend/harness/loop/native_turn.py`
- `backend/harness/routing/turn_router.py`
- `backend/tests/query_runtime_runtime_loop_regression.py`
- `backend/tests/runtime_monitor_projection_test.py`

完成标准：

- 没有 `agent_native_turn` route。
- 没有 prompt contract 冲突测试盲区。
- 测试保护的是用户可见行为和 lifecycle 状态，而不是旧内部结构。
- `plain_conversation_started`、`agent_native_turn_started` 这类旧内部事件不再作为前端/测试的稳定契约。
- 新稳定事件以 `single_agent_turn_started`、`assistant_message_committed`、`task_run_lifecycle_started`、`task_run_lifecycle_event`、`agent_turn_terminal` 为准。

测试迁移规则：

```text
旧测试断言 route_kind=plain_conversation
  -> 改为断言没有 task run、assistant message 被提交、turn terminal 正常。

旧测试断言 route_kind=agent_native_turn
  -> 改为断言 packet 允许 request_task_run、模型 native action 能启动 task lifecycle。

旧测试断言 action_capable_runtime 进入 agent_action
  -> 如果覆盖工具/子 agent，暂时保留为过渡测试；如果覆盖普通任务启动，迁移到 single_agent_turn。

旧测试断言 active_work_control router route
  -> 改为断言 router 不调用模型，active work context 进入 single_agent_turn，控制动作由 single_agent_turn 输出。
```

cutover / 删除标准：

- `compile_single_agent_turn_packet()` 接入后，禁止新增对 `compile_plain_conversation_packet()` 的主链调用。
- `run_single_agent_turn()` 能覆盖普通对话和任务启动后，删除 `run_agent_native_turn()` 主链引用。
- lifecycle starter 覆盖显式合同、native task request、registered engagement 后，删除 `task_lifecycle_bridge` 或合并为无旧语义的内部函数。
- 前端和 monitor 改读新事件后，删除旧事件投影；不保留双事件长期兼容。
- 如果 cutover 后测试失败，不允许恢复旧 route 作为兜底；必须定位 single loop 的缺口并修复。

## 6. 文件级执行清单

### 必改

- `backend/harness/runtime/compiler.py`
  - 新增 `compile_single_agent_turn_packet()`
  - 调整 prompt manifest / segment plan / output contract

- `backend/harness/loop/single_agent_turn.py`
  - 新统一 turn loop
  - 处理 assistant message / request_task_run / request_registered_engagement / active_work_control / ask_user / block

- `backend/harness/routing/turn_router.py`
  - 移除模型调用
  - 删除 `agent_native_turn`
  - route 收敛到 structural route

- `backend/harness/loop/task_lifecycle.py`
  - 提供统一 `start_task_lifecycle_from_model_action()` 或等价函数
  - 统一事件、summary、terminal

- `backend/query/runtime.py`
  - 瘦身为 adapter
  - 删除重复 runner 和 active work 执行细节

### 应清理

- `backend/harness/loop/native_turn.py`
  - Phase 1 cutover 后删除，不保留兼容入口

- `backend/harness/loop/task_lifecycle_bridge.py`
  - Phase 3 后删除；如果合并，只能作为 `task_lifecycle.py` 内部无旧语义 helper

- `backend/harness/loop/agent_loop.py`
  - 保留旧 JSON action loop 仅作为工具路径过渡
  - 不再作为默认单 agent turn 主链
  - 工具/子 agent 接入 single loop 后，删除该过渡职责

## 7. 验收矩阵

### 普通对话

输入：

```text
你好，介绍一下这个项目
```

预期：

- route = `single_agent_turn`
- assistant message committed
- 无 task run
- 无 JSON action request
- 无 active work 模型路由调用

### 任务启动

输入：

```text
帮我做一个五层地下塔肉鸽游戏，生成真实可打开的 HTML，并完成基本验证
```

预期：

- model 输出 `request_task_run`
- 系统创建真实 `TaskRunContract`
- task run 进入 waiting/running
- 会话页显示 handoff
- monitor 有具体 step summary
- `latest_step_summary` 与 `latest_public_progress_note` 不能是“正在处理”类泛化占位句，必须来自 lifecycle starter 或模型公开行动状态。

### Active Work 控制

输入：

```text
先暂停
```

预期：

- router 不调用模型
- single agent turn 根据 active work context 输出 control action
- task run pause 状态写入
- 会话页显示自然语言反馈
- 如果用户消息与当前任务无关，single agent turn 应正常回答，不得被 active work context 强制劫持。

### 显式合同

输入：

```text
task_selection.task_contract = {...}
```

预期：

- route = `explicit_contract_task`
- 不经过模型语义判断
- 直接进入统一 lifecycle starter
- monitor 状态完整

### 已注册特定任务

输入：

```text
模型输出 request_registered_engagement(plan_id, startup_parameters)
```

预期：

- 系统只按注册表解析 `plan_id`，不做关键词意图识别。
- 解析得到成型合同后进入统一 lifecycle starter。
- 解析失败时返回公开阻塞原因，并提交 turn terminal。
- monitor 状态与普通 `request_task_run` 一致。

### 工具 / 子 agent 过渡

输入：

```text
用户要求联网搜索或调用子 agent 协作
```

预期：

- 如果 single agent turn 尚未实现 tool/subagent follow-up，不得在 packet 中暴露 `tool_call` / `delegate_subagent`。
- 如果通过旧 `agent_action` 暂时承接，必须只限工具/子 agent 场景，并记录删除条件。
- 普通对话、任务启动、active work 不得回落到旧 `agent_action`。

## 8. 禁止事项

- 禁止用关键词表替代模型 runtime action 判断。
- 禁止让 router 调用模型做语义判断。
- 禁止一个 packet 同时 forbidden 和 allowed 同一种 action。
- 禁止为了兼容保留 `agent_native_turn` 主链。
- 禁止让 `request_registered_engagement` 只在 prompt/schema 里存在而没有统一执行路径。
- 禁止在 `QueryRuntime` 继续堆具体控制逻辑。
- 禁止测试只断言内部 event 存在而不验证真实状态和用户可见结果。
- 禁止把工具/子 agent 暴露给模型但没有 observation follow-up 执行回路。

## 9. 推荐实施顺序

严格顺序：

```text
1. compile_single_agent_turn_packet
2. run_single_agent_turn
3. QueryRuntime 接入 single_agent_turn
4. 删除 agent_native_turn route
5. router 去模型调用
6. task lifecycle starter 补齐状态记录
7. QueryRuntime 瘦身
8. 清理旧文件和旧测试
9. 真实 CLI / 后端 / 前端监控验收
```

不可跳步原因：

- 先做 packet，才能消除 prompt/action 冲突。
- 先做 unified loop，才能删除 `agent_native_turn`。
- 先完成 lifecycle starter，才能保证长任务状态不再断。
- 最后瘦身 `QueryRuntime`，避免在缺少承接模块时产生功能空洞。

## 10. 最终状态

重构完成后，单 agent 控制系统应具备以下结构：

```text
QueryRuntime
  -> RuntimeAssembly
  -> StructuralTurnRouter
  -> SingleAgentTurnLoop
      -> AssistantMessageCommit
      -> RuntimeNativeActionExecutor
      -> TaskLifecycleStarter
      -> ActiveWorkController
      -> ObservationFollowup
  -> RuntimeMonitorProjection
```

系统表现：

- 对话自然，不被任务协议污染。
- 任务启动自然，不和普通对话断层。
- 长任务有实时状态，有失败恢复，有最终验收。
- prompt 装配和 runtime 能力一致。
- 代码边界清晰，后续接入工具、子 agent、图任务时不会继续复制旧链路。
