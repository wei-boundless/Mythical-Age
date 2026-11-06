# Four Segment Physical Context Closure Algorithm Repair Plan

创建日期：2026-07-01

状态：待确认实施。本文是对最新缓存命中异常、旧工具上下文拼接形态、`physical_prefix_frame` 语义和四段物理模型闭合算法的结构性修复计划。按项目规则，本计划触达 runtime / context / provider payload / prompt accounting 主链路，确认后再一次性实施。

## 1. 结论

四段物理模型已经做实，问题不在模型本身，而在闭合算法仍然沿用历史增量 frame 和 provider protocol replay 逻辑。当前链路把旧工具上下文发给了 provider，但没有把它作为“第二段 confirmed old context”原封不动封存和复用，导致本地 cache accounting 把大量旧上下文识别成 volatile / excluded。

正确算法必须直接修改现有主链路，不新增 V2，不再保留两套正常路径：

```text
第 1 段 static_prefix
  每次稳定生成，作为 provider payload 前缀第一段。

第 2 段 confirmed_old_context
  来自上一次 provider 成功闭合后封存的完整旧上下文快照，下一次原封不动复制。

第 3 段 current_append
  本次新产生、可在 provider 成功后封存的上下文，包括工具调用、工具结果、用户补充等。

第 4 段 dynamic_tail
  每回合刷新，只服务当前请求，永不封存。
```

闭合不变量：

```text
provider_success_closeout:
  next.confirmed_old_context
  = current.confirmed_old_context + current.current_append

confirmed_old_context_byte_invariant:
  once confirmed_old_context is persisted
  replay must be byte-for-byte identical
  no rewrite, no summary, no re-render, no reclassification, no reorder

static_prefix 不进入 confirmed_old_context
dynamic_tail 不进入 confirmed_old_context
current_append 在本次 request 中不可 cache-read
current_append 在 provider success 后成为下一次 confirmed_old_context 的后缀
任何新的 memory / signal / guidance 只能追加到 current_append 或 dynamic_tail
```

## 2. 当前证据

最新会话：`session-de6d5e6638ca4e2b`

最新请求：`providerreq:rtpacket:turn:session-de6d5e6638ca4e2b:1:single_agent_turn:1:tool-followup:4`

provider bus 结果：

```text
cache_status = hit
prompt_tokens = 99,892
cached_tokens = 66,944
miss_tokens = 32,948
provider_under_read_tokens = 0
prefix_health.verdict = covered
physical_cache_spine_status = stable
```

manifest 分段：

| 类别 | 物理 lane | tokens | 说明 |
| --- | --- | ---: | --- |
| 旧 `tool_transcript_delta` | `provider_visible_context_prefix` | 34,028 | 已拼入 provider payload，但仍标为 volatile/excluded |
| 旧 `single_agent_turn_tool_call` | `provider_visible_context_prefix` | 1,234 | 已拼入 provider payload，但仍标为 volatile/excluded |
| 当前轮 `read_file` 结果 | `current_turn_tail` | 30,752 | 本轮新增，按设计不能 cache-read |
| `dynamic_projection` | `never_replay_tail` | 2,253 | 动态尾巴，永不封存 |
| `native_tool_binding_schema` | `provider_tool_schema_prefix` | 7,062 | tools sidecar，显示口径仍需单独修正 |

这说明：

```text
旧工具上下文没有丢，也不是没有拼接。
它被拼接为 provider protocol replay，而不是 confirmed old context 第二段。
```

provider 实测 `cached_tokens=66,944` 已明显高于当前本地 expected message prefix 约 `33k` provider-scaled tokens，说明 provider 侧很可能已经读取了旧上下文缓存；本地统计没有承认这部分为 confirmed second segment。

### 2.1 代码审查结论

本节是按真实代码链路补充的审查结果，用于修正本计划的实施边界。

#### 2.1.1 中断使用 TurnMemory 热缓存，不写 prefix frame

代码证据：

| 文件 | 位置 | 结论 |
| --- | --- | --- |
| `backend/harness/runtime/single_agent_host.py` | `record_chat_turn_run_runtime_interruption()` / `_close_turn_memory_with_interruption_package()` | runtime interruption 会把 TurnRun 标为 `interrupted`，并 patch `TurnMemory(status=terminal, handoff_state=interrupted_turn_memory_package)` |
| `backend/runtime/turn_memory/turn_memory_store.py` | `append_provider_request_ref()` / `record_provider_result()` / `record_tool_round()` | TurnMemory 保存 provider refs、manifest refs、frame ref、tool round refs、assistant draft/final refs、current append hash |
| `backend/harness/loop/single_agent_turn.py` | `_ensure_turn_memory_started()` / `_patch_turn_memory()` | 每个 single-agent turn 启动时创建 TurnMemory，并记录当前 user input 对应的 packet ref / append hash |

