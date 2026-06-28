# Provider Payload Physical Cache Spine Authority Refactor Plan

## 1. 目的

本方案用于把 provider prompt cache 的前缀判断从旧的 messages-only 视角，重构为以真实 provider payload 为权威的 physical cache spine。

2026-06-28 补充优化：主运行代码中已继续清理 provider-payload 三段旧 prefix 字段、`stable_transport_contract_hash` 重复别名、`physical_cache_spine_message_hash` 重复别名、`provider_payload_message/tool_prefix_*` 旧诊断名。当前主动代码只保留 `provider_payload_prefix_hash`、`physical_cache_spine_message_subtotal_hash`、`physical_cache_spine_*` roles/locations/counts/tokens 作为 provider cache 链路字段。

这次不是新增 `v2`，也不是在旧结构旁边再接一套新结构。目标是直接切换权威、清理旧字段、删除旧 fallback，让系统只认一个 provider cache 边界：

```text
provider_payload_manifest.cache_boundary.physical_cache_spine
```

正确的系统属性是：

```text
真实 provider 请求中可复用的 token-bearing 物理前缀
== provider_payload_manifest.physical_cache_spine
== cache planner / ledger / break detector 唯一使用的 provider cache 前缀
```

## 2. 当前断点

### 2.1 具体症状

- `native_tool_binding_schema` 已经真实进入 provider HTTP body 的 `tools` 区域，但当前 `physical_cache_spine` 只扫描 `messages`。
- `ProviderPayloadSegment` 没有显式 `role`，导致系统无法把 provider message role、tool schema role、transport contract role 纳入同一个可审计物理段身份。
- `_physical_prefix_hash()` 丢弃 `transport_contract_hash`，只哈希 `"provider_visible_context_message_prefix_v1"` 和 message prefix hash。
- `cache_planner` 仍把稳定 tool schema 当成 `provider_transport_sidecar` fixed miss，污染命中率诊断。
- `provider_payload_boundary.py` 在 fallback 路径里把 `tool_segment_count` 固定为 `0`。
- `cache_boundary` 同时暴露 `physical_cache_spine`、`cache_spine_*`、`legacy_stable_*`、`legacy_prefix_tier_diagnostics`，旧权威没有被断开。

### 2.2 更深层原因

当前系统把三件事混在一起：

```text
semantic message prefix
provider physical token prefix
transport/request family contract
```

其中 provider cache 命中只应该由真实 provider payload 决定。message label 可以作为上下文管理诊断，不能继续作为 provider cache 的主权威。

## 3. Source Basis

### 3.1 本项目证据

- `backend/runtime/model_gateway/provider_payload.py`
  - `ProviderPayloadSegment` 当前没有 `role` 字段。
  - `_provider_visible_structural_prefix_segments()` 只接受 `transport_location == "messages"`。
  - `_is_current_turn_tool_binding_sidecar()` 对 `native_tool_binding_schema` 一刀切返回 sidecar。
  - `_physical_prefix_hash()` 删除 `transport_contract_hash`，保留旧 messages-only hash seed。
  - `_cache_boundary()` 输出 `legacy_stable_*` 和 `legacy_prefix_tier_diagnostics`。
- `backend/runtime/model_gateway/model_request.py`
  - `ModelRequestSegmentBinding.model_message_role` 已存在，说明上游已经有 role，可直接接入 provider payload segment。
- `backend/runtime/prompt_accounting/serializer.py`
  - tool schema 是否进入 prefix 仍由 serializer 自己结合 `message_transport_prefix_open` 判断，重复了 provider payload manifest 的决策权。
- `backend/runtime/prompt_accounting/cache_planner.py`
  - selected prefix boundaries 跳过非 `messages` 段。
  - `stable_transport_contract_predicted_tokens = sidecar_tool_schema_tokens`，把稳定工具 schema 固定归为 miss。
- `backend/runtime/prompt_accounting/provider_payload_boundary.py`
  - 如果没有嵌套 spine，会从旧 top-level 字段拼 fallback，且 `tool_segment_count = 0`。

### 3.2 成熟 agent 参考

- Codex 源码 `D:\AI应用\openai-codex\codex-rs\core\src\client_common.rs`
  - `Prompt` 是结构化请求：`input + tools + base_instructions + output_schema`，不是 raw text prefix。
- Codex 源码 `D:\AI应用\openai-codex\codex-rs\protocol\src\models.rs`
  - `ResponseItem::Message` 显式携带 `role`。
- Codex 源码 `D:\AI应用\openai-codex\codex-rs\core\src\client.rs`
  - request body 明确包含 `instructions / input / tools / tool_choice / reasoning / prompt_cache_key`。
  - incremental reuse 只在非 input 请求字段不变，且 input 严格延展时成立。
