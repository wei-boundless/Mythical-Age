# 成熟 Vibe Coding Agent 非并发能力升级计划

状态：待确认实施。

本文只覆盖并发执行之外的成熟 coding agent 能力升级。多工具并发、批量 `tool_calls` 协议和并行调度由用户另行推进，本文把它们视为前置输入，不重复设计。

本文依据仅限：

- 当前项目源码。
- 本地 Codex 源码：`D:\AI应用\openai-codex`。
- 本地 Claude Code 源码：`D:\AI应用\claude-code-nb-main`。

旧计划文档不作为本文设计依据。本文是新的升级蓝图，不继承旧文档里的阶段、命名或结论。

## 0. 结论

当前项目已经有 mature agent 的局部零件，但还没有形成 Codex / Claude Code 级别的稳定 coding loop。并发执行之外，最需要升级的是六条权威链：

1. 工具执行权威链：`ToolControlPlane` 已存在，但 `ToolExecutor` 仍有 task-run 与 agent-turn 双执行核心。
2. 文件状态权威链：`FileStateAuthority` 已存在，但主要从 observations 重建，还不是 task-local 持久状态。
3. 恢复策略权威链：协议修复、拒绝恢复、重复调用拦截、任务恢复分散在 task executor 多处逻辑里。
4. 上下文替换与 resume 权威链：已有 replacement store 与 dynamic context，但还没有覆盖所有 tool result / observation / subagent result 的稳定重放契约。
5. Subagent 生命周期权威链：已有 spawn/send/wait/close，但父子上下文隔离、结果摘要、abort 继承、pending message drain 还不够成熟。
6. Vibe coding 前端工作台：当前 `CodeEnvironmentView` 基本只显示环境和 Git 状态，不足以支撑用户理解“正在读、改、测、等审批、失败恢复、子 agent 进度”。

目标不是新增一套 vibe coding 专属旧壳，而是把通用 coding agent runtime 做成熟。`env.coding.vibe_workspace` 只消费这些能力，不应该成为主链路里到处硬编码的特殊分支。

## 1. 当前源码事实

### 1.1 已有正确基础

`RuntimeToolControlPlane` 已经承担工具准入、ActionPermit、capability membership、OperationGate 和 supervisor 检查。当前入口在：

```text
backend/runtime/tool_runtime/tool_control_plane.py:104
```

关键事实：

- `invoke()` 先检查 `_action_permit_denial()`。
- 再检查 `_membership_denial()`。
- task-run 路径会生成 directive、runtime action、sandbox policy、file policy、resource policy。
- 权限不通过时返回 model-visible observation，而不是直接执行工具。

`ToolResultEnvelope` 已经包含成熟 agent 所需的多数事件字段：

```text
backend/runtime/tool_runtime/tool_result_envelope.py:10
```

包括：

- `tool_call_id`
- `action_request_id`
- `caller_kind`
- `caller_ref`
- `artifact_refs`
- `file_state_events`
- `artifact_state_events`
- `verification_events`
- `command_receipt`
- `execution_receipt`
- `idempotency_key`

`ProtocolSanitizer` 已经能在模型调用前修复 tool protocol：

```text
backend/runtime/model_gateway/protocol_sanitizer.py:21
```

它会丢弃 orphan tool output，并给未完成的 tool calls 注入 aborted tool output。这是成熟 agent 的必要底座。

`FileStateAuthority` 已经能从工具观察中构建文件状态投影：

```text
backend/runtime/memory/file_state_authority.py:71
```

它能消费 envelope 或 legacy payload，并维护 read ranges、search hits、write events、content sha、exists 等字段。

`DynamicContextManager` 已经有 context projection、tool result replacement、observation projection、runtime delta、task state projection：

```text
backend/harness/runtime/dynamic_context/manager.py:33
```

它当前会在 execution projection 没有 file state 时，从 observations 重建 `file_state`。

`SubagentControl` 已经提供子 agent 生命周期工具：

```text
backend/harness/agent_control/controller.py:83
```

它能 spawn child task run / agent run，记录 parent-to-child message，并通过 runtime host 启动后台 executor。

### 1.2 当前主要断点

#### 断点 A：工具执行仍有双核心

当前 `ToolExecutor.execute_control_plane_request()` 对 task-run 走 `run()`，非 task-run 走 `_run_core()`：

