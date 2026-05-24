# task domain / task_family / task_domain 三概念收敛清理计划

日期：2026-05-24

## 背景

当前代码里存在三个高度重叠的领域概念：

- `domain_id`：任务域管理容器 ID，例如 `domain.development`。
- `task_family`：任务族/资源分类字段，例如 `development`、`research`。
- `task_domain`：语义任务领域字段，主要来自 `TaskGoalProfile.task_domain`。

实际使用中三者经常互相推导：

```text
domain_id = domain.{task_family}
task_domain ~= task_family
```

这导致 runtime、任务图、任务管理和语义合同之间出现多个“领域真相”。用户要求清理任务族，并追踪三者是否可以收敛。

## 目标结论

本轮不保留 `task_family` 作为 runtime 概念。

目标边界：

```text
domain_id        = 管理层任务资产归属
task_goal_type   = 执行语义主键
semantic domain  = 语义合同上下文，仅服务理解和 planner
task_family      = 删除或退回存储/迁移层，不进入 runtime
```

## 实施原则

1. Runtime 不消费、不携带、不派生 `task_family`。
2. `domain_id` 可以进入任务图/协调 payload，但只作为归属元数据，不决定 runtime mode、工具权限、agent 身份或执行策略。
3. `TaskGoalProfile.task_domain` 暂时保留为语义合同字段，但不再反向制造 task family。
4. 删除无用旧测试断言，不以兼容字段维持旧结构。
5. 能直接改为 `domain_id` 的管理分组逻辑，直接改；不能安全删除的数据模型字段，先从 runtime 输出和消费链路断开。

## 执行步骤

1. 盘点 `task_family` 在 runtime、task_system、API、测试中的消费点。
2. 删除 runtime models/payload/dispatch/finalizer 中的 `task_family` 字段。
3. 删除 execution recipe / task assembly 的 `task_family` 输出与派生逻辑。
4. 任务图 runtime spec 和 coordination compiler 不再输出 `task_family`，一致性检查改用 `domain_id` 或去除。
5. 管理 API 中任务域仍以 `domain_id` 为主，`task_family` 不再作为任务域必填字段；任务域删除不再按 family 级联，而按 `domain_id` 归属级联。
6. 更新测试：删除 runtime 中 `task_family` 断言，改为验证没有 `task_family` 泄漏到 runtime assembly / dispatch payload。
7. 运行相关回归测试。

## 非目标

- 本轮不重命名全部 `TaskGoalProfile.task_domain`，但会避免它参与 task family 派生。
- 本轮不改长期记忆的核心数据结构，除非 runtime 入口仍携带 `task_family`。
- 本轮不新增兼容壳或旧字段兜底。
