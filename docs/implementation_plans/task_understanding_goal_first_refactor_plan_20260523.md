# 任务理解系统目标优先重构计划书 v2

日期：2026-05-23

## 0. 本版修正结论

本计划书替换旧版“任务域 profile 驱动”的表述，改为更接近成熟 agent 产品的目标导向控制系统：

```text
强模型主动理解目标
  + 系统维护显式任务契约
  + agent 自主生成具体执行计划
  + 系统审查计划是否覆盖契约义务
  + 执行过程沉淀真实 evidence
  + 最终用 CompletionJudgment 裁决完成度
```

重要修正：

1. 不新增 `task_system.domains`、`TaskDomainProfile` 或 `TaskDomainBinding` 平行体系。
2. 现有正式任务域层是 `TaskDomainRecord` / `TaskFlowRegistry.list_task_domains()`。
3. `game_vertical_slice_delivery`、`frontend_app_delivery` 是 `task_goal_type` / `TaskGoalProfile`，它们属于 `task_domain="development"`。
4. 状态机只提供稳定阶段和边界，不提前写死所有业务步骤。
5. 具体任务步骤应由 agent 主动生成，再由系统做计划覆盖审查。
6. 最终验证不能只靠程序规则，也不能只靠模型自述；必须是合同、证据和模型评审的受控合议。

## 1. 代码现状报告

### 1.1 已存在并应继续使用的结构

当前代码已经部分完成目标优先链路：

- `backend/intent/task_goal_frame.py`
  - 已有 `TaskGoalFrame`、`TaskGoalDeliverable`、`TaskGoalCriterion`。
  - 目前表示目标、核心交付、辅助交付、成功标准、验证项、显式约束和 evidence。

- `backend/intent/task_goal_interpreter.py`
  - 已有 deterministic `build_task_goal_frame()`。
  - 当前通过 `task_system.goal_profiles.task_goal_profiles()` 对候选 profile 打分。
  - 仍缺少显式 `GoalHypothesisSet`、拒绝理由、歧义处理和模型目标理解入口。

- `backend/task_system/goal_profiles/`
  - 已有 `TaskGoalProfile` 和 `TaskGoalProfileBinding`。
  - 已包含 `game_vertical_slice_delivery`、`frontend_app_delivery`、`code_fix_execution` 等 goal profiles。
  - 这是正确方向，应继续作为 goal profile 层，而不是再建 domain profile 层。

- `backend/task_system/registry/flow_models.py`
  - 已有 `TaskDomainRecord`。
  - 这是正式任务域层。`development` 是任务域，肉鸽游戏不是独立任务域。

- `backend/task_system/contracts/semantic_task_contracts.py`
  - 已开始优先消费 `task_goal_frame`。
  - 已接入 `get_task_goal_profile()` 和 `bind_task_goal_profile()`。
  - 仍有较多 task_goal_type if/else，需要逐步收口到 profile + contract schema。

- `backend/intent/execution_obligation.py`
  - 已开始从 `TaskGoalProfile.required_actions` 推导写入、资源接入、浏览器验证等义务。
  - 仍偏 deterministic，没有正式的 plan coverage gate。

- `backend/task_system/planning/understanding_step_compiler.py`
  - 已将单 agent 流程表达为稳定 step blueprint：
    `turn_intake -> context_resolution -> task_goal_understanding -> domain_flow_matching -> contract_compilation -> prompt_assembly -> execution_planning -> step_execution -> verification -> finalization`
  - 但目前 `execution_planning` 只是 `execution_plan_draft` 的占位，尚未真正让模型生成可审查计划。

- `backend/runtime/professional_runtime/goal_contract.py`
  - `_semantic_control_plan()` 仍以 semantic contract 直接生成较通用的专业计划。
  - 还没有 `AgentPlanDraft`、`PlanCoverageReview`、计划修复循环。

- `backend/runtime/contracts/deliverable_validator.py`
  - 已有 profile-driven evidence dimension 验证雏形。
  - 仍只是 `DeliverableValidationResult`，不是完整 `CompletionJudgment`。

### 1.2 当前主要缺口

当前系统已经不是完全旧系统，但还没有达到成熟 agent 水平。缺口集中在四处：

1. 目标理解缺少候选假设层。
   - 现在直接选一个 `TaskGoalFrame`。
   - 成熟做法应该先产生 `GoalHypothesisSet`，记录候选目标、拒绝目标、选择理由和歧义。

