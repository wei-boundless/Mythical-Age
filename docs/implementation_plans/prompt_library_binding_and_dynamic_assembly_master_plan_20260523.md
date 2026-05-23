# Prompt Library 与动态装配系统统筹重构计划书

日期：2026-05-23

状态：实施前统筹版

## 1. 核心结论

本轮要解决的不是“再补几段提示词”，而是把 agent 的提示词系统从散落字段、旧投影、硬编码专业 profile、任务图 workflow prompt 中收束成一个可维护、可追踪、可按任务流程动态装配的 Prompt Library。

目标链路必须固定为：

```text
理解系统
  -> 判断用户真正要完成什么
  -> 输出 TaskGoalFrame / GoalHypothesisSet

任务系统
  -> 绑定任务目标、流程、阶段、执行义务和验证要求
  -> 输出 SemanticTaskContract / ExecutionRecipe / 当前 step

Prompt Library
  -> 只根据结构化上下文选择、装配 prompt
  -> 输出 PromptAssemblyPlan / PromptManifest

Runtime
  -> 消费 PromptAssembly
  -> 执行、沉淀证据、验证、最终收口
```

Prompt Library 不负责重新理解用户意图，不负责工具授权，不负责替 runtime 执行任务。它只做两件事：

1. 管理稳定、可版本化、可绑定的 prompt 资源。
2. 根据理解系统和任务系统给出的结构化上下文，确定当前模型应该看到哪些职责、规则、技能边界、验证边界和输出边界。

## 2. 当前代码事实

### 2.1 已经完成的基础

当前项目已经有 Prompt Library 雏形：

- `backend/prompt_library/models.py`
  - 已有 `PromptResource`、`PromptSelectionContext`、`PromptAssemblyPlanItem`、`PromptAssemblyPlan`。
  - `PromptSelectionContext` 已包含 workflow、graph、node、stage、current step、recipe steps、skill ids、goal frame、agent plan、plan coverage 等流程字段。

- `backend/prompt_library/registry.py`
  - 已能读取 `storage/prompt_library/prompt_resources.json`。
  - 已能把 `storage/tasks/task_workflows.json` 中的 workflow prompt 同步为 `stage_role` 资源。

- `backend/prompt_library/selector.py`
  - 已有流程感知选择器。
  - 已支持 `workflow_id > task_id > graph/node/stage > step_id/step_kind > domain/mode` 的优先级。
  - 已禁止 `role_prompt` 在非 `role_mode` 中进入 selected。

- `backend/prompt_library/assembler.py`
  - 已在 runtime prompt contract 中接入 `PromptSelector`。
  - 已把 `prompt_selection_context` 和 `prompt_assembly_plan` 写入 metadata。

- `backend/agent_system/assembly/runtime_bundle_builder.py`
  - 已把 `prompt_flow_trace` 写入 orchestration diagnostics 和 stage plan。

- `backend/task_system/planning/understanding_step_compiler.py`
  - 已将单 agent 执行表达为 step 序列：
    `turn_intake -> context_resolution -> task_goal_understanding -> domain_flow_matching -> contract_compilation -> prompt_assembly -> execution_planning -> plan_coverage_review -> step_execution -> verification -> finalization`。

- `backend/intent/task_goal_interpreter.py`
  - 已有 `GoalHypothesisSet` 和 `TaskGoalFrame` 生成逻辑。
  - 已能把游戏垂直切片、前端交付等复杂目标和单文件交付区分开。

- `backend/runtime/professional_runtime/agent_plan.py` 与 `backend/runtime/professional_runtime/plan_coverage.py`
  - 已有 agent plan 和计划覆盖审查的结构。

### 2.2 仍然混乱的地方

1. Prompt Library 现在主要是“资源 + selector”，还不是完整主系统。
   - 缺少 default resources。
   - 缺少 binding registry。
   - 缺少 assembler / renderer / manifest validator 的完整协议。

2. `TaskGoalFrame` 仍携带 `stage_prompt_profiles`。
   - 这会把“理解结果”和“模型可见提示词文本”缠在一起。
   - 目标系统中，理解层只能输出目标、交付物、约束、不可接受结果和阶段需求引用，不能携带 prompt 正文。

3. `professional_profiles.py` 和 `strategy_prototypes.py` 仍是硬编码 prompt 源。
   - 后续应迁移成 `domain_role`、`verification`、`output_boundary` 等 prompt resources。
   - `strategy_prototypes` 应只保留策略引用或 profile binding，不再直接拥有 prompt 主文本。

4. `projection_section` 仍在 runtime sections 中作为模型可见概念存在。
   - 新架构中，Soul 只在 `role_mode` 下提供 `role_prompt`。
   - 标准模式和专业模式不应装配 Soul / projection / persona。
   - 任务图旧 projection prompt 可以迁移或适配为 `stage_role`，但不能继续作为新概念存在。

5. 资源类型命名需要修正。
   - `stage_role` 是阶段角色职责。
   - 旧概念 `task_understanding` 不适合作为长期资源类型名，应改为 `understanding_policy`。
   - `domain_flow_matching` 阶段使用的是流程/任务域匹配规则，应使用 `flow_matching_policy` 或 `domain_binding_policy`。

