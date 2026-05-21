# Task Graph 运行边界系统成熟化设计报告与实施计划

日期：2026-05-22

## 1. 核心结论

这次优化不应该围绕“时序还是 step”展开。真正要修的是图任务运行时的边界能力。

当前任务图最大的不稳定，不是缺少某个执行概念，而是四类边界没有成为统一协议：

1. **启动边界**：节点什么时候允许开始。
2. **读取边界**：节点能读哪些上游结果，不能读哪些半成品。
3. **提交边界**：哪些结果可以成为后续事实和长期记忆。
4. **续跑边界**：修改、失败、重跑时，哪些产物失效，哪些产物保留。

因此，时序系统要保留，但职责要收窄。它不再是节点排队系统，也不承担运行调度波次。它应该成为 **任务生命周期与边界账本**，记录阶段、批次、轮次、审核、提交、失效和恢复坐标。

节点能不能启动，应由依赖边、上游结果状态、审核/提交边界共同决定；运行时一次派发几个 ready 节点，是调度策略，不应该成为图编辑器的主概念。

## 2. 对时序与 step 的本质判断

### 2.1 时序的本质

时序不是“节点排列顺序”，而是任务生命周期中的业务坐标和边界记录。

它回答这些问题：

- 当前任务处于哪个业务阶段。
- 当前是哪个卷、哪个章节批次、哪个返修轮次。
- 哪些候选已经审核通过。
- 哪些结果已经提交为下游可读事实。
- 哪个阶段已经关闭，不能再被旧结果污染。
- 断点续跑应该回到哪个业务边界。

对长篇写作任务来说，时序必须存在。因为写作图不是普通 DAG，它有设计期、创作期、卷审、批次、返修、记忆提交、设定冻结和动态推进。如果没有时序账本，运行时可以跑完节点，但很难知道“哪些东西已经成为作品事实”。

### 2.2 step 的本质

step 只是运行时的一次调度波次。

它回答这些问题：

- 当前有哪些节点 ready。
- 运行资源允许这次派发几个。
- 哪些 request_id 属于同一轮派发。
- checkpoint 记录这次派发到什么状态。

step 不应该成为编辑器里的业务概念。因为同一张图在不同资源、不同模型队列、不同恢复场景下，实际派发波次可能不同。把 step 画进业务图，会把运行资源策略误绑定为业务流程。

### 2.3 设计判断

任务图应该表达：

- 因果依赖。
- 可并发的无序关系。
- 汇合审查。
- 审核裁决。
- 提交边界。
- 记忆可见性。
- 失败返修和失效范围。

运行时自己决定：

- 这次派发哪些 ready 节点。
- 是否因为资源限制分批派发。
- 如何记录 checkpoint 和 request。

所以后续设计中，不新增用户可见的 `StepPlan` 作为核心对象。可以保留运行时内部 dispatch wave，但它只是运行记录，不是图语义。

## 3. 当前系统证据

### 3.1 已有能力

`backend/task_system/graphs/task_graph_models.py`

- 节点已有 `wait_policy`、`join_policy`、`review_gate_policy`、`memory_writeback_policy`、`artifact_policy`。
- 边已有 `wait_policy`、`ack_policy`、`failure_propagation_policy`、`result_delivery_policy`。
- 这些字段已经接近“边界协议”，但还没有被统一命名和验证。

`backend/task_system/compiler/coordination_graph_models.py`

- RuntimeSpec 已保留节点的执行、等待、汇合、记忆、产物、审核策略。
- 说明后端已经具备把图语义传给运行层的通道。

`backend/runtime/graph_runtime/scheduler.py`

- 当前 scheduler 已能根据上游完成、失败传播、timeline result gate、handoff ack 判断 ready/blocked。
- 但它仍混入 active phase / sequence gate，这让“业务生命周期”和“节点排队”纠缠在一起。

`backend/runtime/coordination_runtime/runtime.py`

- 运行态已有 `timeline_result_records`、`accepted_result_records_by_scope`、`result_record_index`。
- `_route_next` 当前仍取 `ready[0]`，说明主运行链没有真正把“多个 ready 节点”当成可调度集合。
- `resume_from_task_result` 已能记录 result record 和 timeline ledger，但结果状态仍需要更明确地区分 candidate、accepted、committed、superseded。

`backend/runtime/memory/timeline_result_record.py`

- 已有 `TimelineResultRecord`，这是正确方向。
- 但它目前更像“节点结果事实记录”，还不是完整的提交边界协议。

