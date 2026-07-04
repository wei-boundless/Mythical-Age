# 项目控制网络与任务底座重构实施索引

状态：重构入口索引，作为后续实施的当前权威入口  
日期：2026-07-04  
适用范围：`graph_system`、`task_system`、`project_network_system`、`project_network_tasks`、`file_management`、`harness`、`capability_system/tools`

## 1. 本索引解决什么

这组文档已经从 Deep AST、项目语义网络、图任务审查、任务环境、成熟 agent 调研一路推进到任务框架定义。现在进入重构阶段，最危险的不是缺少想法，而是多个文档同时存在时实施权威混乱。

本文固定后续重构入口：

```text
先按本文确定阅读顺序和实施权威
再按 16 / 19 / 18 / 17 固定任务底座
再按 13 / 14 固定系统边界和图任务运行底座
再按 10 / 11 / 12 固定项目控制网络资产与维护闭环
最后按 01-08 / 04 / 06 落地 AST 与语义审查生产线
```

## 2. 当前重构总目标

目标不是给旧逻辑再包一层，而是把权威关系整理干净：

```text
Harness = 单 agent 执行权威
TaskSystem = 持久任务环境与 episode 推进权威
GraphSystem = 图结构、图时空、算法调度和 work order 权威
RuntimeEffectRegistry = 图算法副作用请求到领域 handler 的薄路由
ProjectNetworkSystem = 项目控制网络资产、语义产物、generation 与维护信号权威
ProjectNetworkTasks = 依托图任务建立/修复项目网络的任务适配层
FileManagement = 文件树、AST、物理事实和资源引用权威
CapabilitySystem/Tools = 对 agent 暴露工具能力的统一门面
PromptLibrary = agent 可执行契约权威
```

核心不变量：

- `GraphSystem` 不执行模型，不保存项目语义资产。
- `RuntimeEffectRegistry` 只按 `effect_kind` 路由副作用，不做领域语义判断。
- `ProjectNetworkSystem` 不调度 agent，不拥有图运行循环。
- `TaskSystem` 不保存项目网络领域资产，不成为旧 `project_network` 仓库。
- `ProjectNetworkTasks` 只承载项目网络建立/修复的图任务适配、模板、上下文 provider。
- `Harness` 仍是唯一单 agent runtime，不新增第二套模型 loop。
- `Harness` 不直接 import `project_network_tasks` 或 `project_network_system`，领域副作用通过 runtime effect handler 注册。
- `FileManagement` 只给物理事实、AST、资源 ref，不做语义判断。
- `Agent` 给出判断、意图、证据和产物候选；`System` 做持久化、调度、校验、归并和发布。

### 2.1 历史路径说明

早期设计文档中会出现 `backend/task_system/project_network`。该路径只代表当时的源码位置，不再代表当前实施权威。

当前重构后的权威路径是：

```text
project_network_system = 项目网络资产、store、service、generation、repair queue
project_network_tasks = 项目网络建立/修复的图任务模板、adapter、context provider
task_system = 持久任务环境，不保存项目网络领域资产
```

后续实施、import、CLI、工具注册和 runtime effect 都必须使用当前权威路径。历史文档中的旧路径只能作为“迁移前证据”，不能作为新增代码的引用目标。

## 3. 必读文档顺序

### 3.1 当前实施主链

| 顺序 | 文档 | 作用 |
| --- | --- | --- |
| 1 | `16_unified_agent_task_project_control_overall_plan.md` | 总体目标架构，固定 harness / task / graph / project network / file management 的分层 |
| 2 | `19_task_framework_canonical_definition_and_agent_system_contract.md` | 固定 Task、Plan、Todo、Episode、WorkProduct，以及 agent/system 推进协议 |
| 3 | `18_task_environment_runtime_mechanics_plan.md` | 固定任务环境存储、事件、snapshot、lease、checkpoint、reducer、query、repair |
| 4 | `17_task_graph_runtime_interface_detail_alignment.md` | 固定任务环境与图节点运行接口，尤其 GraphNodeTaskBinding / NodeResultEnvelope |
| 5 | `13_graph_task_task_system_file_system_boundary_optimization_plan.md` | 固定 graph/task/file/project network 边界和代码迁移方向 |
| 6 | `14_graph_task_spacetime_runtime_architecture_plan.md` | 固定图任务的时空运行体系、checkpoint、resume、fork、repair 语义 |
| 7 | `10_project_control_system_three_layer_network_contract_rewrite_plan.md` | 固定物理层、语义层、agent 神经控制层的三层网络 |
| 8 | `11_deep_index_repair_and_maintenance_unification_plan.md` | 固定深度索引、断链修复和维护同源闭环 |
| 9 | `12_apix_project_network_status_and_optimization_report.md` | 记录 Apix 实测问题，作为项目控制网络成熟度验收参照 |

