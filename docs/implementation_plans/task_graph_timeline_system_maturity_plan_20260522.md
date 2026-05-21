# Task Graph 时序系统成熟化设计报告

日期：2026-05-22

## 1. 结论

当前时序系统已经具备一批正确的底层零件：`phase_id`、`sequence_index`、`timeline_group_id`、`join_policy`、`barrier`、`timeline_result_record`、`timeline_ledger`、checkpoint、批次并发运行态等。但这些零件还没有收束成一个后端权威的“时序计划”。因此现在的问题不是缺字段，而是缺一个稳定的时序内核。

推荐方向是：保留业务时序层，不直接用 LangGraph step 替代；新增后端一等对象 `TimelinePlan`，把业务阶段编译成运行时 super-step/barrier/checkpoint 计划。编辑器负责编辑业务时序，运行时只消费编译后的时序计划。

目标模型：

```text
业务图节点/边
  -> TimelinePlan 编译
  -> StepPlan / ParallelSet / BarrierPlan
  -> 调度器按 step 选择一组 ready 节点
  -> 结果先进入 pending result
  -> barrier/review 通过后提交 timeline_result_record
  -> 下游只读 committed/accepted 结果
```

这比旧的“主链按节点排队”成熟，也比直接暴露 LangGraph step 更适合你的写作长任务系统。

## 1A. 优化/劣化自审

这份方案只有在满足下面条件时才是优化；否则就是把系统复杂度推高的劣化。

### 1A.1 它为什么可能是优化

当前系统的核心不稳定来自“语义分散”：

- 前端有 timeline frame 和预检。
- RuntimeSpec 保留 phase/sequence/group。
- Scheduler 按 phase/sequence 计算 ready。
- CoordinationRuntime 仍按单 `ready[0]` 推进。
- BatchRuntime 有自己的一套 step/merge。
- BarrierState 存在，但只在局部 dispatch plan 中使用。

这些能力方向都对，但权威不统一。`TimelinePlan` 的价值不是“再加一层”，而是把这些分散语义收束成一个后端可验证、可回放、可续跑的计划对象。它应减少下面这些问题：

1. 同一并发关系在前端、后端、运行时有不同解释。
2. 节点完成了，但下游到底能不能读产物依赖隐式判断。
3. 断点续跑不知道该按节点、批次、阶段还是产物状态恢复。
4. 失败重跑时只能粗暴重启，不能按 step frontier 局部失效。

如果 `TimelinePlan` 只是新增字段，不成为调度、产物可见性、断点恢复的共同依据，那它不是优化。

### 1A.2 它为什么可能劣化

风险必须正视：

1. **概念膨胀**：如果 `Phase / Step / Group / Barrier / Gate / Frame` 同时可编辑且互相覆盖，编辑器会更难用。
2. **双权威**：如果旧拓扑调度和新 TimelinePlan 同时决定 ready，运行结果会更不可预测。
3. **迁移误伤**：现有图大量依赖 `phase_id / sequence_index`，直接切换可能让旧图无法续跑。
4. **并发扩大副作用**：把 `ready_nodes` 全部派发出去，可能冲击现有 artifact 写入、request_id、checkpoint、result_record 的幂等逻辑。
5. **写作任务被过度工程化**：如果每个小节点都要求配置 barrier，用户配置成本会增加。

所以本方案不能以“大重构”方式落地。正确落地方式必须是影子计划、只读验证、小范围切换、指标证明。

### 1A.3 判断是否优化的硬指标

推进每一阶段前必须检查这些指标：

1. 普通图在不配置显式 TimelinePlan 时，仍能从现有 phase/sequence 推导出等价运行计划。
2. 同一 phase/sequence/group 的节点，在前端和后端得到同一个 step_id。
3. 新 plan 不改变旧图的单链执行结果，除非图显式声明同 step 并发。
4. 多节点 dispatch 后，每个节点有独立 request_id、dispatch_event_id、result_record_id。
5. 一个分支完成不会提前释放下游 barrier。
6. 失败分支重跑不会覆盖成功分支产物。
7. 断点续跑仍使用同一 task_run_id、coordination_run_id、run folder。
8. run monitor 能解释“为什么现在 blocked/ready”，而不是只显示状态。

只要这些指标有一条做不到，就不能进入切换阶段。

### 1A.4 更保守的执行原则

因此，真实实施顺序要比“新增 TimelinePlan 后立刻接管运行”更保守：

