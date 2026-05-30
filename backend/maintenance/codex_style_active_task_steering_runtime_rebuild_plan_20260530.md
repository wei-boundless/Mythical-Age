# Codex 式 Active Task Steering 与 TaskRun Runtime 系统级重构升级书

日期：2026-05-30

状态：待用户审阅。本文是重构实施前的系统级升级书，不是代码实施记录。

适用范围：

```text
backend/query/runtime.py
backend/api/orchestration_harness.py
backend/harness/loop/active_work.py
backend/harness/loop/resume_policy.py
backend/harness/loop/task_checkout.py
backend/harness/loop/task_executor.py
backend/harness/loop/agent_loop.py
backend/harness/loop/model_action_protocol.py
backend/harness/loop/admission.py
backend/harness/runtime/compiler.py
backend/harness/runtime/envelope.py
backend/harness/runtime/invocation_packet.py
backend/harness/runtime/monitor_projection.py
backend/harness/runtime/session_timeline.py
backend/runtime/memory/tool_observation_ledger.py
backend/runtime/shared/event_log.py
backend/tests
```

参考来源：

```text
本项目：
backend/maintenance/agent_turn_taskrun_lifecycle_rebuild_plan_20260527.md
backend/maintenance/task_observation_ledger_recovery_design_20260528.md

Codex 本地源码：
C:\Users\admin\.codex\sources\openai-codex\codex-rs\tui\src\app\thread_routing.rs
C:\Users\admin\.codex\sources\openai-codex\codex-rs\tui\src\app_server_session.rs
C:\Users\admin\.codex\sources\openai-codex\codex-rs\app-server\src\request_processors\turn_processor.rs
C:\Users\admin\.codex\sources\openai-codex\codex-rs\core\src\session\mod.rs
C:\Users\admin\.codex\sources\openai-codex\codex-rs\core\src\session\input_queue.rs
C:\Users\admin\.codex\sources\openai-codex\codex-rs\core\src\session\turn.rs
C:\Users\admin\.codex\sources\openai-codex\codex-rs\protocol\src\protocol.rs
```

## 0. 执行结论

当前失败不是单个游戏修复任务的问题，而是 active work、resume、TaskRun executor、用户中途修改、模型行动请求、状态监控之间没有形成唯一的权威主链。

本次重构目标不是补一句 prompt，也不是只修 `same_run_resume`。目标是把系统升级为 Codex 式运行机制：

```text
所有用户输入都是一等 Submission。
运行中输入走 active task steer，不再伪装成 resume。
steer 被写入 active task 的 pending input，并强制下一次模型 invocation 可见。
语义目标变化必须进入 task contract revision 或 checkout fork。
executor 的 invocation/action id 必须从持久 ledger 单调生成，不能因 resume 从 1 重置。
TaskRun 每一步必须由 RuntimeInvocationPacket 驱动。
工具执行必须由 ModelActionRequest -> AdmissionDecision -> ExecutionContext -> ObservationRecord 闭合。
完成必须由真实 artifact、receipt、self-review、acceptance 支撑。
监控和 SSE 必须能显示活跃、等待、阻塞、过期、完成、失败，而不是让任务长期假运行。
```

重构后目标链固定为：

```text
User Submission
-> ActiveWorkRouter
-> TurnStart | ActiveTaskSteer | TaskRunControl | NewWork
-> RuntimeCompiler
-> RuntimeInvocationPacket
-> ModelActionRequest
-> AdmissionDecision
-> ExecutionContext
-> ObservationLedger
-> TaskObservationProjection
-> Follow-up RuntimeInvocationPacket
-> SelfReview / Acceptance
-> UserVisibleTerminalEvent
```

## 1. 当前系统真实问题

### 1.1 新用户指令没有成为权威输入

当前路径中，用户追加的修复要求主要有两种走法：

```text
append_user_work_instruction
-> 记录 observation_type=user_work_instruction

checkout_task_run_for_resume
-> 写入 prompt_contract.resume_context.user_instruction
```

这两条都不等于 Codex 的 active turn steer。问题是：

