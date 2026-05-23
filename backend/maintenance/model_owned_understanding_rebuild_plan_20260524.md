# Model-Owned Understanding Rebuild Plan - 2026-05-24

本计划只依据当前代码和本轮原则，不继承旧计划、不保留旧理解层兼容壳。

## 1. 结论

当前理解系统不合格。

它不是成熟 agent 的“接收请求 -> 主模型判断 -> 行动门禁 -> 执行验证”链路，而是：

```text
用户消息
-> 关键词/弱信号代码提前判断 primary_intent、route_hint、write_requested
-> profile/goal 代码提前判断 task_goal_type
-> contract/shape 代码提前判断 task contract、execution shape、recipe、operation
-> 主模型在被预选 recipe/prompt/tools 框住后执行
-> 证据和完成判断收尾
```

这会让主模型的判断发生得太晚。系统看起来有很多“理解结构”，但真正的目标、行动、工作方式已经被代码层抢先决定。

必须重建为：

```text
UserRequest
-> RequestFacts
-> BoundaryPolicy
-> ContextCandidates
-> ModelTurnDecision
-> ActionPermit
-> RuntimeStartPacket
-> ExecutionLoop
-> EvidenceCloseout
-> FinalResponse
```

核心原则：主模型拥有“用户想要什么、下一步该做什么、是否复杂、是否该计划、是否该读/改/测”的判断权；代码只拥有事实收集、硬边界、候选上下文、权限门禁、资源注册、证据验证。

## 2. 当前代码事实

### 2.1 RequestSignals 已经不是弱信号

证据：

- `backend/request_intent/request_signals.py:52` 定义 `RequestSignals`。
- `backend/request_intent/request_signals.py:55` 暴露 `primary_intent`。
- `backend/request_intent/request_signals.py:201` 到 `213` 生成 `route_hint`。
- `backend/request_intent/request_signals.py:249` `_primary_intent()` 用关键词直接返回 `correct/review/execute/plan/continue/answer`。

判定：

这不是 facts。`primary_intent`、`route_hint`、`write_requested`、`complexity_hint` 都是预裁决。它们会让后续链路相信“用户要执行/要搜索/要工作区材料/要继续”，而不是让主模型先判断。

### 2.2 runtime_chain 在主模型前生成目标和任务包

证据：

- `backend/agent_system/assembly/runtime_chain.py:83` 调 `build_request_signals()`。
- `backend/agent_system/assembly/runtime_chain.py:136` 调 `build_task_goal_spec()`。
- `backend/agent_system/assembly/runtime_chain.py:160` 调 `build_task_execution_assembly_bundle()`。
- `backend/runtime/unit_runtime/loop.py:2258` 才进入 `execution_engine.stream_model_turn()`。

判定：

模型开始行动前，目标、上下文、task bundle、recipe、operation 已经形成。主模型不是入口判断者，只是被装配后的执行者。

### 2.3 TaskGoalSpec 是 profile 分类器，不是用户目标真相

证据：

- `backend/intent/task_goal_interpreter.py:150` `_select_goal_candidate()` 选择 goal。
- `backend/intent/task_goal_interpreter.py:269` profile 匹配继续读取 `route_hint()`。
- `backend/intent/task_goal_interpreter.py:434` `_semantic_type_from_cognition()` 用 route/material/write signals 推断 `artifact_delivery/bounded_tool_task/light_qa`。
- `backend/task_system/goal_profiles/task_goal_profiles.py:177`、`:202` 把 `game_vertical_slice_delivery/frontend_app_delivery` 作为 goal profile。

判定：

这里把“任务模板/专业流程”伪装成“用户目标理解”。游戏、前端、测试分析这些可以作为任务模板或 skill-like workflow，但不能在主模型判断前反推用户真实意图。

### 2.4 TaskRequirementContract 二次识别任务

证据：

- `backend/task_system/contracts/task_requirement_contracts.py:63` 构建 `TaskRequirementContract`。
- `backend/task_system/contracts/task_requirement_contracts.py:223` `_resolve_task_goal_type()` 再次推断 task goal。
- `backend/task_system/contracts/task_requirement_contracts.py:246` 继续使用 `route_hint()`。

判定：

这是第二套目标判断。它可能覆盖或强化前面的错误判断。合同层应该编译模型已判定的任务，不应该重新理解用户。

### 2.5 ExecutionShapeResolver 提前选择 recipe

