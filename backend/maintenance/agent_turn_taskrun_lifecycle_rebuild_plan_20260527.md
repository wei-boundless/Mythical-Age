# 单 Agent Harness 运行时与 TaskRun 生命周期重构计划书

日期：2026-05-27

状态：依据成熟 agent 设计原则重写的实施蓝图

依据文档：

```text
docs/系统框架/003-单AgentHarness运行时设计书-20260527.md
```

适用范围：

```text
backend/query/runtime.py
backend/agent_runtime
backend/harness/runtime
backend/harness/loop
backend/task_system/tasks
backend/task_system/planning
backend/runtime/model_gateway
backend/tests
```

本计划只服务一个目标：把当前单 Agent Harness 重构为成熟 coding agent 风格的受控运行时。系统不再替 agent 做语义任务判断，不再用旧控制字段静默开启 TaskRun，不再用终态补账让长任务看起来完成。系统负责装配运行时、开放行动接口、执行权限门禁、记录观察证据、恢复失败、验证真实交付物；agent 在每次运行时内理解、计划、行动、自审、修复和收尾。

## 0. 执行结论

目标主链固定为：

```text
User Input
-> TurnScope
-> RuntimeEnvelope
-> RuntimeInvocationPacket
-> ModelActionRequest
-> AdmissionDecision
-> ExecutionContext
-> ObservationRecord
-> next RuntimeInvocationPacket
-> SelfReviewRecord
-> AcceptanceRecord
-> UserVisibleFinalAnswer
```

两层状态机固定为：

```text
AgentTurn 轻状态机：
接收用户输入，装配 turn runtime，调用 agent，校验 agent 行动请求，
执行 bounded observation 或开启 TaskRun，最后提交用户可见回答。

TaskRun 长任务状态机：
只在 agent 显式请求并通过 admission 后开启，负责步骤推进、工具执行、
观察回灌、自审、修复、artifact 验收、最终回答。
```

根本变化：

```text
旧的“系统先理解任务，再替 agent 选择执行路径”删除。
新的“系统每次调用前装配运行时，让 agent 在运行时中做判断并请求行动”落地。
```

本计划禁止的方向：

```text
不建立系统侧意图识别层。
不建立系统侧任务原语选择表。
不把 professional_mode 当作 TaskRun 触发器。
不从 selected_task_id 推导任务目标字段。
不把 read/search/browser/delegate 静默升级成长任务。
不在 TaskRun 入口重新解释用户原始请求。
不让 finalizer 启动、完成、跳过步骤。
不让最终自然语言代替真实 artifact、receipt、自审和验收。
```

## 1. 成熟 agent 对照标准

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

可确认的成熟设计事实：

| 成熟设计点 | 可见实现事实 | 对本项目的硬要求 |
| --- | --- | --- |
| 主循环由模型输出驱动 | `query.ts` 收集模型 `tool_use`，执行工具，把工具结果追加回消息后继续循环 | 不能先由系统分类任务再启动不同拓扑 |
| 行动通过真实接口表达 | 模型输出工具调用、计划模式工具、子 agent 工具、最终回答 | 本项目必须使用 `ModelActionRequest` 表达 agent 真实行动请求 |
| 权限是运行时门禁 | `ToolPermissionContext` 管理模式、允许、拒绝、询问规则 | 权限不能只写在 prompt 中，必须在执行前裁决 |
| 工具默认保守 | `buildTool` 默认不是并发安全、不是只读 | 工具能力表必须显式声明只读、副作用和审批要求 |
| Plan mode 是模式和工具 | `EnterPlanModeTool` 改变 permission mode，`ExitPlanModeTool` 请求审批出口 | 计划不是任务类型，也不是专业模式旧结构 |
| Subagent 是工具化调用 | `AgentTool` 通过 `whenToUse` 暴露能力 | 委派是 agent 行动请求，不是系统预分类 |
| 验证要有裁决 | verification agent 输出 `PASS/FAIL/PARTIAL` | 长任务验收必须有可审计裁决记录 |

### 1.1.1 可迁移的源码级控制机制

这批机制必须进入本轮单 agent 重构，不作为后续“优化项”悬空：

1. **行动事实优先**：loop 只根据真实结构化 action / observation 推进，不根据 `stop_reason`、自然语言状态或关键词推进。
2. **协议闭合**：任何已接受 action 都必须闭合为 observation、lifecycle event、error 或 canceled。异常、fallback、abort 不能留下孤立 action。
3. **action id 幂等**：恢复、重试、去重按 action id / request id，不按 message id 或 turn id。
4. **半成品隔离**：模型 fallback、重试和恢复必须废弃未闭合 action 上下文，禁止旧 tool result 泄漏到新响应。
5. **工具默认保守**：工具没有显式声明 read-only / concurrency-safe / side-effect-free 时，按有副作用处理。
6. **权限顺序固定**：显式 deny、安全检查、工具自身检查先于模式放行；模式不是越权开关。
7. **运行时重装配**：每次 model invocation、TaskRun step、resume、self-review、verification 都重新装配 runtime packet。
8. **后台生命周期独立**：正式 TaskRun 与当前 turn 的取消/恢复关系必须显式声明，不能被父 turn 隐式杀死或隐式继续。
9. **恢复前清理协议**：compact/resume 前必须清理或闭合 incomplete action。
10. **完成不可空洞**：TaskRun 完成必须绑定 completion result、artifact verdict、verification receipt 或 failure reason。
11. **自审基于结构状态**：todo/verification 提醒只能从任务状态和合同得出，不能从关键词猜测。
12. **摘要不是裁决**：compact summary 只保存继续执行所需事实，不替代 agent 的下一步判断和系统验收。

### 1.2 Codex 类成熟 coding agent 标准

本项目后续实现以成熟 coding agent 的行为为标准：

