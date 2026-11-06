# 项目网络级索引与爬行审查计划

状态：网络级纠偏设计稿，待审阅后实施  
日期：2026-07-01

## 1. 需求裁决

用户要的不是更强的搜索工具，也不是单文件 AST outline。目标是让 agent 像蜘蛛一样建立项目网络，并顺着网络爬行、审查、索引和维护项目语义空间。

准确目标：

```text
Deep AST Spine
-> Project Network Index
-> Network Crawler Session
-> Relation Review / Curator
-> Published Project Semantic Network Generation
-> Incremental Refresh / Re-crawl
```

这意味着系统必须提供三类能力：

1. **网络级索引**：把系统、文件夹、文件模块、class、function endpoint、call site、prompt、tool、route、state 等统一成可寻址节点和边。
2. **网络级审查**：agent 不再只读文件，而是沿 seed、frontier、edge evidence、coverage gap 和 conflict route 做审查。
3. **网络级操作接口**：agent 可以通过图 API 搜索、展开、追踪、确认、拒绝、标记 stale、申请下一跳，而不是每次从 `rg` 重新猜结构。

一句话裁决：

```text
AST 是骨架；Project Network Index 是神经网络；Crawler Session 是 agent 的移动方式；Review Decision 是边能否进入可发布图的裁决。
```

## 2. 当前系统差距

现有代码已经具备一部分承载能力：

| 层 | 已有文件 | 当前能力 | 差距 |
| --- | --- | --- | --- |
| Deep AST | `capability_system/capabilities/code_intelligence/python_ast_indexer.py` | 生成单文件 AST anchors / functions / calls / assignments | 还未持久化到项目网络 evidence store |
| Work Product | `task_system/project_network/work_product_models.py` | 承载 `module_index`、`endpoint_index`、`relation_candidates` 等节点产物 | 产物还没有归一成一等 network nodes / edges |
| Store | `task_system/project_network/repository.py` | 保存 build、work products、evidence、candidates、layers、generations、traces | 缺少 node/edge/frontier/traversal/review decision 表 |
| Service | `task_system/project_network/service.py` | 接收 graph node result 并写入 store planes | 缺少把 work products 投影为可爬行网络的 indexing service |
| Projection | `task_system/project_network/projection.py` | 展示 build / layer / product 统计 | 缺少 crawler projection 和局部网络视图 |
| Templates | `task_system/project_network/template_catalog.py` | 有 module/index/relation/validate/curate 节点模板 | 缺少 crawler agent 契约和 network traversal 工作单 |

关键缺口：

```text
已有的是“建图产物仓库”。
缺的是“可遍历项目网络”。
```

## 3. 权威链路

网络级系统必须按单向权威链路工作，避免 agent 和系统互相抢事实权：

```text
Source / Registry / Tool / Prompt / Runtime Facts
-> Deep AST / Deterministic Extractors
-> Work Products
-> Network Indexer
-> Network Crawler Session
-> Agent Review Decision
-> Curator Validation
-> Published Generation
```

权威分工：

| 模块 | 职责 | 不允许 |
| --- | --- | --- |
| Deep AST | 生成 hard anchors、line ranges、call/import text | 不判断系统语义 |
| Work Product | 承载节点输出和证据 | 不直接发布图 |
| Network Indexer | 把 work products 归一成 nodes / edges | 不把 hypothesis 边升为 accepted |
| Crawler Session | 维护 seed、frontier、visited、crawl path | 不替 agent 做语义裁决 |
| Agent Review | 审查边、解释关系、提出 accepted/rejected/uncertain | 不伪造无证据边 |
| Curator | 校验 coverage、conflict、stale、schema | 不修改源码 |
| Publish Gate | 发布 generation | 不接受未校验候选 |

## 4. Project Network Index 模型

新增一等网络索引层，不能只把关系藏在 `payload_json` 里。

### 4.1 节点

