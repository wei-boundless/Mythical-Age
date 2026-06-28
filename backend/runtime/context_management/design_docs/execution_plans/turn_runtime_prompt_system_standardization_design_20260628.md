# Turn 运行提示词系统标准化重构设计书

## 0. 文档状态

状态：已按本设计执行第一轮标准化落地，2026-06-28。

实施记录：

- 旧 `runtime.rule.lifecycle_control` 主链路已切断，替换为 `runtime.rule.turn_state_orientation`。
- `TurnNeuralContract` 已改为 `TurnOperatingContract`，动态尾部从 `turn_reflex` 改为 `turn_state_attention` / `turn_attention_index`。
- `lifecycle_runtime_guidance` 已收束为 `turn_state_guidance`，只表达当前 turn 状态提示，不再作为第二套生命周期控制。
- `request_task_run`、`active_work_control` 等动作名暂不改动；旧 TaskRun 执行生命周期保持切断，等待后续任务体系重做。

本文解决的是提示词系统管理问题，不是单条 prompt 去重问题。此前使用的“神经系统”只能作为比喻，用来说明 prompt、状态、动作、协议、输出之间需要形成稳定反射链路；正式架构命名必须回到实际功能：`turn`、`runtime prompt`、`action contract`、`output boundary`、`state guidance`、`protocol schema`。

本设计书的目标是把当前分散的 turn prompt、生命周期提示、动作 schema、输出边界、动态 tail 和恢复反馈整理为一套清晰、具体、全面的 `Turn 运行提示词系统`。

## 1. 问题定义

当前故障不是“同一个 prompt 是否被重复注入”，而是多条规则覆盖了相同的语义地盘：

- 决策规则在讲输出字段。
- 生命周期规则在讲动作选择、阶段判断、输出字段和展示收口。
- 输出边界规则也在讲用户可见内容。
- `turn_output_contract_payload` 又重复讲 action selection。
- 技术字段如 `public_progress_note`、`public_action_state`、`final_answer` 被写进多处 prompt prose，而不是由 schema 和输出层统一承载。

这会破坏三个系统性质：

- **权威唯一性**：agent 无法判断哪条规则才是本轮动作选择的主规则。
- **语义清晰度**：agent 读到的是开发说明和技术字段，而不是可直接执行的行为合同。
- **上下文可管理性**：稳定 prompt、动态状态、协议 metadata、provider tool schema 混在一起，缓存和压缩无法稳定控制。

正确终态：

- 一个 turn 只有一套语义决策入口。
- 一个动作只有一套协议 schema。
- 一个用户可见输出只有一套边界规则。
- 当前任务、todo、active work、恢复线索只作为 turn 的状态注意力输入，不成为第二套生命周期 prompt。

## 2. 源码依据

### 2.1 本项目现状

关键文件：

- `backend/prompt_library/rules.py`
  - `RUNTIME_TURN_DECISION_ALIGNMENT_RULE` 同时讲动作选择和 `public_action_state`。
  - `RUNTIME_LIFECYCLE_CONTROL_RULE` 同时讲阶段判断、动作选择、工具事件、`public_progress_note`、`final_answer` 和收口展示。
  - `RUNTIME_OUTPUT_BOUNDARY_RULE` 已经覆盖用户可见输出边界。
- `backend/prompt_library/packs.py`
  - `runtime.single_agent_turn`、`runtime.task_execution`、`runtime.observation_followup` 都依赖 `turn_decision_alignment` 和 `lifecycle_control`。
  - pack 里同时挂载 `output_boundary`，形成三条规则共同管输出的局面。
- `backend/harness/runtime/turn_neural_contract.py`
  - 当前文件名和类名使用 `Neural`，不够严谨。
  - `turn_action_request_contract_payload` 已承担动作选择和动作形态说明。
  - `turn_output_contract_payload` 又包含 `action_selection_rules`，使输出合同越权参与动作决策。
