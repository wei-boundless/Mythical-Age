# 成熟 Agent 语义时空体系源码审查

日期：2026-06-30  
范围：本地源码 `D:/AI应用/openai-codex`、`D:/AI应用/claude-code-nb-main`。  
目的：用本项目的 `Self / Past / Present / Future / HiddenTransport` 模型观察成熟 agent 的真实上下文结构，反推本项目语义时空体系应该借鉴什么、避免什么。

## 1. 审查结论

Codex 和 Claude Code 并不会把大量内部生命周期词发送给模型。它们都把上下文分成少数稳定语义块、历史消息、当前 turn 状态、下一步行动能力，以及隐藏 provider 传输结构。

对应到本项目的模型：

```text
Self:
  稳定系统指令、项目指令、权限/协作长期规则、工具使用原则

Past:
  历史消息、工具结果、已压缩摘要、可 replay transcript

Present:
  当前用户输入、当前环境/权限 diff、当前 pending action、当前 turn 热状态

Future:
  当前可用工具、下一步行动空间、需要审批/用户输入/恢复的路径

HiddenTransport:
  provider tools schema、tool_choice、cache_control、prompt_cache_key、thinking/reasoning config、request params
```

成熟 agent 的共同特点不是“前缀很多”，而是：

- 模型可见前缀少且语义明确。
- 稳定 prompt 与动态内容有明确边界。
- session 历史和 turn 热状态严格分层。
- provider transport 是隐藏传输层，不伪装成对话连续性摘要。
- prompt cache 以 provider request 的真实结构和 byte-identical prefix 为准，不靠模型可见的 `volatile/stable` 标签。

这支持本项目当前方向：保留四段式物理模型，使用 `ContextContractNode` 做内部语义时空身份，不把内部 cache/lane 字段写成 agent-visible 主标题。

## 2. Codex 源码观察

### 2.1 Session 与 Turn 分层

源码：

```text
D:/AI应用/openai-codex/codex-rs/core/src/state/session.rs
D:/AI应用/openai-codex/codex-rs/core/src/state/turn.rs
```

`SessionState` 管 session 级事实：

- `history: ContextManager`
- `additional_context: AdditionalContextStore`
- `previous_turn_settings`
- `auto_compact_window`
- `granted_permissions`
- `active_connector_selection`

`TurnState` 管当前 turn 热状态：

- `pending_approvals`
- `pending_request_permissions`
- `pending_user_input`
- `pending_elicitations`
- `pending_dynamic_tools`
- `pending_input`
- `mailbox_delivery_phase`
- `granted_permissions`
- `tool_calls`
- `token_usage_at_turn_start`

源码证据：

- `state/session.rs:22-43` 把 history、additional context、previous turn settings、auto compact 和权限放在 session state。
- `state/turn.rs:75-88` 把 pending approvals、permissions、user input、dynamic tools、mailbox phase、tool calls 放在 turn state。

映射：

| 本项目时间域 | Codex 对应结构 |
| --- | --- |
| Self | session configuration、base instructions、AGENTS/user instructions、权限配置 |
| Past | `ContextManager.history` |
| Present | `ActiveTurn` / `TurnState` |
| Future | pending permissions、pending user input、tool calls、mailbox phase |
| HiddenTransport | Responses API request fields |

对本项目的启发：

- `TurnMemory` 应继续作为 turn 热账本，而不是再造 HotJournal。
- confirmed old context 应继续由 physical prefix frame / provider-visible ledger 管，不由 TurnMemory 改写。
- pending approval / pending user input / pending tool round 属于 Present/Future，不应 replay 成历史授权。

### 2.2 历史是 append/normalize，不是每轮重解释

源码：

```text
D:/AI应用/openai-codex/codex-rs/core/src/context_manager/history.rs
```

`ContextManager` 保存 oldest-to-newest 的 `ResponseItem` 列表，并在发送给模型前 normalize：

- `record_items()` 只记录 API message。
- `for_prompt()` normalize history，再返回 prompt items。
- `reference_context_item` 是后续 context diff / full reinjection 的基线。
- rollback / compaction 会 bump `history_version`，必要时清掉 diff baseline。

源码证据：

- `history.rs:32-50` 定义 transcript history、`history_version`、`reference_context_item`。
- `history.rs:98-112` 只记录 API message 并追加。
- `history.rs:115-122` 发送前 normalize。
- `history.rs:236-241` rollback 可能清掉 `reference_context_item`，让未来 turn 走 full reinjection。

映射：

```text
Past = ContextManager history + reference_context baseline
```

对本项目的启发：