## 3. 目标架构

### 3.1 三层 Prompt Library

```text
Static Resources
  稳定 prompt 资源
  common_contract / mode_policy / domain_role / stage_role / skill_prompt / verification / output_boundary

Binding Resources
  将任务目标、模式、技能、流程阶段绑定到 prompt resources
  prompt_bindings / stage_prompt_bindings

Runtime Assembly
  消费 PromptSelectionContext
  解析 bindings
  选择 resources
  渲染动态 section
  生成 PromptAssemblyPlan + PromptManifest
```

### 3.2 所有权边界

| 层级 | 拥有什么 | 不允许做什么 |
|---|---|---|
| Understanding | 用户真实目标、候选目标、拒绝理由、核心交付、不可接受结果 | 直接生成模型可见 prompt 正文 |
| Task System | 任务流程、step 序列、执行义务、验证义务、当前节点和当前阶段 | 装配灵魂角色或选择表达人格 |
| Prompt Library | prompt 资源、绑定规则、装配顺序、manifest、显隐与缓存边界 | 重新猜任务目标、授权工具、执行任务 |
| Runtime | 消费 prompt、调用工具、记录 evidence、验证完成度 | 临时绕过 Prompt Library 拼主 prompt |
| Soul | `role_mode` 的角色提示词来源 | 进入 standard/professional 任务主 prompt |

### 3.3 固定执行流

```text
User Turn
  -> GoalHypothesisSet
  -> TaskGoalFrame
  -> TaskGoalProfileBinding
  -> SemanticTaskContract
  -> ExecutionObligation
  -> ExecutionRecipe / 当前 step
  -> PromptSelectionContext
  -> PromptBindingRegistry
  -> PromptSelector
  -> PromptAssembler
  -> PromptManifest
  -> RuntimeContext
  -> Model Call
```

关键规则：

1. `task_goal_understanding` 是第一层任务理解阶段。
2. `domain_flow_matching` 是任务目标到流程/目标 profile 的绑定阶段，不是模型角色阶段。
3. `prompt_assembly` 必须发生在合同与流程明确之后。
4. 单 agent 也要图化为 step 序列，但不一定前端可视化。
5. Prompt Library 的动态装配必须感知当前 step、step kind、workflow、task graph node 和专业执行计划。

## 4. 资源类型定义

### 4.1 保留和新增的资源类型

| resource_type | 用途 | 模型可见 | 备注 |
|---|---|---|---|
| `common_contract` | 所有任务通用底线，如诚实、证据、不伪造、不暴露内部协议 | 是 | 静态资源 |
| `mode_policy` | role/standard/professional 三模式的表达与执行边界 | 是 | 不写内部配置字段 |
| `understanding_policy` | 任务理解阶段的判断规则和候选目标原则 | 是，仅理解阶段 | 替代旧 `task_understanding` 命名 |
| `flow_matching_policy` | 根据目标 frame 绑定任务流程、目标 profile、阶段模板的规则 | 是，仅流程匹配阶段 | 对应 `domain_flow_matching` step |
| `domain_role` | 某任务目标或领域下的专业职责 | 是 | 如前端交付负责人、游戏垂直切片负责人 |
| `stage_role` | 当前 step / 节点的阶段职责 | 是 | 如世界观审核员、验证员、规划员 |
| `skill_prompt` | skill 的高质量使用要求 | 是 | 如生图 prompt 审美要求 |
| `tool_guidance` | 工具如何使用、结果如何进入 evidence | 是 | 不等于工具授权 |
| `verification` | 验证职责、证据要求、伪完成拦截 | 是 | 专业模式和验证阶段必须重视 |
| `output_boundary` | 最终回答、产物、限制说明 | 是 | 所有任务都需要 |
| `role_prompt` | Soul 角色提示词 | 是，仅 role_mode | standard/professional 禁用 |

### 4.2 明确区分：`stage_role` 与 `understanding_policy`

`stage_role` 回答的是：

```text
当前阶段你是谁？
你只负责什么？
你不负责什么？
你必须交付什么？
什么情况下阻断或返修？
```

示例：

```text
你是一名世界观审核员。
你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。
你不负责替创作者扩写设定。
你需要指出问题、给出裁决、说明是否允许进入下一阶段。
```

`understanding_policy` 回答的是：

```text
如何理解用户目标？
如何区分核心交付和辅助产物？
什么候选目标应该被拒绝？
什么时候需要澄清？
路径、文件名、旧 route 只能作为弱信号还是强信号？
```

示例：

```text
你负责判断用户真正想完成的任务目标。
你需要先区分核心产物和辅助产物：如果用户要求开发可运行产品，报告路径只能视为辅助交付，不能覆盖产品开发目标。
你只能在已注册目标类型中选择，不能发明新的任务类型。
```

`flow_matching_policy` 回答的是：

```text
已理解出的目标应该匹配哪个任务 profile？
应进入哪类流程？
当前阶段和后续阶段需要哪些资源与验证？
```

它不应被命名为 `task_understanding`，否则会把“理解用户目标”和“匹配系统流程”混成一层。

