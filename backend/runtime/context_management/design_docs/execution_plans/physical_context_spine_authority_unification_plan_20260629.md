# Physical Context Spine Authority Unification Plan

## 1. 目的

本计划用于重构 agent runtime 的上下文物理拼接和 provider cache 前缀权威。

这次问题的核心不是某个字段命中率偏低，而是系统缺少一条唯一、清晰、可复算的物理拼接算法。上下文拼接是 agent runtime 的主供血链路，必须像核心运行时协议一样稳定：同一 provider、同一会话、同一旧上下文，在上一轮怎样进入 provider payload，下一轮就必须以同一物理段顺序、同一消息结构、同一 sidecar 位置继续出现。

目标不是给 follow-up 或 ledger 再加一层补丁，而是把当前分裂的拼接权威收束为一个物理前缀账本和一个装配算法：

```text
Transport/tool schema
-> Global static prefix
-> Confirmed old context physical prefix
-> Current append
-> Dynamic tail
```

其中语义空间只负责身份识别、候选归类和语义排序输入，不能直接决定 provider cache 边界。provider cache 只能以真实 provider payload 的物理结构为准。

## 2. 当前断点和设计缺口

### 2.1 运行证据

最新缓存审计中，同一会话 `session-52282b1f2d1a4d58` 出现了跨 turn 物理前缀重组：

| 请求 | physical spine included 段数 | 说明 |
| --- | ---: | --- |
| `turn 11 / tool-followup:1` | 19 | 上一轮最后一次 follow-up provider 请求 |
| `turn 12 / initial` | 62 | 下一轮第一发 provider 请求 |

两者前 13 段一致，从第 14 段开始分叉：

```text
1  native_tool_binding_schema
2  global_static
3  tool_index_stable
...
12 runtime_baseline_refs
13 runtime_memory_context
14 分叉开始
```

上一轮 follow-up 第 14 段之后主要是 `provider_visible_user_message_replay`；下一轮 initial 第 14 段之后插入大量 `provider_visible_tool_transcript_replay`。这说明旧上下文并没有作为一个稳定物理整体跨 turn 继承。

缓存账本里虽然显示：

```text
break_status = no_local_physical_break
first_break_segment = {}
```

但这不是可信的最终结论，因为 break detector 只在当前 run 内比较 previous cache records。跨 turn 的上一轮最后请求和下一轮 initial 属于不同 `run_id`，被 `_record_scope_matches()` 排除在比较外。

### 2.2 代码证据

| 文件 | 当前职责 | 发现 |
| --- | --- | --- |
| `backend/runtime/context_management/context_pipeline.py` | initial 上下文流水线 | `apply_provider_visible_context_ledger_to_specs()` 返回 `static_prefix + ledger_specs + current_turn_tail`，initial 依赖 provider-visible ledger 全量物化。 |
| `backend/runtime/context_management/provider_visible_context_ledger.py` | provider-visible 历史封存与回放 | `_materialize_ledger_entries()` 按 ledger entry / tool round 重新物化旧上下文；它是 initial 旧上下文顺序的事实权威。 |
| `backend/runtime/context_management/physical_context_plan.py` | physical lane 排序 | `build_physical_context_plan()` 按 lane 和 provider tool protocol 排序；但它接收的 specs 已经来自不同上游拼接路径。 |
| `backend/harness/loop/single_agent_turn.py` | single-agent tool loop | follow-up 走 `_single_agent_turn_followup_prompt_payload()`，基于当前 `model_messages` 做 append-only rebase，并标记 `append_only_followup_order=True`。 |
| `backend/runtime/context_management/followup_context_rebase.py` | follow-up base/current append 重新分类 | 非动态尾巴会被重标为 sealed 或 current append，但这套分类不等同于 initial 的 ledger replay。 |
| `backend/runtime/model_gateway/provider_payload.py` | provider payload manifest/cache spine | 已经能输出 physical cache spine，但它只反映当前请求 payload，不负责跨请求继承权威。 |
| `backend/runtime/prompt_accounting/cache_anomaly_detector.py` | cache anomaly 检测 | `_record_scope_matches()` 在 `current.run_id` 存在时要求 previous record 同 run，漏掉跨 turn 物理前缀断点。 |

