# Agent Self-Pause Runtime Control Optimization Plan

## 1. Problem Summary

当前暂停/恢复链路已经具备一部分运行控制能力，但权限和语义分层不够成熟：

- 普通 `single_agent_turn` 可以通过 `active_work_control.action = pause_active_work` 控制当前 active work。
- 正在执行中的 `task_execution` agent 不能提交一等的自暂停动作；任务协议只允许 `respond | ask_user | tool_call | block`。
- `active_work_control` 在 `task_execution` 协议里被明确当作跨上下文字段禁止，因此 task agent 不能表达“我判断现在应主动暂停并保留续跑点”。
- `pause_active_work` 由模型选择时，当前 facade 仍用 `requested_by="user"` 调用暂停 gateway，导致事实归因不准确。
- 现有 runtime control signal 会在多个执行边界被转成 model-visible observation，容易把“暂停已发生/将断流”的事实误做成“暂停当下还要让 agent 收口”的交互。
- 工具取消只能取消 asyncio awaiter，不能保证打断同步线程中的文件写入；因此暂停系统必须记录工具完成/取消事实，而不是假设所有副作用都被硬中止。

这不是一个按钮问题，而是 agent runtime 的控制权问题：系统应该负责承载事实、执行安全边界和记录恢复点；模型应该负责语义判断，包括是否继续、是否改计划、是否写文件、是否询问用户。

## 2. Source Evidence

已经接通的链路：

- `backend/harness/loop/active_work.py` 定义 `pause_active_work`。
- `backend/harness/runtime/compiler.py` 在 single-turn 输出契约里暴露 `active_work_control` 和 `pause_active_work`。
- `backend/harness/loop/single_agent_turn.py` 可以解析并执行 `active_work_control`。
- `backend/harness/entrypoint/runtime_facade.py` 将 `pause_active_work` 转为 `TaskRunControlGateway.pause_task_run()`。
- `backend/harness/runtime/task_run_control_gateway.py` 统一调用 `request_task_run_pause()`。
- `backend/harness/loop/task_executor.py` 已有 pause/resume、runtime control signal、waiting_executor 和 resume_task_run 的基础状态。

当前缺口：

- `backend/harness/loop/model_action_protocol.py` 中 `TaskExecutionModelActionType = Literal["respond", "ask_user", "tool_call", "block"]`。
- 同文件的 `_TASK_EXECUTION_CROSS_CONTEXT_FIELDS` 禁止 `active_work_control` 进入 task execution。
- `backend/harness/runtime/packet_assembler.py` 的 task execution action surface 固定为 `("respond", "ask_user", "tool_call", "block")`。
- `backend/harness/runtime/compiler.py` 的 `task_execution_action_schema()` 也只声明这四类动作。
- `backend/harness/entrypoint/runtime_facade.py` 对模型选择的 `pause_active_work` 使用 `requested_by="user"`，归因不准确。

## 3. Target Principle

目标架构遵循成熟 coding agent 的权责链：

```text
Runtime Facts
-> Boundary Policy
-> Model Decision
-> Action Permit
-> Runtime Control Record
-> Execution Boundary
-> Resume Packet
```

分层原则：

| Layer | 允许做什么 | 禁止做什么 |
| --- | --- | --- |
| Runtime Facts | 记录暂停、断流、工具取消、文件变化、子 agent 状态、上下文缓存状态 | 猜测 agent 是否应该继续 |
| Boundary Policy | 校验安全边界、权限边界、是否存在可续跑上下文 | 替模型选择下一步 |
| Model Decision | 决定继续、暂停、自暂停、询问、阻塞、写工具、重规划 | 给自己越权、伪造事实 |
| Action Permit | 授权或拒绝模型请求的动作 | 把拒绝改写成另一个任务 |
| Runtime Control Record | 落账控制信号、checkpoint、continuation handle | 伪造最终回答 |
| Resume Packet | 把断开事实和可恢复状态交给 agent | 在恢复前自然语言要求 agent 收口 |

## 4. Recommended Design

### 4.1 新增 User-Steer-Gated Task Pause 动作