1. 先做 `TimelinePlan` 影子编译，只产出 diagnostics 和 monitor 展示。
2. 先修正前端 step 聚合，让视图不误导用户。
3. 再让 scheduler 同时输出旧 ready_nodes 和新 ready_dispatch_sets，做一致性对比。
4. 只对显式声明 `timeline_policy.runtime_authority = "timeline_plan"` 的图启用新调度。
5. 写作图先作为试点，但不能写写作专用 runtime shortcut。
6. 新调度稳定后，旧 phase/sequence 直推逻辑才降级为编译输入。

这能避免“为了成熟化而把当前能跑的系统打碎”。

## 2. 当前问题定义

### 2.1 真实故障模式

用户提出的典型场景是：

```text
人设设计师 与 剧情设计师 同时设计
  -> 统筹审查必须等两个都完成
  -> 通过后才能写入记忆并进入下一时序
```

这个场景要求系统同时满足五个性质：

1. 同一时序点可以发起多个节点。
2. 后续节点必须等待所有必要分支完成。
3. 失败分支可以单独重跑，成功分支不被污染。
4. 下游只能读取通过 barrier/review 的产物。
5. 断点续跑必须回到同一个任务运行与同一个时序坐标。

当前系统可以表达其中一部分，但没有统一保证。

### 2.2 深层架构原因

旧“主链”如果指一串节点顺序，就天然不适合并发；如果指一串业务阶段，又缺少阶段内部 step/barrier 的正式对象。于是系统容易出现两种摇摆：

- 前端能画出并行组，但运行时仍按单节点推进。
- 后端能算出多个 ready 节点，但主运行入口一次只挑一个执行。

正确修复不是继续给节点补字段，而是把“时序点、并发集合、汇合门、提交边界”升级为运行时一等对象。

## 3. 当前代码证据

### 3.1 已有可复用能力

`backend/task_system/graphs/task_graph_models.py`

- `TaskGraphNodeDefinition` 已有 `phase_id`、`sequence_index`、`timeline_group_id`、`blocks_phase_exit`。
- 节点执行模式已有 `sync / async / parallel / background / barrier / manual_gate`。
- join policy 已有 `all_success / any_success / quorum / coordinator_decides / allow_partial_with_issues / fail_on_any_error`。
- barrier 节点已有基本校验：不能 `fire_and_continue`，必须存在上游。

`backend/task_system/compiler/coordination_graph_models.py`

- `TaskGraphRuntimeNode` 已保留 phase、sequence、timeline group、join policy。
- `TaskGraphRuntimeSpec` 已保留 `temporal_edges`、`loop_frames`、`graph_module_runtime_plans`。

`backend/runtime/graph_runtime/scheduler.py`

- `bootstrap_scheduler_state` 已能按 active phase 与 active sequence 计算 ready/blocked。
- 同一 phase、同一 sequence 的多个节点可以同时 ready。
- timeline result gate 已接入：下游可以被 `timeline_result_missing`、`timeline_result_not_accepted`、`timeline_result_not_effective` 阻塞。
- `allow_partial_with_issues / coordinator_decides` 已有部分汇合语义。

`backend/runtime/shared/models.py`

- 已有 `CoordinationBarrierState`，字段包括 `barrier_id`、`waiting_for_node_ids`、`completed_node_ids`、`failed_node_ids`、`join_policy`。
- 已有 `AgentDispatchPlan`，可以携带 `barrier_states`、`ready_node_ids`、`blocked_node_ids`、`dispatch_groups`。

`backend/runtime/graph_runtime/batch_runtime.py`

- 批次运行已有 `step_states`、`merge_states`、并发批次数限制、批次级修复与 commit。
- 这说明项目里已经有“批次内 super-step + merge”的局部经验，可以抽象回通用任务图时序。

### 3.2 关键缺口

`backend/task_system/compiler/coordination_graph_compiler.py`

- 诊断里明确写着：`metadata.timeline_policy` 仍是 unsupported，当前 LangGraph runtime 仍按拓扑依赖推进。
- `phase_definitions` 是 partial，阶段定义进入 RuntimeSpec diagnostics 和前端预检，但 phase exit policy 没有成为运行调度权威。
- `timeline_group_id` 是 partial，运行调度尚未按 `timeline_group_id` 同步启动。

`backend/runtime/coordination_runtime/runtime.py`

