# Vibe Coding TaskExecution Runtime and Prompt Upgrade Plan - 2026-06-04

## 1. 目标

把当前 agent 的 vibe coding 能力从“能看到项目上下文、能进入 TaskRun 执行”升级为“进入 TaskRun 后仍具备成熟 coding agent 的项目感知、并发观察、清晰委派和失败恢复能力”。

本计划只覆盖本轮审查确认的关键缺口：

- TaskExecution 支持一轮提交多个工具调用，并复用现有 batch planner 做并发/串行调度。
- 运行中的用户追加指令携带当轮 editor_context，避免“这个文件”类指代丢失。
- editor_context 语义从“把当前文件预览伪装成 selection”改为清晰的 active file preview / selection / visible files。
- prompt 补齐并发工具使用、子 agent 综合委派、editor_context 权威边界。
- 增加重复失败上限，防止同一失败动作无限重试。

暂不做总预算、总 token、总时长或总自动续跑上限。只加入重复失败熔断。

## 2. 当前技术事实

### 2.1 TaskExecution 当前只能单工具串行

现状：

- `backend/prompt_library/packs.py::RUNTIME_TASK_EXECUTION_PROMPT` 要求每轮只输出一个 JSON action。
- `backend/harness/runtime/compiler.py::task_execution_action_schema()` 只暴露单个 `tool_call` 对象。
- `backend/harness/loop/model_action_protocol.py::TaskExecutionModelActionRequest` 只有 `tool_call` 字段。
- `backend/harness/loop/task_executor.py::_invoke_task_model_action()` 设置 `allow_native_tool_calls=False`。这不是需要移除的限制；TaskExecution 仍应走 JSON action 协议，不切换到 provider-native tool calls。

结果：

- TaskExecution 进入持续任务后不能像成熟 coding agent 一样在同一轮并行读取多个文件、并行搜索多个符号或并行启动独立只读子任务。
- 现有并发实现只覆盖 `single_agent_turn`：该路径能收集多个 tool action，调用 `build_tool_batch_plan()`，并对并行 group 使用 `asyncio.wait()`。

### 2.2 现有 batch planner 可以复用

当前已有能力：

- `backend/harness/runtime/tool_batch_planner.py` 能根据工具定义、操作类型、资源锁和 admission 结果分组。
- `backend/harness/loop/single_agent_turn.py` 已经把多个 native tool calls 转成 `invocation_rows`，再由 batch planner 决定并发或串行。
- `backend/harness/runtime/tool_scheduling.py` 已经区分 file read、file write、local search、git read/write、browser、network 等操作组。

目标不是重写一套并发框架，而是让 TaskExecution 进入同一个调度模型。

### 2.3 editor_context 在 TaskRun 中被冻结

现状：

- `backend/harness/loop/task_lifecycle.py::start_task_lifecycle()` 在 TaskRun 创建时把 parent turn 的 `editor_context` 存进 `task_run.diagnostics.editor_context`。
- `backend/harness/runtime/compiler.py::_editor_context_from_task_run()` 后续只从 TaskRun diagnostics 读取这个快照。
- 运行中用户追加指令时，`backend/harness/entrypoint/runtime_facade.py::_queue_active_turn_input_if_requested()` 只把 `request.message` 写入 active steer。
- `backend/harness/loop/task_executor.py::_steer_for_projection()` 只投影 steer 文本，没有 editor_context。

结果：

- 用户在任务运行时打开另一个文件并说“这个也改一下”，前端随请求发送的新 editor_context 会在入队时丢失。
- TaskExecution 继续看到的是任务启动时的 active file，而不是用户追加指令发生时的 active file。

### 2.4 前端 editor_context 的 selection 语义不准确

现状：

- `frontend/src/lib/store/runtime.ts::chatEditorContextPayload()` 把 active inspector 的前 12000 字符放入 `active_file.selection.text`。
- 后端 `backend/harness/runtime/dynamic_context/manager.py::_editor_selection()` 按 selection 投影。

