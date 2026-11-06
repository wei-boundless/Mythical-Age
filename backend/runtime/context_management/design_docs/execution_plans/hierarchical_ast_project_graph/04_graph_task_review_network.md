# 图任务审查网络建立方案

状态：设计稿，待审阅后实施  
日期：2026-07-01

前置依赖：必须先完成 `05_graph_task_project_network_capability_expansion_plan.md` 中的图任务系统项目网络建立承载能力扩展。本文件是语义图审查网络实例方案，不应绕过项目网络建立合同、层级计划、语义分片、work product、资源平面、generation 生命周期和状态投影能力直接实施。审查只是本实例中部分节点的工作姿态，不是图系统的专用形态。

## 1. 核心方向

项目语义网络不应由单个建模 agent 一次性生成。正确方向是把“建网”做成 graph task / TaskRun：由任务合同发起，多名 coding agent 按分层任务图审查、构建、互校，最终由 curator 发布。

```text
Project Semantic Network Build Task
-> TaskRun Contract
-> Graph Task Plan
-> System-Level Review Nodes
-> System Aggregation Node
-> System Layer Memory Commit
-> Folder-Level Review Nodes
-> Folder Aggregation Node
-> Folder Layer Memory Commit
-> Semantic File Module Review Nodes
-> Module Aggregation Node
-> Module Layer Memory Commit
-> File-Internal AST Review Nodes
-> Endpoint Aggregation Node
-> Endpoint Layer Memory Commit
-> Cross-Level Relation Review Nodes
-> Relation Aggregation Node
-> Proposal Store
-> AST Control Curator
-> Published Semantic Network Generation
```

本项目可复用基础：

- `backend/cli/main.py` 的 `task-run start --contract-file`。
- `backend/task_system/compiler/node_contract_models.py` 的 node contract。
- `backend/graph_system/*` 的图运行、调度、resume、supervisor。
- `backend/capability_system/tools/tool_units/subagent_control_tool.py` 的 subagent 生命周期概念。

源码对齐后的真实机制：

```text
TaskGraphDefinition
-> graph_compiler.build_graph_compilation_unit
-> node_contract_index / edge_contract_index / graph_binding_contract
-> ExecutableGraphConfig
-> GraphRuntime.start
-> GraphLoop.initialize
-> SchedulerView / GraphReadinessEvaluator
-> GraphContextMaterializer.build_work_order
-> GraphNodeWorkOrderExecutor
-> NodeResultEnvelope
-> GraphTransitionProcessor
-> GraphLoop.accept_node_result
-> next ready work orders / terminal GraphResultEnvelope
```

对应源码职责：

| 层 | 关键源码 | 职责 |
| --- | --- | --- |
| 图定义 | `task_system/graphs/task_graph_models.py` | 定义 `TaskGraphDefinition`、node、edge、wait/join/failure policy |
| 默认协调图 | `task_system/services/graph_task_registry.py` | 在无显式 graph nodes 时生成 coordinator + participant 双向边 |
| 图编译 | `task_system/compiler/graph_compiler.py` | 生成 node/edge/resource contract 与 deployment package |
| 节点契约 | `task_system/compiler/node_contract_models.py` | 为每个节点生成 input/output/prompt/runtime/tool/permission/session contract |
| 边契约 | `task_system/compiler/edge_contract_models.py` | 定义 edge protocol、flow packet、readiness、human control、failure |
| 运行配置 | `graph_system/models.py` | `ExecutableGraphConfig` 锁定已发布图结构、hash、contracts |
| 启动 | `graph_system/runtime.py` | 创建 `TaskRun`、`GraphRun`、`GraphRuntimeEnvelope` |
| 推进 | `graph_system/loop.py` | 初始化状态、派发 ready 节点、接收 node result、推进边和状态 |
| 就绪判定 | `graph_system/scheduler_view.py` / `readiness_evaluator.py` | 从依赖边、wait policy、join policy 决定 ready nodes |
| 工作单 | `graph_system/context_materializer.py` | 把节点和上游包组装成 `GraphNodeWorkOrder` 与 execution slot |
| 节点执行 | `graph_system/work_order_executor.py` | 执行 agent work order 并转成 `NodeResultEnvelope` |
| 结果传播 | `graph_system/transition_processor.py` | 根据 node result 更新 outgoing edge state 和 flow packet |
| 循环运行 | `graph_system/runner.py` / `resume.py` | run-until-idle、checkpoint resume、blocked/recoverable 处理 |

因此我们的语义建网不应绕开现有 graph runtime。`project_graph_build` 应生成或选择一个已发布的 `ExecutableGraphConfig`，再让 `GraphSystem` 按状态机推进。

核心裁决：

- 图任务本身必须搭建任务图，而不是发起一批松散 subagent。
- 图中的一个 node 先按一个单 agent 执行席位理解；多 agent 协作由多个 nodes、edges、aggregation nodes 和 curator publish 组成。
- 每个任务节点都必须有 node contract 和 agent contract。
- 每个任务边都必须有 edge contract，明确是否产生 flow packet、如何等待上游、失败如何传播。
- 每个 coding agent 都可以是“审查 agent”，差异只在审查层级、输入材料和输出 schema。
- 每一层都必须有 aggregation node，把多个审查 agent 的 proposal 合并成层级共识。
- 每一层汇总后可以通过 memory commit 写入图任务记忆库，供下一层读取。
- agent 不直接“写图”，只按契约输出标准化 graph proposal。
- 项目语义网络按项目层级构建：系统层 -> 文件夹层 -> 文件模块层 -> 文件内部 AST 层 -> 跨层关系层。

