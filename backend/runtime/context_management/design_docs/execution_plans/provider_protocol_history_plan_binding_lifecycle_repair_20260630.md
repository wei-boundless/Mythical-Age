# Provider Protocol History and Plan Binding Lifecycle Repair Plan

创建日期：2026-06-30

状态：待用户确认后实施。本文是 runtime/context/model packet 主链路修复计划，不是已实施记录。

## 1. 问题定义

当前故障表现是：用户要求先写计划书，assistant 已经在 UI 对话中输出计划书正文，用户随后说“可以执行 / 继续 / 开始执行”，但下一轮模型仍然反复写计划书。

系统层面的根因不是 UI 丢消息，也不是模型天然忘记，而是 provider-visible history 编译阶段丢掉普通正文消息：

```text
session api_transcript 有正文
-> compiler provider protocol projection 过滤普通 user / assistant(content)
-> provider-visible history 缺失计划书和批准消息
-> 下一轮 DeepSeek messages 看不到“已计划 + 已批准”
-> agent 重新进入计划阶段
```

正确终态必须同时满足两条链路：

1. 正文历史链路：计划书、批准消息、普通 assistant 正文必须作为 provider protocol conversation history 拼回模型请求。
2. 执行绑定链路：计划书如果成为执行依据，应有 active work / plan binding 生命周期，能绑定、推进、完成、取消、替换和解绑。

计划书不能只靠 memory 维持；memory 只能做摘要或检索辅助，不能替代 provider 对话正文，也不能替代 active execution state。

## 2. 证据来源

### 2.1 本地源码证据

| 位置 | 当前行为 | 问题 |
| --- | --- | --- |
| `backend/harness/runtime/compiler.py:_provider_protocol_message_specs()` | 从 `api_transcript` / `provider_protocol_history` 投影 provider protocol history | 数据源正确，后续过滤错误 |
| `backend/harness/runtime/compiler.py:_provider_protocol_hot_messages()` | 直接委托 `_provider_protocol_closed_tool_round_messages()` | 普通 `user` 和普通 `assistant(content)` 被丢弃 |
| `backend/harness/runtime/compiler.py:_provider_protocol_closed_tool_round_messages()` | 只保留闭合工具轮和带 `reasoning_content` 的 assistant | 计划书正文、批准正文不会进入 provider history |
| `backend/harness/runtime/compiler.py:provider_protocol_history spec` | metadata 说 append-only provider-visible history | spec 却写 `cache_scope=none/cache_role=never_cache/prefix_tier=none` |
| `backend/runtime/context_management/provider_visible_context_ledger.py:provider_visible_context_append_candidate_spec()` | followup 旁路生成 ledger candidate | 没有统一调用 sealability owner，可能把 current context 错封 |
| `backend/runtime/context_management/context_pipeline.py:apply_provider_visible_context_ledger_to_specs()` | 主 pipeline 会用 `context_segment_policy_is_provider_visible_sealable()` 判断 | 主路径有判断，但旁路不一致 |
| `backend/runtime/context_management/physical_context_assembler.py:assemble_physical_context_spine()` | 物理顺序为 static -> confirmed frame -> current append -> tail | 顺序设计正确，但输入 frame 已封错碎片 |
| `backend/harness/entrypoint/runtime_facade.py:_runtime_history_and_session_context_for_record()` | 过滤 public history 当前用户 | 未同步过滤 `api_transcript`，恢复完整 replay 后有重复当前用户风险 |
| `backend/runtime/model_gateway/lightweight_chat_model.py:_build_request_body()` | 直接发送 `messages` 到 `/chat/completions` | model gateway 不会补回上游漏掉的历史 |

### 2.2 真实会话证据

会话：`session-a493d97320c94f70`

`storage/sessions/session-a493d97320c94f70.json` 的 `api_transcript` 包含：

- assistant 计划书正文。
- user “可以执行”。
- user “继续”。
- user “开始执行”。

但 `storage/runtime_state/provider_visible_context_ledger/session-a493d97320c94f70.json` 主要封存：

