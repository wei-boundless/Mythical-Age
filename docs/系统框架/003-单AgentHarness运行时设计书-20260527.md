# 单 Agent Harness 成熟架构对照设计书

日期：2026-05-27

状态：重写锁定稿

适用范围：

```text
backend/agent_runtime
backend/harness/runtime
backend/harness/loop
backend/task_system/tasks
backend/task_system/planning
backend/query/runtime.py
```

本设计书用于后续重构。它不是旧结构上的补丁说明，也不是给旧接口找兼容理由。所有结构必须逐层对标成熟 coding agent 的设计理念和工程实践。凡是不能通过本设计书权威审查的旧链路，应删除、合并或重建。

## 0. 结论先行

本项目的单 Agent Harness 不应有系统侧意图识别层，不应有系统侧任务原语选择层，不应由系统从 `action_intent`、`professional_mode`、`selected_task_id`、`runtime_lane` 或用户关键词推导是否开启 TaskRun。

成熟设计的主链固定为：

```text
User Input
-> System assembles runtime for this invocation
-> Model receives tools / permissions / context / instructions
-> Model decides and emits action through real action interface
-> System validates the action request
-> System authorizes tool / file / shell / browser / task lifecycle
-> System executes and records observations / receipts
-> Model sees observations in the next invocation
-> Model continues, repairs, asks user, verifies, or finalizes
-> System performs artifact and acceptance gates where required
-> User-facing final answer is emitted without leaking control internals
```

这条链路的关键不是“系统先理解任务”，而是“系统每次调用前装配运行时，让 agent 在运行时中理解并行动”。

## 1. 成熟 Agent 对照基准

### 1.1 Claude Code 可见源码结论

已检查本地源码：

```text
D:\AI应用\claude-code-nb-main\query.ts
D:\AI应用\claude-code-nb-main\Tool.ts
D:\AI应用\claude-code-nb-main\constants\prompts.ts
D:\AI应用\claude-code-nb-main\tools\EnterPlanModeTool
D:\AI应用\claude-code-nb-main\tools\ExitPlanModeTool
D:\AI应用\claude-code-nb-main\tools\AgentTool
```

可确认的工程事实：

| 成熟结构 | Claude Code 证据 | 设计含义 |
| --- | --- | --- |
| 主 loop 由模型输出驱动 | `query.ts` 中 `queryLoop` 收集 `tool_use`，执行 `runTools`，把 `toolResults` 追加回 messages 后继续下一轮 | 不存在系统侧先分类任务再执行的独立意图识别器 |
| 行动通过工具/模式表达 | `tool_use` 是 loop 是否继续的核心信号 | 模型行动接口就是工具调用、模式工具、用户询问、最终回答 |
| 权限是运行时结构 | `ToolPermissionContext` 包含 mode、allow/deny/ask rules、prePlanMode 等 | 权限不能写成 prompt 建议，必须是执行前门禁 |
| 工具默认保守 | `buildTool` 默认 `isConcurrencySafe=false`、`isReadOnly=false` | 系统不能乐观假设工具安全或只读 |
| Plan mode 是工具和权限状态 | `EnterPlanModeTool` 修改 permission mode 为 `plan`，返回只读计划要求 | 计划不是 task type，不是旧专业模式；它是模型主动进入的受控工作模式 |
| ExitPlanMode 是审批出口 | `ExitPlanModeTool` 要求计划写入指定文件后再请求审批 | 计划完成必须有明确出口，不是普通 ask_user |
| Subagent 是 AgentTool 调用 | `AgentTool` 用 `whenToUse` 暴露 agent 能力，并重新装配子 agent | 子 agent 不是新 runtime；是另一次 agent invocation |
| Verification 是独立 agent | verification agent 要求 `VERDICT: PASS/FAIL/PARTIAL` | 验收要有反证和证据，不由主 agent 自我声称代替 |

### 1.2 Claude Code 源码级控制细节

以下细节不是框架口号，而是可以直接约束本项目实现的工程机制：

