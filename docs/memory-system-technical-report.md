# LangChain Agent 记忆系统 — 详细技术报告

> 编写日期：2026-06-15  
> 审查范围：`backend/memory_system/` 全部 33 个源文件  
> 报告作者：洪荒智能

---

## 一、整体架构概览

本项目的记忆系统是一个**多层级、全生命周期、可审计**的记忆基础设施，位于 `backend/memory_system/`。它定义了四个核心记忆层级、一个正式记忆子系统、一组运行时供应编排器以及一个治理与维护体系。

### 架构总图

```
┌─────────────────────────────────────────────────────────────┐
│                    MemoryFacade (facade.py)                  │
│   ┌──────────────────────────────────────────────────────┐  │
│   │                 MemoryBundleService                  │  │
│   │              (bundle_service.py)                     │  │
│   │  统筹各层读取，构建 MemoryRuntimeView                 │  │
│   └──────────────────────────────────────────────────────┘  │
│                                                             │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐ │
│   │Conversation│   State   │  Working  │  Durable/LongTerm│ │
│   │  Memory   │  Memory   │  Memory   │     Memory      │ │
│   │  (会话)   │  (状态)   │  (工作)   │   (持久/长期)   │ │
│   └──────────┘ └──────────┘ └──────────┘ └───────────────┘ │
│                                                             │
│   ┌──────────────────────────────────────────────────────┐  │
│   │            Formal Memory (正式记忆)                   │  │
│   │        SQLite 结构化事务记忆（图形节点间）              │  │
│   └──────────────────────────────────────────────────────┘  │
│                                                             │
│   ┌──────────────────────────────────────────────────────┐  │
│   │   MemoryGovernance + DurableMemoryConsolidator       │  │
│   │   治理：审计日志、命名空间脏标记、定期 tick 合并      │  │
│   └──────────────────────────────────────────────────────┘  │
│                                                             │
│   ┌──────────────────────────────────────────────────────┐  │
│   │    MemoryMaintenanceAgent (agent:1)                  │  │
│   │    后台维护：会话摘要、SessionEmphasis、持久记忆写入   │  │
│   └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、记忆层级详解

### 2.1 会话记忆（Conversation Memory）

**文件：** `conversation_memory.py`

| 属性 | 说明 |
|------|------|
| **数据源** | 会话摘要（session summary）和 compaction view |
| **存储形式** | 文件系统上的 Markdown 摘要 |
| **读取方式** | `ConversationMemoryStoreAdapter` → `SessionMemoryManager` |
| **核心契约** | `ConversationMemorySnapshot` |

**工作原理：**

- `ConversationMemoryStoreAdapter` 包装会话根目录下的 session summary 文件
- 通过 `SessionMemoryManager` 读取 `summary_path`、`agent_view_path`、`compaction_view_path`
- 解析出预定义的几个 section：
  - `# Key User Requests` — 关键用户请求
  - `# Decisions and Learnings` — 决策和学习
  - `# Key Results` — 关键结果
- 提取 `hot_truth_window`（最多 6 条关键结果/决策）和 `recent_dialogue_refs`（最多 8 条关键请求/工作日志）
- 产出 `MemoryContextCandidate`，固定 `relevance=0.72`、`confidence=0.66`

**候选池特征：**
```python
MemoryContextCandidate(
    memory_layer="conversation",
    budget_class="preferred",
    requires_verification_before_use=False,
    staleness="session_scoped"
)
```

---

### 2.2 状态记忆（State Memory）

**文件：** `state_memory.py`

| 属性 | 说明 |
|------|------|
| **数据源** | 进程状态存储（process-state storage） |
| **存储形式** | `SessionMemoryManager` 管理的 session 状态文件 |
| **读取方式** | `StateMemoryStoreAdapter` |
| **核心契约** | `StateMemorySnapshot` |

**关键字段：**

```python
@dataclass
class StateMemorySnapshot:
    session_id: str
    active_goal: str                  # 当前活跃目标
    flow_state: dict                  # 流程状态
    task_state: dict                  # 任务状态
    context_slots: dict               # 上下文槽位（committed_pdf, active_dataset 等）
    active_handles: dict              # 活跃 handle（result_handle, object_handle 等）
    bundle_result_refs: tuple         # 子任务结果引用
    task_summary_refs: tuple          # 任务摘要引用
    key_results: tuple                # 关键结果列表
    next_step: tuple                  # 下一步方向
```

