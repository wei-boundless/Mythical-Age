# OpenAI 式链路权限子 Agent 实例化实施计划

日期：2026-04-30  
定位：本计划用于把“带链路权限的子 Agent 实例化”从设计推进到实施，并以健康维护子 Agent 作为第一条完整样板链路。

完整链路蓝图：

```text
docs/系统规划/健康系统/18-链路权限子Agent完整链路设计-20260430.md
```

---

## 0. 核心结论

我们采用“链路权限 AgentCapabilityProfile”方案。

它不是临时自创概念，而是把 OpenAI Agents SDK 等成熟框架中的几个核心范式落到我们自己的分层系统里：

```text
OpenAI Agent:
  instructions / prompt / model / tools / mcpServers / handoffs / guardrails / outputType

OpenAI Runner:
  loop / maxTurns / session / handoffInputFilter / callModelInputFilter / tracing / errorHandlers

我们：
  AgentDescriptor / AgentCapabilityProfile / ProjectionInstance / SkillWorkflowBinding
  RuntimeDirectiveLane / ResourcePolicy / OperationGate / RuntimeLoop / HealthTrace
```

最终目标：

```text
主 Agent 保持完整交互能力。
子 Agent 不复制主 Agent 全链路。
子 Agent 由操作系统创建、禁用、删除和授权。
任务系统只绑定已授权子 Agent。
灵魂系统只生成投影和 PromptManifest。
Skills 系统只提供工作流能力。
编排系统通过统一 RuntimeLoop 执行。
健康系统记录问题、证据、分析和验证结果。
```

健康维护子 Agent 是第一个样板：

```text
agent_id = agent:health:maintainer
agent_profile_id = health_maintainer_agent
default_soul = xuannv
default_projection_template = xuannv__health_maintainer
default_runtime_lanes = health_issue_read / health_trace_read / case_draft_candidate / fix_verification_candidate
default_memory_scope = issue_local_readonly
default_write_policy = candidate_only
```

---

## 1. OpenAI 框架参考结论

### 1.1 Agent 是配置体，不是无边界主体

OpenAI Agents SDK 把 Agent 定义为配置了 instructions、model、tools 的 LLM，并进一步支持 handoffs、guardrails、outputType、MCP servers 等配置。

参考：

```text
https://openai.github.io/openai-agents-js/guides/agents/
https://github.com/openai/openai-agents-js/blob/main/packages/agents-core/src/agent.ts
```

源码中 `Agent` 持有：

```text
instructions
prompt
handoffDescription
handoffs
model
modelSettings
tools
mcpServers
inputGuardrails
outputGuardrails
outputType
toolUseBehavior
```

我们的吸收方式：

```text
AgentDescriptor:
  描述 agent 是谁、归哪个系统管、生命周期状态是什么。

AgentCapabilityProfile:
  描述 agent 能走哪些任务模式、runtime lane、工具、工作流、投影模板、记忆范围。

ProjectionInstance:
  对应 instructions / prompt 的动态部分。

SkillWorkflowBinding:
  对应 tools 的任务化组合方式。

OutputContract:
  对应 outputType / structured output。
```

### 1.2 Runner Loop 是执行中心

OpenAI Running Agents 文档明确描述 Runner loop：

```text
1. 调当前 agent 的模型。
2. 检查 LLM 响应。
   Final output -> return
   Handoff -> switch to new agent and loop
   Tool calls -> execute tools, append results, loop
3. 到 maxTurns 后抛出 MaxTurnsExceeded。
```

参考：

```text
https://openai.github.io/openai-agents-js/guides/running-agents/
https://github.com/openai/openai-agents-js/blob/main/packages/agents-core/src/run.ts
```

我们的吸收方式：

```text
TaskRunLoop 是唯一执行中心。
RuntimeLoopState 记录 turn / step / transition / terminal_reason。
RuntimeLoopLimits 对应 maxTurns / maxSteps / maxRuntime / maxEvents。
工具、子 Agent、健康分析都必须变成 RuntimeEvent。
```

我们不做“每个系统自己 loop”。每个系统只把自己的合同、视图、权限和候选送进 loop。

### 1.3 Handoff 不是随便转交，而是带输入过滤的委派

OpenAI handoff 支持：

```text
agent
tool_name_override
tool_description_override
on_handoff
input_type
input_filter
is_enabled
```

其中 input_filter 可以决定交给下一个 agent 的历史和输入，而不是默认让子 agent 继承所有上下文。

参考：

```text
https://openai.github.io/openai-agents-python/handoffs/
```

我们的吸收方式：

```text
TaskAgentBinding 不是全量 handoff。
RuntimeDirectiveLane 决定本次调用的链路范围。
MemoryScope 决定子 Agent 能看哪些记忆。
ContextSnapshot 只注入与任务相关的问题、trace、prompt、断言、运行证据。
ProjectionInstance 只渲染当前任务所需 sections。
```

