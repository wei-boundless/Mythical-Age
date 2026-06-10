# Codex Lossless Output Stream Replacement Plan - 2026-06-11

## 1. 计划状态

状态：待用户确认，未实施。

本计划用于替换当前主会话 public projection 输出链路。目标不是修补某个前端组件，而是把 Codex 类成熟 agent 的输出规则迁移到本项目：

```text
assistant 正文 delta
-> assistant 正文完成 item
-> tool item started/completed
-> turn completed
```

这几类事件必须属于同一条可追踪、可重放、不可被 UI 投影层二次解释的输出协议。投影层只负责呈现任务、工具、控制和状态，不再拥有正文或最终总结的生成权。

## 2. 直接结论

当前问题不是 CSS、Markdown 渲染或单个 reducer 的问题，而是输出权威链断裂：

- assistant 正文走 `assistant_text_delta/final` typed stream。
- 工具走 `public_projection_envelope.items`。
- 最终总结又可能从 `assistant_text_final`、`done.content`、`answer_candidate`、projection body、task projection final summary 多路进入。
- 前端被迫用 sequence、semantic key、正文去重、timeline body 拼接、done suppression 等补丁规则猜测哪个才是权威输出。

Codex 的关键规则是：正文 delta、完成 item、turn completed 是 lossless tier；工具也有明确 item lifecycle。stdout/progress 可以 best-effort，但 transcript 和 completion 不能丢、不能被 presentation projection 重写。

本项目应迁移这个规则，而不是继续扩展 projection fallback。

## 3. Source Report

### 3.1 Codex 参考点

本计划参考本机项目目录外的 Codex 源码：

- `D:\AI应用\openai-codex\codex-rs\app-server-client\src\lib.rs:151-185`
  - `AgentMessageDelta`、`ItemCompleted`、`TurnCompleted` 被明确归入必须穿越 backpressure 的 lossless tier。
  - 注释说明：丢正文 delta 会破坏可见 Markdown，丢 completed 会让 UI 永远等不到收口。
- `D:\AI应用\openai-codex\codex-rs\app-server-client\src\lib.rs:1347-1431`
  - 测试验证在队列满、stdout 进度可被跳过时，`AgentMessageDelta`、`ItemCompleted`、`TurnCompleted` 仍必须送达。
- `D:\AI应用\openai-codex\codex-rs\app-server-protocol\schema\typescript\v2\AgentMessageDeltaNotification.ts:5`
  - 正文 delta 结构只关心 `threadId`、`turnId`、`itemId`、`delta`。
- `D:\AI应用\openai-codex\codex-rs\app-server-protocol\schema\typescript\v2\ItemStartedNotification.ts:6`
  - item started 是一等事件，携带 `ThreadItem`。
- `D:\AI应用\openai-codex\codex-rs\app-server-protocol\schema\typescript\v2\ItemCompletedNotification.ts:6`
  - item completed 是一等事件，携带最终 `ThreadItem`。
- `D:\AI应用\openai-codex\codex-rs\app-server-protocol\schema\typescript\v2\TurnCompletedNotification.ts:6`
  - turn completed 是一等终端事件。
- `D:\AI应用\openai-codex\codex-rs\app-server-protocol\src\protocol\item_builders.rs:1-11`
  - live tool items 主要来自 first-class `ItemStarted` / `ItemCompleted`，legacy builders 只服务历史和兼容路径。

Codex 可迁移的不是具体 Rust 类型，而是以下不变量：

1. Transcript lossless：正文 delta 和最终正文不能作为普通进度事件被丢弃。
2. Completed item authoritative：最终正文来自完成 item，而不是 terminal fallback。
3. Tool lifecycle first-class：工具开始、进行、完成都绑定同一个 item id。
4. Turn terminal explicit：turn completed 是终端信号，不承担正文兜底。
5. Presentation projection passive：展示层不重新决定正文、工具身份或终端语义。

### 3.2 本项目当前链路

当前本项目已经有 typed assistant stream 的基础：

- `backend/runtime/model_gateway/assistant_stream_frame.py`
  - 定义 `assistant_text_delta`、`assistant_text_final`、`assistant_stream_repair`。
  - frame 包含 `sequence`、UTF-8 offset、accumulated hash、content hash。
