# 会话运行可见性重构完成记录

日期：2026-05-24

范围：主会话页、`/api/chat` SSE、运行事件日志、全局运行监控、长任务阶段性输出。

## 当前事实

任务型运行的可见性主链路已经切换为：

```text
ConversationTurn
-> TaskIntentDecision
-> TaskOrder / TaskOrderDraft
-> TaskOrderRun
-> ExecutionChannel
-> TaskExecutionEnvelope
-> TaskRunLoop / RuntimeEventLog
-> TaskRun
-> Runtime visibility projection
-> Chat progress / Global runtime monitor / Detail view
```

## 已完成清理

- 全局运行监控不再只服务任务图；任务订单运行、专业任务、任务图运行、会话运行都通过统一运行投射进入 UI。
- 前端不再自行推断后端已经完成；`done / error / stopped` 只能来自后端终止事件。
- 任务订单投射只表示真实 `TaskOrderRun` 绑定；没有订单绑定的普通聊天运行只作为 `chat_turn_runtime` 观察轨迹展示。
- 运行详情页优先展示 `TaskOrderRun / ExecutionChannel`，再展示底层 `TaskRun`、专业任务摘要和任务图详情。
- 阶段性进度由结构化运行事件投射进入聊天消息和短状态条。

## 当前边界

- `task_order_projection` 只能来自后端真实任务订单绑定，不能由前端或普通 `TaskRun` 伪造。
- `TaskRun` 可以作为底层运行事实存在，但任务型工作必须通过 `TaskOrderRun` 承担可监管运行身份。
- 普通聊天轮次可以没有 `TaskOrder`；它不参与任务订单统计。
- 任务图专属监控组件仍可以使用任务图术语，但全局入口必须称为运行监控。

## 禁止项

- 禁止用前端计时、候选答案稳定、空闲状态推断任务完成。
- 禁止把没有 `TaskOrderRun` 的运行包装成任务订单投射。
- 禁止让全局监控重新退化成任务图列表。
- 禁止为了显示进度伪造模型输出、产物或验证结果。

## 验证记录

- `npm test -- src/lib/api/client.test.ts src/lib/store/runtime.test.ts src/lib/runtimeWorkProjection.test.ts`
- `npx tsc --noEmit`
- `python -m pytest backend/tests/task_order_entrypoints_regression.py backend/tests/task_order_registry_regression.py -q`
- `python -m py_compile backend/runtime/graph_runtime/run_monitor.py backend/runtime/memory/state_index.py backend/runtime/unit_runtime/loop.py backend/api/task_orders.py backend/query/runtime.py`

以上验证在本次清理后通过。