`backend/runtime/graph_runtime/batch_runtime.py`

- 批次运行已有批次状态、修复轮次、merge readiness。
- 这说明系统已经局部证明：长任务不能只靠节点完成状态，必须有批次、审核、提交、修复状态。

`frontend/src/components/workspace/views/task-system`

- 已有 phase lifecycle、timeline page、edge handoff、standard view。
- 但前端仍容易把 phase/sequence/timeline group 展示成排队结构，而不是边界结构。

### 3.2 主要缺口

1. 节点类型没有明确区分生产、审核、提交、路由、资源、监测。
2. 边类型没有明确区分启动依赖、候选输入、审核输入、提交输入、记忆读取、失败返修、非阻塞参考。
3. 候选产物、审核意见、正式提交产物之间的状态边界不够硬。
4. 时序字段承担了过多调度责任，`sequence_index` 容易把本应无序并发的节点排成链。
5. 断点续跑更多依赖运行快照，缺少以业务边界为核心的失效与恢复模型。

## 4. 目标模型：运行边界系统

### 4.1 四层职责

目标架构分四层：

```text
图语义层
  定义节点职责、边职责、资源职责

边界判定层
  判断节点能否启动、能读什么、能提交什么

生命周期账本层
  记录阶段、批次、轮次、审核、提交、失效、恢复坐标

运行调度层
  从 ready 节点中实际派发请求，并记录 checkpoint
```

这四层不能互相抢职责。

- 图语义层不决定一次派发几个节点。
- 调度层不决定候选是否变成事实。
- 生命周期账本不强行给节点排队。
- 边界判定层必须是下游可见性的唯一门。

### 4.2 节点职责模型

建议把节点职责明确成以下几类：

| 职责 | 作用 | 典型写作节点 |
|---|---|---|
| `producer` | 生产候选产物 | 世界观设计、人设设计、剧情设计、章节细纲、章节正文 |
| `reviewer` | 审核候选并给出裁决 | 世界观审核、设计统筹审查、章节审稿 |
| `committer` | 将已通过结果提交为事实或记忆 | 世界观提交、设计提交、章节记忆提交 |
| `router` | 根据状态决定下一阶段或返修 | 批次推进、卷推进、返修路由 |
| `resource` | 提供记忆、产物库、账本 | 基准库、动态库、线程账本 |
| `monitor` | 观测运行状态，不改变事实 | 运行监测、质量监测 |

这比单纯区分 `agent/review_gate/memory` 更有用，因为它直接决定运行边界。

### 4.3 边职责模型

边也不能只是连线。建议建立边职责：

| 边职责 | 含义 |
|---|---|
| `activation_dependency` | 目标节点启动前，源节点必须到达指定状态 |
| `candidate_input` | 目标读取源节点候选产物，但不得视为事实 |
| `review_input` | 审核节点读取候选与问题上下文 |
| `commit_input` | 提交节点读取已通过审核的结果 |
| `memory_read` | 从指定记忆库读取已提交事实 |
| `memory_commit` | 将结果写入指定记忆库 |
| `revision_return` | 审核失败后回到返修节点 |
| `non_blocking_reference` | 只作为参考，不阻塞启动，不产生事实依赖 |
| `failure_route` | 失败后的隔离、终止或人工处理路线 |

运行时 ready 判断应主要消费边职责和上游结果状态，而不是靠 sequence 排队。

### 4.4 产物状态模型

每个节点产物必须有生命周期状态：

| 状态 | 可读范围 | 是否可成为事实 |
|---|---|---|
| `candidate` | 审核节点、返修节点 | 否 |
| `under_review` | 审核节点 | 否 |
| `accepted` | 提交节点、受控下游 | 还不是长期事实 |
| `committed` | 后续正式节点 | 是 |
| `rejected` | 返修参考 | 否 |
| `superseded` | 审计可见，运行不可读 | 否 |
| `isolated` | 问题隔离区 | 否 |

写作任务里最重要的一条规则是：**下游正式创作只能读 committed；审核和返修可以读 candidate/accepted，但必须带范围。**

### 4.5 时序系统的新职责

保留时序系统，但改成生命周期与边界账本：

```text
phase_id
volume_index
chapter_batch_range
revision_round
attempt_index
boundary_status
opened_at_clock
closed_at_clock
committed_result_refs
invalidated_result_refs
```

时序系统负责记录：