这正好支持我们之前确定的原则：

```text
子 Agent 不是主 Agent 的完整复制。
子 Agent 是按任务装配的受限资源。
```

### 1.4 Session 是持久记忆接口，但不等于无限保存

OpenAI Sessions 文档把 session 定义为持久 memory layer：Runner 可自动读取历史、写入新输入和输出，并支持自定义存储、resume、compaction。

参考：

```text
https://openai.github.io/openai-agents-js/guides/sessions/
https://openai.github.io/openai-agents-python/sandbox/memory/
```

我们的吸收方式：

```text
主 Agent:
  conversation memory + state memory + long-term candidate。

健康子 Agent:
  issue_local_readonly。
  默认不生成长期记忆。
  只写 HealthIssue / HealthTrace / CaseDraft / FixVerification 的候选结果。
```

健康系统不做第二记忆系统。它只保存问题对话、证据引用、分析结果和修复验证。

### 1.5 Tracing 是一等能力

OpenAI tracing 默认覆盖：

```text
run
agent span
LLM generation
function tool call
guardrail
handoff
custom events
```

参考：

```text
https://openai.github.io/openai-agents-js/guides/tracing/
```

我们的吸收方式：

```text
RuntimeEventLog:
  task_run_started
  loop_iteration_started
  task_contract_built
  memory_runtime_view_built
  stage_projection_built
  context_snapshot_built
  runtime_directive_issued
  operation_gate_checked
  executor_observation_received
  commit_gate_checked
  loop_terminal

HealthTrace:
  prompt_manifest_ref
  memory_runtime_view_ref
  context_snapshot_ref
  runtime_event_refs
  assertion_refs
  issue_refs
```

健康系统必须消费 RuntimeTrace，而不是自己另造一套不可验证日志。

### 1.6 Guardrails 属于 agent/tool，而运行时仍要硬检查

OpenAI guardrails 分 input、output、tool guardrails，且 tripwire 会中止执行。

参考：

```text
https://openai.github.io/openai-agents-python/guardrails/
```

我们的吸收方式：

```text
AgentCapabilityProfile:
  声明 agent 级边界。

ResourcePolicy:
  声明本次 task/run 的资源授权。

OperationGate:
  执行前硬检查。

HealthOutputContract:
  对健康子 Agent 的输出做结构约束。

HealthIssuePolicy:
  当子 Agent 越权、输出无证据、误写记忆时生成健康问题。
```

---

## 2. 我们的目标设计

### 2.1 权力边界

```text
操作系统：
  拥有 AgentDescriptor / AgentCapabilityProfile / AgentLifecycleRecord。
  创建、修改、启用、禁用、删除子 Agent。
  决定 allowed_runtime_lanes / allowed_operations / allowed_memory_scopes。

任务系统：
  拥有 TaskDefinition / TaskAgentBinding。
  决定某个任务是否绑定某个已授权 agent。
  不能创建 agent，不能扩大 agent 权限。

Skills 系统：
  拥有 SkillRuntimeContract / SkillWorkflowBinding。
  决定 task_mode 下哪些 skills 可见、步骤顺序、停止条件。

灵魂系统：
  拥有 SoulSeed / ProjectionTemplate / ProjectionInstance / PromptManifest。
  只改变模型可见工作姿态，不授予工具或记忆权限。

编排系统：
  拥有 RuntimeLoop / RuntimeDirective / RuntimeEvent / Checkpoint。
  是唯一执行推进者。

健康系统：
  拥有 HealthIssue / HealthTrace / CaseDraft / FixVerification / HealthReport。
  只维护系统健康，不保存所有成功对话。
```

### 2.2 主 Agent 不被破坏

主 Agent 拥有内建 profile：

```text
agent_id = agent:main
agent_profile_id = main_interactive_agent
profile_type = primary
lifecycle_state = system_builtin
allowed_runtime_lanes = full_interactive
allowed_memory_scopes = conversation_read_write / state_read_write / long_term_candidate
allowed_projection_templates = primary_agent_default
deletable = false
disable_allowed = false
```

子 Agent 拥有受限 profile：

```text
agent_id = agent:health:maintainer
agent_profile_id = health_maintainer_agent
profile_type = sub_agent
lifecycle_state = enabled
allowed_runtime_lanes = health_issue_read / health_trace_read / case_draft_candidate / fix_verification_candidate
allowed_memory_scopes = issue_local_readonly
allowed_projection_templates = xuannv__health_maintainer
allowed_operations = op.model_response / op.read_file / op.search_text / op.memory_read
blocked_operations = op.write_file / op.edit_file / op.shell / op.python_repl / op.memory_write_candidate / op.agent_bounded
```

链路权限是运行时装配合同，不是削弱主 Agent 的全局开关。

---

## 3. 数据合同

### 3.1 AgentDescriptor

