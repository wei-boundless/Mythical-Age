# 上下文拼接系统 — 系统设计报告

> 本报告基于对 `backend/runtime/context_management/` 及相关模块代码的完整审查编写。
> 覆盖范围：context_pipeline、physical_context_plan、provider_visible_append_ledger、physical_prefix_frame_ledger、context_segment_policy、context_segment_registry、context_capability_policy、session_compaction、compactor、semantic_worker 等核心模块。

---

## 一、系统总览

上下文拼接系统是整个 agent runtime 的 **上下文管线**（Context Pipeline），负责把原始消息规格列表经过**能力过滤 → provider-visible append 候选 → 物理前缀帧 replay/物理计划 → Provider 交付**四个阶段，组装成最终发送给 LLM 的请求消息序列。

### 架构层级

```
┌─────────────────────────────────────────────────┐
│                 Agent Turn Loop                  │
│  (single_agent_turn.py / compiler.py)           │
├─────────────────────────────────────────────────┤
│              Context Pipeline                    │
│  build_context_pipeline(specs, ...)              │
├──────────┬──────────┬──────────┬────────────────┤
│ Capabi-  │ Provider │ Physical │ Message        │
│ lity     │ Visible  │ Context  │ Assembly       │
│ Profile  │ Append   │ Plan     │ + Transport    │
│ Filter   │ Stage    │ Stage    │ Contract       │
└──────────┴──────────┴──────────┴────────────────┘
         ↑                            ↑
    Context Candidates           Provider Request
    (各组件贡献)                  (消息体 + cache 元数据)
```

---

## 二、核心流程（Pipeline 四阶段）

入口函数：`build_context_pipeline()` (`context_pipeline.py:44`)

### 阶段 0：候选上下文装配（Context Candidates）

在 pipeline 执行前，各运行时组件已经通过 `ContextCandidateRegistry` (`context_candidate_registry.py`) 注册自己的消息规格到候选列表。**这一段不在 pipeline 内部，是上游行为。**

`ContextCandidateContributor` 接口由各系统模块（system prompt、memory、工具结果、turn tail 等）实现，每个 contributor 把自己的 specs 投递到 registry。

### 阶段 1：上下文能力过滤（Context Capability Profile Filter）

**函数：** `apply_context_capability_profile_to_specs()` (`context_pipeline.py:97`)

- 用途：执行 runtime assembly 已编译的上下文能力边界，**裁减**当前 turn 不允许接入的上下文类型。
- 配置来源：`context_capability_profile` 参数或从 `system_wiring_manifest.compiled.context_capability_profile` 提取；不再读取旧 `context_policy` / `memory_policy` 做二次裁决。
- 过滤逻辑：
  - `provider_message_replay_contract` — 已确认的 provider message replay 契约会保留原始 provider message bytes。
  - 其他 specs 送入 `apply_context_capability_profile()` (`context_capability_policy.py`) 逐条判定。
  - 每条 spec 根据其 `kind` 查找 capability 声明，不符合 profile 的被丢弃并记录诊断。
- **replay 契约机制**：已被物理前缀帧或 provider protocol replay 标记的 specs 不被重新分类，避免 replay 消息因 provider 差异被错误改写。

### 阶段 2：Provider-visible append stage

**函数：** `apply_provider_visible_append_stage_to_specs()` (`context_pipeline.py`)

这一阶段只决定当前请求中哪些 provider-visible 片段可以作为 append candidate 等待 provider success 后确认。它不拥有下一轮 replay 顺序权威；confirmed replay 由 `physical_prefix_frame_ledger.py` 和 `physical_context_assembler.py` 承担。

#### 触发条件
- `invocation_kind` 必须属于 provider-visible append stage 管理的调用类型
- `provider_visible_append_scope` 必须有值
- `storage_root` 必须非空

#### 核心逻辑：三段式分类

