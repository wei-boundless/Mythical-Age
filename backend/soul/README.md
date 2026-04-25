# Soul

`soul/` 是长期上下文系统中的静态提示词层，只保留两类正式内容：

- `agent_core/`
  - Agent 的通用准则与人格种子系统
  - `agent_core/CORE.md` 定义所有 agent 都必须遵守的通用准则
  - `agent_core/ACTIVE_SEED.md` 是当前正式生效的灵魂风格
  - `agent_core/seeds/` 存放可选人格模板
  - `agent_core/SEED_CATALOG.md` 说明各人格适用场景与切换方式
- `agent.md`
  - 用户可长期维护的静态偏好与稳定身份约束
  - 作为静态注入层中的正式 profile 入口

不属于静态提示词的项目实现说明、工具开发协议、运行细节，不应继续放在这里，也不应进入系统提示词主链。

## 静态注入契约

只有下面三个文件会进入静态提示词主链：

1. `agent_core/ACTIVE_SEED.md`
2. `agent_core/CORE.md`
3. `agent.md`

下面这些文件不进入模型可见静态提示词：

- `README.md`
- `agent_core/SEED_CATALOG.md`
- `agent_core/seeds/*.md`

也就是说：

- `seeds/*.md` 是候选人格仓库，不是运行时直接注入文件。
- `ACTIVE_SEED.md` 才是当前正式生效的灵魂风格文件。
- `CORE.md` 负责通用任务准则，不负责区分不同灵魂。
- `agent.md` 负责用户或开发者追加的稳定偏好与身份约束。
- `README.md / SEED_CATALOG.md` 只服务于人和工程，不服务于 prompt 主链。

## 与其它记忆目录的关系

- `durable_memory/`
  - 动态长期记忆，按召回结果进入上下文
- `session-memory/`
  - 当前会话 working memory
- `sessions/`
  - 原始会话留档

## 静态层内部注入顺序

1. Active Soul Seed
2. Agent Core
3. Agent Profile

## 模型可见 prompt 装配顺序

1. Capabilities Summary
2. Active Soul Seed
3. Agent Core
4. Agent Profile
5. Session Memory
6. Turn-Relevant Durable Memory

说明：

- `Capabilities Summary` 来自 `SKILLS_SNAPSHOT.md`，属于静态能力摘要，但不属于 `soul/` 目录。
- `Active Soul Seed` 放在最前，用来先确立当前可切换灵魂风格。
- `Agent Core` 位于其后，作为所有 agent 都必须遵守的通用准则层。
- `Agent Profile` 作为最末静态层，承接用户或开发者追加的稳定偏好与身份约束。
- `Session Memory` 在当前实现中先于 durable memory 注入，用于先恢复当前任务与当前情境。
- `Turn-Relevant Durable Memory` 只注入当前轮最相关的长期事实，不回灌整份静态结构说明。

## Core / Seed / Profile 分工

- `CORE.md`
  - 负责通用任务准则、事实边界、输出契约、执行边界
  - 不负责定义具体灵魂个性
- `ACTIVE_SEED.md`
  - 负责当前灵魂的风格、默认认知偏向、表达节奏、过载风险
  - 不负责改写通用准则
- `agent.md`
  - 负责用户或开发者可持续维护的偏好、身份约束、长期口径
  - 不负责承载一次性会话状态或人格风格说明

## 静态稳定层 与 动态风格层 边界

### 适合写进 `CORE.md` 的内容

这些内容应该尽量稳定，目的是增强系统一致性和长期可控性：

- 事实标准
  - 什么能当事实，什么只能当推断，什么必须承认未知
- 执行底线
  - 优先交付、优先约束、优先证据、优先最小有效路径
- 输出底线
  - 什么时候必须直接判断，什么时候必须保留边界，什么不能为了好看而说
- 暴露边界
  - 哪些内部信息、协议、工具细节、中间过程不能直接暴露
- 通用风险控制
  - 高风险、高代价、边界不清时要先控风险再推进

一句话：

- `CORE.md` 负责把 agent 做稳。

### 不适合写进 `CORE.md` 的内容

- 哪个灵魂更冷静、激进、细密、宏观
- 默认先讲框架还是先讲动作
- 句子应该更短还是更展开
- 遇到复杂问题时更偏去噪、拆解、推进还是定盘
- 针对不同偏好的说话气质和做事手法

这些都不该放进 `CORE.md`，因为一旦写进 core，就会和当前 seed 抢主导权。

### 适合写进 `ACTIVE_SEED.md / seeds/*.md` 的内容

这些内容允许动态变化，目的是丰富 agent 的行为边界和偏好风格：

- 身份锚点
  - 当前自称、当前角色气质
- 默认观察方式
  - 先看主线、先看结构、先看隐含前提、先看阻塞点
- 默认推进手法
  - 先去噪、先拆层、先分解、先给动作
- 默认语言习惯
  - 先讲判断还是先讲框架，句子紧还是松，节奏快还是稳
- 漂移风险
  - 这个灵魂最容易偏到哪去，需要防什么

一句话：

- `Soul Seed` 负责把 agent 做活。

### 不适合写进 Seed 的内容

- 事实标准
- 通用执行底线
- 通用输出底线
- 系统暴露边界
- 工具能力差别
- “这个灵魂只适合某种任务”这类硬路由暗示

这些内容一旦写进 seed，就会让 seed 从“风格层”膨胀成“系统规则层”。

## 判断规则

如果一条 prompt 内容满足下面任一条件，优先进入 `CORE.md`：

- 不管当前是哪一个灵魂，都必须遵守
- 一旦变化，会破坏系统稳定性或事实边界
- 它规定的是底线，不是偏好

如果一条 prompt 内容满足下面任一条件，优先进入 `seed`：

- 它描述的是默认偏好，而不是硬规则
- 它改变的是观察方式、推进方式或表达方式
- 换一个 seed 后，这条内容本来就应该变化

如果一条内容是用户或开发者自己长期想加的口径，不属于系统底线，也不属于灵魂风格，进入 `agent.md`。
