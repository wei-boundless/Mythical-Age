# 角色 / 任务 / Prompt 系统总重构计划书

日期：2026-05-23

状态：总计划，实施前锁定版

关联计划：

- `docs/implementation_plans/task_understanding_goal_first_refactor_plan_20260523.md`
- `docs/implementation_plans/prompt_library_system_refactor_plan_20260523.md`
- `docs/implementation_plans/task_graph_node_prompt_assembly_repair_plan_20260523.md`
- `docs/系统规划/206-角色标准专业三模式与专业长任务母版架构升级计划-20260521.md`
- `docs/设计原则/04-System-Prompt-工程.md`
- `docs/设计原则/07-Prompt-Cache.md`

## 1. 总结论

本轮不是继续给灵魂系统补几个工作 prompt，也不是在 runtime 末端修某个误判。当前系统的问题是 prompt 所有权、任务理解顺序、运行模式、灵魂角色提示和专业 Agent 执行边界混在一起。

总方向：

```text
任务理解先判断用户真正要完成什么。
任务域系统决定流程、资源、验证和阶段。
Prompt Library 负责所有可复用 prompt 资源和动态装配。
投影系统取消；Soul 只在 role_mode 下作为角色提示词来源。
standard_mode / professional_mode 只装配任务 prompt。
Professional Agent 先做成稳定长任务执行母版。
role_mode / standard_mode / professional_mode 只是同一运行底座的三种策略档。
```

最终系统应形成一个统一链路：

```text
User Turn
  -> TaskGoalFrame
  -> TaskDomainBinding
  -> SemanticTaskContract + ExecutionObligation
  -> RuntimeInteractionModePolicy
  -> ExecutionRecipe + TaskRunLedger
  -> PromptSelectionContext
  -> PromptLibraryRegistry
  -> PromptSelector
  -> PromptAssembler
  -> PromptAssembly + PromptManifest
  -> RuntimeContextManager
  -> Model Messages
  -> Evidence / Validation / Finalization
```

核心取舍：

1. `Soul` 不再作为整个 prompt 系统的主入口。
2. `现实世界` 不再按故事世界理解，而是改造为现实工作库 / 公共实用 prompt 库。
3. `role_mode` 和 `task_mode` 必须硬分离。角色模式可以有灵魂角色提示词，标准和专业任务不能装配灵魂、投影或角色表达资源。
4. 不同阶段必须有不同 prompt。任务理解、规划、执行、验证、收口不能共用同一段泛化提示词。
5. 任务图节点 prompt 必须来自注册任务、节点 workflow 和节点输出契约，不能被当前聊天文本误判。
6. Agent-facing prompt 必须写成专业职责语言，不能写成 runtime 节点说明。
7. 新架构不再建设投影系统；但现有任务图里的 projection prompt 是真实生产配置，必须先作为 legacy prompt source 适配和迁移，未完成迁移与回归前绝不能删除。

## 2. 当前系统诊断

### 2.1 Prompt 来源分散

现有 prompt 来源散落在这些位置：

- `backend/prompting/builder.py`
- `backend/prompting/manifest.py`
- `backend/prompting/professional_profiles.py`
- `backend/prompting/strategy_prototypes.py`
- `backend/soul/contracts.py`
- `backend/soul/runtime_assembly.py`
- `backend/soul/prompt_assembly.py`
- `backend/soul/catalog_service.py`
- `backend/agent_system/assembly/runtime_bundle_builder.py`
- `backend/runtime/shared/context_manager.py`
- `backend/runtime/professional_runtime/driver.py`

当前 `runtime_bundle_builder.py` 会手工拼接：

- `task_section`
- `workflow_section`
- `node_professional_prompt_section`
- `semantic_task_section`
- `professional_profile_section`
- `mode_policy_section`
- `output_section`
- `guardrail_section`

问题是这些 section 同时包含模型可见职责语言、系统字段、workflow id、旧 projection id、task mode、debug 字段和运行策略说明。模型真正需要的是职责、目标、边界、交付物和验证标准；系统字段应该进 manifest 和 diagnostics。

### 2.2 Soul 系统职责过载

`backend/soul/contracts.py` 已经有很好的资源雏形：

- `SoulProfile`
- `SoulWorld`
- `SoulStory`
- `SoulCard`
- `WorkPrompt`
- `CommonContractPrompt`
- `PromptSection`
- `SoulRuntimeView`
- `SoulPromptManifest`

但它目前同时承担：

- 身份体验。
- 角色提示词。
- 工作 prompt。
- 共同契约。
- prompt manifest。
- runtime section 装配。
- 前端资源管理。

这些职责混在一起后，专业 Agent 的任务职责会被身份资源污染，角色体验也会被工作流程挤压。Soul 只应在 `role_mode` 下生成角色提示词，不再进入标准任务和专业任务，也不再决定任务流程、工具、验证和专业交付。

### 2.3 任务理解顺序错误

现有失败链路已经在肉鸽游戏实验中暴露：

```text
用户说“开发浏览器端 2D 肉鸽游戏垂直切片”
  -> 路径 / 写入 / 修复关键词抢先裁决
  -> 被归类为 workspace_file_write / code_fix_execution
  -> 专业运行时只写 final_report.md
  -> 没有游戏源码、资源、启动和浏览器验证
```

正确顺序应是：

```text
用户原文
  -> 大模型 / 结构化理解用户真正目标
  -> 系统用已注册任务域校验并绑定流程
  -> 编译 semantic contract 和 execution obligation
  -> 选择运行模式、资源、阶段和 prompt
```

关键词、路径、历史上下文只能作为 evidence，不能作为最终任务类型裁决。

### 2.4 两套 PromptManifest 并存

当前至少有两套 manifest：

- `backend/prompting/manifest.py::PromptManifest`
- `backend/soul/contracts.py::SoulPromptManifest`

它们字段、生命周期和 owner 不统一。后续必须收敛到一个主 `PromptManifest`，记录：

- section id。
- resource id。
- resource type。
- owner layer。
- cache scope。
- model visible。
- source refs。
- order。
- prompt hash。
- diagnostics。

Soul manifest 只允许作为迁移 adapter，不应长期作为第二套主协议。

### 2.5 Agent-facing prompt 泄露开发语言

禁止继续出现这种模型可见语言：

```text
这是 runtime 节点。
根据任务图执行 world_review。
这个节点用于校验资产。
Workflow ID: ...
Task mode: ...
Projection ID: ...
```

必须改成职责语言：

```text
你是一名世界观审核员。
你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。
你不负责替创作者扩写设定。
你需要指出问题、给出裁决、说明是否允许进入下一阶段。
```

