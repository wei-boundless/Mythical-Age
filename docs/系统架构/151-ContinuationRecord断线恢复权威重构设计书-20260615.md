# ContinuationRecord 断线恢复权威重构设计书

日期：2026-06-15  
状态：已根据用户审阅意见修正；模型决策链路已进入实施与验证  
范围：单 Agent 聊天入口、ActiveTurn / TaskRun 恢复边界、模型上下文注入、前端续跑协议、恢复状态投影  
不在范围：GraphRuntime 自动恢复、生图 direct route、模型供应商切换、自动重放具有副作用的 provider 请求

## 1. 目的

本设计书用于解决用户感知的“断开后 agent 像失忆”问题。

准确地说，当前系统并不是完全丢失进度，而是可恢复进度停留在 runtime state、event log、task_run diagnostics 和 work_rollout 中，没有形成下一轮可验证、可控制、模型可见的 continuation handle。

目标不是让模型靠“继续”两个字猜测旧任务，而是建立成熟 Agent 式的恢复协议：

```text
session_id
-> task_run_id / previous_turn_id
-> ContinuationRecord
-> RecoverableWork 模型可见候选
-> ModelTurnDecision 选择 resume_recoverable_work / ask_user / respond / request_task_run / block
-> RecoveryBoundaryReceipt 授权模型选择的 resume 动作
-> RecoveryPacket
-> 显式 resume schedule
-> task executor 下一次模型调用可见恢复上下文
```

本设计书已经过用户审阅并修正一个关键原则：大模型是本轮语义动作的操纵者，前端、selector、boundary、executor 都不能替模型决定是否恢复。后续实施必须以该修正版为准。

## 2. 当前断裂链路

### 2.1 已存在但没有闭环的恢复事实

`docs/系统架构/150-Codex与ClaudeCode断线恢复机制对照报告-20260615.md` 已确认：

- `storage/sessions/session-b8ad792d3cbd4ae2.json` 有公开消息和 API transcript，但 turn 30/31 没有 assistant 完成收口。
- `runtime_state/events` 里有 turn 30/31 的任务进度和写文件事实。
- `runtime_objects/active_turn/session_session-b8ad792d3cbd4ae2.json` 已是 `terminal`，原因是 `runtime_instance_restarted`。
- `state_index/session_latest_task_runs/session-b8ad792d3cbd4ae2.json` 仍指向一个 `waiting_executor` 的 task_run。

这说明恢复材料存在，但没有被收束成一个可恢复身份。

### 2.2 ActiveTurn 已正确 fail closed

`backend/harness/runtime/active_turn.py` 当前行为是合理的：

- `snapshot()` 发现 owner runtime instance 不匹配时，会把 active turn 置为 `terminal/runtime_instance_restarted`，并返回 `None`。
- `resolve_current()` 只返回当前 runtime 仍拥有、且绑定 task_run 非 terminal 的 active turn。
- `compare_and_update_current_turn()` 已支持 `expected_turn_id` 和 `expected_task_run_id` 匹配校验。

这符合 Codex 的成熟原则：live turn 控制必须绑定 expected turn id，不能从历史任务猜。

### 2.3 CurrentWorkBoundary 只覆盖 live active work

`backend/harness/entrypoint/current_work_boundary.py` 已经把 live active turn 控制收束成 decision / receipt。

当前正确边界：

```text
active_turn_input_policy=steer
+ expected_active_turn_id 匹配
+ active_work_context.authority == harness.runtime.active_turn_context
-> 允许 active_work_control
```

当前有意不做的事情：

```text
active_turn terminal
+ latest task_run waiting_executor
-> 不提升为 active work
```

这也是 120 号计划的明确选择：durable TaskRun recovery 不能混入 CurrentWorkBoundary。

### 2.4 latest task 目前只能变成 read-only recent outcome

`backend/harness/entrypoint/runtime_facade.py` 在没有 active work 时会调用 `_recent_work_outcome_from_latest_task()`。

这个对象明确写着：

```text
Do not treat it as active work and do not resume that task unless the user starts a new task or the runtime exposes a current active-work context.
```

所以当前链路最多能让模型“知道最近有个任务结果或中断状态”，不能让模型续跑它。

### 2.5 history assembly 不接收 runtime recovery state

`backend/runtime/shared/history_assembler.py` 当前只归一化公开 `user/assistant` 消息和 compressed context。

它不会读取：

- active_turn terminal reason
- latest task_run
- task_run event tail
- work_rollout interrupted boundary
- recovery_action / recoverable_error
- artifact refs

所以用户下一轮只说“继续”时，模型看到的是公开聊天史，而不是真实执行进度。

### 2.6 前端协议只有 steer / auto 两档

`frontend/src/lib/store/runtime.ts` 的 `shouldQueueActiveTurnInput()` 目前只决定是否发送：

```text
active_turn_input_policy = steer | auto
```

并且 monitor 匹配时要求 task status 在 `created/running`，`waiting_executor` 不进入 steer。