### 3.2 背景和设计来源

| 文档 | 用途 |
| --- | --- |
| `01_principles_and_architecture.md` | 最初的成熟 agent 对齐原则、上下文和工具面边界 |
| `02_deep_ast_spine_plan.md` | Deep AST spine、symbol、binding、call/dataflow 的物理骨架方案 |
| `03_project_semantic_graph_model.md` | Semantic File Module、语义层和控制 route |
| `05_graph_task_project_network_capability_expansion_plan.md` | 项目网络建立对图系统的通用承载能力要求 |
| `07_skeleton_graph_and_semantic_overlay_plan.md` | 系统结构网络 + agent 语义 overlay 的双层建图裁决 |
| `08_project_semantic_review_workflow.md` | 项目级语义审查的分层工作流和产物模板 |
| `09_graph_algorithm_adapter_tree_reduce_architecture.md` | Tree Reduce 作为审查图算法适配器的裁决 |
| `06_network_crawler_index_and_review_plan.md` | 项目网络爬行、frontier、edge review 和 deep locate 操作层 |
| `04_graph_task_review_network.md` | 早期审查图方案，后续只作为生产线设计来源，不作为最终系统边界权威 |

### 3.3 外部成熟 agent 参照

| 文档 | 用途 |
| --- | --- |
| `agent_source_audits/00_turn_session_task_reference_synthesis.md` | Codex / Claude Code / OpenCode / Dify / Hermes / Pi 等调研汇总 |
| `agent_source_audits/01_openai_codex_turn_task_mechanism_audit.md` | Codex 的 turn/session/runtime 边界参照 |
| `agent_source_audits/02_claude_code_nb_turn_task_mechanism_audit.md` | Claude Code 相关任务与上下文机制参照 |
| `agent_source_audits/08_hermes_agent_gateway_kanban_task_environment_mechanism_audit.md` | Hermes 网关、看板、任务环境参照 |
| `agent_source_audits/09_pi_agent_harness_session_runtime_mechanism_audit.md` | Pi agent harness/session/runtime 参照 |

## 4. 重构实施阶段

### Phase 0：文档权威和索引整理

目标：

- 建立当前实施入口。
- 确认哪些文档是主链，哪些是背景来源。
- 固定后续代码重构不得违反的分层权威。

完成标准：

- README 指向本文。
- `agent_source_audits` 有独立索引。
- 每个实施阶段都能追溯到对应权威文档。

### Phase 1：项目网络代码搬家与边界收口

目标：

```text
task_system.project_network -> project_network_system + project_network_tasks
```

原则：

- 资产模型、仓库、service、generation、repair queue 归 `project_network_system`。
- 图任务模板、runtime adapter、context provider、shard planner 归 `project_network_tasks`。
- `task_system` 不再保存 project network 领域代码。
- 删除旧 `task_system.project_network` 主链，不保留兼容入口。

完成标准：

- 运行路径不再 import `task_system.project_network`。
- project network 工具通过统一工具注册暴露能力。
- CLI / harness / graph runtime 引用新包。

### Phase 2：GraphSystem 算法与上下文扩展收口

目标：

- `GraphSystem` 只负责图结构、状态、checkpoint、work order、algorithm adapter。
- 项目网络 tree reduce 作为 graph algorithm adapter，不塞进 GraphLoop 内部。
- context provider 通过 registry 接入，不在 GraphLoop 中硬编码领域上下文。
- runtime effect handler 通过 registry 接入，不在 HarnessRuntimeFacade 中硬编码领域副作用。

完成标准：

- `GraphLoop` 不出现项目网络领域判断。
- runtime adapter 和 context provider 可以按任务类型注册。
- harness effect sink 只调用 `graph_system.runtime_effect_registry`，项目网络 ingest handler 位于 `project_network_tasks.runtime_effects`。
- ready work order 的并发和恢复仍由 graph / task runtime 控制，不由领域代码私自开线程。

### Phase 3：任务环境底座实施准备

目标：

- 根据 19 / 18 / 17 固定 TaskFramework 的最小接口和数据模型。
- 明确 TaskAdmissionService、TaskScheduler、TaskContextBuilder、HarnessBridge、TaskReducer 的实现位置。

