# Writing Chapter Unit Runtime Plan

## 背景

第11-20章多次重跑后仍持续短稿。最新一次已修复 prompt 中的 action JSON 字段和虚假的 `text_metric`/子任务描述，但质量门仍显示正文约 11293 字，低于最低 18000 字。结论是：单个图节点让模型一次性交付十章正文不稳定，质量门只能发现失败，不能把生产粒度变成单章。

现有配置里已经出现 `sequential_chapter_loop`、`subagent_policy`、`chapter_count` 等字段，但它们停留在节点配置语义，没有被图运行器拆成真实单章 work order。prompt 曾经要求写手“交给单章写作子任务”，属于把运行时未实现能力交给模型假装执行。

## 目标

把章节正文生产从“一个节点一次写十章”改为“运行时真实按单章或小批次执行、逐章质量门反馈、最后汇总成十章候选”。

目标不是降低质量门，也不是让模型少写；目标是让每次模型调用只承担可稳定完成的正文量。

## 权力边界

| 层级 | 目标职责 | 禁止事项 |
| --- | --- | --- |
| 图配置 | 声明章节批次、单章生产策略、汇总策略、质量门阈值 | 不再用 prompt 假装有子任务循环 |
| 图运行器 | 根据配置创建单章执行单元、记录单章结果、决定是否进入下一章 | 不替模型写正文，不绕过质量门 |
| 写手 agent | 只写当前单章正文，遵守上游细纲和记忆边界 | 不决定批次进度，不提交记忆 |
| 质量门 | 统计单章正文长度、章节标题、连续性基础要求，并给出返修反馈 | 不做语义审核裁决 |
| 自修节点 | 对失败单章或汇总稿做一次交稿前修正 | 不批准稿件，不替审核通过 |
| 审核节点 | 审核汇总后的十章正文质量和连续性 | 不补写正文 |

## 目标链路

```text
chapter_outline_self_repair
-> chapter_draft_unit_loop
   -> chapter_draft_unit(chapter 11)
   -> unit_quality_gate
   -> chapter_draft_unit(chapter 12)
   -> unit_quality_gate
   ...
   -> chapter_draft_unit(chapter 20)
   -> unit_quality_gate
-> chapter_draft_batch_assemble
-> chapter_draft_self_repair
-> chapter_review
-> memory_commit_chapter
```

短期实现可不新增可视节点名，但运行时必须真实保存每章单元结果和质量反馈，不能只写在 prompt 中。

## 实施方案

### 1. 图配置语义收敛

文件：

- `scripts/configure_writing_modular_novel_graph.py`

修改：

- 保留批次大小 `CHAPTER_BATCH_SIZE = 10`，因为审核和记忆提交仍以十章为一批。
- 新增或明确 `chapter_unit_execution_policy`：
  - `enabled: true`
  - `unit_size: 1`
  - `unit_start_key: batch_start_index`
  - `unit_end_key: batch_end_index`
  - `unit_target_measure: 2000`
  - `unit_min_measure: 1800`
  - `assemble_output_contract_id: contract.writing.modular_novel.chapter_draft`
- 写手 prompt 改为单章角色：
  - 输入是当前单章任务包、批次细纲、上一章承接、记忆包。
  - 输出只包含当前章正文和极短承接。
  - 不要求它知道十章汇总职责。
- 汇总 prompt 只负责拼接十章，不扩写、不改事实。

### 2. 运行器单章执行单元

文件候选：

- `backend/harness/graph/work_order_executor.py`
- `backend/harness/graph/context_materializer.py`
- `backend/harness/graph/flow_packet.py`
- `backend/harness/graph/models.py`

修改：

- 在执行 `chapter_draft` work order 前检查节点契约是否启用 `chapter_unit_execution_policy`。
- 如果启用，运行器按章号生成内部 unit work order：
  - 每个 unit 带 `chapter_index`、`chapter_title`、`chapter_outline_slice`、`previous_unit_summary`、`quality_feedback`。
  - 每个 unit 独立调用 agent。
  - 每个 unit 完成后立即运行质量门。
  - 未达 `CHAPTER_MIN_WORDS` 时，最多做一次 unit-level repair；仍失败则节点 fail-closed。
