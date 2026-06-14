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

## Prompt 配套性补充审查

### 总体判断

Prompts 目前是“部分配套”。基础角色 prompt、worker prompt 和大部分环境生命周期 prompt 已经接近成熟 agent 写法：它们描述身份、职责、输入、输出、禁止事项、验证和失败处理。但 single-agent runtime prompt、动态运行边界 prompt、协议修复 prompt 仍然把系统控制协议、`allowed_action_types` 和 `current_work_permit` 授权语言暴露给模型，和本报告的控制系统原则不完全配套。

配套目标应是：

```text
Role/Responsibility Prompt
-> State Observation Prompt
-> Transport Schema / Action JSON Contract
-> Safety/Tool Execution Boundary
```

不能把 schema、permit、authority 字段本身写成 agent 的世界观。模型可以知道“本轮有哪些可执行操作、状态事实是什么、输出必须符合什么传输格式”，但不应被提示成“系统已授权/拒绝你做某个业务语义决定”。

### 已配套的 prompt 线

| 位置 | 结论 | 证据 |
| --- | --- | --- |
| system foundation prompts | 基本配套。强调最新用户请求、真实观察、工具失败是事实、不要让旧任务劫持新请求 | `backend/prompt_library/system_prompts.py:18`, `backend/prompt_library/system_prompts.py:26`, `backend/prompt_library/system_prompts.py:34` |
| main agent role prompts | 基本配套。描述当前回合职责、持续任务职责、观察 followup 职责 | `backend/prompt_library/agent_prompts.py:6`, `backend/prompt_library/agent_prompts.py:26`, `backend/prompt_library/agent_prompts.py:45` |
| worker prompts | 配套较好。大多数 worker 都以“你是一名...”开头，明确只负责局部职责，不替主 agent 最终裁决 | `backend/prompt_library/worker_prompts.py:10`, `backend/prompt_library/worker_prompts.py:83`, `backend/prompt_library/worker_prompts.py:105`, `backend/prompt_library/worker_prompts.py:139` |
| coding lifecycle prompts | 大体配套。明确旧摘要/旧任务只能作线索，控制观察不是最终回复 | `backend/prompt_library/environment_lifecycle_prompts.py:66`, `backend/prompt_library/environment_lifecycle_prompts.py:85`, `backend/prompt_library/environment_lifecycle_prompts.py:131`, `backend/prompt_library/environment_lifecycle_prompts.py:221` |
| developer-style prompt guard | 有检测“这是 runtime 节点/根据任务图执行”等开发说明残留 | `backend/prompt_library/rules.py:979`, `backend/tests/task_environment_registry_regression.py:522` |

这些内容可以保留，后续只需要把“权限/拒绝”一类语言限定到真实安全边缘。

### 不配套的 prompt 线

#### [P1] dynamic runtime prompt 仍暴露 `current_work_permit` 授权模型

证据：

- single agent packet 把 `current_work_permit` 放入 dynamic refs：`backend/harness/runtime/compiler.py:662`
- dynamic payload 直接包含 `current_work_permit`：`backend/harness/runtime/compiler.py:549`
- model-visible payload 暴露 `permit_id/decision/allows/allowed_action_types/denied_reason`：`backend/harness/runtime/compiler.py:2312`
- active work prompt 文案写着 “only current_work_permit can authorize active_work_control”：`backend/harness/runtime/compiler.py:2541`
- dynamic prompt projection 继续说 “current_work_permit 已授权”：`backend/harness/runtime/compiler.py:4280`, `backend/harness/runtime/compiler.py:4283`
- 测试断言这些文字存在：`backend/tests/dynamic_prompt_context_projection_test.py:1772`

必须改成：

- 模型看到 `active_work_boundary_receipt` 或 `active_work_state_observation`。
- 字段表达 `state/matched/mismatch_reason/available_operations/controlled_active_work_ref`。
- 删除 `permit_id/decision/allows/denied_reason/authorize`。
- prompt 说“当前是否有可控制 active work”，不说“系统授权你控制 active work”。

#### [P1] runtime boundary instruction 把 action surface 写成业务权限

证据：