2. 计划生成缺少模型主动性。
   - 现在系统从 profile reasoning steps 推导执行步骤。
   - 成熟做法应该由 agent 根据目标和代码现状生成具体 `AgentPlanDraft`。

3. 计划审查缺少硬 gate。
   - 现在合同规定了 required actions，但没有在执行前强制检查计划是否覆盖。
   - 成熟做法应新增 `PlanCoverageReview`：不覆盖核心义务就退回重拟。

4. 验证结果缺少完成度裁决模型。
   - 现在 `validate_deliverable()` 返回 passed/missing/unsupported_claims。
   - 成熟做法应升级为 `CompletionJudgment`：
     `verified / partially_verified / unverified / blocked / contradicted`。

## 2. 设计原则

### 2.1 最高优先级原则

1. 用户目标先于路径、关键词、文件名和工具路由。
2. 模型拥有主动规划权，但不拥有事实裁决权。
3. 系统拥有合同和证据裁决权，但不替模型写死所有任务策略。
4. 旧 `query_understanding` 只能提供 weak signal，不能覆盖 `TaskGoalFrame`。
5. `final_answer` 是交付汇报，不是交付事实本身。
6. 任务步骤可以由 agent 生成，但必须经过合同覆盖审查。
7. 任何完成声明都必须能回指 evidence。
8. 验证不是追求绝对真理，而是诚实表达置信状态。

### 2.2 任务域与目标类型边界

必须保持以下分层：

```text
TaskDomainRecord
  - 正式任务域层
  - 示例：development、task_graph、general、agent_runtime_quality

TaskGoalProfile
  - 目标类型能力模板
  - 示例：game_vertical_slice_delivery、frontend_app_delivery、code_fix_execution

SemanticTaskContract
  - 本轮任务的契约化结果

ExecutionObligation
  - 从目标合同反推出必须执行/验证的义务
```

禁止：

- 禁止新增 `TaskDomainProfile` 平行任务域体系。
- 禁止把 `game_vertical_slice_delivery` 注册成独立 task domain。
- 禁止让报告路径、输出文件名、旧 route hint 抢走主目标裁决权。
- 禁止把 runtime 节点说明写成 agent-facing prompt。

## 3. 目标架构

### 3.1 固定控制流

目标系统的主链路：

```text
UserMessage
  -> GoalHypothesisSet
  -> TaskGoalFrame
  -> TaskGoalProfileBinding
  -> SemanticTaskContract
  -> ExecutionObligation
  -> AgentPlanDraft
  -> PlanCoverageReview
  -> ExecutionRecipe / TaskRunLedger
  -> EvidencePacket
  -> ModelCompletionReview
  -> CompletionJudgment
  -> FinalAnswer
```

### 3.2 各阶段职责

`GoalHypothesisSet`：

- 由 deterministic signals + 模型理解共同生成。
- 保存候选目标、选择理由、拒绝理由、歧义和澄清策略。
- 不执行工具，不生成计划。

`TaskGoalFrame`：

- 只表达用户真正要完成的目标。
- 区分核心交付物和辅助交付物。
- 表达成功标准、不可接受结果和用户显式约束。
- 不直接选择工具。

`TaskGoalProfileBinding`：

- 将 `TaskGoalFrame.task_goal_type` 绑定到已注册 `TaskGoalProfile`。
- 继承默认能力、默认验证和 profile policy。
- 冲突进入 diagnostics，不允许 profile 覆盖用户禁止项。

`SemanticTaskContract`：

- 合并 `TaskGoalFrame`、`TaskGoalProfile`、显式输入和 material。
- 生成稳定 deliverables、required_actions、forbidden_actions、validation_schema。
- 作为 runtime、plan review 和 completion judgment 的共同合同。

`ExecutionObligation`：

- 从合同反推出必须读、必须写、必须运行、必须验证。
- 原文关键词只能补充 evidence，不能作为复杂任务义务的唯一来源。

`AgentPlanDraft`：

- 由模型/agent 主动生成具体步骤。
- 步骤应该面向实际工作，不是系统节点说明。
- 每步声明 expected output、required operations、evidence expectation。

`PlanCoverageReview`：

- 系统审查计划是否覆盖合同义务。
- 如果缺少核心义务，必须要求重拟计划。
- 允许模型解释为什么某义务不可执行，但必须进入 blocked/limitation。

