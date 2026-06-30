# Prompt Accounting Ledger Layering Optimization Plan

创建日期：2026-06-30

## 目标

把 `prompt_accounting` 运行账本从“多个相似 JSONL 平铺记录”重构为层次明确、单向流动、前端只读总线投影的结构。

本计划只优化账本结构和读写权责，不改变四段式物理上下文模型：

```text
global_static_prefix
-> provider_visible_context_prefix
-> current_turn_tail
-> never_replay_tail
```

重构后，缓存命中诊断必须只通过 provider cache bus 给出当前裁决；底层事实账本和分析账本不能再被前端或 API 展示层重新解释。

## 当前审查结论

### 1. 当前文件不是完全重复，但层次混乱

当前同一小时目录下存在：

```text
prompt_cache_baselines.jsonl
prompt_cache.jsonl
prompt_stability.jsonl
provider_cache_ledger.jsonl
segment_maps.jsonl
segments.jsonl
token_usage.jsonl
```

这些文件混合了四类职责：

| 文件 | 当前职责 | 问题 |
| --- | --- | --- |
| `segments.jsonl` | 每个 prompt segment 的明细行 | 与 `segment_maps.jsonl` 内嵌 segments 物理重复 |
| `segment_maps.jsonl` | 每次请求的完整 prompt segment map | 名字偏底层，实际是 prompt manifest |
| `token_usage.jsonl` | local prediction 和 provider usage | 同一 request 两条记录，phase 只能靠 `source` 理解 |
| `prompt_cache.jsonl` | 请求前 cache plan 和 provider 回填后的 cache result | 同一旧 cache record identity 双写，容易被误读为重复命中 |
| `prompt_cache_baselines.jsonl` | 跨请求 prefix baseline | 与 stability hash 信息重叠 |
| `prompt_stability.jsonl` | prefix 稳定性、stable/volatile sections、provider usage 回填 | 同一 report 双写，且与 baseline 重叠 |
| `provider_cache_ledger.jsonl` | provider cache 展示/诊断投影 | 应是 UI 权威，但命名仍像底层账本 |

最新会话 `session-e694517fab574639` 的实测形态：

| 文件 | 行数 | 同 request 多记录组 |
| --- | ---: | ---: |
| `segments.jsonl` | 117 | 5 |
| `segment_maps.jsonl` | 5 | 0 |
| `token_usage.jsonl` | 10 | 5 |
| `prompt_cache.jsonl` | 10 | 5 |
| `prompt_cache_baselines.jsonl` | 5 | 0 |
| `prompt_stability.jsonl` | 10 | 5 |
| `provider_cache_ledger.jsonl` | 5 | 0 |

### 2. 重构前双写来自 preflight 和 provider result 两阶段

重构前，`backend/runtime/model_gateway/model_runtime.py` 在请求前写：

- `ledger.record_segment_map(segment_map)`
- `ledger.record_token_usage(prediction)`
- 旧 cache plan 写入入口
- `ledger.record_prompt_stability(stability_report)`
- `ledger.record_prompt_cache_baseline(baseline_record)`

provider 返回后又写：

- `ledger.record_token_usage(provider_usage)`
- 旧 provider cache result 回填入口
- `publish_provider_cache_usage(...)`
- `ledger.record_prompt_stability(updated_stability_report)`

这个流程本身合理：一个阶段是本地预测和组装事实，另一个阶段是 provider 实测。但重构前它们写入同名文件，造成“记录相互覆盖语义但没有覆盖物理行”的观感。

当前实现已经改为：

- preflight 写 `record_segment_map(...)`、`record_token_usage(...)`、`record_cache_plan(...)`、`record_prefix_state(...)`。
- provider result 写 `record_token_usage(...)`、`publish_provider_cache_usage(...)`，异常时写 `record_cache_anomaly(...)`。
- provider usage 不再回填 `cache_plans.jsonl`。
- provider cache bus 记录从 `ProviderPayloadSegment` 继承 `context_contract_node_ref`、`agent_domain`、`connection_contract_ref`、`control_signal`；under-read 断点可回指 ContextContract。

### 3. 展示链路已经接近正确，但 summary 仍会误导

`backend/api/tokens.py` 已经通过 `build_provider_cache_log_view(...)` 输出 `provider_cache_log`。

`frontend/src/components/chat/ChatPanel.tsx` 已经读取 `tokenStats.provider_cache_log`，但当前报警逻辑在 latest 已经 covered 时，仍会用最近 50 条 summary 的历史 under-read 报警。这会把“历史曾经 under-read”显示成“当前仍不稳定”。

### 4. `segments.jsonl` 是最明显的重复账本

`PromptSegmentMap.to_dict()` 已经把全部 `segments` 嵌入 `segment_maps.jsonl`。同时 `record_segment_map()` 又逐条写 `segments.jsonl`。

