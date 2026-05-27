# Agent Turn 与 TaskRun 生命周期重构计划 - 2026-05-27

本计划用于修复当前单 agent harness 控制流的结构性问题。目标不是给旧链路补兜底，而是建立成熟 agent 机制：系统提供环境、权限、上下文、可观测性和任务启动能力；agent 先理解请求并判断本轮应如何行动；只有显式任务合同或 agent 判断需要正式任务生命周期时，才进入 TaskRun。

## 1. 核心结论

当前系统的问题不是“TaskRun 启动太晚”，而是“普通 chat 过早被当成 TaskRun”。如果把所有用户消息都强行包进 `taskinst`，就会破坏 agent 的自主判断：普通回答、澄清、轻量读取、代码审查、长任务执行都会被压成同一种 task assembly 流程。

目标架构必须拆成两层：

```text
ChatTurn / AgentInvocation
-> 理解、判断、授权、反馈
-> 决定是否开启 TaskRun

TaskRun
-> 只承载一段正式任务生命周期
-> 由 loop 在明确合同下开启、推进、恢复、验收、关闭
```

换句话说，TaskRun 不是用户每发一句话就自动存在的容器，而是 agent loop 在需要执行一段可追踪任务时创建的生命周期对象。

## 2. 设计原则

### 2.1 主模型拥有语义判断权

系统不能用关键词、route hint、profile fallback、task goal 猜测来替 agent 决定用户要什么。代码层只能提供事实和边界：

- 用户原文。
- 显式选择的任务、agent、合同、文件路径。
- 当前会话状态、候选上下文、可用工具。
- 权限、沙箱、资源约束。
- 已存在 artifacts、checkpoint、失败记录。

用户意图、是否需要工具、是否需要写文件、是否需要 TaskRun，必须由 agent 的结构化决策给出。

### 2.2 TaskRun 只代表正式任务生命周期

TaskRun 必须具备这些特征：

- 有明确目标或任务合同。
- 有执行边界、权限边界和资源边界。
- 有可观测事件、checkpoint、恢复策略。
- 长任务必须绑定真实 artifacts 或真实外部效果。
- 完成状态必须经过证据和验收，不允许只凭自然语言宣布完成。

不满足这些条件的普通问答不应创建 TaskRun。

### 2.3 系统不阻塞 agent 能力，但必须控制边界

成熟 agent 的控制不是“把 agent 关进固定流程”，而是：

- 允许 agent 自己判断下一步。
- 系统在执行前做权限门禁。
- 系统在执行后记录观察结果。
- 系统在完成前做证据验证。
- 系统在失败时提供恢复入口。

系统不能在理解阶段抢先执行任务分类，也不能在执行阶段静默替 agent 换目标。

### 2.4 所有关键阶段必须可观测

即使没有 TaskRun，也必须有 `AgentTurn` 或 `AgentInvocation` 记录。否则理解决策卡住时，监控只能看到 `task_run_count: 0`，无法判断 agent 是否进入、卡住、超时或失败。

### 2.5 禁止启发式关键词修复

本次修复禁止新增以下类型逻辑：

- 根据“写/创建/修复/测试”等关键词决定是否 TaskRun。
- 根据文件后缀决定用户意图。
- 根据旧 profile fallback 自动生成 task goal。
- 根据自然语言完成宣告判断 artifact 完成。

可以保留路径提取、显式参数读取、结构化合同解析，因为它们是事实，不是意图裁决。

## 3. 理想控制流

### 3.1 普通 chat 入口

```text
/api/chat
-> QueryRuntime.astream
-> AgentTurnController.start_turn
-> AgentTurnStarted event
-> RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> AgentUnderstandingDecision
-> ExecutionDecision
-> ActionPermit
-> 执行对应分支
-> AgentTurnCompleted / Failed
```

`QueryRuntime` 只负责 API 输入、会话消息提交、SSE 输出和调用 agent turn 控制器。它不应直接构造正式 task lifecycle。

### 3.2 ExecutionDecision 类型

`ExecutionDecision` 是成熟 agent 控制流的关键结构，建议至少包含：

```text
direct_answer
ask_clarification
read_only_inspection
tool_turn
task_run
delegate
block
```

字段建议：

```json
{
  "authority": "agent_runtime.execution_decision",
  "decision_id": "...",
  "turn_id": "...",
  "execution_mode": "direct_answer|ask_clarification|read_only_inspection|tool_turn|task_run|delegate|block",
  "decision_basis_refs": [],
  "status_code": "decision.accepted",
  "phase": "execution_decision",
  "next_action": "respond|ask_user|inspect_context|run_tool|launch_task_run|delegate|block",
  "blocking_reason": "",
  "requires_task_run": false,
  "requires_artifacts": false,
  "requires_write": false,
  "requires_command": false,
  "requires_browser": false,
  "resource_contract": {},
  "permission_request": {},
  "task_contract_seed": {},
  "completion_contract": {},
  "uncertainty": [],
  "needs_clarification": false,
  "clarification_question": "",
  "confidence": 0.0
}
```

`task_contract_seed` 只有在 `execution_mode == task_run` 时才允许成为 TaskRun 创建输入。普通回答可以没有 `task_goal_type`。

注意：`ExecutionDecision` 是控制协议，不是用户文案。不要让 agent 输出“我将先检查相关代码”这类自然语言状态。专业 coding agent 的状态应该是可执行、可审计、可恢复的结构化裁决；UI/CLI 可以根据 `phase/status_code/next_action/blocking_reason` 渲染用户提示。

### 3.3 TaskRun 开启点

TaskRun 应由 loop 在以下两种情况下开启：

1. 外部已送入显式任务合同。
   例如 task graph 节点、用户选择的具体任务、恢复某个已有 TaskRun、系统调度任务。

2. 当前 agent turn 的 `ExecutionDecision.execution_mode == task_run`。
   这代表 agent 判断本轮需要一段正式任务生命周期。

