# 主会话正文、工具、提示词与投影链路修复计划书

日期：2026-06-11  
状态：待用户审阅，未实施。  
适用范围：主会话 agent turn、任务启动、工具调用、观察回灌、SSE 流式输出、前端投影页面、水合重建、runtime prompt。

## 1. 结论

当前问题不是单个前端组件、SSE 字节切片、清洗正则或某个工具 item 的小 bug，而是四条权威线没有闭合：

```text
模型正文权威
工具 lifecycle 权威
控制/状态权威
PromptPacket 与观察回灌权威
```

现在代码已经有 `assistant_text_delta/final`、`tool_item_started/completed`、`turn_completed` 的雏形，但还没有把“同一轮多次模型输出”“模型输出同时包含正文和工具调用”“JSON action 中的公开反馈”“工具后阶段总结”“前端 body 与 projection 分权”统一成一个稳定链路。

直接症状对应如下：

| 症状 | 第一根因 |
| --- | --- |
| 调用工具时没有正文 | 工具轮的模型正文/公开反馈没有进入稳定 body ledger；旧 `assistant_text` 又被 public stream 丢弃。 |
| 只能显示前几个字或被后续覆盖 | 前端按 messageId 维护单一 sequence/final，不能表达同一 turn 的多个正文 segment。 |
| 工具跑到下一条回答或顺序错位 | 工具和正文没有共享稳定 active turn / body segment / tool_call_id 排序锚点。 |
| 工具后没有观察反馈 | 工具 observation 进了 tool window，但 followup prompt 与 event contract 没强制产出 model-authored feedback/stage summary。 |
| `ask_user`、`blocked`、阶段反馈被隐藏 | 后端 output boundary 和前端 visibility 同时把这些 channel 当 debug/control 隐藏。 |
| “开始处理/处理完成”等状态词出现 | 控制状态、空收口、terminal 文案曾被当成正文或 projection feedback。 |
| 刷新后反馈分析不持久 | live 投影和 session timeline 重建不是同一事实源；task projection 与 public timeline/body 恢复互相覆盖或跳过。 |

本计划要求重建的是主链路，不是继续补旧 projection fallback。实施时应删除无权威的旧正文投影、旧工具窗口 fallback、旧状态正文、旧 body 拼接逻辑。

## 2. 既有原则对照

### 2.1 页面显示原则

来源：`docs/系统架构/099-主会话显示原则与公开投影契约-20260610.md`

必须遵守：

1. 正文只属于模型对用户的自然语言反馈。
2. 工具调用、等待、观察、暂停、错误属于动作层，不属于正文。
3. 控制命令、工具协议、JSON action、内部状态绝不进入用户可复制正文。
4. `开始处理`、`处理完成`、`done`、`assistant_message` 不作为正文。
5. 页面可以有临时 UI chrome，例如“正在思考”，但不持久化、不写入 assistant message。
6. 刷新后仍能重建开局反馈、工具动作、观察反馈、阶段分析、最终回答。
7. 不能把上一轮动作、工具或观察挂到下一轮回答。

### 2.2 控制协议原则

来源：`docs/系统架构/097-Agent动作控制契约端到端复审报告-20260610.md`

目标链路应为：

```text
ModelActionDecision
-> ActionAdmission
-> ActionExecutor
-> CanonicalOutputDecision
-> PublicProjection
-> FrontendRender
```

硬规则：

1. 控制动作永远不能降级成正文。
2. public SSE 不能输出 raw control payload。
3. 任何未知、未闭合、内部协议形状都 fail-closed。
4. 失败、拒绝、审批 deny 必须作为 observation 或 control/error surface 返回，不能静默吞掉。

### 2.3 投影系统原则

来源：`docs/系统架构/101-主会话投影系统权威重构方案-20260610.md`

必须保留的设计方向：

1. `ActiveTurn.state` 是一等状态，不写在 item.detail 里。
2. `phase_boundary` 由 runtime/StageController 产出。
3. `stage_summary` 由模型产出，说明用户可读判断和下一阶段方向。
4. 工具调用固定时序：

```text
model feedback
-> tool begin
-> tool waiting
-> tool observation
-> model observation_report 或 stage_summary
```

5. pause/stop/interrupt 立即进入 control surface 和 `waiting_safe_boundary`，到安全边界后 terminal。
6. steer 追加到 active turn，不启动新 turn；后续工具、观察、阶段总结仍归属原 active turn。

### 2.4 Prompt 与投影时序原则

来源：`docs/系统架构/102-任务开启正文与工具投影时序修复方案-20260610.md`

目标时序：

```text
UserInput
-> PromptPacket
-> ModelAction
-> PublicModelBody(if any)
-> ToolProjection
-> ToolObservation
-> ObservationToModel
-> ModelStageFeedback or NextAction
-> PersistedTimeline
-> FrontendRender
```

Prompt 输入链和公开投影链必须分离：

| 事实 | 进 PromptPacket | 进公开投影 | 进 assistant body |
| --- | --- | --- | --- |
| 模型自然语言正文 | 后续上下文可用 | 是 | 是 |
| 模型 action JSON | 结构化解析后可用 | 否 | 否 |
| 工具调用参数 | 必要时作为 trace refs | 工具目标摘要 | 否 |
| 工具原始结果 | 压缩或引用后可用 | 否，除非 debug 展开 | 否 |
| 工具观察摘要 | 是 | tool window/timeline | 否 |
| 模型基于观察的判断 | 后续上下文可用 | 是 | 是 |
| task_control / terminal_reason | 运行状态可用 | control/error surface | 否 |

