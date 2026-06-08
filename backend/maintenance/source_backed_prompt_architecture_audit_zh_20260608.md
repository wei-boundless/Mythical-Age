# 基于本地源码的 Prompt 架构审查与重构计划 - 2026-06-08

## 1. 文档目的

这份文档是 `source_backed_prompt_architecture_audit_20260608.md` 的中文版，用于记录本轮基于本地 Codex / Claude Code 源码的 prompt/runtime 架构对照、现有系统细节审查和后续重构蓝图。

本轮目标不是单纯打磨 prompt 文案，而是把 prompt 系统升级成成熟 agent 应有的控制架构：

- 大模型负责理解用户当前请求、判断下一步、调度动作和收口；
- 系统负责提供环境、权限、工具、记忆、当前工作和执行观察；
- prompt 装配必须有明确优先级；
- 生命周期 prompt 必须按当前状态触发，而不是全部常驻；
- 记忆、压缩摘要、历史任务和工具噪声不能覆盖用户最新请求；
- 子 agent 只能提供证据和局部结论，主 agent 负责最终判断。

这份审查基于本地源码，不基于泛泛的外部文章或经验判断。

## 2. 本地参考源码

### 2.1 Codex 本地源码

参考文件：

- `D:/AI应用/openai-codex/codex-rs/protocol/src/prompts/base_instructions/default.md`
- `D:/AI应用/openai-codex/codex-rs/core/templates/model_instructions/gpt-5.2-codex_instructions_template.md`
- `D:/AI应用/openai-codex/codex-rs/core/templates/compact/prompt.md`
- `D:/AI应用/openai-codex/codex-rs/ext/memories/src/prompts.rs`

可借鉴点：

- Codex 的基础 prompt 是稳定的 agent 宪法，包含身份、能力、仓库指令、计划、执行、验证、最终回复等部分。
- 它不会把 prompt 写成“你是请求判断层”“你是 runtime 节点”这种开发描述。
- 压缩 prompt 非常克制，只要求生成恢复点摘要，不承担普通对话或任务执行。
- 记忆读取路径是专门注入的 developer instruction，不混在每个环境 prompt 里。

### 2.2 Claude Code 本地源码

参考文件：

- `D:/AI应用/claude-code-nb-main/utils/systemPrompt.ts`
- `D:/AI应用/claude-code-nb-main/tools/AgentTool/prompt.ts`
- `D:/AI应用/claude-code-nb-main/tools/TaskCreateTool/prompt.ts`
- `D:/AI应用/claude-code-nb-main/memdir/teamMemPrompts.ts`

可借鉴点：

- Claude Code 有明确的 system prompt 优先级：`override > coordinator > agent > custom > default`，append prompt 只在最后追加。
- fresh subagent 不继承完整上下文，父 agent 必须像给刚进房间的聪明同事交代任务一样写 brief。
- 父 agent 不能把理解外包给子 agent，不能写“基于你的发现你来修 bug”这种 prompt。
- 子 agent 未返回前，主 agent 不能预测、编造或提前引用子 agent 结论。
- memory、plan、task 是三种不同持久化机制，不能混用。

## 3. 成熟架构不变式

### 3.1 稳定宪法优先

基础 prompt 应该先定义 agent 的身份、协作方式、指令优先级、计划方式、执行方式、验证标准和最终回复边界。

它不应该写成开发说明，例如：

```text
你是当前会话主 agent 的请求判断层。
```

更成熟的写法应该直接让模型理解当下身份和职责，例如：

```text
你是当前会话的主 agent。
你负责理解用户最新请求，结合本轮可见环境和工具边界，选择一个可执行、可验证、可收口的下一步。
```

### 3.2 Prompt 来源必须有优先级

不同 prompt 来源不能只靠数组顺序拼接。成熟装配应明确：

```text
override
-> coordinator / mode
-> agent role
-> runtime base / action protocol
-> environment boundary
-> lifecycle state fragments
-> tool guidance
-> skill guidance
-> project / user append instructions
```

如果没有这层优先级，后续 mode prompt、agent prompt、environment prompt、lifecycle prompt 和 tool prompt 很容易互相覆盖或重复。

