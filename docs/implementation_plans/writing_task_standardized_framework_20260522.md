# 写作任务标准化框架

日期：2026-05-22

目标：把长篇写作流程从“节点串联”升级为“分层记忆 + 可扩展设定 + 可检索取材 + 审核后提交”的标准化体系。

## 1. 总原则

1. 世界观、人设、大纲、正文都要分层存储。
2. 候选、审核、提交、冻结、动态增量必须分开。
3. 写手先思考，再取材，再写正文。
4. 审核按硬边界裁决，不靠全文硬吃碰运气。
5. 设定可以增长，但只能受控增长。
6. 并行只放在可独立收敛的块上。

## 2. 记忆分层

### 2.1 Baseline

放长期冻结事实：

- 世界规则
- 空间层级
- 历史主轴
- 角色基准
- 关系边界
- 全书大纲基准

### 2.2 Mutable

放运行增量：

- 章节推进
- 卷级变化
- 连续性记录
- 伏笔回收状态
- 动态修正

### 2.3 Index

放检索索引：

- 产物引用
- 版本引用
- 人物引用
- 场景引用
- 卷/章范围引用

### 2.4 Issue Ledger

放问题与返修：

- 冲突
- 偏移
- 阻塞
- 返修指令
- 风险说明

## 3. 设定卡体系

### 3.1 世界观卡

每条世界观都要展开为可执行条目：

- 设定名称
- 所属层级
- 来源依据
- 存在原因
- 运行规则
- 影响范围
- 与主线关系
- 与人物关系
- 可制造的冲突
- 可提供的奖励
- 代价与限制
- 可埋伏笔
- 可回收方式
- 禁止误写
- 后续可扩展口

### 3.2 人设卡

每个核心人物至少包含：

- 身份
- 欲望
- 动机
- 能力边界
- 关系压力
- 情绪债
- 利益债
- 禁改项

### 3.3 剧情卡

每条剧情线至少包含：

- 目标
- 阻碍
- 转折
- 代价
- 兑现
- 余波
- 伏笔
- 回收窗口

### 3.4 章纲卡

每章必须说明：

- 本章目标
- 本章承接
- 本章冲突
- 本章信息释放
- 本章情绪回报
- 章末钩子
- 禁改边界

## 4. 标准流程

```text
project_brief
  -> world_spine_design
  -> world_element_expand
  -> world_playability_review
  -> world_commit
  -> character_design
  -> plot_design
  -> design_sync
  -> outline_design
  -> outline_review
  -> baseline_memory_seed
  -> volume_plan
  -> chapter_outline
  -> chapter_prewrite_planning
  -> memory_request_resolver
  -> chapter_draft
  -> chapter_review
  -> memory_commit_chapter
  -> chapter_progress_router
  -> volume_review
  -> volume_commit
  -> volume_postmortem
  -> world_outline_extension_proposal
  -> extension_review
  -> extension_commit
  -> next_volume_router
  -> final_assemble
  -> final_review
  -> memory_finalize
```

## 5. 并行规则

### 5.1 适合并行

- 世界观内部的子块扩展
- 人设设计与剧情设计
- 章节写前思考中的记忆需求识别
- 卷后复盘后的补充提案准备

### 5.2 不适合并行

- 已冻结世界观之后仍未对齐的人设和剧情主干
- 需要强连续叙事的正文批次
- 同一基准库的并发写入

### 5.3 汇合规则

- 并行产物必须在 `design_sync` 或同级 barrier 汇合
- 汇合后再进入冻结或动态提交
- 冲突优先进入 `issue_ledger`

## 6. 记忆整理员职责

记忆整理员只做四件事：

1. 提纯内容。
2. 分层入库。
3. 标注版本和范围。
4. 生成可检索索引。

它不做：

- 正文创作
- 世界扩写
- 裁决替代
- 临场补洞

## 7. 存储规范

推荐的逻辑目录：

```text
baseline/
mutable/
artifact_index/
issue_ledger/
```

### 7.1 Baseline

存冻结事实，不按轮次重复堆叠。

### 7.2 Mutable

存已成立的章节、卷级变化、扩展增量。

### 7.3 Artifact Index

只存引用，不存真相。

### 7.4 Issue Ledger

只存问题，不存正文事实。

## 8. 写手取材机制

写手要先做写前思考：

1. 这一章要写什么。
2. 需要哪些人物状态。
3. 需要哪些世界细节。
4. 需要哪些伏笔和承接。
5. 哪些东西不能改。

然后系统根据请求返回精确记忆包，再进入正文写作。

## 9. 审核机制

审核只做三类事：

- 检查是否符合硬边界
- 检查是否偏离基准
- 检查是否可以提交

审核不负责替设计师补写。

## 10. 最终结论

这套框架的核心不是“把所有东西写全”，而是：

- 世界观可生长
- 人设可推进
- 大纲可扩展
- 正文可取材
- 记忆可检索
- 偏差可回收
- 提交可追踪

这才是适合长篇商业写作的标准化流程。

## 11. 实时维护规则表

| 维护对象 | 触发时机 | 更新内容 | 更新层级 | 责任节点 |
|---|---|---|---|---|
| 世界观 | 新硬设定出现、扩展提案通过 | 设定条目、规则边界、场域细节、历史补充 | `baseline` 或 `mutable` | `world_review`、`memory_commit_world`、`extension_commit` |
| 人设 | 角色状态变化、关系推进、卷级复盘 | 身份、动机、关系压力、情绪债、禁改项 | `baseline` 或 `mutable` | `character_review`、`memory_commit_character`、`volume_commit` |
| 大纲 | 批次推进、卷级收束、剧情偏移修订 | 卷目标、章节批次、伏笔、回收窗口、节奏调整 | `baseline` 或 `mutable` | `outline_review`、`baseline_memory_seed`、`volume_postmortem` |
| 正文连续性 | 每章审核后、每批提交后 | 上章承接、当前状态、未闭合问题、下一批输入 | `mutable` | `chapter_review`、`memory_commit_chapter` |
| 产物索引 | 每次产物落盘后 | 文件引用、版本号、章节范围、角色引用、场景引用 | `artifact_index` | 所有落盘节点、整理员 |
| 问题台账 | 发现冲突、偏移、阻塞、返修 | 问题描述、风险等级、返修范围、处理状态 | `issue_ledger` | 审核节点、监测节点、整理员 |

### 11.1 更新原则

1. 先更新动态层，再决定是否升级为基准层。
2. 正文推进产生的新事实，默认先进 `mutable`。
3. 只有审核通过且稳定成立的内容，才进入 `baseline`。
4. 旧版本保留，不覆盖删除，统一标记 `superseded` 或 `archived`。
5. 任何偏移都先写入 `issue_ledger`，再决定返修、吸收或冻结。

### 11.2 维护节奏

```text
chapter_review
  -> 更新正文连续性
  -> 更新索引
  -> 写入问题台账
  -> 必要时触发返修

memory_commit_chapter
  -> 更新动态记忆
  -> 同步章节已成立事实

volume_review / volume_commit
  -> 更新卷级状态
  -> 更新人物关系变化
  -> 更新伏笔回收进度

volume_postmortem / extension_review / extension_commit
  -> 更新设定扩展
  -> 受控补强世界观或大纲
```
