# 写作任务图正式记忆入库修复计划书

日期：2026-05-22

## 1. 问题定义

当前写作图的核心故障不是“prompt 不够长”，而是长篇生产所依赖的世界观、人设、大纲、正文事实没有稳定进入正式记忆。产物文件已经落盘，但 formal memory 中大量记录只是产物引用壳，`canonical_text` 为空，后续节点读到的不是可写作依据，而是“某节点已产出若干产物引用”的摘要。

正确的终态是：

1. 世界观、人设、大纲、章节摘要、正文事实、伏笔状态都能作为正式记忆记录被写入、读取、版本化和追踪。
2. 下游节点读取记忆时，能看到有内容的 `canonical_text` 或明确授权展开的 artifact 正文，而不是只有 artifact ref。
3. 写作图可以使用小说专用集合与 record key，但通用 runtime 只认识“正式记忆记录、产物、候选、提交、读取策略”，不认识章节、卷、正文这类业务概念。
4. 如果 required memory 缺失，节点必须 fail closed，不能让写手带着空记忆继续跑。

## 2. 技术源报告

### 2.1 真实源码事实

1. `scripts/configure_writing_modular_novel_graph.py` 已声明专业集合：
   - `world_bible`
   - `world_element_cards`
   - `character_baselines`
   - `relationship_baselines`
   - `outline_canon`
   - `outline_thread_index`
   - `chapter_summaries`
   - `manuscript_fact_index`
   - `scene_continuity`

   但 `_repository_collection()` 当前把读写集合压扁为 `baseline`、`mutable`、`manuscript`、`issues`、`artifact_refs`。这些专业集合没有成为真正的 memory edge 地址。

2. `backend/runtime/coordination_runtime/runtime.py` 的 `_submit_stage_working_memory_candidates()` 在没有显式 `working_memory_candidates` 时，会自动生成候选：
   - summary 是“stage 已产出 N 个产物引用，等待后续审核或提交”
   - artifact_refs 有值
   - canonical_text 没有值

3. `backend/memory_system/formal_memory_service.py` 的 `write_candidate_from_edge()` 只从 candidate 的 `canonical_text`、`payload.canonical_text`、`payload.text`、`payload.content` 取正文。它不会根据 artifact ref 自动读取 markdown 文件。

4. `backend/runtime/coordination_runtime/runtime.py` 的 `_readable_memory_snapshot_sections()` 只展示 `summary` 或 `canonical_text`，不会展开 formal memory 的 artifact refs。formal memory 一旦是空壳，下游 agent 看到的也就是空壳。

5. 真实数据库 `storage/formal_memory/formal_memory.sqlite` 中，`memory.writing.baseline` 多条 committed 记录的 `canonical_text` 长度为 0，summary 是空壳摘要。这证明问题已经在真实运行中发生，不是推测。

### 2.2 当前结构里有价值的部分

这些不要推翻：

1. 写作图已经有 `baseline / mutable / manuscript / artifact_index / issue_ledger` 五层结构。
2. 设计、审核、提交的职责分层是正确方向。
3. `memory_commit_*` 节点作为唯一正式记忆提交权威是正确方向。
4. `chapter_draft` 的写前取材策略是正确方向。
5. 角色设计与剧情设计并行、`design_sync` 对齐后再进大纲，是正确方向。

需要修的是正式记忆入库、读取和验证，不是在旧壳上继续堆 prompt。

## 3. 修复总方向

采用“双层修复”：

1. 通用底座修复：
   - 增加通用的 formal memory candidate materialization 机制。
   - 增加 missing required formal memory 的 fail-closed 执行门。
   - 改进正式记忆快照展示，使模型能看到可用正文或明确的缺失诊断。

2. 写作图专用修复：
   - 不再把专业集合压扁成粗集合。
   - 给每类写作节点定义真实读写矩阵。
   - 给提交节点定义结构化记忆候选产出规则。
   - 增加写作专用回归测试，验证下游节点真的能读到世界观、人设、大纲和章节事实。

## 4. 目标架构

### 4.1 正式记忆记录模型

每条正式记忆记录至少应具备：