| 源码细节 | 解决的控制问题 | 本项目实现要求 |
| --- | --- | --- |
| `query.ts` 不信任 `stop_reason=tool_use`，而是以实际收到的 `tool_use` block 作为继续循环信号 | 避免服务端元信息不稳定导致 loop 误停或误跑 | `AgentLoop` 只能以结构化 `ModelActionRequest` / observation / lifecycle record 推进，不得以自然语言或弱标记推进 |
| `yieldMissingToolResultBlocks()` 为异常路径补齐 tool result | 防止 orphan tool_use 进入下一次模型调用 | 系统一旦接受 action，就必须产出 `ObservationRecord`、`TaskLifecycleRecord`、`error` 或 `canceled`，禁止静默断链 |
| 恢复时按 `tool_use_id` 去重，不按 message id 去重 | 流式消息可能共享 message id，按 message 去重会重复执行或孤立结果 | 所有可执行 action 必须有稳定 `request_id/action_id`，恢复与重试按 action id 幂等 |
| streaming fallback 会 tombstone 半截 assistant message，并 discard 旧 executor | 防止旧 tool_use_id 的结果污染新模型响应 | 模型重试、fallback、恢复必须清空未闭合 action 上下文，不能把半成品 observation 回灌 |
| `Tool` 默认 `isConcurrencySafe=false`、`isReadOnly=false` | 未声明安全的工具按不安全处理 | 工具准入只认显式能力元数据；不得靠工具名、关键词或乐观默认放行 |
| 权限链顺序固定：deny/ask rule -> tool-specific check -> safety check -> mode/allow rule | 防止 bypass/模式覆盖安全裁决 | `AdmissionDecision` 必须先 fail-closed，再处理模式放行；安全和显式 deny 永远优先 |
| async subagent 使用独立 AbortController，sync subagent 共享 parent controller | 区分后台长期任务和当前 turn 同步任务的取消语义 | `TaskRun` 必须区分前台绑定运行和后台独立运行；取消传播要明确 |
| 子 agent 重新装配权限，只保留明确外部授权，不继承父 session 临时规则 | 防止委派越权 | 每个 TaskRun / 子 invocation 都重新装配 runtime，不继承未声明的父级权限 |
| fork/resume 前过滤 incomplete tool calls | 防止恢复上下文带入半截 action | resume/compact 前必须执行 protocol sanitation，移除或闭合未完成 action |
| 子 agent 空输出时显式返回“completed but no output” | 防止父 agent 误判没有事件发生 | TaskRun 完成必须有可读 completion result、artifact verdict 或 failure reason，禁止无消息完成 |
| TodoWrite 完成多个任务但缺少 verification 时返回验证提醒 | 任务关闭前触发质量门禁 | todo/task lifecycle 可以有结构化自审提醒，但必须基于任务状态，不基于用户关键词 |
| compact agent 禁止工具调用、可被 abort、恢复指令要求直接继续 | 压缩只保存继续执行所需事实，不改变任务裁决权 | 长任务续跑摘要是恢复输入，不是重新决策；恢复后必须从最新用户请求和任务状态继续 |

### 1.2 Codex 类成熟 Coding Agent 的可执行标准

本项目对标的是成熟 coding agent 的行为标准：

```text
读代码前不臆断。
执行前装配工具、权限、上下文。
模型自己判断是否需要读、改、测、问、计划或收尾。
工具结果回灌后继续判断。
修改必须绑定真实文件和真实验证。
长任务必须能暂停、恢复、修复和最终验收。
用户看见的是进展和结果，不是内部 task id / hidden reasoning。
```

这里不引入一个“系统侧任务识别器”来模拟 agent 的判断。成熟 agent 的判断能力属于模型本体；系统要做的是把环境、工具、权限和证据链做成可审计的运行时。

## 2. 不可妥协设计原则

### 2.1 系统不拥有语义任务判断权

系统可以：

```text
接收用户输入。
记录可观察事实。
装配当前 runtime。
暴露工具、权限、上下文、artifact、prompt pack。
校验模型行动请求是否合规。
执行授权动作。
记录 observation 和 receipt。
执行 artifact / acceptance gate。
```

系统不可以：

```text
用关键词识别任务。
用 action_intent 决定 TaskRun。
用 professional_mode 强制 TaskRun。
用 selected_task_id 自动填 task_goal_type。
用 runtime_lane 反推用户目标。
把 bounded observation 静默升级成长任务。
```

### 2.2 Agent 拥有理解和行动选择权

agent 必须在当前 invocation runtime 中判断：

```text
直接回答。
请求工具观察。
进入计划。
请求正式 TaskRun。
继续当前任务。
修复或重做前序步骤。
询问用户。
阻止或拒绝。
最终回答。
```

这些选择不得由系统前置替代。若后端需要结构化记录，只能记录 agent 已经发出的行动请求，不能把记录字段设计成系统先验分类器。

### 2.3 每次模型调用都必须装配 runtime

成熟 agent 的核心不是“一次装配后不断复用 prompt”，而是每次模型调用前重新装配：

```text
当前消息窗口
当前工具表
当前权限快照
当前文件/工作区视图
当前 memory view
当前 observation refs
当前 artifact refs
当前 task/step/plan/repair 状态
当前输出契约
当前停止条件和预算
```

任何直接 raw `invoke_messages`、任何 follow-up 复用旧消息而不重新编译 invocation packet，都是不成熟实现。

### 2.4 工具、模式、子 agent 是行动接口，不是任务原语分类器

本项目不建立“大任务原语表”让系统选择。可以建立的是模型可见能力接口：

```text
工具能力：read/search/edit/shell/browser/artifact/delegate
模式能力：plan / approval / repair / verification
用户交互能力：ask_user
任务生命周期能力：request_task_run / pause / resume / abort
```

这些能力必须通过 runtime 装配暴露给 agent，由 agent 选择使用。系统只校验该能力在当前环境是否可用、权限是否满足、请求是否完整。