在 task execution action protocol 中新增一等语义动作，但它不是常驻开放能力。它只在当前 task execution packet 明确携带用户 steer / 用户中断事实时开放，用于让 agent 在尊重用户最新输入的前提下停在可续跑边界。

```json
{
  "authority": "harness.loop.model_action_request",
  "action_type": "pause_for_user_steer",
  "public_progress_note": "用户刚刚改变或打断了当前任务方向，我会先停在可继续状态，避免越过用户最新意图。",
  "public_action_state": {
    "visible_status": "blocked",
    "completion_status": "blocked",
    "current_judgment": "继续原步骤前需要先处理用户最新 steer。"
  },
  "pause_request": {
    "reason": "user_steer_requires_pause",
    "steer_ref": "pending_user_steers 中对应 steer_id",
    "resume_hint": "恢复后应先检查 ...",
    "checkpoint_summary": "已经完成 ...；未完成 ...",
    "requires_user_input": false
  }
}
```

命名可以最终定为 `pause_for_user_steer` 或 `task_control.pause_for_user_steer`。不推荐使用过宽的 `pause_self` 作为模型常驻动作名，因为它容易被误解成 agent 可以因任意主观理由暂停任务。目标语义是：用户 steer 到达后，agent 判断继续执行会越过最新用户意图，因此请求停在可恢复边界。

开放条件：

- 当前 task execution packet 必须包含未消费的用户 steer、用户暂停/打断事实，或明确的 user interruption signal。
- 该 steer 必须指向当前任务，而不是独立新问题。
- agent 必须说明 `steer_ref`、暂停原因、已完成内容、恢复时首先要重新判断的事项。
- 如果只是缺权限、缺资源、缺外部事实、模型不确定、工具失败或上下文预算不足，不使用该动作；应分别走 `ask_user`、`block`、工具观察恢复、系统 budget pause 或 runtime recovery。

### 4.2 自暂停不是工具

user-steer-gated pause 不应挂在普通 tool registry 里。它应该属于 model action protocol：

```text
model action -> protocol validation -> admission -> action permit -> executor lifecycle
```

原因：

- 暂停是任务生命周期动作，不是外部能力调用。
- 它不应经过文件/命令/网络工具的副作用权限逻辑。
- 它必须进入 action lifecycle、event log、runtime control、continuation，而不是仅返回一个 tool observation。

### 4.3 用户暂停和 Agent 自暂停分离

需要保留两类不同事实：

| 场景 | requested_by | signal kind | 语义 |
| --- | --- | --- | --- |
| 用户点暂停/停止输出 | `user` | `pause` / `interrupt_for_resume` | 用户打断当前输出或任务 |
| 普通 turn 中模型选择暂停 active work | `agent` | `pause` | agent 判断应暂停当前 active work |
| task execution 中模型因用户 steer 暂停 | `agent` | `pause` + `origin=user_steer_pause` | task agent 为尊重用户最新 steer 停在可续跑 checkpoint |
| 父 agent 暂停子 agent | `parent_agent` | `pause` | 父任务控制子任务 |
| 系统安全边界暂停 | `system` | `pause` / `safe_boundary` | 系统物理或安全边界介入 |

当前 `pause_active_work` 的 `requested_by="user"` 应修正为由 action origin 决定。

### 4.4 暂停事实应在恢复时交给 Agent

用户指出的原则是正确的：如果暂停会断开 agent 当前执行，那么不要假设暂停瞬间还能自然交互。目标行为应是：

```text
pause requested
-> runtime records facts
-> executor stops/cancels at boundary
-> task stays waiting_executor
-> resume requested
-> resume packet includes interruption facts
-> agent decides next action
```

恢复包至少包含：

- `pause_requested_at`
- `requested_by`
- `pause_reason`
- `interruption_boundary`
- `last_completed_action_ref`
- `inflight_tool_facts`
- `tool_cancel_or_completion_facts`
- `file_change_facts_since_pause`
- `subagent_status_snapshot`
- `context_cache_status`
- `continuation_handle`
- `checkpoint_summary`

关键点：系统只提供事实，不替 agent 判断是否继续原任务。

### 4.5 任何意外都应流出为 Runtime Signal

新增或统一以下信号类别：