- `backend/runtime/model_gateway/assistant_stream_normalizer.py`
  - 负责 coalesce delta、sequence 递增、安全门过滤内部 JSON/tool protocol 泄漏。
- `backend/harness/loop/single_agent_turn.py`
  - 在模型流式输出时发出 `assistant_text_delta`，最终发出 `assistant_text_final`，再发 `done`。

但 public projection 链路把这些优势打散了：

- `backend/harness/runtime/projection/projector.py`
  - `assistant_text_delta/final/repair` 被列入 typed stream event，但 `projection_items_for_event()` 对它们返回空 items。
  - 当前脏改又把 `answer_candidate` 和 `done.content` 投成 `model_body_item/final_answer`，会重新制造正文多权威。
- `backend/api/chat.py`
  - `_run_chat_to_event_log()` 对所有 public event 附加 `public_projection_envelope`，typed 正文事件也会带空 envelope。
  - `_project_public_stream_event()` allowlist 同时允许 typed stream、done、answer_candidate、assistant_text 等多种正文入口。
- `backend/runtime/shared/event_log.py`
  - live subscription queue 默认 500，满了以后 `_put_event_drop_oldest()` 丢最旧事件。
  - 持久 log 能 replay，但 live SSE 没有把 gap recovery 作为 lossless tier 的协议保证。
- `frontend/src/lib/store/events.ts`
  - reducer 先应用 `public_projection_envelope`，再处理 `assistant_text_delta/final/repair`。
  - delta sequence 必须严格连续；一旦缺帧，就只标记 repair pending，不继续追加正文。
- `frontend/src/lib/projection/reducer.ts`
  - projection envelope 更新 activity、runtime attachments 和 timeline；它对 typed 正文没有真正 body item。
- `frontend/src/components/chat/ChatMessage.tsx`
  - 最终渲染把 `message.content` 与 strict assistant body timeline items 合并，再做去重。
  - 这说明正文存在两个渲染来源：typed message content 和 projection timeline body。
- `frontend/src/lib/projection/timeline.ts`
  - 工具 item 依赖 `item_id` 和 semantic key 合并。如果 start 和 observation 的 item_id 不一致，只能靠语义猜测合并。

## 4. 当前失败模式

### 4.1 正文不流畅

当前正文实时性依赖 `assistant_text_delta`，但：

- typed 正文事件被附加空 projection envelope，前端先处理 projection 再处理正文。
- live queue 可以丢事件，前端 sequence 一旦发现 gap 就停止追加。
- repair/final 能最终修正，但用户看到的是中途卡顿。
- 如果 final 被 projection body 或 done body 竞争，前端又进入去重和覆盖逻辑。

正确设计应是：正文 delta 属于 lossless transcript tier，后端负责补 gap，前端不靠猜。

### 4.2 工具窗口不流畅

当前工具开始通常来自 `model_action_admission`，工具结果来自 `turn_tool_observation_recorded` 或 `task_tool_observation_recorded`。但是：

- projection start item 现在可能用 `_item_id("tool", data)`。
- observation item 可能用 `_item_id("toolobs", data)`。
- 二者没有强制同一个 `tool_call_id` 做 item id。
- 前端只能靠 semantic key 比如工具名、target、title 合并。

正确设计应是：工具 item started/completed 都以 `tool_call_id` 为 item id，不靠文本合并。

### 4.3 最终总结不稳定

当前最终总结可能来自：

- `assistant_text_final.content`
- `done.content`
- `answer_candidate.content`
- `assistant_text` projection body
- `public_projection_envelope.items` 中的 `final_summary/final_answer/model_body_final`
- task projection 的 final answer / summary

这导致最终可见输出可能重复、覆盖、顺序反转或被隐藏。

正确设计应是：最终 assistant 正文只来自 `assistant_text_final`，turn terminal 只标记完成。

## 5. 目标输出协议

### 5.1 Public stream event families

实施后 public stream 只保留以下输出族：

```text
Lossless transcript events:
  assistant_text_delta
  assistant_text_final

Lossless item lifecycle events:
  tool_item_started
  tool_item_completed

Lossless turn terminal event:
  turn_completed

Best-effort presentation events:
  task_projection_updated
  status_updated
  control_state_updated       // only non-terminal routine control/status updates
```

