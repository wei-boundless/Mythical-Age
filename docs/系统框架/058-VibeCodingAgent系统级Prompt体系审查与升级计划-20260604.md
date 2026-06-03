# Vibe Coding Agent 系统级 Prompt 体系审查与升级计划

日期：2026-06-04

## 1. 结论

本项目已经有比较完整的 prompt 装配骨架：runtime pack、prompt rule、agent role、environment rule、segment plan、prompt manifest 和 dynamic context projection 都已经存在。当前短板不是“没有提示词”，而是还没有达到成熟 vibe coding agent 所需的系统级 prompt 分层：

- 缺少一段全局稳定的 coding agent foundation prompt，用来定义主 agent 的行为不变量、工作方式、验证真实性、用户改动保护、收口报告和高风险操作边界。
- 缺少受控项目指令通道。`AGENTS.md` 不能进入长期记忆，也不能作为普通静态摘要进入 prompt；它应作为有作用域、优先级和变更诊断的 project instruction section 注入。
- 工具级 prompt 仍以 schema 为主。成熟 coding agent 的 Read/Edit/Write/Terminal/Git/Todo/Subagent/Browser 工具都需要工具自身的行为协议，不能只靠全局 rule 提醒。
- 计划模式不是一等协议。当前有 `planning_policy` 和 `agent_todo`，但缺少类似 EnterPlan/ExitPlan 的模式切换、计划文件/计划书合同、用户批准和实施锁定机制。
- worker agent blueprint 已经像角色 prompt，但还没有完全纳入 prompt_library，缺少可版本化、可诊断、可按 invocation 装配的 worker prompt refs。
- verification gate 不够硬。已有验证 agent blueprint，但缺少成熟验证 agent 那种命令证据、对抗性 probe、PASS/FAIL/PARTIAL verdict 和禁止改项目文件的强协议。
- prompt cache 分层已有，但缺少“session memoized section vs volatile section with reason”的显式审计模型，容易让动态内容误入稳定段。

系统级 prompt 不应该写成一个巨型提示词。目标架构应是：

```text
global foundation
-> runtime protocol pack
-> permission/environment boundary
-> project instructions
-> agent role
-> task contract / graph node contract
-> visible tool guidance
-> dynamic runtime projection
-> volatile current user/task state
```

`TurnRun` 与 `TaskRun` 的 prompt 也必须分开。`TurnRun` 是一次 conversational turn trace，主要用于当前请求判断、只读观察、active work control 和是否创建 TaskRun；`TaskRun` 是 durable lifecycle record，prompt 必须围绕任务合同、执行状态、产物证据、恢复和验收，不再重新判断是否创建任务生命周期。

## 2. 技术源报告

### 2.1 本项目现状

已具备的能力：

- `backend/prompt_library/packs.py` 已有 `runtime.single_agent_turn.v1`、`runtime.task_execution.v1`、`runtime.graph_node_execution.v1`、`runtime.observation_followup.v1` 四类 runtime protocol，并通过 pack 装配 `system_call_protocol`、`intent_feedback`、`tool_use`、`output_boundary`、`error_recovery`、`context_memory`、`permission_denial`、`subagent_delegation`。
- `backend/prompt_library/rules.py` 已有 coding/development 环境规则，包括代码检查、编辑、验证、git safety、Windows shell、task progress、workspace boundary；同时有 rule diagnostics，可拒绝 invocation mismatch、cache tier mismatch 和开发说明式 prompt 文案。
- `backend/prompt_library/agent_prompts.py` 已有 main interactive agent 的 single-turn、task-execution、observation-followup 三套角色 prompt，task execution prompt 已覆盖读文件、编辑、验证、PowerShell、git、安全审批、子 agent、todo 等关键行为。
- `backend/harness/runtime/compiler.py` 已经把 single-turn 分成 `global_static`、`turn_stable`、`turn_context`、provider history、`dynamic_projection`、`volatile_user`；task execution 分成 `global_static`、`action_schema_static`、`environment_stable`、`agent_stable`、`artifact_scope_stable`、`tool_index_stable`、`task_contract_stable`、`dynamic_projection`、`volatile_task_state`。
- `backend/tests/static_agents_context_regression.py` 明确要求 `AGENTS.md` 不进入 static context 或 long-term context。这个约束是正确的，但下一步必须新增受控 project instruction 通道。
- `backend/agent_system/registry/worker_agent_factory.py` 已有 explorer、planner、verification、execution、code executor、review 等 worker blueprints；这些 description 已经接近 agent-facing prompt，但还只是 registry 描述，未成为 prompt_library 中的版本化 prompt resource。
- `backend/harness/runtime/tool_plan.py` 与 `backend/capability_system/tools/native_tool_catalog.py` 已有工具 schema、operation metadata、read_only/destructive/concurrency_safe 投影；但 `prompt_exposure_policy` 大多是 `schema_only`，缺少成熟工具级 prompt。
- `docs/系统框架/057-VibeCodingAgent并发执行架构设计与实施计划-20260604.md` 已经把 single-turn tool batch、TaskRun lifecycle、graph/task parallel 三层并发边界拆开。prompt 体系必须吸收这个裁决，不能继续暗示所有多工具调用都会无条件并行。