内部字段仍要保留，但只能进入 `PromptManifest`、trace、diagnostics、前端开发者展开区或运行监控详情。旧 projection 字段在迁移期可以作为 `legacy_projection_prompt_source` 被读取，渲染后必须进入 `stage_role` 或 `domain_role` 这类任务 prompt，不得继续作为新投影概念暴露给模型。

## 3. 目标架构

### 3.1 分层架构

```text
Turn Intake Layer
  用户消息、当前时间、会话状态、显式约束

Task Understanding Layer
  TaskGoalFrame
  用户真正目标、核心交付物、辅助交付物、成功标准、所需能力

Domain Binding Layer
  TaskDomainProfile / TaskDomainBinding
  任务域、默认流程、资源需求、验证需求、专业 profile

Contract Layer
  SemanticTaskContract
  ExecutionObligation
  RuntimeInteractionModePolicy

Execution Shape Layer
  ExecutionRecipe
  TaskRunLedger
  单 Agent 线性图 / 任务图节点共享 step 协议

Prompt Library Layer
  PromptResource
  PromptSelectionContext
  PromptSelector
  PromptAssembler
  PromptAssembly + PromptManifest

Runtime Context Layer
  RuntimeContextManager
  model messages

Execution / Evidence / Validation Layer
  Professional Runtime
  EvidencePacket
  DeliverableValidator
  OutputBoundary
```

### 3.2 所有权边界

| 层 | 拥有什么 | 不允许做什么 |
|---|---|---|
| TaskGoalFrame | 用户真实目标、交付物、成功标准 | 直接授权工具、直接生成 prompt |
| TaskDomainProfile | 任务域默认流程、能力、验证、profile 绑定 | 覆盖用户显式禁止项 |
| SemanticTaskContract | 本轮任务合同、交付物、材料策略 | 重新猜测用户人格或灵魂 |
| ExecutionObligation | 必做动作、必验事项、证据要求 | 从关键词单独裁决复杂任务 |
| RuntimeInteractionModePolicy | 三模式策略、工具预算、验证强度 | 写模型可见开发字段 |
| PromptLibrary | prompt 资源选择和装配 | 决定工具授权 |
| Soul | role_mode 的角色提示词 | 参与 standard_mode / professional_mode，决定任务流程、验证和交付标准 |
| RuntimeContextManager | 最终上下文拼接 | 重新理解任务类型 |
| Validator | 证据对齐、伪完成拦截 | 用最终回答关键词替代真实证据 |

### 3.3 单 Agent 图化

单 Agent 不一定需要前端可视化，但必须在后端明确 step 时序。复用现有：

- `ExecutionRecipe.step_blueprints`
- `TaskRunLedger.step_runs`
- `TaskStepBlueprint`
- `TaskStepRun`
- `ProfessionalRunState`

标准 step：

```text
turn_intake
  -> context_resolution
  -> task_goal_understanding
  -> domain_flow_matching
  -> contract_compilation
  -> prompt_assembly
  -> execution_planning
  -> step_execution
  -> verification
  -> finalization
```

要求：

1. `task_goal_understanding` 输出 `TaskGoalFrame`。
2. `domain_flow_matching` 输出 `TaskDomainBinding`。
3. `contract_compilation` 输出 `SemanticTaskContract + ExecutionObligation + RuntimeInteractionModePolicy`。
4. `prompt_assembly` 输出 `PromptAssembly + PromptManifest`。
5. `verification` 只能消费真实 observation / evidence，不能消费模型自述。

## 4. 三模式边界

三模式不是三套 driver，不是三个人格。它们是同一专业运行底座的不同策略档。

### 4.1 role_mode

定位：

- 灵魂系统主场。
- 对话、陪伴、角色体验、轻问答、只读检索。
- 可以使用 Soul 生成一段角色提示词。

可消费 prompt：

- `common_contract`
- `role_prompt`
- `light_qa`
- 只读 `tool_guidance`
- 简化 `output_boundary`

禁止：

- 不得注入长任务专业 profile。
- 不得获得写入、终端、浏览器自动化等副作用能力。
- 不得用灵魂故事解释现实任务执行结果。
- 不得启用旧投影系统。

### 4.2 standard_mode

定位：

- 当前回合内解决明确任务。
- 有限工具、有限验证、明确收口。

可消费 prompt：

- `common_contract`
- `task_understanding`
- `domain_role`
- `skill_prompt`
- `tool_guidance`
- `verification`
- `output_boundary`

禁止：

- 不得长期持有复杂计划状态。
- 不得把当前回合工具任务升级成无边界长任务。
- 不得装配 Soul、role_prompt、identity、persona、style 或新 projection。
- 例外：`task_graph_node_runtime` 可通过 `LegacyProjectionPromptAdapter` 读取既有 projection prompt，并转换成 `stage_role/domain_role` 任务提示词。

### 4.3 professional_mode

定位：

- 专业长任务母版。
- 结构化任务理解、阶段计划、证据包、严格验证、失败修正、最终收口。

可消费 prompt：

- `common_contract`
- `task_understanding`
- `domain_role`
- `stage_role`
- `professional_profile`
- `skill_prompt`
- `tool_guidance`
- `verification`
- `output_boundary`

禁止：

- 不得把最终报告当作执行结果本身。
- 不得声称未运行、未验证、未生成的产物已完成。
- 不得装配 Soul、role_prompt、identity、persona、style 或新 projection。
- 例外：`task_graph_node_runtime` 可通过 `LegacyProjectionPromptAdapter` 读取既有 projection prompt，并转换成 `stage_role/domain_role` 任务提示词。
- 不得在 driver 末端用正则重新猜任务类型。

## 5. 现实工作库设计

### 5.1 命名和定位

原 “现实世界” 资源改造为：

```text
现实工作库 / Reality Work Library
```

它不是世界观设定，不是角色背景，而是公共实用 prompt 库。它提供现实任务场景下可复用的职责、流程、边界、验证和表达规范。

### 5.2 首批资源类型

| 类型 | 用途 |
|---|---|
| `common_contract` | 所有任务共用底线，如诚实、证据、不伪造、不泄露内部协议 |
| `task_understanding` | 让模型先理解用户真正任务 |
| `domain_role` | 任务域专业角色，如前端负责人、游戏切片负责人、测试报告诊断员 |
| `stage_role` | 长任务阶段角色，如规划员、实现者、验证员、收口者 |
| `skill_prompt` | skill 的使用边界和高质量要求，如生图审美 prompt |
| `tool_guidance` | 工具如何使用、何时使用、结果如何成为证据 |
| `verification` | 验证职责、证据要求、伪完成拦截 |
| `output_boundary` | 最终回答和产物表达边界 |
| `role_prompt` | 仅 role_mode 可用的 Soul 角色提示词 |