```text
repository_id
collection_id
record_key
record_kind
summary
canonical_text
artifact_refs
source_node_id
source_stage_id
source_review_ref
source_candidate_ref
commit_state
visible_after_clock_seq
```

写作图可以定义自己的 `record_kind`，例如：

```text
world_bible
world_element_card
frozen_fact
forbidden_change
character_baseline
relationship_baseline
outline_canon
outline_thread
approved_chapter_batch
chapter_summary
manuscript_fact
scene_continuity
chapter_hook
character_state_delta
setting_expansion_card
outline_adjustment
next_batch_requirement
```

但这些只是图配置里的业务值，runtime 不内置这些词。

### 4.2 通用 materialization policy

在节点 `memory_writeback_policy` 中增加通用字段：

```json
{
  "candidate_materialization_policy": {
    "enabled": true,
    "mode": "artifact_text_when_candidate_text_missing",
    "allowed_source": "accepted_stage_artifact_refs",
    "artifact_ref_filters": {
      "include_extensions": [".md", ".txt", ".json"],
      "exclude_path_contains": ["/debug/"]
    },
    "record_rules": [
      {
        "repository_id": "memory.writing.baseline",
        "collection_id": "world_bible",
        "record_key": "world_bible.current",
        "record_kind": "world_bible",
        "source_artifact_role": "primary_output",
        "canonical_text_mode": "full_artifact_text",
        "summary_mode": "first_heading_or_excerpt"
      }
    ]
  }
}
```

这是通用策略：它只是把已接受产物转成正式记忆候选。写作图负责提供 collection、record_key、record_kind。

### 4.3 写作记忆库结构

`memory.writing.baseline`

| collection | 用途 |
|---|---|
| `world_bible` | 已冻结世界观主文档 |
| `world_element_cards` | 地图层级、历史、秩序、资源、成长体系、势力关系等可检索卡片 |
| `character_baselines` | 已冻结角色基准 |
| `relationship_baselines` | 已冻结关系网络 |
| `outline_canon` | 已审核全书大纲、分卷结构、主线结构 |
| `outline_thread_index` | 伏笔、悬念、关系推进、回收窗口 |
| `frozen_facts` | 禁止改写的硬事实 |
| `forbidden_changes` | 明确禁止的改动 |

`memory.writing.mutable`

| collection | 用途 |
|---|---|
| `chapter_state_deltas` | 每批正文造成的状态变化 |
| `volume_state_deltas` | 卷级状态变化 |
| `extension_commits` | 审核通过的动态扩展 |
| `continuity_notes` | 连续性说明和风险 |
| `character_state_snapshots` | 当前角色状态快照 |
| `setting_expansion_cards` | 世界细节增量卡 |
| `outline_adjustments` | 大纲动态调整 |
| `next_batch_requirements` | 下一批必须读取事项 |

`memory.writing.manuscript`

| collection | 用途 |
|---|---|
| `approved_chapter_batches` | 已审核通过的正文批次引用 |
| `chapter_summaries` | 逐章摘要 |
| `manuscript_fact_index` | 正文已发生事实索引 |
| `scene_continuity` | 场景、位置、时间、道具连续性 |
| `chapter_hooks` | 章末钩子、伏笔状态 |
| `prose_refs` | 正文产物引用 |

## 5. 节点读写矩阵

### 5.1 设计初始化

| 节点 | 必读 | 写入 | 硬边界 |
|---|---|---|---|
| `project_brief` | 用户硬设定 | artifact only | 不创作设定 |
| `world_design` | project brief | world candidate artifact | 不写 baseline |
| `world_review` | world candidate artifact | issue ledger + review artifact | 不替设计节点补设定 |
| `memory_commit_world` | approved world candidate + review | `world_bible`、`world_element_cards`、`frozen_facts`、`forbidden_changes` | 只提交通过内容 |
| `character_design` | `world_bible`、`world_element_cards`、`frozen_facts` | character candidate artifact | 不改世界观 |
| `plot_design` | `world_bible`、`world_element_cards`、`frozen_facts` | plot candidate artifact | 不默认人设已通过 |
| `design_sync` | world baseline + character candidate + plot candidate | issue ledger + alignment artifact | 只裁决对齐，不冻结 |
| `memory_commit_character` | character review + design sync | `character_baselines`、`relationship_baselines` | 没有 sync 不提交 |
| `outline_design` | world baseline + character baseline + plot candidate + sync | outline candidate artifact | 不另造事实源 |
| `outline_review` | outline candidate + baseline | issue ledger + review artifact | 不替大纲补写 |
| `baseline_memory_seed` | approved outline + approved design assets | `outline_canon`、`outline_thread_index`、`frozen_facts`、`forbidden_changes` | 不写 mutable/manuscript |

