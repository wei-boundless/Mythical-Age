# DeepSeek 适配外部源码对照报告 - 2026-06-27

## 文档目的

本文记录对项目目录外三个本地成熟 agent / 路由工程的 DeepSeek 适配源码审查结果：

- `D:/AI应用/hermes/hermes-agent-main`
- `D:/AI应用/pi-main`
- `D:/AI应用/cc-switch-main`

本文不讨论泛泛的供应商切换，也不把问题简化为改 `base_url`。重点是为本项目的上下文拼接体系、DeepSeek 缓存命中、工具观察 replay、fork 继承和 provider-visible 物理请求链提供工程对照。

需要解决的本地问题已经在 `backend/runtime/context_management/context_cache_live_probe_diagnosis_20260627.md` 中记录：真实 normal turn 在第三轮后缓存命中稳定卡在约 80%-82%，而无动态尾的高 token 合成探针可以达到约 98%。这说明 DeepSeek 本身可以缓存大前缀，剩余问题主要在本项目的物理拼接、动态尾、replay 边界和 provider wire shape。

## 总结结论

Hermes、Pi Agent、CC Switch 的共同做法是：把 DeepSeek 适配当成 provider 契约，而不是 prompt 文案。

成熟链路通常是：

```text
provider/model metadata
-> provider request adapter
-> deterministic transcript replay
-> provider-specific reasoning replay
-> provider-specific cache usage accounting
```

DeepSeek 适配至少有五条硬要求：

1. 请求字段必须符合 DeepSeek 的 OpenAI Chat Completions-compatible 形态。thinking 模式使用 `thinking: {"type": "enabled" | "disabled"}`，启用推理档位时再发送 `reasoning_effort`。
2. DeepSeek V4 thinking/tool-call 历史必须在 assistant replay 中带回 `reasoning_content`。缺失或空 reasoning 需要按 provider 契约处理，不能简单省略。
3. 工具调用历史必须保持确定性的时序相邻关系：assistant tool call message -> tool result message -> 后续 user/assistant message。
4. 缓存命中统计需要同时读取 OpenAI 标准字段 `prompt_tokens_details.cached_tokens` 和兼容供应商字段，例如 `prompt_cache_hit_tokens`。
5. 每轮变化的动态元数据不能进入稳定前缀。CC Switch 专门删除了 Claude Code 开头的动态 billing header，因为其中的 `cch=` 每轮变化，会破坏 prefix cache。

对本项目来说，第一优先级不是先瘦身，而是保证“应该命中的内容”在下一轮请求中以相同字节、相同顺序、相同 provider wire shape 出现在真实物理前缀中。

## 源码证据索引