`EvidencePacket`：

- 只记录真实 observation：
  文件、命令、浏览器、截图、测试、结构化材料、模型评审结果。
- 模型自述不能作为事实 observation。

`CompletionJudgment`：

- 消费 `SemanticTaskContract`、`ExecutionObligation`、`EvidencePacket`、`ModelCompletionReview`。
- 输出完成度状态，而不是简单 boolean。

## 4. 新增核心数据模型

### 4.1 GoalHypothesisSet

建议新增文件：

- `backend/intent/goal_hypothesis.py`

建议结构：

```python
@dataclass(frozen=True, slots=True)
class GoalHypothesis:
    task_goal_type: str
    task_domain: str
    confidence: float
    matched_by: tuple[str, ...]
    supporting_evidence: tuple[str, ...]
    rejection_reason: str = ""
    risks: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class GoalHypothesisSet:
    hypothesis_set_id: str
    user_goal: str
    chosen: GoalHypothesis
    candidates: tuple[GoalHypothesis, ...]
    rejected: tuple[GoalHypothesis, ...]
    ambiguity_points: tuple[str, ...] = ()
    clarification_needed: bool = False
    clarification_question: str = ""
    authority: str = "intent.goal_hypothesis_set"
```

实现要求：

- `artifact_delivery` 和 `game_vertical_slice_delivery` 同时命中时，必须记录为什么选择开发目标、拒绝单文件交付。
- 未注册 `task_goal_type` 不允许进入 chosen。
- 模型输出未知类型必须映射到已注册 profile 或 fallback。

### 4.2 TaskGoalFrame v2

在现有 `TaskGoalFrame` 上新增字段：

```text
goal_hypothesis_set_ref
rejected_goal_candidates
unacceptable_outcomes
ambiguity_points
clarification_policy
```

实现要求：

- `unacceptable_outcomes` 必须能表达“只写最终报告不算完成”。
- `supporting_deliverables` 不得进入核心完成判定。
- `confidence` 低或歧义高时，系统可选择澄清，而不是盲目执行。

### 4.3 AgentPlanDraft

建议新增文件：

- `backend/runtime/professional_runtime/agent_plan.py`

建议结构：

```python
@dataclass(frozen=True, slots=True)
class AgentPlanStep:
    step_id: str
    title: str
    purpose: str
    required_operations: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    evidence_expectations: tuple[str, ...]
    contract_refs: tuple[str, ...]
    may_skip_if: str = ""

@dataclass(frozen=True, slots=True)
class AgentPlanDraft:
    plan_id: str
    task_goal_type: str
    semantic_contract_ref: str
    steps: tuple[AgentPlanStep, ...]
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    authority: str = "runtime.agent_plan_draft"
```

Agent-facing prompt 必须是职责语言，例如：

```text
你是一名任务执行规划员。
你需要根据用户目标、语义合同和代码现状，设计一组可执行步骤。
每个步骤必须说明要产生什么真实证据。
你不能把最终报告当成核心产物的替代品。
```

不能写成：

```text
这是 execution_planning 节点。
根据 runtime 节点输出 execution_plan_draft。
```

### 4.4 PlanCoverageReview

建议新增文件：

- `backend/runtime/professional_runtime/plan_coverage.py`

建议结构：

```python
@dataclass(frozen=True, slots=True)
class PlanCoverageReview:
    review_id: str
    plan_id: str
    semantic_contract_ref: str
    passed: bool
    covered_actions: tuple[str, ...]
    missing_actions: tuple[str, ...]
    covered_deliverables: tuple[str, ...]
    missing_deliverables: tuple[str, ...]
    unsupported_skips: tuple[str, ...] = ()
    required_replan_reason: str = ""
    authority: str = "runtime.plan_coverage_review"
```

审查规则：

- `apply_real_change` 必须有产物修改步骤。
- `integrate_asset` 必须有资源生成/接入/检查步骤。
- `run_browser_verification` 必须有启动/浏览器/可视检查步骤。
- `gameplay_acceptance` 必须有玩法实现和玩法验收步骤。
- `workflow_acceptance` 必须有用户流程实现和流程验收步骤。
- final report 只能作为后置汇报，不能替代核心产物。

### 4.5 CompletionJudgment

建议新增文件：

- `backend/runtime/contracts/completion_judgment.py`

