# Prompt Library 在新理解系统完成后的重规划计划书

日期：2026-05-24

状态：统筹重规划版

## 1. 这次重规划的前提

理解系统已经完成重构，当前后端的任务入口不再应该围绕旧的 `task_goal_frame -> route_hint -> goal_profile` 体系继续扩张，而应以新的模型拥有理解权链路为前提：

```text
UserRequest
-> RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> ModelTurnDecision
-> ActionPermit
-> RuntimeStartPacket
-> TaskRequirementContract / ExecutionShape / Recipe
-> Prompt Assembly
-> ExecutionLoop
```

因此，Prompt Library 现在必须跟着这条链路重新定位：

1. 不再参与“猜用户要做什么”。
2. 不再依赖旧 `route_hint / primary_intent / task_goal_frame` 作为主输入。
3. 只在模型已经做出当前轮判断之后，负责提示词资源选择、动态装配、来源追踪和边界校验。

这不是补丁式修改，而是 Prompt Library 的一次职责归位。

## 2. 当前代码现实

## 2.1 新理解链路已经成型

当前代码里，新的理解权链路已经具备真实结构：

- `backend/agent_runtime/understanding/model_turn_decision.py`
  - 主模型产出 `interaction_intent / action_intent / work_mode / deliverables / constraints / completion_criteria`。
- `backend/agent_runtime/understanding/runtime_start_packet.py`
  - 运行入口已能收口 `request_facts / boundary_policy / context_candidates / model_turn_decision / action_permit`。
- `backend/request_intent/frame_access.py`
  - 已能按 accessor 暴露 `model_turn_decision / action_permit / request_facts / context_binding / capability_needs`。
- `backend/task_system/contracts/task_requirement_contracts.py`
  - 已开始围绕 `model_turn_decision + task_goal_spec` 生成 `TaskRequirementContract`。
- `backend/task_system/services/assembly_builder.py`
  - 已硬要求 `current_turn_context["model_turn_decision"]` 和 `current_turn_context["task_goal_spec"]` 存在。

这意味着 Prompt Library 的真正上游已经变了。

## 2.2 Prompt Library 还带着旧时代的影子

当前 Prompt Library 虽然已有雏形，但它的选择上下文仍然偏旧：

- `backend/prompt_library/models.py`
  - `PromptSelectionContext` 仍保留 `task_goal_type / task_domain_binding / goal_hypothesis_set / task_goal_spec / projection` 时代的结构惯性。
- `backend/prompt_library/selector.py`
  - 已能做流程感知选择，但其语义仍建立在旧任务分类概念上。
- `backend/prompt_library/assembler.py`
  - 仍然显式渲染：
    - `goal_understanding_section`
    - `domain_playbook_section`
    - `projection_section`
  - 并继续把旧诊断数据送入模型可见装配。
- `backend/prompt_library/runtime_sections.py`
  - 仍把 `projection_section` 当成模型可见 section 的正式层。

结论很明确：

Prompt Library 的实现已经比以前进步很多，但它还没有完全切到“新理解系统完成后的主语义”。

## 3. 新架构下 Prompt Library 的职责边界

Prompt Library 在新架构中的职责必须收缩并且更清楚：

### 3.1 它负责什么

1. 管理静态 prompt 资源。
2. 根据当前轮结构化上下文选择资源。
3. 根据当前任务阶段动态装配模型可见 prompt。
4. 记录本轮 prompt 的来源、绑定原因、显隐和校验结果。
5. 阻止旧概念、内部字段、弱推断污染模型可见 prompt。

### 3.2 它不负责什么

1. 不重新理解用户任务。
2. 不重新决定工作模式。
3. 不重新决定要不要计划。
4. 不重新选择执行策略。
5. 不通过 prompt 绕过 `BoundaryPolicy / ActionPermit`。
6. 不再作为 projection/soul 的承载层。

一句话概括：

Prompt Library 现在是“运行前提示词装配层”，不是“任务理解层”。

## 4. 新的输入面定义

本轮重构后，Prompt Library 的合法主输入应统一为以下几类。

## 4.1 第一层：理解结果输入

来自 `RuntimeStartPacket` 和 request intent：

- `request_facts`
- `boundary_policy`
- `context_candidates`
- `model_turn_decision`
- `action_permit`

其中真正决定 prompt 装配方向的核心是：

- `model_turn_decision`
- `action_permit`

## 4.2 第二层：任务编译输入

来自任务系统编译层：

- `task_goal_spec`
- `task_requirement_contract`
- `mode_policy`
- `execution_shape`
- `selected_recipe`
- `task_workflow`
- `operation_requirement`

这层输入回答的不是“用户想做什么”，而是：

- 当前任务被编译成了什么合同；
- 当前执行应该按什么形态推进；
- 当前阶段需要哪些职责、技能、验证和输出边界。

