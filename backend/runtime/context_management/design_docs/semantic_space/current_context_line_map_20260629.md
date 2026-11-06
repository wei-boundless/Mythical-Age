# 当前上下文线图

日期：2026-06-29

本文档记录当前实现里的语义空间、provider-visible 账本、物理上下文 lane 和 provider cache spine 的实际连线。

这是现状文档，不是未来计划。缓存权威只来自物理结构。语义结构只负责识别内容、语义槽位和排序空间，不负责决定 cache spine 成员。

## 核心原则

```text
producer/message spec
-> kind/source_kind/content_source
-> ContextSegmentPolicy section + semantic_slot + semantic_slot_rank
-> ProviderVisibleContextLedger append/replay boundary
-> PhysicalContextPlan lane
-> ProviderPayloadManifest physical cache spine
-> provider request bytes
```

一条上下文线只有在同一段旧上下文以相同 provider-visible 字节、相同顺序、相同物理 prefix lane 回放时，才算缓存线接准。`stable`、`expected prefix`、`task context` 这类语义标签本身不是缓存权威。

上下文位置是固定插线位，但不是固定数组下标。固定的是 `context_cache_section -> semantic_slot -> physical_prefix_lane` 这组语义/物理 lane 关系；数组顺序只是该关系在当前 provider request 中的物理投影。任何新结构都必须挂到这些 slot/lane 上，不能新建旁路位置权威。

## 权威边界

| 层级 | 权威文件 | 负责 | 禁止负责 |
| --- | --- | --- | --- |
| Context segment registry | `backend/runtime/context_management/context_segment_registry.py` | kind 默认声明：section、semantic slot、source kind、content source、capability group、dynamic tier | provider payload 字节顺序 |
| Context segment policy | `backend/runtime/context_management/context_segment_policy.py` | section、semantic slot、semantic rank、commit policy、replay policy、prefix cache policy | 最终 provider 物理排序 |
| Provider-visible context ledger | `backend/runtime/context_management/provider_visible_context_ledger.py` | 已确认旧上下文回放，以及 provider 成功后可封存的 current append candidate | dynamic runtime tail 回放 |
| Physical context plan | `backend/runtime/context_management/physical_context_plan.py` | 物理 lane 分配和 cache-spine lane 成员资格 | 重新解释 task/control 语义 |
| Provider payload manifest | `backend/runtime/model_gateway/provider_payload.py` | provider transport segments、tool schema prefix 校验、physical cache-spine 诊断 | 从旧 stable-prefix 元数据重新推断语义 section |

## 当前物理 Lane

| 物理 lane | 含义 | 进入 cache spine |
| --- | --- | --- |
| `global_static_prefix` | 静态模型可见契约、环境、能力目录和 tool index 消息 | 是 |
| `provider_visible_context_prefix` | 从账本回放的已确认 provider-visible 旧上下文 | 是 |
| `current_turn_tail` | 本轮 provider request 里 materialize 的 current append | 否 |
| `never_replay_tail` | 不允许回放的运行态/控制态尾巴 | 否 |

只有 `global_static_prefix` 和 `provider_visible_context_prefix` 是 cache-spine lane。

## 语义上下文线

### 静态 Prefix 线

```text
STATIC_PREFIX
-> global_static_prefix
-> provider payload included cache-spine message segment
```

用途：稳定的模型可见身份、契约、能力目录、项目/环境说明和 tool index。

典型 kind：

- `global_static`
- `agent_stable`
- `personality_stable`
- `environment_stable`
- `project_instructions_stable`
- `action_schema_static`
- `capability_catalog`
- `tool_index_stable`
- `task_prompt_contract`
- `task_run_contract_stable`
- `task_contract_stable`
- `artifact_scope_stable`
- `runtime_stable_contract`

物理结果：

- Section：`static_prefix`
- Lane：`global_static_prefix`
- Cache-spine participation：是
- Replay 行为：静态 provider context，不走 memory replay

### Provider-Visible Memory Prefix 线

