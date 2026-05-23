# 理解系统与任务系统头部收尾计划书

日期：2026-05-23

## 0. 本计划的定位

本计划重写并统筹此前三份计划：

- `universal_understanding_and_agent_todo_plan_20260523.md`
- `task_understanding_goal_first_refactor_plan_20260523.md`
- 本文件旧版 `mature_agent_understanding_framework_plan_20260523.md`

此前计划里有一个关键表述需要修正：任务域不是用来覆盖用户目标的分类器，也不是具体任务本身。任务域是一个 **领域容器**，类似能力目录或工作空间目录；任务域里面才有具体任务、任务流、目标画像、默认工具集合和成熟工作制式。

正确理解是：

```text
通用理解层永远先理解用户真实目标和边界。
任务域如果已经由平台、用户、任务图或模型绑定，就跳过 domain discovery。
被跳过的是“我应该进入哪个领域目录”的发现步骤，不是用户意图理解，也不是具体任务选择。
```

因此，本系统的目标不是：

```text
用户消息 -> 关键词分类 -> 任务域决定流程 -> agent 照做
```

而是：

```text
用户消息
  -> 通用理解
  -> 可选任务域绑定
  -> 领域内具体任务/目标裁决
  -> 语义合同
  -> agent 生成计划
  -> 系统审查覆盖与证据
  -> 执行
  -> 完成裁决
```

## 1. 核心设计立场

必须保留任务域层，但要重新定义它的位置：任务域是领域，任务域内部才是具体任务系统。

### 1.1 任务域是什么

`TaskDomainRecord` / `TaskDomainBinding` 是平台给 agent 的领域目录绑定，类似：

- development 领域
- writing 领域
- data_analysis 领域
- document_processing 领域
- agent_runtime_quality 领域
- task_graph 领域

每个领域内部可以包含：

- 具体任务类型
- 任务流
- 目标画像
- 默认工具和权限集合
- 成熟工作制式
- 验证习惯
- prompt 模块

它提供：

- 本领域可选的具体任务集合
- 默认工作习惯
- 常见阶段
- 风险提示
- 推荐验证方式
- 可用工具边界
- prompt 模块
- 失败处理习惯

它不负责：

- 替代用户真实目标
- 覆盖用户显式流程
- 覆盖用户禁令
- 直接生成具体业务步骤
- 让验证义务越权升级

### 1.2 跳过步骤的真实含义

如果平台已经告诉 agent：这是 `development` 任务域，那么系统可以跳过：

```text
domain discovery
```

但不能跳过：

```text
在 development 领域内理解用户本轮到底要解释代码、审查代码、修复 bug、重构、开发前端、交付游戏切片、写测试、运行排查，还是只读分析。
```

如果平台进一步告诉 agent：这是 `artifact_delivery`，可以跳过：

```text
task_goal_type classification
```

但仍不能跳过：

```text
理解产物内容、路径、禁令、材料、验证要求、证据边界。
```

这就是成熟 agent 产品里常见的“已处在某个领域内工作”的机制。Codex/Claude Code 默认处于 coding workspace domain，所以很多 domain discovery 被系统上下文提前完成了，但它们仍会在 coding 领域内部继续判断具体任务。

## 2. 目标主链路

最终主链路固定为：

```text
UserMessage
  -> CommunicationFrame
  -> TaskUnderstandingFrame
  -> TaskDomainBinding
  -> DomainTaskCandidateSet
  -> GoalHypothesisSet
  -> TaskGoalFrame
  -> TaskGoalProfileBinding
  -> SemanticTaskContract
  -> ExecutionObligation
  -> AgentPlanDraft
  -> PlanCoverageReview
  -> AgentTodoPlan
  -> ProfessionalExecutionLedger
  -> EvidencePacket
  -> VerificationReview
  -> CompletionJudgment
  -> FinalAnswer
```

顺序说明：