```
输入 specs ──────────────────────────────────────────
    │
    ├── STATIC_PREFIX（系统 prompt）→ 直接保留在最前面
    │
    ├── CONTEXT_MEMORY_PREFIX / CONTEXT_APPEND
    │   ├── 可 seal（可作为 append candidate）→ provider_visible_append_candidates
    │   └── 不可 seal → 放到 current_turn_tail_specs
    │
    └── DYNAMIC_TAIL → 阻塞重放，放到 tail（blocked_dynamic_tail_replay_count）
```

- **可 seal 判定**：`context_segment_policy_is_provider_visible_sealable(policy)` 检查 policy 的 `prefix_cache_scope != ""` 且 `prefix_cache_role != "volatile"`。
- **分隔线原则**：`STATIC_PREFIX` 在最前，`current_turn_tail` 在最后，中间只放本轮可确认的 provider-visible append；已确认 replay 从 physical prefix frame 注入。

#### Append candidate 装配

`assemble_provider_visible_append_specs()` (`provider_visible_append_ledger.py`)：

1. 从磁盘加载 `storage/runtime_state/provider_visible_append_ledger/<scope>.json`
2. 根据统一 `context_segment_policy` 判断 candidate 是否可确认
3. 为本轮可确认片段写入 `provider_visible_append_*` metadata
4. 按 `original_order` 排序，保持当前 append 的相对顺序
5. 返回等待 provider success 的 current append specs

**输出排序：** physical assembler 最终组合为 `[static_prefix, ...confirmed_old_context, ...current_append, ...current_turn_tail, ...never_replay_tail]`

### 阶段 3：物理上下文计划（Physical Context Plan）

**函数：** `build_physical_context_plan()` (`physical_context_plan.py`)

读取已经由 physical assembler 组装好的消息顺序，生成物理车道（lane）诊断、缓存脊柱哈希、可见性和效期信息。它不再改变消息顺序。

#### 四条物理车道

| 车道 | 来源 Section | 缓存脊柱参与 | 说明 |
|---|---|---|---|
| `global_static_prefix` | STATIC_PREFIX | ✅ 是 | 系统 prompt，全局缓存 |
| `provider_visible_context_prefix` | CONTEXT_MEMORY_PREFIX（stable） | ✅ 是 | 经 ledger 确认的可缓存历史 |
| `current_turn_tail` | CONTEXT_APPEND + 不可 seal | ❌ 否 | 当前轮新增消息 |
| `never_replay_tail` | DYNAMIC_TAIL | ❌ 否 | 动态尾，永不重放 |

#### 顺序规则

- 物理顺序只由 `assemble_physical_context_spine()` 生成
- `build_physical_context_plan()` 保留输入顺序，只做诊断和 hash
- 标准顺序：`global_static_prefix < provider_visible_context_prefix < current_turn_tail < never_replay_tail`

#### 缓存脊柱哈希

`cache_spine_hash` 是一个 SHA-256 的确定性哈希，用于标识哪一组消息构成了缓存键。

- 构造材料：transport_contract_hash + cache_spine_generation + 每个脊柱段（lane + content_hash）
- **用途**：给 LLM provider 的缓存系统做前缀缓存匹配；hash 相同说明前缀内容未变，可复用缓存。

#### stable-after-tail 违规检测

如果有脊柱消息（cache_spine_participation == true）出现在 tail 车道之后，会记录为 `stable_after_tail_violations`。这是约束违规——说明不该有缓存消息出现在可变 tail 之后。

### 阶段 4：Provider 请求发货

Pipeline 输出 `ContextPipelineResult.message_specs` 后，由上游（`compiler.py` / `context_message_producers.py`）将其转换为最终的 Provider Request。

`context_message_producers.py` 负责：
- 遍历 message_specs，构建 `model_message` 结构
- 应用 `packet_assembler` 的 `context_live_probe` 策略（如果启用）
- 对每个 spec 决定是**完整消息 delivery** 还是**前缀缓存引用**
- 添加 `cache_scope`、`cache_role`、`prefix_cache_policy` 等参数给 provider

---

## 三、各模块详解

### 3.1 Context Segment Policy (`context_segment_policy.py`)

