# Chat Stream Control Authority Refactor Design - 2026-06-28

状态：设计书，待用户确认后实施。  
范围：主聊天流式输出、RuntimeEventLog / replay、public projection、前端 reducer、可见渲染调度、终端与恢复语义。  
实施原则：不保留无用旧链路，不通过兼容壳维持旧输出权威；不新增回归测试文件；实施验收以代码审查、固定端口真实运行和现有链路联调为主。

## 1. 直接结论

本项目当前不是“缺少流式”，而是流式链路已经有较强基础，但公共事件与可见输出权威还没有完全收束。

正确重构方向不是把 WebSocket 换成 SSE，也不是单纯降低 token flush 延迟，而是把流式输出固定为一条单向权威链：

```text
ProviderRawStream
-> ProviderEventNormalizer
-> AssistantStreamFrame
-> RuntimeEventLog
-> PublicProjectionCompiler
-> LiveReplayTransport
-> ClientProjectionReducer
-> RenderCommitScheduler
```

每层只做自己的事：

- provider normalizer 只把不同模型/provider 的碎片归一化。
- assistant frame 只描述模型正文的 sequence、offset、hash、final、repair。
- RuntimeEventLog 是唯一事件事实源。
- live WebSocket / HTTP replay 只是传输方式，不拥有语义。
- public projection 是唯一可见 UI 写入者。
- assistant delta 只能作为正文校验、恢复和投影材料，不能绕过 projection 写主正文。
- frontend reducer 只做幂等应用和 cursor replay，不重新判断正文来源。
- render scheduler 负责 stable/tail 渲染节奏，不决定业务语义。

要达到成熟 coding agent 的标准，必须把“谁有权写可见正文、谁有权宣告终端、谁有权恢复断流”一次性钉死。否则继续调 buffer、加 fallback、加去重规则，只会让前端和后端都在猜哪个事件才是权威输出。

## 2. 成熟架构参考

本设计只借鉴成熟系统的不变量，不照搬目录或具体语言实现。

### 2.1 OpenAI Codex

本机参考源码：

- `D:\AI应用\openai-codex\codex-rs\tui\src\streaming\controller.rs`
- `D:\AI应用\openai-codex\codex-rs\tui\src\markdown_stream.rs`
- `D:\AI应用\openai-codex\codex-rs\tui\src\streaming\commit_tick.rs`

可迁移不变量：

- 流式 markdown 分成 stable region 和 mutable tail。
- raw source 在流式期间 append-only。
- table / code / list 这类会回流的结构不能简单逐 token commit。
- commit tick 只按队列头有序 drain，不直接改业务状态。
- resize / re-render 从 raw accumulated source 重算，而不是做脆弱的 byte-level remap。

落到本项目：

- 前端不应每个 projection body append 都立即 rebuild 完整 view。
- 可见正文需要稳定前缀和可变尾部，尤其是 Markdown 表格、代码块和列表。
- render scheduler 是呈现层，不应该替代 public projection 的语义权威。

### 2.2 Pi Agent

本机参考源码：

- `D:\AI应用\pi-main\packages\ai\src\utils\event-stream.ts`
- `D:\AI应用\pi-main\packages\ai\src\providers\openai-completions.ts`
- `D:\AI应用\pi-main\packages\ai\src\providers\openai-responses-shared.ts`
- `D:\AI应用\pi-main\packages\ai\src\providers\openai-codex-responses.ts`

可迁移不变量：

- provider-specific chunks 必须归一化为统一 assistant event stream。
- `done` / `error` 是 event stream 的 terminal 条件。
- Chat Completions 流结束但没有 `finish_reason` 必须是错误。
- WebSocket close 前没有 `response.completed` / `response.done` / `response.incomplete` 必须是错误。
- tool-call streaming 的 scratch buffers 只用于增量解析，最终持久化时必须删除。
- WebSocket -> SSE fallback 只能发生在真正开始流式事件之前；已经开始输出后不能换 transport 并假装同一条流无损。

落到本项目：

- `turn_completed` 必须是明确 terminal，不允许 close without terminal 被视为成功。
- 断流恢复只能基于 RuntimeEventLog replay，不允许 transport 层自行补语义。
- provider tool delta 如果公开，必须先归并为稳定 tool item，不把 partial JSON 暴露给 public stream。

### 2.3 Hermes

本机参考源码：

- `D:\AI应用\hermes\hermes-agent-main\gateway\stream_consumer.py`
- `D:\AI应用\hermes\hermes-agent-main\agent\stream_diag.py`
- `D:\AI应用\hermes\hermes-agent-main\mcp_serve.py`