- `CommunicationFrame` 判断如何承接用户。
- `TaskUnderstandingFrame` 理解本轮目标、边界、禁令、上下文绑定。
- `TaskDomainBinding` 绑定已知或推断出的领域目录。
- `DomainTaskCandidateSet` 在领域内列出可选具体任务。
- `GoalHypothesisSet` 在通用理解、领域任务集合和用户目标下裁决具体目标。
- `TaskGoalFrame` 表达真实目标和不可接受结果。
- `SemanticTaskContract` 是 runtime、prompt、计划、验证共同引用的唯一合同。
- `AgentPlanDraft` 是 agent 的执行计划，不是系统节点说明。
- `AgentTodoPlan` 是执行状态，不是理解层。
- `CompletionJudgment` 是完成裁决，不是最终回答修辞。

## 3. 当前代码严格现状

### 3.1 已经具备的结构

当前代码已经有相当多骨架，不需要推倒重来：

- `backend/intent/communication_frame.py`
  - 已有交流承接结构。

- `backend/intent/task_understanding_frame.py`
  - 已有通用理解帧、模型理解请求、仲裁结构。

- `backend/intent/understanding_arbitration.py`
  - 已有 `ModelUnderstandingDraft` schema 校验和 arbitration。

- `backend/intent/task_goal_interpreter.py`
  - 已有 `GoalHypothesisSet`、目标候选、拒绝理由、profile 匹配雏形。

- `backend/task_system/domains/`
  - 已有 `TaskDomainBinding` 方向，适合继续作为领域目录绑定。

- `backend/task_system/goal_profiles/`
  - 已有 `TaskGoalProfile` 和 `TaskGoalProfileBinding`。

- `backend/task_system/contracts/semantic_task_contracts.py`
  - 已能汇总 goal frame、domain binding、profile binding、材料、义务。

- `backend/runtime/professional_runtime/agent_plan.py`
  - 已有 `AgentPlanDraft` schema 和 scaffold fallback。

- `backend/runtime/professional_runtime/plan_coverage.py`
  - 已有计划覆盖审查雏形。

- `backend/runtime/professional_runtime/model_sidecars.py`
  - 已有 readonly planner / verifier sidecar 接口。

- `backend/runtime/professional_runtime/completion_judgment.py`
  - 已有 `VerificationReview` 与 `CompletionJudgment`。

- `backend/runtime/professional_runtime/agent_todo.py`
  - 已有 todo 状态模型。

- `backend/capability_system/units/tools/agent_todo_tool.py`
  - 已有 `agent_todo` 工具入口。

### 3.2 仍未闭合的问题

下面是必须承认并修完的问题。

#### 问题一：模型理解草稿还没有成为主链路理解输入

现在已有 `ModelUnderstandingRequest` 和 sidecar helper，但主链路仍有断点：

- 模型理解通常只在 policy 开启且 runtime 支持 sidecar 时调用。
- `runtime_chain` 的早期目标理解容易先生成 deterministic `TaskGoalFrame`。
- `model_understanding_draft` 需要稳定穿过 `build_turn_context_payload` 和 `build_task_goal_frame`。
- 没有模型草稿时 fallback 是合理的，但不能把 fallback 伪装成模型理解。

目标：

```text
deterministic signals 是弱信号。
model_understanding_draft 是可参与裁决的结构化输入。
显式任务绑定和用户禁令仍高于模型草稿。
```

#### 问题二：模型理解还不能稳定重裁顶层 task_goal_type

当前系统已经有目标候选，但必须保证：

- 显式 `semantic_task_type` 最高优先级。
- 平台预绑定 `task_goal_type` 可以跳过分类。
- 没有显式 goal 时，模型理解可以在注册 goal profile 内重选目标。
- deterministic candidate 不能冒充用户/平台硬绑定。
- 未注册模型目标必须被拒绝或映射到 fallback。

目标：

```text
用户/平台显式具体任务绑定 > 用户禁令和流程 > 模型目标理解 > 任务域内候选任务集合 > deterministic fallback
```

#### 问题三：任务域、领域内具体任务和目标画像边界仍需压实

当前代码中仍有多处 task_goal_type if/else 和 profile/frame 混用，容易导致：

- 任务域默认验证覆盖用户目标。
- 任务域被误当成具体任务。
- frame 推断覆盖显式 task selection。
- goal profile 义务和 user goal 义务重复叠加。

