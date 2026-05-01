---
name: web-search
metadata:
  display_name: 联网搜索
  allowed_tools:
    - web_search
  supported_modalities:
    - web
  supported_task_kinds:
    - web_lookup
  supported_source_kinds:
    - external_web
  capability_tags:
    - search
    - news
    - finance
    - official-docs
  preferred_route: tool
  forbidden_routes:
    - rag
  routing_hints:
    - 联网
    - 搜索
    - 最新
    - 新闻
    - 官网
    - 实时
  examples:
    - 帮我联网查 OpenAI API 最新更新
description: 使用联网搜索获取最新信息、官方文档、新闻动态、实时行情和外部事实来源。
---

# 联网搜索 Skill

## 角色

这是一个工作流契约，用于通用外部检索与最新资料查询，把任务交给 `web_search`，而不是让模型假装知道最新情况。

## 服务的任务

- `web_lookup`

## 服务的数据源

- `external_web`

## 使用原则

1. 用户明确要求联网、搜索、查官网、查最新信息时，优先调用 `web_search`。
2. 对新闻、行情、官方文档类问题，要保留时间说明。
3. 回答时先给结论，再给依据和来源。

## 不要这样做

- 不要把实时外部信息问题交给本地 RAG。
- 不要吞掉已经有专用工具的单点能力，比如天气、黄金价格。
- 不要假装联网成功。
- 不要把低质量搜索摘要当成最终结论。
