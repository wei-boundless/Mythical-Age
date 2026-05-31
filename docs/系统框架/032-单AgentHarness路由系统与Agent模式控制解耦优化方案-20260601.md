# 单 Agent Harness 路由系统与 Agent 模式控制解耦优化方案

日期：2026-06-01

## 1. 问题定义

当前单 Agent Harness 的主要问题不是缺少“意图识别”，而是缺少一个明确的 turn 路由权威层。

现有链路中，`QueryRuntime.astream()` 在完成 `assemble_runtime()` 后，只检查 `direct_system_route` 与 `active_work`，如果没有被拦截，就无条件进入 `AgentHarness.run_stream()`。进入 harness 后，`run_agent_invocation_stream()` 会立即创建 synthetic `turnrun:*`，然后编译 `turn_action` JSON 协议，让模型返回 `model_action_request_json`。

这导致普通对话、角色对话、工具型 turn、任务启动、任务续跑和 active work 控制被压进同一条 heavy action loop。用户看到的结果就是：任务完成后会话不自然，agent 像仍被任务控制协议包裹；更深层的问题是 agent mode 正在越权决定 harness 控制流，而不是只作为配置预设存在。

本方案的目标是：

1. 先切断 agent mode 对 harness 控制流的污染。
2. 接入显式 `TurnRuntimeRouter`。
3. 让路由由运行时事实和能力边界决定，而不是由 `runtime_mode` 直接决定。
4. 保留“角色/标准/专家/自定义”作为配置预设或 UI 选择来源，但不让任何 mode 继续作为主链路由权威。

## 2. 当前代码证据

### 2.1 QueryRuntime 缺少 turn router

文件：`backend/query/runtime.py`

当前主链：

```text
commit user message
-> run_direct_system_route
-> assemble_runtime
-> _handle_active_work_turn
-> agent_harness.run_stream
```

关键位置：

- `runtime.py:213`：先跑 direct system route。
- `runtime.py:236`：编译 runtime assembly。
- `runtime.py:252`：尝试 active work route。
- `runtime.py:261`：否则无条件进入 `agent_harness.run_stream()`。

问题：这里没有一个统一的 `TurnRuntimeRouter` 产出 route decision。`active_work` 是旁路拦截，不是统一路由体系的一部分。

### 2.2 Agent loop 过早创建 synthetic turnrun

文件：`backend/harness/loop/agent_loop.py`

关键位置：

- `agent_loop.py:62`：`_start_turn_runtime()` 在模型判断前执行。
- `agent_loop.py:70`：立刻发出 `harness_run_started`。
- `agent_loop.py:118`：随后编译 `compile_turn_action_packet()`。

问题：普通对话还没有证明需要任务生命周期，却已经创建了 `turnrun:*`。这让监控、状态、会话展示都被任务运行结构污染。

### 2.3 turn_action 固定为 JSON action 协议

文件：`backend/harness/runtime/compiler.py`

关键位置：

- `compiler.py:41`：`compile_turn_action_packet()` 是默认 turn 编译入口。
- `compiler.py:74`：`invocation_kind="turn_action"`。
- `compiler.py:97`：`output_policy={"format": "model_action_request_json"}`。

问题：默认 turn 不支持普通 assistant message 输出。即使只是角色聊天，也必须返回 JSON action。

### 2.4 Agent mode 仍绑定 turn_action 与控制策略

文件：`backend/agent_system/profiles/runtime_mode_config.py`

关键位置：

- `runtime_mode_config.py:56`：role mode 禁止 `request_task_run`。
- `runtime_mode_config.py:62`：role mode 禁用 `active_work_context`。
- `runtime_mode_config.py:69`：role mode 仍绑定 `"turn_action": ("runtime.pack.turn_action.v1",)`。
- `runtime_mode_config.py:101`：standard mode 也绑定 `turn_action`。
- `runtime_mode_config.py:137`：professional mode 也绑定 `turn_action`。

问题：mode 配置同时承担交互风格、权限、prompt pack、task lifecycle、active work、subagent 等职责。它本应是配置输入，却实际变成了 harness 控制源。role mode 只是最容易暴露问题的例子，不是唯一问题。

### 2.5 测试保护了旧行为

文件：`backend/tests/query_runtime_runtime_loop_regression.py`

关键位置：

- `test_direct_agent_response_does_not_start_task_run`
- 断言 `harness_run_started` 存在。
- 断言 `task_run_count == 1`。