可迁移不变量：

- 同步 agent callback 进入异步 queue，再由 consumer 控制平台发送节奏。
- 平台编辑需要 rate limit、flood-control backoff、fresh final 和 segment boundary。
- 工具边界要结束当前文本段，让后续文本出现在工具进度之后。
- stream diagnostics 要记录 status、headers、bytes、chunks、TTFB、elapsed，便于判断是 provider、网关还是客户端问题。
- cursor-based poll / wait 是可行的低阶传输，但仍不应成为语义事实源。

落到本项目：

- 前端可见刷新应有队列和帧预算。
- stream recovery/status 应公开为状态事件，但不能创造正文。
- 诊断字段只能进入 diagnostics，不能进入 agent-visible prompt、history transcript 或最终正文。

### 2.4 LangChain

官方文档：

- https://docs.langchain.com/oss/python/langchain/streaming
- https://docs.langchain.com/oss/python/langchain/event-streaming

本机参考实现：

- `C:\Users\admin\.conda\envs\agent\Lib\site-packages\langchain_core\runnables\schema.py`
- `C:\Users\admin\.conda\envs\agent\Lib\site-packages\langchain_core\runnables\base.py`
- `C:\Users\admin\.conda\envs\agent\Lib\site-packages\langchain_core\tracers\event_stream.py`

可迁移不变量：

- agent progress、LLM token、custom update 是不同 stream mode。
- `astream_events` 的事件携带 `run_id`、`parent_ids`、`name`、`event`、`data`，用于追踪运行树。
- 新文档更强调 typed projections，而不是让 consumer 直接理解 provider 私有 chunk。

落到本项目：

- public event 应该按输出族分类，而不是把所有 runtime event 都推给前端猜。
- 每个 public event 必须携带可追踪 anchor：`stream_run_id`、`event_log_id`、`event_offset`、`turn_run_id`、`task_run_id`、必要时 `tool_call_id`。

### 2.5 Claude Code Source Study

本机目录 `D:\AI应用\Claude-Code-Source-Study-main` 是源码研究文档，不是完整官方源码；因此本文只把它作为线索，不把它当成直接源码证据。

相关材料：

- `docs\05-对话循环.md`
- `docs\20-API调用与错误恢复.md`
- `docs\08-Thinking-与推理控制.md`

可参考线索：

- 流式工具执行需要 gate，发生 streaming fallback 或模型切换时，已启动工具结果必须整体沉没，不能混入新尝试。
- 流式请求要有 stall 观测、idle watcher、资源释放和 request id 追踪。
- thinking / signature block 是 provider-bound 内容，不能随意回放到用户正文或跨 provider 输入。

落到本项目：

- task bridge 与 chat public stream 的连接必须有明确 ownership。
- recovery 不能把失败尝试的中间产物混进下一次 visible output。
- internal protocol / thinking / tool scratch 必须被 normalizer 或 public projection 边界拦住。

## 3. 当前项目审查

### 3.1 已经正确的基础

| 模块 | 当前成熟点 | 目标中保留的权威 |
|---|---|---|
| `backend/runtime/shared/stream_replay.py` | public events 写入 RuntimeEventLog，可按 offset replay，envelope 带 `stream_run_id` / `event_log_id` / `event_offset` / terminal | 继续作为 public stream replay authority |
| `backend/api/chat_live.py` | WebSocket subscribe 后先 catch-up，ack 最新 offset，terminal 后 close | 继续作为 live delivery transport |
| `frontend/src/lib/api/chatStream.ts` | 本地 cursor、HTTP replay、reconnect、final replay、offset 去重 | 继续作为 client transport consumer |
| `backend/runtime/model_gateway/assistant_stream_normalizer.py` | coalesce、sequence、safety gate、内部协议检测 | 继续作为 model text normalizer |
| `backend/runtime/model_gateway/assistant_stream_frame.py` | `assistant_text_delta` / `assistant_text_final` / `assistant_stream_repair` 带 offset/hash/repair | 继续作为 assistant text frame schema |
| `frontend/src/lib/projection/reducer.ts` | projection frame 校验 authority、frame id、event offset、required keys | 继续作为 projection admission gate |
| `frontend/src/lib/store/events.ts` | 裸 `assistant_text_delta` 不直接写 visible message body | 继续并升级为正式契约 |
| `frontend/src/lib/store/runtime.ts` | stream epoch / active binding 防止旧流污染当前流 | 继续作为 stale stream guard |