- Claude Code 源码 `D:\AI应用\claude-code-nb-main\services\api\claude.ts`
  - message param 显式 `role`，cache marker 放在真实 provider message/content block 上。
  - 每次请求只放一个 message-level cache marker，避免多权威断点。
- Claude Code 源码 `D:\AI应用\claude-code-nb-main\utils\toolSchemaCache.ts`
  - tool schema 是 provider 前置 token block，session 内稳定化，避免工具 schema 改动击穿整条下游缓存。
- Claude Code 源码 `D:\AI应用\claude-code-nb-main\services\api\promptCacheBreakDetection.ts`
  - break detection 同时哈希 system、tools、cache_control 和 extra body params。

结论：成熟实现不会把 provider prefix 当作脱离 provider payload 的 raw 文本，也不会让 system/messages/tools 各自拥有独立缓存权威。

## 4. 目标原则

1. Provider cache 前缀只由真实 provider payload 决定。
2. `tools`、`messages` 中会进入 provider prompt token 的稳定前缀，必须在同一条 physical spine 中建模。
3. `role` 是 physical segment identity 的必备字段，不能只存在于 message payload 内部。
4. `transport_contract_hash` 不能被 physical prefix hash 忽略。
5. 通过 stable tool catalog 校验的 `native_tool_binding_schema` 是 provider physical prefix segment，不是 fixed miss sidecar。
6. 未通过 stable tool catalog 校验的工具 schema 是前缀 blocker：它位于 messages 之前时，后续 messages 不能被越过去声明为可复用 provider prefix。
7. `message_prefix_hash` 只能作为 subtotal diagnostic；不能作为 provider cache authority。
8. 不建 `physical_cache_spine_v2`、不双读旧结构、不保留 messages-only fallback。

## 5. 目标权威链路

```text
ModelRequestBuilder
-> build_provider_payload_plan
-> build_provider_payload_manifest
-> ProviderPayloadManifest.segments
-> ProviderPayloadManifest.cache_boundary.physical_cache_spine
-> prompt_accounting.cache_planner
-> provider_cache_ledger / cache_break_detector
-> model_runtime provider usage reconciliation
```

权威分层：

| 层 | 目标职责 | 禁止职责 |
| --- | --- | --- |
| `model_request.py` | 规范化 provider messages/tools，绑定上游 role 和 metadata | 不判断 provider cache 边界 |
| `provider_payload.py` | 生成唯一 provider physical payload manifest 和 cache spine | 不保留 messages-only spine 权威 |
| `serializer.py` | 为账本计 token，复用 manifest 判定 | 不重新判断 tools 是 prefix 还是 sidecar |
| `provider_payload_boundary.py` | 只读取 manifest 中的 physical spine | 不从旧 top-level 字段拼 fallback |
| `cache_planner.py` | 用 physical spine 做预算、命中目标和 expected miss 分类 | 不把已验证 tools 固定算 miss |
| `cache_break_detector.py` | 用 physical spine hash / segment ids / transport family 判断 break | 不用旧 message hash 盖过 physical spine |
| `model_runtime.py` | 对齐 provider usage 和本地 cache record | 不重建 prefix 语义 |

## 6. 目标数据结构

### 6.1 ProviderPayloadSegment

直接修改现有 `ProviderPayloadSegment`，不新建 `ProviderPayloadSegmentV2`：

```text
ProviderPayloadSegment:
  segment_id
  kind
  transport_location
  role
  ordinal
  source_ref
  content_hash
  byte_length
  cache_scope
  cache_role
  prefix_tier
  compression_role
  metadata
  authority
```

`role` 规则：

| transport_location | role |
| --- | --- |
| `messages` | provider message 的真实 `role`: `system/user/assistant/tool` |
| `tools` | `tool_schema` |
| `tool_call_options` | `transport_contract` |
| `response_format` | `transport_contract` |
| `request_params` | `transport_contract` |

### 6.2 Physical Cache Spine

`physical_cache_spine.segments[]` 必须包含：

```text
segment_id
kind
transport_location
role
ordinal
source_ref
content_hash
byte_length
physical_prefix_lane
cache_scope
cache_role
prefix_tier
cache_marker_profile
provider_visible_boundary
```

physical spine hash 的 seed 直接替换旧 `_physical_prefix_hash()`：

```text
{
  "cache_spine": "provider_payload_physical_cache_spine",
  "provider": provider,
  "model": model,
  "transport_contract_hash": transport_contract_hash,
  "segments": [
    {
      "transport_location": "...",
      "role": "...",
      "kind": "...",
      "content_hash": "...",
      "cache_role": "...",
      "prefix_tier": "...",
      "physical_prefix_lane": "..."
    }
  ]
}
```