```text
AgentDescriptor
  agent_id
  display_name
  owner_system
  profile_type
  lifecycle_state
  default_soul_id
  default_projection_template_id
  created_at
  updated_at
  governance_status
  metadata
```

### 3.2 AgentCapabilityProfile

```text
AgentCapabilityProfile
  agent_profile_id
  agent_id
  allowed_task_modes
  allowed_runtime_lanes
  allowed_operations
  blocked_operations
  allowed_skill_workflows
  allowed_projection_templates
  allowed_memory_scopes
  allowed_context_sections
  output_contracts
  approval_policy
  lifecycle_policy
  trace_policy
```

### 3.3 TaskAgentBinding

```text
TaskAgentBinding
  binding_id
  task_id
  task_mode
  agent_id
  agent_profile_id
  runtime_lane
  projection_template_id
  skill_workflow_id
  memory_scope
  output_contract_id
  resource_policy_ref
  validation_state
```

### 3.4 RuntimeDirectiveLane

```text
RuntimeDirectiveLane
  lane_id
  lane_type
  agent_id
  task_id
  allowed_operations
  allowed_context_sections
  memory_scope
  output_contract_id
  max_turns
  terminal_policy
```

### 3.5 ProjectionTemplate / ProjectionInstance

```text
ProjectionTemplate
  template_id
  soul_id
  agent_profile_id
  role_type
  task_mode
  default_skill_workflow_id
  default_memory_policy
  default_output_contract
  guardrails

ProjectionInstance
  projection_id
  template_id
  task_id
  agent_id
  agent_profile_id
  runtime_lane
  prompt_manifest_id
  resource_policy_ref
  context_snapshot_ref
```

### 3.6 SkillWorkflowBinding

```text
SkillWorkflowBinding
  workflow_id
  task_mode
  visible_skill_ids
  steps
  stop_conditions
  required_evidence_refs
  output_contract
```

---

## 4. 健康维护子 Agent 默认配置

### 4.1 AgentDescriptor

```text
agent_id = agent:health:maintainer
display_name = 玄女健康管家
owner_system = health_system
profile_type = sub_agent
lifecycle_state = enabled
default_soul_id = xuannv
default_projection_template_id = xuannv__health_maintainer
governance_status = operation_managed
```

### 4.2 AgentCapabilityProfile

```text
agent_profile_id = health_maintainer_agent
allowed_task_modes:
  issue_triage
  trace_analysis
  case_draft
  fix_verification

allowed_runtime_lanes:
  health_issue_read
  health_trace_read
  prompt_trace_read
  memory_trace_read
  runtime_trace_read
  assertion_trace_read
  case_draft_candidate
  fix_verification_candidate

allowed_operations:
  op.model_response
  op.read_file
  op.search_text
  op.memory_read

blocked_operations:
  op.write_file
  op.edit_file
  op.shell
  op.python_repl
  op.memory_write_candidate
  op.agent_bounded

allowed_memory_scopes:
  issue_local_readonly
  health_trace_readonly

allowed_skill_workflows:
  workflow.health.issue_triage
  workflow.health.trace_analysis
  workflow.health.case_draft
  workflow.health.fix_verification
```

### 4.3 输出合同

健康子 Agent 只输出结构化候选：

```text
HealthTriageResult
HealthTraceAnalysis
HealthCaseDraftProposal
HealthFixVerificationProposal
```

它不能直接修改正式测试用例、不能直接写入长期记忆、不能直接编辑源码。

---

## 5. 实施阶段

### Phase 1：操作系统 Agent 注册与能力档案

目标：

```text
操作系统可以登记主 Agent 和健康子 Agent。
主 Agent 是 system_builtin。
健康子 Agent 是 operation_managed。
AgentCapabilityProfile 可以被查询、启用、禁用和校验。
```

文件：

```text
backend/operations/agent_models.py
backend/operations/agent_registry.py
backend/operations/agent_capability.py
backend/api/operation_agents.py
backend/operations/__init__.py
storage/operations/agents.json
storage/operations/agent_capabilities.json
```

完成标准：

```text
GET /api/operations/agents 能看到 agent:main 和 agent:health:maintainer。
GET /api/operations/agents/{agent_id}/capability-profile 能看到链路权限。
禁用 health agent 后，任务系统不能绑定它。
主 Agent 不可删除、不可禁用。
```

### Phase 2：任务系统绑定 AgentCapabilityProfile

目标：

```text
任务系统新增健康任务类型。
TaskAgentBinding 必须引用操作系统里真实存在且启用的 agent。
绑定时校验 task_mode / runtime_lane / projection_template / skill_workflow / memory_scope。
```

文件：

```text
backend/tasks/definitions.py
backend/tasks/agent_bindings.py
backend/tasks/bindings.py
backend/tasks/contract_builder.py
backend/tasks/runtime_contracts.py
```

完成标准：

```text
task.health.issue_triage 可以绑定 agent:health:maintainer。
task.task_execution 不能误绑定 health_maintainer_agent。
越权 runtime_lane 会 fail-closed。
```

