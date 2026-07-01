# 系统结构网络与语义网络双层建图计划

状态：MVP 第一段实施中，已完成物理骨架与 git 维护入口的首轮落地  
日期：2026-07-01

## 1. 核心裁决

最合理的项目网络架构不是让 agent 从源码文本里直接画完整图，而是双层建网：

```text
Skeleton Graph = 系统确定性抽取的结构网络
Semantic Overlay = 图任务 agent 基于骨架审查建立的语义网络
Published Semantic Generation = curator 校验后的可用项目语义空间
```

系统和 agent 的分工必须清楚：

```text
系统负责：把项目真实结构抽成可验证、可刷新、可寻址的骨架网络。
agent 负责：顺着骨架网络审查关系、命名系统、判断职责、建立语义覆盖。
图任务负责：把多个 agent 的审查工作组织成分层生产线。
curator 负责：校验 anchor、hash、coverage、conflict，发布 generation。
```

这比“让模型直接生成项目图”成熟，因为它把精确结构提取交给系统，把语义判断交给 agent。

### 1.0.1 设施归属裁决

项目网络不是任务系统自己的设施。

最终归属：

```text
file_management.project_structure
  owns Skeleton Graph
  owns Semantic Overlay Store
  owns git change set mapping
  owns semantic repair work item store
  owns maintenance projection

task_system.project_network
  only orchestrates graph tasks
  only defines审查流程、节点模板、分片策略、产物摄取
  does not own physical skeleton tables
  does not own semantic overlay tables
  does not own git delta / maintenance state
```

原因：

- 物理结构是文件/代码管理基础设施，不是一次任务的内部状态。
- 语义 overlay 是项目长期索引和可维护记忆，不是任务系统的临时产物。
- 任务系统只能调度 agent 审查、生成候选和决策，然后把结果提交给 project structure store。
- 后续 CLI、前端、agent runtime、搜索工具都应该从同一个 `file_management.project_structure` 读取项目网络，不能绕到 task graph 私有 store。

因此所有项目网络设施状态都必须落在 `backend/file_management/project_structure/` 及其 storage 中；`backend/task_system/project_network/` 只保留任务图编排和图任务产物协议。

### 1.1 物理架构优先原则

项目结构网络必须是物理架构网络，不是 agent 自由生成的语义草图。

硬规则：

```text
Skeleton Graph = physical architecture facts
Semantic Overlay = agent-reviewed meaning attached to Skeleton Graph
```

系统先铺出物理网络：

```text
file tree
AST tree
symbol/reference index
git history graph
registry/runtime graph
config/state graph
```

agent 只能顺着这张物理网络附着语义：

```text
system ownership
module responsibility
endpoint role
control route interpretation
impact scope
verify scope
risk and coverage judgment
```

禁止：

- agent 不能凭直觉新增没有 skeleton_node_id 的语义节点。
- agent 不能凭语义相似度新增没有 skeleton_edge_id 或 evidence_ref 的 accepted 语义边。
- agent 不能绕过物理层级，直接把两个高层概念连成可发布控制关系。
- agent 不能把 unresolved / hypothesis relation 改写成 hard architecture fact。

允许：

- agent 可以提出 `semantic_candidate`。
- agent 可以提出 `missing_physical_edge_request`，要求系统 extractor 或人工补证据。
- agent 可以把物理边裁决为 `accepted | rejected | uncertain | stale`。
- agent 可以在多个物理节点之上建立系统归属、职责、影响面和验证面。

发布门槛：

```text
accepted semantic node -> must reference skeleton_node_id
accepted semantic edge -> must reference skeleton_edge_id or evidence-backed physical candidate
accepted control route -> must resolve to file_module and endpoint/evidence point
```

这保证系统负责“项目真实结构长什么样”，agent 负责“这些结构意味着什么”。语义网络只能沿物理架构生长，不能脱离物理架构另铺一张网。

## 2. 双层网络定义

### 2.1 Skeleton Graph

Skeleton Graph 是确定性结构网络，只保存 hard facts 和可追踪候选。

它回答：

```text
项目里有什么对象？
这些对象在哪个文件、哪个 anchor、哪个 registry 中？
对象之间有哪些可验证结构边？
哪些关系已解析，哪些仍是 unresolved candidate？
```

它不回答：

```text
哪个模块最重要？
哪个系统边界最合理？
哪条调用是核心控制链路？
某个关系是否应该进入语义图？
```

### 2.2 Semantic Overlay

Semantic Overlay 是 agent 审查后的语义解释层。

它回答：

```text
这个文件属于哪个功能系统？
这个模块暴露什么能力？
这个 endpoint 是否是关键入口？
这条结构边是否构成真实控制关系？
修改某个节点会影响哪些模块？
需要怎么验证？
```

Semantic Overlay 的每条 accepted 语义边都必须挂回 Skeleton Graph 的 node / edge / anchor / evidence。

Semantic Overlay 不是第二张自由图，而是 Skeleton Graph 的附着层：

```text
SemanticNodeAnnotation attaches_to SkeletonNode
SemanticEdgeAnnotation attaches_to SkeletonEdge or evidence-backed SkeletonEdgeCandidate
SemanticControlRoute attaches_to ordered SkeletonEdges + endpoint anchors
```

如果 agent 发现语义上“应该存在一条边”，但 Skeleton Graph 没有对应物理边，它只能输出：

```text
missing_physical_edge_request
coverage_gap
next_crawl_request
```

不能直接把这条边写成 accepted semantic relation。

### 2.3 叠加边界：物理层是结构，语义层是指引

两层必须叠加，但不能混写：

```text
Skeleton Graph 负责可验证结构：
  repo / folder / file / module / class / function
  parent / ancestor / direct children
  contains / defines / imports_text / calls_text
  parameters / return annotation / anchor / line range
  inbound / outbound / resolved / unresolved relation counts

Semantic Overlay 负责 agent 审查后的方向：
  系统归属
  模块职责
  关键入口
  控制链路解释
  影响面
  验证策略
  风险与覆盖裁决
```

因此物理节点不写“这个层负责什么业务”。它只提供层级落脚点、下方节点数量、输入输出结构、调用/被调用关系和证据。语义职责必须由图任务 agent 基于 skeleton slice 审查后，以 overlay 方式挂接到 `stable_ref / skeleton_node_id / skeleton_edge_id / anchor_ref`。

读取时应呈现为叠加视图：

```text
Physical Node Card:
  stable_ref
  physical_layer
  hierarchy_path
  direct_child_count_by_kind
  inbound_edge_count_by_kind
  outbound_edge_count_by_kind
  parameters / returns / imports / calls

Semantic Overlay Card:
  attaches_to stable_ref / skeleton_node_id / skeleton_edge_id
  agent decision
  evidence_refs
  confidence / status / generation
  verification guidance
```

这样 agent 没有物理层时不会迷路，有语义层时才知道往哪里走。物理层提供“能爬过去”的道路，语义层提供“为什么走这条路”的路标。

### 2.4 Harness 接线裁决：深度搜索必须独立于工具槽位

深度项目网络不是“一个更大的搜索工具说明”，不能继续挤在 `Tool Capability Surface` / tool catalog / tool schema 里。工具槽位只负责告诉 agent：

```text
有哪些操作可以调用？
参数和权限边界是什么？
工具生命周期和失败反馈是什么？
```

项目语义空间必须走独立的 runtime context lane。它回答的是：

```text
当前站在哪个物理/语义节点？
周围有哪些 skeleton nodes / skeleton edges？
哪些 semantic overlays 可以作为路标？
当前 frontier、visited、crawl budget 和控制决策状态是什么？
哪些引用可以继续展开，哪些证据需要读取或刷新？
```

因此 runtime 层需要保持三条线分开：

```text
Tool Lane
  只放工具能力、参数、权限、生命周期和可调度 operation。

Project Semantic Space Lane
  放物理骨架、语义索引、局部可爬视图、语义路标和证据引用。
  它不占用工具说明槽位，也不把工具文档伪装成项目地图。

Agent Neural Control Lane
  放 traversal session、frontier、visited、当前目标、crawl budget、控制决策日志。
  它只表达 agent 当前如何在网络上移动，不写入物理事实，也不改写语义事实。
```