### 5.3 资源基本模型

建议新增：

```text
backend/prompt_library/models.py
```

核心模型：

```python
@dataclass(frozen=True, slots=True)
class PromptResource:
    resource_id: str
    resource_type: str
    title: str
    content: str
    tags: tuple[str, ...] = ()
    applies_to_task_goal_types: tuple[str, ...] = ()
    applies_to_domains: tuple[str, ...] = ()
    applies_to_modes: tuple[str, ...] = ()
    applies_to_agents: tuple[str, ...] = ()
    stage_id: str = ""
    priority: int = 100
    cache_scope: str = "static"
    model_visible: bool = True
    source_ref: str = ""
    version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)
```

实现要求：

1. 每个资源必须有稳定 `resource_id`。
2. 每个资源必须声明 `resource_type`。
3. 每个资源必须声明 `cache_scope`。
4. 每个资源必须声明是否 `model_visible`。
5. 每个模型可见资源内容必须是 Agent-facing 职责语言。
6. 任务 prompt 资源可以来自内置库、用户配置、任务域 registry 或 skill registry；Soul 只通过 role_mode 的 `role_prompt` adapter 暴露，不进入标准/专业任务装配。

## 6. Prompt Library 主系统

### 6.1 选择上下文

`PromptSelectionContext` 必须由上游结构化结果构建，不允许靠 prompt selector 自己读用户原文乱猜。

```python
@dataclass(frozen=True, slots=True)
class PromptSelectionContext:
    task_id: str
    session_id: str
    user_goal: str
    agent_id: str
    agent_profile_id: str
    interaction_mode: str
    runtime_lane: str
    task_goal_type: str
    task_domain: str
    stage_id: str
    task_goal_frame: dict[str, Any]
    domain_binding: dict[str, Any]
    semantic_task_contract: dict[str, Any]
    execution_obligation: dict[str, Any]
    mode_policy: dict[str, Any]
    active_skill: dict[str, Any]
    visible_tool_ids: tuple[str, ...]
```

### 6.2 选择顺序

PromptSelector 固定顺序：

1. `common_contract`
2. `role_prompt`，仅 role_mode 可选。
3. `task_understanding`，只进入理解阶段。
4. `domain_role`
5. `stage_role`
6. `professional_profile`
7. `skill_prompt`
8. `tool_guidance`
9. `verification`
10. `output_boundary`

禁止：

1. prompt resource 直接声明工具授权。
2. `role_prompt` 覆盖 semantic contract，或进入 standard/professional 任务。
3. selector 用纯关键词长期判断任务域。
4. 模型可见正文出现 workflow id、operation id、manifest id、projection id。

### 6.3 装配输出

```python
@dataclass(frozen=True, slots=True)
class PromptAssembly:
    assembly_id: str
    task_id: str
    sections: tuple[PromptSection, ...]
    manifest: PromptManifest
    diagnostics: dict[str, Any]
    authority: str = "prompt_library.prompt_assembly"
```

`PromptManifest` 必须包含：

- section order。
- resource ids。
- source refs。
- owner layer。
- cache scope。
- model visible。
- prompt hash。
- stage id。
- selection reason。
- omitted resources and reasons。
- diagnostics。

### 6.4 缓存策略

参考现有 prompt cache 设计原则，资源应分成：

- `static`：全局稳定共同准则、专业职责库。
- `semi_static`：用户配置、agent profile、role_mode 的 soul role prompt。
- `turn`：本轮任务目标、当前阶段职责。
- `runtime`：工具可见性、时间事实、运行状态、证据摘要。

要求：

1. 静态和动态 section 分离。
2. Prompt Library manifest 必须能展示 cache scope。
3. runtime 动态信息不能插在静态共同 prompt 前面破坏缓存前缀。
4. 后续如果接 API prompt cache，应能直接按 manifest 分块。

### 6.5 装配协议

Prompt 装配必须是确定性的协议，不允许由模型自由拼 prompt，也不允许在 runtime 大函数里临时拼字符串。

固定装配顺序：

```text
Static Base
  common_contract
  domain_role / professional_profile 静态定义
  skill_prompt 静态定义
  verification 静态定义
  output_boundary 静态定义

Mode Overlay
  role_mode: role_prompt
  standard_mode: no soul resource
  professional_mode: no soul resource

Turn Contract
  task_goal_frame summary
  domain_binding summary
  semantic_task_contract summary
  execution_obligation summary
  current stage_role

Runtime Facts
  visible tool boundary
  current time facts when required
  evidence summary
  validation state
```

`PromptSelector` 只能输出 `PromptAssemblyPlan`，不能直接渲染文本。`PromptAssembler` 只能按 plan 和固定 renderer 渲染 section，不能重新选择资源。

### 6.6 静态与动态边界

| 层级 | cache_scope | 来源 | 内容 | 生成时机 | 可变性 |
|---|---|---|---|---|---|
| Static Base | `static` | 内置现实工作库、任务域库、skill 库 | 通用准则、领域职责、验证职责、输出边界模板 | 进程启动或配置加载 | 只能随版本变化 |
| Semi Static | `semi_static` | 用户配置、agent profile、role_mode Soul | 角色提示词、用户自定义 prompt 资源 | 会话开始或配置变更 | 需要版本号和 hash |
| Turn Dynamic | `turn` | TaskGoalFrame、DomainBinding、SemanticTaskContract、ExecutionObligation | 本轮目标、交付物、禁止项、当前阶段职责 | 每个 turn / 每个 stage | 必须结构化生成 |
| Runtime Dynamic | `runtime` | ResourcePolicy、工具可见性、时间事实、Evidence、Validator | 工具边界、运行事实、证据摘要、验证状态 | 每次模型调用前 | 白名单字段生成 |

硬规则：

1. `static` section 不能引用 session、task、user message、tool state、当前时间。
2. `semi_static` section 必须有配置版本和 hash；配置变更后才允许变化。
3. `turn` section 只能来自结构化合同，不得直接拼接用户全文。
4. `runtime` section 只能来自白名单 runtime facts，不得把任意 diagnostics dump 给模型。
5. `runtime` section 永远排在 static / semi_static / turn section 之后。
6. standard/professional 模式的动态 section 不得包含 Soul role prompt。

### 6.7 动态内容控制