这些基础说明本项目已经接近成熟 agent 的流式底座，不应该推倒重做。重构重点是收束权威和清理旧链路。

### 3.2 当前主要结构风险

| 风险 | 证据 | 后果 | 处理方向 |
|---|---|---|---|
| public event 类型过宽 | `backend/api/chat.py` 同时处理 assistant delta、projection、task bridge、tool、terminal、commit ack | 前端需要识别太多事件，容易出现重复决策 | 收缩 public event families |
| 可见正文存在双通道 | assistant delta 有 content，projection frame 也可能有 body patch | 裸 delta、projection、done/final 可能竞争正文权威 | 明确 projection-only visible body |
| bridge 路径过多 | turn context、task bridge、active task、projection lifecycle 在 `chat.py` 交织 | task output 与 chat output ownership 不稳定 | 抽出 public stream compiler / bridge adapter |
| terminal 与 transport close 仍需更硬 | WebSocket close 与 run terminal 绑定已存在，但 close without terminal 仍依赖前端重试与最终 replay | 极端断流下容易出现用户误以为仍在生成或已完成 | 后端公开 explicit interruption / terminal reconciliation |
| render scheduler 不够结构化 | 当前有 deferred visible flush，但不是 markdown-aware stable/tail | 表格、代码块、列表可能跳动或重排成本高 | 引入 stable/tail render commit scheduler |
| diagnostics 与正文边界需更清楚 | stream recovery / reconnect / timing 可能进入普通 data | 后续维护容易把诊断显示成正文 | diagnostics 独立命名空间 |

### 3.3 当前真实链路

```text
backend/api/chat.py
-> runtime.harness_runtime.astream(request)
-> model_gateway assistant stream normalizer
-> task / turn events
-> _append_chat_public_event()
-> RuntimeStreamReplayService.append_public_event()
-> RuntimeEventLog
-> backend/api/chat_live.py WebSocket catch-up
-> frontend/src/lib/api/chatStream.ts consume envelope
-> frontend/src/lib/store/runtime.ts stream epoch binding
-> frontend/src/lib/store/events.ts reduceStreamEvent()
-> frontend/src/lib/projection/reducer.ts applyProjectionFrame()
-> Chat UI render
```

这个链路里最需要重构的是 `backend/api/chat.py` 的 public stream 编译职责。它现在既像 API endpoint，又像 public projection compiler，又像 task bridge adapter，又像 terminal reconciler。目标不是简单拆文件，而是拆权威。

## 4. 目标权威链

### 4.1 Layer Contract

| 层 | 允许做什么 | 禁止做什么 | 目标模块 |
|---|---|---|---|
| ProviderRawStream | 接收 provider 原始 chunk | 生成 public UI 事件 | `runtime/model_gateway/*` |
| ProviderEventNormalizer | 归一化 provider text/thinking/tool delta | 修改用户可见最终语义 | `assistant_stream_normalizer.py` |
| AssistantStreamFrame | 生成 sequence/offset/hash/final/repair | 直接写 UI message content | `assistant_stream_frame.py` |
| RuntimeEventLog | append-only 记录 public event | 根据客户端状态改写事件 | `runtime/shared/event_log.py` |
| PublicProjectionCompiler | 把 runtime event 编译成 public projection frame | 执行工具、恢复 provider、生成模型正文 | 新增 `backend/runtime/output_stream/public_stream_compiler.py` 或迁入 harness output boundary |
| LiveReplayTransport | WebSocket / HTTP replay 发送 envelope | 创造 terminal、补正文、吞 gap | `chat_live.py` / `stream_replay.py` |
| ClientProjectionReducer | 幂等应用 projection frame | 从裸 delta / done 猜正文 | `frontend/src/lib/store/events.ts` / `projection/reducer.ts` |
| RenderCommitScheduler | stable/tail / frame budget / markdown holdback | 改变 event 顺序或正文权威 | 新增 frontend projection render scheduler |

### 4.2 Public Event Families

public stream 保留以下输出族。旧事件如果仍在 runtime 内部存在，不得直接穿透到 chat public stream。

```text
body:
  assistant_text_delta
  assistant_text_final
  assistant_stream_repair

projection:
  public_projection_frame

tool:
  tool_item_started
  tool_item_delta        // 可选，仅展示安全摘要，不暴露 partial JSON
  tool_item_completed

control:
  stream_recovery
  stream_reconnected
  stream_reconnect_failed
  runtime_status

terminal:
  turn_completed
  turn_failed
  turn_stopped
```

