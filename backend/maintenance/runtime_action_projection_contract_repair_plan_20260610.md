# Runtime Action Projection Contract Repair Plan - 2026-06-10

## 1. 目的

本计划用于修复主会话投影系统中工具窗口、工具 observation、子 agent 控制、assistant 正文和下一轮回答之间的错位问题。

这不是一次文案清洗修复。目标是建立一条成熟 agent 必须具备的动作契约：

```text
模型请求动作
-> runtime 接管并投影动作
-> runtime 执行动作
-> runtime 记录 observation
-> observation 回灌给模型
-> 模型输出正文反馈
-> runtime 收口本轮
```

核心系统属性：

- assistant 正文只能来自模型的公开正文输出。
- 工具窗口只能来自 runtime public projection。
- 工具 observation 必须绑定同一个 tool_call / run / turn。
- 控制命令、协议字段、执行器错误和生命周期占位文本不得进入主聊天正文。
- 找不到锚点时必须 fail closed 或生成明确的 synthetic runtime placeholder，不能挂到最新 assistant 回答。

## 2. 当前破坏点

### 2.1 用户可见症状

- 工具窗口会出现在下一条回答上，看起来像旧工具泄露到了新回答。
- 有时只有工具动作，没有工具返回后的 observation 反馈。
- 子 agent 工具调用没有表现出正确的等待和返回链路。
- `开始处理`、`处理完成`、`正在处理` 等泛化系统状态曾进入主聊天体验。
- 控制类错误或内部命令可能被当作普通工具结果或正文候选展示。

### 2.2 系统根因

根因是动作链路中存在多个展示和锚定权威：

```text
backend event log
-> backend public projection envelope
-> backend session runtime timeline rebuild
-> frontend stream reducer
-> frontend history hydration
-> frontend activity component filters
```

这些层都有局部兜底。一旦事件延迟、history 缺少 assistant 消息、active turn 已进入下一轮，局部兜底就可能把旧 runtime 事件挂到最新 assistant message。

最危险的当前代码形态：

- `frontend/src/lib/store/publicProjectionReducer.ts`
  - `projectionMessageIndex()` 先接受当前 stream 的 `assistantId`，再看 envelope anchor。
  - 找不到 `message_id`、`run_id`、`turn_id` 后，会回退到最后一条 assistant。
- `frontend/src/lib/store/utils.ts`
  - `runtimeAttachmentsByAssistantMessageId()` 在无显式 `anchor_message_id` 时，使用 `assistantRefs.find(index >= anchorIndex)`。
  - 这会把旧 turn 的附件挂到后续 assistant。
- `backend/harness/runtime/session_timeline.py`
  - `_anchor_assistant_message()` 找不到同 turn assistant 后，也会按 index 向后找 assistant。
- `backend/api/chat.py`
  - `_runtime_run_refs_for_public_event()` 会把 active task refs 补进 stream event。这个方向可以保留，但必须确保补的是当前 event 的锚点，而不是把 active snapshot 作为跨事件兜底。
- `backend/runtime/tool_runtime/tool_control_plane.py`
  - subagent 已有 handler registry 和 fail-closed 趋势，但 agent_turn/task_run 两类 caller 的行为仍需要通过契约和测试证明不会走普通 executor 占位链路。
- `backend/harness/runtime/public_timeline_stream.py`
  - 有大量 suppression 文本和协议过滤。这些只能作为最后保护，不能作为主边界。

## 3. 本地设计依据

本计划继承并收紧以下本地原则：

- `backend/maintenance/codex_style_chat_runtime_ui_contract_design_20260602.md`
  - 聊天页面消费 public chat objects，不消费 raw runtime events。
  - 后端拥有语义投影，前端拥有布局。
- `backend/maintenance/agent_run_projection_single_authority_refactor_plan_20260605.md`
  - 开局、动作、反馈、todo、收尾由单一投影层决定。
  - observation 必须可见，不能被动作窗口吞掉。
- `backend/maintenance/agent_task_todo_subagent_runtime_repair_plan_20260608.md`
  - subagent 生命周期由 runtime/control plane 管理。
  - 父任务不能在 child subagent 仍 active 时直接完成。