| 系统 | 源码位置 | 关键证据 |
| --- | --- | --- |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/hermes_cli/auth.py:349` | DeepSeek direct provider 使用 `https://api.deepseek.com/v1`、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`。 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/hermes_cli/model_normalize.py:119` | DeepSeek 模型归一化保留 `deepseek-chat`、`deepseek-reasoner`、`deepseek-v4-pro`、`deepseek-v4-flash` 和未来 `deepseek-vN-*`。 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/agent/chat_completion_helpers.py:545` | assistant message 构造时保留 provider 返回的 `reasoning_content`；DeepSeek/Kimi thinking tool-call 缺失时补单空格。 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/agent/agent_runtime_helpers.py:1800` | API replay 时复制 provider-facing reasoning 字段，并把旧历史中的空字符串 `reasoning_content` 升级成单空格。 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/agent/anthropic_adapter.py:444` | DeepSeek `/anthropic` endpoint 被单独识别；因为 DeepSeek 要求 thinking replay，所以保留 unsigned thinking blocks。 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/agent/conversation_loop.py:490` | plugin context 注入当前 user message，不注入 system prompt，目的是保持 prompt cache prefix。 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/agent/system_prompt.py:72` | system prompt 缓存在 agent 生命周期内，不在 session 中途重渲染，以保持上游 prefix cache。 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/agent/prompt_caching.py:1` | Anthropic-style cache control 使用固定布局：system prompt + 最近三条 non-system messages。 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/agent/codex_responses_adapter.py:143` | deterministic tool call id 用于避免随机 UUID 破坏 OpenAI prompt cache。 |
| Hermes | `D:/AI应用/hermes/hermes-agent-main/model_tools.py:300` | tool definitions 缓存返回 shallow copy，避免下游 mutation 导致重复工具名，DeepSeek 等 strict provider 会拒绝重复。 |
| Pi Agent | `D:/AI应用/pi-main/packages/ai/src/models.generated.ts:3486` | DeepSeek V4 模型元数据声明 `requiresReasoningContentOnAssistantMessages` 和 `thinkingFormat: "deepseek"`。 |
| Pi Agent | `D:/AI应用/pi-main/packages/ai/src/providers/openai-completions.ts:503` | OpenAI Completions request builder 统一负责 messages、tools、cache controls、thinking 字段和 replay 字段。 |
| Pi Agent | `D:/AI应用/pi-main/packages/ai/src/providers/openai-completions.ts:572` | DeepSeek thinking mode 发送 `thinking: { type }`，并通过 model metadata 映射 `reasoning_effort`。 |
| Pi Agent | `D:/AI应用/pi-main/packages/ai/src/providers/openai-completions.ts:893` | 当模型要求时，replayed assistant messages 会强制携带 `reasoning_content`。 |
| Pi Agent | `D:/AI应用/pi-main/packages/ai/src/providers/openai-completions.ts:1003` | usage 解析读取 `prompt_tokens_details.cached_tokens`，并 fallback 到 `prompt_cache_hit_tokens`。 |
| Pi Agent | `D:/AI应用/pi-main/packages/ai/src/providers/openai-completions.ts:467` | 兼容 provider 可以接收由 session id 派生的 session-affinity headers。 |
| Pi Agent | `D:/AI应用/pi-main/packages/ai/src/providers/openai-prompt-cache.ts:1` | `prompt_cache_key` 被截断到 OpenAI 64 字符限制。 |
| Pi Agent | `D:/AI应用/pi-main/packages/coding-agent/src/core/session-manager.ts:315` | 通过 current leaf 回溯到 root 构造 session context，天然支持 branch/fork 上下文重建。 |
| CC Switch | `D:/AI应用/cc-switch-main/docs/guides/codex-deepseek-routing-guide-zh.md:5` | Codex 使用 Responses，而 DeepSeek 使用 Chat Completions；本地路由负责双向协议转换。 |
| CC Switch | `D:/AI应用/cc-switch-main/src/config/codexProviderPresets.ts:247` | Codex DeepSeek preset 声明 `apiFormat: "openai_chat"` 和 DeepSeek reasoning metadata。 |
| CC Switch | `D:/AI应用/cc-switch-main/src-tauri/src/proxy/providers/transform_codex_chat.rs:250` | Responses request 被转换为 Chat Completions request。 |
| CC Switch | `D:/AI应用/cc-switch-main/src-tauri/src/proxy/providers/transform_codex_chat.rs:358` | provider 声明的 reasoning config 控制 `thinking`、`enable_thinking`、`reasoning_effort`、nested reasoning object。 |
| CC Switch | `D:/AI应用/cc-switch-main/src-tauri/src/proxy/providers/transform_codex_chat.rs:850` | thinking 工具历史无法恢复时，tool-call assistant message 会补 `reasoning_content` placeholder。 |
| CC Switch | `D:/AI应用/cc-switch-main/src-tauri/src/proxy/providers/transform_codex_chat.rs:1533` | Chat usage 转回 Responses usage 时保留 cached token 字段。 |
| CC Switch | `D:/AI应用/cc-switch-main/src-tauri/src/proxy/providers/transform.rs:11` | 删除开头动态 Claude Code billing metadata，因为它会破坏 prefix cache reuse。 |
| CC Switch | `D:/AI应用/cc-switch-main/src-tauri/src/proxy/cache_injector.rs:8` | cache breakpoint 注入到 tools、system、最后一个 non-thinking assistant block；thinking blocks 被跳过。 |

## Hermes 源码结论

### 1. Provider 和模型身份归一化

Hermes 有直接 DeepSeek provider 配置，并且有 provider-aware 的模型名归一化。DeepSeek 不是简单把所有名称都折叠成 `deepseek-chat`，而是保留 V4 和未来 V-series 模型 id。

对本项目的约束：模型归一化必须属于 provider boundary。不要把 DeepSeek 模型名规则写进 agent prompt，也不要散落在上下文拼接层。

