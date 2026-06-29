# TurnMemory Unified Authority Plan

状态：归一化修正版，已确认可执行；Phase 1/2 的账本主体与关键真实链路正在落地。

范围：当前 turn 记忆、流式输出、工具轮、steer、编辑最新消息后重新生成答案、recover、commit、物理上下文拼接、缓存审计、旧链路清理、验证方案。

## 1. 总结

之前的 `TurnHotJournal` 方案方向过宽，容易形成第二套状态权威。现在归一化为一套 `TurnMemory`：

```text
TurnMemory
  live layer: 当前 turn 热工作区
  checkpoint layer: 低频 durable checkpoint
  handoff layer: turn 收口后、confirmed physical frame 完全覆盖前的临时交接
  release layer: payload 释放后的 tombstone/hash
```

结论：

```text
TurnWorkingMemory 作为单纯进程内对象不够用。
TurnWorkingMemory 深化为统一 TurnMemory 后够用。
不需要 TurnWorkingMemory + HotJournal 两套权威。
```

后续不再设计独立 `TurnHotJournal` 主链路。若需要落盘模块，它只是 `TurnMemory` 的存储层：

```text
backend/runtime/turn_memory/turn_memory_models.py
backend/runtime/turn_memory/turn_memory_store.py
backend/runtime/turn_memory/turn_memory_projector.py
backend/runtime/turn_memory/turn_memory_recovery.py
backend/runtime/turn_memory/turn_memory_releaser.py
```

## 2. 设计原则

### 2.1 一个 turn 只有一个记忆权威

一个 turn 从用户输入开始，到 assistant final、commit、abort、recover 或 terminal 结束。这个 turn 中可能发生多次 provider request、工具调用、stream delta、steer、模型重入，但都属于同一个 `TurnMemory`。

禁止：

```text
同 turn 内 provider request 自己拼一份状态
stream recovery 自己保存一份事实
steer 再写一份 session message 当运行时事实
terminal diagnostics 反向成为恢复权威
```

### 2.2 热状态在 TurnMemory，不在交接账本

真正“热”的状态是当前 turn 正在变的东西：

```text
assistant draft
pending tool round
closed tool observations
pending action
active steer refs
current provider request refs
public event cursor
commit state
```

这些都归 `TurnMemory.live`。不能因为它们需要恢复，就拆出第二套 `HotJournal`。

### 2.3 Durable checkpoint 是 TurnMemory 的一层

如果需要重启后恢复，就给 `TurnMemory` 增加 checkpoint layer：

```text
TurnMemory.live -> TurnMemory.checkpoint
```

checkpoint 是同一份 turn 事实的 durable projection，不是另一个账本。它不能重新解释用户目标、工具事实或上下文顺序。

### 2.4 Handoff 也是 TurnMemory 的生命周期

turn 结束后，如果 assistant final / tool facts / commit state 已经被 confirmed physical frame 覆盖，就不需要 handoff。

只有在这些情况才需要 `TurnMemory.handoff`：

```text
assistant final 已生成但 commit 未完成
session commit 已完成但 PhysicalPrefixFrame 未确认
下一 turn 已开始但上一 turn 尚未完全晋升进 confirmed frame
edit-resend rewrite 后需要明确旧分支 cutoff refs
```

handoff 被 next turn 或 confirmed frame 消费后必须释放。

### 2.5 旧上下文一个字不动

`PhysicalPrefixFrameLedger` 是 confirmed old context 的唯一权威。`TurnMemory` 不能修改已 confirmed 的物理前缀，只能在 current turn append 或 handoff projection 中表达尚未晋升的临时事实。

### 2.6 rewrite 和 steer 不属于同一类

`steer` 是 active turn 控制输入：

```text
进入当前 TurnMemory.active_steer_refs
在下一次安全模型边界生效
不截断历史
```

`rewrite` 是编辑最新用户消息并重新生成答案：

```text
validate latest editable user message
truncate session branch from sourceIndex
reset prompt cache baseline
supersede old TurnMemory branch
create new ordinary turn + new TurnMemory
```

二者都不需要独立热账本。

## 3. 权威模型