```text
user_work_instruction 是 observation，但不是 pending input 队列。
resume_context 是恢复参考，不是当前 task goal 或 acceptance criteria。
same_run_resume 可能完全不追加用户当前 message。
```

直接证据：

```text
backend/query/runtime.py
  _apply_continue_active_work 在 same_run_resume 下只 resume，不追加 user_message。

backend/harness/loop/resume_policy.py
  可恢复时优先 same_run_resume。

backend/harness/loop/task_checkout.py
  user_instruction 被放进 prompt_contract.resume_context。

backend/harness/loop/task_executor.py
  user_work_instruction 被投影为 observation，但不是强制下一轮模型必须处理的 pending input。
```

### 1.2 resume 和 steer 的语义混在一起

当前系统把以下几类完全不同的行为混到 resume 体系里：

```text
继续原任务。
暂停后恢复。
用户中途补充新要求。
用户改变目标或验收标准。
运行时重启后恢复。
失败后 checkout fork。
```

成熟 agent runtime 里这些必须分开：

```text
resume: 恢复同一合同下的执行现场。
steer: 把用户新输入注入仍活跃的执行循环。
revision: 修改目标、约束、验收标准或优先级。
checkout fork: 终态中断后基于历史创建新合同。
restart: 从合同和当前工作区重新执行。
```

如果不分开，agent 会继续执行旧目标，用户以为它在修新问题，实际 runtime 没有把新问题升级成权威任务。

### 1.3 executor invocation id 会因 resume 重置

当前 `execute_task_run` 的循环每次从 1 开始：

```text
for step_index in range(1, max_steps + 1)
```

默认 request id 仍有 resettable 形态：

```text
model-action:{task_run_id}:{invocation_index}
```

这会带来三个风险：

```text
恢复后重复 action id。
去重逻辑误判新 action 是旧 action。
event trace 上多个不同模型请求共用同一局部编号。
```

Codex 的做法是 Submission 使用唯一 id，工具调用使用模型/API call id 或独立 id，不依赖会重置的本地 step counter。

### 1.4 已有新结构没有成为唯一主链

本项目已经有成熟化底座：

```text
RuntimeEnvelope
RuntimeInvocationPacket
ModelActionRequest
AdmissionDecision
TaskObservationProjection
runtime_freshness
event_log
monitor_projection
```

但这些还不是唯一权威链。旧链路仍能影响结果：

```text
ActiveWorkTurnDecision 仍在系统侧判断 continue/append/start_new_work。
same_run_resume 仍会绕过 active steer。
checkout resume 仍把用户指令放在弱 resume_context。
executor step_index 仍可重置。
TaskRun completion/self-review/acceptance 还没有完全闭合。
monitor 能标 stale，但不能驱动 runtime recovery 语义闭合。
```

因此本轮重构必须做系统级收束，而不是在旧链路上继续包一层新壳。

## 2. Codex 对照结论

Codex 解决同类问题的核心不是 prompt，而是协议。

### 2.1 Codex 对运行中用户输入使用 turn_steer

Codex TUI 在用户提交输入时先检查是否有 active turn：

```text
如果有 active turn:
  turn_steer(thread_id, expected_turn_id, input)

如果没有 active turn:
  start new turn
```

关键机制：

```text
expected_turn_id 防止 stale UI 把输入打到错误 turn。
turn_steer 不是 resume。
steer input 被追加到 active turn pending input。
turn loop 在下一次 sampling 前 drain pending input。
只要有 pending input，needs_follow_up = true。
```

对本项目的要求：

```text
运行中 TaskRun 收到用户新输入时，不应返回“已经收到”后只写 observation。
它必须生成 ActiveTaskSteer，并绑定 expected_task_run_id / expected_executor_epoch。
下一次 compile_task_execution_packet 必须强制包含 pending steers。
pending steer 未被模型消费前，executor 不允许完成为 completed。
```

### 2.2 Codex 把用户输入作为一等 Submission

Codex protocol 中 Submission 有唯一 id、op、user message id、trace 等字段。