结论：

```text
TurnMemory 是未完成 turn 的热缓存 / 工作记忆包。
用户中断后不能伪造 prefix frame。
下一轮必须从 TurnMemory 输出热缓存生成不完整上一轮输出记忆包。
```

#### 2.1.2 中断输出热缓存当前落入 dynamic tail，不是“上一轮输出热缓存记忆”

代码证据：

| 文件 | 位置 | 当前行为 |
| --- | --- | --- |
| `backend/runtime/turn_memory/turn_memory_prior_work.py` | `build_prior_work_memory_context()` | 只选择 `status=terminal + handoff_state=interrupted_turn_memory_package` 的 TurnMemory，产出 `runtime.turn_memory.prior_work_context` |
| `backend/harness/entrypoint/runtime_facade.py` | 构造 `prior_work_memory_context` | active work 不存在时，把 prior work 放入 `session_context["prior_work_memory_context"]` |
| `backend/harness/runtime/compiler.py` | `_prior_work_memory_model_visible_payload()` | 把 prior work 投影为模型可见的 `prior_work_memory_context` |
| `backend/harness/runtime/compiler.py` | `dynamic_payload = {...dynamic_payload, ...volatile_runtime_payload}` | prior work 被合入 `dynamic_payload` |
| `backend/harness/runtime/compiler.py` | `dynamic_projection` + `_current_runtime_tail_metadata()` | `context_cache_section=DYNAMIC_TAIL`、`context_replay_policy=current_dynamic_tail_only`、`context_commit_policy=never_commit` |
| `backend/runtime/context_management/physical_context_assembler.py` | `_split_current_tail_specs()` | `DYNAMIC_TAIL` 被放入 `never_replay_tail` |

结论：

```text
当前 prior_work_memory_context 能让 agent 在下一轮看到热缓存事实，
但它物理上属于 dynamic_tail / never_replay_tail。
它不会作为 current_append 进入 provider-visible append ledger，
也不会在下一次 provider success 后晋升为 confirmed_old_context。
```

这是和目标语义不一致的真实断点：下一轮需要从上一轮输出中取记忆；如果上一轮中途中断，没有完整持久化输出，就应由 TurnMemory 输出热缓存生成一个“不完整上一轮输出记忆包”，并附带中断信号。这个记忆包应作为下一轮的 provider-visible current append 输入，而不是混在永不封存的动态尾巴里。

#### 2.1.3 task/commit recovery 与中断 prior work 没有混线

代码证据：

| 文件 | 位置 | 结论 |
| --- | --- | --- |
| `backend/runtime/turn_memory/turn_memory_recovery_context.py` | `_turn_memory_record_is_recovery_candidate()` | 只选择 `commit_pending` / `frame_pending` 或对应 commit_state |
| `backend/runtime/turn_memory/turn_memory_recovery.py` | `decide_turn_memory_recovery()` | commit 失败走 `retry_commit`，frame promotion 失败走 `retry_frame_promotion` |
| `backend/runtime/turn_memory/turn_memory_prior_work.py` | `_turn_memory_record_is_prior_work_candidate()` | 中断 prior work 只选 `terminal + interrupted_turn_memory_package` |

结论：

```text
task/commit recovery 与普通中断后的热缓存 prior work 是两条不同语义。
修复时不能把 prior_work_memory_context 改成 recovery action。
```

#### 2.1.4 prefix frame 只在 provider success 后写入，但当前不是完整 second segment 快照

代码证据：

| 文件 | 位置 | 当前行为 |
| --- | --- | --- |
| `backend/runtime/model_gateway/model_runtime.py` | `_finish_prompt_accounting()` | provider error 只写 failed；provider success 才调用 `_confirm_provider_visible_append_success()` 和 `_confirm_physical_prefix_frame_success()` |
| `backend/runtime/model_gateway/model_runtime.py` | `_confirm_physical_prefix_frame_success()` | 从 provider success accounting 中取 current append confirmations，然后调用 `append_physical_prefix_frame_from_provider_success()` |
| `backend/runtime/context_management/physical_prefix_frame_ledger.py` | `append_physical_prefix_frame_from_provider_success()` | 读取 latest previous frame 只用于 `previous_frame_id` lineage |
| `backend/runtime/context_management/physical_prefix_frame_ledger.py` | `_frame_source_segments()` | frame 正文来自当前 provider payload 的 `physical_cache_spine.segment_ids` + confirmed current append indexes |
| `backend/runtime/context_management/physical_context_assembler.py` | `_frame_replay_specs()` | replay 时只取 frame 中 `physical_prefix_lane=provider_visible_context_prefix` 的 message segment |