动态 section 必须通过专用 renderer 生成。每个 renderer 需要声明：

- `renderer_id`
- 输入 schema。
- 输出 section type。
- 最大字符数。
- 允许的字段白名单。
- 是否模型可见。
- 缺字段时的处理方式。

动态控制规则：

1. `task_goal_frame` renderer 只输出目标摘要、核心交付物、辅助交付物、成功标准、显式约束。
2. `semantic_task_contract` renderer 只输出任务类型、领域、材料角色、交付物、禁止项和验证义务。
3. `execution_obligation` renderer 只输出必须执行或必须验证的义务，不输出 operation id。
4. `tool_guidance` renderer 只输出当前模型可见工具的使用边界，不输出未授权工具。
5. `runtime_fact` renderer 只在任务需要时输出当前时间等事实。
6. `evidence` renderer 只输出已经形成的证据摘要和 refs，不输出原始大段工具结果。
7. `validation` renderer 只输出缺失项和阻断原因，不允许模型自我声明通过。

长度控制：

- 单个 `turn` section 默认不超过 1200 字符。
- 单个 `runtime` section 默认不超过 800 字符。
- evidence 摘要超过限制时写 refs 和结论，不塞原文。
- 超限必须进入 manifest diagnostics。

### 6.8 防错和 Fail Closed

Prompt 装配必须先验证，再进入模型调用。

装配前校验：

1. `interaction_mode` 必须存在且只能是 `role_mode / standard_mode / professional_mode`。
2. `standard_mode / professional_mode` 中不得选中 `role_prompt`。
3. `professional_mode` 必须有 `semantic_task_contract`、`domain_role` 或 `professional_profile`、`output_boundary`。
4. 当前 stage 如果需要执行或验证，必须有对应 `stage_role` 或 `verification` section。
5. 所有 model-visible section 必须有非空 content、source_ref、cache_scope、owner_layer。
6. section id 必须唯一。
7. section order 必须来自固定枚举，不允许运行时自由插队。

失败策略：

- 缺少非关键 role prompt：role_mode 可降级为无角色普通回答，并在 diagnostics 标记。
- 缺少 standard_mode 任务合同：降级为澄清问题，不执行副作用工具。
- 缺少 professional_mode 关键 section：fail closed，阻断模型执行，返回装配错误给 runtime。
- 出现 forbidden section，例如 professional_mode 装配 Soul role prompt：fail closed。
- 出现内部字段泄露风险：fail closed，除非当前是显式 debug 视图且 model_visible=false。

### 6.9 Manifest 与可观测性

每次装配必须生成完整 `PromptManifest`。Manifest 是调试和前端展示唯一来源，不能让模型看到内部字段。

Manifest 必须记录：

- `assembly_id`
- `selection_context_hash`
- `section_order`
- 每段 section 的 `resource_id / resource_type / renderer_id / source_ref / cache_scope / model_visible / chars / hash`
- `static_hash`
- `semi_static_hash`
- `turn_hash`
- `runtime_hash`
- omitted resources and reason
- validation status
- fail closed reason

运行监控页显示 manifest，不显示临时拼接字符串。用户看到的是职责和任务状态；开发者展开区才显示 resource ids、hash、diagnostics。

## 7. 专业 Agent 母版

### 7.1 首要建设目标

先把 `professional_mode` 做扎实，再用策略降档形成 `standard_mode` 和 `role_mode`。专业 Agent 的关键不是“更长的 prompt”，而是完整执行闭环：

```text
理解目标
  -> 绑定任务域
  -> 生成语义合同
  -> 规划阶段
  -> 装配阶段 prompt
  -> 执行真实操作
  -> 沉淀证据
  -> 验证交付
  -> 修正或收口
```

### 7.2 专业模式阶段 prompt

不同阶段必须使用不同职责 prompt：

| 阶段 | Prompt 目标 |
|---|---|
| `task_goal_understanding` | 理解用户真正要完成什么，区分核心 / 辅助交付 |
| `domain_flow_matching` | 将目标绑定到已注册任务域和流程 |
| `contract_compilation` | 明确交付物、资源、禁止项、验证义务 |
| `execution_planning` | 拆出可执行步骤，确认资源落点和验证路径 |
| `step_execution` | 按当前阶段真实执行，不提前写最终报告 |
| `verification` | 只根据 evidence 判断是否完成 |
| `finalization` | 面向用户收口，说明真实完成、限制和后续落点 |

### 7.3 首批专业任务域

必须内置：

- `code_fix_execution`
- `frontend_app_delivery`
- `interactive_product_delivery`
- `game_vertical_slice_delivery`
- `image_asset_generation`
- `browser_operation_task`
- `test_report_triage`
- `runtime_trace_analysis`
- `regression_test_design`
- `material_synthesis`
- `workflow_graph_coordination`
- `writing_graph_node_execution`

### 7.4 生图能力位置

生图不应只是“聊天里发一个 provider 请求”，也不应混成任务图同步状态。

目标：

- 注册为 capability / tool。
- 编写 `skill_prompt`。
- Prompt 要求 Agent 精准描述画面、主体、构图、材质、光线、风格、负面约束和用途。
- 生成结果进入 artifact / evidence，不直接被前端刷掉。

生图 prompt 资源示例方向：

```text
你是一名高审美图像提示词设计师。
你只负责把用户的视觉需求转化为清晰、具体、可执行的生图 prompt。
你需要描述主体、构图、镜头、材质、光线、色彩、风格、用途和需要避免的问题。
不要把抽象情绪当作唯一描述；不要输出含混的“大气、好看、精致”而没有可执行视觉细节。
```

## 8. 任务图节点 Prompt 修复并入总架构

任务图节点的职责来源必须按这个优先级：

```text
registered_task
  -> task_workflow
  -> node output contract
  -> legacy projection prompt adapter
  -> node stage role prompt
  -> task graph runtime context
```

不能按当前聊天文本、返修文本或上一个节点残留来裁决节点身份。

要求：

1. `task_graph_node_runtime` 固定为任务图节点执行语义。
2. 节点 workflow 的 `prompt` 进入 Prompt Library 的 `stage_role` 或 `domain_role`。
3. 现有任务图中写在 projection 配置里的 prompt 必须通过 `LegacyProjectionPromptAdapter` 映射为 `stage_role` 或 `domain_role`。
4. 当前节点显式身份覆盖旧上下文残留。
5. 世界观设计节点必须拿到世界观架构师 prompt。
6. 世界观审核节点必须拿到审核员 prompt。
7. 任务图节点 prompt manifest 必须记录 workflow resource id 和 legacy projection source id。
8. 所有任务图节点迁移前，不允许删除 projection 配置、`StageProjectionCycle` 读取路径或旧 prompt 字段。

