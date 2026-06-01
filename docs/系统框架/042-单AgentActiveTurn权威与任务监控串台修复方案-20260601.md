# 单 Agent Active Turn 权威与任务监控串台修复方案

日期：2026-06-01

状态：待实施。

自审修订结论：

- 本项目已经有 `TurnRun`、`ActiveTaskSteer`、pending steer 装配和消费检查。本方案新增的是 `ActiveTurnRegistry` 当前控制权，不是重做 steer 队列。
- `RuntimeRun` / `ChatRun` 是前端 SSE 与断线重连的传输运行，不是 active turn 权威。两者必须显式绑定，但不能互相替代。
- 任务运行中用户继续发消息时，系统不应让 agent 丧失对话能力。新输入应进入当前 active turn 的 steer/queue，并允许 agent 在任务上下文内自然回应、调整计划或继续执行。
- session monitor 仍可显示历史任务，但 current chat card 只能绑定 active turn snapshot 或 explicit `turn_ref`。

## 1. 问题定义

当前问题不是“某个旧任务被错误显示”这一类局部 UI bug，而是单 Agent Harness 的当前控制权来源错误。

现在系统仍存在一条旧链：

```text
session_id
-> list_session_task_runs(session_id)
-> 按 updated_at / monitor bucket 选择一个 active work
-> 注入 runtime prompt / active_work_context
-> 前端 session monitor 贴到当前会话消息
```

这条链的问题是：历史任务记录被当成了当前 turn 的控制权。它会导致：

- 新问题进入当前会话时，旧 task run 被重新激活或被模型看到。
- 会话监控把其它任务、旧任务、图任务或历史任务贴到当前消息。
- 断线重连后，系统不是根据当前 active turn 恢复，而是扫描历史 run 猜测要接谁。
- 用户在任务运行中发消息时，系统无法稳定区分 steer、queue、interrupt、new turn。
- 前端只能看到 monitor 资源，却不知道它是否属于当前 turn。

正确的成熟架构属性是：

```text
一个 thread/session 同一时刻最多只有一个 active turn。
当前输入只允许作用于当前 active turn，或者在没有 active turn 时启动新 turn；运行中输入不能隐式启动第二个当前任务。
历史 task run 只能作为记录、恢复候选或监控列表，不能成为当前控制权。
```

## 2. 外部成熟实现对照

本方案参考本地 Codex 源码，不复制其产品形态，只借用控制权不变量。

### 2.1 Codex 的控制权对象

来源：

```text
D:\AI应用\openai-codex\codex-rs\core\src\session\session.rs
```

关键结构：

```rust
pub(crate) active_turn: Mutex<Option<ActiveTurn>>,
pub(crate) input_queue: InputQueue,
```

源码注释明确说明：

```text
A session has at most 1 running task at a time, and can be interrupted by user input.
```

结论：

- Codex 的当前控制权是 `active_turn`，不是从历史任务列表里推断出来的。
- `input_queue` 服务于当前 active turn 或下一 turn，不负责猜测历史任务。

### 2.2 Codex 的用户输入路由

来源：

```text
D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\v2\turn.rs
D:\AI应用\openai-codex\codex-rs\app-server\src\request_processors\turn_processor.rs
D:\AI应用\openai-codex\codex-rs\tui\src\app\thread_routing.rs
```

Codex API 结构是：

```text
turn/start
turn/steer(expected_turn_id)
turn/interrupt(turn_id)
```

`turn/steer` 必须带 `expected_turn_id`。服务端校验：

```text
no active turn -> reject
expected_turn_id mismatch -> reject with actual active turn id
active turn not steerable -> reject with structured reason
```

TUI 行为：

```text
if active_turn_id exists:
  call turn/steer(thread_id, expected_turn_id, input)
else:
  call turn/start(...)
```

结论：

- 用户输入不是被 router 语义猜测后决定要不要恢复旧任务。
- 用户输入先依据明确 active turn handle 进入 `steer`，失败时按结构化错误处理。
- stale UI 不能把输入打到错误任务，因为 `expected_turn_id` 会被服务端拒绝。

### 2.3 Codex 的前端 active turn 追踪

来源：

```text
D:\AI应用\openai-codex\codex-rs\tui\src\app\thread_events.rs
```

Codex TUI 只维护：

```rust
active_turn_id: Option<String>
```

事件规则：

