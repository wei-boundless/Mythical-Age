# request_task_run 控制信号架构修复计划书

## 0. 文档状态

本文是任务启动机制后续修复的执行计划书，不表示代码已经按本文全部完成。

最新锁定决策：

- 保留 `request_task_run` 名称；当前阶段不改成 `start_task`。
- `request_task_run` 是 agent 发出的任务生命周期启动控制信号，不是系统根据自然语言猜出来的语义结果。
- 系统没有资格判断用户语义或 agent 语义是否“应该开启任务”；系统只负责暴露合法控制动作、校验结构、归一化合同、启动 runtime 生命周期。
- 不做关键词触发、显式用户语义触发、自然语言拦截或系统强制任务启动。
- 公开反馈与结构动作的一致性校验可以保留，但它只防止 agent 口头说“开启任务”而动作不是 `request_task_run`，不能反向变成系统替 agent 决定开启任务。
- 任务执行阶段可以在 prompt 尾部加入 `Current Task Attention Index` 提醒 agent 关注当前任务、todo、plan 和验收；该索引只用于执行注意力，不参与任务是否启动的判断。

后续实现必须先经用户确认本文方向，再按阶段完整落地。

## 1. 目的

本计划修复的是任务启动机制的底层控制动作契约。

正确目标不是让 agent 背一份巨大的内部 JSON，也不是让系统按用户句子猜测“这是任务”。正确目标是建立一条鲜明的控制信号通道：

```text
agent 自己判断当前工作需要持续任务生命周期
-> agent 通过 request_task_run 发出结构化控制信号
-> runtime 只做结构校验、权限/资源边界校验和归一化
-> runtime 生成 canonical TaskRunContract + WorkModeContract
-> task lifecycle 创建 task_run_id
-> executor 在任务身份下执行、更新 todo/plan、投影和收口
```

本文覆盖：

- provider strict tool/function calling 如何承载控制动作 schema；
- `request_task_run` 的最小 TaskStartIntent 形状；
- runtime 与 agent 的权责边界；
- prompt 如何写成 agent 能直接执行的契约；
- task 执行阶段的缓存与尾部注意力索引；
- 文件级实施清单和 CLI 验证闭环。

## 2. 当前断点

当前问题不是简单的“JSON 太复杂”，而是权责和承载层混在一起。

已观察到的断点：

- 普通工具和控制动作有时都走 provider tool，有时又要求 action object，agent 不清楚 `request_task_run` 到底是不是一个可调用控制动作。
- prompt 里既出现“需要长期工作就 request_task_run”，又暴露内部 `TaskRunContract` 骨架，容易让 agent 写出 `container_contract`、DSML wrapper 或完整内部合同碎片。
- 任务启动合同里混入工具、skill、环境、权限等 runtime 字段，导致 agent 试图给自己授权。
- repair feedback 有时像在要求 agent 补完整内部合同，而不是修正最小启动意图。
- 系统曾有被误读为“用户明确说启动任务就必须启动”的方向，这会让系统越权判断用户语义，必须禁止。
- 缓存与动态任务焦点没有分清：工具 schema、控制动作 schema 应稳定；当前 todo 游标、当前任务目标、验收焦点必须放在 volatile tail。

缺失的系统属性：

```text
控制动作入口不够鲜明；
TaskStartIntent 与内部 TaskRunContract 没有彻底分层；
agent 语义决定权、runtime 结构接入权、executor 执行权没有在 prompt 和代码中同步表达；
任务启动 turn 与任务执行 loop 的上下文形状没有明确分离。
```

## 3. 源码依据

### 3.1 本项目依据

主要链路：

```text
backend/harness/runtime/compiler.py
backend/harness/runtime/control_action_schema.py
backend/harness/runtime/tool_call_contract.py
backend/harness/runtime/provider_tool_schema.py
backend/runtime/model_gateway/lightweight_chat_model.py
backend/harness/loop/single_agent_turn.py
backend/harness/loop/model_action_protocol.py
backend/harness/loop/admission.py
backend/harness/loop/task_lifecycle.py
backend/harness/loop/task_executor.py
backend/harness/entrypoint/runtime_facade.py
backend/cli/main.py
backend/prompt_library/packs.py
backend/prompt_library/rules.py
backend/prompt_library/agent_prompts.py
backend/prompt_library/utility_prompts.py
```

