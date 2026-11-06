# Information Acquisition and Semantic Context Spine Design

创建日期：2026-06-30

状态：待用户审阅确认。本文是 runtime/context/model packet 主链路设计与修复计划，不是已实施记录。

本文取代把问题缩小成 `plan_binding` 的旧表述。计划、todo、active work 都只是 agent 工作状态的一部分；更底层的问题是：agent 在每一轮如何获得信息、判断信息新旧与权威、把信息放入正确时间位置，并以不破坏 provider prefix 性能的方式交给模型决策。

## 1. 成熟架构裁决

成熟 agent 的上下文系统不是“把所有看起来相关的内容塞进 prompt”，也不是“靠记忆维持任务”。它必须形成一条清楚的信息获取与语义时空脊柱：

```text
Request facts
-> Information acquisition candidates
-> Authority and freshness ranking
-> Context contract projection
-> Physical lane assembly
-> Provider payload bytes
-> Provider success commit
-> Next-turn replay / recovery
```

正确的 agent 决策来自三个同时成立的条件：

1. 时间连续性完整：模型能看到之前真实发生过的用户正文、assistant 正文、工具调用和工具观察。
2. 当前信息优先：本轮用户输入、当前边界、当前恢复/反馈不会被旧状态覆盖。
3. 获取路径明确：当关键事实缺失或过期时，系统要把“需要获取什么信息”暴露给 agent 的行动空间，而不是用旧摘要、旧计划或猜测补位。

因此当前故障的本质不是“计划书没有绑定”，而是：

```text
正文历史缺失
-> agent 的时间连续性断裂
-> 当前执行态没有足够权威压住 planning mode
-> 信息获取优先级失真
-> 模型重复生成计划书
```

计划书是 conversation 正文。已批准计划可以派生执行状态，但执行状态不能替代正文历史。

## 2. 现有代码事实

本项目不是没有上下文架构。当前已经有可保留的成熟骨架：

| 层 | 现有权威 | 真实职责 |
| --- | --- | --- |
| 原始对话事实 | `storage/sessions/* api_transcript` | 保存 provider-visible 对话正文和 provider protocol message |
| provider history 投影 | `backend/harness/runtime/compiler.py:_provider_protocol_message_specs` | 从 transcript 生成 provider protocol history specs |
| 上下文候选策略 | `backend/runtime/context_management/context_segment_registry.py` / `context_segment_policy.py` | 声明 kind、section、slot、commit/replay/cache policy |
| provider-visible ledger | `backend/runtime/context_management/provider_visible_context_ledger.py` | provider 成功后封存可 replay 的 provider-visible candidate |
| 物理拼接 | `backend/runtime/context_management/physical_context_assembler.py` | 唯一拼接顺序：static -> confirmed frame -> current append -> tail |
| 物理 lane | `backend/runtime/context_management/physical_context_plan.py` | global static / provider-visible prefix / current tail / never replay tail |
| byte preservation | `backend/runtime/context_management/provider_message_replay_contract.py` | 决定 provider-shaped message 是否需要逐字保留 |
| 当前任务/证据投影 | `backend/harness/runtime/dynamic_context/*` | 生成 task state、evidence cursor、read evidence、turn attention |
| 热状态/恢复 | `backend/runtime/turn_memory/*` | 保存 current/recovery/commit/pending 状态，不替代 confirmed history |

这些部件说明正确方向不是新造一套上下文系统，而是把现有部件按成熟权威链重新接准。

## 3. 当前断点

### 3.1 时间脊柱断裂

`compiler.py` 当前核心断点：

```text
_provider_protocol_message_specs()
-> _provider_protocol_hot_messages()
-> _provider_protocol_closed_tool_round_messages()
```

`_provider_protocol_closed_tool_round_messages()` 只保留：

- assistant(tool_calls) + 后续闭合 tool messages。
- 带 `reasoning_content` 的 assistant。

它主动丢掉：

- 普通 `user(content)`。
- 普通 `assistant(content)`。

结果是 `api_transcript` 里有计划书正文和用户批准，但 provider history 投影时丢掉正文。模型下一轮看不到“计划已经写过、用户已经批准”，自然回到 planning。

### 3.2 provider history 的 cache/commit 语义矛盾

`provider_protocol_history` 的 metadata 说它是 append-only provider-visible history，但 spec 顶层仍设置：

```text
cache_scope=none
cache_role=never_cache
prefix_tier=none
```

这会让它既像历史，又不能成为稳定 provider-visible prefix。系统随后只能用其他片段补历史，导致语义位置错乱。

### 3.3 current user context 被误当历史替代品

`current_turn_user_context` 是本轮当前输入。它应该只表达 Present，不应该长期替代 Past timeline。

但当前有两类风险：

- registry 把它声明为 `CONTEXT_APPEND` 且 append-only。
- followup 旁路 `provider_visible_context_append_candidate_spec()` 没有完全委托统一 sealability owner。

因此当 provider history 正文缺失时，ledger 可能封存 current user/context 这类碎片，形成“UI 有正文、模型下一轮却只看到当前上下文残片”的错位。

### 3.4 byte-preserve 与 sealed replay 混用

当前 `provider_message_replay_contract.py` 将两类概念归到同一个判断里：

```text
provider_protocol_replay
physical_prefix_frame_replay
```

两者都需要 byte preservation，但语义不同：

| 概念 | 语义 |
| --- | --- |
| provider protocol append candidate | 当前请求要追加的精确历史 message，尚未成为 physical frame replay |
| physical prefix frame replay | 已经 provider success 确认、下一轮从 frame 回放的旧前缀 |

