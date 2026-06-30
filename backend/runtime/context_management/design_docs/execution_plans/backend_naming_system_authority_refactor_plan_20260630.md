# Backend Naming System Authority Refactor Plan

创建日期：2026-06-30

状态：已确认，Phase 1 已实施（2026-06-30）；Phase 2 已完成 provider-visible append ledger storage/API 迁移；Phase 3 已完成第二条窄切片；Phase 4 已完成第四条窄切片；Phase 5 已执行 active docs/runtime_state/tests-support 清理。

本文不是风格统一清单，而是后端命名权威体系审查和重构计划。目标是让名称准确表达对象的真实职责、权威层级、可见范围、生命周期和迁移边界，避免 `api_transcript` 这类名字把 provider 协议事实源误导成 API 日志。

## 1. 问题定义

当前后端的真实运行链路已经比较成熟，但命名体系存在结构性漂移：

1. 同一词表达多个层级，例如 `history` 同时表示 public UI 消息、provider-native 协议消息、semantic history tail、physical replay。
2. 不同词表达同一类生命周期，例如 `transcript`、`timeline`、`history`、`ledger`、`record` 在部分位置没有清晰区分。
3. `payload`、`packet`、`envelope`、`manifest`、`contract` 的边界不总是自说明。
4. `context_system`、`runtime/context_management`、`harness/runtime/dynamic_context` 都叫 context，但分别处于语义解析、物理拼接和当前动态投影层。
5. 某些历史名保留了旧语义，比如 `api_transcript`、`load_session_for_api`、`append_api_messages`，但实际已经成为 provider protocol timeline。

正确终态不是把所有文件机械改成新词，而是建立一套可执行的命名语法：

```text
owner/domain + semantic object + lifecycle stage + visibility/transport role
```

一个名字必须能回答：

- 它是谁的事实源？
- 它是候选、当前尾部、已确认、封存 replay，还是诊断？
- 它给 agent 看、给 provider 传输、给 UI 展示，还是仅供审计？
- 它是否可缓存、可重放、可提交、可恢复？

## 2. Source Basis

### 2.1 本次代码审查依据

| 文件 | 观察到的命名事实 |
| --- | --- |
| `backend/sessions/__init__.py` | `api_transcript` 实际保存 provider protocol timeline；`messages` 是 public/session UI 消息；fork/compaction/token 都读取 `api_transcript` |
| `backend/harness/entrypoint/runtime_facade.py` | 把 `api_transcript` 注入 `session_context`，并将 `api_protocol_messages` 追加回 session |
| `backend/harness/runtime/compiler.py` | 从 `api_transcript` 投影出 `provider_protocol_history` append candidates |
| `backend/runtime/context_management/context_segment_registry.py` | 四段 context section 已存在，但 `session_history`、`session_history_context` 等命名仍有重复 |
| `backend/runtime/context_management/context_pipeline.py` | 实际权威链是 capability filter -> provider visible append ledger -> physical context plan |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | 该 ledger 记录 append candidates 和确认状态，不拥有 confirmed replay 注入权 |
| `backend/runtime/context_management/physical_context_assembler.py` | 物理拼接规则已明确：static prefix -> confirmed physical frame -> current append -> dynamic tail |
| `backend/runtime/context_management/physical_prefix_frame_ledger.py` | 物理 prefix frame 是 provider success 后的 confirmed replay 权威 |
| `backend/runtime/model_gateway/provider_request.py` | `ProviderRequestPacket` 是 provider transport request packet，不是 runtime invocation packet |
| `backend/runtime/model_gateway/provider_payload.py` | `ProviderPayloadManifest` 是 provider transport/cache/hash 清单 |
| `backend/harness/runtime/invocation_packet.py` | `RuntimeInvocationPacket` 是 agent/runtime 输入包 |
| `backend/harness/runtime/envelope.py` | `RuntimeEnvelope` 是 scope/policy 外壳 |
| `backend/harness/loop/model_action_protocol.py` | `ModelActionRequest` 是模型裁决输出合同 |
| `backend/harness/loop/action_permit.py` | `ActionPermit` 是授权结果，不是模型裁决 |
| `backend/context_system/*` | 包含 turn context resolver、context package、sealed receipt，与物理 context pipeline 层级不同 |