- 全部 unit 通过后，组装成原 `chapter_draft` 节点结果，让下游仍读取同一个 `chapter_draft_ref`。

### 3. 单章上下文切片

文件候选：

- `backend/harness/graph/context_materializer.py`
- `backend/task_system/runtime_semantics/quality_gates.py`

修改：

- 从批次细纲中提取当前章标题和目标。若无法可靠提取，则把完整批次细纲给单章写手，但明确“只写当前章”。
- 给第 N 章传入第 N-1 章已通过正文的短承接摘要和最后状态。
- 不把后续章节正文或未通过草稿作为正史输入。

### 4. 质量门调整

文件候选：

- `backend/task_system/runtime_semantics/quality_gates.py`
- `backend/harness/graph/work_order_executor.py`

修改：

- 保留 batch 质量门。
- 新增 unit 质量门模式：
  - 只统计当前章。
  - 检查正式章标题是否匹配当前章号。
  - 正文低于 1800 立即反馈给 unit repair。
- batch assemble 后再跑现有十章质量门，防止汇总丢章。

### 5. 产物与记忆边界

文件候选：

- `backend/harness/graph/output_policy.py`
- `backend/harness/graph/work_order_executor.py`

修改：

- 单章 unit 产物写入 run-scoped draft workspace，不进入 manuscript memory。
- 十章汇总稿仍走当前 `chapter_drafts` 产物合同。
- 只有 `chapter_review -> memory_commit_chapter` 后才能成为正文记忆。

### 6. 重跑策略

重跑第11-20章时：

- 从 `graph_module.chapter_cycle::chapter_draft` requeue。
- 清理 `chapter_draft`、`chapter_draft_self_repair`、`chapter_review`、`memory_commit_chapter` 下游状态。
- 保留 `chapter_outline_self_repair` 及之前结果。
- 避免沿 `chapter_progress_router -> chapter_outline` 循环边回退到 outline。

如当前 `reset_downstream=true` 仍会跨循环边误重置，需要增加“只重置当前批次下游、忽略 loop continuation edge”的 requeue 模式。

## 测试计划

聚焦测试：

```powershell
pytest backend/tests/writing_modular_graph_self_repair_regression.py backend/tests/writing_chapter_loop_progress_regression.py -q
```

新增测试：

- `chapter_draft` 启用 unit execution policy 时，运行器生成 10 个单章 unit。
- 单章低于 1800 时只重修该章，不重写整批。
- 单章仍失败时节点 fail-closed，不进入 review/memory。
- 十章全通过后汇总产物仍使用原 `contract.writing.modular_novel.chapter_draft`。
- requeue 从 `chapter_draft` 起点不会沿 loop continuation 回到 `chapter_outline`。

真实验证：

1. 发布写作图配置。
2. 固定后端 `127.0.0.1:8003` 启动。
3. 从当前大纲后的 `chapter_draft` 重跑第11-20章。
4. 检查每章 unit 结果：
   - 每章 `>= 1800`
   - 十章总量 `>= 18000`
   - 无 action JSON 协议失败
   - review/memory 不接收未通过候选稿

## 风险

- 单章 unit 会增加模型调用次数，成本上升，但每次调用更稳定。
- 如果批次细纲没有清晰章标题，单章切片会退化为“完整细纲 + 当前章号约束”，仍可执行但上下文更大。
- 需要避免 unit repair 过多导致成本失控，先设每章最多一次 repair。
- 如果只改 prompt 不改运行器，问题会复发。

## 完成标准

- 第11-20章重跑不再出现一轮十章压缩短稿。
- 短章能被定位到具体章并只重修该章。
- 图运行仍以十章为审核和记忆提交边界。
- 单 agent 主循环不需要修改。
