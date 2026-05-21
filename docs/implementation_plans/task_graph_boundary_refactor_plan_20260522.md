# Task Graph 运行边界系统重构计划书

日期：2026-05-22

## 1. 重构目标

这次重构的目标不是把任务图做得更复杂，而是把系统里“看起来像架构、实际不产生运行约束”的东西清掉，把真正决定运行正确性的边界做成唯一权威。

当前系统的核心问题是：

- 配置字段很多，但不是每个字段都被运行时消费。
- 前端展示很多层，但部分展示不对应真实调度能力。
- 写作图声明了候选、审核、提交、记忆防污染，但运行时结果状态没有完整承接。
- 时序字段被拿来做排队，导致本该无序并发的图任务被硬串行。

重构后的系统要做到：

```text
图上表达业务因果和产物边界
运行时根据边界判断 ready/blocked
调度器只负责派发 ready 节点
时序系统只记录生命周期、批次、轮次、提交和失效
前端只展示真实被后端消费的结构
```

## 2. 真正有用的设计原则

### 2.1 没有运行消费的字段就是噪声

任何字段如果只在配置里存在、只在前端展示、只在 diagnostics 里出现，但不影响 ready、读取、提交、续跑、失效，就不能被称为架构能力。

处理规则：

- 能被运行时消费，就升级为正式协议。
- 不能被运行时消费，就降级为说明字段。
- 既不消费也不说明，就删除。

重点对象：

- `timeline_group_id`
- `timeline_policy`
- `timeline_frames`
- `phase_definitions.exit_policy`
- 写作图里的 governance 声明

### 2.2 图语义不能和调度策略混在一起

图任务应该表达：

- 谁依赖谁。
- 谁读候选。
- 谁审核候选。
- 谁提交事实。
- 谁能触发返修。
- 谁会让下游失效。

调度策略只表达：

- 当前 ready 节点实际派发几个。
- 是否受资源限制排队。
- checkpoint 如何记录派发请求。

所以不能继续把 `sequence_index` 当默认阻塞链，也不能把 step 当业务结构。

### 2.3 产物状态必须比节点状态更重要

节点 completed 不等于产物可被下游当事实读取。

必须区分：

- `candidate`
- `under_review`
- `accepted`
- `committed`
- `rejected`
- `superseded`
- `isolated`

下游正式节点只能读 `committed`。审核节点和返修节点可以读 `candidate / accepted`，但必须带边界范围。

### 2.4 审核节点不能成为事实生产者

审核节点只能裁决、指出问题、给出返修要求。它不能把自己补写的新设定、新剧情、新记忆直接提交为事实。

如果审核节点发现缺口，应该：

```text
review -> revision_request -> producer_retry -> review -> commit
```

不能：

```text
review -> 直接补写 -> commit
```

### 2.5 时序系统只做生命周期账本

时序系统保留，但不再承担节点排队。

它记录：

- 当前阶段。
- 当前卷和章节批次。
- 当前返修轮次。
- 哪些边界已经关闭。
- 哪些结果已经提交。
- 哪些结果已经失效。

它不决定：

- 同一时刻派发几个节点。
- 哪些节点必须按序排队。
- 候选是否自动成为事实。

### 2.6 前端只能展示后端真实权威

前端不能创造假结构。

如果后端没有真正的并发组，前端就不能展示“并行 Frame”让用户以为系统支持。

如果后端没有真正的 phase exit policy，前端就不能把它当强约束展示。

编辑器应该从“字段配置器”变成“边界工作台”。

## 3. 第一轮必须清理或降级的假结构

### 3.1 `timeline_group_id = phase_id`

位置：

- `scripts/configure_writing_modular_novel_graph.py`

问题：

- 这不是并发组，只是把阶段 ID 复制成 group。
- 它会误导前端和后续维护者，以为系统有并发分组语义。

处理：

- 写作图生成脚本停止写入 `timeline_group_id = phase_id`。
- `timeline_group_id` 暂时降级为 legacy/display 字段。
- 真正并发关系由“无互相依赖 + 共同下游汇合边界”表达。

### 3.2 `sequence_index` 默认阻塞链

位置：

- `backend/task_system/compiler/layered_graph_normalizer.py`
- `backend/runtime/graph_runtime/scheduler.py`