如果 assembler 把 provider protocol append candidate 当成“已经 replay 的旧 frame”，它会被排除出 current append，导致历史继续缺席。

### 3.5 信息获取层没有被提升为决策前置能力

现有代码已经有 evidence index、read evidence、editor index、task state projection、turn attention index，但它们目前更像若干上下文片段，而不是明确的信息获取优先级系统。

成熟设计里，agent 在做 planning / execution / recovery 前，需要先知道：

```text
当前我看到了什么？
哪些信息是历史已确认？
哪些信息只是记忆线索？
哪些信息已经过期？
哪些文件/证据只看到索引，还需要精确读取？
哪些工具观察是新事实？
当前用户输入是否覆盖旧计划？
当前边界允许我获取哪些信息？
```

这个能力必须成为 context assembly 的结构目标，而不是散落在 prompt 文案里。

## 4. 目标原则

### 4.1 时间原则

```text
Current user input outranks all old context.
Exact conversation history outranks memory summary.
Current runtime boundary outranks old runtime boundary.
Committed tool/evidence observations outrank unverified memory.
```

### 4.2 空间原则

信息按来源空间分层：

| 空间 | 含义 | 默认形态 |
| --- | --- | --- |
| Conversation space | 用户和 assistant 曾经说过什么 | provider protocol messages |
| Runtime state space | 当前 turn/run/work 的状态 | current tail / never replay tail |
| Evidence space | 文件、附件、编辑器、工具观察 | refs/hash/index，必要时 exact read |
| Memory space | 长期偏好、摘要、背景 | low-authority hints |
| Transport space | provider tools/schema/params/cache | hidden transport, not prompt memory |

### 4.3 获取原则

信息获取不是“工具调用前的小步骤”，而是 agent 决策前的认知位置：

```text
When exactness matters, prefer exact evidence over summary.
When freshness matters, prefer current read over old observation.
When scope is unknown, acquire index before full body.
When index says missing/stale, expose a read action path.
When current user changes the goal, do not let old plan continue silently.
```

### 4.4 性能原则

性能不能靠丢正文获得。性能应靠：

- 精确 history replay 后进入 confirmed physical prefix。
- evidence 默认 ref/hash/index，只有决策需要时读取精确正文。
- dynamic tail 不进入 cache spine。
- old runtime boundary 不回放为当前授权。
- compaction 只替换明确边界前的旧历史，不能吞掉未封存的正文。
- provider transport 作为 hidden sidecar，不复制进 prompt。

## 5. 目标信息优先级

每轮模型看到的信息应按以下权威关系组装。这里的 P0/P1/P2 是语义优先级，不等于物理数组下标。

| Priority | 信息类别 | 作用 | 物理位置 |
| --- | --- | --- | --- |
| P0 | 当前用户输入 | 本轮最高优先级意图来源 | current_turn_tail |
| P0 | 精确 conversation timeline | 维持时间连续性，包含 plan 正文和批准正文 | provider_visible_context_prefix 或 current append |
| P0 | 当前 runtime boundary | 当前权限、动作合同、恢复限制 | never_replay_tail |
| P0 | 当前信息缺口 | 告诉 agent 哪些事实必须获取后才能判断 | never_replay_tail / action horizon |
| P1 | 已确认工具观察 | 已发生事实，可用于后续判断 | provider_visible_context_prefix |
| P1 | evidence index / read refs | 空间证据索引、hash、范围、freshness | current append then seal |
| P1 | active TaskRun/goal/plan/todo cursor | 当前工作状态和注意力锚点 | dynamic tail |
| P2 | memory / pinned facts | 背景线索，不可覆盖正文和证据 | memory prefix or current append |
| P2 | external sources | 仅在需要外部/时间敏感信息时获取 | tool observations |

关键裁决：

```text
Task/plan/todo 是工作状态，不是时间连续性的替代品。
Memory 是线索，不是正文历史的替代品。
Evidence index 是定位系统，不是已读取正文的替代品。
Runtime boundary 是本轮边界，不是历史事实。
```

## 6. 目标物理 lane

沿用现有四段式物理模型，不新增第五条 prompt 物理主链。

```text
global_static_prefix
-> provider_visible_context_prefix
-> current_turn_tail
-> never_replay_tail
```

| Lane | 放什么 | cache 预期 | 禁止 |
| --- | --- | --- | --- |
| `global_static_prefix` | 稳定身份、项目规则、工具/能力摘要、provider-independent operating contract | expected read | 放当前用户、当前错误、当前恢复 |
| `provider_visible_context_prefix` | 已 provider success 确认的历史正文、工具观察、证据 refs、memory hints | expected read | 放本轮授权和 current boundary |
| `current_turn_tail` | 本轮新增用户输入、provider protocol append candidates、新证据 refs | write candidate | 要求本轮 cache hit |
| `never_replay_tail` | current runtime boundary、feedback cursor、action horizon、active lease/todo cursor | excluded | provider success 后原样封存 |

## 7. 信息生命周期

### 7.1 Conversation history

```text
api_transcript
-> provider_protocol_history candidate
-> provider request current append
-> provider success
-> provider_visible_context_ledger confirmed
-> physical_prefix_frame confirmed
-> next turn provider_visible_context_prefix replay
```

规则：

- 普通 user/assistant content 必须保留。
- tool round 必须闭合后 replay。
- control protocol tool call 不进入 provider history。
- 当前 precommitted user 必须从 history 中去重，只留 current tail。

### 7.2 Current user input

```text
request facts
-> current_turn_user_context
-> current_turn_tail
-> provider success 后是否封存由 policy 明确决定
```