- `current_turn_user_context`
- `single_agent_turn_tool_call`
- `tool_transcript_delta`

普通 assistant 计划正文没有成为正确的 provider protocol replay。

`storage/runtime_state/physical_prefix_frame_ledger/session-a493d97320c94f70.json` 的 latest confirmed frame 已经继承这些错误碎片。修复代码后还需要对该 session 做基于真实 `api_transcript` 的恢复，不能继续复用错误 frame。

### 2.3 外部 provider 约束

DeepSeek `/chat/completions` 是无状态接口，客户端每次必须传入当前请求所需的完整 conversation messages。工具调用协议要求按：

```text
assistant(tool_calls)
-> tool(tool_call_id)
-> next model call
```

拼接历史。参考：

- `https://api-docs.deepseek.com/guides/multi_round_chat`
- `https://api-docs.deepseek.com/guides/function_calling`
- `https://api-docs.deepseek.com/api/create-chat-completion`

因此 provider history 不是可选记忆层，而是每次请求的正式输入。

## 3. 权威边界

| 层 | 权威职责 | 禁止事项 |
| --- | --- | --- |
| `api_transcript` | 原始 provider 对话正文事实源 | 不做执行状态裁决 |
| `provider_protocol_history` | 将正文事实源投影成 provider messages replay candidate | 不过滤普通正文，不猜 active work |
| `provider_visible_context_ledger` | 记录 provider success 后可封存的 provider-visible candidate | 不绕开 sealability owner，不重排 tool protocol |
| `physical_prefix_frame_ledger` | provider 成功后确认下一轮可重放的物理 prefix 顺序 | 不从 current tail 猜历史，不保留失败请求的错误 binding |
| `physical_context_assembler` | 唯一物理拼接点：static -> confirmed frame -> current append -> dynamic tail | 不直接读取 session history 另起 replay |
| `active_work / plan_binding` | 当前执行控制平面，记录 plan_ref、批准状态、阶段和生命周期 | 不替代正文历史，不永久注入已关闭计划 |
| `model_gateway` | 发送已组装 messages | 不补救上游丢失历史 |

核心裁决：

```text
history owns what was said
plan binding owns what is currently being executed
physical frame owns what is safe to replay next turn
```

三者不能互相替代。

## 4. Provider Protocol History 目标设计

### 4.1 replay 输入

`api_transcript` 是当前 session 的精确 provider protocol timeline。编译时应读取并生成 `provider_protocol_history` specs。

### 4.2 过滤规则

允许进入 provider protocol history：

- 普通 `user` message，只要有 provider-visible content。
- 普通 `assistant(content)`，包括计划书正文、解释、确认、最终答复。
- 带 `reasoning_content` 的 assistant，保持 provider payload。
- 闭合工具轮：
  - `assistant(tool_calls)`
  - 紧随其后的全部匹配 `tool(tool_call_id)`。

禁止进入 provider protocol history：

- 孤立 `tool` message。
- 未闭合 assistant tool call。
- `tool_call_id` 缺失或重复导致无法闭合的工具轮。
- control protocol tool call，如 `respond`、`ask_user`、`block`、`request_task_run`、`active_work_control`、`resume_task_recovery` 等。

### 4.3 seal / replay 语义

`provider_protocol_history` 必须以 current append candidate 进入当前请求，provider success 后由 physical frame 确认成下一轮 `provider_visible_context_prefix`。

需要拆开两个概念：

| 概念 | 含义 | 示例 |
| --- | --- | --- |
| byte preservation | 当前 spec 的 `model_message` 必须逐字保留 provider payload | provider protocol message / physical frame replay |
| sealed frame replay | 该 message 已经来自 confirmed physical frame | `physical_prefix_frame_*_replay` |

不能把 `provider_protocol_replay=True` 同时当作 “byte-preserve” 和 “already sealed replay”。否则 `provider_protocol_history` 可能在成为 candidate 前就被 assembler 当旧 replay 忽略。