问题：

- 这不是用户真实选区，而是文件预览。
- 模型可能误判用户强调的是这段文本，而不是“当前打开文件”。
- Codex IDE context 把 active file、active selection、selection ranges、open tabs 分开表达；这个语义更适合借鉴，但不需要照抄。

### 2.5 子 agent prompt 还缺少综合委派纪律

当前 prompt 已经要求 brief 包含目标、已知事实、范围、排除项、context_refs、期望输出和失败处理。

缺口：

- 没有强制主 agent 在 worker 返回后先综合理解，再给 follow-up worker 明确文件路径、行号、错误信息和完成标准。
- 没有明确“研究 worker 可并行，写入同文件必须串行，验证 worker 最好 fresh”的工作纪律。
- 没有禁止“根据你的发现继续修”这类懒委派。

### 2.6 重复失败目前主要靠局部 guard

当前已有：

- 工具失败会进入 observation。
- prompt 要求不能原样重复失败动作。
- `task_executor` 有重复只读工具调用 guard。
- `task_executor` 已有 repeated admission guard：重复未获准动作第 2 次开始返回恢复 observation，第 3 次会暂停 TaskRun。
- `task_executor` 已有 `_MAX_MODEL_PROTOCOL_REPAIR_ATTEMPTS=3`，但它按 protocol repair 总数收口，不按同一错误指纹收口。
- `runtime/shared/tool_repetition_guard.py` 已有通用签名工具，但当前 TaskExecution 主链主要使用本地 duplicate read-only guard，尚未形成任务级失败熔断。

缺口：

- 没有统一的“同一 action/tool/error 指纹连续失败 N 次后强制改变策略或 block”的任务级熔断；现有 admission/protocol/duplicate guard 各自独立，阈值和投影语义不一致。
- 一旦模型反复触发同类协议错误、同类 admission 拒绝、同类工具失败，自动续跑可能继续制造噪声。

### 2.7 已有 step budget 不能被本计划误删

当前已有：

- `backend/harness/loop/task_executor.py::_MAX_TASK_EXECUTION_STEPS = 12`。
- `backend/harness/entrypoint/runtime_facade.py` 多个入口会传入 `max_steps`。
- `task_executor` step budget 耗尽后会通过 `_pause_executor_for_step_budget()` 进入可恢复暂停。

因此本计划中的“不做总预算”只表示不新增 token、总时长、总自动续跑或总工具调用预算；不能理解为删除已有 TaskExecution step budget。批量工具调用进入一轮 model action 后，step budget 仍按 model action step 计数，不按 batch 内每个 tool call 额外消耗 step。

## 3. 参考架构借鉴

### 3.1 Claude Code 可借鉴点

从本地 `D:/AI应用/claude-code-nb-main` 看到的成熟做法：

- 工具提示明确鼓励无依赖工具并行，依赖链串行。
- coordinator 模式明确区分：
  - 只读研究任务可自由并行。
  - 写入重任务按文件集串行。
  - worker 结果回来后，主 agent 必须自己理解并综合，再给后续 worker 明确路径、行号和改动要求。

本项目不需要复刻 Claude coordinator 模式，但应吸收这些不变量。

### 3.2 Codex 可借鉴点

从本地 `D:/AI应用/openai-codex` 看到的成熟做法：

- IDE context 是当前用户输入的上下文，不是稳定系统规则。
- active file、selection、open tabs 分开表达。
- coding agent 要持续推进到任务真实解决，但必须基于真实验证和明确边界收口。

本项目已经有 stable/dynamic/volatile 分层，不需要推倒；需要修补 TaskExecution 对动态 editor_context 和并发工具的消费能力。

## 4. 目标设计

### 4.1 Canonical TaskExecution action

TaskExecution 的 canonical 工具 action 改为：