### 2.5 TaskRun 是生命周期，不是执行默认值

TaskRun 只在 agent 显式请求正式任务生命周期，或外部已提交明确 TaskRun 合同并经过 admission 时开启。

TaskRun 适用于：

```text
多步骤执行
写入工作区
真实 artifact 交付
命令或浏览器验证
长期续跑
checkpoint/resume
repair/replan
final acceptance
```

TaskRun 不适用于：

```text
普通问答
纯解释
短只读观察
一次性上下文读取
轻量搜索后回答
因为 professional_mode 看起来更专业
```

### 2.6 计划和修复必须由 agent 基于真实观察触发

计划不是系统脚手架生成的步骤列表。成熟设计要求：

```text
agent 读到真实上下文后制定计划。
系统记录计划文件或 PlanRecord。
执行中出现失败或新事实时，agent 产出 revision / repair / invalidation。
系统校验是否改变合同、是否越权、是否需要用户确认。
```

### 2.7 Artifact 和验收必须是真实门禁

长期任务完成必须绑定真实 artifact、真实 receipt、真实验收记录。

禁止：

```text
用最终自然语言补完成 step。
用文件存在直接代表任务达成。
用 self-review 代替系统 acceptance。
用 finalizer 补账让 ledger 变绿。
```

## 3. 当前项目结构审查

### 3.1 QueryRuntime

当前文件：

```text
backend/query/runtime.py
```

当前职责：

```text
接收 API 输入。
提交用户消息。
构造 turn_id / task_id。
调用 AgentTurnController。
提交 assistant final message。
```

成熟对照：

```text
QueryRuntime 应是 API adapter。
它不应拥有任务理解、工具路由、TaskRun admission 或恢复主权。
```

当前偏差：

```text
task_id 仍在普通 turn 入口生成。
task_id 容易让普通 turn 被理解成任务实例。
```

目标规则：

```text
普通 turn 只应生成 turn_id / invocation_id。
TaskRun id 只能在 TaskRun admission 接受后由系统生成。
QueryRuntime 不得从 task_selection 推断任务语义。
```

### 3.2 AgentTurnController

当前文件：

```text
backend/agent_runtime/turn_controller.py
```

当前职责：

```text
build_request_facts
build_boundary_policy
build_context_candidates
main_model_owned_turn_decision
execution_decision_from_model_turn
build_action_permit
direct answer 或 launch TaskRun
```

成熟对照：

```text
成熟 loop 不应先让系统建立 facts/boundary/context candidates 再把它当成意图管线。
正确做法是 Runtime Compiler 为本次模型调用装配 runtime packet。
模型在 packet 内理解并通过行动接口表达下一步。
```

当前偏差：

```text
ModelTurnDecision 像系统侧理解节点。
ExecutionDecision 从 action_intent 推出 execution_mode。
direct_answer 直接 raw invoke_messages，绕过 Runtime Compiler。
TaskRun 由 ExecutionDecision 静默启动。
```

必须删除或重建：

```text
execution_decision_from_model_turn 中 action_intent -> task_run 的映射。
AgentTurnController._invoke_direct_answer 的 raw messages 路径。
普通 turn 阶段的 task_goal_type 要求。
系统从 needs_clarification/action_intent 推出最终控制分支的设计。
```

目标规则：

```text
AgentTurnController 降级为 TurnLoop 入口，不再是理解管线。
第一次模型调用也必须走 RuntimeInvocationPacket。
模型输出可以是 final answer、tool_use、ask_user、enter_plan、request_task_run、block。
系统只校验模型输出是否属于当前 runtime 暴露的行动接口。
```

### 3.3 ModelTurnDecision

当前文件：

```text
backend/agent_runtime/understanding/model_turn_decision.py
backend/agent_runtime/understanding/model_turn_decision_runtime.py
```

成熟对照：

```text
成熟 coding agent 没有独立系统侧 intent classifier。
模型任务理解发生在主模型调用中，并通过工具/行动输出表达。
```

当前偏差：

```text
interaction_intent / action_intent / work_mode 枚举看似由模型输出，但系统把它当控制事实。
task_goal_type 出现在普通 turn understanding 阶段。
prompt 要求模型先输出 JSON 决策，再由系统执行。
```

目标规则：

```text
删除“ModelTurnDecision 作为独立入口控制层”的生产主权。
保留时只能作为 observation/diagnostic 或旧迁移对象，不参与是否 TaskRun 的控制。
如果需要结构化模型输出，应改为 Runtime Action Request，由模型在实际调用中产出。
```

### 3.4 ExecutionDecision

当前文件：

```text
backend/agent_runtime/execution_decision.py
```

成熟对照：

```text
执行决策不能由系统从 action_intent 二次推断。
成熟 agent 的行动应来自模型 tool_use / action request 本身。
```

当前严重偏差：

