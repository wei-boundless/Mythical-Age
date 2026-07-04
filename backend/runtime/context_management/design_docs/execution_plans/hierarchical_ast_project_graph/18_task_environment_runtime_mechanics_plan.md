# 任务环境运行机制实施细节方案

状态：实施细节方案，待审阅后实施  
日期：2026-07-04  
前置文档：`16_unified_agent_task_project_control_overall_plan.md`、`17_task_graph_runtime_interface_detail_alignment.md`

## 1. 文档定位

第 17 号文档已经固定任务环境与图任务的接口。本文件继续向下压实，回答具体工程问题：

```text
任务进度怎么存
任务怎么查询
任务怎么停止
任务怎么暂停
任务怎么恢复
并发和 lease 怎么控制
checkpoint 怎么写
WorkProduct 怎么归并
图节点任务怎么回传
失败和断点怎么修复
```

本文件采用成熟任务系统的标准，而不是只覆盖人类当前想到的功能点。一个成熟任务环境系统必须同时具备：

- canonical store；
- append-only event ledger；
- materialized state snapshot；
- explicit state machine；
- lease / heartbeat / stale lease recovery；
- idempotency；
- checkpoint / save point；
- structured query indexes；
- cooperative pause / stop / abort；
- reducer / work product ingestion；
- dead letter / repair；
- observability and UI projection；
- migration and cleanup plan。

## 2. 当前源码依据

### 2.1 可复用基础

现有系统已经有几类成熟基础：

| 现有模块 | 可复用能力 | 限制 |
| --- | --- | --- |
| `backend/graph_system/loop.py` | `GraphLoopState`、`active_work_orders`、`dispatch_ready()`、`accept_node_result()`、checkpoint | 只管图运行状态，不管任务环境真相 |
| `backend/graph_system/checkpoint_store.py` | checkpoint protocol：`put_checkpoint()`、`get_latest_state()`、`pending_writes` | 面向 GraphLoop，不是通用任务环境存储 |
| `backend/graph_system/resume.py` | 从 checkpoint 恢复图运行，重连 active work orders | 不能恢复单 agent 任务环境语义 |
| `backend/runtime/memory/state_index.py` | runtime trace 快速索引、recent task summaries、graph node task run lookup | 是运行态投影，不适合作为 canonical task store |
| `backend/runtime/shared/runtime_object_store.py` | 大对象 ref 存储，适合重 payload 外置 | JSON 文件对象存储，不适合复杂查询 |
| `backend/project_network_system/repository.py` | SQLite canonical store、work product、generation、channel reducer | 是领域资产 store，不应承载通用任务环境 |
| `backend/harness/task_run_state_view.py` | 旧任务状态公开视图、pause/resume/stop capability 推导经验 | 依赖旧 TaskRun/executor，不能作为新主线 |

### 2.2 不可继续使用为主线的部分

`backend/harness/loop/task_executor.py` 已经包含大量暂停、恢复、工具审批、模型恢复、budget pause 等逻辑，但它同时包含第二套模型执行 loop。后续只能借鉴其中的控制经验，不能继续让它承担执行权威。

裁决：

```text
旧 task_executor 的 pause/resume 经验可以迁移成 task_environment 控制算法。
旧 task_executor 的 provider/tool/model loop 必须被清理或降级。
```

## 3. 成熟体系要求

### 3.1 核心不变量

```text
Event 是发生事实。
Snapshot 是查询投影。
Lease 是执行占用。
Checkpoint 是恢复边界。
WorkProduct 是可消费产物。
Runtime trace 是观测，不是任务真相。
Session binding 是视图，不是任务所有权。
```

### 3.2 存储策略裁决

通用任务环境必须使用 SQLite 作为 canonical store。

原因：

- 任务需要按 status、project、owner、session、graph、updated_at 查询；
- 任务事件、lease、episode、work product 需要事务一致性；
- 单个 JSON 文件无法稳定支持并发、分页、索引、修复和迁移；
- runtime state index 只适合快速投影，不适合作为长期任务真相；
- project_network_system 已经证明 SQLite 适合长期资产与 work product 管理。

推荐位置：

```text
ProjectLayout.tasks_dir / "task_environment.sqlite"
```

JSON 文件仍可用于：

- graph/task template 配置；
- 轻量 runtime view；
- 大 payload 的 object ref；
- 人类可读报告 artifact。

## 4. 数据库 schema 方案

### 4.1 `task_instances`

任务业务实例。