### 3.1 TurnMemory 数据模型

```text
TurnMemory:
  identity:
    session_id
    turn_id
    turn_run_id
    branch_id
    parent_turn_id

  lifecycle:
    status: active | checkpointed | final_ready | commit_pending | frame_pending | handoff_ready | terminal | released
    phase: user_input | provider_request | tool_round | model_reentry | committing | recovering | terminal
    created_at
    updated_at

  input:
    current_user_message_ref
    attachments_ref
    editor_context_ref
    active_steer_refs
    edit_resend_ref
    branch_cutoff_message_index

  model:
    provider_request_refs
    provider_payload_manifest_refs
    physical_prefix_frame_id
    current_append_hash

  assistant:
    assistant_draft_ref
    assistant_draft_sha256
    assistant_final_ref
    assistant_final_sha256

  tools:
    tool_rounds
    pending_tool_summary
    closed_tool_round_refs

  action:
    pending_action_ref
    aborted_action_refs

  public:
    public_event_cursor
    public_projection_refs

  commit:
    commit_state
    session_commit_ref
    frame_promotion_ref
    pending_commit_summary

  recovery:
    recovery_state
    recovery_decision_ref
    uncertain_side_effect_refs

  release:
    release_state
    released_at
    tombstone_hash
```

### 3.2 TurnMemory 不拥有的东西

| 内容 | 权威 |
| --- | --- |
| 已 confirmed 旧上下文正文 | `PhysicalPrefixFrameLedger` |
| 静态工具 schema / 能力目录 / 输出协议 | static physical segments |
| 动态尾巴 | dynamic tail builder |
| UI replay | `RuntimeEventLog` |
| 已 commit 聊天历史 | session history |
| 长期知识/记忆 | memory subsystem |
| edit-resend 的 truncate 操作 | session branch controller / session manager |

## 4. 物理拼接算法

所有 provider request 只走一套算法：

```text
assemble_provider_context(session_id, turn_id):
  static_segments = load_static_physical_segments()
  confirmed_prefix = PhysicalPrefixFrameLedger.latest_confirmed_frame(session_id, branch_id)
  previous_handoff = TurnMemory.load_handoff_if_needed(session_id, branch_id)
  current_projection = TurnMemory.project_current_turn(session_id, turn_id)
  dynamic_tail = DynamicTailBuilder.build(request_facts)

  return concat(
    static_segments,
    confirmed_prefix,
    previous_handoff,
    current_projection,
    dynamic_tail,
  )
```

规则：

1. `confirmed_prefix` 一旦确认，字节不动。
2. 同 turn 内工具 follow-up、steer、assistant draft 都只从 current `TurnMemory` 投影。
3. `previous_handoff` 只在上一 turn 未完全晋升为 confirmed frame 时存在。
4. edit-resend rewrite 后，`confirmed_prefix` 必须停在 truncate cutoff 之前。
5. dynamic tail 永远不承载旧上下文或记忆事实。

## 5. 场景和算法分析

### 5.1 普通工具 follow-up

```text
request #1
-> model asks tool
-> TurnMemory.tool_rounds.pending
-> tool completes
-> TurnMemory.tool_rounds.closed
-> request #2 from TurnMemory projection
-> assistant final
-> commit / frame promotion
```

判断：

```text
同一 turn 内，不需要 handoff。
不需要 HotJournal。
如果工具输出很大，TurnMemory 只保存 ref/hash/summary，正文走工具观察存储或 public event ref。
```

### 5.2 steer

```text
receive steer
-> validate expected_turn_id == active_turn_id
-> append steer_ref to TurnMemory.active_steer_refs
-> if current provider request cannot be interrupted:
     wait until next model boundary
-> if current action conflicts:
     mark pending action aborted/interrupted
-> next provider request reads TurnMemory projection
```

判断：

```text
steer 不写 session message 作为运行时权威。
steer 不截断历史。
steer 不需要第二套热账本。
如果 steer 影响下一 turn，TurnMemory.handoff 只保留 accepted_steer_refs。
```

### 5.3 编辑最新用户消息并重新生成

现有前端真实链路：