### 2.2 已有本地原则

从当前主索引和上下文设计中抽取的可执行原则：

- `harness` 是 agent 语义中枢和运行调度中枢。
- `runtime/context_management` 是物理上下文、provider-visible append、prefix/cache/ledger 层，不做 agent 意图裁决。
- `runtime/model_gateway` 是 provider transport、payload、cache hash 和 provider 兼容层。
- `capability_system` 是能力事实源；当前回合可用性由 harness runtime tool plan/admission/permit 决定。
- `ProviderMessageReplayContract` 是 byte-preserve replay 判断唯一权威。
- 普通 turn 恢复不应有第二权威，当前以 TurnMemory recovery 为主。
- 名称不得通过字符串形状伪装权威；来源标签不能代替 origin authority、contract 或 lifecycle state。

## 3. Naming Doctrine

### 3.1 词根规则

| 词 | 允许含义 | 禁止含义 |
| --- | --- | --- |
| `timeline` | 按时间追加的原始事实源，通常是 session/run scope | 不表示编译后的 prompt 段 |
| `history` | 已选择给某个消费者重放的历史视图 | 不表示原始事实源 |
| `transcript` | 人类可读的转录文本，或工具转录内容 | 不表示 provider-native protocol stream |
| `ledger` | 追加式账本，记录候选/确认/状态变化 | 不表示当前请求输入包 |
| `frame` | 已确认的物理切片或快照，可作为 replay 单元 | 不表示普通上下文候选 |
| `record` | 单条审计/提交/事件记录 | 不表示可直接重放的消息序列 |
| `snapshot` | 某时刻状态副本 | 不表示持续活跃状态 |
| `candidate` | 可被后续阶段选择或确认的候选 | 不表示已确认事实 |
| `append` | 当前请求新增、等待 provider success 后确认 | 不表示已封存 replay |
| `replay` | 已确认后重新注入 provider-visible 输入 | 不表示当前未确认新增 |
| `packet` | 单次运行/模型请求输入包 | 不表示持久账本 |
| `payload` | 传输体或序列化消息体 | 不表示长期语义合同 |
| `envelope` | scope/policy/route 外壳 | 不表示正文内容 |
| `manifest` | 清单、目录、hash/index 说明 | 不表示执行动作本身 |
| `contract` | 可验证约束/职责/边界 | 不表示自然语言说明 |
| `projection` | 从源事实投影给特定消费者的视图 | 不拥有源事实 |

### 3.2 可见性后缀

| 后缀 | 含义 |
| --- | --- |
| `public_*` | UI/user-visible |
| `agent_visible_*` | 模型/agent 可见 |
| `provider_protocol_*` | provider-native chat protocol，包括 tool_calls/reasoning/tool result |
| `provider_transport_*` | 发给 provider 的最终 transport 形态 |
| `runtime_private_*` | runtime 内部，不进入 agent/provider/public |
| `diagnostic_*` | 只用于审计/排查，不参与决策 |

### 3.3 生命周期后缀

| 后缀 | 含义 |
| --- | --- |
| `*_candidate` | 等待选择/确认 |
| `*_current_append` | 当前请求新增，provider success 后可确认 |
| `*_confirmed` | provider/runtime 已确认 |
| `*_replay` | confirmed 后重新注入 |
| `*_tail` | 当前轮可变尾部 |
| `*_prefix` | 稳定前缀 |
| `*_lease` | 有开始/释放生命周期的活跃绑定 |
| `*_receipt` | 不可变回执 |

## 4. Canonical Backend Naming Map

### 4.1 Session message/time spine