目标语义：

```text
provider_protocol_history candidate:
  section = context_append
  commit_policy = append_then_seal
  replay_policy = provider_protocol_append_candidate
  byte_preserve = true
  already_replayed_from_physical_frame = false

physical_prefix_frame_*_replay:
  section = context_memory_prefix
  commit_policy = replay_only_from_physical_prefix_frame
  replay_policy = physical_prefix_frame_replay
  byte_preserve = true
  already_replayed_from_physical_frame = true
```

## 5. Plan Binding 生命周期目标设计

计划书正文是 conversation history；计划作为执行依据时，需要额外的 active binding，但 binding 必须有关闭规则。

### 5.0 成熟 agent 形态：Work Item + Plan Source + Execution Contract + Active Lease

更成熟的实现不应该只叫 `plan_binding`。计划绑定只是其中一个子结构。目标应拆成六个对象，并复用项目已有 todo 游标，不再另造一套 todo：

| 对象 | 职责 | 是否进模型上下文 |
| --- | --- | --- |
| `WorkItem` | 用户当前要完成的工作单元，拥有目标、scope、状态 | 只注入 active work 摘要 |
| `PlanSourceSnapshot` | 已批准执行依据的不可变快照，可来自 inline assistant plan、`task_plan_context`、todo baseline 或 plan 文件 | 默认只注入 ref/hash，必要时按源读取全文 |
| `ExecutionContract` | 从已批准计划派生的执行契约，说明允许做什么、交付什么、何时停 | 注入当前契约摘要 |
| `ActiveLease` | 当前 turn/run 对某个 work item 的短期执行租约 | 只有 active lease 注入 |
| `TodoCursor` | 复用现有 `agent_todo` / `task_todo_context`，表示当前 active item、事项状态和恢复游标 | 注入现有 todo focus |
| `RecoveryCheckpoint` | 可恢复失败的精确恢复点，包含 run/turn/tool 状态 | 只在 recoverable 状态注入 |

核心升级点：

```text
plan binding 不是永久绑定
plan binding 被 active lease 临时持有
lease 只能由明确事件续租、关闭或替换
closed lease 永不进入当前模型上下文
```

这更接近成熟 coding agent 的工作方式：正文历史负责事实，execution contract 负责当前任务边界，active lease 负责“此刻正在执行”，已有 todo cursor 负责“执行到哪一项”。

本项目已有明确约束：`todo` 是任务执行工具契约和游标，不是 primary mode，也不是计划本身。binding 要引用 todo baseline/cursor，而不是替代 todo。

### 5.1 状态机

```text
draft
-> approval_pending
-> approved
-> bound_to_active_work
-> executing
-> completed
-> unbound
```

异常分支：

```text
approval_pending -> rejected -> unbound
approval_pending -> canceled -> unbound
executing -> recoverable_failed -> resume | cancel
executing -> suspended -> resume | cancel
executing -> superseded -> unbind old plan -> bind new plan
executing -> canceled -> unbound
completed -> archived_only
```

### 5.1.1 ActiveLease 状态机

`PlanBindingRecord.status` 描述计划绑定的业务状态；`ActiveLease.status` 描述当前执行占用状态。两者分开，避免“计划已批准”被误当成“永远执行中”。

```text
none
-> acquired
-> active
-> heartbeat_seen
-> released
```

异常分支：

```text
active -> stale -> recoverable_failed | released
active -> superseded -> released
active -> canceled -> released
active -> completed -> released
```

规则：

- 同一 session 默认只能有一个 active execution lease。
- 如果未来支持并行任务，也必须有显式 `work_item_id`，当前 turn 只能选择一个 focused lease。
- lease 不是靠时间自然永久有效，而是靠 runtime event 续租；没有后续 active event 的旧 lease 必须进入 stale/recovery 判断。
- terminal output commit 成功后必须 release lease。
- 用户明确取消、替换计划或切换目标时必须 release 旧 lease。

### 5.2 数据契约

