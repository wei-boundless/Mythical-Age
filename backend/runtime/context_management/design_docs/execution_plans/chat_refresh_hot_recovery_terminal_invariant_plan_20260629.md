# Chat Refresh Hot Recovery And Terminal Authority Plan

## 1. 结论先行

这次“最新对话卡住 / 刷新后恢复不稳定”的根因不是单一前端问题，也不是工具执行失败。真实断点显示：

```text
模型请求成功
-> read_file 工具执行成功
-> tool observation 写入成功
-> single-agent turn 准备工具 follow-up prompt
-> physical context plan 排序抛 TypeError
-> facade 产出 runtime_status_only error
-> public stream compiler 过滤该 error
-> chat stream 没收到 terminal
-> API 标记 missing_terminal_event / orphaned
-> 前端刷新后 active_only latest-run 查不到可恢复 run
```

所以问题不是“模型没有回答”本身，而是 agent runtime 的权力链路没有统一：

- `single_agent_turn.py` 仍在拼 follow-up 消息和工具 transcript。
- `provider_tool_protocol.py` 仍在给 provider 工具回合补排序语义。
- `physical_context_plan.py` 又按 lane / ledger / tool round 重新决定物理顺序。
- `runtime_facade.py` 把异常降级成 runtime-status-only error。
- `public_stream_compiler.py` 又把这类 error 从公开流中过滤掉。
- `api/chat.py` 最后只能兜成 `missing_terminal_event`。

成熟 agent runtime 不应该让多个层级同时决定同一条链路。目标是把权威收束成稳定单向链：

```text
ToolObservation facts
-> Context Segment facts
-> Physical Context Plan authority
-> Provider Payload assembly
-> Follow-up model decision
-> Output commit / terminal authority
-> Public projection / replay / restore
```

本计划分两层处理：

1. 先修真实断点：统一 physical context ordering 的排序契约，并保证 runtime 异常能形成公开 terminal，不再变成无终态 orphan。
2. 再修刷新恢复体验：前端不再只认 live attached run，而是消费后端拆分后的 live / replay / recoverable / continuation 契约。

## 2. 真实故障证据

### 2.1 卡住的 run

原始失败 run：

- `strun:ed812bf94299456ca8582f1da989d92e`
- session: `session-f0a4e448b0ed4070`
- status: `orphaned`
- diagnostics:
  - `runtime_interruption_code = missing_terminal_event`
  - `recoverable = true`
  - `agent_decision_terminal = false`
  - interrupted turn lifecycle closed and memory package ready

事件链证明工具执行本身完成：

```text
tool_batch_group_completed
-> turn_tool_observation_recorded
-> turn_runtime_interruption_recorded
-> agent_runtime_cell_completed
```

后续复现 run：

- `strun:5fd7c553e65e46ea80300ca2c0f80097`
- 同一 session / 同一 turn
- 同样在 `turn_tool_observation_recorded` 后进入 `missing_terminal_event`

### 2.2 后端栈迹

后端错误日志显示真实异常：

```text
HarnessRuntimeFacade failed while streaming request.
File backend/harness/loop/single_agent_turn.py, line 2741
  _single_agent_turn_followup_prompt_context(...)
File backend/harness/loop/single_agent_turn.py, line 7538
  annotate_specs_with_physical_context_plan(specs)
File backend/runtime/context_management/physical_context_plan.py, line 132
  segments = sorted(raw_segments, key=_physical_context_order_key)
TypeError: '<' not supported between instances of 'str' and 'int'
```

这说明断点发生在工具观察之后、follow-up 模型请求之前。不是模型 follow-up 返回非法结果，而是 follow-up prompt 还没组装成功。

### 2.3 具体代码问题

`backend/runtime/context_management/physical_context_plan.py` 中 `_physical_context_order_key()` 对 provider-visible prefix 和普通 segment 返回不同形状的 tuple：

```py
return (
    lane_rank,
    *tool_round_order,
    int(segment.index or 0),
    str(segment.source_ref or ""),
)
```

和：

```py
return (
    lane_rank,
    int(segment.index or 0),
    0,
    str(segment.source_ref or ""),
)
```

当两个 segment 的前几项相同或可继续比较时，Python 会把某一位的 `int` 和另一位的 `str` 放在同一排序位置比较，从而抛出 TypeError。