| 当前名 | 问题 | 推荐名 | 迁移优先级 |
| --- | --- | --- | --- |
| `messages` | 太泛，但已经是 public session contract | 保留存储字段；内部命名用 `public_message_timeline` | P2 |
| `api_transcript` | 实际不是 API 日志，而是 provider protocol timeline | `provider_protocol_timeline` | P0 |
| `load_session_for_api()` | API 暗示错误消费者 | `load_provider_protocol_timeline()` | P0 |
| `append_api_messages()` | 实际追加 provider protocol messages | `append_provider_protocol_messages()` | P0 |
| `_api_message()` | 实际规范化 provider protocol message | `_provider_protocol_message()` | P0 |
| `_truncated_api_transcript()` | 实际按 public kept turns 裁剪 provider timeline | `_truncate_provider_protocol_timeline()` | P0 |
| `api_protocol_messages` | 是本轮待追加 provider protocol delta | `provider_protocol_message_delta` 或 `provider_protocol_messages_to_append` | P0 |
| `fork_point_api_transcript_count` | fork 断点其实是 provider protocol 消息数 | `fork_point_provider_protocol_message_count` | P0 |

目标分层：

```text
public_message_timeline
-> provider_protocol_timeline
-> provider_protocol_history append candidates
-> physical_prefix_frame replay
-> provider_transport_messages
```

### 4.2 Context namespaces

| 当前名 | 实际层级 | 推荐处理 |
| --- | --- | --- |
| `backend/context_system` | turn context resolution/package/receipt 层 | 后续收口为 `turn_context_system` 或并入 `harness/runtime/turn_context`，避免和物理 context pipeline 混淆 |
| `backend/runtime/context_management` | 物理 context/cache/provider-visible append/replay 层 | 保留；不要让它承担 agent semantic decision |
| `backend/harness/runtime/dynamic_context` | 当前请求动态投影层 | 保留，但对象名补充 `current_*` / `runtime_delta_*` / `task_state_replay_*` |
| `ContextPackage` | 可见 context package，偏语义包 | 若保留在 `context_system`，更名为 `TurnContextPackage` |
| `SealedContextLedgerEntry` | context 选择回执项，不是 provider ledger | `ContextSelectionReceiptEntry` 或 `SealedContextSelectionEntry` |
| `SealedContextReceipt` | 选择回执 | `ContextSelectionReceipt` |

### 4.3 Provider-visible append and physical replay

| 当前名 | 判断 | 推荐处理 |
| --- | --- | --- |
| `provider_visible_context_ledger` | 可接受，但略宽 | 中期更准确为 `provider_visible_append_ledger` |
| `provider_visible_context_append_candidate_spec` | 准确但长 | 保留或改为 `provider_visible_append_candidate_spec` |
| `provider_visible_context_ledger_commit_stage` | 准确但可短化 | `provider_visible_append_commit_stage` |
| `physical_prefix_frame_ledger` | 准确 | 保留 |
| `physical_prefix_frame_*_replay` | 准确 | 保留 |
| `provider_protocol_history` | 编译出的 provider history segment，不是原始源 | 保留，前提是原始源改为 `provider_protocol_timeline` |

### 4.4 Packet / payload / envelope / manifest

| 当前名 | 判断 | 推荐边界 |
| --- | --- | --- |
| `RuntimeEnvelope` | scope/policy 外壳，准确 | 保留 |
| `RuntimePacketContext` | packet context 组装中间态，准确 | 保留 |
| `RuntimeInvocationPacket` | agent/runtime 输入包，准确 | 保留 |
| `ProviderRequestPacket` | provider transport request packet | 已收口；禁止再用 `ModelRequestPacket` 表示 provider transport request |
| `ProviderPayloadManifest` | provider payload/cache/hash 清单，准确 | 保留 |
| `payload` 变量 | 局部序列化体可以用 | 跨层对象禁止只叫 payload，必须带领域前缀，如 `provider_payload`, `commit_payload`, `session_payload` |

### 4.5 Decision / authorization / execution