对本项目的要求：

```text
对话输入、继续、暂停、停止、用户补充、审批结果、工具结果都必须有一等事件 id。
不能靠自然语言、turn_id、step_index 拼接来代表不同事件。
所有 event/ref 必须可追踪到原始用户 Submission 或系统 control Submission。
```

### 2.3 Codex 不让 resume 承担目标修改

Codex 的 pending input 进入 active turn，是当前模型 loop 的新输入；它不会被塞进“恢复摘要”里让模型自己猜重要性。

对本项目的要求：

```text
resume_context 只能保存恢复事实。
用户当前修改必须进入 pending steer 或 contract revision。
task_run_goal / completion_criteria / repair_focus 必须能表达用户新目标。
```

## 3. 目标权责链

| 层 | 当前问题 | 目标权力 | 禁止事项 |
| --- | --- | --- | --- |
| QueryRuntime | active work 控制和 resume 混用 | 接收用户 Submission，路由到 turn/start/steer/control | 不直接改写目标，不静默 same-run resume |
| ActiveWorkRouter | 模型判断 action，但结果仍落旧链路 | 只判断用户输入属于 control、steer、new work、status question | 不决定 agent 下一步执行方案 |
| TaskSteerStore | 当前缺失 | 保存 active task pending input，记录 consumed state | 不替 agent 总结成弱 resume_context |
| ResumePolicy | same-run 优先过强 | 区分 resume、steer、revision、checkout、restart | 不把新目标当 continue |
| RuntimeCompiler | 已有 packet，但缺 pending steer 强制语义 | 每次 invocation 装配当前 pending steers、contract、observations、permissions | 不根据用户关键词选择动作 |
| ModelActionProtocol | 已有基础，但 id 仍可弱化 | 表达 agent 真实动作请求，id 全局唯一或 task-run 单调 | 不用 resettable step index 当唯一性来源 |
| Admission | 已有基础 | 只裁决 allow/deny/ask/invalid/needs_contract | 不把 deny/invalid 改写成别的动作 |
| Executor | 能执行 TaskRun，但 resume 语义不稳 | 单调推进 invocation，消费 steer，记录 observation，触发 review/acceptance | 不在没有证据时完成 |
| ObservationProjection | 已有 freshness | 给 agent 当前事实、历史失败、修复焦点、pending steer | 不把历史失败当当前事实 |
| Monitor/SSE | 能显示状态，但不能解释 stuck 原因 | 显示 pending steer、executor epoch、stale、blocked、waiting_user | 不让 running 无限期无诊断 |
| Presentation | 有 final_answer_event | 输出自然用户状态和终态 | 不泄露内部控制 id |

## 4. 新对象模型

### 4.1 UserSubmission

新增或落地为统一数据结构：

```json
{
  "submission_id": "submission:...",
  "session_id": "...",
  "turn_id": "...",
  "source": "conversation | api | monitor_control | approval",
  "kind": "user_input | continue | pause | stop | approval | system_resume",
  "content": "...",
  "created_at": 0.0,
  "client_message_id": "",
  "authority": "runtime.user_submission"
}
```

要求：

```text
每条用户输入先成为 Submission，再决定路由。
同一用户输入不能既作为普通 chat 又作为 active work control 被重复消费。
Submission id 不允许从 step_index 派生。
```

### 4.2 ActiveTaskSteer

新增核心结构：

```json
{
  "steer_id": "steer:...",
  "submission_ref": "submission:...",
  "session_id": "...",
  "task_run_id": "...",
  "expected_task_run_id": "...",
  "expected_executor_epoch": 0,
  "steer_kind": "instruction | correction | acceptance_change | priority_change | status_question",
  "content": "...",
  "priority": "normal | high | blocking",
  "consumption_state": "pending | included_in_packet | consumed | rejected | superseded",
  "created_at": 0.0,
  "included_packet_ref": "",
  "consumed_action_ref": "",
  "authority": "harness.loop.active_task_steer"
}
```

要求：