根因不是“排序缺少兜底”，而是 physical context order 的排序契约没有固定字段结构。不同来源的 metadata 进入同一 physical order authority 时，没有先规范成稳定、同类型、同长度的排序键。

### 2.4 终态投影问题

`runtime_facade.py` 捕获异常后产出的 error 带有：

```text
answer_persist_policy = runtime_status_only
answer_finalization_policy = no_agent_answer_runtime_unavailable
```

但 `backend/runtime/output_stream/public_stream_compiler.py` 会过滤这类 error：

```py
if _is_runtime_status_only_error_event(normalized, raw_data):
    return []
```

因此公开 chat stream 没有 `turn_completed`，`api/chat.py` 只能在流结束后记录 `missing_terminal_event`。这就是用户看到“工具卡结束后没下文”的直接原因。

## 3. 权力链路诊断

| 层 | 当前职责 | 权力问题 | 目标职责 |
| --- | --- | --- | --- |
| `single_agent_turn.py` | 执行工具、记录 observation、拼 follow-up context | 既执行，又参与 provider-visible 顺序拼装 | 只提交工具事实和当前 turn append facts |
| `provider_tool_protocol.py` | 标注 provider native tool round | 工具回合顺序可能被当成全局物理顺序 | 只描述同一 provider tool round 的原子关系 |
| `physical_context_plan.py` | 排列 physical context lane / cache spine | 排序键没有统一契约，混合来源互相冲突 | 唯一决定 provider payload 物理顺序 |
| `runtime_facade.py` | runtime 入口和异常捕获 | 把执行异常降级为 status-only，导致 terminal 断链 | 把 runtime 异常闭合成明确 failed terminal 或 recoverable interruption |
| `public_stream_compiler.py` | 公开投影 | 过滤了唯一错误终态 | 错误可不入正文，但必须投递 terminal |
| `api/chat.py` | chat run 状态和 replay | 只能兜底 missing terminal | 只在进程级硬中断等真正无 terminal 情况下记录 missing_terminal_event |
| 前端 restore | 刷新恢复 | 把 active live run 当成唯一恢复源 | 消费 live / replay / recoverable / continuation 的拆分契约 |

核心原则：

```text
排序权威不能分裂。
终态权威不能被投影层吞掉。
恢复权威不能由前端猜测。
```

## 4. 目标不变量

### 4.1 Context Assembly 不变量

```text
Context producers may emit facts and metadata.
Only physical_context_plan / assembler decides physical provider order.
Every physical order key must have one stable schema:
  lane_rank:int
  provider_round_start:int
  provider_round_member:int
  ledger_entry_index:int
  original_index:int
  source_ref:str
```

要求：

- 不允许不同分支返回不同 tuple 长度或不同类型位置。
- provider tool round 只能影响 provider-visible prefix 内部的工具原子回合顺序。
- 没有 ledger entry 的 segment 必须得到稳定的 numeric fallback，而不是落到字符串比较。
- old context / protected context 只能通过明确 metadata 进入 plan，不再绕过排序契约。

### 4.2 Terminal 不变量

```text
任何 single-agent turn stream 结束前必须满足：
  agent_turn_terminal 已投递
  or task handoff terminal 已投递
  or failed turn_completed 已投递
  or recoverable interruption 已投递并公开可见
```

要求：

- runtime-only error 可以不提交 assistant 正文，但不能被公开流完全吞掉。
- `missing_terminal_event` 只能表示生成器/进程级异常导致没有机会形成终态，不能成为普通 runtime exception 的主路径。
- 工具 observation 后的 follow-up prompt 构造失败必须形成 failed terminal，而不是 orphan。

### 4.3 Restore 不变量

```text
Frontend restore must not require live execution attachment to display a recoverable run.
```

要求：

- live reconnect、public replay、recoverable interruption、continuation 是四个不同语义。
- 前端只消费后端契约，不根据 active_only 结果推断“无可恢复内容”。
- recoverable run 展示为可恢复/中断，不伪装成 completed。

## 5. 实施方案

### Phase 1: 修复 physical context order authority

目标：消除 follow-up prompt 构造阶段的真实 TypeError。

涉及文件：