代码搜索显示当前主消费者主要是：

- `api.sessions._latest_prompt_manifest_summary()` 读取 `list_segment_maps(...)`
- prompt accounting 内部可列出 `list_segments(...)`，但没有明确高价值外部消费者

所以 `segments.jsonl` 应降级为可重建索引，不能继续和 manifest 平级作为主账本。

## 目标结构

目标不是简单减少文件数量，而是让每个文件只属于一个层级、一个权责、一个消费方向。

```text
runtime/model request
  -> prompt_manifest
  -> local_accounting_plan
  -> provider_observation
  -> prefix_state
  -> provider_cache_bus
  -> api/frontend
```

### 目标账本

| 目标文件 | 层级 | 来源 | 权责 | 替代旧文件 |
| --- | --- | --- | --- | --- |
| `prompt_manifests.jsonl` | 组装事实层 | provider payload / segment map | 记录每次请求实际发送前的 segment manifest，内嵌 segment 列表 | `segment_maps.jsonl` |
| `token_observations.jsonl` | 原始观测层 | local prediction / provider usage | 记录 token 预测和 provider 实测，必须有 `phase` | `token_usage.jsonl` |
| `cache_plans.jsonl` | 本地计划层 | cache planner | 记录本地选定的 cache boundary、prefix hash、safety reasons，一次请求只写一次 | `prompt_cache.jsonl` 的 preflight 部分 |
| `prefix_state.jsonl` | prefix 状态层 | PrefixStateReporter + PrefixStateDiffReporter | 合并原 baseline、diff、changed sections、continuity，一次请求只写一次 state record | `prompt_cache_baselines.jsonl` + `prompt_stability.jsonl` |
| `provider_cache_bus.jsonl` | 展示总线层 | provider usage + cache plan + prefix health + ContextContract refs | 记录 provider cache 当前裁决，API/frontend 唯一读取源，缓存断点必须能定位到 agent_domain/contract node | `provider_cache_ledger.jsonl` |
| `cache_anomalies.jsonl` | 异常层 | cache anomaly detector / bus | 只记录异常事件，不参与正常展示汇总 | 原生异常事件账本 |

### 不再保留为主账本

| 旧文件 | 处理 |
| --- | --- |
| `segments.jsonl` | 删除主写入；如需要调试 segment 级检索，由 `prompt_manifests.jsonl` 派生临时视图，不再持久平级写入 |
| `segment_maps.jsonl` | 重命名为 `prompt_manifests.jsonl` |
| `prompt_cache.jsonl` | 拆为 `cache_plans.jsonl` 和 `provider_cache_bus.jsonl`，不再双写同一 record |
| `prompt_stability.jsonl` | 合并进 `prefix_state.jsonl` |
| `prompt_cache_baselines.jsonl` | 合并进 `prefix_state.jsonl` |
| `provider_cache_ledger.jsonl` | 重命名为 `provider_cache_bus.jsonl` |
| `token_usage.jsonl` | 重命名为 `token_observations.jsonl`，显式 `phase` |

## 权责边界

### 写入权责

| 模块 | 目标职责 | 禁止事项 |
| --- | --- | --- |
| `model_runtime.py` | 只协调两次提交：`record_preflight_accounting()` 和 `record_provider_result_accounting()` | 禁止直接散落调用 5-8 个 `ledger.record_*` |
| `ledger.py` | 只负责 append、list、retention、prune，不判断 cache 是否命中 | 禁止在 ledger 内重算 prefix/cache 裁决 |
| `cache_planner.py` | 只生成 local cache plan | 禁止写 provider hit/miss 结论 |
| `prefix_state.py` | 唯一拥有 prefix continuity/generation/reset | 禁止 baseline 与 diff 分散成第二状态权威 |
| `provider_cache_bus.py` | 唯一发布 provider cache 展示裁决 | 禁止前端/API 直接读 `cache_plans` 或 `token_observations` 重算命中 |

### 读取权责

| 消费者 | 允许读取 |
| --- | --- |
| 前端缓存状态 | 只读 `provider_cache_bus` API 投影 |
| `/api/tokens/session/{session_id}` | `token_observations` + `provider_cache_bus` + context snapshot |
| prompt manifest summary | `prompt_manifests` |
| compaction/context meter | `token_observations` |
| cache/prefix 内部分析 | `cache_plans` + `prefix_state` |

## 文件级改造计划

### Phase 1：建立账本通道定义，不改变业务语义

目标：先消除硬编码文件名和平铺认知。

修改：

- `backend/runtime/prompt_accounting/ledger.py`
  - 新增账本通道定义，例如 `LedgerChannel` / `PromptAccountingFileSpec`。
  - 用通道常量替换散落的字符串文件名。
  - 标记每个通道的 `layer`、`phase`、`retention_policy`、`public_surface`。