## 9. 实施总阶段

### 阶段 0：盘点和基线

任务细纲：

1. 扫描所有 prompt 来源。
2. 列出每个 section 的 owner、source、model_visible、cache_scope、是否含内部字段。
3. 固化当前失败样本：
   - 肉鸽游戏长任务。
   - 写作图世界观节点。
   - 生图任务前端显示。
   - 专业代码修复。
   - 角色模式普通对话。
   - 标准模式工具任务。
4. 建立 prompt source report。

功能要求：

- 能展示当前 prompt 是从哪里来的。
- 能证明哪些字段不该给模型看。
- 能证明任务图节点和专业模式的 prompt 来源可追踪。

代码要求：

- 新增 `backend/tests/prompt_inventory_regression.py`。
- 新增 `backend/tests/fixtures/prompt_cases.py`。
- 不改变运行行为，只建立诊断基线。

完成标准：

- 当前系统的 prompt 泄露、误判和重复 manifest 问题被测试表达出来。

### 阶段 1：模式和边界模型

任务细纲：

1. 固化 `role_mode / standard_mode / professional_mode`。
2. 定义 `RuntimeInteractionModePolicy`。
3. 明确 Soul 只在 `role_mode` 输出 `role_prompt`。
4. 明确 `standard_mode / professional_mode` 的 prompt 装配只允许任务资源。
5. 将旧 `simple / managed / autonomy_mode` 标记迁移为 mode policy diagnostics。

功能要求：

- 每次运行只有一个 `interaction_mode`。
- 专业模式强制语义合同和验证策略。
- 角色模式不吃专业 prompt。
- 标准和专业模式不吃 Soul / role prompt / 新 projection。
- 任务图节点在迁移期允许读取旧 projection prompt，但必须由 adapter 转成任务 prompt。

代码要求：

- 新增或完善 `backend/orchestration/interaction_mode_policy.py`。
- 修改 `backend/agent_system/assembly/runtime_chain.py`。
- 修改 `backend/agent_system/assembly/runtime_bundle_builder.py`。
- 修改 `backend/task_system/services/assembly_support.py`。

完成标准：

- trace 中能看到唯一 interaction mode。
- 新任务不再出现正式 `simple / managed` 语义。

### 阶段 2：目标优先任务理解

任务细纲：

1. 新增 `TaskGoalFrame`。
2. 将旧 TaskUnderstanding 降级为 evidence。
3. 区分核心交付物和辅助交付物。
4. 接入模型目标理解，但必须 schema validate。
5. 对短任务保留快速 deterministic fallback。

功能要求：

- 肉鸽游戏识别为 `game_vertical_slice_delivery`。
- 前端 UI 重构识别为 `frontend_app_delivery`。
- 单纯写 Markdown 文件仍识别为 bounded artifact。
- 路径和“写”字不能抢先裁决复杂任务。

代码要求：

- 新增 `backend/intent/task_goal_frame.py`。
- 新增 `backend/intent/task_goal_interpreter.py`。
- 新增 `backend/intent/model_task_goal_interpreter.py`。
- 新增 `backend/intent/task_goal_schema.py`。
- 修改 `backend/intent/__init__.py`。
- 修改 `backend/context_system/current_turn/current_turn.py`。

完成标准：

- `TaskGoalFrame` 进入 current turn diagnostics。
- 专业任务链路优先消费 `TaskGoalFrame`。

### 阶段 3：任务域注册表

任务细纲：

1. 新增 `TaskDomainProfile`。
2. 新增 `TaskDomainBinding`。
3. 把现有 task goal type / professional profile / strategy prototype 迁入 domain registry。
4. 为产品开发、游戏、生图、浏览器操作、写作图节点建立任务域。

功能要求：

- 任务域定义默认流程、能力、交付物、验证和 prompt profile。
- 未匹配时返回 fallback binding，不悄悄走旧 route。
- 用户显式禁止项不能被 domain profile 覆盖。

代码要求：

- 新增 `backend/task_system/domains/__init__.py`。
- 新增 `backend/task_system/domains/task_domain_profiles.py`。
- 新增 `backend/task_system/domains/domain_registry.py`。
- 新增 `backend/task_system/domains/domain_matcher.py`。
- 新增 `backend/task_system/domains/domain_binding.py`。
- 修改 `backend/prompting/strategy_prototypes.py`。
- 修改 `backend/prompting/professional_profiles.py`。

完成标准：

- domain binding 结果可序列化进 current turn 和 ledger。
- 肉鸽、前端、生图、任务图节点都有稳定 domain。

### 阶段 4：语义合同和执行义务

任务细纲：

1. `SemanticTaskContract` 优先消费 `TaskGoalFrame + TaskDomainBinding`。
2. `ExecutionObligation` 从合同反推资源和验证。
3. 交付物必须带 role：
   - `core_output`
   - `supporting_output`
   - `input_material`
   - `verification_artifact`
4. 验证义务必须从任务域产生，而不是从“测试、运行”等关键词产生。

功能要求：

- final_report 在游戏开发任务中是辅助交付，不能替代源码和验证。
- 生图任务必须有 image artifact 义务。
- 前端任务必须有运行或浏览器观察义务。
- 代码修复任务必须有真实 diff / 写入证据和验证结果或限制。

代码要求：

- 修改 `backend/task_system/contracts/semantic_task_contracts.py`。
- 修改 `backend/intent/execution_obligation.py`。
- 新增 `backend/intent/domain_obligation_builder.py`。
- 修改 `backend/task_system/services/assembly_support.py`。

完成标准：

- 专业任务没有核心产物或验证证据时不能通过收口。

### 阶段 5：Prompt Library 数据层

任务细纲：

1. 新增 `backend/prompt_library/` 包。
2. 实现 `PromptResource`、`PromptSelectionContext`、`PromptAssembly`、`PromptManifest`。
3. 实现 registry 和 catalog store。
4. 建立现实工作库默认资源。
5. 将 professional profiles、workflow prompts 通过 adapter 转成任务 prompt resources。
6. 将 Soul 通过 adapter 转成仅 role_mode 可用的 `role_prompt`。

功能要求：

- 所有 prompt 资源可按 type/domain/mode/stage 查询。
- 每个资源有 source、version、cache、visibility。
- 模型可见内容全部是职责语言。

代码要求：