```text
read_context
search_external
use_browser
edit_workspace
run_command
start_service
delegate
```

都会被映射为 `task_run`。

这是系统侧静默升级，必须删除。

目标规则：

```text
ExecutionDecision 不再作为独立控制层。
如果保留名称，应只表示 AdmissionDecision：对模型已发出的 action request 做 allow/deny/ask/invalid。
```

### 3.5 Harness Runtime Assembly

当前文件：

```text
backend/harness/runtime/start_packet.py
backend/harness/runtime/turn_context.py
backend/harness/runtime/agent_assembly.py
```

成熟对照：

```text
Runtime 是每次模型调用前的装配器。
它不应重新理解任务，也不应持有旧 start packet 一跑到底。
```

当前偏差：

```text
RuntimeStartPacket 仍围绕 request_facts/boundary/context/model_turn_decision/action_permit。
build_agent_turn_context 在 TaskRun 入口仍可调用 main_model_owned_turn_decision。
RuntimeStartPacket 不是真正的 per-invocation packet。
```

目标规则：

```text
RuntimeStartPacket 更名或替换为 RuntimeInvocationPacket。
每次 agent 调用、follow-up、self-review、repair、final answer 都由 compiler 生成新 packet。
TaskRun 入口只消费已接受的 TaskRunContract，不重新理解用户意图。
```

### 3.6 Agent Loop

当前文件：

```text
backend/harness/loop/agent_loop.py
backend/harness/loop/agent_turn_loop.py
backend/harness/loop/agent_model_turn.py
backend/harness/loop/agent_execution/*
```

成熟对照：

```text
loop 的核心是 model output -> tool execution -> observation -> next model call。
loop 不拥有任务语义判断权。
```

当前可保留点：

```text
已有 model/tool follow-up loop。
已有 tool_call_requested 事件翻译。
已有 permission / sandbox / file policy 接入点。
已有 loop control。
```

当前偏差：

```text
follow-up 通过 build_initial_followup_messages / build_next_followup_messages 组装消息，而不是请求 Runtime Compiler 生成新 invocation packet。
agent_loop 在入口调用 build_agent_turn_context，可重新做理解。
TaskRun assembly 与 ordinary turn 的理解/执行界限混在一起。
```

目标规则：

```text
run_agent_turn_loop 每次模型调用前调用 RuntimeCompiler.compile_invocation。
followup_cycle 只能作为 prompt/message fragment helper，不能拥有调用包主权。
agent_loop 只接受 TaskRunContract 或 RuntimeInvocation，不得重新理解用户意图。
```

### 3.7 TaskRun Ledger 和 Finalization

当前文件：

```text
backend/task_system/tasks/run_models.py
backend/harness/loop/agent_finalization.py
backend/task_system/tasks/step_summary.py
```

成熟对照：

```text
TaskRun 是状态机。
step completion 必须来自真实 observation、self-review 和 acceptance。
finalizer 只能提交结果，不能补做执行事实。
```

当前严重偏差：

```text
finalize_runtime_task_run_ledger 会在 terminal finalize 中：
启动 pending model step。
完成 running step。
跳过 allow_unverified_completion step。
用 final_content 补 step result。
```

这属于旧控制残留，必须删除。

目标规则：

```text
StepRun 只能在 loop 执行阶段改变状态。
finalizer 只能读取 ledger 并生成 TaskResult / commit gate。
无 SelfReviewRecord 和 AcceptanceRecord 的 required step 不能 completed。
```

### 3.8 Prompt Library

当前相关文件：

```text
backend/prompt_library/*
backend/harness/runtime/*
```

成熟对照：

```text
prompt 是 runtime packet 的模型可见层。
prompt pack 由环境、工具、权限、调用目的装配。
prompt 不能反向决定任务生命周期。
```

目标规则：

```text
prompt_library 根据 task_environment / agent_profile / invocation_kind / permission_snapshot 选择。
不得根据用户关键词选择 prompt。
不得通过 prompt pack 强制 TaskRun。
prompt 必须写给 agent 理解角色、职责、边界和裁决标准，不能写开发节点说明。
```

### 3.9 模式：role / standard / professional

成熟对照：

```text
模式是 runtime 装配厚度、工具可见范围、验证强度、计划要求和输出契约的配置。
模式不是 loop 架构。
模式不是是否 TaskRun 的判断依据。
```

目标规则：

```text
role_mode <= standard_mode <= professional_mode 表示配置覆盖关系。
role_mode 可以请求 TaskRun。
professional_mode 可以直接回答。
professional_mode 不能强制旧 professional task topology。
```

### 3.10 Explicit Contract / 外部 Task 合同

成熟对照：

```text
外部合同是运行时输入，不是跳过 agent 理解的理由。
agent 仍需要读取合同、判断当前行动、发现冲突并反馈。
```

目标规则：

```text
explicit contract 进入 RuntimeEnvelope / InvocationPacket。
系统校验合同结构和权限。
agent 在 packet 中理解合同和用户当前请求。
不得因为 explicit contract 跳过模型判断。
不得用 selected_task_id 自动填 task_goal_type。
```

