# 单 Agent Harness 路由系统与 Agent Mode 解耦方案

日期：2026-06-01

## 1. 当前结论

本系统没有“会话模式”。`role`、`standard`、`professional` 或历史 `runtime_mode` 不能控制 harness，也不能决定本轮走普通对话、任务、active work 或旧 action loop。

当前单 agent 主链只允许三类 route：

```text
single_agent_turn
explicit_contract_task
blocked_runtime
```

含义：

- `single_agent_turn`：默认 agent turn。模型可以直接回复，也可以通过已装配的 native runtime action 请求任务启动、active work 控制、澄清或阻止。
- `explicit_contract_task`：系统收到成型任务合同，直接进入任务生命周期，不做意图识别。
- `blocked_runtime`：runtime 装配失败或边界明确阻断。

`ask_user` 和 `block` 不是“会话模式允许澄清/阻止”，而是所有成熟 agent turn 都必须具备的通用收口动作。它们表示模型认为需要用户补充，或当前边界下无法继续。

## 2. 权威链

目标链路：

```text
QueryRuntime.astream
-> commit user message
-> direct system route
-> assemble_runtime
-> build_turn_route
-> run_single_agent_turn | run_explicit_contract_task | blocked_runtime_response
-> commit assistant message or task handoff
-> public stream projection
```

职责：

- `QueryRuntime`：API adapter，负责加载会话、提交用户消息、调用 runtime/harness、转发事件。
- `assemble_runtime`：装配 agent profile、任务环境、工具可见性、权限投影和 control capabilities。
- `turn_router`：只做结构路由，不读 mode，不调用模型，不做关键词判断。
- `RuntimeCompiler`：根据 runtime assembly 生成模型请求包，保证 allowed/forbidden action 和真实能力一致。
- `single_agent_turn`：统一处理 assistant message、native `request_task_run`、native active work control、`ask_user`、`block`。
- `task_lifecycle`：统一创建、记录、调度、恢复 task run。
- `monitor/public projection`：只呈现公开状态，不反向决定任务意图。

## 3. 路由规则

`build_turn_route()` 的判断顺序：

```text
runtime blocked -> blocked_runtime
explicit contract present -> explicit_contract_task
otherwise -> single_agent_turn
```

禁止：

- `if runtime_mode == ...`
- `if role/standard/professional`
- `conversation_only`
- `plain_conversation` route
- `agent_native_turn` route
- `agent_action` 作为单 agent 主链 route
- active work 在 router 中调用模型判断
- 用户消息关键词表

## 4. Capability 边界

control capabilities 只能表达具体能力，不允许表达模式。

有效字段：

```json
{
  "may_emit_assistant_message": true,
  "may_call_tools": false,
  "may_request_task_run": true,
  "may_control_active_work": true,
  "may_use_subagents": false,
  "requires_json_action_protocol": false,
  "has_explicit_contract": false,
  "visible_tool_count": 0
}
```

关闭任务能力时，必须写：

```json
{
  "may_request_task_run": false,
  "may_control_active_work": false
}
```

关闭工具/子 agent 时，必须写：

```json
{
  "may_call_tools": false,
  "may_use_subagents": false
}
```

不得再生成或读取：

```json
{"conversation_only": true}
```

## 5. Agent 与系统交互

### 5.1 普通回复

```text
用户消息
-> runtime 装配
-> route = single_agent_turn
-> compiler 装配 single agent turn packet
-> 模型返回 assistant message
-> commit assistant message
-> agent_turn_terminal
-> done
```

普通回复不创建 task run，不进入旧 JSON action 协议。

### 5.2 任务启动

```text
用户消息
-> route = single_agent_turn
-> 模型判断需要持续执行
-> 模型调用 native request_task_run
-> harness normalize 成 ModelActionRequest
-> task_lifecycle 建立 TaskRunContract
-> 初始化 todo
-> 记录 lifecycle event / step summary / monitor 状态
-> 调度 executor 或进入人工门控
-> turn terminal
```

任务启动由 agent 的显式动作触发，不由系统猜测用户意图触发。

### 5.3 显式合同

```text
API/task system 传入 engagement_contract 或 task_contract
-> route = explicit_contract_task
-> 标准化合同
-> 权限/监督检查
-> task_lifecycle start
-> 调度 executor 或等待人工门控
```

显式合同是系统收到的成型契约，不经过模型意图识别。

### 5.4 Active Work

```text
存在 active work context
-> context 作为事实进入 single_agent_turn packet
-> 模型根据用户本轮消息决定是否调用 native active_work_control
-> harness 执行 continue / pause / stop / append_instruction / answer_about_active_work
```

router 不判断“用户是不是想继续当前任务”。判断权在模型 turn 内，执行权在 harness。

### 5.5 澄清与阻止

```text
ask_user -> commit clarification question -> terminal
block -> commit public block reason -> terminal
```

这两个动作不属于某种 mode。它们是所有 single agent turn 的基础安全出口。

## 6. 当前必须修复的问题

### P1：`conversation_only` 残留

问题：

- `assembly.py` 曾用 `conversation_only` 隐式关闭工具、任务和 active work。
- `compiler.py` 曾用 `conversation_only` 改写 allowed actions。
- `turn_router.py` 曾允许该字段穿过 route。
- 测试曾以 `conversation_only` 保护旧行为。

修复标准：

- assembly 不生成 `conversation_only`。
- compiler 不读取 `conversation_only`。
- router 不允许 `conversation_only` 字段。
- 测试改用具体 capability。

### P1：health API 旧 harness 引用

问题：

`backend/api/health_system.py` 仍引用 `runtime.query_runtime.agent_harness`。`QueryRuntime` 已经不再拥有旧 `AgentHarness` 主链，因此这些接口会断。

修复标准：

- 不把旧 `AgentHarness` 塞回 `QueryRuntime`。
- health 只通过当前 `agent_runtime_services` / `single_agent_runtime_host` 获取 task run、trace、event count。
- 旧 health `run_stream` 执行入口未迁移时必须显式失败，不能静默复活旧链。

### P2：QueryRuntime 仍承载过多 harness 细节

当前仍待后续切出：

- active work control 执行细节。
- task executor scheduling。
- task todo 初始化。

迁移方向：

```text
QueryRuntime thin adapter
-> harness.loop.active_work_control
-> harness.loop.task_scheduler
-> harness.loop.task_todo
```

本项不能用“兼容”长期保留在 QueryRuntime。若暂未迁移，必须作为明确技术债记录。

## 7. 验收标准

代码搜索：

```text
backend/harness backend/query backend/api 不存在 conversation_only
backend/harness/routing 不存在 mode/runtime_mode 分支
backend/query/runtime.py 不引用 query_runtime.agent_harness
```

行为验收：

- 简单对话 route 为 `single_agent_turn`。
- 显式关闭任务能力时，不暴露 `request_task_run` native action。
- active work 存在但能力关闭时，不执行 active work control。
- 显式合同 route 为 `explicit_contract_task`，不进入模型意图识别。
- health API 不因缺少 `query_runtime.agent_harness` 抛 `AttributeError`。

测试命令：

```text
python -m py_compile backend/harness/runtime/assembly.py backend/harness/runtime/compiler.py backend/harness/routing/turn_router.py backend/api/health_system.py backend/query/runtime.py
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py backend/tests/dynamic_prompt_context_projection_test.py backend/tests/prompt_library_registry_regression.py backend/tests/runtime_monitor_projection_test.py -q
python -m pytest backend/tests/health_management_control_plane_regression.py -q
```
