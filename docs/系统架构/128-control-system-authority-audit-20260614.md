# 控制系统权威审查报告（2026-06-14）

## 审查口径

本次审查只以当前代码、当前测试和当前前端投影实现为依据，不引用旧文档或旧计划。审查原则如下：

- 系统不能替模型拒绝用户的语义请求。
- 系统可以控制的只有开发者定义的安全边缘：文件/网络/命令/工具副作用、不可逆写入、真实资源不可用、协议无法执行等。
- 非安全类问题，例如 active turn 过期、当前工作不存在、关系不明确、工具作用域不匹配，应作为模型可见的状态事实、契约失败或资源观察交给模型，让模型回应用户并决定下一步。
- 前端只负责呈现和合并生命周期，不重新解释后端权威；后端必须给足稳定身份锚点，避免旧时序内容写入新时序。

成熟目标链路应收束为：

```text
RequestFacts
-> State/Boundary Observation
-> ModelTurnDecision
-> ActionPermit only for safety/resource/tool side effects
-> ExecutionLoop
-> Tool/State Observation
-> PublicProjection
-> Commit
```

当前系统的主要问题是：`CurrentWorkPermit` 把“当前工作状态契约”做成了“许可/拒绝模型”，并且在部分路径上会在模型运行前直接提交系统阻塞正文。这与上面的原则冲突。

## 结论总览

| 严重度 | 结论 | 影响 | 必改位置 |
| --- | --- | --- | --- |
| P1 | `CurrentWorkPermit` 把 active work 关系判断权限化 | 系统会用 `deny/block/allowed_action_types` 限制模型语义决策 | `backend/harness/entrypoint/current_work_boundary.py`, `backend/harness/runtime/compiler.py`, `backend/harness/loop/admission.py` |
| P1 | 任务期 steer 缺 active turn 时会在模型前终止 | 用户发出的“继续/补充”可能被系统直接挡回，模型没有机会解释或转入普通回应 | `backend/harness/entrypoint/runtime_facade.py`, `backend/tests/current_work_boundary_regression.py`, `backend/tests/active_turn_authority_regression.py` |
| P1 | final action admission 失败会系统提交 blocked 正文 | 部分非安全契约错误没有走“观察 -> 模型恢复”闭环 | `backend/harness/loop/single_agent_turn.py` |
| P2 | 前端投影仍存在 turn-only 回退锚点 | 后端若把 active steer frame 锚到旧 turn，UI 可能把旧时序内容写回新消息或反向串线 | `frontend/src/lib/projection/reducer.ts`, `frontend/src/lib/store/events.ts` |
| P2 | 工具生命周期骨架存在，但身份规则必须收紧 | 重复工具、开始/结果分裂、收口后仍显示临时工具状态都依赖 ID 是否严格一致 | `backend/harness/runtime/projection/projector.py`, `frontend/src/lib/projection/reducer.ts`, `frontend/src/lib/projection/reducer.test.ts` |
| P2 | 回归测试已经固化旧权限模型 | 不改测试会继续把错误架构当正确行为保护 | `backend/tests/current_work_boundary_regression.py`, `backend/tests/active_turn_authority_regression.py`, `backend/tests/dynamic_prompt_context_projection_test.py` |

## 现有控制链路

### 用户输入到模型前

1. `runtime_facade.astream` 创建/读取 turn，组装 active work、runtime assembly 和 turn facts。
2. `_decide_current_work_boundary_for_turn` 调用 active turn registry 做 expected active turn 校验。
3. `decide_current_work_boundary` 产出 `CurrentWorkBoundaryDecision`。
4. `current_work_permit_from_decision` 把 boundary decision 转成 `CurrentWorkPermit`。
5. 如果 `current_work_permit.execution_route == "terminal"`，`runtime_facade` 调 `_current_work_boundary_terminal_events`，提交 assistant message 并返回，不进入模型。
6. 否则编译 single agent packet，`RuntimeCompiler` 使用 `current_work_permit.allowed_action_types_for_next_packet` 作为本轮模型 action surface。