设计决策：

- `assistant_text_delta` 可以继续存在，但它不是 visible body writer。
- visible body 必须通过 `public_projection_frame` 中 `body_append` / `body_finalize` 修改。
- `assistant_text_final` 用于最终校验和 projection final material，不直接覆盖 UI message content。
- `done.content`、`answer_candidate.content`、legacy `assistant_text` 不再进入可见正文。
- `turn_completed` 不承担正文兜底，只承担 terminal。
- tool partial args 不进入 public stream；公开工具进度只展示 tool name、target、state、safe summary。

### 4.3 Projection Frame Contract

所有可见 projection frame 必须满足：

```text
authority = "harness.public_projection"
frame_id / projection_id 非空
event_offset 有效
op 非空
slot 非空
main_visibility 非空
retention 非空
anchor.stream_run_id / event_log_id / turn_run_id 尽量完整
```

新增约束：

- body patch 必须携带 `body_ref` 或 `message_ref`。
- 同一 `body_ref` 的 body append 必须按 `event_offset` 单调应用。
- body finalize 必须携带 `content_sha256` 或 equivalent final checksum。
- replay 时同一 `frame_id` 幂等。
- frame 不得包含 provider raw protocol、tool raw arguments、internal action JSON。

### 4.4 Terminal Contract

terminal 不再由 transport close 推断。终端语义如下：

```text
turn_completed(status="completed")
turn_completed(status="failed")
turn_completed(status="stopped")
```

规则：

- WebSocket 收到 terminal envelope 后可以 close。
- WebSocket close without terminal 是 transport failure，前端必须 HTTP replay。
- replay 后仍无 terminal 且 backend run 已 terminal，后端必须公开 terminal reconciliation event。
- backend run 未 terminal 且 active task 仍存在，前端显示 recovering / reconnecting，不宣告完成。
- backend 确认 interruption 时，必须写 public interruption/failed terminal，不只记录私有 diagnostics。

### 4.5 Recovery Contract

recovery 只允许做三件事：

1. 根据 `event_offset` replay 已经存在的 public events。
2. 根据 final checksum 修正当前 body projection。
3. 把不可恢复状态公开为 `turn_completed(status="failed")` 或 `stream_reconnect_failed`。

recovery 禁止做：

- 根据当前 UI 字符串拼接一段“看起来像”缺失正文。
- 根据 `done.content` 反向覆盖 projection body。
- 把内部 protocol JSON 作为正文补出来。
- 把旧 stream_run 的事件应用到新 stream epoch。

## 5. 重构范围与删除规则

### 5.1 必须删除或停止穿透的旧入口

| 旧入口 | 处理 |
|---|---|
| `done.content` 作为可见正文 | 停止进入 public body projection |
| `answer_candidate.content` 作为可见正文 | 停止进入 public body projection，保留为内部候选或诊断 |
| legacy `assistant_text` 可见正文 | 停止作为 public body writer |
| assistant delta 裸写 message content | 保持当前禁止，并把禁止规则文档化为 reducer contract |
| projection fallback 根据内容去重猜测 final | 以 frame id / body ref / checksum 替代 |
| task bridge 直接散发多类正文事件 | 统一经过 public stream compiler |
| provider tool partial JSON public passthrough | 移到 internal diagnostics 或 tool normalizer scratch |

### 5.2 可保留但需收口的模块

| 模块 | 保留原因 | 收口方式 |
|---|---|---|
| `RuntimeStreamReplayService` | 已是正确 event-sourced 方向 | 增加更严格 envelope schema 和 terminal reconciliation |
| `chat_live.py` | WebSocket live 可继续作为低延迟 transport | 不再承担语义；只 subscribe/catch-up/ack/terminal close |
| `assistant_stream_normalizer.py` | provider text safety gate 正确 | stream policy 参数化，进一步明确不负责 UI |
| `frontend chatStream.ts` | replay/reconnect 成熟 | 收口事件族，严格 terminal/recovery 状态 |
| `projection/reducer.ts` | authority gate 正确 | 增加 body ref/checksum/finalize contract |
| `runtime.ts` stream epoch | 防旧流污染正确 | 接入 render commit scheduler |

### 5.3 不做的事