这会导致 UI 可以显示“运行时重启后待续跑”，但真正发送请求时没有 `expected_task_run_id` / `expected_continuation_id`，后端只能按普通新 turn 或 read-only outcome 处理。

## 3. 来源依据

### 3.1 本地文档依据

- `docs/系统架构/150-Codex与ClaudeCode断线恢复机制对照报告-20260615.md`：恢复必须由显式 session/thread/turn/task_run handle 驱动，不能由自然语言猜测驱动。
- `docs/系统架构/148-任务重复读与重启卡住根因审查及成熟Agent对照-20260615.md`：runtime restart 后当前策略是明确不自动 schedule，后续应做“等待人工恢复”的结构化恢复语义。
- `docs/系统架构/120-CurrentWorkBoundary单Agent控制边界优化计划书-20260613.md`：CurrentWorkBoundary 只处理 active-turn-bound work；durable TaskRun recovery 必须另建边界。
- `docs/系统架构/141-输出流网络断线重连边界-20260615.md`：SSE 重连只保护已建立输出流，不等于任务恢复。

### 3.2 本项目源码依据

| 文件 | 当前事实 | 设计含义 |
| --- | --- | --- |
| `backend/harness/runtime/active_turn.py` | owner runtime 不匹配时 terminal 化 active turn | live steer 不能跨 runtime instance 盲接 |
| `backend/harness/entrypoint/current_work_boundary.py` | 只允许 active-turn-bound work 控制 | durable recovery 必须独立成层 |
| `backend/harness/entrypoint/runtime_facade.py` | latest task 只生成 read-only recent outcome | 需要新增 RecoverableWork，而不是复用 RecentWorkOutcome |
| `backend/runtime/shared/history_assembler.py` | 只装公开 user/assistant history | 需要由上游注入 RecoveryPacket |
| `backend/harness/loop/task_executor_controller.py` | `runtime_start_recovery` 禁止自动 schedule | 用户显式 resume 必须走新的 scheduler reason |
| `backend/harness/loop/task_run_recovery_state.py` | 已能判断 same_run_resumable / executable | 可作为 RecoveryBoundary 的恢复资格判断 |
| `backend/api/orchestration_harness.py` | 已有 task-run resume + schedule API | 可复用执行能力，但聊天入口需要自己的 continuation receipt |
| `frontend/src/lib/store/runtime.ts` | 只有 steer/auto，缺 recovery handle | 需要输入分类和请求协议扩展 |

### 3.3 成熟 Agent 借鉴点

Codex 借鉴点：

- thread id 是会话恢复身份，turn 是执行边界。
- `turn/steer` 带 expected turn id 前置条件。
- rollout / metadata 持久化和实时工具输出分层。
- fork / shutdown / resume 前先 materialize + flush rollout。

Claude Code 源码样本借鉴点：

- sessionId、sessionProjectDir、projectRoot 原子绑定。
- prompt history 与 transcript/session log 分离。
- resume 会重建模型可见消息，并清理 unresolved tool uses / orphaned assistant messages。
- interrupted turn 会补入模型可见的 meta continuation message，而不是由 UI 直接调度旧动作。
- reconnect/requeue 有 session worker lease，不靠旧进程猜。
- compact summary 明确保留 current work、pending tasks 和 next step。

本地源码证据：

- `D:\AI应用\claude-code-nb-main\utils\conversationRecovery.ts`：对 interrupted turn 追加模型可见 meta user message `Continue from where you left off.`，说明恢复首先是模型上下文恢复。
- `D:\AI应用\claude-code-nb-main\screens\ResumeConversation.tsx`：resume 后把 restored messages 作为 `initialMessages` 交给 REPL，而不是 UI 直接调用旧任务调度。
- `D:\AI应用\claude-code-nb-main\query.ts`：主线程和 subagent 队列有作用域区分，用户 prompt 仍只进入 main thread，由 Claude 在 agent loop 内决定后续动作。
- `D:\AI应用\claude-code-nb-main\utils\sessionStorage.ts`：sessionId 与 projectDir 原子绑定，避免恢复到错误 transcript。

Claude Code / Agent SDK 官方文档借鉴点：

- session 用来保存 prompt、tool calls、tool results 和 responses；continue / resume 的职责是恢复上下文。
- agent loop 中 Claude 评估当前状态后选择文本响应或 tool call；SDK / runtime 负责执行工具并把结果返回给 Claude。
- subagent delegation 由 Claude 根据 agent description 判断何时使用，说明成熟设计把“动作选择权”交给模型，而不是交给 UI 分类器。
- permissions / hooks / runtime boundary 约束工具能否执行；它们是授权器和拦截器，不是用户意图操纵者。

本项目不应该照搬实现细节，但必须借鉴共同不变量：

```text
显式身份
显式执行边界
持久化恢复记录
模型可见恢复包
模型选择恢复动作
resume/steer 前置条件
恢复与普通新 turn 分离
```

### 3.4 用户质疑后的权威修正

用户指出：“是否恢复不是应该由大模型来判断吗？如果用户的意图是继续刚才的内容，那大模型应该会选择恢复动作。”

