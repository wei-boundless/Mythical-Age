# 任务理解系统目标优先重构计划书

日期：2026-05-23

## 1. 背景与问题定义

当前任务理解链路在复杂开发任务上出现结构性误判。典型失败是“开发一个浏览器端 2D 肉鸽游戏垂直切片”被识别成 `workspace_file_write` 和 `code_fix_execution`，最终主 Agent 只写了 `final_report.md`，没有完成游戏源码、生图资源、启动验证和浏览器验收。

这不是单个 prompt 失效，也不是某个关键词缺失，而是任务理解架构的裁决顺序错误：

```text
当前错误顺序：
用户原文 -> 路径/关键词规则 -> route_hint/task_kind -> semantic contract -> runtime

目标顺序：
用户原文 -> 目标理解 -> 任务域匹配 -> 流程/资源绑定 -> semantic contract -> runtime
```

系统应先理解用户真正要完成的结果，再根据任务域和已注册流程确定资源、工具、阶段和验收要求。路径、关键词、文件名、报告名只能作为证据，不应拥有最终裁决权。

## 2. 现有代码诊断

### 2.1 旧任务理解层拥有过高裁决权

文件：

- `backend/understanding/task_understanding.py`
- `backend/understanding/query_understanding.py`

问题：

- `WORKSPACE_FILE_PATH_PATTERN` 会把 `docs/.../final_report.md` 识别成显式工作区路径。
- `_looks_like_workspace_write_request` 看到“写入、生成、产出、创建”等词后，直接触发 `workspace_write_request`。
- `_build_bounded_workspace_write_task` 直接产出 `task_kind=workspace_file_write`、`route_hint=workspace_write`、`candidate_tools=["write_file"]`。

代码层问题不是“规则不够多”，而是规则结果被当成任务裁决，而不是弱信号。

### 2.2 执行义务层从原文关键词反推动作

文件：

- `backend/intent/execution_obligation.py`

问题：

- `_WRITE_MARKERS` 包含“实现”，导致复杂产品开发任务被抽象成普通写入义务。
- `_VERIFY_MARKERS` 偏向 `pytest`、`run tests` 等命令语言，无法识别“启动项目、浏览器验证、运行验证、玩法验收”。
- `_build_write_requirements` 无法从“做一个游戏/应用/工具”反推出源码、资源、入口文件和验证对象，只能得到泛化的 `workspace_change`。

### 2.3 语义任务合同缺少产品交付类任务域

文件：

- `backend/task_system/contracts/semantic_task_contracts.py`

问题：

- `_resolve_task_goal_type` 主要在 `code_fix_execution`、`artifact_delivery`、`material_synthesis`、`bounded_tool_task` 等类型之间选择。
- 缺少 `interactive_product_delivery`、`frontend_app_delivery`、`game_vertical_slice_delivery` 等任务类型。
- 因为用户说“真实修改代码”，系统把“开发产品”归为“代码修复执行”。

### 2.4 专业运行时继承错误合同

文件：

- `backend/runtime/professional_runtime/goal_contract.py`
- `backend/runtime/professional_runtime/driver.py`

问题：

- `_goal_contract_from_semantic_contract` 只消费已经被误判的 semantic contract。
- `code_fix_execution` 生成的是“检查代码、结构性修改、运行或说明验证”的通用计划。
- 计划没有保留用户要求的阶段，如玩法设计、技术设计、资产清单、生图提示词、MVP、资源接入、运行验证、最终报告。

### 2.5 验收层没有任务域验收

文件：

- `backend/runtime/contracts/obligation_validation.py`
- `backend/runtime/contracts/deliverable_validator.py`

问题：

- 主要检查是否有写入观察、命令观察、输出路径、最终回答关键词。
- 无法识别“最终报告声称存在 index.html/game.js/图片资源，但实际没有文件观察”的伪完成。
- 没有按任务域验证浏览器应用、游戏切片、图片资源、运行截图或 Playwright/浏览器证据。