- `ContextContractManifest` 应承担类似 `reference_context_item` 的结构化基线职责。
- history replay 不应按当前语义重新拼写旧内容。
- 如果 rollback / edit-resend 破坏了基线，应显式 reset baseline，而不是让 cache accounting 猜。

### 2.3 Codex 的 prompt cache 是稳定 key + 完整 prefix

源码：

```text
D:/AI应用/openai-codex/codex-rs/core/src/client.rs
D:/AI应用/openai-codex/codex-rs/core/tests/suite/prompt_caching.rs
D:/AI应用/openai-codex/codex-rs/core/tests/suite/client.rs
```

Codex 的 Responses request 包含：

```text
model
instructions
input
tools
tool_choice
parallel_tool_calls
reasoning
prompt_cache_key
text
client_metadata
```

源码证据：

- `client.rs:368-372` 默认 `prompt_cache_key` 是 thread id，除非 override。
- `client.rs:734-783` request 由 `instructions`、`input`、`tools`、`tool_choice`、`reasoning`、`prompt_cache_key` 等字段组成。
- `prompt_caching.rs:488-495` 测试要求 `prompt_cache_key` 跨 override 保持不变，且第一请求的 entire prefix 是第二请求 prefix。
- `client.rs` 测试在 `client.rs:441-466` 检查实际顺序：prior history -> permissions -> AGENTS instructions -> environment context -> new user message。

映射：

| 本项目模型 | Codex 做法 |
| --- | --- |
| Self | `instructions` + permissions + AGENTS instructions |
| Past | prior response items in `input` |
| Present | new user message + environment/context diff |
| HiddenTransport | tools / tool_choice / reasoning / prompt_cache_key / metadata |

对本项目的启发：

- 不要用总 hit rate 证明缓存健康，必须证明 previous prefix 是 current prefix。
- `prompt_cache_key` / transport params 属于隐藏传输契约，不应自然语言化进入 agent prompt。
- provider request 的真实结构比模型可见标签更重要。

### 2.4 Codex 有少数可见 marker，但不是海量前缀

源码：

```text
D:/AI应用/openai-codex/codex-rs/core/src/context/*
```

Codex 常见可见 marker：

```text
<permissions instructions>
# AGENTS.md instructions for ...
<INSTRUCTIONS>
<environment_context>
<external_...>
```

源码证据：

- `context/permissions_instructions.rs` 的 `ContextualUserFragment` marker 是 `<permissions instructions>`。
- `context/user_instructions.rs` 使用 `# AGENTS.md instructions for ...` 和 `</INSTRUCTIONS>`。
- `context/environment_context.rs` 投影 `<environment_context>`。
- `context/fragments.rs` 对 additional context 使用 `<external_{key}>` 形态，并限制 token。
- `state/additional_context.rs:15-30` 对 additional context 做 merge，只有变化才注入新 fragment。

结论：

Codex 使用少数稳定 marker 标识语义来源，但没有把 `volatile`、`cacheable_prefix`、`context_append` 等内部生命周期词给模型看。

对本项目的启发：

- 本项目的 8 个 agent-visible 段名已经足够，不应再扩展一堆可见 prefix。
- 内部 kind / slot / lane 应保留在 manifest/diagnostics，不作为 prompt 标题。

## 3. Claude Code 源码观察

### 3.1 稳定 system prompt 与动态内容有硬边界

源码：

```text
D:/AI应用/claude-code-nb-main/constants/prompts.ts
D:/AI应用/claude-code-nb-main/constants/systemPromptSections.ts
```

Claude Code 定义：

```text
SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"
```

注释明确说明：

- boundary 前是 static / cross-org cacheable content。
- boundary 后是 user/session-specific dynamic content。
- marker 不可移动，否则要更新 cache logic。

源码证据：

- `constants/prompts.ts:105-115` 定义动态边界。
- `constants/prompts.ts:560-576` 先返回 static content，再插入 boundary，再追加 dynamic sections。
- `constants/systemPromptSections.ts:13-30` 普通 system prompt section memoized until `/clear` or `/compact`。
- `constants/systemPromptSections.ts:20-30` 每 turn 重算的段必须用 `DANGEROUS_uncachedSystemPromptSection`，并提供 cache-breaking reason。

映射：

| 本项目时间域 | Claude Code 对应 |
| --- | --- |
| Self | boundary 前 static system prompt |
| Present/Future | boundary 后 dynamic registry-managed sections |
| HiddenTransport | cache_control blocks / provider request params |

对本项目的启发：