| 当前名 | 判断 | 推荐处理 |
| --- | --- | --- |
| `ModelActionRequest` | 模型输出的 action contract，不是真正 request from user | 可接受；文档中称 `model action decision/request` |
| `AdmissionDecision` | 准入裁决 | 保留 |
| `ActionPermit` | 授权令牌 | 保留 |
| `RuntimeToolControlPlane` | 工具执行控制面 | 保留 |
| `active_work_context` | active work 状态/边界较宽 | 后续拆成 `active_work_snapshot`、`active_work_control_surface`、`active_execution_lease` |
| `current_work_boundary_receipt` | 当前工作边界回执 | 保留 |

## 5. File-Level Impact Checklist

### P0: Provider protocol timeline rename

| 文件 | 动作 |
| --- | --- |
| `backend/sessions/__init__.py` | `api_transcript` 存储字段和方法改为 `provider_protocol_timeline`；写 one-shot storage migration；不保留长期双写 |
| `backend/harness/entrypoint/runtime_facade.py` | session_context key、load/append 方法名、去重参数改名 |
| `backend/harness/loop/single_agent_turn.py` | `api_protocol_messages` 改为 provider protocol delta 命名 |
| `backend/harness/loop/active_turn_steering.py` | 更新 append provider protocol messages 调用 |
| `backend/harness/runtime/compiler.py` | 输入 key 改为 `provider_protocol_timeline`，继续输出 `provider_protocol_history` |
| `backend/runtime/context_management/session_compaction.py` | token pressure 字段改为 provider protocol timeline count |
| `backend/runtime/context_management/context_commit_record.py` | commit record 字段改为 provider protocol timeline count/hash |
| `backend/api/tokens.py` | cumulative transcript token 命名改为 provider protocol cumulative tokens |
| `backend/tests/support/runtime_stubs.py` 和现有相关测试 | 改旧字段名；不新增测试文件 |
| `storage/sessions/*.json` | 一次性迁移 `api_transcript` -> `provider_protocol_timeline` |

### P1: Context namespace clarity

| 文件/目录 | 动作 |
| --- | --- |
| `backend/context_system/models/context_models.py` | 将 selection ledger/receipt 命名从 ledger 降级为 selection receipt，避免和 provider ledger 混淆 |
| `backend/context_system/resolution/resolver.py` | 明确为 turn context resolver；去掉 legacy goal 命名残留时需单独计划 |
| `backend/context_system/projection/projection.py` | 将 `ContextProjection` 更名为 `TurnContextProjection` 或迁入 harness runtime projection |
| `backend/runtime/context_management/context_segment_registry.py` | 合并 `session_history` / `session_history_context` 等重复 kind，保留一个 canonical kind |
| `backend/harness/runtime/dynamic_context/models.py` | `DynamicContextProjection` 字段补足 current/runtime_delta/task_state_replay 语义 |

### P1: Provider-visible append ledger tightening

| 文件 | 动作 |
| --- | --- |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | 评估是否改名为 `provider_visible_append_ledger.py`；至少内部字段从 `context_ledger` 收窄为 `append_ledger` |
| `backend/runtime/context_management/context_pipeline.py` | stage 名称从 provider_visible_context_ledger stage 精确为 provider_visible_append_stage |
| `backend/runtime/context_management/physical_context_assembler.py` | 保持 replay 权威只来自 physical prefix frame |

### P2: Provider request packet naming

| 文件 | 动作 |
| --- | --- |
| `backend/runtime/model_gateway/provider_request.py` | 已将 provider transport request 类型收口为 `ProviderRequestPacket` / `ProviderRequestBuilder` |
| `backend/runtime/model_gateway/model_runtime.py` | 更新 provider request packet 相关字段 |
| `backend/runtime/model_gateway/provider_payload.py` | 保持 `ProviderPayloadManifest`，禁止把 manifest 当 request owner |

## 6. Migration and Cutover Rules

### 6.1 Clean migration 优先

本项目原则是不长期保留旧链路。推荐采用 clean migration：

1. 停止写旧字段。
2. 一次性迁移本地 `storage/sessions/*.json`。
3. 代码只读新字段。
4. 如必须读取旧字段，只允许在迁移脚本内读取，不放入 runtime active path。
5. `rg` 确认 active Python 代码不再引用旧名。