目标：

```text
TaskDomainBinding = 领域目录绑定
DomainTaskCandidateSet = 领域内可选具体任务集合
TaskGoalProfileBinding = 本轮具体目标画像绑定
SemanticTaskContract = 唯一运行合同
ExecutionObligation = 从合同派生，不独立篡改目标
```

#### 问题四：计划覆盖检查和真实执行计划不是同一张计划

当前已有 `AgentPlanDraft` 和 `PlanCoverageReview`，但 professional driver 默认仍可能用 `_semantic_control_plan()` 生成实际控制 plan。

风险：

```text
agent_plan_draft 通过覆盖审查，不代表 runtime 按它执行。
```

目标：

```text
被 coverage review 通过的 AgentPlanDraft 必须成为 professional driver 的真实业务执行计划。
_semantic_control_plan 只能作为无模型计划时的低等级 scaffold fallback，并且必须带 diagnostics。
```

#### 问题五：understanding/domain steps 更像账本，不是真调度

`compile_understanding_runtime_steps()` 能生成：

```text
turn_intake
context_resolution
task_goal_understanding
domain_flow_matching
contract_compilation
prompt_assembly
execution_planning
plan_coverage_review
step_execution.*
verification
finalization
```

但当前 driver 仍会自动完成很多前置步骤，真正执行不一定逐步受这些 step 强制。

目标：

```text
系统阶段用于生命周期。
业务步骤来自 AgentPlanDraft。
TaskRunLedger 必须能映射系统阶段、业务步骤和 evidence refs。
不要把账本展示当作执行保证。
```

#### 问题六：CompletionJudgment 语义偏宽

当前 `completion_allowed` 允许 `partially_verified`，这对下游很危险。

目标：

```text
completion_allowed 只能在 verified 时为 true。
partially_verified 可以作为用户可见状态，但不能作为完成许可。
blocked/unverified/contradicted 都不能关闭合同。
```

#### 问题七：旧架构残留需要清理

需要清理的不是所有历史代码，而是会继续参与决策、制造重复真相的旧结构。

重点包括：

- `query_understanding` 只能作为 weak signal，不能再作为目标裁决源。
- 散落的 task_goal_type if/else 需要收口到 profile/contract。
- 旧 route/task_kind 不得覆盖 `SemanticTaskContract`。
- 旧 validator 不能和 `CompletionJudgment` 各自裁决完成。
- 旧测试若只验证旧行为，必须改写或删除。
- 旧计划文档互相冲突的表述必须标记为 superseded 或合并。

## 4. 新目标架构

### 4.1 Binding Source 统一模型

所有任务域、领域内具体任务和目标绑定必须记录来源：

```text
platform_preselected
user_selected
task_graph_bound
agent_invocation_bound
model_inferred
deterministic_fallback
legacy_restored
```

来源决定优先级。

```text
platform_preselected/user_selected/task_graph_bound
  > model_inferred
  > deterministic_fallback
  > legacy_restored
```

但任何来源都不能覆盖：

```text
safety / permission boundary
user forbidden_actions
user_provided_flow
latest user correction
```

### 4.2 Domain Binding 语义

`TaskDomainBinding` 字段建议：

```text
binding_id
domain_id
binding_source
binding_status: bound / inferred / absent / rejected
domain_role: domain_container / capability_catalog / playbook_catalog
skipped_steps: list[str]
available_task_refs
available_flow_refs
available_goal_profile_refs
playbook_refs
default_required_capabilities
default_verification_habits
must_not_override
diagnostics
authority
```

关键规则：

```text
如果 domain 已绑定，则跳过 domain discovery。
如果 domain 未绑定，模型可以推断 domain。
domain 只决定进入哪个领域目录。
domain 内部仍必须选择具体任务或 task_goal_type。
```

### 4.3 DomainTaskCandidateSet 语义

`DomainTaskCandidateSet` 字段建议：

```text
candidate_set_id
domain_id
binding_source
available_task_types
available_task_flows
available_goal_profiles
selected_candidate_ref
rejected_candidates
diagnostics
authority
```