```text
ProjectNetworkNodeRecord:
  network_node_id
  build_id
  generation
  node_kind:
    project | system | folder | file_module | class | function_endpoint
    call_site | import_binding | prompt | tool | route | state | config | artifact
  stable_ref
  display_name
  path
  anchor_ref
  file_hash
  layer_id
  source_work_product_id
  evidence_refs
  status: candidate | accepted | rejected | stale | published
  confidence: deterministic | derived | hypothesis | reviewed
  payload
  metadata
```

节点原则：

- `file_module` 是 agent 常规读取和调度的最小模块单位。
- `function_endpoint`、`class`、`call_site` 是可爬行末梢，不是 graph task node。
- 没有 `stable_ref` 的节点不能进入 published generation。
- 没有 `anchor_ref` 的 code node 只能是 locator 或 hypothesis。

### 4.2 边

```text
ProjectNetworkEdgeRecord:
  network_edge_id
  build_id
  generation
  edge_kind:
    contains | imports | calls | configures | registers | exposes
    routes_to | uses_tool | uses_prompt | reads_state | writes_state
    depends_on | verifies | publishes | conflicts_with | supersedes
  src_node_id
  dst_node_id
  src_anchor_ref
  dst_anchor_ref
  evidence_chain_refs
  source_work_product_id
  review_status: unreviewed | accepted | rejected | uncertain | stale
  confidence: deterministic | derived | hypothesis | reviewed
  weight
  freshness
  payload
```

边原则：

- `contains`、AST parent-child 可以 deterministic。
- `imports` 可以 deterministic 或 derived，视解析精度而定。
- `calls` 首版保留 unresolved text；跨文件目标只能 candidate。
- `registers/routes_to/uses_tool/uses_prompt/state` 需要 domain extractor 或 agent review。
- `accepted` 边必须有 evidence chain；没有证据只能 `hypothesis` 或 `uncertain`。

### 4.3 Frontier

```text
ProjectNetworkFrontierItem:
  frontier_id
  session_id
  build_id
  source_node_id
  target_node_id
  edge_id
  priority
  crawl_reason
  expected_read_unit
  required_evidence_refs
  status: queued | expanded | skipped | blocked | completed
  blocker_reason
```

frontier 是动态尾该放的东西。完整网络留在 store，当前上下文只投影 seed、visited、frontier、top edges 和 blockers。

### 4.4 Traversal Session

```text
ProjectNetworkTraversalSession:
  session_id
  build_id
  generation
  user_goal
  seed_node_ids
  visited_node_ids
  visited_edge_ids
  active_frontier_ids
  crawl_budget
  crawl_policy
  coverage
  status
```

## 5. Crawler API

agent-visible 能力应尽量少而强，不再暴露一堆零散搜索命令。

首版工具建议：

```text
project_network_search
  输入 query、node_kinds、edge_kinds、scope、limit
  输出 locator-only nodes / edges / recommended seeds

project_network_expand
  输入 node_id、depth、edge_kinds、direction、limit
  输出 neighbors、frontier、coverage、blocked edges

project_network_trace
  输入 source_node_id、target_node_id、edge_kinds、max_depth
  输出 candidate paths、evidence chains、uncertain gaps

project_network_read_node
  输入 node_id
  输出 node card、anchors、read windows、local edges

project_network_read_edge
  输入 edge_id
  输出 edge card、evidence chain、review state、required next read

project_network_crawl
  action=start|continue|pause|status
  输入 goal、seeds、budget、policy
  输出 current session projection

project_network_review_edge
  输入 edge_id、decision、evidence_refs、reason
  输出 review decision record

project_network_coverage
  输入 scope、generation
  输出 covered / uncovered / stale / conflict summary
```

工具契约：

- search/expand/trace 只给 locator 和下一步建议，不能伪装成完整源码。
- read_node/read_edge 给 agent 当前所需的结构卡和证据链。
- review_edge 只接受 agent 明确裁决，不自动替 agent 决定。
- crawl session 只维护控制状态，不发布 generation。

## 6. Agent 爬行工作契约

网络 crawler agent 的 prompt 不能写成开发说明，必须是可执行角色契约。

建议契约：

