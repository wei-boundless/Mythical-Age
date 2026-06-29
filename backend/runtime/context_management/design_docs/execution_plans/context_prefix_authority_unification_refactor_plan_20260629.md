# Context Prefix Authority Unification Refactor Plan

日期：2026-06-29

状态：已确认，实施中。本文件是对缓存命中审计、前缀身份格式审计、最新对话卡住修复计划、以及成熟 agent 源码研究的汇总重构方案。当前先实施单 agent `TurnMemory` 热账本恢复接线，再继续 prefix identity / cache authority 收束。

相关文档：

- `backend/runtime/context_management/design_docs/cache_prefix_hit_audit_report_20260629.md`
- `backend/runtime/context_management/design_docs/cache_prefix_identity_format_audit_report_20260629.md`
- `backend/runtime/context_management/design_docs/execution_plans/chat_refresh_hot_recovery_terminal_invariant_plan_20260629.md`
- `backend/runtime/context_management/design_docs/execution_plans/physical_context_spine_authority_unification_plan_20260629.md`
- `backend/runtime/context_management/design_docs/execution_plans/provider_payload_physical_cache_spine_authority_plan_20260628.md`

## 1. 结论

当前上下文拼接系统的核心问题不是“prompt cache 命中率不够高”，而是前缀权威链路没有统一。系统已经有四段式物理模型，也有 provider-visible ledger、physical prefix frame、provider payload manifest、cache planner、stability report，但这些模块仍在用各自的字段解释“什么算前缀”。

直接后果是：

```text
本地报告认为 no_local_physical_break
provider usage 却显示 provider_under_read
总 cached ratio 可以到 77.19%
但 expected physical prefix 仍未完整命中
```

正确目标不是继续追求一个好看的总命中率，而是建立可复算的不变量：

```text
previous_confirmed_prefix_bytes
== current_request_prefix_bytes[0:len(previous_confirmed_prefix_bytes)]

previous_confirmed_prefix_identity_sequence
== current_request_prefix_identity_sequence[0:len(previous_confirmed_prefix_identity_sequence)]
```

只要 `provider_under_read_tokens > 0`，即使总命中率是 77.19%，也不能判定 prefix cache 成功。

本次重构目标：

```text
Context producers
-> ContextSegmentRegistry semantic slot
-> PrefixIdentityAuthority
-> PhysicalContextAssembler / PhysicalContextPlan
-> ProviderPayloadManifest
-> PhysicalPrefixFrameLedger
-> CachePlanner / StabilityReport / ProviderCacheLedger
```

其中只有 `PrefixIdentityAuthority + PhysicalPrefixFrameLedger + ProviderPayloadManifest` 共同决定 provider prefix 身份、字节和晋升。其他模块只产候选、读账本或展示诊断。

## 2. 问题定义

### 2.1 当前失败模式

最新 turn 的三次 provider 请求均为 `provider_under_read`：

| request | prompt_tokens | cached_tokens | hit_rate | cache_status | provider_under_read_tokens | coverage |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| initial | 119138 | 36608 | 30.73% | provider_under_read | 74019 | physical_spine_estimated_partial |
| tool-followup-1 | 47280 | 36608 | 77.43% | provider_under_read | 2956 | physical_spine_estimated_partial |
| tool-followup-2 | 51738 | 39936 | 77.19% | provider_under_read | 436 | physical_spine_estimated_partial |

`tool-followup-2` 的 changed sections 从 ordinal 14 开始出现替换：当前工具调用和工具结果顶到了上一帧 runtime memory / evidence replay 的位置。成熟 prefix cache 要求旧 prefix 原样保留后追加 tail；当前表现更像旧 frame 被重新拼接。

### 2.2 真正破损的系统属性

破损属性不是“缺少缓存字段”，而是这四个维度没有分离：

```text
logical prefix identity      这段上下文是什么
content version hash         这一次内容是什么
physical frame position      它在确认前缀帧中的位置
cache read expectation       本次是否必须命中 provider cache
```

当前 `segment_id` 含 ordinal，`logical_segment_ref` 含 content hash，`prefix_family` 太粗，provider-visible item key fallback 会退化为 content-addressed，physical spine hash 是字节/content hash 不是身份 hash。结果是同一段上下文在 append、seal、replay、provider payload、cache accounting 中可能换身份。

### 2.3 正确终态

正确终态应该满足：

- 四段式物理模型继续保留，但它只表达物理域，不把 `volatile/session_stable/cacheable` 写成模型可见身份声明。
- 前缀身份是结构化 object，不是可见 prompt 文案，也不是单个 hash。
- hash 只用于内容版本、provider 序列化字节、差异检测和 telemetry，不作为逻辑身份。
- current append 本次可发给 provider，但不能计入 expected read；provider success 后才晋升为下一帧 confirmed replay。
- cache report 优先显示 prefix coverage、under-read、first changed identity，不再用总 hit ratio 掩盖 miss。

## 3. 成熟 Agent 源码标准

### 3.1 Codex

本地源码：`D:/AI应用/openai-codex`

Codex 的 Responses request 前缀载体是 provider request 的真实字段，而不是自造的一堆模型可见标签：

```text
model
instructions
input
tools
tool_choice
parallel_tool_calls
reasoning
service_tier
prompt_cache_key
text / output schema
client_metadata
```

证据：

- `D:/AI应用/openai-codex/codex-rs/core/src/client.rs:368`：`prompt_cache_key()` 默认使用 thread id，也可显式 override。
- `D:/AI应用/openai-codex/codex-rs/core/src/client.rs:734`：request body 构造包含 `instructions`、`input`、`tools`、`reasoning`、`prompt_cache_key`。
- `D:/AI应用/openai-codex/codex-rs/core/tests/suite/prompt_caching.rs:488`：断言 `prompt_cache_key` 跨 override 不变。
- `D:/AI应用/openai-codex/codex-rs/core/tests/suite/prompt_caching.rs:494` 与 `:783`：断言上一请求的 entire prefix 必须作为下一请求 prefix 原样复用。

Codex 的具体前缀标识是少数稳定 block marker，例如：

```text
<permissions instructions>
<skills_instructions>
<plugins_instructions>
# AGENTS.md instructions for ...
<INSTRUCTIONS>
<environment_context>
```

结论：Codex 用稳定 request key + provider-visible byte-identical prefix，而不是给每个上下文小段声明 `volatile`。

### 3.2 Claude Code

本地源码：`D:/AI应用/claude-code-nb-main`

Claude Code 明确把 system prompt 分成静态前缀和动态后缀：

```text
__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__
```

证据：

- `D:/AI应用/claude-code-nb-main/constants/prompts.ts:107`：boundary 前可用 global cache，boundary 后为 user/session dynamic content。
- `D:/AI应用/claude-code-nb-main/constants/systemPromptSections.ts:17`：普通 system prompt section memoized until `/clear` or `/compact`。
- `D:/AI应用/claude-code-nb-main/constants/systemPromptSections.ts:28`：`DANGEROUS_uncachedSystemPromptSection` 明确说明变化会破坏 prompt cache，必须给 reason。
- `D:/AI应用/claude-code-nb-main/utils/forkedAgent.ts:49`：cache key 受 system prompt、tools、model、messages prefix、thinking config 影响。

Claude Code 使用 hash，但用途是缓存破坏检测：

```text
systemHash
toolsHash
cacheControlHash
perToolHashes
extraBodyHash
```

证据：

- `D:/AI应用/claude-code-nb-main/services/api/promptCacheBreakDetection.ts:29`：记录 `systemHash/toolsHash/cacheControlHash`。
- `D:/AI应用/claude-code-nb-main/services/api/promptCacheBreakDetection.ts:274`：计算 stripped system/tools hash。
- `D:/AI应用/claude-code-nb-main/services/api/promptCacheBreakDetection.ts:279`：单独 hash cache_control，检测 scope/TTL 变化。
- `D:/AI应用/claude-code-nb-main/services/api/promptCacheBreakDetection.ts:332`：用 hash 差异判定 system/tool/cache_control/model 等是否变化。

结论：Claude Code 确实用 hash，但 hash 是 diff / diagnostics / break detection，不是逻辑段身份。

### 3.3 Hermes

本地源码：`D:/AI应用/hermes/hermes-agent-main`

Hermes 的关键策略是 system prompt 会话内冻结：

```text
stable/context/volatile 内部分层
-> join 成一条 cached system prompt
-> 存到 agent._cached_system_prompt
-> continuation 时从 DB 恢复 exact stored prompt
```

证据：

- `D:/AI应用/hermes/hermes-agent-main/agent/system_prompt.py:1`：system prompt built once per session。
- `D:/AI应用/hermes/hermes-agent-main/agent/system_prompt.py:287`：最终 join system prompt 并写入 `_cached_system_prompt`。
- `D:/AI应用/hermes/hermes-agent-main/agent/conversation_loop.py:85`：continuing session 优先恢复 DB 中存储的 system prompt。
- `D:/AI应用/hermes/hermes-agent-main/cli.py:9743`：`/reload-mcp` 明确提示会 invalidates provider prompt cache。
- `D:/AI应用/hermes/hermes-agent-main/cli.py:9894`：reload skills 不清 prompt cache，而是把 note 排到下一次 user message。
- `D:/AI应用/hermes/hermes-agent-main/agent/background_review.py:420`：review fork 继承父 `_cached_system_prompt`，避免 byte-exact prefix miss。

结论：Hermes 内部可以叫 `volatile`，但不会把“volatile”作为每轮漂移的模型可见前缀声明。物理生命周期冻结才是关键。

### 3.4 OpenCode

本地源码：`D:/AI应用/opencode-main`

OpenCode 的前缀载体同样是 provider request 的真实结构：

```text
systemMessage
messages
tools
cache_control / usage cached tokens
```

证据：

- `D:/AI应用/opencode-main/internal/llm/provider/openai.go:68`：OpenAI request 先放 system message，再放 user/assistant/tool messages。
- `D:/AI应用/opencode-main/internal/llm/provider/openai.go:128`：构造 tools array。
- `D:/AI应用/opencode-main/internal/llm/provider/openai.go:385`：读取 `PromptTokensDetails.CachedTokens`。
- `D:/AI应用/opencode-main/internal/llm/provider/anthropic.go:187`：Anthropic request 中 system block 带 `cache_control`。
- `D:/AI应用/opencode-main/internal/llm/prompt/prompt.go:35`：项目上下文以 `# Project-Specific Context` 追加。

结论：OpenCode 也没有给每个上下文来源设计大量模型可见 prefix label。

### 3.5 DeepSeek

官方文档：

- `https://api-docs.deepseek.com/guides/kv_cache`
- `https://api-docs.deepseek.com/guides/chat_prefix_completion`

DeepSeek Context Caching 默认开启，核心是后续请求完整匹配已持久化的 cache prefix unit。usage 字段是：