### 3.3 生命周期 prompt 应按状态触发

不是每轮都需要全部生命周期 prompt。

应该按状态选择：

- 有 `active_work_context` 时，才挂 active-work control prompt；
- 有工具观察或 followup 时，才挂 tool-observation recovery prompt；
- 有 memory context、memory maintenance 或 compaction 时，才挂 memory handoff prompt；
- 允许进入 task run 时，才挂 task-run handoff prompt；
- 普通直接回答不应该看到过多长期任务、记忆写入或当前工作控制说明。

### 3.4 工具 prompt 应负责工具契约

工具 prompt 应说明：

- 什么时候用；
- 什么时候不用；
- 输入参数边界；
- 失败、拒绝、超时、省略输出如何处理；
- 工具结果对模型意味着什么。

runtime protocol 不应该重复每一个工具的细节。

### 3.5 主 agent 保持最终裁决权

子 agent 负责局部搜索、验证、资料阅读、证据整理。

主 agent 负责：

- 综合子 agent 返回；
- 判断哪些证据可信；
- 决定是否继续读取、实现、验证或收口；
- 给用户最终答复。

子 agent 的结果不能自动升级成最终答案。

### 3.6 记忆不是当前事实

记忆只能提供候选背景。

当前事实优先级应是：

```text
用户最新明确要求
-> 系统最新工具观察
-> 当前可见文件/运行结果
-> active_work_context / task_state
-> session summary / compaction
-> durable memory
```

长期记忆不能证明当前文件仍然存在，也不能证明测试已经通过。

### 3.7 不应让模型输出自评分 confidence

成熟 agent 不应依赖模型自己输出一个数字或 high/medium/low 来代表判断可信度。

应该改成：

- `evidence_refs`
- `limitations`
- `open_questions`
- `verification_status`
- `source_strength`
- `parse_quality`
- `retrieval_score`

其中 `source_strength`、`parse_quality`、`retrieval_score` 必须来自证据或系统计算，而不是模型自评。

## 4. 当前系统生命周期

当前 chat turn 大致路径：

```text
api.chat.ChatRequest
-> _query_request_from_payload()
-> HarnessRuntimeFacade.astream()
-> assemble_runtime()
-> active/current work candidate lookup
-> turn_input_facts
-> session_emphasis
-> runtime memory context
-> runtime_branch projection
-> _run_single_agent_turn()
-> run_single_agent_turn()
-> RuntimeCompiler.compile_single_agent_turn_packet()
-> model invocation
-> action parsing / protocol repair
-> tool execution or control action
-> tool observation followup or final answer
-> memory maintenance after commit
```

关键文件：

- `backend/api/chat.py`
  - 接收前端请求，严格禁止额外字段。
  - 合并 VSCode editor context 和 session project binding。
- `backend/harness/entrypoint/runtime_facade.py`
  - 组装 runtime assembly。
  - 查找 active work、latest resumable work、recent outcome。
  - 构造 turn input facts 和 memory context。
  - 决定 single-agent turn 或 task lifecycle。
- `backend/harness/runtime/assembly.py`
  - 解析 runtime profile、task environment、prompt refs、工具可见性和 operation authorization。
- `backend/harness/runtime/compiler.py`
  - 构造 model messages、stable payload、dynamic payload、output contract、prompt manifest。
- `backend/harness/loop/single_agent_turn.py`
  - 调用模型、解析 action、修复协议错误、执行工具和输出最终事件。
- `backend/harness/loop/active_work.py`
  - 校验 active work 控制动作和 `relation_to_current_work`。
- `backend/memory_system/runtime_context_provider.py`
  - 构造模型可见 memory context。
- `backend/memory_system/maintenance.py`
  - 在提交后运行记忆维护 agent，生成记忆写入候选。

## 5. 当前责任图