### Phase 3：Skills 工作流注册

目标：

```text
从单个 skill 列表升级为 workflow。
健康任务按 workflow 注入 skill views。
workflow 有步骤、输入、输出和停止条件。
```

文件：

```text
backend/skill_system/workflow_models.py
backend/skill_system/workflow_registry.py
backend/skill_system/health_workflows.py
backend/skill_system/__init__.py
```

默认 workflow：

```text
workflow.health.issue_triage
workflow.health.trace_analysis
workflow.health.case_draft
workflow.health.fix_verification
```

完成标准：

```text
ProjectionInstance 的 skill_view 不再是全量 skills。
每个健康任务只看到对应 workflow 的 visible_skill_ids。
```

### Phase 4：灵魂系统 ProjectionTemplate / ProjectionInstance

目标：

```text
玄女健康管家成为正式 ProjectionTemplate。
每次健康任务生成 ProjectionInstance。
PromptManifest 成为 HealthTrace 的一等证据。
```

文件：

```text
backend/soul/projection_templates.py
backend/soul/projection_instances.py
backend/soul/projection.py
backend/soul/contracts.py
backend/api/souls.py
backend/soul/projections/catalog.json
```

完成标准：

```text
xuannv__health_maintainer template 可查询。
健康任务运行时生成 projection_id 和 prompt_manifest_id。
HealthTrace 可引用 prompt_manifest_id。
投影里不会声明自己拥有工具或记忆权限。
```

### Phase 5：RuntimeLoop 接入 agent lane

目标：

```text
RuntimeLoop 启动时知道当前 agent_id、agent_profile_id 和 runtime_lane。
RuntimeDirective 必须携带 agent lane 信息。
OperationGate 使用 ResourcePolicy + AgentCapabilityProfile 双重校验。
```

文件：

```text
backend/orchestration/runtime_loop/models.py
backend/orchestration/runtime_loop/task_run_loop.py
backend/orchestration/runtime_loop/context_manager.py
backend/orchestration/runtime_loop/stage_projection.py
backend/orchestration/runtime_loop/events.py
backend/orchestration/runtime_directive.py
backend/orchestration/runtime_loop/trace_reader.py
```

完成标准：

```text
runtime_loop_event 里能看到 agent_id / profile_id / lane_id。
health agent 请求 blocked operation 时被 OperationGate 拦截。
trace_reader 能按 agent_id 聚合运行记录。
```

### Phase 6：健康系统子 Agent 任务闭环

目标：

```text
HealthIssue 可以一键交给健康子 Agent 分析。
健康子 Agent 读取问题对话、trace、prompt、memory、assertion。
输出 HealthTriageResult / CaseDraftProposal / FixVerificationProposal。
健康系统只保存问题与候选，不保存所有正常对话。
```

文件：

```text
backend/health_system/models.py
backend/health_system/issue_registry.py
backend/health_system/trace_registry.py
backend/health_system/agent_tasks.py
backend/api/health_system.py
```

完成标准：

```text
用户在对话中发现问题，可以生成 HealthIssue。
HealthIssue 可触发 task.health.issue_triage。
健康报告展示 issue、trace、prompt sections、memory scope、agent operation path、problem nodes。
```

### Phase 7：前端管理与可视化

目标：

```text
操作系统页面管理子 Agent。
任务系统页面显示 TaskAgentBinding。
灵魂系统页面显示 ProjectionTemplate / ProjectionInstance。
健康系统页面显示健康问题、链路追踪、分析结果和候选用例。
```

文件：

```text
frontend/src/components/workspace/views/SystemFrameworkView.tsx
frontend/src/components/workspace/views/TestSystemView.tsx
frontend/src/lib/api.ts
```

完成标准：

```text
前端不再只展示后端文件。
健康系统报告可读、可追踪、可定位问题节点。
子 Agent 管理入口在操作系统，不散落在健康系统。
```

### Phase 7A：Harness 体系具象化

本阶段新增硬口径：

```text
健康系统前端不是测试运行按钮集合。
健康系统前端必须把 harness 体系可视化。
```

它至少要让开发者一眼看到：

```text
功能域 Feature
  -> 测试文件 TestFile
  -> 用例定义 TestCaseDefinition
  -> 这个测试提出/覆盖的问题 ProblemStatement
  -> 什么回答/行为算通过 PassCriteria
  -> 哪个 profile 会运行它 TestProfile
  -> 最近运行与失败证据 RunEvidence
  -> 关联 HealthIssue / ProblemNode / CaseDraft
```

新增后端视图：

```text
GET /api/test-system/harness-map
```

该视图不是新事实源，而是把现有事实合成一张治理图：

```text
test_system.case_registry
  active_cases / candidate_cases / legacy_cases

test_system.harness_records
  issues / case_drafts

test_system.test_agent
  governance findings / unregistered paths

experiments / harness artifacts
  runs / turns / issues / trace refs
```