结论：

```text
prefix frame 的写入触发是正确的：只有 provider success。
但 frame 内容构造还不是显式的：
  previous_confirmed_old_context + current_append
完整 second segment 快照。
它依赖当前 payload 已经怎样 replay 旧上下文。
frame 里还可能保留 static / tool sidecar 等缓存脊柱噪声，
虽然 assembler replay 会过滤非 provider_visible_context_prefix message。
```

#### 2.1.5 follow-up 仍有 provider_protocol_replay 热路径

代码证据：

| 文件 | 位置 | 当前行为 |
| --- | --- | --- |
| `backend/harness/loop/single_agent_turn.py` | `_single_agent_turn_followup_prompt_payload()` | follow-up 从 `base_segment_plan + model_messages` 重新构造 specs，再进入 context pipeline |
| `backend/harness/loop/single_agent_turn.py` | `_single_agent_turn_followup_base_message_spec()` | 非当前 tool round 的 base message 走 `provider_protocol_prefix_replay_policy()` |
| `backend/runtime/context_management/followup_context_rebase.py` | `provider_protocol_prefix_replay_policy()` | 把旧 base context 标成 `CONTEXT_MEMORY_PREFIX + provider_protocol_replay` |

结论：

```text
旧上下文显示为 provider protocol replay，不是单纯 UI 命名问题。
follow-up 热路径仍然用 provider message prefix preservation 重新解释旧上下文。
目标结构应把它降级为诊断 / degraded replay，
正常旧上下文只从 confirmed prefix frame 进入第二段。
```

## 3. 当前错误算法

当前实际路径：

```text
static_prefix
+ latest physical frame 的局部 replay
+ follow-up base 中的 provider_protocol_replay
+ current tool round append
+ dynamic tail
```

主要断点：

| 断点 | 文件 | 当前行为 | 问题 |
| --- | --- | --- | --- |
| provider protocol replay 热路径 | `backend/runtime/context_management/followup_context_rebase.py` | 旧 follow-up base 被标为 `provider_protocol_prefix_replay` | 旧上下文被重新解释为 protocol replay，而不是读取 confirmed frame |
| frame 只保存增量 | `backend/runtime/context_management/physical_prefix_frame_ledger.py` | `_frame_source_segments()` 取 physical spine included 段 + current append | frame 不是完整第二段，只是增量封存块 |
| assembler 只读 latest frame | `backend/runtime/context_management/physical_context_assembler.py` | `latest_confirmed_physical_prefix_frame()` 后只 replay latest frame 内的 message | 如果 frame 是增量，旧上下文必然要靠其他路径重拼 |
| cache accounting 不承认旧工具第二段 | `backend/runtime/prompt_accounting/cache_planner.py` | expected read 只按当前 physical cache spine message prefix 算 | 旧工具上下文落入 non-cache payload / volatile 展示口径 |
| sidecar 口径混合 | `backend/runtime/prompt_accounting/cache_planner.py` | `native_tool_binding_schema` 进 physical spine，但 expected read scope 写 provider message prefix | tools sidecar 和 message prefix 的账本口径混杂 |

## 4. 目标算法

### 4.1 请求组装

provider payload 的主顺序必须只有一个：

```text
provider_payload =
  static_prefix
  + confirmed_old_context
  + current_append
  + dynamic_tail
```

其中：

```text
static_prefix:
  来源：本轮稳定系统、工具能力、环境、项目约束等
  权威：ContextSegmentPolicy + PhysicalContextAssembler
  cache 语义：provider_global 或 session stable
  封存：不进入 confirmed_old_context

confirmed_old_context:
  来源：PhysicalPrefixFrameLedger.latest_confirmed_frame
  权威：PhysicalPrefixFrameLedger
  cache 语义：expected_read
  封存：已封存，下一轮按 provider message bytes 原样复制，一个字都不能变

current_append:
  来源：本轮 provider-visible append candidates，包括当前用户输入、当前工具观察、当前证据、记忆选择、以及中断场景下从 TurnMemory 输出热缓存生成的不完整上一轮输出记忆包
  权威：ProviderVisibleAppendLedger + PhysicalContextAssembler
  cache 语义：write_candidate，本轮不 expected_read
  封存：provider success 后追加进下一帧 confirmed_old_context

dynamic_tail:
  来源：runtime control、permission summary、当前请求控制信号等
  权威：DynamicContext / Runtime packet assembly
  cache 语义：excluded
  封存：永不封存
```

