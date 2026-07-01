# 项目级语义审查工作流设计

状态：工作流设计稿，待据此实施图任务编排  
日期：2026-07-01

## 1. 核心裁决

项目级语义网络不能只靠“分层审查”四个字。真正要固定的是每一层怎么进入、怎么分片、agent 审什么、共享状态怎么读写、产物怎么归一、汇总节点怎么收口。

最终工作流采用两遍结构：

```text
第一遍：自上而下结构分解
  project scope
  -> system candidates
  -> folder scopes
  -> file module shards
  -> endpoint / relation hints

第二遍：自下而上语义汇总
  file module review products
  -> folder layer summary
  -> system layer summary
  -> project semantic index
  -> curator publish candidate
```

这不是让上层 agent 一次性决定全项目语义。上层先负责切分和约束，文件层负责最小语义事实，后续再把文件级事实逐层汇总成索引。

最重要的执行原则：

```text
物理骨架由系统抽取。
结构分解自上而下。
语义判断以单文件模块为原子。
汇总与索引自下而上。
共享状态只存结构化 refs、channels、coverage 和 layer summaries。
worker agent 只能提交 typed work product，不能直接改共享状态或发布语义 generation。
```

## 2. 当前系统可复用底座

现有代码已经具备承载这个工作流的基础：

```text
file_management.project_structure
  Skeleton Graph
  Semantic Overlay Store
  navigation / path candidates
  git change set / maintenance work items

task_system.project_network
  ProjectNetworkBuildContract
  ProjectNetworkLayerPlan
  SemanticShardSpec
  ProjectNetworkNodeTemplate
  GraphBuildWorkProductEnvelope
  WorkProductChannel
  ProjectNetworkBuildService
  Evidence / Candidate / Layer / Generation / Trace stores

graph_system / harness
  TaskGraphDefinition
  ExecutableGraphConfig
  GraphLoop
  GraphNodeWorkOrder
  graph node -> single-agent TaskRun
```

因此项目级审查不需要另写调度器。它应该表现为：

```text
LayerPlan -> ShardPlan -> TaskGraphDefinition -> GraphNodeWorkOrder -> single-agent review -> WorkProductEnvelope -> channel reduce -> LayerSummary
```

当前缺口不是底座不存在，而是缺少一份明确的“项目级审查工作流合同”。本文件补上这个合同。

## 3. 共享状态模型

共享状态不是聊天记录，也不是所有 agent 都能随便追加的上下文池。它必须是结构化的、可版本化的、可投影的状态平面。

### 3.1 Shared State 的组成

每个项目网络 build 拥有一个共享状态视图：

```text
ProjectNetworkSharedReviewState:
  build_id
  build_kind
  build_mode
  skeleton_generation_ref
  source_snapshot_refs
  active_layer_id
  upstream_layer_index_refs
  upstream_layer_summary_refs
  shard_plan_ref
  work_product_channel_refs
  evidence_channel_refs
  conflict_refs
  coverage_map
  current_generation_lineage
  validation_policy
  publish_policy
```

这份共享状态读取自现有 store：

```text
ProjectNetworkBuildRecord
ProjectNetworkChannelState
ProjectNetworkEvidenceRecord
ProjectNetworkCandidateRecord
ProjectNetworkLayerIndexRecord
ProjectNetworkGenerationRecord
ProjectNetworkTraceRecord
ProjectStructure skeleton nodes / edges / overlays
```

### 3.2 读写规则

worker agent 的权限必须非常窄：

```text
worker agent 可读：
  assigned_scope
  upstream layer summary refs
  skeleton slice
  required evidence refs
  同层 channel 摘要
  自己 shard 相关的 coverage / conflict

worker agent 可写：
  GraphBuildWorkProductEnvelope
  evidence_refs
  coverage
  limitations
  conflict candidates
  downstream_shard_hints

worker agent 不可写：
  channel state
  layer index
  published generation
  skeleton graph
  shared state raw table
```

共享状态的唯一写入路径：

```text
agent final structured output
-> GraphBuildWorkProductEnvelope
-> ProjectNetworkBuildService.accept_node_result()
-> WorkProductChannel reducer
-> Evidence / Candidate / Layer / Generation stores
```

这样可以共享状态，又不会让 agent 互相覆盖结论。

### 3.3 三种共享状态投影

不同节点看到不同投影：

```text
Shard Worker Projection
  只看 assigned_scope、相关 skeleton slice、上游摘要、输出模板。

Layer Aggregator Projection
  看同层 work product channels、coverage、conflicts、上游 layer summary。

Curator Projection
  看跨层 layer indexes、conflict reports、validation reports、publish candidate。
```

禁止把全量共享状态塞给每个 worker。worker 只应看到完成当前 shard 所需的最小共享状态。

## 4. 单层审查标准流程

每一层都必须走同一个微流程。层的区别只在 shard 单位、prompt contract、output contract 和 validation policy。

```text
Layer Entry Gate
-> Shared State Snapshot
-> Shard Planning
-> Node Context Materialization
-> Single-Agent Review
-> Work Product Validation
-> Work Product Ingest
-> Channel Reduction
-> Layer Aggregation
-> Conflict / Coverage Gate
-> Next Layer Planning or Publish Gate
```

### 4.1 Layer Entry Gate