```sql
CREATE TABLE task_instances (
  task_instance_id TEXT PRIMARY KEY,
  task_kind TEXT NOT NULL,
  title TEXT NOT NULL,
  goal TEXT NOT NULL,
  owner_agent_id TEXT NOT NULL DEFAULT '',
  owner_user_id TEXT NOT NULL DEFAULT '',
  project_id TEXT NOT NULL DEFAULT '',
  workspace_view TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'normal',
  acceptance_contract_ref TEXT NOT NULL DEFAULT '',
  root_task_environment_id TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  archived_at REAL NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  authority TEXT NOT NULL DEFAULT 'task_system.task_instance'
);

CREATE INDEX idx_task_instances_status_updated
  ON task_instances(status, updated_at DESC);
CREATE INDEX idx_task_instances_project_status
  ON task_instances(project_id, status, updated_at DESC);
```

### 4.2 `task_environments`

任务工作环境真相。

```sql
CREATE TABLE task_environments (
  task_environment_id TEXT PRIMARY KEY,
  task_instance_id TEXT NOT NULL,
  environment_kind TEXT NOT NULL,
  caller_kind TEXT NOT NULL,
  status TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0,
  current_phase TEXT NOT NULL DEFAULT '',
  current_step TEXT NOT NULL DEFAULT '',
  progress_current INTEGER NOT NULL DEFAULT 0,
  progress_total INTEGER NOT NULL DEFAULT 0,
  progress_label TEXT NOT NULL DEFAULT '',
  active_episode_id TEXT NOT NULL DEFAULT '',
  active_lease_id TEXT NOT NULL DEFAULT '',
  latest_event_id TEXT NOT NULL DEFAULT '',
  latest_checkpoint_id TEXT NOT NULL DEFAULT '',
  latest_context_package_id TEXT NOT NULL DEFAULT '',
  latest_work_product_id TEXT NOT NULL DEFAULT '',
  continuation_hint TEXT NOT NULL DEFAULT '',
  blocked_reason TEXT NOT NULL DEFAULT '',
  recovery_action TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  authority TEXT NOT NULL DEFAULT 'task_system.task_environment',
  FOREIGN KEY(task_instance_id) REFERENCES task_instances(task_instance_id)
);

CREATE INDEX idx_task_env_instance
  ON task_environments(task_instance_id, updated_at DESC);
CREATE INDEX idx_task_env_status_updated
  ON task_environments(status, updated_at DESC);
CREATE INDEX idx_task_env_recovery
  ON task_environments(recovery_action, status, updated_at DESC);
```

### 4.3 `task_events`

append-only 事件账本。

```sql
CREATE TABLE task_events (
  event_id TEXT PRIMARY KEY,
  task_environment_id TEXT NOT NULL,
  task_instance_id TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  actor_kind TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  source_episode_id TEXT NOT NULL DEFAULT '',
  source_graph_run_id TEXT NOT NULL DEFAULT '',
  source_work_order_id TEXT NOT NULL DEFAULT '',
  idempotency_key TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  refs_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  authority TEXT NOT NULL DEFAULT 'task_system.task_event',
  UNIQUE(task_environment_id, event_seq),
  UNIQUE(task_environment_id, idempotency_key)
);

CREATE INDEX idx_task_events_env_seq
  ON task_events(task_environment_id, event_seq);
CREATE INDEX idx_task_events_graph_work_order
  ON task_events(source_graph_run_id, source_work_order_id);
```

事件是事实，不允许 update。错误事件只能追加补偿事件。

### 4.4 `task_environment_leases`

执行占用记录。

```sql
CREATE TABLE task_environment_leases (
  lease_id TEXT PRIMARY KEY,
  task_environment_id TEXT NOT NULL,
  episode_id TEXT NOT NULL,
  lease_kind TEXT NOT NULL,
  holder_kind TEXT NOT NULL,
  holder_id TEXT NOT NULL,
  status TEXT NOT NULL,
  acquired_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  heartbeat_at REAL NOT NULL,
  released_at REAL NOT NULL DEFAULT 0,
  release_reason TEXT NOT NULL DEFAULT '',
  idempotency_key TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(task_environment_id, idempotency_key)
);

CREATE INDEX idx_task_leases_active
  ON task_environment_leases(task_environment_id, status, expires_at);
CREATE INDEX idx_task_leases_holder
  ON task_environment_leases(holder_kind, holder_id, status);
```

### 4.5 `agent_execution_episodes`

agent 进入任务环境的一次运行片段。