```json
{
  "authority": "harness.loop.model_action_request",
  "action_type": "tool_call",
  "tool_calls": [
    {
      "tool_name": "read_file",
      "args": {"path": "backend/a.py"}
    },
    {
      "tool_name": "read_file",
      "args": {"path": "backend/b.py"}
    }
  ],
  "public_progress_note": "正在并行读取相关文件。",
  "public_action_state": {
    "visible_status": "waiting_for_tool",
    "next_action": "并行读取相关文件",
    "completion_status": "working"
  },
  "diagnostics": {}
}
```

规则：

- `action_type=tool_call` 可以包含 1 个或多个 `tool_calls`。
- `tool_calls` 是 canonical 字段。
- 这里的 `tool_calls` 是 TaskExecution JSON action 内的协议字段，不是 provider-native tool calls；`_invoke_task_model_action(... allow_native_tool_calls=False)` 应保持不变。
- TaskExecution prompt 不再要求模型输出单数 `tool_call`。
- 迁移期内部可以在 parser 里把旧单数归一化为数组用于现有测试过渡，但模型可见 schema 和新测试只使用 `tool_calls`。
- 过渡完成后删除 TaskExecution 单数 `tool_call` 依赖；single_agent_turn 的 native tool call 路径不受影响。
- 不允许同一个 action 同时携带非空 `tool_call` 和 `tool_calls`。迁移解析可以接受旧单数，但模型可见 schema 只能暴露数组。

### 4.2 TaskExecution batch execution

TaskExecutor 处理 `tool_calls` 时：

1. 为当前 batch action 生成一个 envelope action_request，并为每个 tool call 生成稳定 child action_request_ref / tool_call_id。
2. 对每个 child row 执行 `admit_model_action()` 和 `action_permit_from_admission()`。
3. 使用 `build_tool_batch_plan()` 分组。
4. 并行 group 使用 `asyncio.wait()` 执行。
5. 独占 group 串行执行。
6. 每个工具结果都写入 observation / tool result ledger。
7. 本轮所有 observation 聚合进入下一次 TaskExecution packet。

并发规则：

- read-only file/search/code-intelligence/git-read 可并行，前提是资源锁不冲突。
- write_file/edit_file/git-write/terminal 默认独占。
- 写同一文件必须串行。
- browser_control 默认独占，避免页面状态竞争。
- subagent spawn 可以并行，但 wait / message / close 必须按具体 subagent ref 串行化。

审批和拒绝规则：

- admission / action permit 必须逐个 child tool call 判断，不能因为 batch envelope 被允许就跳过单个工具边界。
- 某个 child 被拒绝时，为该 child 生成 admission observation；其他互不依赖且已获准的 child 可以继续执行。
- 某个 child 需要显式人工审批时，必须记录 child-level pending approval。已经执行成功的 sibling tool call 不得在审批 replay 时重复执行。
- `backend/harness/loop/task_tool_approval.py` 与 `_replay_approved_pending_tool_call()` 当前只处理单个 `action_request`，Phase 2 必须同步升级为 child-level replay，或在过渡期规定“包含需要审批工具的 batch 被拆成单工具独占组”。
- 任何审批 replay 都必须重新跑 admission 和 action permit；批准只证明用户确认了该风险，不代表绕过 runtime 权限。

进度和事件规则：

- `model_action_request_received` 可以记录 batch envelope。
- `task_tool_call_started`、`task_tool_observation_recorded`、approval、duplicate guard、repeated failure guard 必须记录 child refs。
- `runtime/shared/action_request.py::build_tool_action_request()`、前端 runtime visibility projection 和 store progress 文案需要支持 `tool_calls` 数组，否则 UI 仍只会显示第一个工具或隐藏 next_action。

### 4.3 运行中 editor_context 作为 steer-local context

新增 active steer editor context 规则：