首版字段：

```text
HarnessMap
  features:
    feature_id
    title
    owner_system
    boundary
    case_count
    active_case_count
    candidate_case_count
    legacy_case_count
    open_issue_count
    governance_finding_count
    risk_status

  cases:
    case_id
    title
    layer
    path
    runner
    status
    profiles
    owner_system
    feature_id
    feature_title
    behavior_under_test
    problem_statement
    pass_criteria
    assertions
    issue_refs
    case_draft_refs
    governance_findings
```

前端验收标准：

```text
用例库页不再只列测试文件。
每个测试文件必须展示它指向哪个功能。
每个测试文件必须展示它覆盖/提出的问题。
每个测试文件必须展示通过标准，而不仅是文件名。
候选测试必须显示为什么还不能进入正式门禁。
治理发现必须能反向定位到测试文件或功能域。
健康问题必须能推动用例草案，而不是停留在报告文本。
```

新增用例管理口径：

```text
用例不是散落在 Python 列表里的临时对象。
用例必须先进入规范化模板，再进入候选用例池。
前端可以新增 / 移除候选用例。
候选用例必须声明：
  title
  owner_system
  layer
  path
  profiles
  problem_statement
  pass_criteria
  assertions
  source_template_id

正式进入 curated gate 前必须满足：
  测试文件存在。
  runner 可执行。
  pass_criteria 明确。
  owner_system 与功能域一致。
  由人工或后续测试治理 Agent 采纳。
```

新增 API：

```text
GET    /api/test-system/case-templates
POST   /api/test-system/managed-cases
DELETE /api/test-system/managed-cases/{case_id}
```

如果做不到这些，说明 harness 不是健康系统的一等事实源，而只是一个命令集合；这种状态视为健康系统设计不合格。

---

## 6. 固定执行链路

健康问题分诊链：

```text
HealthIssueDraft
  -> HealthSystem.create_issue()
  -> TaskSystem.create(task.health.issue_triage)
  -> OperationSystem.resolve_agent(agent:health:maintainer)
  -> AgentLifecycleCheck
  -> AgentCapabilityCheck
  -> TaskAgentBinding
  -> SkillSystem.resolve_workflow(workflow.health.issue_triage)
  -> OperationSystem.build_resource_policy()
  -> SoulSystem.build_projection_instance(xuannv__health_maintainer)
  -> RuntimeLoop.start(agent_lane=health_issue_read)
  -> ModelResponseExecutor
  -> OperationGate
  -> HealthTriageResult
  -> HealthSystem.record_agent_run()
```

链路分析链：

```text
HealthIssue + RuntimeTrace
  -> task.health.trace_analysis
  -> workflow.health.trace_analysis
  -> runtime_lane=health_trace_read
  -> HealthTraceAnalysis
```

用例草案链：

```text
HealthIssue(triaged)
  -> task.health.case_draft
  -> workflow.health.case_draft
  -> runtime_lane=case_draft_candidate
  -> HealthCaseDraftProposal
```

修复验证链：

```text
HealthIssue + before_trace + after_trace
  -> task.health.fix_verification
  -> workflow.health.fix_verification
  -> runtime_lane=fix_verification_candidate
  -> HealthFixVerificationProposal
```

---

## 7. 验证矩阵

### 7.1 不破坏主 Agent

```text
主 Agent 正常对话。
主 Agent 正常调用已授权工具。
主 Agent 的 memory scope 不被 health profile 限制。
主 Agent 不可被删除或禁用。
```

### 7.2 子 Agent 权限收敛

```text
健康子 Agent 只能读 HealthIssue / HealthTrace / scoped docs。
健康子 Agent 不能写源码。
健康子 Agent 不能写长期记忆。
健康子 Agent 不能调用 shell/python。
健康子 Agent 不能启动其他子 Agent。
```

### 7.3 投影正确性

```text
ProjectionInstance 使用 xuannv seed。
PromptManifest 包含 health task / issue / trace / workflow / resource / memory / output sections。
模型可见 sections 和 debug-only refs 分离。
投影不能扩大 ResourcePolicy。
```

### 7.4 RuntimeLoop 可追踪

```text
每次健康子 Agent run 有 task_run_id。
每次 run 有 agent_id / profile_id / lane_id。
每次 run 有 RuntimeEventLog。
每次 run 有 checkpoint。
每次 run 可被 HealthTrace 引用。
```

### 7.5 健康系统职责清晰

```text
成功对话不全量保存。
问题对话保存 issue 和证据引用。
HealthIssue 可以生成分析。
CaseDraft 只是候选。
FixVerification 只是候选。
正式测试用例由人工或后续测试 Agent 采纳。
```

---

## 8. 风险与约束

### 8.1 风险：链路权限变成全局开关

避免方式：

