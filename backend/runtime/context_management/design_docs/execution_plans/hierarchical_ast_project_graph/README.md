# Deep AST 项目语义空间分层文档索引

状态：设计拆分稿，待审阅后实施  
日期：2026-07-01  
入口来源：`../hierarchical_ast_project_graph_engineering_feasibility_plan_20260701.md`

## 0. 当前重构入口

后续重构以 [00_refactor_execution_index.md](00_refactor_execution_index.md) 为当前入口。  
它负责把这组文档整理成实施权威：哪些是任务底座主链，哪些是 graph/project network 边界，哪些是 AST/语义图背景方案，哪些只是成熟 agent 调研参照。

最重要的执行裁决：

```text
Harness = 单 agent 执行权威
TaskSystem = 持久任务环境与 episode 推进权威
GraphSystem = 图结构、图时空、算法调度和 work order 权威
ProjectNetworkSystem = 项目控制网络资产、语义产物、generation 与维护信号权威
ProjectNetworkTasks = 依托图任务建立/修复项目网络的任务适配层
FileManagement = 文件树、AST、物理事实和资源引用权威
```

历史文档里出现的 `backend/task_system/project_network` 只代表迁移前源码位置。当前实现应使用 `project_network_system` 和 `project_network_tasks`，不能再把旧路径作为新增代码入口。

## 1. 文档分层

这组文档把原来的长计划书拆成可实施的多层文档。当前阅读和实现应按这个顺序推进：

```text
00 重构实施入口索引
-> 16 Agent 任务系统与项目控制网络总体规划
-> 19 任务框架稳定定义与 Agent/System 对接契约
-> 18 任务环境运行机制实施细节方案
-> 17 任务环境与图任务运行接口细节对接方案
-> 13 图任务 / 任务系统 / 文件系统边界优化方案
-> 14 图任务时空运行体系架构计划
-> 10 项目控制系统三层网络与契约重写计划
-> 11 深度索引修复与同源维护统一计划
-> 12 Apix 项目网络实测状态与优化技术报告
-> 01 原则 / 原理 / 总体架构
-> 02 Deep AST 树深化方案
-> 03 项目图语义模型设计方案
-> 05 图任务系统项目网络建立承载能力扩展方案
-> 07 系统结构网络与语义网络双层建图计划
-> 08 项目级语义审查工作流设计
-> 09 图任务算法适配器与 Tree Reduce 架构裁决
-> 15 单 Agent 持久任务工作环境底座整合计划
-> 06 项目网络级索引与爬行审查计划
-> 04 图任务审查网络建立方案
```