## 3. 重构目标

### 3.1 核心目标

建立目标优先的任务理解系统：

```text
User Message
  -> TaskGoalFrame
  -> TaskDomainProfile Match
  -> SemanticTaskContract
  -> ExecutionObligation
  -> RuntimeInteractionModePolicy
  -> Professional Runtime Plan
  -> Domain-Aware Validation
```

### 3.2 功能要求

重构完成后，系统必须支持：

1. 识别复杂任务的真实目标，而不是被文件路径或局部动词劫持。
2. 区分核心交付物和辅助交付物。
3. 根据任务域绑定系统已有流程、skills、工具和验证要求。
4. 支持产品开发类任务，如浏览器应用、游戏原型、图编辑器、任务系统 UI 重构。
5. 支持阶段化长任务，不把最终报告当成替代执行。
6. 对最终回答中的完成声明做证据对齐检查。
7. 保留短任务、PDF、表格、实时查询等轻量路径的效率。

### 3.3 设计原则

1. 目标理解优先，关键词规则降级为证据。
2. 系统流程可注册、可查询、可扩展，而不是散落在 if/else。
3. 任务域合同应描述用户可理解的职责，不写成 runtime 节点说明。
4. 执行义务从目标合同反推，而不是只从用户原文关键词抽取。
5. 验收必须和任务域绑定，不能只看是否写了一个文件。
6. 兼容路径要有限期，旧逻辑不能长期作为第二套主系统。

## 4. 目标数据模型

### 4.1 TaskGoalFrame

新增文件建议：

- `backend/intent/task_goal_frame.py`

功能要求：

- 表示当前 turn 的真实任务目标。
- 作为 semantic contract 的上游输入。
- 不直接执行工具，不直接产生路由。

建议结构：

```python
@dataclass(frozen=True, slots=True)
class TaskGoalFrame:
    user_goal: str
    goal_summary: str
    task_goal_type: str
    task_domain: str
    complexity: str
    core_deliverables: tuple[dict[str, Any], ...]
    supporting_deliverables: tuple[dict[str, Any], ...]
    success_criteria: tuple[dict[str, Any], ...]
    required_capabilities: tuple[str, ...]
    required_verifications: tuple[dict[str, Any], ...]
    explicit_constraints: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    evidence: dict[str, Any]
    confidence: float
    authority: str = "intent.task_goal_frame"
```

实现要求：

- `task_goal_type` 必须是稳定枚举式字符串，不能随模型自由命名。
- `core_deliverables` 和 `supporting_deliverables` 必须分离。
- `success_criteria` 必须面向功能完成状态，而不是面向最终回答格式。
- `evidence` 可以包含路径、关键词、已有 `IntentFrame`、旧 `TaskUnderstanding` 结果，但不能让 evidence 自动覆盖目标类型。

### 4.2 TaskDomainProfile

新增文件建议：

- `backend/task_system/domains/task_domain_profiles.py`

功能要求：

- 注册可复用任务域。
- 定义每个任务域的目标类型、默认流程、能力需求、验证需求和专业 prompt profile。

建议结构：

```python
@dataclass(frozen=True, slots=True)
class TaskDomainProfile:
    domain_id: str
    task_goal_type: str
    title: str
    description: str
    match_markers: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    default_core_deliverables: tuple[str, ...]
    default_supporting_deliverables: tuple[str, ...]
    default_success_criteria: tuple[str, ...]
    default_verifications: tuple[str, ...]
    strategy_prototype_id: str
    professional_profile_id: str
    validator_profile_id: str
```

首批内置任务域：

- `code_fix_execution`
- `artifact_delivery`
- `material_synthesis`
- `frontend_app_delivery`
- `interactive_product_delivery`
- `game_vertical_slice_delivery`
- `image_asset_generation`
- `browser_operation_task`
- `workflow_graph_coordination`

