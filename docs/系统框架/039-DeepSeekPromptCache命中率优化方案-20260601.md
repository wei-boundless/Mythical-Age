# DeepSeek Prompt Cache 命中率优化方案

日期：2026-06-01

## 1. 结论

当前项目已经做了 prompt segment plan、本地 prompt accounting 和 DeepSeek usage 采集，方向是对的；但现有设计把 `cacheable_prefix` 和 `session_stable` 一起当作 provider stable prefix 来统计和规划，导致本地“稳定前缀”口径大于 DeepSeek 实际能稳定命中的前缀口径。

DeepSeek 官方 Context Caching 文档说明：缓存默认开启，用户不需要改代码显式创建缓存；后续请求只有完整匹配已持久化的 prefix unit 时才算命中，命中状态以 `usage.prompt_cache_hit_tokens` 和 `usage.prompt_cache_miss_tokens` 为准。官方 V4 文档同时确认 `deepseek-v4-pro` 与 `deepseek-v4-flash` 支持 1M context 和 Thinking / Non-Thinking 双模式，`deepseek-chat` 与 `deepseek-reasoner` 是退役前的兼容路由。

因此优化目标不是继续加一层本地 prompt cache，而是重构上下文装配，使真实请求从第 0 token 开始具备更长、更稳定、跨轮可复用的前缀。

官方依据：

- DeepSeek Context Caching: https://api-docs.deepseek.com/guides/kv_cache
- DeepSeek V4 Preview Release: https://api-docs.deepseek.com/news/news260424

## 2. 当前测试和 ledger 证据

已执行测试：

```text
python -m pytest backend\tests\dynamic_prompt_context_projection_test.py backend\tests\graph_node_prompt_budget_regression.py backend\tests\deepseek_prompt_cache_diagnostics_test.py backend\tests\prompt_accounting_ledger_test.py -q
24 passed

python -m pytest backend\tests\model_runtime_regression.py -k "prompt_stability or stable_prefix or prompt_cache" -q
8 passed, 36 deselected
```

当前 ledger 诊断结果：

```text
provider_usage=834 local_prediction=1493 cache=1493 segment_maps=1582 stability=15
prompt=15667798 cached=5333376 miss=10334422 deepseek_hit_rate=34.04%
cache_status_counts={"bypassed":384,"eligible":450,"hit":604,"miss":55}
provider_cache_policy_modes={"automatic_prefix":1364,"unknown":129}
```

主要问题：

```text
repeated_prefix_provider_miss
volatile_metadata_inside_stable_prefix
stable_segment_content_changes
```

当前代码生成的 packet 实测：

- 同一个 `task_execution` 节点，仅 observations / execution_state 变化时，`stable_prefix_hash` 不变。
- 不同 graph node / 不同 task contract 时，`global_static` 不变，但 `task_stable`、`task_prompt_contract` 变化，整体 `stable_prefix_hash` 变化。
- `turn_action` 在同一 runtime assembly 下，用户消息和 history 变化不会改变 stable prefix。

这说明当前实现对“同节点连续执行”已经有效，但对“跨节点工作流”和“多入口模型调用”没有形成足够稳定的 provider prefix。

## 3. 代码核查结果

### 3.1 上下文装配路径

核心装配在：

- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/prompt_segment_plan.py`
- `backend/runtime/model_gateway/model_request.py`
- `backend/runtime/model_gateway/model_runtime.py`
- `backend/runtime/prompt_accounting/cache_planner.py`
- `backend/runtime/prompt_accounting/compression_budget.py`
- `backend/runtime/prompt_accounting/stability_report.py`
- `backend/scripts/diagnose_deepseek_prompt_cache.py`

`RuntimeCompiler` 当前按调用类型生成 messages：

```text
global_static           cacheable_prefix
task/turn/session段     session_stable
dynamic_projection      volatile
current_user/state      volatile
```

`prompt_segment_plan.py`、`model_request.py`、`stability_report.py` 都把 `cacheable_prefix` 与 `session_stable` 一起视为连续 stable prefix。

`cache_planner.py` 也用同一口径生成 `PromptCacheRecord.cache_key`；`compression_budget.py` 也把二者都当作不可压缩的 hard-required 段；`model_runtime.py` 会把 `model_request.stable_prefix_hash` 写入 segment metadata、local prediction diagnostics，并与 `cache_record.prefix_hash` 比较。也就是说，旧 stable prefix 口径已经同时进入请求构建、账本、压缩预算和运行时诊断，不能只改一个模块。

这是本次优化的结构性矛盾：`session_stable` 在本地语义上可能稳定，但在 DeepSeek provider cache 语义上，不一定能跨节点、跨 task、跨模型路径复用。

### 3.2 当前仍合理的部分

以下设计应保留：

- `dynamic_projection` 和 `volatile_task_state` 放在尾部。
- observations、execution_state、pending_user_steers、compressed history 不进入稳定前缀。
- graph node prompt 已避免嵌入完整 graph policy、`graph_identity`、`state_refs`、`runtime_controls`、`task_run_id` 等控制字段。
- 本地 accounting 不参与请求内容复用，只做诊断和账本记录。

### 3.3 当前不合理或不充分的部分

1. `session_stable` 语义过宽。

`task_stable`、`task_prompt_contract`、`active_skills` 可能只对当前节点稳定；把它们并入 provider stable prefix 会让整体 hash 在跨节点时频繁变化。

2. 统计口径误导。

`stable_prefix_tokens` 现在包含 `session_stable`，容易让本地报告显示“有很大稳定前缀”，但 DeepSeek 实际命中可能只复用了更短的 global prefix。

3. graph 工作流天然拆 cache。

graph node 的 prompt contract 和 node context 是不同节点的真实语义，不应该强行伪装成全局稳定。正确做法是拆分 tier，而不是把所有 stable 压成一个 prefix hash。

4. 模型切换拆 cache 池。

ledger 最近请求里同时有 `deepseek-v4-pro` 和 `deepseek-v4-flash`。如果同一 workload 在两个模型间切换，provider cache 不能期望完全共享。

5. 存在无 segment plan 的调用路径。

最近 stability report 里有 `stable_section_count=0` 但 provider cache hit 很高的记录，说明仍有模型调用没有经过当前 `RuntimeCompiler` segment plan，或者没有完整传入 accounting context。它们会污染统计口径，也让缓存问题难定位。

6. 历史 ledger 里有旧路径噪音。

诊断显示 `runtime_boundary` 曾被标成 `session_stable` 且带 volatile metadata；当前 `compiler.py` 已把 `Task execution runtime boundary` 放在 `dynamic_projection` / `volatile`，所以这部分可能是旧 ledger 残留或未迁移入口。优化前必须用当前代码生成的新 ledger 重新验证。

## 4. 目标设计

采用四层上下文装配模型：

```text
Tier 0: provider_global_prefix
只放跨 session / task / node / turn / attempt 稳定的内容。
例如 runtime pack、固定输出协议、固定 agent 角色原则、固定静态工具协议。

Tier 1: session_prefix
只放同一 session 或同一 runtime assembly 下稳定的内容。
例如 agent profile baseline、environment baseline。

Tier 2: task_or_node_prefix
只放同一 task/node 内稳定的内容。
例如 task contract、graph node role prompt、active skill bodies。

