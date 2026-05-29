# 后端目录分层说明

日期：2026-05-04

## 一、文档定位

本文用于说明 `backend/` 当前的正式目录边界、历史重叠目录以及后续目录治理方向。

它不是源码实现文档，而是目录层级说明。

## 二、正式分层

当前建议把 `backend/` 里的目录理解为五层：

## 2.1 Interface Layer

主要目录：

- `api`
- `bootstrap`

职责：

- HTTP / stream / app host 接入
- 外部调用入口

## 2.2 Control Plane Layer

主要目录：

- `query`
- `tasks`

职责：

- query 入口适配
- turn 归口
- task 识别、登记、绑定、工作流

## 2.3 Orchestration Layer

主要目录：

- `orchestration`

职责：

- body 装配
- runtime spec
- directive
- runloop spine

## 2.4 Supply Systems Layer

主要目录：

- `memory_system`
- `soul`
- `operations`
- `health_system`
- `sessions`

职责：

- 给编排系统提供正式输入材料
- 给主链提供会话连续体与持久化

## 2.5 Execution / Output Layer

主要目录：

- `execution`
- `output`
- `output_boundary`

职责：

- model/tool 执行
- 输出边界
- 结果收口

## 三、当前重叠目录

以下目录当前应视为实现层或历史残留，不应继续无边界扩张：

- `memory`
- `structured_memory`

说明：

- `memory` 更接近兼容层
- `structured_memory` 更接近记忆底层实现层

## 四、数据根边界

从 2026-05-04 起，`backend/` 只作为代码根使用。

所有运行生成数据、索引、checkpoint、会话态、健康记录统一进入项目根 `storage/`。

正式数据根包括：

- `storage/durable_memory`
- `storage/session_memory`
- `storage/sessions`
- `storage/runtime_state`
- `storage/health_system`
- `storage/indexes`
- `storage/document_cache`
- `storage/modality_artifacts`
- `storage/capability_system`
- `storage/tasks`
- `storage/orchestration`
- `storage/test_system`

因此：

- `backend/` 不再承载持久化运行数据
- `storage/` 是唯一正式数据根
- 旧 `backend/storage`、`backend/session-memory`、`backend/health-system`、`backend/runtime-loop` 已清退

## 五、当前目录阅读建议

如果你要理解当前主链，建议按下面顺序看目录：

1. `api`
2. `query`
3. `tasks`
4. `orchestration`
5. `memory_system`
6. `soul`
7. `operations`
8. `sessions`
9. `execution`
10. `output_boundary`

## 六、目录治理规则

后续目录重构统一遵守：

1. 每个正式系统只保留一个 public boundary
2. 兼容层不再放在正式系统根目录里长期生长
3. 数据目录和代码目录命名必须可区分
4. 新能力优先接到正式系统目录，不再接到历史重叠目录

## 七、当前冻结结论

从现在开始，后续新代码优先落到这些正式系统目录：

- `tasks`
- `orchestration`
- `memory_system`
- `soul`
- `operations`
- `health_system`
- `bootstrap`
- `sessions`
- `execution`

而以下对象默认不再作为新系统边界继续扩展：

- `memory`
- `structured_memory`
