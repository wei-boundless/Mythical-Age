# Provider Tool Protocol Cache-Spine Governance Plan

## 1. Problem

本次故障不是网络断线，也不是工具执行失败，而是 provider payload 中出现了不合法的原生工具协议序列：

```text
tool
assistant(tool_calls)
```

DeepSeek 按 OpenAI/ChatCompletions 风格校验时，要求 `role=tool` 必须紧跟在声明了对应 `tool_calls` 的 assistant 消息之后：

```text
assistant(tool_calls: call_x)
tool(tool_call_id: call_x)
```

旧版本没有暴露这个问题，是因为旧链路多把工具观察包装为普通上下文文本，provider 看不到 native `role=tool` 消息。新链路把 provider-visible transcript 作为 append-only history 回放，进入了更成熟但更严格的 provider-native protocol 区域，因此必须把一轮工具协议建模为结构原子，而不是散落消息。

## 2. Source Findings

| 文件 | 当前职责 | 发现 |
| --- | --- | --- |
| `backend/runtime/context_management/context_segment_registry.py` | 声明上下文段种类 | `single_agent_turn_tool_call`、`tool_transcript_delta` 是 `context_append`；`provider_visible_tool_transcript_replay` 是 `context_memory_prefix`。 |
| `backend/runtime/context_management/context_segment_policy.py` | 根据段种类和 metadata 决定 section/cache policy | 当前 append 工具轮 provider 成功前为 current append，成功后进 session prefix。 |
| `backend/runtime/context_management/physical_context_plan.py` | 把上下文段分到 physical lane | cache spine lane 只有 `global_static_prefix` 和 `provider_visible_context_prefix`；tail 之后不能再出现 prefix。 |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | provider-visible 历史封存与回放 | 旧逻辑按 entry index 顺序回放，遇到历史错序时只能靠相邻启发式修复。 |
| `backend/runtime/model_gateway/provider_payload.py` | 唯一 provider physical payload manifest/cache spine 权威 | physical cache spine 已成为 cache boundary，但没有显式展示工具协议轮结构。 |
| `backend/runtime/prompt_accounting/cache_planner.py` | 从 physical cache spine 生成 cache record | 已不应从 messages-only prefix 判断缓存；需要能诊断工具协议轮变化。 |
| `backend/runtime/model_gateway/protocol_sanitizer.py` | provider 边界结构验收 | 只能做最后协议验收，不应承担主要装配权威。 |

## 3. Principles

1. 系统只验收结构契约，不判断 agent 语义。
2. Agent 负责说明、收口和用户可见解释；系统不替 agent 编造失败说明。
3. 公开反馈是 agent 的语义义务，不是 provider/parser/admission 的硬阻断条件；缺失只能形成 `contract_gaps` 或下一轮反馈义务。
4. Provider-native tool round 是协议原子：

```text
assistant(tool_calls[])
tool(tool_call_id)
...
```

5. Cache authority 只有一个：`ProviderPayloadManifest.cache_boundary.physical_cache_spine`。
6. 工具协议轮不能创建 `v2`，不能并行保留旧 messages-only 权威。
7. Current append 在 provider 成功前不算 cache-readable；provider 成功后才进入 session prefix replay。
8. Gateway sanitizer 是最后防线，不是主装配层。
9. 上下文位置是固定插线位：`context_cache_section + semantic_slot + physical_prefix_lane` 决定上下文进入哪条线；工具协议 metadata 只描述同一条 provider-visible 线里的原子回合，不拥有上下文插线权。
10. 工具调用没有任意单 turn 次数预算；只由权限、审批、沙盒、provider transport、重复失败和资源缺失这些边缘保护终止或要求 agent 收口。

## 4. Target Structure

```text
single_agent_turn tool execution
-> provider tool protocol group annotation
-> provider-visible append candidate
-> provider success ledger commit
-> ledger replay as closed provider-native tool round
-> physical_context_plan provider_visible_context_prefix order
-> provider_payload_manifest.physical_cache_spine
-> prompt cache planner / break detector
-> gateway structural sanitizer
```

