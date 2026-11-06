# 图任务系统项目网络建立承载能力扩展计划

状态：前置扩展设计稿，待审阅后实施  
日期：2026-07-01

## 1. 纠偏结论

这里要扩展的不是“审查专用系统”，而是图任务系统真正承载项目网络建立的能力。

审查只是项目网络建立流程中的一种节点工作姿态：

```text
work_posture = review / classify / index / trace / aggregate / validate / curate / publish
```

它不应该成为图系统的新中心。图系统真正需要增强的是：

```text
能表达项目网络建立任务；
能分层生成和承载大量语义分片；
能把分片绑定到稳定 agent / node / contract；
能收集 typed work products；
能汇聚、校验、发布 generation；
能追踪证据、状态、版本和增量更新。
```

因此正确方向是：

```text
Project Network Build Capability
-> Layered Build Contract
-> Semantic Shard Plan
-> Generic Node Templates
-> Typed Work Product Envelope
-> Evidence / Candidate / Layer / Generation Stores
-> Aggregation / Validation / Curator / Publish
-> Lifecycle / Incremental Update
-> Semantic Graph Review Network as one instance
```

不是：

```text
Review Task Capability
-> Review Proposal
-> Review Memory
-> Review UI
```

前者是底层能力，后者是业务用法。项目语义网络建立可以使用审查 agent，但图系统不能被改造成审查专用系统。

## 2. 项目网络建立到底需要图系统承载什么

项目网络建立不是单个任务节点，也不是一批松散 agent。它要求图系统承载一条长期、分层、可恢复、可增量更新的建设链路：

```text
Project Scope
-> Source Snapshots
-> Layer Plan
-> Semantic Shards
-> Work Orders
-> Work Products
-> Evidence Anchors
-> Layer Aggregation
-> Cross-Layer Relation Build
-> Validation / Curator
-> Published Generation
-> Incremental Refresh
```

需要的通用能力如下。

### 2.1 项目网络建立合同

需要一种通用 `ProjectNetworkBuildContract`，而不是 `ReviewTaskContract`。

它描述：

- 这次要建立哪类项目网络。
- 输入事实快照是什么。
- 输出哪些层。
- 是否允许增量构建。
- 哪些节点可以模型判断，哪些必须 deterministic。
- 发布前需要哪些校验。

建议字段：

```json
{
  "build_id": "",
  "build_kind": "project_semantic_network|code_control_network|prompt_runtime_network|tool_capability_network",
  "build_mode": "bootstrap|incremental|repair|audit",
  "scope": {
    "project_id": "",
    "root_paths": [],
    "system_refs": [],
    "folder_refs": [],
    "module_refs": [],
    "anchor_refs": []
  },
  "source_snapshots": {
    "file_tree_snapshot": "",
    "deep_ast_generation": "",
    "registry_snapshot": "",
    "tool_catalog_snapshot": "",
    "prompt_registry_snapshot": ""
  },
  "target_layers": [
    "system",
    "folder",
    "semantic_file_module",
    "ast_endpoint",
    "relation_route",
    "generation"
  ],
  "publication_policy": {
    "requires_curator": true,
    "requires_anchor_validation": true,
    "publish_store": "project_semantic_space_store"
  }
}
```

### 2.2 层级构建计划

需要一种 `ProjectNetworkLayerPlan`，表达每层怎么展开、依赖什么、输出什么。

```text
Layer 0 source_snapshot
Layer 1 system_map
Layer 2 folder_index
Layer 3 semantic_file_module
Layer 4 ast_endpoint
Layer 5 relation_route
Layer 6 validated_generation
```

每层都要有：

- layer id。
- 输入 snapshot / upstream layer refs。
- shard policy。
- node template refs。
- aggregation policy。
- validation policy。
- output contract。
- publish / memory / artifact policy。

这比“审查流程从上往下还是从下往上”更底层：图系统要能表达层级构建计划，具体是审查、扫描、索引、追踪还是校验，都只是节点模板。

### 2.3 语义分片模型

需要通用 `SemanticShardSpec`，不是 `ReviewShardSpec`。

一个 shard 是项目网络建立的最小可调度工作单元：

```json
{
  "shard_id": "",
  "layer_id": "semantic_file_module",
  "work_unit_kind": "system|folder|file_batch|file_module|ast_endpoint|relation_route|aggregation|validation|publish",
  "assigned_scope": {},
  "input_refs": [],
  "required_anchor_refs": [],
  "expected_work_product_contract_id": "",
  "node_template_id": "",
  "executor_policy": {
    "agent_id": "",
    "agent_profile_id": "",
    "work_posture": "classify|index|trace|review|aggregate|validate|curate|publish"
  },
  "complexity": {
    "score": 0,
    "risk_flags": []
  },
  "dependencies": []
}
```

审查只是：

```text
executor_policy.work_posture = review
```

不是 shard 模型本身。

### 2.4 通用节点模板

需要的是项目网络构建节点模板，而不是审查节点模板。

首版模板建议：

```text
project_network.source_snapshot
project_network.system_classify
project_network.folder_index
project_network.module_index
project_network.ast_endpoint_extract
project_network.relation_trace
project_network.layer_aggregate
project_network.cross_layer_validate
project_network.conflict_curate
project_network.generation_publish
project_network.memory_commit
project_network.artifact_commit
project_network.human_gate
```

其中 `system_classify`、`folder_index`、`module_index` 可以由 agent 执行，也可以由 deterministic extractor 执行。`cross_layer_validate` 可以是审查节点，但它不代表整个图系统是审查系统。

### 2.5 Typed Work Product

需要一个通用 `GraphBuildWorkProductEnvelope`，承载任意节点产出的结构化工作产品。

```json
{
  "work_product_id": "",
  "build_id": "",
  "graph_run_id": "",
  "node_id": "",
  "shard_id": "",
  "layer_id": "",
  "product_kind": "source_snapshot|system_map|folder_index|module_index|endpoint_index|relation_candidates|coverage_report|conflict_report|layer_summary|publish_candidate",
  "contract_id": "",
  "payload_ref": "",
  "evidence_refs": [],
  "anchor_refs": [],
  "coverage": {},
  "confidence": "deterministic|derived|hypothesis|rejected|needs_human_review",
  "status": "candidate|accepted|rejected|superseded|published"
}
```

这样审查输出、索引输出、关系追踪输出、汇总输出都走同一个载体，而不是为 review proposal 单独造一套模型。

