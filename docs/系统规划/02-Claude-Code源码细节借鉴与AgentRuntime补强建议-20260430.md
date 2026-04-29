# Claude Code 源码细节借鉴与 AgentRuntime 补强建议

日期：2026-04-30  
定位：本文件基于本机 `D:/AI应用/claude-code-nb-main` 与 `D:/AI应用/Claude-Code-Source-Study-main` 的源码/源码研究材料，对照当前洪荒时代 AgentRuntime，提炼值得学习的工程细节，并转化为后续重构约束。

---

## 0. 阅读范围

本次重点阅读：

```text
D:/AI应用/claude-code-nb-main/query.ts
D:/AI应用/claude-code-nb-main/QueryEngine.ts
D:/AI应用/claude-code-nb-main/Tool.ts
D:/AI应用/claude-code-nb-main/Task.ts
D:/AI应用/claude-code-nb-main/tasks.ts
D:/AI应用/claude-code-nb-main/query/config.ts
D:/AI应用/claude-code-nb-main/query/tokenBudget.ts
D:/AI应用/claude-code-nb-main/tools/AgentTool/*
D:/AI应用/claude-code-nb-main/services/compact/*
D:/AI应用/claude-code-nb-main/utils/permissions/*
D:/AI应用/claude-code-nb-main/tools/BashTool/readOnlyValidation.ts
D:/AI应用/claude-code-nb-main/memdir/*
D:/AI应用/claude-code-nb-main/python_agent_memory/*
```

辅助对照：

```text
D:/AI应用/Claude-Code-Source-Study-main/docs/05-对话循环.md
D:/AI应用/Claude-Code-Source-Study-main/docs/06-上下文管理.md
D:/AI应用/Claude-Code-Source-Study-main/docs/16-权限系统.md
```

---

## 1. 总判断

Claude Code 最值得我们学习的不是“把所有逻辑塞进一个 query loop”，而是这些更底层的工程不变量：

```text
工具是完整契约，不只是函数。
权限是多层决策管线，不是 prompt 提示。
只读执行也需要严格验证，不是名字像 read 就 allow。
上下文压缩是多级压力响应，不是一次性摘要。
压缩后必须维护 API 消息不变量。
子 agent 必须有明确生命周期、权限模式、记忆范围和递归保护。
后台 / headless 场景不能弹窗，必须自动 deny 或走 hook。
feature flag 要区分编译期裁剪和运行期快照。
```

对我们当前架构的直接结论：

```text
当前 AgentRuntime 的分层方向比 Claude Code 更清楚；
但 Claude Code 在执行细节、安全验证、压缩恢复、任务生命周期上比我们成熟。
我们应该吸收它的合同细节，而不是回到 query 中央大循环。
```

---

## 2. 工具契约：Tool 不是函数，而是可验证资源

Claude Code 的 `Tool.ts` 把工具定义成一个很厚的 typed contract。它不仅有 `call()`，还包含：

```text
inputSchema / outputSchema
validateInput
checkPermissions
isConcurrencySafe
isReadOnly
isDestructive
isOpenWorld
requiresUserInteraction
interruptBehavior
maxResultSizeChars
mapToolResultToToolResultBlockParam
renderToolUseMessage / renderToolResultMessage
toAutoClassifierInput
preparePermissionMatcher
shouldDefer / alwaysLoad
```

值得我们学习的点：

1. `isConcurrencySafe` 默认 false。
2. `isReadOnly` 默认 false。
3. `maxResultSizeChars` 是工具契约的一部分，避免工具结果无限塞回上下文。
4. `backfillObservableInput` 只修改观测副本，不修改 API-bound 原始输入，保护 prompt cache。
5. `shouldDefer / alwaysLoad` 把工具发现和工具加载也合同化，而不是一次性把所有工具塞进 prompt。

落到我们这里：

```text
backend/operations/registry.py
backend/operations/requirements.py
backend/operations/policies.py
backend/skill_system/contracts.py
backend/workers/*
```

应补强：

```text
OperationDescriptor 增加：
  input_contract_ref
  output_contract_ref
  read_only
  destructive
  concurrency_safe
  open_world
  requires_user_interaction
  max_result_size
  interrupt_behavior
  deferred_loading
  always_load

ResourcePolicyBuilder 只能从这些 typed fields 生成 allowed / denied / requires_approval。
```

不要照搬：

```text
不要把 UI render 函数塞进后端 ToolContract。
我们只需要输出投影合同；UI 渲染应留在 frontend / OutputBoundary。
```

---

## 3. 权限系统：OperationGate 需要从单点检查升级为管线