### 2. `reasoning_content` 写入和 replay

Hermes 在两个阶段处理 `reasoning_content`：

1. assistant message 写入阶段：保留 provider/SDK 暴露的 `reasoning_content`，如果捕获到 streamed reasoning，也会保存。
2. API replay 阶段：把 provider-facing reasoning 字段复制回请求；如果旧历史中是空字符串，而当前 DeepSeek thinking mode 要求非空，就升级成单空格。

这里最重要的规则是：

```text
DeepSeek thinking mode 的 assistant 历史必须带 provider-facing reasoning_content
```

Hermes 使用单空格作为 strict-safe placeholder，因为 DeepSeek V4 Pro 会拒绝空字符串。

### 3. 防止跨 provider reasoning 泄漏

Hermes 明确处理了 cross-provider poisoned history：如果历史里的 `reasoning` 来自其他 provider，而当前要 replay 到 DeepSeek/Kimi，它不会把别的 provider 的 chain-of-thought 泄漏给 DeepSeek，而是补单空格满足 API 结构要求。

对本项目的约束：`reasoning_content` 是 provider-facing replay state，不是普通语义记忆。跨 provider 切换时必须有隔离策略。

### 4. DeepSeek `/anthropic` 特殊路径

Hermes 对 DeepSeek `/anthropic` endpoint 单独识别。该 endpoint 说 Anthropic Messages 协议，但 thinking mode 需要 replay unsigned thinking blocks；同时它不能验证 Anthropic 签名，所以 signed/redacted 逻辑不能照搬 Claude。

对本项目的约束：reasoning replay 不是一个万能字段。不同 wire protocol 的 replay 形态不同：

- DeepSeek Chat Completions：`message.reasoning_content`
- DeepSeek Anthropic-compatible：unsigned `thinking` blocks
- 通用 OpenAI-compatible：不要发送 DeepSeek-only 字段，除非 profile 明确声明兼容

### 5. 缓存前缀策略

Hermes 把 system prompt 缓存在 agent 生命周期内，不在 session 中途重渲染。plugin/context hook 注入当前 user message，而不是 system prompt。源码注释明确说明：system prompt 变化会破坏 prompt cache prefix。

Hermes 还使用 deterministic tool call id，避免随机 UUID 进入 provider-visible 前缀。

对本项目的约束：缓存命中看的是物理字节/token 前缀，不是语义标签。任何每轮变化的内容，只要出现在已封存内容之前，就会破坏 provider automatic prefix cache。

### 6. 工具 schema 和工具结果稳定性

Hermes 缓存 tool definitions，但返回 shallow copy，避免下游 mutation 污染缓存并累积重复工具名。它还对 open-weight 模型常见参数错误做工具执行前修复，例如 schema 期望 array 但模型给 scalar。

对本项目的约束：tool catalog 一旦进入 cacheable prefix，就必须 canonical、稳定、不可被下游动态修改。参数修复、action permit 和 observation acceptance 可以在模型提交动作后发生，但 provider-visible schema 字节不能每轮漂移。

## Pi Agent 源码结论

### 1. DeepSeek 行为由模型元数据驱动

Pi Agent 的 generated model metadata 对 DeepSeek V4 模型声明：

```text
compat.requiresReasoningContentOnAssistantMessages = true
compat.thinkingFormat = "deepseek"
reasoning = true
thinkingLevelMap.high = "high"
thinkingLevelMap.xhigh = "max"
```

这是本项目应该采用的方向：DeepSeek 适配等于 provider metadata + provider adapter logic，而不是 prompt 拼接里的条件分支。

### 2. 请求构造集中在 provider adapter

Pi Agent 的 OpenAI Completions provider 在一个 request builder 中完成：

- convert messages
- convert tools
- 根据 `compat.cacheControlFormat` 决定是否应用 cache controls
- DeepSeek thinking mode 发送 `thinking: { type }`
- `reasoning_effort` 通过 `thinkingLevelMap` 映射
- replayed assistant messages 按需携带 `reasoning_content`

Pi 当前 inspected code 中对 `reasoning_content` placeholder 使用空字符串。Hermes 和 CC Switch 对严格 DeepSeek V4 更稳，使用非空 placeholder。对本项目来说，应该采用 Hermes/CC Switch 规则：当 active DeepSeek model 要求 reasoning replay 时，不发送空字符串。