推荐入口：

```text
AgentTurnController
-> if explicit_task_contract:
      TaskRunLoop.start_from_contract(...)
-> elif execution_decision.execution_mode == "task_run":
      TaskRunLoop.start_from_decision(...)
-> else:
      DirectTurnLoop / ToolTurnLoop
```

`TaskRunLoop.start_from_decision()` 是唯一从普通 chat 转入 TaskRun 的入口。

## 4. TaskRun 生命周期设计

TaskRun 是 loop 开启的一段任务生命周期，不是 chat turn 的别名。建议状态机如下：

```text
created
-> admitted
-> assembled
-> running
-> waiting_approval
-> recovering
-> verifying
-> finalizing
-> completed

失败/中止分支：
created/admitted/assembled/running/verifying/finalizing
-> failed | blocked | aborted
```

### 4.1 created

创建 TaskRun 记录，但还不执行模型或工具。

必须写入：

- `task_run_id`
- `session_id`
- `turn_id`
- `source_agent_invocation_id`
- `task_contract_ref`
- `execution_mode`
- `artifact_policy`
- `permission_policy`
- `recovery_policy`

### 4.2 admitted

检查这个 TaskRun 是否允许启动：

- 是否来自显式合同或 agent execution decision。
- 是否有目标、边界、权限、资源约束。
- 是否有 artifact 要求和完成标准。
- 是否和当前 agent profile/runtime lane 匹配。

失败时进入 `blocked`，不能降级为普通回答伪装成功。

### 4.3 assembled

把合同装配成 runtime start packet：

- system prompt
- role prompt
- context package
- tool table
- sandbox/file policy
- artifact repository binding
- checkpoint policy
- closeout policy

装配层不能重新解释用户目标，只能使用上游 decision/contract。

### 4.4 running

执行 loop：

```text
model step
-> tool request
-> permission gate
-> tool execution
-> observation ledger
-> model step
```

loop 可以让 agent 自由规划和使用工具，但每次外部动作都必须通过权限和环境控制。

### 4.5 waiting_approval

当 agent 请求越权操作、危险命令、写入关键路径、网络访问或用户确认时进入该状态。

要求：

- 记录 pending approval token。
- SSE/CLI 返回用户可见等待事件。
- resume 时从 checkpoint 恢复，不重新发明任务。

### 4.6 recovering

失败恢复不是自然语言重试，而是结构化恢复：

- 读取 checkpoint。
- 读取 artifact repository 当前状态。
- 读取 observation ledger。
- 让 agent 判断恢复策略。
- 只允许在原任务合同边界内继续。

恢复不能偷偷换目标，不能把失败任务改成普通回答完成。

### 4.7 verifying

长任务完成必须进入验证阶段。验证依据：

- artifact repository records
- structured tool receipts
- observed paths
- command receipts
- acceptance checks
- browser/screenshot/test outputs
- final closeout judgment

自然语言“我已完成”不能作为完成证据。

### 4.8 finalizing

最终写回：

- TaskRun terminal status。
- final answer。
- artifact refs。
- verification summary。
- memory receipts。
- trace summary。
- session live view。

只有验证通过才允许 `completed`。验证失败必须是 `failed` 或 `blocked`，并给出下一步恢复建议。

## 5. AgentTurn 状态机与执行细节

AgentTurn 是每一轮用户输入的控制壳。它必须存在，即使本轮最后只是普通回答。它负责让系统知道 agent 当前是在理解、决策、执行轻量动作、启动 TaskRun，还是已经失败。

### 5.1 AgentTurn 状态机

```text
received
-> facts_built
-> boundary_checked
-> context_candidates_built
-> understanding
-> deciding
-> permit_checking
-> direct_responding
-> tool_turn_running
-> launching_task_run
-> waiting_task_run
-> closing
-> completed

失败/阻断分支：
received/facts_built/boundary_checked/context_candidates_built/understanding/deciding/permit_checking/direct_responding/tool_turn_running/launching_task_run/closing
-> clarification_required | blocked | failed | timed_out | aborted
```

状态含义：

- `received`：API 已接收用户输入，并生成 `turn_id`。
- `facts_built`：系统只抽取事实，不判断意图。
- `boundary_checked`：系统完成安全、权限、产品边界判断。
- `context_candidates_built`：系统给出候选上下文，不替 agent 选目标。
- `understanding`：agent 正在理解用户请求。
- `deciding`：agent 正在输出本轮执行决策。
- `permit_checking`：系统根据决策做权限门禁。
- `direct_responding`：agent 直接回答，不创建 TaskRun。
- `tool_turn_running`：agent 做轻量工具轮，不创建 TaskRun。
- `launching_task_run`：agent 决定开启正式任务生命周期，系统正在创建 TaskRun。
- `waiting_task_run`：TaskRun 已接管，AgentTurn 等待其终态或阶段性回写。
- `closing`：系统正在提交 assistant 消息、写 memory、更新 live view。
- `completed`：本轮 turn 完成。
- `clarification_required`：agent 判断必须先问用户。
- `blocked`：边界或权限阻断。
- `failed`：系统或模型失败，已给出用户可见错误。
- `timed_out`：理解、决策、直接回答或工具轮超时。
- `aborted`：用户或系统取消。

### 5.2 AgentTurn 持久模型

建议新增 `AgentTurnRecord`：

```json
{
  "turn_id": "turn:<session_id>:<index>",
  "session_id": "...",
  "agent_invocation_id": "aginvoke:<turn_id>:main",
  "user_message_ref": "...",
  "status": "received|facts_built|...|completed|failed",
  "source": "chat|cli|graph|resume|automation",
  "created_at": 0.0,
  "updated_at": 0.0,
  "request_facts": {},
  "boundary_policy": {},
  "context_candidates": {},
  "understanding_decision": {},
  "execution_decision": {},
  "action_permit": {},
  "active_task_run_id": "",
  "terminal_reason": "",
  "status_code": "",
  "phase": "",
  "blocking_reason": "",
  "diagnostics": {}
}
```