- `backend/runtime/context_management/physical_context_plan.py`

改动：

1. 将 `_physical_context_order_key()` 改为固定长度、固定类型的排序键。
2. provider-visible prefix 使用 `provider_tool_protocol_order()` 只填 numeric round 字段。
3. 非 provider-visible 或无 ledger entry 的 segment 使用明确 numeric fallback。
4. 保留 `source_ref` 作为最后稳定 tie-breaker，且只在所有 numeric 字段之后出现。

目标排序键：

```py
(
    lane_rank,
    provider_round_start,
    provider_round_order,
    ledger_entry_index,
    original_index,
    source_ref,
)
```

停止条件：

- `str/int` 不可能出现在同一排序位置。
- provider tool round 顺序仍能保持 assistant/tool message 的原子相邻关系。

### Phase 2: 修复 runtime error terminal projection

目标：runtime 异常不能被公开投影层吞成无终态。

涉及文件：

- `backend/runtime/output_stream/public_stream_compiler.py`
- 必要时：`backend/harness/entrypoint/runtime_facade.py`

改动：

1. 调整 `_is_runtime_status_only_error_event()` 的消费方式：
   - runtime-status-only error 不写 assistant 正文。
   - 但必须投递 `turn_completed(status=failed)`，或者投递等价 terminal public event。
2. `turn_completed_data()` 保留 `failure_code`、`terminal_reason`、`error_summary`，但继续走 public redaction。
3. 不把 runtime exception 内容作为 assistant final message 提交。

停止条件：

- follow-up prompt 构造异常时，chat run 结束为 failed terminal，而不是 orphan missing terminal。
- replay 中能看到 terminal event。

### Phase 3: 收紧 single-agent turn terminal guard

目标：工具 observation 后的所有后续路径都闭合。

涉及文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/entrypoint/runtime_facade.py`

改动：

1. 在工具 follow-up prompt 构造 / 模型调用周围保留结构化失败路径。
2. 如果 follow-up response 为 `None`，明确 closeout 为 model invocation failure。
3. 最外层 guard 只作为保险：自然结束且 `terminal_recorded=false` 时记录结构化 runtime interruption / failed terminal。

边界：

- 不用 guard 掩盖 Phase 1 的排序 bug。
- 不把系统异常伪装成 agent 正常回答。

### Phase 4: 后端 run restore contract 拆分

目标：API 明确区分 live / replay / recoverable / continuation。

涉及文件：

- `backend/api/chat.py`
- `frontend/src/lib/api/types.ts`
- `frontend/src/lib/api/chatStream.ts`

新增或调整字段：

```json
{
  "chat_run_execution_attached": true,
  "live_reconnectable": true,
  "replay_available": true,
  "recoverable_interruption": false,
  "continuation_available": false,
  "continuation_ref": {},
  "replay_url": "/api/chat/runs/.../events/replay",
  "live_ws_url": "/api/chat/sessions/.../live"
}
```

规则：

- `live_reconnectable = execution_attached && not terminal`
- `replay_available = event_log_id exists && latest_event_offset >= 0`
- `recoverable_interruption = diagnostics.recoverable && agent_decision_terminal is false`
- `continuation_available = task continuation record exists; ordinary interrupted turns are exposed through prior work memory on the next turn`
- 删除旧 live 兼容字段；live 重连接入只允许读取 `live_reconnectable`。

### Phase 5: 前端刷新恢复接入 replay / continuation

目标：刷新后不因为没有 live run 而显示空白。

涉及文件：

- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/api/chatStream.ts`
- `frontend/src/lib/store/events.ts`
- `frontend/src/components/chat/ToolTrace.tsx`

目标流程：

```text
restoreRememberedSessionOnStartup
-> hydrate committed history
-> get latest run with active_only=false
-> if live_reconnectable: attach websocket
-> else if replay_available: replay public events into same projection reducer
-> get latest continuation
-> if recoverable_interruption: show recoverable interrupted assistant turn shell
-> hydrate harness / active turn snapshot
```

前端规则：

- `applySelectedSessionShell()` 不应在恢复路径上制造不可见空白。
- no active live run 不等于 no recoverable run。
- replay、live、history 进入同一 ToolTrace projection，不保留第二套工具 UI。
- recoverable interrupted state 显示为“可恢复/可继续”，不伪装完成。

