# Provider-Visible 上下文、Prefix Cache 与 Fork 交接报告

日期：2026-06-26
更新：2026-06-27，物理模型改为插线式 `provider_visible_context_prefix`。

## 当前主链

运行时上下文链路为：

```text
ContextSegmentPolicy
-> PhysicalContextPlan
-> ProviderPayloadManifest
-> ProviderRequestContextCommit
-> ProviderVisibleContextLedger
-> Session/Fork Boundary
```

旧的独立 physical assembler 不再是运行时主链。section、prefix、replay、commit policy 归 `context_segment_policy.py`；物理排序和 cache-spine membership 归 `physical_context_plan.py`。

## 权限边界

`ContextSegmentPolicy` 只负责语义分类：

- `static_prefix`
- `context_memory_prefix`
- `context_append`
- `dynamic_tail`

`PhysicalContextPlan` 只负责物理 lane：

- `global_static_prefix`
- `provider_visible_context_prefix`
- `current_turn_tail`
- `never_replay_tail`

只有下面这段进入 cache spine：

```text
cache_spine = global_static_prefix + provider_visible_context_prefix
request = cache_spine + current_turn_tail + never_replay_tail
```

同一物理段内采用插线式处理：provider-visible ledger replay 无论语义是 active、historical-only、tool transcript 还是 runtime replay-only，都落入 `provider_visible_context_prefix`，再按 `provider_visible_context_ledger_entry_index` 线性排列。语义差异只能进入 `semantic_visibility`、`semantic_commit_class`、`validity_scope` 等 metadata，不允许改变物理位置。

## Prefix Cache 规则

本轮 append 内容不是同请求 cache-spine 内容。

`context_append` 映射到 `current_turn_tail`。它可以被 provider 看见，也可以在 provider success 后确认进 ledger，但不能在同一请求里计入可命中的 prefix。下一轮确认条目从 ledger replay 为 `context_memory_prefix`，再统一进入 `provider_visible_context_prefix`。

这避免旧失败模式：

```text
current append -> provider success 前提前进入 prefix -> 虚假的 cache-spine continuity
```

## Provider Payload 规则

Provider payload cache hash 使用物理 cache spine，不再只看 `cache_role/prefix_tier`。

prefix hash 来源：

```text
transport_contract_hash + physical cache-spine message segment hashes
```

缺失 `physical_prefix_lane` 是违规。Provider payload 不从旧 section 字段猜 lane。

## Ledger 规则

`provider_visible_context_ledger.py` 是 confirmed-entry ledger，不负责判断 candidate 是否可封存。它只接收已被 policy 接受的 candidate，并且只在 provider success 后记录。

失败请求可以创建 provider request commit record，但不能确认 provider-visible replay entry。

## Fork 交接

fork 继承锚定 confirmed context state：

- fork point context commit
- parent provider-visible ledger anchor
- cache spine hash
- compaction generation

子 session 读取父 session 到 fork anchor 为止的 confirmed entries，然后只在子 scope 下写入后续 entries。父条目和子条目都在同一 `provider_visible_context_prefix` 物理线中按 entry 顺序插入；fork snapshot 显式保存 fork-point compaction generation，compiler inheritance 随父 anchor metadata 传递。

## Removed Old Runtime Entrypoints

Removed from runtime:

- the standalone physical assembler module
- provider-cache-policy physical-model switching
- provider-payload ordering diagnostics based on old section-order fields
- legacy physical segment/rank and prefix-state metadata emitted by context policy
- test fossils that protected the old fixed-package path
- metadata writes and fallback reads for the old assembly section field

## Remaining Boundaries

Tool context is now projected into provider request context commits as `tool_context_anchor` and `tool_context_projection`.

Further deepening still belongs in the tool-memory layer:

- large tool output should be stored by ref/summary before model entry
- fork child tool observations must write only to child scope
- provider-bound history must keep tool-use/tool-result pairing closed

These are not allowed to reintroduce another context assembly path; they must feed the same policy and physical plan chain.