| Signal | 触发 | Agent 可见时机 |
| --- | --- | --- |
| `transport_disconnected` | 前端断流、WebSocket/HTTP 中断 | 下一次恢复/继续 packet |
| `tool_cancel_requested` | pause/stop 尝试取消工具 | 当前任务 ledger 和恢复 packet |
| `tool_completed_after_cancel` | 线程内写入或命令在取消后仍完成 | 恢复 packet，必须作为事实告知 |
| `file_changed_during_pause` | 文件监督发现变更 | 恢复 packet 和 monitor |
| `subagent_interrupted` | 子 agent 被 cascade pause/stop | 父任务恢复 packet |
| `context_cache_stale` | 上下文缓存不满足续跑条件 | 恢复 packet，让 agent 判断 |
| `checkpoint_incomplete` | 暂停时 checkpoint 不完整 | 恢复 packet，让 agent 选择修复/询问/重跑 |

## 5. File-Level Execution Plan

### Phase 1: Protocol And Action Surface

Files:

- `backend/harness/loop/model_action_protocol.py`
- `backend/harness/runtime/packet_assembler.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/admission.py`
- `backend/harness/loop/action_permit.py`
- `backend/harness/loop/execution_kernel.py`

Actions:

- 将 task execution allowed action 在用户 steer 场景下扩展为 `respond | ask_user | tool_call | block | pause_for_user_steer`。
- 默认 task execution action surface 不开放暂停动作。
- 增加 `pause_request` 结构化字段，只允许在 `action_type=pause_for_user_steer` 时使用。
- packet assembler 根据 canonical pending user steer / interruption facts 决定是否开放该 action。
- 保持 `active_work_control` 禁止进入 task execution，避免外层 current work 控制和 task 自控混线。
- admission 对 `pause_for_user_steer` 校验 steer ref、当前 task 归属、未消费状态和 action surface，不进入 tool authorization。
- action permit 记录 `action_type=pause_for_user_steer`、`grant_scope=task_run`、`requested_by=agent`、`origin=user_steer_pause`。

Completion criteria:

- 没有 pending user steer 时，task execution packet 不暴露暂停动作。
- 有 pending user steer 且指向当前任务时，task execution packet 对模型可见 `pause_for_user_steer`。
- 协议解析接受合法 `pause_for_user_steer`，拒绝缺少 `steer_ref`、原因或非法字段的 payload。
- `active_work_control` 仍不能作为 task execution 动作进入。

### Phase 2: Executor Lifecycle

Files:

- `backend/harness/loop/task_executor.py`
- `backend/harness/loop/task_run_execution_control.py`
- `backend/harness/runtime/task_run_control_gateway.py`

Actions:

- 在 executor 主循环处理 `action_request.action_type == "pause_for_user_steer"`。
- 写入 `task_run_user_steer_pause_requested` 或等价事件。
- 将 TaskRun 更新为 `waiting_executor`，`recovery_action=resume_task_run`。
- 写 checkpoint、work rollout item、runtime control diagnostics。
- 不生成最终 answer，不把自暂停投影成 completed。
- 可复用 `request_task_run_pause()` 的底层状态写入能力，但必须保留 `requested_by=agent`、`origin=user_steer_pause` 和 `steer_ref`。

Completion criteria:

- user-steer pause 后 task_run 停在同一个 `task_run_id`。
- monitor 显示“已暂停，可继续”，不是“失败/完成”。
- resume 后仍走同一个 task_run 的恢复调度。

### Phase 3: Resume Packet And Signal Delivery

Files:

- `backend/harness/loop/task_executor.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/packet_assembler.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/harness/runtime/runtime_control_signal_projection.py`
- `backend/runtime/context_management/provider_visible_context_ledger.py`

Actions:

- 把暂停事实从“暂停时要求 agent 收口”调整为“恢复时提供事实包”。
- 梳理 `_record_pending_runtime_control_signal_for_agent()` 和 `_runtime_control_signal_observation()` 的职责，避免暂停路径误导 agent 当下继续输出。
- 新增 resume-visible interruption block。
- 将工具取消、工具取消后完成、文件变化、子 agent 状态、context cache 状态汇入恢复包。

Completion criteria:

- 用户暂停后不会要求已被断开的 agent 继续自然语言收口。
- 恢复后 agent 能看到结构化 interruption facts。
- agent 可以自由选择 `tool_call`、`respond`、`ask_user`、`block` 或继续执行。

### Phase 4: Active Work Control Attribution

Files:

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/active_work.py`

Actions:

- 修正模型选择 `pause_active_work` 时的 `requested_by`。
- `user` 输入直接命令暂停时，记录 `requested_by=user`。
- 模型基于判断主动暂停时，记录 `requested_by=agent`。
- 事件 payload 增加 `origin_action_request_ref`。

Completion criteria:

- 审计记录可以区分用户暂停、agent 暂停、父 agent 暂停、系统暂停。

### Phase 5: Frontend Projection

Files:

- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/store/types.ts`
- `frontend/src/components/chat/ChatPanel.tsx`
- `frontend/src/components/monitor` 相关 task/run monitor 文件

Actions:

- UI 区分 `user_paused`、`agent_self_paused`、`interrupted_for_resume`、`hard_stopped`。
- 将 `agent_self_paused` 命名收敛为 `agent_paused_for_user_steer`，避免暗示 agent 可以任意暂停。
- 恢复按钮只表达“发送恢复请求”，不表达“强制继续任务”。
- 恢复后由 agent 根据 resume packet 决定下一步。

Completion criteria:

- 用户能看出暂停来源。
- 自暂停不会显示为错误。
- 继续按钮不会跳过 agent 判断。

## 6. Cutover Rules

- 不保留 task execution 里用 `block` 假装自暂停的旧语义。
- `block` 只表示真实阻塞：缺用户输入、缺权限、缺资源、不可继续。
- `pause_for_user_steer` 只表示 agent 因用户 steer 选择可续跑暂停。
- 没有 user steer / interruption fact 时，不开放 task-level pause action。
- `ask_user` 表示需要用户回答，不等同暂停；如果问完要停，应由 task 状态进入 waiting_executor。
- `active_work_control` 保持为 single-turn current work 控制，不混入 task execution。

## 7. Validation Plan

不新增回归测试文件。按项目要求使用代码审阅和真实运行验证：

1. 启动固定后端 `http://127.0.0.1:8003`。
2. 启动固定前端 `http://127.0.0.1:3000`。
3. 创建一个持续 TaskRun。
4. 在没有 pending user steer 时，确认 task execution packet 不暴露暂停动作。
5. 发送指向当前任务的 user steer。
6. 让 task agent 在任务执行中输出 `pause_for_user_steer`。
7. 确认 task_run 状态为 `waiting_executor`，`requested_by=agent`，`origin=user_steer_pause`。
8. 点击继续，确认恢复 packet 包含 user-steer pause facts。
9. 让 agent 自主判断下一步，确认系统没有强制续跑或强制阻塞。
10. 对比用户点击暂停，确认 `requested_by=user`。
11. 对比父 agent 暂停子 agent，确认 `requested_by=parent_agent`。
12. 触发一个文件写入工具后暂停，确认恢复 facts 能体现工具取消/完成事实，不伪造中止。

## 8. Risks And Guardrails

- 不要把 `pause_self` 做成普通工具。
- 不要把 task-level pause 作为常驻模型自由动作开放。
- 不要让 frontend 自己决定 task 是否继续。
- 不要把 resume 设计成强制继续原任务；resume 只恢复上下文和执行机会。
- 不要把中断 closeout 写成 final answer。
- 不要保留 `block` 兼容自暂停的旧语义。
- 不要让 runtime signal 只停留在日志里；必须进入 agent 可见恢复事实。

## 9. Recommended Next Step

建议先执行 Phase 1 和 Phase 2，形成最小闭环：

```text
user steer targets current task
-> task packet exposes pause_for_user_steer
-> task agent emits pause_for_user_steer
-> protocol accepts
-> admission verifies steer_ref and permits
-> executor records user-steer-gated agent pause
-> task_run waiting_executor
-> resume_task_run can continue same task_run_id
```

完成这个闭环后，再做 Phase 3 的恢复事实包重构。这样可以避免一次性改动过大，同时不会把旧的 `block` 假暂停继续留在主链路里。