- `backend/runtime/prompt_accounting/models.py`
  - 为 `ModelTokenUsageRecord` 引入显式 `phase`，取值至少包括 `local_prediction`、`provider_usage`。
  - 保留 `source` 的含义，但不再让 `source` 承担文件层级解释。

验收：

- 搜索不到新增硬编码旧文件名。
- `ledger.py` 中所有 append/list/retention/prune 都通过通道定义寻址。

### Phase 2：删除 `segments.jsonl` 主写入，确立 manifest 权威

目标：让 prompt 组装事实只有一个主账本。

修改：

- `backend/runtime/prompt_accounting/ledger.py`
  - `record_segment_map()` 只写 `prompt_manifests.jsonl`。
  - 删除或降级 `record_segment()`。
  - `list_segments()` 如确有内部需要，改为从 `prompt_manifests` 派生，不再读持久 `segments.jsonl`。
- `backend/api/sessions.py`
  - `_latest_prompt_manifest_summary()` 改读 `list_prompt_manifests(...)`。

清理：

- 删除新写入路径中的 `segments.jsonl`。
- 不新增运行时双读兼容；旧热目录文件只作为历史残留，不参与新代码读取。

验收：

- 新请求不再生成 `segments.jsonl`。
- latest manifest summary 仍返回 `request_id`、`segment_count`、`predicted_prompt_tokens`。

### Phase 3：拆分 preflight plan 和 provider result

目标：消除 `token_usage.jsonl`、`prompt_cache.jsonl`、`prompt_stability.jsonl` 的同 request 双写歧义。

修改：

- `backend/runtime/model_gateway/model_runtime.py`
  - 引入两个清晰入口：
    - `record_preflight_accounting(...)`
    - `record_provider_result_accounting(...)`
  - preflight 只写：
    - `prompt_manifests`
    - `token_observations` with `phase=local_prediction`
    - `cache_plans`
    - `prefix_state` local state
  - provider result 只写：
    - `token_observations` with `phase=provider_usage`
    - `provider_cache_bus`
    - `cache_anomalies` when needed
- `backend/runtime/prompt_accounting/cache_planner.py`
  - `with_provider_usage(...)` 不再写回 `cache_plans` 同一记录。
  - provider usage 相关诊断交给 `provider_cache_bus`。

验收：

- 每个 request 在 `cache_plans` 中最多一条。
- 每个 request 在 `prefix_state` 中最多一条。
- 每个 provider response 在 `provider_cache_bus` 中最多一条。

### Phase 4：合并 baseline 和 stability 为 `prefix_state`

目标：prefix continuity 只由一个状态账本表达。

修改：

- 新增或重写 `backend/runtime/prompt_accounting/prefix_state.py`。
- 合并现有：
  - `cache_baseline.py`
  - `prefix_state_diff.py`
  - `prefix_state_diff_models.py`
- `PrefixStateRecord` 必须包含：
  - `request_id`
  - `provider`
  - `model`
  - `provider_lane`
  - `physical_payload_family_hash`
  - `previous_state_ref`
  - `generation`
  - `provider_payload_prefix_hash`
  - `global_static_prefix_hash`
  - `provider_visible_context_prefix_hash`
  - `current_turn_tail_hash`
  - `never_replay_tail_hash`
  - `changed_tiers`
  - `changed_sections`
  - `first_changed_section`
  - `stable_token_count`
  - `volatile_token_count`
  - `provider_cache_read_expectation_summary`

删除：

- 新代码不再写 `prompt_cache_baselines.jsonl`。
- 新代码不再写 `prompt_stability.jsonl`。

验收：

- prefix 连续性查询只走 `prefix_state`。
- 不再存在 baseline/stability 双 authority。

### Phase 5：把 provider cache bus 变成展示唯一权威

目标：解决“总命中率”和“历史 under-read”误导当前状态的问题。

修改：

- `backend/runtime/prompt_accounting/provider_cache_bus.py`
  - 输出字段拆分：
    - `latest_status`
    - `latest_prefix_health`
    - `current_context_contract_node_refs`
    - `current_agent_domains`
    - `current_connection_contract_refs`
    - `latest_under_read_tokens`
    - `warm_provider_under_read_tokens`
    - `cold_start_under_read_tokens`
    - `history_under_read_tokens`
    - `current_prefix_covered`
    - `current_cache_spine_hash`
    - `current_transport_contract_hash`
  - summary 不再把 cold start 的 under-read 和 warm under-read 混成一个字段。
- `backend/api/tokens.py`
  - `provider_cache_log` 只从 bus view 输出。
  - `cache_metrics` 可以保留 billing/context 指标，但不能成为 prefix 命中裁决来源。