该意见是正确的。成熟 Agent 设计不能把“恢复候选存在”偷换成“必须恢复”，也不能让前端用 `recovery_input_policy=resume` 替模型提交动作。

修正后的权威链路是：

| 层 | 可以做什么 | 禁止做什么 |
| --- | --- | --- |
| 前端 | 展示可恢复任务；发送 `expected_task_run_id` / `expected_continuation_id` 作为候选证据；`recovery_input_policy` 默认保持 `auto` | 不能决定本轮是 resume；不能发送等价执行命令 |
| ContinuationSelector | 查找并投影 `RecoverableWork` / `RecentWorkOutcome` | 不能推断用户意图；不能 schedule task_run |
| ModelTurnDecision | 根据用户输入、聊天上下文、RecoverableWork 选择 `resume_recoverable_work`、`ask_user`、`respond`、`request_task_run` 或 `block` | 不能绕过权限；不能自己授权副作用 |
| RecoveryBoundary / ActionPermit | 校验模型选择的 resume 动作、expected ids、任务状态和权限 | 不能把 `auto` 政策升级成 resume；不能重新解释用户目标 |
| Executor | 只消费已授权 receipt，写入 RecoveryPacket 并 schedule existing task_run | 不能根据 latest task 或“继续”文本自行恢复 |

这也是本设计区别于旧方案的核心：恢复上下文由系统提供，恢复动作由模型选择，恢复执行由边界授权。

## 4. 关键设计决策

### 4.1 不改 CurrentWorkBoundary 的职责

`CurrentWorkBoundary` 继续只处理 live active turn。

禁止把 latest waiting task 偷偷提升成 active work，因为这会破坏 120 号计划已经建立的 live steer fail-closed 边界。

新增同级边界：

```text
CurrentWorkBoundary
- live active turn
- expected_active_turn_id
- active_work_control

RecoveryBoundary
- durable recoverable task_run
- expected_task_run_id
- expected_continuation_id
- resume schedule
```

### 4.2 新增 ContinuationRecord 作为恢复权威

`ContinuationRecord` 是 runtime/state 层的持久化恢复对象。

它不是 assistant final message，不进入公开聊天 canonical history，不伪造“已完成”回答。

建议存储：

```text
runtime_objects/continuation_record/{continuation_id}
state_index/session_latest_continuations/{session_id}
```

如果实现阶段发现 state_index 暂不适合新增索引，也可以先由 builder 从 latest task_run 实时 materialize，并把 record_ref 写入 task_run diagnostics；但 cutover 后必须保证前端和后端使用同一个 continuation identity。

### 4.3 新增 RecoveryPacket 作为模型可见恢复包

`RecoveryPacket` 是从 `ContinuationRecord` 派生出来的 bounded、结构化、模型可见上下文。

它只说明：

- 用户正在恢复哪个任务。
- 已确认做到哪里。
- 为什么中断。
- 下一步允许做什么。
- 需要核对哪些 artifact / 文件状态。
- 哪个 continuation/task_run handle 已通过验证。

它不能包含原始 event log 整段文本，也不能伪造 assistant 历史。

### 4.4 用户 resume 必须带显式 handle

后端不能因为用户文本包含“继续”就恢复任务；前端也不能因为当前 UI 展示了可恢复任务，就替模型决定本轮必须 resume。

成熟链路必须拆成三层：

```text
ContinuationSelector
-> 只恢复候选上下文，生成 RecoverableWork / RecentWorkOutcome

ModelTurnDecision
-> 模型根据用户输入和 RecoverableWork 判断：
   resume_recoverable_work | answer_about_recoverable_work | ask_user | new_independent_turn | block

RecoveryBoundary / ActionPermit
-> 只校验模型选择的 resume action 是否合法，并授权或拒绝执行
```

允许恢复的条件：

```text
模型输出 action_type == "resume_recoverable_work"
+ expected_continuation_id 匹配
+ expected_task_run_id 匹配
+ ContinuationRecord.state 可恢复
+ TaskRunRecoveryState.executable 或 same_run_resumable
+ 权限 / side effect 边界允许
```

如果用户只输入“继续”，但模型没有选择 `resume_recoverable_work`，后端不能执行恢复；如果模型选择了恢复但请求/候选缺少 handle，RecoveryBoundary 必须返回可解释的拒绝或确认需求。

前端可以在当前 UI 明确展示 recoverable work 时携带 `expected_task_run_id` / `expected_continuation_id` 作为候选句柄，但不能把 `recovery_input_policy` 直接置为 `resume` 来替模型做动作选择。句柄是模型和边界使用的证据，不是 UI 发出的执行命令。

### 4.5 恢复不等于自动续跑

`runtime_start_recovery` 继续不自动 schedule，这是安全边界。

用户显式 resume 后使用新的 scheduler reason：

```text
conversation_recovery_resume
```

或：

```text
task_run_continuation_resume
```

禁止复用 `runtime_start_recovery` 作为用户恢复 scheduler，否则会和“启动恢复只记录、不执行”的语义冲突。

## 5. 目标状态分类