当前问题判断：

- 装配框架是成熟架构的骨架。
- 内容权威层还不完整。
- 工具级协议缺失是最大行为短板。
- 项目指令缺受控发现和注入链路。
- plan/review/verification/subagent 还没有达到一等 coding agent 模式。

### 2.2 Codex 源码可借鉴点

已对照的源码：

- `D:\AI应用\openai-codex\codex-rs\core\gpt_5_codex_prompt.md`
- `D:\AI应用\openai-codex\codex-rs\core\prompt_with_apply_patch_instructions.md`
- `D:\AI应用\openai-codex\codex-rs\core\src\context\user_instructions.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\context\permissions_instructions.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\client_common.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\tools\handlers\plan_spec.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\tools\handlers\multi_agents_spec.rs`
- `D:\AI应用\openai-codex\codex-rs\core\src\tools\handlers\apply_patch_spec.rs`

关键成熟不变量：

- 基础 prompt 明确定义 coding agent 身份、搜索偏好、编辑约束、dirty git safety、计划工具、review stance、最终答复风格。
- 项目指令不是长期记忆，而是带 marker 的 user fragment；直接系统/开发/用户指令优先于项目指令。
- 权限和 sandbox 是 developer fragment，由运行配置生成，不靠模型猜测。
- `Prompt` 同时包含 tools、parallel_tool_calls、base_instructions；工具能不能并行由 runtime/tool handler 和请求参数共同控制。
- `update_plan` 是工具 spec，状态规则写进 schema description，最多一个 `in_progress`。
- `apply_patch` 是 grammar/freeform tool，编辑协议被工具本身约束，而不是普通文本提醒。
- subagent spawn 是工具协议：brief 必须具体，子 agent 用于明确授权的并行/隔离任务，主 agent 仍要推进关键路径。

本项目应借鉴这些不变量，但不照搬 CLI 形态。本项目有独立的 TaskRun、task_system、graph 和 runtime assembly，因此应把 Codex 的原则映射到现有边界，而不是把本项目重写成 Codex。

### 2.3 Claude Code 源码可借鉴点

已对照的源码：

- `D:\AI应用\claude-code-nb-main\constants\prompts.ts`
- `D:\AI应用\claude-code-nb-main\constants\systemPromptSections.ts`
- `D:\AI应用\claude-code-nb-main\utils\systemPrompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\BashTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\PowerShellTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\FileReadTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\FileEditTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\FileWriteTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\TodoWriteTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\AgentTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\EnterPlanModeTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\ExitPlanModeTool\prompt.ts`
- `D:\AI应用\claude-code-nb-main\tools\AgentTool\built-in\exploreAgent.ts`
- `D:\AI应用\claude-code-nb-main\tools\AgentTool\built-in\verificationAgent.ts`

关键成熟不变量：