### 6.2 可接受的短期兼容边界

只有在用户要求不中断已有未迁移 session 时，才允许短期 read fallback：

```text
read provider_protocol_timeline
if missing and api_transcript exists:
    migrate payload in-memory and persist new field
    delete old field from persisted payload
```

禁止长期双写，禁止 active path 同时把两个字段当事实源。

## 7. Phase Plan

### Phase 0: 命名体系确认

目标：确认本文命名原则和 P0/P1/P2 优先级。

完成标准：

- 用户确认 `provider_protocol_timeline` 是 `api_transcript` 的目标名。
- 用户确认 clean migration，不保留长期 alias。
- 用户确认 context/ledger/packet 的重命名按垂直切片执行，不一次性全仓机械替换。

禁止：

- 直接批量替换所有 `history` / `context` / `payload`。
- 保留旧名作为永久兼容。

### Phase 1: Provider protocol timeline vertical slice

目标：先修最危险、最确定的命名错位。

输入：

- session 存储中的 `api_transcript`
- runtime facade 的 session_context 注入
- compiler 的 provider history projection

输出：

- `provider_protocol_timeline` 成为原始 provider protocol 时间轴唯一字段。
- `provider_protocol_history` 继续作为 compiler 输出 segment。
- 相关 fork/compaction/token/commit 字段同步改名。

验证：

- `rg -n "api_transcript|load_session_for_api|append_api_messages|api_protocol_messages|api_content|api_protocol_prefix_messages"` active backend code 无残留。
- targeted `py_compile` 覆盖 touched modules。
- 用现有 session JSON 做一次真实加载/投影检查，确认普通 user/assistant/tool messages 数量不变。

### Phase 2: Context ledger terminology cleanup

目标：把 selection receipt、provider-visible append ledger、physical prefix frame ledger 三类 ledger/receipt 分清。

执行状态：已完成三条窄切片（2026-06-30）。

- `context_system` 的选择回执从 `SealedContextLedgerEntry` / `SealedContextReceipt` 收口为 `ContextSelectionReceiptEntry` / `ContextSelectionReceipt`，输出字段从 `sealed_receipt` 收口为 `selection_receipt`。
- `context_pipeline` 的 provider-visible stage 从 `provider_visible_context_ledger` diagnostics 收口为 `provider_visible_append_stage`；`physical_context_assembler` 的入参从 `provider_visible_ledger_specs` 收口为 `provider_visible_append_specs`。
- `inspection_payload` 的拓扑节点从 `ProviderVisibleLedger` 收口为 `ProviderVisibleAppendLedger`，说明其只确认 current append，不拥有下一轮 replay 顺序权威。
- `provider_visible_context_ledger.py` 文件名、磁盘目录和 `provider_visible_context_ledger_*` metadata 字段暂不在本切片迁移；它们属于 storage/API contract，需要单独迁移计划。
- 单独迁移计划已落文档并实施：`backend/runtime/context_management/design_docs/execution_plans/provider_visible_append_ledger_storage_api_migration_plan_20260630.md`。active code/storage/API 已 clean cutover 到 `provider_visible_append_ledger`，并迁移 active runtime_state，不保留 runtime fallback。

输出：

- `context_system` 内部不再把选择回执叫成 provider-style ledger。
- provider-visible ledger 文档和 metadata 明确 `append` 而非 replay owner。
- physical frame replay 继续是唯一 confirmed replay owner。

验证：

- `rg` 检查 `ledger` 使用点能归入 selection/provider-append/physical-frame 三类。

### Phase 3: Context namespace boundary

目标：区分 turn semantic context、runtime physical context、current dynamic context。

执行状态：已完成第一条窄切片（2026-06-30）。

