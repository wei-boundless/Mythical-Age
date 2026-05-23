# 成熟 Agent 理解系统范式设计计划书

日期：2026-05-23

## 0. 不可变更的设计立场

本系统不是要复制一个纯 vibe coding agent，也不是把任务域删除后完全依赖模型自由发挥。

本系统的核心设计立场是：

```text
强模型主动理解
  + 平台可配置任务域成熟制式
  + 显式任务目标合同
  + agent 自主生成执行计划
  + 系统审查覆盖、权限和证据
  + 最终以证据裁决完成状态
```

`TaskDomainRecord` 必须保留。它不是旧设计，也不是低级分类器。它是平台给 agent 的成熟领域先验和稳定工作制式，用来缩小行动空间、提供默认流程、工具边界、验证习惯和风险控制。

这与 Codex 近期更通用任务的设计方向并不冲突：成熟 agent 会根据任务类别、工具边界、环境规则、用户显式流程和长期经验收窄行动空间。区别只是 Codex/CClaude Code 更多把这些东西内化在系统提示、工具协议、技能、运行时策略和模型能力里；本系统选择把其中一部分显式平台化、可配置化、可审计化。

禁止把本设计篡改成：

```text
用户消息 -> 关键词分类 -> 任务域决定流程 -> 系统写死步骤 -> agent 照做
```

正确范式是：

```text
用户消息 -> 通用理解与交流承接 -> 目标假设裁决 -> 任务域制式补强 -> 语义任务合同 -> agent 生成计划 -> 系统审查与执行
```

## 1. 成熟 Agent 的真实分层

成熟 agent 不是简单地“先分类任务域”。它一般同时做五种判断：

1. 交流承接判断：用户是在提问、讨论方案、下达执行、纠偏、审查、继续任务，还是表达不满。
2. 目标判断：用户真正要完成什么，不被文件名、路径、报告要求或工具路由抢走主目标。
3. 行动边界判断：能不能改、要不要先问、是否只读、是否需要联网、是否需要验证。
4. 工作制式选择：根据任务域、环境、工具和成熟经验选择默认流程。
5. 执行状态管理：复杂任务生成 todo/plan，推进时更新，发现事实后修正。

其中第 4 点就是任务域结构的合理位置。任务域不是主裁判，但它是成熟工作制式来源。

## 2. 目标控制流

目标主链路固定为：

```text
UserMessage
  -> CommunicationFrame
  -> TaskUnderstandingFrame
  -> GoalHypothesisSet
  -> TaskGoalFrame
  -> TaskDomainBinding
  -> TaskGoalProfileBinding
  -> SemanticTaskContract
  -> ExecutionObligation
  -> AgentPlanDraft
  -> PlanCoverageReview
  -> AgentTodoPlan
  -> ExecutionLedger
  -> EvidencePacket
  -> CompletionJudgment
  -> FinalAnswer
```

这个顺序不能互相替代：

- `CommunicationFrame` 决定如何承接用户。
- `TaskUnderstandingFrame` 决定本轮任务边界。
- `GoalHypothesisSet` 负责目标候选和拒绝理由。
- `TaskDomainBinding` 只提供成熟制式和默认约束。
- `SemanticTaskContract` 是运行期共同合同。
- `AgentPlanDraft` 必须由 agent 根据真实上下文生成或修正。
- `AgentTodoPlan` 是执行状态，不是理解层和目标层。
- `CompletionJudgment` 是完成裁决，不是最终回答修辞。

## 3. 各层工程合同

### 3.1 CommunicationFrame

职责：

- 判断用户当前是在什么协作姿态下发言。
- 决定 agent 是直接回答、先澄清、先规划、直接执行、停下纠偏，还是继续已有任务。
- 决定回复密度、是否需要中间进度、是否需要 review-first 输出。

字段建议：

```text
frame_id
user_posture: ask / explore / execute / correct / continue / review / dissatisfied
agent_posture: answer / clarify / plan_first / execute / review_first / repair_understanding
collaboration_mode: conversation / planning / implementation / verification / long_task
clarification_policy: ask_now / proceed_with_assumption / no_clarification_needed
progress_policy: none / brief_updates / todo_required
final_response_contract: direct_answer / implementation_report / findings_first / verification_report
latest_user_instruction_priority: boolean
```