注意：这里不是 `v2`。这是直接替换旧 seed 名称和旧 hash 语义。

### 6.3 Transport Contract

`transport_contract` 继续表示影响 provider cache family 的非 token-bearing request contract，例如：

```text
provider
model
tool_call_options
response_format
provider_params
reasoning / thinking mode
cache marker profile
```

已验证的 `native_tool_binding_schema` 不属于 `transport_contract_component`；它是 token-bearing `tools` physical prefix segment。

### 6.4 Prefix Structural Correspondence Model

前缀不是一个 hash，也不是一个“稳定/不稳定”标签。前缀必须是可审计的结构对应关系：

```text
semantic source
-> logical prompt segment
-> provider physical segment
-> prefix lane
-> cache boundary identity
-> accounting / ledger / break consumer
```

任何进入 provider cache 判断的 prefix 都必须由同一个 `ProviderPayloadSegment` 承载结构身份。不要新增并行的 binding 数组；segment 本身就是语义源到 provider 物理位置的对应单元。

```text
ProviderPayloadSegment structural identity:
  segment_id
  kind
  transport_location
  role
  content_hash
  byte_length
  prefix_family
  semantic_source
  logical_segment_ref
  semantic_slot
  physical_prefix_lane
  cache_scope
  cache_role
  prefix_tier
  boundary_participation
  exclusion_reason
  consumer_contracts
  forbidden_authorities
  authority
```

字段含义：

| 字段 | 含义 | 权威来源 |
| --- | --- | --- |
| `prefix_family` | 这条前缀属于哪个标准族 | `provider_payload.py` / context policy |
| `semantic_source` | 原始语义来源，例如 tool catalog、project instruction、provider-visible replay | `context_segment_registry.py` / prompt manifest |
| `logical_segment_ref` | prompt 层 segment 身份 | segment plan |
| `kind` | prompt/context segment kind 或 provider structural kind | context segment registry / provider payload builder |
| `semantic_slot` | 该段在 agent 语义空间中的槽位 | context segment policy |
| `segment_id` | 进入 provider payload 后的物理段 ID | `ProviderPayloadManifest.segments[]` |
| `transport_location` | `tools/messages/tool_call_options/response_format/request_params` | provider request builder |
| `role` | provider-visible role 或结构角色 | provider payload segment |
| `physical_prefix_lane` | 物理前缀 lane | physical context plan / tool schema validator |
| `content_hash` | 物理段内容 hash | provider payload manifest |
| `byte_length` | provider payload 物理段字节长度 | provider payload manifest |
| `cache_scope/cache_role/prefix_tier` | prompt/cache 策略结果 | context segment policy 或 tool schema validation |
| `boundary_participation` | `included/blocker/non_token_family_selector/excluded` | physical spine scanner |
| `exclusion_reason` | 未进入 physical spine 的原因 | physical spine scanner |
| `consumer_contracts` | 谁消费这条前缀身份 | serializer/cache planner/baseline/ledger/break detector |
| `forbidden_authorities` | 哪些层不能重新解释这条前缀 | serializer、stability report、frontend |
| `authority` | 结构身份由谁签发 | `runtime.model_gateway.provider_payload.segment` |

标准 prefix family：

| prefix family | 结构对应 | provider 物理位置 | role | lane | cache 边界行为 |
| --- | --- | --- | --- | --- | --- |
| `provider_physical_tool_schema_prefix` | stable tool catalog -> native tool schema | `tools` | `tool_schema` | `provider_tool_schema_prefix` | included |
| `provider_tool_schema_blocker` | unvalidated native tool schema | `tools` | `tool_schema` | `provider_tool_schema_blocker` | blocker |
| `provider_global_static_prefix` | global/static system context | `messages` | provider message role | `global_static_prefix` | included |
| `provider_visible_context_prefix` | sealed provider-visible replay / append-only committed context | `messages` | provider message role | `provider_visible_context_prefix` | included |
| `transport_contract_family_selector` | tool choice、response format、provider params、reasoning mode | request family fields | `transport_contract` | none | non-token family selector |
| `dynamic_tail` | 当前用户输入、工具观察、控制尾巴、未封存上下文 | `messages` | provider message role | none | excluded; stops message prefix scan |

硬规则：