## 5. 数据模型设计

### 5.1 PromptResource 增量要求

现有 `PromptResource` 可以继续使用，但需要补强以下约束：

1. `resource_type` 必须来自固定枚举。
2. `cache_scope` 必须来自固定枚举：`static / semi_static / turn / runtime`。
3. `model_visible=True` 的资源必须是 agent-facing 职责语言。
4. `source_ref` 必须有来源，支持内置库、用户配置、skill、workflow、legacy projection。
5. `metadata` 中可以记录内部 id，但不能直接渲染给模型。
6. `legacy_projection_ids` 只能作为迁移追踪字段，不能作为新系统绑定主键。

### 5.2 新增 PromptBinding

建议新增文件：

- `backend/prompt_library/binding_models.py`
- `backend/prompt_library/binding_registry.py`
- `storage/prompt_library/prompt_bindings.json`

建议结构：

```python
@dataclass(frozen=True, slots=True)
class PromptBinding:
    binding_id: str
    title: str
    resource_ids: tuple[str, ...]
    applies_to_task_goal_types: tuple[str, ...] = ()
    applies_to_domains: tuple[str, ...] = ()
    applies_to_modes: tuple[str, ...] = ()
    applies_to_agents: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()
    priority: int = 100
    enabled: bool = True
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.prompt_binding"
```

功能要求：

1. `PromptBinding` 解决“某类任务通常需要哪些资源”。
2. 例如 `frontend_app_delivery + professional_mode` 绑定：
   - `common_contract`
   - `domain_role.frontend_app_delivery`
   - `verification.frontend_browser_workflow`
   - `output_boundary.professional_delivery`
3. binding 只绑定资源 id，不直接包含 prompt 正文。
4. binding 可以被用户配置覆盖，但必须进入 manifest diagnostics。

### 5.3 新增 StagePromptBinding

建议新增文件：

- `storage/prompt_library/stage_prompt_bindings.json`

建议结构：

```python
@dataclass(frozen=True, slots=True)
class StagePromptBinding:
    binding_id: str
    title: str
    resource_ids: tuple[str, ...]
    workflow_id: str = ""
    graph_id: str = ""
    node_id: str = ""
    stage_id: str = ""
    step_id: str = ""
    step_kind: str = ""
    task_goal_type: str = ""
    interaction_mode: str = ""
    priority: int = 100
    enabled: bool = True
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_library.stage_prompt_binding"
```

功能要求：

1. `StagePromptBinding` 解决“当前阶段应该装配哪些阶段职责和阶段策略”。
2. 精确 workflow/node/stage 绑定优先级高于 generic step_kind 绑定。
3. `task_graph_node_execution` 的 workflow prompt 迁移资源必须通过这里或 selector 精确命中，不被通用专业 prompt 覆盖。
4. `task_goal_understanding` step 应绑定 `stage_role + understanding_policy`。
5. `domain_flow_matching` step 应绑定 `stage_role + flow_matching_policy`。
6. `verification` step 应绑定 `stage_role + verification`。

## 6. 装配协议

### 6.1 PromptSelector 目标状态

当前 `PromptSelector` 已能直接按 resource 打分。目标状态应变为：

```text
PromptSelectionContext
  -> resolve PromptBinding / StagePromptBinding
  -> merge bound resource ids + exact context resources
  -> score resources
  -> produce PromptAssemblyPlan
```

选择优先级：

1. 任务图精确资源：
   `workflow_id > task_id > graph_id/node_id > node_id/stage_id > step_id`
2. 当前阶段资源：
   `current_step_id > current_step_kind`
3. 显式 binding resources：
   `stage_prompt_bindings > prompt_bindings`
4. 任务目标和模式：
   `task_goal_type + interaction_mode`
5. 任务领域：
   `task_domain / task_family`
6. 通用资源：
   `common_contract / output_boundary`

禁止：

1. `role_prompt` 在 `standard_mode` 或 `professional_mode` 被 selected。
2. generic `domain_role` 覆盖 workflow/node/stage 精确 `stage_role`。
3. selector 从用户原文关键词重新裁决任务目标。
4. selector 直接拼接模型可见文本。

### 6.2 PromptAssembler 目标状态

当前 `assembler.py` 还承担大量手写 section 渲染。目标状态应拆成：

```text
PromptSelector
  只选资源和排序

PromptAssembler
  只按 plan 渲染 section

PromptRenderers
  只渲染白名单动态字段

PromptValidator
  校验 section 显隐、模式、内部字段泄露、关键 section 缺失

PromptManifest
  记录来源、hash、cache、显隐、omitted reason、validation
```

新增建议文件：

- `backend/prompt_library/manifest.py`
- `backend/prompt_library/renderers.py`
- `backend/prompt_library/validator.py`
- `backend/prompt_library/hash_utils.py`

### 6.3 固定装配顺序

```text
Static Base
  common_contract
  mode_policy
  domain_role
  skill_prompt
  tool_guidance
  verification
  output_boundary

Mode Overlay
  role_mode: role_prompt
  standard_mode: no role_prompt
  professional_mode: no role_prompt

Turn Dynamic
  task_goal_frame_summary
  semantic_task_contract_summary
  execution_obligation_summary
  current_stage_role
  agent_plan_summary
  plan_coverage_summary

Runtime Dynamic
  visible_tool_boundary
  evidence_summary
  validation_state
  blocking_state
```

