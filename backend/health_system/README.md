# 健康系统

日期：2026-05-26

## 定位

`backend/health_system` 是 Agent 运行治理系统。

它负责管理：

- 任务风险
- 系统风险
- Token 消耗
- 运行效率

健康系统消费任务记录、运行监控和 token 统计，输出任务健康档案、风险事件、系统风险、成本画像、效率指标和处理建议。

## 权责边界

```text
任务记录
  -> 运行监控
      -> 健康治理
```

- 任务记录保存事实账本，不决定风险等级。
- 运行监控观察实时状态，不沉淀长期治理判断。
- 健康系统负责治理分析，不运行测试和实验。

## 当前目录

- `governance.py`
  聚合任务记录、运行监控和 token 数据，生成健康治理视图。
- `registry.py`
  保留健康 issue、report、command、receipt 和健康分析会话。
- `command_service.py`
  处理健康管理命令；不再启动测试系统。
- `store.py`
  存储健康问题、报告、命令、回执、健康 agent 运行和会话。

## 已移除职责

健康系统不再负责：

- 测试系统
- 实验运行
- 长场景测试
- regression sample 管理
- verification gate
- harness 执行

这些能力如需恢复，应作为独立验证系统重新设计，不能挂回健康系统主职责下。

## 对外入口

当前健康治理 API：

- `/api/health-system/overview`
- `/api/health-system/tasks`
- `/api/health-system/tasks/{task_run_id}`
- `/api/health-system/risks`
- `/api/health-system/system-risks`
- `/api/health-system/token-usage`
- `/api/health-system/efficiency`

兼容保留的健康管理 API：

- `/api/health-system/issues`
- `/api/health-system/reports`
- `/api/health-system/commands`
- `/api/health-system/conversation-sessions`
- `/api/health-system/agent-runs`
