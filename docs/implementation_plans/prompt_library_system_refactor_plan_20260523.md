# Prompt Library 系统重构计划书

日期：2026-05-23

## 1. 问题定义

当前项目已经有大量 prompt 能力，但它们分散在不同系统里：

- `backend/prompting/builder.py`：静态 prompt、会话 prompt、turn prompt、memory/context prompt。
- `backend/soul/*`：身份、灵魂、旧投影、共同契约、工作 prompt、PromptManifest。
- `backend/prompting/professional_profiles.py`：专业任务角色 prompt。
- `backend/prompting/strategy_prototypes.py`：任务策略与 prompt profile 绑定。
- `backend/agent_system/assembly/runtime_bundle_builder.py`：手工拼接 task/workflow/semantic/professional/mode/output sections。
- `backend/runtime/shared/context_manager.py`：最终把 base prompt、旧 projection、context、runtime facts 拼进模型消息。

现有问题不是“没有 prompt”，而是缺少一个实用的 Prompt Library 作为统一来源和装配协议。灵魂系统目前承担了太多混合职责：身份体验、工作提示、投影、共同契约、前端管理资源、runtime prompt section。新架构取消投影系统，灵魂只在 `role_mode` 下作为角色提示词来源，不再作为标准任务或专业任务的 prompt 资源。

正确方向：

```text
Soul System
  -> 收敛为 role_mode 专用 role_prompt 来源

Prompt Library
  -> 管理所有可复用 prompt 资源
  -> 按任务理解、任务域、runtime mode、skill/tool、验证阶段进行任务 prompt 装配
  -> 输出 PromptAssembly + PromptManifest
```

## 2. 现有代码诊断

### 2.1 Prompt 来源分散

`runtime_bundle_builder.py` 目前直接构造：

- `task_section`
- `workflow_section`
- `semantic_task_section`
- `professional_profile_section`
- `mode_policy_section`
- `projection_section`，旧链路待清理
- `output_section`
- `guardrail_section`

这些 section 有的是给模型看的职责语言，有的是系统字段摘要，有的是调试信息。它们在同一个函数里拼装，导致 prompt 的来源、优先级、显隐、缓存边界不够清楚。

### 2.2 Agent-facing prompt 混入开发字段

例如当前 `_workflow_section()` 会输出 `Workflow ID`、`Task mode`、`Output boundary` 等字段。用户此前明确指出，agent-facing prompt 不能写成：

```text
这是 runtime 节点。
根据任务图执行 world_review。
这个节点用于校验资产。
```

而应该写成：

```text
你是一名世界观审核员。
你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。
你不负责替创作者扩写设定。
你需要指出问题、给出裁决、说明是否允许进入下一阶段。
```

因此新系统必须区分：

- 模型可见 prompt：职责语言、任务目标、交付物、约束、验证标准。
- 系统 manifest：source_id、workflow_id、task_mode、cache_scope、diagnostics。

### 2.3 Soul 已经有资源雏形，但分类不够实用

`backend/soul/contracts.py` 已有：

- `PromptSection`
- `SoulRuntimeView`
- `SoulPromptManifest`
- `WorkPrompt`
- `CommonContractPrompt`
- `SoulProfile`
- `SoulProjectionRequest`

`backend/soul/catalog_store.py` 已有 JSON bucket 存储。

问题是资源分类偏“灵魂体验”和旧投影机制，不够覆盖实用任务 prompt：

- 任务理解 prompt。
- 任务域 prompt。
- 阶段角色 prompt。
- 验证 prompt。
- 工具使用 prompt。
- 输出边界 prompt。
- 长任务监督 prompt。
- 生图审美 prompt。
- 前端设计 prompt。
- 写作图节点 prompt。

### 2.4 现有 PromptManifest 有两套

- `backend/prompting/manifest.py`
- `backend/soul/contracts.py::SoulPromptManifest`

它们都记录 section，但字段和生命周期不统一。新系统应保留一个通用 `PromptManifest` 模型，兼容 soul manifest，但不要长期维护两套主协议。

### 2.5 缓存边界尚未成为 prompt 库的一等字段