证据：

- `backend/task_system/planning/execution_shape_resolver.py:38` `resolve_execution_shape()`。
- `backend/task_system/planning/execution_shape_resolver.py:54` 读取 `route_hint()`。
- `backend/task_system/services/assembly_builder.py:97` `selected_recipe = build_execution_recipe(...)`。
- `backend/task_system/services/assembly_builder.py:221` 根据 recipe/definition/binding 生成 `operation_requirement`。

判定：

recipe、工具权限、operation 是执行策略，不是理解层。当前代码让 heuristic route 影响 recipe，再让 recipe 影响工具可见性和 prompt，这会放大早期误判。

### 2.6 model_goal sidecar 位置不对

证据：

- `backend/runtime/unit_runtime/loop.py:1312` 调 `invoke_model_goal_draft()`。
- `backend/runtime/unit_runtime/loop.py:1323` 把 draft 塞进 `runtime_context_override["model_goal_draft"]`。
- `backend/intent/task_goal_interpreter.py:572` 以后只把 draft 当作覆盖候选。

判定：

这不是主模型入口判断层，而是一个旁路补丁。它仍被旧 profile/contract/shape 包围，不能从根上解决 ownership。

### 2.7 Completion 仍允许 partial 完成

证据：

- `backend/runtime/professional_runtime/completion_judgment.py:262` `completion_allowed=status in {"verified", "partially_verified"}`。
- `backend/tests/completion_judgment_regression.py:115` 保护 partial allowed。

判定：

这违反“证据收尾”。`partially_verified` 可以作为最终回答中的限制说明，但不能作为完成许可。

## 3. 正确层级设计

### 3.1 RequestFacts

职责：

- 保存用户原话、turn/session/workspace、附件、显式选择。
- 提取明确路径、材料后缀、原文约束片段。
- 收集 action words 作为 raw markers。

禁止：

- 不产 `primary_intent`。
- 不产 `route_hint`。
- 不产 `write_requested` 这类行动结论。
- 不选 task、recipe、tool、agent。

目标文件：

- 新建 `backend/agent_runtime/understanding/request_facts.py`。
- 删除或改写 `backend/request_intent/request_signals.py`。

### 3.2 BoundaryPolicy

职责：

- 合并 system/developer/project/user 最新禁令。
- 表达写入、shell、网络、浏览器、审批、安全路径等硬边界。
- 明确“必须先计划”“禁止修改”“不能跳过测试”等规则。

禁止：

- 不理解用户目标。
- 不选择工作模式。

目标文件：

- 新建 `backend/agent_runtime/understanding/boundary_policy.py`。
- 消费现有权限系统，但不把权限逻辑塞进 intent。

### 3.3 ContextCandidates

职责：

- 收集 continuation、memory、active task、selected files、prior plan 候选。
- 标记候选来源、置信度、可能目标。

禁止：

- 不因为“继续”就决定执行。
- 不覆盖最新用户请求。

目标文件：

- 新建 `backend/agent_runtime/understanding/context_candidates.py`。
- 改写 `backend/continuation/*` 的输出语义：只产候选，不产当前轮业务决策。

### 3.4 ModelTurnDecision

职责：

这是理解系统唯一的目标和行动判断结果，由主模型产出。

结构：

```text
ModelTurnDecision
- interaction_intent: answer | explain | inspect | review | plan | modify | create | run | verify | continue | stop | restore
- action_intent: answer_only | read_context | search_external | edit_workspace | run_command | start_service | use_browser | delegate | ask_clarification | block
- target_objects
- desired_outcome
- deliverables
- constraints
- context_binding_decision
- work_mode: conversation | read_only_analysis | implementation | verification | planning | delegated | background
- planning_required
- todo_required
- completion_criteria
- confidence
- ambiguity
```

禁止：

- 不选具体 executor。
- 不直接越过 BoundaryPolicy。
- 不伪造证据。

目标文件：

- 新建 `backend/agent_runtime/understanding/model_turn_decision.py`。
- 新建 `backend/agent_runtime/understanding/model_turn_decision_invoker.py`。
- 删除 `backend/intent/model_goal_*`，因为它只是旧链路旁路补丁。

### 3.5 ActionPermit

职责：

- 用 `BoundaryPolicy + ModelTurnDecision + tool/resource policy` 判断行动是否允许。
- 决定哪些工具可见、哪些操作可执行、哪些需要审批。