- `_runtime_projection_instruction` 写“模型决策合同来自开发者 prompt 权威；当合同要求 JSON action...必须遵守”：`backend/harness/runtime/compiler.py:4140`
- 同一段写“你可以...在越界、缺少授权或无法继续时阻止”：`backend/harness/runtime/compiler.py:4167`
- `request_task_run` 仍以 `current_work_permit` 是否允许为条件：`backend/harness/runtime/compiler.py:4295`
- output contract 也写 “request_task_run is available only when current_work_permit allows”：`backend/harness/runtime/compiler.py:2448`

应改为：

- `allowed_action_types` 是传输/格式约束，不是业务许可世界观。
- `block` 是模型在真实边界不可恢复时的语义回应，不是系统要求模型拒绝用户。
- `request_task_run` 是否可执行来自 task lifecycle operation availability；若不可用，模型应看到 state/resource observation。

#### [P1] admission repair prompt 延续“运行边界已经拒绝”叙事

证据：

- `SINGLE_AGENT_ADMISSION_REPAIR_PROMPT` 写“运行边界已经拒绝上一动作”：`backend/prompt_library/utility_prompts.py:65`
- single turn final admission 失败当前会进入 repair，然后仍可能系统 blocked：`backend/harness/loop/single_agent_turn.py:1337`

应改为：

- “上一动作未执行，因为它不满足本轮可执行操作/工具资源/安全边缘。”
- 修复 prompt 不要求模型接受“被拒绝”叙事，而是要求模型基于 observation 重新回应用户。
- 非安全 contract mismatch 应进 observation-followup，而不是 admission repair closeout。

#### [P2] protocol prompt 与角色 prompt 混在同一层

证据：

- `RuntimeCompiler.compile_single_agent_turn_packet` 同一组 system messages 同时包含 global role prompt、stable runtime payload、tool index、personality、environment、agent instruction、dynamic runtime payload：`backend/harness/runtime/compiler.py:555`
- runtime pack 直接告诉模型合法动作、字段和 JSON 形态由 output contract 定义：`backend/prompt_library/packs.py:8`
- system call rule 直接要求 `authority` 与 `allowed_action_types`：`backend/prompt_library/rules.py:18`
- graph node prompt 直接把 JSON 顶层字段和 `authority` 写进角色 prompt：`backend/prompt_library/packs.py:44`

这不是全错，因为模型确实需要严格输出 JSON action；问题是 schema 指令和角色职责没有清楚分层。目标是：

- 角色 prompt：只描述身份、职责、判断标准、失败处理、用户回应义务。
- schema prompt：只描述输出格式、字段、校验，不解释业务权限。
- state observation：只描述当前事实和资源可用性。
- safety/tool boundary：只描述执行前会被系统检查的真实安全边缘。

#### [P2] “权限/拒绝”词汇过宽

证据：

- foundation prompt 写“系统负责执行工具、记录观察、校验权限和维护协议边界”：`backend/prompt_library/system_prompts.py:22`
- runtime rules 写“被拒绝时把拒绝当作事实边界”：`backend/prompt_library/rules.py:24`
- permission denial rule 使用“权限、沙盒、策略或用户拒绝”：`backend/prompt_library/rules.py:71`
- coding lifecycle 多处把权限、工具不可见、控制面拒绝并列：`backend/prompt_library/environment_lifecycle_prompts.py:93`, `backend/prompt_library/environment_lifecycle_prompts.py:165`

这些词在工具安全边缘里成立，但放到 current work / action contract / service unavailable 上会扩大成系统拒绝权。应统一改词：

- `permission denied` 只用于真实安全/授权/沙盒/用户审批边缘。
- `operation unavailable` 用于资源或服务未挂载。
- `state mismatch` 用于 active turn/current work 不匹配。
- `contract invalid` 用于模型 action payload 或任务合同结构不满足。
- `observation` 用于交回模型恢复的非安全失败。

### Prompt 修改位置清单

1. `backend/harness/runtime/compiler.py`
   - 删除 `current_work_permit` model-visible payload。
   - `_runtime_projection_instruction` 删除 authorize/permit 语言。
   - output contract 中 `request_task_run/current_work_permit` 改成 operation availability。
   - dynamic payload 改挂 `active_work_boundary_receipt`。