硬边界：

- `Tool Lane` 是手和脚；`Project Semantic Space Lane` 是地图；`Agent Neural Control Lane` 是当前位置、注意力和下一跳决策状态。
- 深度搜索工具返回的主要价值不是散文本，而是更新后的 semantic space projection / control projection。
- 语义空间不进入工具 catalog，不增加工具说明噪声；但它仍然会消耗上下文预算，所以只能投影局部切片、索引摘要和必要 refs。
- 大图必须持久化在 `file_management.project_structure` / store 中；当前回合只加载和目标有关的局部可爬视图。
- agent 的下一跳仍由 agent 在普通 `tool_call` / task execution 决策中选择；系统只提供结构化候选、证据、状态和边界。
- `Semantic Overlay` 不允许写 `next_action`、active frontier、当前回合预算等控制字段；这些属于 `Agent Neural Control Lane`。
- `Agent Neural Control Lane` 不允许伪造 `skeleton_node_id`、`skeleton_edge_id`、anchor、hash 或 accepted semantic relation；它只能引用已有物理/语义节点并记录 traversal decision。

目标接线形态：

```text
ProjectStructureStore
  -> Skeleton Graph
  -> Semantic Overlay Index

ProjectNetworkControlStore
  -> traversal session
  -> frontier / visited
  -> crawl budget
  -> agent control decisions

RuntimeCompiler / DynamicContextManager
  -> RuntimePacketContext.project_semantic_space
  -> RuntimePacketContext.project_network_control
  -> provider-visible local semantic slice

project_network tool
  -> start_traversal / continue_traversal / read_frontier / record_decision
  -> ToolObservation returns updated control state refs

agent
  -> reads semantic space lane
  -> chooses next hop through normal action protocol
  -> uses tools as execution limbs
```

这条接线保留 harness 的成熟闭环：系统编译 packet，agent 做语义决策，工具执行动作，observation 回流为下一轮动态上下文。深度搜索要成为系统能力，关键不是把工具说明写得更长，而是把项目语义空间和网络控制态变成 harness 可投影、可观察、可回写的一等运行资源。

## 3. 系统结构网络怎么搭建

系统结构网络应由多个确定性 extractor 组成，不依赖模型判断。

```text
Source Snapshot
-> FileTreeExtractor
-> DeepAstExtractor
-> RegistryExtractor
-> DomainExtractor
-> GitHistoryExtractor
-> RelationNormalizer
-> SkeletonGraphStore
```

### 3.0 成熟架构参照与可利用骨架源

成熟代码智能系统通常不会只依赖一种索引。更合理的结构网络应叠加多类可靠骨架：

| 骨架源 | 成熟参照 | 系统可抽取内容 | 在本项目中的用途 |
| --- | --- | --- | --- |
| Git history / commit graph | Git commit-graph 使用提交父子关系、提交时间、root tree、generation number 加速图遍历 | commit、parent、changed files、rename、co-change、author/time、hotspot | 识别历史耦合、变更热点、影响范围、过期语义边 |
| File tree / package tree | 所有 IDE / code host / build tools 的基础结构 | project、folder、package、file_module、path ownership | 建立最稳定的系统入口和分片边界 |
| Concrete syntax tree / AST | Tree-sitter、Python ast、compiler frontend | module、class、function、call_site、import、assignment、line range | 生成最小可验证代码骨架和 anchor |
| Symbol / reference index | SCIP、LSIF、Kythe | definition、reference、implementation、xref、document symbols | 支撑 go-to-definition / find-references 风格的跨文件结构边 |
| Build / runtime graph | Kythe 强调 build systems、compilers、static analyses、editors 等工具间共享代码事实 | build target、runtime profile、task graph node、operation、capability | 补足纯 AST 看不到的运行时控制结构 |
| Registry / manifest graph | agent registry、tool catalog、prompt registry、route registry | prompt、tool、agent、profile、node template、operation | 对 agent 项目尤其关键，很多真实控制关系不在函数调用里 |
| Config / state graph | repo config、env、sqlite/repository、state store | config key、store、table、read/write state refs | 支撑影响面、验证面和运行状态依赖 |

裁决：

```text
Skeleton Graph = Git Graph + File Tree + AST Tree + Symbol/Reference Index + Registry/Runtime Graph + Config/State Graph
```

其中：

- File tree 决定最稳定的空间边界。
- AST tree 决定文件内部的可验证结构。
- Symbol/reference index 决定跨文件跳转能力。
- Git graph 决定演化关系、热点、staleness 和 co-change 证据。
- Registry/runtime graph 决定 agent 系统真实控制关系。
- Config/state graph 决定运行时依赖和验证范围。

这与成熟系统的方向一致：Kythe 把代码事实设计成语言无关的图交换机制；SCIP/LSIF 聚焦 definition/reference 导航；Tree-sitter 提供可增量更新的语法树；Git commit-graph 用提交拓扑和 generation 加速历史图遍历。本项目在这些基础上扩展 agent 专用的 prompt/tool/runtime/task graph 骨架。

### 3.0.1 建模形态裁决：分布式抽取，中心化归一，局部化爬行

蜘蛛网不能用单一集中式 builder 从头到尾生成，也不能让每个 agent / extractor 各自维护一张图。

最终裁决：

```text
Distributed Extractors
-> Raw Fact Stream
-> Central Identity / Relation Normalizer
-> Materialized Skeleton Graph Index
-> Local Slice Projection
-> Agent Crawler / Graph Task Semantic Overlay
-> Curator Publish Generation
```

原因：

- 纯集中式 builder 易读，但会变成巨型上帝模块，难维护、难增量、难定位错误。
- 纯分布式建图扩展性好，但 identity、边语义、冲突、stale 和发布状态会漂移。
- 最合理的是 extractor 分布式、事实格式统一、归一与发布中心化、agent 只看局部切片。

权威结构：

| 阶段 | 形态 | 职责 | 审查性 |
| --- | --- | --- | --- |
| Extract | 分布式 | 每个 extractor 只观察自己的事实源 | 可单独复跑、单独比对 |
| Fact Stream | append-only | 保存原始事实和 provenance | 可追踪谁产出事实 |
| Normalize | 中心化 | stable identity、边归一、冲突合并 | 可统一审查规则 |
| Materialize | 中心化索引 | adjacency、reverse index、slice index | 可快速查询和爬行 |
| Crawl | 局部化 | agent 只拿当前目标切片 | 避免上下文爆炸 |
| Semantic Overlay | 图任务分布式 | agent 分层审查语义 | 每个决策可回溯 |
| Publish | 中心化 gate | curator 校验并发布 generation | 防止未审语义入库 |

### 3.0.2 原始事实模型：先建 Fact，再折叠成 Graph

为了易读、易追踪、方便审查，extractor 不应直接写最终 node/edge，而应先输出统一事实。

```text
SkeletonFact:
  fact_id
  build_id
  source_kind: file_tree | ast | symbol | registry | domain | git | config
  subject_ref
  predicate
  object_ref
  object_literal
  qualifiers
  evidence_refs
  anchor_refs
  source_snapshot_ref
  extractor_id
  extractor_version
  content_hash
  confidence: exact | derived | unresolved
```

这个模型类似成熟代码索引系统中的“分析器输出事实，再由图存储聚合消费”。Kythe 的 graph store 也是 analyzer 输出与消费工具之间的接口；SCIP 也强调多来源信息可以合并成统一代码智能体验。

Fact 的好处：

- extractor 简单，不承担全局身份合并。
- 中央 normalizer 可以复查每条边从哪里来。
- 事实可 append-only 保存，便于 diff、回滚和审计。
- 同一个事实源升级 extractor 版本后，可以只重放受影响 facts。

### 3.0.3 Stable Identity 算法

蜘蛛网能否维护，关键是 node id 稳定。

采用 URI-like stable refs：

