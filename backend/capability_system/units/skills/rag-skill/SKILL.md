---
name: rag-skill
metadata:
  display_name: 知识库问答
  supported_modalities:
    - text
    - document
    - knowledge
  supported_task_kinds:
    - knowledge_lookup
    - faq_explanation
  supported_source_kinds:
    - knowledge_base
  capability_tags:
    - knowledge_lookup
    - retrieval
    - local-knowledge
    - faq
    - grounded-answer
    - citation-aware
  preferred_route: rag
  forbidden_routes:
    - tool
  routing_hints:
    - 知识库
    - 本地资料
    - 本地文档
    - 内部资料
    - 查资料
    - 查一下
    - 根据资料
    - FAQ
    - 为什么
    - 解释一下
    - 说明一下
  examples:
    - 从本地知识库里查一下三一重工前三大股东
    - 根据内部资料解释一下这个产品的退款规则
    - 为什么我在我的帐户中找不到我的订单
    - 帮我从知识库里确认这个功能是否支持批量导出
description: 面向本地知识库、FAQ 和内部资料的检索问答工作流，适合做基于现有材料的事实确认、规则解释和可追溯回答。
---

# 知识库问答

## 角色

这是一个“基于已有资料回答”的工作流。它的任务不是自由发挥，而是优先从本地知识库、FAQ 和内部文档中找到依据，再给出可追溯的结论。

适合被唤起的情况：

- 用户明确提到知识库、本地资料、内部文档、FAQ、帮助中心、规则说明。
- 问题本质上是在确认一个事实、解释一个规则、核对一个产品能力、说明一个常见故障原因。
- 回答需要“根据现有材料来讲”，而不是依赖最新外部信息或临时计算。

不适合被唤起的情况：

- 用户要的是某个 PDF 的页级/章节级阅读，这应该交给 `pdf-analysis`。
- 用户要的是 Excel/CSV/JSON 的筛选、排序、汇总，这应该交给 `structured-data-analysis`。
- 用户问的是实时新闻、官网最新更新、当前行情、今天/今年是否还在发生，这应该交给 `realtime_network` 路线和 `web_search` / `fetch_url` 底座工具。

## 执行目标

1. 先确认问题是否真的需要“从已有资料中找答案”，再进入检索。
2. 优先召回最可能直接回答问题的条目，而不是泛化搜索大段相近内容。
3. 输出时先给结论，再给依据；如果依据不足，要明确说“不足以确认”。
4. 当问题像 FAQ 时，回答要简洁直接；当问题像规则说明时，要把适用条件一起说清楚。

## 回答要求

- 结论优先，不要先铺陈检索过程。
- 尽量保留来源感，比如“根据知识库说明”或“从现有资料看”。
- 有冲突证据时，不要强行合并，要说明冲突点。
- 没有足够依据时，不要补齐想象内容。

## 不要这样做

- 不要把“本地资料问答”退化成无依据的泛泛回答。
- 不要把实时外部问题硬解释成知识库问题。
- 不要把 PDF 深读、表格分析、代码阅读临时塞进这条链里兜底。
