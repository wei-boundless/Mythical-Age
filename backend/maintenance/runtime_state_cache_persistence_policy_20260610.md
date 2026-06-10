# Runtime State Cache And Persistence Policy

## 背景

这次 `storage/runtime_state/sandboxes` 膨胀的根因不是单个节点写错，而是运行态数据边界不够硬：执行沙盒把运行时生成目录也当作工作区材料复制，导致 sandbox 套 sandbox，最终把图任务主循环卡在路径解析和全量物化上。

后续必须把运行态数据分成两条线：

- **权威持久化**：用于恢复、审计、继续运行、用户查看和正式产物管理。
- **动态缓存**：用于加速、隔离、临时执行和派生视图，允许删除，删除后必须能重建或自然失效。

缓存不能成为图任务是否完成、节点是否通过、产物是否正式提交的判断来源。

## 总原则

1. 图任务事实权威只来自图运行记录、节点结果、任务记录、事件日志、正式产物和 memory/事实库。
2. 沙盒、投影视图、索引、编译包、日志和临时执行目录默认不是事实权威。
3. 所有可删除目录必须具备 `owner`、`ttl`、`max_size`、`rebuild_source` 和 `cleanup_receipt`。
4. 删除缓存不允许改变图 loop 状态、不允许制造节点完成、不允许删除正式产物。
5. 持久化数据可以压缩、归档、分区和 vacuum，但不能被无凭据删除。
6. 当前运行中的 graph run、task run、node work order 关联数据必须受保护。

## 数据分层

### A. 必须持久化的事实权威

这些数据是恢复和审计来源，不能当缓存处理。

| 数据 | 当前位置 | 保留原因 | 清理策略 |
| --- | --- | --- | --- |
| 图运行记录 | `storage/runtime_state/runtime_objects/graph_run` | graph run 的事实状态 | 只能由图实例生命周期归档/删除 |
| 图 loop checkpoint | `storage/runtime_state/graph_checkpoints.sqlite*` | 恢复 running/blocked/ready 节点 | compact/vacuum，不直接删除 |
| 节点 work order / result | `storage/runtime_state/runtime_objects/graph_node_work_order`, `graph_node_result` | 节点交付、边传播、恢复审计 | 只按 graph run 生命周期清理 |
| task run / agent run 索引 | `storage/runtime_state/state_index` | 当前运行读模型和恢复索引 | 通过 health maintenance prune，禁止手删 |
| task lifecycle / contract | `storage/runtime_state/runtime_objects/task_lifecycle`, `task_run_contract` | 任务契约、状态、验收边界 | 跟随 task run 生命周期 |
| runtime event log | `storage/runtime_state/events`, `event_payloads` | 审计和恢复证据 | archive，不直接 delete |
| prompt accounting ledger | `storage/runtime_state/prompt_accounting` | token、cache、provider 行为审计 | archive/partition，不直接 delete |
| facts / memory / file state | `storage/runtime_state/facts`, `file_state`, `durable_memory_governance` | 记忆、事实和文件状态权威 | compact/partition，不当缓存 |
| 正式项目产物 | `storage/graph_task_instances`, `storage/artifact_repository`, `storage/task_environments` | 用户可管理产物和正式库 | 由项目/产物生命周期管理 |

### B. 可重建投影和运行视图

这些目录为了查询和 UI 快，不是事实权威。可以删除后从 A 类数据重建。

| 数据 | 当前位置 | 重建来源 | 清理策略 |
| --- | --- | --- | --- |
| event tail/index | `storage/runtime_state/event_index` | `events` + `event_payloads` | 可 rebuild_or_delete |
| runtime live views | `storage/runtime_state/runtime_views` | task run + events + runtime_objects | 启动时可重建，TTL |
| active executor indexes | `storage/runtime_state/state_index/active_executor_task_runs` | task run 状态 + scheduler | stale 后重建 |
| session latest/recent views | `storage/runtime_state/state_index/session_latest_task_runs`, `global_recent_task_runs` | task run 列表 | 可重建 |
| runtime monitor/traces projection | `storage/runtime_state/runtime_monitor`, `traces` | event log + current process | keep latest / TTL |

规则：B 类可以作为 UI 和 monitor 的读模型，但不能单独作为恢复事实。如果 B 与 A 冲突，以 A 为准并重建 B。

### C. 动态缓存

这些应该从 `runtime_state` 的事实区剥离，改成 cache root，例如 `storage/runtime_cache` 或 `output/runtime_cache`。

| 数据 | 当前位置 | 应迁移到 | 删除条件 |
| --- | --- | --- | --- |
| local overlay sandbox | `storage/runtime_state/sandboxes` | `storage/runtime_cache/sandboxes` | task terminal 后 TTL，stale running 超时，size cap |
| prompt 编译包缓存 | 当前混在 prompt/cache/accounting/packet 相关目录 | `storage/runtime_cache/prompt_packets` | key 失效、模型/规则版本变化、TTL |
| context projection cache | dynamic context replacements 中的可重建投影 | `storage/runtime_cache/context_projection` | source hash 失效或 TTL |
| tokenizer/model estimate cache | token 估算、segment map 派生缓存 | `storage/runtime_cache/tokenization` | tokenizer/version/hash 失效 |
| provider prompt-cache probe artifacts | `prompt_cache_live_tests` | `output/runtime_cache/provider_probe` | keep last N 或 TTL |
| dev server/session temp | `.tmp`, `dev_servers`, `background_tasks` 中非任务事实部分 | `output/runtime_cache/dev` | 进程退出或 TTL |