当前已有可继承的基础：

- `control_action_schema.py` 已能把 `request_task_run` 暴露为 provider-native strict control action，并把 native tool call 转成 `ModelActionRequest` payload。
- `tool_call_contract.py` 已区分 `ordinary_tool_submission` 与 `control_action_submission`。
- `provider_tool_schema.py` 和 `lightweight_chat_model.py` 已支持 per-tool `strict` 标志进入 provider payload。
- `model_action_protocol.py` 已有 `compact_task_start_intent_v1 -> task_run_contract_seed -> canonical layers` 的归一化雏形。
- `task_lifecycle.py` 的 `contract_from_action_request` 是 `TaskRunContract` 的 runtime 生成入口。
- `single_agent_turn.py` 已有 native control action parse、repair template 和混合动作拒绝逻辑。
- `compiler.py` 已有 action schema、prompt contract 和 `Current Task Attention Index` 的初步实现。
- `backend/cli/main.py` 已提供 `send`、`task-run goal/plan/todo`、`task-run watch/trace` 等真实 CLI 验证入口。

需要修正的重点：

- 把这些能力收束成唯一主链路，而不是 provider strict、action object、旧 contract skeleton 三套并存。
- prompt 必须把 `request_task_run` 解释为 agent 可选择的控制信号，而不是系统语义判断结果。
- repair 必须围绕紧凑 TaskStartIntent，不再诱导 agent 手写内部 `TaskRunContract`。
- `Current Task Attention Index` 必须仅在 task execution tail 中做注意力提醒，不能进入 task-start 判断或 stable prefix。

### 3.2 Codex 参考

本地源码：`D:/AI应用/openai-codex`。

相关文件：

- `codex-rs/tools/src/responses_api.rs`
- `codex-rs/tools/src/tool_spec.rs`
- `codex-rs/core/src/tools/handlers/plan_spec.rs`
- `codex-rs/core/src/tools/handlers/goal_spec.rs`

可借鉴机制：

- `ResponsesApiTool` 用 `name / description / strict / parameters` 定义 provider tool 形状。
- `update_plan` 只暴露紧凑 `{ explanation?, plan[{ step, status }] }`，runtime 和 UI 持有计划状态。
- `create_goal/update_goal` 只让模型提交目标或状态变更，预算、用量、生命周期约束由 runtime 管。
- 计划和目标工具是控制面入口，不要求模型写完整内部 runtime 状态。

不可照搬点：

- Codex 的 `update_plan` 是 checklist 控制工具，不等价于本项目的长期 task lifecycle。
- 本项目需要 `TaskRunContract + WorkModeContract + executor + projection + resume`，不能只做轻量 todo。

### 3.3 Claude Code 参考

本地源码：`D:/AI应用/claude-code-nb-main`。

相关文件：

- `Tool.ts`
- `tools/TaskCreateTool/TaskCreateTool.ts`
- `tools/TodoWriteTool/TodoWriteTool.ts`
- `utils/api.ts`
- `utils/toolSchemaCache.ts`

可借鉴机制：

- `Tool.ts` 集中定义工具的 schema、strict、validateInput、checkPermissions、并发、可中断和结果映射。
- `TaskCreateTool` 用严格的小对象 `subject / description / activeForm? / metadata?` 创建任务，任务 ID 和任务状态由 runtime 管。
- `TodoWriteTool` 使用 `strict: true` 和紧凑 `{ todos }` 更新 todo，存储和清理由 runtime 管。
- `utils/api.ts` 只在 provider、模型和工具都支持时添加 `strict: true`。
- `toolSchemaCache.ts` 把 session-stable tool schema 缓存起来，可变的 defer/cache 控制用 per-request overlay，避免 prompt cache 被动态字段破坏。

不可照搬点：

- Claude Code 的 task/todo 主要是工作清单和子任务协作，不直接等价于本项目的 `TaskRunContract`。
- 本项目需要把 task start 当作 agent control action，而不是普通能力工具。

## 4. 方案取舍

### 4.1 只优化 prompt

不采用为主方案。

原因：prompt 可以让 agent 更懂，但不能解决 provider transport、schema strict、native call parsing、runtime normalization 和 task lifecycle 对接的问题。只写更长提示会继续让 agent 在自然语言、action object、内部 JSON 之间摇摆。