### 2.5 六月五号流畅版本给出的局部经验

Commit `c7a722060` 中旧前端 `agentRunProjection.ts` 把 timeline 归约成：

```text
opening
liveAction
feedback
commandOutput
todo
closeout
stopped
tone
```

旧 `PublicRunActivity.tsx` 只显示当前动作、反馈、命令输出折叠、todo、收尾总结。旧后端 `public_timeline_stream.py` 会产生 `opening_judgment`、`work_action`、`observation_report`、`final_summary`，并压制 `done/completed/running` 等空状态词。

这说明“流畅感”来自单一归约视图和明确优先级，不是来自把所有事件塞进正文。新方案可以保留这种体验原则，但不能保留旧 projection 对正文的权威。

## 3. 当前代码证据

### 3.1 Public stream contract 只做了一半

当前 `backend/runtime/output_stream/public_contract.py` 已定义：

```text
assistant_text_delta
assistant_text_final
assistant_stream_repair
tool_item_started
tool_item_completed
turn_completed
```

并让这些 lossless events 不再附加 public projection envelope。

当前 `backend/api/chat.py`：

1. `_project_public_stream_event()` 把 internal `done/error/stopped` 转成 `turn_completed`。
2. `answer_candidate` 和 `assistant_text` 直接返回 `None`。
3. `model_action_admission` 转成 `tool_item_started`。
4. tool observation 转成 `tool_item_completed`。

这解决了“旧 projection body 抢正文”的一部分，但也带来新缺口：如果任务启动或 JSON action 只发 `assistant_text` / `public_progress_note`，public stream 会丢掉它，前端不会再从 projection body 找回来。

### 3.2 任务启动 opening 仍在旧事件里

当前 `backend/harness/loop/task_lifecycle.py`：

1. `start_task_lifecycle_from_contract()` 先 `commit_task_opening_message()`。
2. 然后 `yield assistant_text_event(content=opening_content, answer_channel="opening_judgment")`。
3. 调度 executor 后又 `yield final_answer_event(content="", answer_channel="task_control", terminal_reason="task_executor_scheduled")`。

而 `backend/api/chat.py` 当前把 `assistant_text` 丢弃。结果是：

```text
opening 已提交到存储或旧事件
-> live public stream 不显示 assistant_text
-> task_control 空收口/turn_completed 关闭本轮
-> 页面只剩工具/任务投影
```

修复目标不是恢复 `assistant_text` 旧入口，而是把 opening 作为模型正文 segment 进入新的 assistant body ledger；`task_control` 只进入 control/terminal，不写 assistant body。

### 3.3 同一响应含正文和 native tool_calls 时正文会被忽略

当前 `backend/runtime/output_boundary/boundary.py`：

```python
def ingest_ai_update(self, content: str, *, has_tool_calls: bool = False) -> None:
    ...
    if has_tool_calls:
        return
```

这意味着模型同一条返回中如果同时有安全可见 content 和 tool_calls，content 不进入 visible text。

当前 `backend/harness/loop/single_agent_turn.py::_single_agent_action_request_from_response()`：

1. 先解析 `protocol.native_tool_calls`。
2. 如果有 tool action，返回 `tool_actions`。
3. 没有把 `response.content` 作为同轮模型公开反馈 segment 一并返回。

这正好对应用户看到的“工具出来了，正文没了”：工具调用被识别，正文没有被提升为用户可见模型输出。

### 3.4 工具后 followup 被强制 JSON 且不流式输出正文

当前 `single_agent_turn.py`：

```text
current_requires_json_action = True
allow_assistant_text_delta = not current_requires_json_action
require_json_action = current_requires_json_action
```

工具 observation 后 followup 通常进入 JSON action 模式，因此 natural language delta 被关闭。若 JSON 里只有下一次 tool_call，没有被提升的 `public_progress_note/current_judgment/stage_summary`，前端就只能看到连续工具，没有模型观察反馈。

这不是前端清洗导致的，而是 runtime 没有把 structured model feedback 转成正文 segment。

### 3.5 ask_user / blocked / stage_feedback 被双重隐藏

当前后端 `backend/runtime/output_boundary/boundary.py` 把以下 channel 放入 `_DEBUG_ONLY_FINAL_TEXT_CHANNELS`：

```text
active_work_control
ask_user
task_control
blocked
orchestration_fail_closed
runtime_control
```

这会给它们 `canonical_state=progress_only`、`persist_policy=persist_debug_only`。

当前前端 `frontend/src/lib/store/assistantContentVisibility.ts` 又把以下 channel 当作 control 隐藏：

```text
ask_user
blocked
runtime_control
stage_feedback
task_control
```

控制命令不能进正文是对的，但模型对用户的自然语言提问、阻塞说明、阶段反馈必须可见。当前实现把“控制动作类型”和“模型可见说明文字”混成了同一个 channel。

### 3.6 前端 body 流是单 message 单 sequence，不能表达多段模型输出

当前 `frontend/src/lib/store/events.ts`：