- 新增 `backend/prompt_library/__init__.py`。
- 新增 `backend/prompt_library/models.py`。
- 新增 `backend/prompt_library/catalog_store.py`。
- 新增 `backend/prompt_library/registry.py`。
- 新增 `backend/prompt_library/default_resources.py`。
- 新增 `backend/prompt_library/soul_adapter.py`。

完成标准：

- Prompt Library 可以独立生成资源清单。
- 不改变 runtime 主行为，先 shadow 对照。

### 阶段 6：Prompt Selector / Assembler

任务细纲：

1. 实现 `PromptSelector`。
2. 实现 `PromptAssembler`。
3. 输出 `PromptAssembly + PromptManifest`。
4. 区分 model-visible prompt 和 manifest diagnostics。
5. 支持 stage-aware prompt。
6. 实现 dynamic renderer 白名单。
7. 实现 static / semi_static / turn / runtime 分层 hash。
8. 实现 assembly validator 和 fail closed。

功能要求：

- `professional_mode` 装配专业职责、阶段职责、验证、输出边界。
- `role_mode` 可装配 Soul role prompt，不装配长任务 profile。
- `standard_mode / professional_mode` 不装配 Soul role prompt。
- `task_understanding` prompt 只在理解阶段出现。
- `workflow ID / projection ID / operation ID` 不进入模型正文。
- 动态内容只能通过 renderer 生成，不能直接 dump diagnostics。
- 缺少 professional_mode 关键 section 时阻断模型调用。

代码要求：

- 新增 `backend/prompt_library/selection_context.py`。
- 新增 `backend/prompt_library/selector.py`。
- 新增 `backend/prompt_library/assembly_plan.py`。
- 新增 `backend/prompt_library/assembler.py`。
- 新增 `backend/prompt_library/manifest.py`。
- 新增 `backend/prompt_library/rendering.py`。
- 新增 `backend/prompt_library/renderers.py`。
- 新增 `backend/prompt_library/validator.py`。
- 新增 `backend/prompt_library/hash_utils.py`。
- 新增 `backend/prompt_library/stage_binding.py`。

完成标准：

- 新旧 prompt assembly shadow diff 可读。
- manifest 完整记录 source 和 cache。
- assembly validator 能拦截错装、漏装和内部字段泄露。

### 阶段 7：Runtime 接入

任务细纲：

1. 在 `runtime_bundle_builder.py` 中构建 `PromptSelectionContext`。
2. 用 Prompt Library 替换手工拼接 section。
3. 将 `PromptAssembly` 直接交给 `RuntimeContextManager`。
4. 新增 `LegacyProjectionPromptAdapter`，把任务图旧 projection prompt 映射为 `stage_role/domain_role`。
5. `StageProjectionCycle` / `SoulRuntimeView` 继续服务未迁移任务图，但输出必须进入 adapter，不再作为新 prompt 概念。
6. 保留短期旧 view adapter 只做迁移对照。
7. 移除模型可见内部字段渲染。

功能要求：

- runtime prompt 主来源变成 Prompt Library。
- `TaskBodyOrchestration.prompt_manifest` 可继续被监控页展示。
- 任务图节点 prompt 来自注册 workflow，不被当前聊天误判。

代码要求：

- 修改 `backend/agent_system/assembly/runtime_bundle_builder.py`。
- 修改 `backend/soul/runtime_assembly.py`。
- 修改 `backend/soul/prompt_assembly.py`。
- 修改 `backend/runtime/shared/stage_projection.py`。
- 修改 `backend/runtime/shared/context_manager.py`。
- 修改 `backend/task_system/contracts/runtime_contracts.py`。

完成标准：

- 新运行链路默认使用 Prompt Library。
- 未迁移任务图仍可通过旧 projection 配置拿到节点提示词。
- 新 prompt manifest 能记录 legacy projection source，并将其渲染为任务 prompt。

### 阶段 8：Soul 系统收敛与投影清理

任务细纲：

1. 保留 `SoulProfile / SoulWorld / SoulStory / SoulCard` 作为角色模式资源。
2. 保留任务图旧 projection 配置读取能力，直到全部节点提示词迁移到 Prompt Library。
3. 新链路不再建立 projection resource；旧 projection prompt 只能通过 adapter 转成 `stage_role/domain_role`。
4. 将 Soul 运行时输出收敛为单一 `role_prompt`，且只允许 role_mode 装配。
5. 将 WorkPrompt 迁移到现实工作库或 domain/stage resources。
6. `/api/soul/*` 保持兼容，但内部只服务角色资源管理和 role prompt 生成。
7. 迁移完成并通过任务图回归后，再删除无用旧 prompt 主装配逻辑。

功能要求：

- 用户仍可选择灵魂。
- 灵魂只在角色模式下成为角色提示词。
- 专业任务可以完全不依赖灵魂故事完成。
- 标准和专业任务不能装配灵魂角色提示词。
- 现实工作库不再被误解为角色世界观。
- 投影系统不再作为目标能力保留，但旧任务图 projection prompt 在迁移期必须可用。

代码要求：

- 修改 `backend/soul/catalog_service.py`。
- 修改 `backend/soul/runtime_assembly.py`。
- 修改 `backend/soul/facade.py`。
- 修改 `backend/soul/contracts.py` 中 prompt 主协议相关结构，保留兼容模型或迁移注释。

完成标准：

- 只有一个 prompt 主装配协议。
- Soul 是 role_mode 角色提示词来源，不是主 prompt 系统。
- 新 trace / manifest 不再出现 projection 作为主概念，但会记录 `legacy_projection_source_ref` 直到迁移完成。

### 阶段 9：Professional Runtime 阶段化

任务细纲：

1. 将 `ExecutionRecipe.step_blueprints` 映射到专业阶段 prompt。
2. 每个阶段绑定 required operation 和 verification。
3. 建立 domain plan templates。
4. 引入 EvidencePacket。
5. 引入 DeliverableValidator。

功能要求：

- 专业任务不能第一步写最终报告。
- 每阶段必须有产物或 observation。
- 验证失败后进入 repair，而不是直接总结。
- 子 Agent 或工具结果必须沉淀为 evidence。

代码要求：

- 修改 `backend/runtime/professional_runtime/driver.py`。
- 修改 `backend/runtime/professional_runtime/goal_contract.py`。
- 新增 `backend/runtime/professional_runtime/domain_plan_templates.py`。
- 新增 `backend/runtime/contracts/domain_validators.py`。
- 新增 `backend/runtime/contracts/claim_evidence_alignment.py`。
- 修改 `backend/runtime/contracts/obligation_validation.py`。
- 修改 `backend/runtime/contracts/deliverable_validator.py`。