设计裁决：

- 当前 user input 本轮必须可见。
- 下一轮的 user history 应通过 provider protocol timeline replay，而不是通过 current_turn_user_context 替代。
- current_turn_user_context 不得作为 provider_protocol_history 的替身进入 ledger。

### 7.3 Evidence acquisition

```text
file/editor/attachment/tool observation
-> evidence_index_cursor(ref/hash/range/freshness)
-> if decision needs exact body:
     read_evidence_context exact ref/window
-> provider success seals refs/observations
```

规则：

- 默认注入 index/ref/hash/range，不默认注入大正文。
- 如果 index 显示 missing/stale，action horizon 暴露 read path。
- 已读取窗口要带 path、range、hash、freshness。
- 写文件后相关 evidence 必须标记 stale 或重新读取。

### 7.4 Task / plan / todo

```text
TaskRun / WorkItem
-> Goal / Plan baseline refs
-> Todo baseline + cursor
-> Active execution lease
-> current runtime boundary / attention cursor
```

规则：

- PlanSourceSnapshot 可以引用 inline assistant message、task_plan_context、todo baseline 或 artifact。
- Todo 是执行游标，不是 plan 本体。
- ActiveLease 是当前执行占用，不是永久绑定。
- completed/canceled/superseded/released 不能继续注入 current boundary。
- 没有 active lease 时，不能从旧 plan 正文猜“仍在执行”。

### 7.5 Tool observations

```text
tool_call_id / invocation_id
-> tool observation
-> tool_transcript_delta
-> provider success
-> confirmed replay
```

规则：

- 工具观察是事实，不是最终结论。
- tool message 必须匹配 assistant tool_call_id。
- 孤立 tool 不回放。
- failed tool observation 可以进入 feedback cursor，但不能被渲染成成功事实。

### 7.6 Memory

```text
memory retrieval
-> selected memory hints
-> low authority context
-> exact claim requires verification
```

规则：

- memory 不保存或替代 plan 全文。
- memory 不替代 provider protocol history。
- memory 不决定当前用户意图。
- memory 可提示“应该查哪里”，不能伪造“已经查过”。

### 7.7 Provider transport

```text
tool schema / tool_choice / params / cache key / reasoning config
-> ProviderPayloadManifest
-> hidden transport
```

规则：

- 不进入 agent-visible memory。
- 不进入 provider-visible context ledger。
- 可以影响 cache family，但不能作为正文历史。

## 8. 修复设计

### Phase 1: 恢复精确 provider protocol history

文件：

- `backend/harness/runtime/compiler.py`

改动：

- 重写 `_provider_protocol_hot_messages()`，不再只委托 closed tool round。
- 保留普通 `user(content)`。
- 保留普通 `assistant(content)`。
- 保留带 `reasoning_content` 的 assistant。
- 保留闭合工具轮：`assistant(tool_calls)` 后紧随匹配的 `tool(tool_call_id)`。
- 丢弃孤立 tool、未闭合工具轮、重复 tool_call_id、control protocol tool call。

完成条件：

- `api_transcript` 中的计划书正文能进入 provider request。
- 用户“可以执行 / 继续 / 开始执行”能进入 provider request。
- DeepSeek tool protocol 顺序仍合法。

### Phase 2: 让 provider_protocol_history 成为正确 append candidate

文件：

- `backend/harness/runtime/compiler.py`
- `backend/runtime/context_management/context_segment_policy.py`
- `backend/runtime/context_management/provider_message_replay_contract.py`
- `backend/runtime/context_management/physical_context_assembler.py`

改动：

- `provider_protocol_history` 是 current append candidate，不是 already sealed replay。
- 它需要 byte preservation，但 `already_replayed_from_physical_frame=false`。
- 明确区分：
  - `byte_preserve_provider_message`
  - `physical_frame_replay`
  - `provider_protocol_append_candidate`
- 修正 `cache_scope/cache_role/prefix_tier` 与 append_then_seal 语义一致。

完成条件：

- provider protocol candidate 进入本轮 current append。
- provider success 后进入 ledger/frame。
- 下一轮从 physical frame replay。
- assembler 不因 `provider_protocol_replay=True` 把它忽略。

### Phase 3: 统一 sealability owner

文件：

- `backend/runtime/context_management/context_segment_policy.py`
- `backend/runtime/context_management/provider_visible_context_ledger.py`
- `backend/harness/loop/single_agent_turn.py`

改动：

- 所有可封存判断只调用 `context_segment_policy_is_provider_visible_sealable()` 或其唯一升级版。
- `provider_visible_context_append_candidate_spec()` 不再用本地散条件绕过 sealability。
- followup commit candidate 不能把 volatile/current control/current user 替代为历史。
- 明确禁止 `current_turn_user_context` 作为 provider_protocol_history 替代封存。

完成条件：

- ledger 不再确认错误 current user/context 碎片。
- dynamic tail 永不通过旁路封存。
- 历史正文只来自 provider protocol timeline 或 confirmed provider-visible observations。

### Phase 4: 当前用户去重

文件：

- `backend/harness/entrypoint/runtime_facade.py`

改动：

- `_runtime_history_and_session_context_for_record()` 对 `api_transcript` 同步应用 `_history_without_current_user_request()`。
- 与普通 direct path 的 precommitted user 去重规则一致。

完成条件：

- 修复完整 provider history 后，不会出现当前 user 同时在 history 和 current tail 中重复。

### Phase 5: 信息获取控制面显式化

文件：

- `backend/harness/runtime/dynamic_context/evidence_index_cursor.py`
- `backend/harness/runtime/context_message_producers.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/harness/runtime/dynamic_context/turn_state_attention_context.py`
- `backend/harness/runtime/compiler.py`