### 4.2 provider success 闭合

provider 成功后，闭合算法必须按真实 provider message 顺序复制：

```text
previous_confirmed_old_context = latest_confirmed_frame.messages
current_append_messages = current_request.current_append.messages

next_confirmed_old_context =
  copy_exact(previous_confirmed_old_context)
  + copy_exact(current_append_messages)
```

不允许：

```text
从自然语言 marker 重新解析旧上下文
从 follow-up base 重新构造旧工具记录
重新渲染 / 摘要 / normalize 已确认旧上下文
重新分类已落地旧上下文来改变其 bytes 或顺序
把 dynamic tail 放入 frame
把 static_prefix 混入 confirmed_old_context
把失败/中断请求的 current_append 写入 confirmed frame
```

### 4.3 下一轮输出记忆源选择

```text
normal completed previous work:
  上一轮 provider success + output commit + frame promotion 完成
  下一轮从持久化输出 / confirmed prefix frame 中读取已完成记忆
  这些内容进入 confirmed_old_context

provider failure:
  不产生新的 confirmed frame
  保留 previous confirmed frame
  未确认 current_append 仍属于 TurnMemory 输出热缓存
  若后续需要继续，只能由 TurnMemory 生成不完整上一轮输出记忆包
  不晋升为第二段

用户中断 / agent stopped:
  中断使当前 turn run 不再继续占用 active lifecycle
  但该 turn 没有完成 provider success / output commit / frame promotion
  TurnMemory 作为输出热缓存保存未完成工作中的用户输入、工具观察、草稿、refs、append hash
  下一条用户输入开启新的 ordinary turn
  新 turn 从 TurnMemory 输出热缓存生成 previous_incomplete_output_memory
  同时生成 state_signal_evidence
  previous_incomplete_output_memory 作为下一 turn 的 current_append 来源
  不 resume 旧 turn
  不把 TurnMemory 输出热缓存伪装成 provider-confirmed 第二段
  若 provider 未成功返回，不产生新的 confirmed frame
  未确认 append 不写入 confirmed_old_context

网络断流但 provider 已成功:
  后端如能拿到 provider success 和 usage，则正常闭合
  若后端无法确认 provider success，则不能伪造 confirmed frame
```

因此这里的核心不是新增一套 prefix 权威，而是下一轮输出记忆源选择：

| 记忆源 | 来源 | 作用 | 下一 turn 位置 | cache 语义 |
| --- | --- | --- | --- | --- |
| 持久化上一轮输出记忆 | provider success + output commit + frame promotion 后确认过的 provider-visible message bytes / committed output refs | 给下一轮提供完整、已完成、可缓存的旧上下文 | 第 2 段 `confirmed_old_context` | expected-read，可作为稳定物理前缀 |
| TurnMemory 输出热缓存 | 未完成 turn 中的用户输入、工具观察、草稿、refs、append hash、checkpoint | 在 turn 中断或失败时生成“不完整上一轮输出记忆包”，让下一轮知道之前做到哪里以及它不完整 | 第 3 段 `current_append` 的 previous incomplete output memory | write-candidate / request-local；下一轮 provider success 后才可被持久化 |

用户中断不是“恢复同一 turn”，也不是写入持久化 prefix frame。它的正确语义是：

```text
turn_n interrupted before completion
-> TurnMemory output hot cache keeps unfinished output memory
-> next user input starts turn_(n+1)
-> runtime builds previous_incomplete_output_memory from TurnMemory
-> runtime records state_signal_evidence
-> compiler projects it as current_append input for turn_(n+1)
-> dynamic tail renders guidance from state_signal_evidence
```

这个不完整输出记忆包可以让 agent 继续理解之前已经做过的工具观察、草稿、约束和部分工作；中断信号告诉 agent 这些内容不是完整最终输出。它仍是从热缓存抽取出来的新 turn 上下文输入；它不能绕过 provider success 写入 `confirmed_old_context`。

dynamic tail guidance 的 agent-facing 表达不应暴露 runtime/turn 实现细节，应表达为：

