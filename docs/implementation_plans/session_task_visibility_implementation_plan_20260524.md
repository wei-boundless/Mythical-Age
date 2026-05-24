# 会话任务显式可观察实施方案

日期：2026-05-24

状态：已实施

## 目标

把主会话中的任务运行展示成清晰的状态流程，而不是散落的阶段文案、工具折叠块和监控摘要。此方案只优化前端可见性投影，不改变任务系统权威模型。

## 范围

本次只处理主会话消息内的展示：

- 任务订单绑定。
- 运行阶段。
- 工具调用与返回。
- 产物和验证提示。
- 错误、等待、完成状态。

不处理：

- 不删除 `task_selection` 迁移期投影。
- 不改变 `TaskOrder / TaskOrderRun / ExecutionChannel` 的后端结构。
- 不新增独立任务入口。

## 当前问题

- `runtimeProgress` 已经存在，但展示像日志列表，缺少状态流层级。
- `ThoughtChain` 与运行进度分离，用户需要在两个区域拼接“现在在做什么”和“用了什么工具”。
- 工具调用缺少状态感，不能一眼区分请求中、已返回、失败。
- 任务订单信息只显示为普通进度项，没有成为本轮任务上下文的锚点。

## 设计原则

- 会话消息里的第一对象是本轮工作流，不是裸日志。
- 任务订单是锚点；没有订单时展示为会话运行轨迹。
- 工具调用是工作流的一部分，与阶段流相邻展示。
- 只展示用户可理解的状态，不泄漏长机器 ID；必要 ID 只作为短标签。
- 保持工作台式密度：细线、低饱和底色、紧凑信息层级。

## 实施步骤

1. 扩展 `RuntimeProgressEntry`，增加 `kind`、`statusText`、`meta`、`toolName`、`startedAt`、`completedAt` 等展示字段。
2. `runtimeVisibilityProjection` 把 `task_order_projection`、`runtime_loop_event`、`tool_start`、`tool_end` 投影成明确的状态条目。
3. 用新的 `RuntimeProgressList` 作为会话任务状态面板：
   - 顶部概要。
   - 中间状态流程。
   - 底部工具调用与产物。
4. 保留 `ThoughtChain` 的详细输入输出，但弱化为“查看详细 I/O”，避免和状态流抢主层级。
5. 增加前端回归测试，保证任务订单、专业任务、工具事件都会生成可见进度。
6. 跑 `tsc`、相关 vitest、固定端口和 Edge 烟测。

## 验收

- 任务订单绑定能在消息内显示为明确起点。
- 工具调用开始和返回能在同一流程中显示。
- 完成、等待、错误状态颜色和图标明确。
- 普通聊天不会伪装成任务订单。
- 任务系统权威来源仍然是 `TaskOrderProjection`，前端只做投影。

## 实施结果

- `RuntimeProgressEntry` 已扩展为结构化状态条目，支持 `kind`、`statusText`、`meta`、`toolName`、开始/完成时间和产物。
- `runtimeVisibilityProjection` 已把 `task_order_projection`、`runtime_loop_event`、`tool_start`、`tool_end`、`done/error/stopped` 投影成会话任务流程信号。
- 主聊天消息内已改为“会话任务流程”面板，任务订单作为锚点，阶段、工具、权限、验收、终止信号进入同一条时间线。
- 工具输入输出保留在次级折叠区“工具 I/O 详情”，避免和主流程抢层级。
- 已补充投影测试和 store 挂载测试，确保真实事件能进入 assistant 消息的 `runtimeProgress`。

## 验证结果

- `frontend\node_modules\.bin\tsc.cmd -p frontend\tsconfig.json --noEmit` 通过。
- `npm --prefix frontend test -- --run src/lib/runtimeVisibilityProjection.test.ts src/lib/store/runtime.test.ts src/lib/mainAgentAssemblyModes.test.ts src/lib/runtimeWorkProjection.test.ts src/lib/api/client.test.ts` 通过，44 个测试通过。
- `scripts\project_stack.ps1 -Action check` 通过，固定端口 `3000/8003` 健康。
- Edge 桌面烟测通过，无 console/page error，截图：`output/session-task-flow-ui-verification.png`。
- Edge 移动可见容器复测通过，无横向溢出，截图：`output/session-task-flow-ui-mobile-visible-verification.png`。