问题：

- 自动按 phase 内 sequence 派生 blocking temporal edge。
- scheduler 又按 active sequence 阻塞后续节点。
- 这会把本该并行的节点硬排队。

处理：

- `sequence_index` 降级为显示排序、迁移辅助。
- 阻塞关系必须由显式边或边界规则决定。
- 保留兼容开关：旧图可启用 `legacy_sequence_blocks = true`。

### 3.3 前端 timeline step 视图

位置：

- `frontend/src/components/workspace/views/task-system/taskGraphTimeline.ts`

问题：

- step key 包含 nodeId，每个节点都被包装成 step。
- 这不是运行时 step，也不是业务边界，只是视觉分组。

处理：

- 移除用户可见 step 作为主概念。
- Timeline 页面改为 Lifecycle / Boundary 页面。
- 展示阶段、候选、审核、提交、失效，而不是伪 step。

### 3.4 governance policy 中的空约束

位置：

- `scripts/configure_writing_modular_novel_graph.py`

问题：

- `review_cannot_mutate_candidate`
- `forbid_unreviewed_candidate_commit`
- `candidate_artifacts_are_not_committed_memory`

这些声明方向正确，但如果运行时不消费，就是纸面安全。

处理：

- 抽取成 `BoundaryManifest`。
- 每条约束必须对应 runtime enforcement 或 preflight error。
- 不能 enforcement 的约束标为 warning，不允许标成已支持。

### 3.5 `timeline_policy` 与 `phase_definitions` 的伪权威

位置：

- `backend/task_system/compiler/coordination_graph_compiler.py`

问题：

- 编译器已经标记 `timeline_policy` unsupported。
- `phase_definitions` 只是 partial。
- 但前端和配置仍容易把它们当强控制能力。

处理：

- 文档和 UI 中明确标记为 legacy/lifecycle metadata。
- phase 只表示生命周期坐标。
- phase exit 必须落到边界规则，不能只是 phase 字段。

## 4. 新目标结构

### 4.1 Boundary Manifest

新增一个后端权威对象：

```text
TaskGraphBoundaryManifest
```

它由任务图编译得出，不要求用户手写全部字段。

包含：

```text
node_boundaries
edge_boundaries
result_lifecycle_rules
commit_boundaries
review_boundaries
invalidation_rules
lifecycle_coordinates
diagnostics
```

### 4.2 Node Boundary

每个节点必须明确职责：

```text
producer
reviewer
committer
router
resource
monitor
```

示例：

```text
world_design -> producer
world_review -> reviewer
memory_commit_world -> committer
chapter_progress_router -> router
baseline_memory -> resource
runtime_monitor -> monitor
```

### 4.3 Edge Boundary

每条边必须明确作用：

```text
activation_dependency
candidate_input
review_input
commit_input
memory_read
memory_commit
revision_return
non_blocking_reference
failure_route
```

这会取代目前“edge_type + metadata + wait_policy + ack_policy”分散表达的状态。

### 4.4 Result Lifecycle

新增或扩展结果记录：

```text
TaskGraphResultRecord
```

核心字段：

```text
result_record_id
node_id
state
attempt_index
source_result_record_ids
visible_to_node_ids
visible_to_roles
committed_memory_refs
supersedes_result_record_id
invalidated_by
coordinate
```

`TimelineResultRecord` 可以继续作为底层事件坐标，但不能再单独承担产物生命周期。

### 4.5 Lifecycle Ledger

时序系统改造成生命周期账本：

```text
phase_id
volume_index
batch_range
round_index
attempt_index
opened_boundaries
closed_boundaries
accepted_results
committed_results
invalidated_results
active_retry_scope
```

它只记录边界变化，不给节点排队。

## 5. 分阶段实施计划

### 阶段 0：冻结旧语义扩张

目标：

防止继续向旧 timeline/sequence/group 体系加字段。

改动：

- 写一条内部规则：新能力不得再挂到 `timeline_group_id`、`timeline_frames`、`sequence_index` 上。
- 标记旧字段用途：
  - `phase_id`: 生命周期坐标。
  - `sequence_index`: 展示排序/旧图迁移。
  - `timeline_group_id`: legacy，不作为并发权威。