### 6.4 动态 renderer 白名单

| renderer_id | 输入 | 输出 | 要求 |
|---|---|---|---|
| `task_goal_frame_summary` | `TaskGoalFrame` | 本轮目标、核心交付、不可接受结果 | 不输出 raw user message |
| `goal_hypothesis_summary` | `GoalHypothesisSet` | chosen/rejected/ambiguity | 不输出无关候选噪音 |
| `semantic_contract_summary` | `SemanticTaskContract` | 任务类型、领域、交付物、禁止项 | 不输出内部 contract id |
| `execution_obligation_summary` | `ExecutionObligation` | 必须读/写/运行/验证 | 不输出 operation id |
| `workflow_step_summary` | `ExecutionRecipe` | 当前流程和当前 step | 不输出 workflow id |
| `agent_plan_summary` | `AgentPlanDraft` | 计划步骤和证据期望 | 只输出前 12 步摘要 |
| `plan_coverage_summary` | `PlanCoverageReview` | 是否通过、缺失项 | 未通过必须阻断 |
| `tool_boundary_summary` | `ResourcePolicy` | 当前可见工具和边界 | 不显示未授权工具 |
| `evidence_summary` | Evidence | 真实观察摘要 | 不把模型自述当证据 |
| `validation_state_summary` | Validator/Judgment | 完成度和缺失项 | 不允许模型自称通过 |

## 7. 阶段实施计划

## 阶段 0：术语和基线锁定

目标：

- 固定命名和边界，防止后续实现继续把角色职责、理解策略、流程匹配策略混在一起。

任务细纲：

1. 更新计划和代码注释中的资源类型命名：
   - `task_understanding` 概念改为 `understanding_policy`。
   - `domain_flow_matching` 对应资源改为 `flow_matching_policy`。
2. 在文档中明确：
   - `stage_role` 是阶段角色职责。
   - `understanding_policy` 是任务理解规则。
   - `flow_matching_policy` 是目标到流程/profile 的绑定规则。
3. 扫描现有 prompt 资源和 tests，记录还在依赖旧命名的地方。
4. 不在本阶段改运行行为。

涉及文件：

- `docs/implementation_plans/*.md`
- `backend/prompt_library/models.py`
- `backend/prompt_library/selector.py`
- `backend/task_system/planning/understanding_step_compiler.py`
- `backend/tests/prompt_library_selector_regression.py`

功能要求：

- 团队后续不会再把 `task_understanding` 当成泛化资源类型继续扩张。
- 现有测试仍可通过。

完成标准：

- 计划文档和注释明确三类概念区别。
- 旧命名依赖点列入后续迁移清单。

## 阶段 1：建立默认静态资源库

目标：

- 让 Prompt Library 不再只依赖 task workflow prompt 和手写 runtime section，拥有首批可复用默认资源。

任务细纲：

1. 新增 `backend/prompt_library/default_resources.py`。
2. 内置首批资源：
   - `common_contract.default`
   - `mode_policy.role_mode`
   - `mode_policy.standard_mode`
   - `mode_policy.professional_mode`
   - `understanding_policy.goal_first`
   - `flow_matching_policy.profile_binding`
   - `domain_role.code_fix_execution`
   - `domain_role.frontend_app_delivery`
   - `domain_role.game_vertical_slice_delivery`
   - `domain_role.test_report_triage`
   - `stage_role.execution_planning`
   - `stage_role.verification`
   - `stage_role.finalization`
   - `verification.evidence_required`
   - `output_boundary.default`
   - `output_boundary.professional_delivery`
3. `PromptLibraryRegistry.list_resources()` 合并默认资源和 storage 资源。
4. storage 中同 id 用户资源可覆盖默认资源，但必须记录 `source_ref` 和 `version`。
5. 默认资源正文必须是 agent-facing 职责语言，不出现 runtime 节点说明。

涉及文件：

- 新增 `backend/prompt_library/default_resources.py`
- 修改 `backend/prompt_library/registry.py`
- 修改 `backend/prompt_library/__init__.py`
- 修改 `backend/tests/prompt_library_registry_regression.py`

功能要求：

- 没有用户配置时，专业任务也能装配基础职责、验证和输出边界。
- 写作任务图节点仍优先使用 workflow 同步来的 `stage_role`。

代码要求：

- 默认资源使用 `PromptResource` dataclass，不写散 dict。
- 每个资源必须有 `resource_id/resource_type/title/content/cache_scope/model_visible/source_ref/version`。
- 默认资源不能写入 storage，除非用户显式保存覆盖版。

完成标准：

- registry 返回默认资源 + storage 资源。
- 同 id storage 资源覆盖 default resource。
- `role_prompt` 不在默认标准/专业资源中出现。

## 阶段 2：建立 PromptBinding 和 StagePromptBinding

目标：

- 让资源选择从“所有资源打分”升级为“绑定解析 + 精确资源优先 + 通用资源补充”。