### 3. cache key、cache retention 和 affinity

Pi Agent 有三种缓存亲和面：

1. 直接 OpenAI-compatible 字段：`prompt_cache_key` 和可选 `prompt_cache_retention`
2. provider compatibility flag：是否支持 long retention
3. provider opt-in 的 session-affinity headers

`prompt_cache_key` 会被截断到 64 字符，避免违反 OpenAI 限制。

对本项目的约束：provider cache scope 必须显式存在。fork 时，如果继承的 sealed prefix 完全相同，不应该盲目换成完全无关的新随机 cache key。更合理的是用稳定前缀 lineage 派生 cache key，child session id 只用于存储、UI 和审计。

### 4. usage accounting

Pi Agent 的 usage 解析同时读取：

```text
prompt_tokens_details.cached_tokens
prompt_cache_hit_tokens
```

这比只读 `prompt_tokens_details.cached_tokens` 更适合 DeepSeek-compatible server，因为某些上游会通过 `prompt_cache_hit_tokens` 返回缓存命中。

对本项目的约束：provider usage normalizer 应该接受两个字段，并在 manifest/ledger 中记录本轮使用了哪个来源字段。

### 5. fork / branch context model

Pi Agent 的 session manager 从 current leaf 回溯到 root 构建 LLM context。session replacement 可以把当前 branch path 写成新 session，同时保留 path entries。

这个模型满足 fork 的关键属性：

```text
旧 branch entries 不变
新 branch 只追加新 entries
LLM context 由当前 leaf path 构造
```

对本项目的约束：fork 必须是 confirmed provider-visible entries 上的分支。为了缓存继承，不允许对父分支 provider-visible prefix 重新摘要、重排或重新渲染。

## CC Switch 源码结论

### 1. Codex 到 DeepSeek 需要协议路由

CC Switch 文档明确指出：

```text
Codex CLI -> OpenAI Responses
DeepSeek -> OpenAI Chat Completions
```

它的做法是让 Codex 继续面向 Responses，本地 route 在内部识别真实上游是 Chat Completions，再把 request 转成 Chat Completions，最后把 Chat response 转回 Responses。

对本项目的约束：如果我们有统一内部 model gateway，DeepSeek adapter 仍然需要明确的 wire-shape transform layer。上下文 compiler 不应该知道 DeepSeek 的具体字段名。

### 2. DeepSeek reasoning config 是声明式 metadata

CC Switch 的 Codex DeepSeek preset 声明：

```text
apiFormat = openai_chat
supportsThinking = true
supportsEffort = true
thinkingParam = thinking
effortParam = reasoning_effort
effortValueMode = deepseek
outputFormat = reasoning_content
```

transform layer 根据这些声明做映射：

- `reasoning.effort = xhigh | max` -> `reasoning_effort = max`
- 其他 enabled effort clamp 到 DeepSeek 可接受值
- 显式关闭 reasoning 时发送 `thinking: {"type": "disabled"}`，但不发送非法的 `reasoning_effort: "none"`

对本项目的约束：DeepSeek provider profile 应直接包含这些字段。不要在无关模块中通过 model name substring 临时推断。

### 3. Responses-to-Chat 的 reasoning replay

CC Switch 会把 Responses reasoning item 重新贴回前一个 assistant message 或 tool-call message 的 `reasoning_content`。如果 bare tool call 没有可恢复 reasoning，它会注入 `"tool call"`。

这解决的是和 Hermes 相同的问题：

```text
assistant tool_calls message 缺 reasoning_content
-> DeepSeek/Kimi/Moonshot thinking mode replay 失败
```

对本项目的约束：sealed transcript 必须把 provider-facing reasoning replay fields 存在需要它的 assistant message 附近。不要只把 reasoning 放在每轮重新生成的 dynamic projection 中。

### 4. 动态前缀污染

CC Switch 专门删除开头的 `x-anthropic-billing-header`，原因是里面的 `cch=` 会每轮变化，导致 OpenAI Chat messages 或 Responses `instructions` 的 prompt prefix 每轮都不同。

这是对我们当前缓存问题最直接的外部证据：看似无害的动态 metadata，只要出现在稳定内容之前，就会破坏 automatic prefix cache。

### 5. usage 和 cache 可见性

