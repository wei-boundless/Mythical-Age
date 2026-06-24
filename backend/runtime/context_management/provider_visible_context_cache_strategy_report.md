# Provider Prompt Cache 命中技术报告

## 1. 报告目的

本文说明上下文装配系统的 provider prompt cache 命中问题，重点回答三个问题：

1. 之前为什么 provider 返回的缓存命中率会掉到 50% 以下。
2. 当前链路为什么能够让应该命中的旧上下文稳定命中。
3. 真实运行链路中，哪些模块、字段、数据结构共同保证 provider-visible 前缀一字不动。

本文讨论的是 provider 真实返回的 prompt cache 命中，不讨论本地预测命中。

核心原则只有一句：

```text
已经被 provider 成功接收过的 provider-visible 旧字节，下一次请求必须原样位于新请求最前面；新内容只能追加在其后。
```

如果这个原则成立，DeepSeek 可以复用旧前缀缓存。如果这个原则不成立，本地 metadata 写得再漂亮，provider 也只会按真实 payload 计算低命中。

## 2. DeepSeek 缓存机制的工程含义

DeepSeek KV Cache 是 provider 侧自动前缀缓存。我们不显式上传 cache key，也不能靠本地声明告诉 provider 哪些段是 cacheable。DeepSeek 只看最终发送给它的请求内容。

官方参考：

- https://api-docs.deepseek.com/guides/kv_cache
- https://api-docs.deepseek.com/news/news0802

provider 返回中与缓存相关的关键字段是：

```text
prompt_cache_hit_tokens
prompt_cache_miss_tokens
prompt_tokens
```

运行时记录时映射为：

```text
provider_cached_tokens
provider_cache_miss_tokens
provider_returned_cache_hit_rate
```

真实命中率应按 provider 返回计算：

```text
provider_hit_rate = prompt_cache_hit_tokens / prompt_tokens
```

或在 hit/miss 字段齐全时按：

```text
provider_hit_rate = cached_tokens / (cached_tokens + miss_tokens)
```

本地 `segment_map`、`prefix_hash`、`cache_scope`、`cache_role`、`prefix_tier` 只能帮助我们诊断，不是 provider 的实际判断依据。

## 3. 之前低命中的根因

之前低命中不是 DeepSeek 不能缓存，也不是上下文总量太小。根因是我们的 runtime 没有严格保持 provider-visible 旧前缀的字节稳定。

旧链路的典型请求形态是：

```text
第 N 次请求：
S + C_old + T_old

第 N+1 次请求：
S + C_old + C_new + T_new
```

其中：

```text
S      = 静态前缀、系统稳定提示词、工具索引等稳定内容
C_old  = 上一轮已经提交的上下文记忆
T_old  = 上一轮动态尾部、action contract、运行时控制尾部、followup 指引等
C_new  = 本轮新增上下文、工具观察、增量事实、会话增量
T_new  = 本轮动态尾部
```

语义上，`T_old` 不应该成为长期语义记忆，这个判断是对的。

问题在于，我们把两个概念混在了一起：

```text
不是语义记忆
```

和：

```text
不需要 provider-visible 原文重放
```

这两个概念不是一回事。

只要 `T_old` 曾经被发送给 DeepSeek，并且 provider 成功返回了响应，它就已经是上一轮 provider-visible payload 的一部分。下一轮如果直接把 `T_old` 删除或替换成 `C_new`，那么上一轮完整请求就不再是下一轮请求的前缀。

provider 只能命中：

```text
S + C_old
```

provider 无法命中：

```text
S + C_old + T_old
```

因为 `T_old` 在新请求里消失了，或者它后面的边界被移动了。

这就是之前命中率会掉到 50% 以下的核心技术原因：不是旧上下文本身不能缓存，而是旧 provider-visible payload 的中后段没有被原样保留在下一次请求的前缀里。

## 4. 为什么这个问题会被本地诊断掩盖

本地计划层可能认为某些段是稳定的：