- `backend/harness/runtime/compiler.py`
  - `lifecycle_runtime_guidance` 仍作为 model-visible system text 注入。
  - `model_action_request_schema` 和输出合同仍在 prompt 文本中暴露大量字段规则。
- `backend/harness/runtime/control_action_schema.py`
  - provider strict control action schema 是正确方向，但字段语义仍和 prompt prose 重叠。
- `backend/harness/loop/single_agent_turn.py`
  - repair prompt 中仍多处直接讲字段补写，应该保留为局部协议反馈，不能上升为全局 prompt doctrine。
- `backend/harness/runtime/dynamic_context/turn_reflex_tail_context.py`
  - 名称仍使用 `reflex` 比喻。实际功能是当前 turn 的状态注意力尾部索引。

### 2.2 原始 Turn Prompt 与生命周期提示词冲突审计

本次重构必须先承认一个事实：冲突不是 `RUNTIME_TURN_DECISION_ALIGNMENT_RULE` 和 `RUNTIME_LIFECYCLE_CONTROL_RULE` 两条规则之间的局部重复，而是原始 turn prompt、生命周期 prompt、运行合同 payload、compiler 动态注入和 repair 文案共同覆盖了同一组语义权威。

| 来源 | 当前实际内容 | 冲突对象 | 问题性质 | 目标归属 |
|---|---|---|---|---|
| `RUNTIME_SINGLE_AGENT_TURN_PROMPT` | 讲行动裁决、合法动作、字段和 JSON 形态、`public_action_state`、工具前后公开反馈、最终收口 | `turn_decision_alignment`、`output_boundary`、`turn_action_request_contract_payload` | invocation prompt 越权讲字段协议和输出边界 | 只保留“本轮会话行动定位”，字段协议迁入 schema/Action Protocol，公开输出迁入 Output Boundary |
| `RUNTIME_TASK_EXECUTION_PROMPT` | 讲任务合同、工具执行、文件写入策略、`public_progress_note`、`public_action_state`、`final_answer` | 任务合同、工具规则、输出边界、生命周期环境提示 | 任务执行 prompt 混合角色定位、工具策略、输出协议和持续任务生命周期 | 暂时隔离为旧任务入口；后续任务体系重做时拆为 task contract、tool guidance、output guidance |
| `RUNTIME_OBSERVATION_FOLLOWUP_PROMPT` | 讲观察后重新判断、何时 `request_task_run`、何时 `active_work_control`、如何写公开判断 | decision rule、lifecycle runtime guidance、repair feedback | 观察跟进 prompt 同时做动作选择和展示收口 | 只保留“观察是事实输入，重新裁决下一步”；字段和展示规则外移 |
| `RUNTIME_TURN_DECISION_ALIGNMENT_RULE` | 讲动作选择，同时讲公开进展、`public_action_state.current_judgment` | output boundary、single turn prompt、operating contract | 决策层借用了输出层权威 | 只选择动作，不解释 public fields |
| `RUNTIME_LIFECYCLE_CONTROL_RULE` | 讲生命周期阶段、动作推进、todo、工具事件、`public_progress_note`、`final_answer`、closeout | decision rule、output boundary、dynamic tail | 用“生命周期控制”覆盖 turn 决策、状态注意力和输出边界 | 删除旧规则，替换为 `turn_state_orientation` |
| `environment.*.lifecycle.action_selection` | 按 coding/office/general 分环境再讲一次动作选择骨架 | runtime decision rule、runtime pack prompt | 环境提示词拥有第二套动作决策入口 | 改为环境能力/工作形态 guidance；动作选择由统一 decision rule 承担 |
| `environment.*.lifecycle.finalization` | 分环境解释最终回复、验证、风险、能力不足和内部字段禁止 | output boundary、runtime output contract | 输出边界按环境重复定义 | 迁为 environment-specific output guidance，只补充领域验收重点，不重写全局 output boundary |
| `turn_action_request_contract_payload` | 在协议 payload 中写 `turn_reflex.selection`、字段用途、forbidden 和 `request_task_run` 示例 | prompt rules、control action schema、output contract | schema/contract 对象携带大段 agent-facing prompt prose | 结构字段和不可变短契约留在核心模块；可变/领域化解释迁入 prompt library |
| `turn_output_contract_payload` | 在 output contract 里写 `action_selection_rules` 和 action protocol 行为说明 | decision rule、system call protocol | 输出合同反向参与动作选择 | output contract 只表达输出提交边界和提交格式；动作选择移除 |
| compiler `lifecycle_runtime_guidance` | 根据当前状态动态选择 lifecycle prompt 并作为 system text 注入 | dynamic tail、turn_state_orientation、environment prompt set | compiler 拥有一条不经过统一 slot 计划的动态提示词总线 | 改为 `turn_state_guidance` / `turn_attention_index`，由 wiring plan 决定 slot |
| `single_agent_turn.py` repair 文案 | 针对缺字段、非法动作、污染 final answer 给出修复提示 | 全局 rules、output boundary | repair 文案可保留，但不能上升为全局 doctrine | 只作为局部协议反馈，指向本次非法动作和当前 schema |