## 4. 目标对象模型

### 4.1 RuntimeEnvelope

生命周期边界对象。

```text
authority: harness.runtime.envelope
scope: turn | task_run | step | delegate | graph_node
environment_ref
agent_profile_ref
tool_capability_table_ref
permission_policy_ref
sandbox_policy_ref
file_policy_ref
memory_policy_ref
artifact_policy_ref
prompt_policy_ref
output_policy_ref
budget_policy
approval_policy
recovery_policy
```

成熟对照：

```text
对应 Claude Code 的 userContext/systemContext/toolPermissionContext/enabledTools 等运行时上下文组合。
```

禁止：

```text
包含系统推断的 user_intent。
包含系统选择的 next_action。
包含普通 turn 的 task_goal_type。
```

### 4.2 RuntimeInvocationPacket

每次模型调用唯一输入合同。

```text
authority: harness.runtime.invocation_packet
invocation_id
parent_scope_ref
invocation_kind
model_messages
available_tools
available_modes
permission_snapshot
context_refs
observation_refs
artifact_refs
current_task_contract_ref
current_step_ref
plan_ref
repair_refs
output_contract
stop_conditions
budget_snapshot
user_visible_status_policy
hidden_control_refs
```

成熟对照：

```text
对应 Claude Code 每轮 query 的 messages + tools + permission context + app state。
```

必须满足：

```text
每次模型调用前创建。
每次 tool result 后重新创建。
每次 user revision 后重新创建。
每次 resume 后重新创建。
```

### 4.3 ModelActionRequest

模型行动输出，不是系统意图分类。

允许形态：

```text
final_answer
tool_call
ask_user
enter_plan_mode
exit_plan_mode
request_task_run
delegate_agent
record_plan
revise_plan
repair_step
invalidate_step
self_review
final_review
block
```

成熟对照：

```text
Claude Code 用 tool_use block 表达行动。
本项目可以将同类行动结构化，但必须由模型输出。
```

禁止：

```text
系统从 action_intent 填 ModelActionRequest。
系统从关键词填 request_task_run。
系统替 agent 填 task_goal_type。
```

### 4.4 AdmissionDecision

系统对模型行动请求的校验裁决。

```text
authority: harness.admission
action_request_ref
decision: allow | deny | ask_approval | invalid | needs_contract
permission_delta
contract_errors
resource_errors
user_visible_reason
system_reason
```

成熟对照：

```text
对应 Claude Code canUseTool / checkPermissions / permission mode / approval。
```

禁止：

```text
把 deny 改成另一个可执行动作。
把 invalid action 自动改成 TaskRun。
```

### 4.5 ExecutionContext

系统执行工具、文件、命令、浏览器、artifact 操作前生成。

```text
authority: harness.execution_context
action_request_ref
admission_ref
tool_name / operation_id
workspace_root
sandbox_snapshot
permission_receipt_ref
file_policy_ref
artifact_policy_ref
timeout
idempotency_key
```

禁止：

```text
执行没有 action_request_ref 的工具。
执行没有 admission_ref 的工具。
执行时重写用户目标。
```

### 4.6 ObservationRecord

真实观察记录。

```text
authority: harness.observation
source: model | tool | file | shell | browser | artifact | approval | verifier
action_request_ref
execution_context_ref
receipt_ref
summary
payload_ref
error
timestamp
```

Observation 只记录事实，不裁决完成。

### 4.7 PlanRecord

agent 计划记录。

```text
authority: agent.plan_record
plan_ref
task_contract_ref
created_from_invocation_ref
steps
risks
verification_strategy
artifact_strategy
open_questions
approval_required
```

成熟对照：

```text
对应 Claude Code EnterPlanMode + plan file + ExitPlanMode 审批出口。
```

禁止：

```text
系统脚手架自动生成正式计划。
计划缺失时系统假装有计划继续执行。
```

### 4.8 TaskRunContract

正式长任务合同。

```text
authority: harness.task_run_contract
task_run_goal
contract_source: model_request | external_contract | graph_node
required_artifacts
required_verifications
completion_criteria
resource_requirements
permission_requirements
acceptance_policy
recovery_policy
user_visible_goal
```

`task_goal_type` 如需保留，只能是 TaskRunContract 内部字段，不能出现在普通 turn 决策里作为系统路由依据。

### 4.9 StepRunState

TaskRun 内轻状态机步骤。

状态：

```text
pending
ready
running
waiting_tool
waiting_approval
waiting_user
self_reviewing
repairing
completed
failed
invalidated
skipped_by_contract
```

禁止：

```text
finalizer 启动 step。
finalizer 完成 step。
无 observation/self-review/acceptance 的 completed。
```

### 4.10 SelfReviewRecord

agent 自审记录。