问题：测试名义上说“不启动 task run”，实际上保护了 synthetic `turnrun`。这会阻碍目标架构落地。

## 3. 成熟 Agent 架构对照

### 3.1 Codex 的核心原则

本地参考：

- `D:/AI应用/openai-codex/codex-rs/core/src/session/turn.rs`
- `D:/AI应用/openai-codex/codex-rs/core/src/tools/router.rs`

Codex turn loop 的关键原则：

```text
model returns assistant message -> record and finish turn
model returns tool call -> route tool call, execute, feed observation back
```

也就是说，assistant message 是一等结果，不需要先被包成任务动作 JSON。工具路由处理的是模型真实返回的 tool call，而不是先对用户消息做模糊意图分类。

### 3.2 Claude Code 的核心原则

本地参考：

- `D:/AI应用/claude-code-nb-main/query.ts`
- `D:/AI应用/claude-code-nb-main/tools.ts`
- `D:/AI应用/claude-code-nb-main/tools/AgentTool/runAgent.ts`

Claude Code 的核心做法是：

1. query loop 管理消息、工具结果、递归 follow-up 和 token/compact。
2. 工具和子 agent 由显式 permission/context 装配。
3. 子 agent 是显式工具/能力，不是普通消息被模糊分类后暗中转走。
4. 普通 assistant message 可以自然完成 turn。

这说明成熟 agent 需要 route/dispatch，但不需要旧式“每轮意图识别层”。路由应处理运行时事实、能力边界和显式 action，而不是猜用户属于哪个任务类型。

## 4. 目标设计原则

### 4.1 route 是控制结果，mode 不是控制权威

`runtime_mode` 不能继续决定 loop 形态。它最多是 UI 或配置层的预设输入。

目标控制轴应是：

```text
TurnRoute.route_kind
```

而不是：

```text
runtime_mode = role | standard | professional
```

### 4.2 Agent mode 先断开控制

本次不急于彻底删除 role/standard/professional/custom 字段，因为它们已经被前端、任务图、契约和历史配置引用。

但必须先做到：

1. mode 不再直接决定 `turn_action`、`plain_conversation`、`task_execution` 或 active work 控制路径。
2. mode 不再直接决定是否创建 synthetic `turnrun:*`。
3. mode 不再直接决定是否参与 active work 控制。
4. mode 只作为配置预设展开为 agent profile、persona、context policy、permission ceiling、task lifecycle policy 等运行时能力。
5. route 判断不直接写 `if mode == ...` 作为长期控制逻辑，而是读取装配后的 `control_capabilities`。

切断控制的硬约束：

- `TurnRoute` 结构中不允许出现 `mode`、`runtime_mode`、`role_mode`、`standard_mode`、`professional_mode` 这类控制字段。
- `QueryRuntime` 的 dispatch 不允许读取 mode 名称。
- `agent_loop` 不允许读取 mode 名称来决定是否启动 task run、是否走 JSON action、是否控制 active work。
- mode 字段只能在 assembly 阶段被展开为 `control_capabilities`；进入 router 后，mode 只能作为 diagnostics 的历史输入记录，不能作为决策输入。

### 4.3 路由只能基于显式事实

允许路由依据：

- 请求是否已经被 direct system route 消费。
- 是否存在 active work continuation candidate。
- active work relation decision 是否确认本轮属于当前工作。
- 是否存在显式 engagement contract / task contract。
- agent profile 装配出的能力边界。
- task lifecycle 是否允许启动。
- 可见工具是否存在。
- 当前 invocation 是否要求普通对话、action turn、task execution 或 graph node execution。

禁止路由依据：

- 用户消息关键词表。
- 模糊 task type 猜测。
- 为了绕过 bug 写的 fallback action。
- mode 名称直接决定主链。

### 4.4 普通对话必须是一等路径

`plain_conversation` 不是任何 mode 的私有路径。它是成熟 agent turn 的基本路径。

本轮如果只需要自然回答，系统应允许模型直接输出 assistant message，并把它作为 canonical assistant answer 提交会话。它不应该先创建 task run，也不应该要求 JSON action。

### 4.5 task run 只能由任务生命周期开启

`task_run` 不应该作为普通 turn 的容器。

只有以下情况能启动 task run：

1. 模型在 `agent_action` route 中明确请求 `request_task_run`。
2. API / task system 显式传入 task or engagement contract。
3. active work control 明确续跑既有任务。