不允许：

- 不允许在这一层指导具体工具操作。
- 不允许把 todo、测试、浏览器验证等执行细节塞进交流承接层。

### 3.2 TaskUnderstandingFrame

职责：

- 表达用户本轮请求的通用任务边界。
- 捕获目标对象、显式流程、禁令、约束、上下文绑定和证据要求。
- 为目标假设和任务域绑定提供输入。

当前已有字段位于 `backend/intent/task_understanding_frame.py`，但应升级为模型辅助理解。

必须补强：

- `communication_frame_ref`
- `priority_stack`
- `conflict_set`
- `assumption_set`
- `decision_trace`

不允许：

- 不允许直接生成执行步骤。
- 不允许决定工具可用性。
- 不允许把任务域默认流程当作用户目标。

### 3.3 GoalHypothesisSet

职责：

- 生成多个目标候选。
- 记录为什么选择当前目标。
- 记录为什么拒绝其他候选。
- 处理“报告/文件/路径/工具动作”与“真实任务目标”的冲突。

要求：

- 每个候选必须有 `task_goal_type`、`task_domain`、证据和拒绝理由。
- 目标裁决必须优先用户真实目标，而不是输出格式或工具路线。
- 未注册目标类型不能直接进入 chosen。

### 3.4 TaskDomainBinding

职责：

- 绑定一个或多个 `TaskDomainRecord`。
- 给 agent 提供成熟制式：默认阶段、典型风险、推荐验证、工具边界、常见失败模式。
- 作为 domain prior 缩小行动空间。

必须明确：

```text
TaskDomainBinding 不裁决用户目标。
TaskDomainBinding 不覆盖用户显式流程。
TaskDomainBinding 不覆盖 forbidden_actions。
TaskDomainBinding 可以在用户没说清的地方补默认专业习惯。
```

这层是你的设计理念中必须保留的外层任务域结构。

### 3.5 TaskGoalProfileBinding

职责：

- 将 `TaskGoalFrame.task_goal_type` 绑定到目标画像。
- 给出核心交付物、默认验收、专业 profile、验证习惯。

它和任务域的区别：

```text
TaskDomainRecord = 领域成熟制式
TaskGoalProfile = 本轮目标类型模板
```

例如：

```text
development = TaskDomainRecord
frontend_app_delivery = TaskGoalProfile
game_vertical_slice_delivery = TaskGoalProfile
code_fix_execution = TaskGoalProfile
```

### 3.6 SemanticTaskContract

职责：

- 汇总理解、目标、任务域、目标画像、用户约束、材料和执行义务。
- 形成 runtime、计划审查、验证、最终回答共同引用的合同。

要求：

- 必须保留 `task_understanding_frame`、`goal_hypothesis_set`、`task_domain_binding` diagnostics。
- 必须明确 deliverables、required_actions、forbidden_actions、validation_schema。
- 不允许只靠 prompt 文本表达关键合同。

### 3.7 AgentPlanDraft

职责：

- 由 agent 生成真实可执行计划。
- 根据读到的代码、材料和环境事实修正。
- 每个步骤声明预期产物、所需操作和证据期望。

不允许：

- 不允许由平台提前写死所有具体业务步骤。
- 不允许把系统 runtime 节点当作 agent 执行步骤。

### 3.8 AgentTodoPlan

职责：

- 维护执行过程中的可变状态。
- 记录 pending / in_progress / completed。
- 帮助用户和系统理解当前推进位置。

位置：

```text
AgentTodoPlan 属于执行状态层。
它不属于 CommunicationFrame。
它不属于 TaskUnderstandingFrame。
它不属于 TaskGoalFrame。
```

工具可用性要求：

- `agent_todo` 只有在 operation requirement 和 resource policy 中真实暴露时，prompt 才能提示使用。
- 不允许 prompt 说“使用 agent_todo”但运行时没有 `op.agent_todo`。

### 3.9 EvidencePacket 与 CompletionJudgment

职责：