```text
AgentCapabilityProfile 必须挂在 agent_id / agent_profile_id 下。
主 Agent 和子 Agent 各自独立 profile。
OperationGate 不读取全局 allowed_lanes。
```

### 8.2 风险：子 Agent 靠 prompt 限权

避免方式：

```text
prompt 只说明边界。
真正权限由 AgentCapabilityProfile + ResourcePolicy + OperationGate 执行。
```

### 8.3 风险：健康系统变成第二记忆系统

避免方式：

```text
只记录问题、证据、分析、候选和验证。
普通对话结束后清理。
长期知识仍归记忆系统。
```

### 8.4 风险：多 Agent 拓扑提前膨胀

避免方式：

```text
本轮只做 agent:health:maintainer。
不做任意多 Agent 协作。
不做子 Agent 互相调用。
只预留 protocol 字段。
```

---

## 9. 实施顺序建议

先做后端合同，再做前端体验。

```text
1. Operation Agent Registry
2. AgentCapabilityProfile
3. Health TaskDefinition + TaskAgentBinding
4. SkillWorkflowRegistry
5. Xuannv Health ProjectionTemplate
6. RuntimeLoop agent lane
7. HealthIssue -> HealthAgentRun
8. HealthTrace report
9. 任务系统前端工作区替换系统架构工作区
10. 前端健康系统页面重构
11. 操作系统子 Agent 管理页
```

Phase 9 的前端专项参考：

```text
docs/系统规划/操作系统与任务系统/06-任务系统前端工作区设计与Agent编排管理计划-20260430.md
```

该文件作为任务系统前端的细化设计参考；若与本计划发生冲突，以本计划和后续关于“链路权限、主 Agent 调度、子 Agent 固定任务流、协调任务占位”的新讨论口径为准。

完整链路施工时，同时参考：

```text
docs/系统规划/健康系统/18-链路权限子Agent完整链路设计-20260430.md
```

本轮不要做：

```text
不要开放子 Agent 任意创建任意工具权限。
不要让健康子 Agent 修改代码。
不要让健康子 Agent 写长期记忆。
不要做复杂多 Agent 拓扑。
不要把前端做成文件列表管理器。
```

---

## 10. 任务系统前端工作区设计

本计划准备一口气打通：

```text
操作系统 Agent Registry
  -> 任务系统 Agent/任务流/协调任务装配
  -> 灵魂系统 Projection
  -> Skills Workflow
  -> RuntimeLoop
  -> 健康系统 HealthIssue / HealthTrace / HealthAgentRun
```

因此前端不能只做健康系统页面。任务系统也必须成为这条链路的主控工作台。

### 10.1 导航替换决策

当前前端有：

```text
frontend/src/components/workspace/views/SystemFrameworkView.tsx
frontend/src/components/workspace/WorkspacePanel.tsx
```

细化参考：

```text
docs/系统规划/操作系统与任务系统/06-任务系统前端工作区设计与Agent编排管理计划-20260430.md
```

06 文件不再作为独立施工主线，而是本计划 Phase 9 的前端工作区专项设计稿。

但没有真正的任务系统工作区。

决策：

```text
用“任务系统”替换现有“系统架构”工作区。
系统架构不再作为一等 workspace。
系统架构信息只保留为文档或任务系统总览里的只读摘要。
```

目标落点：

```text
frontend/src/components/workspace/views/TaskSystemView.tsx
frontend/src/components/workspace/WorkspacePanel.tsx
frontend/src/lib/api.ts
frontend/src/lib/store.ts
```

迁移建议：

```text
第一步：
  保留 system-framework view key，但渲染 TaskSystemView，降低导航迁移成本。

第二步：
  将 view key 正式改为 task-system。
  清理 SystemFrameworkView 的导航入口和旧文案。
```

### 10.2 任务系统前端的定位

任务系统前端不是系统架构海报。

它是：

```text
AgentRuntime 的任务装配、任务分配、协调任务、链路权限和运行追踪工作台。
```

它负责把这些关系可视化：

```text
TaskDefinition
  -> Agent / AgentCapabilityProfile
  -> SkillWorkflowBinding
  -> ProjectionTemplate / ProjectionInstance
  -> RuntimeDirectiveLane
  -> ResourcePolicy
  -> RuntimeLoop
  -> OutputContract
  -> HealthTrace
```

### 10.3 权力边界

任务系统前端可以发起 Agent 管理动作，但底层权力仍归操作系统。

```text
操作系统：
  创建、禁用、启用、归档、删除、权限落库、生命周期治理。

任务系统：
  管理 agent 在任务系统中的可见性。
  管理任务流绑定。
  管理主 Agent 调度策略。
  管理协调任务模板。
  管理 task mode / workflow / projection / runtime lane / memory scope / output contract 的装配。
```

前端按钮语义必须区分：

```text
建立子 Agent：
  调用 OperationSystem.create_agent_profile。

隐藏子 Agent：
  只修改 TaskSystem visibility。

禁用子 Agent：
  调用 OperationSystem.disable_agent_profile。

删除子 Agent：
  默认 archive，不物理删除历史 trace 引用。
```