```text
repo://<project_id>
folder://backend/task_system/project_network
file://backend/task_system/project_network/service.py
pyast://backend/.../service.py#function:ProjectNetworkBuildService.accept_node_result
registry://tool/op.python_symbol_search
prompt://worker.prompt.project_network_build
agent://agent:project_network_builder
profile://project_network_builder_agent
git://commit/<sha>
config://backend/.env/API_BASE
state://sqlite/storage/tasks/project_network.sqlite/project_network_edges
```

稳定性规则：

- file/module 以 normalized path 为主，hash 只做 freshness，不做 identity。
- AST endpoint 首版用 path + qualname + node_kind；line range 只做 evidence，不做 identity。
- call site 用 path + enclosing function stable ref + stable_ast_path + text digest。
- registry 对象用 registry id。
- git commit 用 commit sha。
- rename 通过 git rename / file similarity 只生成 `supersedes` 或 `renames` 边，不直接改旧 node id。

### 3.0.4 关系归一算法

关系构建按确定性优先级执行：

```text
1. exact id reference
   registry id、prompt id、tool operation id、route path、commit sha。

2. scoped symbol resolution
   import alias table、module exports、qualname、symbol index。

3. structural candidate
   call_text、attribute access、config key、file path string。

4. historical candidate
   git co-change、rename、recent churn。

5. semantic candidate
   agent 提出，但不能进入 Skeleton hard edge。

6. unresolved
   保留原始文本、anchor、reason、next extractor hint。
```

边状态：

```text
exact -> 可进入 Skeleton accepted structure edge
derived -> 可进入 Skeleton candidate edge
historical -> traversal priority / hypothesis evidence
semantic -> Semantic Overlay candidate
unresolved -> 只能作为 frontier 或 coverage gap
```

### 3.0.5 增量构建算法

不要每次全量重建蜘蛛网。首版采用 hash-bound incremental pipeline：

```text
source snapshot diff
-> changed paths / changed registry refs / changed commits
-> affected extractor shards
-> delete or supersede old facts owned by extractor_version + source_hash
-> re-emit facts
-> normalize affected identities
-> update adjacency indexes
-> stale propagation through reverse dependencies
-> queue semantic repair shards
```

stale propagation 使用有界 BFS：

```text
seed = changed skeleton node/edge
for reverse_edge in incoming_edges(seed):
  if edge_kind in stale_propagation_policy:
    mark semantic annotation stale
    enqueue repair frontier
stop at budget / layer boundary / published generation boundary
```

这样可以保证：

- 文件小改只刷新相关子图。
- registry 改动只刷新 prompt/tool/profile/runtime 相关边。
- git 历史只影响 traversal priority 和 stale 证据，不强行改语义边。

### 3.0.6 可读性与审查性设计

蜘蛛网不能只给全局大图。每个 node/edge 都要有 card：

```text
NodeCard:
  stable_ref
  kind
  display_name
  source facts
  inbound edges summary
  outbound edges summary
  evidence refs
  freshness
  semantic annotations

EdgeCard:
  edge_kind
  src -> dst / candidate
  resolution_status
  evidence chain
  extractor provenance
  review decisions
  stale status
  next crawl hints
```

审查界面和 agent 上下文默认只显示：

```text
local node card
top inbound/outbound edges
unresolved edges
conflict edges
coverage gaps
recommended frontier
```

全图只作为后端索引，不作为 prompt 或前端默认视图。

### 3.0.7 爬行算法

agent 爬图使用 weighted best-first frontier，而不是盲目 BFS 或全文搜索。

```text
priority =
  goal_relevance
  + edge_kind_weight
  + node_kind_weight
  + unresolved_bonus
  + conflict_bonus
  + stale_bonus
  + git_hotspot_bonus
  + coverage_gap_bonus
  - already_visited_penalty
  - high_degree_noise_penalty
```

常用算法：

- `best-first expansion`：选择最高价值 frontier。
- `bidirectional BFS`：用于 trace A 到 B 的路径。
- `bounded DFS`：用于沿单条控制链深入。
- `SCC detection`：识别循环依赖或强耦合模块。
- `degree / centrality`：只用于排序和热点提示，不作为语义事实。
- `co-change clustering`：只用于候选影响范围，不作为 accepted dependency。

成熟边界：

- 图算法给 agent 推荐下一跳，不替 agent 裁决语义。
- embedding / BM25 / 文本搜索只用于 seed discovery 或 fallback，不写入 hard skeleton edge。
- high-degree node 要降权，避免所有路径都跑到 common utils / base classes。

### 3.0.8 存储形态

首版不引入外部图数据库。使用 SQLite + adjacency index 足够：

```text
project_network_skeleton_facts
project_network_skeleton_nodes
project_network_skeleton_edges
project_network_adjacency
project_network_reverse_adjacency
project_network_semantic_node_annotations
project_network_semantic_edge_annotations
project_network_traversal_sessions
project_network_frontier_items
```

后续如果图规模扩大，再考虑专用图数据库或列式索引。首版优先保证：

- schema 可读。
- 每条边可追 facts。
- 每次 generation 可重放。
- 每个 agent 决策可审查。

### 3.0.9 层级落脚点：Hierarchy Spine

agent 不能在无层级节点海里爬行。它需要稳定的层级落脚点，先纵向定位，再横向追踪关系。

因此 Skeleton Graph 必须内置一条主干：

```text
Project
-> Functional System
-> Subsystem / Folder
-> FileModule
-> Class / FunctionEndpoint
-> CallSite / ImportBinding / StateRef / ConfigRef
```

这条主干是 agent 的“落脚链”：

- `Project`：当前仓库和 generation 的顶层入口。
- `Functional System`：语义系统边界，首版可以先由目录/registry 生成 candidate，再由 agent 审查 accepted。
- `Folder`：最稳定的结构分片，适合规划、聚合和缩小范围。
- `FileModule`：agent 常规读取和图任务调度的最小语义单位。
- `Class / FunctionEndpoint`：可控制的代码末梢。
- `CallSite / ImportBinding / StateRef / ConfigRef`：需要 exact evidence 的细粒度证据点。

层级边：

```text
project contains system_candidate
project contains folder
system_candidate owns folder
folder contains file_module
file_module defines class
file_module defines function_endpoint
class contains function_endpoint
function_endpoint contains call_site
function_endpoint references state_ref / config_ref
file_module imports import_binding
```

层级规则：

- 每个非 project 节点必须至少有一个 parent anchor 或 parent candidate；否则进入 orphan queue。
- agent 每次横向追 relation 前，必须知道当前节点处在哪一层。
- 横向边不能替代层级边；`calls/imports/uses_tool/uses_prompt/routes_to` 都是跨层或同层关系，必须挂在 hierarchy spine 的具体落脚点上。
- 高层语义系统可以是 agent 审查后 accepted，但底层 folder/file/module/AST 层级必须来自系统确定性抽取。
- 若一个节点有多个系统归属，只能通过 semantic ownership annotation 表达，不复制 skeleton node。

agent 爬行模式：

```text
vertical descend:
  project -> system/folder -> module -> endpoint -> evidence point

horizontal traverse:
  endpoint -> call/import/tool/prompt/state edge -> neighbor endpoint/module

vertical ascend:
  evidence point -> endpoint -> module -> folder/system for impact summary
```

这样 agent 可以一层一层顺着链条爬：

```text
先找系统落脚点
再找文件夹/模块落脚点
再落到 endpoint
再沿 call/import/registry 边横向跳转
再向上汇总影响面
```

### 3.0.10 层级索引算法

为了让层级可读、可追踪、可维护，需要维护 materialized path 和 ancestor index。

```text
node_depth
hierarchy_path
ancestor_node_ids
parent_node_ids
child_node_ids
layer_kind
```

示例：

```text
project://langchain-agent
/folder://backend
/folder://backend/task_system
/folder://backend/task_system/project_network
/file://backend/task_system/project_network/service.py
/pyast://...#class:ProjectNetworkBuildService
/pyast://...#function:ProjectNetworkBuildService.accept_node_result
```

构建算法：