```text
上一段工作被中断，以下是不完整的工作记忆。
这些内容可能包含已完成的工具观察、临时草稿、尚未收尾的判断和约束。
请把它作为当前请求的背景继续判断，不要假设它已经是最终结论。
```

### 4.4 状态信号证据与动态尾巴指引

状态需要标准化为两层，不能混在同一个 payload 里：

```text
state_signal_evidence:
  当前 turn 的结构化证据
  只描述发生了什么
  不写 agent 指令
  可作为 current_append facts 随本轮 provider success 被封存

dynamic_tail_guidance:
  当前 turn 的解释指引
  根据 state_signal_evidence 的类型生成
  告诉 agent 如何理解当前状态
  永远不封存，不进入 confirmed_old_context
```

也就是说，`state_signal_evidence.signal_type=previous_output_interrupted` 本身是当前 turn 证据；“上一段工作不完整，请不要当作最终输出”是动态尾巴指引。前者可以和 previous incomplete output memory 一起作为 current append facts 被本轮 provider 看见；后者只在当前请求中引导 agent，不进入持久化记忆。

状态信号标准化表：

| signal_type | signal evidence 内容 | dynamic tail guidance | 是否进入 current_append | 是否进入 dynamic_tail |
| --- | --- | --- | --- | --- |
| `previous_output_interrupted` | interruption code、event ref、previous turn refs、incomplete output memory refs、tool/draft refs | 上一段工作不完整；只能作为背景和部分证据；不要假设它是最终结论；根据当前用户输入重新判断下一步 | 是，作为 previous incomplete output memory 的证据 | 是，生成解释指引 |
| `provider_failure_unconfirmed` | provider request ref、failure reason、unconfirmed append hash | 上一段请求没有 provider 成功确认；不要把未确认内容当作已持久化输出 | 是，若需要继续当前工作 | 是 |
| `commit_pending` | assistant final ref、commit state、pending commit reason | 已有 final ref，优先修复提交边界；不要重新生成同一最终输出 | 否，属于 repair evidence | 是 |
| `frame_pending` | frame promotion ref、provider success ref、pending frame reason | provider 已成功但 frame promotion 未完成；优先修复 frame promotion，不要重跑模型 | 否，属于 repair evidence | 是 |
| `normal_completed_output` | committed output ref、confirmed frame id、provider success ref | 无特殊中断指引；按正常已完成历史读取 | 已在 confirmed_old_context | 否 |

实现时必须满足：

```text
signal evidence != guidance text
current_append facts != dynamic_tail guidance
interruption signal can be sealed only as evidence attached to incomplete output memory
guidance text is always current request only
```

## 5. 权威边界

| 模块 | 目标职责 | 禁止事项 |
| --- | --- | --- |
| `context_segment_policy.py` | 给候选 spec 赋予 section、生命周期、可封存语义 | 不决定最终物理顺序，不修复缺失 frame |
| `provider_visible_append_ledger.py` | 记录本轮可封存 current append 候选及 confirmation identity | 不拥有旧上下文重放权威 |
| `physical_prefix_frame_ledger.py` | provider success 后保存完整 confirmed_old_context 快照及 provider message bytes | 不保存半截增量 frame 作为正常主链路；不重写、摘要、normalize 已确认旧上下文 |
| `physical_context_assembler.py` | 唯一四段拼接点；对 confirmed_old_context 只做 byte-for-byte replay | 不从 protocol replay 重建旧上下文；不改变已确认旧上下文任意字符 |
| `followup_context_rebase.py` | 只处理异常恢复或无 confirmed frame 的 protocol replay 诊断 | 不再作为正常热路径旧上下文来源 |
| `provider_payload.py` / serializer | 保留真实 provider message bytes 和 manifest identity | 不重新分类 confirmed second segment 来改变 bytes / order |
| `cache_planner.py` / `provider_cache_bus.py` | 只读 manifest + provider usage 做统计 | 不反向决定上下文归属 |
| `turn_memory_store.py` / `turn_memory_prior_work.py` | 从未完成 / 中断 turn 的输出热缓存中生成 previous incomplete output memory 包 | 不确认 provider frame，不 resume 旧 turn，不拥有持久化 prefix cache 权威 |
| `compiler.py` | 把 previous incomplete output memory 投影为新 turn 的只读 current_append facts，并附带 state signal evidence | 不扫描 TurnMemoryStore，不把热缓存输出记忆放进 dynamic tail 或 confirmed second segment |
| `turn_state_guidance` / prompt wiring | 根据标准化 state signal 生成动态尾巴解释指引 | 不保存事实，不重写 signal，不进入 current_append 或 confirmed frame |