进入一层前先检查：

```text
required source snapshots 是否存在
skeleton generation 是否固定
upstream layer summary 是否可读
目标 layer output_contract_id 是否明确
shard_policy 是否明确
上一层 conflict 是否已裁决或标记 needs_human_review
```

没有通过 entry gate，不允许派发 agent。

### 4.2 Shared State Snapshot

系统冻结当前层可见状态，形成 layer snapshot：

```text
layer_snapshot_id
build_id
layer_id
skeleton_generation
source_snapshot_refs
upstream_layer_index_refs
input_work_product_refs
channel_snapshot_refs
coverage_baseline
conflict_baseline
```

冻结不是复制全量数据，而是记录 refs。agent 后续通过 refs 获取局部切片。

### 4.3 Shard Planning

分片规则按层不同：

```text
system layer:
  shard = project root / top-level domain candidate

folder layer:
  shard = folder scope

semantic_file_module layer:
  shard = one source file module

ast_endpoint layer:
  shard = one file module endpoint bundle, or one large class/function group

relation_route layer:
  shard = relation scope around module pair / route / registry edge
```

首版最关键规则：

```text
semantic_file_module layer 必须 force_single_file_modules=true。
也就是一个 agent 单审一个文件模块。
```

大文件可以在 endpoint 层继续拆，但 module 层仍然必须有一个单文件总审查产物，作为该文件语义索引的入口。

### 4.4 Node Context Materialization

每个 shard 物化成一个 graph node，也就是一个单 agent 执行座位。

审查节点默认采用低配置。低配置不是低质量，而是低上下文、低权限、低工具面、低全局耦合：

```text
系统负责提供：
  上一层已经裁决或候选的边界信息
  当前 shard 的 skeleton slice
  当前 shard 的 AST anchors / required read windows
  当前节点必须遵守的 output contract
  当前节点允许输出的 work product template

agent 负责判断：
  assigned_scope 内的语义职责
  候选事实是否有足够证据
  哪些内容 accepted / rejected / hypothesis
  coverage、limitations、downstream hints
```

节点输入应包含：

```text
assigned_scope
上一层提供的 parent boundary refs
当前 shard 的 skeleton node ids
当前 shard 的 anchor refs
当前 shard 的 local skeleton slice
当前 shard 的 AST outline / endpoint anchors
必要的 upstream layer summary 摘要
必要的 existing semantic overlays
必要的 required read windows
output contract id
work product template
forbidden behavior
definition of done
```

节点不能收到：

```text
全项目源码
全量共享状态
全量项目语义图
全量工具目录
全局搜索任务
跨层发布策略细节
其它 worker 的原始自然语言输出
未裁决 conflict 的 accepted 结论
发布 generation 的权限
```

单文件审查节点尤其要低配置：

```text
不需要项目级规划能力。
不需要全项目搜索能力作为常态入口。
不需要读取其它文件作为默认动作。
不需要 graph publish / semantic overlay write 权限。
不需要 broad memory read。
只需要系统投影出的上一层信息、当前文件骨架、当前文件 AST、当前输出契约。
```

### 4.5 Single-Agent Review

单个 worker agent 的审查顺序固定如下：

```text
1. 确认 assigned_scope 与上游边界
2. 读取 skeleton node card / local slice
3. 确认必须证据是否足够
4. 必要时读取 exact file window
5. 判断当前 shard 的语义职责
6. 标记 public surface / endpoints / relations
7. 列出 accepted / rejected / hypothesis candidates
8. 写 coverage 与 limitations
9. 写 downstream_shard_hints
10. 输出标准 work product
```

其中第 5 步之后的每个 accepted 判断都必须带证据：

```text
stable_ref
skeleton_node_id or skeleton_edge_id
anchor_ref when available
evidence_refs
confidence
status
```

### 4.6 Work Product Validation

节点输出先做格式和证据校验：

```text
work_product_id exists
build_id exists
node_id / shard_id / layer_id matches current work order
product_kind matches output_contract_id
accepted candidate has evidence_refs
endpoint candidate has anchor_refs
relation candidate has skeleton_edge_id or evidence-backed missing_physical_edge_request
coverage exists
limitations exists
```

不合格输出不得进入 accepted channel，只能进入 rejected / needs_human_review / conflict channel。

### 4.7 Channel Reduction

同层产物进入 channel reducer：

```text
module_index:
  merge_by_stable_ref

endpoint_index:
  reject_on_anchor_mismatch

relation_candidates:
  merge_by_stable_ref, conflict_policy=emit_conflict_product

coverage_report:
  merge_scope_coverage

layer_summary:
  replace_by_generation
```

reducer 只合并结构化产物，不读 raw markdown 做语义判断。

### 4.8 Layer Aggregation

每层必须有汇总节点。汇总节点不重新审查源码，只消费 typed channels：

```text
accepted_refs
rejected_refs
conflict_refs
coverage
uncovered_scope_refs
downstream_shard_hints
next_layer_plan_hints
```

汇总节点输出 `project_network.layer_summary.v1`，作为下一层共享状态的一部分。

### 4.9 Conflict / Coverage Gate

层级收口必须检查：

```text
是否有同一 stable_ref 的冲突职责
是否有 endpoint anchor mismatch
是否有 relation 无物理边或无证据链
是否有 assigned_scope 未覆盖
是否有上游系统边界被 worker 私自扩大
是否有 stale skeleton generation
```