### 4.2 揭露式任务合同

部分采用。

正确用法是 progressive disclosure repair：当 agent 发出不合格 `request_task_run` 时，repair feedback 揭露缺失字段和最小示例。

不把完整 `TaskRunContract` 提前塞给 agent。启动 turn 只暴露 `TaskStartIntent`，内部合同由 runtime 生成。

### 4.3 把任务当普通工具

不采用为主方案。

`request_task_run` 可以通过 provider function/tool calling 承载 schema，但语义上不是普通 read/edit/search 工具。它是模型动作控制面的一员，和 `respond / ask_user / block / active_work_control` 同层。

普通工具执行外部能力；控制动作改变本轮模型行动和 runtime 生命周期。

### 4.4 最终采用：strict control action schema

采用。

把 `request_task_run` 定义为 provider strict function/tool schema 承载的控制动作：

```text
ordinary tools:
  read_file / edit_file / terminal / search / browser
  -> capability execution plane

control actions:
  respond / ask_user / block / request_task_run / active_work_control / pause_for_user_steer
  -> model action control plane
```

provider transport 可以都是 tool/function call；语义 plane 必须分开。

## 5. 推荐架构

### 5.1 权责链

固定链路：

```text
RuntimeCompiler
-> ToolCallContract
-> ControlActionSchema
-> provider strict control action binding
-> agent chooses exactly one next action
-> native control call parsed into ModelActionRequest
-> ActionPermit validates allowed action and structural boundary
-> compact TaskStartIntent normalized into canonical task_run_contract_seed
-> TaskLifecycle creates TaskRunContract and task_run_id
-> TaskExecutor executes under task identity
```

禁止链路：

```text
user text keyword -> system decides request_task_run
assistant prose says "start task" -> system silently creates task
runtime prompt heuristic -> forced task lifecycle
ordinary tool_call -> rewritten as request_task_run
request_task_run -> agent-authored full internal TaskRunContract
```

### 5.2 各层职责

Agent：

- 判断当前目标是否需要持续任务生命周期。
- 如果选择启动，调用 `request_task_run`。
- 只填写紧凑 TaskStartIntent。
- 如果信息不足以形成启动意图，选择 `ask_user` 或在当前 turn 内处理。
- 不给自己授权工具、权限、模型、环境、memory 写入或 executor 控制权。

Provider strict schema：

- 约束控制动作的字段形状。
- 限制同一动作只表达一个控制意图。
- 让 `request_task_run` 的字段以函数参数出现，而不是让 agent 手写大 JSON。

Runtime：

- 根据当前 allowed actions 暴露控制动作。
- 解析 native control call。
- 校验字段结构、allowed action、混合动作、权限/资源边界。
- 归一化 TaskStartIntent 为 canonical `TaskRunContract + WorkModeContract`。
- 创建 task_run_id、记录事件、交给 executor。
- 不根据普通用户文本或 agent 未结构化正文自行启动任务。

Executor：

- 在 task_run_id 绑定下执行。
- 使用 task contract、task mode context、runtime boundary、tool observations 和 tail attention index。
- 更新 todo/plan/checkpoint/projection。
- 遇到暂停、停止、失败时保留可恢复状态并给用户可见收口。

### 5.3 动作一致性规则

保留但降权为结构一致性，不作为语义启动判断：

```text
如果 agent 的 public_progress_note/public_action_state 宣称已经或即将进入持续任务生命周期，
但 action_type 不是 request_task_run，
runtime 应拒绝该动作并要求 agent 重新选择一致动作。
```

这条规则的含义是：

- agent 仍然自己决定是否启动任务；
- runtime 不把普通文本改写成任务；
- runtime 只拒绝“公开反馈与结构动作不一致”的输出。

## 6. Agent-facing 契约写法

prompt 必须写成 agent 能直接执行的职责说明，不写成开发说明。

推荐核心文案：