结论：

- 原始 turn prompt 需要精简，不应再承担字段说明、生命周期控制和输出收口。
- 生命周期提示词不应作为横跨所有 turn 的第二控制系统；其中可保留的内容要按功能拆入环境 guidance、工具 guidance、恢复 feedback、输出领域补充和动态状态注意力。
- `turn_operating_contract` 应成为结构化运行合同。不可变核心契约、schema、字段语义、提交边界和 provider 严格 tool/function calling 定义可以直接保留在代码中，因为它们不是 agent 可配置资源。
- 需要迁入 prompt library 的不是所有字符串，而是会随 agent、环境、任务形态、工作角色、工具域或项目策略变化的 agent-facing prose。不可变核心契约可以留在代码中，但必须集中封装、命名稳定、只出现一次，并通过 manifest/slot 暴露其 authority，而不是散落在 compiler、repair、pack 和环境 lifecycle prompt 中重复解释。

### 2.3 外部成熟 agent 参考

只抽取结构性原则，不复制命名。

- OpenAI Codex 源码中，`codex-rs/core/src/state/mod.rs` 明确拆出 `SessionState`、`ActiveTurn`、`TurnState`、`RunningTask`。
- OpenAI Codex `codex-rs/core/src/state/turn.rs` 把 pending approvals、pending permissions、pending user input、dynamic tools、mailbox phase、tool calls 都收在 turn-scoped state 中，说明“任务/工具/审批/输入等待”是 turn 状态，而不是模型的第二套提示词生命周期。
- Claude Code 源码研究文档 `03-状态管理.md` 把状态分为 Session 全局、AppState Store、ToolUseContext，并强调“向下依赖，向上隔离”。这对应本项目应采用的原则：状态层提供事实和句柄，不能反向替 prompt 决策。

外部参考带来的设计原则：

- Session、turn、tool context 必须分层。
- 任务和工具执行是运行资源或状态对象，不应变成 prompt 层第二套生命周期。
- prompt 可以约束模型行为，但 technical protocol 应优先由 schema、metadata、state object 承载。

## 3. 设计原则

### 3.1 命名原则

不为了“听起来先进”改名，只在职责改变或原名误导时改名。

保留名称的条件：

- 名称准确描述当前职责。
- 已被多个调用点引用，且职责不变。
- 改名只会带来迁移噪声。

必须改名的条件：

- 名称使用比喻，不能表达可维护职责。
- 名称让 agent 或开发者误以为该层拥有不属于它的权威。
- 名称绑定了旧任务生命周期，而目标设计已经切断旧任务体系。

### 3.2 Prompt 规则原则