持久化要求：

- `received` 必须在任何模型调用前写入。
- 每次状态变化必须更新 `updated_at`。
- 模型调用开始前必须写 `understanding_started` 或 `decision_started` 事件。
- 任何异常都必须收敛为 `failed/timed_out/blocked/clarification_required`，不能让 SSE 无终态。

### 5.3 AgentTurn 事件规范

每个事件必须有：

```json
{
  "scope": "agent_turn",
  "turn_id": "...",
  "event_type": "...",
  "status_after": "...",
  "payload": {},
  "created_at": 0.0
}
```

最低事件集：

- `agent_turn_received`
- `request_facts_built`
- `boundary_policy_checked`
- `context_candidates_built`
- `understanding_started`
- `understanding_completed`
- `understanding_failed`
- `execution_decision_started`
- `execution_decision_completed`
- `action_permit_checked`
- `direct_response_started`
- `direct_response_completed`
- `tool_turn_started`
- `tool_turn_observed`
- `task_run_launch_requested`
- `task_run_launched`
- `task_run_terminal_observed`
- `agent_turn_closing`
- `agent_turn_completed`
- `agent_turn_failed`
- `agent_turn_timed_out`
- `agent_turn_blocked`

SSE/CLI 至少要把以下事件转成用户可见消息：

- `understanding_started`：正在理解请求。
- `execution_decision_completed`：已决定直接回答、使用工具或开启任务。
- `task_run_launched`：正式任务已启动；`task_run_id` 只作为系统内部关联键记录。
- `task_run_terminal_observed`：任务完成/失败/阻断。
- 所有 terminal 事件。

事件 payload 中不存手写聊天文案。事件只存 `phase`、`status_code`、`next_action`、`blocking_reason`、`task_run_id`、`artifact_refs`、`error_code` 等结构化字段。presentation 层负责把这些字段渲染为 CLI/SSE/前端文案。

`task_run_id`、`turn_id`、`agent_invocation_id` 默认不展示给普通用户。它们用于系统恢复、监控、日志关联、开发者调试和显式“查看运行详情”场景。用户默认只看到任务状态、阻塞原因、交付物、验证结果和下一步操作。

### 5.4 Agent 和系统逐步交互协议

#### Step 1: API 接收

系统动作：

1. 校验 `session_id`。
2. 生成 `turn_id` 与 `agent_invocation_id`。
3. 提交用户消息。
4. 写入 `AgentTurnRecord(status=received)`。
5. SSE 发出 `agent_turn_received`。

agent 权限：

- 此阶段 agent 不参与。

禁止：

- 禁止创建 TaskRun。
- 禁止选择 `task_goal_type`。

#### Step 2: 系统构建 facts/boundary/context candidates

系统动作：

1. `RequestFacts`：抽取显式路径、显式 task selection、显式 artifact refs、显式权限参数。
2. `BoundaryPolicy`：判断安全边界、产品边界、是否必须拒绝。
3. `ContextCandidates`：列出可能相关的 memory、文件、artifact、task run、tool，不做最终选择。
4. 更新 AgentTurn 状态到 `context_candidates_built`。

agent 权限：

- 此阶段 agent 不参与。

禁止：

- 禁止根据关键词判断“用户要写文件/要跑命令/要开启任务”。
- 禁止把 candidate 变成 selected goal。

#### Step 3: agent 理解

系统给 agent 的输入：

```json
{
  "user_message": "...",
  "request_facts": {},
  "boundary_policy": {},
  "context_candidates": {},
  "conversation_summary": "",
  "available_execution_modes": [
    "direct_answer",
    "ask_clarification",
    "read_only_inspection",
    "tool_turn",
    "task_run",
    "delegate",
    "block"
  ]
}
```

agent 输出 `AgentUnderstandingDecision`：

```json
{
  "authority": "agent_runtime.understanding_decision",
  "turn_id": "...",
  "understood_user_goal": "",
  "user_goal_type": "question|clarification|inspection|implementation|verification|long_task|unknown",
  "known_requirements": [],
  "unknowns": [],
  "target_objects": [],
  "explicit_constraints": [],
  "success_meaning": "",
  "risk_notes": [],
  "requires_context_selection": false,
  "confidence": 0.0
}
```

系统校验：

- `authority` 必须正确。
- `turn_id` 必须匹配。
- `understood_user_goal` 不能为空，除非 `user_goal_type=unknown`。
- 不能包含工具执行结果。

失败处理：

- JSON 无效：允许一次 repair。
- repair 后仍无效：AgentTurn -> `failed`，SSE 返回 `understanding_invalid`。
- 模型超时：AgentTurn -> `timed_out`，SSE 返回 `understanding_timeout`。

#### Step 4: agent 决定执行模式

agent 输出 `ExecutionDecision`：

```json
{
  "authority": "agent_runtime.execution_decision",
  "turn_id": "...",
  "execution_mode": "direct_answer|ask_clarification|read_only_inspection|tool_turn|task_run|delegate|block",
  "decision_basis_refs": [],
  "status_code": "decision.accepted",
  "phase": "execution_decision",
  "next_action": "respond|ask_user|inspect_context|run_tool|launch_task_run|delegate|block",
  "blocking_reason": "",
  "requires_task_run": false,
  "requires_write": false,
  "requires_command": false,
  "requires_browser": false,
  "requires_network": false,
  "requires_artifacts": false,
  "selected_context_refs": [],
  "tool_intent": {},
  "permission_request": {},
  "task_contract_seed": {},
  "completion_contract": {},
  "clarification_question": "",
  "block_reason": "",
  "confidence": 0.0
}
```

一致性规则：