- 不把本项目重写成 LangChain runnable graph。
- 不把 WebSocket 改成唯一 SSE 或把 SSE 改成唯一 WebSocket。
- 不复制 Codex Rust TUI；只迁移 stable/tail 和 commit tick 不变量。
- 不用前端字符串去重代替后端 event identity。
- 不新增测试文件来制造通过。
- 不保留旧 projection body fallback 作为“兼容路径”。

## 6. 目标模块设计

### 6.1 Backend Public Stream Compiler

建议新增或收束成一个明确模块：

```text
backend/runtime/output_stream/public_stream_compiler.py
```

如果后续进行 harness 目录收束，也可以放入：

```text
backend/harness/runtime/output_stream/public_stream_compiler.py
```

职责：

- 接收 runtime event + current public anchor。
- 决定该 event 是否进入 public stream。
- 编译 `public_event_type` 和 `public_projection_frame`。
- 统一 body/tool/status/terminal families。
- 对所有 data 做 public redaction。
- 维护 ProjectionLifecycleState。

禁止：

- 调用 provider。
- 执行 tool。
- 根据 UI 旧状态补正文。
- 直接写 WebSocket。

输入：

```python
RuntimePublicEventInput(
    raw_event: dict,
    stream_run_id: str,
    event_log_id: str,
    session_id: str,
    turn_run_id: str,
    task_run_id: str,
    active_turn_id: str,
    public_sequence_base: int,
)
```

输出：

```python
CompiledPublicStreamEvent(
    public_event_type: str,
    data: dict,
    projection_frame: dict | None,
    terminal: bool,
    visibility: "public" | "diagnostic" | "drop",
)
```

### 6.2 Backend Transport Envelope

`RuntimeStreamReplayService.to_public_envelope()` 输出固定结构：

```json
{
  "type": "event",
  "protocol": "agent-live.v1",
  "stream_run_id": "...",
  "event_log_id": "...",
  "event_id": "...",
  "event_offset": 12,
  "runtime_event_id": "...",
  "public_event_type": "public_projection_frame",
  "terminal": false,
  "data": {},
  "diagnostics": {},
  "public_projection_frame": {}
}
```

规则：

- `data.event_offset` 与 envelope `event_offset` 必须一致。
- `diagnostics` 与 `data` 分离；不会进入 projection text。
- sanitize 发生在 append 前和 replay 前两个边界，append 前是主防线，replay 前是防腐层。
- `public_projection_frame` 若不合法，直接移除，不做降级 body。

### 6.3 Frontend Projection Reducer

`reduceStreamEvent()` 的目标规则：

```text
event envelope
-> validate stream epoch / binding
-> validate event_offset monotonic
-> validate projection frame authority
-> apply projection ledger
-> update stream connection state
-> schedule visible render commit
```

禁止：

- `assistant_text_delta.content` 直接写 `message.content`。
- `done.content` 覆盖最终正文。
- 通过正文字符串相似度决定 final 权威。
- replay 事件绕过 projection ledger。

### 6.4 Render Commit Scheduler

新增前端结构建议：

```text
frontend/src/lib/projection/renderScheduler.ts
frontend/src/lib/projection/markdownStability.ts
```

职责：

- 将 projection body source 分为 stable prefix 和 mutable tail。
- 对普通段落按 newline / punctuation / time budget commit。
- 对 markdown table 从 header + delimiter 处进入 holdback。
- 对 code fence 在 fence 未闭合前保持 tail。
- 对 list / blockquote 保留当前 block tail，避免反复重排。
- 按 requestAnimationFrame 或最大 32ms flush。
- final / repair / terminal 到达时 drain pending。

状态模型：

```ts
type RenderCommitState = {
  bodyRef: string;
  rawSource: string;
  committedSourceLength: number;
  stableText: string;
  tailText: string;
  tableHoldbackStart: number | null;
  pendingFrameIds: string[];
  latestEventOffset: number;
};
```

### 6.5 Stream Diagnostics

诊断字段只用于观测：

```json
{
  "diagnostics": {
    "server_event_created_at": 0,
    "server_ws_sent_at": 0,
    "server_replay_sent_at": 0,
    "client_received_at": 0,
    "client_visible_flushed_at": 0,
    "reconnect_attempt": 0,
    "replay_reason": ""
  }
}
```

规则：

- 不进入 history transcript。
- 不进入 agent context。
- 不进入 final answer。
- 不参与 projection identity。

## 7. 分阶段实施计划

本计划涉及 backend runtime/API contract、frontend reducer/render、public stream protocol，实施前必须由用户确认。

### 阶段 0：锁定契约与现状清点