```text
backend/runtime/tool_runtime/tool_executor.py:189
```

这意味着同一个工具结果 envelope、错误处理、idempotency、file state events、artifact events 可能因为 caller kind 不同而走不同路径。成熟 agent 不应该在执行核心层保留这种双主链。

#### 断点 B：FileStateAuthority 不是持久权威

当前 file state 的主要入口仍是：

```text
FileStateAuthority.from_observations(...)
```

也就是从观察日志重建。这适合首批投影，不适合成熟 coding agent。成熟状态需要 task-local 持久对象，覆盖：

- 文件 path canonicalization。
- content hash。
- mtime。
- read windows。
- partial read coverage。
- search hit provenance。
- write 后 stale 标记。
- resume 后恢复。
- subagent clone / merge。

#### 断点 C：恢复策略分散

当前恢复相关逻辑分布在：

```text
backend/harness/loop/task_executor.py
backend/harness/loop/task_run_recovery_state.py
backend/runtime/model_gateway/protocol_sanitizer.py
backend/runtime/tool_runtime/tool_control_plane.py
```

这些逻辑各自能处理一部分情况，但没有统一 `RecoveryPolicy` 或 `RecoveryDecision`：

- 模型输出格式错误。
- admission denied。
- repeated admission denied。
- repeated read-only tool call。
- tool execution failed。
- completion verification failed。
- task step budget exceeded。
- user pause / stop / replan。

成熟 agent 的恢复策略必须能被测试和审计，不应靠 task executor 内部大量分支隐式决定。

#### 断点 D：上下文替换还没有成为 resume 硬契约

`DynamicContextManager` 和 replacement store 已存在，但现在更像投影优化，而不是“恢复时必须重放的上下文契约”。Claude Code 明确持久化 `contentReplacements`，用于 resume reconstruction；本项目需要把 replacement decision 从动态优化升级为可恢复状态。

#### 断点 E：Subagent 生命周期缺少成熟父子隔离协议

当前 subagent 能被创建和等待，但还缺成熟 coding agent 中常见的几类契约：

- 父 agent 的 abort 是否传播给 child。
- background subagent 的 pending message 如何在 tool-round boundary drain。
- 子 agent 原始日志不进入父上下文，只允许 summary / refs / progress delta。
- 子 agent result 如何进入 `ToolResultEnvelope`、`FileStateAuthority`、`ArtifactAuthority`。
- 子 agent 的 file state snapshot 是 clone、只读继承还是可 merge。

#### 断点 F：Vibe coding 前端缺少工作台级反馈

当前 `CodeEnvironmentView` 主要加载：

```text
getCodeEnvironment(host)
getCodeEnvironmentGitStatus()
```

并显示错误和 Git 浮窗：

```text
frontend/src/components/workspace/views/CodeEnvironmentView.tsx:147
```

`PublicRunActivity` 已能把部分 runtime attachments 映射成读、搜、写、命令、artifact 的公开活动：

```text
frontend/src/components/chat/PublicRunActivity.tsx:85
```

但 vibe coding 需要更完整的 workbench surface：

- 文件读写状态。
- 当前 diff。
- 命令和测试输出。
- approval request。
- 子 agent 状态。
- 失败恢复建议。
- task-local file state。
- artifact / verification 状态。

## 2. 成熟参考架构

### 2.1 Codex 可借鉴的不变量

Codex 的成熟能力不是“能调用工具”，而是把工具执行变成可追踪 turn item / event / approval / diff surface。

Codex app-server 文档明确 turn events：

```text
D:\AI应用\openai-codex\codex-rs\app-server\README.md:1234
```

关键事件包括：

- `turn/started`
- `turn/completed`
- `turn/diff/updated`
- `turn/plan/updated`
- `item/started`
- `item/completed`
- `commandExecution`
- `fileChange`
- `mcpToolCall`
- `collabToolCall`
- `contextCompaction`

审批也是 turn/item lifecycle 的一部分：

```text
D:\AI应用\openai-codex\codex-rs\app-server\README.md:1323
```

命令和文件修改 approval 都有固定顺序：

```text
item/started
requestApproval
client response
serverRequest/resolved
item/completed
```

这说明成熟前端不是展示内部日志，而是消费稳定 runtime item lifecycle。

Codex 工具执行也有明确 cancellation / terminal outcome：