```text
你是一名项目网络爬行审查员。
你只负责围绕当前目标在项目网络中选择下一跳、审查边证据、补齐覆盖缺口。
你不能把没有 evidence_ref、anchor_ref 或 exact read receipt 的关系标为 accepted。
你需要优先沿高价值 frontier 爬行：入口、注册、调用、prompt、tool、state、runtime 边优先。
你每次行动必须说明：当前节点、选择的边、需要读取的证据、接受/拒绝/不确定的理由。
当网络缺边、边过期或证据不足时，你要输出 correction proposal 或 coverage gap，而不是编造关系。
你的输出必须是结构化的 crawl decision 和 edge review decision。
```

## 7. 网络级审查算法

不是一个搜索机制包打天下，而是多层网络控制：

```text
1. Seed Selection
   从用户目标、已发布系统节点、路径关键词、AST anchors、tool/prompt registry 中找 seed。

2. Frontier Expansion
   按 edge_kind、node_kind、freshness、coverage gap 和用户目标生成下一跳。

3. Evidence Read
   对候选边读取最小必要 read windows 或 node card，不读无关全文。

4. Edge Review
   agent 裁决 accepted / rejected / uncertain / stale。

5. Network Update
   记录 review decision，更新 edge status 和 frontier。

6. Coverage Check
   看目标范围是否覆盖系统、模块、endpoint、relation，决定继续爬或收口。

7. Curator Publish
   只有 curator 校验通过后，generation 才能发布。
```

优先级 scoring 首版可以简单：

```text
score =
  goal_relevance
  + edge_kind_weight
  + node_kind_weight
  + stale_penalty
  + uncertainty_bonus
  + coverage_gap_bonus
  + conflict_bonus
```

成熟原则：

- 常态定位仍可用 `rg/search_text/codebase_search`，但它们只能提供 seed 或 evidence locator。
- 网络爬行负责建立连接，不替代 exact read。
- graph task 负责大规模建网生产线，crawler 负责 agent 的交互式网络行走。

## 8. 上下文投影

agent 当前上下文不应塞全图，只放“当前爬行切面”：

```text
Current Goal
Active Traversal Session
Seed Nodes
Visited Nodes / Edges
Top Frontier Items
Relevant Node Cards
Relevant Edge Cards
Coverage Gaps
Required Next Actions
```

动态尾只放本回合变化：

```text
newly_expanded_nodes
newly_reviewed_edges
new_frontier
blocked_edges
fresh evidence receipts
next crawl recommendation
```

稳定网络事实进入 store，不反复塞记忆。变化小的事实只保留 generation ref、node id、edge id、hash 和 freshness。

## 9. 实施架构

### Phase 1：网络索引模型

新增：

```text
backend/task_system/project_network/network_models.py
```

定义：

- `ProjectNetworkNodeRecord`
- `ProjectNetworkEdgeRecord`
- `ProjectNetworkReviewDecisionRecord`
- `ProjectNetworkTraversalSession`
- `ProjectNetworkFrontierItem`
- `ProjectNetworkSliceProjection`

### Phase 2：Repository 扩表

修改：

```text
backend/task_system/project_network/repository.py
backend/task_system/project_network/store_models.py
```

新增表：

```text
project_network_nodes
project_network_edges
project_network_review_decisions
project_network_traversal_sessions
project_network_frontier_items
```

注意：这是新增网络平面，不替换 work product 平面。work product 是生产证据，network nodes/edges 是可爬行索引。

### Phase 3：Network Indexer

新增：

```text
backend/task_system/project_network/network_indexer.py
```

职责：

- 从 `FileModuleAstIndex` 生成 module/class/function/call/import 节点和 contains/imports/calls 候选边。
- 从 `module_index`、`endpoint_index`、`relation_candidates` work products 生成 semantic nodes/edges。
- 保留 source_work_product_id、evidence_refs、anchor_refs。
- 只做归一，不做语义裁决。

### Phase 4：Crawler Service

新增：

```text
backend/task_system/project_network/crawler_service.py
```

职责：

- start/continue traversal session。
- search/expand/trace/read_node/read_edge。
- 生成 frontier。
- 写 review decision。
- 构造 agent-visible slice projection。