缓存记录必须写明：

```json
{
  "cache_key": "stable hash",
  "owner": "runtime subsystem",
  "source_refs": ["authoritative refs used to build it"],
  "schema_version": "cache schema",
  "created_at": 0,
  "last_accessed_at": 0,
  "ttl_seconds": 0,
  "max_size_bytes": 0,
  "rebuildable": true
}
```

### D. 诊断和日志

这些用于排错，不参与恢复。

| 数据 | 当前位置 | 策略 |
| --- | --- | --- |
| backend/frontend logs | `logs`, `output/*.log`, `storage/runtime_state/*log*` | rotate，保留最近 N 份 |
| dev/test traces | `dev_logs`, `dev_server_logs`, `manual_verification_logs` | TTL，失败用例可延长 |
| executions receipts | `storage/runtime_state/executions` | 保留近期和失败，成功记录可 TTL |
| backups | `storage/runtime_state/backups` | 带 receipt 的短期保留，超期归档 |

## 图任务专用规则

图任务是项目级系统，不应绑定对话环境。每个节点可以有自己的 session，但 session transcript 和 sandbox workspace 要分开：

- 节点 session 对话、节点输出、节点结果：持久化。
- 节点执行沙盒、工具临时文件、显式 workspace materialize：动态缓存。
- 写作正文、章纲、审核意见、memory commit、正式库索引：持久化。
- 未提交草稿可以保留在项目草稿库，但必须有状态：`draft`, `approved`, `rejected`, `superseded`。

对写作图来说，正文和 memory 是用户资产；沙盒只是写手临时桌面。

## 权威链

目标链路应该是：

```text
GraphConfig / GraphRun
-> GraphLoopCheckpoint
-> NodeWorkOrder
-> TaskRunContract
-> TaskRun / AgentRun
-> NodeResultEnvelope
-> Artifact / Memory Commit
```

缓存只能挂在链路旁边：

```text
RuntimeCache
-> sandbox workspace
-> prompt packet cache
-> context projection cache
-> runtime view cache
```

缓存可以加速链路，但不能替链路产出事实。

## 迁移计划

1. 扩展 `ArtifactGovernanceRegistry`，把每个 runtime root 标注为 `source_of_truth`, `projection`, `dynamic_cache`, `diagnostic`。
2. 新建 `RuntimeCacheManager`，统一管理 `storage/runtime_cache`：
   - 分配 cache root。
   - 写 cache manifest。
   - 执行 TTL / max size 清理。
   - 记录 cleanup receipt。
3. 把 `LocalOverlaySandboxBackend` 的默认 sandbox root 从 `storage/runtime_state/sandboxes` 迁到 `storage/runtime_cache/sandboxes`。
4. 保留当前防线：显式 workspace materialize 永远排除 `storage/runtime_state`, `storage/runtime_cache`, `output/sandbox_runs`, sessions 和 logs。
5. 给图任务 monitor 增加一致性检查：
   - 如果 task run completed 但 graph loop 仍 running 旧 work order，应以 node result + checkpoint 权威恢复。
   - stale active work order 不允许长期污染运行视图。
6. 提供维护 API：
   - `GET /api/runtime/artifacts/inventory`
   - `POST /api/runtime/cache/cleanup-preview`
   - `POST /api/runtime/cache/cleanup`
   - `POST /api/runtime/projections/rebuild`

## 清理策略建议

| 类别 | 默认 TTL | 体积上限 | 运行中保护 |
| --- | --- | --- | --- |
| sandbox cache | task terminal 后 30 分钟 | 全局 5GB，可配置 | running/waiting task 保护 |
| prompt packet cache | 7 天 | 2GB | 当前 graph run 引用保护 |
| context projection cache | 24 小时 | 1GB | 当前 task run 引用保护 |
| runtime views | 24 小时 | 512MB | 可重建，不保护单文件 |
| logs/traces | 3 天，失败保留 7 天 | 2GB | 当前进程日志保护 |
| live test artifacts | 24 小时 | 1GB | 无 |

## 近期必须做的修正

1. 不再把 `storage/runtime_state/sandboxes` 当长期状态保存。
2. 避免默认 full workspace snapshot；显式 materialize 也不能扫描运行态目录。
3. 增加 stale running task/work order 修复器，避免旧 task run 和新 node result 同时存在时 monitor 读错。
4. 把 cache cleanup 做成 HealthSystem/RuntimeSystem 的正式维护动作，所有删除都要有 receipt。
5. 前端文件管理只展示正式项目库、草稿库、审核库和产物库，不展示 cache root。