禁止：

- 不改变用户目标。
- 不把 forbidden action 通过 recipe 加回来。

目标文件：

- 新建 `backend/agent_runtime/understanding/action_permit.py`。
- 接入现有 `backend/permissions/` 和 operation gate。

### 3.6 RuntimeStartPacket

职责：

把执行循环需要的东西一次性交清楚：

```text
RuntimeStartPacket
- user_request
- request_facts
- boundary_policy
- context_candidates
- model_turn_decision
- action_permit
- resource_binding
- execution_plan
- completion_criteria
- prompt_handoff
```

禁止：

- 不再让 runtime loop 重新理解 intent。
- 不再让 assembly builder 重新选择目标。

目标文件：

- 新建 `backend/agent_runtime/understanding/runtime_start_packet.py`。
- 用它替代 `runtime_chain.py` 当前返回的散装 `task_operation/current_turn_context/task_execution_assembly` 入口语义。

## 4. 必删或重写清单

### 必删

- `backend/intent/model_goal_arbitration.py`
- `backend/intent/model_goal_invoker.py`
- `backend/intent/model_goal_request.py`
- `backend/intent/goal_hypothesis.py`
- `backend/intent/task_goal_interpreter.py`
- `backend/intent/task_goal_spec.py`

理由：这些把模型入口判断、profile 分类、目标合同混在一起。保留会继续产生双权威。

### 必改名/降级

- `backend/request_intent/request_signals.py`

改为 `RequestFacts`。删除 `primary_intent/route_hint/write_requested/complexity_hint/target_domain_hints` 的权威语义。

- `backend/request_intent/frame_access.py`

删除 `primary_intent()`、`route_hint()`、`flow_hint()` 等访问器，避免下游继续偷用旧判断。

### 必重写

- `backend/agent_system/assembly/runtime_chain.py`

重写为：

```text
build_runtime()
-> build_request_facts()
-> build_boundary_policy()
-> collect_context_candidates()
-> invoke_model_turn_decision()
-> build_action_permit()
-> build_runtime_start_packet()
```

- `backend/task_system/contracts/task_requirement_contracts.py`

只从 `ModelTurnDecision + CompletionCriteria` 编译合同，不再 `_resolve_task_goal_type()`。

- `backend/task_system/planning/execution_shape_resolver.py`

删除 route heuristic。改为从 `work_mode/action_intent/resource_binding` 映射执行形态。

- `backend/task_system/services/assembly_builder.py`

删除 `_ensure_task_goal_spec()`，不再自行生成 goal。只消费 `RuntimeStartPacket`。

- `backend/task_system/services/assembly_support.py`

删除 `build_runtime_task_intent_contract()` 中的 `primary_intent/route_hint` 依赖。合同来自 `ModelTurnDecision`。

- `backend/runtime/unit_runtime/loop.py`

移除 `model_goal_sidecar`，在 runtime chain 前不再做旁路 goal draft。执行循环只消费 start packet。

- `backend/runtime/professional_runtime/completion_judgment.py`

改为：

```text
completion_allowed = status == "verified"
```

### 应保留但降权

- `backend/task_system/goal_profiles/*`

不再作为理解分类器。可迁移为 `task_templates` 或 `skills/workflows`，只在 `ModelTurnDecision` 已判定需要模板后作为候选资源。

- `backend/prompt_library/*`

保留 prompt 组装能力，但输入必须来自 `PromptHandoff`。prompt 内容必须是 agent 角色职责语言，不写 runtime 节点说明。

- `backend/runtime/execution_engine/*`

保留工具调用循环和协议守卫。它属于执行循环，不属于理解层。

## 5. 实施顺序

### Phase 1: 建新入口模型

新增：

```text
backend/agent_runtime/understanding/
  __init__.py
  user_request.py
  request_facts.py
  boundary_policy.py
  context_candidates.py
  model_turn_decision.py
  model_turn_decision_invoker.py
  action_permit.py
  runtime_start_packet.py
  pipeline.py
```

完成标准：

- 新模型没有 `Frame` 命名。
- `RequestFacts` 不包含任何 route/intent/action 决策字段。
- `ModelTurnDecision` 是唯一 intent/action/work_mode/completion criteria 来源。

### Phase 2: 主链切到模型判断

改：