未通过时有三种处理：

```text
block_next_layer:
  阻止下一层启动。

allow_partial_with_issues:
  允许下一层处理已覆盖 scope，未覆盖 scope 进入 conflict / repair。

needs_human_review:
  保留产物，但不得进入 published generation。
```

## 5. 自上而下结构分解

结构分解的目标不是发布最终语义，而是把项目拆成可审查、可复用、可汇总的工作单元。

### 5.1 Project Intake

输入：

```text
ProjectNetworkBuildContract
SkeletonExtractionReport
source_snapshot_refs
root_paths
```

输出：

```text
source_snapshot work product
project scope baseline
top-level folder refs
initial coverage baseline
```

### 5.2 System Layer

system layer 的任务是建立系统候选和上游边界约束。

它确定：

```text
functional_system candidates
owned folder candidates
entry modules
system boundary candidates
cross-system relation hints
downstream folder shards
```

它不能确定：

```text
文件的最终职责
函数级语义
跨模块关系的 accepted control route
published generation
```

输出模板：

```text
system_map:
  systems:
    - system_ref
      display_name
      purpose_candidate
      owned_folder_refs
      entry_node_refs
      boundary_refs
      relation_hints
      evidence_refs
      confidence
      status
  rejected_candidates
  conflicts
  coverage
  downstream_shard_hints
```

### 5.3 Folder Layer

folder layer 的任务是把系统候选继续拆成文件夹级审查边界。

它确定：

```text
folder responsibility candidate
folder owned modules
key files
boundary files
mixed responsibility risk
downstream file module shards
```

输出模板：

```text
folder_index:
  folder_ref
  parent_system_ref
  responsibility_candidate
  owned_file_refs
  key_file_refs
  boundary_relation_hints
  mixed_scope_risks
  downstream_module_shards
  evidence_refs
  coverage
  limitations
```

### 5.4 File Module Shard Plan

folder layer 汇总后，系统生成 file module shards：

```text
one file module = one shard = one agent review seat
```

每个 shard 必须绑定：

```text
file stable_ref
skeleton_node_id
folder_ref
candidate parent_system_ref
deep_ast anchors
upstream folder summary ref
expected output_contract_id = project_network.module_index.v1
```

这一步是整个流程的语义根。后续 folder/system/project 索引都要能追溯到这里。

## 6. 单文件模块审查

单文件模块是最小语义单位。一个 agent 单审一篇文件，输出标准模块索引。

单文件模块审查必须保持低配置。这个 agent 不是项目架构师，也不是全局搜索员；它只是在上层给定边界内，把一个文件审成标准化模块索引。项目级关系由系统提供候选、由 relation layer 追踪、由 aggregator/curator 汇总裁决。

### 6.1 输入

```text
assigned_scope:
  file_stable_ref
  skeleton_node_id
  path
  parent_folder_ref
  parent_system_candidate_ref

context:
  upstream boundary summary
  file node card
  direct AST outline
  import / call candidates
  class / function anchors
  required endpoint anchors
  required relation hints
  required read windows
  existing semantic overlays for this file only
  output contract
  work product template
```

单文件 agent 不应该接收：

```text
全项目文件树
全项目 search result
兄弟文件全文
其它文件模块的 raw review text
跨系统总图
发布 gate 状态
```

如果系统提供的文件级上下文不足，agent 只能输出：

```text
coverage_gap
missing_evidence_request
relation_trace_needed
hypothesis
```

### 6.2 审查动作

agent 必须按这个顺序工作：

```text
1. 确认上游边界：parent folder/system candidate 是否与当前文件匹配
2. 确认文件骨架：path、skeleton_node_id、AST anchors、read windows
3. 判断文件类型：service / repository / model / prompt / tool / API / UI / config / test / generated / unknown
4. 判断文件职责：用一句话和结构化 responsibility tags 表达
5. 提取 public surface：导出的 class/function/API/tool/prompt ids
6. 提取 internal endpoints：内部关键 class/function/method
7. 标记 state usage：数据库、memory、artifact、file、network、runtime state
8. 标记 relation candidates：只基于系统提供的 imports、calls、registry refs、prompt/tool refs
9. 判断 impact scope hints：只写当前文件可支持的影响线索
10. 判断 verify scope hints：只写当前文件可支持的验证线索
11. 标记 limitations：证据不足、动态调用、未解析关系、生成文件
12. 输出 module_index work product
```

如果需要跨文件确认，单文件 agent 不直接扩大读取面，而是输出 `relation_trace_needed` 或 `missing_evidence_request`，交给 relation layer 或系统投影补齐。

### 6.3 输出模板

`project_network.module_index.v1` 的 payload 必须包含：

```text
module:
  module_ref
  file_stable_ref
  skeleton_node_id
  path
  parent_folder_ref
  parent_system_ref
  file_kind
  responsibility_summary
  responsibility_tags
  public_surface
  internal_endpoints
  state_usage
  inbound_relation_hints
  outbound_relation_hints
  impact_scope_hints
  verify_scope_hints
  required_read_windows
  evidence_refs
  anchor_refs
  confidence
  limitations

semantic_facts:
  accepted
  rejected
  hypothesis

relation_candidates:
  accepted_candidates
  missing_physical_edge_requests
  unresolved_candidates

coverage:
  covered_refs
  uncovered_refs
  exact_read_confirmed
  ast_anchor_confirmed
```

