# Runtime Monitor 监控系统 — 详细技术报告

> 编写日期：2026-06-15
> 审查范围：`backend/harness/runtime/run_monitor/` 全部 11 个源文件
> 报告作者：洪荒智能

---

## 一、整体架构概览

监控系统是 Harness Runtime 的**运行时任务可视化与行为管理**基础设施，位于 `backend/harness/runtime/run_monitor/`。它负责将底层的任务运行记录、事件日志、活动状态等信息投影（project）为前端可消费的监控视图，并提供暂停、停止、清除、删除等管理操作。

### 架构总图

```
┌──────────────────────────────────────────────────────────────────────┐
│                         RuntimeMonitorService                        │
│                     (service.py — 服务入口层)                         │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │                    RuntimeMonitorProjector                    │   │
│   │                   (projector.py — 投影核心)                    │   │
│   │  task_run → project_task_run() → 完整的 monitor item 字典      │   │
│   │  global/session/task/active_turn 四种视图构建                   │   │
│   └──────────────────────────────────────────────────────────────┘   │
│                          │                                            │
│   ┌──────────┐  ┌───────┴───────┐  ┌──────────────┐  ┌───────────┐  │
│   │ signals  │  │   contract    │  │  management   │  │  actions  │  │
│   │ 信号投影  │  │   契约构建    │  │  管理策略     │  │  操作执行  │  │
│   └──────────┘  └───────────────┘  └──────────────┘  └───────────┘  │
│                          │                                            │
│   ┌──────────────┐  ┌─────────────────┐  ┌──────────────────────┐   │
│   │   activity   │  │ resource_resolver│  │   retention_store    │   │
│   │ 活动状态模型  │  │   资源解析器     │  │  隐藏/保留存储       │   │
│   └──────────────┘  └─────────────────┘  └──────────────────────┘   │
│                          │                                            │
│   ┌──────────────┐                                                    │
│   │  lifecycle   │  状态常量 + 生命周期函数                            │
│   └──────────────┘                                                    │
└──────────────────────────────────────────────────────────────────────┘
```

### 数据流主线

```
TaskRun 记录
    │
    ▼
RuntimeMonitorProjector.project_task_run()
    │ 读取: event_log, diagnostics, state_view, graph_monitor
    │ 计算: status, lifecycle, bucket, activity_state
    │ 聚合: fact_summary, trace_summary, artifact_refs
    │ 投影: 100+ 字段的 monitor item 字典
    │
    ▼
with_runtime_activity(item)  — 注入 activity 状态和控制能力
    │
    ▼
build_envelope / build_runtime_monitor_envelope / apply_management
    │ 分桶、管理策略、隐藏过滤
    │
    ▼
前端消费（global / session / task 监控视图）
```

---

## 二、模块详解

### 2.1 生命周期（`lifecycle.py` — 2.6 KB）

最底层的状态常量和函数定义。

**状态常量：**

| 常量 | 值 |
|------|-----|
| `RUNNING_TASK_RUN_STATUSES` | `{"created", "running"}` |
| `WAITING_TASK_RUN_STATUSES` | `{"waiting_executor", "waiting_approval"}` |
| `BLOCKED_TASK_RUN_STATUSES` | `{"blocked"}` |
| `FAILED_TASK_RUN_STATUSES` | `{"failed", "aborted", "cancelled", "error"}` |
| `COMPLETED_TASK_RUN_STATUSES` | `{"completed", "success"}` |
| `TERMINAL_TASK_RUN_STATUSES` | `COMPLETED \| FAILED` |
| `GLOBAL_MONITOR_BUCKETS` | `("running", "waiting", "completed", "failed", "diagnostics")` |

**核心函数：**

| 函数 | 作用 |
|------|------|
| `runtime_control(diagnostics)` | 从 diagnostics 中提取运行时控制状态（state, requested_by, requested_at, reason） |
| `task_lifecycle(status, stale, action_required, control_state)` | 将 raw status 映射为语义生命周期：`completed` / `failed` / `paused` / `running` / `waiting` / `stale` / `action_required` |
| `monitor_bucket(lifecycle)` | 将生命周期映射到监控分桶：`running` → `"running"`, `failed` → `"failed"`, `paused`/`stale` → `"diagnostics"` |
| `ended_at(status, updated_at, last_activity_at, resource_class)` | 计算结束时间，`dynamic` 资源类返回 `None`（表示仍在运行） |
| `is_terminal_status(status)` | 判断是否终端状态 |