证据：

- `CurrentWorkPermit` 字段包含 `allowed_action_types_for_next_packet`、`decision`、`allows`、`denied_reason`、`enforced`：`backend/harness/entrypoint/current_work_boundary.py:70`
- `block` 被映射为 `permit_decision = "deny"`：`backend/harness/entrypoint/current_work_boundary.py:244`
- `ask_user/block` 被映射为 terminal route：`backend/harness/entrypoint/current_work_boundary.py:361`
- `runtime_facade` 在 terminal route 上直接返回：`backend/harness/entrypoint/runtime_facade.py:518`
- terminal path 直接提交 assistant message：`backend/harness/entrypoint/runtime_facade.py:765`
- compiler 直接采用 permit allowed actions：`backend/harness/runtime/compiler.py:2286`

### 模型动作到工具执行

1. `run_single_agent_turn` 编译 packet 并发出 `single_agent_turn_started`，包含 `allowed_action_types/current_work_permit/turn_id/turn_run_id`。
2. 模型输出 action request。
3. `admit_model_action` 判断 action 是否在本轮 action surface、工具是否可用、是否需要 task run、是否违反 plan mode 或副作用边界。
4. 允许的工具调用转成 `ActionPermit`，进入 tool control plane。
5. 被挡住的工具调用会变成模型可见 `ToolObservation`，模型可以继续恢复。

证据：

- single agent started event 暴露 `allowed_action_types/current_work_permit/turn_run_id`：`backend/harness/loop/single_agent_turn.py:371`
- tool action admission 失败转成 observation：`backend/harness/loop/single_agent_turn.py:925`
- observation 继续进入模型上下文：`backend/harness/loop/single_agent_turn.py:1051`
- `_tool_observation_from_admission` 明确让模型基于观察继续：`backend/harness/loop/single_agent_turn.py:3092`
- `ActionPermit` 对真实工具执行做风险和作用域校验：`backend/harness/loop/action_permit.py:12`, `backend/harness/loop/action_permit.py:153`

这一段是比较成熟的：安全/资源边界不执行动作，但会把事实交回模型。这个模式应该扩展到 current work 边界，而不是让 current work 在模型前终止。

## 主要问题

### [P1] CurrentWorkPermit 把状态契约错误写成了系统许可

当前 `CurrentWorkPermit` 的真实含义是：把本轮输入与 active turn/current work 的关系转成下一步执行路线和 action surface。但代码把它命名并实现成 permit：

- `decision = allow/deny/needs_user`
- `allows.active_work_control/request_task_run/tool_call`
- `denied_reason`
- `allowed_action_types_for_next_packet`
- `enforced=True`

这让“当前工作是否存在、是否新鲜、是否属于 active turn”变成了系统许可。系统因此拥有了业务语义层面的“允许/拒绝”权威。

损坏的边：

```text
active turn state facts -> model sees state -> model decides response/control
```

实际变成：

```text
active turn state facts -> CurrentWorkPermit decides allow/deny/action surface -> model can only在收窄范围内动作，甚至不被调用
```

必须改成：

- `CurrentWorkPermit` 删除或重命名为 `CurrentWorkBoundaryReceipt` / `ActiveWorkRelationReceipt`。
- 字段从 `decision/allows/denied_reason` 改为 `relation/status/mismatch_reason/available_operations/state_observation`。
- 它只能表达事实和可执行资源是否存在，不能表达“系统允许模型做什么语义动作”。
- `active_work_control` 只能在确实存在 fresh active work ref 时作为“可执行操作”开放；不存在时给模型 `active_turn_unavailable` 观察，由模型回应用户。

### [P1] stale/missing steer 在模型前终止

当 `active_turn_input_policy == "steer"` 且缺 `expected_active_turn_id`、缺 active work、或 active turn check 失败时，`decide_current_work_boundary` 直接返回 `action="block"`，然后 `runtime_facade` 直接提交“请刷新后重试”的 blocked final answer。