```text
运行中的任务收到用户“继续修这个”“不是这里”“要加载美术资源”时，创建 steer。
steer 必须进入 execution_state.pending_user_steers。
blocking/high steer 未消费前，TaskRun 不允许 completed。
如果 expected_task_run_id 不匹配，必须拒绝并重新选择 active work，不能静默写入旧任务。
```

### 4.3 TaskContractRevision

当用户输入改变目标或验收标准时，不能只记 steer，必须生成合同修订候选：

```json
{
  "revision_id": "taskrev:...",
  "task_run_id": "...",
  "submission_ref": "submission:...",
  "revision_kind": "goal_change | acceptance_change | scope_change | constraint_change",
  "proposed_goal": "",
  "proposed_acceptance_criteria": [],
  "impact": {
    "invalidate_steps": [],
    "invalidate_artifacts": [],
    "requires_user_confirmation": false
  },
  "status": "pending_agent_triage | accepted | needs_user | rejected",
  "authority": "harness.loop.task_contract_revision"
}
```

要求：

```text
简单补充执行方向可只作为 steer。
改变交付目标、产物要求、验收标准，必须进入 revision triage。
revision triage 应由 agent 在 RuntimeInvocationPacket 中判断，不由系统关键词决定。
```

### 4.4 ExecutorEpoch 与 InvocationSequence

为 TaskRun 引入持久执行 epoch 和单调 invocation sequence：

```json
{
  "task_run_id": "...",
  "executor_epoch": 3,
  "next_invocation_index": 27,
  "last_completed_invocation_index": 26,
  "active_packet_ref": "",
  "authority": "harness.loop.executor_sequence"
}
```

要求：

```text
每次 executor start/resume 增加 executor_epoch。
invocation_index 从 event log 或 state_index 中读取 next 值。
request_id 默认使用 uuid 或 monotonic sequence，不再从 range(1) 直接派生。
旧 request id 只作为兼容读取，不作为新写入格式。
```

建议新 id：

```text
model-action:{task_run_id}:epoch:{executor_epoch}:invocation:{invocation_index}:uuid:{short}
rtpacket:{task_run_id}:task_execution:{executor_epoch}:{invocation_index}
```

### 4.5 TaskObservationProjection 扩展

现有 projection 应增加 pending steer 和 contract revision：

```json
{
  "system_projection": {
    "pending_user_steers": [],
    "active_contract_revisions": [],
    "current_facts": [],
    "artifact_evidence": [],
    "active_failures": [],
    "historical_failures": [],
    "repair_focus": [],
    "last_action_receipts": []
  }
}
```

要求：

```text
pending_user_steers 是当前最高优先级 volatile state。
historical_failures 不能覆盖 pending_user_steers。
repair_focus 必须结合 contract revision 和验收缺口生成。
```

## 5. 固定执行流

### 5.1 普通用户输入

```text
QueryRuntime receives message
-> create UserSubmission
-> build ActiveWorkContext candidates
-> ActiveWorkRouter decides:
   A. no active work: start normal turn
   B. active work status question: answer status
   C. active work control: pause/stop/resume
   D. active work instruction: create ActiveTaskSteer
   E. unrelated new work: start normal turn
```

硬规则：

```text
如果 active work 正在 running，用户补充指令不能走 same_run_resume。
如果 active work paused/waiting，用户补充指令先 create steer，再 resume。
如果 active work terminal checkoutable，用户补充指令走 checkout fork，并把它提升为新合同修订，不只写 resume_context。
```

### 5.2 Active Task Steer

```text
create ActiveTaskSteer
-> append event active_task_steer_recorded
-> update TaskRun diagnostics pending_steer_count
-> if task is paused/waiting: resume and schedule executor
-> if task is running: do not start duplicate executor; active executor sees pending steer in next packet
-> if executor is stale: mark recovery_required and schedule controlled resume
```

硬规则：

```text
steer 不是 observation-only。
steer 必须在 RuntimeInvocationPacket volatile payload 中可见。
steer 必须有 consumed/rejected/superseded 终态。
```

### 5.3 TaskRun Executor