**恢复候选（Restore Candidates）：** 通过 `restore_candidates()` 从快照中提取，支持以下类型：
- `context_slot`（绑定文件/数据集/实体/规则）
- `active_binding`（当前活跃绑定）
- `result_handle`（已完成分析结果）
- `bundle_ref`（子任务结果引用）
- `flow_state`（流程状态）
- `task_state`（任务状态）

每种恢复候选有不同的 confidence 评分（0.55~0.82），且**必须经过 OrchestrationSystem 验证**后才能成为当前事实。

**上下文候选预览生成：** 自动检测当前是否有 PDF、数据集、分析结果 handle 或子任务结果，生成中文自然语言预览段落。

---

### 2.3 工作记忆（Working Memory）

**文件：** `working_memory_models.py`, `working_memory_service.py`, `working_memory_store.py`

| 属性 | 说明 |
|------|------|
| **数据源** | 图表执行期间的节点间数据流转 |
| **存储形式** | JSON 文件（`WorkingMemoryStore`） |
| **作用域** | task_scope / graph_scope / node_scope / edge_scope / artifact_scope |
| **核心契约** | `WorkingMemoryItem` |

**WorkingMemoryItem 关键字段：**

- `work_memory_id` — 唯一标识
- `task_run_id` / `graph_id` / `owner_node_id` / `node_run_id` — 归属链
- `scope` — 可见性作用域（node_scope → graph_scope 递进）
- `kind` — 类型（intermediate_result, artifact, instruction 等）
- `memory_semantics` — 语义类型（`working_fact`, `draft_artifact`, `reflection`, `instruction`, `temporal_event`, `conflict`, `decision`, `handoff_note`, `evaluation`）
- `visibility` — 可见性（private_to_agent, private_to_node, shared_in_graph, handoff_only 等）
- `status` — 生命周期状态（draft, proposed, accepted, conflicted, superseded, archived, promoted, discarded）
- `promotion_state` — 提升状态（not_applicable, candidate, needs_review, approved, rejected, promoted_to_artifact_store 等）
- `authority` — 权限级（candidate_only, runloop_adopted, coordinator_adopted, human_gate_adopted）

**语义类型枚举说明：**
| Semantics | 用途 |
|-----------|------|
| `working_fact` | 当前工作事实 |
| `draft_artifact` | 草稿产物 |
| `reflection` | 反思/分析 |
| `instruction` | 指令 |
| `temporal_event` | 时序事件 |
| `conflict` | 冲突记录 |
| `decision` | 决策记录 |
| `handoff_note` | 交接备注 |
| `evaluation` | 评估结果 |

**读取策略：** `WorkingMemoryService.select_for_node()` 基于 reader 角色、read_policy、dynamic_policy 和 token_budget 进行细粒度授权选择。

**候选池特征：**
- `accepted` 状态的项固定 `budget_class="required"`，无需验证
- 其他状态为 `"preferred"`，需要验证
- `relevance` 根据 status 映射：`accepted=0.82`, `proposed=0.72`, `draft=0.55`

---

### 2.4 持久记忆（Durable Memory / Long-Term Memory）

**文件：** `durable.py`, `governance_service.py`, `manifest_scan.py`

| 属性 | 说明 |
|------|------|
| **数据源** | 用户偏好、反馈、项目约定、参考资料 |
| **存储形式** | Markdown 文件 + frontmatter（YAML 头部元数据） |
| **索引** | `MEMORY.md` 索引 + 内存中的 MemoryManager 索引 |
| **命名空间** | `global_common` 和 `env:<environment_id>` |
| **核心契约** | `MemoryNote`, `MemoryHeader` |

**MemoryNote 结构：**
- 文件路径：`storage/memory/durable/{namespace}/notes/{slug}.md`
- Frontmatter 包含：`id`, `title`, `type`, `memory_class`, `status`, `confidence`, `canonical_statement`, `summary`, `retrieval_hints`, `eligible_for_injection`, `tags`, `source_kind` 等
- Body 包含：Canonical Memory、Retrieval Hints、Why Stored、Source Evidence

**允许的 memory_type：** `user`, `feedback`, `project`, `reference`  
**允许的 memory_class：** `work`, `preference`  
**拒绝的来源：** `assistant_inferred_fact`, `temporary_task_state`  
**拒绝的证据类型：** `assistant_summary`, `runtime_state`, `unknown`

