---
name: gold-price
metadata:
  display_name: 黄金价格查询
  allowed_tools:
    - get_gold_price
  supported_modalities:
    - realtime
    - finance
  supported_task_kinds:
    - realtime_lookup
  supported_source_kinds:
    - external_web
  capability_tags:
    - gold_price
    - gold
    - xau
    - realtime
    - finance
    - spot-price
  preferred_route: tool
  forbidden_routes:
    - rag
  routing_hints:
    - 黄金
    - 金价
    - 现货黄金
    - XAU
    - XAUUSD
    - 实时黄金价格
  examples:
    - 查询黄金价格
    - 我要实时的黄金价格
    - XAU/USD 现在多少
description: 使用专用黄金价格工具查询现货黄金或 XAU/USD 的实时价格，并返回整理后的中文结果与来源。
---

# 黄金价格查询 Skill

## 角色

这是一个工作流契约，用于黄金现货价格与 XAU/USD 的实时查询任务。此类问题应优先调用 `get_gold_price`，而不是退回通用 `web_search`。

## 服务的任务

- `realtime_lookup`

## 服务的数据源

- `external_web`

## 使用原则

1. 用户询问黄金价格、金价、现货黄金、XAU/USD 时，优先调用 `get_gold_price`。
2. 回答应优先给出当前参考价格，其次给出来源与时间说明。
3. 如无法稳定抽取单一价格数字，应明确说明并给出可用来源，不要编造价格。

## 不要这样做

- 不要把黄金价格问题交给本地 RAG。
- 不要默认退回通用 `web_search` 并直接把原始搜索结果 JSON 返回给用户。
- 不要把股票代码、换汇页、无关贵金属页面当成黄金现货价格来源。