- `execution_mode=direct_answer` 时，`requires_task_run` 必须为 false。
- `execution_mode=ask_clarification` 时，必须有 `clarification_question`。
- `execution_mode=block` 时，必须有 `block_reason`。
- `execution_mode=task_run` 时，`requires_task_run` 必须为 true，且 `task_contract_seed` 必须包含目标、边界、完成标准。
- `requires_artifacts=true` 时，必须有 `completion_contract.artifact_requirements`。
- `requires_write/requires_command/requires_browser/requires_network` 为 true 时，必须有对应 `permission_request`。

系统校验失败时：

- 不允许自动改 decision。
- 返回 `execution_decision_invalid`。
- AgentTurn -> `failed` 或 `clarification_required`。

#### Step 5: 系统权限门禁

系统输入：

- `BoundaryPolicy`
- `ExecutionDecision`
- 当前 permission mode
- tool/file/network/browser policy
- explicit user approvals

系统输出 `ActionPermit`：

```json
{
  "authority": "agent_runtime.action_permit",
  "turn_id": "...",
  "allowed": true,
  "execution_mode": "...",
  "granted_operations": [],
  "denied_operations": [],
  "approval_required": false,
  "approval_request": {},
  "sandbox_policy": {},
  "file_policy": {},
  "network_policy": {},
  "diagnostics": {}
}
```

规则：

- `ActionPermit` 只能授权或拒绝，不能改目标。
- 权限不足时进入 `blocked` 或 `waiting_approval`，不能降级为普通回答声称完成。

#### Step 6: 分派执行

分派规则：

```text
direct_answer
-> DirectResponseLoop

ask_clarification
-> Commit clarification answer

read_only_inspection
-> ReadOnlyInspectionLoop

tool_turn
-> ToolTurnLoop

task_run
-> TaskRunLoop.start_from_execution_decision

delegate
-> Delegation admission

block
-> Blocked final response
```

禁止：

- `direct_answer` 分支创建 TaskRun。
- `tool_turn` 分支写入文件，除非 decision 和 permit 明确允许并升级为 TaskRun。
- `read_only_inspection` 分支执行 shell 修改命令。

## 6. AgentTurn 与 TaskRun 对接设计

### 6.1 HandoffPacket

AgentTurn 转入 TaskRun 时，必须生成 `TaskRunHandoffPacket`：

```json
{
  "authority": "agent_runtime.task_run_handoff",
  "turn_id": "...",
  "agent_invocation_id": "...",
  "session_id": "...",
  "source": "execution_decision|explicit_contract|resume",
  "understanding_decision_ref": "...",
  "execution_decision": {},
  "action_permit": {},
  "task_contract_seed": {},
  "resource_contract": {},
  "completion_contract": {},
  "artifact_policy": {},
  "recovery_policy": {},
  "status_code": "task_run.launch_requested",
  "phase": "launching_task_run"
}
```

该 packet 是普通 turn 到 TaskRun 的唯一入口。TaskRun assembly 只能读取这个 packet 和显式合同，不能重新猜测用户意图。

### 6.2 start_from_execution_decision

`TaskRunLoop.start_from_execution_decision(packet)` 执行：

1. 校验 `packet.authority`。
2. 校验 `execution_decision.execution_mode == task_run`。
3. 校验 `action_permit.allowed == true`。
4. 编译正式 `TaskContract`。
5. 创建 artifact repository scope。
6. 创建 `TaskRun(status=created)`。
7. 写 `task_run_created_from_agent_turn` 事件。
8. 状态推进到 `admitted`。
9. 将 `task_run_id` 写入 AgentTurn 的 `active_task_run_id`，作为内部关联键。

如果第 1 到 4 步失败：

- 不创建 TaskRun。
- AgentTurn -> `failed`。
- SSE 返回明确失败原因。

如果第 5 到 7 步失败：

- 如果 TaskRun 已创建，TaskRun -> `failed`。
- AgentTurn -> `failed`。
- 必须写入失败事件，避免半截不可见 run。

### 6.3 start_from_contract

`TaskRunLoop.start_from_contract(contract)` 用于显式任务：

1. 校验合同来源。
2. 跳过普通 agent execution decision。
3. 仍然构造 AgentTurn 记录，状态直接到 `launching_task_run`。
4. 创建 TaskRun。
5. TaskRun 终态回写 AgentTurn。

显式合同优先级高于普通 chat decision。agent 可以在 TaskRun 内执行合同，但不能在启动前覆盖合同目标。

### 6.4 AgentTurn 等待 TaskRun

AgentTurn 进入 `waiting_task_run` 后：

- 订阅 TaskRun terminal event。
- 将 TaskRun 的阶段性事件转发为 SSE。
- 记录 `active_task_run_id`。
- 不再直接提交最终 assistant message，除非 TaskRun 返回 closeout packet。

TaskRun 返回：

```json
{
  "authority": "task_run.closeout_packet",
  "task_run_id": "...",
  "turn_id": "...",
  "terminal_status": "completed|failed|blocked|aborted",
  "terminal_reason": "",
  "final_content": "",
  "artifact_refs": [],
  "verification_summary": {},
  "recovery_hint": {},
  "memory_writeback": {}
}
```

AgentTurn 根据 closeout packet 进入 `closing`。

## 7. DirectResponseLoop 与 ToolTurnLoop

### 7.1 DirectResponseLoop

适用：

- 普通问答。
- 解释。
- 不需要读取外部上下文的建议。
- 简短总结。

流程：

1. AgentTurn -> `direct_responding`。
2. 系统构造 answer prompt。
3. agent 生成最终回答。
4. 系统提交 assistant message。
5. AgentTurn -> `completed`。
6. SSE 发送 `done`。

约束：

- 不创建 TaskRun。
- 不写 artifact。
- 不声称执行了工具或文件修改。
- 如果回答过程中发现需要读文件/运行命令，必须返回 `execution_escalation_requested`，由 AgentTurn 重新进入 `deciding`。