设计资料 `docs/设计原则/04-System-Prompt-工程.md` 和 `docs/设计原则/07-Prompt-Cache.md` 明确强调：

- prompt 应分段。
- 静态与动态内容应分离。
- 每段 prompt 需要 cache scope。
- 动态 section 会影响成本和稳定性。

当前 `soul.contracts.PromptSection.cache_scope` 已经有字段，但没有统一执行到全局 prompt library 的选择和装配层。

## 3. 目标设计

### 3.1 总体架构

```text
User Turn
  -> TaskGoalFrame / SemanticTaskContract / RuntimeModePolicy
  -> PromptSelectionContext
  -> PromptLibraryRegistry
  -> PromptSelector
  -> PromptAssemblyPlan
  -> PromptAssembler
  -> PromptAssembly + PromptManifest
  -> RuntimeContextManager
  -> Model Messages
```

### 3.2 Prompt Library 的资源分类

首批资源类型：

| 类型 | 用途 |
|---|---|
| `common_contract` | 所有任务通用底线，如事实、输出、暴露限制 |
| `role_prompt` | 仅 `role_mode` 可用的灵魂角色提示词 |
| `task_understanding` | 模型先理解用户任务时使用 |
| `domain_role` | 按任务域装配的专业职责 |
| `stage_role` | 长任务每个阶段的角色职责 |
| `skill_prompt` | skill 给模型看的使用边界 |
| `tool_guidance` | 工具使用方式，不等于授权 |
| `verification` | 验证员职责和证据标准 |
| `output_boundary` | 最终回答、产物、限制说明 |

### 3.3 核心数据模型

新增建议文件：

- `backend/prompt_library/models.py`
- `backend/prompt_library/registry.py`
- `backend/prompt_library/selector.py`
- `backend/prompt_library/assembler.py`
- `backend/prompt_library/catalog_store.py`
- `backend/prompt_library/soul_adapter.py`

建议模型：

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
    semantic_task_contract: dict[str, Any]
    task_goal_frame: dict[str, Any]
    active_skill: dict[str, Any]
    visible_tool_ids: tuple[str, ...]
    stage_id: str = ""
```

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

### 3.4 选择规则

PromptSelector 必须按稳定优先级选择：

1. `common_contract`：固定基础层。
2. `role_prompt`：仅 `role_mode` 可选，来自 Soul。
3. `task_understanding`：只用于任务理解阶段，不进入执行阶段常驻 prompt。
4. `domain_role`：由 `task_goal_type/task_domain` 绑定。
5. `stage_role`：由 `ExecutionRecipe.step_blueprints` 或当前 `TaskRunLedger.current_step_id` 绑定。
6. `skill_prompt`：由 active skill / skill runtime view 绑定。
7. `tool_guidance`：只描述使用边界，授权仍由 ResourcePolicy 决定。
8. `verification`：验证阶段或专业模式强制装配。
9. `output_boundary`：始终装配，但内容随 task mode 变化。

禁止事项：

- 不允许 prompt 资源直接声明工具授权。
- 不允许 `role_prompt` 覆盖 semantic contract。
- 不允许 `role_prompt` 进入 `standard_mode` 或 `professional_mode`。
- 不允许模型可见内容包含内部字段名、workflow id、operation id、manifest id，除非用户正在做系统调试。
- 不允许 prompt 选择器靠纯关键词长期判断任务域；它只能消费上游 `TaskGoalFrame/SemanticTaskContract`。

### 3.5 装配协议

Prompt 装配必须拆成两个动作：

```text
PromptSelector
  -> 输入 PromptSelectionContext
  -> 输出 PromptAssemblyPlan
  -> 只负责选资源、排序、给出 omitted reason

PromptAssembler
  -> 输入 PromptAssemblyPlan + structured runtime payload
  -> 输出 PromptAssembly + PromptManifest
  -> 只负责按 renderer 渲染，不重新选择资源
```

固定装配顺序：

```text
Static Base
  common_contract
  domain_role / professional_profile
  skill_prompt
  verification
  output_boundary

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