```text
D:\AI应用\openai-codex\codex-rs\core\src\tools\parallel.rs:82
```

即使本文不设计并发，也需要借鉴它的工具执行不变量：

- 每个 tool call 有 call id。
- 每个 tool call 有 terminal outcome。
- cancellation 不能留下缺失 output。
- runtime 必须能产出可记录、可展示、可恢复的工具结果。

### 2.2 Claude Code 可借鉴的不变量

Claude Code 的 `query.ts` 在 abort 时会补齐缺失 tool_result：

```text
D:\AI应用\claude-code-nb-main\query.ts:1011
```

这和本项目 `ProtocolSanitizer` 的方向一致，但 Claude Code 把它作为 streaming loop 的硬规则，避免工具调用与工具结果不成对。

Claude Code 在工具批次完成后生成 tool use summary：

```text
D:\AI应用\claude-code-nb-main\query.ts:1411
```

这个 summary 不是 UI 装饰，而是下一轮上下文压缩和用户可见进度的基础。

Claude Code 的 subagent task state 包含：

```text
D:\AI应用\claude-code-nb-main\tasks\LocalAgentTask\LocalAgentTask.tsx:116
```

关键字段包括：

- `abortController`
- `progress`
- `messages`
- `lastReportedToolCount`
- `lastReportedTokenCount`
- `isBackgrounded`
- `pendingMessages`
- `retain`
- `diskLoaded`
- `evictAfter`

子 agent 注册时可以继承 parent abort controller：

```text
D:\AI应用\claude-code-nb-main\tasks\LocalAgentTask\LocalAgentTask.tsx:460
```

Claude Code 还把 `contentReplacements` 持久化到 transcript metadata：

```text
D:\AI应用\claude-code-nb-main\types\logs.ts:52
```

并定义 replacement 记录用于 resume reconstruction：

```text
D:\AI应用\claude-code-nb-main\types\logs.ts:174
```

这说明成熟 coding agent 的上下文压缩不是临时投影，而是可恢复、可重放的状态。

## 3. 目标权威链

目标架构固定为：

```text
RequestFacts
-> BoundaryPolicy
-> ContextSnapshot
-> ModelTurnDecision
-> ActionPermit
-> RuntimeExecutionPacket
-> ToolControlPlane
-> ToolExecutionCore
-> ToolResultEnvelope
-> RuntimeStateAuthorities
-> StableDynamicContext
-> PresentationWorkbench
```

各层职责如下。

### 3.1 RequestFacts

只记录用户输入、当前 session、active task、环境、可用工作区。不判断是否该执行工具，不猜测用户目标。

### 3.2 BoundaryPolicy

决定本轮允许什么行为：回答、询问、持续任务、读文件、写文件、命令、浏览器、git、审批。它不执行工具，不生成 prompt 文案。

### 3.3 ContextSnapshot

汇总当前可见 facts：

- file state。
- artifact state。
- tool result refs。
- replacement state。
- subagent summaries。
- runtime recovery state。
- git status。
- environment profile。

它只提供候选上下文，不替模型决定动作。

### 3.4 ModelTurnDecision

模型只负责语义决策：回答、询问、调用工具、阻塞、完成。它不能绕过 ActionPermit，也不能直接写权限结果。

### 3.5 ActionPermit

唯一授权层。它覆盖：

- tool membership。
- operation gate。
- sandbox。
- file policy。
- approval state。
- idempotency key seed。

`ToolControlPlane` 只消费 permit，不反向改写用户意图。

### 3.6 RuntimeExecutionPacket

为真实执行创建固定输入：

- caller kind / caller ref。
- tool call id。
- action request id。
- directive。
- sandbox policy。
- file policy。
- resource policy。
- execution receipt seed。
- cancellation handle。

### 3.7 ToolControlPlane

只做：

- permit validation。
- membership validation。
- supervision。
- operation gate。
- handler selection。
- denied / needs_approval observation。
- execution receipt lifecycle。

禁止：

- 自己发明第二套权限判断。
- 在 handler 里硬编码 subagent 前缀特判。
- 因 caller kind 不同走不同结果 envelope 语义。

### 3.8 ToolExecutionCore

统一 task-run 和 agent-turn 的真实工具执行核心。caller kind 只能作为上下文字段，不允许决定不同执行架构。

目标是删除 `run()` / `_run_core()` 的双主链，只保留一个 core：