改动：

- 将 evidence index 的 missing/stale/exact-read-needed 信息提升为 action horizon 可读信号。
- task_plan_context / task_todo_context 保持 dynamic tail attention，不替代 provider history。
- turn_attention_index 只作为注意力引导，不做 lifecycle authority。
- 当前信息缺口应表达成 agent 可执行的获取指令：

```text
你当前缺少 X 的精确证据。
可用路径：读取 path:start-end / 调用 search / 请求用户确认。
在获取前不要给出最终裁决。
```

完成条件：

- agent 不靠旧摘要猜缺失事实。
- 需要精确信息时能自然选择 read/search/tool。
- prompt 不膨胀成全文证据堆叠。

### Phase 6: Active execution lease，而不是永久 plan binding

候选文件：

- `backend/runtime/turn_memory/*`
- `backend/harness/runtime/request_facts.py`
- `backend/harness/runtime/packet_assembler.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/runtime/output_commit_authority.py`

目标结构：

```text
WorkItem
PlanSourceSnapshot
ExecutionContract
ActiveLease
TodoCursor
RecoveryCheckpoint
```

规则：

- inline plan 用 `api_transcript` message id/hash 绑定，不要求先落成 plan.md。
- todo baseline 可以作为 PlanSourceSnapshot 来源，但 todo 不变成 plan。
- ActiveLease 只在 executing/recoverable/suspended 时注入。
- output commit 成功后 release lease。
- canceled/superseded/completed/released 不注入。

完成条件：

- 用户批准后，agent 看到的是“执行已批准计划”的当前契约。
- 没有 active lease 时，不从旧 plan 文本恢复执行。
- 已完成计划不会继续污染后续回合。

### Phase 7: 修复受影响 session

状态对象：

- `storage/sessions/session-a493d97320c94f70.json`
- `storage/runtime_state/provider_visible_context_ledger/session-a493d97320c94f70.json`
- `storage/runtime_state/physical_prefix_frame_ledger/session-a493d97320c94f70.json`

规则：

- 只以真实 `api_transcript` 为内容来源。
- 作废错误 confirmed frame。
- 重新生成或等待下一轮生成正确 provider-visible/physical frame。
- 不伪造计划、批准或工具观察文本。

完成条件：

- 下一轮 provider payload 包含计划书正文和批准正文。
- 错误 current_turn_user_context 历史碎片不再作为主历史。

## 9. 连接矩阵

| Line | Producer | Payload identity | Consumer | 必须满足 |
| --- | --- | --- | --- | --- |
| time-spine | `api_transcript` | provider message index/message id/hash | `provider_protocol_history` | 不丢普通 user/assistant content |
| protocol-tool | assistant tool_calls | tool_call_id | tool messages | 闭合、连续、无重复 |
| append-seal | current append candidate | item_key/provider hash | provider-visible ledger | 只在 provider success 后确认 |
| frame-replay | confirmed ledger entries | frame_id/ordinal/provider hash | physical assembler | byte-identical replay |
| current-user | request facts | turn_id/user message hash | current tail | 本轮可见，history 去重 |
| evidence-index | file/editor/tool state | path/range/hash/freshness | action horizon/read evidence | 缺失或 stale 时触发获取路径 |
| task-state | TaskRun/plan/todo | work_item/task_run/plan/todo ref | dynamic tail | 注意力引导，不替代 history |
| lease | active execution state | lease_id/work_item_id | runtime boundary | terminal 后 release |
| memory | memory retrieval | memory ref/source/hash | selected hints | 低权威，需验证 |
| transport | provider adapter | manifest ref/transport hash | provider request | hidden，不入 memory |

## 10. 性能设计

### 10.1 不靠丢历史省 token

丢正文会破坏 agent 时间连续性，属于语义故障，不是优化。性能优化必须保持 provider-visible history 的正确性。

### 10.2 prefix 性能来源

```text
global_static_prefix:
  稳定命中

provider_visible_context_prefix:
  confirmed frame byte-identical replay

current_turn_tail:
  本轮新增，正常 miss

never_replay_tail:
  excluded，不参与 expected read
```

### 10.3 evidence 性能来源

- 默认注入 refs/hash/ranges/freshness。
- 精确正文只在当前决策需要时读取。
- read evidence 成功后以 ref/window 进入 append-only history。
- 大正文不永久塞 dynamic tail。

### 10.4 plan/todo 性能来源

- plan 全文已在 provider protocol history 中，不重复长期注入。
- current execution contract 注入短摘要和 refs。
- todo 注入 active item/cursor，而不是每轮重复整个长计划。

### 10.5 cache 健康指标

优先级：

1. expected prefix 是否完整覆盖。
2. `provider_under_read_tokens == 0`。
3. first missing expected prefix identity 为空。
4. 总 hit rate 只能做辅助背景。

## 11. Agent-visible 引导标准

给 agent 的提示必须是可执行角色/边界，不是开发说明。

### 11.1 Current Information Boundary

```text
你需要先判断当前信息是否足够。
如果用户要求的是代码、文件、运行状态、上下文拼接或缓存判断，你必须基于当前可见证据作答。
如果只有摘要、记忆或索引，不能把它当作已经读取的原文。
如果当前证据缺少关键范围，你应选择读取、搜索或询问用户，而不是猜测。
```

### 11.2 Execution Continuity