## 2. 图任务总合同

每个建网任务必须从合同开始：

```json
{
  "task_kind": "project_semantic_network_build",
  "user_visible_goal": "为 prompt/runtime/tool 链路构建项目语义网络。",
  "scope": {
    "systems": ["prompt_system", "tool_runtime"],
    "roots": ["backend/prompt_library", "backend/prompt_composition"],
    "module_refs": [],
    "max_files_per_agent": 12
  },
  "required_inputs": {
    "deep_ast_generation": "gen:...",
    "semantic_file_module_refs": [],
    "evidence_pack_refs": []
  },
  "agent_contract": {
    "role": "semantic_file_module_reviewer",
    "must_read": ["assigned semantic file modules", "required evidence windows"],
    "must_output": ["module proposal", "endpoint annotations", "edge candidates", "conflicts"],
    "forbidden": ["invent files or symbols", "write final graph", "edit source code"]
  },
  "output_contract": {
    "schema": "project_graph.semantic_proposal.v1",
    "evidence_required": true,
    "confidence_allowed": ["derived", "hypothesis", "rejected", "needs_human_review"]
  }
}
```

合同必须锁住：

- scope。
- 输入 evidence。
- agent role。
- 输出 schema。
- 禁止事项。
- 失败处理。

## 3. 任务节点契约

图任务不是“给 agent 一段说明”，而是每个节点都有可执行契约：

```json
{
  "node_id": "system_boundary_review:prompt_system",
  "node_type": "agent",
  "title": "Prompt system boundary review",
  "agent_id": "agent:semantic_graph_reviewer",
  "agent_selection_policy": "explicit_agent",
  "execution_mode": "parallel",
  "wait_policy": "wait_all_upstream_completed",
  "join_policy": "all_success",
  "executor": {
    "executor_type": "agent"
  },
  "contract_bindings": {
    "schema": {
      "input_contract_id": "project_graph.system_review_input.v1",
      "output_contract_id": "project_graph.layered_review_proposal.v1"
    },
    "execution": {
      "node_contract_id": "node-contract:semantic_graph_review",
      "receipt_required": true
    },
    "semantic": {
      "review_level": "system",
      "proposal_kinds": ["system_node", "folder_ownership", "conflict"]
    }
  },
  "prompt": {
    "role": "你是一名项目语义图审查员。你只审查 assigned_scope 内的代码结构，并输出标准化图 proposal。",
    "must": "你必须基于输入证据和必要 read_file 结果判断，为每个系统、文件夹、模块、endpoint 标明 evidence_ref。",
    "must_not": "你不能发明文件、目录、符号或函数，不能直接写 Project Semantic Space Store，不能编辑源码。"
  },
  "metadata": {
    "review_level": "system",
    "assigned_scope": {
      "system_refs": ["system:prompt_system"],
      "folder_refs": ["folder:backend/prompt_library"],
      "module_refs": [],
      "ast_anchor_refs": []
    },
    "required_refs": ["deep_ast_generation", "file_tree_snapshot", "parent_proposal_refs"],
    "required_reads": ["semantic module envelopes", "required evidence windows"],
    "forbidden_inputs": ["full project dump", "unbounded repository scan"]
  }
}
```

每个节点的输出必须包含：

```text
proposal_id
review_level
assigned_scope
accepted_candidates
rejected_candidates
needs_human_review
evidence_refs
confidence
downstream_shard_hints
```

`downstream_shard_hints` 很重要：上一层审查结果要指导下一层任务图怎么展开，而不是每一层重新盲扫项目。

节点设计规则：

- `node_type` 首版使用 `agent`；需要汇总、发布、路由的节点也可以先由 agent 执行，后续再替换为 deterministic executor。
- `executor.executor_type` 对 agent 审查节点使用 `agent`，这样 `GraphNodeWorkOrderExecutor` 会走 harness 回调。
- `wait_policy` / `join_policy` 必须按任务图语义设置：并行审查后汇总节点通常用 `wait_all_upstream_completed + allow_partial_with_issues` 或 `quorum`。
- `contract_bindings.schema` 必须声明输入/输出合同，不能只靠 prompt 约定。
- `prompt` 必须写成 agent 可执行角色契约，不写开发说明。
- `metadata.assigned_scope` 是分片边界，必须来自系统层、文件夹层、Semantic File Module 或 AST anchor。

边设计规则：

- 普通上游交付边用 `edge_type=handoff` 或默认 `node_handoff`。
- 审查反馈边用 `edge_type=review_feedback`，可进入 conflict/revision 路径。
- 汇总 barrier 可用 `edge_type=barrier` / `join` 语义，或通过目标节点 `join_policy` 表达。
- 高风险系统边界发布前需要 human control edge，让 `GraphLoop` 进入 `waiting_human_gate` 或 human edge decision。
- 边要让 `edge_contract_models.py` 能推导 protocol kind、packet、readiness、failure 和 human control。

## 4. 分层任务图

图任务按项目层级展开：