```sql
CREATE TABLE agent_execution_episodes (
  episode_id TEXT PRIMARY KEY,
  task_environment_id TEXT NOT NULL,
  task_instance_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  agent_profile_id TEXT NOT NULL,
  invocation_kind TEXT NOT NULL,
  caller_kind TEXT NOT NULL,
  graph_binding_id TEXT NOT NULL DEFAULT '',
  input_context_package_id TEXT NOT NULL DEFAULT '',
  lease_id TEXT NOT NULL DEFAULT '',
  runtime_trace_ref TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  terminal_reason TEXT NOT NULL DEFAULT '',
  continuation_hint TEXT NOT NULL DEFAULT '',
  started_at REAL NOT NULL,
  ended_at REAL NOT NULL DEFAULT 0,
  diagnostics_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_episodes_env_started
  ON agent_execution_episodes(task_environment_id, started_at DESC);
CREATE INDEX idx_episodes_status
  ON agent_execution_episodes(status, started_at DESC);
```

### 4.6 `task_context_packages`

episode 输入包的持久记录。

```sql
CREATE TABLE task_context_packages (
  package_id TEXT PRIMARY KEY,
  task_environment_id TEXT NOT NULL,
  episode_id TEXT NOT NULL,
  package_hash TEXT NOT NULL,
  stable_context_ref TEXT NOT NULL DEFAULT '',
  current_context_ref TEXT NOT NULL DEFAULT '',
  memory_refs_json TEXT NOT NULL DEFAULT '[]',
  artifact_refs_json TEXT NOT NULL DEFAULT '[]',
  graph_context_json TEXT NOT NULL DEFAULT '{}',
  packet_policy_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);

CREATE INDEX idx_context_packages_env
  ON task_context_packages(task_environment_id, created_at DESC);
```

大块 context 放 object store 或 artifact store，表里只保存 ref 和 hash。

### 4.7 `task_work_products`

通用 WorkProduct store。

```sql
CREATE TABLE task_work_products (
  work_product_id TEXT PRIMARY KEY,
  task_environment_id TEXT NOT NULL,
  task_instance_id TEXT NOT NULL,
  source_episode_id TEXT NOT NULL,
  product_domain TEXT NOT NULL,
  product_kind TEXT NOT NULL,
  stable_ref TEXT NOT NULL DEFAULT '',
  payload_ref TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  anchor_refs_json TEXT NOT NULL DEFAULT '[]',
  artifact_refs_json TEXT NOT NULL DEFAULT '[]',
  confidence TEXT NOT NULL,
  status TEXT NOT NULL,
  generation INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_work_products_env
  ON task_work_products(task_environment_id, updated_at DESC);
CREATE INDEX idx_work_products_domain_kind_status
  ON task_work_products(product_domain, product_kind, status, updated_at DESC);
CREATE INDEX idx_work_products_stable_ref
  ON task_work_products(product_domain, stable_ref, status);
```

### 4.8 `graph_node_task_bindings`

图节点与任务环境绑定。

```sql
CREATE TABLE graph_node_task_bindings (
  binding_id TEXT PRIMARY KEY,
  graph_run_id TEXT NOT NULL,
  graph_id TEXT NOT NULL,
  config_id TEXT NOT NULL,
  structure_hash TEXT NOT NULL,
  node_id TEXT NOT NULL,
  work_order_id TEXT NOT NULL,
  parent_task_environment_id TEXT NOT NULL DEFAULT '',
  node_task_environment_id TEXT NOT NULL,
  task_instance_id TEXT NOT NULL,
  status TEXT NOT NULL,
  expected_result_contract_ref TEXT NOT NULL DEFAULT '',
  result_projection_policy_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(graph_run_id, work_order_id),
  UNIQUE(idempotency_key)
);

CREATE INDEX idx_graph_bindings_node_env
  ON graph_node_task_bindings(graph_run_id, node_id, status);
CREATE INDEX idx_graph_bindings_task_env
  ON graph_node_task_bindings(node_task_environment_id);
```

### 4.9 `task_control_signals`

pause / stop / resume / abort 控制信号。

```sql
CREATE TABLE task_control_signals (
  signal_id TEXT PRIMARY KEY,
  task_environment_id TEXT NOT NULL,
  signal_kind TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  created_at REAL NOT NULL,
  handled_at REAL NOT NULL DEFAULT 0,
  handler_episode_id TEXT NOT NULL DEFAULT '',
  idempotency_key TEXT NOT NULL,
  UNIQUE(task_environment_id, idempotency_key)
);

CREATE INDEX idx_control_signals_pending
  ON task_control_signals(task_environment_id, status, created_at);
```