### 6.4 文件级准确性标准

文件级语义不能靠文件名猜测直接 accepted。允许按证据等级分级：

```text
deterministic:
  来自 AST / registry / manifest 的硬事实。

exact_read_confirmed:
  agent 已读取当前文件窗口并确认。

model_derived:
  agent 基于 skeleton + exact read 推导。

hypothesis:
  线索存在，但证据不足。

rejected:
  被证据否定或不属于当前 scope。
```

`accepted` 至少需要：

```text
skeleton_node_id or skeleton_edge_id
stable_ref
evidence_refs
confidence != hypothesis
coverage entry
```

endpoint 级 accepted 还必须有：

```text
anchor_ref
line range or AST anchor
file hash / skeleton generation
```

## 7. Endpoint 与 Relation 审查

文件级审查后，如果需要更细粒度控制，进入 endpoint 和 relation 层。

### 7.1 Endpoint Layer

endpoint layer 不是重新审文件，而是围绕 AST anchors 建立控制末梢。

它确定：

```text
endpoint role
input parameters
return / output
side effects
state reads / writes
call sites
controlled capability
verification target
```

输出模板：

```text
endpoint_index:
  endpoint_ref
  module_ref
  anchor_ref
  endpoint_kind
  role
  inputs
  outputs
  side_effects
  reads_state
  writes_state
  called_by_hints
  calls_hints
  verification_target
  evidence_refs
  limitations
```

### 7.2 Relation Layer

relation layer 只顺着物理线索追关系：

```text
import edge
call edge
registry ref
router ref
tool operation ref
prompt ref
state store ref
artifact / memory / file contract ref
```

禁止凭语义相似度直接补 accepted relation。

输出模板：

```text
relation_candidates:
  relation_ref
  source_ref
  target_ref
  skeleton_edge_id
  relation_kind
  route_kind
  evidence_chain
  confidence
  status
  impact_meaning
  verify_meaning
  limitations
```

没有 `skeleton_edge_id` 的关系只能进入：

```text
missing_physical_edge_request
unresolved_candidate
coverage_gap
```

## 8. 自下而上语义汇总

语义汇总从文件级开始，而不是从项目级开始。

### 8.1 File -> Folder

folder aggregator 消费本文件夹内的 `module_index` 和 `endpoint_index`。

它输出：

```text
folder_semantic_index:
  folder_ref
  responsibility_summary
  module_refs
  key_module_refs
  public_surface_summary
  internal_structure_summary
  inbound_relations
  outbound_relations
  impact_scope
  verify_scope
  conflicts
  coverage
```

规则：

```text
folder responsibility 必须由文件级 module responsibilities 汇总而来。
不能因为文件夹名好听就直接 accepted。
```

### 8.2 Folder -> System

system aggregator 消费 folder summaries 和 relation candidates。

它输出：

```text
system_semantic_index:
  system_ref
  system_name
  responsibility_summary
  owned_folder_refs
  owned_module_refs
  entry_module_refs
  control_routes
  external_dependencies
  impact_scope
  verify_scope
  open_conflicts
  coverage
```

规则：

```text
系统边界必须能追溯到 folder/module refs。
系统职责必须能追溯到多个 module_index 或明确入口证据。
```

### 8.3 System -> Project

project aggregator 消费所有 system summaries。

它输出：

```text
project_semantic_index:
  systems
  cross_system_routes
  global entrypoints
  shared infrastructure
  state stores
  tool / prompt / runtime control areas
  high-risk boundaries
  coverage gaps
  generation_publish_readiness
```

project summary 只是索引，不是硬事实。最终还要经过 curator。

## 9. 应确定的语义集合

首版只确定高价值语义，不追求把所有自然语言理解都塞进图里。

### 9.1 Ownership Semantics

```text
system owns folder
folder owns file module
file module owns endpoint
endpoint belongs to file module
```

### 9.2 Responsibility Semantics

```text
system responsibility
folder responsibility
file module responsibility
endpoint role
```

### 9.3 Surface Semantics

```text
public surface
internal endpoint
entrypoint
adapter / bridge
repository / store
tool / prompt / runtime contract
```

### 9.4 Relation Semantics

```text
imports
calls
reads state
writes state
registers tool
uses prompt
dispatches graph node
publishes work product
consumes work product
```

### 9.5 Control Semantics

```text
impact_scope
edit_scope_hint
verify_scope
risk_boundary
coverage_gap
stale_risk
```

这些语义必须挂在物理骨架 refs 上。不能产生脱离 skeleton 的自由概念节点。

## 10. 准确性控制机制

### 10.1 Evidence Gate

每条 accepted 语义必须至少有一个证据来源：

```text
AST anchor
file read window
registry id
tool operation id
prompt id
graph node id
skeleton edge id
git change evidence
```

### 10.2 Cross-Layer Consistency

跨层必须一致：

```text
file module 的 parent_folder_ref 必须存在。
folder 的 parent_system_ref 必须来自 system_map 或 conflict_curate。
system 的 owned_folder_refs 必须能在 skeleton 中解析。
relation 的 source / target 必须能解析到 module 或 endpoint。
```