2. `backend/prompt_library/packs.py`
   - 保留 runtime single agent turn 语义裁决职责。
   - 把 JSON/action schema 句子缩短为“输出格式见 schema”，不要把 schema 字段当角色职责。
   - `active_work_control` 文案改成“当存在 fresh active work operation 时可请求控制动作”。

3. `backend/prompt_library/rules.py`
   - `RUNTIME_SYSTEM_CALL_PROTOCOL_RULE` 保留 schema 要求，但去掉“边界允许/拒绝”的业务色彩。
   - `RUNTIME_TURN_DECISION_ALIGNMENT_RULE` 保留 active_work_control 由模型语义裁决负责。
   - `RUNTIME_PERMISSION_DENIAL_RULE` 拆成 safety denial 与 operation unavailable 两条规则。

4. `backend/prompt_library/utility_prompts.py`
   - `SINGLE_AGENT_ADMISSION_REPAIR_PROMPT` 改名或改文案为 contract observation repair。
   - 删除“运行边界已经拒绝上一动作”的默认叙事。

5. `backend/harness/loop/single_agent_turn.py`
   - `_tool_limit_closeout_messages` 可以保留 JSON-only closeout，因为它是预算/工具限制后的格式收口。
   - `_agent_authored_closeout_messages` 已经更接近正确方向，应作为非安全失败的自然语言恢复模板参考。

6. `backend/tests/dynamic_prompt_context_projection_test.py`
   - 删除 `current_work_permit can authorize active_work_control` 和 `current_work_permit_required` 断言。
   - 改断言 active work context 是 state fact，operation availability 是独立字段。

7. `backend/tests/task_environment_registry_regression.py`
   - 现有 developer-style marker 测试只覆盖 coding prompt refs。
   - 增加 runtime pack、compiler dynamic instruction、utility repair prompt 的 prompt hygiene 检查。

### Prompt 与控制系统的目标配套语句

建议后续把 prompts 统一到类似表述：

```text
你负责理解用户当前请求，并基于本轮可见事实、工具观察和可执行操作选择下一步。
系统会执行工具和副作用动作，并在执行前守住安全边缘。
如果某个操作因状态不匹配、资源不可用或合同不满足而无法执行，你会收到观察；你需要向用户解释真实状态、选择替代路径、询问用户或说明无法继续。
不要把状态不匹配说成用户请求被系统拒绝。
不要把工具名、协议字段、内部 ID 或运行状态写成用户正文。
```

这一版与本报告的控制原则一致：系统守安全和执行契约，模型负责语义回应和下一步裁决。

## Codex / Claude Code 源码对照

### 对照口径

本节只对照项目目录外的当前源码，不引用旧文档。对照目标不是照搬某个实现细节，而是确认成熟 agent 在三件事上的边界：

1. 用户输入、任务期补充和中断如何进入运行时。
2. 权限/审批到底约束什么。
3. 工具生命周期和投影 ID 如何避免串线。

结论是：Codex 和 Claude Code 都有多层协议，但成熟设计不是“系统可以任意拒绝模型回应”。它们的拒绝主要出现在协议调用不满足前置条件、工具/命令/文件/网络安全边缘、用户显式审批、上下文容量等执行边界；用户语义请求和模型回应职责仍应保留给模型。

### Codex 对照

#### turn/start 与 turn/steer 是两类协议

Codex 的 app-server v2 协议把普通启动和任务期注入拆成两个 API：

- `TurnStartParams` 是普通 turn 入口，携带 `thread_id/client_user_message_id/input/cwd/permissions/sandbox_policy` 等 turn 配置：`D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\v2\turn.rs:61`
- `TurnSteerParams` 是运行中 turn 的注入入口，要求 `expected_turn_id` 必须匹配当前 active turn：`D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\v2\turn.rs:160`, `D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\v2\turn.rs:175`