```text
execute_core(ToolInvocationContext, ToolExecutionContract) -> ToolResultEnvelope
```

### 3.9 ToolResultEnvelope

所有工具、subagent control、shell、git、file edit、browser、image、MCP 都必须输出 envelope-compatible result。

envelope 是后续状态权威的唯一输入，不允许前端、task executor、dynamic context 再从 raw text 里二次猜产物或文件状态。

### 3.10 RuntimeStateAuthorities

至少包含：

- `FileStateAuthority`
- `ArtifactAuthority`
- `VerificationAuthority`
- `RecoveryAuthority`
- `SubagentAuthority`

这些 authority 消费 envelope events，维护 task-local state。

### 3.11 StableDynamicContext

只消费 authority projection 和 replacement records，输出短、稳定、可重放的模型上下文。

### 3.12 PresentationWorkbench

前端只消费 stable runtime items / authority projections，不把 raw logs 当主界面。

## 4. 分阶段升级计划

### Phase 0：源码基线和失败用例锁定

目标：

- 锁定当前真实行为。
- 建立并发之外的成熟性失败测试。
- 避免后续靠 prompt、mock 或兼容旧链路制造通过。

新增或更新测试：

```text
backend/tests/tool_executor_single_core_regression.py
backend/tests/file_state_authority_persistence_regression.py
backend/tests/recovery_policy_authority_regression.py
backend/tests/dynamic_context_resume_contract_regression.py
backend/tests/subagent_authority_isolation_regression.py
frontend/src/components/workspace/views/CodeEnvironmentWorkbench.test.tsx
frontend/src/lib/runtime-monitor/codingWorkbenchProjection.test.ts
```

验收：

- 测试能复现当前缺口。
- 不降低现有断言。
- 不 mock 掉核心 tool execution、file state、subagent lifecycle。

### Phase 1：ToolExecutionCore 收敛

目标：

- 删除 task-run `run()` 与 agent-turn `_run_core()` 的语义分裂。
- 保留 caller kind 作为 context，不保留双执行架构。

设计：

新增：

```text
backend/runtime/tool_runtime/execution_contract.py
backend/runtime/tool_runtime/execution_core.py
```

`ToolExecutionContract` 固定字段：

- `invocation_context`
- `tool_name`
- `tool_args`
- `runtime_action`
- `directive`
- `sandbox_policy`
- `file_management_policy`
- `execution_record`
- `max_result_size_chars`
- `cancellation_ref`

改造：

```text
backend/runtime/tool_runtime/tool_executor.py
```

- `execute_control_plane_request()` 只构造 `ToolExecutionContract`。
- task-run 和 agent-turn 都调用同一个 `execute_core()`。
- `run()` 和 `_run_core()` 先变成薄 wrapper。
- cutover 后删除 wrapper 或保留仅测试辅助入口，不能被 runtime 主链调用。

验收：

- task-run 和 agent-turn 同一工具输出相同 envelope shape。
- permission denied / tool failed / command failed 都返回 envelope-compatible observation。
- `idempotency_key` 在 caller kind 不同情况下仍稳定。

### Phase 2：Handler Registry 正式化

目标：

- 让 subagent、native tool、MCP、shell/git/browser 等都通过 handler registry 进入统一控制平面。
- 移除 operation prefix 特判。

改造：

```text
backend/runtime/tool_runtime/tool_control_plane.py
backend/capability_system/tools/native_tool_catalog.py
backend/capability_system/tools/tool_units/subagent_control_tool.py
```

新增：

```text
backend/runtime/tool_runtime/handler_registry.py
backend/runtime/tool_runtime/handlers/native_handler.py
backend/runtime/tool_runtime/handlers/subagent_handler.py
backend/runtime/tool_runtime/handlers/mcp_handler.py
```

验收：

- `spawn_subagent` 等工具通过正式 handler 执行。
- `ToolControlPlane` 不再根据 operation prefix 直接分支执行 subagent。
- handler 只负责执行，不负责授权。

### Phase 3：FileStateAuthority 持久化

目标：

- 从“从 observations 重建投影”升级为 task-local 文件状态权威。

新增：

```text
backend/runtime/memory/file_state_store.py
backend/runtime/memory/file_state_models.py
```

核心模型：