```text
cache_scope = task
cache_role = session_stable
prefix_tier = task
```

但是 DeepSeek 不看这些字段。

DeepSeek 看到的是最终 provider payload：

```text
messages + tools + request params
```

所以真正的问题不是：

```text
这段在本地是否被标记为 stable？
```

而是：

```text
这段 role/content/provider-visible message 是否在最终请求里以完全相同的字节、相同顺序、相同位置出现？
```

如果本地 metadata 稳定，但发送前重新渲染、重新排序、丢了上一轮动态尾、改了空格、改了 role、改了 tool schema、改了 reasoning_content，provider 都会按真实 payload 重新计算 miss。

## 5. 旧链路中的具体坏点

旧逻辑中存在一个看似合理但会破坏 provider cache 的规则。

在 provider-visible ledger 组装中，普通逻辑会跳过不应语义提交的内容：

```python
if policy.commit_policy == "never_commit" or policy.section == "dynamic_tail":
    continue
```

这个规则对“语义记忆”是正确的：

```text
dynamic_tail 不应该进入长期记忆
runtime action contract 不应该成为事实记忆
lifecycle guidance 不应该变成用户上下文事实
```

但它对 provider cache 是不完整的。

因为 provider cache 需要关心的是：

```text
上一轮 provider 已经看见的字节，下轮是否还在前缀里？
```

旧链路把 dynamic tail 视为 `never_commit` 后，等价于：

```text
不进入语义记忆
也不进入 provider-visible replay
```

这会导致：

```text
上一轮已经发送成功的 T_old 下轮不重放
新内容 C_new 插到 T_old 原来的位置
provider 前缀边界提前断开
```

如果 `T_old`、工具观察、action contract、followup frame token 量较大，provider 命中率就会被显著拉低。

## 6. token 结构示例

下面是低命中的典型结构示例。

假设上一轮请求：

```text
S       = 8k tokens
C_old   = 7k tokens
T_old   = 12k tokens
总计    = 27k tokens
```

下一轮如果错误地丢掉 `T_old`，并在其位置追加新内容：

```text
S + C_old + C_new + T_new
```

provider 能稳定复用的只有：

```text
S + C_old = 15k tokens
```

如果新请求总 prompt 是 31k tokens，命中率大约是：

```text
15k / 31k = 48.38%
```

这就是“上下文看起来不大，但命中率只有五十不到”的技术解释。

真正的问题不是 token 量不够，而是 provider-visible 前缀在 `T_old` 边界处断了。

## 7. 当前修复的核心设计

当前修复不是把 dynamic tail 变成语义记忆，而是引入一个更精确的状态：

```text
provider-visible replay-only
```

它表示：

```text
provider cache 可见：是
语义记忆可见：否
长期事实提交：否
```

也就是：

```text
这段文字已经被 provider 看过，所以下轮为了缓存需要原样重放；
但这段文字不是用户事实、不是长期记忆、不是会话语义上下文。
```

当前目标形态是：

```text
第 N 次请求：
S + C_old_replay + C_current + T_current

provider 成功后：
C_current 和必要的 T_current 以 provider-visible replay-only 方式封存

第 N+1 次请求：
S + C_old_replay + C_current_replay + T_current_replay_only + C_next + T_next
```

对 provider 来说，这是 append-only：

```text
旧 provider-visible 前缀 + 新增内容
```

对语义记忆系统来说，`T_current_replay_only` 仍然不可见：

```text
semantic_memory_visible = false
semantic_memory_commit_policy = never_commit
```

这就是当前方案为什么既能保证缓存，又不会污染记忆。

## 8. 当前真实链路总览

真实链路如下：