```text
CONTEXT_MEMORY_PREFIX
-> provider_visible_context_prefix
-> provider payload included cache-spine message segment
```

用途：已经经过 provider request 确认，并从 provider-visible ledger 回放的旧上下文。

典型 kind：

- `runtime_memory_context`
- `provider_visible_tool_transcript_replay`
- `provider_visible_user_context_replay`
- `provider_visible_user_message_replay`
- `provider_visible_assistant_message_replay`
- `provider_visible_context_replay`

物理结果：

- Section：`context_memory_prefix`
- Lane：provider-visible 可封存时为 `provider_visible_context_prefix`
- Cache-spine participation：是
- Replay 行为：provider-visible ledger replay

这是旧上下文缓存命中的关键线。上一轮已经发送过的旧上下文，下一轮必须以相同 provider-visible 字节和相同顺序出现在这个 lane，且必须位于任何 current-turn tail 之前。否则就是物理 prefix 断了，即使语义含义没有变化。

### Current Append 线

```text
CONTEXT_APPEND
-> current_turn_tail
-> provider payload excluded message segment
-> provider success
-> ledger confirmation
-> next request CONTEXT_MEMORY_PREFIX
```

用途：本轮新增上下文。本轮只 materialize 一次；provider 成功后，下一轮才可以通过账本封存并回放成旧上下文。

典型 kind：

- `provider_protocol_history`
- `current_turn_user_context`
- `single_agent_turn_user_steer_context`
- `user_steering_context_append`
- `session_history`
- `incremental_context_frame`
- `task_state_replay_entry`
- `task_start_inherited_context`
- `single_agent_turn_tool_call`
- `tool_transcript_delta`
- `read_evidence_context`
- `evidence_index_cursor`
- `attachment_context_index`
- `editor_context_index`

物理结果：

- Section：`context_append`
- Lane：`current_turn_tail`
- 当前 request 的 cache-spine participation：否
- 下一轮 request 的 cache-spine participation：只有 provider-visible ledger 将它回放为 `context_memory_prefix` 后才是

### Dynamic Tail 线

```text
DYNAMIC_TAIL
-> never_replay_tail
-> provider payload excluded message segment
```

用途：当前运行态/控制态。它不能成为旧上下文回放，也不能成为缓存 prefix。

典型 kind：

- `bound_task_runtime_context`
- `task_goal_context`
- `task_plan_context`
- `task_todo_context`
- `task_runtime_boundary_dynamic`
- `graph_node_runtime_context`
- `current_editor_evidence_delta`
- `read_evidence_injection`
- `incremental_context_cursor`
- `active_skills`
- `session_history_tail_context`
- `dynamic_projection`
- `volatile_runtime_state`
- `volatile_task_state`
- `turn_state_guidance`
- `turn_attention_index`
- `turn_operating_contract`
- `runtime_control_signal_tail`
- `partial_stream_recovery_instruction`
- `partial_stream_recovery_visible_prefix`

物理结果：

- Section：`dynamic_tail`
- Lane：`never_replay_tail`
- Cache-spine participation：否
- Replay 行为：永不作为旧上下文回放

当 recovery 内容是当前 runtime control 时，它属于这里。因为它物理上在稳定 lane 后面，所以它不应该破坏 cache spine。

## Current Append 的语义排序

`context_append` 内容先按语义 rank 排序，再进入物理装配。当前 rank 表是：

| Semantic slot | Rank |
| --- | ---: |
| `recovery_or_recent_work_facts` | 10 |
| `provider_protocol_history` | 15 |
| `selected_memory_and_task_state_facts` | 20 |
| `task_goal_context` | 21 |
| `task_plan_context` | 22 |
| `task_todo_context` | 23 |
| `current_user_intent` | 30 |
| `active_user_steer_content` | 35 |
| `evidence_refs_and_file_state_facts` | 40 |
| `tool_transcript` | 70 |
| `context_memory_append` | 90 |
| `action_contract` | 95 |

这只是语义空间排序。缓存行为之后由物理 lane 决定。