实现要求：

- 注册表必须是单一来源。
- 不允许在 `semantic_task_contracts.py` 中继续堆新增任务域 if/else。
- domain profile 可从存储加载，但必须有内置兜底。
- 任务域 prompt 必须写成 agent 职责语言，而不是系统实现语言。

## 5. 阶段实施计划

## 阶段一：建立诊断基线与回归样本

### 任务细纲

1. 固化肉鸽失败 prompt 为回归样本。
2. 新增至少 6 类任务理解样本：
   - 浏览器肉鸽游戏开发。
   - 前端图编辑器重构。
   - 普通代码 bug 修复。
   - 只写一份 Markdown 报告。
   - PDF 页面阅读。
   - 实时联网查询。
3. 为每个样本记录预期：
   - `task_goal_type`
   - `task_domain`
   - 核心交付物
   - 辅助交付物
   - 必须验证项
   - 禁止误判项

### 功能要求

- 必须能证明当前系统如何失败。
- 必须覆盖“带报告路径但报告不是核心产物”的任务。
- 必须覆盖“确实只写文件”的任务，防止新系统过度复杂化。

### 代码实现要求

新增或扩展：

- `backend/tests/task_goal_understanding_regression.py`
- `backend/tests/fixtures/task_goal_cases.py`

测试用例必须直接调用理解层函数，不依赖完整 `/api/chat`。

### 完成标准

- 当前旧系统在肉鸽样本上失败的断言清晰存在。
- 新目标类型的预期合同被测试表达出来。
- 不允许通过修改测试预期掩盖当前缺陷。

## 阶段二：新增 TaskGoalFrame，不切换主链路

### 任务细纲

1. 新增 `TaskGoalFrame` 数据模型。
2. 新增 `build_task_goal_frame`。
3. 先采用 deterministic + 结构化规则混合实现：
   - 复用 `IntentFrame`。
   - 读取 `TaskUnderstanding` 作为 evidence。
   - 根据产品类、开发类、报告类、查询类信号初步归类。
4. 输出 shadow diagnostics，不改变 runtime 行为。

### 功能要求

- 对肉鸽任务输出：
  - `task_goal_type=game_vertical_slice_delivery`
  - `task_domain=browser_game_development`
  - `core_deliverables` 包含 runnable game/source/assets。
  - `supporting_deliverables` 包含 stage docs/final report。
  - `required_verifications` 包含 dev server/browser/playability。
- 对单纯“创建 docs/tmp/test.md”仍输出文件写入类目标。

### 代码实现要求

新增：

- `backend/intent/task_goal_frame.py`
- `backend/intent/task_goal_interpreter.py`

修改：

- `backend/intent/__init__.py`
- `backend/agent_system/assembly/runtime_chain.py`

实现限制：

- 不允许直接删除旧 `TaskUnderstanding`。
- 不允许让 `TaskGoalFrame` 直接决定工具。
- 所有旧理解结果只能进入 `evidence.legacy_task_understanding`。

### 完成标准

- 新测试能读取 `TaskGoalFrame`。
- runtime trace 中能看到 shadow `task_goal_frame`。
- 主链路行为暂不改变，便于对照。

## 阶段三：任务域注册表与产品类任务域

### 任务细纲

1. 新增任务域 profile 注册表。
2. 把现有 task goal type 映射迁入 profile：
   - code fix
   - artifact delivery
   - material synthesis
   - runtime trace
   - regression test design
3. 新增产品开发类 profile：
   - `frontend_app_delivery`
   - `interactive_product_delivery`
   - `game_vertical_slice_delivery`
4. 新增查询 API 或内部 catalog builder，供配置页和任务系统 UI 后续展示。

### 功能要求

`game_vertical_slice_delivery` 必须定义：

- 核心交付：
  - 可运行游戏入口。
  - 游戏源码。
  - 至少一个视觉资源。
  - 玩法功能实现。