```text
load task_run
-> claim executor epoch
-> compute next_invocation_index from state/event log
-> assemble runtime
-> build observation_context:
   pending_user_steers
   active_contract_revisions
   current_facts
   artifact_evidence
   active_failures
   historical_failures
   repair_focus
-> compile RuntimeInvocationPacket
-> model returns ModelActionRequest
-> mark included steer as consumed only when model action acknowledges or acts on it
-> admission
-> execution
-> observation
-> projection refresh
-> self-review / acceptance / next packet
```

完成禁止条件：

```text
存在 blocking/high pending steer 未消费。
存在 active contract revision 未裁决。
存在 repair_focus 且未被 repair 或 accepted。
合同要求 artifact 但没有 artifact evidence。
测试/验证要求存在但没有 receipt。
```

### 5.4 Checkout Fork

```text
terminal interrupted checkoutable task
-> user asks continue or adds instruction
-> create child task_run
-> child contract inherits source facts
-> child contract explicitly includes current user instruction as goal/revision/acceptance delta
-> resume_context only stores historical recovery facts
```

硬规则：

```text
checkout fork 不能只把 user_instruction 写入 prompt_contract.resume_context。
child task_run_goal 或 completion_criteria 必须体现用户当前要求。
```

## 6. Prompt 与 agent 可见输入要求

### 6.1 Task execution prompt 必须让 agent 理解 steer

给 agent 的提示应是角色和职责，不是开发说明。

建议加入 task execution prompt pack：

```text
你是当前长任务的执行 agent。
系统会给你 pending_user_steers，它们是用户在任务执行期间追加的最新要求。
你必须先判断这些要求是否改变当前目标、验收标准、约束或优先级。
如果它们只是补充执行方向，你需要把它纳入下一步行动。
如果它们改变了目标或验收标准，你需要请求 task_contract_revision 或说明需要用户确认。
你不能忽略 pending_user_steers 后直接宣布完成。
你不能把 historical_failures 当作当前工具不可用的证据。
完成前必须确认当前合同、pending_user_steers、repair_focus、artifact_evidence 和验证 receipt 都已闭合。
```

禁止写法：

```text
这是 steer 节点。
根据 pending input 执行修复。
```

### 6.2 Resume prompt 必须降级为恢复事实

`resume_context` 只能告诉 agent：

```text
上次在哪里中断。
哪些文件或 artifact 可能已被改动。
哪些 observation 是历史事实。
继续前必须检查当前状态。
```

`resume_context` 不能承担：

```text
最新用户目标。
最新验收标准。
最新修复要求。
```

## 7. 文件级实施计划

### 阶段一：建立 Submission、Steer、Sequence 数据模型

新增：

```text
backend/harness/loop/user_submission.py
backend/harness/loop/task_steering.py
backend/harness/loop/executor_sequence.py
backend/tests/task_steering_protocol_regression.py
```

修改：

```text
backend/runtime/shared/events.py
backend/runtime/shared/event_log.py
backend/harness/runtime/session_timeline.py
backend/harness/runtime/monitor_projection.py
```

完成标准：

```text
UserSubmission 可序列化、可追踪、id 唯一。
ActiveTaskSteer 有 pending/included/consumed/rejected/superseded 状态。
ExecutorSequence 能从 event log 或 state_index 恢复 next_invocation_index。
monitor 能显示 pending_steer_count 和 executor_epoch。
```

### 阶段二：重写 active work 输入路由

修改：

```text
backend/query/runtime.py
backend/harness/loop/active_work.py
backend/harness/loop/resume_policy.py
backend/harness/loop/task_executor.py
```

执行细节：

```text
1. QueryRuntime 收到 message 后先创建 UserSubmission。
2. ActiveWorkTurnDecision 输出不再直接触发 same_run_resume。
3. append_instruction_to_active_work 改为 create_active_task_steer。
4. continue_active_work 在有非空 user_message 时，也创建 steer 或明确 status/control。
5. paused/waiting 任务：先 steer，再 resume。
6. running 任务：只 steer，不重复启动 executor。
7. stale running 任务：steer 后标记 recovery_required，再由 scheduler 受控恢复。
```