**Recall 选择器（`DurableMemoryRecallSelector`）：**
- 扫描 manifest headers → 调用 AI 模型选择相关笔记
- 使用 `DURABLE_MEMORY_RECALL_SELECTOR_PROMPT` 作为 selector prompt
- 返回 `MemoryRecallSelection`，包含是否召回、选中的 note_ids、是否需要验证
- 选中笔记上限 5 条

**持久记忆候选池特征：**
```python
MemoryContextCandidate(
    memory_layer="long_term",
    budget_class="optional",
    requires_verification_before_use=True,
    staleness="durable_memory_may_drift"
)
```

---

### 2.5 正式记忆（Formal Memory）

**文件：** `formal_memory_models.py`, `formal_memory_service.py`, `formal_memory_store.py`, `formal_memory_content.py`

| 属性 | 说明 |
|------|------|
| **数据源** | 图形工作流节点间的输出 |
| **存储形式** | SQLite 数据库（`formal_memory.sqlite`） |
| **作用域** | run_scoped / project_scoped / durable |
| **核心契约** | 5 个 dataclass 实体 |

**五层实体模型：**

```
FormalMemoryRepository (仓库)
    └── FormalMemoryCollection (集合)
            └── FormalMemoryRecord (记录)
                    └── FormalMemoryRecordVersion (版本)
FormalMemoryTransaction (事务)
FormalMemoryReadLog (读取日志)
```

**作用域解析（`scope_kind` 三选一）：**

| scope_kind | 作用域范围 | effective_repository_id 格式 |
|-----------|-----------|-----------------------------|
| `run_scoped` | 单次运行 | `run:{scope_id}:{logical_repository_id}` |
| `project_scoped` | 项目级别 | `project:{scope_id}:{logical_repository_id}` |
| `durable` | 全局持久 | 直接使用 `logical_repository_id` |

**关键策略：**
- `key_strategy` — 记录键策略，默认 `stable_key`
- `default_version_selector` — 版本选择策略，默认 `latest_committed_before_clock`
- `content_requirement` — 内容要求，支持 `canonical_text_required` 等选项
- `snapshot_budget` — 快照预算配置

**数据库 Schema 表：** `formal_repositories`, `formal_collections`, `formal_records`, `formal_record_versions`, `formal_transactions`, `formal_read_logs`

**版本管理：** 每条记录可拥有多个版本，状态为 `candidate` → `committed`，支持 `supersedes_version_id` 链式替换。

---

## 三、存储布局（Storage Layout）

**文件：** `storage_layout.py`

```
memory/
├── durable/                      # 持久记忆
│   ├── global_common/            # 全局命名空间
│   │   ├── notes/                # *.md 笔记文件
│   │   ├── index/                # MEMORY.md 索引
│   │   └── meta/                 # SCHEMA.md
│   └── environments/             # 环境命名空间
│       └── {env_id}/
│           ├── notes/
│           ├── index/
│           └── meta/
├── session/                      # 会话记忆
├── working/                      # 工作记忆
├── formal/                       # 正式记忆（SQLite 文件存储于此）
└── runtime/                      # 运行时状态
    ├── maintenance/              # 维护协调状态
    └── durable_governance/       # 治理运行时状态 + 报告
```

---

## 四、记忆编排与运行时供应

**文件：** `runtime_supply.py`, `runtime_view.py`, `bundle_service.py`

### 4.1 编排管线

```
MemoryRequestProfile
    → MemoryOrchestrator.build_read_plan()
        → MemoryReadPlan (含 requested_layers, 作用域, 约束)
    → MemorySupplier.fetch_candidates()
        → MemoryCandidatePool (4 层候选 + restore 候选)
    → MemoryBundleService.build_memory_runtime_view()
        → MemoryRuntimeView (只读快照)
    → MemoryBundleService.build_memory_context_package_result()
        → ContextPackageResult (含预算裁剪后的上下文)
```

### 4.2 MemoryRuntimeView

```python
@dataclass
class MemoryRuntimeView:
    view_id: str
    session_id: str
    conversation_snapshot: ConversationMemorySnapshot | None
    state_snapshot: StateMemorySnapshot | None
    context_candidates: tuple[MemoryContextCandidate, ...]  # 所有层级候选
    restore_candidates: tuple[StateMemoryRestoreCandidate, ...]
    read_only: bool = True  # 强制只读
    memory_write_allowed: bool = False  # 强制不可写
```

运行时视图是**严格只读**的，约束包括：
- `can_override_current_turn` 必须为 `False`
- `can_promote_to_current_fact` 必须为 `False`
- 所有候选 `authority` 必须为 `candidate_only`

### 4.3 上下文预算策略