**核心数据结构：** `ContextSegmentPolicy`（dataclass）

每个消息 spec 根据其 `kind` 被映射到一个 segment policy，policy 决定：

| 字段 | 含义 |
|---|---|
| `section` | 归属区域：STATIC_PREFIX / CONTEXT_MEMORY_PREFIX / CONTEXT_APPEND / DYNAMIC_TAIL |
| `prefix_cache_scope` | 缓存作用域：`"global"` / `"session"` / `""`（空=不可缓存） |
| `prefix_cache_role` | 缓存角色：`"static_prefix"` / `"volatile"` / `"memory_prefix"` |
| `prefix_tier` | 层级：`"static"` / `"dynamic"` / `"volatile"` |
| `semantic_slot` | 语义槽位（用于排序和 content replacement） |

**映射规则：** `context_segment_policy_for_spec()` 从 `context_segment_registry` 查找 spec.kind 对应的声明，若找不到则使用 `CONTEXT_APPEND` 兜底。

**已知 kind 分类示例：**

```
STATIC_PREFIX_KINDS: system, runtime_instruction
MEMORY_CONTEXT_KINDS: memory_context, session_history, compressed_history
APPEND_ONLY_CONTEXT_KINDS: user_message, tool_call, tool_result, prompt_censorship
CURRENT_CONTROL_TAIL_KINDS: current_turn_instruction, provider_prefill
DYNAMIC_TAIL: tool_observation_followup
```

### 3.2 Context Segment Registry (`context_segment_registry.py`)

集中注册所有上下文类型的声明。每种 kind 声明包含：

- `layer` — 层级归属
- `semantic_slot` — 语义槽
- `source_kind` / `content_source` — 来源标记
- `capability` — LLM 能力要求
- `dynamic_tier` — 动态分层

**注册方式：** `register_context_segment_policy_defaults()` 在模块加载时调用，建立 kind → policy 的完整映射。

### 3.3 Provider Visible Append Ledger (`provider_visible_append_ledger.py`)

**磁盘持久化目录：** `storage/runtime_state/provider_visible_append_ledger/*.json`（按 scope 隔离）

**数据架构：**

```json
{
  "schema_version": 1,
  "scope": "session_xxx",
  "entries": [
    {
      "entry_index": 1,
      "kind": "memory_context",
      "content_hash": "sha256:...",
      "provider_visible_message": { ... },
      "confirmed_at": "2026-06-27T...",
      "status": "confirmed"
    }
  ]
}
```

**核心函数：**
- `save_provider_visible_append_ledger()` — 写入 append ledger 到磁盘
- `load_provider_visible_append_ledger()` — 从磁盘加载
- `assemble_provider_visible_append_specs()` — 生成本轮 current append candidates
- `confirm_provider_visible_append_entries()` — 在 provider 成功响应后确认条目
- `latest_provider_visible_append_success_anchor()` — 获取最近的成功 append anchor（用于 fork 继承）

**注意边界：** append ledger 记录“可确认候选”和 provider success 后的确认状态；它不负责下一轮 replay。下一轮 replay 的唯一物理权威是 `physical_prefix_frame_ledger.py` 生成的 confirmed frame。

### 3.4 物理上下文计划 (`physical_context_plan.py`)

**`PhysicalContextPlan`** dataclass 包含完整的物理编排计划：

- `plan_id` — 确定性 plan 标识
- `cache_spine_hash` — 缓存脊柱哈希
- `cache_spine_segment_count` — 缓存脊柱段数
- `lane_counts` — 各车道计数
- `segments` — 排序后的物理段列表（每个带有 lane、section、cache_scope、cache_role、content_hash 等信息）
- `stable_after_tail_violations` — 违规记录

### 3.5 会话压缩（Session Compaction）

`session_compaction.py` — `compact_session_history()`