- TaskRun 初始 editor_context 仍作为 `task_initial_editor_context`，表示任务启动时用户关注的文件。
- 用户运行中追加输入时，如果请求携带 editor_context，把它和 steer 一起保存。
- TaskExecution 投影 pending_user_steers 时，带上 steer-local editor_context。
- prompt 明确：
  - 解释该 steer 时，优先使用 steer 自带 editor_context。
  - 初始 editor_context 不能覆盖后来的 steer editor_context。
  - editor_context 是上下文证据，不授予额外文件权限；权限仍来自 session project binding 和 runtime assembly。

推荐投影形态：

```json
{
  "pending_user_steers": [
    {
      "steer_id": "steer:...",
      "content": "这个文件也改一下",
      "editor_context": {
        "source": "frontend.center_workspace",
        "captured_at": "...",
        "active_file": {"path": "frontend/src/Foo.tsx", "dirty": false},
        "visible_files": [{"path": "frontend/src/Foo.tsx"}],
        "authority": "harness.loop.active_task_steer.editor_context_snapshot"
      }
    }
  ]
}
```

### 4.4 editor_context 语义清理

前端 payload 调整为：

```json
{
  "active_file": {
    "path": "frontend/src/App.tsx",
    "language_id": "typescriptreact",
    "dirty": true,
    "content_preview": {
      "text": "...",
      "start": {"line": 0, "character": 0},
      "end": {"line": 120, "character": 3},
      "truncated": true,
      "source": "frontend_inspector"
    },
    "selection": null,
    "visible_ranges": []
  },
  "visible_files": []
}
```

规则：

- `selection` 只表示真实用户选区。
- 当前前端没有真实选区时，不发送 selection。
- 当前文件内容片段放 `content_preview`。
- 后端 dynamic context 同时支持 `selection` 和 `content_preview`。
- prompt 把 content_preview 描述为“文件局部上下文”，不能当完整文件事实；修改前仍需读文件或确认 dirty 内容。

### 4.5 prompt 更新范围

更新目标：

- `RUNTIME_TASK_EXECUTION_PROMPT`：说明 `tool_calls` 数组、并发读/搜、串行写、收到批量观察后继续判断。
- `MAIN_INTERACTIVE_TASK_EXECUTION_PROMPT`：加入“独立只读工具应合并到同一 action；同文件写入和依赖链必须串行”。
- `TOOL_SUBAGENT_GUIDANCE`：加入“worker 不共享主对话；返回后主 agent 必须综合；follow-up brief 必须包含路径、行号、错误信息、完成标准”。
- editor context notes：加入 steer-local editor_context 优先级和 content_preview/selection 区分。

不做：

- 不把 Claude/Codex 的 prompt 原文照搬进本项目。
- 不把内部 trace、event id、segment plan 暴露给模型。
- 不让 prompt 替代 runtime 权限判断。

### 4.6 重复失败上限

新增任务级 repeated failure guard，但必须复用并约束现有局部 guard，不能再堆一套互相竞争的收口逻辑。

指纹来源：

- model action protocol invalid：`action_type + validation_errors`
- admission denial：`action_type + tool_name + normalized_args + denial_reason`
- tool failure：`tool_name + normalized_args + error_code/status`
- duplicate guard：复用现有 duplicate read-only fingerprint

必须排除的字段：

- request_id、tool_call_id、step_index、timestamp、event_offset、随机 observation_id。
- protocol repair 当前 `_stable_model_protocol_repair_ref()` 包含 `step_index`，不能直接作为重复失败指纹；需要新增稳定 fingerprint 函数。

默认策略：