建议使用结构化 work / plan source / lease 记录，而不是把计划全文塞进动态上下文：

```json
{
  "work_item_id": "work:<session_id>:<hash>",
  "session_id": "...",
  "root_user_message_id": "...",
  "goal": "写一个篮球小游戏",
  "status": "executing",
  "active_plan_binding_id": "planbind:...",
  "active_lease_id": "lease:...",
  "created_at": 0,
  "updated_at": 0,
  "closed_at": 0,
  "closed_reason": ""
}
```

```json
{
  "binding_id": "planbind:<session_id>:<turn_id>:<hash>",
  "session_id": "...",
  "turn_id": "...",
  "plan_source": {
    "source_kind": "inline_assistant_message|task_plan_context|todo_snapshot|artifact_ref",
    "source_ref": "...",
    "source_message_id": "...",
    "plan_ref": "",
    "todo_list_id": "",
    "todo_baseline_ref": "",
    "content_hash": "sha256:..."
  },
  "approval_message_id": "...",
  "approval_turn_id": "...",
  "status": "executing",
  "current_phase": "implementation",
  "active_work_ref": "...",
  "created_at": 0,
  "updated_at": 0,
  "closed_at": 0,
  "closed_reason": ""
}
```

```json
{
  "lease_id": "lease:<work_item_id>:<turn_id>:<run_id>",
  "work_item_id": "...",
  "binding_id": "...",
  "owner_turn_id": "...",
  "owner_run_id": "...",
  "status": "active",
  "last_event_id": "...",
  "last_heartbeat_at": 0,
  "release_event_id": "",
  "release_reason": ""
}
```

```json
{
  "todo_cursor_ref": "todo:<task_run_id>:<todo_list_id>",
  "work_item_id": "...",
  "binding_id": "...",
  "todo_list_id": "...",
  "active_item_id": "...",
  "active_item_ref": "...",
  "status_counts": {},
  "authority": "existing_agent_todo_or_task_todo_context"
}
```

所有这些记录应优先由 append-only lifecycle events 派生当前状态，而不是多个模块直接覆写同一个 mutable blob。

### 5.2.1 没有落成文档的 plan 怎么绑定

不要求先写 `plan.md`。binding 绑定的是 `PlanSourceSnapshot`，其 source 可以有四种：

| source_kind | 适用场景 | 稳定 identity | 读取方式 |
| --- | --- | --- | --- |
| `inline_assistant_message` | assistant 在聊天正文里输出计划书，但没有保存成文件 | `source_message_id + content_hash + provider_protocol_index` | 从 `api_transcript` / provider protocol history 读取原文 |
| `task_plan_context` | 已经进入任务资源的 plan contract / plan baseline | `plan_baseline_ref + plan_sha256` | 从 `task_plan_context` 投影读取 |
| `todo_snapshot` | 用户给的是 checklist，或 agent 已用 todo 初始化执行清单 | `todo_baseline_ref + todo_sha256` | 从 `task_todo_context` / `agent_todo` baseline 读取 |
| `artifact_ref` | 计划已保存成 `plan.md` 或其他 artifact | `plan_ref + content_hash` | 从 workspace/artifact store 读取 |

因此“没有落成文档的计划”可以这样绑定：

```json
{
  "binding_id": "planbind:session-a493:inline:sha256...",
  "plan_source": {
    "source_kind": "inline_assistant_message",
    "source_ref": "api_transcript:assistant:6",
    "source_message_id": "msg:...",
    "content_hash": "sha256:..."
  },
  "approval_message_id": "msg:approval",
  "status": "approved"
}
```

如果当前已经有 todo，则 binding 不绑定“计划文件”，而是绑定 todo baseline：

```json
{
  "binding_id": "planbind:session-a493:todo:sha256...",
  "plan_source": {
    "source_kind": "todo_snapshot",
    "todo_list_id": "todo:stable-id",
    "todo_baseline_ref": "task_todo_context.task_todo_baseline",
    "content_hash": "sha256:..."
  },
  "approval_message_id": "msg:approval",
  "status": "approved"
}
```