```text
frontend/src/lib/store/runtime.ts
  resendEditedMessage(messageId, value)
  -> truncateSessionMessages(sessionId, truncateIndex)
  -> sendMessage(editedText)
```

后端真实链路：

```text
backend/api/sessions.py
  POST /sessions/{session_id}/messages/truncate
  -> session_manager.truncate_messages_from(session_id, message_index)
  -> reset_prompt_cache_baseline(reason=session_history_truncated)
```

目标算法：

```text
edit latest user message
-> validate latest editable user message
-> reject if active stream/session is running
-> truncate session messages and api_transcript from sourceIndex
-> reset prompt cache baseline
-> supersede old TurnMemory branch after cutoff
-> create new branch_id if needed
-> create new TurnMemory for edited user text
-> provider context starts from cutoff-safe confirmed prefix
```

判断：

```text
rewrite 不等于 steer。
rewrite 不在 active turn 中间执行。
旧 assistant answer / tool observation / provider manifest / TurnMemory branch 不得进入新 turn projection。
```

### 5.4 流式输出中断

```text
assistant delta
-> TurnMemory.live.assistant_draft
-> RuntimeEventLog public stream
```

后端还活着：

```text
recover from TurnMemory.live
```

后端重启：

```text
recover from TurnMemory.checkpoint
cross-check public_event_cursor / RuntimeEventLog refs
```

判断：

```text
如果要进程崩溃后逐 delta 零丢失，需要 TurnMemory draft WAL。
不能用第二套 HotJournal 假装 WAL。
```

### 5.5 final 已生成但 commit 失败

```text
assistant final
-> TurnMemory.assistant_final_ref/hash
-> commit session history
```

commit 失败：

```text
TurnMemory.status = commit_pending
recover 只重试 commit
不重跑模型
```

frame 晋升失败：

```text
TurnMemory.status = frame_pending
recover 只补 PhysicalPrefixFrame confirmation
```

判断：

```text
assistant final 和 session/frame commit 是两个状态。
不能因为 commit 失败让模型重新生成。
```

### 5.6 下一 turn 交接

```text
previous turn terminal
-> if PhysicalPrefixFrame confirmed:
     release TurnMemory payload
-> else:
     TurnMemory.status = handoff_ready
     next turn reads TurnMemory.handoff projection
-> once frame confirmed / next turn consumes:
     release payload and keep tombstone/hash
```

判断：

```text
handoff 是 TurnMemory 的生命周期层。
不是第二套热账本。
```

### 5.7 缓存命中低

定位算法：

```text
compare static segment hashes
compare confirmed physical_prefix_frame_id
compare optional TurnMemory.handoff hash
compare current TurnMemory.current_append_hash
compare dynamic_tail hash
```

分类：

```text
static changed -> 静态段漂移
physical_prefix_frame_id changed unexpectedly -> confirmed prefix 漂移
handoff hash changed -> 上一 turn 未晋升交接变化
current_append_hash changed -> 当前 turn live projection 变化
dynamic_tail only changed -> 预期动态尾变化
sidecar/tool schema inserted before confirmed frame -> 物理段排序 bug
```

## 6. 状态机

```text
active
  当前 turn 运行中，live layer 高频更新

checkpointed
  安全边界低频落盘，用于重启恢复

final_ready
  assistant final 已生成，等待 commit

commit_pending
  final 已有，但 session history commit 未完成

frame_pending
  session commit 已完成，但 PhysicalPrefixFrame 未确认

handoff_ready
  下一 turn 需要临时继承尚未完全晋升的事实

terminal
  turn 已完成且可进入 release 判断

released
  payload 已释放，只保留 tombstone/hash
```

转移：

```text
active -> checkpointed
active -> final_ready
final_ready -> commit_pending
final_ready -> frame_pending
frame_pending -> handoff_ready
handoff_ready -> released
terminal -> released
```

## 7. 实现落地

### Phase 1: 建立 TurnMemory 模型和 store

新增：

```text
backend/runtime/turn_memory/__init__.py
backend/runtime/turn_memory/turn_memory_models.py
backend/runtime/turn_memory/turn_memory_store.py
backend/runtime/turn_memory/turn_memory_projector.py
backend/runtime/turn_memory/turn_memory_recovery.py
backend/runtime/turn_memory/turn_memory_releaser.py
```