**生命周期决策链：**
```
status → task_lifecycle() → lifecycle
                                ↓
                            monitor_bucket() → bucket
                                ↓
                            ended_at() → ended timestamp
```

---

### 2.2 契约构建（`contract.py` — 4.9 KB）

负责构建监控系统的标准信封（envelope）结构和导航目标。

**核心函数：**

| 函数 | 作用 |
|------|------|
| `monitor_revision(items, now)` | 基于所有项的 `task_instance_id:status:bucket:last_activity_at` 生成 SHA256 摘要（12 位 hex），格式 `rtmon:{timestamp}:{digest}` |
| `build_envelope(scope, items, now, limit, selected, extra)` | 构建标准监控信封：按 5 个桶分桶排序、统计各桶数量、生成 revision |
| `build_task_detail_envelope(item, now)` | 构建单个任务详情信封 |
| `build_navigation_target(kind, task_instance_id, ...)` | 构建导航目标：`task_graph` → graph_monitor 模式，`agent_run` → conversation 模式 |

**信封结构示例：**
```python
{
    "authority": "runtime_monitor.v1",
    "scope": "global",  # "session" / "task_run"
    "revision": "rtmon:1747350000:a1b2c3d4e5f6",
    "updated_at": 1747350000.0,
    "bucket_limit": 20,
    "summary": {"total": 5, "running": 2, "waiting": 1, ...},
    "buckets": {"running": [...], "waiting": [...], ...},
    "items": [...],  # 按桶排序后的可见项
    "task_runs": [...],
    "selected": {...},  # session 视图的当前选中项
    "events": [],
}
```

---

### 2.3 活动状态模型（`activity.py` — 10 KB）

定义任务项的**行为活动状态**（activity state），是通往前端可视化状态的桥梁。

**核心类型：**

```python
ActivityState = Literal["running", "waiting", "paused", "stopped", "failed", "completed", "stale", "idle"]
ActivityTone = Literal["active", "neutral", "attention", "done"]
SignalState  = Literal["active", "waiting", "attention", "completed", "failed", "stale"]
```

**RuntimeActivity 结构：**
```python
class RuntimeActivity(TypedDict):
    activity_state: ActivityState
    activity_label: str          # "运行中" / "已暂停" / "等待确认" / "失败" / ...
    is_running: bool
    is_waiting: bool
    is_resumable: bool
    is_interruptible: bool
    control_reason: str
    tone: ActivityTone
```

**状态推导函数 `activity_state(item)`：**
1. 检查 `terminal_reason` 是否在 `STOPPED_REASONS` → `"stopped"`
2. 检查 `status` 是否在 `FAILED_STATUSES` 或 `lifecycle=="failed"` → `"failed"`
3. 检查是否 `COMPLETED_STATUSES` → `"completed"`
4. 检查 `control_state == "paused"` → `"paused"`
5. 检查 `lifecycle == "stale"` → `"stale"`
6. 检查 `WAITING_STATUSES` / `action_required` → `"waiting"`
7. 检查 `RUNNING_STATUSES` / `is_live` → `"running"`
8. 默认 `"idle"`

**控制能力判定：**

| 函数 | 判定逻辑 |
|------|---------|
| `_is_resumable(item, state, control_context)` | 优先 `control_context`，其次 `control_capability.can_resume_task`，最后检查是否 `paused` 状态 |
| `_is_interruptible(item, state, control_context)` | 优先 `control_context`，其次 `control_capability.can_pause_task`，排除 `turnrun:` 和 `single_agent_turn` |

**辅助函数：**

| 函数 | 作用 |
|------|------|
| `with_runtime_activity(item, control_context)` | 将 activity 注入到 item 字典，同时更新 `control_capability` |
| `signal_state_from_activity(activity)` | 将 `ActivityState` 映射为 `SignalState` |
| `activity_sort_rank(item)` | 返回排序权重：running=7 > paused=6 > waiting=5 > stale=4 > failed=3 > stopped=2 > completed=1 |
| `activity_is_monitor_visible(item)` | 判断是否应在监控中显示：running/waiting/paused/stale/action_required |