### 4.10 `task_dead_letters`

不可自动恢复的问题进入死信/修复队列。

```sql
CREATE TABLE task_dead_letters (
  dead_letter_id TEXT PRIMARY KEY,
  task_environment_id TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  error_code TEXT NOT NULL,
  error_json TEXT NOT NULL DEFAULT '{}',
  repair_action TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE INDEX idx_dead_letters_status
  ON task_dead_letters(status, created_at);
```

## 5. 进度存储算法

### 5.1 进度不直接靠自然语言

任务进度由三层共同表达：

```text
task_events      = 发生过什么
task_environment = 当前进度投影
work_products    = 已交付什么
```

`progress_label` 可以是人类可读文本，但不能作为唯一进度事实。

### 5.2 事件驱动更新

每次状态变化必须走事务：

```text
BEGIN
  read task_environment current revision
  validate expected revision / transition
  insert task_events(event_seq = previous + 1)
  update task_environments snapshot fields
  update affected indexes
COMMIT
```

伪代码：

```python
def append_task_event(env_id, event_type, payload, expected_revision, idempotency_key):
    with transaction():
        env = select_env_for_update(env_id)
        if env.revision != expected_revision:
            raise RevisionConflict
        if event_exists(env_id, idempotency_key):
            return existing_event
        next_seq = latest_event_seq(env_id) + 1
        event = insert_event(env_id, next_seq, event_type, payload, idempotency_key)
        patch = reduce_event_to_snapshot(env, event)
        update_env(env_id, revision=env.revision + 1, **patch)
        return event
```

SQLite 没有 `SELECT FOR UPDATE`，实现时用 `BEGIN IMMEDIATE` 获取写锁。

### 5.3 进度字段

`task_environments` 的进度字段只保存当前投影：

```text
current_phase
current_step
progress_current
progress_total
progress_label
latest_work_product_id
continuation_hint
blocked_reason
recovery_action
```

来源规则：

- 图任务节点总量来自 GraphLoop / tree_reduce frame；
- 单任务阶段来自 task contract 的 phase plan；
- 文件审查类任务 `progress_total` 可由 physical shard count 填充；
- 没有确定总量时 `progress_total=0`，只显示 current_step，不伪造百分比。

### 5.4 进度查询

公开进度视图：

```text
TaskProgressView
  task_environment_id
  task_instance_id
  title
  status
  activity_state
  current_phase
  current_step
  progress_current
  progress_total
  progress_percent
  latest_work_product_refs
  blocked_reason
  recovery_action
  can_pause
  can_resume
  can_stop
  updated_at
```

算法：

```python
percent = None
if progress_total > 0:
    percent = min(100, round(progress_current * 100 / progress_total))
activity_state = map_environment_status_and_lease(env.status, active_lease)
control_capabilities = derive_control_capabilities(env, lease, latest_control_signal)
```

## 6. 查询算法

### 6.1 查询入口

必须提供四类查询：

```text
get_task_environment(task_environment_id)
list_task_environments(filters, cursor, limit)
search_task_environments(query, filters, cursor, limit)
lookup_graph_node_binding(graph_run_id, work_order_id)
```

### 6.2 列表查询

按稳定索引查询，不扫描 event log。

支持过滤：

```text
status
task_kind
project_id
owner_agent_id
session_id
graph_run_id
caller_kind
product_domain
product_kind
updated_before / updated_after
recoverable_only
active_only
```

分页：

```text
ORDER BY updated_at DESC, task_environment_id ASC
cursor = base64(updated_at, task_environment_id)
```

不用 offset 分页，避免大表翻页漂移。

### 6.3 文本搜索

第一阶段可用 SQLite `LIKE` 覆盖 title/goal/progress_label。

第二阶段启用 SQLite FTS5：

```sql
CREATE VIRTUAL TABLE task_environment_fts
USING fts5(task_environment_id UNINDEXED, title, goal, progress_label, continuation_hint);
```

更新策略：

- task_instance title/goal 变更时同步；
- task_environment progress_label/continuation_hint 变更时同步；
- WorkProduct 只入 summary，不把大 payload 入 FTS。

### 6.4 可恢复任务查询

```sql
SELECT *
FROM task_environments
WHERE status IN ('ready', 'paused', 'blocked')
  AND recovery_action <> ''
  AND task_environment_id NOT IN (
    SELECT task_environment_id
    FROM task_environment_leases
    WHERE status = 'active' AND expires_at > :now
  )
ORDER BY updated_at DESC
LIMIT :limit;
```

