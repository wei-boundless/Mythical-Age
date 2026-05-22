# 任务图编辑器通用底座重构计划

日期：2026-05-22

## 1. 问题判断

当前任务图系统已经有很多正确的局部能力：`TaskGraphDefinition`、标准视图、可组合图、记忆矩阵、运行语义、模板向导、预检器、图模块展开。

真正的问题不是缺少更多业务模板，而是这些能力没有被收束成统一的编辑器底座：

1. 前端模板是硬编码生成器，后端没有一等模板目录。
2. 模板只生成节点和边，没有统一声明结构层、角色槽位、记忆层、产物层、审核提交边界。
3. 记忆库系统已经能服务复杂任务，但模板没有把 baseline / mutable / artifact_index / issue_ledger 作为通用资源模式暴露。
4. 编辑器预检依赖散落字段推断，缺少模板级的基础约束。
5. 图模块、拓扑模板、前端模板、运行语义使用的语言不完全一致，导致编辑器更像配置页面，而不是可复用图构建系统。

## 2. 目标

把任务图编辑器的第一阶段底座做成可复用结构：

- 模板目录后端化：后端能描述可用模板、角色槽位、结构层、记忆模型和验证策略。
- 前端模板结构化：每个模板不仅生成节点和边，还生成 `editor_foundation` 元数据。
- 记忆库通用化：模板可声明标准记忆层，复杂任务默认有资源节点与读写边界。
- 预检更严格：能检查模板是否缺失角色职责、记忆资源、图模块接口和基础发布约束。
- 写作任务只作为高压样板，不成为专用后门。

## 3. 实施边界

本轮不重写整个编辑器 UI，不改运行时执行器主链，不把写作任务专用规则塞进通用后端。

补充硬边界：

1. 通用运行时不得内置 `chapter_draft`、`memory_commit_chapter`、`chapters_per_round` 这类业务节点或业务字段判断。
2. 批次、提交幂等、记忆提交来源、产物边界必须由图节点契约或运行协议声明，不能靠 runtime 猜业务。
3. 写作图可以继续使用“章、卷、正文”等业务配置，但这些词只能留在写作图定义、写作测试样例或专用质量门，不允许成为通用编辑器底座的默认逻辑。
4. 旧字段只有在它们是运行边界的通用兼容入口时才保留；如果只是某个任务的历史补丁，必须移出通用 runtime 或改成显式策略。

本轮落地四个基础件：

1. 新增后端 `task_system.editor.graph_template_catalog`。
2. 新增任务系统 API：`GET /tasks/task-graph-templates`。
3. 前端模板生成器补充通用 foundation 元数据与标准记忆资源模板。
4. 增加回归测试，保证模板目录、模板职责语言、记忆层和预检约束稳定。

追加第五个基础件：

5. 运行时业务去污染：把提交去重、批次边界提示、scope 坐标从写作硬编码改成通用策略读取。图任务要用这些能力时，必须在节点 `memory_writeback_policy`、`runtime_batch_boundary_policy` 或 loop/contract 输入里显式声明。

## 4. 验收标准

- 后端可返回通用任务图模板目录。
- 模板目录包含结构层、角色槽位、记忆层、产物层和验证策略。
- 前端生成的模板草稿包含 `editor_foundation`，而不是只有节点边。
- 长期项目循环模板能生成标准记忆资源，而不是把“记忆管理员”伪装成仓库。
- 回归测试覆盖模板目录和前端模板生成。
- `backend/runtime/coordination_runtime/runtime.py` 不再硬编码具体写作节点 id、章节产物 key 或章节批次字段。
- 通用批次提示能用 `unit_batch` 风格字段生成，写作图通过配置生成“章”语义，非写作图不会被章节语言污染。

## 5. 执行审查结论

本轮审查的关键判断：编辑器底座最危险的问题不是缺某个写作流程节点，而是通用 runtime / orchestration / permissions / agent_system 的边界会把具体业务概念、旧包路径和隐式兜底带进所有图任务。这样的系统表面可以跑一个任务，实际上不适合作为通用编辑器。

已确认并修复的结构问题：

1. 包级入口做了过重导入。
   `agent_system.__init__`、`permissions.__init__`、`orchestration.__init__` 以前会在导入一个模型或策略时拉起运行装配、资源视图、权限候选和 runtime 组件，造成循环依赖。现在统一改为懒导出表，包入口只负责导出协议，不负责初始化运行链路。