1. File tree 先建立 project/folder/file_module 的确定性层级。
2. AST extractor 在 file_module 下挂 class/function/call/import。
3. Registry extractor 在 project 下挂 registry namespace，再通过 `declares/uses` 边连到 file/module/endpoint。
4. Semantic system candidate 通过 `owns` 边覆盖 folder/file/module，但不改变 file tree 的物理 parent。
5. Normalizer 生成 `hierarchy_path` 和 `ancestor_node_ids`，供 projection 和 crawler 快速使用。

爬行约束：

- 默认 expand 先返回同层高价值邻居，再返回下层 children，最后返回上层 ancestors。
- impact scope 先向上找到 folder/system，再横向找同系统关系，再向下列出受影响 module/endpoint。
- relation trace 如果跨越不同系统，必须显示最近共同 ancestor 或明确标记 cross_system_relation。

### 3.1 FileTreeExtractor

职责：

- 提取 project、folder、package、file_module。
- 生成 contains 边。
- 记录 path、file hash、mtime、suffix、size。

节点：

```text
project
folder
package
file_module
```

边：

```text
project contains folder
folder contains folder
folder contains file_module
package contains file_module
```

### 3.2 DeepAstExtractor

职责：

- 消费 `FileModuleAstIndex`。
- 生成 module、class、function_endpoint、call_site、import_binding、assignment、return 节点。
- 生成 defines、contains、imports_text、calls_text 等结构边。

节点：

```text
file_module
class
function_endpoint
call_site
import_binding
assignment
return_site
```

边：

```text
file_module defines class
file_module defines function_endpoint
class contains function_endpoint
function_endpoint contains call_site
file_module imports_text import_binding
function_endpoint calls_text call_site
```

首版重要原则：

- `calls_text` 不伪装成已解析跨文件调用。
- 能 exact 解析时写 `dst_node_id`。
- 不能解析时保留 `dst_candidate_ref`、`callee_text` 和 `unresolved`。

### 3.3 RegistryExtractor

职责：

- 抽取系统已有注册结构。
- 把 registry 中的 prompt、tool、agent、profile、task template、graph node template 等转成结构节点。

节点：

```text
agent
agent_profile
agent_group
prompt
prompt_set
tool
operation
task_template
node_template
runtime_profile
capability
```

边：

```text
agent has_profile agent_profile
agent belongs_to agent_group
profile allows_operation operation
prompt_set includes prompt
node_template uses_agent agent
node_template requires_capability capability
tool exposes_operation operation
```

RegistryExtractor 对本项目尤其关键，因为 agent 系统不是纯代码调用链，很多真实控制关系藏在 registry、profile、prompt set、tool catalog、task template 中。

### 3.4 DomainExtractor

职责：

- 抽取项目领域结构，首版只做高价值、可确定的领域。

建议首批：

```text
FastAPI route / API endpoint
SSE endpoint
frontend API client call
native tool catalog
prompt resource / prompt set
task graph template
runtime profile / context policy
state store / sqlite table / repository
config key
```

边：

```text
route handled_by function_endpoint
frontend_call routes_to route
tool registered_by file_module
prompt referenced_by node_template
profile declares_capability capability
repository reads_state state_store
repository writes_state state_store
config_key configures module
```

DomainExtractor 不做模糊推断，只做可验证提取。不能确定的关系进入 candidate。

### 3.5 GitHistoryExtractor

职责：

- 抽取提交拓扑、文件变更、rename、co-change、hotspot 和最近修改时间。
- 为 Skeleton Graph 提供演化关系，不直接判断语义职责。
- 标记可能 stale 的 skeleton / semantic refs。

节点：

```text
commit
branch
file_revision
change_set
author
```

边：

```text
commit parent commit
commit changes file_module
commit renames old_file_module -> new_file_module
file_module co_changes_with file_module
file_revision supersedes file_revision
```

用途：

- 文件频繁共同变化时，给 agent 提供 impact_scope 候选。
- 文件 hash 或 rename 变化时，驱动 skeleton edge / semantic annotation stale。
- 审查图任务可以优先处理高 churn、高 co-change、高入边的模块。
- curator 可以把“历史强相关但结构边不足”的关系标成 review candidate，而不是 accepted edge。

GitHistoryExtractor 的边界：

- co-change 不是语义依赖，只能作为 traversal priority 或 hypothesis evidence。
- git 历史不能覆盖 AST/registry hard facts。
- rename/copy 检测首版可以依赖 git 命令结果，不自己发明相似度算法。

### 3.6 RelationNormalizer

职责：

- 把不同 extractor 的原始关系统一成 Skeleton Edge。
- 对同一对象做 stable identity 合并。
- 记录 unresolved reason。
- 不做语义裁决。

归一规则：

```text
same stable_ref -> same node
same src + edge_kind + dst/candidate -> merge evidence
different confidence -> 保留最高确定性，同时记录 evidence set
conflict -> 生成 conflict candidate，不静默覆盖
```

## 4. Skeleton Graph 数据模型

### 4.1 Skeleton Node

```text
SkeletonNode:
  node_id
  build_id
  generation
  node_kind
  stable_ref
  display_name
  path
  layer_kind
  hierarchy_path
  parent_node_ids
  ancestor_node_ids
  anchor_ref
  file_hash
  extractor
  confidence: exact | derived | unresolved
  status: active | stale | removed
  payload
  created_at
  updated_at
```

### 4.2 Skeleton Edge

```text
SkeletonEdge:
  edge_id
  build_id
  generation
  edge_kind
  src_node_id
  dst_node_id
  dst_candidate_ref
  src_anchor_ref
  dst_anchor_ref
  evidence_refs
  extractor
  confidence: exact | derived | unresolved
  resolution_status: resolved | unresolved | ambiguous
  freshness: fresh | stale
  payload
```

### 4.3 Evidence

Skeleton Graph 的证据必须是机器可复查的：

```text
file_hash
anchor_ref
line_range
registry_ref
schema_ref
content_hash
extractor_version
```

## 5. 语义网络如何由图任务建立

图任务不重新抽骨架，只消费 Skeleton Graph slice。

```text
Skeleton Graph
-> Skeleton Slice Projection
-> Graph Task Work Orders
-> Agent Semantic Work Products
-> Semantic Overlay Index
-> Curator Validation
-> Published Semantic Generation
```

### 5.1 图任务分层

推荐流水线：

```text
G0 skeleton_snapshot
  系统生成 Skeleton Graph generation。

G1 system_classify
  agent 基于 folder/file/module/registry 骨架识别功能系统边界。

G2 folder_index
  agent 汇总文件夹职责、关键模块、边界风险。

G3 module_semantic_index
  agent 逐文件模块建立 module role、public capability、关键 endpoint。

G4 endpoint_review
  agent 审查 class/function/call_site 是否是关键入口、控制末梢或风险点。

G5 relation_review
  agent 顺着 imports/calls/tools/prompts/routes/state refs 审查结构边，裁决 accepted/rejected/uncertain。

G6 layer_aggregate
  汇总 system/folder/module/endpoint/relation 层的语义产物。

G7 curator_validate
  校验 anchor/hash/coverage/conflict/stale/schema。

G8 publish_generation
  发布 Semantic Graph generation candidate。
```

### 5.2 Semantic Overlay 产物

```text
SemanticNodeAnnotation:
  skeleton_node_id
  semantic_kind
  role
  system_ref
  module_capability
  risk_tags
  confidence
  evidence_refs
  reviewer_node_id

SemanticEdgeAnnotation:
  skeleton_edge_id
  semantic_relation_kind
  decision: accepted | rejected | uncertain
  reason
  impact_scope
  verify_scope
  confidence
  evidence_refs
  reviewer_node_id
```

### 5.3 agent 审查契约

写给 agent 的 prompt 应该是：

```text
你是一名项目语义网络审查员。
你只基于输入的 Skeleton Graph slice、AST anchors、registry refs 和 exact evidence 判断语义关系。
你不负责重新抽取代码结构，也不能凭经验补不存在的边。
你需要对每条候选边给出 accepted、rejected 或 uncertain 裁决。
accepted 必须引用 skeleton_edge_id 和 evidence_ref。
证据不足时，你必须输出 coverage gap 或 next crawl request。
```

## 6. Skeleton Slice 给 agent 看什么

agent 不应看到全量图，而应看到当前任务所需切片。

系统给 graph node 的输入：