Claude Code 的权限系统不是一个简单 `allowed_tools` 集合，而是管线：

```text
deny rule
ask rule
tool.checkPermissions
safety check
permission mode
allow rule
classifier / hook / headless deny
```

关键细节：

```text
deny 优先。
ask 规则在高信任模式下仍可生效。
safety check 不能被 bypassPermissions 简单跳过。
headless / background agent 遇到 ask，默认不能弹窗，应走 hook 或 deny。
auto classifier 有 denial tracking，连续拒绝后熔断。
dangerous allow rules 在 auto mode 入口会被剥离。
```

源码细节对我们很重要：

```text
utils/permissions/denialTracking.ts:
  maxConsecutive = 3
  maxTotal = 20

utils/permissions/dangerousPatterns.ts:
  python / node / bash / sh / ssh / npm run / npx 等 prefix allow 都被视为危险。

utils/permissions/permissions.ts:
  dontAsk: ask -> deny
  headless: ask -> hook or deny
```

落到我们这里：

```text
backend/operations/gate.py
backend/operations/policies.py
backend/orchestration/execution_preflight.py
backend/orchestration/runtime_directive.py
```

应补强：

```text
OperationGatePipeline:
  1. descriptor exists
  2. RuntimeDirective exists
  3. AdoptedResourcePolicy exists
  4. deny rule
  5. requires_approval rule
  6. operation-specific safety validator
  7. headless policy
  8. approval token
  9. allow

新增：
  PermissionMode
  ApprovalPolicy
  DenialTrackingState
  HeadlessPermissionPolicy
  DangerousAllowRuleStripper
```

不该现在做：

```text
不要急着引入 AI classifier。
我们可以先做 deterministic policy pipeline。
等 tool / shell / worker 真正恢复后，再讨论 classifier。
```

---

## 4. Bash / Shell 只读验证：不能只看工具名

Claude Code 的 `tools/BashTool/readOnlyValidation.ts` 很细。它不会因为命令看起来像 `git status`、`grep`、`ls` 就直接放行，而是做：

```text
shell parse
flag allowlist
UNC path 拒绝
变量展开拒绝
glob 展开拒绝
git -c / --exec-path / --config-env 拒绝
cd + git 复合命令拒绝
创建 git internal paths 后再跑 git 拒绝
bare git repo 结构拒绝
```

这给我们的提醒非常直接：

```text
未来恢复 shell/tool 执行时，read_only 不能是工具自报字段。
必须有 operation-specific validator。
```

落到我们这里：

```text
backend/operations/validators/shell_read_only.py
backend/operations/validators/filesystem_path.py
backend/operations/gate.py
```

最低实现建议：

```text
Phase 1 只支持显式 allowlisted read-only commands。
禁止 shell control operator。
禁止变量展开。
禁止 glob 参与写路径。
禁止 cd + git 组合。
禁止未知 flag。
禁止网络命令。
```

和当前原则的关系：

```text
这属于 OperationGate 的执行前复核，不属于 TaskSystem，也不属于 Prompt。
```

---

## 5. 上下文压缩：多级压力响应，而不是一个 compact 函数

Claude Code 的上下文管理是分层压力响应：

```text
token warning
microcompact
context collapse
session memory compact
full compact
reactive compact
blocking
```

值得我们吸收的细节：

1. 先做轻量清理，再做重型模型摘要。
2. 预留输出 token，不能把输入塞满窗口。
3. compact 有熔断器，连续失败后不再反复浪费 API。
4. session memory compact 可以直接使用会话记忆作为摘要，避免再次调用模型。
5. compact 后要做 cache cleanup，但子 agent compact 不能清理主线程模块缓存。

对应源码：

```text
services/compact/autoCompact.ts
services/compact/microCompact.ts
services/compact/sessionMemoryCompact.ts
services/compact/postCompactCleanup.ts
query/tokenBudget.ts
```

落到我们这里：

```text
backend/memory_system/compaction.py
backend/context_policy/package_builder.py
backend/runtime/agent_chain.py
```

应补强：

```text
ContextPressureState:
  token_usage
  effective_window
  warning_threshold
  compact_threshold
  blocking_threshold

CompactionStrategy:
  micro_trim
  session_memory_compact
  full_summary_compact
  reactive_compact

CompactionCircuitBreaker:
  consecutive_failures
  last_failure_reason
```

当前我们已经有 `MemoryCompactionPreview`，下一步应该让它从“诊断”升级为可被 `ContextPolicy` 消费的压力策略，但仍不能直接写 session memory。

---

## 6. 压缩后的 API 消息不变量

Claude Code 的 `sessionMemoryCompact.ts` 有一个非常关键的函数：