## 4.3 第三层：运行阶段输入

来自 execution/runtime：

- `current_step_id`
- `current_step_kind`
- `workflow_id / graph_id / node_id / stage_id`
- `agent_plan_draft`
- `plan_coverage_review`
- `verification_review`
- `completion_judgment`

这层决定的是当前要给模型看哪一段“阶段职责 prompt”，而不是重新给任务定性。

## 5. 新 Prompt Library 的静态资源分类

理解系统已经重构后，静态库继续保留，但需要重新解释用途。

建议保留的资源类型如下：

| resource_type | 新定位 |
|---|---|
| `common_contract` | 所有任务通用底线 |
| `mode_policy` | conversation / implementation / verification / planning 等模式边界 |
| `understanding_policy` | 只给“任务理解阶段节点”使用，不再给普通执行阶段泛化使用 |
| `flow_matching_policy` | 只给“目标到流程绑定阶段”使用 |
| `domain_role` | 某类专业任务的长期职责 |
| `stage_role` | 当前阶段或当前节点的即时职责 |
| `skill_prompt` | 某项 skill 的高质量使用要求 |
| `tool_guidance` | 工具结果如何转化为证据 |
| `verification` | 验证边界 |
| `output_boundary` | 最终交付边界 |
| `role_prompt` | 仅 role mode 可见的灵魂/角色提示词 |

## 5.1 需要降权的旧概念

以下概念不应再作为 Prompt Library 的核心组织轴：

1. `projection`
2. `legacy_projection_ids`
3. `goal_hypothesis_set` 直接进入模型正文
4. `task_goal_profile_binding` 直接进入模型正文
5. 旧 `route_hint` 风格的理解辅助信号

这些可以保留在 diagnostics 中，但不应继续成为模型可见主 prompt 的正式来源。

## 6. 新 PromptSelectionContext 应如何改

当前 `PromptSelectionContext` 最大的问题不是字段多，而是“哪些字段是主输入、哪些只是诊断输入”没有重新划清。

建议把它重构为三组字段。

## 6.1 主选择字段

这批字段直接参与选择：

- `task_id`
- `agent_id`
- `interaction_mode`
- `work_mode`
- `interaction_intent`
- `action_intent`
- `task_goal_type`
- `task_domain`
- `workflow_id`
- `graph_id`
- `node_id`
- `stage_id`
- `current_step_id`
- `current_step_kind`
- `skill_ids`
- `visible_tool_ids`

## 6.2 合同与验证字段

这批字段不决定基础分类，但决定要不要装配验证、计划、收口类资源：

- `task_goal_spec`
- `task_requirement_contract`
- `agent_plan_draft`
- `plan_coverage_review`
- `verification_review`
- `completion_judgment`
- `action_permit`
- `boundary_policy`

## 6.3 纯诊断字段

这些字段保留在 metadata / diagnostics 即可，不应成为主 prompt 选择主轴：

- `goal_hypothesis_set`
- `task_domain_binding`
- `task_goal_profile_binding`
- 任何旧 projection 迁移痕迹

换句话说，选择上下文要从“历史遗留信息堆”变成“以模型判断和任务编译结果为中心的上下文包”。

## 7. 新装配体系的核心规则

## 7.1 先模型判断，后 prompt 装配

严格顺序必须是：

```text
ModelTurnDecision
-> TaskRequirementContract
-> ExecutionShape / Recipe / Workflow
-> PromptSelectionContext
-> PromptSelector
-> PromptAssembler
```

Prompt Library 不能再提前影响 `ModelTurnDecision`。

## 7.2 Prompt 装配必须流程感知

既然单 agent 流程已经明确为 step 序列，那么动态装配必须感知当前阶段。

至少应覆盖以下 step kind：

- `task_goal_understanding`
- `domain_flow_matching`
- `contract_compilation`
- `prompt_assembly`
- `execution_planning`
- `plan_coverage_review`
- `step_execution`
- `verification`
- `finalization`

装配规则不是“全程一套 prompt”，而是：

- 理解阶段强调判断边界；
- 流程匹配阶段强调匹配规则；
- 执行阶段强调专业职责；
- 验证阶段强调证据；
- 收口阶段强调完成边界。

## 7.3 Prompt 内容必须是 agent-facing 职责语言

继续严格执行你的原则：

不能写：

```text
这是 runtime 节点。
根据 task graph 执行 verification。
这个节点用于检查资产。
```

必须写：

```text
你是一名交付验证员。
你只根据真实文件、命令、浏览器观察或结构化证据判断当前任务是否达标。
如果缺少关键证据，你必须明确指出未验证项和阻断原因。
```

## 8. 投影系统与 Prompt Library 的关系重划