---

### 2.4 投影核心（`projector.py` — 80 KB，最大的文件）

**核心类：`RuntimeMonitorProjector`**

这是整个监控系统的**大脑**，将底层任务运行记录投影成前端可消费的字典。

**构造函数参数：**
```python
RuntimeMonitorProjector(
    event_log,                     # 事件日志
    runtime_host=None,             # 运行时宿主
    freshness_seconds=300.0,      # 新鲜度窗口（5 分钟）
    resource_resolver=None,        # 资源解析器
    session_scope_resolver=None,   # 会话作用域解析器
    observability_query=None,      # 可观测性查询
    fact_ledger=None,              # 事实账本
    trace_service=None,            # 追踪服务
)
```

**主要方法：**

| 方法 | 作用 |
|------|------|
| `project_task_run(task_run, now, ...)` | **核心方法**：将一个 TaskRun 对象投影为 100+ 字段的 monitor item 字典 |
| `build_global_monitor(task_runs, now, limit)` | 构建全局监控视图，过滤 `_is_internal_child_run` 和 `_is_global_live_task_run_candidate` |
| `build_session_monitor(session_id, task_runs, now, limit)` | 构建会话级监控视图，自动将最活跃项展开为详细模式 |
| `build_task_monitor(task_run, now)` | 构建单任务监控详情 |
| `project_active_turn(active_turn, turn_run, runtime_run, now)` | 将当前活跃的 turn（对话轮次）投影为监控项 |
| `build_turn_monitor(...)` | 构建 turn 监控详情 |
| `select_current_items_by_session(items)` | 按会话去重，每个会话只保留最高优先级的项 |

**`project_task_run()` 流程：**
1. 获取 `task_run_id`, `session_id`, `diagnostics`
2. 读取 `_recent_events()`（最近 240 条事件）
3. 计算 `latest_event`, `latest_step`, `last_activity_at`, `last_activity_age_seconds`
4. 读取 `task_run_state_view()` 获取状态视图
5. 提取 `runtime_control`, `control_state`, `control_capability`, `activity`
6. 通过 `_route()` 和 `_session_scope()` 解析路由和作用域
7. 判断 `stale`（超过 5 分钟无活动且非 paused 且非 graph_runtime_active）
8. 判断 `action_required`（waiting_approval / blocked / paused）
9. 运行 `_diagnostic_reasons()` 生成诊断原因
10. 计算 `lifecycle`, `bucket`, `resource_class`, `ended_at`, `duration_seconds`
11. 聚合 `artifact_refs`, `fact_summary`, `trace_summary`, `diagnostic_signal_refs`
12. 构建 `latest_progress` 和 `navigation_target`
13. 组装 100+ 字段的 item 字典
14. 调用 `with_runtime_activity()` 注入活动状态

**辅助函数：**

| 函数 | 作用 |
|------|------|
| `_latest_interaction_turn_id()` | 从事件中解析最新交互 turn ID |
| `_human_duration()` | 将秒数格式化为人类可读时长 |
| `_compact_trace_run()` / `_compact_trace_span()` | 压缩追踪运行数据 |
| `_artifact_refs_from_event_log()` | 从事件日志中提取交付物引用 |
| `_fact_scope_ref()` | 解析事实作用域引用 |

---

### 2.5 信号系统（`signals.py` — 13 KB）

将监控项投影为**前端信号**格式，用于 UI 仪表盘展示。

**核心函数：**

| 函数 | 作用 |
|------|------|
| `build_runtime_monitor_envelope(items, now, limit)` | 将监控项转换为信号信封，按优先级 + 最后活动时间排序，分 primary / attention / recent / projects 组 |
| `project_monitor_signal(item, now)` | 将一个监控项投影为信号字典（40+ 字段） |