- `EvidencePacket` 只接收真实观察：文件读写、命令、浏览器、测试、结构化材料、模型评审。
- `CompletionJudgment` 裁决完成状态：verified / partially_verified / blocked / unverified / contradicted。

不允许：

- 不允许把模型自述当事实证据。
- 不允许测试没跑却宣称通过。
- 不允许 final answer 替代证据。

## 4. 与 Codex / Claude Code 的比较

### 4.1 共同点

三者都需要：

- 根据用户最新指令修正行动。
- 区分解释、规划、执行、审查、继续任务。
- 对复杂任务维护计划或 todo。
- 工具权限与执行状态分离。
- 完成声明依赖验证证据。
- 任务流程不能覆盖用户禁令。

### 4.2 Codex 型范式

Codex 更偏：

```text
强模型通用理解
  + 系统提示中的工程纪律
  + 工具和权限边界
  + 动态计划/todo
  + 实时验证
```

它也会做任务域收窄，只是不一定暴露成 `TaskDomainRecord`。例如代码审查、前端实现、测试修复、文档处理、浏览器验证，本质上都会激活不同工作制式。

因此，保留任务域结构不是落后，而是把隐式 domain prior 显式平台化。

### 4.3 Claude Code 型范式

Claude Code 更偏：

```text
主 agent 强理解
  + 工具级 todo 说明
  + 只读 Plan Agent
  + 只读 Verification Agent
  + 文件/命令权限边界
  + 项目 CLAUDE.md 规则注入
```

它的 TodoWrite 是执行工具说明，不是理解入口。Plan Agent 是只读计划专家，Verification Agent 是只读反向验证专家。

本系统应借鉴：

- todo 只在执行状态层。
- 计划可以由只读 planner 生成。
- 验证应有独立 verifier，而不是实现者自证。
- prompt 必须是角色职责语言，不是 runtime 节点说明。

不应照搬：

- 不应把所有理解都藏在一个巨大 system prompt 中。
- 不应删除平台任务域配置能力。
- 不应让专用 agent 替代显式任务合同。

## 5. 当前实现的严格判定

### 5.1 已成立

- `TaskUnderstandingFrame` 已作为通用理解结构接入。
- `TaskGoalFrame` 已携带理解框架。
- `SemanticTaskContract` 已保留理解 diagnostics。
- `task_understanding_section` 已从执行工具说明退回交流承接层。
- `agent_todo` 已作为执行状态工具接入 operation registry、resource policy 和 tool mapping。
- `CommunicationFrame` 已独立建模并接入理解帧和 prompt 装配。
- `TaskDomainBinding` 已作为正式绑定产物进入语义合同，并作为独立 domain playbook section 注入 prompt。
- `ModelUnderstandingRequest`、`ModelUnderstandingDraft`、`UnderstandingArbitration` 已形成模型辅助理解入口；没有真实模型草稿时明确标记 `model_draft_absent`，不伪造模型理解。
- `AgentPlanDraft` 已区分真实 `model_agent_plan_draft` 与系统脚手架兜底；兜底状态明确标记为 `scaffold_fallback`。
- `ReadonlyPlannerRequest` 已为后续只读 planner/model 计划生成提供请求契约。
- `PlanCoverageReview` 已成为硬 gate；覆盖未通过时 professional recipe 不进入后续执行步骤。
- `ReadonlyVerifierRequest`、`VerificationReview`、`CompletionJudgment` 已接入，完成状态由证据、交付验证和义务验证裁决。

### 5.2 尚未成立

- 尚未接入真实模型调用器来自动生成 `ModelUnderstandingDraft`；当前已完成的是请求契约、schema 校验、仲裁和无草稿诊断。
- 尚未接入真实只读 planner 子 agent 来自动生成 `AgentPlanDraft`；当前已完成的是只读 planner 请求契约、模型计划草稿验收和系统兜底标记。
- 尚未接入真实只读 verifier 子 agent 的模型调用；当前已完成的是只读 verifier 请求契约、结构化评审与完成裁决。
- 尚未实现 plan repair loop 的自动重拟过程；当前硬 gate 会阻断后续执行，并要求补齐或修正计划。
- 尚未把 `CompletionJudgment` 全面替换所有旧 runtime 收口路径；professional runtime 已产出 completion judgment 事件和 final answer metadata，但更外层历史路径仍需逐步切换。

