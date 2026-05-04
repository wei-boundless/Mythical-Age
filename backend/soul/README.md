# Soul

`soul/` 现在已经是正式的灵魂系统目录。
它管理静态身份素材、SoulProfile、Projection、prompt sections、skills/tools 可见视图和运行时身份装配。

这里放的不是运行日志，也不是实现说明，而是会参与模型长期行为塑形的静态设定和后续灵魂契约。

这个目录里正式保留一类运行时 prompt 内容：

- `agent_core/`
  - `ACTIVE_SEED.md`：当前真正进入模型的那一份人格设定
  - `CORE.md`：接在当前人格设定后面的共同契约，承载通用底线、稳定协作偏好和项目口径
  - `seeds/`：候选 seed 仓库，只给人看，不直接进入运行时
  - `SEED_CATALOG.md`：候选 seed 的说明文档，只给人看

不属于静态 prompt 的项目实现说明、工具开发协议和运行细节，不应该继续放在这里。

## 静态注入契约

只有下面两个文件会进入静态 prompt 主链：

1. `agent_core/ACTIVE_SEED.md`
2. `agent_core/CORE.md`

下面这些文件不会进入模型可见 prompt：

- `README.md`
- `agent_core/SEED_CATALOG.md`
- `agent_core/seeds/*.md`

下面这些实现文件也不直接进入模型可见 prompt；它们只负责把灵魂档案装配成受控的 `SoulRuntimeView`：

- `contracts.py`
- `registry.py`
- `projection_builder.py`
- `runtime_assembly.py`
- `view_mapping.py`
- `prompt_assembly.py`

## 模型实际读到的顺序

模型看到静态层时，顺序是：

1. `ACTIVE_SEED.md`
2. `CORE.md`

这个顺序的含义是：

- 先让模型进入“当前这一次的人格设定”
- 再补上“不管当前风格是什么，都不能越过的共同契约”，包括事实底线、输出边界、暴露限制、稳定协作偏好和项目口径

对模型来说，它只会读到当前这一份 `ACTIVE_SEED.md`。
它不会同时读到 `seeds/` 目录里的其它候选版本，也不需要知道候选仓库的存在。

## Core / Seed 分工

### `ACTIVE_SEED.md`

负责当前人格 prompt，本质上是在定义：

- 你现在是谁
- 你平时怎么说
- 你默认怎么处理问题
- 你最容易偏到哪里，所以要特别防什么

### `CORE.md`

负责通用底线，本质上是在定义：

- 你怎么处理事实
- 你怎么控制输出
- 你怎么约束执行
- 你哪些内容不能往外暴露

`CORE.md` 不负责定义风格，也不负责抢走当前 seed 的主导权。
用户或项目长期想固定下来的协作偏好、项目口径和表达约束，也进入 `CORE.md`，但应写成共同契约，而不是写成某个灵魂的人格风格。

## 适合写进 `CORE.md` 的内容

- 所有情况下都必须成立的工作底线
- 事实原则
- 输出原则
- 暴露限制
- 高风险情况下的通用收边界方式

一句话说，`CORE.md` 负责把 agent 做稳。

## 不适合写进 `CORE.md` 的内容

- 当前这一次的人格身份
- 当前的语气、节奏和称呼
- 当前更偏先讲框架还是先讲动作
- 当前更偏收束、拆解、推进还是辨析

这些内容都应该交给 seed。

## 适合写进 `ACTIVE_SEED.md / seeds/*.md` 的内容

- 身份锚点
- 语言风格
- 工作习惯
- 语言组织方式
- 特定约束

一句话说，seed 负责把 agent 做活。

## 判断规则

如果一条内容满足下面任一条件，优先进入 `CORE.md`：

- 不管当前人格是什么，都必须遵守
- 一旦变化，会破坏事实边界、输出边界或执行稳定性
- 它描述的是底线，不是偏好
- 它是用户或项目长期想固定下来的稳定协作偏好或项目口径

如果一条内容满足下面任一条件，优先进入 `seed`：

- 它描述的是当前默认偏好，而不是底线
- 它改变的是说话方式、处理方式或组织方式
- 换一份人格设定后，这条内容本来就应该变化

## 新架构方向

灵魂系统现在不再只是人格切换器。

目标是：

- `SoulProfile` 管理灵魂身份、背景、风格、工作习惯和偏好。
- `SoulProjection` 根据任务、AgentProfile、SkillScope、ToolScope 生成当前运行时视图。
- `SoulRuntimeView` 作为最终 prompt 装配输入。
- `PromptManifest` 记录每段 prompt 的来源。
- tools / skills 可以进入灵魂视图，但授权仍然由 `ControlKernel / ResourcePolicy` 决定。

当前正式设计与收口审查见：

- `docs/系统规划/06-灵魂系统详细设计书-20260504.md`
- `docs/系统规划/22-第六阶段灵魂系统正式收口与身份装配重构蓝图-20260504.md`
- `docs/系统规划/23-第六阶段灵魂系统正式收口源码对照审查-20260504.md`
- `docs/系统规划/24-第六阶段灵魂系统收口后框架与设计原则对照审查-20260504.md`