**文件：** `context_budget_policy.py`

提供 `build_model_aware_context_budget_policy()`，基于模型类型（如 `deepseek_1m`）预设可用 token 预算，并据此对候选进行裁剪（按 `budget_class` 优先级：`required > preferred > optional > debug_only`）。

---

## 五、治理机制（Governance）

**文件：** `governance_service.py`

### 5.1 MemoryGovernance

- 记录所有 commit 操作的审计日志到 `governance_log.jsonl`
- 每条记录包含：`commit_layer`, `action`, `target_refs`, `created_ref`, `reason`, `actor`, `allowed`, `source_candidate_refs`

### 5.2 DurableMemoryGovernanceService

**命名空间管理：**
- `global_common` — 全局命名空间
- `env:{environment_id}` — 环境级命名空间
- 使用 `mark_namespaces_dirty()` 标记脏命名空间

**Governance Tick 流程：**
1. 加载运行时状态（`state.json`）
2. 确定目标命名空间（指定 / 脏 / 全部）
3. 对每个命名空间检查是否可以运行 tick（最小间隔策略，默认 6 小时）
4. 运行 `DurableMemoryConsolidator.run()` 进行合并/整理
5. 生成治理报告（JSON 格式，存储至 `reports/{namespace}/`）
6. 更新运行时状态（`dirty=False`, `last_governed_at`, `run_count` 等）

**发送方配置：**
- `default_min_interval_seconds = 6 * 60 * 60`（6 小时）
- 支持 `force=True` 强制立即执行

### 5.3 DurableMemoryConsolidator

**文件：** `storage/consolidation.py`

负责持久笔记的合并、去重和整理，生成治理报告。

---

## 六、记忆维护系统（Maintenance）

**文件：** `maintenance.py`（1608 行，整个记忆系统最大的文件）

### 6.1 维护 Agent（agent:1）

- 固定 agent_id = `agent:1`
- profile_id = `memory_system_agent`
- 不允许嵌套子 agent（`allow_nested_subagents=False`）
- 限定操作范围：
  - **允许：** `op.model_response`, `op.memory_read`, `op.memory_write_candidate`
  - **禁止：** `op.write_file`, `op.edit_file`, `op.shell`, `op.python_repl`, `op.agent_bounded`, `op.web_search`
- 必需作用域：`conversation_readonly`, `state_readonly`, `long_term_candidate`, `session_memory_write_candidate`, `durable_memory_write_candidate`

### 6.2 SessionMemoryMaintenanceDraft

标准化的会话记忆草案，包含 16 个可选字段：
`session_title`, `active_goal`, `flow_state`, `context_slots`, `current_task_state`, `warm_context`, `key_user_requests`, `files_and_functions`, `conventions_and_constraints`, `errors_and_corrections`, `decisions_and_learnings`, `key_results`, `historical_results`, `risk_watch`, `next_step`, `worklog`

支持 `is_empty()` 检测和 `render_markdown()` 渲染。

### 6.3 DurableMemoryWriteAction

写持久记忆的行动模型，包含：
- `action`（none / create / update / merge）
- `memory_type`（user / feedback / project / reference）
- `memory_class`（work / preference）
- `title`, `canonical_statement`, `summary`, `retrieval_hints`
- `source_strength`（low / medium / high）
- `memory_origin`（8 种来源枚举）
- `evidence_source_kind`（5 种证据类型枚举）
- `preference_scope`（turn_only → global_common 递进）
- `proposed_target_layer`（turn / session / environment_durable / global_common）

### 6.4 SessionEmphasis

**文件：** `session_emphasis.py`

| 组件 | 说明 |
|------|------|
| `SessionPinnedUserSteer` | 固定级用户指引（emphasis_id, content, scope, priority, status） |
| `SessionEmphasisStore` | 增删查改 emphasis 条目，支持文件持久化 |
| `SessionEmphasisCaptureGate.evaluate()` | 从最新用户消息中检测 emphasis 触发信号（如"以后不要"、"偏好"、"纠正"、"记住"等关键词） |

**Emphasis Scope 枚举：** `turn_only`, `session_task`, `environment`, `global_common`  
**Emphasis Priority：** `low`, `medium`, `high`  
**Emphasis Status：** `active`, `superseded`, `resolved`, `archived`

---

## 七、环境上下文与作用域解析

**文件：** `environment_context.py`, `layout.py`

### 7.1 环境上下文解析

`resolve_memory_environment_context()` 从 10 个候选源按优先级解析环境上下文：