- `_scheduler_node_sets` 会返回 `ready_nodes`。
- 但 `_route_next` 当前取 `ready[0]` 作为 `next_stage`，一次只派发一个节点。
- 这意味着普通图节点的并行 ready 还没有成为主运行链的一组 dispatch，只有 batch runtime 的专用分发可以做到多请求。

`frontend/src/components/workspace/views/task-system/taskGraphTimeline.ts`

- `buildTimelinePhases` 的 step key 包含 `nodeId`：

```text
phase:group:sequence:nodeId
phase:step:sequence:nodeId
```

- 这会导致同一 phase、同一 sequence、同一 group 的节点在前端也被拆成多个 step，而不是一个 super-step。
- 如果目标是“一个时序点内并发”，step key 应按 `phase + sequence + group` 聚合，节点列表放在同一个 step 内。

`backend/runtime/unit_runtime/dispatch_plan_compiler.py`

- 只在 `mode == "barrier"` 时创建 `CoordinationBarrierState`。
- timeline group / same sequence 没有自动形成 barrier。
- 这是 dispatch plan 层的局部能力，没有和主 coordination runtime 的调度闭环统一。

## 4. 本地设计原则约束

从现有设计文档提炼出的约束如下。

`docs/系统规划/168-写作任务设计文件夹-20260519/06-图模板与协议复用.md`

- 完整流程不是一条统一时序的单链路，而是正式流程目录。
- 不同阶段的时序差异是常态。
- 图模板本质是可复用闭环，不是固定业务节点串。

`docs/系统规划/168-写作任务设计文件夹-20260519/08-三阶段任务图拆分.md`

- 设计、创作、收尾应拆成不同任务图。
- 协议可以复用，但时序不能混用。
- 前端不应把不同层级混在一页。

`docs/系统规划/208-写作任务流程记忆防污染与持续运行优化方案-20260521.md`

- 下游只消费 `accepted / committed`。
- `candidate / review` 只能用于本轮返修，不得直接外溢。
- 伏笔和悬念的剧情事实应由大纲结构表达，运行层只能生成派生追踪视图。

`docs/系统规划/211-现有资源统筹与专业长任务持久运行优化设计书-20260521.md`

- 状态机负责长任务时序、恢复、阻塞和收口。
- 投影和 profile 不应覆盖执行义务。
- 不应保留无用旧链路作为兼容分支。

这些原则共同指向一个结论：时序系统必须是结构化的运行协议，不是 prompt 约束，也不是编辑器里的展示字段。

## 5. LangGraph Step 可借鉴但不可直接替代

LangGraph 的 Pregel/graph runtime 思想可以借鉴三个点：

1. super-step：一个运行 tick 内可以执行多个 ready 节点。
2. barrier：下一个 tick 只看上一 tick 已提交的状态。
3. checkpoint：step 边界天然适合作为断点续跑边界。

但不建议把 LangGraph step 直接暴露成你的编辑器主概念。原因是你的系统比 LangGraph 原始 step 多了业务层含义：

- 设计阶段、创作阶段、收尾阶段。
- 审核门、提交门、记忆可见性。
- 卷、章节批次、返修轮次。
- 产物路径、任务文件夹、断点续跑隔离。
- 商业网文写作流程中的候选、审核、提交和长期事实边界。

因此正确关系应该是：

```text
业务 TimelinePlan
  编译为
运行时 SuperStepPlan
  再由
LangGraph/checkpoint/runtime 调度执行
```

也就是说，借 LangGraph 的执行不变量，不借它替代业务时序模型。

## 6. 推荐目标架构

### 6.1 新增一等对象：TimelinePlan

后端需要新增 canonical timeline schema，不能只依赖节点 metadata。

建议对象：

```text
TimelinePlan
TimelinePhaseSpec
TimelineStepSpec
TimelineParallelGroupSpec
TimelineBarrierSpec
TimelineTransitionSpec
TimelineMemoryCommitGateSpec
TimelineLoopFrameSpec
```

其中 `TimelineStepSpec` 是核心：

```text
step_id
phase_id
sequence_index
dispatch_node_ids
parallel_group_id
barrier_id
join_policy
failure_policy
visibility_policy
checkpoint_policy
commit_policy
```

`TimelineBarrierSpec` 负责汇合：

```text
barrier_id
wait_for_node_ids
join_policy
required_result_state
on_success_step_id
on_failure_step_id
retry_scope
commit_scope
```

### 6.2 主链的新定义

主链不再是节点链，而是 phase/step 链：

