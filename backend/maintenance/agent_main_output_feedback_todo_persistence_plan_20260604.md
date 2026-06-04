# Agent 主页面公开反馈优化计划

## 目标

- 主会话只展示用户能理解的工作反馈，不展示 `agent_todo`、工具名、内部事件名或 JSON。
- 开局要有一次明确判断，让用户知道 agent 已经理解任务并进入工作。
- 多步骤任务展示可恢复的处理清单；刷新后从 runtime events 重建。
- 工具返回后展示观察报告，表达“得到什么、下一步意味着什么”。
- 结束时只保留一个收口总结，避免 assistant 正文和 timeline 重复。

## 目标架构

- `progress_presenter.py`：唯一的 runtime event 归一层，负责把 agent todo、模型公开判断、工具观察转成 work unit。
- `public_chat_timeline.py`：只把 work unit 投影成聊天可见条目。
- `public_timeline_stream.py`：实时 SSE 复用同一套 todo 投影，不维护第二套状态。
- 前端只消费 `public_timeline`，不理解工具内部结构。

## 实施边界

- 不新增独立公开状态聚合器。
- 不在前端硬编码工具名解释。
- 不保留过时的 `public_execution_state` API 字段。
- 不为观察报告二次扫描完整事件流；直接使用 work unit 的 evidence。

## 验证

- 后端：`pytest backend/tests/agent_todo_tool_regression.py backend/tests/runtime_progress_presenter_regression.py backend/tests/runtime_monitor_projection_test.py backend/tests/harness_runtime_facade_regression.py::test_session_runtime_timeline_projects_tool_observation_as_agent_visible_observation -q`
- 前端：`npx vitest run src/lib/runtimeVisibilityProjection.test.ts src/lib/store/runtime.test.ts src/components/chat/PublicRunActivity.test.ts src/components/chat/ChatMessage.test.ts`
- 类型：`npx tsc --noEmit`
- 页面：固定端口 `127.0.0.1:3000`、`127.0.0.1:8003` 实测。