注意：

- `leased` 状态但 lease 过期，要先走 stale lease recovery；
- graph node 任务恢复要通过 graph binding，不能由普通 session 直接续跑。

## 7. Lease 与并发控制算法

### 7.1 acquire lease

```python
def acquire_lease(env_id, episode_id, lease_kind, idempotency_key, ttl):
    with begin_immediate():
        env = get_env(env_id)
        assert env.status in {'ready', 'paused', 'blocked'}
        active = get_unexpired_active_exclusive_lease(env_id)
        if active and active.idempotency_key != idempotency_key:
            raise LeaseConflict(active)
        if active and active.idempotency_key == idempotency_key:
            return active
        lease = insert_lease(...)
        update_env(status='leased', active_lease_id=lease.id, active_episode_id=episode_id)
        append_event('lease_acquired')
        return lease
```

### 7.2 heartbeat

episode 执行期间必须周期性心跳：

```text
model step 前
tool call 前
tool result 后
checkpoint 后
每 N 秒后台 heartbeat
```

伪代码：

```python
def heartbeat(lease_id):
    with transaction():
        lease = get_lease(lease_id)
        if lease.status != 'active':
            raise LeaseLost
        update heartbeat_at=now, expires_at=now+ttl
```

### 7.3 stale lease recovery

```python
def recover_stale_leases(now):
    leases = select active leases where expires_at < now
    for lease in leases:
        mark lease status='expired'
        mark episode status='interrupted'
        update env status='paused', recovery_action='resume_task_environment'
        append event 'lease_expired'
```

成熟要求：

- 不自动重放未确认副作用；
- 工具调用未结束时写 pending tool ref；
- 幂等工具才可自动 retry；
- 非幂等工具必须等待 agent / user / repair。

## 8. 停止、暂停、恢复算法

### 8.1 控制信号模型

控制不是直接改状态，而是写 `task_control_signals`。

```text
pause_requested
stop_requested
abort_requested
resume_requested
replan_requested
```

原因：

- 正在运行的 episode 需要在安全边界响应；
- stop/pause 是请求，真正完成要看 episode 是否写出 boundary；
- 这样可以审计谁在什么时候请求了控制。

### 8.2 pause

pause 是协作式暂停。

流程：

```text
API / user / graph control
-> insert task_control_signal(kind=pause_requested)
-> active episode poll_control_signal()
-> write checkpoint_summary + continuation_hint
-> append event episode_paused
-> release lease(reason=pause)
-> env.status = paused
```

pause 必须提供：

```text
checkpoint_summary
continuation_hint
current_step
pending_questions
unsafe_to_retry_refs
```

禁止：

- 无 checkpoint summary 的 pause；
- pause 后继续启动新 tool；
- pause 时把未知工具副作用标记为完成。

### 8.3 stop

stop 是正常停止，不再继续该 episode。

流程：

```text
insert stop_requested
-> episode reaches safe boundary
-> write interrupted/stop boundary
-> release lease(reason=stopped)
-> env.status = blocked 或 aborted
```

状态选择：

- 用户只是暂停当前工作：用 `paused`；
- 用户明确停止但未来可能重开：用 `blocked` + `recovery_action=''`；
- 用户明确取消：用 `aborted`。

### 8.4 abort

abort 是强终止。

流程：

```text
insert abort_requested
-> mark env.status='aborted'
-> mark active lease='revoked'
-> mark active episode='aborted'
-> append event task_aborted
-> if graph-bound: project NodeResultEnvelope(status='failed' or 'blocked')
```

要求：

- abort 不保证外部工具已停止；
- 如果 tool 支持 cancel，调用 cancel；
- 如果 tool 不支持 cancel，记录 `unknown_external_side_effect` dead letter；
- graph-bound abort 必须通知 GraphLoop，不能让 active_work_order 永久悬挂。

### 8.5 resume

resume 必须从 durable boundary 开始。

流程：

```text
load task_environment
-> recover stale leases
-> validate status in paused/blocked/ready
-> validate graph binding if graph-bound
-> build TaskContextPackage from snapshot + latest events + work products + refs
-> acquire lease
-> create AgentExecutionEpisode
-> run through harness
-> reduce EpisodeResult
```

resume 不允许：

- 恢复 provider stream；
- 直接从旧 transcript 继续；
- 绕过 graph binding 恢复 graph node；
- 自动重试非幂等工具。

## 9. Checkpoint / Save Point 算法

### 9.1 checkpoint 分类

