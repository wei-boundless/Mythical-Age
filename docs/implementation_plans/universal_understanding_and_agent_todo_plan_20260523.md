# 通用理解系统与 Agent Todo 工具实施计划书

日期：2026-05-23

## 1. 现有层次审查

当前系统已经具备比较完整的任务运行骨架：

- `TaskDomainRecord`：正式任务域层，适合保存开发、写作、数据、文档、研究等成熟制式。
- `TaskGoalProfile`：具体目标画像层，适合保存代码修复、前端交付、文件产物、材料综合等目标模板。
- `GoalHypothesisSet` / `TaskGoalFrame`：本轮目标理解层，已经能表达候选目标、拒绝候选、核心交付物、不可接受结果。
- `SemanticTaskContract`：合同层，负责把目标、材料、义务、交付物和验证要求合成 runtime 可消费结构。
- `AgentPlanDraft` / `PlanCoverageReview`：执行计划与覆盖审查层，已经具备雏形。
- `prompt_library`：prompt 装配层，已经能把目标理解、语义合同、执行计划、覆盖审查注入 agent-facing prompt。
- `capability_system`：工具注册、工具合同、prompt 可见性、权限边界已经集中管理。

主要结构问题：

1. 还缺少一个真正通用的“agent 原生理解层”。
   现在 `query_understanding` 更像路由/能力候选，`TaskGoalFrame` 更像目标合同，中间缺少“用户这句话在 agent 认知里被拆成哪些层”的稳定结构。

2. 任务域和目标画像的边界需要继续压实。
   任务域应该是成熟制式库，不是替 agent 判断用户要什么；目标画像可以指导交付物，但不能覆盖用户明确流程和禁令。

3. 计划层还偏系统脚手架。
   成熟 agent 的具体 todo/plan 应该由 agent 理解任务后生成，系统负责可见化、覆盖审查和完成证据，而不是预先写死所有业务步骤。

4. 当前工具系统缺少 todo 状态工具。
   复杂任务需要一个可被 agent 显式调用的 `agent_todo` 工具，用于创建、更新、清理本轮执行步骤，并为后续 coverage/evidence 链路提供稳定状态。

## 2. 设计原则

1. 通用理解流程不变，任务域只提供成熟制式。
2. 用户明确流程优先于任务域默认制式。
3. 任务域缩小行动空间，不替 agent 做最终理解。
4. 具体步骤由 agent 生成，系统检查覆盖。
5. todo 是执行状态，不是上游分类器。
6. prompt 面向 agent 职责描述，不能暴露 runtime 节点术语。
7. 完成声明必须回指真实证据或明确限制。

优先级固定为：

```text
安全/权限边界
  > 用户明确流程
  > 本轮目标理解
  > 任务域成熟制式
  > agent 自生成 todo/plan
  > 默认习惯
```

## 3. 目标架构

目标链路：

```text
UserMessage
  -> TaskUnderstandingFrame
  -> GoalHypothesisSet
  -> TaskGoalFrame
  -> TaskDomain Playbook binding
  -> TaskGoalProfileBinding
  -> SemanticTaskContract
  -> AgentTodoPlan / AgentPlanDraft
  -> PlanCoverageReview
  -> EvidencePacket
  -> CompletionJudgment
  -> FinalAnswer
```

其中：

- `TaskUnderstandingFrame` 负责表达 agent 对用户请求的通用认知层次。
- `TaskDomainRecord` 继续作为外层成熟制式库。
- `TaskGoalProfile` 继续作为目标画像和交付模板。
- `AgentTodoPlan` 是 agent 执行中可变步骤状态。
- `PlanCoverageReview` 只检查覆盖，不替 agent 写计划。

## 4. 本次实施范围

本次一次性完成以下增量：

1. 新增 `TaskUnderstandingFrame` 数据模型和 deterministic 构建器。
2. 将理解框架接入 `TaskGoalFrame`、`SemanticTaskContract`、prompt 装配。
3. 新增 `agent_todo` 工具和 todo 状态模型。
4. 将 `agent_todo` 注册进 capability tool registry。
5. 增加回归测试，覆盖通用理解层、prompt 可见性、todo 工具状态。