写给 agent 的 prompt 必须能被 agent 直接执行。它要说明“你是谁、你此刻负责什么、你不能做什么、你如何裁决”，不能写成开发说明。

Prompt 规则必须分层：

- 决策层只讲怎么选本轮动作。
- 输出层只讲用户可见内容边界。
- 状态层只提供当前事实、游标、风险、恢复点和注意力索引。
- 协议层只定义字段、schema、required paths、provider strict tool calling。
- 恢复层只反馈本次动作哪里不合法，不重新解释用户意图。

### 3.3 Context 和缓存原则

稳定身份、长期规则、工具目录、项目约束进入稳定前缀。

当前用户输入、active work、todo cursor、恢复线索、观察结果、当前文件证据进入动态尾部。

技术 metadata 应进入 `context_fragment` metadata 或 provider schema，不作为自然语言 prompt 重复出现。

### 3.4 不可变核心契约原则

不是所有模型可见内容都应该进入 prompt library。Prompt library 管理的是可组合、可替换、可按 agent/environment/task 绑定的提示词资源；不可变核心契约属于 runtime control plane，可以直接放在代码中集中维护。

允许保留在代码中的内容：

- provider strict tool/function calling schema。
- action object 字段定义、required paths、字段类型和解析规则。
- output commit 的结构化边界。
- action surface、tool transport、permission/admission 的不可变协议描述。
- context fragment metadata、manifest、diagnostics、authority id。

不应保留在 runtime 代码中散落书写的内容：

- agent 工作角色说明。
- 环境差异化行动准则。
- 任务形态、工具域、项目策略、写作/办公/coding 等领域判断标准。
- 可由不同 agent 覆盖或扩展的行为提示。
- 与 prompt library 中已有规则重复的长段自然语言说明。

核心契约留在代码中的条件：

- 只有一个权威生成点。
- 不通过自然语言重复覆盖 prompt library 的职责。
- 以 locked slot 或 manifest 的形式暴露给 prompt assembly 和运行诊断。
- 文案尽量短，服务于协议理解，不承担 agent 角色训练或环境策略。
- 不能被 agent prompt、environment prompt 或项目 prompt 覆盖。

## 4. 目标分层

### 4.1 Turn Prompt Layer

职责：给 agent 一个清晰的当前 turn 行为定位。

保留：

- `runtime.single_agent_turn`
- `runtime.task_execution`，但后续任务体系重做前不得继续强化第二套生命周期。
- `runtime.observation_followup`

调整：

- 这些 runtime prompt 只描述 invocation 角色和当前输入输出关系。
- 不再重复列字段 schema。
- 不再用“生命周期”解释普通 turn。

### 4.2 Turn Decision Layer

职责：唯一负责“本轮语义上选择哪个动作”。

保留并重写：

- `runtime.rule.turn_decision_alignment`

目标内容：

```text
你负责根据当前用户话语、可见上下文和本轮动作边界，选择一个最小充分动作。
如果当前事实足以回应，选择 respond。
如果缺少用户决策，选择 ask_user。
如果需要观察、读取、执行或验证，选择 tool_call。
如果需要系统分配长任务运行资源来保存跨 turn 状态，选择 request_task_run。
如果当前 turn 已绑定可控工作且用户正在控制它，选择 active_work_control。
如果合法路径不足以继续，选择 block。
```

禁止内容：

- 不写 `final_answer` 字段规则。
- 不写 `public_progress_note` 字段规则。
- 不写 JSON 示例。
- 不写生命周期阶段枚举。

### 4.3 Turn State Guidance Layer

职责：告诉 agent 当前 turn 应关注哪些状态事实。

新 canonical 名称：

- `runtime.rule.turn_state_orientation`

替换旧名：

- `runtime.rule.lifecycle_control`

改名原因：

- 旧名 `lifecycle_control` 暗示这条 prompt 拥有生命周期控制权。
- 目标职责不是控制生命周期，而是把当前任务、todo、观察、恢复、active work 和收口状态整理成注意力方向。