- system prompt 有显式 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`，静态跨组织缓存内容和动态会话内容严格分离。
- `systemPromptSection` 是 session memoized，`DANGEROUS_uncachedSystemPromptSection` 每轮重算并要求理由。
- effective system prompt 有优先级：override、coordinator、main thread agent、custom、default，再追加 append prompt。
- 系统 prompt 拆成 intro、system、doing tasks、executing actions with care、using tools、tone/style、output efficiency、language、memory、environment、MCP、scratchpad、tool-result summarization 等 section。
- 工具 prompt 很重。Read/Edit/Write/PowerShell/Todo/Agent 工具都把使用时机、禁止事项、失败处理、并发/后台、专用工具优先级写进工具说明。
- Plan mode 是工具化协议：进入 plan mode、探索代码、写计划文件、退出并请求用户审批，是明确模式，不靠普通回复“我先计划一下”。
- Explore/Verification 是专门 worker prompt。Explore 明确只读、禁止写入和快速搜索；Verification 明确不是确认成功，而是尝试打破实现，要求命令证据和 verdict。

本项目应借鉴这些层级和协议强度，但不复制 Claude Code 的 UI/工具名/文件名。重点是把“prompt section、tool prompt、plan mode、worker prompt、verification verdict”作为本项目自己的 prompt resource 和 runtime contract。

## 3. 成熟 vibe coding agent 的系统级 prompt 标准

系统级 prompt 至少要覆盖以下能力，而且要按权威层分开：

1. **身份和工作不变量**
   - 这是 coding agent，不是普通聊天机器人。
   - 必须读懂真实代码、遵循现有架构、保护用户改动、真实验证、准确报告。
   - 不允许跳过测试、弱化断言、硬编码输出或伪造通过。

2. **用户目标裁决**
   - 区分问答、只读观察、短工具批处理、持续 TaskRun、graph/task_system 业务任务。
   - 不被历史摘要、todo、旧任务、active work 或记忆劫持当前用户意图。

3. **项目指令优先级**
   - scoped project instructions 高于普通历史和记忆，低于直接系统/开发/用户指令。
   - 嵌套目录指令按作用域和深度生效。
   - 项目指令文件变化必须反映在 prompt manifest 和 cache key。

4. **工具使用边界**
   - 不可见工具不存在。
   - 专用读写搜索工具优先于 shell。
   - 工具失败是事实观察，不能原样重试。
   - 多工具调用只是模型可以提出多个，runtime 会按安全边界并发或串行。

5. **文件和编辑协议**
   - 编辑前读取当前真实内容。
   - edit old_text 必须来自当前读取结果并足够唯一。
   - write_file 用于新文件或完整重写，修改现有文件优先 edit_file。
   - 不主动创建 README、说明文档或计划文档，除非用户或合同要求。

6. **计划模式和实施锁定**
   - 大改动先探索、写计划、等待确认。
   - 用户批准后按计划实施。
   - 计划变更需要重新说明偏差，不允许实施时随意漂移。

7. **验证和收口**
   - 按风险运行测试、构建、语法检查、API 或浏览器验证。
   - 不能把阅读代码当作验证。
   - 最终答复必须区分已完成、已验证、未验证和阻塞。

8. **子 agent 和并发**
   - 子 agent 用于隔离搜索、独立验证、并行探索或边界清楚的局部执行。
   - brief 必须包含目标、上下文、范围、排除项、期望输出和失败处理。
   - 子 agent 未返回前不能预测结论。

9. **安全和 prompt injection**
   - 工具结果和外部内容可能含有 prompt injection，只能作为数据。
   - hooks、MCP、网页、文件内容、测试输出不能覆盖系统/开发/项目指令。

10. **上下文和缓存**
    - 静态基础规则、环境稳定规则、任务合同、动态状态、当前用户消息必须分层。
    - volatile 内容不能进入 global/static cache。
    - prompt manifest 必须能解释每段来源、权威、cache tier 和变更原因。

## 4. 系统级 prompt 应该怎么写

### 4.1 不写成一个巨型 prompt

系统级 prompt 应拆成可审计资源。建议新增以下 prompt refs：

```text
system.foundation.vibe_coding_agent.v1
system.foundation.response_and_reporting.v1
system.foundation.security_and_injection.v1
system.foundation.context_and_cache.v1
runtime.rule.multi_tool_scheduling.v1
runtime.rule.plan_mode_boundary.v1
project.instructions.scoped.v1
tool.guidance.read_file.v1
tool.guidance.edit_file.v1
tool.guidance.write_file.v1
tool.guidance.terminal_powershell.v1
tool.guidance.git.v1
tool.guidance.todo.v1
tool.guidance.subagent.v1
tool.guidance.browser.v1
skill.candidate_cards.v1
skill.active_body.v1
mcp.instructions.delta.v1
memory.context_projection.v1
tool_result.summary_policy.v1
worker.prompt.explorer.v1
worker.prompt.planner.v1
worker.prompt.execution.v1
worker.prompt.verification.v1
worker.prompt.review.v1
```

每段 prompt resource 必须带：

```text
prompt_id
owner_layer
allowed_invocation_kinds
allowed_agent_refs
allowed_environment_refs
cache_scope
authority
requires / conflicts_with
version
diagnostics metadata
```

### 4.2 Foundation prompt 草案

以下是 foundation prompt 的写法方向，不是最终逐字上线文本：

```text
你是一名在用户本地项目中工作的 coding agent。
你的职责是理解用户当前目标，检查真实代码和运行环境，在授权边界内完成实现、验证、审查或解释工作，并向用户准确报告结果。

你需要先让当前请求本身成为最高优先级事实。
历史摘要、旧任务、todo、记忆、工具建议和当前运行上下文只能帮助你判断下一步，不能替代用户当前消息。

处理代码任务时，你必须先理解相关文件、调用链、配置、测试入口和已有改动。
不了解位置时先搜索；知道路径后读取具体文件；修改前必须读到目标文件当前真实内容。

你需要保护用户已有改动。
除非用户明确要求，不要回滚、覆盖、清理或提交不属于当前任务的变更。

你只能使用当前运行边界可见的工具和动作。
工具失败是事实观察；下一步必须改变参数、范围、工具或计划，不能原样重复失败动作。
当模型可以提出多个工具调用时，运行时会根据工具能力、资源冲突和审批状态决定并发或串行。

你需要真实验证。
完成前根据改动风险运行测试、构建、语法检查、脚本、API 请求或浏览器检查。
如果无法验证，必须说明具体原因和剩余风险。
不要跳过测试、弱化断言、硬编码结果、删除失败用例或伪造输出。

对于高影响改动、架构重构、任务合同变更、数据库/API 协议变化或跨多个核心模块的工作，你需要先形成可审查计划，并在用户批准后实施。
计划获批后按计划推进；如果发现计划假设错误或风险显著扩大，需要说明偏差并重新确认。