### 2.3 深层原因

当前系统有三套相互靠近但不一致的权威：

```text
provider_visible_context_ledger: 旧上下文内容/entry 顺序权威
followup_context_rebase: follow-up 当前 model_messages 顺序权威
provider_payload_manifest.physical_cache_spine: 当前请求 provider payload 物理边界权威
```

这三者各自局部自洽，但没有一个“上一轮 provider 成功请求的物理前缀 frame”作为跨 turn 继承权威。结果是：

```text
上一轮 follow-up 实际发送的 prefix
!= 下一轮 initial 从 ledger 重新展开的 prefix
```

这就是缓存稳定前缀吃不满的结构性根因。

## 3. 设计原则

### 3.1 物理结构唯一权威

provider cache 的权威对象只能是真实 provider payload 中可复用的物理前缀：

```text
ProviderPayloadManifest.cache_boundary.physical_cache_spine
```

任何 `stable_prefix`、`expected_prefix`、`semantic_slot`、`context_cache_section` 都只能作为候选分类或诊断，不能替代物理结构。

### 3.2 旧上下文必须按物理 frame 继承

旧上下文不能在下一轮重新按语义、tool round、entry index 或消息类型排序。provider 成功后必须封存：

```text
本次 provider 请求真实发送的 prefix frame
```

下一轮 initial 和本轮 follow-up 都从同一个 frame 继续拼接。

### 3.3 current append 只在 provider 成功后晋升

本轮新增内容在当前请求里属于 current append。只有 provider 成功返回后，它才可以按本次真实发送的物理顺序晋升为下一次请求的 confirmed old context。

禁止在 assemble 阶段提前把 current append 当成稳定旧上下文。

### 3.4 dynamic tail 永远不进入旧上下文 frame

动态尾巴可以每轮变化，但它必须位于物理段末尾，并且不能污染 confirmed prefix frame。

### 3.5 provider-native tool round 是原子段组

工具协议轮必须满足：

```text
assistant(tool_calls)
-> tool(tool_call_id)
-> ...
```

只有闭合工具轮可以进入 confirmed old context。未闭合工具轮必须停留在 current append 或 dynamic tail，不能被 physical spine 声明为稳定前缀。

### 3.6 cache anomaly 检测按 cache scope 比较，不按 run 截断

缓存断点的比较范围应是：

```text
provider + model + provider_cache_scope_id/session_id + provider_lane + physical_payload_family
```

不能因为 `run_id` 不同就跳过跨 turn 比较。

### 3.7 诊断账本必须能复算物理段

健康系统、缓存分析和 runtime 账本必须从同一个物理前缀账本读取，不再各自从 prompt stability、semantic section 或 provider ledger 推断。

## 4. 推荐设计方向

新增一个明确的物理前缀账本模型，暂定名称：

```text
PhysicalPrefixFrameLedger
```

它不是替代 provider-visible 内容账本，而是补上缺失的“物理顺序和 cache 边界账本”。

### 4.1 权威关系

```text
Context candidates
  只产出候选、语义 slot、身份 key

ProviderVisibleContextLedger
  只保存 provider-visible message 内容、entry identity、provider 成功确认状态

PhysicalPrefixFrameLedger
  保存每次 provider 成功请求的真实 physical prefix frame

PhysicalContextAssembler
  读取当前 static/tool schema、上一个 confirmed physical frame、current append、dynamic tail
  输出唯一 provider message/spec 顺序

ProviderPayloadManifest
  对最终 provider payload 建 physical_cache_spine
  与 PhysicalPrefixFrameLedger 双向校验
```

### 4.2 目标链路