CC Switch 在 Chat Completions streaming 请求中注入 `stream_options.include_usage`，否则流式响应末尾不会返回 usage chunk，缓存命中率、token、成本都会漏记。随后它把 `prompt_tokens_details.cached_tokens` 映射回 Responses 的 `input_tokens_details.cached_tokens`。

对本项目的约束：provider-visible cache probe 必须同时验证物理 prompt 和 usage transport。低缓存数字可能是真 miss，也可能是 usage 字段没被正确打开或解析。

## 跨系统设计不变量

### 不变量 1：Provider 适配必须在边界层

DeepSeek-specific 字段属于 provider adapter/profile：

```text
ProviderProfile
  api_wire_shape
  model_id_normalization
  thinking_format
  effort_mapping
  reasoning_replay_policy
  cache_usage_fields
  cache_affinity_policy
```

这些内容不应该写在 context segment 名称、agent prompt 或 tool observation summary 里。

### 不变量 2：cacheable prefix 必须物理稳定

provider 缓存的是 byte/token prefix，不知道我们的语义标签。

正确形态：

```text
stable provider prefix
-> sealed transcript replay
-> current user delta
-> current tool delta
-> current dynamic tail
```

错误形态：

```text
turn 1:
stable provider prefix
-> user 1
-> dynamic tail 1

turn 2:
stable provider prefix
-> user 1
-> user 2
-> dynamic tail 2
```

第二种形态意味着 turn 1 的完整请求不是 turn 2 的物理前缀。它正好解释了本项目真实请求为什么只能命中一截，而达不到 no-tail 探针的 98%。

### 不变量 3：旧上下文字节不可变

provider-visible entry 一旦确认并封存，fork/replay 必须逐字节保持。

允许：

- fork point 后追加 child turn
- 添加 child-only current-turn tail
- 显式 compaction 后把新 summary 作为新的 sealed entry

不允许：

- 重写旧 tool observations
- 用新 prefix 重新渲染旧 context blocks
- 把旧 dynamic tail 换位置
- 在 replay 前把旧 reasoning fields 合并进新的语义 summary

### 不变量 4：工具观察要区分稳定量和增量

成熟系统不会无限重复塞旧工具输出。它们区分：

```text
sealed tool observation replay
current tool observation delta
tool result handle / digest
fresh read result
```

对于重复读文件：

- 旧 read result 如果已经发给 provider，就作为 sealed transcript 保留。
- 模型再次要求读取时，工具仍应读取当前文件状态。
- 如果同一 file/range/content hash 未变，read evidence reuse 可以返回 compact handle 或 digest，并说明相对 observation X 未变化，而不是重复全量内容。
- 如果内容变化，新 read result 是新的 current-turn delta，provider 成功后再封存。

这是 read evidence reuse / observation acceptance 执行契约，不是 prompt 文案优化。

### 不变量 5：reasoning replay 是 provider-facing state

DeepSeek `reasoning_content` 不是普通语义记忆，而是 multi-turn thinking/tool-call replay 所需的 provider-facing state。

它应该存放在 assistant message 附近：

```text
assistant message
  content
  tool_calls
  provider_replay.reasoning_content
```

不应该每轮从 dynamic projection 临时重建。

## 本项目目标架构

### 1. DeepSeek Provider Profile

需要标准化 DeepSeek provider profile：

```text
provider_id = deepseek
wire_api = openai_chat_completions
base_url_default = https://api.deepseek.com
model_id_policy = canonical_or_v_series
supports_thinking = true
thinking_param = thinking
thinking_enabled_value = {"type": "enabled"}
thinking_disabled_value = {"type": "disabled"}
supports_effort = true
effort_param = reasoning_effort
effort_map:
  xhigh -> max
  max -> max
  high -> high
  medium -> high
  low -> high
  minimal -> high
reasoning_replay:
  assistant_requires_reasoning_content_when_thinking = true
  empty_placeholder = " "
  tool_call_placeholder = "tool call"
usage_cache_fields:
  - prompt_tokens_details.cached_tokens
  - prompt_cache_hit_tokens
```

具体 low/medium 是否能映射成更细档位，需要以 DeepSeek 当前 API 接受值为准。若上游只接受 `high` 和 `max`，则低档位应该 clamp 到 `high`，不能发送非法枚举。

### 2. Provider-visible 物理上下文链

目标请求链应明确分成：

