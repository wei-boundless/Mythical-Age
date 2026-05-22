# 写作任务真实推演与记忆边界报告

日期：2026-05-22

范围：
- `graph.writing.modular_novel.master`
- `graph.writing.modular_novel.design_init`
- `graph.writing.modular_novel.chapter_cycle`
- `graph.writing.modular_novel.finalize`

这份报告不是概念总结，而是按现有源码链路做的一次“真跑一卷”推演。重点只看四件事：
1. 哪些东西会成为事实。
2. 哪些东西只能停留在候选。
3. 哪些东西只是运行账本和恢复坐标。
4. 哪些地方最容易发生污染、串味和误回收。

## 1. 先给结论

当前系统已经不是“只靠 prompt 写小说”的阶段了，它已经具备了真实的边界层：
- 候选层：`WorkingMemoryItem(status=draft/proposed)`、`FormalMemoryRecordVersion(status=candidate)`
- 审核层：`review_gate` 节点 + `issue_ledger`
- 提交层：`memory_commit` 节点 + `formal_memory.commit_version`
- 运行账本：`TimelineLedger`、`TimelineResultRecord`、`RuntimeLoopState`
- 恢复账本：`TaskRun`、`CoordinationRun`、checkpoint、`accepted_result_records_by_scope`

所以，真正该保留的不是“step 作为业务概念”，而是“边界账本 + 恢复坐标”。`step` 只能是运行时派发波次，不能变成编辑器主概念。

## 2. 源码证据

几个关键事实已经写进代码，不是口头假设：

- `runtime_assembly_builder` 会把 `memory_snapshot`、`artifact_context`、`revision_context` 装配成节点上下文，而且 `memory_snapshot` 的可见别名已经映射到 `working_memory` / `memory_runtime_view` / `task`。
- `FormalMemoryStore.select_versions()` 默认只取 `committed`，并且按 `latest_committed_before_clock` 做可见性门。
- `WorkingMemoryService.context_candidates()` 会过滤 `discarded/superseded/archived/promoted`，只有 `accepted` 更适合作为下游必需项。
- `scheduler.bootstrap_scheduler_state()` 不是单靠顺序排队，它已经在看 `result_record_index`、`accepted_result_records_by_scope`、`edge_handoff_index`。
- `TimelineLedgerStore` 是追加式事件账本，不是 canon。

这说明系统方向是对的，但还没有完全把“哪些信息是事实”锁死。

## 3. 一卷真实推演

### 3.1 启动期

入口是 `project_brief`。它只做项目整理：
- 读取用户目标、题材约束、字数规模、风格方向
- 写出 `project_brief.md`
- 不产生 canon
- 不写正式记忆

这一阶段的正确状态只有一句话：**项目进入设计，不代表世界已经成立。**

### 3.2 世界观阶段

`world_design -> world_review -> memory_commit_world`

真实语义如下：
- `world_design` 只能产出世界候选
- `world_review` 只能裁决、挑错、给返修建议，写 `issue_ledger`
- `memory_commit_world` 才能把通过项固化进 `memory.writing.baseline`

这一段之后，才出现第一批可长期引用的事实：世界卖点、空间划分、历史秩序、资源体系、成长机制、题材边界。

污染点也最明显：
- 把审核意见当世界事实
- 把候选草稿直接喂给后续人设/剧情当 canon
- 把“像是合理的设定”误当“已经冻结的设定”

### 3.3 人设与剧情阶段

当前图里，这一段并不是完全并行的。

现状更接近：
- `world_commit -> character_design -> character_review -> memory_commit_character -> plot_design -> design_sync -> outline_design`

这意味着：
- 角色设计先于剧情设计冻结
- 剧情设计并没有真正与人设并发
- 如果你想让“人设设计师”和“剧情设计师”同步工作，当前图还不支持，至少 `plot_design` 现在吃的是 `character_commit_ref`

这点很关键：**系统不是“名字上并发”，而是“图上真正允许并发”。**

### 3.4 全书细纲阶段

`outline_design -> outline_review -> baseline_memory_seed`

这一段的本质不是写目录，而是把后续一整卷、乃至整书的承接关系定下来。

这里最该保住的不是“标题列表”，而是：
- 伏笔
- 悬念
- 关系推进
- 回收窗口
- 角色状态变化

它们应该是大纲的权威内容，后续运行层只派生线程追踪视图，不该另起一套剧情事实源。

### 3.5 章节批次阶段

`volume_plan -> chapter_outline -> chapter_draft -> chapter_review -> memory_commit_chapter -> chapter_progress_router`

这是整套系统最像“真实产品”的地方，因为它已经不是单章写作，而是批次化交付。