```text
prompt_cache_hit_tokens
prompt_cache_miss_tokens
```

Chat Prefix Completion 是另一件事：最后一条 assistant message 设置 `prefix=true`，用于让模型续写 assistant prefix，不是 prompt cache prefix。

结论：DeepSeek 也证明 provider cache 的核心是完整 serialized prefix unit 匹配，不是 agent 在 prompt 里声明很多 cache label。

### 3.6 横向结论：成熟 Agent 具体前缀清单

成熟 agent 的具体前缀主要是这些 provider-visible request 前段：

```text
1. system / instructions / developer policy
2. tool schema / tool contract
3. project/user/context instruction blocks
4. environment/runtime facts
5. conversation history prefix
6. cache boundary/control metadata
7. model/request-shape parameters
```

它们使用少数稳定 marker：

```text
Codex:
  <permissions instructions>
  <skills_instructions>
  <plugins_instructions>
  # AGENTS.md instructions for ...
  <INSTRUCTIONS>
  <environment_context>

Claude Code:
  __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__
  system prompt sections
  cache_control blocks

Hermes:
  # Project Context
  ## AGENTS.md
  ## CLAUDE.md
  <available_skills>

OpenCode:
  # Project-Specific Context
  # From:{filePath}
```

不成熟的做法是把内部生命周期词大量写到模型可见 prompt 里，例如：

```text
volatile
session_stable
cacheable_prefix
current_append_pending_provider_success
```

这些应是 ledger / diagnostics 字段，不应成为 agent 需要阅读的 prompt 前缀文案。

## 4. 本项目当前代码证据

### 4.1 已有正确基础

本项目已经有四段式物理模型：

```text
global_static_prefix
provider_visible_context_prefix
current_turn_tail
never_replay_tail
```

证据：`backend/runtime/context_management/physical_context_plan.py:23`

`context_segment_registry.py` 已经有大量 semantic slot：

```text
tool_index
current_user_intent
tool_transcript
selected_memory_and_task_state_facts
evidence_refs_and_file_state_facts
turn_operating_contract
runtime_control_contract
```

证据：`backend/runtime/context_management/context_segment_registry.py:97-155`

这些是好的骨架。问题不是没有四段式，也不是没有语义槽位，而是这些槽位没有成为 canonical prefix identity 的主键。

### 4.2 当前混淆点

`ProviderPayloadSegment` 当前已经包含很多字段：

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
metadata
```

证据：`backend/runtime/model_gateway/provider_payload.py:42`

但字段职责混在一起：

- `provider_payload.py:607` 的 `_stable_logical_segment_ref()` 把 `content_hash` 放进 logical ref seed。
- `provider_payload.py:1054` 的 `_provider_payload_segment_id()` 把 `ordinal`、`content_hash`、lane、boundary 放进 `ppseg`。
- `provider_payload.py:1072` 的 `_segments_hash()` 只按 transport、role、content、lane、boundary 计算 byte/content hash，不包含 logical identity。
- `provider_visible_context_ledger.py:1108` 的 item key fallback 包含 `provider_visible_hash`，会让身份退化成内容 hash。
- `stability_report.py:310` 主要按 ordinal 上的 `cache_role/content_hash` 比较，不能区分 identity drift、content version drift、position drift。
- `cache_planner.py:521` 对 physical spine 做 total-only coverage estimate，能发现 under-read，但不能定位第一个 identity 断点。

### 4.3 当前已部分修过但不等于本重构完成

`chat_refresh_hot_recovery_terminal_invariant_plan_20260629.md` 关注的是最新对话卡住：

```text
tool observation 成功
-> follow-up prompt physical context order TypeError
-> runtime status only error 被 public stream 过滤
-> missing_terminal_event / orphaned
```

当前 `physical_context_plan.py:341` 的 `_physical_context_order_key()` 已经是固定 tuple：

```text
lane_rank
provider_round_start
provider_round_order
ledger_entry_index
original_index
source_ref
```

这说明排序 TypeError 的窄问题已经有修复迹象。但 prefix identity 仍未统一，尤其是 identity/content/ordinal/cache expectation 混用仍然存在。

## 5. 目标设计决策

### 5.1 不把 volatile 声明成模型可见前缀

用户的判断是对的：四段式物理段本身已经提供生命周期域，额外声明 `volatile` 反而会污染模型可见上下文身份。

目标：

```text
物理域:
  global_static_prefix
  provider_visible_context_prefix
  current_turn_tail
  never_replay_tail

内部 lifecycle:
  static_prefix
  confirmed_frame_replay
  current_append_pending_provider_success
  dynamic_tail_never_replay

模型可见文本:
  只保留 agent 能理解的角色、任务、边界、事实来源
```

禁止：

```text
把 volatile/session_stable/cacheable_prefix 写成模型可见段标题
用 cache label 替代物理 lane
用 lifecycle word 让 agent 自己判断缓存资格
```

### 5.2 Hash 使用边界

成熟 agent 用 hash，但用途明确：

```text
允许:
  content_version_hash
  provider_serialized_hash
  prefix_identity_chain_hash
  diagnostics diff hash
  telemetry dedupe hash

禁止:
  content_hash 作为 logical_segment_ref 的一部分
  ordinal 作为跨 turn identity 的一部分
  provider_visible_hash fallback 成为 prefix item identity
  单个 hash 取代结构化 prefix identity object
```

Hash 是体温计，不是身份证。

### 5.3 Canonical Prefix Identity

新增或明确一个结构化身份对象：

```text
context_prefix_identity.v1
```

字段：

| 字段 | 职责 | 稳定性 |
| --- | --- | --- |
| `schema` | 格式版本 | 稳定 |
| `prefix_domain` | 固定为 provider prompt prefix | 稳定 |
| `semantic_slot` | 语义槽位 | 稳定 |
| `origin_authority` | 段来源权威 | 稳定 |
| `origin_ref` | 来源身份，不含内容 hash | 稳定 |
| `logical_segment_ref` | 跨 turn/replay 逻辑身份 | 稳定 |
| `physical_lane` | 四段式物理域 | 当前请求内稳定 |
| `lifecycle_state` | static / confirmed / pending / never replay | 随阶段变化 |
| `content_version_hash` | 内容版本 | 可变 |
| `provider_serialized_hash` | provider 实际序列化字节 | 可变 |
| `frame_ref` | 所属 confirmed frame | confirmed 后稳定 |
| `frame_ordinal` | confirmed frame 内位置 | confirmed 后稳定 |
| `request_ordinal` | 当前 request 局部位置 | 每次请求局部 |
| `cache_read_expectation` | expected_read / write_candidate / excluded / blocker | 当前请求策略 |
| `promotion_state` | pending / confirmed / rejected / never_promote | 随 provider success 变化 |

示例：

```json
{
  "schema": "context_prefix_identity.v1",
  "prefix_domain": "provider_prompt_prefix",
  "semantic_slot": "tool_transcript",
  "origin_authority": "runtime.context_management.physical_prefix_frame.replay",
  "origin_ref": "turn:session-x:5/tool_round:1",
  "logical_segment_ref": "ctxprefix:v1:tool_transcript:turn.session-x.5.tool_round.1",
  "physical_lane": "provider_visible_context_prefix",
  "lifecycle_state": "confirmed_frame_replay",
  "content_version_hash": "sha256:...",
  "provider_serialized_hash": "sha256:...",
  "frame_ref": "physframe:55c2086897eb1c85",
  "frame_ordinal": 16,
  "request_ordinal": 18,
  "cache_read_expectation": "expected_read",
  "promotion_state": "confirmed"
}
```

诊断可提供 compact display string，但不能作为存储主键：

```text
ctxp:v1/{lane}/{state}/{slot}/{origin_ref_short}/{content_hash8}
```

### 5.4 Expected Cache Read 规则

只允许两类进入 expected read：

```text
global_static_prefix / static_prefix
provider_visible_context_prefix / confirmed_frame_replay
```

不允许两类进入 expected read：

```text
current_turn_tail / current_append_pending_provider_success
never_replay_tail / dynamic_tail_never_replay
```

current append 可以成为 write candidate，但本次请求不能要求 provider 读它。provider success 后，它才能成为下一次请求的 confirmed frame replay。

### 5.5 四段式前缀机制是唯一物理权威

后续实现不再增加新的“前缀种类”。四段式模型已经足够表达缓存资格，判断规则必须直接落在四段上：

| 物理段 | 是否 expected cache read | 谁能写入 | 含义 |
| --- | --- | --- | --- |
| `global_static_prefix` | 是 | static/context compiler | 会话或全局稳定的 agent 指令、工具能力、项目指令、环境边界、文件证据政策 |
| `provider_visible_context_prefix` | 是 | `PhysicalPrefixFrameLedger` replay only | provider success 已确认的旧上下文 frame，必须原顺序原字节 replay |
| `current_turn_tail` | 否，本次只是 write candidate | current context producers | 当前用户请求、当前工具结果、当前证据追加、当前 steer |
| `never_replay_tail` | 否，永不 promote | runtime control producers | turn operating contract、runtime control、recovery instruction、临时纠错 |

这四段就是缓存控制本体。`cache_scope`、`cache_role`、`prefix_tier`、`lifecycle_state`、`prefix_family` 只能作为派生诊断字段，不能反过来决定缓存资格。

Provider transport request 结构仍要纳入缓存诊断，但它不是第五个上下文物理段：

```text
TransportContract:
  model
  tools schema
  tool_choice
  response_format
  reasoning / thinking config
  cache_control / provider cache key
  provider-specific request params
```

`TransportContract` 的变化会使 provider cache family 改变；但它只由 `ProviderPayloadManifest` 记录和校验，不进入上下文四段式拼接，也不显示给模型为“前缀段”。

注意：这里必须区分两种“工具”：

```text
Tool Capability Surface:
  模型可见的工具能力说明，属于 global_static_prefix 的语义内容。

Native provider tools schema:
  provider request 的 transport contract，属于 ProviderPayloadManifest 的传输结构和 cache family 诊断。
  它可以有 provider_tool_schema_prefix / blocker 这类内部传输标记，但不是第五个上下文物理段。
