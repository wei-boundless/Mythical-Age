---
name: retry-lesson-capture
metadata:
  display_name: 重试经验沉淀
  allowed_tools:
    - read_file
  supported_modalities:
    - workflow
  supported_task_kinds:
    - workflow_lesson_capture
  supported_source_kinds:
    - workflow
  capability_tags:
    - lesson
    - retry
    - durable-memory
  preferred_route: internal
  forbidden_routes: []
  routing_hints:
    - 失败后成功
    - 经验教训
    - 沉淀
  examples:
    - 第一次失败，改参数后成功，帮我沉淀经验
description: 当任务首轮失败、调整后成功时，提炼可复用经验，并写回当前 skill 或 durable memory。
---

# 重试经验沉淀 Skill

## 角色

这是一个内部工作流契约，用于把“失败 -> 调整 -> 成功”的经验沉淀成可复用资料。

## 服务的任务

- `workflow_lesson_capture`

## 服务的数据源

- `workflow`

## 使用原则

1. 只有在首轮失败、后续修正成功且经验可复用时，才沉淀。
2. 如果经验只对某个 skill 有意义，优先更新对应 `SKILL.md` 或 reference。
3. 如果经验属于长期项目规则，写入 durable memory。

## 不要这样做

- 不要把偶然现象沉淀成长期规则。
- 不要机械复制整段日志。
- 不要在尚未成功时提前总结“经验”。