目标：先冻结目标事件族和旧入口删除清单，避免实施中漂移。

涉及文件：

- `backend/runtime/output_stream/public_contract.py`
- `backend/api/chat.py`
- `backend/runtime/shared/stream_replay.py`
- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/projection/reducer.ts`
- `frontend/src/lib/api/chatStream.ts`

动作：

1. 列出所有当前 public event type。
2. 标记 body/tool/status/terminal/diagnostic/drop family。
3. 明确 `done.content`、`answer_candidate.content`、legacy `assistant_text` 的删除路径。
4. 在 public contract 中增加事件族注释和禁止事项。

完成标准：

- 每个 public event 都有唯一 family。
- 每个 family 都有 owner。
- 没有“临时继续让前端猜”的开放项。

### 阶段 1：抽出 Public Stream Compiler

目标：从 `backend/api/chat.py` 中移出 public event 编译权威。

涉及文件：

- `backend/api/chat.py`
- `backend/runtime/output_stream/public_contract.py`
- 新增 `backend/runtime/output_stream/public_stream_compiler.py`
- 可能新增 `backend/runtime/output_stream/projection_frame_builder.py`

动作：

1. 将 `_project_public_stream_event()`、`_assistant_stream_public_data()`、tool/status/terminal public data 编译逻辑归入 compiler。
2. `chat.py` 只负责接收 runtime astream、调用 compiler、append public event。
3. ProjectionLifecycleState 归 compiler 管理。
4. 删除不再合法的 body fallback 分支。

完成标准：

- `chat.py` 不再直接决定某个 runtime event 如何写 visible body。
- public stream compiler 成为唯一 public projection 生成点。
- 旧正文入口不再进入 body projection。

### 阶段 2：Projection-Only Visible Body

目标：可见正文唯一由 `public_projection_frame` 修改。

涉及文件：

- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/projection/reducer.ts`
- `frontend/src/lib/projection/chronological/*`
- `frontend/src/lib/store/runtime.ts`
- `backend/runtime/model_gateway/assistant_stream_frame.py`
- `backend/runtime/model_gateway/assistant_stream_normalizer.py`

动作：

1. 固化 reducer 规则：裸 `assistant_text_delta/final/repair` 只更新 stream diagnostic state，不 patch visible body。
2. body append/finalize 只能从合法 projection frame 进入。
3. projection frame body 增加 `body_ref`、`message_ref`、final checksum。
4. 删除 `done.content`、`answer_candidate.content` 等覆盖逻辑。

完成标准：

- 前端没有第二条 visible body writer。
- assistant delta 可用于 checksum/repair，但不会绕过 projection。
- final answer 权威来自 body finalize projection，而非 terminal event。

### 阶段 3：Transport 与 Replay 收口

目标：WebSocket 和 HTTP replay 共用同一 envelope contract。

涉及文件：

- `backend/runtime/shared/stream_replay.py`
- `backend/api/chat_live.py`
- `backend/api/chat.py`
- `frontend/src/lib/api/chatStream.ts`

动作：

1. envelope schema 固定并集中生成。
2. replay response 与 WebSocket event 保持同构。
3. close without terminal 强制进入 replay/recovery。
4. run 已 terminal 但 stream 缺 terminal 时，后端生成 terminal reconciliation public event。
5. gap event 不让前端猜，直接触发 HTTP replay。

完成标准：

- live 和 replay 消费路径一致。
- transport close 不代表业务完成。
- replay 后前端能得到明确 completed/failed/stopped 或 reconnect_failed。

### 阶段 4：Markdown Stable/Tail Render Scheduler

目标：提升可见流式质量，降低重排压力。

涉及文件：