### 7.2 ReadOnlyInspectionLoop

适用：

- 代码审查。
- 文件解释。
- 搜索上下文。
- 不修改文件的分析。

流程：

1. AgentTurn -> `tool_turn_running`。
2. 系统只授予 read/search 类工具。
3. agent 请求读取。
4. 系统执行读取并记录 observation。
5. agent 输出审查/解释。
6. AgentTurn -> `closing -> completed`。

约束：

- 不写文件。
- 不启动服务。
- 不运行破坏性命令。
- 如果 agent 判断需要修复，必须输出 escalation decision，由系统转入 `task_run` admission。

### 7.3 ToolTurnLoop

适用：

- 单轮或短轮工具动作。
- 不需要正式 artifact 生命周期。
- 可在 turn 内完成并验证的小操作。

流程：

1. AgentTurn -> `tool_turn_running`。
2. 根据 `ActionPermit.granted_operations` 构造工具表。
3. agent 发起工具请求。
4. 系统执行工具并记录 structured observation。
5. agent 根据 observation 继续或收尾。
6. 若产生外部效果，必须有 structured receipt。
7. AgentTurn -> `closing -> completed`。

升级规则：

- 出现多步骤写入、真实 artifact、长时间命令、需要 checkpoint、需要恢复、需要用户批准时，ToolTurnLoop 必须停止并请求 `task_run`。

## 8. TaskRun 状态机执行细节

### 8.1 created -> admitted

输入：

- `TaskRunHandoffPacket` 或 explicit contract。

检查项：

- 目标非空。
- 权限已授权或可进入 waiting approval。
- artifact policy 与 completion contract 一致。
- runtime lane 存在。
- agent profile 存在。
- task_run_id 未冲突。

输出：

- `task_run_admitted` event。

失败：

- `task_run_admission_failed`。
- TaskRun -> `blocked` 或 `failed`。

### 8.2 admitted -> assembled

系统生成：

- `RuntimeStartPacket`
- `TaskContract`
- `PromptAssembly`
- `ToolRuntimePolicy`
- `ArtifactRepositoryBinding`
- `CheckpointPolicy`
- `CloseoutPolicy`

禁止：

- 禁止 assembly 层重写 `understood_user_goal`。
- 禁止 assembly 层发明新的 `task_goal_type`。
- 禁止 fallback 到 `general_response`。

### 8.3 assembled -> running

loop 初始化：

- 写 checkpoint。
- 写 `task_run_running`。
- 发 SSE `task_run_running`。
- 将 prompt、tools、policies 交给模型执行器。

agent 能力：

- 可以规划。
- 可以调用授权工具。
- 可以根据 observation 调整方案。
- 可以请求升级权限。
- 可以声明阻塞。

系统职责：

- 执行权限门禁。
- 执行工具。
- 记录 observation。
- 维护 budget/timeout/checkpoint。
- 不替 agent 改目标。

### 8.4 running -> waiting_approval

触发：

- agent 请求未授权操作。
- 文件写入越过边界。
- 命令风险过高。
- 网络/browser 权限不足。
- 用户确认是任务合同要求。

系统动作：

1. 创建 approval token。
2. 写 checkpoint。
3. TaskRun -> `waiting_approval`。
4. AgentTurn/CLI/SSE 返回审批请求。

恢复：

- 用户同意：TaskRun -> `running`，继续 checkpoint。
- 用户拒绝：agent 必须重新规划或 TaskRun -> `blocked`。

### 8.5 running -> recovering

触发：

- 模型调用失败。
- 工具失败。
- 进程中断。
- 服务重启。
- verification 失败但允许修复。

恢复输入：

- latest checkpoint。
- event log。
- observation ledger。
- artifact repository state。
- failed step。
- remaining budget。

恢复流程：

1. 系统进入 `recovering`。
2. 构造 recovery prompt 给 agent。
3. agent 输出 `RecoveryDecision`：

```json
{
  "authority": "task_run.recovery_decision",
  "task_run_id": "...",
  "recovery_action": "retry_step|revise_plan|request_approval|declare_blocked|fail",
  "reason": "",
  "preserve_artifacts": [],
  "discard_artifacts": [],
  "next_step": {},
  "needs_user_input": false
}
```

4. 系统校验 recovery action 不越过原合同。
5. 返回 `running`、`waiting_approval`、`blocked` 或 `failed`。

禁止：

- 禁止恢复时换任务。
- 禁止把 verification 失败改写成 completed。
- 禁止丢弃已产出 artifact 而无记录。

### 8.6 running -> verifying

触发：

- agent 输出 `ready_for_verification`。
- tool loop 达到完成条件。
- contract 要求的 steps 全部完成。

VerificationPacket：

```json
{
  "authority": "task_run.verification_packet",
  "task_run_id": "...",
  "claimed_completed_items": [],
  "artifact_refs": [],
  "observed_paths": [],
  "command_receipts": [],
  "acceptance_checks": [],
  "known_limitations": []
}
```

系统验证：

- artifact refs 存在。
- required files 存在且在允许目录。
- command receipts 真实来自工具执行。
- acceptance checks 通过。
- browser/screenshot/test 输出真实可读取。
- known limitations 不违反核心完成条件。

失败：

- 如果可修复：TaskRun -> `recovering`。
- 如果不可修复：TaskRun -> `failed`。

### 8.7 verifying -> finalizing

只有 verification 通过后进入 finalizing。

系统构造 CloseoutPacket：

```json
{
  "authority": "task_run.closeout_packet",
  "task_run_id": "...",
  "terminal_status": "completed",
  "final_content": "",
  "artifact_refs": [],
  "verification_summary": {},
  "memory_writeback": {},
  "trace_summary": {}
}
```

agent 可参与 final response 组织，但不能覆盖 verification 结果。