```text
读代码前不臆断。
每次模型调用前装配工具、权限、上下文、artifact、预算和输出契约。
模型自己决定读、查、改、测、问、计划、修复或收尾。
工具结果作为 observation 回灌给下一次模型调用。
写入和长任务必须绑定真实文件、真实命令或浏览器 receipt、真实验收。
用户看见自然的进展和结果，不看内部控制 id。
```

因此，本项目不能用一个系统侧分类器模拟 agent 判断。系统必须把 runtime 做好，让 agent 在受控环境中发挥能力。

## 2. 当前代码审查结论

### 2.1 当前真实入口链

用户请求当前进入路径：

```text
backend/query/runtime.py
QueryRuntime.astream
-> backend/agent_runtime/turn_controller.py
   AgentTurnController.run_stream
-> backend/harness/agent_harness.py
   AgentHarness.run_stream
-> backend/harness/loop/agent_loop.py
   run_agent_invocation_stream
-> backend/harness/loop/agent_preflight.py
   run_agent_runtime_preflight
-> backend/harness/loop/agent_turn_loop.py
   run_agent_turn_loop
-> backend/harness/loop/agent_model_turn.py
   run_agent_model_turn
-> backend/harness/loop/agent_execution/engine.py
   RuntimeExecutionEngine.stream_model_turn
-> backend/runtime/model_gateway/model_response.py
   ModelResponseRuntimeExecutor.stream
```

已有基础：

```text
backend/query/runtime.py
  已基本成为 API adapter。

backend/agent_runtime/turn_models.py
  已有 AgentTurnRecord，可作为外层轻状态机基础。

backend/harness/loop/state.py
  已有 HarnessLoopState，可作为 TaskRun 内部 loop 状态基础。

backend/task_system/tasks/run_models.py
  已有 TaskRunLedger / TaskStepRun，可作为长任务账本基础。

backend/harness/loop/agent_execution/tool_loop.py
  已有 OperationGate、PermissionContext、ToolSupervisor、receipt、approval_waiting。

backend/runtime/model_gateway/model_response.py
  已有 directive-only executor，可作为受控执行底座。
```

### 2.2 当前核心偏差

#### 偏差 A：系统侧理解和执行判断仍占主权

文件：

```text
backend/agent_runtime/turn_controller.py
backend/agent_runtime/understanding/model_turn_decision.py
backend/agent_runtime/understanding/model_turn_decision_runtime.py
backend/agent_runtime/execution_decision.py
```

当前问题：

```text
ModelTurnDecision 被系统当作生产控制节点。
ExecutionDecision 从 action_intent 映射执行模式。
普通 turn 被迫经过任务理解语义。
```

目标：

```text
删除系统侧理解管线的生产主权。
保留的结构化输出必须改为 agent 在真实 invocation 中发出的行动请求。
系统只校验行动请求，不替 agent 选择行动。
```

#### 偏差 B：轻量观察被静默升级为 TaskRun

文件：

```text
backend/agent_runtime/execution_decision.py
```

当前问题：

```text
read_context
search_external
use_browser
delegate
```

会被系统映射到 TaskRun。这违反成熟 agent 模式：读、查、浏览、委派可以是当前 turn 的 bounded observation，只有 agent 请求正式长任务并通过 admission 后才创建 TaskRun。

目标：

```text
删除 ExecutionDecision 的生产路由职责。
建立 AdmissionDecision：只对 agent 已发出的行动请求做 allow / deny / ask_approval / invalid / needs_contract 裁决。
```

#### 偏差 C：direct answer 绕过运行时装配

文件：

```text
backend/agent_runtime/turn_controller.py
```

当前问题：

```text
_invoke_direct_answer() 直接拼 raw messages 调 invoke_messages。
```

目标：

```text
direct answer 也必须先编译 RuntimeInvocationPacket。
所有模型调用共享同一装配、权限、输出契约和审计链。
```

#### 偏差 D：TaskRun 入口仍有重新理解能力

文件：

```text
backend/harness/runtime/turn_context.py
backend/harness/loop/agent_loop.py
```

当前问题：

```text
run_agent_invocation_stream() 调用 build_agent_turn_context()。
build_agent_turn_context() 可以再次调用 main_model_owned_turn_decision()。
```

目标：

```text
TaskRun 入口只消费已通过 admission 的 TaskRunContract。
TaskRun 入口不得重新解释用户意图。
用户当前输入和合同都作为 runtime 输入给 agent，而不是由系统重新分类。
```

#### 偏差 E：RuntimeStartPacket 不是每次调用的 RuntimeInvocationPacket

文件：

```text
backend/harness/runtime/start_packet.py
```

当前问题：

```text
旧 start packet 围绕 request_facts / boundary_policy / context_candidates /
model_turn_decision / action_permit 组织。
```

目标：

```text
替换为 RuntimeInvocationPacket。
每次模型调用、工具回灌、自审、修复、恢复、最终回答前都重新编译 packet。
```

#### 偏差 F：TaskRun 内 follow-up 直接构造消息

文件：

```text
backend/harness/loop/agent_turn_loop.py
backend/harness/loop/agent_execution/followup_cycle.py
```

当前问题：

```text
build_initial_followup_messages()
build_next_followup_messages()
```

直接承担模型调用输入主权。

目标：

```text
这些函数只能降为 prompt/message fragment helper。
最终模型输入必须来自 RuntimeCompiler.compile_invocation_packet()。
```

#### 偏差 G：finalizer 能补完步骤

文件：

```text
backend/harness/loop/agent_finalization.py
```

当前问题：

```text
terminal finalize 会启动 pending step、完成 running step、跳过未验证 step。
```

目标：

```text
finalizer 只能读取已完成且已验收状态，并提交用户可见结果。
step 状态推进只能发生在 loop 执行、自审和验收阶段。
```

#### 偏差 H：没有一等 self-review 和 acceptance

文件：