### 10.4 信息架构

任务系统工作区建议包含：

```text
任务系统
  总览
  主 Agent 调度中心
  子 Agent 实例
  单 Agent 任务流
  协调任务
  拓扑模板
  链路权限矩阵
  Skills 工作流
  投影分配
  运行记录
```

### 10.5 主 Agent 调度中心

主 Agent 不和子 Agent 混在一个列表。

主 Agent 页面关注：

```text
主 Agent Profile
任务识别策略
任务分配策略
可委派子 Agent
handoff input filter
projection_resolution_policy
memory_scope
final response owner
output merge policy
最近调度记录
```

主 Agent 的职责：

```text
理解用户目标。
拆分和识别任务。
选择任务流。
决定是否委派子 Agent。
承担最终对话和结果整合。
```

主 Agent 不是固定任务流执行者，它是任务分配层。

### 10.6 子 Agent 实例

子 Agent 页面管理受限执行单元。

列表字段：

```text
agent_id
display_name
owner_system
agent_profile_id
lifecycle_state
task_visibility
allowed_task_modes
allowed_runtime_lanes
default_projection_template
default_skill_workflows
memory_scope
risk_status
last_run
```

详情页展示：

```text
基础信息
生命周期
任务系统可见性
链路权限
Skills 工作流
投影模板
记忆范围
输出合同
最近运行
治理记录
```

子 Agent 默认绑定固定任务族，但允许受控变体。

健康维护子 Agent 示例：

```text
agent:health:maintainer
  allowed_task_modes:
    issue_triage
    trace_analysis
    case_draft
    fix_verification
```

它不能越界到：

```text
代码实现
任意 shell
长期记忆写入
创建其他子 Agent
```

### 10.7 单 Agent 任务流

单 Agent 任务流页面展示一条完整装配链：

```text
TaskDefinition
  -> TaskAgentBinding
  -> SkillWorkflowBinding
  -> ProjectionTemplate
  -> RuntimeDirectiveLane
  -> ResourcePolicy
  -> OutputContract
```

健康维护任务流示例：

```text
task.health.issue_triage
  default_agent = agent:health:maintainer
  projection = xuannv__health_maintainer
  workflow = workflow.health.issue_triage
  lane = health_issue_read
  memory_scope = issue_local_readonly
  output_contract = HealthTriageResult
```

页面需要显示：

```text
任务目标
输入合同
输出合同
默认 agent
可选 agent
workflow
projection_resolution_policy
runtime lane
resource policy preview
memory scope
stop conditions
validation report
```

### 10.8 协调任务

协调任务必须提前占位，因为后面会设置多智能体协调任务。

协调任务不是现在就开放任意多 Agent 自由对话，而是管理：

```text
多个受限 agent 如何在同一任务目标下协作。
```

核心对象：

```text
CoordinationTaskDefinition
  task_id
  coordination_mode
  coordinator_agent_id
  participant_agent_ids
  topology_template
  handoff_policy
  shared_context_policy
  memory_sharing_policy
  conflict_resolution_policy
  output_merge_policy
  stop_conditions
```

协调模式：

```text
sequential
parallel
supervisor
review_merge
debate
pipeline
```

页面必须展示每个参与者自己的链路权限：

```text
participant agent
  task_mode
  runtime_lane
  workflow
  projection
  memory_scope
  allowed_operations
  output_contract
```

原则：

```text
协调任务不让多个 agent 共享全链路。
协调任务为每个参与者分配独立 capability、context window 和 output contract。
```

### 10.9 拓扑模板

拓扑模板用于复用协调任务结构。

示例：

```text
写作流程：
  director -> outline -> draft -> editor -> final_merge

公司协作：
  coordinator -> parallel_review -> conflict_resolution -> decision_summary

健康修复：
  health_triage -> issue_owner -> fix_verification -> report
```

字段：

```text
template_id
nodes
edges
handoff_rules
join_policy
failure_policy
terminal_policy
```

第一版只做只读展示和草案配置，不执行多 Agent。

### 10.10 链路权限矩阵

链路权限矩阵是任务系统前端的关键页面。

它回答：

```text
哪个 agent 在哪个 task mode 下能走哪条系统链路？
```

矩阵维度：

```text
Agent
TaskMode
RuntimeLane
SkillWorkflow
ProjectionTemplate
MemoryScope
Operations
OutputContract
Visibility
RiskStatus
```

视觉要求：

```text
允许项用明确状态标识。
阻断项显示 blocked reason。
越权项显示 fail-closed。
不要把后端 JSON 原文作为主要 UI。
```

### 10.11 Skills 工作流

Skills 工作流页面不是 skill 列表。

它展示：

```text
workflow_id
task_mode
visible_skill_ids
steps
input_boundary
output_boundary
stop_conditions
required_evidence_refs
绑定任务流
绑定 agent
```

