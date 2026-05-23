# Prompt Library 实时重构计划

日期：2026-05-23

## 目标

先把 prompt 从散落字段迁入一个可查询、可追踪、可被运行时消费的 Prompt Library，然后逐步重构提示词装配系统。

本轮最小闭环：

1. 建立 `PromptResource` 数据模型和 `PromptLibraryRegistry`。
2. 将任务图 workflow prompt 迁移为 `stage_role` prompt resource。
3. 运行时节点专业职责优先读取 Prompt Library。
4. Prompt manifest 标记 prompt resource 来源。
5. 原有 workflow prompt 和 legacy projection id 只作为迁移 source/ref，不作为任务图 prompt 主路径。

## 第一阶段实现细纲

### 1. 数据层

新增 `backend/prompt_library/`：

- `models.py`：定义 `PromptResource` 和查询条件。
- `registry.py`：读取/写入 `storage/prompt_library/prompt_resources.json`。

资源字段要求：

- `resource_id`
- `resource_type`
- `title`
- `content`
- `workflow_id`
- `task_id`
- `graph_id`
- `node_id`
- `cache_scope`
- `model_visible`
- `source_ref`
- `legacy_projection_ids`
- `metadata`

### 2. 迁移层

从 `TaskWorkflowRegistry.list_workflows()` 读取所有带 `prompt` 的 workflow。

迁移规则：

- `workflow.prompt` -> `resource_type=stage_role`
- `workflow.workflow_id` -> `workflow_id`
- `workflow.metadata.node_id` -> `node_id`
- `workflow.metadata.domain_id/task_family` -> metadata
- `workflow.compatible_projection_ids` 和旧 projection binding -> `legacy_projection_ids`

### 3. 运行时接入

修改 `runtime_bundle_builder.py`：

- 构建 `node_professional_prompt_section` 时先查 Prompt Library。
- 找到资源时，正文来自 `PromptResource.content`。
- contract metadata 记录 `node_professional_prompt_resource`。
- 未找到资源时，才回退 workflow prompt / registered task metadata。

修改 `soul/runtime_assembly.py`：

- `node_professional_prompt_section` 的 manifest source 改为 `prompt_library_resource`。
- `source_id/source_refs/cache_scope` 来自 prompt resource。

### 4. API 迁移入口

任务图 API 中旧 `role_prompt` metadata 不再迁入 projection card，而是迁入 Prompt Library resource。

### 5. 验证

新增或更新测试：

- Prompt Library 能从写作任务图 workflow 生成 `stage_role` 资源。
- 世界观节点运行时模型可见 prompt 来自 prompt resource。
- 旧 API prompt metadata 迁移到 Prompt Library，而不是 projection card。

## 后续阶段

第二阶段再把 `task_section/workflow_section/semantic_task_section/mode_policy_section/output_section` 全部改为 `PromptAssembler` 统一装配，删除运行时大函数里的模型可见拼接。

## 第二阶段增量：流程感知动态装配

用户新增要求：动态装配不能只按角色、任务域或当前问题选择 prompt，必须显式考虑任务流程。当前阶段先实现可运行闭环，不一次性改写整个 runtime 状态机。

### 任务细纲

1. 扩展 `PromptSelectionContext`：
   - 记录 `workflow_id/workflow_title`。
   - 记录任务图节点的 `graph_id/node_id/stage_id/phase_id`。
   - 记录单 agent 或专业模式的 `current_step_id/current_step_kind/current_step_title/current_step_index`。
   - 记录 `workflow_steps/recipe_steps/step_sequence`。
   - 标记 `task_graph_node_runtime` 和 `process_kind`。
2. 新增 `PromptSelector`：
   - 输入 `PromptSelectionContext` 和 `PromptResource` 列表。
   - 输出 `PromptAssemblyPlan`。
   - `stage_role` 选择优先级必须是：`workflow_id` 精确匹配 > `task_id` 精确匹配 > `graph_id/node_id/stage_id` 精确匹配 > `current_step_id/current_step_kind` 匹配 > 任务域/模式通用资源。
   - `role_prompt` 只能进入 `role_mode`，不能进入 `standard_mode` 或 `professional_mode`。
3. 接入 `assemble_runtime_prompt_contract()`：
   - 从 `task_workflow`、`selected_recipe.step_blueprints`、`registered_task` 和 `current_turn_context` 生成选择上下文。
   - `node_professional_prompt_section` 优先使用 selector 选中的 `stage_role` resource。
   - contract metadata 写入 `prompt_selection_context` 和 `prompt_assembly_plan`。
4. 更新 runtime manifest：
   - `node_professional_prompt_section` 的 source 信息来自装配计划。
   - 模型可见内容仍必须是职责语言，不输出 workflow id、内部 task mode、resource id。

### 功能要求

- 写作任务图节点必须按当前节点/工作流拿到对应的专业职责 prompt。
- 单 agent 任务虽然暂时不必可视化成图，但装配上下文必须能表达当前 step 序列和当前 step。
- generic/domain prompt 不能覆盖更具体的 workflow/node/stage prompt。
- Prompt 选择过程必须可追踪，便于前端配置页后续预览“为什么装配了这些 prompt”。

### 代码实现要求

新增：

- `backend/prompt_library/selector.py`
- `backend/tests/prompt_library_selector_regression.py`

修改：

- `backend/prompt_library/models.py`
- `backend/prompt_library/assembler.py`
- `backend/prompt_library/runtime_sections.py`
- `backend/prompt_library/registry.py`
- `backend/prompt_library/__init__.py`
- `backend/agent_system/assembly/runtime_bundle_builder.py`