| 层级 | 当前 owner | 合法职责 | 风险点 | 目标动作 |
| --- | --- | --- | --- | --- |
| API | `backend/api/chat.py` | 校验请求、绑定编辑器项目 | 不应判断用户意图 | 保持严格，不加入 prompt 逻辑 |
| Runtime facade | `backend/harness/entrypoint/runtime_facade.py` | 装配环境、active work、memory、branch | latest task 可能被误看作 current work | 用 turn facts 明确区分 active / resumable / recent outcome |
| Assembly | `backend/harness/runtime/assembly.py` | 解析 profile、environment、tools、prompt refs | environment prompt refs 全量复制 | 增加 lifecycle selector |
| Prompt assembly | `backend/prompt_library/assembly.py` | 解析 pack/resource 并校验 scope | 没有显式优先级 | 增加 PromptAssemblyPolicy |
| Environment | `backend/task_system/environments/default_environments.py` | 定义资源边界 | 挂载全部 lifecycle prompt | 只保留环境边界，移走状态 prompt |
| Runtime protocol | `backend/prompt_library/packs.py` | 定义 action schema 和输出协议 | 和 lifecycle prompt 重复 | 保留协议，移走判断文案 |
| Lifecycle prompts | `backend/prompt_library/general_lifecycle_prompts.py` | 指导当前 turn 判断 | 文案方向对，但挂载粒度不对 | 改为按状态挂载 |
| Tool guidance | `backend/prompt_library/tool_prompts.py` | 说明工具契约 | 需要纳入 assembly diagnostics | 保留并强化 |
| Subagent tools | `backend/capability_system/tools/tool_units/subagent_control_tool.py` | 子 agent 生命周期 | 已有 fresh specialist / no prediction，但还不够 | 补 never delegate understanding |
| Worker prompts | `backend/prompt_library/worker_prompts.py` | 专家角色 prompt | 还要求 confidence | 改成证据质量和限制 |
| Memory manager | `backend/prompt_library/agent_prompts.py` | 记忆候选维护 | 需要更清晰区分 memory/plan/task | 保留并强化 |
| Durable recall | `backend/memory_system/durable.py` | 选择相关长期记忆 | 仍要求模型输出 confidence | 改成 reason / verification |
| Compiler | `backend/harness/runtime/compiler.py` | 最终 model packet 装配 | 没有 lifecycle selector | 加选择层 |
| Single turn loop | `backend/harness/loop/single_agent_turn.py` | 执行动作、恢复协议 | active_work native payload 仍保留 confidence | 删除或拒绝 |

## 6. 细节问题清单

### P0. General lifecycle prompt 全部常驻

证据：

- `backend/task_system/environments/default_environments.py` 把所有 `environment.general.lifecycle.*` prompt 都挂到 `env.general.workspace`。
- `backend/tests/task_environment_registry_regression.py` 目前还断言 general model input 中必须包含 active-work、tool-observation、memory lifecycle 文案。

问题：

- 没有 active work 时，模型也会看到 active-work control prompt。
- 没有工具观察时，模型也会看到 tool recovery prompt。
- 没有记忆动作时，模型也会看到 memory handoff prompt。
- 环境 prompt 变成了“大杂烩”，不再只是资源边界。

目标：

- environment 只保留 workspace orientation 和 boundary。
- lifecycle prompt 由 runtime selector 按状态挂载。

### P0. Prompt assembly 没有显式优先级

证据：

- `backend/prompt_library/assembly.py` 当前是 pack refs、explicit refs、skill refs、soul prompt 依次拼接。
- manifest 记录 stable refs，但没有记录“哪个 layer 权威更高”。

问题：

- agent role、runtime protocol、environment boundary、lifecycle fragment、tool guidance 都只是文本顺序。
- 未来加入 coordinator/mode/override 时，容易出现隐性覆盖或重复。

目标：

- 引入 `PromptAssemblyPolicy`。
- manifest 中记录 prompt layer、precedence、source、superseded refs 和 append refs。

### P1. Runtime protocol 和 lifecycle prompt 重复

证据：

- `backend/prompt_library/packs.py` 的 `RUNTIME_SINGLE_AGENT_TURN_PROMPT` 已经包含请求判断、active work、task handoff、tool observation、memory、finalization。
- `backend/prompt_library/general_lifecycle_prompts.py` 又分别写了这些生命周期。

问题：

- 同一职责分散在两个 owner layer。
- 后续改一处容易漏另一处。

目标：