### 4.1 Provider Tool Protocol Group

每个闭合工具轮写入统一 metadata：

```json
{
  "provider_tool_protocol": {
    "unit": "provider_native_tool_round",
    "round_id": "ptround:...",
    "round_member_role": "assistant|tool",
    "round_order": 0,
    "tool_call_ids": ["call_x"],
    "tool_call_id": "call_x",
    "complete": true,
    "authority": "runtime.context_management.provider_tool_protocol"
  }
}
```

这里的 `round_member_role` 不是上下文位置。真正的插线位置仍由外层 spec metadata 表达：

```text
context_cache_section = context_append | context_memory_prefix | static_prefix | dynamic_tail
context_semantic_slot = tool_transcript | provider_protocol_history | ...
physical_prefix_lane = current_turn_tail | provider_visible_context_prefix | ...
```

工具轮在本轮成功前属于 `context_append -> current_turn_tail`；provider 成功确认后，下一轮从 ledger replay 为 `context_memory_prefix -> provider_visible_context_prefix`。这条生命周期不能被 provider tool protocol metadata 改写。

### 4.2 Cache Spine Projection

`physical_cache_spine` 继续只由真实 provider payload segment 生成；新增的工具轮结构只作为 segment metadata/diagnostic 投影：

```text
physical_cache_spine.segments[].provider_tool_protocol
physical_cache_spine.provider_tool_protocol_rounds[]
physical_cache_spine.provider_tool_protocol_round_count
```

这些字段用于结构诊断和 break reason，不替代 provider payload bytes。

## 5. Implemented Slice

本轮已落地第一批治理：

| Slice | 文件 | 结果 |
| --- | --- | --- |
| Tool round standard model | `provider_tool_protocol.py` | 新增 provider-native 工具轮结构标记、round id、closed group 识别、物理排序 key。 |
| Follow-up and protocol history assembly | `single_agent_turn.py`, `compiler.py` | follow-up spec 与 compiler provider protocol history 都标记同一个工具轮模型，再生成 ledger commit candidate。 |
| Ledger commit/replay | `context_candidates.py`, `provider_visible_context_ledger.py` | commit candidate 保存 `provider_tool_protocol`；ledger replay 优先按 round id 回放闭合工具轮。 |
| Physical order/hash | `physical_context_plan.py` | provider prefix 内工具轮按 round order 排序；本地 content hash 纳入 `tool_calls/tool_call_id`。 |
| Cache diagnostics | `provider_payload.py`, `provider_payload_boundary.py`, `cache_planner.py`, `cache_break_detector.py` | cache spine 暴露工具轮诊断；break detector 同时定位 prefix family 与工具协议轮变化。 |

## 6. Remaining Governance Phases

1. 把 `single_agent_turn.py` 中的 follow-up provider message/spec 编排拆出独立 assembler，减少主 loop 决策和装配混杂。
2. 把 `protocol_sanitizer.py` 的相邻错序修复降级为报警型最后防线；主路径应由 ledger/physical plan 保证顺序。
3. 清理历史测试中保护旧 messages-only cache 或旧工具工具页注册的残留；不新增回归测试文件。
4. 继续收敛 `compiler.py` 的 provider protocol hot message 筛选逻辑：当前已复用同一个 provider tool protocol metadata，后续应把闭合工具轮筛选也抽到 `provider_tool_protocol.py`，避免第二套识别算法长期存在。
5. 在真实运行日志中核对：
   - `provider_tool_round_grouping.annotated_provider_tool_round_count > 0`
   - `physical_cache_spine_tool_protocol_round_count > 0`
   - 无 `Messages with role 'tool' must be a response...`
   - provider cache break reason 可指向 physical spine 或 tool protocol round。

## 7. Validation

允许的验证方式：

```text
python -m py_compile <changed runtime files>
fixed-port backend/frontend health check
real chat/tool run
runtime event / prompt accounting log inspection
```

禁止的验证方式：

```text
新增弱语义测试文件
跳过失败断言
mock provider payload 让测试“看起来通过”
保留旧 messages-only fallback
```