本次暂不做：

- 不引入模型目标理解调用。
- 不做完整数据库持久化 todo。
- 不替换现有 `AgentPlanDraft`，只为后续 model-generated plan 做结构准备。
- 不新增平行 `TaskDomainProfile`。

## 5. 文件级改动

新增：

- `backend/intent/task_understanding_frame.py`
- `backend/runtime/professional_runtime/agent_todo.py`
- `backend/capability_system/units/tools/agent_todo_tool.py`
- `backend/tests/universal_understanding_frame_regression.py`
- `backend/tests/agent_todo_tool_regression.py`

修改：

- `backend/intent/__init__.py`
- `backend/intent/task_goal_frame.py`
- `backend/intent/task_goal_interpreter.py`
- `backend/task_system/contracts/semantic_task_contracts.py`
- `backend/prompt_library/models.py`
- `backend/prompt_library/selector.py`
- `backend/prompt_library/assembler.py`
- `backend/prompt_library/runtime_sections.py`
- `backend/capability_system/tool_definitions.py`

## 6. 数据模型

`TaskUnderstandingFrame` 字段：

- `frame_id`
- `user_message`
- `interaction_intent`
- `action_intent`
- `target_objects`
- `desired_outcomes`
- `explicit_constraints`
- `forbidden_actions`
- `user_provided_flow`
- `context_binding`
- `execution_mode_hint`
- `task_domain_hint`
- `task_goal_type_hint`
- `evidence_requirements`
- `ambiguity_points`
- `clarification_needed`
- `clarification_question`
- `playbook_policy`

`AgentTodoPlan` 字段：

- `plan_id`
- `session_id`
- `task_id`
- `items`
- `active_item_id`
- `completion_ready`
- `coverage_refs`

`AgentTodoItem` 字段：

- `todo_id`
- `content`
- `active_form`
- `status`
- `evidence_expectations`
- `contract_refs`
- `notes`

## 7. Prompt 设计

`task_understanding_section` 只负责入口理解和交流承接，不负责执行状态管理。

新增 agent-facing section：

```text
你负责先判断本轮请求应该如何被承接：用户是在提问、探讨方案、下达执行、纠偏，还是延续之前任务。
你需要以用户真实目标、明确流程、约束和证据要求来确定行动边界。
任务域只提供成熟工作习惯；用户明确给出的流程和禁令优先于任务域默认制式。
如果存在会导致误执行的歧义，你应该先澄清；如果边界足够清楚，就按当前协作姿态继续。
```

`agent_todo` 不放在理解入口，而放在执行计划/执行状态层。执行计划 section 可以写成：

```text
你是一名任务执行规划员。
进入多步执行时，你需要维护当前任务的执行状态：哪些步骤待处理、哪一步正在进行、哪些步骤已经完成。
如果本轮可用工具中包含 agent_todo，请用它记录和更新执行状态；当真实发现改变计划时，先更新状态再继续行动。
todo 只是执行状态，不能替代用户目标、语义任务合同或完成证据。
```

禁止写成：

```text
这是 task_understanding_frame runtime 节点。
消费上游字段并生成下游字段。
```

## 8. 验证矩阵

必须覆盖：

- 通用开发请求：识别为 `development`，但具体步骤不预先写死。
- 用户明确流程：进入 `user_provided_flow`，并在 prompt 中高优先级呈现。
- 继续任务：识别 `context_binding.kind=continuation`。
- 分析/只读任务：生成 read-only 或 analysis execution hint。
- 文件交付任务：仍能进入 `artifact_delivery`。
- `agent_todo` 工具能创建、更新、完成、删除 todo。
- registry 中能看到 `agent_todo`，并且不是 destructive 工具。

## 9. 完成标准

1. `TaskGoalFrame.to_dict()` 包含通用理解框架引用和 payload。
2. `SemanticTaskContract.diagnostics` 保留 `task_understanding_frame`。
3. prompt selector/context/assembler 能把理解框架注入 model-visible section。
4. `agent_todo` 工具出现在 tool definitions 和 registry payload。
5. 新增测试和相关既有理解/prompt/tool 测试通过。