**信号字段结构：**
```python
{
    "signal_id": "...",          # task_instance_id or task_run_id
    "source_kind": "turn_run" / "graph_run" / "task_run",
    "work_kind": "graph_task" / "chat_turn" / "agent_task",
    "state": "active" / "waiting" / "attention" / "completed" / "failed" / "stale",
    "priority": 100,             # active turn=100, active task=95, waiting=80, stale=70, failed=60, completed=20
    "title": "...",
    "line": "...",
    "detail": {...},
    "activity": {...},
    "control_capability": {...},
    "navigation_target": {...},
    "detail_ref": {...},
    "graph_ref": {...},
    "fact_summary": {...},
    "trace_summary": {...},
    "timestamps": {"started_at", "updated_at", "last_activity_at", "elapsed_seconds"},
}
```

**信号优先级策略：**
| 状态 | source_kind=turn_run | source_kind=task_run/graph_run |
|------|---------------------|-------------------------------|
| active | 100 | 95 |
| waiting | 80 | 80 |
| stale | 70 | 70 |
| failed | 60 | 60 |
| completed | 20 | 20 |
| 其他 | 50 | 50 |

**来源分类：**
- `turn_run` — `execution_runtime_kind == "single_agent_turn"` 或 `task_run_id` 以 `turnrun:` 开头
- `graph_run` — 有 `graph_run_id`
- `task_run` — 其他

**工作分类：**
- `graph_task` — `kind == "task_graph"` 或包含 `graph_run_id`
- `chat_turn` — `source_kind == "turn_run"`
- `agent_task` — 其他

---

### 2.6 管理策略（`management.py` — 14 KB）

负责对监控信号进行**容量管理、可见性控制和隐藏处理**。

**策略配置（`RuntimeMonitorManagementPolicy`）：**
```python
@dataclass(frozen=True)
class RuntimeMonitorManagementPolicy:
    active_max: int = 5                    # 活跃信号上限
    attention_max: int = 12                # 关注信号上限
    project_max: int = 8                   # 项目信号上限
    recent_max: int = 12                   # 最近完成信号上限
    recent_ttl_seconds: int = 30 * 60      # 最近完成的 TTL（30 分钟）
    hidden_retention_seconds: int = 7 * 24 * 60 * 60  # 隐藏后的保留时间（7 天）
```

**核心类：`RuntimeMonitorManagementProjector`**

| 方法 | 作用 |
|------|------|
| `apply_management(envelope, now, source_items)` | 应用管理逻辑：隐藏过滤、容量裁剪、分 lane、更新摘要 |
| `_enrich_signal(signal, source_index, hidden_index)` | 丰富信号：添加 `visibility` 和 `actions` 字段 |
| `_apply_capacity(signals, revision, now)` | 容量裁剪：如果 `recent` 超过上限，将超出部分按最后活动时间排序后隐藏（TTL 7 天） |

**Lane 分类：**
| Lane | 条件 |
|------|------|
| `current` | `is_running == True` 或 `state == "active"` |
| `attention` | 非 current 非 completed 非 graph_task |
| `projects` | `work_kind == "graph_task"` |
| `recent` | `state == "completed"` |
| `hidden` | 用户手动隐藏或被容量裁剪自动隐藏 |

**可见性控制：** 每个信号都带有一个 `visibility` 字段，包含 `visible`、`lane`、`hidden`、`hidden_reason`、`expires_at` 等。

**操作（Actions）生成：**
基于信号的状态和能力，为每个信号生成可用的操作列表（如 `pause_task`、`stop_task`、`clear_from_monitor`、`delete_record` 等），UI 据此渲染操作按钮。

---

### 2.7 操作执行（`actions.py` — 18 KB）

**核心类：`RuntimeMonitorActionService`**

提供实际的监控操作执行逻辑，支持以下操作：

| 操作 | 方法 | 说明 |
|------|------|------|
| `clear_from_monitor` | `_clear_from_monitor()` | 向 `retention_store` 写入 hide 记录 |
| `restore_to_monitor` | `_restore_to_monitor()` | 向 `retention_store` 写入 unhide 记录 |
| `close_runtime` | `_close_runtime()` | stop + hide 组合操作 |
| `delete_record` | `_delete_record()` | 使用 `TaskRecordLifecycleManager` 删除任务记录 |
| `pause_task` | `_pause_task()` | 暂停任务 |
| `stop_task` | `_stop_task()` | 停止任务 |
| `preview_delete_record` | `_preview_effects()` | 预览删除效果（状态、影响范围） |
| `preview_delete_graph_run` | `_preview_effects()` | 预览图运行删除效果 |