- `context_system.models.ContextPackage` 收口为 `TurnContextPackage`，表示它是 turn semantic context policy 的可见包，不是 runtime physical context package。
- `context_system.policy.ContextCandidateDecision` / `ContextPolicyResult` / `MemoryContextPolicy` 收口为 `TurnContextCandidateDecision` / `TurnContextPolicyResult` / `TurnMemoryContextPolicy`，result authority 从 `context_policy_result` 收口为 `turn_context_policy_result`。
- `build_context_package_result()` 和 memory bundle service 的 `build_memory_context_package_result()` / `abuild_memory_context_package_result()` 收口为 `build_turn_context_package_result()` / `build_turn_memory_context_package_result()` / `abuild_turn_memory_context_package_result()`。
- `context_system.projection.ContextProjection` 收口为 `TurnContextProjection`，authority 从 `context.execution_projection` 收口为 `context_system.turn_context_projection`。
- `context_system.resolution.ContextResolver` 收口为 `TurnContextResolver`，表示它解析 current-turn truth/bindings，不是 runtime physical context assembler。
- 旧类名/函数名没有保留 alias；active Python 代码不再引用 `ContextPackage` / `ContextProjection` / `ContextResolver` / `ContextPolicyResult` / `ContextCandidateDecision` / `MemoryContextPolicy`。
- `session_history_context` 重复 kind/producer 已收口为 canonical `session_history`：producer order、producer id、segment registry、policy defaults 不再保留旧别名；payload 源仍为 `session_history`，不改变语义历史尾部的实际内容。

输出：

- `context_system` 的公开对象加 `Turn*` 语义，或迁入 harness runtime turn context。
- `runtime/context_management` 保持物理/cache/provider-visible 层。
- `dynamic_context` 的字段名不再把 current volatile state 表达成可 replay memory。

验证：

- context segment registry 中重复 kind 收口。
- `current_*`、`dynamic_tail`、`replay`、`append` 字段不互相冒充。

### Phase 4: Packet/transport vocabulary cleanup

目标：清理 runtime packet 与 provider request packet 的边界。

执行状态：已完成四条窄切片（2026-06-30）。

- `runtime.model_gateway.provider_request.ProviderRequestPacket` / `ProviderRequestBuilder` / `ProviderRequestSegmentBinding` 成为 provider transport request 的唯一类型名。
- 类型 authority 从 `runtime.model_gateway.model_request_*` 收口为 `runtime.model_gateway.provider_request_*`。
- `runtime.model_gateway.__init__` 不再导出旧 `ModelRequest*` 类型名。
- 文件从 `backend/runtime/model_gateway/model_request.py` 收口为 `backend/runtime/model_gateway/provider_request.py`；active Python import path 不再引用 `runtime.model_gateway.model_request`。
- `runtime.prompt_accounting.provider_lane` 的 physical payload family helper 从 `physical_payload_family_hash_for_model_request()` 收口为 `physical_payload_family_hash_for_provider_request()`。
- `runtime.prompt_accounting.provider_payload_boundary` 的 helper 入参从 `model_request` 收口为 `provider_request`。
- `runtime.model_gateway.model_runtime` 的 accounting 对象键从 `model_request` 收口为 `provider_request`；prompt serializer、cache planner、prefix state reporter、prefix diff reporter、context commit record 的入参同步改为 `provider_request`。
- provider request 引用类 diagnostics 从 `model_request_ref` / `model_request_*` 收口为 `provider_request_ref` / `provider_request_*`；cache plan 的 prefix match 字段从 `prefix_hash_matches_model_request` 收口为 `prefix_hash_matches_provider_request`。
- harness 生成的 provider request id 前缀从 `modelreq:*` 收口为 `providerreq:*`；reasoning projection status 事件从 `model_request_id` 收口为 `provider_request_id`，前端 chronological accumulator 同步读取新字段。
- `TaskRunContract.contract_source` 中真正表示模型行动裁决来源的值从 `model_request` 收口为 `model_action_request`。
- provider payload / prompt accounting 的新写入 source identity 从 `model_request.message` / `model_request.tools` / `model_request.unplanned_message` / `model_request.tool_call_options` / `model_request.response_format` / `model_request.cache_relevant_params` 收口为 `provider_request.*`。
- physical prefix frame 新写入的 provider message source 从 `"model_request.messages"` 收口为 `"provider_request.messages"`；校验规则和 promotion diagnostics 同步改为 provider request 表达。
- 本切片不迁移历史 storage JSON 中已写入的旧 source_ref / message source；历史 ledger 只作为既有事实保留，新 runtime active path 停止产生旧 source identity。