```text
backend/task_system/tasks/run_models.py
backend/task_system/tasks/step_summary.py
backend/harness/service_host.py
backend/harness/loop/agent_phase_pipeline.py
```

当前问题：

```text
StepExecutionSummary 是系统摘要，不是 agent self-review。
artifact validation 是局部能力，不是一等 AcceptanceRecord。
```

目标：

```text
新增 SelfReviewRecord，由 agent 独立 invocation 产出。
新增 AcceptanceRecord，由系统基于 artifact、receipt、self-review、权限和审批记录裁决。
```

#### 偏差 I：终态消息回传链路必须可验证

当前风险：

```text
测试、工具、验收结果可能写入内部事件，但最终用户消息没有稳定回传。
```

目标：

```text
每个 terminal path 都必须生成用户可见终态事件：
completed
blocked
failed
needs_user
```

终态事件必须引用已提交的 ObservationRecord / AcceptanceRecord，但用户正文不能泄露内部 id。

## 3. 目标权责链

| 层 | 允许拥有的权力 | 禁止拥有的权力 | 产物 |
| --- | --- | --- | --- |
| `QueryRuntime` | 接收 API 输入，提交用户消息，启动 turn | 判断用户意图、选择 TaskRun | `TurnInput` |
| `AgentTurnLoop` | 管理一轮用户输入的生命周期 | 用关键词或旧字段替 agent 选择行动 | `AgentTurnRecord` |
| `RuntimeCompiler` | 为每次模型调用装配 runtime | 根据用户文本决定行动 | `RuntimeInvocationPacket` |
| `Model` | 理解当前 runtime，发出行动请求或最终回答 | 绕过系统权限直接执行副作用 | `ModelActionRequest` |
| `Admission` | 校验行动请求、权限、合同完整性 | 把无效请求改写成另一个行动 | `AdmissionDecision` |
| `Execution` | 执行已授权工具、文件、命令、浏览器操作 | 重写用户目标或补充 agent 未请求的行动 | `ExecutionContext` / receipt |
| `Observation` | 记录真实事实、错误、输出引用 | 裁决任务完成 | `ObservationRecord` |
| `TaskRunLoop` | 推进已开启的长任务状态机 | 重新理解原始用户意图 | `TaskRunLedger` |
| `SelfReview` | 让 agent 审查当前步骤或最终结果 | 替系统验收 artifact | `SelfReviewRecord` |
| `Acceptance` | 根据证据裁决是否可完成 | 生成不存在的证据 | `AcceptanceRecord` |
| `Presentation` | 生成自然用户可见消息 | 泄露隐藏推理和内部控制 id | assistant message |

## 4. 目标对象模型

### 4.1 RuntimeEnvelope

新增文件：

```text
backend/harness/runtime/envelope.py
```

职责：

```text
描述一次受控运行环境的外壳。
它是 runtime 装配的输入边界，不是 agent 决策结果。
```

字段：

```text
envelope_id
scope_kind: turn | task_run | step | delegate | recovery
session_id
turn_id
task_run_id
step_id
agent_profile_ref
task_environment_ref
mode_policy
tool_policy
permission_policy
sandbox_policy
file_policy
memory_policy
artifact_policy
prompt_policy
output_policy
budget_policy
approval_policy
recovery_policy
diagnostics
authority = harness.runtime.envelope
```

禁止字段：

```text
system_inferred_intent
system_selected_action
ordinary_turn_task_goal_type
```

### 4.2 RuntimeInvocationPacket

新增文件：

```text
backend/harness/runtime/invocation_packet.py
```

职责：

```text
每次模型调用唯一输入合同。
任何模型调用都必须先创建新的 packet。
```

字段：

```text
packet_id
envelope_ref
invocation_kind
invocation_index
session_id
turn_id
task_run_id
step_id
model_messages
system_instructions
agent_role_prompt
prompt_pack_refs
available_tools
available_modes
permission_snapshot
context_refs
observation_refs
artifact_refs
current_task_contract_ref
current_plan_ref
current_repair_refs
output_contract
stop_conditions
budget_snapshot
user_visible_status_policy
hidden_control_refs
authority = harness.runtime.invocation_packet
```

必须重新编译的场景：

```text
普通 turn 第一次 agent 调用。
direct answer。
bounded observation 后。
TaskRun step action。
工具结果回灌后。
进入计划模式后。
用户中途修改后。
agent 自审前。
repair 前。
resume 后。
最终回答前。
```

### 4.3 ModelActionRequest

新增文件：

```text
backend/harness/loop/model_action_protocol.py
```

职责：

```text
记录 agent 在本次 invocation 中真实发出的行动请求。
它不是系统侧意图枚举，也不是路由分类器。
```

请求族：

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

硬规则：

```text
只能由模型输出或外部已验证合同入口创建。
系统不得从用户关键词创建。
系统不得从旧 action_intent 创建。
系统不得替 agent 补请求字段。
```

### 4.4 AdmissionDecision

新增文件：

```text
backend/harness/loop/admission.py
```

职责：

```text
对 agent 已发出的行动请求做执行前裁决。
```

字段：

```text
admission_id
action_request_ref
decision: allow | deny | ask_approval | invalid | needs_contract
permission_delta
contract_errors
resource_errors
approval_request_ref
user_visible_reason
system_reason
authority = harness.loop.admission
```

硬规则：

```text
deny 不可改写为别的行动。
invalid 不可自动变成 TaskRun。
needs_contract 只能请求 agent 或用户补合同。
```

### 4.5 ToolCapabilityTable

新增文件：

```text
backend/harness/runtime/tool_capability_table.py
```

职责：

```text
为当前 invocation 暴露模型可用的工具能力。
工具可见性由 environment、mode、permission 和 invocation_kind 决定。
```