完成标准：

```text
用户补充修复要求不会只落入 resume_context。
running task 收到补充要求不会返回“正在处理”后丢失语义。
same_run_resume 不再吞掉 user_message。
```

### 阶段三：RuntimeCompiler 注入 pending steer

修改：

```text
backend/harness/runtime/compiler.py
backend/harness/runtime/invocation_packet.py
backend/harness/loop/task_executor.py
backend/runtime/memory/tool_observation_ledger.py
```

执行细节：

```text
1. _observations_for_packet 读取 pending steers。
2. execution_state.system_projection 增加 pending_user_steers。
3. compile_task_execution_packet 的 volatile payload 必须包含 pending steers。
4. prompt_manifest 记录 volatile_state_refs 包含 pending_user_steers。
5. packet.observation_refs/context_refs 可追踪 steer refs。
```

完成标准：

```text
runtime_invocation_packet_compiled 事件中可看到 pending_user_steers。
高优先级 steer 在 packet 中排在普通 observations 之前。
```

### 阶段四：executor 单调 invocation 与 action id

修改：

```text
backend/harness/loop/task_executor.py
backend/harness/loop/model_action_protocol.py
backend/harness/runtime/compiler.py
backend/tests/query_runtime_runtime_loop_regression.py
```

执行细节：

```text
1. execute_task_run 启动时 claim executor_epoch。
2. step loop 不再使用 range(1, max_steps) 作为全局 id 来源。
3. invocation_index 从 ExecutorSequence.next_invocation_index 读取并递增。
4. parse model action 时，如果模型未给 request_id，生成 uuid/monotonic id。
5. duplicate action 检查基于全局 request_id，不误杀 resume 后的新 action。
```

完成标准：

```text
同一 task_run 多次 resume 不会出现重复 model-action:{task_run_id}:1。
packet_id、request_id、observation.request_ref 能跨 resume 唯一追踪。
```

### 阶段五：steer 消费、合同修订和完成门禁

新增：

```text
backend/harness/loop/task_contract_revision.py
backend/harness/loop/task_completion_gate.py
backend/tests/task_contract_revision_regression.py
backend/tests/task_completion_pending_steer_regression.py
```

修改：

```text
backend/harness/loop/task_executor.py
backend/harness/loop/model_action_protocol.py
backend/harness/loop/admission.py
backend/harness/runtime/compiler.py
```

执行细节：

```text
1. ModelActionRequest 支持 acknowledge_steer_refs 或 diagnostics.consumed_steer_refs。
2. 如果 agent 的下一步 action 明确处理了 steer，标记 consumed。
3. 如果 agent 判断 steer 改变目标，创建 TaskContractRevision。
4. completion gate 检查 pending steer、active revision、repair_focus、artifact evidence、receipt。
5. 未闭合时禁止 respond/completed，要求 repair/ask_user/block。
```

完成标准：

```text
agent 不能忽略用户中途要求后完成。
改变验收标准的用户输入不会只作为普通 observation 消失。
```

### 阶段六：checkout fork 合同升级

修改：

```text
backend/harness/loop/task_checkout.py
backend/harness/loop/resume_policy.py
backend/query/runtime.py
backend/tests/query_runtime_runtime_loop_regression.py
```

执行细节：

```text
1. checkout_task_run_for_resume 不再只写 resume_context.user_instruction。
2. child contract 增加 current_user_revision 或 revised_acceptance_criteria。
3. resume_context 仅保留历史恢复事实。
4. checkout fork 后第一个 packet 必须包含 source summary + current user revision。
```

完成标准：

```text
终态中断后继续时，新用户要求成为 child contract 的权威字段。
旧 resume_context 不再承担最新任务目标。
```

### 阶段七：监控、SSE 与卡死诊断

修改：

```text
backend/harness/runtime/monitor_projection.py
backend/harness/runtime/session_timeline.py
backend/api/orchestration_harness.py
frontend 相关 runtime monitor 组件
```