```

### 5.6 表现层前缀只保留少数语义分组

模型可见文本不承担缓存控制，只承担理解任务的语义分组。为了避免冗余，模型可见 title 收敛为六类：

| 可见分组 | 对应物理段 | 用途 |
| --- | --- | --- |
| `Stable Instructions` | `global_static_prefix` | agent 身份、项目规则、环境边界、文件证据政策 |
| `Tool Capability Surface` | `global_static_prefix` | agent 可用工具、工具动作契约、工具边界 |
| `Confirmed Context` | `provider_visible_context_prefix` | 已确认历史、记忆、证据、工具 transcript |
| `Current Request` | `current_turn_tail` | 当前用户请求和本轮用户 steering |
| `Current Evidence` | `current_turn_tail` | 当前工具结果、当前文件/附件/编辑器证据 |
| `Runtime Control` | `never_replay_tail` | 当前轮行动边界、恢复指令、运行时纠错 |

这些 title 是表现层名字，不是物理段名字。它们可以合并多个固定槽，避免把每个小段都变成一个模型可见前缀。

`context_fragment.v1` 可以保留，但模型可见属性只允许：

```text
protocol
kind
title
role
```

以下字段不得出现在模型可见 tag、title、section header 中：

```text
global_static_prefix
provider_visible_context_prefix
current_turn_tail
never_replay_tail
cache_scope
cache_role
prefix_tier
session_stable
volatile
cacheable_prefix
never_cache
lifecycle_state
frame_ref
frame_ordinal
request_ordinal
logical_segment_ref
provider_serialized_hash
ctxp:v1/...
ppseg:...
physframe:...
provider_under_read
physical_spine_estimated_partial
```

如果模型需要理解上下文，只看 `Stable Instructions / Tool Capability Surface / Confirmed Context / Current Request / Current Evidence / Runtime Control`。如果系统需要判断缓存，只看四段式物理归属和 provider usage。

### 5.7 固定集合槽只做语义路由

固定集合槽不是新的前缀系统，它只回答“这条事实应该插到哪类集合”。槽位必须少而稳，接入方只能选择，不能临时发明槽位来绕过四段式。

| 固定槽 | 默认插入段 | 可见分组 | 典型来源 |
| --- | --- | --- | --- |
| `agent_instructions` | `global_static_prefix` | `Stable Instructions` | `agent_stable`、`personality_stable` |
| `tool_contract` | `global_static_prefix` | `Tool Capability Surface` | `tool_index_stable`、`capability_catalog` |
| `project_policy` | `global_static_prefix` | `Stable Instructions` | `project_instructions_stable` |
| `environment_policy` | `global_static_prefix` | `Stable Instructions` | `task_environment_context`、`environment_stable` |
| `file_evidence_policy` | `global_static_prefix` | `Stable Instructions` | `file_evidence_policy_stable` |
| `conversation_history` | `provider_visible_context_prefix` | `Confirmed Context` | provider protocol replay、physical frame message replay |
| `user_intent` | `current_turn_tail`，confirmed 后进 `provider_visible_context_prefix` | `Current Request` / `Confirmed Context` | current user context、user message replay |
| `memory_state` | `current_turn_tail`，confirmed 后进 `provider_visible_context_prefix` | `Confirmed Context` | runtime memory context、task state replay |
| `evidence_facts` | `current_turn_tail`，confirmed 后进 `provider_visible_context_prefix` | `Current Evidence` / `Confirmed Context` | read evidence、evidence index、attachment/editor context |
| `tool_transcript` | `current_turn_tail`，confirmed 后进 `provider_visible_context_prefix` | `Current Evidence` / `Confirmed Context` | tool call、tool result、tool transcript replay |
| `turn_contract` | `never_replay_tail` | `Runtime Control` | turn operating contract、follow-up action contract |
| `runtime_control` | `never_replay_tail` | `Runtime Control` | runtime control signal、recovery instruction |

新增固定槽的门槛要高：只有当现有槽不能表达事实类别、promotion rule、可见分组和权限边界时才新增。普通新证据、新工具结果、新记忆选择都应接到已有槽。

### 5.8 上下文接入只能定义来源事实

上下文接入方只定义事实来源，不定义缓存前缀。

接入方必须提供：

```text
ingress_kind
semantic_slot
origin_authority
origin_ref
payload_schema
payload
visibility_intent
```

接入方可以建议：

```text
append_only
preferred_visible_group
provider_role_hint
```

接入方禁止提供或覆盖：

```text
physical_prefix_lane
cache_read_expectation
promotion_state
frame_ref
frame_ordinal
request_ordinal
logical_segment_ref
provider_serialized_hash
prefix_family
cache_scope
cache_role
prefix_tier
```

标准接入链路：

```text
IngressKind + OriginRef
-> fixed SemanticSlot
-> four-segment PhysicalLane
-> provider serialized bytes
-> expected cache read derived from PhysicalLane
```

这条链路的控制点很少，但表现足够具体：线插到哪一段，是否应命中就自然确定。

### 5.9 上下文时空模型

你的判断可以作为本次重构的核心架构语言：上下文拼接不是平面列表，而是时空模型。

```text
语义空间:
  这条事实是什么，属于哪个固定槽，模型用什么语义分组理解它。

物理空间:
  这条事实插到四段式的哪一段，是否应当命中 cache。

时序空间:
  这条事实在哪一轮进入，何时确认，何时重放，何时压缩，何时淘汰，何时恢复。
```

三者不是三套前缀。它们是同一条上下文事实的三个坐标：

```text
ContextCoordinate =
  semantic_slot
  + physical_lane
  + temporal_position
```

其中 `physical_lane` 仍然只有四段。`temporal_position` 不新增前缀种类，只记录事实在长时间交互中的状态。

#### 5.9.1 空间：线插到哪一段

空间判断必须由四段式直接表达：

```text
global_static_prefix
  稳定存在，应该命中。

provider_visible_context_prefix
  已确认旧上下文，应该命中。

current_turn_tail
  当前新增，只能写入候选，本次不应该命中。

never_replay_tail
  当前控制尾，永不重放，不应该命中。
```

所以缓存判断不需要额外声明：

```text
if lane in {global_static_prefix, provider_visible_context_prefix}:
  expected_read = true
else:
  expected_read = false
```

这就是四段式自带的缓存属性。

#### 5.9.2 时间：事实如何长期演化

一条上下文事实的时序流如下：

```text
observed
-> admitted_to_current_turn_tail
-> sent_to_provider
-> confirmed_on_provider_success
-> replayed_from_provider_visible_context_prefix
-> compacted_or_summarized_when_needed
-> retired_or_archived_when_no_longer_active
```

四段各自的时间规则：

| 物理段 | 时间规则 |
| --- | --- |
| `global_static_prefix` | 会话内冻结；变化必须走显式 invalidation，不做静默漂移 |
| `provider_visible_context_prefix` | 只能来自上一轮 provider success 的 confirmed frame；重放时不按语义重新排序 |
| `current_turn_tail` | 只活在当前请求；provider success 后才能晋升到下一帧 |
| `never_replay_tail` | 只活在当前请求；请求结束即消失，不能晋升 |

这解决长期交互的关键问题：系统知道每条事实“什么时候进入、什么时候可信、什么时候可重放、什么时候应该退出”。

本单 agent 架构的时序节拍是 `turn`。每个 turn 是一次上下文收集、provider boundary、工具闭合、输出提交、frame promotion 和释放/恢复判断的节拍；`TurnMemory pending/handoff state` 是 turn 与 turn 之间保存未完全持久化事实的热账本。它不是图结构调度器，也不是第五个物理段。

#### 5.9.3 语义：事实属于哪个稳定集合

语义空间负责让 agent 理解上下文，不负责 cache。固定槽只回答：

```text
这是用户意图？
这是工具 transcript？
这是证据事实？
这是记忆状态？
这是运行控制？
```

语义槽不决定命中，命中只由物理段决定。同一个 `tool_transcript` 在当前轮是 `current_turn_tail`，下一轮确认后才是 `provider_visible_context_prefix`。语义不变，时序状态变，缓存资格随物理段自然变化。

#### 5.9.4 长时间智能交互的闭环

长时间交互需要四个闭环：

```text
append loop:
  当前事实进入 current_turn_tail，保持本轮响应能力。

confirm loop:
  provider success 后写入 confirmed frame，保证下一轮可原样重放。

compact loop:
  当历史过长时，把 confirmed context 压缩为新的稳定事实，保留 origin lineage。

recover loop:
  刷新、失败、fork、继续时，从 latest confirmed frame + current turn snapshot 恢复，不靠猜测。
```

这四个闭环形成时序空间。它们比单纯“拼 prompt”更重要，因为 agent 的长期智能来自稳定的事实演化，而不是每轮重新堆一大段上下文。

#### 5.9.5 设计约束

时空模型必须遵守这些约束：

```text
语义空间不能重排已确认物理帧。
时序恢复不能猜测当前意图。
压缩只能生成新的 confirmed fact，不能改写旧 provider bytes。
current_turn_tail 晋升必须以 provider success 为边界。
never_replay_tail 不能进入 memory/frame/ledger。
cache under-read 必须能定位到空间断点或时序断点。
```

因此，最终架构不是“多加几个前缀”，而是：

```text
语义空间清晰
+ 四段物理空间稳定
+ 时序空间可追踪
= 长时间智能交互
```

### 5.10 四段物理模型与 Turn 生命周期

目标架构必须用同一条 turn 生命周期处理上下文事实：收集事实、归入语义空间、放入四段物理空间、发送 provider、记录边界、确认 frame、提交输出、释放或恢复未提交状态。任何上下文来源都不能绕过这条生命周期链路。

```text
Context Ingress
-> Semantic Space
-> Four-Segment Physical Kernel
-> Provider Payload
-> TurnMemory turn lifecycle state
-> PhysicalPrefixFrameLedger
-> Accounting / Recovery
```

#### 5.10.1 四段是唯一物理内核

四个物理段内部处理必须统一：

```text
global_static_prefix
  固定稳定段。只接受系统确认的静态事实。

provider_visible_context_prefix
  已确认历史段。只接受 provider success 后的 confirmed frame replay。

current_turn_tail
  当前新增段。接收当前用户、工具、证据、steer，本次不期待缓存命中。

never_replay_tail
  当前控制段。接收本轮控制和恢复指令，永不进入长期记忆或 frame。
```

插入的上下文只要进入同一个物理段，就没有物理上的差别：

```text
read evidence current item
tool result current item
user steer current item
runtime memory current item

进入 current_turn_tail 后:
  都是 current-turn append facts
  只在 semantic_slot / origin_ref / payload_schema 上有差别
  不允许各自拥有不同物理排序权威
```

这条规则非常重要：语义可以丰富，物理必须单纯。

#### 5.10.2 语义空间是插入内容自己的差别

接入上下文各自形成语义空间，但语义空间只表达“它是什么”，不表达“它怎么缓存”。

```text
user_intent
tool_transcript
evidence_facts
memory_state
turn_contract
runtime_control
```

这些槽位可以影响：

```text
模型可见分组
同段内的稳定排序
压缩策略
展示和诊断
```

不能影响：

```text
是否 expected cache read
是否能 promote
是否能进入 confirmed frame
是否能重排旧 frame
```

所以架构上应当是：

```text
语义差别:
  slot / origin / payload / visibility

物理差别:
  只有四段 lane
```

#### 5.10.3 稳定 Turn 生命周期算法

每一轮固定执行同一个算法：

```text
Step 1: Observe
  收集用户输入、工具结果、记忆候选、证据候选、运行控制信号。

Step 2: Normalize
  标准化为 IngressContextItem，只保留 ingress_kind、origin_ref、payload。