**执行流程：**
1. `execute(payload)` 调用 `preflight()` 进行前置检查
2. 检查动作是否 enabled、信号是否存在、source_revision 是否新鲜
3. 执行具体操作
4. 成功后调用 `invalidate_global_monitor_cache()` 清除全局缓存
5. 返回包含 effects 和最新 monitor 的完整结果

---

### 2.8 服务层（`service.py` — 21 KB）

**核心类：`RuntimeMonitorService`**

监控系统的**服务入口**，组装所有子模块。

**构造函数参数：**
```python
RuntimeMonitorService(
    runtime_host,                          # 运行时宿主
    graph_harness=None,                    # 图执行引擎
    freshness_seconds=300.0,               # 新鲜度窗口
    global_monitor_cache_seconds=1.0,      # 全局监控缓存 TTL
    retention_sweep_interval_seconds=30.0, # 过期回收间隔
)
```

**内部子模块：**
- `self.resource_resolver` — `MonitorResourceResolver`
- `self.projector` — `RuntimeMonitorProjector`
- `self.retention_store` — `RuntimeMonitorRetentionStore`
- `self.management_projector` — `RuntimeMonitorManagementProjector`
- `self.lifecycle_retention` — `TaskRunLifecycleRetention`

**主要方法：**

| 方法 | 作用 |
|------|------|
| `list_global_live_monitor(limit)` | 快速列出全局活跃监控项（轻量，仅 live items） |
| `collect_global_runtime_monitor(limit)` | 收集全局运行时监控（含信号投影和管理），**带缓存**（1 秒 TTL） |
| `get_session_live_monitor(session_id, limit)` | 获取会话级活跃监控，自动查找当前活跃 turn |
| `get_session_task_summary(session_id)` | 获取会话级任务摘要 |
| `get_task_run_live_monitor(task_run_id)` | 获取单任务运行监控详情 |
| `get_resource(...)` | 获取资源详情 |
| `invalidate_global_monitor_cache()` | 手动清除全局监控缓存 |
| `_sweep_expired_task_runs(now, limit)` | 周期性回收过期任务运行（默认 30 秒间隔） |

**缓存策略：**
- 全局监控缓存基于 `(limit, state_index_meta_mtime_ns, state_index_meta_size)` 的元组作为 key
- 缓存 TTL 默认 1 秒（`global_monitor_cache_seconds`）
- 过期条目在写入新缓存时自动清理
- 任何成功执行的操作都会触发 `invalidate_global_monitor_cache()`

---

### 2.9 资源解析器（`resource_resolver.py` — 6.7 KB）

**核心类：`MonitorResourceResolver`**

负责将任务运行中的引用（task_run / session / graph_run / artifact）解析为可消费的资源描述。

| 方法 | 作用 |
|------|------|
| `task_run_ref(task_run_id, label, available)` | 构建任务运行引用，检测是否存在 |
| `session_ref(session_id, label)` | 构建会话引用 |
| `graph_run_ref(graph_run_id, label, available)` | 构建图运行引用，通过 `graph_harness.get_graph_run()` 检测可用性 |
| `graph_config_ref(graph_harness_config_id, ...)` | 构建图配置引用，通过 `TaskFlowRegistry` 检测 |
| `artifact_refs(refs, resolve_availability)` | 构建交付物引用列表，检测文件是否存在 |
| `graph_monitor(graph_run_id, ...)` | 获取子图运行的监控快照 |

**资源描述格式：**
```python
{
    "ref": "task_run:xxx",
    "kind": "task_run",    # session / graph_run / artifact
    "id": "xxx",
    "label": "任务运行",
    "availability": {
        "state": "available" / "missing",
        "reason": "" / "task_run_missing",
        "checked_at": 1747350000.0,
    },
    "detail_endpoint": "/api/orchestration/runtime-monitor/resources/task_run:xxx",
}
```

---

### 2.10 保留存储（`retention_store.py` — 6.5 KB）

**核心类：`RuntimeMonitorRetentionStore`**

负责管理用户从监控视图中**隐藏的信号**，基于 JSONL 文件 + Windows 文件锁。

**存储位置：** `{runtime_state_dir}/runtime_monitor/hidden_signals.jsonl`

**核心方法：**