- runtime protocol 只负责 action schema、输出协议、工具/控制 action 传输规则。
- lifecycle prompt 负责当前状态下的判断准则。
- agent role prompt 负责工作姿态、综合和收口。

### P1. Active work 控制结构已经更安全，但 prompt 没跟上

证据：

- `backend/harness/loop/active_work.py` 会校验 `relation_to_current_work`，独立请求或模糊请求不能控制当前工作。
- `backend/harness/runtime/compiler.py` 只有在存在 `active_work_context` 时才允许 `active_work_control`。
- 但 environment lifecycle 仍然常驻 active-work prompt。

目标：

- 有 active work 时挂载 active-work fragment。
- 没有 active work 时，只在 runtime projection 里给一句负事实：当前没有可控制工作。

### P1. 子 agent 架构接近成熟，但输出契约还有 confidence

证据：

- `backend/capability_system/tools/tool_units/subagent_control_tool.py` 已说明 fresh specialist 和不能预测 child result。
- `backend/prompt_library/rules.py` 仍要求 web researcher 返回 `confidence`。
- `backend/prompt_library/worker_prompts.py` 仍要求 web/PDF/table worker 返回 `confidence`。

目标：

- 子 agent prompt 增加“不要外包理解”。
- 删除模型自评 confidence。
- 输出改成 evidence、limitations、open questions、verification status、recommended parent action。

### P1. 记忆系统方向成熟，但 prompt 应该收窄作用域

证据：

- `memory_system_agent` 已注册。
- `context_compactor_agent` 已注册，并限制工具。
- memory maintenance 是 proposal 模式，不直接绕过系统提交层。
- runtime memory context 只暴露过滤后的 sections。

问题：

- `MEMORY_STATE_HANDOFF_PROMPT` 不应该作为 general environment 常驻。
- `backend/memory_system/durable.py` 的 recall selector 仍要求模型输出 confidence。
- 内部检索、解析、记忆治理确实有 quality/confidence 字段，需要和模型自评分开命名。

目标：

- memory handoff 按 memory/compaction/maintenance 状态挂载。
- recall selector 改成 `selection_reason`、`needs_verification`、`ignore_memory`。
- evidence quality 字段保留，但必须来自证据或系统计算。

### P2. `.v1` 后缀需要有范围切换规则

用户约束：新 prompt ID 不使用 `.v1`。

当前情况：

- 新 general lifecycle prompt 已经没有 `.v1`。
- 旧 runtime、worker、tool、environment prompt 仍大量使用 `.v1`。

目标规则：

- 本次新建 prompt resource 不使用 `.v1`。
- 被本次 refactor 触碰的 lifecycle/runtime prompt，应在切换时迁移到无后缀 ID。
- 无关旧 `.v1` 资源不要混在 lifecycle selector 第一阶段里大规模重命名，避免把范围扩大到不可控。

## 7. 目标 Prompt 库结构

建议目标资源族：

```text
runtime.base.constitution
runtime.turn.action_protocol
runtime.task.execution_protocol
runtime.observation.followup_protocol
runtime.compaction.semantic_checkpoint

agent.role.main_interactive.single_turn
agent.role.main_interactive.task_execution
agent.role.context_compactor.semantic_checkpoint
agent.role.memory_manager.maintenance

environment.general.workspace.orientation
environment.general.workspace.boundary

lifecycle.turn.context_intake
lifecycle.turn.request_judgment
lifecycle.turn.environment_alignment
lifecycle.turn.action_selection
lifecycle.state.active_work_control
lifecycle.state.task_run_handoff
lifecycle.state.user_steer_contract_revision
lifecycle.state.tool_observation_recovery
lifecycle.state.memory_state_handoff
lifecycle.turn.finalization

tool.guidance.read_file
tool.guidance.write_file
tool.guidance.terminal_powershell
tool.guidance.subagent
tool.guidance.browser
tool.guidance.web_fetch

memory.recall.selector
memory.context.runtime_view
memory.maintenance.proposal_schema
```

这些新目标 ID 都不使用 `.v1`。

## 8. 生命周期选择矩阵