- 使用 `compactor.py` 的 `Compactor` 类，触发 `semantic_worker.py` 中的语义压缩
- 过滤条件由 `low_authority_text.py` 的低权威文本规则控制
- `invariants.py` 保证压缩前后上下文完整性
- `hooks.py` 提供压缩前后 hook（logging/metrics/状态更新）
- `microcompact.py` 提供轻量级增量压缩（不完整语义，只做 token 预算修剪）
- `budget/presets.py` — 提供预设 token 预算模板

**压缩触发：** `auto_compact_session_if_needed()` 在每轮结束前检查 token 预算，超出阈值时异步触发压缩。

### 3.6 工具结果存储 (`runtime_objects/tool_result_storage.py`)

- `DEFAULT_PAYLOAD_BUDGET_BYTES` — 默认 payload 预算
- `DEFAULT_FIELD_SIZE_LIMIT_BYTES` — 字段大小限制
- `DEFAULT_PREVIEW_SIZE_BYTES` — 预览大小限制
- `PERSISTED_OUTPUT_TAG` — 持久化输出标签
- `ContentReplacement` — 内容替换机制（当原始工具结果 > 预算时，替换为摘要引用）

---

## 四、整体数据流（Agent 一轮的上下文生命周期）

```
1. Turn 开始
   │
2. Compiler 收集上下文 specs ───────────────────┐
   │  ├─ system prompt (STATIC_PREFIX)           │
   │  ├─ session history / compressed memory     │  ContextCandidateRegistry
   │  ├─ tool results (CONTEXT_APPEND)           │
   │  ├─ current user message                    │
   │  └─ current turn tail                       │
   │                                            │
3. build_context_pipeline(specs) ◄──────────────┘
   │
   ├─ (1) Capability Profile Filter
   │    └─ 移除当前 provider 不支持的消息类型
   │
   ├─ (2) Compaction Generation 标记
   │    └─ specs_with_context_compaction_generation()
   │
   ├─ (3) Provider Visible Ledger Stage
   │    ├─ 分类：static / candidate / tail
   │    ├─ 合并继承 scope 的 ledger
   │    ├─ 写 ledger 到磁盘（未确认）
   │    └─ 输出：static_prefix + ledger_specs + tail
   │
   ├─ (4) Physical Context Plan
   │    ├─ 分配物理车道
   │    ├─ 排序（车道优先级 + tool order）
   │    ├─ 计算 cache_spine_hash
   │    ├─ 检测 stable-after-tail 违规
   │    └─ 标注各 spec 的物理元信息
   │
4. Context Message Producers
   │  ├─ 遍历 message_specs
   │  ├─ 组装 model_message
   │  ├─ 应用 live_probe 策略（如启用）
   │  └─ 输出最终 Provider Request
   │
5. Provider 发送 + 响应
   │
6. Post-turn 处理
   │  ├─ confirm_provider_visible_append_entries()
   │  ├─ append_physical_prefix_frame_from_provider_success()
   │  ├─ auto_compact_session_if_needed()
   │  └─ update context_commit_record
```

---

## 五、关键设计约定与注意风险

### 5.1 核心设计约定

1. **SPT（Static Prefix Then...）：**
   物理重放顺序严格为 `global_static_prefix → provider_visible_context_prefix → current_turn_tail → never_replay_tail`。

2. **可 seal 即锁定：**
   只有统一 segment policy 判定为 provider-visible sealable 的 segment 才能进入 provider-visible append ledger。进入 append ledger 不等于可 replay；只有 provider success 后被 physical prefix frame 提升的消息，下一轮才可作为 confirmed replay 注入。

3. **内容哈希驱动：**
   每条消息的 content_hash 决定它是否与之前相同。hash 相同 = 缓存可能命中。这是 LLM provider 前缀缓存的底层依据。

4. **确定性组装：**
   pipeline 中的物理顺序只由 `assemble_physical_context_spine()` 生成；`build_physical_context_plan()` 使用 `_stable_json_hash` 计算诊断 hash，不做二次排序。

### 5.2 已识别的风险点