- 四段式物理模型相当于比 Claude Code 更细的 dynamic boundary；不要再额外暴露 `volatile`。
- 动态段必须有明确理由和权威，不应每轮随意重算稳定内容。
- 如果某段当前必须动态，应该在 contract 中记录原因，而不是让它混进 static prefix。

### 3.2 Claude Code 的 provider transport 是隐藏层

源码：

```text
D:/AI应用/claude-code-nb-main/utils/api.ts
D:/AI应用/claude-code-nb-main/services/api/claude.ts
```

关键结构：

- `toolToAPISchema()` 生成 provider tool schema。
- `splitSysPromptPrefix()` 把 system prompt 切成 cache scope blocks。
- `buildSystemPromptBlocks()` 给 system prompt block 加 `cache_control`。
- `addCacheBreakpoints()` 给 messages 加 message-level cache marker，且每请求只允许一个 message-level marker。

源码证据：

- `utils/api.ts:136-149` tool schema base 缓存，避免 mid-session drift。
- `utils/api.ts:211-230` defer_loading / cache_control 是 per-request overlay，不污染 cached base schema。
- `utils/api.ts:321-355` split system prompt prefix。
- `services/api/claude.ts:3213-3236` build system prompt blocks 并加 cache_control。
- `services/api/claude.ts:3063-3105` message-level cache marker 每请求 exactly one。

映射：

```text
Provider Transport Contract =
  tool schema
  cache_control
  model/request params
  thinking config
  cache anomalypoint
```

对本项目的启发：

- provider native schema 不应进入 `Capability Surface` 正文。
- `Capability Surface` 应只投影能力摘要、边界和 schema_ref。
- `ProviderPayloadManifest` 才是 hidden transport 的权威。

### 3.3 Claude Code 用 hash 做诊断，不用 hash 当语义身份

源码：

```text
D:/AI应用/claude-code-nb-main/services/api/promptCacheBreakDetection.ts
```

`PreviousState` 记录：

```text
systemHash
toolsHash
cacheControlHash
perToolHashes
model
globalCacheStrategy
betas
extraBodyHash
prevCacheReadTokens
```

源码证据：

- `promptCacheBreakDetection.ts:28-69` 定义 previous cache state。
- `promptCacheBreakDetection.ts:267-281` 分别计算 stripped system/tools hash 和 cache_control hash。
- `promptCacheBreakDetection.ts:332-346` 比较 system/tools/model/cache_control/betas/extra body 等变化。

结论：

Claude Code 用 hash 定位 cache anomaly 的来源，但没有用单个 content hash 代替逻辑身份。

对本项目的启发：

- `content_hash`、`provider_serialized_hash`、`transport_contract_hash` 是诊断字段，不应替代 `logical_segment_ref`。
- 本项目已经推进 prefix identity / provider_cache_bus，这是正确方向。

### 3.4 Claude Code 的 hot state 与恢复

源码：

```text
D:/AI应用/claude-code-nb-main/bootstrap/state.ts
D:/AI应用/claude-code-nb-main/utils/sessionState.ts
D:/AI应用/claude-code-nb-main/utils/conversationRecovery.ts
```

重要状态：

- `lastAPIRequest`
- `lastAPIRequestMessages`
- `systemPromptSectionCache`
- `lastMainRequestId`
- `lastApiCompletionTimestamp`
- `pendingPostCompaction`
- `promptCache1hEligible`
- `afkModeHeaderLatched`
- `fastModeHeaderLatched`
- `cacheEditingHeaderLatched`
- `thinkingClearLatched`
- `pending_action`

源码证据：

- `bootstrap/state.ts:113-118` 保存 last API request 和 exact post-compaction messages。
- `bootstrap/state.ts:202-205` 保存 system prompt section cache 和 last emitted date。
- `bootstrap/state.ts:220-242` 多个 cache-sensitive header / eligibility latch，避免 mid-session cache bust。
- `bootstrap/state.ts:253-256` `pendingPostCompaction` 用来标记压缩后的第一次 API call。
- `sessionState.ts:2-24` pending action details 给外部界面展示当前 blocked on 什么。
- `sessionState.ts:92-120` `notifySessionStateChanged()` 把 requires_action 写到 external metadata。
- `conversationRecovery.ts:149-155` resume 时会过滤 unresolved tool uses、orphaned thinking、并追加 synthetic sentinel。
- `conversationRecovery.ts:556-568` resume 时恢复 skill state、deserialize messages、追加 session start hook messages。

映射：

| 本项目时间域 | Claude Code 对应 |
| --- | --- |
| Present | last API request, pending action, current session state |
| Future | requires_action details, permission mode, pending approval path |
| Past | transcript / messages / compaction summary |
| Self | system prompt cache, section cache, latches |