按当前配置：
- 一卷 100 章
- 每批 10 章
- 一卷就是 10 个批次

每个批次的真实语义是：
- `chapter_outline` 只读已提交的世界/人设/大纲/上批承接
- `chapter_draft` 只产出正文候选
- `chapter_review` 只裁决，不补写
- `memory_commit_chapter` 才能把本批正文事实写进动态记忆
- `chapter_progress_router` 只认已提交结果，不认草稿

这也是“行为污染”最容易出现的地方：
- 草稿混入下批上下文
- 审核意见混成正文设定
- 已失败批次仍被当成已完成进度
- 字数统计从草稿数，而不是提交数

### 3.6 卷级收束阶段

`volume_review -> volume_commit -> volume_postmortem -> world_outline_extension_proposal -> extension_review -> extension_commit -> next_volume_router`

这一段的真实作用不是“再写一次总结”，而是把本卷沉淀成下一卷可用的动态记忆：
- `volume_review` 检查整卷达成度
- `volume_commit` 只写动态增量，不改 baseline
- `volume_postmortem` 提供风险和补强方向
- `extension_review` 判断提案有没有越界
- `extension_commit` 只允许写入动态层

## 4. 真事实、候选、局部态、派生态

| 层级 | 典型对象 | 能不能给下游当事实 |
|---|---|---|
| 真事实 | `FormalMemoryRecordVersion(status=committed)`、`ProjectProgressLedger`、已提交章节/卷结果 | 可以 |
| 候选 | `WorkingMemoryItem(status=draft/proposed)`、`FormalMemoryRecordVersion(status=candidate)` | 不可以 |
| 局部态 | `RuntimeLoopState`、`TaskRun`、`CoordinationRun`、`NodeExecutionRequest` | 只用于运行，不是故事事实 |
| 派生态 | `TimelineLedger`、`TimelineResultRecord`、`outline_thread_index` | 只能用于追踪和恢复 |

一句话：**故事事实只认提交，运行事实只认账本。**

## 5. 最容易出问题的地方

### 5.1 版本链不完整

`FormalMemoryStore.commit_version()` 里，旧 head 会被标记成 `superseded`，但 `supersedes_version_id` 目前没有真正写成新版本引用，版本替换链条是不完整的。

这会导致：
- 审计链不好追
- 旧事实被谁替换，不够清楚
- 回滚或复盘时，版本关系不够硬

### 5.2 计划层和运行层混线

`phase_id`、`sequence_index`、`loop_frame_id` 都是有用坐标，但它们只能是生命周期坐标，不应该被误当成业务真相。

真正的 ready，不该由“排队顺序”决定，而应由：
- 上游是否已 committed
- 记忆是否可见
- 审核是否通过
- 依赖边是否满足

### 5.3 章节事实和卷级事实混写

`chapter_commit` 应该只写章节事实和动态记忆。
`volume_commit` 应该只写卷级增量。
`memory_commit_world` 和 `memory_commit_character` 才能写 baseline。

如果这三者互相越权，长篇就会慢慢变成“哪里都像事实，结果哪里都不稳”。

### 5.4 运行时并发不是图上并发

系统可以并发派发多个 ready 节点，但那是调度策略，不是图语义。

真正的图并发，必须满足：
- 没有强依赖边
- 没有共享未提交输入
- 汇合节点能等齐所有必需结果

否则就只是“看起来同时跑”，不是“业务上可以并行”。

## 6. 应该怎么收紧

1. 把 `step` 彻底降级成 runtime dispatch wave，不进入编辑器主概念。
2. 把 `TimelineLedger` 固定为诊断账本，不当 canon。
3. 把 `FormalMemory` 固定为事实源，只允许 commit 节点写。
4. 把 `WorkingMemory` 固定为候选/交接层，不允许下游把它当最终事实。
5. 把 `outline_thread_index` 固定为派生索引，不单独生成剧情事实。
6. 把并发改成“依赖并发”，而不是“顺序并发”。
7. 把续跑改成“同一任务根下的失效重算”，而不是“新开一条任务线”。

## 7. 最后结论

如果现在直接跑一卷，系统已经有能力把它跑出来，但前提是边界必须守住：
- 候选不能越过审核
- 审核不能变成事实
- 提交不能跨层写
- 运行账本不能冒充故事事实
- 续跑必须在同一任务根上做失效隔离

所以，真正该优化的不是“把名称换成 step”，而是把：
- 事实边界
- 可见性边界
- 提交边界
- 恢复边界

四条线收紧。这样它才算一个能稳定承载长篇小说的一卷一卷生产系统。