普通 `respond`、角色聊天、轻问答、只读工具观察，都不应该创建 task run。

## 5. 目标架构

### 5.1 新主链

```text
QueryRuntime.astream
-> commit user message
-> direct_system_route
-> assemble_runtime
-> build_turn_route
-> dispatch route
   -> plain_conversation_runner
   -> agent_action_runner
   -> active_work_control_runner
   -> explicit_contract_task_runner
   -> blocked_runtime_response
-> commit canonical assistant message
-> emit final stream event
```

### 5.2 TurnRoute 数据结构

新增文件：

```text
backend/harness/routing/turn_router.py
```

建议数据结构：

```python
@dataclass(frozen=True, slots=True)
class TurnRoute:
    route_kind: str
    invocation_kind: str
    dispatch_target: str
    reason: str
    control_capabilities: dict[str, Any]
    monitor_policy: dict[str, Any]
    diagnostics: dict[str, Any]
```

建议 route kind：

```text
plain_conversation
agent_action
active_work_control
explicit_contract_task
blocked_runtime
```

建议 invocation kind：

```text
plain_conversation
turn_action
active_work_control
task_execution
```

### 5.3 control_capabilities

`control_capabilities` 是 mode 解耦的关键。它由 runtime assembly 产出，router 只读取它，不关心它来自某个 mode preset、agent profile 还是显式 task selection。

建议字段：

```json
{
  "conversation_only": true,
  "may_emit_assistant_message": true,
  "may_call_tools": false,
  "may_request_task_run": false,
  "may_control_active_work": false,
  "may_use_subagents": false,
  "requires_json_action_protocol": false
}
```

不同 preset 可以展开成不同能力边界。router 看到的是能力，不是 `mode == role`、`mode == standard` 或 `mode == professional`。

### 5.4 agent mode 断开规则

第一阶段必须达成：

```text
mode preset
-> runtime assembly profile
-> control_capabilities
-> TurnRuntimeRouter.route_kind
-> route-specific compiler
-> route-specific runner
-> canonical assistant/task result
```

不允许：

```text
mode preset
-> directly choose harness loop
-> directly choose task lifecycle
-> directly create synthetic turnrun
```

## 6. 执行计划

### Phase 1：新增路由层，不改任务执行器

目标：

1. 新增 `backend/harness/routing/turn_router.py`。
2. 定义 `TurnRoute`。
3. 在 `QueryRuntime.astream()` 中接入 router。
4. 当前具备 action 能力的 runtime capability 可先走既有 `agent_action` 路径。
5. conversation-only capability 路由到 `plain_conversation`。

完成标准：

- 所有 turn 都有明确 `turn_route_decided` 事件。
- conversation-only capability 的 turn 不再进入 `agent_harness.run_stream()`。
- 所有路线都由 `control_capabilities` 与显式请求事实决定，不由 mode 名称进入 loop。

### Phase 2：新增 plain conversation 编译与 runner

目标：

1. 在 `RuntimeCompiler` 中新增 `compile_plain_conversation_packet()`。
2. 新增普通对话 prompt pack，例如 `runtime.pack.plain_conversation.v1`。
3. plain conversation packet 不包含 `model_action_request_json` schema。
4. plain conversation runner 直接调用模型，接收 assistant text。
5. 提交 assistant message 时标记：

```json
{
  "answer_source": "harness.route.plain_conversation",
  "answer_channel": "conversation",
  "answer_canonical_state": "final"
}
```

完成标准：

- conversation-only capability 的 direct chat 有自然 assistant answer。
- 不创建 task run。
- 不产生 `harness_run_started`。
- 不暴露 runtime packet、task id、内部协议字段。

### Phase 3：把 active work 纳入 router 结果

目标：

1. `_handle_active_work_turn()` 不再作为 QueryRuntime 的独立旁路。
2. router 先检查 active work candidate。
3. 如果需要模型判断 relation，调用现有 `decide_active_work_turn()`。
4. 如果 decision 是 active work control，route_kind=`active_work_control`。
5. 如果 decision 是 `normal_response` 或 `start_new_work`，router 继续选择普通 route。

完成标准：

- active work 控制是 router 的一种结果。
- 无关闲聊不会续跑旧任务。
- 用户询问当前任务状态时仍能自然回答。

### Phase 4：收缩 agent_action 的职责

目标：