关键不变量：

- inline plan 不因为没有文件就丢失；它由 `api_transcript` 的 message id/hash 锁定。
- todo 不因为被绑定就变成 plan；todo 仍是执行清单和游标。
- 如果 todo 来自某份 plan，todo item 应尽量记录 `plan_step_ref`；没有 plan step 时也可以作为 checklist snapshot 执行。

### 5.3 上下文注入规则

允许注入当前轮：

- `approved`
- `bound_to_active_work`
- `executing`
- `recoverable_failed`
- `suspended`

禁止注入当前轮：

- `draft`
- `approval_pending` 但未批准
- `completed`
- `canceled`
- `rejected`
- `superseded`
- `unbound`
- `archived_only`

已关闭 binding 只能用于审计和 UI 展示，不能再影响下一轮模型输入。

### 5.3.1 注入内容的成熟裁剪

注入 active work 时不要把整份计划书重复塞进 prompt。成熟注入应是短 contract：

```text
你正在执行用户已批准的工作。
work_item_id: ...
plan_source_ref: api_transcript:assistant:6 | task_plan_context:... | task_todo_context:... | basketball-game/plan.md
approval_ref: ...
current_phase: implementation
active_todo_item: ...
next_step: ...
boundary: 按已批准计划实现，不重新写计划；如计划冲突或缺少关键条件，暂停并说明。
```

全文计划来源有四类：

- provider protocol history 中的 assistant 正文。
- `task_plan_context` 中的 plan baseline。
- `task_todo_context` / `agent_todo` 中的 todo baseline。
- `PlanSourceSnapshot.plan_ref` 指向的文件或 artifact。

active context 只注入执行锚点、当前阶段、active todo item、下一步和边界。这样可以减少 token 噪声，也防止旧计划全文长期占据当前轮尾部。

### 5.4 执行绑定与正文历史的关系

```text
api_transcript:
  保存计划书全文、用户批准正文、后续执行对话。

artifact store:
  可选。只有计划落成文件时保存计划文件，如 basketball-game/plan.md。

plan_binding:
  只保存 PlanSourceSnapshot、批准来源和生命周期，不保存完整正文作为记忆替代品。

todo:
  既有执行清单和当前游标，binding 只引用它，不替代它。

active_work:
  消费 plan_binding 的 active 状态，决定当前执行目标。
```

模型看到的上下文应表达为 agent 可执行契约，而不是开发说明：

```text
你正在执行用户已批准的计划。
计划来源：api_transcript assistant message / task_plan_context / task_todo_context / plan.md
批准来源：用户在本会话中明确要求开始执行。
你应继续实施计划，不要重新输出计划书。
如果发现计划过期、冲突或缺失关键条件，说明原因并请求用户确认。
```

### 5.5 版本、替换和撤销规则

计划 source snapshot 必须不可变；修改计划或 todo baseline 应创建新版本，而不是原地改旧快照。

```text
PlanSourceSnapshot v1 approved -> Binding A executing
user asks to change plan
-> Binding A status = superseded
-> ActiveLease A released
-> PlanSourceSnapshot v2 draft/proposed
-> user approves v2
-> Binding B active
```

撤销规则：

- 用户说“取消/别做了/先停下”：release active lease，binding -> canceled 或 suspended。
- 用户说“重新写计划/改计划”：旧 binding -> superseded，新计划重新进入 approval flow。
- agent 自己发现计划无法执行：binding -> recoverable_failed，lease -> stale/released，向用户说明阻塞点。
- agent 完成交付并通过 output commit：binding -> completed，lease -> released。

### 5.6 反复写计划的硬闸

如果存在 active execution lease，并且当前用户消息是“执行/继续/开始/按计划做”这类推进信号，runtime 给模型的 action contract 必须是执行契约，而不是 planning contract。

这不是用 regex 替模型决定任务，而是由显式状态裁决：