```text
context_checkpoint
  TaskContextPackage 已构建，可复现输入。

episode_checkpoint
  episode 当前阶段、latest event、latest tool observation。

work_product_checkpoint
  WorkProduct 已写入，可被 reducer 重放。

graph_binding_checkpoint
  graph node binding 与 work_order 可恢复。

pause_boundary
  agent 明确给出 checkpoint_summary 和 continuation_hint。
```

### 9.2 写入时机

必须写 checkpoint：

- episode 开始后；
- 每个工具结果后；
- 每个 WorkProduct 写入后；
- pause / stop / abort 边界；
- graph node result projection 前；
- reducer commit 后。

可选写 checkpoint：

- 长模型步骤前；
- 大文件证据读取后；
- 子任务批次完成后。

### 9.3 checkpoint 内容

```text
checkpoint_id
task_environment_id
episode_id
event_seq
context_package_id
latest_work_product_ids
latest_artifact_refs
pending_tool_refs
continuation_hint
hashes
created_at
```

大 payload 一律存 ref，不直接塞 checkpoint 表。

## 10. TaskContextPackage 构建算法

### 10.1 输入来源

```text
TaskEnvironment snapshot
TaskInstance goal / acceptance
latest WorkProducts
TaskMemory refs
ProjectNetwork refs
File/AST refs
GraphNodeTaskBinding
latest control signal
continuation_hint
```

### 10.2 构建步骤

```python
def build_context_package(env_id, episode_id):
    env = get_env(env_id)
    instance = get_instance(env.task_instance_id)
    stable = build_stable_context(instance, env)
    current = build_current_context(env, latest_events(env_id), latest_control_signal(env_id))
    refs = select_relevant_refs(env)
    graph = build_graph_context(env) if graph_bound(env) else {}
    package_hash = stable_hash(stable, current, refs, graph)
    store_large_payloads_as_refs()
    insert task_context_packages(...)
    return package
```

### 10.3 裁剪规则

- stable facts 进 stable context；
- 当前步骤、控制信号、最新观察进 current context；
- 历史产物只给 ref；
- 文件内容默认不进入，除非节点契约明确 `file_text_provided`；
- graph node 只看自己的直接输入和父层摘要，不展开全图。

## 11. Episode 执行算法

目标链：

```text
TaskEnvironmentLease
-> TaskContextPackage
-> RuntimeCompiler.compile_task_episode_packet()
-> harness single-agent execution
-> EpisodeResult
-> TaskReducer
```

伪代码：

```python
def run_task_episode(env_id, request):
    recover_stale_leases()
    episode = create_episode(...)
    lease = acquire_lease(env_id, episode.id, ...)
    package = build_context_package(env_id, episode.id)
    mark_episode_running(episode, package)
    result = harness.run_single_agent_episode(package)
    reduce_episode_result(env_id, episode.id, result)
```

要求：

- harness 是唯一模型/tool loop；
- episode 不直接写最终 task state；
- 输出必须先变成 EpisodeResult；
- reducer 决定哪些写入任务状态、记忆、WorkProduct 和 GraphLoop。

## 12. Reducer 算法

### 12.1 reducer 输入

```text
EpisodeResult
WorkProduct candidates
state update proposals
memory candidates
artifact refs
graph binding ref
acceptance claims
```

### 12.2 reducer 步骤

```python
def reduce_episode_result(env_id, episode_id, result):
    with begin_immediate():
        env = get_env(env_id)
        validate_episode_owns_active_lease(env, episode_id)
        products = normalize_work_products(result.work_product_candidates)
        products = apply_product_reducer_policy(products)
        upsert_work_products(products)
        state_patch = validate_state_update(result.state_update_proposals)
        append_event('episode_result_reduced', refs=products)
        update_env_from_reduction(state_patch, latest_product=products[-1])
        if graph_bound(env):
            node_result = project_node_result(env, result, products)
            store pending node_result_ref
        release_lease(env.active_lease_id)
```

### 12.3 WorkProduct reducer policies

```text
append_by_work_product_id
  用于审计记录、报告。

merge_by_stable_ref
  用于语义坐标、文件模块卡。

replace_by_generation
  用于项目网络 generation 发布候选。

reject_on_anchor_mismatch
  用于物理 ref 不匹配的语义关系。

merge_scope_coverage
  用于目录覆盖率、审查完成度。
```

### 12.4 不允许 reducer 做的事

- 从自然语言 final answer 反解析结构事实；
- 将 candidate 自动升级 accepted；
- 替 agent 补证据；
- 忽略 anchor mismatch；
- 绕开项目网络 curator 直接 publish generation。