```text
TaskFileState
- path
- canonical_path
- exists
- mtime
- size_bytes
- content_sha256
- read_windows
- search_hits
- write_events
- stale_reason
- last_read_observation_ref
- last_write_observation_ref
- last_tool_call_id
- producer_agent_run_ref
- source_scope: parent|subagent|merged
```

核心 API：

```text
load(task_run_id) -> FileStateAuthority
save(authority)
apply_envelope(envelope)
mark_stale(path, reason)
clone_for_subagent(parent_task_run_id, child_task_run_id, scope)
merge_child_result(parent_task_run_id, child_task_run_id, merge_policy)
projection(limit, changed_only=False)
```

改造：

```text
backend/harness/runtime/dynamic_context/manager.py
backend/harness/loop/task_executor.py
backend/runtime/tool_runtime/tool_result_envelope.py
backend/runtime/tool_runtime/native_tools.py
```

验收：

- read 后记录 hash/mtime/read window。
- write/edit 后旧 read windows 标记 stale。
- resume 后 file state 不依赖重新扫描全部 observation。
- subagent 文件状态不会自动污染父状态，必须通过 merge policy 进入父 task。

### Phase 4：Artifact / Verification 状态从 raw extraction 收敛到 envelope events

目标：

- artifact refs、verification status 不再由 task executor、frontend、dynamic context 多头抽取。
- `ToolResultEnvelope.artifact_state_events` 和 `verification_events` 成为唯一入口。

改造：

```text
backend/artifact_system/artifact_authority.py
backend/harness/loop/task_executor.py
backend/harness/runtime/dynamic_context/manager.py
frontend/src/components/chat/PublicRunActivity.tsx
```

新增：

```text
backend/runtime/memory/verification_authority.py
backend/tests/verification_authority_regression.py
```

验收：

- shell test command 通过 / 失败有 verification event。
- artifact 是否存在、是否发布、是否验证，只从 authority projection 展示。
- 前端不再从 raw text 猜 artifact。

### Phase 5：RecoveryAuthority 与 RecoveryPolicy

目标：

- 把 task executor 内部分散恢复逻辑收敛成可测试的恢复决策。

新增：

```text
backend/harness/loop/recovery_policy.py
backend/harness/loop/recovery_authority.py
```

输入：

- `ModelProtocolError`
- `AdmissionDenied`
- `ToolExecutionFailed`
- `RepeatedToolCall`
- `CompletionVerificationFailed`
- `ContextOverflow`
- `UserControlSignal`
- `StepBudgetExceeded`

输出：

```text
RecoveryDecision
- decision: continue|retry|ask_user|block|pause|replan|stop
- model_visible_observation
- retry_budget_delta
- suppress_repeated_action
- user_visible_summary
- recovery_action
```

改造：

```text
backend/harness/loop/task_executor.py
backend/harness/loop/task_run_recovery_state.py
backend/runtime/model_gateway/protocol_sanitizer.py
```

验收：

- repeated admission denied 不再散落计数。
- tool 参数错误能反馈给模型重试，但有预算。
- 同一失败不会无限重复。
- user pause/stop/replan 优先级高于自动恢复。

### Phase 6：StableDynamicContext 与 replacement resume 契约

目标：

- replacement decision 成为持久、可恢复、可重放契约。
- 所有大型 tool result / observation / subagent result 都必须有 stable ref。

改造：

```text
backend/harness/runtime/dynamic_context/replacement_store.py
backend/harness/runtime/dynamic_context/tool_result_projector.py
backend/harness/runtime/dynamic_context/observation_projector.py
backend/harness/runtime/dynamic_context/manager.py
```

新增：

```text
backend/harness/runtime/dynamic_context/resume_manifest.py
```

`ResumeManifest` 包含：

- session id。
- task run id。
- replacement records。
- file state projection ref。
- artifact projection ref。
- subagent summary refs。
- context budget report。
- sanitizer diagnostics ref。

验收：

- resume 后同一 tool result 不会重新以 raw text 进入模型。
- replacement refs 可反查完整内容。
- prompt cache stable sections 不被 volatile result 破坏。
- subagent sidechain replacement 不混入 main thread。

### Phase 7：SubagentAuthority 成熟化

目标：

- 子 agent 生命周期从“能 spawn”升级为“可观察、可取消、可摘要、可恢复、可隔离”。

新增：