这个点现在必须正式定下来。

## 8.1 保留什么

保留：

- `role_prompt` 作为 role mode 的角色提示词来源。

## 8.2 取消什么

取消 Prompt Library 内部把 `projection_section` 作为标准任务主层的一部分。

标准模式和专业模式下：

- Prompt Library 不再以 projection 为正式层；
- projection 相关字段只能作为迁移诊断数据存在；
- task graph 旧 projection prompt 必须迁移为 `stage_role` 或 `domain_role`。

## 8.3 为什么现在可以这么做

因为你已经明确要求：

1. 投影系统取消。
2. 只保留灵魂在角色模式下作为角色提示词。
3. 任务模式只装配任务 prompt。

所以 Prompt Library 的主系统现在应当彻底与 projection 解耦。

## 9. 新的动态装配总图

建议新的 Prompt Library 装配链固定为：

```text
PromptStaticResources
  common_contract
  mode_policy
  domain_role
  stage_role
  skill_prompt
  tool_guidance
  verification
  output_boundary

PromptBindings
  task_goal_type bindings
  work_mode bindings
  step_kind bindings
  workflow/node bindings

PromptSelector
  exact binding first
  stage-aware selection
  mode-aware filtering
  role_prompt visibility guard

PromptAssembler
  task contract summary
  stage role summary
  plan summary
  verification summary
  output boundary summary

PromptManifest
  selected
  omitted
  binding reasons
  source refs
  model-visible validation
```

## 10. 需要立即调整的代码目标

下面不是立刻开改，而是下一轮实现必须按这个方向推进。

## 10.1 `backend/prompt_library/models.py`

目标：

1. 收紧 `PromptSelectionContext`。
2. 增加：
   - `work_mode`
   - `interaction_intent`
   - `action_intent`
   - `action_permit`
   - `boundary_policy`
   - `task_requirement_contract`
3. 将旧 `goal_hypothesis_set / task_domain_binding` 降为 diagnostics 用字段。

功能要求：

- 让 selector 的主要判断来自新理解链路，而不是旧 goal 体系余波。

## 10.2 `backend/prompt_library/selector.py`

目标：

1. 选择逻辑以 `model_turn_decision + task_requirement_contract + current step` 为主。
2. `understanding_policy` 只在 `task_goal_understanding` 被强命中。
3. `flow_matching_policy` 只在 `domain_flow_matching` 被强命中。
4. `role_prompt` 严格限定 role mode。
5. `projection` 相关特殊逻辑继续降权。

功能要求：

- 执行阶段不再因为旧理解诊断字段误装配理解层 prompt。

## 10.3 `backend/prompt_library/assembler.py`

目标：

1. 以 `task_requirement_contract + model_turn_decision + action_permit` 为新的主装配输入。
2. 保留 `goal_understanding_section` 仅在理解阶段使用。
3. `projection_section` 退出标准/专业模式装配主路径。
4. `mode_policy_section` 需要开始反映新的 `work_mode`。

功能要求：

- 装配结果应像“当前专业 agent 的职责包”，而不是“历史结构的拼接包”。

## 10.4 `backend/prompt_library/runtime_sections.py`

目标：

1. 只把真正模型可见的任务 section 送进 runtime。
2. projection 只在 role mode 保留。
3. source id / manifest id / contract id 等内部字段只保留在 diagnostics。

功能要求：

- 杜绝模型看见内部运行协议字段。

## 10.5 `backend/task_system/contracts/task_requirement_contracts.py`

目标：

1. 继续弱化旧 profile binding 的直接主导地位。
2. `task_goal_type` 的推导最终以 `model_turn_decision + task_goal_spec` 为准。
3. 后续 prompt library 不再依赖它输出的旧诊断结构作为主输入。

功能要求：

- 它是“合同编译层”，不是“第二理解层”。

## 10.6 `backend/task_system/services/assembly_builder.py`

目标：

1. 后续成为 Prompt Library 的正式上游组织者。
2. 把 prompt 装配所需的当前轮输入整理干净。
3. 不再把 projection 视为任务 prompt 的正式组成。

功能要求：

- 输出给 Prompt Library 的数据包应清楚分层：
  - model-owned understanding
  - task contract
  - step execution state
  - diagnostics

## 11. 新的阶段计划

因为理解系统已经完成，这次计划的顺序也要改。

## 阶段 1：Prompt Library 输入面重整

任务细纲：

1. 盘点 `models.py / selector.py / assembler.py / runtime_sections.py` 中所有旧理解时代字段。
2. 标记：
   - 主输入字段
   - 降级诊断字段
   - 可删除字段
3. 重构 `PromptSelectionContext` 为“新理解链路优先”的结构。

功能要求：

