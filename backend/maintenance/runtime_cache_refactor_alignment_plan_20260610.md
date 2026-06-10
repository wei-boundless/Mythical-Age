# Runtime Cache Refactor Alignment Plan

## 目标

把 runtime 中“事实权威”和“动态缓存”彻底分开，避免 sandbox、prompt packet、projection cache 这类可再生数据污染图任务恢复、monitor 和节点执行。

这次重构不是为了兼容旧目录，而是建立清晰的新边界：

```text
Durable Runtime Facts
-> Rebuildable Runtime Projections
-> Dynamic Runtime Cache
-> Diagnostic Logs
```

## 对齐结论

### 1. 图任务权威层

这些数据决定图任务能否恢复、继续、审计，必须持久化。

```text
GraphRun
GraphLoopCheckpoint
GraphNodeWorkOrder
TaskRunContract
TaskRun / AgentRun
TaskLifecycle
GraphNodeResult
RuntimeEvents
Formal Artifacts / Memory Commits
```

对应目录：

- `storage/runtime_state/graph_checkpoints.sqlite*`
- `storage/runtime_state/runtime_objects`
- `storage/runtime_state/state_index`
- `storage/runtime_state/events`
- `storage/runtime_state/event_payloads`
- `storage/runtime_state/prompt_accounting`
- `storage/graph_task_instances`
- `storage/artifact_repository`
- `storage/task_environments`

规则：

- 只能通过 graph lifecycle、task maintenance、artifact lifecycle 管理。
- 不允许 cache cleanup 触碰。
- 不允许用“可恢复/兼容”名义保留第二套事实链。

### 2. 可重建投影层

这些数据服务查询和 UI，可以删除后重建，但当前系统可能仍依赖它们做快速读取，因此清理必须走 rebuild/refresh 流程。

对应目录：

- `storage/runtime_state/event_index`
- `storage/runtime_state/runtime_views`
- `storage/runtime_state/state_index/*latest*`
- `storage/runtime_state/state_index/active_executor_task_runs`
- `storage/runtime_state/runtime_monitor`
- `storage/runtime_state/traces`

规则：

- 和事实冲突时，以事实层为准。
- projection rebuild 必须有明确入口。
- monitor 不应只相信 projection，遇到 stale running 必须回查 node result / task lifecycle / checkpoint。

### 3. 动态缓存层

这些数据只是执行加速和临时隔离，应该迁出 `runtime_state`。

目标根目录：

```text
storage/runtime_cache
```

子目录建议：

```text
storage/runtime_cache/sandboxes
storage/runtime_cache/prompt_packets
storage/runtime_cache/context_projection
storage/runtime_cache/tokenization
storage/runtime_cache/provider_probe
storage/runtime_cache/dev
```

规则：

- cache 必须可删、可重建或可自然失效。
- cache 不能作为 graph run/node result/task completion 的判断依据。
- cache manifest 必须记录 `cache_key`, `owner`, `source_refs`, `created_at`, `last_accessed_at`, `ttl_seconds`, `size_bytes`, `rebuildable`。
- running task 引用的 cache 受保护；terminal task cache 可按 TTL 删除。

### 3.1 双沙盒职责分层

系统已经有 Docker Sandboxes 后端，因此自研 `local_overlay` 不能继续承担重隔离或完整执行环境职责。目标分层如下：

| 层 | 职责 | 不负责 |
| --- | --- | --- |
| `local_overlay` | 快速 copy-on-write、路径边界、显式材料物化、产物发布扫描、缓存生命周期 | 强隔离、依赖安装、完整项目快照、不可信代码执行 |
| `docker_sandboxes` | shell/python 的强隔离执行、CPU/内存/超时限制、只读项目挂载、可写 sandbox 挂载 | 图事实判断、任务完成裁决、产物真实性合成 |

规则：

- `local_overlay` 默认不再为 terminal/python 自动复制整个工作区。
- 需要材料时由 `materialized_roots` 显式声明，或由搜索/list/read 的具体工具参数按需物化。
- 需要完整项目执行、依赖隔离、系统级命令或不可信代码时，通过 `sandbox_policy.execution_backend=docker_sandboxes` 进入 Docker 后端。
- Docker 后端仍只执行，不拥有权限裁决；权限来自 operation gate、sandbox policy 和 tool preflight。

### 4. 诊断日志层

这些数据仅用于排障。

对应目录：

- `logs`
- `output/*.log`
- `storage/runtime_state/dev_logs`
- `storage/runtime_state/dev_server_logs`
- `storage/runtime_state/manual_verification_logs`
- `storage/runtime_state/executions`
- `storage/runtime_state/backups`

规则：

- rotate / keep-last-N / TTL。
- failure diagnostics 可延长保留。
- 不能参与恢复决策。

## 目标权威链

图任务执行的事实链：

```text
GraphConfig Snapshot
-> GraphRun
-> GraphLoopCheckpoint
-> GraphNodeWorkOrder
-> TaskRunContract
-> TaskRun / AgentRun
-> GraphNodeResult
-> Edge Propagation
-> Formal Artifact / Memory Commit
```