- 设计阶段是否完成。
- 当前卷和当前章节批次。
- 当前返修轮次。
- 哪些候选已通过审核。
- 哪些结果已提交。
- 哪些结果因重跑失效。

时序系统不负责：

- 给所有节点排队。
- 决定同一批 ready 节点是否一起派发。
- 替代依赖边判断。
- 把 candidate 自动升级为 committed。

## 5. 写作图中的真实应用

### 5.1 世界观流程

不是：

```text
world_design -> world_review -> world_commit
```

这么简单的线性节点链。

真实语义应该是：

- `world_design` 生产 `world_candidate`。
- `world_review` 读取 `world_candidate`，输出 verdict 和 issue list。
- verdict 为 pass 时，`world_commit` 才能读取 accepted candidate。
- `world_commit` 写入基准库后，后续人设、剧情、大纲才可以正式读取世界观事实。
- verdict 为 revise 时，只允许 `world_design` 读取 review issue 进行返修。

这解决之前“只有 review 落盘、design 不落盘”或“审核意见被误当设定”的问题。

### 5.2 人设与剧情并行

不是表达成“同一个 step”。

真实语义是：

- `character_design` 与 `plot_design` 之间没有因果依赖。
- 二者都依赖已 committed 的世界观。
- `design_sync_review` 同时依赖两份 accepted 或 candidate-for-review 结果。
- 只要其中一个缺失、失败、被隔离，`design_sync_review` 就不能启动。
- 其中一个失败重跑，不影响另一个成功候选，但成功候选在统筹提交前不能成为长期事实。

这才是任务图与真实运行相关的并发设计。

### 5.3 章节批次

章节正文节点不是普通 producer，它还受批次边界约束：

- 只能写当前批次章节。
- 只能读取当前批次允许的已提交记忆、上批承接摘要、当前章纲。
- 审稿失败时，返修只能修改当前批次产物。
- 章节提交后，章节事实、伏笔推进、人物状态才进入后续可读记忆。

这类约束必须写进边界系统，不能靠 prompt 提醒。

## 6. 推荐数据模型

### 6.1 新增 Boundary Manifest

不建议新增以 step 为核心的模型。建议新增：

```text
TaskGraphBoundaryManifest
NodeBoundarySpec
EdgeBoundarySpec
ResultLifecycleSpec
CommitBoundarySpec
LifecycleCoordinateSpec
InvalidationRuleSpec
```

### 6.2 NodeBoundarySpec

核心字段：

```text
node_id
boundary_role
produces_result_kind
required_input_states
read_visibility
write_visibility
review_policy_ref
commit_policy_ref
retry_policy_ref
```

### 6.3 EdgeBoundarySpec

核心字段：

```text
edge_id
source_node_id
target_node_id
boundary_role
required_source_state
target_input_key
blocks_activation
failure_policy
visibility_policy
```

### 6.4 ResultLifecycleSpec

核心字段：

```text
result_ref
node_id
run_id
phase_id
coordinate
state
attempt_index
supersedes_ref
visible_to_node_ids
committed_memory_refs
```

### 6.5 Lifecycle Ledger

当前 timeline ledger 可以继续存在，但要从“事件流水”升级为边界账本视图：

```text
lifecycle_coordinate
boundary_events
open_boundaries
closed_boundaries
accepted_results
committed_results
invalidated_results
active_retry_scope
```

## 7. 实施计划

### 阶段一：边界影子模型

目标：不改变运行行为，先从现有图编译出 Boundary Manifest。

改动：

- 新增 `backend/task_system/boundaries/boundary_models.py`。
- 新增 `backend/task_system/boundaries/boundary_compiler.py`。
- 从现有 `node_type`、`review_gate_policy`、`memory_writeback_policy`、`artifact_policy`、`wait_policy`、`join_policy`、边 metadata 推导 boundary manifest。
- RuntimeSpec diagnostics 输出 boundary manifest summary。

完成标准：

- 现有图不需要新配置也能生成 boundary manifest。
- 世界观设计、审核、提交能被识别为 producer/reviewer/committer。
- 人设设计与剧情设计能被识别为无互相依赖的 producer。

禁止：

- 不改变 `_route_next`。
- 不删除现有 phase/sequence 字段。
- 不引入用户可见 step 概念。

### 阶段二：结果生命周期硬化

目标：把候选、审核、提交、失效做成真实状态。

改动：