规则：

```text
如果只有 domain 绑定，则根据该 domain 的候选任务集合裁决具体任务。
如果具体任务已显式绑定，则可以跳过领域内任务选择。
领域内任务集合只是候选目录，不是最终合同。
```

### 4.4 Goal Binding 语义

`TaskGoalProfileBinding` 字段建议：

```text
profile_id
task_goal_type
binding_source
binding_status
classification_skipped: bool
matched_by
confidence
inherited_deliverables
inherited_required_actions
inherited_forbidden_actions
diagnostics
```

规则：

```text
如果 task_goal_type 显式绑定，则跳过 goal classification。
如果只有 task_domain 绑定，仍必须在 domain 内裁决具体任务或具体 goal。
如果都未绑定，先发现 domain，再在 domain 内产生候选任务和 GoalHypothesisSet。
```

### 4.5 SemanticTaskContract 成为唯一运行合同

所有执行层只读：

```text
SemanticTaskContract
ExecutionObligation
AgentPlanDraft
PlanCoverageReview
EvidencePacket
CompletionJudgment
```

禁止执行层重新从用户原文自由推断新目标。

允许执行层做的事：

- 检查合同是否缺字段。
- 发现事实后要求 replan。
- 记录 blocked reason。
- 生成 evidence。

不允许执行层做的事：

- 把 artifact_delivery 升级为 frontend_app_delivery。
- 把只读分析升级为代码修改。
- 把任务域当成具体任务。
- 把任务域 playbook 当作用户显式流程。

## 5. Prompt 装配原则

prompt 中每段必须有层级归属。

### 5.1 理解层 prompt

正确：

```text
你负责理解用户本轮真实目标、行动边界、显式流程、禁令和证据要求。
如果任务域已经绑定，它只是领域目录上下文，不代表用户目标和具体任务已经被完全理解。
如果用户给出明确流程或禁令，你必须让后续合同尊重它们。
```

错误：

```text
这是 task_goal_understanding runtime 节点。
消费上游 task_domain_binding。
输出 semantic_task_contract。
```

### 5.2 Domain playbook prompt

正确：

```text
当前任务已绑定 development 工作制式。
这表示你可以采用成熟工程习惯：先读相关代码、最小范围修改、真实验证、说明限制。
这些习惯不能覆盖用户明确要求的只读、先讨论、禁止修改或指定流程。
```

### 5.3 Todo prompt

正确：

```text
当任务需要多步推进，且当前工具确实包含 agent_todo 时，你可以维护执行状态。
todo 用来反映当前计划和进度，不能替代语义合同和完成证据。
发现事实改变计划时，先更新 todo，再继续执行。
```

错误：

```text
你必须调用 agent_todo。
这是执行计划节点。
```

## 6. 分阶段实施计划

### 阶段 0：收束当前工作区和计划冲突

目标：

- 盘点当前未提交改动。
- 区分已验证改动、被中断的 WIP、无关旧残留。
- 标记旧计划文档为 superseded 或合并进本计划。

文件：

- `docs/implementation_plans/mature_agent_understanding_framework_plan_20260523.md`
- `docs/implementation_plans/universal_understanding_and_agent_todo_plan_20260523.md`
- `docs/implementation_plans/task_understanding_goal_first_refactor_plan_20260523.md`

完成标准：

- 本文件成为唯一头部系统收尾计划。
- 旧计划不再作为互相冲突的实施依据。
- 被中断的代码改动必须跑对应回归后才能继续扩展。

### 阶段 1：ModelUnderstandingDraft 主链路接入

目标：

- 模型理解草稿能真实进入 `runtime_chain -> build_task_goal_frame -> TaskUnderstandingFrame`。
- 无模型草稿时明确 fallback。
- 结构化 sidecar 结果必须 schema gated。

文件：

- `backend/runtime/unit_runtime/loop.py`
- `backend/runtime/agent_assembly/boundary.py`
- `backend/agent_system/assembly/runtime_chain.py`
- `backend/task_system/services/assembly_builder.py`
- `backend/intent/model_understanding_invoker.py`
- `backend/intent/task_understanding_frame.py`
- `backend/intent/understanding_arbitration.py`