1. `assistantTextStreamsByMessageId[assistantId]` 只维护一个 stream state。
2. `assistant_text_delta` 要求 sequence 从 1 连续递增。
3. `assistant_text_final` 直接 `content = data.content` 覆盖 message content。
4. `assistant_stream_repair` 直接用 replacement 覆盖 message content。

这适合“一次模型调用产生一个完整回答”，不适合成熟 agent 的真实 turn：

```text
模型 opening segment
-> 工具 A
-> 模型 stage feedback segment
-> 工具 B
-> 模型 final answer segment
```

如果每次模型调用都从 sequence=1 开始，前端会认为重复或 gap；如果每次 final 都覆盖 message.content，前面的 opening/stage feedback 会消失。

### 3.7 projection 已过滤 body/tool，但 renderer 仍混合两套活动来源

当前 `frontend/src/lib/projection/reducer.ts` 过滤：

```text
slot=body / surface=assistant_body
slot=tool / surface=tool_window
```

当前 `frontend/src/lib/projection/timeline.ts` 也跳过 body item。

这说明新方向已经是“正文不从 projection 来”。但 `frontend/src/components/chat/PublicTimelineActivity.tsx` 仍同时读取：

```text
timelineEntries
projectionEntries
```

并按：

```text
timelineFeedback
projectionFeedback
timelineTools
projectionTools
```

重新排序。task projection 仍可能生成 tool window 风格活动。结果是 live tool lifecycle 和旧 task projection activity 仍有机会重复、错位或把工具挤到正文/反馈之前。

### 3.8 当前 prompts 不够闭合

当前 `backend/prompt_library/packs.py` 和 `rules.py` 已经有正确方向：

1. 工具由系统执行。
2. 工具返回后重新判断。
3. 用户可见内容不能暴露内部编号、协议字段。
4. 公开进展必须和 action 一致。

但缺少强约束：

1. tool_call 前必须优先给真实、简短、可公开判断；没有则记录 contract gap，不能伪造。
2. 工具 observation 后必须产出“短观察反馈 / 下一步说明 / 阶段总结 / final_answer / ask_user / blocked”之一。
3. 连续工具调用不能成为裸工具链。
4. 阶段总结必须覆盖工具 refs，用于前端折叠。
5. `respond.final_answer`、`ask_user.user_question`、`block.blocking_reason` 必须成为可见模型正文，而不是 debug-only。

六月五号版本的 `runtime.rule.intent_feedback.v1` 明确要求“持续任务中出现补充要求、合同修订或状态质疑时，必须先裁决，并在公开进展中反映裁决”。当前规则只剩“先裁决”，公开反映力度变弱。

## 4. 目标架构

### 4.1 四条权威线

```text
PromptPacketLedger
  只给模型看：角色、用户请求、上下文、active turn、工具目录、观察、阶段边界、输出契约。

AssistantBodyLedger
  只收模型写给用户看的内容：natural content、public_progress_note/current_judgment、stage_summary、final_answer、ask_user question、blocking reason。

ToolItemLedger
  只收系统执行动作：tool/subagent start、waiting、observation、error、completed，稳定 tool_call_id。

ControlStateLedger
  只收系统状态：starting、model_turn、running_tool、waiting_approval、waiting_safe_boundary、interrupted、terminal。
```

前端只能按这四条线展示；不能从一条线推导另一条线的内容。

### 4.2 AssistantBodyLedger 是正文唯一来源

正文必须支持多 segment，而不是单一 message stream：

```text
assistant message
  body_segment 1: opening_judgment
  body_segment 2: stage_feedback
  body_segment 3: stage_summary
  body_segment 4: final_answer
```

每个正文事件必须携带：

```ts
type AssistantBodyFrame = {
  type: "assistant_text_delta" | "assistant_text_final" | "assistant_stream_repair";
  message_ref: string;          // 当前 assistant turn 的消息 ref
  body_segment_id: string;      // 同一模型输出或 structured feedback 的 segment id
  body_sequence: number;        // 当前 assistant message 内的 segment 顺序
  segment_sequence: number;     // 当前 segment 内 delta 顺序，从 1 开始
  content: string;              // delta 或 segment final
  segment_role:
    | "opening_judgment"
    | "conversation"
    | "observation_report"
    | "stage_summary"
    | "final_answer"
    | "ask_user"
    | "blocked";
  source_authority: "model";
  answer_channel: string;
  answer_canonical_state: "stable_answer" | "stable_feedback" | "needs_user" | "blocked";
  answer_persist_policy: "persist_canonical";
}
```

前端 message.content 不再等于某一个 stream 的 final，而是：

```text
join(body segments ordered by body_sequence)
```

这样同一 turn 内工具前正文、工具后反馈和最终回答不会互相覆盖。

### 4.3 工具 lifecycle 是 tool_item_* 唯一来源

工具显示只使用：

```text
tool_item_started
tool_item_completed
```

硬规则：

1. `item_id = tool_call_id`。
2. started 和 completed 原地更新同一个 item。
3. 工具 observation 只进入 tool window/timeline，不进入 assistant body。
4. raw stdout、文件列表、JSON、traceback 默认折叠或只进 debug trace。
5. subagent 作为长等待工具 item，spawn 后保持 running/waiting，wait 后 completed/error。

### 4.4 ControlStateLedger 不生成正文

允许状态：

```text
starting
model_turn
running_tool
running_task
waiting_executor
waiting_user
waiting_approval
waiting_safe_boundary
interrupting
terminal
```