```text
backend/harness/agent_control/subagent_authority.py
backend/harness/agent_control/subagent_result_envelope.py
```

改造：

```text
backend/harness/agent_control/controller.py
backend/capability_system/tools/tool_units/subagent_control_tool.py
backend/runtime/tool_runtime/tool_control_plane.py
```

模型：

```text
SubagentRunState
- subagent_run_ref
- parent_agent_run_ref
- child_task_run_ref
- status
- abort_ref
- pending_messages
- progress
- result_summary_ref
- artifact_refs
- file_state_merge_policy
- token_usage
- tool_use_count
```

规则：

- 父 abort 默认传播到 foreground child。
- background child 可独立运行，但必须有 close / wait / retrieve result。
- 父线程只接收 summary、refs、progress delta。
- child raw transcript 只进入 sidechain，不进入 parent model context。
- child file state 默认 isolated，显式 merge 才进入 parent。

验收：

- 子 agent 失败不会污染父 agent final answer。
- 子 agent 完成后父 agent 可看到 summary/ref，不看到原始长日志。
- parent stop 能取消应取消的 child。
- background child 可恢复和查询。

### Phase 8：Code Environment 安全边界和 sidecar gating

目标：

- `PiSidecarManager` 从 read-only smoke 逐步升级，但必须先有项目自有 permission / change-set gate。

当前源码说明：

```text
backend/code_environment/pi_rpc_process.py:15
```

当前 sidecar 注释明确只支持 read-only smoke commands，prompting/editing 需要后续 permission 和 change-set gates。

改造：

```text
backend/code_environment/pi_rpc_process.py
backend/code_environment/pi_environment.py
backend/runtime/tool_runtime/tool_control_plane.py
backend/permissions/operation_gate.py
```

新增：

```text
backend/code_environment/change_set_gate.py
backend/code_environment/code_action_receipt.py
```

规则：

- Pi sidecar 不直接获得写文件或命令权限。
- 所有 sidecar write/edit/shell 都必须转成本项目 ToolInvocationRequest。
- 所有 change set 都必须生成 diff、approval request、execution receipt。
- 不允许 sidecar 绕过 `FileStateAuthority` 和 `ArtifactAuthority`。

验收：

- read-only sidecar command 保持可用。
- 未授权 edit/shell 被拒绝并返回 observation。
- 授权 edit 产生 file_state_event 和 diff。

### Phase 9：Vibe Coding Workbench 前端

目标：

- 从 Git 浮窗升级为 coding workbench。
- 前端展示权威状态，不展示 raw runtime logs 作为主要进展。

改造：

```text
frontend/src/components/workspace/views/CodeEnvironmentView.tsx
frontend/src/components/chat/PublicRunActivity.tsx
frontend/src/lib/runtime-monitor/presentation.ts
frontend/src/lib/runtime-monitor/types.ts
frontend/src/lib/api.ts
```

新增：

```text
frontend/src/components/workspace/views/code-environment/CodeWorkbenchShell.tsx
frontend/src/components/workspace/views/code-environment/FileStatePanel.tsx
frontend/src/components/workspace/views/code-environment/DiffReviewPanel.tsx
frontend/src/components/workspace/views/code-environment/CommandRunPanel.tsx
frontend/src/components/workspace/views/code-environment/SubagentPanel.tsx
frontend/src/components/workspace/views/code-environment/VerificationPanel.tsx
frontend/src/lib/runtime-monitor/codingWorkbenchProjection.ts
```

WorkBench 信息架构：

```text
Top bar:
- environment status
- branch
- dirty count
- active task
- permission mode

Left:
- file state
- changed files
- stale reads

Center:
- active plan / current action
- diff / command output / test output

Right:
- approvals
- subagents
- artifacts
- verification

Bottom:
- recoverable errors
- retry / resume / stop controls
```

验收：

- 读文件、改文件、运行测试、生成 artifact 的状态都能看到。
- approval request 显示在当前 task 上，不混成普通聊天文本。
- 子 agent 能显示 running/completed/failed 和 summary refs。
- stale file read 明确提示，需要重读时能显示原因。

### Phase 10：旧链路删除和 cutover

目标：

- 不保留无用旧链路。
- 不以兼容为理由让旧结构继续参与主执行。

删除条件：