1. `physical_cache_spine` 只能由 `ProviderPayloadSegment.boundary_participation == included` 的 token-bearing 物理段投影而来。
2. `provider_tool_schema_blocker` 出现在 `tools` 位置时，必须阻断后续 messages prefix；不能越过它继续声明 provider cache prefix。
3. `transport_contract_family_selector` 不进入 token subtotal，但必须进入 `transport_contract_hash`，并参与 physical spine cache key。
4. `dynamic_tail` 不能进入 provider-visible ledger commit，也不能被 cache planner 解释成 warm prefix。
5. `serializer` 只按 segment identity 计 token，不允许重新裁决 prefix family。
6. `cache_break_detector` 只比较标准结构身份：`physical_cache_spine_hash`、`segment_ids`、`transport_locations`、`roles`、`transport_contract_hash`。
7. `stability_report` 可以展示 prompt 层稳定性，但不能把 prompt stable prefix 当 provider cache authority。

目标实现形态：

```text
ProviderPayloadManifest
  segments[]  # sole structural identity source
  cache_boundary.physical_cache_spine
```

其中 `physical_cache_spine.segments[]` 是 `segments[]` 中 `included` 段的 provider-cache 投影。完整审计面仍然是 `ProviderPayloadManifest.segments[]`，不能再维护一份并行 identity 表。

## 7. 固定执行流

```text
1. normalize provider messages/tools
2. bind message role into ModelRequestSegmentBinding
3. build ordered ProviderPayloadSegment list in real provider order
4. validate tools against stable tool catalog
5. build transport contract from non-token-bearing family selectors
6. scan token-bearing physical prefix in provider order
7. stop at first blocker
8. write physical_cache_spine as the only cache boundary
9. serializer counts tokens against manifest segment identity
10. cache planner creates cache record from physical_cache_spine
11. provider usage reconciles against physical_cache_spine expected read
12. break detector compares physical_cache_spine hash and segment ids
```

扫描规则：

```text
for segment in provider physical order:
    if segment is non-token-bearing transport contract:
        continue
    if segment is validated tools prefix:
        append to physical_cache_spine
        continue
    if segment is unvalidated tools:
        stop; record blocker
        break
    if segment is message lane global_static_prefix/provider_visible_context_prefix:
        append to physical_cache_spine
        continue
    stop
```

## 8. 旧结构清理清单

以下内容没有保留资格，执行时直接删除或改写调用方：

| 旧结构 | 处理 |
| --- | --- |
| `provider_visible_context_message_prefix_v1` hash seed | 删除，替换为 `provider_payload_physical_cache_spine` |
| `_physical_prefix_hash()` 忽略 `transport_contract_hash` | 改写为 physical spine hash，必须纳入 transport contract |
| `legacy_stable_segment_count` | 删除 |
| `legacy_stable_segment_hash` | 删除 |
| `legacy_stable_message_prefix_hash` | 删除 |
| `legacy_stable_message_prefix_physical_hash` | 删除 |
| `legacy_stable_message_prefix_segment_count` | 删除 |
| `legacy_prefix_tier_diagnostics` | 删除 |
| messages-only `_cache_spine_diagnostics()` 权威 | 删除或并入 physical spine diagnostic |
| `provider_payload_boundary.py` top-level fallback rebuild | 删除 |
| `tool_segment_count = 0` fallback | 删除 |
| validated tools 的 `provider_transport_sidecar` fixed miss | 删除 |
| `native_tool_binding_schema_is_provider_sidecar_not_message_prefix_cacheable` | 删除，改为 prefix / blocker 的真实裁决 |
| `stable_transport_contract_predicted_tokens = sidecar_tool_schema_tokens` | 删除 |

允许保留但必须改名和降权：

| 诊断 | 新定位 |
| --- | --- |
| message-only subtotal hash | `physical_cache_spine_message_subtotal_hash`，只做诊断，不参与 cache key |
| message segment count | `physical_cache_spine_message_segment_count`，只做诊断 |
| tool segment count | `physical_cache_spine_tool_segment_count`，必须来自真实 spine |

## 9. 分阶段落地计划

### Phase 1: ProviderPayloadSegment 身份补齐

目标：让 provider physical segment 拥有完整身份。

文件：

- `backend/runtime/model_gateway/provider_payload.py`
- `backend/runtime/model_gateway/model_request.py`

改动：

- 给 `ProviderPayloadSegment` 增加 `role`。
- messages segment 使用 `binding.model_message_role`，兜底为 provider message `role`。
- unplanned messages 读取 message `role`。
- tools segment 设为 `role="tool_schema"`。
- request params / response format / options 设为 `role="transport_contract"`。
- manifest seed 和 segment payloads 纳入 `role`。

完成标准：

- `ProviderPayloadManifest.segments[]` 每段都有 role。
- role 不再只能从 raw provider message 内部推断。

禁止：

- 不新增 `ProviderPayloadSegmentV2`。
- 不保留无 role 的兼容读法作为新逻辑入口。