证据：

- 缺 expected turn 直接 block：`backend/harness/entrypoint/current_work_boundary.py:138`
- 缺 active work 直接 block：`backend/harness/entrypoint/current_work_boundary.py:154`
- active turn check 失败直接 block：`backend/harness/entrypoint/current_work_boundary.py:169`
- terminal route 不进入模型：`backend/harness/entrypoint/runtime_facade.py:518`
- terminal answer 由系统提交：`backend/harness/entrypoint/runtime_facade.py:786`
- 测试要求“不调用模型”：`backend/tests/active_turn_authority_regression.py:563`

这正是用户感受到“我的命令被边界控制阻止”的来源。正确行为应是：

- 不自动把补充提升到 latest task。
- 不控制一个不存在或不匹配的 active turn。
- 但仍启动模型 turn，把 `active_turn_unavailable/expected_active_turn_mismatch/terminal_active_work` 作为模型可见状态观察。
- 模型必须回应用户：说明状态变化，询问是否另开任务，或按普通请求处理。

也就是说，“不接入旧任务”是系统可执行边界；“怎么回应用户”属于模型。

### [P1] final action admission 失败不应直接系统 blocked

工具调用 admission 失败时，系统会生成 observation 给模型恢复，这是成熟路径。但 final action admission 失败后，当前代码尝试一次 repair，仍失败就直接提交 blocked assistant message。

证据：

- final admission 失败后提交 `answer_channel="blocked"`：`backend/harness/loop/single_agent_turn.py:1416`
- 与工具 admission observation 路径不一致：`backend/harness/loop/single_agent_turn.py:925`, `backend/harness/loop/single_agent_turn.py:3092`

必须改成：

- 安全边缘：危险工具、写入、网络、命令、真实资源不可用，可以不执行。
- 非安全协议/状态/作用域错误：生成 `model_action_contract_observation`，回给模型一次或多次恢复。
- 若模型持续输出无法解析的动作，最终也应是 runtime failure/contract failure 的透明状态，而不是“系统替模型拒绝用户请求”的业务话术。

### [P2] active work 解析层也使用了 denied 语义

`active_work_turn_decision_from_payload` 会把 relation ambiguity、非法 authority、非法 action 写成 `accepted=False/denied_reason`。

证据：

- `ActiveWorkTurnDecision` 包含 `accepted/denied_reason`：`backend/harness/loop/active_work.py:128`
- relation 非 current_work 直接 denied：`backend/harness/loop/active_work.py:189`
- denial observation 文案：`backend/harness/loop/active_work.py:245`

这里的正确职责是“解析/校验模型 action payload”。它可以说 payload invalid、relation ambiguous、operation unavailable；不应表达系统拒绝用户。

### [P2] 前端投影锚点仍有 turn-only fallback

前端发送任务期补充时，会先创建新的 queued active turn UI message，再带上旧 active turn 的 `expected_active_turn_id` 发请求：

- queued active turn 创建：`frontend/src/lib/store/runtime.ts:1571`
- steer 请求携带 `expected_active_turn_id` 和 `active_turn_input_policy="steer"`：`frontend/src/lib/store/runtime.ts:1612`

投影 reducer 选择消息时：

- 先尝试 `assistantId + streamAnchorMatchesFrame`
- 再尝试 `message_id`
- 再按 `turn_id` 找 assistant
- 再按强锚点/任务锚点回退

证据：

- `projectionMessageIndex` 的 turn-only fallback：`frontend/src/lib/projection/reducer.ts:159`
- session anchor 首次绑定后不覆盖：`frontend/src/lib/store/events.ts:529`
- active task turn gate 使用 boundTurnId 或事件 active_turn_id：`frontend/src/lib/store/events.ts:592`