## 6. 连接线矩阵

| line_id | 触发 | producer | payload identity | authority | transport/store | consumer | 终态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `static-to-payload` | 每次 provider request | static context producers | content hash + context contract ref | ContextSegmentPolicy | message specs | PhysicalContextAssembler | 第 1 段 |
| `frame-to-old-context` | provider request assembly | PhysicalPrefixFrameLedger | frame_id + segment ordinal + provider message hash | PhysicalPrefixFrameLedger | `physical_prefix_frame_ledger/*.json` | PhysicalContextAssembler | 第 2 段原样复制 |
| `append-to-current` | 工具结果/用户补充/可封存上下文 | ProviderVisibleAppendLedger | entry_index + item_key + provider_visible_hash | ProviderVisibleAppendLedger | append ledger metadata | PhysicalContextAssembler | 第 3 段本轮发送 |
| `tail-to-request-only` | 每轮 runtime assembly | DynamicContext / runtime packet | request id + validity scope | RuntimeStartPacket | message specs | PhysicalContextAssembler | 第 4 段本轮发送，永不封存 |
| `success-to-frame` | provider success | ModelRuntime | request id + response ref + provider message hashes | PhysicalPrefixFrameLedger | confirmed frame ledger | 下一次 assembler | 二三段合并为下一次第 2 段 |
| `failure-no-frame` | provider failure / unconfirmed interruption | ModelRuntime | request id + failure reason | PhysicalPrefixFrameLedger | diagnostic only | 下一次 assembler | 继续使用旧 frame |
| `interruption-hot-cache-to-output-memory` | 用户中断 / runtime interruption | SingleAgentRuntimeHost + TurnMemoryStore | session_id + turn_id + interruption event id + checkpoint hash | TurnMemory 输出热缓存 | `TurnMemory` unfinished output refs / checkpoint | RuntimeFacade / compiler | 下一 turn 开新 turn，从输出热缓存生成 previous incomplete output memory |
| `incomplete-output-memory-to-current-append` | 下一条用户输入启动新 turn | `turn_memory_prior_work.build_prior_work_memory_context()` | previous_turn_id + current_append_hash + tool refs + provider refs + interruption signal | TurnMemory output memory projection | `session_context["prior_work_memory_context"]` -> previous incomplete output memory message spec | compiler / PhysicalContextAssembler | 作为 current_append facts 发送；provider success 后才进入下一帧 confirmed old context |
| `state-signal-to-guidance` | current turn 有 state signal | compiler / prompt wiring | signal_type + signal_ref + validity_scope | Turn state guidance selector | dynamic tail message spec | agent model request | 当前请求解释指引，永不封存 |
| `frame-to-cache` | provider usage 返回 | PromptAccounting | frame segment ids + provider usage | ProviderCacheBus | provider cache bus jsonl | API/frontend | confirmed second segment 不再展示为 volatile payload |

## 7. 文件级修改计划

### Phase 1：把 `physical_prefix_frame` 改成完整第二段快照

文件：

```text
backend/runtime/context_management/physical_prefix_frame_ledger.py
backend/runtime/context_management/physical_prefix_frame_models.py
```

改动：

1. 保留现有 `PhysicalPrefixFrame` 名称和文件，不加 V2。
2. `build_physical_prefix_frame_from_provider_payload()` 生成 frame 时：
   - 读取 previous confirmed frame 的 provider-visible message segments。
   - byte-for-byte 复制 previous confirmed old context。
   - byte-for-byte 追加本次 confirmed current append 的 provider message。
   - 不把 static prefix 加入 old context。
   - 不把 dynamic tail 加入 old context。
3. frame validation 改为校验完整第二段：
   - provider message 存在。
   - provider message hash 与当前 payload / previous frame 一致。
   - current append entry indexes 全部晋升。
   - dynamic tail segment 不存在。
   - previous confirmed old context 的 provider message bytes 与上一帧完全一致。
4. `previous_frame_id` 保留为 lineage 诊断，不作为正常 replay 需要展开的链。

### Phase 2：assembler 只读完整 second segment

文件：

```text
backend/runtime/context_management/physical_context_assembler.py
backend/runtime/context_management/context_pipeline.py
backend/harness/runtime/compiler.py
backend/harness/runtime/context_message_producers.py
```

改动：

