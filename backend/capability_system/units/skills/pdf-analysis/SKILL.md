---
name: pdf-analysis
metadata:
  display_name: PDF 阅读分析
  supported_modalities:
    - pdf
    - document
  supported_task_kinds:
    - document_read
    - document_section
    - document_page
  supported_source_kinds:
    - document
  capability_tags:
    - document_analysis
    - pdf
    - document
    - section
    - page
    - longform-reading
    - page-grounded
  preferred_route: pdf
  activation_policy: model_visible
  context_mode: isolated
  route_authority: candidate_only
  forbidden_routes:
    - rag
  routing_hints:
    - 白皮书
    - 报告
    - PDF
    - 手册
    - 论文
    - 第几页
    - 章节
    - 这一页
    - 这一部分
    - 核心结论
  examples:
    - 这份白皮书主要讲什么
    - 第五页讲得什么
    - 第二部分强调了什么
    - 把这份 PDF 的核心结论压成三条行动建议
description: 用于本地 PDF 的整篇阅读、章节定位和页级问答，适合回答“这份文档讲什么”“这一部分讲什么”“第几页写了什么”等深读问题。
---

# PDF 阅读分析

## 角色

这是一个“面向单个 PDF 的定向阅读”工作流。它应该在用户已经锁定某份 PDF，或者问题明显针对页码、章节、某一部分内容时被唤起。

适合被唤起的情况：

- 用户点名某个 PDF、报告、白皮书、手册、论文。
- 用户问“第几页讲了什么”“第二部分强调了什么”“这份文档核心观点是什么”。
- 会话里已经有激活的 PDF 绑定，用户继续追问“这一页”“这一部分”“这份 PDF”。

不适合被唤起的情况：

- 用户只是想在知识库里查一个事实，这应交给 `rag-skill`。
- 用户要算表格、统计数据、做排序分组，这应交给 `structured-data-analysis`。
- 用户问外部最新信息、官网更新、实时情况，这应交给 `realtime_network` 路线和 `web_search` / `fetch_url` 底座工具。

## 执行目标

1. 先判断问题是页级、章节级还是整篇级，再选择对应阅读粒度。
2. 尽量围绕一个明确文档回答，不要把 PDF 深读退化成普通相似段落检索。
3. 当用户问的是“这页/这段写了什么”，回答要贴近原意，不要过度抽象。
4. 当用户问的是“整份文档主要讲什么”，回答要先给主题，再提关键结构和结论。

## 辅助资料

- `references/pdf_reading.md`

## 回答要求

- 页级问题优先保留定位感，说明是基于哪一页或哪一部分。
- 总览问题优先给摘要，再给重要章节或结论。
- 有明显 OCR 噪声或抽取不完整时，要提示不确定性。
- 遇到图表、附录、脚注等边缘内容，不要把局部细节误讲成全文中心。

## 不要这样做

- 不要把 PDF 深读退化成泛泛的知识库问答。
- 不要在没有文档锚点时假装自己已经定位到了具体页或章节。
- 不要把抽取原文大段照搬成最终回答。
