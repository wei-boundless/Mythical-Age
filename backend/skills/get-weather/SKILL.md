---
name: get-weather
metadata:
  display_name: 天气查询
  allowed_tools:
    - get_weather
  supported_modalities:
    - realtime
  supported_task_kinds:
    - realtime_lookup
  supported_source_kinds:
    - external_web
  capability_tags:
    - weather
    - forecast
    - realtime
  preferred_route: tool
  activation_policy: model_visible
  context_mode: inline
  route_authority: candidate_only
  forbidden_routes:
    - rag
  routing_hints:
    - 天气
    - 气温
    - 温度
    - 预报
    - 下雨
  examples:
    - 北京今天天气怎么样
    - 上海明天气温多少
description: 查询指定地点的实时天气或短期天气情况，并整理成适合直接回复用户的中文结果。
---

# 天气查询 Skill

## 角色

这是一个工作流契约，不负责自己“理解世界”，只负责把天气类任务稳定交给 `get_weather`。

## 服务的任务

- `realtime_lookup`

## 服务的数据源

- `external_web`

## 使用原则

1. 用户明确在问天气、温度、风力、降雨、预报时，优先使用 `get_weather`。
2. 输出应直接面向用户，简洁说明地点、天气、温度和时间。
3. 如果工具失败，要明确说明失败，而不是假装查到了天气。

## 不要这样做

- 不要把天气问题交给知识库检索。
- 不要把工具说明原样展示给用户。
- 不要为了查天气临时改用 `python_repl` 或 `terminal`。