内部 runtime 可以继续产生 `done` / `error` / `stopped`，但 chat public stream 不再把这些事件的 `content` 当作用户正文。public stream 的终端 sentinel 统一使用 `turn_completed`，通过 `status` 区分 completed / failed / stopped。终端错误或停止不是 best-effort；它们必须进入 lossless terminal。

### 5.2 Event contract

#### assistant_text_delta

```ts
type AssistantTextDeltaEvent = {
  type: "assistant_text_delta";
  stream_ref: string;
  message_ref: string;
  turn_run_id: string;
  task_run_id?: string;
  sequence: number;
  content: string;
  content_utf8_start: number;
  content_utf8_end: number;
  content_utf8_bytes: number;
  accumulated_utf8_bytes: number;
  accumulated_sha256: string;
  answer_channel: "conversation";
  answer_source: "model";
};
```

规则：

- sequence 从 1 开始严格递增。
- public SSE 发送前必须已写入 event log。
- 前端发现 event_offset gap 时，必须由后端 replay 补齐，而不是直接卡住。
- projection envelope 不附加到该事件。

#### assistant_text_final

```ts
type AssistantTextFinalEvent = {
  type: "assistant_text_final";
  stream_ref: string;
  message_ref: string;
  turn_run_id: string;
  task_run_id?: string;
  sequence: number;
  content: string;
  content_utf8_bytes: number;
  content_sha256: string;
  answer_channel: "conversation";
  answer_source: "model";
  answer_canonical_state: "stable_answer" | "final";
  answer_persist_policy: "persist_canonical";
};
```

规则：

- 这是 assistant 最终正文的唯一权威。
- 它覆盖此前 delta 累计结果。
- 它不需要 projection body item。
- `done`、`turn_completed`、task projection 不允许覆盖它。

#### tool_item_started

```ts
type ToolItemStartedEvent = {
  type: "tool_item_started";
  item_id: string;        // tool_call_id
  tool_call_id: string;
  turn_run_id: string;
  task_run_id?: string;
  tool_name: string;
  title: string;
  target?: string;
  arguments_preview?: string;
  state: "running";
};
```

规则：

- 只在 action permit/runtime 接管后发出，不能只因为模型写了 JSON 就显示。
- `item_id` 必须等于稳定 `tool_call_id`。
- 不产生 assistant body。

#### tool_item_completed

```ts
type ToolItemCompletedEvent = {
  type: "tool_item_completed";
  item_id: string;        // same tool_call_id
  tool_call_id: string;
  turn_run_id: string;
  task_run_id?: string;
  tool_name: string;
  state: "done" | "error";
  observation?: string;
  error?: string;
  duration_ms?: number;
};
```

规则：

- 必须更新同一个 `tool_item_started.item_id`。
- 不允许用 `toolobs:*` 生成第二个并列工具 item。
- raw file listing、布尔值、内部 traceback 不能直接进入 observation；仍走已有 tool result projection/summarization 规则。

#### turn_completed

```ts
type TurnCompletedEvent = {
  type: "turn_completed";
  turn_run_id: string;
  task_run_id?: string;
  status: "completed" | "failed" | "stopped";
  final_message_ref?: string;
  terminal_reason?: string;
  error_summary?: string;
  stopped_reason?: string;
};
```

规则：

- 只表示本轮完成。
- 不携带正文兜底。
- 可携带状态和错误摘要，但错误摘要只能用于 terminal receipt/control/status，不进入 assistant body。
- `error` 和 `stopped` 必须被转译为 `turn_completed.status="failed" | "stopped"`，不能作为可丢 presentation event。

## 6. 权威边界

