# 写作图任务深度开发实施计划

日期：2026-05-22

目标：在通用图编辑器底座已经收紧的前提下，把模块化长篇写作图从“能串起来跑”升级为“能持续生产高质量长篇产品”的专业工作流。此计划只改写作专用图、写作专用契约和写作图回归测试，不把小说业务概念塞回通用运行时。

## 1. 技术源报告

### 1.1 当前可用结构

源码入口是 `scripts/configure_writing_modular_novel_graph.py`。

当前图已经具备四个关键边界：

- 图模块：`master -> design_init -> chapter_cycle -> finalize`。
- 记忆库：`baseline`、`mutable`、`artifact_index`、`issue_ledger`。
- 审核提交链：候选产物先进入 review，再由 memory_commit 节点写入记忆。
- 章节循环：一卷一百章，每十章一批，批次由运行时边界控制。

这些结构是有价值的，应该保留。

### 1.2 真实缺口

现有问题不在于“写手 prompt 不够长”，而在于长期写作缺少几个硬协议：

1. 正文事实没有独立分层。章节正文、章节摘要、人物状态变化、设定增量和产物引用都挤在 `mutable` 的粗集合里，后续节点虽然能读，但很难精确判断哪些是正文事实、哪些是连续性状态、哪些只是扩展建议。
2. 写手没有显式写前取材协议。`chapter_draft` 被要求读取记忆，但没有要求它先输出写前判断：本批要用哪些世界规则、人物状态、伏笔线程、上一批承接和禁改边界。
3. 世界观生长协议不够硬。已有卷后 `world_outline_extension_proposal`，但它的职责过宽，没有把世界细节卡、角色状态卡、大纲线程卡、正文连续性卡分清。
4. 提交包 schema 过泛。所有提交节点都使用同一组基础字段，章节提交没有强制包含章节摘要、人物状态 delta、世界设定 delta、伏笔状态、连续性索引、下一批取材清单。
5. 人设与剧情目前仍是串行。用户希望二者能拆分各自做出最出彩设计，再对齐；串行可以减少冲突，但牺牲了设计发散。更合理的做法是：二者都必须读已提交世界观，分别产出候选，然后由对齐节点做 barrier，只有对齐通过后才进入全书细纲。
6. 记忆整理员职责还不够规范。它应该只做提纯、分层、索引、版本和提交回执，不应该补设定、替审核、改正文。

### 1.3 不能做的事

- 不能把 `chapter_draft`、`outline`、`world_bible` 等写作概念放回通用 runtime / orchestration / memory_system。
- 不能用 prompt 替代提交边界。prompt 只描述角色职责，真正的读写目标、schema、可见性、提交权必须写进图契约。
- 不能把未审核候选、审核意见、卷后建议直接变成 canon。
- 不能为通用图编辑器引入小说专属字段。小说专属字段只能存在于写作图配置和写作测试中。

## 2. 推荐设计方向

采用“专用写作图 + 通用底座契约”的方式，不新增写作专用后端入口。

核心结构如下：

```text
baseline
  冻结世界观、角色、人设关系、全书大纲、禁改边界

mutable
  卷级动态、章节动态、设定扩展、角色状态、连续性状态

manuscript
  已通过审核的正文批次、章节摘要、正文事实索引、章末承接

artifact_index
  候选/审核/提交/最终产物引用

issue_ledger
  审核问题、偏移、返修、冲突裁决
```

`manuscript` 是本次新增的写作专用记忆仓库。它的意义不是再存一遍全文，而是把“已经审核通过的正文产品及其可检索摘要”从动态设定里分离出来，让写手和审核员可以稳定读取上一批正文事实。

## 3. 目标流程

### 3.1 设计初始化

```text
project_brief
  -> world_design
  -> world_review
  -> memory_commit_world
  -> character_design
  -> plot_design
  -> design_sync
  -> outline_design
  -> outline_review
  -> baseline_memory_seed
```

调整点：

- `character_design` 和 `plot_design` 同时依赖 `memory_commit_world`，都只读取已提交世界观。
- `plot_design` 不能再依赖已提交人设；它要先基于世界观设计主线压力、场域推进、秘密揭示和商业节奏。
- `design_sync` 同时接收角色候选、剧情候选、世界基准，负责对齐冲突和互相强化。只有对齐后的产物才能进入 `outline_design`。
- `outline_design` 必须把伏笔、悬念、关系推进、回收窗口写成大纲权威内容，不另开独立剧情事实源。

### 3.2 章节批次

```text
volume_plan
  -> chapter_outline
  -> chapter_draft
  -> chapter_review
  -> memory_commit_chapter
  -> chapter_progress_router
```

调整点：

- `chapter_draft` 仍然是写手自己取材，不新增单独 `chapter_memory_select` 节点，避免把写作判断拆成僵硬流程。
- 但写手必须在正文前输出“写前取材记录”，列出本批读取和采用的世界规则、人物状态、伏笔线程、上一批承接、禁改边界。
- `chapter_review` 必须审核写前取材是否真实支撑正文，不能只看正文表面。
- `memory_commit_chapter` 同时写入 `mutable` 与 `manuscript`：动态记忆保存状态变化，正文库保存正文引用、章节摘要和正文事实索引。

### 3.3 设定增长

```text
volume_postmortem
  -> world_outline_extension_proposal
  -> extension_review
  -> extension_commit
```

调整点：

- 扩展提案必须拆成世界细节卡、角色状态卡、大纲线程卡、连续性修正卡。
- 世界观可以增长，但默认进入 `mutable`。只有后续明确需要稳定冻结，并通过专门审核/提交链，才可以升级 baseline。
- 如果正文偏离世界观或大纲，不能默默吸收。审核节点必须裁决：返修正文、动态吸收、或要求回到上游设计节点。