```text
Runtime specs
  -> compiler._fixed_context_package_message_specs
  -> provider_visible_context_ledger.assemble_provider_visible_context_specs
  -> prompt segment plan / materialized model messages
  -> model_runtime._provider_visible_append_only_passthrough
  -> ModelRequestBuilder.build
  -> provider_payload_manifest / prefix hash / segment binding
  -> DeepSeek API request
  -> provider usage extraction
  -> model_runtime._confirm_provider_visible_context_success
  -> provider_visible_context_ledger.confirm_provider_visible_context_entries
  -> next request ledger replay
```

其中有三条关键线：

1. 装配线：决定哪些内容位于 provider-visible 前缀。
2. 发送线：保证发送前不再重写 message。
3. 确认线：只有 provider 成功后才把当前新增内容封存为下轮可重放前缀。

## 9. 装配线：compiler 如何处理上下文段

文件：

```text
backend/harness/runtime/compiler.py
```

关键函数：

```text
_model_messages_and_segment_plan(...)
_fixed_context_package_message_specs(...)
_provider_visible_replay_only_dynamic_tail_spec(...)
_provider_visible_context_memory_specs(...)
```

`_fixed_context_package_message_specs(...)` 会先把输入 specs 分到物理上下文桶：

```text
static_prefix
context_append
noncommitted_context_memory
dynamic_tail
```

当前默认 DeepSeek 生产路径中，dynamic tail 不再直接丢弃，而是转换为 replay-only candidate：

```python
elif section == DYNAMIC_TAIL:
    if independent_dynamic_tail_enabled:
        dynamic_tail.append((index, spec))
    else:
        context_append.append(
            _provider_visible_replay_only_dynamic_tail_spec(...)
        )
```

这段逻辑的意义是：

```text
默认策略下，动态尾部参与 provider-visible append-only 前缀；
但它以 replay-only 形式进入，不成为语义记忆。
```

`_provider_visible_replay_only_dynamic_tail_spec(...)` 会写入关键 metadata：

```text
context_dynamic_tail_folded_into_context_memory = true
context_physical_segment = context_memory
provider_visible_runtime_tail_replay_only = true
semantic_memory_commit_policy = never_commit
semantic_memory_visible = false
cache_scope = task
cache_role = session_stable
prefix_tier = task
```

这一步修复了旧链路的根因：

```text
旧：dynamic_tail => never_commit => 下轮不重放
新：dynamic_tail => replay_only_candidate => provider 成功后下轮原文重放
```

## 10. ledger 线：旧 provider-visible 原文如何被封存和重放

文件：

```text
backend/runtime/context_management/provider_visible_context_ledger.py
```

关键函数：

```text
assemble_provider_visible_context_specs(...)
provider_visible_context_append_candidate_spec(...)
provider_visible_context_replay_only_candidate_spec(...)
confirm_provider_visible_context_entries(...)
```

### 10.1 assemble 阶段

`assemble_provider_visible_context_specs(...)` 是旧 provider-visible context 的权威来源。

它做三件事：

1. 读取当前 scope 的 ledger。
2. 找到已确认的 provider-visible entries。
3. 把它们按 ledger 顺序作为 `context_memory_prefix` 重放。

ledger replay 产生的 spec 带有：

```text
context_cache_section = context_memory_prefix
context_assembly_section = context_memory_prefix
fixed_context_package = context_memory_prefix
provider_visible_payload_authority = runtime.context_management.provider_visible_context_ledger.replay
provider_visible_hash = stored provider-visible hash
model_message = stored provider-visible message
cache_scope = task
cache_role = session_stable
prefix_tier = task
```

关键点：

```text
重放使用 ledger 中保存的 provider-visible message，而不是重新渲染 prompt 文本。
```

这样可以避免：

```text
多一个空格
少一个标题
role 改变
content wrapper 改变
排序改变
工具观察被重新格式化
```

这些都会破坏 provider prefix cache。

### 10.2 append candidate 阶段

当前新增内容不会立刻写死到 ledger。

它先被标记为 candidate：