```text
adjustIndexToPreserveAPIInvariants()
```

它解决两个问题：

```text
不能切断 tool_use / tool_result 配对。
不能切断同一个 assistant message.id 下的 thinking / tool_use 分段。
```

如果 compact 从错误位置切历史，会造成：

```text
tool_result 找不到对应 tool_use。
thinking block 丢失。
normalizeMessagesForAPI 合并后结构非法。
```

落到我们这里：

```text
MemoryCompactionPreview / ContextPolicy 必须维护 MessageBoundaryInvariant。
```

建议新增：

```text
ContextBoundaryValidator:
  preserve_tool_call_pairs
  preserve_assistant_message_segments
  preserve_commit_boundary
  preserve_last_user_goal

CompactionResult:
  dropped_message_refs
  preserved_message_refs
  boundary_validation
```

这个点很重要，因为我们后面如果有 tool / worker / agent 的结构化消息，compact 不能只按 token 数裁剪。

---

## 7. 子 agent：可学生命周期，不照搬默认 fork

Claude Code 的 AgentTool 有很多成熟细节：

```text
AgentTool input schema 包含 description / prompt / subagent_type / model / run_in_background / isolation / cwd。
TaskStateBase 有 status、outputFile、outputOffset、notified。
local_agent / remote_agent / local_bash / monitor_mcp 都是 TaskType。
forkSubagent 能继承父上下文，但有递归 fork guard。
worktree isolation 明确告知子 agent 路径要从 parent cwd 映射到 worktree cwd。
fork child 复用父 system prompt bytes，避免 prompt cache 失效。
```

对我们有价值：

```text
未来 MultiAgentTaskContract 应该区分：
  agent seat
  task handle
  output handle
  memory scope
  permission mode
  isolation mode
  lifecycle status
```

落到我们这里：

```text
backend/orchestration/topology.py
backend/orchestration/unit_registry.py
backend/tasks/runtime_contracts.py
backend/memory_system/contracts.py
```

但不能照搬：

```text
不要让 AgentTool 自己决定多智能体拓扑。
不要默认让子 agent 继承完整父上下文。
不要让子 agent 自己 commit 文件或接管主会话。
```

符合我们之前定下的口径：

```text
任务系统是多智能体管理总入口。
编排系统决定拓扑。
记忆系统决定 memory scope。
操作系统决定权限。
子 agent 输出只是 ResultCandidate。
主 agent / OutputBoundary 保留最终答案所有权。
```

---

## 8. Agent Memory：三层记忆之外，还需要 agent scope

Claude Code 的 `tools/AgentTool/agentMemory.ts` 提供了 agent memory scope：

```text
user    -> ~/.claude/agent-memory/<agentType>/
project -> .claude/agent-memory/<agentType>/
local   -> .claude/agent-memory-local/<agentType>/
```

它还区分：

```text
user-scope: 跨项目泛化经验。
project-scope: 项目共享经验。
local-scope: 本机本项目经验，不进 VCS。
```

`python_agent_memory` 还给出一个简化模式：

```text
MEMORY.md 作为 index
topic files 带 frontmatter
summary.md 作为 session memory
post-turn extraction scheduler 合并多次提取
```

对我们有价值：

```text
当前我们有 conversation / state / long_term 三层。
未来多 agent 时，需要再增加 agent_memory_scope 维度，而不是新建第四种记忆层。
```

建议：

```text
MemoryWriteCandidate 增加：
  target_layer: conversation | state | long_term
  scope: main_agent | agent:<id> | task:<id> | user | project | local
  share_policy: private | project_shared | user_global
```

注意：

```text
agent memory 写入仍必须走 MemoryGate / CommitGate。
不能让子 agent 直接写长期记忆。
```

---

## 9. Feature Flag：编译期裁剪和运行期快照要分开

Claude Code 的 `query/config.ts` 明确区分：

```text
feature() gate: 编译期常量，保持 inline，方便 dead-code elimination。
runtime gates: 进入 query 时快照一次，保证本轮行为稳定。
```

这对我们很有借鉴意义。

落到我们这里：

```text
backend/runtime/settings.py
backend/orchestration/*
backend/operations/*
frontend feature flags
```

建议：

```text
RuntimeFeatureSnapshot:
  session_id
  turn_id
  model_only_enabled
  tool_executor_enabled
  worker_executor_enabled
  commit_gate_write_enabled
  memory_write_enabled
  multi_agent_enabled

原则：
  一轮开始后 feature snapshot 不变。
  preview event 必须带 feature snapshot ref。
  编译期/部署期禁用的模块不要出现在运行时可选列表里。
```

---

