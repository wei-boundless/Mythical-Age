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
    - document_browse
    - document_deep_read
    - document_page_read
  supported_source_kinds:
    - document
  capability_tags:
    - pdf
    - browse
    - deep-read
    - page-read
  preferred_route: tool
  forbidden_routes:
    - rag
  routing_hints:
    - 白皮书
    - 报告
    - PDF
    - 第几页
    - 详细解读
  examples:
    - 这份白皮书主要讲什么
    - 第五页讲得什么
    - 详细解读这份 PDF
description: 用于本地 PDF 文件的泛读、精读和单页阅读，适合回答“这份 PDF 主要讲什么”“第几页讲什么”等问题。
---

# PDF 阅读分析 Skill

## 角色

这是一个文档阅读工作流契约。它负责承接 PDF 相关任务，并把执行交给 `pdf_analysis`。

## 服务的任务

- `document_browse`
- `document_deep_read`
- `document_page_read`

## 服务的数据源

- `document`

## 使用原则

1. 用户问某一页时，优先 `page_read`。
2. 用户问整份 PDF 核心内容时，优先 `browse`。
3. 用户要求详细解读、通读、分段总结时，优先 `deep_read`。

## 辅助资料

- `references/pdf_reading.md`

## 不要这样做

- 不要把“详细解读 PDF”退化成普通 top-k RAG。
- 不要用表格工具处理 PDF。
- 不要把工具的原始抽取噪声直接当最终回答。