任务细纲：

1. 新增 binding 模型：
   - `PromptBinding`
   - `StagePromptBinding`
2. 新增 registry：
   - `PromptBindingRegistry`
   - `StagePromptBindingRegistry`
3. 新增 storage：
   - `storage/prompt_library/prompt_bindings.json`
   - `storage/prompt_library/stage_prompt_bindings.json`
4. 建立默认 bindings：
   - `professional_mode + game_vertical_slice_delivery`
   - `professional_mode + frontend_app_delivery`
   - `professional_mode + code_fix_execution`
   - `professional_mode + test_report_triage`
   - `task_goal_understanding step_kind`
   - `domain_flow_matching step_kind`
   - `execution_planning step_kind`
   - `verification step_kind`
   - `finalization step_kind`
5. binding 只保存 resource ids，不保存 prompt 正文。
6. binding 解析结果写入 `PromptAssemblyPlan.diagnostics`。

涉及文件：

- 新增 `backend/prompt_library/binding_models.py`
- 新增 `backend/prompt_library/binding_registry.py`
- 新增 `backend/tests/prompt_library_binding_registry_regression.py`
- 修改 `backend/prompt_library/selector.py`

功能要求：

- `task_goal_understanding` 阶段装配 `stage_role + understanding_policy`。
- `domain_flow_matching` 阶段装配 `stage_role + flow_matching_policy`。
- `verification` 阶段装配 `stage_role + verification`。
- 专业游戏任务装配游戏 domain role、验证和输出边界。
- 精确任务图节点 prompt 仍然高于 generic binding prompt。

代码要求：

- binding registry 必须容忍 storage 文件不存在。
- 禁止 binding 引用不存在资源时静默成功；应在 diagnostics 中记录 missing resource。
- 缺少关键 binding 不应导致直接崩溃，除非处于 cutover 后的 validator 阶段。

完成标准：

- 新增测试覆盖 task goal type binding、mode binding、step kind binding、missing resource diagnostics。

## 阶段 3：改造 PromptSelector 为绑定感知

目标：

- Selector 统一处理绑定资源、精确资源、通用资源，并输出可解释选择计划。

任务细纲：

1. `PromptSelector.__init__()` 支持传入 resources 和可选 bindings。
2. `select()` 流程改为：
   - resolve prompt bindings。
   - resolve stage prompt bindings。
   - collect bound resource ids。
   - score all eligible resources。
   - bound resources 加权。
   - exact workflow/node/stage 资源最高优先。
3. winner key 规则细化：
   - `stage_role` 可以按 stage 维度有多个，但同一阶段同一职责只能一个 winner。
   - `domain_role` 通常一个 winner。
   - `verification` 可按 validator profile 多个 winner。
   - `common_contract` 可以多个静态 winner。
   - `skill_prompt/tool_guidance` 按 skill/tool id 多个 winner。
4. selected item metadata 增加：
   - `binding_ids`
   - `binding_match_reason`
   - `identity_score`
   - `compatibility_score`
5. omitted item 保留明确原因。

涉及文件：

- 修改 `backend/prompt_library/selector.py`
- 修改 `backend/prompt_library/models.py`
- 修改 `backend/tests/prompt_library_selector_regression.py`

功能要求：

- generic prompt 不能覆盖 workflow/node/stage prompt。
- role prompt 仍只能 role mode selected。
- 当前 step kind 没有精确资源时，能命中 generic stage binding。
- skill prompt 按 active skill 或 runtime skill view 装配。

代码要求：

- selector 不直接读取 storage。
- selector 不调用模型。
- selector 不渲染 prompt 正文。
- selector 不从 user_goal 关键词猜任务类型。

完成标准：

- selector tests 覆盖 exact > binding > generic 的优先级。
- selector diagnostics 能解释为什么选中和为什么 omitted。

## 阶段 4：拆出 PromptAssembler / Renderer / Manifest / Validator

目标：

- 结束 runtime 大函数手写拼接主 prompt 的状态，让装配变成可校验协议。

任务细纲：

1. 新增 `PromptManifest` 模型。
2. 新增 `PromptAssembly` 模型。
3. 新增 `PromptAssembler`：
   - 输入 `PromptAssemblyPlan`
   - 输入 structured runtime payload
   - 输出 `PromptAssembly + PromptManifest`
4. 新增 renderers：
   - `task_goal_frame_summary`
   - `semantic_contract_summary`
   - `execution_obligation_summary`
   - `workflow_step_summary`
   - `agent_plan_summary`
   - `plan_coverage_summary`
   - `tool_boundary_summary`
   - `evidence_summary`
   - `validation_state_summary`
5. 新增 validator：
   - section id 唯一。
   - section order 固定。
   - `standard/professional` 不允许 `role_prompt`。
   - 模型可见正文不得包含禁止字段模式：`workflow_id`、`operation_id`、`manifest_id`、`projection_id`、裸 resource id。
   - professional mode 缺少语义合同、domain/stage role、verification、output boundary 时 fail closed。
6. manifest 记录：
   - selected / omitted resources。
   - section hash。
   - cache scope。
   - model visible。
   - renderer id。
   - validation result。