已有测试覆盖了“旧 turn + shared task_run 不应写入新 turn”：`frontend/src/lib/projection/reducer.test.ts:477`。但还缺一个更贴近真实问题的测试：任务运行中用户发新 steer，UI 已创建新 assistant placeholder，后端 frame 如果带旧 active turn 的 `turn_id`、但 stream/session anchor 是新消息，应确保 frame 绑定新 assistant 或被拒绝，不能写回旧 assistant。

### [P2] 工具生命周期显示基本可行，但 ID 规则必须硬化

后端公开投影有工具生命周期状态机：

```text
tool_call_requested
-> tool_permission_decided
-> tool_item_started
-> tool_item_completed
```

证据：

- 缺 tool_call_id 会生成协议诊断：`backend/harness/runtime/projection/projector.py:38`
- permission 必须晚于 request：`backend/harness/runtime/projection/projector.py:56`
- started 必须绑定已允许 permission：`backend/harness/runtime/projection/projector.py:82`
- completed 必须绑定 started lifecycle：`backend/harness/runtime/projection/projector.py:108`
- started 事件携带 `tool_lifecycle_id/tool_call_id/permission_decision_id`：`backend/harness/loop/single_agent_turn.py:4551`

前端 ledger 也已经具备：

- request 作为 current action：`frontend/src/lib/projection/reducer.ts:234`
- completed retire current action：`frontend/src/lib/projection/reducer.ts:259`
- commit_ack retire transient activity：`frontend/src/lib/projection/reducer.ts:297`
- 一次工具调用 request/start/completion 合并到一条 timeline：`frontend/src/lib/projection/reducer.test.ts:216`
- 同名不同工具调用不合并：`frontend/src/lib/projection/reducer.test.ts:270`
- 收口后临时工具状态退出：`frontend/src/lib/projection/reducer.test.ts:531`

风险点：

- `timelineItemFromFrame` 优先用 `tool_call_id` 作为 timeline item id：`frontend/src/lib/projection/reducer.ts:481`。这适合“一次 model tool call 一条公开工具生命周期”，但如果同一个 `tool_call_id` 多次执行/retry，必须明确是合并为一次调用的多个 execution attempts，还是以 `tool_lifecycle_id` 显示多条。
- `ProjectionLifecycleState._tool_record` 在找不到 scoped key 时会按 `tool_call_id` fallback 查找：`backend/harness/runtime/projection/projector.py:136`。这有助于容错，但在多 stream/multi run 场景可能弱化隔离。

目标行为：

- 一次模型工具调用只能有一个 `tool_call_id`。
- 一次实际执行只能有一个 `tool_lifecycle_id` / invocation id。
- 同一个 `tool_call_id` 的 request/start/completion 在主视图合并为一次工具生命周期。
- retry 或二次执行必须有新的 `tool_lifecycle_id`，UI 要么折叠成同一个 tool call 的 attempt 子状态，要么显示为独立 attempt，不能靠标题或工具名合并。
- final commit 后，成功工具生命周期退到 trace；失败工具可 pinned；主正文只显示收口正文。

## `current-work permit` 到底是什么

它现在不是系统底层安全 permit，而是一个 active work 关系收据被错误命名为 permit。

当前意义：

- 记录本轮输入是否命中当前 active work。
- 记录 expected active turn 与实际 active turn 是否匹配。
- 决定是否开放 `active_work_control`。
- 决定本轮模型 action surface。
- 在 block 时直接阻断模型。

应有意义：

- 只作为 `CurrentWorkBoundaryReceipt`：告诉模型和执行器“当前 active work 状态是什么、是否新鲜、是否有可控制对象、如果不能控制原因是什么”。
- 不能包含 `decision=deny`、`allows`、`forbidden_next_actions` 这种授权语义。
- 不能让 `execution_route=terminal` 在非安全场景下跳过模型。
- 真正的 permit 只能是 `ActionPermit`，用于工具、文件、网络、命令、副作用等开发者定义安全边缘。

## turn_id / turn_run_id / run_id 应该如何分工

当前代码里这些 ID 同时用于模型 accounting、active turn、投影 anchor、task run 和 SSE，容易让人感觉“串线”。建议明确语义：