| 层 | 当前问题 | 目标权威 | 实施动作 |
| --- | --- | --- | --- |
| Model Gateway | 已有 delta/final，但 final 不是唯一最终权威 | 只产生 assistant transcript | 保留 normalizer，收紧 final event 元数据 |
| Single Agent Loop | 同时发 typed final 和 done content | 决定模型正文与工具动作顺序 | final 后只发 terminal state，不发 body fallback |
| Tool Runtime | 工具 id 存在但投影未强制使用 | 工具 lifecycle 权威 | tool started/completed 必须用 tool_call_id |
| Chat API | 给所有 public event 附加 projection envelope | public event routing 和 replay 权威 | typed transcript 不附加 envelope；lossless events gap replay |
| Public Projector | 把 done/answer_candidate 投成正文，且 live tool 也靠 projection 合并 | 只做非正文、非 live-tool 的 presentation projection | 删除正文 projection；live tool 交给 `tool_item_*`；projection 只投状态、控制、任务附件 |
| Frontend Store | 先 projection 再 typed 正文，且正文/timeline 双源 | transcript reducer 权威 | 正文只来自 typed events |
| Chat Renderer | 合并 message.content 与 timeline body | 只展示 reducer 产物 | 删除 timeline body 与正文拼接 |

## 7. 分阶段实施计划

### Phase 0 - Baseline Freeze

目标：确认当前脏改和测试基线，避免误覆盖用户改动。

动作：

1. 记录当前 dirty files。
2. 阅读相关 diff，标记与目标协议冲突的改动。
3. 不回滚用户改动；实施时以目标协议覆盖冲突逻辑。

冲突点已确认：

- `backend/harness/runtime/projection/projector.py`
  - 当前脏改把 `answer_candidate` 和 `done.content` 投成 `model_body_item`，与目标协议冲突。
- `frontend/src/components/chat/ChatMessage.tsx`
  - 当前脏改扩展了 timeline body 与 message content 的合并策略，目标协议会删除这类合并。
- `frontend/src/lib/projection/reducer.ts`
  - 当前脏改增加 active turn fallback，目标协议需要更严格 anchor-first，不靠最新 assistant 猜。

完成标准：

- 明确哪些 dirty changes 会被目标架构替换。
- 不做任何测试绕过或断言降低。

### Phase 1 - Backend Public Output Contract

目标：建立 Codex-style public stream contract。

涉及文件：

- `backend/runtime/model_gateway/assistant_stream_frame.py`
- `backend/runtime/model_gateway/assistant_stream_normalizer.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/api/chat.py`
- 新增：`backend/runtime/output_stream/public_contract.py` 或等价模块

动作：

1. 定义 public stream 事件分类：
   - lossless transcript
   - lossless item lifecycle
   - lossless turn terminal
   - best-effort presentation
2. `assistant_text_delta/final` 保持现有事件名，但纳入 lossless tier。
3. 增加 `turn_completed` public event，由 internal `done` 转译而来。
4. chat public stream 不再把 `done.content` 作为正文输出。
5. typed transcript event 不再附带 `public_projection_envelope`。
6. `_project_public_stream_event()` 对 `answer_candidate`、`assistant_text`、`done` 的正文 allowlist 做收紧：
   - `answer_candidate` 不进入 public body。
   - `assistant_text` 不作为新 public body；旧测试依赖必须改写或删除。
   - `done.content` 不允许进入 UI 正文。
7. 更新终端事件集合：
   - `backend/api/chat.py::TERMINAL_STREAM_EVENTS`
   - `backend/runtime/shared/stream_replay.py::TERMINAL_PUBLIC_EVENTS`
   - `frontend/src/lib/api.ts::TERMINAL_STREAM_EVENTS`
   - `frontend/src/lib/api.ts::StreamResult.terminalEvent`
   - `frontend/src/lib/store/runtime.ts` 中依赖 `"done" | "error" | "stopped"` 的收口逻辑

完成标准：

- public stream 中正文只来自 `assistant_text_delta/final`。
- public terminal 统一为 `turn_completed`，且 status 能表达 completed/failed/stopped。
- backend unit tests 能证明 final 在 terminal 前发出。

### Phase 2 - Tool Item Lifecycle

目标：工具输出从 projection item 猜测改成 first-class lifecycle。