Codex 的 `turn_steer_inner` 会拒绝没有 active turn、expected turn mismatch、非 steerable turn、空输入等协议错误：`D:\AI应用\openai-codex\codex-rs\app-server\src\request_processors\turn_processor.rs:749`, `D:\AI应用\openai-codex\codex-rs\app-server\src\request_processors\turn_processor.rs:761`, `D:\AI应用\openai-codex\codex-rs\app-server\src\request_processors\turn_processor.rs:780`。测试也明确 `turn/steer` 在没有 active turn 时返回 JSON-RPC error，并记录 analytics `result="rejected"`、`rejection_reason="no_active_turn"`：`D:\AI应用\openai-codex\codex-rs\app-server\tests\suite\v2\turn_steer.rs:40`, `D:\AI应用\openai-codex\codex-rs\app-server\tests\suite\v2\turn_steer.rs:92`, `D:\AI应用\openai-codex\codex-rs\app-server\tests\suite\v2\turn_steer.rs:102`。

这个设计可以借鉴的是：直接注入运行中 turn 的 API 必须有 expected active turn CAS，防止旧输入写进新任务。

不能照搬成当前项目做法的是：当用户在聊天 UI 发出一句“继续/补充/新命令”时，如果当前 active turn 不存在，不应由后端伪造 assistant blocked 正文。成熟边界应是：

```text
explicit turn/steer API precondition failure -> protocol error / state observation
chat user message accepted -> model sees active turn unavailable observation -> model responds
```

当前项目把 `active_turn_input_policy="steer"` 的缺失/过期状态转成 `CurrentWorkPermit.decision="deny"` 并在模型前 terminal，问题就在这里。

#### Codex 的权限模型集中在工具、命令、网络、文件和沙盒

Codex 的 approval/permission 结构集中在执行边界：

- `TurnStartParams` 可以覆盖 `approval_policy`、`approvals_reviewer`、`sandbox_policy`、`permissions`，这些都是运行环境/工具执行配置：`D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\v2\turn.rs:90`
- `RequestPermissionProfile` 只包含 `network` 和 `file_system`：`D:\AI应用\openai-codex\codex-rs\protocol\src\request_permissions.rs:14`
- approval reviewer 文档列举的是 sandbox escapes、blocked network access、MCP approval prompts、ARC escalations：`D:\AI应用\openai-codex\codex-rs\protocol\src\config_types.rs:160`
- guardian review action 覆盖 Command、Execve、ApplyPatch、NetworkAccess、McpToolCall、RequestPermissions：`D:\AI应用\openai-codex\codex-rs\protocol\src\approvals.rs:125`
- command approval request 绑定 `call_id/approval_id/turn_id/command/cwd/network/additional_permissions/available_decisions`：`D:\AI应用\openai-codex\codex-rs\protocol\src\approvals.rs:218`

这说明成熟权限层可以有 allow/deny，但它约束的是“要不要执行某个有副作用或受保护资源的动作”，不是“用户这句话是否允许模型理解和回应”。因此本项目应保留 `ActionPermit`，但删除 `CurrentWorkPermit` 的授权语义。

#### Codex 的公开事件把 turn 归属和 item 生命周期分开

Codex 的 item 流以 `thread_id + turn_id + item.id` 表达归属和生命周期：

- `ItemStartedNotification` 携带 `item/thread_id/turn_id/started_at_ms`：`D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\v2\item.rs:1066`
- `ItemCompletedNotification` 携带 `item/thread_id/turn_id/completed_at_ms`：`D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\v2\item.rs:1140`
- 增量事件携带 `item_id`，例如 agent message delta、command output delta：`D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\v2\item.rs:1159`, `D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\v2\item.rs:1231`
- MCP tool call item 自身有 `id/server/tool/arguments/status/result/error/duration`：`D:\AI应用\openai-codex\codex-rs\protocol\src\items.rs:177`

这与本报告建议一致：`turn_id` 是消息/轮次归属，工具/命令/文件变更必须有自己的 lifecycle item id。当前项目的 `tool_call_id + tool_lifecycle_id` 方向正确，但前端不能只靠 `turn_id` 或 `task_run_id` 回退归并。

### Claude Code 对照

#### 用户消息先进入会话，工具权限另行检查