```text
你可以看到已经发生过的对话历史和当前用户最新输入。
历史用于理解上下文，当前用户输入拥有最高优先级。
如果历史中已经有计划并且用户已经明确批准执行，你应继续执行，不要重新输出计划。
只有当计划冲突、过期、缺少关键条件或用户要求重新计划时，才进入重新计划。
```

### 11.3 Evidence Acquisition

```text
当判断依赖文件、代码、日志、配置或外部事实时，你需要确认是否已有足够精确的证据。
如果只看到文件索引或旧读取窗口，先读取最小必要范围。
如果证据过期或写入后未重新读取，不要把旧观察当作当前事实。
```

### 11.4 Runtime Boundary

```text
当前运行边界只对本轮有效。
旧边界只代表过去，不能作为本轮授权。
你必须在当前允许的动作空间内选择最小充分行动。
```

这些文案应由现有 prompt/context projection 选择性投影，不能变成重复长 prompt。

## 12. 禁止路径

- 用 memory summary 替代 `api_transcript`。
- 用 `current_turn_user_context` 替代普通 user history。
- 用 prompt 口头要求“不要重复写计划”代替修正文历史。
- 把 plan 全文永久塞进 dynamic tail。
- 把 todo 当 plan 本体。
- 让 active lease 不解绑。
- 让 old runtime boundary 作为 current authorization replay。
- 让 provider transport sidecar 进入 agent-visible memory。
- 靠降低测试断言、mock provider payload、删除失败用例制造通过。
- 为兼容旧错误 frame 保留双主链路。

## 13. 验证策略

遵守项目要求：不新增回归测试文件，不用假输出应付验证。

### 13.1 静态审查

```powershell
rg -n "_provider_protocol_hot_messages|_provider_protocol_closed_tool_round_messages|provider_protocol_history" backend/harness/runtime/compiler.py
rg -n "provider_message_replay_metadata|provider_message_byte_preservation_required" backend/runtime/context_management
rg -n "provider_visible_context_append_candidate_spec|context_segment_policy_is_provider_visible_sealable" backend/runtime/context_management backend/harness/loop
rg -n "current_turn_user_context|context_commit_policy|context_replay_policy" backend/harness backend/runtime/context_management
```

### 13.2 编译检查

```powershell
python -m py_compile backend/harness/runtime/compiler.py
python -m py_compile backend/runtime/context_management/context_segment_policy.py
python -m py_compile backend/runtime/context_management/provider_message_replay_contract.py
python -m py_compile backend/runtime/context_management/provider_visible_context_ledger.py
python -m py_compile backend/runtime/context_management/physical_context_assembler.py
python -m py_compile backend/harness/entrypoint/runtime_facade.py
```

### 13.3 provider payload 审计

目标 session：

```text
session-a493d97320c94f70
```

必须看到：

- assistant 计划书正文。
- user 批准/继续/开始执行正文。
- 当前 user 不重复。
- tool round 闭合。
- control protocol tool call 不进入 provider protocol history。
- current runtime boundary 在 never replay tail。

### 13.4 性能审计

必须确认：

- static prefix 和 confirmed provider-visible prefix 是 expected read。
- current tail / never replay tail 不算 expected read。
- first missing expected prefix identity 可回溯到具体 context contract node/edge。
- 恢复正文历史后，token 增量主要来自真实历史，不来自重复 plan/todo 注入。

### 13.5 真实运行