- 辅助交付：
  - 项目简报。
  - 玩法设计。
  - 技术设计。
  - 资产清单。
  - 最终报告。
- 必须能力：
  - workspace read/write。
  - terminal。
  - browser verification。
  - image generation 或 asset integration。
- 必须验证：
  - 启动项目。
  - 浏览器打开。
  - Canvas/DOM 非空。
  - 关键玩法验收。
  - 图片资源真实可见。

### 代码实现要求

新增：

- `backend/task_system/domains/__init__.py`
- `backend/task_system/domains/task_domain_profiles.py`
- `backend/task_system/domains/domain_registry.py`

修改：

- `backend/prompting/strategy_prototypes.py`
- `backend/prompting/professional_profiles.py`

实现限制：

- domain profile 的 prompt 必须是角色职责描述。
- 不允许把 runtime 节点、内部 operation id、调试术语写进 agent-facing prompt。
- 内置 profiles 必须可序列化，方便前端任务系统后续读取。

### 完成标准

- 注册表能按 `task_goal_type` 和 `domain_id` 查询。
- 旧 task goal type 的 strategy/profile 不回退。
- 肉鸽任务能匹配 `game_vertical_slice_delivery` profile。

## 阶段四：SemanticTaskContract 优先消费 TaskGoalFrame

### 任务细纲

1. 修改 `build_semantic_task_contract` 输入，支持 `task_goal_frame`。
2. 调整 `_resolve_task_goal_type`：
   - 优先使用 `TaskGoalFrame.task_goal_type`。
   - 其次使用显式 `current_turn_context.task_goal_type`。
   - 最后才使用旧关键词 fallback。
3. 交付物从 domain profile + task goal frame 合并生成。
4. material 收集逻辑区分输入材料、输出路径、辅助报告路径。

### 功能要求

- `final_report.md` 在肉鸽任务中必须是 supporting deliverable。
- semantic contract 必须保留用户的功能验收项。
- `task_goal_type=game_vertical_slice_delivery` 时，deliverables 不能退化为 `change_summary/changed_files`。

### 代码实现要求

修改：

- `backend/task_system/contracts/semantic_task_contracts.py`
- `backend/task_system/services/assembly_support.py`
- `backend/context_system/current_turn/current_turn.py`

新增测试：

- `backend/tests/semantic_task_goal_frame_contract_regression.py`

实现限制：

- 不允许直接把所有路径都当 material。
- 输出路径必须带 role：
  - `core_output`
  - `supporting_output`
  - `input_material`
  - `verification_artifact`
- 旧 fallback 必须保留，但 diagnostics 要明确 `source=legacy_fallback`。

### 完成标准

- 肉鸽样本 semantic contract 为 `game_vertical_slice_delivery`。
- 单纯创建 Markdown 文件仍为 `artifact_delivery` 或 bounded file write。
- code fix 样本仍为 `code_fix_execution`。

## 阶段五：ExecutionObligation 从合同反推资源与验证

### 任务细纲

1. 扩展 `build_execution_obligation`，支持 semantic contract/task goal frame 输入。
2. 对产品类任务生成结构化写入义务：
   - 源码变更。
   - 资源文件。
   - 文档产物。
3. 对产品类任务生成验证义务：
   - terminal 启动或构建。
   - browser 打开。
   - UI/Canvas 可见性检查。
   - 任务域功能 checklist。
4. 保留原文关键词抽取作为补充 evidence。

### 功能要求

肉鸽任务必须产生：

- `required_writes`：
  - `workspace_change`
  - `source_artifact`
  - `visual_asset`
  - `supporting_report`
- `required_commands`：
  - `dev_server_or_build`
- `required_verifications`：
  - `browser_open`
  - `visual_nonblank`
  - `gameplay_acceptance`
  - `asset_visible`

### 代码实现要求

修改：