| Prompt fragment | 挂载条件 | Owner | 说明 |
| --- | --- | --- | --- |
| `lifecycle.turn.context_intake` | single-agent turn 或有用户/历史上下文的任务执行 | runtime lifecycle selector | 处理上下文权威顺序 |
| `lifecycle.turn.request_judgment` | single-agent turn | runtime lifecycle selector | 判断用户当前请求 |
| `lifecycle.turn.environment_alignment` | 有环境/工具边界投影 | runtime lifecycle selector | 对齐目标和可用能力 |
| `lifecycle.turn.action_selection` | 有 action schema 的模型 turn | runtime lifecycle selector | 选择最小充分动作 |
| `lifecycle.state.active_work_control` | 有 `active_work_context` 且允许 `active_work_control` | runtime lifecycle selector | 不能常驻环境 |
| `lifecycle.state.task_run_handoff` | 允许 `request_task_run` | runtime lifecycle selector | 生成高质量任务合同 |
| `lifecycle.state.user_steer_contract_revision` | 有 active work、pending steer 或合同修订上下文 | runtime lifecycle selector | 处理用户中途改方向 |
| `lifecycle.state.tool_observation_recovery` | tool observation followup 或存在最新工具观察 | runtime lifecycle selector | 跟工具观察绑定 |
| `lifecycle.state.memory_state_handoff` | memory context、memory maintenance 或 compaction 在场 | memory/runtime lifecycle selector | 不能常驻 general environment |
| `lifecycle.turn.finalization` | 任何用户可见收口路径 | runtime lifecycle selector | 保持简短、始终可用 |

## 9. 环境式 Prompt 控制器设计

本轮新增约束：prompt 应做成环境式，由环境控制器为每个任务环境装配一整套 prompt 策略。

这里的“环境式”不是把某个环境的全部 prompt 静态塞入模型，而是：

```text
通用环境基座
+ 用户当前选择的任务环境 overlay
+ 当前 invocation 的 runtime protocol
+ 当前状态触发的 lifecycle fragments
+ 当前可见工具的 tool guidance
+ 当前可见 memory/compaction guidance
=> PromptMountPlan
```

### 9.1 通用环境是默认基座

`env.general.workspace` 是默认环境，也是所有任务环境的基础。

它负责：

- 通用 workspace orientation；
- 通用资源边界；
- 通用上下文权威顺序；
- 通用用户请求判断；
- 通用收口标准；
- 通用工具/权限解释框架。

它不负责：

- 替用户选择专门任务环境；
- 把所有任务环境 prompt 都常驻；
- 覆盖 runtime action protocol；
- 覆盖 agent profile；
- 替模型判断当前用户意图。

### 9.2 其他任务环境只做覆盖

除通用环境外，其它任务环境应该是 overlay，而不是替换整套 base prompt。

例如：

```text
general.workspace.base
+ coding.workspace.overlay
```

或：

```text
general.workspace.base
+ writing.graph_node.overlay
```

overlay 只能补充或收窄：

- 任务领域身份；
- 产物验收标准；
- 领域工具说明；
- 特定环境的文件/存储边界；
- 特定任务的 lifecycle policy；
- 特定 finalization policy。

overlay 不能移除：

- runtime action protocol；
- 用户最新请求最高权威；
- 工具观察事实权威；
- 权限边界；
- active work relation guard；
- memory candidate-only 规则。

### 9.3 环境切换由用户控制

环境切换的来源应该是用户或 session/project binding，而不是模型自己静默切换。

当前推荐规则：

- 默认使用 `env.general.workspace`。
- 用户在 UI、会话设置或任务入口明确选择任务环境后，系统记录 `selected_environment_id`。
- 运行时基于 `selected_environment_id` 装配对应 overlay。
- 模型只能看到当前已选择环境和可请求的环境切换能力说明，不能直接伪造环境已切换。

### 9.4 通用环境可预留自主切换接口，但暂不实装

可以为通用环境设计一个未来接口，例如：

```text
environment_switch_request
```

这个接口只表示主 agent 认为当前任务可能更适合某个任务环境，需要请求用户确认或 UI 控制面处理。

暂时不实装：

- 不新增 action type；
- 不新增 API route；
- 不新增前端切换控件；
- 不让模型直接切换环境；
- 不改当前 runtime branch 行为。