### 10.3 Negative Evidence

agent 不只写 accepted，还必须写 rejected：

```text
看起来像系统边界但不是
看起来像 public surface 但实际内部使用
看起来像 control route 但没有证据链
看起来相关但不在 assigned_scope
```

这能减少后续重复误判。

### 10.4 Conflict Policy

冲突不靠 aggregator 抹平。

常见冲突：

```text
同一文件被两个 system claimed
同一 endpoint 被标成不同 role
relation source / target 不一致
accepted 语义缺 anchor
module summary 与 endpoint facts 矛盾
folder summary 与 module facts 矛盾
```

冲突处理：

```text
emit conflict_report
curator 裁决
证据不足则 needs_human_review
不得直接发布
```

## 11. 图任务模式

### 11.1 推荐执行形态

首版建议使用 rolling one-hop 加局部静态 fan-out：

```text
G0 Source / System classify
-> G1 Folder index
-> G2 File module review fan-out
-> G3 Endpoint / Relation review fan-out
-> G4 Bottom-up aggregation
-> G5 Cross-layer validate / conflict curate / publish candidate
```

每张图只负责下一层或一个清晰阶段，减少远期漂移。

### 11.2 静态模式仍保留

小项目或限定目录可以使用 static_pre_materialized：

```text
source
-> system shards
-> folder shards
-> module shards
-> relation shards
-> aggregate / validate / publish
```

但静态模式必须有预算限制：

```text
max files
max folders
max endpoint anchors
max graph nodes
max layer count
```

## 12. Agent 契约样式

给 agent 的 prompt 必须是可执行职责，不是开发说明。

单文件模块审查 agent 应写成：

```text
你是一名单文件语义模块索引员。
你只负责 assigned_scope 指向的一个源码文件。
你需要基于 skeleton node card、Deep AST anchors、上游 folder summary 和必要的 exact read window，判断该文件在项目中的职责。
你必须输出 project_network.module_index.v1 work product。
你不能修改源码，不能扩大 assigned_scope，不能把没有 evidence_ref 或 anchor_ref 的推测写成 accepted。
如果证据不足，你必须标记 hypothesis 或 needs_human_review，并说明缺少什么证据。
```

folder 汇总 agent 应写成：

```text
你是一名文件夹语义汇总员。
你只消费当前 folder 下的 module_index、endpoint_index、relation_candidates 和上游 system boundary refs。
你不重新审查源码，不凭文件夹名直接确定职责。
你需要把文件级事实汇总成 folder_semantic_index，并列出 coverage、conflicts、uncovered modules 和 downstream hints。
```

curator agent 应写成：

```text
你是一名项目语义网络发布裁决员。
你只检查 typed work products、layer summaries、evidence refs、anchor refs、coverage 和 conflict reports。
你不为完成发布而补事实。
你需要裁决 generation 是否可以发布；如果不能发布，输出 blockers、needs_human_review 和必须返修的 refs。
```

## 13. 实施清单

后续实现应按以下顺序补齐，不要先做前端或新搜索工具。

### Phase 1：工作流合同落库

需要补：

```text
LayerReviewSharedState projection
standard payload templates for system_map / folder_index / module_index / endpoint_index / relation_candidates / layer_summary
channel policies per layer
coverage and conflict gate policy
```

### Phase 2：分片规划强化

需要补：

```text
system -> folder -> file module 的 top-down shard derivation
force_single_file_modules 的文件层规则
large file endpoint refinement policy
folder summary driven downstream_shard_hints
single-file low-config node projection policy
```

### Phase 3：work product schema validation

需要补：

```text
accepted candidate evidence validation
endpoint anchor validation
relation skeleton_edge validation
coverage required validation
assigned_scope boundary validation
```

### Phase 4：bottom-up aggregation

需要补：

```text
file -> folder summary reducer
folder -> system summary reducer
system -> project summary reducer
cross-layer consistency validator
conflict curator input projection
```

### Phase 5：publish gate 接语义覆盖层

需要补：

```text
publish_candidate -> SemanticOverlayRecord mapping
generation status transition
published overlay query projection
navigation path semantic enrichment
git maintenance stale propagation
```

## 14. 禁止的反模式

```text
禁止让项目级 agent 一次性总结全项目并直接发布。
禁止把共享状态做成自由 markdown 池。
禁止 worker agent 直接写 Semantic Overlay Store。
禁止 aggregator 凭自然语言摘要发明新 accepted fact。
禁止 folder/system 层绕过 file module 层生成最终职责。
禁止把 next_action、当前路径、预算、frontier 写入语义层。
禁止把没有 skeleton refs 的语义节点发布为项目索引。
禁止为了覆盖率把 unknown / hypothesis 升级为 accepted。
```

## 15. 完成定义

这条工作流完成时，系统应满足：

```text
能从物理骨架生成 system/folder/file module 审查分片。
能让一个 agent 单审一个文件并输出 module_index。
能把 module_index 汇总成 folder_semantic_index。
能把 folder summaries 汇总成 system_semantic_index。
能把 system summaries 汇总成 project_semantic_index。
能把每个 accepted 语义追溯到 skeleton refs 和 evidence refs。
能把冲突、覆盖缺口和 stale 风险阻断在 publish gate 前。
```