完成标准：

- 新代码不再新增 timeline group 逻辑。
- 写作图生成脚本不再把 phase_id 复制到 timeline_group_id。

### 阶段 1：Boundary Manifest 影子编译

目标：

先建立权威视图，不改变运行行为。

新增文件：

- `backend/task_system/boundaries/boundary_models.py`
- `backend/task_system/boundaries/boundary_compiler.py`
- `backend/task_system/boundaries/boundary_validator.py`

改动文件：

- `backend/task_system/compiler/coordination_graph_compiler.py`
- `backend/task_system/graphs/task_graph_standard_models.py`

主要工作：

- 从现有节点和边推导 boundary manifest。
- 输出 diagnostics：
  - 哪些字段被 runtime 消费。
  - 哪些字段只是配置噪声。
  - 哪些候选/审核/提交链路不完整。

完成标准：

- 世界观设计链路可被识别为 producer -> reviewer -> committer。
- 人设设计和剧情设计可被识别为互不依赖 producer。
- commit 节点能识别 source candidate 和 review gate。

### 阶段 2：结果生命周期模型

目标：

把候选、审核、提交做成运行时真实状态。

改动文件：

- `backend/runtime/memory/timeline_result_record.py`
- `backend/runtime/coordination_runtime/runtime.py`
- `backend/runtime/coordination_runtime/context_packet_resolver.py`

主要工作：

- 新增 result state。
- `accepted` 不再等同于 `committed`。
- commit 节点生成 committed record。
- rejected/superseded/isolated 不可被正式下游读取。

完成标准：

- producer 完成后结果是 candidate。
- reviewer 通过后结果进入 accepted。
- committer 提交后才进入 committed。
- context resolver 按目标节点职责控制可读状态。

### 阶段 3：Scheduler 改为边界 ready

目标：

节点能否启动由边界规则决定，不由 sequence 默认排队决定。

改动文件：

- `backend/runtime/graph_runtime/scheduler.py`
- `backend/runtime/graph_runtime/scheduler_models.py`
- `backend/task_system/compiler/layered_graph_normalizer.py`

主要工作：

- 消费 Boundary Manifest。
- phase gate 只检查生命周期是否开启/关闭。
- sequence gate 默认关闭。
- required input 必须达到指定 result state。
- blocked reasons 输出具体边界原因。

完成标准：

- 两个互不依赖的 producer 可同时 ready。
- reviewer 必须等所有 review_input 到达 candidate/accepted。
- committer 必须等 commit_input 到达 accepted。
- 已关闭 phase 不会被旧 result 唤醒。

### 阶段 4：运行派发队列

目标：

让运行层能处理多个 ready 节点，但不把派发波次变成图语义。

改动文件：

- `backend/runtime/coordination_runtime/runtime.py`
- `backend/runtime/execution/node_execution_request.py`
- `backend/runtime/graph_runtime/run_monitor.py`

主要工作：

- `_route_next` 不再只取 `ready[0]`。
- 新增 dispatch queue。
- 支持资源策略：
  - 单节点派发。
  - 多节点派发。
  - 限流派发。
- 每个 request 独立记录 request_id、dispatch_event_id、result lifecycle。

完成标准：

- ready 列表中多个节点不会被静默吞掉。
- 资源限制下可以串行派发，但 ready 状态保持真实。
- run monitor 能显示 ready、queued、running、blocked。

### 阶段 5：失效与续跑边界

目标：

断点续跑不重启全任务，不新建任务总目录，只隔离失效范围。

新增文件：

- `backend/runtime/graph_runtime/invalidation_planner.py`

改动文件：

- `backend/runtime/coordination_runtime/runtime.py`
- `backend/runtime/graph_runtime/run_monitor.py`
- artifact materializer 相关文件

主要工作：

- 根据 result dependency graph 计算失效范围。
- superseded 旧结果。
- isolated 问题结果。
- 保留无关成功产物。
- 同一 task_run_id / coordination_run_id / run folder 内继续。

完成标准：

- 修改世界观候选，只失效依赖旧世界观的下游。
- 章节批次返修不影响其他批次。
- 旧产物不被删除，但不会被正式上下文读取。

### 阶段 6：编辑器重构

目标：