```text
你正在为本轮选择唯一行动。

选择 request_task_run，表示你要把当前用户目标转入一条新的持续任务线。
这条任务线会拥有自己的目标、范围、进度、证据、恢复点和验收边界。

只在你已经确认以下事实时选择 request_task_run：
- 当前目标不能用一次回答或一次普通工具观察稳定收束；
- 你已经能写清这条任务线要完成什么、从哪一步开始、围绕哪些对象推进、怎样算完成；
- 后续执行需要保留同一目标下的计划、todo、证据、暂停/恢复状态或失败收口。

不要把 request_task_run 当成“我会继续处理”的表达。
不要因为用户用了“任务”“启动”“开始”“继续”等词就机械选择它。
不要在目标、第一步、范围或验收任一项不清楚时选择它。
不要用它控制已有任务；控制已有任务用 active_work_control，恢复已有工作用 resume_recoverable_work。

如果你选择 request_task_run，只提交 TaskStartIntent。
TaskStartIntent 要让后续执行立刻知道：做什么、从哪里开始、看哪些对象、避开哪些范围、怎样结束。

按下面含义填写：
- primary_mode：选择主工作形态。goal 用于达成明确目标；plan 用于按步骤推进；todo 用于维护执行清单；investigation 用于查明未知问题；recovery 用于接续失败或暂停线索；monitor 用于持续观察目标；open_work 用于确需持续推进但暂不能归入前述形态的工作。
- task_objective：写这条任务线最终要完成的目标。写可执行目标，不写启动理由。
- minimum_viable_next_step：写任务开始后的第一步。必须是可执行动作，不能写“继续处理”“进一步分析”这类空泛表述。
- working_scope：写本任务绑定的对象、路径、资料、来源、排除范围和约束。只写已知对象，不编造范围。
- acceptance：写可判断的完成条件、验收方式和最终回复要求。让后续执行知道什么时候可以结束。
- mode_payload：补充与 primary_mode 对齐的最小执行材料。plan 写步骤；todo 写事项；investigation 写待查问题；recovery 写恢复线索；monitor 写监控目标；goal/open_work 写目标摘要和必要步骤。

public_progress_note 只向用户说明你正在开启一条持续任务线；不要把它写成任务目标、计划或验收条件。
不要提交内部 TaskRunContract、WorkModeContract、工具授权、模型配置、环境策略、权限授予或 memory 规则。

无法写清 TaskStartIntent 时，选择 ask_user。
需要先取得事实再判断是否开启任务时，选择 tool_call。
当前回合可以完成时，选择 respond。
```

这段文案应放在 action schema 附近，而不是藏在长文档尾部。

## 7. TaskStartIntent v1

agent-facing `request_task_run` 参数保持紧凑：

```json
{
  "public_progress_note": "向用户说明当前目标将进入一条持续任务线",
  "public_action_state": {
    "visible_status": "thinking",
    "current_judgment": "当前目标需要新的持续任务线",
    "next_action": "提交 request_task_run",
    "evidence_refs": [],
    "open_risks": [],
    "completion_status": "working"
  },
  "primary_mode": "goal|plan|todo|investigation|recovery|monitor|open_work",
  "task_objective": "这条任务线最终要完成的具体目标",
  "minimum_viable_next_step": "任务启动后立刻执行的第一步",
  "working_scope": {
    "target_objects": [],
    "workspace_refs": [],
    "source_refs": [],
    "excluded_scope": [],
    "known_constraints": []
  },
  "acceptance": {
    "mode": "checkpoint|user_review|best_effort|strict|none_yet",
    "criteria": [],
    "final_answer_requirements": []
  },
  "mode_payload": {
    "summary": "",
    "steps": [],
    "items": [],
    "success_definition": "",
    "question": "",
    "recovery_handle": "",
    "monitor_target": "",
    "notes": []
  }
}
```

strict schema 规则：

- provider schema 要求字段完整，空数组/空字符串可用于当前不适用字段。
- `task_objective / primary_mode / minimum_viable_next_step / working_scope / acceptance` 是 runtime 创建任务容器所需的机器字段。
- `public_progress_note / public_action_state` 只服务公开反馈和动作一致性，不参与 runtime 判断是否应该启动任务。
- backend intake 允许只把这些字段归入 `task_run_contract_seed.contract_shape=compact_task_start_intent_v1`。
- backend 将其扩展为内部 canonical `container_contract / work_modes / lifecycle_contract / feedback_contract / memory_contract / acceptance_contract / runtime_requirements`。
- 内部合同字段不得作为 agent-facing 必填大骨架出现。