健康系统首批 workflow：

```text
workflow.health.issue_triage
workflow.health.trace_analysis
workflow.health.case_draft
workflow.health.fix_verification
```

### 10.12 投影分配

投影分配页管理任务态 projection。

核心字段：

```text
projection_template_id
soul_id
agent_profile_id
role_type
task_mode
projection_resolution_policy
default_skill_workflow_id
default_memory_policy
default_output_contract
```

投影切换策略：

```text
pinned:
  固定投影。适合健康维护、测试用例、代码审查。

manual:
  运行前手动选择。

auto:
  系统根据 task_mode、risk、trace、intent 自动选择。

hybrid:
  默认系统判断，但允许用户手动覆盖。
```

建议：

```text
健康子 Agent：pinned。
主 Agent：hybrid。
写作类子 Agent：manual 或 hybrid。
```

### 10.13 运行记录

运行记录页展示任务系统视角的 RuntimeLoop trace。

字段：

```text
task_run_id
task_id
agent_id
agent_profile_id
runtime_lane
task_mode
projection_id
prompt_manifest_id
workflow_id
status
terminal_reason
duration
health_issue_ref
```

详情页展示：

```text
任务合同
Agent 绑定
投影实例
PromptManifest
MemoryScope
ResourcePolicy
OperationGate decisions
Executor observations
OutputContract
CommitGate
Health issue refs
```

### 10.14 UI 体验要求

任务系统是配置与治理工具。

设计应偏：

```text
高密度
清晰
可扫描
工程化
状态可读
链路可追踪
```

避免：

```text
大段说明文字。
后端 JSON 文件列表。
卡片堆卡片。
把运行按钮放到总览页。
混淆主 Agent 和子 Agent。
把健康系统、操作系统、灵魂系统职责塞进一个页面。
```

推荐布局：

```text
左侧二级导航。
顶部状态条。
中间表格/矩阵/链路图。
右侧详情抽屉。
运行记录使用时间线，不直接倾倒 JSON。
```

关键组件：

```text
链路图：
  Task -> Agent -> Workflow -> Projection -> Lane -> ResourcePolicy -> RuntimeLoop -> Output

权限矩阵：
  行为 agent/task，列为 lane/workflow/projection/memory/operation。

详情抽屉：
  展示当前选择项的合同、风险和最近运行。

运行时间线：
  展示 RuntimeEventLog 的可读节点。
```

### 10.15 首版落地范围

首版先做只读和断链可见。

```text
TaskSystemView 壳和二级导航。
总览。
主 Agent 调度中心只读版。
子 Agent 实例列表和详情只读版。
单 Agent 任务流只读版。
协调任务只读/草案版。
链路权限矩阵只读版。
运行记录只读版。
```

第二阶段开放写操作：

```text
创建 / 隐藏 / 禁用 / 归档子 Agent。
编辑 TaskAgentBinding。
编辑 SkillWorkflowBinding。
编辑 ProjectionResolutionPolicy。
配置 CoordinationTaskDefinition。
```

写操作开放前提：

```text
OperationSystem AgentCapabilityProfile 稳定。
TaskAgentBinding 校验稳定。
OperationGate / governance trace 就位。
```

### 10.16 前端验收标准

```text
前端导航中系统架构入口被任务系统替代。
任务系统工作区能区分主 Agent 和子 Agent。
主 Agent 页面展示任务分配职责，不展示为普通子 Agent。
子 Agent 页面展示实例、生命周期、任务可见性和链路权限。
单 Agent 任务流页面能展示 Task -> Agent -> Workflow -> Projection -> Lane -> Policy -> Output。
协调任务页面存在，至少支持模板草案和只读配置。
链路权限矩阵能显示 allowed / blocked / risky / missing。
健康维护子 Agent 能作为样例展示完整装配链。
运行记录能按 task_run_id 查看 agent/profile/lane/projection/workflow/health issue refs。
页面不再把后端文件名当作主要管理对象。
```

---

## 11. 最终口径

OpenAI Agents SDK 给我们的启发不是“照搬它的类名”，而是这几个不变量：

```text
Agent 是配置化能力边界。
Runner 是统一 loop。
Handoff 必须可过滤输入。
Session 是可插拔持久层。
Tracing 是运行事实。
Guardrails 是 agent/tool 绑定的硬边界。
```

我们的系统将这些不变量翻译为：

```text
AgentCapabilityProfile 是子 Agent 实例化的链路权限合同。
ProjectionInstance 是任务态 prompt 承载。
SkillWorkflowBinding 是任务态工具/方法组织。
ResourcePolicy + OperationGate 是硬权限执行。
RuntimeLoop 是唯一推进者。
HealthSystem 是问题发现、证据追踪、候选修复和系统健康维护层。
```

这条链路打通后，健康维护子 Agent 就是后续所有子 Agent 的样板。