```text
authority: agent.self_review
review_scope: step | repair | final
checked_contract_refs
checked_observation_refs
checked_artifact_refs
verdict: pass | fail | partial | needs_more_observation | needs_repair | ask_user
issues
proposed_followup_request
user_visible_summary
```

Self-review 由独立 invocation 产生。

### 4.11 AcceptanceRecord

系统验收记录。

```text
authority: harness.acceptance
scope: step | task_run | artifact | final
self_review_ref
required_artifact_refs
required_receipt_refs
verification_refs
permission_receipts
approval_receipts
decision: accepted | rejected | partial | repair_required | blocked
reason
```

成熟对照：

```text
对应成熟 coding agent 的测试、验证、artifact 检查、反证 verifier 和最终 gate。
```

### 4.12 UserVisibleStepSummary

用户可见步骤摘要。

```text
authority: agent.user_visible_step_summary
step_ref
what_happened
evidence_summary
status
next_user_visible_status
```

要求：

```text
不暴露 hidden reasoning。
不暴露 task_run_id / invocation_packet_id。
不写“这是 runtime 节点”之类开发说明。
```

## 5. 固定执行流

### 5.1 普通 Turn

```text
1. QueryRuntime receives user input.
2. Harness creates TurnScope.
3. RuntimeCompiler compiles invocation packet.
4. Model is called with tools/modes/context.
5. Model emits final/tool_call/ask_user/enter_plan/request_task_run/block.
6. Harness validates action request.
7. If final: output layer commits final answer.
8. If tool_call: permission -> execution -> observation -> new invocation packet.
9. If request_task_run: TaskRun admission validates contract.
10. If ask_user: user-facing question emitted.
11. If block: fail-closed with user-visible reason.
```

### 5.2 Bounded Observation

```text
1. Model requests one or more bounded tool observations.
2. System checks tool availability and permission.
3. Tool executes and returns ObservationRecord.
4. RuntimeCompiler compiles follow-up packet.
5. Model either answers, asks for more allowed observation, requests TaskRun, or blocks.
```

Bounded observation 不创建 TaskRun。

### 5.3 Plan Mode

```text
1. Model emits enter_plan_mode.
2. System switches permission snapshot to read-only planning mode.
3. RuntimeCompiler compiles planning packet.
4. Model explores and writes PlanRecord or plan artifact when allowed.
5. Model emits exit_plan_mode.
6. System requests approval if required.
7. After approval, model may request_task_run or continue bounded answer.
```

Plan mode 是可进入、可退出、可审批的模式，不是 professional_mode 的旧别名。

### 5.4 TaskRun Admission

```text
1. Model emits request_task_run with proposed TaskRunContract.
2. System validates contract completeness.
3. System validates permissions and environment limits.
4. System creates task_run_id only after admission accepted.
5. RuntimeEnvelope for TaskRun is created.
6. AgentLoop enters TaskRun lifecycle.
```

禁止：

```text
在 admission 前生成用户可见 task_run_id。
系统补 task_goal_type。
系统因为 read_context 启动 TaskRun。
```

### 5.5 TaskRun Loop

```text
1. RuntimeCompiler compiles step/action packet.
2. Model acts.
3. System validates and executes tools.
4. ObservationRecord written.
5. RuntimeCompiler compiles follow-up packet.
6. Model continues or emits self_review.
7. SelfReviewRecord produced.
8. System AcceptanceRecord checks evidence.
9. Step advances only after acceptance.
10. Loop continues until final review and final acceptance.
```

### 5.6 用户中途修改

```text
1. UserRevisionInput is received.
2. Current TaskRun pauses at safe boundary.
3. RuntimeCompiler compiles user_revision_triage packet.
4. Agent decides:
   apply_to_current_step
   revise_plan
   revise_contract
   split_new_task
   ask_user
   reject_as_conflict
   abort_current
5. System validates whether contract or permissions change.
6. If accepted, affected steps/artifacts are invalidated.
7. Repair or replan proceeds through normal loop.
```

系统不能把用户修改当普通聊天忽略，也不能直接改写 TaskRun 合同。

### 5.7 Agent 发现自己错了

```text
1. Problem observed from tool/test/browser/self-review/verifier.
2. RuntimeCompiler compiles step_invalidation_review packet.
3. Agent identifies affected steps, artifacts, assumptions, contract refs.
4. System records StepInvalidationRecord.
5. RuntimeCompiler compiles repair_action packet.
6. Agent repairs.
7. System executes and records new observations.
8. Agent self-reviews repair.
9. System acceptance gate decides whether repaired state is valid.
```

禁止：

```text
继续按旧计划硬跑。
系统自动重排计划。
finalizer 用最终回答掩盖前序错误。
```

### 5.8 Resume / 自动续跑

```text
1. System loads checkpoint, ledger, observations, artifacts, pending approvals.
2. RuntimeCompiler compiles resume_safety_review packet.
3. Agent checks whether state is safe to continue.
4. System validates no stale permission/tool/context is reused.
5. Loop resumes at recorded state or enters repair/ask_user/block.
```