### 7.1 primary_mode 真实承接要求

`primary_mode` 不能只是 prompt 里的分类词。凡是暴露给 agent 的 mode，都必须有 runtime 承接。

最低承接合同：

```text
agent-facing primary_mode
-> compact TaskStartIntent mode_payload
-> model_action_protocol normalized WorkModeContract
-> TaskRunContract.work_modes primary instance
-> task_contract_manifest model-visible WorkModeContext
-> task_mode_tail_context current focus
-> Current Task Attention Index
-> executor action guidance and closeout semantics
```

已经有较强基础的 mode：

- `goal`：已有 goal contract、goal context、working_scope、acceptance 和 tail goal ref。
- `plan`：已有 plan contract、plan context、major_steps、plan baseline 和 tail plan preview。
- `todo`：已有 todo contract、todo context、todo baseline/cursor 和 agent_todo 更新通道。

需要补成一等承接的 mode：

- `investigation`：必须承接 `problem_statement/question`、已知事实、待查对象、预期裁决。tail context 要提醒 agent 当前要查明的问题和需要形成的结论。
- `recovery`：必须承接 `recovery_handle/previous_state/next_resume_step`、失败或暂停来源、可恢复边界。tail context 要提醒 agent 从哪个恢复点继续，而不是重新解释旧消息。
- `monitor`：必须承接 `monitor_target/trigger_conditions`、观察范围、触发条件和 checkpoint 输出。若还没有后台调度器，monitor 只能表示当前 TaskRun 内的有界观察任务，不能暗示无限期自动监控。
- `open_work`：必须承接 `summary/next_step/working_scope/acceptance`，作为通用持续工作线。它不是兜底垃圾桶；只有无法归入 goal/plan/todo/investigation/recovery/monitor 但仍需要 TaskRun 身份时才使用。

因此 Phase 3 不只是解析 enum，还要补齐这些 mode 的模型可见上下文和 executor 语义。任何没有真实承接的 mode 不得在 agent-facing schema 中暴露。

## 8. 缓存与执行注意力

任务启动和任务执行需要不同上下文形状。

### 8.1 stable prefix

适合缓存：

```text
global role
project instructions
stable action/control schema
stable tool catalog summary
provider tool schema hash
```

控制动作 schema 必须稳定，不能混入当前 task_run_id、当前 todo 游标或本轮动态证据。

### 8.2 request overlay

适合 per-request：

```text
当前 allowed action set
provider native tools binding
tool_choice / parallel_tool_calls
defer_loading / cache_control
```

这些字段可以每轮变，但不能修改 session-stable schema cache 本体。

### 8.3 volatile tail

适合尾部提醒：

```text
Current Runtime Boundary
latest tool observations
current task attention index
current todo cursor
current plan pointer / short preview
acceptance focus
```

`Current Task Attention Index` 只在任务已启动后的 executor 上下文中出现。它提醒 agent：

- 先看当前 task 的 `required_target_objects`；
- 文件类目标先读/验证精确路径；
- todo 变更时要更新 todo；
- plan 很长时只用尾部 preview 定位，完整步骤仍看 Task Plan Context；
- final answer 必须符合 acceptance focus。

它不是第二个合同来源，也不参与是否启动任务的判断。

## 9. 固定执行流

### 9.1 普通 chat turn 启动任务

```text
1. RuntimeCompiler 汇总当前用户输入、项目指令、工具目录、allowed actions。
2. ToolCallContract 判断本轮可暴露哪些 ordinary tools 和 control actions。
3. provider_control_action_bindings 暴露 request_task_run strict schema。
4. agent 选择一个动作。
5. 如果是 request_task_run，provider 返回 native function/tool call。
6. single_agent_turn 把 native control call 解析为 ModelActionRequest。
7. model_action_protocol 校验 compact TaskStartIntent 并归一化为 canonical seed。
8. admission 校验 action 是否允许、是否混合普通工具、是否越界。
9. task_lifecycle 从 action request 创建 TaskRunContract 和 task_run_id。
10. runtime_facade 投影 task_run_lifecycle_started。
11. task_executor 在 task_run_id 下执行。
```