完成标准：

- `model_understanding_draft` 不被 context projection 丢弃。
- `TaskUnderstandingFrame.understanding_arbitration.model_draft_status=accepted` 能在主链路出现。
- 没有模型调用时 `model_call_performed=False`，不能伪装。
- 测试覆盖 sidecar enabled、sidecar disabled、invalid JSON、schema mismatch。

### 阶段 2：任务域作为领域目录绑定

目标：

- `TaskDomainBinding` 不再表达“任务目标分类”，只表达“领域目录绑定”。
- 支持 preselected domain 跳过 domain discovery。
- domain 内部暴露可选具体任务、任务流、目标画像和 playbook。
- domain playbook 注入 prompt，但低于用户流程和语义合同。

文件：

- `backend/task_system/domains/`
- `backend/task_system/contracts/semantic_task_contracts.py`
- `backend/prompt_library/runtime_sections.py`
- `backend/prompt_library/selector.py`
- `backend/prompt_library/registry.py`

完成标准：

- `development` 已绑定时不再重新分类 domain。
- 只有 domain 绑定时，仍会在领域内裁决具体 task_goal_type 或具体任务。
- 用户说“只分析不要改”时，development playbook 不会引入写入义务。
- prompt 中明确 domain 是领域目录，不是用户目标，也不是具体任务。

### 阶段 2.5：领域内具体任务候选集

目标：

- 从 `TaskDomainBinding` 解析该领域下可用具体任务。
- 形成 `DomainTaskCandidateSet`。
- 让 `GoalHypothesisSet` 在这个候选集内做目标裁决。

文件：

- `backend/task_system/domains/`
- `backend/task_system/registry/flow_registry.py`
- `backend/task_system/registry/flow_models.py`
- `backend/intent/task_goal_interpreter.py`
- `backend/task_system/contracts/semantic_task_contracts.py`

完成标准：

- `development` domain 下能列出 `code_fix_execution`、`frontend_app_delivery`、`game_vertical_slice_delivery`、`regression_test_design` 等具体任务/目标画像。
- 平台只绑定 `development` 时，系统不会直接把任务当成前端开发或代码修复。
- 平台绑定具体任务时，才跳过领域内任务选择。

### 阶段 3：GoalHypothesisSet 和 task_goal_type 仲裁

目标：

- 目标裁决支持显式绑定、模型推断、domain 内分类、deterministic fallback。
- 模型可重选顶层 `task_goal_type`，但不能覆盖显式绑定和用户禁令。
- deterministic candidate 不能冒充 caller hint。

文件：

- `backend/intent/goal_hypothesis.py`
- `backend/intent/task_goal_interpreter.py`
- `backend/intent/task_goal_frame.py`
- `backend/tests/task_goal_frame_regression.py`
- `backend/tests/understanding_arbitration_regression.py`

完成标准：

- 用户/平台显式 `semantic_task_type` 最高优先级。
- 模型能把误判的 `frontend_app_delivery` 重裁为 `artifact_delivery`。
- 模型输出未知 goal type 被拒绝或降级。
- `GoalHypothesisSet.rejected` 记录拒绝理由，不静默丢候选。

### 阶段 4：SemanticTaskContract 与 ExecutionObligation 收口

目标：

- `SemanticTaskContract` 成为唯一运行合同。
- `ExecutionObligation` 从合同派生，不再单独根据旧 route/frame 抢目标。
- 任务域默认义务不得覆盖显式 task_goal_type。
- 任务域不能直接生成具体任务义务，必须通过具体 task/goal profile。

文件：

- `backend/task_system/contracts/semantic_task_contracts.py`
- `backend/intent/execution_obligation.py`
- `backend/runtime/contracts/obligation_validation.py`
- `backend/task_system/goal_profiles/task_goal_profiles.py`

完成标准：

- artifact_delivery 不会被 frontend_app_delivery 验证项污染。
- material_synthesis 不会被 code_fix_execution 写入义务污染。
- old `query_understanding.route` 只作为 weak signal。
- obligation validator 不再用 schema 字段名做重复硬文本判定。