涉及 runtime / 前后端 / SSE / provider payload 时，按项目固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
api base: http://127.0.0.1:8003/api
```

端口占用时先确认是否本项目旧进程；非本项目进程不得擅自关闭。

## 14. 实施顺序

确认后按顺序实施：

1. 修 provider protocol history：恢复普通 user/assistant content。
2. 拆 byte preservation 与 physical sealed replay。
3. 统一 sealability owner，关闭 current context 错封旁路。
4. 修 precommitted current user 去重。
5. 显式化 evidence acquisition / information gap / action horizon。
6. 引入 WorkItem / PlanSourceSnapshot / ExecutionContract / ActiveLease 生命周期。
7. 恢复受影响 session 的 ledger/frame。
8. 做静态审查、py_compile、provider payload 审计和真实运行验证。

如果实施中发现某阶段假设错误，必须暂停并说明偏差，再请求确认。

## 15. 最小验收不变量

```text
api_transcript 是正文事实源
provider_protocol_history 不丢普通 user/assistant content
tool protocol replay 必须闭合
byte preservation 不等于 already sealed physical replay
current_turn_user_context 不是历史替代品
sealability 只有一个 owner
physical_prefix_frame 是下一轮 replay 顺序权威
evidence index 提供 ref/hash/freshness，不伪装成全文证据
缺失/过期信息必须进入 acquisition path
memory 是线索，不是证据或正文历史
task/plan/todo 是 active state，不是时间脊柱
ActiveLease 必须可释放、可替换、可恢复、可终止
dynamic tail 不进入 provider-visible history
provider transport 不进入 agent-visible memory
性能靠 prefix lane、refs、hash、compaction boundary，不靠丢语义正文
```

## 16. System Carrier Capability Audit

本节审查上面的协议是否有真实系统承载能力。审查标准不是“prompt 能不能描述”，而是每条语义线必须能被系统观察、命名、存储、计算、投影、消费、失效和验证。

### 16.1 审查门槛

一条协议线只有同时满足以下条件，才能算 `connected`：

| Gate | 必须证明 |
| --- | --- |
| Observable | 系统能看到真实输入、状态、工具观察或 provider payload，而不是让模型猜 |
| Stable identity | 有稳定 id/hash/ref 贯穿创建、更新、重试、恢复、完成 |
| Store / ledger | 有明确存储或 ledger，不靠临时 prompt 文本维持 |
| Algorithm computable | 有确定算法能算出 freshness、缺口、顺序、权限或生命周期 |
| Projection path | 能进入正确 lane：prefix / current append / never replay tail / hidden transport |
| Consumer | 下游真正读取这个结构，而不是只写在文档里 |
| Terminal / invalidation | completed、released、superseded、stale、missing、failed 能关闭或降权 |
| Verification | 能通过 payload/ledger/frame/manifest 审计证明，不靠语义测试造结果 |

### 16.2 源码证据摘要

| Area | Evidence |
| --- | --- |
| Raw conversation storage | `backend/sessions/__init__.py:297-307` 从 `api_transcript` 加载 provider-visible 历史；`549-567` 追加规范化 API message；`579-584` 在旧 session 缺失时回填；`1441-1467` 按保留 turn 截断 |
| Provider history projection | `backend/harness/runtime/compiler.py:3503-3597` 从 `api_transcript` 生成 `provider_protocol_history`；但 `3614-3672` 只保留闭合工具轮和 reasoning assistant，丢普通正文 |
| Current user dedupe | `backend/harness/entrypoint/runtime_facade.py:480-506` direct path 会对 `api_transcript` 去重；但 `275-337` 的 record helper 只对 public history 去重，未同步处理 `api_transcript` |
| Sealability authority | `backend/runtime/context_management/context_segment_policy.py:365-378` 有统一 sealability 判断；但 `provider_visible_context_ledger.py:155-218` 有本地散条件旁路 |
| Cache policy conflict | `context_segment_policy.py:529-536` 会把非 `never_cache` 的 `CONTEXT_APPEND` 归一成 `session_stable/session`；`compiler.py:4158-4172` 对 current user 写了 volatile，但仍可能被 section 归一抵消 |
| Physical spine | `physical_context_assembler.py:46-128` 定义 static -> confirmed frame -> current append -> tail；`132-154` 排除被标记为 provider replay 的 current append |
| Byte replay contract | `provider_message_replay_contract.py:14-57` 把 physical frame replay 与 provider protocol replay 都归到 byte-preserve 判断，缺少 append candidate 与 sealed replay 的类型分离 |
| Provider payload manifest | `provider_payload.py:111-166` 为 message 建 segment/hash；`243-303`、`328-391` 把 tools/options/response_format/params 作为 transport segment；`621-688` 只把 static 和 confirmed frame 纳入 expected read |
| Evidence state | `file_state_authority.py:92-127` 保存 path/range/hash/coverage；`237-318` 读后刷新、写后 stale；`508-692` 计算 coverage/missing ranges |
| Evidence action signals | `task_state_projector.py:1814-1870` 生成 `file_evidence_decisions`；`1934-2015` 生成 candidate/required read windows；`2108-2188` 生成 read resource state 和 action conditions |
| Exact read reuse | `read_evidence_reuse.py:170-296` 用 scope、current facts、hash/mtime、exact segment 判断 reuse 或 allow read；`native_tools.py:350-420`、`450-530` 对 read_file 接入复用与 artifact 写入 |
| Edit guard | `native_tools.py:1068-1186` 要求当前 exact read window 才允许 edit，说明 evidence freshness 已有执行边界 |
| Active work boundary | `current_work_boundary.py:24-88` 定义 input/decision/receipt；`120-225` 判定 no current work、stale/mismatch、terminal；`runtime_facade.py:1277-1543` 校验 active turn/task run 后才执行控制 |
| Active work context | `active_work.py:47-75` 有 active work model-visible payload；`runtime_facade.py:1741-1820` 只在 running/same-run resumable/paused 时生成 |
| Task plan/todo projection | `turn_state_attention_context.py:69-188` 生成 goal/plan/todo baseline 和 cursor；`dynamic_context/manager.py:469-510` 明确 plan/todo 是 dynamic tail |
| Turn memory | `turn_memory_models.py:55-99` 保存 provider refs、manifest refs、frame id、tool rounds、commit/recovery/release；`turn_memory_store.py:412-520` 有 commit/frame pending、terminal、release tombstone |
| Turn recovery | `turn_memory_recovery_context.py:15-73` 选择未释放恢复候选；`76-88` 排除 released/superseded/terminal |
| Memory hints | `compiler.py:5750-5799` 只暴露 allowlisted memory sections，并写 `requires_verification_before_use=True` |
| Provider transport | `provider_payload.py:860-926` 将 tool schema、request params、tool options、response format 作为 cache/transport contract 统计；`1171-1177` transport 先于 messages 排序，但不作为 agent 正文历史 |

### 16.3 承载能力矩阵

| Protocol line | Observable | Identity | Store / ledger | Algorithm | Projection / consumer | Invalidation | Verdict | Required system work |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `conversation-time-spine` | yes: `api_transcript` | partial: turn/message/hash 可派生，但 provider history source_ref 仍按 index | yes: session `api_transcript` | broken: `_provider_protocol_hot_messages()` 丢普通正文 | broken: `provider_protocol_history` 缺正文，下一轮模型不可见 | compaction boundary exists | `partial` | Phase 1: 重写 provider protocol hot projection，保留普通 user/assistant，工具轮仍按闭合规则 |
| `current-user-present` | yes: request facts/current user context | yes: turn_id/message hash | yes: current tail | partial: direct path 去重存在，record helper 未同步 `api_transcript` 去重 | current tail 可见 | weak: current user 可被 append policy 误封存 | `partial` | Phase 4: 对所有 session_context 入口同步 current user dedupe；Phase 3: current user 不得作为历史封存 |
| `provider-seal-frame` | yes: provider request + manifest | yes: segment_id/item_key/provider hash/frame_id | yes: provider-visible ledger + physical prefix frame ledger | partial: sealability owner 分裂，byte replay 类型混用 | mostly: assembler 有固定物理顺序，provider manifest 有 expected-read 统计 | partial: confirmed/rejected frame 有校验，append candidate 类型不清 | `partial` | Phase 2/3: 拆 `byte_preserve_provider_message`、`provider_protocol_append_candidate`、`physical_frame_replay`；ledger 只调用唯一 sealability owner |
| `tool-observation` | yes: assistant tool_calls + tool messages + observations | yes: `tool_call_id`、round_id、observation_ref | yes: tool transcript、TurnMemory.tool_rounds、provider frame | mostly: 闭合工具轮识别、round order、orphan drop | yes: provider prefix 排序和 payload diagnostics 消费 | yes: unclosed/orphan 不回放，failed observation 可作为反馈 | `mostly connected` | 保留工具轮规则，但禁止把工具轮筛选器当作普通正文历史筛选器 |
| `evidence-acquisition` | yes: file state、read observations、search recommendations | yes: path/range/hash/mtime/artifact_ref | yes: FileStateAuthorityStore、read observation artifact | mostly: freshness、coverage、missing ranges、reuse/allow read 都可计算 | partial: evidence index/read refs 可投影，但 action horizon 不够强 | yes: write/edit 后 stale；edit guard 阻止旧证据 | `partial / strong base` | Phase 5: 建 `EvidenceAcquisitionHorizon`，把 required/stale/missing 转为当前行动边界，不只做上下文提示 |
| `active-plan-execution` | partial: TaskRun、active work、todo cursor | partial: task_run_id、active_turn_id、plan_baseline_ref、todo_baseline_ref | partial: TaskRun/runtime objects/active turn registry | partial: current work boundary 能判定可控工作，但缺 plan source 生命周期 | partial: dynamic tail 投影 plan/todo，不替代 history | partial: task terminal/active turn release 存在，plan source release 不完整 | `partial` | Phase 6: 新增或固化 `WorkItem / PlanSourceSnapshot / ExecutionContract / ActiveLease`，支持 inline plan 不落文档也能绑定和解绑 |
| `inline-plan-source` | yes: assistant plan 正文在 `api_transcript` | missing: 没有显式 PlanSourceSnapshot 对 message id/hash 建源 | missing: todo/plan contract 可投影，但不是计划源账本 | missing: 没有“批准正文 -> plan source -> execution contract”的确定算法 | missing: agent 主要靠正文历史理解批准 | missing: no source release/supersede lifecycle | `missing` | 允许未落成文档的 plan 以 `api_transcript` assistant message id/hash 作为 PlanSourceSnapshot；批准后生成 ExecutionContract/ActiveLease，完成后 release |
| `memory-hints` | yes | partial: section/source ref | yes: runtime memory context | yes: allowlist + verification flag | yes: selected memory context | partial: memory selection append/seal，但不能证明每条 fact freshness | `connected as low-authority` | 保持低权威：memory 不可替代正文、证据、当前用户和 active lease；需验证的 claim 进入 acquisition path |
| `turn-recovery` | yes: TurnMemory records | yes: turn_id/turn_run_id/request refs/frame id | yes: turn memory store + tombstones | mostly: recoverable candidate selection | yes: recovery context 投影到 volatile payload | yes: released/superseded/terminal 排除 | `connected for recovery` | 只用于未完成 turn 的恢复，不得用来补正文历史或恢复已释放 plan |
| `provider-transport` | yes: tools/options/params/response_format | yes: segment/hash/transport_contract_hash | yes: ProviderPayloadManifest | yes: transport contract/cache boundary | yes: model_gateway/provider payload 消费 | yes: never_cache/non-token/family selector | `connected` | 保持 hidden transport，不进入 memory/history；用 manifest 审计 DeepSeek cache 与 tool schema drift |
| `semantic-guidance` | partial: environment prompt controller 可根据 active work/memory/evidence 触发 guidance | weak: reason refs 多是状态触发，不是信息缺口对象 | partial: prompt mount/profile | partial: 触发原因存在，但缺统一 acquisition horizon | partial: agent 看见 guidance，但未必有强制行动边界 | weak: prompt guidance 本身无生命周期 | `partial` | 把“当前缺什么信息”从 prompt 文案提升为结构化 action horizon；prompt 只解释如何消费该结构 |

### 16.4 架构裁决

当前系统已经有较成熟的骨架，但断在三个关键接口：

1. `api_transcript` 到 `provider_protocol_history` 的投影接口断裂，导致正文时间脊柱缺失。
2. `CONTEXT_APPEND`、sealability、provider-visible ledger、physical frame replay 的权威没有统一，导致 current/user/dynamic 类片段可能被错误提升。
3. evidence、plan、todo、active work 都有局部 carrier，但缺少统一的“信息获取和执行占用”生命周期对象，导致 agent 容易把旧计划、旧摘要或旧游标当作当前认知边界。

因此修复不应新增一套平行上下文系统，而应把现有系统收束成一条自然链：

```text
api_transcript
-> provider_protocol_append_candidate
-> provider success confirmed
-> provider_visible_ledger entry
-> physical_prefix_frame replay
-> provider payload manifest audit
```

同时把当前执行态收束为另一条短生命周期链：

```text
PlanSourceSnapshot
-> ExecutionContract
-> ActiveLease
-> TodoCursor / EvidenceAcquisitionHorizon
-> completed | released | superseded | canceled
```

这两条链不能互相替代：conversation timeline 负责“过去真实发生过什么”，ActiveLease 负责“现在是否正在执行某个已批准工作”。

### 16.5 未落文档 plan 的绑定原则

未落成 `plan.md` 的计划书仍然是正文事实，不是无主文本。它的自然 source 应是 provider-visible conversation message：

```text
PlanSourceSnapshot {
  source_type: "inline_assistant_message",
  source_message_ref: api_transcript.message_id | turn_id:index,
  source_content_hash: sha256(provider_message),
  approved_by_user_message_ref: api_transcript.user_message_id | turn_id:index,
  approved_at_turn_id: current_turn_id,
  plan_visibility: "conversation_timeline",
  artifact_ref: "",
  authority: "runtime.plan_source_snapshot"
}
```

如果后续生成 todo，则 todo 只能作为执行游标：

```text
TodoCursor {
  todo_baseline_ref,
  active_item_ref,
  cursor_hash,
  derives_from_plan_source_ref,
  authority: "runtime.todo_cursor"
}
```

Todo 不能反向成为计划本体，也不能在 plan source released 后继续维持执行绑定。

### 16.6 ActiveLease 生命周期要求

`ActiveLease` 必须是短生命周期执行占用，不是永久绑定。

| State | 可见性 | 行为 |
| --- | --- | --- |
| `proposed` | 不进入 execution boundary | 等用户批准或 agent 继续澄清 |
| `active` | current runtime boundary / dynamic tail | agent 应继续执行，不重写计划 |
| `paused` | current work boundary | 可恢复，但必须通过 current work control |
| `recoverable` | recovery boundary | 只暴露恢复选项和缺口 |
| `completed` | 不进入 current boundary | 只保留正文历史和结果引用 |
| `released` | 不进入 current boundary | 写 tombstone / release reason |
| `superseded` | 不进入 current boundary | 新 plan source/lease 替代旧 lease |
| `canceled` | 不进入 current boundary | 后续 turn 不再继续执行 |

绑定与解绑必须有同一套 owner。建议 owner 放在 current work / task runtime 边界，而不是 memory、prompt producer 或 ledger：

```text
request facts
-> plan approval detector / task contract intake
-> PlanSourceSnapshot
-> ExecutionContract
-> ActiveLease
-> current_work_boundary_receipt
-> compiler dynamic tail
```

Provider-visible ledger 只封存 provider-visible 事实，不负责决定 lease 是否仍 active。

### 16.7 EvidenceAcquisitionHorizon

现有 evidence 系统已经能算出可复用证据、缺失范围和 stale 状态，但它需要一个统一投影对象进入 agent 当前行动空间：

```text
EvidenceAcquisitionHorizon {
  required_reads: [
    {path, start_line, line_count, reason, source_decision_ref}
  ],
  candidate_reads: [
    {path, start_line, line_count, read_condition}
  ],
  stale_evidence: [
    {path, covered_ranges_ref, repair_instruction}
  ],
  reusable_exact_refs: [
    {path, start_line, end_line, exact_artifact_ref, usage_condition}
  ],
  authority: "runtime.evidence_acquisition_horizon"
}
```

投影位置：

| Payload | Lane |
| --- | --- |
| evidence refs/hash/coverage | `current_turn_tail` then seal if provider-visible and stable |
| current missing/stale action horizon | `never_replay_tail` |
| exact file body | only via read_file/tool observation, not permanent dynamic prompt blob |

这样 agent 的信息获取能力在时空认知中的位置是：位于最终判断和工具选择之前，权威高于 memory summary，低于当前用户指令，但能阻止基于过期证据给最终裁决。

### 16.8 性能边界

承载能力补强不能破坏 prefix 性能：

1. Conversation 正文进入 provider protocol append candidate，provider success 后由 physical frame replay。性能来自 confirmed frame 的 byte-identical replay。
2. Evidence 默认注入 ref/hash/range/freshness；exact body 只通过 read_file 最小窗口获取。
3. ActiveLease/current boundary/action horizon 进入 `never_replay_tail`，不参与 expected read。
4. Memory 保持 low-authority hints，不复制 plan 全文，不替代 provider history。
5. Provider transport 继续作为 manifest/transport segment，不进入 agent-visible memory。

### 16.9 修复计划调整

前 1-4 阶段必须先做，因为它们修复正文时间脊柱和封存权威。第 5-6 阶段不应做成 prompt 增强，而应补系统 carrier：

| Phase | 调整后目标 |
| --- | --- |
| Phase 1 | 恢复普通 user/assistant provider protocol history，同时保留工具轮闭合校验 |
| Phase 2 | 把 append candidate 与 physical frame replay 分型，byte preservation 只是序列化要求，不代表已 sealed |
| Phase 3 | sealability 只能由 policy owner 决定；current user、runtime control、dynamic tail 必须显式不可封存 |
| Phase 4 | 所有 session_context 入口同步 current user dedupe，包括 record helper |
| Phase 5 | 新增 EvidenceAcquisitionHorizon，把 missing/stale/required read 从提示词提升为行动边界 |
| Phase 6 | 新增或固化 PlanSourceSnapshot / ExecutionContract / ActiveLease，支持 inline plan 绑定、完成解绑、supersede、release |
| Phase 7 | 恢复受影响 session，只从真实 `api_transcript` 重建，不伪造计划或批准 |

最小成熟标准：

```text
agent 不是靠“记得有计划”继续执行
agent 是看到：
1. provider history 中确实有计划正文和批准正文
2. current work boundary 中确实有 active execution lease
3. action horizon 中确实没有阻止继续执行的缺失/过期证据
```

三者缺一不可。