- `backend/harness/runtime/compiler.py`
  - 已经在 action schema 中要求 tool_call 不写泛化状态词，不预测工具结果。
  - 这条 prompt 规则需要和 runtime 投影契约一起测试，而不是孤立存在。
- `authority-led-refactor` agent runtime pattern
  - 采用单向权责链：RequestFacts -> BoundaryPolicy -> ContextCandidates -> ModelTurnDecision -> ActionPermit -> RuntimeStartPacket -> ExecutionLoop。
  - 下游层不重新决定用户意图，不用隐式 fallback 改写上游事实。

## 4. 权威边界表

| 层 | 当前风险 | 目标权威 | 修复动作 |
| --- | --- | --- | --- |
| ModelTurnDecision | 模型可能把工具状态写成正文前置话术 | 只决定语义动作和自然语言正文 | schema/prompt 明确 tool_call 不写 `开始处理` 等泛化状态；测试保护。 |
| ActionPermit | subagent 或控制动作可能落入普通工具执行器 | 决定动作是否允许，不能替模型换动作 | subagent 只走 `subagent_control` handler；误入普通 executor 返回结构化 observation，不生成正文。 |
| ExecutionLoop | 工具结果可能缺少 observation 回灌或 public projection | 执行工具、记录 observation、回灌模型 | 每个 accepted tool_call 必须产生 `tool_started` 和 `tool_observed/tool_failed` 两类公开投影，且有模型可见 observation。 |
| Event Projection | runtime 状态和正文混在一起 | 只把 public timeline item 发给 UI | `body` slot 只允许 `source_authority=model` 和 `surface=assistant_body`。工具和控制事件不得产生 body。 |
| Timeline Rebuild | 无锚点时向后找 assistant | 历史 runtime 附件只能绑定明确 turn/message | 删除向后找 assistant 的 fallback；缺 assistant 时生成 synthetic placeholder。 |
| Frontend Reducer | envelope 找不到锚点就挂最新 assistant | 只按 envelope anchor / exact run / exact turn 更新 | 有 anchor 时必须先解析 anchor；解析失败则 drop 或 synthetic，不使用当前 stream assistant 兜底。 |
| Chat Rendering | activity 组件靠文本过滤防泄漏 | 只渲染契约化 public item | 过滤保留为防线，但测试不再依赖过滤补救主协议错误。 |

## 5. 推荐设计方向

### 5.1 单一动作契约

所有可投影动作必须有以下最小身份：

```ts
type RuntimeActionProjectionKey = {
  session_id: string;
  turn_id: string;
  turn_run_id?: string;
  message_id?: string;
  task_run_id?: string;
  run_id: string;
  tool_call_id?: string;
  projection_id: string;
  sequence: number;
};
```

规则：

- `turn_id` 是聊天轮次锚点。
- `message_id` 是 assistant message 锚点；如果缺失，前端可以合成 `history-message:${turn_id}:assistant`。
- `run_id` 指 turn_run 或 task_run，不能缺。
- `tool_call_id` 绑定工具动作和工具结果。
- `sequence` 只负责排序，不负责锚定。
- 同一个 public item 的 `item_id` 必须在 started 和 observed 阶段稳定，done observation 更新同一个工具窗口，而不是新开一个不相关窗口。

live stream 需要额外的本地绑定规则，因为前端会先创建一个临时 assistant message id，而后端 envelope 未必知道这个 id。允许使用当前 stream 的 `assistantId` 只有一个条件：前端已经把该 stream session 绑定到 envelope 的 `turn_id` 或 `run_id`，且后续 envelope 的 anchor 与这个绑定完全一致。没有完成绑定时，`assistantId` 不能作为 fallback。

### 5.2 固定执行流

#### A. 普通工具调用

```text
user turn opened
assistant stream/message emits tool_call
runtime records model_action_admission_checked
backend emits public_projection(tool_window, state=running, tool_call_id)
runtime executes tool
runtime records turn_tool_observation_recorded
backend emits public_projection(tool_window, state=done/error, same tool_call_id)
tool observation is appended to model protocol messages
model emits assistant_text_delta/final
backend emits public_projection(assistant_body) only for true model body
turn terminal closes current stream
```