```text
Phase 1
  Step 1: input
  Step 2: world_design
  Step 3: world_review
  Step 4: memory_commit

Phase 2
  Step 1: character_design + plot_design
  Step 2: design_sync_review
  Step 3: outline_design
```

同一 step 内的节点可以并发，step 出口由 barrier/review/commit policy 裁决。

### 6.3 运行时调度规则

调度器每次不应返回单个 `next_stage`，而应返回 `StepDispatchSet`：

```text
step_id
dispatches[]
barrier_id
checkpoint_id
resume_token
```

执行规则：

1. 只有当前 active step 的节点可以 ready。
2. 同一 step 内所有 ready 且 blocking 的节点一起进入 dispatch set。
3. step 内节点产物先进入 pending result。
4. barrier 达成后，结果升级为 accepted timeline result。
5. review gate 通过后，才能 memory commit。
6. 下一 step 只能读取 accepted/committed 的结果。

### 6.4 Artifact 与 Memory 可见性

每个节点输出应有明确状态：

```text
candidate
pending_review
accepted
committed
rejected
isolated
superseded
```

并行 step 内，分支结果不能互相读半成品。下游只能读：

- 本 step barrier 通过后的 accepted。
- memory commit 后的 committed。
- 显式允许的 diagnostic/review issue。

这样才能减少行为污染和记忆偏移。

### 6.5 断点续跑与重跑

断点续跑的锚点应该是：

```text
task_run_id
coordination_run_id
timeline_plan_version
phase_id
step_id
barrier_id
attempt_index
accepted_result_record_ids
invalidated_result_record_ids
```

重跑不应默认创建新任务文件夹。正确策略：

- 同一业务任务继续使用同一 run folder。
- 有问题的产物移动到 isolated/superseded 状态或隔离目录。
- 新产物写入同一任务 run 下的新 round/attempt。
- 下游缓存按 invalidation frontier 清除，而不是清空全任务。

## 7. 并发问题的标准解法

以“人设设计 + 剧情设计并行，统筹审查汇合”为例：

```text
Phase: design_architecture

Step 10:
  dispatch:
    - character_design
    - plot_design
  barrier:
    id: barrier.design_architecture.design_branches
    join_policy: all_success
    result_state: accepted_candidate

Step 20:
  dispatch:
    - design_sync_review
  reads:
    - accepted candidate from character_design
    - accepted candidate from plot_design

Step 30:
  dispatch:
    - architecture_memory_commit
  gate:
    design_sync_review verdict == pass
```

如果 `plot_design` 失败：

- `character_design` 保持 completed/pending_commit，不重跑。
- barrier 状态为 waiting/failed_partial。
- 只派发 `plot_design` 的 retry attempt。
- `design_sync_review` 不可 ready。
- 下游不能读 `character_design` 的结果作为正式记忆，只能在 retry context 内作为 pending sibling result。

这就是成熟时序系统需要保证的语义。

## 8. 编辑器设计方向

编辑器可见层要取消“父图是一种特殊节点”的主概念，改成“导入模块展开为可编辑的子图结构”。但运行时仍可以有模块实例、版本锚点和隔离作用域。

页面层级建议：

1. Phase Chain View：只看阶段链和阶段出口。
2. Step Plan View：看每个 phase 内的 step、并发组、barrier。
3. Parallel Group Editor：编辑同一 step 内的并发分支。
4. Barrier / Review Gate Inspector：编辑 join policy、失败策略、返修路由。
5. Runtime Monitor View：看当前 active step、running dispatches、barrier 状态、checkpoint。

不要把节点、资源、时序、模块、运行监测全部塞进同一个画布。切换层级应用明确入口。

## 9. 数据模型与 API 变更

### 9.1 后端新增模块

建议新增：

```text
backend/task_system/timeline/timeline_models.py
backend/task_system/timeline/timeline_compiler.py
backend/task_system/timeline/timeline_validator.py
backend/runtime/graph_runtime/step_scheduler.py
```

### 9.2 RuntimeSpec 增强

`TaskGraphRuntimeSpec` 新增：

```text
timeline_plan: dict[str, Any]
step_plans: tuple[dict[str, Any], ...]
barrier_plans: tuple[dict[str, Any], ...]
```

迁移期仍保留 `phase_id / sequence_index / timeline_group_id` 字段，但它们不再是运行时唯一事实源，而是编译输入。

### 9.3 SchedulerState 增强

`TaskGraphSchedulerState` 新增：