本流程中系统不看“用户是不是说了启动任务”来决定启动。唯一入口是 agent 发出的结构化 `request_task_run`，或上游已经签发的显式结构化合同。

### 9.2 显式结构化合同入口

允许：

- 前端任务编辑器已保存并提交完整合同；
- workflow/graph 节点签发结构化任务合同；
- CLI `task-run start --contract-file` 提交结构化合同；
- slash task command 显式走 `request_task_run` 信号路径。

禁止：

- 普通自然语言用户输入被 runtime 自动转成显式合同。

### 9.3 任务执行 loop

```text
1. executor 读取 TaskRunContract、Task Mode Context、Task State。
2. compiler 在 volatile tail 注入 Current Task Attention Index。
3. agent 选择 task-execution action：tool_call、respond、ask_user、block、pause_for_user_steer。
4. 工具观察写入 task evidence / projection。
5. todo/plan 变化写入当前任务状态，并在下一轮 tail 反映。
6. terminal closeout 根据 acceptance 和 lifecycle contract 收口。
```

任务执行 loop 不再允许新的 `request_task_run` 控制当前 task；新任务启动与当前任务执行必须分边界处理。

## 10. 实施阶段

### Phase 0：文档锁定

目标：本文得到确认，作为后续代码落地依据。

完成条件：

- 文档明确保留 `request_task_run`。
- 文档明确禁止系统语义判断启动任务。
- 文档明确采用 provider strict control action schema。
- 文档明确缓存和 tail attention 边界。

禁止事项：

- 不在确认前继续扩大 runtime/prompt/API 修改。

### Phase 1：控制动作入口收束

目标：让 `request_task_run` 在代码和 prompt 中只表示 agent 发出的控制信号。

主要动作：

- 审查 `compiler.py`、`prompt_library/*` 中所有 `request_task_run` 文案。
- 删除或改写任何可能表达“用户说启动 -> 系统必须启动”的文本。
- 保留“公开反馈和结构动作一致”规则，但在命名和 repair 文案中标明它是 action consistency，不是 semantic trigger。
- 明确普通工具与控制动作不可混合。

完成条件：

- 搜不到用户关键词触发类逻辑。
- action schema 中 `request_task_run` 的说明只指向 agent 自己的行动选择。

### Phase 2：provider strict control action 主链路

目标：把 provider native strict control action 设为标准路径。

主要动作：

- 固化 `control_action_schema.py` 为控制动作 schema 唯一来源。
- `tool_call_contract.py` 只根据 allowed actions 暴露 control action transport，不掺入语义判断。
- `provider_tool_schema.py` 和 `lightweight_chat_model.py` 保留 per-tool strict，不用全局 strict 覆盖不同工具。
- `single_agent_turn.py` 拒绝同轮多个控制动作、普通工具与控制动作混合、非 allowed control action。
- 旧 action-object 控制动作路径不作为长期兼容链路保留；若必须为 provider 不支持场景保留，必须复用同一 compact schema adapter，且标为显式降级路径，后续清理。

完成条件：

- provider tool payload 中 `request_task_run` 是 strict function/tool。
- native control call 能进入 `ModelActionRequest`。
- 普通工具和控制动作同一轮混用会失败并给出 repair。

### Phase 3：TaskStartIntent 到内部合同归一化

目标：agent 只提交最小启动意图，runtime 生成内部合同。

主要动作：

- `model_action_protocol.py` 保持 `compact_task_start_intent_v1` 作为 agent-facing 合同。
- 为 `goal / plan / todo / investigation / recovery / monitor / open_work` 建立同等级 primary WorkModeContract 归一化入口。
- 清理旧的 full contract skeleton prompt guidance。
- `task_lifecycle.py` 继续从 normalized seed 生成 `TaskRunContract`。
- `task_contract_manifest.py` 不只输出 goal/plan/todo；必须输出所有暴露 mode 的 model-visible context 或统一的 mode-specific context。
- `task_mode_tail_context.py` 不只投影 goal/plan/todo；必须为 investigation/recovery/monitor/open_work 提供当前执行焦点。
- `compiler.py` 的 `Current Task Attention Index` 必须从所有 primary mode 读取目标、第一步、scope 和 acceptance，而不是只读 goal/plan/todo。
- repair feedback 只暴露缺失的 compact 字段和最小示例。
- 禁止 agent-facing contract 中出现系统执行授权字段：tool、skill、model、environment、permission grant、memory write policy。