对本项目的启发：

- 本项目也需要保留“最后一次真实 provider request / messages snapshot”用于诊断和分享，不应只保存自定义 segment map。
- `TurnMemory` 应保存 pending action、commit/recovery/frame 状态；UI replay 不能成为 runtime recovery 权威。
- cache-sensitive 参数要 latch 或显式标记变更，不能每轮漂移。

### 3.5 Claude Code fork/subagent 的缓存与隔离

源码：

```text
D:/AI应用/claude-code-nb-main/utils/forkedAgent.ts
D:/AI应用/claude-code-nb-main/query.ts
```

`CacheSafeParams` 包含：

```text
systemPrompt
userContext
systemContext
toolUseContext
forkContextMessages
```

注释明确：Anthropic API cache key 由 system prompt、tools、model、messages prefix、thinking config 组成。

源码证据：

- `forkedAgent.ts:46-68` 定义 cache-safe params。
- `forkedAgent.ts:345-455` 创建 subagent context，默认 clone mutable state，并隔离 UI callbacks / setAppState。
- `forkedAgent.ts:388-403` content replacement state clone 用于保持 wire prefix 一致，避免 cache miss。
- `forkedAgent.ts:520-524` fork 初始消息是 parent context messages + prompt messages，保持相同 post-repair prefix。
- `query.ts:1124-1131` reactive compact 也传 cacheSafeParams。

对本项目的启发：

- 虽然当前先做单 agent，但将来做 subagent 时必须区分“cache-safe shared prefix”和“mutable isolated state”。
- 本项目 `TurnMemory` 不应被子 agent 共享为可写状态；共享只能是 sealed prefix / cache-safe context refs。
- provider transport、tools、thinking config 也属于 cache-safe identity 的一部分。

## 4. 横向对照表

| 维度 | Codex | Claude Code | 本项目建议 |
| --- | --- | --- | --- |
| Self | base instructions、permissions、AGENTS、environment stable parts | boundary 前 static system prompt | `Operating Contract` + stable `Capability Surface` |
| Past | `ContextManager.history` oldest-to-newest | transcript messages、compaction summary、resume chain | `Sealed Conversation Timeline` / provider-visible ledger |
| Present | `TurnState` pending items、current input、context diffs | pending action、last API request、dynamic sections | `Current Task and User Delta` + `Current Runtime Boundary` |
| Future | pending approvals/user input/tools/mailbox | requires_action、tool availability、fork/recovery path | `Feedback and Recovery Cursor` + `Action Horizon` |
| HiddenTransport | Responses request fields: tools, tool_choice, reasoning, prompt_cache_key | tools schema、cache_control、thinking config、request params | `Provider Transport Contract` hidden L8 |
| Cache identity | thread `prompt_cache_key` + byte-identical prefix | system/tools/cache_control/model/messages/thinking | `PrefixIdentity` + provider bytes + transport contract |
| Dynamic boundary | context diff / full reinjection baseline | `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` | 四段式 physical lane |
| Turn hot ledger | `TurnState` | bootstrap/session state + pending action | `TurnMemory` |

## 5. 成熟 Agent 的共同不变量

### 5.1 模型可见段少，工程字段多但隐藏

Codex 和 Claude Code 都有大量内部字段，但模型只看到少数稳定语义段或 provider-native tool schema。内部字段用于：

- routing
- diff
- cache diagnosis
- request assembly
- recovery
- telemetry

它们不会把这些字段变成模型的主要上下文标题。

本项目规则：

```text
ContextContractNode 是内部语义身份。
Agent-visible prompt 只用少数标准段名。
```

### 5.2 Session 历史和 turn 热状态分离

成熟 agent 不让历史层承担当前 turn 的 pending approvals / pending action / dynamic tools。

本项目规则：

```text
PhysicalPrefixFrameLedger = Past 权威
TurnMemory = Present/Future 热账本
```

### 5.3 Provider transport 不等于 agent memory

tools schema、cache_control、prompt_cache_key、thinking config 都是 provider transport。

本项目规则：

```text
Provider Transport Contract 只存在于 ProviderPayloadManifest / request params / diagnostics。
```

### 5.4 Cache 是真实 request prefix，不是 prompt 标签

成熟 agent 关注：

- request key 是否稳定
- system prompt 是否被 boundary 切分
- tools/schema/hash 是否变化
- messages prefix 是否一致
- cache_control/TTL/betas/extra body 是否变化

本项目规则：