执行细节：

```text
1. monitor 显示 executor_epoch、last_packet_ref、pending_steer_count。
2. running 超过 freshness 且无 event，显示 stale/recovery_required。
3. 有 pending steer 但长期未 included，显示 steer_not_consumed。
4. SSE 输出 active_task_steer_recorded、steer_included、steer_consumed。
5. 用户可见文案不泄露内部 id，但诊断面板可显示 refs。
```

完成标准：

```text
任务不会只显示“running”而没有卡住原因。
用户能区分正在执行、等待确认、已接收补充、恢复中、已阻塞、已失败。
```

### 阶段八：旧链路删除和测试改写

删除或改写：

```text
same_run_resume 吞 user_message 的路径
checkout resume 仅写 resume_context.user_instruction 的路径
step_index 作为 request_id 唯一来源的路径
只保护旧 resume_context 形状的测试
允许 pending steer 未消费仍 completed 的测试或逻辑
```

保留但重接：

```text
RuntimeCompiler
RuntimeInvocationPacket
ModelActionRequest
AdmissionDecision
TaskObservationProjection
runtime_freshness
event_log
monitor_projection
```

完成标准：

```text
生产入口不再存在“用户新要求只进入 resume_context”的路径。
生产入口不再存在“continue 不记录当前 user_message”的路径。
生产入口不再新写 resettable action id。
```

## 8. 验证矩阵

### 8.1 单元回归

新增或改写：

```text
backend/tests/task_steering_protocol_regression.py
backend/tests/task_executor_sequence_regression.py
backend/tests/task_contract_revision_regression.py
backend/tests/task_completion_pending_steer_regression.py
backend/tests/query_runtime_runtime_loop_regression.py
backend/tests/runtime_monitor_projection_test.py
backend/tests/runtime_event_index_test.py
```

必须断言：

```text
running task 收到用户补充 -> 创建 ActiveTaskSteer，不 schedule duplicate executor。
paused task 收到用户补充 -> 先创建 steer，再 resume。
continue with message 不会吞掉 user_message。
checkout fork 的 child contract 包含当前用户要求。
pending high/blocking steer 未消费时不能 completed。
多次 execute_task_run 不产生重复 request_id。
runtime_invocation_packet_compiled 包含 pending_user_steers。
monitor 显示 pending_steer_count、stale、last_activity。
```

### 8.2 集成场景

必须覆盖：

```text
普通问答，不创建 TaskRun。
只读项目检查，走 bounded observation，不创建 TaskRun。
写入请求，由 agent request_task_run 后创建 TaskRun。
TaskRun running 期间，用户追加“不是这个，修美术资源加载”。
下一次 packet 必须包含该 steer。
agent 必须修订计划或执行修复，不能直接完成。
暂停后用户追加要求并继续。
终态中断后 checkout fork，并把用户新要求写入 child contract。
工具历史失败被标 historical，不阻止当前重试。
completion validator 失败进入 repair_focus，不能 completed。
```

### 8.3 真实启动验证

涉及 runtime、SSE、前后端联调，实施完成后必须使用固定端口实测：

```text
前端 Next.js: http://127.0.0.1:3000
后端 FastAPI/Uvicorn: http://127.0.0.1:8003
前端 API Base: http://127.0.0.1:8003/api
```

验证步骤：

```text
1. 清理旧 .next，固定 3000 启动前端。
2. 固定 8003 启动后端。
3. 打开本地 Edge 浏览器。
4. 创建一个需要文件修改和测试的长任务。
5. 在 running 期间输入修订要求。
6. 观察 monitor/SSE 是否显示 steer recorded/included/consumed。
7. 确认最终完成前包含真实文件修改、测试 receipt、acceptance。
8. 模拟 stale executor，确认 monitor 显示 recovery_required，而不是无限 running。
```

## 9. 切换规则

实施时必须遵守：