- `backend/intent/execution_obligation.py`
- `backend/intent/obligation_models.py`
- `backend/task_system/services/assembly_support.py`

新增：

- `backend/intent/domain_obligation_builder.py`

实现限制：

- `_WRITE_MARKERS` 不能继续作为复杂任务是否写入的唯一依据。
- `_VERIFY_MARKERS` 不能继续作为是否需要验证的唯一依据。
- domain obligation 必须可测试、可序列化。

### 完成标准

- 肉鸽任务不再只得到泛化 `workspace_change`。
- “运行验证”类中文表达能触发验证义务。
- 没有验证证据时，专业运行时不能通过交付验收。

## 阶段六：Professional Runtime 生成任务域计划

### 任务细纲

1. 扩展 `_semantic_control_plan`，支持 domain profile plan template。
2. 为 `game_vertical_slice_delivery` 生成阶段计划：
   - 项目结构勘察。
   - 产品简报。
   - 玩法设计。
   - 技术设计。
   - 资产计划与生图提示词。
   - MVP 实现。
   - 资源接入。
   - 启动与浏览器验证。
   - 最终报告。
3. 每一阶段绑定 required operations。
4. 计划进入 ledger 和 trace，方便 UI 监控。

### 功能要求

- 阶段计划必须保留用户明确要求的阶段。
- 不能允许第一步直接写最终报告。
- 每个阶段必须有明确产物或观察。
- 如果某阶段失败，runtime 应要求追踪原因并继续修复，而不是直接总结。

### 代码实现要求

修改：

- `backend/runtime/professional_runtime/goal_contract.py`
- `backend/runtime/professional_runtime/driver.py`
- `backend/task_system/planning/execution_shape_resolver.py`

新增：

- `backend/runtime/professional_runtime/domain_plan_templates.py`

实现限制：

- 不允许把 domain plan 写死在 driver 大函数里。
- 模板必须独立可测试。
- required operations 必须使用已有 operation refs，不引入未注册工具名。

### 完成标准

- 肉鸽任务计划不再显示通用 `code_change_execution` 四步。
- trace 中能看到 domain-specific plan。
- 第一项副作用工具调用不应是写 `final_report.md`。

## 阶段七：任务域验收器与伪完成拦截

### 任务细纲

1. 新增 domain-aware validation。
2. 对最终回答做 claim-to-evidence 对齐。
3. 对产品类任务检查：
   - 文件观察。
   - 图片资源观察。
   - terminal 运行观察。
   - browser/visual 观察。
   - 功能 checklist 观察。
4. 对报告中声称的文件路径进行存在性和写入证据检查。

### 功能要求

肉鸽任务必须拦截以下伪完成：

- 声称 `index.html` 已创建，但无写入观察。
- 声称图片已生成，但无图片文件或生图工具观察。
- 声称浏览器验证通过，但无 browser/terminal 观察。
- 只验证 `final_report.md` 存在就声称游戏完成。

### 代码实现要求

修改：

- `backend/runtime/contracts/obligation_validation.py`
- `backend/runtime/contracts/deliverable_validator.py`

新增：

- `backend/runtime/contracts/domain_validators.py`
- `backend/runtime/contracts/claim_evidence_alignment.py`

实现限制：

- 不允许靠最终回答关键词通过验收。
- unsupported claims 必须进入 validation diagnostics。
- validator 不应该要求固定文件名，但必须要求对应类别证据。

### 完成标准

- 旧失败 trace 中的行为会被明确判定为缺少核心产物和验证证据。
- `partial_contract_failed` 的原因包含结构化缺失项，而不是只缺“测试/原因”这类词。

## 阶段八：模型驱动目标理解接入

### 任务细纲

1. 在 deterministic `TaskGoalFrame` 稳定后，引入模型目标理解。
2. 模型只输出固定 schema。
3. 系统用 domain registry 校验模型输出。
4. 如果模型输出未知类型，降级到 `generic_professional_task` 或 deterministic fallback。