```text
TurnStarted -> active_turn_id = turn.id
TurnCompleted matching active_turn_id -> active_turn_id = None
ThreadClosed -> active_turn_id = None
```

结论：

- UI 可以显示历史事件，但当前输入和当前任务卡片绑定 active turn。
- 历史 snapshot 可以恢复 active turn，但恢复依据是 turn status，而不是随便选最新 task run。

## 3. 当前项目代码审查结论

### 3.0 已有资产必须复用，不能重复建设

当前项目已有以下结构：

```text
backend/runtime/shared/models.py
  TurnRun

backend/harness/loop/task_steering.py
  ActiveTaskSteer
  create_active_task_steer
  list_pending_task_steers
  mark_task_steers_included
  mark_task_steers_consumed

backend/harness/loop/task_executor.py
  pending_user_steers 装配
  consumed_steer_refs 消费校验
  pending_user_steer_unconsumed 完成阻断

backend/harness/runtime/dynamic_context/execution_state_projector.py
  pending_user_steers 动态投影
```

因此修复边界必须明确：

```text
新增 ActiveTurnRegistry：解决“当前控制权是谁”的问题。
复用 ActiveTaskSteer：解决“运行中用户补充如何进入任务”的问题。
复用 TurnRun：解决“本轮模型调用可追踪”的问题。
```

禁止重复新增一套 pending input / steer queue。重复建设会制造第二套用户输入权威。

### 3.1 后端仍用 task run 扫描做当前工作权威

文件：

```text
backend/harness/loop/active_work.py
backend/query/runtime.py
```

问题：

- `build_active_work_context()` 调用 `select_primary_work_continuation_candidate()`。
- `select_primary_work_continuation_candidate()` 调用 `collect_work_continuation_candidates()`。
- `collect_work_continuation_candidates()` 从 `state_index.list_session_task_runs(session_id)` 扫描所有 session task runs。
- `QueryRuntime.astream()` 每一轮都会调用 `build_active_work_context(...)`，再把结果交给 `run_single_agent_turn()`。

这意味着：只要某 session 下存在一个看起来可继续的历史 task run，新 turn 就可能看到 active work context。

目标修复：

```text
active_work_context 不能由 session task run 扫描生成。
它只能来自 ActiveTurnRegistry 中当前 active turn 绑定的 task_run_id。
```

### 3.2 前端 session monitor 仍可把任务贴到当前消息

文件：

```text
frontend/src/lib/store/runtime.ts
```

问题点：

- `hydrateLatestOrchestrationSnapshot(sessionId)` 拉取 session live monitor。
- `activeHarnessSessionMonitor(...)` 选择 session active monitor。
- `patchRuntimeAttachmentFromMonitor(...)` 通过 `latest_interaction_turn_id`、`turnIdFromTaskRunId()` 或 task id 推导 anchor。
- 推导 anchor 的逻辑会把 monitor 贴到某个 assistant message，即使这个 monitor 不属于当前 active turn。

已做过的局部修正：

```text
发送新消息时清空 taskGraphLiveMonitor。
activeHarnessSessionMonitor 不再 fallback 到 taskRuns[0]。
```

但这不是完整修复。完整修复必须让前端 current card 只接受当前 active turn/run 的显式 handle。

目标修复：

```text
session monitor 是历史/列表投影。
current turn attachment 只从 active turn monitor 或 runtime event refs.turn_ref 进入。
没有 active turn handle 的 monitor 不允许 patch 到当前会话消息。
```

### 3.3 runtime monitor 可以保留，但不能参与控制

文件：

```text
backend/harness/runtime/monitoring/projector.py
backend/harness/runtime/monitoring/service.py
```

`build_session_monitor()` 当前会从 session task runs 中选择 running/diagnostics item，并输出：

```text
active_task_run_id
latest_task_run_id
monitor
task_runs
```

这个结构可以继续用于“任务监管台”和“历史列表”，但不能再被 `QueryRuntime` 或前端当前消息视为控制权。

目标修复：

```text
monitor projection = present/observe
active turn registry = decide/current authority
```

### 3.4 router 当前不是根因，但能力字段仍残留 active_work 控制

文件：

```text
backend/harness/routing/turn_router.py
backend/harness/runtime/compiler.py
```

`turn_router.py` 目前只做三类结构 route：

```text
single_agent_turn
explicit_contract_task
blocked_runtime
```

这符合目标方向。问题在于 `active_work_context` 的来源错误。router 不应重新承担 active work 语义判断。