- 扩展 `TimelineResultRecord` 或新增 `TaskGraphResultRecord`。
- 增加 `state`：candidate、accepted、committed、rejected、superseded、isolated。
- `accepted_result_records_by_scope` 改造成更明确的 visibility index。
- review gate 只产生 verdict，不允许把审核员新增内容直接当被审事实提交。
- commit 节点只能读取 accepted result。

完成标准：

- candidate 不会进入正式下游上下文。
- review 未通过时 commit 不会 ready。
- 被 superseded 的结果不会再被 context resolver 读取。

### 阶段三：Scheduler 消费边界

目标：节点 ready 由依赖边和结果状态决定，时序只提供生命周期限制。

改动：

- `scheduler.py` 从“phase/sequence gate”为主，改为“boundary readiness”为主。
- `sequence_index` 降级为编辑器排序和迁移输入，不作为默认阻塞条件。
- `wait_policy` 与边职责合并成明确 activation rules。
- 保留 phase open/closed 检查，防止已关闭阶段被旧结果唤醒。

完成标准：

- 两个互不依赖节点可以同时 ready。
- 有共同下游的审核节点必须等所有 required input 到达指定状态。
- 资源受限时运行可串行派发，但业务 ready 状态不变。

### 阶段四：运行派发与 checkpoint 调整

目标：运行时可以处理多个 ready 节点，但不把 dispatch wave 暴露成图语义。

改动：

- `_route_next` 不再固定取 `ready[0]` 作为唯一可能路径。
- 新增 ready dispatch queue，按资源策略派发一个或多个节点。
- 每个派发请求有独立 `request_id`、`dispatch_event_id`、`result_record_id`。
- checkpoint 记录 dispatch queue 和 in-flight requests。

完成标准：

- 普通图可以同时持有多个 running 节点。
- 一个节点完成不会提前释放需要多输入的审核节点。
- 服务重启后可以恢复 in-flight、completed、pending boundary 状态。

### 阶段五：续跑与失效边界

目标：断点续跑不新建任务，不全量清空，只按边界失效。

改动：

- 新增 invalidation planner。
- 以 result dependency graph 计算失效范围。
- 同一任务继续使用同一 `task_run_id`、`coordination_run_id`、run folder。
- 旧产物标记 `superseded/isolated`，不删除审计记录。
- 下游只重跑依赖失效结果的节点。

完成标准：

- 修改世界观候选后，人设/剧情/大纲中依赖旧世界观的结果失效。
- 无关成功产物保留。
- 产物目录仍属于同一个任务 run。

### 阶段六：编辑器重构

目标：编辑器展示真实任务边界，不展示 runtime step。

改动：

- 节点面板显示 boundary role。
- 边面板显示 edge boundary role。
- 新增“边界视图”：候选、审核、提交、返修、记忆读取。
- 时序页改为“生命周期账本”：阶段、批次、轮次、提交、失效。
- 运行监测页显示 ready/running/blocked 的边界原因。

完成标准：

- 用户能看懂为什么节点 blocked。
- 用户能看懂哪些产物已成为正式事实。
- 用户能看懂重跑会影响哪些下游。
- 不把不同层级混在一个页面。

### 阶段七：写作图迁移

目标：用边界模型重配写作图。

改动：

- 世界观、人设、剧情、大纲、章节正文统一标成 producer。
- 各审核节点标成 reviewer。
- 各记忆提交节点标成 committer。
- 章节推进、卷推进标成 router。
- 明确世界观 committed 后，人设/剧情/大纲才能正式读取。
- 明确章节 committed 后，人物状态、伏笔推进、情节事实才进入后续批次。

完成标准：

- 跑一卷时，候选、审核、提交产物路径和状态清楚。
- 断点续跑使用同一任务目录。
- 修改后续跑只隔离失效产物，不重启全任务。

## 8. 文件级清单

`backend/task_system/graphs/task_graph_models.py`

- 增加 boundary role 字段或通过 contract bindings 表达。
- 增加边职责字段。
- 校验 producer/reviewer/committer 的必要策略。

`backend/task_system/compiler/coordination_graph_compiler.py`

- 编译 Boundary Manifest。
- diagnostics 输出边界支持状态。
- 降低 `timeline_policy` 对调度的权重，强化边界协议。

`backend/task_system/compiler/layered_graph_normalizer.py`

- 不再把 phase/sequence 派生为强制节点链。
- 将 memory/artifact/revision/temporal 边统一归入边界分类。

