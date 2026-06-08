# Prompt Provider Payload 缓存装配升级方案

日期：2026-06-09

## 结论

现有缓存体系的主要问题不是“纯聊天是否加载工具”，而是 prompt 装配权威还没有完全树立。当前代码里有资源选择、环境挂载、运行时合并、message segment plan、provider request accounting 多个局部权威；缓存只是暴露了这些权威边界不一致的问题。

目标架构必须先树立 prompt 装配体系，再处理 provider cache。第一层建立 `PromptCompositionPlan / PromptCompositionManifest`，明确哪些 prompt 来源被选择、按什么层级和生命周期进入 runtime prompt；第二层再建立 `ProviderPayloadManifest`，把最终 `messages + tools + tool binding options + provider cache policy` 统一纳入 provider-visible payload。工具 schema 不应默认 `never_cache`；稳定工具定义应成为一等缓存段，动态授权/可用性只保留为小型 volatile 或 cache-key 参数。

重要原则：prompt 自由装配是核心设计，缓存不能成为装配限制。系统必须允许通过 pack、profile、environment、personality、lifecycle、tool guidance、skill、project instruction、task contract 自由组合出不同 agent 形态。缓存层只能根据已经确定的装配结果标注生命周期和稳定性，不能为了追求命中率而删除工具、禁止动态挂载、压平 agent 形态，或把本该动态的运行事实伪装成静态。

## 外部依据