完成标准：

- 肉鸽游戏任务能看到 domain-specific plan。
- 无源码、无资源、无浏览器证据时验证失败。
- 测试报告诊断任务能输出失败归类、结构根因、回归测试建议。

### 阶段 10：能力 / Skill / Tool 装配

任务细纲：

1. 明确 capability、skill、tool 的边界。
2. 生图能力注册为工具或 capability。
3. 生图 skill 注册为 `skill_prompt`。
4. 浏览器操作能力注册为可由资源策略控制的工具。
5. Tool guidance 只描述使用边界，不授予权限。

功能要求：

- 主 Agent 能根据任务域选择生图 skill。
- 生图结果进入 artifact，并能被前端展示。
- 浏览器任务需要浏览器工具时，由 ResourcePolicy 和 operation requirement 控制。
- 注册工具后不应出现层层权限路障导致 Agent 看不懂如何使用。

代码要求：

- 修改 capability registry 相关文件。
- 修改 skill registry / skill runtime view。
- 修改 resource policy view。
- 修改 task domain profile 中的 required capabilities。

完成标准：

- `image_asset_generation` 任务能装配审美 skill prompt。
- `browser_operation_task` 能装配浏览器操作职责和工具边界。

### 阶段 11：前端配置页和监控页

任务细纲：

1. 新增 Prompt Library 配置页。
2. 新增 Domain Registry 配置 / 查看页。
3. 运行监控页展示 PromptManifest。
4. 任务系统配置页可绑定 prompt resources。

功能要求：

- 配置页像数据库一样实用。
- 列表、筛选、搜索、编辑、预览、版本、回滚。
- 不使用大卡片环绕式布局。
- 不把开发说明当副标题。
- 用户能看到某任务为什么装配这些 prompt。

API 建议：

- `GET /api/prompt-library/resources`
- `PUT /api/prompt-library/resources/{resource_id}`
- `POST /api/prompt-library/preview`
- `GET /api/task-domains`
- `GET /api/task-domains/{domain_id}`

完成标准：

- 能预览：输入任务 + 模式 + 阶段，输出将装配的 prompt sections。
- 能看到每段 prompt 是否模型可见、来源、缓存范围。

### 阶段 12：旧系统清理

任务细纲：

1. 删除 `runtime_bundle_builder.py` 中大段手工 prompt 拼接。
2. 删除或迁移 `professional_profiles.py` 中硬编码 prompt 主路径。
3. 删除 `soul` 中不再作为主协议的 manifest 主逻辑。
4. 清理旧 `simple/managed` 正式路径。
5. 删除无用旧测试，改写为 Prompt Library / Domain Registry / Professional Runtime 测试。

禁止长期保留：

- 两套 PromptManifest 主协议。
- 两套路由 / 任务类型系统。
- 两套 runtime prompt assembler。
- driver 末端重新正则理解任务。
- agent-facing prompt 中的内部字段串。
- 为某个失败样本写死答案。

完成标准：

- 新任务 trace、prompt manifest、recipe metadata 都使用新命名和新结构。
- legacy 只作为 evidence/fallback，且有删除阶段。

## 10. 文件级清单

### 10.1 新增目录 / 文件

Prompt Library：

- `backend/prompt_library/__init__.py`
- `backend/prompt_library/models.py`
- `backend/prompt_library/default_resources.py`
- `backend/prompt_library/catalog_store.py`
- `backend/prompt_library/registry.py`
- `backend/prompt_library/selection_context.py`
- `backend/prompt_library/selector.py`
- `backend/prompt_library/assembler.py`
- `backend/prompt_library/manifest.py`
- `backend/prompt_library/rendering.py`
- `backend/prompt_library/soul_adapter.py`
- `backend/prompt_library/stage_binding.py`
- `backend/prompt_library/runtime_integration.py`

Task Understanding / Domain：

- `backend/intent/task_goal_frame.py`
- `backend/intent/task_goal_interpreter.py`
- `backend/intent/model_task_goal_interpreter.py`
- `backend/intent/task_goal_schema.py`
- `backend/intent/domain_obligation_builder.py`
- `backend/task_system/domains/__init__.py`
- `backend/task_system/domains/task_domain_profiles.py`
- `backend/task_system/domains/domain_registry.py`
- `backend/task_system/domains/domain_matcher.py`
- `backend/task_system/domains/domain_binding.py`

Professional Runtime：

- `backend/runtime/professional_runtime/domain_plan_templates.py`
- `backend/runtime/contracts/domain_validators.py`
- `backend/runtime/contracts/claim_evidence_alignment.py`
- `backend/runtime/shared/evidence_packet.py`

Tests：

- `backend/tests/prompt_inventory_regression.py`
- `backend/tests/prompt_library_registry_regression.py`
- `backend/tests/prompt_library_selector_regression.py`
- `backend/tests/prompt_library_assembly_regression.py`
- `backend/tests/task_goal_understanding_regression.py`
- `backend/tests/domain_binding_regression.py`
- `backend/tests/domain_obligation_regression.py`
- `backend/tests/professional_mode_runtime_regression.py`
- `backend/tests/task_graph_node_prompt_regression.py`
- `backend/tests/domain_validation_regression.py`

### 10.2 重点修改文件

- `backend/agent_system/assembly/runtime_chain.py`
- `backend/agent_system/assembly/runtime_bundle_builder.py`
- `backend/context_system/current_turn/current_turn.py`
- `backend/context_system/resolution/resolver.py`
- `backend/intent/__init__.py`
- `backend/intent/execution_obligation.py`
- `backend/intent/obligation_models.py`
- `backend/task_system/contracts/semantic_task_contracts.py`
- `backend/task_system/contracts/runtime_contracts.py`
- `backend/task_system/planning/execution_recipe_builder.py`
- `backend/task_system/planning/execution_recipe_models.py`
- `backend/task_system/services/assembly_support.py`
- `backend/runtime/shared/context_manager.py`
- `backend/runtime/shared/stage_projection.py`，迁移期间继续读取任务图旧 projection prompt，迁移完成后再降级或删除。
- `backend/runtime/professional_runtime/driver.py`
- `backend/runtime/professional_runtime/goal_contract.py`
- `backend/runtime/contracts/obligation_validation.py`
- `backend/runtime/contracts/deliverable_validator.py`
- `backend/prompting/builder.py`
- `backend/prompting/manifest.py`
- `backend/prompting/professional_profiles.py`
- `backend/prompting/strategy_prototypes.py`
- `backend/soul/contracts.py`
- `backend/soul/catalog_service.py`
- `backend/soul/runtime_assembly.py`
- `backend/soul/prompt_assembly.py`
- `backend/soul/facade.py`