### 8.8 finalizing -> completed/failed/blocked/aborted

finalizing 必须完成：

- upsert TaskRun terminal state。
- append final event。
- write checkpoint terminal marker。
- commit assistant message。
- write memory maintenance receipt。
- update session live view。
- notify AgentTurn。
- SSE 发送 `done/error/stopped`。

任何一步失败：

- 如果 assistant message 已提交但 state 未更新，必须进入 recovery repair。
- 如果 state 已完成但 message 未提交，必须补交或返回明确 `finalization_partial_failure`。
- 不允许静默丢 terminal event。

## 9. TaskRun 步骤执行摘要

当前代码已有 `TaskRunLedger.step_runs`、`step_entered/step_completed/step_failed` 事件、`observation_refs`、`output_refs`、`diagnostics`、`execution_summary` 和 observation ledger。这些能记录“步骤状态”和“证据引用”，但还不是成熟 coding agent 的“每一步执行摘要”。

成熟 agent 需要为每个任务步骤生成结构化 `StepExecutionSummary`。它不是 UI 进度文案，也不是隐藏推理摘要，而是任务恢复、审查、最终验收和用户理解都可复用的步骤级执行记录。

### 9.1 StepExecutionSummary 模型

建议新增：

```json
{
  "authority": "task_run.step_execution_summary",
  "summary_id": "stepsummary:<task_run_id>:<step_id>:<attempt>",
  "task_run_id": "...",
  "step_id": "...",
  "attempt": 1,
  "status": "completed|failed|blocked|skipped",
  "action_summary": "",
  "inputs_used": [],
  "operations_performed": [],
  "files_read": [],
  "files_written": [],
  "commands_run": [],
  "artifacts_touched": [],
  "observations": [],
  "outputs": [],
  "verification": {
    "performed": false,
    "passed": false,
    "evidence_refs": [],
    "limitations": []
  },
  "failure": {
    "reason": "",
    "recoverable": false,
    "recovery_hint": ""
  },
  "next_step_recommendation": "",
  "hidden_reasoning_included": false
}
```

要求：

- `action_summary` 是执行事实摘要，不是“我准备做什么”。
- `observations` 只能引用真实 tool/model observation。
- `files_written` 必须来自 structured tool receipts 或 artifact records。
- `commands_run` 必须来自 command receipts。
- `verification.evidence_refs` 必须指向真实验证证据。
- 不允许包含隐藏推理。
- 不允许用自然语言补造没有发生的操作。

### 9.2 生成时机

每个 TaskRun step 必须在以下时机生成或更新摘要：

```text
step_entered
-> 创建空 StepExecutionSummary 草稿，status=running 不对用户展示

step_completed
-> 根据 observation ledger、tool receipts、artifact records 生成 completed summary

step_failed
-> 根据失败事件、异常、partial observations 生成 failed summary

verification_completed
-> 回填 verification 字段

recovery_decision_completed
-> 回填 recovery_hint 或 next_step_recommendation
```

如果 step 没有工具动作而只由模型完成，也必须有 summary，至少记录：

- 本步骤做了什么判断或产出了什么。
- 使用了哪些上下文。
- 输出引用是什么。
- 是否需要后续验证。

### 9.3 生成责任边界

系统负责：

- 收集真实 observation、receipt、artifact refs。
- 生成不可伪造字段：文件、命令、artifact、验证结果。
- 校验 summary 中的 refs 是否真实存在。
- 持久化 summary。

agent 负责：

- 用简短、专业、可审查的语言总结本步骤实际完成内容。
- 说明阻塞、限制和建议的下一步。
- 不声称系统证据中不存在的动作。

推荐实现方式：

```text
StepSummaryBuilder
-> 输入 structured evidence packet
-> 调用 agent 生成 action_summary / limitation / next_step_recommendation
-> 系统合并不可伪造字段
-> StepSummaryValidator 校验
-> StepSummaryStore 持久化
```

### 9.4 Step summary prompt

该 prompt 只用于步骤摘要，不用于执行决策：

```text
你负责为当前任务步骤生成执行摘要。
你只根据系统提供的结构化证据、工具观察、文件记录、命令回执和 artifact refs 总结已经发生的事实。
不要写计划，不要写隐藏推理，不要补充没有证据的动作。
如果步骤失败，说明失败点、已完成部分、是否可恢复，以及建议下一步。
如果步骤成功，说明本步骤完成了什么、产生了什么输出、是否做过验证。
```

### 9.5 存储与展示

存储：

- `TaskStepRun.step_result_ref` 指向 `StepExecutionSummary.summary_id`。
- `TaskStepRun.diagnostics.step_summary_ref` 保存同一个 ref。
- event log 记录 `step_summary_recorded`。
- final `TaskResult` 包含 `step_summary_refs`。

展示：

- 普通用户默认看到压缩后的步骤摘要列表，不显示内部 id。
- 开发者/监控视图可展开每个 summary 的 refs、receipts、diagnostics。
- 最终回答可以引用“完成了哪些步骤、哪些通过验证、哪些有阻塞”，但不暴露 `task_run_id`。

### 9.6 恢复中的用途

恢复时必须读取：

- latest checkpoint。
- TaskRunLedger。
- StepExecutionSummary 列表。
- observation ledger。
- artifact repository。

恢复 prompt 应优先给 agent 步骤摘要，而不是完整原始日志。原始日志只在需要核验证据时提供。这能让长任务续跑更稳定，也能避免 agent 在恢复时重复已完成步骤。

### 9.7 验收标准

新增测试：

- 每个 completed step 都有 `StepExecutionSummary`。
- 每个 failed step 都有 failure summary 和 recoverability。
- summary 中的 files/artifacts/commands 必须来自真实 receipts。
- 没有工具动作的 model step 也有执行摘要。
- final TaskResult 包含 step summary refs。
- resume 时 recovery prompt 能读取 step summaries。