后续需要改的是：

```text
compiler 只在 current active turn 存在且允许 steer/control 时装配 active_work_control。
compiler 不能因为 session 里有历史 task run 就装配 active_work_context。
```

### 3.5 ChatRun / RuntimeRun 与 ActiveTurn 的职责冲突

文件：

```text
backend/api/chat.py
backend/runtime/shared/runtime_run_registry.py
frontend/src/lib/api.ts
frontend/src/lib/store/runtime.ts
```

当前 `/chat/runs` 每次用户发送消息都会创建一个 `RuntimeRun`，用于 SSE 事件流、断线重连和前端首包显示。

这类 run 的职责是：

```text
transport run / stream run
```

它不等于：

```text
active turn / current task authority
```

如果实施时把 `RuntimeRun` 当成 active turn，会产生新冲突：

- 运行中用户补充会创建新的 `RuntimeRun`，但它应该 steer 当前 active turn。
- 一个长任务 active turn 可能跨越多个前端连接或多个用户 steer stream。
- `resume_chat_run` 当前是 attach-only，不能被改造成重新执行旧消息。

目标修复：

```text
RuntimeRun 继续作为 SSE/transport run。
ActiveTurnRecord 作为当前控制权。
RuntimeRun.diagnostics 记录 active_turn_id / expected_active_turn_id / bound_task_run_id。
前端重连可以恢复 stream run，但 current task 控制必须以 active_turn_snapshot 为准。
```

### 3.6 QueryRequest / ChatRequest 缺少 expected active turn 协议字段

文件：

```text
backend/query/models.py
backend/api/chat.py
frontend/src/lib/api.ts
frontend/src/lib/store/runtime.ts
```

当前 `QueryRequest` 和 `ChatRequest` 没有：

```text
expected_active_turn_id
active_turn_input_policy
```

如果没有这个字段，后端无法区分：

```text
前端确认自己正在 steer 当前 active turn
前端状态过期，不知道当前已有 active turn
用户确实想新开 side/fork work
```

目标修复：

```text
ChatRequest.expected_active_turn_id?: string
QueryRequest.expected_active_turn_id: str = ""
ChatRequest.active_turn_input_policy?: "auto" | "steer" | "interrupt" | "start_new_after_complete"
```

Phase 1 可只实现：

```text
auto:
  有 active turn 且 expected 匹配 -> steer
  有 active turn 但 expected 缺失/不匹配 -> structured active_turn_exists/mismatch
  无 active turn -> start
```

不要用自然语言关键词推断 policy。

## 4. 目标架构

### 4.1 权威链

目标主链：

```text
UserSubmission
-> QueryRuntime.astream
-> ActiveTurnRegistry.resolve(session_id)
-> if active turn exists:
     TurnSteer(expected_turn_id, user input)
   else:
     TurnStart(new turn)
-> RuntimeAssembly
-> StructuralTurnRoute
-> SingleAgentTurnLoop
-> TaskLifecycle / ToolExecution / AssistantMessage
-> ActiveTurn terminal release
-> RuntimeMonitorProjection
```

关键边界：

- `ActiveTurnRegistry` 是当前控制权唯一来源。
- `TaskRunIndex` 是历史和任务详情来源，不是当前控制权来源。
- `RuntimeMonitorProjector` 只负责显示，不反向影响路由。
- `TurnRouter` 只做结构路由，不做历史任务选择。
- `SingleAgentTurnLoop` 接收当前 active turn facts，再让 agent 决定是否 request task、steer、pause、stop、answer。

### 4.2 新对象：ActiveTurnRecord

新增后端对象：

```json
{
  "session_id": "session:...",
  "turn_id": "turn:session:12",
  "turn_run_id": "turnrun:...",
  "state": "starting|model_turn|running_task|waiting_executor|waiting_user|interrupting|terminal",
  "bound_task_run_id": "taskrun:...",
  "stream_run_id": "strun:...",
  "started_at": 0,
  "updated_at": 0,
  "owner_instance_id": "runtime-instance:...",
  "steerable": true,
  "terminal_reason": "",
  "authority": "harness.runtime.active_turn"
}
```

约束：