```text
provider_visible_context_ledger_commit_stage = provider_success_required
provider_visible_context_ledger_item_key = ...
provider_visible_hash = ...
provider_visible_context_candidate_message = ...
provider_visible_context_candidate_kind = ...
provider_visible_context_candidate_source_ref = ...
provider_visible_context_candidate_semantic_commit_class = ...
provider_adapter_contract = deepseek_v4_provider_visible_message_v1
```

这表示：

```text
这段内容本轮会发送给 provider；
只有 provider 成功返回后，才能成为下轮可重放的旧前缀。
```

### 10.3 confirm 阶段

文件：

```text
backend/runtime/model_gateway/model_runtime.py
```

关键函数：

```text
_finish_prompt_accounting(...)
_confirm_provider_visible_context_success(...)
_provider_visible_context_commit_candidates_from_accounting(...)
```

provider 成功返回后，runtime 从 `model_request.provider_payload_manifest.segments` 中找出待确认的 candidate，并调用：

```text
confirm_provider_visible_context_entries(...)
```

确认时会校验：

```text
scope 存在
item_key 存在
provider_visible_hash 存在
candidate_message 存在
computed_hash == expected_hash
adapter_contract 一致
同 item_key 已确认内容 hash 没有变化
```

只有这些条件都满足，entry 才会写入 ledger。

这保证了：

```text
ledger 里保存的一定是 provider 成功看过的、hash 可验证的 provider-visible message。
```

## 11. 发送线：为什么发送前不能再处理 message

文件：

```text
backend/runtime/model_gateway/model_runtime.py
```

关键函数：

```text
_provider_visible_append_only_passthrough(...)
```

这条线的原则是：

```text
上下文装配在发送前已经完成，provider gateway 不再重新组织 provider-visible prefix。
```

当前逻辑会把 message 规范化为 provider payload，但不会改变上游 append-only 顺序：

```text
provider_gateway_preserves_upstream_append_only_message_order
```

这是重要边界。

如果发送层再做“修正”“重排”“补尾巴”“替换上下文”，就会把 compiler 和 ledger 的稳定性全部破坏。当前修复把权威放回装配层和 ledger，不让 gateway 重新决定上下文结构。

## 12. ModelRequestBuilder 和 provider payload manifest 的作用

文件：

```text
backend/runtime/model_gateway/model_request.py
backend/runtime/model_gateway/provider_payload.py
```

关键作用：

1. 将最终 messages/tools/request params 转为 provider transport payload。
2. 根据 segment_plan 绑定每个 provider message 到对应 segment。
3. 计算真实 provider payload hash、prefix hash、tool catalog hash、cache-sensitive params hash。
4. 生成 `provider_payload_manifest`，供后续确认 candidate 和诊断 cache boundary 使用。

这层不是 provider cache 的来源，但它是诊断真实发送内容的证据层。

它能告诉我们：

```text
planned segment 是否真的绑定到了 provider message
message hash 是否和计划一致
工具 schema 是否改变
request params 是否改变
dynamic_tail 后面是否还有 stable segment
```

如果 provider 命中低，应优先查这里，而不是只看上游语义上下文。

## 13. provider usage 线：为什么必须看 provider 返回

文件：

```text
backend/runtime/model_gateway/model_runtime.py
```

关键位置：

```text
_finish_prompt_accounting(...)
extract_provider_usage(...)
PromptCachePlanner.with_provider_usage(...)
```

provider 返回后，runtime 会记录：

```text
provider_prompt_tokens
provider_cached_tokens
provider_cache_miss_tokens
provider_returned_cache_hit_rate
```

报告缓存命中时必须看这条线。

不能只看：

```text
local_prediction
stable_prefix_predicted_tokens
segment cache_role
prefix_tier
本地 estimated coverage
```

这些只能解释原因，不能作为最终命中率。

## 14. 当前为什么能达到 95%+

当前能达到 95%+ 的原因不是“压缩”或“减少上下文”，而是 provider-visible 前缀终于被锁住了。

成功形态是：