硬规则：

1. `waiting_approval` 只由 ActionPermit/approval flow 设置。
2. `waiting_safe_boundary` 只由 pause/stop/interrupt flow 设置。
3. control surface 可以有 UI chrome，但不写 message.content。
4. 不能出现 `开始处理`、`处理完成`、`任务执行器已接管` 作为正文。
5. 错误必须有结构化 error/control item，并作为 observation 回灌给模型；不能阻塞链路后不给返回。

### 4.5 PromptPacketLedger 必须持久可追溯

每次模型调用前生成 `PromptPacket`：

```text
prompt_packet_ref
invocation_kind
role_prompt
user_request
visible_conversation_context
active_turn_state
task_contract_if_any
tool_catalog
permission_contract
observation_context
stage_boundary_context
action_output_contract
```

PromptPacket 不公开显示，只在 trace 中可查。public projection 不反喂模型，除非带原始 observation refs。

## 5. 固定执行时序

### 5.1 普通直接回答

```text
UserInput
-> PromptPacket(single_agent_turn)
-> model content stream
-> assistant body segment(conversation/final_answer)
-> turn_completed(completed)
```

### 5.2 首轮工具调用

```text
UserInput
-> PromptPacket(single_agent_turn)
-> model content/public_progress_note/current_judgment
-> assistant body segment(opening_judgment, if model provided)
-> action parsed
-> ActionAdmission/ActionPermit
-> tool_item_started
-> tool execution
-> tool_item_completed
-> ObservationToModel PromptPacket
-> model observation_report/stage_summary/final_answer/next tool
```

如果模型没有提供真实 opening：

```text
diagnostics.public_feedback_missing
-> tool_item_started
```

系统不能伪造“开始处理”。前端最多显示非持久 UI chrome 或工具动作。

### 5.3 同一响应 content + native tool_calls

```text
provider assistant response:
  content = safe visible text
  tool_calls = [...]

runtime:
  content -> assistant body segment before tool
  tool_calls -> action parse/admission
  admitted tools -> tool_item_started
```

`has_tool_calls=True` 不能再让 visible content 被跳过。

### 5.4 工具后继续工具

合法：

```text
tool A completed
-> model short observation_report or next_action note
-> tool B started
```

也允许在同一阶段内简短连续执行，但必须满足至少一项：

1. tool A 有短观察摘要。
2. tool B 的 body segment 说明“基于 tool A 结果，下一步检查什么”。
3. 阶段边界时产生 `stage_summary`，覆盖前面工具 refs。

不允许：

```text
tool A completed
-> tool B started
-> tool C started
-> no model feedback / no stage summary
```

### 5.5 阶段总结与工具折叠

阶段边界由 StageController 或等价模块判断：

```text
phase_boundary(runtime)
-> PromptPacket(stage_summary_request)
-> model stage_summary body segment
-> stage_summary.covers_tool_refs
-> frontend folds covered successful tools
```

阶段边界触发条件：

1. 开局判断结束，进入信息收集。
2. 信息收集结束，进入实施。
3. 实施结束，进入验证。
4. 验证结束，进入收口。
5. 工具失败导致改变方向。
6. 用户 steer 改变当前阶段目标。
7. 准备暂停、中断、阻塞或最终收口。

### 5.6 request_task_run

`request_task_run` 不能当作“模型交给系统所以正文结束”。

固定时序：

```text
model action request_task_run
-> assistant body segment(opening_judgment/public_progress_note)
-> task_run_contract_created
-> control state running_task / waiting_executor
-> executor tool/subagent events
-> executor observations
-> observation_prompt_packet_created
-> model stage_feedback/final/next_action
```

`task_executor_scheduled` 归属：

```text
raw trace: yes
control surface: yes
task projection: yes
assistant body: no
final answer: no
```

### 5.7 ask_user / blocked

模型选择 `ask_user`：

```text
user_question -> assistant body segment(ask_user)
ActiveTurn.state = waiting_user
turn_completed(status="completed", terminal_reason="ask_user")
```

模型选择 `block`：

```text
blocking_reason -> assistant body segment(blocked)
control/error item with reason/ref
turn_completed(status="failed" or "blocked")
```

`ask_user` 和 `blocked` 不是 raw control command。它们的 action JSON 不显示，但自然语言问题/阻塞说明必须显示。

### 5.8 approval / pause / stop / steer

Approval：

```text
ActionPermit needs approval
-> approval_request control item
-> ActiveTurn.state=waiting_approval
-> user approve/deny
-> approval_decision control item
-> deny becomes model-visible observation
-> model explains next step or closes
```

Pause / stop / interrupt：

```text
UI request
-> control item immediately
-> ActiveTurn.state=waiting_safe_boundary
-> runtime stops at safe boundary
-> interrupted/pause boundary event
-> turn_completed(status="stopped")
```

Steer：

```text
user steer with expected active_turn_id
-> ActiveTurn validates steerable
-> accepted: append to same turn/task context
-> rejected: structured control/error response
```

Steer 不创建新 `turn_started`，也不能让后续工具挂到下一条 assistant message。

## 6. Prompt 修复方案

### 6.1 统一写法要求

prompt 必须写给 agent 直接执行，不能写成开发节点说明。

禁止：

```text
这是 runtime 节点。
根据任务图执行 observation_followup。
```

应写成：

