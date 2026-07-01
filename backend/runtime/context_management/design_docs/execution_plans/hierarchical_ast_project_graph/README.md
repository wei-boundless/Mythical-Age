# Deep AST 项目语义空间分层文档索引

状态：设计拆分稿，待审阅后实施  
日期：2026-07-01  
入口来源：`../hierarchical_ast_project_graph_engineering_feasibility_plan_20260701.md`

## 1. 文档分层

这组文档把原来的长计划书拆成五层。阅读和实现都应按这个顺序推进：

```text
01 原则 / 原理 / 总体架构
-> 02 Deep AST 树深化方案
-> 03 项目图语义模型设计方案
-> 05 图任务系统项目网络建立承载能力扩展方案
-> 07 系统结构网络与语义网络双层建图计划
-> 06 项目网络级索引与爬行审查计划
-> 04 图任务审查网络建立方案
```

| 文档 | 职责 | 不能承担的职责 |
| --- | --- | --- |
| `01_principles_and_architecture.md` | 锁定设计原则、成熟 agent 对齐标准、总体架构和上下文边界 | 不展开 AST schema 细节 |
| `02_deep_ast_spine_plan.md` | 设计 Deep AST spine、symbol/binding/call/dataflow、刷新生命周期 | 不让模型决定硬事实 |
| `03_project_semantic_graph_model.md` | 设计 Semantic File Module、系统层、endpoint、control route 和 agent 交互 | 不负责多 agent 生产线 |
| `05_graph_task_project_network_capability_expansion_plan.md` | 先扩展图任务系统，让它承载项目网络建立的层级计划、语义分片、work product、资源平面、generation 生命周期和状态投影 | 不把图系统改造成审查专用系统 |
| `07_skeleton_graph_and_semantic_overlay_plan.md` | 设计系统确定性抽取 Skeleton Graph、图任务 agent 建立 Semantic Overlay 的双层建网架构 | 不把语义判断写进系统抽取器，不让 agent 伪造结构事实 |
| `06_network_crawler_index_and_review_plan.md` | 设计可爬行 Project Network Index、frontier、crawler session、edge review 和 agent 网络操作接口 | 不替代 Deep AST，不直接发布最终 generation |
| `04_graph_task_review_network.md` | 设计 graph task / TaskRun / 多 coding agent 审查建网流程 | 不直接定义 AST 抽取细节，不绕过 05 的通用承载能力 |

## 2. 总裁决

本系统不是“更复杂的搜索工具”。目标是建立一个 AST-first 的项目语义空间：

```text
Deep AST Spine = 结构骨架和审查权威
Skeleton Graph = 系统确定性抽取的项目结构网络
Semantic File Module = agent 与系统对齐的基本读取单位
Semantic Control Graph = 控制神经系统
Class / Function / Parameter / Call Site = 控制末梢
Project Network Build Capability = 图系统承载项目网络建立的通用能力
Project Network Index / Crawler = agent 顺着项目网络爬行、审边、补图的操作层
Graph Task Review Network = 多 coding agent 建网和互审生产线实例
```

硬边界：

- 硬事实来自 AST、registry、tool catalog、API route、文件 hash 和 exact read。
- 语义图只负责导航、关系解释和控制路由，不替代 AST 骨架。
- agent 的基本读取入口是单文件 `Semantic File Module`，不是裸文件、散乱行窗口或孤立函数。
- 函数、class、参数、call site 是模块内部控制末梢。
- 图任务系统必须先具备项目网络建立的通用承载能力，再承载多 coding agent 审查建网实例。
- 审查只是部分节点的 `work_posture`，不是图系统形态。
- 每一层审查后必须有汇总节点；汇总结果可写入图任务记忆库，作为下一层分片依据。
- 记忆库保存 proposal 和 layer summary，最终语义图只由 Project Semantic Space Store 的 generation 发布。
- 发布必须经过 AST Control Curator 校验。
- 图任务推进必须复用现有 `TaskGraphDefinition -> ExecutableGraphConfig -> GraphRuntime -> GraphLoop -> WorkOrder -> NodeResult` 链路，不另写平行调度器。

## 3. 实施依赖

推荐实施顺序：

```text
Phase 1 Deep AST Spine MVP
Phase 2 Semantic File Module Builder
Phase 3 AST Control Command Plane
Phase 4 Coding Agent 适配
Phase 5 Project Network Build Capability
Phase 6 Graph Task Semantic Build
Phase 7 Domain Extractors
Phase 8 Lifecycle / Context Projection
Phase 9 Model Annotation / Review Agents
Phase 10 Frontend Control Trace
Phase 11 验证与清理
```

最低可用闭环：

```text
Deep AST Spine
-> Semantic File Module
-> project_graph control session
-> required read windows
-> read_file exact evidence
-> edit / verify / refresh
```

## 4. 文档链接

- [01_principles_and_architecture.md](01_principles_and_architecture.md)
- [02_deep_ast_spine_plan.md](02_deep_ast_spine_plan.md)
- [03_project_semantic_graph_model.md](03_project_semantic_graph_model.md)
- [05_graph_task_project_network_capability_expansion_plan.md](05_graph_task_project_network_capability_expansion_plan.md)
- [07_skeleton_graph_and_semantic_overlay_plan.md](07_skeleton_graph_and_semantic_overlay_plan.md)
- [06_network_crawler_index_and_review_plan.md](06_network_crawler_index_and_review_plan.md)
- [04_graph_task_review_network.md](04_graph_task_review_network.md)