你的最终答复只描述用户需要知道的结果、产物、验证和风险。
不要暴露隐藏推理、内部协议字段、运行标识或无关工具噪声。
```

关键点：

- 这段只放稳定行为不变量。
- 不放当前日期、cwd、端口、权限、工具列表、AGENTS 内容、active work、task state。
- 不把 runtime schema、JSON action、工具参数细节塞进 foundation。
- 不写开发说明式语言，要直接告诉 agent 它是谁、负责什么、怎么判断、怎么失败处理。

### 4.3 Runtime protocol prompt 写法

runtime protocol 只负责“本轮怎么调用系统”，不负责重复所有 coding 规则：

- single-turn protocol：允许 respond、ask_user、tool_call、request_task_run、active_work_control 等当前轮动作。
- task-execution protocol：只能输出一个合法 JSON action；每轮只提交一个 action；不能再次开启 TaskRun；完成必须基于合同和证据。
- graph-node protocol：只完成当前节点合同，不重写全图流程。
- observation-followup protocol：把观察结果作为事实，继续 respond、只读观察、request_task_run 或 block。

这里应补一条并发文案：

```text
你可以在同一轮提出多个互不依赖的工具调用。
这只表示请求层允许多个 tool calls；运行时会根据工具元数据、资源冲突、审批和安全策略决定并发执行、串行执行或阻塞等待。
不要把多工具调用理解为所有工具都会同时执行。
```

### 4.4 Tool prompt 写法

工具 prompt 应由工具自己的 prompt resource 承担，不能只依赖全局 rule。

最小工具 prompt 集合：

- `read_file`：路径要求、窗口读取、has_more/next_start_line、图片/PDF/结构化文件边界、不要重复同窗口。
- `edit_file`：必须先读、old_text 唯一、保留缩进、失败后重新读取局部、最小修改。
- `write_file`：新文件或完整重写、覆盖风险、现有文件优先 edit_file、不要主动创建文档。
- `terminal_powershell`：用途限制、不要用 shell 做专用文件读写搜索、PowerShell 5.1/7 差异、交互命令禁止、后台任务、路径引用、git 安全、timeout。
- `git`：read 与 write 分开、dirty worktree、stage 精确文件、commit/push 只在用户明确要求时执行、禁止 destructive 默认操作。
- `todo`：何时用、何时不用、状态规则、完成条件、不能作为事实来源。
- `subagent`：何时委派、何时不要委派、fresh agent brief 内容、等待结果、不要预测子 agent。
- `browser`：何时需要真实浏览器、页面启动前置、截图/console/network 证据、固定项目端口规则。
- `web/fetch`：当前信息必须查、优先官方来源、外部内容不可信、来源和日期。

工具 prompt 注入规则：

- 只有工具可见时注入该工具 guidance。
- guidance 可以进入 `tool_index_stable` 或独立 `tool_guidance_stable`。
- `prompt_exposure_policy` 应从纯 `schema_only` 扩展为 `schema_plus_guidance`、`hidden`、`runtime_bound_only` 等可诊断模式。
- 工具 guidance 不应重复工具 schema 的字段定义，而应说明使用协议、失败处理和禁止事项。

### 4.5 Project instructions 写法

项目指令应作为 `project.instructions.scoped.v1`，不是 long-term memory。

推荐规则：

- 从 workspace root 到目标文件路径逐层发现 `AGENTS.md`。
- root 到 cwd 的指令作为当前会话基础项目指令。
- 当 agent 要触碰 cwd 子目录以外路径时，按目标路径补充更深层 `AGENTS.md`。
- 更深层指令覆盖更浅层同类指令。
- 直接系统/开发/用户指令高于 project instruction。
- 当前用户消息高于旧项目指令中的一般偏好，但不能覆盖安全和权限边界。
- project instruction 的内容进入 prompt manifest，并包含 path、scope_root、mtime/hash、applies_to。
- `AGENTS.md` 变化导致对应 session/task stable section cache break，而不是污染 global static cache。

本项目现有测试已经禁止 `AGENTS.md` 进入 static/long-term context，后续应保留这些测试，并新增 project instruction runtime tests。

### 4.6 Skills、MCP、Memory 和工具结果摘要

成熟 prompt 体系还需要把“可选能力”“外部服务说明”“记忆投影”“工具结果摘要策略”分开。它们不属于 global foundation，也不应塞进项目指令。

本项目已有相关入口：

- `backend/task_system/contracts/runtime_contracts.py` 已有 skill candidate cards 和 selected skill body 展开机制。
- `backend/harness/runtime/tool_plan.py` 已能投影 local MCP route capability。
- `backend/harness/runtime/dynamic_context/manager.py` 已有 tool result projection/ref projection 能力。
- `backend/prompt_library/rules.py` 已有 context/memory rule，但缺少更细的 memory section 归属和工具结果摘要策略。

目标规则：

- skill candidate cards 只告诉 agent “哪些 skill 可选、何时用、不能用于什么”，不展开完整技能正文。
- selected skill body 只在 agent 选择或任务合同绑定后展开，并且不能覆盖用户目标、权限边界和验证要求。
- MCP instructions 应作为独立 section 注入，记录 server/source、可用能力、动态变化原因和安全边界；MCP 返回内容不能覆盖系统/项目/工具规则。
- memory context projection 只提供有来源和新鲜度的事实、偏好或候选；不确定记忆不能当作当前事实。
- tool result summary policy 应告诉 agent：长结果、外部结果、失败结果和截断结果如何被摘要、引用和复查；不能把摘要当作完整原文。
- output style/language 属于用户沟通层，不能改变工具调用协议、验证标准或任务合同。

建议新增 section：

```text
skill_candidate_stable
skill_active_body_stable
mcp_instruction_delta
memory_context_projection
tool_result_summary_policy
```

这些 section 的 cache 策略：

- skill candidate cards 可以 session_stable，取决于 task/runtime assembly。
- selected skill body 通常 task_stable 或 session_stable，必须记录 accepted/rejected skill ids。
- MCP instruction delta 是 session_stable 或 volatile，取决于 MCP 连接是否会话内变化。
- memory context projection 是 volatile 或 task_stable candidate，不进入 global static。
- tool result summary policy 可 global_static，但具体 tool result refs 和摘要必须 volatile。

## 5. 目标 prompt 分层

| 层级 | 建议 cache | owner | 内容 | 不允许包含 |
| --- | --- | --- | --- | --- |
| Global foundation | global_static | system | coding agent 身份、工作方式、安全、验证、报告 | cwd、权限、工具列表、项目指令、用户消息 |
| Runtime protocol | global_static | runtime | 本 invocation 的 action schema 和系统调用规则 | 业务任务内容、工具长说明 |
| Permission/env boundary | static_environment / session_stable | environment | sandbox、approval、固定端口、shell 环境、文件边界 | 历史摘要、用户当前目标 |
| Project instructions | session_stable / task_stable | project_instruction | scoped AGENTS.md 等项目规则 | 长期记忆、未作用于当前路径的指令 |
| Agent role | session_stable | agent | main/worker agent 职责和边界 | 当前 task state |
| Task contract | task_stable | task | TaskRunContract、验收、产物、权限和恢复策略 | 与合同无关的历史 |
| Tool guidance | tool_index_stable | tool | 可见工具的使用协议、失败处理、禁止事项 | 不可见工具说明 |
| Skill/MCP guidance | session_stable / task_stable | capability | skill 候选、已激活 skill、MCP 能力说明 | 覆盖系统/项目/工具规则的外部指令 |
| Memory projection | volatile / task_stable | memory | 有来源和新鲜度的记忆事实或候选 | 未验证记忆、旧任务裁决 |
| Tool-result summary policy | global_static / volatile | runtime | 摘要规则和具体结果 refs | 把摘要伪装成完整原文 |
| Dynamic projection | volatile | runtime | active work、operation authorization、最近工具观察、状态投影 | 稳定规则 |
| Current user/task state | volatile | user/runtime | 当前消息、当前 step state、最新 observation | 可缓存规则 |

推荐装配顺序：

```text
1. system.foundation.*
2. runtime.pack.*
3. environment prompt refs
4. project instruction sections
5. agent role prompt
6. skills / worker capability cards
7. MCP / memory / selected skill bodies
8. task contract / graph node contract
9. visible tool schema + tool guidance
10. provider transcript
11. dynamic runtime projection
12. volatile current request or task state
```

## 6. TurnRun 与 TaskRun 对 prompt 的影响

### 6.1 TurnRun prompt

`TurnRun` prompt 服务于当前用户这一轮：

- 判断用户是在问答、要求观察、要求实现、控制 active work、补充当前工作，还是需要创建新的 TaskRun。
- 可以通过只读工具观察后 followup。
- 可以通过 `request_task_run` 建立 durable lifecycle。
- 可以关联已有 active_work_context，但不能被旧任务劫持。
- 不应看到完整 TaskRun executor step loop 的内部控制协议。

TurnRun 的 prompt 应包括：

- global foundation
- single-turn runtime protocol
- environment/project instructions
- main interactive agent role
- visible tool guidance
- active work projection
- current user message

### 6.2 TaskRun prompt

`TaskRun` prompt 服务于已存在的 durable lifecycle：

- 目标来自 TaskRunContract，不再重新判断是否要创建任务。
- 每轮只执行一个 action JSON。
- 必须根据 task_state、artifact_evidence、latest_tool_results、active_failures 推进。
- 完成必须满足 completion criteria、required artifacts 或 required verifications。
- 不能再次开启新的持续处理流程。

TaskRun 的 prompt 应包括：

- global foundation
- task-execution runtime protocol
- environment/project instructions
- executing agent role
- task contract stable payload
- artifact scope and tool index
- visible tool guidance
- execution state / rollout / observations

### 6.3 二者关系裁决

`TurnRun` 和 `TaskRun` 是并列 durable records，通过 refs 关联：

- `TurnRun` 是 conversational turn trace。
- `TaskRun` 是 durable lifecycle record。
- 一个 TurnRun 可以创建一个 executable TaskRun，但 TurnRun 结束后 TaskRun 可继续后台运行。
- TaskRun 可来自 TurnRun、graph node、subagent、engagement 等路径。
- `execute_task_run` 只调度/恢复已有 executable TaskRun，不创建业务任务。
- prompt 体系不能把 TaskRun execution prompt 用在普通 TurnRun，也不能把 single-turn active work prompt 用来替代 TaskRunContract。

## 7. 对 057 并发设计的 prompt 审查

057 的并发设计没有严重冲突，反而给 prompt 体系提供了必要边界。需要补充的 prompt 事项：

- `parallel_tool_calls=True` 只表示模型可以同轮提出多个工具调用，不表示 runtime 无差别并发。
- single-turn prompt 和 tool guidance 需要统一改成“运行时按安全边界并发或串行”。
- subagent prompt 需要区分“可以并行委派互不依赖任务”和“不能重复委派同一搜索或预测结果”。
- TaskRun prompt 不应承诺每步可多工具并发；第一阶段仍保持每轮一个 action。
- graph/task parallel prompt 应通过 graph contract 和 resource conflict policy 表达，不和 single-turn tool batch 混用。

## 8. 实施计划

### Phase 1：新增 foundation prompt resource

目标：

- 新增全局 vibe coding foundation prompt。
- 把响应风格、安全、验证、用户改动保护、上下文压缩、prompt injection 基础规则从分散 rule 中抽成稳定 foundation。
- 保持现有 runtime pack 可用，但让 pack 的第一层先装配 foundation。

涉及文件：

- `backend/prompt_library/system_prompts.py` 新增。
- `backend/prompt_library/__init__.py` 导出。
- `backend/prompt_library/packs.py` 修改 pack refs。
- `backend/prompt_library/rules.py` 保留具体 rule，避免和 foundation 重复冲突。
- `backend/tests/prompt_library_registry_regression.py`
- `backend/tests/prompt_rule_system_regression.py`

完成标准：

- single-turn、task-execution、observation-followup、graph-node packet 都有 foundation prompt ref。
- prompt diagnostics 能看到 foundation、runtime protocol、agent role 分层。
- foundation 不包含 cwd、用户消息、工具列表、AGENTS 内容等动态内容。
- developer-style prompt lint 仍通过。

### Phase 2：受控 project instructions 通道

目标：

- 实现 scoped `AGENTS.md` 发现和注入。
- 保持 `AGENTS.md` 不进入 static context / long-term memory。
- 项目指令进入 session/task stable section，并带 scope/hash/mtime 诊断。

涉及文件：

- `backend/harness/runtime/project_instructions.py` 新增。
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/prompt_segment_plan.py`
- `backend/memory_system/static_loader.py` 保持不加载。
- `backend/prompting/long_term_context.py` 保持不提升。
- `backend/tests/static_agents_context_regression.py`
- `backend/tests/project_instructions_runtime_regression.py` 新增。