完成条件：

- malformed full internal contract 不再是正常 prompt 诱导结果。
- invalid request 只要求修正 `task_objective / primary_mode / minimum_viable_next_step / working_scope / acceptance / mode_payload`。
- 每个暴露给 agent 的 primary_mode 都能在 TaskRunContract、model-visible context、tail context、attention index 和 executor closeout 中被识别。

### Phase 4：执行注意力与缓存边界

目标：让任务已启动后的执行上下文稳定聚焦，不破坏 provider cache。

主要动作：

- `compiler.py` 中 `Current Task Attention Index` 只在 task execution context 生成。
- todo cursor、active item、current target、acceptance focus 放 volatile tail。
- 长 plan 放 Task Plan Context，tail 只给 pointer/preview。
- stable tool schema catalog 和 control action schema 不混入动态 task 状态。
- 若新增缓存层，采用 session-stable schema cache + per-request overlay 结构，参照 Claude Code 的 `toolSchemaCache.ts` 思路。

完成条件：

- 当前任务目标和 todo 更新能在下一次 executor prompt 尾部出现。
- stable prefix 不因 todo 游标变化而变动。

### Phase 5：CLI 真实验证

目标：证明任务能通过 CLI 正常发动和执行。

验证前提：

- 后端使用固定端口 `127.0.0.1:8003`。
- 不切换随机端口。
- 不新增测试文件，不 mock，不硬编码输出。

建议命令：

```powershell
python -m compileall backend\harness\runtime\control_action_schema.py backend\harness\runtime\tool_call_contract.py backend\harness\runtime\provider_tool_schema.py backend\runtime\model_gateway\lightweight_chat_model.py backend\harness\loop\single_agent_turn.py backend\harness\loop\model_action_protocol.py backend\harness\loop\task_lifecycle.py backend\harness\runtime\compiler.py

python backend\run_uvicorn.py --host 127.0.0.1 --port 8003

python -m backend.cli.main --api-base http://127.0.0.1:8003/api session create --title "request_task_run smoke"

python -m backend.cli.main --api-base http://127.0.0.1:8003/api --verbose send "请在当前项目中完成一个需要持续任务生命周期的真实小任务，并在需要时用任务模式执行。"

python -m backend.cli.main --api-base http://127.0.0.1:8003/api task-run goal "检查 request_task_run 控制信号链路，给出一个可验证的 checkpoint" --no-watch
```

验收观察：

- verbose stream 能看到 `model_action_request`。
- 当 agent 自己选择启动任务时，`action_type` 为 `request_task_run`。
- `task_run_lifecycle_started` 出现并带 `task_run_id`。
- `task-run watch` 能进入 executor 或 waiting gate，而不是只停在口头回复。
- 如果 agent 不选择启动任务，runtime 不自动启动；这不是失败，除非用户使用 slash task 或结构化合同入口。

## 11. 文件级清单

