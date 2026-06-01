# DeepSeek Prompt Cache 稳定性诊断设计书

日期：2026-06-01

## 1. 背景与问题

当前项目已经将本地 `prompt_cache` 从执行缓存调整为诊断 shim，真实命中以 DeepSeek 服务端自动上下文缓存为准。这个方向正确，但现有诊断仍偏粗粒度：可以看到 hit/miss 和 stable prefix hash，却不能稳定回答“第一处破坏缓存的结构段在哪里”“是否是 prompt 内容变化还是请求参数变化”“压缩上下文是否污染 recent history”。

正确目标不是恢复本地 prompt 内容缓存，而是让每次模型请求的 prompt 结构具备可审计、可 diff、可定位的稳定性报告。

## 2. 外部参考结论

DeepSeek 当前官方 API 主模型入口是 `deepseek-v4-pro` / `deepseek-v4-flash`；二者支持 1M 上下文和最大 384K 输出。`deepseek-chat` / `deepseek-reasoner` 仅为兼容别名并将废弃，不应作为项目默认或 preset。Thinking 模式的 `reasoning_effort` 支持 `high` / `max`；系统默认保持 `high`，前端提供 `Max` 作为显式强推理档。

Codex 的成熟做法是把请求缓存身份与上下文窗口代际分开：`prompt_cache_key` 默认绑定 thread，会被普通请求和 compact 请求复用；`window_generation/current_window_id` 用于标识当前上下文窗口。压缩是替换 history 的运行时事件，不是把摘要伪装成普通 assistant 历史消息。

Claude Code 的成熟做法是把系统 prompt section 默认 memoize，只有显式标记的动态 section 才允许每轮重算；同时对会影响 prompt cache 的 TTL、beta header、mode header 做 session latch，避免中途开关破坏服务端缓存。它的上下文处理顺序也清楚：compact boundary 后，先做 tool result budget replacement，再 microcompact，再 collapse/autocompact。

本项目使用 DeepSeek，不应照搬 Anthropic `cache_control`。应借鉴的是：

- 稳定 section 的纪律。
- 请求缓存身份与窗口代际分离。
- 每轮稳定前缀和动态参数可 diff。
- 压缩摘要不伪装成普通历史消息。

## 3. 目标架构

新增 `PromptStabilityReport`，作为 `runtime.prompt_accounting` 的旁路事实记录。它只观察，不参与 prompt 拼装、不改变模型请求、不决定缓存命中。

目标链路：

```text
RuntimeCompiler
-> RuntimeInvocationPacket.segment_plan
-> ModelRequestPacket
-> PromptSegmentMap
-> PromptCacheRecord
-> PromptStabilityReporter
-> PromptAccountingLedger(prompt_stability.jsonl)
-> provider usage 回填
-> DeepSeek 诊断脚本展示 first_changed_section 与 hit rate
```

权责边界：

- `RuntimeCompiler` 只负责装配模型可见消息和 `segment_plan`。
- `ModelRequestBuilder` 只负责规范化 provider 请求和绑定 segment。
- `PromptCachePlanner` 只负责 stable prefix eligible 记录。
- `PromptStabilityReporter` 只负责生成稳定性报告、diff 上一轮报告、回填 provider usage。
- `PromptAccountingLedger` 只负责持久化事实。
- `diagnose_deepseek_prompt_cache.py` 只负责读 ledger 并解释。

## 4. 核心数据模型

`PromptStabilityReport` 字段：

```text
report_id
request_id
session_id
task_run_id
run_id
packet_id
invocation_kind
provider
model

session_cache_key
context_window_generation
compaction_generation

stable_prefix_hash
stable_prefix_tokens
stable_section_count
volatile_token_count

stable_sections[]
  section_id
  kind
  ordinal
  source_ref
  cache_role
  content_hash
  predicted_tokens

volatile_sections[]
  section_id
  kind
  ordinal
  source_ref
  cache_role
  volatility_reason
  predicted_tokens

dynamic_param_hash
dynamic_param_summary

previous_report_ref
first_changed_section
changed_sections[]

provider_usage
  prompt_tokens
  cached_tokens
  cache_read_tokens
  cache_creation_tokens
  cache_hit_rate

diagnostics
```

`session_cache_key` 第一阶段使用稳定派生值：

```text
session:<session_id> 或 task:<task_run_id> 或 request:<request_id>
```

当前实现采用事实指纹式代际，而不是伪造全局递增计数：

- `context_window_generation=1` 表示本轮存在 `replacement-history:*` 窗口替换引用；否则为 0。
- `compaction_generation=1` 表示本轮存在 compressed summary hash；否则为 0。
- 真实判断依据记录在 `diagnostics.context_window`，包括 `compressed_summary_hash`、`replacement_history_ref`、raw/recent/omitted history message counts、budget report 和 dynamic context diagnostics。

如果后续引入持久化 compact checkpoint 表，再升级为真实递增 generation。

## 5. Diff 规则

同一 `session_cache_key + invocation_kind + provider + model` 下，取上一条 report 作为比较对象。