1. `explicit`（显式传入）
2. `main_context.task_environment`
3. `main_context`
4. `runtime_assembly.task_environment`
5. `environment_binding`
6. `active_work_context`
7. `recent_work_outcome`
8. 会话记录中的 `turn_environment_snapshot`
9. 会话记录的 `active_task_environment`
10. 会话记录的 `scope`/`task_binding`

每个字段只被首次非空值填充（`_fill` 模式）。

### 7.2 Durable Memory 命名空间计算

```python
def durable_memory_namespace_id_for_task_environment(task_environment_id):
    return f"env:{safe_memory_namespace_id(task_environment_id)}"
```

`safe_memory_namespace_id()` 对输入进行规范化：小写化、替换特殊字符、长度限制 120 字符。

---

## 八、关键数据流与事务模型

### 8.1 读取流程

```
用户请求
    → MemoryBundleService.build_memory_context_package()
        → resolve_memory_environment_context()
        → MemoryOrchestrator.build_read_plan()
            → 解析 requested_memory_layers
            → 计算命名空间（env + global_common）
        → MemorySupplier.fetch_candidates()
            → 会话快照
            → 状态快照 + 恢复候选
            → 工作记忆候选
            → 持久记忆召回（AI 选择器筛选 manifest headers）
        → MemoryRuntimeView（只读）
        → ContextPackageResult（预算裁剪后）
```

### 8.2 写入流程

```
会话写入 → session memory summary/compaction
状态写入 → process_state 存储
工作记忆写入 → WorkingMemoryStore（JSON 文件）
持久记忆写入 → MemoryManager.save_note()（Markdown + frontmatter）
    → 触发 mark_namespaces_dirty()
    → Governance tick（定期合并/整理）
正式记忆写入 → FormalMemoryStore（SQLite 事务）
    → 版本管理（candidate → committed）
```

### 8.3 事务模型（Formal Memory）

FormalMemoryTransaction 包含：
- `operation` — 操作类型
- `candidate_version_id` — 候选版本
- `committed_version_id` — 提交版本
- `receipt` — 回执
- `status` — 状态（completed）
- `idempotency_key` — 幂等键

读取日志 `FormalMemoryReadLog` 记录每次读取操作的 selector、selected_version_ids、clock 信息。

---

## 九、各文件关键类/函数索引

| 文件 | 行数 | 关键类/函数 |
|------|------|-------------|
| `contracts.py` | 192 | `MemoryContextCandidate`, `StateMemorySnapshot`, `ConversationMemorySnapshot`, `MemoryCommitRecord` |
| `conversation_memory.py` | 143 | `ConversationMemoryStoreAdapter` |
| `state_memory.py` | 375 | `StateMemoryStoreAdapter` |
| `working_memory_models.py` | 220+ | `WorkingMemoryItem`, `WorkingMemoryReadLog`, `WorkingMemoryTemporalEdge`, `WorkingMemoryHandoffTransaction` |
| `working_memory_service.py` | 1000+ | `WorkingMemoryService` |
| `working_memory_store.py` | 1500+ | `WorkingMemoryStore`（JSON 文件存储管理） |
| `durable.py` | 800+ | `DurableMemoryRecallSelector`, `DurableMemoryLayer` |
| `manifest_scan.py` | 156 | `MemoryHeader`, `scan_memory_headers()`, `load_memory_header()` |
| `governance_service.py` | 697 | `MemoryGovernance`, `DurableMemoryGovernanceService` |
| `maintenance.py` | 1608 | `MemoryMaintenanceAgent`, `MemoryMaintenanceCoordinator`, `SessionMemoryMaintenanceDraft`, `DurableMemoryWriteAction`, `MemoryMaintenanceProposal` |
| `session_emphasis.py` | 292 | `SessionEmphasisStore`, `SessionEmphasisCaptureGate` |
| `bundle_service.py` | 603 | `MemoryBundleService` |
| `runtime_supply.py` | 1000+ | `MemoryOrchestrator`, `MemorySupplier`, `build_memory_runtime_view()` |
| `runtime_view.py` | 88 | `MemoryRuntimeView`, `normalize_memory_layer()` |
| `continuity.py` | 405 | `MemoryMessageAdapter`, `SessionMemoryLayer`, `ForegroundContinuityStateStore` |
| `facade.py` | 600+ | `MemoryFacade`（统一入口） |
| `environment_context.py` | 162 | `resolve_memory_environment_context()` |
| `formal_memory_models.py` | 165 | `FormalMemoryRepository`, `FormalMemoryCollection`, `FormalMemoryRecord`, `FormalMemoryRecordVersion`, `FormalMemoryTransaction`, `FormalMemoryReadLog` |
| `formal_memory_service.py` | 800+ | `FormalMemoryService` |
| `formal_memory_store.py` | 2000+ | `FormalMemoryStore`（SQLite 存储） |
| `formal_memory_content.py` | 500+ | `materialize_formal_memory_candidate()`, `formal_memory_content_requirement_from_payloads()` |
| `storage_layout.py` | 100 | `MemoryStorageLayout` |
| `layout.py` | 80+ | `DurableMemoryLayout`, `durable_memory_layout_from_backend_dir()` |
| `runtime_services.py` | 40+ | `MemoryRuntimeServices`（组装各服务实例） |
| `paths.py` | 25+ | `normalize_session_id()`, `safe_session_dir()` |