这才是项目级语义网络的正确生产线：上层负责拆分，下层负责实证，汇总层负责索引，curator 负责发布。

## 16. 目录层级渲染图任务设计

目录级语义审查不应该预设固定层数。正确做法是让系统根据物理文件树层层渲染：

```text
当前目录
-> 读取 direct child directories
-> 读取 direct code files
-> 子目录继续渲染目录帧
-> 代码文件生成单文件审查节点
-> 等待子目录 summary 与直接文件 module_index 回传
-> 当前目录生成 folder_summary
-> 向父目录回传
```

这里“渲染”不是让 agent 规划目录树，而是系统根据 Skeleton Graph 的 `folder contains folder/file` 关系生成下一层 graph materialization package。agent 只审语义，不决定物理树有几层。

### 16.1 与现有图任务结构的对齐

现有结构可复用：

```text
ProjectNetworkBuildContract
  定义一次 project semantic network build。

ProjectNetworkLayerPlan
  可继续描述 folder / semantic_file_module / aggregation 层。

SemanticShardSpec
  可承载 directory shard 和 file module shard。

ProjectNetworkGraphBuilder
  可物化一批 shards 为 TaskGraphDefinition。

GraphBuildWorkProductEnvelope
  可承载 module_index、folder_index、layer_summary。

WorkProductChannel
  可合并直接文件审查结果和子目录回传 summary。

ProjectNetworkBuildService
  可消费 node result，写入 work product / evidence / candidate / layer index。
```

现有结构不足：

```text
缺少 directory render frame。
缺少 directory manifest product。
缺少 child graph package 与 parent folder frame 的回传绑定。
缺少“父目录等待子目录图完成”的 project_network 级协调服务。
缺少 tree-shaped graph builder，用于小目录一次静态渲染整棵树。
```

因此不需要改 graph core，但需要拓展 `task_system.project_network` 的基础设施。

### 16.2 两种执行模式

#### A. 小目录：静态树形图

适用于文件数量、目录深度、节点数量都在预算内的 scope。

系统一次性从 Skeleton Graph 读取完整子树，然后渲染成一张树形任务图：

```text
folder_review(root)
  waits on:
    folder_review(child_dir_a)
    folder_review(child_dir_b)
    module_review(file_1.py)
    module_review(file_2.py)

folder_review(child_dir_a)
  waits on:
    module_review(child_a_1.py)
    module_review(child_a_2.py)
```

图中节点类型：

```text
directory_manifest node
  deterministic/runtime_state_store，不调用模型。
  输出 direct children refs。

module_review nodes
  单文件低配置 agent。
  输出 module_index。

folder_aggregate node
  aggregator agent 或 deterministic reducer。
  等待 direct module_index + child folder_summary。
  输出 folder_index / folder_summary。
```

这需要新增一个 tree-shaped graph builder。它不是 graph core 改造，只是 `ProjectNetworkGraphBuilder` 的一种新 materialization strategy：

```text
build_directory_tree_graph(package)
```

#### B. 大项目：滚动目录帧

适用于大项目、深目录、增量维护。

每个目录是一个 render frame：

```text
DirectoryRenderFrame:
  frame_id
  build_id
  parent_frame_id
  folder_stable_ref
  folder_skeleton_node_id
  skeleton_generation
  direct_child_folder_refs
  direct_code_file_refs
  child_frame_refs
  direct_module_work_product_refs
  child_folder_summary_refs
  status
  depth
  budget
```

执行顺序：

```text
1. create frame for current folder
2. deterministic directory_manifest reads direct children
3. if direct code files exist:
     render file module review graph for direct files
4. if direct child folders exist:
     create child DirectoryRenderFrame for each child folder
     render child directory graphs
5. wait until:
     all direct file module_index are ingested
     all child frames have folder_summary
6. render parent folder_aggregate graph
7. parent folder_summary written as work product
8. notify parent frame through refs, not raw text
```

父目录等待的不是运行中的子节点，而是 `ProjectNetworkBuildService` 已摄取的结构化 work products：

```text
required_child_summary_refs
required_direct_module_refs
coverage requirements
conflict refs
```

这避免改 `GraphLoop`。等待逻辑由 project_network 的 render coordinator 管理。

### 16.3 目录渲染帧状态机

```text
planned
-> manifest_ready
-> child_frames_created
-> direct_file_reviews_running
-> waiting_child_returns
-> ready_to_aggregate
-> aggregating
-> summarized
-> returned_to_parent
```

失败状态：

```text
blocked_missing_skeleton
blocked_child_failed
blocked_unresolved_conflict
needs_human_review
cancelled
```

关键规则：

```text
目录帧只能管理渲染和等待，不写语义事实。
单文件节点只写 module_index candidate。
folder_aggregate 只消费 direct module refs 和 child folder refs。
父目录 summary 必须能追溯到子目录 summary 和直接文件 module_index。
```

### 16.4 单个目录帧的图结构

每个目录帧可以渲染成一张小图：

```text
pn.dir.manifest
  -> pn.file.<n>.module_review      parallel
  -> pn.dir.wait_child_returns      barrier/runtime_state_store
  -> pn.dir.aggregate
  -> pn.dir.output
```

其中：