### 5.2 章节循环

| 节点 | 必读 | 写入 | 硬边界 |
|---|---|---|---|
| `volume_plan` | baseline + previous volume mutable + manuscript summaries | volume plan artifact | 不改 canon |
| `chapter_outline` | baseline + volume plan + previous batch summaries + continuity | chapter outline artifact | 不写正文 |
| `chapter_draft` | baseline + mutable + manuscript + chapter outline | draft artifact | 必须先写取材记录 |
| `chapter_review` | draft + chapter outline + baseline + mutable + manuscript | issue ledger + review artifact | 偏移必须裁决，不静默吸收 |
| `memory_commit_chapter` | approved draft + review + outline | mutable + manuscript + artifact index | 不写 baseline |
| `chapter_progress_router` | chapter commit receipt | route artifact | 只统计已提交批次 |
| `volume_review` | volume plan + chapter commits + manuscript | issue ledger + review artifact | 不补写正文 |
| `volume_commit` | approved volume review + chapter commits | mutable + artifact index | 不写 baseline/manuscript 正文 |
| `volume_postmortem` | volume commit + baseline + mutable | postmortem artifact | 只形成观察与提案入口 |
| `world_outline_extension_proposal` | postmortem + baseline + mutable | extension proposal artifact | 不直接修改记忆 |
| `extension_review` | extension proposal + baseline | issue ledger + review artifact | 审核动态扩展 |
| `extension_commit` | approved extension proposal + review | mutable + artifact index | 不覆盖 frozen facts |

## 6. 实施计划

### 阶段一：写作图 memory edge 结构化

文件：

```text
scripts/configure_writing_modular_novel_graph.py
backend/tests/writing_modular_novel_graph_config_regression.py
```

改动：

1. 引入写作图专用 `MemoryReadSpec` / `MemoryWriteSpec` 或等价结构。
2. 移除 `_repository_collection()` 对写作专业集合的压扁逻辑。
3. `_memory_edges_for_nodes()` 按节点真实读写矩阵生成 edge。
4. 每条 memory edge 带上：
   - `repository`
   - `collection`
   - `record_kinds`
   - `record_keys` 或 selector
   - `model_visible_label`
   - `usage_instruction`
   - `on_missing`

完成标准：

1. `memory_commit_world -> memory.writing.baseline` 至少生成 `world_bible`、`world_element_cards`、`frozen_facts`、`forbidden_changes` 写入边。
2. `chapter_draft` 读取的不是粗集合 `baseline`，而是具体的 baseline/mutable/manuscript collection。
3. 写作图测试禁止把 `memory.writing.baseline` 的主要读写 collection 继续生成为 `baseline`。

### 阶段二：通用 formal memory candidate materializer

文件：

```text
backend/runtime/coordination_runtime/runtime.py
backend/runtime/coordination_runtime/memory_helpers.py
backend/runtime/coordination_runtime/context_packet_resolver.py
backend/tests/langgraph_coordination_runtime_regression.py
backend/tests/formal_memory_store_regression.py
```

改动：

1. 增加通用 helper：根据 `candidate_materialization_policy` 从已接受 artifact refs 生成正式记忆候选。
2. 排除 debug artifact，避免把 run report 写成 canon。
3. 对 `artifact_index` 这类 refs-only 仓库保持 refs-only，不灌入大段正文。
4. 当 candidate 已经带 `canonical_text` 时，尊重 candidate，不重复读取 artifact。
5. 当 policy 要求 `canonical_text_required` 但无法取得正文时，写入失败并返回 formal memory error。

完成标准：

1. 提交节点即使没有 event diagnostics 中的 `working_memory_candidates`，也能通过显式 policy 把主 markdown 产物转成 formal memory candidate。
2. 非提交节点不会因为有 artifact refs 就自动写 canon。
3. debug run report 不会进入 baseline/mutable/manuscript 正文。