Diff 顺序：

1. 比较 stable section 数量。
2. 按 ordinal 比较 stable section 的 `kind/source_ref/cache_role/content_hash`。
3. 第一处不同写入 `first_changed_section`。
4. 如果 stable prefix 不变但命中低，比较 `dynamic_param_hash`。
5. 如果都不变但 provider miss，诊断为 `provider_cache_cold_or_expired`。

`changed_sections` 只记录稳定前缀内变化，不把 volatile 区域变化视为 cache break。

## 6. 诊断规则

优先级：

1. 没有 stable prefix：`no_stable_prefix_boundary`。
2. stable prefix 第一段变化：`global_static_changed`。
3. stable prefix 中间段变化：`stable_section_changed`。
4. stable prefix 不变但 dynamic params 变：`dynamic_request_params_changed`。
5. stable prefix 不变且 params 不变但 cached tokens 为 0：`provider_cache_cold_or_expired`。
6. provider usage 缺失：`provider_usage_missing`。
7. cached tokens 大于 0：`provider_cache_hit`。

## 7. 实施阶段

### 阶段一：只读稳定性报告

文件：

- `backend/runtime/prompt_accounting/stability_models.py`
- `backend/runtime/prompt_accounting/stability_report.py`
- `backend/runtime/prompt_accounting/ledger.py`
- `backend/runtime/model_gateway/model_runtime.py`
- `backend/tests/model_runtime_regression.py`

完成标准：

- 每次有 `segment_plan` 的模型请求都生成 `prompt_stability.jsonl`。
- 报告能列出 stable / volatile sections。
- 同 session 连续请求能定位 `first_changed_section`。
- 不改变模型请求内容。

### 阶段二：DeepSeek 诊断脚本升级

文件：

- `backend/scripts/diagnose_deepseek_prompt_cache.py`
- `backend/tests/deepseek_prompt_cache_diagnostics_test.py`

完成标准：

- 输出最近 report 的 `stable_prefix_hash`、`first_changed_section`、`dynamic_param_hash`、`hit_rate`。
- 对低命中给出结构化原因。

### 阶段三：窗口代际接入

已接入 compiler prompt manifest 与 stability report：

- `RuntimeCompiler` 在 `prompt_manifest.context_window` 写入 compressed summary hash 与 replacement history ref。
- `QueryRuntime`、agent loop、task executor 将 prompt manifest 传入 `accounting_context`。
- `PromptStabilityReport.diagnostics.context_window` 记录上述事实。
- 由于当前项目还没有持久化 compact checkpoint 表，generation 字段只表达“是否存在窗口替换/压缩摘要”，不虚构递增代际。

### 阶段四：动态参数稳定性强化

纳入 provider 请求参数：

- model
- tools schema hash
- temperature/top_p
- max tokens
- stream / reasoning 参数

第一版已纳入：

- provider/model/base_url 归一化值。
- call_kind。
- tool_count 与 tools_hash。
- max_output_tokens。
- temperature 只在真实请求会生效时记录；DeepSeek thinking 模式下官方声明该参数不生效，因此不作为 cache-relevant 参数。
- thinking_mode。
- reasoning_effort。
- chat_openai_reasoning_effort。
- stream_policy。
- tool_choice / strict / parallel_tool_calls，按当前 DeepSeek 官方契约原样记录；thinking 模式支持工具调用，不应再为兼容旧规则过滤 tool_choice。

当前模型请求层没有显式暴露 response/output schema、top_p 或通用 provider extra body；DeepSeek `extra_body.thinking` 已由 `thinking_mode/reasoning_effort` 覆盖。后续只有当这些参数进入真实请求层时，才继续加入 `cache_relevant_params`。

## 8. 明确不做

- 不恢复本地 prompt 内容缓存。
- 不伪造 DeepSeek cache hit。
- 不把 compressed context 塞回 recent history。
- 不照搬 Anthropic `cache_control`。
- 不让稳定性报告参与 runtime 决策。

## 9. 自审

一致性检查：

- 与现有 `segment_plan` 不冲突：报告从 segment map 派生，不改变 segment plan。
- 与 DeepSeek 自动缓存不冲突：本地只记录结构和 usage，不声明命中真相。
- 与刚完成的 compressed context 调整一致：摘要仍走 `session_context.compressed_summary`。
- 与旧 prompt cache shim 一致：shim 继续 bypass，稳定性报告承担诊断职责。

遗漏检查：

- provider usage 缺失有独立诊断。
- stable prefix 不变但命中低有动态参数和冷缓存解释。
- compact/window 代际采用事实指纹式实现，未伪造不存在的全局递增计数。
- 测试覆盖连续请求、稳定段变化、动态参数变化、工具调用选项变化、跨 run 同 session 对比、compressed context 装载、context window 事实记录、provider usage 回填。

结论：计划已按四个阶段完成当前可落地范围。实现只记录 prompt/context/request 事实，不改变模型请求语义；剩余可升级项仅限未来出现真实 compact checkpoint 表或新增 provider 请求参数时继续扩展。