涉及文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/runtime/tool_runtime/tool_observation.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/api/chat.py`
- `backend/harness/runtime/projection/projector.py`

动作：

1. 在模型动作通过 admission/permit 后发出 `tool_item_started`。
2. `tool_item_started.item_id = tool_call_id`。
3. 在 observation 记录后发出 `tool_item_completed`。
4. `tool_item_completed.item_id = same tool_call_id`。
5. 工具错误也通过 completed event state=`error` 输出。
6. 删除 `_item_id("toolobs", data)` 这类导致 observation 变成第二个工具 item 的路径。
7. 保留 tool result summarization/filtering，禁止 raw 大文本直接出现在 UI。

完成标准：

- 一个工具调用在前端只有一个 timeline item。
- running -> done/error 原地更新。
- 没有 tool_call_id 的工具事件 fail closed，不挂到最新 assistant。

### Phase 3 - Public Projection Demotion

目标：投影系统不再拥有正文权威。

涉及文件：

- `backend/harness/runtime/projection/projector.py`
- `backend/harness/runtime/projection/authority.py`
- `backend/harness/runtime/projection/items.py`
- `backend/harness/runtime/projection/timeline_builder.py`
- 相关 projection tests

动作：

1. `projection_items_for_event()` 不再为以下事件生成 body item：
   - `assistant_text_delta`
   - `assistant_text_final`
   - `assistant_stream_repair`
   - `assistant_text`
   - `answer_candidate`
   - `done`
2. `_done_item()` 删除或改为永远不返回 body item。
3. `_assistant_text_item()` 删除；如需要覆盖旧输入，只保留测试 fixture 证明旧 `assistant_text` 不会生成 body，不保留运行路径。
4. `model_action_admission` 不再生成 `opening_judgment` assistant body。
5. projection items 限定为：
   - `status_bar`
   - `control`
   - `task_attachment`
6. live tool window 不再来自 projection envelope；只来自 `tool_item_started/completed`。
7. 历史 task projection 可以保留只读工具活动摘要，但不能作为 live tool item 的权威来源，也不能生成 assistant body。
8. envelope 无 anchor 时 fail closed，不挂最新 assistant。

完成标准：

- `public_projection_envelope.items` 中不存在 assistant body slot。
- 正文、最终总结和投影完全解耦。
- 原来依赖 projection body 的测试被删除或改写为新 transcript contract。

### Phase 4 - Replay And Backpressure Repair

目标：实现 Codex-like lossless tier，不因 live queue 丢事件导致正文卡住。

涉及文件：

- `backend/runtime/shared/event_log.py`
- `backend/runtime/shared/stream_replay.py`
- `backend/api/chat.py`

动作：

1. 给 public event 增加分类字段或通过 event type 判断：
   - lossless: `assistant_text_delta`, `assistant_text_final`, `tool_item_started`, `tool_item_completed`, `turn_completed`
   - best-effort: routine status/progress updates
   - conditionally lossless: terminal control/error receipts that feed `turn_completed`
2. `_stream_run_events()` 发送 live event 前检查 offset 连续性。
3. 如果 `event.offset > latest_offset + 1`：
   - 先从持久 event log replay missing events。
   - 再发送当前 event。
4. 如果 missing events 中有 lossless event，必须发送；best-effort 可按策略压缩或跳过，但必须显式推进 cursor，不能让前端误以为还有缺帧。
5. 保留 `event_log` drop-oldest 作为内存保护，但它不能导致 lossless public stream 永久缺帧。

完成标准：

- 前端不再因为单个 live delta 丢失而永久 pending。
- replay cursor 能恢复完整正文和工具生命周期。

### Phase 5 - Frontend Store Refactor

目标：前端按 Codex-like item stream 消费，不再让 projection 和正文竞争。

涉及文件：

- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/projection/reducer.ts`
- `frontend/src/lib/projection/timeline.ts`
- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/store/utils.ts`
- `frontend/src/lib/store/types.ts`
- `frontend/src/lib/api.ts`

动作：

1. `assistant_text_delta/final` 只更新 `message.content` 和 assistant stream state。
2. `assistant_text_delta/final` 不再读取或依赖 `public_projection_envelope`。
3. 新增 `tool_item_started/completed` reducer：
   - 以 `item_id` upsert timeline item。
   - `completed` 覆盖 `started`。
4. `turn_completed` 只更新 terminal state，不写正文。
5. projection reducer 只处理 task/status/control attachment。
6. 删除 active-turn-to-latest-assistant 的正文/工具 fallback。
7. 历史 hydration 时，runtime attachments 只能按明确 `anchor_message_id` / `anchor_turn_id` 绑定；不能向后找最近 assistant。
8. `frontend/src/lib/api.ts` 和 `frontend/src/lib/store/runtime.ts` 的 terminal event union 从 `"done" | "error" | "stopped"` 迁移到 `turn_completed.status`。

完成标准：

- 正文 reducer 和 projection reducer 权责分离。
- 工具 item 不靠 semantic key 合并。
- turn terminal 不影响 message.content。

### Phase 6 - Chat Rendering Cleanup

目标：删除渲染层正文拼接猜测。

涉及文件：

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/*`

