# Memory System — 记忆系统

本项目采用**多层记忆架构**，覆盖从会话级上下文到持久化长期记忆的完整链路。系统位于 `backend/memory_system/`，包含 30+ 模块，设计严谨、边界清晰。

---

## 目录结构

```
backend/memory_system/
├── facade.py                    # 系统门面，构造并串联所有记忆层
├── contracts.py                 # 数据契约与安全边界
├── bundle_service.py            # 记忆供应链编排
├── continuity.py                # 前台连续性状态 + 消息过滤适配
├── conversation_memory.py       # 会话记忆适配器
├── state_memory.py              # 状态记忆适配器
├── session_emphasis.py          # 用户强调偏好管理
├── durable.py                   # 持久记忆层 + AI 召回选择器
├── governance_service.py        # 长期记忆治理服务
├── maintenance.py               # 记忆维护 Agent 与协调器
├── working_memory_service.py    # 工作记忆服务
├── working_memory_store.py      # 工作记忆存储
├── working_memory_models.py     # 工作记忆数据模型
├── working_memory_finalizer.py  # 工作记忆终结器
├── formal_memory_service.py     # 正式记忆服务
├── formal_memory_store.py       # 正式记忆存储
├── formal_memory_content.py     # 正式记忆内容模型
├── formal_memory_models.py      # 正式记忆数据模型
├── runtime_services.py          # 运行时记忆服务构造
├── runtime_supply.py            # 记忆供应与编排
├── runtime_view.py              # 运行时视图
├── runtime_scope.py             # 运行时作用域
├── runtime_context_provider.py  # 运行时上下文提供
├── runtime_fact_bridge.py       # 运行时事实桥接
├── storage_layout.py            # 存储目录布局定义
├── layout.py                    # 持久记忆布局与作用域
├── environment_context.py       # 环境上下文
├── manifest_scan.py             # 记忆清单扫描
├── paths.py                     # 路径安全工具
├── static_loader.py             # 静态加载器
└── storage/                     # 存储层实现
```

---

## 记忆分层架构

系统由五层记忆构成，从短时到长期逐级递进：

| 层级 | 核心模块 | 职责 |
|------|----------|------|
| **会话记忆** | `conversation_memory.py` | 从 SessionMemoryManager 提取对话摘要、关键请求、决策与结果 |
| **状态记忆** | `state_memory.py` | 保存任务/流程的上下文快照（active goal, flow_state, result_refs） |
| **工作记忆** | `working_memory_service.py` | 图节点级别的工作项，带策略管控的生命周期 |
| **正式记忆** | `formal_memory_service.py` | 已审核/已接受的正式任务记忆，带版本管理 |
| **持久记忆** | `durable.py` | 基于文件的长期笔记存储，AI 驱动的召回选择器 |

---

## 核心组件

### MemoryFacade（`facade.py`）

系统统一入口，构造并串联所有子组件：

- `SessionMemoryLayer` — 会话层
- `ForegroundContinuityStateStore` — 前台连续性持久化
- `SessionEmphasisStore` — 用户强调/偏好管理
- `DurableMemoryLayer` — 持久层
- `MemoryMaintenanceAgent` / `MemoryMaintenanceCoordinator` — 后台维护
- `MemoryBundleService` — 跨层上下文打包
- `DurableMemoryGovernanceService` — 治理

### MemoryBundleService（`bundle_service.py`）

记忆供应链编排，从会话、状态、工作、持久各层收集候选，打包为运行时上下文。

### DurableMemoryGovernanceService（`governance_service.py`）

长期记忆治理的核心：

- 命名空间脏标记 + 治理 tick（默认冷却 6 小时）
- 笔记 CRUD、合并、移动至回收站
- JSONL 审计日志

### DurableMemoryLayer（`durable.py`）

文件级持久化存储 + `DurableMemoryRecallSelector` 提供 AI 模型驱动的相关记忆择取。

### ForegroundContinuityStateStore（`continuity.py`）

前台状态持久化，维护 active_goal、active_bindings、result_refs、next_step。

### SessionEmphasisStore（`session_emphasis.py`）

用户强调偏好管理，支持优先级、状态生命周期和自动信号捕获。

---

## 存储布局

所有记忆数据存储在如下目录结构中：

```
memory/
├── durable/
│   ├── global_common/       # 全局持久记忆
│   └── environments/        # 环境级持久记忆
├── session/                 # 会话记忆
├── working/                 # 工作记忆
├── formal/                  # 正式记忆
└── runtime/
    ├── maintenance/         # 维护运行时
    └── durable_governance/  # 治理状态与报告
```

---

## 安全设计

- **Candidate-only 契约**：记忆数据以 `MemoryContextCandidate` 包装，`__post_init__` 强制校验 authority，不能覆盖当前轮次事实
- **Authority 溯源**：每个数据对象携带 `authority` 字段
- **内容过滤**：`MemoryMessageAdapter` 过滤控制平面内容、技能文档，避免污染记忆
- **消息去重**：`_dedupe()`、`_take_nonempty()` 保证唯一性
- **路径安全**：`_safe_note_path()` 防目录遍历

---

## 模块规模概览

| 模块 | 行数 | 说明 |
|------|------|------|
| `maintenance.py` | ~85,642 | 记忆维护 Agent + 协调器，体量最大，建议按职责拆分 |
| `formal_memory_store.py` | ~59,095 | 正式记忆存储实现 |
| `formal_memory_service.py` | ~30,902 | 正式记忆服务 |
| `governance_service.py` | ~29,951 | 治理服务 |
| `bundle_service.py` | ~23,601 | 记忆打包编排 |
| `formal_memory_content.py` | ~21,222 | 正式记忆内容模型 |
| `durable.py` | ~19,996 | 持久记忆层 |

---

## 使用说明

### 初始化

```python
from memory_system.facade import MemoryFacade

facade = MemoryFacade(base_dir=backend_path)
```

### 构建记忆上下文包

```python
package = facade.build_memory_context_package(
    session_id=session_id,
    pending_user_message=user_message,
    note_limit=5,
)
```

### 持久记忆治理

```python
# 标记命名空间脏
facade.mark_durable_memory_namespaces_dirty(saved_namespaces)

# 运行治理 tick
facade.run_durable_memory_governance_tick(force=False)
```

### 记忆维护

```python
facade.enqueue_memory_maintenance_after_commit(
    session_id=session_id,
    messages=messages,
    turn_id=turn_id,
)
```

---

## 调用链路

```
用户请求 → MemoryFacade
              ├── SessionMemoryLayer（会话）
              ├── ConversationMemoryStoreAdapter（对话摘要）
              ├── StateMemoryStoreAdapter（状态快照）
              ├── WorkingMemoryService（工作项）
              ├── DurableMemoryLayer（持久回忆）
              │     └── DurableMemoryRecallSelector（AI 选择）
              └── MemoryBundleService（打包输出）
                       → MemoryContextCandidate 列表
```

持久记忆写入和治理由 `DurableMemoryGovernanceService` 和 `MemoryMaintenanceCoordinator` 在后台异步执行。

---

## 注意

- `maintenance.py`（85KB）和 formal_memory 系列（合计约 116KB）体量偏大，后续可考虑按职责拆分
- 持久记忆召回依赖 AI 模型（`message_invoker`），无模型时降级返回空，请确保运行时注入模型调用器
