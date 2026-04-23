---
name: pdf-analysis
metadata:
  display_name: PDF 阅读分析
  allowed_tools:
    - pdf_analysis
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
    - pdf
    - document
    - section
    - page
  preferred_route: tool
  activation_policy: model_visible
  context_mode: isolated
  route_authority: candidate_only
  forbidden_routes:
    - rag
  routing_hints:
    - 白皮书
    - 报告
    - PDF
    - 第几页
    - 章节
  examples:
    - 这份白皮书主要讲什么
    - 第五页讲得什么
    - 第二部分强调了什么
description: 用于本地 PDF 文件的文档级、章节级和页级阅读分析，适合回答“这份 PDF 主要讲什么”“某一章讲什么”“第几页讲什么”等问题。
---

# PDF 阅读分析 Skill

## 角色

这是一个文档阅读工作流契约。它负责承接 PDF 相关任务，并把执行交给 `pdf_analysis`。

## 服务的任务

- `document_read`
- `document_section`
- `document_page`

## 服务的数据源

- `document`

## 使用原则

1. 用户问某一页时，优先页级约束。
2. 用户问某一章、某一部分时，优先章节约束。
3. 用户问整份 PDF 核心内容时，走文档级主链路，不再区分“泛读 / 精读”。

## 辅助资料

- `references/pdf_reading.md`

## 不要这样做

- 不要把“详细解读 PDF”退化成普通 top-k RAG。
- 不要用表格工具处理 PDF。
- 不要把工具的原始抽取噪声直接当最终回答。
- 不要继续把 `browse / deep_read / page_read` 当成正式产品模式扩展。
