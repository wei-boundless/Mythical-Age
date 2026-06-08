# Agent Task/Todo/Subagent Runtime 修复计划 - 2026-06-08

## 问题背景

最近的会话暴露出几类结构性问题：

1. Chat turn 仍可能通过旧 `task_selection` 包解释任务环境和任务身份，但当前产品并不存在独立的 task selection 层。图节点、显式任务和系统签发的工作单应传递 `runtime_contract`；用户环境绑定应来自用户或会话选择，不应由 agent 推断。
2. `agent_todo` 存在重复状态实现，并且 `start`、`complete`、`update_status`、`remove` 等目标操作在缺少稳定 `todo_id` 时可能误伤多条 todo。
3. Subagent 生命周期和 worker prompt 不完整。父任务可能在 owned child subagent 仍 pending/running 时完成；部分内置 specialist 没有绑定可直接执行的 worker prompt。
4. 用户在任务运行期间追加要求时，`steer` 不应触发额外意图识别或隐藏边界模型。它应作为当前任务的追加用户引导信息排队，并在 task executor 下一次向大模型发送运行上下文时插入，且完成前必须被消费或显式处理。

目标架构遵循成熟 agent 的单向权责链：

```text
RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> ModelTurnDecision
-> ActionPermit
-> RuntimeStartPacket
-> ExecutionLoop
```

下游层不应重新决定用户意图、选中环境、任务身份或子 agent 生命周期。运行时只能保存事实、授权动作、装配上下文、执行和记录结果。

## 权责表

| 区域 | 当前问题 | 目标权责 | 修复动作 |
| --- | --- | --- | --- |
| 用户环境 | 旧链路把环境选择混进 `task_selection` | API/session 的 `environment_binding` 优先，显式 contract 只能在无用户绑定时提供任务运行环境 | 将环境绑定和模型意图分离，拒绝旧 `task_selection` API 字段。 |
| 图/节点执行 | work order 语义被命名成 selection | Runtime 接收 `runtime_contract`，不接收 `task_selection` | 重命名执行输入、测试和诊断字段，去掉 selection 语义。 |
| Chat turn | 旧隐藏边界层可能二次判断当前工作 | 主模型回合可通过 `active_work_control` 控制已知 active work；不允许隐藏 current-work classifier 或通用 task-selection classifier 预判本轮 | 删除旧 current-work boundary 层，保留 active turn id 守卫。 |
| Steer 追加要求 | 追加要求容易被当成一条新的 chat 路由或即时回答 | `steer` 是绑定当前 task 的追加用户事实，由 executor 排队、插入、消费和完成门禁 | 建立 durable steer 队列、packet 插入点、消费状态和 final completion gate。 |
| Todo 状态 | `agent_todo` 有重复状态路径和宽松目标操作 | 单一 `AgentTodoStateStore`，存储在 `storage/runtime_state/agent_todo` | 删除 `.tmp/agent_todo` 旧路径；缺少/未知 `todo_id` 时返回结构化错误且不批量修改。 |
| Subagent 生命周期 | 父任务可能忽略 active child subagent 完成 | `SubagentControl` 和 task executor 共同约束父子生命周期 | 父任务 `respond` 前扫描 owned child runs；仍 active 时生成 repair observation。 |
| Worker role prompt | specialist 缺少直接可执行角色 prompt | 每个 callable specialist 都有直接面向 agent 的 worker prompt 和 profile binding | 补齐 knowledge/memory/PDF/table worker prompts，并用 registry/profile 测试保护。 |

## 实施阶段

### 1. Runtime contract 清理

- 全链路使用 `runtime_contract`：chat entrypoint、runtime assembly、task lifecycle、tool scheduling、graph node task execution。
- 保持 `environment_binding` 为用户/会话选择边界，agent 不承担环境选择权。
- Chat API 对旧 `task_selection` 字段使用 strict validation 拒绝。
- 删除旧 current-work boundary 层。普通消息不预跑单独 current-work classifier；明确控制当前工作时走主模型回合的 `active_work_control` action。

### 2. Steer 队列和插入机制

- 用户在 active task 期间追加要求时，先记录 durable event：
  - `user_submission_recorded`
  - `active_task_steer_recorded`
- 每条 steer 必须包含：
  - `steer_id`
  - `task_run_id`
  - `session_id`
  - `turn_id`
  - `sequence`
  - 原始用户文本
  - 创建时间和来源 authority
