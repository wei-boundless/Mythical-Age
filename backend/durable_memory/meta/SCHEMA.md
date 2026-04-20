# Durable Memory Schema

## Purpose

`durable_memory/notes/*.md` 是跨会话长期记忆的真相源。

每条 note 分成三部分：

1. 语义内容
   - `title`
   - `summary`
   - `canonical_statement`
   - `body`

2. 检索辅助
   - `type`
   - `memory_class`
   - `tags`
   - `retrieval_hints`

3. 治理与来源
   - `schema_version`
   - `created_at`
   - `updated_at`
   - `created_by`
   - `source_kind`
   - `source_session_id`
   - `source_role`
   - `source_message_excerpt`
   - `confidence`
   - `status`
   - `last_confirmed_at`
   - `scope`
   - `stability`
   - `eligible_for_injection`
   - `review_after`
   - `supersedes`
   - `invalidation_reason`

## Field Guidelines

- `summary`
  - 面向索引与概览的一句话摘要。

- `canonical_statement`
  - 面向系统消费的稳定表述。
  - 应尽量去掉上下文依赖和模糊指代。

- `retrieval_hints`
  - 用于补充 tags 不足以覆盖的检索别名、常见问法或术语变体。

- `confidence`
  - 表示这条长期记忆的稳定性判断，而不是模型置信度。
  - 推荐值：`high` / `medium` / `low`

- `status`
  - 表示运行时是否应继续参与长期记忆注入。
  - 推荐值：`active` / `inactive` / `archived` / `deprecated`

- `scope`
  - 表示这条 durable note 的作用域。
  - 推荐值：`user` / `project` / `agent` / `shared`

- `stability`
  - 表示这条 durable note 是稳定事实还是暂时保留的 provisional 事实。
  - 推荐值：`stable` / `provisional`

- `eligible_for_injection`
  - 表示这条 durable note 在运行时是否允许继续参与 relevant selection。
  - 推荐值：`true` / `false`

- `source_kind`
  - 表示 durable note 的来源类型。
  - 推荐值：`preference` / `correction` / `policy` / `reference` / `derived_summary`

- `supersedes`
  - 表示当前 note 替代了哪条旧 note。

- `invalidation_reason`
  - 当 note 被降级、停用或 supersede 时，记录原因。

## Recommended Body Layout

```md
## Canonical Memory
<stable statement or normalized workflow>

## Retrieval Hints
- hint 1
- hint 2

## Why Stored
<why this deserves durable retention>

## Source Evidence
<short excerpt from the originating message or seed rationale>
```