动作：

1. 删除 `assistantBodyFromPublicTimelineItems()` 对最终正文的参与。
2. 删除 `combineAssistantDisplayContent()` 中 message content 与 timeline body 的拼接。
3. timeline 只显示工具、任务、控制、状态。
4. final answer 只显示 `message.content`。

完成标准：

- 渲染层没有正文去重 heuristic。
- timeline body item 不再参与 assistant 正文。

### Phase 7 - Tests And Contract Replacement

目标：测试保护新协议，而不是保护旧 fallback。

后端测试：

- `backend/tests/public_projection_contract_test.py`
  - projection 不产生 assistant body。
  - done 不产生 body。
  - tool start/complete 同 id。
- `backend/tests/harness_single_agent_tool_runtime_regression.py`
  - delta -> final -> turn_completed 顺序。
  - JSON action 不泄漏为 delta。
  - tool_call_id 贯穿 started/completed/observation。
- `backend/tests/harness_model_action_protocol_regression.py`
  - blocked/ask_user 等终端输出走 final 或 control，不走 done body。
- `backend/tests/harness_task_lifecycle_control_regression.py`
  - task executor scheduled 不产生 assistant body。
- `backend/tests/session_runtime_timeline_contract_test.py`
  - history runtime attachment 不把旧 projection body 或旧 tool_window 变成正文。
- `backend/tests/runtime_monitor_projection_test.py`
  - monitor/hydration projection 不重新引入 live tool/window/body 权威。

前端测试：

- `frontend/src/lib/store/assistantStreamReplay.test.ts`
  - delta gap 通过 replay/final 修复，不靠 projection。
- `frontend/src/lib/projection/reducer.test.ts`
  - projection 不渲染正文。
  - no-anchor projection fail closed。
- `frontend/src/lib/store/runtime.test.ts`
  - `done.content` 不覆盖 final。
  - `tool_item_completed` 更新同一工具 item。
- `frontend/src/lib/store/utils.test.ts`
  - history attachment 无明确锚点时不向后挂 assistant。
- 新增：`frontend/src/lib/store/toolItemLifecycle.test.ts`
  - started -> completed 原地更新。
  - completed without started 可生成受控 placeholder，但不能挂错 turn。

完成标准：

- 删除旧的 projection body 合并测试。
- 所有新测试验证真实行为，不 mock 掉核心链路。

## 8. File-Level Execution Checklist

### Backend

| 文件 | 动作 |
| --- | --- |
| `backend/runtime/model_gateway/assistant_stream_frame.py` | 保留 delta/final builder，补齐 final 作为唯一正文完成事件的 contract 字段 |
| `backend/runtime/model_gateway/assistant_stream_normalizer.py` | 保留 safety gate 和 checksum repair，不承担 projection 责任 |
| `backend/harness/loop/single_agent_turn.py` | 发出 tool_item_started/completed；internal done 转为 terminal，不再作为正文权威 |
| `backend/runtime/tool_runtime/tool_executor.py` | 确保 tool_call_id 进入 execution receipt 和 observation |
| `backend/runtime/tool_runtime/tool_observation.py` | 确保 observation to_dict 包含 tool_call_id |
| `backend/api/chat.py` | public stream event 分类；typed events 不 attach envelope；done -> turn_completed |
| `backend/runtime/shared/stream_replay.py` | SSE payload 保留 event_offset，并支持 lossless replay |
| `backend/runtime/shared/event_log.py` | 保持内存保护，但不能造成 lossless 永久缺帧 |
| `backend/harness/runtime/projection/projector.py` | 删除 body projection；工具/status/control only |
| `backend/harness/runtime/projection/items.py` | 收紧 item 类型，不再鼓励 model body item 从 projection 产生 |
| `backend/harness/runtime/projection/timeline_builder.py` | 历史投影与 live contract 对齐 |
| `backend/harness/runtime/session_timeline.py` | 删除向后找 assistant 的历史附件 fallback；旧 body/tool projection 不回灌正文 |
| `backend/harness/runtime/run_monitor/projector.py` | monitor/hydration 输出与新 public stream contract 对齐 |
| `backend/harness/runtime/progress_presenter.py` | progress summary 不再制造 live tool/window/body 权威 |