禁止：

- 工具 started 事件没有 `turn_id/run_id`。
- observation 不带同一个 `tool_call_id` 或 action request ref。
- 前端用最后一条 assistant 接收孤儿工具事件。
- `done` 或 terminal receipt 变成正文。

#### B. 长任务 task_run

```text
assistant requests request_task_run
runtime creates TaskRun and binds ActiveTurnRecord
chat turn terminal visible=false when terminal_reason=task_executor_scheduled
task executor emits task events with task_run_id + anchor_turn_id
session timeline attachment anchors to original assistant turn
task observation/progress updates same runtime attachment
task final answer writes canonical assistant answer or task projection final, not both
```

禁止：

- `latest_interaction_turn_id` 把 task attachment 改挂到 continue turn。
- session rebuild 找不到 old assistant 后挂到 new assistant。
- `waiting_executor` 长期显示为正文反馈。

#### C. 子 agent

```text
parent model requests spawn_subagent
RuntimeToolControlPlane routes to subagent_control handler
SubagentControl creates child run and returns subagent_run_ref observation
parent model may continue other independent work
parent model requests wait_subagent
RuntimeToolControlPlane routes to same handler
wait_subagent returns mailbox status/result observation
parent synthesizes result; parent finalization gate checks active children
```

禁止：

- subagent lifecycle tools 调到普通 LangChain tool `_run/_arun`。
- `subagent_lifecycle_requires_task_runtime` 出现在用户正文。
- 父任务在 pending/running child subagent 未处理时 `respond` 完成。

#### D. steer / pause / stop

```text
user sends current-work control with expected_active_turn_id
runtime validates active turn
control action is recorded as runtime/control projection
if pause/stop: executor receives interrupt or lifecycle transition
if append/continue: steer queue records durable user fact
next executor model packet consumes steer
model outputs feedback after observation or terminal control result
```

暂停策略：

- 如果当前工具或 executor 步骤可中断，立即请求 pause/stop，并产生控制 observation。
- 如果当前步骤不可安全中断，记录 pause_requested/stop_requested，当前步骤收口后暂停或停止。
- UI 不应显示“已暂停”直到 runtime 确认状态迁移；可以显示“暂停请求已记录”作为 control projection。

## 6. 数据与协议调整

### 6.1 PublicProjectionEnvelope

现有 `authority=harness.public_projection.v1` 保留，但需要收紧：

- `anchor.turn_id` 对 tool/status/task/control 投影必须存在。
- `anchor.message_id` 可以缺，但不能用最新 assistant 替代。
- `anchor.task_run_id/run_id` 至少一个存在于 task/tool projection。
- `items[].slot=body` 只能在 `source_authority=model` 且 `surface=assistant_body` 时有效。
- `terminal.visible=false` 的事件不得更新 message body 和 stageStatus。
- envelope 有 anchor 且前端无法解析时，前端必须 drop 并记录 dev diagnostic，不能兜底展示。
- live stream 的本地 `assistantId` 不是权威 anchor；它只是当前 stream 在确认 `turn_id/run_id` 后的渲染目标。

建议补充字段：

```json
{
  "anchor": {
    "session_id": "...",
    "turn_id": "...",
    "message_id": "...",
    "run_id": "...",
    "task_run_id": "...",
    "turn_run_id": "...",
    "tool_call_id": "..."
  },
  "projection_contract": {
    "version": "runtime_action_projection.v1",
    "fallback_policy": "fail_closed",
    "message_anchor_policy": "exact_or_synthetic"
  }
}
```

### 6.2 SessionRuntimeAttachment

必须从“最近 assistant 附件”改为“明确 turn/message 附件”：

- `anchor_turn_id` 必须是原始发起 turn。
- `anchor_message_id` 如果有，则 exact match。
- 如果 `anchor_message_id` 缺失但 history 中存在同 `turn_id` assistant，绑定该 assistant。
- 如果 history 中不存在同 `turn_id` assistant，创建 synthetic assistant placeholder。
- 不允许使用 `assistant index >= anchor index`。