这些不是“基本对”。它们就是未完成项。

## 6. 下一阶段实施计划

### 阶段一：CommunicationFrame 正式化

新增：

- `backend/intent/communication_frame.py`
- `backend/tests/communication_frame_regression.py`

接入：

- `TaskUnderstandingFrame.communication_frame_ref`
- `TaskUnderstandingFrame.communication_frame`
- `prompt_library.assembler._task_understanding_section`

完成标准：

- 用户纠偏时识别 `user_posture=correct`、`agent_posture=repair_understanding`。
- 用户提问时不进入执行状态。
- 用户明确“继续推进”时绑定 continuation。

### 阶段二：TaskDomainBinding 正式化

新增：

- `backend/task_system/domains/task_domain_binding.py`

接入：

- 从 `TaskUnderstandingFrame.task_domain_hint` 和 `TaskGoalFrame.task_domain` 绑定 `TaskDomainRecord`。
- 写入 `SemanticTaskContract.diagnostics.task_domain_binding`。
- prompt 中新增 domain playbook section，但必须低于用户流程和目标合同。

完成标准：

- `development` 能提供默认验证、代码阅读、最小变更、测试习惯。
- 用户禁令能覆盖 domain playbook。
- goal profile 不再承担 domain playbook 职责。

### 阶段三：模型辅助理解

新增：

- `ModelUnderstandingDraft`
- `UnderstandingArbitration`

流程：

```text
deterministic signals
  + model understanding draft
  -> arbitration
  -> TaskUnderstandingFrame
```

完成标准：

- deterministic 只做弱信号和兜底。
- 模型输出必须被 schema 校验。
- 冲突必须进入 `conflict_set`，不能静默覆盖。

### 阶段四：模型生成 AgentPlanDraft

新增：

- `backend/runtime/professional_runtime/model_plan_generator.py`
- `backend/runtime/professional_runtime/plan_repair_loop.py`

要求：

- agent 根据合同和真实 workspace observation 生成计划。
- 计划每步含 evidence expectation。
- PlanCoverageReview 不通过则重拟或标记 blocked。

### 阶段五：独立 Verifier 与 CompletionJudgment

新增：

- `backend/runtime/professional_runtime/completion_judgment.py`
- `backend/runtime/professional_runtime/verification_review.py`

要求：

- verifier 只读，不允许修改项目。
- 运行验证命令或明确记录环境阻断。
- CompletionJudgment 输出完成状态，不输出营销式结论。

## 7. Prompt 设计铁律

任何 prompt section 都必须先回答：

```text
它属于哪一层？
它让 agent 扮演什么职责？
它是否描述了系统机制而不是 agent 任务？
它提到的工具在当前层是否真实可用？
它是否覆盖了用户显式流程或禁令？
```

示例：

正确的理解入口：

```text
你负责先判断本轮请求应该如何被承接。
如果用户在纠偏，你要先修正理解，而不是继续旧计划。
如果用户在提问，你要回答问题，不要擅自进入执行。
如果用户给出明确流程，你要让后续任务边界尊重这个流程。
```

错误的理解入口：

```text
你需要调用 agent_todo。
你需要执行 execution_planning 节点。
你需要消费 task_understanding_frame。
```

正确的执行状态提示：

```text
你是一名任务执行规划员。
进入多步执行时，你需要维护待处理、进行中、已完成的任务状态。
如果当前可用工具包含 agent_todo，你可以用它记录和修正执行状态。
```

## 8. 验收标准

一个成熟 agent 理解系统必须满足：

1. 用户纠偏会改变理解，而不是被旧计划吞掉。
2. 任务域提供成熟制式，但不能替代用户目标。
3. 目标候选有选择理由和拒绝理由。
4. prompt section 的职责位置清楚，不能混层。
5. 工具提示必须和真实 operation/resource 可用性一致。
6. agent 生成具体计划，系统只审查覆盖和证据。
7. verifier 独立于 implementer。
8. 最终完成状态由证据裁决，而不是由回答语气裁决。
