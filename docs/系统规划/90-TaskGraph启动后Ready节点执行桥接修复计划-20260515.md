# 90-TaskGraph启动后Ready节点执行桥接修复计划

## 0. 问题结论

在“洪荒时代”写作团队真实启动测试中，`graph.writing_team.long_novel` 能成功启动：

- 创建 `task_run`
- 创建 `coordination_run`
- 编译 11 节点、13 边 runtime spec
- 编译 dispatch plan
- `world_design` 正确进入 ready

但运行停在：

- `scheduler_phase = compiled_plan_only`
- `execution_count = 0`
- 没有生成 `stage_execution_request`
- `/coordination-runs/{id}/resume` 返回 `CoordinationRun has no LangGraph checkpoint`

这说明问题不是 Agent prompt，也不是小说输入，而是 TaskGraph 启动路径缺少从 ready 节点到既有 LangGraph 协调执行器的初始化桥。

## 1. 结构性原因

现有代码有两条路径：

1. 普通主会话/协调任务路径：
   - 创建 task run
   - 同步 runtime objects
   - 调用 `langgraph_coordination_runtime.initialize(...)`
   - 生成 `stage_execution_request`
   - 通过 continuation payload 进入节点 Agent 执行

2. 新 TaskGraph 启动 API 路径：
   - `POST /api/orchestration/runtime-loop/task-graphs/{graph_id}/start`
   - 调用 `TaskRunLoop.start_task_graph_run(...)`
   - 只创建 task run、coordination run、dispatch plan、checkpoint
   - 没有调用 `langgraph_coordination_runtime.initialize(...)`

因此 TaskGraph 主模型已能“建运行”，但尚未能“驱动首个 ready 节点执行”。

## 2. 修复原则

本轮不伪造产物，不让 Codex 代写世界观。

修复只做一件事：

- 在 `start_task_graph_run()` 创建基础运行后，如果该 TaskGraph 支持 LangGraph 协调运行，则立即初始化 LangGraph runtime，并把生成的事件写入启动结果。

不做：

- 不改写作团队图结构。
- 不改 Projection prompt。
- 不绕过 Agent 执行。
- 不手动创建 world_design 输出。

## 3. 目标行为

启动后应出现：

- `coordination_state_initialized`
- `stage_execution_request` 指向 `world_design`
- `active_stage_id = world_design`
- `agent_id = agent:world_designer`
- `task_ref = task.writing_team.long_novel.world_design`
- checkpoint 存在于 LangGraph checkpoint store

随后主会话或 runtime continuation 才能真正把 `world_design` 交给对应 Agent 执行。

## 4. 修改范围

后端：

- `backend/orchestration/runtime_loop/task_run_loop.py`

测试：

- 优先跑现有：
  - `backend/tests/task_graph_registry_test.py`
  - `backend/tests/task_system_api_regression.py`
  - `backend/tests/langgraph_coordination_runtime_regression.py`

真实验证：

- 重新启动 `graph.writing_team.long_novel`
- 输入“洪荒时代”测试种子
- 检查启动响应和 trace 是否包含 `stage_execution_request`

## 5. 验收标准

通过标准：

- TaskGraph 启动接口不只返回 compiled plan。
- 启动响应包含 LangGraph 初始化事件。
- `world_design` 形成可执行 stage request。
- 不产生任何伪造小说产物。

