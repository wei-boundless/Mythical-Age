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

### 6. Codex 式等待执行与监控投影

- 采用 Codex 的生命周期权威模型：`started/completed/interrupted/failed` 一类终态事件和 `lifecycle` 是 UI/监控判断的权威来源。
- `waiting_executor` 只表示 executor 调度边界或下一轮模型请求前的短暂队列状态，不作为长期可见运行状态。
- 当记录同时具备 `status=waiting_executor` 与 `lifecycle=stale`、`stale=true` 或诊断语义时，监控必须投影为 `stale`，不能显示为“等待继续”。
- stale 运行不计入 waiting summary，不允许走 resume 语义；可提供 `clear_from_monitor` 和 `close_runtime` 管理动作。
- 前端本地兜底 projection 必须遵循同一优先级：显式 `paused/action_required` 优先，其次 stale/diagnostics，最后才是 fresh `waiting_executor`。
- 完成/终态类事件必须作为 lossless 信号处理；普通进度可以降级或丢弃，但不能因为丢 completion 让 UI 永久等待。

### 7. 当前工作生命周期体系

目标不是只修“暂停后重发”，而是建立完整、可恢复、可重启、可审计的 current-work lifecycle。生命周期权威拆成五层：

| 层 | 权威对象 | 只负责 | 禁止事项 |
| --- | --- | --- | --- |
| Chat/Stream | `RuntimeRun` / SSE 事件 | 传输、重连、流式输出 | 不决定任务是否恢复、重启或完成。 |
| 当前工作指针 | `ActiveTurnRecord` | 当前会话正在控制哪个 TaskRun，以及 expected turn gate | 不保存执行进度，不替代 TaskRun 终态。 |
| 任务生命周期 | `TaskRun` + lifecycle event log | started/running/waiting/paused/blocked/completed/stopped/replaced | 不根据 UI 状态猜测用户新意图。 |
| 执行租约 | `executor_status` / executor epoch | scheduled/running/lost/blocked，防重复 executor | 不决定用户是继续还是重启。 |
| 用户控制输入 | `active_work_control` / `request_task_run` / steer queue | 当前轮语义动作和追加要求 | 不隐式把新任务请求改写成恢复旧任务。 |

#### 7.1 用户动作语义矩阵

| 用户语义 | 模型动作 | 运行时迁移 | 后续输入 gate |
| --- | --- | --- | --- |
| 继续当前任务 | `active_work_control.continue_active_work` + `continuation_strategy=same_run_resume` | paused/blocked/waiting -> `resume_requested` -> schedule executor | 保持或重新绑定 `active_turn` 到同一 TaskRun。 |
| 补充要求并继续 | `active_work_control.append_instruction_to_active_work` | 先写 durable steer；running 则 replan signal，paused/waiting 则 resume+schedule | 同一 TaskRun，steer 必须进入下一次 packet 并被消费。 |
| 暂停 | `active_work_control.pause_active_work` | running -> `pause_requested`，waiting -> `paused` | `active_turn` 保留，后续必须能继续/重启/停止。 |
| 停止/放弃 | `active_work_control.stop_active_work` | 非终态 -> stopped/aborted，清理 active turn | 下一轮可以作为全新请求处理。 |
| 重启/从头做/不要沿用旧进度 | `request_task_run`，并显式声明 replacement intent | 当前 TaskRun 先标记 `replaced`/`user_restarted`，再创建新 TaskRun | active turn 绑定到新 TaskRun，旧 TaskRun 只保留审计记录。 |
| 新的独立长期任务 | `request_task_run`，并显式声明 independent intent | 运行时不做隐藏意图复判；在单 current-work 约束下先对旧 TaskRun 做 replaced/stopped 审计收口，再启动新 TaskRun | 不允许 silently fork 两条当前任务，但也不把 agent 已选择的新任务请求改写成恢复旧任务。 |
| 只问状态/原因 | `active_work_control.answer_about_active_work` 或普通回答 | 不改变 TaskRun 状态 | 不改变 active turn。 |

#### 7.2 request_task_run 与 current work 的边界