```text
你已经收到工具观察。
你需要判断这个观察对当前用户目标意味着什么，并决定继续检查、进入下一阶段、询问用户、阻塞或收口。
```

### 6.2 single_agent_turn prompt

补充硬规则：

```text
如果你需要调用工具，请先给用户一句真实、具体、简短的公开判断。
这句话只能说明你已经判断出的事实、需要确认的边界、或为什么下一步要调用该工具。
不要预测工具结果。
不要写“开始处理”“正在处理”“处理完成”。
不要输出 JSON、action_type、tool_call、内部编号或系统协议字段给用户。
如果你确实还没有形成任何判断，可以不写公开反馈；系统会记录 public_feedback_missing，但不会替你编造正文。
```

### 6.3 observation_followup prompt

补充硬规则：

```text
你已经收到工具观察。观察是事实输入，不是最终回答。
先判断观察对当前目标意味着什么，再选择下一步。

你的下一步必须属于以下之一：
1. respond：观察足以收口，final_answer 写完整回答。
2. tool_call：仍需观察，但必须给出一句基于当前观察的下一步说明，或保证当前阶段稍后会有 stage_summary。
3. ask_user：缺少用户决策，user_question 写清需要用户决定什么。
4. block：边界不足且无替代路径，blocking_reason 写清原因和继续条件。
5. active_work_control：用户明确要求暂停、停止、继续或追加当前工作。

不要连续裸调用工具。
不要把工具错误、控制命令、JSON 协议或内部字段复制给用户。
```

### 6.4 task_execution prompt

补充硬规则：

```text
每一轮动作都要让 public_progress_note 或 public_action_state 反映当前阶段判断。
如果合同满足，action_type=respond，final_answer 必须总结完成情况、真实产物、验证结果和剩余风险。
如果继续调用工具，公开反馈必须说明这一步服务于哪个阶段目标。
如果阶段已经完成或方向改变，产出 stage_summary，说明上一阶段结论、依据、下一阶段或收口条件。
```

### 6.5 stage_summary prompt

新增或并入 observation followup：

```text
当你完成一个阶段、发现关键事实、改变方向、遇到失败恢复、收到用户 steer，或准备最终收口时，给出阶段总结。

阶段总结应包含：
- 本阶段结论；
- 结论依据的关键观察；
- 下一阶段要做什么，或是否准备收口；
- 仍存在的风险或需要用户确认的边界。

阶段总结不复述完整工具日志。
```

### 6.6 subagent prompt

补充：

```text
如果你启动子 agent，请说明为什么需要它处理这部分工作。
子 agent 运行期间你会收到完成通知或观察摘要。
在 wait_subagent 返回前，不要引用子 agent 的结论。
wait 后由主 agent 综合结果，给出阶段反馈或下一步。
```

## 7. 后端修复计划

### Phase A - 冻结输出契约

文件：

- `backend/runtime/output_stream/public_contract.py`
- `backend/runtime/model_gateway/assistant_stream_frame.py`
- `backend/runtime/model_gateway/assistant_stream_normalizer.py`

动作：

1. 在现有 `assistant_text_delta/final/repair` 上补齐 body segment 字段：
   - `body_segment_id`
   - `body_sequence`
   - `segment_sequence`
   - `segment_role`
   - `source_authority="model"`
2. sequence 从“message 全局连续”改成“segment 内连续”。
3. `assistant_text_final` 只 final 当前 segment，不覆盖整个 assistant message。
4. `turn_completed` 不携带正文兜底。
5. lossless events 仍不附加 projection envelope。

完成标准：

```text
正文 segment、工具 item、terminal event 三者事件类型清楚，互不替代。
```

### Phase B - 修复模型响应解析

文件：

- `backend/runtime/output_boundary/boundary.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/runtime/model_gateway/model_response_protocol.py`

动作：

1. 删除 `has_tool_calls=True` 时跳过 visible content 的行为。
2. `_single_agent_action_request_from_response()` 返回结构中增加：
   - `visible_model_content`
   - `public_feedback_text`
   - `feedback_role`
   - `feedback_source`
3. native tool call 响应若同时有安全 content，先发 assistant body segment，再进入 action admission。
4. JSON action 中的 `public_progress_note/current_judgment/final_answer/user_question/blocking_reason` 按动作类型提升为 body segment。
5. hidden reasoning / `reasoning_content` 只进入 provider protocol history，不进入 public body。

完成标准：

```text
模型同一批返回中的正文和工具调用都被保留：正文进 body，工具进 tool lifecycle。
```

### Phase C - 修复 task_lifecycle 空收口

文件：

- `backend/harness/loop/task_lifecycle.py`
- `backend/harness/loop/presentation.py`
- `backend/api/chat.py`

动作：

1. `opening_content` 不再通过旧 `assistant_text` public 路径输出。
2. opening 进入 assistant body segment，role=`opening_judgment`。
3. `task_control` 空 `final_answer_event(content="")` 不再作为 assistant final。
4. `task_executor_scheduled` 只产生 control/task projection/turn state，不关闭正文通道。
5. schedule failed 的用户可见错误进入 `blocked` 或 error body segment，同时 control error item 记录结构化原因。

完成标准：

```text
request_task_run 后 opening 不丢，task_control 不覆盖正文，executor 事件仍归属当前 turn。
```

### Phase D - 修复 ask_user / blocked / stage_feedback 可见性

