# Context Prefix Identity Format Audit Report - 2026-06-29

## 1. 结论

本次审查结论：当前上下文前缀格式还不能作为稳定的上下文段身份标识。系统已经有 `prefix_family`、`logical_segment_ref`、`physical_prefix_lane`、`provider_visible_hash`、`cache_spine_hash`、`segment_id` 等字段，但它们把四类信息混在了一起：

- 逻辑身份：这段上下文是什么，属于哪个语义槽位。
- 内容版本：这一次发给 provider 的字节内容是什么。
- 物理位置：它在当前 provider payload 中排第几。
- 缓存资格：它是否应该被认为是 expected prefix read。

成熟 agent 的前缀身份必须把这些维度分开。前缀不是一个普通 label，而是 provider 看到的累积字节前缀的身份契约。正确目标应是：

```text
logical_prefix_identity   稳定表达“这是哪一段”
content_version_hash      表达“这一次内容是什么”
physical_frame_position   表达“它在已确认前缀帧中的位置”
cache_read_expectation    表达“本次是否要求 provider 命中”
```

当前最大问题不是缺少字段，而是没有一个 canonical prefix identity format。结果是同一段上下文在 append、seal、replay、provider payload、cache accounting 中可能换不同身份，或者用内容 hash/ordinal 代替身份。

## 2. 来源依据

### 2.1 外部成熟标准

