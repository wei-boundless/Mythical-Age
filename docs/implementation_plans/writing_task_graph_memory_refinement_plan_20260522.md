# 写作任务图与记忆库专业化重构实施计划

日期：2026-05-22

目标：按当前讨论的设计原则，修正模块化写作任务图与记忆库边界，使世界观、人设、剧情、细纲、正文、审核与记忆提交都能在通用编排系统内稳定运行，减少污染、减少噪声、保证可追踪和可持续维护。

## 1. 现状问题

1. 节点 prompt 虽然已有专业化方向，但部分职责边界仍不够锋利，容易让“设计”“审核”“提交”“整理”之间互相越权。
2. 世界观节点需要更明确地覆盖世界构成要素，不能只停留在概念层。
3. 记忆库层次已经有 baseline / mutable / issue_ledger / artifact_index，但运行时可见性与读取偏好还需要进一步显式化。
4. 章节写手、审核员、记忆管家需要不同的专业角色口径，不能混用开发说明。

## 2. 设计原则

1. 结构优先于措辞。
2. 设计、审核、提交、路由、整理各司其职。
3. baseline 只收已冻结事实，mutable 只收动态增量，issue_ledger 只收问题与裁决，artifact_index 只收引用。
4. 节点 prompt 必须是专业角色口径，不得写成开发注释。
5. 写手要有商业网文文风约束，但不能模仿具体作者的可识别风格。
6. 运行时只给节点看它真正需要的记忆层，隐藏视图要 fail closed。

## 3. 计划范围

### 3.1 任务图配置

- 强化 `world_design`、`world_review`、`memory_commit_world` 的职责边界。
- 强化 `character_design`、`plot_design`、`outline_design`、`chapter_outline`、`chapter_draft` 的专业口径。
- 强化 `memory_steward` 的提交职责，让它只做归档、固化、索引与版本控制，不替创作者扩写。
- 保留 review / commit 分层，不让候选、审核意见、动态提案直接变成 canon。

### 3.2 记忆库与运行时

- 明确 writing 任务可见的记忆层：baseline、mutable、issue_ledger、artifact_index、working_memory、task_durable_memory。
- 显式校验运行时 profile 对 `working_memory` 与 `task_durable_memory` 的可见性。
- 保持 memory_snapshot、revision_context、artifact_context 的 fail-closed 策略。

### 3.3 回归测试

- 检查世界观 prompt 是否覆盖地图/场域、历史、交换/货币、成长体系、原创机制等核心维度。
- 检查写手 prompt 是否明确为中文商业网文口径。
- 检查 memory_steward 是否只做基准提交与索引，不越权写作。
- 检查 writing runtime profile 是否保留必要的 memory 可见性。

## 4. 实施顺序

1. 更新 `scripts/configure_writing_modular_novel_graph.py` 中的节点 prompt 与记忆/上下文策略。
2. 更新 `backend/runtime/contracts/runtime_assembly_builder.py` 中的上下文别名或显式可见层策略，如有必要。
3. 更新 `backend/tests/writing_modular_novel_graph_config_regression.py` 与必要的运行时回归测试。
4. 重新生成受管 storage 配置。
5. 跑定向测试并修正失败项。

## 5. 完成标准

- 图配置能重新生成且通过回归测试。
- 世界观、角色、剧情、细纲、正文、审核、记忆提交的职责边界更清楚。
- 运行时对写作记忆层的可见性没有遗漏。
- 没有新增的兼容性赘肉或旧概念残留。