禁止：

```text
恢复时复用旧 invocation packet。
恢复时重跑已完成工具造成重复副作用。
恢复层覆盖当前用户输入。
```

## 6. Prompt 设计标准

### 6.1 Prompt 是 invocation packet 的模型可见层

每个 prompt 必须回答：

```text
你是谁？
你现在负责什么？
你不能做什么？
你能请求哪些行动？
你必须基于哪些 evidence / artifact / contract 作判断？
你输出给系统的结构是什么？
你给用户看的内容边界是什么？
```

禁止开发说明式 prompt：

```text
这是 runtime 节点。
根据任务图执行 world_review。
这个节点用于校验资产。
```

应写成 agent 可理解的职责语言：

```text
你是一名交付验收员。
你只负责判断当前交付物是否真实存在、是否被验证、是否满足用户请求。
你不能替执行 agent 扩写成果。
你必须指出证据缺口，并给出 pass、partial、repair_required 或 fail。
```

### 6.2 通用 prompt pack

必须建立这些 invocation prompt，而不是一个总 prompt 复用到底：

```text
turn_action
tool_observation_followup
enter_plan_mode
plan_review
request_task_run
task_step_action
step_self_review
user_revision_triage
step_invalidation_review
repair_action
repair_self_review
final_self_review
final_acceptance_summary
resume_safety_review
final_user_answer
```

这些 prompt 的选择由 environment/profile/invocation_kind 装配，不由用户关键词选择。

## 7. 权限和工具设计标准

### 7.1 ToolCapabilityTable

RuntimeCompiler 每次调用前生成工具表：

```text
tool_name
description_for_agent
input_schema
read_only
destructive
requires_approval
requires_task_run
allowed_in_plan_mode
allowed_in_bounded_turn
allowed_in_task_run
permission_policy_ref
```

成熟对照：

```text
Claude Code 工具通过 schema/prompt/permission 暴露给模型。
工具是否可用由当前 tool permission context 决定。
```

### 7.2 工具调用门禁

```text
Model tool_call
-> schema validation
-> permission decision
-> approval if needed
-> execution context compile
-> execution
-> receipt
-> observation
```

任何工具调用缺一环都必须 fail closed。

## 8. Artifact 和验收设计标准

### 8.1 ArtifactContract

TaskRunContract 中需要真实交付物时，必须定义：

```text
artifact_kind
expected_paths_or_refs
creation_allowed
modification_allowed
validation_method
required_receipts
user_visible_name
```

### 8.2 ArtifactValidation

系统验收至少检查：

```text
文件是否存在。
是否由当前 TaskRun 写入或引用。
是否满足路径和类型要求。
是否有必要的命令/浏览器/测试 receipt。
是否被 self-review 引用。
```

禁止：

```text
只因 final answer 提到路径就判定 artifact 存在。
```

## 9. 输出和用户可见状态

### 9.1 用户不关心内部 ID

最终回答和步骤状态不得暴露：

```text
task_run_id
invocation_packet_id
directive_ref
hidden reasoning
internal authority strings
raw ledger dumps
```

### 9.2 步骤摘要

成熟 agent 可以有每步简短摘要，但摘要应该是用户可见的工作进展，不是内部 JSON 字段。

正确内容：

```text
我已经检查了 harness 入口，发现 TaskRun 是由 action_intent 静默触发的。
接下来我会审查 follow-up loop 是否重新编译 runtime packet。
```

错误内容：

```text
reasoning_summary: 简短说明，不暴露隐藏推理
user_visible_status: 我将先检查相关代码再判断是否需要修改
task_run_id: xxx
```

## 10. 删除清单

后续实现必须删除或重建：

```text
backend/agent_runtime/execution_decision.py 中 action_intent -> task_run 映射
backend/agent_runtime/understanding/model_turn_decision* 的生产控制主权
backend/agent_runtime/turn_controller.py 中 raw direct answer invoke
backend/harness/runtime/turn_context.py 中 TaskRun 入口重新理解用户的路径
backend/harness/runtime/start_packet.py 的旧 RuntimeStartPacket 语义
backend/harness/loop/agent_turn_loop.py 中 follow-up 绕过 RuntimeCompiler 的调用方式
backend/harness/loop/agent_finalization.py 中 terminal_finalize 补 step 逻辑
backend/task_system/tasks/run_models.py 中允许无 acceptance 完成 required step 的路径
保护旧 execution_mode / professional topology / terminal_finalize 的测试
```

删除原则：

```text
不保留兼容分支。
不保留旧链路作为 fallback。
不在旧壳上加新字段。
如果旧测试只保护旧内部形状，删除并改写为成熟行为测试。
```

## 11. 目标文件结构

目标新增或重建：