| ID | 应有含义 | 当前证据 | 使用规则 |
| --- | --- | --- | --- |
| `turn_id` | 用户语义轮次 / assistant 消息归属 | `single_agent_turn_started` 暴露 `turn_id`：`backend/harness/loop/single_agent_turn.py:371` | 用于消息归属和 active turn 绑定，不代表一次执行尝试 |
| `turn_run_id` | 单次 turn 执行尝试 | 模型 accounting 使用 `run_id = turn_run.turn_run_id`：`backend/harness/loop/single_agent_turn.py:793` | 用于工具 caller_ref、事件日志、重试隔离 |
| `stream_run_id` | SSE/前端流会话 | 前端 anchor 读取 `stream_run_id`：`frontend/src/lib/store/events.ts:552` | 用于前端当前流绑定，避免旧事件写入新 placeholder |
| `task_run_id` | 持续任务实例 | active work context / projection anchor 使用 | 不能单独决定 chat message 归属，因为同一任务可能跨多轮 |
| `run_id` | 泛化运行 ID，当前有混用风险 | projection anchor 读取 `runtime_run_id/run_id`：`backend/harness/runtime/projection/authority.py:178` | 不应作为主锚点；需要逐步拆成 `turn_run_id/stream_run_id/task_run_id/graph_run_id` |
| `tool_call_id` | 模型请求的一次工具调用 | tool projection 和 reducer 均使用 | 主视图工具生命周期的合并键 |
| `tool_lifecycle_id` | 工具实际执行实例 | started event 生成 invocation id：`backend/harness/loop/single_agent_turn.py:4582` | retry/attempt 的执行键，不能替代 `tool_call_id` |

投影主锚点优先级应为：

```text
message_id
-> turn_id + stream_run_id
-> turn_id + turn_run_id
-> turn_id
```

`task_run_id` 只能作为附属锚点，不能单独把事件归入某条 chat assistant message。

## 已经连通且应保留的线

| 线 | 结论 | 证据 |
| --- | --- | --- |
| 工具执行安全边缘 | 保留。`ActionPermit` 是真正 permit 层 | `backend/harness/loop/action_permit.py:12`, `backend/harness/loop/action_permit.py:153` |
| 工具 admission 失败交回模型 | 保留并推广到 current work | `backend/harness/loop/single_agent_turn.py:925`, `backend/harness/loop/single_agent_turn.py:3092` |
| active task steer 持久化 | 保留。它是 accepted steer 的执行记录 | `backend/harness/loop/task_steering.py:47`, `backend/harness/loop/task_executor.py:579` |
| 显式 UI task control 的 stale write guard | 保留。API button/control 可以 409，因为这是直接操作而非模型语义 turn | `backend/api/orchestration_harness.py:264` |
| public projection commit gate | 保留。`commit_ack` 是收口 authority | `frontend/src/lib/projection/reducer.ts:297`, `frontend/src/lib/projection/reducer.test.ts:531` |
| 内部控制 JSON 从正文隐藏 | 保留，但不能作为唯一防线 | `frontend/src/lib/internalControlText.ts:45`, `frontend/src/components/chat/ChatMessage.tsx:70` |

## 修改位置审查清单

### 后端控制系统

1. `backend/harness/entrypoint/current_work_boundary.py`
   - 删除/替换 `CurrentWorkPermit` 权限语义。
   - `decide_current_work_boundary` 不再返回业务 `block` 作为模型前终止。
   - 输出 `CurrentWorkBoundaryReceipt`：relation、active turn match、state_observation、available_operations、mismatch_reason。
   - `_allowed_next_actions` 不再由 current work receipt 直接塑造完整模型 action surface。

2. `backend/harness/entrypoint/runtime_facade.py`
   - 删除非安全 `execution_route == "terminal"` 的模型前提交。
   - stale/missing steer 转成模型可见 observation，并继续进入 single agent turn。
   - `_run_current_work_control_action_request` 保留 fresh revalidation，但失败时返回 observation 给模型，不直接 final blocked。