文件：

- `backend/runtime/output_boundary/boundary.py`
- `frontend/src/lib/store/assistantContentVisibility.ts`

动作：

1. 拆分 channel：
   - control-only：`runtime_control`、`task_control`、`active_work_control`
   - model-visible：`ask_user`、`blocked`、`stage_feedback`、`opening_judgment`
2. model-visible channel 如果内容通过清洗且有意义，必须 `persist_canonical`。
3. raw action JSON 继续 fail-closed，不因为 channel 可见就放协议文本。
4. 前端 visibility 只隐藏 control-only，不隐藏 model-visible body segment。

完成标准：

```text
用户问题、阻塞说明、阶段反馈能显示；控制命令和协议仍不显示。
```

### Phase E - 工具 lifecycle 单权威

文件：

- `backend/api/chat.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/runtime/tool_runtime/*`
- `backend/harness/runtime/projection/projector.py`
- `backend/harness/runtime/projection/items.py`

动作：

1. `tool_item_started` 只在 admission/permit 后发出。
2. `tool_item_completed` 只在 observation 记录后发出。
3. 两者必须共享 `tool_call_id`。
4. 没有 `tool_call_id` 的工具事件 fail closed，不挂最近 assistant。
5. 删除 live tool window 从 projection envelope 生成的旧路径。
6. projection 中的 `work_action_item` 只允许历史/任务摘要使用，不作为 live tool item 权威。

完成标准：

```text
工具不会生成两条投影，不会跑到下一轮，不靠 semantic key 猜合并。
```

### Phase F - StageController 与阶段总结

文件：

- 新增或重写 `backend/harness/runtime/stage_controller.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/prompt_library/packs.py`
- `backend/prompt_library/rules.py`

动作：

1. StageController 只决定阶段边界事实，不写用户正文。
2. 阶段边界触发后生成 stage summary prompt packet。
3. 模型返回 stage_summary body segment。
4. stage_summary 携带 `covers_tool_refs`。
5. 前端根据 `covers_tool_refs` 折叠成功工具。

完成标准：

```text
工具反馈短，阶段总结负责分析和下一阶段交代。
```

### Phase G - PromptPacket 可追溯

文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/prompt_manifest*`
- `backend/prompt_library/packs.py`
- `backend/prompt_library/rules.py`

动作：

1. 每次模型调用记录 `prompt_packet_ref`。
2. prompt manifest 标明 invocation_kind：
   - `single_agent_turn`
   - `tool_observation_followup`
   - `task_execution`
   - `stage_summary`
3. observation followup packet 必须包含：
   - tool name
   - target
   - status
   - key observation
   - error summary
   - artifact/trace refs
   - approval/control result if any
4. public projection 文案不反喂模型，除非引用原始 observation refs。

完成标准：

```text
能从任一工具后反馈追溯到模型看到的观察和 prompt 契约。
```

### Phase H - 水合重建同源

文件：

- `backend/harness/runtime/session_timeline.py`
- `backend/harness/runtime/projection/timeline_builder.py`
- `backend/harness/runtime/run_monitor/projector.py`

动作：

1. 重建顺序固定：

```text
assistant body ledger
-> tool item ledger
-> task projection
-> control state
```

2. `task_projection` 存在时不能跳过 public timeline/body。
3. 无 anchor 的投影 fail closed，不挂最新 assistant。
4. 旧历史 body/tool projection 不回灌成正文。
5. `event_offset/body_sequence/tool_call_id` 是排序锚点。

完成标准：

```text
刷新后顺序与 live 一致，opening、工具、观察反馈、阶段总结、最终回答都保留。
```

## 8. 前端修复计划

### Phase I - Body segment reducer

文件：

- `frontend/src/lib/store/types.ts`
- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/store/runtime.ts`

动作：

1. `assistantTextStreamsByMessageId` 改为 body segment ledger：

```ts
assistantBodySegmentsByMessageId: Record<string, {
  orderedSegmentIds: string[];
  segmentsById: Record<string, AssistantBodySegmentState>;
}>
```

2. delta/final/repair 按 `body_segment_id` 更新 segment。
3. message.content = 按 `body_sequence` 拼接所有 public body segments。
4. segment gap 只影响当前 segment，不冻结整个 message。
5. final 只 final 当前 segment，不覆盖其它 segment。

完成标准：

```text
同一 turn 多段模型反馈不会互相覆盖，不再只显示前几个字。
```

### Phase J - Tool item reducer

文件：

- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/projection/timeline.ts`
- `frontend/src/lib/api.ts`

动作：

1. `tool_item_started/completed` 以 `tool_call_id` upsert。
2. completed 覆盖 started 的 state/sections/observation。
3. `semanticKey` 只能用于非工具 fallback，不能合并 live tool。
4. completed without started 可以生成受控 placeholder，但必须绑定 turn/tool_call_id，不能挂最近 assistant。

完成标准：

```text
工具 started -> completed 原地更新；没有重复工具窗口。
```

### Phase K - PublicTimelineActivity 重写

文件：

- `frontend/src/components/chat/PublicTimelineActivity.tsx`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/lib/projection/reducer.ts`
- `frontend/src/lib/projection/runtimeTransportProjection.ts`

动作：

