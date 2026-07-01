# 层级化 Deep AST 项目语义空间工程计划书索引

状态：已拆分为多层文档，待审阅后实施  
日期：2026-07-01  
拆分目录：`hierarchical_ast_project_graph/`

## 1. 拆分原因

原计划书同时承载了原则、总体架构、Deep AST、Semantic File Module、控制协议、图任务审查网络和实施预算，文件过大，不利于审查和后续执行。

现在改为带索引的多层文档：

```text
hierarchical_ast_project_graph/
  README.md
  01_principles_and_architecture.md
  02_deep_ast_spine_plan.md
  03_project_semantic_graph_model.md
  05_graph_task_project_network_capability_expansion_plan.md
  04_graph_task_review_network.md
```

## 2. 阅读顺序

1. [README.md](hierarchical_ast_project_graph/README.md)
2. [01_principles_and_architecture.md](hierarchical_ast_project_graph/01_principles_and_architecture.md)
3. [02_deep_ast_spine_plan.md](hierarchical_ast_project_graph/02_deep_ast_spine_plan.md)
4. [03_project_semantic_graph_model.md](hierarchical_ast_project_graph/03_project_semantic_graph_model.md)
5. [05_graph_task_project_network_capability_expansion_plan.md](hierarchical_ast_project_graph/05_graph_task_project_network_capability_expansion_plan.md)
6. [04_graph_task_review_network.md](hierarchical_ast_project_graph/04_graph_task_review_network.md)

## 3. 核心裁决

```text
Deep AST Spine = 结构骨架和审查权威
Semantic File Module = agent 与系统对齐的基本读取单位
Semantic Control Graph = 控制神经系统
Class / Function / Parameter / Call Site = 控制末梢
Project Network Build Capability = 图系统承载项目网络建立的通用能力
Graph Task Review Network = 多 coding agent 建网和互审生产线实例
```

## 4. 实施主线

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

## 5. 不变边界

- 硬事实来自 AST、registry、tool catalog、API route、文件 hash 和 exact read。
- 语义图只做导航和控制，不替代 AST。
- agent 先进入 `Semantic File Module`，再进入 AST endpoints。
- 多 coding agent 图任务只能输出 proposal。
- 语义图审查网络必须先依托图任务系统的项目网络建立承载能力；审查只是节点工作姿态。
- 发布必须经过 AST Control Curator。