- `frontend/src/components/chat/ChatPanel.tsx`
  - 当前报警只看 latest：
    - `latest_status === provider_under_read`
    - `latest_prefix_health.verdict === provider_under_read`
    - `latest_under_read_tokens > 0`
  - 历史 under-read 只显示为历史提示，不改变当前压力条状态。

验收：

- latest 两条 provider cache hit 时，前端不再显示当前 under-read 报警。
- 历史 cold start 不再污染当前前缀命中状态。

### Phase 6：retention/prune/summary 统一走新通道

目标：清理旧链路，不做长期兼容。

修改：

- `backend/runtime/prompt_accounting/ledger.py`
  - `RETENTION_DETAIL_FILES` 和 `TIME_BUCKETED_DETAIL_FILES` 改为通道列表。
  - `prune_task_runs()` / `prune_session()` 按通道删除。
  - `_summary_scan_allowed()` 不再扫描旧 `segment_maps.jsonl` / `prompt_cache.jsonl`。
  - `summarize_session()` 改用 `token_observations` + `cache_plans` 或 summary index。

删除：

- 旧文件名在新代码中不再作为 active path 出现：
  - `segments.jsonl`
  - `segment_maps.jsonl`
  - `token_usage.jsonl`
  - `prompt_cache.jsonl`
  - `prompt_cache_baselines.jsonl`
  - `prompt_stability.jsonl`
  - `provider_cache_ledger.jsonl`

验收：

- `rg` 搜索旧文件名，只允许在一次性迁移/文档中出现。
- 新运行只生成目标账本文件。

## 目标目录结构

建议保留当前按时间热目录，但在小时目录下按层级拆分：

```text
storage/runtime_state/prompt_accounting/hot/by_time/YYYYMMDD/HH/
  observations/
    token_observations.jsonl
  manifests/
    prompt_manifests.jsonl
  analysis/
    cache_plans.jsonl
    prefix_state.jsonl
    cache_anomalies.jsonl
  bus/
    provider_cache_bus.jsonl
```

如果为了减少目录层级，也可以保持同一小时目录下的扁平文件，但文件名必须体现层级：

```text
prompt_manifests.jsonl
token_observations.jsonl
cache_plans.jsonl
prefix_state.jsonl
cache_anomalies.jsonl
provider_cache_bus.jsonl
```

建议采用第一种目录结构，因为它能直接让观察层、manifest 层、分析层、展示层分开。

## 关键不变量

1. 每个 provider request 只有一个 `request_id`。
2. `prompt_manifests` 是 segment 事实权威。
3. `token_observations` 是 token 原始事实权威。
4. `cache_plans` 只表达本地计划，不表达 provider 是否命中。
5. `prefix_state` 是 prefix 连续性和变化检测权威。
6. `provider_cache_bus` 是 provider cache 当前裁决和 UI 展示权威。
7. 前端不读取分析层文件，不重算缓存命中。
8. cold start、warm under-read、current append miss、dynamic tail miss 必须拆分显示。
9. 不保留长期旧文件双读兼容。
10. 新代码不得再写 `segments.jsonl`。

## 风险和处理

| 风险 | 处理 |
| --- | --- |
| 历史热目录仍有旧文件，视觉上仍像重复 | 新代码不再读取旧文件；是否删除历史 runtime state 由单独清理动作处理 |
| `prompt_stability` 包含大量 section 详情，合并后 `prefix_state` 可能过大 | `prefix_state` 存 segment refs、hash、token counts；详细 segment 从 `prompt_manifests` 反查 |
| context meter 当前依赖 `list_token_usage()` | 新接口 `list_token_observations()` 保持同等语义，但返回 phase 明确的记录 |
| summary index 当前用 `token_usage` + `prompt_cache` | 改为 `token_observations` + `provider_cache_bus`，避免 plan 与 result 混算 |
| provider bus 依赖 cache plan 和 provider usage | provider result 阶段统一组装 bus record，禁止前端从底层重建 |

## 验证方式

按项目约束，不新增测试文件，不通过 mock 或跳过断言制造通过。采用代码审查、编译检查、真实运行链路验证。

建议验证命令：

```powershell
python -m compileall backend/runtime/prompt_accounting backend/runtime/model_gateway backend/api
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8003/api/tokens/session/<session_id>
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/api/tokens/session/<session_id>
```

真实运行验收：

1. 固定后端 `http://127.0.0.1:8003`、前端 `http://127.0.0.1:3000`。
2. 发起一轮 agent 对话和至少两次 tool follow-up。
3. 检查新小时目录只生成目标账本。
4. 检查 provider cache bus latest covered 时，前端不显示当前 under-read。
5. 检查 cold start 只进入历史统计，不影响 current prefix status。

## 实施顺序建议