目标内容：

```text
你会看到当前 turn 的状态提示。
这些状态只帮助你定位当前目标、计划游标、todo 游标、恢复线索、active work 和验收边界。
它们不能替你决定用户意图，也不能覆盖用户最新话语。
如果状态和用户最新话语冲突，先回应用户最新话语，并按本轮动作边界选择动作。
```

禁止内容：

- 不定义动作字段。
- 不讲最终回答格式。
- 不判断“任务生命周期阶段”。
- 不把 todo 写成任务模式。

### 4.4 Action Protocol Layer

职责：定义动作传输和字段 schema。

保留：

- `backend/harness/runtime/control_action_schema.py`
- `backend/harness/runtime/tool_call_contract.py`
- `ModelActionRequest`

调整：

- provider strict tool/function calling 是控制动作 schema 的主承载。
- `request_task_run`、`active_work_control`、`resume_recoverable_work` 的字段要求由 schema 表达。
- prompt 只说明“选择哪个动作”，不反复讲字段路径。

命名建议：

- `TurnActionSurface`：保留。它描述本轮可行动作面，准确。
- `TurnActionTransport`：保留。它描述动作提交通道，准确。
- `TurnActionRequest`：作为目标概念使用；现有 `ModelActionRequest` 可保留到实现阶段评估，不为追求统一而强行改。

### 4.5 Output Boundary Layer

职责：唯一负责用户可见内容边界。

保留并强化：

- `runtime.rule.output_boundary`
- `harness.runtime.output_boundary`
- `public_stream_compiler.py`

目标内容：

- `final_answer` 是最终可见收口正文。
- `user_question` 是需要用户回答的问题。
- `blocking_reason` 是无法继续的真实阻塞。
- `public_progress_note` 是非终止动作前的公开短判断。
- `public_action_state` 是结构化公开状态，不是用户正文。

禁止其他层再解释这些字段用途。

### 4.6 Recovery Feedback Layer

职责：只处理本次动作不合法或失败后的局部修正。

保留：

- `single_agent_turn.py` 中的 repair observation。
- `runtime.rule.error_recovery`。

调整：

- repair 可以说“respond 缺少 final_answer”，因为这是局部协议反馈。
- repair 不能重新定义全局 prompt 规则。
- recovery 不能替 agent 改写用户意图，不能 silent fallback 到 `open_work`。

### 4.7 Prompt Assembly And Cache Layer

职责：决定 prompt 资源如何装配、缓存、压缩和投影。

保留：

- `PromptAssemblyService`
- `context_fragment`
- `context_capability_policy`

调整：

- 规则资源要按 layer 分类，并通过 metadata 声明 owner。
- `lifecycle_runtime_guidance` 不再作为大段 prompt text 注入。
- 当前状态提示改为 `turn_state_guidance` 或 `current_turn_state_guidance`，并尽量以结构化 `context_fragment` payload 承载。

## 5. 命名决策

### 5.1 保留

- `runtime.rule.turn_decision_alignment`
  - 真实职责仍是动作选择对齐。
- `runtime.rule.output_boundary`
  - 真实职责仍是输出边界。
- `TurnActionSurface`
  - 真实职责是动作面。
- `TurnActionTransport`
  - 真实职责是动作提交通道。
- `public_progress_note`
  - 字段名准确表示公开进展短说明。
- `public_action_state`
  - 字段名准确表示公开动作状态。
- `final_answer`
  - 字段名准确表示最终回答。

### 5.2 改名或替换

- `RUNTIME_LIFECYCLE_CONTROL_RULE`
  - 替换为 `RUNTIME_TURN_STATE_ORIENTATION_RULE`。
  - prompt id 从 `runtime.rule.lifecycle_control` 替换为 `runtime.rule.turn_state_orientation`。
  - 不保留旧规则作为兼容 prompt；完成迁移后删除旧资源引用。