### 功能要求

- 模型负责理解“用户真正要完成什么”。
- 系统负责校验类型、绑定流程、控制工具和验收。
- 模型不能凭空创造不可执行任务域。

### 代码实现要求

新增：

- `backend/intent/model_task_goal_interpreter.py`
- `backend/intent/task_goal_schema.py`

实现限制：

- 模型输出必须 JSON/schema validate。
- 未注册 `task_goal_type` 不得直接进入 runtime。
- prompt 必须要求区分 core/supporting deliverables。

### 完成标准

- 对复杂自然语言任务，模型理解结果优于纯关键词。
- 对短任务，模型路径可跳过，避免增加延迟。
- 模型失败时系统仍可 deterministic fallback。

## 阶段九：旧逻辑收口与迁移

### 任务细纲

1. 将 `TaskUnderstanding` 明确标记为 legacy signal layer。
2. 清理 semantic contract 中重复的关键词分支。
3. 将任务类型映射迁移到 domain registry。
4. 删除无用旧测试或改写为新结构测试。
5. 更新设计文档和调试输出。

### 功能要求

- 系统只有一个主任务裁决源：`TaskGoalFrame + TaskDomainProfile`。
- 旧规则只用于轻量工具路由和 evidence。
- 前端任务系统可以显示任务目标、任务域、核心交付、验证状态。

### 代码实现要求

修改或清理：

- `backend/understanding/task_understanding.py`
- `backend/task_system/contracts/semantic_task_contracts.py`
- `backend/intent/execution_obligation.py`
- 相关 regression tests

实现限制：

- 不保留无用旧残留。
- 不允许两套任务类型系统长期并行。
- 清理时必须保证 PDF、表格、知识库、实时查询路径不退化。

### 完成标准

- 新链路默认启用。
- legacy fallback 有明确边界。
- 任务理解 debug 输出能清楚显示：
  - goal frame source
  - matched domain
  - core deliverables
  - supporting deliverables
  - required capabilities
  - required verifications

## 6. 文件级执行清单

### 新增文件

- `backend/intent/task_goal_frame.py`
- `backend/intent/task_goal_interpreter.py`
- `backend/intent/model_task_goal_interpreter.py`
- `backend/intent/task_goal_schema.py`
- `backend/intent/domain_obligation_builder.py`
- `backend/task_system/domains/__init__.py`
- `backend/task_system/domains/task_domain_profiles.py`
- `backend/task_system/domains/domain_registry.py`
- `backend/runtime/professional_runtime/domain_plan_templates.py`
- `backend/runtime/contracts/domain_validators.py`
- `backend/runtime/contracts/claim_evidence_alignment.py`
- `backend/tests/task_goal_understanding_regression.py`
- `backend/tests/semantic_task_goal_frame_contract_regression.py`
- `backend/tests/domain_obligation_regression.py`
- `backend/tests/domain_validation_regression.py`

### 重点修改文件

- `backend/agent_system/assembly/runtime_chain.py`
- `backend/intent/__init__.py`
- `backend/intent/execution_obligation.py`
- `backend/intent/obligation_models.py`
- `backend/task_system/contracts/semantic_task_contracts.py`
- `backend/task_system/services/assembly_support.py`
- `backend/runtime/professional_runtime/goal_contract.py`
- `backend/runtime/professional_runtime/driver.py`
- `backend/runtime/contracts/obligation_validation.py`
- `backend/runtime/contracts/deliverable_validator.py`
- `backend/prompting/strategy_prototypes.py`
- `backend/prompting/professional_profiles.py`
- `backend/orchestration/interaction_mode_policy.py`

### 后续前端可接入文件

- 任务系统配置页读取 domain registry catalog。
- 任务运行监控页展示 goal frame、domain、core deliverables、verification obligations。

## 7. 验证矩阵

### 单元测试

必须覆盖：