## 10. 输出和工具结果预算：ResultCandidate 也要有大小治理

Claude Code 的工具契约有：

```text
maxResultSizeChars
tool result budget
contentReplacementState
large result persist-to-disk preview
```

对我们当前架构的启发：

```text
ResultCandidate 不能无限大。
OutputBoundary 不能吃原始超大 worker/tool 输出。
CommitGate 不能默认把大结果写 session。
Evidence / Artifact 应持有大结果，FinalAnswer 只引用摘要和 handle。
```

落到我们这里：

```text
backend/output_boundary/*
backend/evidence/*
backend/workers/*
backend/orchestration/execution_graph.py
```

建议：

```text
ResultCandidate 增加：
  size_chars
  size_tokens_estimate
  storage_policy
  artifact_ref
  visible_preview

OutputBoundary 只消费：
  visible_preview
  canonical_summary
  evidence_refs
```

---

## 11. 应直接进入我们缺口分析的补强项

把这些细节映射到 `01-AgentRuntime当前框架对照与缺口分析-20260430.md`，应新增或强调：

```text
1. OperationGatePipeline，而不是单函数 check。
2. OperationDescriptor 增加 read_only / destructive / concurrency_safe / open_world / max_result_size。
3. ShellReadOnlyValidator 必须在恢复 shell 前完成。
4. ContextBoundaryValidator 必须在恢复 tool/worker 后进入 compact。
5. CommitGate 需要 CommitApplier，并管理大结果 artifact 化。
6. TaskCoordinator 要引入 TaskHandle / output handle / lifecycle status。
7. Multi-agent 未来必须有 AgentSeatPlan + permission mode + memory scope + isolation mode。
8. RuntimeFeatureSnapshot 应成为每轮 trace 的一部分。
9. MemoryWriteCandidate 增加 scope 维度，为 agent memory 预留。
```

---

## 12. 明确不借鉴的部分

Claude Code 很成熟，但有些设计不适合我们当前阶段：

```text
不把 query loop 重新变成大脑。
不让工具自己绕过 OperationGate。
不让 AgentTool 自己决定拓扑。
不默认 fork 完整父上下文给子 agent。
不让子 agent 直接提交主会话 final answer。
不在恢复 tool 执行前引入 AI classifier。
不把 UI render contract 混入后端执行 contract。
不把 memory extraction 变成自动 durable write。
```

原因：

```text
我们的核心原则是：
Candidate != Decision。
RuntimeDirective 是唯一执行真相。
CommitGate 是唯一写回门。
TaskSystem 是多智能体管理总入口。
```

---

## 13. 下一步建议

按照当前工程状态，优先级应调整为：

### Phase 1：OperationGatePipeline

```text
从 Claude Code 权限管线吸收 deterministic 部分。
先不做 classifier。
先完成 deny / ask / approval / headless deny / operation validator。
```

### Phase 2：OperationDescriptor 补字段

```text
read_only
destructive
concurrency_safe
open_world
requires_user_interaction
max_result_size
interrupt_behavior
```

### Phase 3：CommitGate / ResultCandidate 大结果治理

```text
ResultCandidate 增加 size / artifact / preview。
CommitGate 决定 session_message / artifact / task_result。
OutputBoundary 不消费原始大结果。
```

### Phase 4：TaskCoordinator 合同化

```text
引入 TaskHandle / output handle / lifecycle status。
去掉 raw query 推断 binding 的执行权。
任务结果写回变成 CommitCandidate。
```

### Phase 5：ContextBoundaryValidator

```text
压缩不能拆 tool_use / tool_result。
压缩不能拆 assistant message segment。
压缩不能丢当前 user goal。
```

### Phase 6：只读 Tool / Worker Executor

```text
只恢复 deterministic read-only 工具。
shell 先不恢复或只恢复极小 allowlist。
所有结果进 ResultCandidate，不直接 final answer。
```

---

## 14. 最终口径

Claude Code 给我们的最大启发是：

```text
成熟 agent runtime 的难点不在“能不能调用工具”，
而在“每一次调用之前、之中、之后，系统是否还有清晰的所有权和边界”。
```

洪荒时代现在的分层是正确的。下一步不应该回去补旧 query 的能力，而应该把 Claude Code 这些成熟细节吸收到新系统的合同层：

```text
ToolContract 更厚。
OperationGate 更像管线。
ContextPolicy 更懂压缩边界。
CommitGate 更懂结果大小和写回治理。
TaskSystem 更懂 task handle 和 agent lifecycle。
MemorySystem 更懂 agent scope。
```

这样做，才能既保留我们现在已经清理出来的新架构边界，又补上真实执行所需的生产级细节。