- `turn_neural_contract.py`
  - 替换为 `turn_operating_contract.py`。
  - class 从 `TurnNeuralContract` 替换为 `TurnOperatingContract`。
  - 原因：该对象实际是 turn 的运行合同，不是“神经”对象。
- `turn_reflex_tail_context.py`
  - 替换为 `turn_state_attention_context.py`。
  - 原因：该模块实际生成当前 turn 状态注意力尾部，不应继续使用比喻命名。
- `turn_reflex_index`
  - 替换为 `turn_attention_index`。
  - 原因：index 的功能是提醒 agent 当前关注目标、计划、todo、验收和恢复线索。
- `lifecycle_runtime_guidance`
  - 替换为 `turn_state_guidance`。
  - 原因：该片段不再控制生命周期，只提供当前 turn 状态提示。

### 5.3 不在本次设计中改动

- `task_run`
- `request_task_run`
- `active_work_control`
- `resume_recoverable_work`

原因：这些是动作或资源概念，用户已经明确认可 `request_task_run` 方向；后续任务体系重做时再处理 TaskRun 内部模型。

## 6. 固定执行流

```text
User Input
-> Request Facts
-> Runtime State Projection
-> Turn Prompt Assembly
-> Turn Decision Rule
-> Action Protocol Schema
-> Model Action
-> Action Admission
-> Execution / Tool / Control
-> Observation Or Terminal
-> Output Boundary
-> State Commit
```

| 阶段 | 输入 | 输出 | 拥有者 | 禁止事项 |
|---|---|---|---|---|
| Request Facts | 用户话语、附件、session refs | 当前 turn fact payload | request/runtime facts | 不判断用户意图 |
| Runtime State Projection | active work、todo、恢复、观察 | turn state guidance / attention index | dynamic context | 不选择动作 |
| Prompt Assembly | stable rules、state guidance、工具面 | model messages | compiler / prompt assembly | 不把 schema 写成重复 prompt |
| Turn Decision | 用户话语、上下文、动作面 | 语义动作选择 | model under decision rule | 不写协议字段说明 |
| Action Protocol | allowed actions、provider tools | strict schema / action object | schema layer | 不判断该不该做 |
| Admission | action request、权限、工具、资源 | permit / denial / repair | runtime admission | 不重写用户语义 |
| Execution | permit、工具、控制动作 | observation / terminal | execution loop | 不生成第二套模型生命周期 |
| Output Boundary | final/progress/question/block candidate | canonical public output | output layer | 不暴露内部字段 |
| State Commit | observation、terminal、refs | session/task/turn state update | state layer | 不抢占用户正文 |

## 7. 模块改造计划

### 7.1 `backend/prompt_library/rules.py`

动作：

- 重写 `RUNTIME_TURN_DECISION_ALIGNMENT_RULE`，只保留动作选择语义。
- 删除 `RUNTIME_LIFECYCLE_CONTROL_RULE`。
- 新增 `RUNTIME_TURN_STATE_ORIENTATION_RULE`。
- 保持 `RUNTIME_OUTPUT_BOUNDARY_RULE` 为用户可见输出唯一规则，并补足 public fields 的边界描述。

完成标准：

- decision rule 不出现 `public_progress_note`、`public_action_state`、`final_answer`。
- state orientation rule 不出现 JSON 字段 schema。
- output boundary rule 是唯一解释 public/final/question/blocking 字段用途的全局规则。

### 7.2 `backend/prompt_library/packs.py`

动作：

- 把所有 `runtime.rule.lifecycle_control` 引用替换为 `runtime.rule.turn_state_orientation`。
- `runtime.single_agent_turn` prompt 保留角色说明，但删掉字段级协议重复。
- `runtime.observation_followup` 保留观察后重新裁决，但不讲任务生命周期。
- `runtime.task_execution` 暂时保留，但标明它是旧任务体系重做前的隔离入口，不能影响普通 turn。