- Prompt Library 的主输入面与 `RuntimeStartPacket + TaskRequirementContract` 对齐。

## 阶段 2：静态资源重新归类

任务细纲：

1. 检查 `default_resources.py` 中每种资源类型是否仍符合新链路。
2. 明确：
   - 哪些资源只在理解阶段使用；
   - 哪些资源只在流程匹配阶段使用；
   - 哪些资源属于执行阶段；
   - 哪些资源只在 role mode 可见。
3. 开始把 `projection` 从任务模式默认资源体系中剥离。

功能要求：

- 资源类型名与实际使用场景一致。

## 阶段 3：动态装配改为流程感知

任务细纲：

1. 让 selector 对 `current_step_kind` 成为一级强信号。
2. 根据 step kind 控制理解、匹配、执行、验证、收口资源的命中。
3. 让 professional mode 的长任务明确依赖：
   - `agent_plan_draft`
   - `plan_coverage_review`
   - `verification_review`
   - `completion_judgment`

功能要求：

- Prompt 能真正随任务阶段变化，而不是只看任务类型。

## 阶段 4：装配结果去 projection 化

任务细纲：

1. 调整 `runtime_sections.py`。
2. 让 standard/professional 不再正式输出 `projection_section`。
3. 只在 role mode 保留 `role_prompt`。

功能要求：

- 新主系统里，projection 不再是任务 prompt 层。

## 阶段 5：建立 Prompt Manifest 与校验器

任务细纲：

1. 为每次装配输出：
   - selected resources
   - omitted resources
   - binding reason
   - mode visibility
   - validation result
2. 增加校验：
   - 标准/专业模式不得含 `role_prompt`
   - 模型可见 prompt 不得泄漏内部字段
   - 缺关键专业 section 时 fail closed

功能要求：

- 以后你在监控里能直接看见“这次为什么装了这些 prompt”。

## 阶段 6：接入主 runtime

任务细纲：

1. 把新的 Prompt Assembly 真正接入 runtime 主调用链。
2. 移除旧主路径的 prompt 拼接权。
3. 保留必要 diagnostics，不保留双轨主系统。

功能要求：

- Prompt Library 成为任务 prompt 的唯一主装配器。

## 阶段 7：清理旧残留

任务细纲：

1. 清理不再有意义的 projection 任务 prompt 逻辑。
2. 清理无用旧字段和旧测试。
3. 清理 selector/assembler 中仅服务旧理解链路的残留判断。

功能要求：

- 不以兼容为理由保留无意义旧壳。

## 12. 这次重规划后的关键设计结论

这里把结论定死，后面实现不再反复摇摆。

### 12.1 `task_goal_understanding` 和 `domain_flow_matching` 的区别

`task_goal_understanding`：

- 回答“用户这轮到底想做什么”；
- 主体是主模型判断；
- Prompt Library 只在这个阶段提供理解规则。

`domain_flow_matching`：

- 回答“既然已经知道要做什么，那应该匹配哪类任务流程/专业职责/阶段模板”；
- 主体是任务系统绑定；
- Prompt Library 只在这个阶段提供匹配规则。

所以这两个阶段必须并存，但不能混成一层。

### 12.2 Prompt Library 以后要围绕“任务流程”装配

你之前提的要求是对的：

动态装配必须考虑任务流程。

现在理解系统已经重构完，Prompt Library 就不该再只围绕“任务类型”装配，而必须围绕：

- 当前轮模型判断
- 当前任务合同
- 当前 step
- 当前验证状态

进行装配。

### 12.3 Soul 系统与任务 prompt 彻底分工

今后分工固定为：

- `role_mode`：灵魂/角色提示词系统负责。
- `standard_mode / professional_mode`：Prompt Library 负责。

这两个系统不能再互相抢主导权。

## 13. 下一步最合理的推进方式

理解系统已经完成，所以现在最合理的实施顺序不是先接 runtime，而是：

1. 先改 Prompt Library 的输入结构；
2. 再改 selector 的流程感知逻辑；
3. 再改 assembler/runtime sections 去 projection 化；
4. 最后再做 runtime cutover 和旧残留清理。

也就是说，下一轮真正该开工的不是“大而全重构”，而是：

**先把 Prompt Library 重新绑定到新的理解链路上。**

## 14. 最终目标状态

完成后，系统应满足：

1. 主模型先理解，Prompt Library 后装配。
2. Prompt Library 只消费结构化输入，不再反向猜目标。
3. 动态装配对 step 流程敏感。
4. 标准/专业模式不再带 projection 主层。
5. role mode 仍保留灵魂角色能力。
6. 模型可见 prompt 全部是自然职责语言。
7. 每次 prompt 装配都可追踪、可解释、可校验。

这才是理解系统重构完成之后，Prompt Library 应该进入的位置。