新增一个明确分类层，不能再只有 active work / recent outcome 两档。

```text
LiveActiveWork
- 来源：ActiveTurnRegistry.resolve_current()
- 条件：owner runtime 匹配，active_turn 非 terminal，bound task_run 非 terminal
- 控制：CurrentWorkBoundary
- 请求字段：expected_active_turn_id

RecoverableWork
- 来源：ContinuationRecordBuilder 从 latest task_run / event tail / work_rollout 生成
- 条件：无 live active turn，task_run waiting_executor / paused / waiting_approval 等可恢复或待确认状态
- 控制：RecoveryBoundary
- 请求字段：expected_task_run_id + expected_continuation_id

RecentWorkOutcome
- 来源：terminal / failed / completed / aborted task_run
- 条件：不可 resume
- 控制：只读
- 请求字段：无控制字段
```

`RecoverableWork` 不属于 active turn，也不能伪装成 active turn。

## 6. 数据模型设计

### 6.1 ContinuationRecord

建议字段：

```text
continuation_id: string
session_id: string
task_run_id: string
previous_turn_id: string
previous_active_turn_id: string
previous_stream_run_id: string
state: live | recoverable | waiting_approval | paused | blocked | terminal_read_only
resume_allowed: boolean
resume_strategy: same_run_resume | require_approval | ask_user_confirm | unavailable
resume_scheduler: conversation_recovery_resume
recovery_cause: runtime_instance_restarted | executor_interrupted | user_paused | waiting_approval | blocked | unknown
task_status: string
executor_status: string
control_state: string
user_visible_goal: string
latest_progress: string
last_completed_step: string
next_recommended_step: string
task_contract_ref: string
work_rollout_ref: string
event_log_ref: string
event_cursor: number
artifact_refs: list[string]
model_visible_summary: string
requires_user_confirmation: boolean
control_version: number
created_at: number
updated_at: number
expires_at: number | null
authority: harness.continuation.record
```

字段原则：

- `continuation_id` 必须稳定，且随 task_run 状态关键变化产生新 `control_version`。
- `model_visible_summary` 是摘要，不是原始日志。
- `resume_allowed=false` 时仍可用于 UI 展示和状态回答。
- `terminal_read_only` 替代当前 `_recent_work_outcome_from_latest_task()` 对可恢复状态的混用。

### 6.2 RecoveryPacket

建议字段：

```text
packet_id: string
continuation_id: string
session_id: string
task_run_id: string
resume_intent: user_requested_resume | status_only | confirm_required
user_visible_goal: string
confirmed_progress: list[string]
interruption_summary: string
next_step_contract: string
artifact_refs: list[string]
file_refs: list[string]
resume_constraints: list[string]
forbidden_actions: list[string]
model_instruction: string
authority: harness.continuation.recovery_packet
```

`model_instruction` 必须是 Agent 可执行说明，例如：

```text
你正在恢复一个被后端运行时重启打断的本地代码任务。
当前恢复句柄已通过校验：continuation_id=...，task_run_id=...
已确认进度：上一轮已经写入目标文件，并记录了恢复断点。
你需要先核对最新文件状态和未完成验收项，再继续执行，不要从聊天文本中的“继续”猜测任务。
如果恢复句柄失效、任务状态不允许续跑，必须说明原因并停止。
```

禁止写成：

```text
这是 recovery 节点。
根据 runtime_state 继续 task_run。
```

### 6.3 RecoveryBoundaryDecision

`RecoveryBoundaryDecision` 不是用户意图分类器，只对模型已经提交的恢复动作做授权裁决。

建议裁决集合：

```text
no_recoverable_work
recoverable_work_available
resume_recoverable_work
confirm_recoverable_work
recoverable_work_unavailable
recent_work_read_only
block
```

必要字段：

```text
decision_id
session_id
turn_id
action
continuation_id
expected_continuation_id
task_run_id
expected_task_run_id
resume_strategy
allowed_next_actions
forbidden_next_actions
reason
evidence
public_response_obligation
diagnostics
authority = harness.continuation.recovery_boundary
```

### 6.4 RecoveryBoundaryReceipt

后续执行层唯一消费 receipt，不直接消费 candidate。

建议字段：

```text
receipt_id
decision_id
boundary_decision
continuation_ref
task_run_ref
recovery_packet_ref
available_action_types_for_next_packet
operation_availability
resume_execution_route
expected_continuation_id
expected_task_run_id
state_reason
public_projection_policy
diagnostics
enforced
authority = harness.continuation.recovery_boundary_receipt
```

`operation_availability.resume_recoverable_work` 为 true 时，才允许 schedule existing task_run。

## 7. 固定执行流

目标入口链路：