2. 写作节点名曾经污染通用运行时。
   `chapter_draft`、`memory_commit_chapter`、`chapters_per_round` 这类字段不能出现在通用 runtime / orchestration / memory_system 的默认逻辑里。现在批次边界、提交幂等、续跑清洗、质量门、产物路径都由节点契约或显式 policy 决定。

3. 产物路径渲染曾经替任务发明业务值。
   旧逻辑会默认生成 `chapter_001`、`第1卷`、`chapter_batch_size` 等写作语义，这对通用编辑器是错误的。现在产物路径只消费显式输入和通用派生值；写作图如果需要章节路径，必须由写作图 loop derived fields 产出。

4. 质量门曾经内置章节识别。
   旧逻辑会默认识别“第X章”“本批第X章至第Y章”，这是写作专用能力，不是通用能力。现在改成 `range_mention_patterns`、`range_declaration_keywords`、`unit_summary_template` 等显式策略。写作图继续有强章节审核，但它来自写作图契约，不来自底层默认。

5. 旧运行字段兼容兜底被清理。
   `committed_chapter_count`、`last_committed_chapter_index`、`chapter_word_receipts` 这类旧字段不再作为通用状态读取的兜底来源。通用项目进度只认 `committed_unit_count`、`last_committed_unit_index`、`metric_receipts` 等单位化字段。

6. 写作配置脚本仍有旧归属路径。
   `scripts/configure_writing_modular_novel_graph.py` 曾从 `orchestration.agent_registry` 等旧位置导入 agent/profile/model 配置。现在改为 `agent_system.*` 一等归属，不新增兼容假模块。

## 6. 已落地边界

- 通用底座只认识图、节点、边、契约、单位、批次、产物、记忆、权限、执行许可。
- 写作、章节、卷、正文、审核话术全部留在写作图配置、写作测试或专用质量策略里。
- 父子图/图模块运行只通过 graph module handle、handoff contract、input/output port 表达，不把父节点当 agent。
- 续跑清洗不再根据节点名推断行为，只读取 `replay_sanitization_policy`。
- 提交幂等不再根据 `memory_commit_chapter` 推断，只读取 `commit_identity_policy`。
- rejected 产物隔离目录使用通用 batch/round scope，不再默认生成 chapter scope。

## 7. 验证记录

已通过的定向验证：

- `python -m pytest backend/tests/task_graph_standard_models_test.py backend/tests/contract_compiler_coordination_test.py backend/tests/orchestration_runtime_spec_regression.py -q`
- `python -m pytest backend/tests/task_graph_template_catalog_regression.py backend/tests/task_system_api_regression.py::test_graph_module_core_artifact_refs_exclude_debug_reports backend/tests/agent_assembly_models_regression.py::test_work_order_to_assembly_and_permit_close_the_boundary -q`
- `python -m pytest backend/tests/langgraph_coordination_runtime_regression.py::test_stage_execution_message_declares_runtime_batch_boundary_over_stale_project_brief backend/tests/langgraph_coordination_runtime_regression.py::test_stage_execution_message_uses_generic_batch_boundary_without_domain_defaults backend/tests/langgraph_coordination_runtime_regression.py::test_formal_memory_commit_edge_uses_candidate_ref_and_verdict backend/tests/langgraph_coordination_runtime_regression.py::test_formal_memory_commit_edge_uses_approval_source_candidate_refs -q`
- `python -m pytest backend/tests/writing_modular_novel_graph_config_regression.py::test_modular_writing_graph_config_compiles_graph_modules_and_chapter_batches backend/tests/writing_modular_novel_graph_config_regression.py::test_modular_writing_review_and_commit_memory_boundaries backend/tests/writing_modular_novel_graph_config_regression.py::test_modular_writing_outline_threads_are_outline_owned_and_derived -q`
- `python -m pytest backend/tests/task_artifact_materializer_regression.py backend/tests/chapter_draft_quality_gate_regression.py backend/tests/length_budget_contract_regression.py -q`
- `cd frontend; npm test -- taskGraphTemplates.test.ts taskGraphPreflight.test.ts taskGraphTimeline.test.ts`

静态边界扫描：

- `rg -n "chapter_draft|memory_commit_chapter|chapters_per_round|chapter_batch_size|chapter_index|last_committed_chapter|committed_chapter|chapter_word|expected_chapter|found_chapter|missing_chapter" backend/orchestration backend/runtime backend/memory_system -S -g '!**/__pycache__/**'`
- 结果：通用运行链路无匹配。写作术语只保留在写作图配置和写作专用测试中。