1. 先做 Phase 1-2：通道定义 + 删除 `segments.jsonl` 主写入。
2. 再做 Phase 3：拆 preflight/result 双写。
3. 再做 Phase 5：provider cache bus 和前端展示修正。
4. 最后做 Phase 4 和 Phase 6：合并 prefix state、清理旧文件名和 retention/prune。

原因：

- `segments.jsonl` 重复最明确，先删风险最低。
- provider cache bus 展示误导对用户影响最大，应尽早修。
- baseline/stability 合并涉及最多内部依赖，应在前面链路稳定后做。

## 2026-06-30 实施记录

本轮已完成 Phase 1、Phase 2、Phase 3、Phase 4、Phase 5，并完成 Phase 6 中与 prefix state、cache plan 相关的旧文件入口清理。`cache_plans.jsonl` 现在只记录 preflight local cache plan；provider result 不再回写 plan，而是进入 `provider_cache_bus.jsonl`。

### 已完成

- `ledger.py` 建立账本通道常量，active append/list/retention/prune 改为 `prompt_manifests.jsonl`、`token_observations.jsonl`、`provider_cache_bus.jsonl` 等通道。
- `record_segment_map()` 只写 `prompt_manifests.jsonl`；`record_segment()` 仅派生单段 manifest，不再写 `segments.jsonl`。
- 删除 active runtime/api/frontend/health 中的 `list_segment_maps`、`segment_maps`、`provider_cache_ledger.jsonl`、`token_usage.jsonl`、`segments.jsonl` 入口。
- `ModelTokenUsageRecord` 增加显式 `phase`；本地预测写 `local_prediction`，provider usage 写 `provider_usage`，账本写入时会补齐旧调用点遗漏的 phase。
- `provider_cache_bus.py` 成为 provider cache 展示总线，写入 `provider_cache_bus.jsonl`，并输出：
  - `latest_status`
  - `latest_prefix_health`
  - `latest_under_read_tokens`
  - `warm_provider_under_read_tokens`
  - `cold_start_under_read_tokens`
  - `history_under_read_tokens`
  - `current_prefix_covered`
  - `current_cache_spine_hash`
  - `current_transport_contract_hash`
