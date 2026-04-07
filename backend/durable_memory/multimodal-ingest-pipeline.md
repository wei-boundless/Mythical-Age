---
schema_version: durable-memory.v2
title: 多模态资料入库前先解析清洗切分
summary: 多模态资料进入知识库前，应先解析、清洗、切分，再做 embedding 和索引。
canonical_statement: 多模态资料进入知识库前，应先解析、清洗、切分，再做 embedding 和索引。
type: workflow
memory_class: work
tags: [workflow, multimodal, rag, ingestion]
retrieval_hints: [多模态入库, multimodal ingestion, embedding 前处理, RAG 预处理]
created_at: 2026-04-05T00:00:00+00:00
updated_at: 2026-04-06T00:00:00+00:00
created_by: manual
source_session_id:
source_role: user
source_message_excerpt: 多模态资料入库前要先解析、清洗、切分，再做 embedding。
confidence: high
status: active
last_confirmed_at: 2026-04-05T00:00:00+00:00
---

## Canonical Memory

多模态资料进入知识库前，应遵循统一预处理流程：
1. 先解析原始文件内容。
2. 再做必要的清洗与去噪。
3. 然后进行结构化切分。
4. 最后再做 embedding 与索引构建。

## Retrieval Hints

- 多模态入库
- multimodal ingestion
- embedding 前处理
- RAG 预处理

## Why Stored

这是稳定的项目工作流约定。后续设计多模态入库、RAG 索引或文档预处理流程时，应默认遵循这条规则。

## Source Evidence

多模态资料入库前要先解析、清洗、切分，再做 embedding。