### 2.6 资源与存储平面

项目网络建立需要多个存储层，不应该只叫 memory：

```text
Evidence Store:
  source snapshot、文件 hash、AST anchor、read window、registry facts。

Candidate Store:
  agent / deterministic node 产出的候选系统、模块、endpoint、relation。

Layer Store:
  每一层 aggregation 后的 layer index / layer summary。

Generation Store:
  curator 发布后的项目语义网络 generation。

Trace Store:
  graph_run_id、node_id、shard_id、work_order_id、work_product_id 的追踪链。
```

现有 formal memory 可以承载部分 layer summary / process memory，但最终项目网络 generation 不应该只是 memory record。它应是 Project Semantic Space Store 的版本化 generation。

### 2.7 汇聚与校验

需要通用 aggregation / validation 能力：

```text
layer_aggregate:
  合并同层 work products，生成 layer index。

cross_layer_validate:
  校验 system -> folder -> module -> endpoint -> relation 的一致性。

conflict_curate:
  对冲突候选做裁决。

generation_publish:
  只发布通过 anchor / schema / coverage 校验的 generation。
```

这不是审查专用能力。任何项目网络构建都需要 layer merge、coverage、conflict、publish。

### 2.8 增量生命周期

项目网络建立必须支持生命周期：

```text
bootstrap:
  首次构建完整 generation。

incremental:
  根据 file hash / AST generation diff 重建受影响 shards。

repair:
  针对冲突或人工反馈重建局部。

audit:
  只检查 generation 是否陈旧、断链、覆盖不足。
```

需要明确：

- 哪些 snapshot 变化会让哪些 layer 失效。
- 哪些 shard 可以复用。
- 哪些 work product 需要 supersede。
- generation 如何发布新版本。
- 旧 generation 如何保留和回滚。

### 2.9 前端投影

前端需要展示通用项目网络构建状态，而不是审查任务状态：

```text
build overview
layer progress
shard queue
work product list
evidence / anchor inspector
coverage map
conflict panel
generation publish gate
incremental refresh impact
```

前端仍然不做调度权威，只发控制动作：

```text
start / pause / resume / approve / reject / publish / cancel
```

## 3. 现有图系统已经有的能力

| 能力 | 源码 | 可复用情况 |
| --- | --- | --- |
| 静态图定义 | `task_system/graphs/task_graph_models.py` | 可定义 node / edge / resource / loop / contract |
| 图模块组合 | `task_system/graphs/composable_graph_models.py`、`graph_module_expansion.py`、`task_graph_standard_models.py` | 已有导入图模块和展开概念，可用于层级模板复用 |
| 分层归一 | `task_system/compiler/layered_graph_normalizer.py` | 已识别 memory、artifact、revision、timeline、loop、resource layers |
| 发布配置 | `task_system/compiler/executable_graph_config_publisher.py` | 能发布 `ExecutableGraphConfig`，支持 graph module expansion、resource nodes、loop frames |
| 节点合同 | `task_system/compiler/node_contract_models.py` | 可把 prompt/runtime/tool/permission/session 编译进 node contract |
| 边合同 | `task_system/compiler/edge_contract_models.py` | 已有 resource read/write/commit、review feedback、audit、human gate、barrier 等 protocol |
| 调度与恢复 | `graph_system/loop.py`、`resume.py`、`checkpoint_store.py` | 已有 state、ready、dispatch、checkpoint、resume |
| flow packet | `graph_system/flow_packet.py` | 能传递 node result、artifact refs、memory refs、receipt refs |
| 资源节点 | `memory_repository`、`artifact_repository`、`working_memory_store` 等 node type | 可作为候选/证据/层级产物的基础 |
| node config catalog | `task_system/node_configurations/catalog.py` | 可沉淀可复用节点配置，但还不是项目网络模板体系 |

这些说明：现有图系统已经不是空白。要补的是项目网络构建的通用语义层和产物层，不是重写 graph core。

## 3.1 LangGraph 可借鉴点