建议结构：

```python
@dataclass(frozen=True, slots=True)
class CompletionJudgment:
    judgment_id: str
    task_goal_type: str
    status: str  # verified | partially_verified | unverified | blocked | contradicted
    verified_deliverables: tuple[str, ...]
    missing_deliverables: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    blocked_reasons: tuple[str, ...] = ()
    confidence: str = "medium"
    next_required_actions: tuple[str, ...] = ()
    evidence_alignment: dict[str, Any] = field(default_factory=dict)
    model_review: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.completion_judgment"
```

状态定义：

- `verified`：核心交付和必需验证均有充分 evidence。
- `partially_verified`：核心产物部分有证据，但存在非阻断缺口。
- `unverified`：final answer 声称完成，但缺少关键 evidence。
- `blocked`：环境、权限、依赖等阻断验证或交付。
- `contradicted`：final answer 声明与 evidence 冲突。

## 5. 模型主动性设计

### 5.1 模型负责什么

模型应负责：

- 理解用户真实目标。
- 在候选目标之间做语义判断。
- 根据代码现状主动生成计划。
- 主动发现还缺什么。
- 根据失败证据修复计划。
- 对完成证据做语义评审。

### 5.2 系统负责什么

系统应负责：

- 限定合法 `task_goal_type`。
- 维护 `TaskGoalProfile` 注册表。
- 维护 `SemanticTaskContract`。
- 审查 plan 是否覆盖 contract。
- 记录真实 observation。
- 拦截没有 evidence 的完成声明。
- 输出明确完成度状态。

### 5.3 模型输出约束

模型不能：

- 自由创造未注册 task goal type。
- 把工具未观察到的事情当事实。
- 声称未运行的测试通过。
- 声称未打开的浏览器验证通过。
- 把 supporting report 当核心产物替代。
- 把 runtime 节点说明写给 agent。

## 6. 固定状态机与动态计划的关系

系统固定阶段：

```text
turn_intake
context_resolution
task_goal_understanding
domain_flow_matching
contract_compilation
prompt_assembly
execution_planning
plan_coverage_review
step_execution
verification
finalization
```

说明：

- `domain_flow_matching` 名称可保留，但输出必须是 `task_goal_profile_binding`，不是新 domain binding。
- 新增 `plan_coverage_review` step kind，或者先在 `execution_planning` diagnostics 中落地，之后再提升为正式 step kind。
- 固定状态机只管边界和生命周期。
- 业务步骤来自 `AgentPlanDraft.steps`。
- `TaskRunLedger.step_runs` 应记录系统阶段和 agent 业务步骤之间的映射。

## 7. 分阶段实施计划

### 阶段一：修正目标假设层

目标：

- 新增 `GoalHypothesisSet`。
- 让 `build_task_goal_frame()` 先产生候选集，再生成 chosen frame。
- 保留 deterministic 逻辑，但改为候选评分器，不直接作为最终裁决。

涉及文件：

- `backend/intent/goal_hypothesis.py`
- `backend/intent/task_goal_interpreter.py`
- `backend/intent/task_goal_frame.py`
- `backend/tests/task_goal_frame_regression.py`

完成标准：

- 肉鸽任务同时记录 `game_vertical_slice_delivery` chosen 和 `artifact_delivery` rejected。
- rejected reason 明确说明：报告路径是辅助产物，不是核心目标。
- 前端分析类任务不会误入 `frontend_app_delivery`。

### 阶段二：升级 TaskGoalFrame v2

目标：

- 增加 `unacceptable_outcomes`、`rejected_goal_candidates`、`ambiguity_points`。
- 将“只写 final_report 不算完成”等反目标写入 frame。

涉及文件：

- `backend/intent/task_goal_frame.py`
- `backend/intent/task_goal_interpreter.py`
- `backend/task_system/contracts/semantic_task_contracts.py`

完成标准：

- `TaskGoalFrame.to_dict()` 输出完整 v2 字段。
- `SemanticTaskContract.diagnostics` 保留 rejected candidates 和 unacceptable outcomes。

### 阶段三：模型目标理解接入

目标：

- 在 deterministic 稳定后接入模型目标理解。
- 模型只输出固定 schema。
- 系统校验模型输出是否属于已注册 `TaskGoalProfile`。

建议新增：

- `backend/intent/model_task_goal_interpreter.py`
- `backend/intent/task_goal_schema.py`