Claude Code 的 `QueryEngine.ask` 先处理用户输入，生成 `messagesFromUserInput`，推入 `mutableMessages`，并在进入模型 loop 前写 transcript：`D:\AI应用\claude-code-nb-main\QueryEngine.ts:411`, `D:\AI应用\claude-code-nb-main\QueryEngine.ts:430`, `D:\AI应用\claude-code-nb-main\QueryEngine.ts:450`。随后才构建 system prompt、工具上下文和 query loop：`D:\AI应用\claude-code-nb-main\QueryEngine.ts:490`, `D:\AI应用\claude-code-nb-main\QueryEngine.ts:675`。

它也会记录工具 permission denials，但 denials 是 `tool_name/tool_use_id/tool_input` 级别：`D:\AI应用\claude-code-nb-main\QueryEngine.ts:243`, `D:\AI应用\claude-code-nb-main\QueryEngine.ts:631`。这支持一个重要设计原则：用户消息接受与工具执行许可应分层。工具被拒绝不等于用户请求被系统拒绝；模型应基于失败结果调整路径或向用户说明。

#### Claude Code 的 PermissionMode 是工具权限，不是 current work 权限

Claude Code 的 permission 类型集中在工具规则和模式：

- 外部 permission modes 包含 `acceptEdits/bypassPermissions/default/dontAsk/plan`：`D:\AI应用\claude-code-nb-main\types\permissions.ts:14`
- permission behavior 是 `allow/deny/ask`：`D:\AI应用\claude-code-nb-main\types\permissions.ts:38`
- permission rule value 是 `toolName + ruleContent`：`D:\AI应用\claude-code-nb-main\types\permissions.ts:53`
- `PermissionDecision` 是 allow/ask/deny，且 deny 携带 `toolUseID`：`D:\AI应用\claude-code-nb-main\types\permissions.ts:126`, `D:\AI应用\claude-code-nb-main\types\permissions.ts:176`
- `ToolPermissionContext` 由 mode、working directories、allow/deny/ask rules 组成：`D:\AI应用\claude-code-nb-main\Tool.ts:110`
- `filterToolsByDenyRules` 会按 deny 规则过滤工具池，`assembleToolPool` 把内置工具和 MCP 工具合并去重：`D:\AI应用\claude-code-nb-main\tools.ts:254`, `D:\AI应用\claude-code-nb-main\tools.ts:338`

Claude Code 的系统 prompt 也把这件事说得很窄：工具在用户选择的 permission mode 下执行；当工具调用不自动允许时，提示用户审批，若用户拒绝该工具调用，模型不要重复同一个调用，而应调整方法：`D:\AI应用\claude-code-nb-main\constants\prompts.ts:189`。

这与本项目的偏差很直接：本项目把 `current_work_permit` 放进模型世界观，并让它裁剪 `allowed_action_types`、授权 `active_work_control/request_task_run`。成熟实现里没有看到“当前任务关系 permit”这种业务权限层。

#### plan mode 是显式交互工具，不是隐式运行时拒绝

Claude Code 的 `EnterPlanModeTool` 明确是一个工具，用来请求进入 plan mode，并说明需要用户 approval：`D:\AI应用\claude-code-nb-main\tools\EnterPlanModeTool\prompt.ts:11`, `D:\AI应用\claude-code-nb-main\tools\EnterPlanModeTool\prompt.ts:85`。`AskUserQuestionTool` 也是显式工具，用于执行中澄清偏好和决策：`D:\AI应用\claude-code-nb-main\tools\AskUserQuestionTool\prompt.ts:22`。

这说明 mature agent 可以有“请求确认/请求选择”的交互协议，但这些协议应由模型主动使用，并对用户可见；不能由后端静默替模型拒绝用户输入。

#### Claude Code 强化 tool_use / tool_result 配对，避免重复和串线

Claude Code 在工具生命周期上有多重保护：