计划中只保留接口设计和 prompt 约束，等环境控制器稳定后再做。

### 9.5 EnvironmentPromptController 输出

目标输出不是直接字符串，而是结构化 mount plan：

```text
PromptMountPlan
- base_environment_id
- selected_environment_id
- base_prompt_refs
- overlay_prompt_refs
- lifecycle_prompt_refs
- tool_guidance_refs
- memory_prompt_refs
- precedence_report
- rejected_refs
- diagnostics
```

RuntimeCompiler 只消费 `PromptMountPlan`，不再自己猜哪些 environment refs 应该进入本轮。

## 10. 实施蓝图

### 阶段 1：增加 PromptAssemblyPolicy 和 precedence diagnostics

涉及文件：

- `backend/prompt_library/models.py`
- `backend/prompt_library/assembly.py`
- `backend/prompt_library/manifest.py`
- `backend/harness/runtime/compiler.py`
- `backend/tests/prompt_rule_system_regression.py`
- `backend/tests/prompt_library_registry_regression.py`

目标：

- 给 prompt resource/section 增加 layer、precedence、source metadata。
- manifest 能说明每段 prompt 的来源层级和最终顺序。
- 行为先保持等价，只增强结构和可观测性。

完成标准：

- 旧 prompt 仍能 resolve。
- manifest 能回答“哪一层装配了哪段 prompt”。
- 测试不只断言 ref list，还断言 precedence。

### 阶段 2：引入 EnvironmentPromptController 和 lifecycle selector

涉及文件：

- `backend/prompt_library/general_lifecycle_prompts.py`
- `backend/task_system/environments/default_environments.py`
- `backend/task_system/environments/spec_resolver.py`
- `backend/harness/runtime/assembly.py`
- `backend/harness/runtime/compiler.py`
- `backend/tests/task_environment_registry_regression.py`
- `backend/tests/dynamic_prompt_context_projection_test.py`

目标：

- general environment 成为默认基座。
- 其它任务环境只作为 overlay 装配。
- lifecycle refs 由 EnvironmentPromptController 根据 invocation、allowed actions、active work、memory context、tool observations、recent outcome 选择。
- 只写入自主切换接口设计，不实装 action/API/UI。

完成标准：

- 没有 active work 时，model input 不包含完整 active-work prompt。
- 没有工具观察时，model input 不包含 tool recovery prompt。
- 没有 memory context/maintenance/compaction 时，model input 不包含 memory handoff prompt。
- stable payload 能区分 base environment refs、overlay environment refs 和 lifecycle refs。
- manifest 能显示 `base_environment_id=env.general.workspace` 和当前用户选择的 `selected_environment_id`。

### 阶段 3：去重 runtime protocol 和 lifecycle 文案

涉及文件：

- `backend/prompt_library/packs.py`
- `backend/prompt_library/agent_prompts.py`
- `backend/prompt_library/rules.py`
- `backend/tests/prompt_library_registry_regression.py`

目标：

- runtime prompt 只保留 action protocol。
- lifecycle prompt 负责判断细节。
- agent role prompt 负责角色、责任和收口。

完成标准：

- active-work/tool-observation/memory 判断文案不在 runtime 和 lifecycle 中重复。
- runtime prompt 仍完整定义合法 JSON/native action 行为。

### 阶段 4：子 agent prompt 成熟化和 confidence 清理

涉及文件：

- `backend/prompt_library/rules.py`
- `backend/prompt_library/worker_prompts.py`
- `backend/capability_system/tools/tool_units/subagent_control_tool.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/tests/search_specialist_split_regression.py`
- `backend/tests/worker_prompt_registry_regression.py`
- `backend/tests/subagent_control_regression.py`

目标：

- 子 agent 工具说明补充 “never delegate understanding”。
- worker prompt 删除模型自评 confidence。
- active_work native control payload 删除或拒绝 confidence。

完成标准：

```powershell
rg -n "confidence" backend/prompt_library backend/harness/loop/single_agent_turn.py
```

结果中不应再出现模型决策 confidence 要求。

### 阶段 5：记忆 selector 和记忆分类清理