- 新增 `frontend/src/lib/projection/renderScheduler.ts`
- 新增 `frontend/src/lib/projection/markdownStability.ts`
- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/projection/reducer.ts`
- `frontend/src/components/chat/ChatMessage.tsx`

动作：

1. projection body source append 后进入 render scheduler。
2. scheduler 根据 markdown block stability 产出 stable text + tail text。
3. requestAnimationFrame / max 32ms 批量 flush。
4. final/repair/terminal/session switch 立即 drain。
5. 表格、代码块、列表、blockquote 使用 holdback。

完成标准：

- 长回复不再每帧重建全量 view。
- 表格和代码块流式显示不明显跳动。
- final 到达后 visible body 与 final checksum 一致。

### 阶段 5：Diagnostics 与 Failure Visibility

目标：让用户和开发者能区分 provider 慢、backend 慢、transport 断、frontend flush 慢。

涉及文件：

- `backend/runtime/shared/stream_replay.py`
- `backend/api/chat_live.py`
- `frontend/src/lib/api/chatStream.ts`
- `frontend/src/lib/store/runtime.ts`

动作：

1. envelope diagnostics 加入 server created/sent timestamps。
2. client consume 加入 received/visible flushed timestamps。
3. reconnect/replay reason 进入 diagnostics/status，不进入正文。
4. stream_recovery 只作为状态显示，不作为 body patch。

完成标准：

- 单轮 run 可定位四段延迟。
- diagnostics 不进入 transcript / final answer / agent context。
- reconnect/replay 的用户可见状态清楚，但不污染正文。

### 阶段 6：旧逻辑清理与文件瘦身

目标：移除旧输出权威和重复桥接。

涉及文件：

- `backend/api/chat.py`
- `backend/runtime/output_stream/public_contract.py`
- `frontend/src/lib/store/events.ts`
- `frontend/src/lib/projection/reducer.ts`
- `frontend/src/lib/projection/chronological/*`
- `frontend/src/lib/store/runtime.ts`

动作：

1. 删除不再可达的 public event allowlist 项。
2. 删除 legacy body fallback 和 content-based final overwrite。
3. 删除过时的 semantic body dedupe 分支，只保留 frame/body ref 幂等。
4. `chat.py` 只保留 API orchestration，不再承担 projection compiler。
5. 同步清理废弃类型和注释。

完成标准：

- 没有旧正文权威残留。
- 没有双写 visible body。
- 文件职责清楚，后续维护者能沿目标权威链追踪。

## 8. 文件级执行清单

### Backend

| 文件 | 操作 | 说明 |
|---|---|---|
| `backend/api/chat.py` | 重写/瘦身 | 移出 public event 编译、body projection、terminal reconciliation 细节 |
| `backend/api/chat_live.py` | 小改 | 保持 transport，只强化 close/gap/terminal 协议 |
| `backend/runtime/shared/stream_replay.py` | 重写局部 | 固定 envelope schema、sanitize、terminal reconciliation support |
| `backend/runtime/output_stream/public_contract.py` | 重写局部 | 定义 public event families、terminal、projection required fields |
| `backend/runtime/output_stream/public_stream_compiler.py` | 新增 | public stream 编译权威 |
| `backend/runtime/output_stream/projection_frame_builder.py` | 可选新增 | 如果 compiler 过大，则抽 frame builder |
| `backend/runtime/model_gateway/assistant_stream_normalizer.py` | 小改 | 明确 normalizer 不拥有 visible body，stream policy 参数化 |
| `backend/runtime/model_gateway/assistant_stream_frame.py` | 小改 | 补 body_ref/message_ref/final checksum contract |
| `backend/runtime/model_gateway/stream_recovery.py` | 小改 | recovery 只产状态/repair，不产正文猜测 |

### Frontend

| 文件 | 操作 | 说明 |
|---|---|---|
| `frontend/src/lib/api/chatStream.ts` | 小改 | 收口 event families，强化 replay/terminal 状态 |
| `frontend/src/lib/store/events.ts` | 重写局部 | projection-only visible body，删除 legacy body writer |
| `frontend/src/lib/store/runtime.ts` | 重写局部 | 接 render scheduler，保留 stream epoch/binding |
| `frontend/src/lib/projection/reducer.ts` | 重写局部 | 增加 body_ref/checksum/finalize 幂等 |
| `frontend/src/lib/projection/chronological/accumulator.ts` | 小改 | 从 frame/body ref 构建 ledger，不做正文猜测 |
| `frontend/src/lib/projection/renderScheduler.ts` | 新增 | stable/tail + frame budget |
| `frontend/src/lib/projection/markdownStability.ts` | 新增 | markdown block holdback 判断 |
| `frontend/src/components/chat/ChatMessage.tsx` | 小改 | 渲染 stable/tail body，不参与正文权威判断 |

### Docs

| 文件 | 操作 | 说明 |
|---|---|---|
| `docs/maintenance/chat_stream_control_authority_refactor_design_20260628.md` | 保留 | 本设计书 |
| `docs/maintenance/codex_lossless_output_stream_replacement_plan_20260611.md` | 参考/可能归档 | 若实施本方案，新方案应取代旧 lossless 输出流计划中已过时的正文权威描述 |
| `docs/reviews/chat-streaming-output-audit-2026-06-18.md` | 参考/可能归档 | 作为历史问题审计，不作为新目标架构 |

## 9. Cutover Rules

本项目要求不保留无用旧链路，因此 cutover 不能长期双轨。

### 9.1 允许的过渡

- 同一阶段内可以先加入新 compiler，再把调用点切过去，最后删除旧函数。
- live/replay 可短时间同时支持同一 envelope 的旧字段和新字段，但新字段必须是主路径。
- diagnostics 可先作为可选字段出现。

### 9.2 禁止的过渡

- 不允许新 projection body 与旧 `done.content` 同时写 visible body。
- 不允许旧 assistant_text fallback 继续保留在 reducer 中。
- 不允许前端以字符串去重作为新 contract 的一部分。
- 不允许 provider raw tool JSON 出现在 public stream。
- 不允许 terminal 缺失时前端自己宣告 completed。

### 9.3 回滚原则

如果实施中发现关键假设错误，不能在旧链路上叠补丁，应暂停并回到本文调整计划。

允许回滚到上一阶段完整状态；不允许只回滚某个删除点后继续保留半新半旧正文权威。

## 10. 验收与验证

用户明确禁止新增回归测试文件，因此本文不规划新增测试文件。验证以真实运行、代码审查和现有链路检查为主。

### 10.1 静态审查

必须逐项确认：

- `assistant_text_delta` 不直接写 visible body。
- `done.content` 不覆盖 final body。
- `answer_candidate.content` 不进入 public body projection。
- public projection frame 都经过 authority / required keys / event_offset 校验。
- `chat.py` 不再散落 body/tool/terminal 编译逻辑。
- recovery 不制造正文。
- diagnostics 不进入 transcript。

### 10.2 真实运行验证

涉及运行链路时必须使用固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api base: http://127.0.0.1:8003/api
```

验证场景：

| 场景 | 验收 |
|---|---|
| 普通长文本回复 | 正文持续出现，final 后无重复 |
| Markdown 表格 | 表格区域不反复破碎重排，final 后格式稳定 |
| 代码块回复 | 未闭合代码块保持 tail，final 后稳定 |
| 工具调用后继续正文 | 工具 item 与后续正文顺序正确 |
| WebSocket 断开 | HTTP replay 补齐，不重复正文 |
| terminal 到达 | cursor 清理，状态 completed/failed/stopped 明确 |
| 后端 run terminal 但前端缺 terminal | replay 后收到 terminal reconciliation |
| 内部 action JSON 输出风险 | 不出现在用户正文 |

### 10.3 诊断验收

每轮 stream 至少能定位：

- server event created time
- server sent time
- client received time
- visible flushed time
- reconnect attempt/reason
- replay reason

这些信息只在 diagnostics/status 中出现，不进入正文。

## 11. 风险控制

| 风险 | 控制 |
|---|---|
| 拆 `chat.py` 牵动太大 | 先抽 compiler，不改 runtime astream 主链 |
| 前端 body 权威收束后出现空白 | compiler 必须先产合法 body projection，再删除旧 body writer |
| replay 与 live 字段不一致 | 统一由 `RuntimeStreamReplayService.to_public_envelope()` 生成 |
| Markdown scheduler 引入 UI 卡顿 | scheduler 只处理可见 body，不参与 reducer 语义；final/repair 立即 drain |
| recovery 丢正文 | 只能 replay event log 或 apply repair/final checksum，不靠 UI 字符串补 |
| 旧逻辑被保留 | 每阶段完成时执行旧入口删除清单，不留“兼容”出口 |

## 12. 实施前确认项

本文已经锁定目标设计，不保留开放架构分歧。实施前只需要用户确认是否按本文路线执行。

确认后应按阶段完整实施；如果实施中发现本文假设错误、影响范围扩大、或需要改变 public protocol，必须暂停说明偏差，再请求确认。

## 13. 最终目标状态

完成后，主聊天流式输出应满足：

```text
append-only event source
-> typed public stream
-> replayable cursor
-> projection-only visible body
-> markdown-aware stable/tail render
-> explicit terminal
-> observable recovery
```

维护者应该能从任意用户可见字符反查：

- 来自哪个 `stream_run_id`
- 来自哪个 `event_log_id`
- 来自哪个 `event_offset`
- 来自哪个 projection frame
- 属于哪个 turn/task/tool anchor
- 是否 final checksum 覆盖

这才是成熟 agent 的流式控制：快只是结果，权威清楚、可恢复、可审计、可收口才是底层标准。