前端从 timeline 字段编辑器变成边界工作台。

改动文件：

- `frontend/src/components/workspace/views/task-system/TaskGraphTimelinePage.tsx`
- `frontend/src/components/workspace/views/task-system/taskGraphTimeline.ts`
- `frontend/src/components/workspace/views/task-system/EdgeHandoffCard.tsx`
- `frontend/src/components/workspace/views/task-system/taskGraphStandardView.ts`

主要工作：

- Timeline 页面改名或重构为 Lifecycle & Boundary。
- 节点显示 boundary role。
- 边显示 boundary role。
- 运行监控显示 blocked boundary reasons。
- 删除伪 step 展示。

完成标准：

- 用户能看到“为什么节点不能启动”。
- 用户能看到“哪个产物只是候选，哪个已提交”。
- 用户能看到“重跑会影响哪些下游”。
- 不再展示未被后端消费的伪能力。

### 阶段 7：写作图重配

目标：

用新边界系统重配商业网文写作任务图。

改动文件：

- `scripts/configure_writing_modular_novel_graph.py`
- 写作图相关测试

主要工作：

- 删除 `timeline_group_id = phase_id`。
- world/character/plot/outline/chapter draft 标为 producer。
- review 节点标为 reviewer。
- memory commit 节点标为 committer。
- router 节点标为 router。
- 明确世界观 committed 后，设计节点才能正式读取。
- 明确章节 committed 后，线程、人物、剧情事实才能进入后续批次。

完成标准：

- 跑一卷时，产物状态清楚。
- review 和 commit 都有落盘。
- 断点续跑不新建任务目录。
- 修改后续跑只隔离失效产物。

## 6. 测试计划

### 6.1 必须新增的后端测试

- producer 结果只能进入 candidate。
- reviewer 不能直接提交事实。
- committer 只能读取 accepted。
- committed 才能被正式下游读取。
- rejected/superseded/isolated 不可被正式下游读取。
- 两个无依赖 producer 同时 ready。
- reviewer 缺任一 required input 时 blocked。
- sequence_index 不再默认阻塞。
- 修改上游 result 后，下游按依赖失效。
- 同一 run folder 内续跑。

### 6.2 必须新增的前端测试

- 不再把每个 node 包成 step。
- 节点显示 boundary role。
- 边显示 boundary role。
- blocked reason 能映射到边界原因。
- 未被后端支持的 timeline 字段不显示为强能力。

### 6.3 写作图回归测试

- 世界观：candidate -> review -> accepted -> commit -> committed。
- 人设/剧情：世界观 committed 前 blocked。
- 设计统筹：缺任一输入 blocked。
- 章节正文：只能写当前批次。
- 章节提交：只提交审稿通过结果。
- 续跑：只重跑失效范围。

## 7. 切换策略

### 7.1 Shadow

先只生成 Boundary Manifest，不影响现有运行。

### 7.2 Warn

发现噪声字段和伪约束时报警：

- timeline_group_id 和 phase_id 相同。
- sequence 派生阻塞边。
- review policy 配置了但运行不消费。
- commit guard 配置了但没有 source candidate。

### 7.3 Enforce

先对写作图启用强校验。

### 7.4 Cutover

调度器改用边界 ready。

### 7.5 Cleanup

删除或降级旧 timeline 排队逻辑。

## 8. 禁止事项

1. 禁止继续用 prompt 代替运行边界。
2. 禁止继续把 `sequence_index` 当默认执行链。
3. 禁止把 `timeline_group_id` 当并发组。
4. 禁止把 review 输出直接当 committed 事实。
5. 禁止只在 governance policy 里声明规则而不 enforcement。
6. 禁止前端展示后端不支持的强能力。
7. 禁止为了续跑新建任务总目录。
8. 禁止为写作图写后端特判。

## 9. 最终验收标准

重构完成后，系统必须做到：

- 每个节点为什么 ready/blocked 可解释。
- 每个产物处于什么生命周期状态可追踪。
- 每条边的作用可被运行时消费。
- 时序只记录生命周期，不强行排队。
- 调度可以并发，但不污染图语义。
- 续跑精确隔离失效产物。
- 前端展示的能力都是真能力。

如果做不到这些，就不是重构成功，只是把旧问题换了新名字。