1. `latest_confirmed_physical_prefix_frame()` 返回的 frame 被视为完整 second segment。
2. `_frame_replay_specs()` 只按 frame 中保存的 provider message bytes replay provider-visible message segments，不再需要历史链展开。
3. `old_context_replay_specs` 正常情况下只来自 confirmed frame。
4. `prior_work_memory_context` 必须从 `dynamic_projection` 中拆出，并规范成 previous incomplete output memory message spec：
   - 来源是未完成 / 中断 turn 的 TurnMemory 输出热缓存投影。
   - current append payload 必须包含结构化 `state_signal_evidence`，其中 `signal_type=previous_output_interrupted`。
   - `state_signal_evidence` 只描述中断事实、refs、hash、incomplete marker，不写指令。
   - metadata 使用 `context_cache_section=CONTEXT_APPEND`。
   - metadata 使用 `context_commit_policy=append_then_seal`。
   - metadata 使用 `context_replay_policy=current_append_commit_on_provider_success_then_next_physical_prefix_frame`。
   - 进入 provider-visible append ledger，成为本轮 write candidate。
   - provider success 后才晋升入下一帧 confirmed second segment。
   - 不留在 `dynamic_projection` / `never_replay_tail` 里作为唯一模型可见形态。
   - 不转换为 provider protocol replay。
   - 不形成“resume previous turn”提示语义。
5. 根据 `state_signal_evidence` 生成 dynamic tail guidance：
   - `turn_state_guidance` 或等价动态尾巴 spec 只放解释指引。
   - `context_cache_section=DYNAMIC_TAIL`。
   - `context_commit_policy=never_commit`。
   - provider success 后也不晋升。
   - 不把 guidance 文本写入 previous incomplete output memory。
6. 若缺失 confirmed frame：
   - 首轮允许为空。
   - 非首轮输出 structural diagnostic。
   - 不静默转向 provider protocol replay 主路径。

### Phase 3：降级 provider protocol replay

文件：

```text
backend/runtime/context_management/followup_context_rebase.py
backend/harness/loop/single_agent_turn.py
backend/harness/runtime/compiler.py
backend/runtime/context_management/context_pipeline.py
```

改动：

1. 正常 follow-up 不再通过 `provider_protocol_prefix_replay_policy()` 重建旧上下文。
2. `_single_agent_turn_followup_prompt_payload()` 的旧上下文来源切到 confirmed prefix frame：
   - base model_messages 只用于当前工具轮 append 和协议校验。
   - 旧 provider-visible history 不再由 `base_segment_plan + model_messages` 重新分类。
   - 不允许从旧上下文重新生成“语义等价”的新消息；只能复制 confirmed frame bytes。
   - prefix lock 保留为诊断，不再成为旧上下文顺序权威。
3. `provider_protocol_replay` 只保留为：
   - 无 confirmed frame 的诊断路径。
   - 断线/恢复时的证据展示。
   - provider message byte-preservation 的局部保护，而不是上下文来源权威。
4. 如果确实触发 provider protocol replay，必须标记为 degraded path，并且不参与正常 cache spine 健康判定。

### Phase 4：修正 cache accounting

文件：

```text
backend/runtime/prompt_accounting/cache_planner.py
backend/runtime/prompt_accounting/provider_cache_bus_record.py
backend/runtime/prompt_accounting/provider_cache_bus.py
backend/harness/runtime/context_contract/inspection_payload.py
frontend/src/app/agent-network/page.tsx
frontend/src/components/chat/ChatPanel.tsx
frontend/src/lib/api/types.ts
```

改动：

1. confirmed second segment 进入 expected-read 统计。
2. current append 继续展示为 current-turn write candidate。
3. dynamic tail 继续展示为 never replay / volatile。
4. provider protocol replay 不再混进 volatile 主口径；若出现，展示为 degraded replay。
5. `native_tool_binding_schema` sidecar 与 message prefix 分开展示：
   - tools transport sidecar 是 provider physical payload 的一部分。
   - message prefix expected read 是 provider usage 可直接解释的范围。
   - UI 不再把 sidecar uncategorized 成“工具调用过大”。

### Phase 5：清理旧残留和重复判断

搜索并清理：

```text
provider_visible_context_prefix_not_confirmed:provider_protocol_replay
provider_protocol_prefix_replay_reason
append_only_replay_volatile_predicted_tokens
provider_protocol_replay_metadata 主路径调用点
```

保留条件：

```text
只允许保留在 degraded recovery / diagnostics 中。
不得参与正常四段组装、provider cache spine 或 UI 主指标。
```

## 8. 验收标准

以真实运行记录验证，不新增测试文件。