## Provider-Visible 账本线

账本线有两种形态。

本轮 append candidate：

```text
current append candidate
-> provider_visible_context_ledger_commit_stage=provider_success_required
-> current_turn_tail in this request
-> confirmation after provider success
```

已确认 ledger entry：

```text
confirmed ledger entry
-> context_cache_section=context_memory_prefix
-> fixed_context_package=context_memory_prefix
-> provider_visible_context_ledger_entry_index
-> provider_visible_context_prefix in the next request
```

`provider_visible_context_prefix` 内部的回放顺序由 `provider_visible_context_ledger_entry_index` 决定。这就是旧上下文从缓存角度必须保持稳定的物理顺序。

Provider-native 工具调用历史在这条线内还有一个更小的原子结构：

```text
assistant(tool_calls[])
-> tool(tool_call_id)
```

这个结构的 metadata 只允许描述 `round_id`、`round_member_role` 和 `round_order`。它不能决定上下文插线位置；工具轮本轮仍是 `context_append -> current_turn_tail`，成功封存后的下一轮才是 `context_memory_prefix -> provider_visible_context_prefix`。

## Provider Payload 缓存线

provider payload 只在下面条件成立时，把 message segment 标成 cache-spine included：

```text
physical_prefix_lane in {
  global_static_prefix,
  provider_visible_context_prefix
}
```

所有 current-tail lane 都排除在 cache spine 之外：

```text
current_turn_tail -> excluded
never_replay_tail -> excluded
```

provider 原生 tool schema 是单独的物理 prefix 组件。只有当它和稳定 tool index 或 tool catalog manifest 校验一致时，才能 included；如果不一致，它必须成为 blocker，不能静默变成 cacheable。

## 禁止串线

- 不允许创建 `task` cache tier。合法 prefix tier 只有 `provider_global`、`session`、`volatile`、`none`。
- 不允许用 semantic layer name 作为缓存权威。
- 不允许让 `DYNAMIC_TAIL` 或 recovery control 通过 `context_memory_prefix` 回放。
- 不允许对已封存 provider-visible replay 再做 capability filtering 重分类。
- 不允许任何 cache-spine lane 出现在 `current_turn_tail` 或 `never_replay_tail` 之后。
- 不允许 provider payload 从旧 stable-prefix metadata 推断 lane。

## 当前需要继续核查的风险

`backend/runtime/context_management/physical_context_plan.py` 里的本地 `content_hash` 仍由以下字段组成：

```text
role + content + kind + source_ref
```

provider payload 的 cache-spine hash 已经按 provider payload segment 和 physical lane participation 计算，但如果缓存账本、健康系统或 break detector 仍把这个本地 physical plan hash 当成缓存权威，那么 `kind/source_ref` 这种语义字段仍可能错误影响缓存断点判断。

必须坚持的解释：

- 权威缓存 prefix 是物理 prefix lane 里的 provider-visible bytes。
- `kind`、`source_ref` 这类语义字段可以用于诊断和身份辅助。
- 除非它们改变了实际 provider-visible prefix 字节、物理 lane 或物理顺序，否则不能成为 provider cache-spine anomaly reason。

## 代码证据

| 证据 | 文件 |
| --- | --- |
| section 常量和 kind 声明 | `backend/runtime/context_management/context_segment_registry.py` |
| 语义 rank 表和 section/cache policy | `backend/runtime/context_management/context_segment_policy.py` |
| pipeline 顺序：capability、compaction generation、provider-visible ledger、physical plan | `backend/runtime/context_management/context_pipeline.py` |
| 物理 lane 常量、lane 映射、cache-spine lane | `backend/runtime/context_management/physical_context_plan.py` |
| provider-visible replay metadata 和 ledger entry index | `backend/runtime/context_management/provider_visible_context_ledger.py` |
| prompt slot source/layer/dynamic-tier 投影 | `backend/prompt_composition/slot_policy.py` |
| provider payload included/excluded 决策和 cache boundary | `backend/runtime/model_gateway/provider_payload.py` |