```text
assigned_scope
skeleton_generation_ref
seed_nodes
local_nodes
local_edges
candidate_edges
unresolved_edges
required_evidence_refs
coverage_gaps
upstream_semantic_summary_refs
```

对 module 节点：

```text
file_module node
contained class/function/call/import nodes
outbound structure edges
inbound candidate edges
required read windows
```

对 relation 节点：

```text
source node
target candidate node
edge evidence chain
neighbor context
conflicting candidates
unresolved reason
```

## 7. Crawler 与图任务的关系

图任务是批量建语义网络的生产线；crawler 是 agent 日常使用网络、补图、审边的交互方式。

```text
Graph Task:
  大规模、分层、可恢复、可聚合。

Crawler:
  目标驱动、局部展开、frontier 控制、交互式审查。

Skeleton Graph:
  两者共享的结构底座。

Semantic Overlay:
  两者共同写入的语义候选与审查结果。
```

## 8. 生命周期

### 8.1 构建

```text
source snapshot created
-> skeleton extractors run
-> skeleton generation candidate
-> deterministic validation
-> skeleton generation active
-> graph task semantic build starts
```

### 8.2 刷新

```text
file hash changed
-> re-run affected extractors
-> mark affected skeleton nodes/edges stale
-> mark dependent semantic annotations stale
-> queue graph task repair shards
-> crawler frontier receives stale review items
```

### 8.2.1 Git 驱动的网络维护

网络建立之后，git 应成为持续维护触发器。编程过程中的修改会改变物理结构、调用关系、registry 关系和语义判断，因此维护不能等到人工重新全量建图。

维护链路：

```text
git working tree / staged diff / commit diff
-> GitChangeSet
-> Physical Impact Planner
-> Skeleton Delta Refresh
-> Semantic Stale Marker
-> Network Maintenance Agent Work Items
-> Semantic Repair Decisions
-> Curator Revalidate
```

关键分工：

```text
系统：
  读取 git diff、文件 hash、AST diff、registry diff。
  刷新受影响的 Skeleton facts/nodes/edges。
  标记受影响 semantic annotations stale。
  生成 repair work items。

Network Maintenance Agent：
  只消费系统给出的 affected skeleton slice。
  读取 ProjectNetworkSharedMemory 中已有模块职责、关系裁决、维护历史和 stale 记录。
  审查语义是否仍成立。
  更新 module role、relation decision、impact scope、verify scope。
  写回共享语义维护记忆，供后续维护任务和图任务复用。
  不能直接修改物理 Skeleton Graph。
```

触发时机：

- agent 修改代码后，进入验证前。
- 用户提交或准备提交前。
- `git status` 检测到 tracked file 变化时。
- merge/rebase/pull 后。
- 手动调用 project network refresh 时。

GitChangeSet 最小模型：

```text
GitChangeSet:
  change_set_id
  build_id
  base_ref
  head_ref
  change_mode: working_tree | staged | commit_range | merge
  changed_files
  renamed_files
  deleted_files
  added_files
  diff_stats
  touched_skeleton_node_ids
  touched_skeleton_edge_ids
  semantic_refs_to_mark_stale
```

SemanticRepairWorkItem：

```text
work_item_id
change_set_id
skeleton_generation
repair_kind:
  module_role_review | relation_recheck | endpoint_recheck
  impact_scope_update | verify_scope_update | stale_conflict_review
assigned_scope
affected_node_ids
affected_edge_ids
previous_semantic_refs
required_evidence_refs
priority
status
```

维护 agent 的 prompt 契约：

```text
你是一名项目网络维护审查员。
你只负责审查 git change set 影响到的语义网络是否仍然成立。
你不能重建物理结构网，也不能新增没有 skeleton_edge_id 的 accepted 关系。
你需要对每个 affected semantic ref 给出 keep、update、reject、uncertain 或 needs_more_evidence。
当代码修改改变了模块职责、调用关系、prompt/tool/runtime 关系或验证范围时，你必须输出 semantic repair decision。
```

维护算法：

```text
1. git diff --name-status 找到 changed/renamed/deleted/added files。
2. 用 file path / previous stable refs 找到 affected skeleton nodes。
3. 对 changed files 重跑 file tree + AST + registry/domain extractors。
4. normalizer 生成 skeleton delta。
5. reverse adjacency 找到 inbound/outbound 受影响边。
6. stale propagation 标记 semantic overlay annotations。
7. 按 priority 生成 repair work items。
8. graph task 或 crawler 派发给 Network Maintenance Agent。
9. curator 校验 repair decisions，更新 semantic overlay generation。
```

优先级：

```text
deleted/renamed file > public endpoint signature changed > registry/prompt/tool changed
> cross-module relation changed > internal call changed > comment/doc-only changed
```

边界：

- git co-change 只能提升 repair priority，不能创建 accepted dependency。
- dirty working tree 可以生成 maintenance candidate，但发布 generation 需要固定 source snapshot。
- maintenance agent 更新的是 Semantic Overlay，不是 Skeleton Graph。

### 8.2.2 共享记忆维护模式

维护 agent 不应每次从空白开始。它应该共享项目网络记忆，复用已有语义判断和历史修复记录。

复用现有工作记忆能力：

```text
WorkingMemoryItem.scope = graph_scope
WorkingMemoryItem.visibility = shared_in_graph
WorkingMemoryItem.memory_semantics = decision | working_fact | temporal_event | conflict
```

新增逻辑概念：

```text
ProjectNetworkSharedMemory
```

它不是新的物理图，也不是完整上下文缓存，而是 Semantic Overlay 的可召回记忆层：

```text
module_role_memory
relation_decision_memory
endpoint_role_memory
impact_scope_memory
verify_scope_memory
maintenance_event_memory
stale_reason_memory
conflict_resolution_memory
```

缓存绑定键：

```text
project_id
build_id
skeleton_generation
semantic_generation
skeleton_node_id
skeleton_edge_id
file_hash
change_set_id
```

读取规则：

- 维护 agent 只读取与 affected skeleton refs 直接相关的 shared memory。
- 优先读 accepted / latest / non-stale 的 semantic memory。
- stale memory 可以读，但必须显示为 previous decision，不可直接复用为当前裁决。
- 召回结果只投影 summary、refs、decision、reason、freshness，不塞完整历史上下文。

写入规则：

- 维护 agent 可以写 `SemanticRepairDecision`、`maintenance_event`、`stale_reason`、`updated_relation_decision`。
- 维护 agent 不能写 Skeleton facts/nodes/edges。
- 维护 agent 写入必须带 `change_set_id`、affected skeleton refs、evidence refs。
- 同一 skeleton ref + change_set 的写入必须 idempotent，避免重复维护事件污染记忆。

失效规则：

```text
git change set touches skeleton refs
-> mark related semantic memory stale_candidate
-> maintenance agent reviews affected slice
-> keep/update/reject/uncertain
-> accepted repair memory supersedes old memory
```

这样维护 agent 可以“吃缓存”：

```text
已有模块职责
已有关系裁决
历史冲突解决
上次维护原因
验证范围经验
```

但不会盲目复用过期语义，因为所有记忆都绑定 skeleton generation、file hash 和 change set。

建议 memory policy：

```text
memory_read_policy:
  scopes: ["graph_scope"]
  visibility: ["shared_in_graph"]
  tags: ["project_network", "semantic_overlay", "maintenance"]
  freshness: "same_skeleton_generation_or_mark_stale"
  max_items: 24

memory_writeback_policy:
  scope: "graph_scope"
  visibility: "shared_in_graph"
  allowed_semantics: ["decision", "working_fact", "temporal_event", "conflict"]
  require_refs: ["skeleton_node_id|skeleton_edge_id", "change_set_id"]
  idempotency_key: "project_network:{change_set_id}:{skeleton_ref}:{decision_kind}"
```

### 8.3 发布

```text
semantic overlay candidate
-> curator validates anchor/hash/coverage/conflict
-> publish generation
-> previous generation superseded
```

## 9. 代码落地计划

### Phase 1：Skeleton 模型

新增：

```text
backend/file_management/project_structure/skeleton_models.py
```