- admission denial 沿用现有 `_REPEATED_ADMISSION_GUARD_COUNT=2` 和 `_REPEATED_ADMISSION_PAUSE_COUNT=3`，只把事件名、active failure 投影和指纹计算并入统一 repeated failure ledger。
- protocol invalid 沿用 `_MAX_MODEL_PROTOCOL_REPAIR_ATTEMPTS=3` 的 recoverable block 语义，但新增同指纹统计，避免 3 个不同格式错误被误判为同一重复失败。
- tool failure / duplicate failure 使用新任务级 fingerprint：同一 fingerprint 连续失败 3 次，写入 `repeated_failure_limit_exceeded` observation；若下一步仍提交同 fingerprint，TaskExecutor 直接 block 当前 TaskRun，状态为 recoverable blocked。
- batch tool call 中每个 child tool call 独立统计失败；一个 child 超限不能污染同 batch 中其他工具。

不做总预算：

- 不新增总 step 数限制；已有 `_MAX_TASK_EXECUTION_STEPS` 和入口 `max_steps` 保持有效。
- 不限制总自动续跑次数。
- 不限制总 token。

## 5. 分阶段实施计划

### Phase 1：TaskExecution action 协议升级

目标：

- 引入 canonical `tool_calls` 数组。
- 更新 TaskExecution schema 和 parser。
- 保证单工具也是数组长度 1。

文件：

- `backend/harness/loop/model_action_protocol.py`
- `backend/harness/runtime/compiler.py`
- `backend/prompt_library/packs.py`
- `backend/prompt_library/agent_prompts.py`
- `backend/runtime/shared/action_request.py`
- `backend/tests/*model_action*`
- `backend/tests/*prompt*`

完成标准：

- TaskExecution packet 中 action schema 暴露 `tool_calls`。
- parser 能生成 `TaskExecutionModelActionRequest.tool_calls`。
- parser 拒绝模型可见新协议下同时携带非空 `tool_call` 和 `tool_calls` 的 payload。
- 旧 TaskExecution prompt 不再要求单数 `tool_call`。
- `_invoke_task_model_action()` 仍保持 `allow_native_tool_calls=False`，避免 TaskExecution 同时存在 JSON action tool calls 和 provider-native tool calls 两条主链。

禁止：

- 不改 single_agent_turn native tool call 主链路。
- 不保留两个长期并行 schema。

### Phase 2：TaskExecution batch planner 接入

目标：

- TaskExecutor 对 `tool_calls` 构造 invocation rows。
- 复用 `build_tool_batch_plan()`。
- 实现 TaskExecution 的并行 group 和串行 group 执行。

文件：

- `backend/harness/loop/task_executor.py`
- `backend/harness/runtime/tool_batch_planner.py`
- `backend/harness/runtime/tool_scheduling.py`
- `backend/harness/loop/action_permit.py`
- `backend/harness/loop/task_tool_approval.py`
- `backend/runtime/shared/action_request.py`
- `frontend/src/lib/runtimeVisibilityProjection.ts`
- `frontend/src/lib/store/runtime.ts`
- `backend/tests/tool_batch_planner_regression.py`
- `backend/tests/task_executor_*`

完成标准：

- 两个互不冲突的 read_file/search_text 能在同一 TaskExecution step 并行执行。
- 两个同文件 edit_file 必须串行或被 planner 拆组。
- 批量工具结果都进入 observation，并在下一次 prompt 的 `latest_tool_results/current_facts` 中可见。
- batch 中某个工具需要审批时，审批 replay 只重放该 child，不重复执行已完成 sibling。
- batch 中某个工具 admission deny 时，deny observation 可见，其他已获准且互不依赖工具不被无故阻止。
- 前端能显示 batch 中多个工具的开始、目标、结果和失败，而不是只显示第一个 `tool_call`。

禁止：

- 不绕过 admission。
- 不绕过 action_permit。
- 不让并发写入同一资源。
- 不让审批 replay 跳过权限判断。

### Phase 3：active steer editor_context 绑定

目标：

- 运行中用户追加输入时保留当轮 editor_context。
- TaskExecution 投影 pending steer 时携带 steer-local editor_context。

文件：