```text
compile candidates
-> classify semantic slots
-> load latest confirmed PhysicalPrefixFrame
-> resolve static/tool schema physical segments
-> replay old context by frame segment order
-> append current context candidates
-> append dynamic tail
-> build physical_context_plan
-> build ProviderPayloadManifest
-> invoke provider
-> on provider success: confirm current append entries
-> write next PhysicalPrefixFrame
-> prompt accounting / health read PhysicalPrefixFrame
```

### 4.3 initial 和 follow-up 的收敛

initial 和 follow-up 不再分别拥有拼接算法。

| 请求类型 | 当前状态 | 目标状态 |
| --- | --- | --- |
| initial | `context_pipeline -> provider_visible_context_ledger -> physical_context_plan` | `PhysicalContextAssembler(base_frame + current_initial_append + dynamic_tail)` |
| follow-up | `model_messages append-only rebase -> physical_context_plan` | `PhysicalContextAssembler(base_frame + current_followup_append + dynamic_tail)` |

follow-up 可以复用当前消息流作为 append 输入，但不能用当前消息流决定旧上下文物理前缀。

## 5. 固定执行算法

### 5.1 输入

```text
provider
model
provider_cache_scope_id / session_id
invocation_kind
current context candidates
latest confirmed PhysicalPrefixFrame
current tool schema / transport contract
dynamic tail candidates
```

### 5.2 阶段

#### Stage A: 物理 frame 读取

Owner: `PhysicalPrefixFrameLedger`

输入：

```text
scope_id
provider
model
provider_lane
```

输出：

```text
latest_confirmed_frame
```

禁止：

```text
不重排 frame.segments
不从 semantic slot 推断缺失段
不把 dynamic tail 补进 frame
```

#### Stage B: 静态/transport 前缀解析

Owner: `ProviderPayloadTransportResolver`

输入：

```text
current tool catalog
global static specs
provider params
```

输出：

```text
tool_schema_segment
global_static_segments
transport_contract_hash
```

禁止：

```text
不读取历史上下文
不决定 current append 是否封存
```

#### Stage C: 旧上下文物理回放

Owner: `PhysicalContextAssembler`

输入：

```text
latest_confirmed_frame.old_context_segments
ProviderVisibleContextLedger entries/messages referenced by frame
```

输出：

```text
old_context_specs_in_exact_frame_order
```

禁止：

```text
不按 entry_index 重新全量排序
不按 tool round id 重新插队
不按 semantic_slot 合并
```

如果 frame 引用的 message 不存在，必须形成结构性失败，不能静默走当前 ledger 全量回放。

#### Stage D: current append 拼接

Owner: `CurrentAppendCollector`

输入：

```text
本轮 user context
本轮 tool call/tool observation transcript
本轮 read evidence summary
本轮 steering
```

输出：

```text
current_append_specs
```

禁止：

```text
不把 current append 标记为 provider_visible_context_prefix
不写入 confirmed frame
不覆盖旧 frame 顺序
```

#### Stage E: dynamic tail 拼接

Owner: `DynamicTailCollector`

输入：

```text
runtime control tail
follow-up action contract
recovery instruction
volatile cursor
```

输出：

```text
dynamic_tail_specs
```

禁止：

```text
不进入 provider-visible ledger
不进入 PhysicalPrefixFrame
```

#### Stage F: provider payload manifest 校验

Owner: `ProviderPayloadManifest`

输入：

```text
最终 specs/messages/tools/params
```

输出：

```text
provider_payload_manifest
physical_cache_spine
```

必须校验：

```text
physical_cache_spine.segments == assembled prefix segments
old_context frame hash == replayed old_context hash
tool schema position stable
no prefix segment after current tail
no unclosed tool round in confirmed prefix
```

#### Stage G: provider 成功提交

Owner: `ModelRuntimeProviderSuccessCommit`

输入：

```text
provider response success
provider usage
provider_payload_manifest
current_append_candidates
previous PhysicalPrefixFrame
```

输出：

```text
confirmed provider-visible entries
new PhysicalPrefixFrame
prompt accounting records
```

禁止：