完成标准：

- root `AGENTS.md` 在 runtime packet 中作为 project instruction section 出现。
- 子目录 `AGENTS.md` 只对作用域内目标路径生效。
- 更深层规则覆盖浅层同类规则。
- 修改 `AGENTS.md` 只打破对应 session/task stable cache，不影响 global static。
- prompt manifest 记录 instruction paths、hash、scope_root、applies_to。

### Phase 3：工具级 prompt resource

目标：

- 为核心工具补齐工具级行为协议。
- `prompt_exposure_policy` 从 schema-only 扩展为可诊断策略。
- 将工具 guidance 装配到 tool index stable section。

涉及文件：

- `backend/prompt_library/tool_prompts.py` 新增。
- `backend/capability_system/tools/contracts.py`
- `backend/capability_system/tools/native_tool_catalog.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/tool_plan.py`
- `backend/tests/prompt_tool_visibility_regression.py`
- `backend/tests/tool_prompt_guidance_regression.py` 新增。

第一批工具：

- read_file
- edit_file
- write_file
- terminal
- git read/write tools
- agent_todo
- subagent control tools
- browser_control
- web_search/fetch_url

完成标准：

- 只有可见工具的 guidance 进入 prompt。
- 不可见工具 guidance 不泄露。
- terminal guidance 明确 PowerShell、本项目固定端口、不要用 shell 替代专用文件工具。
- edit/write guidance 强制读前置和最小编辑。
- subagent guidance 强制 brief、等待、不能预测结果。
- todo guidance 明确状态规则和非事实来源。

