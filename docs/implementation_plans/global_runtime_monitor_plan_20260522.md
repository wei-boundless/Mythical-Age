# 全局运行监控台实用化计划

## 目标

- 右侧监控不再是任务系统页面的附属视图，而是全局运行监控台。
- 多个任务同时执行时，能看到每个任务的运行状态、运行时长、最后更新时间、事件数量和是否存在审批/阻塞。
- 点击某个任务后，在监控台中部显示该任务的详细监控；详细视图复用后端权威 TaskGraph monitor，不在前端拼假拓扑。

## 信息结构

- 总览：
  - 运行中、等待处理、已完成、总数。
  - 最近刷新时间。
- 任务列表：
  - 标题或任务 ID。
  - 状态。
  - 已运行时间。
  - 最近事件数/更新时间。
  - coordination run 或 graph 标识。
- 任务详情：
  - 若有 TaskGraph monitor，显示节点、状态、产物、记忆、时序等详细监控。
  - 若还没有 TaskGraph monitor，显示普通 runtime-loop live monitor 摘要。

## 后端实现

- 新增 `/api/orchestration/runtime-loop/live-monitor`。
- 数据来源只读 `RuntimeStateIndex` 和现有 trace reader。
- 返回轻量摘要，不把所有事件和正文塞进总览接口。

## 前端实现

- Store 增加 `globalRuntimeMonitor`、选中任务、刷新/轮询状态。
- 右侧 `TaskMonitorDock` 改为全局监控台：
  - 默认展示任务列表。
  - 点击任务后展示详情。
  - 保留审批操作和现有 TaskGraphRunMonitorPanel。
- 与任务系统解耦：不依赖当前 task-system 页面，也不要求先绑定任务。

## 验收标准

- 没有任务时显示空状态。
- 有多个 task_run 时显示多行任务摘要。
- 选中任务后能拉取该任务的详细 monitor。
- 构建通过，右侧监控在桌面宽度下不溢出。