```text
Layer 0: Deterministic Foundation
  file tree / file hash / Deep AST spine / registry facts

Layer 1: System Classification Review
  审查项目由哪些 functional systems 组成。

Layer 2: System Aggregation
  汇总多个 agent 的系统分级 proposal，形成候选系统图，写 system_layer_summary_memory。

Layer 3: Folder Index Review
  读取 system_layer_summary_memory，对每个系统建立文件夹级索引和语义说明。

Layer 4: Folder Aggregation
  汇总 folder proposal，形成 folder_index_summary_memory。

Layer 5: System File Scan
  读取 folder_index_summary_memory，每个系统分别扫描，建立 Semantic File Module 索引和语义说明。

Layer 6: Module Aggregation
  汇总 module proposal，形成 module_layer_summary_memory。

Layer 7: File-Internal AST Review
  读取 module_layer_summary_memory，在单文件模块内根据 AST 树建立 class/function/parameter/call-site 索引。

Layer 8: Endpoint Aggregation
  汇总 endpoint proposal，形成 endpoint_layer_summary_memory。

Layer 9: Relation Trace Review
  顺着 import/call/registry/router/tool/prompt refs 建立跨模块关系。

Layer 10: Relation Aggregation
  汇总 control route proposal，形成 relation_layer_summary_memory。

Layer 11: Conflict Cross Review
  复核系统归属、模块职责、endpoint、route 的冲突。

Layer 12: Curator Publish
  校验 anchor、合并 proposal、发布 generation。
```

这是“神经系统控制项目”的建网方式：

```text
Project
-> Functional Systems
-> System Folders
-> Semantic File Modules
-> File-Internal AST Endpoints
-> Cross-Level Control Routes
-> Project Management / Agent Control
```

文件和 AST 树是指引方向：系统层告诉 agent 先进入哪个功能系统，文件夹层告诉 agent 进入哪个维护区域，Semantic File Module 告诉 agent 单文件职责和 public surface，AST endpoint 告诉 agent 真正可控制的函数、class、参数和调用点。

## 5. 任务图推进规则

现有 `graph_system` 的推进核心是 node state + edge state：

```text
start nodes ready
-> dispatch ready nodes into GraphNodeWorkOrder
-> agent executor returns NodeResultEnvelope
-> GraphTransitionProcessor updates outgoing edge states
-> GraphReadinessEvaluator checks target inbound edge states
-> next nodes ready / blocked / waiting_human_gate / completed
```

我们的审查任务图应按这个机制设计：

```text
deterministic_foundation
  start node。生成 file tree、Deep AST generation、registry facts。

system_classification_review[*]
  多个并行 agent 节点。等待 deterministic_foundation 的 handoff edge ready。

system_aggregation
  汇总节点。join_policy=allow_partial_with_issues 或 quorum；输入是多个 system proposal flow packets。

folder_index_review[*]
  按 system_aggregation 输出的 system/folder shard hints 动态或预生成分片。

folder_aggregation
  汇总 folder_index proposal，形成系统内 folder map。

semantic_file_module_review[*]
  按 folder map 分片审查单文件模块。

file_internal_ast_review[*]
  按 module_refs 分片审查 endpoint。

relation_trace_review[*]
  按 module/endpoint/registry refs 建立跨层 control routes。

conflict_cross_review
  接收全部 proposal refs 和冲突，输出 accept/reject/needs_human_review 建议。

curator_publish
  deterministic 或强约束 agent 节点。只有通过 anchor 校验的 proposal 才进入 publish candidate。
```

推进策略：

- 层内并行：同一层 review nodes 可以并行，受 `control.max_active_nodes` 限制。
- 层间阻塞：下一层必须等上一层汇总节点完成，不能让文件级审查绕过系统/文件夹索引。
- 部分可用：大项目允许 `allow_partial_with_issues`，但输出必须标明缺口和未覆盖 scope。
- 返修：review result 中出现 rejected / revise verdict 时，revision edge 把任务路由回对应上游节点。
- 人工门：系统边界合并、删除大量边、发布 generation 这些节点必须允许 human gate。
- 恢复：任务图依赖 checkpoint；中断后由 `GraphResumeService` 恢复 active work orders 或重新 dispatch ready nodes。

`GraphLoop` 的真实推进点要求我们不要在 `project_graph_build` 里自己写一套调度器。`project_graph_build` 只应该：

```text
plan:
  生成 TaskGraphDefinition / ExecutableGraphConfig 草案。

start:
  发布或选择 ExecutableGraphConfig，调用 GraphSystem.start_run。

status:
  读取 GraphLoopState、semantic_graph_task_runs、semantic_graph_task_shards。

review:
  对 proposal refs 做 curator/human review。

publish:
  通过 curator 后发布 Project Semantic Space generation。
```

## 6. 汇总节点与记忆库

多 agent 审查如果没有汇总节点，会变成 proposal 碎片堆。每一层必须有正式 aggregation node：

```text
review agents
-> aggregation node
-> memory write candidate
-> memory commit
-> next layer shard planning
```

汇总节点职责：

```text
输入：
  同层多个审查 agent 的 proposal refs
  上一层 Layer Summary Memory
  当前 AST / file / registry hard facts

输出：
  accepted candidates
  rejected candidates
  conflict set
  next layer shard plan
  memory write candidates
```

三类存储必须分清：