禁止在 `runtime_bundle_builder.py`、driver 或 context manager 中绕过 `PromptAssembler` 临时拼接模型可见 prompt。

### 3.6 静态与动态边界

| 层级 | cache_scope | 来源 | 内容 | 生成时机 | 可变性 |
|---|---|---|---|---|---|
| Static Base | `static` | 内置现实工作库、任务域库、skill 库 | 通用准则、领域职责、验证职责、输出边界模板 | 进程启动或配置加载 | 只能随版本变化 |
| Semi Static | `semi_static` | 用户配置、agent profile、role_mode Soul | 角色提示词、用户自定义 prompt 资源 | 会话开始或配置变更 | 必须有版本号和 hash |
| Turn Dynamic | `turn` | TaskGoalFrame、DomainBinding、SemanticTaskContract、ExecutionObligation | 本轮目标、交付物、禁止项、当前阶段职责 | 每个 turn / 每个 stage | 必须结构化生成 |
| Runtime Dynamic | `runtime` | ResourcePolicy、工具可见性、时间事实、Evidence、Validator | 工具边界、运行事实、证据摘要、验证状态 | 每次模型调用前 | 白名单字段生成 |

硬规则：

1. `static` section 不能引用 session、task、user message、tool state、当前时间。
2. `semi_static` section 必须有配置版本和 hash，只有配置变更才允许变化。
3. `turn` section 只能来自结构化合同，不得直接拼接用户全文。
4. `runtime` section 只能来自白名单 runtime facts，不得把任意 diagnostics dump 给模型。
5. `runtime` section 永远排在 static / semi_static / turn section 之后。
6. standard/professional 模式的动态 section 不得包含 Soul role prompt。

### 3.7 动态 Renderer 控制

每类动态 section 必须有专用 renderer。Renderer 必须声明：

- `renderer_id`
- 输入 schema。
- 输出 section type。
- 最大字符数。
- 允许字段白名单。
- 是否模型可见。
- 缺字段处理方式。

首批 renderer：

| renderer_id | 输入 | 输出 | 控制要求 |
|---|---|---|---|
| `task_goal_frame_summary` | `TaskGoalFrame` | `turn.task_goal` | 只输出目标、核心/辅助交付、成功标准、显式约束 |
| `domain_binding_summary` | `TaskDomainBinding` | `turn.domain_binding` | 只输出领域、流程模板和继承验证，不输出内部 binding id |
| `semantic_contract_summary` | `SemanticTaskContract` | `turn.semantic_contract` | 只输出任务类型、领域、材料角色、交付物、禁止项 |
| `execution_obligation_summary` | `ExecutionObligation` | `turn.execution_obligation` | 只输出必须执行/验证的义务，不输出 operation id |
| `tool_boundary_summary` | `ResourcePolicy` | `runtime.tool_guidance` | 只输出当前模型可见工具边界，不输出未授权工具 |
| `runtime_time_fact` | runtime facts | `runtime.time_fact` | 只在任务需要时间事实时输出 |
| `evidence_summary` | EvidencePacket | `runtime.evidence` | 只输出证据摘要和 refs，不塞原始大段工具结果 |
| `validation_state_summary` | Validator result | `runtime.validation` | 只输出缺失项和阻断原因，不允许模型自我声明通过 |

长度控制：

- 单个 `turn` section 默认不超过 1200 字符。
- 单个 `runtime` section 默认不超过 800 字符。
- evidence 超限时输出 refs 和结论，不塞原文。
- 超限、截断、丢弃字段必须进入 manifest diagnostics。

### 3.8 装配校验与 Fail Closed

PromptAssembly 在进入模型调用前必须通过校验。

装配前校验：

1. `interaction_mode` 必须存在且只能是 `role_mode / standard_mode / professional_mode`。
2. `standard_mode / professional_mode` 中不得选中 `role_prompt`。
3. `professional_mode` 必须有 `semantic_task_contract`、`domain_role` 或 `professional_profile`、`output_boundary`。
4. 当前 stage 如果需要执行或验证，必须有对应 `stage_role` 或 `verification` section。
5. 所有 model-visible section 必须有非空 content、source_ref、cache_scope、owner_layer。
6. section id 必须唯一。
7. section order 必须来自固定枚举。