Step 3: Slot
  映射到固定 SemanticSlot；未知槽失败或走明确 fallback，不临时扩展。

Step 4: Place
  根据四段规则插入 physical lane。

Step 5: Assemble
  按固定顺序拼接：
    global_static_prefix
    -> provider_visible_context_prefix
    -> current_turn_tail
    -> never_replay_tail

Step 6: Invoke
  构造 provider payload；transport contract 只作为 provider request 结构校验。

Step 7: Record and Commit
  TurnMemory 记录 provider request、tool round、assistant draft/final、commit/frame 状态。

Step 8: Promote
  provider success 后，将 eligible current_turn_tail 晋升为下一帧 confirmed context。

Step 9: Maintain
  根据窗口压力做 compaction；根据失败/刷新做 recovery；不改写旧 confirmed bytes。
```

这个生命周期不能根据上下文来源改变。工具、记忆、文件证据、用户 steering 都走同一条链路。

#### 5.10.4 内部处理结构

四段内核的内部结构可以这样落地：

```text
FourSegmentFrame:
  global_static_prefix: tuple[ContextAtom, ...]
  provider_visible_context_prefix: tuple[ContextAtom, ...]
  current_turn_tail: tuple[ContextAtom, ...]
  never_replay_tail: tuple[ContextAtom, ...]
```

`ContextAtom` 是统一物理单元：

```text
ContextAtom:
  semantic_slot
  ingress_kind
  origin_ref
  provider_role_hint
  payload_schema
  payload
  visibility_intent
  content_version_hash
```

注意：`ContextAtom` 不携带物理决策权。它只是被插入某个 lane 后，作为该 lane 的成员存在。

物理身份来自位置：

```text
physical_identity =
  lane
  + lane_local_order
  + origin_ref
```

语义身份来自事实：

```text
semantic_identity =
  semantic_slot
  + ingress_kind
  + origin_ref
```

两者分开，才不会把“语义不同”误判成“物理链路不同”。

#### 5.10.5 长时间上下文连续性的来源

长时间智能交互靠以下机制保持连续：

```text
current_turn_tail
  让 agent 当前轮持续吸收新事实。

provider_visible_context_prefix
  让 agent 下一轮稳定继承已确认事实。

compaction
  把过长历史转化成新的稳定事实，而不是反复搬运旧噪声。

recovery
  从 confirmed frame 和 current snapshot 恢复，而不是从 UI 或模型文本猜测状态。
```

因此系统稳定性不是来自“更多前缀”，而是来自固定的状态流：

```text
收集 -> 归槽 -> 放入四段 -> 响应 -> 记录 -> 确认 -> 重放 -> 维护
```

### 5.11 当前代码中的恢复记忆来源

要判断 turn 之间的即时信息由谁保存，必须反向看 recover 入口实际读取什么。当前代码里存在四类恢复材料，它们职责不同，不能合并成一个新缓存概念。

#### 5.11.1 历史记忆恢复：完整历史或 ContextRecoveryPackage

当 session 没有压缩边界时，runtime 仍从完整 session history 恢复上下文：

```text
session record messages
-> assemble_runtime_history()
-> DynamicContextManager.project(history=...)
-> compiler context messages
```

当 session 已压缩时，恢复材料来自 session memory 的 `ContextRecoveryPackage`：

| 代码位置 | 当前作用 | 结论 |
| --- | --- | --- |
| `backend/harness/entrypoint/runtime_facade.py:236-266` | `_context_recovery_package_for_session()` 调 `memory_facade.session_memory.manager(session_id).load_context_recovery_package()`，并用 `validate_compaction_state()` 校验新鲜度 | 压缩后的历史记忆恢复权威 |
| `backend/harness/entrypoint/runtime_facade.py:268-317` | 只有存在 `compressed_context` 或 provider protocol compaction boundary 时才把 package 放入 `session_context["context_recovery_package"]` | 未压缩历史不依赖 package |
| `backend/harness/runtime/dynamic_context/history_projector.py:76-114` | `_session_context_projection()` 把 package 投影到动态上下文 | package 进入模型上下文 |
| `backend/harness/runtime/compiler.py:4545-4599` | `context_window_report` 记录 package hash、source、coverage | package 被用于诊断和上下文窗口报告 |

结论：

```text
uncompacted history -> full_session_history
compacted history -> ContextRecoveryPackage
```

#### 5.11.2 可恢复任务：ContinuationRecord 和 RecoveryPacket

这条链路恢复的是 task/work，不是普通聊天历史记忆：

| 代码位置 | 当前作用 | 结论 |
| --- | --- | --- |
| `backend/harness/continuation/selector.py:76-124` | `select_session_continuation()` 选择 `ContinuationRecord` 或 interrupted turn record | 找到可恢复工作候选 |
| `backend/harness/continuation/recovery_boundary.py:84-189` | 根据 policy、expected ids、当前 active work 判断是否允许 `resume_recoverable_work` | action permit，不是记忆恢复本体 |
| `backend/harness/continuation/recovery_packet.py:9-58` | `build_recovery_packet()` 生成 confirmed_progress、resume_constraints、artifact_refs、runtime_facts | task resume packet |
| `backend/harness/entrypoint/runtime_facade.py:949-1238` | `_run_recoverable_work_resume_action_request()` 和 `_attach_recovery_packet_to_task_run()` 把 packet 写入 task diagnostics | task executor 恢复入口 |
| `backend/harness/runtime/compiler.py:1440-1446`、`:2018-2023` | task execution packet 把 `recovery_packet` 放入 dynamic payload | 只作用于 task execution |

结论：

```text
ContinuationRecord -> RecoveryBoundary -> RecoveryPacket -> task_execution dynamic payload
```

这不是单 agent 普通 turn 之间的即时记忆缓存，不能让它承担普通对话的 pending state。

#### 5.11.3 普通单 Agent 中断：InterruptedTurnContinuationRecord

实施前，普通单 agent turn 中断后的恢复入口主要来自 turn_run diagnostics，而不是 `TurnMemory` projector：

| 代码位置 | 当前作用 | 结论 |
| --- | --- | --- |
| `backend/harness/runtime/single_agent_host.py:342-424` | runtime 中断时写 `turn_runtime_interruption_recorded`，并在 turn_run diagnostics 标记 `interrupted_turn_continuation_pending` | 中断事实入口 |
| `backend/harness/runtime/single_agent_host.py:445-498` | `_mark_turn_memory_interrupted_handoff()` 同时把 `TurnMemory.status` 标为 `handoff_ready`，`phase=recovering` | TurnMemory 已记录 handoff |
| `backend/harness/continuation/selector.py:370-551` | `_latest_interrupted_turn_record()` 从 turn_run diagnostics 构造 `InterruptedTurnContinuationRecord`，包含 `assistant_visible_stream_continuity` | 当前模型可见中断恢复材料来源 |
| `backend/harness/entrypoint/runtime_facade.py:652-663` | 把 `interrupted_turn_work` 和 `recoverable_work` 放进 `session_context` | single-agent 编译器入口 |
| `backend/harness/runtime/compiler.py:630-640`、`:3173-3234` | compiler 把 `interrupted_turn_work` 投影到 `volatile_runtime_state`，含 visible assistant prefix 和 followup contract | 当前普通 turn 续接依赖 diagnostics/visible prefix |

结论：

```text
runtime interruption diagnostics
-> InterruptedTurnContinuationRecord
-> session_context["interrupted_turn_work"]
-> compiler volatile_runtime_state
```

这条链路能让 agent 继续，但它不是最稳的未提交 turn 状态权威，因为它依赖 turn_run diagnostics 和 visible assistant prefix。`TurnMemory` 已经同步写了 handoff 状态，Phase 0.5 将 compiler 的恢复投影来源切到 `TurnMemory`。

#### 5.11.4 TurnMemory 已有记录，但 projector/recovery 未接入主链路

`TurnMemory` 是当前最接近“turn 之间即时信息状态”的持久化结构：

| 状态材料 | 字段 / 代码证据 | 职责 |
| --- | --- | --- |
| 当前输入追加 | `TurnMemoryRecord.current_user_message_ref/current_append_hash` | 记录本 turn current append |
| provider 边界 | `provider_request_refs/provider_payload_manifest_refs` | 保存 provider request / manifest refs |
| 工具闭合 | `tool_rounds/closed_tool_round_refs/pending_tool_summary` | 保存同一 turn reentry 所需工具事实 |
| assistant draft | `assistant_draft_ref/assistant_draft_sha256/public_event_cursor` | 支持断线或刷新后定位未完成输出 |
| assistant final | `assistant_final_ref/assistant_final_sha256` | final 已生成时，commit 失败不能重跑模型 |
| commit/frame pending | `commit_state/session_commit_ref/frame_promotion_ref/pending_commit_summary` | 区分补提交和补 frame 晋升 |
| handoff/recovery | `status=handoff_ready/recovery_state/recovery_decision_ref` | runtime 中断后的未提交 turn 状态 |
| release | `release_state/released_at/tombstone_hash` | handoff 被后续 turn 消费后的释放凭证 |

实施前，主动运行链路未消费它的 projector/recovery：

```text
backend/runtime/turn_memory/turn_memory_projector.py
  project_current_turn_context()
  project_handoff_context()

backend/runtime/turn_memory/turn_memory_recovery.py
  decide_turn_memory_recovery()
```

实施前代码搜索结果显示，以上函数只在 `backend/runtime/turn_memory/__init__.py` 导出，并被设计文档引用；active runtime 中没有消费者。Phase 0.5 已把它们接入 `runtime_facade -> compiler`。

2026-06-29 代码审查补充：

| 审查项 | 实际结果 | 处理要求 |
| --- | --- | --- |
| `TurnMemoryStore` 落盘 | `storage/runtime_state/turn_memory` 已有真实 turn JSON、checkpoints、tombstones；状态覆盖 `terminal/handoff_ready/released/active/frame_pending` | 继续使用现有账本，不新建 hot journal |
| `assistant_draft_ref` | 字段和 `update_assistant_draft()` 存在，但 active runtime 没有真实调用点，存量数据未发现非空 draft ref | 不把 draft recovery 当作已完成能力；本轮只保留裁决分支并标明 writer 缺口 |
| projector/recovery 消费 | `project_current_turn_context()`、`project_handoff_context()`、`decide_turn_memory_recovery()` 没有进入 `runtime_facade -> compiler` 主链路 | 本轮必须接入 `session_context["turn_memory_recovery"]` 并由 compiler 投影为模型可见 runtime signal |
| 旧 interrupted chain | `InterruptedTurnContinuationRecord` 仍从 turn_run diagnostics / visible prefix 构造 | 旧链路只可作为选择诊断；不得进入 compiler active payload；active 权威转交给 TurnMemory |

目标判断：

```text
已有存储: TurnMemory pending/handoff state
缺失接线: TurnMemory recovery projection -> single-agent context assembly
错误方向: 新建第二套即时状态账本
```

历史命名校准：

```text
TurnWorkingMemory 是早期设计里“当前 turn 热工作区”的名字。
当前 active code 没有 TurnWorkingMemory 类。
旧计划已经把 TurnWorkingMemory 深化并落地为统一 TurnMemory：
  live layer
  checkpoint layer
  handoff layer
  release layer