- 同一个 `session_id` 只能有一个非 terminal active turn。
- 启动 task run 时，task run 绑定到当前 active turn。
- task run executor 运行中，active turn 不释放；状态变为 `waiting_executor` 或 `running_task`。
- `stream_run_id` 只表示最近承载该 active turn 事件的 transport run，不能作为控制权。
- task run 完成、失败、停止或中断并完成收口后，active turn 才释放。
- 普通 assistant message 完成后，active turn 立即释放。

### 4.3 新接口语义

后端内部接口：

```text
turn_start(session_id, user_message, runtime_selection) -> ActiveTurnRecord
turn_steer(session_id, expected_turn_id, user_message, stream_run_id) -> SteerResult
turn_interrupt(session_id, expected_turn_id, reason) -> InterruptResult
turn_complete(session_id, expected_turn_id, terminal_reason) -> ActiveTurnRecord
```

`turn_steer` 行为：

```text
no active turn:
  return no_active_turn

expected_turn_id mismatch:
  return expected_turn_mismatch(actual_turn_id)

active turn not steerable:
  return active_turn_not_steerable

matched:
  if bound_task_run_id exists:
    call existing create_active_task_steer(...)
  else:
    append to active turn pending input queue for the next model turn
  emit public event
  return accepted
```

注意：`turn_steer` 不应该直接决定 agent 下一步做什么。它只把用户输入作为当前 active turn 的权威输入保存下来，下一轮 runtime packet 必须可见。

### 4.4 用户输入流程

无 active turn：

```text
用户发送消息
-> start new active turn
-> assemble runtime
-> agent 决定直接答复或 request_task_run
-> 普通答复 terminal release
-> task_run 则 active turn 绑定 task_run，等待 executor 完成后 release
```

有 active turn：

```text
用户发送消息
-> frontend 携带 expected_active_turn_id
-> backend turn_steer 校验
-> 如果 active turn 已绑定 task_run，复用 ActiveTaskSteer 写入 pending_user_steers
-> 如果 active turn 仍处于模型 turn 且未绑定 task_run，写入 active turn pending input queue
-> 当前 stream 返回 steer accepted / queued 的公开事件
-> executor 或下一次模型调用装配 pending input
-> agent 自己判断是否自然回应、调整计划、继续、停止、提问或修正
```

注意：

```text
任务运行中的用户消息仍属于会话的一部分。
系统负责把输入送入当前 active turn。
agent 负责判断这句话是补充要求、问题、纠错、验收修改、停止请求还是普通说明。
```

断线重连：

```text
frontend reconnect
-> read thread/session snapshot
-> backend 返回 active_turn_snapshot
-> frontend 恢复 active_turn_id
-> 监控只订阅这个 active turn/run
-> 不扫描历史 task runs 激活旧任务
```

停止：

```text
frontend stop(expected_active_turn_id)
-> backend turn_interrupt 校验当前 active turn
-> task executor 收到 stop/pause control
-> runtime emit terminal/interrupted event
-> active turn release
```

## 5. 必须删除或降级的旧链路

### 5.1 删除作为控制权的 session task scan

目标动作：

```text
backend/harness/loop/active_work.py
  build_active_work_context 不再扫描 session task runs。
  collect_work_continuation_candidates 降级为 resume suggestions/history helper，不能被 QueryRuntime 主链调用。

backend/query/runtime.py
  删除 astream 内 build_active_work_context(session_id) 的主链调用。
  改为从 ActiveTurnRegistry 读取 current turn bound task context。
```

保留条件：

- 可以保留 `collect_work_continuation_candidates` 作为“历史恢复建议 API”的内部工具。
- 不允许它再进入每一轮 prompt 装配。

### 5.2 删除前端 monitor fallback attachment

目标动作：

```text
frontend/src/lib/store/runtime.ts
  patchRuntimeAttachmentFromMonitor 只允许 active_turn_id / explicit turn_ref match。
  禁止 turnIdFromTaskRunId fallback 作为当前消息 anchor。
  session monitor 无 active_turn_id 时只更新监管台，不更新当前消息 runtimeAttachments。
```

### 5.3 清理 capability 中的 active_work 主链污染

目标动作：

```text
active_work_control 只在 active turn 绑定 task_run 且 steer/control enabled 时暴露。
不存在 active turn 时，不装配 active_work_context。
历史任务存在不能让 model 看到 active_work_context。
```

### 5.4 测试清理

需要删除或重写保护旧行为的测试：

```text
依赖 _seed_active_work + build_active_work_context(session_id) 自动扫描历史 task run 的测试。
依赖 taskRuns[0] fallback 的前端测试。
依赖 “历史 interrupted task 自动成为当前 active work” 的测试。
```