### Phase 2: 工具 schema 从 sidecar 改为 physical prefix / blocker

目标：让工具 schema 的裁决符合真实 provider 顺序。

文件：

- `backend/runtime/model_gateway/provider_payload.py`
- `backend/harness/runtime/provider_tool_schema.py`
- `backend/harness/runtime/tool_schema_identity.py`

改动：

- stable catalog 校验通过：

```text
prefix_family = provider_physical_tool_schema_prefix
boundary_participation = included
physical_prefix_lane = provider_tool_schema_prefix
cache_role = session_stable
prefix_tier = provider_global 或 session
transport_contract_component = False
transport_contract_role = provider_physical_tool_schema_prefix
```

- stable catalog 校验失败：

```text
prefix_family = provider_tool_schema_blocker
boundary_participation = blocker
physical_prefix_lane = provider_tool_schema_blocker
physical_prefix_blocker = True
native_tool_binding_reason = ...
```

- provider tool schema blocker 判断不再因为 `kind == native_tool_binding_schema` 直接返回 True，只看 segment 的 `boundary_participation/prefix_family`。

完成标准：

- validated `native_tool_binding_schema` 进入 physical spine。
- unvalidated tools 阻断后续 messages prefix。

禁止：

- 不再写 “stable schema is carried by tool_schema_catalog message” 这种掩盖真实 provider payload 的说明。

### Phase 3: 重写 physical spine 扫描和 hash

目标：唯一 cache boundary 从真实 provider physical order 生成。

文件：

- `backend/runtime/model_gateway/provider_payload.py`

改动：

- 删除 messages-only `_provider_visible_structural_prefix_segments()` 作为 provider cache 权威。
- 新建或改写为 `_physical_cache_spine_segments()`，按 provider physical order 扫描 token-bearing prefix。
- `_physical_cache_spine_prefix_diagnostics()` 输出 tools + messages 的统一段列表。
- physical spine hash seed 纳入 `provider/model/transport_contract_hash/role/transport_location/kind/content_hash/cache_role/prefix_tier/lane`。
- 删除 `_physical_prefix_hash()` 的旧语义；如果函数名保留，函数体必须是新 physical spine hash，不保留旧 seed。
- `message_prefix_hash` 改为 `physical_cache_spine_message_subtotal_hash`。

完成标准：

- `physical_cache_spine.segment_ids[0]` 在有 validated tools 时是 `native_tool_binding_schema`。
- `physical_cache_spine_tool_segment_count > 0`。
- `transport_contract_hash` 变化会导致 physical spine cache key 变化。

禁止：

- 不建 `physical_cache_spine_v2`。
- 不保留旧 messages-only hash 作为并行字段。

### Phase 4: Cache boundary 清理和调用方切换

目标：断开旧 boundary 字段，让读者只能读 physical spine。

文件：

- `backend/runtime/model_gateway/provider_payload.py`
- `backend/runtime/model_gateway/model_request.py`
- `backend/runtime/prompt_accounting/provider_payload_boundary.py`
- `backend/runtime/context_management/context_commit_record.py`
- `backend/runtime/context_management/context_pipeline.py`
- `backend/runtime/context_management/provider_visible_context_ledger.py`
- `backend/harness/runtime/compiler.py`

改动：

- `_cache_boundary()` 删除 `legacy_stable_*`、`legacy_prefix_tier_diagnostics`、旧 `cache_spine_*` 权威字段。
- top-level 只保留当前消费者需要的 summary，但 authority 必须指向嵌套 `physical_cache_spine`。
- `provider_payload_boundary.py` 删除 top-level fallback rebuild；没有嵌套 spine 就返回空，让 cache planner bypass。
- `ModelRequestPacket` 删除或降权 provider payload tier hash 字段；保留字段必须只从 physical spine summary 来。
- context commit / fork point 里不再记录旧 message-prefix authority；如仍需诊断，使用 `physical_cache_spine_hash` 和 `physical_cache_spine_message_subtotal_hash`。

完成标准：

- 代码中不再出现 `legacy_stable_*`。
- provider cache 主路径不再读取 `provider_payload_message_prefix_hash` 作为 authority。

禁止：

- 不做 “新字段优先，旧字段兜底”。

### Phase 5: Serializer 只计数，不裁决

目标：serializer 不再拥有 provider prefix 决策权。

文件：

- `backend/runtime/prompt_accounting/serializer.py`

改动：

- tool schema segment 直接复用 provider manifest 中对应 segment 的：

```text
segment_id
kind
role
transport_location
content_hash
cache_role
prefix_tier
prefix_family
boundary_participation
exclusion_reason
physical_prefix_lane
```