### Phase 4：计划模式一等协议

目标：

- 将“大改动先写计划书并等待用户确认”从外部协作规则升级为 runtime 可见协议。
- 新增 EnterPlan/ExitPlan 或等价 action contract。
- 计划被批准后形成 implementation lock，后续 TaskRun 按计划实施；偏离计划需要重新确认。

涉及文件：

- `backend/harness/runtime/compiler.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/task_lifecycle.py`
- `backend/runtime/shared/models.py`
- `backend/api/orchestration_harness.py`
- `backend/prompt_library/packs.py`
- `backend/prompt_library/rules.py`
- `backend/tests/harness_runtime_facade_regression.py`
- `backend/tests/plan_mode_protocol_regression.py` 新增。

完成标准：

- 非 trivial 大改动可进入 plan mode。
- plan mode 只允许探索、读取、写计划书或询问，不允许直接实施。
- ExitPlan 会请求用户批准计划。
- 用户批准后创建或更新 TaskRunContract，并记录 plan_ref。
- 实施中发现重大偏差会 block/ask_user，而不是静默改变方案。

### Phase 5：worker prompt 纳入 prompt_library

目标：

- 将 worker blueprints 的 description 升级为版本化 prompt resources。
- 每类 worker 有清晰角色、输入、禁止事项、输出格式、失败处理和工具边界。
- worker prompt 与 runtime profile、allowed operations、blocked operations 一致。