涉及文件：

- 新增 `backend/prompt_library/manifest.py`
- 新增 `backend/prompt_library/renderers.py`
- 新增 `backend/prompt_library/validator.py`
- 新增 `backend/prompt_library/hash_utils.py`
- 修改 `backend/prompt_library/assembler.py`
- 修改 `backend/prompt_library/runtime_sections.py`
- 新增 `backend/tests/prompt_library_assembly_regression.py`

功能要求：

- 模型可见 prompt 全部是职责语言、任务目标、边界、验证和输出要求。
- 内部 id 只进入 manifest，不进入模型正文。
- validation fail closed 可被 runtime 识别。

代码要求：

- renderer 只消费白名单字段。
- 每个 renderer 有最大字符数。
- 截断必须进入 manifest diagnostics。
- assembler 不重新选择资源。

完成标准：

- 组装出的 prompt assembly 可直接替代当前 runtime prompt contract sections。
- tests 覆盖内部字段泄露、role prompt 越权、缺关键 section。

## 阶段 5：迁移硬编码 prompt 源

目标：

- 把专业 prompt、策略 prompt、skill prompt、旧 workflow prompt 逐步迁移到 Prompt Library 主资源体系。

任务细纲：

1. `professional_profiles.py`
   - 迁移为 `domain_role` 或 `stage_role` 默认资源。
   - 原模块短期保留只读 adapter。
2. `strategy_prototypes.py`
   - 去掉 prompt 主文本职责。
   - 只保留 strategy id、default reasoning steps、validator refs、prompt resource refs。
3. `TaskGoalFrame.stage_prompt_profiles`
   - 从 frame 中移除 prompt 正文字段。
   - 改为 `recommended_stage_prompt_refs` 或完全由 `StagePromptBinding` 解析。
4. `backend/capability_system/units/skills/*/SKILL.md`
   - skill 中模型可见的能力边界迁移为 `skill_prompt` / `tool_guidance` resource。
   - 尤其是生图 skill：要求 agent 精准描述画面、主体、构图、光影、材质、风格边界，具备高审美。
5. `storage/tasks/task_workflows.json`
   - workflow prompt 继续同步为 `stage_role`。
   - 同步后的资源进入 prompt library，不再依赖 metadata.role_prompt 作为主路径。
6. 旧 projection prompt：
   - 若是工作职责，迁移为 `stage_role/domain_role`。
   - 若是角色表达，保留为 Soul 的 `role_prompt`，仅 role_mode 可用。

涉及文件：

- `backend/prompting/professional_profiles.py`
- `backend/prompting/strategy_prototypes.py`
- `backend/intent/task_goal_frame.py`
- `backend/intent/task_goal_interpreter.py`
- `backend/capability_system/units/skills/*/SKILL.md`
- `backend/soul/projections/catalog.json`
- `backend/soul/work_prompts/catalog.json`
- `storage/tasks/task_workflows.json`
- `storage/prompt_library/prompt_resources.json`

功能要求：

- 专业模式不再依赖 hardcoded profile prompt 主路径。
- skill prompt 可被 selector 和 binding 显式装配。
- 任务图节点 prompt 不丢失。

代码要求：

- 迁移脚本必须可重复运行。
- 不为兼容长期保留第二套主 prompt 体系。
- 每个迁移资源必须有 `source_ref` 和 `legacy_*` 追踪字段。

完成标准：

- 写作任务图节点、游戏开发、前端交付、生图 skill 都能从 Prompt Library 找到主 prompt resource。

## 阶段 6：Runtime cutover

目标：

- Runtime 默认消费 Prompt Library 输出，不再由 `runtime_bundle_builder.py` 手写拼主 prompt。

任务细纲：

1. `assemble_runtime_prompt_contract()` 改为：
   - 构建 `PromptSelectionContext`。
   - 调用 binding-aware selector。
   - 调用 PromptAssembler。
   - 返回兼容旧 contract shape 的同时，metadata 中给出新 `prompt_assembly` 和 `prompt_manifest`。
2. `runtime_sections.py` 改为消费新 assembly sections。
3. `SoulFacade.build_runtime_view()`：
   - role mode 可消费 role prompt。
   - standard/professional 只包装任务 prompt assembly，不再添加 projection prompt。
4. `runtime_bundle_builder.py`：
   - `projection_requirement` 降级为迁移 diagnostics。
   - `prompt_flow_trace` 来自 new manifest。
5. `context_manager.py`：
   - 不再把 `_model_visible_projection_sections` 当主 prompt 来源。
   - 只消费 `PromptAssembly.sections`。
6. 保留短期 shadow/fallback 开关：
   - shadow 对比旧 prompt 和新 prompt。
   - cutover 默认走新系统。
   - fallback 只用于严重阻断，不能长期存在。

涉及文件：

- `backend/prompt_library/assembler.py`
- `backend/prompt_library/runtime_sections.py`
- `backend/agent_system/assembly/runtime_bundle_builder.py`
- `backend/soul/runtime_assembly.py`
- `backend/soul/facade.py`
- `backend/runtime/shared/context_manager.py`
- `backend/task_system/contracts/runtime_contracts.py`