```text
不在 provider 失败时晋升 current append
不重新生成旧上下文顺序
不把 current dynamic tail 写入 frame
```

## 6. 数据模型设计

### 6.1 PhysicalPrefixFrame

```text
PhysicalPrefixFrame:
  frame_id
  scope_id
  provider
  model
  provider_lane
  source_request_id
  source_run_id
  previous_frame_id
  status: pending | confirmed | rejected
  transport_contract_hash
  provider_payload_prefix_hash
  physical_cache_spine_message_subtotal_hash
  provider_payload_messages_hash
  physical_payload_family_hash
  boundary_segment_id
  segment_count
  message_segment_count
  tool_segment_count
  segments[]
  current_append_entry_indexes[]
  created_at
  confirmed_at
  authority
```

### 6.2 PhysicalPrefixFrameSegment

```text
PhysicalPrefixFrameSegment:
  ordinal
  segment_id
  transport_location
  role
  kind
  source_ref
  content_hash
  byte_length
  physical_prefix_lane
  prefix_family
  cache_scope
  cache_role
  prefix_tier
  provider_visible_entry_index
  provider_visible_hash
  provider_tool_round_id
  provider_tool_round_closed
  boundary_participation
```

### 6.3 存储位置

建议新增：

```text
storage/runtime_state/physical_prefix_frame_ledger/{safe_scope}.json
```

并在 prompt accounting hot logs 中记录只读快照：

```text
storage/runtime_state/prompt_accounting/hot/by_time/.../physical_prefix_frames.jsonl
```

健康系统以后读取 `PhysicalPrefixFrameLedger` 和 `physical_prefix_frames.jsonl`，不再从 `prompt_stability` 推断缓存边界。

### 6.4 ProviderVisibleContextLedger 降权

`ProviderVisibleContextLedger` 保留内容账本职责：

```text
entry_index
item_key
provider_visible_message
provider_visible_hash
confirmed_by_request_id
confirmed_turn_id
```

但它不再拥有全量 replay 顺序权威，也不从 `confirmed_by_request_id` 反解析 turn 身份。旧上下文顺序由 `PhysicalPrefixFrame.segments[]` 决定，turn 归属来自 provider success 确认时写入的 `confirmed_turn_id`。

`context_prefix_identity` 不再通过 `physical_prefix_frame_*` kind、`source_kind` 或 `content_source` 判断 confirmed frame replay。frame replay 必须由显式 replay contract 标记；provider protocol replay 单独作为 provider protocol replay 生命周期，不能伪装成 physical frame replay。

同一原则也适用于 historical-only 可见性：`semantic_commit_class` 名称不再承担隐藏开关，历史可见性必须由 `semantic_visibility`、`provider_visible_replay_only`、`context_memory_visible=false` 或 `historical_only_on_replay` 这类显式字段表达。

## 7. 模块改造计划

### 7.1 新增模块

| 文件 | 职责 |
| --- | --- |
| `backend/runtime/context_management/physical_prefix_frame_ledger.py` | 读写 `PhysicalPrefixFrameLedger`，提供 latest confirmed frame、append confirmed frame、结构校验。 |
| `backend/runtime/context_management/physical_context_assembler.py` | 唯一物理拼接算法，供 initial 和 follow-up 共用。 |
| `backend/runtime/context_management/physical_prefix_frame_models.py` | frame/segment dataclass 和序列化。 |

### 7.2 重写或收束模块