缓存链只允许旁路加速：

```text
RuntimeCacheManager
-> sandbox workspace
-> prompt packet cache
-> context projection cache
-> tokenizer estimate cache
```

禁止出现：

```text
Sandbox file/result -> synthetic node receipt -> graph loop advance
```

运行中断恢复边界另见：

- `backend/maintenance/graph_runtime_interruption_recovery_boundary_plan_20260610.md`

## 需要重构的模块

### 第一阶段：建立 cache authority

新增：

- `backend/runtime/cache_manager.py`
- `backend/tests/runtime_cache_manager_regression.py`

职责：

- 提供 `runtime_cache_root`。
- 分配 cache namespace。
- 写 cache manifest。
- 判断 running 引用保护。
- 清理 TTL/size 超限缓存。
- 产出 cleanup receipt。

### 第二阶段：迁移 sandbox root

修改：

- `backend/harness/loop/task_executor.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/runtime/tool_runtime/sandbox_backend.py`
- `backend/harness/runtime/sandbox_execution_scope.py` 如需暴露 cache diagnostics

目标：

- 默认 sandbox root 从 `storage/runtime_state/sandboxes` 迁到 `storage/runtime_cache/sandboxes`。
- `local_overlay` 默认只做按需 materialize，不为 terminal/python 自动做全量工作区快照。
- 若显式 `materialized_roots=["."]`，`sandbox_backend` materialize 永远排除：
  - `storage/runtime_state`
  - `storage/runtime_cache`
  - `output/sandbox_runs`
  - `backend/mythical-agent/sessions`
  - logs/dev/generated traces
- 不再保留旧 `runtime_state/sandboxes` 写入路径。

### 第三阶段：projection/stale 修复

修改：

- `backend/harness/graph/resume.py`
- `backend/harness/graph/runner.py`
- `backend/api/orchestration.py` 或 graph monitor 相关模块
- `backend/health_system/task_record_maintenance.py`

目标：

- monitor 遇到 stale active work order 时回查：
  - latest `graph_node_result`
  - task lifecycle
  - state_index task status
  - graph checkpoint
- 如果 node result 已 completed，而 active view 仍 running，重建 projection，不制造 synthetic result。
- 保留真实历史，但不让旧 running view 污染当前运行。

### 第四阶段：治理表和维护 API

修改：

- `backend/artifact_system/governance.py`
- `backend/scripts/maintain_runtime_artifacts.py`
- health/runtime maintenance API

目标：

- `ArtifactPortPolicy` 增加 `storage_layer`: `durable_fact | projection | dynamic_cache | diagnostic`。
- cache cleanup 与 task record prune 分离。
- runtime cache cleanup 支持 dry-run 和 receipt。

## 不改动范围

这次不改：

- 写作图拓扑。
- 节点 prompt 语义。
- DeepSeek/provider adapter。
- graph task project binding。
- 正式 memory/artifact 写入协议。
- 单 agent loop 的语义，只改其 sandbox cache 根目录。

## 删除和迁移原则

1. 旧 `storage/runtime_state/sandboxes` 不做兼容写入。
2. 如果目录存在，maintenance 可以清理；不做自动读取回退。
3. 已持久化的 graph result/task result 不迁移为 cache。
4. cache manifest 是缓存管理凭据，不是任务事实。
5. 所有 destructive cleanup 必须先 preview，再 execute，并写 receipt。

## 测试计划

必须通过：

```text
python -m pytest backend/tests/sandbox_tool_runtime_regression.py -q
python -m pytest backend/tests/runtime_tool_control_plane_regression.py backend/tests/harness_task_executor_control_regression.py -q
python -m pytest backend/tests/graph_harness_api_regression.py -q
```

新增测试：

- sandbox root 默认落在 `storage/runtime_cache/sandboxes`。
- 默认 terminal/python 不触发 full workspace materialize。
- 显式 full workspace materialize 不复制 `runtime_state` / `runtime_cache`。
- cache cleanup 不删除 running task cache。
- cache cleanup 可删除 terminal task cache。
- monitor stale active work order 可重建 projection，不合成 node result。

运行验证：

- 固定后端 `127.0.0.1:8003` 启动。
- 固定前端 `127.0.0.1:3000` 如涉及 UI。
- 启动写作图任务，确认节点 session 和 graph project 正常。
- 确认 `storage/runtime_state/sandboxes` 不再产生新数据。
- 确认 `storage/runtime_cache/sandboxes` 有 TTL/manifest。

## 需要确认的架构点

我建议直接采用以下默认，不再犹豫：

1. cache root 使用 `storage/runtime_cache`，不放在 `output`，因为它属于运行系统管理，但不是事实状态。
2. sandbox terminal task terminal 后默认保留 30 分钟，失败保留 24 小时。
3. runtime cache 全局默认上限 5GB，超过后按 terminal、最久未访问、最大目录顺序清理。
4. `prompt_accounting` 仍是持久审计，不等于 prompt cache。
5. `runtime_views/event_index` 是 projection，不是 cache；可重建但由 projection rebuild 管理，不和 sandbox cache 一起删。