### 6.3 PublicTimelineItem

工具窗口统一使用：

```ts
type PublicToolWindowItem = {
  kind: "work_action";
  slot: "tool";
  surface: "tool_window";
  source_authority: "tool";
  item_id: string;
  tool_call_id: string;
  title: string;
  state: "running" | "done" | "error" | "waiting";
  subject_label?: string;
  observation?: string;
  recovery_hint?: string;
  trace_refs: string[];
};
```

同一 `tool_call_id` 的 done/error item 必须覆盖 running item，而不是生成并列残留。

## 7. Prompt 配套

Prompt 不是主修复手段，但必须和协议一致。

### 7.1 单轮 action schema

保留并加强 `backend/harness/runtime/compiler.py` 中 action schema 文案：

- `tool_call` 时 `public_progress_note` 默认为空。
- 如果确实有开局判断，必须是独立于工具状态的公开判断，不是“我开始处理”。
- 不得写：
  - `开始处理`
  - `正在处理`
  - `处理完成`
  - `正在建立任务运行`
  - `工具已完成`
  - `已发起工具调用，正在等待工具返回`
- 不得预测工具结果。
- 不得把控制命令写成最终回复。

### 7.2 工具 observation 后续提示

每次工具 observation 回灌给模型时，followup prompt 必须表达：

```text
你刚刚收到的是系统执行工具后的观察结果。
你需要基于观察结果继续判断下一步。
如果观察足以回答用户，输出自然语言正文。
如果仍需要工具，继续提交结构化 tool_call。
不要把工具协议、tool_call_id、runtime id、控制字段或内部错误码暴露给用户。
不要只说“处理完成”；说明实际结论、证据、修改或下一步。
```

### 7.3 子 agent 工具 prompt

子 agent 工具说明必须维持当前方向：

- `spawn_subagent` 返回 `subagent_run_ref`。
- 父 agent 不得预测 child result。
- 必须调用 `wait_subagent` 或 `list_subagents` 观察子 agent。
- 父 agent 最终回答必须自己综合 child 结果，不能把 child 原始日志贴给用户。

需要补充测试：prompt registry 中不能出现把 subagent lifecycle 描述为普通工具 `_run` 占位执行的文案。

## 8. 模块实施计划

### Phase 1: 锚点 fail-closed

目标：彻底移除“挂最新 assistant”的投影路径。

文件：

- `frontend/src/lib/store/publicProjectionReducer.ts`
- `frontend/src/lib/store/publicProjectionReducer.test.ts`
- `frontend/src/lib/store/utils.ts`
- `frontend/src/lib/store/utils.test.ts`
- `backend/harness/runtime/session_timeline.py`
- `backend/tests/session_runtime_timeline_contract_test.py`

动作：

1. `projectionMessageIndex()` 改为 anchor-first。
2. envelope 有 `anchor.message_id` 时只 exact match。
3. envelope 有 `anchor.turn_id` 时只绑定同 `sourceIndex` 或同 history-generated id。
4. envelope 有 `run_id/task_run_id` 时只更新已有同 run attachment，不创建最新 assistant fallback。
5. `StreamSession` 增加 `boundTurnId/boundRunId` 或等价结构；只有 envelope anchor 与 bound stream 一致时，才允许使用本地 `assistantId`。
6. 无法解析 anchor 的 tool/task/status/control projection 直接 drop。
7. `toUiMessages()` 删除 `assistantRefs.find(index >= anchorIndex)`。
8. `session_timeline._anchor_assistant_message()` 删除向后找 assistant fallback。
9. 缺 assistant 时依靠 synthetic placeholder 承载 runtime attachment。

完成标准：

- 旧 task attachment 不会挂到新 reply。
- 延迟到达的 tool observation 不会更新当前新 assistant。
- 缺少 assistant message 的 turn 仍能显示 runtime placeholder。

### Phase 2: 工具 started/observed 合并契约

目标：确保“工具之后的反馈”稳定出现，并和工具窗口同源合并。

文件：