`backend/runtime/graph_runtime/scheduler.py`

- ready 判断消费 Boundary Manifest。
- phase 只作为 lifecycle open/closed 约束。
- 输出 blocked boundary reasons。

`backend/runtime/coordination_runtime/runtime.py`

- 结果写入时明确 result lifecycle state。
- `_route_next` 支持 ready dispatch queue。
- `resume_from_task_result` 更新结果状态、边界状态、失效范围。

`backend/runtime/memory/timeline_result_record.py`

- 增加 result state、attempt、supersedes、visibility。
- 或迁移为新的 task graph result record。

`backend/runtime/coordination_runtime/context_packet_resolver.py`

- 只允许正式下游读取 committed。
- 审核/返修节点按边界读取 candidate/accepted。

`backend/runtime/graph_runtime/run_monitor.py`

- 展示 boundary health。
- 展示 result lifecycle。
- 展示 invalidation frontier。

`frontend/src/components/workspace/views/task-system/TaskGraphTimelinePage.tsx`

- 改为生命周期账本与边界状态页。
- 不再把 step 作为主展示对象。

`frontend/src/components/workspace/views/task-system/EdgeHandoffCard.tsx`

- 增加边职责编辑。
- 明确启动依赖、审核输入、提交输入、记忆读取、返修路线。

`scripts/configure_writing_modular_novel_graph.py`

- 重配写作图节点职责与边职责。
- 移除 `timeline_group_id = phase_id` 这类容易误导的配置。
- 明确 candidate/review/commit 的产物和记忆策略。

## 9. 验证矩阵

必须覆盖：

1. 世界观设计产物为 candidate，不能被正式下游读取。
2. 世界观审核通过后，提交节点才能读取 accepted candidate。
3. 世界观提交后，人设/剧情/大纲才能读取 committed world。
4. 人设设计与剧情设计互不依赖时可同时 ready。
5. 统筹审查缺任一 required input 时 blocked。
6. 审核失败时只返修失败范围，不提交记忆。
7. 修改世界观候选后，依赖旧候选的下游结果被 superseded。
8. 无关成功产物不被清空。
9. 断点续跑保持同一 run folder。
10. 运行资源串行派发时，业务并发语义不变。
11. 已关闭阶段不会被旧结果重新唤醒。
12. run monitor 能说明 blocked 的具体边界原因。

## 10. 迁移和切换规则

### 10.1 旧字段处理

- `phase_id` 保留，作为生命周期坐标。
- `sequence_index` 保留为编辑排序和旧图迁移输入，不默认作为强制阻塞。
- `timeline_group_id` 不再作为并发语义主字段；并发来自“无互相依赖 + 共同汇合边界”。
- `join_policy` 保留，但归入 reviewer/committer/aggregator 的边界规则。

### 10.2 切换策略

先 shadow，后 enforcement。

1. Shadow：只生成 Boundary Manifest，不改变运行。
2. Warn：发现候选直读、审核绕提交、sequence 误阻塞时报警。
3. Enforce：写作图先启用边界强校验。
4. Cutover：普通图逐步切换。
5. Cleanup：删除无用旧时序排队逻辑。

### 10.3 回滚策略

任何阶段出现以下问题，立即回滚到旧调度：

- committed 结果无法被下游读取。
- candidate 泄漏进正式下游。
- 断点续跑新建任务目录。
- 无关产物被错误失效。
- run monitor 无法解释 blocked 原因。

## 11. 禁止事项

1. 不用 prompt 要求 agent 自己遵守边界。
2. 不用 step 作为用户配置的主概念。
3. 不用 `sequence_index` 强行表达所有依赖。
4. 不把 review 文本当 committed 事实。
5. 不为写作图写 runtime 特判。
6. 不在断点续跑时新建任务总目录。
7. 不同时保留两套互相竞争的 ready 规则。

## 12. 最终目标

优化完成后，图任务系统应该具备以下能力：

- 图表达的是业务因果和边界，不是运行排队。
- 时序系统记录生命周期、提交、失效和恢复坐标。
- 调度器根据依赖与结果状态决定 ready。
- 运行层可并发派发，但并发是资源策略，不污染图语义。
- 候选、审核、提交、记忆有硬边界。
- 续跑能在同一任务内精确隔离失效产物。
- 编辑器能让用户看清真实流程，而不是看一串伪时序节点。

这才是对当前写作任务图真正有用的成熟化方向。