| 文件 | 行动 |
| --- | --- |
| `context_pipeline.py` | initial 不再直接 `static_prefix + ledger_specs + tail`；改为调用 `PhysicalContextAssembler`。 |
| `provider_visible_context_ledger.py` | 保留内容确认；删除“全量旧上下文顺序权威”职责；materialize 必须支持按 frame refs 回放。 |
| `physical_context_plan.py` | 保留 lane 排序和 spine 诊断，但输入必须来自 assembler 的物理顺序；不再弥补上游顺序分叉。 |
| `followup_context_rebase.py` | 逐步删除或降为 current append 标注工具；不得再决定旧上下文顺序。 |
| `single_agent_turn.py` | follow-up 从 append-only message order 切换为 `PhysicalContextAssembler`；移除 `append_only_followup_order` 作为物理顺序权威。 |
| `provider_payload.py` | build manifest 后校验 manifest spine 与 PhysicalPrefixFrame 的 old prefix/hash 对齐。 |
| `model_runtime.py` | provider 成功后同时确认 provider-visible entries 和写入 new PhysicalPrefixFrame。 |
| `cache_anomaly_detector.py` | 比较范围改为 cache scope/session，不被 run_id 截断；新增跨 turn physical frame drift reason。 |
| `provider_cache_ledger.py` | ledger record 引用 `physical_prefix_frame_id`，报告 frame diff，不只报告 local no break。 |
| `cache_planner.py` | expected cacheable tokens 从 physical frame + manifest spine 读取；未闭合工具轮进入 expected miss/blocker。 |
| `stability_report.py` | stable/volatile 报告降为诊断，不作为缓存权威。 |
| `health_system/*` | 健康面板读取 `PhysicalPrefixFrameLedger` / prompt accounting frame records。 |

### 7.3 删除旧权威

以下逻辑在新链路稳定后必须删除，不能长期保留为 fallback：

```text
follow-up append-only order as physical message order
provider_visible ledger full materialization as replay order authority
run_id-scoped break comparison
semantic stable_prefix as cache authority
tool round heuristic reorder as primary assembly path
```

## 8. 分阶段实施计划

### Phase 0: 冻结目标和字段

目标：锁定命名、数据模型和禁止事项。

改动：

```text
只更新设计文档
不改运行代码
```

完成条件：

```text
本文档通过审阅
PhysicalPrefixFrame 字段确认
initial/follow-up 共用 assembler 方向确认
```

### Phase 1: 建立 PhysicalPrefixFrameLedger 只写影子账本

目标：在不改变 provider 请求行为的前提下，把每次 provider 成功请求的真实 physical spine 记录成 frame。

涉及文件：

```text
physical_prefix_frame_models.py
physical_prefix_frame_ledger.py
model_runtime.py
provider_payload.py
provider_cache_ledger.py
```

输出：

```text
每次 provider success 产生 confirmed PhysicalPrefixFrame
prompt accounting 记录 frame_id/frame_hash/frame segments
```

禁止：

```text
不改变 prompt 拼接顺序
不把 shadow frame 作为 fallback
```

完成条件：

```text
连续真实三轮对话中，每个 provider success 都能写出 frame
frame.segments 与 provider_payload_manifest.physical_cache_spine 完全一致
未闭合工具轮不会进入 confirmed frame
```

### Phase 2: initial 改为 frame-driven old context replay

目标：下一轮第一发请求不再从 provider-visible ledger 全量重排旧上下文，而是按 latest confirmed frame 回放 old context。

涉及文件：

```text
context_pipeline.py
physical_context_assembler.py
provider_visible_context_ledger.py
physical_context_plan.py
```

输入：

```text
latest confirmed frame
current static/tool schema
current turn candidates
dynamic tail
```

输出：

```text
initial request specs/messages
```

禁止：

```text
不允许 ledger entry_index 全量排序覆盖 frame 顺序
不允许缺失 frame 时静默回旧链路
```

缺失 frame 的处理：

```text
新会话第一轮允许无 frame
已有会话 frame 缺失必须记录 structural_missing_frame，并使用明确 cold-start policy
```

完成条件：

```text
turn N 最后一次 provider success frame 的 old prefix
与 turn N+1 initial old prefix 前缀段一致
```

### Phase 3: follow-up 改为 frame-driven assembly

目标：follow-up 不再把当前 `model_messages` 当作物理前缀权威。

涉及文件：

```text
single_agent_turn.py
followup_context_rebase.py
physical_context_assembler.py
provider_tool_protocol.py
```

改动：

```text
follow-up 只提交 current append delta
old context 从 same latest confirmed frame 回放
dynamic tail 始终拼在末尾
```