```

因此本方案中的“turn 之间即时信息状态”对应现有 `TurnMemory`，不是 `memory_system.WorkingMemoryService`，也不是新的第二套账本。

#### 5.11.5 其他短期状态结构的边界

| 结构 | 代码位置 | 边界 |
| --- | --- | --- |
| `ActiveTurnRegistry` | `backend/harness/runtime/active_turn.py:62-90` | 当前 live turn handle。runtime instance 变更后会 terminal，不是 durable recovery memory。 |
| `QueuedUserInputStore` | `backend/runtime/shared/queued_user_input_store.py:69-174` | 存放 queued/dispatching 用户输入和 active steer。被 claim 后应写入 turn 消息和 `TurnMemory.active_steer_refs`。 |
| `PhysicalPrefixFrameLedger.turn_snapshot` | `backend/runtime/context_management/physical_prefix_frame_ledger.py:1009-1065` | confirmed frame 和 provider success snapshot 权威。它保存恢复契约，但不替代 TurnMemory 的 pending state。 |

所以当前恢复记忆的完整权威划分应是：

```text
历史已提交记忆:
  full session history 或 ContextRecoveryPackage

已确认旧 provider prefix:
  PhysicalPrefixFrameLedger

可恢复 task:
  ContinuationRecord + RecoveryPacket

普通单 agent 未提交 turn 状态:
  TurnMemory pending/handoff state

运行中 live handle:
  ActiveTurnRegistry

未消费用户追加/steer:
  QueuedUserInputStore -> TurnMemory.active_steer_refs
```

### 5.12 单 Agent 未提交 Turn 状态与恢复投影归位

本方案当前范围只处理单 agent 主链路：

```text
single_agent_turn
-> TurnMemory
-> ModelRuntime
-> PhysicalPrefixFrameLedger
-> next single_agent_turn
```

不纳入本轮梳理：

```text
graph / node / edge runtime
memory_system.WorkingMemoryService graph/task working memory
turn_to_task_context_handoff
task executor inherited_start_context
```

这些结构可以以后单独审计；它们不能影响本轮 single-agent turn pending/handoff 状态权威。这里排除的是 `memory_system.WorkingMemoryService`，不是历史命名里的 `TurnWorkingMemory`。

#### 5.12.1 问题定义：turn 边界之间存在未提交状态

`turn` 是 single-agent 对话生命周期的主边界。边界之间存在尚未完全提交、尚未进入 confirmed physical frame、但恢复或下一次 provider reentry 必须可见的状态：

```text
assistant draft 已产生但 final 未提交
assistant final 已产生但 session commit 未完成
session commit 已完成但 physical frame 未确认
provider request 已完成但 cache/frame accounting 尚未收口
工具观察已闭合但下一次 provider reentry 尚未消化
active steer 已接收但还没到下一次模型边界
前端刷新/后端中断后需要继续同一条单 agent 语义链
```

这些事实不能直接进入 durable memory，也不能混进 confirmed old prefix。它们应由 `TurnMemory pending/handoff state` 持有，并由投影层按语义槽接入四段物理模型。

#### 5.12.2 当前代码里已有的状态结构

当前 single-agent 未提交状态已经在 `TurnMemory` 里：

| 未提交状态 | 代码字段 / 证据 | 当前作用 |
| --- | --- | --- |
| 当前输入追加 | `TurnMemoryRecord.current_user_message_ref/current_append_hash`，`single_agent_turn.py:1737-1756` | 记录本轮 current append，不等于 confirmed prefix |
| provider 进行中/已返回 | `provider_request_refs/provider_payload_manifest_refs`，`model_runtime.py:1228-1338` | provider 边界检查点 |
| 工具观察闭合 | `tool_rounds/closed_tool_round_refs/pending_tool_summary`，`turn_memory_store.py:296-333` | 同一 turn 内 reentry 的 pending facts |
| assistant draft | `assistant_draft_ref/assistant_draft_sha256/public_event_cursor`，`turn_memory_store.py:191-210` | 断线/刷新时恢复未完成输出 |
| assistant final | `assistant_final_ref/assistant_final_sha256`，`single_agent_turn.py:9547-9553` | final 已有，commit 失败时不能重跑模型 |
| commit/frame pending | `commit_state/session_commit_ref/frame_promotion_ref/pending_commit_summary`，`turn_memory_store.py:412-454` | 区分待提交和待 frame 确认 |
| recovery handoff | `status=handoff_ready`，`single_agent_host.py:416-498` | 单 agent 运行中断后的恢复入口 |
| release tombstone | `release_state/released_at/tombstone_hash`，`turn_memory_store.py:485-520` | pending/handoff 状态被消费后的释放凭证 |

这说明不需要新建独立的第二套即时状态账本。正确做法是接通现有 `TurnMemory pending/handoff state`。

#### 5.12.3 目标定义：TurnMemory pending/handoff state

目标命名使用现有对象，不新造模块：

```text
TurnMemory pending/handoff state
```

归属：

```text
TurnMemory 内部生命周期层
```

职责：

```text
保存当前 turn 生命周期内尚未完全提交、尚未进入 confirmed physical frame、但恢复或下一次 provider boundary 必须可见的 refs/hash/summary。
```

它已经保存或应该保存：

```text
refs:
  provider_request_refs
  provider_payload_manifest_refs
  assistant_draft_ref
  assistant_final_ref
  session_commit_ref
  frame_promotion_ref
  closed_tool_round_refs

hashes:
  current_append_hash
  assistant_draft_sha256
  assistant_final_sha256
  checkpoint_hash

compact summaries:
  pending_tool_summary
  pending_commit_summary
  public_event_cursor
  active_steer_refs
  recovery_state
```

它禁止保存或决定：

```text
confirmed old prefix bytes
physical lane
prefix identity
cache read expectation
durable memory promotion
UI replay text as runtime fact
graph/task working memory
```

#### 5.12.4 单 Agent pending/handoff 状态生命周期

```text
Turn N starts
-> TurnMemory.active
-> TurnMemory records current input refs / provider refs / tool refs / draft refs
-> assistant final ready
-> session commit pending or committed
-> physical frame pending or confirmed
-> Turn N terminal
-> if confirmed frame covers facts:
     release pending/handoff payload and keep tombstone
   else:
     status = handoff_ready / frame_pending / commit_pending
     next turn can read TurnMemory recovery projection
```

重要边界：

```text
TurnMemory pending/handoff state 是未提交 turn 状态，不是长期记忆。
PhysicalPrefixFrameLedger 确认后，相关 pending/handoff payload 必须释放或降为 tombstone。
如果 commit/frame 失败，恢复只补 commit/frame，不重跑模型。
如果后端中断，恢复从 TurnMemory checkpoint + latest confirmed frame 继续。
```

#### 5.12.5 和四段式物理模型的关系

TurnMemory pending/handoff state 不新增第五段。它只决定“下一轮该把哪些尚未 confirmed 的事实重新投影为 current_turn_tail 中的恢复事实，并同时提供 runtime recovery signal”。

```text
confirmed old facts:
  PhysicalPrefixFrameLedger -> provider_visible_context_prefix

pending/handoff turn facts:
  TurnMemory pending/handoff projection -> current_turn_tail recovery facts + runtime recovery signal

runtime control:
  Dynamic tail builder -> never_replay_tail
```

所以四段式仍然是唯一物理模型：

```text
global_static_prefix
provider_visible_context_prefix
current_turn_tail
never_replay_tail
```

pending/handoff state 是 turn 生命周期状态，不是物理段。

#### 5.12.6 当前缺线

当前代码已有 `TurnMemory` 数据和 projector：

```text
backend/runtime/turn_memory/turn_memory_projector.py
  project_current_turn_context()
  project_handoff_context()