定义：

- `SkeletonFactRecord`
- `SkeletonNodeRecord`
- `SkeletonEdgeRecord`
- `SkeletonGenerationRecord`
- `SkeletonSliceProjection`
- `SkeletonExtractionReport`

### Phase 2：Repository 扩展

修改：

```text
backend/task_system/project_network/repository.py
backend/task_system/project_network/store_models.py
```

新增表：

```text
project_network_skeleton_facts
project_network_skeleton_nodes
project_network_skeleton_edges
project_network_skeleton_generations
project_network_adjacency
project_network_reverse_adjacency
project_network_hierarchy
```

不要把 skeleton nodes/edges 塞进 generic candidates 里。它们是一等结构网络。

### Phase 3：Distributed Extractors

新增：

```text
backend/file_management/project_structure/skeleton_extractors/
  __init__.py
  file_tree_extractor.py
  deep_ast_extractor.py
  registry_extractor.py
  domain_extractor.py
  git_history_extractor.py
```

Extractor 输出 `SkeletonFactRecord`，不直接写最终 node/edge。

首版范围：

- file tree。
- Python Deep AST。
- git commit / changed file / rename / co-change 基础事实。
- tool catalog / prompt registry / agent registry / project_network templates。
- 简单 route/config/state refs 只做可确定项。

### Phase 4：Identity / Relation Normalizer

新增：

```text
backend/file_management/project_structure/skeleton_normalizer.py
backend/file_management/project_structure/skeleton_extractors/relation_normalizer.py
```

职责：

- fold raw facts into stable skeleton nodes。
- fold raw relation facts into skeleton edges。
- build adjacency / reverse adjacency。
- build hierarchy spine and ancestor index。
- merge evidence sets。
- mark exact / derived / unresolved。
- emit conflict candidates when identity or relation resolution is ambiguous。

### Phase 5：Skeleton Index Service

新增：

```text
backend/file_management/project_structure/skeleton_index_service.py
```

职责：

- run distributed extractors。
- upsert raw facts。
- run central normalizer。
- upsert skeleton generation。
- produce skeleton slice。
- mark stale。
- expose extraction report。

### Phase 6：Crawler Slice Index

新增：

```text
backend/file_management/project_structure/skeleton_slice_service.py
```

职责：

- read node card / edge card。
- expand local neighborhood。
- trace bounded path。
- produce agent-safe local slice。

### Phase 7：Semantic Overlay 模型

新增：

```text
backend/file_management/project_structure/semantic_models.py
backend/file_management/project_structure/repository.py
```

定义：

- `SemanticNodeAnnotationRecord`
- `SemanticEdgeAnnotationRecord`
- `SemanticReviewDecisionRecord`
- `SemanticOverlayGenerationRecord`

### Phase 8：图任务接线

修改：

```text
backend/task_system/project_network/template_catalog.py
backend/task_system/project_network/service.py
backend/task_system/project_network/projection.py
```

接线：

- graph task 的 source_snapshot 节点输入 skeleton generation ref。
- module/endpoint/relation 节点输入 skeleton slice。
- node result 输出 semantic annotations / edge decisions。
- service 将 work products 写入 semantic overlay。

### Phase 9：Crawler 与工具

复用 `06_network_crawler_index_and_review_plan.md`：

```text
project_network action=search|expand|trace|read_node|read_edge|crawl|review_edge|coverage
```

首版 crawler 只读 Skeleton + Semantic Overlay 的局部切片，不读全图。

### Phase 10：Git-driven Network Maintenance

新增：

```text
backend/file_management/project_structure/change_models.py + semantic_models.py
backend/file_management/project_structure/maintenance_service.py
```

修改：

```text
backend/task_system/project_network/repository.py
backend/task_system/project_network/template_catalog.py
backend/task_system/project_network/projection.py
backend/agent_system/profiles/runtime_profile_registry.py
```

职责：

- 生成 `GitChangeSetRecord`。
- 根据 changed files 定位 affected skeleton nodes/edges。
- 调用 skeleton index service 做 delta refresh。
- 标记 semantic overlay stale。
- 生成 `SemanticRepairWorkItemRecord`。
- 从现有 working memory 读取 shared semantic cache。
- 提供维护 agent 的 work order projection。
- 接收 `SemanticRepairDecisionRecord`，写回 shared memory，并交给 curator validate。

新增表：

```text
project_network_git_change_sets
project_network_maintenance_runs
project_network_semantic_repair_work_items
project_network_semantic_repair_decisions
```

不新增独立 cache DB。共享记忆复用：

```text
backend/memory_system/working_memory_service.py
backend/memory_system/working_memory_store.py
backend/memory_system/working_memory_models.py
```

维护 agent profile 增加：

```text
allowed_memory_scopes = (
  "graph_task_readonly",
  "layer_summary_readonly",
  "project_network_shared_read",
  "project_network_shared_write_candidate",
)
```

节点模板增加：

```text
memory_read_policy:
  scope: "graph_scope"
  visibility: "shared_in_graph"
  tags: ["project_network", "semantic_overlay", "maintenance"]

memory_writeback_policy:
  scope: "graph_scope"
  visibility: "shared_in_graph"
  allowed_kinds: ["semantic_repair_decision", "maintenance_event", "stale_reason"]
```

新增 agent 模板：

```text
project_network.network_maintenance_review
```

它不是建图 agent，而是维护 agent：只处理 git change set 影响到的 stale semantic refs。

prompt_contract：

```text
你是一名项目网络共享记忆维护员。
你只负责维护 git change set 影响到的语义网络记忆。
你必须先读取相关 ProjectNetworkSharedMemory：旧模块职责、旧关系裁决、上次维护原因、冲突记录和验证范围。
你需要判断旧记忆是否仍成立：keep、update、reject、uncertain、needs_more_evidence。
你不能修改 Skeleton Graph，也不能新增没有 skeleton_node_id 或 skeleton_edge_id 的 accepted 语义关系。
你写回的维护记忆必须绑定 change_set_id、skeleton refs、evidence refs 和 freshness。
```

### Phase 11：Projection / UI

新增或扩展：

```text
backend/task_system/project_network/projection.py
```

输出：

- skeleton generation status。
- local slice。
- frontier。
- stale refs。
- unresolved/conflict refs。
- semantic overlay coverage。
- maintenance run status。
- repair work item queue。
- git change set summary。

不默认展示全图。

## 10. MVP 工程落地方案

这一节是可执行工程方案。第一期只做物理 Skeleton Graph 闭环，不做完整语义网络、不做前端、不引入外部图数据库。

### 10.1 MVP 目标

第一期交付一个真实可运行的结构网络构建器：

```text
输入：
  project root
  build_id
  scope roots

处理：
  file tree extract
  Python Deep AST extract
  git changed-file/co-change extract
  raw facts persist
  central normalize
  skeleton nodes/edges persist
  hierarchy index persist
  local slice query

输出：
  SkeletonGenerationRecord
  extraction report
  node/edge counts
  node card / edge card
  expand(node_id)
```

MVP 不碰 graph runtime 主循环，不修改 agent 执行链路。先把物理网建起来，让后续图任务能消费。

### 10.2 工程边界

只改这些区域：

```text
backend/task_system/project_network/
backend/capability_system/capabilities/code_intelligence/
```

首版不改：

```text
graph_system/
runtime/
frontend/
API routes
database migrations outside project_network repository
```

这样风险可控，且不会把 graph core 改成项目网络专用系统。

### 10.3 文件级实施清单

新增文件：

```text
backend/file_management/project_structure/skeleton_models.py
backend/file_management/project_structure/skeleton_extractors/__init__.py
backend/file_management/project_structure/skeleton_extractors/file_tree_extractor.py
backend/file_management/project_structure/skeleton_extractors/deep_ast_extractor.py
backend/file_management/project_structure/skeleton_extractors/git_history_extractor.py
backend/file_management/project_structure/skeleton_normalizer.py
backend/file_management/project_structure/skeleton_index_service.py
backend/file_management/project_structure/skeleton_slice_service.py
```

修改文件：