删除/降权：

```text
append_only_followup_order
physical_message_order=append_only_context_including_dynamic_tail
cache_policy_rebased=disabled_physical_source_order_append_only
```

完成条件：

```text
同一 turn 内 follow-up 的 old prefix 与 latest confirmed frame 一致
新增 tool transcript 只出现在 current append
provider success 后才写入下一 frame
```

### Phase 4: break detector 和账本切换到 frame authority

目标：缓存诊断不再漏掉跨 turn 物理断点。

涉及文件：

```text
cache_anomaly_detector.py
provider_cache_ledger.py
cache_planner.py
stability_report.py
context_usage_meter.py
```

新增 anomaly reason：

```text
physical_prefix_frame_changed
old_context_frame_replay_order_changed
provider_visible_entry_missing_for_frame_segment
unclosed_tool_round_in_confirmed_prefix
cross_turn_previous_frame_under_read
```

完成条件：

```text
turn N last success frame != turn N+1 initial frame 时必须报告具体首个分歧段
不再输出误导性的 no_local_physical_break
```

### Phase 5: 健康系统和诊断脚本切换

目标：缓存健康只读统一账本。

涉及文件：

```text
backend/health_system/*
backend/scripts/diagnose_deepseek_prompt_cache.py
backend/scripts/diagnose_real_writing_prompt_cache.py
backend/scripts/live_prompt_cache_task_probe.py
backend/scripts/probe_deepseek_physical_dynamic_tail_cache.py
```

完成条件：

```text
健康报告显示 frame_id、previous_frame_id、first_divergence_segment
缓存命中解释来自 PhysicalPrefixFrameLedger
prompt_stability 只作为补充，不再作为 cache spine 权威
```

### Phase 6: 清理旧链路

目标：删除旧权威和旧 fallback，避免以后再次分叉。

清理对象：

```text
provider_visible ledger full replay as ordering authority
followup append-only physical order
messages-only prefix fallback
run_id-only previous cache comparison
旧 semantic stable prefix cache authority 文案
```

完成条件：

```text
rg 检查旧 authority 标记不可达
真实三轮对话 initial/follow-up/next initial old prefix frame 连续一致
```

## 9. 文件级执行清单

| 文件 | 当前角色 | 目标行动 | 完成条件 |
| --- | --- | --- | --- |
| `context_pipeline.py` | initial 拼接入口 | 改为调用 `PhysicalContextAssembler` | initial 不再直接拼 `static + ledger + tail` |
| `physical_context_plan.py` | lane 排序/diagnostics | 保留物理 lane 计算；输入来自 assembler | plan 不再修复上游顺序分叉 |
| `provider_visible_context_ledger.py` | 内容账本 + replay 排序 | 降为内容账本；按 frame refs materialize | 不再拥有全量 replay 顺序权威 |
| `followup_context_rebase.py` | follow-up 重分类 | 删除旧上下文顺序决策，只保留 current append 标注或整体移除 | follow-up 不再从当前 model_messages 推断旧 prefix |
| `single_agent_turn.py` | tool loop/follow-up 请求装配 | follow-up 接入 assembler；删除 append-only physical order | initial/follow-up 同一物理算法 |
| `provider_tool_protocol.py` | 工具轮结构 | 增加 confirmed-prefix eligibility 判断 | 未闭合工具轮不能进 frame |
| `provider_payload.py` | provider manifest/cache spine | 与 frame 双向校验 | manifest spine 和 frame prefix 可复算一致 |
| `model_runtime.py` | provider success commit | 成功后写 PhysicalPrefixFrame | provider 失败不晋升 current append |
| `cache_anomaly_detector.py` | break 检测 | 跨 run 按 cache scope 比较 frame | 能报告跨 turn 首个物理分歧 |
| `provider_cache_ledger.py` | cache ledger | 写入 frame refs 和 frame diff | ledger 不再只显示 no_local_physical_break |
| `cache_planner.py` | expected cacheable tokens | 从 frame/manifest spine 计算 | expected miss 家族不混 semantic stable |
| `stability_report.py` | stable/volatile 报告 | 降为语义诊断 | 不再作为 cache authority |
| `context_usage_meter.py` | 上下文用量 | 引用 frame tokens | UI/健康的缓存读数和账本一致 |
| `health_system/*` | 健康报告 | 读取 frame ledger | health 不再自算缓存边界 |
| `diagnose_*cache*.py` | 诊断脚本 | 输出 frame diff 和 first divergence | 能解释 initial 低命中原因 |