```text
pn.dir.manifest
  系统节点，输出 direct_code_file_refs 和 child_folder_refs。

pn.file.<n>.module_review
  agent:project_network_builder
  low-config single-file module review。

pn.dir.wait_child_returns
  不需要模型，检查 child frame summary refs 是否齐全。
  若未齐，frame 保持 waiting_child_returns。

pn.dir.aggregate
  agent:project_network_aggregator
  消费 direct module_index refs + child folder_summary refs。
  输出 folder_index / layer_summary。
```

如果当前目录没有子目录，`wait_child_returns` 直接通过。

如果当前目录没有直接代码文件，也允许只汇总 child folder summaries。

如果当前目录既没有子目录也没有代码文件，frame 输出 empty / skipped summary，不能调用 agent。

### 16.5 回传协议

子目录回传给父目录的不是自然语言，而是 refs：

```text
FolderReturnEnvelope:
  frame_id
  parent_frame_id
  folder_stable_ref
  folder_summary_work_product_id
  layer_index_ref
  coverage
  conflict_refs
  evidence_refs
  status
```

父目录 aggregator 的输入：

```text
direct_module_work_product_refs
child_folder_summary_refs
child_conflict_refs
coverage_baseline
parent_boundary_refs
```

父目录 aggregator 不读取子目录 agent 的原始回答。它只消费 typed work products。

### 16.6 子目录渲染策略

目录渲染不能无控制展开。需要预算：

```text
max_depth_per_wave
max_child_frames_per_wave
max_direct_files_per_frame
max_parallel_file_reviews
max_total_open_frames
max_total_graphs_per_build
skip_generated_dirs
skip_vendor_dirs
```

跳过目录：

```text
.git
.next
node_modules
dist
build
coverage
__pycache__
.pytest_cache
.mypy_cache
generated
vendor
```

跳过不是删除。跳过目录应形成 coverage limitation：

```text
skipped_scope:
  folder_ref
  reason
  policy
```

### 16.7 需要拓展的基础设施

已新增模型：

```text
backend/task_system/project_network/directory_render_models.py

DirectoryRenderBudget
DirectoryRenderFrame
DirectoryManifestProduct
DirectoryChildReturnEnvelope
DirectoryFrameMaterializationPackage
DirectoryRenderProjection
```

已新增服务：

```text
backend/task_system/project_network/directory_render_service.py

create_root_frame()
materialize_manifest()
create_child_frames()
register_child_return()
build_materialization_package()
projection()
```

已新增 graph builder 方法：

```text
ProjectNetworkGraphBuilder.build_directory_frame_graph(package)
```

已新增 node template：

```text
project_network.directory_aggregate
```

当前实现原则：

```text
目录 manifest 和 child return 是 task_system.project_network orchestration state。
文件模块审查沿用 project_network.module_index。
目录汇总输出 project_network.directory_summary.v1。
非 agent 的 manifest / wait 节点不进入 GraphLoop 可执行队列。
```

这样可以避免为了表达系统状态而创建不可执行节点。GraphLoop 调度的仍然是 agent work order；目录 manifest 和子回传由 project_network repository 维护为强类型 refs。

### 16.8 Graph Harness 接入原则

目录层级渲染必须接入 Graph Harness，但接入点不是让 `GraphLoop` 读取文件树或裁决语义，而是让它承载一种明确的 loop algorithm frame：

```text
loop_frame.kind = tree_reduce
loop_frame.algorithm_kind = directory_tree_reduce
loop_frame.unit_kind = directory_frame
```

职责边界：

```text
file_management.project_structure
  提供物理 Skeleton Graph：目录、文件、AST、git facts。

tree_reduce algorithm materialization
  根据物理骨架生成下一层目录/文件运行图。
  文件成为 leaf review node；目录成为 aggregate node 或子 tree frame。

graph_system.GraphLoop
  识别 tree_reduce loop frame。
  初始化 frame state。
  派发单文件审查和目录汇总 work order。
  把 loop_context / loop_contract 投给节点。
  在接受 NodeResult 前执行 required runtime algorithm side effects。
```

已完成的 harness 接线：

```text
backend/graph_system/loop.py
  _normalize_loop_frame() 显式保留 algorithm_kind / unit_kind / tree_reduce。

backend/graph_system/loop_engine.py
  frame projection 暴露 tree_reduce 路标字段。

backend/graph_system/context_materializer.py
  GraphNodeExecutionSlot.loop_contract 投影 tree_reduce 信息。
```

这意味着 directory tree reduce 已经成为 GraphLoop 的一种可见算法结构；它不是旁路服务。

禁止事项：

```text
GraphLoop 不读取 skeleton repository。
GraphLoop 不决定 child folder / direct file。
GraphLoop 不解释目录语义。
GraphLoop 不写 semantic overlay。
```

GraphLoop 只根据已物化的 tree frame graph 派发节点；树的下一层如何生成，由 tree_reduce algorithm 的 materialization 步骤根据物理骨架生成。`DirectoryRenderService` 只能作为当前实现中的目录树 materializer，不能拥有独立调度权威。

### 16.9 实施顺序与当前实现状态