### 阶段 5：AgentPlanDraft 成为真实执行计划

目标：

- professional driver 使用通过 coverage 的 `AgentPlanDraft` 作为业务执行计划。
- `_semantic_control_plan()` 只保留为 scaffold fallback。
- sidecar planner 生成的计划必须 coverage 通过才能替换。

文件：

- `backend/runtime/professional_runtime/agent_plan.py`
- `backend/runtime/professional_runtime/plan_coverage.py`
- `backend/runtime/professional_runtime/model_sidecars.py`
- `backend/runtime/professional_runtime/driver.py`
- `backend/task_system/planning/execution_recipe_builder.py`

完成标准：

- `professional_task_readonly_planner_checked` 事件说明实际使用的 plan source。
- `AgentPlanDraft.source=scaffold_fallback` 时 diagnostics 明确。
- 覆盖通过的 agent plan 与 driver plan 是同一张计划。
- coverage 未通过不得继续执行核心动作。

### 阶段 6：Understanding steps 与 TaskRunLedger 对齐

目标：

- `compile_understanding_runtime_steps` 输出的步骤不只是展示。
- 系统阶段和业务步骤在 ledger 中有稳定映射。
- 每个业务步骤能挂 evidence refs、blocked reason、completion state。

文件：

- `backend/task_system/planning/understanding_step_compiler.py`
- `backend/task_system/tasks/run_models.py`
- `backend/runtime/professional_runtime/driver.py`

完成标准：

- `step_execution.*` 对应 `AgentPlanDraft.steps`。
- 前置理解步骤可自动完成，但必须标注 `system_lifecycle_step`。
- 业务步骤不能被一口气假完成。
- 长任务能看到当前 in_progress 步骤。

### 阶段 7：AgentTodoPlan 工具化收尾

目标：

- `agent_todo` 只在真实可用时提示给模型。
- todo 只表示执行状态，不参与目标裁决。
- driver 能把 todo 状态和 plan step 关联。

文件：

- `backend/runtime/professional_runtime/agent_todo.py`
- `backend/capability_system/units/tools/agent_todo_tool.py`
- `backend/capability_system/tool_definitions.py`
- `backend/capability_system/operation_registry.py`
- `backend/permissions/resource_policy_builder.py`
- `backend/prompt_library/runtime_sections.py`

完成标准：

- operation/resource 未暴露时 prompt 不提示 `agent_todo`。
- 多步任务可创建、更新、完成 todo。
- todo 不能让未验证任务显示为完成。

### 阶段 8：EvidencePacket 标准化

目标：

- 证据从自由文本 preview 升级为 typed evidence。
- 文件、命令、浏览器、截图、测试、模型评审都有结构化证据类型。
- final answer 自述不能成为事实证据。

建议 evidence 类型：

```text
file_read
file_write
file_edit
command_run
test_result
browser_open
browser_dom_snapshot
browser_screenshot
canvas_pixel_check
asset_file
asset_visible
workflow_check
gameplay_check
model_review
blocked_reason
```

文件：

- `backend/runtime/memory/evidence_packet.py`
- `backend/runtime/memory/tool_observation_ledger.py`
- `backend/runtime/professional_runtime/evidence_closeout.py`
- `backend/runtime/contracts/deliverable_validator.py`

完成标准：

- validator 主要看 typed evidence，不主要靠 preview 字符串猜。
- 浏览器验证、文件写入、资源可见性、测试结果可结构化判断。
- blocked reason 进入 evidence packet。

### 阶段 9：CompletionJudgment 收紧

目标：

- `completion_allowed` 只允许 `verified`。
- `partially_verified` 是用户可见状态，不是完成许可。
- professional driver 以 `verification.passed` 和 `CompletionJudgment` 双重一致作为关闭条件。

文件：

- `backend/runtime/professional_runtime/completion_judgment.py`
- `backend/runtime/professional_runtime/driver.py`
- `backend/runtime/contracts/deliverable_validator.py`

完成标准：