- `backend/agent_system/assembly/runtime_chain.py`
- `backend/runtime/unit_runtime/loop.py`

完成标准：

- `stream_model_turn()` 前必须已经有 `ModelTurnDecision`。
- `agent_runtime_chain.build_runtime()` 不再调用 `build_task_goal_spec()`。
- 删除 model_goal sidecar。

### Phase 3: 删旧理解权威

删：

- `backend/intent/task_goal_interpreter.py`
- `backend/intent/task_goal_spec.py`
- `backend/intent/goal_hypothesis.py`
- `backend/intent/model_goal_*`

改：

- `backend/intent/__init__.py`
- 所有 import 旧 goal/spec/model_goal 的文件。

完成标准：

```text
rg "build_task_goal_spec|TaskGoalSpec|GoalHypothesis|model_goal|primary_intent|route_hint" backend
```

结果中不能有 active request path 依赖。允许只在迁移说明或已删除测试中不存在。

### Phase 4: 重写 contract/shape/recipe 所有权

改：

- `backend/task_system/contracts/task_requirement_contracts.py`
- `backend/task_system/planning/execution_shape_resolver.py`
- `backend/task_system/services/assembly_builder.py`
- `backend/task_system/services/assembly_support.py`

完成标准：

- contract 不再识别 task_goal_type。
- shape 不再消费 route/material keyword。
- recipe 只由 `ModelTurnDecision.work_mode/action_intent/resource_binding` 映射。
- operation requirement 只由 `ActionPermit` 和 resource policy 生成。

### Phase 5: 模板降权

改：

- `backend/task_system/goal_profiles/*`

目标：

- 改名为 `task_templates` 或移入 workflow/template registry。
- 删除 match markers 作为入口判断依据。
- 游戏/前端/测试类只作为“模型已决定采用模板后的候选流程”。

完成标准：

- 没有任何代码通过 `match_markers` 从用户原话直接选择 goal。

### Phase 6: 完成标准收紧

改：

- `backend/runtime/professional_runtime/completion_judgment.py`
- `backend/tests/completion_judgment_regression.py`

完成标准：

- `partially_verified` 不允许 completion。
- 最终回答可以报告 partial，但 runtime 不能把 partial 作为完成。

### Phase 7: 重写测试

新增测试：

```text
backend/tests/understanding_model_owned_pipeline_regression.py
backend/tests/request_facts_no_decision_regression.py
backend/tests/model_turn_decision_regression.py
backend/tests/action_permit_boundary_regression.py
backend/tests/runtime_start_packet_regression.py
```

覆盖场景：

1. “只分析，不要改”不能进入 edit/write。
2. “继续”必须先绑定 continuation candidate，再由模型决定继续什么。
3. “重构并测试”必须识别 planning_required 和 implementation work mode。
4. “PDF + Excel + 天气”必须允许 mixed resources，但不能由 route_hint 硬选单一路径。
5. “审查代码，不要留情”是 review/inspect，不是 artifact delivery。
6. `partially_verified` 不能完成。

## 6. 切换规则

- 不做旧接口兼容。
- 不新增 shim 模块。
- 不保留保护旧 route/goal/profile 分类的测试。
- 不允许旧 `route_hint/primary_intent` 在 active path 中继续存在。
- 不允许 contract/recipe 再次理解用户目标。
- 不允许模板覆盖用户禁令。

## 7. 验证命令

执行阶段完成后至少运行：

```powershell
python -m compileall backend
python -m pytest backend/tests/request_facts_no_decision_regression.py -q
python -m pytest backend/tests/model_turn_decision_regression.py -q
python -m pytest backend/tests/action_permit_boundary_regression.py -q
python -m pytest backend/tests/runtime_start_packet_regression.py -q
python -m pytest backend/tests/completion_judgment_regression.py -q
```

再跑全量收口：

```powershell
python -m pytest backend/tests -q
```

## 8. 最终验收定义

重构完成后，用户请求进入系统时必须满足：

1. 代码先收集事实，不判断意图。
2. 代码先建立不可越过的边界。
3. 上下文只产候选，不替用户决定。
4. 主模型产出唯一的当前轮判断。
5. 权限门禁只允许/拒绝行动，不改写目标。
6. task/template/recipe 只能在模型判断之后绑定。
7. 执行循环不重新理解 intent。
8. 证据不足不能完成。

达不到这 8 条，就不是成熟 agent 理解系统。