```text
active lease exists
approval_state = approved
binding status in active set
current user message is compatible continuation
-> inject execution contract
-> forbid re-plan unless model reports plan conflict / missing precondition
```

如果没有 active lease 或批准状态不明确，则不能强行执行，应该问用户确认或输出计划。

### 5.7 与 TurnMemory 的关系

`TurnMemory` 适合存 hot state / recovery state，但不能把计划正文混成 memory。

建议归属：

| 数据 | Owner |
| --- | --- |
| 对话正文 | `api_transcript` / provider protocol history |
| 计划文件全文 | artifact / workspace file |
| 当前工作状态 | `TurnMemoryStore` 或 dedicated active work store |
| 可恢复失败点 | `RecoveryCheckpoint` |
| 长期偏好/事实 | memory system |

这样 memory 不会因为“记住计划”而越权决定当前任务，active work 也不会因为上下文压缩丢失执行位置。

## 6. 固定执行流

### 6.1 普通对话进入执行

```text
user request
-> assistant writes plan as normal assistant(content)
-> api_transcript records assistant(content)
-> user approves
-> api_transcript records approval user message
-> WorkItem created or selected
-> PlanArtifact version is approved
-> ExecutionContract derived
-> ActiveLease acquired
-> next runtime packet includes:
   1. provider protocol history from api_transcript
   2. active execution contract summary
   3. progress cursor
   3. current user request
-> model executes instead of replanning
```

### 6.2 provider success 后封存

```text
current request provider messages
-> provider_visible_context_ledger confirms append candidates
-> physical_prefix_frame_ledger confirms exact provider message order
-> next turn assembler replays confirmed physical frame
```

### 6.3 完成后解绑

```text
execution reaches completed final commit
-> active_work marks completed
-> plan_binding status = completed
-> active lease released
-> existing todo cursor terminalized or closed according to todo completion_policy
-> closed_at / closed_reason written
-> binding removed from active context injection
-> history remains in api_transcript and audit store
```

### 6.4 恢复时的裁决

```text
runtime starts turn
-> load latest active WorkItem
-> load latest ActiveLease
-> if lease active and owner run still open: continue current execution
-> if lease stale and RecoveryCheckpoint exists: inject recovery contract
-> if binding completed/canceled/superseded: do not inject
-> if no active binding: rely on provider history and current user request
```

恢复不能从旧计划正文里猜当前任务。只能从未关闭的 work item / lease / recovery checkpoint 恢复。

## 7. 文件级实施计划

### Phase 1: 修 provider protocol history 正文保留

文件：

- `backend/harness/runtime/compiler.py`

改动：

- 重写 `_provider_protocol_hot_messages()`，按 provider protocol order 保留普通 user / assistant content / 闭合工具轮。
- 保留 `_CONTROL_PROTOCOL_TOOL_CALL_NAMES` 的过滤边界。
- 修正 diagnostics：记录 omitted orphan tool、unclosed tool round、control tool call。
- 给 `provider_protocol_history` spec 增加稳定 origin ref，避免 ledger item key 只靠 source_ref 波动。

完成条件：

- `api_transcript` 中普通 assistant 计划正文会进入 `provider_protocol_history`。
- `user` 的批准消息会进入 provider messages。
- 孤立 tool 和未闭合工具轮不会进入 provider messages。

### Phase 2: 拆分 byte-preserve 与 sealed replay

文件：

- `backend/runtime/context_management/provider_message_replay_contract.py`
- `backend/runtime/context_management/context_pipeline.py`
- `backend/runtime/context_management/context_segment_policy.py`
- `backend/runtime/context_management/physical_context_assembler.py`
- `backend/prompt_composition/materializer.py`
- `backend/prompt_composition/fragments.py`

改动：

- 引入或明确区分：
  - provider message byte preservation contract
  - physical frame sealed replay contract
- `provider_protocol_history` 可以 byte-preserve，但不能被视为 already replayed physical frame。
- `physical_context_assembler._current_append_specs()` 只排除真正 sealed frame replay，不排除 provider protocol append candidate。