- `ToolExecutionCore` 覆盖 task-run 与 agent-turn 后，删除 runtime 主链对旧 `run()` / `_run_core()` 语义分支的依赖。
- `FileStateAuthority` 持久化后，dynamic context 不再从 full observations 重建主 file state，只允许作为 migration fallback，并在 cutover 后删除。
- `ArtifactAuthority` / `VerificationAuthority` 切换后，删除 raw text artifact extraction 的主链调用。
- `RecoveryAuthority` 切换后，删除 task executor 内部重复恢复分支。
- `SubagentAuthority` 切换后，删除 subagent operation prefix 特判。

验收：

- 搜索旧入口不再被 runtime 主链调用。
- 旧测试如果只保护旧结构，应删除或改成保护目标行为。
- 无新增兼容 shim。

## 5. 固定执行流

非并发版成熟执行流如下：

```text
1. 用户输入进入 RequestFacts。
2. BoundaryPolicy 确定本轮能力边界。
3. ContextSnapshot 从 FileStateAuthority / ArtifactAuthority / SubagentAuthority / RecoveryAuthority 读取状态。
4. StableDynamicContext 生成模型上下文。
5. ProtocolSanitizer 修正模型消息协议。
6. 模型给出 ModelTurnDecision。
7. ActionPermit 授权具体动作。
8. RuntimeExecutionPacket 固定执行输入。
9. ToolControlPlane 选择 handler 并监督执行。
10. ToolExecutionCore 真实执行。
11. ToolResultEnvelope 记录结果。
12. RuntimeStateAuthorities 消费 envelope events。
13. RecoveryAuthority 判断是否继续、重试、暂停、阻塞或完成。
14. PresentationWorkbench 消费 authority projection 展示。
15. Final answer 只引用 canonical output / artifact / verification refs。
```

## 6. 文件级执行清单

### 后端工具执行

```text
backend/runtime/tool_runtime/execution_contract.py
backend/runtime/tool_runtime/execution_core.py
backend/runtime/tool_runtime/tool_executor.py
backend/runtime/tool_runtime/tool_control_plane.py
backend/runtime/tool_runtime/handler_registry.py
backend/runtime/tool_runtime/handlers/native_handler.py
backend/runtime/tool_runtime/handlers/subagent_handler.py
backend/runtime/tool_runtime/handlers/mcp_handler.py
```

### 后端状态权威

```text
backend/runtime/memory/file_state_authority.py
backend/runtime/memory/file_state_store.py
backend/runtime/memory/file_state_models.py
backend/artifact_system/artifact_authority.py
backend/runtime/memory/verification_authority.py
backend/harness/loop/recovery_authority.py
backend/harness/loop/recovery_policy.py
```

### 上下文和 resume

```text
backend/harness/runtime/dynamic_context/manager.py
backend/harness/runtime/dynamic_context/replacement_store.py
backend/harness/runtime/dynamic_context/tool_result_projector.py
backend/harness/runtime/dynamic_context/observation_projector.py
backend/harness/runtime/dynamic_context/resume_manifest.py
backend/runtime/model_gateway/protocol_sanitizer.py
```

### Subagent

```text
backend/harness/agent_control/controller.py
backend/harness/agent_control/subagent_authority.py
backend/harness/agent_control/subagent_result_envelope.py
backend/capability_system/tools/tool_units/subagent_control_tool.py
```

### Code environment

```text
backend/code_environment/pi_environment.py
backend/code_environment/pi_rpc_process.py
backend/code_environment/change_set_gate.py
backend/code_environment/code_action_receipt.py
```

### 前端

```text
frontend/src/components/workspace/views/CodeEnvironmentView.tsx
frontend/src/components/workspace/views/code-environment/CodeWorkbenchShell.tsx
frontend/src/components/workspace/views/code-environment/FileStatePanel.tsx
frontend/src/components/workspace/views/code-environment/DiffReviewPanel.tsx
frontend/src/components/workspace/views/code-environment/CommandRunPanel.tsx
frontend/src/components/workspace/views/code-environment/SubagentPanel.tsx
frontend/src/components/workspace/views/code-environment/VerificationPanel.tsx
frontend/src/components/chat/PublicRunActivity.tsx
frontend/src/lib/runtime-monitor/codingWorkbenchProjection.ts
frontend/src/lib/runtime-monitor/presentation.ts
frontend/src/lib/runtime-monitor/types.ts
frontend/src/lib/api.ts
```