```text
Proposal Memory:
  保存各 agent 原始审查 proposal、证据、拒绝理由、冲突。

Layer Summary Memory:
  保存每一层汇总节点形成的当前层候选共识，用于下一层任务分片和上下文输入。

Project Semantic Space Store:
  保存最终发布后的语义图 generation。
```

记忆库只承载过程态和阶段态，不能替代最终图数据库。未经过 Curator 的 proposal 和 layer summary 不能进入主查询 generation。

可复用现有任务图节点类型：

```text
memory_read:
  下一层审查节点读取上一层 layer summary。

memory_write_candidate:
  汇总节点提出写入候选。

memory_handoff:
  把阶段性共识交给下游审查层。

memory_commit:
  将 aggregation 输出正式写入图任务记忆库。

memory_repository / working_memory_store:
  保存 graph task scope 内的 proposal memory 和 layer summary memory。
```

层级汇总建议：

```text
system_review_agents
-> system_aggregation_node
-> system_memory_commit

folder_review_agents
-> folder_aggregation_node
-> folder_memory_commit

semantic_file_module_review_agents
-> module_aggregation_node
-> module_memory_commit

ast_endpoint_review_agents
-> endpoint_aggregation_node
-> endpoint_memory_commit

relation_trace_agents
-> relation_aggregation_node
-> conflict_review_node
-> curator_publish_node
```

汇总节点不能只做文本摘要。它必须输出可机器消费的 layer summary：

```json
{
  "layer_summary_kind": "system_layer_summary",
  "semantic_task_run_id": "semantic_task:...",
  "source_proposal_refs": [],
  "accepted_refs": [],
  "rejected_refs": [],
  "conflict_refs": [],
  "coverage": {
    "covered_scope_refs": [],
    "uncovered_scope_refs": []
  },
  "next_layer_shards": [],
  "memory_commit_policy": "graph_task_scoped"
}
```

裁决：

```text
审查 agent 负责分片判断；
汇总节点负责层级共识；
记忆库负责过程态和阶段态；
Curator 负责最终发布。
```

## 7. 多 Coding Agent 分工

```text
System Classification Review Agent:
  审查系统边界、owned folders、entrypoints、跨系统关系。

Folder Index Review Agent:
  对系统内文件夹建立 folder index、职责说明、入口文件、风险点和下游扫描建议。

Semantic File Module Review Agent:
  建立 module summary、public surface、internal endpoints、module read profile。

AST Endpoint Auditor Agent:
  审查 class/function/parameter/call-site 是否真实可控。

Relation Trace Agent:
  从 import/call/registry/router/tool/prompt refs 追踪跨模块边。

Conflict Review Agent:
  查找系统归属冲突、edge 证据不足、stale hash、模型过度解释。

Curator / Publisher:
  只做 schema 校验、AST anchor 校验、冲突裁决和 generation 发布。
```

每个 agent 都是审查 agent。它们不负责“创造架构”，只负责在自己层级内根据证据审查、标注、拒绝或提出候选关系。每个 agent 都必须拿独立任务合同和有限 evidence pack，不能继承主对话全部上下文。

## 8. 建网流程

```text
0. deterministic_index
   刷新 Deep AST spine，生成 semantic_file_modules 和 endpoint hard facts。

1. project_level_shard_planning
   读取文件树、registry、router、tool catalog、prompt registry 和顶层目录，生成系统分级审查节点。

2. system_classification_review
   多个审查 agent 独立提出 functional systems、owned folders、entrypoints、跨系统关系。

3. system_aggregation
   汇总系统分级 proposal，建立候选系统图；输出 system_layer_summary memory write candidate。

4. system_memory_commit
   将 system_layer_summary 写入图任务记忆库，作为 folder_index_review 的输入。

5. folder_index_review
   对每个系统建立文件夹级索引和语义说明，输出 folder_index proposal。

6. folder_aggregation
   汇总 folder proposal，输出 folder_index_summary memory write candidate。

7. folder_memory_commit
   写入 folder_index_summary，作为 system_file_scan 的输入。

8. system_file_scan
   每个系统分别扫描，建立 Semantic File Module 索引和语义说明。

9. module_aggregation
   汇总 module proposal，输出 module_layer_summary memory write candidate。

10. module_memory_commit
   写入 module_layer_summary，作为 file_internal_ast_review 的输入。

11. file_internal_ast_review
   以单文件模块为边界，根据 Deep AST 建立 class/function/parameter/call-site endpoint proposal。

12. endpoint_aggregation
   汇总 endpoint proposal，输出 endpoint_layer_summary memory write candidate。

13. endpoint_memory_commit
   写入 endpoint_layer_summary，作为 relation_trace_build 的输入。

14. relation_trace_build
   追踪跨模块关系，生成 control_routes / semantic_edges 候选。

15. relation_aggregation
   汇总 relation proposal，输出 relation_layer_summary。

16. conflict_cross_review
   不同 agent 对系统、文件夹、模块、endpoint、route 进行交叉复核。

17. curator_normalize
   只接受能回指 AST/registry/tool/API anchor 的 proposal。

18. publish_generation
   发布新的 semantic network generation。

19. management_projection
   输出系统 overview、模块责任、风险点、维护面和可控路径。
```

## 9. 标准化图输出

每层任务都输出同一种标准化图 proposal，只是 `review_level` 不同。

系统层输出：

```text
functional_system nodes
system responsibility
owned folders
entrypoints
system relations
conflicts
```

文件夹层输出：