- `backend/harness/runtime/public_timeline_stream.py`
- `backend/harness/runtime/runtime_monitor_public_projection.py`
- `backend/harness/runtime/public_timeline_projection.py`
- `frontend/src/lib/store/publicTimeline.ts`
- `frontend/src/components/chat/PublicTimelineActivity.tsx`
- `frontend/src/components/chat/agentRunProjection.ts`

动作：

1. `model_action_admission` 产生 running work_action 时写入稳定 `tool_call_id/action_request_ref`。
2. `turn_tool_observation_recorded` 和 `task_tool_observation_recorded` 使用同一 semantic key 覆盖 running item。
3. observation detail 为空时也要显示明确结果状态，如“结果已返回”，但不能显示 raw JSON 或 runtime id。
4. frontend merge 以 `tool_call_id` 优先，其次 `trace_refs/action_kind/subject_label`。
5. PublicTimelineActivity 不再通过“generic text”决定是否丢 observation；只根据 item contract 决定展示。

完成标准：

- 工具 started 先显示。
- 工具 observation 返回后同一窗口更新为 done/error。
- 没有出现只有工具没有 observation 的正常路径。

### Phase 3: 子 agent 控制链路收紧

目标：subagent lifecycle tool 永远不走普通工具占位执行。

文件：

- `backend/runtime/tool_runtime/tool_control_plane.py`
- `backend/capability_system/tools/tool_units/subagent_control_tool.py`
- `backend/harness/agent_control/controller.py`
- `backend/tests/runtime_tool_control_plane_regression.py`
- 需要时新增 `backend/tests/subagent_control_projection_regression.py`

动作：

1. `RuntimeToolControlPlane.invoke()` 对 `spawn_subagent/send_subagent_message/wait_subagent/list_subagents/close_subagent` 只允许 `subagent_control` handler。
2. `agent_turn` caller 若请求 subagent，必须明确返回不支持或切到正式 handler，不允许普通 executor。
3. `_SubagentLifecycleTool._run/_arun` 的 RuntimeError 只作为开发期 fail-closed，不允许进入 public projection。
4. wait_subagent observation 必须投影为 waiting/done/error，不阻塞 event loop。
5. 父任务 finalization gate 检查 active child runs。

完成标准：

- `subagent_lifecycle_requires_task_runtime` 不出现在 UI。
- wait_subagent 未完成时返回 waiting observation，父模型继续判断。
- child completed 后父模型收到 result observation 并输出正文综合。

### Phase 4: 正文和状态边界清理

目标：正文只来自模型公开正文，不再显示系统生命周期词。

文件：

- `backend/harness/runtime/public_projection_envelope.py`
- `backend/harness/runtime/public_timeline_stream.py`
- `backend/runtime/output_boundary/*`
- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/store/assistantContentVisibility.ts`
- `frontend/src/components/chat/ChatMessage.tsx`

动作：

1. `assistant_body` 只接受 model authority 的 body item。
2. `done/error/stopped` 不再向 message content fallback。
3. `stageStatus` 不显示 `开始处理/处理完成`，仅在空消息且无 activity 时显示极短非正文状态。
4. `sessionActivity` 可以显示 runtime 状态，但不能写入 assistant message content。
5. 删除依赖中文泛化词的主路径测试，替换为协议测试。

完成标准：

- 主正文无 `开始处理`、`处理完成`、raw `done`、`agent_turn_terminal`。
- 错误一定有用户可见反馈，但反馈来自 error/control projection 或模型正文，而非内部异常堆栈。

### Phase 5: Active turn / steer 时序一致性

目标：任务间反馈、观察、暂停、继续都绑定正确 active turn。

文件：

- `backend/harness/runtime/active_turn.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/task_lifecycle.py`
- `backend/harness/loop/task_executor.py`
- `frontend/src/lib/store/runtime.ts`
- `frontend/src/components/chat/ChatInput.tsx`

动作：

1. 发送 active work 控制时必须携带 `expected_active_turn_id`。
2. 后端 mismatch 返回结构化 error，不写正文。
3. pause/stop 分为 request accepted 和 state confirmed，不提前显示终态。
4. running 下 append instruction 写 durable steer，不开启第二 executor。
5. task_run finalization 前检查 pending/included-but-unconsumed steer。

完成标准：

- 当前任务反馈不会消失。
- 下一轮新请求不会继承旧 active turn 工具窗口。
- pause/continue 不产生双 executor 或虚假完成。

### Phase 6: 运行链路和页面验收

目标：以固定端口真实启动验证，不以静态测试替代。

动作：

1. 后端固定 `http://127.0.0.1:8003`。
2. 前端固定 `http://127.0.0.1:3000`。
3. 清理 `.next` 后启动前端。
4. 用浏览器验证：
   - 工具 started -> observation -> assistant final。
   - 子 agent spawn -> wait -> final。
   - 旧 task update 不挂新回答。
   - pause/continue 时序正确。