失败策略：

- 缺少非关键 role prompt：role_mode 可降级为无角色普通回答，并在 diagnostics 标记。
- 缺少 standard_mode 任务合同：降级为澄清问题，不执行副作用工具。
- 缺少 professional_mode 关键 section：fail closed，阻断模型执行，返回装配错误给 runtime。
- 出现 forbidden section，例如 professional_mode 装配 Soul role prompt：fail closed。
- 出现内部字段泄露风险：fail closed，除非当前是显式 debug 视图且 model_visible=false。

### 3.9 Manifest 可观测性

每次装配必须生成完整 `PromptManifest`。Manifest 是调试和前端展示唯一来源，模型不可见。

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

## 4. 分阶段实施计划

## 阶段一：Prompt 资源盘点与测试基线

### 任务细纲

1. 扫描所有 prompt 来源：
   - `backend/prompting/builder.py`
   - `backend/prompting/professional_profiles.py`
   - `backend/prompting/strategy_prototypes.py`
   - `backend/soul/*.py`
   - `backend/soul/*/catalog.json`
   - `backend/agent_system/assembly/runtime_bundle_builder.py`
   - `backend/runtime/shared/context_manager.py`
2. 列出每段 prompt 的：
   - 当前来源。
   - 模型是否可见。
   - 是否静态。
   - 是否和任务域相关。
   - 是否包含内部实现字段。
3. 固化回归样本：
   - 角色模式聊天。
   - 标准模式工具任务。
   - 专业代码修复。
   - 专业游戏开发。
   - 写作任务图世界观节点。
   - 生图 prompt skill。

### 功能要求

- 能生成当前 prompt section 报告。
- 能证明哪些 section 泄露了开发式字段。
- 能证明任务图节点和专业模式 prompt 来源可追踪。

### 代码实现要求

新增：

- `backend/tests/prompt_library_inventory_regression.py`
- `backend/tests/fixtures/prompt_cases.py`

不改运行行为，只建立诊断基线。

## 阶段二：新增 Prompt Library 数据模型与注册表

### 任务细纲

1. 新增 `backend/prompt_library/` 包。
2. 实现 `PromptResource`、`PromptSelectionContext`、`PromptAssembly`、`PromptManifest`。
3. 实现 JSON catalog store。
4. 建立内置默认资源：
   - common contract。
   - default work prompt。
   - task understanding prompt。
   - code fix domain role。
   - frontend delivery domain role。
   - game vertical slice domain role。
   - verification prompt。
   - output boundary prompt。
5. 暂时从现有 soul/professional profiles 导入资源，不改变 runtime。

### 功能要求

- 所有 prompt 资源可按 type/domain/mode/stage 查询。
- 每个资源必须有 `resource_id/resource_type/cache_scope/source_ref/model_visible`。
- 资源内容必须是 agent-facing 职责语言。

### 代码实现要求

新增：

- `backend/prompt_library/__init__.py`
- `backend/prompt_library/models.py`
- `backend/prompt_library/catalog_store.py`
- `backend/prompt_library/registry.py`
- `backend/prompt_library/default_resources.py`

测试：

- `backend/tests/prompt_library_registry_regression.py`

## 阶段三：Prompt Selector 与装配计划

### 任务细纲

1. 实现 `PromptSelector`。
2. 输入 `PromptSelectionContext`。
3. 输出 `PromptAssemblyPlan`，包含：
   - selected resource ids。
   - section order。
   - conflict diagnostics。
   - cache plan。
   - model-visible plan。
   - static / semi_static / turn / runtime 分层计划。
   - forbidden section 检查结果。
4. 支持按三模式选择：
   - `role_mode`：可以装配 Soul role prompt，任务职责只保留轻量问答边界。
   - `standard_mode`：只装配任务职责和工具边界。
   - `professional_mode`：semantic contract、domain role、stage role、verification 权重最高。

### 功能要求

- 同一任务在不同模式下 section 组合不同。
- standard_mode / professional_mode 不得装配 Soul role prompt。
- task_understanding prompt 只进入理解阶段，不常驻执行 prompt。