- `backend/harness/entrypoint/runtime_facade.py`
- `backend/harness/loop/task_executor.py`
- `backend/harness/loop/task_steering.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/tests/vscode_editor_context_regression.py`
- `backend/tests/dynamic_prompt_context_projection_test.py`

完成标准：

- 用户追加 steer 时，steer 记录包含 editor_context snapshot。
- TaskExecution packet 中 pending_user_steers 能看到该 steer 的 active_file。
- 新 steer editor_context 不覆盖 TaskRun 初始 editor_context，而是作为 steer-local context 并列投影。

禁止：

- 不用 editor_context 直接改变项目绑定。
- 不用 editor_context 扩大工具权限。

### Phase 4：前端 editor_context 语义清理

目标：

- `selection` 只表示真实选区。
- 当前文件预览改为 `content_preview`。
- 保持一个 session 一个页面文件上下文，不跨 session 污染。

文件：

- `frontend/src/lib/store/runtime.ts`
- `frontend/src/lib/store/types.ts`
- `frontend/src/lib/store/runtime.test.ts`
- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/tests/dynamic_prompt_context_projection_test.py`
- `frontend/src/lib/runtimeVisibilityProjection.ts`

完成标准：

- 没有真实选区时，payload 不发送 `selection.text`。
- 当前文件预览进入 `active_file.content_preview.text`。
- 后端 volatile editor_context 同时正确投影 active file、content_preview、visible_files。
- session A 打开的文件不会进入 session B 的 editor_context；运行中追加 steer 时也遵守同一 session 绑定。

禁止：

- 不把 content_preview 当完整文件事实。
- 不让 dirty preview 自动替代 read_file / edit_file 的真实文件校验。

### Phase 5：prompt 和子 agent 委派纪律升级

目标：

- 让 agent 明确知道什么时候合并独立工具调用。
- 让 agent 明确知道 worker 结果必须由主 agent 综合后再派发。
- 让 prompt 与新 `tool_calls` schema 一致。

文件：

- `backend/prompt_library/system_prompts.py`
- `backend/prompt_library/agent_prompts.py`
- `backend/prompt_library/tool_prompts.py`
- `backend/prompt_library/packs.py`
- `backend/harness/runtime/compiler.py`
- `backend/tests/prompt_library_registry_regression.py`
- `backend/tests/tool_prompt_guidance_regression.py`
- `backend/tests/prompt_accounting_ledger_test.py`

完成标准：

- TaskExecution prompt 明确支持批量工具。
- runtime projection 不再写“当前持续任务执行协议每次只能提交一个 action；如需工具，提交一个本轮可见工具调用”这类和 `tool_calls` 数组冲突的旧文案，应改成“一次 action 可以包含多个互不依赖工具调用；runtime 决定并发或串行”。
- 子 agent guidance 禁止懒委派，要求路径、行号、错误信息、完成标准。
- editor context notes 区分 initial task context、steer-local context、content preview、selection。

禁止：

- 不加入大段参考系统原文。
- 不把开发者说明写成 agent prompt。

### Phase 6：重复失败上限

目标：

- 对同一失败指纹连续失败设置上限。
- 超限后给模型一次明确 observation。
- 再次重复则 block，避免无限噪声。

文件：

- `backend/harness/loop/task_executor.py`
- `backend/runtime/shared/tool_repetition_guard.py`
- `backend/harness/runtime/dynamic_context/task_state_projector.py`
- `backend/tests/tool_repetition_guard_regression.py`
- `backend/tests/task_executor_*`
- `backend/tests/model_response_protocol_regression.py`

完成标准：

- 同一工具失败指纹连续 3 次后生成 `repeated_failure_limit_exceeded`。
- 模型下一轮看到该 active failure。
- 第 4 次同指纹动作被 runtime block。
- 不影响合理的“修正参数后重试”。
- 现有 repeated admission guard 仍按第 2 次观察、第 3 次暂停生效，不被新 guard 覆盖。
- protocol repair 仍有 3 次 recoverable block，但同指纹统计不能使用包含 `step_index` 的 repair ref。

禁止：

- 不加入总预算。
- 不把所有失败都强制终止；只限制同指纹重复失败。

### Phase 7：清理旧链路和验证

目标：

- 删除 TaskExecution 单数 `tool_call` 作为模型可见协议的残留。
- 清理旧 prompt 里的单工具限制。
- 更新测试，确保新链路稳定。

文件：

- 上述所有已改模块。
- `backend/tests/*task*`
- `backend/tests/*prompt*`
- `backend/tests/*vscode*`
- `frontend/src/lib/store/runtime.test.ts`

完成标准：

- TaskExecution 新协议测试通过。
- editor_context steer 测试通过。
- prompt packet 中不再出现“每轮只能提交一个工具调用”的旧限制。
- 旧单数 `tool_call` 只允许在 single_agent_turn 或兼容解析测试中出现；TaskExecution prompt 不再暴露它。
- 前端 runtime projection 和 store progress 不再依赖单数 `action_request.tool_call` 才能显示工具活动。
- approval pending / replay / grant 里不存在会重复执行 sibling tool call 的旧单数假设。

## 6. 验证矩阵

| 场景 | 预期 |
| --- | --- |
| TaskExecution 一轮请求 3 个 read_file | batch planner 规划并行 group，3 个 observation 全部进入下一轮 |
| TaskExecution 一轮请求 2 个同文件 edit_file | planner 拆成串行或 admission 阻止冲突 |
| TaskExecution 一轮请求 read_file + edit_file 同文件 | edit 依赖 read 时必须串行 |
| TaskExecution 一轮请求 read_file + 需要审批的 edit_file | read_file 可记录 observation；edit_file 进入 child-level pending approval，批准后只重放 edit_file |
| TaskExecution 一轮请求一个被拒绝工具 + 一个获准只读工具 | 拒绝工具生成 admission observation；获准只读工具不被强行否定 |
| 用户运行中打开新文件并追加“这个文件也改” | pending steer 带新 active_file，模型可解释“这个文件” |
| 前端无真实选区但打开文件 | payload 使用 content_preview，不使用 selection |
| 同一工具错误连续 3 次 | 生成 repeated_failure_limit_exceeded observation |
| 第 4 次同指纹失败动作 | TaskRun block，提示必须改变策略 |
| 同一 admission denial 连续 3 次 | 沿用现有 repeated admission pause，不再额外生成矛盾 block |
| 三个不同 protocol invalid | 按已有 protocol repair 总数收口，但不被同一 fingerprint guard 误判为同类重复 |
| batch 中一个 child 连续失败 | 只统计该 child fingerprint，不污染同 batch 其他工具 |
| 子 agent research 后 follow-up | prompt 要求主 agent 写明确路径/行号/完成标准 |
| 前端展示 batch 工具动作 | 展示多个工具名和目标，runtime next_action 校验不会因为没有单数 tool_name 而隐藏 |
| TaskExecution step budget | batch 内多个工具不额外消耗 model step；已有 max_steps 耗尽仍进入 recoverable pause |

## 7. 风险控制

- 并发工具只扩大吞吐，不扩大权限。每个 tool call 仍走 admission 和 action permit。
- editor_context 只提供上下文，不提供授权。项目绑定仍是 session project binding。
- 批量工具结果必须逐条入 observation，不能只汇总成一段自然语言。
- 重复失败 guard 必须基于 normalized fingerprint，避免因为 timestamp/request_id 变化失效。
- prompt 更新必须和 schema 同步，否则模型会生成运行时无法解析的 action。
- approval replay 是高风险路径。任何 child-level pending approval 都必须有稳定 child ref，批准后只能重放该 child，不能重放整个 batch。
- 前端进度展示不能继续只读 `tool_call` 单数字段，否则后端升级后用户会看到“进入 task 但没有回应/没有工具细节”的假象。
- provider-native tool calls 不能和 TaskExecution JSON action `tool_calls` 混用，否则会出现两套 tool call 历史和 tool_call_id 对账。
- 已有 step budget 是恢复边界，不是本计划要删除的预算；批量工具升级不能让任务无限跑。

## 8. 切换规则

推荐一次性按 Phase 1-7 连续落地，不长期保留双协议。

允许的短过渡：

- parser 在一个实施分支内临时接受旧 `tool_call` 并归一化为 `tool_calls`，用于让现有测试逐步迁移。
- 过渡期如果 approval replay 暂未升级到 child-level，只允许 batch planner 在含审批风险工具时拆成单工具独占 action，不允许把整个 batch 存成一个 pending approval。
- 过渡期如果前端 batch 展示未完成，后端事件至少必须提供 `tool_calls` 数组和 batch summary，不能丢失工具明细。

最终状态：

- TaskExecution 模型可见协议只有 `tool_calls`。
- TaskExecution executor 主链路按 batch planner 执行。
- single_agent_turn 继续保留 native tool call + batch planner 路径。
- TaskExecution 仍保持 provider-native tool calls disabled，只使用 JSON action 协议。
- approval、progress、observation、repeated failure、frontend projection 都使用 batch envelope + child tool call refs。

回滚规则：

- 如果 Phase 2 并发执行出现状态污染，保留 `tool_calls` 协议但把 planner 配置为全部串行，先保证语义正确。
- 如果 Phase 3 editor_context steer 投影出现权限混淆，保留 steer 文本，暂时只把 editor_context 存 trace，不进模型，直到权限边界测试补齐。
- 如果 child-level approval replay 无法一次落地，先禁止含审批风险工具进入并行 batch，而不是保留会重放整个 batch 的旧单数 pending approval。

## 9. 实施顺序建议

优先级：

1. Phase 1 + Phase 2：先解决 TaskRun 进入后不能并发的问题。
2. Phase 3 + Phase 4：再解决“当前打开文件”在运行中指代丢失和 selection 语义不准。
3. Phase 5：同步更新 prompt，避免新协议和旧语言冲突。
4. Phase 6：加重复失败上限。
5. Phase 7：清理旧限制和补齐验证。

这条顺序的原因：

- 并发协议是主干，prompt 必须围绕主干写。
- editor_context 是 vibe coding 的项目感知核心，必须在 TaskRun 和 active steer 两条路径都成立。
- 重复失败 guard 可以独立补强，不应阻塞主干能力升级。

## 10. 本轮审查结论

原计划的核心方向成立，但存在以下遗漏和冲突，已经在本文修正：

- `allow_native_tool_calls=False` 不是需要修掉的问题。TaskExecution 应继续禁止 provider-native tool calls，只升级 JSON action 内的 `tool_calls` 数组。
- “不做总预算”不能理解为删除已有 step budget。当前 `_MAX_TASK_EXECUTION_STEPS`、入口 `max_steps` 和 `_pause_executor_for_step_budget()` 是可恢复运行边界，应保留。
- 重复失败上限不能覆盖现有 repeated admission guard 和 protocol repair guard。新设计必须把 admission/protocol/tool failure 纳入统一 ledger，但保留各自现有收口语义。
- 原计划漏了 approval pending / replay。批量工具里只要有需要审批的 child，就必须 child-level pending approval；批准后不能重放已经成功的 sibling。
- 原计划漏了前端进度和 runtime visibility projection。后端升级为 `tool_calls` 后，前端不能继续只依赖单数 `action_request.tool_call` 展示工具活动。
- 原计划漏了 batch envelope 与 child refs。event log、observation、approval、duplicate guard、repeated failure 和 tool_call_id 对账都需要稳定 child ref。
- 原计划对 protocol repeated fingerprint 还不够精确。当前 repair ref 包含 `step_index`，不能直接作为同指纹重复失败判断依据。