## 4. 记忆读写矩阵

| 节点 | 必读 | 可写 | 禁止 |
|---|---|---|---|
| `world_design` | project brief | candidate artifact | baseline/mutable |
| `memory_commit_world` | world review + candidate | baseline + artifact index | mutable/manuscript |
| `character_design` | baseline world | candidate artifact | baseline/mutable |
| `plot_design` | baseline world | candidate artifact | baseline/mutable |
| `design_sync` | baseline world + character candidate + plot candidate | issue ledger + artifact index | baseline/mutable |
| `baseline_memory_seed` | outline review + design assets | baseline + artifact index | mutable/manuscript |
| `volume_plan` | baseline + mutable + manuscript summaries | candidate artifact | all memory writes |
| `chapter_outline` | baseline + mutable + manuscript summaries | candidate artifact | all memory writes |
| `chapter_draft` | baseline + mutable + manuscript summaries + chapter outline | candidate artifact | all memory writes |
| `chapter_review` | baseline + mutable + manuscript summaries + draft | issue ledger + artifact index | canon writes |
| `memory_commit_chapter` | review + draft + outline | mutable + manuscript + artifact index | baseline |
| `volume_commit` | volume review + chapter commits | mutable + artifact index | baseline |
| `extension_commit` | extension review + proposal | mutable + artifact index | baseline/manuscript |

## 5. 实施计划

### 阶段一：计划与源报告落盘

完成标准：

- 本文档落盘。
- 明确本次只改写作专用配置和测试。

### 阶段二：写作记忆仓库细化

文件：

- `scripts/configure_writing_modular_novel_graph.py`
- `backend/tests/writing_modular_novel_graph_config_regression.py`

改动：

- 新增 `memory.writing.manuscript`。
- 细化 `baseline`、`mutable`、`manuscript`、`artifact_index`、`issue_ledger` collections。
- 更新工作记忆策略，让 `manuscript_memory` 成为显式库。

完成标准：

- 章节写手、细纲、审核、卷级节点能读 `manuscript`。
- 只有 `memory_commit_chapter`、`memory_finalize` 能写 `manuscript`。

### 阶段三：写前取材协议与提交 schema

文件：

- `scripts/configure_writing_modular_novel_graph.py`
- `backend/tests/writing_modular_novel_graph_config_regression.py`

改动：

- 为 `chapter_draft` 增加 `prewrite_memory_plan_policy`。
- 强化 `chapter_draft` prompt，要求正文前有写前取材记录，但最终产物仍必须以小说正文为主体。
- 强化 `chapter_review` prompt 和 policy，审核取材、正文、偏移、风格、连续性。
- 强化 `memory_commit_chapter` commit schema，要求章节摘要、人物状态 delta、世界细节 delta、伏笔状态、连续性索引、下一批取材清单。

完成标准：

- 测试能证明章节提交包不是泛化提交包。
- 写手不是依赖外部 RAG 随机检索，而是读取结构化记忆包并声明采用依据。

### 阶段四：设计并行与对齐 barrier

文件：

- `scripts/configure_writing_modular_novel_graph.py`
- `backend/tests/writing_modular_novel_graph_config_regression.py`

改动：

- `plot_design` 从依赖 `memory_commit_character` 改成依赖 `memory_commit_world`。
- `character_design` 与 `plot_design` 都进入 `design_sync`。
- `memory_commit_character` 在 `design_sync` 后执行，不再提前冻结未对齐人设。
- `baseline_memory_seed` 统一把对齐后的人设、剧情、细纲写入 baseline。

完成标准：

- 图结构上能看到角色候选与剧情候选并行，然后在 `design_sync` 等齐。
- 对齐前不把角色候选写入 baseline。

### 阶段五：设定增长协议

文件：

- `scripts/configure_writing_modular_novel_graph.py`
- `backend/tests/writing_modular_novel_graph_config_regression.py`

改动：

- 强化 `world_outline_extension_proposal`、`extension_review`、`extension_commit` 的 schema 和 prompt。
- 扩展提案必须拆成世界细节、角色状态、大纲线程、连续性修正、拒绝项。
- 动态提交必须保留来源、适用范围、有效期、是否可升级 baseline 的判断。

完成标准：

- 动态扩展不能静默覆盖冻结事实。
- 偏移处理有返修、动态吸收、上游重设三种明确裁决。

### 阶段六：生成与验证

命令：

```powershell
python .\scripts\configure_writing_modular_novel_graph.py
python -m pytest backend/tests/writing_modular_novel_graph_config_regression.py -q
python -m pytest backend/tests/task_artifact_materializer_regression.py backend/tests/chapter_draft_quality_gate_regression.py backend/tests/length_budget_contract_regression.py -q
```

完成标准：

- 写作图配置可生成。
- 写作图回归测试通过。
- 产物、质量门、长度预算测试不被破坏。

## 6. 风险控制

1. 如果现有运行时暂不支持一个 commit 节点写多个仓库，本次只在写作图 policy 和边上表达多目标提交，由测试验证图配置；不改通用后端为小说开特例。
2. 如果并行设计改动影响既有测试，优先修正测试和图结构，不回退到旧串行冻结模式。
3. 如果某个 prompt 必须出现题材词，只能以“来自项目硬设定时才可使用”的方式表达，不能作为通用默认类型资产。
4. 如果发现提交节点越权补写内容，必须收紧 prompt 和 schema，而不是让审核节点替它兜底。