```text
active_step_id
ready_step_ids
step_states
barrier_states
dispatch_sets
invalidated_result_record_ids
```

### 9.4 CoordinationRuntime 改造

`_route_next` 从：

```text
ready = [...]
next_stage = ready[0]
```

改为：

```text
dispatch_set = scheduler.next_dispatch_set()
dispatch all nodes in dispatch_set, subject to concurrency limits
checkpoint step dispatch
wait for barrier/result events
```

### 9.5 前端 Timeline 修正

`buildTimelinePhases` 的 step 聚合从：

```text
phase + group + sequence + nodeId
```

改为：

```text
phase + sequence + group
```

无 group 的节点按 `phase + sequence` 归入默认 step。是否允许无 group 节点同 step 并发，由 `timeline_policy.parallel_group_policy` 决定。

## 10. 迁移计划

### 阶段一：影子 TimelinePlan

目标：不改变运行行为，先编译出 canonical timeline plan。

改动：

- 新增 timeline models/compiler/validator。
- 从现有 `phase_id / sequence_index / timeline_group_id / edges` 推导 step/barrier。
- RuntimeSpec diagnostics 输出 timeline plan。
- 前端标准视图读取 timeline plan 展示。

完成标准：

- 现有测试不破。
- 写作图能编译出 design/chapter/finalize 的 step plan。
- 同一 sequence 并发节点在 plan 中同 step。

禁止：

- 不在本阶段改 `_route_next` 派发行为。
- 不写写作专用特判。

### 阶段二：Scheduler 消费 TimelinePlan

目标：ready/blocked 由 step plan 决定。

改动：

- `bootstrap_scheduler_state` 接入 step/barrier 计算。
- 增加 `StepRunState`、`BarrierRunState`。
- join policy 支持至少 `all_success`、`allow_partial_with_issues`、`coordinator_decides`。
- `timeline_group_id` 从展示字段升级为 step dispatch group。

完成标准：

- 同一 step 多节点同时 ready。
- 下游 step 在 barrier 未通过前 blocked。
- 失败分支能被标记为 retryable，成功分支不失效。

### 阶段三：CoordinationRuntime 多节点派发

目标：普通图节点也能真正并发，不只批次节点并发。

改动：

- `_route_next` 返回 dispatch set。
- 新增 `dispatch_ready_step_requests`，复用现有 batch dispatcher 的执行实例思想。
- checkpoint 记录 step dispatch set 与每个 node request。
- `resume_from_task_result` 更新 barrier 状态，而不是直接推进单节点链。

完成标准：

- 两个同 step 节点可同时产生 execution request。
- 任意一个完成不会提前触发下游 review。
- 两个都完成且 accepted 后，下游 review 才 ready。

### 阶段四：Artifact/Memory Commit Gate 收束

目标：解决行为污染和记忆污染。

改动：

- timeline result 状态区分 candidate/pending/accepted/committed。
- memory commit 节点只读 accepted result。
- review 节点不能把自己的补写内容当成被审对象提交。
- run monitor 增加 step/barrier/result visibility 检查。

完成标准：

- candidate 不进入下游事实上下文。
- review 未通过时 memory commit 不 ready。
- 断点重跑只隔离失效 attempt，不新开任务文件夹。

### 阶段五：编辑器重构

目标：编辑器从“节点字段面板”升级为“时序计划工作台”。

改动：

- Phase Chain View。
- Step Plan View。
- Parallel Group Editor。
- Barrier Inspector。
- Runtime Monitor View。
- 删除无用父图可见概念，模块导入直接展开为图结构。

完成标准：

- 用户能一眼看到哪个 step 并发、哪个 barrier 汇合、哪个 commit 门控。
- 不同层级不混在一页。
- 标准视图与运行时 monitor 对同一 timeline plan 展示一致。

## 11. 文件级执行清单

`backend/task_system/graphs/task_graph_models.py`

- 保留节点时序字段作为编译输入。
- 增加校验：同一 phase/sequence 的节点必须能编译进 step。
- barrier/review/memory commit 的关系要能被 validator 检出。

`backend/task_system/compiler/coordination_graph_models.py`

- 增加 runtime spec 的 timeline plan 字段。
- 保留旧字段作为迁移输入。

`backend/task_system/compiler/coordination_graph_compiler.py`

- 调用 timeline compiler。
- diagnostics 不再把 `timeline_policy` 标为 unsupported；至少进入 shadow/supporting 状态。
- `timeline_group_id` 支持状态从 partial 推进到 supported。