```text
backend/harness/runtime/envelope.py
backend/harness/runtime/invocation_packet.py
backend/harness/runtime/compiler.py
backend/harness/runtime/tool_capability_table.py
backend/harness/runtime/execution_context.py
backend/harness/loop/agent_loop_controller.py
backend/harness/loop/model_action_protocol.py
backend/harness/loop/admission.py
backend/harness/loop/observation_records.py
backend/harness/loop/plan_records.py
backend/harness/loop/task_run_contract.py
backend/harness/loop/self_review.py
backend/harness/loop/acceptance.py
backend/harness/loop/recovery.py
backend/harness/loop/user_visible_status.py
```

目标删除或降权：

```text
backend/agent_runtime/understanding
backend/agent_runtime/execution_decision.py
backend/harness/runtime/turn_context.py
backend/harness/runtime/start_packet.py
```

如果迁移期间暂时保留，必须不可被生产入口调用，并有删除测试。

## 12. 验证矩阵

### 12.1 普通 turn

```text
用户问解释性问题。
系统编译 invocation packet。
模型 final answer。
不生成 TaskRun。
不生成 task_goal_type。
不暴露内部 ID。
```

### 12.2 只读观察

```text
用户要求检查文件或目录后回答。
模型请求 read/search tool。
系统执行并记录 observation。
follow-up 前重新编译 packet。
模型回答。
不创建 TaskRun。
```

### 12.3 写入任务

```text
用户要求修改代码并测试。
模型请求 TaskRun。
admission 验证 artifact/verification/permission 合同。
TaskRun 创建。
步骤执行、观察、自审、验收全部记录。
```

### 12.4 professional_mode

```text
professional_mode 下用户问普通问题。
agent 可直接回答。
不得强制 TaskRun。
professional_mode 下写入任务可使用更强 plan/review/verification prompt pack。
```

### 12.5 用户中途修改

```text
TaskRun running 时收到用户修改。
loop 暂停。
agent revision triage。
系统按裁决更新合同或拆新任务。
受影响 step/artifact invalidated。
```

### 12.6 失败恢复

```text
测试失败。
agent step_invalidation_review。
repair_action。
repair_self_review。
acceptance gate。
最终回答包含真实失败或修复结果。
```

### 12.7 Finalizer

```text
finalizer 不得启动 pending step。
finalizer 不得完成 running step。
finalizer 不得跳过 required step。
只有已验收 ledger 可提交 TaskResult。
```

## 13. 实施阶段

### 阶段一：权威删除

目标：

```text
删除系统侧意图识别和 action_intent -> execution_mode 控制。
普通 turn 由 RuntimeInvocationPacket + model action 输出驱动。
```

完成标准：

```text
rg "execution_decision_from_model_turn" backend 不能命中生产入口。
read_context/search_external/use_browser 不会启动 TaskRun。
普通 direct answer 也有 invocation packet。
```

### 阶段二：RuntimeCompiler

目标：

```text
建立 RuntimeEnvelope / RuntimeInvocationPacket / ExecutionContext。
所有模型调用前都编译 packet。
```

完成标准：

```text
run_agent_turn_loop follow-up 不直接复用旧消息构造器作为调用输入。
每次 model call 事件都有 invocation_packet_ref。
```

### 阶段三：行动协议和 admission

目标：

```text
建立 ModelActionRequest 和 AdmissionDecision。
工具、ask_user、plan、request_task_run 都走同一 admission。
```

完成标准：

```text
系统只校验模型行动，不补行动。
invalid request fail closed。
```

### 阶段四：TaskRun 状态机

目标：

```text
TaskRun 只从 accepted request_task_run 或外部合同进入。
StepRun 状态由 loop 执行推进。
```

完成标准：

```text
finalizer 不再补 ledger。
required step 无 self-review/acceptance 不能 completed。
```

### 阶段五：Plan / Repair / Resume

目标：

```text
实现 PlanRecord、RevisionDecision、StepInvalidationRecord、RepairRecord、ResumeSafetyReview。
```

完成标准：

```text
用户中途修改和测试失败都能进入结构化修复流程。
恢复不会复用旧 packet 或重复副作用工具。
```

### 阶段六：Artifact / Acceptance / 输出

目标：

```text
实现 AcceptanceRecord 和用户可见步骤摘要。
最终回答只基于 accepted evidence。
```

完成标准：

```text
artifact 缺失时 fail closed。
最终消息不暴露内部 ID。
每步摘要有真实事件来源。
```

## 14. 最终架构定义

本项目的成熟单 Agent Harness 定义为：

```text
Harness 是 agent 的受控运行环境。
RuntimeCompiler 在每次模型调用前编译当前可见世界。
Agent 在该世界中理解、行动、计划、修复和收口。
Loop 只推进模型行动、工具执行、观察回灌和状态机。
Permission / Sandbox / File / Artifact / Acceptance 是系统门禁。
TaskRun 是 agent 请求或外部合同开启的正式长任务生命周期。
Final answer 是经过证据和验收过滤后的用户可见结果。
```

任何偏离这一定义的实现，即使短期能跑通，也视为旧控制残留。