- `backend/api/tokens.py` 的缓存签名纳入 `token_observations`、`prompt_cache`、`provider_cache_bus`。
- `backend/api/sessions.py` 的 latest prompt manifest summary 改读 `list_prompt_manifests()`。
- `backend/health_system/governance.py` 的展示支线改为 `provider_cache_bus` 和 `prompt_manifests` 命名。
- `frontend/src/components/chat/ChatPanel.tsx` 的当前缓存告警只看 latest bus 裁决，不再用历史 under-read 改写当前压力条状态。
- `frontend/src/lib/api/types.ts` 增加 provider cache bus summary 字段。
- 新增 `backend/runtime/prompt_accounting/prefix_state.py`，`PrefixStateRecord` 合并 legacy baseline、prefix diff、四段 lane hash、generation、previous state ref 和 provider cache 读取预期。
- `model_runtime.py` 新请求不再写 `prompt_cache_baselines.jsonl` / `prompt_stability.jsonl`；`PrefixStateReporter` 直接拥有 continuity、generation、changed_tiers 和 provider prefix seal 计算，最终只写一条 `prefix_state.jsonl`。
- `cache_baseline.py` 已从 active code 删除；`ProviderPayloadSegment.consumer_contracts` 和 serializer consumer contracts 均改指向 `runtime.prompt_accounting.prefix_state`。
- `stability_report.py` / `stability_models.py` 已从 active code 移除；当前 diff helper 为 `prefix_state_diff.py` / `prefix_state_diff_models.py`，导出名为 `PrefixStateDiffReporter` / `PrefixStateDiffReport`。
- `prefix_state.py` 不再读取旧 `diagnostics.baseline.provider_prefix_seal`；provider prefix continuity 只接受当前 `provider_prefix_seal` 字段。
- `prefix_state.memory_segment_hash` 不再通过 `kind/source/authority` 文本包含关系判断 memory 段；现在只消费标准化 segment identity：显式 memory kind、registry `CONTEXT_MEMORY` capability、`agent_domain=ContextMemoryDomain` + `selected_memory_and_task_state_facts`、或 `semantic_commit_class=selected_memory_context`。`authority_class`、`content_source`、`authority=memory_system.*` 只描述来源，不能单独让未知段进入 memory hash，避免把 TaskStateDomain 或来源相似段混入 memory state。
- `provider_lane.py` 删除显式 `legacy_unscoped` 别名；未知 lane 仍统一归一到当前 canonical `unscoped`，但 active code 不再保留 legacy 命名分支。
- `provider_lane_from_accounting_context()` 删除基于 `source/call_kind/request_id` 的字符串启发式归属，并移除 `call_kind` 接口参数；provider lane 只读 `accounting_context.provider_lane` 或 `prompt_manifest.provider_lane`。`context_pipeline.provider_lane_from_model_selection()` 不再构造伪 accounting context，只读取 `model_selection.provider_lane`。Utility 和 semantic compaction 已补显式 lane。
- `unplanned_model_call` anomaly 的 severity 不再通过 `source.startswith("harness.")` 或 stream `call_kind` 判断；现在只由显式 `provider_lane` 裁决，`agent_tool_loop` / `agent_control_no_tool` 为 high，其它 lane 为 medium。
- `ContextUsageMeter` 选择 agent runtime token observation 时不再解析 `request_id` / `packet_ref` 的 `modelreq:rtpacket` 字符串形状，也不再读取 `cache_metric_scope=agent_runtime`。上下文压力候选只由显式 `provider_lane` 识别；无显式 agent lane 的记录只能作为 `all_session_usage` 背景，不获得 agent runtime 身份。
- `ProviderVisibleContextLedger` 的 provider success 确认新增显式 `confirmed_turn_id` 记录；`model_runtime.py` 从 `accounting_context.turn_id` 传入，session cutoff 截断只读取 `confirmed_turn_id`，不再从 `modelreq:rtpacket:*` request id 字符串反解析 turn 身份。
- `context_prefix_identity` 的 replay 生命周期不再读取 `kind` 前缀、`source_kind` 或 `content_source` 字符串启发式；`confirmed_frame_replay` 只来自 physical prefix frame replay contract，`provider_protocol_replay` 单独表达并保持 expected read。
- `context_prefix_identity` 的 origin authority 不再读取 `authority_class`；前缀身份只接受显式 origin/source 字段和稳定 source_ref/kind fallback，避免旧类别标签改变 logical segment ref。
- `CanonicalPromptSerializer._authority_class()` 不再根据 `kind`、`role=user`、`compression_role` 猜测 authority class；只接受上游显式标准枚举，否则输出 `unknown`。
- `CompressionBudgetPlanner._is_hard_required()` 不再读取 `authority_class`，也不再把 `cache_role=session_stable` 单独作为硬保留条件。硬保留只来自显式 `compression_role=preserve`、expected-read 物理前缀、capability `contract/control/feedback` member、以及显式 contract/recovery slot。
- `context_commit_record` 的 tool transcript projection 不再读取 `authority_class=append_only_tool_transcript_delta`，只读标准 tool transcript kind 或 `semantic_slot=tool_transcript`。
- `authority_class` 已从 active Python 代码退场：`PromptSegment` 不再有该字段，serializer 不再读取 planned metadata 中的该字段，cache planner 不再输出该诊断字段，prompt composition slot/load plan、context segment registry、harness compiler/context producers/follow-up specs 和 memory maintenance specs 均不再转发该旧标签。
- `harness.runtime.compiler` 的 dynamic context metadata validation 不再通过 `kind.startswith("dynamic")` 判断动态段；动态校验只读 volatile cache role 或 ContextSegmentPolicy `dynamic_tail` section，sealed replay 例外统一读取 `provider_message_replay_contract`。
- versioned compact task start intent 名称已退出 active code；`compact_task_start_intent` 是 agent-facing task start intake identity。旧 `task_contract_seed` / layered task contract seed 不再迁移成 canonical Work Mode，只作为 validation error / repair diagnostic。
- dynamic context replacement identity 已退出 `*_v3` / `.v3` / `projector_version` 表达；`projector_id` 是当前稳定投影身份，provider-visible ledger entry hash salt 使用无版本后缀的稳定 schema。
- 自有 runtime authority/protocol/schema identity 已继续去掉 `.v1` / `_v1` 后缀；缓存和 provider-visible adapter 链路使用稳定契约身份，不再用版本号表达主链路身份。模型族事实命名如 `deepseek_v4` 不属于本项目契约版本后缀。
- task/file evidence 合同身份已统一为 `contract_id`；assistant stream frame、context recovery package、runtime cache manifest 和 session runtime projection slice 已统一使用 `*_schema_id` 稳定身份字段。Provider-visible ledger、physical prefix frame ledger、TurnMemory、context commit record 的落盘结构号已统一为 `*_schema_revision`，不再使用 `schema_version` 混淆缓存/上下文身份。
- `session_runtime_timeline` 的 live projection 裁剪已收口为单点预算算法：按最近 projection root 选帧，并在预算内带上 tool lifecycle closure；旧的未用 closure helper 与泛化 semantic root 命名已从 active path 删除。
- provider-native tool invocation 自动 fallback 到 JSON action object 已从 active path 删除；工具 transport 由 `ToolCallContract` 单点决定，执行层不再通过 provider 错误文本重选 transport。
- provider-visible ledger 已删除 `last_provider_success_anchor` / `last_success_anchor_id` legacy alias；prefix/provider-visible replay 只读取 active provider success cursor。
- `prompt_composition.fragments` 不再通过 `content_source.startswith("runtime.")` 或 `content_source=runtime.provider_protocol_replay` 决定使用 message spec 还是 fallback model message；byte-preserve 统一读取 `provider_message_replay_contract`。
- `context_capability_policy` 不再通过 prompt rule kind 子串、contract slot 子串或 `tool_` kind 前缀决定能力组；prompt resource 和 context contract 的能力归属只读显式 metadata、精确 rule/slot 目录、registry capability 与资源 category/subtype。
- `prompt_library.assembly` 不再通过 `system.foundation.*` / `runtime.*` prompt ref 前缀绕过 capability gate；稳定必入 prompt 只接受 `builtin_runtime_prompt=True` 或 `category=system/subtype=foundation/source_type=builtin_system_foundation_prompt`。
- `prompt_library.rules` 不再通过 `rule_kind.startswith("system.foundation")` 判断 foundation coverage；`PromptSection.metadata.source_type` 由 prompt resource 显式透传。
- `harness.runtime.assembly` 不再通过 `runtime.*` prompt ref 前缀把 prompt resource gate 降级为 diagnostic-only；`system_wiring_manifest.compiled.prompt_resource_gates` 由系统组显式 `prompt_resources` 列表生成。
- `context_prefix_identity`、`provider_payload`、`serializer`、`provider_visible_context_ledger` 与 ContextContract authority projection 不再把 `content_source/source_kind/context_source_kind` 当作 prefix origin authority 或 provider-visible item identity。来源标签只保留为来源描述，prefix/logical/provider-visible 身份只读显式 origin、显式 semantic source、source_ref/kind fallback 或已生成 prefix identity。
- `physical_context_plan` 与 `provider_visible_context_ledger` 不再通过 `semantic_commit_class.startswith("provider_visible_replay_only")` 推断 historical-only；历史可见性只由显式 visibility/replay flags 决定。
- `context_pipeline.sealed_provider_visible_replay_spec()`、`physical_context_assembler._current_append_specs()` 和 `context_segment_policy` replay section 分类不再重复实现 replay 条件；sealed 判断、section 分类与 current append 分流统一委托 `provider_message_replay_contract`。
- `provider_message_replay_contract.provider_protocol_replay_metadata()` 不再通过 `content_source=runtime.provider_protocol_replay` 授权 byte-preserve replay；provider protocol replay 必须由显式 boolean/policy/status/authority contract 字段声明。
- provider result 阶段不再二次写 diff report；provider 实测缓存日志只写 `provider_cache_bus.jsonl`。
- preflight 阶段调用 `ledger.record_cache_plan(...)` 写入 `cache_plans.jsonl`；provider result 阶段不再调用旧 cache result 回填入口，也不再把 provider usage 回填到 cache plan。
- `provider_cache_bus_record.py` 构造 `ProviderCacheBusRecord`，引用字段为 `cache_plan_ref`，避免把 bus record 误读成 cache plan 本身。
- `ProviderCacheLedgerRecord`、`provider_cache_ledger.py`、`break_status`、`first_break_segment` 已退出 active code；当前字段为 `ProviderCacheBusRecord`、`bus_record_id`、`physical_cache_spine_status`、`first_mismatch_segment`。
- 旧 prompt cache 计划类已重命名为 `CachePlanRecord`；持久字段使用 `cache_plan_id`，summary 使用 `cache_plan_count`，不再把本地计划层称作 cache record。
- `ledger.py` 删除 `record_prompt_cache_baseline`、`record_prompt_stability`、旧 baseline/stability list/reset 方法；`reset_prefix_state()` 成为 compact/truncate 后的状态失效入口。
- `app_runtime.py` 与 `api/sessions.py` 的 compact/truncate prefix reset 均改为写 `prefix_state` invalidated 记录。
- prompt cache 诊断脚本改读 `prompt_manifests.jsonl`、`token_observations.jsonl` 和 `prefix_state.jsonl`，不再读取 `segment_maps.jsonl`、`token_usage.jsonl`、`prompt_stability.jsonl`。