完成标准：

- pack 中不再挂载 `lifecycle_control`。
- single turn、observation followup、task execution 的 prompt 层级清晰。

### 7.3 `backend/harness/runtime/turn_neural_contract.py`

动作：

- 文件改为 `turn_operating_contract.py`。
- `TurnNeuralContract` 改为 `TurnOperatingContract`。
- `turn_action_request_contract_payload` 只保留动作选择和动作面说明。
- `turn_output_contract_payload` 移除 `action_selection_rules`，只保留输出提交和公开反馈边界。
- `turn_reflex_index_payload` 改为 `turn_attention_index_payload`。

完成标准：

- operating contract 不再使用 `neural` 命名。
- action contract 和 output contract 不互相讲对方职责。

### 7.4 `backend/harness/runtime/compiler.py`

动作：

- 更新 import 和调用点。
- `lifecycle_runtime_guidance` 改为 `turn_state_guidance`。
- 将字段级协议从 model-visible prose 中移到 schema payload 或 context metadata。
- 保留必要的 agent-facing短句，但不重复 schema。

完成标准：

- compiler 只装配分层后的 prompt 和 context。
- volatile tail 只包含当前 turn 状态，不包含旧生命周期大段提示。

### 7.5 `backend/harness/runtime/control_action_schema.py`

动作：

- 作为控制动作字段和 strict schema 的主承载。
- `request_task_run` schema 只表达系统需要解析的字段。
- 不从 prompt prose 继承旧 `entry_reason`、旧 mode fallback 或生命周期措辞。

完成标准：

- 控制动作字段要求可由 schema 单独说明。
- prompt 不再复制 schema 字段表。

### 7.6 `backend/harness/runtime/dynamic_context`

动作：

- `turn_reflex_tail_context.py` 改为 `turn_state_attention_context.py`。
- 输出 `turn_attention_index`，包含 current goal、plan cursor、todo cursor、scope、acceptance、recovery handles、active work boundary。
- todo 明确作为 cursor/tool，不作为 mode。

完成标准：

- 当前任务/todo 信息位于尾部状态注意力索引。
- 长 plan 可在上下文主体，当前 todo cursor 在尾部提醒。

### 7.7 `backend/harness/loop/single_agent_turn.py`

动作：

- 全局 repair 文案不再引用 lifecycle doctrine。
- 局部协议错误仍可明确指出缺少哪个字段。
- `request_task_run` 继续保持任务体系切断状态，直到任务体系重做。

完成标准：

- repair 只修本次动作，不重塑全局 prompt。
- 没有旧生命周期语义从 repair 回灌到 prompt 系统。

## 8. 分阶段实施计划

### Phase 1：规则分层和命名切换

目标：先让 prompt 资源层权威清晰。

文件：

- `backend/prompt_library/rules.py`
- `backend/prompt_library/packs.py`
- `backend/prompt_library/migrations.py`

完成标准：

- `runtime.rule.lifecycle_control` 不再被 pack 使用。
- 新规则 `runtime.rule.turn_state_orientation` 成为状态注意力规则。
- `turn_decision_alignment`、`output_boundary`、`turn_state_orientation` 三者无字段和职责重叠。

禁止：

- 不改任务体系执行语义。
- 不为了通过编译保留旧 lifecycle prompt 双挂载。

### Phase 2：Turn operating contract 改名和职责拆分

目标：移除 `neural` 比喻命名，并拆开 action/output 合同。

文件：

- `backend/harness/runtime/turn_neural_contract.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/control_action_schema.py`

完成标准：

- `TurnOperatingContract` 成为唯一 turn 运行合同对象。
- action selection 不再出现在 output contract。
- 字段 schema 不再作为多处 prompt prose 重复。

禁止：

- 不改 `request_task_run` 这个动作名。
- 不把 schema 逻辑塞回 prompt 文本。