```text
第 N 次 provider 成功：
S + C1 + T1

ledger confirm：
C1 confirmed
T1 confirmed as provider_visible_replay_only

第 N+1 次发送：
S + C1(replay) + T1(replay-only) + C2 + T2
```

对于 provider：

```text
S + C1 + T1
```

仍然完整位于新请求前缀。

所以 provider 可以命中旧前缀，只 miss 新增：

```text
C2 + T2 + 当前用户输入 + 当前工具观察 + 当前请求参数变化
```

如果旧前缀是 31,744 tokens，新 miss 是 797 tokens，则 provider 返回率为：

```text
31744 / (31744 + 797) = 97.55%
```

这就是前面能够跑到 95%+ 的直接技术原因。

## 15. 之前为什么只有五十不到

之前低命中形态更接近：

```text
第 N 次：
S + C1 + T1

第 N+1 次：
S + C1 + C2 + T2
```

如果 `T1` 很大，provider 只能命中：

```text
S + C1
```

即使 `C1` 被本地认为是稳定上下文，`T1` 丢失后，provider 看到的公共前缀也已经断掉。

典型 token 结构：

```text
S + C1 = 14k
T1     = 12k
C2+T2  = 4k
新请求总量 = 30k
```

实际 provider 命中约为：

```text
14k / 30k = 46.67%
```

所以五十不到是合理后果，不是随机波动。

根因就是：

```text
旧 provider-visible tail/action/followup 字节没有成为下轮 provider-visible prefix。
```

## 16. 当前哪些内容必须 miss

当前设计不是追求 100% hit。

以下内容必须 miss：

```text
当前用户输入
当前 runtime cursor
当前工具观察增量
当前 exact read evidence injection
当前 action contract
当前 lifecycle guidance
当前 pending user steer
当前 active skill body
当前新增事实/会话增量
当前动态尾部
发生变化的 native tool schema
发生变化的 request params
```

关键要求是：

```text
已经 provider-confirmed 的旧 provider-visible 内容必须命中。
```

也就是说，miss 只能来自真正新增或本轮变化的内容，不能来自旧上下文被改写、移动、丢弃。

## 17. 结构化失败是什么意思

结构化失败不是“不让系统继续用”。

结构化失败的含义是：

```text
当前 ledger 无法证明某段旧 provider-visible 字节仍然可信，所以不能把它伪装成稳定前缀继续重放。
```

典型失败：

```text
receipt 损坏
ledger schema 版本不匹配
adapter contract 不一致
同 item_key 的 provider_visible_hash 改变
candidate message hash mismatch
confirmed entry message 缺失
provider-visible message 结构不完整
```

正确处理不是直接丢失全部记忆，而是：

```text
记录 recovery_required
停止重放可疑 provider-visible prefix
优先使用 recovery package / 压缩包替代上下文继续运行
在安全状态上重新建立新的 provider-visible prefix
```

这能最大程度保留记忆，同时避免污染 cache ledger。

## 18. DeepSeek V4 reasoning_content 的关系

DeepSeek V4 thinking + tool call 场景下，assistant tool-call 历史可能需要保留 provider-visible `reasoning_content`。

如果历史 assistant tool-call message 被重放时丢了 `reasoning_content`，可能造成两个问题：

1. provider 请求语义不完整或不符合 DeepSeek V4 thinking 工具调用契约。
2. provider-visible message hash 改变，导致旧前缀无法命中。

因此，当前诊断里需要检查：

```text
messages_include_provider_reasoning_content
assistant_tool_call_reasoning_content_indexes
assistant_tool_call_missing_reasoning_content_indexes
```

这不是独立的缓存策略，而是 provider-visible byte stability 的一部分。

## 19. 两段式和三段式在本文中的位置

本文核心不是两段式/三段式选择，而是 provider-visible prefix 是否稳定。

默认生产策略仍然应保证：

```text
旧 provider-visible 内容一字不动重放
新内容只追加
```