完成条件：

- provider protocol candidate 能进入 current append。
- confirmed physical frame replay 仍按原规则进入 prefix。
- materializer 继续逐字保留 provider-shaped messages。

### Phase 3: 统一 sealability，关闭 current user 错封旁路

文件：

- `backend/runtime/context_management/provider_visible_context_ledger.py`
- `backend/runtime/context_management/context_segment_policy.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/single_agent_turn.py`

改动：

- `provider_visible_context_append_candidate_spec()` 和 `_provider_visible_context_append_candidate_allowed()` 必须调用统一 sealability 判断。
- `current_turn_user_context` 默认只作为当前尾部，不作为历史替代品封存。
- 真正的用户历史通过 `provider_protocol_history` 进入，而不是通过 `current_turn_user_context` 进入。
- followup commit candidate 不能绕过主 pipeline policy。

完成条件：

- ledger 不再出现 current turn user context 代替 provider protocol history 的现象。
- current user request 当前轮仍可见，但不会污染下一轮历史。

### Phase 4: 修 precommitted 当前用户去重

文件：

- `backend/harness/entrypoint/runtime_facade.py`

改动：

- `_runtime_history_and_session_context_for_record()` 对 `api_transcript` 也应用 `_history_without_current_user_request()`。
- 与 `astream()` 直接路径保持一致。

完成条件：

- 完整恢复 provider protocol history 后，当前用户消息不会重复出现在 history 和 current tail。

### Phase 5: 增加 work item / execution contract / active lease lifecycle

候选文件：

- `backend/runtime/turn_memory/turn_memory_models.py`
- `backend/runtime/turn_memory/turn_memory_store.py`
- `backend/runtime/turn_memory/turn_memory_projector.py`
- `backend/harness/runtime/request_facts.py`
- `backend/harness/runtime/packet_assembler.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/runtime/output_commit_authority.py`

改动：

- 增加 `WorkItemRecord`、`PlanSourceSnapshot`、`PlanBindingRecord`、`ExecutionContractRecord`、`ActiveLeaseRecord` 或等价结构。
- 复用现有 `agent_todo` / `task_todo_context` 作为执行 cursor，不新增第二套 todo/progress cursor。
- 在用户批准计划时创建或推进 binding。
- 批准后派生 execution contract，并 acquire active lease。
- active / recoverable lease 投影到当前模型上下文。
- completed / canceled / rejected / superseded 时解绑。
- output commit 成功后关闭 binding、release lease，并按既有 todo completion policy 关闭或归档 todo cursor。
- supersede 新计划时先关闭旧 binding，再绑定新计划。
- 生命周期状态优先由 append-only events 派生，避免多模块互相覆写。

完成条件：

- agent 能从 active binding 知道“当前要执行哪份已批准计划”。
- 没有 plan.md 的 inline plan 可以通过 `api_transcript` message id/hash 绑定。
- 已有 todo 可以通过 todo baseline/cursor ref 绑定，不被新结构覆盖。
- 已完成或被替换的计划不会继续注入上下文。
- 恢复只恢复未关闭 binding，不从旧正文猜 active task。
- 同一 session 默认最多一个 active lease；并行任务必须显式 work item 聚焦。

### Phase 6: 恢复受影响 session

文件/状态：

- `storage/sessions/session-a493d97320c94f70.json`
- `storage/runtime_state/provider_visible_context_ledger/session-a493d97320c94f70.json`
- `storage/runtime_state/physical_prefix_frame_ledger/session-a493d97320c94f70.json`

改动：

- 以现有 `api_transcript` 为唯一内容来源。
- 清理或截断错误封存的 provider-visible ledger / physical frame。
- 重新生成 provider-visible / physical context，不伪造任何计划或批准文本。
- 保留审计备份或 recovery event，说明旧 frame 因 provider protocol omission 被作废。

完成条件：