```text
folder_ref
owned_by_system
folder_role
child folders
key files
scan_priority
downstream module shards
```

文件模块层输出：

```text
semantic_file_module
module_summary
public_surface
internal_endpoints
upstream/downstream edges
module_read_profile
required_read_windows
```

文件内部 AST 层输出：

```text
class/function/parameter/call_site endpoints
anchor_ref
line range
control_capabilities
side_effect candidates
verify_scope hints
```

关系层输出：

```text
control_route
source_ref
target_endpoint_id
route_kind
edge_refs
required_read_windows
confidence
freshness
```

## 10. 存储表

`semantic_graph_task_runs`：

```text
semantic_task_run_id TEXT PRIMARY KEY
task_run_id TEXT
task_contract_ref TEXT
graph_config_id TEXT
graph_run_id TEXT
graph_structure_hash TEXT
task_kind TEXT
scope_json TEXT
input_generation_id TEXT
output_generation_id TEXT
status TEXT
agent_run_refs_json TEXT
proposal_refs_json TEXT
created_at REAL
updated_at REAL
```

`semantic_graph_task_shards`：

```text
shard_id TEXT PRIMARY KEY
semantic_task_run_id TEXT
graph_run_id TEXT
node_id TEXT
work_order_id TEXT
shard_kind TEXT
assigned_agent_profile TEXT
module_refs_json TEXT
system_refs_json TEXT
evidence_pack_refs_json TEXT
input_contract_json TEXT
output_contract_json TEXT
status TEXT
agent_run_ref TEXT
node_result_ref TEXT
proposal_refs_json TEXT
created_at REAL
updated_at REAL
```

约束：

- shard 必须有 input/output contract。
- shard 范围必须落到 `semantic_file_module` 或 system refs。
- agent 输出只能进入 `graph_proposals`。
- 未发布任务不得改变主查询 generation。
- `semantic_graph_task_runs.graph_run_id` 必须能追到 `GraphLoopState`。
- `semantic_graph_task_shards.node_id/work_order_id/node_result_ref` 必须能追到 graph runtime 的节点执行、结果和上游 flow packet。

`semantic_graph_layer_summaries`：

```text
layer_summary_id TEXT PRIMARY KEY
semantic_task_run_id TEXT
graph_run_id TEXT
layer_kind TEXT              # system | folder | module | endpoint | relation | conflict
aggregation_node_id TEXT
source_proposal_refs_json TEXT
accepted_refs_json TEXT
rejected_refs_json TEXT
conflict_refs_json TEXT
covered_scope_refs_json TEXT
uncovered_scope_refs_json TEXT
next_layer_shards_json TEXT
memory_candidate_ref TEXT
memory_commit_ref TEXT
status TEXT                  # candidate | committed | rejected | superseded
created_at REAL
updated_at REAL
```

约束：

- 每个 aggregation node 至少输出一个 layer summary candidate。
- 进入下一层审查前，上一层 layer summary 必须是 `committed` 或明确允许 `allow_partial_with_issues`。
- `memory_commit_ref` 指向图任务记忆库提交记录，不指向最终 Project Semantic Space generation。
- Curator 发布时可以读取 layer summaries，但不能把 layer summary 原文直接当最终图事实。

## 11. project_graph_build

语义网络建设由独立工具入口控制：

```text
project_graph_build
  action: plan | start | status | review | publish | cancel
  build_mode: bootstrap | incremental | review | correction | management_audit
```

默认行为：

- 只写 runtime graph task state。
- 默认产出 draft proposal。
- 默认不自动发布。
- 高风险系统边界变更必须人工审查。

## 12. 项目管理输出

发布后的网络服务项目管理：

- 系统 ownership overview。
- 模块职责、public surface、维护风险。
- 改动影响面和验证范围。
- 架构漂移、重复链路、无人维护模块。
- agent 失败诊断：搜索失败、模块语义错、endpoint 错、route 错。

这让语义网络不仅帮助搜索，也成为项目管理和 agent 控制的基础设施。

## 13. 审查专用 Agent 组配置

审查专用 agent 组的配置原则是：运行能力尽量统一，审查契约按节点差异化。不要为系统层、文件夹层、模块层、endpoint 层各复制一套工具权限；真正的差异应落在 `prompt_contract`、`assigned_scope`、`input_contract_id`、`output_contract_id`、`memory_*_policy`、`edge payload_contract_id` 和 layer summary 输出 schema 上。

源码接线点：

| 配置层 | 真实字段 / 源码 | 作用 |
| --- | --- | --- |
| agent 运行 profile | `agent_system/profiles/runtime_profile_models.py::AgentRuntimeProfile` | 限制工具、记忆、上下文段、approval、trace、prompt set、模型配置 |
| worker prompt / prompt set | `prompt_library/worker_prompts.py`、`prompt_library/prompt_sets.py` | 定义基础 worker work role；审查图需要新增语义图审查基础 prompt |
| graph node 定义 | `task_system/graphs/task_graph_models.py::TaskGraphNodeDefinition` | 定义 `agent_id`、`agent_group_id`、执行模式、合同、记忆策略、metadata |
| graph config 发布 | `task_system/compiler/executable_graph_config_publisher.py::_node_config` | `metadata.agent_profile_id` / `metadata.agent_profile_ref` 会投影成发布后节点的 `agent_profile_id` |
| node contract 编译 | `task_system/compiler/node_contract_models.py::build_node_contract` | 把 prompt、runtime、tool、permission、session、memory contract 编进 node contract |
| work order 生成 | `graph_system/context_materializer.py::build_work_order` | work order 真正携带 `agent_id`、`agent_profile_id`、`message`、`expected_result_contract` |
| graph node 执行 | `harness/entrypoint/runtime_facade.py::execute_graph_agent_work_order` | 创建 graph node task run，并按 work order 的 profile 解析 agent runtime profile |
| graph node prompt wiring | `harness/runtime/graph_node_contract.py` | graph node 使用 `runtime.pack.graph_node_execution`，普通环境/personality/project prompt 对节点隐藏 |