### 阶段三：提交节点结构化输出契约

文件：

```text
scripts/configure_writing_modular_novel_graph.py
backend/tests/writing_modular_novel_graph_config_regression.py
```

改动：

1. `memory_commit_world` 的 commit schema 增加：
   - `world_bible_record`
   - `world_element_cards`
   - `frozen_facts`
   - `forbidden_changes`
2. `memory_commit_character` 的 commit schema 增加：
   - `character_baseline_records`
   - `relationship_baseline_records`
   - `character_forbidden_changes`
3. `baseline_memory_seed` 的 commit schema 增加：
   - `outline_canon_record`
   - `outline_thread_index_records`
   - `baseline_fact_index`
4. `memory_commit_chapter` 的 commit schema 增加并强制：
   - `approved_chapter_batch_refs`
   - `chapter_summaries`
   - `manuscript_fact_index`
   - `scene_continuity`
   - `chapter_hooks`
   - `character_state_deltas`
   - `setting_expansion_candidates`
   - `foreshadowing_status_updates`
   - `next_batch_memory_requests`

完成标准：

1. 提交员 prompt 是 agent-facing 职责说明，不写开发说明。
2. schema 可以被 runtime materializer 使用。
3. 提交节点不再只产出“提交了几个 artifact refs”的空壳。

### 阶段四：required memory fail-closed

文件：

```text
backend/runtime/coordination_runtime/runtime.py
backend/runtime/coordination_runtime/context_packet_resolver.py
backend/tests/langgraph_coordination_runtime_regression.py
backend/tests/writing_professional_runtime_regression.py
```

改动：

1. `_select_stage_working_memory_context()` 已能拿到 `missing_required_records`，但执行前需要硬拦截。
2. 当节点有 required memory read edge 且 formal memory 缺失时：
   - 不派发 agent。
   - 写 timeline event：`memory_snapshot_missing_required_records`。
   - stage 状态进入 blocked 或 pending upstream。
3. 对非 required 的 preferred memory，只记录 warning，不阻塞。

完成标准：

1. `character_design` 在没有 `world_bible.current` 时不能执行。
2. `chapter_draft` 在没有 `chapter_outline_ref`、baseline world、baseline characters 时不能执行。
3. 回归测试证明 required memory 缺失不会继续生成正文。

### 阶段五：记忆快照可读性修复

文件：

```text
backend/runtime/coordination_runtime/runtime.py
backend/runtime/contracts/runtime_assembly_builder.py
backend/tests/runtime_assembly_builder_test.py
backend/tests/langgraph_coordination_runtime_regression.py
```

改动：

1. `_readable_memory_snapshot_sections()` 按 repository/collection 分组展示。
2. 每条记录展示：
   - label
   - repository/collection/record_key
   - usage_instruction
   - canonical_text 摘要或正文片段
   - artifact refs
3. 对写作长文本节点，允许更高的记忆展示预算，但必须按 collection 预算控制，避免前 20 条记录吃掉全部上下文。
4. 如果记录 `canonical_text` 为空但 artifact refs 存在，展示明确警告：
   - “此记录只有产物引用，没有正式记忆正文”
   - 这类记录不得满足 required canonical memory。

完成标准：

1. 写手能在输入里直接看到世界规则、人物状态、上一批摘要、活跃伏笔等具体内容。
2. 空壳记录不会被伪装成可用 canon。

### 阶段六：旧空壳记录隔离与重跑策略

文件：

```text
backend/maintenance/
docs/implementation_plans/
backend/tests/formal_memory_run_scope_regression.py
```

改动：

1. 增加维护脚本或维护说明：识别 `canonical_text = '' AND artifact_refs_json != '[]'` 的 writing formal records。
2. 对当前任务继续跑时，必须先把这些空壳记录标为 invalidated 或隔离，不允许继续作为 committed canon 被选中。
3. 对《洪荒时代》当前运行，建议从最近一次有效的 `world_candidate + world_review` 之后重跑 `memory_commit_world`，而不是继续沿用空壳 baseline。

完成标准：