- 下一轮对该 session 的 provider payload 中包含：
  - 用户要求写篮球小游戏。
  - assistant 计划正文。
  - 用户批准执行消息。
  - 当前执行请求。
- 工具轮仍保持 assistant(tool_calls) -> tool 顺序。

## 8. 验证计划

项目规则禁止用新测试文件制造通过。本次验证使用代码审查、编译检查和真实运行链路。

### 8.1 静态验证

```bash
python -m py_compile backend/harness/runtime/compiler.py
python -m py_compile backend/runtime/context_management/provider_message_replay_contract.py
python -m py_compile backend/runtime/context_management/provider_visible_context_ledger.py
python -m py_compile backend/runtime/context_management/context_segment_policy.py
python -m py_compile backend/runtime/context_management/physical_context_assembler.py
python -m py_compile backend/harness/entrypoint/runtime_facade.py
```

如果 Phase 5 修改 TurnMemory / output commit，再补对应文件的 `py_compile`。

### 8.2 payload 审计

检查目标 session 的最终 provider messages：

```text
system/static prefix
confirmed physical frame replay
provider protocol history containing ordinary user/assistant messages
active plan binding summary only if still active
current user request tail
dynamic tail
```

必须满足：

- 普通 assistant 计划正文存在。
- user 批准消息存在。
- 当前 user 不重复。
- tool messages 不孤立。
- control protocol tool call 不进入 provider protocol history。

### 8.3 真实运行验证

涉及 runtime / SSE / 前后端联调时必须使用固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api base: http://127.0.0.1:8003/api
```

若端口被占用，先确认是否为本项目旧进程；非本项目进程不得擅自关闭。

## 9. 风险和禁止路径

禁止：

- 只在 prompt 里写“不要重复写计划书”。
- 用 memory summary 替代 provider protocol history。
- 把计划全文永久绑定到 current tail。
- 把 `approved` 当成永久 `executing`。
- 允许两个 active leases 同时争夺当前 turn。
- 新增第二套 todo/progress cursor 覆盖已有 `agent_todo`。
- 让 `current_turn_user_context` 替代普通 user message history。
- 保留旧错误 frame 继续作为 confirmed prefix。
- 通过降低断言、跳过测试或 mock provider payload 制造验证通过。

主要风险：

- provider protocol append candidate 与 physical frame replay 的 contract 混淆。
- 完整恢复 api transcript 后出现当前用户重复。
- plan binding 没有关闭，导致已完成计划继续影响下一轮。
- active lease 和 plan binding 不分层，导致已批准计划被误认为永远执行中。
- 计划或 todo baseline 原地修改，导致旧批准对应的 source snapshot 不可审计。
- 工具轮不闭合时错误回放，引发 provider protocol 400 或模型误解。

## 10. 最小验收不变量

```text
api_transcript 是正文事实源
provider_protocol_history 不丢普通 user / assistant(content)
tool protocol replay 必须闭合
current_turn_user_context 不是历史替代品
provider_visible_context_ledger 不绕开 sealability owner
physical_prefix_frame 是下一轮 replay 顺序权威
WorkItem 表达当前工作单元
PlanSourceSnapshot 不可变，修改必须新版本
ExecutionContract 表达已批准执行边界
ActiveLease 表达当前 turn/run 的执行占用
TodoCursor 复用已有 agent_todo/task_todo_context 表达执行位置
closed plan_binding / released lease 不进入当前模型上下文
completed/canceled/superseded plan 必须解绑并 release lease
```

## 11. 用户确认后的执行顺序

确认后按以下顺序实施，不跨阶段跳跃：

1. 先修 provider protocol history 保留普通正文。
2. 再拆 byte-preserve / sealed replay contract。
3. 再统一 ledger sealability，关闭 current user 错封旁路。
4. 再修 api_transcript 当前用户去重。
5. 再实现 work item / execution contract / active lease lifecycle。
6. 最后恢复 `session-a493d97320c94f70` 并真实验证 provider payload。

如果实施中发现某阶段假设错误，必须暂停并说明偏差，再请求确认。