关键接线约束：

- 首版节点必须显式设置 `agent_id`，并在 `metadata.agent_profile_id` 或 `metadata.agent_profile_ref` 中设置可解析的 profile id。
- `agent_group_id` 可作为组织和分片配置，但当前 work order 执行不直接用它解析 profile；不能只填 group 不填可执行 agent。
- 节点 prompt 必须放在 `metadata.prompt_contract` 或标准 node `prompt` 中，最终变成 work order message 和 `TaskRunContract.prompt_contract`。
- 普通主 agent 的环境/personality prompt 不会自动进入 graph node；审查节点契约必须自足。
- 如果需要专门 graph coordinator profile，发布器需要把 `coordinator_agent_profile_id` 投影到 `ExecutableGraphConfig.agents`；当前 publisher 只投影 `coordinator_agent_id` 和 `agent_group_id`。

### 13.1 基础运行配置

建议新增一个基础审查 profile，所有分片审查节点默认共用：

```text
agent_id: agent:semantic_graph_reviewer
agent_profile_id: semantic_graph_review_agent
lifecycle_policy: system_builtin 或 graph_task_managed
approval_policy: read_only_first
trace_policy: runtime_event_log
prompt_set_refs:
  - prompt_set.worker.semantic_graph_review
allowed_context_sections:
  - task
  - projection
  - tool
  - runtime_contracts
  - upstream_outputs
  - artifact_refs
allowed_memory_scopes:
  - graph_task_readonly
  - layer_summary_readonly
extra_allowed_operations:
  - op.model_response
  - op.read_file
  - op.search_files
  - op.search_text
  - op.glob_paths
  - op.list_dir
  - op.stat_path
  - op.path_exists
  - op.python_code_outline
  - op.python_symbol_search
  - op.git_status
  - op.git_diff
  - op.git_show
blocked_operations:
  - op.write_file
  - op.edit_file
  - op.shell
  - op.python_repl
  - op.web_search
  - op.fetch_url
  - op.memory_write_candidate
```

这个 profile 是“审查员的身体”，不是“审查员的岗位”。岗位差异不能塞进 runtime profile；岗位差异必须由 graph node contract 表达。

基础 worker prompt 建议新增：

```text
你是一名项目语义图审查员。
你只负责在 assigned_scope 内审查项目结构、代码事实、AST anchor、模块职责和候选关系。
你必须基于输入证据、Deep AST hard facts、文件树、registry facts 和必要的只读文件窗口做判断。
你不能修改源码、不能发布最终语义图、不能把推测写成事实、不能绕过缺失证据。
你需要把每个接受、拒绝、冲突或待人工确认的候选都绑定 evidence_ref 或说明缺口。
你的输出必须符合当前节点的 output_contract；如果证据不足，应输出 rejected 或 needs_human_review，而不是补写结论。
```

### 13.2 需要分开的少量专用 profile

大多数审查节点共用 `semantic_graph_review_agent`。只有三类节点建议单独配置 profile：

| profile | 使用节点 | 差异 |
| --- | --- | --- |
| `semantic_graph_review_coordinator_agent` | graph root / coordinator / shard planner | 可以读取任务图状态、layer summary、coverage；不直接审查源码细节 |
| `semantic_graph_aggregator_agent` | system/folder/module/endpoint/relation aggregation | 读取同层 proposals，输出 layer summary candidate；仍不写最终图 |
| `semantic_graph_curator_agent` | conflict review / curator normalize | 可读取全部 proposal refs、AST hard facts、冲突集；只做发布前裁决，不直接改源码 |

这三个 profile 的工具权限仍应保持只读。记忆提交由 `memory_commit` 节点或正式 memory edge 完成，不让普通审查 agent 直接调用 memory write 工具。

### 13.3 Agent Group 配置

`agent_group_id` 用来表达审查组身份和默认参与者，不作为首版执行时的唯一绑定来源：

```text
agent_group_id: group.semantic_graph_reviewers
coordinator_agent_id: agent:semantic_graph_coordinator
member_agent_ids:
  - agent:semantic_graph_reviewer
  - agent:semantic_graph_aggregator
  - agent:semantic_graph_curator
group_policy:
  context_sharing: explicit_refs_only
  memory_sharing: graph_task_scoped
  output_merge: aggregation_node_only
  conflict_resolution: curator_decides_with_human_gate
```

这里的“分配任务”不是让前端 agent 临时创建后端 agent。正确边界是：