功能要求：

- runtime 主 prompt 来源是 Prompt Library。
- 任务图节点 prompt 不被当前聊天误判覆盖。
- role mode 仍保留 Soul 角色体验。
- professional mode 不装配 Soul role prompt。

代码要求：

- cutover 后禁止在 runtime driver 里临时追加模型可见主 prompt。
- 旧 contract 字段仅作为 adapter 输出，不作为主 source。
- manifest 必须能定位每段 prompt 来源。

完成标准：

- 现有 prompt library、professional mode、writing graph、skill runtime 回归测试通过。
- 新增 cutover 测试证明 standard/professional 没有 projection section 主路径。

## 阶段 7：Soul 和旧投影收口

目标：

- Soul 只保留角色模式角色提示词，投影系统不再作为新 prompt 主概念。

任务细纲：

1. Soul 资源分流：
   - 角色身份、世界、故事 -> role mode role prompt。
   - 工作职责 -> Prompt Library domain/stage resources。
2. 删除或降级旧 projection runtime 主路径。
3. `/api/soul/*` 保持角色资源管理能力。
4. 任务图旧 projection prompt 迁移完成前，adapter 仍能读取旧配置，但输出必须是 `stage_role/domain_role` resource。
5. 迁移完成后删除无用旧代码和旧测试。

涉及文件：

- `backend/soul/runtime_assembly.py`
- `backend/soul/prompt_assembly.py`
- `backend/soul/catalog_service.py`
- `backend/soul/facade.py`
- `backend/soul/contracts.py`
- `backend/tests/soul_projection_interaction_mode_regression.py`
- `backend/tests/soul_projection_resource_boundary_regression.py`

功能要求：

- 用户选择灵魂时，只有 role_mode 被注入角色提示词。
- standard/professional 不受灵魂人格污染。
- 任务图旧配置不崩。

代码要求：

- 不把 projection 改名后继续作为主系统保留。
- 旧 projection 只允许作为 migration source。
- 清理无用旧测试，改写为 Prompt Library/Soul role mode 边界测试。

完成标准：

- 新 trace 和 manifest 不再把 projection 当主 prompt layer。
- role_mode 仍有角色提示词。
- standard/professional 没有 role prompt。

## 阶段 8：前端配置页与监控接入

目标：

- 让用户能像查数据库一样管理 Prompt Library，而不是看卡片堆。

任务细纲：

1. 新增 API：
   - `GET /api/prompt-library/resources`
   - `GET /api/prompt-library/bindings`
   - `GET /api/prompt-library/stage-bindings`
   - `PUT /api/prompt-library/resources/{resource_id}`
   - `PUT /api/prompt-library/bindings/{binding_id}`
   - `POST /api/prompt-library/preview`
2. 配置页布局：
   - 上方筛选区。
   - 中间数据库表格。
   - 右侧或底部详情编辑器。
   - preview 面板展示某个任务/模式/阶段会装配哪些 sections。
3. 表格字段：
   - resource id。
   - type。
   - title。
   - modes。
   - task goal types。
   - domains。
   - stage/step。
   - cache scope。
   - model visible。
   - source ref。
   - version。
   - enabled。
4. 运行监控页展示：
   - prompt manifest。
   - selected/omitted resources。
   - binding match reason。
   - validation result。
   - model-visible preview。

涉及文件：

- `backend/api/prompt_library.py`
- 前端配置页相关文件，以当前前端路由为准。
- runtime monitor 相关前端文件。

功能要求：

- 配置页实用、可搜索、可筛选、可编辑、可预览。
- 不使用大卡片环绕式布局。
- 不把开发式说明当副标题。
- 用户能看到“为什么这个 agent 装配了这些 prompt”。

代码要求：

- API 返回 manifest/diagnostics 给前端，但模型可见正文和系统字段分开。
- 编辑保存需要版本号或 updated_at。
- preview 不触发真实任务执行。

完成标准：

- 输入任务 goal、mode、step，即可预览 prompt assembly。
- 配置页能维护 prompt resources 和 bindings。

## 阶段 9：旧残留清理

目标：

- 完成 cutover 后删除无用旧代码，不以兼容为理由长期保留旧壳。

任务细纲：

1. 删除或降级旧 runtime prompt assembler。
2. 删除 `professional_profiles.py` 中作为主路径的 hardcoded prompt。
3. 删除 `strategy_prototypes.py` 中 prompt 主文本职责。
4. 删除 `TaskGoalFrame.stage_prompt_profiles`。
5. 删除 standard/professional 中 projection section 主路径。
6. 删除或重写依赖旧 projection 主路径的测试。
7. 清理 storage 中无用 projection prompt 字段。

功能要求：

- 系统只有一个 prompt 主装配协议。
- Soul 不是任务 prompt 系统。
- Prompt Library 是任务 prompt 唯一主来源。

代码要求：

- 清理前必须有迁移测试覆盖。
- 删除旧测试时必须用新架构测试替代，不能降低覆盖。
- 不允许留下“新旧都能跑但没人知道用哪个”的双轨主系统。

完成标准：

- 全量目标测试通过。
- 代码里没有新的任务 prompt 从 projection 主路径进入模型。

