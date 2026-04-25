---
name: rag-skill
metadata:
  display_name: 知识库问答
  allowed_tools:
    - search_knowledge
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
    - rag
    - retrieval
    - local-knowledge
    - faq
  preferred_route: rag
  forbidden_routes:
    - tool
  routing_hints:
    - 知识库
    - 本地资料
    - 查资料
    - FAQ
    - 为什么
  examples:
    - 为我讲讲 AI 吧，你的数据库里有不少 AI 知识吧
    - 从本地知识库里查一下三一重工前三大股东
    - 为什么我在我的帐户中找不到我的订单
description: 面向本地知识库目录的检索和问答能力，适合事实查询、FAQ 解释和基于本地文档的可追溯回答。
---

# 知识库问答 Skill

## 角色

这是一个知识问答工作流契约，不再承担 PDF 阅读或结构化数据分析的职责。它只负责把知识库问答任务稳定交给 RetrievalWorker / evidence worker。

## 服务的任务

- `knowledge_lookup`
- `faq_explanation`

## 服务的数据源

- `knowledge_base`

## 使用原则

1. 问题是在问本地资料、知识库、FAQ 或文档事实时，优先走这条链。
2. 先定位来源，再回答；回答要尽量基于知识库证据。
3. 遇到 PDF 单页阅读或表格分析需求时，应交给各自的专门 skill，而不是在本 skill 内兜底。

## 不要这样做

- 不要把实时外部信息问题交给本地知识库。
- 不要把结构化分析问题误当成普通文档问答。
- 不要默认调用 `analyze_multimodal_file`、`index_multimodal_file` 或 `read_file` 作为常规路径。