新测试必须保护：

```text
active turn handle
expected id mismatch
no active turn steer rejection
historical task not attached to current message
stop/interrupt must match active turn
```

## 6. 分阶段实施计划

### Phase 1：ActiveTurnRegistry 落地

新增：

```text
backend/harness/runtime/active_turn.py
```

职责：

- 读写 active turn record。
- 保证每 session 一个 active turn。
- 提供 start / steer / interrupt / complete / snapshot。
- 绑定已有 TurnRun、TaskRun、RuntimeRun。
- 对 task run 的用户补充调用现有 `create_active_task_steer`，不新增第二套 steer。
- 在 runtime host 初始化时恢复或关闭无 owner 的 active turn。

存储：

- 初期可使用 `RuntimeStateIndex` 附近的 JSONL/SQLite 轻量表。
- 不复用 `task_run.status` 当 active turn 权威。
- 不复用 `RuntimeRun.status` 当 active turn 权威。

验收：

```text
同 session 重复 start 被拒绝或转为 steer。
expected_turn_id mismatch 返回 actual_turn_id。
terminal release 后可以 start 新 turn。
```

### Phase 2：QueryRuntime 主链改为 start/steer

改造：

```text
backend/query/runtime.py
```

流程：

```text
active = active_turn_registry.snapshot(session_id)
if active and request.expected_active_turn_id:
  turn_steer(...)
  emit accepted event
  return
if active and no expected id:
  return structured active_turn_exists error, frontend 刷新 snapshot 后重试 steer
else:
  turn_start(...)
  run current single_agent_turn
```

重要约束：

- 不再从 session task runs 构建 active work context。
- 不再在主链 `_apply_active_work_turn_decision` 里根据扫描候选控制旧 task。
- agent 决策仍发生在 active turn loop 内，不由 router 代替。
- `/chat/runs` 仍可每次创建 RuntimeRun，但它只是 transport run；必须写入 active_turn_id 绑定。
- `resume_chat_run` 继续 attach-only，不能重放旧用户消息。

API 改造：

```text
backend/api/chat.py
  ChatRequest 增加 expected_active_turn_id / active_turn_input_policy。
  _query_request_from_payload 透传字段。

backend/query/models.py
  QueryRequest 增加 expected_active_turn_id / active_turn_input_policy。
```

### Phase 3：Task lifecycle 绑定 active turn

改造：

```text
backend/harness/loop/task_lifecycle.py
backend/harness/loop/task_executor.py
backend/harness/loop/task_run_execution_control.py
```

规则：

- `request_task_run` 创建 task run 后，写入 `bound_task_run_id`。
- executor 运行期间 active turn 保持占用。
- pending steer 继续使用现有 `ActiveTaskSteer`。
- executor 每次 compile packet 前继续装配现有 `pending_user_steers`。
- task terminal 时 release active turn。

验收：

```text
任务运行中用户新消息不会创建第二个 task run。
用户 steer 必须进入下一次模型 packet。
任务完成后新消息可以启动新 turn。
```

### Phase 4：前端 current task monitor 改为 active turn 绑定

改造：

```text
frontend/src/lib/store/runtime.ts
frontend/src/components/chat/ChatPanel.tsx
frontend/src/lib/runtime-monitor/controller.ts
```

规则：

- Store 增加 `activeTurnSnapshot`。
- 发送消息时：
  - 有 active turn -> 发送 steer 请求，携带 `expected_active_turn_id`。
  - 无 active turn -> 发送普通 start。
- 会话页 current runtime card 只显示 active turn 绑定 run。
- 全局/历史监管台可以显示其它 run，但不能贴到当前消息。

验收：

```text
新会话不会显示旧任务卡片。
旧任务仍可在历史监管台看到。
断线重连恢复当前 active turn，不激活历史 run。
停止按钮只作用于当前 active turn。
```

### Phase 5：旧 active_work 主链删除

删除或降级：

```text
backend/harness/loop/active_work.py 中的主链选择函数
backend/query/runtime.py 中 active_work_turn_decision 主链
backend/harness/runtime/compiler.py 中 session-scan active_work_context 装配入口
```

保留：

```text
active work 历史恢复建议可迁移为 backend/harness/runtime/resume_suggestions.py
```

验收搜索：