### 代码实现要求

新增：

- `backend/prompt_library/selection_context.py`
- `backend/prompt_library/selector.py`
- `backend/prompt_library/assembly_plan.py`

测试：

- `backend/tests/prompt_library_selector_regression.py`

## 阶段四：Prompt Assembler 与统一 Manifest

### 任务细纲

1. 实现 `PromptAssembler`。
2. 只把模型可见 section 渲染成 prompt 内容。
3. 把系统字段写入 manifest，不写入模型可见正文。
4. 实现动态 renderer 白名单。
5. 实现装配校验和 fail closed。
6. 支持 cache scope：
   - `static`
   - `semi_static`
   - `turn`
   - `runtime`
7. 输出统一 `PromptManifest`。

### 功能要求

- 每段 prompt 可追踪来源。
- prompt 正文不出现 `Workflow ID`、`Task mode`、`operation_id` 这类开发字段。
- manifest 保留这些字段供调试和前端展示。
- static / semi_static / turn / runtime section 顺序固定。
- dynamic section 只能通过 renderer 生成。
- 缺少 professional_mode 关键 section 时阻断模型调用。

### 代码实现要求

新增：

- `backend/prompt_library/assembler.py`
- `backend/prompt_library/manifest.py`
- `backend/prompt_library/rendering.py`
- `backend/prompt_library/renderers.py`
- `backend/prompt_library/validator.py`
- `backend/prompt_library/hash_utils.py`

修改：

- `backend/prompting/manifest.py` 逐步适配或迁移。
- `backend/soul/prompt_assembly.py` 改为兼容 adapter。

测试：

- `backend/tests/prompt_library_assembly_regression.py`

## 阶段五：Soul 系统收敛为 role_mode 角色提示词

### 任务细纲

1. 保留 `SoulProfile`、世界、故事、manifestation 等角色资源。
2. 保留任务图旧 projection 配置读取能力，直到全部节点提示词迁移到 Prompt Library。
3. 取消新架构中的投影系统，不再建立 projection prompt resource。
4. 将旧 projection prompt 通过 `LegacyProjectionPromptAdapter` 映射为 `stage_role/domain_role`。
5. 将 Soul 的模型可见内容收敛为单一 `role_prompt`，且只允许 `role_mode` 装配。
6. 将 `work_prompts/catalog.json` 迁移为 prompt library `domain_role/stage_role` 或 `output_boundary` 资源。
7. 保留 `/api/soul/*` 兼容 API，但内部只服务角色资源管理和 role prompt 生成。

### 功能要求

- 用户仍可选择灵魂。
- 灵魂只在角色模式下作为角色提示词，不再承担工作 prompt 装配。
- 工作类 agent 可以完全不启用灵魂身份，只使用实用 prompt 资源。
- standard_mode / professional_mode 不得装配 Soul role prompt。
- 新 trace / manifest 不再出现 projection 作为主概念，但迁移期必须记录 `legacy_projection_source_ref`。
- 未迁移任务图仍能通过旧 projection prompt 获得节点职责提示词。

### 代码实现要求

新增：

- `backend/prompt_library/soul_adapter.py`
- `backend/prompt_library/legacy_projection_adapter.py`

修改：

- `backend/soul/catalog_service.py`
- `backend/soul/runtime_assembly.py`
- `backend/soul/projection_builder.py`，迁移期间继续服务任务图旧 projection prompt 读取，迁移完成后再降级或删除。
- `backend/soul/facade.py`

迁移要求：

- 不保留无用旧路径作为第二套主系统。
- 兼容 API 只做 adapter，不再生成独立主 prompt 协议。

## 阶段六：接入 Agent Runtime Assembly

### 任务细纲