- `request_task_run` 不应再无条件复用最新 `waiting_executor` TaskRun，也不应被系统阻断成二次确认。
- 如果模型想继续旧任务，应该使用 `active_work_control.continue_active_work`；runtime 不再把 `request_task_run` 静默改写成 resume。
- 如果模型想重启旧任务，`request_task_run` 可以携带明确 replacement intent，例如：
  - `diagnostics.active_work_relationship = "replace_current_work"`
  - 或 `task_contract_seed.active_work_relationship = "restart_current_work"`
- active work 存在时，`request_task_run` 表示 agent 选择开启新/替换生命周期；runtime 只做边缘控制：
  - 旧 TaskRun 可立即终止时，标记为 `user_restarted`/`replaced_by_new_task_request`。
  - 旧 TaskRun 正在运行时，请求 stop，标记为 `replaced_by_new_task_request`，并从 current-work guard 中移除，避免阻挡新任务。
  - 新 TaskRun 由当前 action 的 `task_contract_seed` 正常创建并绑定新的 active turn。
- 系统不应靠隐藏意图识别阻挡 agent；它只维护单 current-work 指针、executor 去重、旧任务审计和 active turn 边界。
- `task_lifecycle` 不再执行 `current_session_task_run` handoff guard。它只负责 contract 校验、TaskRun 创建、executor 调度和事件记录；current work 的替换、停止和审计收口统一在 facade 边界完成，避免生命周期层二次改写模型的 `request_task_run` 动作。

#### 7.3 ActiveTurn 保活与恢复

- `active_turn` 是当前会话控制句柄，不是普通 chat turn 的临时对象。
- 一旦一个 turn 创建、恢复、重启或接管非终态 TaskRun，`ActiveTurnRecord.bound_task_run_id` 必须指向该 TaskRun。
- 单个 chat turn 的 `done`/`agent_turn_terminal` 只能结束本轮传输；如果 bound TaskRun 非终态，不能清掉 active turn。
- 后端重启或 active turn 丢失后，只有用户明确对最新可恢复 TaskRun 发出 current-work 控制动作时，才可重新绑定本轮 active turn。
- 前端每次打开当前 session 必须直接 hydrate 当前 session 的 live monitor 和 active_turn_snapshot；发送当前工作输入时应携带 `expected_active_turn_id` 作为乐观并发令牌。
- `expected_active_turn_id` 缺省时不应阻断 agent：后端以当前 `ActiveTurnRecord.bound_task_run_id` 和模型可见 `active_work_context.task_run_id` 做边缘一致性校验；只有 active turn 消失、已换绑到其它 TaskRun，或前端提供的 expected id 已过期时才拒绝控制动作。
- 若没有 snapshot，前端不能猜 task id；请求仍可进入主模型回合，由后端投影 current-work 事实并让 agent 决定继续、补充、重启或普通回答。

#### 7.4 Executor 与重复发送

- scheduler 是唯一 executor 启动权威；若 TaskRun 已被 claim，重复 schedule 返回 already-running，不产生第二个 executor。
- paused/waiting 下的补充要求：写 steer -> resume -> schedule；若 schedule 失败，用户可见回复必须报告失败，不能说“已继续”。
- waiting_approval 等不可续跑态下的补充要求：只写 steer 并报告“已记录/等待确认”，不得使用“已继续处理”口吻，也不得启动 executor。
- running 下的补充要求：写 steer -> replan/interruption signal；不能直接开启第二个 executor。
- stale/diagnostic/terminal/graph-node task 不参与用户 chat 的 current-work 控制，只能走监控管理动作或 graph runtime。
- `resume_paused_task_run` 或 executor schedule 失败时，active work 控制必须返回结构化 `blocked` 结果。UI 不得收到 `active_task_steer_accepted` 或“已继续”类投影；断点和已写入的 steer 保留，等待下一次模型轮次或人工修复后继续。

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
python -m pytest backend/tests/harness_runtime_facade_regression.py -k "active_work_control or running_active_turn or waiting_executor or active_turn_rebind or paused_resend or restart_current_work or replace_current_work" -q
python -m pytest backend/tests/runtime_monitor_projection_test.py -q
```

前端 active turn 请求验证：

```powershell
cd frontend
npm test -- src/lib/runtimeVisibilityProjection.test.ts src/lib/store/runtime.test.ts src/components/layout/RunMonitorActionMenu.test.ts
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