## 9. 文件级清单

| 文件 | 当前角色 | 计划动作 |
| --- | --- | --- |
| `frontend/src/lib/store/publicProjectionReducer.ts` | live envelope 到 message 的 reducer | 改为 anchor-first，删除 latest assistant fallback。 |
| `frontend/src/lib/store/utils.ts` | session history hydration | 删除 `index >= anchorIndex` fallback，改 exact-or-synthetic。 |
| `frontend/src/lib/store/events.ts` | stream event reducer | 建立 stream local assistant 与 `turn_id/run_id` 的绑定；不让 current `assistantId` 覆盖不匹配的 envelope anchor；raw visibility 仅用于 transport events。 |
| `frontend/src/lib/store/publicTimeline.ts` | timeline normalize/merge | 增加 tool_call_id 合并键；减少语义文本兜底。 |
| `frontend/src/components/chat/PublicTimelineActivity.tsx` | public activity 渲染 | 只渲染契约化 public item；保留过滤为最后防线。 |
| `frontend/src/components/chat/ChatMessage.tsx` | assistant/user message 渲染 | 正文和 runtime activity 分离，禁止 runtime fallback 成正文。 |
| `backend/api/chat.py` | public stream event 写入 | 确认 active refs 只补当前 event，必要时携带 explicit public_anchor。 |
| `backend/harness/runtime/public_projection_envelope.py` | public envelope 构造 | 收紧 anchor 和 body 规则，增加 projection contract 字段。 |
| `backend/harness/runtime/public_timeline_stream.py` | live timeline item projector | 建立 started/observed 工具合并契约。 |
| `backend/harness/runtime/runtime_monitor_public_projection.py` | monitor/history public projection | 与 live projection 使用同一 key/anchor 规则。 |
| `backend/harness/runtime/session_timeline.py` | history runtime attachment rebuild | 删除向后 assistant fallback；缺 assistant 时交给 frontend synthetic。 |
| `backend/runtime/tool_runtime/tool_control_plane.py` | 工具执行控制面 | subagent handler fail-closed；普通工具 executor 不接控制工具。 |
| `backend/capability_system/tools/tool_units/subagent_control_tool.py` | subagent tool definition | 保留 fail-closed，占位异常不允许进入 public UI。 |
| `backend/harness/runtime/compiler.py` | action schema/prompt packet | 强化 tool_call/status 文案边界并添加 prompt 测试。 |
| `backend/prompt_library/*` | agent 角色和规则 prompts | 去除开发说明式 prompt；补齐 observation 后续要求。 |

## 10. 验证矩阵

### 10.1 后端测试

```powershell
python -m pytest backend/tests/session_runtime_timeline_contract_test.py -q
python -m pytest backend/tests/public_projection_envelope_test.py -q
python -m pytest backend/tests/runtime_monitor_projection_test.py -q
python -m pytest backend/tests/runtime_tool_control_plane_regression.py -q
python -m pytest backend/tests/harness_single_agent_tool_runtime_regression.py -q
python -m pytest backend/tests/harness_model_action_protocol_regression.py -q
python -m pytest backend/tests/session_manager_runtime_contract_regression.py -q
python -m pytest backend/tests/prompt_accounting_ledger_test.py -q
python -m pytest backend/tests/dynamic_prompt_context_projection_test.py -q
```