#### 风险 1：Ledger 写入与确认的时序间隙
- **描述：** `assemble_provider_visible_append_specs()` 在 provider 请求发送前登记 current append candidate；`confirm_provider_visible_append_entries()` 在 provider 成功响应后才确认。
- **后果：** 如果 provider 请求发送后但确认前进程崩溃，append ledger 中可能存在未确认条目。
- **缓解：** `physical_context_assembler` 只从 physical prefix frame replay confirmed provider-visible 历史；未确认 append candidate 不会因为存在于 append ledger 而成为下一轮 replay。

#### 风险 2：Fork 子会话的继承锚点
- **描述：** 当 `inherited_scope` 指向一个父会话时，子会话通过 fork 点的 provider-visible append anchor 和 physical frame 继承已确认前缀。继承锚点通过多种 hash 关联（`fork_point_provider_request_commit_id`、`fork_point_cache_spine_hash` 等），任何 hash 不匹配都会导致继承失败（返回空）。
- **后果：** hash 不匹配 → 继承空 anchor → 子会话失去所有父会话的上下文 → 子会话在"空历史"状态下运行。
- **缓解：** 需要确保 fork 时所有 hash 正确传递；`provider_visible_context_inheritance_contract()` 只提取 `inherited_anchor`，不提供 fallback。

#### 风险 3：stable-after-tail 违规
- **描述：** 物理计划会检测是否有缓存脊柱段出现在 current_turn_tail 之后。这些违规段仍然会随消息体发送，但**不参与缓存脊柱哈希计算**。
- **后果：** 违规段可能破坏 provider 的前缀缓存命中率，因为 tail 之后的缓存段导致哈希变化。
- **缓解：** 违规被记录在 `stable_after_tail_violations` 中，可在上游排查时查看。当前没有自动修复逻辑。

#### 风险 4：Compaction Generation 版本漂移
- **描述：** `normalize_context_compaction_generation` 默认值是 `"0"`。如果某轮 pipeline 没有传递 compaction_generation，所有消息都标记为 generation `"0"`。
- **后果：** 这可能导致压缩后的历史消息与当前轮的 generation 不匹配，物理计划无法区分新旧压缩历史。
- **缓解：** `session_compaction.py` 会在压缩时显式设置 generation；如果使用旧版代码（未传入 generation），所有消息默认 `"0"`，不影响运行但无法精细化区分版本。

#### 风险 5：内容替换（Content Replacement）与引用失效
- **描述：** `tool_result_storage.py` 的 ContentReplacement 机制在大工具结果 > payload budget 时，将原始内容替换为引用键。引用的实际内容在独立存储中。
- **后果：** 如果引用存储被清理或写入引用后被修改，重放时内容替换引用变成**悬空引用**，重放的消息内容不完整。
- **缓解：** ContentReplacement 的 `replacement_id` 需要在引用持续期内有效，但当前没有显式的引用 GC 保护机制。

#### 风险 6：缓存脊柱哈希的传输契约
- **描述：** `cache_spine_hash` 的计算包括 `transport_contract_hash`。如果 transport contract 在连续两轮之间变化（比如 provider/model 切换），hash 会变化，前缀缓存失效。
- **后果：** 属于正常行为（provider/model 切换自然应该清缓存），但需要确保 transport_contract_hash 的生成是**稳定且唯一的**，且在同一 provider/model 持续期内不变。
- **缓解：** 当前 `_stable_json_hash` 确保确定性，无需额外缓解。

### 5.3 Debug 与排查要点

| 症状 | 排查切入点 |
|---|---|
| 上下文缺失 | 检查 `context_capability_profile` 是否过滤了目标 kind；检查 ledger 文件是否存在且正确 |
| 重复上下文 | 检查 `provider_message_replay_contract` 是否错误地把非 replay 消息标记为 byte-preserve replay |
| 缓存不命中 | 检查 `cache_spine_hash` 是否在连续轮之间变化，对比 transport_contract_hash |
| 子会话无历史 | 检查 `inherited_anchor` 中的各个 hash 是否与父会话最终确认状态一致 |
| 压缩后上下文变化 | 检查 `compaction_generation` 是否正确传递，对比压缩前后的 spec count 和 content_hash |
| Append ledger 膨胀 | 检查 `provider_visible_current_append_spec_count` 诊断值，确认是否有不可 seal 的条目被误放入 append ledger |
| 工具结果不完整 | 检查 `ContentReplacement` 是否生效，确认 `replacement_id` 对应的实际内容可用 |