### 10.3 前端后续文件方向

具体路径以后以前端项目结构为准，但页面必须服务这些能力：

- Prompt Library 资源表。
- Domain Registry 资源表。
- Prompt preview。
- Runtime PromptManifest 面板。
- 任务系统节点 prompt 绑定。
- Skill / Tool / Capability 可见配置。

## 11. 验证矩阵

### 11.1 Prompt 装配验证

| 场景 | 必须满足 |
|---|---|
| role_mode 普通聊天 | 可装配 Soul role prompt，不注入专业长任务职责 |
| standard_mode 工具任务 | 有任务职责和工具边界，不装配 Soul / 新 projection |
| professional_mode 代码修复 | 有 code fix domain role、semantic contract、verification prompt |
| 写作图世界观节点 | 有世界观架构师职责，不出现代码修复 profile |
| 写作图审核节点 | 有审核员职责，不替创作者扩写 |
| 生图任务 | 有高审美生图 skill prompt 和 image artifact obligation |
| 前端产品任务 | 有 frontend delivery role、运行 / 浏览器验证要求 |
| 游戏切片任务 | 有 game vertical slice role、资源、玩法、浏览器验证要求 |

### 11.2 Manifest 验证

必须检查：

- section 来源完整。
- cache scope 正确。
- model_visible 正确。
- 内部字段只在 diagnostics。
- omitted resources 有原因。
- stage prompt 能按阶段变化。
- Prompt hash 稳定。

### 11.3 验收器验证

必须拦截：

- 声称图片生成但没有 artifact。
- 声称浏览器验证但没有 browser / terminal observation。
- 声称游戏完成但只有 final_report。
- 声称测试通过但没有命令输出。
- 任务图节点缺少注册 workflow prompt。
- 专业任务最终回答泄露内部运行字段。
- standard/professional 普通任务出现 Soul role prompt 或新 projection。
- 任务图旧 projection prompt 没有被 adapter 转成 `stage_role/domain_role`。

## 12. 迁移和切换规则

### 12.1 Shadow 阶段

Prompt Library 只生成 shadow assembly，不改变真实模型 prompt。

要求：

- 对比旧 SoulRuntimeView / StageProjection sections 和新 PromptAssembly sections。
- 对任务图节点额外检查 legacy projection prompt 是否完整映射为 `stage_role/domain_role`。
- 记录遗漏、冲突和内部字段泄露。
- 不修改用户可见行为。

### 12.2 Cutover 阶段

默认使用 Prompt Library 生成 runtime prompt。

要求：

- `runtime_bundle_builder.py` 不再手工拼主 prompt。
- `RuntimeContextManager` 直接消费 PromptAssembly。
- SoulRuntimeView / StageProjection 对普通新任务只保留迁移对照；对未迁移任务图继续作为 legacy prompt source。
- 旧 prompt builder 只允许短期 fallback。

### 12.3 Cleanup 阶段

删除 fallback 和重复主协议。

要求：

- 删除旧 manifest 主入口。
- 删除 driver 中硬编码 profile。
- 删除旧 simple/managed 正式路径。
- 任务图节点 prompt 全量迁移并回归通过后，才删除旧 projection 主链路。
- 删除无用旧测试。

### 12.4 回滚规则

如果 cutover 阶段出现严重阻断：

1. 回滚到 shadow mode。
2. 保留新 PromptManifest diagnostics。
3. 不恢复旧系统作为长期双轨。
4. 修复 selector / adapter / context manager 后再次 cutover。

## 13. 禁止事项

1. 禁止只针对肉鸽任务加关键词特判。
2. 禁止只针对世界观节点塞 prompt 补丁。
3. 禁止让 Soul 继续承担任务流程主系统。
4. 禁止让 projection 系统换名保留为新架构主概念。
5. 禁止在任务图迁移完成前删除旧 projection prompt 读取链路。
6. 禁止 standard/professional 普通任务装配 Soul role prompt。
7. 禁止长期保留两套 PromptManifest。
8. 禁止把开发字段写进 Agent-facing prompt。
9. 禁止让 prompt selector 自己猜任务域。
10. 禁止用最终回答关键词通过验收。
11. 禁止为了测试伪造产物、命令、图片或浏览器观察。
12. 禁止把配置页做成卡片堆叠展示而无法实际筛选和维护。
13. 禁止用“兼容”为理由保留无用旧残留。

## 14. 推荐实施顺序

必须按以下顺序推进：

1. 阶段 0：盘点和基线。
2. 阶段 1：模式和边界模型。
3. 阶段 2：目标优先任务理解。
4. 阶段 3：任务域注册表。
5. 阶段 4：语义合同和执行义务。
6. 阶段 5：Prompt Library 数据层。
7. 阶段 6：Prompt Selector / Assembler。
8. 阶段 7：Runtime 接入。
9. 阶段 8：Soul 系统收敛。
10. 阶段 9：Professional Runtime 阶段化。
11. 阶段 10：能力 / Skill / Tool 装配。
12. 阶段 11：前端配置页和监控页。
13. 阶段 12：旧系统清理。

其中最小可用闭环是阶段 0 到阶段 9。阶段 10 和 11 可以在专业 Agent 稳定后继续增强，但生图和浏览器能力如果要纳入专业任务验收，应随阶段 9 一起接入最小版本。

## 15. 最终成功状态

完成后系统应达到：

```text
TaskGoalFrame 是任务目标裁决源。
TaskDomainBinding 是流程和资源绑定源。
SemanticTaskContract 是本轮任务合同。
ExecutionRecipe / TaskRunLedger 是单 Agent 和任务图共享执行骨架。
Prompt Library 是 prompt 唯一主来源。
Soul 只在 role_mode 下作为角色提示词来源。
投影系统不再作为新 prompt 主概念；现有任务图 projection prompt 通过 adapter 迁移为 stage_role/domain_role。
现实工作库是公共实用 prompt 库。
PromptManifest 记录所有来源、显隐、缓存和装配结果。
Professional Runtime 按阶段执行、沉淀证据、验证交付。
Agent-facing prompt 全部是职责语言，不混入 runtime 字段。
```

这套架构的关键是把“理解任务”“绑定流程”“装配任务 prompt”“执行验证”“角色模式提示词”分开。分开以后，主 Agent 才能真正独立完成长任务，灵魂系统也能回到它唯一清晰的职责：在角色模式下提供角色提示词。