### 当前边界

- `cache_plans.jsonl` 已替代 active preflight cache plan 写入；旧热目录中可能仍有历史 `prompt_cache.jsonl`，但新代码不再把它作为 active plan/result 通道。
- `prompt_cache_baselines.jsonl` 与 `prompt_stability.jsonl` 已退出 active runtime/code/script 写入读取路径；旧热目录中可能仍存在历史文件，但新代码不再把它们作为 previous state 或诊断入口。
- 旧热目录中的旧文件不做 runtime 双读兼容。重启后旧 session 如果尚未产生新 `provider_cache_bus.jsonl`，`provider_cache_log.records` 会按新链路返回空数组；下一次真实 provider response 才会写入新 bus。
- 新 session 的 prefix continuity previous 只从 `prefix_state` 读取；历史旧 state 不做双读迁移。

### 已验证

- `python -m compileall -q backend/runtime/context_management backend/runtime/model_gateway backend/runtime/prompt_accounting backend/harness/runtime backend/api backend/bootstrap backend/health_system` 通过。
- `python -c` 内存 smoke 已验证 invalidated prefix state 不会跨 reset 读取更早 active state，且 `PrefixStateReporter.build()` 可直接生成 active state。
- `python -c` 已验证 `provider_lane` 对空值、未知值和历史输入均归一为当前 canonical lane，不再通过 legacy alias 常量分支，也不再接受 `call_kind` 作为 lane 推断输入。
- `python -c` 已验证 `unplanned_model_call` anomaly severity 只由 provider lane 决定。
- `python -c` 已验证 `ContextUsageMeter` 的 agent runtime token observation 身份只由 provider lane 决定。
- `python -c` 已验证 provider-visible ledger 写入 `confirmed_turn_id`，并且 session cutoff 截断只依据该字段保留/停用 entries，不从 `modelreq:rtpacket:*` request id 反解析 turn。
- `python -c` 已验证 `context_prefix_identity` 只凭 `physical_prefix_frame_*` kind 不再生成 expected read；显式 physical frame replay contract 与 provider protocol replay contract 仍能生成 expected read。
- `python -c` 已验证 compression budget 的硬保留不再读取 `authority_class`：`current_turn_tail + session_stable/session` 不再被当作 expected-read 硬保留，`provider_visible_context_prefix + included` 与 contract/control kind 仍被保护。
- `python -c` 已验证 active Python 不再生成 prompt accounting / prompt composition `authority_class` 字段；`rg authority_class backend -g '*.py'` 无结果。
- `python -c` 已验证 fragments source selection 不再读取 `content_source=runtime.provider_protocol_replay` 作为 fallback 条件；显式 `provider_protocol_replay=True` 才触发 provider byte-preserve fallback。
- `python -c` 已验证 contract slot 能力归属不再读取 `tool` 子串或 `tool_` kind 前缀；精确 `tool_dispatch`、`tool_observation_recovery` 等 slot 仍按目录归属。
- `python -c` 已验证 prompt stable gate 不再读取 prompt ref 前缀；只有显式 builtin runtime metadata 或 builtin system foundation metadata 才能 bypass gate。
- `python -c` 已验证改变 `content_source/source_kind` 不再改变 `context_prefix_identity.logical_segment_ref` 或 `provider_visible_context_ledger` item key；显式 `context_origin_authority` 仍能改变身份。
- `python -c` 已验证 `semantic_commit_class=provider_visible_replay_only_*` 不再隐式改写 historical-only；显式 `provider_visible_replay_only=True` 和显式 `semantic_visibility=historical_only` 仍然生效。
- `python -c` 已验证 provider message replay contract 成为 sealed 判断和 assembler current append 分流的共同 owner：current append 不被 sealed，physical frame replay/provider protocol replay 会被排除出 current append。
- `python -c` 已验证 `context_segment_policy` 的 replay section 分类也消费 `provider_message_replay_contract`：provider protocol replay / physical frame replay 进入 memory prefix，current append 仍为 append，dynamic tail 显式策略优先。
- `python -c` 已验证 `content_source=runtime.provider_protocol_replay` 单独不再触发 provider protocol replay；显式 `provider_protocol_replay` boolean、policy、status、authority 仍然触发。
- `npx tsc --noEmit` 通过。
- `python -m pytest -q backend/tests/session_runtime_timeline_contract_test.py backend/tests/runtime_cache_manager_regression.py` 通过，确认 session runtime projection 裁剪和 cache manager 当前契约。
- 固定端口已重启并验证：
  - 后端 `http://127.0.0.1:8003`
  - 前端 `http://127.0.0.1:3000`
- `/api/tokens/session/session-e694517fab574639` 经后端和前端代理均返回 `source: prompt_accounting.provider_cache_bus.jsonl`，且 summary 已切换为 latest/warm/cold/history 拆分字段。

## 暂停条件

实施中如果发现以下情况，必须暂停并重新确认：

- `segments.jsonl` 存在当前未发现的外部消费者。
- `prompt_stability` 中有不能从 manifest + prefix_state 重建的关键字段。
- provider adapter 返回的 cache usage 无法稳定映射到 bus record。
- 新目录结构影响已有 runtime state 清理、归档、或用户可见下载链路。