- Bash 等工具结果返回时使用同一个 `tool_use_id` 写入 `tool_result`：`D:\AI应用\claude-code-nb-main\tools\BashTool\BashTool.tsx:566`, `D:\AI应用\claude-code-nb-main\tools\BashTool\BashTool.tsx:618`
- remote session UI 收到 assistant tool_use 时把 tool id 加入 in-progress，收到 user tool_result 时按 `tool_use_id` 删除：`D:\AI应用\claude-code-nb-main\hooks\useRemoteSession.ts:244`, `D:\AI应用\claude-code-nb-main\hooks\useRemoteSession.ts:285`
- streaming fallback 会丢弃旧 executor，防止旧 `tool_use_id` 的结果泄漏到新响应：`D:\AI应用\claude-code-nb-main\query.ts:731`
- `ensureToolResultPairing` 会修复缺失/孤儿/重复 tool result；缺结果时插入 synthetic error，重复 tool_use id 会被剔除：`D:\AI应用\claude-code-nb-main\utils\messages.ts:5133`, `D:\AI应用\claude-code-nb-main\utils\messages.ts:5187`, `D:\AI应用\claude-code-nb-main\utils\messages.ts:5324`
- tool result 持久化说明 `tool_use_id` 是每次 invocation 唯一，内容对该 id 确定：`D:\AI应用\claude-code-nb-main\utils\toolResultStorage.ts:157`
- API 错误层专门识别 missing tool_result、unexpected tool_result、duplicate tool_use_id：`D:\AI应用\claude-code-nb-main\services\api\errors.ts:666`, `D:\AI应用\claude-code-nb-main\services\api\errors.ts:711`, `D:\AI应用\claude-code-nb-main\services\api\errors.ts:716`

这给本项目工具显示的成熟标准是：

```text
tool_call_id: 模型一次工具调用，必须唯一
tool_lifecycle_id: 实际执行尝试，必须唯一
tool_result/completed: 必须回连原 tool_call_id，并在 retry 时有明确 attempt/lifecycle
UI in-progress: 只能由同一 tool_call_id / lifecycle completion 清理
断流/重试: 必须 tombstone 或 discard 旧执行器，不能让旧结果进入新 turn
```

当前项目已有 request/start/completed/commit_ack 骨架，但还需要把 scoped fallback 限定在同一 `turn_run_id/stream_run_id`，并为 retry/attempt 定义显示规则。

### 成熟实现对本项目的修正结论

1. 保留真实权限层：`ActionPermit`、文件/网络/命令/工具副作用、UI 显式控制按钮 stale write guard。
2. 删除伪权限层：`CurrentWorkPermit.decision/allows/denied_reason/enforced/allowed_action_types_for_next_packet`。
3. 把 active work/current turn 检查改成 state receipt 或 observation：`matched/mismatch_reason/available_operations/controlled_ref`。
4. 普通聊天输入永远应有模型回应机会；如果 steer precondition 不满足，模型看到 `active_turn_unavailable`，而不是系统提交 blocked 正文。
5. 直接控制 API 可以返回 409/JSON-RPC error，因为那是显式执行协议；聊天语义 turn 不应被这种错误替代。
6. 工具生命周期必须以后端强 ID 和状态机为准，前端只合并同一调用/同一执行尝试，不按标题、工具名或裸 `task_run_id` 猜测。
7. prompt 中可以告诉模型工具 permission mode 和安全边缘，但不能把 `current_work_permit` 这类内部状态包装成业务授权世界观。

## 最终判断

当前控制系统不是完全错误：工具安全边缘、ActionPermit、工具 observation、公开投影 lifecycle、commit gate 都有成熟结构。但 current work 这条线把“状态事实/时序契约”错误升格成了“系统许可/拒绝”，并且有模型前 terminal path。这是控制系统串线和用户命令被边界挡住的核心原因。

对照 Codex 和 Claude Code 当前源码后，结论更明确：成熟 agent 可以有多层协议、审批和权限模式，但这些层主要守工具/命令/文件/网络/显式协议调用边界；它们不应成为隐藏的业务权限层，更不应在普通聊天输入路径上替模型提交“拒绝用户”的正文。

重构方向不是再加一个权限层，而是删掉 current work 的权限化表达：系统只负责报告状态、守住安全边缘和执行真实可执行的动作；模型负责理解用户当前请求、解释状态变化、选择询问/回应/继续/另开任务。