### Phase 5：工具入口

新增或扩展 native tool：

```text
project_network_search
project_network_expand
project_network_trace
project_network_read_node
project_network_read_edge
project_network_crawl
project_network_review_edge
project_network_coverage
```

如果工具数量过多，首版可以合并成一个 `project_network` action tool，但 action 必须稳定：

```text
action=search|expand|trace|read_node|read_edge|crawl|review_edge|coverage
```

建议首版采用单工具多 action，降低 agent 操作负担。

### Phase 6：Graph Task 接线

修改：

```text
backend/task_system/project_network/service.py
backend/task_system/project_network/template_catalog.py
```

接线原则：

- `ProjectNetworkBuildService.accept_node_result()` 接收 work product 后，可调用 `NetworkIndexer.ingest_work_products()`。
- module/endpoint/relation 节点产物进入网络候选层。
- aggregator/curator 节点可消费 network coverage 和 conflict projection。
- graph runtime 不直接懂网络语义，避免把 graph core 改成项目网络专用系统。

### Phase 7：Projection / API / 前端

新增投影：

```text
build_project_network_slice_projection()
build_project_network_crawler_projection()
```

前端显示：

- 当前 seed。
- 已访问路径。
- frontier 队列。
- edge review 状态。
- coverage gaps。
- next actions。

不显示全图为主界面，防止大项目爆炸；全图只作为搜索/过滤/展开视图。

## 10. 审查图任务如何使用

graph task 负责规模化生产：

```text
system_classify
-> folder_index
-> module_index
-> endpoint_extract
-> relation_trace
-> layer_aggregate
-> cross_layer_validate
-> conflict_curate
-> generation_publish
```

Network Indexer 负责把这些产物归一成：

```text
ProjectNetworkNodeRecord
ProjectNetworkEdgeRecord
```

Crawler Agent 负责交互式爬行：

```text
seed
-> expand
-> read_node/read_edge
-> review_edge
-> update frontier
-> coverage
```

二者关系：

```text
Graph Task = 建网生产线
Crawler = 用网和补网的操作方式
Network Index = 二者共享的可遍历底座
```

## 11. 验收标准

首版必须真实通过：

- 能从一个真实 Python 文件的 `FileModuleAstIndex` 写出 network nodes / edges。
- 能从 `module_index` 或 `relation_candidates` work product 写出候选语义边。
- `expand(file_module_node)` 能返回 class/function/import/call neighbors。
- `trace(A, B)` 能返回至少一条 evidence-chain candidate path 或明确说明无路径。
- `review_edge(edge_id, accepted/rejected/uncertain)` 能写入 review decision，并更新 edge review 状态。
- crawler projection 只包含当前 session slice，不把全图塞进上下文。
- 没有 evidence/anchor 的边不能变成 accepted。

验证方式：

```text
compileall backend/task_system/project_network backend/capability_system
repository smoke: create build -> ingest AST index -> list nodes/edges
crawler smoke: start session -> expand node -> review edge -> coverage projection
code reading: graph core 不新增项目网络专用分支
```

## 12. 不做的事

首版不做：

- 不做全语言 LSP 图谱。
- 不做大型图数据库依赖。
- 不把 graph runtime 改成项目网络 runtime。
- 不让模型直接生成 hard facts。
- 不把所有函数升级为 graph task node。
- 不把 crawler frontier 长期塞入 prompt memory。

后续再做：

- TypeScript/TSX parser profile。
- 更强 import/call resolution。
- domain extractors：FastAPI route、tool registry、prompt slot、state store、DB schema。
- 前端交互式局部图。
- stale propagation 和 incremental re-crawl。

## 13. 最终判断

当前应从“项目网络可爬行索引”开始，而不是继续强化单个搜索工具。

正确落地顺序：

```text
Network Models
-> Repository Tables
-> Network Indexer
-> Crawler Service
-> Single Action Tool
-> Graph Build Service Integration
-> Projection / API / UI
```

这样 agent 才能真正做到：

```text
找到入口
顺边爬行
审查证据
更新网络
保持覆盖
按 generation 发布
```