```text
1. api/chat.py 接收 ChatRequest
2. 构造 HarnessRuntimeRequest
3. runtime_facade 建立 active turn / runtime assembly
4. build_turn_input_facts 只记录事实
5. ContinuationSelector 读取候选：
   5.1 session_latest_task_runs -> RecoverableWork candidate
   5.2 terminal latest task -> RecentWorkOutcome candidate
6. CurrentWorkBoundary 裁决 live steer
7. RecoverableWork / RecentWorkOutcome 注入 model-visible turn context
8. single_agent_turn 让模型选择动作：
   8.1 active_work_control
   8.2 resume_recoverable_work
   8.3 request_task_run
   8.4 respond / ask_user / block
9. 只有模型选择 resume_recoverable_work 时，RecoveryBoundary 才裁决 durable resume
10. RecoveryBoundary 允许后，write RecoveryPacket 并 schedule existing task_run
11. task_executor 下一次 packet 装载 RecoveryPacket
12. Runtime Monitor / chat projection 展示同一 continuation 状态
```

执行优先级：

```text
explicit live steer > model-selected recovery resume > model-selected status/ask_user > ordinary new turn
```

禁止优先级：

```text
不能因为有 latest_task_run 就覆盖 active turn。
不能因为用户文本像“继续”就跳过 expected handle。
不能让 RecoveryBoundary 重新决定用户的新任务目标。
不能让前端代替模型选择 resume_recoverable_work。
```

## 8. 后端模块计划

### 8.1 新增 `backend/harness/continuation/`

建议文件：

```text
backend/harness/continuation/__init__.py
backend/harness/continuation/record.py
backend/harness/continuation/selector.py
backend/harness/continuation/recovery_packet.py
backend/harness/continuation/recovery_boundary.py
backend/harness/continuation/projection.py
```

职责：

- `record.py`：定义 `ContinuationRecord`。
- `selector.py`：从 active_turn、state_index、task_run、event tail、work_rollout 读取候选，不做 resume 决策。
- `recovery_packet.py`：把 record 转成模型可见 packet。
- `recovery_boundary.py`：校验 expected ids、状态、权限，产出 decision / receipt。
- `projection.py`：给前端和 session live view 的用户可见投影。

### 8.2 修改 `backend/harness/runtime/request_facts.py`

新增事实字段：

```text
expected_task_run_id
expected_continuation_id
recovery_input_policy: auto | status
recoverable_work_candidate
```

说明：公共请求事实层不接受 `resume` 作为外部动作策略。`resume` 只能在模型已经输出 `action_type=resume_recoverable_work` 之后，由后端内部构造 `RecoveryBoundaryInput` 时使用。

仍然禁止：

- 分类“继续”意图。
- 选择恢复任务。
- 授权 resume。
- 把前端策略字段当作模型动作。

### 8.3 修改 `backend/harness/entrypoint/models.py`

`HarnessRuntimeRequest` 新增：

```text
expected_task_run_id: str = ""
expected_continuation_id: str = ""
recovery_input_policy: str = "auto"
```

不建议把 `active_turn_input_policy` 扩展成 `resume`。它语义上属于 active turn，durable recovery 应有独立字段。

### 8.4 修改 `backend/api/chat.py`

`ChatRequest` 新增同名字段，并在 `_query_request_from_payload()` 透传。

同时新增或扩展一个查询投影：

```text
GET /chat/sessions/{session_id}/continuations/latest
```

返回当前 session 的：

```text
live_active_work | recoverable_work | recent_work_outcome | none
```

如果实现阶段选择复用 session monitor snapshot，也必须保证响应中有 `continuation_id` 和 `task_run_id`，不能只返回文案。

### 8.5 修改 `backend/harness/entrypoint/runtime_facade.py`

新增流程：

```text
active_work_context = _active_work_context_from_active_turn()
continuation_candidate = ContinuationSelector.select(...)
current_work_receipt = CurrentWorkBoundary.decide(...)
run_single_agent_turn(... recoverable_work candidate ...)
if model_action.action_type == "resume_recoverable_work":
    recovery_receipt = RecoveryBoundary.decide(model_action + candidate + expected ids)
```

分流规则：

- `current_work_receipt` 允许 live control 时，走现有 active work control。
- `recoverable_work_available` 进入模型上下文，由模型决定 resume / ask_user / respond / new task。
- `recovery_receipt` 允许模型选择的 resume 时，写入 RecoveryPacket，调用 task executor schedule。
- `RecoveryBoundary` 拒绝模型选择的 resume 时，返回结构化 observation / final answer，不退化成普通工具调用。
- terminal task 只进入 read-only `RecentWorkOutcome`。

需要收敛的旧逻辑：

- `_recent_work_outcome_from_latest_task()` 不再覆盖 recoverable waiting task。
- 对 waiting_executor 的“可恢复”展示从 ContinuationRecord 投影生成。
- 普通 single-agent prompt 中可以告知模型有 RecoverableWork，但必须要求模型显式选择 `resume_recoverable_work`，并说明该动作会被 RecoveryBoundary 校验。

### 8.6 修改 `backend/runtime/shared/history_assembler.py`

不要让 history assembler 自己读取 state。

新增参数：

```text
recovery_packet: dict | None = None
```

职责只限于把上游已裁决的 packet 放入模型上下文，不能自行选择恢复任务。

如果 task executor 不走 `assemble_runtime_history()`，则需要在 task executor packet 编译处接入同一个 `RecoveryPacketContextLoader`。