- 缺核心交付物时 `completion_allowed=False`。
- 有事实但缺义务时状态为 `partially_verified` 或 `blocked`，不能关闭合同。
- unsupported claims 进入 `contradicted`。
- final metadata 不再误导下游。

### 阶段 10：旧架构清理

目标：

- 删除或降级会制造重复真相的旧结构。
- 清理无用旧残留代码和旧测试。
- 保留必要兼容层时必须标明 weak signal / deprecated。

清理范围：

- 旧 `query_understanding` 目标裁决权。
- 散落 task_goal_type if/else。
- 旧 route/task_kind 对专业任务的强制影响。
- 重复的 deliverable/obligation 完成判定。
- 已被 prompt library 替代的旧 prompt 拼接段。
- 无用旧测试文件。

完成标准：

- 主任务裁决源唯一：`TaskUnderstandingFrame -> GoalHypothesisSet -> TaskGoalFrame -> SemanticTaskContract`。
- 旧路线只用于工具效率和 fallback。
- 删除旧测试不会降低真实覆盖，因为新回归覆盖等价或更强行为。

## 7. 验证矩阵

必须覆盖以下任务：

- 已绑定 development domain 的普通代码修复。
- 已绑定 development domain 但用户只要求分析，不允许修改。
- 已绑定 artifact_delivery 的文件产物交付。
- 未绑定 domain 的材料综合。
- 前端应用交付。
- 浏览器游戏垂直切片。
- 测试报告诊断。
- runtime trace 分析。
- role conversation。
- task graph node execution。

关键断言：

- domain 已绑定时跳过 domain discovery，但不跳过用户目标理解和领域内具体任务选择。
- task_goal_type 已绑定时跳过 goal classification，但仍生成具体合同。
- domain playbook 不覆盖 forbidden actions。
- model_understanding_draft 能重裁目标，但不能覆盖显式绑定。
- AgentPlanDraft coverage 通过才执行。
- driver 实际执行 plan 与 coverage plan 是同一张。
- partially_verified 不允许 completion_allowed。
- final answer 中的完成声明必须回指 evidence。

建议回归命令：

```powershell
pytest backend/tests/understanding_arbitration_regression.py -q
pytest backend/tests/task_goal_frame_regression.py -q
pytest backend/tests/task_domain_binding_regression.py -q
pytest backend/tests/universal_understanding_frame_regression.py -q
pytest backend/tests/agent_plan_draft_regression.py -q
pytest backend/tests/model_sidecar_regression.py -q
pytest backend/tests/completion_judgment_regression.py -q
pytest backend/tests/professional_task_run_regression.py -q
pytest backend/tests/agent_todo_tool_regression.py backend/tests/task_system_api_regression.py -q
python backend/tests/tool_registry_regression.py
```

## 8. 不允许的实现方式

禁止：

- 用关键词特判单个样例。
- 把任务域当作目标裁决器。
- 把任务域当作具体任务。
- 把任务域默认流程写成用户显式流程。
- 把 runtime 节点说明写进 agent-facing prompt。
- 用模型自述替代工具 evidence。
- 计划 coverage 通过一张计划，driver 执行另一张计划。
- `partially_verified` 作为完成许可。
- 旧架构和新架构长期并行制造两个真相。
- 为了测试通过伪造工具结果、模型输出或 evidence。

## 9. 收尾定义

理解与任务系统头部完成的定义：

1. 用户任何请求先经过通用理解层。
2. 任务域作为领域目录绑定，提供领域内具体任务集合和成熟制式，不覆盖用户目标。
3. 显式 domain 绑定只跳过领域发现；显式具体任务绑定才跳过领域内任务选择。
4. 模型理解草稿能参与主链路仲裁。
5. 目标裁决结果进入唯一 `SemanticTaskContract`。
6. 执行义务只从合同和用户硬约束派生。
7. agent 计划、coverage、driver 执行是同一张计划。
8. todo 是执行状态工具，且只在真实可用时提示。
9. evidence 是真实 observation，不是回答文本。
10. completion judgment 严格控制完成许可。
11. 旧架构残留不再参与目标裁决或完成裁决。

达到以上 11 条，才可以说理解系统与任务系统这个头部系统做完。