- OpenAI Prompt Caching 官方文档：Prompt Caching 依赖请求开头相同的前缀，usage 中通过 `cached_tokens` 观测缓存读取。参考：[OpenAI Prompt Caching](https://platform.openai.com/docs/guides/prompt-caching)。
- Anthropic Prompt Caching 官方文档：缓存断点之前的 `tools -> system -> messages` 累积前缀会被写入/读取，改变 breakpoint 前的 block 会改变缓存前缀。参考：[Anthropic Prompt Caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)。
- 本地 Codex 参考：`D:/AI应用/openai-codex/codex-rs/core/src/client.rs:368` 默认用 thread id 作为 `prompt_cache_key`；`D:/AI应用/openai-codex/codex-rs/core/tests/suite/prompt_caching.rs:488` 与 `:777` 断言 override / per-turn override 下 `prompt_cache_key` 不应改变；`:494` 与 `:783` 断言前一次请求的完整 prefix 应作为下一次请求 prefix 原样复用。
- 本地 Claude Code 研究资料：`D:/AI应用/Claude-Code-Source-Study-main/docs/07-Prompt-Cache.md:9` 记录重复前缀是 system prompt、工具定义和消息历史前缀的组合；`:11` 强调字节完全一致；`:24` 说明 cache anomalypoint 表达“从请求开头到标记处”的累积前缀。
- 本地 Hermes 参考：`D:/AI应用/hermes/hermes-agent-main/AGENTS.md:863` 明确“Prompt Caching Must Not Break”；`:865-875` 禁止中途改变 past context、toolsets、memory/system prompt，要求默认 deferred invalidation。

### 2.2 本项目本地原则

- `backend/prompt_composition/assembly_plan.py:262` 已经写明：prompt composition 只保留 source lineage，真正的 provider-visible physical order 应由 `PhysicalContextPlan` 分配，`cache_role`、`prefix_tier`、provider policy、`context_cache_section` 在那里应当只是 diagnostics。
- `backend/runtime/context_management/physical_context_plan.py:234` 已经有四段物理模型：`GLOBAL_STATIC_PREFIX`、`PROVIDER_VISIBLE_CONTEXT_PREFIX`、`CURRENT_TURN_TAIL`、`NEVER_REPLAY_TAIL`。
- `backend/harness/runtime/compiler.py:4232` 明确 current user input 当前请求内不能算作 already cached prefix。

这些原则本身是对的，问题是后续 prefix identity format 没有把这些原则固化成不可混淆的字段契约。

## 3. 当前前缀格式事实

### 3.1 ProviderPayloadSegment 当前字段

`backend/runtime/model_gateway/provider_payload.py:41` 定义的 `ProviderPayloadSegment` 已包含：

```text
segment_id
kind
transport_location
ordinal
role
source_ref
content_hash
cache_scope / cache_role / prefix_tier
prefix_family
semantic_source
logical_segment_ref
semantic_slot
physical_prefix_lane
boundary_participation
```

这些字段覆盖面足够，但没有分层。例如：

- `segment_id` 现在包含 ordinal。
- `logical_segment_ref` 现在包含 content hash。
- `prefix_family` 主要由 lane 推导。
- `physical_cache_spine_hash` 主要由内容 hash、role、lane、boundary 组成。

所以当前 identity 既不是纯逻辑身份，也不是纯内容版本，也不是纯物理位置。

### 3.2 当前 `segment_id` 有两套格式

初始 segment id：

```text
ppseg:{request_id}:{ordinal}:{kind}:{payload_hash12}
```

证据：`backend/runtime/model_gateway/provider_payload.py:1223`

provider payload 重新排序后 segment id：

```text
ppseg:{ordinal}:{transport_location}:{digest16}
```

证据：`backend/runtime/model_gateway/provider_payload.py:1054`

第二套 digest 的种子包含：

```text
ordinal
transport_location
role
content_hash
physical_prefix_lane
boundary_participation
```

问题：这让 `ppseg` 同时表达“当前 payload 位置”和“内容版本”。它适合作为 provider payload manifest 的局部段 id，不适合作为跨 turn/replay 的上下文段身份。

### 3.3 当前 `logical_segment_ref` 把内容 hash 放进身份

证据：`backend/runtime/model_gateway/provider_payload.py:607`

当前 seed 是：

```text
kind
semantic_source
semantic_slot
content_hash
```

问题：如果同一个 semantic slot 的内容版本变化，`logical_segment_ref` 也会变化。这样它就不是“逻辑段身份”，而是“逻辑段 + 内容版本”的混合身份。对缓存诊断来说，这会模糊两件事：

- 这是同一段上下文换了版本。
- 这是完全不同的上下文段。

这两件事在 prefix cache 中必须区分。

### 3.4 当前 `prefix_family` 太粗

证据：`backend/runtime/model_gateway/provider_payload.py:574`

当前 message prefix family 基本只有：

```text
global_static_prefix -> provider_global_static_prefix
provider_visible_context_prefix -> provider_visible_context_prefix
其他 -> dynamic_tail
```

问题：`provider_visible_context_prefix` 会同时容纳：

- current user context replay
- tool transcript replay
- runtime memory context replay
- evidence index replay
- provider protocol history replay

这些段在 provider 前缀中都重要，但只靠同一个 `prefix_family` 不能表达身份差异。它只能表达物理大类，不能承担段身份。

### 3.5 Provider-visible ledger 的 item key 可能退化为内容身份

证据：`backend/runtime/context_management/provider_visible_context_ledger.py:1108`

当前逻辑：

```text
explicit item key
or source_ref_stable(kind + source_ref)
or kind + source_ref + provider_visible_hash
```

问题：fallback 使用 `provider_visible_hash`。这意味着如果没有 explicit key 或 `source_ref_stable`，内容变化会直接变成新 item key。对于 append-only evidence 这可能可接受，但对于需要稳定表达“同一段上下文身份”的 prefix，这会丢失版本关系。

更严重的是，`backend/runtime/context_management/provider_visible_context_ledger.py:97` 会把同 key 不同 hash 当成 recovery failure。这说明 ledger 想维护稳定 item identity，但 fallback 又让很多段没有真正稳定 identity。

### 3.6 Physical cache spine hash 不包含逻辑身份

证据：`backend/runtime/model_gateway/provider_payload.py:1072`

`_segments_hash()` 当前只包含：

```text
transport_location
role
content_hash
physical_prefix_lane
boundary_participation
```

它没有包含：

```text
logical_segment_ref
semantic_slot
source_ref
provider_visible_entry_index
frame_id
```

从 provider byte prefix 角度，只按 role/content/lane 计算能代表“字节是否相同”的一部分事实；但从上下文段身份角度，这不足以解释“哪一段变了”。所以它适合作为 byte/content spine hash，不适合作为 identity hash。

### 3.7 Stability report 按 ordinal 比较，身份诊断不够强

证据：`backend/runtime/prompt_accounting/stability_report.py:310`

当前变更判断核心是：

```text
previous.cache_role != current.cache_role
or previous.content_hash != current.content_hash
```

问题：它可以发现 ordinal 位置上的内容变化，但不能清晰指出：

- 同一个 logical segment 是否移动了位置。
- 同一个 logical segment 是否换了版本。
- 同一个 ordinal 是否被不同 logical segment 占用。
- prefix 是 append-only 追加，还是中间替换。

本次 `tool-followup-2` 的 changed sections 已经暴露了这个问题：我们能看到 ordinal 14 之后 changed，但报告没有用 canonical prefix identity 解释“谁顶掉了谁”。

## 4. Findings

### [P1] `ppseg` 被当作跨阶段身份，但它包含 ordinal

证据：

- `backend/runtime/model_gateway/provider_payload.py:1054`
- `backend/runtime/model_gateway/provider_payload.py:1223`

Broken edge:

```text
context segment logical identity -> provider payload segment id -> physical frame replay identity
```

为什么重要：ordinal 是当前 provider payload 的物理位置，不是上下文段身份。只要工具 schema、system segment、replay frame、current append 的排序发生变化，同一段内容就可能得到新 `ppseg`。这会让 frame diff 看起来像段变化，而不是位置变化。

Required fix：保留 `ppseg` 作为 request-local payload segment id，但新增独立的 `prefix_segment_ref` 作为跨 turn/replay 稳定身份。

### [P1] `logical_segment_ref` 包含 content hash，导致逻辑身份和内容版本混合

证据：`backend/runtime/model_gateway/provider_payload.py:607`

Broken edge:

```text
semantic slot identity -> logical_segment_ref -> replay/version diagnosis
```

为什么重要：成熟 prefix identity 要能表达“同一段的新内容版本”。当前做法会把内容版本变化变成 identity 变化，导致后续无法稳定判断 append-only、replacement、slot drift。

Required fix：`logical_segment_ref` 只由稳定来源生成，例如：

```text
schema + scope + physical_domain + semantic_slot + origin_authority + origin_ref
```

内容 hash 应进入 `prefix_content_version_hash`，不能进入 logical identity。

### [P1] `prefix_family` 只表达大物理域，不能承担段身份

证据：

- `backend/runtime/model_gateway/provider_payload.py:574`
- `backend/runtime/context_management/context_segment_registry.py:113-134`

Broken edge:

```text
semantic segment class -> prefix family -> provider cache spine diagnosis
```

为什么重要：`provider_visible_context_prefix` 下包含 user、tool、memory、evidence、history 多类段。只靠 family 无法判断 provider 前缀中的身份错位。例如 `tool_transcript` 顶掉 `runtime_memory_context` 时，family 仍可能都在 provider-visible context 大类中。

Required fix：`prefix_family` 只保留物理家族语义；段身份必须看 `prefix_segment_ref` + `semantic_slot` + `origin_ref`。

### [P1] provider-visible item key fallback 使用 content hash，会让身份退化

证据：`backend/runtime/context_management/provider_visible_context_ledger.py:1108`

Broken edge:

```text
context append candidate -> provider-visible ledger item identity -> confirmed replay identity
```

为什么重要：没有 explicit item key 时，内容变化会直接变成新 item。这样系统无法区分“同一逻辑槽位更新”和“新 append evidence”。在缓存前缀场景里，这会弱化 append-only 与 replacement 的边界。

Required fix：append-only evidence 可以使用 content-addressed event id，但 provider-visible prefix identity 仍应有稳定 origin ref，例如：

```text
turn_id + tool_round_id + tool_call_id
turn_id + user_message_index
memory_selection_id
evidence_cursor_id
```

内容 hash 只能作为版本。

### [P1] physical cache spine hash 是 byte/content hash，不是身份 hash

证据：`backend/runtime/model_gateway/provider_payload.py:1072`

Broken edge:

```text
provider byte prefix hash -> context segment identity report
```

为什么重要：byte hash 能判断 provider 看到的内容是否可能相同，但不能回答“是哪一段变了”。当前系统把 cache 命中问题和身份问题混在一起，导致 `77.19%` 这种总命中率容易掩盖真实 prefix identity drift。

Required fix：同时维护两类 hash：

```text
prefix_byte_hash      = provider-serialized bytes identity
prefix_identity_hash  = ordered prefix_segment_ref identity chain
```

二者必须都进入 diagnostics。

### [P1] current append 的 prefix label 可能提前看起来像 stable prefix

证据：

- `backend/runtime/context_management/context_segment_policy.py:561`
- `backend/runtime/context_management/provider_visible_context_ledger.py:1080`

Broken edge:

```text
current append physical domain -> cache label -> provider-visible prefix identity
```

为什么重要：当前 append 被改写成 `session_stable/session` 后，identity report 很难区分它是“本次写入候选”还是“已确认可读前缀”。这正是 `volatile` 声明问题的延伸：标签反过来污染了物理段身份。

Required fix：prefix identity 必须带 `lifecycle_state`：

```text
static_prefix
confirmed_frame_replay
current_append_pending_provider_success
dynamic_tail_never_replay
```

cache label 不能覆盖 lifecycle state。

### [P2] semantic slot 已在 registry 中存在，但没有成为 prefix identity 的主键

证据：`backend/runtime/context_management/context_segment_registry.py:113-134`

Broken edge:

```text
registered semantic slot -> provider payload identity -> cache stability report
```

为什么重要：registry 已经知道 `current_user_intent`、`tool_transcript`、`evidence_refs_and_file_state_facts` 等语义槽位，但 provider payload 没有把它们提升为 canonical identity 主键，只是放进 `logical_segment_ref` 的混合 seed。

Required fix：把 registry 的 semantic slot 用作 `prefix_segment_ref` 的核心字段。

## 5. 推荐前缀身份格式

建议新增 canonical prefix identity object，名字可以是：

```text
context_prefix_identity
```

### 5.1 字段格式

```json
{
  "schema": "context_prefix_identity",
  "prefix_domain": "provider_prompt_prefix",
  "physical_lane": "global_static_prefix",
  "lifecycle_state": "static_prefix",
  "semantic_slot": "tool_index",
  "origin_authority": "runtime.tool_catalog_manifest",
  "origin_ref": "tool_catalog_manifest:{stable_hash}",
  "logical_segment_ref": "ctxprefix:global_static_prefix:tool_index:{origin_hash}",
  "content_version_hash": "sha256:...",
  "provider_serialized_hash": "sha256:...",
  "frame_ref": "",
  "frame_ordinal": 0,
  "request_ordinal": 4,
  "cache_read_expectation": "expected_read",
  "promotion_state": "already_confirmed"
}
```

### 5.2 字段职责

| 字段 | 是否稳定 | 谁设置 | 说明 |
| --- | --- | --- | --- |
| `schema` | 稳定 | prefix identity authority | 格式版本 |
| `prefix_domain` | 稳定 | physical context authority | 固定为 provider prompt prefix |
| `physical_lane` | 当前请求内稳定 | PhysicalContextPlan | 四段式物理域 |
| `lifecycle_state` | 随提交阶段变化 | PhysicalPrefixFrame authority | static / confirmed / pending / tail |
| `semantic_slot` | 稳定 | context segment registry/policy | 段语义槽位 |
| `origin_authority` | 稳定 | producer | 谁生产这段上下文事实 |
| `origin_ref` | 稳定 | producer | 业务来源身份，不含内容 hash |
| `logical_segment_ref` | 稳定 | prefix identity authority | 跨 turn/replay 身份 |
| `content_version_hash` | 可变 | provider payload serializer | 内容版本 |
| `provider_serialized_hash` | 可变 | provider payload serializer | provider 实际字节版本 |
| `frame_ref` | confirmed 后稳定 | physical prefix frame ledger | 所属已确认 frame |
| `frame_ordinal` | confirmed 后稳定 | physical prefix frame ledger | 在 confirmed frame 中的位置 |
| `request_ordinal` | 每次请求局部 | provider payload | 当前 payload 中的位置 |
| `cache_read_expectation` | 当前请求策略 | cache planner | expected_read / write_candidate / excluded / blocker |
| `promotion_state` | 随 provider success 变化 | provider-visible ledger/frame ledger | pending / confirmed / rejected |

### 5.3 字符串化前缀格式

为了日志和报告可读，建议同时提供 compact display string：

```text
ctxp/{lane}/{state}/{slot}/{origin_hash}/{content_hash8}
```

示例：

```text
ctxp/global_static_prefix/static_prefix/tool_index/8b2f1a1c/c25b4277
ctxp/provider_visible_context_prefix/confirmed_frame_replay/tool_transcript/turn5.toolround1/be14ddc5
ctxp/current_turn_tail/current_append_pending_provider_success/current_user_intent/turn5.user1/b8dfc2dd
ctxp/never_replay_tail/dynamic_tail_never_replay/turn_operating_contract/run9cf9747f/4d31a880
```

这类 display string 只用于诊断，不作为唯一存储主键。唯一主键仍是结构化 object。

## 6. 四段式模型下的具体前缀规则

### 6.1 Global Static Prefix

身份格式：

```text
physical_lane = global_static_prefix
lifecycle_state = static_prefix
semantic_slot = registry semantic slot
origin_ref = stable manifest/ref, not request id
cache_read_expectation = expected_read
```

允许内容：

- tool index stable
- project instructions stable
- environment stable
- capability catalog
- runtime baseline refs

禁止：

- current request id
- current run id
- current timestamp
- current tool observation

### 6.2 Provider Visible Context Prefix

身份格式：

```text
physical_lane = provider_visible_context_prefix
lifecycle_state = confirmed_frame_replay
frame_ref = confirmed physical prefix frame id
frame_ordinal = original confirmed ordinal
cache_read_expectation = expected_read
```

允许进入条件：

- 来自 confirmed physical prefix frame replay。
- provider success 已确认。
- provider message 字节可重放。

禁止：

- current append pending 直接伪装成 replay prefix。
- 仅凭 `cache_role=session_stable` 进入 expected read。

### 6.3 Current Turn Append

身份格式：

```text
physical_lane = current_turn_tail
lifecycle_state = current_append_pending_provider_success
cache_read_expectation = write_candidate
promotion_state = pending_provider_success
```

允许内容：

- 当前用户输入。
- 当前工具调用与工具结果。
- 当前 read evidence append。
- 当前 user steer append。

关键规则：

```text
current append 可以发送给 provider
但本次不能计入 expected cache read
provider success 后才进入下一帧 confirmed replay
```

### 6.4 Never Replay Tail

身份格式：

```text
physical_lane = never_replay_tail
lifecycle_state = dynamic_tail_never_replay
cache_read_expectation = excluded
promotion_state = never_promote
```

允许内容：

- 当前 turn operating contract。
- repair feedback。
- runtime control signal。
- transient task state cursor。

禁止：

- 写入 provider-visible ledger。
- 进入 physical prefix frame。
- 参与 expected cache read。

## 7. 推荐权力链路

目标链路：

```text
Context producer
-> ContextSegmentRegistry semantic slot
-> PrefixIdentityAuthority generates logical prefix identity
-> PhysicalContextPlan assigns physical lane
-> ProviderPayloadSerializer computes provider serialized hash
-> ProviderVisibleLedger tracks pending append
-> PhysicalPrefixFrameLedger promotes confirmed replay
-> CachePlanner computes expected read
-> StabilityReport compares identity chain and byte chain
```

每层职责：

| 层 | 可决定 | 不可决定 |
| --- | --- | --- |
| producer | origin_authority / origin_ref / semantic source | 是否是 expected cache read |
| registry | semantic_slot / default physical class | provider payload ordinal |
| prefix identity authority | logical_segment_ref | cache hit 结果 |
| physical plan | physical_lane / request order | provider success |
| serializer | content_version_hash / provider_serialized_hash | logical identity |
| provider-visible ledger | pending append item / provider success commit | global static prefix |
| physical frame ledger | confirmed frame / frame ordinal | current request intent |
| cache planner | expected_read / write_candidate / excluded | 修改 segment identity |
| stability report | compare and explain | 重新分类 prefix family |

## 8. 诊断报告必须新增的字段

后续 cache report 不能只列：

```text
ordinal
kind
source_ref
content_hash
cache_role
```

必须列：

```text
request_ordinal
frame_ordinal
logical_segment_ref
semantic_slot
origin_ref
lifecycle_state
physical_lane
content_version_hash
provider_serialized_hash
cache_read_expectation
promotion_state
```

### 8.1 Prefix diff 标准

稳定前缀比较应输出三类 diff：

```text
identity_chain_changed:
  logical_segment_ref sequence changed

content_version_changed:
  same logical_segment_ref, different provider_serialized_hash

position_changed:
  same logical_segment_ref, different frame_ordinal/request_ordinal
```

当前 `changed_sections_count=20` 应进一步解释为：

```text
first_identity_break_ordinal
first_content_version_break_ordinal
first_position_break_ordinal
old logical_segment_ref
new logical_segment_ref
old lifecycle_state
new lifecycle_state
```

这样才能判断是“正常 append”、“内容更新”、“中间替换”还是“current append 抢占 confirmed prefix ordinal”。

## 9. 目标验收标准

### 9.1 Prefix identity invariant

同一 confirmed physical frame 被 replay 时必须满足：

```text
previous_frame.logical_segment_ref_sequence
==
current_request.prefix.logical_segment_ref_sequence[0:n]
```

并且：

```text
previous_frame.provider_serialized_hash_sequence
==
current_request.prefix.provider_serialized_hash_sequence[0:n]
```

### 9.2 Append-only invariant

当前请求只能在 confirmed prefix 后追加：

```text
static prefix
+ confirmed frame replay
+ current append write candidates
+ dynamic tail
```

禁止：

```text
same frame ordinal:
  confirmed replay segment -> current append segment
```

### 9.3 Cache read invariant

只有下面两类能进入 expected cache read：

```text
global_static_prefix/static_prefix
provider_visible_context_prefix/confirmed_frame_replay
```

下面两类不能进入 expected cache read：

```text
current_turn_tail/current_append_pending_provider_success
never_replay_tail/dynamic_tail_never_replay
```

### 9.4 Report invariant

任何 provider under-read 都必须能报告：

```text
first missing expected prefix identity
expected logical_segment_ref
expected provider_serialized_hash
actual segment at same ordinal
break type: identity / content / position / transport_contract
```

## 10. 文件级执行清单

这不是本报告立即实施的代码修改，只是后续修复计划的文件级边界。

| 文件 | 当前角色 | 建议动作 |
| --- | --- | --- |
| `backend/runtime/context_management/context_segment_registry.py` | semantic slot registry | 将 semantic slot 明确提升为 prefix identity 输入 |
| `backend/runtime/context_management/context_segment_policy.py` | section/cache policy 混合解析 | 停止让 cache role 影响 append/stable identity；只输出物理/语义诊断 |
| `backend/runtime/context_management/physical_context_plan.py` | physical lane/order authority | 负责 lifecycle_state 与 physical lane，不接收 cache label 反向授权 |
| `backend/runtime/model_gateway/provider_payload.py` | provider payload segment/manifest | 新增 `prefix_identity` object；保留 `ppseg` 为 request-local id |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | current append ledger | item key 改成稳定 origin identity + content version 分离 |
| `backend/runtime/context_management/physical_prefix_frame_models.py` | confirmed frame schema | 保存 logical identity sequence 和 provider serialized hash sequence |
| `backend/runtime/context_management/physical_prefix_frame_ledger.py` | confirmed frame promotion | 只 promote provider success confirmed append，并固定 frame ordinal |
| `backend/runtime/prompt_accounting/stability_report.py` | prefix diff report | 增加 identity/content/position 三类 diff |
| `backend/runtime/prompt_accounting/cache_planner.py` | expected cache read planner | expected read 只看 lifecycle_state，不看 session_stable 标签 |

## 11. 禁止的修复方式

禁止继续用这些方式修：

- 用 `volatile/session_stable` 字段替代 physical lane。
- 把 `content_hash` 当成逻辑身份。
- 把 `ordinal` 放进跨 turn identity。
- 用 `prefix_family` 单独判断上下文段身份。
- 用 provider 总 cached token 比例判断 prefix 是否成功。
- current append 在本次请求里被算作 expected cache read。
- 为兼容旧链路保留第二套 prefix identity 解释器。

## 12. 最终判断

你的判断是对的：前缀本身就是上下文段身份标识。当前系统的问题不是“前缀字符串不够漂亮”，而是身份格式没有分层，导致内容版本、物理位置、缓存标签和逻辑身份互相污染。

后续修复必须先建立 canonical prefix identity format，再清理旧链路。否则即使短期提高 cached token 比例，也仍然无法保证上下文拼接稳定。

## 13. 成熟 Agent 源码实证：具体前缀到底有什么

本节补充用户追问的核心问题：成熟 agent 的“前缀”不是抽象结构口号，也不是无限增加的语义标签，而是 provider request 开头真实可序列化的字段和 block。缓存命中依赖这些字段的字节顺序、内容、工具 schema、cache_control、model/thinking 配置等共同稳定。

### 13.1 Codex：Responses request 的前缀载体

本地源码：`D:/AI应用/openai-codex`

Codex 的请求构造在 `codex-rs/core/src/client.rs:734-789`。实际 provider-visible request 由这些字段组成：

```text
model
instructions              = prompt.base_instructions.text
input                     = prompt.get_formatted_input()
tools                     = create_tools_json_for_responses_api(prompt.tools)
tool_choice               = "auto"
parallel_tool_calls
reasoning
service_tier
prompt_cache_key          = thread id or explicit override
text / output schema
client_metadata
```

其中 `prompt_cache_key()` 在 `codex-rs/core/src/client.rs:368-372` 默认返回 `state.thread_id`。这只是稳定 cache key，不等于段身份本身。真正的 prefix 命中要求在测试里写死：`codex-rs/core/tests/suite/prompt_caching.rs:494-495` 和 `:783-784` 断言“第一次请求的整个 prefix 必须原样成为第二次请求的 prefix”。

Codex `input` 的初始上下文在 `codex-rs/core/src/session/mod.rs:2638-2864` 构造。具体可见前缀标识包括：

```text
developer role message:
  <permissions instructions> ... </permissions instructions>
  <collaboration_mode> ... </collaboration_mode>
  <model_switch> ... </model_switch>
  <personality_spec> ... </personality_spec>
  <apps_instructions>
    ## Apps (Connectors)
  </apps_instructions>
  <skills_instructions>
    ## Skills
    ### Available skills
    ### How to use skills
  </skills_instructions>
  <plugins_instructions>
    ## Plugins
    ### Available plugins
    ### How to use plugins
  </plugins_instructions>

user role contextual message:
  # AGENTS.md instructions for {directory}
  <INSTRUCTIONS>
  ...
  </INSTRUCTIONS>

  <environment_context>
    <cwd>...</cwd>
    <shell>...</shell>
    <current_date>...</current_date>
    <timezone>...</timezone>
    <network enabled="true">...</network>
    <filesystem>...</filesystem>
    <subagents>...</subagents>
  </environment_context>
```

来源：

- `codex-rs/core/src/context/user_instructions.rs:19-23`
- `codex-rs/core/src/context/environment_context.rs:525-590`
- `codex-rs/protocol/src/protocol.rs:92-102`
- `codex-rs/core-skills/src/render.rs:62-83`
- `codex-rs/core/src/context/available_plugins_instructions.rs`
- `codex-rs/core/src/context/apps_instructions.rs`
- `codex-rs/core/src/context/permissions_instructions.rs:163-177`

Codex 对 `AGENTS.md` 的拼接规则也很具体：`codex-rs/core/src/agents_md.rs:1-16` 从 project root 到 cwd 收集 `AGENTS.md`，不越过 project root；`codex-rs/core/src/agents_md.rs:34-44` 定义默认文件、override 文件和分隔符：

```text
AGENTS.md
AGENTS.override.md

--- project-doc ---
```

结论：Codex 的“具体前缀”是 `instructions + tools + input 中的 developer/contextual user/history`，并由少量稳定 block marker 识别。它没有给每个运行时小段都贴一个模型可见 `volatile` 标签。

### 13.2 Claude Code：system prompt boundary、tools、messages prefix

本地源码：`D:/AI应用/claude-code-nb-main`

Claude Code 的主 system prompt 构造在 `constants/prompts.ts:444-576`。它有一个明确的工程边界：

```text
__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__
```

定义在 `constants/prompts.ts:114-115`。注释要求边界之前是 cacheable static content，边界之后是 user/session dynamic content。

具体 system prompt 前缀内容顺序：

```text
optional attribution header:
  x-anthropic-billing-header: cc_version=...; cc_entrypoint=...;

CLI sysprompt prefix:
  You are Claude Code, Anthropic's official CLI for Claude.
  You are Claude Code, Anthropic's official CLI for Claude, running within the Claude Agent SDK.
  You are a Claude agent, built on Anthropic's Claude Agent SDK.

static content before boundary:
  getSimpleIntroSection(...)
  getSimpleSystemSection()
  getSimpleDoingTasksSection()
  getActionsSection()
  getUsingYourToolsSection(enabledTools)
  getSimpleToneAndStyleSection()
  getOutputEfficiencySection()

boundary:
  __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__

dynamic registry-managed sections:
  session_guidance
  memory
  ant_model_override
  env_info_simple
  language
  output_style
  mcp_instructions
  scratchpad
  frc
  summarize_tool_results
  numeric_length_anchors
  token_budget
  brief
```

来源：

- `constants/system.ts:10-27`
- `constants/system.ts:64-91`
- `constants/prompts.ts:491-555`
- `constants/prompts.ts:560-575`

Claude Code 的 system prompt section 不是每轮随便重算。`constants/systemPromptSections.ts` 定义：

```text
systemPromptSection(name, compute)                  // memoized until /clear or /compact
DANGEROUS_uncachedSystemPromptSection(name, compute) // 会破坏 prompt cache，必须给 reason
```

Claude Code 的 cache 边界和请求分块在 `utils/api.ts:321-435`：

```text
global cache mode with boundary:
  attribution header              cacheScope = null
  system prompt prefix            cacheScope = null
  static content before boundary  cacheScope = global
  dynamic content after boundary  cacheScope = null

default/org mode:
  attribution header              cacheScope = null
  system prompt prefix            cacheScope = org
  everything else                 cacheScope = org
```

`services/api/claude.ts:3213-3236` 将这些 block 转为 Anthropic `TextBlockParam` 并加 `cache_control`。

Claude Code 还把可破坏缓存的因素直接做成检测项。`services/api/promptCacheBreakDetection.ts:227-241` 的 snapshot 包含：

```text
system
toolSchemas
querySource
model
agentId
fastMode
globalCacheStrategy
betas
autoModeActive
isUsingOverage
cachedMCEnabled
effortValue
extraBodyParams
```

并在 `:332-360` 检测：

```text
system prompt changed
tool schemas changed
model changed
fast mode changed
cache_control changed
global cache strategy changed
betas changed
effort/thinking changed
extra body changed
```

fork/side question 也必须继承 cache-safe 参数。`utils/forkedAgent.ts:46-68` 写明 Anthropic cache key 由：

```text
system prompt
tools
model
messages prefix
thinking config
```

组成。`commands/btw/btw.tsx:183-227` 优先复用 `getLastCacheSafeParams()`，注释直接说明这是上一次主线程发送的 exact systemPrompt/userContext/systemContext bytes，复用它们才能保证 byte-identical prefix hit。

结论：Claude Code 的具体前缀包括 `attribution header + CLI sysprompt prefix + static system sections + dynamic sections + tool schemas + messages prefix + thinking/cache_control 配置`。它用 `__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__` 管工程分割，但不是把业务上下文拆成一堆模型可见前缀标签。

### 13.3 Hermes：整串 system prompt 会话内冻结

本地源码：`D:/AI应用/hermes/hermes-agent-main`

Hermes 的核心文件是 `agent/system_prompt.py`。文件头 `:1-21` 直接说明：

```text
system prompt built once per session and reused across all turns
only context compression triggers rebuild
```

它内部有三层，但最终合成一条字符串并缓存到 `agent._cached_system_prompt`：

```text
stable:
  You are Hermes Agent, an intelligent AI assistant created by Nous Research.
  Hermes Agent help guidance
  memory/session_search/skill_manage guidance, if tools loaded
  Kanban guidance, if worker mode
  Computer Use guidance, if tool loaded
  Nous subscription block, if relevant
  Tool-use enforcement guidance
  model-family operational guidance
  ## Skills (mandatory)
  <available_skills>...</available_skills>
  model identity workaround
  environment hints
  platform hints

context:
  caller-supplied system_message
  # Project Context
  ## .hermes.md / HERMES.md
  ## AGENTS.md
  ## CLAUDE.md
  ## .cursorrules

volatile:
  memory snapshot
  USER.md profile
  external memory provider block
  Conversation started: {weekday, month day, year}
  Session ID: ...
  Model: ...
  Provider: ...
```

来源：

- `agent/system_prompt.py:60-76`
- `agent/system_prompt.py:83-185`
- `agent/system_prompt.py:221-283`
- `agent/system_prompt.py:287-303`
- `agent/prompt_builder.py:134-142`
- `agent/prompt_builder.py:1188-1218`
- `agent/prompt_builder.py:1364-1465`

注意：Hermes 虽然内部叫 `volatile`，但 `agent/system_prompt.py:72-76` 与 `:287-303` 明确说这些层会 join 成一个 cached prompt，会话内不重渲染。也就是说，成熟做法不是给模型声明“这段是 volatile”，而是由物理构造和生命周期冻结保证它不会在本会话内漂移。

Hermes 的缓存恢复路径在 `agent/conversation_loop.py:85-185`：

```text
if continuing session and DB has stored system_prompt:
  agent._cached_system_prompt = stored_prompt
  return

else:
  build system prompt
  update_system_prompt(session_id, cached_prompt)
```

注释 `:134-137` 写明：continuing session 复用 exact system prompt，这样 Anthropic cache prefix 才匹配。

Hermes 的请求发送前缀在 `agent/conversation_loop.py:790-826`：

```text
effective_system = active_system_prompt
optional ephemeral_system_prompt appended at API-call time only
api_messages = [{"role": "system", "content": effective_system}] + history
apply_anthropic_cache_control(system + last 3 non-system messages)
```

`agent/prompt_caching.py` 固定策略：

```text
system_and_3:
  system prompt
  last 3 non-system messages
  max 4 cache_control breakpoints
  same TTL
```

Hermes 对工具和 skills 的边界非常硬：

```text
/reload-mcp:
  invalidates provider prompt cache
  tool schemas are baked into the system prompt

/reload-skills:
  does NOT clear prompt cache
  skill changes are queued into next user message
  skills can be invoked via /skill-name, skills_list, skill_view
```

来源：

- `cli.py:9743-9783`
- `cli.py:9861-9876`
- `cli.py:9894-9905`
- `AGENTS.md:863-875`

后台 review fork 也继承父 agent 的 `_cached_system_prompt`。`agent/background_review.py:420-440` 注释说明：如果 fork 重建 system prompt，会因为 timestamp/session_id/toolset/skills_prompt 不同导致 byte-exact prefix miss。

结论：Hermes 的具体前缀是 `system prompt snapshot + history messages + tools schema + cache_control breakpoints`。它把工具变更视为显式 invalidation，把 plugin/skill 动态上下文压到 user message 或 tool result，而不是改 system prefix。

### 13.4 OpenCode：system message + tools + messages

本地源码：`D:/AI应用/opencode-main`

OpenCode 的 OpenAI provider 在 `internal/llm/provider/openai.go:68-146`：

```text
messages:
  system message first = providerOptions.systemMessage
  user messages
  assistant messages
  tool messages

tools:
  function name
  description
  parameters
  required
```

`internal/llm/provider/openai.go:162-167` 构造 ChatCompletion params：

```text
Model
Messages
Tools
ReasoningEffort / MaxCompletionTokens, if supported
```

`internal/llm/provider/openai.go:384-393` 从 OpenAI usage 读取：

```text
PromptTokensDetails.CachedTokens
```

Anthropic provider 在 `internal/llm/provider/anthropic.go:60-118` 对最近消息加 cache control，在 `:180-195` 发送：

```text
System:
  providerOptions.systemMessage
  cache_control: ephemeral

Messages
Tools
Thinking
```

OpenCode 的 prompt 前缀内容在 `internal/llm/prompt/coder.go:16-24` 与 `:27-90`，常见起始语包括：

```text
You are operating as and within the OpenCode CLI...
You are OpenCode, an interactive CLI tool...

# Memory
# Tone and style
```

项目上下文在 `internal/llm/prompt/prompt.go:16-31` 以：

```text
# Project-Specific Context
Make sure to follow the instructions in the context below
# From:{filePath}
```

追加到 agent prompt。

结论：OpenCode 也是少数稳定载体：`system message / project context / tools / messages / cache_control`。它没有把每个上下文来源都变成复杂模型可见前缀标签。

### 13.5 DeepSeek：provider 自动缓存完整 prefix unit

官方文档：DeepSeek Context Caching，`https://api-docs.deepseek.com/guides/kv_cache`

DeepSeek 的规则与 Anthropic 的手动 `cache_control` 不同：Context Caching 默认开启，不要求用户改代码。命中要求是“后续请求完整匹配已经持久化的 cache prefix unit”。

DeepSeek 官方规则：

```text
cache hit requires:
  subsequent request fully matches a persisted cache prefix unit

prefix units are persisted at:
  request boundaries:
    end of user input
    end of model output
  common prefix detection:
    shared prefix across requests
  fixed token intervals:
    long input/output interval persistence

usage fields:
  prompt_cache_hit_tokens
  prompt_cache_miss_tokens
```

DeepSeek 的 Chat Prefix Completion 是另一件事。官方文档 `https://api-docs.deepseek.com/guides/chat_prefix_completion` 说最后一条 message 必须：

```text
role = assistant
prefix = true
base_url = https://api.deepseek.com/beta
```

这不是 prompt cache prefix，而是“让模型续写 assistant prefix message”的生成控制。

结论：DeepSeek 的 cache prefix 不是 agent 自己声明多段标签，而是 provider 对完整 serialized request prefix unit 做自动匹配。我们如果接 DeepSeek，应以 `prompt_cache_hit_tokens / prompt_cache_miss_tokens` 校验完整 prefix unit 命中，而不是套用 Anthropic 的 `cache_control` 思维。

### 13.6 横向结论：成熟 agent 具体前缀清单

成熟 agent 的前缀不是“很多个自造前缀名”，而是下面这些 provider request 前段：

```text
1. system / instructions / developer policy
   - Codex: instructions + developer input messages
   - Claude Code: system prompt blocks
   - Hermes: cached system prompt string
   - OpenCode: providerOptions.systemMessage

2. tool schema / tool contract
   - tools array / model-visible tool specs
   - MCP/toolset reload 必须显式 invalidation

3. project/user/context instruction blocks
   - Codex: # AGENTS.md instructions for ... + <INSTRUCTIONS>
   - Claude Code: memory/env/language/output style/MCP sections
   - Hermes: # Project Context / ## AGENTS.md / ## HERMES.md
   - OpenCode: # Project-Specific Context / # From:{filePath}

4. environment/runtime facts
   - Codex: <environment_context> with cwd/shell/date/timezone/filesystem
   - Claude Code: # Environment
   - Hermes: environment hints + Conversation started date

5. conversation history prefix
   - prior user/assistant/tool messages
   - tool calls and tool results must keep role/order/provider format stable

6. cache boundary/control metadata
   - Anthropic: cache_control on selected system/message/tool blocks
   - Claude Code: global/org cache scopes + boundary marker
   - Codex/OpenAI: prompt_cache_key + cached_tokens usage
   - DeepSeek: persisted cache prefix units + hit/miss token usage

7. model/request-shape parameters that affect cache key
   - model
   - reasoning/thinking config
   - fast mode / beta headers
   - extra body params
   - service tier / provider-specific knobs when serialized into request identity
```

因此，本项目不要再把 prefix 当成“声明越多越清楚”。正确做法是：

```text
canonical prefix identity:
  stable logical segment identity
  + provider-visible serialized hash
  + physical frame position
  + lifecycle state

provider-visible prompt text:
  只保留少数必要、可审计、模型可理解的段标识
```

也就是说，`volatile`、`session_stable`、`cacheable` 这类生命周期词应该是内部 ledger / frame / diagnostics 字段，不应该到处变成模型可见 prefix 文案。物理四段模型本身已经提供了域边界；多余声明会让 prefix 身份、缓存资格、模型语义混在一起，反而破坏稳定性。