字段：

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
receipt_policy
```

硬规则：

```text
默认不可假设只读。
默认不可假设无副作用。
工具表只暴露能力，不替 agent 选择工具。
```

### 4.6 ExecutionContext

新增文件：

```text
backend/harness/runtime/execution_context.py
```

职责：

```text
执行工具、文件、命令、浏览器、artifact 操作前的系统执行合同。
```

字段：

```text
execution_context_id
packet_ref
action_request_ref
admission_ref
tool_name
operation_id
workspace_root
sandbox_snapshot
permission_receipt_ref
approval_token_ref
file_policy_ref
artifact_policy_ref
timeout
idempotency_key
authority = harness.runtime.execution_context
```

硬规则：

```text
没有 action_request_ref 不执行。
没有 admission_ref 不执行。
没有 ExecutionContext 不调用副作用工具。
```

### 4.7 ObservationRecord

新增文件：

```text
backend/harness/loop/observation_records.py
```

职责：

```text
记录真实观察结果，不裁决任务完成。
```

字段：

```text
observation_id
source: model | tool | file | shell | browser | artifact | approval | verifier
packet_ref
action_request_ref
execution_context_ref
receipt_ref
summary
payload_ref
error
created_at
authority = harness.loop.observation
```

### 4.8 PlanRecord

新增文件：

```text
backend/harness/loop/plan_records.py
```

职责：

```text
记录 agent 基于真实 runtime 和 observation 形成的计划。
```

字段：

```text
plan_ref
task_contract_ref
created_from_packet_ref
steps
risks
verification_strategy
artifact_strategy
open_questions
approval_required
authority = agent.plan_record
```

硬规则：

```text
系统不能脚手架式生成正式计划。
计划必须由 agent invocation 输出。
计划修改必须产生新的 revision 记录。
```

### 4.9 TaskRunContract

新增文件：

```text
backend/harness/loop/task_run_contract.py
```

职责：

```text
TaskRun admission 接受后的正式长任务合同。
```

字段：

```text
contract_id
contract_source: model_request | external_contract
user_visible_goal
task_run_goal
required_artifacts
required_verifications
completion_criteria
resource_requirements
permission_requirements
acceptance_policy
recovery_policy
created_from_packet_ref
authority = harness.loop.task_run_contract
```

本轮实施边界：

```text
优先实现 model_request 入口。
external_contract 只建立新合同接口，不接入旧 selected_task_id 路径。
外部合同正式开放前，必须经过 admission，并且仍作为 runtime 输入交给 agent 判断当前行动。
```

### 4.10 StepRunState

修改文件：

```text
backend/task_system/tasks/run_models.py
```

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

硬规则：

```text
finalizer 不得启动 step。
finalizer 不得完成 step。
required step 没有 self-review 和 acceptance 不得 completed。
skipped_by_contract 必须来自合同裁决，不得来自终态补账。
```

### 4.11 SelfReviewRecord

新增文件：

```text
backend/harness/loop/self_review.py
```

职责：

```text
让 agent 独立审查当前步骤、修复或最终结果。
```

字段：

```text
self_review_id
task_run_id
step_id
packet_ref
review_scope: step | repair | final
verdict: pass | fail | partial | needs_more_observation | needs_repair | ask_user
checked_contract_refs
checked_observation_refs
checked_artifact_refs
issues
proposed_followup_request
user_visible_summary
authority = agent.self_review
```

硬规则：

```text
pass 必须引用真实 evidence。
artifact 交付的 pass 必须引用真实 artifact。
self-review 不是最终验收。
```

### 4.12 AcceptanceRecord

新增文件：

```text
backend/harness/loop/acceptance.py
```

职责：

```text
系统基于证据裁决步骤、artifact 或最终结果是否可接受。
```

字段：

```text
acceptance_id
scope: step | task_run | artifact | final
task_run_id
step_id
self_review_ref
required_artifact_refs
required_receipt_refs
verification_refs
permission_receipts
approval_receipts
decision: accepted | rejected | partial | repair_required | blocked
reason
authority = harness.acceptance
```

### 4.13 UserVisibleStepSummary

新增文件：

```text
backend/harness/loop/user_visible_status.py
```

职责：

```text
把真实执行进展转成用户可见的自然摘要。
```

字段：

```text
summary_id
scope_ref
what_happened
evidence_summary
status
next_user_visible_status
authority = harness.user_visible_status
```

禁止：

```text
hidden reasoning
task_run_id
packet_id
directive_id
开发节点说明式文本
```

## 5. 固定执行流

### 5.1 普通 turn

```text
1. QueryRuntime 接收用户输入。
2. 创建 TurnScope 和 RuntimeEnvelope(scope=turn)。
3. RuntimeCompiler 编译 invocation_kind=turn_action 的 RuntimeInvocationPacket。
4. 模型输出 ModelActionRequest 或 final answer。
5. Admission 校验行动请求。
6. final answer：编译 final_user_answer packet 后提交用户消息。
7. tool_call：进入 bounded observation。
8. request_task_run：进入 TaskRun admission。
9. ask_user：提交用户可见问题。
10. block：提交用户可见阻断原因。
```

### 5.2 Bounded observation

```text
1. agent 请求 read/search/browser 等轻量观察。
2. Admission 校验工具可用性和权限。
3. RuntimeCompiler 编译 ExecutionContext。
4. 执行工具并写入 ObservationRecord。
5. RuntimeCompiler 编译 invocation_kind=tool_observation_followup。
6. agent 基于 observation 继续回答、请求更多观察、请求 TaskRun、询问用户或阻断。
```

硬规则：

```text
bounded observation 不创建 TaskRun。
bounded observation 有 observation 和 receipt。
bounded observation 失败必须回到 agent 或用户可见失败，不得静默吞掉。
```

### 5.3 Plan mode

```text
1. agent 输出 enter_plan_mode。
2. Admission 校验当前环境允许计划模式。
3. 权限快照切换为计划约束。
4. RuntimeCompiler 编译 invocation_kind=plan。
5. agent 读取真实上下文并产出 PlanRecord。
6. agent 输出 exit_plan_mode。
7. 系统按策略请求用户审批或进入 request_task_run admission。
```

硬规则：

```text
Plan mode 是 runtime 模式，不是任务类型。
professional_mode 可以加强计划要求，但不能强制进入计划或 TaskRun。
```

### 5.4 TaskRun admission

```text
1. agent 输出 request_task_run，并给出 TaskRunContract 草案。
2. Admission 检查合同完整性、权限、资源、artifact、verification、预算。
3. 通过后系统创建 task_run_id。
4. 创建 RuntimeEnvelope(scope=task_run)。
5. 进入 TaskRunLoop。
```

硬规则：

```text
admission 前不生成正式 task_run_id。
普通 turn 不要求任务目标字段。
系统不从旧字段补合同。
```

### 5.5 TaskRun loop

```text
1. 选择 ready step。
2. RuntimeCompiler 编译 invocation_kind=task_step_action。
3. agent 输出工具调用、计划修订、询问用户、自审请求、阻断或最终检查请求。
4. Admission 校验行动。
5. RuntimeCompiler 编译 ExecutionContext。
6. 执行并写 ObservationRecord。
7. RuntimeCompiler 编译 follow-up packet。
8. agent 继续行动，直到步骤进入 self_review。
9. RuntimeCompiler 编译 invocation_kind=step_self_review。
10. agent 输出 SelfReviewRecord。
11. Acceptance 校验证据。
12. step accepted 后进入下一步。
```

### 5.6 用户中途修改

```text
1. TaskRun running 时收到新的用户输入。
2. loop 在安全边界暂停：当前不可中断工具完成后停住。
3. RuntimeCompiler 编译 invocation_kind=user_revision_triage。
4. agent 判断：
   apply_to_current_step
   revise_plan
   revise_contract
   split_new_task
   ask_user
   reject_conflict
   abort_current