## 10. 收尾协议

### 10.1 AgentTurn 收尾

AgentTurn 收尾输入可能来自：

- DirectResponseLoop final answer。
- ReadOnlyInspectionLoop final answer。
- ToolTurnLoop final answer。
- TaskRun CloseoutPacket。
- Block/Clarification/Error packet。

统一收尾流程：

1. AgentTurn -> `closing`。
2. 构造 assistant payload。
3. 提交 session message。
4. 触发 memory maintenance。
5. 更新 turn terminal state。
6. 更新 live monitor。
7. SSE 发送 terminal event。

terminal event 规则：

- 成功：`done`。
- 失败：`error`。
- 用户停止：`stopped`。
- 等待审批：非 terminal，不能关闭 SSE，除非客户端协议要求返回 waiting 状态。

### 10.2 最终回答必须如实反映执行层级

普通回答：

- 不提 TaskRun。
- 不声称有 artifact。

轻量读取：

- 可以说明读取了哪些上下文。
- 不声称修改。

TaskRun 完成：

- 必须包含 artifact refs。
- 必须包含验证摘要。
- 默认不向普通用户展示 `task_run_id`；开发者模式、监控视图或用户要求运行详情时可以展示。

TaskRun 失败：

- 必须说明失败阶段。
- 必须说明已完成部分。
- 必须说明恢复入口。

### 10.3 防止重复收尾

需要 terminal idempotency key：

```text
terminal_key = <turn_id>:<terminal_status>:<source_ref>
```

重复 closeout 时：

- 不重复提交 assistant message。
- 不重复写 memory。
- 可以重复返回同一个 terminal event。

## 11. 失败恢复总则

### 11.1 AgentTurn 级失败

适用：

- understanding timeout。
- decision invalid。
- direct response timeout。
- permission denied。
- direct/tool turn exception。

处理：

1. 写 `agent_turn_failed/timed_out/blocked`。
2. 提交用户可见错误或澄清。
3. 不创建 TaskRun。
4. 保留 retry token。

Retry：

- 用户重试时新建 AgentTurn。
- 可引用上一轮 failed turn 的 diagnostics。
- 不复用未完成 TaskRun，因为没有 TaskRun。

### 11.2 TaskRun 级失败

适用：

- 已创建 TaskRun 后失败。

处理：

1. TaskRun 写失败 checkpoint。
2. TaskRun 状态进入 `recovering` 或 terminal failed。
3. AgentTurn 记录 active TaskRun 失败。
4. final answer 提供恢复入口。

Retry：

- 如果合同仍有效，resume 同一个 TaskRun。
- 如果用户改变目标，创建新 AgentTurn 和新 TaskRun。

### 11.3 服务重启恢复

启动时扫描：

- 非 terminal AgentTurn。
- 非 terminal TaskRun。
- waiting approval token。
- stale running checkpoint。

恢复策略：

- AgentTurn 在 `understanding/deciding/direct_responding/tool_turn_running` 且无 TaskRun：标记 `failed`，提示可重试。
- AgentTurn 在 `waiting_task_run`：读取 TaskRun 状态并同步。
- TaskRun 在 `running` 且有 checkpoint：进入 `recovering`。
- TaskRun 在 `waiting_approval`：保持等待。
- TaskRun 在 `finalizing`：执行 finalization repair。

## 12. Prompt 设计原则

### 12.1 系统给 agent 的理解 prompt

应该写成 agent 能理解的职责，而不是开发说明：

```text
你是本轮请求的理解决策者。
你先判断用户真正想达成什么，再判断本轮应该直接回答、请求澄清、读取上下文、使用工具、开启正式任务生命周期，还是拒绝执行。
你不执行任务，不调用工具，不编造已经完成的结果。
如果需要正式任务生命周期，你必须说明为什么普通回答不足以完成，并给出任务合同种子、资源边界和完成标准。
如果不需要正式任务生命周期，你不能输出 task_goal_type。
```

### 12.2 TaskRun 内 agent prompt

TaskRun 内 prompt 应该围绕具体角色、目标、边界、交付物和裁决要求：

```text
你是当前 TaskRun 的执行 agent。
你负责在给定合同和权限边界内完成任务。
你可以规划、读取、修改、运行验证命令，并根据工具观察调整执行。
你不能用自然语言声明代替真实交付物。
当你认为完成时，必须提交 artifact refs、验证结果和最终验收说明。
如果任务无法完成，你必须说明阻塞原因、已完成部分、恢复入口。
```

## 13. 代码改造阶段

### 阶段一：建立 AgentTurnController

新增：

- `backend/agent_runtime/turn_controller.py`
- `backend/agent_runtime/turn_models.py`
- `backend/agent_runtime/execution_decision.py`
- `backend/agent_runtime/execution_decision_runtime.py`

职责：

- 创建 `AgentTurnStarted`。
- 执行 RequestFacts / BoundaryPolicy / ContextCandidates。
- 调用模型生成 `AgentUnderstandingDecision` 和 `ExecutionDecision`。
- 超时、失败、阻断都生成用户可见事件。
- 根据 decision 分派 direct/tool/task_run。

### 阶段二：拆除 QueryRuntime 的 task-first 入口

修改：

- `backend/query/runtime.py`

目标：

- 不再无条件构造 `taskinst:...:general_response` 作为正式任务。
- 改为构造 `turn_id` 和 `agent_invocation_id`。
- 只在 `ExecutionDecision == task_run` 或显式 task selection 时生成 TaskRun 请求。

### 阶段三：重构 ModelTurnDecision

修改：

- `backend/agent_runtime/understanding/model_turn_decision.py`
- `backend/agent_runtime/understanding/model_turn_decision_runtime.py`

目标：