### Frontend

| 文件 | 动作 |
| --- | --- |
| `frontend/src/lib/api.ts` | 增加/更新 public stream event 类型 |
| `frontend/src/lib/store/types.ts` | 增加 tool item lifecycle state |
| `frontend/src/lib/store/events.ts` | transcript reducer 与 tool lifecycle reducer 分离 |
| `frontend/src/lib/store/runtime.ts` | stream terminal/result/hydration 迁移到 `turn_completed.status` |
| `frontend/src/lib/store/utils.ts` | 历史 runtime attachment 锚定收紧，删除向后找 assistant fallback |
| `frontend/src/lib/projection/reducer.ts` | projection 只处理 task/status/control |
| `frontend/src/lib/projection/timeline.ts` | item_id first，semantic key 只作为非工具 fallback |
| `frontend/src/components/chat/ChatMessage.tsx` | 删除 timeline body 与 message content 合并 |
| `frontend/src/lib/store/assistantStreamReplay.test.ts` | 更新正文流 contract 测试 |
| `frontend/src/lib/projection/reducer.test.ts` | 删除旧 body projection 契约，新增 fail-closed 契约 |
| `frontend/src/lib/store/runtime.test.ts` | 更新 done/final/tool lifecycle 测试 |

## 9. Cutover Rules

本次不保留旧正文投影链路。

允许保留：

- internal runtime `done` 作为内部生命周期事件。
- task projection 作为任务附件状态。
- status/control projection 作为 UI 辅助信息。
- 历史 task projection 的只读活动摘要，但它不能作为 live tool lifecycle 或 assistant body 权威。

不允许保留：

- `done.content` -> assistant body。
- `answer_candidate` -> assistant body。
- `assistant_text` -> projection body。
- `model_action_admission` -> opening_judgment body。
- live tool 通过 projection `tool_window` 呈现。
- tool observation 使用新 `item_id` 并靠 semantic key 合并。
- no-anchor projection 挂到最新 assistant。
- ChatMessage 合并 `message.content` 与 timeline body。
- public stream terminal 继续依赖 `"done" | "error" | "stopped"` 作为 UI 收口权威。

如果实施中发现某条旧链路仍被前端或测试依赖，应暂停说明该依赖是否代表真实外部契约。若不是外部契约，删除旧依赖并更新测试。

## 10. Verification Commands

后端聚焦测试：

```powershell
python -m pytest backend/tests/public_projection_contract_test.py -q
python -m pytest backend/tests/harness_single_agent_tool_runtime_regression.py -q
python -m pytest backend/tests/harness_model_action_protocol_regression.py -q
python -m pytest backend/tests/harness_task_lifecycle_control_regression.py -q
python -m pytest backend/tests/session_runtime_timeline_contract_test.py -q
python -m pytest backend/tests/runtime_monitor_projection_test.py -q
```

前端聚焦测试：

```powershell
Push-Location frontend
npm run test -- src/lib/store/assistantStreamReplay.test.ts src/lib/projection/reducer.test.ts src/lib/store/runtime.test.ts src/lib/store/utils.test.ts
Pop-Location
```

运行链路实测：

```powershell
# 后端固定端口
# 以项目现有启动脚本为准，必须确认监听 127.0.0.1:8003

# 前端固定端口
Push-Location frontend
npm run dev:clean
Pop-Location
```

实测要求：

