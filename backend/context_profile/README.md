# Context Profile

`context_profile/` 是长期上下文系统中的静态层，用来承载高稳定性的设定与长期画像。

## 目录职责

- `constitution/`
  - 系统设定、角色身份、稳定原则
  - 例如 `SOUL.md`、`IDENTITY.md`
- `profile/`
  - 用户长期偏好、项目长期画像、协作默认值
  - 例如 `USER.md`、`AGENTS.md`

## 与其它记忆目录的关系

- `durable_memory/`
  - 动态长期记忆
  - 用于 durable facts、可复用工作约定、可整理的长期 note
- `session-memory/`
  - 当前会话 working memory
- `sessions/`
  - 原始会话留档

## 运行时注入顺序

1. Constitution
2. Profile
3. Dynamic Long-Term Memory
4. Session Memory

`workspace/` 已不再作为长期上下文的正式目录。