| 方法 | 作用 |
|------|------|
| `hidden_index(now)` | 读取当前未过期的隐藏记录，构建 `{signal_id: row}` 索引 |
| `hide_signal(signal_id, task_run_id, ...)` | 写入 hide 记录，支持 `ttl_seconds`（过期时间） |
| `unhide_signal(signal_id, ...)` | 写入 unhide 记录 |

**存储格式：**
```json
{"authority": "runtime_monitor.retention_store", "action": "hide", "signal_id": "...", "task_run_id": "...", "hidden_at": 1747350000.0, "expires_at": 1747954800.0, ...}
```

**文件锁机制：**
- 使用 `msvcrt.locking()` 实现 Windows 级文件锁
- 锁文件路径：`.hidden_signals.jsonl.lock`
- 在锁保护下追加写入，写入后自动 compact（超过 256KB 时重建）

**Compact 策略：** 当 `hidden_signals.jsonl` 超过 256KB 时，读取当前有效索引，覆盖写入去重压缩后的内容。

---

### 2.11 包入口（`__init__.py` — 534 字节）

导出 6 个核心类：
```python
__all__ = [
    "RuntimeMonitorActionService",
    "RuntimeMonitorManagementProjector",
    "RuntimeMonitorProjector",
    "RuntimeMonitorRetentionStore",
    "RuntimeMonitorService",
    "TaskRunLifecycleRetention",  # 来自外部模块
]
```

---

## 三、关键数据流

### 3.1 全局监控数据流

```
list_global_live_monitor() / collect_global_runtime_monitor()
    │
    ├── _sweep_expired_task_runs()  — 回收过期任务（30 秒间隔）
    │
    ├── _recent_task_run_summaries()  — 读取最近任务摘要
    │
    ├── project.build_global_monitor()
    │   ├── 过滤 internal_child_run + global_live_task_run_candidate
    │   ├── project_task_run() 批量投影（轻量模式）
    │   └── select_current_items_by_session() 按会话去重
    │
    ├── _recent_terminal_items()  — 补充最近完成的终端任务（collect 模式）
    │
    ├── _global_active_turn_items()  — 补充当前活跃轮次
    │
    ├── [collect 模式] build_runtime_monitor_envelope()
    │   └── 每个 item → project_monitor_signal() → 信号字典
    │
    └── [collect 模式] management_projector.apply_management()
        └── 隐藏过滤 + 容量裁剪 + 分 lane
```

### 3.2 会话监控数据流

```
get_session_live_monitor(session_id, limit)
    │
    ├── _session_task_run_summaries(session_id)
    │
    ├── project.build_session_monitor()
    │   ├── 过滤 internal_child_run
    │   ├── project_task_run() 批量投影
    │   ├── select_current_items_by_session() 按会话去重
    │   ├── 自动将最高优先级的 active item 展开为详细模式
    │   └── build_envelope(scope="session", selected=active_item)
    │
    └── _session_active_turn_item()  — 补充当前活跃 turn
```

### 3.3 操作执行数据流

```
RuntimeMonitorActionService.execute(payload)
    │
    ├── preflight() — 前置检查
    │   ├── collect_global_runtime_monitor() 获取当前监控状态
    │   ├── _find_signal() 定位目标信号
    │   ├── _source_revision_check() 检查 revision 新鲜度
    │   └── _action_check() 检查操作是否可用
    │
    ├── 执行具体操作（pause/stop/delete/hide/unhide/close）
    │
    ├── 成功后 invalidate_global_monitor_cache()
    │
    └── 返回最新 collect_global_runtime_monitor()
```

---

## 四、关键技术细节

### 4.1 新鲜度检测

```python
stale = (
    control_state != "paused"
    and status in RUNNING_TASK_RUN_STATUSES | {"waiting_executor"}
    and (not last_activity_at or last_activity_age_seconds > freshness_seconds)
)
if stale and graph_runtime_active:
    stale = False  # 如果子图仍在运行，不标记为 stale
```

`freshness_seconds` 默认为 **5 分钟**。

### 4.2 资源分类

| 资源类 | 条件 |
|--------|------|
| `dynamic` | `bucket == "running"` 且非 terminal |
| `static` | 其他 |