- [OpenAI Prompt Caching](https://platform.openai.com/docs/guides/prompt-caching) 要求静态内容放前、动态内容放后，并明确 messages 和 available tools 都可进入 prompt cache；usage 里通过 `prompt_tokens_details.cached_tokens` 观察命中。
- [Anthropic Prompt Caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) 把缓存层级定义为 `tools -> system -> messages`，tool definitions 可缓存，但修改工具名称、描述、参数会使后续缓存失效。
- [DeepSeek Context Caching](https://api-docs.deepseek.com/guides/kv_cache) 默认启用，命中依赖后续请求完整匹配已持久化的 prefix unit，并通过 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 回传状态。

这些规则说明成熟做法不是移除工具，而是让 provider-visible 的稳定工具定义、稳定系统提示和动态用户内容处在可解释、可复用的缓存边界中。

## DeepSeek 前缀缓存设计准则

本节作为后续 prompt/provider 装配升级的长期约束。DeepSeek 的缓存不是应用侧显式 `cache_control`，而是 provider 侧自动的磁盘 Context Caching；因此我们的重点不是给某段 prompt 打一个 provider cache 开关，而是保证 provider-visible payload 的稳定前缀可重复、可解释、可观测。

### 官方规则提炼

依据：[DeepSeek Context Caching](https://api-docs.deepseek.com/guides/kv_cache) 与 [Context Caching 发布说明](https://api-docs.deepseek.com/news/news0802)。

- Context Caching 默认启用，不要求业务侧改接口；每次请求都会触发磁盘缓存构建，后续请求如果与已缓存内容存在重复前缀，重复部分可从缓存读取。
- 当前命中规则的核心是 `cache prefix unit`：后续请求必须完整匹配一个已经持久化的 prefix unit，才能命中该单元。不能把任意中间片段重复当作有效缓存命中。
- prefix unit 的持久化来源包括三类：请求边界、系统检测到的多请求公共前缀、长输入/长输出中的固定 token 间隔。
- 2024 发布说明明确强调重复判断从第 0 token 开始；输入中间的局部重复不会触发命中。当前文档的 `A + B`、`A + C`、`A + D` 示例也体现了同一原则：公共前缀需要被持久化为独立单元后，后续完整复用才命中。
- 命中状态必须以 provider usage 为准：`prompt_cache_hit_tokens` 表示本次输入中命中的 token 数，`prompt_cache_miss_tokens` 表示未命中的 token 数。
- 磁盘缓存只影响输入前缀复用；输出仍通过推理生成，并受 `temperature` 等参数影响，不等同于输出复用。
- 缓存系统是 best-effort，不保证 100% 命中；缓存构建需要数秒，不再使用的缓存通常会在数小时到数天内清理。
- 2024 发布说明提到 64 tokens 作为存储单元、少于 64 tokens 的内容不会缓存。当前 guide 已改用 prefix unit / fixed token intervals 表述，工程上可以把 64 token 作为诊断下限和历史参考，不应把它硬编码成唯一命中规则。

### 对本项目装配体系的硬约束

- 装配顺序必须服务语义生命周期，同时满足 DeepSeek 前缀命中：`global_static -> agent_shape_stable -> environment_stable -> lifecycle_stable -> capability_stable -> task_contract_stable -> runtime_dynamic -> conversation_volatile`。动态内容只能出现在稳定前缀之后，不能插入稳定前缀中间。
- prompt 自由装配优先。pack、profile、environment、personality、lifecycle、tool guidance、skills、project instructions、task contract 仍然可以自由组合；缓存层只消费最终装配结果并标注稳定性，不能为了命中率删 prompt、藏工具、压平 agent 形态。
- 稳定前缀必须完全确定：同一 agent 形态下，section 顺序、标题、换行、序列化格式、工具 schema 排序、skill 排序、环境 prompt 排序都必须稳定。禁止把 `run_id`、时间戳、请求计数、临时许可变化、实时状态、token 压力值、观测结果写进 stable prefix。
- lifecycle prompt 可以动态选择，但一旦当前生命周期确定，就要进入固定 slot，而不是在 compiler 中临时拼接。生命周期变化导致 prefix hash 变化是正确行为；同一生命周期内无理由漂移才是问题。
- Provider-visible payload 必须一等记账：`messages`、`tools`、tool binding options、provider、model、base_url、user/cache isolation 相关字段都要进入 `ProviderPayloadManifest` 或 cache diagnostic key。DeepSeek 官方没有像 Anthropic 那样明确声明 tools 层级，但工具 schema 是模型可见输入；本项目不能继续由 serializer 事后把 `tool_schema` 硬编码为 `never_cache`。
- cache hit 诊断必须从 usage 闭环校验：内部 `stable_prefix_hash`、`provider_global_prefix_hash`、`session_prefix_hash`、`task_prefix_hash` 只能作为预测和解释；真实命中率以 DeepSeek 返回的 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 为准。
- 对 DeepSeek 的优化目标不是“每轮都满命中”，而是“同生命周期同 agent 形态下稳定前缀不漂移”。首次请求 miss、第二轮因公共前缀尚未持久化而局部 miss、缓存过期后 miss 都是合理现象；无端 stable segment 变动、工具 schema 顺序漂移、动态状态前置才是装配错误。

## 当前结构审查

### 主要链路

| 模块 | 当前职责 | 发现的问题 | 目标职责 |
|---|---|---|---|
| `backend/harness/runtime/assembly.py` | 汇总 profile、environment、permission、tools、prompt refs | 负责运行时事实装配，但 prompt 选择结果只以 refs/prompt_mount_plan 出现，没有形成完整 prompt composition plan | 继续做 runtime fact/start packet 上游，输出 prompt 选择事实，不负责 prompt 文本合并 |
| `backend/harness/runtime/environment_prompt_controller.py` | 构建 `PromptMountPlan`，选择 base/overlay/lifecycle refs | lifecycle 选择很关键，但当前只是 refs 层，和最终 stable/dynamic/cache boundary 没有一等绑定 | 成为 prompt composition 的 mount-plan 输入层，说明每个 ref 的生命周期和触发原因 |
| `backend/prompt_library/assembly.py` | `PromptAssemblyService` 从 pack/ref/resource 生成 `PromptAssemblyResult` | precedence 目前是 diagnostic-only，`PromptAssemblyResult.content` 只是按 refs 顺序 join；多层 assembly 后又在 compiler 里手工 merge | 升级为 prompt section assembly 权威，输出可验证的 section graph/order/cache scope |
| `backend/prompt_library/manifest.py` | `RuntimePromptManifest` 记录稳定 refs、动态 refs、cache boundary 概况 | manifest 粒度偏统计，不足以作为完整装配权威；不能描述 section slot、layer、message target、provider payload 关系 | 升级或被 `PromptCompositionManifest` 接管，作为 runtime prompt 装配账本 |
| `backend/prompting/*` | 旧式 prompt builder/cache/manifest | 与 `prompt_library` 并行存在，可能保留旧 prompt cache 观念和旧静态装配顺序 | 审查后删除或隔离到 legacy，不参与新 runtime 主链路 |
| `backend/harness/runtime/compiler.py` | 构建 `RuntimeInvocationPacket.model_messages`、`segment_plan`、`available_tools`、`prompt_manifest` | `segment_plan` 只规划 message；`available_tools` 进入 packet 但没有 provider payload 缓存段 | 继续负责语义 prompt 和可见工具边界，但输出 tool cache hint / tool boundary refs |
| `backend/harness/runtime/prompt_segment_plan.py` | 为 messages 生成 cache role、prefix tier、stable hash | dataclass 强绑定 `model_message_index`，没有 `transport_location=tools` 之类的 payload 位置 | 升级为支持 provider payload segment，或保留 message plan 并让新 manifest 接管完整 payload |
| `backend/runtime/model_gateway/model_request.py` | 规范化 messages/tools，绑定 segment plan，计算 stable prefix hash | bindings 只来自 message index；工具虽然 canonicalized/sorted，但不进入 prefix hash | 成为 provider-visible payload manifest 的装配权威 |
| `backend/runtime/prompt_accounting/serializer.py` | 从 model request 生成账本 `PromptSegmentMap` | 对 tools 事后追加 `kind=tool_schema` 且硬编码 `cache_role=never_cache` | 只序列化 manifest 已裁决的 payload segment，不再自行决定 tool cache role |
| `backend/runtime/prompt_accounting/cache_planner.py` | 根据 stable prefix segments 生成 cache record/key | 只按线性 segment 顺序遇 volatile 截断；cache key 不包含 tool schema hash / cache-sensitive params | 从 provider payload manifest 的 cache boundary 生成 key 和诊断 |
| `backend/runtime/prompt_accounting/cache_baseline.py` | 跨轮追踪 stable/session/task hash | 只跟踪 message-derived prefix；工具变化不会进入 baseline changed tiers | 增加 tool catalog / provider payload hash tier |
| `backend/runtime/prompt_accounting/stability_report.py` | 稳定性报告 | `tools_hash` 只在 dynamic summary 中记录，不参与 prefix 或 key | 报告 tool catalog hash、tool change reason、payload boundary |
| `backend/runtime/prompt_accounting/cache_break_detector.py` | 识别 repeated prefix miss | 只能识别重复 cache_key miss，不能解释 tool/schema/param/order 变化 | 分类解释 tool schema changed、tool count changed、binding options changed、provider param changed、unplanned call |
| `backend/runtime/model_gateway/model_runtime.py` | 调用 provider 前后做 accounting | `_begin_prompt_accounting()` 同时做 context normalization、model request、segment map、cache record、baseline，权威过多 | 调用 manifest builder，accounting 只记录 manifest 裁决和 provider usage |

### 实测账本信号

最近一次全局诊断：

- `unplanned_model_call`: 70 个。
- `repeated_prefix_provider_miss`: 8 组。
- `stable_segment_content_changes`: 8 类 stable segment 变化。
- 全局 DeepSeek cache hit rate：`0.6210`。
- `agent_runtime` hit rate：`0.6513`。
- `memory_maintenance` hit rate：`0.1205`。
- 当前会话 `session-1bbe0b7b504f436d` 最近单轮请求：`prompt_tokens=33598`，`cached_tokens=15616`，hit rate `0.4648`。

这说明主聊天链路已有部分命中，但缓存解释力不够；utility / memory maintenance 和工具 payload 边界是需要治理的主要区域。

## 目标架构

新增两个不与现有 `prompt_manifest` / `segment_plan` 重名的核心对象：

```text
PromptCompositionPlan
  -> PromptCompositionSlot[]
  -> PromptCompositionManifest
  -> RuntimeInvocationPacket

ProviderPayloadManifest
  -> ProviderPayloadSegment[]
  -> ProviderPayloadCacheBoundary
  -> ProviderPayloadCacheDiagnostics
```

命名意图：

- `PromptCompositionPlan` 描述 prompt 如何被选中、分层、排序和放入 runtime 输入。
- `PromptCompositionManifest` 描述实际装配后的 prompt section、生命周期、stable/dynamic 边界和审计信息。
- `ProviderPayloadManifest` 描述 provider 实际可见 payload，不是 runtime prompt 文本清单，也不是纯 message segment plan。

### Prompt 装配主链

```text
RuntimeAssembly facts
  -> PromptMountPlan
  -> PromptCompositionPlan
  -> PromptAssemblyService
  -> PromptCompositionManifest
  -> RuntimeCompiler message slots
  -> RuntimeInvocationPacket
```

每层只做一类决定：

| 层 | 决定内容 | 禁止内容 |
|---|---|---|
| `RuntimeAssembly facts` | profile、environment、permission、tool visibility、selected skills、runtime contract | 不拼 prompt 文本 |
| `PromptMountPlan` | base/overlay/lifecycle/personality prompt refs 选择 | 不把 refs 直接当最终顺序和 cache boundary |
| `PromptCompositionPlan` | prompt slots、layer precedence、slot target、cache class、lifecycle trigger | 不调用 provider，不估算 provider cache |
| `PromptAssemblyService` | 从 registry 读取 active resource 并渲染 section | 不自行改变 runtime action 权限 |
| `PromptCompositionManifest` | 记录实际 section graph、hash、slot、stable/dynamic 边界 | 不追加 provider-only tools schema |
| `RuntimeCompiler` | 把 composition manifest 映射成 model messages 和 runtime dynamic projection | 不重新选择 prompt refs |

成熟边界：cache 只能消费 `PromptCompositionManifest` 和 `ProviderPayloadManifest`，不能反过来决定 prompt 内容。

### 动态 / 静态分层原则

动态和静态不是为了缓存硬切，而是按语义生命周期切：

| 层级 | 生命周期 | 示例 | cache 处理 |
|---|---|---|---|
| `global_static` | 版本发布级稳定 | 全局安全边界、通用 runtime protocol、固定输出协议 | 可作为 provider/global stable prefix |
| `agent_shape_stable` | agent 形态级稳定 | agent role、personality、默认 planning/tool/memory policy | session 或 profile stable；agent 形态变化时自然换 hash |
| `environment_stable` | 环境选择级稳定 | workspace/environment rules、base/overlay environment prompts | session/task stable；环境切换时换 hash |
| `lifecycle_stable` | 当前运行生命周期稳定 | 当前阶段需要的 lifecycle prompt：tool dispatch、memory read、compaction handoff | 由 trigger reason 决定，可稳定但不能强制常驻 |
| `capability_stable` | 可见能力集合稳定 | tool guidance、skill cards、available tool schema catalog | 随可见工具/skill 集合变化；不能为缓存隐藏工具 |
| `task_contract_stable` | 当前任务/合同稳定 | task contract、graph node contract、definition of done | task stable；合同修订时换 hash |
| `runtime_dynamic` | 每轮运行事实 | active work、pending steer、permission delta、observations、memory recall result | volatile 或 key-only |
| `conversation_volatile` | 对话自然变化 | session history、provider transcript、current user request | volatile，可压缩但不伪装稳定 |

规则：

- 先按 agent 需要自由装配 prompt，再给每个 slot 标注生命周期。
- 不确定是否稳定时，宁可标为 `volatile` 或 `key_only_dynamic`，不要牺牲正常运行。
- 缓存命中率低只能说明需要优化装配边界、排序或稳定字段，不能作为移除 prompt/tool 的理由。
- 动态 slot 可以继续存在；优化方向是把动态内容放在稳定内容之后，并记录变化原因。
- agent 形态变化、环境变化、工具集合变化、权限变化都应自然改变 hash，这是正确行为，不是缓存失败。

### 权威链

```text
RuntimeCompiler
  -> RuntimeInvocationPacket(messages, available_tools, prompt_composition_manifest, segment_plan, tool_boundary_hint)
  -> ModelRequestBuilder
  -> ProviderPayloadManifest
  -> PromptAccountingSerializer
  -> PromptCachePlanner
  -> Provider Adapter
  -> PromptCacheBreakDetector / StabilityReporter
```

职责边界：

- `RuntimeCompiler`：只决定 agent 语义输入、可见工具集合、运行边界。它可以给工具段提供 `cache_scope_hint`，但不直接计算 provider 传输 payload hash。
- `PromptCompositionPlan / Manifest`：先于 provider cache 存在，是 prompt 装配的唯一账本；所有 stable/dynamic/cache scope 都从这里进入后续 message segment plan。
- `ModelRequestBuilder`：唯一负责把最终 `messages`、`tools`、`tool_call_options`、provider/model/base_url/cache policy 规范化成 provider-visible payload manifest。
- `CanonicalPromptSerializer`：只把 manifest 落账，不再自行推断 tools 是不是 `never_cache`。
- `PromptCachePlanner`：只根据 manifest 的 cache boundary 生成 cache record/key，不再重新解释 payload 结构。
- `PromptCacheBreakDetector`：只做诊断归因，不改变缓存裁决。

## ProviderPayloadSegment 设计

建议字段：

```python
ProviderPayloadSegment(
    segment_id: str,
    kind: str,
    ordinal: int,
    transport_location: Literal[
        "tools",
        "tool_call_options",
        "messages",
        "response_format",
        "request_params",
    ],
    model_message_index: int | None,
    cache_scope: Literal["global", "session", "task", "none"],
    cache_role: Literal["cacheable_prefix", "session_stable", "volatile", "never_cache"],
    prefix_tier: Literal["provider_global", "session", "task", "volatile", "none"],
    content_hash: str,
    predicted_tokens: int,
    authority_class: str,
    source_ref: str,
    metadata: dict,
)
```

首批 segment：

| kind | transport_location | cache_role | 说明 |
|---|---|---|---|
| `tool_schema_catalog` | `tools` | `session_stable` 默认，满足纯全局条件时可 `cacheable_prefix` | 规范化后的工具 name/description/schema，排序稳定 |
| `tool_authorization_delta` | `tool_call_options` 或 metadata | `volatile` 或 key-only | 动态 tool_choice、strict、parallel_tool_calls、权限 profile hash |
| `provider_params` | `request_params` | key-only / `never_cache` | provider、model、base_url、thinking/reasoning、temperature、retention 等影响 cache 路由或命中解释的参数 |
| `message:*` | `messages` | 沿用现有 plan | 当前 messages 的 stable/volatile 段 |

注意：tool schema 是 provider-visible payload 的稳定内容；权限、审批状态、运行时 ID 不是工具定义，不能混入 stable tool schema。

## Tool Schema 稳定化规则

1. 工具按 `name` 排序。
2. 只保留 provider 实际发送的 name、description、schema、strict 兼容字段。
3. schema 用稳定 JSON：key 排序、去除非语义运行时字段。
4. 禁止把 `turn_id`、`task_run_id`、`request_id`、审批状态、临时 cwd 状态写进 stable tool schema。
5. 如果工具说明确实依赖 environment 或 permission profile，则降级为 `session_stable` 或 `task`，并记录 `tool_cache_scope_reason`。
6. 任何 tool count/name/schema/hash 变化都必须在 stability report 中可见。

## Cache Key 规则

现有 cache key 只包含 provider、model、prefix_hash、boundary segment。升级后改为：

```text
provider_payload_prefix_key = hash(
  provider,
  model,
  cache_relevant_base_url,
  provider_cache_policy.mode,
  prompt_cache_key_or_route_key,
  prefix_key_tier,
  provider_payload_prefix_hash,
  tool_catalog_hash,
  cache_sensitive_params_hash
)
```

说明：

- `provider_payload_prefix_hash` 应包含 tool schema catalog 与 stable message prefix。
- `cache_sensitive_params_hash` 包含 tool binding options、thinking mode、reasoning effort、temperature、response_format/structured output、prompt cache retention/key 等会影响 provider cache 命中的参数。
- 这些参数不一定都算“prefix tokens”，但必须进入本地 cache key 或诊断，否则会出现“本地以为同 prefix，provider 实际不同请求”的假阳性。

## 实施阶段

### 阶段 0：树立 PromptCompositionPlan / PromptCompositionManifest

改动文件：

- `backend/harness/runtime/assembly.py`
- `backend/harness/runtime/environment_prompt_controller.py`
- `backend/prompt_library/assembly.py`
- `backend/prompt_library/manifest.py`
- `backend/harness/runtime/compiler.py`
- `backend/prompting/*`
- `backend/tests/prompt_library_registry_regression.py`
- `backend/tests/prompt_rule_system_regression.py`
- `backend/tests/dynamic_prompt_context_projection_test.py`

工作：

- 新增 `PromptCompositionPlan` / `PromptCompositionManifest`，不要复用现有 `prompt_manifest` 名称。
- `RuntimeAssembly` 只输出 prompt 选择事实：profile refs、environment refs、tool visibility、selected skill ids、permission/environment facts。
- `PromptMountPlan` 只负责 base/overlay/lifecycle/personality refs 和 trigger reason。
- `PromptCompositionPlan` 统一声明 slot：
  - `global_static`
  - `agent_shape_stable`
  - `personality_stable`
  - `environment_stable`
  - `environment_base_stable`
  - `environment_overlay_stable`
  - `lifecycle_stable`
  - `capability_stable`
  - `agent_stable`
  - `skill_stable`
  - `project_instruction_stable`
  - `tool_guidance_stable`
  - `task_contract_stable`
  - `runtime_dynamic`
  - `history_volatile`
  - `current_user_volatile`
- `PromptAssemblyService` 输出 section graph/order/hash/cache_scope，而不是只返回 content join。
- `RuntimeCompiler` 从 composition manifest 映射 message specs；禁止在 compiler 内重新决定 prompt refs。
- 审查 `backend/prompting/*`，不属于新 runtime 主链路的旧 prompt builder/cache 逻辑列入删除或 legacy 隔离。

验收：

- 单轮聊天、task_execution、tool_observation_followup 都能输出 `prompt_composition_manifest_ref`。
- 每个 model message segment 都能追溯到 composition slot 或 runtime dynamic source。
- prompt precedence 不再只是 diagnostic；最终 section order 可解释、可测试。
- 没有新的 prompt refs 在 `RuntimeCompiler` 中被临时拼接或静默兜底。
- 改变 agent prompt refs、environment prompt refs、skill refs、tool visibility 时，系统能自由生成新 agent 形态，同时 manifest/hash 正确变化。
- cache 诊断只能报告变化原因，不能阻止 prompt 动态装配。

### 阶段 1：引入 ProviderPayloadManifest，不改变 provider 调用行为

改动文件：

- `backend/runtime/model_gateway/model_request.py`
- `backend/runtime/prompt_accounting/serializer.py`
- `backend/runtime/prompt_accounting/models.py`
- `backend/runtime/model_gateway/model_runtime.py`

工作：

- 新增 `ProviderPayloadSegment` / `ProviderPayloadManifest` dataclass。
- `ModelRequestBuilder.build()` 在 normalized messages/tools 之后，基于 `PromptCompositionManifest` 和 `segment_plan` 生成 manifest。
- tool schema segment 先默认 `session_stable`；无法保证稳定的字段以 diagnostics 标出。
- `ModelRequestPacket` 增加 `provider_payload_manifest`。
- serializer 从 manifest 生成 segment map；保留原 message binding 结果，但删除 tool_schema 硬编码 `never_cache` 的决策权。

验收：

- 带工具请求的 segment map 中存在 `kind=tool_schema_catalog`，且不是 `never_cache`。
- tool schema hash 连续两轮稳定。
- 没有改变实际 `bind_tools()` 输入。

### 阶段 2：缓存 planner / baseline 接入 provider payload boundary

改动文件：

- `backend/runtime/prompt_accounting/cache_planner.py`
- `backend/runtime/prompt_accounting/cache_baseline.py`
- `backend/runtime/prompt_accounting/stability_report.py`
- `backend/runtime/model_gateway/provider_cache_policy.py`

工作：

- cache planner 用 manifest boundary 计算 `provider_payload_prefix_hash`。
- cache key 加入 `tool_catalog_hash` 与 `cache_sensitive_params_hash`。
- baseline 增加 `tool_catalog_hash`、`provider_payload_prefix_hash`。
- stability report 输出 tool diff、cache-sensitive param diff。
- provider cache policy 扩展为声明哪些 request params 进入 cache key / diagnostics。

验收：

- 两轮相同工具 + 相同 stable messages 的请求拥有相同 provider payload prefix hash。
- 修改一个 tool schema 字段会改变 tool catalog hash，并在 break/stability report 里归因。
- 修改 user message 不改变 tool catalog hash。

### 阶段 3：治理 unplanned model call 与 utility prompt cache

改动文件：

- `backend/runtime/model_gateway/model_runtime.py`
- 触发 utility 调用的 memory / title / directive 相关入口。
- `backend/tests/model_runtime_regression.py`
- `backend/tests/memory_maintenance_agent_regression.py`

工作：

- utility 调用必须明确 `cache_metric_scope`、`call_purpose`、minimal segment plan 或 provider payload manifest。
- 对 memory maintenance 的 stable prefix 单独清理，避免 prompt 内混入动态时间、请求 ID、随机标题等。
- `unplanned_model_call` 不能再作为“正常降级”，只允许作为诊断失败路径。

验收：

- 全局诊断 `unplanned_model_call` 不再新增。
- memory_maintenance 连续同类请求的 prefix hash 稳定，hit rate 明显高于当前 `0.1205`。

### 阶段 4：缓存诊断打磨

改动文件：

- `backend/runtime/prompt_accounting/cache_break_detector.py`
- `backend/scripts/diagnose_deepseek_prompt_cache.py`
- `backend/tests/deepseek_prompt_cache_diagnostics_test.py`

新增诊断 reason：

- `tool_schema_hash_changed`
- `tool_count_changed`
- `tool_binding_options_changed`
- `cache_sensitive_params_changed`
- `provider_payload_prefix_changed`
- `stable_message_prefix_changed`
- `stable_prefix_broken_by_volatile_segment`
- `provider_reported_miss_for_repeated_provider_payload_prefix`

验收：

- repeated miss 不再只有泛化原因，能指出工具、参数、message prefix 或 provider best-effort。
- 诊断 JSON 中保留旧指标但新增 provider payload 指标。

## 测试计划

新增或更新：

- `backend/tests/model_runtime_regression.py`
  - tool schema segment 由 manifest 生成，cache_role 非 `never_cache`。
  - model request canonical hash、provider payload prefix hash 连续请求稳定。
  - tool schema 修改导致 tool catalog hash 改变。
- `backend/tests/prompt_cache_prefix_tier_regression.py`
  - provider payload prefix tier 包含 tools + stable messages。
  - volatile user 不破坏 tool schema hash。
- `backend/tests/deepseek_prompt_cache_diagnostics_test.py`
  - repeated provider miss 能归因到 provider payload / tool / params。
- `backend/tests/harness_single_agent_tool_runtime_regression.py`
  - 单轮聊天保留工具可见性，仍可从普通聊天转入工具调用。
- `backend/tests/memory_maintenance_agent_regression.py`
  - memory maintenance utility call 不再 unplanned，并有稳定缓存边界。

建议验证命令：

```powershell
python -m pytest backend\tests\model_runtime_regression.py -q
python -m pytest backend\tests\deepseek_prompt_cache_diagnostics_test.py -q
python -m pytest backend\tests\harness_single_agent_tool_runtime_regression.py -q
python backend\scripts\diagnose_deepseek_prompt_cache.py --limit 8 --json
```

如果实施触及前后端运行链路或会话接口，再按项目固定端口启动：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8003
npm run dev -- --hostname 127.0.0.1 --port 3000
```

## 清理标准

必须删除或替换：

- `serializer.py` 中工具 schema 固定 `never_cache` 的决策逻辑。
- `ModelRequestBuilder` 只按 message binding 计算 stable prefix 的旧入口，改为 provider payload manifest 主导。
- 对 unplanned model call 的静默正常化，只保留带 severity 的诊断记录。
- 任何重复计算 tool schema hash / prefix hash 的散落逻辑。

允许短期保留：

- 旧 `segment_plan` 作为 message plan，前提是新 `ProviderPayloadManifest` 是 cache planner 的唯一权威。
- 旧 `RuntimePromptManifest` 只能作为历史账本或被 `PromptCompositionManifest` 替代；不能继续作为分散的 prompt 装配权威。
- 旧账本字段，用于历史记录读取；但新请求必须写入 provider payload 字段。

## 风险和边界

- 不改变工具真实可见性，不通过“聊天不带工具”来换速度。
- 不改变 provider 调用参数，第一阶段只改变 accounting/manifest。
- 不把权限状态混进 stable tool schema，避免缓存命中建立在过期授权上。
- DeepSeek 的缓存是 best-effort，不能保证每次命中；本地目标是消除可控 miss 和误诊断。

## 待确认决策

建议采用 `PromptCompositionPlan / PromptCompositionManifest + ProviderPayloadManifest` 两层方案，并按五阶段实施。确认后从阶段 0 开始改代码，先把 prompt 装配体系树立起来，再把 tool schema 从 `never_cache` 升级为稳定 provider payload segment，最后接 cache planner 和诊断。