涉及文件：

- `backend/prompt_library/agent_prompts.py`
- `backend/memory_system/durable.py`
- `backend/memory_system/maintenance.py`
- `backend/memory_system/runtime_context_provider.py`
- `backend/tests/memory_maintenance_agent_regression.py`
- `backend/tests/memory_system_contracts_regression.py`

目标：

- 记忆管理员 prompt 明确区分：
  - 当前用户回复；
  - 当前任务状态；
  - todo；
  - plan；
  - session recovery summary；
  - durable memory。
- durable recall selector 不再要求模型 confidence。
- memory context 继续作为候选上下文，不能覆盖当前事实。

完成标准：

- memory prompt 不再要求模型自评分。
- 测试证明 memory 不能覆盖最新用户消息和工具观察。

### 阶段 6：完整验证

建议命令：

```powershell
python -m pytest backend/tests/prompt_library_registry_regression.py backend/tests/task_environment_registry_regression.py
python -m pytest backend/tests/dynamic_prompt_context_projection_test.py backend/tests/prompt_rule_system_regression.py
python -m pytest backend/tests/search_specialist_split_regression.py backend/tests/worker_prompt_registry_regression.py backend/tests/subagent_control_regression.py
python -m pytest backend/tests/memory_maintenance_agent_regression.py backend/tests/memory_system_contracts_regression.py backend/tests/context_compaction_budget_regression.py
python -m pytest backend/tests/harness_runtime_facade_regression.py backend/tests/active_turn_authority_regression.py
```

运行链路验证：

- 后端固定 `127.0.0.1:8003`。
- 前端固定 `127.0.0.1:3000`。
- 普通直接回答。
- 单轮只读工具调用。
- active work 状态询问。
- active work 继续。
- 有 active work 时提出独立新问题。
- task-run handoff。
- 工具失败后的恢复。
- memory context 可见但不成为当前事实。
- context compactor 调用。
- memory maintenance after commit。

## 11. 切换规则

1. 不保留旧 lifecycle 常驻路径。
   - selector 生效后，environment default 不应再挂所有 lifecycle refs。

2. 不增加隐藏 fallback。
   - lifecycle ref 缺失应显式诊断失败，不能偷偷恢复旧大包。

3. 不再让模型输出自评 confidence。
   - 需要质量字段时，必须说明它是证据质量、解析质量还是系统计算分。

4. 新 prompt ID 不使用 `.v1`。
   - 被本次触碰的新资源和重构资源应使用无后缀 ID。

5. 测试保护目标行为，不保护旧内部形状。
   - 当前断言所有 lifecycle prompt 常驻的测试必须改成 selector 行为测试。

6. 环境切换必须由用户或 session 控制。
   - 主 agent 可以请求切换，但不能静默切换。
   - 自主切换接口只作为预留设计，不在本阶段落实现。

7. 非通用任务环境只能 overlay。
   - overlay 可以补充和收窄环境要求，不能替换通用基座、runtime protocol 或权限边界。

## 12. 当前结论

已经比较稳的部分：

- prompt library 已存在。
- agent role prompt 已存在。
- context compactor agent 已存在，且工具受限。
- memory manager 已存在，并以 proposal 方式工作。
- active-work relation 校验已存在。
- subagent lifecycle tools 已存在，并已有 fresh specialist / no prediction 规则。

还不能称为成熟架构的部分：

- prompt assembly 没有显式优先级；
- lifecycle prompt 仍然常驻 general environment；
- runtime protocol 和 lifecycle prompt 有重复；
- worker/subagent/memory 中还有模型自评 confidence；
- memory handoff prompt 作用域过宽；
- 部分测试仍在保护旧的 always-mounted lifecycle 形状。

推荐下一步先做阶段 1 和阶段 2：

- 阶段 1 让 prompt 装配可观测、可诊断、有优先级；
- 阶段 2 修掉最大结构问题：由 EnvironmentPromptController 以通用环境为基座，按用户选择的任务环境 overlay 和当前状态装配 prompt。

这两个阶段必须一起做。只做阶段 1 会留下主问题；只做阶段 2 会让 selector 难以审计。