完成标准：

- 有可落地的模块目录和接口清单。
- GraphNodeWorkOrder 到 TaskWorkEnvironment 的桥接点明确。
- 普通 session task 与 graph node task 走同一 episode/reducer 主链。

### Phase 4：项目控制网络深度索引和维护闭环

目标：

- 统一物理网络和语义网络，不再把两者做成割裂产物。
- 建立 deep locate、semantic coordinates、signal chain audit、layer report、repair task 同源闭环。

完成标准：

- root report 供人看。
- 每层 layer report 供审查和汇总。
- semantic coordinates 供 agent 定位。
- signal chain audit 供 agent 快速理解链路。
- repair task 能从断线或 git delta 发起。

### Phase 5：审查图生产线接入任务环境

目标：

- 审查图不直接执行 agent，而是通过 task environment 承载每个节点。
- 文件/目录/系统级审查都形成 WorkProduct。
- Tree Reduce 只处理结构化子结果回传和汇总。

完成标准：

- 文件级产物、目录级产物、根级汇总产物分层保存。
- Agent 契约是可执行角色合同，不是开发说明。
- 图节点输出通过 NodeResultEnvelope 回到 GraphLoop。

## 5. 权威链检查表

每次动代码前检查：

| 问题 | 正确答案 |
| --- | --- |
| 谁执行模型？ | `Harness` |
| 谁拥有任务真相？ | `TaskWorkEnvironment / TaskStore` |
| 谁推进任务状态？ | `TaskReducer` |
| 谁决定图节点 ready？ | `GraphSystem / GraphLoop / algorithm adapter` |
| 谁保存项目网络资产？ | `ProjectNetworkSystem` |
| 谁处理图算法领域副作用？ | `RuntimeEffectRegistry` 路由，领域 handler 在对应 task adapter 包 |
| 谁提供文件和 AST 物理事实？ | `FileManagement` |
| 谁把能力暴露给 agent？ | `CapabilitySystem/Tools` |
| 谁写 agent 契约？ | `PromptLibrary / task contract template` |
| 谁发布项目网络 generation？ | `ProjectNetworkSystem curator / service` |
| 谁能让 graph node 完成？ | `NodeResultEnvelope` 被 GraphLoop 接受 |

如果一个模块开始跨层回答多个问题，就必须拆开。

## 6. 严禁保留的旧链路

后续重构不允许为了“兼容”保留这些主链：

- `task_system.project_network` 作为项目网络资产主包。
- GraphLoop 内部硬编码项目网络审查语义。
- project network service 直接调 agent 或 graph loop。
- graph task executor 直接绕过 harness 执行模型。
- session transcript 作为 task truth。
- assistant final answer 作为唯一 WorkProduct。
- 自然语言报告反解析为结构事实。
- 旧测试保护已经废弃的包路径或内部形状。

允许短暂存在的迁移痕迹必须满足：

```text
有明确删除条件
不作为运行主链
不吞错误
不改变行为
不让新代码继续依赖旧入口
```

## 7. 后续代码重构的最小验证

本项目不通过新增回归测试文件来制造安全感。重构验证以真实链路和静态一致性为主：

```text
python -m compileall <changed_backend_files_or_packages>
rg -n "from task_system\\.project_network|import task_system\\.project_network|task_system/project_network" backend -g "*.py"
rg -n "project_network_system|project_network_tasks" backend
python -m backend.cli.main <existing relevant command>
```

涉及前后端或运行链路时，必须固定端口实测：

```text
frontend: http://127.0.0.1:3000
backend:  http://127.0.0.1:8003
```

不允许为了通过验证：

- 跳过核心路径；
- 伪造产物；
- 降低断言；
- mock 掉真实执行；
- 保留旧路径做暗兜底。

## 8. 当前执行建议

下一步代码重构建议从 Phase 1 开始：

```text
1. 检查所有 task_system.project_network 引用是否已经迁移。
2. 确认 project_network_system 只保存资产和服务，不调度 agent。
3. 确认 project_network_tasks 只保存图任务适配和模板。
4. 清理旧包和旧 import。
5. 编译相关后端文件。
6. 用 CLI 路径真实跑一次 project network 轻量命令。
```

完成 Phase 1 后，再进入 GraphSystem adapter/context provider 收口；不要同时开始 TaskFramework 的完整存储层，否则改动面会过大，状态不容易稳定。