### 8.7 修改 task executor 编译链路

目标：用户 resume 后，被 schedule 的旧 task_run 下一次模型调用能看到 RecoveryPacket。

建议做法：

1. RecoveryBoundary resume 成功前，把 `recovery_packet_ref` 写入 task_run diagnostics。
2. `task_executor.py` 或 task runtime compiler 在编译下一次 invocation packet 时读取该 ref。
3. 注入 bounded `RecoveryPacket` 到 dynamic context。
4. task executor 开始执行后写事件：

```text
task_run_continuation_resume_started
task_run_recovery_packet_attached
```

禁止：

- 只把 RecoveryPacket 放进聊天 turn，不给真正续跑的 task executor。
- 把完整 event log 拼到 prompt。

### 8.8 修改 `backend/harness/loop/task_executor_controller.py`

保留：

```text
runtime_start_recovery -> runtime_start_recovery_does_not_auto_schedule
```

新增用户恢复 scheduler：

```text
conversation_recovery_resume
```

schedule 前置条件由 RecoveryBoundary receipt 给出。controller 不重新猜 continuation，只执行已授权的 task_run schedule。

### 8.9 修改 ActionPermit / admission

新增 resume 动作权限：

```text
resume_recoverable_work
```

Action schema 必须允许模型在 single-agent turn 中输出：

```json
{
  "authority": "harness.loop.model_action_request",
  "action_type": "resume_recoverable_work",
  "recovery_resume": {
    "task_run_id": "taskrun:...",
    "continuation_id": "cont:...",
    "reason": "用户要求继续上一轮可恢复任务"
  },
  "public_progress_note": "我会从已恢复的任务断点继续，并先核对当前文件状态。"
}
```

Admission / RecoveryBoundary 必须检查：

- receipt 存在。
- `operation_availability.resume_recoverable_work == true`。
- expected ids 匹配。
- task_run 仍可执行。

如果不满足，返回结构化 deny，不退化成 ordinary tool_call。

## 9. 前端协议计划

### 9.1 新增输入分类

替换当前二分函数：

```text
shouldQueueActiveTurnInput()
```

目标函数：

```text
classifyCurrentWorkInput()
-> live_steer
-> recoverable_context
-> new_turn
-> ask_confirm
```

分类依据：

- `activeTurnSnapshot` 可 steer：`live_steer`
- `recoverableWorkSnapshot.resume_allowed=true`：`recoverable_context`，只附带候选 handle，不替模型决定 resume
- 多个候选或 handle 缺失：`ask_confirm`
- 只有 terminal recent outcome：`new_turn`，但可带 read-only status

### 9.2 请求字段

live steer：

```json
{
  "active_turn_input_policy": "steer",
  "expected_active_turn_id": "turn:..."
}
```

recoverable context：

```json
{
  "recovery_input_policy": "auto",
  "expected_task_run_id": "taskrun:...",
  "expected_continuation_id": "cont:..."
}
```

ordinary new turn：

```json
{
  "active_turn_input_policy": "auto",
  "recovery_input_policy": "auto"
}
```

### 9.3 UI 状态

前端必须区分：

```text
正在运行：live active turn
运行时重启后待续跑：recoverable continuation
最近任务已结束：recent outcome
普通空闲：none
```

点击“继续”或用户在该状态下发送“继续”时，必须带 continuation handle，但 `recovery_input_policy` 仍保持 `auto`；是否恢复由模型在本轮 action 中选择。

如果模型选择恢复且 handle 过期，后端返回 `recoverable_work_unavailable`，前端刷新 continuation projection，而不是再次按普通 turn 猜。

### 9.4 SSE reconnect 与 continuation 的边界

`docs/系统架构/141-输出流网络断线重连边界-20260615.md` 的规则保持不变：

- `stream_run_id + event_offset` 只用于恢复输出流。
- `continuation_id + task_run_id` 用于恢复执行任务。

这两个机制不能互相替代。

## 10. 迁移与切换规则

### 10.1 Shadow 阶段

允许先生成 ContinuationRecord，但不执行 resume。

要求：

- 事件标记 `enforced=false`。
- 前端只展示调试或只读状态。
- 不影响 CurrentWorkBoundary。

退出条件：

- 当前问题 session 能生成 `RecoverableWork`。
- completed task 只能生成 `RecentWorkOutcome`。
- live active turn 仍由 CurrentWorkBoundary 接管。

### 10.2 Cutover 阶段

Cutover 后：

- `RecoveryBoundaryReceipt.enforced=true` 是恢复 task_run 的唯一凭证。
- recoverable waiting task 不再走 `_recent_work_outcome_from_latest_task()`。
- 前端发送 recoverable context 必须带 expected ids，但不得替模型发送 resume 决策。
- task executor 下一次模型调用必须包含 RecoveryPacket。

### 10.3 Rollback 规则

Phase 1/2 shadow 失败，可以删除 continuation 模块和投影，不影响旧链路。