## 8. 验证矩阵

### 8.1 必测场景

| 场景 | 预期 |
|---|---|
| role_mode 普通聊天 | 可装配 `role_prompt`，不装配专业长任务职责 |
| standard_mode 普通工具任务 | 不装配 Soul/projection，装配任务目标、工具边界和输出边界 |
| professional code fix | 装配 code fix domain role、verification、output boundary |
| professional frontend delivery | 装配 frontend domain role、浏览器验证相关 verification |
| professional game vertical slice | 装配 game domain role、资源接入和浏览器验证要求 |
| task_goal_understanding step | 装配 stage role + understanding policy |
| domain_flow_matching step | 装配 stage role + flow matching policy |
| writing graph world_design node | 精确装配 world_design workflow stage role |
| writing graph world_review node | 精确装配审核员 stage role，不扩写设定 |
| image prompt skill | 装配高审美 skill_prompt，不启动无关同步状态 |

### 8.2 关键断言

1. professional/standard 模式没有 selected `role_prompt`。
2. 精确 workflow/node/stage prompt 高于 generic domain prompt。
3. `task_understanding` 旧资源类型不再新增。
4. `TaskGoalFrame` 不再携带 prompt 正文。
5. Prompt manifest 中能看到 binding reason、selected、omitted。
6. 模型可见正文不出现内部 id 和 projection 概念。
7. 缺少专业模式关键 section 时 fail closed。
8. 生图 skill prompt 能被主 agent 装配为能力提示，而不是写死在聊天 prompt 中。

## 9. 迁移与切换规则

### 9.1 Shadow

- 新 Prompt Library 生成 assembly 和 manifest。
- 旧 runtime prompt 仍可作为实际 prompt。
- 对比差异，记录遗漏资源、越权资源、内部字段泄露。

### 9.2 Cutover

- Runtime 默认使用 Prompt Library assembly。
- 旧字段只作为兼容 adapter。
- 遇到严重阻断可临时退回 shadow，但不能长期双轨。

### 9.3 Cleanup

- 删除旧主路径。
- 删除无用旧测试。
- 清理旧 projection 主概念。
- 保留 Soul role mode 资源管理。

### 9.4 回滚

如果 cutover 发现任务图关键节点 prompt 丢失：

1. 回滚到 shadow mode。
2. 保留新 manifest diagnostics。
3. 修复 binding/selector/adapter。
4. 再次 cutover。

不允许用“重新启用 projection 主系统”作为长期回滚方案。

## 10. 禁止事项

1. 禁止在旧壳上继续堆新壳。
2. 禁止让 Prompt Library 重新猜用户目标。
3. 禁止 `stage_role` 和 `understanding_policy` 混用。
4. 禁止 `domain_flow_matching` 使用 `task_understanding` 类型资源。
5. 禁止 standard/professional 装配 Soul role prompt。
6. 禁止把 workflow id、operation id、manifest id、projection id 写进模型可见 prompt。
7. 禁止工具授权写在 prompt resource 中。
8. 禁止最终报告替代真实产物或验证。
9. 禁止为了测试伪造产物、图片、命令输出或浏览器观察。
10. 禁止在任务图 prompt 全量迁移前删除旧配置读取能力。
11. 禁止迁移完成后继续保留无用旧残留。

## 11. 推荐实施顺序

按当前代码状态，最稳妥顺序是：

1. 阶段 0：术语和基线锁定。
2. 阶段 1：默认静态资源库。
3. 阶段 2：PromptBinding / StagePromptBinding。
4. 阶段 3：Binding-aware PromptSelector。
5. 阶段 4：PromptAssembler / Renderer / Manifest / Validator。
6. 阶段 5：迁移 hardcoded prompt 源。
7. 阶段 6：Runtime cutover。
8. 阶段 7：Soul 和旧投影收口。
9. 阶段 8：前端配置页和监控接入。
10. 阶段 9：旧残留清理。

这套顺序的关键是：先把资源和绑定建好，再切 runtime；先迁移任务图 prompt，再清投影；先有 manifest 和 validator，再删除旧主路径。

## 12. 最终成功状态

完成后系统应满足：

```text
TaskGoalFrame 是目标理解结果，不携带 prompt 正文。
ExecutionRecipe / current step 是流程事实来源。
Prompt Library 是任务 prompt 唯一主来源。
PromptBinding 负责任务/模式/技能到资源的绑定。
StagePromptBinding 负责 step/workflow/node 到阶段资源的绑定。
PromptSelector 只选择资源，不渲染文本。
PromptAssembler 只按 plan 和 renderer 装配，不重新选择。
PromptManifest 记录所有来源、显隐、cache、hash、omitted reason 和 validation。
Soul 只在 role_mode 下作为 role_prompt 来源。
旧 projection 只作为迁移 source，不再作为新 prompt 主概念。
Agent-facing prompt 全部是自然专业职责语言。
```

这份计划的核心不是让 prompt 变多，而是让 prompt 有所有权、有来源、有阶段、有验证、有可解释装配路径。这样主 agent 才能在长任务里知道自己当前该做什么、为什么做、做到什么才算完成。