```text
global_static_prefix
provider_visible_context_prefix
current_turn_user_delta
current_turn_tool_delta
current_turn_dynamic_tail
never_replay_tail
```

分段规则：

| 物理段 | 内容 | 缓存预期 | 封存行为 |
| --- | --- | --- | --- |
| `global_static_prefix` | 稳定 system identity、稳定 tool catalog、稳定 provider 指令 | 应命中 | 按 profile/session version 生成一次 |
| `provider_visible_context_prefix` | 已确认进入 prefix 的旧 user/memory/tool/evidence/runtime replay-only 字节 | 应命中 | 只接收 confirmed entries，按 ledger entry index 线性插线 |
| `current_turn_user_delta` | 当前用户请求和当前显式上下文 | 不承诺同轮命中 | provider 成功后可封存 |
| `current_turn_tool_delta` | 当前执行循环中新产生的工具观察 | 不承诺同轮命中 | provider 成功后可封存 |
| `current_turn_dynamic_tail` | 新鲜 projection、volatile runtime status、current boundary hints | 不承诺同轮命中 | 只有筛选后的事实可转成未来 sealed entry |
| `never_replay_tail` | one-shot runtime controls | 不承诺命中 | 永不封存 |

关键修正：上一轮成功确认的动态内容，下一轮不能仍停留在会变化的 dynamic tail 里。它要么作为 confirmed provider-visible entry 进入 `provider_visible_context_prefix`，要么被丢弃，不能以新位置重渲染。active、historical-only、tool transcript、runtime replay-only 只是语义 metadata，不允许拆成不同物理 lane。

### 3. Fork-safe context

fork 应表达为 confirmed provider-visible commits 上的 branch：

```text
root session
-> commit A
-> commit B
-> fork point C
   -> child branch D
   -> parent branch E
```

child 首轮请求应该复用到 commit C 为止的完全相同 provider-visible 字节，然后追加 child D。不能通过重新摘要父上下文、重新渲染父上下文或替换 prefix 来构造。

provider cache affinity 建议：

```text
cache_scope_id = provider_id + root_session_id + fork_point_commit_hash
```

当 provider 支持 `prompt_cache_key` 或 session-affinity header 时，这个 lineage key 比完全随机 child session id 更利于 fork 后缓存继承。child session id 仍然保留，用于存储、UI 和审计。

### 4. 工具 Observation Acceptance 与 Read Evidence Reuse

工具结果进入上下文前需要 observation acceptance 决策：

```text
tool_call
-> tool_result_observation
-> observation_fingerprint
-> observation_acceptance_decision
   -> full_delta
   -> digest_delta
   -> unchanged_reference
   -> excluded_from_context
```

读文件策略：

- 首次读取相关 file/range：发送 full content 或 bounded content。
- 重复读取且 content hash 未变：发送 compact unchanged reference + handle。
- 重复读取且 content hash 改变：按大小发送 changed range 或 bounded full result。
- 已封存的旧 tool observation 永远不重写。

这样可以避免重复上下文膨胀，同时不破坏 transcript 时序和旧上下文字节。

## 应该借鉴什么

从 Hermes 借鉴：

- system prompt 在 session 内稳定，不中途重渲染。
- 动态 plugin/context 注入当前 user turn，不污染 system prefix。
- DeepSeek strict replay 使用非空 placeholder。
- 防止跨 provider reasoning 泄漏。
- replay-sensitive tool call 使用 deterministic id。
- tool schema canonical 且避免 mutation drift。

从 Pi Agent 借鉴：

- provider/model metadata 控制 DeepSeek compatibility。
- `thinkingFormat: "deepseek"` 类型的 adapter switch。
- `thinkingLevelMap` / effort mapping。
- usage fallback 到 `prompt_cache_hit_tokens`。
- tree/leaf context reconstruction 支持 fork。
- cache key 长度限制和显式 cache retention / affinity surface。

从 CC Switch 借鉴：

- 协议转换属于 adapter layer，不属于 context layer。
- DeepSeek `codexChatReasoning` 等价配置应声明式存在。
- Responses reasoning items 必须回贴到 assistant/tool-call messages。
- 删除或隔离动态前缀污染。
- Chat Completions streaming 必须 include usage。
- wire protocol 转换时保留 cached token 字段。

## 不应该直接照搬什么