```text
expected prefix coverage > total hit rate
provider_under_read_tokens == 0 才能认为 expected prefix 健康
```

### 5.5 动态内容必须有理由

Claude Code 对每 turn 重算的 system section 使用 `DANGEROUS_uncachedSystemPromptSection(reason)`，这不是给模型看的提示，而是给工程层的约束。

本项目规则：

```text
Present/Future 节点必须有 authority、ttl、commit_policy、replay_policy。
没有 agent_use_contract 的 agent-visible 节点不能入 prompt。
```

## 6. 对本项目当前设计的校正

### 6.1 8 个 agent-visible 段已经够用

当前文档定义的 8 个段：

```text
Operating Contract
Capability Surface
Sealed Conversation Timeline
Selected Memory Hints
Current Task and User Delta
Current Runtime Boundary
Feedback and Recovery Cursor
Action Horizon
```

对照 Codex / Claude Code 后，结论是：这些段已经比成熟 agent 的可见 marker 更细，不应继续增加更多可见前缀。

### 6.2 不应声明 volatile

Claude Code 内部有 uncached section，但它是工程 API，不是模型可见段名。Codex 也不会让模型读 `volatile`。

本项目应保持：

```text
volatile / current_turn / never_replay 是 ContextContractNode 与 PhysicalContextPlan 字段。
不是 agent-visible prompt 文案。
```

### 6.3 ContextContractNode 应替代启发式分类

当前本项目 `backend/harness/runtime/context_contract/authority_rules.py` 仍主要通过 kind 字符串猜 `semantic_layer` / `semantic_time`。

成熟 agent 的做法更接近：

- Codex 用具体 `ContextualUserFragment` 类型和 `TurnContextItem` 基线。
- Claude Code 用 system prompt section、cache boundary、request builder、state latch。

因此本项目后续应把语义分类显式化：

```text
context_segment_registry declaration
-> context_segment_policy
-> ContextContractNode explicit fields
```

缺字段时应诊断，而不是默默猜。

### 6.4 需要保存 exact provider request projection

Claude Code 保存 `lastAPIRequestMessages`，用于 `/share` 和真实 API 形态回放。Codex 测试也直接检查请求 body。

本项目后续应确保：

```text
ProviderPayloadManifest + provider_cache_bus
必须能还原：
  messages exact order
  segment bindings
  provider serialized hash
  tools sidecar hash
  transport contract hash
```

不要只保留抽象 segment map。

### 6.5 TurnMemory 方向是成熟的，但必须守边界

Codex 的 `TurnState` 和 Claude Code 的 pending action/session state 证明 turn 热账本是成熟 agent 的必要结构。

本项目的 `TurnMemory` 可以更 durable，但必须满足：

- 只管 current / handoff / recovery。
- 不改 confirmed history。
- 不从 UI replay 或 raw visible prefix 猜事实。
- 不成为第二套 prompt 拼接权威。

## 7. 推荐落地顺序

本文是审查文档，不直接改代码。若继续实施，建议顺序：

1. 将 `ContextContractNode` 的 `semantic_time` / `semantic_layer` 从启发式改为 registry / policy 显式字段。
2. 将 8 个 agent-visible 段做成 prompt projection 模板。
3. 保证 `ProviderPayloadManifest` 输出 exact request projection，类似 Claude Code 的 `lastAPIRequestMessages`。
4. 把 provider transport 全部收进 hidden L8，不让 tool schema / cache_control 泄漏成 agent memory。
5. 对 `TurnMemory` 做边界审查：只承载 Present/Future 热状态，不替代 Past ledger。
6. cache 诊断继续以 provider_cache_bus / expected prefix coverage 为主，不用总 hit rate 做健康判断。

## 8. 最终裁决

成熟 agent 的语义时空体系不是一套显式哲学术语，而是通过工程边界自然形成：

```text
stable system prompt / instructions
-> history transcript
-> current turn state
-> action and permission boundary
-> hidden provider transport
```

本项目把它形式化为：

```text
Self / Past / Present / Future / HiddenTransport
```

是合理的，但必须保持它是内部语义契约模型，不要把每个内部维度都变成模型可见前缀。

最终建议：

```text
四段式物理模型继续作为缓存和 replay 权威。
ContextContractNode 作为内部语义时空身份。
8 个 agent-visible 段作为 prompt 投影上限。
Provider Transport Contract 作为隐藏 L8。
TurnMemory 作为 turn 热账本。
Provider-visible ledger / physical prefix frame 作为 Past 权威。
```

这与 Codex 和 Claude Code 的成熟源码结构一致。