Tier 3: volatile_tail
只放本轮运行状态。
例如 runtime projection、授权摘要、observations、execution_state、history、current request、attempt 信息。
```

DeepSeek provider cache 的主优化目标是 Tier 0；同节点连续执行时可以额外受益于 Tier 1/2，但统计和测试不能把 Tier 1/2 伪装成全局缓存。

## 5. 实施方案

### 阶段一：修正缓存语义和诊断口径

目标：先让报告可信。

修改：

- 在 `prompt_segment_plan.py` 引入 `prefix_tier` 或等价 metadata：
  - `provider_global`
  - `session`
  - `task`
  - `volatile`
- 在 `model_request.py` 同时计算：
  - `provider_global_prefix_hash`
  - `session_prefix_hash`
  - `task_prefix_hash`
  - 当前字段 `stable_prefix_hash` 改为 legacy diagnostic，并明确等价于旧口径；不能再作为 DeepSeek 命中预期或 planner 主 key。
- 在 `cache_planner.py` 中迁移 `PromptCacheRecord` 生成逻辑：
  - 主 cache key 使用 `provider_global_prefix_hash`。
  - 诊断字段保留 session/task tier hash 和 token 数。
  - 不再把 task/node 段变化解释为 provider global prefix 失效。
- 在 `compression_budget.py` 中拆分 hard-required 语义：
  - `provider_global` / `session` / `task` tier 默认 preserve。
  - cache impact 必须区分 `global_invalidated`、`session_rebuilt`、`task_rebuilt`、`volatile_preserved`。
  - 压缩策略不能因为 task tier 可变而误报 provider cache 被破坏。
- 在 `model_runtime.py` 中迁移所有 `stable_prefix_hash` 消费者：
  - segment metadata 写入 prefix tier hashes。
  - local prediction diagnostics 写入 prefix tier hashes。
  - `prefix_hash_matches_model_request` 改为比较 planner 使用的 provider-global hash。
- 在 `stability_report.py` 拆分展示：
  - global prefix tokens
  - session prefix tokens
  - task/node prefix tokens
  - volatile tokens
- 在 `diagnose_deepseek_prompt_cache.py` 按模型、调用类型、prefix tier 分组输出命中率。

验收：

- 同一请求报告能明确说明：DeepSeek 理论最稳可复用的是哪段，而不是笼统 stable prefix。
- `stable_section_count=0` 或没有 `segment_plan` 的请求被单独列为 `unsegmented_model_call` 或 `utility_minimal_plan`，不混入 agent 主链路命中率。
- 旧字段 `stable_prefix_hash` 仍可读，但任何 DeepSeek cache 判断不得只依赖它。

### 阶段二：清理稳定前缀内容

目标：保证进入 Tier 0/1/2 的内容字节稳定，且不含运行态字段。

修改：

- 给 stable 段增加 linter，按字段类型区分禁止范围：

运行实例 ID 和执行态字段禁止进入 Tier 0/1/2，只能进入 volatile tail：
  - `task_run_id`
  - `graph_run_id`
  - `graph_work_order_id`
  - `work_order_id`
  - `turn_id`
  - `agent_invocation_id`
  - `runtime_assembly_id`
  - `attempt`
  - `executor_status`
  - `runtime_controls`
  - `state_refs`
  - `observations`
  - `current_facts`
  - `pending_user_steers`
  - `active_contract_revisions`

语义身份字段允许进入 task/node tier，但不得进入 provider_global/session tier：
  - `task_id`
  - `contract_id`
  - `node_id`
  - `task_contract_ref`
  - `owner_agent_seat_id`

- 审核 `_task_run_stable_payload`：普通 task execution 当前会保留 `task_run_id`、`session_id`、`graph_run_id` 等字段，这些字段不应进入 Tier 0/1/2；如确实需要给模型看，应移入 volatile projection。`task_id`、`contract_id`、`node_id` 等语义身份字段可以进入 task/node tier。
- 审核 `_environment_model_visible_payload`：`policy_hash` 使用完整 environment payload 计算，若 payload 含动态字段会造成稳定段 hash 变化；应改为只 hash model-visible normalized payload。

验收：

- 新增测试覆盖 stable 段字段黑名单。
- 同一节点不同 observations 下 Tier 0/1/2 hash 不变。
- 不同节点下 Tier 0 hash 不变，Tier 2 hash 允许变化。
- linter 能区分运行实例字段和语义身份字段，不会为了缓存删掉 agent 理解当前节点职责所需的 contract / node role 信息。

### 阶段三：统一模型调用入口

目标：agent/runtime 主链路的 DeepSeek 请求都有完整 segment plan 和 prompt manifest；utility 类直接调用要有最小 segment plan 或明确排除出主链路命中率。

修改：

- 追踪 `stable_section_count=0` 的请求来源，区分：
  - agent/runtime 主调用缺失 segment plan。
  - utility 调用，例如 title generation、history summarization、active work decision。
- agent/runtime 主调用必须通过统一 builder 生成 `ModelRequestPacket`，禁止直接绕过 `RuntimeCompiler` 或不带 `segment_plan` 调用 DeepSeek。
- 对 utility 类直接模型调用，生成最小 segment plan：
  - static/system prefix
  - volatile user request
  - call purpose metadata，例如 `utility.generate_title`、`utility.summarize_history`
- 如果某个 utility 调用没有可复用价值，应显式标记为 `utility_unsegmented`，并从 agent 主链路 cache 指标中排除。

验收：

- 新 ledger 中 agent/runtime 主调用 `segment_plan` 覆盖率达到 100%。
- utility 调用必须 100% 被归类为 `utility_minimal_plan` 或 `utility_unsegmented`。
- 诊断脚本不再把大量请求归入 `unknown` 或 `no_stable_prefix_boundary`，除非调用确实没有可复用前缀且已明确标记为 utility。

### 阶段四：减少无意义 cache 拆分

目标：让同一 workload 尽量留在同一 cache 池。

修改：

- 前端已经提供普通 / Thinking / Max 模式，后端应把 mode、model、reasoning_effort 纳入 cache report。
- 同一 task run 默认不要在 `deepseek-v4-flash` 与 `deepseek-v4-pro` 间自动切换；切换必须被记录为 cache-breaking event。
- `model_runtime.py` 当前存在 primary/fallback candidate 切换；fallback 切换要记录原始 provider/model/base_url、目标 provider/model/base_url、attempt、call_kind 和异常原因。
- request 参数也要纳入 cache report，包括 `thinking_mode`、`reasoning_effort`、`max_tokens` / `max_completion_tokens`、temperature、tool count、tool binding options、stream/non-stream。
- 对 Thinking / Max 与普通模式分别统计，不混算命中率。

验收：

- 诊断报告输出 `model + thinking_mode + reasoning_effort` 分组。
- 同一 session 的模型切换会在报告中明确提示为 cache split。
- fallback candidate 切换不再只出现在日志里，而是进入 prompt accounting ledger。

### 阶段五：基于真实运行重建基线

目标：用新账本验证优化是否有效。

执行：

- 不直接清空旧 ledger；新建 baseline run 或用 `ledger_generation` / 时间窗口隔离旧 ledger，避免历史 `runtime_boundary session_stable` 噪音污染新统计，同时保留优化前后对比数据。
- 固定模型为 `deepseek-v4-flash`，固定模式为普通或 Thinking，高频执行同一图节点和多节点图。
- 分别统计：
  - same-node repeat hit rate
  - cross-node global prefix hit rate
  - unsegmented call count
  - utility call count
  - model-switch split count

目标指标：

- 同节点连续执行：cached tokens 应显著大于 miss tokens。
- 跨节点图：至少 Tier 0 global prefix 应稳定命中；不能期望整个 task/node prefix 命中。
- agent/runtime 主链路 unsegmented DeepSeek calls 应为 0。
- utility 调用必须被单独统计，不能拉低主链路命中率。

## 6. 需要新增或调整的测试

新增 `backend/tests/prompt_cache_prefix_tier_regression.py`：

```text
test_same_task_execution_keeps_task_prefix_across_observation_updates
test_different_graph_nodes_keep_global_prefix_but_change_node_prefix
test_stable_segments_reject_runtime_identity_fields
test_model_request_reports_prefix_tiers_separately
test_unsegmented_deepseek_call_is_diagnosed
test_model_switch_is_reported_as_cache_split
test_prompt_cache_planner_uses_provider_global_prefix_key
test_compression_budget_reports_tiered_cache_impact
test_utility_model_calls_are_classified_outside_agent_cache_rate
```

调整现有测试：

- `prompt_accounting_ledger_test.py`
  - 不再断言 `cacheable_prefix_chars > assembly_prompt_chars` 这种模糊指标。
  - 改为断言 global/session/task/volatile 四类 token 统计。
  - 增加 `PromptCacheRecord.prefix_hash` 与 provider-global hash 对齐的断言。
- `model_runtime_regression.py`
  - 保留同节点 stable prefix 不变测试。
  - 增加不同节点只要求 global prefix 不变的测试。
  - 增加 primary/fallback model 切换写入 accounting diagnostics 的测试。
- `deepseek_prompt_cache_diagnostics_test.py`
  - 增加 prefix tier 分组输出。
  - 增加模型切换、无 segment plan、旧 ledger 噪音隔离场景。
- `context_compaction_budget_regression.py`
  - 增加 tiered cache impact 断言，避免压缩预算继续使用旧 stable prefix 口径。

## 7. 风险和边界

- DeepSeek cache 是 best-effort，不能保证 100% 命中；即使本地 prefix 完全一致，缓存持久化、过期、服务端路由也会影响结果。
- Graph workflow 的节点 prompt contract 本来就应该变化，不应为了缓存牺牲 agent 对当前节点职责的理解。
- 1M context 解决的是可装载上限，不等于应该把所有上下文都塞进 prompt；agent 仍应使用分层上下文、动态投影和证据引用。
- 本地 prompt cache 不应作为 provider cache 的替代品；它可以保留为诊断账本和 hash 对比工具，但不要让它参与请求内容复用或伪造命中。
- `stable_prefix_hash` 是旧口径字段，迁移期内只能作为向后可读的诊断字段。新实现必须以 tier hash 为准，否则会出现新旧统计混用。
- Utility 模型调用不一定有缓存优化价值，但必须被识别出来；否则它们会污染 DeepSeek cache 命中率，并让主 agent 链路误判。

## 8. 推荐执行顺序

1. 先实施阶段一和阶段二，修正统计语义和 stable 字段边界。
2. 再实施阶段三，统一所有 DeepSeek 调用入口。
3. 然后实施阶段四，按模型和 thinking mode 拆分报告。
4. 最后用阶段五重新跑真实任务，拿新 ledger 判断是否继续压缩 task/node prompt。

这套方案不会降低 agent prompt 的职责清晰度，也不会为了缓存把节点角色、任务契约、授权边界混在一起。目标是让“真正全局稳定的内容”稳定地出现在请求开头，让“任务/节点稳定内容”只在它自己的作用域内复用，让所有运行态内容固定留在尾部。