- 删除 `message_transport_prefix_open` 对 tools prefix 的裁决。
- `authority_class` 来自 manifest 决策：
  - prefix: `provider_physical_prefix`
  - blocker: `provider_physical_prefix_blocker`
  - non-token contract: `transport_contract`

完成标准：

- serializer 不再推翻 provider payload manifest。
- token lookup 可以用 `(transport_location, role, kind, content_hash)` 精确匹配。

禁止：

- 不通过 serializer 再造一条 prefix 线。

### Phase 6: Cache planner / ledger / break detector 对齐

目标：命中率、miss family、break reason 都以 physical spine 为准。

文件：

- `backend/runtime/prompt_accounting/cache_planner.py`
- `backend/runtime/prompt_accounting/cache_baseline.py`
- `backend/runtime/prompt_accounting/cache_break_detector.py`
- `backend/runtime/prompt_accounting/provider_cache_ledger.py`
- `backend/runtime/model_gateway/model_runtime.py`

改动：

- `_provider_payload_selected_prefix_boundaries()` 不再跳过 tools，boundary 中必须包含 `transport_location` 和 `role`。
- `physical_cache_spine_predicted_tokens = physical spine tools + messages token sum`。
- `provider_tool_schema_blocker_predicted_tokens` 只统计未进入 spine 的 blocker tools。
- 删除 `stable_transport_contract_predicted_tokens = sidecar_tool_schema_tokens`。
- expected miss family 中：
  - validated tools 不进入旧 `provider_transport_sidecar` 诊断族。
  - blocker tools 才进入 `provider_physical_prefix_blocker` 或 `unvalidated_provider_tool_schema`。
- break detector 优先比较：

```text
physical_cache_spine_hash
physical_cache_spine_segment_ids
physical_cache_spine_transport_locations
physical_cache_spine_roles
transport_contract_hash
```

完成标准：

- tools schema 改动会表现为 physical spine 改变或 blocker，而不是旧 sidecar fixed miss。
- provider under-read 和本地结构错位能分开诊断。

禁止：

- 不用旧 `message_prefix_hash` 解释 provider cache break。

### Phase 7: 提示词 / 文档 / 运行验证收口

目标：让 agent prompt 和工程文档都对齐“provider payload 是结构化物理请求”的心智模型。

文件：

- `backend/prompt_library/agent_prompts.py`
- `backend/prompt_composition/message_specs.py`
- `backend/prompt_composition/slot_policy.py`
- `backend/runtime/context_management/design_docs/README.md`
- 本文档

改动：

- 检查 prompt 中是否把 “prefix/raw text/message 前缀” 说成执行契约。
- 保留给 agent 的提示词只描述角色、职责、输入、输出和裁决标准。
- 工程控制语义放在 runtime contract，不混入 agent role prompt。
- README 指向本计划，标记旧 cache provider 文档中 messages-only 说明为废弃，不保留旧方案作为可选路径。

完成标准：

- prompt 不再诱导 agent 输出 raw markdown 来绕过 action contract。
- cache 文档只承认 physical spine 权威。

禁止：

- 不把开发说明直接塞进 agent prompt。
- 不通过 prompt 文案掩盖 runtime 权威链路问题。

### Phase 8: ProviderPayloadSegment 结构身份标准化

目标：把 prefix 从“若干散落字段”升级为 `ProviderPayloadSegment` 的标准结构身份，让每条 provider cache 前缀都能追溯到语义源、prompt segment、provider physical segment、cache boundary 和消费者，同时不引入并行数组或影子表。

文件：

- `backend/runtime/model_gateway/provider_payload.py`
- `backend/runtime/model_gateway/model_request.py`
- `backend/runtime/prompt_accounting/serializer.py`
- `backend/runtime/prompt_accounting/cache_planner.py`
- `backend/runtime/prompt_accounting/cache_break_detector.py`
- `backend/runtime/prompt_accounting/provider_cache_ledger.py`
- `backend/runtime/context_management/context_segment_registry.py`
- `backend/runtime/context_management/context_segment_policy.py`

改动：

- 不新增 `prefix_structural_bindings[]`；`ProviderPayloadManifest.segments[]` 是唯一结构身份表。
- 每个 provider segment 都必须携带或可直接归一化出以下结构身份：

```text
segment_id
kind
transport_location
role
content_hash
prefix_family
semantic_source
logical_segment_ref
semantic_slot
physical_prefix_lane
cache_scope
cache_role
prefix_tier
boundary_participation
exclusion_reason
consumer_contracts
authority
```