5. Admission 校验合同、权限、artifact、预算是否改变。
6. 受影响 step / artifact / summary 进入 invalidated。
7. RuntimeCompiler 编译 repair 或 revised step packet。
```

硬规则：

```text
系统不直接改写合同。
用户修改不能被普通聊天路径吞掉。
已被新事实推翻的步骤必须显式 invalidated。
```

### 5.7 agent 发现前序错误

```text
1. 错误来自工具、测试、浏览器、self-review、verifier 或 agent 反思。
2. RuntimeCompiler 编译 invocation_kind=step_invalidation_review。
3. agent 指出受影响 step、artifact、assumption 和 evidence。
4. 系统记录 invalidation。
5. RuntimeCompiler 编译 invocation_kind=repair_action。
6. agent 修复。
7. 系统执行并记录新 observation。
8. agent repair_self_review。
9. Acceptance 决定修复是否接受。
```

硬规则：

```text
不能按旧计划硬跑。
不能让 final answer 掩盖前序错误。
不能让系统自动重排计划而不经过 agent 审查。
```

### 5.8 Resume / 自动续跑

```text
1. 系统加载 checkpoint、ledger、observation、artifact、pending approval。
2. RuntimeCompiler 编译 invocation_kind=resume_safety_review。
3. agent 检查当前状态是否可继续。
4. Admission 校验权限、工具、环境是否仍有效。
5. 可继续则从 recorded state 恢复；不可继续则进入 repair、ask_user 或 blocked。
```

硬规则：

```text
resume 不复用旧 packet。
resume 不重复执行已有副作用工具。
resume 层不得覆盖当前用户输入。
```

### 5.9 Finalization

```text
1. 所有 required step 已 accepted。
2. RuntimeCompiler 编译 invocation_kind=final_self_review。
3. agent 输出 final SelfReviewRecord。
4. Acceptance 生成 final AcceptanceRecord。
5. 通过后 RuntimeCompiler 编译 invocation_kind=final_user_answer。
6. agent 生成用户可见最终回答。
7. QueryRuntime / stream 提交 terminal event 和 assistant message。
```

硬规则：

```text
finalizer 只提交已验收结果。
finalizer 不改变 step 执行状态。
final acceptance 失败时必须回传失败或修复请求。
测试结果、artifact 路径、失败原因必须来自真实 receipt 或 observation。
```

## 6. Prompt 与 runtime 装配设计

### 6.1 每一步都必须装配 runtime

每个 invocation 的 prompt pack 由以下输入决定：

```text
task_environment_ref
agent_profile_ref
mode_policy
invocation_kind
permission_snapshot
tool_capability_table
artifact_policy
acceptance_policy
current observations
current contract
current user revision
```

不能由以下输入决定：

```text
用户关键词。
旧 professional topology。
旧 action field。
系统侧任务分类结果。
```

### 6.2 Prompt pack 清单

新增或重建：

```text
backend/harness/runtime/prompts/models.py
backend/harness/runtime/prompts/library.py
backend/harness/runtime/prompts/packs.py
backend/harness/runtime/prompts/assembler.py
```

必须支持的 invocation prompt：

```text
turn_action
direct_answer
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
resume_safety_review
final_self_review
final_user_answer
```

### 6.3 Prompt 写法标准

禁止写给 agent 的文本：

```text
这是 runtime 节点。
根据任务图执行 world_review。
这个节点用于校验资产。
```

必须写成 agent 可理解的职责语言：

```text
你是一名交付验收员。
你只负责判断当前交付物是否真实存在、是否被验证、是否满足用户请求。
你不能替执行 agent 扩写成果。
你必须指出证据缺口，并给出 accepted、partial、repair_required 或 rejected。
```

## 7. 文件级实施计划

### 阶段一：建立新运行时协议模型

新增：

```text
backend/harness/runtime/envelope.py
backend/harness/runtime/invocation_packet.py
backend/harness/runtime/compiler.py
backend/harness/runtime/tool_capability_table.py
backend/harness/runtime/execution_context.py
backend/harness/loop/model_action_protocol.py
backend/harness/loop/admission.py
backend/harness/loop/observation_records.py
backend/harness/loop/user_visible_status.py
```

修改：

```text
backend/harness/runtime/__init__.py
backend/harness/loop/__init__.py
backend/runtime/shared/events.py
```

完成标准：

```text
RuntimeEnvelope 可序列化并包含 authority。
RuntimeInvocationPacket 校验 packet_id、envelope_ref、invocation_kind。
ToolCapabilityTable 明确只读、副作用、审批、TaskRun 要求。
ExecutionContext 强制绑定 packet_ref、action_request_ref、admission_ref。
ModelActionRequest 只能表达模型行动请求。
```

测试：

```text
backend/tests/runtime_invocation_packet_regression.py
backend/tests/model_action_admission_regression.py
backend/tests/tool_capability_table_regression.py
```

### 阶段二：删除旧系统侧执行判断主权

重写或删除：

```text
backend/agent_runtime/execution_decision.py
backend/agent_runtime/understanding/model_turn_decision.py
backend/agent_runtime/understanding/model_turn_decision_runtime.py
```

修改：

```text
backend/agent_runtime/turn_controller.py
backend/agent_runtime/turn_models.py
backend/query/runtime.py
```

执行细节：

```text
1. AgentTurnController 不再从旧 action 字段推出 TaskRun。
2. AgentTurnController 创建 RuntimeEnvelope(scope=turn)。
3. RuntimeCompiler 编译 turn_action packet。
4. 模型输出 ModelActionRequest。
5. Admission 裁决请求。
6. direct_answer、bounded observation、request_task_run、ask_user、block 分别进入对应路径。
7. direct_answer 也走 RuntimeInvocationPacket。
8. 普通 turn 不校验任务目标注册表。
```

完成标准：

```text
read_context、search_external、use_browser、delegate 不会启动 TaskRun。
professional_mode 的普通回答不会启动 TaskRun。
无法解析模型行动请求时，turn 失败关闭并回传用户可见原因。
```

### 阶段三：实现 bounded observation turn

新增：

```text
backend/agent_runtime/bounded_observation_loop.py
```

复用但重接：

```text
backend/harness/loop/agent_execution/engine.py
backend/harness/loop/agent_execution/tool_loop.py
backend/runtime/model_gateway/model_response.py
```

执行细节：

```text
1. agent 在 turn_action 或 follow-up 中请求轻量工具。
2. Admission 判定该工具允许在 bounded turn 中使用。
3. RuntimeCompiler 生成 ExecutionContext。
4. 工具执行写入 ObservationRecord。
5. RuntimeCompiler 重新编译 tool_observation_followup packet。
6. agent 回答、继续观察、请求 TaskRun、询问用户或阻断。
```

完成标准：

```text
bounded observation 有 event log。
bounded observation 有 permission receipt。
bounded observation 有 observation refs。
bounded observation 不写 TaskRunLedger。
bounded observation 失败会回传用户可见状态。
```

### 阶段四：重建 TaskRun admission 和入口

新增：

```text
backend/harness/loop/task_run_contract.py
```

修改：

```text
backend/harness/loop/agent_lifecycle.py
backend/harness/loop/agent_loop.py
backend/harness/runtime/agent_request.py
backend/harness/runtime/agent_assembly.py
backend/harness/runtime/turn_context.py
```

执行细节：

```text
1. agent 输出 request_task_run。
2. Admission 校验 TaskRunContract。
3. 通过后 start_agent_run 创建系统 task_run_id。
4. AgentHarness 接收 TaskRunContract 和 RuntimeEnvelope。
5. TaskRun 入口不再调用 main_model_owned_turn_decision。
6. turn_context 的生产调用删除。
```

完成标准：

```text
TaskRun 只从 accepted request_task_run 进入。
TaskRun 入口不能重新理解原始用户请求。
旧 selected_task_id 路径不接入新 TaskRunContract。
```

### 阶段五：TaskRun 内每次模型调用都通过 RuntimeCompiler

重命名或重写：

```text
backend/harness/loop/agent_turn_loop.py
```

建议目标命名：

```text
backend/harness/loop/model_tool_followup_loop.py
```

修改：

```text
backend/harness/loop/agent_model_turn.py
backend/harness/loop/agent_execution/followup_cycle.py
backend/harness/loop/agent_execution/engine.py
backend/runtime/model_gateway/model_response.py
```

执行细节：

```text
1. step action 调用前编译 task_step_action packet。
2. 工具执行后写 ObservationRecord。
3. follow-up 调用前编译 tool_observation_followup packet。
4. repair 调用前编译 repair_action packet。
5. 原 follow-up message builder 降为 compiler 内部片段 helper，不能直接作为模型输入主权。
```

完成标准：

```text
每次 model response 都能追溯 packet_ref。
每次 tool_call_requested 都能追溯 action_request_ref 和 execution_context_ref。
每次 follow-up packet 包含最新 observation_refs。
```

### 阶段六：实现 self-review、用户修改和修复

新增：

```text
backend/harness/loop/self_review.py
backend/harness/loop/recovery.py
backend/task_system/tasks/revision.py
backend/task_system/tasks/invalidation.py
backend/task_system/tasks/repair.py
```

修改：

```text
backend/task_system/tasks/run_models.py
backend/task_system/tasks/step_summary.py
backend/harness/loop/agent_event_application.py
backend/harness/service_host.py
```

执行细节：

```text
1. step 完成候选进入 self_reviewing。
2. RuntimeCompiler 编译 step_self_review packet。
3. agent 输出 SelfReviewRecord。
4. verdict=pass 后进入 Acceptance。
5. verdict=needs_repair 进入 repair_action。
6. verdict=needs_more_observation 回到 observation loop。
7. 用户中途修改进入 user_revision_triage。
8. 受影响 step / artifact / summary 必须 invalidated。
```

完成标准：

```text
SelfReviewRecord.pass 无 evidence refs 时拒绝。
artifact step 无 artifact refs 时拒绝 pass。
用户修改不会被吞掉。
agent 发现前序错误能进入 invalidation + repair。
```

### 阶段七：实现 final acceptance 和终态回传

新增：

```text
backend/harness/loop/acceptance.py
```

修改：

```text
backend/harness/loop/agent_phase_pipeline.py
backend/harness/loop/agent_finalization.py
backend/runtime/shared/artifact_paths.py
backend/task_system/tasks/run_models.py
backend/runtime/shared/events.py
backend/query/runtime.py
```

执行细节：

```text
1. 所有 required step accepted 后，编译 final_self_review packet。
2. agent 输出 final SelfReviewRecord。
3. AcceptanceRecord 校验 artifact、receipt、self-review、permission、approval、checkpoint。
4. 通过后编译 final_user_answer packet。
5. 用户终态消息必须通过 stream 和 session commit 回传。
6. 失败、阻断、等待用户也必须有用户可见 terminal event。
```

完成标准：

```text
finalizer 不再启动 pending step。
finalizer 不再完成 running step。
finalizer 不再跳过 required step。
final acceptance 失败不能提交 completed。
测试结果缺失时不能声称测试通过。
终态消息不会因为内部状态写入失败而丢失。
```

### 阶段八：Prompt library 与模式覆盖

新增：

```text
backend/harness/runtime/prompts/models.py
backend/harness/runtime/prompts/library.py
backend/harness/runtime/prompts/packs.py
backend/harness/runtime/prompts/assembler.py
```

修改：

```text
backend/harness/runtime/compiler.py
backend/harness/runtime/agent_assembly.py
backend/harness/runtime/environment/*
```

执行细节：

```text
1. prompt pack 由 task_environment_ref、agent_profile_ref、mode_policy、invocation_kind 选择。
2. role / standard / professional 是 runtime coverage policy。
3. professional_mode 加强计划、自审、验收和摘要要求。
4. professional_mode 不改变主 loop 架构，不强制 TaskRun。
5. prompt 内容全部写成 agent 职责语言。
```

完成标准：

```text
业务 loop 不再手写临时 system prompt。
同一 invocation_kind 在不同 environment 下可装配不同 prompt pack。
prompt pack 不决定是否开启 TaskRun。
```

### 阶段九：清理旧结构和旧测试

删除或彻底改写：

```text
backend/agent_runtime/execution_decision.py 的旧路由职责
backend/agent_runtime/understanding 的生产控制路径
backend/harness/runtime/turn_context.py 的 TaskRun 入口理解路径
backend/harness/runtime/start_packet.py 的生产依赖
backend/harness/loop/agent_turn_loop.py 的旧命名和旧输入主权
backend/harness/loop/agent_finalization.py 的步骤补账逻辑
backend/task_system/planning 中保护旧 topology 的文件
```

测试处理：

```text
删除只保护旧内部形状的测试。
改写保护行为契约的测试。
新增真实 runtime、admission、observation、自审、验收、终态回传测试。
```

完成标准：

```text
生产入口不再引用旧理解管线。
生产入口不再引用旧 start packet。
生产入口不再有系统侧行动路由。
旧测试不再要求旧 topology 存在。
```

## 8. 状态机细节

### 8.1 AgentTurn 轻状态机

| 当前状态 | 条件 | 下一状态 | 产物 |
| --- | --- | --- | --- |
| received | 创建 turn envelope | compiling_runtime | RuntimeEnvelope |
| compiling_runtime | packet 编译成功 | invoking_agent | RuntimeInvocationPacket(turn_action) |
| invoking_agent | 模型输出 | validating_action | ModelActionRequest |
| validating_action | final answer allowed | finalizing_turn | final_user_answer packet |
| validating_action | tool allowed | bounded_observation | ExecutionContext |
| validating_action | task request allowed | launching_task_run | TaskRunContract |
| validating_action | ask user | waiting_user | user question |
| validating_action | block | blocked | visible reason |
| bounded_observation | observation recorded | compiling_runtime | ObservationRecord |
| launching_task_run | TaskRun started | waiting_task_run | task_run system ref |
| waiting_task_run | terminal event | finalizing_turn | accepted result refs |
| finalizing_turn | message committed | completed | assistant message |
| 任意非终态 | unrecoverable error | failed | user-visible failure |

### 8.2 TaskRun 状态机

| 当前状态 | 条件 | 下一状态 | 产物 |
| --- | --- | --- | --- |
| created | contract admitted | admitted | TaskRunContract |
| admitted | envelope compiled | selecting_step | RuntimeEnvelope |
| selecting_step | step ready | compiling_invocation | TaskStepRun |
| compiling_invocation | packet compiled | invoking_agent | RuntimeInvocationPacket |
| invoking_agent | model output | validating_action | ModelActionRequest |
| validating_action | tool request | authorizing_action | AdmissionDecision |
| authorizing_action | allowed | executing_action | ExecutionContext |
| authorizing_action | approval required | waiting_approval | approval request |
| executing_action | receipt produced | recording_observation | receipt |
| recording_observation | observation saved | compiling_invocation | ObservationRecord |
| recording_observation | step ready for review | self_reviewing | step_self_review packet |
| self_reviewing | pass | accepting_step | SelfReviewRecord |
| self_reviewing | needs repair | repairing | repair packet |
| self_reviewing | needs observation | compiling_invocation | follow-up packet |
| accepting_step | accepted | selecting_step | AcceptanceRecord |
| accepting_step | repair required | repairing | AcceptanceRecord |
| selecting_step | no more required steps | final_self_reviewing | final review packet |
| final_self_reviewing | review produced | final_accepting | SelfReviewRecord |
| final_accepting | accepted | final_answering | AcceptanceRecord |
| final_answering | message committed | completed | assistant message |
| 任意可恢复状态 | recoverable failure | recovering | recovery packet |
| 任意不可恢复状态 | blocked | failed | visible failure |

## 9. 用户可见输出协议

用户应看到：

```text
我正在检查相关入口。
我已经确认普通 direct answer 当前绕过运行时装配。
我修改了 TaskRun finalizer 的补账逻辑，并运行了对应回归测试。
测试失败在 artifact 验收阶段，原因是缺少真实 receipt。
```

用户不应看到：

```text
task_run_id
packet_id
directive_id
hidden reasoning
internal authority strings
raw ledger dumps
control protocol JSON
```

实现要求：

```text
stream event 可以携带 debug refs。
assistant final content 默认不展示 internal refs。
诊断面板可以显示 refs。
所有 terminal path 必须回传用户可见结果。
```

## 10. 验证矩阵

### 10.1 单元测试

新增或改写：

```text
backend/tests/runtime_invocation_packet_regression.py
backend/tests/model_action_admission_regression.py
backend/tests/tool_capability_table_regression.py
backend/tests/bounded_observation_turn_regression.py
backend/tests/task_run_contract_admission_regression.py
backend/tests/task_run_self_review_acceptance_regression.py
backend/tests/task_run_no_finalizer_step_completion_regression.py
backend/tests/user_revision_repair_regression.py
backend/tests/terminal_message_delivery_regression.py
```

必须断言：

```text
RuntimeInvocationPacket 必须有 envelope_ref 和 invocation_kind。
ExecutionContext 必须有 packet_ref、action_request_ref、admission_ref。
read/search/browser/delegate 不会创建 TaskRun。
direct answer 经过 RuntimeInvocationPacket。
SelfReviewRecord.pass 无 evidence refs 被拒绝。
artifact step 无 artifact refs 被拒绝。
AcceptanceRecord 缺 required receipt 时 rejected。
finalizer 不能改变 pending/running step 为 completed。
terminal failure 也会产生用户可见消息。
```

### 10.2 集成测试

必须覆盖：

```text
普通问答 direct answer，不创建 TaskRun。
professional_mode 普通问答，不创建 TaskRun。
读取项目文件后总结，走 bounded observation，不创建 TaskRun。
浏览器或搜索观察后回答，走 bounded observation，不创建 TaskRun。
代码修改请求，由 agent 请求 TaskRun，再通过 admission 创建 TaskRun。
TaskRun 每次模型调用都有 packet_ref。
工具调用都有 ExecutionContext 和 permission receipt。
approval_waiting 可恢复。
用户中途修改进入 user_revision_triage。
测试失败进入 invalidation + repair。
final acceptance rejected 时不提交 completed。
```

### 10.3 后端 CLI 实测

用户偏好实测，因此最终实施必须跑真实后端 CLI / 窗口输入：

```text
你好，介绍一下 harness。
请读 backend/agent_runtime/execution_decision.py 并总结问题。
请搜索项目中 TaskRun 入口并给出审查意见。
请修改一个小 bug 并运行测试。
请完成一个需要真实 artifact 的长任务。
在任务执行中途输入修改要求。
制造一次测试失败，确认 agent 能修复或回传失败原因。
```

期望：

```text
普通问答无 TaskRun。
只读观察无 TaskRun。
写入和真实交付进入 TaskRun。
测试结果通过真实命令 receipt 回传。
长任务完成有 artifact、observation、self-review、acceptance。
失败有用户可见失败消息。
```

固定本地节点：

```text
前端：http://127.0.0.1:3000
后端：http://127.0.0.1:8003
前端 API Base：http://127.0.0.1:8003/api
```

## 11. 切换规则

实施时必须遵守：

```text
一旦某阶段接入新 RuntimeCompiler，对应旧生产入口必须删除。
一旦 ModelActionRequest 接管行动表达，旧 ExecutionDecision 路由必须删除。
一旦 TaskRunContract 接管长任务入口，旧 turn_context 理解路径必须删除。
一旦 AcceptanceRecord 接管完成裁决，finalizer 补账逻辑必须删除。
一旦 prompt pack 接管装配，业务 loop 手写 prompt 必须删除。
```

禁止保留：

```text
旧 professional task topology。
旧 understanding step compiler。
旧 RuntimeStartPacket 生产依赖。
旧 action field 到 TaskRun 的映射。
旧 selected task 到任务目标字段的推导。
旧测试要求旧内部结构存在。
```

允许保留：

```text
真实工具执行能力。
真实 permission / sandbox / approval 能力。
真实 artifact path validation 能力。
真实 event stream 和诊断事件能力。
```

保留条件：

```text
必须重新接到 RuntimeInvocationPacket、ModelActionRequest、AdmissionDecision、
ExecutionContext、ObservationRecord、SelfReviewRecord、AcceptanceRecord 这条链上。
```

## 12. 最终完成定义

重构完成必须同时满足：

```text
AgentTurn 是用户一轮输入生命周期。
TaskRun 是正式长任务生命周期。
每次模型调用都由 RuntimeCompiler 编译 RuntimeInvocationPacket。
agent 自己请求工具、计划、TaskRun、修复、自审或最终回答。
系统只做 admission、permission、execution、observation、acceptance、presentation。
bounded observation 能完成轻量读/查/浏览。
professional_mode 是 runtime coverage policy，不是强制 TaskRun 结构。
长任务完成绑定真实 artifact、真实 receipt、self-review 和 final acceptance。
用户中途修改进入 revision triage。
agent 发现错误进入 invalidation + repair。
resume 重新装配 runtime，不复用旧 packet。
finalizer 不补账。
测试结果和最终消息能真实回传。
用户最终回答自然、简洁、不泄露内部控制协议。
```

任何实现如果让系统重新获得语义任务判断权、让旧字段重新决定 TaskRun、让 finalizer 继续补完成，均视为未完成。