1. `ChatMessage` 正文只显示 message.content。
2. 删除 timeline body 与 message.content 拼接。
3. `PublicTimelineActivity` 只显示：
   - active tool/subagent
   - tool observation summary
   - control/waiting/error
   - todo/task attachment
   - folded covered tool records
4. 不再把 `projectionEntries` 和 `timelineEntries` 作为两个同级 tool 来源排序竞争。
5. task projection 只做任务附件摘要；live tool 只来自 tool item ledger。
6. 删除状态词映射成为正文的路径；UI chrome 只在无模型 body 且模型未返回前显示。

完成标准：

```text
正文、工具、控制、任务附件四层清楚；不会再有两条投影或工具飞到正文上方。
```

### Phase L - SSE gap 与前端稳定性

文件：

- `frontend/src/lib/api.ts`
- `frontend/src/lib/store/events.ts`
- `backend/api/chat.py`
- `backend/runtime/shared/stream_replay.py`

动作：

1. 后端已存在 gap catchup，需要对 lossless event 做强约束验证。
2. 前端发现 event_offset gap 时，不能把当前 body 永久卡住；应请求/等待 replay，并允许其它 lanes 继续按锚点显示。
3. `assistant_stream_repair` 只修复目标 segment。
4. `turn_completed` 前必须 flush body segments 和 tool lifecycle。

完成标准：

```text
丢一个 live event 不导致正文永久停在前两个字节。
```

## 9. 必须删除或停用的旧链路

这些不是兼容保留项，实施时必须清理：

1. `done.content` -> assistant body。
2. `answer_candidate` -> assistant body。
3. `assistant_text` 旧 public body 入口。
4. `task_control final_answer_event(content="")` 作为 turn 正文收口。
5. `model_action_admission` 直接生成 projection body。
6. live tool window 从 projection envelope 生成。
7. tool observation 用 `toolobs:*` 新 id 再靠 semantic key 合并。
8. no-anchor projection 挂最近 assistant。
9. `ChatMessage` 合并 timeline body 和 message.content。
10. 前端把 `ask_user/blocked/stage_feedback` 作为 control channel 全部隐藏。
11. `开始处理`、`处理完成`、`工具结果已返回` 等状态词写入 assistant content。
12. 用清洗函数返回空后回退 raw JSON、布尔值、内部状态词。

## 10. 文件级执行清单

### 后端

| 文件 | 动作 |
| --- | --- |
| `backend/runtime/output_stream/public_contract.py` | 定义 body segment/tool/control/terminal event family 与 lossless 规则。 |
| `backend/runtime/model_gateway/assistant_stream_frame.py` | 给 assistant_text frames 增加 body segment 字段；final 只 final 当前 segment。 |
| `backend/runtime/model_gateway/assistant_stream_normalizer.py` | 支持 segment 内 sequence；不负责整 message 覆盖。 |
| `backend/runtime/output_boundary/boundary.py` | 删除 has_tool_calls 跳过正文；拆分 control-only 与 model-visible channel。 |
| `backend/harness/loop/single_agent_turn.py` | 同时保留 content 和 tool_calls；JSON public feedback 提升为 body segment；工具后 followup 产出反馈/总结。 |
| `backend/harness/loop/task_lifecycle.py` | opening 改为 body segment；task_control 空收口改为 control/terminal。 |
| `backend/api/chat.py` | public stream routing 按四条权威线输出；不再让旧正文事件参与。 |
| `backend/runtime/shared/stream_replay.py` | lossless replay/gap contract 明确，terminal 前 flush。 |
| `backend/harness/runtime/projection/projector.py` | projection 不生成 body，不生成 live tool。 |
| `backend/harness/runtime/projection/items.py` | 删除或迁移 `model_body_item/opening_judgment/stage_summary` 的 projection body 权威。 |
| `backend/harness/runtime/projection/timeline_builder.py` | 历史重建与 live contract 同源。 |
| `backend/harness/runtime/session_timeline.py` | 按 body/tool/task/control 顺序水合，禁止 task_projection 吃掉 public timeline。 |
| `backend/harness/runtime/run_monitor/projector.py` | monitor 只输出状态/任务附件，不重建 body/tool 权威。 |
| `backend/prompt_library/packs.py` | 更新 single_agent_turn、task_execution、observation_followup、stage_summary prompt。 |
| `backend/prompt_library/rules.py` | 恢复并强化 intent/public feedback、阶段总结、连续工具约束。 |

### 前端

| 文件 | 动作 |
| --- | --- |
| `frontend/src/lib/api.ts` | 更新 SSE event 类型字段：body_segment_id、body_sequence、segment_role、tool_call_id。 |
| `frontend/src/lib/store/types.ts` | 新增 assistant body segment ledger、tool item lifecycle state。 |
| `frontend/src/lib/store/events.ts` | 分离 body segment reducer、tool item reducer、control reducer。 |
| `frontend/src/lib/store/runtime.ts` | active turn anchor、terminal、hydration 迁移到新 contract。 |
| `frontend/src/lib/store/assistantContentVisibility.ts` | model-visible channel 可见，control-only channel 隐藏。 |
| `frontend/src/lib/projection/reducer.ts` | projection 只处理 task/status/control attachment。 |
| `frontend/src/lib/projection/timeline.ts` | 工具 item_id first；body item 永久不参与 timeline 正文。 |
| `frontend/src/components/chat/ChatMessage.tsx` | 正文只来自 message.content；删除 timeline body 拼接。 |
| `frontend/src/components/chat/PublicTimelineActivity.tsx` | 重写为 tool/control/task attachment renderer；删除双来源工具排序竞争。 |