```text
Phase 1 已完成:
  DirectoryRenderFrame / Manifest / ChildReturn / MaterializationPackage。
  DirectoryRenderService 从 Skeleton Graph 生成目录 manifest 和 child frames。
  ProjectNetworkRepository 持久化目录帧编排状态。
  ProjectNetworkGraphBuilder.build_directory_frame_graph() 生成 frame graph。
  GraphLoop / LoopEngine / ContextMaterializer 投影 tree_reduce loop frame。

Phase 2 已完成:
  DirectoryRuntimeService.prepare_frame() 负责确定性地补齐 manifest 与 child frames。
  DirectoryRuntimeService.scheduler_decision() 输出 parent-frame 的下一步动作。
  child frames 全部 returned 后，parent frame 状态进入 ready_to_aggregate。
  child directory_summary 可自动登记为 DirectoryChildReturnEnvelope。

Phase 3 已完成:
  DirectoryRuntimeService.publish_frame_graph() 提供 frame graph 配置发布入口：
    DirectoryFrameMaterializationPackage
    -> TaskGraphDefinition
    -> ExecutableGraphConfig
    -> TaskFlowRegistry.upsert_graph_config(publish=True)
  frame graph 可以是运行期展开能力，但仍必须作为正式 TaskGraph/ExecutableGraphConfig 进入 registry。
  真实启动只能走 graph_system 的统一 starter；DirectoryRuntimeService.record_frame_graph_start() 只登记已启动的 graph_run_id，不直接调用 GraphSystem.start_run()。
  frame graph 的 materialization package 必须是稳定输入：允许包含物理骨架、manifest、child return refs、coverage 与必要 contract refs；禁止把 graph_run_id、latest_graph_config_*、时间戳、运行状态抖动等运行期字段写进 ExecutableGraphConfig。

Phase 4 已完成首段:
  WorkProductKind 已纳入 directory_summary。
  directory_summary 使用 replace_by_generation reducer，并作为 candidate semantic work product 入库。
  DirectoryRuntimeService.accept_directory_node_result() 可在 ProjectNetworkBuildService.ingest 后自动识别 directory_summary。
  module_index、relation candidates、coverage limitations 继续沿用 ProjectNetworkBuildService 统一入口。
  runtime_algorithm_adapters.py 将 tree_reduce 的合格 graph_build_work_products 转换为 required side effect。
  GraphLoop.accept_node_result() 先执行 required side effect；入库失败时节点 blocked，不允许父层收到假成功。

Phase 4 待补:
  directory_summary schema validation。
  accepted candidate evidence gate。
  parent aggregate 对 direct module refs 与 child summary refs 的完整覆盖校验。

Phase 5:
  接入 semantic overlay publish gate。
  只有 schema、anchor/hash、coverage、conflict 校验通过后写入 semantic store。
```

### 16.10 当前接线清单

新增 runtime 承载层：

```text
backend/task_system/project_network/directory_run_models.py

DirectoryFrameGraphPublishResult
DirectoryFrameSchedulerDecision
```

```text
backend/task_system/project_network/directory_runtime_service.py

prepare_frame()
scheduler_decision()
publish_frame_graph()
frame_graph_start_initial_inputs()
record_frame_graph_start()
accept_directory_node_result()
```

工作产物接线：

```text
project_network.directory_summary.v1
-> GraphBuildWorkProductEnvelope(product_kind=directory_summary)
-> ProjectNetworkBuildService.accept_node_result()
-> WorkProductChannel(replace_by_generation)
-> ProjectNetworkCandidateRecord
-> DirectoryRuntimeService registers DirectoryChildReturnEnvelope
-> parent DirectoryRenderFrame.child_return_refs
```

目录聚合 agent 的强制输出要求：

```text
你必须在 graph_build_work_products 中提交 product_kind=directory_summary 的 work product。
stable_ref 使用 folder_stable_ref。
payload 必须包含 directory_frame_id、parent_frame_id、folder_stable_ref、directory_summary、direct_module_refs、child_summary_refs、accepted_relation_candidates、conflicts、coverage、uncovered_refs 和 parent_return_payload。
```

职责边界：

```text
DirectoryRuntimeService
  只做帧准备、调度决策、图配置发布、启动结果登记、summary 回传登记。

ProjectNetworkBuildService
  只摄取 typed work products，执行 channel reduce 与候选记录。

GraphSystem / GraphLoop
  只通过已发布 ExecutableGraphConfig 执行 frame graph，投影 tree_reduce 路标。

agent
  只负责 assigned directory_frame / file module 内的语义判断，输出 typed work product。
```

### 16.11 最终裁决

目录层级渲染流程可以基于现有图任务结构设计，但不能只靠当前 `build_next_layer_shard_plan()`。当前 planner 是按固定 layer scope refs 切分；目录渲染需要按物理树递归生成 frames。

最合理方案：

```text
保留现有 ProjectNetworkBuildContract / WorkProduct / Channel / GraphBuilder 主干。
tree_reduce 是图任务运行算法，不是 project_network 专用渲染流程。
旧 DirectoryRenderFrame / DirectoryRenderService 只能被视为当前实现里的 tree materialization 数据结构和薄层工具。
GraphLoop 承载 tree_reduce loop frame，负责派发 frame graph 内的 agent work orders，并执行必需算法 side effect。
目录递归的物理展开不由 agent 自行决定；它由 tree_reduce materialization 依据 Skeleton Graph 决定。
```