1. `agent_action` route 只负责“模型需要选择 action”的 turn。
2. 逐步取消普通 `respond` 也创建 synthetic `turnrun` 的行为。
3. 将 `turnrun:*` 从普通 turn 监控中剥离。
4. 真正的 task run 只在 `request_task_run` 或 explicit contract 后创建。

完成标准：

- direct `respond` 不再增加 `task_run_count`。
- tool-call turn 可以记录 turn trace，但不伪装成 task run。
- task monitor 只展示真实任务和等待监管的任务。

### Phase 5：清理 mode 控制残留

目标：

1. `runtime_mode_config.py` 不再直接绑定主链 invocation。
2. `prompt_pack_refs_by_invocation.turn_action` 不再被任何 mode preset 当作 harness 控制入口。
3. `allowed_runtime_modes` 只作为资源装配约束，不作为控制流条件。
4. 旧测试中保护 synthetic turnrun 的断言删除或改写。

完成标准：

- 搜索 `mode ==`、`runtime_mode ==`，不能存在主链路由判断。
- 搜索 `role_conversation`、`standard_mode`、`professional_mode`，只允许出现在 profile/preset/prompt 描述，不允许作为 loop 分支权威。
- 搜索 `turn_action`，不能被 mode preset 当作直接 harness 控制入口。

## 7. 文件级执行清单

### 新增

- `backend/harness/routing/__init__.py`
- `backend/harness/routing/turn_router.py`

### 修改

- `backend/query/runtime.py`
  - 在 `assemble_runtime()` 后调用 `build_turn_route()`。
  - 根据 route dispatch。
  - 移除 `_handle_active_work_turn()` 的独立旁路位置，后续改为 router runner。

- `backend/harness/runtime/assembly.py`
  - 在 `RuntimeAssemblyProfile` 或 assembly payload 中加入 `control_capabilities`。
  - 所有 mode preset 都先展开为能力边界，router 不读取 mode 名称。

- `backend/harness/runtime/compiler.py`
  - 增加 `compile_plain_conversation_packet()`。
  - plain conversation 不挂 `model_action_request_json`。

- `backend/prompt_library/packs.py`
  - 新增 `runtime.plain_conversation.v1`。
  - 新增 `runtime.pack.plain_conversation.v1`。
  - prompt 必须写给 agent，而不是写开发说明。

- `backend/agent_system/profiles/runtime_mode_config.py`
  - mode preset 不再绑定主链 invocation。
  - mode preset 只表达配置预设与能力边界。

- `backend/harness/loop/agent_loop.py`
  - Phase 1 可暂不大改。
  - Phase 4 需要拆掉普通 turn synthetic task run。

- `backend/tests/query_runtime_runtime_loop_regression.py`
  - 删除或重写保护旧行为的 direct response 测试。
  - 新增 conversation-only/plain conversation route 测试。

- `backend/tests/runtime_monitor_projection_test.py`
  - 验证 plain conversation 不进入 task monitor。

### 暂不修改

- 图任务执行器。
- 特定任务契约结构。
- 子 agent 生命周期。
- 前端任务图编辑器。

这些系统会受到最终 mode 解耦影响，但不是第一阶段入口。

## 8. 验收标准

### 8.1 conversation-only capability

输入：

```json
{
  "runtime_profile": {
    "control_capabilities": {
      "conversation_only": true,
      "may_emit_assistant_message": true,
      "may_call_tools": false,
      "may_request_task_run": false,
      "requires_json_action_protocol": false
    }
  },
  "message": "你今天心情怎么样？"
}
```

说明：如果旧 UI 仍传入 `runtime_mode=role`，只能由 assembly 把它展开为上面的 capability。router 和 loop 不允许直接读取 `runtime_mode=role`。

期望：

- 产生 `turn_route_decided route_kind=plain_conversation`。
- 不产生 `harness_run_started`。
- 不产生 `taskrun:` 或 `turnrun:`。
- 不要求模型返回 JSON。
- assistant message 自然写入会话。

### 8.2 action-capable 普通 turn

输入普通问题。

期望：

- Phase 1 可由 capability route 继续走 `agent_action`。
- 后续 Phase 4 应逐步支持直接 assistant message 或 action route 内 respond 不创建 task run。

### 8.3 explicit contract task

输入显式 task/engagement contract。

期望：

- 直接 route 到 `explicit_contract_task` 或 `agent_action -> request_task_run`。
- 不经过 fuzzy intent recognition。
- task run 绑定真实 contract、artifact policy 和 verification policy。

### 8.4 active work control

有 active work 时输入：