```text
Frontend / Workbench:
  展示项目语义图构建任务、分片、节点状态、证据、冲突和人工门。
  可以发起 start / pause / review / publish 等控制动作。
  不负责决定 shard，不负责创建 agent，不负责写 graph runtime state。

Backend Shard Planner / Coordinator Node:
  根据系统层、文件夹层、AST hard facts、文件复杂度和 layer summary 生成审查 shards。
  生成或选择 TaskGraphDefinition / ExecutableGraphConfig。
  把每个 shard 绑定到固定的 reviewer agent pool。

GraphRuntime / GraphLoop:
  按已发布 graph config 调度 ready nodes。
  生成 GraphNodeWorkOrder。
  通过 work_order.agent_id + work_order.agent_profile_id 调用对应审查 agent。
```

因此首版不依赖“临时搭建 agent”。系统应该预先登记一组固定审查 agent / profile，然后动态创建的是 task graph nodes、shards、work orders 和 node sessions，不是动态创建 agent 身份。

固定审查池建议：

```text
agent:semantic_graph_reviewer_01
agent:semantic_graph_reviewer_02
agent:semantic_graph_reviewer_03
agent:semantic_graph_aggregator
agent:semantic_graph_curator
agent:semantic_graph_coordinator
```

每个 reviewer 可以共用同一个 `semantic_graph_review_agent` profile。分片数量大于 agent 数量时，不新增 agent，而是让 graph scheduler 排队调度；每个 work order 使用独立 `node_session_id` 和 `per_node_run_session`，避免一个 agent 的上一个节点上下文污染下一个节点。

可以保留现有 `WorkerAgentFactory` / worker blueprint 的 spawn 能力作为未来扩展，但语义图审查网络首版不应依赖它。原因是 graph node 执行链路当前以发布后的节点 `agent_id`、`metadata.agent_profile_id`、`GraphNodeWorkOrder` 和 `TaskRunContract` 为准；临时 spawn agent 会引入 identity、profile、prompt set、trace、resume 和权限可追踪性的额外复杂度。

执行节点仍要写清：

```json
{
  "agent_id": "agent:semantic_graph_reviewer",
  "metadata": {
    "agent_profile_id": "semantic_graph_review_agent"
  }
}
```

### 13.4 节点契约模板

每个审查节点至少需要这些配置：

```json
{
  "node_id": "semantic_file_module_review:prompt_library.models",
  "node_type": "agent",
  "agent_id": "agent:semantic_graph_reviewer",
  "agent_group_id": "group.semantic_graph_reviewers",
  "execution_mode": "parallel",
  "dispatch_group": "module_review",
  "wait_policy": "wait_all_upstream_completed",
  "join_policy": "all_success",
  "contract_bindings": {
    "schema": {
      "input_contract_id": "project_graph.module_review_input.v1",
      "output_contract_id": "project_graph.layered_review_proposal.v1"
    },
    "execution": {
      "node_contract_id": "node-contract:semantic_graph_module_review"
    },
    "semantic": {
      "review_level": "module",
      "proposal_kinds": ["semantic_file_module", "public_surface", "module_edge", "conflict"]
    }
  },
  "memory_read_policy": {
    "readable_kinds": ["layer_summary"],
    "readable_scopes": ["graph_task", "parent_layer"]
  },
  "dynamic_memory_read_policy": {
    "max_dynamic_reads_per_node_run": 4,
    "allow_temporal_expansion": false
  },
  "metadata": {
    "agent_profile_id": "semantic_graph_review_agent",
    "prompt_contract": {
      "role_prompt": "你是一名语义文件模块审查员。你只审查 assigned_scope 内的单文件模块职责、public surface、内部 endpoint 线索和模块级关系候选。",
      "task_instruction": "你必须先对齐输入的 parent layer summary、Deep AST hard facts、文件 hash 和 evidence windows，再决定哪些 module proposal 可以接受、拒绝或需要人工确认。",
      "output_instruction": "输出必须符合 project_graph.layered_review_proposal.v1，包含 accepted_candidates、rejected_candidates、conflicts、evidence_refs、coverage 和 downstream_shard_hints。"
    },
    "assigned_scope": {
      "review_level": "module",
      "module_refs": ["sfm:backend/prompt_library/models.py"],
      "system_refs": ["system:prompt_system"]
    },
    "required_refs": [
      "deep_ast_generation",
      "parent_layer_summary",
      "file_tree_snapshot"
    ],
    "forbidden_inputs": [
      "full_project_dump",
      "unbounded_repository_scan"
    ]
  }
}
```

节点契约必须回答六件事：

- 你是谁：`role_prompt`。
- 你审查哪一层：`semantic.review_level`。
- 你只能看什么：`assigned_scope`、`required_refs`、`memory_read_policy`。
- 你必须输出什么：`output_contract_id`、`output_instruction`。
- 你不能做什么：禁止写源码、禁止发布最终图、禁止无证据推断。
- 你失败时怎么处理：输出 `rejected_candidates`、`needs_human_review`、`limitations`，而不是静默通过。

### 13.5 各层契约差异