存储：

```text
storage/runtime_state/turn_memory/{safe_session_id}/turns/{safe_turn_id}.json
storage/runtime_state/turn_memory/{safe_session_id}/checkpoints.jsonl
storage/runtime_state/turn_memory/{safe_session_id}/tombstones.jsonl
```

完成条件：

```text
同一 turn_id 只有一条 active TurnMemory
checkpoint hash chain 可验证
released payload 不再进入 projection
```

### Phase 2: 接入 active turn loop

涉及：

```text
backend/harness/loop/single_agent_turn.py
backend/runtime/model_gateway/model_response.py
backend/harness/loop/active_turn_steering.py
backend/runtime/shared/queued_user_input_store.py
```

改造：

```text
assistant delta -> TurnMemory.live.assistant_draft
tool lifecycle -> TurnMemory.live.tool_rounds
steer -> TurnMemory.live.active_steer_refs
model reentry -> TurnMemory projection
```

### Phase 3: 接入 physical context assembler

涉及：

```text
backend/runtime/context_management/physical_context_assembler.py
backend/runtime/context_management/physical_prefix_frame_ledger.py
backend/harness/runtime/compiler.py
```

改造：

```text
confirmed prefix 仍从 PhysicalPrefixFrameLedger 来
current turn append 从 TurnMemory.project_current_turn 来
handoff projection 只在上一 turn 未晋升时插入
dynamic tail 保持 request-time
```

### Phase 4: edit-resend rewrite branch cleanup

涉及：

```text
frontend/src/lib/store/runtime.ts
backend/api/sessions.py
backend/sessions/__init__.py
backend/runtime/prompt_accounting/ledger.py
backend/runtime/turn_memory/turn_memory_store.py
```

改造：

```text
truncate success -> supersede old TurnMemory branch after cutoff
reset prompt cache baseline -> record reset ref
send edited text -> create new TurnMemory
```

### Phase 5: recovery

涉及：

```text
backend/harness/continuation/selector.py
backend/harness/continuation/record.py
backend/runtime/model_gateway/stream_recovery.py
backend/harness/runtime/active_turn.py
```

改造：

```text
current process alive -> TurnMemory.live
process restarted -> TurnMemory.checkpoint
commit_pending -> retry commit
frame_pending -> retry frame promotion
released -> tombstone only
```

### Phase 6: 清理旧链路

删除或降权：

```text
assistant_visible_stream_continuity as authority
visible_assistant_prefix as recovery authority
stream_recovery.raw_content as durable fact
steer session message as runtime authority
terminal diagnostics as recovery source
HotJournal as independent state authority
```

## 8. 验证 / 测试方案

说明：这里的“测试”优先是可执行验证场景和必要的既有链路检查，不新增保护旧结构的弱回归测试文件。

### 8.1 静态检查

```text
rg "TurnHotJournal|turn_hot_journal" backend -g "!**/design_docs/**"
rg "assistant_visible_stream_continuity" backend -g "!**/design_docs/**"
rg "visible_assistant_prefix" backend -g "!**/design_docs/**"
rg "active_turn_steer" backend -g "!**/design_docs/**"
python -m py_compile touched_backend_files
```

### 8.2 真实运行验证