新增或调整用例：

- history 中 old turn task attachment 不挂 new assistant。
- no assistant for anchor turn 时生成 synthetic placeholder。
- public envelope 有 old anchor 但当前 stream assistant 不同，不更新当前 assistant。
- accepted tool_call 必须产生 observation projection。
- subagent lifecycle tool 不走普通 executor。
- control command / raw protocol never visible in assistant body。

### 10.2 前端测试

```powershell
cd frontend
npm test -- --run src/lib/store/publicProjectionReducer.test.ts src/lib/store/utils.test.ts src/lib/store/runtime.test.ts src/components/chat/ChatMessage.test.ts src/components/chat/PublicTimelineActivity.test.ts src/components/chat/ChatPanel.test.ts
npm run lint
```

新增或调整用例：

- `applyPublicProjectionEnvelope` 不把 anchored old tool event 挂到 current assistant。
- `toUiMessages` 不再支持向后最近 assistant fallback。
- observation item 覆盖 running tool item。
- `开始处理/处理完成` 不作为正文出现。
- ask_user/control item 可以显示为控制反馈，但不成为普通 assistant content。

### 10.3 静态守护

```powershell
rg -n "find\\(\\(item\\) => item\\.index >= anchorIndex\\)|latest assistant|messages\\.length - 1" frontend/src/lib/store backend/harness/runtime -S
rg -n "开始处理|处理完成|正在处理当前请求|回答已生成并写回会话|会话输出完成" frontend/src backend/harness backend/runtime -S
rg -n "subagent_lifecycle_requires_task_runtime|model_action_request|action_type.*tool_call" frontend/src -S
```

注意：第二条搜索允许出现在 suppression/test/prompt policy 文件中，但不得出现在主展示路径和默认 public item 文案中。

### 10.4 真实运行验收

固定端口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action stop
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action start -FrontendMode dev
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/project_stack.ps1 -Action check
```

浏览器验收场景：

1. 简单读取文件工具：先显示工具动作，结果返回后显示 observation，最后模型正文收口。
2. 工具失败：工具窗口显示失败和恢复提示，正文不泄露 traceback 或协议字段。
3. 子 agent：spawn 后显示等待，wait 后显示 child 结果摘要，父 agent 输出自然语言综合。
4. active task 继续：旧任务反馈仍挂旧 turn，不挂新回答。
5. 新独立请求：旧 runtime 附件不污染新 assistant。
6. 暂停：pause_requested 和 paused 区分显示，不出现虚假“已完成”。

## 11. Cutover 规则

- 不保留旧 fallback 作为兼容路径。
- 旧历史中已经错误绑定的 runtime attachment 不在 reducer 中继续传播；必要时通过 history rebuild 重新锚定。
- 如果某个 envelope 缺少 anchor，先修后端 producer；前端只记录 diagnostic，不猜。
- 如果某个 task_run 缺少原始 turn，使用 task_run_id 结构派生 turn；派生失败则显示在 monitor/debug，不进入 chat。
- 完成 Phase 1 后，任何新增“挂最新 assistant”行为都视为回归。

## 12. 禁止捷径

- 禁止用扩大中文黑名单解决控制泄露。
- 禁止让前端根据文本猜测工具属于哪个回答。
- 禁止让 session timeline 用后一个 assistant 承接旧附件。
- 禁止把 subagent lifecycle tool 当普通 LangChain tool 执行。
- 禁止用 `done`、`completed`、`running` 这类状态词当正文。
- 禁止为了测试通过删除失败用例或降低断言。
- 禁止保留旧链路后再在新链路外层套判断。

## 13. 预期结果

完成后，主会话投影系统应该具备以下稳定性：

- 工具窗口不会泄露到下一轮。
- observation 不会被清洗丢失。
- 子 agent 有明确的 spawn/wait/result 生命周期。
- 控制命令不会暴露到 UI 正文。
- stream 恢复、history rebuild、live monitor 使用同一锚定语义。
- prompt、runtime、frontend reducer、history hydration 的契约一致。
- 后续遇到异常时会 fail closed 并给出结构化错误，而不是生成新的模糊边界。