- 如果 executor 当前已经把 prompt 发给模型，不能半路插入；该 steer 保持 pending，等待下一次 executor 模型调用。
- 下一次组装 task execution packet 时，在任务契约和最近执行观察之后、普通历史之前插入 `User steering updates for this task` 上下文段。
- 插入文本必须明确告诉 worker：
  - 这些是用户对当前任务追加的要求。
  - 必须影响后续计划、工具调用或最终输出。
  - 不允许忽略；如果无法满足，必须在最终回答或阻塞说明中解释。
- 区分两个状态：
  - `included`：steer 已进入某次模型上下文。
  - `consumed`：模型后续动作、计划修订、工具调用或最终回答已经处理该 steer。
- 任务完成前执行 final completion gate：
  - 若存在 pending 或 included-but-unconsumed steer，拒绝父任务 `respond`。
  - runtime 注入 repair observation，要求模型处理这些 steer 后再完成。
  - 只有 steer 被消费、显式拒绝并说明原因，或任务被用户停止/关闭时，才允许终态。
- 前端只负责发送 `expected_active_turn_id` 防止串线；是否排队、何时插入、何时消费由 runtime/executor 决定。

### 3. Todo 权责合并

- `AgentTodoTool` 统一通过 `AgentTodoStateStore` 读写。
- 状态存储固定到 `storage/runtime_state/agent_todo`。
- `start`、`complete`、`update_status`、`remove` 缺少 `todo_id` 或目标不存在时返回结构化错误。
- 不保留 `.tmp/agent_todo` 兼容链路。

### 4. Subagent 生命周期守卫

- 通过局部 import 消除 runtime/control-plane 的 `SubagentControl` 循环导入。
- 父任务接受 `respond` 前扫描 owned child agent runs。
- 如果存在 pending/running child subagent，拒绝完成并给模型 repair observation，要求选择：
  - `wait_subagent`
  - `list_subagents`
  - 综合已完成 child 结果后继续
  - `close_subagent`

### 5. Worker prompt 成熟化

- 为 knowledge search、memory search、PDF analysis、structured data analysis 增加直接面向 agent 的 worker prompt。
- 在 runtime profile 中绑定 `worker_prompt_ref` 和 `agent_prompt_refs_by_invocation.task_execution`。
- Prompt 必须描述身份、职责、输入、输出、禁止事项、失败处理和质量标准，不能写成节点说明。

## 验证计划

聚焦回归：

```powershell
python -m pytest backend/tests/agent_todo_tool_regression.py -q
python -m pytest backend/tests/subagent_control_regression.py -q
python -m pytest backend/tests/worker_prompt_registry_regression.py -q
python -m pytest backend/tests/search_specialist_split_regression.py -q
python -m pytest backend/tests/sandbox_tool_runtime_regression.py -q
python -m pytest backend/tests/prompt_library_registry_regression.py -q
python -m pytest backend/tests/chat_environment_binding_regression.py -q
python -m pytest backend/tests/harness_runtime_facade_regression.py -k "active_work_control or running_active_turn or waiting_executor" -q
```

前端 active turn 请求验证：

```powershell
cd frontend
npm test -- src/lib/store/runtime.test.ts
```

静态检查：

```powershell
rg -n "\.tmp.*agent_todo|agent_todo.*\.tmp" backend -S
rg -n "request_task_selection|task_selection|explicit_task_selection" backend frontend --glob "!backend/maintenance/**" -S
rg -n "current_work_boundary|current_work_boundary_decided|harness\.current_work_boundary" backend frontend -S
python -c "import sys; sys.path.insert(0,'backend'); from harness.agent_control.controller import SubagentControl; print(SubagentControl.__name__)"
python -m compileall backend/harness backend/capability_system/tools backend/prompt_library backend/agent_system/profiles backend/request_intent backend/task_system backend/runtime/tool_runtime
git diff --check
```

运行链路烟测必须使用固定端口：

```powershell
Invoke-WebRequest http://127.0.0.1:8003/health
Invoke-WebRequest http://127.0.0.1:8003/api/sessions
Invoke-WebRequest http://127.0.0.1:3000
```

## 非目标

- 不引入新的通用意图识别层。
- 不让 prompt 授予环境访问权或任务身份权。
- 不保留旧 `.tmp/agent_todo` 路径作为兼容链。
- 不允许父任务只靠 prompt 自觉等待 child subagent。
- 不把 `steer` 当成新的 chat task selection；它只是在已知 active task 上追加用户约束。