| 文档 | 职责 | 不能承担的职责 |
| --- | --- | --- |
| `00_refactor_execution_index.md` | 作为当前重构实施入口，固定阅读顺序、实施阶段、系统权威链、旧链路清理标准和最小验证方式 | 不替代各细节文档，不直接设计新接口字段，不允许被当成宽泛原则备忘录 |
| `01_principles_and_architecture.md` | 锁定设计原则、成熟 agent 对齐标准、总体架构和上下文边界 | 不展开 AST schema 细节 |
| `02_deep_ast_spine_plan.md` | 设计 Deep AST spine、symbol/binding/call/dataflow、刷新生命周期 | 不让模型决定硬事实 |
| `03_project_semantic_graph_model.md` | 设计 Semantic File Module、系统层、endpoint、control route 和 agent 交互 | 不负责多 agent 生产线 |
| `05_graph_task_project_network_capability_expansion_plan.md` | 先扩展图任务系统，让它承载项目网络建立的层级计划、语义分片、work product、资源平面、generation 生命周期和状态投影 | 不把图系统改造成审查专用系统 |
| `07_skeleton_graph_and_semantic_overlay_plan.md` | 设计系统确定性抽取 Skeleton Graph、图任务 agent 建立 Semantic Overlay 的双层建网架构 | 不把语义判断写进系统抽取器，不让 agent 伪造结构事实 |
| `08_project_semantic_review_workflow.md` | 固定项目级语义审查工作流、共享状态、单层审查微流程、单文件模块审查模板和自下而上汇总规则 | 不定义新的 graph core，不替代 05 的承载能力和 07 的物理/语义分层 |
| `09_graph_algorithm_adapter_tree_reduce_architecture.md` | 固定图任务算法适配器架构：写作图是循环迭代，审查图是 tree_reduce；旧 render 收缩为 tree materialization | 不把项目网络业务逻辑塞进 GraphLoop，不保留独立渲染调度路径 |
| `10_project_control_system_three_layer_network_contract_rewrite_plan.md` | 固定项目控制系统三层网络、契约重写、根目录报告、语义坐标、深度定位索引、信号链路索引和神经控制工具边界 | 不替代物理骨架抽取，不把信号链路和定位网络混成一个产物 |
| `11_deep_index_repair_and_maintenance_unification_plan.md` | 固定深度索引修复、断点检测、repair 发起、同源维护闭环和控制桥补网方案 | 不另起平行补网系统，不让 repair 绕开现有 maintenance / generation / curator 主链 |
| `12_apix_project_network_status_and_optimization_report.md` | 记录 Apix 大项目实测后的功能现状、问题点、成熟度判断和下一步工程技术方案 | 不替代 11 的修复计划，不直接定义新的图任务调度机制 |
| `13_graph_task_task_system_file_system_boundary_optimization_plan.md` | 固定 graph_system、task_system、file_management、project_network_system、project_network_tasks 的职责边界和迁移计划 | 不直接搬代码，不把旧 `task_system.project_network` 作为长期兼容壳 |
| `14_graph_task_spacetime_runtime_architecture_plan.md` | 设计图任务时空运行体系：空间坐标、时间坐标、时空坐标、timeline、checkpoint、resume、fork、repair 的统一运行底座 | 不推翻当前 GraphLoop，不把领域任务逻辑重新塞进 graph_system |
| `15_persistent_task_work_environment_spine_plan.md` | 把“任务需要环境支持、agent 是智能输入输出体”的裁决下沉到单 agent 任务系统，设计 TaskWorkEnvironment、TaskContextPackage、TaskMemorySpace、AgentExecutionEpisode 和 WorkProduct | 不把任务压扁成函数形式，不新增第二套 agent runtime，不让 task_system 或 graph_system 直接执行模型循环 |
| `16_unified_agent_task_project_control_overall_plan.md` | 汇总现有源码、成熟 agent 调研和 13-15 号规划，锁定单 agent 持久任务环境、图任务时空调度、项目控制网络、repair/maintenance 的总体目标架构和分阶段实施路线 | 不直接实施代码，不跳过任务环境底座去接回旧 TaskRun executor |
| `17_task_graph_runtime_interface_detail_alignment.md` | 把 16 号总体架构下压到接口细节，固定 TaskExecutionRequest、TaskEnvironmentLease、TaskContextPackage、AgentExecutionEpisode、WorkProduct、GraphNodeTaskBinding、NodeResultEnvelope 的身份、生命周期、字段边界和迁移切口 | 不新增抽象原则，不把旧 TaskRun/AgentRun/GraphNodeWorkOrder 直接解释成新的任务真相，不让旧 task_executor 回流 |
| `18_task_environment_runtime_mechanics_plan.md` | 把任务环境落到可实现的运行机制，固定 SQLite canonical store、事件账本、snapshot、query index、lease/heartbeat、pause/stop/resume、checkpoint、reducer、graph binding、dead letter/repair 和验证矩阵 | 不停留在概念解释，不用单 JSON 或 session transcript 承担任务真相，不跳过幂等、并发和恢复边界 |
| `19_task_framework_canonical_definition_and_agent_system_contract.md` | 固定任务框架的稳定定义，明确 Task 的核心要素、Plan/Todo 的任务内归属、agent 与 system 推动任务的工程协议、session/task/graph/project network 的关系、状态机、调度、reducer 和最小接口 | 不重复运行机制细节，不把 plan/todo 等同 task，不让 agent 直接改 task state，不让系统替 agent 做语义判断 |
| `agent_source_audits/` | 记录 Codex、Claude Code、OpenCode、OpenClaw、Dify、Hermes、Pi 等成熟 agent 源码审查，沉淀 turn/session/task/run/work product 的工程边界，并由目录 README 维护调研索引 | 不直接替代本项目设计文档，不把参考系统照搬成本项目架构 |
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

- [00_refactor_execution_index.md](00_refactor_execution_index.md)
- [01_principles_and_architecture.md](01_principles_and_architecture.md)
- [02_deep_ast_spine_plan.md](02_deep_ast_spine_plan.md)
- [03_project_semantic_graph_model.md](03_project_semantic_graph_model.md)
- [05_graph_task_project_network_capability_expansion_plan.md](05_graph_task_project_network_capability_expansion_plan.md)
- [07_skeleton_graph_and_semantic_overlay_plan.md](07_skeleton_graph_and_semantic_overlay_plan.md)
- [08_project_semantic_review_workflow.md](08_project_semantic_review_workflow.md)
- [09_graph_algorithm_adapter_tree_reduce_architecture.md](09_graph_algorithm_adapter_tree_reduce_architecture.md)
- [10_project_control_system_three_layer_network_contract_rewrite_plan.md](10_project_control_system_three_layer_network_contract_rewrite_plan.md)
- [11_deep_index_repair_and_maintenance_unification_plan.md](11_deep_index_repair_and_maintenance_unification_plan.md)
- [12_apix_project_network_status_and_optimization_report.md](12_apix_project_network_status_and_optimization_report.md)
- [13_graph_task_task_system_file_system_boundary_optimization_plan.md](13_graph_task_task_system_file_system_boundary_optimization_plan.md)
- [14_graph_task_spacetime_runtime_architecture_plan.md](14_graph_task_spacetime_runtime_architecture_plan.md)
- [15_persistent_task_work_environment_spine_plan.md](15_persistent_task_work_environment_spine_plan.md)
- [16_unified_agent_task_project_control_overall_plan.md](16_unified_agent_task_project_control_overall_plan.md)
- [17_task_graph_runtime_interface_detail_alignment.md](17_task_graph_runtime_interface_detail_alignment.md)
- [18_task_environment_runtime_mechanics_plan.md](18_task_environment_runtime_mechanics_plan.md)
- [19_task_framework_canonical_definition_and_agent_system_contract.md](19_task_framework_canonical_definition_and_agent_system_contract.md)
- [agent_source_audits/README.md](agent_source_audits/README.md)
- [agent_source_audits/00_turn_session_task_reference_synthesis.md](agent_source_audits/00_turn_session_task_reference_synthesis.md)
- [06_network_crawler_index_and_review_plan.md](06_network_crawler_index_and_review_plan.md)
- [04_graph_task_review_network.md](04_graph_task_review_network.md)