- 移除普通 turn 的 `task_goal_type_required`。
- `task_goal_type` 只属于 TaskRun contract projection。
- prompt 改成“理解 + 执行模式判断”，不是“任务类型分类器”。

### 阶段四：TaskRunLoop start API 正名

修改：

- `backend/harness/loop/agent_loop.py`
- `backend/harness/agent_harness.py`
- `backend/harness/service_host.py`
- `backend/harness/runtime/agent_assembly.py`

目标：

- `AgentHarness.run_stream()` 只接受正式 TaskRun request 或 explicit invocation。
- 增加 `start_from_contract` / `start_from_execution_decision` 概念。
- `runtime_host.start()` 之前必须已有合法 task lifecycle admission packet。

### 阶段五：补齐 AgentTurn 可观测性

新增或扩展：

- state index 中的 `agent_turns`
- event log 中的 turn scope
- live monitor 中的 current agent turn view

必须支持：

- 没有 TaskRun 的普通回答也能被监控。
- 理解决策超时能看到卡点。
- CLI/SSE 能收到 terminal event。
- `task_run_count: 0` 不再代表“系统没有响应信息”。

### 阶段六：长任务 artifacts 与恢复验收

在已有 artifact 机制上补强：

- TaskRun admission 必须绑定 artifact repository scope。
- 长任务 closeout 必须读取 artifact records。
- completion judgment 必须依赖结构化 evidence。
- 恢复时必须读取 artifact repository 和 observation ledger。
- final response 必须包含真实 artifact refs 或明确失败原因。

## 14. 必须删除或迁移的旧权责

以下逻辑如果仍在普通 chat 路径上做决定，需要删除或迁移：

- `QueryRuntime` 中默认 task instance 语义。
- 普通 turn 的 `task_goal_type_required`。
- assembly 阶段从普通 turn 强制投射 `task_goal_spec`。
- 任何 profile/route hint 在模型决策前决定任务类型的逻辑。
- 任何把自然语言完成宣告当完成证据的逻辑。

可以保留：

- 显式 task selection。
- 显式 graph/stage contract。
- 路径、后缀、显式资源引用等事实提取。
- 权限门禁。
- artifact 结构化校验。

## 15. 验收标准

### 15.1 普通聊天

输入普通问题，系统应：

- 创建 AgentTurn。
- 不创建 TaskRun。
- 返回 `done`。
- session monitor 能看到最近 turn 状态。

### 15.2 澄清

输入信息不足请求，系统应：

- 创建 AgentTurn。
- 返回 clarification。
- 不创建 TaskRun。
- 不伪造任务失败。

### 15.3 轻量审查

输入“审查这段代码/解释这个文件”，系统可选择 read-only inspection：

- 可以读取上下文。
- 不写文件。
- 默认不创建 TaskRun。
- 如果 agent 判断范围扩大，可解释并升级为 TaskRun。

### 15.4 显式任务合同

输入已绑定 task/graph/stage 的请求，系统应：

- 直接进入 TaskRun admission。
- 不让普通 chat decision 覆盖合同。
- 保留合同目标和权限边界。

### 15.5 agent 自主开启长任务

输入复杂开发/修复/生成 artifact 请求，agent 可判断 `execution_mode=task_run`：

- TaskRun 由 loop 创建。
- artifact repository 绑定成功。
- 执行、验证、finalize 全链路可观测。

### 15.6 理解决策超时

模拟模型决策超时，系统应：

- 有 AgentTurn 记录。
- SSE/CLI 返回 error 或 retryable failure。
- 不出现静默无消息。
- 不创建半截 TaskRun。

### 15.7 长任务完成验收

长任务必须：

- 有真实 artifact refs。
- 有结构化 verification evidence。
- completion judgment 通过。
- TaskRun 才能 completed。

### 15.8 状态机验收

新增状态机测试：

- AgentTurn 每个非 terminal 状态都有 terminal 出口。
- Direct answer 不创建 TaskRun。
- ToolTurn 升级 TaskRun 时必须生成 HandoffPacket。
- TaskRun admission 失败不会留下不可见半截运行。
- TaskRun finalization 失败可 repair。
- 服务重启后 stale AgentTurn/TaskRun 可被正确恢复或标记失败。

## 16. 推荐测试命令

先补 focused tests：

```powershell
python -m pytest backend/tests/query_runtime_runtime_loop_regression.py -q
python -m pytest backend/tests/model_turn_decision_validation_regression.py -q
python -m pytest backend/tests/completion_judgment_regression.py -q
python -m pytest backend/tests/task_graph_artifact_validation_test.py -q
```

再做真实 CLI/SSE 实测：

```powershell
python -m backend.cli.main --api-base http://127.0.0.1:8003/api --verbose send "你好，简单解释一下这个项目当前 agent harness 是做什么的"
python -m backend.cli.main --api-base http://127.0.0.1:8003/api --verbose send "请创建 output/e2e_completion_artifact.md，写入 completion evidence e2e，并验证文件真实存在"
```

第一条应无 TaskRun 或仅有 AgentTurn；第二条应由 agent decision 开启 TaskRun，并最终绑定真实 artifact。

## 17. 实施顺序

推荐按以下顺序一次性推进，每阶段必须有测试保护：

1. 新建 AgentTurn/ExecutionDecision 数据结构和测试。
2. 接入 QueryRuntime，但先保持 TaskRun 路径可用。
3. 移除普通 chat 的 task-first 强制路径。
4. 拆掉普通 turn 的 `task_goal_type_required`。
5. 改造 harness 入口，使 TaskRun 只从合同或 execution decision 开启。
6. 补监控和 CLI/SSE terminal 事件。
7. 补长任务 artifact/recovery/final acceptance 测试。
8. 删除旧测试中保护 task-first 行为的断言。

最终目标是：系统不替 agent 做语义决定，agent 不绕过系统权限和证据边界；TaskRun 成为 loop 明确开启、可恢复、可验收的一段任务生命周期。