```text
一旦 ActiveTaskSteer 接入 active work，旧 append_instruction_to_active_work 不能再只写 observation。
一旦 ExecutorSequence 接入 execute_task_run，旧 resettable step_index id 不能再新写。
一旦 TaskContractRevision 接入 checkout fork，resume_context 不能再承载最新用户目标。
一旦 completion gate 检查 pending steer，所有 completed 路径都必须经过同一 gate。
一旦 monitor 显示 stale/recovery_required，scheduler 必须有对应 recovery 策略或明确 blocked。
```

禁止保留：

```text
以兼容为理由保留“同一用户新要求既可能进 steer，也可能只进 resume_context”的双路径。
以兼容为理由继续写 model-action:{task_run_id}:1 这种 resume 后重复 id。
以兼容为理由允许 pending steer 未消费但任务完成。
以兼容为理由让系统通过关键词替 agent 决定具体修复动作。
```

允许短期保留：

```text
读取旧 resume_context.user_instruction，用于迁移旧任务。
读取旧 model-action:{task_run_id}:{n}，用于旧 trace 展示。
读取旧 user_work_instruction observation，用于历史任务恢复。
```

保留条件：

```text
只能读旧格式，不能新写旧格式。
迁移读取必须转换为 ActiveTaskSteer 或 historical observation projection。
必须标注 removal condition。
```

## 10. 风险与控制

| 风险 | 控制 |
| --- | --- |
| steer 和 observation 双写导致模型看到重复指令 | steer 是权威 pending input，observation 仅为审计；packet 只展示 steer projection |
| 用户普通闲聊误入 active task | ActiveWorkRouter 仍判断 status/new work/normal response，但不能决定执行动作 |
| 合同修订过度复杂 | 初期只支持 instruction、acceptance_change、scope_change 三类 |
| executor epoch 引入竞态 | claim executor 时检查 claimed/running 状态，event log 写 executor_claimed |
| monitor 显示内部细节过多 | 用户正文隐藏 refs，诊断面板保留 refs |
| 旧任务迁移困难 | 旧格式只读迁移，遇到旧 user_instruction 生成 historical steer candidate |

## 11. 最终完成定义

重构完成必须同时满足：

```text
用户输入先成为 UserSubmission。
运行中任务的新用户要求进入 ActiveTaskSteer。
ActiveTaskSteer 进入下一次 RuntimeInvocationPacket。
high/blocking steer 未消费时不能 completed。
目标或验收变化进入 TaskContractRevision。
resume_context 只保存恢复事实，不保存最新权威目标。
checkout fork 的 child contract 明确包含当前用户要求。
execute_task_run 跨 resume 使用单调 invocation/action id。
每次模型调用都能追踪 RuntimeInvocationPacket。
每次工具执行都能追踪 ModelActionRequest、AdmissionDecision、ExecutionContext、ObservationRecord。
历史失败和当前失败通过 TaskObservationProjection 分区。
monitor/SSE 能显示 pending steer、stale、recovery、blocked、terminal。
前后端固定 3000/8003 真实启动验证通过。
旧链路不再新写。
```

如果实现后仍然存在“用户新修复要求只进入 resume_context 或普通 observation，agent 可以无视后完成”的路径，则本次重构视为未完成。

## 12. 推荐实施顺序

```text
1. 新增 UserSubmission、ActiveTaskSteer、ExecutorSequence 模型和测试。
2. 改 QueryRuntime/active_work，让用户补充要求进入 steer。
3. 改 task_executor/RuntimeCompiler，让 pending_user_steers 进入 packet。
4. 改 executor id 生成，消除 resume 重复 id。
5. 增加 steer consumed/rejected/superseded 状态。
6. 增加 TaskContractRevision 和 completion gate。
7. 改 checkout fork，让用户当前要求进入 child contract。
8. 改 monitor/SSE 和 session timeline。
9. 删除旧新写路径，迁移旧读路径。
10. 跑单元、集成、固定端口真实启动和 Edge 验证。
```

建议先做 1 到 4，解决当前 agent 无法完成修复任务的结构性根因；随后做 5 到 8，补齐任务修订、完成门禁和运行可观测性；最后做 9 到 10 完成切换。