完成标准：

- 模型可参与候选目标排序。
- 未注册类型被拒绝并降级到 deterministic fallback。
- 短任务可以跳过模型路径，避免延迟。

### 阶段四：SemanticTaskContract 收口

目标：

- 让 semantic contract 更彻底地消费 `TaskGoalFrame + TaskGoalProfile`。
- 减少散落 task_goal_type if/else。
- deliverables、required_actions、forbidden_actions 优先来自 profile 和 frame。

涉及文件：

- `backend/task_system/contracts/semantic_task_contracts.py`
- `backend/task_system/goal_profiles/task_goal_profiles.py`
- `backend/task_system/goal_profiles/goal_profile_binding.py`

完成标准：

- `game_vertical_slice_delivery` 合同 domain 为 `development`。
- `final_report` 不是唯一核心完成条件。
- 单文件写入仍稳定为 `artifact_delivery`。

### 阶段五：AgentPlanDraft 生成

目标：

- 在 professional runtime 中让 agent 根据合同主动生成具体执行计划。
- 计划步骤包含 expected outputs 和 evidence expectations。

涉及文件：

- `backend/runtime/professional_runtime/agent_plan.py`
- `backend/runtime/professional_runtime/goal_contract.py`
- `backend/runtime/professional_runtime/driver.py`
- `backend/task_system/planning/understanding_step_compiler.py`

完成标准：

- 肉鸽任务计划不是通用四步，而是围绕项目勘察、玩法实现、资源接入、运行验证、最终汇报。
- 前端任务计划围绕具体用户工作流。
- 计划由 agent 生成，但必须结构化。

### 阶段六：PlanCoverageReview gate

目标：

- 对 `AgentPlanDraft` 做合同覆盖审查。
- 不通过时要求 replan，而不是继续执行。

涉及文件：

- `backend/runtime/professional_runtime/plan_coverage.py`
- `backend/runtime/professional_runtime/driver.py`
- `backend/tests/professional_task_run_regression.py`

完成标准：

- 缺少浏览器验证步骤的前端/游戏计划不能执行。
- 缺少资源接入步骤的游戏计划不能执行。
- 把 final report 放在第一步并替代实现的计划不能执行。

### 阶段七：ExecutionRecipe / TaskRunLedger 对接动态计划

目标：

- 固定系统阶段继续由 `ExecutionRecipe.step_blueprints` 表达。
- `AgentPlanDraft.steps` 映射到 `TaskRunLedger.step_runs` 的业务步骤。
- 每个业务步骤必须挂 observation refs。

涉及文件：

- `backend/task_system/planning/understanding_step_compiler.py`
- `backend/task_system/tasks/step_models.py`
- `backend/task_system/tasks/run_models.py`
- `backend/runtime/professional_runtime/driver.py`

完成标准：

- ledger 能显示系统阶段和 agent 业务步骤。
- 每个执行步骤能追踪输入、输出、观察和失败原因。

### 阶段八：EvidencePacket 标准化

目标：

- 将文件、命令、浏览器、截图、测试、模型评审全部标准化为 typed evidence。
- 让 profile-driven validator 不依赖自由文本 marker。

涉及文件：

- `backend/runtime/memory/evidence_packet.py`
- `backend/runtime/contracts/evidence_types.py`
- `backend/runtime/professional_runtime/evidence_closeout.py`

建议 evidence 类型：

```text
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
gameplay_check
workflow_check
model_review
blocked_reason
```

完成标准：

- 不再主要靠 `preview` 文本猜证据类型。
- 浏览器验证、文件写入、资源可见性都能结构化表达。

### 阶段九：CompletionJudgment 替代单薄 validator

目标：

- 新增 `CompletionJudgment`。
- `deliverable_validator` 保留为底层检查器，但不再是最终裁决模型。

涉及文件：

- `backend/runtime/contracts/completion_judgment.py`
- `backend/runtime/contracts/deliverable_validator.py`
- `backend/runtime/professional_runtime/driver.py`

完成标准：

- 输出 `verified / partially_verified / unverified / blocked / contradicted`。
- unsupported claims 明确进入 judgment。
- final answer 根据 judgment 诚实汇报完成度。

### 阶段十：旧逻辑收口

目标：

- 旧 `query_understanding` 降级为 weak signal。
- 清理重复 task_goal_type if/else。
- 删除无用旧测试和旧残留。