## 11. 实施顺序

按以下顺序一次性推进，不能先改前端掩盖后端缺口：

```text
1. 锁定 public event contract 和 body segment schema
2. 修后端模型响应解析：content + tool_calls 同时保留
3. 修 task_lifecycle：opening body segment + task_control 不收口正文
4. 修 output boundary：ask_user/blocked/stage_feedback 可见
5. 修 tool lifecycle：tool_call_id 单权威
6. 修 prompts：工具前反馈、工具后观察反馈、阶段总结、收口
7. 修 StageController / covers_tool_refs
8. 修 session timeline 水合
9. 修前端 body segment reducer
10. 修前端 tool item reducer
11. 重写 PublicTimelineActivity / ChatMessage 展示分层
12. 固定端口真实运行验证
```

如果实施中发现某个旧路径仍被依赖，先判断它是否是真实外部契约。不是外部契约就删除，不以兼容为理由保留旧链路。

## 12. 验收标准

功能验收：

1. 普通聊天有正文。
2. 首轮 tool_call 若模型有 content/public_progress_note，先显示正文再显示工具。
3. 同一响应 content + native tool_calls 时，正文和工具都显示。
4. 工具结果返回后，有工具短观察。
5. 工具后模型 followup 产生阶段反馈、阶段总结、继续工具说明、ask_user、blocked 或 final_answer。
6. 连续工具不会成为无反馈裸工具链。
7. 阶段总结出现后，被覆盖的成功工具默认折叠，但 refs 不丢。
8. request_task_run 后 opening 不丢，task_control 不覆盖正文。
9. ask_user 问题可见，blocked 说明可见。
10. pause/stop 立即显示 control state，到安全边界后 terminal。
11. steer 归属原 active turn，后续工具不挂下一轮。
12. 刷新后顺序仍是正文、工具、观察反馈、阶段总结、最终回答。

安全验收：

1. raw JSON action 不进入正文。
2. `tool_call`、`action_type`、`model_action_request` 不进入正文。
3. `runtime_control/task_control/active_work_control` 不进入正文。
4. hidden reasoning / `reasoning_content` 不进入正文。
5. `done/error/stopped/turn_completed` 不写正文。
6. 清洗为空不回退 raw protocol、布尔值、内部状态词。
7. 不出现 `开始处理`、`处理完成`、`任务执行器已接管` 作为正文。

稳定验收：

1. 正文不会卡在前几个字节。
2. 每个 body segment 的 delta/final 不覆盖其它 segment。
3. SSE gap 通过 replay/repair 收敛。
4. 每个工具只有一个 item，started/completed 同 id。
5. 无 anchor 事件不挂最近 assistant。
6. terminal 前 body/tool/control 已 flush。

## 13. 验证方式

用户已经明确要求先把逻辑理顺，不要用测试掩盖问题。因此实施后的验证顺序应为：

1. 代码级链路审查：逐项确认旧 body/tool fallback 删除。
2. SSE 抓包：真实查看事件顺序和字段。
3. 固定端口实测：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api base: http://127.0.0.1:8003/api
```

4. 手动触发场景：
   - 直接回答。
   - 工具前有正文的 tool_call。
   - content + native tool_calls。
   - 工具后继续工具。
   - 工具后 final_answer。
   - ask_user。
   - blocked。
   - request_task_run。
   - subagent spawn/wait。
   - pause/stop。
   - steer。
   - 刷新水合。
5. 只有链路真实稳定后，再按需要补契约测试；测试只保护新 contract，不保护旧 fallback。

## 14. 禁止事项

实施中禁止：

1. 为了让页面有字，伪造“开始处理/处理完成”正文。
2. 为了防泄露，把模型可见正文直接丢掉。
3. 用前端正则清洗代替后端输出边界。
4. 用 projection body 救正文。
5. 用 task projection 救 live tool lifecycle。
6. 让 terminal/done/error 承担 final answer。
7. 让 tool observation 冒充模型阶段判断。
8. 让 prompt 写开发说明而不是 agent 可执行职责。
9. 保留旧链路并说是兼容。
10. 先写测试绕过真实链路。

## 15. 最终目标形态

用户看到的是：

```text
模型正文：
  我先检查后端如何把模型正文和工具调用分流，再对照前端 reducer。

工具：
  读取 backend/harness/loop/single_agent_turn.py
  结果：同一响应含 tool_calls 时 visible content 被跳过。

模型阶段反馈：
  问题发生在模型响应解析层：工具被保留，正文没有进入 body segment。下一步修复解析和前端 body ledger。

工具：
  读取 frontend/src/lib/store/events.ts
  结果：final 会覆盖整个 message.content。

阶段总结：
  正文丢失有两个根因：后端工具轮不产出 body segment，前端也不能承载多段 body。接下来应先改 backend body segment contract，再改前端 reducer。

最终回答：
  已完成修复，并验证工具调用轮正文、工具观察、阶段总结和收口均能刷新后保留。
```

系统内部同时保留：

```text
PromptPacket refs
raw model response
tool_call_id
tool observation refs
phase_boundary refs
control state
event_offset
body_segment_id/body_sequence
```

但这些内部控制字段不进入用户可复制正文。