## 13. Graph 节点集成算法

### 13.1 bind

```python
def bind_graph_node_work_order(work_order):
    idempotency_key = work_order.idempotency_key
    existing = get_binding_by_work_order(work_order.graph_run_id, work_order.work_order_id)
    if existing:
        return existing
    env = create_task_environment(caller_kind='graph_node', task_ref=work_order.task_ref)
    binding = insert_graph_node_task_binding(...)
    append_event('graph_node_bound')
    return binding
```

### 13.2 execute

```text
GraphNodeWorkOrder
-> GraphNodeTaskBinding
-> run_task_episode(node_task_environment_id)
-> reducer creates WorkProduct
-> reducer projects NodeResultEnvelope
-> GraphLoop.accept_node_result()
```

### 13.3 interruption

如果 graph node episode 可恢复：

```text
env.status = paused / blocked
binding.status = waiting_resume
GraphLoop active_work_order 保留
GraphResumeService 重连 active work order
```

如果 graph node episode 不可恢复：

```text
project NodeResultEnvelope(status='failed' or 'blocked')
GraphLoop.accept_node_result()
binding.status = completed_with_failure
```

禁止 active work order 无期限悬挂。超过 lease TTL 后必须进入 stale lease recovery 或 NodeResultEnvelope 失败投影。

## 14. 死信与修复

进入 `task_dead_letters` 的情况：

- 非法状态转移；
- stale lease 无法确认副作用；
- context package 构建失败；
- WorkProduct anchor mismatch；
- NodeResultEnvelope projection 失败；
- GraphLoop accept result 失败；
- project_network ingest 失败；
- 非幂等工具中断后状态未知。

dead letter 处理：

```text
open
-> repair_queued
-> repair_running
-> resolved / ignored / escalated
```

修复入口：

```text
TaskDeadLetter
-> RepairWorkItem
-> RepairTaskEnvironment
-> AgentExecutionEpisode
-> WorkProduct
-> same generation lineage
```

这与项目网络 repair / maintenance 同源，不另建补丁链路。

## 15. API / Service 方案

### 15.1 后端 service

新增：

```text
backend/task_system/work_environments/repository.py
backend/task_system/work_environments/service.py
backend/task_system/work_environments/query_service.py
backend/task_system/work_environments/control_service.py
backend/task_system/work_environments/context_package_builder.py
backend/task_system/episodes/service.py
backend/task_system/work_products/reducer.py
backend/task_system/graph_bindings/service.py
```

### 15.2 service 方法

```text
TaskWorkEnvironmentService.create_task_environment()
TaskWorkEnvironmentService.get()
TaskWorkEnvironmentService.append_event()
TaskWorkEnvironmentService.acquire_lease()
TaskWorkEnvironmentService.heartbeat()
TaskWorkEnvironmentService.release_lease()
TaskWorkEnvironmentService.recover_stale_leases()

TaskEnvironmentQueryService.list()
TaskEnvironmentQueryService.search()
TaskEnvironmentQueryService.list_resumable()
TaskEnvironmentQueryService.progress_view()

TaskEnvironmentControlService.request_pause()
TaskEnvironmentControlService.request_stop()
TaskEnvironmentControlService.request_abort()
TaskEnvironmentControlService.request_resume()

TaskEpisodeService.start_episode()
TaskEpisodeService.finish_episode()
TaskEpisodeService.interrupt_episode()

TaskReducer.reduce_episode_result()
GraphNodeTaskBindingService.bind_work_order()
GraphNodeTaskBindingService.project_node_result()
```

### 15.3 API 草案

```text
GET  /api/task-environments
GET  /api/task-environments/{id}
GET  /api/task-environments/{id}/events
GET  /api/task-environments/{id}/work-products
POST /api/task-environments/{id}/pause
POST /api/task-environments/{id}/stop
POST /api/task-environments/{id}/abort
POST /api/task-environments/{id}/resume
GET  /api/task-environments/resumable
```

API 不直接暴露内部 event mutation，只调用 service。

## 16. UI / 前端投影

任务列表不展示原始 event log，而展示 `TaskProgressView`。

推荐视图：

```text
任务标题
状态
当前阶段/步骤
进度 current/total
最新产物
阻塞原因
可恢复/可暂停/可停止按钮
所属项目 / 图运行 / session binding
更新时间
```

任务详情页：

```text
Overview: goal / status / progress / controls
Timeline: task_events
Episodes: each AgentExecutionEpisode
Products: WorkProduct list
Evidence: artifact refs / file refs
Graph: graph binding / work_order / node result
Repair: dead letters / repair items
```