1. 在 `runtime_bundle_builder.py` 中构建 `PromptSelectionContext`。
2. 用 Prompt Library 生成 `PromptAssembly`。
3. 将 `PromptAssembly` 直接进入 `TaskBodyOrchestration` 和 `RuntimeContextManager`。
4. 对任务图节点调用 `LegacyProjectionPromptAdapter`，把旧 projection prompt 转成 `stage_role/domain_role`。
5. `SoulRuntimeView` / `StageProjectionCycle` 对普通新任务只保留迁移对照；对未迁移任务图继续作为 legacy prompt source。
6. 删除 `_semantic_task_section/_workflow_section/_mode_policy_section` 中模型可见的内部字段渲染。

### 功能要求

- runtime prompt 来源变成 Prompt Library。
- `TaskBodyOrchestration.prompt_manifest` 仍可被监控页展示。
- 任务图节点 prompt 必须来自注册工作流和 prompt resource，而不是当前聊天误判。
- 任务图旧 projection prompt 必须能在 manifest 中追踪到 source ref。

### 代码实现要求

修改：

- `backend/agent_system/assembly/runtime_bundle_builder.py`
- `backend/runtime/shared/stage_projection.py`，迁移期间继续读取任务图旧 projection prompt，迁移完成后再降级或删除。
- `backend/runtime/shared/context_manager.py`
- `backend/task_system/contracts/runtime_contracts.py`

测试：

- `backend/tests/professional_mode_runtime_regression.py`
- `backend/tests/soul_role_prompt_interaction_mode_regression.py`
- `backend/tests/writing_modular_novel_graph_config_regression.py`

## 阶段七：阶段化 Prompt 装配

### 任务细纲

1. 将 `ExecutionRecipe.step_blueprints` 和 `TaskRunLedger.current_step_id` 映射为 stage prompt context。
2. 支持不同阶段装配不同 prompt：
   - task understanding。
   - domain matching。
   - planning。
   - implementation。
   - verification。
   - finalization。
3. 专业模式中，每一阶段只给模型看该阶段职责。

### 功能要求

- 任务理解阶段不能拿执行 prompt。
- 验证阶段必须拿 evidence-only 验证 prompt。
- 写作图节点必须拿节点专业职责 prompt。
- 生图能力必须拿审美和 prompt 描述 prompt，而不是通用聊天 prompt。

### 代码实现要求

修改：

- `backend/runtime/professional_runtime/driver.py`
- `backend/runtime/shared/context_manager.py`
- `backend/task_system/planning/execution_recipe_builder.py`

新增：

- `backend/prompt_library/stage_binding.py`

## 阶段八：前端 Prompt Library 配置页

### 任务细纲

1. 新增 prompt library catalog API。
2. 前端配置页按数据库风格展示：
   - 资源列表。
   - 类型筛选。
   - 适用任务域。
   - 适用模式。
   - 版本。
   - 是否模型可见。
   - cache scope。
3. 支持编辑用户自定义 prompt 资源。
4. 支持预览某个任务会装配哪些 prompt。

### 功能要求

- 配置页必须实用，不做卡片环绕式展示。
- 像数据库一样能筛选、查看、编辑、预览、回滚。
- 用户能看到 agent 当前为什么装配了这些 prompt。

### 代码实现要求

新增 API：

- `GET /api/prompt-library/resources`
- `PUT /api/prompt-library/resources/{resource_id}`
- `POST /api/prompt-library/preview`

新增或修改前端：

- `frontend/src/.../PromptLibraryPage`
- 复用现有配置页布局，不重新堆一个“灵魂门户”。

## 阶段九：旧系统收口与清理

### 任务细纲

1. 清理 `professional_profiles.py` 中硬编码 prompt，迁移为内置 prompt resources。
2. 清理 `runtime_bundle_builder.py` 中大段手写 section 渲染。
3. 清理 soul 中不再作为主协议的 prompt manifest 代码。
4. 更新 API 命名与文档：Soul 是 role_mode 的 role prompt 来源，不是 prompt 主系统。
5. 删除无用旧测试或改写为 prompt library 测试。

### 功能要求

- 只有一个主 prompt 装配协议。
- Soul 作为资源层兼容存在。
- 所有 runtime prompt 都有 manifest 和 source diagnostics。

### 代码实现要求

禁止长期保留：

- 两套 PromptManifest 主协议。
- 两套 runtime prompt assembler。
- 在 runtime driver 里直接硬编码专业 prompt。
- agent-facing prompt 中的内部字段串。