1. 新运行不会读到旧空壳 baseline。
2. 续跑时能明确知道是从哪个 commit 节点重新提交，而不是重新创作全部上游产物。

### 阶段七：端到端验证

测试命令候选：

```text
python -m pytest backend/tests/formal_memory_store_regression.py backend/tests/langgraph_coordination_runtime_regression.py::test_formal_memory_read_edge_does_not_fallback_to_working_memory -q
python -m pytest backend/tests/writing_modular_novel_graph_config_regression.py backend/tests/writing_professional_runtime_regression.py -q
python -m pytest backend/tests/task_artifact_materializer_regression.py backend/tests/chapter_draft_quality_gate_regression.py -q
```

新增验证用例：

1. 世界观提交后，`character_design` 的 memory snapshot 中包含 `world_bible.current` 的 `canonical_text`。
2. 人设提交后，`outline_design` 能读取 `character_baselines.current` 和 `relationship_baselines.current`。
3. 大纲提交后，`chapter_draft` 能读取 `outline_canon.current` 和 `outline_thread_index`。
4. 章节提交后，下一批 `chapter_outline` 和 `chapter_draft` 能读取上一批 `chapter_summaries`、`manuscript_fact_index`、`chapter_hooks`。
5. 空壳 formal memory 不能满足 required memory。
6. debug artifact 不会进入任何 canon record 的 `canonical_text`。

## 7. 迁移与切换规则

1. 不对旧空壳记录做无声兼容。空壳记录应该隔离、失效或要求重提交流程。
2. 如果用户要求继续同一任务断点，续跑点应落在最近的 commit 节点，而不是候选创作节点。
3. 对《洪荒时代》，当前最稳妥切换点是：
   - 保留已通过的 `world_candidate_round_002.md`
   - 保留 `world_review_round_002.md`
   - 重跑 `memory_commit_world`
   - 之后重新推进 `character_design / plot_design / design_sync`
4. 只有当 formal memory 中能读到非空 `world_bible.current`，才允许进入后续设计。

## 8. 风险与控制

| 风险 | 控制 |
|---|---|
| runtime 被写作概念污染 | materialization policy 通用化，写作名词只在图配置 |
| artifact 正文过长挤爆上下文 | 按 collection 分组预算，写作图拆 element cards |
| debug report 被写进 canon | artifact filter 默认排除 `/debug/` |
| 模型提交产物格式不稳定 | runtime 支持 artifact materialization，不完全依赖模型 diagnostics |
| required memory 缺失仍继续跑 | stage dispatch 前 fail closed |
| 旧记录继续污染新任务 | shell record 隔离和 run-scoped 读取验证 |

## 9. 文件级执行清单

### 必改

```text
scripts/configure_writing_modular_novel_graph.py
backend/runtime/coordination_runtime/runtime.py
backend/runtime/coordination_runtime/memory_helpers.py
backend/runtime/coordination_runtime/context_packet_resolver.py
backend/tests/writing_modular_novel_graph_config_regression.py
backend/tests/langgraph_coordination_runtime_regression.py
backend/tests/formal_memory_store_regression.py
backend/tests/runtime_assembly_builder_test.py
```

### 视实现需要改

```text
backend/runtime/contracts/runtime_assembly_builder.py
backend/runtime/unit_runtime/finalizer.py
backend/memory_system/formal_memory_service.py
backend/memory_system/formal_memory_store.py
backend/tests/writing_professional_runtime_regression.py
```

### 维护与文档

```text
backend/maintenance/
docs/implementation_plans/writing_formal_memory_commit_repair_plan_20260522.md
```

## 10. 验收标准

这次修复完成后，必须满足：

1. 写作图中专业 collections 不再只是配置名词，而是真实 memory edge 地址。
2. `memory_commit_world` 后，formal memory 中至少存在非空 `world_bible.current`。
3. `memory_commit_chapter` 后，formal memory 中至少存在非空 `chapter_summaries` 和 `manuscript_fact_index`。
4. 下游节点的输入消息里能看到正式记忆正文或结构化摘要。
5. required memory 缺失时，节点不会执行。
6. 原有写作图模块、章节循环、断点续跑、产物落盘测试继续通过。
7. 通用 runtime 中不出现写作专用节点名或章节业务默认值。