固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
```

验收命令：

```text
python -m py_compile backend/runtime/context_management/physical_prefix_frame_ledger.py backend/runtime/context_management/physical_context_assembler.py backend/runtime/context_management/followup_context_rebase.py backend/runtime/context_management/context_pipeline.py backend/runtime/prompt_accounting/cache_planner.py backend/runtime/prompt_accounting/provider_cache_bus_record.py backend/runtime/prompt_accounting/provider_cache_bus.py backend/harness/runtime/compiler.py backend/harness/runtime/context_message_producers.py backend/harness/loop/single_agent_turn.py backend/runtime/model_gateway/model_runtime.py
npx tsc --noEmit
```

真实运行验收：

1. 发起一次包含多轮 tool follow-up 的真实会话。
2. 第一次 provider success 后 frame 中只有本次成功封存的 old context。
3. 第二次 provider success 后 frame 中的 confirmed_old_context 等于上一帧 old context + 本轮 current append。
4. 下一次 request 的 manifest 中：
   - 旧工具记录来自 `physical_prefix_frame_replay` / confirmed second segment。
   - 旧工具记录不再显示为 `provider_visible_context_prefix_not_confirmed`。
   - 旧上下文 provider message bytes / provider_serialized_hash 与上一帧完全一致。
   - 旧上下文顺序与上一帧完全一致。
   - current tool result 仍在 `current_turn_tail`。
   - dynamic tail 仍在 `never_replay_tail`。
5. provider cache bus 中：
   - stable prefix healthy 继续显示 covered。
   - confirmed old context 不再计入 volatile payload。
   - total hit rate 仍可受 current append 大小影响，但 UI 能解释为 current append miss，不误判为旧上下文 cache 失败。
6. 发起一次用户中断场景：
   - 中断 turn 的 `TurnMemory` 保存 provider refs、tool refs、draft refs、current append hash。
   - 下一条用户输入开启新普通 turn。
   - previous incomplete output memory 从 TurnMemory 输出热缓存生成，并带结构化 `state_signal_evidence.signal_type=previous_output_interrupted`。
   - manifest 中该不完整输出记忆包作为 `current_turn_tail` / current append write candidate，而不是 `never_replay_tail`。
   - dynamic tail 中出现由该 signal 派生的 guidance，且 guidance 不进入 provider-visible append ledger。
   - 该轮 provider success 后，该输出记忆包晋升到下一帧 confirmed old context。
   - task/commit recovery 链路仍只处理 `commit_pending` / `frame_pending`，不接管普通中断。

## 9. 不做事项

```text
不新增 physical_prefix_frame_v2。
不新增 parallel runtime recovery 语义。
不把 turn 概念写入 agent-facing prompt。
不把 provider_protocol_replay 继续作为正常旧上下文拼接主路径。
不对 confirmed_old_context 做摘要、压缩、格式化、normalize、重渲染或重新排序。
不通过降低断言、删除失败样例或 mock provider usage 来制造通过。
不新增回归测试文件；验证使用静态审查、编译检查、真实固定端口运行和真实 provider usage。
```

## 10. 实施顺序

```text
1. 修改 physical_prefix_frame_ledger，使 frame 成为完整 confirmed_old_context 快照。
2. 修改 physical_context_assembler，使第 2 段只读 latest confirmed frame。
3. 修改 compiler / context producer，把 TurnMemory 输出热缓存记忆从 dynamic tail 拆出为 previous incomplete output memory current append facts。
4. 调整 followup_context_rebase / single_agent_turn，移除正常热路径 provider_protocol_replay 重拼旧上下文。
5. 修正 prompt accounting 和 UI 命名展示，让 confirmed second segment、current append、dynamic tail 分账。
6. 清理 provider protocol replay 主路径残留。
7. 编译检查。
8. 固定端口重启。
9. 用真实工具调用会话和用户中断会话验收 manifest、frame ledger、provider cache bus。
```

## 11. 最终目标

修复完成后，四段物理模型的运行语义应变成：

```text
request_n:
  static_n
  old_context_n
  append_n
  tail_n

provider_success(request_n):
  old_context_(n+1) = old_context_n + append_n

request_(n+1):
  static_(n+1)
  old_context_(n+1)
  append_(n+1)
  tail_(n+1)
```

这才是成熟 agent 稳定运行需要的上下文闭合机制：旧上下文原封不动，新增上下文成功后晋升，动态尾巴永不污染记忆线，cache accounting 只读真实物理段，不再靠 provider protocol replay 和 volatile 字段拼解释。