| 文件 | 当前角色 | 计划动作 | 完成标准 |
| --- | --- | --- | --- |
| `backend/harness/runtime/control_action_schema.py` | 控制动作 strict schema 与 native call adapter | 固化为控制动作 schema 唯一来源；保持 `request_task_run` compact intent | schema 无内部 TaskRunContract 大骨架；metadata 标明 model_control_action |
| `backend/harness/runtime/tool_call_contract.py` | ordinary/control transport contract | 保持普通工具与控制动作分 plane；禁止语义判断混入 | allowed actions 决定暴露面，不靠用户关键词 |
| `backend/harness/runtime/provider_tool_schema.py` | provider binding schema | 保留 per-tool strict 和 stable schema catalog | control action 和 ordinary tool 都能稳定序列化 |
| `backend/runtime/model_gateway/lightweight_chat_model.py` | provider payload | 保留 per-tool strict；避免全局 strict 误伤 | provider payload 中 `function.strict` 按工具设置 |
| `backend/harness/loop/single_agent_turn.py` | model decision loop | 收束 native control parsing、repair、mixed action rejection | 单次决策只有一个控制动作；repair 指向 compact fields |
| `backend/harness/loop/model_action_protocol.py` | ModelActionRequest normalization | 保持 compact intent 到 canonical seed；清理 legacy full skeleton 诱导 | `request_task_run` 只接受 TaskStartIntent 或已规范 seed |
| `backend/harness/loop/admission.py` | action permit | 只判断 allowed action、结构、权限边界 | 不替 agent 判断是否该启动任务 |
| `backend/harness/loop/task_lifecycle.py` | TaskRunContract 创建 | 保持 runtime 生成 canonical contract | agent 不直接写内部生命周期授权 |
| `backend/harness/loop/task_executor.py` | task execution loop | 消费 TaskRunContract、todo、plan 和 attention tail | executor 不重新判断 task-start 语义 |
| `backend/harness/runtime/task_contract_manifest.py` | TaskRunContract 模型可见 manifest | 为所有暴露 primary_mode 输出可读 WorkModeContext | investigation/recovery/monitor/open_work 不再只是 raw passthrough |
| `backend/harness/runtime/dynamic_context/task_mode_tail_context.py` | Task mode tail context | 为所有暴露 primary_mode 输出当前执行焦点 | tail 能提醒对应 mode 的问题、恢复点、监控目标或通用下一步 |
| `backend/harness/runtime/compiler.py` | prompt packet/action schema/context tail | 改写 agent-facing 契约；保留 tail attention；清理语义触发措辞 | prompt 清楚说明 control signal 本质 |
| `backend/prompt_library/packs.py` | 高层 action guidance | 把“需要写入/长期跟进就 request_task_run”改成 agent 自决且 compact intent | 不再像硬规则或系统判断 |
| `backend/prompt_library/rules.py` | 全局规则 | 保留 allowed action 与字段要求 | 不出现用户关键词触发任务 |
| `backend/prompt_library/agent_prompts.py` | agent 角色 prompt | 让 agent 理解自己可发控制信号 | 不是开发说明式 prompt |
| `backend/prompt_library/utility_prompts.py` | 兜底 action 指引 | 与新契约统一 | ask/respond/block/request_task_run 的边界清楚 |
| `backend/cli/main.py` | 真实 CLI 验证入口 | 不一定改代码；用于验收 | 能通过 `send`、`task-run goal` 观察 task 启动 |
| `backend/runtime/context_management/design_docs/execution_plans/task_mode_long_running_runtime_architecture_plan.md` | 更大 Task Mode 蓝图 | 与本文术语对齐 | 不冲突、不保留旧口径 |

## 12. 迁移与清理规则

- 新主链路是 provider strict control action。
- 不保留旧 full `TaskRunContract` skeleton prompt 作为兼容入口。
- action-object fallback 不得作为长期旧链路存在；若短期保留，必须复用同一个 compact schema，并标明清理条件。
- `task_contract_seed` 等旧 alias 只可作为 intake 迁移层，不得继续出现在 agent-facing guidance。
- 清理旧测试文件或旧 prompt 断言时，不能通过删断言、mock 或硬编码制造通过；本项目按用户要求不新增回归测试文件。
- 若实现中发现需要跨更多模块或改变本文权责链，必须暂停并重新确认。

## 13. 禁止捷径

- 禁止系统用用户自然语言关键词触发 `request_task_run`。
- 禁止把 ordinary tool_call 自动改写成 `request_task_run`。
- 禁止让 agent 在普通 turn 写完整内部 `TaskRunContract`。
- 禁止在 prompt 里用开发说明代替 agent 可执行契约。
- 禁止把动态 todo/当前任务目标放进 stable provider prefix。
- 禁止保留旧链路作为“兼容兜底”长期存在。
- 禁止新增测试文件、mock 核心逻辑、降低断言或硬编码输出。

## 14. 预期结果

完成后，任务启动机制应具备这些性质：

- agent 清楚知道 `request_task_run` 是自己发出的控制信号。
- runtime 不判断语义，只接收结构信号并做边界校验。
- provider strict schema 降低 JSON 形状错误。
- 启动时只提交紧凑 TaskStartIntent，内部合同由 runtime 生成。
- task 执行阶段通过 tail attention index 关注当前目标、todo、plan 和验收。
- 缓存边界清楚：schema 稳定，动态任务焦点在尾部。
- CLI 能真实观察任务从信号到 task_run_id 再到 executor 的链路。