Phase 3 之后如果发现后端会无 handle 恢复任务，必须停止 cutover，不能退回“根据继续文本猜任务”。

如果 RecoveryPacket 只进入聊天模型、没有进入 task executor，不能发布 cutover。

### 10.4 删除规则

必须删除或收敛：

- recoverable waiting task 通过 RecentWorkOutcome 文案伪装成可解释状态的旧投影。
- 前端 `waiting_executor` 显示可继续但请求不带 handle 的链路。
- 后端任何基于自然语言“继续”直接选择 latest task_run 的逻辑。
- 普通 single-agent prompt 中暗示模型可以 resume read-only recent outcome 的文案。

允许保留：

- CurrentWorkBoundary live active turn 控制。
- `/chat/runs/{stream_run_id}/resume` 的 attach-only SSE run 语义，但文案和类型必须避免被误解成 task resume。
- `/orchestration/harness/task-runs/{task_run_id}/resume` 作为任务监控 API，但聊天入口不能绕过 RecoveryBoundary 调用它。

## 11. 分阶段实施计划

### Phase 0：基线确认

目标：锁定当前问题和现有测试。

动作：

- 跑 current work / active turn / chat API 相关测试。
- 记录当前 session 样本的 active_turn terminal、latest task_run waiting_executor、recent outcome 投影。
- 记录前端 `shouldQueueActiveTurnInput()` 对 waiting_executor 的分类。

完成标准：

- 基线可复现。
- dirty worktree 不被覆盖。

### Phase 1：ContinuationRecord shadow

目标：建立恢复对象，不改变行为。

涉及文件：

- 新增 `backend/harness/continuation/record.py`
- 新增 `backend/harness/continuation/selector.py`
- 修改 `backend/harness/entrypoint/runtime_facade.py`
- 新增 `backend/tests/continuation_record_regression.py`

完成标准：

- runtime restarted + waiting_executor 生成 `RecoverableWork`。
- completed / failed 生成 `RecentWorkOutcome`。
- active turn running 生成 `LiveActiveWork`，不生成 recoverable resume。

### Phase 2：RecoveryBoundary 与请求协议

目标：后端能裁决 resume 是否允许，但仍可先不执行。

涉及文件：

- 新增 `backend/harness/continuation/recovery_boundary.py`
- 修改 `backend/harness/runtime/request_facts.py`
- 修改 `backend/harness/entrypoint/models.py`
- 修改 `backend/api/chat.py`
- 新增 `backend/tests/recovery_boundary_regression.py`

完成标准：

- handle 匹配时 decision 为 `resume_recoverable_work`。
- handle 缺失时 decision 为 `confirm_recoverable_work` 或 `recoverable_work_available`。
- stale handle 被拒绝。
- live active turn 存在时 recovery resume 不覆盖 live steer。

### Phase 3：RecoveryPacket 注入

目标：恢复上下文进入真正续跑模型调用。

涉及文件：

- 新增 `backend/harness/continuation/recovery_packet.py`
- 修改 `backend/runtime/shared/history_assembler.py`
- 修改 task executor packet 编译链路
- 修改 dynamic context projection 相关测试

完成标准：

- RecoveryPacket 不进入 assistant canonical history。
- task executor 下一次 invocation packet 可见 `continuation_id/task_run_id/latest_progress/next_step_contract`。
- prompt 文案符合 Agent Prompt 规则。

### Phase 4：显式 resume schedule

目标：用户带 handle 继续后，旧 task_run 被安全调度。

涉及文件：

- 修改 `backend/harness/entrypoint/runtime_facade.py`
- 修改 `backend/harness/loop/task_executor_controller.py`
- 修改 `backend/harness/loop/admission.py`
- 新增 `backend/tests/recovery_resume_facade_regression.py`

完成标准：

- `runtime_start_recovery` 仍不自动 schedule。
- `conversation_recovery_resume` 能 schedule waiting_executor。
- schedule 失败返回结构化失败，不开新 task_run。
- event log 写入 recovery receipt 和 recovery packet ref。

### Phase 5：前端 continuation 协议

目标：UI 显示与请求行为一致。

涉及文件：

- 修改 `frontend/src/lib/store/runtime.ts`
- 修改 `frontend/src/lib/api.ts`
- 新增或更新 frontend store tests

完成标准：

- waiting_executor + runtime restart 显示 `recoverable_resume`。
- 点击继续或发送继续时带 `expected_task_run_id/expected_continuation_id`。
- stale handle 刷新 projection。
- `stream_run_id` reconnect 与 task continuation 状态不混淆。

### Phase 6：旧路径清理与 cutover

目标：避免双链路残留。

动作：

- `_recent_work_outcome_from_latest_task()` 只保留 terminal read-only outcome。
- 搜索 `waiting_executor` 状态下不带 continuation handle 的普通继续路径。
- 删除保护旧行为的测试，补充结构性测试。
- 真实启动固定端口联调。

完成标准：

- recoverable waiting task 只有 RecoveryBoundary 一条恢复路径。
- 普通 turn 不能 resume task_run。
- 当前问题 session 回放能恢复到原 task_run，而不是开新任务。