---

## 六、文件索引与依赖关系

```
backend/runtime/context_management/
├── __init__.py                          # 模块入口，导出所有公开 API
├── context_pipeline.py                  # 核心管线编排（四阶段）
├── context_segment_policy.py            # 消息段策略定义与映射
├── context_segment_registry.py          # 消息段 kind 注册表
├── context_capability_policy.py         # 能力过滤策略
├── physical_context_plan.py             # 物理车道规划 + 缓存脊柱
├── provider_visible_append_ledger.py    # Provider-visible current append 确认账本
├── physical_prefix_frame_ledger.py      # Provider success 后的 confirmed replay frame
├── context_candidates.py                # 上下文候选与提交数据结构
├── context_candidate_registry.py        # 候选注册器
├── context_commit_record.py             # 提交记录持久化
├── session_compaction.py                # 会话级历史压缩
├── child_result_compaction.py           # 子结果压缩
├── history_compaction.py                # 历史微压缩
├── recovery_package.py                 # 上下文恢复包
├── budget/
│   ├── __init__.py
│   └── presets.py                       # Token 预算预设
├── projection/
│   ├── __init__.py
│   └── projection.py                    # 上下文投影
├── policy/
│   ├── __init__.py
│   └── package_builder.py               # 策略包构建
├── resolution/
│   ├── __init__.py
│   └── resolver.py                      # 上下文解析器
├── compaction/
│   ├── __init__.py
│   ├── compactor.py                     # 压缩引擎（异步）
│   ├── semantic_worker.py               # 语义压缩工作器
│   ├── low_authority_text.py            # 低权威文本过滤
│   ├── microcompact.py                  # 微压缩（预算修剪）
│   ├── invariants.py                    # 压缩不变性校验
│   └── hooks.py                         # 压缩钩子
├── tool_transcript.py                   # 工具调用转录
├── tool_use_summary.py                  # 工具使用摘要
└── design_docs/                         # 设计文档（参考）
    ├── cache_provider/
    └── execution_plans/

backend/harness/runtime/
├── compiler.py                          # 编译器（调用 pipeline 的上层编排）
├── context_message_producers.py         # 消息生产者（spec → provider 消息）
├── packet_assembler.py                  # 包组装 + live_probe

backend/runtime_objects/
└── tool_result_storage.py               # 工具结果存储 + 内容替换
```

---

## 七、总结

上下文拼接系统是一个**高度结构化、确定性驱动**的构件。它的核心设计哲学是：

1. **四阶段流水线** — 每个阶段职责清晰，可独立 debug
2. **内容哈希驱动缓存** — 所有缓存决策基于消息内容的确定性 hash，而非轮次号或时间戳
3. **Ledger 持久化** — provider visible 上下文通过文件账本跨轮持久化，支持 fork 子会话继承
4. **物理车道隔离** — 缓存脊柱与可变尾部分离，保证前缀缓存稳定性
5. **压缩异步化** — 历史压缩在 turn 之间异步触发，不阻塞当前轮请求

**当前最大风险来自 ledger 写入/确认的时序间隙**（风险 1）和 **fork 继承的 hash 一致性**（风险 2）。建议在未来的迭代中引入写入确认锁或两阶段提交机制，以及 fork 继承的 fallback 策略。

---

*报告生成时间：基于代码版本 1264692a1fdb30fa02eab23624ecea38a2c878328196b3d3b4c2f4f7efcb52c2*
*覆盖模块：runtime/context_management/* + harness/runtime/compiler.py(1-900行) + harness/runtime/context_message_producers.py*