## 6. 调整后的实施顺序

本次修复按风险从低到高推进：

1. 先修 `physical_context_plan.py` 排序键契约。
2. 再修 `public_stream_compiler.py` 的 runtime error terminal 投影。
3. 再检查并补齐 `single_agent_turn.py` follow-up `response is None` / prompt 构造异常闭合。
4. 然后拆分后端 latest-run restore contract。
5. 最后接入前端 refresh replay / continuation 恢复。

原因：

- Phase 1/2 直接针对真实卡住根因。
- Phase 4/5 是体验恢复和状态展示，不应该先于 runtime terminal 不变量。
- 不先做前端大改，避免用 UI 层掩盖后端终态断链。

## 7. 验收标准

### 7.1 后端 runtime

- 工具执行成功后，follow-up prompt 构造不再因 context order 抛 `str/int` TypeError。
- 工具 observation 后要么继续模型 follow-up，要么投递 failed terminal。
- 普通 runtime exception 不再被记录成 `missing_terminal_event` 主路径。
- `missing_terminal_event` 只保留给进程硬杀、生成器取消等真正无法形成终态的情况。

### 7.2 Chat public stream

- runtime-status-only error 不提交 assistant 正文。
- 但 chat replay 中必须有 `turn_completed(status=failed)` 或等价 terminal。
- 前端不会停留在最后一个 `tool_item_completed` 后无下文。

### 7.3 刷新恢复

- completed run 走 committed history。
- live run 走 websocket reconnect。
- orphaned but recoverable run 走 replay + recoverable shell。
- 工具窗口、content_window、duration 在 replay 后仍能恢复。
- UI 不把 recoverable interrupted run 显示成 completed。

## 8. 验证方式

不新增测试文件，不写回归测试。验证只做静态审查、编译检查和固定端口真实运行。

### 静态检查

```bash
python -m py_compile backend/runtime/context_management/physical_context_plan.py backend/runtime/output_stream/public_stream_compiler.py backend/harness/loop/single_agent_turn.py backend/api/chat.py
```

### 固定端口检查

项目固定端口：

- frontend: `http://127.0.0.1:3000`
- backend: `http://127.0.0.1:8003`

启动前必须确认：

- `3000` 只有一个本项目前端进程监听。
- `8003` 只有一个本项目后端进程监听。
- frontend API base 指向 `http://127.0.0.1:8003/api`。

### API probe

对真实 session/run 检查：

```text
GET /api/chat/sessions/{session_id}/latest-run?active_only=true
GET /api/chat/sessions/{session_id}/latest-run?active_only=false
GET /api/chat/sessions/{session_id}/continuations/latest
GET /api/chat/runs/{stream_run_id}/events/replay?after_offset=-1
```

预期：

- live run 返回 `live_reconnectable=true`。
- recoverable orphaned run 返回 `replay_available=true`、`recoverable_interruption=true`。
- continuation 返回 interrupted turn 或明确无 continuation。
- replay 返回工具 public events 和 terminal public event。

### 手工场景

1. 发起会触发 read_file / 多工具读取的 agent turn。
2. 工具完成后确认 follow-up 模型请求真实发出。
3. 刷新页面，确认 UI 不空白。
4. 等待完成，确认有 terminal。
5. 人为制造 follow-up prompt 构造异常或模型异常，确认 UI 显示 failed/recoverable terminal，而不是停在工具卡。

## 9. 风险和边界

1. 不用前端恢复逻辑掩盖后端 terminal 断链。
2. 不把系统异常伪装成 agent 正常回答。
3. 不让多个模块继续共同决定 provider physical order。
4. 不新增第二套工具 UI。
5. 不用 `missing_terminal_event` 作为普通异常处理路径。
6. 不写测试文件，不用 mock 或硬编码结果制造通过。

## 10. 需要确认

该计划涉及：

- context physical ordering authority
- single-agent tool follow-up runtime
- public terminal projection
- chat run restore contract
- frontend refresh replay / continuation

按项目规则，这是跨 runtime/API/frontend 的结构性改动。实施前需要确认本计划；确认后应按阶段完整推进，不能只在前端或后端某个点补丁式处理。