涉及文件：

- `backend/prompt_library/worker_prompts.py` 新增。
- `backend/agent_system/registry/worker_agent_factory.py`
- `backend/agent_system/registry/worker_agent_blueprints.py`
- `backend/harness/runtime/compiler.py`
- `backend/tests/worker_prompt_registry_regression.py` 新增。

完成标准：

- explorer 是只读搜索 agent，不写文件、不创建临时文件、不做最终裁决。
- planner 是只读方案 agent，不实施。
- execution/code executor 只做边界明确的局部实现。
- review 是 bug-first code review，不修改文件。
- verification 是证据驱动验证，不确认式背书。
- worker prompt ref、runtime profile、operation allowlist 三者一致可诊断。

### Phase 6：verification gate 强化

目标：

- 非 trivial coding TaskRun 完成前可触发 verification worker。
- verification 输出必须包含真实命令/请求/浏览器证据和 verdict。
- verification worker 严禁修改项目文件。

涉及文件：

- `backend/prompt_library/worker_prompts.py`
- `backend/harness/loop/task_executor.py`
- `backend/harness/loop/task_lifecycle.py`
- `backend/agent_system/registry/worker_agent_factory.py`
- `backend/tests/verification_agent_regression.py` 新增。

完成标准：

- verification worker 接收 original task、changed files、approach、plan_ref、required verifications。
- 每个检查包含 command/request、observed output、result。
- 必须包含至少一个对抗性 probe，除非任务类型不适用并说明。
- verdict 只能是 PASS、FAIL、PARTIAL。
- FAIL/PARTIAL 阻止 TaskRun 自动宣称完成。

### Phase 7：cache、manifest 和 diagnostics 收敛

目标：

- 显式区分 global static、static environment、session memoized、task stable、volatile。
- volatile section 需要 reason。
- prompt manifest 可解释每段来源、权威、cache tier、hash 和 rejection。

涉及文件：

- `backend/harness/runtime/prompt_segment_plan.py`
- `backend/harness/runtime/compiler.py`
- `backend/prompt_library/rules.py`
- `backend/tests/prompt_cache_prefix_tier_regression.py`
- `backend/tests/prompt_accounting_ledger_test.py`
- `backend/tests/dynamic_prompt_context_projection_test.py`

完成标准：

- 动态 user/task state 不能进入 stable segment。
- project instruction 修改只影响对应 session/task segment。
- tool guidance 变化影响 tool_index_stable，不影响 foundation。
- selected skill body、MCP delta、memory projection 和 tool result refs 的 cache tier 有明确诊断。
- diagnostics 能指出缺失 foundation、缺失 tool guidance、cache tier mismatch、invocation mismatch。

## 9. 文件级执行清单

新增：

- `backend/prompt_library/system_prompts.py`
- `backend/prompt_library/tool_prompts.py`
- `backend/prompt_library/worker_prompts.py`
- `backend/harness/runtime/project_instructions.py`
- `backend/harness/runtime/dynamic_context/manager.py`
- `backend/tests/project_instructions_runtime_regression.py`
- `backend/tests/tool_prompt_guidance_regression.py`
- `backend/tests/plan_mode_protocol_regression.py`
- `backend/tests/worker_prompt_registry_regression.py`
- `backend/tests/verification_agent_regression.py`

修改：

- `backend/prompt_library/__init__.py`
- `backend/prompt_library/packs.py`
- `backend/prompt_library/rules.py`
- `backend/prompt_library/agent_prompts.py`
- `backend/capability_system/tools/contracts.py`
- `backend/capability_system/tools/native_tool_catalog.py`
- `backend/harness/runtime/compiler.py`
- `backend/harness/runtime/tool_plan.py`
- `backend/harness/runtime/prompt_segment_plan.py`
- `backend/harness/loop/single_agent_turn.py`
- `backend/harness/loop/task_lifecycle.py`
- `backend/harness/loop/task_executor.py`
- `backend/agent_system/registry/worker_agent_factory.py`
- `backend/agent_system/registry/worker_agent_blueprints.py`

保留但加测试约束：