固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api base: http://127.0.0.1:8003/api
```

场景：

| 场景 | 合格标准 |
| --- | --- |
| 普通三轮对话 | confirmed old context 稳定，TurnMemory release 正常 |
| 工具 follow-up | 同 turn 内工具观察只从 TurnMemory 投影，不走第二账本 |
| steer | steer 进入 TurnMemory.active_steer_refs，下一次模型边界可见 |
| 编辑最新消息重发 | session truncate 后新 TurnMemory 不继承旧 answer/tool refs |
| 流式断线 | 后端活着时从 TurnMemory.live 继续 |
| 后端重启 | 从 TurnMemory.checkpoint 恢复，不从 UI 字符串猜 |
| final commit 失败 | 只 retry commit，不重跑模型 |
| frame 晋升失败 | 只补 PhysicalPrefixFrame |
| 缓存命中低 | 能区分 static / confirmed prefix / handoff / current append / dynamic tail |

### 8.3 审计输出

每轮应能输出：

```text
turn_id
turn_run_id
branch_id
turn_memory_status
turn_memory_checkpoint_hash
physical_prefix_frame_id
current_append_hash
assistant_draft_sha256
assistant_final_sha256
active_steer_refs
edit_resend_ref
commit_state
frame_promotion_ref
release_state
public_event_cursor
```

### 8.4 可执行验收用例

本项目当前规则不新增弱回归测试文件，也不通过 mock 或硬编码制造通过。这里的“测试”指真实链路验收、静态结构检查、账本记录检查和必要的编译检查。

| 用例 | 输入 / 操作 | 必须观察到的结构结果 |
| --- | --- | --- |
| 三轮普通对话 | 连续发送 3 轮普通消息 | 第 2/3 轮 confirmed prefix frame id 稳定递进，旧上下文不被 current append 重写 |
| 工具 follow-up | 让 agent 调用工具并继续回答 | 同一 turn 的 provider_request_refs 增长，tool_rounds 记录 observation refs，不把工具正文塞进动态尾 |
| sidecar/tool schema | 对比两次同模型请求 segment map | 工具 schema / 能力目录在 static physical segment，不出现在 current_context_append |
| active steer | 运行中追加用户 steer | queued steer ref 进入 TurnMemory.active_steer_refs，模型下一边界可见，不改 tool authorization |
| rewrite 最新用户消息 | 编辑最新 user 后重发 | truncate cutoff 之后旧 TurnMemory 标记 superseded，新 turn 不继承旧 answer/tool refs |
| stream 中断但进程未死 | 断开前端 SSE 后重连 | RuntimeEventLog 负责 UI replay，TurnMemory 保留 draft/ref/checkpoint |
| provider 成功但 frame 拒绝 | 制造 physical frame rejected 日志 | TurnMemory 能显示 provider succeeded 但 physical_prefix_frame_id 未晋升，缓存审计能定位 frame 断点 |
| final 已生成但 commit 失败 | 让 commit gate 或 committer 失败 | TurnMemory.status=commit_pending，recover 只重试 commit，不重跑模型 |
| commit 成功 | 普通成功回答 | TurnMemory 记录 assistant_final_sha256、session_commit_ref、commit_state=committed |
| 后端重启恢复 | 运行中重启后端 | 从 TurnMemory checkpoint 判断恢复动作，而不是从 UI 文本猜目标 |

### 8.5 本轮实施后的检查命令

```text
python -m py_compile backend/runtime/turn_memory/__init__.py backend/runtime/turn_memory/turn_memory_models.py backend/runtime/turn_memory/turn_memory_store.py backend/runtime/turn_memory/turn_memory_projector.py backend/runtime/turn_memory/turn_memory_recovery.py backend/runtime/turn_memory/turn_memory_releaser.py backend/harness/runtime/single_agent_host.py backend/harness/entrypoint/runtime_facade.py backend/runtime/model_gateway/model_runtime.py backend/api/sessions.py backend/harness/loop/active_turn_steering.py backend/harness/loop/single_agent_turn.py
rg "TurnHotJournal|turn_hot_journal" backend -g "!**/design_docs/**" -g "!**/__pycache__/**"
rg "assistant_visible_stream_continuity" backend/harness/loop/single_agent_turn.py
```

预期：

```text
py_compile 无输出。
TurnHotJournal 无运行代码引用。
assistant_visible_stream_continuity 仍存在，但只作为 Phase 6 待替换旧恢复链，不再作为新增权威扩展。
```

## 9. 权威链路矩阵

| 线 | 生产者 | 权威 | 传输 / 存储 | 消费者 | 禁止路线 |
| --- | --- | --- | --- | --- | --- |
| user turn start | `single_agent_turn._start_turn_runtime` | runtime turn lifecycle | `RuntimeEventLog` + `TurnMemory.create_or_get_turn` | provider request / monitor | 不能由 provider request 重新建语义目标 |
| provider request | `ModelRuntime._begin/_finish_prompt_accounting` | model gateway accounting | prompt ledger + `TurnMemory.provider_request_refs` | cache audit / recovery | 不能由工具 follow-up 分支各自私记 |
| physical prefix frame | `physical_prefix_frame_ledger` | `PhysicalPrefixFrameLedger` | `storage/runtime_state/physical_prefix_frame_ledger` | physical assembler | TurnMemory 不能改 confirmed frame 正文 |
| current turn projection | `TurnMemory` | `TurnMemoryStore` | `storage/runtime_state/turn_memory` | current append / recovery | dynamic tail 不能承载旧上下文 |
| tool observation | tool runtime / single turn loop | tool lifecycle + TurnMemory ref projection | event log + `TurnMemory.tool_rounds` | follow-up provider request | 工具正文不能变成另一个“热账本” |
| steer | queued input store claim | active turn boundary | queued store + `TurnMemory.active_steer_refs` | next model boundary | steer 不能截断历史或替代 rewrite |
| rewrite | session truncate controller | session branch cutoff | session history + prompt baseline reset + TurnMemory supersede | new ordinary turn | rewrite 不能进入 active-turn steer |
| assistant final | output boundary before commit | output commit authority + TurnMemory final ref | `TurnMemory.assistant_final_*` | commit/recover | commit 失败不能重跑模型 |
| session commit | `OutputCommitAuthority` | commit gate | session history + TurnMemory commit state | UI history / recovery | terminal text 不能绕过 commit gate |
| UI replay | `RuntimeEventLog` | public event replay | event log / stream replay | frontend projection | UI replay 不能成为 runtime memory |

## 10. 实施进度

### 已落地

```text
TurnMemory 模型 / store / projector / recovery / releaser
SingleAgentRuntimeHost 持有 TurnMemoryStore
ModelRuntime 接入 TurnMemoryStore，provider request pending/succeeded/failed 进入 TurnMemory
provider 成功后的 physical_prefix_frame_confirmation 写入 TurnMemory frame 字段
single_agent_turn 启动时创建 TurnMemory
single_agent_turn 编译 packet 后写 current_user_message_ref/current_append_hash
tool round close 后写 compact tool_rounds/observation refs
assistant final 生成后写 assistant_final_ref/hash
OutputCommitAuthority 返回后写 commit_state/session_commit_ref
agent_turn_terminal 后写 terminal checkpoint
active steer claim 后写 active_steer_refs
edit-resend truncate 后写 cutoff，并 supersede cutoff 后已存在旧 TurnMemory
```

### 仍需后续按计划继续

```text
把 physical_context_assembler 的 current_projection 显式切到 TurnMemory.project_current_turn
把 handoff projection 接入 assembler，并在 confirmed frame 消费后 release
把 partial visible stream recovery 从 raw_content/visible_prefix 迁移到 TurnMemory draft/checkpoint
把 health system/cache ledger 的读取口径切到 TurnMemory + PhysicalPrefixFrameLedger
清理 assistant_visible_stream_continuity/visible_assistant_prefix 作为恢复权威的旧链路
清理 steer session message 的 runtime authority，只保留 UI/历史展示意义
```

## 11. 旧链路清理准则

旧链路删除必须满足三个条件：

```text
1. 新权威已经在真实链路生产同等或更强的结构事实。
2. 下游消费者已经切到新权威字段，不再从旧字段推断。
3. 删除后失败会暴露明确缺线，而不是静默改走 fallback。
```

本计划禁止以下清理方式：

```text
删掉旧字段但不接新消费者。
把旧字段改名成新字段但语义不变。
保留旧恢复链作为隐式 fallback。
让 terminal diagnostics、UI replay、stream raw text 继续承担 runtime recovery。
```

## 12. 最终原则

```text
一个 turn，只有一个 TurnMemory。
一个旧上下文，只有一个 PhysicalPrefixFrameLedger。
一个 UI replay，只有一个 RuntimeEventLog。
一个编辑重发，只有一个 session branch cutoff。
```

`TurnMemory` 可以很深，但不能分裂。  
我们要深化一套，不维护两套。