### Phase 3：动态尾部和缓存治理

目标：把当前任务/todo/恢复线索接到 turn 状态注意力尾部。

文件：

- `backend/harness/runtime/dynamic_context/turn_reflex_tail_context.py`
- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/harness/runtime/compiler.py`
- `backend/runtime/context_management/context_capability_policy.py`
- `backend/runtime/context_management/context_segment_policy.py`

完成标准：

- `turn_attention_index` 位于 volatile tail。
- 长 plan 可以在上下文主体，todo cursor 和当前关注点在尾部。
- `turn_state_guidance` 是结构化当前状态提示，不是旧生命周期 prompt。

禁止：

- 不把 todo 升级为 primary mode。
- 不让动态 tail 替 agent 决定用户语义。

### Phase 4：恢复反馈收束

目标：让 recovery 只做局部修正，不再携带旧生命周期教义。

文件：

- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/model_action_protocol.py`
- `backend/harness/loop/admission.py`

完成标准：

- unsupported mode 不 silent fallback。
- repair prompt 只指向本次非法动作和本轮 schema。
- admission 返回资源/权限/边界问题，不用旧任务生命周期语言。

禁止：

- 不让系统替 agent 判断语义。
- 不通过 fallback 把错误合同改成 open_work。

### Phase 5：清理旧残留和验证

目标：删除旧 lifecycle prompt 路径，不保留双轨。

文件：

- 全局 `rg "lifecycle_control|lifecycle_runtime_guidance|TurnNeural|turn_reflex"`
- 相关 import、manifest、docs 引用

完成标准：

- 普通 turn prompt 系统只剩功能命名。
- 旧生命周期 prompt 资源不可达。
- CLI 和真实运行链路可启动。

## 9. 验证策略

不新增回归测试文件。按项目要求使用静态审查、编译和真实 CLI/运行链路验证。

必须验证：

- `python -m compileall backend\prompt_library backend\harness\runtime backend\harness\loop backend\runtime\context_management`
- `rg "runtime.rule.lifecycle_control|RUNTIME_LIFECYCLE_CONTROL_RULE|lifecycle_runtime_guidance|TurnNeuralContract|turn_reflex" backend` 确认旧链路清理。
- CLI 单 turn 能正常启动。
- CLI `request_task_run` 路径仍返回当前已切断的任务系统 receipt，不重启旧 TaskRun 执行器。
- 如果涉及前后端运行链路，固定端口启动：
  - backend `http://127.0.0.1:8003`
  - frontend `http://127.0.0.1:3000`

## 10. 禁止的捷径

- 不把 `lifecycle_control` 改短一点继续保留。
- 不把字段 schema 同时写在 prompt、schema、repair、output contract 四处。
- 不用“兼容”理由保留旧 lifecycle prompt 双轨。
- 不把“神经系统”作为正式代码命名。
- 不让系统根据自然语言猜是否启动任务。
- 不把 todo 当任务模式。
- 不在 output contract 里重新定义 action selection。
- 不在 recovery 中 silent fallback 或改写 agent 原始语义。

## 11. 预期结果

完成后，agent 读到的 turn prompt 将变成一套稳定的运行合同：

- 它知道自己在当前 turn 中行动。
- 它只从一条决策规则选择动作。
- 它只从一条输出规则理解用户可见边界。
- 它通过 strict schema 提交控制动作。
- 它从尾部状态索引关注当前任务、todo、恢复和验收。
- 它不会把任务资源看成第二套模型生命周期。

工程上，prompt 系统会从“多条规则互相提醒”变成“分层权威链路”：

```text
Turn Prompt
-> Turn State Orientation
-> Turn Decision Alignment
-> Action Protocol Schema
-> Admission / Execution
-> Output Boundary
-> State Commit
```

这才是可维护的标准化系统；“神经系统”只是对这条链路的形象描述，不进入正式命名。