3. `backend/harness/runtime/compiler.py`
   - 删除模型可见 `current_work_permit` 授权语言。
   - 改为 `active_work_boundary_receipt` / `current_work_state_observation`。
   - prompt 中删除 “only current_work_permit can authorize active_work_control” 这类授权表述。
   - action surface 由 runtime capability + actual operation availability + safety edge 共同形成，不由业务 block 决定。

4. `backend/harness/loop/admission.py`
   - 拆分 admission 类型：`safety_denied/resource_unavailable/protocol_invalid/contract_observation/operation_unavailable`。
   - `active_work_control_permit_required` 改成 `active_work_operation_unavailable` 或 `active_work_state_mismatch`。
   - 非安全失败统一产出模型观察。

5. `backend/harness/loop/single_agent_turn.py`
   - final action admission 失败走 observation + model recovery，与 tool call path 对齐。
   - 只有真实安全边缘或运行时不可执行错误可以终止执行；用户可见正文应尽量由模型生成。
   - 工具 lifecycle 继续使用 `tool_call_id` + `tool_lifecycle_id`，并补充 retry/attempt 明确规则。

6. `backend/harness/loop/active_work.py`
   - `accepted/denied_reason` 改为解析/契约术语：`valid/mismatch_reason/operation_available`。
   - relation ambiguity 不叫 deny，作为模型可见 ambiguity observation。

7. `backend/harness/runtime/active_turn.py`
   - `compare_and_update_current_turn` 可以保留 CAS 语义。
   - 返回字段建议从 `accepted/denied_reason` 迁移到 `matched/mismatch_reason`。

8. `backend/api/orchestration_harness.py`
   - 保留 `_assert_expected_active_turn` 的 409。
   - 这是用户点击 UI 控制按钮时的 stale write guard，不是模型语义 turn 的拒绝权。

### 前端投影与显示

1. `frontend/src/lib/store/runtime.ts`
   - 继续在任务期输入时创建 queued active turn message。
   - 请求中必须同时带新消息锚点和 expected active turn ref，避免后端只锚旧 active turn。

2. `frontend/src/lib/store/events.ts`
   - `bindStreamSessionAnchor` 不应让旧 active turn anchor 覆盖新 stream/message anchor。
   - 对任务期 steer，应区分“当前 chat turn anchor”和“被控制的 active work ref”。

3. `frontend/src/lib/projection/reducer.ts`
   - `turn_id` 单独 fallback 只应在没有 stream/message 强锚点时使用。
   - 有 stream session 时，frame anchor 与 stream anchor 不兼容必须拒绝。
   - `task_run_id` 不能单独决定 message 归属。

4. `backend/harness/runtime/projection/authority.py`
   - `projection_anchor` 应显式区分 `anchor_turn_id` 与 `controlled_active_turn_id`。
   - public projection frame 必须有 chat message/turn anchor；active work ref 作为附属 refs。

5. `backend/harness/runtime/projection/projector.py`
   - 工具生命周期必须强制 request -> permission -> started -> completed 顺序。
   - scoped tool lifecycle fallback 需要限制在同一 `turn_run_id/stream_run_id` 内。

6. `frontend/src/components/chat/ChatMessage.tsx`
   - 保持正文与工具 timeline 分离。
   - 收口后主显示只看 committed body；trace/debug 不应重新进入正文。

### 测试必须重写

1. `backend/tests/current_work_boundary_regression.py`
   - 删除“fails closed before model”和“permit as only control authority”的旧断言。
   - 新断言：stale steer 不控制旧任务、不提升 latest task、模型收到 state observation 并能回应用户。

2. `backend/tests/active_turn_authority_regression.py`
   - 删除 `missing active turn steer should block before model`。
   - 保留 active turn stale revalidation：不能 append 到已失效任务。
   - 新断言：revalidation 失败进入模型可见 observation 或 runtime observation，不直接系统业务阻塞。