- `physical_cache_spine.segments[]` 从 manifest segments 中筛选 `boundary_participation=included` 生成。
- blocker tools 在同一个 tools segment 上标记 `boundary_participation=blocker`，并在 spine diagnostics 中暴露 first blocker。
- transport family selector 在同一个 transport segment 上标记 `boundary_participation=non_token_family_selector`，参与 `transport_contract_hash`，不参与 token subtotal。
- dynamic tail 在同一个 message segment 上标记或诊断为 `boundary_participation=excluded`，并明确 `exclusion_reason`。
- `serializer`、`cache_planner`、`provider_cache_ledger`、`cache_break_detector` 优先读取 segment canonical identity，不再各自从 metadata 猜 lane、role 或 prefix family。

完成标准：

- 任一 `physical_cache_spine.segment_id` 都能在 `ProviderPayloadManifest.segments[]` 中找到同 ID segment。
- 任一 `native_tool_binding_schema` 都明确是 `provider_physical_tool_schema_prefix` 或 `provider_tool_schema_blocker`，不存在第三种含糊状态。
- `cache_break_detector` 输出的 break reason 可以定位到 segment 的 `prefix_family / transport_location / role / physical_prefix_lane`。
- `provider_cache_ledger` 可以复盘本轮 provider cache 目标：哪些段进入 spine、哪些段是 blocker、哪些段只是 transport family selector。
- active runtime 中不存在用字段名猜测 prefix 族的逻辑。

禁止：

- 不用 `prefix_structural_bindings[]`、`prefix_structural_bindings_v2`、`new_prefix_model`、`compat_binding`。
- 不允许在 `segments[]` 之外维护第二份 prefix 身份表。
- 不允许 serializer 或 ledger 重新给段分配 prefix family。

## 10. 文件级 Checklist

| 文件 | 当前问题 | 动作 | 完成标准 |
| --- | --- | --- | --- |
| `backend/runtime/model_gateway/provider_payload.py` | messages-only spine、无 role、旧 hash、legacy fields | 重写为唯一 physical spine authority，并标准化 segment structural identity | no `legacy_stable_*`; spine includes role/tools; every spine segment maps to one manifest segment |
| `backend/runtime/model_gateway/model_request.py` | role 已有但未传到 provider segment | 传递 `model_message_role` | manifest segments role 完整 |
| `backend/runtime/prompt_accounting/serializer.py` | 重判 tools prefix | 改为 manifest segment-only decision | serializer 只计数，不分配 prefix family |
| `backend/runtime/prompt_accounting/provider_payload_boundary.py` | fallback 拼旧结构 | 删除 fallback | 缺 spine 即 bypass |
| `backend/runtime/prompt_accounting/cache_planner.py` | boundaries 跳过 tools，sidecar fixed miss | 以 spine segment identity 全段预算 | validated tools 不算 miss；blocker 可定位 |
| `backend/runtime/prompt_accounting/cache_baseline.py` | 本地从 PromptSegment lanes 重算 spine | 改读 provider payload spine | baseline 和 manifest 一致 |
| `backend/runtime/prompt_accounting/cache_break_detector.py` | 旧 message hash 仍参与 break | spine/contract/segment identity 优先 | reason 指向真实物理变化和 prefix family |
| `backend/runtime/prompt_accounting/provider_cache_ledger.py` | 记录 sidecar miss 旧语义 | 记录 physical spine roles/locations/segment identity | ledger 可复盘 included/blocker/family selector |
| `backend/runtime/model_gateway/model_runtime.py` | usage reconcile 依赖旧诊断字段 | 读取新 physical spine diagnostics | under-read 归因清楚 |
| `backend/runtime/context_management/context_commit_record.py` | 记录 message prefix authority | 改为 physical spine authority | fork/commit 不携带旧权威 |
| `backend/runtime/context_management/context_pipeline.py` | fork point 保留 message prefix hash | 改为 physical spine hash | continuation 不串旧线 |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | provider visible ledger 仍含旧字段名 | 改为 subtotal diagnostic | 不影响 provider cache authority |
| `backend/harness/runtime/compiler.py` | fork contract 可能携带旧 message prefix | 改为 physical spine contract | fork 继承真实 provider cache family |
| `backend/prompt_library/agent_prompts.py` | 可能有输出载体/生命周期提示词冲突 | 审查并只保留 agent 可执行角色语义 | prompt 不再诱导 raw text |

## 11. 验收标准

### 11.1 静态结构验收