```text
backend/query/runtime.py 不 import build_active_work_context
backend/query/runtime.py 不 import active_work_turn_decision_from_payload
backend/harness/runtime/compiler.py 不因 session_id 自动生成 active_work_context
frontend runtime.ts 不使用 turnIdFromTaskRunId 作为 monitor 当前消息 fallback
```

### Phase 6：运行中自然会话与公开反馈修正

目标：

```text
任务运行期间，用户消息不能让 agent “丧失对话能力”。
steer accepted 不是最终回答，只是系统确认输入进入当前 active turn。
后续 agent 观察、判断、工具调用、结果必须继续通过当前 active turn 的公开事件显示。
```

改造：

```text
backend/api/chat.py
  active turn steer accepted 事件进入当前 RuntimeRun stream。

backend/harness/loop/task_executor.py
  pending_user_steers 已存在，保留其强制装配和完成前消费约束。

backend/harness/runtime/monitoring/projector.py
  公开 latest_progress 优先显示真实 tool_status / observation / current_judgment / next_action。
  不允许用泛化硬编码句子覆盖已有真实字段。

frontend/src/components/chat/RuntimeRunSummary.tsx
  分离显示：工具调用、观察结果、Agent 判断、下一步。
```

验收：

```text
任务运行中发送“刚才那里不对，改成 X”：
  当前消息流返回 steer accepted。
  当前任务卡片显示用户补充已进入队列。
  下一次 executor 模型 packet 出现 pending_user_steers。
  agent 后续公开反馈能说明观察/判断/下一步，而不是套话。
```

## 7. 验收矩阵

### 7.1 后端单元行为

```text
test_turn_start_claims_active_turn
test_second_turn_start_while_active_rejected_or_steered
test_turn_steer_requires_expected_turn_id
test_turn_steer_rejects_mismatch_with_actual_id
test_turn_interrupt_requires_matching_active_turn
test_runtime_run_is_not_active_turn_authority
test_task_run_binds_to_active_turn_until_terminal
test_turn_steer_reuses_existing_active_task_steer_for_bound_task
test_terminal_releases_active_turn
test_history_task_run_does_not_create_active_context
```

### 7.2 前端行为

```text
test_send_message_with_active_turn_calls_steer
test_send_message_without_active_turn_calls_start
test_session_monitor_without_active_turn_does_not_patch_message
test_historical_task_run_not_displayed_in_current_chat_card
test_stop_button_uses_expected_active_turn_id
test_chat_run_reconnect_restores_stream_without_selecting_historical_task
```

### 7.3 CLI 实测

固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
```

实测流程：

```text
1. 启动普通对话：确认不创建 task run，active turn 完成后释放。
2. 启动长任务：确认 active turn 绑定 task run。
3. 任务运行中发送补充要求：确认走 steer，不新建第二个任务。
4. 刷新/断线重连：确认恢复同一个 active turn/run。
5. 停止当前任务：确认 expected id 校验，释放 active turn。
6. 停止后发送新任务：确认启动新 turn，不激活旧任务。
```

## 8. 禁止事项

实施时禁止：

- 用关键词判断“继续、暂停、停止”。
- 用 `list_session_task_runs(session_id)[0]` 或 latest run 作为当前任务。
- 用 monitor projection 反向决定控制流。
- 用 `turnIdFromTaskRunId()` 把任务强贴到当前消息。
- 为兼容旧 active_work 主链保留双权威。
- 把用户 steer 写成普通 observation 后让模型自己猜重要性。
- 任务运行中允许同 session 并发两个 active turn。
- 把已有 `ActiveTaskSteer` 旁路掉，另建一套用户补充队列。
- 把 `RuntimeRun`、`ChatRun`、SSE stream run 当作 current work authority。
- 运行中用户发消息时直接启动新任务，除非未来明确实现 side/fork 协议。

## 9. 预期效果

完成后系统行为应接近 Codex 的核心控制属性：

- 普通会话、长任务、任务中用户补充、停止、重连都在同一 turn 权威下运转。
- 用户不会看到旧任务莫名其妙窜到当前会话。
- agent 不再被旧 active_work_context 污染，可以基于当前输入和当前 active turn 作判断。
- 监控系统只负责真实显示，不再暗中改变控制流。
- 断线重连恢复的是当前 active turn，不是历史 task run。

这不是把项目改成 Codex，而是把单 Agent Harness 的当前控制权收敛到成熟 agent 必须具备的 active turn 不变量上。