不要直接照搬 Pi Agent 中空字符串 `reasoning_content` placeholder。对本项目 DeepSeek V4 路径，更安全的是 Hermes/CC Switch 的非空 placeholder 规则。

不要给 DeepSeek 默认套 Anthropic-style `cache_control`，除非选中的 DeepSeek-compatible endpoint 明确支持。DeepSeek automatic prefix caching 的核心是稳定物理前缀和正确 usage accounting，而不是 Anthropic cache marker。

不要先用瘦身掩盖低命中。no-tail 探针已经证明大 prompt 也能达到 98%。当前首要问题是 prefix continuity。

## 本地执行计划

### Phase 1 - Profile 和 Usage Normalization

目标：DeepSeek-specific 行为集中到 provider profile。

影响范围：

- model gateway provider profile / payload builder
- usage normalizer
- provider cache policy

完成标准：

- DeepSeek request builder 只通过 provider profile 发送 `thinking` 和 `reasoning_effort`。
- cache usage 同时读取 `prompt_tokens_details.cached_tokens` 和 `prompt_cache_hit_tokens`。
- request manifest 记录本轮使用的 usage 字段来源。

### Phase 2 - 物理前缀修复

目标：旧 provider-visible 字节作为下一轮真实请求前缀 replay。

影响范围：

- `context_segment_policy.py`
- `physical_context_plan.py`
- `context_pipeline.py`
- provider-visible ledger commit/replay path

完成标准：

- 上一轮成功 turn 的 dynamic tail 要么封存进 byte replay archive，要么丢弃。
- dynamic tail 不允许插入到 sealed replay bytes 之前。
- provider-visible manifest 能输出：

```text
cacheable_prefix_bytes
current_turn_delta_bytes
never_replay_bytes
```

### Phase 3 - Tool Observation Acceptance

目标：重复工具读取不再重复塞旧全量输出，同时旧观察保持不可变。

影响范围：

- tool transcript / observation model
- read-file tool result handling
- context observation acceptance policy

完成标准：

- 同一 file/range/content hash 可以返回 compact unchanged reference。
- 内容变化时产生新的 delta。
- sealed old tool observations 永远不被重写。

### Phase 4 - Fork Lineage Cache

目标：fork 在物理上继承 provider-visible prefix。

影响范围：

- session/fork boundary
- provider-visible ledger materialization
- cache scope id generation

完成标准：

- child 首轮逐字节 replay parent fork-point provider-visible prefix。
- child 有独立 session id，但可使用 root session + fork-point commit hash 派生 lineage cache key。
- fork probe 输出 common physical prefix bytes 和 cached token 结果。

### Phase 5 - 真实 CLI/API 探针

目标：证明 should-hit prefix 真实命中。

必须覆盖：

- API normal turns：`POST /api/chat/runs`
- CLI turns：`backend/cli/main.py send`
- same-session follow-up after tool observation
- fork child first turn

预期结果：

- normal same-session follow-up 在 warm-up 后，当新增内容很小时应接近 95%+ cached tokens。
- fork child 应继承 parent cacheable prefix，而不是掉到约 80%。
- usage 字段必须非零，且能追踪到 provider response 的来源字段。

## 清理规则

实现时必须删除或重写仍能决定物理位置的旧链路。

必须清理：

- `PhysicalContextPlan` 已经决定物理 lane 后，仍从旧 semantic section fallback 推断 lane 的逻辑。
- 重复 dynamic tail 中的 sealed tool observations。
- prompt assembly 内部的 DeepSeek 字段补丁。
- 出现在 cacheable prefix 前的随机、时间变化或每轮变化 model-visible metadata。
- 保护旧内部形状而不是 provider-visible 行为的旧测试/探针。

必须保留：

- 旧 sealed context bytes。
- confirmed provider-visible commit records。
- 用户 transcript chronology。
- fork ancestry。

## 最终建议

正确升级路径是：先标准化 provider adaptation layer，再修复物理上下文链。

DeepSeek 缓存命中可靠性的核心公式是：

```text
same sealed bytes
same order
same provider wire shape
same cache scope
only new turn content appended after sealed prefix
```

满足这些条件后，prompt 瘦身才是优化。满足之前，瘦身只会遮住问题，无法让 agent 支持稳定 fork，也无法让上下文缓存达到常态 95%+ 的目标。