## 12. 文件级 checklist

| 文件 | 当前角色 | 目标动作 | 完成条件 |
| --- | --- | --- | --- |
| `backend/harness/runtime/active_turn.py` | live active turn 权威 | 保留，只暴露校验给 RecoveryBoundary 判断 live 冲突 | 不允许 latest task 绕过 active turn |
| `backend/harness/entrypoint/current_work_boundary.py` | live current work 边界 | 保留职责，不加入 durable recovery | tests 证明 recoverable task 不走 active_work_control |
| `backend/harness/continuation/record.py` | 不存在 | 新增 ContinuationRecord | 可序列化、可投影、可版本校验 |
| `backend/harness/continuation/selector.py` | 不存在 | 新增候选收集 | 只 observe/retrieve，不 decide |
| `backend/harness/continuation/recovery_boundary.py` | 不存在 | 新增恢复裁决 | expected ids 不匹配时 fail closed |
| `backend/harness/continuation/recovery_packet.py` | 不存在 | 新增模型可见恢复包 | bounded summary，不含原始日志整段 |
| `backend/harness/runtime/request_facts.py` | 请求事实 | 增加 recovery facts | 仍不分类 intent |
| `backend/harness/entrypoint/models.py` | runtime request schema | 增加 recovery request fields | chat API 能透传 |
| `backend/api/chat.py` | chat run API | 增加 continuation 字段和 latest projection | resume task 与 attach SSE run 语义分离 |
| `backend/harness/entrypoint/runtime_facade.py` | 入口编排 | 接入 selector/boundary/packet/schedule | 入口只分流，不猜文本 |
| `backend/runtime/shared/history_assembler.py` | history 归一化 | 接收上游 RecoveryPacket | 不自行读取 state |
| `backend/harness/loop/task_executor_controller.py` | executor schedule | 增加用户 recovery scheduler reason | runtime_start_recovery 仍不自动 schedule |
| `backend/harness/loop/admission.py` | action permit | 增加 resume receipt 校验 | 无 receipt 不允许 resume |
| `frontend/src/lib/api.ts` | API 类型 | 增加 recovery fields/types | 请求携带 continuation handle |
| `frontend/src/lib/store/runtime.ts` | 前端运行态 | 新增 classifyCurrentWorkInput | waiting_executor 不再落回普通 auto |

## 13. 验证矩阵

| 场景 | 期望 |
| --- | --- |
| active_turn running + expected_active_turn_id 匹配 | CurrentWorkBoundary 允许 live steer |
| active_turn owner mismatch | active_turn terminal，不允许 steer |
| active_turn terminal + latest task waiting_executor | 生成 RecoverableWork / ContinuationRecord |
| recoverable resume handle 匹配 | RecoveryBoundary 允许 resume |
| recoverable resume handle 缺失 | 返回 confirm/status，不 schedule |
| expected_continuation_id 过期 | 拒绝并要求刷新 |
| expected_task_run_id 不匹配 | 拒绝，不恢复 latest task |
| task_run completed | 只生成 RecentWorkOutcome |
| 用户只发“继续”且没有 handle | 不恢复，可提示存在可恢复任务 |
| 前端点击 recoverable continue | 请求带 task_run_id + continuation_id |
| runtime_start_recovery | 只记录 waiting resume，不自动 schedule |
| conversation_recovery_resume | schedule existing task_run |
| task executor 下一次模型调用 | 包含 RecoveryPacket |
| RecoveryPacket 注入 | 不写假 assistant final |
| SSE 网络断线 | 只用 stream_run_id/event_offset 重连，不触发 task resume |
| 当前问题 session 回放 | 续跑原 task_run 31，不开新 task_run |

## 14. 禁止捷径

- 禁止只在 prompt 里写“记住之前进度”。
- 禁止根据“继续”关键词选择 latest task_run。
- 禁止把 `waiting_executor` 直接伪装成 active turn。
- 禁止写假的 assistant final message 补聊天历史。
- 禁止把原始 event log 整段塞进模型上下文。
- 禁止让前端显示“可续跑”，但请求仍按 `auto` 普通 turn 发送。
- 禁止让 `/chat/runs/{stream_run_id}/resume` 承担 task_run resume。
- 禁止 `runtime_start_recovery` 自动重放有副作用的任务。
- 禁止保留两套互相竞争的 recoverable task 判断。

## 15. 预期结果

重构后，断线恢复将具备以下性质：

- 用户可见状态和后端恢复权威来自同一 ContinuationRecord。
- live active turn 控制仍由 CurrentWorkBoundary fail closed。
- runtime restart 后的 waiting task 由 RecoveryBoundary 管理，不污染 active turn。
- 模型下一次真正执行时能看到 RecoveryPacket。
- 用户恢复操作有 expected continuation handle，不会接错任务。
- 公开聊天历史不被伪造，runtime checkpoint 与 assistant final 分离。

最终目标不是“看起来记得”，而是让系统真的拥有成熟 Agent 的恢复协议：可追踪、可校验、可拒绝、可续跑、可测试。