```text
backend/task_system/project_network/repository.py
backend/task_system/project_network/store_models.py
backend/task_system/project_network/projection.py
backend/task_system/project_network/__init__.py
```

暂不新增 native tool。等 service smoke 通过后，再接 `project_network action=...` 工具。

### 10.4 数据库表

在 `ProjectNetworkRepository._ensure_schema()` 中新增：

```text
project_network_skeleton_facts
project_network_skeleton_nodes
project_network_skeleton_edges
project_network_skeleton_generations
project_network_hierarchy
project_network_adjacency
project_network_reverse_adjacency
```

最小字段：

```text
project_network_skeleton_facts:
  fact_id PRIMARY KEY
  build_id
  generation
  source_kind
  subject_ref
  predicate
  object_ref
  object_literal
  qualifiers_json
  evidence_refs_json
  anchor_refs_json
  extractor_id
  extractor_version
  content_hash
  confidence
  created_at

project_network_skeleton_nodes:
  node_id PRIMARY KEY
  build_id
  generation
  node_kind
  stable_ref
  display_name
  path
  layer_kind
  hierarchy_path
  parent_node_ids_json
  ancestor_node_ids_json
  anchor_ref
  file_hash
  confidence
  status
  payload_json

project_network_skeleton_edges:
  edge_id PRIMARY KEY
  build_id
  generation
  edge_kind
  src_node_id
  dst_node_id
  dst_candidate_ref
  src_anchor_ref
  dst_anchor_ref
  evidence_refs_json
  confidence
  resolution_status
  freshness
  payload_json
```

### 10.5 模块职责

`skeleton_models.py`

- 只定义 dataclass 和 `to_dict/from_dict`。
- 不读文件、不访问数据库、不做归一。

`file_tree_extractor.py`

- 输入 `root_dir`、`scope_roots`。
- 输出 project/folder/file_module facts。
- 生成 `contains` facts。
- 使用现有 `WorkspaceFileService` 的排除规则，避免重新写一套搜索边界。

`deep_ast_extractor.py`

- 输入 Python 文件列表。
- 调用 `build_python_file_module_ast_index()`。
- 输出 file_module/class/function/call/import facts。
- 输出 contains/defines/calls_text/imports_text facts。
- 不做跨文件调用解析。

`git_history_extractor.py`

- 输入 scope roots 和 max commits。
- 调用只读 git 命令读取 changed files / rename / co-change。
- 输出 commit/file_revision/co_changes_with facts。
- co-change 只标 `confidence=derived`，不能成为 hard dependency。

`skeleton_normalizer.py`

- 输入 facts。
- 生成 stable nodes/edges。
- 生成 hierarchy_path、ancestor index。
- 生成 adjacency/reverse adjacency。
- 对 unresolved 关系保留 candidate，不丢弃。

`skeleton_index_service.py`

- 对外提供 `build_skeleton_generation()`。
- 顺序调用 extractors、repository、normalizer。
- 返回 extraction report。
- 不调用模型。

`skeleton_slice_service.py`

- 对外提供 `read_node()`、`read_edge()`、`expand()`、`trace_local()`。
- 只读 repository。
- 输出 agent-safe local slice。

### 10.6 MVP 执行顺序

按这个顺序实施，不并行乱接线：

```text
Step 1: skeleton_models.py
Step 2: repository 表与 CRUD
Step 3: file_tree_extractor.py
Step 4: deep_ast_extractor.py
Step 5: skeleton_normalizer.py
Step 6: skeleton_index_service.py
Step 7: skeleton_slice_service.py
Step 8: git_history_extractor.py
Step 9: projection/__init__ 导出
Step 10: smoke 验证
```

其中 Step 1-7 必须先形成闭环；Git 可以在闭环之后接入，避免第一版被历史分析拖住。

### 10.7 首版算法

stable node id：

```text
sha1(build_id + generation + stable_ref)
```

stable edge id：

```text
sha1(build_id + generation + src_stable_ref + edge_kind + dst_stable_ref_or_candidate)
```

hierarchy path：

```text
project stable ref
-> folder path refs
-> file path ref
-> ast qualname ref
-> call/import ast path ref
```

normalization priority：

```text
exact registry id
exact file path
exact AST anchor / qualname
derived import/call candidate
git historical candidate
unresolved text
```

expand 默认顺序：

```text
children contains edges
outbound exact/derived edges
inbound edges
unresolved candidates
ancestors
```

这让 agent 先有层级落脚点，再横向爬行。

### 10.8 Smoke 验证

不用新增测试文件。用临时脚本真实调用 service：

```text
python -m compileall backend/file_management/project_structure backend/task_system/project_network backend/capability_system/capabilities/code_intelligence

smoke 1:
  build_skeleton_generation(scope_roots=["backend/task_system/project_network"])
  assert facts > 0
  assert nodes > 0
  assert edges > 0
  assert hierarchy_paths present

smoke 2:
  find file_module node for service.py
  expand(file_module_node)
  assert children include class/function nodes

smoke 3:
  read edge card
  assert evidence_refs or anchor_refs present

smoke 4:
  no model call
  no graph runtime modification
```

### 10.9 工程工作量预算

可执行预算：

```text
MVP physical skeleton graph:
  1.5-2.5 engineering days

repository + models:
  0.5 day

file tree + deep AST extractors:
  0.5 day

normalizer + hierarchy/adjaency:
  0.5-1 day

service + slice smoke:
  0.5 day

git extractor:
  0.5 day after core loop
```

风险最高点：

- stable identity 设计不稳会导致后续 generation 难维护。
- repository 方法太散会导致 service 难用。
- normalizer 如果做太多智能解析，会越权进入语义判断。

控制策略：

- 第一版只做 exact/derived/unresolved 三档。
- semantic 判断全部留给 graph task agent。
- crawler 工具等 service smoke 通过后再接。

### 10.10 完成定义

MVP 完成不以“文档完整”为准，而以物理网可用为准：

```text
能构建
能持久化
能展开
能追证据
能看到层级路径
能给 graph task 提供 skeleton slice
```

到这里才进入下一阶段：图任务 agent 基于 skeleton slice 建 Semantic Overlay。

### 10.11 维护闭环扩展

物理网 MVP 通过后，立即接 Git-driven maintenance。它不是另一个大系统，而是增量维护入口。

新增文件：

```text
backend/file_management/project_structure/change_models.py + semantic_models.py
backend/file_management/project_structure/maintenance_service.py
```

最小模型：

```text
GitChangeSetRecord
NetworkMaintenanceRunRecord
SemanticRepairWorkItemRecord
SemanticRepairDecisionRecord
```

最小服务 API：

```text
collect_git_change_set(mode="working_tree|staged|commit_range")
plan_skeleton_delta(change_set_id)
refresh_affected_skeleton(change_set_id)
mark_semantic_refs_stale(change_set_id)
create_repair_work_items(change_set_id)
build_maintenance_agent_projection(work_item_id)
accept_repair_decision(decision)
```

维护 smoke：

```text
1. 修改一个真实 Python 文件。
2. collect_git_change_set(mode="working_tree") 能识别 changed file。
3. plan_skeleton_delta 能找到 file_module node。
4. refresh_affected_skeleton 重跑该文件 AST extractor。
5. mark_semantic_refs_stale 能标记相关 semantic annotation stale。
6. create_repair_work_items 生成 relation/module/endpoint repair item。
7. maintenance projection 包含 affected nodes、edges、previous semantic refs、required evidence。
8. working memory 中已有同一 skeleton ref 的 semantic decision 时，maintenance projection 能召回 shared memory summary。
9. accept_repair_decision 能写回 graph_scope/shared_in_graph working memory，且带 change_set_id 和 skeleton refs。
```

维护闭环的完成定义：

```text
代码一变，网络知道哪里变了。
物理网先刷新，语义网再标 stale。
维护 agent 只处理受影响切片。
curator 再决定是否更新 semantic generation。
```

### 10.12 首轮实施记录（2026-07-01）

已落地文件：