```text
ProviderPayloadSegment has role
physical_cache_spine.segments[] has transport_location + role
validated native_tool_binding_schema appears in physical_cache_spine.segments
validated native_tool_binding_schema.prefix_family = provider_physical_tool_schema_prefix
validated native_tool_binding_schema.boundary_participation = included
validated native_tool_binding_schema.transport_contract_component = False
every physical_cache_spine segment has a matching ProviderPayloadManifest segment
every provider cache relevant segment has prefix_family + boundary_participation
physical_cache_spine_tool_segment_count > 0 when tools are present and validated
provider_tool_schema_blocker_predicted_tokens = 0 for validated tools
physical_cache_spine_predicted_tokens = tool prefix tokens + message prefix tokens
transport_contract_hash participates in physical_cache_spine_hash
```

### 11.2 清理验收

```text
rg "physical_cache_spine_v2|ProviderPayloadSegmentV2" backend/runtime backend/harness -g "!**/design_docs/**"
=> no matches

rg "legacy_stable_|legacy_prefix_tier_diagnostics|provider_visible_context_message_prefix_v1" backend/runtime backend/harness -g "!**/design_docs/**"
=> no active runtime matches

rg "stable_transport_contract_predicted_tokens = sidecar_tool_schema_tokens" backend/runtime backend/harness -g "!**/design_docs/**"
=> no matches
```

### 11.3 编译验收

使用项目 Python 环境编译触达文件：

```text
C:\Users\admin\.conda\envs\agent\python.exe -m py_compile ^
  backend\runtime\model_gateway\provider_payload.py ^
  backend\runtime\model_gateway\model_request.py ^
  backend\runtime\prompt_accounting\serializer.py ^
  backend\runtime\prompt_accounting\provider_payload_boundary.py ^
  backend\runtime\prompt_accounting\cache_planner.py ^
  backend\runtime\prompt_accounting\cache_baseline.py ^
  backend\runtime\prompt_accounting\cache_break_detector.py ^
  backend\runtime\prompt_accounting\provider_cache_ledger.py ^
  backend\runtime\model_gateway\model_runtime.py
```

再执行：

```text
git diff --check
```

### 11.4 真实运行验收

因为本改动触达 runtime / cache / provider usage，必须用固定端口真实启动验证：

```text
前端: http://127.0.0.1:3000
后端: http://127.0.0.1:8003
API:  http://127.0.0.1:8003/api
```

验收运行：

```text
1. 清理旧前后端进程，只保留固定端口各一个。
2. 从干净 .next 启动前端。
3. 启动后端 8003。
4. 同一 session 跑三轮真实 CLI 请求。
5. 检查 prompt_cache.jsonl、segments.jsonl、token_usage.jsonl、prompt_cache_breaks.jsonl。
```

三轮预期：

```text
第一轮允许 provider cache miss。
第二、三轮必须以 physical_cache_spine 作为唯一目标。
如果 provider cached tokens 仍偏低，诊断必须显示 provider under-read 或 provider cache behavior，而不是本地 tools sidecar fixed miss。
```

## 12. 风险和控制

| 风险 | 控制 |
| --- | --- |
| 删除旧 fallback 后某些调用方缺字段 | 同 phase 更新所有 internal consumers；缺 spine 直接 bypass，不重建旧结构 |
| 上游 prompt composition 仍只提供 message role | 使用 `ModelRequestSegmentBinding.model_message_role` 接线，unplanned message 从 provider message 读取 role |
| unvalidated tools 导致 cache 目标消失 | 这是正确行为，因为 tools 在 messages 前面；诊断必须暴露 blocker |
| context commit/fork 仍携带旧 message prefix hash | Phase 4 同步清理 fork/commit contract |
| prompt 修改误伤 agent 输出 | Phase 7 只修正冲突提示词，不把 runtime 开发说明塞给 agent |

## 13. 禁止事项

- 禁止新增 `v2`、`next`、`new_*` 并行结构。
- 禁止 “新字段优先，旧字段兜底”。
- 禁止保留 messages-only physical spine 作为 provider cache authority。
- 禁止用 raw markdown / raw text 作为绕过 action contract 的输出方案。
- 禁止把已验证 tools schema 继续归为 fixed miss。
- 禁止通过调低命中率目标制造通过。
- 禁止新增回归测试文件或用测试文件伪造通过；验证以代码审查、编译、diff check、真实固定端口运行和账本为准。

## 14. 预期结果

重构后，系统的 provider cache 解释会从：

```text
messages prefix + tools sidecar + legacy diagnostics
```

收敛为：

```text
real provider physical payload spine + transport contract family
```

这会带来三个直接收益：

1. 前缀命中率诊断不再被旧 messages-only 结构误导。
2. tools schema 的稳定性和破坏性都能被准确归因。
3. lifecycle / cache / ledger / break detector 的线接到同一个权威对象，后续维护者不需要在多个“看似合理”的 prefix 之间猜哪一个是真的。