## 10. 验证方案

项目规则禁止新增弱语义测试文件，也禁止 mock provider payload 造通过。验证以真实运行和账本审计为主。

### 10.1 静态检查

```text
python -m py_compile changed runtime files
rg append_only_followup_order
rg disabled_physical_source_order_append_only
rg no_local_physical_break
```

要求：

```text
旧 authority 不再位于主路径
旧字段如存在，只能在迁移诊断或文档中出现
```

### 10.2 真实三轮运行

必须跑同一会话连续三轮：

```text
turn A initial + follow-ups
turn B initial + follow-ups
turn C initial + follow-ups
```

检查：

```text
turn A last confirmed frame == turn B initial old frame
turn B last confirmed frame == turn C initial old frame
initial provider cached tokens 覆盖 static + old context frame
follow-up current append 不污染 old frame
dynamic tail 不进入 frame
```

### 10.3 账本核对

必须输出：

```text
frame_id
previous_frame_id
source_request_id
provider_payload_prefix_hash
physical_cache_spine_message_subtotal_hash
segment_count
first_divergence_segment
provider cached / prompt / miss
```

合格标准：

```text
如果 hit rate 低，账本必须给出明确 first divergence 或 provider under-read evidence
不能只给 no_local_physical_break
```

## 11. 迁移与切换规则

### 11.1 Shadow 只记录，不兜底

Phase 1 可以 shadow 写 frame，但不允许用 shadow 结果覆盖主路径，也不允许在出错时静默回旧路径。

### 11.2 缺失 frame 的唯一合法场景

```text
新会话第一轮
清空缓存后的 cold start
provider/model/tool transport contract 明确变化
```

其他缺失都必须记录 structural failure。

### 11.3 旧链路保留窗口

旧链路只能保留到对应 phase 切换完成。每个旧函数必须有删除条件，不允许以兼容为理由长期并行。

### 11.4 回滚规则

回滚只能回滚到上一阶段入口，不允许局部打开旧 fallback。

例如 Phase 3 失败：

```text
回滚 follow-up 到 Phase 2 前状态
保留 frame shadow logs
不允许同时让 follow-up 一半用 frame、一半用 append-only
```

## 12. 禁止事项

执行时禁止：

```text
用 stable/expected prefix 当缓存权威
让 semantic slot 决定 provider physical boundary
让 provider-visible ledger entry_index 重新全量排序旧上下文
follow-up 独立维护 append-only 物理顺序
把未闭合工具轮写入 confirmed prefix
用 run_id 截断跨 turn break detection
新增 v2 并长期双跑旧链路
新增弱语义测试或 mock provider payload 造通过
保留旧 fallback 只为了“兼容”
```

## 13. 预期结果

完成后系统应具备以下性质：

1. initial 和 follow-up 使用同一条物理拼接算法。
2. 旧上下文跨 turn 以 frame 为单位稳定继承。
3. dynamic tail 可以变化，但不会污染 confirmed old context。
4. provider cache 账本能明确说明断点在第几个物理段。
5. 健康系统和诊断脚本读同一个 cache/frame 账本。
6. 如果 provider 少读缓存，系统能区分：

```text
本地物理前缀确实变了
本地物理前缀没变但 provider under-read
当前 append/dynamic tail 过大
tool schema/transport contract 改变
```

7. 不再出现“明明插线到一个上下文段，却吃不到稳定缓存还解释不清”的结构性问题。