```text
backend/file_management/project_structure/skeleton_refs.py
backend/file_management/project_structure/skeleton_models.py
backend/file_management/project_structure/skeleton_extractors/file_tree_extractor.py
backend/file_management/project_structure/skeleton_extractors/deep_ast_extractor.py
backend/file_management/project_structure/skeleton_extractors/git_history_extractor.py
backend/file_management/project_structure/skeleton_normalizer.py
backend/file_management/project_structure/skeleton_index_service.py
backend/file_management/project_structure/skeleton_slice_service.py
backend/file_management/project_structure/change_models.py + semantic_models.py
backend/file_management/project_structure/maintenance_service.py
backend/task_system/project_network/repository.py
```

首轮实现边界：

- 物理层只保存结构事实和证据链路，不保存业务职责。
- File tree 生成 repo/folder/file 物理节点和 contains 边。
- Deep AST 生成 py_module/py_class/py_function/py_method 节点和 defines/imports_text/calls_text 边。
- 函数节点保存参数、返回注解、line range、call site anchors。
- normalizer 给每个节点补齐 parent、ancestor、direct_child_count_by_kind、direct_child_node_ids_by_kind、descendant_endpoint_node_ids_by_kind、inbound/outbound edge counts、resolved call targets、unresolved call candidates。
- slice service 以 `SkeletonNodeCard / SkeletonSliceProjection` 返回物理切片，并通过 `semantic_overlays` 读取现有 project_network candidates，形成“物理结构 + 语义路标”的叠加视图。
- maintenance service 使用 git working tree 建立 `GitChangeSetRecord`，映射 affected skeleton nodes/edges，并生成 `SemanticRepairWorkItemRecord`。
- 共享记忆不另建库；maintenance projection 预留接入 `WorkingMemoryService graph_scope/shared_in_graph`。

真实 smoke 结果：

```text
scope: backend/file_management/project_structure
fact_count: 3668
node_count: 397
edge_count: 2224
service.py file node: found
expand(service.py, depth=2): nodes=38 edges=153
git changed files: 47
touched skeleton nodes: 25
touched skeleton edges: 50
semantic repair work items: 25
```

Agent 试用结论：

```text
物理层已经能让我顺着 folder -> file -> module -> class -> method/function 爬行。
它能显著减少盲目全文搜索：文件节点能看到下方 endpoint 数量，class 节点能看到 method，method 节点能看到参数、返回和调用候选。

但“顺手的多级跳转”不能靠物理层继续加职责字段完成。
缺少 Semantic Overlay 时，agent 仍然不知道应该优先读哪条路线：
  例如维护链路应优先看 maintenance_service -> normalizer -> repository schema，
  这种路线是语义指引，不是物理事实。

因此下一步要做 Semantic Route Overlay：
  attaches_to skeleton node/edge
  records purpose / recommended next hops / review focus / verification target
  may span multiple physical nodes
  must keep every hop anchored to skeleton_node_id or skeleton_edge_id
```

这次试用强化了边界裁决：物理层负责“可爬”，语义层负责“会走”。如果把“该层负责什么业务”写进 Skeleton Graph，会污染物理层；如果没有物理层，Semantic Overlay 又无法稳定落地和维护。

本轮刻意不做：

- 不把 semantic responsibility 写入 skeleton node payload。
- 不做完整跨文件调用图，只做本文件可解析调用和 unresolved text candidate。
- 不接 graph runtime 主循环。
- 不新增测试文件。
- 不把全图塞进 prompt。

## 11. 验收标准

首版验收：

- 系统能从真实项目目录生成 folder/file_module skeleton nodes。
- 系统能从 `FileModuleAstIndex` 生成 class/function/call/import skeleton nodes 和 contains/calls_text/imports_text edges。
- 系统能生成 hierarchy spine：project -> folder/system candidate -> file_module -> endpoint -> evidence point。
- crawler 能从 project/folder 纵向 descend 到 module/endpoint，再沿 relation 横向 traverse，并向上 ascend 汇总 impact scope。
- 系统能从 tool/prompt/agent/profile/template registry 生成 registry nodes/edges。
- graph task module node 能收到 skeleton slice，而不是重新从空白文本开始审查。
- agent 产出的 semantic edge decision 必须引用 skeleton_edge_id。
- agent 提出的新语义关系如果没有 skeleton_edge_id，只能进入 missing_physical_edge_request 或 coverage_gap，不能进入 accepted。
- accepted semantic edge 没有 evidence_ref 时被 curator 拒绝。
- 文件 hash 变化后，相关 skeleton edge 和 semantic annotation 能标 stale。
- git working tree 变化后，能生成 `GitChangeSetRecord`、affected skeleton refs 和 semantic repair work items。
- Network Maintenance Agent 的 repair decision 只能更新 Semantic Overlay，不能直接改 Skeleton Graph。
- Network Maintenance Agent 能读取 graph_scope/shared_in_graph 的 ProjectNetworkSharedMemory，并把 repair decision 写回同一共享记忆域。

验证方式：

```text
compileall backend/file_management/project_structure backend/task_system/project_network backend/capability_system
skeleton smoke: extract small scope -> nodes>0 edges>0
semantic smoke: ingest edge decision -> overlay record points to skeleton_edge_id
stale smoke: changed hash simulation -> affected skeleton/semantic refs stale
git maintenance smoke: dirty tracked file -> change set -> skeleton delta -> repair work item
shared memory smoke: existing relation memory -> maintenance projection cache hit -> repair decision writeback
code reading: graph core 没有项目网络专用分支
```

## 12. 不做的事

首版不做：

- 不引入外部图数据库。
- 不做模型直接建 hard fact。
- 不做完整 Python interprocedural call graph。
- 不把函数变成 graph task 调度节点。
- 不把语义图混进 skeleton graph 表。
- 不把全图塞进 prompt。

后续再做：

- TypeScript/TSX extractor。
- 更强跨文件 import/call resolution。
- FastAPI/frontend route 完整双向映射。
- prompt/tool/runtime/control route domain extractor。
- 前端局部图探索视图。

## 13. 成熟方案参考

本计划参考的成熟工程化方向：

- Git commit-graph：提交历史本身是可加速遍历的图结构，包含 commit、parents、commit date、root tree 和 generation number。用于本项目的历史拓扑、co-change、stale 和影响范围骨架。
- Tree-sitter：提供 concrete syntax tree 和增量解析能力，适合多语言语法骨架和编辑态刷新。
- SCIP / LSIF 系列：把 definition / reference / implementation 等代码导航能力标准化为语言无关索引，适合作为跨文件符号边参照。
- Kythe：用语言无关 graph schema 连接编译器、构建系统、编辑器、代码浏览器和静态分析事实；其“宁可输出不完整数据，也不要输出错误数据”的原则应作为 Skeleton Graph 的硬规则。

官方资料：

- https://git-scm.com/docs/commit-graph
- https://tree-sitter.github.io/tree-sitter/
- https://scip-code.org/
- https://kythe.io/docs/kythe-overview.html

## 14. 最终架构图

```text
                 ┌──────────────────────────┐
                 │ Source / Registry Facts   │
                 └────────────┬─────────────┘
                              │
                              ▼
                 ┌──────────────────────────┐
                 │ Skeleton Extractors       │
                 │ file tree / AST / registry│
                 └────────────┬─────────────┘
                              │
                              ▼
                 ┌──────────────────────────┐
                 │ Skeleton Graph Store      │
                 │ hard nodes / hard edges   │
                 └────────────┬─────────────┘
                              │ skeleton slice
                              ▼
                 ┌──────────────────────────┐
                 │ Graph Task Agents         │
                 │ semantic review/build     │
                 └────────────┬─────────────┘
                              │ semantic decisions
                              ▼
                 ┌──────────────────────────┐
                 │ Semantic Overlay Store    │
                 │ node/edge annotations     │
                 └────────────┬─────────────┘
                              │
                              ▼
                 ┌──────────────────────────┐
                 │ Curator / Publish Gate    │
                 └────────────┬─────────────┘
                              │
                              ▼
                 ┌──────────────────────────┐
                 │ Published Generation      │
                 └──────────────────────────┘
```

结论：

```text
先让系统建立真实骨架网络。
再让图任务 agent 顺着骨架建立语义网络。
最后让 curator 发布可用 generation。
```