---

## 十、技术细节汇总

### 10.1 数据库 Schema（Formal Memory - SQLite）

- `formal_repositories` — 记忆仓库表（repository_id 为主键）
- `formal_collections` — 集合表（repository_id + collection_id 复合主键）
- `formal_records` — 记录表（含 current_committed_version, head_version_id）
- `formal_record_versions` — 版本表（含 payload, canonical_text, summary, artifact_refs, source_clock 等）
- `formal_transactions` — 事务日志
- `formal_read_logs` — 读取审计日志

### 10.2 版本控制策略

- `key_strategy`：`stable_key`（默认，基于 record_key 稳定定位）
- `default_version_selector`：`latest_committed_before_clock`（默认，按时钟选择最新已提交版本）
- 版本状态流转：`candidate` → `committed`
- 支持 `supersedes_version_id` 链式替换

### 10.3 Scope 解析策略

```
scope_kind = run_scoped / project_scoped / durable
if run_scoped:
    effective_repository_id = "run:{scope_id}:{logical_id}"
    scope_id = task_run_id or memory_namespace_id
elif project_scoped:
    effective_repository_id = "project:{scope_id}:{logical_id}"
    scope_id = 项目级 scope_id
else:  # durable
    effective_repository_id = logical_id
    scope_id = "global"
```

### 10.4 内容物化策略（Formal Memory Content）

当 Formal Memory 需要写入时，可选物化策略：
- `materialization_policy.enabled` 控制是否启用
- `canonical_text_mode`：`full_text`(默认) / `none` / `refs_only`
- 支持 artifact 引用读取、过滤（按扩展名、路径关键词）
- 自动生成 summary（如 `first_heading` 模式）

### 10.5 候选置信度体系

| 层级 | 默认 relevance | 默认 confidence | budget_class |
|------|---------------|----------------|-------------|
| Conversation | 0.72 | 0.66 | preferred |
| State | 0.80 | 0.68 | preferred |
| Working (accepted) | 0.82 | 根据状态 | required |
| Working (其他) | 0.55~0.72 | 根据状态 | preferred |
| Long-Term | 0.70 | 0.35~0.82 | optional |

### 10.6 审计与治理

- `MemoryGovernance`：JSONL 格式审计日志
- `DurableMemoryGovernanceService`：状态机管理脏命名空间、最小间隔策略（6h）、tick 执行与报告持久化
- `MemoryCommitRecord`：每个 commit 都记录 action、layer、target_refs、actor、allowed 状态

---

## 十一、总结

LangChain Agent 项目的记忆系统是一个**全面且成熟的多层记忆基础设施**，特点包括：

1. **四层记忆分层**：会话（Conversation）、状态（State）、工作（Working）、持久（Long-Term/Durable），覆盖从短期到长期的完整记忆谱系
2. **正式记忆子系统**：基于 SQLite 的结构化事务记忆，支持版本管理、作用域隔离和读取审计
3. **候选+验证模式**：所有记忆读取都是 `candidate_only`，需要上层验证后才能成为当前事实，防止记忆污染
4. **细粒度权限控制**：工作记忆支持基于 role、visibility、read_policy 的细粒度授权
5. **治理与维护**：自动化的脏标记→tick→合并→报告流水线，最小间隔策略防止过度治理
6. **AI 驱动的召回**：持久记忆使用 AI selector 从 manifest headers 中选择相关笔记
7. **统一入口**：`MemoryFacade` 封装所有子服务，提供一致的读写接口
8. **严格只读运行时视图**：确保记忆读取不会意外改变系统状态