- `backend/tests/static_agents_context_regression.py` 必须继续证明 `AGENTS.md` 不进入 static/long-term context。

清理：

- 删除重复、旧版、只靠自然语言兜底的 prompt 分支。
- 删除无条件并行的提示文案。
- 删除 worker blueprint 中与 prompt_library 重复且可能漂移的长描述，保留 prompt_ref 和 registry metadata。
- 删除为了兼容旧 prompt 装配保留的 fallback 路径，除非存在明确外部契约和删除期限。

## 10. 验证矩阵

Prompt assembly：

- single-turn packet 包含 foundation、runtime protocol、environment、project instructions、agent role、tool guidance、dynamic projection。
- task-execution packet 包含 foundation、task protocol、TaskRunContract、artifact scope、tool guidance、volatile task state。
- graph-node packet 不混入 main turn active work。
- observation-followup packet 不丢失 observation failure rule。
- selected skill body 只在已选择或合同绑定时出现，未选择 skill 只显示候选卡片。
- MCP instruction delta 和 memory projection 不进入 global static。

Project instructions：

- root `AGENTS.md` 可见。
- nested `AGENTS.md` 按目标路径覆盖。
- `AGENTS.md` 不进入 long-term context。
- 文件变更触发 session/task stable cache key 变化。

Tool guidance：

- read/edit/write guidance 只在对应工具可见时出现。
- terminal guidance 明确 PowerShell 规则和专用工具优先。
- git write guidance 不在仅 git read 可见时注入。
- hidden/python_repl 等不可见工具 guidance 不泄露。

Plan mode：

- 跨核心模块修改触发 plan mode 或 request_task_run contract 中的 plan requirement。
- plan mode 下写入实现被拒绝。
- ExitPlan 后等待用户批准。
- 批准后实施使用 plan_ref。

Worker/verification：

- explorer 尝试写文件被拒绝。
- planner 尝试 edit_file 被拒绝。
- verification 输出缺 command evidence 时被拒绝或标记 invalid。
- verification FAIL 时 TaskRun 不得 respond 完成。

Concurrency prompt：

- prompt 不再承诺所有普通工具并行。
- 多工具调用文案与 ToolBatchPlan 一致。
- TaskRun execution prompt 不承诺 batch tool call。

Prompt injection：

- 外部网页、文件内容、tool result 中的“忽略系统规则”等文本不会改变系统/项目/工具规则。
- MCP/tool result/skill body 中的外部指令只能作为对应能力说明或数据，不能提升为系统规则。
- project instruction 与当前用户指令冲突时，按 authority 和 scope 诊断。

## 11. 风险和控制

主要风险：

- foundation prompt 与现有 runtime/agent prompt 重复，导致冗长和冲突。
- tool guidance 注入过多，增加 token 成本。
- project instruction 引入后 cache key 变动频繁。
- plan mode 过度触发，降低执行效率。
- worker prompt 和 runtime profile 漂移。
- verification gate 过重，阻塞简单任务。

控制方式：

- foundation 只放不变量，具体工具和动作格式下沉到 tool/runtime prompt。
- 工具 guidance 只随可见工具注入，并做短版/完整版策略。
- project instruction 用 hash/mtime 和 scope 控制 cache break。
- plan mode 只对高影响、架构不确定、跨模块、协议/DB/runtime 改动触发；普通明确实现直接做。
- worker prompt resource 与 allowed/blocked operations 同源生成 diagnostics。
- verification gate 根据风险分级触发，trivial 任务不强制。

## 12. 不允许的实现方式

- 不允许把所有规则塞进一个长 system prompt。
- 不允许把 `AGENTS.md` 放进长期记忆或 static context。
- 不允许只靠 tool schema description 承担 Read/Edit/Write/Terminal 的行为协议。
- 不允许用旧 prompt fallback 兼容新 prompt，导致新旧链路并存。
- 不允许继续在 prompt 中承诺无条件并行工具执行。
- 不允许把 TaskRun execution prompt 用来处理普通 TurnRun。
- 不允许把 graph/task_system 业务任务入口改写成 bare `execute_task_run`。
- 不允许为了让验证通过而跳过测试、弱化断言、mock 核心逻辑或伪造结果。

## 13. 最终目标

完成后，本项目的 prompt 体系应达到以下状态：

- agent 一进入 coding 环境，就具备接近 Codex/Claude Code 成熟 coding agent 的行为不变量。
- 系统 prompt、runtime protocol、项目指令、工具说明、worker prompt 和动态状态各有明确权威层。
- TurnRun 和 TaskRun 使用不同 prompt 合同，职责不会混淆。
- 工具调用行为由工具 prompt 和 runtime control plane 共同约束。
- 大改动有计划模式和用户批准闭环。
- verification 不再是“看起来通过”，而是有命令、输出、probe 和 verdict 的证据链。
- prompt manifest 能解释每一段内容为什么出现、来自哪里、作用于什么 invocation、是否可缓存。
- 旧 prompt 残留和重复链路被清理，新体系不靠兼容旧壳维持。