3. `backend/tests/dynamic_prompt_context_projection_test.py`
   - 删除 `current_work_permit can authorize active_work_control` 文案断言。
   - 改为 active work context 是 state fact，operation availability 来自 fresh active work ref。

4. `backend/tests/harness_model_action_protocol_regression.py`
   - 保留 JSON action schema、canonical `active_work_control.action`、parser validation。
   - 更新 admission 失败的恢复模型：非安全 contract failure 进入 observation。

5. `frontend/src/lib/projection/reducer.test.ts`
   - 增加任务期 steer 新消息锚点测试：旧 active turn ref 不能污染新 assistant。
   - 增加同一 task_run 多 turn、多 stream 的 projection 隔离测试。
   - 增加 tool retry/attempt 生命周期测试。

## 推荐重构阶段

### 阶段 1：去权限化 current work

目标：把 `CurrentWorkPermit` 改成 state receipt。

完成标准：

- stale/missing active turn 不再 terminal before model。
- 模型输入中出现 state observation，而不是 permit deny。
- `ActionPermit` 仍保留并只负责工具/副作用安全边缘。

### 阶段 2：统一 admission 恢复模型

目标：让非安全 action failure 和 tool failure 一样进入模型可见 observation。

完成标准：

- final action admission failure 不直接提交系统 blocked 正文。
- 工具 unavailable、requires task run、active work unavailable 均能作为 observation 让模型回应。
- 真实安全边缘仍在执行前阻止动作。

### 阶段 3：投影锚点拆分

目标：把 chat turn anchor 和 controlled active work ref 拆开。

完成标准：

- 用户任务期输入一定有自己的 assistant placeholder 和 message/turn anchor。
- active work ref 只表示被控制对象，不用于决定当前 assistant 消息归属。
- 旧 stream/turn/task frame 不能写进新 stream assistant。

### 阶段 4：工具生命周期硬化

目标：一次工具调用一次显示，开始/结果合并，收口后只留正文和必要 pinned failure。

完成标准：

- request/start/completed 必须共享 `tool_call_id`。
- started/completed 必须共享 `tool_lifecycle_id`。
- success completion + commit_ack 后 transient activity 退出主视图。
- failed tool 保持 pinned，直到后续 resolved/retired。

### 阶段 5：清理旧测试和旧语义

目标：删除保护旧权限模型的测试，改成保护目标行为。

完成标准：

- 没有测试再断言 `current_work_permit.decision == "deny"`。
- 没有 prompt/test 再说 `current_work_permit authorize active_work_control`。
- stale steer 相关测试断言“模型有回应、任务不串线、旧任务不被误控制”。

## 验证建议

后端重点：

```bash
pytest backend/tests/current_work_boundary_regression.py
pytest backend/tests/active_turn_authority_regression.py
pytest backend/tests/harness_model_action_protocol_regression.py
pytest backend/tests/dynamic_prompt_context_projection_test.py
```

前端重点：

```bash
npm test -- frontend/src/lib/projection/reducer.test.ts
npm test -- frontend/src/lib/store/runtime.test.ts
npm test -- frontend/src/components/chat/ChatMessage.test.ts
```

运行链路重点：

- 固定后端 `http://127.0.0.1:8003`。
- 固定前端 `http://127.0.0.1:3000`。
- 实测普通输入、任务期补充、任务期继续、active turn stale、工具成功、工具失败、final commit 后显示。

## 最终判断

当前控制系统不是完全错误：工具安全边缘、ActionPermit、工具 observation、公开投影 lifecycle、commit gate 都有成熟结构。但 current work 这条线把“状态事实/时序契约”错误升格成了“系统许可/拒绝”，并且有模型前 terminal path。这是控制系统串线和用户命令被边界挡住的核心原因。

重构方向不是再加一个权限层，而是删掉 current work 的权限化表达：系统只负责报告状态、守住安全边缘和执行真实可执行的动作；模型负责理解用户当前请求、解释状态变化、选择询问/回应/继续/另开任务。