## 5. 文件级执行清单

### 新增文件

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
- `backend/tests/prompt_library_inventory_regression.py`
- `backend/tests/prompt_library_registry_regression.py`
- `backend/tests/prompt_library_selector_regression.py`
- `backend/tests/prompt_library_assembly_regression.py`

### 修改文件

- `backend/agent_system/assembly/runtime_bundle_builder.py`
- `backend/runtime/shared/context_manager.py`
- `backend/runtime/shared/stage_projection.py`，迁移期间继续读取任务图旧 projection prompt，迁移完成后再降级或删除。
- `backend/soul/contracts.py`
- `backend/soul/catalog_service.py`
- `backend/soul/runtime_assembly.py`
- `backend/soul/prompt_assembly.py`
- `backend/soul/facade.py`
- `backend/prompting/builder.py`
- `backend/prompting/manifest.py`
- `backend/prompting/professional_profiles.py`
- `backend/prompting/strategy_prototypes.py`
- `backend/task_system/contracts/runtime_contracts.py`
- `backend/runtime/professional_runtime/driver.py`

### 前端后续文件

- prompt library 配置页。
- runtime monitor prompt manifest 面板。
- task system 配置页中增加 prompt resources 绑定字段。

## 6. 验证矩阵

### 单元测试

- 资源注册与查询。
- selector 按模式和任务域选择资源。
- assembler 不泄露内部字段。
- manifest 来源完整。
- soul adapter 兼容现有 soul catalog。
- professional profile 迁移后仍能装配。

### 回归测试

- role_mode 聊天仍可装配 Soul role prompt。
- standard_mode 工具任务不装配灵魂故事或 role prompt。
- professional_mode 优先任务职责和验证。
- 写作图世界观节点能看到世界观架构师 prompt。
- 写作图节点旧 projection prompt 能被 adapter 转成 stage_role/domain_role。
- 生图能力能看到审美 prompt。
- 游戏开发任务不能只拿 final_report prompt。

### 端到端测试

- 发起一个普通聊天任务，检查 prompt sections。
- 发起一个专业代码修复任务，检查 domain_role 和 verification。
- 发起一个写作图节点任务，检查 stage_role。
- 发起一个生图任务，检查 skill_prompt。
- 发起一个长任务，检查不同阶段 prompt 是否变化。

## 7. 迁移与切换规则

### Shadow 阶段

- Prompt Library 只生成 diagnostics，不改变模型实际 prompt。
- 对比旧 soul/runtime/projection sections 和新 assembly。
- 对任务图节点额外检查 legacy projection prompt 是否完整映射为 `stage_role/domain_role`。

### Cutover 阶段

- `runtime_bundle_builder.py` 默认使用 Prompt Library。
- `RuntimeContextManager` 直接消费 PromptAssembly。
- SoulRuntimeView / StageProjection 对普通新任务只保留迁移对照；对未迁移任务图继续作为 legacy prompt source。
- 旧 builder 保留一个短期 fallback 开关。

### Cleanup 阶段

- 删除 fallback。
- 删除重复 manifest。
- 删除专业 prompt 硬编码主路径。
- 任务图节点 prompt 全量迁移并回归通过后，才删除旧 projection 读取链路。

## 8. 最终状态

完成后系统应满足：

```text
Prompt Library 是 prompt 的唯一主来源。
Soul 只在 role_mode 下作为 role_prompt 来源。
投影系统不再作为新 prompt 主概念；现有任务图 projection prompt 通过 adapter 迁移为 stage_role/domain_role。
TaskGoalFrame 和 SemanticTaskContract 决定任务职责 prompt。
ExecutionRecipe/TaskRunLedger 决定阶段 prompt。
Skill/Tool 只贡献使用边界，不贡献授权。
PromptManifest 记录所有来源、显隐、缓存和装配结果。
Agent-facing prompt 全部是职责语言，不混入 runtime 字段。
```

这会让 agent 需要什么 prompt 就装配什么 prompt，而不是让一个灵魂系统硬撑所有工作场景。