参考资料：

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph Thinking in LangGraph](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- [LangGraph Time Travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel)

可以借鉴，但必须转译，不照搬。

### 3.1.1 State schema + reducer

LangGraph 的核心思想之一是每个 state key 有自己的 reducer；没有 reducer 时默认覆盖，有 reducer 时可以 append / merge。这个机制适合我们转译成 `WorkProductChannel`：

```text
work_products:
  reducer = append_by_work_product_id

layer_index:
  reducer = replace_by_layer_generation

conflicts:
  reducer = merge_by_conflict_key

coverage:
  reducer = merge_scope_coverage
```

借鉴点：

- 不让所有节点都写同一个自由 JSON。
- 每类产物声明合并策略。
- 并行 shard 输出不会互相覆盖。
- aggregation 不靠模型读一堆文本，而是消费 typed channels。

对应到本项目：

```text
GraphBuildWorkProductEnvelope
-> WorkProductChannel
-> channel reducer / merge_policy
-> LayerAggregate node
```

### 3.1.2 Send / map-reduce

LangGraph 的 `Send` 用于未知数量对象的 fan-out：上游节点产生对象列表，下游同一个 node 模板被应用到每个对象。这个非常接近我们的 shard materialization。

但本项目不直接在同一个运行图里动态创建边。转译方式：

```text
LangGraph Send:
  runtime returns Send(node_name, per_item_state)

本项目:
  planner outputs SemanticShardSpec[]
  graph builder materializes shard nodes from stable node template
  each shard node receives assigned_scope / input_refs
```

借鉴点：

- “模板稳定，输入变化”。
- 一个 node 模板可实例化为多个 shard nodes。
- fan-out 的单位是结构化 item，而不是 prompt 里的一段任务说明。

### 3.1.3 Command = update + route

LangGraph 的 `Command` 把 state update 和 routing 放在同一个返回值中。它还提醒：同一个节点不要混用静态边和动态 routing，否则会同时执行，难以推理。

对应到本项目，应该形成硬规则：

```text
每个 node 只能选择一种出边权威：
  static_edges
  conditional_route
  next_graph_materialization
  human_gate_decision
```

如果一个 node 产出 `NextGraphMaterializationPackage`，它不应同时走一堆普通下游执行边。下一张图应由 package 发布后启动，而不是当前图里继续偷偷展开。

### 3.1.4 Checkpointer vs Store

LangGraph 明确区分：

```text
checkpointer:
  线程 / 单次图运行状态，用于 resume、interrupt、time travel、fault tolerance。

store:
  应用级长期数据，跨 thread / run 保存事实、偏好、知识。
```

这和我们必须坚持的分层一致：

```text
Graph checkpoint:
  GraphLoopState / active work orders / edge states / node results。

Project network stores:
  Evidence Store / Candidate Store / Layer Store / Generation Store / Trace Store。
```

借鉴点：

- 不把 generation 当 checkpoint。
- 不把 checkpoint 当长期项目事实。
- 图运行失败后恢复的是执行状态；项目语义网络发布的是独立 generation。

### 3.1.5 Time travel / fork

LangGraph 的 time travel 可以从 checkpoint replay 或 fork。我们不一定照搬 API，但应借鉴“从某个稳定点派生新分支”的思想。

对应本项目：

```text
Graph lineage:
  G0 -> G1 -> G2 -> ... -> Gn

Fork point:
  ProjectNetworkLayerPlan
  NextGraphMaterializationPackage
  LayerIndex generation
```

如果 G2 的 module index 判断错，不需要重跑 G0/G1，也不需要污染后续 generation；可以从 G1 的 layer index 或 G2 package fork 出 G2'。

### 3.1.6 Subgraph

LangGraph 支持 subgraph as node，用于复用节点集合和团队分工。但本项目已经裁决：

```text
Graph Node = single-agent work seat。
```

因此不能直接照搬“subgraph as node”作为执行语义。可借鉴的是接口思想：

```text
subgraph interface:
  input schema / output schema / shared state keys

本项目转译:
  graph module template
  materialization package
  input/output contract
  work product contract
```

也就是说，子图可以作为模板、阶段或下一张 graph 的发布包，不作为一个普通 node 内部偷偷运行的多 agent 系统。

### 3.1.7 State 存原始数据，不存 prompt

LangGraph 文档强调 state 应保存 raw data，需要 prompt 时在 node 内按需格式化。这一点非常适合我们：

```text
source snapshots
AST anchors
file hashes
work product payload refs
coverage
conflicts
layer index refs
generation refs
```

这些可以进入状态或 store。prompt、说明文字、给 agent 的长描述不应该成为状态事实。

本项目应坚持：

```text
Graph state / work product stores 保存 raw structured facts。
Agent prompt projection 在执行时由 node contract + input refs 动态生成。
```

### 3.1.8 最终借鉴裁决

应该借鉴：

- State schema + reducer 的产物合并思想。
- Send 的 map-reduce / shard fan-out 思想。
- Command 的 update+route 统一回执思想。
- 不混用静态边与动态 routing 的约束。
- checkpointer 与 store 分离。
- time travel / fork 的 lineage 思想。
- subgraph 的接口边界，而不是 subgraph-as-node 的执行语义。
- state 存 raw data，prompt 按需投影。

不应该照搬：

- 不把 graph node 改成 subgraph node。
- 不把共享 state 当成所有 agent 的上下文池。
- 不在运行中的 GraphLoopState 里临时插拓扑。
- 不用 Command 风格绕过现有 edge contract / flow packet / node result 链路。

转译到本项目的新增能力：

```text
WorkProductChannel + reducer_policy
SemanticShardSpec[] as Send-equivalent
NodeRouteDecision / NextGraphMaterializationPackage as Command-equivalent
Graph checkpoint vs Project network stores
GraphGenerationLineage with fork/replay semantics
Graph module templates with explicit input/output contracts
Raw structured state + prompt-time projection
```

## 3.2 LangGraph 借鉴后的工程规则

LangGraph 最值得借鉴的不是某个 API 名字，而是几个稳定的工程原则：状态有 schema，状态更新有 reducer，并行 fan-out 有结构化 item，路由回执和状态更新绑定，短期 checkpoint 与长期 store 分离。转到本项目后，这些原则必须落成以下规则。

### 3.2.1 WorkProductChannel 是图构建状态的唯一合并入口

项目网络构建节点不能把自然语言结果直接堆进一个共享上下文池。每个节点只能提交 `GraphBuildWorkProductEnvelope`，再由 `WorkProductChannel` 根据 reducer 合并：

```json
{
  "channel_id": "module_index_candidates",
  "layer_id": "semantic_file_module",
  "accepted_product_kinds": ["module_index", "module_relation_candidates"],
  "reducer_policy": "merge_by_stable_ref",
  "identity_keys": ["build_id", "layer_id", "scope_ref", "anchor_ref"],
  "conflict_policy": "emit_conflict_product",
  "visibility": "aggregation_nodes_only"
}
```

首版 reducer 建议：

| reducer | 用途 | 规则 |
| --- | --- | --- |
| `append_by_work_product_id` | 原始 proposal / evidence pack | 只追加，不覆盖 |
| `merge_by_stable_ref` | module / endpoint / relation candidates | 同一 stable ref 合并证据，冲突转 conflict product |
| `replace_by_generation` | layer index / publish candidate | 只允许更高 generation 替换旧 generation |
| `merge_scope_coverage` | coverage map | 合并 covered / uncovered scope，保留缺口 |
| `reject_on_anchor_mismatch` | AST endpoint | anchor/hash 不一致时拒绝进入 accepted channel |

这能避免“多个 agent 输出文本，最后让一个模型凭感觉汇总”的老问题。汇总节点消费的是 typed channels，不是聊天记录。

### 3.2.2 分片 fan-out 等价于 Send，但必须在发布图前物化

LangGraph 的 `Send` 给我们的启发是：fan-out 的单位必须是结构化对象，而不是让 agent 自己在 prompt 里拆任务。本项目的等价物是：

```text
ProjectNetworkLayerPlan
-> SemanticShardSpec[]
-> GraphMaterializationPackage
-> TaskGraphDefinition
-> ExecutableGraphConfig
```

硬规则：

- `SemanticShardSpec` 是 fan-out item。
- node template 是稳定模板，变化只通过 shard scope、input refs、contract refs、output contract 注入。
- 首版不在当前 `GraphLoopState` 里动态插节点。
- static 模式一次性物化受控分片。
- rolling one-hop 模式每次只物化下一张图。

### 3.2.3 每个节点只能有一个出边权威

借鉴 LangGraph `Command` 的关键不是把我们的返回值改成 Command，而是建立 route decision 的唯一权威。

```json
{
  "node_id": "layer_aggregate:module",
  "route_authority": "next_graph_materialization",
  "state_updates": ["module_index_channel", "coverage_channel", "conflict_channel"],
  "route_decision": {
    "decision_kind": "materialize_next_graph",
    "next_package_ref": "pkg:project-network:g2",
    "allowed_static_edges": []
  }
}
```

规则：

- 普通 handoff 节点使用 `static_edges`。
- 条件裁决节点使用 `conditional_route`。
- rolling 图规划节点使用 `next_graph_materialization`。
- 人工门节点使用 `human_gate_decision`。
- 一个节点不能同时让普通下游边继续执行、又产出下一张图 package。

这条规则比算法更重要。它防止图系统一半走静态边，一半偷偷展开新拓扑，最后 resume、checkpoint、前端状态都失真。

### 3.2.4 Checkpoint 只保存运行态，Store 才保存项目事实

LangGraph 的 checkpointer/store 分层必须在本项目里更严格：

```text
Graph checkpoint:
  GraphLoopState
  node_state / edge_state
  active work orders
  node result refs
  blocked / recoverable status

Project network stores:
  Evidence Store
  Candidate Store
  Layer Store
  Generation Store
  Trace Store
```

禁止：

- 不把 `Project Semantic Space generation` 存成 checkpoint。
- 不把 checkpoint replay 当作项目事实回滚。
- 不让普通 review node 直接写 generation store。
- 不让前端用 GraphLoopState 原始结构拼业务视图。

正确链路：

```text
node result
-> GraphBuildWorkProductEnvelope
-> WorkProductChannel reducer
-> layer aggregate
-> validation / curator
-> generation candidate
-> publish gate
-> generation store
```

### 3.2.5 Mode selector 必须是可解释的预算策略

LangGraph 提醒我们：复杂拓扑可以动态 fan-out，但项目级建网不能把所有动态性都塞到运行中。因此首版 mode selector 必须保守、可解释、可配置：

```json
{
  "mode": "static_pre_materialized",
  "reason": "estimated graph is within static budget",
  "budget": {
    "max_materialized_nodes": 120,
    "max_parallel_shards_per_layer": 40,
    "max_layers": 6,
    "max_files_in_scope": 80
  },
  "observed": {
    "estimated_nodes": 76,
    "estimated_parallel_shards": 18,
    "estimated_layers": 5,
    "files_in_scope": 42
  }
}
```

建议默认策略：

- `static_pre_materialized`：文件数、分片数、层数、关系复杂度都在预算内，且目录/系统边界清晰。
- `rolling_one_hop`：项目大、系统边界不清、fan-out 估算不稳定、跨模块关系多、需要逐层校验。
- `runtime_requested_expansion`：首版不启用；后续也必须通过新 `ExecutableGraphConfig` / 新 graph run 表达。

阈值不是架构真理，而是运行预算。它应该在配置层可调，且每次选择都写入 `GraphGenerationLineage`，方便事后审计为什么用了静态图或 rolling 图。

### 3.2.6 GraphGenerationLineage 是 rolling 图的安全带

rolling one-hop 能降低漂移率，但只有在 lineage 严格记录时才安全：

```json
{
  "lineage_id": "lineage:project-network:20260701",
  "build_id": "build:project-semantic-network",
  "graph_generation": 2,
  "parent_graph_run_id": "graph-run:g1",
  "parent_layer_index_ref": "layer-index:folder:g1",
  "source_work_product_refs": [],
  "materialization_package_ref": "pkg:g2",
  "executable_graph_config_ref": "graph-config:g2",
  "mode": "rolling_one_hop",
  "forked_from": null,
  "status": "active"
}
```

fork / replay 规则：

- 错在某层 shard：从该层上一张 graph 的 layer index 重新物化。
- 错在 package：废弃 package，保留 parent layer index，重新生成 package。
- 错在 source snapshot：整条 lineage 标记 stale，不能局部修补成 published generation。
- 错在 curator 裁决：只重跑 validation / publish graph，不重跑已验证 layer。

### 3.2.7 Subgraph 只作为模板边界，不作为多 agent 节点

LangGraph subgraph 的接口思想可以借鉴，但本项目必须保持：

```text
Graph Node = single-agent work seat。
```

所以我们使用：

```text
Graph module template
Materialization package
Input/output contract
Work product contract
```

不使用：

```text
一个 node 内部偷偷运行多 agent 子图。
```

多 agent 协作必须被显式表达为：

```text
peer shard nodes
-> aggregation node
-> validation / curator node
-> publish gate
```

## 4. 还差什么

### Gap 1：缺 ProjectNetworkBuildContract

现在图可以跑任务，但缺少“项目网络建立”这种上层合同。没有它，scope、source snapshots、target layers、publication policy 都会散落。

需要新增：

```text
ProjectNetworkBuildContract
ProjectNetworkLayerPlan
ProjectNetworkBuildMode
ProjectNetworkPublicationPolicy
```

### Gap 2：缺 SemanticShardSpec

现在有 graph nodes，但没有“为什么这些节点是这些分片”的标准记录。项目网络建立需要 shard 可以追踪到 scope、layer、anchor、source snapshot 和 downstream product。

需要新增：

```text
SemanticShardSpec
ShardPlan
ShardAssignment
ShardComplexityPolicy
```

### Gap 3：缺通用 GraphBuildWorkProductEnvelope

现在 `NodeResultEnvelope.outputs` 可以放结构化输出，但没有项目网络构建统一 work product 模型。后续汇聚、发布、前端展示都会缺稳定载体。

需要新增：

```text
GraphBuildWorkProductEnvelope
WorkProductRef
WorkProductStatus
WorkProductContractCatalog
```

### Gap 4：缺 Project Network Builder

现在能手写 TaskGraphDefinition，但缺少从 build contract / layer plan / shard plan 生成图的 builder。

需要新增：

```text
ProjectNetworkGraphBuilder
LayerGraphBuilder
ShardNodeMaterializer
GraphBuildTemplateCatalog
```

### Gap 5：图渲染模式能力还不够

源码已有 `graph_module_expansion` 和 `loop_frames`，但项目网络建立至少需要多种图渲染模式并存。不能用 rolling one-hop 替代 static graph；它们适合不同任务。

```text
static pre-materialized graph:
  构建前先生成所有 shard node，发布静态 ExecutableGraphConfig。
  适合小项目、流程确定、层级固定、成本可控的构建任务。

rolling one-hop graph materialization:
  先发布一张固定 bootstrap planning graph。
  第一层读取文件结构、source snapshots 和基础 hard facts。
  planning node 只产出下一张 graph 的 ProjectNetworkLayerPlan + SemanticShardPlan + materialization package。
  下一张 graph 执行完成后，再由 aggregation / planner 节点产出再下一张 graph。
  适合大项目、结构不确定、需要逐层降低漂移的构建任务。

runtime requested expansion:
  coordinator / aggregation 节点产出 next_layer_shards 后，请求生成下一层图或下一代 graph config。
  作为未来高级模式，仍必须通过新 config / 新 graph run 表达，不能偷改当前 GraphLoopState。
```

首版应同时支持两种安全模式：

```text
mode = static_pre_materialized
mode = rolling_one_hop
```

不建议首版支持在同一个运行中直接变更拓扑。原因是当前 `ExecutableGraphConfig` 依赖 `content_hash`、`structure_hash`、checkpoint 和 resume 语义；运行时直接改拓扑会牵动 config hash、active work orders、edge state 和 result replay。

模式选择策略：

| 模式 | 适用场景 | 优点 | 风险 |
| --- | --- | --- | --- |
| `static_pre_materialized` | 小项目、层级已知、节点数可控、流程稳定 | 简单、可审查、一次发布、resume 最稳定 | 对大型未知项目容易前期规划过多，漂移和节点爆炸 |
| `rolling_one_hop` | 大项目、结构未知、需要逐层确认 | 每次只规划下一张图，漂移率低，局部可回滚 | 多次发布图，lineage 和前端投影要求更高 |
| `runtime_requested_expansion` | 后续高级能力 | 灵活 | 首版不做；必须避免破坏 config hash / checkpoint |

因此，滚动一跳是模式之一，不是替代静态图模式。

rolling one-hop 的正确做法：

```text
G0 Bootstrap Planning Graph:
  source_snapshot
  -> project_structure_intake
  -> next_graph_plan_design
  -> next_graph_materialization_package
  -> plan_validation
  -> optional_human_gate

G1 First Layer Execution Graph:
  根据 G0 已校验的 materialization package 生成第一张真实执行图。
  G1 只处理 immediate target layer，例如 system map 或 folder index。
  G1 聚合后产出 G2 的 materialization package。

G2..Gn Rolling Execution Graphs:
  每一张图只消费上一张图的 typed work products / layer index。
  每一张图只规划并发布下一张图。
  最后一张 publish graph 只在 anchor / schema / coverage 校验通过后发布 generation。
```

后续如果做 runtime requested expansion，也必须发布下一代 `ExecutableGraphConfig` 或启动后续 execution graph，不允许在原 `GraphLoopState` 里偷偷插 node。

这个方案满足用户提出的要求：节点由我们配置，但实际层数和分片可以由第一层在看到文件结构后决定；同时每张图只设计下一张图，不把远期层级一次性锁死。节点模板可复用，变化的是 `assigned_scope`、`input_refs`、`contract refs`、`target_layer`、`work_product_contract_id` 和 `next_graph_ref`。

这种 one-hop 方式降低漂移率：

- 每次规划只面对下一层，不让模型提前猜完整项目网络。
- 每张图都以上一张图的 typed work products、layer index、coverage 和 conflicts 为输入。
- 每张图发布前都有 plan validation / optional human gate。
- 每张图都有独立 `ExecutableGraphConfig`、hash、checkpoint、result refs 和 generation lineage。
- 如果某层判断错误，只回滚或重建相邻图，不污染完整未来拓扑。

### Gap 5.1：缺 Graph Materialization Mode Protocol

当前系统能跑 graph，但缺少项目网络建立专用的图渲染模式协议。它不是业务审查图，而是决定“这次构建用静态图，还是滚动一跳多图”的协议。

需要新增：

```text
GraphMaterializationMode
ProjectNetworkBootstrapPlan
ProjectStructureIntakeProduct
StaticGraphMaterializationPackage
NextGraphPlanProduct
NextGraphMaterializationPackage
PlanValidationProduct
GraphGenerationLineage
```

图渲染模式协议的职责：

- 读取文件树、基础 source snapshots、Deep AST generation 摘要和 registry/tool/prompt catalog 摘要。
- 判断使用 `static_pre_materialized` 还是 `rolling_one_hop`。
- 静态模式下生成完整但受控的 graph materialization package。
- 滚动模式下只判断下一张图要处理哪一层或哪一组紧邻层。
- 生成当前模式所需的 layer plan。
- 生成当前模式所需的 shard plan。
- 绑定节点模板和 contract refs。
- 输出 static graph 或 next graph 的 materialization package。
- 记录 parent_graph_run_id、source_work_product_refs、layer_index_refs、materialization_mode 和 next_graph_config_ref。

每张 graph 不能做：

- 不直接发布最终 Project Semantic Space generation。
- rolling 模式下不替后续多层 graph 一次性做完整规划。
- static 模式下可以一次性规划完整执行图，但必须受 node count、layer count、scope 和 validation policy 限制。
- 不直接替下一张 graph 执行所有审查/索引工作。
- 不在当前运行图内动态插入未发布节点。
- 不让前端决定分片。

### Gap 5.2：缺节点模板复用与契约重定向

用户提出“契约指向变化的复用会方便”是可行的。节点模板应该稳定，变化项通过 `node_config_overrides` 或 materialized node metadata 注入：

```text
stable template:
  node_config_id
  node_type
  work_posture
  prompt_contract base
  allowed output kind
  memory/artifact policy

per-shard overrides:
  assigned_scope
  input_refs
  required_anchor_refs
  input_contract_id
  output_contract_id
  payload_contract_id
  target_context_key
  work_product_contract_id
  agent_id / agent_profile_id
```

这样一个 `project_network.module_index` 模板可以实例化为多个 module shard nodes，一个 `project_network.layer_aggregate` 模板可以实例化为 system/folder/module/endpoint/relation 不同层级的汇聚节点。

### Gap 6：缺证据与索引资源平面

现有 memory/artifact 资源能用，但项目网络建立需要明确资源类型：

```text
evidence_pack_repository
network_candidate_repository
layer_index_repository
semantic_generation_repository
build_trace_repository
```

这可以先映射到 artifact repository / formal memory / project semantic store，但必须在合同层明确，不要混成普通 memory。

### Gap 7：缺 generation 生命周期

需要明确 generation 的状态机：

```text
draft
candidate
validating
published
superseded
rejected
rolled_back
```

以及 source snapshot -> shard -> work product -> layer index -> generation 的可追踪链。

### Gap 8：缺项目网络构建状态投影

现有 graph status 偏 runtime，前端需要 project network build view：

```text
layers
shards
work products
coverage
conflicts
evidence
generation
publish gate
incremental impact
```

这应该是 projection，不应该让前端理解底层 edge_state / node_state 的全部细节。

## 5. 推荐目标模块

新增通用模块：

```text
backend/task_system/project_network/
  __init__.py
  build_contract_models.py
  layer_plan_models.py
  shard_models.py
  work_product_models.py
  template_catalog.py
  shard_planner.py
  graph_builder.py
  work_product_extractor.py
  lifecycle_policy.py
  projection.py
```

不要叫 `review_tasks`。如果后续需要审查专用策略，可以放在：

```text
backend/task_system/project_network/strategies/review_strategy.py
```

或者用模板参数表达：

```text
work_posture = review
validation_policy = cross_agent_review
```

## 6. 分阶段实施计划

### Phase 1：项目网络建立合同

目标：

- 定义 `ProjectNetworkBuildContract`。
- 定义 `ProjectNetworkLayerPlan`。
- 定义 target layers、source snapshots、publication policy。

完成标准：

- 可以用结构化合同表达“我要为这个项目建立语义网络”。
- 合同不包含审查专用字段。
- 审查只作为某些 layer 的 `work_posture` 或 `validation_policy`。

### Phase 2：语义分片计划

目标：

- 定义 `SemanticShardSpec`。
- 实现自适应 shard planner。
- 同时支持 static shard plan 和 rolling one-hop shard plan。
- 定义 `StaticGraphMaterializationPackage`。
- 定义 `NextGraphMaterializationPackage`。

完成标准：

- static 模式能从 scope + source snapshots + full layer plan 生成受控完整 shards。
- rolling 模式能从 scope + source snapshots + parent work products + layer plan 生成下一张图的 shards。
- shard 能追踪 layer、scope、input refs、expected output、executor policy。
- 小文件 batch、大文件单独、复杂文件下钻 endpoint 由统一 shard policy 控制。
- rolling shard plan 不提前锁死远期层级；static shard plan 必须受 node count、layer count 和 scope policy 限制。

### Phase 3：通用节点模板与图构建器

目标：

- 建 `GraphBuildTemplateCatalog`。
- 建 `ProjectNetworkGraphBuilder`。
- 从 `StaticGraphMaterializationPackage` 生成完整静态 `TaskGraphDefinition`。
- 从 `NextGraphMaterializationPackage` 生成下一张滚动 `TaskGraphDefinition`。

完成标准：

- 能生成 source snapshot、index、trace、aggregate、validate、curate、publish、commit、human gate 节点。
- 节点模板可复用，不写死项目语义图。
- 生成的图仍走现有 `TaskGraphDefinition -> ExecutableGraphConfig`。
- static 模式可以承载完整受控拓扑。
- rolling 模式每张图只承载 immediate target layer 或紧邻层，不承载完整未来拓扑。

### Phase 4：Work Product 抽取与存储

目标：

- 定义 `GraphBuildWorkProductEnvelope`。
- 从 node result structured output 抽取 typed work products。
- 建 evidence / candidate / layer / generation refs。

完成标准：

- agent 输出不能只停留在 raw markdown。
- aggregation 可以消费同层 work product refs。
- publish 可以消费 layer index refs 和 validation refs。

### Phase 5：资源平面与 generation 生命周期

目标：

- 定义 evidence/candidate/layer/generation store 的逻辑资源。
- 定义 generation lifecycle。
- 接入现有 artifact repository / formal memory / Project Semantic Space Store。

完成标准：

- 过程产物和最终 generation 分离。
- generation 可版本化、可 supersede、可回滚。
- source snapshot 变化能定位受影响 shards。

### Phase 6：运行接线补齐

目标：

- 补齐 `coordinator_agent_profile_id` 投影。
- 确保 node `metadata.agent_profile_id` 编译、发布、work order、task run 全链路可追踪。
- 确保 graph module / resource / loop / edge contracts 对 project network builder 可用。

完成标准：

- 缺 profile、contract、resource 时在构建/发布期失败。
- 不等到执行期才报错。

### Phase 7：状态投影与前端控制

目标：

- 提供 project network build projection。
- 前端展示 build/layer/shard/work product/generation 状态。
- 前端只发控制动作，不做调度权威。

完成标准：

- 用户能看到项目网络建立到了哪一层。
- 能看到哪个 shard 阻塞、哪个证据缺失、哪个 generation 待发布。
- 不要求用户读 GraphLoopState 原始结构。

### Phase 8：项目语义网络实例

目标：

- 用上述通用能力搭建 `project_semantic_network`。
- 其中部分节点使用 review posture。

完成标准：

- 语义图审查网络是 project network build capability 的实例。
- 审查图不拥有自己的调度器、存储层或专用 graph core。

## 7. 文件级清单

预计新增：

```text
backend/task_system/project_network/__init__.py
backend/task_system/project_network/build_contract_models.py
backend/task_system/project_network/layer_plan_models.py
backend/task_system/project_network/shard_models.py
backend/task_system/project_network/work_product_models.py
backend/task_system/project_network/template_catalog.py
backend/task_system/project_network/shard_planner.py
backend/task_system/project_network/graph_builder.py
backend/task_system/project_network/work_product_extractor.py
backend/task_system/project_network/lifecycle_policy.py
backend/task_system/project_network/projection.py
```

预计修改：

```text
backend/task_system/compiler/executable_graph_config_publisher.py
backend/task_system/compiler/node_contract_models.py
backend/task_system/compiler/edge_contract_models.py
backend/task_system/node_configurations/catalog.py
backend/graph_system/work_order_executor.py
backend/graph_system/context_materializer.py
backend/graph_system/runtime.py
backend/harness/runtime/graph_node_contract.py
backend/api/task_system.py
```

后续语义图实例才涉及：

```text
backend/task_system/project_network/strategies/project_semantic_network.py
backend/prompt_library/worker_prompts.py
backend/prompt_library/prompt_sets.py
backend/agent_system/profiles/runtime_profile_registry.py
```

## 8. 验证方式

实施后用真实运行验证，不通过新增回归测试文件制造通过：

```text
Static path:
  1. 创建 ProjectNetworkBuildContract。
  2. 选择 mode=static_pre_materialized。
  3. 生成 StaticGraphMaterializationPackage。
  4. 发布单张 ExecutableGraphConfig。
  5. 执行完整受控 topology。
  6. 检查 GraphBuildWorkProductEnvelope refs、layer index、generation candidate。

Rolling path:
  1. 创建 ProjectNetworkBuildContract。
  2. 选择 mode=rolling_one_hop。
  3. 发布 G0 Bootstrap Planning Graph。
  4. 执行 G0，生成 G1 的 NextGraphMaterializationPackage。
  5. 校验 G1 package，发布 G1 ExecutableGraphConfig。
  6. 执行 G1 immediate target layer。
  7. 由 G1 aggregation 生成 G2 的 NextGraphMaterializationPackage。
  8. 校验 G0 -> G1 -> G2 lineage。
  9. 最后一张 publish graph 生成 generation candidate。
  10. 检查 frontend/API projection。
```

验证通过标准：

- 图系统没有变成审查专用系统。
- 审查只是某些节点的 `work_posture`。
- work product 能跨节点、跨层传递。
- generation 可追溯到 source snapshots、shards、work orders、evidence refs。
- static 模式能稳定跑完整受控拓扑。
- rolling 模式每张 graph 只规划下一张 graph，不一次性锁死完整未来拓扑。
- 每张 graph 都有独立 `ExecutableGraphConfig`、hash、checkpoint、result refs 和 lineage。
- rolling 模式任一层失败时可以重建相邻下一张 graph，不污染全局 generation。

## 9. 最终裁决

```text
要扩展的是项目网络建立的通用 graph carrying capacity。
审查只是节点策略，不是图系统形态。
static_pre_materialized 和 rolling_one_hop 都是一等图渲染模式。
图系统承载 layer、shard、work product、resource、generation、lifecycle。
语义图审查网络只能作为这个能力上的第一个业务实例。
```

补充节点模型裁决：

```text
Graph Node = single-agent work seat。
```

在项目网络建立能力里，节点应直接看作一个单 agent 执行单元：一个 node 接收一个明确 shard / input refs / node contract，生成一个可追踪 work product。多个 agent 的协作不是塞进同一个 node，而是由多个 node、edge、layer aggregation 和 curator publish 组织出来。

因此：

- `node_id` 是单 agent work unit 的执行身份。
- `agent_group_id` 只是候选 agent 池或组织标签，不代表一个 node 内部有多个 agent。
- 一个复杂 folder / system 可以生成多个 shard nodes，而不是让一个 node 同时扮演多个 agent。
- aggregation / validation / curator 也是独立 node；它们可以由单 agent 或 deterministic executor 执行，但语义上仍是一个执行席位。
- 如果需要多 agent 互审，应该表现为多个 peer review nodes + aggregation node，而不是一个“多 agent node”。

## 10. 2026-07-01 首批实施记录

已新增通用项目网络建立承载能力的第一批代码骨架：

```text
backend/task_system/project_network/__init__.py
backend/task_system/project_network/build_contract_models.py
backend/task_system/project_network/layer_plan_models.py
backend/task_system/project_network/shard_models.py
backend/task_system/project_network/work_product_models.py
backend/task_system/project_network/template_catalog.py
backend/task_system/project_network/shard_planner.py
backend/task_system/project_network/graph_builder.py
backend/task_system/project_network/work_product_extractor.py
backend/task_system/project_network/lifecycle_policy.py
backend/task_system/project_network/projection.py
```

本次实施范围：

- 落地 `ProjectNetworkBuildContract`、`ProjectNetworkLayerPlan`、`SemanticShardSpec`、`GraphBuildWorkProductEnvelope`、`WorkProductChannel`、`StaticGraphMaterializationPackage`、`NextGraphMaterializationPackage`、`NodeRouteDecision`、`GraphGenerationLineage`。
- 建立 `ProjectNetworkGraphBuilder`，能从 static package 或 rolling one-hop package 物化 `TaskGraphDefinition`。
- 建立 `GraphMaterializationBudget` 和 mode selector，static / rolling 的选择有可解释预算。
- 建立 typed work product 抽取、projection 和 generation status transition 辅助能力。
- 默认节点身份使用 `project_network_builder / aggregator / curator`，不把底层能力命名成审查专用系统。

本次明确未做：

- 未修改 `GraphLoopState`，未在运行中动态插 node。
- 未改 graph core、compiler publisher、work order executor 或 API。
- 未注册真实 agent/profile/prompt set；这些属于后续 graph node 执行接线阶段。
- 未发布 Project Semantic Space generation；当前只做到项目网络构建图的结构化物化能力。

## 11. 2026-07-01 执行接线实施记录

已补齐项目网络构建图进入现有 graph runtime 的基础接线：

```text
backend/agent_system/registry/agent_registry.py
backend/agent_system/groups/registry.py
backend/agent_system/profiles/runtime_profile_registry.py
backend/prompt_library/worker_prompts.py
backend/task_system/compiler/executable_graph_config_publisher.py
backend/task_system/project_network/graph_builder.py
backend/task_system/project_network/template_catalog.py
```

本次实施范围：

- 新增固定 agent：`agent:project_network_coordinator`、`agent:project_network_builder`、`agent:project_network_aggregator`、`agent:project_network_curator`。
- 新增固定 group：`group.project_network_builders`。group 只表示可调度 agent 池，不改变“一个 graph node 是一个单 agent 执行席位”的裁决。
- 新增 runtime profiles：`project_network_coordinator_agent`、`project_network_builder_agent`、`project_network_aggregator_agent`、`project_network_curator_agent`。
- 新增 worker prompt：`worker.prompt.project_network_build`，并自动生成 `prompt_set.worker.project_network_build`。
- `ProjectNetworkGraphBuilder` 物化的图会写入 `coordinator_agent_id`、`coordinator_agent_profile_id` 和 `agent_group_id`。
- `ProjectNetworkNodeTemplate` 现在内置 agent 可执行的 `prompt_contract`，包含 role、task、output、forbidden_behavior 和 definition_of_done。
- AST 能力不写入 task environment；它由 project network agent runtime profile 默认配备，并由节点 `runtime_policy.context_policy.code_intelligence.ast` 按 basic/deep 档位声明或覆盖。
- `ExecutableGraphConfig` publisher 现在会投影 `coordinator_agent_profile_id`，并保留节点 prompt 的 `forbidden_behavior` / `definition_of_done`。
- `pn.source` 和 `pn.output` 改为资源节点，source refs 通过 shard assignment/input refs 进入节点，不再用资源节点发起 handoff 调度边。

验证结果：

```text
Static publish:
  nodes=6
  edges=3
  coordinator_agent_profile_id=project_network_coordinator_agent
  blocking_issues=[]

Static runtime + loop:
  runtime_started=project_network_coordinator_agent
  loop_status=running
  first_work_order_node=pn.system.shard.build.runtime.system.001
  first_work_order_agent=agent:project_network_builder
  first_work_order_profile=project_network_builder_agent
  prompt_contract includes forbidden_behavior and definition_of_done

Rolling publish:
  nodes=5
  edges=2
  node_profiles=[project_network_aggregator_agent, project_network_builder_agent]
  blocking_issues=[]
```

本次仍未做：

- 未执行真实模型节点，也未发布最终 Project Semantic Space generation。
- 未新增 API / frontend projection。
- 未实现 stores 的持久化表或 Project Semantic Space Store 写入。

## 12. 2026-07-01 Work Product 存储与发布生命周期实施记录

已补齐项目网络建立的长期事实平面和产物消费服务：

```text
backend/task_system/project_network/store_models.py
backend/task_system/project_network/repository.py
backend/task_system/project_network/service.py
backend/task_system/project_network/work_product_extractor.py
backend/task_system/project_network/projection.py
backend/task_system/project_network/__init__.py
```

本次实施范围：

- 新增 `ProjectNetworkRepository`，使用 `storage/tasks/project_network.sqlite` 承载项目网络建立的持久化事实。
- 新增 store planes：build、work product、channel state、evidence、candidate、layer index、generation、trace。
- 新增 `ProjectNetworkBuildService`，消费 `NodeResultEnvelope`，抽取 `GraphBuildWorkProductEnvelope`，再写入各个 store plane。
- `work_product_extractor` 支持读取 `outputs.graph_build_work_products`、`outputs.work_products`、`outputs.structured_output.graph_build_work_products`、`outputs.node_output.work_products` 等真实 agent 常见输出形态。
- `WorkProductChannel` 的 reducer 现在能通过 repository 持久化 channel state，不再只是内存辅助函数。
- `publish_candidate` 只生成 `ProjectNetworkGenerationRecord(status=candidate)`；最终发布必须由 `curator`、`publish_gate`、`human_gate` 或 `system_publish_gate` 调用 publish 生命周期。
- builder 类节点不能直接发布 generation；这保证 `NodeResultEnvelope -> WorkProduct -> Store planes -> Curator Publish` 的权威链路不被绕过。
- `build_project_network_store_projection()` 现在可以从 store snapshot 生成前端/API 可用的项目网络构建视图，前端不需要理解底层 `GraphLoopState`。

权威边界：

```text
GraphLoop:
  接受节点结果、推进 checkpoint / edge state / ready node。

ProjectNetworkBuildService:
  在节点结果已被接受后，消费结构化 work product，写入项目网络长期事实平面。

ProjectNetworkRepository:
  只负责持久化和生命周期状态转换，不进行 agent 语义判断。

Curator / Publish Gate:
  唯一允许把 generation candidate 推进到 published 的执行权威。
```

验证结果：

```text
compileall backend/task_system/project_network:
  passed

temporary repository smoke:
  products=3
  channels=3
  evidence=2
  candidates=1
  layers=1
  generations=[('generation:smoke:g1', 'published')]
  builder_publish_blocked=True
  transition_publish_blocked=True
  published_status=published
  projection_status=published
  latest_generation_ref=generation:smoke:g1
```

本次仍未做：

- 未把 service 自动挂入 `GraphLoop.accept_node_result()`；这样避免 graph runtime 变成项目网络专用系统。后续应在 runner/API 的领域消费点中调用 `ProjectNetworkBuildService.accept_node_result()`。
- 未新增 API / frontend 页面；当前已提供 repository snapshot 与 projection 作为接线基础。
- 未实现真正的 Project Semantic Space Store 写入；当前 generation 已有生命周期记录，后续 publish gate 可再对接最终语义空间存储。

## 13. 2026-07-01 Deep AST 工具权威收口实施记录

已把 Python AST 的确定性事实来源收口到 `code_intelligence` 能力层：

```text
backend/capability_system/capabilities/code_intelligence/python_ast_indexer.py
backend/capability_system/tools/tool_units/python_ast_tools.py
backend/capability_system/capabilities/codebase_search/providers.py
```

本次实施范围：

- 新增确定性 `FileModuleAstIndex`，作为单文件模块的 Deep AST hard facts。
- `python_code_outline` 只做工具适配和展示，不再拥有独立 AST outline 权威。
- `python_symbol_search` 只从 `FileModuleAstIndex` 派生符号候选，不再复制 class/function/import/assignment 遍历逻辑。
- symbol search 增加 exact name / qualname 优先排序，避免精确类名查询被导入位置或类方法抢占前排。
- `codebase_search` 的 symbol layer 继续沿用原工具入口，但 diagnostics / read window authority 指向 `capability_system.capabilities.code_intelligence.python_ast_indexer`。

对项目网络建立的意义：

- graph node 的最小调度单位仍是 `file_module`；函数、class、参数、调用点是模块内可引用 anchor，不升级为 graph node。
- module/endpoint/relation/validate 类节点要求 `deep_ast required=true` 时，应消费该索引器产出的 anchors 和 cards，而不是要求 agent 重新读全文件猜结构。
- 后续 Project Network Build Service 可以把 `FileModuleAstIndex` 写入 Evidence Store，再让 module_index / relation_trace 节点只读取必要的 file module shard。

本次仍未做：

- 未把 `FileModuleAstIndex` 持久化到项目网络 repository。
- 未把 Deep AST index 自动注入 graph work order input refs。
- 未实现跨文件 relation resolver；跨文件边仍需要后续 relation_trace 节点结合 AST anchors、import text 和 registry facts 建立候选。

验证结果：

```text
python -m compileall:
  passed

python_file_module_ast_index smoke:
  passed

python_code_outline / python_symbol_search smoke:
  passed

codebase_search symbol layer smoke:
  passed
```