- `127.0.0.1:3000` 只有一个前端进程监听。
- `127.0.0.1:8003` 只有一个后端进程监听。
- 前端 API base 是 `http://127.0.0.1:8003/api`。
- 手动触发一次包含工具调用的对话：
  - 正文 delta 连续出现。
  - 工具窗口 started 后原地 completed。
  - 最终总结只出现一次。
  - terminal 不覆盖正文。

## 11. Risks And Controls

### 11.1 风险：旧测试依赖 done body

控制：

- 区分 runtime internal done 和 public stream turn_completed。
- 后端内部可继续断言 done 存在，但 public UI 不能从 done 渲染正文。

### 11.2 风险：工具没有 tool_call_id

控制：

- runtime permit 阶段必须补稳定 id。
- 无 id 的 public tool lifecycle event fail closed。
- 测试覆盖 no-id 不挂最新 assistant。

### 11.3 风险：projection 历史 hydration 仍产生正文

控制：

- live projection 和 timeline rebuild 使用同一 contract。
- history hydration 禁止 body slot。
- 如果历史数据中有旧 body item，前端忽略，不做兼容展示。

### 11.4 风险：前端短期缺少工具状态

控制：

- 先实现 `tool_item_started/completed` reducer。
- 再删除 projection tool fallback。
- 两者不能长期共存；同一阶段内完成替换。

## 12. Final Acceptance Criteria

最终验收必须同时满足：

1. 正文只来自 `assistant_text_delta/final`。
2. 最终总结只由 `assistant_text_final` 决定。
3. internal `done/error/stopped` 和 public `turn_completed` 都不写 assistant body。
4. 工具 started/completed 使用同一个 `tool_call_id` item。
5. projection envelope 不含 assistant body item。
6. live tool window 不来自 projection envelope。
7. front-end renderer 不合并 timeline body 与 message content。
8. 历史 hydration 不把旧 projection body/tool_window 回挂到最新 assistant。
9. SSE gap 不会让正文永久卡住。
10. public terminal 由 `turn_completed.status` 表达 completed/failed/stopped。
11. 真实前后端固定端口运行通过。
12. 旧 fallback 代码和旧契约测试被删除或改写。
13. 没有通过 mock、跳过、降低断言来制造通过。

## 13. Implementation Decision

确认后按以下顺序一次性实施：

```text
Phase 0 baseline
-> Phase 1 backend public contract
-> Phase 2 tool lifecycle
-> Phase 3 projection demotion
-> Phase 4 replay/backpressure
-> Phase 5 frontend store
-> Phase 6 renderer cleanup
-> Phase 7 tests and real run
```

除非实施中发现本计划对现有真实外部契约判断错误，否则不保留旧 projection 正文链路。

## 14. Self-Audit Corrections

本节记录计划自审时发现并已修正的遗漏/矛盾，防止实施时回到旧链路。

1. live tool ownership 矛盾已修正：
   - 原文同时说工具归 `tool_item_*` lifecycle，又说 projection items 仍包含 `tool_window`。
   - 修正后：live tool window 只来自 `tool_item_started/completed`；projection 只能保留历史/任务附件的只读活动摘要。

2. terminal lossless 范围已修正：
   - 原文容易把 `error/stopped/control` 归入 best-effort presentation。
   - 修正后：public terminal 统一为 `turn_completed.status`，failed/stopped 也属于 lossless terminal。

3. terminal event cutover 清单已补齐：
   - 原文没有点名 `TERMINAL_STREAM_EVENTS`、`TERMINAL_PUBLIC_EVENTS`、`StreamResult.terminalEvent`。
   - 修正后：后端 chat、stream replay、前端 API、前端 runtime 都列入 Phase 1/Phase 5。

4. history hydration 遗漏已补齐：
   - 原文只覆盖 live reducer，没有覆盖 `session_timeline.py`、`runtime.ts`、`utils.ts` 的历史附件绑定。
   - 修正后：history attachment 不允许向后找最近 assistant，也不能把旧 projection body/tool_window 回灌正文。

5. legacy wording 已收紧：
   - 原文提到 `assistant_text` 可作为 legacy 测试迁移对象，容易被误解为保留旧 public body。
   - 修正后：旧测试依赖必须改写或删除，不保留 public body 链路。