三段式独立 dynamic tail 可以作为 provider/model strategy 实验，但它天然会让上一整包不再成为下一整包的严格前缀：

```text
S + C1 + T1
S + C1 + C2 + T2
```

它仍然可能命中 `S + C1`，但不能提供默认 append-only 模型那种最强保证。

因此当前生产目标不是追求形式上的三段式，而是追求：

```text
能命中的旧 provider-visible 字节必须命中。
```

## 20. 排查缓存命中低的顺序

如果 provider 返回 hit rate 低于预期，按以下顺序查：

1. 查 provider usage：

```text
prompt_cache_hit_tokens
prompt_cache_miss_tokens
prompt_tokens
provider_cache_hit_rate_source
```

2. 查 provider payload manifest：

```text
message order
message hashes
tools hash
cache_sensitive_params_hash
stable_segment_after_dynamic_tail_count
dynamic_tail_after_cache_boundary
```

3. 查 ledger replay：

```text
provider_visible_context_ledger_scope
provider_visible_context_ledger_entry_index
provider_visible_hash
provider_visible_payload_authority
semantic_memory_visible
provider_visible_replay_only
```

4. 查 current append candidate：

```text
provider_visible_context_ledger_commit_stage
provider_visible_context_candidate_message
provider_visible_context_candidate_semantic_commit_class
provider_adapter_contract
```

5. 查发送前是否还有 rewrite：

```text
provider_visible_append_only_transport
provider_gateway_preserves_upstream_append_only_message_order
unplanned_message_count
segment_binding_content_mismatch_count
```

6. 查工具和请求参数：

```text
tool_catalog_hash
stable_tool_catalog_hash
tool_call_options
response_format
thinking_mode
reasoning_effort
model
base_url
```

7. 查 DeepSeek V4 thinking 历史：

```text
provider_reasoning_contract.status
assistant_tool_call_missing_reasoning_content_indexes
```

## 21. 验证标准

合格标准必须来自 provider 返回。

暖机后的真实 agent 调用应满足：

```text
provider_returned_cache_hit_rate >= 0.95
```

并且 miss 应能解释为：

```text
当前用户输入
当前工具观察
当前 action/lifecycle contract
当前 dynamic tail
当前新增上下文
当前变化的工具或请求参数
```

如果旧 context_memory_prefix、旧 replay-only tail、旧 action/tool-followup transcript 重新 miss，就说明 provider-visible 前缀仍然没有封死。

## 22. 当前实现带来的保证

当前实现能提供以下保证：

```text
1. 旧 provider-visible 内容由 ledger 原文重放，不靠重新渲染。
2. dynamic tail 可以 provider-visible replay-only，不污染语义记忆。
3. current append 只有 provider 成功后才 confirm。
4. confirm 时校验 hash、item_key、adapter contract。
5. provider usage 是最终命中依据。
6. 发送层不重新决定上下文顺序。
7. model_request/provider_payload_manifest 提供真实发送证据。
```

这就是为什么当前系统从设计上可以把命中率拉回 95% 左右：旧 provider-visible 前缀不再在动态尾/工具 followup/action contract 边界处被切断。

## 23. 总结

之前缓存命中只有五十不到，根因不是缓存机制本身，也不是上下文 token 量小，而是旧 provider-visible 前缀没有被严格原文重放。

旧系统把：

```text
不进入语义记忆
```

误处理成：

```text
不需要 provider-visible replay
```

导致上一轮已经发送给 DeepSeek 的动态尾部、action contract、followup 控制内容在下一轮消失或移位，provider 只能命中更短的公共前缀。

当前系统把二者拆开：

```text
semantic_memory_visible = false
provider_visible_replay_only = true
```

并通过 ledger 在 provider 成功后封存 exact provider-visible message，下轮从 ledger 原文重放，再追加新内容。

因此，当前能够实现：

```text
旧上下文必须原样命中
新增内容才允许 miss
```

这也是 provider 返回命中率能够恢复到 95%+ 的技术原因。