```

但单 agent 上下文拼接链路还没有明确消费它们。当前缺线是：

```text
TurnMemory pending/handoff projection
-> ContextIngress / SemanticSpaceRegistry
-> FourSegmentPhysicalKernel.current_turn_tail
```

目标修复不是新增账本，而是接通这条线：

```text
single_agent_turn starts
-> load latest unreleased TurnMemory pending/handoff projection
-> normalize as TurnMemoryRecoveryContextItem
-> slot into fixed semantic slots
-> place recovery facts into current_turn_tail
-> attach recovery control signal to never_replay_tail only when it is a current-turn operating contract
-> provider success 后由 PhysicalPrefixFrameLedger 覆盖
-> release TurnMemory pending/handoff payload
```

## 6. 目标权威链路

```text
ContextIngress
-> SemanticSpaceRegistry
-> FourSegmentPhysicalKernel
-> ProviderPayloadManifest
-> ProviderModelInvocation
-> TurnMemoryStore pending/handoff state
-> PhysicalPrefixFrameLedger
-> CacheAccounting / StabilityReport
-> Recovery / API / Frontend health presentation
```

权威表：

| 层 | 目标职责 | 禁止职责 |
| --- | --- | --- |
| ContextIngress | 产出上下文事实、ingress_kind、origin_ref、payload | 不判断物理段，不判断 cache read |
| SemanticSpaceRegistry | 将事实归入固定 semantic slot | 不创建物理 lane，不发明临时槽 |
| FourSegmentPhysicalKernel | 唯一分配四段 lane，并按四段顺序拼接 | 不按来源创建特殊物理路径 |
| ProviderPayloadManifest | 生成真实 provider segment、serialized hash、transport contract 诊断 | 不用 `ppseg` 承担跨 turn identity |
| ProviderModelInvocation | 发送 provider 请求并收集 usage | 不解释上下文语义 |
| TurnMemoryStore pending/handoff state | 按 turn 边界记录 provider request、tool round、draft/final、commit、frame、terminal、handoff、release 状态 | 不决定四段 lane，不确认 old prefix frame，不解释 cache health，不替代 durable memory |
| PhysicalPrefixFrameLedger | provider success 后确认 frame，维护 replay/compaction/recovery snapshot 状态 | 不从 semantic slot 重排旧 frame，不保存普通 turn pending state |
| CacheAccounting / StabilityReport | 按四段和 provider usage 判断 expected read | 不用总 hit ratio 判定成功 |
| Recovery / API / Frontend | 展示 prefix health、under-read、context recovery、turn handoff 状态 | 不把 UI 状态、visible stream 文本或 terminal diagnostics 当唯一恢复权威 |

### 6.1 代码管理架构审查

本轮同步审查结论：当前不是缺目录，而是缺少足够窄的 public facade 和可检查的跨层边界。领域模块已经存在，但 active 调用仍会直接穿透内部函数，导致管理规则依赖人工记忆。

现有结构事实：

| 区域 | 当前代码事实 | 管理风险 | 目标管理方式 |
| --- | --- | --- | --- |
| `backend/runtime/context_management/__init__.py` | 同时导出 pipeline、policy、physical plan、frame ledger、provider-visible ledger、tool transcript、tool result store | public API 面太宽，调用方可以绕过 ContextIngress / SemanticSpaceRegistry / FourSegmentPhysicalKernel 的顺序 | 拆成窄 facade：`context_pipeline` 负责组装入口，`physical_context_plan` 负责四段 lane，ledger 只通过明确 commit/replay API 暴露 |
| `backend/harness/entrypoint/runtime_facade.py:649-674` | entrypoint 负责 session continuation，同时接入 `turn_memory_recovery` | entrypoint 可以调度，但不应拥有 TurnMemory recovery candidate 选择算法 | 下沉到 `runtime.turn_memory` public API；entrypoint 只调用 `build_turn_memory_recovery_context(...)` |
| `backend/harness/entrypoint/runtime_facade.py:3730-3805` | `_turn_memory_recovery_context()` 和 recovery candidate 判断临时位于 entrypoint | 恢复选择规则散在 harness，会再次形成“拼接式权威” | 迁入 `runtime/turn_memory/turn_memory_recovery_context.py` 或 `turn_memory_selector.py` |
| `backend/harness/runtime/compiler.py:599-640` | compiler 汇总 dynamic context、runtime signals、TurnMemory recovery projection | compiler 适合 assemble，不适合选择恢复对象或解释 TurnMemory 生命周期 | 只消费标准投影 payload，不直接扫描 store，不决定 recovery action |
| `backend/runtime/model_gateway/model_runtime.py:1228-1338` | provider request/result 写入 TurnMemory checkpoint | provider boundary 写账本是合理的，但不应手动拼 TurnMemory checkpoint payload 细节 | 通过 `TurnMemoryStore.record_provider_*` 或更窄 writer facade 写入 |
| `backend/runtime/model_gateway/model_runtime.py:1499-1585` | provider success 同时确认 provider-visible ledger 和 physical frame | provider invocation 可以触发 success event，但 physical frame promotion 应由 context_management 的 commit facade 完成 | 新增或明确 `context_management.commit_provider_success(...)`，model runtime 只传 provider success receipt |
| `backend/runtime/model_gateway/provider_payload.py:921-954` | provider payload 输出 physical cache spine 诊断 | provider payload 是传输权威，但不应反向决定 semantic identity 或 lifecycle | 只消费 physical plan / prefix identity，不自行重新定义跨 turn identity |
| `backend/runtime/prompt_accounting/*` | cache planner、stability report、provider ledger 分散解释 cache 状态 | 容易再次回到 total hit ratio 或 messages-only 解释 | 只读取 ProviderPayloadManifest + provider usage，不决定上下文归属 |

管理结论：

```text
harness 可以调度 turn，但不能拥有领域选择算法。
runtime 子系统可以记录和传输事实，但不能改写 agent 语义决策。
context_management 是四段物理上下文权威，但 public API 必须变窄。
turn_memory 是单 agent pending/handoff 状态权威，恢复选择不能散落在 entrypoint。
prompt_accounting 是核算/诊断权威，不反向修改上下文拼接。
```

因此，本方案后续不仅要修 prefix identity，还要建立代码管理约束：

```text
每个领域只暴露 public facade。
跨领域调用只能调用 facade，不直接 import 内部 policy/ledger/helper。
facade 名称必须表达权威：selector / projector / writer / committer / reporter。
旧 helper 若没有领域 owner，删除或降为 diagnostics。
```

### 6.2 目标代码管理边界

目标不新增“大中台”，而是用小而明确的 facade 固化权威链。

| 目标 facade | 所属领域 | 允许职责 | 禁止职责 |
| --- | --- | --- | --- |
| `runtime.turn_memory.build_turn_memory_recovery_context` | TurnMemory | 选择 latest unreleased pending/handoff turn，调用 projector/recovery，产出标准 recovery context | 读取 UI visible stream，决定 physical lane |
| `runtime.turn_memory.record_provider_boundary` | TurnMemory | 接收 provider request/result receipt，写 provider refs/checkpoint | 解释 provider cache health |
| `runtime.context_management.build_context_pipeline` | ContextManagement | 统一调用 capability filter、provider-visible replay、physical plan | 让调用方单独重排 ledger replay |
| `runtime.context_management.commit_provider_success` | ContextManagement | provider success 后确认 provider-visible ledger 和 physical frame | 调 provider，解释模型输出 |
| `runtime.model_gateway.build_provider_payload_manifest` | ModelGateway | 绑定 provider messages/tools/params，输出 request-local transport manifest | 决定 semantic slot 或 durable memory |
| `runtime.prompt_accounting.prefix_cache_health.evaluate_prefix_cache_health` | PromptAccounting | 基于 provider payload manifest 和 provider usage 输出 prefix cache health | 重新分类上下文或改变 prompt |
| `runtime.prompt_accounting.provider_cache_bus` | PromptAccounting | 写入 provider cache ledger，并向 API/health/frontend 提供只读日志视图 | 重新判断 cache health 或回写上下文 |
| `harness.runtime.compiler.compile_single_agent_turn_packet` | Harness compiler | 组装 agent-visible prompt packet 和 current runtime signals | 扫描 TurnMemoryStore，选择恢复对象 |

跨层导入规则：

```text
harness -> runtime.turn_memory public facade: allowed
harness -> runtime.context_management public facade: allowed
harness -> runtime.model_gateway protocol sanitizer/lightweight helpers: limited, should shrink
model_gateway -> context_management commit facade: allowed
model_gateway -> context_management internal ledger functions: target remove
prompt_accounting -> provider payload manifest / usage records: allowed
prompt_accounting -> context segment policy rewrite: forbidden
api/frontend -> projections only: allowed
api/frontend -> runtime decision helpers: forbidden
```

## 7. 固定执行流

### Stage A: 候选归一

输入：

```text
compiler source specs
tool transcript append
memory/evidence candidates
project/env/tool static specs
dynamic tail contracts
```

输出：

```text
ContextCandidate[]
semantic_slot
origin_authority
origin_ref
```

禁止：

```text
不生成 provider payload ordinal
不决定 expected cache read
不把 lifecycle word 写进 prompt text
```

### Stage B: Prefix Identity 生成

输入：

```text
ContextCandidate
ContextSegmentRegistry declaration
current lifecycle source
```

输出：

```text
PrefixIdentity(logical fields only)
```

规则：

```text
logical_segment_ref seed 不含 content_hash
origin_ref 不含 request_ordinal
current append 的 lifecycle_state 必须是 pending
confirmed replay 必须带 frame_ref + frame_ordinal
```

### Stage C: 物理拼接

固定顺序：

```text
provider transport contract
  native tool schema / params / response format
  cache family only, not a context physical segment
-> global_static_prefix
-> provider_visible_context_prefix confirmed frame replay
-> current_turn_tail current append
-> never_replay_tail dynamic tail
```

不变量：

```text
confirmed frame replay must keep frame segment order and provider bytes
current append can only get new request ordinals after confirmed replay
dynamic tail never promotes
```

### Stage D: Provider Payload 序列化

输出：

```text
ProviderPayloadSegment[]
request_ordinal
provider_serialized_hash
physical_cache_spine
prefix_identity_chain_hash
provider_byte_chain_hash
```

规则：

```text
ppseg remains request-local
prefix_identity is the cross-turn identity
physical_cache_spine includes only expected-read segments
tools/system/messages all belong to one provider physical spine
```

### Stage E: Provider success 晋升

provider success 后：

```text
current append write_candidate
-> confirmed_frame_replay in next frame
```

晋升时保存：

```text
logical identity sequence
provider serialized hash sequence
frame ordinal
provider message copy
provider_visible_hash
source request id / response ref
```

禁止：

```text
provider failure 后 promote
dynamic tail promote
重新按 semantic_slot 或 tool_round 重排旧 frame
```

### Stage F: 诊断与展示

诊断必须优先输出：

```text
cache_status
provider_under_read_tokens
expected_prefix_tokens
first_missing_expected_prefix_identity
break_type: identity / content / position / transport_contract
previous identity at ordinal
current identity at ordinal
provider_serialized_hash diff
```

UI/API 不再把总 `cached_tokens / prompt_tokens` 作为第一健康判断。

## 8. 文件级执行清单

| 文件 | 当前问题 | 目标动作 |
| --- | --- | --- |
| `backend/runtime/context_management/context_segment_registry.py` | semantic_slot 已存在但不是 prefix identity 主键 | 将 kind/slot/origin 作为 PrefixIdentity 输入 |
| `backend/runtime/context_management/context_segment_policy.py` | cache role 可影响 seal/stable 判断 | 保留分类，但停止让 cache role 反向定义 identity |
| `backend/runtime/context_management/physical_context_plan.py` | 已有四段式 lane，但缺 lifecycle identity 契约 | 输出 lane + lifecycle，不把 current append 计入 expected read |
| `backend/runtime/context_management/physical_prefix_frame_models.py` | frame segment 保存 content/hash/ordinal，但缺 prefix_identity | 增加 identity sequence、provider serialized hash sequence、frame ordinal |
| `backend/runtime/context_management/physical_prefix_frame_ledger.py` | frame_id seed 仍依赖 segment_id/content_hash | 按 provider success 保存 confirmed frame，不重排、不猜测 |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | item key fallback 可含 provider_visible_hash | 改为 stable origin_ref；content hash 只作 version |
| `backend/runtime/model_gateway/provider_payload.py` | `ppseg`、`logical_segment_ref`、`_segments_hash` 混合身份/内容/位置 | 新增 `prefix_identity` object；`ppseg` 保持 request-local |
| `backend/runtime/prompt_accounting/stability_report.py` | ordinal + content hash diff 不够 | 增加 identity/content/position/provider-byte diff |
| `backend/runtime/prompt_accounting/cache_planner.py` | physical spine total-only 估算 | expected read 只来自 lifecycle，并输出 first uncovered identity |
| `backend/runtime/prompt_accounting/provider_cache_ledger.py` | 已有 provider_under_read 状态 | 将 under-read 明确作为 prefix health failure |
| `backend/runtime/prompt_accounting/provider_cache_bus.py` | provider cache telemetry 缺少单一发布/读取总线 | 写入 `provider_cache_ledger.jsonl`，并给 API/health/frontend 提供只读日志视图 |
| `backend/api/tokens.py` / `backend/health_system/governance.py` | health/report contract 可能仍偏总命中率或重复拼装日志 | 只消费 provider cache bus，输出 prefix coverage / under-read / first break |
| `frontend/src/lib/api/types.ts` | 类型缺 prefix health 结构 | 增加结构化 prefix health 类型 |
| `frontend/src/components/chat/ChatPanel.tsx` | 可能把 cached ratio 当健康展示 | UI 投影改为 prefix coverage first，只展示 provider cache bus 结论 |
| `backend/runtime/turn_memory/turn_memory_recovery_context.py` | 目前 recovery candidate 选择临时在 `runtime_facade.py` | 新增/迁入 TurnMemory recovery context facade |
| `backend/harness/entrypoint/runtime_facade.py` | 调度层仍含 TurnMemory candidate 选择细节 | 只调用 `runtime.turn_memory` facade，不拥有恢复选择算法 |
| `backend/runtime/context_management/__init__.py` | public API 面过宽，导出多个内部 policy/ledger/helper | 标记窄 facade 清单，后续禁止新调用直接穿透内部 |
| `backend/runtime/model_gateway/model_runtime.py` | provider success 直接调用 provider-visible ledger / physical frame ledger / TurnMemory writer | 分阶段改为调用 context commit facade 和 TurnMemory writer facade |

## 9. 旧链路清理标准

确认实施后，不保留旧链路兼容。以下路径应删除或改为只读诊断：

| 候选 | 为什么没有目标权威 | 替代 |
| --- | --- | --- |
| `logical_segment_ref(kind + semantic + slot + content_hash)` | 混合逻辑身份和内容版本 | `PrefixIdentity.logical_segment_ref` + `content_version_hash` |
| `ppseg` 跨 turn 比较 | 含 request ordinal，是 request-local id | `prefix_identity.logical_segment_ref` |
| provider-visible item key fallback 含 `provider_visible_hash` | 内容变化会变成新身份 | stable `origin_ref` + content version |
| `prefix_family` 单独判断身份 | 只能表达物理大类 | `semantic_slot + origin_ref + lifecycle_state` |
| stability report 只看 ordinal/content | 无法区分 identity drift / position drift | identity chain diff |
| cache planner 只报 total coverage | 不能定位第一个 missing prefix | first missing expected identity |
| UI 用 hit ratio 表示缓存健康 | 会误导 77.19% 这类 under-read | prefix coverage + under-read |
| current append 被 session_stable 化后进入 expected read | 本次不可能已缓存 | pending/write_candidate lifecycle |
| `interrupted_turn_work` visible prefix 作为普通 turn 恢复权威 | 来源是 turn_run diagnostics / UI visible stream，不是未提交 turn 状态账本 | `TurnMemory pending/handoff projection`；旧记录只可作为只读诊断，不进入模型可见 active payload |
| `runtime_facade.py` 内部保存 TurnMemory recovery candidate 选择规则 | 调度层拥有了 TurnMemory 领域选择算法 | `runtime.turn_memory.build_turn_memory_recovery_context` |
| 宽 `runtime.context_management.__init__` 被新代码直接依赖内部 helper | public API 无法表达领域边界 | 窄 facade + 内部模块只由领域 facade 调用 |
| `model_runtime.py` 直接操作多个 context ledger 内部函数 | provider invocation 层同时承担 context commit orchestration | `runtime.context_management.commit_provider_success` |

保留条件只有一个：该代码在目标权威链中有明确 current owner。否则删除、合并或改成 diagnostics。

## 10. 分阶段实施计划

### Phase 0: 锁定边界

目标：确认本方案只处理 prefix identity / cache authority，不回滚已落地的 terminal/sorting 修复。

动作：

- 检查 `chat_refresh_hot_recovery_terminal_invariant_plan_20260629.md` 对应改动是否仍然通顺。
- 检查当前 dirty worktree，避免覆盖用户或已有修复。
- 不新增测试文件。

完成标准：

```text
runtime terminal/sorting 修复保持现状
prefix identity 重构边界明确
```

### Phase 0.5: TurnMemory 恢复权威接线

目标：先把单 agent turn 间即时状态的权威从 `interrupted_turn_work` 转交给 `TurnMemory pending/handoff state`。

涉及文件：

- `backend/runtime/turn_memory/turn_memory_recovery.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/runtime/compiler.py`
- 本计划文档

改动：

1. `decide_turn_memory_recovery()` 明确支持 `handoff_ready`，输出 `recover_interrupted_turn`。
2. `runtime_facade` 在每轮普通 single-agent turn 前读取最新 unreleased pending/handoff `TurnMemory`。
3. 将 `TurnMemory` decision、handoff projection、current turn projection 归一为 `session_context["turn_memory_recovery"]`。
4. `compiler` 优先消费 `turn_memory_recovery` 并投影到 current runtime signals。
5. 删除 compiler 对 `interrupted_turn_work` 的模型可见消费路径。

完成标准：

```text
TurnMemory projector/recovery 有 active runtime consumer
普通 single-agent 中断恢复的模型可见事实来自 TurnMemory recovery projection
visible_assistant_prefix 不再是模型可见恢复权威
不新增 TurnWorkingMemory / HotJournal 第二套账本
```

### Phase 0.6: 管理架构 facade 收口

目标：把 Phase 0.5 临时接线中暴露出的管理问题收束掉，让领域选择算法回到领域模块，`harness` 只保留调度和组装职责。

涉及文件：

- `backend/runtime/turn_memory/__init__.py`
- 新增或就地实现：`backend/runtime/turn_memory/turn_memory_recovery_context.py`
- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/runtime/compiler.py`
- `backend/runtime/context_management/__init__.py`
- 后续阶段涉及：`backend/runtime/model_gateway/model_runtime.py`

改动：

1. 将 `_turn_memory_recovery_context()` 和 `_turn_memory_record_is_recovery_candidate()` 从 `runtime_facade.py` 下沉到 `runtime.turn_memory`。
2. `runtime.turn_memory` 暴露唯一恢复入口：`build_turn_memory_recovery_context(store, session_id=...)`。
3. `runtime_facade.py` 只调用该 facade，并把结果放入 `session_context["turn_memory_recovery"]`。
4. `compiler.py` 保持只消费标准 payload，不 import store，不扫描 TurnMemory。
5. 对 `runtime/context_management/__init__.py` 做 public API 审查，标记后续要收窄的导出，不在本阶段大搬文件。
6. 为 `model_runtime.py` 记录后续收口点：provider success 触发 context commit facade，而不是直接操作多个 ledger 内部函数。

完成标准：

```text
TurnMemory recovery selection authority 位于 runtime.turn_memory
harness entrypoint 不再包含 TurnMemory candidate 选择规则
compiler 只消费 projected payload
context_management public API 收窄清单明确
model_gateway -> context_management 内部 ledger 直接调用列入后续删除候选
```

实施记录：

```text
2026-06-29:
  新增 backend/runtime/turn_memory/turn_memory_recovery_context.py
  导出 build_turn_memory_recovery_context()
  runtime_facade.py 改为只调用 runtime.turn_memory facade
  compiler.py 只接受 authority=runtime.turn_memory.recovery_context
  删除 runtime_facade.py 内 TurnMemory candidate 选择规则
  continuation_selection 内 TurnMemory recovery 元信息同步引用 runtime.turn_memory.recovery_context，不再声明 harness 选择权威
  interrupted_turn_work 不再进入 compiler 的模型可见恢复段；visible_assistant_prefix 仍仅留在 continuation record/selector 元数据，列入后续 continuation 旧字段收窄/删除审查
```

### Phase 1: 建立 PrefixIdentityAuthority

目标：从现有字段中拆出 canonical prefix identity。

涉及文件：

- `context_segment_registry.py`
- `context_segment_policy.py`
- 新增或就地实现：`context_prefix_identity.py`
- `provider_payload.py`

改动：

1. 定义 `PrefixIdentity` dataclass / typed dict。
2. `logical_segment_ref` seed 移除 `content_hash`。
3. `origin_ref` 使用稳定业务来源，例如 turn id、tool round id、tool call id、memory selection id、evidence cursor id。
4. `content_version_hash` 和 `provider_serialized_hash` 独立。
5. `ppseg` 明确标注为 request-local。

完成标准：

```text
同一 logical segment 内容变化时 identity 不变、content_version_hash 变化
同一内容移动位置时 identity 不变、request_ordinal 变化
```

实施记录：

```text
2026-06-29:
  新增 backend/runtime/context_management/context_prefix_identity.py
  定义 PrefixIdentity / context_prefix_identity.v1 / runtime.context_management.context_prefix_identity
  logical_segment_ref seed 改为 prefix_domain + physical_lane + semantic_slot + origin_authority + origin_ref，不再包含 content hash
  ProviderPayloadSegment 增加 content_version_hash、provider_serialized_hash、prefix_segment_ref、prefix_identity
  prompt_accounting serializer / ledger / models 透传 canonical prefix identity
  physical_prefix_frame_models / ledger / assembler 透传 confirmed-frame replay identity 与 provider serialized hash
  provider_visible_context_ledger item key 改为 origin_ref + semantic_slot + origin_authority 优先；provider_visible_hash 只作为缺 origin_ref 的诊断 fallback
  harness follow-up current append metadata 改为 context_identity_policy=origin_ref_stable，并补齐 context_origin_authority / context_origin_ref
  followup_context_rebase 对 current append 与 current-turn exact old context 补齐 origin-ref identity
  内存验证通过：
    same_identity_content_changed=True
    content_version_changed=True
    provider_serialized_changed=True
    same_identity_position_changed=True
    request_ordinal_changed=True
    request-local ppseg changed=True
```

### Phase 2: 收紧 ProviderPayload physical spine

目标：expected read 只包含 static prefix 和 confirmed frame replay。

涉及文件：

- `provider_payload.py`
- `physical_context_plan.py`
- `physical_prefix_frame_models.py`

改动：

1. `_is_physical_cache_spine_message_segment()` 不再只看 lane + included。
2. provider-visible context 进入 spine 必须满足 `lifecycle_state=confirmed_frame_replay`。
3. current append 即使 lane/role 看起来稳定，也只能是 `write_candidate`。
4. physical spine segment 保留 prefix_identity / provider_serialized_hash；不在本阶段重复生成额外 chain hash。

完成标准：

```text
current append 不再进入本次 expected read
physical spine segment list 可映射到 prefix identity sequence
```

实施记录：

```text
2026-06-29:
  provider_payload.py 的 message spine participation 不再只看 lane
  provider_visible_context_prefix 必须是 lifecycle_state=confirmed_frame_replay 且 cache_read_expectation=expected_read 才能进入 physical cache spine
  current_turn_tail / provider_visible_prefix_unconfirmed 标为 write_candidate 或 excluded，不能进入本次 expected read
  _physical_cache_spine_segments() 增加 spine segment gate，遇到 included 但非 expected-read 的消息即停止 prefix spine
  收缩实现：transport selector 不生成完整 prefix_identity；额外 identity/provider-byte chain hash 不在本阶段落地
  内存验证通过：
    global_static_prefix -> expected_read/included
    provider_visible_context_prefix + unconfirmed -> write_candidate/excluded
    current_turn_tail -> write_candidate/excluded
    未确认 append 后的内容不会被误算进 physical spine
```

### Phase 3: 重写 frame promotion / replay 身份

目标：confirmed frame 成为跨 turn 旧上下文的唯一物理权威。

涉及文件：

- `physical_prefix_frame_ledger.py`
- `physical_prefix_frame_models.py`
- `provider_visible_context_ledger.py`

改动：

1. frame 保存 provider message copy、provider serialized hash、prefix identity。
2. provider success 后只 promote current append，且按本次 provider payload 顺序追加。
3. 下一次 request replay 旧 frame 时不按 semantic slot、entry index 或 tool round 重排。
4. provider-visible ledger 的 key fallback 不再使用 content hash 作为 identity。

完成标准：

```text
previous frame identity sequence 是 current request prefix identity sequence 的严格前缀
previous frame provider byte hash sequence 是 current request byte hash sequence 的严格前缀
```

实施记录：

```text
2026-06-29:
  physical_prefix_frame_ledger.py promotion 时优先继承 provider payload prefix_identity 的 origin_authority / origin_ref
  _frame_segment_metadata() 保留 context_origin_authority / context_origin_ref / context_identity_policy 等身份字段，避免 source_ref 与 origin_ref 不一致时晋升漂移
  current append 在 provider success 后按 current_append_entry_indexes 拉入 confirmed frame，并晋升为 provider_visible_context_prefix + confirmed_frame_replay
  physical_context_assembler.py replay confirmed frame 时继续携带 context_prefix_identity / logical_segment_ref / provider_serialized_hash
  内存验证通过：
    source_ref != origin_ref 时，frame promotion 后 origin_ref 保持不变
    promoted lane=provider_visible_context_prefix
    promoted lifecycle_state=confirmed_frame_replay
    frame replay 后下一次 provider payload 的 logical_segment_ref 与 frame 内保存值完全一致
```

### Phase 4: 重做 stability/cache reporting

目标：让报告能解释为什么 77.19% 仍然失败。

涉及文件：

- `prefix_cache_health.py`
- `stability_report.py`
- `cache_planner.py`
- `provider_cache_ledger.py`
- `provider_cache_bus.py`
- `backend/api/tokens.py`
- `backend/health_system/governance.py`
- `frontend/src/lib/api/types.ts`
- `frontend/src/components/chat/ChatPanel.tsx`

改动：

1. 先建立单一核心算法：`runtime.prompt_accounting.prefix_cache_health.evaluate_prefix_cache_health()`。
2. 核心算法统一计算 provider token scale、expected prefix coverage、under-read、first missing expected prefix identity。
3. `cache_planner.py` 只负责收集 physical spine 边界和 provider usage，然后委托核心算法；不再保留第二套 coverage/scale 计算。
4. `provider_cache_ledger.py` 只消费 `provider_prefix_cache_health.verdict / under_read_tokens / first_missing_expected_prefix_identity`；ledger 不重新解释 cache health。
5. stability/API/frontend 后续只能投影核心算法结果：prefix coverage first，hit ratio second；不得在展示层重新定义一套健康口径。

完成标准：

```text
命中健康口径:
  provider_under_read_tokens == 0
  provider_cache_read_required_coverage_status == physical_spine_estimated_covered
  expected identity prefix fully covered
```

Phase 4A 实施记录：

```text
2026-06-29:
  先撤回 stability/cache reporting 的模型扩展，避免本轮核心重构膨胀为展示层功能堆叠。
  保留 runtime.context_management.__init__ 对 session_compaction 的 lazy facade 修复，解除 prompt_accounting -> context_management -> prompt_accounting 循环导入。
  Phase 4 后续只允许消费 ProviderPayloadManifest / PhysicalPrefixFrameLedger 已有 identity diagnostics，不再在 reporting 层重新定义第二套 identity model。
2026-06-30:
  新增 backend/runtime/prompt_accounting/prefix_cache_health.py，作为 provider prefix cache health 的唯一判断入口。
  cache_planner.py 的 _provider_cache_read_coverage_diagnostics() 已收缩为核心算法委托。
  cache_planner.py 只补齐边界 identity 投影字段：logical_segment_ref、prefix_segment_ref、semantic_slot、physical_prefix_lane、prefix_identity。
  核心算法内部按 provider message read scope 重新计算 cumulative，避免 tool sidecar transport 污染 provider cache read coverage。
  provider_cache_ledger.py 优先消费 provider_prefix_cache_health verdict/under_read/first_missing identity，不再独立推导缓存健康。
  新增 backend/runtime/prompt_accounting/provider_cache_bus.py，作为 provider cache telemetry 的单一总线 facade。
  model_runtime.py 在 provider usage 返回后通过 publish_provider_cache_usage() 写入 durable provider_cache_ledger.jsonl。
  api/tokens.py 和 health_system/governance.py 只消费 build_provider_cache_log_view() / provider_cache_log_row()，不再各自拼装 provider cache 日志。
  /tokens/session/{session_id} 返回 provider_cache_log，并把 provider_cache_ledger.jsonl 纳入响应缓存签名，前端可直接从 tokenStats.provider_cache_log 读取结构化缓存日志。
  stability_report.py 改为记录 identity/content version/position/transport contract 分类，不再把 cached_tokens > 0 当作缓存成功。
  cache_break_detector.py 对 provider_prefix_cache_health.verdict == provider_under_read 生成 break record，即使总 cached_tokens 大于 0 也不会误判为健康。
  ChatPanel 的 sessionContextMeterPresentation() 只读取 tokenStats.provider_cache_log 的总线结论；上下文压力照常计算，前缀 under-read 时 meter 状态显示为 cache_under_read。
```

### Phase 5: 删除旧解释器和旧字段依赖

目标：不保留双链路。

动作：

- 删除 active path 中对旧 `logical_segment_ref` content hash 语义的依赖。
- 删除 messages-only / prefix_family-only / total-hit-only 的判断分支。
- 删除或改写只保护旧内部结构的测试文件；不新增回归测试文件，除非用户后续明确要求。
- `rg` 搜索旧字段，确认不再驱动 active runtime。

完成标准：

```text
旧链路无法再参与 active provider prefix decision
旧字段只可作为历史 ledger/replay metadata 被读取
```

Phase 5 实施记录：

```text
2026-06-30:
  context_candidates.py 不再用 provider_visible_hash 作为 content_hash fallback；identity 优先来自 origin refs。
  provider_visible_context_ledger.py 的 active item key 优先使用 prefix_identity.logical_segment_ref / origin_ref，provider_visible_hash 只保留为缺失 origin_ref 时的诊断。
  model_runtime.py 的 provider-visible commit candidate 去重键移除 provider_visible_hash，改用 storage_root/scope/item_key/provider/model/lane 稳定身份。
  physical_prefix_frame_ledger.py 删除 confirmation_by_hash fallback；frame promotion 只能通过显式 entry_index 或稳定 item_key 确认 provider-visible entry，hash 仅保留为 provider message 字节校验。
  stability_models.PromptStabilitySection 增加 transport_location、logical_segment_ref、semantic_slot、content_version_hash、provider_serialized_hash、prefix_identity。
  stability diff 分类收束为 identity_changed、content_version_changed、position_changed、transport_contract_changed。
  provider_cache_ledger.py、api/tokens.py、health_system/governance.py、ChatPanel.tsx 均改为消费 provider cache bus / prefix cache health 结果，不再用总 hit ratio 或 cached_tokens > 0 定义健康。
  最后仍需通过 rg 确认旧字段只作为历史 ledger/replay metadata、字节诊断或展示字段存在，不能驱动 active prefix decision。
```

## 11. 验证方案

按用户要求，本轮计划不新增测试文件。实施后的验证以静态审查、编译检查、真实固定端口运行和真实 provider usage 为准。

### 11.1 静态审查

```powershell
rg -n "logical_segment_ref|provider_visible_hash|prefix_family|provider_under_read|physical_cache_spine" backend/runtime
rg -n "provider_under_read|cache_hit_rate|cached_tokens" backend/api frontend/src
```

检查点：

- `logical_segment_ref` 不再由 content hash 生成。
- `ppseg` 不再作为跨 turn identity。
- `prefix_family` 不再单独决定身份。
- current append 不进入 expected read。

### 11.2 编译检查

```powershell
python -m py_compile backend/runtime/context_management/context_segment_registry.py backend/runtime/context_management/context_segment_policy.py backend/runtime/context_management/physical_context_plan.py backend/runtime/context_management/physical_prefix_frame_models.py backend/runtime/context_management/physical_prefix_frame_ledger.py backend/runtime/context_management/provider_visible_context_ledger.py backend/runtime/model_gateway/provider_payload.py backend/runtime/prompt_accounting/stability_report.py backend/runtime/prompt_accounting/cache_planner.py backend/runtime/prompt_accounting/provider_cache_ledger.py backend/runtime/prompt_accounting/provider_cache_bus.py backend/api/tokens.py backend/health_system/governance.py
```

### 11.3 固定端口真实运行

项目固定端口：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
API base: http://127.0.0.1:8003/api
```

涉及运行链路、前后端联调、SSE、监控、页面可用性时，必须按 AGENTS.md 真实启动并实测，不能换随机端口。

### 11.4 真实 provider 验收

对同一 session 连续发起：

```text
initial
tool-followup
next user turn initial
next tool-followup
```

验收：

```text
cache_status == hit
provider_under_read_tokens == 0
provider_cache_read_required_coverage_status == physical_spine_estimated_covered
previous confirmed identity sequence is current prefix
first_missing_expected_prefix_identity == empty
```

如果 provider 有缓存过期或 provider-side eviction，应报告为 provider 外部状态，而不是本地结构通过。

## 12. 禁止修复方式

禁止：

- 为了兼容保留第二套 prefix identity 解释器。
- 用 `volatile/session_stable/cacheable` 字段替代四段式物理 lane。
- 把 content hash 当成逻辑身份。
- 把 request ordinal 放进跨 turn identity。
- 把 `prefix_family` 当段身份。
- current append 本次请求内计入 expected cache read。
- 只提高总 hit ratio，不修 expected prefix under-read。
- 在 prompt 里写开发式声明让 agent 理解内部缓存系统。
- 新增测试文件或降低断言来制造通过。

## 13. 需要用户确认的实施边界

本方案将影响 runtime/context/provider payload/prompt accounting/API/frontend contract，属于结构性重构。确认后应按 Phase 0 到 Phase 5 连续实施，不能只补一个 report 字段，也不能在旧壳上堆新壳。

建议确认口径：

```text
同意按本方案统一 prefix authority。
允许清理 active path 中旧 logical_segment_ref/content hash/ordinal/prefix_family-only 链路。
不保留旧兼容解释器。
不新增测试文件；使用静态审查、编译检查、固定端口真实运行和 provider usage 验收。
```