## 7. 验证矩阵

### 后端单元和回归

```text
python -m pytest ^
  backend/tests/tool_executor_single_core_regression.py ^
  backend/tests/runtime_tool_control_plane_regression.py ^
  backend/tests/tool_result_envelope_identity_regression.py ^
  backend/tests/file_state_authority_regression.py ^
  backend/tests/file_state_authority_persistence_regression.py ^
  backend/tests/artifact_authority_regression.py ^
  backend/tests/verification_authority_regression.py ^
  backend/tests/recovery_policy_authority_regression.py ^
  backend/tests/dynamic_context_replacement_store_regression.py ^
  backend/tests/dynamic_context_resume_contract_regression.py ^
  backend/tests/protocol_sanitizer_regression.py ^
  backend/tests/subagent_control_regression.py ^
  backend/tests/subagent_authority_isolation_regression.py ^
  backend/tests/code_environment_workspace_tree_regression.py ^
  backend/tests/code_environment_open_workspace_regression.py ^
  -q
```

### 前端回归

```text
npm test -- ^
  frontend/src/components/workspace/views/CodeEnvironmentWorkbench.test.tsx ^
  frontend/src/components/chat/PublicRunActivity.test.tsx ^
  frontend/src/lib/runtime-monitor/codingWorkbenchProjection.test.ts ^
  frontend/src/lib/runtime-monitor/runtimeMonitor.test.ts
```

### 真实运行验证

涉及运行链路时必须使用固定端口：

```text
后端：http://127.0.0.1:8003
前端：http://127.0.0.1:3000
前端 API Base：http://127.0.0.1:8003/api
```

真实场景：

1. 只读 coding 任务：读多个文件、搜索符号、file state 记录 read windows。
2. 修改 coding 任务：读文件、编辑文件、显示 diff、file state stale / refresh 正确。
3. 测试任务：运行测试命令，verification event 进入 workbench。
4. 权限拒绝：未授权写入或 shell 不执行，返回 observation，前端显示阻塞原因。
5. Resume：恢复任务后 tool result replacement、file state、artifact refs 不丢失。
6. Subagent：子 agent 运行、失败、完成都只向父线程返回 summary / refs。
7. Sidecar：Pi read-only command 可用，edit/shell 未授权时被项目 gate 拦截。

## 8. 风险和禁止事项

### 禁止用 prompt 修结构问题

工具执行双核心、file state 持久化、recovery policy、subagent 隔离都是结构问题。prompt 只能指导模型表达动作，不能替代 runtime 权威。

### 禁止保留旧链路兜底

除非存在明确 migration endpoint，否则旧 raw extraction、旧 observation rebuild、旧 subagent 特判、旧双执行核心都应在 cutover 后删除。

### 禁止让 frontend 猜 runtime 事实

前端只能消费 authority projection 和 stable lifecycle event。不能靠 raw text 正则判断 artifact、verification、file state。

### 禁止 sidecar 绕过项目权限

Pi sidecar 或任何外部 coding agent 只能作为工具执行后端，不能拥有直接写项目文件、执行 shell、提交 git 的权限。

### 禁止子 agent 污染父上下文

子 agent raw transcript、长 tool logs、临时推理不进入父模型上下文。父上下文只接收 summary、refs、progress delta 和明确 merge 后的 file/artifact state。

## 9. 最终验收标准

系统达到成熟 vibe coding agent 非并发能力后，应满足：

- task-run 和 agent-turn 工具执行使用同一个 execution core。
- 所有工具结果都有稳定 `ToolResultEnvelope`。
- 文件状态是 task-local 持久权威，不依赖每轮从 observation 全量重建。
- 写入后旧读取状态会被标记 stale，模型和前端都能看到。
- artifact / verification 状态来自 authority，不来自 raw text 猜测。
- recovery 决策由统一 authority 输出，重复失败有预算和抑制。
- replacement / resume 可重放，长 tool result 不破坏 prompt cache。
- subagent 隔离运行，父线程只接收 summary / refs。
- sidecar 不绕过本项目权限、diff、approval、receipt。
- 前端 workbench 清楚展示文件、diff、命令、测试、审批、子 agent、artifact 和恢复状态。
- 旧双链路、旧特判、旧 raw extraction 和保护旧结构的测试被删除或改成目标行为测试。