```text
继续
```

期望：

- router 检查 active work candidate。
- relation decision 确认后 route 到 `active_work_control`。
- 续跑或追加指令。

有 active work 时输入无关闲聊。

期望：

- 不续跑旧任务。
- 进入普通 route。

### 8.5 监控展示

期望：

- plain conversation 不出现在任务监控台。
- task monitor 只展示真实运行中、等待监管、失败恢复中的任务。
- 会话页可以展示自然进行中的思考/工具/观察/结果，不暴露内部 task id。

## 9. 禁止事项

实施时禁止：

1. 新增关键词意图识别。
2. 用 `if "继续" in message` 这类逻辑决定续跑。
3. 把 role/standard/professional 改名后继续作为主链控制权威。
4. 在旧 `agent_loop` 上继续堆 mode 特例。
5. 为了兼容旧测试保留 synthetic turnrun 作为普通 turn 容器。
6. 用 fallback 隐式启动任务。
7. 把开发说明当作 agent prompt。

## 10. 风险与控制

### 风险 1：plain conversation route 切断 task monitor 后前端状态缺事件

控制：

- `plain_conversation_runner` 必须发出轻量事件：

```text
turn_route_decided
plain_conversation_started
assistant_message_committed
done
```

不要用 task monitor 事件补位。

### 风险 2：旧测试失败较多

控制：

- 失败测试按行为目标重写。
- 保护旧 synthetic turnrun 的测试直接删除或改成反向断言。

### 风险 3：agent_action executor 仍然重链路

控制：

- Phase 1 先保证 route 权威切换完成。
- 这里的“重链路”只能指 `agent_action` executor 本身仍沿用旧实现，不能指 standard/professional 这类 mode。
- Phase 4 单独处理 non-task turn trace 与 task run 分离。

### 风险 4：mode 字段历史依赖很多

控制：

- 本次不强行删除字段。
- 先禁止它作为主链 route authority。
- 后续再迁移成 profile preset / runtime preset。

## 11. 最小实施顺序

推荐按以下顺序执行：

1. 新增 router 数据结构和 route decision。
2. assembly 增加 `control_capabilities`。
3. assembly 将现有 mode/profile/task selection 展开为 `control_capabilities`。
4. compiler 增加 plain conversation packet。
5. QueryRuntime 接 router dispatch。
6. plain conversation runner 写入 assistant message。
7. 测试 plain conversation path 不创建 turnrun。
8. 将 active work 旁路纳入 router。
9. 清理 mode preset 对 turn_action 的直接控制引用。
10. 更新旧测试。

第一轮实施只要求 agent mode 不再直接控制 harness，conversation-only capability path 与 router 接入稳定，不要求一次性删除所有 `runtime_mode` 字段。

## 12. 自审结论

本方案允许继续出现 `role`、`standard`、`professional`、`runtime_mode` 的场景只有三类：

1. 当前代码证据：说明旧结构哪里把 mode 绑定到了控制流。
2. 迁移输入：旧 UI、旧配置或历史任务仍可能传入 mode 字段，但只能由 assembly 展开成 `control_capabilities`。
3. 禁止事项或清理标准：用于检查不能再把 mode 名称作为 route、dispatch、loop、task run 或 monitor 的控制依据。

本方案不允许出现的场景：

1. `TurnRoute` 携带 mode 字段。
2. `QueryRuntime` 根据 mode 名称选择 runner。
3. `agent_loop` 根据 mode 名称决定是否创建 task run。
4. `RuntimeCompiler` 根据 mode 名称决定本轮是 `plain_conversation`、`turn_action` 还是 `task_execution`。
5. monitor 根据 mode 名称决定是否展示为任务。
6. 测试断言某个 mode 必然走某个 loop。

仍需后续清理但不构成本方案控制冲突的旧债：

1. `runtime_mode_config.py` 作为历史 preset catalog 暂时存在。
2. `prompt_library` 中的 `allowed_runtime_modes` 暂时作为资源装配约束存在，但不能参与控制流。
3. `agent_action` executor 在 Phase 1 可以复用旧执行器，但它代表的是 action-capable route，不代表 standard/professional mode。
4. 图任务和特定任务中历史字段 `runtime_mode` 需要后续迁移成 profile/capability preset，不在第一轮直接删除。

真正的最终状态是：

```text
mode/preset 负责配置
route 负责控制
loop 负责执行
monitor 负责呈现
task run 只属于真实任务生命周期
```