`dynamic` 资源的 `ended_at` 始终为 `None`（表示仍在运行中）。

### 4.3 监控修订号（Revision）

```python
def monitor_revision(items, now):
    identity = "|".join(f"{task_instance_id}:{status}:{bucket}:{last_activity_at}" for item in items)
    digest = sha256(identity.encode())[:12]
    return f"rtmon:{int(latest or now)}:{digest}"
```

用于前端判断监控数据是否发生变化，支持增量更新。

### 4.4 会话去重策略

`select_current_items_by_session()` 确保每个会话在全局监控中只保留一个优先级最高的项。排序依据：activity_sort_rank（running > paused > waiting > stale > failed > stopped > completed）。

### 4.5 子图运行过滤

`_is_internal_child_run()` 和 `is_top_level_task_run()` 用于过滤内部子运行，确保只有顶层任务运行出现在全局监控中。

### 4.6 全局缓存

- Key：`(requested_limit, state_index_meta_mtime_ns, state_index_meta_size)`
- TTL：默认 `1.0` 秒
- 任何成功的操作执行都会清除缓存
- 过期的缓存在新写入时自动清理

### 4.7 过期回收

`_sweep_expired_task_runs()` 每 30 秒执行一次（由 `retention_sweep_interval_seconds` 控制），受 `_retention_sweep_lock` 保护防止并发。

### 4.8 文件锁

`retention_store` 使用 `msvcrt.locking()`（Windows 专属）实现进程级文件锁，确保并发的 hide/unhide 操作安全。

---

## 五、文件索引（11 个源文件）

| 文件 | 大小 | 核心类/函数 | 职责 |
|------|------|-------------|------|
| `__init__.py` | 534 B | 导出 6 个类 | 包入口 |
| `actions.py` | 17.8 KB | `RuntimeMonitorActionService` | 操作执行（pause/stop/delete/hide） |
| `activity.py` | 10 KB | `RuntimeActivity`, `RuntimeActivityControlContext` | 活动状态模型 |
| `contract.py` | 4.9 KB | `build_envelope`, `monitor_revision`, `build_navigation_target` | 契约构建 |
| `lifecycle.py` | 2.6 KB | 状态常量 + `task_lifecycle`, `monitor_bucket`, `ended_at` | 生命周期 |
| `management.py` | 13.6 KB | `RuntimeMonitorManagementProjector`, `RuntimeMonitorManagementPolicy` | 管理策略 |
| `projector.py` | 80 KB | `RuntimeMonitorProjector`（50+ 方法） | **核心投影器** |
| `resource_resolver.py` | 6.7 KB | `MonitorResourceResolver` | 资源解析 |
| `retention_store.py` | 6.5 KB | `RuntimeMonitorRetentionStore` | 隐藏/保留存储 |
| `service.py` | 21.2 KB | `RuntimeMonitorService` | **服务入口** |
| `signals.py` | 13.1 KB | `build_runtime_monitor_envelope`, `project_monitor_signal` | 信号投影 |

---

## 六、技术细节汇总

| 维度 | 值 |
|------|-----|
| **总代码量** | ~177 KB（11 个源文件） |
| **最大文件** | `projector.py` — 80 KB |
| **核心类** | `RuntimeMonitorService`（入口）+ `RuntimeMonitorProjector`（核心） |
| **状态体系** | status → lifecycle → bucket → activity_state → signal_state，5 层映射 |
| **监控范围** | global / session / task / turn 四级 |
| **缓存策略** | 全局监控 1 秒 TTL，基于 state_index 文件元数据作为 revision key |
| **新鲜度窗口** | 5 分钟（`freshness_seconds=300`） |
| **回收周期** | 30 秒（`retention_sweep_interval_seconds=30`） |
| **隐藏保留** | 7 天（`hidden_retention_seconds=7*24*60*60`） |
| **容量限制** | active=5, attention=12, projects=8, recent=12 |
| **并发控制** | `threading.RLock`（缓存 + 回收）+ `msvcrt.locking`（文件锁） |
| **修订号** | `rtmon:{timestamp}:{sha256_hex[:12]}` |
| **事件日志读取** | 最多 240 条/任务运行 |
| **依赖** | `harness.*`, `artifact_system.*`, `task_system.*`, `project_layout` |