## 17. 迁移计划

### Phase 1：只读模型和 SQLite store

新增 schema、repository、query service。  
不接执行链。

完成标准：

- 可以创建/读取 task environment；
- 可以 append event 并更新 snapshot；
- 可以 list/search/resumable 查询。

### Phase 2：request_task_run 创建任务环境

把 `request_task_run` 从 cut receipt 接到 `TaskWorkEnvironmentService.create_task_environment()`。  
不启动旧 executor。

完成标准：

- agent 能得到 `task_environment_id`；
- session 只拿 binding receipt；
- runtime state index 只保存轻量投影。

### Phase 3：episode + context package

实现 `TaskContextPackageBuilder` 和 `AgentExecutionEpisode`。  
compiler 新增 `compile_task_episode_packet()`。

完成标准：

- 继续任务不依赖完整 transcript；
- context package hash 可追踪；
- stable/current/refs 分层明确。

### Phase 4：lease/control/checkpoint

实现 acquire、heartbeat、stale recovery、pause、stop、abort、resume。

完成标准：

- pause 必须写 continuation hint；
- stop/abort 不留 active lease；
- stale lease 可恢复或进入 dead letter。

### Phase 5：reducer/work product

实现通用 WorkProduct store 和 reducer。

完成标准：

- assistant final answer 不再直接成为结构产物；
- WorkProduct 可投影给 project_network_system；
- candidate/accepted/published 不混淆。

### Phase 6：graph node binding

把 `GraphNodeWorkOrder` 执行改接 `GraphNodeTaskBindingService`。

完成标准：

- 旧 `_create_graph_node_task_run()` 不再是主线；
- graph node 任务能恢复；
- NodeResultEnvelope 来自 reducer projection。

### Phase 7：清理旧链路

清理旧 task_executor 主执行权威和重复状态视图。

完成标准：

- 没有第二 model loop；
- 没有第二 tool authorization path；
- 没有旧 TaskRun 被当作任务真相。

## 18. 验证矩阵

按项目规则，不新增回归测试文件。实施时用代码审查和真实运行验证。

### 18.1 静态检查

```powershell
rg -n "TaskWorkEnvironmentService|TaskEnvironmentQueryService|TaskReducer|GraphNodeTaskBindingService" backend
rg -n "_create_graph_node_task_run|execute_task_run\\(" backend/harness backend/graph_system
rg -n "call_model_invoker|call_model_streamer" backend/harness/loop/task_executor.py
python -m compileall backend/task_system backend/harness backend/graph_system
```

### 18.2 真实运行场景

固定后端端口：

```text
backend: http://127.0.0.1:8003
frontend: http://127.0.0.1:3000
```

场景：

1. 创建任务环境后能查询列表和详情。
2. append event 后 snapshot 进度更新。
3. acquire lease 后第二个 exclusive lease 被拒绝。
4. heartbeat 延长 lease。
5. stale lease 能转 interrupted/paused。
6. pause 写 checkpoint summary 和 continuation hint。
7. resume 从 TaskContextPackage 继续。
8. graph node work order 绑定任务环境。
9. reducer 生成 WorkProduct 和 NodeResultEnvelope。
10. project network build 能通过 WorkProduct 发布 generation。

## 19. 严禁反模式

1. 用单个 JSON 文件保存所有任务运行状态。
2. 用 session transcript 当任务恢复源。
3. 用 assistant message 当结构化 WorkProduct。
4. stop/pause 直接杀状态，不写控制信号和边界事件。
5. lease 过期后自动重试非幂等工具。
6. GraphLoop active_work_order 永久悬挂。
7. reducer 从自然语言报告反解析结构事实。
8. task_system 保存 project_network generation。
9. graph_system 保存项目网络长期资产。
10. 旧 task_executor 包一层继续跑模型。
11. 没有 idempotency_key 的事件写入。
12. 没有 revision 检查的状态更新。

## 20. 最终裁决

新任务系统不是“更复杂的 turn 管理器”，而是一套持久工作环境运行系统。

它的实现核心是：

```text
SQLite canonical store
append-only event ledger
materialized task snapshot
lease + heartbeat
checkpoint + context package
episode through harness
reducer writes WorkProduct
graph binding projects NodeResultEnvelope
query service exposes progress
dead letter drives repair
```

只有这些工程细节都成立，任务环境才能真正区别于普通 turn，并给 agent 带来稳定的跨 session、图任务、项目控制网络和长期维护能力。
