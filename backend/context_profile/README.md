# Context Profile

`context_profile/` 是长期上下文系统中的静态提示词层，只保留两类正式内容：

- `agent_core/`
  - Agent 的高稳定原则与人格种子系统
  - `agent_core/CORE.md` 定义不随人格切换变化的底层原则
  - `agent_core/ACTIVE_SEED.md` 是当前正式生效的人格种子
  - `agent_core/seeds/` 存放可选人格模板
  - `agent_core/SEED_CATALOG.md` 说明各人格适用场景与切换方式
- `profile/`
  - 用户可长期维护的静态偏好
  - 当前正式入口为 `profile/agent.md`

不属于静态提示词的项目实现说明、工具开发协议、运行细节，不应继续放在这里，也不应进入系统提示词主链。

## 与其它记忆目录的关系

- `durable_memory/`
  - 动态长期记忆，按召回结果进入上下文
- `session-memory/`
  - 当前会话 working memory
- `sessions/`
  - 原始会话留档

## 运行时注入顺序

1. Agent Core
2. Active Soul Seed
3. Agent Profile
4. Dynamic Long-Term Memory
5. Session Memory