- 目标理解分类。
- domain profile 匹配。
- semantic contract 生成。
- execution obligation 生成。
- domain plan template。
- domain validator。
- claim/evidence 对齐。

### 回归测试

必须覆盖：

- 肉鸽游戏长任务。
- 前端应用开发任务。
- 普通代码修复任务。
- 单文件写入任务。
- PDF 阅读任务。
- 表格分析任务。
- 实时查询任务。
- 任务图节点运行任务。

### 端到端测试

必须至少跑一条专业模式任务，确认：

- 不再首步写最终报告。
- 能生成 domain-specific plan。
- 无核心产物时验收失败。
- 有核心产物和验证证据时验收通过。

## 8. 风险与控制

### 风险一：模型理解不稳定

控制：

- 先做 deterministic shadow frame。
- 模型输出必须 schema validate。
- 未注册任务域不能进入 runtime。

### 风险二：轻量任务变慢

控制：

- 短问答、明确工具读取、PDF、表格、实时查询可以继续走轻量路径。
- 只有复杂任务、长任务、产品开发任务进入目标理解。

### 风险三：新旧系统并行导致混乱

控制：

- 阶段九必须清理旧裁决权。
- legacy 只能作为 evidence/fallback。
- diagnostics 必须标明 source。

### 风险四：domain profile 变成新 if/else

控制：

- 注册表单一来源。
- profile 数据化。
- plan template 独立模块。
- validator 独立模块。

## 9. 禁止事项

1. 禁止只给肉鸽样本加关键词特判。
2. 禁止只把 `final_report.md` 特判成非核心产物就收工。
3. 禁止把 runtime 节点说明写进 agent-facing prompt。
4. 禁止用最终回答关键词替代真实验收。
5. 禁止保留无用旧残留代码。
6. 禁止让模型自由创造未注册任务域。
7. 禁止在专业运行时 driver 中继续堆大段任务域 if/else。

## 10. 推荐实施顺序

推荐按以下顺序一次性推进到可用闭环：

1. 阶段一：测试基线。
2. 阶段二：TaskGoalFrame shadow。
3. 阶段三：Domain Registry。
4. 阶段四：SemanticTaskContract 接入。
5. 阶段五：ExecutionObligation 接入。
6. 阶段六：Professional Runtime domain plan。
7. 阶段七：Domain Validation。
8. 阶段八：模型目标理解。
9. 阶段九：旧逻辑收口。

最小可交付闭环是阶段一到阶段七。阶段八可以在 deterministic 版本稳定后再接入，避免一开始把模型不稳定性和结构重构混在一起。

## 11. 本次肉鸽实验修复后的期望结果

同样输入“开发浏览器端 2D 肉鸽游戏垂直切片”后，系统应产生：

```text
TaskGoalFrame:
  task_goal_type = game_vertical_slice_delivery
  task_domain = browser_game_development
  complexity = long_running
  core_deliverables = runnable_game, source_files, visual_asset, gameplay_features
  supporting_deliverables = stage_docs, final_report
  required_capabilities = workspace_read, workspace_write, terminal, browser, image_generation
  required_verifications = dev_server_run, browser_open, visual_nonblank, asset_visible, gameplay_acceptance

SemanticTaskContract:
  strategy_prototype_id = game_vertical_slice_delivery
  professional_profile_id = professional.game_vertical_slice_delivery
  deliverables = runnable_artifact_refs, gameplay_acceptance, visual_asset_refs, verification_evidence, final_report

Professional Plan:
  inspect_project
  write_brief
  design_gameplay
  design_technical_architecture
  plan_and_generate_assets
  implement_mvp
  integrate_assets
  run_and_verify_browser
  write_final_report

Validation:
  final_report alone cannot satisfy contract
```

这才符合用户真实任务，也符合项目现有设计原则中“工具合适就用、任务生命周期可追踪、事实和验证不伪造、结构服务执行”的方向。