`backend/task_system/compiler/layered_graph_normalizer.py`

- 不再只派生相邻 sequence 的 temporal edge。
- 改为派生 step 与 phase barrier，temporal edge 成为兼容投影。

`backend/runtime/graph_runtime/scheduler.py`

- 从 active phase/active sequence 升级为 active step。
- 输出 `ready_dispatch_sets`。
- 输出 barrier state。

`backend/runtime/graph_runtime/scheduler_models.py`

- 新增 `TaskGraphStepState`、`TaskGraphBarrierState`、`TaskGraphDispatchSetState`。

`backend/runtime/shared/models.py`

- 扩展或迁移 `CoordinationBarrierState`，增加 `step_id`、`phase_id`、`attempt_index`、`retry_scope`、`visibility_state`。

`backend/runtime/coordination_runtime/runtime.py`

- `_route_next` 消费 dispatch set。
- `resume_from_task_result` 更新 step/barrier，而非只推进单 stage。
- rewinding/invalidation 按 step frontier 处理。

`backend/runtime/graph_runtime/batch_runtime.py`

- 将批次 `step_states / merge_states` 的通用思想抽象给 timeline step，不做写作特判。

`frontend/src/components/workspace/views/task-system/taskGraphTimeline.ts`

- 修正 step 聚合 key。
- 增加 barrier/step plan 类型。
- preflight 检查 step/barrier 缺失。

`frontend/src/components/workspace/views/task-system/TaskGraphTimelinePage.tsx`

- 拆成 phase、step、parallel group、barrier inspector 分层视图。

`scripts/configure_writing_modular_novel_graph.py`

- 写作图配置不再把所有节点统一塞到 `timeline_group_id = phase_id`。
- 明确设计阶段哪些节点同 step 并发，哪些节点是 review/commit barrier。

`backend/tests/task_graph_scheduler_regression.py`

- 增加同 step 并发、barrier 未满足、分支失败局部重跑测试。

`backend/tests/langgraph_coordination_runtime_regression.py`

- 增加普通图多节点并发 dispatch、server restart 后 step resume 测试。

`frontend/src/components/workspace/views/task-system/taskGraphTimeline.test.ts`

- 增加同 phase/sequence/group 聚合为一个 step 的测试。

## 12. 验证矩阵

必须覆盖这些场景：

1. 同 phase 同 sequence 的两个 agent 同时 ready。
2. `_route_next` 不再只派发 `ready[0]`。
3. 一个并发分支完成时，下游 review 仍 blocked。
4. 两个并发分支都 accepted 后，review ready。
5. 一个分支 failed，另一个 completed，系统只重跑 failed 分支。
6. failed 分支重跑成功后，barrier 通过。
7. review 未通过时，memory commit 不 ready。
8. memory commit 只读取 accepted result，不读取 candidate。
9. 断点续跑保持同一个 `task_run_id / coordination_run_id / run folder`。
10. 重跑隔离旧产物，不新建任务总文件夹。
11. 服务器重启后可从 active step checkpoint 恢复。
12. 编辑器 step 视图和运行 monitor 对同一个 timeline plan 展示一致。

## 13. 禁止的捷径

1. 不允许用 prompt 要求 agent “等另一个节点完成”来替代 barrier。
2. 不允许用节点标题或节点顺序猜并发关系。
3. 不允许让 review 节点补写设定后直接提交为事实。
4. 不允许新开 run folder 伪装断点重跑。
5. 不允许把 `timeline_group_id = phase_id` 当作通用并发组。
6. 不允许只修前端展示，不改后端调度权威。
7. 不允许保留无用旧父图概念作为编辑器主概念。
8. 不允许为写作图写专用 runtime shortcut。

## 14. 最终状态

成熟后的时序系统应该满足：

- 主链是业务 phase/step 链，不是节点单链。
- 并发是 step 内 dispatch set，不是旁路批次特例。
- barrier 是运行时状态对象，不是一个可有可无的节点字段。
- checkpoint 绑定 step/barrier/attempt，而不是只绑定最后 active node。
- 下游只读 accepted/committed，记忆写入只发生在 commit gate 后。
- 编辑器能清楚表达阶段、时序点、并发组、汇合门和运行状态。

这样才能支撑一卷、五卷、一百万字这种长任务：不是每次靠人工盯产物，而是让流程本身具备抗偏移、可续跑、可返修、可审计的能力。