涉及文件：

- `backend/understanding/task_understanding.py`
- `backend/understanding/query_understanding.py`
- `backend/task_system/contracts/semantic_task_contracts.py`
- `backend/intent/execution_obligation.py`
- 相关 regression tests

完成标准：

- 系统只有一个主任务裁决源：`GoalHypothesisSet -> TaskGoalFrame -> TaskGoalProfileBinding`。
- legacy route 只能影响工具效率，不能覆盖目标裁决。

## 8. 肉鸽任务期望闭环

同样输入“开发浏览器端 2D 肉鸽游戏垂直切片”后，系统应产生：

```text
GoalHypothesisSet:
  chosen = game_vertical_slice_delivery
  rejected = artifact_delivery
  rejection_reason = final_report 是辅助产物，不是核心产品目标

TaskGoalFrame:
  task_goal_type = game_vertical_slice_delivery
  task_domain = development
  core_deliverables = runnable_game, source_files, visual_asset, gameplay_features
  supporting_deliverables = stage_docs, final_report
  unacceptable_outcomes = final_report_only, design_doc_only, unverified_game_claim

TaskGoalProfileBinding:
  profile_id = game_vertical_slice_delivery
  task_domain = development

SemanticTaskContract:
  deliverables = runnable_artifact_refs, gameplay_acceptance, visual_asset_refs, verification_evidence, final_report
  required_actions = inspect_code, apply_real_change, integrate_asset, run_browser_verification, validate_deliverables

AgentPlanDraft:
  inspect_project
  identify_entrypoints
  implement_game_loop
  implement_player_and_enemy_interaction
  add_progression_or_hud
  integrate_visual_asset
  run_app
  browser_verify_canvas_and_gameplay
  write_final_report

PlanCoverageReview:
  passed = true
  covered_actions = apply_real_change, integrate_asset, run_browser_verification

CompletionJudgment:
  status = verified | partially_verified | blocked
  never verified when only final_report exists
```

## 9. 验证矩阵

必须覆盖：

- 浏览器肉鸽游戏开发。
- 前端应用/编辑器开发。
- 普通代码修复。
- 单文件 Markdown 交付。
- PDF 阅读。
- 表格分析。
- 实时查询。
- 测试报告诊断。
- 任务图节点执行。

关键断言：

- 产品开发任务不能被报告路径劫持。
- agent 生成的计划必须覆盖合同义务。
- 没有 evidence 的完成声明进入 `unverified` 或 `contradicted`。
- 环境阻断进入 `blocked`，不能伪装成完成。
- 短任务不应被长任务控制流拖慢。

## 10. 风险控制

### 风险一：模型主动性导致漂移

控制：

- 模型只能在注册 goal profile 内选择。
- plan 必须过 coverage review。
- 未覆盖合同义务时不能执行。

### 风险二：系统规则过硬导致 agent 失去灵活性

控制：

- 系统只固定阶段和合同，不写死业务步骤。
- agent 可以提出替代验证方式，但必须说明 evidence expectation。

### 风险三：验证无法完全自动化

控制：

- 使用 `CompletionJudgment` 表达置信状态。
- 可机器验证的用工具验证。
- 语义质量用模型评审辅助，但不能替代事实 evidence。

### 风险四：新旧系统并行混乱

控制：

- 不新增 domain profile 平行层。
- 旧理解层只保留为 weak signal。
- 阶段十必须清理旧残留。

## 11. 禁止事项

1. 禁止只给肉鸽样本加关键词特判。
2. 禁止新增 `task_system.domains` 平行体系。
3. 禁止把 `game_vertical_slice_delivery` 当独立任务域。
4. 禁止让 final report 替代核心产品交付。
5. 禁止让模型自述替代工具 evidence。
6. 禁止把 runtime 节点说明写进 agent-facing prompt。
7. 禁止保留无用旧残留代码和旧测试。
8. 禁止计划未覆盖合同义务就进入执行。

## 12. 下一步执行建议

按当前代码现状，下一步不应该继续扩写 validator 分支，而应该先做：

1. `GoalHypothesisSet`
2. `TaskGoalFrame v2`
3. `AgentPlanDraft`
4. `PlanCoverageReview`

这四步完成后，理解系统才会从“目标分类 + 合同补强”升级为“成熟 agent 主动规划 + 系统契约审查”的架构。