| 节点类型 | 共用配置 | 差异化契约 |
| --- | --- | --- |
| system classification review | `semantic_graph_review_agent`、只读代码工具、graph task scoped memory read | 判断 functional system、owned folders、entrypoints、跨系统边界；不得深入函数级细节 |
| folder index review | 同上 | 判断文件夹职责、关键文件、下游 module shards；不得重新定义系统边界 |
| semantic file module review | 同上 | 判断单文件职责、public surface、内部 endpoint 线索和 module read profile |
| file-internal AST review | 同上 | 只围绕 Deep AST anchor 审查 class/function/parameter/call-site；不能凭语义想象 endpoint |
| relation trace review | 同上 | 顺着 import/call/registry/router/tool/prompt refs 建立候选 control route；必须列出边证据链 |
| conflict review | `semantic_graph_curator_agent` | 复核冲突、陈旧 hash、无证据候选、跨层不一致；输出 accept/reject/human gate |
| aggregation | `semantic_graph_aggregator_agent` | 合并同层 proposals，产生 layer summary candidate 和 next_layer_shards |
| memory commit | memory node / memory edge | 只提交 aggregation 输出的 layer summary，不提交普通 review agent 原文 |
| curator publish | deterministic 或 `semantic_graph_curator_agent` | 只发布通过 AST anchor / registry / schema 校验的 generation |

### 13.6 边和记忆配置

审查网络至少需要四类边：

```text
handoff:
  上游层级 summary / evidence pack 交给下游审查节点。

review_feedback:
  conflict 或 curator 发现问题后，把返修请求送回对应层级。

memory_commit:
  aggregation node 的 layer summary candidate 正式提交到图任务记忆库。

human_gate:
  系统边界发布、批量删除关系、高风险冲突裁决进入人工门。
```

边配置重点：

- `payload_contract_id` 必须区分 `system_layer_summary.v1`、`folder_layer_summary.v1`、`module_layer_summary.v1`、`endpoint_layer_summary.v1`、`relation_layer_summary.v1`。
- `context_filter_policy` 默认只传 refs 和必要 summary，不传全量 proposal 原文。
- `result_delivery_policy` 对 review -> aggregation 用 `contract_payload_and_refs`；对大文本 evidence 用 `refs_only` 或 `summary_and_refs`。
- `failure_propagation_policy` 对普通分片可用 `allow_partial`，对 curator publish 必须 `fail_downstream`。

记忆配置分层：

```text
Proposal Memory:
  普通审查 agent 的原始 proposal、证据、拒绝理由和冲突。

Layer Summary Memory:
  aggregation node 输出的层级共识和 next_layer_shards。

Project Semantic Space Store:
  curator publish 后的最终 generation。
```

普通审查 agent 只能写 proposal 输出，不能直接写 Project Semantic Space Store。aggregation 输出可以形成 memory write candidate；真正 commit 由 `memory_commit` 节点或 formal memory edge 处理。

### 13.7 输出 Schema 最小字段

所有审查节点共享一个基础 proposal envelope：

```json
{
  "proposal_id": "",
  "review_level": "system|folder|module|endpoint|relation|conflict",
  "assigned_scope": {},
  "accepted_candidates": [],
  "rejected_candidates": [],
  "conflicts": [],
  "needs_human_review": [],
  "evidence_refs": [],
  "coverage": {
    "covered_scope_refs": [],
    "uncovered_scope_refs": []
  },
  "downstream_shard_hints": [],
  "limitations": [],
  "confidence": "derived|hypothesis|rejected|needs_human_review"
}
```

禁止输出：

- 没有 `evidence_ref` 的 accepted candidate。
- 没有 `anchor_ref` 的 AST endpoint。
- 直接写最终 generation 的内容块。
- 用自然语言 summary 替代 schema 字段。

### 13.8 实施前必须补齐的配置清单

```text
1. 新增 worker prompt:
   worker.prompt.semantic_graph_review

2. 新增 prompt set:
   prompt_set.worker.semantic_graph_review

3. 新增 runtime profiles:
   semantic_graph_review_agent
   semantic_graph_review_coordinator_agent
   semantic_graph_aggregator_agent
   semantic_graph_curator_agent

4. 新增或登记 agent descriptors:
   agent:semantic_graph_reviewer
   agent:semantic_graph_coordinator
   agent:semantic_graph_aggregator
   agent:semantic_graph_curator

5. 新增 agent group:
   group.semantic_graph_reviewers

6. 新增 graph node contract ids:
   node-contract:semantic_graph_system_review
   node-contract:semantic_graph_folder_review
   node-contract:semantic_graph_module_review
   node-contract:semantic_graph_endpoint_review
   node-contract:semantic_graph_relation_review
   node-contract:semantic_graph_aggregation
   node-contract:semantic_graph_conflict_review
   node-contract:semantic_graph_curator_publish

7. 新增 input/output/payload contract ids:
   project_graph.*_review_input.v1
   project_graph.layered_review_proposal.v1
   project_graph.*_layer_summary.v1
   project_graph.semantic_generation_publish_candidate.v1

8. 检查 graph config publisher:
   确认 coordinator_agent_profile_id 能进入 ExecutableGraphConfig.agents。
   确认 metadata.agent_profile_id 能进入 published node agent_profile_id。

9. 检查 graph node runtime:
   确认 prompt_contract 在 TaskRunContract 中模型可见。
   确认 graph node prompt wiring 不吞掉节点级角色契约。

10. 检查 memory edge:
   确认 layer summary candidate 只进入 graph task memory。
   确认 Project Semantic Space Store 只能由 curator publish 写入。
```

最终裁决：

```text
运行配置统一，契约分层差异化。
agent group 负责组织，node contract 负责执行身份。
review agent 只产 proposal，aggregation node 产 layer summary。
memory commit 只提交阶段态，curator publish 才发布 generation。
```