输出：

- runtime 输入包、provider 请求包、provider payload manifest 三者命名可一眼区分。
- 跨文件变量禁止裸 `payload` 传递关键事实。

验证：

- `ProviderRequestPacket` 所有 provider gateway 路径编译通过。
- provider payload manifest 仍能生成相同 transport/cache hash。

### Phase 5: Documentation and old-name cleanup

目标：文档、diagnostics、tests/support 同步新体系。

执行状态：已完成当前 active 切片（2026-06-30）。

- 修正 `backend/sessions/__init__.py` 的 fork snapshot 残留：`fork_point_provider_visible_ledger_anchor` 收口为 `fork_point_provider_visible_append_anchor`，并改用 `latest_provider_visible_append_success_anchor()`。
- 修正 provider request success 生命周期中的命名和断线：`provider_visible_ledger_confirmation` / `provider_visible_confirmation` 收口为 `provider_visible_append_confirmation`；`provider_visible_anchor_before/after` 收口为 `provider_visible_append_anchor_before/after`；`_finish_prompt_accounting()` 成功路径恢复先确认 append ledger 再推进 physical prefix frame。
- `context_pipeline` fork inheritance diagnostics 从 `fork_inherited_provider_visible_*` 收口为 `fork_inherited_provider_visible_append_*`。
- `storage/runtime_state` 结构化 JSON 已按 key/value 迁移：跳过 provider message content、tool call arguments、transcript、search preview 等历史原文；只迁移 active contract key、metadata 和 authority 字符串。
- `backend/runtime/context_management/README.md` 已从旧 ledger replay owner 叙述更新为 append ledger + physical prefix frame replay 的当前权威链。
- 现有 tests/support 中的 provider request id 样例前缀从 `modelreq:` 机械收口为 `providerreq:`；不新增测试文件，不降低断言。

输出：

- 新命名进入主索引文档。
- 旧字段只保留在历史文档的问题记录中。
- active code/test/support 不再保护旧内部形状。

验证：

- `rg` 检查旧名只存在于历史文档或迁移记录。

## 8. Prohibited Shortcuts

- 禁止把 `api_transcript` 简单改成 `provider_protocol_history`，这会混淆 raw source 与 compiled projection。
- 禁止为了兼容长期保留 `api_transcript` 和 `provider_protocol_timeline` 双轨。
- 禁止一次性全局替换 `history`、`context`、`payload` 这类高频词。
- 禁止把 `runtime/context_management` 改造成 agent semantic decision owner。
- 禁止把 `content_source`、`source_kind`、字符串前缀或文件名形状当作权威身份。
- 禁止用新名字包旧逻辑；如果旧逻辑无权威，应删除或迁移。

## 9. Expected Outcome

完成后，后端命名应形成稳定读法：

```text
public_message_timeline              # UI/public session message
provider_protocol_timeline           # 原始 provider-native protocol fact source
provider_protocol_history            # compiler 生成的 provider-visible history segment
provider_visible_append_ledger        # 当前 append candidate 的确认账本
physical_prefix_frame                 # provider success 后的 confirmed replay frame
provider_transport_messages           # 最终发给 provider 的消息体
runtime_invocation_packet             # agent/runtime 输入包
provider_request_packet               # provider 请求包
provider_payload_manifest             # provider payload/cache/hash 清单
model_action_request                  # 模型行动裁决合同
action_permit                         # 动作授权令牌
tool_observation                      # 执行观察
output_commit                         # 最终输出提交
```

这样以后看到一个名字，就能知道它在 agent 的时空认知里处于什么位置：事实源、候选、当前尾部、确认账本、物理重放、provider transport、模型裁决、授权，还是最终提交。
